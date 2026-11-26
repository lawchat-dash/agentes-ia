"""Entrar no painel com o código que a plataforma manda (e-mail ou telefone), sem senha nossa.

Usa o mesmo login da tela oficial da plataforma (API interna, a mesma de painel_crm.py):

  enviar       POST {login}/auth/v2/login/send-otp
               e-mail:   {"email","type":"EMAIL","website":"","partnerId"}
               telefone: {"phoneNumber","type":"PHONENUMBER","website":"","partnerId"}   (DDD + número, sem 55)
  confirmar    POST {login}/auth/v2/login/authenticate
               {"grantType":"OTP","partnerId","internalDeviceId": id do navegador,"email"|"phoneNumber","password": código}
               -> accessToken (JWT) e refreshToken
  empresas     GET  {login}/core/v4/company/filter/me?pageSize=50&page=1&orderBy=name&userId=…&searchableText=
               &includeDetails=ALL   Authorization: Bearer <accessToken>
               ids das empresas = id_conta_helena dos nossos escritórios

Cabeçalhos: Content-Type/Accept json, Origin e Referer = AGENTESIA_HELENA_PARCEIRO_ORIGEM (ex.: https://advmidia.wts.chat).

O accessToken só PROVA a identidade: lemos o payload do JWT (sem validar a assinatura, que é da plataforma; ele veio
direto dela por TLS) para pegar id/e-mail/telefone/nome e conferir que bate com o que a pessoa digitou, usamos o token
na consulta de empresas e o descartamos na mesma requisição. Nunca vai para banco, log, exceção ou resposta. O código
digitado também nunca vai para log. Em log só entram as CHAVES das respostas (para ajustar o formato), nunca valores.

Quem entra:
  1. usuário nosso ligado ao id da plataforma (id_usuario_helena) ou com o mesmo e-mail;
     equipe LawChat (papéis *_lawchat) entra se já existir; cliente precisa do escritório ativo;
  2. senão, o primeiro escritório ativo cuja conta está nas empresas da pessoa: cria o usuário ligado a ele
     (gestor se o perfil na empresa for admin/dono, senão atendente; sem senha utilizável; trocar_senha falso).
     Reserva: se a consulta de empresas falhar, procura a pessoa (id/e-mail) nos usuários de cada conta ativa, com o
     token permanente do escritório (usuarios_helena.listar).

Configuração (ambiente): AGENTESIA_HELENA_LOGIN_URL (valor certo: https://wapi.wts.chat; sem ela usa
AGENTESIA_HELENA_INTERNA_URL), AGENTESIA_HELENA_PARCEIRO_ID, AGENTESIA_HELENA_PARCEIRO_ORIGEM.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import time
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from app.canal.helena_conta import ErroHelenaApi, HelenaConta
from app.gestao import usuarios_helena
from app.gestao.rotas import (PAPEIS_LAWCHAT, _anotar_falha_login, _chaves_login, _FALHAS_LOGIN, _gravar_sessao,
                              _login_bloqueado, _repo)

log = logging.getLogger("agentesia")
api = APIRouter(prefix="/api")

TIMEOUT_S = 15.0
TIMEOUT_LISTA_S = 8.0
# Nos testes: um httpx.MockTransport no lugar da rede.
TRANSPORTE: httpx.AsyncBaseTransport | None = None

# Nome do campo do telefone nos dois pedidos (fácil de ajustar se a plataforma mudar).
CAMPO_TELEFONE = "phoneNumber"
TIPO_TELEFONE = "PHONENUMBER"

GENERICO = "Se este acesso tiver permissão, o código chega em instantes."
FORA_DO_AR = "Não foi possível falar com a plataforma agora. Tente de novo em instantes."
CODIGO_ERRADO = "Código errado ou vencido. Confira os 6 dígitos ou peça um novo código."
SEM_ESCRITORIO = "Este acesso não está ligado a nenhum escritório ativo no LawChat. Fale com o responsável do escritório."

# Envio de código: por e-mail/telefone 5 em 15 min; por IP 20 em 15 min.
_ENVIOS: dict[str, list[float]] = {}
_JANELA_ENVIO_S, _MAX_ENVIOS_ID, _MAX_ENVIOS_IP = 15 * 60, 5, 20


# ============================================================================ configuração
def configuracao() -> dict[str, str]:
    url = (os.environ.get("AGENTESIA_HELENA_LOGIN_URL") or os.environ.get("AGENTESIA_HELENA_INTERNA_URL") or "").strip()
    return {"url": url.rstrip("/"), "parceiro": (os.environ.get("AGENTESIA_HELENA_PARCEIRO_ID") or "").strip(),
            "origem": (os.environ.get("AGENTESIA_HELENA_PARCEIRO_ORIGEM") or "").strip().rstrip("/")}


def _cfg() -> dict[str, str]:
    cfg = configuracao()
    if not all(cfg.values()):
        raise HTTPException(503, "A entrada por código ainda não está configurada. Use \"Entrar com senha\".")
    return cfg


def _cabecalhos(cfg: dict[str, str], token: str | None = None) -> dict[str, str]:
    cab = {"Content-Type": "application/json", "Accept": "application/json",
           "Origin": cfg["origem"], "Referer": cfg["origem"] + "/"}
    if token:
        cab["Authorization"] = f"Bearer {token}"
    return cab


def _cliente() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT_S, transport=TRANSPORTE) if TRANSPORTE else httpx.AsyncClient(timeout=TIMEOUT_S)


# ============================================================================ identificador
class Pedido(BaseModel):
    email: str | None = None
    telefone: str | None = None


class Confirmar(Pedido):
    codigo: str
    dispositivo: str | None = None


_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,}$")


def telefone_normalizado(bruto: str) -> str | None:
    """DDD + número (10 ou 11 dígitos), sem o 55."""
    digitos = re.sub(r"\D", "", bruto or "")
    if len(digitos) in (12, 13) and digitos.startswith("55"):
        digitos = digitos[2:]
    return digitos if len(digitos) in (10, 11) and not digitos.startswith("0") else None


def _identificador(dados: Pedido) -> tuple[str, str]:
    """('email', e-mail) ou ('telefone', DDD+número). 400 se nenhum dos dois for válido."""
    if dados.email and dados.email.strip():
        email = dados.email.strip().lower()
        if not _EMAIL.match(email):
            raise HTTPException(400, "Digite um e-mail válido.")
        return "email", email
    if dados.telefone and dados.telefone.strip():
        telefone = telefone_normalizado(dados.telefone)
        if not telefone:
            raise HTTPException(400, "Digite o celular com DDD (ex.: 31 98693-6492).")
        return "telefone", telefone
    raise HTTPException(400, "Digite o e-mail ou o celular.")


def _campo(tipo: str, valor: str) -> dict[str, str]:
    return {"email": valor} if tipo == "email" else {CAMPO_TELEFONE: valor}


def _chaves(pedido: Request, tipo: str, valor: str) -> list[str]:
    """Chaves do limite de tentativas (as mesmas do login por senha para e-mail e IP)."""
    return _chaves_login(pedido, valor if tipo == "email" else f"tel:{valor}")


def _mascarar(tipo: str, valor: str) -> str:
    if tipo == "email":
        nome, _, dominio = valor.partition("@")
        return nome[:2] + "…@" + dominio
    return "…" + valor[-4:]


def _dispositivo(bruto: str | None, pedido: Request, valor: str) -> str:
    """Id do navegador (o front gera um UUID e guarda). Sem ele, um UUID derivado do navegador e do acesso."""
    if bruto and re.fullmatch(r"[0-9a-fA-F-]{32,36}", bruto.strip()):
        return bruto.strip().lower()
    base = f"{pedido.headers.get('user-agent', '')}|{valor}".encode()
    return str(uuid.UUID(hashlib.sha256(base).hexdigest()[:32]))


# ============================================================================ token (só leitura do payload)
def claims_do_token(token: str) -> dict[str, Any]:
    """Payload do JWT sem validar a assinatura. Nada aqui vai para log."""
    try:
        parte = token.split(".")[1]
        parte += "=" * (-len(parte) % 4)
        dados = json.loads(base64.urlsafe_b64decode(parte.encode()))
        return dados if isinstance(dados, dict) else {}
    except (IndexError, ValueError):
        return {}


def _texto(claims: dict[str, Any], *chaves: str) -> str | None:
    for chave in chaves:
        valor = claims.get(chave)
        if isinstance(valor, str) and valor.strip():
            return valor.strip()
    return None


def identidade(claims: dict[str, Any]) -> dict[str, str | None]:
    telefone = _texto(claims, "phone_number", "phoneNumber")
    if telefone:                                     # "+55|31986936492"
        telefone = telefone_normalizado(telefone.split("|")[-1])
    email = _texto(claims, "email")
    return {"id": _texto(claims, "nameid", "id", "sub", "userId"), "email": email.lower() if email else None,
            "telefone": telefone, "nome": _texto(claims, "unique_name", "name", "given_name")}


def _token(dados: Any) -> str | None:
    if isinstance(dados, dict):
        for chave in ("accessToken", "access_token", "token"):
            if isinstance(dados.get(chave), str) and dados[chave]:
                return dados[chave]
    return None


def _chaves_de(dados: Any) -> list[str]:
    return sorted(dados.keys()) if isinstance(dados, dict) else [type(dados).__name__]


# ============================================================================ rotas
@api.post("/entrar/codigo")
async def pedir_codigo(dados: Pedido, pedido: Request) -> dict[str, Any]:
    cfg = _cfg()
    tipo, valor = _identificador(dados)
    chave_id, chave_ip = _chaves(pedido, tipo, valor)
    agora = time.time()
    for chave, limite in ((chave_id, _MAX_ENVIOS_ID), (chave_ip, _MAX_ENVIOS_IP)):
        recentes = [t for t in _ENVIOS.get(chave, []) if agora - t < _JANELA_ENVIO_S]
        _ENVIOS[chave] = recentes
        if len(recentes) >= limite:
            raise HTTPException(429, "Muitos códigos pedidos seguidos. Espere 15 minutos e tente de novo.")
    if _login_bloqueado([chave_id, chave_ip]):
        raise HTTPException(429, "Muitas tentativas erradas. Espere 15 minutos e tente de novo.")
    for chave in (chave_id, chave_ip):
        _ENVIOS.setdefault(chave, []).append(agora)

    corpo = {**_campo(tipo, valor), "type": "EMAIL" if tipo == "email" else TIPO_TELEFONE, "website": "",
             "partnerId": cfg["parceiro"]}
    try:
        async with _cliente() as http:
            resposta = await http.post(f"{cfg['url']}/auth/v2/login/send-otp", headers=_cabecalhos(cfg),
                                       content=json.dumps(corpo).encode())
    except httpx.HTTPError as erro:
        log.warning("login por código: send-otp sem resposta (%s)", type(erro).__name__)
        raise HTTPException(503, FORA_DO_AR) from None
    if resposta.status_code >= 500:
        log.warning("login por código: send-otp HTTP %s", resposta.status_code)
        raise HTTPException(503, FORA_DO_AR)
    if resposta.status_code >= 400:
        # Acesso que a plataforma não conhece: mesma resposta (não revela quem tem conta).
        log.info("login por código: send-otp recusado HTTP %s para %s", resposta.status_code, _mascarar(tipo, valor))
    return {"ok": True, "mensagem": GENERICO}


@api.post("/entrar/codigo/confirmar")
async def confirmar_codigo(dados: Confirmar, pedido: Request, resposta: Response) -> dict[str, Any]:
    cfg = _cfg()
    tipo, valor = _identificador(dados)
    chaves = _chaves(pedido, tipo, valor)
    if _login_bloqueado(chaves):
        raise HTTPException(429, "Muitas tentativas erradas. Espere 15 minutos e tente de novo.")
    codigo = re.sub(r"\s", "", dados.codigo or "")
    if not re.fullmatch(r"\d{4,8}", codigo):
        _anotar_falha_login(chaves)
        raise HTTPException(401, CODIGO_ERRADO)
    repo = _repo(pedido)

    corpo = {"grantType": "OTP", "partnerId": cfg["parceiro"],
             "internalDeviceId": _dispositivo(dados.dispositivo, pedido, valor), **_campo(tipo, valor),
             "password": codigo}
    async with _cliente() as http:
        try:
            r = await http.post(f"{cfg['url']}/auth/v2/login/authenticate", headers=_cabecalhos(cfg),
                                content=json.dumps(corpo).encode())
        except httpx.HTTPError as erro:
            log.warning("login por código: authenticate sem resposta (%s)", type(erro).__name__)
            raise HTTPException(503, FORA_DO_AR) from None
        del corpo, codigo
        if r.status_code in (400, 401, 403, 404, 422):
            _anotar_falha_login(chaves)
            raise HTTPException(401, CODIGO_ERRADO)
        if r.status_code >= 400:
            log.warning("login por código: authenticate HTTP %s", r.status_code)
            raise HTTPException(503, FORA_DO_AR)
        try:
            dados_login = r.json()
        except ValueError:
            dados_login = None
        token = _token(dados_login)
        log.info("login por código: authenticate devolveu as chaves %s", _chaves_de(dados_login))
        del dados_login, r
        if not token:
            raise HTTPException(503, "A plataforma não confirmou o acesso. Peça um novo código.")

        quem = identidade(claims_do_token(token))
        # O que a plataforma diz que é a pessoa precisa bater com o que ela digitou.
        if (tipo == "email" and quem["email"] and quem["email"] != valor) or \
                (tipo == "telefone" and quem["telefone"] and quem["telefone"] != valor):
            token = None
            _anotar_falha_login(chaves)
            raise HTTPException(401, "A plataforma confirmou outro acesso. Peça um novo código.")
        if tipo == "email":
            quem["email"] = valor
        contas = await _empresas_da_pessoa(http, cfg, token, quem["id"])
        token = None                                  # descartado: não sai desta requisição
    del token

    usuario = await _achar_ou_criar(pedido, repo, quem, contas)
    for chave in chaves:
        _FALHAS_LOGIN.pop(chave, None)
    _gravar_sessao(pedido, resposta, usuario["id"])
    await repo.registrar_acesso(usuario["id"])
    lawchat = usuario["papel"] in PAPEIS_LAWCHAT
    return {"ok": True, "trocar_senha": False, "destino": "/admin/escritorios" if lawchat else "/"}


# ============================================================================ quem é a pessoa
_PERFIS_GESTOR = {"ADMIN", "ADMINISTRATOR", "ADMINISTRADOR", "OWNER", "DONO", "MANAGER", "GESTOR"}


def _papel_na_empresa(empresa: dict[str, Any]) -> str:
    """gestor se algum campo de perfil da pessoa na empresa disser admin/dono/gestor; senão atendente."""
    candidatos: list[Any] = [empresa]
    for chave in ("user", "currentUser", "agent", "me", "member", "details", "userDetails"):
        if isinstance(empresa.get(chave), dict):
            candidatos.append(empresa[chave])
    for c in candidatos:
        if c.get("isOwner") is True or c.get("isAdmin") is True:
            return "gestor"
        for chave in ("profile", "role", "userProfile", "userRole", "profileName"):
            if str(c.get(chave) or "").strip().upper() in _PERFIS_GESTOR:
                return "gestor"
    return "atendente"


async def _empresas_da_pessoa(http: httpx.AsyncClient, cfg: dict[str, str], token: str,
                              id_pessoa: str | None) -> dict[str, str] | None:
    """{id da conta (minúsculo): papel}. None se a consulta falhou (aí vale a reserva pelos usuários das contas)."""
    params = {"pageSize": 50, "page": 1, "orderBy": "name", "searchableText": "", "includeDetails": "ALL"}
    if id_pessoa:
        params["userId"] = id_pessoa
    try:
        r = await http.get(f"{cfg['url']}/core/v4/company/filter/me", headers=_cabecalhos(cfg, token), params=params)
    except httpx.HTTPError as erro:
        log.warning("login por código: empresas sem resposta (%s)", type(erro).__name__)
        return None
    if r.status_code >= 400:
        log.warning("login por código: empresas HTTP %s", r.status_code)
        return None
    try:
        dados = r.json()
    except ValueError:
        return None
    itens = dados.get("items") or dados.get("data") or [] if isinstance(dados, dict) else dados or []
    if isinstance(itens, list) and itens and isinstance(itens[0], dict):
        log.info("login por código: empresas devolveu %s item(ns) com as chaves %s", len(itens), _chaves_de(itens[0]))
    contas: dict[str, str] = {}
    for item in itens if isinstance(itens, list) else []:
        if isinstance(item, dict) and item.get("id"):
            contas.setdefault(str(item["id"]).lower(), _papel_na_empresa(item))
    return contas


async def _escritorios_ativos(repo: Any) -> list[dict[str, Any]]:
    """Escritórios ativos com conta da plataforma, menos a conta da própria LawChat (lá ninguém vira cliente)."""
    linhas = await repo.pool.fetch(
        """select e.id::text as id, e.nome, e.id_conta_helena::text as id_conta, i.id_segredo_vault::text as segredo
           from agentesia_escritorios e
           left join agentesia_integracoes i on i.id_escritorio = e.id and i.tipo = 'helena'
           where e.situacao = 'ativo' and e.id_conta_helena is not null order by e.criado_em""")
    conta_lawchat = os.environ.get("AGENTESIA_HELENA_CONTA_LAWCHAT", "").strip().lower()
    return [dict(l) for l in linhas if l["id_conta"].lower() != conta_lawchat]


async def _procurar_nas_contas(pedido: Request, repo: Any, ativos: list[dict[str, Any]],
                               quem: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Reserva: a pessoa (pelo id ou e-mail) nos usuários de cada conta ativa, com o token permanente do escritório."""
    limite = asyncio.Semaphore(5)

    async def uma(esc: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]] | None:
        async with limite:
            token = await repo.ler_segredo(esc.get("segredo"))
            if not token:
                return None
            try:
                async with httpx.AsyncClient(timeout=TIMEOUT_LISTA_S) as http:
                    lista = await usuarios_helena.listar(HelenaConta(token, pedido.app.state.cfg.helena_url, http=http),
                                                         timeout=TIMEOUT_LISTA_S, limite_paginas=5)
            except (ErroHelenaApi, httpx.HTTPError):
                return None
            for a in lista:
                if a["ativo"] and ((quem["id"] and a["id_usuario"] == quem["id"]) or
                                   (quem["email"] and a["email"] == quem["email"])):
                    return esc, a
            return None

    return [r for r in await asyncio.gather(*(uma(e) for e in ativos)) if r]


async def _achar_ou_criar(pedido: Request, repo: Any, quem: dict[str, Any],
                          contas: dict[str, str] | None) -> dict[str, Any]:
    usuario = None
    if quem["id"]:
        linhas = await repo.pool.fetch("select id::text as id from agentesia_usuarios where id_usuario_helena = $1 "
                                       "order by ativo desc, criado_em", quem["id"])
        if linhas:
            usuario = await repo.usuario(linhas[0]["id"])
    if not usuario and quem["email"]:
        achado = await repo.usuario_por_email(quem["email"])
        usuario = await repo.usuario(achado["id"]) if achado else None
    if usuario:
        if not usuario["ativo"]:
            raise HTTPException(403, "Seu acesso está desativado. Fale com o responsável do escritório.")
        if quem["id"] and not usuario.get("id_usuario_helena"):
            # Liga ao usuário da plataforma (abas embutidas abrem logadas como a pessoa); o e-mail não muda.
            await repo.vincular_usuario_helena(usuario["id"], quem["id"], usuario["nome"])
            usuario = await repo.usuario(usuario["id"]) or usuario
        if usuario["papel"] in PAPEIS_LAWCHAT:
            return usuario
        situacao = await repo.pool.fetchval("select situacao from agentesia_escritorios where id = $1::uuid",
                                            usuario["id_escritorio"])
        if situacao == "ativo":
            return usuario
        raise HTTPException(403, SEM_ESCRITORIO)

    ativos = await _escritorios_ativos(repo)
    if contas is not None:
        achados = [(e, {"id_usuario": quem["id"], "nome": quem["nome"], "email": quem["email"],
                        "papel": contas[e["id_conta"].lower()]}) for e in ativos if e["id_conta"].lower() in contas]
    else:
        achados = await _procurar_nas_contas(pedido, repo, ativos, quem)
        achados = [(e, {**a, "papel": a["papel"] or "atendente"}) for e, a in achados]
    if not achados or not (quem["id"] or achados[0][1].get("id_usuario")):
        log.info("login por código: %s sem escritório ativo", _mascarar("email", quem["email"]) if quem["email"] else "telefone")
        raise HTTPException(403, SEM_ESCRITORIO)

    escritorio, pessoa = achados[0]
    id_plataforma = pessoa.get("id_usuario") or quem["id"]
    email = pessoa.get("email") or quem["email"]
    if not email or await repo.usuario_por_email(email):
        email = f"helena-{id_plataforma}@{escritorio['id'][:8]}.helena.local"
    nome = pessoa.get("nome") or quem["nome"] or (email.split("@")[0])
    criado = await repo.criar_usuario_da_helena(
        id_escritorio=escritorio["id"], id_usuario_helena=str(id_plataforma), email=email, nome=nome[:200],
        papel=pessoa["papel"] if pessoa["papel"] in ("gestor", "atendente") else "atendente",
        senha_hash=usuarios_helena.SEM_SENHA)
    resumo = f"{nome} entrou pela primeira vez com o código da plataforma, como {criado['papel']}"
    if len(achados) > 1:
        outros = ", ".join(e["nome"] for e, _ in achados[1:])
        resumo += f"; também está em outro(s) escritório(s): {outros} (ligado só a este)"
    await repo.registrar_alteracao(id_usuario=criado["id"], id_escritorio=escritorio["id"], tabela="agentesia_usuarios",
                                   id_registro=criado["id"], acao="criou", resumo=resumo)
    return await repo.usuario(criado["id"]) or criado
