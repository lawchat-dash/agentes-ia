"""Conta da Helena (migração 006): onboarding em passos, "Sincronizar conta", histórico de etapa do lead, contato sem o
nono dígito e falha de ação de admin registrada.

Só roda com AGENTESIA_TESTE_PG_URL (banco local: node db/testes/servidor_local.mjs). A Helena é falsa
(httpx.MockTransport): nenhuma chamada sai da máquina.
"""

import json
import os
import uuid

import httpx
import pytest
from fastapi import FastAPI

from app.banco.postgres import RepositorioPostgres, chave_telefone
from app.banco.tipos import Agente, Canal, Escritorio, Etapa
from app.canal import helena_conta
from app.config import Configuracao
from app.contrato import servico as contrato_servico
from app.gestao import seguranca
from app.gestao.repositorio import RepositorioGestao
from app.gestao.rotas import api, entrada
from app.gestao.rotas_conta import api as api_conta
from app.gestao.sincronizar_conta import ETIQUETAS_PADRAO

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
pytestmark = pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")


class HelenaFalsa:
    """Uma conta da Helena por token, com estado que muda (para ver o que some na sincronização)."""

    def __init__(self):
        self.contas: dict[str, dict] = {}
        self.pedidos: list[tuple[str, str]] = []
        self.falhar: set[str] = set()                   # caminhos que respondem 500
        self.empresas: dict[str, dict] = {}             # GET core/v1/company (token de parceiro)
        self.tokens_criados: list[dict] = []

    def conta(self, token: str) -> dict:
        chave = token if token.lower().startswith("bearer ") else f"Bearer {token}"
        if chave not in self.contas:
            sufixo = uuid.uuid4().hex[:8]
            self.contas[chave] = {
                "canais": [
                    {"id": f"ch-a-{sufixo}", "active": True, "type": "ZAPI_WhatsApp", "number": "5511912345678",
                     "numberFormatted": "(11) 91234-5678", "identity": {"displayName": "Recepção"}},
                    {"id": f"ch-b-{sufixo}", "active": True, "type": "CloudAPI_WhatsApp", "number": "5511987654321",
                     "numberFormatted": "(11) 98765-4321", "identity": {"displayName": "Oficial"}},
                ],
                "paineis": [
                    {"id": f"p0-{sufixo}", "title": "🤖 CRM COMERCIAL IA", "type": "SALES",
                     "steps": [{"id": f"w{i}-{sufixo}", "title": t, "position": i, "isInitial": i == 1}
                               for i, t in enumerate(["📞SDR", "🛒 Comercial", "📄 Contrato em Elaboração",
                                                      "✍️ Aguardando Assinatura", "✅ Contrato Assinado",
                                                      "❌ Desqualificado"], 1)]},
                    {"id": f"p1-{sufixo}", "title": "Comercial", "type": "SALES",
                     "steps": [{"id": f"s2-{sufixo}", "title": "Proposta", "position": 2},
                               {"id": f"s1-{sufixo}", "title": "Novo lead", "position": 1, "isInitial": True}]},
                    {"id": f"p2-{sufixo}", "title": "Jurídico", "type": "OTHER",
                     "steps": [{"id": f"s3-{sufixo}", "title": "Protocolo", "position": 1}]},
                ],
                "etiquetas": [{"id": f"t-sdr-{sufixo}", "name": "📞 SDR", "color": "BLUE_500"},
                              {"id": f"t-vip-{sufixo}", "name": "VIP", "color": "RED_500"}],
                "equipes": [{"id": f"d1-{sufixo}", "name": "Comercial", "isDefault": True}],
                "usuarios": [{"id": f"a1-{sufixo}", "userId": f"u1-{sufixo}", "name": "Dra. Paula",
                              "email": "paula@escritorio.com", "phoneNumber": "5511977776666",
                              "availability": "AVAILABLE"}],
                "assinaturas": [],
            }
        return self.contas[chave]

    def __call__(self, pedido: httpx.Request) -> httpx.Response:
        self.pedidos.append((pedido.method, pedido.url.path))
        token = pedido.headers.get("authorization", "")
        if token == "Bearer token-ruim-123":
            return httpx.Response(401, json={"error": True})
        if pedido.url.path in self.falhar:
            return httpx.Response(500, text="falhou")
        c = self.conta(token)
        caminho, metodo = pedido.url.path, pedido.method
        corpo = json.loads(pedido.content) if pedido.content else {}
        if caminho == "/chat/v1/channel":
            return httpx.Response(200, json=c["canais"])
        if caminho == "/core/v1/webhook/subscription" and metodo == "GET":
            return httpx.Response(200, json=[{**a, "events": [{"event": e} for e in a["events"]]} for a in c["assinaturas"]])
        if caminho == "/core/v1/webhook/subscription" and metodo == "POST":
            nova = {"id": str(uuid.uuid4()), **corpo}
            c["assinaturas"].append(nova)
            return httpx.Response(200, json=nova)
        if caminho == "/crm/v2/panel":
            return httpx.Response(200, json={"items": c["paineis"]})
        if caminho == "/core/v1/tag" and metodo == "GET":
            return httpx.Response(200, json=c["etiquetas"])
        if caminho == "/core/v1/tag" and metodo == "POST":
            nova = {"id": "t-" + uuid.uuid4().hex[:8], "name": corpo["name"], "color": corpo.get("color")}
            c["etiquetas"].append(nova)
            return httpx.Response(200, json=nova)
        if caminho == "/core/v2/department":
            return httpx.Response(200, json={"items": c["equipes"]})
        if caminho == "/core/v1/department" and metodo == "POST":
            nova = {"id": "d-" + uuid.uuid4().hex[:8], "name": corpo["name"], "isDefault": corpo.get("isDefault")}
            c["equipes"].append(nova)
            return httpx.Response(200, json=nova)
        if caminho.startswith("/core/v1/company/") and caminho.endswith("/tokens") and metodo == "POST":
            self.tokens_criados.append(corpo)
            return httpx.Response(200, json={"token": "token-novo-" + uuid.uuid4().hex[:12]})
        if caminho == "/core/v1/company":
            return httpx.Response(200, json={"items": list(self.empresas.values())})
        if caminho == "/core/v1/agent":
            return httpx.Response(200, json={"items": c["usuarios"]})
        return httpx.Response(404)


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

    banco = await RepositorioPostgres.conectar(URL, max_conexoes=1)  # o servidor de teste só aceita uma
    app = FastAPI()
    app.include_router(api)
    app.include_router(api_conta)
    app.include_router(entrada)
    from app.gestao.produtos import api as api_produtos
    app.include_router(api_produtos)
    app.state.gestao = RepositorioGestao(banco._pool)
    app.state.assinador = seguranca.Assinador("segredo-de-teste")
    app.state.cfg = Configuracao(banco_url=URL, helena_url="https://api.helena.run", modelo_padrao="falso",
                                 modelo_falso=True, espera_minima_s=0, espera_maxima_s=0, espera_padrao_s=0,
                                 segundos_por_letra=0, max_reprocessos=2)
    app.state.http_ativacao = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda pedido: httpx.Response(200, json={"ok": True, "feito": "teste"})))
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


async def _criar(cliente, token=None, **extra):
    corpo = {"nome": "Conta " + uuid.uuid4().hex[:4], "id_conta_helena": str(uuid.uuid4()),
             "token_helena": token or "token-bom-" + uuid.uuid4().hex[:8], **extra}
    return await cliente.post("/api/admin/escritorios", json=corpo)


# ------------------------------------------------------------------------------------------- primeira criação
async def test_primeira_criacao_cria_etiquetas_padrao_e_escolhe_o_painel(ambiente):
    cliente, falsa, banco = ambiente
    token = "token-bom-" + uuid.uuid4().hex[:8]
    conta = falsa.conta(token)
    painel = conta["paineis"][2]
    criado = (await _criar(cliente, token, criar_etiquetas_padrao=True, id_painel=painel["id"])).json()
    id_escritorio = criado["escritorio"]["id"]
    # "📞 SDR" já existia: cria só as outras seis, uma vez.
    assert criado["etiquetas"]["ja_existiam"] == ["📞 SDR"]
    assert len(criado["etiquetas"]["criadas"]) == len(ETIQUETAS_PADRAO) - 1
    assert [e["name"] for e in conta["etiquetas"]].count("🤖 IA Desativada") == 1
    assert criado["crm"]["id_painel"] == painel["id"] and criado["crm"]["titulo_painel"] == "Jurídico"
    assert {p["titulo"] for p in criado["paineis"]} == {"🤖 CRM COMERCIAL IA", "Comercial", "Jurídico"}
    crm = await banco._pool.fetchval(
        "select config->>'id_painel' from agentesia_integracoes where id_escritorio = $1::uuid and tipo = 'crm'", id_escritorio)
    assert crm == painel["id"]
    # Repetir não duplica (idempotente pelo nome).
    from app.gestao.sincronizar_conta import garantir_etiquetas_padrao
    de_novo = await garantir_etiquetas_padrao(helena_conta.HelenaConta(token))
    assert de_novo["criadas"] == [] and len(de_novo["ja_existiam"]) == len(ETIQUETAS_PADRAO)

    # Painel que não existe: o escritório é criado, o erro volta e fica no histórico.
    criado2 = (await _criar(cliente, criar_etiquetas_padrao=False, id_painel="painel-que-nao-existe")).json()
    assert criado2["crm"] == {"erro": "painel_nao_encontrado"}
    falha = await banco._pool.fetchrow(
        "select situacao, erro from agentesia_alteracoes where id_escritorio = $1::uuid and situacao = 'erro'",
        criado2["escritorio"]["id"])
    assert falha and "painel-que-nao-existe" in falha["erro"]


# ------------------------------------------------------------------------------------------- sincronizar conta
async def test_sincronizar_conta_copia_e_marca_o_que_sumiu(ambiente):
    cliente, falsa, banco = ambiente
    token = "token-bom-" + uuid.uuid4().hex[:8]
    conta = falsa.conta(token)
    id_escritorio = (await _criar(cliente, token)).json()["escritorio"]["id"]

    feita = (await cliente.post(f"/api/admin/escritorios/{id_escritorio}/sincronizar")).json()
    assert feita["completa"] is True and feita["erros"] == {}
    assert {t: v["total"] for t, v in feita["tipos"].items()} == {
        "canal": 2, "painel": 3, "coluna": 9, "etiqueta": 2, "equipe": 1, "usuario": 1}
    assert all(v["novos"] == v["total"] and v["sumiram"] == 0 for v in feita["tipos"].values())

    recursos = (await cliente.get(f"/api/admin/escritorios/{id_escritorio}/helena-recursos")).json()
    usuario = next(r for r in recursos if r["tipo"] == "usuario")
    assert usuario["nome"] == "Dra. Paula" and usuario["id_externo"] == conta["usuarios"][0]["userId"]
    texto = json.dumps(recursos, ensure_ascii=False)
    assert "paula@escritorio.com" not in texto and "5511977776666" not in texto      # nada de e-mail/telefone de pessoa
    colunas = [r for r in recursos if r["tipo"] == "coluna" and r["id_pai_externo"] == conta["paineis"][1]["id"]]
    assert [(c["nome"], c["posicao"]) for c in colunas] == [("Novo lead", 1), ("Proposta", 2)]

    # Canais com nome e tipo cru da Helena; escritório com a data da sincronização.
    canais = await banco._pool.fetch(
        "select id_canal_helena, nome_exibicao, tipo_helena, sincronizado_em from agentesia_canais where id_escritorio = $1::uuid order by nome_exibicao",
        id_escritorio)
    assert [(c["nome_exibicao"], c["tipo_helena"]) for c in canais] == [("Oficial", "CloudAPI_WhatsApp"), ("Recepção", "ZAPI_WhatsApp")]
    assert all(c["sincronizado_em"] for c in canais)
    lista = (await cliente.get("/api/admin/escritorios")).json()
    assert next(e for e in lista if e["id"] == id_escritorio)["sincronizado_em"]
    tela = (await cliente.get("/api/integracoes", headers={"x-escritorio": id_escritorio})).json()
    assert {c["nome_exibicao"] for c in tela["canais"]} == {"Oficial", "Recepção"}

    # Some uma etiqueta e um canal; aparece uma equipe.
    vip = conta["etiquetas"].pop(1)
    canal_b = conta["canais"].pop(1)
    conta["equipes"].append({"id": "d2-" + uuid.uuid4().hex[:6], "name": "Jurídico"})
    feita = (await cliente.post(f"/api/admin/escritorios/{id_escritorio}/sincronizar")).json()
    assert feita["tipos"]["etiqueta"] == {"total": 1, "novos": 0, "sumiram": 1}
    assert feita["tipos"]["canal"] == {"total": 1, "novos": 0, "sumiram": 1}
    assert feita["tipos"]["equipe"] == {"total": 2, "novos": 1, "sumiram": 0}
    etiquetas = (await cliente.get(f"/api/admin/escritorios/{id_escritorio}/helena-recursos?tipo=etiqueta")).json()
    assert [e["nome"] for e in etiquetas] == ["📞 SDR"]
    com_sumidos = (await cliente.get(f"/api/admin/escritorios/{id_escritorio}/helena-recursos?tipo=etiqueta&sumidos=true")).json()
    sumida = next(e for e in com_sumidos if e["id_externo"] == vip["id"])
    assert sumida["sumiu_em"] is not None
    assert await banco._pool.fetchval("select ativo from agentesia_canais where id_canal_helena = $1", canal_b["id"]) is False

    # Volta: sumiu_em limpa.
    conta["etiquetas"].append(vip)
    feita = (await cliente.post(f"/api/admin/escritorios/{id_escritorio}/sincronizar")).json()
    assert feita["tipos"]["etiqueta"] == {"total": 2, "novos": 0, "sumiram": 0}
    assert len((await cliente.get(f"/api/admin/escritorios/{id_escritorio}/helena-recursos?tipo=etiqueta")).json()) == 2

    # Histórico: sincronizações com situacao ok. O gestor também vê a cópia (rota de gestão).
    historico = (await cliente.get("/api/alteracoes", headers={"x-escritorio": id_escritorio})).json()
    sincs = [h for h in historico if h["acao"] == "sincronizou"]
    assert len(sincs) == 3 and all(h["situacao"] == "ok" for h in sincs)
    gestor = (await cliente.get("/api/integracoes/helena/recursos?tipo=equipe", headers={"x-escritorio": id_escritorio})).json()
    assert len(gestor) == 2
    assert (await cliente.get(f"/api/admin/escritorios/{id_escritorio}/helena-recursos?tipo=contato")).status_code == 400


async def test_sincronizacao_parcial_nao_marca_sumido_o_tipo_que_falhou(ambiente):
    cliente, falsa, banco = ambiente
    token = "token-bom-" + uuid.uuid4().hex[:8]
    id_escritorio = (await _criar(cliente, token)).json()["escritorio"]["id"]
    assert (await cliente.post(f"/api/admin/escritorios/{id_escritorio}/sincronizar")).status_code == 200
    falsa.falhar.add("/core/v1/agent")
    feita = (await cliente.post(f"/api/admin/escritorios/{id_escritorio}/sincronizar")).json()
    assert feita["completa"] is False and feita["erros"] == {"usuario": "erro_helena"} and "usuario" not in feita["tipos"]
    usuarios = (await cliente.get(f"/api/admin/escritorios/{id_escritorio}/helena-recursos?tipo=usuario")).json()
    assert len(usuarios) == 1 and usuarios[0]["sumiu_em"] is None
    falha = await banco._pool.fetchrow(
        """select situacao, erro from agentesia_alteracoes where id_escritorio = $1::uuid and acao = 'sincronizou'
           order by criado_em desc limit 1""", id_escritorio)
    assert falha["situacao"] == "erro" and "usuario" in falha["erro"]


# ------------------------------------------------------------------------------------------- falha de admin
async def test_falha_das_acoes_de_admin_fica_registrada(ambiente):
    cliente, falsa, banco = ambiente
    # Token recusado na criação: o escritório existe e a falha fica no histórico.
    id_conta = str(uuid.uuid4())
    ruim = await _criar(cliente, "token-ruim-123", id_conta_helena=id_conta)
    assert ruim.status_code == 502
    id_escritorio = await banco._pool.fetchval(
        "select id from agentesia_escritorios where id_conta_helena = $1::uuid", id_conta)
    falha = await banco._pool.fetchrow(
        "select acao, situacao, erro from agentesia_alteracoes where id_escritorio = $1 and situacao = 'erro'", id_escritorio)
    assert falha["acao"] == "conectou" and "recusou" in falha["erro"]

    # Sincronizar com o token recusado: 502 e registro com erro.
    resposta = await cliente.post(f"/api/admin/escritorios/{id_escritorio}/sincronizar")
    assert resposta.status_code == 502
    historico = (await cliente.get("/api/alteracoes", headers={"x-escritorio": str(id_escritorio)})).json()
    sinc = next(h for h in historico if h["acao"] == "sincronizou")
    assert sinc["situacao"] == "erro" and "token_recusado" in sinc["erro"]

    # Escritório sem token nenhum: 409, também registrado.
    sem_token = (await cliente.post("/api/admin/escritorios", json={"nome": "Sem token"})).json()["escritorio"]["id"]
    assert (await cliente.post(f"/api/admin/escritorios/{sem_token}/sincronizar")).status_code == 409
    assert await banco._pool.fetchval(
        "select erro from agentesia_alteracoes where id_escritorio = $1::uuid and situacao = 'erro'", sem_token)
    assert (await cliente.post(f"/api/admin/escritorios/{uuid.uuid4()}/sincronizar")).status_code == 404


# ------------------------------------------------------------------------------------------- onboarding
async def test_onboarding_em_passos(ambiente):
    cliente, falsa, banco = ambiente
    token = "token-bom-" + uuid.uuid4().hex[:8]
    conta = falsa.conta(token)
    id_conta = str(uuid.uuid4())
    falsa.empresas[id_conta] = {
        "id": id_conta, "name": "Silva Adv", "legalName": "Silva Advocacia Ltda", "documentId": "12345678000199",
        "documentType": "CNPJ", "email": "admin@empresa.com", "phoneNumber": "5511900001111",
        "address": {"zipcode": "01000000", "address1": "Rua A", "number": "10", "city": "São Paulo", "state": "SP"},
        "createdAt": "2025-01-02T00:00:00Z", "config": {"resources": {"includedAgents": 5, "includedSessions": 1000}}}
    id_escritorio = (await _criar(cliente, token, id_conta_helena=id_conta)).json()["escritorio"]["id"]
    base = f"/api/admin/escritorios/{id_escritorio}/onboarding"

    guardado = (await cliente.get(base)).json()
    assert [p["codigo"] for p in guardado["passos"]] == [
        "token", "webhook", "equipe", "etiquetas", "painel", "painel_padrao", "canais", "sincronizacao",
        "usuarios", "zapsign", "produto"]
    assert all(p["situacao"] == "pendente" for p in guardado["passos"])

    # Conferir não muda nada na Helena.
    antes = len([p for p in falsa.pedidos if p[0] != "GET"])
    conferido = (await cliente.post(f"{base}/conferir")).json()
    assert len([p for p in falsa.pedidos if p[0] != "GET"]) == antes
    situacao = {p["codigo"]: p["situacao"] for p in conferido["passos"]}
    assert situacao == {"token": "ok", "webhook": "pendente", "canais": "ok", "etiquetas": "pendente", "equipe": "pendente",
                        "painel": "pendente", "painel_padrao": "pulado", "zapsign": "pulado", "produto": "pendente",
                        "sincronizacao": "pendente", "usuarios": "pendente"}
    assert conferido["completo"] is False and len(conferido["paineis"]) == 3

    # Avançar: cria o webhook e as etiquetas, escolhe o painel pedido, sincroniza. A equipe só porque foi marcada.
    painel = conta["paineis"][0]
    avancado = (await cliente.post(f"{base}/avancar", json={"id_painel": painel["id"], "criar_equipe_ia": True})).json()
    situacao = {p["codigo"]: p["situacao"] for p in avancado["passos"]}
    assert situacao == {"token": "ok", "webhook": "feito", "canais": "feito", "etiquetas": "feito", "equipe": "feito",
                        "painel": "feito", "painel_padrao": "pulado", "zapsign": "pulado", "produto": "pendente",
                        "sincronizacao": "feito", "usuarios": "feito"}
    assert avancado["usuarios"]["criados"] == 1 and "1 criados" in next(
        p["detalhe"] for p in avancado["passos"] if p["codigo"] == "usuarios")
    # Ids do que foi criado ou escolhido ficam no escritório (dados_helena), com as etapas ligadas aos 6 tipos.
    ids = avancado["dados_helena"]["ids"]
    assert ids["id_assinatura"] == conta["assinaturas"][0]["id"] and ids["id_painel"] == painel["id"]
    assert ids["id_departamento"] == next(e["id"] for e in conta["equipes"] if e["name"] == "🤖 Comercial IA")
    assert ids["etapas_por_tipo"] == {"SDR": f"w1-{painel['id'][3:]}", "COMERCIAL": f"w2-{painel['id'][3:]}",
                                      "CONTRATO": f"w3-{painel['id'][3:]}", "AGUARDANDO_ASSINATURA": f"w4-{painel['id'][3:]}",
                                      "CONTRATO_ASSINADO": f"w5-{painel['id'][3:]}", "DESQUALIFICADO": f"w6-{painel['id'][3:]}"}
    assert set(ids["etiquetas"]) == {n for n, _ in ETIQUETAS_PADRAO}
    criada_tag = next(e for e in conta["etiquetas"] if e["name"] == "✅ Contrato Assinado")
    assert criada_tag["color"] == "GREEN_600"
    # Dados da empresa (token de parceiro), sem e-mail nem telefone.
    conta_helena = avancado["dados_helena"]["conta"]
    assert conta_helena["documento"] == "12345678000199" and conta_helena["endereco"]["city"] == "São Paulo"
    assert conta_helena["recursos"] == {"includedAgents": 5, "includedSessions": 1000}
    assert conta_helena["email_contato"] == "admin@empresa.com"                       # e-mail de contato DA EMPRESA
    # Telefone de contato DA EMPRESA entra desde a tela Contas (pedido do dono); dados de pessoas, não.
    assert conta_helena["telefone"] == "5511900001111" and conta_helena["documento_formatado"] == "12.345.678/0001-99"
    assert "paula@escritorio.com" not in json.dumps(avancado["dados_helena"], ensure_ascii=False)
    assert ids["token_final"] == token[-4:]
    assert len(conta["assinaturas"]) == 1 and len(conta["etiquetas"]) == len(ETIQUETAS_PADRAO) + 1
    guardado = (await cliente.get(base)).json()
    # Primeiro produto não trava a conta: token, webhook, etiquetas e painel prontos = onboarding concluído.
    assert guardado["passos"][1]["situacao"] == "feito" and guardado["concluido_em"] and guardado["sincronizado_em"]
    historico = (await cliente.get("/api/alteracoes", headers={"x-escritorio": id_escritorio})).json()
    assert any(h["acao"] == "onboarding" and h["situacao"] == "ok" for h in historico)

    # Primeiro produto: o agente pausado passa pela checagem da ativação (ativacao.preparar).
    canais = (await cliente.get("/api/integracoes", headers={"x-escritorio": id_escritorio})).json()["canais"]
    agente = await cliente.post("/api/agentes", json={"nome": "Júlia", "id_canal": canais[0]["id"]},
                                headers={"x-escritorio": id_escritorio})
    assert agente.status_code == 200, agente.text
    conferido = (await cliente.post(f"{base}/conferir")).json()
    situacao = {p["codigo"]: p["situacao"] for p in conferido["passos"]}
    assert situacao["webhook"] == "ok" and situacao["etiquetas"] == "ok" and situacao["painel"] == "ok"
    produto = next(p for p in conferido["passos"] if p["codigo"] == "produto")
    assert produto["situacao"] == "aviso" and "Júlia" in produto["detalhe"]
    assert {p["codigo"] for p in conferido["ativacao"]["passos"]} >= {"helena", "canal", "webhook", "teste"}

    # Ligado: o onboarding fica completo e guarda quando concluiu.
    await banco._pool.execute("update agentesia_agentes set situacao = 'ativo' where id = $1::uuid", agente.json()["id"])
    conferido = (await cliente.post(f"{base}/conferir")).json()
    assert conferido["completo"] is True and conferido["concluido_em"]
    assert (await cliente.post(f"{base}/avancar", json={"passos": ["inventado"]})).status_code == 400


async def test_onboarding_escolhe_o_painel_unico_e_avisa_sem_painel(ambiente):
    cliente, falsa, banco = ambiente
    token = "token-bom-" + uuid.uuid4().hex[:8]
    conta = falsa.conta(token)
    conta["paineis"] = conta["paineis"][:1]
    id_escritorio = (await _criar(cliente, token)).json()["escritorio"]["id"]
    feito = (await cliente.post(f"/api/admin/escritorios/{id_escritorio}/onboarding/avancar",
                                json={"passos": ["painel"]})).json()
    painel = next(p for p in feito["passos"] if p["codigo"] == "painel")
    assert painel["situacao"] == "feito" and "CRM COMERCIAL IA" in painel["detalhe"] and "6/6" in painel["detalhe"]
    # Só o painel foi aplicado: webhook e etiquetas continuam só conferidos.
    assert conta["assinaturas"] == [] and len(conta["etiquetas"]) == 2

    token2 = "token-bom-" + uuid.uuid4().hex[:8]
    falsa.conta(token2)["paineis"] = []
    id2 = (await _criar(cliente, token2)).json()["escritorio"]["id"]
    conferido = (await cliente.post(f"/api/admin/escritorios/{id2}/onboarding/conferir")).json()
    painel = next(p for p in conferido["passos"] if p["codigo"] == "painel")
    assert painel["situacao"] == "erro" and "não cria painel" in painel["detalhe"]


# ------------------------------------------------------------------------------------------- etapa e telefone
async def _cenario_lead(banco):
    pool = banco._pool
    id_escritorio = str(await pool.fetchval("insert into agentesia_escritorios (nome) values ('Etapas') returning id"))
    numero = "55119" + str(uuid.uuid4().int)[:8]
    id_canal = str(await pool.fetchval(
        "insert into agentesia_canais (id_escritorio, numero_normalizado, id_canal_helena) values ($1::uuid, $2, $3) returning id",
        id_escritorio, numero, "ch-" + uuid.uuid4().hex[:8]))
    id_agente = str(await pool.fetchval(
        "insert into agentesia_agentes (id_escritorio, id_canal, nome) values ($1::uuid, $2::uuid, 'Júlia') returning id",
        id_escritorio, id_canal))
    etapas = []
    for ordem, codigo in enumerate(["sdr", "closer", "assinatura"], 1):
        id_etapa = str(await pool.fetchval(
            "insert into agentesia_agente_etapas (id_agente, codigo, ordem, principal) values ($1::uuid, $2, $3, $4) returning id",
            id_agente, codigo, ordem, ordem == 1))
        etapas.append(Etapa(id=id_etapa, codigo=codigo, principal=ordem == 1))
    return (Escritorio(id=id_escritorio, nome="Etapas"), Canal(id=id_canal, id_escritorio=id_escritorio, numero_normalizado=numero),
            Agente(id=id_agente, id_escritorio=id_escritorio, id_canal=id_canal, nome="Júlia", etapas=etapas))


async def test_historico_de_troca_de_etapa(ambiente):
    cliente, _falsa, banco = ambiente
    escritorio, canal, agente = await _cenario_lead(banco)
    lead = await banco.achar_ou_criar_lead(escritorio=escritorio, canal=canal, agente=agente,
                                           telefone="5511955554444", id_sessao="s1")
    # Equipe pelo painel (rota de conversa) -> 'equipe'.
    resposta = await cliente.post(f"/api/conversas/{lead.id}/ia", json={"acao": "trocar_etapa", "etapa": "closer"},
                                  headers={"x-escritorio": escritorio.id})
    assert resposta.json()["mudou"] is True
    # Contrato gerado (mesma função da fila de ações) -> 'contrato'.
    assert await contrato_servico.mover_lead_para_etapa(banco._pool, lead.id, "assinatura") is True
    # A IA troca durante o turno (sem origem declarada) -> 'ia', com o turno.
    id_turno = await banco.abrir_turno(lead=lead, modo="teste", etapa_antes="assinatura")
    await banco.atualizar_lead(lead.id, id_etapa=agente.etapas[1].id)
    await banco.fechar_turno(id_turno, situacao="respondido", motivo=None, etapa_depois="closer", contexto=None, resposta=None)
    # Sem mudança de etapa: nada no histórico.
    await banco.atualizar_lead(lead.id, estado="pausado")
    linhas = await banco._pool.fetch(
        "select etapa_de, etapa_para, origem, id_turno from agentesia_lead_etapas where id_lead = $1::uuid order by criado_em",
        lead.id)
    assert [(l["etapa_de"], l["etapa_para"], l["origem"]) for l in linhas] == [
        (None, "sdr", "entrada"), ("sdr", "closer", "equipe"), ("closer", "assinatura", "contrato"), ("assinatura", "closer", "ia")]
    assert str(linhas[3]["id_turno"]) == id_turno and linhas[1]["id_turno"] is None


async def test_contato_sem_o_nono_digito_e_o_mesmo_lead(ambiente):
    _cliente, _falsa, banco = ambiente
    assert chave_telefone("5511988887777") == chave_telefone("551188887777") == "551188887777"
    assert chave_telefone("14155550123") is None and chave_telefone(None) is None
    escritorio, canal, agente = await _cenario_lead(banco)
    com_9 = await banco.achar_ou_criar_lead(escritorio=escritorio, canal=canal, agente=agente,
                                            telefone="5511988887777", id_sessao="s1", nome="Maria")
    sem_9 = await banco.achar_ou_criar_lead(escritorio=escritorio, canal=canal, agente=agente,
                                            telefone="551188887777", id_sessao="s2")
    assert sem_9.id == com_9.id and sem_9.novo is False and sem_9.telefone == "5511988887777"
    assert await banco._pool.fetchval("select count(*) from agentesia_contatos where id_escritorio = $1::uuid", escritorio.id) == 1
    # O número exato sempre ganha.
    exato = await banco.achar_ou_criar_lead(escritorio=escritorio, canal=canal, agente=agente,
                                            telefone="5511988887777", id_sessao="s3")
    assert exato.id == com_9.id

    # Dois contatos com a mesma chave (dados antigos): não escolhe ao acaso, cria/usa o exato.
    await banco._pool.execute(
        "insert into agentesia_contatos (id_escritorio, telefone_normalizado) values ($1::uuid, '5521977776666'), ($1::uuid, '5521877776666')",
        escritorio.id)
    outro = await banco.achar_ou_criar_lead(escritorio=escritorio, canal=canal, agente=agente,
                                            telefone="552177776666", id_sessao="s4")
    assert outro.telefone == "552177776666" and outro.novo is True

    # Sem a coluna (banco antes da 006), o caminho antigo continua.
    banco._telefone_chave = False
    antigo = await banco.achar_ou_criar_lead(escritorio=escritorio, canal=canal, agente=agente,
                                             telefone="551133332222", id_sessao="s5")
    assert antigo.telefone == "551133332222"


async def test_onboarding_cria_o_token_da_conta_e_reaproveita(ambiente):
    cliente, falsa, banco = ambiente
    id_conta = str(uuid.uuid4())
    criado = (await cliente.post("/api/admin/escritorios", json={"nome": "Sem token ainda", "id_conta_helena": id_conta})).json()
    id_escritorio = criado["escritorio"]["id"]
    base = f"/api/admin/escritorios/{id_escritorio}/onboarding"
    conferido = (await cliente.post(f"{base}/conferir")).json()
    assert conferido["passos"][0]["situacao"] == "erro" and falsa.tokens_criados == []        # conferir não cria
    feito = (await cliente.post(f"{base}/avancar", json={"passos": ["token"]})).json()
    token = feito["passos"][0]
    assert token["situacao"] == "feito" and "IA LawChat" in token["detalhe"]
    assert falsa.tokens_criados == [{"name": "IA LawChat"}]
    integracao = await banco._pool.fetchrow(
        "select final_segredo, config::text as config from agentesia_integracoes where id_escritorio = $1::uuid and tipo = 'helena'",
        id_escritorio)
    assert integracao["final_segredo"] and "token-novo" not in integracao["config"]            # só o final no banco
    assert feito["dados_helena"]["ids"]["token_final"] == integracao["final_segredo"]
    # Avançar de novo reaproveita: não cria outro token.
    de_novo = (await cliente.post(f"{base}/avancar", json={"passos": ["token"]})).json()
    assert de_novo["passos"][0]["situacao"] == "ok" and len(falsa.tokens_criados) == 1
