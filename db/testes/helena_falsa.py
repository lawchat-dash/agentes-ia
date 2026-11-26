"""Helena de mentira para testar o painel no navegador, sem tocar na Helena de verdade.

Rodar: .venv/Scripts/python -m uvicorn db.testes.helena_falsa:app --port 8020
e apontar AGENTESIA_HELENA_URL=http://127.0.0.1:8020 no servidor do painel.
Aceita qualquer token, menos os que começam com "ruim".
"""

import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Helena de mentira")
ASSINATURAS: list[dict] = []
CARDS: list[dict] = []
NOTAS: list[dict] = []


def _token_ruim(pedido: Request) -> bool:
    return pedido.headers.get("authorization", "").lower().startswith("bearer ruim")


@app.middleware("http")
async def conferir_token(pedido: Request, seguir):
    if _token_ruim(pedido):
        return JSONResponse({"error": True, "text": "token inválido"}, status_code=401)
    return await seguir(pedido)


@app.get("/chat/v1/channel")
async def canais():
    return [
        {"id": "canal-demo-1", "active": True, "type": "ZAPI_WhatsApp", "number": "5511912345678",
         "numberFormatted": "(11) 91234-5678", "identity": {"displayName": "Escritório Demo"}},
        {"id": "canal-demo-2", "active": True, "type": "CloudAPI_WhatsApp", "number": "5511987654321",
         "numberFormatted": "(11) 98765-4321", "identity": {"displayName": "Escritório Demo Oficial"}},
    ]


@app.get("/core/v1/webhook/subscription")
async def listar_assinaturas():
    return [{**a, "events": [{"event": e, "description": e} for e in a["events"]]} for a in ASSINATURAS]


@app.post("/core/v1/webhook/subscription")
async def criar_assinatura(pedido: Request):
    corpo = await pedido.json()
    assinatura = {"id": str(uuid.uuid4()), **corpo}
    ASSINATURAS.append(assinatura)
    return assinatura


@app.put("/core/v1/webhook/subscription/{id_assinatura}")
async def alterar_assinatura(id_assinatura: str, pedido: Request):
    corpo = await pedido.json()
    for a in ASSINATURAS:
        if a["id"] == id_assinatura:
            a.update({k: v for k, v in corpo.items() if k != "fields"})
            return a
    return JSONResponse({"error": True}, status_code=404)


@app.get("/crm/v2/panel")
async def paineis():
    return {"items": [{"id": "painel-demo", "title": "Comercial", "type": "SALES", "steps": [
        {"id": "col-1", "title": "Novos leads", "position": 1, "isInitial": True},
        {"id": "col-2", "title": "Negociação", "position": 2},
        {"id": "col-3", "title": "Contrato", "position": 3},
        {"id": "col-4", "title": "Desqualificados", "position": 4},
        {"id": "col-5", "title": "Análise da equipe", "position": 5},
    ]}]}


@app.get("/core/v1/tag")
async def etiquetas():
    return [{"id": "t1", "name": "📞 SDR", "color": "BLUE_500"}, {"id": "t2", "name": "🛒 Comercial", "color": "GREEN_500"}]


@app.get("/core/v2/department")
async def equipes():
    return {"items": [{"id": "equipe-1", "name": "Comercial", "isDefault": True}, {"id": "equipe-2", "name": "Jurídico"}]}


@app.get("/core/v1/agent/{id_usuario}")
async def atendente(id_usuario: str):
    if id_usuario == "11111111-1111-1111-1111-111111111111":
        return {"id": "agente-1", "userId": id_usuario, "name": "Dra. Paula Demo", "email": "paula@demo.com"}
    return JSONResponse({"error": True}, status_code=404)


@app.get("/core/v1/agent")
async def atendentes():
    return {"items": [{"id": "agente-1", "userId": "11111111-1111-1111-1111-111111111111", "name": "Dra. Paula Demo",
                       "email": "paula@demo.com"}]}


@app.get("/chat/v2/session/{id_sessao}")
async def sessao(id_sessao: str):
    return {"id": id_sessao, "contactId": "contato-demo-1", "status": "IN_PROGRESS"}


@app.get("/crm/v2/panel/card")
async def cards(ContactId: str = ""):
    return {"items": [c for c in CARDS if ContactId in c.get("contactIds", [])]}


@app.post("/crm/v2/panel/card")
async def criar_card(pedido: Request):
    corpo = await pedido.json()
    card = {"id": "card-" + uuid.uuid4().hex[:6], **corpo, "status": "OPEN"}
    CARDS.append(card)
    return card


@app.put("/crm/v3/panel/card/{id_card}")
async def mover_card(id_card: str, pedido: Request):
    corpo = await pedido.json()
    for c in CARDS:
        if c["id"] == id_card:
            c["stepId"] = corpo.get("stepId")
    return {"id": id_card}


@app.post("/core/v1/contact/{id_contato}/tags")
async def tags(id_contato: str):
    return {"id": id_contato}


@app.post("/chat/v1/session/{id_sessao}/note")
async def nota(id_sessao: str, pedido: Request):
    NOTAS.append({"sessao": id_sessao, **(await pedido.json())})
    return {"id": str(uuid.uuid4()), "type": "NOTE"}


@app.put("/chat/v1/session/{id_sessao}/transfer")
async def transferir(id_sessao: str):
    return {"id": id_sessao}


@app.post("/chat/v1/session/{id_sessao}/message")
async def mensagem(id_sessao: str):
    return {"id": str(uuid.uuid4()), "sessionId": id_sessao, "status": "QUEUED"}


@app.post("/auth/v1/login/authenticate")
async def login_integrado(pedido: Request):
    """Login integrado: devolve um link de uso único para a 'tela da Helena' de mentira."""
    corpo = await pedido.json()
    if corpo.get("email") != "paula@demo.com" and not str(corpo.get("email", "")).endswith("@lawchat.local"):
        return JSONResponse({"error": True, "text": "usuário não encontrado"}, status_code=404)
    destino = corpo.get("redirectUrl") or "/chat2/sessions"
    codigo = uuid.uuid4().hex
    CODIGOS[codigo] = destino
    return {"userId": "agente-1", "tenantId": corpo.get("tenantId"),
            "urlRedirect": f"http://127.0.0.1:8020/auth/external-login?code={codigo}", "expiresIn": "2099-01-01T00:00:00Z"}


CODIGOS: dict[str, str] = {}


@app.get("/auth/external-login")
async def entrada_externa(code: str = ""):
    from fastapi.responses import HTMLResponse
    destino = CODIGOS.pop(code, None)
    if not destino:
        return HTMLResponse("<h1>Código já usado ou inválido</h1>", status_code=401)
    return HTMLResponse(f"<html><body style='font-family:sans-serif;padding:24px'><h2>Helena (teste)</h2>"
                        f"<p>Logado. Destino: <code>{__import__('html').escape(destino)}</code></p></body></html>")


# ---------------------------------------------------------------- contas do parceiro (token pn_ de mentira)
def _endereco(cep: str, rua: str, numero: str, bairro: str, cidade: str, uf: str) -> dict:
    return {"zipcode": cep, "address1": rua, "number": numero, "neighborhood": bairro, "city": cidade, "state": uf}


# A primeira é a do escritório de demonstração. Documentos e telefones são inventados.
EMPRESAS = [
    {"id": "00000000-0000-4000-8000-000000000001", "name": "Escritório Demo", "active": True, "email": "contato@demo.com",
     "legalName": "Escritório Demo Advocacia Ltda", "documentId": "11222333000181", "documentType": "CNPJ",
     "phoneNumber": "5511912345678", "address": _endereco("01310100", "Av. Paulista", "1000", "Bela Vista", "São Paulo", "sp"),
     "createdAt": "2025-03-10T12:00:00Z", "pictureUrl": "",  # sem foto: a tela mostra a inicial
     "config": {"resources": {"includedAgents": 5, "includedSessions": 1000}}},
    {"id": "11111111-0000-4000-8000-000000000002", "name": "LawChat (teste)", "active": True, "email": "parceiro@lawchat.test",
     "legalName": "LawChat Tecnologia Ltda (teste)", "documentId": "44555666000102", "documentType": "CNPJ",
     "phoneNumber": "5511900000001", "pictureUrl": "", "address": _endereco("04538133", "Av. Brigadeiro Faria Lima", "3477", "Itaim Bibi", "São Paulo", "SP")},
    {"id": "44444444-0000-4000-8000-000000000005", "name": "Silva & Souza Advocacia (teste)", "active": True,
     "email": "contato@silvasouza.test", "legalName": "Silva e Souza Sociedade de Advogados", "documentId": "77888999000155",
     "documentType": "CNPJ", "phoneNumber": "5531988887777", "pictureUrl": "http://inseguro.test/foto.png",
     "address": _endereco("30130010", "Rua da Bahia", "250", "Centro", "Belo Horizonte", "MG")},
    {"id": "22222222-0000-4000-8000-000000000003", "name": "Previdência Fácil (teste)", "active": True, "email": "oi@previfacil.test",
     "legalName": "Maria Previdência", "documentId": "12345678909", "documentType": "CPF", "phoneNumber": "5521977776666",
     "address": _endereco("20040002", "Rua da Assembleia", "10", "Centro", "Rio de Janeiro", "RJ")},
    {"id": "33333333-0000-4000-8000-000000000004", "name": "Conta cancelada (teste)", "active": False, "email": None,
     "legalName": "Conta Cancelada ME", "documentId": "99888777000166", "documentType": "CNPJ", "phoneNumber": None, "address": {}},
]


@app.get("/core/v1/company")
async def empresas(PageNumber: int = 1, PageSize: int = 50, SearchableText: str = ""):
    itens = [e for e in EMPRESAS if SearchableText.lower() in e["name"].lower()]
    inicio = (PageNumber - 1) * PageSize
    return {"items": itens[inicio:inicio + PageSize], "totalItems": len(itens)}


@app.post("/core/v1/company/{id_empresa}/tokens")
async def criar_token_empresa(id_empresa: str):
    if not any(e["id"] == id_empresa for e in EMPRESAS):
        return JSONResponse({"error": True}, status_code=404)
    return {"token": "pn_conta_teste_" + uuid.uuid4().hex[:12]}


@app.post("/core/v1/tag")
async def criar_etiqueta(pedido: Request):
    corpo = await pedido.json()
    return {"id": "t-" + uuid.uuid4().hex[:6], "name": corpo.get("name"), "color": corpo.get("color")}


@app.post("/core/v1/department")
async def criar_equipe(pedido: Request):
    corpo = await pedido.json()
    return {"id": "equipe-" + uuid.uuid4().hex[:6], "name": corpo.get("name"), "isDefault": corpo.get("isDefault", False)}


@app.get("/_estado")
async def estado():
    """Para conferir o que o sistema fez na 'Helena'."""
    return {"assinaturas": ASSINATURAS, "cards": CARDS, "notas": NOTAS}


# ---------------------------------------------------------------- ZapSign de mentira (AGENTESIA_ZAPSIGN_URL_TESTE)
MODELOS_ZAPSIGN = [
    {"token": "modelo-auxilio-acidente", "name": "Contrato Auxílio-Acidente (teste)"},
    {"token": "modelo-loas", "name": "Contrato BPC/LOAS (teste)"},
    {"token": "modelo-aposentadoria", "name": "Contrato Aposentadoria (teste)"},
]


@app.get("/api/v1/templates/")
async def zapsign_modelos():
    return {"count": len(MODELOS_ZAPSIGN), "next": None, "previous": None, "results": MODELOS_ZAPSIGN}


WEBHOOKS_ZAPSIGN: list[dict] = []


@app.post("/api/v1/user/company/webhook/")
async def zapsign_criar_webhook(pedido: Request):
    corpo = await pedido.json()
    WEBHOOKS_ZAPSIGN.append(corpo)
    return {"id": len(WEBHOOKS_ZAPSIGN)}


@app.get("/api/v1/templates/{token}/")
async def zapsign_modelo(token: str):
    modelo = next((m for m in MODELOS_ZAPSIGN if m["token"] == token), None)
    if not modelo:
        return JSONResponse({"detail": "não encontrado"}, status_code=404)
    nomes = ["NOME COMPLETO", "CPF", "RG", "ESTADO CIVIL", "PROFISSAO", "ENDERECO", "NUMERO", "BAIRRO", "CIDADE", "UF", "CEP", "EMAIL"]
    return {**modelo, "inputs": [{"variable": "{{" + n + "}}", "label": n.title()} for n in nomes]}
