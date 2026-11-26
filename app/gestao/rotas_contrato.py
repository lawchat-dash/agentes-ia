"""Rotas do contrato no painel: contratos do lead (com o resumo do caso) e o prompt do resumo por agente.

  GET /api/leads/{id_lead}/contratos              versões do contrato do lead: situação, link, PDF guardado, resumo
  GET /api/agentes/{id_agente}/resumo-contrato    configuração do resumo do agente + a que vale (agente > escritório > padrão)
  PUT /api/agentes/{id_agente}/resumo-contrato    {ativo, prompt, modelo, no_aviso}; prompt vazio = volta ao padrão

A configuração fica em agentesia_agentes.config.resumo_contrato (sem migração). Escritório inteiro: config.resumo da
integração ZapSign (já existia). Tudo do escritório da sessão; alteração vai para agentesia_alteracoes.
"""

from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.contrato import resumo as cresumo
from app.gestao.rotas import GESTAO, TODOS, Contexto, _repo

api = APIRouter(prefix="/api")
MODELOS_PERMITIDOS = ("gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini", "gpt-4o")


class ResumoContrato(BaseModel):
    ativo: bool = True
    prompt: str | None = Field(default=None, max_length=8000)
    modelo: str | None = None
    no_aviso: bool = False


def _uuid(valor: str, nome: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", valor or ""):
        raise HTTPException(404, f"{nome} não encontrado.")
    return valor


def _json(valor: Any) -> dict[str, Any]:
    return valor if isinstance(valor, dict) else json.loads(valor or "{}")


async def _config_zapsign(pool: Any, id_escritorio: str) -> dict[str, Any]:
    return _json(await pool.fetchval(
        "select config from agentesia_integracoes where id_escritorio = $1::uuid and tipo = 'zapsign'", id_escritorio))


@api.get("/leads/{id_lead}/contratos")
async def contratos_do_lead(id_lead: str, pedido: Request, ctx: Contexto = Depends(TODOS)) -> dict[str, Any]:
    pool = _repo(pedido).pool
    linhas = await pool.fetch(
        """select id, versao, situacao, causa_erro, link, gerado_em, assinado_em, lead_assinou_em, concluido_em,
                  arquivo_assinado, resumo, criado_em
           from agentesia_contratos where id_lead = $1::uuid and id_escritorio = $2::uuid order by versao desc""",
        _uuid(id_lead, "Lead"), ctx.escritorio())
    contratos = []
    for x in linhas:
        item = {k: (v.isoformat() if hasattr(v, "isoformat") else str(v) if k == "id" else v) for k, v in dict(x).items()}
        arquivo = item.get("arquivo_assinado") or ""
        # O link da ZapSign vence em 60 min: só mostra o PDF quando é o guardado no nosso armazenamento.
        item["pdf"] = arquivo if "/contratos/" in arquivo and "zapsign" not in arquivo.lower() else None
        item.pop("arquivo_assinado", None)
        contratos.append(item)
    return {"contratos": contratos, "resumo": next((c["resumo"] for c in contratos if c.get("resumo")), None)}


async def _agente(pool: Any, id_agente: str, id_escritorio: str) -> dict[str, Any]:
    linha = await pool.fetchrow("select id, config from agentesia_agentes where id = $1::uuid and id_escritorio = $2::uuid",
                                _uuid(id_agente, "Agente"), id_escritorio)
    if not linha:
        raise HTTPException(404, "Agente não encontrado.")
    return dict(linha)


@api.get("/agentes/{id_agente}/resumo-contrato")
async def ver_resumo_contrato(id_agente: str, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    pool = _repo(pedido).pool
    agente = await _agente(pool, id_agente, ctx.escritorio())
    config = _json(agente["config"])
    return {"agente": config.get("resumo_contrato") or {},
            "vale": cresumo.configuracao(config, await _config_zapsign(pool, ctx.escritorio())),
            "prompt_padrao": cresumo.PROMPT_PADRAO, "modelos": list(MODELOS_PERMITIDOS)}


@api.put("/agentes/{id_agente}/resumo-contrato")
async def salvar_resumo_contrato(id_agente: str, dados: ResumoContrato, pedido: Request,
                                 ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    repo = _repo(pedido)
    if dados.modelo and dados.modelo not in MODELOS_PERMITIDOS:
        raise HTTPException(400, "Modelo de IA não permitido para o resumo.")
    novo = {"ativo": dados.ativo, "prompt": (dados.prompt or "").strip() or None, "modelo": dados.modelo or None,
            "no_aviso": dados.no_aviso}
    agente = await _agente(repo.pool, id_agente, ctx.escritorio())
    antes = _json(agente["config"]).get("resumo_contrato")
    await repo.pool.execute(
        """update agentesia_agentes set config = coalesce(config, '{}'::jsonb) || jsonb_build_object('resumo_contrato', $2::jsonb)
           where id = $1::uuid""", agente["id"], json.dumps(novo, ensure_ascii=False))
    await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=ctx.escritorio(), tabela="agentesia_agentes",
                                   id_registro=str(agente["id"]), acao="alterou", resumo="Resumo do contrato assinado",
                                   antes=antes, depois=novo)
    config = _json(await repo.pool.fetchval("select config from agentesia_agentes where id = $1", agente["id"]))
    return {"agente": novo, "vale": cresumo.configuracao(config, await _config_zapsign(repo.pool, ctx.escritorio()))}
