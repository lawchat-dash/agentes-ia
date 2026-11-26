"""Memória longa do Weaver (bloco 11): ficha do começo da conversa refeita pela fila ('resumir_conversa'),
bloco '# COMEÇO DA CONVERSA' no prompt e os fatos do sistema completos (hora, aviso do nome, regra por etapa)."""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app import memoria
from app.banco.postgres import contrato_pela_etapa
from app.cerebro import turno
from app.modelo import ErroModelo, ModeloFalso
from tests.test_catalogo_weaver import entrada as entrada_catalogo, extrai as extrai_catalogo, resposta
from tests.test_pipeline import SIMPLES, montar, webhook
from tests.test_turno import extrai, fala

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
FICHA = "- Quem é: Maria, 52 anos, Contagem\n- Caso: acidente de moto em março de 2024"


def _antigas(n, autor_par="lead", autor_impar="ia"):
    return [{"autor": autor_par if i % 2 == 0 else autor_impar, "texto": f"mensagem {i}"} for i in range(n)]


# ----------------------------------------------------------------------------- texto (funções puras)
def test_bloco_vazio_quando_nada_fica_fora_da_janela():
    assert memoria.bloco_comeco_da_conversa(None) == ""
    assert memoria.bloco_comeco_da_conversa(memoria.ComecoDaConversa()) == ""
    assert memoria.bloco_comeco_da_conversa(memoria.ComecoDaConversa(antigas=[{"autor": "lead", "texto": "  "}])) == ""


def test_bloco_com_ficha_e_antigas_ainda_sem_resumo():
    comeco = memoria.ComecoDaConversa(resumo=FICHA, antigas=[
        {"autor": "lead", "texto": "sofri o acidente\n\n  em março"}, {"autor": "ia", "texto": "Entendi."},
        {"autor": "humano", "texto": "Aqui é a Paula"}])
    assert memoria.bloco_comeco_da_conversa(comeco) == (
        "# COMEÇO DA CONVERSA (mensagens antigas que não aparecem mais no seu histórico)\n"
        "Use para não repetir perguntas já respondidas. Não cite que existe um resumo.\n\n"
        + FICHA + "\n\nMensagens antigas mais recentes:\n"
        "Lead: sofri o acidente em março\nAtendimento: Entendi.\nAtendente: Aqui é a Paula")


def test_bloco_sem_ficha_leva_ate_60_antigas_de_600_caracteres():
    comeco = memoria.ComecoDaConversa(antigas=_antigas(80) + [{"autor": "lead", "texto": "x" * 900}])
    bloco = memoria.bloco_comeco_da_conversa(comeco)
    linhas = bloco.split("Mensagens antigas mais recentes:\n")[1].split("\n")
    assert len(linhas) == 60 and linhas[-1] == "Lead: " + "x" * 600
    assert linhas[0] == "Atendimento: mensagem 21"                       # as 60 mais perto da janela, não as primeiras
    assert "\n\n- Quem é" not in bloco


def test_pedido_de_resumo_igual_ao_do_n8n():
    sistema, conteudo = memoria.montar_pedido(None, [{"autor": "lead", "texto": "a" * 2000}, {"autor": "ia", "texto": "ok"}])
    assert sistema.startswith("Você mantém a ficha de memória de um atendimento de escritório de advocacia pelo WhatsApp.")
    for topico in ("- Quem é:", "- Caso:", "- Trabalho e INSS:", "- Já respondido:", "- Dados pessoais já informados:",
                   "- Combinados e objeções:", "- Atendimento humano:", "No máximo 220 palavras", "sem repetir CPF e RG por extenso"):
        assert topico in sistema
    assert conteudo == "FICHA ANTERIOR:\n(vazia)\n\nTRECHO NOVO:\nLead: " + "a" * 1500 + "\nAtendimento: ok"
    _, longo = memoria.montar_pedido(FICHA, [{"autor": "lead", "texto": "b" * 1500}] * 40)
    assert longo.startswith("FICHA ANTERIOR:\n" + FICHA + "\n\nTRECHO NOVO:\n")
    assert len(longo.split("TRECHO NOVO:\n")[1]) == 40_000


def test_so_pede_resumo_com_20_antigas_sem_resumo():
    assert memoria.acao_de_resumo("lead-1", memoria.ComecoDaConversa(pendentes=19)) is None
    assert memoria.acao_de_resumo("lead-1", memoria.ComecoDaConversa(pendentes=40, falhou=True)) is None
    acao = memoria.acao_de_resumo("lead-1", memoria.ComecoDaConversa(pendentes=25, ate_id_mensagem="m-9"))
    assert acao == {"tipo": "resumir_conversa", "chave_unica": "lead-1:resumir_conversa:m-9:1", "dados": {"pendentes": 25}}
    assert memoria.acao_de_resumo("lead-1", memoria.ComecoDaConversa(pendentes=20))["chave_unica"].endswith(":inicio:1")


def test_contrato_sem_documento_segue_a_etapa():
    assert contrato_pela_etapa("contratoassinado") == "consta como JÁ ASSINADO."
    assert contrato_pela_etapa("contrato_assinado") == "consta como JÁ ASSINADO."
    assert contrato_pela_etapa("assinatura") == "já foi gerado e enviado ao lead. Ainda não consta a assinatura."
    assert contrato_pela_etapa("sdr") == contrato_pela_etapa(None) == "ainda não foi gerado."


# ----------------------------------------------------------------------------- cérebro: bloco no prompt
async def test_bloco_entra_no_fim_do_sistema_do_catalogo_e_do_auxilio_acidente():
    comeco = memoria.ComecoDaConversa(resumo=FICHA)
    modelo = ModeloFalso({"extrator": extrai_catalogo(), "etapa": resposta()})
    await turno.processar(modelo, entrada_catalogo(["oi"], comeco_conversa=comeco))
    assert modelo.pedidos[-1]["sistema"].endswith("\n\n---\n\n# COMEÇO DA CONVERSA (mensagens antigas que não aparecem mais "
                                                  "no seu histórico)\nUse para não repetir perguntas já respondidas. "
                                                  "Não cite que existe um resumo.\n\n" + FICHA)

    modelo = ModeloFalso({"extrator": extrai(), "etapa": fala("Oi!")})
    await turno.processar(modelo, turno.Entrada(escritorio="E", agente="Júlia", etapa="sdr", novas=["oi"], comeco_conversa=comeco))
    assert modelo.pedidos[-1]["sistema"].endswith(FICHA)

    modelo = ModeloFalso({"extrator": extrai(), "etapa": fala("Oi!")})
    await turno.processar(modelo, turno.Entrada(escritorio="E", agente="Júlia", etapa="sdr", novas=["oi"]))
    assert "COMEÇO DA CONVERSA" not in modelo.pedidos[-1]["sistema"]


# ----------------------------------------------------------------------------- repositório em memória e pipeline
async def _lead_com_conversa(quantas):
    atendimento, repo, helena = montar(SIMPLES)
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    lead = next(iter(repo.leads.values()))
    inicio = datetime.now(timezone.utc) - timedelta(days=2)
    for i in range(quantas):
        await repo.gravar_mensagem(lead=lead, autor="lead" if i % 2 == 0 else "ia", tipo="texto", texto=f"antiga {i}",
                                   texto_extraido=None, url_midia=None, enviada_em=inicio + timedelta(minutes=i),
                                   id_externo=None, id_turno="turno-velho")
    return atendimento, repo, helena, lead


async def test_antigas_fora_da_janela_entram_no_prompt_e_pedem_o_resumo():
    atendimento, repo, _helena, lead = await _lead_com_conversa(60)      # + as 2 do primeiro turno = 62
    await atendimento.receber(webhook("e agora?"))
    await atendimento.aguardar_esperas()
    sistema = atendimento.modelo.pedidos[-1]["sistema"]
    assert "# COMEÇO DA CONVERSA" in sistema and "Lead: antiga 0\nAtendimento: antiga 1" in sistema
    assert "antiga 22" not in sistema.split("# COMEÇO DA CONVERSA")[1]   # 62 - 40 = 22 antigas fora da janela (0 a 21)
    acao = next(a for a in repo.acoes if a["tipo"] == "resumir_conversa")
    assert acao["chave_unica"] == f"{lead.id}:resumir_conversa:inicio:1" and acao["dados"] == {"pendentes": 22}


async def test_poucas_antigas_nao_pedem_resumo():
    atendimento, repo, _helena, _lead = await _lead_com_conversa(45)
    await atendimento.receber(webhook("e agora?"))
    await atendimento.aguardar_esperas()
    assert "Lead: antiga 0" in atendimento.modelo.pedidos[-1]["sistema"]
    assert not [a for a in repo.acoes if a["tipo"] == "resumir_conversa"]


async def test_leitura_que_falha_nao_derruba_a_resposta():
    atendimento, repo, helena, _lead = await _lead_com_conversa(60)

    async def quebrado(*_a, **_k):
        raise RuntimeError("tabela ainda não criada")

    repo.comeco_da_conversa = quebrado
    await atendimento.receber(webhook("e agora?"))
    await atendimento.aguardar_esperas()
    assert len(helena.enviadas) == 2 and "COMEÇO DA CONVERSA" not in atendimento.modelo.pedidos[-1]["sistema"]
    assert not [a for a in repo.acoes if a["tipo"] == "resumir_conversa"]


async def test_resumo_grava_a_ficha_e_a_marca_so_anda_para_a_frente():
    _atendimento, repo, _helena, lead = await _lead_com_conversa(70)    # 72 mensagens: 32 fora da janela
    modelo = ModeloFalso({"resumo_conversa": [{"resumo": " " + FICHA + " "}, {"resumo": "ficha 2"}]})
    resultado, chamadas = await memoria.resumir(repo, modelo, lead.id)
    assert resultado == {"resumo": "feito", "mensagens": 32, "caracteres": len(FICHA)} and len(chamadas) == 1
    pedido = modelo.pedidos[0]
    assert pedido["temperatura"] == 0.2 and pedido["conteudo"].startswith("FICHA ANTERIOR:\n(vazia)\n\nTRECHO NOVO:\nLead: antiga 0")
    ficha = repo.resumos[lead.id]
    assert ficha["resumo"] == FICHA and ficha["mensagens_resumidas"] == 32
    comeco = await memoria.ler_comeco(repo, lead.id)
    assert (comeco.resumo, comeco.antigas, comeco.pendentes) == (FICHA, [], 0)

    for i in range(5):                                                    # mais 5 mensagens empurram 5 antigas para fora
        await repo.gravar_mensagem(lead=lead, autor="lead", tipo="texto", texto=f"nova {i}", texto_extraido=None,
                                   url_midia=None, enviada_em=datetime.now(timezone.utc) + timedelta(minutes=i),
                                   id_externo=None, id_turno="t")
    comeco = await memoria.ler_comeco(repo, lead.id)
    assert comeco.pendentes == 5 and comeco.antigas[0] == {"autor": "lead", "texto": "antiga 32"}
    await memoria.resumir(repo, modelo, lead.id)
    assert modelo.pedidos[1]["conteudo"].startswith("FICHA ANTERIOR:\n" + FICHA + "\n\nTRECHO NOVO:\nLead: antiga 32")
    assert repo.resumos[lead.id]["mensagens_resumidas"] == 37 and repo.resumos[lead.id]["resumo"] == "ficha 2"
    assert (await memoria.resumir(repo, modelo, lead.id))[0] == {"resumo": "nada_para_resumir"}


async def test_resumo_vazio_nao_grava_e_erro_da_ia_sobe():
    _atendimento, repo, _helena, lead = await _lead_com_conversa(70)
    assert (await memoria.resumir(repo, ModeloFalso({"resumo_conversa": {"resumo": "  "}}), lead.id))[0] == {"resumo": "vazio"}
    assert lead.id not in repo.__dict__.get("resumos", {})
    with pytest.raises(ErroModelo):
        await memoria.resumir(repo, ModeloFalso({}), lead.id)


# ----------------------------------------------------------------------------- Postgres de verdade
async def _cenario_pg(pool, nome, quantas, *, etapa=None, nome_contato="'Maria'"):
    esc = str(await pool.fetchval("insert into agentesia_escritorios (nome) values ($1) returning id", nome))
    canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado) values ($1, $2) returning id",
                                esc, "5531" + str(uuid.uuid4().int)[:9])
    contato = await pool.fetchval("insert into agentesia_contatos (id_escritorio, nome, telefone_normalizado) values ($1, $2, $3) returning id",
                                  esc, nome_contato, "55319" + str(uuid.uuid4().int)[:8])
    id_etapa = None
    if etapa:
        agente = await pool.fetchval("insert into agentesia_agentes (id_escritorio, id_canal, nome) values ($1, $2, 'Júlia') returning id",
                                     esc, canal)
        id_etapa = await pool.fetchval("insert into agentesia_agente_etapas (id_agente, codigo, ordem) values ($1, $2, 1) returning id",
                                       agente, etapa)
    lead = str(await pool.fetchval(
        "insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_etapa, criado_em) values ($1, $2, $3, $4, $5) returning id",
        esc, contato, canal, id_etapa, datetime(2026, 11, 20, 13, 5, tzinfo=timezone.utc)))
    turno_id = await pool.fetchval("insert into agentesia_turnos (id_escritorio, id_lead, modo) values ($1, $2, 'teste') returning id", esc, lead)
    inicio = datetime(2026, 11, 20, 13, 0, tzinfo=timezone.utc)
    await pool.executemany(
        """insert into agentesia_mensagens (id_escritorio, id_lead, id_turno, autor, texto, enviada_em)
           values ($1, $2, $3, $4, $5, $6)""",
        [(esc, lead, turno_id, "lead" if i % 2 == 0 else "ia", f"antiga {i}", inicio + timedelta(minutes=i)) for i in range(quantas)])
    # mensagem do lead ainda sem turno: fica fora do histórico e da conta
    await pool.execute("insert into agentesia_mensagens (id_escritorio, id_lead, autor, texto, enviada_em) values ($1, $2, 'lead', 'pendente', $3)",
                       esc, lead, inicio + timedelta(days=1))
    return esc, lead


@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_postgres_janela_ficha_e_marca():
    from app.banco.postgres import RepositorioPostgres

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        _esc, lead = await _cenario_pg(pool, "Memória longa", 70)
        historico = await repo.historico(lead)
        comeco = await memoria.ler_comeco(repo, lead)
        assert not comeco.falhou and comeco.pendentes == 30 and len(comeco.antigas) == 30
        assert comeco.antigas[0] == {"autor": "lead", "texto": "antiga 0"} and comeco.antigas[-1]["texto"] == "antiga 29"
        assert historico[0].texto == "antiga 30"                                 # sem buraco nem sobreposição
        assert memoria.acao_de_resumo(lead, comeco)["chave_unica"] == f"{lead}:resumir_conversa:inicio:1"

        modelo = ModeloFalso({"resumo_conversa": [{"resumo": FICHA}, {"resumo": "ficha 2"}]})
        resultado, _ = await memoria.resumir(repo, modelo, lead)
        assert resultado["mensagens"] == 30
        ficha = await pool.fetchrow("select * from agentesia_lead_resumo where id_lead = $1::uuid", lead)
        marca = await pool.fetchval("select texto from agentesia_mensagens where id = $1", ficha["ate_id_mensagem"])
        assert (ficha["resumo"], ficha["mensagens_resumidas"], marca, ficha["modelo"]) == (FICHA, 30, "antiga 29", "falso")
        comeco = await memoria.ler_comeco(repo, lead)
        assert (comeco.resumo, comeco.pendentes, comeco.ate_id_mensagem) == (FICHA, 0, str(ficha["ate_id_mensagem"]))

        antiga = await pool.fetchval("select id from agentesia_mensagens where id_lead = $1::uuid and texto = 'antiga 3'", lead)
        await repo.gravar_resumo(id_lead=lead, resumo="ficha 2", ate_id_mensagem=str(antiga), quantidade=2, modelo="m", tokens=10)
        ficha2 = await pool.fetchrow("select * from agentesia_lead_resumo where id_lead = $1::uuid", lead)
        assert ficha2["ate_id_mensagem"] == ficha["ate_id_mensagem"]           # marca não volta
        assert (ficha2["resumo"], ficha2["mensagens_resumidas"], ficha2["tokens"]) == ("ficha 2", 32, 10)

        await pool.execute("delete from agentesia_leads where id = $1::uuid", lead)
        assert not await pool.fetchval("select count(*) from agentesia_lead_resumo where id_lead = $1::uuid", lead)
    finally:
        await pool.execute("delete from agentesia_escritorios where nome = 'Memória longa'")
        await repo.fechar()


@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_postgres_fila_faz_o_resumo_sem_helena_e_tenta_de_novo_se_a_ia_falhar():
    from app.acoes import Executor
    from app.banco.postgres import RepositorioPostgres

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        await pool.execute("update agentesia_acoes set situacao = 'cancelada' where situacao in ('pendente', 'executando')")
        esc, lead = await _cenario_pg(pool, "Resumo pela fila", 65)              # escritório sem token da Helena
        acao = memoria.acao_de_resumo(lead, await memoria.ler_comeco(repo, lead))
        await repo.enfileirar_acoes(id_escritorio=esc, id_lead=lead, id_turno=None, acoes=[acao])

        def quebrado(_s, _c):
            raise ErroModelo("provedor_fora_do_ar", "503")

        await Executor(pool, "https://api.helena.run", modelo=ModeloFalso({"resumo_conversa": quebrado})).rodar_uma_vez()
        linha = await pool.fetchrow("select situacao, erro, tentativas from agentesia_acoes where id_lead = $1::uuid", lead)
        assert (linha["situacao"], linha["tentativas"]) == ("pendente", 1) and "provedor_fora_do_ar" in linha["erro"]
        assert not await pool.fetchval("select count(*) from agentesia_lead_resumo where id_lead = $1::uuid", lead)

        await pool.execute("update agentesia_acoes set proxima_em = now() where id_lead = $1::uuid", lead)
        modelo = ModeloFalso({"resumo_conversa": {"resumo": FICHA}})
        await Executor(pool, "https://api.helena.run", modelo=modelo).rodar_uma_vez()
        linha = await pool.fetchrow("select situacao, resultado from agentesia_acoes where id_lead = $1::uuid", lead)
        resultado = linha["resultado"] if isinstance(linha["resultado"], dict) else json.loads(linha["resultado"])
        assert linha["situacao"] == "feita" and resultado["mensagens"] == 25
        assert await pool.fetchval("select resumo from agentesia_lead_resumo where id_lead = $1::uuid", lead) == FICHA
        assert await pool.fetchval("select count(*) from agentesia_chamadas_ia where id_escritorio = $1::uuid and papel = 'resumo_conversa'", esc) == 1
    finally:
        await pool.execute("delete from agentesia_escritorios where nome = 'Resumo pela fila'")
        await repo.fechar()


@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_postgres_fatos_com_hora_aviso_do_nome_e_regra_por_etapa():
    from app.banco.postgres import RepositorioPostgres

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        _esc, lead = await _cenario_pg(pool, "Fatos por etapa", 0, etapa="assinatura")
        fatos = await repo.fatos_do_sistema(lead)
        assert fatos["nome no WhatsApp"] == "Maria (pode não ser o nome completo)"     # sem as aspas
        assert fatos["primeiro contato"] == "20/11/2026 10:05"
        assert fatos["contrato"] == "já foi gerado e enviado ao lead. Ainda não consta a assinatura."
        _esc, sem_nome = await _cenario_pg(pool, "Fatos por etapa", 0, etapa="contratoassinado", nome_contato=None)
        fatos = await repo.fatos_do_sistema(sem_nome)
        assert fatos["nome no WhatsApp"] is None and fatos["contrato"] == "consta como JÁ ASSINADO."
    finally:
        await pool.execute("delete from agentesia_escritorios where nome = 'Fatos por etapa'")
        await repo.fechar()
