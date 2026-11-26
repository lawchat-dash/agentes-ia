"""Roteiros de áudio (Ferramentas > Roteiros; tabela da migração 009).

O roteiro é o texto que alguém da equipe vai gravar. O áudio (gravado no navegador ou enviado) entra na biblioteca de
mídia pelo mesmo caminho do upload normal (POST /api/midia: formato, limite, cota, armazenamento) e fica ligado ao
roteiro (id_midia). Gravação do Chrome/Edge vem em WebM/Opus: o servidor troca o envelope para Ogg/Opus, que o
WhatsApp entrega como mensagem de voz.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.gestao.produtos import NOMES_PAPEL, MidiaNova, _linha, _pool, apagar_midia, enviar_midia, slugificar
from app.gestao.rotas import GESTAO, Contexto
from app.midia.webm_para_ogg import ErroConversao, eh_webm, webm_para_ogg

api = APIRouter(prefix="/api")

SEM_TABELA = "Os roteiros ainda não estão no banco: aplique a migração db/migracoes/009_agentesia_roteiros.sql."
STATUS = ("a_gravar", "gravado")

_SELECT = """
select r.*, a.nome as agente_nome, p.nome as produto_nome,
       m.nome as midia_nome, m.url as midia_url, m.mime_type as midia_mime, m.tamanho_bytes as midia_tamanho,
       m.criado_em as midia_criado_em
  from agentesia_roteiros r
  left join agentesia_agentes a on a.id = r.id_agente
  left join agentesia_produtos_ativados p on p.id = r.id_produto_ativado
  left join agentesia_biblioteca_midia m on m.id = r.id_midia
"""


def _para_tela(registro: asyncpg.Record | None) -> dict[str, Any]:
    linha = _linha(registro) or {}
    midia = None
    if linha.get("id_midia"):
        midia = {"id": linha["id_midia"], "nome": linha.get("midia_nome"), "url": linha.get("midia_url"),
                 "mime_type": linha.get("midia_mime"), "tamanho_bytes": linha.get("midia_tamanho"),
                 "criado_em": linha.get("midia_criado_em")}
    for chave in ("midia_nome", "midia_url", "midia_mime", "midia_tamanho", "midia_criado_em"):
        linha.pop(chave, None)
    etapa = linha.get("etapa")
    linha["etapa_nome"] = NOMES_PAPEL.get(etapa, etapa) if etapa else None
    linha["midia"] = midia
    return linha


async def _consultar(pedido: Request, metodo: str, sql: str, *args: Any) -> Any:
    try:
        return await getattr(_pool(pedido), metodo)(sql, *args)
    except asyncpg.UndefinedTableError as erro:
        raise HTTPException(503, SEM_TABELA) from erro


async def _um(pedido: Request, ctx: Contexto, id_roteiro: str) -> dict[str, Any]:
    _uuid(id_roteiro)
    linha = await _consultar(pedido, "fetchrow", _SELECT + " where r.id = $1::uuid and r.id_escritorio = $2::uuid",
                             id_roteiro, ctx.escritorio())
    if not linha:
        raise HTTPException(404, "Roteiro não encontrado.")
    return _para_tela(linha)


def _uuid(valor: str) -> None:
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", valor or ""):
        raise HTTPException(404, "Roteiro não encontrado.")


async def _conferir_destino(pedido: Request, ctx: Contexto, id_agente: str | None, id_produto: str | None) -> None:
    """Agente e produto têm de ser do escritório (senão o roteiro apontaria para o de outro)."""
    pool = _pool(pedido)
    if id_agente:
        _uuid_ou_400(id_agente, "Agente")
        if not await pool.fetchval("select 1 from agentesia_agentes where id = $1::uuid and id_escritorio = $2::uuid",
                                   id_agente, ctx.escritorio()):
            raise HTTPException(400, "Agente não encontrado neste escritório.")
    if id_produto:
        _uuid_ou_400(id_produto, "Produto")
        if not await pool.fetchval(
                "select 1 from agentesia_produtos_ativados where id = $1::uuid and id_escritorio = $2::uuid and excluido_em is null",
                id_produto, ctx.escritorio()):
            raise HTTPException(400, "Produto não encontrado neste escritório.")


def _uuid_ou_400(valor: str, nome: str) -> None:
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", valor):
        raise HTTPException(400, f"{nome} inválido.")


class RoteiroNovo(BaseModel):
    titulo: str = Field(min_length=1, max_length=200)
    texto: str = Field(default="", max_length=20000)
    id_agente: str | None = None
    etapa: str | None = Field(default=None, max_length=60)
    id_produto_ativado: str | None = None


class RoteiroMudar(BaseModel):
    titulo: str | None = Field(default=None, min_length=1, max_length=200)
    texto: str | None = Field(default=None, max_length=20000)
    id_agente: str | None = None
    etapa: str | None = Field(default=None, max_length=60)
    id_produto_ativado: str | None = None
    status: str | None = None


class AudioDoRoteiro(BaseModel):
    conteudo_base64: str = Field(min_length=4)
    mime: str | None = None
    nome: str | None = Field(default=None, max_length=200)


def _vazio_none(valor: str | None) -> str | None:
    valor = (valor or "").strip()
    return valor or None


@api.get("/roteiros")
async def listar_roteiros(pedido: Request, ctx: Contexto = Depends(GESTAO)) -> list[dict[str, Any]]:
    linhas = await _consultar(pedido, "fetch", _SELECT + " where r.id_escritorio = $1::uuid order by r.criado_em desc",
                              ctx.escritorio())
    return [_para_tela(l) for l in linhas]


@api.get("/roteiros/opcoes")
async def opcoes_roteiro(pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Agentes (com as etapas) e produtos do escritório, para o "para quem é" do roteiro."""
    pool = _pool(pedido)
    agentes = await pool.fetch(
        """select a.id, a.nome, coalesce(json_agg(json_build_object('codigo', e.codigo, 'ordem', e.ordem) order by e.ordem)
                    filter (where e.id is not null), '[]') as etapas
             from agentesia_agentes a left join agentesia_agente_etapas e on e.id_agente = a.id
            where a.id_escritorio = $1::uuid group by a.id, a.nome order by a.nome""", ctx.escritorio())
    produtos = await pool.fetch(
        """select id, nome from agentesia_produtos_ativados
            where id_escritorio = $1::uuid and excluido_em is null order by nome""", ctx.escritorio())
    saida_agentes = []
    for a in agentes:
        etapas = a["etapas"] if isinstance(a["etapas"], list) else json.loads(a["etapas"] or "[]")
        saida_agentes.append({"id": str(a["id"]), "nome": a["nome"],
                              "etapas": [{"codigo": e["codigo"], "nome": NOMES_PAPEL.get(e["codigo"], e["codigo"])} for e in etapas]})
    return {"agentes": saida_agentes, "produtos": [{"id": str(p["id"]), "nome": p["nome"]} for p in produtos]}


@api.post("/roteiros")
async def criar_roteiro(dados: RoteiroNovo, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    id_agente, id_produto = _vazio_none(dados.id_agente), _vazio_none(dados.id_produto_ativado)
    await _conferir_destino(pedido, ctx, id_agente, id_produto)
    novo = await _consultar(
        pedido, "fetchval",
        """insert into agentesia_roteiros (id_escritorio, titulo, texto, id_agente, etapa, id_produto_ativado, id_usuario)
           values ($1::uuid, $2, $3, $4::uuid, $5, $6::uuid, $7::uuid) returning id""",
        ctx.escritorio(), dados.titulo.strip(), dados.texto, id_agente, _vazio_none(dados.etapa), id_produto, ctx.id_usuario)
    return await _um(pedido, ctx, str(novo))


@api.get("/roteiros/{id_roteiro}")
async def ver_roteiro(id_roteiro: str, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    return await _um(pedido, ctx, id_roteiro)


@api.patch("/roteiros/{id_roteiro}")
async def mudar_roteiro(id_roteiro: str, dados: RoteiroMudar, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    atual = await _um(pedido, ctx, id_roteiro)
    enviados = dados.model_fields_set
    campos: dict[str, Any] = {}
    if "titulo" in enviados and dados.titulo is not None:
        campos["titulo"] = dados.titulo.strip()
    if "texto" in enviados and dados.texto is not None:
        campos["texto"] = dados.texto
    if "id_agente" in enviados:
        campos["id_agente"] = _vazio_none(dados.id_agente)
    if "etapa" in enviados:
        campos["etapa"] = _vazio_none(dados.etapa)
    if "id_produto_ativado" in enviados:
        campos["id_produto_ativado"] = _vazio_none(dados.id_produto_ativado)
    if "status" in enviados and dados.status is not None:
        if dados.status not in STATUS:
            raise HTTPException(400, "Situação inválida: use a_gravar ou gravado.")
        if dados.status == "gravado" and not atual.get("id_midia"):
            raise HTTPException(400, "Grave ou envie o áudio antes de marcar como gravado.")
        campos["status"] = dados.status
    await _conferir_destino(pedido, ctx, campos.get("id_agente"), campos.get("id_produto_ativado"))
    if campos:
        tipos = {"id_agente": "::uuid", "id_produto_ativado": "::uuid"}
        sets = ", ".join(f"{c} = ${i + 3}{tipos.get(c, '')}" for i, c in enumerate(campos))
        await _consultar(pedido, "execute", f"update agentesia_roteiros set {sets} where id = $1::uuid and id_escritorio = $2::uuid",
                         id_roteiro, ctx.escritorio(), *campos.values())
    return await _um(pedido, ctx, id_roteiro)


@api.delete("/roteiros/{id_roteiro}")
async def apagar_roteiro(id_roteiro: str, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Apaga só o roteiro: o áudio gravado continua na biblioteca de mídia (pode estar num prompt)."""
    await _um(pedido, ctx, id_roteiro)
    await _consultar(pedido, "execute", "delete from agentesia_roteiros where id = $1::uuid and id_escritorio = $2::uuid",
                     id_roteiro, ctx.escritorio())
    return {"ok": True}


def _extensao(bruto: bytes, mime: str, nome: str | None) -> str:
    mime = (mime or "").lower()
    final = (nome or "").rsplit(".", 1)[-1].lower() if nome and "." in nome else ""
    if bruto[:4] == b"OggS":
        return "ogg"
    if bruto[:3] == b"ID3" or (len(bruto) > 1 and bruto[0] == 0xFF and bruto[1] & 0xE0 == 0xE0) or "mpeg" in mime:
        return "mp3"
    if bruto[4:8] == b"ftyp" or "mp4" in mime or "m4a" in mime or "aac" in mime:
        return "m4a"
    return final or "ogg"


@api.post("/roteiros/{id_roteiro}/audio")
async def gravar_audio(id_roteiro: str, dados: AudioDoRoteiro, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Recebe o áudio do roteiro (gravado no navegador ou arquivo), guarda na biblioteca e liga ao roteiro."""
    roteiro = await _um(pedido, ctx, id_roteiro)
    try:
        bruto = base64.b64decode(dados.conteudo_base64.split(",")[-1], validate=True)
    except (binascii.Error, ValueError) as erro:
        raise HTTPException(400, "Arquivo inválido (não veio em base64).") from erro
    if not bruto:
        raise HTTPException(400, "A gravação está vazia.")
    if eh_webm(bruto) or "webm" in (dados.mime or "").lower():
        try:
            bruto = webm_para_ogg(bruto)
        except ErroConversao as erro:
            raise HTTPException(400, f"Não deu para converter a gravação: {erro}") from erro
        extensao = "ogg"
    else:
        extensao = _extensao(bruto, dados.mime or "", dados.nome)
        if extensao not in ("ogg", "oga", "opus", "mp3", "m4a"):
            raise HTTPException(400, "Envie o áudio em .ogg/.opus (chega como mensagem de voz), .mp3 ou .m4a.")
    nome = f"{slugificar(roteiro['titulo'])[:80] or 'roteiro'}.{extensao}"
    criada = await enviar_midia(MidiaNova(nome=nome, conteudo_base64=base64.b64encode(bruto).decode()), pedido, ctx)
    # O nome que aparece na biblioteca é o título do roteiro (não o slug).
    await _pool(pedido).execute("update agentesia_biblioteca_midia set nome = $2 where id = $1::uuid",
                                criada["id"], roteiro["titulo"][:200])
    anterior = roteiro.get("id_midia")
    await _consultar(pedido, "execute",
                     "update agentesia_roteiros set id_midia = $3::uuid, status = 'gravado' where id = $1::uuid and id_escritorio = $2::uuid",
                     id_roteiro, ctx.escritorio(), criada["id"])
    if anterior:
        # O áudio antigo sai da biblioteca, salvo se algum prompt ainda o usa (aí fica lá, só sem o roteiro).
        try:
            await apagar_midia(anterior, pedido, ctx)
        except HTTPException:
            pass
    return await _um(pedido, ctx, id_roteiro)


@api.delete("/roteiros/{id_roteiro}/audio")
async def soltar_audio(id_roteiro: str, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Tira o áudio do roteiro (volta para "a gravar"). O arquivo continua na biblioteca de mídia."""
    await _um(pedido, ctx, id_roteiro)
    await _consultar(pedido, "execute",
                     "update agentesia_roteiros set id_midia = null, status = 'a_gravar' where id = $1::uuid and id_escritorio = $2::uuid",
                     id_roteiro, ctx.escritorio())
    return await _um(pedido, ctx, id_roteiro)
