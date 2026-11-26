"""Relatórios (app/gestao/rotas_relatorios.py) e a varredura do CRM (app/gestao/reconciliar_crm.py).

Os testes com banco só rodam com AGENTESIA_TESTE_PG_URL num banco com a migração 012 (db/testes/servidor_local.mjs).
Nada externo é chamado: leads, etapas, contratos, mensagens, turnos e chamadas são gravados direto no banco, e a
plataforma do CRM é um objeto falso.
"""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.gestao import reconciliar_crm as rc
from app.gestao import rotas_relatorios as rel
from tests.test_gestao import _entrar, ambiente  # noqa: F401  (fixture)

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
RAIZ = Path(__file__).resolve().parent.parent
pg = pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")


# ------------------------------------------------------------------ sem banco
def test_fase_pelo_nome_da_coluna_do_crm():
    assert rel.fase_do_titulo("🤖 SDR") == "sdr"
    assert rel.fase_do_titulo("Closer - proposta") == "closer"
    assert rel.fase_do_titulo("CONTRATO ASSINADO ✅") == "assinado"
    assert rel.fase_do_titulo("Fizemos contrato, não assinou") == "nao_assinou"
    assert rel.fase_do_titulo("Aguardando assinatura") == "assinatura"
    assert rel.fase_do_titulo("Confecção de contrato") == "contratos"
    assert rel.fase_do_titulo("Desqualificado") == "desqualificado"
    assert rel.fase_do_titulo("Análise manual") == "analise"
    assert rel.fase_do_titulo("Qualquer coisa") == "outra" and rel.fase_do_titulo(None) == "outra"


def _anuncio(chave, nome, leads, assinados, desq=0, campanha="C"):
    return {"chave": chave, "nome": nome, "campanha": campanha, "leads": leads, "assinados": assinados,
            "desqualificados": desq, "conversao": round(assinados / leads * 100, 1) if leads else None,
            "desqualificacao": None, "plataforma_nome": "Instagram"}


def test_teste_ab_e_alertas():
    ab = rel.teste_ab([_anuncio("a", "A", 10, 3), _anuncio("b", "B", 8, 0), _anuncio("c", "C", 2, 2),
                       _anuncio("x", "X", 5, 1, campanha="Outra")])
    assert len(ab) == 1                                    # "Outra" tem um anúncio só; "C" tem só 2 leads
    assert ab[0]["vencedor"] == "a" and ab[0]["perdedor"] == "b" and "Pause" in ab[0]["recomendacao"]
    assert [a["chave"] for a in ab[0]["anuncios"]] == ["a", "b"]
    alertas = rel.alertas_de_campanhas([
        {"campanha": "Sem contrato", "leads": 8, "assinados": 0, "desqualificados": 1},
        {"campanha": "Desqualifica", "leads": 4, "assinados": 1, "desqualificados": 3},
        {"campanha": "Baixa", "leads": 40, "assinados": 1, "desqualificados": 0},
        {"campanha": "Boa", "leads": 10, "assinados": 4, "desqualificados": 0}])
    assert [(a["campanha"], a["gravidade"]) for a in alertas] == [
        ("Sem contrato", "alta"), ("Desqualifica", "alta"), ("Baixa", "media")]


def test_filtros_validam_periodo():
    with pytest.raises(Exception):
        rel.Filtros("2026-02-10", "2026-01-01", None, None, None)
    with pytest.raises(Exception):
        rel.Filtros("2020-01-01", "2026-01-01", None, None, None)
    with pytest.raises(Exception):
        rel.Filtros(None, None, "nao-e-uuid", None, None)
    f = rel.Filtros("2026-01-01", "2026-01-31", None, None, None)
    assert f.dias == 31 and f.anteriores()[1] == f.limites()[0]


def test_ler_card_da_plataforma():
    card = rc.ler_card({"id": "c1", "stepId": "s1", "panelId": "p", "contactIds": ["k"], "title": "Maria",
                        "monetaryAmount": "1500.5", "createdAt": "2026-01-01T10:00:00Z", "updatedAt": "2026-01-02T10:00:00"})
    assert card["id_contato"] == "k" and card["valor"] == 1500.5 and card["atualizado_em"].tzinfo is not None
    assert rc.ler_card({"title": "sem id"}) is None


def test_rotas_menu_e_telas_sem_o_nome_da_plataforma():
    main = (RAIZ / "app" / "main.py").read_text(encoding="utf-8")
    assert "from app.gestao.rotas_relatorios import api as api_relatorios" in main
    assert "Reconciliador(" in main
    estrutura = (RAIZ / "painel" / "src" / "componentes" / "Estrutura.tsx").read_text(encoding="utf-8")
    assert 'rotulo: "Relatórios"' in estrutura
    assert '{ para: "/relatorios/dashboard", rotulo: "Dashboard"' in estrutura
    assert '{ para: "/relatorios/campanhas", rotulo: "Rastreamento de campanhas"' in estrutura
    rotas = (RAIZ / "painel" / "src" / "main.tsx").read_text(encoding="utf-8")
    assert 'path="/relatorios/dashboard"' in rotas and 'path="/relatorios/campanhas"' in rotas
    for arquivo in (RAIZ / "painel" / "src" / "telas").glob("Relatorio*.tsx"):
        assert "Helena" not in arquivo.read_text(encoding="utf-8"), arquivo.name


def test_painel_do_servidor_leva_as_rotas():
    from app.servidor import criar_app, rotas_montadas
    caminhos = rotas_montadas(criar_app("painel"))
    assert {"/api/relatorios/dashboard", "/api/relatorios/campanhas", "/api/relatorios/filtros",
            "/api/relatorios/campanhas/anuncio/{chave}", "/api/relatorios/crm/importar"} <= caminhos
    assert "/api/relatorios/dashboard" not in rotas_montadas(criar_app("ia"))


# ------------------------------------------------------------------ com banco
async def _etapa(pool, id_agente, codigo, ordem):
    return str(await pool.fetchval(
        """insert into agentesia_agente_etapas (id_agente, codigo, ordem) values ($1::uuid, $2, $3)
           on conflict (id_agente, codigo) do update set ordem = agentesia_agente_etapas.ordem returning id""",
        id_agente, codigo, ordem))


async def _semear(cliente, pool, nome_conta):
    escritorio = (await cliente.post("/api/admin/escritorios", json={
        "nome": nome_conta, "id_conta_helena": str(uuid.uuid4()),
        "token_helena": f"token-bom-{uuid.uuid4().hex[:8]}"})).json()["escritorio"]
    id_esc = escritorio["id"]
    h = {"x-escritorio": id_esc}
    canal = next(c for c in (await cliente.get("/api/integracoes", headers=h)).json()["canais"] if c["tipo"] != "oficial")
    agente = (await cliente.post("/api/agentes", headers=h, json={"nome": f"Agente {nome_conta}", "id_canal": canal["id"]})).json()
    etapas = {c: await _etapa(pool, agente["id"], c, i) for i, c in enumerate(
        ["sdr", "closer", "contratos", "assinatura", "contrato_assinado", "desqualificado"], start=1)}
    agora = datetime.now(timezone.utc)
    ids = {}

    async def lead(nome, telefone, origem, caminho, dias_atras=2, assinado_horas=None):
        contato = await pool.fetchval(
            "insert into agentesia_contatos (id_escritorio, nome, telefone_normalizado, id_contato_helena) values ($1::uuid, $2, $3, $4) returning id",
            id_esc, nome, telefone, f"ct-{uuid.uuid4().hex[:8]}")
        criado = agora - timedelta(days=dias_atras)
        id_lead = str(await pool.fetchval(
            """insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_agente, id_etapa, origem, criado_em)
               values ($1::uuid, $2, $3::uuid, $4::uuid, $5::uuid, $6::jsonb, $7) returning id""",
            id_esc, contato, canal["id"], agente["id"], etapas[caminho[0]], json.dumps(origem), criado))
        for codigo in caminho[1:]:
            await pool.execute("update agentesia_leads set id_etapa = $2::uuid where id = $1::uuid", id_lead, etapas[codigo])
        if assinado_horas is not None:
            await pool.execute(
                """insert into agentesia_contratos (id_escritorio, id_lead, versao, dados, dados_hash, situacao, assinado_em)
                   values ($1::uuid, $2::uuid, 1, '{}'::jsonb, 'h', 'assinado', $3)""",
                id_esc, id_lead, criado + timedelta(hours=assinado_horas))
        return id_lead

    insta = {"origem": "anuncio", "campanha": "Campanha Auxílio", "titulo": "Anúncio 1", "fonte": "instagram",
             "url": "https://www.instagram.com/p/abc/", "clid": "x1"}
    ids["a"] = await lead("Maria Relatório", "5531999990001", insta,
                          ["sdr", "closer", "contratos", "assinatura", "contrato_assinado"], assinado_horas=30)
    ids["b"] = await lead("João Relatório", "5511999990002", insta, ["sdr", "closer", "desqualificado"])
    ids["c"] = await lead("Ana Relatório", "5521999990003",
                          {"origem": "anuncio", "campanha": "Campanha Auxílio", "titulo": "Anúncio 2", "fonte": "facebook"}, ["sdr"])
    ids["d"] = await lead("Pedro Relatório", "5541999990004", {}, ["sdr", "closer"])
    ids["velho"] = await lead("Antigo Relatório", "5551999990005", insta, ["sdr"], dias_atras=60)

    criado_a = await pool.fetchval("select criado_em from agentesia_leads where id = $1::uuid", ids["a"])
    for autor, seg in (("lead", 60), ("ia", 72), ("ia", 75)):
        await pool.execute(
            """insert into agentesia_mensagens (id_escritorio, id_lead, autor, tipo, texto, enviada_em, situacao_envio)
               values ($1::uuid, $2::uuid, $3, 'texto', 'oi', $4, 'enviada')""", id_esc, ids["a"], autor, criado_a + timedelta(seconds=seg))
    t1 = await pool.fetchval(
        """insert into agentesia_turnos (id_escritorio, id_lead, modo, etapa_antes, etapa_depois, situacao, iniciado_em, concluido_em)
           values ($1::uuid, $2::uuid, 'producao', 'sdr', 'closer', 'respondido', $3::timestamptz, $3::timestamptz + interval '4 seconds') returning id""",
        id_esc, ids["a"], criado_a + timedelta(seconds=61))
    await pool.execute(
        """insert into agentesia_turnos (id_escritorio, id_lead, modo, etapa_antes, situacao, iniciado_em, concluido_em)
           values ($1::uuid, $2::uuid, 'producao', 'closer', 'erro', $3::timestamptz, $3::timestamptz + interval '1 second')""",
        id_esc, ids["b"], criado_a + timedelta(seconds=90))
    await pool.execute(
        """insert into agentesia_chamadas_ia (id_escritorio, id_turno, id_lead, papel, modelo, tokens_entrada, tokens_saida,
                                              custo_usd, duracao_ms, sucesso, criado_em)
           values ($1::uuid, $2::uuid, $3::uuid, 'etapa', 'gpt-4.1', 1000, 100, 0.01, 900, true, $4)""",
        id_esc, t1, ids["a"], criado_a + timedelta(seconds=62))
    return {"escritorio": id_esc, "agente": agente["id"], "h": h, **ids}


@pg
async def test_dashboard_campanhas_e_anuncio(ambiente):  # noqa: F811
    cliente, _simulada, email_admin, banco = ambiente
    cliente._transport.app.include_router(rel.api)
    pool = banco._pool
    await _entrar(cliente, email_admin, "senha-admin-123")
    s = await _semear(cliente, pool, f"Relatórios {uuid.uuid4().hex[:5]}")
    outro = await _semear(cliente, pool, f"Relatórios outro {uuid.uuid4().hex[:5]}")
    h = s["h"]

    r = await cliente.get("/api/relatorios/dashboard", headers=h)
    assert r.status_code == 200, r.text
    d = r.json()
    k = d["kpis"]
    assert (k["leads"], k["assinados"], k["conversao"], k["desqualificados"]) == (4, 1, 25.0, 1)
    assert k["qualificados"] == 2                          # A (assinou) e D (closer); B saiu desqualificado
    assert k["com_origem"] == 3 and k["respostas_ia"] == 2 and k["mensagens_lead"] == 1
    assert k["primeira_resposta_s"] == 12
    assert k["custo_brl"] > 0 and k["custo_por_lead"] == round(k["custo_brl"] / 4, 2)
    assert [e["chegaram"] for e in d["funil"]] == [4, 3, 1, 1, 1]
    assert d["funil"][1]["conversao"] == 75.0 and d["funil"][-1]["fase"] == "assinado"
    assert d["tempo_ate_assinar"]["media_horas"] == 30.0
    assert d["tempo_ate_assinar"]["faixas"][1]["total"] == 1   # 30 h = 1 a 2 dias
    assert d["ia"]["turnos"] == 2 and d["ia"]["erros"] == 1 and d["ia"]["trocas"] == 1 and d["ia"]["duracao_media_s"] == 4.0
    assert len(d["serie"]) == 30 and sum(x["leads"] for x in d["serie"]) == 4 and sum(x["assinados"] for x in d["serie"]) == 1
    assert d["agentes"][0]["leads"] == 4 and d["agentes"][0]["assinados"] == 1
    assert {p["plataforma"]: p["leads"] for p in d["plataformas"]} == {"instagram": 2, "facebook": 1, "direto": 1}
    assert d["uf"]["leads"] == {"mg": 1, "sp": 1, "rj": 1, "pr": 1} and d["uf"]["contratos"] == {"mg": 1}
    assert sum(map(sum, d["horarios"]["leads"])) == 4 and sum(map(sum, d["horarios"]["assinados"])) == 1
    assert d["crm"] is not None and d["crm"]["total"] == 0
    assert "Antigo Relatório" not in r.text

    # Filtros: campanha, plataforma, agente e período.
    async def kpis(**params):
        resp = await cliente.get("/api/relatorios/dashboard", headers=h, params=params)
        assert resp.status_code == 200, resp.text
        return resp.json()["kpis"]
    assert (await kpis(campanha="Campanha Auxílio"))["leads"] == 3
    assert (await kpis(fonte="direto"))["leads"] == 1
    assert (await kpis(fonte="instagram"))["assinados"] == 1
    assert (await kpis(agente=outro["agente"]))["leads"] == 0  # agente de outra conta não vaza nada
    hoje = datetime.now(timezone(timedelta(hours=-3))).date()
    assert (await kpis(de=(hoje - timedelta(days=90)).isoformat()))["leads"] == 5
    assert (await cliente.get("/api/relatorios/dashboard", headers=h, params={"de": "x"})).status_code == 400
    assert (await cliente.get("/api/relatorios/dashboard", headers=h, params={"fonte": "orkut"})).status_code == 400

    # Rastreamento de campanhas.
    c = (await cliente.get("/api/relatorios/campanhas", headers=h)).json()
    assert c["kpis"]["leads"] == 3 and c["kpis"]["assinados"] == 1 and c["kpis"]["anuncios"] == 2
    assert [x["campanha"] for x in c["campanhas"]] == ["Campanha Auxílio"]
    camp = c["campanhas"][0]
    assert (camp["leads"], camp["closer"], camp["contratos"], camp["assinados"], camp["desqualificados"]) == (3, 2, 1, 1, 1)
    assert camp["horas_ate_assinar"] == 30.0 and camp["custo_brl"] > 0
    melhor = c["anuncios"][0]
    assert melhor["nome"] == "Anúncio 1" and melhor["leads"] == 2 and melhor["conversao"] == 50.0
    assert melhor["plataforma_nome"] == "Instagram" and melhor["url"].startswith("https://www.instagram.com/")
    assert {p["plataforma"]: p["leads"] for p in c["plataformas"]} == {"instagram": 2, "facebook": 1}
    assert [e["chegaram"] for e in c["funil"]] == [3, 2, 1, 1, 1]
    assert c["ab"] == []                                   # nenhum anúncio com 3 leads

    # Detalhe do anúncio: série, funil e os leads (telefone mascarado).
    a = await cliente.get(f"/api/relatorios/campanhas/anuncio/{melhor['chave']}", headers=h)
    assert a.status_code == 200, a.text
    a = a.json()
    assert a["leads"] == 2 and a["campanha"] == "Campanha Auxílio" and [x["chegaram"] for x in a["funil"]] == [2, 2, 1, 1, 1]
    assert {x["nome"] for x in a["lista_leads"]} == {"Maria Relatório", "João Relatório"}
    assert all("*****" in x["telefone"] for x in a["lista_leads"]) and "5531999990001" not in json.dumps(a)
    # A outra conta tem um anúncio igual (mesma chave): cada uma vê só os próprios leads.
    do_outro = (await cliente.get(f"/api/relatorios/campanhas/anuncio/{melhor['chave']}", headers=outro["h"])).json()
    assert {x["id"] for x in do_outro["lista_leads"]} == {outro["a"], outro["b"]}
    assert {x["id"] for x in a["lista_leads"]} == {s["a"], s["b"]}
    assert (await cliente.get("/api/relatorios/campanhas/anuncio/0123456789abcdef", headers=h)).status_code == 404
    assert (await cliente.get("/api/relatorios/campanhas/anuncio/zz", headers=h)).status_code == 400

    f = (await cliente.get("/api/relatorios/filtros", headers=h)).json()
    assert f["agentes"][0]["id"] == s["agente"] and f["campanhas"][0] == {"campanha": "Campanha Auxílio", "leads": 4}

    # Pedido de importação do CRM.
    assert (await cliente.post("/api/relatorios/crm/importar", headers=h)).status_code == 200
    d = (await cliente.get("/api/relatorios/dashboard", headers=h)).json()
    assert d["crm"]["importacao_pedida"] is True


class _PlataformaFalsa:
    def __init__(self, cards):
        self.cards = cards
        self.pedidos = []

    async def paineis(self):
        return [{"id": "painel-1", "etapas": [{"id": "col-sdr", "titulo": "SDR"}, {"id": "col-ok", "titulo": "Contrato assinado"}]}]

    async def _pedir(self, metodo, caminho, **kw):
        self.pedidos.append(kw["params"])
        pagina, tamanho = kw["params"]["PageNumber"], kw["params"]["PageSize"]
        itens = self.cards[(pagina - 1) * tamanho: pagina * tamanho]
        return {"items": itens, "hasMorePages": pagina * tamanho < len(self.cards)}


@pg
async def test_varredura_do_crm_importa_e_so_grava_o_que_mudou(ambiente, monkeypatch):  # noqa: F811
    cliente, _simulada, email_admin, banco = ambiente
    pool = banco._pool
    monkeypatch.setattr(rc, "PAUSA_ENTRE_PAGINAS_S", 0)
    monkeypatch.setattr(rc, "POR_PAGINA", 2)
    await _entrar(cliente, email_admin, "senha-admin-123")
    s = await _semear(cliente, pool, f"Varredura {uuid.uuid4().hex[:5]}")
    id_esc = s["escritorio"]
    m = uuid.uuid4().hex[:6]                               # o banco de teste é o mesmo entre rodadas
    await pool.execute(
        """insert into agentesia_integracoes (id_escritorio, tipo, config, situacao) values ($1::uuid, 'crm', '{"id_painel": "painel-1"}', 'ok')
           on conflict (id_escritorio, tipo) do update set config = excluded.config""", id_esc)
    await pool.execute(
        """insert into agentesia_crm_cards (id_escritorio, id_lead, id_card_helena, id_painel_helena, id_etapa_helena, situacao)
           values ($1::uuid, $2::uuid, $3, 'painel-1', 'col-sdr', 'ok')""", id_esc, s["a"], f"card-a-{m}")
    contato_c = await pool.fetchval(
        "select c.id_contato_helena from agentesia_leads l join agentesia_contatos c on c.id = l.id_contato where l.id = $1::uuid", s["c"])
    agora = datetime.now(timezone.utc)
    cards = [
        {"id": f"card-a-{m}", "stepId": "col-ok", "panelId": "painel-1", "title": "Maria", "updatedAt": agora.isoformat()},
        {"id": f"card-c-{m}", "stepId": "col-sdr", "contactIds": [contato_c], "updatedAt": (agora - timedelta(hours=1)).isoformat()},
        {"id": f"card-velho-{m}", "stepId": "col-ok", "contactIds": ["ninguem"], "createdAt": "2025-01-01T00:00:00Z",
         "updatedAt": (agora - timedelta(days=200)).isoformat()},
    ]
    falsa = _PlataformaFalsa(cards)
    r = await rc.varrer_escritorio(pool, id_esc, falsa)
    assert r["feito"] == "importado" and r["vistos"] == 3 and r["mudados"] == 3 and r["colunas_atualizadas"] == 1
    espelho = {x["id_card_helena"]: dict(x) for x in await pool.fetch(
        "select id_card_helena, fase, etapa_titulo, id_lead::text as id_lead from agentesia_crm_espelho where id_escritorio = $1::uuid", id_esc)}
    assert espelho[f"card-a-{m}"]["fase"] == "assinado" and espelho[f"card-a-{m}"]["id_lead"] == s["a"]
    assert espelho[f"card-c-{m}"]["id_lead"] == s["c"] and espelho[f"card-c-{m}"]["etapa_titulo"] == "SDR"
    assert espelho[f"card-velho-{m}"]["id_lead"] is None
    assert await pool.fetchval("select id_etapa_helena from agentesia_crm_cards where id_card_helena = $1", f"card-a-{m}") == "col-ok"
    # card-c não tinha card ligado: a varredura não cria a ligação (quem liga é a fila de ações).
    assert await pool.fetchval("select count(*) from agentesia_crm_cards where id_lead = $1::uuid", s["c"]) == 0

    # Segunda vez: incremental, para na página velha e não regrava nada igual.
    falsa.pedidos.clear()
    r = await rc.varrer_escritorio(pool, id_esc, falsa)
    assert r["feito"] == "incremental" and r["mudados"] == 0 and len(falsa.pedidos) == 2

    # Card movido sem aviso: só ele muda.
    cards[1].update(stepId="col-ok", updatedAt=(agora + timedelta(minutes=1)).isoformat())
    r = await rc.varrer_escritorio(pool, id_esc, falsa)
    assert r["mudados"] == 1
    assert await pool.fetchval("select fase from agentesia_crm_espelho where id_card_helena = $2 and id_escritorio = $1::uuid", id_esc, f"card-c-{m}") == "assinado"

    linha = await pool.fetchrow("select importado_em, cards_vistos, erro from agentesia_crm_varredura where id_escritorio = $1::uuid", id_esc)
    assert linha["importado_em"] is not None and linha["erro"] is None
    # limite alto: o banco de teste tem contas de outros testes na frente da fila
    contas = await rc.contas_para_varrer(pool, agora + timedelta(hours=1), limite=100000)
    assert id_esc in contas and id_esc not in await rc.contas_para_varrer(pool, agora, limite=100000)
