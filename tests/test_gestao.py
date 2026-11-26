"""API do painel de gestão contra um Postgres local (mesmas tabelas do Supabase).

Só roda com AGENTESIA_TESTE_PG_URL (ver tests/test_postgres.py). A Helena é simulada.
"""

import json
import os
import uuid

import httpx
import pytest
from fastapi import FastAPI

from app.banco.postgres import RepositorioPostgres
from app.canal import helena_conta
from app.config import Configuracao
from app.gestao import seguranca
from app.gestao.laboratorio import Laboratorios
from app.gestao.repositorio import RepositorioGestao
from app.gestao.rotas import api, entrada
from app.modelo import ModeloFalso
from tests.test_turno import extrai, fala

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
pytestmark = pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")

def novos_canais():
    """Cada conta da Helena tem os próprios canais (o id do canal é único no sistema)."""
    return [
        {"id": "ch-" + uuid.uuid4().hex[:8], "active": True, "type": "ZAPI_WhatsApp", "number": "5511912345678",
         "numberFormatted": "(11) 91234-5678", "identity": {"displayName": "Escritório"}},
        {"id": "ch-" + uuid.uuid4().hex[:8], "active": True, "type": "CloudAPI_WhatsApp", "number": "5511987654321",
         "numberFormatted": "(11) 98765-4321", "identity": {"displayName": "Oficial"}},
    ]


ATENDENTE = {"id": str(uuid.uuid4()), "userId": str(uuid.uuid4()), "name": "Dra. Paula",
             "email": f"paula-{uuid.uuid4().hex[:6]}@escritorio.com"}


class HelenaSimulada:
    """Faz o papel da api.helena.run nos testes."""

    def __init__(self):
        self.assinaturas: list[dict] = []
        self.canais: dict[str, list[dict]] = {}
        self.pedidos: list[tuple[str, str]] = []

    def __call__(self, pedido: httpx.Request) -> httpx.Response:
        self.pedidos.append((pedido.method, pedido.url.path))
        if pedido.headers.get("authorization") == "Bearer token-ruim-123":
            return httpx.Response(401, json={"error": True})
        caminho = pedido.url.path
        if caminho == "/chat/v1/channel":
            token = pedido.headers.get("authorization", "")
            if token not in self.canais:
                self.canais[token] = novos_canais()
            return httpx.Response(200, json=self.canais[token])
        if caminho == "/core/v1/webhook/subscription" and pedido.method == "GET":
            return httpx.Response(200, json=[{**a, "events": [{"event": e} for e in a["events"]]} for a in self.assinaturas])
        if caminho == "/core/v1/webhook/subscription" and pedido.method == "POST":
            import json
            corpo = json.loads(pedido.content)
            assinatura = {"id": str(uuid.uuid4()), **corpo}
            self.assinaturas.append(assinatura)
            return httpx.Response(200, json=assinatura)
        if caminho == "/crm/v2/panel":
            return httpx.Response(200, json={"items": [{"id": "painel-1", "title": "Comercial", "type": "SALES",
                                                        "steps": [{"id": "s2", "title": "Proposta", "position": 2},
                                                                  {"id": "s1", "title": "Novo lead", "position": 1, "isInitial": True}]}]})
        if caminho == "/core/v1/agent":
            return httpx.Response(200, json={"items": [ATENDENTE]})
        if caminho.startswith("/core/v1/agent/"):
            id_pedido = caminho.rsplit("/", 1)[1]
            if id_pedido == ATENDENTE["userId"]:
                return httpx.Response(200, json=ATENDENTE)
            return httpx.Response(404)
        if caminho == "/core/v1/tag":
            return httpx.Response(200, json=[{"id": "t1", "name": "📞 SDR", "color": "BLUE_500"}])
        return httpx.Response(404)


@pytest.fixture
async def ambiente(monkeypatch):
    simulada = HelenaSimulada()
    original = helena_conta.HelenaConta.__init__

    def init_com_simulacao(self, token, url_base="https://api.helena.run", http=None):
        original(self, token, url_base, httpx.AsyncClient(transport=httpx.MockTransport(simulada)))

    monkeypatch.setattr(helena_conta.HelenaConta, "__init__", init_com_simulacao)
    monkeypatch.setenv("AGENTESIA_URL_PUBLICA", "https://ia.exemplo.com")
    monkeypatch.setenv("AGENTESIA_WEBHOOK_SEGREDO", "segredo-do-webhook")
    monkeypatch.setenv("OPENAI_API_KEY", "chave-de-teste")
    import tempfile
    monkeypatch.setenv("AGENTESIA_PASTA_MIDIA", tempfile.mkdtemp(prefix="midia-teste-"))

    banco = await RepositorioPostgres.conectar(URL, max_conexoes=1)  # o servidor de teste só aceita uma
    cfg = Configuracao(banco_url=URL, helena_url="https://api.helena.run", modelo_padrao="falso", modelo_falso=True,
                       espera_minima_s=0, espera_maxima_s=0, espera_padrao_s=0, segundos_por_letra=0, max_reprocessos=2)
    app = FastAPI()
    app.include_router(api)
    app.include_router(entrada)
    from app.gestao.produtos import api as api_produtos
    app.include_router(api_produtos)
    app.state.gestao = RepositorioGestao(banco._pool)
    app.state.assinador = seguranca.Assinador("segredo-de-teste")
    app.state.cfg = cfg
    # A ativação chama a URL pública do webhook para ver se ela chega no servidor: aqui, responde que sim.
    app.state.http_ativacao = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda pedido: httpx.Response(200, json={"ok": True, "feito": "teste"})))
    app.state.laboratorios = Laboratorios(ModeloFalso({
        "extrator": lambda _s, _c: extrai([("acidente_descricao", "caí da moto", "caí da moto")]),
        "etapa": lambda sistema, _c: fala("Entendi. Ficou com alguma sequela?"),
    }), cfg)

    email_admin = f"admin-{uuid.uuid4().hex[:6]}@lawchat.com"
    await banco._pool.execute(
        "insert into agentesia_usuarios (email, nome, senha_hash, papel) values ($1, 'Equipe', $2, 'admin_lawchat')",
        email_admin, seguranca.gerar_hash("senha-admin-123"))
    cliente = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://painel")
    try:
        yield cliente, simulada, email_admin, banco
    finally:
        await cliente.aclose()
        await banco.fechar()


async def _entrar(cliente, email, senha):
    resposta = await cliente.post("/api/entrar", json={"email": email, "senha": senha})
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


async def test_jornada_completa_do_admin_e_do_cliente(ambiente):
    cliente, simulada, email_admin, banco = ambiente

    # Sem sessão, nada.
    assert (await cliente.get("/api/eu")).status_code == 401
    assert (await cliente.post("/api/entrar", json={"email": email_admin, "senha": "errada"})).status_code == 401

    # 1. A equipe LawChat cria o escritório, com o token da Helena e o gestor.
    await _entrar(cliente, email_admin, "senha-admin-123")
    email_gestor = f"gestor-{uuid.uuid4().hex[:6]}@escritorio.com"
    criado = (await cliente.post("/api/admin/escritorios", json={
        "nome": "Silva Advocacia", "id_conta_helena": str(uuid.uuid4()), "token_helena": "token-bom-" + uuid.uuid4().hex[:6] + "3456",
        "email_gestor": email_gestor, "nome_gestor": "Dra. Silva"})).json()
    id_escritorio = criado["escritorio"]["id"]
    assert criado["helena"]["situacao"] == "ok" and criado["helena"]["final_segredo"] == "3456"
    senha = criado["senha_provisoria"]
    lista = (await cliente.get("/api/admin/escritorios")).json()
    assert any(e["id"] == id_escritorio and e["helena"] == "ok" for e in lista)
    # O token não fica em tabela nossa: só no cofre.
    assert await banco._pool.fetchval("select count(*) from agentesia_integracoes where config::text like '%token-bom%'") == 0

    # 2. O gestor entra e vê só o próprio escritório.
    await cliente.post("/api/sair")
    entrada = await _entrar(cliente, email_gestor, senha)
    assert entrada["trocar_senha"] is True
    assert (await cliente.post("/api/senha", json={"atual": senha, "nova": "nova-senha-forte"})).status_code == 200
    eu = (await cliente.get("/api/eu")).json()
    assert eu["papel"] == "gestor" and eu["id_escritorio"] == id_escritorio
    assert (await cliente.get("/api/admin/escritorios")).status_code == 403
    outro = (await cliente.get("/api/escritorio", headers={"x-escritorio": str(uuid.uuid4())})).json()
    assert outro["id"] == id_escritorio                        # cabeçalho de escritório não vale para gestor

    # 3. Integrações: canais vieram da Helena; webhook é conectado pelo sistema.
    integracoes = (await cliente.get("/api/integracoes")).json()
    assert len(integracoes["canais"]) == 2 and integracoes["integracoes"]["helena"]["situacao"] == "ok"
    conectado = (await cliente.post("/api/integracoes/helena/conectar")).json()
    assert conectado["assinatura"]["acao"] == "criada" and "url" not in conectado["assinatura"]
    from app.canal.webhook import segredo_do_escritorio
    assert simulada.assinaturas[0]["url"] ==         f"https://ia.exemplo.com/webhook/helena/{id_escritorio}?segredo={segredo_do_escritorio(id_escritorio)}"
    assert (await cliente.post("/api/integracoes/helena/conectar")).json()["assinatura"]["acao"] == "ja_estava_certa"
    paineis = (await cliente.get("/api/integracoes/helena/paineis")).json()
    assert [e["titulo"] for e in paineis["paineis"][0]["etapas"]] == ["Novo lead", "Proposta"]
    crm = (await cliente.put("/api/integracoes/crm", json={"id_painel": "painel-1", "titulo_painel": "Comercial"})).json()
    assert crm["config"]["id_painel"] == "painel-1"

    # Token errado: avisa e não quebra.
    ruim = await cliente.put("/api/integracoes/helena", json={"token": "token-ruim-123"})
    assert ruim.status_code == 502 and "recusou o token" in ruim.json()["detail"]
    assert (await cliente.put("/api/integracoes/helena", json={"token": "token-bom-" + uuid.uuid4().hex[:8]})).status_code == 200
    await cliente.post("/api/integracoes/helena/conectar")

    # 4. Cria o agente no número livre; o mesmo número não aceita outro agente.
    canal = integracoes["canais"][0]
    agente = (await cliente.post("/api/agentes", json={"nome": "Júlia", "id_canal": canal["id"]})).json()
    assert agente["situacao"] == "pausado" and agente["modo"] == "teste" and agente["modelo"] == "gpt-4.1-mini"
    assert [e["codigo"] for e in agente["etapas"]][:3] == ["sdr", "periodo_graca", "closer"]
    assert (await cliente.post("/api/agentes", json={"nome": "Outra", "id_canal": canal["id"]})).status_code == 409

    # 5. Instrução (prompt por etapa) é só da equipe LawChat: o gestor do escritório não edita.
    negada = await cliente.put(f"/api/agentes/{agente['id']}/etapas/sdr", json={"instrucao": "Fale bem devagar."})
    assert negada.status_code == 403 and "equipe LawChat" in negada.json()["detail"]
    assert (await cliente.put(f"/api/agentes/{agente['id']}/etapas/sdr",
                              json={"instrucao": "x", "travada": True})).status_code == 403

    # 6. Ativar exige número de teste; depois ativa em teste e passa para todos.
    checagem = (await cliente.get(f"/api/agentes/{agente['id']}/ativacao/checagem")).json()
    passos = {p["codigo"]: p for p in checagem["passos"]}
    assert not checagem["pronto"] and passos["teste"]["situacao"] == "erro"
    assert passos["helena"]["situacao"] == "ok" and passos["canal"]["situacao"] == "ok"
    assert passos["webhook"]["situacao"] == "ok" and passos["alcance"]["situacao"] == "ok"
    assert passos["modelo_ia"]["situacao"] == "ok" and passos["etapas"]["situacao"] == "ok"
    bloqueio = await cliente.post(f"/api/agentes/{agente['id']}/ativacao", json={"situacao": "ativo"})
    assert bloqueio.status_code == 409 and "número de teste" in bloqueio.json()["detail"]
    guardada = (await cliente.get(f"/api/agentes/{agente['id']}")).json()["ultima_preparacao"]
    assert guardada["pronto"] is False and guardada["por"]
    alterado = (await cliente.patch(f"/api/agentes/{agente['id']}", json={
        "numeros_teste": ["(11) 98888-7777"], "honorarios": "30% no final", "modelo": "gpt-4.1-mini"})).json()
    assert alterado["numeros_teste"] == ["5511988887777"] and alterado["modelo"] == "gpt-4.1-mini"
    ativo = (await cliente.post(f"/api/agentes/{agente['id']}/ativacao", json={"situacao": "ativo", "modo": "teste"})).json()
    assert (ativo["situacao"], ativo["modo"]) == ("ativo", "teste") and ativo["preparacao"]["pronto"]
    assert (await cliente.post(f"/api/agentes/{agente['id']}/ativacao",
                               json={"situacao": "ativo", "modo": "producao"})).json()["modo"] == "producao"

    # 6b. Automações ligam o agente ao CRM, e valem para o agente que já está rodando.
    sugestao = (await cliente.get(f"/api/agentes/{agente['id']}/automacoes/sugestao")).json()
    assert sugestao["automacoes"]["lead_novo"]["coluna_crm"] == "s1"            # etapa inicial do painel
    assert sugestao["automacoes"]["etapa:closer"]["coluna_crm"] == "s2"          # "Proposta" casa com o closer
    regras = {**sugestao["automacoes"],
              "etapa:closer": {"coluna_crm": "s2", "adicionar_etiquetas": ["🛒 Comercial"], "remover_etiquetas": ["📞 SDR"]},
              "gatilho_inventado": {"nota": "x"}}
    salvo = (await cliente.put(f"/api/agentes/{agente['id']}/automacoes", json={"automacoes": regras})).json()
    assert "gatilho_inventado" not in salvo["automacoes"]
    assert salvo["automacoes"]["etapa:closer"]["remover_etiquetas"] == ["📞 SDR"]
    funcoes = (await cliente.patch(f"/api/agentes/{agente['id']}", json={
        "funcoes": {"crm": True, "avisos": True, "contrato_zapsign": True}})).json()["funcoes"]
    assert funcoes["crm"] and funcoes["avisos"] and funcoes["contrato_zapsign"]   # ligar o contrato acrescenta as etapas de assinatura

    # 7. Laboratório com a configuração salva.
    lab = (await cliente.post(f"/api/agentes/{agente['id']}/laboratorio", json={"texto": "oi, caí da moto"})).json()
    assert lab["turno"]["mensagens"][0]["texto"] == "Entendi. Ficou com alguma sequela?"
    assert lab["fatos"] == {"acidente_descricao": "caí da moto"}
    seguinte = (await cliente.post(f"/api/agentes/{agente['id']}/laboratorio",
                                   json={"texto": "sim", "id_conversa": lab["id_conversa"]})).json()
    assert seguinte["id_conversa"] == lab["id_conversa"]

    # 8. Início, erros e histórico.
    inicio = (await cliente.get("/api/inicio")).json()
    assert inicio["agentes"][0]["nome"] == "Júlia" and "resumo" in inicio
    historico = (await cliente.get("/api/alteracoes")).json()
    acoes = [h["acao"] for h in historico]
    assert {"criou", "conectou", "ativou", "ativou_producao", "alterou"} <= set(acoes)
    assert all(h["usuario"] for h in historico if h["acao"] != "criou" or h["tabela"] != "agentesia_escritorios")

    # 9. Atendente vê conversas mas não mexe em agente.
    usuario = (await cliente.post("/api/escritorio/usuarios", json={
        "email": f"atendente-{uuid.uuid4().hex[:6]}@escritorio.com", "nome": "Ana", "papel": "atendente"})).json()
    await cliente.post("/api/sair")
    await _entrar(cliente, usuario["usuario"]["email"], usuario["senha_provisoria"])
    assert (await cliente.get("/api/conversas")).status_code == 200
    assert (await cliente.patch(f"/api/agentes/{agente['id']}", json={"nome": "X"})).status_code == 403

    # 10. A equipe LawChat trava a instrução; o gestor não consegue mais mudar.
    await cliente.post("/api/sair")
    await _entrar(cliente, email_admin, "senha-admin-123")
    cabecalho = {"x-escritorio": id_escritorio}
    etapa = await cliente.put(f"/api/agentes/{agente['id']}/etapas/sdr", json={"instrucao": "Fale bem devagar."}, headers=cabecalho)
    assert etapa.json()["instrucao"] == "Fale bem devagar."
    padrao = agente["etapas"][0]["instrucao_padrao"]
    assert (await cliente.put(f"/api/agentes/{agente['id']}/etapas/sdr", json={"instrucao": padrao},
                              headers=cabecalho)).json()["instrucao"] is None
    travada = await cliente.put(f"/api/agentes/{agente['id']}/etapas/closer",
                                json={"instrucao": "Regra do escritório.", "travada": True}, headers=cabecalho)
    assert travada.json()["instrucao_travada"] is True
    # Na visão do cliente (x-visao) a equipe LawChat também não edita: vale o que o escritório vê.
    visao_cliente = {**cabecalho, "x-visao": "gestor"}
    assert (await cliente.put(f"/api/agentes/{agente['id']}/etapas/closer", json={"instrucao": "Outra coisa."},
                              headers=visao_cliente)).status_code == 403
    await cliente.post("/api/sair")
    await _entrar(cliente, email_gestor, "nova-senha-forte")
    bloqueada = await cliente.put(f"/api/agentes/{agente['id']}/etapas/closer", json={"instrucao": "Outra coisa."})
    assert bloqueada.status_code == 403


async def test_admin_precisa_escolher_escritorio(ambiente):
    cliente, _simulada, email_admin, _banco = ambiente
    await _entrar(cliente, email_admin, "senha-admin-123")
    resposta = await cliente.get("/api/agentes")
    assert resposta.status_code == 400 and "Escolha um escritório" in resposta.json()["detail"]
    assert (await cliente.get("/api/agentes", headers={"x-escritorio": "nao-e-uuid"})).status_code == 400


def test_senha_e_sessao():
    guardado = seguranca.gerar_hash("minha senha")
    assert seguranca.conferir_senha("minha senha", guardado) and not seguranca.conferir_senha("outra", guardado)
    assinador = seguranca.Assinador("x" * 32)
    token = assinador.criar("usuario-1")
    assert assinador.ler(token).id_usuario == "usuario-1"
    assert assinador.ler(token[:-2] + "aa") is None                   # assinatura adulterada
    assert seguranca.Assinador("y" * 32).ler(token) is None          # outro segredo
    assert assinador.ler(assinador.criar("u", duracao_s=-1)) is None  # vencido


async def test_entrada_pela_helena(ambiente, monkeypatch):
    import hashlib
    import hmac
    import time

    cliente, _simulada, email_admin, _banco = ambiente
    await _entrar(cliente, email_admin, "senha-admin-123")
    conta = str(uuid.uuid4())
    criado = (await cliente.post("/api/admin/escritorios", json={
        "nome": "Escritório Helena", "id_conta_helena": conta, "token_helena": "token-bom-" + uuid.uuid4().hex[:8]})).json()
    await cliente.post("/api/sair")

    async def abrir(**params):
        cliente.cookies.clear()
        return await cliente.get("/entrar/helena", params=params, follow_redirects=False)

    # Link incompleto, conta sem IA, usuário que não é da conta.
    assert (await abrir(company_id=conta)).headers["location"] == "/entrar?erro=link_incompleto"
    assert (await abrir(company_id="1 or 1=1", user_id=ATENDENTE["userId"])).headers["location"] == "/entrar?erro=link_incompleto"
    assert (await abrir(company_id=str(uuid.uuid4()), user_id=ATENDENTE["userId"])).headers["location"] == "/entrar?erro=conta_sem_ia"
    assert (await abrir(company_id=conta, user_id=str(uuid.uuid4()))).headers["location"] == "/entrar?erro=usuario_nao_encontrado"

    # Usuário de verdade da conta: entra sem senha, como gestor, com os nomes que a Helena usa.
    resposta = await abrir(id_da_conta=conta, id_do_usuario=ATENDENTE["userId"])
    assert resposta.status_code == 303 and resposta.headers["location"] == "/"
    eu = (await cliente.get("/api/eu")).json()
    assert (eu["nome"], eu["papel"], eu["id_escritorio"]) == ("Dra. Paula", "gestor", criado["escritorio"]["id"])

    # Segunda entrada reaproveita o mesmo usuário.
    await abrir(companyId=conta, userId=ATENDENTE["userId"])
    assert (await cliente.get("/api/eu")).json()["id"] == eu["id"]

    # Com o segredo de handoff configurado, a assinatura passa a ser obrigatória.
    monkeypatch.setenv("AGENTESIA_HELENA_HANDOFF_SEGREDO", "segredo-da-helena")
    assert (await abrir(company_id=conta, user_id=ATENDENTE["userId"])).headers["location"] == "/entrar?erro=assinatura_ausente"
    ts = str(int(time.time() * 1000))
    assinatura = hmac.new(b"segredo-da-helena", f"{conta}.{ts}".encode(), hashlib.sha256).hexdigest()
    assert (await abrir(company_id=conta, user_id=ATENDENTE["userId"], ts=ts, sig="0" * 64)).headers["location"] == "/entrar?erro=assinatura_invalida"
    assert (await abrir(company_id=conta, user_id=ATENDENTE["userId"], ts=ts, sig=assinatura)).headers["location"] == "/"
    velho = str(int(time.time() * 1000) - 10 * 60 * 1000)
    assinatura_velha = hmac.new(b"segredo-da-helena", f"{conta}.{velho}".encode(), hashlib.sha256).hexdigest()
    assert (await abrir(company_id=conta, user_id=ATENDENTE["userId"], ts=velho, sig=assinatura_velha)).headers["location"] == "/entrar?erro=assinatura_expirada"


async def test_agente_proprio_pelo_painel(ambiente):
    import copy

    from app.gestao.rotas import DEFINICAO_INICIAL

    cliente, _simulada, email_admin, banco = ambiente
    await _entrar(cliente, email_admin, "senha-admin-123")
    criado = (await cliente.post("/api/admin/escritorios", json={
        "nome": "Trabalhista Ltda", "id_conta_helena": str(uuid.uuid4()), "token_helena": "token-trab-" + uuid.uuid4().hex[:8]})).json()
    cab = {"x-escritorio": criado["escritorio"]["id"]}
    canais = (await cliente.get("/api/integracoes", headers=cab)).json()["canais"]

    # Cria do zero com a definição inicial; as etapas da tabela seguem a definição.
    inicial = (await cliente.get("/api/modelo-inicial-proprio", headers=cab)).json()
    agente = (await cliente.post("/api/agentes", headers=cab, json={
        "nome": "Bia", "id_canal": canais[0]["id"], "produto": "proprio", "definicao": inicial})).json()
    assert agente["tipo_produto"] == "proprio"
    assert [(e["codigo"], e["nome"], e["tipo"]) for e in agente["etapas"]] == [
        ("triagem", "Triagem", "conversa"), ("encaminhamento", "Encaminhamento", "terminal"),
        ("fora_do_perfil", "Fora do perfil", "terminal")]
    assert agente["etapas"][0]["instrucao_padrao"].startswith("ETAPA: triagem")
    assert "etapa:encaminhamento" in agente["gatilhos"] and "intencao:quer_agendar" in agente["gatilhos"]

    # Definição inválida é recusada com mensagem clara.
    ruim = copy.deepcopy(DEFINICAO_INICIAL)
    ruim["regras"].append({"quando": {"tipo": "etapa_completa"}, "ir_para": "lugar_nenhum"})
    resposta = await cliente.put(f"/api/agentes/{agente['id']}/definicao", headers=cab, json={"definicao": ruim})
    assert resposta.status_code == 400 and "etapa que não existe" in resposta.json()["detail"]

    # Acrescenta uma etapa e uma automação que usa a intenção própria.
    nova = copy.deepcopy(DEFINICAO_INICIAL)
    nova["etapas"].insert(1, {"codigo": "agendamento", "nome": "Agendamento", "tipo": "conversa"})
    salvo = (await cliente.put(f"/api/agentes/{agente['id']}/definicao", headers=cab, json={"definicao": nova})).json()
    assert [e["codigo"] for e in salvo["etapas"]] == ["triagem", "agendamento", "encaminhamento", "fora_do_perfil"]
    regras = (await cliente.put(f"/api/agentes/{agente['id']}/automacoes", headers=cab, json={"automacoes": {
        "intencao:quer_agendar": {"nota": "Lead quer agendar."}, "etapa:sdr": {"nota": "não existe aqui"}}})).json()
    assert list(regras["automacoes"]) == ["intencao:quer_agendar"]

    # Etapa com conversa parada não pode sair da definição.
    etapa_agendamento = next(e["id"] for e in salvo["etapas"] if e["codigo"] == "agendamento")
    contato = await banco._pool.fetchval(
        "insert into agentesia_contatos (id_escritorio, telefone_normalizado) values ($1, '5511955554444') returning id",
        criado["escritorio"]["id"])
    await banco._pool.execute(
        "insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_agente, id_etapa) values ($1, $2, $3, $4, $5)",
        criado["escritorio"]["id"], contato, canais[0]["id"], agente["id"], etapa_agendamento)
    bloqueado = await cliente.put(f"/api/agentes/{agente['id']}/definicao", headers=cab,
                                  json={"definicao": DEFINICAO_INICIAL})
    assert bloqueado.status_code == 409 and "agendamento" in bloqueado.json()["detail"]

    # Agente pronto não aceita definição.
    pronto = (await cliente.post("/api/agentes", headers=cab, json={"nome": "Júlia", "id_canal": canais[1]["id"]})).json()
    assert (await cliente.put(f"/api/agentes/{pronto['id']}/definicao", headers=cab,
                              json={"definicao": DEFINICAO_INICIAL})).status_code == 400


async def test_biblioteca_de_modelos(ambiente):
    cliente, _simulada, email_admin, _banco = ambiente
    await _entrar(cliente, email_admin, "senha-admin-123")
    criado = (await cliente.post("/api/admin/escritorios", json={
        "nome": "Escritório Biblioteca", "id_conta_helena": str(uuid.uuid4()),
        "token_helena": "token-bib-" + uuid.uuid4().hex[:8], "email_gestor": f"g-{uuid.uuid4().hex[:6]}@x.com"})).json()
    cab = {"x-escritorio": criado["escritorio"]["id"]}

    # A equipe cria um modelo do zero, com instrução, função e automação (a coluna do CRM é descartada).
    inicial = (await cliente.get("/api/modelo-inicial-proprio")).json()
    modelo = (await cliente.post("/api/admin/modelos", json={
        "nome": "Triagem trabalhista", "descricao": "Triagem e agendamento", "produto": "proprio", "definicao": inicial,
        "instrucoes": {"triagem": "Seja breve.", "inexistente": "x"}, "funcoes": {"avisos": True, "contrato_zapsign": True},
        "automacoes": {"lead_novo": {"coluna_crm": "col-x", "adicionar_etiquetas": ["Novo"]}}})).json()
    assert modelo["situacao"] == "rascunho" and modelo["config"]["instrucoes"] == {"triagem": "Seja breve."}
    assert modelo["config"]["funcoes"] == {"avisos": True, "contrato_zapsign": True}

    # Rascunho não aparece para o cliente; publicado aparece.
    gestor = {"email": criado["gestor"]["email"], "senha": criado["senha_provisoria"]}
    assert all(m["id"] != modelo["id"] for m in (await cliente.get("/api/modelos", headers=cab)).json())
    corpo = {k: v for k, v in modelo["config"].items() if k in ("definicao", "instrucoes", "funcoes", "automacoes", "honorarios")}
    publicado = (await cliente.put(f"/api/admin/modelos/{modelo['id']}", json={
        "nome": modelo["nome"], "descricao": modelo["descricao"], "produto": "proprio", "situacao": "publicado",
        **corpo, "automacoes": {"lead_novo": {"coluna_crm": "col-x", "adicionar_etiquetas": ["Novo"]}}})).json()
    assert publicado["situacao"] == "publicado"

    await cliente.post("/api/sair")
    await _entrar(cliente, gestor["email"], gestor["senha"])
    lista = (await cliente.get("/api/modelos")).json()
    assert any(m["id"] == modelo["id"] for m in lista)
    assert (await cliente.get("/api/admin/modelos")).status_code == 403

    # O cliente ativa o modelo num número dele.
    canais = (await cliente.get("/api/integracoes")).json()["canais"]
    agente = (await cliente.post("/api/agentes", json={"nome": "Lia", "id_canal": canais[0]["id"], "id_modelo": modelo["id"]})).json()
    assert agente["tipo_produto"] == "proprio" and agente["funcoes"]["avisos"] is True
    assert next(e for e in agente["etapas"] if e["codigo"] == "triagem")["instrucao"] == "Seja breve."
    assert agente["automacoes"] == {"lead_novo": {"adicionar_etiquetas": ["Novo"]}}       # sem coluna do CRM

    # A equipe transforma o agente num modelo novo.
    await cliente.post("/api/sair")
    await _entrar(cliente, email_admin, "senha-admin-123")
    copia = (await cliente.post(f"/api/admin/modelos/do-agente/{agente['id']}", headers=cab)).json()
    assert copia["situacao"] == "rascunho" and copia["config"]["instrucoes"]["triagem"] == "Seja breve."


async def test_dono_equipe_e_visao_do_cliente(ambiente):
    cliente, _simulada, email_admin, banco = ambiente
    email_dono = f"dono-{uuid.uuid4().hex[:6]}@lawchat.com"
    await banco._pool.execute(
        "insert into agentesia_usuarios (email, nome, senha_hash, papel) values ($1, 'Dono', $2, 'dono_lawchat')",
        email_dono, seguranca.gerar_hash("senha-dono-123"))

    # Equipe vê a equipe, mas não muda.
    await _entrar(cliente, email_admin, "senha-admin-123")
    equipe = (await cliente.get("/api/admin/equipe")).json()
    assert {m["email"] for m in equipe} >= {email_admin, email_dono}
    assert (await cliente.post("/api/admin/equipe", json={"email": "x@lawchat.com", "nome": "X"})).status_code == 403

    # Dono adiciona alguém, muda papel e não consegue ficar sem dono.
    await cliente.post("/api/sair")
    await _entrar(cliente, email_dono, "senha-dono-123")
    novo_email = f"suporte-{uuid.uuid4().hex[:6]}@lawchat.com"
    novo = (await cliente.post("/api/admin/equipe", json={"email": novo_email, "nome": "Suporte"})).json()
    assert novo["membro"]["papel"] == "admin_lawchat" and len(novo["senha_provisoria"]) >= 10
    assert (await cliente.post("/api/admin/equipe", json={"email": novo_email, "nome": "De novo"})).status_code == 409
    id_dono = (await cliente.get("/api/eu")).json()["id"]
    proprio = await cliente.patch(f"/api/admin/equipe/{id_dono}", json={"ativo": False})
    assert proprio.status_code == 400 and "próprio" in proprio.json()["detail"]
    promovido = (await cliente.patch(f"/api/admin/equipe/{novo['membro']['id']}", json={"papel": "dono_lawchat"})).json()
    assert promovido["membro"]["papel"] == "dono_lawchat"
    assert (await cliente.patch(f"/api/admin/equipe/{novo['membro']['id']}", json={"ativo": False})).status_code == 200
    assert "senha_provisoria" in (await cliente.post(f"/api/admin/equipe/{novo['membro']['id']}/senha")).json()

    # Responsável pelo escritório e visão do cliente.
    escritorio = (await cliente.post("/api/admin/escritorios", json={"nome": "Visão Ltda"})).json()["escritorio"]
    assert (await cliente.put(f"/api/admin/escritorios/{escritorio['id']}/responsavel",
                              json={"id_usuario": novo["membro"]["id"]})).status_code == 400      # desativado
    assert (await cliente.put(f"/api/admin/escritorios/{escritorio['id']}/responsavel",
                              json={"id_usuario": id_dono})).status_code == 200
    linha = next(e for e in (await cliente.get("/api/admin/escritorios")).json() if e["id"] == escritorio["id"])
    assert linha["responsavel"] == "Dono"

    como_gestor = {"x-escritorio": escritorio["id"], "x-visao": "gestor"}
    assert (await cliente.get("/api/eu", headers=como_gestor)).json()["visao"] == "gestor"
    assert (await cliente.get("/api/agentes", headers=como_gestor)).status_code == 200
    bloqueado = await cliente.get("/api/admin/escritorios", headers=como_gestor)
    assert bloqueado.status_code == 403 and "visão do cliente" in bloqueado.json()["detail"]
    como_atendente = {"x-escritorio": escritorio["id"], "x-visao": "atendente"}
    assert (await cliente.get("/api/integracoes", headers=como_atendente)).status_code == 403
    assert (await cliente.get("/api/conversas", headers=como_atendente)).status_code == 200
    assert (await cliente.get("/api/eu", headers={"x-visao": "dono_lawchat", "x-escritorio": escritorio["id"]})).status_code == 400


async def test_avisos_a_equipe_pelo_painel(ambiente):
    cliente, _simulada, email_admin, _banco = ambiente
    await _entrar(cliente, email_admin, "senha-admin-123")
    escritorio = (await cliente.post("/api/admin/escritorios", json={
        "nome": "Avisos Ltda", "id_conta_helena": str(uuid.uuid4()), "token_helena": "token-bom-" + uuid.uuid4().hex[:8]})).json()["escritorio"]
    h = {"x-escritorio": escritorio["id"]}
    canal = (await cliente.get("/api/integracoes", headers=h)).json()["canais"][0]
    await cliente.post("/api/agentes", headers=h, json={"nome": "Júlia", "id_canal": canal["id"], "produto": "auxilio_acidente"})

    lista = (await cliente.get("/api/notificacoes", headers=h)).json()
    assert lista["eventos"]["sinal:nao_sabe_ler"] == "Lead não sabe ler" and "etapa:closer" in lista["eventos"]
    assert (await cliente.put("/api/notificacoes/inventado", headers=h, json={
        "nome": "Inventado", "modelo_mensagem": "oi!", "destinatarios": []})).status_code == 400
    sem_numero = await cliente.put("/api/notificacoes/etapa:closer", headers=h, json={
        "nome": "Qualificado", "modelo_mensagem": "{{nome}}", "destinatarios": []})
    assert sem_numero.status_code == 400 and "número" in sem_numero.json()["detail"]
    salvo = (await cliente.put("/api/notificacoes/etapa:closer", headers=h, json={
        "nome": "Lead qualificado", "modelo_mensagem": lista["modelo_padrao"],
        "destinatarios": [{"rotulo": "Dra. Ana", "numero": "(11) 91111-2222"}]})).json()
    assert salvo["destinatarios"] == [{"rotulo": "Dra. Ana", "numero": "5511911112222"}]
    previa = (await cliente.post("/api/notificacoes/etapa:closer/teste", headers=h)).json()
    assert previa["texto"].startswith("[TESTE]") and "Maria Exemplo" in previa["texto"] and previa["destinatarios"] == ["Dra. Ana"]
    enviado = (await cliente.post("/api/notificacoes/etapa:closer/teste?enviar=true", headers=h)).json()
    assert enviado["enfileirados"] == 1
    assert (await cliente.delete("/api/notificacoes/etapa:closer", headers=h)).json() == {"ok": True}


async def test_equipe_lawchat_entra_pela_conta_da_lawchat_na_helena(ambiente, monkeypatch):
    cliente, _simulada, _email_admin, _banco = ambiente
    conta_lawchat = str(uuid.uuid4())
    monkeypatch.setitem(ATENDENTE, "email", f"suporte-{uuid.uuid4().hex[:6]}@lawchat.com")   # pessoa da equipe na Helena
    monkeypatch.setenv("AGENTESIA_HELENA_CONTA_LAWCHAT", conta_lawchat)
    cliente.cookies.clear()
    # Sem o token da conta LawChat no servidor: recusa.
    r = await cliente.get("/entrar/helena", params={"company_id": conta_lawchat, "user_id": ATENDENTE["userId"]}, follow_redirects=False)
    assert r.headers["location"] == "/entrar?erro=helena_nao_conectada"
    monkeypatch.setenv("AGENTESIA_HELENA_TOKEN_LAWCHAT", "token-bom-lawchat")
    r = await cliente.get("/entrar/helena", params={"company_id": conta_lawchat, "user_id": ATENDENTE["userId"]}, follow_redirects=False)
    assert r.headers["location"] == "/admin/escritorios"
    eu = (await cliente.get("/api/eu")).json()
    assert eu["papel"] == "admin_lawchat" and eu["id_escritorio"] is None and eu["email"] == ATENDENTE["email"]
    # Pessoa que não existe na conta da LawChat: recusa.
    cliente.cookies.clear()
    r = await cliente.get("/entrar/helena", params={"company_id": conta_lawchat, "user_id": str(uuid.uuid4())}, follow_redirects=False)
    assert r.headers["location"] == "/entrar?erro=usuario_nao_encontrado"


async def test_followup_configurado_pelo_painel(ambiente):
    cliente, _simulada, email_admin, _banco = ambiente
    await _entrar(cliente, email_admin, "senha-admin-123")
    escritorio = (await cliente.post("/api/admin/escritorios", json={
        "nome": "Follow Ltda", "id_conta_helena": str(uuid.uuid4()), "token_helena": "token-bom-" + uuid.uuid4().hex[:8]})).json()["escritorio"]
    h = {"x-escritorio": escritorio["id"]}
    canal = next(c for c in (await cliente.get("/api/integracoes", headers=h)).json()["canais"] if c["tipo"] != "oficial")
    agente = (await cliente.post("/api/agentes", headers=h, json={"nome": "Júlia", "id_canal": canal["id"]})).json()

    inicial = (await cliente.get(f"/api/agentes/{agente['id']}/followup", headers=h)).json()
    assert inicial["config"]["ativo"] is False and [p["apos_horas"] for p in inicial["config"]["passos"]] == [1, 24, 72, 168]
    assert {"codigo": "sdr", "nome": "Primeiro atendimento", "tipo": "conversa", "pode_followup": True} in inicial["etapas"]
    ruim = await cliente.put(f"/api/agentes/{agente['id']}/followup", headers=h, json={**inicial["config"], "horario": {"inicio": 20, "fim": 8, "dias": [0]}})
    assert ruim.status_code == 400 and "início" in ruim.json()["detail"]
    salvo = (await cliente.put(f"/api/agentes/{agente['id']}/followup", headers=h, json={
        **inicial["config"], "ativo": True, "etapas": ["sdr", "inventada"], "por_etapa": {"closer": "lembre dos honorários"},
        "passos": [{"apos_horas": 2, "modo": "texto", "texto": "Oi {nome}!"}, {"apos_horas": 48, "modo": "ia", "instrucao": "pergunte se tem dúvida"}]})).json()
    assert salvo["ativo"] and salvo["etapas"] == ["sdr"] and salvo["por_etapa"] == {"closer": "lembre dos honorários"}
    previa = (await cliente.post(f"/api/agentes/{agente['id']}/followup/previa", headers=h, json={"passo": 0, "config": salvo})).json()
    assert previa["mensagens"] == ["Oi Maria!"]


async def test_documentos_limite_de_consumo_e_botao_da_ia(ambiente):
    import base64

    cliente, _simulada, email_admin, banco = ambiente
    await _entrar(cliente, email_admin, "senha-admin-123")
    escritorio = (await cliente.post("/api/admin/escritorios", json={
        "nome": "Base Ltda", "id_conta_helena": str(uuid.uuid4()), "token_helena": "token-bom-" + uuid.uuid4().hex[:8]})).json()["escritorio"]
    h = {"x-escritorio": escritorio["id"]}
    integracoes = (await cliente.get("/api/integracoes", headers=h)).json()
    assert integracoes["url_botao_ia"].startswith(f"https://ia.exemplo.com/webhook/helena/{escritorio['id']}/ia?segredo=")
    canal = next(c for c in integracoes["canais"] if c["tipo"] != "oficial")
    agente = (await cliente.post("/api/agentes", headers=h, json={"nome": "Júlia", "id_canal": canal["id"]})).json()

    # Documento de texto: lido, guardado só o texto, aparece na lista e na contagem do agente.
    arquivo = "Horário: segunda a sexta, 8h às 18h.\nEndereço: Rua Central, 100.".encode()
    enviado = await cliente.post(f"/api/agentes/{agente['id']}/documentos", headers=h, json={
        "nome": "Escritório.txt", "conteudo_base64": "data:text/plain;base64," + base64.b64encode(arquivo).decode(), "mime": "text/plain"})
    assert enviado.status_code == 200, enviado.text
    assert enviado.json()["formato"] == "texto" and "Rua Central" in enviado.json()["previa"]
    lista = (await cliente.get(f"/api/agentes/{agente['id']}/documentos", headers=h)).json()
    assert [d["nome"] for d in lista] == ["Escritório.txt"]
    assert (await cliente.get(f"/api/agentes/{agente['id']}", headers=h)).json()["documentos"] == 1
    ruim = await cliente.post(f"/api/agentes/{agente['id']}/documentos", headers=h, json={
        "nome": "foto.png", "conteudo_base64": base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 20).decode()})
    assert ruim.status_code == 400 and "Formato não suportado" in ruim.json()["detail"]
    assert (await cliente.delete(f"/api/agentes/{agente['id']}/documentos/{lista[0]['id']}", headers=h)).status_code == 200
    assert (await cliente.get(f"/api/agentes/{agente['id']}/documentos", headers=h)).json() == []

    # Limite de consumo: só a equipe LawChat define; o escritório vê o gasto do mês.
    assert (await cliente.put(f"/api/admin/escritorios/{escritorio['id']}/limite", json={"mensal_usd": -5})).status_code == 400
    salvo = (await cliente.put(f"/api/admin/escritorios/{escritorio['id']}/limite", json={"mensal_usd": 2, "ao_estourar": "pausar"})).json()
    assert salvo["limite_consumo"] == {"mensal_usd": 2.0, "ao_estourar": "pausar", "avisar_em": [80, 100]}
    await banco._pool.execute("insert into agentesia_chamadas_ia (id_escritorio, papel, modelo, custo_usd, sucesso) values ($1::uuid, 'etapa', 'gpt-4.1', 1.7, true)",
                              escritorio["id"])
    consumo = (await cliente.get("/api/consumo", headers=h)).json()
    assert consumo["gasto_usd"] == 1.7 and consumo["percentual"] == 85.0 and not consumo["bloqueado"]
    assert consumo["por_papel"][0]["papel"] == "etapa"
    linha = next(e for e in (await cliente.get("/api/admin/escritorios")).json() if e["id"] == escritorio["id"])
    assert linha["gasto_mes_usd"] == 1.7 and linha["limite_consumo"]["mensal_usd"] == 2.0


async def test_funil_do_inicio(ambiente):
    cliente, _simulada, email_admin, banco = ambiente
    await _entrar(cliente, email_admin, "senha-admin-123")
    escritorio = (await cliente.post("/api/admin/escritorios", json={
        "nome": "Funil Ltda", "id_conta_helena": str(uuid.uuid4()), "token_helena": "token-bom-" + uuid.uuid4().hex[:8]})).json()["escritorio"]
    h = {"x-escritorio": escritorio["id"]}
    canal = next(c for c in (await cliente.get("/api/integracoes", headers=h)).json()["canais"] if c["tipo"] != "oficial")
    agente = (await cliente.post("/api/agentes", headers=h, json={"nome": "Júlia", "id_canal": canal["id"]})).json()
    etapas = {r["codigo"]: r["id"] for r in await banco._pool.fetch(
        "select id, codigo from agentesia_agente_etapas where id_agente = $1::uuid", agente["id"])}
    vazio = (await cliente.get("/api/funil", headers=h)).json()
    assert vazio["agente"]["nome"] == "Júlia" and vazio["totais"]["leads"] == 0

    async def lead(etapa, origem=None, assinado=False, passou_por=()):
        contato = await banco._pool.fetchval("insert into agentesia_contatos (id_escritorio, telefone_normalizado) values ($1::uuid, $2) returning id",
                                             escritorio["id"], "5511" + str(uuid.uuid4().int)[:9])
        id_lead = await banco._pool.fetchval(
            "insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_agente, id_etapa, origem) values ($1::uuid, $2, $3::uuid, $4::uuid, $5, $6::jsonb) returning id",
            escritorio["id"], contato, canal["id"], agente["id"], etapas[etapa], json.dumps(origem or {}))
        for codigo in passou_por:
            await banco._pool.execute("insert into agentesia_turnos (id_escritorio, id_lead, modo, etapa_depois, situacao) values ($1::uuid, $2, 'teste', $3, 'respondido')",
                                      escritorio["id"], id_lead, codigo)
        if assinado:
            await banco._pool.execute("insert into agentesia_contratos (id_escritorio, id_lead, versao, situacao, dados, dados_hash) values ($1::uuid, $2, 1, 'assinado', '{}', 'h')",
                                      escritorio["id"], id_lead)

    anuncio = {"origem": "anuncio", "campanha": "aa-mg"}
    await lead("sdr")
    await lead("sdr", anuncio)
    await lead("closer", anuncio, assinado=True)
    await lead("desqualificado", passou_por=["closer"])         # foi até o closer e depois saiu do funil
    funil = (await cliente.get("/api/funil?dias=30", headers=h)).json()
    por_codigo = {e["codigo"]: e for e in funil["etapas"]}
    assert por_codigo["sdr"]["leads"] == 4 and por_codigo["closer"]["leads"] == 2 and por_codigo["closer"]["do_inicio"] == 50.0
    assert "desqualificado" not in por_codigo and funil["totais"]["desqualificados"] == 1 and funil["totais"]["assinados"] == 1
    assert {"origem": "aa-mg", "leads": 2, "assinados": 1} in funil["origens"] and {"origem": "Direto", "leads": 2, "assinados": 0} in funil["origens"]



async def test_catalogo_rascunho_ativacao_midia_e_conhecimento(ambiente):
    """Fluxo do agents-lawchat-main pela nossa API: produto no catálogo -> rascunho -> ativar -> agente com uma etapa por papel."""
    import base64

    from app import vetores
    from app.conhecimento_indice import indexar_pendentes

    cliente, _simulada, email_admin, banco = ambiente
    await _entrar(cliente, email_admin, "senha-admin-123")
    escritorio = (await cliente.post("/api/admin/escritorios", json={
        "nome": "Catálogo Ltda", "id_conta_helena": str(uuid.uuid4()), "token_helena": "token-bom-" + uuid.uuid4().hex[:8]})).json()["escritorio"]
    h = {"x-escritorio": escritorio["id"]}

    # Admin: produto no padrão (5 agentes), conteúdo, documento padrão e publicação.
    produto = (await cliente.post("/api/admin/biblioteca/produtos/padrao", json={
        "nome": f"BPC Autismo {uuid.uuid4().hex[:4]}", "area_juridica": "Previdenciário", "descricao": "BPC/LOAS para TEA"})).json()
    agentes = (await cliente.get(f"/api/biblioteca/produtos/{produto['id']}/agentes")).json()
    assert [a["papel"] for a in agentes] == ["sdr", "closer", "contratos", "assinatura", "desqualificado"]
    assert "@Comercial" in agentes[0]["blocos_prompt"][0]["content"]
    await cliente.patch(f"/api/admin/biblioteca/produtos/{produto['id']}", json={
        "status": "publicado", "faq": [{"pergunta": "Demora?", "resposta": "Uns meses."}], "etiquetas": ["bpc", "loas"]})
    doc = (await cliente.post(f"/api/admin/biblioteca/produtos/{produto['id']}/documentos", json={
        "nome": "Regras BPC", "tipo": "texto", "texto": "Renda familiar por pessoa de até 1/4 do salário mínimo."})).json()
    assert doc["tipo"] == "texto"
    frase = (await cliente.put("/api/admin/biblioteca/frases-troca", json={
        "id_produto_biblioteca": produto["id"], "etapa_destino": "closer", "nome": "Closer",
        "frase": "Vou te passar para a nossa especialista agora"})).json()
    assert frase["etapa_destino"] == "closer"
    assert produto["slug"] in [x["slug"] for x in (await cliente.get("/api/biblioteca/produtos")).json()]

    # Cliente: rascunho (um por produto), números e mídia.
    rascunho = (await cliente.post("/api/produtos-ativados/rascunho", headers=h, json={"id_produto_biblioteca": produto["id"]})).json()
    assert rascunho["faq"] == [{"pergunta": "Demora?", "resposta": "Uns meses."}] and rascunho["status"] == "rascunho"
    assert (await cliente.post("/api/produtos-ativados/rascunho", headers=h, json={"id_produto_biblioteca": produto["id"]})).json()["id"] == rascunho["id"]
    canais = (await cliente.get("/api/canais/disponiveis", headers=h)).json()
    livre = next(c for c in canais if c["disponivel"] and c["tipo"] != "oficial")
    audio = base64.b64encode(b"OggS" + b"0" * 64).decode()
    midia = (await cliente.post("/api/midia", headers=h, json={"nome": "explicando.ogg", "conteudo_base64": audio, "mime": "audio/ogg"})).json()
    assert midia["tipo"] == "audio" and "/midia/" in midia["url"]
    assert (await cliente.get("/api/midia", headers=h)).json()["usado_bytes"] == 68

    # Ativar: agente com uma etapa por papel, o prompt de cada um e o documento padrão copiado travado.
    payload = {"nome": "Júlia", "id_canal": livre["id"], "delay_s": 10, "pausa_min": -1, "temperatura": 0.9, "modelo": "gpt-4.1-mini",
               "ativar_imediatamente": True,
               "agentes": [{"papel": a["papel"], "nome": a["nome_exibicao"], "prompt": f"Prompt do {a['papel']} " + midia["url"],
                            "mensagem_troca": "Vou te passar para a nossa especialista agora" if a["papel"] == "closer" else None}
                           for a in agentes],
               "variables": {"NOME ESCRITORIO": "Catálogo Ltda"}}
    ativado = await cliente.post(f"/api/produtos-ativados/{rascunho['id']}/ativar", headers=h, json=payload)
    assert ativado.status_code == 200, ativado.text
    id_agente = ativado.json()["id_agente"]
    etapas = await banco._pool.fetch(
        "select codigo, tipo, instrucao, temperatura from agentesia_agente_etapas where id_agente = $1::uuid order by ordem", id_agente)
    assert [e["codigo"] for e in etapas] == ["sdr", "closer", "contratos", "assinatura", "desqualificado", "contrato_assinado"]
    assert etapas[0]["instrucao"].startswith("Prompt do sdr") and float(etapas[0]["temperatura"]) == 0.9
    agente = await banco._pool.fetchrow("select produto, situacao, modo, config from agentesia_agentes where id = $1::uuid", id_agente)
    assert (agente["produto"], agente["situacao"], agente["modo"]) == ("catalogo", "ativo", "producao")
    assert json.loads(agente["config"])["pausa_sem_volta"] is True
    detalhe = (await cliente.get(f"/api/produtos-ativados/{rascunho['id']}", headers=h)).json()
    assert detalhe["status"] == "ativo" and len(detalhe["etapas"]) == 5 and detalhe["variables"] == {"NOME ESCRITORIO": "Catálogo Ltda"}
    assert detalhe["etapas"][1]["mensagem_troca"] == "Vou te passar para a nossa especialista agora"
    resposta_docs = await cliente.get(f"/api/agentes/{id_agente}/documentos", headers=h)
    assert resposta_docs.status_code == 200, resposta_docs.text
    docs = resposta_docs.json()
    assert len(docs) == 1 and docs[0]["travado"] and docs[0]["situacao"] == "processando"
    assert (await cliente.delete(f"/api/agentes/{id_agente}/documentos/{docs[0]['id']}", headers=h)).status_code == 404
    colado = await cliente.post(f"/api/agentes/{id_agente}/documentos", headers=h,
                                json={"nome": "Honorários", "tipo": "texto", "texto": "Honorários de 30% dos atrasados."})
    assert colado.status_code == 200 and colado.json()["tipo"] == "texto"
    assert await indexar_pendentes(banco._pool, vetores.VetorizadorFalso()) >= 2
    prontos = (await cliente.get(f"/api/agentes/{id_agente}/documentos", headers=h)).json()
    assert {d["situacao"] for d in prontos} == {"pronto"} and all(d["tokens"] > 0 for d in prontos)
    assert await banco._pool.fetchval("select count(*) from agentesia_documento_trechos where id_agente = $1::uuid", id_agente) == 2

    # O número agora está em uso; pausar, sincronizar (edição) e mudar a frase propaga para o prompt.
    usado = next(c for c in (await cliente.get("/api/canais/disponiveis", headers=h)).json() if c["id"] == livre["id"])
    assert usado["em_uso_por"] == id_agente and usado["em_uso_por_nome"] == "Júlia" and not usado["disponivel"]
    pausado = await cliente.post(f"/api/produtos-ativados/{rascunho['id']}/status", headers=h, json={"status": "pausado"})
    assert pausado.json()["status"] == "pausado"
    payload["agentes"][0]["prompt"] = "Prompt novo do SDR"
    assert (await cliente.post(f"/api/produtos-ativados/{rascunho['id']}/sincronizar", headers=h, json=payload)).status_code == 200
    sdr = "select instrucao from agentesia_agente_etapas where id_agente = $1::uuid and codigo = 'sdr'"
    assert await banco._pool.fetchval(sdr, id_agente) == "Prompt novo do SDR"
    await banco._pool.execute(
        "update agentesia_agente_etapas set instrucao = 'Diga: Vou te passar para a nossa especialista agora' where id_agente = $1::uuid and codigo = 'sdr'",
        id_agente)
    await cliente.put("/api/admin/biblioteca/frases-troca", json={**frase, "frase": "Agora você fala com a nossa especialista"})
    assert "Agora você fala com a nossa especialista" in await banco._pool.fetchval(sdr, id_agente)
    lista = (await cliente.get("/api/produtos-ativados", headers=h)).json()
    assert lista[0]["biblioteca"]["slug"] == produto["slug"]
    assert (await cliente.delete(f"/api/produtos-ativados/{rascunho['id']}", headers=h)).json() == {"ok": True}
    assert await banco._pool.fetchval("select count(*) from agentesia_agentes where id = $1::uuid", id_agente) == 0



async def test_importar_catalogo_pelo_admin(ambiente):
    """Importar catálogo: prévia não grava, aplicar grava, arquivo ruim dá mensagem, gestor não pode."""
    import base64
    from pathlib import Path

    cliente, _simulada, email_admin, banco = ambiente
    await _entrar(cliente, email_admin, "senha-admin-123")
    await banco._pool.execute("""delete from agentesia_biblioteca_produtos where id in ('11111111-1111-4111-8111-111111111111',
                                 '22222222-2222-4222-8222-222222222222', '33333333-3333-4333-8333-333333333333')""")
    bruto = (Path(__file__).parent / "dados" / "catalogo_exportado.json").read_bytes()
    corpo = {"arquivos": [{"nome": "catalogo.json", "conteudo_base64": base64.b64encode(bruto).decode()}]}
    previa = await cliente.post("/api/admin/biblioteca/importar", json={**corpo, "aplicar": False})
    assert previa.status_code == 200, previa.text
    assert not previa.json()["aplicado"] and {p["acao"] for p in previa.json()["produtos"]} == {"criar"}
    assert await banco._pool.fetchval("select count(*) from agentesia_biblioteca_produtos where slug = 'auxilio-acidente'") == 0
    feito = await cliente.post("/api/admin/biblioteca/importar", json={**corpo, "aplicar": True})
    assert feito.status_code == 200 and feito.json()["aplicado"]
    catalogo = {p["slug"]: p for p in (await cliente.get("/api/biblioteca/produtos")).json()}
    assert catalogo["auxilio-acidente"]["status"] == "publicado" and "auxilio-acidente-midia" in catalogo
    agentes = (await cliente.get("/api/biblioteca/produtos/auxilio-acidente/agentes")).json()
    assert agentes[0]["config_modelo"]["faq_items"][0]["q"] == "Atende sábado?"
    ruim = await cliente.post("/api/admin/biblioteca/importar", json={"arquivos": [
        {"nome": "x.json", "conteudo_base64": base64.b64encode(b"{quebrado").decode()}], "aplicar": False})
    assert ruim.status_code == 400 and "JSON inválido" in ruim.json()["detail"]
    # Gestor de escritório não importa catálogo.
    escritorio = (await cliente.post("/api/admin/escritorios", json={
        "nome": "Importa Ltda", "id_conta_helena": str(uuid.uuid4()), "token_helena": "token-bom-" + uuid.uuid4().hex[:8],
        "email_gestor": f"gestor-{uuid.uuid4().hex[:6]}@x.com", "nome_gestor": "Gestor"})).json()
    gestor = escritorio["escritorio"]
    await cliente.post("/api/sair")
    await _entrar(cliente, (await banco._pool.fetchval("select email from agentesia_usuarios where id_escritorio = $1::uuid", gestor["id"])),
                  escritorio["senha_provisoria"])
    negado = await cliente.post("/api/admin/biblioteca/importar", json={**corpo, "aplicar": False})
    assert negado.status_code == 403
