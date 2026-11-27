"""Tela "Créditos & Consumo" (GET /api/carteira/painel e /api/carteira/conversas): gasto por agente, conversas e
contratos por agente, conversas que mais gastaram (telefone mascarado), só valores cobrados (isenta fora) e só do
escritório da sessão. Roda com AGENTESIA_TESTE_PG_URL (node db/testes/servidor_local.mjs PORTA)."""

import os
import uuid

import pytest

from app import cobranca
from app.cobranca.rotas import mascarar_telefone
from app.modelo import Chamada
from tests.test_cobranca import api_cobranca  # noqa: F401  (fixture)

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
com_banco = pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")


def test_mascara_telefone():
    assert mascarar_telefone("5521987654321") == "(21) 9****-4321"
    assert mascarar_telefone("21 3333-4444") == "(21) 3***-4444"
    assert mascarar_telefone(None) is None and mascarar_telefone("123") is None


async def _lead(pool, esc, agente, nome, telefone):
    canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado) values ($1::uuid, $2) returning id",
                                esc, "5521" + str(uuid.uuid4().int)[:9])
    contato = await pool.fetchval(
        "insert into agentesia_contatos (id_escritorio, nome, telefone_normalizado) values ($1::uuid, $2, $3) returning id",
        esc, nome, telefone)
    return str(await pool.fetchval(
        "insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_agente) values ($1::uuid, $2, $3, $4::uuid) returning id",
        esc, contato, canal, agente))


async def _agente(pool, esc, nome):
    canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado) values ($1::uuid, $2) returning id",
                                esc, "5521" + str(uuid.uuid4().int)[:9])
    return str(await pool.fetchval(
        "insert into agentesia_agentes (id_escritorio, id_canal, nome) values ($1::uuid, $2, $3) returning id", esc, canal, nome))


async def _chamada(pool, esc, lead, agente, usd, papel="etapa", turno=None, tokens=(100, 50)):
    await cobranca.gravar_chamadas(pool, id_escritorio=esc, chamadas=[
        Chamada(papel=papel, modelo="gpt-4.1", tokens_entrada=tokens[0], tokens_saida=tokens[1], custo_usd=usd)])
    await pool.execute(
        """update agentesia_chamadas_ia set id_lead = $2::uuid, id_agente = $3::uuid, id_turno = $4::uuid
           where id = (select id from agentesia_chamadas_ia where id_escritorio = $1::uuid order by criado_em desc limit 1)""",
        esc, lead, agente, turno)


@com_banco
async def test_painel_por_agente_conversas_e_mais_caras(api_cobranca):  # noqa: F811
    pool, esc, cliente = api_cobranca
    ana, beto = await _agente(pool, esc, "Ana Previdência"), await _agente(pool, esc, "Beto Trabalhista")
    l1 = await _lead(pool, esc, ana, "Maria", "5521987654321")
    l2 = await _lead(pool, esc, ana, "João", "5511912345678")
    l3 = await _lead(pool, esc, beto, "Carla", "5531999990000")
    t1 = str(await pool.fetchval("insert into agentesia_turnos (id_escritorio, id_lead, modo) values ($1::uuid, $2::uuid, 'producao') returning id", esc, l1))
    await _chamada(pool, esc, l1, ana, 0.10, turno=t1)
    await _chamada(pool, esc, l1, ana, 0.05, papel="extrator", turno=t1)
    await _chamada(pool, esc, l2, ana, 0.01)
    await _chamada(pool, esc, l3, beto, 0.02, papel="followup")
    # Chamada isenta (antes da cobrança) não entra em nenhum número.
    await _chamada(pool, esc, l3, beto, 5.0)
    await pool.execute("update agentesia_chamadas_ia set cobranca = 'isenta' where id_escritorio = $1::uuid and custo_usd = 5.0", esc)
    await pool.execute(
        "insert into agentesia_mensagens (id_escritorio, id_lead, autor, texto, enviada_em) values ($1::uuid, $2::uuid, 'lead', 'oi', now()), ($1::uuid, $2::uuid, 'ia', 'olá', now())",
        esc, l1)
    await pool.execute(
        "insert into agentesia_contratos (id_escritorio, id_lead, versao, dados, dados_hash, situacao, assinado_em) values ($1::uuid, $2::uuid, 1, '{}', 'h', 'assinado', now())",
        esc, l1)
    await cobranca.lancar(pool, esc, "recarga", 200, motivo="recarga de teste")

    # Outro escritório com consumo: não pode aparecer.
    outro = str(await pool.fetchval("insert into agentesia_escritorios (nome) values ('Vizinho') returning id"))
    ag_outro = await _agente(pool, outro, "Agente do vizinho")
    await _chamada(pool, outro, await _lead(pool, outro, ag_outro, "Zé", "5521911112222"), ag_outro, 3.0)

    async with cliente("gestor") as gestor, cliente("atendente") as atendente:
        assert (await atendente.get("/api/carteira/painel")).status_code == 403
        assert (await atendente.get("/api/carteira/conversas")).status_code == 403
        painel = (await gestor.get("/api/carteira/painel?dias=30")).json()
        t = painel["totais"]
        assert t["conversas"] == 3 and t["contratos"] == 1 and t["chamadas"] == 4 and t["tokens"] == 4 * 150
        assert t["conversao_pct"] == pytest.approx(33.3)
        cobrado = float(await pool.fetchval(
            "select sum(custo_brl) from agentesia_chamadas_ia where id_escritorio = $1::uuid and cobranca <> 'isenta'", esc))
        assert t["creditos_brl"] == pytest.approx(cobrado) and t["custo_por_contrato_brl"] == pytest.approx(round(cobrado, 2))
        por_agente = {a["agente"]: a for a in painel["por_agente"]}
        assert set(por_agente) == {"Ana Previdência", "Beto Trabalhista"}
        assert por_agente["Ana Previdência"]["conversas"] == 2 and por_agente["Ana Previdência"]["contratos"] == 1
        assert por_agente["Beto Trabalhista"]["conversas"] == 1 and por_agente["Beto Trabalhista"]["contratos"] == 0
        assert painel["por_agente"][0]["agente"] == "Ana Previdência"                   # quem mais gastou primeiro
        assert {f["papel"] for f in painel["por_funcao"]} == {"etapa", "extrator", "followup"}
        assert painel["creditos"]["recargas_brl"] == 200 and painel["creditos"]["recargas"] == 1
        assert painel["carteira"]["disponivel_brl"] is not None and "markup" not in painel["carteira"]
        assert painel["media_dia_brl"] > 0 and sum(p["valor_brl"] for p in painel["serie"]) == pytest.approx(cobrado)
        assert (await gestor.get("/api/carteira/painel?dias=1")).json()["granularidade"] == "hora"
        # Custo por lead do período (real, com markup: é o custo_brl cobrado) e quantos leads o saldo atende.
        pl = painel["custo_por_lead"]
        assert pl["fonte"] == "periodo" and pl["estimativa"] is False and pl["valor_brl"] == pytest.approx(cobrado / 3, abs=1e-4)
        assert pl["leads_com_saldo"] == int(painel["carteira"]["disponivel_brl"] / pl["valor_brl"] + 1e-9)
        assert por_agente["Ana Previdência"]["custo_por_lead_brl"] == pytest.approx(por_agente["Ana Previdência"]["valor_brl"] / 2, abs=1e-4)

        caras = (await gestor.get("/api/carteira/conversas?dias=30&ordem=custo&limite=10")).json()
        assert caras["total"] == 3 and [c["contato"] for c in caras["conversas"]] == ["Maria", "Carla", "João"]
        maria = caras["conversas"][0]
        assert maria["telefone"] == "(21) 9****-4321" and maria["agente"] == "Ana Previdência"
        assert maria["turnos"] == 1 and maria["mensagens"] == 2 and maria["chamadas"] == 2 and maria["contrato_assinado"] is True
        assert "5521987654321" not in str(caras)
        so_beto = (await gestor.get(f"/api/carteira/conversas?id_agente={beto}")).json()
        assert [c["contato"] for c in so_beto["conversas"]] == ["Carla"]
        assert (await gestor.get("/api/carteira/conversas?ordem=qualquer")).status_code == 400
        pagina2 = (await gestor.get("/api/carteira/conversas?ordem=custo&limite=2&deslocamento=2")).json()
        assert pagina2["total"] == 3 and [c["contato"] for c in pagina2["conversas"]] == ["João"]


@com_banco
async def test_painel_vazio_sem_numeros_inventados(api_cobranca, monkeypatch):  # noqa: F811
    from app.cobranca import rotas
    monkeypatch.setattr(rotas, "MINIMO_REFERENCIA", {"escritorios": 10**6, "leads": 10**6})
    _, _, cliente = api_cobranca
    async with cliente("gestor") as gestor:
        painel = (await gestor.get("/api/carteira/painel?dias=7")).json()
        t = painel["totais"]
        assert t["creditos_brl"] == 0 and t["conversas"] == 0 and t["custo_por_conversa_brl"] is None
        assert t["custo_por_contrato_brl"] is None and t["conversao_pct"] is None and painel["media_dia_brl"] is None
        assert painel["por_agente"] == [] and painel["serie"] == []
        assert painel["custo_por_lead"] == {"valor_brl": None, "fonte": None, "estimativa": True, "leads_com_saldo": None}
        assert (await gestor.get("/api/carteira/conversas")).json() == {"dias": 30, "ordem": "custo", "total": 0, "conversas": []}


@com_banco
async def test_sem_historico_usa_referencia_do_modelo_com_o_markup_do_escritorio(api_cobranca):  # noqa: F811
    pool, esc, cliente = api_cobranca
    modelo = "modelo-ref-" + uuid.uuid4().hex[:6]           # só este teste usa: a média não mistura outros dados
    for i in range(3):
        outro = str(await pool.fetchval("insert into agentesia_escritorios (nome) values ($1) returning id", f"Ref {i}"))
        ag = await _agente(pool, outro, f"Ag {i}")
        for _ in range(7):
            lead = await _lead(pool, outro, ag, "X", "55219" + str(uuid.uuid4().int)[:8])
            await cobranca.gravar_chamadas(pool, id_escritorio=outro, chamadas=[Chamada(papel="etapa", modelo=modelo, custo_usd=0.01)])
            await pool.execute(
                """update agentesia_chamadas_ia set id_lead = $2::uuid, custo_brl_real = 0.10, custo_brl = 0.50
                   where id = (select id from agentesia_chamadas_ia where id_escritorio = $1::uuid order by criado_em desc limit 1)""",
                outro, lead)
    canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado) values ($1::uuid, '5521955554444') returning id", esc)
    await pool.execute("insert into agentesia_agentes (id_escritorio, id_canal, nome, config) values ($1::uuid, $2, 'Novo', $3::jsonb)",
                       esc, canal, '{"modelos": {"etapa": "%s"}}' % modelo)
    await pool.execute("update agentesia_carteiras set markup = 2.0 where id_escritorio = $1::uuid", esc)
    await cobranca.lancar(pool, esc, "recarga", 10, motivo="teste")
    async with cliente("gestor") as gestor:
        pl = (await gestor.get("/api/carteira/painel?dias=30")).json()["custo_por_lead"]
    # custo real médio R$ 0,10 por lead × markup 2,0 deste escritório (não o R$ 0,50 cobrado dos outros).
    assert pl["fonte"] == "referencia_modelo" and pl["estimativa"] is True and pl["valor_brl"] == pytest.approx(0.20)
    assert pl["leads_com_saldo"] == 50


@com_banco
async def test_painel_bloco_do_mes_e_saldo_depois_da_recarga(api_cobranca):  # noqa: F811
    """Bloco "mes" (desde o dia 1º, independe do período): gasto, tokens, contratos, custo por contrato, mês anterior
    e participação por agente com o nome do produto. Recarga confirmada traz o saldo logo depois dela."""
    pool, esc, cliente = api_cobranca
    ana = await _agente(pool, esc, "Ana Mês")
    await pool.execute("insert into agentesia_produtos_ativados (id_escritorio, id_agente, nome, status) values ($1::uuid, $2::uuid, 'BPC Infantil', 'ativo')",
                       esc, ana)
    l1, l2 = await _lead(pool, esc, ana, "Atual", "5521900000001"), await _lead(pool, esc, ana, "Antigo", "5521900000002")
    await _chamada(pool, esc, l1, ana, 0.10)
    await _chamada(pool, esc, l2, ana, 0.20)
    # A chamada do l2 e o contrato dele vão para o meio do mês anterior.
    meio_ant = "(date_trunc('month', now() at time zone 'America/Sao_Paulo') - interval '15 days') at time zone 'America/Sao_Paulo'"
    await pool.execute(f"update agentesia_chamadas_ia set criado_em = {meio_ant} where id_lead = $1::uuid", l2)
    for lead, quando in ((l1, "now()"), (l2, meio_ant)):
        await pool.execute(
            f"insert into agentesia_contratos (id_escritorio, id_lead, versao, dados, dados_hash, situacao, assinado_em) values ($1::uuid, $2::uuid, 1, '{{}}', 'h', 'assinado', {quando})",
            esc, lead)
    rec = str(await pool.fetchval("insert into agentesia_recargas (id_escritorio, valor_brl, gateway) values ($1::uuid, 150, 'manual') returning id", esc))
    await cobranca.confirmar_recarga(pool, rec)
    await pool.fetchval("insert into agentesia_recargas (id_escritorio, valor_brl, gateway) values ($1::uuid, 50, 'manual') returning id", esc)

    async with cliente("gestor") as gestor:
        painel = (await gestor.get("/api/carteira/painel?dias=1")).json()
        mes = painel["mes"]
        atual = float(await pool.fetchval("select custo_brl from agentesia_chamadas_ia where id_lead = $1::uuid", l1))
        antigo = float(await pool.fetchval("select custo_brl from agentesia_chamadas_ia where id_lead = $1::uuid", l2))
        assert mes["creditos_brl"] == pytest.approx(atual) and mes["tokens"] == 150 and mes["contratos"] == 1
        assert mes["custo_por_contrato_brl"] == pytest.approx(round(atual, 2))
        assert mes["anterior"]["creditos_brl"] == pytest.approx(antigo) and mes["anterior"]["contratos"] == 1
        assert mes["por_agente"] == [{"id_agente": ana, "agente": "Ana Mês", "produto": "BPC Infantil",
                                      "valor_brl": pytest.approx(atual), "participacao_pct": 100.0}]
        recargas = {r["id"]: r for r in (await gestor.get("/api/carteira/recargas")).json()}
        saldo = await pool.fetchrow("select saldo_brl::float8 as s, bonus_brl::float8 as b from agentesia_carteiras where id_escritorio = $1::uuid", esc)
        assert recargas[rec]["saldo_depois_brl"] == pytest.approx(saldo["s"] + saldo["b"])
        assert [r["saldo_depois_brl"] for r in recargas.values() if r["id"] != rec] == [None]
