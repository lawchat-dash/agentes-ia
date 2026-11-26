"""Follow-up dentro das regras da OAB e da Meta e lead parado como tarefa da equipe (docs/FOLLOWUP.md, seções 2 e 4).

- cadência padrão nova: no máximo 4 toques (1 h, 24 h, 72 h e 7 dias), só para quem ativa ou liga com o padrão agora;
- quem nunca respondeu à IA recebe no máximo 2; o penúltimo toque oferece parar;
- pedido para parar ("pare", "não quero mais", "sair", "remover") cancela e marca os follow-ups do lead;
- quem já tinha cadência configurada (sem "limites") segue igual;
- 24 h depois do 3º toque sem resposta: nota "Lead parado: retomar contato", automação/aviso do gatilho e evento lead_parado.
"""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app import automacoes
from app.followup import padrao, regras

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
COM_BANCO = pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")


# ------------------------------------------------------------------ sem banco
def test_cadencia_padrao_nova_tem_4_toques_e_limites():
    assert regras.CADENCIA_PADRAO == (1, 24, 72, 168)
    vazio = padrao.config_do_produto({}, ativo=True)
    assert [p["apos_horas"] for p in vazio["passos"]] == [1, 24, 72, 168]
    assert vazio["limites"] == {"max_toques_sem_resposta": 2, "oferecer_parar": True, "lead_parado_apos": 3}
    longo = padrao.config_do_produto({"padrao_followup": {"cadence": ["1h", "5h", "24h", "3d", "7d", "15d", "30d"]}}, ativo=True)
    assert padrao.resumo(longo) == ["1 h", "5 h", "24 h", "72 h"]                     # o produto manda, mas até 4
    assert padrao.previa_do_produto({})["resumo"] == ["1 h", "24 h", "72 h", "7 dias"]


def test_quem_ja_tem_cadencia_configurada_nao_muda():
    antiga = {"ativo": True, "passos": [{"apos_horas": h} for h in regras.CADENCIA_ANTIGA]}
    c = regras.Config.de(antiga)
    assert len(c.passos) == 7 and c.max_sem_resposta is None and not c.oferecer_parar
    assert c.total_de_toques(respondeu_a_ia=False) == 7 and not c.leva_opcao_de_parar(5, 7)
    assert c.lead_parado_apos == 3                                                   # a tarefa da equipe vale para todos
    assert "limites" not in regras.validar(antiga)                                   # salvar não inventa limites


def test_limites_nunca_respondeu_e_penultimo_toque():
    c = regras.Config.de(padrao.config_do_produto({}, ativo=True))
    assert c.total_de_toques(respondeu_a_ia=False) == 2 and c.total_de_toques(respondeu_a_ia=True) == 4
    assert [c.leva_opcao_de_parar(p, 4) for p in range(4)] == [False, False, True, False]
    assert [c.leva_opcao_de_parar(p, 2) for p in range(2)] == [True, False]
    assert not c.leva_opcao_de_parar(0, 1)
    # validar guarda os limites que vieram e, sem eles, os da config anterior (tela que não conhece o campo).
    novo = padrao.config_do_produto({}, ativo=True)
    assert regras.validar(novo)["limites"] == novo["limites"]
    sem = {k: v for k, v in novo.items() if k != "limites"}
    assert regras.validar(sem, anterior=novo)["limites"] == novo["limites"]
    assert regras.validar({**novo, "limites": {"max_toques_sem_resposta": 1, "lead_parado_apos": 0}})["limites"] == {
        "max_toques_sem_resposta": 1, "oferecer_parar": False, "lead_parado_apos": 0}
    assert regras.Config.de({"limites": {"lead_parado_apos": 0}}).lead_parado_apos == 0


def test_frase_de_parar_no_fim_sem_repetir():
    assert regras.com_opcao_de_parar(["Oi Maria!", "Conseguiu ver?"]) == ["Oi Maria!", "Conseguiu ver?\n\n" + regras.FRASE_PARAR]
    ja_tem = ["Oi! Se não quiser, eu não te mando mais mensagens."]
    assert regras.com_opcao_de_parar(ja_tem) == ja_tem
    assert regras.FRASE_PARAR == "Se preferir que eu não mande mais mensagens, é só me avisar."


@pytest.mark.parametrize("texto", ["pare", "Pare!", "PARA", "não quero mais", "Não quero mais receber isso", "sair", "quero sair",
                                   "remover", "me tira dessa lista", "remove meu número por favor", "para de me mandar mensagem",
                                   "parem com isso", "não me mande mais nada", "descadastrar", "pode parar"])
def test_reconhece_pedido_para_parar(texto):
    assert regras.pediu_para_parar(texto)


@pytest.mark.parametrize("texto", ["para quando é a perícia?", "vou sair do trabalho às 18h", "parei de trabalhar em 2020",
                                   "a dor não para", "quero saber mais", "pode mandar", "", None, "sim, quero seguir"])
def test_nao_confunde_com_pedido_para_parar(texto):
    assert not regras.pediu_para_parar(texto)


def test_acoes_do_lead_parado():
    config = {"funcoes": {"crm": True, "avisos": True},
              "automacoes": {"lead_parado": {"adicionar_etiquetas": ["⏸️ Parado"], "coluna_crm": "c9"}}}
    acoes = automacoes.acoes_do_lead_parado(config, {"id_painel": "p1"}, id_lead="L", id_followup="F", avisos={"lead_parado"})
    assert [a["tipo"] for a in acoes] == ["nota", "preparar_aviso", "mover_card", "etiquetar"]
    assert acoes[0] == {"tipo": "nota", "chave_unica": "L:lead_parado:F", "dados": {"texto": "Lead parado: retomar contato"}}
    assert acoes[1]["dados"] == {"evento": "lead_parado"} and acoes[3]["dados"]["adicionar"] == ["⏸️ Parado"]
    # Nota configurada troca a padrão (sai uma só); sem automação nem aviso, sai só a nota.
    proprio = automacoes.acoes_do_lead_parado({"funcoes": {"avisos": True}, "automacoes": {"lead_parado": {"nota": "Ligar para o lead"}}},
                                              None, id_lead="L", id_followup="F")
    assert proprio == [{"tipo": "nota", "chave_unica": "L:lead_parado:F", "dados": {"texto": "Ligar para o lead"}}]
    assert [a["tipo"] for a in automacoes.acoes_do_lead_parado({}, None, id_lead="L", id_followup="F")] == ["nota"]


# ------------------------------------------------------------------ banco local
@pytest.fixture
async def fu():
    """Escritório, número, agente com follow-up ligado (texto fixo, 24 h por dia) e um lead na etapa SDR."""
    from app.banco.postgres import RepositorioPostgres
    from app.canal.helena_conta import HelenaConta
    from app.followup import servico
    from app.modelo import ModeloFalso

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    await pool.execute("update agentesia_followups set situacao = 'cancelado' where situacao in ('pendente', 'reservado')")
    enviadas: list[dict] = []

    def helena(pedido: httpx.Request) -> httpx.Response:
        enviadas.append({"caminho": pedido.url.path, **json.loads(pedido.content or b"{}")})
        return httpx.Response(200, json={"id": f"fu-{uuid.uuid4().hex[:8]}"})

    disparador = servico.Disparador(pool, ModeloFalso({}), "https://api.helena.run", helena_por_token=lambda t, u: HelenaConta(
        t, u, httpx.AsyncClient(transport=httpx.MockTransport(helena))))

    async def montar(*, limites: bool = True, respondeu: bool = False, funcoes: dict | None = None, automacoes_cfg: dict | None = None):
        segredo = await pool.fetchval("select vault.create_secret('token-fu', 'teste')")
        esc = await pool.fetchval("insert into agentesia_escritorios (nome) values ('OAB FU') returning id")
        await pool.execute("insert into agentesia_integracoes (id_escritorio, tipo, id_segredo_vault, situacao) values ($1, 'helena', $2, 'ok')", esc, segredo)
        canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado, id_canal_helena) values ($1, $2, $3) returning id",
                                    esc, "5511" + str(uuid.uuid4().int)[:9], "ch-" + uuid.uuid4().hex[:6])
        followup = {"ativo": True, "horario": {"inicio": 0, "fim": 24, "dias": [0, 1, 2, 3, 4, 5, 6]}, "intervalo_minimo_min": 5,
                    "passos": [{"apos_horas": h, "modo": "texto", "texto": f"Toque {i + 1}, {{nome}}"} for i, h in enumerate(regras.CADENCIA_PADRAO)]}
        if limites:
            followup["limites"] = dict(regras.LIMITES_PADRAO)
        config = {"followup": followup, "funcoes": funcoes or {}, "automacoes": automacoes_cfg or {}}
        agente = await pool.fetchval(
            """insert into agentesia_agentes (id_escritorio, id_canal, nome, produto, config, situacao, modo)
               values ($1, $2, 'Júlia', 'auxilio_acidente', $3::jsonb, 'ativo', 'producao') returning id""", esc, canal, json.dumps(config))
        sdr = await pool.fetchval("insert into agentesia_agente_etapas (id_agente, codigo, ordem, tipo, principal) values ($1, 'sdr', 0, 'conversa', true) returning id", agente)
        contato = await pool.fetchval("insert into agentesia_contatos (id_escritorio, nome, telefone_normalizado) values ($1, 'Maria da Silva', $2) returning id",
                                      esc, "55119" + str(uuid.uuid4().int)[:8])
        base = datetime.now(timezone.utc) - timedelta(hours=2)
        lead = await pool.fetchval(
            """insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_agente, id_etapa, id_sessao_helena, ultima_mensagem_lead_em)
               values ($1, $2, $3, $4, $5, $6, $7) returning id""", esc, contato, canal, agente, sdr, "sessao-" + uuid.uuid4().hex[:6],
            base - timedelta(minutes=5))
        conversa = [("lead", 30, "oi"), ("ia", 25, "Olá! Como posso ajudar?")]
        if respondeu:
            conversa += [("lead", 10, "sofri um acidente"), ("ia", 2, "Entendi. Ficou com sequela?")]
        for autor, minutos, texto in conversa:
            await pool.execute("insert into agentesia_mensagens (id_escritorio, id_lead, autor, tipo, texto, enviada_em) values ($1, $2, $3, 'texto', $4, $5)",
                               esc, lead, autor, texto, base - timedelta(minutes=minutos))
        await pool.execute(
            "insert into agentesia_followups (id_escritorio, id_lead, id_agente, passo, base, agendado_para) values ($1, $2, $3, 0, $4, now() - interval '1 minute')",
            esc, lead, agente, base)
        return {"esc": esc, "agente": agente, "lead": lead, "base": base}

    async def proximo(d) -> list[dict]:
        """Vence o pendente, afasta as mensagens enviadas (intervalo mínimo) e roda o disparador."""
        await pool.execute("update agentesia_followups set agendado_para = now() - interval '1 minute' where id_lead = $1 and situacao = 'pendente'", d["lead"])
        await pool.execute("update agentesia_mensagens set enviada_em = $2 - interval '1 minute' where id_lead = $1 and autor = 'ia' and enviada_em > $2",
                           d["lead"], d["base"])
        antes = len(enviadas)
        await disparador.rodar_uma_vez()
        return enviadas[antes:]

    async def linhas(d):
        return [dict(r) for r in await pool.fetch(
            "select passo, situacao, motivo from agentesia_followups where id_lead = $1 order by criado_em", d["lead"])]

    try:
        yield pool, montar, proximo, linhas, disparador, servico
    finally:
        await repo.fechar()


@COM_BANCO
async def test_nunca_respondeu_recebe_2_toques_e_o_1o_oferece_parar(fu):
    pool, montar, proximo, linhas, _disparador, _servico = fu
    d = await montar()
    saida = await proximo(d)
    assert saida[0]["text"] == "Toque 1, Maria\n\n" + regras.FRASE_PARAR            # penúltimo dos 2
    saida = await proximo(d)
    assert saida[0]["text"] == "Toque 2, Maria"                                     # último: sem a frase
    assert await linhas(d) == [{"passo": 0, "situacao": "enviado", "motivo": None}, {"passo": 1, "situacao": "enviado", "motivo": None}]
    # Um 3º toque agendado à mão (config antiga, corrida) também não sai.
    await pool.execute("insert into agentesia_followups (id_escritorio, id_lead, id_agente, passo, base, agendado_para) values ($1, $2, $3, 2, $4, now())",
                       d["esc"], d["lead"], d["agente"], d["base"])
    assert await proximo(d) == []
    assert (await linhas(d))[-1] == {"passo": 2, "situacao": "cancelado", "motivo": "limite_sem_resposta"}


@COM_BANCO
async def test_quem_respondeu_recebe_4_toques_e_o_3o_oferece_parar(fu):
    _pool, montar, proximo, linhas, _disparador, _servico = fu
    d = await montar(respondeu=True)
    textos = [(await proximo(d))[0]["text"] for _ in range(4)]
    assert textos == ["Toque 1, Maria", "Toque 2, Maria", "Toque 3, Maria\n\n" + regras.FRASE_PARAR, "Toque 4, Maria"]
    assert [r["passo"] for r in await linhas(d)] == [0, 1, 2, 3]                     # e nada depois do 4º
    assert await proximo(d) == []


@COM_BANCO
async def test_config_antiga_sem_limites_segue_igual(fu):
    _pool, montar, proximo, linhas, _disparador, _servico = fu
    d = await montar(limites=False)                                                  # nunca respondeu, mas sem limites
    textos = [(await proximo(d))[0]["text"] for _ in range(3)]
    assert textos == ["Toque 1, Maria", "Toque 2, Maria", "Toque 3, Maria"]          # sem limite de 2 e sem a frase
    assert (await linhas(d))[-1]["situacao"] == "pendente"


@COM_BANCO
async def test_pedido_para_parar_cancela_e_marca(fu):
    pool, montar, proximo, linhas, _disparador, servico = fu
    d = await montar(respondeu=True, limites=False)
    await pool.execute("update agentesia_mensagens set texto = 'Não quero mais, pode parar' where id_lead = $1 and texto = 'sofri um acidente'", d["lead"])
    assert await proximo(d) == []
    assert await linhas(d) == [{"passo": 0, "situacao": "cancelado", "motivo": "lead_pediu_para_parar"}]
    assert await pool.fetchval("select count(*) from agentesia_eventos where id_lead = $1 and tipo = 'followup_lead_pediu_para_parar'", d["lead"]) == 1
    # Na próxima resposta da IA o agendar nem agenda: deixa a marca.
    assert await servico.agendar(pool, str(d["lead"]), datetime.now(timezone.utc)) is None
    assert (await linhas(d))[-1] == {"passo": 0, "situacao": "cancelado", "motivo": "lead_pediu_para_parar"}
    assert await pool.fetchval("select count(*) from agentesia_followups where id_lead = $1 and situacao = 'pendente'", d["lead"]) == 0
    # O lead volta a conversar normalmente: a cadência volta.
    await pool.execute("insert into agentesia_mensagens (id_escritorio, id_lead, autor, tipo, texto, enviada_em) values ($1, $2, 'lead', 'texto', 'oi, voltei', now())",
                       d["esc"], d["lead"])
    assert await servico.agendar(pool, str(d["lead"]), datetime.now(timezone.utc)) is not None


@COM_BANCO
async def test_lead_parado_vira_tarefa_da_equipe_uma_vez(fu):
    pool, montar, proximo, linhas, disparador, _servico = fu
    d = await montar(respondeu=True, funcoes={"avisos": True, "crm": True},
                     automacoes_cfg={"lead_parado": {"adicionar_etiquetas": ["⏸️ Parado"]}})
    await pool.execute(
        """insert into agentesia_notificacoes (id_escritorio, tipo_evento, nome, modelo_mensagem, destinatarios)
           values ($1, 'lead_parado', 'Lead parado', 'Retomar {{nome}}', '[{"numero": "11977776666"}]'::jsonb)""", d["esc"])
    for _ in range(3):
        await proximo(d)
    assert [r["passo"] for r in await linhas(d)] == [0, 1, 2, 3]                     # 3 enviados, o 4º pendente

    assert await disparador.varrer_parados() == 0                                   # o 3º acabou de sair: espera 24 h
    await pool.execute("update agentesia_followups set enviado_em = now() - interval '2 hours' where id_lead = $1 and passo = 1", d["lead"])
    await pool.execute("update agentesia_followups set enviado_em = now() - interval '25 hours' where id_lead = $1 and passo = 2", d["lead"])
    assert await disparador.varrer_parados() == 1
    acoes = {r["tipo"]: r for r in await pool.fetch("select tipo, chave_unica, dados from agentesia_acoes where id_lead = $1", d["lead"])}
    nota = json.loads(acoes["nota"]["dados"]) if isinstance(acoes["nota"]["dados"], str) else acoes["nota"]["dados"]
    assert nota == {"texto": "Lead parado: retomar contato"} and ":lead_parado:" in acoes["nota"]["chave_unica"]
    assert "preparar_aviso" in acoes and "etiquetar" in acoes                          # aviso à equipe e a etiqueta do gatilho
    evento = await pool.fetchrow("select gravidade, responsavel, descricao from agentesia_eventos where id_lead = $1 and tipo = 'lead_parado'", d["lead"])
    assert (evento["gravidade"], evento["responsavel"]) == ("info", "lead") and "3 follow-ups sem resposta" in evento["descricao"]
    assert await disparador.varrer_parados() == 0                                   # uma vez por ciclo
    assert await pool.fetchval("select count(*) from agentesia_eventos where id_lead = $1 and tipo = 'lead_parado'", d["lead"]) == 1

    # Lead que respondeu depois do 3º toque não é parado; desligado por config (lead_parado_apos = 0) também não.
    d2 = await montar(respondeu=True)
    for _ in range(3):
        await proximo(d2)
    await pool.execute("update agentesia_followups set enviado_em = now() - interval '25 hours' where id_lead = $1 and passo = 2", d2["lead"])
    await pool.execute("insert into agentesia_mensagens (id_escritorio, id_lead, autor, tipo, texto, enviada_em) values ($1, $2, 'lead', 'texto', 'oi', now())",
                       d2["esc"], d2["lead"])
    assert await disparador.varrer_parados() == 0
    d3 = await montar(respondeu=True)
    await pool.execute("update agentesia_agentes set config = jsonb_set(config, '{followup,limites,lead_parado_apos}', '0') where id = $1", d3["agente"])
    for _ in range(3):
        await proximo(d3)
    await pool.execute("update agentesia_followups set enviado_em = now() - interval '25 hours' where id_lead = $1 and passo = 2", d3["lead"])
    assert await disparador.varrer_parados() == 0
