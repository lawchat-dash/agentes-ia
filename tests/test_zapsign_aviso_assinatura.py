"""Aviso de contrato assinado (webhook da conta ZapSign) cadastrado pelo servidor, ligado por padrão na ativação.

A ZapSign é simulada (httpx.MockTransport). A parte com banco usa AGENTESIA_TESTE_PG_URL.
"""

import json
import os
import uuid

import httpx
import pytest

from app.canal import zapsign as czapsign
from app.canal.webhook import segredo_do_escritorio
from tests.test_gestao import ambiente  # noqa: F401  (fixture do painel com a Helena simulada)

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")


async def test_cliente_manda_url_sem_senha_e_a_senha_no_cabecalho():
    pedidos = []

    def zap(pedido: httpx.Request) -> httpx.Response:
        pedidos.append((pedido.url.path, json.loads(pedido.content)))
        return httpx.Response(200, json={"id": 77})

    z = czapsign.ZapSign("tok", http=httpx.AsyncClient(transport=httpx.MockTransport(zap)))
    assert await z.criar_webhook("https://ia.exemplo.com/webhook/zapsign/abc", {"x-agentesia-segredo": "s3"}) == "77"
    caminho, corpo = pedidos[0]
    assert caminho == "/api/v1/user/company/webhook/"
    assert corpo == {"url": "https://ia.exemplo.com/webhook/zapsign/abc", "type": "",
                     "headers": [{"name": "x-agentesia-segredo", "value": "s3"}]}


_INIT_ORIGINAL = czapsign.ZapSign.__init__


def _simular_zapsign(monkeypatch, responder):
    def init(self, token, url_base=czapsign.URL_PRODUCAO, http=None):
        _INIT_ORIGINAL(self, token, url_base, httpx.AsyncClient(transport=httpx.MockTransport(responder)))

    monkeypatch.setattr(czapsign.ZapSign, "__init__", init)


@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_conectar_uma_vez_reaproveitar_e_falha_nao_grava(ambiente, monkeypatch):
    from tests.test_gestao import _entrar

    cliente, _simulada, email_admin, banco = ambiente
    pool = banco._pool
    await _entrar(cliente, email_admin, "senha-admin-123")
    escritorio = (await cliente.post("/api/admin/escritorios", json={
        "nome": "Aviso ZapSign", "id_conta_helena": str(uuid.uuid4()), "token_helena": "token-bom-" + uuid.uuid4().hex[:8]})).json()["escritorio"]
    h = {"x-escritorio": escritorio["id"]}
    rota = "/api/integracoes/zapsign/aviso-assinatura"

    # Sem ZapSign conectada: 409.
    assert (await cliente.post(rota, headers=h, json={})).status_code == 409

    segredo = await pool.fetchval("select vault.create_secret($1, 'teste')", "token-zapsign-" + uuid.uuid4().hex[:8])
    await pool.execute(
        "insert into agentesia_integracoes (id_escritorio, tipo, id_segredo_vault, situacao, config) values ($1::uuid, 'zapsign', $2, 'ok', $3::jsonb)",
        escritorio["id"], segredo, json.dumps({"ambiente": "producao"}))

    # A ZapSign fora do ar: 502 e nada gravado (o Início continua avisando).
    _simular_zapsign(monkeypatch, lambda p: httpx.Response(403, text="forbidden"))
    assert (await cliente.post(rota, headers=h, json={})).status_code == 502
    config = (await cliente.get("/api/integracoes", headers=h)).json()["integracoes"]["zapsign"]["config"]
    assert not config.get("webhook_id")

    # Agora aceita: cadastra uma vez, com a senha do escritório em cabeçalho.
    cadastros = []

    def zap(pedido: httpx.Request) -> httpx.Response:
        cadastros.append(json.loads(pedido.content))
        return httpx.Response(200, json={"id": 4321})

    _simular_zapsign(monkeypatch, zap)
    r = await cliente.post(rota, headers=h, json={})
    assert r.status_code == 200, r.text
    assert r.json() == {"webhook_id": "4321", "ja_existia": False}
    assert cadastros[0]["url"] == f"https://ia.exemplo.com/webhook/zapsign/{escritorio['id']}"     # sem ?segredo=
    assert cadastros[0]["headers"] == [{"name": "x-agentesia-segredo", "value": segredo_do_escritorio(escritorio["id"], "zapsign")}]
    config = (await cliente.get("/api/integracoes", headers=h)).json()["integracoes"]["zapsign"]["config"]
    assert config["webhook_id"] == "4321" and config.get("webhook_em")

    # Segunda vez (outro produto ativando): reaproveita, não cadastra de novo.
    r2 = await cliente.post(rota, headers=h, json={})
    assert r2.json() == {"webhook_id": "4321", "ja_existia": True} and len(cadastros) == 1

    # O Início recebe a integração com o webhook_id (o painel some com o alerta "Conectar aviso").
    inicio = (await cliente.get("/api/inicio", headers=h)).json()
    assert inicio["integracoes"]["zapsign"]["config"]["webhook_id"] == "4321"

    # Fica no histórico.
    resumo = await pool.fetchval(
        "select resumo from agentesia_alteracoes where id_escritorio = $1::uuid and acao = 'conectou' order by criado_em desc limit 1",
        escritorio["id"])
    assert "Aviso de assinatura" in resumo
