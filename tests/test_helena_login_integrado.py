"""Atendimento: Login integrado da Helena (POST auth/v1/login/authenticate) pelo servidor.

O painel pede o link; o servidor chama a Helena com o token da conta do escritório e devolve o link de uso único.
A Helena é simulada. A parte com banco usa AGENTESIA_TESTE_PG_URL.
"""

import json
import os
import uuid

import httpx
import pytest

from app.canal import helena_conta
from app.gestao.rotas import _link_da_helena_e_seguro
from tests.test_gestao import ambiente  # noqa: F401  (fixture do painel com a Helena simulada)

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")


def test_so_aceita_link_https_da_helena():
    assert _link_da_helena_e_seguro("https://web.helena.run/auth/external-login?code=x")
    assert _link_da_helena_e_seguro("https://advmidia.wts.chat/auth/external-login?code=x")
    assert not _link_da_helena_e_seguro("http://web.helena.run/auth/external-login?code=x")       # sem https
    assert not _link_da_helena_e_seguro("https://helena.run.golpe.com/x")                          # domínio parecido
    assert not _link_da_helena_e_seguro("javascript:alert(1)")
    assert not _link_da_helena_e_seguro("")
    # O endereço configurado da Helena (teste local) também vale, com o mesmo esquema.
    assert _link_da_helena_e_seguro("http://127.0.0.1:8020/auth/external-login?code=x", "http://127.0.0.1:8020")
    assert not _link_da_helena_e_seguro("http://outro-host:8020/x", "http://127.0.0.1:8020")


async def test_cliente_manda_email_conta_e_destino():
    pedidos = []

    def helena(pedido: httpx.Request) -> httpx.Response:
        pedidos.append((pedido.url.path, pedido.headers.get("authorization"), json.loads(pedido.content)))
        return httpx.Response(200, json={"urlRedirect": "https://web.helena.run/auth/external-login?code=abc"})

    h = helena_conta.HelenaConta("pn_conta", http=httpx.AsyncClient(transport=httpx.MockTransport(helena)))
    r = await h.login_integrado(email="ana@x.com", id_conta="conta-1", destino="/chat2/sessions")
    assert r["urlRedirect"].startswith("https://web.helena.run/")
    caminho, auth, corpo = pedidos[0]
    assert caminho == "/auth/v1/login/authenticate" and auth == "Bearer pn_conta"
    assert corpo == {"email": "ana@x.com", "tenantId": "conta-1", "redirectUrl": "/chat2/sessions"}


@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_rota_abre_lista_e_conversa_e_recusa_o_que_nao_deve(ambiente, monkeypatch):
    from tests.test_gestao import _entrar

    cliente, _simulada, email_admin, banco = ambiente
    pool = banco._pool
    chamadas: list[dict] = []
    resposta = {"urlRedirect": "https://advmidia.wts.chat/auth/external-login?code=uso-unico", "expiresIn": "2099-01-01T00:00:00Z"}

    async def login_falso(self, *, email, id_conta, destino=None):
        chamadas.append({"email": email, "id_conta": id_conta, "destino": destino})
        if email == "sem-cadastro@x.com":
            raise helena_conta.ErroHelenaApi("nao_encontrado", "auth", 404)
        return dict(resposta)

    monkeypatch.setattr(helena_conta.HelenaConta, "login_integrado", login_falso)
    await _entrar(cliente, email_admin, "senha-admin-123")
    conta = str(uuid.uuid4())
    escritorio = (await cliente.post("/api/admin/escritorios", json={
        "nome": "Atendimento", "id_conta_helena": conta, "token_helena": "token-bom-123456"})).json()["escritorio"]
    h = {"x-escritorio": escritorio["id"]}
    rota = "/api/atendimento/entrar"

    # Lista de conversas, como o usuário logado, na conta do escritório.
    r = await cliente.post(rota, headers=h, json={})
    assert r.status_code == 200, r.text
    assert r.json()["url"] == resposta["urlRedirect"]
    assert chamadas[-1] == {"email": email_admin, "id_conta": conta, "destino": "/chat2/sessions"}

    # Conversa de um lead: só ela, sem o menu da Helena.
    canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado) values ($1::uuid, $2) returning id",
                                escritorio["id"], "5511" + str(uuid.uuid4().int)[:9])

    async def novo_lead(sessao):
        contato = await pool.fetchval("insert into agentesia_contatos (id_escritorio, nome, telefone_normalizado) "
                                      "values ($1::uuid, 'Maria', $2) returning id", escritorio["id"], "5511" + str(uuid.uuid4().int)[:9])
        return await pool.fetchval("insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_sessao_helena) "
                                   "values ($1::uuid, $2, $3, $4) returning id", escritorio["id"], contato, canal, sessao)

    lead = await novo_lead("sessao-abc-123")
    r = await cliente.post(rota, headers=h, json={"id_lead": str(lead)})
    assert r.status_code == 200 and chamadas[-1]["destino"] == "/chat2/sessions/sessao-abc-123/preview?interactive=true"

    # Lead sem atendimento na Helena, lead de outro escritório ou id estranho: 404, sem chamar a Helena.
    sem_sessao = await novo_lead(None)
    antes = len(chamadas)
    assert (await cliente.post(rota, headers=h, json={"id_lead": str(sem_sessao)})).status_code == 404
    assert (await cliente.post(rota, headers=h, json={"id_lead": str(uuid.uuid4())})).status_code == 404
    assert (await cliente.post(rota, headers=h, json={"id_lead": "../../x"})).status_code == 404
    assert len(chamadas) == antes

    # Link que não é da Helena: recusado (não devolve para o navegador).
    resposta["urlRedirect"] = "https://golpe.com/login"
    assert (await cliente.post(rota, headers=h, json={})).status_code == 502
    resposta["urlRedirect"] = "https://advmidia.wts.chat/auth/external-login?code=uso-unico"

    # Fica no histórico, sem o link (ele tem o código de acesso).
    linha = await pool.fetchrow(
        "select resumo, depois::text as depois from agentesia_alteracoes where id_escritorio = $1::uuid and acao = 'abriu_atendimento' "
        "order by criado_em desc limit 1", escritorio["id"])
    assert "Abriu o atendimento da Helena" in linha["resumo"] and "uso-unico" not in (linha["depois"] or "")

    # Escritório sem conta Helena: 409.
    outro = (await cliente.post("/api/admin/escritorios", json={"nome": "Sem conta"})).json()["escritorio"]
    assert (await cliente.post(rota, headers={"x-escritorio": outro["id"]}, json={})).status_code == 409

    # Sem sessão no painel: 401.
    await cliente.post("/api/sair")
    cliente.cookies.clear()
    assert (await cliente.post(rota, headers=h, json={})).status_code == 401


@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_conta_lawchat_entra_com_o_email_do_atendimento(ambiente, monkeypatch):
    """Na conta da própria LawChat, a equipe LawChat entra no atendimento com AGENTESIA_HELENA_EMAIL_ATENDIMENTO."""
    from tests.test_gestao import _entrar

    cliente, _simulada, email_admin, _banco = ambiente
    chamadas: list[dict] = []

    async def login_falso(self, *, email, id_conta, destino=None):
        chamadas.append({"email": email, "id_conta": id_conta})
        return {"urlRedirect": "https://advmidia.wts.chat/auth/external-login?code=x"}

    monkeypatch.setattr(helena_conta.HelenaConta, "login_integrado", login_falso)
    conta = str(uuid.uuid4())
    monkeypatch.setenv("AGENTESIA_HELENA_CONTA_LAWCHAT", conta)
    monkeypatch.setenv("AGENTESIA_HELENA_EMAIL_ATENDIMENTO", "atendimento@lawchat.test")
    await _entrar(cliente, email_admin, "senha-admin-123")
    lawchat = (await cliente.post("/api/admin/escritorios", json={
        "nome": "LawChat", "id_conta_helena": conta, "token_helena": "token-bom-123456"})).json()["escritorio"]
    outra = (await cliente.post("/api/admin/escritorios", json={
        "nome": "Cliente", "id_conta_helena": str(uuid.uuid4()), "token_helena": "token-bom-123456"})).json()["escritorio"]
    r = await cliente.post("/api/atendimento/entrar", headers={"x-escritorio": lawchat["id"]}, json={})
    assert r.status_code == 200 and chamadas[-1]["email"] == "atendimento@lawchat.test"
    # Em conta de cliente, nunca: vale o próprio e-mail de quem está logado.
    r = await cliente.post("/api/atendimento/entrar", headers={"x-escritorio": outra["id"]}, json={})
    assert r.status_code == 200 and chamadas[-1]["email"] == email_admin
