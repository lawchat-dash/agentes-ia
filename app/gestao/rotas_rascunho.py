"""Testar o rascunho antes de publicar e voltar versão (docs/PESQUISA_PLATAFORMAS.md, itens 1 e 3).

Laboratório do RASCUNHO: o assistente de ativação e o editor do produto mandam o conteúdo que está na tela (o mesmo
payload de ativar/sincronizar, ainda não salvo) e o motor de verdade (app/pipeline.py, modo laboratório) responde em
memória: sem número, sem Helena, sem gravar lead nem conversa. Cada resposta volta com a etapa, os fatos, as travas,
a troca de agente e o custo estimado em R$. O teste gasta créditos (as chamadas de IA entram na carteira com origem
'laboratorio') e respeita o "pode gastar?" da cobrança; com o modelo falso (testes e demo local) não gasta.

Versões: lista, uma versão com as diferenças e "restaurar" (devolve o conteúdo para o rascunho do editor; não publica).
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app import cobranca
from app.gestao import versoes
from app.gestao.produtos import (DESTINOS, NOMES_PAPEL, PAPEIS, Ativar, _ativado, _config_do_agente, _linha, _pool,
                                 juntar_config)
from app.gestao.rotas import GESTAO, Contexto, _repo

log = logging.getLogger("agentesia.rascunho")

api = APIRouter(prefix="/api")

SEM_SALDO = ("O saldo de IA do escritório acabou e o teste usa créditos. Recarregue a carteira para testar de novo "
             "(os agentes no ar também estão parados até lá).")


# ============================================================================ laboratório do rascunho
class MensagemRascunho(BaseModel):
    texto: str = Field(min_length=1, max_length=4000)
    id_conversa: str | None = None
    etapa_inicial: str | None = None        # "começar na etapa" (só vale ao abrir a conversa)
    rascunho: Ativar                        # o mesmo payload de ativar/sincronizar, com o que está na tela


class Recomecar(BaseModel):
    id_conversa: str | None = None


def _modelo_falso(pedido: Request) -> bool:
    from app.modelo import ModeloFalso
    return isinstance(getattr(pedido.app.state.laboratorios, "_modelo", None), ModeloFalso)


async def _agente_do_rascunho(pedido: Request, produto: dict[str, Any], dados: Ativar) -> dict[str, Any]:
    """O agente como ficaria se o rascunho fosse salvo agora (a mesma montagem da ativação, sem gravar nada)."""
    papeis = [a.papel for a in dados.agentes]
    if not papeis or any(p not in PAPEIS for p in papeis):
        raise HTTPException(400, "Envie os agentes do funil (SDR, Closer, Contratos, Assinatura, Desqualificado).")
    pool = _pool(pedido)
    catalogo = (await pool.fetchrow("select * from agentesia_biblioteca_produtos where id = $1::uuid", produto["id_produto_biblioteca"])
                if produto.get("id_produto_biblioteca") else None)
    config = _config_do_agente(dados, _linha(catalogo) or {}, produto, tem_zapsign=False)
    if produto.get("id_agente"):          # produto no ar: CRM, avisos, follow-up etc. continuam os do agente salvo
        antigo = await pool.fetchval("select config from agentesia_agentes where id = $1::uuid", produto["id_agente"])
        config = juntar_config(json.loads(antigo) if isinstance(antigo, str) else (antigo or {}), config)
    prompts = {a.papel: a.prompt for a in dados.agentes}
    codigos = [p for p in PAPEIS if p in papeis]
    etapas = [{"id": f"rascunho-{c}", "codigo": c, "principal": i == 0, "instrucao": prompts.get(c) or None,
               "modelo": dados.modelo} for i, c in enumerate(codigos)]
    etapas.append({"id": "rascunho-contrato_assinado", "codigo": "contrato_assinado", "principal": False,
                   "instrucao": None, "modelo": dados.modelo})
    return {"id": f"rascunho-{produto['id']}", "nome": (dados.nome or produto["nome"]).strip()[:120],
            "produto": "catalogo", "config": config, "etapas": etapas}


async def _preco(pool: Any, id_escritorio: str) -> tuple[float, float]:
    """(cotação, markup) que o gatilho da 007 usaria agora para este escritório."""
    try:
        if await cobranca.tem_cobranca(pool):
            linha = await pool.fetchrow(
                """select v.cotacao_usd_brl::float8 as cotacao, coalesce(c.markup, v.markup)::float8 as markup
                   from agentesia_cobranca_vigente() v
                   left join agentesia_carteiras c on c.id_escritorio = $1::uuid""", id_escritorio)
            if linha:
                return float(linha["cotacao"] or cobranca.COTACAO_PADRAO), float(linha["markup"] or cobranca.MARKUP_PADRAO)
    except Exception:
        log.exception("falha ao ler a cotação vigente")
    return cobranca.COTACAO_PADRAO, cobranca.MARKUP_PADRAO


def _nome_etapa(dados: Ativar, codigo: str | None) -> str | None:
    if not codigo:
        return None
    if codigo == "contrato_assinado":
        return "Contrato assinado"
    agente = next((a for a in dados.agentes if a.papel == codigo), None)
    return (agente.nome if agente and agente.nome else None) or NOMES_PAPEL.get(codigo, codigo)


def _travas(turno: dict[str, Any]) -> list[dict[str, str]]:
    """As travas que barraram uma resposta neste turno (a IA refez a mensagem), uma vez cada."""
    vistas: dict[str, dict[str, str]] = {}
    for tentativa in turno.get("reprovacoes") or []:
        for r in tentativa or []:
            codigo = str(r.get("codigo") or "trava")
            vistas.setdefault(codigo, {"codigo": codigo, "orientacao": str(r.get("orientacao") or "")})
    return list(vistas.values())


@api.get("/produtos-ativados/{id_ativado}/laboratorio")
async def laboratorio_info(id_ativado: str, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """O que o painel mostra antes do teste: se gasta créditos e se pode gastar agora."""
    pool = _pool(pedido)
    await _ativado(pool, ctx.escritorio(), id_ativado)
    falso = _modelo_falso(pedido)
    situacao = None
    try:
        situacao = await cobranca.situacao(pool, ctx.escritorio())
    except Exception:
        log.exception("falha ao ler a carteira")
    return {"gasta_creditos": not falso, "modelo_falso": falso,
            "pode_gastar": falso or not (situacao and situacao.bloqueado),
            "disponivel_brl": round(situacao.disponivel_brl, 2) if situacao and not falso else None,
            "aviso": None if falso else "Cada mensagem de teste usa a IA de verdade e gasta créditos da carteira."}


@api.post("/produtos-ativados/{id_ativado}/laboratorio")
async def laboratorio_rascunho(id_ativado: str, dados: MensagemRascunho, pedido: Request,
                               ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    pool = _pool(pedido)
    produto = await _ativado(pool, ctx.escritorio(), id_ativado)
    escritorio = await _repo(pedido).escritorio(ctx.escritorio())
    if not escritorio:
        raise HTTPException(404, "Escritório não encontrado.")
    falso = _modelo_falso(pedido)
    if not falso and await cobranca.bloqueado(pool, ctx.escritorio()):
        raise HTTPException(402, SEM_SALDO)
    agente = await _agente_do_rascunho(pedido, produto, dados.rascunho)
    if dados.etapa_inicial and dados.etapa_inicial not in {e["codigo"] for e in agente["etapas"]}:
        raise HTTPException(400, "Etapa inicial fora do funil deste produto.")
    resultado = await pedido.app.state.laboratorios.mensagem(
        escritorio=escritorio, agente=agente, id_conversa=dados.id_conversa, texto=dados.texto.strip(),
        etapa_inicial=dados.etapa_inicial)
    turno = resultado.get("turno") or {}
    chamadas = turno.get("chamadas") or []
    custo_usd = round(sum(float(c.get("custo_usd") or 0) for c in chamadas), 6)
    cotacao, markup = await _preco(pool, ctx.escritorio())
    _real, custo_brl = cobranca.calcular(custo_usd, cotacao, markup)
    gastou = bool(chamadas) and any((c.get("modelo") or "falso") != "falso" for c in chamadas)
    if gastou:                              # entra na carteira como qualquer chamada (origem 'laboratorio')
        try:
            await cobranca.gravar_chamadas(
                pool, id_escritorio=ctx.escritorio(), chamadas=[SimpleNamespace(**c) for c in chamadas],
                id_agente=produto.get("id_agente"), codigo_etapa=turno.get("etapa_antes") or None, origem="laboratorio")
        except Exception:
            log.exception("falha ao gravar as chamadas do laboratório do rascunho")
    antes, depois = turno.get("etapa_antes") or None, resultado.get("etapa") or turno.get("etapa_depois") or None
    return {
        "id_conversa": resultado["id_conversa"],
        "situacao": turno.get("situacao") or ("silencio" if not turno else "respondido"),
        "motivo": turno.get("motivo") or "",
        "mensagens": [m for m in turno.get("mensagens") or []],
        "etapa": depois, "etapa_nome": _nome_etapa(dados.rascunho, depois),
        "troca": ({"de": antes, "de_nome": _nome_etapa(dados.rascunho, antes), "para": depois,
                   "para_nome": _nome_etapa(dados.rascunho, depois)} if antes and depois and antes != depois else None),
        # Chaves com "_" na frente são controle interno do motor (ex.: variáveis sem valor): não são fatos do lead.
        "fatos_novos": [{"chave": f.get("chave"), "valor": f.get("valor"), "trecho": f.get("trecho")}
                        for f in turno.get("fatos_novos") or [] if not str(f.get("chave") or "").startswith("_")],
        "fatos": {k: v for k, v in (resultado.get("fatos") or {}).items() if not str(k).startswith("_")},
        "travas": _travas(turno),
        "sinais": turno.get("sinais") or [],
        "estado": resultado.get("estado") or "ativo",
        "custo_brl": round(custo_brl, 4), "custo_usd": custo_usd, "chamadas": len(chamadas), "gastou": gastou,
    }


@api.post("/produtos-ativados/{id_ativado}/laboratorio/recomecar")
async def laboratorio_recomecar(id_ativado: str, dados: Recomecar, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    await _ativado(_pool(pedido), ctx.escritorio(), id_ativado)
    pedido.app.state.laboratorios.esquecer(dados.id_conversa)
    return {"ok": True}


# ============================================================================ versões
@api.get("/produtos-ativados/{id_ativado}/versoes")
async def listar_versoes(id_ativado: str, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    pool = _pool(pedido)
    await _ativado(pool, ctx.escritorio(), id_ativado)
    if not await versoes.tem_versoes(pool):
        return {"disponivel": False, "versoes": []}
    return {"disponivel": True, "versoes": await versoes.listar(pool, ctx.escritorio(), id_ativado)}


async def _versao(pedido: Request, ctx: Contexto, id_ativado: str, numero: int) -> dict[str, Any]:
    pool = _pool(pedido)
    await _ativado(pool, ctx.escritorio(), id_ativado)
    if not await versoes.tem_versoes(pool):
        raise HTTPException(404, "Versão não encontrada.")
    versao = await versoes.uma(pool, ctx.escritorio(), id_ativado, numero)
    if not versao:
        raise HTTPException(404, "Versão não encontrada.")
    return versao


@api.get("/produtos-ativados/{id_ativado}/versoes/{numero}")
async def ver_versao(id_ativado: str, numero: int, pedido: Request, com: int | None = None,
                     ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """A versão e o que ela mudou. com=N compara com a versão N; sem com, com a anterior (o que esta publicação mudou)."""
    versao = await _versao(pedido, ctx, id_ativado, numero)
    base = None
    if com is not None:
        base = await _versao(pedido, ctx, id_ativado, com)
    elif numero > 1:
        try:
            base = await _versao(pedido, ctx, id_ativado, numero - 1)
        except HTTPException:
            base = None
    return {**versao, "comparada_com": base["numero"] if base else None,
            "diferencas": versoes.diferencas(base["conteudo"] if base else None, versao["conteudo"])}


@api.post("/produtos-ativados/{id_ativado}/versoes/{numero}/restaurar")
async def restaurar_versao(id_ativado: str, numero: int, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Devolve o conteúdo da versão para o rascunho do editor. NÃO publica: o agente no ar só muda no "Salvar"
    (que grava uma versão nova)."""
    versao = await _versao(pedido, ctx, id_ativado, numero)
    papeis_validos = {p for p in DESTINOS}
    conteudo = {**versao["conteudo"],
                "agentes": [a for a in versao["conteudo"].get("agentes") or [] if a.get("papel") in papeis_validos]}
    return {"numero": versao["numero"], "criado_em": versao["criado_em"], "autor": versao["autor"], "conteudo": conteudo,
            "aviso": f"Versão {versao['numero']} carregada no rascunho. Confira e salve para publicar."}
