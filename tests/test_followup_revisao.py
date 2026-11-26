"""Revisão do follow-up (26/11): bugs achados e corrigidos.

1. Desistência agendada com a desistência desligada (ou cadência encurtada) encerrava o lead: agora cancela.
2. Salvar a cadência reprograma os follow-ups já agendados do agente (tempo novo; toque que sumiu é cancelado).
3. Número torto na config vira mensagem em português (não "invalid literal for int()").
4. Motivos novos em português (IA desligada, lead suspeito, sem saldo, cadência alterada...).
5. A tela do agente recebe quais etapas podem ter follow-up e o resumo certo (4 toques no padrão, não 7).
Sem IA paga: ModeloFalso. Os testes com banco só rodam com AGENTESIA_TESTE_PG_URL.
"""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.canal.helena_conta import HelenaConta
from app.followup import regras
from app.gestao import rotas_followup
from app.modelo import ModeloFalso
from tests.test_gestao import _entrar, ambiente  # noqa: F401  (fixture)

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
pg = pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
TODO_DIA = {"inicio": 0, "fim": 24, "dias": [0, 1, 2, 3, 4, 5, 6]}


# ------------------------------------------------------------------ sem banco
def test_numero_torto_vira_mensagem_em_portugues():
    for torto in ({"horario": {"inicio": "x"}}, {"passos": ["a"]}, {"intervalo_minimo_min": "abc"},
                  {"horario": {"dias": ["seg"]}}, {"desistir": {"apos_horas": "muito"}}):
        with pytest.raises(ValueError, match="Configuração do follow-up inválida"):
            regras.validar(torto)
    with pytest.raises(ValueError, match="10 minutos e 90 dias"):              # as mensagens próprias seguem iguais
        regras.validar({"passos": [{"apos_horas": 0.05}]})
    with pytest.raises(ValueError, match="inválida"):
        regras.validar("não é objeto")  # type: ignore[arg-type]
    assert regras.validar({"passos": [{"apos_horas": 10 / 60}]})["passos"][0]["apos_horas"] == pytest.approx(10 / 60)


def test_motivos_novos_em_portugues():
    for codigo in ("ia_desativada", "lead_suspeito", "sem_saldo", "cadencia_alterada", "lead_pausado", "lead_encerrado",
                   "ia_desligada_durante_o_envio", "produto_na_lixeira"):
        texto = rotas_followup.motivo_legivel(codigo)
        assert texto and "_" not in texto and texto != codigo.replace("_", " ")


# ------------------------------------------------------------------ com banco
async def _cenario(pool, config_followup, *, passo_pendente=None, base_h=2.0):
    segredo = await pool.fetchval("select vault.create_secret($1, 'teste')", "token-" + uuid.uuid4().hex[:6])
    esc = await pool.fetchval("insert into agentesia_escritorios (nome) values ($1) returning id", f"Revisão {uuid.uuid4().hex[:5]}")
    await pool.execute("insert into agentesia_integracoes (id_escritorio, tipo, id_segredo_vault, situacao) values ($1, 'helena', $2, 'ok')", esc, segredo)
    tel = "5511" + str(uuid.uuid4().int)[:9]
    canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado, id_canal_helena) values ($1, $2, $3) returning id",
                                esc, "5511" + str(uuid.uuid4().int)[:9], "ch-" + uuid.uuid4().hex[:6])
    agente = await pool.fetchval(
        """insert into agentesia_agentes (id_escritorio, id_canal, nome, produto, config, situacao, modo, numeros_teste)
           values ($1, $2, 'Júlia', 'auxilio_acidente', $3::jsonb, 'ativo', 'teste', $4) returning id""",
        esc, canal, json.dumps({"followup": config_followup}), [tel])
    sdr = await pool.fetchval("insert into agentesia_agente_etapas (id_agente, codigo, ordem, principal) values ($1, 'sdr', 0, true) returning id", agente)
    contato = await pool.fetchval("insert into agentesia_contatos (id_escritorio, nome, telefone_normalizado) values ($1, 'Rita', $2) returning id", esc, tel)
    base = datetime.now(timezone.utc) - timedelta(hours=base_h)
    lead = await pool.fetchval(
        """insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_agente, id_etapa, id_sessao_helena, ultima_mensagem_lead_em)
           values ($1, $2, $3, $4, $5, $6, $7) returning id""", esc, contato, canal, agente, sdr, "sessao-" + uuid.uuid4().hex[:6],
        base - timedelta(minutes=1))
    if passo_pendente is not None:
        await pool.execute("""insert into agentesia_followups (id_escritorio, id_lead, id_agente, passo, base, agendado_para)
                              values ($1, $2, $3, $4, $5, now() - interval '1 minute')""", esc, lead, agente, passo_pendente, base)
    return esc, agente, lead, base


def _disparador(pool, enviadas):
    from app.followup import servico

    def helena(pedido: httpx.Request) -> httpx.Response:
        enviadas.append(pedido.url.path)
        return httpx.Response(200, json={"id": f"fu-{uuid.uuid4().hex[:8]}"})

    return servico.Disparador(pool, ModeloFalso({"followup": {"mensagens": ["Oi Rita! Ficou alguma dúvida?"]}}),
                              "https://api.helena.run", helena_por_token=lambda t, u: HelenaConta(
                                  t, u, httpx.AsyncClient(transport=httpx.MockTransport(helena))))


@pg
async def test_desistencia_com_desistir_desligado_nao_encerra_o_lead():
    from app.banco.postgres import RepositorioPostgres
    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        await pool.execute("update agentesia_followups set situacao = 'cancelado' where situacao in ('pendente', 'reservado')")
        # Era a desistência de uma cadência de 2 toques; o dono desligou a desistência depois. Antes: o lead era encerrado.
        config = {"ativo": True, "horario": TODO_DIA, "intervalo_minimo_min": 5, "decidir": False,
                  "passos": [{"apos_horas": 1}, {"apos_horas": 24}], "desistir": {"ativo": False}}
        _, _, lead, _ = await _cenario(pool, config, passo_pendente=2, base_h=30)
        enviadas: list[str] = []
        assert await _disparador(pool, enviadas).rodar_uma_vez() == 1
        assert enviadas == []
        assert await pool.fetchval("select estado from agentesia_leads where id = $1", lead) == "ativo"
        linha = await pool.fetchrow("select situacao, motivo from agentesia_followups where id_lead = $1", lead)
        assert (linha["situacao"], linha["motivo"]) == ("cancelado", "cadencia_alterada")
    finally:
        await repo.fechar()


@pg
async def test_reprogramar_segue_a_cadencia_nova():
    from app.banco.postgres import RepositorioPostgres
    from app.followup import servico
    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        antes = {"ativo": True, "horario": TODO_DIA, "passos": [{"apos_horas": 1}, {"apos_horas": 24}, {"apos_horas": 72}],
                 "desistir": {"ativo": True, "apos_horas": 24}}
        # Lead A no 2º toque (24 h); lead B no 3º (72 h); lead C na desistência (passo 3).
        _, agente, lead_a, base = await _cenario(pool, antes, passo_pendente=1)
        esc = await pool.fetchval("select id_escritorio from agentesia_agentes where id = $1", agente)
        outros = []
        for passo in (2, 3):
            contato = await pool.fetchval("insert into agentesia_contatos (id_escritorio, nome, telefone_normalizado) values ($1, 'X', $2) returning id",
                                          esc, "5511" + str(uuid.uuid4().int)[:9])
            canal = await pool.fetchval("select id_canal from agentesia_agentes where id = $1", agente)
            lead = await pool.fetchval("""insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_agente)
                                          values ($1, $2, $3, $4) returning id""", esc, contato, canal, agente)
            await pool.execute("""insert into agentesia_followups (id_escritorio, id_lead, id_agente, passo, base, agendado_para)
                                  values ($1, $2, $3, $4, $5, now() + interval '3 days')""", esc, lead, agente, passo, base)
            outros.append(lead)
        lead_b, lead_c = outros
        # Cadência nova: 2 toques (1 h e 5 h), desistência ligada.
        depois = regras.validar({**antes, "passos": [{"apos_horas": 1}, {"apos_horas": 5}]})
        feito = await servico.reprogramar_do_agente(pool, str(agente), antes, depois)
        assert feito == {"reprogramados": 2, "cancelados": 1}
        a = await pool.fetchrow("select situacao, agendado_para from agentesia_followups where id_lead = $1", lead_a)
        assert a["situacao"] == "pendente" and abs((a["agendado_para"] - (base + timedelta(hours=5))).total_seconds()) < 60
        b = await pool.fetchrow("select situacao, motivo from agentesia_followups where id_lead = $1", lead_b)
        assert (b["situacao"], b["motivo"]) == ("cancelado", "cadencia_alterada")            # o 3º toque deixou de existir
        c = await pool.fetchrow("select situacao, passo from agentesia_followups where id_lead = $1", lead_c)
        assert (c["situacao"], c["passo"]) == ("pendente", 2)                                # desistência da cadência nova
        # Desistência desligada: a que estava agendada sai.
        sem_desistir = regras.validar({**depois, "desistir": {"ativo": False}})
        assert (await servico.reprogramar_do_agente(pool, str(agente), depois, sem_desistir))["cancelados"] == 1
        assert await pool.fetchval("select situacao from agentesia_followups where id_lead = $1", lead_c) == "cancelado"
    finally:
        await repo.fechar()


@pg
async def test_tela_do_agente_liga_salva_e_mostra_agendados(ambiente):  # noqa: F811
    cliente, _simulada, email_admin, banco = ambiente
    pool = banco._pool
    await _entrar(cliente, email_admin, "senha-admin-123")
    escritorio = (await cliente.post("/api/admin/escritorios", json={
        "nome": f"Tela FU {uuid.uuid4().hex[:5]}", "id_conta_helena": str(uuid.uuid4()),
        "token_helena": f"token-bom-{uuid.uuid4().hex[:8]}"})).json()["escritorio"]
    h = {"x-escritorio": escritorio["id"]}
    canais = (await cliente.get("/api/integracoes", headers=h)).json()["canais"]
    comum = next(c for c in canais if c["tipo"] != "oficial")
    agente = (await cliente.post("/api/agentes", headers=h, json={"nome": "Júlia", "id_canal": comum["id"]})).json()

    # Nunca configurado: desligado, cadência padrão de 4 toques (antes o resumo dizia 7).
    assert (await cliente.get(f"/api/agentes/{agente['id']}", headers=h)).json()["followup_resumo"]["passos"] == 4
    tela = (await cliente.get(f"/api/agentes/{agente['id']}/followup", headers=h)).json()
    assert tela["configurado"] is False and tela["config"]["ativo"] is False
    pode = {e["codigo"]: e["pode_followup"] for e in tela["etapas"]}
    assert pode.get("sdr") is True and pode.get("desqualificado") is not True

    # Erro claro ao salvar (nada de falhar calado).
    torto = await cliente.put(f"/api/agentes/{agente['id']}/followup", headers=h,
                              json={**tela["config"], "ativo": True, "passos": [{"apos_horas": 2}, {"apos_horas": 2}]})
    assert torto.status_code == 400 and "mesmo tempo" in torto.json()["detail"]

    # Liga e monta a cadência: 30 min e 1 dia, das 9h às 18h, só no primeiro atendimento.
    salvo = await cliente.put(f"/api/agentes/{agente['id']}/followup", headers=h, json={
        **tela["config"], "ativo": True, "horario": {"inicio": 9, "fim": 18, "dias": [0, 1, 2, 3, 4]}, "etapas": ["sdr", "nao_existe"],
        "passos": [{"apos_horas": 0.5, "modo": "ia", "instrucao": "", "texto": ""}, {"apos_horas": 24, "modo": "ia", "instrucao": "", "texto": ""}]})
    assert salvo.status_code == 200, salvo.text
    corpo = salvo.json()
    assert corpo["ativo"] is True and corpo["etapas"] == ["sdr"] and corpo["reprogramacao"] == {"reprogramados": 0, "cancelados": 0}
    relida = (await cliente.get(f"/api/agentes/{agente['id']}/followup", headers=h)).json()
    assert relida["configurado"] is True and [p["apos_horas"] for p in relida["config"]["passos"]] == [0.5, 24]
    assert relida["config"]["horario"] == {"inicio": 9, "fim": 18, "dias": [0, 1, 2, 3, 4]}
    resumo = (await cliente.get(f"/api/agentes/{agente['id']}", headers=h)).json()["followup_resumo"]
    assert resumo == {"ativo": True, "passos": 2, "resumo": ["30 min", "24 h"]}

    # Agendados e já enviados/cancelados aparecem com o motivo em português.
    contato = await pool.fetchval("insert into agentesia_contatos (id_escritorio, nome, telefone_normalizado) values ($1::uuid, 'Lia', '5511977776666') returning id",
                                  escritorio["id"])
    lead = await pool.fetchval("""insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_agente, estado)
                                  values ($1::uuid, $2, $3::uuid, $4::uuid, 'ativo') returning id""", escritorio["id"], contato, comum["id"], agente["id"])
    await pool.execute("""insert into agentesia_followups (id_escritorio, id_lead, id_agente, passo, base, agendado_para, situacao, motivo)
                          values ($1::uuid, $2, $3::uuid, 0, now() - interval '1 day', now() - interval '1 day', 'cancelado', 'ia_desativada')""",
                       escritorio["id"], lead, agente["id"])
    await pool.execute("""insert into agentesia_followups (id_escritorio, id_lead, id_agente, passo, base, agendado_para)
                          values ($1::uuid, $2, $3::uuid, 1, now(), now() + interval '2 hours')""", escritorio["id"], lead, agente["id"])
    relida = (await cliente.get(f"/api/agentes/{agente['id']}/followup", headers=h)).json()
    assert [(p["passo"], p["desistencia"]) for p in relida["proximos"]] == [(1, False)]
    assert relida["recentes"][0]["motivo_texto"] == "a IA foi desligada nesta conversa"

    # Desligar cancela os agendados e diz quantos.
    desligado = (await cliente.put(f"/api/agentes/{agente['id']}/followup", headers=h, json={**relida["config"], "ativo": False})).json()
    assert desligado["ativo"] is False and desligado["reprogramacao"]["cancelados"] == 1
