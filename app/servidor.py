"""Fábrica dos servidores por papel (Frente D do plano: dois apps no Easypanel).

  ia      webhooks da Helena e da ZapSign, pipeline, fila de ações, follow-ups e os laços de fundo  -> app.entrada_ia:app
  painel  front compilado (painel/dist) e API de gestão /api/*, SEM laços de fundo              -> app.entrada_painel:app
  tudo    o servidor de sempre (desenvolvimento e testes): é o próprio app.main:app

Como funciona sem mexer no app/main.py: as rotas continuam definidas lá; aqui cada papel monta um FastAPI novo só com
as rotas que lhe cabem. As rotas do main.py leem o `app.state` do módulo (não o do pedido), então o app novo usa o MESMO
objeto `state` do app.main: em produção cada processo roda um papel só, e o estado é o daquele papel.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.routing import Mount

from app import main as principal

log = logging.getLogger("agentesia")

Papel = Literal["ia", "painel", "tudo"]
PAPEIS: tuple[str, ...] = ("ia", "painel", "tudo")


def _caminho(rota: Any) -> str:
    return getattr(rota, "path", "") or ""


def _roteador_incluido(rota: Any) -> Any | None:
    """Routers incluídos com app.include_router (o FastAPI novo guarda um _IncludedRouter com o original dentro)."""
    return getattr(rota, "original_router", None)


def _caminhos(rota: Any) -> set[str]:
    roteador = _roteador_incluido(rota)
    if roteador is None:
        return {_caminho(rota)}
    return set().union(*(_caminhos(r) for r in roteador.routes)) if roteador.routes else set()


def _eh_do_lab(caminho: str) -> bool:
    return caminho == "/lab" or caminho.startswith("/lab/")


def _lab_antigo_no_painel() -> bool:
    """O /lab antigo (em memória) só sobe no painel com senha: sem AGENTESIA_LAB_SENHA ele ficaria aberto na internet."""
    return bool(os.environ.get("AGENTESIA_LAB_SENHA", "").strip())


def _da_ia(caminho: str) -> bool:
    """Webhooks (/webhook/helena, /webhook/helena/{id}, /webhook/helena/{id}/ia, /webhook/zapsign/{id}), /saude e o
    diagnóstico com o banco /saude/banco."""
    return caminho.startswith("/webhook/") or caminho in ("/saude", "/saude/banco")


def _do_painel(caminho: str) -> bool:
    """API de gestão (/api/*) e entrada pela Helena (/entrar/helena). O /saude do painel é próprio."""
    return caminho.startswith(("/api/", "/entrar/")) or (_eh_do_lab(caminho) and _lab_antigo_no_painel())


def _montar_rotas(app: FastAPI, papel: str) -> None:
    """Copia do app.main as rotas do papel. /midia (só existe no modo local da mídia; no modo supabase a mídia é servida
    pelo bucket) vai nos dois (pasta compartilhada; ver docs/DEPLOY_EASYPANEL.md);
    /assets e o catch-all do painel/dist só no painel, com o catch-all sempre por último (senão engole as outras)."""
    pertence = _da_ia if papel == "ia" else _do_painel
    catch_all = None
    for rota in principal.app.router.routes:
        if isinstance(rota, Mount):
            if _caminho(rota) == "/midia" or (papel == "painel" and _caminho(rota) == "/assets"):
                app.router.routes.append(rota)
            continue
        roteador = _roteador_incluido(rota)
        if roteador is not None:
            caminhos = _caminhos(rota)
            if caminhos and all(pertence(c) for c in caminhos):
                app.include_router(roteador)
            continue
        caminho = _caminho(rota)
        if caminho == "/{caminho:path}":
            catch_all = rota
        elif isinstance(rota, APIRoute) and pertence(caminho):
            app.router.routes.append(rota)
    if papel == "painel" and catch_all is not None:
        app.router.routes.append(catch_all)


@asynccontextmanager
async def _ciclo_painel(app: FastAPI):
    """Igual ao do main.py, menos o atendimento e os laços de fundo: só pool, gestão, sessão e laboratórios."""
    from app import config as configuracao
    from app.banco.memoria import RepositorioMemoria
    from app.gestao.laboratorio import Laboratorios
    from app.gestao.seguranca import Assinador
    from app.pipeline import Atendimento

    cfg = configuracao.carregar()
    modelo = principal._modelo(cfg)

    repo_lab = RepositorioMemoria()                      # /lab antigo (só montado com AGENTESIA_LAB_SENHA)
    principal._montar_laboratorio(repo_lab)
    app.state.lab = Atendimento(repo_lab, modelo, cfg, helena=None, digitar=False)
    app.state.repo_lab = repo_lab

    app.state.assinador = Assinador()
    if app.state.assinador.provisorio:
        log.warning("sem AGENTESIA_SEGREDO_SESSAO: as sessões do painel caem quando o servidor reinicia")
    app.state.laboratorios = Laboratorios(modelo, cfg)
    app.state.atendimento = None                         # o painel não atende: quem atende é o app "ia"
    app.state.gestao = None
    app.state.tarefas = {}
    app.state.visao = False
    app.state.indexar_agora = None                       # o laço do app "ia" indexa os pendentes a cada 30 s
    repo = None
    if cfg.banco_url:
        from app.banco.postgres import RepositorioPostgres
        from app.gestao.repositorio import RepositorioGestao

        # Padrão 10: o Início abre ~8 pedidos de uma vez e várias rotas leem em paralelo (asyncio.gather); com 5 os
        # pedidos esperavam conexão livre, e cada ida ao banco (us-west-2) custa ~200 ms.
        repo = await RepositorioPostgres.conectar(cfg.banco_url, int(os.environ.get("AGENTESIA_BANCO_CONEXOES", "10")),
                                                  conferir=True)
        app.state.gestao = RepositorioGestao(repo._pool)
        log.info("painel ligado ao banco (sem laços de fundo)")
    else:
        log.info("painel sem AGENTESIA_BANCO_URL: as telas que dependem do banco respondem 503")
    app.state.cfg = cfg
    app.state.papel = "painel"
    try:
        yield
    finally:
        if repo:
            await repo.fechar()


@asynccontextmanager
async def _ciclo_ia(app: FastAPI):
    """O ciclo completo do main.py (pool, Atendimento, Executor, Disparador, retomar esperas, central de avisos e
    indexação da base de conhecimento)."""
    async with principal._ciclo(app):
        app.state.papel = "ia"
        yield


async def _saude_do_painel(pedido: Request) -> Any:
    """200 com o banco respondendo (ou sem banco configurado); 503 se o banco não responde."""
    estado = pedido.app.state
    gestao = getattr(estado, "gestao", None)
    corpo: dict[str, Any] = {"ok": True, "papel": "painel", "banco_configurado": gestao is not None,
                             "modelo": estado.cfg.modelo_padrao}
    if gestao is None:
        return corpo
    try:
        corpo["banco"] = await asyncio.wait_for(gestao.pool.fetchval("select 1"), 2) == 1
    except Exception as erro:                            # banco fora ou pendurado
        corpo.update(ok=False, banco=False, erro=type(erro).__name__)
    return corpo if corpo["ok"] else JSONResponse(corpo, status_code=503)


def criar_app(papel: Papel = "tudo") -> FastAPI:
    if papel not in PAPEIS:
        raise ValueError(f"papel inválido: {papel!r} (use um de {PAPEIS})")
    if papel == "tudo":
        return principal.app
    if papel == "ia":
        app = FastAPI(title="LawChat IA (atendimento)", lifespan=_ciclo_ia, docs_url=None, redoc_url=None,
                      openapi_url=None)
    else:
        app = FastAPI(title="LawChat IA (painel)", lifespan=_ciclo_painel)
        app.add_api_route("/saude", _saude_do_painel, methods=["GET"])
    app.state = principal.app.state                      # as rotas do main.py leem este objeto (ver o topo)
    _montar_rotas(app, papel)
    if papel == "painel":
        # Os middlewares do app.main não vêm junto com as rotas: sem isto o painel em produção mandava o JS e o JSON
        # sem compressão e nunca apagava os caches curtos ao salvar.
        from app.gestao.cache_curto import LimparAoEscrever
        app.add_middleware(principal._GzipDoPainel)
        app.add_middleware(LimparAoEscrever)
    return app


def rotas_montadas(app: FastAPI) -> set[str]:
    """Caminhos montados, com os dos routers incluídos (para os testes e para conferir na subida)."""
    caminhos: set[str] = set()
    for rota in app.router.routes:
        if _roteador_incluido(rota) is not None or isinstance(rota, (APIRoute, Mount)):
            caminhos |= _caminhos(rota)
    return caminhos
