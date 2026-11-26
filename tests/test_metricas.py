"""Números da tela Início (/api/inicio/metricas) contra um Postgres local.

Só roda com AGENTESIA_TESTE_PG_URL (ver tests/test_postgres.py). A Helena é simulada como em test_gestao.
"""

import os
import tempfile
import uuid

import httpx
import pytest
from fastapi import FastAPI

from app.banco.postgres import RepositorioPostgres
from app.canal import helena_conta
from app.config import Configuracao
from app.gestao import seguranca
from app.gestao.metricas import api as api_metricas
from app.gestao.metricas import uf_do_telefone, variacao
from app.gestao.repositorio import RepositorioGestao
from app.gestao.rotas import api
from tests.test_gestao import HelenaSimulada, _entrar

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")


def test_uf_pelo_ddd():
    assert uf_do_telefone("5511912345678") == "sp"
    assert uf_do_telefone("5531988887777") == "mg"
    assert uf_do_telefone("71988887777") == "ba"
    assert uf_do_telefone("+55 (61) 3333-4444") == "df"
    assert uf_do_telefone("5520912345678") is None          # DDD que não existe
    assert uf_do_telefone(None) is None and uf_do_telefone("123") is None


def test_variacao():
    assert variacao(12, 10) == 20 and variacao(5, 10) == -50
    assert variacao(3, 0) is None


@pytest.fixture
async def ambiente(monkeypatch):
    if not URL:
        pytest.skip("sem AGENTESIA_TESTE_PG_URL")
    simulada = HelenaSimulada()
    original = helena_conta.HelenaConta.__init__

    def init_com_simulacao(self, token, url_base="https://api.helena.run", http=None):
        original(self, token, url_base, httpx.AsyncClient(transport=httpx.MockTransport(simulada)))

    monkeypatch.setattr(helena_conta.HelenaConta, "__init__", init_com_simulacao)
    monkeypatch.setenv("AGENTESIA_URL_PUBLICA", "https://ia.exemplo.com")
    monkeypatch.setenv("AGENTESIA_WEBHOOK_SEGREDO", "segredo-do-webhook")
    monkeypatch.setenv("AGENTESIA_PASTA_MIDIA", tempfile.mkdtemp(prefix="midia-teste-"))

    banco = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    app = FastAPI()
    app.include_router(api)
    app.include_router(api_metricas)
    app.state.gestao = RepositorioGestao(banco._pool)
    app.state.assinador = seguranca.Assinador("segredo-de-teste")
    app.state.cfg = Configuracao(banco_url=URL, helena_url="https://api.helena.run", modelo_padrao="falso", modelo_falso=True,
                                  espera_minima_s=0, espera_maxima_s=0, espera_padrao_s=0, segundos_por_letra=0, max_reprocessos=2)
    app.state.http_ativacao = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda pedido: httpx.Response(200, json={"ok": True, "feito": "teste"})))

    email_admin = f"admin-{uuid.uuid4().hex[:6]}@lawchat.com"
    await banco._pool.execute(
        "insert into agentesia_usuarios (email, nome, senha_hash, papel) values ($1, 'Equipe', $2, 'admin_lawchat')",
        email_admin, seguranca.gerar_hash("senha-admin-123"))
    cliente = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://painel")
    try:
        yield cliente, email_admin, banco
    finally:
        await cliente.aclose()
        await banco.fechar()


async def test_metricas_do_inicio(ambiente):
    cliente, email_admin, banco = ambiente
    pool = banco._pool
    await _entrar(cliente, email_admin, "senha-admin-123")
    escritorio = (await cliente.post("/api/admin/escritorios", json={
        "nome": "Métricas Ltda", "id_conta_helena": str(uuid.uuid4()), "token_helena": "token-bom-123456"})).json()["escritorio"]
    h = {"x-escritorio": escritorio["id"]}

    # Sem escritório escolhido a rota pede um; escritório vazio responde com zeros.
    assert (await cliente.get("/api/inicio/metricas")).status_code == 400
    vazio = (await cliente.get("/api/inicio/metricas?dias=7", headers=h)).json()
    assert vazio["dias"] == 7 and len(vazio["serie"]) == 7
    assert vazio["conversas_hoje"] == 0 and vazio["mensagens"] == 0 and vazio["tokens"] == 0
    assert vazio["agentes_total"] == 0 and vazio["atividades"] == [] and vazio["uf"] == {"leads": {}, "contratos": {}}
    assert vazio["consumo"]["gasto_usd"] == 0 and vazio["consumo"]["limite_usd"] is None

    canal = next(c for c in (await cliente.get("/api/integracoes", headers=h)).json()["canais"] if c["tipo"] != "oficial")
    agente = (await cliente.post("/api/agentes", headers=h, json={"nome": "Júlia", "id_canal": canal["id"]})).json()
    await pool.execute("update agentesia_agentes set situacao = 'ativo' where id = $1::uuid", agente["id"])

    async def lead(telefone, *, estado="ativo", dias_atras=0, assinado=False, nome="Contato"):
        contato = await pool.fetchval(
            "insert into agentesia_contatos (id_escritorio, nome, telefone_normalizado) values ($1::uuid, $2, $3) returning id",
            escritorio["id"], nome, telefone)
        id_lead = await pool.fetchval(
            """insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_agente, estado, criado_em)
               values ($1::uuid, $2, $3::uuid, $4::uuid, $5, now() - make_interval(days => $6)) returning id""",
            escritorio["id"], contato, canal["id"], agente["id"], estado, dias_atras)
        if assinado:
            await pool.execute(
                "insert into agentesia_contratos (id_escritorio, id_lead, versao, situacao, dados, dados_hash, assinado_em) values ($1::uuid, $2, 1, 'assinado', '{}', 'h', now())",
                escritorio["id"], id_lead)
        return id_lead

    sp = await lead("5511" + str(uuid.uuid4().int)[:9], nome="Ana")
    await lead("5531" + str(uuid.uuid4().int)[:9], assinado=True, nome="Bruno")
    await lead("5531" + str(uuid.uuid4().int)[:9], estado="pausado", nome="Carla")
    await lead("5571" + str(uuid.uuid4().int)[:9], estado="encerrado", dias_atras=3, nome="Davi")
    await lead("5521" + str(uuid.uuid4().int)[:9], dias_atras=40, nome="Eva")      # fora do período

    # Mensagens: o lead fala, a IA responde 30 s depois.
    await pool.execute(
        """insert into agentesia_mensagens (id_escritorio, id_lead, autor, texto, enviada_em) values
             ($1::uuid, $2, 'lead', 'oi', now() - interval '60 seconds'),
             ($1::uuid, $2, 'ia', 'olá', now() - interval '30 seconds')""", escritorio["id"], sp)
    await pool.execute(
        "insert into agentesia_chamadas_ia (id_escritorio, papel, modelo, tokens_entrada, tokens_saida, custo_usd, sucesso) values ($1::uuid, 'etapa', 'gpt-4.1', 1000, 200, 0.5, true)",
        escritorio["id"])
    # Follow-up: um pendente e um enviado que o lead respondeu depois.
    await pool.execute(
        """insert into agentesia_followups (id_escritorio, id_lead, id_agente, passo, base, agendado_para, situacao, enviado_em) values
             ($1::uuid, $2, $3::uuid, 0, now(), now() + interval '1 day', 'pendente', null)""", escritorio["id"], sp, agente["id"])
    outro = await lead("5511" + str(uuid.uuid4().int)[:9], estado="ativo", dias_atras=2, nome="Fábio")
    await pool.execute(
        """insert into agentesia_followups (id_escritorio, id_lead, id_agente, passo, base, agendado_para, situacao, enviado_em) values
             ($1::uuid, $2, $3::uuid, 0, now() - interval '2 hours', now() - interval '2 hours', 'enviado', now() - interval '2 hours')""",
        escritorio["id"], outro, agente["id"])
    await pool.execute("insert into agentesia_mensagens (id_escritorio, id_lead, autor, texto, enviada_em) values ($1::uuid, $2, 'lead', 'voltei', now())",
                       escritorio["id"], outro)
    await pool.execute(
        "update agentesia_escritorios set config = jsonb_set(coalesce(config, '{}'::jsonb), '{limite_consumo}', '{\"mensal_usd\": 10}'::jsonb) where id = $1::uuid",
        escritorio["id"])

    m = (await cliente.get("/api/inicio/metricas?dias=30", headers=h)).json()
    assert len(m["serie"]) == 30 and m["serie"][-1]["conv"] == 3 and sum(d["conv"] for d in m["serie"]) == 5
    assert m["conversas_hoje"] == 3 and m["conversas_periodo"] == 5
    assert m["mensagens"] == 3 and m["tokens"] == 1200 and sum(d["tokens"] for d in m["serie"]) == 1200
    assert m["agentes_ativos"] == 1 and m["agentes_total"] == 1
    assert m["ranking_agentes"][0]["nome"] == "Júlia" and m["ranking_agentes"][0]["conversas"] == 5
    assert m["ranking_agentes"][0]["assinados"] == 1
    assert {e["estado"]: e["total"] for e in m["estados"]} == {"ativo": 3, "pausado": 1, "encerrado": 1}
    assert m["resposta_media_s"] == 30
    assert m["uf"]["leads"] == {"sp": 2, "mg": 2, "ba": 1} and m["uf"]["contratos"] == {"mg": 1}
    assert m["followup"]["pendentes"] == 1 and m["followup"]["enviados"] == 1 and m["followup"]["taxa_resposta"] == 100
    tipos = {a["nome"]: a["tipo"] for a in m["atividades"]}
    assert tipos["Bruno"] == "contrato_assinado" and tipos["Carla"] == "pausada" and tipos["Davi"] == "encerrada"
    assert tipos["Ana"] == "nova" and tipos["Fábio"] == "em_andamento"
    assert m["consumo"]["gasto_usd"] == 0.5 and m["consumo"]["limite_usd"] == 10 and m["consumo"]["percentual"] == 5.0
    assert not m["consumo"]["bloqueado"]

    # Atendente vê os números do escritório, mas não o consumo em dólar.
    atendente = (await cliente.get("/api/inicio/metricas", headers={**h, "x-visao": "atendente"})).json()
    assert atendente["consumo"] is None and atendente["conversas_hoje"] == 3
