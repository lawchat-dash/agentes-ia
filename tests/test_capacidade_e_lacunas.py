"""Capacidade (pool com prazo, /saude sem banco, teto de turnos, consultas paralelas, cache da configuração) e as
lacunas dos tickets (IA desligada no meio do envio, follow-up ausente, escritório sem webhook, responder agora, link de
avaliação do Google, chamadas pagas no teto do turno, nota de início antes da 1ª mensagem).

Unitários com fakes; os de banco só rodam com AGENTESIA_TESTE_PG_URL (node db/testes/servidor_local.mjs <porta>).
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import pipeline, vigia
from app.banco import postgres
from app.cerebro import turno as cerebro
from app.modelo import Chamada, Resultado
from tests.test_pipeline import CANAL, LEAD, HelenaFalsa, montar, webhook
from tests.test_turno import extrai, fala

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
PG = pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")


# ============================================================================ A1 /saude sem ir ao banco
class _PoolQueNaoPodeSerUsado:
    def __getattr__(self, nome):
        raise AssertionError(f"o /saude não pode usar o pool ({nome})")


async def test_saude_responde_sem_usar_o_pool(monkeypatch):
    from app import main

    estado = main.app.state
    for nome, valor in (("atendimento", SimpleNamespace(repo=SimpleNamespace(_pool=_PoolQueNaoPodeSerUsado()))),
                        ("cfg", SimpleNamespace(modelo_padrao="falso")), ("tarefas", {}), ("visao", False)):
        monkeypatch.setattr(estado, nome, valor, raising=False)
    monkeypatch.setattr(postgres, "ULTIMA_CONSULTA_OK", [0.0])
    corpo = await main.saude()
    assert corpo["ok"] is True and corpo["banco"] is False          # nenhuma consulta ainda: vivo, banco não confirmado
    postgres._marcar_consulta(SimpleNamespace(exception=None))
    corpo = await main.saude()
    assert corpo["ok"] is True and corpo["banco"] is True and corpo["banco_ultima_consulta_ok_s"] == 0
    postgres._marcar_consulta(SimpleNamespace(exception=RuntimeError("x")))      # consulta com erro não conta
    assert postgres.ULTIMA_CONSULTA_OK[0] > 0


def test_saude_do_banco_fica_no_app_ia():
    from app import servidor
    assert servidor._da_ia("/saude/banco") and servidor._da_ia("/saude") and not servidor._do_painel("/saude/banco")


# ============================================================================ A2 pool com prazo
@PG
async def test_pool_cheio_vira_banco_ocupado(monkeypatch):
    monkeypatch.setenv("AGENTESIA_BANCO_ESPERA_S", "1")
    repo = await postgres.RepositorioPostgres.conectar(URL, max_conexoes=1)
    try:
        assert isinstance(repo._pool, postgres.PoolComPrazo) and repo._pool.prazo_s == 1
        async with repo._pool.acquire():
            with pytest.raises(postgres.BancoOcupado):
                await repo._pool.fetchval("select 1")
        assert await repo._pool.fetchval("select 1") == 1
        assert postgres.segundos_desde_a_ultima_consulta_ok() is not None
    finally:
        await repo.fechar()


def test_banco_ocupado_e_erro_de_banco_na_tela_execucoes():
    from app.gestao import rotas_execucoes
    assert "BancoOcupado" in rotas_execucoes.TIPOS_BANCO
    assert "BancoOcupado" not in rotas_execucoes.TIMEOUTS
    detalhe = pipeline.detalhe_do_erro(postgres.BancoOcupado("x"))
    assert detalhe["tipo"] == "BancoOcupado"


# ============================================================================ A3 teto de turnos e consultas paralelas
async def test_em_paralelo_nunca_passa_do_limite():
    rodando, maximo = [0], [0]

    async def consulta(i):
        rodando[0] += 1
        maximo[0] = max(maximo[0], rodando[0])
        await asyncio.sleep(0.01)
        rodando[0] -= 1
        return i

    assert await pipeline._em_paralelo(*(consulta(i) for i in range(9)), limite=3) == list(range(9))
    assert maximo[0] == 3
    falhas = await pipeline._em_paralelo(consulta(1), asyncio.sleep(0, result=2), return_exceptions=True)
    assert falhas == [1, 2]


async def test_teto_de_turnos_simultaneos(monkeypatch):
    monkeypatch.setenv("AGENTESIA_TURNOS_SIMULTANEOS", "2")
    atendimento, _, _ = montar({"extrator": extrai(), "etapa": fala("oi")})
    rodando, maximo = [0], [0]

    async def na_vez(id_lead, modo):
        rodando[0] += 1
        maximo[0] = max(maximo[0], rodando[0])
        await asyncio.sleep(0.02)
        rodando[0] -= 1

    monkeypatch.setattr(atendimento, "_processar_na_vez", na_vez)
    await asyncio.gather(*(atendimento.processar(f"lead-{i}") for i in range(6)))
    assert maximo[0] == 2


# ============================================================================ A4 cache da configuração
class _PoolContador:
    def __init__(self, linha):
        self.linha, self.idas = linha, 0

    async def fetchrow(self, *_a):
        self.idas += 1
        return self.linha


async def test_cache_da_config_guarda_o_achado_e_nao_o_vazio(monkeypatch):
    from app.gestao import cache_curto
    monkeypatch.setattr(cache_curto, "LIGADO", True)
    postgres.limpar_cache_da_config()
    linha = {"id": uuid.uuid4(), "nome": "Esc", "ia_desligada": False, "situacao": "ativo", "id_segredo_helena": None,
             "config": {"a": 1}}
    pool = _PoolContador(linha)
    repo = postgres.RepositorioPostgres(pool)
    primeiro = await repo.escritorio_por_conta("conta-1")
    primeiro.config["a"] = 99                                   # quem recebe mexe na cópia, não no guardado
    segundo = await repo.escritorio_por_conta("conta-1")
    assert pool.idas == 1 and segundo.config == {"a": 1}
    cache_curto.limpar_todos()                                  # escrita no painel (mesmo processo) apaga
    await repo.escritorio_por_conta("conta-1")
    assert pool.idas == 2
    vazio = _PoolContador(None)
    repo_vazio = postgres.RepositorioPostgres(vazio)
    assert await repo_vazio.canal_por_numero("esc", "5511") is None
    assert await repo_vazio.canal_por_numero("esc", "5511") is None
    assert vazio.idas == 2                                      # "não achou" não fica guardado
    postgres.limpar_cache_da_config()


async def test_eco_da_ia_nao_cria_lead():
    """MESSAGE_SENT de uma parte que a IA já gravou: sai antes de achar/criar o lead."""
    atendimento, repo, helena = montar({"extrator": extrai(), "etapa": fala("Oi!")})
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    chamadas = []
    original = repo.achar_ou_criar_lead

    async def contar(**dados):
        chamadas.append(dados)
        return await original(**dados)

    repo.achar_ou_criar_lead = contar
    eco = webhook("Oi!", de=CANAL, para=LEAD, direcao="TO_HUB", origem="API", evento="MESSAGE_SENT",
                  id_msg=helena.ids[0])
    resultado = await atendimento.receber(eco)
    assert resultado["motivo"] == "eco_da_ia"
    assert chamadas == []


# ============================================================================ B5 IA desligada no meio do envio
async def test_ia_desligada_no_escritorio_antes_da_primeira_parte_nao_envia_nada():
    atendimento, repo, helena = montar({"extrator": extrai(), "etapa": fala("Parte 1.", "Parte 2.")})
    original = atendimento._parar_o_envio

    async def desligar_e_conferir(lead):
        repo.escritorios["esc-1"].ia_desligada = True          # a equipe desligou enquanto a IA pensava
        return await original(lead)

    atendimento._parar_o_envio = desligar_e_conferir
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    assert helena.enviadas == []
    turno_ = next(iter(repo.turnos.values()))
    assert turno_["contexto"]["envio_interrompido"]["motivo"] == "ia_desligada_no_escritorio"
    lead = next(iter(repo.leads.values()))
    assert [m.autor for m in repo.mensagens[lead.id]] == ["lead"]


async def test_agente_pausado_entre_partes_para_o_envio():
    class HelenaQuePausaOAgente(HelenaFalsa):
        repo = None

        async def enviar(self, **dados):
            feito = await super().enviar(**dados)
            self.repo.agentes["canal-1"].situacao = "pausado"
            return feito

    helena = HelenaQuePausaOAgente()
    atendimento, repo, _ = montar({"extrator": extrai(), "etapa": fala("Parte 1.", "Parte 2.")}, helena=helena)
    helena.repo = repo
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    assert helena.enviadas == ["Parte 1."]
    assert next(iter(repo.turnos.values()))["contexto"]["envio_interrompido"]["motivo"] == "agente_pausado"


# ============================================================================ nota de início antes da 1ª mensagem
class HelenaComNota(HelenaFalsa):
    def __init__(self, falhar_nota=False):
        super().__init__()
        self.ordem: list[str] = []
        self.falhar_nota = falhar_nota

    async def nota(self, *, token, id_sessao, texto):
        if self.falhar_nota:
            raise RuntimeError("nota fora")
        self.ordem.append("nota:" + texto)

    async def enviar(self, **dados):
        feito = await super().enviar(**dados)
        self.ordem.append("msg:" + (dados.get("texto") or ""))
        return feito


async def test_nota_de_inicio_sai_antes_da_primeira_mensagem_e_uma_vez_so():
    helena = HelenaComNota()
    atendimento, repo, _ = montar({"extrator": extrai(), "etapa": [fala("Oi!", "Tudo bem?"), fala("Certo.")]},
                                  helena=helena)
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    assert helena.ordem[0].startswith("nota:🤖 Atendimento iniciado pelo agente Júlia")
    assert helena.ordem[1:] == ["msg:Oi!", "msg:Tudo bem?"]
    notas = [a for a in repo.acoes if a["tipo"] == "nota" and a["chave_unica"].endswith(":nota:atendimento_iniciado")]
    assert len(notas) == 1 and notas[0]["situacao"] == "feita"   # direta: a fila não manda de novo
    await atendimento.receber(webhook("e agora?"))
    await atendimento.aguardar_esperas()
    assert [o for o in helena.ordem if o.startswith("nota:")] == [helena.ordem[0]]   # só no primeiro turno


async def test_nota_de_inicio_que_falha_nao_atrasa_e_vai_pela_fila():
    helena = HelenaComNota(falhar_nota=True)
    atendimento, repo, _ = montar({"extrator": extrai(), "etapa": fala("Oi!")}, helena=helena)
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    assert helena.ordem == ["msg:Oi!"]
    notas = [a for a in repo.acoes if a["chave_unica"].endswith(":nota:atendimento_iniciado")]
    assert len(notas) == 1 and notas[0]["situacao"] == "pendente"   # o Executor manda depois, como antes


# ============================================================================ B8 link de avaliação do Google
LINK = "https://g.page/r/escritorio-teste/review"


def _saida(mensagens, antes="sdr", depois="sdr"):
    saida = cerebro.Saida(etapa_antes=antes, etapa_depois=depois)
    saida.mensagens = [{"tipo": "texto", "texto": t} for t in mensagens]
    return saida


def _agente(**config):
    from app.banco.tipos import Agente
    return Agente(id="ag", id_escritorio="esc", id_canal="c", nome="Júlia",
                  config={"variables": {"LINK AVALIACAO GOOGLE": LINK}, **config})


def test_link_de_avaliacao_sai_uma_vez_so():
    atendimento, _, _ = montar({})
    entrada = SimpleNamespace(etapa="sdr", historico=[])
    saida = _saida(["Obrigada!\nSe puder, avalie: " + LINK])
    atendimento._guardar_link_de_avaliacao(_agente(), entrada, saida)
    assert saida.mensagens[0]["texto"].endswith(LINK)            # primeira vez: vai
    entrada = SimpleNamespace(etapa="sdr", historico=[{"autor": "você", "texto": "Avalie: " + LINK + "/"}])
    saida = _saida(["Obrigada!\nSe puder, avalie: " + LINK.replace("https://", "http://www."), LINK])
    atendimento._guardar_link_de_avaliacao(_agente(), entrada, saida)
    assert [m["texto"] for m in saida.mensagens] == ["Obrigada!"]
    assert any(e["tipo"] == "link_avaliacao_bloqueado" for e in saida.eventos)


def test_link_de_avaliacao_bloqueado_para_desqualificado():
    atendimento, _, _ = montar({})
    entrada = SimpleNamespace(etapa="sdr", historico=[])
    saida = _saida(["Infelizmente não há direito.", "Avalie a gente: " + LINK], depois="desqualificado")
    atendimento._guardar_link_de_avaliacao(_agente(), entrada, saida)
    assert [m["texto"] for m in saida.mensagens] == ["Infelizmente não há direito."]
    saida = _saida(["Avalie a gente: " + LINK], antes="desqualificado", depois="desqualificado")
    atendimento._guardar_link_de_avaliacao(_agente(avaliacao_google_ao_desqualificado=True), entrada, saida)
    assert len(saida.mensagens) == 1                             # liberado pelo escritório
    saida = _saida(["Oi"])
    atendimento._guardar_link_de_avaliacao(_agente(variables={}), entrada, saida)   # sem link cadastrado: nada muda
    assert saida.mensagens == [{"tipo": "texto", "texto": "Oi"}]


# ============================================================================ B9 chamadas pagas no teto do turno
async def test_teto_do_turno_grava_as_chamadas_ja_pagas(monkeypatch):
    monkeypatch.setenv("AGENTESIA_TETO_TURNO_S", "5")
    atendimento, repo, helena = montar({"extrator": extrai(), "etapa": fala("Oi!")})

    async def cerebro_lento(modelo, entrada):
        await modelo.gerar(papel="extrator", sistema="s", conteudo="c" * 400, esquema={}, modelo="falso")
        await asyncio.sleep(60)

    monkeypatch.setattr(pipeline.cerebro, "processar", cerebro_lento)
    monkeypatch.setattr(atendimento, "_teto_do_turno", lambda: 0.05)
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    assert helena.enviadas == []
    assert [c["papel"] for c in repo.chamadas] == ["extrator"]


async def test_modelo_que_anota_guarda_chamadas_com_erro():
    from app.modelo import ErroModelo

    class Falha:
        async def gerar(self, **_):
            erro = ErroModelo("sem_conexao", "x")
            erro.chamadas = [Chamada(papel="auditor", modelo="m", sucesso=False)]
            raise erro

    caderno = pipeline.ModeloQueAnota(Falha())
    with pytest.raises(ErroModelo):
        await caderno.gerar(papel="auditor")
    assert [c.papel for c in caderno.chamadas] == ["auditor"]

    class Ok:
        pedidos = ["x"]

        async def gerar(self, **_):
            return Resultado(dados={}, chamadas=[Chamada(papel="etapa", modelo="m")])

    caderno = pipeline.ModeloQueAnota(Ok())
    await caderno.gerar(papel="etapa")
    assert [c.papel for c in caderno.chamadas] == ["etapa"] and caderno.pedidos == ["x"]


# ============================================================================ B7b escritório sem webhook (horário)
def test_silencio_conta_so_no_horario_comercial_de_hoje(monkeypatch):
    monkeypatch.delenv("AGENTESIA_SEM_WEBHOOK_HORARIO", raising=False)
    sp = timezone(timedelta(hours=-3))
    segunda_14h = datetime(2026, 11, 23, 14, 0, tzinfo=sp)
    sexta_18h = datetime(2026, 11, 20, 18, 0, tzinfo=sp)
    assert vigia.silencio_conta("America/Sao_Paulo", sexta_18h, 4, segunda_14h)        # 9h-14h: 5 h de silêncio
    assert not vigia.silencio_conta("America/Sao_Paulo", sexta_18h, 4, segunda_14h.replace(hour=12))   # só 3 h
    assert not vigia.silencio_conta("America/Sao_Paulo", sexta_18h, 1, segunda_14h.replace(hour=20))   # fora do horário
    sabado = datetime(2026, 11, 21, 15, 0, tzinfo=sp)
    assert not vigia.silencio_conta("America/Sao_Paulo", sexta_18h, 1, sabado)          # fim de semana
    assert not vigia.silencio_conta("America/Sao_Paulo", segunda_14h - timedelta(hours=1), 4, segunda_14h)


# ============================================================================ banco: vigia, follow-up e responder agora
async def _cenario(pool, *, followup_ativo=True, modo="producao"):
    segredo = await pool.fetchval("select vault.create_secret('token-vigia', 'teste')")
    esc = await pool.fetchval("insert into agentesia_escritorios (nome) values ('Vigia Adv') returning id")
    await pool.execute("insert into agentesia_integracoes (id_escritorio, tipo, id_segredo_vault, situacao) "
                       "values ($1, 'helena', $2, 'ok')", esc, segredo)
    canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado, id_canal_helena) "
                                "values ($1, $2, $3) returning id", esc, "5511" + str(uuid.uuid4().int)[:9], "ch-" + uuid.uuid4().hex[:8])
    config = {"followup": {"ativo": followup_ativo, "horario": {"inicio": 0, "fim": 24, "dias": [0, 1, 2, 3, 4, 5, 6]},
                           "passos": [{"apos_horas": 1, "modo": "texto", "texto": "Oi {nome}!"}]}}
    agente = await pool.fetchval(
        """insert into agentesia_agentes (id_escritorio, id_canal, nome, produto, config, situacao, modo)
           values ($1, $2, 'Júlia', 'auxilio_acidente', $3::jsonb, 'ativo', $4) returning id""",
        esc, canal, json.dumps(config), modo)
    sdr = await pool.fetchval("insert into agentesia_agente_etapas (id_agente, codigo, ordem, principal) "
                              "values ($1, 'sdr', 0, true) returning id", agente)
    contato = await pool.fetchval("insert into agentesia_contatos (id_escritorio, nome, telefone_normalizado) "
                                  "values ($1, 'Ana', $2) returning id", esc, "5511" + str(uuid.uuid4().int)[:9])
    fala_ia = datetime.now(timezone.utc) - timedelta(hours=3)
    lead = await pool.fetchval(
        """insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_agente, id_etapa, id_sessao_helena,
                                        ultima_mensagem_lead_em, ultima_resposta_ia_em)
           values ($1, $2, $3, $4, $5, 'sessao-v', $6, $7) returning id""",
        esc, contato, canal, agente, sdr, fala_ia - timedelta(minutes=2), fala_ia)
    for autor, quando in (("lead", fala_ia - timedelta(minutes=2)), ("ia", fala_ia)):
        await pool.execute("""insert into agentesia_mensagens (id_escritorio, id_lead, autor, tipo, texto, enviada_em)
                              values ($1, $2, $3, 'texto', 'x', $4)""", esc, lead, autor, quando)
    return SimpleNamespace(esc=esc, canal=canal, agente=agente, lead=lead, fala_ia=fala_ia)


@PG
async def test_followup_ausente_e_agendado_uma_vez_e_respeita_a_equipe():
    repo = await postgres.RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    vigia._tentados.clear()
    try:
        c = await _cenario(pool)
        humano = await _cenario(pool)                      # a equipe falou depois da IA: não reaborda
        await pool.execute("""insert into agentesia_mensagens (id_escritorio, id_lead, autor, tipo, texto, enviada_em)
                              values ($1, $2, 'humano', 'texto', 'deixa comigo', now() - interval '1 hour')""",
                           humano.esc, humano.lead)
        antigo = await _cenario(pool)                      # fora da janela de leads recentes
        await pool.execute("update agentesia_leads set ultima_resposta_ia_em = now() - interval '5 days' where id = $1",
                           antigo.lead)
        await vigia.followup_ausente(pool, horas=2, janela_h=24, limite=50)
        agendados = {r["id_lead"] for r in await pool.fetch(
            "select id_lead from agentesia_followups where situacao = 'pendente' and id_lead = any($1::uuid[])",
            [c.lead, humano.lead, antigo.lead])}
        assert agendados == {c.lead}
        assert await pool.fetchval("select count(*) from agentesia_eventos where id_lead = $1 and tipo = "
                                   "'followup_recuperado'", c.lead) == 1
        vigia._tentados.clear()
        await vigia.followup_ausente(pool, horas=2, janela_h=24, limite=50)    # já tem follow-up: não duplica
        assert await pool.fetchval("select count(*) from agentesia_followups where id_lead = $1", c.lead) == 1
    finally:
        await repo.fechar()


@PG
async def test_aviso_de_followup_desligado_em_producao_uma_vez_por_semana():
    repo = await postgres.RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        c = await _cenario(pool, followup_ativo=False)
        ligado = await _cenario(pool)
        await vigia.followup_desligado(pool, dias=7)
        await vigia.followup_desligado(pool, dias=7)
        por_esc = {r["id_escritorio"]: r["n"] for r in await pool.fetch(
            """select id_escritorio, count(*) as n from agentesia_eventos where tipo = 'followup_desligado'
               and id_escritorio = any($1::uuid[]) group by 1""", [c.esc, ligado.esc])}
        assert por_esc == {c.esc: 1}
    finally:
        await repo.fechar()


@PG
async def test_escritorio_sem_webhook_avisa_uma_vez(monkeypatch):
    repo = await postgres.RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        c = await _cenario(pool)
        await pool.execute(
            """insert into agentesia_eventos_recebidos (id_escritorio, origem, id_externo, tipo, payload, recebido_em)
               values ($1, 'helena', $2, 'lead', '{}'::jsonb, now() - interval '30 hours')""", c.esc, uuid.uuid4().hex)
        monkeypatch.setattr(vigia, "silencio_conta", lambda *_a, **_k: True)
        await vigia.escritorio_sem_webhook(pool, horas=4)
        await vigia.escritorio_sem_webhook(pool, horas=4)
        assert await pool.fetchval("select count(*) from agentesia_eventos where id_escritorio = $1 "
                                   "and tipo = 'escritorio_sem_webhook'", c.esc) == 1
    finally:
        await repo.fechar()


@PG
async def test_followup_nao_sai_se_a_ia_foi_desligada_enquanto_escrevia():
    from app.followup import servico
    repo = await postgres.RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        c = await _cenario(pool)
        await servico._agendar(pool, str(c.lead), c.fala_ia)
        f = dict(await pool.fetchrow("""update agentesia_followups set situacao = 'reservado',
                                        reservado_ate = now() + interval '5 minutes' where id_lead = $1 returning *""",
                                     c.lead))
        disparador = servico.Disparador(pool, None, "http://helena.invalid")
        await pool.execute("update agentesia_leads set estado = 'pausado', motivo_estado = 'desativada_pela_equipe' "
                           "where id = $1", c.lead)
        assert await disparador._ainda_vale(f) is False
        assert await pool.fetchval("select motivo from agentesia_followups where id = $1", f["id"]) \
            == "ia_desligada_durante_o_envio"
    finally:
        await repo.fechar()


@PG
async def test_responder_agora_devolve_as_mensagens_sem_resposta():
    from fastapi import HTTPException

    from app.gestao.repositorio import RepositorioGestao
    from app.gestao.rotas import Contexto
    from app.gestao.rotas_reprocessar import reprocessar_conversa

    repo = await postgres.RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        c = await _cenario(pool)
        pedido = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(gestao=RepositorioGestao(pool),
                                                                           atendimento=None)))
        ctx = Contexto({"id": None, "papel": "gestor", "id_escritorio": str(c.esc)}, str(c.esc))
        with pytest.raises(HTTPException) as erro:               # a última fala é da IA: nada a responder
            await reprocessar_conversa(str(c.lead), pedido, ctx)
        assert erro.value.status_code == 409
        turno_ = await pool.fetchval("""insert into agentesia_turnos (id_escritorio, id_lead, modo, situacao, motivo)
                                        values ($1, $2, 'producao', 'erro', 'erro_interno:X') returning id""",
                                     c.esc, c.lead)
        await pool.execute("""insert into agentesia_mensagens (id_escritorio, id_lead, autor, tipo, texto, enviada_em,
                                                                id_turno)
                              values ($1, $2, 'lead', 'texto', 'e aí?', now() - interval '10 minutes', $3)""",
                           c.esc, c.lead, turno_)
        feito = await reprocessar_conversa(str(c.lead), pedido, ctx)
        assert feito == {"ok": True, "mensagens": 1}
        assert "e aí?" in [m.texto for m in await repo.mensagens_pendentes(str(c.lead))]
        assert await pool.fetchval("select responder_apos is not null from agentesia_leads where id = $1", c.lead)
        outro = Contexto({"id": None, "papel": "gestor", "id_escritorio": str(uuid.uuid4())}, str(uuid.uuid4()))
        with pytest.raises(HTTPException) as erro:               # gestor de outro escritório não vê
            await reprocessar_conversa(str(c.lead), pedido, outro)
        assert erro.value.status_code == 404
    finally:
        await repo.fechar()
