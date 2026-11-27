"""Superadmin › Logs: o log da plataforma (agentesia_log_plataforma, migração 018). Só a equipe LawChat.

  GET  /api/admin/logs?de=&ate=&status=ok|erro&funcao=&conta=&busca=&pagina=&por_pagina=   lista (mais novas primeiro)
  GET  /api/admin/logs/resumo?(mesmos filtros)     cartões: total, sucesso, erros, % sucesso, duração média, funções
  GET  /api/admin/logs/filtros                     contas e funções que já apareceram no log
  GET  /api/admin/logs/exportar.csv?(filtros)      o mesmo recorte em CSV (até 10 mil linhas)
  POST /api/admin/logs/acesso-cliente              a equipe abriu a visão do cliente (botão "Entrar como cliente")

Só leitura (menos o acesso-cliente, que só grava a linha do log). Sem a migração 018 a lista volta vazia com aviso.
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel

from app.gestao import log_plataforma
from app.gestao.rotas import ADMIN, Contexto, _repo

api = APIRouter(prefix="/api/admin/logs")

UUID = re.compile(r"[0-9a-fA-F-]{36}")
FUNCAO = re.compile(r"[a-z0-9_.]{1,80}")
SEM_TABELA = "O log da plataforma ainda não está no banco: aplique a migração db/migracoes/018_agentesia_log_plataforma.sql."
LIMITE_CSV = 10_000

_SELECT = """
    select l.id, l.criado_em, l.id_escritorio, e.nome as conta, e.id_conta_helena, l.id_usuario, u.nome as usuario,
           u.email as email_usuario, coalesce(l.papel, u.papel) as papel, l.funcao, l.rotulo, l.referencia, l.payload,
           l.resultado, l.status, l.erro, l.duracao_ms
    from agentesia_log_plataforma l
    left join agentesia_escritorios e on e.id = l.id_escritorio
    left join agentesia_usuarios u on u.id = l.id_usuario"""


def _data(texto: str | None, nome: str) -> datetime | None:
    if not texto:
        return None
    try:
        return datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, f"Data inválida em {nome}.") from None


def filtros_sql(args: list[Any], *, de: str | None = None, ate: str | None = None, status: str = "",
                funcao: str = "", conta: str | None = None, busca: str = "") -> list[str]:
    """Monta o where (sempre com parâmetros). Exposto para os testes."""
    onde: list[str] = []
    if (inicio := _data(de, "de")) is not None:
        args.append(inicio)
        onde.append(f"l.criado_em >= ${len(args)}")
    if (fim := _data(ate, "ate")) is not None:
        args.append(fim)
        onde.append(f"l.criado_em < ${len(args)}")
    if status:
        if status not in ("ok", "erro"):
            raise HTTPException(400, "Status: ok ou erro.")
        args.append(status)
        onde.append(f"l.status = ${len(args)}")
    if funcao:
        if not FUNCAO.fullmatch(funcao):
            raise HTTPException(400, "Função inválida.")
        args.append(funcao)
        onde.append(f"l.funcao = ${len(args)}")
    if conta:
        if conta == "plataforma":                       # ações sem conta (catálogo, equipe, cotação...)
            onde.append("l.id_escritorio is null")
        elif not UUID.fullmatch(conta):
            raise HTTPException(400, "Conta inválida.")
        else:
            args.append(conta)
            onde.append(f"l.id_escritorio = ${len(args)}::uuid")
    texto = (busca or "").strip()[:120]
    if texto:
        args.append("%" + texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
        n = len(args)
        onde.append(f"(l.referencia ilike ${n} or l.rotulo ilike ${n} or l.funcao ilike ${n} or l.erro ilike ${n} "
                    f"or e.nome ilike ${n} or u.nome ilike ${n} or u.email ilike ${n} or l.id::text ilike ${n} "
                    f"or l.id_escritorio::text ilike ${n})")
    return onde


def _onde(onde: list[str]) -> str:
    return (" where " + " and ".join(onde)) if onde else ""


def _obj(valor: Any) -> Any:
    if isinstance(valor, str):
        try:
            return json.loads(valor)
        except json.JSONDecodeError:
            return valor
    return valor


def _item(r: Any) -> dict[str, Any]:
    return {
        "id": str(r["id"]), "criado_em": r["criado_em"].isoformat(),
        "conta": {"id": str(r["id_escritorio"]) if r["id_escritorio"] else None, "nome": r["conta"],
                  "id_conta_helena": str(r["id_conta_helena"]) if r["id_conta_helena"] else None},
        "executado_por": {"id": str(r["id_usuario"]) if r["id_usuario"] else None, "nome": r["usuario"],
                          "email": r["email_usuario"], "papel": r["papel"]},
        "funcao": r["funcao"], "rotulo": r["rotulo"], "referencia": r["referencia"],
        "payload": _obj(r["payload"]), "resultado": _obj(r["resultado"]),
        "status": r["status"], "erro": r["erro"], "duracao_ms": r["duracao_ms"],
    }


@api.get("")
async def listar(pedido: Request, _: Contexto = Depends(ADMIN), de: str | None = None, ate: str | None = None,
                 status: str = "", funcao: str = "", conta: str | None = None, busca: str = "",
                 pagina: int = Query(1, ge=1, le=10_000), por_pagina: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
    args: list[Any] = []
    onde = filtros_sql(args, de=de, ate=ate, status=status, funcao=funcao, conta=conta, busca=busca)
    args.extend([por_pagina + 1, (pagina - 1) * por_pagina])
    sql = _SELECT + _onde(onde) + f" order by l.criado_em desc, l.id desc limit ${len(args) - 1} offset ${len(args)}"
    try:
        linhas = await _repo(pedido).pool.fetch(sql, *args)
    except asyncpg.UndefinedTableError:
        return {"itens": [], "pagina": pagina, "por_pagina": por_pagina, "tem_mais": False, "aviso": SEM_TABELA}
    tem_mais = len(linhas) > por_pagina
    return {"itens": [_item(r) for r in linhas[:por_pagina]], "pagina": pagina, "por_pagina": por_pagina,
            "tem_mais": tem_mais}


@api.get("/resumo")
async def resumo(pedido: Request, _: Contexto = Depends(ADMIN), de: str | None = None, ate: str | None = None,
                 status: str = "", funcao: str = "", conta: str | None = None, busca: str = "") -> dict[str, Any]:
    args: list[Any] = []
    onde = filtros_sql(args, de=de, ate=ate, status=status, funcao=funcao, conta=conta, busca=busca)
    sql = f"""select count(*)::int as total, count(*) filter (where l.status = 'ok')::int as sucesso,
                     count(*) filter (where l.status = 'erro')::int as erros,
                     avg(l.duracao_ms)::float8 as duracao_media_ms, count(distinct l.funcao)::int as funcoes
              from agentesia_log_plataforma l
              left join agentesia_escritorios e on e.id = l.id_escritorio
              left join agentesia_usuarios u on u.id = l.id_usuario{_onde(onde)}"""
    try:
        r = await _repo(pedido).pool.fetchrow(sql, *args)
    except asyncpg.UndefinedTableError:
        return {"total": 0, "sucesso": 0, "erros": 0, "taxa_sucesso": None, "duracao_media_ms": None, "funcoes": 0,
                "aviso": SEM_TABELA}
    total = r["total"] or 0
    return {"total": total, "sucesso": r["sucesso"] or 0, "erros": r["erros"] or 0,
            "taxa_sucesso": round((r["sucesso"] or 0) / total, 4) if total else None,
            "duracao_media_ms": round(r["duracao_media_ms"]) if r["duracao_media_ms"] is not None else None,
            "funcoes": r["funcoes"] or 0}


@api.get("/filtros")
async def filtros(pedido: Request, _: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    pool = _repo(pedido).pool
    contas = [{"id": str(c["id"]), "nome": c["nome"]}
              for c in await pool.fetch("select id, nome from agentesia_escritorios order by nome")]
    try:
        funcoes = [{"funcao": f["funcao"], "rotulo": f["rotulo"]} for f in await pool.fetch(
            """select distinct on (funcao) funcao, rotulo from agentesia_log_plataforma
               order by funcao, criado_em desc""")]
    except asyncpg.UndefinedTableError:
        funcoes = []
    return {"contas": contas, "funcoes": funcoes}


COLUNAS_CSV = ["quando", "conta", "id_conta", "funcao", "rotulo", "referencia", "status", "erro", "duracao_ms",
               "executado_por", "email", "papel", "payload", "resultado"]


def linhas_csv(itens: list[dict[str, Any]]) -> str:
    """CSV com ; e BOM (o Excel em português abre certo)."""
    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=";", lineterminator="\r\n")
    escritor.writerow(COLUNAS_CSV)
    for i in itens:
        escritor.writerow([
            i["criado_em"], i["conta"]["nome"] or "", i["conta"]["id"] or "", i["funcao"], i["rotulo"], i["referencia"] or "",
            i["status"], i["erro"] or "", "" if i["duracao_ms"] is None else i["duracao_ms"],
            i["executado_por"]["nome"] or "", i["executado_por"]["email"] or "", i["executado_por"]["papel"] or "",
            json.dumps(i["payload"], ensure_ascii=False) if i["payload"] is not None else "",
            json.dumps(i["resultado"], ensure_ascii=False) if i["resultado"] is not None else "",
        ])
    return "﻿" + saida.getvalue()


@api.get("/exportar.csv")
async def exportar(pedido: Request, _: Contexto = Depends(ADMIN), de: str | None = None, ate: str | None = None,
                   status: str = "", funcao: str = "", conta: str | None = None, busca: str = "") -> Response:
    args: list[Any] = []
    onde = filtros_sql(args, de=de, ate=ate, status=status, funcao=funcao, conta=conta, busca=busca)
    args.append(LIMITE_CSV)
    try:
        linhas = await _repo(pedido).pool.fetch(_SELECT + _onde(onde) + f" order by l.criado_em desc limit ${len(args)}", *args)
    except asyncpg.UndefinedTableError:
        raise HTTPException(409, SEM_TABELA) from None
    nome = f"log-plataforma-{datetime.now().strftime('%Y-%m-%d-%H%M')}.csv"
    return Response(linhas_csv([_item(r) for r in linhas]), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nome}"'})


class AcessoCliente(BaseModel):
    id_escritorio: str
    visao: str = "gestor"


@api.post("/acesso-cliente")
async def acesso_cliente(dados: AcessoCliente, pedido: Request, ctx: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    """A equipe LawChat entrou na visão do cliente (impersonate pelo painel: X-Visao). Só grava a linha do log."""
    if not UUID.fullmatch(dados.id_escritorio):
        raise HTTPException(400, "Conta inválida.")
    if dados.visao not in ("gestor", "atendente"):
        raise HTTPException(400, "Visão inválida.")
    escritorio = await _repo(pedido).escritorio(dados.id_escritorio)
    if not escritorio:
        raise HTTPException(404, "Escritório não encontrado.")
    gravou = await log_plataforma.registrar(
        pedido, ctx=ctx, id_escritorio=dados.id_escritorio, funcao="acesso.como_cliente",
        rotulo=f"Acesso como cliente (visão {dados.visao})", referencia=escritorio.get("nome"),
        payload={"visao": dados.visao}, resultado={"ok": True})
    return {"ok": True, "registrado": gravou}
