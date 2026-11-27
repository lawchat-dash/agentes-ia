"""Roteiro de gravação por produto (migração 019).

Superadmin (Admin › Produtos › Roteiros): monta as partes de cada produto do catálogo — título, texto para ler, áudio ou
vídeo, seção, exemplo, ordem e o marcador do prompt que a parte preenche ([[audio:Honorários]] → "Honorários").
"Puxar do prompt" cria uma parte para cada marcador dos textos do produto que ainda não tem parte.

Escritório (Roteiros e o card da ativação do produto): grava pelo navegador ou anexa cada parte. O arquivo é convertido
para o que o WhatsApp entrega (voz em Ogg/Opus, vídeo em MP4 até 16 MB), entra na biblioteca de mídia na pasta
"Roteiros gravados/<produto>" e fica ligado à parte. Parte geral (chave_geral) é gravada uma vez e vale para todos os
produtos que têm a mesma chave. Na ativação, o painel troca cada marcador pelo link da gravação.

Liberação: o plano da conta precisa de "midia" (Admin › Planos); conta sem plano (antiga) continua liberada.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import unicodedata
import uuid
from typing import Any
from urllib.parse import unquote

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app import armazenamento
from app.gestao.produtos import (COTA_MIDIA, LIMITES_POR_TIPO, MidiaNova, _linha, _pool, _quem_usa_a_midia, _uso_midia,
                                 apagar_midia, enviar_midia)
from app.gestao.rotas import ADMIN, GESTAO, Contexto
from app.midia.conversao import ErroConversao, codecs, para_mp4, para_ogg, tem_ffmpeg
from app.midia.webm_para_ogg import eh_webm, webm_para_ogg
from app.midia.webm_para_ogg import ErroConversao as ErroWebm

api = APIRouter(prefix="/api")

SEM_TABELA = "O roteiro de gravação ainda não está no banco: aplique a migração db/migracoes/019_agentesia_roteiro_gravacao.sql."
SECOES = ("videos", "principais", "objecoes")
LIMITE_ENTRADA = 80 * 1024 * 1024          # arquivo bruto antes de converter (vídeo do celular pode vir grande)
LIMITE_EXEMPLO = 16 * 1024 * 1024
_MARCADOR = re.compile(r"\\?\[\\?\[\s*([aá]udio|v[ií]deo|m[ií]dia|media|imagem)\s*:\s*([^\]\\\n]+?)\s*\\?\]\\?\]", re.I)


# ---------------------------------------------------------------------------------------------------------- utilidades
def normalizar(nome: str | None) -> str:
    """Chave de comparação de marcador: sem acento, minúsculo, só letras e números ("Honorários " = "honorarios")."""
    texto = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", texto).strip()


def marcadores_do_texto(texto: str) -> list[tuple[str, str]]:
    """[(tipo, nome)] na ordem em que aparecem, sem repetir. tipo: audio|video (midia/imagem contam como audio)."""
    vistos: set[str] = set()
    saida: list[tuple[str, str]] = []
    for prefixo, nome in _MARCADOR.findall(texto or ""):
        nome = nome.strip()
        if not nome or normalizar(nome) in vistos:
            continue
        vistos.add(normalizar(nome))
        # O catálogo escreve vídeos como [[audio:Video Inicial]]: "vídeo" no nome também conta como vídeo.
        tipo = "video" if prefixo.lower().startswith("v") or normalizar(nome).startswith("video") else "audio"
        saida.append((tipo, nome))
    return saida


def chave_da_parte(parte: dict[str, Any]) -> str:
    return f"geral:{parte['chave_geral']}" if parte.get("chave_geral") else f"parte:{parte['id']}"


async def _consultar(pedido: Request, metodo: str, sql: str, *args: Any) -> Any:
    try:
        return await getattr(_pool(pedido), metodo)(sql, *args)
    except (asyncpg.UndefinedTableError, asyncpg.UndefinedColumnError) as erro:
        raise HTTPException(503, SEM_TABELA) from erro


def _uuid(valor: str, oque: str = "Parte") -> str:
    try:
        return str(uuid.UUID(valor))
    except (ValueError, TypeError) as erro:
        raise HTTPException(404, f"{oque} não encontrada.") from erro


def _decodificar(conteudo: str) -> bytes:
    try:
        bruto = base64.b64decode(conteudo.split(",")[-1], validate=True)
    except (binascii.Error, ValueError) as erro:
        raise HTTPException(400, "Arquivo inválido (não veio em base64).") from erro
    if not bruto:
        raise HTTPException(400, "O arquivo está vazio.")
    return bruto


def _formato(bruto: bytes, mime: str | None, nome: str | None) -> str:
    """Extensão provável pelo conteúdo, depois pelo tipo e pelo nome."""
    mime = (mime or "").lower()
    final = nome.rsplit(".", 1)[-1].lower() if nome and "." in nome else ""
    if bruto[:4] == b"OggS":
        return "ogg"
    if eh_webm(bruto) or "webm" in mime:
        return "webm"
    if bruto[:4] == b"RIFF" and bruto[8:12] == b"WAVE":
        return "wav"
    if bruto[4:8] == b"ftyp":
        marca = bruto[8:12]
        if marca == b"qt  " or final == "mov" or "quicktime" in mime:
            return "mov"
        if final in ("m4a", "aac") or "audio" in mime or marca in (b"M4A ", b"M4B "):
            return "m4a"
        return "mp4"
    if bruto[:3] == b"ID3" or (len(bruto) > 1 and bruto[0] == 0xFF and bruto[1] & 0xE0 == 0xE0 and "aac" not in mime):
        return "mp3"
    return final or ("mp4" if "video" in mime else "ogg")


async def preparar_arquivo(bruto: bytes, tipo: str, mime: str | None, nome: str | None) -> tuple[bytes, str]:
    """Bytes + extensão no formato que o WhatsApp entrega. Áudio: ogg/mp3/m4a passam; webm vira ogg (sem ffmpeg);
    o resto vira ogg pelo ffmpeg. Vídeo: mp4 H.264/AAC até 16 MB passa; o resto (webm, mov, mp4 grande ou de outro codec,
    como o HEVC do iPhone) vira mp4 pelo ffmpeg. Sem ffprobe/ffmpeg no servidor, o mp4 até 16 MB passa sem conferir."""
    if len(bruto) > LIMITE_ENTRADA:
        raise HTTPException(413, f"Este arquivo tem {len(bruto) / 1_048_576:.0f} MB e o limite é "
                                 f"{LIMITE_ENTRADA // 1_048_576} MB. Grave um trecho mais curto.")
    formato = _formato(bruto, mime, nome)
    try:
        if tipo == "audio":
            if formato == "ogg":
                # Mensagem de voz do WhatsApp só em Ogg com OPUS: Ogg/Vorbis (alguns gravadores) é convertido.
                achados = await codecs(bruto, ".ogg") if tem_ffmpeg() else None
                if achados is None or achados[1] == "opus":
                    return bruto, "ogg"
                return await para_ogg(bruto, ".ogg"), "ogg"
            if formato in ("mp3", "m4a"):
                return bruto, formato
            if formato == "webm":
                try:
                    return webm_para_ogg(bruto), "ogg"
                except ErroWebm:
                    return await para_ogg(bruto, ".webm"), "ogg"
            if formato in ("mp4", "mov"):                 # gravou com câmera numa parte de áudio: fica só o som
                return await para_ogg(bruto, f".{formato}"), "ogg"
            return await para_ogg(bruto, f".{formato or 'wav'}"), "ogg"
        if formato == "mp4" and len(bruto) <= LIMITES_POR_TIPO["video"]:
            achados = await codecs(bruto, ".mp4") if tem_ffmpeg() else None
            if achados is None or (achados[0] == "h264" and achados[1] in ("aac", None)):
                return bruto, "mp4"
            return await para_mp4(bruto, ".mp4"), "mp4"   # HEVC, áudio em outro codec etc.: o WhatsApp não toca
        if formato in ("ogg", "mp3", "m4a", "wav"):
            raise HTTPException(400, "Esta parte é de vídeo: grave ou envie um vídeo (.mp4, .mov ou .webm).")
        return await para_mp4(bruto, f".{formato}"), "mp4"
    except ErroConversao as erro:
        raise HTTPException(400, f"Não deu para preparar o arquivo: {erro}") from erro


async def _liberacao(pedido: Request, ctx: Contexto) -> tuple[bool, str | None]:
    """O plano da conta libera mídia? Conta sem plano (antiga) e equipe LawChat: liberado."""
    if ctx.lawchat:
        return True, None
    pool = _pool(pedido)
    try:
        linha = await pool.fetchrow(
            """select p.nome, p.midia from agentesia_carteiras c join agentesia_planos p on p.id = c.id_plano
                where c.id_escritorio = $1::uuid""", ctx.escritorio())
    except (asyncpg.UndefinedTableError, asyncpg.UndefinedColumnError):
        return True, None
    if not linha or linha["midia"]:
        return True, None
    return False, f"O plano {linha['nome']} não inclui mídia e roteiros de gravação. Fale com a LawChat para mudar de plano."


async def _exigir_liberado(pedido: Request, ctx: Contexto) -> None:
    liberado, motivo = await _liberacao(pedido, ctx)
    if not liberado:
        raise HTTPException(403, motivo)


_COLUNAS_PARTE = """id, id_produto_biblioteca, titulo, texto, tipo, secao, marcador, chave_geral, exemplo_url, ordem, ativo,
                    criado_em, atualizado_em"""


async def _partes(pedido: Request, id_produto: str, so_ativas: bool = False) -> list[dict[str, Any]]:
    linhas = await _consultar(pedido, "fetch",
                              f"select {_COLUNAS_PARTE} from agentesia_roteiro_partes where id_produto_biblioteca = $1::uuid"
                              f"{' and ativo' if so_ativas else ''} order by "
                              "array_position(array['videos','principais','objecoes'], secao), ordem, criado_em", id_produto)
    return [_linha(l) for l in linhas]  # type: ignore[misc]


async def _produto(pedido: Request, id_produto: str) -> dict[str, Any]:
    linha = await _pool(pedido).fetchrow(
        "select id, slug, nome, categoria, icone, modo_midia, status, roteiro_orientacoes from agentesia_biblioteca_produtos "
        "where id = $1::uuid",
        _uuid(id_produto, "Produto"))
    if not linha:
        raise HTTPException(404, "Produto não encontrado.")
    return _linha(linha)  # type: ignore[return-value]


async def _marcadores_do_produto(pedido: Request, id_produto: str) -> list[tuple[str, str]]:
    """Marcadores de mídia em todos os textos do produto do catálogo: o produto e os agentes dele."""
    textos = await _pool(pedido).fetch(
        """select row_to_json(p)::text as t from agentesia_biblioteca_produtos p where p.id = $1::uuid
           union all
           select row_to_json(a)::text from agentesia_biblioteca_agentes a where a.id_produto_biblioteca = $1::uuid""",
        id_produto)
    # A regex roda sobre os textos de verdade, não sobre o JSON: no JSON as barras dobram (\[\[ vira \\[\\[) e o
    # marcador escapado não seria achado. Cada texto numa linha para a regex não atravessar campos.
    pedacos: list[str] = []
    for t in textos:
        _textos_do_json(json.loads(t["t"]), pedacos)
    return marcadores_do_texto("\n".join(pedacos))


def _textos_do_json(valor: Any, saida: list[str]) -> None:
    """Junta em saida todos os textos (str) de dicts e listas aninhados, na ordem em que aparecem."""
    if isinstance(valor, str):
        saida.append(valor)
    elif isinstance(valor, dict):
        for item in valor.values():
            _textos_do_json(item, saida)
    elif isinstance(valor, list):
        for item in valor:
            _textos_do_json(item, saida)


# ======================================================================================================= superadmin
class ParteNova(BaseModel):
    titulo: str = Field(min_length=1, max_length=160)
    texto: str = Field(default="", max_length=20000)
    tipo: str = Field(default="audio", pattern="^(audio|video)$")
    secao: str = Field(default="principais", pattern="^(videos|principais|objecoes)$")
    marcador: str | None = Field(default=None, max_length=160)
    chave_geral: str | None = Field(default=None, max_length=60)
    ordem: int | None = None
    ativo: bool = True


class ParteMudar(BaseModel):
    titulo: str | None = Field(default=None, min_length=1, max_length=160)
    texto: str | None = Field(default=None, max_length=20000)
    tipo: str | None = Field(default=None, pattern="^(audio|video)$")
    secao: str | None = Field(default=None, pattern="^(videos|principais|objecoes)$")
    marcador: str | None = Field(default=None, max_length=160)
    chave_geral: str | None = Field(default=None, max_length=60)
    ordem: int | None = None
    ativo: bool | None = None


class Orientacoes(BaseModel):
    texto: str = Field(default="", max_length=8000)


class Ordem(BaseModel):
    ids: list[str] = Field(max_length=300)


class Arquivo(BaseModel):
    conteudo_base64: str = Field(min_length=4)
    mime: str | None = Field(default=None, max_length=120)
    nome: str | None = Field(default=None, max_length=200)


def _chave_geral(valor: str | None) -> str | None:
    if valor is None:
        return None
    chave = re.sub(r"[^a-z0-9]+", "_", normalizar(valor)).strip("_")[:60]
    if valor.strip() and len(chave) < 2:
        raise HTTPException(400, "Chave da parte geral inválida: use pelo menos 2 letras.")
    return chave or ""


@api.get("/admin/biblioteca/produtos/{id_produto}/roteiro")
async def roteiro_do_produto(id_produto: str, pedido: Request, _: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    produto = await _produto(pedido, id_produto)
    partes = await _partes(pedido, produto["id"])
    marcadores = await _marcadores_do_produto(pedido, produto["id"])
    com_parte = {normalizar(p["marcador"]) for p in partes if p.get("marcador")}
    gerais = await _consultar(pedido, "fetch",
                              """select chave_geral, min(titulo) as titulo, min(tipo) as tipo, count(*)::int as produtos
                                   from agentesia_roteiro_partes where chave_geral is not null group by chave_geral
                                  order by chave_geral""")
    gravacoes = await _consultar(pedido, "fetchval",
                                 """select count(*)::int from agentesia_roteiro_gravacoes g
                                      join agentesia_roteiro_partes p on p.id = g.id_parte
                                     where p.id_produto_biblioteca = $1::uuid""", produto["id"])
    return {
        "produto": produto, "partes": partes, "gravacoes": gravacoes,
        "marcadores": [{"tipo": t, "nome": n, "tem_parte": normalizar(n) in com_parte} for t, n in marcadores],
        "gerais": [dict(g) for g in gerais],
    }


@api.post("/admin/biblioteca/produtos/{id_produto}/roteiro/partes")
async def criar_parte(id_produto: str, dados: ParteNova, pedido: Request, _: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    produto = await _produto(pedido, id_produto)
    ordem = dados.ordem
    if ordem is None:
        ordem = await _consultar(pedido, "fetchval", "select coalesce(max(ordem), 0) + 10 from agentesia_roteiro_partes "
                                 "where id_produto_biblioteca = $1::uuid", produto["id"])
    linha = await _consultar(pedido, "fetchrow",
                             f"""insert into agentesia_roteiro_partes (id_produto_biblioteca, titulo, texto, tipo, secao, marcador,
                                    chave_geral, ordem, ativo) values ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9)
                                 returning {_COLUNAS_PARTE}""",
                             produto["id"], dados.titulo.strip(), dados.texto, dados.tipo, dados.secao,
                             (dados.marcador or "").strip() or None, _chave_geral(dados.chave_geral) or None, ordem, dados.ativo)
    return _linha(linha)  # type: ignore[return-value]


@api.post("/admin/biblioteca/produtos/{id_produto}/roteiro/puxar")
async def puxar_do_prompt(id_produto: str, pedido: Request, _: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    """Uma parte para cada marcador dos textos do produto que ainda não tem parte (o texto fica para preencher)."""
    produto = await _produto(pedido, id_produto)
    partes = await _partes(pedido, produto["id"])
    com_parte = {normalizar(p["marcador"]) for p in partes if p.get("marcador")}
    ordem = max((p["ordem"] for p in partes), default=0)
    criadas = 0
    for tipo, nome in await _marcadores_do_produto(pedido, produto["id"]):
        if normalizar(nome) in com_parte:
            continue
        ordem += 10
        secao = "videos" if tipo == "video" else "objecoes" if normalizar(nome).startswith("objec") else "principais"
        titulo = re.sub(r"[_-]+", " ", nome).strip()
        await _consultar(pedido, "execute",
                         """insert into agentesia_roteiro_partes (id_produto_biblioteca, titulo, tipo, secao, marcador, ordem)
                            values ($1::uuid, $2, $3, $4, $5, $6)""",
                         produto["id"], titulo[:1].upper() + titulo[1:], tipo, secao, nome, ordem)
        com_parte.add(normalizar(nome))
        criadas += 1
    return {"criadas": criadas, **(await roteiro_do_produto(produto["id"], pedido, _))}


@api.patch("/admin/roteiro/partes/{id_parte}")
async def mudar_parte(id_parte: str, dados: ParteMudar, pedido: Request, _: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    mudancas = {k: v for k, v in dados.model_dump().items() if v is not None}
    if "titulo" in mudancas:
        mudancas["titulo"] = mudancas["titulo"].strip()
    if "marcador" in mudancas:
        mudancas["marcador"] = mudancas["marcador"].strip() or None
    if "chave_geral" in mudancas:
        mudancas["chave_geral"] = _chave_geral(mudancas["chave_geral"]) or None
    if not mudancas:
        raise HTTPException(400, "Nada para mudar.")
    antes = await _consultar(pedido, "fetchrow", f"select {_COLUNAS_PARTE} from agentesia_roteiro_partes where id = $1::uuid",
                             _uuid(id_parte))
    if not antes:
        raise HTTPException(404, "Parte não encontrada.")
    parte = _linha(antes) or {}
    sets = ", ".join(f"{k} = ${i}" for i, k in enumerate(mudancas, 2))
    try:
        async with _pool(pedido).acquire() as con, con.transaction():
            linha = await con.fetchrow(f"update agentesia_roteiro_partes set {sets}, atualizado_em = now() where id = $1::uuid "
                                       f"returning {_COLUNAS_PARTE}", parte["id"], *mudancas.values())
            if not linha:
                raise HTTPException(404, "Parte não encontrada.")
            if "chave_geral" in mudancas and mudancas["chave_geral"] != parte.get("chave_geral"):
                await _mudar_chave_das_gravacoes(con, parte["id"], chave_da_parte(parte),
                                                 chave_da_parte({**parte, "chave_geral": mudancas["chave_geral"]}))
    except (asyncpg.UndefinedTableError, asyncpg.UndefinedColumnError) as erro:
        raise HTTPException(503, SEM_TABELA) from erro
    return _linha(linha)  # type: ignore[return-value]


async def _mudar_chave_das_gravacoes(con: Any, id_parte: str, antiga: str, nova: str) -> None:
    """A chave da gravação ('geral:<chave>' ou 'parte:<id>') segue a chave_geral da parte: sem isto, trocar ou tirar a
    chave_geral esconderia o que os escritórios já gravaram. Só as gravações feitas por ESTA parte mudam: a de uma parte
    geral pode ter sido feita pela parte de outro produto com a mesma chave, e essa continua valendo para ele.
    Se o escritório já tem gravação na chave nova, ela fica e a desta parte sai (só o vínculo: o arquivo continua na
    biblioteca de mídia do escritório)."""
    if antiga == nova:
        return
    await con.execute(
        """delete from agentesia_roteiro_gravacoes g
            where g.id_parte = $1::uuid and g.chave = $2
              and exists (select 1 from agentesia_roteiro_gravacoes o where o.id_escritorio = g.id_escritorio and o.chave = $3)""",
        id_parte, antiga, nova)
    await con.execute(
        """update agentesia_roteiro_gravacoes g set chave = $3, atualizado_em = now()
            where g.id_parte = $1::uuid and g.chave = $2
              and not exists (select 1 from agentesia_roteiro_gravacoes o where o.id_escritorio = g.id_escritorio and o.chave = $3)""",
        id_parte, antiga, nova)


@api.put("/admin/biblioteca/produtos/{id_produto}/roteiro/orientacoes")
async def salvar_orientacoes(id_produto: str, dados: Orientacoes, pedido: Request, _: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    produto = await _produto(pedido, id_produto)
    await _consultar(pedido, "execute", "update agentesia_biblioteca_produtos set roteiro_orientacoes = $2 where id = $1::uuid",
                     produto["id"], dados.texto.strip() or None)
    return {"ok": True}


@api.post("/admin/biblioteca/produtos/{id_produto}/roteiro/ordem")
async def ordenar_partes(id_produto: str, dados: Ordem, pedido: Request, _: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    produto = await _produto(pedido, id_produto)
    async with _pool(pedido).acquire() as con, con.transaction():
        for i, id_parte in enumerate(dados.ids):
            await con.execute("update agentesia_roteiro_partes set ordem = $3 where id = $1::uuid and id_produto_biblioteca = $2::uuid",
                              _uuid(id_parte), produto["id"], (i + 1) * 10)
    return {"partes": await _partes(pedido, produto["id"])}


@api.delete("/admin/roteiro/partes/{id_parte}")
async def apagar_parte(id_parte: str, pedido: Request, _: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    """Apaga a parte. As gravações dos escritórios continuam na biblioteca deles (só perdem o vínculo)."""
    linha = await _consultar(pedido, "fetchrow", "delete from agentesia_roteiro_partes where id = $1::uuid returning exemplo_url",
                             _uuid(id_parte))
    if not linha:
        raise HTTPException(404, "Parte não encontrada.")
    await _apagar_exemplo(linha["exemplo_url"])
    return {"ok": True}


def _caminho_do_exemplo(origem: armazenamento.Armazenamento, url: str) -> str | None:
    """Caminho do exemplo no armazenamento pela URL gravada. Só devolve caminhos de exemplo (roteiros/<id da parte>/...):
    uma URL de outro lugar nunca leva a apagar outro arquivo."""
    if isinstance(origem, armazenamento.ArmazenamentoSupabase):
        caminho = origem.caminho_da_url(url)
    else:                                                 # local: {AGENTESIA_URL_PUBLICA}/midia/<caminho>
        caminho = url.split("/midia/", 1)[1] if "/midia/" in url else None
    caminho = unquote(caminho.split("?", 1)[0]) if caminho else None
    return caminho if caminho and caminho.startswith("roteiros/") and ".." not in caminho else None


async def _apagar_exemplo(url: str | None) -> None:
    """Tira do armazenamento o arquivo de um exemplo que saiu (trocado, tirado ou parte apagada). Falha não trava a tela:
    no pior caso o arquivo fica sobrando no armazenamento."""
    if not url:
        return
    origem = armazenamento.de_uma_midia(url)
    caminho = _caminho_do_exemplo(origem, url) if origem is not None else None
    if not caminho:
        return
    try:
        await origem.apagar(caminho)  # type: ignore[union-attr]
    except (armazenamento.ErroArmazenamento, OSError) as erro:
        armazenamento.log.warning("exemplo do roteiro não saiu do armazenamento (%s): %s", caminho, type(erro).__name__)


@api.post("/admin/roteiro/partes/{id_parte}/exemplo")
async def enviar_exemplo(id_parte: str, dados: Arquivo, pedido: Request, _: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    """Exemplo de referência (como deve soar). Fica no armazenamento em roteiros/<id da parte>/."""
    parte = await _consultar(pedido, "fetchrow", f"select {_COLUNAS_PARTE} from agentesia_roteiro_partes where id = $1::uuid",
                             _uuid(id_parte))
    if not parte:
        raise HTTPException(404, "Parte não encontrada.")
    bruto = _decodificar(dados.conteudo_base64)
    if len(bruto) > LIMITE_EXEMPLO * 3:
        raise HTTPException(413, "Exemplo grande demais.")
    bruto, extensao = await preparar_arquivo(bruto, parte["tipo"], dados.mime, dados.nome)
    try:
        destino = armazenamento.do_ambiente()
        caminho = f"roteiros/{parte['id']}/{uuid.uuid4().hex}.{extensao}"
        url = await destino.enviar(caminho, bruto, {"ogg": "audio/ogg", "mp3": "audio/mpeg", "m4a": "audio/mp4",
                                                     "mp4": "video/mp4"}.get(extensao, "application/octet-stream"))
    except armazenamento.ErroArmazenamento as erro:
        raise HTTPException(502, str(erro)) from erro
    linha = await _consultar(pedido, "fetchrow", f"update agentesia_roteiro_partes set exemplo_url = $2, atualizado_em = now() "
                             f"where id = $1::uuid returning {_COLUNAS_PARTE}", parte["id"], url)
    if not linha:                                         # a parte saiu enquanto o arquivo subia: o novo não fica órfão
        await _apagar_exemplo(url)
        raise HTTPException(404, "Parte não encontrada.")
    if parte["exemplo_url"] and parte["exemplo_url"] != url:
        await _apagar_exemplo(parte["exemplo_url"])       # o exemplo anterior sai do armazenamento
    return _linha(linha)  # type: ignore[return-value]


@api.delete("/admin/roteiro/partes/{id_parte}/exemplo")
async def tirar_exemplo(id_parte: str, pedido: Request, _: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    anterior = await _consultar(pedido, "fetchval", "select exemplo_url from agentesia_roteiro_partes where id = $1::uuid",
                                _uuid(id_parte))
    linha = await _consultar(pedido, "fetchrow", f"update agentesia_roteiro_partes set exemplo_url = null, atualizado_em = now() "
                             f"where id = $1::uuid returning {_COLUNAS_PARTE}", _uuid(id_parte))
    if not linha:
        raise HTTPException(404, "Parte não encontrada.")
    await _apagar_exemplo(anterior)
    return _linha(linha)  # type: ignore[return-value]


# ======================================================================================================= escritório
async def _gravacoes_do_escritorio(pedido: Request, ctx: Contexto) -> dict[str, dict[str, Any]]:
    linhas = await _consultar(pedido, "fetch",
                              """select g.chave, g.id_parte, g.qualidade, g.duracao_s::float8 as duracao_s, g.criado_em,
                                        g.atualizado_em, m.id as id_midia, m.nome, m.url, m.tipo, m.mime_type, m.tamanho_bytes,
                                        p.id_produto_biblioteca as produto_da_gravacao
                                   from agentesia_roteiro_gravacoes g
                                   join agentesia_biblioteca_midia m on m.id = g.id_midia
                                   left join agentesia_roteiro_partes p on p.id = g.id_parte
                                  where g.id_escritorio = $1::uuid""", ctx.escritorio())
    return {l["chave"]: _linha(l) for l in linhas}  # type: ignore[misc]


def _com_gravacao(parte: dict[str, Any], gravacoes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    g = gravacoes.get(chave_da_parte(parte))
    saida = {**parte, "gravacao": None}
    if g:
        saida["gravacao"] = {**g, "reaproveitada": bool(parte.get("chave_geral")) and
                             str(g.get("produto_da_gravacao") or "") != str(parte["id_produto_biblioteca"])}
    return saida


def _resumo(partes: list[dict[str, Any]]) -> dict[str, int]:
    return {"total": len(partes), "gravadas": sum(1 for p in partes if p["gravacao"]),
            "videos": sum(1 for p in partes if p["tipo"] == "video"), "audios": sum(1 for p in partes if p["tipo"] == "audio"),
            "faltam_videos": sum(1 for p in partes if p["tipo"] == "video" and not p["gravacao"]),
            "faltam_audios": sum(1 for p in partes if p["tipo"] == "audio" and not p["gravacao"])}


@api.get("/roteiro-gravacao")
async def meus_roteiros(pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Produtos com roteiro de gravação (de mídia e publicados), com o progresso do escritório. Os já ativados vêm antes."""
    liberado, motivo = await _liberacao(pedido, ctx)
    produtos = await _consultar(pedido, "fetch",
                                """select b.id, b.slug, b.nome, b.categoria, b.icone,
                                          exists (select 1 from agentesia_produtos_ativados a where a.id_escritorio = $1::uuid
                                                     and a.id_produto_biblioteca = b.id and a.excluido_em is null) as ativado
                                     from agentesia_biblioteca_produtos b
                                    where b.modo_midia = 'audio' and b.status = 'publicado'
                                      and exists (select 1 from agentesia_roteiro_partes r where r.id_produto_biblioteca = b.id and r.ativo)
                                    order by 6 desc, b.nome""", ctx.escritorio())
    gravacoes = await _gravacoes_do_escritorio(pedido, ctx)
    saida = []
    for p in produtos:
        partes = [_com_gravacao(x, gravacoes) for x in await _partes(pedido, str(p["id"]), so_ativas=True)]
        saida.append({**_linha(p), **_resumo(partes)})  # type: ignore[dict-item]
    return {"liberado": liberado, "motivo": motivo, "produtos": saida}


@api.get("/roteiro-gravacao/{id_produto}")
async def roteiro_para_gravar(id_produto: str, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    produto = await _produto(pedido, id_produto)
    liberado, motivo = await _liberacao(pedido, ctx)
    gravacoes = await _gravacoes_do_escritorio(pedido, ctx)
    partes = [_com_gravacao(x, gravacoes) for x in await _partes(pedido, produto["id"], so_ativas=True)]
    return {"produto": produto, "liberado": liberado, "motivo": motivo, "partes": partes, **_resumo(partes)}


class Gravacao(Arquivo):
    duracao_s: float | None = Field(default=None, ge=0, le=36000)
    pico: float | None = Field(default=None, ge=0, le=1)
    silencio_pct: float | None = Field(default=None, ge=0, le=100)
    qualidade: str | None = Field(default=None, pattern="^(boa|curta|baixa|silenciosa)$")
    como_audio: bool = False          # parte de vídeo: "não quero inserir um vídeo, vou trocar por áudio"


@api.post("/roteiro-gravacao/partes/{id_parte}")
async def gravar_parte(id_parte: str, dados: Gravacao, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Recebe a gravação (ou o arquivo anexado) de uma parte. Regravar substitui a anterior."""
    await _exigir_liberado(pedido, ctx)
    linha = await _consultar(pedido, "fetchrow",
                             f"""select {', '.join('r.' + c.strip() for c in _COLUNAS_PARTE.replace(chr(10), ' ').split(','))},
                                        b.nome as produto_nome
                                   from agentesia_roteiro_partes r join agentesia_biblioteca_produtos b on b.id = r.id_produto_biblioteca
                                  where r.id = $1::uuid and r.ativo""", _uuid(id_parte))
    if not linha:
        raise HTTPException(404, "Parte não encontrada.")
    parte = _linha(linha) or {}
    tipo = "audio" if dados.como_audio else parte["tipo"]
    bruto, extensao = await preparar_arquivo(_decodificar(dados.conteudo_base64), tipo, dados.mime, dados.nome)
    titulo = parte["titulo"][:150]
    # Número = a posição da parte na tela do roteiro (a mesma do "Áudio 03"), para a pasta seguir a ordem da tela.
    ordem_na_tela = [str(x["id"]) for x in await _partes(pedido, str(parte["id_produto_biblioteca"]), so_ativas=True)]
    posicao = ordem_na_tela.index(str(parte["id"])) + 1 if str(parte["id"]) in ordem_na_tela else 0
    nome = f"{posicao:02d} - {titulo}" if posicao else titulo
    pool = _pool(pedido)
    chave = chave_da_parte(parte)
    anterior = await pool.fetchval("select id_midia from agentesia_roteiro_gravacoes where id_escritorio = $1::uuid and chave = $2",
                                   ctx.escritorio(), chave)
    url_anterior = await pool.fetchval("select url from agentesia_biblioteca_midia where id = $1::uuid", anterior) if anterior else None
    if anterior and await _abrir_espaco(pedido, ctx, str(anterior), len(bruto)):
        anterior = None                                   # já saiu (e o vínculo com ele, em cascata)
    criada = await enviar_midia(MidiaNova(nome=f"{nome}.{extensao}", conteudo_base64=base64.b64encode(bruto).decode()),
                                pedido, ctx)
    # "/" no nome do produto viraria uma subpasta que não existe na biblioteca.
    produto_pasta = re.sub(r"\s*[/\\]+\s*", " - ", parte["produto_nome"] or "").strip() or "Produto"
    pasta = "Roteiros gravados/Gerais" if parte.get("chave_geral") else f"Roteiros gravados/{produto_pasta}"
    await pool.execute("update agentesia_biblioteca_midia set nome = $2, pasta = $3 where id = $1::uuid",
                       criada["id"], nome[:200], pasta)
    await pool.execute(
        """insert into agentesia_roteiro_gravacoes (id_escritorio, chave, id_parte, id_midia, duracao_s, pico, silencio_pct,
                                                    qualidade, id_usuario)
           values ($1::uuid, $2, $3::uuid, $4::uuid, $5, $6, $7, $8, $9::uuid)
           on conflict (id_escritorio, chave) do update set id_parte = excluded.id_parte, id_midia = excluded.id_midia,
               duracao_s = excluded.duracao_s, pico = excluded.pico, silencio_pct = excluded.silencio_pct,
               qualidade = excluded.qualidade, id_usuario = excluded.id_usuario, atualizado_em = now()""",
        ctx.escritorio(), chave, parte["id"], criada["id"], dados.duracao_s, dados.pico, dados.silencio_pct, dados.qualidade,
        ctx.id_usuario)
    pos_assinatura = False
    if parte.get("chave_geral") == CHAVE_POS_ASSINATURA:   # antes de apagar o antigo: a ZapSign passa a mandar o novo
        pos_assinatura = await _pos_assinatura(pool, ctx.escritorio(), url_anterior, criada["url"])
    if anterior and str(anterior) != str(criada["id"]):
        try:                                     # o arquivo antigo sai, salvo se um prompt ainda usa o link dele
            await apagar_midia(str(anterior), pedido, ctx)
        except HTTPException:
            pass
    gravacoes = await _gravacoes_do_escritorio(pedido, ctx)
    return {**_com_gravacao(parte, gravacoes), "pos_assinatura": pos_assinatura}


async def _abrir_espaco(pedido: Request, ctx: Contexto, id_anterior: str, tamanho_novo: int) -> bool:
    """Regravar perto da cota: o arquivo antigo ainda conta no espaço e o novo seria recusado. Só nesse caso (e se tirar o
    antigo basta para caber o novo) a gravação antiga sai ANTES de subir a nova. Fora disso a ordem é a de sempre (sobe
    a nova, depois apaga a antiga), para uma falha no envio não fazer a pessoa perder o que já tinha gravado.
    Não sai se um prompt ainda usa o link dela. True = a antiga foi apagada."""
    pool = _pool(pedido)
    usado = await _uso_midia(pool, ctx.escritorio())
    if usado + tamanho_novo <= COTA_MIDIA:
        return False
    antiga = await pool.fetchrow("select url, caminho_storage, tamanho_bytes from agentesia_biblioteca_midia "
                                 "where id = $1::uuid and id_escritorio = $2::uuid", id_anterior, ctx.escritorio())
    if not antiga or usado - int(antiga["tamanho_bytes"] or 0) + tamanho_novo > COTA_MIDIA:
        return False
    if await _quem_usa_a_midia(pool, ctx.escritorio(), antiga["caminho_storage"] or antiga["url"]):
        return False
    try:
        await apagar_midia(id_anterior, pedido, ctx)
    except HTTPException:
        return False
    return True


# A parte geral "contrato_assinado" (áudio de parabéns depois da assinatura) não preenche marcador de prompt: ela vira a
# mídia que a ZapSign manda ao lead quando o contrato é assinado (agentesia_integracoes.config.midia_pos_assinatura,
# app/acoes.py), antes da mensagem de confirmação.
CHAVE_POS_ASSINATURA = "contrato_assinado"


async def _pos_assinatura(pool: Any, id_escritorio: str, url_antiga: str | None, url_nova: str | None) -> bool:
    """Liga a gravação como mídia pós-assinatura do escritório. Nova gravação: só entra se o escritório ainda não escolheu
    outra mídia (ou se a escolhida era a gravação antiga desta parte). Gravação apagada: tira o link só se era ela.
    Nunca troca uma mídia que o escritório escolheu à mão. True = a configuração mudou."""
    try:
        if url_nova:
            r = await pool.execute(
                """update agentesia_integracoes
                      set config = jsonb_set(coalesce(config, '{}'::jsonb), '{midia_pos_assinatura}',
                                             jsonb_build_object('url', $3::text), true)
                    where id_escritorio = $1::uuid and tipo = 'zapsign'
                      and (coalesce(config->'midia_pos_assinatura'->>'url', '') = ''
                           or config->'midia_pos_assinatura'->>'url' = $2)""",
                id_escritorio, url_antiga or "", url_nova)
        elif url_antiga:
            r = await pool.execute(
                """update agentesia_integracoes
                      set config = jsonb_set(config, '{midia_pos_assinatura}', jsonb_build_object('url', null), true)
                    where id_escritorio = $1::uuid and tipo = 'zapsign' and config->'midia_pos_assinatura'->>'url' = $2""",
                id_escritorio, url_antiga)
        else:
            return False
    except (asyncpg.UndefinedTableError, asyncpg.UndefinedColumnError):
        return False
    return r.split()[-1] != "0"


@api.get("/roteiro-gravacao/geral/{chave}")
async def gravacao_geral(chave: str, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """A gravação do escritório para uma parte geral (ex.: contrato_assinado), para a tela da ZapSign sugerir."""
    gravacoes = await _gravacoes_do_escritorio(pedido, ctx)
    return {"gravacao": gravacoes.get(f"geral:{_chave_geral(chave) or chave}")}


@api.delete("/roteiro-gravacao/partes/{id_parte}")
async def apagar_gravacao(id_parte: str, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Apaga a gravação da parte. Se o link ainda está num prompt, o arquivo fica na biblioteca e só o vínculo sai."""
    linha = await _consultar(pedido, "fetchrow", f"select {_COLUNAS_PARTE} from agentesia_roteiro_partes where id = $1::uuid",
                             _uuid(id_parte))
    if not linha:
        raise HTTPException(404, "Parte não encontrada.")
    parte = _linha(linha) or {}
    pool = _pool(pedido)
    id_midia = await pool.fetchval("delete from agentesia_roteiro_gravacoes where id_escritorio = $1::uuid and chave = $2 "
                                   "returning id_midia", ctx.escritorio(), chave_da_parte(parte))
    if id_midia and parte.get("chave_geral") == CHAVE_POS_ASSINATURA:
        url = await pool.fetchval("select url from agentesia_biblioteca_midia where id = $1::uuid", id_midia)
        await _pos_assinatura(pool, ctx.escritorio(), url, None)   # a ZapSign não manda um link que vai sumir
    arquivo_ficou = False
    if id_midia:
        try:
            await apagar_midia(str(id_midia), pedido, ctx)
        except HTTPException:
            arquivo_ficou = True
    return {"ok": True, "arquivo_ficou": arquivo_ficou}
