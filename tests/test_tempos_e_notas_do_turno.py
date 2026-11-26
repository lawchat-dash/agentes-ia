"""Tempo do turno e notas internas do atendimento.

- resposta["tempos"] do turno: duração de cada passo e idas ao banco (app/tempos.py);
- o delay conta da CHEGADA do webhook (a recepção lenta não soma no prazo);
- as gravações antes do envio correm junto da pausa de digitação da 1ª parte;
- notas internas (pela fila, tipo 'nota', sem IA): atendimento iniciado (uma vez por lead), IA pausada pela equipe
  (só na primeira fala que pausa) e IA voltou; nota que falha não derruba o turno nem a pausa.
Banco em memória, IA falsa e Helena falsa. Os testes com Postgres só rodam com AGENTESIA_TESTE_PG_URL.
"""

import asyncio
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app import pipeline as modulo_pipeline
from app.notificacoes import fuso
from tests.test_pipeline import CANAL, LEAD, SIMPLES, montar, webhook

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")


def _notas(repo, trecho=""):
    return [a["dados"]["texto"] for a in repo.acoes if a["tipo"] == "nota" and trecho in a["dados"]["texto"]]


def _humano(texto="Oi, aqui é a Paula do escritório", quando=None):
    return webhook(texto, de=CANAL, para=LEAD, direcao="TO_HUB", origem="DEFAULT", evento="MESSAGE_SENT", quando=quando)


def _hora(quando):
    return quando.astimezone(fuso()).strftime("%H:%M")


# ------------------------------------------------------------------ tempos do turno

async def test_turno_grava_os_tempos_de_cada_passo():
    atendimento, repo, helena = montar(SIMPLES)
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    assert helena.enviadas == ["Oi! Me conta o que aconteceu?"]
    (turno,) = repo.turnos.values()
    tempos = turno["resposta"]["tempos"]
    for passo in ("carregar_contexto", "extrator", "agente", "ia_total", "conferencia", "gravacoes", "envio", "pos_envio"):
        assert passo in tempos["passos_ms"], passo
    assert "primeira_parte_enviada" in tempos["marcas_ms"]
    assert tempos["idas_ao_banco"] == 0 and tempos["total_ms"] >= 0      # banco em memória: nenhuma ida


async def test_delay_conta_da_chegada_e_nao_do_fim_da_recepcao():
    atendimento, repo, helena = montar(SIMPLES)
    repo.escritorios["esc-1"].config["espera_teste_s"] = 0.6
    gravar = repo.gravar_mensagem

    async def gravar_devagar(**kw):                       # recepção lenta (banco longe): 0,4 s
        if kw.get("autor") == "lead":
            await asyncio.sleep(0.4)
        return await gravar(**kw)
    repo.gravar_mensagem = gravar_devagar

    inicio_turno = []
    abrir = repo.abrir_turno

    async def abrir_marcando(**kw):
        inicio_turno.append(time.monotonic())
        return await abrir(**kw)
    repo.abrir_turno = abrir_marcando

    chegada = time.monotonic()
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    espera = inicio_turno[0] - chegada
    assert 0.55 <= espera < 0.9, espera                   # antes: 0,4 s de recepção + 0,6 s de delay = 1,0 s
    assert helena.enviadas == ["Oi! Me conta o que aconteceu?"]


async def test_gravacoes_antes_do_envio_correm_dentro_da_pausa_de_digitacao():
    atendimento, repo, helena = montar(SIMPLES)
    atendimento.digitar = True
    canal = repo.canal

    async def canal_devagar(id_canal):                    # leitura antes do envio que leva 0,3 s
        await asyncio.sleep(0.3)
        return await canal(id_canal)
    repo.canal = canal_devagar

    momentos = {}
    enviar = helena.enviar

    async def enviar_marcando(**kw):
        momentos.setdefault("envio", time.monotonic())
        return await enviar(**kw)
    helena.enviar = enviar_marcando
    gerar = atendimento.modelo.gerar

    async def gerar_marcando(**kw):
        resultado = await gerar(**kw)
        momentos["ia"] = time.monotonic()
        return resultado
    atendimento.modelo.gerar = gerar_marcando

    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    pausa = 1.5                                           # tempo_de_digitacao do texto curto (mínimo 1,5 s)
    decorrido = momentos["envio"] - momentos["ia"]
    assert pausa - 0.1 <= decorrido < pausa + 0.25, decorrido   # antes: 0,3 s de leitura + 1,5 s de pausa


# ------------------------------------------------------------------ nota: atendimento iniciado

async def test_nota_de_atendimento_iniciado_uma_vez_por_lead():
    atendimento, repo, helena = montar(SIMPLES)
    antes = datetime.now(timezone.utc)
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    notas = _notas(repo, "Atendimento iniciado")
    assert notas == [f"🤖 Atendimento iniciado pelo agente Júlia (Primeiro atendimento) às {_hora(antes)}"] or \
        notas == [f"🤖 Atendimento iniciado pelo agente Júlia (Primeiro atendimento) às {_hora(datetime.now(timezone.utc))}"]

    await atendimento.receber(webhook("caí da moto"))     # segunda resposta: não repete
    await atendimento.aguardar_esperas()
    assert len(helena.enviadas) == 2 and len(_notas(repo, "Atendimento iniciado")) == 1


async def test_lead_novo_depois_de_zerar_o_numero_ganha_a_nota_de_novo():
    atendimento, repo, _helena = montar(SIMPLES)
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    # Zerar o número de teste apaga o lead: a próxima conversa é um lead novo (outro id).
    lead = next(iter(repo.leads.values()))
    repo.leads.pop(lead.id)
    repo.mensagens.pop(lead.id, None)
    repo.fatos.pop(lead.id, None)
    await atendimento.receber(webhook("oi de novo"))
    await atendimento.aguardar_esperas()
    assert len(_notas(repo, "Atendimento iniciado")) == 2


async def test_sem_resposta_entregue_nao_ha_nota_de_inicio():
    from tests.test_pipeline import HelenaFalsa
    atendimento, repo, _helena = montar(SIMPLES, helena=HelenaFalsa(falhar=True))
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    assert _notas(repo, "Atendimento iniciado") == []


async def test_nota_que_falha_nao_derruba_o_turno():
    atendimento, repo, helena = montar(SIMPLES)
    enfileirar = repo.enfileirar_acoes

    async def enfileirar_sem_nota(**kw):
        if any(a["tipo"] == "nota" and ":nota:" in a["chave_unica"] for a in kw["acoes"]):
            raise RuntimeError("fila fora do ar")
        return await enfileirar(**kw)
    repo.enfileirar_acoes = enfileirar_sem_nota
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    assert helena.enviadas == ["Oi! Me conta o que aconteceu?"]
    (turno,) = repo.turnos.values()
    assert turno["situacao"] == "respondido"
    assert "pos_envio_falhou:nota_atendimento_iniciado" in [e["tipo"] for e in repo.eventos]


# ------------------------------------------------------------------ nota: IA pausada pela equipe / IA voltou

async def test_nota_de_pausa_pela_equipe_so_na_primeira_fala(monkeypatch):
    atendimento, repo, helena = montar(SIMPLES)
    repo.agentes["canal-1"].minutos_pausa_humano = 30
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    assert (await atendimento.receber(_humano()))["feito"] == "pausado"
    await atendimento.aguardar_esperas()
    lead = next(iter(repo.leads.values()))
    assert _notas(repo, "IA pausada") == [
        "🙋 IA pausada: alguém da equipe entrou no atendimento. Ela volta a responder às " + _hora(lead.pausado_ate)]

    # A atendente fala de novo (a pausa é renovada): não repete a nota.
    await atendimento.receber(_humano("Pode me mandar o laudo?"))
    await atendimento.aguardar_esperas()
    assert len(_notas(repo, "IA pausada")) == 1

    # A pausa vence, o lead escreve: a IA volta sozinha e deixa a nota.
    quando = datetime.now(timezone.utc) + timedelta(minutes=31)
    monkeypatch.setattr(modulo_pipeline, "agora", lambda: quando)
    await atendimento.receber(webhook("ainda estão aí?", quando=quando))
    await atendimento.aguardar_esperas()
    assert lead.estado == "ativo" and len(helena.enviadas) == 2
    assert _notas(repo, "IA voltou") == ["🤖 IA voltou a atender"]


async def test_sem_nota_de_pausa_em_conversa_que_o_lead_nunca_abriu():
    """26/11: a conta dispara avisos automáticos para números da equipe ("NOVA DEMANDA…"). Esses chats não são de lead:
    nada de nota "IA pausada" neles. Nem em número fora da lista de teste com o agente em teste."""
    atendimento, repo, _helena = montar(SIMPLES)
    await atendimento.receber(_humano("🆕 NOVA DEMANDA JUDICIAL DISPONÍVEL"))
    await atendimento.aguardar_esperas()
    assert _notas(repo, "IA pausada") == []

    atendimento, repo, _helena = montar(SIMPLES, numeros_teste=())      # modo teste, lista vazia
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    await atendimento.receber(_humano())
    await atendimento.aguardar_esperas()
    assert _notas(repo, "IA pausada") == []


async def test_nota_de_pausa_sem_volta():
    atendimento, repo, _helena = montar(SIMPLES)
    repo.agentes["canal-1"].config["pausa_sem_volta"] = True
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    await atendimento.receber(_humano())
    await atendimento.aguardar_esperas()
    assert _notas(repo, "IA pausada") == [
        "🙋 IA pausada: alguém da equipe entrou no atendimento. Ela só volta quando a equipe religar"]


async def test_nota_de_pausa_que_falha_nao_desfaz_a_pausa():
    atendimento, repo, _helena = montar(SIMPLES)
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()

    async def fila_quebrada(**_kw):
        raise RuntimeError("fila fora do ar")
    repo.enfileirar_acoes = fila_quebrada
    assert (await atendimento.receber(_humano()))["feito"] == "pausado"
    await atendimento.aguardar_esperas()
    lead = next(iter(repo.leads.values()))
    assert (lead.estado, lead.motivo_estado) == ("pausado", "humano_assumiu")
    assert "pos_envio_falhou:nota_pausa_humano" in [e["tipo"] for e in repo.eventos]


# ------------------------------------------------------------------ Postgres: fatos em lote e tempos com idas ao banco

@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_postgres_fatos_em_lote_e_idas_ao_banco_no_turno():
    from app.banco.postgres import RepositorioPostgres
    from tests.test_postgres import _cenario, _config
    from tests.test_pipeline import HelenaFalsa
    from app.modelo import ModeloFalso
    from tests.test_turno import extrai, fala

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    try:
        conta, numero_canal, id_escritorio = await _cenario(repo)
        modelo = ModeloFalso({"extrator": extrai([("acidente_descricao", "caí da moto", "caí da moto"),
                                                  ("acidente_ano", "2022", "em 2022")]),
                              "etapa": fala("Poxa, sinto muito.")})
        atendimento = modulo_pipeline.Atendimento(repo, modelo, _config(), HelenaFalsa(), digitar=False)
        corpo = webhook("caí da moto em 2022", para=numero_canal)
        corpo["content"]["companyId"] = conta
        await atendimento.receber(corpo)
        await atendimento.aguardar_esperas()
        pool = repo._pool
        lead = await pool.fetchval("select id from agentesia_leads where id_escritorio = $1::uuid", id_escritorio)
        fatos = {k: v for k, v in (await repo.fatos_vigentes(str(lead))).items() if not k.startswith("_")}
        assert fatos == {"acidente_descricao": "caí da moto", "acidente_ano": 2022}

        # Mesma chave de novo: a versão antiga é substituída no mesmo comando (substituido_em = criado_em da nova).
        await repo.gravar_fatos(lead=await repo.lead(str(lead)), id_turno=None,
                                fatos=[{"chave": "acidente_ano", "valor": 2021, "trecho": "foi em 2021"}])
        linhas = await pool.fetch("select valor, criado_em, substituido_em from agentesia_lead_fatos "
                                  "where id_lead = $1 and chave = 'acidente_ano' order by criado_em", lead)
        assert [l["substituido_em"] is None for l in linhas] == [False, True]
        assert linhas[0]["substituido_em"] == linhas[1]["criado_em"]
        # Chave repetida no mesmo lote: o caminho antigo (um por um) e só a última fica vigente.
        await repo.gravar_fatos(lead=await repo.lead(str(lead)), id_turno=None, fatos=[
            {"chave": "sequela", "valor": "sim", "trecho": "a"}, {"chave": "sequela", "valor": "não", "trecho": "b"}])
        assert (await repo.fatos_vigentes(str(lead)))["sequela"] == "não"

        resposta = await pool.fetchval("select resposta from agentesia_turnos where id_lead = $1 and situacao = 'respondido'",
                                       lead)
        import json
        tempos = (json.loads(resposta) if isinstance(resposta, str) else resposta)["tempos"]
        assert 10 <= tempos["idas_ao_banco"] <= 80, tempos
        assert tempos["passos_ms"]["carregar_contexto"] >= 0
    finally:
        await repo.fechar()


@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_postgres_agente_do_canal_numa_consulta_so_traz_as_etapas_em_ordem():
    from app.banco.postgres import RepositorioPostgres
    from tests.test_postgres import _cenario

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    try:
        _conta, numero_canal, id_escritorio = await _cenario(repo)
        canal = await repo.canal_por_numero(id_escritorio, numero_canal)
        agente = await repo.agente_do_canal(canal.id)
        assert [e.codigo for e in agente.etapas] == ["sdr", "closer", "desqualificado"]
        assert agente.principal().codigo == "sdr" and all(isinstance(e.id, str) for e in agente.etapas)
        assert await repo.agente_do_canal(str(uuid.uuid4())) is None
    finally:
        await repo.fechar()
