"""Vozes prontas do roteiro de gravação (migração 020).

A LawChat grava uma vez (voz de IA ou da equipe) os áudios de cada parte do roteiro em algumas vozes
(ex.: "Clara — acolhedora"). Superadmin (Admin › Produtos › Roteiros › Vozes prontas): cria as vozes e sobe o áudio de
cada parte. Numa parte de vídeo (vídeo inicial) a voz pode trazer um ÁUDIO de boas-vindas no lugar do vídeo.

Escritório que não quer gravar: escolhe a voz, ouve, marca o aceite e usa. Cada áudio vira um item da biblioteca de
mídia dele (pasta "Roteiros prontos/<voz>", tag voz_pronta) ligado à parte como uma gravação (origem 'pronta'); o resto
(sugestão na ativação, Confirmar, preenchimento do prompt) funciona igual. O arquivo é da LawChat e compartilhado:
o item tem caminho_storage nulo, então apagar da biblioteca nunca apaga o arquivo, e ele não conta na cota de 200 MB.
A gravação própria sempre vale mais: usar a voz de novo não passa por cima dela (a não ser com substituir_minhas).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import tempfile
import uuid
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app import armazenamento
from app.gestao.produtos import LIMITES_POR_TIPO, _linha, _pool, apagar_midia, slugificar
from app.gestao.rotas import ADMIN, GESTAO, Contexto
from app.gestao.rotas_roteiro_gravacao import (CHAVE_POS_ASSINATURA, Arquivo, _decodificar, _exigir_liberado, _formato,
                                               _partes, _pos_assinatura, _produto, _uuid, chave_da_parte, normalizar,
                                               preparar_arquivo)

api = APIRouter(prefix="/api")

SEM_TABELA = ("As vozes prontas ainda não estão no banco: aplique a migração "
              "db/migracoes/020_agentesia_vozes_prontas.sql (depois da 019).")
TEXTO_ACEITE = ("Entendo que estes áudios são modelos da LawChat, feitos com voz de inteligência artificial ou da equipe, "
                "e usados também por outros escritórios. Eles não falam o nome do meu escritório; o de honorários fala um "
                "valor padrão, que eu confiro antes de usar. Posso trocar qualquer um pela minha própria gravação quando "
                "quiser.")
PREFIXO = "vozes-prontas/"
MIMES = {"ogg": "audio/ogg", "mp3": "audio/mpeg", "m4a": "audio/mp4", "mp4": "video/mp4"}
_COLUNAS_VOZ = "id, nome, tom, genero, origem, descricao, ativo, ordem, criado_em, atualizado_em"


async def _q(pedido: Request, metodo: str, sql: str, *args: Any) -> Any:
    """Consulta com 503 claro quando a 020 (ou a 019) não está aplicada."""
    try:
        return await getattr(_pool(pedido), metodo)(sql, *args)
    except (asyncpg.UndefinedTableError, asyncpg.UndefinedColumnError) as erro:
        raise HTTPException(503, SEM_TABELA) from erro


def _pasta_da_voz(nome: str) -> str:
    # "/" no nome da voz viraria uma subpasta que não existe na biblioteca.
    return "Roteiros prontos/" + (re.sub(r"\s*[/\\]+\s*", " - ", nome or "").strip() or "Voz")


async def _duracao(bruto: bytes, extensao: str) -> float | None:
    """Duração em segundos pelo ffprobe. None se não der (sem ffprobe ou arquivo que ele não lê)."""
    if shutil.which("ffprobe") is None:
        return None
    with tempfile.TemporaryDirectory(prefix="lawchat-dur-") as pasta:
        origem = os.path.join(pasta, f"entrada.{extensao}")
        with open(origem, "wb") as arquivo:
            arquivo.write(bruto)
        try:
            processo = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", origem,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            saida, _ = await asyncio.wait_for(processo.communicate(), timeout=30)
        except (OSError, asyncio.TimeoutError):
            return None
        if processo.returncode != 0:
            return None
        try:
            valor = float((json.loads(saida or b"{}").get("format") or {}).get("duration"))
        except (TypeError, ValueError):
            return None
    return round(valor, 2) if 0 <= valor < 36000 else None


async def _apagar_arquivo(pedido: Request, url: str | None, caminho: str | None) -> None:
    """Tira do armazenamento o arquivo de uma voz pronta. Só caminhos de vozes-prontas/ e só se nenhuma biblioteca de
    escritório ainda aponta para o link (quem já usou continua com o áudio tocando). Falha não trava a tela."""
    if not url or not caminho or not caminho.startswith(PREFIXO) or ".." in caminho:
        return
    if await _pool(pedido).fetchval("select 1 from agentesia_biblioteca_midia where url = $1 limit 1", url):
        return
    origem = armazenamento.de_uma_midia(url)
    if origem is None:
        return
    try:
        await origem.apagar(caminho)
    except (armazenamento.ErroArmazenamento, OSError) as erro:
        armazenamento.log.warning("áudio de voz pronta não saiu do armazenamento (%s): %s", caminho, type(erro).__name__)


# ======================================================================================================= superadmin
class VozNova(BaseModel):
    nome: str = Field(min_length=1, max_length=80)
    tom: str | None = Field(default=None, max_length=80)
    genero: str | None = Field(default=None, pattern="^(feminina|masculina)?$")
    origem: str | None = Field(default=None, pattern="^(ia|equipe)$")
    descricao: str | None = Field(default=None, max_length=1000)
    ordem: int | None = None


class VozMudar(BaseModel):
    nome: str | None = Field(default=None, min_length=1, max_length=80)
    tom: str | None = Field(default=None, max_length=80)
    genero: str | None = Field(default=None, pattern="^(feminina|masculina)?$")
    origem: str | None = Field(default=None, pattern="^(ia|equipe)$")
    descricao: str | None = Field(default=None, max_length=1000)
    ordem: int | None = None
    ativo: bool | None = None


def _texto(valor: str | None) -> str | None:
    return (valor or "").strip() or None


@api.get("/admin/vozes-prontas")
async def listar_vozes(pedido: Request, _: Contexto = Depends(ADMIN)) -> list[dict[str, Any]]:
    linhas = await _q(pedido, "fetch",
                      f"""select {', '.join('v.' + c.strip() for c in _COLUNAS_VOZ.split(','))},
                                 (select count(*)::int from agentesia_voz_pronta_audios a where a.id_voz = v.id) as audios,
                                 (select count(distinct g.id_escritorio)::int from agentesia_roteiro_gravacoes g
                                   where g.id_voz = v.id) as escritorios
                            from agentesia_vozes_prontas v order by v.ordem, v.criado_em""")
    return [_linha(l) for l in linhas]  # type: ignore[misc]


async def _voz(pedido: Request, id_voz: str, so_ativa: bool = False) -> dict[str, Any]:
    linha = await _q(pedido, "fetchrow", f"select {_COLUNAS_VOZ} from agentesia_vozes_prontas where id = $1::uuid"
                     f"{' and ativo' if so_ativa else ''}", _uuid(id_voz, "Voz"))
    if not linha:
        raise HTTPException(404, "Voz não encontrada.")
    return _linha(linha)  # type: ignore[return-value]


@api.post("/admin/vozes-prontas")
async def criar_voz(dados: VozNova, pedido: Request, _: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    nome = dados.nome.strip()
    if not nome:
        raise HTTPException(400, "Dê um nome para a voz.")
    ordem = dados.ordem
    if ordem is None:
        ordem = await _q(pedido, "fetchval", "select coalesce(max(ordem), 0) + 10 from agentesia_vozes_prontas")
    linha = await _q(pedido, "fetchrow",
                     f"""insert into agentesia_vozes_prontas (nome, tom, genero, origem, descricao, ordem)
                         values ($1, $2, $3, $4, $5, $6) returning {_COLUNAS_VOZ}""",
                     nome, _texto(dados.tom), _texto(dados.genero), dados.origem or "ia", _texto(dados.descricao), ordem)
    return _linha(linha)  # type: ignore[return-value]


@api.patch("/admin/vozes-prontas/{id_voz}")
async def mudar_voz(id_voz: str, dados: VozMudar, pedido: Request, _: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    mudancas = dados.model_dump(exclude_unset=True)
    for campo in ("tom", "genero", "descricao"):            # "" limpa o campo
        if campo in mudancas:
            mudancas[campo] = _texto(mudancas[campo])
    if "nome" in mudancas:
        if not _texto(mudancas["nome"]):
            raise HTTPException(400, "Dê um nome para a voz.")
        mudancas["nome"] = mudancas["nome"].strip()
    for campo in ("nome", "origem", "ordem", "ativo"):      # não aceitam nulo
        if campo in mudancas and mudancas[campo] is None:
            del mudancas[campo]
    if not mudancas:
        raise HTTPException(400, "Nada para mudar.")
    sets = ", ".join(f"{k} = ${i}" for i, k in enumerate(mudancas, 2))
    linha = await _q(pedido, "fetchrow", f"update agentesia_vozes_prontas set {sets}, atualizado_em = now() "
                     f"where id = $1::uuid returning {_COLUNAS_VOZ}", _uuid(id_voz, "Voz"), *mudancas.values())
    if not linha:
        raise HTTPException(404, "Voz não encontrada.")
    return _linha(linha)  # type: ignore[return-value]


@api.delete("/admin/vozes-prontas/{id_voz}")
async def apagar_voz(id_voz: str, pedido: Request, _: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    """Apaga a voz e os arquivos dela. Voz em uso (gravação de algum escritório, ou item da biblioteca que ainda aponta
    para um arquivo dela) não sai: o link morreria na conta do escritório. Nesse caso, desative."""
    voz = await _voz(pedido, id_voz)
    em_uso = await _q(pedido, "fetchval",
                      """select count(distinct id_escritorio)::int from (
                           select g.id_escritorio from agentesia_roteiro_gravacoes g where g.id_voz = $1::uuid
                           union all
                           select m.id_escritorio from agentesia_biblioteca_midia m
                             join agentesia_voz_pronta_audios a on a.url = m.url where a.id_voz = $1::uuid) usos""",
                      voz["id"])
    if em_uso:
        raise HTTPException(409, f"{em_uso} escritório(s) usam esta voz. Desative em vez de apagar.")
    audios = await _q(pedido, "fetch", "select url, caminho_storage from agentesia_voz_pronta_audios where id_voz = $1::uuid",
                      voz["id"])
    await _q(pedido, "execute", "delete from agentesia_vozes_prontas where id = $1::uuid", voz["id"])
    for a in audios:
        await _apagar_arquivo(pedido, a["url"], a["caminho_storage"])
    return {"ok": True}


def _audio_json(a: Any) -> dict[str, Any]:
    return {"url": a["url"], "tipo": a["tipo"], "mime_type": a["mime_type"],
            "tamanho_bytes": int(a["tamanho_bytes"]) if a["tamanho_bytes"] is not None else None,
            "duracao_s": float(a["duracao_s"]) if a["duracao_s"] is not None else None}


@api.get("/admin/biblioteca/produtos/{id_produto}/vozes-prontas")
async def vozes_do_produto(id_produto: str, pedido: Request, _: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    produto = await _produto(pedido, id_produto)
    partes = await _partes(pedido, produto["id"])
    vozes = await listar_vozes(pedido, _)
    audios = await _q(pedido, "fetch",
                      """select a.id_voz, a.id_parte, a.url, a.tipo, a.mime_type, a.tamanho_bytes, a.duracao_s
                           from agentesia_voz_pronta_audios a join agentesia_roteiro_partes p on p.id = a.id_parte
                          where p.id_produto_biblioteca = $1::uuid""", produto["id"])
    por_voz: dict[str, dict[str, Any]] = {}
    for a in audios:
        por_voz.setdefault(str(a["id_voz"]), {})[str(a["id_parte"])] = _audio_json(a)
    textos = {str(l["id"]): l for l in await _q(
        pedido, "fetch", "select id, texto_pronto, aviso_pronto from agentesia_roteiro_partes where id_produto_biblioteca = $1::uuid",
        produto["id"])}
    return {
        "partes": [{**{k: p[k] for k in ("id", "titulo", "secao", "tipo", "marcador", "ordem", "ativo", "chave_geral")},
                    "texto_pronto": (textos.get(str(p["id"])) or {}).get("texto_pronto"),
                    "aviso_pronto": (textos.get(str(p["id"])) or {}).get("aviso_pronto")} for p in partes],
        "vozes": [{**v, "audios": por_voz.get(str(v["id"]), {})} for v in vozes],
    }


class TextoPronto(BaseModel):
    texto_pronto: str | None = Field(default=None, max_length=6000)
    aviso_pronto: str | None = Field(default=None, max_length=600)


@api.patch("/admin/roteiro-partes/{id_parte}/texto-pronto")
async def mudar_texto_pronto(id_parte: str, dados: TextoPronto, pedido: Request, _: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    """O texto que as vozes prontas falam nesta parte (vai para o ElevenLabs) e o aviso para o escritório."""
    mudancas = {k: _texto(v) for k, v in dados.model_dump(exclude_unset=True).items()}
    if not mudancas:
        raise HTTPException(400, "Nada para mudar.")
    sets = ", ".join(f"{k} = ${i}" for i, k in enumerate(mudancas, 2))
    linha = await _q(pedido, "fetchrow", f"update agentesia_roteiro_partes set {sets} where id = $1::uuid "
                     "returning id, texto_pronto, aviso_pronto", _uuid(id_parte), *mudancas.values())
    if not linha:
        raise HTTPException(404, "Parte não encontrada.")
    return {"id": str(linha["id"]), "texto_pronto": linha["texto_pronto"], "aviso_pronto": linha["aviso_pronto"]}


def _eh_video(bruto: bytes, mime: str | None, nome: str | None) -> bool:
    formato = _formato(bruto, mime, nome)
    return formato in ("mp4", "mov") or (formato == "webm" and "video" in (mime or "").lower())


@api.post("/admin/vozes-prontas/{id_voz}/partes/{id_parte}")
async def enviar_audio_da_voz(id_voz: str, id_parte: str, dados: Arquivo, pedido: Request,
                              _: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    """Áudio (ou vídeo) da voz numa parte. Parte de vídeo aceita áudio (boas-vindas por áudio). Substitui o anterior."""
    voz = await _voz(pedido, id_voz)
    parte = await _q(pedido, "fetchrow", "select id, titulo, tipo from agentesia_roteiro_partes where id = $1::uuid",
                     _uuid(id_parte))
    if not parte:
        raise HTTPException(404, "Parte não encontrada.")
    bruto = _decodificar(dados.conteudo_base64)
    tipo = "video" if parte["tipo"] == "video" and _eh_video(bruto, dados.mime, dados.nome) else "audio"
    bruto, extensao = await preparar_arquivo(bruto, tipo, dados.mime, dados.nome)
    if len(bruto) > LIMITES_POR_TIPO[tipo]:
        raise HTTPException(413, f"O arquivo ficou com {len(bruto) / 1_048_576:.0f} MB e o WhatsApp só entrega até "
                                 f"{LIMITES_POR_TIPO[tipo] // 1_048_576} MB. Use um trecho mais curto.")
    try:
        destino = armazenamento.do_ambiente()
    except armazenamento.ErroArmazenamento as erro:
        raise HTTPException(409, str(erro)) from erro
    if destino.modo == "local" and not os.environ.get("AGENTESIA_URL_PUBLICA", "").strip().lower().startswith("https://"):
        raise HTTPException(409, "Configure o endereço público do servidor (AGENTESIA_URL_PUBLICA, com https://) antes de "
                                 "subir mídia.")
    caminho = f"{PREFIXO}{voz['id']}/{uuid.uuid4().hex}-{(slugificar(parte['titulo']) or 'parte')[:40].rstrip('-')}.{extensao}"
    mime = MIMES.get(extensao, "application/octet-stream")
    try:
        url = await destino.enviar(caminho, bruto, mime)
    except armazenamento.ErroArmazenamento as erro:
        raise HTTPException(502, str(erro)) from erro
    duracao = await _duracao(bruto, extensao)
    anterior = await _q(pedido, "fetchrow", "select url, caminho_storage from agentesia_voz_pronta_audios "
                        "where id_voz = $1::uuid and id_parte = $2::uuid", voz["id"], parte["id"])
    try:
        await _pool(pedido).execute(
            """insert into agentesia_voz_pronta_audios (id_voz, id_parte, tipo, url, caminho_storage, mime_type, tamanho_bytes,
                                                        duracao_s)
               values ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8)
               on conflict (id_voz, id_parte) do update set tipo = excluded.tipo, url = excluded.url,
                   caminho_storage = excluded.caminho_storage, mime_type = excluded.mime_type,
                   tamanho_bytes = excluded.tamanho_bytes, duracao_s = excluded.duracao_s, criado_em = now()""",
            voz["id"], parte["id"], tipo, url, caminho, mime, len(bruto), duracao)
    except Exception:
        try:                                              # sem a linha, o arquivo ficaria órfão no armazenamento
            await destino.apagar(caminho)
        except armazenamento.ErroArmazenamento:
            pass
        raise
    if anterior and anterior["url"] != url:
        await _apagar_arquivo(pedido, anterior["url"], anterior["caminho_storage"])
    return {"id_parte": str(parte["id"]), "url": url, "tipo": tipo, "mime_type": mime, "tamanho_bytes": len(bruto),
            "duracao_s": duracao}


@api.delete("/admin/vozes-prontas/{id_voz}/partes/{id_parte}")
async def tirar_audio_da_voz(id_voz: str, id_parte: str, pedido: Request, _: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    linha = await _q(pedido, "fetchrow", "delete from agentesia_voz_pronta_audios where id_voz = $1::uuid and id_parte = $2::uuid "
                     "returning url, caminho_storage", _uuid(id_voz, "Voz"), _uuid(id_parte))
    if not linha:
        raise HTTPException(404, "Esta voz não tem áudio nesta parte.")
    await _apagar_arquivo(pedido, linha["url"], linha["caminho_storage"])
    return {"ok": True}


# ======================================================================================================= escritório
async def _audios_do_produto(pedido: Request, id_produto: str, id_voz: str | None = None) -> list[Any]:
    """Áudios das vozes ATIVAS nas partes ATIVAS do produto."""
    return await _q(pedido, "fetch",
                    f"""select a.id_voz, a.id_parte, a.tipo, a.url, a.mime_type, a.tamanho_bytes, a.duracao_s::float8 as duracao_s
                          from agentesia_voz_pronta_audios a
                          join agentesia_vozes_prontas v on v.id = a.id_voz and v.ativo
                          join agentesia_roteiro_partes p on p.id = a.id_parte and p.ativo
                         where p.id_produto_biblioteca = $1::uuid{' and a.id_voz = $2::uuid' if id_voz else ''}""",
                    id_produto, *([id_voz] if id_voz else []))


@api.get("/roteiro-gravacao/{id_produto}/vozes")
async def vozes_para_usar(id_produto: str, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    produto = await _produto(pedido, id_produto)
    partes = await _partes(pedido, produto["id"], so_ativas=True)
    audios = await _audios_do_produto(pedido, produto["id"])
    vozes = await _q(pedido, "fetch", f"select {_COLUNAS_VOZ} from agentesia_vozes_prontas where ativo order by ordem, criado_em")
    avisos = {str(l["id"]): l["aviso_pronto"] for l in await _q(
        pedido, "fetch", "select id, aviso_pronto from agentesia_roteiro_partes where id_produto_biblioteca = $1::uuid "
        "and ativo and nullif(btrim(aviso_pronto), '') is not null", produto["id"])}
    chaves = [chave_da_parte(p) for p in partes]
    em_uso = {str(l["id_voz"]) for l in await _q(
        pedido, "fetch", "select distinct id_voz from agentesia_roteiro_gravacoes where id_escritorio = $1::uuid "
        "and id_voz is not null and chave = any($2::text[])", ctx.escritorio(), chaves)} if chaves else set()
    por_voz: dict[str, dict[str, Any]] = {}
    for a in audios:
        por_voz.setdefault(str(a["id_voz"]), {})[str(a["id_parte"])] = a
    saida = []
    for v in vozes:
        dela = por_voz.get(str(v["id"]))
        if not dela:
            continue
        lista = [{"id_parte": str(p["id"]), "titulo": p["titulo"], "secao": p["secao"], "tipo": dela[str(p["id"])]["tipo"],
                  "url": dela[str(p["id"])]["url"], "_marcador": p.get("marcador")}
                 for p in partes if str(p["id"]) in dela]
        amostra = (next((a for a in lista if normalizar(a["_marcador"] or a["titulo"]).startswith("como funciona")), None)
                   or next((a for a in lista if a["secao"] == "principais"), None) or lista[0])
        saida.append({**{k: v[k] for k in ("nome", "tom", "genero", "origem", "descricao")}, "id": str(v["id"]),
                      "partes_cobertas": len(lista), "total_partes": len(partes), "em_uso": str(v["id"]) in em_uso,
                      "amostra": {"url": amostra["url"], "tipo": amostra["tipo"], "titulo": amostra["titulo"]},
                      "audios": [{k: a[k] for k in ("id_parte", "titulo", "secao", "tipo", "url")} for a in lista],
                      "avisos": [{"id_parte": a["id_parte"], "titulo": a["titulo"], "aviso": avisos[a["id_parte"]]}
                                 for a in lista if a["id_parte"] in avisos]})
    return {"texto_aceite": TEXTO_ACEITE, "vozes": saida}


class Usar(BaseModel):
    aceite: bool = False
    substituir_minhas: bool = False
    # Partes que o escritório não quer com a voz pronta (ex.: honorários com valores diferentes): seguem em texto
    # ou com a gravação dele.
    pular_partes: list[str] = Field(default_factory=list, max_length=200)


@api.post("/roteiro-gravacao/{id_produto}/vozes/{id_voz}/usar")
async def usar_voz(id_produto: str, id_voz: str, dados: Usar, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Os áudios da voz entram na biblioteca do escritório como gravações (origem 'pronta'). A gravação própria fica,
    salvo com substituir_minhas. Usar de novo a mesma voz não duplica nada."""
    if not dados.aceite:
        raise HTTPException(400, "Marque o aceite para usar a voz pronta.")
    await _exigir_liberado(pedido, ctx)
    produto = await _produto(pedido, id_produto)
    voz = await _voz(pedido, id_voz, so_ativa=True)
    partes = await _partes(pedido, produto["id"], so_ativas=True)
    audios = {str(a["id_parte"]): a for a in await _audios_do_produto(pedido, produto["id"], voz["id"])}
    if not audios:
        raise HTTPException(404, "Esta voz ainda não tem áudios para este produto.")
    pool = _pool(pedido)
    existentes = {l["chave"]: l for l in await _q(
        pedido, "fetch",
        """select g.chave, g.id_midia, g.origem, g.id_voz, m.url from agentesia_roteiro_gravacoes g
             left join agentesia_biblioteca_midia m on m.id = g.id_midia where g.id_escritorio = $1::uuid""", ctx.escritorio())}
    await _q(pedido, "execute",
             """insert into agentesia_voz_pronta_aceites (id_escritorio, id_voz, id_produto_biblioteca, id_usuario, texto)
                values ($1::uuid, $2::uuid, $3::uuid, $4::uuid, $5)""",
             ctx.escritorio(), voz["id"], produto["id"], ctx.id_usuario, TEXTO_ACEITE)
    pasta = _pasta_da_voz(voz["nome"])
    pular = {str(x) for x in dados.pular_partes}
    usadas = mantidas = puladas = 0
    for posicao, parte in enumerate(partes, 1):           # posição = a da tela do roteiro (a mesma do "Áudio 03")
        audio = audios.get(str(parte["id"]))
        if not audio:
            continue
        if str(parte["id"]) in pular:
            puladas += 1
            continue
        chave = chave_da_parte(parte)
        atual = existentes.get(chave)
        if atual and atual["origem"] != "pronta" and not dados.substituir_minhas:
            mantidas += 1
            continue
        if atual and atual["origem"] == "pronta" and str(atual["id_voz"] or "") == str(voz["id"]) and atual["url"] == audio["url"]:
            usadas += 1                                   # já está com esta voz e este áudio
            continue
        nome = f"{posicao:02d} - {parte['titulo'][:150]}"
        criada = await pool.fetchval(
            """insert into agentesia_biblioteca_midia (id_escritorio, nome, tipo, url, caminho_storage, mime_type, tamanho_bytes,
                                                       pasta, tags)
               values ($1::uuid, $2, $3, $4, null, $5, $6, $7, '["voz_pronta"]'::jsonb) returning id""",
            ctx.escritorio(), nome[:200], audio["tipo"], audio["url"], audio["mime_type"], int(audio["tamanho_bytes"] or 0), pasta)
        await _q(pedido, "execute",
                 """insert into agentesia_roteiro_gravacoes (id_escritorio, chave, id_parte, id_midia, duracao_s, qualidade,
                                                             id_usuario, origem, id_voz)
                    values ($1::uuid, $2, $3::uuid, $4::uuid, $5, 'boa', $6::uuid, 'pronta', $7::uuid)
                    on conflict (id_escritorio, chave) do update set id_parte = excluded.id_parte, id_midia = excluded.id_midia,
                        duracao_s = excluded.duracao_s, pico = null, silencio_pct = null, qualidade = 'boa',
                        id_usuario = excluded.id_usuario, origem = 'pronta', id_voz = excluded.id_voz, atualizado_em = now()""",
                 ctx.escritorio(), chave, parte["id"], criada, audio["duracao_s"], ctx.id_usuario, voz["id"])
        if parte.get("chave_geral") == CHAVE_POS_ASSINATURA:   # a ZapSign passa a mandar o novo (como ao gravar)
            await _pos_assinatura(pool, ctx.escritorio(), atual["url"] if atual else None, audio["url"])
        if atual and atual["id_midia"] and str(atual["id_midia"]) != str(criada):
            try:      # a mídia anterior sai (arquivo próprio: some do armazenamento; voz pronta: só a linha), salvo se um
                await apagar_midia(str(atual["id_midia"]), pedido, ctx)   # prompt ainda usa o link dela
            except HTTPException:
                pass
        usadas += 1
    return {"usadas": usadas, "mantidas": mantidas, "puladas": puladas, "total": len(audios)}
