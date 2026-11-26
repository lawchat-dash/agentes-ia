"""Desligar e religar a IA pela Helena: etiqueta "IA Desativada" e botão (antigo fluxo "IA - Desativar")."""

import json
import os
import uuid

import pytest

from app import ia_controle

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")


def test_reconhece_a_etiqueta_com_ou_sem_emoji():
    assert ia_controle._tem_etiqueta([{"name": "🤖 IA Desativada"}])
    assert ia_controle._tem_etiqueta(["ia desativada"])
    assert not ia_controle._tem_etiqueta([{"name": "Lead quente"}, "Contrato"])
    assert not ia_controle._tem_etiqueta(None)


@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_etiqueta_e_botao_desligam_e_religam():
    from app.banco.postgres import RepositorioPostgres

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        esc = await pool.fetchval("insert into agentesia_escritorios (nome) values ('Controle IA') returning id")
        canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado, id_canal_helena) values ($1, $2, $3) returning id",
                                    esc, "5531" + str(uuid.uuid4().int)[:9], "ch-" + uuid.uuid4().hex[:6])
        telefone = "55319" + str(uuid.uuid4().int)[:8]
        contato = await pool.fetchval("insert into agentesia_contatos (id_escritorio, nome, telefone_normalizado) values ($1, 'João', $2) returning id",
                                      esc, telefone)
        sessao = "sessao-" + uuid.uuid4().hex[:6]
        lead = await pool.fetchval("insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_sessao_helena) values ($1, $2, $3, $4) returning id",
                                   esc, contato, canal, sessao)
        await pool.execute("insert into agentesia_followups (id_escritorio, id_lead, passo, base, agendado_para) values ($1, $2, 0, now(), now())", esc, lead)

        # 1. Equipe põe a etiqueta na Helena: desliga, cancela o follow-up, deixa nota (sem mexer na etiqueta de novo).
        evento = {"eventType": "CONTACT_TAG_UPDATE", "content": {"phonenumber": "+" + telefone, "tags": [{"name": "🤖 IA Desativada"}]}}
        r = await ia_controle.receber_evento_de_etiqueta(pool, str(esc), evento)
        assert r["alterados"] == 1
        linha = await pool.fetchrow("select estado, motivo_estado, pausado_ate from agentesia_leads where id = $1", lead)
        assert (linha["estado"], linha["motivo_estado"], linha["pausado_ate"]) == ("pausado", "desativada_pela_equipe", None)
        assert await pool.fetchval("select situacao from agentesia_followups where id_lead = $1", lead) == "cancelado"
        tipos = [x["tipo"] for x in await pool.fetch("select tipo from agentesia_acoes where id_lead = $1", lead)]
        assert tipos == ["nota"]
        # Repetir o evento não faz nada (Helena manda o mesmo evento mais de uma vez).
        assert (await ia_controle.receber_evento_de_etiqueta(pool, str(esc), evento))["alterados"] == 0

        # 2. Tirar a etiqueta religa.
        evento["content"]["tags"] = [{"name": "Lead quente"}]
        assert (await ia_controle.receber_evento_de_etiqueta(pool, str(esc), evento))["alterados"] == 1
        assert await pool.fetchval("select estado from agentesia_leads where id = $1", lead) == "ativo"

        # 3. Pausa do atendente: mexer em outra etiqueta NÃO religa; o botão religa.
        await pool.execute("update agentesia_leads set estado = 'pausado', motivo_estado = 'humano_assumiu', pausado_ate = now() + interval '15 minutes' where id = $1", lead)
        assert (await ia_controle.receber_evento_de_etiqueta(pool, str(esc), evento))["alterados"] == 0
        r = await ia_controle.mudar_ia(pool, str(esc), ligar=True, origem="botao", id_sessao=sessao)
        assert r["alterados"] == 1 and await pool.fetchval("select estado from agentesia_leads where id = $1", lead) == "ativo"

        # 4. Botão desligar põe a etiqueta (pela fila) e deixa nota.
        r = await ia_controle.mudar_ia(pool, str(esc), ligar=False, origem="botao", id_sessao=sessao)
        assert r["alterados"] == 1 and r["codigo"].startswith("DES-")
        etiquetas = [json.loads(r["dados"]) for r in await pool.fetch("select dados from agentesia_acoes where id_lead = $1 and tipo = 'etiquetar'", lead)]
        assert {"adicionar": [], "remover": ["🤖 IA Desativada"]} in etiquetas          # religar pelo botão tira a etiqueta
        assert {"adicionar": ["🤖 IA Desativada"], "remover": []} in etiquetas          # desligar pelo botão põe
        assert await pool.fetchval("select count(*) from agentesia_alteracoes where id_escritorio = $1 and acao = 'desligou_ia'", esc) == 2

        # Sem sessão e sem telefone: nada a fazer; outro evento qualquer: não é com a gente.
        assert (await ia_controle.mudar_ia(pool, str(esc), ligar=False, origem="botao"))["motivo"] == "sem_sessao_nem_telefone"
        assert await ia_controle.receber_evento_de_etiqueta(pool, str(esc), {"eventType": "MESSAGE_RECEIVED"}) is None
    finally:
        await repo.fechar()
