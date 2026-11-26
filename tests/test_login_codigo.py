"""Entrar com o código da plataforma (app/gestao/login_codigo.py). A plataforma é simulada (httpx.MockTransport):
nenhum pedido sai para a rede. A parte com banco usa AGENTESIA_TESTE_PG_URL (ver tests/test_gestao.py)."""

import base64
import json
import os
import uuid

import httpx
import pytest

from app.gestao import login_codigo
from app.gestao import rotas as rotas_gestao
from tests.test_gestao import ATENDENTE, ambiente  # noqa: F401  (fixture do painel com a plataforma simulada)

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
CODIGO = "123456"


def jwt(claims: dict) -> str:
    def b64(d: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{b64({'alg': 'HS256', 'typ': 'JWT'})}.{b64(claims)}.assinatura"


class Plataforma:
    """Faz o papel de wapi.wts.chat: send-otp, authenticate e company/filter/me."""

    def __init__(self):
        self.pedidos: list[tuple[str, dict, dict]] = []
        self.pessoas: dict[str, dict] = {}         # e-mail ou telefone -> claims
        self.empresas: dict[str, list[dict]] = {}  # id da pessoa -> empresas
        self.fora_do_ar = False
        self.empresas_quebradas = False

    def __call__(self, pedido: httpx.Request) -> httpx.Response:
        corpo = json.loads(pedido.content) if pedido.content else {}
        self.pedidos.append((pedido.url.path, dict(pedido.headers), corpo))
        if self.fora_do_ar:
            return httpx.Response(503)
        caminho = pedido.url.path
        if caminho == "/auth/v2/login/send-otp":
            return httpx.Response(200 if (corpo.get("email") or corpo.get("phoneNumber")) in self.pessoas else 404)
        if caminho == "/auth/v2/login/authenticate":
            pessoa = self.pessoas.get(corpo.get("email") or corpo.get("phoneNumber"))
            if not pessoa or corpo.get("password") != CODIGO:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"accessToken": jwt(pessoa), "refreshToken": "rf_segredo"})
        if caminho == "/core/v4/company/filter/me":
            if self.empresas_quebradas:
                return httpx.Response(500)
            assert pedido.headers["authorization"].startswith("Bearer ")
            return httpx.Response(200, json={"items": self.empresas.get(pedido.url.params.get("userId"), [])})
        return httpx.Response(404)


@pytest.fixture
def plataforma(monkeypatch):
    p = Plataforma()
    monkeypatch.setattr(login_codigo, "TRANSPORTE", httpx.MockTransport(p))
    monkeypatch.setenv("AGENTESIA_HELENA_LOGIN_URL", "https://wapi.exemplo.test")
    monkeypatch.setenv("AGENTESIA_HELENA_PARCEIRO_ID", "parceiro-1")
    monkeypatch.setenv("AGENTESIA_HELENA_PARCEIRO_ORIGEM", "https://parceiro.exemplo.test")
    monkeypatch.delenv("AGENTESIA_HELENA_CONTA_LAWCHAT", raising=False)
    login_codigo._ENVIOS.clear()
    rotas_gestao._FALHAS_LOGIN.clear()
    yield p
    login_codigo._ENVIOS.clear()
    rotas_gestao._FALHAS_LOGIN.clear()


# ---------------------------------------------------------------------------- sem banco
def test_telefone_e_claims():
    assert login_codigo.telefone_normalizado("(31) 98693-6492") == "31986936492"
    assert login_codigo.telefone_normalizado("+55 31 98693-6492") == "31986936492"
    assert login_codigo.telefone_normalizado("123") is None
    quem = login_codigo.identidade(login_codigo.claims_do_token(jwt(
        {"nameid": "u-1", "unique_name": "Ana", "email": "Ana@X.com", "phone_number": "+55|31986936492"})))
    assert quem == {"id": "u-1", "email": "ana@x.com", "telefone": "31986936492", "nome": "Ana"}
    assert login_codigo.claims_do_token("lixo") == {}


def test_papel_pela_empresa():
    assert login_codigo._papel_na_empresa({"id": "c", "isOwner": True}) == "gestor"
    assert login_codigo._papel_na_empresa({"id": "c", "user": {"profile": "ADMIN"}}) == "gestor"
    assert login_codigo._papel_na_empresa({"id": "c", "user": {"profile": "AGENT"}}) == "atendente"
    assert login_codigo._papel_na_empresa({"id": "c"}) == "atendente"


# ---------------------------------------------------------------------------- com banco
pg = pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")


async def _escritorio(cliente, email_admin, conta=None):
    from tests.test_gestao import _entrar
    await _entrar(cliente, email_admin, "senha-admin-123")
    conta = conta or str(uuid.uuid4())
    esc = (await cliente.post("/api/admin/escritorios", json={
        "nome": "Escritório " + conta[:4], "id_conta_helena": conta,
        "token_helena": "token-bom-" + uuid.uuid4().hex[:8]})).json()["escritorio"]
    await cliente.post("/api/sair")
    cliente.cookies.clear()
    return esc, conta


def _app_com_login(cliente):
    app = cliente._transport.app
    if not any(getattr(r, "path", "") == "/api/entrar/codigo" for r in app.router.routes):
        app.include_router(login_codigo.api)


@pg
async def test_envia_codigo_e_responde_generico(ambiente, plataforma):
    cliente, _s, _e, _b = ambiente
    _app_com_login(cliente)
    plataforma.pessoas["ana@x.com"] = {"nameid": "u-ana", "email": "ana@x.com"}
    for email in ("ana@x.com", "ninguem@x.com"):
        r = await cliente.post("/api/entrar/codigo", json={"email": email})
        assert r.status_code == 200 and r.json()["mensagem"] == login_codigo.GENERICO
    caminho, cab, corpo = plataforma.pedidos[0]
    assert caminho == "/auth/v2/login/send-otp"
    assert corpo == {"email": "ana@x.com", "type": "EMAIL", "website": "", "partnerId": "parceiro-1"}
    assert cab["origin"] == "https://parceiro.exemplo.test" and cab["referer"] == "https://parceiro.exemplo.test/"
    # Telefone: DDD + número, sem 55.
    await cliente.post("/api/entrar/codigo", json={"telefone": "+55 (31) 98693-6492"})
    assert plataforma.pedidos[-1][2] == {"phoneNumber": "31986936492", "type": "PHONENUMBER", "website": "",
                                         "partnerId": "parceiro-1"}
    # Plataforma fora do ar: erro claro.
    plataforma.fora_do_ar = True
    r = await cliente.post("/api/entrar/codigo", json={"email": "ana@x.com"})
    assert r.status_code == 503 and "plataforma" in r.json()["detail"]


@pg
async def test_limite_de_envios(ambiente, plataforma):
    cliente, _s, _e, _b = ambiente
    _app_com_login(cliente)
    for _ in range(login_codigo._MAX_ENVIOS_ID):
        assert (await cliente.post("/api/entrar/codigo", json={"email": "muito@x.com"})).status_code == 200
    assert (await cliente.post("/api/entrar/codigo", json={"email": "muito@x.com"})).status_code == 429
    # Código errado muitas vezes também bloqueia.
    for _ in range(rotas_gestao._MAX_FALHAS_LOGIN):
        r = await cliente.post("/api/entrar/codigo/confirmar", json={"email": "erra@x.com", "codigo": "000000"})
        assert r.status_code == 401
    r = await cliente.post("/api/entrar/codigo/confirmar", json={"email": "erra@x.com", "codigo": CODIGO})
    assert r.status_code == 429


@pg
async def test_codigo_errado_e_usuario_existente(ambiente, plataforma):
    cliente, _s, email_admin, banco = ambiente
    _app_com_login(cliente)
    pool = banco._pool
    # Equipe LawChat que já existe: entra por código, cai no admin e fica ligada ao usuário da plataforma.
    id_equipe = "u-equipe-" + uuid.uuid4().hex[:6]
    plataforma.pessoas[email_admin] = {"nameid": id_equipe, "email": email_admin, "unique_name": "Equipe"}
    r = await cliente.post("/api/entrar/codigo/confirmar", json={"email": email_admin, "codigo": "999999"})
    assert r.status_code == 401 and "Código errado" in r.json()["detail"]
    dispositivo = str(uuid.uuid4())
    r = await cliente.post("/api/entrar/codigo/confirmar",
                           json={"email": email_admin.upper(), "codigo": CODIGO, "dispositivo": dispositivo})
    assert r.status_code == 200, r.text
    assert r.json()["destino"] == "/admin/escritorios"
    corpo = plataforma.pedidos[-2][2]
    assert plataforma.pedidos[-2][0] == "/auth/v2/login/authenticate"
    assert corpo == {"grantType": "OTP", "partnerId": "parceiro-1", "internalDeviceId": dispositivo,
                     "email": email_admin, "password": CODIGO}
    eu = (await cliente.get("/api/eu")).json()
    assert eu["email"] == email_admin and eu["papel"] == "admin_lawchat"
    assert await pool.fetchval("select id_usuario_helena from agentesia_usuarios where email = $1", email_admin) == id_equipe
    # O token não aparece na resposta nem no cookie.
    assert "accessToken" not in r.text and "rf_segredo" not in r.text
    assert all("rf_" not in v for v in r.cookies.values())


@pg
async def test_usuario_existente_mantem_email_e_so_preenche_id_vazio(ambiente, plataforma):
    cliente, _s, email_admin, banco = ambiente
    _app_com_login(cliente)
    pool = banco._pool
    esc, conta = await _escritorio(cliente, email_admin)
    email = f"gestor-{uuid.uuid4().hex[:6]}@x.com"
    await pool.execute("insert into agentesia_usuarios (email, nome, senha_hash, papel, id_escritorio, id_usuario_helena) "
                       "values ($1, 'Gestor', 'x', 'gestor', $2::uuid, 'u-antigo')", email, esc["id"])
    plataforma.pessoas[email] = {"nameid": "u-novo", "email": email}
    plataforma.empresas["u-novo"] = [{"id": conta}]
    r = await cliente.post("/api/entrar/codigo/confirmar", json={"email": email, "codigo": CODIGO})
    assert r.status_code == 200, r.text
    linha = await pool.fetchrow("select email, id_usuario_helena from agentesia_usuarios where email = $1", email)
    assert linha["id_usuario_helena"] == "u-antigo"            # já tinha: não troca


@pg
async def test_provisiona_usuario_novo_pelo_escritorio(ambiente, plataforma):
    cliente, _s, email_admin, banco = ambiente
    _app_com_login(cliente)
    pool = banco._pool
    esc1, conta1 = await _escritorio(cliente, email_admin)
    esc2, conta2 = await _escritorio(cliente, email_admin)
    email = f"nova-{uuid.uuid4().hex[:6]}@x.com"
    id_pessoa = "u-" + uuid.uuid4().hex[:8]
    plataforma.pessoas[email] = {"nameid": id_pessoa, "email": email.upper(), "unique_name": "Dra. Nova"}
    plataforma.empresas[id_pessoa] = [{"id": str(uuid.uuid4())},                       # conta sem escritório aqui
                                      {"id": conta1.upper(), "user": {"profile": "ADMIN"}},
                                      {"id": conta2}]
    r = await cliente.post("/api/entrar/codigo/confirmar", json={"email": email, "codigo": CODIGO})
    assert r.status_code == 200, r.text
    u = await pool.fetchrow("select * from agentesia_usuarios where email = $1", email)
    assert str(u["id_escritorio"]) == esc1["id"] and u["papel"] == "gestor"
    assert u["id_usuario_helena"] == id_pessoa and u["trocar_senha"] is False
    assert u["senha_hash"] == "sem_senha$login_pela_lawchat"
    resumo = await pool.fetchval("select resumo from agentesia_alteracoes where id_registro = $1 and acao = 'criou'", u["id"])
    assert "código da plataforma" in resumo and esc2["nome"] in resumo
    assert (await cliente.get("/api/eu")).json()["id_escritorio"] == esc1["id"]
    # A consulta de empresas levou o token da pessoa; nada de token no banco.
    assert plataforma.pedidos[-1][0] == "/core/v4/company/filter/me"
    assert not await pool.fetchval("select count(*) from agentesia_alteracoes where resumo like '%rf_segredo%'")


@pg
async def test_telefone_provisiona_pelo_id_da_plataforma(ambiente, plataforma):
    cliente, _s, email_admin, banco = ambiente
    _app_com_login(cliente)
    pool = banco._pool
    _esc, conta = await _escritorio(cliente, email_admin)
    id_pessoa = "u-" + uuid.uuid4().hex[:8]
    plataforma.pessoas["31986936492"] = {"nameid": id_pessoa, "phone_number": "+55|31986936492", "unique_name": "Zé"}
    plataforma.empresas[id_pessoa] = [{"id": conta}]
    r = await cliente.post("/api/entrar/codigo/confirmar", json={"telefone": "(31) 98693-6492", "codigo": CODIGO})
    assert r.status_code == 200, r.text
    assert plataforma.pedidos[-2][2]["phoneNumber"] == "31986936492" and "email" not in plataforma.pedidos[-2][2]
    u = await pool.fetchrow("select * from agentesia_usuarios where id_usuario_helena = $1", id_pessoa)
    assert u["papel"] == "atendente" and u["email"].endswith(".helena.local")
    # Segunda vez acha pelo id, sem criar outro.
    await cliente.post("/api/sair")
    cliente.cookies.clear()
    assert (await cliente.post("/api/entrar/codigo/confirmar",
                               json={"telefone": "31986936492", "codigo": CODIGO})).status_code == 200
    assert await pool.fetchval("select count(*) from agentesia_usuarios where id_usuario_helena = $1", id_pessoa) == 1


@pg
async def test_sem_escritorio_403_e_reserva_pelas_contas(ambiente, plataforma):
    cliente, _s, email_admin, banco = ambiente
    _app_com_login(cliente)
    pool = banco._pool
    email = f"solto-{uuid.uuid4().hex[:6]}@x.com"
    plataforma.pessoas[email] = {"nameid": "u-solto", "email": email}
    plataforma.empresas["u-solto"] = [{"id": str(uuid.uuid4())}]
    r = await cliente.post("/api/entrar/codigo/confirmar", json={"email": email, "codigo": CODIGO})
    assert r.status_code == 403 and "nenhum escritório ativo" in r.json()["detail"]

    # Consulta de empresas quebrada: procura nos usuários de cada conta (a simulada devolve ATENDENTE).
    esc, _conta = await _escritorio(cliente, email_admin)
    plataforma.empresas_quebradas = True
    plataforma.pessoas[ATENDENTE["email"]] = {"nameid": ATENDENTE["userId"], "email": ATENDENTE["email"]}
    await pool.execute("delete from agentesia_usuarios where email = $1 or id_usuario_helena = $2",
                       ATENDENTE["email"], ATENDENTE["userId"])
    r = await cliente.post("/api/entrar/codigo/confirmar", json={"email": ATENDENTE["email"], "codigo": CODIGO})
    assert r.status_code == 200, r.text
    u = await pool.fetchrow("select * from agentesia_usuarios where email = $1", ATENDENTE["email"].lower())
    assert u["id_usuario_helena"] == ATENDENTE["userId"] and u["papel"] == "atendente"
    assert u["id_escritorio"] is not None

    # Plataforma fora do ar na confirmação.
    plataforma.fora_do_ar = True
    r = await cliente.post("/api/entrar/codigo/confirmar", json={"email": email, "codigo": CODIGO})
    assert r.status_code == 503
