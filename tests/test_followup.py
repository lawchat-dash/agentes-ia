"""Follow-up (antigos "Follow Up Unificado"): cadência, horário comercial, envio, cancelamento e desistência."""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.canal.helena_conta import HelenaConta
from app.followup import regras
from app.modelo import ModeloFalso

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
BRT = timezone(timedelta(hours=-3))


def test_horario_comercial_empurra_para_a_proxima_abertura():
    c = regras.Config.de({"horario": {"inicio": 8, "fim": 20, "dias": [0, 1, 2, 3, 4, 5]}})
    sabado_noite = datetime(2026, 11, 21, 21, 0, tzinfo=BRT)          # sábado 21h; domingo fechado
    segunda = regras.ajustar_ao_horario(sabado_noite, c)
    assert (segunda.weekday(), segunda.hour) == (0, 8)
    terca_cedo = datetime(2026, 11, 24, 6, 30, tzinfo=BRT)
    assert regras.ajustar_ao_horario(terca_cedo, c).hour == 8
    dentro = datetime(2026, 11, 24, 15, 0, tzinfo=BRT)
    assert regras.ajustar_ao_horario(dentro, c) == dentro
    espalhado = regras.ajustar_ao_horario(sabado_noite, c, semente="lead-1")
    assert espalhado.hour == 8 and 0 <= espalhado.minute < 40


def test_cadencia_padrao_e_validacao():
    c = regras.Config.de({})
    assert [p.apos_horas for p in c.passos] == [1, 24, 72, 168] and not c.ativo           # padrão OAB/Meta: 4 toques
    base = datetime(2026, 11, 24, 10, 0, tzinfo=BRT)                     # terça 10h
    assert regras.horario_do_passo(base, 0, c) == base + timedelta(hours=1)
    assert regras.horario_do_passo(base, 4, c) is None
    with pytest.raises(ValueError, match="início"):
        regras.validar({"horario": {"inicio": 20, "fim": 8}})
    with pytest.raises(ValueError, match="texto"):
        regras.validar({"passos": [{"apos_horas": 1, "modo": "texto"}]})
    with pytest.raises(ValueError, match="mesmo tempo"):
        regras.validar({"passos": [{"apos_horas": 2}, {"apos_horas": 2}]})
    limpo = regras.validar({"ativo": True, "passos": [{"apos_horas": 24}, {"apos_horas": 1, "modo": "texto", "texto": "Oi {nome}!"}]})
    assert [p["apos_horas"] for p in limpo["passos"]] == [1, 24]                     # em ordem
    assert regras.preencher("Oi {nome}! Tudo bem?", nome="Maria da Silva") == "Oi Maria! Tudo bem?"
    assert regras.preencher("Oi {nome}!", nome=None) == "Oi!"


@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_envia_segue_a_cadencia_cancela_e_desiste():
    from app.banco.postgres import RepositorioPostgres
    from app.followup import servico

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        await pool.execute("update agentesia_followups set situacao = 'cancelado' where situacao in ('pendente', 'reservado')")
        segredo = await pool.fetchval("select vault.create_secret('token-fu', 'teste')")
        esc = await pool.fetchval("insert into agentesia_escritorios (nome) values ('Follow-up Adv') returning id")
        await pool.execute("insert into agentesia_integracoes (id_escritorio, tipo, id_segredo_vault, situacao) values ($1, 'helena', $2, 'ok')", esc, segredo)
        canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado, id_canal_helena) values ($1, $2, $3) returning id",
                                    esc, "5511" + str(uuid.uuid4().int)[:9], "ch-" + uuid.uuid4().hex[:6])
        config = {"followup": {"ativo": True, "horario": {"inicio": 0, "fim": 24, "dias": [0, 1, 2, 3, 4, 5, 6]}, "intervalo_minimo_min": 5,
                               "passos": [{"apos_horas": 1, "modo": "texto", "texto": "Oi {nome}! Conseguiu ver minha última mensagem?"},
                                          {"apos_horas": 24, "modo": "ia", "instrucao": "pergunte se ficou dúvida"}],
                               "desistir": {"ativo": True, "apos_horas": 24}}}
        agente = await pool.fetchval(
            """insert into agentesia_agentes (id_escritorio, id_canal, nome, produto, config, situacao, modo, numeros_teste)
               values ($1, $2, 'Júlia', 'auxilio_acidente', $3::jsonb, 'ativo', 'teste', '{5511988881111}') returning id""",
            esc, canal, json.dumps(config))
        sdr = await pool.fetchval("insert into agentesia_agente_etapas (id_agente, codigo, ordem, principal) values ($1, 'sdr', 0, true) returning id", agente)
        contato = await pool.fetchval("insert into agentesia_contatos (id_escritorio, nome, telefone_normalizado) values ($1, 'Maria da Silva', '5511988881111') returning id", esc)
        base = datetime.now(timezone.utc) - timedelta(hours=2)
        lead = await pool.fetchval(
            """insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_agente, id_etapa, id_sessao_helena, ultima_mensagem_lead_em)
               values ($1, $2, $3, $4, $5, 'sessao-fu', $6) returning id""", esc, contato, canal, agente, sdr, base - timedelta(minutes=1))

        quando = await servico.agendar(pool, str(lead), base)
        assert quando is not None and abs((quando - (base + timedelta(hours=1))).total_seconds()) < 60

        enviadas = []

        def helena(pedido: httpx.Request) -> httpx.Response:
            if pedido.url.path == "/chat/v1/session/sessao-fu/message":
                enviadas.append(json.loads(pedido.content))
                return httpx.Response(200, json={"id": f"fu-{uuid.uuid4().hex[:8]}"})
            return httpx.Response(404)

        modelo = ModeloFalso({"followup": {"mensagens": ["Oi Maria! Ficou alguma dúvida sobre o seu caso?"]}})
        disparador = servico.Disparador(pool, modelo, "https://api.helena.run", helena_por_token=lambda t, u: HelenaConta(
            t, u, httpx.AsyncClient(transport=httpx.MockTransport(helena))))
        assert await disparador.rodar_uma_vez() == 1
        assert enviadas[0]["text"] == "Oi Maria! Conseguiu ver minha última mensagem?"
        linhas = [dict(r) for r in await pool.fetch("select passo, situacao from agentesia_followups where id_lead = $1 order by criado_em", lead)]
        assert linhas == [{"passo": 0, "situacao": "enviado"}, {"passo": 1, "situacao": "pendente"}]
        assert await pool.fetchval("select count(*) from agentesia_mensagens where id_lead = $1 and autor = 'ia'", lead) == 1

        # Passo 2 vencido: a IA escreve.
        await pool.execute("update agentesia_followups set agendado_para = now() where id_lead = $1 and situacao = 'pendente'", lead)
        await pool.execute("update agentesia_mensagens set enviada_em = now() - interval '1 hour' where id_lead = $1", lead)
        await disparador.rodar_uma_vez()
        assert enviadas[-1]["text"] == "Oi Maria! Ficou alguma dúvida sobre o seu caso?"
        assert modelo.pedidos[-1]["papel"] == "followup" and "pergunte se ficou dúvida" in modelo.pedidos[-1]["sistema"]
        desistencia = await pool.fetchrow("select passo, situacao from agentesia_followups where id_lead = $1 and situacao = 'pendente'", lead)
        assert desistencia["passo"] == 2                                        # depois do último: a desistência

        # Desistência vencida: encerra a IA para o lead e põe a nota na fila.
        await pool.execute("update agentesia_followups set agendado_para = now() where id_lead = $1 and situacao = 'pendente'", lead)
        await pool.execute("update agentesia_mensagens set enviada_em = now() - interval '1 hour' where id_lead = $1", lead)
        await disparador.rodar_uma_vez()
        estado = await pool.fetchrow("select estado, motivo_estado from agentesia_leads where id = $1", lead)
        assert (estado["estado"], estado["motivo_estado"]) == ("encerrado", "sem_resposta_followup")
        notas = [r["texto"] for r in await pool.fetch(
            "select dados->>'texto' as texto from agentesia_acoes where id_lead = $1 and tipo = 'nota' order by criado_em", lead)]
        assert [n.split(" enviado às ")[0] for n in notas[:2]] == ["🔁 Follow-up 1 de 2", "🔁 Follow-up 2 de 2"]
        assert all(n.endswith("(etapa Primeiro atendimento).") and " pelo agente " in n for n in notas[:2])
        assert notas[2:] == [regras.NOTA_DESISTENCIA]                       # uma nota por envio e a da desistência

        # Lead responde: o próximo envio é cancelado na hora da conferência.
        await pool.execute("update agentesia_leads set estado = 'ativo', motivo_estado = null where id = $1", lead)
        nova_base = datetime.now(timezone.utc) - timedelta(hours=2)
        await servico.agendar(pool, str(lead), nova_base)
        await pool.execute("update agentesia_followups set agendado_para = now() where id_lead = $1 and situacao = 'pendente'", lead)
        await pool.execute("update agentesia_leads set ultima_mensagem_lead_em = now() where id = $1", lead)
        total = len(enviadas)
        await disparador.rodar_uma_vez()
        assert len(enviadas) == total
        assert await pool.fetchval("select motivo from agentesia_followups where id_lead = $1 order by atualizado_em desc limit 1", lead) == "lead_respondeu"

        # Número fora dos de teste (agente em modo teste): não recebe follow-up.
        await pool.execute("update agentesia_agentes set numeros_teste = '{}' where id = $1", agente)
        await pool.execute("update agentesia_leads set ultima_mensagem_lead_em = now() - interval '3 hours' where id = $1", lead)
        await servico.agendar(pool, str(lead), datetime.now(timezone.utc) - timedelta(hours=2))
        await pool.execute("update agentesia_followups set agendado_para = now() where id_lead = $1 and situacao = 'pendente'", lead)
        await disparador.rodar_uma_vez()
        assert await pool.fetchval("select motivo from agentesia_followups where id_lead = $1 order by atualizado_em desc limit 1", lead) == "modo_teste"
    finally:
        await repo.fechar()
