"""Página /superadmin: só a equipe LawChat entra; tentativas erradas demais bloqueiam o login por 15 minutos."""

import os
import uuid

import pytest

from app.gestao import rotas
from tests.test_gestao import ambiente  # noqa: F401  (fixture do painel com a Helena simulada)

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")


@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_superadmin_so_equipe_lawchat_e_limite_de_tentativas(ambiente):
    from tests.test_gestao import _entrar

    cliente, _simulada, email_admin, _banco = ambiente
    rotas._FALHAS_LOGIN.clear()

    # Equipe LawChat entra pela página do superadmin.
    r = await cliente.post("/api/entrar", json={"email": email_admin, "senha": "senha-admin-123", "superadmin": True})
    assert r.status_code == 200, r.text
    eu = (await cliente.get("/api/eu")).json()
    assert eu["papel"] in ("dono_lawchat", "admin_lawchat")

    # Um gestor de escritório.
    email_gestor = f"gestor-{uuid.uuid4().hex[:6]}@escritorio.com"
    criado = (await cliente.post("/api/admin/escritorios", json={"nome": "Escritório X", "email_gestor": email_gestor})).json()
    senha_gestor = criado["senha_provisoria"]
    await cliente.post("/api/sair")
    cliente.cookies.clear()

    # Pela página do superadmin: recusado, sem abrir sessão.
    r = await cliente.post("/api/entrar", json={"email": email_gestor, "senha": senha_gestor, "superadmin": True})
    assert r.status_code == 403
    assert (await cliente.get("/api/eu")).status_code == 401
    # Pelo login normal ele entra.
    assert (await cliente.post("/api/entrar", json={"email": email_gestor, "senha": senha_gestor})).status_code == 200
    await cliente.post("/api/sair")
    cliente.cookies.clear()

    # Senha errada demais: bloqueia (mesmo com a senha certa depois), sem dizer se o e-mail existe.
    rotas._FALHAS_LOGIN.clear()
    for _ in range(rotas._MAX_FALHAS_LOGIN):
        assert (await cliente.post("/api/entrar", json={"email": email_admin, "senha": "errada-123"})).status_code == 401
    r = await cliente.post("/api/entrar", json={"email": email_admin, "senha": "senha-admin-123", "superadmin": True})
    assert r.status_code == 429
    rotas._FALHAS_LOGIN.clear()
    await _entrar(cliente, email_admin, "senha-admin-123")
