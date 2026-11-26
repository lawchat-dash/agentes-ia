"""Primeiros passos (Início e Contas), saúde do número (selo e "Testar conexão") e o rastro da conversa (B11).

Rotas: GET /api/inicio/primeiros-passos, GET /api/admin/escritorios/primeiros-passos, GET /api/saude/numeros,
POST /api/saude/numeros/{id_canal}/testar e os campos `funil` e `rastro` de GET /api/conversas/{id}.
Só roda com AGENTESIA_TESTE_PG_URL (ver tests/test_postgres.py). A Helena é simulada como em test_gestao.
"""

import json
import os
import uuid
from pathlib import Path

import pytest

from app.gestao import rastro as rastro_mod
from app.gestao import saude_numero
from tests.test_gestao import _entrar, ambiente  # noqa: F401  (fixture)

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
RAIZ = Path(__file__).resolve().parent.parent
pg = pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")


async def _conta(cliente, nome):
    escritorio = (await cliente.post("/api/admin/escritorios", json={
        "nome": nome, "id_conta_helena": str(uuid.uuid4()), "token_helena": f"token-bom-{uuid.uuid4().hex[:8]}"})).json()["escritorio"]
    h = {"x-escritorio": escritorio["id"]}
    canais = (await cliente.get("/api/integracoes", headers=h)).json()["canais"]
    return escritorio["id"], h, canais


async def _lead(pool, id_escritorio, id_canal, id_agente, telefone):
    contato = await pool.fetchval(
        "insert into agentesia_contatos (id_escritorio, nome, telefone_normalizado) values ($1::uuid, 'Maria', $2) returning id",
        id_escritorio, telefone)
    etapa = await pool.fetchval(
        "select id from agentesia_agente_etapas where id_agente = $1::uuid order by ordem limit 1", id_agente)
    return str(await pool.fetchval(
        """insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_agente, id_etapa, estado)
           values ($1::uuid, $2, $3::uuid, $4::uuid, $5, 'ativo') returning id""",
        id_escritorio, contato, id_canal, id_agente, etapa))


async def _mensagem_do_lead(pool, id_escritorio, id_lead, ha: str):
    await pool.execute(
        f"""insert into agentesia_mensagens (id_escritorio, id_lead, autor, tipo, texto, enviada_em, situacao_envio)
            values ($1::uuid, $2::uuid, 'lead', 'texto', 'oi', now() - interval '{ha}', 'recebida')""", id_escritorio, id_lead)


# ------------------------------------------------------------------ sem banco
def test_selo_do_numero():
    from datetime import datetime, timedelta, timezone
    agora = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)
    assert saude_numero.selo(False, None, agora) == {"tipo": "sem_numero", "minutos": None}
    assert saude_numero.selo(True, None, agora) == {"tipo": "sem_mensagens", "minutos": None}
    assert saude_numero.selo(True, agora - timedelta(minutes=3), agora) == {"tipo": "recebendo", "minutos": 3}
    assert saude_numero.selo(True, agora - timedelta(days=3), agora) == {"tipo": "parado", "minutos": 3 * 24 * 60}


def test_eventos_novos_tem_nome_legivel_no_rastro_e_na_tela():
    tipos = (RAIZ / "painel" / "src" / "components" / "conversas" / "tipos.ts").read_text(encoding="utf-8")
    for tipo in ("formato_invalido", "fora_do_tema", "tentativa_de_manipular", "trocas_demais", "portao_de_fatos",
                 "lead_quente", "lead_parado"):
        assert rastro_mod.tipo_do_evento(tipo) is not None, tipo
        assert rastro_mod.titulo_do_evento(tipo) != tipo, tipo
        assert f"{tipo}:" in tipos, tipo
    assert rastro_mod.tipo_do_evento("trava_promessa_valor") == "barreira"
    assert rastro_mod.titulo_do_evento("trava_promessa_valor") == "Trava: promessa valor"
    assert rastro_mod.tipo_do_evento("etapa_trocada") is None       # vira passagem, não item solto


def test_menu_um_caminho_so():
    main = (RAIZ / "painel" / "src" / "main.tsx").read_text(encoding="utf-8")
    estrutura = (RAIZ / "painel" / "src" / "componentes" / "Estrutura.tsx").read_text(encoding="utf-8")
    inicio = (RAIZ / "painel" / "src" / "telas" / "Inicio.tsx").read_text(encoding="utf-8")
    assert '{ para: "/meus-produtos", rotulo: "Meus agentes"' in estrutura
    assert 'rotulo: "Agentes"' not in estrutura and 'rotulo: "Meus Produtos"' not in estrutura
    assert '<Route path="/agentes" element={<Navigate to="/meus-produtos" replace />} />' in main
    assert 'path="/agentes/:id/:secao"' in main
    assert "Copie o token na Helena" not in inicio and "Fale com a equipe LawChat para habilitar" in inicio


# ------------------------------------------------------------------ com banco
@pg
async def test_primeiros_passos_se_marcam_sozinhos(ambiente):  # noqa: F811
    cliente, _simulada, email_admin, banco = ambiente
    pool = banco._pool
    await _entrar(cliente, email_admin, "senha-admin-123")
    id_escritorio, h, canais = await _conta(cliente, "Passos Ltda")

    r = (await cliente.get("/api/inicio/primeiros-passos", headers=h)).json()
    passos = {p["codigo"]: p for p in r["passos"]}
    assert [p["codigo"] for p in r["passos"]] == ["conta", "whatsapp", "produto", "zapsign", "followup", "conversa", "saldo"]
    assert r["total"] == 7 and all(p["para"] or p["situacao"] == "feito" for p in r["passos"])
    assert passos["whatsapp"]["situacao"] == "feito"
    assert passos["produto"]["situacao"] == "pendente" and passos["produto"]["para"] == "/biblioteca"
    assert passos["zapsign"]["situacao"] == "nao_se_aplica"            # nenhum agente gera contrato
    assert passos["conversa"]["situacao"] == "pendente" and passos["conversa"]["para"] == "/atendimento"
    assert r["completo"] is False and r["proximo"] in passos
    antes = r["feitos"]

    # Conta sem a marca da equipe e sem a Helena: "Fale com a equipe LawChat para habilitar".
    await pool.execute("""update agentesia_escritorios set config = jsonb_set(coalesce(config, '{}'::jsonb), '{criar_agente}',
                          '{"habilitado": false}'::jsonb) where id = $1::uuid""", id_escritorio)
    conta = next(p for p in (await cliente.get("/api/inicio/primeiros-passos", headers=h)).json()["passos"] if p["codigo"] == "conta")
    assert conta["situacao"] == "pendente" and "Fale com a equipe LawChat para habilitar" in conta["detalhe"]
    await pool.execute("""update agentesia_escritorios set config = jsonb_set(config, '{criar_agente}', '{"habilitado": true}'::jsonb)
                          where id = $1::uuid""", id_escritorio)

    # Agente ligado, gerando contrato e sem follow-up; e a primeira mensagem de um lead.
    canal = next(c for c in canais if c["tipo"] != "oficial")
    agente = (await cliente.post("/api/agentes", headers=h, json={"nome": "Júlia", "id_canal": canal["id"]})).json()
    await pool.execute("""update agentesia_agentes set situacao = 'ativo',
                          config = jsonb_set(config, '{funcoes}', '{"contrato_zapsign": true}'::jsonb) where id = $1::uuid""", agente["id"])
    id_lead = await _lead(pool, id_escritorio, canal["id"], agente["id"], "5511" + str(uuid.uuid4().int)[:9])
    await _mensagem_do_lead(pool, id_escritorio, id_lead, "1 minute")
    r = (await cliente.get("/api/inicio/primeiros-passos", headers=h)).json()
    passos = {p["codigo"]: p for p in r["passos"]}
    assert passos["conta"]["situacao"] == "feito"
    assert passos["produto"]["situacao"] == "feito" and "Júlia" in passos["produto"]["detalhe"]
    assert passos["zapsign"]["situacao"] == "pendente" and passos["zapsign"]["para"] == "/minha-conta?aba=integracoes"
    assert passos["followup"]["situacao"] == "pendente" and passos["followup"]["para"] == f"/agentes/{agente['id']}/followup"
    assert passos["conversa"]["situacao"] == "feito"
    assert r["feitos"] >= antes + 1

    # Contas do superadmin: a mesma conta, com o "X/7" e os que faltam.
    todos = (await cliente.get("/api/admin/escritorios/primeiros-passos")).json()
    assert todos[id_escritorio]["feitos"] == r["feitos"] and todos[id_escritorio]["total"] == 7
    assert any(f.startswith("ZapSign conectada") for f in todos[id_escritorio]["faltam"])

    # Só a equipe LawChat vê o progresso de todas; o gestor vê o próprio Início.
    email = f"gestor-{uuid.uuid4().hex[:6]}@passos.com"
    senha = (await cliente.post("/api/escritorio/usuarios", headers=h, json={"email": email, "nome": "Gestora"})).json()["senha_provisoria"]
    await cliente.post("/api/sair")
    await _entrar(cliente, email, senha)
    assert (await cliente.get("/api/admin/escritorios/primeiros-passos")).status_code == 403
    assert (await cliente.get("/api/inicio/primeiros-passos")).json()["feitos"] == r["feitos"]


@pg
async def test_saude_do_numero_e_testar_conexao(ambiente):  # noqa: F811
    cliente, simulada, email_admin, banco = ambiente
    pool = banco._pool
    await _entrar(cliente, email_admin, "senha-admin-123")
    id_escritorio, h, canais = await _conta(cliente, "Saúde Ltda")
    comum = next(c for c in canais if c["tipo"] != "oficial")
    oficial = next(c for c in canais if c["tipo"] == "oficial")
    a1 = (await cliente.post("/api/agentes", headers=h, json={"nome": "Júlia", "id_canal": comum["id"]})).json()
    a2 = (await cliente.post("/api/agentes", headers=h, json={"nome": "Oficial", "id_canal": oficial["id"]})).json()

    saude = (await cliente.get("/api/saude/numeros", headers=h)).json()
    por_agente = {a["id"]: a for a in saude["agentes"]}
    assert por_agente[a1["id"]]["selo"]["tipo"] == "sem_mensagens"
    assert por_agente[a2["id"]]["tipo"] == "oficial" and "24 h" in por_agente[a2["id"]]["aviso_tipo"]
    assert por_agente[a1["id"]]["aviso_tipo"] is None

    l1 = await _lead(pool, id_escritorio, comum["id"], a1["id"], "5511" + str(uuid.uuid4().int)[:9])
    await _mensagem_do_lead(pool, id_escritorio, l1, "5 minutes")
    await _mensagem_do_lead(pool, id_escritorio, l1, "2 hours")
    l2 = await _lead(pool, id_escritorio, oficial["id"], a2["id"], "5521" + str(uuid.uuid4().int)[:9])
    await _mensagem_do_lead(pool, id_escritorio, l2, "3 days")
    saude = (await cliente.get("/api/saude/numeros", headers=h)).json()
    por_agente = {a["id"]: a for a in saude["agentes"]}
    assert por_agente[a1["id"]]["selo"]["tipo"] == "recebendo" and 4 <= por_agente[a1["id"]]["selo"]["minutos"] <= 6
    assert por_agente[a2["id"]]["selo"]["tipo"] == "parado" and por_agente[a2["id"]]["selo"]["minutos"] >= 3 * 24 * 60
    por_canal = {c["id"]: c for c in saude["canais"]}
    assert por_canal[comum["id"]]["selo"]["tipo"] == "recebendo" and por_canal[comum["id"]]["nome_agente"] == "Júlia"

    # Testar conexão: passo a passo, só lendo. Antes do webhook, o passo dele avisa; depois de conectar, fica ok.
    simulada.pedidos.clear()
    teste = (await cliente.post(f"/api/saude/numeros/{comum['id']}/testar", headers=h)).json()
    codigos = [p["codigo"] for p in teste["passos"]]
    assert codigos == ["helena", "canal", "webhook", "alcance", "mensagens"]
    situacao = {p["codigo"]: p["situacao"] for p in teste["passos"]}
    assert situacao["helena"] == "ok" and situacao["canal"] == "ok" and situacao["webhook"] == "aviso"
    assert situacao["mensagens"] == "ok" and teste["ok"] is True
    assert all("Helena" not in p["detalhe"] for p in teste["passos"])
    assert {m for m, _ in simulada.pedidos} == {"GET"}                 # nada foi criado nem mudado na Helena
    await cliente.post("/api/integracoes/helena/conectar", headers=h)
    teste = (await cliente.post(f"/api/saude/numeros/{oficial['id']}/testar", headers=h)).json()
    situacao = {p["codigo"]: p["situacao"] for p in teste["passos"]}
    assert situacao["webhook"] == "ok" and situacao["mensagens"] == "aviso" and teste["tipo"] == "oficial"

    # Número que sumiu da Helena: o passo do número dá erro e o teste não passa.
    await pool.execute("update agentesia_canais set id_canal_helena = 'sumiu-' || id_canal_helena where id = $1::uuid", comum["id"])
    teste = (await cliente.post(f"/api/saude/numeros/{comum['id']}/testar", headers=h)).json()
    assert teste["ok"] is False and next(p for p in teste["passos"] if p["codigo"] == "canal")["situacao"] == "erro"

    # Agente sem número: "sem número". Número de outro escritório: 404.
    await pool.execute("update agentesia_agentes set id_canal = null where id = $1::uuid", a2["id"])
    saude = (await cliente.get("/api/saude/numeros", headers=h)).json()
    assert {a["id"]: a for a in saude["agentes"]}[a2["id"]]["selo"]["tipo"] == "sem_numero"
    _outro, h_outro, _ = await _conta(cliente, "Outro Ltda")
    assert (await cliente.post(f"/api/saude/numeros/{comum['id']}/testar", headers=h_outro)).status_code == 404
    assert (await cliente.post("/api/saude/numeros/nao-e-id/testar", headers=h)).status_code == 404


@pg
async def test_rastro_da_conversa(ambiente):  # noqa: F811
    cliente, _simulada, email_admin, banco = ambiente
    pool = banco._pool
    await _entrar(cliente, email_admin, "senha-admin-123")
    id_escritorio, h, canais = await _conta(cliente, "Rastro Ltda")
    canal = next(c for c in canais if c["tipo"] != "oficial")
    agente = (await cliente.post("/api/agentes", headers=h, json={"nome": "Júlia", "id_canal": canal["id"]})).json()
    id_lead = await _lead(pool, id_escritorio, canal["id"], agente["id"], "5511" + str(uuid.uuid4().int)[:9])
    codigos = [r["codigo"] for r in await pool.fetch(
        "select codigo from agentesia_agente_etapas where id_agente = $1::uuid order by ordem", agente["id"])]
    primeira, segunda = codigos[0], next(c for c in codigos[1:] if c not in ("desqualificado", "analise_manual"))

    # Um turno da IA passa o lead da primeira etapa para a segunda (o gatilho do banco grava o histórico).
    turno = str(await pool.fetchval(
        """insert into agentesia_turnos (id_escritorio, id_lead, modo, etapa_antes, etapa_depois, situacao, motivo, concluido_em)
           values ($1::uuid, $2::uuid, 'producao', $3, $4, 'respondido', 'qualificou: tem sequela', now()) returning id""",
        id_escritorio, id_lead, primeira, segunda))
    async with pool.acquire() as conexao, conexao.transaction():
        await conexao.execute("select set_config('agentesia.origem_etapa', 'ia', true), set_config('agentesia.id_turno', $1, true)", turno)
        await conexao.execute(
            """update agentesia_leads set id_etapa = (select id from agentesia_agente_etapas where id_agente = $2::uuid and codigo = $3)
               where id = $1::uuid""", id_lead, agente["id"], segunda)
    # Depois: a IA quis pular para outra etapa (recusado), uma trava segurou a resposta e o portão de fatos barrou.
    eventos = [("destino_recusado", "info", {"destino": "assinatura", "etapa": segunda}, "1 second"),
               ("trava_promessa_valor", "aviso", {"etapa": segunda}, "2 seconds"),
               ("portao_de_fatos", "info", {"destino": "contratos", "etapa": segunda}, "3 seconds"),
               ("algo_que_nao_entra", "info", {}, "4 seconds")]
    for tipo, gravidade, detalhe, depois in eventos:
        await pool.execute(
            f"""insert into agentesia_eventos (id_escritorio, id_lead, tipo, gravidade, responsavel, descricao, detalhe, criado_em)
                values ($1::uuid, $2::uuid, $3, $4, 'lawchat', $5, $6::jsonb, now() + interval '{depois}')""",
            id_escritorio, id_lead, tipo, gravidade, f"descrição de {tipo}", json.dumps(detalhe))

    conversa = (await cliente.get(f"/api/conversas/{id_lead}", headers=h)).json()
    rastro = conversa["rastro"]
    tipos = [(i["tipo"], i["evento"]) for i in rastro]
    assert tipos == [("recusa", "portao_de_fatos"),
                     ("barreira", "trava_promessa_valor"), ("recusa", "destino_recusado"),
                     ("passagem", None), ("entrada", None)], tipos
    passagem = rastro[3]
    assert (passagem["de"], passagem["para"], passagem["quem"]) == (primeira, segunda, "ia")
    assert passagem["motivo"] == "qualificou: tem sequela" and passagem["nome_para"]
    assert rastro[0]["titulo"] == "Portão de fatos: faltam dados para passar" and rastro[0]["para"] == "contratos"
    assert rastro[2]["para"] == "assinatura" and rastro[2]["quem"] == "ia"

    funil = conversa["funil"]
    assert funil["ativa"] == segunda and [e["codigo"] for e in funil["etapas"]] == codigos
    ativa = next(e for e in funil["etapas"] if e["ativa"])
    assert ativa["codigo"] == segunda and ativa["visitada"]
    assert next(e for e in funil["etapas"] if e["codigo"] == primeira)["visitada"]
    assert primeira not in funil["alcancaveis"] and "desqualificado" in funil["alcancaveis"]

    # A equipe passa o lead pelo painel e depois desliga a IA: os dois entram no topo do rastro.
    terceira = funil["alcancaveis"][0]
    r = await cliente.post(f"/api/conversas/{id_lead}/ia", headers=h, json={"acao": "trocar_etapa", "etapa": terceira})
    assert r.status_code == 200, r.text
    r = await cliente.post(f"/api/conversas/{id_lead}/ia", headers=h, json={"acao": "desativar", "minutos": 30})
    assert r.status_code == 200, r.text
    rastro = (await cliente.get(f"/api/conversas/{id_lead}", headers=h)).json()["rastro"]
    pausa = next(i for i in rastro if i["tipo"] == "pausa")
    assert pausa["titulo"] == "IA desligada pela equipe" and pausa["quem"] == "painel"
    pela_equipe = next(i for i in rastro if i["tipo"] == "passagem" and i["para"] == terceira)
    assert pela_equipe["de"] == segunda and pela_equipe["quem"] == "painel"


def test_contas_painel_do_crm_e_primeiro_agente():
    """Contas › passos: o painel do CRM volta a ser escolhido aqui (a ativação só usa o escolhido) e o "Primeiro produto"
    pendente tem o botão que entra na conta e abre a Biblioteca."""
    tela = (RAIZ / "painel" / "src" / "telas" / "AdminEscritorios.tsx").read_text(encoding="utf-8")
    assert 'const FORA_DA_INTEGRACAO = ["canais", "zapsign"];' in tela
    # "Primeiro produto" é da ativação do agente: aparece como informativo e não trava o onboarding da conta.
    assert 'const OBRIGATORIOS = ["token", "webhook", "etiquetas", "painel"];' in tela
    assert 'const INFORMATIVOS = ["produto"];' in tela
    assert "Painel do CRM (aplica ao avançar)" in tela and "<CriarPainelPadrao idEscritorio={linha.id}" in tela
    assert "Etapas do painel ligadas" in tela and "Falta escolher o painel do CRM" in tela
    assert "crm comercial ia" in tela and "/onboarding/conferir" in tela
    assert "Acessar e ativar o primeiro agente" in tela and 'entrar(id, "/biblioteca")' in tela
    assert "Escolha aqui o painel do CRM. O número entra na ativação do agente." in tela
    assert "O painel do CRM e o número entram na ativação do agente" not in tela
