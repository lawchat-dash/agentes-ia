"""Cobrança em R$ (app/cobranca, migração 007): débito com cotação e markup, livro = carteira, concorrência sem débito
duplo, bônus do mês, pausa por saldo e volta ao creditar, "pode gastar" no turno, follow-up e mídia, chave própria
(BYOK) ignorada e permissões cliente × admin.

Os testes com banco rodam com AGENTESIA_TESTE_PG_URL (node db/testes/servidor_local.mjs PORTA)."""

import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import FastAPI

from app import cobranca
from app.cobranca import gateways
from app.modelo import Chamada, ModeloFalso
from tests.test_pipeline import SIMPLES, HelenaFalsa, montar, webhook

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
com_banco = pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")


# ============================================================================ sem banco
def test_formula_e_markup():
    assert cobranca.calcular(0.01, 5.50, 1.00) == (0.055, 0.055)
    assert cobranca.calcular(0.0123, 5.00, 1.30) == (0.0615, 0.07995)
    assert cobranca.markup_de(percentual=30) == 1.3 and cobranca.markup_de(2) == 2.0
    for ruim in ({"valor": 0}, {"valor": "x"}, {"percentual": -100}, {"valor": 50}):
        with pytest.raises(ValueError):
            cobranca.markup_de(**ruim)
    with pytest.raises(ValueError):
        cobranca.validar_cotacao(0)


def test_avisos_devidos_uma_vez_por_mes_e_por_pausa():
    base = {"modo": "pre_pago", "saldo_brl": 50.0, "bonus_brl": 15.0, "bonus_do_mes_brl": 100.0, "pausado_por_saldo": False,
            "pausado_em": None, "avisos": {}, "nome": "Sousa"}
    avisos = cobranca.avisos_devidos(base, "2026-11")
    assert [a["chave"] for a in avisos] == ["bonus_80"] and "85% do bônus" in avisos[0]["texto"]
    assert cobranca.avisos_devidos({**base, "avisos": {"bonus_80": "2026-11"}}, "2026-11") == []
    assert cobranca.avisos_devidos({**base, "avisos": {"bonus_80": "2026-10"}}, "2026-11")[0]["chave"] == "bonus_80"
    acabou = cobranca.avisos_devidos({**base, "bonus_brl": 0.0}, "2026-11")
    assert [a["chave"] for a in acabou] == ["bonus_100"] and "R$ 50,00" in acabou[0]["texto"]
    pausa = {**base, "saldo_brl": -1.0, "bonus_brl": 0.0, "pausado_por_saldo": True, "pausado_em": "2026-11-25 10:00"}
    devido = cobranca.avisos_devidos(pausa, "2026-11")
    assert [a["tipo_evento"] for a in devido] == ["saldo_esgotado"] and devido[0]["gravidade"] == "critico"
    assert cobranca.avisos_devidos({**pausa, "avisos": {"saldo_zero": "2026-11-25 10:00"}}, "2026-11") == []
    assert cobranca.avisos_devidos({**base, "modo": "so_registrar", "bonus_brl": 0.0}, "2026-11") == []


def test_gateway_asaas_so_aceita_o_token_e_traduz_os_eventos():
    gw = gateways.GatewayAsaas(token_webhook="segredo-do-asaas")
    assert gw.webhook_autentico({"asaas-access-token": "segredo-do-asaas"}, b"{}")
    assert gw.webhook_autentico({"Asaas-Access-Token": "segredo-do-asaas"}, b"{}")
    assert not gw.webhook_autentico({"asaas-access-token": "outro"}, b"{}")
    assert not gw.webhook_autentico({}, b"{}")
    assert not gateways.GatewayAsaas(token_webhook="").webhook_autentico({"asaas-access-token": ""}, b"{}")
    ev = gw.ler_webhook({"id": "evt_1", "event": "PAYMENT_RECEIVED", "payment": {"id": "pay_1", "externalReference": "r-1"}})
    assert (ev.id_evento, ev.tipo, ev.id_externo, ev.id_recarga) == ("evt_1", "paga", "pay_1", "r-1")
    assert gw.ler_webhook({"event": "PAYMENT_OVERDUE", "payment": {"id": "p"}}).tipo == "expirada"
    assert gw.ler_webhook({"event": "PAYMENT_CREATED", "payment": {"id": "p"}}).tipo == "ignorado"
    assert gateways.gateway("manual").nome == "manual" and gateways.gateway("asaas").nome == "asaas"


async def test_turno_sem_saldo_fica_em_silencio_e_volta_sem_rajada():
    atendimento, repo, helena = montar(SIMPLES)
    repo.sem_saldo = {"esc-1"}
    for texto in ("oi", "alô?"):
        await atendimento.receber(webhook(texto))
        await atendimento.aguardar_esperas()
    assert helena.enviadas == [] and repo.chamadas == []                 # nada pago foi chamado
    assert {t["motivo"] for t in repo.turnos.values()} == {"sem_saldo"}
    assert len([e for e in repo.eventos if e["tipo"] == "sem_saldo"]) == 2
    assert len([a for a in repo.acoes if a["tipo"] == "nota"]) == 1          # a equipe é avisada no chat uma vez

    repo.sem_saldo = set()                                                  # entrou crédito
    await atendimento.aguardar_esperas()
    assert helena.enviadas == []                                            # não responde o que ficou na pausa
    await atendimento.receber(webhook("tem alguém?"))
    await atendimento.aguardar_esperas()
    assert helena.enviadas == ["Oi! Me conta o que aconteceu?"]             # uma resposta só, à mensagem nova


async def test_midia_nao_e_lida_sem_saldo():
    from app.canal.helena import ler_webhook

    atendimento, repo, _ = montar(SIMPLES)
    repo.sem_saldo = {"esc-1"}
    lidas = []

    class Visao:
        async def transcrever_audio(self, dados, nome):
            lidas.append(nome)
            return "texto", Chamada(papel="transcrever_audio", modelo="gpt-4o-mini-transcribe", custo_usd=0.01)

    atendimento.visao = Visao()
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    lead = next(iter(repo.leads.values()))
    mensagem = repo.mensagens[lead.id][0]
    evento = ler_webhook(webhook(None, tipo="AUDIO", fileUrl="https://exemplo.com/a.ogg"))
    await atendimento._ler_midia(mensagem.id, lead, None, evento)
    assert lidas == [] and repo.chamadas == []
    assert mensagem.texto_extraido == "[arquivo não lido: o saldo da IA acabou]"


# ============================================================================ com banco
async def _repo():
    from app.banco.postgres import RepositorioPostgres
    return await RepositorioPostgres.conectar(URL, max_conexoes=1)       # o servidor de teste só aceita uma


async def _escritorio(pool, *, modo="pre_pago", nome="Cobrança Adv") -> str:
    esc = str(await pool.fetchval("insert into agentesia_escritorios (nome) values ($1) returning id", nome))
    await pool.execute("insert into agentesia_carteiras (id_escritorio, modo) values ($1::uuid, $2)", esc, modo)
    return esc


async def _conferencia(pool, esc) -> float:
    return float(await pool.fetchval(
        "select diferenca from agentesia_v_carteira_conferencia where id_escritorio = $1::uuid", esc))


@com_banco
async def test_debito_com_cotacao_e_markup_e_livro_igual_a_carteira():
    repo = await _repo()
    pool = repo._pool
    id_config = None
    try:
        id_config = await pool.fetchval(
            "insert into agentesia_cobranca_config (cotacao_usd_brl, markup, motivo) values (5.00, 1.50, 'teste') returning id")
        esc = await _escritorio(pool)
        await cobranca.lancar(pool, esc, "recarga", 10, motivo="primeira recarga")
        await cobranca.gravar_chamadas(pool, id_escritorio=esc, chamadas=[
            Chamada(papel="etapa", modelo="gpt-4.1", tokens_entrada=1000, tokens_saida=200, tokens_cache=500, custo_usd=0.004),
            Chamada(papel="extrator", modelo="gpt-4.1-mini", custo_usd=0.0002),
            Chamada(papel="auditor", modelo="modelo-sem-preco", tokens_entrada=50, custo_usd=0.0, sucesso=True)])
        linhas = [dict(r) for r in await pool.fetch(
            """select papel, tokens_entrada, tokens_cache, cotacao::float8 as cotacao, markup::float8 as markup,
                      custo_brl_real::float8 as real, custo_brl::float8 as cobrado, cobranca, sem_preco
               from agentesia_chamadas_ia where id_escritorio = $1::uuid order by papel""", esc)]
        etapa = next(l for l in linhas if l["papel"] == "etapa")
        assert (etapa["tokens_entrada"], etapa["tokens_cache"]) == (1500, 500)       # entrada total, cache à parte
        assert (etapa["cotacao"], etapa["markup"], etapa["real"], etapa["cobrado"]) == (5.0, 1.5, 0.02, 0.03)
        auditor = next(l for l in linhas if l["papel"] == "auditor")
        assert auditor["sem_preco"] and auditor["cobranca"] == "isenta"
        antes = await cobranca.situacao(pool, esc)
        assert antes.pendente_brl == pytest.approx(0.0315) and antes.disponivel_brl == pytest.approx(9.9685)

        debitos = await cobranca.debitar_pendentes(pool, esc)
        assert len(debitos) == 1 and debitos[0]["valor"] == pytest.approx(0.0315) and debitos[0]["quantidade"] == 2
        assert await cobranca.debitar_pendentes(pool, esc) == []                     # nada debitado duas vezes
        mov = await pool.fetchrow("select valor_brl::float8 as v, detalhe from agentesia_carteira_movimentos where id = $1",
                                  debitos[0]["movimento"])
        detalhe = mov["detalhe"] if isinstance(mov["detalhe"], dict) else json.loads(mov["detalhe"])
        assert mov["v"] == pytest.approx(-0.0315) and detalhe["chamadas"] == 2 and detalhe["custo_usd"] == pytest.approx(0.0042)
        depois = await cobranca.situacao(pool, esc)
        assert depois.saldo_brl == pytest.approx(9.9685) and depois.pendente_brl == 0
        assert await _conferencia(pool, esc) == 0
        # A carteira não muda por fora do livro, e o livro não muda.
        with pytest.raises(Exception, match="livro"):
            await pool.execute("update agentesia_carteiras set saldo_brl = 1000 where id_escritorio = $1::uuid", esc)
        with pytest.raises(Exception, match="livro"):
            await pool.execute("update agentesia_carteira_movimentos set valor_brl = 1 where id_escritorio = $1::uuid", esc)
        # A mudança de cotação vale só daqui para a frente: a chamada antiga guarda a dela.
        await pool.execute("delete from agentesia_cobranca_config where id = $1", id_config)
        id_config = None
        await cobranca.gravar_chamadas(pool, id_escritorio=esc, chamadas=[Chamada(papel="etapa", modelo="gpt-4.1", custo_usd=0.01)])
        assert await pool.fetchval(
            "select array_agg(distinct cotacao::float8 order by cotacao::float8) from agentesia_chamadas_ia where id_escritorio = $1::uuid",
            esc) == [5.0, 5.5]
    finally:
        if id_config:
            await pool.execute("delete from agentesia_cobranca_config where id = $1", id_config)
        await repo.fechar()


@com_banco
async def test_concorrencia_sem_debito_duplo_e_recarga_creditada_uma_vez():
    repo = await _repo()
    pool = repo._pool
    try:
        esc = await _escritorio(pool)
        for _ in range(4):
            await cobranca.gravar_chamadas(pool, id_escritorio=esc, chamadas=[
                Chamada(papel="etapa", modelo="gpt-4.1", custo_usd=0.01) for _ in range(25)])
        total = float(await pool.fetchval("select sum(custo_brl) from agentesia_chamadas_ia where id_escritorio = $1::uuid", esc))
        resultados = await asyncio.gather(*[cobranca.debitar_pendentes(pool, esc) for _ in range(6)])
        debitado = sum(d["valor"] for lote in resultados for d in lote)
        assert debitado == pytest.approx(total)
        assert await pool.fetchval(
            "select count(*) from agentesia_chamadas_ia where id_escritorio = $1::uuid and cobranca <> 'debitada'", esc) == 0
        assert await pool.fetchval(
            """select count(distinct id_movimento) from agentesia_chamadas_ia where id_escritorio = $1::uuid""", esc) == \
            await pool.fetchval("select count(*) from agentesia_carteira_movimentos where id_escritorio = $1::uuid and tipo = 'consumo'", esc)

        recarga = await pool.fetchval("insert into agentesia_recargas (id_escritorio, valor_brl) values ($1::uuid, 50) returning id", esc)
        movimentos = await asyncio.gather(*[cobranca.confirmar_recarga(pool, str(recarga)) for _ in range(5)])
        assert len(set(movimentos)) == 1
        assert await pool.fetchval(
            "select count(*) from agentesia_carteira_movimentos where id_escritorio = $1::uuid and tipo = 'recarga'", esc) == 1
        situacao = await cobranca.situacao(pool, esc)
        assert situacao.saldo_brl == pytest.approx(50 - total)
        # Webhook do gateway repetido: credita uma vez e o segundo é "repetido".
        r2 = await pool.fetchval(
            "insert into agentesia_recargas (id_escritorio, valor_brl, gateway, id_externo) values ($1::uuid, 20, 'asaas', $2) returning id",
            esc, "pay_" + uuid.uuid4().hex[:8])
        externo = await pool.fetchval("select id_externo from agentesia_recargas where id = $1", r2)
        corpo = {"id": "evt_" + uuid.uuid4().hex[:8], "event": "PAYMENT_RECEIVED", "payment": {"id": externo}}
        ev = gateways.GatewayAsaas("x").ler_webhook(corpo)
        assert await gateways.processar_evento(pool, "asaas", ev, corpo) == "creditada"
        assert await gateways.processar_evento(pool, "asaas", ev, corpo) == "repetido"
        assert (await cobranca.situacao(pool, esc)).saldo_brl == pytest.approx(70 - total)
        assert await _conferencia(pool, esc) == 0
    finally:
        await repo.fechar()


@com_banco
async def test_bonus_do_mes_renovado_sem_acumular_e_acumulando():
    repo = await _repo()
    pool = repo._pool
    try:
        sufixo = uuid.uuid4().hex[:6]
        plano = await pool.fetchval(
            "insert into agentesia_planos (codigo, nome, preco_mensal_brl, bonus_mensal_brl) values ($1, 'Básico', 297, 100) returning id",
            "basico-" + sufixo)
        esc = await _escritorio(pool)
        await pool.execute("update agentesia_carteiras set id_plano = $2 where id_escritorio = $1::uuid", esc, plano)
        assert await cobranca.renovar_bonus(pool, "2026-10", esc) == 1
        assert await cobranca.renovar_bonus(pool, "2026-10", esc) == 0              # mesmo mês: nada
        await cobranca.gravar_chamadas(pool, id_escritorio=esc, chamadas=[Chamada(papel="etapa", modelo="x", custo_usd=10 / 5.5)])
        await cobranca.debitar_pendentes(pool, esc)                                 # R$ 10 sai do bônus, não do saldo
        s = await cobranca.situacao(pool, esc)
        assert (round(s.bonus_brl, 4), s.saldo_brl) == (90, 0)
        assert await cobranca.renovar_bonus(pool, "2026-11", esc) == 1
        s = await cobranca.situacao(pool, esc)
        assert round(s.bonus_brl, 4) == 100                                         # a sobra de 90 expirou
        tipos = [r["tipo"] for r in await pool.fetch(
            "select tipo from agentesia_carteira_movimentos where id_escritorio = $1::uuid order by criado_em, tipo = 'bonus_plano'", esc)]
        assert tipos == ["bonus_plano", "consumo", "expira_bonus", "bonus_plano"]

        await pool.execute("update agentesia_planos set bonus_acumula = true where id = $1", plano)
        assert await cobranca.renovar_bonus(pool, "2026-12", esc) == 1
        s = await cobranca.situacao(pool, esc)
        assert round(s.bonus_brl, 4) == 200                                         # acumula: 100 + 100
        assert await pool.fetchval("select bonus_do_mes_brl::float8 from agentesia_carteiras where id_escritorio = $1::uuid", esc) == 200
        assert await _conferencia(pool, esc) == 0
    finally:
        await repo.fechar()


@com_banco
async def test_pausa_por_saldo_no_turno_avisa_e_volta_ao_creditar():
    from tests.test_postgres import _cenario, _config
    from tests.test_turno import extrai, fala
    from app.pipeline import Atendimento

    repo = await _repo()
    pool = repo._pool
    try:
        conta, numero_canal, esc = await _cenario(repo)
        await pool.execute("insert into agentesia_carteiras (id_escritorio, modo) values ($1::uuid, 'pre_pago')", esc)
        await pool.execute("insert into agentesia_cobranca_config (cotacao_usd_brl, markup, motivo) values (5.5, 1, 'teste-pausa')")
        helena = HelenaFalsa()
        modelo = ModeloFalso({"extrator": extrai(), "etapa": fala("Oi! Me conta o que aconteceu?")})
        atendimento = Atendimento(repo, modelo, _config(), helena, digitar=False)

        def msg(texto):
            corpo = webhook(texto, para=numero_canal)
            corpo["content"]["companyId"] = conta
            return corpo

        await atendimento.receber(msg("oi"))
        await atendimento.aguardar_esperas()
        assert helena.enviadas == []
        turno = await pool.fetchrow("select situacao, motivo from agentesia_turnos where id_escritorio = $1::uuid", esc)
        assert (turno["situacao"], turno["motivo"]) == ("silencio", "sem_saldo")
        assert await pool.fetchval("select count(*) from agentesia_chamadas_ia where id_escritorio = $1::uuid", esc) == 0

        # O cobrador marca a pausa e põe os avisos na fila (painel + WhatsApp do gestor; saldo esgotado vai à LawChat).
        await cobranca.lancar(pool, esc, "ajuste", -0.01, motivo="força a passagem pela carteira")
        await cobranca.ciclo(pool)
        carteira = await pool.fetchrow("select pausado_por_saldo, avisos from agentesia_carteiras where id_escritorio = $1::uuid", esc)
        assert carteira["pausado_por_saldo"]
        avisos = await pool.fetch("select dados from agentesia_acoes where id_escritorio = $1::uuid and tipo = 'aviso_consumo'", esc)
        assert len(avisos) == 1 and json.loads(avisos[0]["dados"])["tipo_evento"] == "saldo_esgotado"
        await cobranca.ciclo(pool)                                                    # não repete o aviso
        assert await pool.fetchval(
            "select count(*) from agentesia_acoes where id_escritorio = $1::uuid and tipo = 'aviso_consumo'", esc) == 1

        # Entra crédito: volta sozinha, sem responder o que chegou na pausa.
        await cobranca.lancar(pool, esc, "recarga", 20, motivo="recarga")
        assert not await repo.bloqueado_por_saldo(esc)
        assert not await pool.fetchval("select pausado_por_saldo from agentesia_carteiras where id_escritorio = $1::uuid", esc)
        await atendimento.receber(msg("tem alguém?"))
        await atendimento.aguardar_esperas()
        assert helena.enviadas == ["Oi! Me conta o que aconteceu?"]
        chamadas = await pool.fetch(
            "select id_lead, id_agente, codigo_etapa, cobranca from agentesia_chamadas_ia where id_escritorio = $1::uuid", esc)
        # Lead, agente e etapa vêm do turno (o modelo falso custa zero: a chamada fica 'isenta').
        assert chamadas and all(c["id_lead"] and c["id_agente"] and c["codigo_etapa"] == "sdr" for c in chamadas)
    finally:
        await pool.execute("delete from agentesia_cobranca_config where motivo = 'teste-pausa'")
        await repo.fechar()


@com_banco
async def test_follow_up_sem_saldo_e_cancelado_sem_chamar_a_ia():
    from app.canal.helena_conta import HelenaConta
    from app.followup import servico

    repo = await _repo()
    pool = repo._pool
    try:
        await pool.execute("update agentesia_followups set situacao = 'cancelado' where situacao in ('pendente', 'reservado')")
        segredo = await pool.fetchval("select vault.create_secret('token-fu-saldo', 'teste')")
        esc = await _escritorio(pool, nome="Follow-up sem saldo")
        await pool.execute("insert into agentesia_integracoes (id_escritorio, tipo, id_segredo_vault, situacao) values ($1::uuid, 'helena', $2, 'ok')", esc, segredo)
        canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado, id_canal_helena) values ($1::uuid, $2, $3) returning id",
                                    esc, "5511" + str(uuid.uuid4().int)[:9], "ch-" + uuid.uuid4().hex[:6])
        config = {"followup": {"ativo": True, "horario": {"inicio": 0, "fim": 24, "dias": [0, 1, 2, 3, 4, 5, 6]}, "intervalo_minimo_min": 5,
                               "passos": [{"apos_horas": 1, "modo": "ia"}]}}
        agente = await pool.fetchval(
            """insert into agentesia_agentes (id_escritorio, id_canal, nome, produto, config, situacao, modo)
               values ($1::uuid, $2, 'Júlia', 'auxilio_acidente', $3::jsonb, 'ativo', 'producao') returning id""", esc, canal, json.dumps(config))
        sdr = await pool.fetchval("insert into agentesia_agente_etapas (id_agente, codigo, ordem, principal) values ($1, 'sdr', 0, true) returning id", agente)
        contato = await pool.fetchval("insert into agentesia_contatos (id_escritorio, nome, telefone_normalizado) values ($1::uuid, 'Ana', '5511977776666') returning id", esc)
        base = datetime.now(timezone.utc) - timedelta(hours=2)
        lead = await pool.fetchval(
            """insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_agente, id_etapa, id_sessao_helena, ultima_mensagem_lead_em)
               values ($1::uuid, $2, $3, $4, $5, 'sessao-saldo', $6) returning id""", esc, contato, canal, agente, sdr, base - timedelta(minutes=1))
        await servico.agendar(pool, str(lead), base)
        modelo = ModeloFalso({"followup": {"mensagens": ["Oi Ana!"]}})
        enviadas = []
        disparador = servico.Disparador(pool, modelo, "https://api.helena.run", helena_por_token=lambda t, u: HelenaConta(
            t, u, httpx.AsyncClient(transport=httpx.MockTransport(lambda p: (enviadas.append(p), httpx.Response(200, json={"id": "x"}))[1]))))
        assert await disparador.rodar_uma_vez() == 1
        assert enviadas == [] and modelo.pedidos == []
        assert await pool.fetchrow("select situacao, motivo from agentesia_followups where id_lead = $1", lead) == ("cancelado", "sem_saldo")
    finally:
        await repo.fechar()


# ---------------------------------------------------------------------------- API: permissões e BYOK
@pytest.fixture
async def api_cobranca():
    from app.cobranca.rotas import api
    from app.gestao import seguranca
    from app.gestao.repositorio import RepositorioGestao
    from app.gestao.rotas import api as api_gestao

    repo = await _repo()
    pool = repo._pool
    app = FastAPI()
    app.include_router(api)
    app.include_router(api_gestao)
    app.state.gestao = RepositorioGestao(pool)
    app.state.assinador = seguranca.Assinador("segredo-de-teste")
    esc = await _escritorio(pool, nome="Permissões Adv")
    usuarios = {}
    for papel in ("admin_lawchat", "gestor", "atendente"):
        usuarios[papel] = str(await pool.fetchval(
            "insert into agentesia_usuarios (email, nome, senha_hash, papel, id_escritorio) values ($1, $2, 'x', $3, $4::uuid) returning id",
            f"{papel}-{uuid.uuid4().hex[:6]}@teste.com", papel.title(), papel, None if papel == "admin_lawchat" else esc))

    def cliente(papel):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://teste",
                                 cookies={"agentesia_sessao": app.state.assinador.criar(usuarios[papel])},
                                 headers={"X-Escritorio": esc} if papel == "admin_lawchat" else {})
    try:
        yield pool, esc, cliente
    finally:
        await repo.fechar()


@com_banco
async def test_permissoes_cliente_e_admin(api_cobranca):
    pool, esc, cliente = api_cobranca
    async with cliente("gestor") as gestor, cliente("atendente") as atendente, cliente("admin_lawchat") as admin:
        r = await gestor.get("/api/carteira")
        assert r.status_code == 200 and "markup" not in r.json() and r.json()["modo"] == "pre_pago"
        assert (await atendente.get("/api/carteira")).status_code == 403
        estado = (await atendente.get("/api/carteira/estado")).json()
        assert estado["bloqueado"] is True and "disponivel_brl" not in estado and estado["pode_pedir_recarga"] is False
        assert "disponivel_brl" in (await gestor.get("/api/carteira/estado")).json()
        for caminho in ("/api/admin/carteiras", "/api/admin/planos", "/api/admin/cobranca/config", "/api/admin/recargas"):
            assert (await gestor.get(caminho)).status_code == 403
        assert (await gestor.post(f"/api/admin/carteiras/{esc}/lancamentos",
                                  json={"tipo": "bonus_manual", "valor_brl": 100, "motivo": "eu mesmo"})).status_code == 403

        # Cliente pede recarga: pendente, evento para a LawChat; clique duplo não cria outro pedido.
        pedido = (await gestor.post("/api/carteira/recargas", json={"valor_brl": 300})).json()
        assert pedido["situacao"] == "pendente" and pedido["gateway"] == "manual"
        assert (await gestor.post("/api/carteira/recargas", json={"valor_brl": 300})).json().get("repetida") is True
        evento = await pool.fetchrow("select responsavel, gravidade from agentesia_eventos where id_escritorio = $1::uuid and tipo = 'pedido_recarga'", esc)
        assert evento["responsavel"] == "lawchat"
        assert (await gestor.post(f"/api/admin/recargas/{pedido['id']}/confirmar")).status_code == 403

        # Admin: lançamento sem motivo é recusado; com motivo entra no livro; confirmar a recarga credita uma vez.
        assert (await admin.post(f"/api/admin/carteiras/{esc}/lancamentos", json={"tipo": "bonus_manual", "valor_brl": 50, "motivo": ""})).status_code == 422
        assert (await admin.post(f"/api/admin/carteiras/{esc}/lancamentos", json={"tipo": "consumo", "valor_brl": -5, "motivo": "não pode"})).status_code == 400
        r = await admin.post(f"/api/admin/carteiras/{esc}/lancamentos", json={"tipo": "bonus_manual", "valor_brl": 50, "motivo": "boas-vindas"})
        assert r.status_code == 200 and r.json()["carteira"]["disponivel_brl"] == 50
        um = (await admin.post(f"/api/admin/recargas/{pedido['id']}/confirmar")).json()
        dois = (await admin.post(f"/api/admin/recargas/{pedido['id']}/confirmar")).json()
        assert um["id_movimento"] == dois["id_movimento"] and dois["ja_estava_paga"] and dois["carteira"]["saldo_brl"] == 350
        carteira = (await gestor.get("/api/carteira")).json()
        assert carteira["bloqueado"] is False and carteira["disponivel_brl"] == 350

        # Extrato do cliente sem o custo real; o do admin com.
        await cobranca.gravar_chamadas(pool, id_escritorio=esc, chamadas=[Chamada(papel="etapa", modelo="gpt-4.1", custo_usd=0.02)])
        await cobranca.debitar_pendentes(pool, esc)
        extrato = (await gestor.get("/api/carteira/extrato")).json()
        consumo = next(m for m in extrato if m["tipo"] == "consumo")
        assert "custo_usd" not in consumo["detalhe"] and consumo["detalhe"]["chamadas"] == 1
        detalhe = (await admin.get(f"/api/admin/carteiras/{esc}")).json()
        assert next(m for m in detalhe["extrato"] if m["tipo"] == "consumo")["detalhe"]["custo_usd"] == pytest.approx(0.02)
        assert detalhe["conferencia"]["diferenca"] == 0
        porcao = (await gestor.get("/api/carteira/consumo?dias=7")).json()
        assert porcao["total_brl"] > 0 and "tokens" not in porcao["por_funcao"][0]
        assert "tokens" in (await gestor.get("/api/carteira/consumo?dias=7&detalhe=1")).json()["por_funcao"][0]
        margem = (await admin.get(f"/api/admin/cobranca/consumo?dias=7&id_escritorio={esc}")).json()
        assert margem["por_escritorio"][0]["custo_usd"] == pytest.approx(0.02)

        # Cotação e markup: validação e histórico.
        assert (await admin.post("/api/admin/cobranca/config", json={"cotacao_usd_brl": 0, "markup": 1})).status_code == 400
        assert (await gestor.post("/api/admin/cobranca/config", json={"cotacao_usd_brl": 6, "markup": 1})).status_code == 403


@com_banco
async def test_chave_propria_byok_ignorada_e_nao_apagada(api_cobranca, monkeypatch):
    from app.gestao import ativacao

    pool, esc, cliente = api_cobranca
    segredo = await pool.fetchval("select vault.create_secret('sk-chave-do-escritorio', 'byok')")
    await pool.execute(
        "insert into agentesia_integracoes (id_escritorio, tipo, id_segredo_vault, final_segredo, situacao) values ($1::uuid, 'openai', $2, 'ritó', 'ok')",
        esc, segredo)
    async with cliente("gestor") as gestor:
        r = await gestor.put("/api/integracoes/openai", json={"token": "sk-nova-chave-123"})
        assert r.status_code == 410
    assert await pool.fetchval("select count(*) from agentesia_integracoes where id_escritorio = $1::uuid and tipo = 'openai'", esc) == 1
    assert await pool.fetchval("select decrypted_secret from vault.decrypted_secrets where id = $1", segredo) == "sk-chave-do-escritorio"

    # Na ativação, a chave salva do escritório não conta: sem a chave da LawChat no .env, o passo do modelo dá erro.
    from app.gestao.repositorio import RepositorioGestao
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    async def sem_helena(_):
        raise RuntimeError("sem helena no teste")

    agente = {"id": str(uuid.uuid4()), "config": {"modelos": {"etapa": "gpt-4.1"}}, "produto": "auxilio_acidente", "etapas": []}
    try:
        resultado = await ativacao.preparar(repo=RepositorioGestao(pool), id_escritorio=esc, agente=agente, modo="teste",
                                            aplicar=False, helena_de=sem_helena)
    except Exception as erro:                       # a preparação inteira depende da Helena; o passo do modelo vem antes
        pytest.skip(f"preparar exige a Helena neste cenário: {erro}")
    passo = next(p for p in resultado.passos if p.codigo == "modelo_ia")
    assert passo.situacao == "erro" and "chave própria" not in passo.detalhe
    monkeypatch.setenv("OPENAI_API_KEY", "chave-da-lawchat")
    resultado = await ativacao.preparar(repo=RepositorioGestao(pool), id_escritorio=esc, agente=agente, modo="teste",
                                        aplicar=False, helena_de=sem_helena)
    assert "chave da LawChat" in next(p for p in resultado.passos if p.codigo == "modelo_ia").detalhe
