"""Catálogo de produtos, ativação, números e biblioteca de mídia (contrato em docs/API_PRODUTOS.md).

Mesmo desenho do agents-lawchat-main: o produto do catálogo é a equipe de agentes do funil; o escritório
ativa e vira um agente aqui (produto 'catalogo'), com uma etapa por papel e o prompt de cada uma.
As linhas voltam com os nomes de coluna das tabelas de lá, mais created_at/updated_at e id_conta.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import secrets
import unicodedata
import uuid
from pathlib import Path
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app import armazenamento
from app.gestao.rotas import ADMIN, GESTAO, TODOS, Contexto, _repo

api = APIRouter(prefix="/api")

PAPEIS = ("sdr", "periododegraca", "closer", "contratos", "assinatura", "desqualificado")
NOMES_PAPEL = {"sdr": "SDR", "periododegraca": "Período de Graça", "closer": "Closer", "contratos": "Contratos",
               "assinatura": "Assinatura", "desqualificado": "Desqualificado"}
DESCRICOES_PAPEL = {"sdr": "Recebe, qualifica e agenda o lead", "periododegraca": "Confere a qualidade de segurado",
                    "closer": "Apresenta a solução e quebra objeções", "contratos": "Gera e personaliza o contrato",
                    "assinatura": "Conduz o cliente até a assinatura", "desqualificado": "Encerra com educação leads não viáveis"}
# Para onde cada agente pode passar o lead (como no sistema de referência; desqualificar vale sempre). Contratos não
# passa para Assinatura: quem põe o lead lá é a geração do contrato (o link já existe), como o fluxo 06 do n8n.
DESTINOS = {"sdr": ["periododegraca", "closer", "desqualificado"], "periododegraca": ["closer", "desqualificado"],
            "closer": ["contratos", "desqualificado"], "contratos": ["desqualificado"],
            "assinatura": [], "desqualificado": []}

JSONB = {"exemplos", "etiquetas", "config_modelo", "casos_de_uso", "faq", "objecoes", "padrao_followup", "blocos_prompt",
         "regras_handoff", "canais", "conhecimento", "integracoes", "rascunho", "tags", "biblioteca", "config"}


def _linha(registro: asyncpg.Record | dict | None) -> dict[str, Any] | None:
    if registro is None:
        return None
    saida: dict[str, Any] = {}
    for chave, valor in dict(registro).items():
        if chave in JSONB and isinstance(valor, str):
            try:
                valor = json.loads(valor)
            except json.JSONDecodeError:
                pass
        if hasattr(valor, "isoformat"):
            valor = valor.isoformat()
        elif valor is not None and type(valor).__name__ in ("UUID", "Decimal"):
            valor = str(valor) if type(valor).__name__ == "UUID" else float(valor)
        saida[chave] = valor
    if "criado_em" in saida:
        saida.setdefault("created_at", saida["criado_em"])
    if "atualizado_em" in saida:
        saida.setdefault("updated_at", saida["atualizado_em"])
    if "id_escritorio" in saida:
        saida.setdefault("id_conta", saida["id_escritorio"])
    return saida


def _linhas(registros: list) -> list[dict[str, Any]]:
    return [_linha(r) for r in registros]  # type: ignore[misc]


def _j(valor: Any) -> str:
    return json.dumps(valor, ensure_ascii=False, default=str)


def _pool(pedido: Request) -> asyncpg.Pool:
    return _repo(pedido).pool


def slugificar(texto: str) -> str:
    sem = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", sem).strip("-")[:60] or "produto"


# ============================================================================ catálogo
@api.get("/biblioteca/produtos")
async def listar_produtos(pedido: Request, todos: bool = False, ctx: Contexto = Depends(TODOS)) -> list[dict[str, Any]]:
    situacoes = ["publicado", "em_breve"] + (["rascunho"] if todos and ctx.admin else [])
    return _linhas(await _pool(pedido).fetch(
        # n_agentes: papéis do núcleo (o período de graça é ramo opcional e não entra na contagem, como no painel).
        """select p.*, (select count(*) from agentesia_biblioteca_agentes a where a.id_produto_biblioteca = p.id
                          and a.papel in ('sdr', 'closer', 'contratos', 'assinatura', 'desqualificado'))::int as n_agentes
           from agentesia_biblioteca_produtos p where p.status = any($1::text[]) order by p.nome""", situacoes))


async def _produto(pool: asyncpg.Pool, chave: str, ctx: Contexto) -> dict[str, Any]:
    por_id = re.fullmatch(r"[0-9a-fA-F-]{36}", chave)
    linha = await pool.fetchrow(
        f"select * from agentesia_biblioteca_produtos where {'id = $1::uuid' if por_id else 'slug = $1'}", chave)
    if not linha or (linha["status"] == "rascunho" and not ctx.admin):
        raise HTTPException(404, "Produto não encontrado.")
    return _linha(linha)  # type: ignore[return-value]


@api.get("/biblioteca/produtos/{chave}")
async def ver_produto(chave: str, pedido: Request, ctx: Contexto = Depends(TODOS)) -> dict[str, Any]:
    return await _produto(_pool(pedido), chave, ctx)


@api.get("/biblioteca/produtos/{id_produto}/agentes")
async def agentes_do_produto(id_produto: str, pedido: Request, ctx: Contexto = Depends(TODOS)) -> list[dict[str, Any]]:
    produto = await _produto(_pool(pedido), id_produto, ctx)      # aceita id ou slug
    return _linhas(await _pool(pedido).fetch(
        "select * from agentesia_biblioteca_agentes where id_produto_biblioteca = $1::uuid order by ordem", produto["id"]))


@api.get("/biblioteca/produtos/{id_produto}/documentos")
async def documentos_do_produto(id_produto: str, pedido: Request, ctx: Contexto = Depends(TODOS)) -> list[dict[str, Any]]:
    produto = await _produto(_pool(pedido), id_produto, ctx)      # aceita id ou slug
    return _linhas(await _pool(pedido).fetch(
        """select id, nome, tipo, formato, tamanho_bytes, caracteres, ordem, criado_em, left(texto, 300) as previa
           from agentesia_documentos where id_produto_biblioteca = $1::uuid and ativo order by ordem, criado_em""", produto["id"]))


@api.get("/biblioteca/frases-troca")
async def frases_troca(pedido: Request, id_produto: str | None = None, ctx: Contexto = Depends(TODOS)) -> list[dict[str, Any]]:
    return _linhas(await _pool(pedido).fetch(
        """select * from agentesia_frases_troca
           where id_produto_biblioteca is null or ($1::uuid is not null and id_produto_biblioteca = $1::uuid)
           order by ordem, etapa_destino""", id_produto))


# ============================================================================ admin do catálogo
CAMPOS_PRODUTO = {
    "slug", "nome", "categoria", "icone", "capa_gradiente", "capa_imagem_url", "descricao_curta", "descricao_longa",
    "etiquetas", "modelo_recomendado", "config_modelo", "mensagem_boas_vindas", "casos_de_uso", "plano_minimo",
    "status", "versao", "faq", "objecoes", "regras_markdown", "dados_escritorio", "modo_midia", "id_produto_base",
    "oferece_periodo_graca", "padrao_followup", "mensagem_despedida", "mensagem_fallback", "mensagem_fora_horario",
    "idioma", "blocos_prompt", "exemplos",
}
CAMPOS_AGENTE = {"papel", "nome_exibicao", "descricao", "icone", "ordem", "blocos_prompt", "texto_prompt",
                 "mensagem_boas_vindas", "mensagem_despedida", "mensagem_fallback", "modelo_recomendado",
                 "config_modelo", "regras_handoff"}


def _sql_campos(dados: dict[str, Any], permitidos: set[str], inicio: int = 1) -> tuple[list[str], list[Any]]:
    nomes, valores = [], []
    for nome, valor in dados.items():
        if nome not in permitidos:
            continue
        nomes.append(nome)
        valores.append(_j(valor) if nome in JSONB else valor)
    return nomes, valores


def _cast(nome: str) -> str:
    return "::jsonb" if nome in JSONB else ("::uuid" if nome.startswith("id_") else "")


@api.post("/admin/biblioteca/produtos")
async def criar_produto(dados: dict[str, Any], pedido: Request, ctx: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    if not str(dados.get("nome") or "").strip():
        raise HTTPException(400, "O produto precisa de um nome.")
    dados = {**dados, "slug": slugificar(dados.get("slug") or dados["nome"])}
    nomes, valores = _sql_campos(dados, CAMPOS_PRODUTO)
    marcas = ", ".join(f"${i + 1}{_cast(n)}" for i, n in enumerate(nomes))
    try:
        linha = await _pool(pedido).fetchrow(
            f"insert into agentesia_biblioteca_produtos ({', '.join(nomes)}, criado_por) values ({marcas}, ${len(nomes) + 1}::uuid) returning *",
            *valores, ctx.id_usuario)
    except asyncpg.UniqueViolationError as erro:
        raise HTTPException(409, "Já existe um produto com esse endereço (slug).") from erro
    return _linha(linha)  # type: ignore[return-value]


@api.patch("/admin/biblioteca/produtos/{id_produto}")
async def alterar_produto(id_produto: str, dados: dict[str, Any], pedido: Request, ctx: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    if "slug" in dados:
        dados["slug"] = slugificar(dados["slug"])
    if dados.get("status") not in (None, "rascunho", "em_breve", "publicado"):
        raise HTTPException(400, "Situação inválida.")
    nomes, valores = _sql_campos(dados, CAMPOS_PRODUTO)
    if not nomes:
        return await _produto(_pool(pedido), id_produto, ctx)
    sets = ", ".join(f"{n} = ${i + 2}{_cast(n)}" for i, n in enumerate(nomes))
    try:
        linha = await _pool(pedido).fetchrow(
            f"update agentesia_biblioteca_produtos set {sets} where id = $1::uuid returning *", id_produto, *valores)
    except asyncpg.UniqueViolationError as erro:
        raise HTTPException(409, "Já existe um produto com esse endereço (slug).") from erro
    if not linha:
        raise HTTPException(404, "Produto não encontrado.")
    return _linha(linha)  # type: ignore[return-value]


@api.delete("/admin/biblioteca/produtos/{id_produto}")
async def apagar_produto(id_produto: str, pedido: Request, ctx: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    feito = await _pool(pedido).fetchval("delete from agentesia_biblioteca_produtos where id = $1::uuid returning true", id_produto)
    if not feito:
        raise HTTPException(404, "Produto não encontrado.")
    return {"ok": True}


@api.post("/admin/biblioteca/produtos/{id_produto}/duplicar")
async def duplicar_produto(id_produto: str, pedido: Request, ctx: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    pool = _pool(pedido)
    original = await _produto(pool, id_produto, ctx)
    copia = {k: v for k, v in original.items() if k in CAMPOS_PRODUTO}
    copia.update(nome=original["nome"] + " (cópia)", slug=f"{original['slug']}-copia-{secrets.token_hex(2)}", status="rascunho")
    nova = await criar_produto(copia, pedido, ctx)
    agentes = await pool.fetch("select * from agentesia_biblioteca_agentes where id_produto_biblioteca = $1::uuid", id_produto)
    await _gravar_agentes(pool, nova["id"], [{k: v for k, v in (_linha(a) or {}).items() if k in CAMPOS_AGENTE} for a in agentes])
    return nova


class ProdutoPadrao(BaseModel):
    nome: str = Field(min_length=2)
    area_juridica: str | None = None
    categoria: str = "Previdenciário"
    descricao: str = ""


def _prompt_padrao(papel: str, nome: str, area: str) -> str:
    objetivo = {
        "sdr": f"Receber o lead, entender o caso e qualificar para {nome}. Quando o caso se encaixar, passe para o Comercial com @Comercial; se não se encaixar, @Desqualificado.",
        "periododegraca": "Conferir a qualidade de segurado do lead (último vínculo e contribuições) antes da proposta.",
        "closer": "Apresentar como o escritório pode ajudar, explicar os honorários e quebrar objeções com calma. Com o aceite, passe para @Coleta de Dados.",
        "contratos": "Pedir os dados do contrato (nome completo, CPF, endereço com CEP), mostrar o resumo e, com a confirmação, gerar o contrato com @ZapSign.",
        "assinatura": "Acompanhar a assinatura do contrato: tirar dúvidas de como assinar e confirmar quando estiver assinado.",
        "desqualificado": "Encerrar com educação, explicando de forma simples por que o escritório não pode seguir com o caso.",
    }[papel]
    return (f"# 1. CONTEXTO\n\n{{{{NOME AGENTE}}}} atende pelo escritório {{{{NOME ESCRITORIO}}}} ({area or 'advocacia'}).\n\n"
            f"# 2. OBJETIVO | FUNÇÃO\n\n{objetivo}\n\n# 3. COMO FALAR\n\n- Frases curtas, sem juridiquês.\n- Uma pergunta por vez.\n")


@api.post("/admin/biblioteca/produtos/padrao")
async def criar_produto_padrao(dados: ProdutoPadrao, pedido: Request, ctx: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    produto = await criar_produto({"nome": dados.nome.strip(), "categoria": dados.categoria, "descricao_curta": dados.descricao,
                                   "status": "rascunho"}, pedido, ctx)
    agentes = [{"papel": p, "nome_exibicao": NOMES_PAPEL[p], "descricao": DESCRICOES_PAPEL[p], "ordem": i,
                "blocos_prompt": [{"id": "freeform", "type": "freeform", "icon": "📝", "label": "Prompt",
                                   "content": _prompt_padrao(p, dados.nome, dados.area_juridica or "")},
                                  {"id": "handoff_trigger", "type": "handoff_trigger", "icon": "🔀", "label": "Gatilho de transferência", "content": ""}]}
               for i, p in enumerate(p for p in PAPEIS if p != "periododegraca")]
    await _gravar_agentes(_pool(pedido), produto["id"], agentes)
    return produto


async def _gravar_agentes(pool: asyncpg.Pool, id_produto: str, agentes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    papeis = []
    async with pool.acquire() as conexao, conexao.transaction():
        for i, agente in enumerate(agentes):
            papel = agente.get("papel")
            if papel not in PAPEIS:
                raise HTTPException(400, f"Papel inválido: {papel}")
            papeis.append(papel)
            dados = {"nome_exibicao": NOMES_PAPEL[papel], "ordem": i, **agente}
            nomes, valores = _sql_campos(dados, CAMPOS_AGENTE - {"papel"})
            colunas = ", ".join(nomes)
            marcas = ", ".join(f"${j + 3}{_cast(n)}" for j, n in enumerate(nomes))
            atualiza = ", ".join(f"{n} = excluded.{n}" for n in nomes)
            await conexao.execute(
                f"""insert into agentesia_biblioteca_agentes (id_produto_biblioteca, papel, {colunas}) values ($1::uuid, $2, {marcas})
                    on conflict (id_produto_biblioteca, papel) do update set {atualiza}""", id_produto, papel, *valores)
        await conexao.execute("delete from agentesia_biblioteca_agentes where id_produto_biblioteca = $1::uuid and not (papel = any($2::text[]))",
                              id_produto, papeis)
        await conexao.execute("update agentesia_biblioteca_produtos set atualizado_em = now() where id = $1::uuid", id_produto)
    return _linhas(await pool.fetch("select * from agentesia_biblioteca_agentes where id_produto_biblioteca = $1::uuid order by ordem", id_produto))


@api.put("/admin/biblioteca/produtos/{id_produto}/agentes")
async def salvar_agentes_do_produto(id_produto: str, agentes: list[dict[str, Any]], pedido: Request,
                                    ctx: Contexto = Depends(ADMIN)) -> list[dict[str, Any]]:
    await _produto(_pool(pedido), id_produto, ctx)
    return await _gravar_agentes(_pool(pedido), id_produto, agentes)


class Frase(BaseModel):
    id: str | None = None
    id_produto_biblioteca: str | None = None
    etapa_destino: str
    nome: str
    frase: str
    descricao: str | None = None
    ordem: int = 0


@api.put("/admin/biblioteca/frases-troca")
async def salvar_frase(dados: Frase, pedido: Request, ctx: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    frase = dados.frase.strip()
    if not 8 <= len(frase) <= 400 or "\n" in frase or re.search(r'[@{}"\\\[\]]', frase):
        raise HTTPException(400, "A frase precisa ter de 8 a 400 caracteres, numa linha só, sem @ { } \" \\ [ ].")
    pool = _pool(pedido)
    anterior = await pool.fetchval("select frase from agentesia_frases_troca where id = $1::uuid", dados.id) if dados.id else None
    linha = await pool.fetchrow(
        """insert into agentesia_frases_troca (id, id_produto_biblioteca, etapa_destino, nome, frase, descricao, ordem)
           values (coalesce($1::uuid, gen_random_uuid()), $2::uuid, $3, $4, $5, $6, $7)
           on conflict (id) do update set etapa_destino = excluded.etapa_destino, nome = excluded.nome, frase = excluded.frase,
             descricao = excluded.descricao, ordem = excluded.ordem returning *""",
        dados.id, dados.id_produto_biblioteca, dados.etapa_destino, dados.nome.strip(), frase, dados.descricao, dados.ordem)
    if anterior and anterior != frase:
        # Como no sistema de referência: o texto novo entra nos prompts dos agentes já ativados.
        await pool.execute(
            """update agentesia_agente_etapas e set instrucao = replace(e.instrucao, $1, $2)
               from agentesia_agentes a where a.id = e.id_agente and a.produto = 'catalogo' and position($1 in e.instrucao) > 0
                 and ($3::uuid is null or a.config -> 'catalogo' ->> 'id_produto_biblioteca' = $3::text)""",
            anterior, frase, dados.id_produto_biblioteca)
    return _linha(linha)  # type: ignore[return-value]


@api.delete("/admin/biblioteca/frases-troca/{id_frase}")
async def apagar_frase(id_frase: str, pedido: Request, ctx: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    await _pool(pedido).execute("delete from agentesia_frases_troca where id = $1::uuid", id_frase)
    return {"ok": True}


class DocumentoNovo(BaseModel):
    nome: str = Field(min_length=1, max_length=200)
    tipo: str = "arquivo"
    conteudo_base64: str | None = None
    texto: str | None = None
    mime: str | None = None


def ler_documento(dados: DocumentoNovo) -> tuple[str, str, int]:
    """(texto, formato, tamanho). Arquivo: o servidor lê o texto; colar texto: guarda como está."""
    from app import conhecimento as base
    from app.midia.extrair import ErroArquivo, detectar_formato, extrair_texto

    if dados.tipo == "texto":
        texto = (dados.texto or "").strip()
        if len(texto) < 3:
            raise HTTPException(400, "Cole o texto que o agente deve conhecer.")
        return texto[:base.LIMITE_DOCUMENTO], "texto", len(texto.encode())
    try:
        bruto = base64.b64decode((dados.conteudo_base64 or "").split(",")[-1], validate=True)
    except (binascii.Error, ValueError) as erro:
        raise HTTPException(400, "Arquivo inválido (não veio em base64).") from erro
    if len(bruto) > base.LIMITE_ARQUIVO:
        raise HTTPException(413, "Arquivo grande demais: o limite é 8 MB.")
    formato = detectar_formato(bruto, dados.mime, dados.nome)
    if dados.nome.lower().endswith((".json", ".md", ".csv", ".txt")) and formato == "desconhecido":
        formato = "texto"
    if formato not in ("pdf", "docx", "xlsx", "texto"):
        raise HTTPException(400, "Formato não suportado. Use PDF, DOCX, TXT/MD ou cole o texto.")
    try:
        texto = extrair_texto(bruto, formato)[:base.LIMITE_DOCUMENTO]
    except ErroArquivo as erro:
        motivos = {"sem_texto": "Não consegui ler texto desse arquivo (PDF escaneado ou imagem). Envie a versão em texto.",
                   "protegido": "O PDF tem senha. Envie sem senha.", "corrompido": "Não foi possível abrir o arquivo."}
        raise HTTPException(400, motivos.get(erro.codigo, "Não foi possível ler o arquivo.")) from erro
    return texto, formato, len(bruto)


@api.post("/admin/biblioteca/produtos/{id_produto}/documentos")
async def criar_documento_padrao(id_produto: str, dados: DocumentoNovo, pedido: Request, ctx: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    await _produto(_pool(pedido), id_produto, ctx)
    texto, formato, tamanho = ler_documento(dados)
    linha = await _pool(pedido).fetchrow(
        """insert into agentesia_documentos (id_produto_biblioteca, tipo, nome, formato, tamanho_bytes, texto, caracteres,
                                             situacao, origem, travado, criado_por)
           values ($1::uuid, $2, $3, $4, $5, $6, length($6), 'pronto', 'produto', true, $7::uuid)
           returning id, nome, tipo, formato, tamanho_bytes, caracteres, criado_em""",
        id_produto, "texto" if dados.tipo == "texto" else "arquivo", dados.nome.strip(), formato, tamanho, texto, ctx.id_usuario)
    return _linha(linha)  # type: ignore[return-value]


@api.delete("/admin/biblioteca/produtos/{id_produto}/documentos/{id_doc}")
async def apagar_documento_padrao(id_produto: str, id_doc: str, pedido: Request, ctx: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    await _pool(pedido).execute("delete from agentesia_documentos where id = $1::uuid and id_produto_biblioteca = $2::uuid", id_doc, id_produto)
    return {"ok": True}


class ArquivoImportacao(BaseModel):
    nome: str = Field(min_length=1, max_length=300)
    conteudo_base64: str = Field(min_length=4)


class Importacao(BaseModel):
    arquivos: list[ArquivoImportacao] = Field(min_length=1, max_length=10)
    aplicar: bool = False                     # False = só mostra o que vai acontecer


@api.post("/admin/biblioteca/importar")
async def importar_catalogo(dados: Importacao, pedido: Request, ctx: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    """Importa o catálogo exportado do agents-lawchat-main (docs/EXPORTAR_CATALOGO.sql). Prévia primeiro, depois aplica."""
    from app.catalogo_importar import ErroImportacao, importar, ler_arquivos

    arquivos = []
    for arquivo in dados.arquivos:
        try:
            bruto = base64.b64decode(arquivo.conteudo_base64.split(",")[-1], validate=True)
        except (binascii.Error, ValueError) as erro:
            raise HTTPException(400, f"{arquivo.nome}: arquivo inválido (não veio em base64).") from erro
        if len(bruto) > 40 * 1024 * 1024:
            raise HTTPException(413, f"{arquivo.nome}: arquivo grande demais (limite de 40 MB).")
        arquivos.append((arquivo.nome, bruto))
    try:
        lidos = ler_arquivos(arquivos)
        plano = await importar(_pool(pedido), lidos, simular=not dados.aplicar, criado_por=ctx.id_usuario)
    except ErroImportacao as erro:
        raise HTTPException(400, str(erro)) from erro
    except asyncpg.PostgresError as erro:     # nada foi gravado (a importação é uma transação só)
        raise HTTPException(400, f"O banco recusou a importação e nada foi gravado: {str(erro)[:300]}") from erro
    if plano.aplicado:
        await _repo(pedido).registrar_alteracao(
            id_usuario=ctx.id_usuario, id_escritorio=None, tabela="agentesia_biblioteca_produtos", id_registro=None,
            acao="importou", resumo=f"Catálogo importado: {len(plano.produtos)} produto(s) do agents-lawchat-main")
    return plano.como_dict()


# ============================================================================ produtos ativados
_SELECT_ATIVADO = """select p.*, (select row_to_json(b) from (select id, slug, nome, icone, capa_gradiente, descricao_curta, categoria,
                            versao, oferece_periodo_graca, modo_midia from agentesia_biblioteca_produtos
                            where id = p.id_produto_biblioteca) b) as biblioteca,
                            -- Agente sem número (foi para a lixeira e soltou o canal): precisa escolher o número e ativar de novo.
                            coalesce((select a.id_canal is null from agentesia_agentes a where a.id = p.id_agente), false) as precisa_ativar,
                            (select c.numero_normalizado from agentesia_agentes a join agentesia_canais c on c.id = a.id_canal_anterior
                              where a.id = p.id_agente and a.id_canal is null) as numero_liberado,
                            (select a.config->'followup' from agentesia_agentes a where a.id = p.id_agente) as followup_config
                     from agentesia_produtos_ativados p"""


async def _ativado(pool: asyncpg.Pool, id_escritorio: str, id_ativado: str) -> dict[str, Any]:
    linha = await pool.fetchrow(_SELECT_ATIVADO + " where p.id = $1::uuid and p.id_escritorio = $2::uuid", id_ativado, id_escritorio)
    if not linha:
        raise HTTPException(404, "Produto não encontrado.")
    return _com_followup(_linha(linha))  # type: ignore[arg-type]


def _com_followup(linha: dict[str, Any]) -> dict[str, Any]:
    """followup: null (contrato antigo da API) e followup_situacao: ligado, cadência resumida (docs/FOLLOWUP.md)."""
    from app.followup import padrao as padrao_fu
    bruto = linha.pop("followup_config", None)
    if isinstance(bruto, str):
        bruto = json.loads(bruto or "null")
    linha["followup"] = None
    linha["followup_situacao"] = padrao_fu.situacao({"followup": bruto} if bruto is not None else {}) if linha.get("id_agente") else None
    return linha


@api.get("/produtos-ativados")
async def meus_produtos(pedido: Request, lixeira: int = 0, ctx: Contexto = Depends(GESTAO)) -> list[dict[str, Any]]:
    filtro = ("p.excluido_em is not null and p.excluido_em > now() - interval '30 days'" if lixeira else "p.excluido_em is null")
    linhas = _linhas(await _pool(pedido).fetch(
        _SELECT_ATIVADO + f" where p.id_escritorio = $1::uuid and {filtro} order by coalesce(p.excluido_em, p.criado_em) desc",
        ctx.escritorio()))
    return [_com_followup(linha) for linha in linhas]


@api.get("/produtos-ativados/{id_ativado}")
async def ver_ativado(id_ativado: str, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    pool = _pool(pedido)
    produto = await _ativado(pool, ctx.escritorio(), id_ativado)
    etapas: list[dict[str, Any]] = []
    variables: dict[str, Any] = {}
    comportamento: dict[str, Any] | None = None
    if produto.get("id_agente"):
        agente = await pool.fetchrow("select config, id_canal, minutos_pausa_humano from agentesia_agentes where id = $1::uuid", produto["id_agente"])
        config = json.loads(agente["config"]) if agente and isinstance(agente["config"], str) else (agente["config"] if agente else {}) or {}
        if agente:
            comportamento = {"id": produto["id_agente"], "modelo": (config.get("modelos") or {}).get("etapa") or "gpt-4.1-mini",
                             "temperatura": config.get("temperatura", 0.7), "delay_s": config.get("espera_s", 10),
                             "pausa_min": -1 if config.get("pausa_sem_volta") else agente["minutos_pausa_humano"],
                             "id_canal": str(agente["id_canal"]) if agente["id_canal"] else None}
        catalogo = config.get("catalogo") or {}
        variables = config.get("variables") or {}
        for e in await pool.fetch(
                """select id, codigo, ordem, instrucao, temperatura, modelo from agentesia_agente_etapas
                   where id_agente = $1::uuid and tipo = 'conversa' order by ordem""", produto["id_agente"]):
            papel = catalogo.get("papeis", {}).get(e["codigo"], {})
            etapas.append({"id": str(e["id"]), "id_agente": produto["id_agente"], "etapa": e["codigo"], "ordem": e["ordem"],
                           "prompt": e["instrucao"] or "", "nome": papel.get("nome") or NOMES_PAPEL.get(e["codigo"], e["codigo"]),
                           "mensagem_troca": papel.get("mensagem_troca"),
                           "config": {"welcome_message": papel.get("boas_vindas"), "boas_vindas": papel.get("boas_vindas"), "variables": variables,
                                      "model_config": {"temperature": float(e["temperatura"]), "model": e["modelo"]}}})
    return {**produto, "etapas": etapas, "variables": variables, "agente": comportamento,
            "id_canal": comportamento["id_canal"] if comportamento else None}


class Rascunho(BaseModel):
    id_produto_biblioteca: str
    nome: str | None = None          # nome que o cliente deu ao agente (Identidade)
    numero_ia: str | None = None


@api.post("/produtos-ativados/rascunho")
async def rascunho(dados: Rascunho, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Acha ou cria o rascunho do escritório para o produto (um por produto)."""
    pool = _pool(pedido)
    catalogo = await _produto(pool, dados.id_produto_biblioteca, ctx)
    if catalogo["status"] != "publicado" and not ctx.admin:
        raise HTTPException(409, "Este produto ainda está em breve.")
    existente = await pool.fetchval(
        """select id from agentesia_produtos_ativados where id_escritorio = $1::uuid and id_produto_biblioteca = $2::uuid
           and status = 'rascunho' and excluido_em is null""", ctx.escritorio(), catalogo["id"])
    if not existente:
        existente = await pool.fetchval(
            """insert into agentesia_produtos_ativados (id_escritorio, id_produto_biblioteca, nome, descricao, faq, objecoes,
                                                      regras_markdown, dados_escritorio, versao_template)
               values ($1::uuid, $2::uuid, $3, $4, $5::jsonb, $6::jsonb, $7, $8, $9)
               on conflict do nothing returning id""",
            ctx.escritorio(), catalogo["id"], (dados.nome or "").strip()[:120] or catalogo["nome"], catalogo.get("descricao_curta"), _j(catalogo.get("faq") or []),
            _j(catalogo.get("objecoes") or []), catalogo.get("regras_markdown"), catalogo.get("dados_escritorio"), catalogo.get("versao"))
        if not existente:                    # outro pedido criou ao mesmo tempo
            existente = await pool.fetchval(
                """select id from agentesia_produtos_ativados where id_escritorio = $1::uuid and id_produto_biblioteca = $2::uuid
                   and status = 'rascunho' and excluido_em is null""", ctx.escritorio(), catalogo["id"])
    if dados.nome or dados.numero_ia:   # escolhas da Identidade valem também para o rascunho que já existia
        await pool.execute(
            """update agentesia_produtos_ativados set nome = coalesce($2, nome), numero_ia = coalesce($3, numero_ia)
               where id = $1::uuid""", existente, (dados.nome or "").strip()[:120] or None, dados.numero_ia or None)
    return await _ativado(pool, ctx.escritorio(), str(existente))


SEM_NUMERO = ("Este produto está sem número de WhatsApp (o número foi liberado quando ele foi para a lixeira). "
              "Abra o produto, escolha o número e ative.")

CAMPOS_ATIVADO = {"nome", "descricao", "faq", "objecoes", "conhecimento", "dados_escritorio", "regras_markdown", "integracoes",
                  "numero_ia", "rascunho", "status", "versao_template", "periodo_graca_ativo", "excluido_em", "canais"}


@api.patch("/produtos-ativados/{id_ativado}")
async def alterar_ativado(id_ativado: str, dados: dict[str, Any], pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    pool = _pool(pedido)
    atual = await _ativado(pool, ctx.escritorio(), id_ativado)
    if dados.get("status") not in (None, "rascunho", "ativo", "pausado", "erro"):
        raise HTTPException(400, "Situação inválida.")
    if dados.get("status") == "ativo" and atual.get("precisa_ativar"):
        raise HTTPException(409, SEM_NUMERO)
    nomes, valores = _sql_campos({k: v for k, v in dados.items() if k != "excluido_em"}, CAMPOS_ATIVADO)
    if nomes:
        sets = ", ".join(f"{n} = ${i + 3}{_cast(n)}" for i, n in enumerate(nomes))
        await pool.execute(f"update agentesia_produtos_ativados set {sets} where id = $1::uuid and id_escritorio = $2::uuid",
                           id_ativado, ctx.escritorio(), *valores)
    if "excluido_em" in dados:
        # A data é a do servidor (o painel manda o ISO do navegador, que o asyncpg não aceita como timestamptz).
        if dados["excluido_em"]:
            await _para_a_lixeira(pool, ctx, atual)
            resumo = f"Produto na lixeira: {atual['nome']}" + (f" (número {atual['numero_ia']} liberado)" if atual.get("numero_ia") and atual.get("id_agente") else "")
        elif atual.get("excluido_em"):
            await _restaurar(pool, ctx, atual)
            resumo = f"Produto restaurado da lixeira: {atual['nome']} (sem número: precisa ativar)"
        else:
            resumo = None
        if resumo:
            await _repo(pedido).registrar_alteracao(
                id_usuario=ctx.id_usuario, id_escritorio=ctx.escritorio(), tabela="agentesia_produtos_ativados",
                id_registro=id_ativado, acao="alterou", resumo=resumo)
    return await _ativado(pool, ctx.escritorio(), id_ativado)


async def _soltar_canal(conexao: Any, id_agente: str, motivo: str) -> str | None:
    """Solta o número do agente (decisão do dono: produto na lixeira libera o WhatsApp para outro produto).
    O agente fica pausado e sem número (o número anterior fica só de histórico) e os follow-ups pendentes dos
    leads dele são cancelados. O motor acha o agente pelo canal: número solto = ninguém responde nele até outro
    produto ativar ali. Leads e conversas ficam como estão (o lead é do número, não do agente).
    Devolve o id do canal que foi solto (None se já estava sem número)."""
    id_canal = await conexao.fetchval(
        """update agentesia_agentes a set id_canal_anterior = coalesce(a.id_canal, a.id_canal_anterior), id_canal = null,
                  canal_liberado_em = case when a.id_canal is null then a.canal_liberado_em else now() end, situacao = 'pausado'
           from agentesia_agentes antes where antes.id = a.id and a.id = $1::uuid returning antes.id_canal""", id_agente)
    await conexao.execute(
        """update agentesia_followups set situacao = 'cancelado', motivo = $2, atualizado_em = now()
           where situacao in ('pendente', 'reservado')
             and (id_agente = $1::uuid or id_lead in (select id from agentesia_leads where id_agente = $1::uuid))""",
        id_agente, motivo)
    return str(id_canal) if id_canal else None


async def _adotar_leads_do_numero(conexao: Any, id_agente: str, id_canal: str) -> int:
    """O agente que assume um número herda os leads dele. O lead é único por número e contato, e o motor acha o
    agente pelo canal: o lead que falou com o produto antigo (na lixeira ou excluído) ficaria preso numa etapa que
    o agente novo não tem e a IA não responderia ("agente_sem_etapa"). Ele entra no início do funil novo; estado
    (pausa do atendente, pediu para parar, encerrado) e conversa ficam como estão. Os leads do próprio agente
    (reativou no mesmo número) não mudam."""
    resultado = await conexao.execute(
        """update agentesia_leads l
              set id_agente = $1::uuid, atualizado_em = now(),
                  id_etapa = (select e.id from agentesia_agente_etapas e where e.id_agente = $1::uuid and e.principal)
            where l.id_canal = $2::uuid and l.id_agente is distinct from $1::uuid
              and l.id_escritorio = (select a.id_escritorio from agentesia_agentes a where a.id = $1::uuid)""",
        id_agente, id_canal)
    return int(resultado.split()[-1])


async def _para_a_lixeira(pool: asyncpg.Pool, ctx: Contexto, produto: dict[str, Any]) -> None:
    """Lixeira: o produto fica pausado e SEM número (o canal volta a aparecer como disponível). A ativação salva
    perde o número, para que reenviar/restaurar nunca pegue de volta um número que outro produto pode ter usado."""
    async with pool.acquire() as conexao, conexao.transaction():
        await conexao.execute(
            """update agentesia_produtos_ativados set excluido_em = now(),
                      status = case when id_agente is null then status else 'pausado' end,
                      numero_ia = case when id_agente is null then numero_ia else null end,
                      rascunho = rascunho #- '{payload_ativacao,id_canal}' #- '{payload_ativacao,numero_ia}'
               where id = $1::uuid and id_escritorio = $2::uuid""", produto["id"], ctx.escritorio())
        if produto.get("id_agente"):
            await _soltar_canal(conexao, produto["id_agente"], "produto_na_lixeira")


async def _restaurar(pool: asyncpg.Pool, ctx: Contexto, produto: dict[str, Any]) -> None:
    """Restaurar NÃO devolve o número: o produto volta pausado e sem canal ("precisa ativar"). O cliente escolhe o
    número de novo na tela do produto e ativa (reaproveitando o agente, os prompts e o contrato)."""
    try:
        await pool.execute(
            """update agentesia_produtos_ativados set excluido_em = null,
                      status = case when id_agente is null then status else 'pausado' end
               where id = $1::uuid and id_escritorio = $2::uuid""", produto["id"], ctx.escritorio())
    except asyncpg.UniqueViolationError as erro:   # rascunho nunca ativado: já existe outro rascunho do mesmo produto
        raise HTTPException(409, "Já existe um rascunho deste produto em andamento. Continue por ele ou exclua-o antes de restaurar.") from erro


class AgenteDoFunil(BaseModel):
    papel: str
    nome: str | None = None
    boas_vindas: str | None = None
    prompt: str = ""
    mensagem_troca: str | None = None


class Ativar(BaseModel):
    nome: str | None = None
    numero_ia: str | None = None
    id_canal: str | None = None
    delay_s: int = 10
    pausa_min: int = 30
    temperatura: float = 0.7
    modelo: str = "gpt-4.1-mini"
    ativar_imediatamente: bool = True
    periodo_graca_ativo: bool = False
    agentes: list[AgenteDoFunil] = Field(default_factory=list)
    faq: list[dict[str, Any]] | None = None
    objecoes: list[dict[str, Any]] | None = None
    regras_markdown: str | None = None
    dados_escritorio: str | None = None
    variables: dict[str, Any] = Field(default_factory=dict)
    reenviar: bool = False
    # Etapa "Follow-up" da ativação. None = o padrão: liga na ativação; na sincronização de um agente que ainda não
    # tem follow-up, copia a cadência desligada (quem liga é o cliente ou o admin, nunca a sincronização sozinha).
    # Agente que já tem config.followup não muda por aqui (é a aba Follow-up que manda).
    followup_ativo: bool | None = None


async def _canal(pool: asyncpg.Pool, id_escritorio: str, dados: Ativar, id_agente_atual: str | None) -> dict[str, Any] | None:
    """O número escolhido na ativação. Sem número escolhido: None (o agente é criado e configurado sem número; o
    número entra depois, quando o WhatsApp for conectado). Número escolhido que não existe: 400."""
    from app.canal.helena import normalizar_telefone

    if not dados.id_canal and not (dados.numero_ia or "").strip():
        return None
    canal = None
    if dados.id_canal:
        canal = await pool.fetchrow("select * from agentesia_canais where id = $1::uuid and id_escritorio = $2::uuid", dados.id_canal, id_escritorio)
    elif dados.numero_ia:
        digitos = re.sub(r"\D", "", dados.numero_ia)
        canal = await pool.fetchrow(
            """select * from agentesia_canais where id_escritorio = $1::uuid
               and right(numero_normalizado, 11) = right($2, 11) order by ativo desc limit 1""",
            id_escritorio, normalizar_telefone(digitos) or digitos)
    if not canal:
        raise HTTPException(400, "Escolha o número de WhatsApp (use Sincronizar para buscar na Helena).")
    ocupante = await pool.fetchrow("select id, nome from agentesia_agentes where id_canal = $1::uuid", canal["id"])
    if ocupante and str(ocupante["id"]) != (id_agente_atual or ""):
        raise HTTPException(409, f"Este número já está em uso pelo agente {ocupante['nome']}.")
    return dict(canal)


def _config_do_agente(dados: Ativar, catalogo: dict[str, Any], produto: dict[str, Any], tem_zapsign: bool) -> dict[str, Any]:
    papeis = {a.papel: {"nome": a.nome or NOMES_PAPEL.get(a.papel, a.papel), "boas_vindas": (a.boas_vindas or "").strip() or None,
                        "mensagem_troca": (a.mensagem_troca or "").strip() or None,
                        "destinos": [d for d in DESTINOS.get(a.papel, []) if d in {x.papel for x in dados.agentes}]}
              for a in dados.agentes}
    faq = dados.faq if dados.faq is not None else produto.get("faq") or []
    objecoes = dados.objecoes if dados.objecoes is not None else produto.get("objecoes") or []
    return {
        "espera_s": max(0, min(int(dados.delay_s), 120)),
        "pausa_sem_volta": dados.pausa_min < 0,
        "temperatura": max(0.0, min(float(dados.temperatura), 2.0)),
        "modelos": {"etapa": dados.modelo, "extrator": "gpt-4.1-mini"},
        "catalogo": {"id_produto_biblioteca": catalogo.get("id"), "slug": catalogo.get("slug"), "modo_midia": catalogo.get("modo_midia"),
                     "papeis": papeis, "regras": dados.regras_markdown if dados.regras_markdown is not None else produto.get("regras_markdown")},
        "conhecimento": {
            "faq": [{"pergunta": f.get("pergunta") or f.get("q") or "", "resposta": f.get("resposta") or f.get("a") or ""} for f in faq],
            "objecoes": [{"objecao": o.get("titulo") or o.get("gatilho") or o.get("objecao") or "", "resposta": o.get("resposta") or ""} for o in objecoes],
            "dados_escritorio": dados.dados_escritorio if dados.dados_escritorio is not None else produto.get("dados_escritorio") or "",
        },
        "funcoes": {"contrato_zapsign": tem_zapsign, "buscar_cep": True},
        "variables": dados.variables or {},
    }


def juntar_config(antigo: dict[str, Any], novo: dict[str, Any]) -> dict[str, Any]:
    """Config do agente ao reativar ou sincronizar o produto: a nova por cima da antiga, mas as funções se somam.
    Com o merge raso, crm, avisos e transferir_humano que o escritório ligou voltavam a desligadas a cada
    sincronização (o CRM parava de mover card e trocar etiqueta sem ninguém saber). contrato_zapsign e buscar_cep
    continuam vindo da ativação."""
    funcoes = {**((antigo or {}).get("funcoes") or {}), **(novo.get("funcoes") or {})}
    return {**(antigo or {}), **novo, "funcoes": funcoes}


async def _vincular_contrato(conexao: Any, id_escritorio: str, id_ativado: str, id_agente: str) -> None:
    """O modelo de contrato salvo pela tela do produto (antes de existir o agente) ganha o id_agente:
    é por ele que o motor escolhe o modelo do lead. Linha travada, como nas rotas da ZapSign."""
    from app.contrato import modelos as cmodelos
    await _mudar_modelos_zapsign(conexao, id_escritorio, lambda modelos: cmodelos.vincular_agente(modelos, id_ativado, id_agente))


async def _tirar_contrato(conexao: Any, id_escritorio: str, id_ativado: str, id_agente: str | None) -> None:
    """Exclusão do produto: o modelo de contrato dele sai da lista (o padrão vira modelo geral)."""
    from app.contrato import modelos as cmodelos
    await _mudar_modelos_zapsign(conexao, id_escritorio,
                                 lambda modelos: cmodelos.remover_do_produto(modelos, id_ativado, str(id_agente) if id_agente else None))


async def _mudar_modelos_zapsign(conexao: Any, id_escritorio: str, mudar: Any) -> None:
    """mudar(modelos) devolve a lista nova, ou None quando não há nada a mudar."""
    linha = await conexao.fetchrow(
        "select id, config from agentesia_integracoes where id_escritorio = $1::uuid and tipo = 'zapsign' for update", id_escritorio)
    if not linha:
        return
    config = json.loads(linha["config"]) if isinstance(linha["config"], str) else dict(linha["config"] or {})
    novos = mudar(config.get("modelos"))
    if novos is not None:
        await conexao.execute("update agentesia_integracoes set config = $2::jsonb where id = $1::uuid",
                              linha["id"], _j({**config, "modelos": novos}))


async def _montar_agente(pedido: Request, ctx: Contexto, id_ativado: str, dados: Ativar, sincronizar: bool) -> dict[str, Any]:
    pool = _pool(pedido)
    produto = await _ativado(pool, ctx.escritorio(), id_ativado)
    if dados.reenviar and not dados.agentes:
        salvo = (produto.get("rascunho") or {}).get("payload_ativacao")
        if not salvo:
            raise HTTPException(409, "Não há ativação salva para reenviar. Abra o produto e ative de novo.")
        dados = Ativar(**salvo)
    papeis = [a.papel for a in dados.agentes]
    if not papeis or any(p not in PAPEIS for p in papeis):
        raise HTTPException(400, "Envie os agentes do funil (SDR, Closer, Contratos, Assinatura, Desqualificado).")
    catalogo = (await pool.fetchrow("select * from agentesia_biblioteca_produtos where id = $1::uuid", produto["id_produto_biblioteca"])
                if produto.get("id_produto_biblioteca") else None)
    catalogo = _linha(catalogo) or {}
    id_agente = produto.get("id_agente")
    canal = await _canal(pool, ctx.escritorio(), dados, id_agente)
    tem_zapsign = bool(await pool.fetchval(
        "select true from agentesia_integracoes where id_escritorio = $1::uuid and tipo = 'zapsign' and situacao = 'ok'", ctx.escritorio()))
    config = _config_do_agente(dados, catalogo, produto, tem_zapsign)
    nome = (dados.nome or produto["nome"]).strip()[:120]
    # Produto que voltou da lixeira (agente sem número): esta é a reativação, com o número escolhido agora.
    reativando = bool(id_agente and produto.get("precisa_ativar"))
    if reativando and canal is None:
        # Volta da lixeira: o número antigo foi liberado; para ativar de novo, escolha um número.
        raise HTTPException(400, "Escolha o número de WhatsApp para ativar de novo (use Sincronizar para buscar na LawChat).")
    pausa = 15 if dados.pausa_min < 0 else max(1, min(int(dados.pausa_min), 10080))
    etapas = [(p, "conversa") for p in PAPEIS if p in papeis] + [("contrato_assinado", "terminal")]
    prompts = {a.papel: a.prompt for a in dados.agentes}
    temperatura = max(0.0, min(float(dados.temperatura), 2.0))
    async with pool.acquire() as conexao, conexao.transaction():
        if id_agente:
            antigo = await conexao.fetchval("select config from agentesia_agentes where id = $1::uuid", id_agente)
            antigo = json.loads(antigo) if isinstance(antigo, str) else (antigo or {})
            config = juntar_config(antigo, config)
            config = _com_followup_padrao(config, catalogo, dados, sincronizar and not reativando)
            try:
                await conexao.execute(
                    """update agentesia_agentes set nome = $2, id_canal = coalesce($3::uuid, id_canal), minutos_pausa_humano = $4, config = $5::jsonb,
                              id_produto_ativado = $6::uuid, canal_liberado_em = null,
                              situacao = case when $7 then $8 else situacao end
                       where id = $1::uuid""",
                    id_agente, nome, canal["id"] if canal else None, pausa, _j(config), id_ativado, reativando,
                    "ativo" if dados.ativar_imediatamente else "pausado")
            except asyncpg.UniqueViolationError as erro:     # outro produto pegou o número entre a conferência e agora
                raise HTTPException(409, "Este número acabou de ser usado por outro agente. Escolha outro.") from erro
        else:
            config = _com_followup_padrao(config, catalogo, dados, False)
            try:
                id_agente = str(await conexao.fetchval(
                    """insert into agentesia_agentes (id_escritorio, id_canal, nome, produto, situacao, modo, minutos_pausa_humano, config, id_produto_ativado)
                       values ($1::uuid, $2::uuid, $3, 'catalogo', $4, 'producao', $5, $6::jsonb, $7::uuid) returning id""",
                    ctx.escritorio(), canal["id"] if canal else None, nome, "ativo" if dados.ativar_imediatamente else "pausado", pausa, _j(config), id_ativado))
            except asyncpg.UniqueViolationError as erro:     # dois produtos ativando no mesmo número ao mesmo tempo
                raise HTTPException(409, "Este número acabou de ser usado por outro agente. Escolha outro.") from erro
        codigos = [c for c, _ in etapas]
        em_uso = [r["codigo"] for r in await conexao.fetch(
            """select distinct e.codigo from agentesia_agente_etapas e join agentesia_leads l on l.id_etapa = e.id
               where e.id_agente = $1::uuid and not (e.codigo = any($2::text[]))""", id_agente, codigos)]
        if em_uso:
            raise HTTPException(409, f"Há leads nas etapas {', '.join(em_uso)}; não dá para tirar essas etapas agora.")
        await conexao.execute("delete from agentesia_agente_etapas where id_agente = $1::uuid and not (codigo = any($2::text[]))", id_agente, codigos)
        await conexao.execute("update agentesia_agente_etapas set principal = false where id_agente = $1::uuid", id_agente)
        for ordem, (codigo, tipo) in enumerate(etapas, start=1):
            await conexao.execute(
                """insert into agentesia_agente_etapas (id_agente, codigo, ordem, tipo, principal, instrucao, modelo, temperatura)
                   values ($1::uuid, $2, $3, $4, $5, $6, $7, $8)
                   on conflict (id_agente, codigo) do update set ordem = excluded.ordem, tipo = excluded.tipo, principal = excluded.principal,
                     instrucao = excluded.instrucao, modelo = excluded.modelo, temperatura = excluded.temperatura""",
                id_agente, codigo, ordem, tipo, ordem == 1, prompts.get(codigo), dados.modelo, temperatura)
        if canal:
            await _adotar_leads_do_numero(conexao, str(id_agente), str(canal["id"]))
        # Documentos padrão do produto: copiados travados, uma vez só (id_origem).
        if catalogo.get("id"):
            await conexao.execute(
                """insert into agentesia_documentos (id_escritorio, id_agente, id_origem, tipo, nome, formato, tamanho_bytes, texto,
                                                     caracteres, situacao, origem, travado, ordem)
                   select $1::uuid, $2::uuid, d.id, d.tipo, d.nome, d.formato, d.tamanho_bytes, d.texto, d.caracteres,
                          'processando', 'produto', true, d.ordem
                   from agentesia_documentos d where d.id_produto_biblioteca = $3::uuid and d.ativo
                   on conflict (id_agente, id_origem) where id_origem is not null do nothing""",
                ctx.escritorio(), id_agente, catalogo["id"])
        await _vincular_contrato(conexao, ctx.escritorio(), str(produto["id"]), str(id_agente))
        rascunho_salvo = {**(produto.get("rascunho") or {}), "payload_ativacao": dados.model_dump()}
        if reativando:      # volta da lixeira: ativa já (padrão) ou fica pausado; nunca "rascunho" (já tem agente)
            status = "ativo" if dados.ativar_imediatamente else "pausado"
        elif sincronizar and produto["status"] in ("ativo", "pausado"):
            status = produto["status"]
        else:
            status = "ativo" if dados.ativar_imediatamente else "rascunho"
        await conexao.execute(
            """update agentesia_produtos_ativados set id_agente = $2::uuid, nome = $3, numero_ia = coalesce($4, numero_ia), status = $5,
                      status_provisionamento = 'pronto', erro_provisionamento = null, periodo_graca_ativo = $6, rascunho = $7::jsonb,
                      faq = coalesce($8::jsonb, faq), objecoes = coalesce($9::jsonb, objecoes),
                      regras_markdown = coalesce($10, regras_markdown), dados_escritorio = coalesce($11, dados_escritorio),
                      versao_template = coalesce(versao_template, $12)
               where id = $1::uuid""",
            id_ativado, id_agente, nome, canal["numero_normalizado"] if canal else None, status, dados.periodo_graca_ativo, _j(rascunho_salvo),
            _j(dados.faq) if dados.faq is not None else None, _j(dados.objecoes) if dados.objecoes is not None else None,
            dados.regras_markdown, dados.dados_escritorio, catalogo.get("versao"))
    await _repo(pedido).registrar_alteracao(
        id_usuario=ctx.id_usuario, id_escritorio=ctx.escritorio(), tabela="agentesia_produtos_ativados", id_registro=id_ativado,
        acao="sincronizou" if sincronizar else "ativou",
        resumo=f"{'Produto atualizado' if sincronizar else 'Produto ativado'}: {nome} ({len(papeis)} agentes, {('número ' + canal['numero_normalizado']) if canal else 'ainda sem número'})"
               + _resumo_followup(config))
    # Webhook, alcance e o resto da conferência da ativação (o mesmo passo a passo dos outros agentes).
    verificacao: dict[str, Any] = {}
    try:
        from app.gestao.rotas import _guardar_preparacao, _preparar
        agente = await _repo(pedido).agente(ctx.escritorio(), id_agente)
        resultado = await _preparar(pedido, _repo(pedido), ctx.escritorio(), agente, "producao", aplicar=True)
        await _guardar_preparacao(_repo(pedido), ctx, agente, resultado)
        verificacao = resultado.como_dict()
    except HTTPException:
        raise
    except Exception as erro:                  # a conferência não desfaz a ativação: mostra o que faltou
        verificacao = {"erro": str(erro)[:300]}
    _avisar_indexacao(pedido)
    return {"ok": True, "id_agente": id_agente, "verificacao": verificacao}


def _com_followup_padrao(config: dict[str, Any], catalogo: dict[str, Any], dados: Ativar, sincronizando: bool) -> dict[str, Any]:
    """Opt-out (decisão do dono, docs/FOLLOWUP.md): agente sem follow-up recebe a cadência e os prompts padrão do
    produto da biblioteca, ligado na ativação. Quem já tem config.followup fica como está."""
    if isinstance(config.get("followup"), dict):
        return config
    from app.followup import padrao as padrao_fu
    ligar = dados.followup_ativo if dados.followup_ativo is not None else not sincronizando
    return {**config, "followup": padrao_fu.config_do_produto(catalogo, ativo=ligar)}


def _resumo_followup(config: dict[str, Any]) -> str:
    from app.followup import padrao as padrao_fu
    fu = config.get("followup") or {}
    return f"; follow-up {'ligado' if fu.get('ativo') else 'desligado'} ({', '.join(padrao_fu.resumo(fu))})"


def _avisar_indexacao(pedido: Request) -> None:
    sinal = getattr(pedido.app.state, "indexar_agora", None)
    if sinal is not None:
        sinal.set()


@api.post("/produtos-ativados/{id_ativado}/ativar")
async def ativar_produto(id_ativado: str, dados: Ativar, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    try:
        return await _montar_agente(pedido, ctx, id_ativado, dados, sincronizar=False)
    except HTTPException as erro:
        await _pool(pedido).execute(
            """update agentesia_produtos_ativados set status_provisionamento = 'falhou', erro_provisionamento = $3
               where id = $1::uuid and id_escritorio = $2::uuid and id_agente is null""", id_ativado, ctx.escritorio(), str(erro.detail)[:500])
        raise


@api.post("/produtos-ativados/{id_ativado}/sincronizar")
async def sincronizar_produto(id_ativado: str, dados: Ativar, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    produto = await _ativado(_pool(pedido), ctx.escritorio(), id_ativado)
    if not produto.get("id_agente"):
        raise HTTPException(409, "Este produto ainda não foi ativado.")
    return await _montar_agente(pedido, ctx, id_ativado, dados, sincronizar=True)


class MudarStatus(BaseModel):
    status: str


@api.post("/produtos-ativados/{id_ativado}/status")
async def mudar_status(id_ativado: str, dados: MudarStatus, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    if dados.status not in ("ativo", "pausado"):
        raise HTTPException(400, "Situação inválida.")
    pool = _pool(pedido)
    produto = await _ativado(pool, ctx.escritorio(), id_ativado)
    if dados.status == "ativo" and (produto.get("precisa_ativar") or produto.get("excluido_em")):
        # Sem número (voltou da lixeira) ou ainda na lixeira: ligar aqui deixaria "ativo" um agente que não atende.
        raise HTTPException(409, SEM_NUMERO if produto.get("precisa_ativar") else "Restaure o produto antes de ativar.")
    if produto.get("id_agente"):
        await pool.execute("update agentesia_agentes set situacao = $2 where id = $1::uuid", produto["id_agente"], dados.status)
    await pool.execute("update agentesia_produtos_ativados set status = $2 where id = $1::uuid", id_ativado, dados.status)
    return await _ativado(pool, ctx.escritorio(), id_ativado)


@api.delete("/produtos-ativados/{id_ativado}")
async def excluir_produto(id_ativado: str, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Exclusão definitiva: solta o número sempre. O agente é apagado se não houver conversa; com conversa ele fica
    pausado e sem número (o histórico dos leads continua apontando para ele)."""
    pool = _pool(pedido)
    produto = await _ativado(pool, ctx.escritorio(), id_ativado)
    async with pool.acquire() as conexao, conexao.transaction():
        if produto.get("id_agente"):
            tem_leads = await conexao.fetchval("select exists(select 1 from agentesia_leads where id_agente = $1::uuid)", produto["id_agente"])
            if tem_leads:
                await _soltar_canal(conexao, produto["id_agente"], "produto_excluido")
            else:
                await conexao.execute("delete from agentesia_agentes where id = $1::uuid", produto["id_agente"])
        await _tirar_contrato(conexao, ctx.escritorio(), str(produto["id"]), produto.get("id_agente"))
        await conexao.execute("delete from agentesia_produtos_ativados where id = $1::uuid", id_ativado)
    await _repo(pedido).registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=ctx.escritorio(), tabela="agentesia_produtos_ativados",
                                            id_registro=id_ativado, acao="apagou", resumo=f"Produto excluído: {produto['nome']}")
    return {"ok": True}


# ============================================================================ números
@api.get("/canais/disponiveis")
async def canais_disponiveis(pedido: Request, ctx: Contexto = Depends(GESTAO)) -> list[dict[str, Any]]:
    """Números de WhatsApp do escritório; disponível = nenhum agente usando (como no sistema de referência)."""
    from app.notificacoes import formatar_telefone

    linhas = await _pool(pedido).fetch(
        """select c.id, c.numero_normalizado, c.id_canal_helena, c.tipo, c.ativo, c.atualizado_em, a.id as id_agente, a.nome as agente
           from agentesia_canais c left join agentesia_agentes a on a.id_canal = c.id
           where c.id_escritorio = $1::uuid and c.ativo order by (a.id is null) desc, c.numero_normalizado""", ctx.escritorio())
    return [{"id": str(l["id"]), "numero": l["numero_normalizado"], "numero_formatado": formatar_telefone(l["numero_normalizado"]),
             "nome": None, "tipo": l["tipo"], "id_canal_helena": l["id_canal_helena"], "disponivel": l["id_agente"] is None,
             "id_agente": str(l["id_agente"]) if l["id_agente"] else None,
             "em_uso_por": str(l["id_agente"]) if l["id_agente"] else None, "em_uso_por_nome": l["agente"],
             "sincronizado_em": l["atualizado_em"].isoformat() if l["atualizado_em"] else None} for l in linhas]


# ============================================================================ biblioteca de mídia
COTA_MIDIA = 200 * 1024 * 1024
# Só o que o WhatsApp entrega como mídia: voz em ogg/opus (chega como mensagem de voz), mp3 e m4a (chegam como arquivo
# de áudio), vídeo mp4 (H.264/AAC) e imagem jpg/png. Limites do WhatsApp: áudio e vídeo até 16 MB, imagem até 5 MB.
EXTENSOES = {"audio": ("ogg", "oga", "opus", "mp3", "m4a"), "video": ("mp4",), "imagem": ("jpg", "jpeg", "png")}
LIMITES_POR_TIPO = {"audio": 16 * 1024 * 1024, "video": 16 * 1024 * 1024, "imagem": 5 * 1024 * 1024}
LIMITE_MIDIA = max(LIMITES_POR_TIPO.values())
MIMES = {"ogg": "audio/ogg", "oga": "audio/ogg", "opus": "audio/ogg", "mp3": "audio/mpeg", "m4a": "audio/mp4",
         "mp4": "video/mp4", "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}
# Formatos recusados com o motivo (o WhatsApp recusa ou entrega como documento).
RECUSADOS = {
    **{e: "Áudio em .{ext} não chega como mensagem de voz: converta para .ogg (opus) para chegar como mensagem de voz; "
          ".mp3 chega como arquivo de áudio." for e in ("wav", "flac", "aac", "wma", "amr", "aiff")},
    **{e: "Vídeo em .{ext} o WhatsApp não entrega: converta para .mp4 (H.264), até 16 MB." for e in ("mov", "webm", "avi", "mkv", "3gp", "wmv")},
    **{e: "Imagem em .{ext} não é aceita: use .jpg ou .png, até 5 MB." for e in ("webp", "gif", "heic", "heif", "bmp", "tif", "tiff")},
}
NOMES_DO_TIPO = {"audio": "áudio", "video": "vídeo", "imagem": "imagem"}


def pasta_midia() -> Path:
    """Pasta do modo local (app/armazenamento.py); no modo supabase a mídia vai para o bucket."""
    return armazenamento.pasta_local()


def url_midia(caminho: str) -> str:
    return armazenamento.ArmazenamentoLocal().url_publica(caminho)


class MidiaNova(BaseModel):
    nome: str = Field(min_length=1, max_length=200)
    conteudo_base64: str = Field(min_length=4)
    mime: str | None = None


async def _uso_midia(pool: asyncpg.Pool, id_escritorio: str) -> int:
    return int(await pool.fetchval("select coalesce(sum(tamanho_bytes), 0) from agentesia_biblioteca_midia where id_escritorio = $1::uuid",
                                   id_escritorio) or 0)


@api.get("/midia")
async def listar_midia(pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    pool = _pool(pedido)
    itens = _linhas(await pool.fetch("select * from agentesia_biblioteca_midia where id_escritorio = $1::uuid order by criado_em desc",
                                     ctx.escritorio()))
    return {"itens": itens, "usado_bytes": await _uso_midia(pool, ctx.escritorio()), "limite_bytes": COTA_MIDIA}


@api.post("/midia")
async def enviar_midia(dados: MidiaNova, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    pool = _pool(pedido)
    try:
        destino_midia = armazenamento.do_ambiente()
    except armazenamento.ErroArmazenamento as erro:
        raise HTTPException(409, str(erro)) from erro
    if destino_midia.modo == "local" and not os.environ.get("AGENTESIA_URL_PUBLICA", "").strip().lower().startswith("https://"):
        # Sem o endereço público, a URL ficaria relativa ("/midia/..."): a Helena não baixa e o lead recebe o link cru.
        raise HTTPException(409, "Configure o endereço público do servidor (AGENTESIA_URL_PUBLICA, com https://) antes de "
                                 "subir mídia.")
    extensao = (dados.nome.rsplit(".", 1)[-1] if "." in dados.nome else "").lower()
    tipo = next((t for t, exts in EXTENSOES.items() if extensao in exts), None)
    if not tipo:
        raise HTTPException(400, RECUSADOS[extensao].format(ext=extensao) if extensao in RECUSADOS else
                            "Formato não aceito. Áudio (.ogg/.opus para mensagem de voz, .mp3, .m4a), vídeo (.mp4) "
                            "ou imagem (.jpg, .png).")
    try:
        bruto = base64.b64decode(dados.conteudo_base64.split(",")[-1], validate=True)
    except (binascii.Error, ValueError) as erro:
        raise HTTPException(400, "Arquivo inválido (não veio em base64).") from erro
    if len(bruto) > LIMITES_POR_TIPO[tipo]:
        raise HTTPException(413, f"Arquivo grande demais: o limite para {NOMES_DO_TIPO[tipo]} é "
                                 f"{LIMITES_POR_TIPO[tipo] // 1_048_576} MB (o WhatsApp não entrega maior).")
    if await _uso_midia(pool, ctx.escritorio()) + len(bruto) > COTA_MIDIA:
        raise HTTPException(413, "O espaço da biblioteca de mídia (200 MB) acabou. Apague arquivos antigos para enviar este.")
    nome_base = slugificar(dados.nome.rsplit(".", 1)[0]) or "arquivo"
    caminho = f"{ctx.escritorio()}/{tipo}/{uuid.uuid4().hex}-{nome_base}.{extensao}"
    mime = MIMES.get(extensao) or dados.mime or "application/octet-stream"
    try:
        url = await destino_midia.enviar(caminho, bruto, mime)
    except armazenamento.ErroArmazenamento as erro:
        raise HTTPException(502, str(erro)) from erro
    try:
        linha = await pool.fetchrow(
            """insert into agentesia_biblioteca_midia (id_escritorio, nome, tipo, url, caminho_storage, mime_type, tamanho_bytes)
               values ($1::uuid, $2, $3, $4, $5, $6, $7) returning *""",
            ctx.escritorio(), dados.nome.rsplit(".", 1)[0][:200], tipo, url, caminho, mime, len(bruto))
    except Exception:
        try:                                             # sem a linha, o arquivo ficaria órfão no bucket
            await destino_midia.apagar(caminho)
        except armazenamento.ErroArmazenamento:
            pass
        raise
    return _linha(linha)  # type: ignore[return-value]


async def _quem_usa_a_midia(pool: asyncpg.Pool, id_escritorio: str, trecho: str | None) -> str | None:
    """Nome do agente (ou produto em configuração) do escritório cujo roteiro ainda cita o arquivo: prompt das etapas,
    config do agente (regras, objeções, mídias) ou o assistente do produto. None = ninguém usa."""
    if not trecho:
        return None
    return await pool.fetchval(
        """select nome from (
             select a.nome, 1 as ordem from agentesia_agentes a
              where a.id_escritorio = $1::uuid
                and (strpos(a.config::text, $2) > 0
                     or exists (select 1 from agentesia_agente_etapas e where e.id_agente = a.id and strpos(coalesce(e.instrucao, ''), $2) > 0))
             union all
             select p.nome, 2 from agentesia_produtos_ativados p
              where p.id_escritorio = $1::uuid and p.excluido_em is null
                and (strpos(p.rascunho::text, $2) > 0 or strpos(p.objecoes::text, $2) > 0
                     or strpos(coalesce(p.regras_markdown, ''), $2) > 0 or strpos(p.conhecimento::text, $2) > 0)
           ) usos order by ordem limit 1""", id_escritorio, trecho)


class RenomearMidia(BaseModel):
    nome: str = Field(min_length=1, max_length=200)


@api.patch("/midia/{id_midia}")
async def renomear_midia(id_midia: str, dados: RenomearMidia, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    linha = await _pool(pedido).fetchrow(
        "update agentesia_biblioteca_midia set nome = $3 where id = $1::uuid and id_escritorio = $2::uuid returning *",
        id_midia, ctx.escritorio(), dados.nome.strip())
    if not linha:
        raise HTTPException(404, "Arquivo não encontrado.")
    return _linha(linha)  # type: ignore[return-value]


@api.delete("/midia/{id_midia}")
async def apagar_midia(id_midia: str, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    pool = _pool(pedido)
    linha = await pool.fetchrow("select url, caminho_storage from agentesia_biblioteca_midia where id = $1::uuid and id_escritorio = $2::uuid",
                                id_midia, ctx.escritorio())
    if linha and (quem := await _quem_usa_a_midia(pool, ctx.escritorio(), linha["caminho_storage"] or linha["url"])):
        # Apagar o arquivo que o roteiro ainda cita deixaria um link morto que a IA continua mandando.
        raise HTTPException(409, f"Este arquivo ainda é usado no roteiro de {quem}. Tire o link do roteiro antes de apagar.")
    if linha and linha["caminho_storage"]:
        # Onde o arquivo está vem da URL gravada: bucket (mídia nova) ou disco local (mídia antiga, /midia/...).
        # Apaga o arquivo antes da linha: se o Storage falhar, a linha fica e dá para tentar de novo.
        origem = armazenamento.de_uma_midia(linha["url"])
        if origem is None:
            armazenamento.log.warning("mídia %s está num bucket sem configuração aqui: só a linha é apagada", id_midia)
        else:
            try:
                await origem.apagar(linha["caminho_storage"])
            except armazenamento.ErroArmazenamento as erro:
                raise HTTPException(502, str(erro)) from erro
    await pool.execute("delete from agentesia_biblioteca_midia where id = $1::uuid and id_escritorio = $2::uuid",
                       id_midia, ctx.escritorio())
    return {"ok": True}
