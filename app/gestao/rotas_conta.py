"""Rotas da conta da Helena: onboarding em passos e "Sincronizar conta" (migração 006).

Admin LawChat (por escritório, id no caminho):
  GET  /api/admin/escritorios/{id}/onboarding            passos guardados (não chama a Helena)
  POST /api/admin/escritorios/{id}/onboarding/conferir   confere todos os passos sem mudar nada na Helena
  POST /api/admin/escritorios/{id}/onboarding/avancar    faz o que cada passo pode fazer sozinho (webhook, canais,
                                                         etiquetas padrão, painel escolhido, cópia da conta); só o
                                                         que não está ok, a não ser com {"forcar": true}; com
                                                         {"passos": ["painel"], "id_painel": ...} só o painel
  POST /api/admin/escritorios/{id}/sincronizar           copia canais, painéis, colunas, etiquetas, equipes e usuários;
                                                         alinha os logins do painel com os usuários da conta
  GET  /api/admin/escritorios/{id}/helena-recursos       a cópia (?tipo=etiqueta&sumidos=true)
Gestor (escritório da sessão):
  POST /api/integracoes/helena/sincronizar
  GET  /api/integracoes/helena/recursos

Cada ação de admin fica em agentesia_alteracoes, também quando falha (situacao='erro').
"""

from __future__ import annotations

import os
import re
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.canal.helena_conta import ErroHelenaApi, HelenaParceiro
from app.gestao import onboarding, sincronizar_conta
from app.gestao.log_plataforma import registrado
from app.gestao.rotas import ADMIN, GESTAO, Contexto, _erro_helena, _esquecer_helena, _helena_do_escritorio, _repo, _salvar_token_helena

api = APIRouter(prefix="/api")


class Avancar(BaseModel):
    passos: list[str] | None = None
    id_painel: str | None = None
    titulo_painel: str | None = None
    etapas_por_tipo: dict[str, str] | None = None     # {"SDR": "<id da coluna>", ...}: vence o palpite pelo nome
    criar_equipe_ia: bool = False                     # "🤖 Comercial IA" vira a equipe PADRÃO da conta: só se marcado
    forcar: bool = False                              # refaz também os passos já ok/feito (sem: só o que falta)


async def _escritorio_existe(repo: Any, id_escritorio: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", id_escritorio):
        raise HTTPException(404, "Escritório não encontrado.")
    escritorio = await repo.escritorio(id_escritorio)
    if not escritorio:
        raise HTTPException(404, "Escritório não encontrado.")
    return escritorio


def _parceiro(pedido: Request) -> HelenaParceiro | None:
    """Token de parceiro (variável de ambiente): só para ler os dados cadastrais da empresa."""
    token = os.environ.get("AGENTESIA_HELENA_TOKEN_PARCEIRO")
    return HelenaParceiro(token, pedido.app.state.cfg.helena_url) if token else None


def _guardar_token(pedido: Request, repo: Any, id_escritorio: str):
    """Token da conta criado no onboarding: cofre (Vault) + só o final no banco, pelo mesmo caminho da tela."""
    async def _guardar(token: str) -> None:
        await _salvar_token_helena(pedido, repo, id_escritorio, token)
    return _guardar


def _helena_de(pedido: Request, repo: Any):
    async def _de(id_escritorio: str):
        return await _helena_do_escritorio(pedido, repo, id_escritorio)
    return _de


async def _onboarding(pedido: Request, ctx: Contexto, id_escritorio: str, *, aplicar: bool,
                      dados: Avancar | None = None) -> dict[str, Any]:
    repo = _repo(pedido)
    escritorio = await _escritorio_existe(repo, id_escritorio)
    dados = dados or Avancar()
    invalidos = [p for p in dados.passos or [] if p not in onboarding.CODIGOS]
    if invalidos:
        raise HTTPException(400, "Passo desconhecido: " + ", ".join(invalidos))
    try:
        resultado = await onboarding.conferir(
            repo=repo, id_escritorio=id_escritorio, helena_de=_helena_de(pedido, repo), aplicar=aplicar,
            passos=dados.passos, id_painel=dados.id_painel, titulo_painel=dados.titulo_painel,
            etapas_por_tipo=dados.etapas_por_tipo, parceiro=_parceiro(pedido),
            id_conta=str(escritorio.get("id_conta_helena") or "") or None,
            guardar_token=_guardar_token(pedido, repo, id_escritorio),
            http=getattr(pedido.app.state, "http_ativacao", None), criar_equipe_ia=dados.criar_equipe_ia,
            id_usuario=ctx.id_usuario, forcar=dados.forcar, escritorio=escritorio)
    except Exception as erro:
        if aplicar:
            await repo.registrar_alteracao(
                id_usuario=ctx.id_usuario, id_escritorio=id_escritorio, tabela="agentesia_escritorios",
                id_registro=id_escritorio, acao="onboarding", resumo=f"Onboarding de {escritorio['nome']}",
                situacao="erro", erro=onboarding._inesperado(erro))
        if isinstance(erro, ErroHelenaApi):
            raise _erro_helena(erro) from erro
        if isinstance(erro, HTTPException):
            raise
        # Nunca um 500 cru ("Internal Server Error" virava "Erro 500" na tela): texto legível, sem segredo.
        raise HTTPException(500, ("Não deu para avançar o onboarding: " if aplicar else "Não deu para conferir: ")
                            + onboarding._inesperado(erro) + ". O erro ficou no histórico da conta.") from erro
    if aplicar and resultado.get("completo"):
        # Conta pronta (os obrigatórios ok): a lista Contas passa a mostrar "Habilitado". Só grava a primeira vez.
        config = dict(escritorio.get("config") or {})
        if not (config.get("criar_agente") or {}).get("habilitado"):
            config["criar_agente"] = {"habilitado": True, "em": resultado.get("atualizado_em"), "por": ctx.id_usuario,
                                      "pelo_onboarding": True}
            await repo.alterar_escritorio(id_escritorio, {"config": config})
        resultado["habilitado"] = True
    if aplicar:
        feitos = [p["titulo"] for p in resultado["passos"] if p["situacao"] == "feito"]
        erros = [f"{p['titulo']}: {p['detalhe']}" for p in resultado["passos"] if p["situacao"] == "erro"]
        await repo.registrar_alteracao(
            id_usuario=ctx.id_usuario, id_escritorio=id_escritorio, tabela="agentesia_escritorios",
            id_registro=id_escritorio, acao="onboarding",
            resumo=f"Onboarding de {escritorio['nome']}: " + (", ".join(feitos) if feitos else "nada a fazer"),
            depois={"passos": {p["codigo"]: p["situacao"] for p in resultado["passos"]}},
            situacao="erro" if erros else "ok", erro="; ".join(erros) or None)
    return resultado


@api.get("/admin/escritorios/{id_escritorio}/onboarding")
async def ver_onboarding(id_escritorio: str, pedido: Request, _: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    repo = _repo(pedido)
    await _escritorio_existe(repo, id_escritorio)
    guardado = await onboarding.ler(repo.pool, id_escritorio)
    if not guardado.get("passos"):
        guardado = {**guardado, "passos": [{"codigo": c, "titulo": t, "situacao": "pendente", "detalhe": "ainda não conferido"}
                                           for c, t in onboarding.PASSOS]}
    quando = await repo.pool.fetchval(
        "select to_jsonb(e) ->> 'sincronizado_em' from agentesia_escritorios e where e.id = $1::uuid", id_escritorio)
    return {**guardado, "sincronizado_em": quando, "obrigatorios": sorted(onboarding.OBRIGATORIOS),
            "dados_helena": await sincronizar_conta.ler_dados_helena(repo.pool, id_escritorio)}


@api.post("/admin/escritorios/{id_escritorio}/onboarding/conferir")
async def conferir_onboarding(id_escritorio: str, pedido: Request, ctx: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    return await _onboarding(pedido, ctx, id_escritorio, aplicar=False)


@api.post("/admin/escritorios/{id_escritorio}/onboarding/avancar")
@registrado("conta.onboarding", "Onboarding da conta avançado", referencia=lambda a: a["id_escritorio"],
            payload=lambda a: a.get("dados") or {},
            resultado=lambda _a, r: {"passos": {p.get("codigo"): p.get("situacao") for p in (r or {}).get("passos") or []}},
            falha=lambda _a, r: "; ".join(f"{p.get('titulo')}: {p.get('detalhe')}" for p in (r or {}).get("passos") or []
                                          if p.get("situacao") == "erro") or None)
async def avancar_onboarding(id_escritorio: str, pedido: Request, dados: Avancar | None = None,
                             ctx: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    return await _onboarding(pedido, ctx, id_escritorio, aplicar=True, dados=dados)


async def _sincronizar(pedido: Request, ctx: Contexto, id_escritorio: str) -> dict[str, Any]:
    _esquecer_helena(id_escritorio)          # etiquetas/equipes do painel voltam a ser lidas da Helena
    repo = _repo(pedido)
    escritorio = await _escritorio_existe(repo, id_escritorio)

    async def falhou(erro: str) -> None:
        await repo.registrar_alteracao(
            id_usuario=ctx.id_usuario, id_escritorio=id_escritorio, tabela="agentesia_helena_recursos",
            id_registro=id_escritorio, acao="sincronizou", resumo=f"Sincronizar conta da LawChat ({escritorio['nome']})",
            situacao="erro", erro=erro)

    try:
        helena = await _helena_do_escritorio(pedido, repo, id_escritorio)
    except HTTPException as erro:
        await falhou(str(erro.detail))
        raise
    try:
        feita = await sincronizar_conta.sincronizar(
            repo=repo, id_escritorio=id_escritorio, helena=helena, parceiro=_parceiro(pedido),
            id_conta=str(escritorio.get("id_conta_helena") or "") or None, id_usuario=ctx.id_usuario,
            escritorio=escritorio)
    except asyncpg.UndefinedTableError as erro:
        await falhou("banco sem a migração 006")
        raise HTTPException(503, "O banco ainda não tem a migração 006 (cópia da conta da LawChat).") from erro
    except ErroHelenaApi as erro:
        await falhou(f"{erro.motivo}: {erro.detalhe}")
        raise _erro_helena(erro) from erro
    except Exception as erro:
        await falhou(onboarding._inesperado(erro))
        raise HTTPException(500, "Não deu para sincronizar a conta: " + onboarding._inesperado(erro)) from erro
    if not feita["tipos"]:                          # nada foi lido: token recusado, Helena fora...
        motivo = next(iter(feita["erros"].values()), "sem_conexao")
        await falhou("nada foi lido: " + ", ".join(f"{t} ({m})" for t, m in feita["erros"].items()))
        raise _erro_helena(ErroHelenaApi(motivo))
    resumo = ", ".join(f"{v['total']} {t}" + (f" (+{v['novos']})" if v["novos"] else "")
                       + (f" ({v['sumiram']} sumiram)" if v["sumiram"] else "") for t, v in feita["tipos"].items())
    if feita.get("usuarios"):
        resumo += f"; logins: {feita['usuarios']['texto']}"
    await repo.registrar_alteracao(
        id_usuario=ctx.id_usuario, id_escritorio=id_escritorio, tabela="agentesia_helena_recursos",
        id_registro=id_escritorio, acao="sincronizou", resumo=f"Conta da LawChat sincronizada: {resumo}",
        depois=feita["tipos"], situacao="erro" if feita["erros"] else "ok",
        erro=("falhou: " + ", ".join(f"{t} ({m})" for t, m in feita["erros"].items())) if feita["erros"] else None)
    return feita


@api.post("/admin/escritorios/{id_escritorio}/sincronizar")
async def sincronizar_admin(id_escritorio: str, pedido: Request, ctx: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    return await _sincronizar(pedido, ctx, id_escritorio)


# ============================================================================ tela Contas (superadmin)
def _conta_lawchat() -> str:
    return os.environ.get("AGENTESIA_HELENA_CONTA_LAWCHAT", "").strip().lower()


def _parceiro_ou_409(pedido: Request) -> HelenaParceiro:
    parceiro = _parceiro(pedido)
    if parceiro is None:
        raise HTTPException(409, "Configure AGENTESIA_HELENA_TOKEN_PARCEIRO no servidor para puxar as contas do LawChat.")
    return parceiro


@api.post("/admin/escritorios/sincronizar-lawchat")
@registrado("conta.sincronizar_todas", "Contas sincronizadas com a LawChat",
            resultado=lambda _a, r: {k: (r or {}).get(k) for k in ("total", "criadas", "atualizadas", "com_erro")},
            falha=lambda _a, r: f"{(r or {}).get('com_erro')} conta(s) com erro" if (r or {}).get("com_erro") else None,
            escritorio=None)
async def sincronizar_com_lawchat(pedido: Request, ctx: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    """"Sincronizar com LawChat" (sync do Weaver): todas as empresas do token de parceiro (GET core/v1/company,
    paginando) viram conta aqui; cria a que falta e atualiza a que existe, casando por id_conta_helena."""
    repo = _repo(pedido)

    async def registrar(resumo: str, *, situacao: str = "ok", erro: str | None = None, depois: Any = None) -> None:
        await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=None, tabela="agentesia_escritorios",
                                       id_registro=None, acao="sincronizou_contas", resumo=resumo,
                                       situacao=situacao, erro=erro, depois=depois)

    try:
        parceiro = _parceiro_ou_409(pedido)
        empresas = await parceiro.todas_as_empresas_completas()
    except HTTPException as erro:
        await registrar("Sincronizar com LawChat", situacao="erro", erro=str(erro.detail))
        raise
    except ErroHelenaApi as erro:
        await registrar("Sincronizar com LawChat", situacao="erro", erro=f"{erro.motivo}: {erro.detalhe}")
        raise _erro_helena(erro) from erro
    feito = await sincronizar_conta.sincronizar_contas(repo.pool, empresas, conta_lawchat=_conta_lawchat())
    await registrar(f"Sincronizar com LawChat: {feito['criadas']} criadas, {feito['atualizadas']} atualizadas, "
                    f"{feito['com_erro']} com erro",
                    situacao="erro" if feito["com_erro"] else "ok",
                    erro="; ".join(f"{e.get('nome') or e.get('id_conta_helena')}: {e['erro']}" for e in feito["erros"]) or None,
                    depois={k: feito[k] for k in ("total", "criadas", "atualizadas", "com_erro")})
    return feito


@api.post("/admin/escritorios/{id_escritorio}/sincronizar-lawchat")
async def sincronizar_uma_com_lawchat(id_escritorio: str, pedido: Request, ctx: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    """sync_one do Weaver: atualiza os dados desta conta a partir da empresa no token de parceiro."""
    repo = _repo(pedido)
    escritorio = await _escritorio_existe(repo, id_escritorio)

    async def registrar(situacao: str = "ok", erro: str | None = None) -> None:
        await repo.registrar_alteracao(
            id_usuario=ctx.id_usuario, id_escritorio=id_escritorio, tabela="agentesia_escritorios",
            id_registro=id_escritorio, acao="sincronizou_conta",
            resumo=f"Sincronizar com LawChat: {escritorio['nome']}", situacao=situacao, erro=erro)

    if not escritorio.get("id_conta_helena"):
        await registrar("erro", "conta sem id da LawChat")
        raise HTTPException(409, "Esta conta não tem o id da conta no LawChat.")
    try:
        empresa = await sincronizar_conta.empresa_bruta(_parceiro_ou_409(pedido), str(escritorio["id_conta_helena"]))
    except HTTPException as erro:
        await registrar("erro", str(erro.detail))
        raise
    except ErroHelenaApi as erro:
        await sincronizar_conta.marcar_erro_sync(repo.pool, str(escritorio["id_conta_helena"]), erro.motivo)
        await registrar("erro", f"{erro.motivo}: {erro.detalhe}")
        raise _erro_helena(erro) from erro
    if not empresa:
        await sincronizar_conta.marcar_erro_sync(repo.pool, str(escritorio["id_conta_helena"]), "não encontrada no LawChat")
        await registrar("erro", "empresa não encontrada no token de parceiro")
        raise HTTPException(404, "Esta conta não foi encontrada no LawChat (token de parceiro).")
    await sincronizar_conta.gravar_empresa(repo.pool, empresa, conta_lawchat=_conta_lawchat())
    await registrar()
    return {"ok": True, "conta": sincronizar_conta.limpar_empresa(empresa)}


class HabilitarAgente(BaseModel):
    criar_equipe_ia: bool = False          # "🤖 Comercial IA" como equipe PADRÃO da conta: só se marcado


async def habilitar_agente(pedido: Request, ctx: Contexto, id_escritorio: str, *, criar_equipe_ia: bool = False) -> dict[str, Any]:
    """"Criar Agente: Habilitar" = a integração inicial (a mesma lógica do POST /admin/escritorios e do
    onboarding/avançar): gera o token "IA LawChat" pelo parceiro (se ainda não há token), salva no cofre e testa,
    lê os números, cria as etiquetas padrão que faltam e conecta o webhook. A equipe da IA só com criar_equipe_ia.
    Marca config.criar_agente.habilitado quando o token ficou de pé. Tudo fica em agentesia_alteracoes."""
    _esquecer_helena(id_escritorio)
    repo = _repo(pedido)
    escritorio = await _escritorio_existe(repo, id_escritorio)

    async def falhou(motivo: str) -> None:
        await repo.registrar_alteracao(
            id_usuario=ctx.id_usuario, id_escritorio=id_escritorio, tabela="agentesia_escritorios",
            id_registro=id_escritorio, acao="habilitou_agente", resumo=f"Habilitar Criar Agente: {escritorio['nome']}",
            situacao="erro", erro=motivo)

    id_conta = str(escritorio.get("id_conta_helena") or "")
    # A conta da própria LawChat também pode receber o agente (é onde a equipe testa a IA de verdade).
    if not id_conta:
        await falhou("conta sem id da LawChat")
        raise HTTPException(409, "Esta conta não tem o id da conta no LawChat. Sincronize com o LawChat antes.")
    tem_token = bool(((await repo.integracoes(id_escritorio)).get("helena") or {}).get("tem_segredo"))
    if not tem_token and _parceiro(pedido) is None:
        await falhou("sem token de parceiro (AGENTESIA_HELENA_TOKEN_PARCEIRO)")
        raise HTTPException(409, "Sem token de parceiro no servidor (AGENTESIA_HELENA_TOKEN_PARCEIRO) para gerar o token da conta.")

    passos = ["token", "webhook", "etiquetas", "canais", "usuarios"] + (["equipe"] if criar_equipe_ia else [])
    resultado = await _onboarding(pedido, ctx, id_escritorio, aplicar=True, dados=Avancar(passos=passos))
    por_codigo = {p["codigo"]: p for p in resultado["passos"]}
    habilitado = por_codigo.get("token", {}).get("situacao") in ("ok", "feito")
    if habilitado:
        config = dict(((await repo.escritorio(id_escritorio)) or escritorio).get("config") or {})
        config["criar_agente"] = {"habilitado": True, "em": resultado.get("atualizado_em"), "por": ctx.id_usuario,
                                  "com_equipe_ia": criar_equipe_ia}
        await repo.alterar_escritorio(id_escritorio, {"config": config})
    erros = [f"{p['titulo']}: {p['detalhe']}" for c, p in por_codigo.items() if c in passos and p["situacao"] == "erro"]
    await repo.registrar_alteracao(
        id_usuario=ctx.id_usuario, id_escritorio=id_escritorio, tabela="agentesia_escritorios",
        id_registro=id_escritorio, acao="habilitou_agente",
        resumo=f"Criar Agente {'habilitado' if habilitado else 'não habilitado'}: {escritorio['nome']}",
        depois={"passos": {c: por_codigo[c]["situacao"] for c in passos if c in por_codigo}},
        situacao="ok" if habilitado and not erros else "erro", erro="; ".join(erros) or None)
    return {"habilitado": habilitado, "passos": [por_codigo[c] for c in passos if c in por_codigo],
            "onboarding": resultado}


@api.post("/admin/escritorios/{id_escritorio}/habilitar-agente")
@registrado("conta.plataforma_liberada", "Plataforma liberada (Criar Agente habilitado)", referencia=lambda a: a["id_escritorio"],
            payload=lambda a: a.get("dados") or {},
            resultado=lambda _a, r: {"habilitado": (r or {}).get("habilitado"),
                                     "passos": {p.get("codigo"): p.get("situacao") for p in (r or {}).get("passos") or []}},
            falha=lambda _a, r: None if (r or {}).get("habilitado") else "Criar Agente não ficou habilitado (token da conta não ficou de pé)")
async def habilitar_agente_rota(id_escritorio: str, pedido: Request, dados: HabilitarAgente | None = None,
                                ctx: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    return await habilitar_agente(pedido, ctx, id_escritorio, criar_equipe_ia=bool(dados and dados.criar_equipe_ia))


async def _listar(pedido: Request, id_escritorio: str, tipo: str | None, sumidos: bool) -> list[dict[str, Any]]:
    if tipo and tipo not in sincronizar_conta.TIPOS:
        raise HTTPException(400, "Tipo inválido.")
    repo = _repo(pedido)
    try:
        return await sincronizar_conta.listar(repo.pool, id_escritorio, tipo=tipo, incluir_sumidos=sumidos)
    except asyncpg.UndefinedTableError:
        return []


@api.get("/admin/escritorios/{id_escritorio}/helena-recursos")
async def recursos_admin(id_escritorio: str, pedido: Request, tipo: str | None = None, sumidos: bool = False,
                         _: Contexto = Depends(ADMIN)) -> list[dict[str, Any]]:
    await _escritorio_existe(_repo(pedido), id_escritorio)
    return await _listar(pedido, id_escritorio, tipo, sumidos)


@api.post("/integracoes/helena/sincronizar")
async def sincronizar_gestor(pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    return await _sincronizar(pedido, ctx, ctx.escritorio())


@api.get("/integracoes/helena/recursos")
async def recursos_gestor(pedido: Request, tipo: str | None = None, sumidos: bool = False,
                          ctx: Contexto = Depends(GESTAO)) -> list[dict[str, Any]]:
    return await _listar(pedido, ctx.escritorio(), tipo, sumidos)
