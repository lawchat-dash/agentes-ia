"""Rotas do painel padrão do CRM (API interna da Helena, impersonate). PERIGOSO: age dentro da conta de outra empresa.

Travas (todas antes de qualquer chamada à Helena):
  1  desligado por padrão: sem AGENTESIA_PAINEL_CRM_LIGADO=1 toda rota responde 404 (e main.py só inclui o router
     com a variável ligada). Só no app de admin/painel.
  2  só admin LawChat (dono/admin) na visão LawChat, login há menos de 15 min, cabeçalho anti-CSRF
     (X-LawChat-Acao: painel-crm + Origin igual ao host quando vier), no máximo 3 pedidos de código por escritório/hora.
  3  trava por escritório: estado "em_andamento" gravado de forma atômica (um update condicional) em
     agentesia_escritorios.dados_helena.painel_crm; dois cliques nunca rodam juntos; cada passo é gravado.
  4  identidade: companyId do banco == items[].id da lista do parceiro; usuário com exatamente o e-mail configurado;
     tenantId == companyId. Divergência para tudo.
  5  token do impersonate só para o POST do painel (painel_crm.Fluxo.criar_painel); nunca em banco/log/resposta.
  6  sem repetição; timeout 15 s; timeout no POST do painel = "incerto", bloqueado até um admin marcar "conferido".
  7  retorno conferido (id + 6 etapas com os títulos esperados); senão "divergente" + aviso na central (agentesia_eventos).
  8  ?simular=1 faz login, empresas e usuários e mostra o que seria criado (sem impersonate e sem POST). Criar de verdade
     exige uma simulação ok nos últimos 30 min.
  9  auditoria em agentesia_alteracoes (quem, quando, IP, passos com situação e erro, sem token).
  + já existe painel gravado no escritório -> bloqueia antes de pedir código.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.gestao import painel_crm, sincronizar_conta
from app.gestao.painel_crm import ErroPainelCrm
from app.gestao.rotas import ADMIN, COOKIE, Contexto, _repo
from app.gestao.seguranca import DURACAO_SESSAO_S

api = APIRouter(prefix="/api")

SESSAO_RECENTE_S = 15 * 60
LIMITE_POR_HORA = 3
VALIDADE_SIMULACAO = timedelta(minutes=30)
BLOQUEADOS = ("em_andamento", "incerto")


class Codigo(BaseModel):
    codigo: str = Field(min_length=4, max_length=12)


# ------------------------------------------------------------------------------------------------ travas
async def _guarda(pedido: Request, ctx: Contexto = Depends(ADMIN)) -> Contexto:
    if not painel_crm.ligado():
        raise HTTPException(404, "Not Found")
    if ctx.visao:
        raise HTTPException(403, "Saia da visão do cliente para usar esta ação.")
    sessao = pedido.app.state.assinador.ler(pedido.cookies.get(COOKIE))
    if not sessao or time.time() - (sessao.expira_em - DURACAO_SESSAO_S) > SESSAO_RECENTE_S:
        raise HTTPException(401, "Por segurança, entre de novo (login há menos de 15 minutos) para criar o painel.")
    return ctx


def _csrf(pedido: Request) -> None:
    if pedido.headers.get("x-lawchat-acao") != "painel-crm":
        raise HTTPException(403, "Pedido sem a confirmação do painel (CSRF).")
    origem = pedido.headers.get("origin")
    if origem and urlparse(origem).netloc != pedido.headers.get("host", pedido.url.netloc):
        raise HTTPException(403, "Origem do pedido não confere (CSRF).")


def _ip(pedido: Request) -> str | None:
    encaminhado = (pedido.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    return encaminhado or (pedido.client.host if pedido.client else None)


async def _escritorio(repo: Any, id_escritorio: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", id_escritorio):
        raise HTTPException(404, "Escritório não encontrado.")
    escritorio = await repo.escritorio(id_escritorio)
    if not escritorio:
        raise HTTPException(404, "Escritório não encontrado.")
    if not escritorio.get("id_conta_helena"):
        raise HTTPException(409, "O escritório não tem a conta da LawChat (companyId).")
    return escritorio


async def _estado(pool: Any, id_escritorio: str) -> dict[str, Any]:
    return ((await sincronizar_conta.ler_dados_helena(pool, id_escritorio)).get("painel_crm")) or {}


async def _ja_tem_painel(repo: Any, id_escritorio: str) -> bool:
    dados = await sincronizar_conta.ler_dados_helena(repo.pool, id_escritorio)
    crm = await repo.integracao(id_escritorio, "crm") or {}
    return bool((dados.get("ids") or {}).get("id_painel") or (crm.get("config") or {}).get("id_painel"))


async def _gravar_estado(pool: Any, id_escritorio: str, mudar: dict[str, Any]) -> None:
    await pool.execute(
        """update agentesia_escritorios set dados_helena = coalesce(dados_helena, '{}'::jsonb)
             || jsonb_build_object('painel_crm', coalesce(dados_helena -> 'painel_crm', '{}'::jsonb) || $2::jsonb)
           where id = $1::uuid""", id_escritorio, json.dumps(mudar, ensure_ascii=False, default=str))


async def _tomar_trava(pool: Any, id_escritorio: str, ctx: Contexto, simular: bool) -> bool:
    """Update condicional: só um pedido passa de 'livre' para 'em_andamento'."""
    marca = {"estado": "em_andamento", "desde": datetime.now(timezone.utc).isoformat(), "por": ctx.id_usuario,
             "simulacao_em_curso": simular, "passos": []}
    linha = await pool.fetchval(
        """update agentesia_escritorios set dados_helena = coalesce(dados_helena, '{}'::jsonb)
             || jsonb_build_object('painel_crm', coalesce(dados_helena -> 'painel_crm', '{}'::jsonb) || $2::jsonb)
           where id = $1::uuid
             and coalesce(dados_helena -> 'painel_crm' ->> 'estado', 'livre') not in ('em_andamento', 'incerto', 'criado', 'divergente')
           returning 1""", id_escritorio, json.dumps(marca))
    return bool(linha)


async def _auditar(repo: Any, ctx: Contexto, pedido: Request, id_escritorio: str, acao: str, resumo: str,
                   passos: list[dict[str, str]], erro: str | None = None, extra: dict[str, Any] | None = None) -> None:
    await repo.registrar_alteracao(
        id_usuario=ctx.id_usuario, id_escritorio=id_escritorio, tabela="agentesia_escritorios",
        id_registro=id_escritorio, acao=acao, resumo=resumo,
        depois={"ip": _ip(pedido), "quando": datetime.now(timezone.utc).isoformat(), "passos": passos, **(extra or {})},
        situacao="erro" if erro else "ok", erro=painel_crm.mascarar(erro) if erro else None)


def _http(pedido: Request):
    return getattr(pedido.app.state, "http_painel_crm", None)


def _conferir_config() -> None:
    falta = painel_crm.faltando()
    if falta:
        raise HTTPException(409, "Configure no servidor: " + ", ".join(falta))


# ------------------------------------------------------------------------------------------------ rotas
@api.get("/admin/escritorios/{id_escritorio}/painel-crm")
async def ver(id_escritorio: str, pedido: Request, ctx: Contexto = Depends(_guarda)) -> dict[str, Any]:
    repo = _repo(pedido)
    await _escritorio(repo, id_escritorio)
    estado = await _estado(repo.pool, id_escritorio)
    return {"estado": estado.get("estado", "livre"), "passos": estado.get("passos", []),
            "simulacao": estado.get("simulacao"), "erro": estado.get("erro"),
            "ja_tem_painel": await _ja_tem_painel(repo, id_escritorio), "falta_configurar": painel_crm.faltando()}


@api.post("/admin/escritorios/{id_escritorio}/painel-crm/codigo")
async def pedir_codigo(id_escritorio: str, pedido: Request, ctx: Contexto = Depends(_guarda)) -> dict[str, Any]:
    _csrf(pedido)
    repo = _repo(pedido)
    await _escritorio(repo, id_escritorio)
    _conferir_config()
    if await _ja_tem_painel(repo, id_escritorio):
        raise HTTPException(409, "Já existe painel do CRM neste escritório. Não é possível criar outro.")
    estado = await _estado(repo.pool, id_escritorio)
    if estado.get("estado") in BLOQUEADOS:
        raise HTTPException(409, "Há uma criação em andamento ou com resultado incerto. Confira na LawChat e marque como conferido.")
    tentativas = await repo.pool.fetchval(
        """select count(*) from agentesia_alteracoes where id_escritorio = $1::uuid and acao = 'painel_crm_codigo'
           and criado_em > now() - interval '1 hour'""", id_escritorio)
    if tentativas >= LIMITE_POR_HORA:
        raise HTTPException(429, "Limite de 3 tentativas por hora neste escritório. Tente mais tarde.")
    fluxo = painel_crm.Fluxo(_http(pedido))
    try:
        await fluxo.enviar_codigo()
    except ErroPainelCrm as erro:
        fluxo.marcar(erro.passo, "erro", erro.mensagem)
        await _auditar(repo, ctx, pedido, id_escritorio, "painel_crm_codigo", "Painel padrão do CRM: pedir código",
                       fluxo.andamento, erro.mensagem)
        raise HTTPException(502, f"Não foi possível pedir o código: {erro.mensagem}") from None
    finally:
        await fluxo.fechar()
    await _auditar(repo, ctx, pedido, id_escritorio, "painel_crm_codigo", "Painel padrão do CRM: código pedido",
                   fluxo.andamento)
    return {"enviado": True, "para": painel_crm.mascarar_email(fluxo.cfg["email"])}


@api.post("/admin/escritorios/{id_escritorio}/painel-crm")
async def criar(id_escritorio: str, dados: Codigo, pedido: Request, simular: bool = False,
                ctx: Contexto = Depends(_guarda)) -> dict[str, Any]:
    _csrf(pedido)
    repo = _repo(pedido)
    escritorio = await _escritorio(repo, id_escritorio)
    _conferir_config()
    if await _ja_tem_painel(repo, id_escritorio):
        raise HTTPException(409, "Já existe painel do CRM neste escritório. Não é possível criar outro.")
    id_conta = str(escritorio["id_conta_helena"])
    anterior = await _estado(repo.pool, id_escritorio)
    if not simular:
        sim = anterior.get("simulacao") or {}
        quando = sim.get("quando")
        if not quando or datetime.now(timezone.utc) - datetime.fromisoformat(quando) > VALIDADE_SIMULACAO \
                or sim.get("id_conta") != id_conta:
            raise HTTPException(409, "Faça a simulação antes (vale por 30 minutos) e confira conta, empresa e usuário.")
    try:
        tomou = await _tomar_trava(repo.pool, id_escritorio, ctx, simular)
    except asyncpg.UndefinedColumnError:
        raise HTTPException(503, "O banco ainda não tem a migração 006.") from None
    if not tomou:
        raise HTTPException(409, "Já há uma criação em andamento, incerta ou concluída neste escritório.")

    fluxo = painel_crm.Fluxo(_http(pedido))
    acao = "painel_crm_simulacao" if simular else "painel_crm_criar"
    try:
        acesso = await fluxo.login(dados.codigo.strip())
        empresa = await fluxo.empresa(acesso, id_conta)
        usuario = await fluxo.usuario_admin(acesso, id_conta)
        if empresa["id"].lower() != id_conta.lower():                 # trava 4 (de novo, antes de agir)
            raise ErroPainelCrm("empresas", "o id da empresa não bate com o do escritório")
        if simular:
            del acesso
            simulacao = {"quando": datetime.now(timezone.utc).isoformat(), "por": ctx.id_usuario, "id_conta": id_conta,
                         "empresa": empresa, "usuario": usuario,
                         "painel": {"titulo": painel_crm.painel_crm_padrao.TITULO,
                                    "etapas": painel_crm.painel_crm_padrao.TITULOS_DAS_ETAPAS}}
            fluxo.marcar("simulacao", "ok", "nada foi criado")
            await _gravar_estado(repo.pool, id_escritorio, {"estado": "livre", "passos": fluxo.andamento,
                                                            "simulacao": simulacao, "erro": None})
            await _auditar(repo, ctx, pedido, id_escritorio, acao, "Painel padrão do CRM: simulação ok", fluxo.andamento,
                           extra={"empresa": empresa, "usuario": {"id": usuario["id"], "nome": usuario["nome"]}})
            return {"ok": True, "simulacao": True, "conta": id_conta, "empresa": empresa, "usuario": usuario,
                    "painel": simulacao["painel"], "passos": fluxo.andamento}

        na_conta = await fluxo.impersonate(acesso, usuario["id"], id_conta)   # tenantId = companyId do escritório
        del acesso
        try:
            criado = await fluxo.criar_painel(na_conta, usuario["id"])
        finally:
            del na_conta                                                    # trava 5: descartado logo depois
        mapa, divergencias = painel_crm.conferir_retorno(criado)
        painel = {"id": criado.get("id"), "titulo": criado.get("title") or painel_crm.painel_crm_padrao.TITULO}
        if painel["id"]:
            from app.gestao import onboarding
            await onboarding.guardar_painel(repo, id_escritorio, {"id": str(painel["id"]), "titulo": painel["titulo"]},
                                            mapa)
        if divergencias:
            fluxo.marcar("conferencia", "erro", "; ".join(divergencias))
            estado_final = "divergente"
            await repo.pool.execute(
                """insert into agentesia_eventos (id_escritorio, tipo, gravidade, responsavel, descricao, detalhe)
                   values ($1::uuid, 'painel_crm_divergente', 'erro', 'lawchat', $2, $3::jsonb)""",
                id_escritorio, "Painel padrão do CRM criado com divergência: " + "; ".join(divergencias)
                + ". Confira o painel na LawChat.", json.dumps({"id_painel": painel["id"], "etapas_por_tipo": mapa}))
        else:
            fluxo.marcar("conferencia", "ok", "6 etapas com os títulos esperados")
            estado_final = "criado"
        fluxo.marcar("gravar", "ok", f"{len(mapa)}/6 etapas gravadas por tipo")
        await _gravar_estado(repo.pool, id_escritorio, {"estado": estado_final, "passos": fluxo.andamento,
                                                        "id_painel": painel["id"], "erro": "; ".join(divergencias) or None})
        await _auditar(repo, ctx, pedido, id_escritorio, acao,
                       f"Painel padrão do CRM {'criado' if not divergencias else 'criado com divergência'}",
                       fluxo.andamento, "; ".join(divergencias) or None,
                       extra={"id_painel": painel["id"], "etapas_por_tipo": mapa})
        return {"ok": not divergencias, "estado": estado_final, "id_painel": painel["id"], "etapas_por_tipo": mapa,
                "divergencias": divergencias, "passos": fluxo.andamento}
    except ErroPainelCrm as erro:
        fluxo.marcar(erro.passo, "incerto" if erro.incerto else "erro", erro.mensagem)
        estado_final = "incerto" if erro.incerto else "livre"
        mensagem = (f"Resultado incerto no passo {erro.passo}: {erro.mensagem}. Confira na LawChat se o painel foi "
                    "criado antes de tentar de novo; novas tentativas ficam bloqueadas até marcar como conferido."
                    if erro.incerto else f"Parou no passo {erro.passo}: {erro.mensagem}")
        await _gravar_estado(repo.pool, id_escritorio, {"estado": estado_final, "passos": fluxo.andamento,
                                                        "erro": mensagem})
        await _auditar(repo, ctx, pedido, id_escritorio, acao, "Painel padrão do CRM: " + (
            "simulação" if simular else "criação"), fluxo.andamento, mensagem)
        return {"ok": False, "estado": estado_final, "parou_em": erro.passo, "erro": mensagem, "passos": fluxo.andamento}
    except BaseException:
        await _gravar_estado(repo.pool, id_escritorio, {"estado": "incerto" if not simular else "livre",
                                                        "passos": fluxo.andamento, "erro": "falha inesperada"})
        await _auditar(repo, ctx, pedido, id_escritorio, acao, "Painel padrão do CRM: falha inesperada",
                       fluxo.andamento, "falha inesperada")
        raise
    finally:
        await fluxo.fechar()


@api.post("/admin/escritorios/{id_escritorio}/painel-crm/conferido")
async def marcar_conferido(id_escritorio: str, pedido: Request, ctx: Contexto = Depends(_guarda)) -> dict[str, Any]:
    """Depois de conferir na Helena um resultado incerto: libera nova tentativa. Se o painel foi criado, escolha-o no
    passo "Painel do CRM" do onboarding (isso bloqueia criar outro)."""
    _csrf(pedido)
    repo = _repo(pedido)
    await _escritorio(repo, id_escritorio)
    estado = await _estado(repo.pool, id_escritorio)
    if estado.get("estado") not in BLOQUEADOS:
        raise HTTPException(409, "Nada para conferir.")
    await _gravar_estado(repo.pool, id_escritorio, {"estado": "livre", "conferido_por": ctx.id_usuario,
                                                    "conferido_em": datetime.now(timezone.utc).isoformat()})
    await _auditar(repo, ctx, pedido, id_escritorio, "painel_crm_conferido",
                   f"Painel padrão do CRM: resultado '{estado.get('estado')}' conferido na LawChat", estado.get("passos") or [])
    return {"ok": True, "estado": "livre"}
