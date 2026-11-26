"""Painel padrão do CRM pela API interna da Helena (impersonate): chamadas iguais ao n8n e cada trava.

Só roda com AGENTESIA_TESTE_PG_URL (banco local). A API interna é falsa (httpx.MockTransport): nada sai da máquina.
"""

import asyncio
import json
import os
import uuid

import httpx
import pytest
from fastapi import FastAPI

from app.banco.postgres import RepositorioPostgres
from app.config import Configuracao
from app.gestao import painel_crm_padrao, seguranca
from app.gestao.repositorio import RepositorioGestao
from app.gestao.rotas import COOKIE, api
from app.gestao.rotas_painel_crm import api as api_painel_crm

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
pytestmark = pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")

INTERNA = "https://interna.helena.teste"
ORIGEM = "https://parceiro.helena.teste"
ADMIN_EMAIL = "ia@lawchat.teste"
TOKEN_LOGIN = "TOKENLOGIN" + "a" * 40
TOKEN_CONTA = "TOKENCONTA" + "b" * 40
CAB = {"x-lawchat-acao": "painel-crm"}

# O corpo combinado com o dono (cópia do n8n), para conferir a constante byte a byte.
CORPO_N8N = '{"available":false,"title":"🤖 CRM COMERCIAL IA","key":"CCI","description":"A IA analisa o histórico de interações de cada lead — mensagens, respostas, qualificação e avanços nas etapas e posiciona automaticamente o contato na etapa correta do funil","scope":"COMPANY","adminUserIds":["<userId>"],"departmentIds":null,"customType":"UNDEFINED","type":"SALE","autoLossDays":60,"steps":[{"title":"📞SDR","type":0,"primaryColor":"rgb(102, 204, 255)","secondaryColor":"white","position":1,"isInitial":true,"isFinal":false},{"title":"🛒 Comercial","type":2,"primaryColor":"rgb(120, 75, 209)","secondaryColor":"white","position":2,"isInitial":false,"isFinal":false},{"title":"📄 Contrato em Elaboração","type":2,"primaryColor":"rgb(253, 171, 61)","secondaryColor":"#4F4F4F","position":3,"isInitial":false,"isFinal":false},{"title":"✍️ Aguardando Assinatura","type":2,"position":4,"primaryColor":"rgb(255, 203, 0)","secondaryColor":"#4F4F4F","isInitial":false,"isFinal":false},{"title":"✅ Contrato Assinado","type":2,"position":5,"primaryColor":"rgb(0, 200, 117)","secondaryColor":"white","isInitial":false,"isFinal":false},{"title":"❌ Desqualificado","type":2,"position":6,"primaryColor":"rgb(226, 68, 92)","secondaryColor":"white","isInitial":false,"isFinal":false}],"details":{"viewMode":"ALL","allowRestrictedAgent":false,"celebrateOnWin":true,"celebrationSound":true}}'


class InternaFalsa:
    def __init__(self, id_conta: str):
        self.id_conta = id_conta
        self.pedidos: list[httpx.Request] = []
        self.empresas = [{"id": "outra-" + uuid.uuid4().hex[:6], "name": "Outra"}, {"id": id_conta, "name": "Silva Adv"}]
        self.usuarios = [{"id": "ag-1", "userId": "usr-admin-1", "name": "IA LawChat", "email": ADMIN_EMAIL},
                         {"id": "ag-2", "userId": "usr-2", "name": "Dra. Ana", "email": "ana@escritorio.teste"}]
        self.etapas = 6
        self.timeout_no_painel = False
        self.atraso_login = 0.0

    async def __call__(self, pedido: httpx.Request) -> httpx.Response:
        self.pedidos.append(pedido)
        caminho = pedido.url.path
        if caminho == "/auth/v2/login/send-otp":
            return httpx.Response(200, json={"ok": True})
        if caminho == "/auth/v2/login/authenticate":
            if self.atraso_login:
                await asyncio.sleep(self.atraso_login)
            if json.loads(pedido.content)["password"] != "123456":
                return httpx.Response(401, json={"error": "invalid_grant", "token": TOKEN_LOGIN})
            return httpx.Response(200, json={"accessToken": TOKEN_LOGIN})
        if caminho == "/core/v5/company":
            return httpx.Response(200, json={"items": self.empresas})
        if caminho == "/core/v1/agent":
            return httpx.Response(200, json={"items": self.usuarios})
        if caminho == "/auth/v2/login/authenticate/impersonate":
            return httpx.Response(200, json={"accessToken": TOKEN_CONTA})
        if caminho == "/crm/v1/panel":
            if self.timeout_no_painel:
                raise httpx.ReadTimeout("timeout", request=pedido)
            corpo = json.loads(pedido.content)
            return httpx.Response(200, json={"id": "painel-novo", "title": corpo["title"],
                                             "steps": [{"id": f"etapa-{i}", "title": s["title"]}
                                                       for i, s in enumerate(corpo["steps"][: self.etapas])]})
        return httpx.Response(404)

    def caminhos(self) -> list[str]:
        return [p.url.path for p in self.pedidos]


@pytest.fixture
async def ambiente(monkeypatch):
    for nome, valor in {"AGENTESIA_PAINEL_CRM_LIGADO": "1", "AGENTESIA_HELENA_INTERNA_URL": INTERNA,
                        "AGENTESIA_HELENA_PARCEIRO_EMAIL": "parceiro@lawchat.teste",
                        "AGENTESIA_HELENA_PARCEIRO_ID": "parceiro-123", "AGENTESIA_HELENA_DEVICE_ID": "dispositivo-9",
                        "AGENTESIA_HELENA_PARCEIRO_ORIGEM": ORIGEM, "AGENTESIA_HELENA_ADMIN_EMAIL": ADMIN_EMAIL}.items():
        monkeypatch.setenv(nome, valor)
    banco = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    id_conta = str(uuid.uuid4())
    id_escritorio = str(await banco._pool.fetchval(
        "insert into agentesia_escritorios (nome, id_conta_helena) values ('Silva Adv', $1::uuid) returning id", id_conta))
    falsa = InternaFalsa(id_conta)
    app = FastAPI()
    app.include_router(api)
    app.include_router(api_painel_crm)
    app.state.gestao = RepositorioGestao(banco._pool)
    app.state.assinador = seguranca.Assinador("segredo-de-teste")
    app.state.cfg = Configuracao(banco_url=URL, helena_url="https://api.helena.run", modelo_padrao="falso",
                                 modelo_falso=True, espera_minima_s=0, espera_maxima_s=0, espera_padrao_s=0,
                                 segundos_por_letra=0, max_reprocessos=2)
    app.state.http_painel_crm = httpx.AsyncClient(transport=httpx.MockTransport(falsa))
    email = f"admin-{uuid.uuid4().hex[:6]}@lawchat.com"
    await banco._pool.execute(
        "insert into agentesia_usuarios (email, nome, senha_hash, papel) values ($1, 'Equipe', $2, 'admin_lawchat')",
        email, seguranca.gerar_hash("senha-admin-123"))
    cliente = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://painel")
    assert (await cliente.post("/api/entrar", json={"email": email, "senha": "senha-admin-123"})).status_code == 200
    try:
        yield cliente, falsa, banco, id_escritorio, id_conta, app
    finally:
        await cliente.aclose()
        await banco.fechar()


def _base(id_escritorio):
    return f"/api/admin/escritorios/{id_escritorio}/painel-crm"


async def _simular(cliente, base):
    assert (await cliente.post(f"{base}/codigo", headers=CAB)).status_code == 200
    return (await cliente.post(f"{base}?simular=true", json={"codigo": "123456"}, headers=CAB)).json()


def test_corpo_do_painel_e_o_do_n8n_byte_a_byte():
    assert painel_crm_padrao.CORPO_PAINEL_PADRAO.encode("utf-8") == CORPO_N8N.encode("utf-8")
    assert painel_crm_padrao.corpo_para("usr-1") == CORPO_N8N.replace('"<userId>"', '"usr-1"').encode("utf-8")


async def test_criacao_completa_com_as_chamadas_do_n8n(ambiente):
    cliente, falsa, banco, id_escritorio, id_conta, _app = ambiente
    base = _base(id_escritorio)
    # Simulação primeiro: login, empresas e usuários; nada de impersonate nem POST do painel.
    sim = await _simular(cliente, base)
    assert sim["ok"] and sim["simulacao"] and sim["empresa"] == {"id": id_conta, "nome": "Silva Adv"}
    assert sim["usuario"]["id"] == "usr-admin-1" and sim["painel"]["etapas"][0] == "📞SDR"
    assert falsa.caminhos() == ["/auth/v2/login/send-otp", "/auth/v2/login/authenticate", "/core/v5/company", "/core/v1/agent"]

    falsa.pedidos.clear()
    assert (await cliente.post(f"{base}/codigo", headers=CAB)).status_code == 200
    feito = await cliente.post(base, json={"codigo": "123456"}, headers=CAB)
    resultado = feito.json()
    assert resultado["ok"] and resultado["estado"] == "criado" and resultado["id_painel"] == "painel-novo"
    assert resultado["etapas_por_tipo"] == {"SDR": "etapa-0", "COMERCIAL": "etapa-1", "CONTRATO": "etapa-2",
                                            "AGUARDANDO_ASSINATURA": "etapa-3", "CONTRATO_ASSINADO": "etapa-4",
                                            "DESQUALIFICADO": "etapa-5"}
    p = {r.url.path: r for r in falsa.pedidos}
    assert falsa.caminhos() == ["/auth/v2/login/send-otp", "/auth/v2/login/authenticate", "/core/v5/company",
                                "/core/v1/agent", "/auth/v2/login/authenticate/impersonate", "/crm/v1/panel"]
    # send-otp e authenticate: cabeçalhos e corpo.
    otp = p["/auth/v2/login/send-otp"]
    assert otp.method == "POST" and str(otp.url) == f"{INTERNA}/auth/v2/login/send-otp"
    assert otp.headers["content-type"] == "application/json" and otp.headers["accept"] == "application/json"
    assert otp.headers["origin"] == ORIGEM
    assert json.loads(otp.content) == {"email": "parceiro@lawchat.teste", "type": "EMAIL", "partnerId": "parceiro-123"}
    login = p["/auth/v2/login/authenticate"]
    assert login.headers["origin"] == ORIGEM and login.headers["content-type"] == "application/json"
    assert json.loads(login.content) == {"email": "parceiro@lawchat.teste", "grantType": "OTP",
                                         "internalDeviceId": "dispositivo-9", "partnerId": "parceiro-123", "password": "123456"}
    # empresas e usuários: GET com o token do login.
    emp = p["/core/v5/company"]
    assert emp.method == "GET" and emp.url.query.decode() == "refPartnerId=parceiro-123&pageSize=50&orderBy=name&includeDetails=PICTUREURL"
    assert emp.headers["authorization"] == f"Bearer {TOKEN_LOGIN}" and emp.headers["origin"] == ORIGEM
    assert emp.headers["referer"] == ORIGEM + "/"
    usu = p["/core/v1/agent"]
    assert usu.url.query.decode() == f"companyId={id_conta}&pageSize=1000" and usu.headers["authorization"] == f"Bearer {TOKEN_LOGIN}"
    # impersonate: token do login, userId achado e tenantId = companyId do escritório.
    imp = p["/auth/v2/login/authenticate/impersonate"]
    assert imp.headers["authorization"] == f"Bearer {TOKEN_LOGIN}" and imp.headers["origin"] == ORIGEM
    assert json.loads(imp.content) == {"userId": "usr-admin-1", "tenantId": id_conta}
    # painel: token do impersonate, cabeçalhos e corpo byte a byte.
    pan = p["/crm/v1/panel"]
    assert pan.method == "POST" and pan.headers["authorization"] == f"Bearer {TOKEN_CONTA}"
    assert pan.headers["accept"] == "application/json, text/plain, */*" and pan.headers["referer"] == ORIGEM + "/"
    assert pan.content == painel_crm_padrao.corpo_para("usr-admin-1")
    # O token do impersonate foi usado numa chamada só.
    assert sum(1 for r in falsa.pedidos if TOKEN_CONTA in r.headers.get("authorization", "")) == 1

    # Gravado por tipo (integração crm e dados_helena); token em lugar nenhum.
    crm = json.loads(await banco._pool.fetchval(
        "select config from agentesia_integracoes where id_escritorio = $1::uuid and tipo = 'crm'", id_escritorio))
    assert crm["id_painel"] == "painel-novo" and crm["etapas_por_tipo"]["DESQUALIFICADO"] == "etapa-5"
    tudo = await banco._pool.fetchval(
        """select coalesce((select string_agg(coalesce(resumo,'') || coalesce(erro,'') || coalesce(depois::text,''), ' ')
                            from agentesia_alteracoes where id_escritorio = $1::uuid), '')
                  || (select dados_helena::text from agentesia_escritorios where id = $1::uuid)""", id_escritorio)
    assert TOKEN_LOGIN not in tudo and TOKEN_CONTA not in tudo and "123456" not in tudo
    assert TOKEN_LOGIN not in feito.text and TOKEN_CONTA not in feito.text
    auditoria = await banco._pool.fetch(
        "select acao, situacao, depois from agentesia_alteracoes where id_escritorio = $1::uuid order by criado_em", id_escritorio)
    assert [a["acao"] for a in auditoria] == ["painel_crm_codigo", "painel_crm_simulacao", "painel_crm_codigo", "painel_crm_criar"]
    assert all(a["situacao"] == "ok" and json.loads(a["depois"])["ip"] for a in auditoria)

    # Já existe painel: bloqueia antes de pedir código.
    de_novo = await cliente.post(f"{base}/codigo", headers=CAB)
    assert de_novo.status_code == 409 and "Já existe painel" in de_novo.json()["detail"]


async def test_trava_desligado_responde_404(ambiente, monkeypatch):
    cliente, _f, _b, id_escritorio, _c, _a = ambiente
    monkeypatch.delenv("AGENTESIA_PAINEL_CRM_LIGADO")
    assert (await cliente.post(f"{_base(id_escritorio)}/codigo", headers=CAB)).status_code == 404
    assert (await cliente.get(_base(id_escritorio))).status_code == 404


async def test_trava_nao_admin_403_sessao_velha_401_e_csrf(ambiente):
    cliente, falsa, banco, id_escritorio, _c, app = ambiente
    base = _base(id_escritorio)
    assert (await cliente.post(f"{base}/codigo")).status_code == 403                 # sem o cabeçalho anti-CSRF
    assert (await cliente.post(f"{base}/codigo", headers={**CAB, "origin": "https://malicioso.teste"})).status_code == 403
    # Gestor do escritório: 403.
    gestor = await banco._pool.fetchval(
        "insert into agentesia_usuarios (email, nome, senha_hash, papel, id_escritorio) values ($1, 'G', 'h', 'gestor', $2::uuid) returning id",
        f"g-{uuid.uuid4().hex[:6]}@x.com", id_escritorio)
    cliente.cookies.clear()
    cliente.cookies.set(COOKIE, app.state.assinador.criar(str(gestor)))
    assert (await cliente.post(f"{base}/codigo", headers=CAB)).status_code == 403
    # Admin com login de mais de 15 minutos: pede login de novo.
    admin = await banco._pool.fetchval("select id from agentesia_usuarios where papel = 'admin_lawchat' order by criado_em desc limit 1")
    cliente.cookies.clear()
    cliente.cookies.set(COOKIE, app.state.assinador.criar(str(admin), seguranca.DURACAO_SESSAO_S - 16 * 60))
    assert (await cliente.post(f"{base}/codigo", headers=CAB)).status_code == 401
    assert falsa.pedidos == []


async def test_trava_criar_sem_simulacao_e_limite_por_hora(ambiente):
    cliente, falsa, _b, id_escritorio, _c, _a = ambiente
    base = _base(id_escritorio)
    sem = await cliente.post(base, json={"codigo": "123456"}, headers=CAB)
    assert sem.status_code == 409 and "simulação" in sem.json()["detail"]
    for _ in range(3):
        assert (await cliente.post(f"{base}/codigo", headers=CAB)).status_code == 200
    assert (await cliente.post(f"{base}/codigo", headers=CAB)).status_code == 429
    assert falsa.caminhos().count("/auth/v2/login/send-otp") == 3


async def test_trava_codigo_errado_para_no_login(ambiente):
    cliente, falsa, banco, id_escritorio, _c, _a = ambiente
    base = _base(id_escritorio)
    await cliente.post(f"{base}/codigo", headers=CAB)
    r = (await cliente.post(f"{base}?simular=true", json={"codigo": "999999"}, headers=CAB)).json()
    assert r["ok"] is False and r["parou_em"] == "login" and "código errado ou vencido" in r["erro"]
    assert TOKEN_LOGIN not in json.dumps(r)
    assert (await cliente.get(base)).json()["estado"] == "livre"


async def test_trava_companyid_divergente_para_sem_criar(ambiente):
    cliente, falsa, banco, id_escritorio, _c, _a = ambiente
    base = _base(id_escritorio)
    sim = await _simular(cliente, base)
    assert sim["ok"]
    falsa.empresas = [e for e in falsa.empresas if e["id"] != falsa.id_conta]          # a conta sumiu da lista
    falsa.pedidos.clear()
    await cliente.post(f"{base}/codigo", headers=CAB)
    r = (await cliente.post(base, json={"codigo": "123456"}, headers=CAB)).json()
    assert r["ok"] is False and r["parou_em"] == "empresas"
    assert "/auth/v2/login/authenticate/impersonate" not in falsa.caminhos() and "/crm/v1/panel" not in falsa.caminhos()
    erro = await banco._pool.fetchval(
        "select erro from agentesia_alteracoes where id_escritorio = $1::uuid and acao = 'painel_crm_criar'", id_escritorio)
    assert "empresas" in erro


async def test_trava_usuario_com_outro_email_para(ambiente):
    cliente, falsa, _b, id_escritorio, _c, _a = ambiente
    falsa.usuarios = [{"userId": "usr-x", "email": "ia@lawchat.teste.br"}]               # parecido não vale
    r = await _simular(cliente, _base(id_escritorio))
    assert r["ok"] is False and r["parou_em"] == "usuarios"


async def test_trava_duplo_clique_roda_uma_vez(ambiente):
    cliente, falsa, _b, id_escritorio, _c, _a = ambiente
    base = _base(id_escritorio)
    assert (await _simular(cliente, base))["ok"]
    await cliente.post(f"{base}/codigo", headers=CAB)
    falsa.atraso_login = 0.3
    um, dois = await asyncio.gather(cliente.post(base, json={"codigo": "123456"}, headers=CAB),
                                    cliente.post(base, json={"codigo": "123456"}, headers=CAB))
    codigos = sorted([um.status_code, dois.status_code])
    assert codigos == [200, 409]
    assert falsa.caminhos().count("/crm/v1/panel") == 1


async def test_trava_timeout_no_painel_fica_incerto_e_bloqueado(ambiente):
    cliente, falsa, banco, id_escritorio, _c, _a = ambiente
    base = _base(id_escritorio)
    assert (await _simular(cliente, base))["ok"]
    await cliente.post(f"{base}/codigo", headers=CAB)
    falsa.timeout_no_painel = True
    r = (await cliente.post(base, json={"codigo": "123456"}, headers=CAB)).json()
    assert r["ok"] is False and r["estado"] == "incerto" and "Confira na LawChat" in r["erro"]
    assert falsa.caminhos().count("/crm/v1/panel") == 1                                  # sem repetir
    bloqueado = await cliente.post(f"{base}/codigo", headers=CAB)
    assert bloqueado.status_code == 409 and "incerto" in bloqueado.json()["detail"]
    assert (await cliente.post(f"{base}/conferido", headers=CAB)).json()["estado"] == "livre"
    assert (await cliente.post(f"{base}/codigo", headers=CAB)).status_code == 200


async def test_trava_retorno_sem_6_etapas_vira_divergencia_e_aviso(ambiente):
    cliente, falsa, banco, id_escritorio, _c, _a = ambiente
    base = _base(id_escritorio)
    assert (await _simular(cliente, base))["ok"]
    await cliente.post(f"{base}/codigo", headers=CAB)
    falsa.etapas = 5
    r = (await cliente.post(base, json={"codigo": "123456"}, headers=CAB)).json()
    assert r["ok"] is False and r["estado"] == "divergente" and "5 etapas" in r["divergencias"][0]
    aviso = await banco._pool.fetchrow(
        "select gravidade, descricao from agentesia_eventos where id_escritorio = $1::uuid and tipo = 'painel_crm_divergente'",
        id_escritorio)
    assert aviso and aviso["gravidade"] == "erro"
    assert (await cliente.get(base)).json()["estado"] == "divergente"
