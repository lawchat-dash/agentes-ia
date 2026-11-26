"""Nota do lead de 0 a 10 com motivos (app/cerebro/temperatura.py, ANALISE_5_PROJETOS B8).

Sem banco: a tabela de casos da função pura e o texto do aviso (sem CPF).
Com banco (AGENTESIA_TESTE_PG_URL): o gancho de fim de turno grava "_temperatura" e, na primeira vez que o lead fica
quente, sai o evento lead_quente e o aviso à equipe com nome, benefício, nota e motivos; uma vez só por lead.
"""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app import automacoes, notificacoes
from app.cerebro import temperatura
from app.cerebro.temperatura import nota_do_lead

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
T0 = datetime(2026, 11, 24, 10, 0, tzinfo=timezone.utc)


def conversa(*minutos_para_responder: float) -> list[dict]:
    """IA fala, lead responde depois de N minutos, várias vezes."""
    msgs, t = [], T0
    for n in minutos_para_responder:
        msgs.append({"autor": "ia", "enviada_em": t, "texto": "Pergunta"})
        t += timedelta(minutes=n)
        msgs.append({"autor": "lead", "enviada_em": t, "texto": "Resposta"})
        t += timedelta(minutes=1)
    return msgs


CLT_COM_SEQUELA = {"sequela": "sim", "vinculo_na_data": "clt", "aposentado": "nao", "tem_advogado_no_caso": "nao"}


@pytest.mark.parametrize("fatos, etapa, mensagens, contrato, intencoes, nota, faixa", [
    # CLT, com sequela, aceitou e responde rápido: quente
    (CLT_COM_SEQUELA, "closer", conversa(2, 5), None, {"aceitou_honorarios"}, 7, "quente"),
    # ... e pediu o link e assinou: 10
    (CLT_COM_SEQUELA, "assinatura", conversa(2), {"situacao": "assinado"}, {"aceitou_honorarios", "pediu_link"}, 10, "quente"),
    # contrato só gerado: +1
    (CLT_COM_SEQUELA, "assinatura", conversa(90), "gerado", set(), 7, "quente"),
    # sequela e segurado, devagar: morno
    (CLT_COM_SEQUELA, "sdr", conversa(120, 300), None, set(), 4, "morno"),
    # desempregado sem sequela informada, sem seguro: frio
    ({"vinculo_na_data": "desempregado"}, "sdr", conversa(200), None, set(), 0, "frio"),
    # período de graça (seguro-desemprego) + sequela + rápido
    ({"vinculo_na_data": "desempregado", "seguro_desemprego": "sim", "sequela": "sim"}, "sdr", conversa(3), None, set(), 5, "morno"),
    # catálogo: condição de saúde por outro nome e qualidade de segurado
    ({"tem_condicao": "sim", "qualidade_de_segurado": "sim"}, "sdr", [], None, set(), 4, "morno"),
])
def test_tabela_de_casos(fatos, etapa, mensagens, contrato, intencoes, nota, faixa):
    r = nota_do_lead(fatos, etapa, mensagens, contrato, intencoes=intencoes)
    assert (r["nota"], r["faixa"]) == (nota, faixa), r["motivos"]
    assert all(m.startswith("+") for m in r["motivos"]) and sum(int(m.split()[0]) for m in r["motivos"]) == nota


def test_motivos_legiveis():
    r = nota_do_lead(CLT_COM_SEQUELA, "closer", conversa(2), None, intencoes={"aceitou_honorarios", "pediu_link"})
    assert r["motivos"] == ["+2 ficou com sequela", "+2 tinha carteira assinada na época", "+1 responde rápido",
                            "+2 aceitou a proposta", "+1 pediu o link do contrato"]
    # Sem a intenção marcada: a etapa de contrato conta como aceite e "link" na mensagem do lead conta como pedido.
    msgs = conversa(2) + [{"autor": "lead", "enviada_em": T0 + timedelta(hours=1), "texto": "me manda o link de novo"}]
    r = nota_do_lead(CLT_COM_SEQUELA, "contratos", msgs, None)
    assert "+2 aceitou a proposta e passou para o contrato" in r["motivos"] and "+1 pediu o link do contrato" in r["motivos"]


@pytest.mark.parametrize("fatos, etapa, intencoes, ultima, motivo", [
    ({**CLT_COM_SEQUELA, "aposentado": "sim"}, "closer", set(), None, "zerada: já é aposentado"),
    ({**CLT_COM_SEQUELA, "tem_advogado_no_caso": "sim"}, "closer", set(), None, "zerada: já tem advogado no caso"),
    ({**CLT_COM_SEQUELA, "sequela": "nao"}, "closer", set(), None, "zerada: disse que não ficou com sequela"),
    ({**CLT_COM_SEQUELA, "vinculo_na_data": "servidor_estatutario"}, "sdr", set(), None, "zerada: servidor estatutário"),
    (CLT_COM_SEQUELA, "desqualificado", set(), None, "zerada: lead desqualificado"),
    (CLT_COM_SEQUELA, "closer", {"engano"}, None, "zerada: disse que foi engano"),
    (CLT_COM_SEQUELA, "closer", set(), "pare de me mandar mensagem", "zerada: pediu para não receber mais mensagens"),
])
def test_desqualificadores_zeram(fatos, etapa, intencoes, ultima, motivo):
    msgs = conversa(1) + ([{"autor": "lead", "enviada_em": T0 + timedelta(hours=2), "texto": ultima}] if ultima else [])
    r = nota_do_lead(fatos, etapa, msgs, {"situacao": "assinado"}, intencoes=intencoes | {"aceitou_honorarios"})
    assert r["nota"] == 0 and r["faixa"] == "frio" and motivo in r["motivos"]


def test_fatos_de_controle_e_vazios_nao_quebram():
    assert nota_do_lead(None, None, None) == {"nota": 0, "faixa": "frio", "motivos": []}
    assert nota_do_lead({"_temperatura": {"nota": 9}}, "sdr", [{"autor": "lead", "texto": "oi"}])["nota"] == 0


def test_aviso_do_lead_quente_tem_nota_e_motivos_e_nunca_cpf():
    valores = notificacoes.valores_do_aviso(evento="lead_quente", nome="Maria 123.456.789-09", telefone="5511988887777",
                                            produto="Auxílio-Acidente", etapa="closer", mensagem_lead="meu cpf 12345678909")
    texto = notificacoes.texto_lead_quente(notificacoes.MODELO_PADRAO, valores, nota=8, faixa="quente",
                                           motivos="+2 ficou com sequela; +2 aceitou a proposta", beneficio="Auxílio-Acidente")
    assert texto.startswith("🔔 *Lead quente*")
    assert "Benefício: Auxílio-Acidente" in texto and "Nota: 8/10 (quente)" in texto
    assert "Motivos: +2 ficou com sequela; +2 aceitou a proposta" in texto and "(11) 98888-7777" in texto
    assert "123.456.789-09" not in texto and "12345678909" not in texto and "Mensagem do lead" not in texto
    # Modelo próprio para lead quente com os marcadores: não repete as linhas.
    proprio = notificacoes.texto_lead_quente(notificacoes.MODELO_LEAD_QUENTE, valores, nota=8, faixa="quente",
                                             motivos="+2 ficou com sequela", beneficio="Auxílio-Acidente")
    assert proprio.count("Nota:") == 1 and proprio.count("Benefício:") == 1
    assert {"nota", "motivos", "beneficio"} <= set(notificacoes.MARCADORES)
    assert notificacoes.NOMES_DE_EVENTO["lead_quente"] == "Lead quente"
    assert "lead_quente" in automacoes.GATILHOS_FIXOS and "lead_parado" in automacoes.GATILHOS_FIXOS


# ------------------------------------------------------------------ banco local
@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_gancho_grava_a_nota_e_avisa_lead_quente_uma_vez():
    from app.banco.postgres import RepositorioPostgres
    from app.followup import servico

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        esc = await pool.fetchval("insert into agentesia_escritorios (nome) values ('Nota Adv') returning id")
        canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado, id_canal_helena) values ($1, $2, $3) returning id",
                                    esc, "5511" + str(uuid.uuid4().int)[:9], "ch-" + uuid.uuid4().hex[:6])
        config = {"funcoes": {"avisos": True, "crm": True},
                  "automacoes": {"lead_quente": {"adicionar_etiquetas": ["🔥 Quente"]}}}
        agente = await pool.fetchval(
            """insert into agentesia_agentes (id_escritorio, id_canal, nome, produto, config, situacao, modo)
               values ($1, $2, 'Júlia', 'auxilio_acidente', $3::jsonb, 'ativo', 'producao') returning id""", esc, canal, json.dumps(config))
        closer = await pool.fetchval("insert into agentesia_agente_etapas (id_agente, codigo, ordem, principal) values ($1, 'closer', 1, false) returning id", agente)
        contato = await pool.fetchval("insert into agentesia_contatos (id_escritorio, nome, telefone_normalizado) values ($1, 'Maria da Silva', $2) returning id",
                                      esc, "55119" + str(uuid.uuid4().int)[:8])
        lead = await pool.fetchval(
            """insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_agente, id_etapa, id_sessao_helena)
               values ($1, $2, $3, $4, $5, 'sessao-nota') returning id""", esc, contato, canal, agente, closer)
        await pool.execute(
            """insert into agentesia_notificacoes (id_escritorio, tipo_evento, nome, modelo_mensagem, destinatarios)
               values ($1, 'lead_quente', 'Lead quente', $2, $3::jsonb)""", esc, notificacoes.MODELO_PADRAO,
            json.dumps([{"rotulo": "Dra. Ana", "numero": "11 97777-6666"}]))
        for chave, valor in {**CLT_COM_SEQUELA, "cpf": "123.456.789-09"}.items():
            await pool.execute("insert into agentesia_lead_fatos (id_escritorio, id_lead, chave, valor, fonte) values ($1, $2, $3, $4::jsonb, 'extrator')",
                               esc, lead, chave, json.dumps(valor))
        agora = datetime.now(timezone.utc)
        for autor, minutos in (("lead", 30), ("ia", 29), ("lead", 27)):
            await pool.execute("insert into agentesia_mensagens (id_escritorio, id_lead, autor, tipo, texto, enviada_em) values ($1, $2, $3, 'texto', 'oi', $4)",
                               esc, lead, autor, agora - timedelta(minutes=minutos))

        async def nota_gravada():
            valor = await pool.fetchval("select valor from agentesia_lead_fatos where id_lead = $1 and chave = '_temperatura' and substituido_em is null", lead)
            return json.loads(valor) if isinstance(valor, str) else valor

        # Turno 1: sequela + CLT + rápido = 5 (morno). Grava, sem aviso. O agendar do follow-up chama o gancho.
        await servico.agendar(pool, str(lead), agora)
        gravada = await nota_gravada()
        assert (gravada["nota"], gravada["faixa"], gravada["avisou_quente"]) == (5, "morno", False)
        assert await pool.fetchval("select count(*) from agentesia_eventos where id_lead = $1 and tipo = 'lead_quente'", lead) == 0

        # Turno 2: aceitou os honorários (intenção do turno) = 7, quente: evento, etiqueta e aviso à equipe.
        await pool.execute(
            """insert into agentesia_turnos (id_escritorio, id_lead, modo, situacao, resposta)
               values ($1, $2, 'producao', 'respondido', $3::jsonb)""", esc, lead, json.dumps({"intencoes": {"aceitou_honorarios": True}}))
        resultado = await automacoes.depois_do_turno(pool, str(lead))
        assert (resultado["nota"], resultado["faixa"]) == (7, "quente")
        assert (await nota_gravada())["avisou_quente"] is True
        evento = await pool.fetchrow("select descricao, detalhe from agentesia_eventos where id_lead = $1 and tipo = 'lead_quente'", lead)
        assert "nota 7/10" in evento["descricao"]
        acoes = {r["tipo"]: json.loads(r["dados"]) if isinstance(r["dados"], str) else r["dados"]
                 for r in await pool.fetch("select tipo, dados from agentesia_acoes where id_lead = $1", lead)}
        assert acoes["etiquetar"]["adicionar"] == ["🔥 Quente"]
        aviso = acoes["notificar"]
        assert aviso["para"] == "5511977776666" and aviso["evento"] == "lead_quente"
        assert "Lead: Maria da Silva" in aviso["texto"] and "Benefício: Auxílio-Acidente" in aviso["texto"]
        assert "Nota: 7/10 (quente)" in aviso["texto"] and "+2 aceitou a proposta" in aviso["texto"]
        assert "123.456.789-09" not in aviso["texto"]

        # Turno 3: continua quente (e até sobe): não avisa de novo.
        await pool.execute("update agentesia_turnos set resposta = $2::jsonb where id_lead = $1", lead,
                           json.dumps({"intencoes": {"aceitou_honorarios": True, "pediu_link": True}}))
        assert (await automacoes.depois_do_turno(pool, str(lead)))["nota"] == 8
        await automacoes.depois_do_turno(pool, str(lead))
        assert await pool.fetchval("select count(*) from agentesia_eventos where id_lead = $1 and tipo = 'lead_quente'", lead) == 1
        assert await pool.fetchval("select count(*) from agentesia_acoes where id_lead = $1 and tipo = 'notificar'", lead) == 1
        # Nota igual: não regrava o fato.
        antes = await pool.fetchval("select count(*) from agentesia_lead_fatos where id_lead = $1 and chave = '_temperatura'", lead)
        await automacoes.depois_do_turno(pool, str(lead))
        assert await pool.fetchval("select count(*) from agentesia_lead_fatos where id_lead = $1 and chave = '_temperatura'", lead) == antes
        assert temperatura.CHAVE == "_temperatura"
    finally:
        await repo.fechar()
