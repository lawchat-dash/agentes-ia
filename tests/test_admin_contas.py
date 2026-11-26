"""Tela Contas do superadmin (/admin/escritorios), igual ao painel antigo: "Sincronizar com LawChat" (todas as empresas
do token de parceiro viram conta), sync_one, "Criar Agente: Habilitar" (integração inicial) e só admin acessa.

Só roda com AGENTESIA_TESTE_PG_URL (banco local: node db/testes/servidor_local.mjs). A Helena é falsa
(httpx.MockTransport, a mesma de tests/test_conta_helena.py): nenhuma chamada sai da máquina.
"""

import os
import uuid

import httpx
import pytest
from fastapi import FastAPI

from app.banco.postgres import RepositorioPostgres
from app.canal import helena_conta
from app.config import Configuracao
from app.gestao import seguranca
from app.gestao.repositorio import RepositorioGestao
from app.gestao.rotas import api, entrada
from app.gestao.rotas_conta import api as api_conta
from tests.test_conta_helena import HelenaFalsa

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
pytestmark = pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")


@pytest.fixture
async def ambiente(monkeypatch):
    falsa = HelenaFalsa()
    original = helena_conta.HelenaConta.__init__

    def init_com_falsa(self, token, url_base="https://api.helena.run", http=None):
        original(self, token, url_base, httpx.AsyncClient(transport=httpx.MockTransport(falsa)))

    monkeypatch.setattr(helena_conta.HelenaConta, "__init__", init_com_falsa)
    monkeypatch.setenv("AGENTESIA_URL_PUBLICA", "https://ia.exemplo.com")
    monkeypatch.setenv("AGENTESIA_WEBHOOK_SEGREDO", "segredo-do-webhook")
    monkeypatch.setenv("OPENAI_API_KEY", "chave-de-teste")
    monkeypatch.setenv("AGENTESIA_HELENA_TOKEN_PARCEIRO", "parceiro-de-teste")
    monkeypatch.delenv("AGENTESIA_HELENA_CONTA_LAWCHAT", raising=False)

    banco = await RepositorioPostgres.conectar(URL, max_conexoes=1)  # o servidor de teste só aceita uma
    app = FastAPI()
    app.include_router(api)
    app.include_router(api_conta)
    app.include_router(entrada)
    app.state.gestao = RepositorioGestao(banco._pool)
    app.state.assinador = seguranca.Assinador("segredo-de-teste")
    app.state.cfg = Configuracao(banco_url=URL, helena_url="https://api.helena.run", modelo_padrao="falso",
                                 modelo_falso=True, espera_minima_s=0, espera_maxima_s=0, espera_padrao_s=0,
                                 segundos_por_letra=0, max_reprocessos=2)
    app.state.http_ativacao = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda pedido: httpx.Response(200, json={"ok": True})))
    email = f"admin-{uuid.uuid4().hex[:6]}@lawchat.com"
    await banco._pool.execute(
        "insert into agentesia_usuarios (email, nome, senha_hash, papel) values ($1, 'Equipe', $2, 'admin_lawchat')",
        email, seguranca.gerar_hash("senha-admin-123"))
    cliente = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://painel")
    assert (await cliente.post("/api/entrar", json={"email": email, "senha": "senha-admin-123"})).status_code == 200
    try:
        yield cliente, falsa, banco
    finally:
        await cliente.aclose()
        await banco.fechar()


def _empresa(nome: str, **extra) -> dict:
    return {"id": str(uuid.uuid4()), "name": nome, "active": True, "legalName": f"{nome} Ltda", "documentId": "11222333000181",
            "documentType": "CNPJ", "email": f"contato-{uuid.uuid4().hex[:4]}@empresa.test", "phoneNumber": "5511912345678",
            "address": {"zipcode": "01310100", "address1": "Av. Paulista", "number": "1000", "city": "São Paulo", "state": "sp"},
            **extra}


async def _sincronizar(cliente) -> dict:
    resposta = await cliente.post("/api/admin/escritorios/sincronizar-lawchat")
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


async def _linha(cliente, id_conta: str) -> dict:
    lista = (await cliente.get("/api/admin/escritorios")).json()
    return next(e for e in lista if e["id_conta_helena"] == id_conta)


# ------------------------------------------------------------------------------------------- Sincronizar com LawChat
async def test_sincronizar_cria_e_atualiza_sem_duplicar(ambiente, monkeypatch):
    cliente, falsa, banco = ambiente
    a = _empresa("Alfa Advocacia", pictureUrl="https://cdn.helena.run/empresa/alfa.png")
    b = _empresa("Beta Previdência", documentId="12345678909", documentType="CPF", pictureUrl="http://inseguro.test/b.png")
    admin = _empresa("LawChat (admin)")
    for e in (a, b, admin):
        falsa.empresas[e["id"]] = e
    falsa.empresas["sem-id"] = {"id": "nao-e-uuid", "name": "Quebrada"}
    monkeypatch.setenv("AGENTESIA_HELENA_CONTA_LAWCHAT", admin["id"].upper())

    primeira = await _sincronizar(cliente)
    assert (primeira["total"], primeira["criadas"], primeira["atualizadas"], primeira["com_erro"]) == (4, 3, 0, 1)
    a["name"] = "Alfa Advocacia Nova"
    segunda = await _sincronizar(cliente)
    assert (segunda["criadas"], segunda["atualizadas"], segunda["com_erro"]) == (0, 3, 1)
    for e in (a, b, admin):
        assert await banco._pool.fetchval(
            "select count(*) from agentesia_escritorios where id_conta_helena = $1::uuid", e["id"]) == 1

    linha_a = await _linha(cliente, a["id"])
    assert linha_a["nome"] == "Alfa Advocacia Nova" and linha_a["webhook"] == "synced" and linha_a["sincronizado_em"]
    conta = linha_a["conta_helena"]
    assert conta["documento_formatado"] == "11.222.333/0001-81" and conta["tipo_pessoa"] == "PJ"
    assert conta["razao_social"] == "Alfa Advocacia Ltda" and conta["administrador"] == "Alfa Advocacia Ltda"
    assert conta["telefone"] == "5511912345678" and conta["email_contato"] == a["email"]
    assert conta["endereco"]["zipcode"] == "01310-100" and conta["endereco"]["state"] == "SP"
    assert linha_a["agente_habilitado"] is False and linha_a["conta_lawchat"] is False
    assert conta["foto"] == "https://cdn.helena.run/empresa/alfa.png"
    linha_b = await _linha(cliente, b["id"])
    assert linha_b["conta_helena"]["documento_formatado"] == "123.456.789-09" and linha_b["conta_helena"]["tipo_pessoa"] == "PF"
    assert linha_b["conta_helena"]["foto"] is None                                      # só https vira foto

    # A conta da própria LawChat entra marcada e vem primeiro. Ela pode receber o agente (é onde a equipe testa a IA),
    # pelo mesmo "Criar Agente" das outras contas.
    lista = (await cliente.get("/api/admin/escritorios")).json()
    assert lista[0]["id_conta_helena"] == admin["id"] and lista[0]["conta_lawchat"] is True

    registro = await banco._pool.fetchrow(
        """select resumo, situacao, erro from agentesia_alteracoes where acao = 'sincronizou_contas'
           order by criado_em desc limit 1""")
    assert registro["resumo"] == "Sincronizar com LawChat: 0 criadas, 3 atualizadas, 1 com erro"
    assert registro["situacao"] == "erro" and "Quebrada" in registro["erro"]


async def test_sincronizar_sem_token_de_parceiro_avisa_e_registra(ambiente, monkeypatch):
    cliente, _falsa, banco = ambiente
    monkeypatch.delenv("AGENTESIA_HELENA_TOKEN_PARCEIRO")
    resposta = await cliente.post("/api/admin/escritorios/sincronizar-lawchat")
    assert resposta.status_code == 409 and "AGENTESIA_HELENA_TOKEN_PARCEIRO" in resposta.json()["detail"]
    assert await banco._pool.fetchval(
        """select situacao from agentesia_alteracoes where acao = 'sincronizou_contas' order by criado_em desc limit 1""") == "erro"


# ------------------------------------------------------------------------------------------- sync_one
async def test_sync_one_atualiza_so_esta_conta(ambiente):
    cliente, falsa, banco = ambiente
    a, b = _empresa("Gama"), _empresa("Delta")
    falsa.empresas.update({a["id"]: a, b["id"]: b})
    await _sincronizar(cliente)
    linha_a, linha_b = await _linha(cliente, a["id"]), await _linha(cliente, b["id"])

    a.update(name="Gama Renomeada", legalName="Gama Sociedade de Advogados", documentId="99888777000166")
    b["name"] = "Delta mudou mas não sincronizou"
    feito = await cliente.post(f"/api/admin/escritorios/{linha_a['id']}/sincronizar-lawchat")
    assert feito.status_code == 200, feito.text
    linha_a = await _linha(cliente, a["id"])
    assert linha_a["nome"] == "Gama Renomeada" and linha_a["conta_helena"]["documento_formatado"] == "99.888.777/0001-66"
    assert (await _linha(cliente, b["id"]))["nome"] == "Delta"

    # Sumiu do token de parceiro: 404, Webhook vira error e o erro fica registrado.
    del falsa.empresas[a["id"]]
    sumiu = await cliente.post(f"/api/admin/escritorios/{linha_a['id']}/sincronizar-lawchat")
    assert sumiu.status_code == 404
    assert (await _linha(cliente, a["id"]))["webhook"] == "error"
    assert await banco._pool.fetchval(
        """select situacao from agentesia_alteracoes where acao = 'sincronizou_conta' and id_escritorio = $1::uuid
           order by criado_em desc limit 1""", linha_a["id"]) == "erro"
    assert linha_b["id"] != linha_a["id"]


# ------------------------------------------------------------------------------------------- Criar Agente
async def test_habilitar_agente_gera_o_token_e_marca_como_habilitado(ambiente):
    cliente, falsa, banco = ambiente
    a = _empresa("Épsilon")
    falsa.empresas[a["id"]] = a
    await _sincronizar(cliente)
    linha = await _linha(cliente, a["id"])
    assert linha["agente_habilitado"] is False

    resposta = await cliente.post(f"/api/admin/escritorios/{linha['id']}/habilitar-agente", json={})
    assert resposta.status_code == 200, resposta.text
    feito = resposta.json()
    situacao = {p["codigo"]: p["situacao"] for p in feito["passos"]}
    assert feito["habilitado"] is True
    assert situacao == {"token": "feito", "webhook": "feito", "etiquetas": "feito", "canais": "feito"}
    assert falsa.tokens_criados == [{"name": "IA LawChat"}]
    # Equipe "🤖 Comercial IA" só se marcado: por padrão, não.
    assert ("POST", "/core/v1/department") not in falsa.pedidos
    linha = await _linha(cliente, a["id"])
    assert linha["agente_habilitado"] is True and linha["helena"] == "ok"
    assert await banco._pool.fetchval(
        "select count(*) from agentesia_canais where id_escritorio = $1::uuid", linha["id"]) == 2
    # O token não fica em tabela nossa: só o final.
    assert await banco._pool.fetchval(
        "select count(*) from agentesia_integracoes where config::text like '%token-novo%'") == 0
    registro = await banco._pool.fetchrow(
        """select resumo, situacao from agentesia_alteracoes where acao = 'habilitou_agente' and id_escritorio = $1::uuid
           order by criado_em desc limit 1""", linha["id"])
    assert registro["situacao"] == "ok" and "habilitado" in registro["resumo"]

    # Outra conta, com a equipe marcada: cria a equipe padrão.
    b = _empresa("Zeta")
    falsa.empresas[b["id"]] = b
    await _sincronizar(cliente)
    linha_b = await _linha(cliente, b["id"])
    com_equipe = (await cliente.post(f"/api/admin/escritorios/{linha_b['id']}/habilitar-agente",
                                     json={"criar_equipe_ia": True})).json()
    assert {p["codigo"]: p["situacao"] for p in com_equipe["passos"]}["equipe"] == "feito"
    assert ("POST", "/core/v1/department") in falsa.pedidos


async def test_nao_habilita_sem_token_de_parceiro(ambiente, monkeypatch):
    cliente, falsa, banco = ambiente
    a = _empresa("Eta")
    falsa.empresas[a["id"]] = a
    await _sincronizar(cliente)
    linha = await _linha(cliente, a["id"])
    monkeypatch.delenv("AGENTESIA_HELENA_TOKEN_PARCEIRO")
    resposta = await cliente.post(f"/api/admin/escritorios/{linha['id']}/habilitar-agente", json={})
    assert resposta.status_code == 409 and "token de parceiro" in resposta.json()["detail"]
    assert falsa.tokens_criados == []
    assert (await _linha(cliente, a["id"]))["agente_habilitado"] is False
    assert await banco._pool.fetchval(
        """select situacao from agentesia_alteracoes where acao = 'habilitou_agente' and id_escritorio = $1::uuid
           order by criado_em desc limit 1""", linha["id"]) == "erro"


# ------------------------------------------------------------------------------------------- permissão
async def test_so_admin_acessa_a_tela_contas(ambiente):
    cliente, falsa, banco = ambiente
    a = _empresa("Teta")
    falsa.empresas[a["id"]] = a
    await _sincronizar(cliente)
    linha = await _linha(cliente, a["id"])
    email = f"gestor-{uuid.uuid4().hex[:6]}@escritorio.com"
    await banco._pool.execute(
        """insert into agentesia_usuarios (email, nome, senha_hash, papel, id_escritorio)
           values ($1, 'Gestor', $2, 'gestor', $3::uuid)""", email, seguranca.gerar_hash("senha-gestor-123"), linha["id"])
    await cliente.post("/api/sair")
    assert (await cliente.post("/api/entrar", json={"email": email, "senha": "senha-gestor-123"})).status_code == 200
    assert (await cliente.get("/api/admin/escritorios")).status_code == 403
    assert (await cliente.post("/api/admin/escritorios/sincronizar-lawchat")).status_code == 403
    assert (await cliente.post(f"/api/admin/escritorios/{linha['id']}/sincronizar-lawchat")).status_code == 403
    assert (await cliente.post(f"/api/admin/escritorios/{linha['id']}/habilitar-agente", json={})).status_code == 403
    assert falsa.tokens_criados == []
