"""Motor de follow-up: o agente de follow-up DECIDE (enviar, adiar, não enviar) e o agente do lead (o da etapa, com a
voz dele) escreve. Puros (sem banco) e com o Postgres local (AGENTESIA_TESTE_PG_URL)."""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.followup import agente, regras

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
COM_BANCO = pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")


def _lead(**extra):
    base = {"nome_agente": "Júlia", "escritorio": "Souza Advocacia", "etapa": "sdr", "produto": "catalogo",
            "instrucao_etapa": "Você é a Júlia, SDR do {{ Nome do Escritório }}. Fale com carinho.\n"
                               "Quando qualificar, @Agente Closer.\nPergunte a data do acidente.",
            "config_agente": {"catalogo": {"regras": "Nunca fale de valores."}}, "config_escritorio": {}}
    return {**base, **extra}


def test_le_a_decisao_e_qualquer_coisa_estranha_vira_enviar():
    assert agente.ler_decisao({"funcao": "adiar_followup", "horas": 5000, "motivo": "viajando", "orientacao": ""}).horas == 720
    assert agente.ler_decisao({"funcao": "adiar_followup", "horas": None, "motivo": "", "orientacao": ""}).horas == 24
    d = agente.ler_decisao({"funcao": "nao_enviar", "horas": None, "motivo": "vai mandar o laudo", "orientacao": ""})
    assert (d.funcao, d.decidiu, d.enviar) == ("nao_enviar", True, False)
    for estranho in (None, {}, {"funcao": "apagar_tudo"}, "texto"):
        assert agente.ler_decisao(estranho).enviar and not agente.ler_decisao(estranho).decidiu


def test_o_agente_do_lead_fala_com_a_voz_da_etapa_sem_ferramentas_e_com_as_regras():
    c = regras.Config.de({"por_etapa": {"sdr": "Retome pela pergunta do {{ Nome do Escritório }}.\nLinha com {{ Variavel Sem Valor }}"}})
    sistema = agente.sistema_do_agente_do_lead(_lead(), c, 0, 2, "retome pela data do acidente")
    assert "Você é Júlia, do escritório Souza Advocacia" in sistema
    assert "SDR do Souza Advocacia" in sistema and "Pergunte a data do acidente" in sistema       # a voz da etapa
    assert "@Agente" not in sistema and "{{" not in sistema                                        # sem troca e sem variável crua
    assert "Retome pela pergunta do Souza Advocacia" in sistema and "Variavel" not in sistema
    assert "Nunca fale de valores" in sistema and "Não avance de etapa" in sistema
    assert "Tentativa 1 de 2" in sistema and "Orientação para esta retomada: retome pela data do acidente" in sistema
    # Produto próprio sem instrução gravada: vale a instrução padrão da etapa.
    proprio = agente.sistema_do_agente_do_lead(_lead(produto="auxilio_acidente", instrucao_etapa=None), c, 1, 2)
    assert "ETAPA" in proprio and "Esta é a última tentativa" in proprio


def test_o_agente_de_followup_recebe_o_prompt_e_as_funcoes():
    c = regras.Config.de({"prompt": "Seja gentil, {{ Nome do Escritório }}.", "por_etapa": {"sdr": "Foque na qualificação."}})
    sistema = agente.sistema_do_decisor(_lead(), c, 2, 4, "quarta-feira, 26/11/2026, 10:00")
    assert "agente de follow-up do escritório Souza Advocacia" in sistema and "Tentativa 3 de 4" in sistema
    assert "Seja gentil, Souza Advocacia." in sistema and "Foque na qualificação." in sistema
    assert all(f in sistema for f in agente.FUNCOES) and "26/11/2026" in sistema
    assert agente.ESQUEMA_DECISAO["properties"]["funcao"]["enum"] == list(agente.FUNCOES)


def test_limpa_as_mensagens_e_recusa_link_e_valor():
    assert agente.limpar_mensagens(["**Oi** Ana", " ", "\"Tudo bem?\"", "a", "b"]) == ["*Oi* Ana", "Tudo bem?", "a\n\nb"]
    assert agente.limpar_mensagens(["Veja https://x.com"]) == []
    assert agente.limpar_mensagens(["Custa R$ 300"]) == []
    assert agente.limpar_mensagens(["Oi {{nome}}"]) == []
    assert agente.limpar_mensagens("não é lista") == []


def test_config_decidir_ligado_por_padrao_e_guardado_na_edicao():
    assert regras.Config.de({}).decidir and not regras.Config.de({"decidir": False}).decidir
    assert "decidir" not in regras.validar({"ativo": True})
    assert regras.validar({"ativo": True, "decidir": False})["decidir"] is False
    assert regras.validar({"ativo": True}, anterior={"decidir": False})["decidir"] is False       # a tela não apaga


# ------------------------------------------------------------------ com banco
@pytest.fixture
async def base():
    from app.banco.postgres import RepositorioPostgres
    from app.canal.helena_conta import HelenaConta
    from app.followup import servico

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    await pool.execute("update agentesia_followups set situacao = 'cancelado' where situacao in ('pendente', 'reservado')")
    enviadas: list[dict] = []

    def helena(pedido: httpx.Request) -> httpx.Response:
        enviadas.append({"caminho": pedido.url.path, **json.loads(pedido.content or b"{}")})
        return httpx.Response(200, json={"id": f"fu-{uuid.uuid4().hex[:8]}"})

    def disparador(modelo):
        return servico.Disparador(pool, modelo, "https://api.helena.run", helena_por_token=lambda t, u: HelenaConta(
            t, u, httpx.AsyncClient(transport=httpx.MockTransport(helena))))

    async def montar(followup_extra: dict | None = None, *, instrucao: str = "Você é a Júlia, SDR. Pergunte a sequela."):
        segredo = await pool.fetchval("select vault.create_secret('token-fu', 'teste')")
        esc = await pool.fetchval("insert into agentesia_escritorios (nome) values ('Agente FU') returning id")
        await pool.execute("insert into agentesia_integracoes (id_escritorio, tipo, id_segredo_vault, situacao) values ($1, 'helena', $2, 'ok')", esc, segredo)
        canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado, id_canal_helena) values ($1, $2, $3) returning id",
                                    esc, "5511" + str(uuid.uuid4().int)[:9], "ch-" + uuid.uuid4().hex[:6])
        followup = {"ativo": True, "horario": {"inicio": 0, "fim": 24, "dias": [0, 1, 2, 3, 4, 5, 6]}, "intervalo_minimo_min": 5,
                    "passos": [{"apos_horas": 1, "modo": "ia"}, {"apos_horas": 24, "modo": "ia"}], **(followup_extra or {})}
        agente_id = await pool.fetchval(
            """insert into agentesia_agentes (id_escritorio, id_canal, nome, produto, config, situacao, modo)
               values ($1, $2, 'Júlia', 'auxilio_acidente', $3::jsonb, 'ativo', 'producao') returning id""", esc, canal,
            json.dumps({"followup": followup}))
        sdr = await pool.fetchval("""insert into agentesia_agente_etapas (id_agente, codigo, ordem, tipo, principal, instrucao)
                                     values ($1, 'sdr', 0, 'conversa', true, $2) returning id""", agente_id, instrucao)
        contato = await pool.fetchval("insert into agentesia_contatos (id_escritorio, nome, telefone_normalizado) values ($1, 'Ana Souza', $2) returning id",
                                      esc, "55119" + str(uuid.uuid4().int)[:8])
        b = datetime.now(timezone.utc) - timedelta(hours=2)
        lead = await pool.fetchval(
            """insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_agente, id_etapa, id_sessao_helena, ultima_mensagem_lead_em)
               values ($1, $2, $3, $4, $5, $6, $7) returning id""", esc, contato, canal, agente_id, sdr, "sessao-" + uuid.uuid4().hex[:6],
            b - timedelta(minutes=5))
        for autor, minutos, texto in [("ia", 30, "Oi! Como posso ajudar?"), ("lead", 10, "estou no trabalho agora"),
                                      ("ia", 2, "Sem problema! Ficou com alguma sequela?")]:
            await pool.execute("insert into agentesia_mensagens (id_escritorio, id_lead, autor, tipo, texto, enviada_em) values ($1, $2, $3, 'texto', $4, $5)",
                               esc, lead, autor, texto, b - timedelta(minutes=minutos))
        await pool.execute(
            "insert into agentesia_followups (id_escritorio, id_lead, id_agente, passo, base, agendado_para) values ($1, $2, $3, 0, $4, now() - interval '1 minute')",
            esc, lead, agente_id, b)
        return {"esc": esc, "lead": lead, "agente": agente_id, "base": b}

    async def linhas(d):
        return [dict(r) for r in await pool.fetch(
            "select passo, situacao, motivo, agendado_para from agentesia_followups where id_lead = $1 order by criado_em", d["lead"])]

    try:
        yield pool, montar, disparador, enviadas, linhas
    finally:
        await repo.fechar()


@COM_BANCO
async def test_decide_e_o_agente_da_etapa_escreve_com_a_orientacao(base):
    from app.modelo import ModeloFalso
    pool, montar, disparador, enviadas, linhas = base
    d = await montar()
    modelo = ModeloFalso({"followup_decisor": {"funcao": "enviar_followup", "horas": None, "motivo": "parou na sequela",
                                               "orientacao": "retome pela pergunta da sequela"},
                          "followup": {"mensagens": ["Oi, Ana! Conseguiu ver minha pergunta sobre a sequela?"]}})
    assert await disparador(modelo).rodar_uma_vez() == 1
    assert [p["papel"] for p in modelo.pedidos] == ["followup_decisor", "followup"]
    decisor, escritor = modelo.pedidos
    assert "estou no trabalho agora" in decisor["conteudo"] and "adiar_followup" in decisor["sistema"]
    assert "Você é a Júlia, SDR. Pergunte a sequela." in escritor["sistema"]                       # a voz da etapa
    assert "retome pela pergunta da sequela" in escritor["sistema"]
    assert enviadas[-1]["text"] == "Oi, Ana! Conseguiu ver minha pergunta sobre a sequela?"
    assert [(r["passo"], r["situacao"]) for r in await linhas(d)] == [(0, "enviado"), (1, "pendente")]
    nota = await pool.fetchval("select dados->>'texto' from agentesia_acoes where id_lead = $1 and tipo = 'nota'", d["lead"])
    assert nota.startswith("🔁 Follow-up 1 de 2 enviado às ") and nota.endswith("(etapa Primeiro atendimento).") and " pelo agente " in nota
    assert await pool.fetchval("select count(*) from agentesia_chamadas_ia where id_lead = $1", d["lead"]) == 2


@COM_BANCO
async def test_lead_pediu_para_esperar_adia_uma_vez_so(base):
    from app.modelo import ModeloFalso
    pool, montar, disparador, enviadas, linhas = base
    d = await montar()
    adiar = {"funcao": "adiar_followup", "horas": 4, "motivo": "disse que está no trabalho", "orientacao": ""}
    modelo = ModeloFalso({"followup_decisor": [adiar, adiar], "followup": {"mensagens": ["Oi, Ana! Agora pode falar?"]}})
    antes = len(enviadas)
    await disparador(modelo).rodar_uma_vez()
    assert len(enviadas) == antes                                                                    # não mandou
    (linha,) = await linhas(d)
    assert (linha["situacao"], linha["motivo"]) == ("pendente", "lead_pediu_para_esperar")
    assert timedelta(hours=3, minutes=55) < linha["agendado_para"] - datetime.now(timezone.utc) < timedelta(hours=4, minutes=5)
    evento = await pool.fetchrow("select gravidade, descricao from agentesia_eventos where id_lead = $1 and tipo = 'followup_adiado'", d["lead"])
    assert evento["gravidade"] == "info" and "disse que está no trabalho" in evento["descricao"]
    # Venceu de novo e o agente quer adiar outra vez: já adiou neste ciclo, então envia.
    await pool.execute("update agentesia_followups set agendado_para = now() - interval '1 minute' where id_lead = $1", d["lead"])
    await disparador(modelo).rodar_uma_vez()
    assert enviadas[-1]["text"] == "Oi, Ana! Agora pode falar?"
    assert [r["situacao"] for r in await linhas(d)] == ["enviado", "pendente"]


@COM_BANCO
async def test_agente_decide_nao_enviar_e_o_ciclo_vira_tarefa_da_equipe(base):
    from app.modelo import ModeloFalso
    pool, montar, disparador, enviadas, linhas = base
    d = await montar({"limites": dict(regras.LIMITES_PADRAO)})
    enviar = {"funcao": "enviar_followup", "horas": None, "motivo": "", "orientacao": ""}
    nao = {"funcao": "nao_enviar", "horas": None, "motivo": "ela disse que vai mandar o laudo", "orientacao": ""}
    modelo = ModeloFalso({"followup_decisor": [enviar, nao], "followup": {"mensagens": ["Oi, Ana! Tudo bem?"]}})
    fu = disparador(modelo)
    await fu.rodar_uma_vez()
    await pool.execute("update agentesia_followups set agendado_para = now() - interval '1 minute' where id_lead = $1 and situacao = 'pendente'", d["lead"])
    await pool.execute("update agentesia_mensagens set enviada_em = now() - interval '2 hours' where id_lead = $1 and autor = 'ia'", d["lead"])
    antes = len(enviadas)
    await fu.rodar_uma_vez()
    assert len(enviadas) == antes
    assert [(r["situacao"], r["motivo"]) for r in await linhas(d)][-1] == ("cancelado", "agente_decidiu_nao_enviar")
    assert "vai mandar o laudo" in await pool.fetchval(
        "select descricao from agentesia_eventos where id_lead = $1 and tipo = 'followup_agente_decidiu_nao_enviar'", d["lead"])
    # 24 h depois do último toque que saiu, sem resposta: lead parado (mesmo antes do 3º toque).
    await pool.execute("update agentesia_followups set enviado_em = now() - interval '25 hours' where id_lead = $1 and situacao = 'enviado'", d["lead"])
    assert await fu.varrer_parados() == 1
    assert "1 follow-ups sem resposta" in await pool.fetchval(
        "select descricao from agentesia_eventos where id_lead = $1 and tipo = 'lead_parado'", d["lead"])


@COM_BANCO
async def test_nunca_respondeu_recebe_2_e_vira_lead_parado(base):
    from app.modelo import ModeloFalso
    pool, montar, disparador, enviadas, linhas = base
    d = await montar({"limites": dict(regras.LIMITES_PADRAO),
                      "passos": [{"apos_horas": h, "modo": "texto", "texto": f"Toque {i + 1}"} for i, h in enumerate(regras.CADENCIA_PADRAO)]})
    await pool.execute("delete from agentesia_mensagens where id_lead = $1 and autor = 'lead'", d["lead"])   # nunca respondeu
    fu = disparador(ModeloFalso({}))                     # o agente de follow-up fora do ar: segue enviando
    for _ in range(2):
        await pool.execute("update agentesia_followups set agendado_para = now() - interval '1 minute' where id_lead = $1 and situacao = 'pendente'", d["lead"])
        await pool.execute("update agentesia_mensagens set enviada_em = now() - interval '3 hours' where id_lead = $1", d["lead"])
        await fu.rodar_uma_vez()
    assert [(r["passo"], r["situacao"]) for r in await linhas(d)] == [(0, "enviado"), (1, "enviado")]   # e nada depois
    assert await fu.varrer_parados() == 0                                                                # ainda não deu 24 h
    await pool.execute("update agentesia_followups set enviado_em = now() - interval '25 hours' where id_lead = $1", d["lead"])
    assert await fu.varrer_parados() == 1
    # Follow-up desligado: não vira tarefa.
    d2 = await montar({"limites": dict(regras.LIMITES_PADRAO)})
    await pool.execute("insert into agentesia_followups (id_escritorio, id_lead, id_agente, passo, base, agendado_para, situacao, enviado_em) "
                       "values ($1, $2, $3, 1, $4, now(), 'enviado', now() - interval '25 hours')", d2["esc"], d2["lead"], d2["agente"], d2["base"])
    await pool.execute("update agentesia_followups set situacao = 'cancelado' where id_lead = $1 and situacao = 'pendente'", d2["lead"])
    await pool.execute("update agentesia_agentes set config = jsonb_set(config, '{followup,ativo}', 'false') where id = $1", d2["agente"])
    assert await fu.varrer_parados() == 0


@COM_BANCO
async def test_reserva_retomada_depois_de_cair_nao_reenvia(base):
    from app.modelo import ModeloFalso
    pool, montar, disparador, enviadas, linhas = base
    d = await montar({"passos": [{"apos_horas": 1, "modo": "texto", "texto": "Oi!"}, {"apos_horas": 24, "modo": "texto", "texto": "Oi de novo!"}]})
    # O servidor mandou e caiu antes de marcar: a mensagem está na conversa e a reserva venceu.
    await pool.execute("update agentesia_followups set situacao = 'reservado', reservado_ate = now() - interval '1 minute', tentativas = 1 where id_lead = $1", d["lead"])
    await pool.execute("insert into agentesia_mensagens (id_escritorio, id_lead, autor, tipo, texto, enviada_em) values ($1, $2, 'ia', 'texto', 'Oi!', now())",
                       d["esc"], d["lead"])
    antes = len(enviadas)
    await disparador(ModeloFalso({})).rodar_uma_vez()
    assert len(enviadas) == antes
    assert [(r["passo"], r["situacao"], r["motivo"]) for r in await linhas(d)] == [(0, "enviado", "enviado_antes_da_queda"), (1, "pendente", None)]


@COM_BANCO
async def test_sem_saldo_nao_chama_ia_nem_o_agente_de_followup(base, monkeypatch):
    from app.followup import servico
    from app.modelo import ModeloFalso
    pool, montar, disparador, enviadas, linhas = base
    await montar()
    modelo = ModeloFalso({"followup_decisor": {"funcao": "nao_enviar", "horas": None, "motivo": "", "orientacao": ""}})

    async def estourado(self, lead):
        return True
    monkeypatch.setattr(servico.Disparador, "_consumo_estourado", estourado)
    await disparador(modelo).rodar_uma_vez()
    assert modelo.pedidos == [] and enviadas[-1]["text"].startswith("Oi, Ana! Passando para saber")
