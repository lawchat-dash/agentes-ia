"""Ferramentas > Resumo de contrato: o resumo do caso que a IA faz quando o contrato é assinado, por agente.

  GET /api/resumo-contrato/agentes                 agentes do escritório com o resumo ligado/desligado e o consumo
  GET /api/agentes/{id_agente}/contrato/resumo     configuração, o prompt padrão do produto, o consumo e os últimos resumos
  PUT /api/agentes/{id_agente}/contrato/resumo     {ligado, prompt, modelo, no_aviso, id_equipe_assinado}

A configuração fica em agentesia_agentes.config.contrato.resumo = {ligado, prompt, modelo, no_aviso} (sem migração);
config.contrato.id_equipe_assinado é o departamento para onde o atendimento vai quando o contrato é assinado.
Prompt vazio = o padrão do produto. O consumo vem de agentesia_chamadas_ia (papel contrato_resumo), o mesmo que entra
em Créditos. Tudo do escritório da sessão; alteração vai para agentesia_alteracoes.
"""

from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app import cobranca
from app.contrato import resumo as cresumo
from app.gestao.rotas import GESTAO, Contexto, _repo

api = APIRouter(prefix="/api")
MODELOS_PERMITIDOS = ("gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini", "gpt-4o")


class ResumoDoAgente(BaseModel):
    ligado: bool = True
    prompt: str | None = Field(default=None, max_length=12000)
    modelo: str | None = None
    no_aviso: bool = True
    id_equipe_assinado: str | None = Field(default=None, max_length=64)


def _uuid(valor: str, nome: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", valor or ""):
        raise HTTPException(404, f"{nome} não encontrado.")
    return valor


def _json(valor: Any) -> dict[str, Any]:
    if isinstance(valor, dict):
        return valor
    try:
        return json.loads(valor or "{}")
    except (TypeError, ValueError):
        return {}


async def _config_zapsign(pool: Any, id_escritorio: str) -> dict[str, Any]:
    return _json(await pool.fetchval(
        "select config from agentesia_integracoes where id_escritorio = $1::uuid and tipo = 'zapsign'", id_escritorio))


async def _agente(pool: Any, id_agente: str, id_escritorio: str) -> dict[str, Any]:
    linha = await pool.fetchrow(
        "select id, nome, produto, config from agentesia_agentes where id = $1::uuid and id_escritorio = $2::uuid",
        _uuid(id_agente, "Agente"), id_escritorio)
    if not linha:
        raise HTTPException(404, "Agente não encontrado.")
    return {**dict(linha), "config": _json(linha["config"])}


def _numero(valor: Any) -> float:
    return float(valor or 0)


async def _consumo(pool: Any, id_escritorio: str, id_agente: str | None = None) -> dict[str, Any]:
    """Tokens e custo do resumo (total e últimos 30 dias). Sem a migração da cobrança não há id_agente nas chamadas:
    o consumo é o do escritório inteiro."""
    por_agente = id_agente is not None and await cobranca.tem_cobranca(pool)
    custo_brl = "coalesce(sum(custo_brl), 0)" if await cobranca.tem_cobranca(pool) else "0"
    filtro = "and id_agente = $3::uuid" if por_agente else ""
    linha = await pool.fetchrow(
        f"""select count(*) as chamadas, count(*) filter (where sucesso) as feitos,
                   coalesce(sum(tokens_entrada), 0) as tokens_entrada, coalesce(sum(tokens_saida), 0) as tokens_saida,
                   coalesce(sum(custo_usd), 0) as custo_usd, {custo_brl} as custo_brl,
                   count(*) filter (where criado_em > now() - interval '30 days') as chamadas_30d,
                   coalesce(sum(tokens_entrada + tokens_saida) filter (where criado_em > now() - interval '30 days'), 0) as tokens_30d,
                   {custo_brl.replace("sum(custo_brl)", "sum(custo_brl) filter (where criado_em > now() - interval '30 days')")} as custo_brl_30d
            from agentesia_chamadas_ia where id_escritorio = $1::uuid and papel = $2 {filtro}""",
        *([id_escritorio, cresumo.PAPEL_IA, id_agente] if por_agente else [id_escritorio, cresumo.PAPEL_IA]))
    chamadas = int(linha["chamadas"] or 0)
    tokens = int(linha["tokens_entrada"] or 0) + int(linha["tokens_saida"] or 0)
    return {"por_agente": por_agente, "chamadas": chamadas, "feitos": int(linha["feitos"] or 0),
            "tokens_entrada": int(linha["tokens_entrada"] or 0), "tokens_saida": int(linha["tokens_saida"] or 0),
            "tokens": tokens, "media_tokens": round(tokens / chamadas) if chamadas else 0,
            "custo_usd": round(_numero(linha["custo_usd"]), 6), "custo_brl": round(_numero(linha["custo_brl"]), 4),
            "chamadas_30d": int(linha["chamadas_30d"] or 0), "tokens_30d": int(linha["tokens_30d"] or 0),
            "custo_brl_30d": round(_numero(linha["custo_brl_30d"]), 4)}


def _visao(agente: dict[str, Any], config_zapsign: dict[str, Any]) -> dict[str, Any]:
    config = agente["config"]
    caso = cresumo.nome_do_caso(agente.get("produto"), config)
    salvo = cresumo.bloco_do_agente(config)
    contrato = config.get("contrato") if isinstance(config.get("contrato"), dict) else {}
    vale = cresumo.configuracao(config, config_zapsign, caso)
    return {"agente": {"id": str(agente["id"]), "nome": agente["nome"], "produto": agente.get("produto"), "caso": caso},
            "config": {"ligado": vale["ativo"], "prompt": str(salvo.get("prompt") or ""), "modelo": vale["modelo"],
                       "no_aviso": vale["no_aviso"], "id_equipe_assinado": contrato.get("id_equipe_assinado") or None},
            "vale": vale, "prompt_padrao": cresumo.prompt_padrao(caso), "modelos": list(MODELOS_PERMITIDOS)}


@api.get("/resumo-contrato/agentes")
async def agentes_do_resumo(pedido: Request, ctx: Contexto = Depends(GESTAO)) -> list[dict[str, Any]]:
    pool = _repo(pedido).pool
    config_zapsign = await _config_zapsign(pool, ctx.escritorio())
    linhas = await pool.fetch(
        "select id, nome, produto, config, situacao from agentesia_agentes where id_escritorio = $1::uuid order by nome",
        ctx.escritorio())
    saida = []
    for x in linhas:
        agente = {**dict(x), "config": _json(x["config"])}
        visao = _visao(agente, config_zapsign)
        saida.append({**visao["agente"], "situacao": x["situacao"], "ligado": visao["config"]["ligado"],
                      "prompt_proprio": visao["vale"]["origem"] == "agente"})
    return saida


@api.get("/agentes/{id_agente}/contrato/resumo")
async def ver_resumo(id_agente: str, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    pool = _repo(pedido).pool
    agente = await _agente(pool, id_agente, ctx.escritorio())
    visao = _visao(agente, await _config_zapsign(pool, ctx.escritorio()))
    ultimos = await pool.fetch(
        """select k.id, k.versao, k.assinado_em, k.resumo, c.nome
           from agentesia_contratos k join agentesia_leads l on l.id = k.id_lead join agentesia_contatos c on c.id = l.id_contato
           where k.id_escritorio = $1::uuid and l.id_agente = $2::uuid and k.situacao = 'assinado'
           order by k.assinado_em desc nulls last limit 5""", ctx.escritorio(), agente["id"])
    return {**visao, "consumo": await _consumo(pool, ctx.escritorio(), str(agente["id"])),
            "ultimos": [{"id": str(u["id"]), "versao": u["versao"], "nome": u["nome"],
                         "assinado_em": u["assinado_em"].isoformat() if u["assinado_em"] else None,
                         "resumo": u["resumo"]} for u in ultimos]}


@api.put("/agentes/{id_agente}/contrato/resumo")
async def salvar_resumo(id_agente: str, dados: ResumoDoAgente, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    repo = _repo(pedido)
    if dados.modelo and dados.modelo not in MODELOS_PERMITIDOS:
        raise HTTPException(400, "Modelo de IA não permitido para o resumo.")
    agente = await _agente(repo.pool, id_agente, ctx.escritorio())
    caso = cresumo.nome_do_caso(agente.get("produto"), agente["config"])
    prompt = (dados.prompt or "").strip()
    if prompt == cresumo.prompt_padrao(caso).strip():
        prompt = ""                                   # igual ao padrão: guarda vazio (segue o padrão se ele mudar)
    novo = {"ligado": dados.ligado, "prompt": prompt or None, "modelo": dados.modelo or cresumo.MODELO_PADRAO,
            "no_aviso": dados.no_aviso}
    antes = {"resumo": cresumo.bloco_do_agente(agente["config"]),
             "id_equipe_assinado": (agente["config"].get("contrato") or {}).get("id_equipe_assinado")
             if isinstance(agente["config"].get("contrato"), dict) else None}
    await repo.pool.execute(
        """update agentesia_agentes set config = jsonb_set(coalesce(config, '{}'::jsonb), '{contrato}',
                  (case when jsonb_typeof(config->'contrato') = 'object' then config->'contrato' else '{}'::jsonb end)
                  || jsonb_build_object('resumo', $2::jsonb, 'id_equipe_assinado', $3::text))
           where id = $1::uuid""", agente["id"], json.dumps(novo, ensure_ascii=False), (dados.id_equipe_assinado or "").strip() or None)
    depois = {"resumo": novo, "id_equipe_assinado": (dados.id_equipe_assinado or "").strip() or None}
    await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=ctx.escritorio(), tabela="agentesia_agentes",
                                   id_registro=str(agente["id"]), acao="alterou", resumo="Resumo de contrato do agente",
                                   antes=antes, depois=depois)
    atualizado = await _agente(repo.pool, id_agente, ctx.escritorio())
    return _visao(atualizado, await _config_zapsign(repo.pool, ctx.escritorio()))
