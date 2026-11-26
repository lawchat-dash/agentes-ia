"""Rotas do follow-up padrão (docs/FOLLOWUP.md): prévia para a etapa da ativação, "Ligar com o padrão" do cliente e a
visão do admin de todos os escritórios (com a ação em lote). Nada liga sozinho: cada ligação é um clique ou um pedido
explícito, e cada uma fica em agentesia_alteracoes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.followup import padrao
from app.gestao.rotas import ADMIN, GESTAO, TODOS, Contexto, _repo

api = APIRouter(prefix="/api")


@api.get("/biblioteca/produtos/{id_produto}/followup-padrao")
async def followup_padrao_do_produto(id_produto: str, pedido: Request, ctx: Contexto = Depends(TODOS)) -> dict[str, Any]:
    """A cadência que a ativação vai copiar (etapa "Follow-up" do assistente). Aceita id ou slug."""
    linha = await _repo(pedido).pool.fetchrow(
        "select padrao_followup from agentesia_biblioteca_produtos where id::text = $1 or slug = $1 limit 1", id_produto)
    if not linha:
        raise HTTPException(404, "Produto não encontrado.")
    return padrao.previa_do_produto(dict(linha))


@api.post("/produtos-ativados/{id_ativado}/followup/ligar-padrao")
async def ligar_padrao(id_ativado: str, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Botão "Ligar com o padrão" (Início, tela do produto, Meus produtos)."""
    feito = await padrao.ligar_com_padrao(_repo(pedido).pool, id_ativado, id_usuario=ctx.id_usuario,
                                          id_escritorio=ctx.escritorio(), origem="painel")
    if not feito:
        raise HTTPException(404, "Produto não encontrado ou ainda não ativado.")
    return feito


@api.get("/admin/followup")
async def visao_admin(pedido: Request, ctx: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    produtos = await padrao.panorama(_repo(pedido).pool)
    ligados = sum(1 for p in produtos if p["followup"]["ligado"])
    return {"produtos": produtos, "totais": {"produtos": len(produtos), "ligados": ligados, "desligados": len(produtos) - ligados}}


class LigarEmLote(BaseModel):
    ids: list[str] = Field(default_factory=list)      # produtos ativados escolhidos
    todos_desligados: bool = False                    # ou: todos os ATIVOS com follow-up desligado
    simular: bool = False                             # só mostra quem seria ligado


@api.post("/admin/followup/ligar")
async def ligar_em_lote(dados: LigarEmLote, pedido: Request, ctx: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    """Liga com o padrão, um a um ou em lote. Exige a lista ou todos_desligados: nunca liga "tudo" sem pedir."""
    pool = _repo(pedido).pool
    if not dados.ids and not dados.todos_desligados:
        raise HTTPException(400, "Escolha os produtos ou marque todos os desligados.")
    produtos = {p["id_ativado"]: p for p in await padrao.panorama(pool)}
    if dados.todos_desligados:
        alvo = [i for i, p in produtos.items() if p["status"] == "ativo" and not p["followup"]["ligado"]]
    else:
        alvo = [i for i in dict.fromkeys(dados.ids) if i in produtos]
    if dados.simular:
        return {"simulado": True, "ligaria": [{"id_ativado": i, "nome": produtos[i]["nome"], "escritorio": produtos[i]["escritorio"]} for i in alvo]}
    ligados, avisos = [], []
    for id_ativado in alvo:
        feito = await padrao.ligar_com_padrao(pool, id_ativado, id_usuario=ctx.id_usuario, origem="admin")
        if feito:
            ligados.append({"id_ativado": id_ativado, "nome": feito["nome"], "escritorio": produtos[id_ativado]["escritorio"]})
            if feito["aviso"]:
                avisos.append(f"{produtos[id_ativado]['escritorio']} · {feito['nome']}: {feito['aviso']}")
    return {"simulado": False, "ligados": ligados, "avisos": avisos}
