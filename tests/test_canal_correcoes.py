"""Correções da área "canal": webhook, número do lead, card na 1ª mensagem, atraso, eco, janela de 24 h, balões,
tipo desconhecido, entrega assíncrona, novas tentativas de envio e token da Helena por escritório.

Unitários com fakes (repositório em memória, Helena falsa, httpx.MockTransport). Os de banco só rodam com
AGENTESIA_TESTE_PG_URL (PGlite local, ver tests/test_postgres.py).
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.canal import filtro, webhook as canal_webhook
from app.canal.helena import ClienteHelena, ErroHelena, ler_webhook, numero_do_lead
from app.cerebro import formatador
from tests.test_pipeline import CANAL, LEAD, SIMPLES, HelenaFalsa, montar, webhook

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")


def _notas(repo):
    return [a["dados"]["texto"] for a in repo.acoes if a["tipo"] == "nota"]


# ============================================================================ [0] segredo do webhook global
def test_segredo_global_e_derivado_e_nao_abre_os_escritorios(monkeypatch):
    monkeypatch.setenv("AGENTESIA_WEBHOOK_SEGREDO", "mestre")
    id_esc = str(uuid.uuid4())
    global_ = canal_webhook.segredo_global()
    assert global_ and global_ != "mestre" and len(global_) == 40
    assert global_ != canal_webhook.segredo_do_escritorio(id_esc)
    assert "mestre" not in (canal_webhook.url_do_escritorio(id_esc) or "")
    monkeypatch.delenv("AGENTESIA_WEBHOOK_SEGREDO")
    assert canal_webhook.segredo_global() is None and canal_webhook.segredo_do_escritorio(id_esc) is None


def test_rota_global_desligada_por_padrao_e_nunca_aceita_o_mestre(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    cliente = TestClient(app)
    monkeypatch.setenv("AGENTESIA_WEBHOOK_SEGREDO", "mestre")
    monkeypatch.delenv("AGENTESIA_WEBHOOK_GLOBAL", raising=False)
    assert cliente.post("/webhook/helena?segredo=mestre", json={}).status_code == 404
    monkeypatch.setenv("AGENTESIA_WEBHOOK_GLOBAL", "1")
    assert cliente.post("/webhook/helena?segredo=mestre", json={}).status_code == 401      # o mestre não vale mais
    assert cliente.post("/webhook/helena", json={}, headers={"x-agentesia-segredo": "mestre"}).status_code == 401


def test_log_de_acesso_nao_mostra_o_segredo():
    filtro_log = canal_webhook.FiltroDeSegredo()
    registro = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                                 ("1.2.3.4:5", "POST", "/webhook/helena/abc?segredo=s3cr3t&teste=1", "1.1", 200), None)
    assert filtro_log.filter(registro)
    linha = registro.getMessage()
    assert "s3cr3t" not in linha and "segredo=***&teste=1" in linha
    canal_webhook.proteger_logs_de_acesso()
    canal_webhook.proteger_logs_de_acesso()                                                   # idempotente
    assert sum(isinstance(f, canal_webhook.FiltroDeSegredo) for f in logging.getLogger("uvicorn.access").filters) == 1


# ============================================================================ [1] contato @lid / número inválido
def test_numero_do_lead_recusa_lid_e_numero_grande_sem_55():
    assert numero_do_lead("123456789012345@lid") is None
    assert numero_do_lead("+123456789012345") is None                 # 15 dígitos sem 55: não é telefone de lead
    assert numero_do_lead("+5511988887777") == "5511988887777"
    assert numero_do_lead("+351912345678") == "351912345678"           # estrangeiro vale
    evento_bruto = webhook("oi")
    evento_bruto["content"]["details"]["from"] = "123456789012345@lid"
    evento = ler_webhook(evento_bruto)
    assert evento.numero_lead is None and evento.numero_canal == CANAL


def _do_lid(texto="oi", sessao="sessao-1"):
    corpo = webhook(texto)
    corpo["content"]["details"]["from"] = "123456789012345@lid"
    corpo["content"]["sessionId"] = sessao
    return corpo


async def test_lid_sem_lead_ligado_vira_contato_sem_numero():
    atendimento, repo, helena = montar(SIMPLES)
    resultado = await atendimento.receber(_do_lid())
    assert resultado == {"feito": "ignorado", "motivo": "contato_sem_numero"}
    assert not repo.leads and any(e["tipo"] == "contato_sem_numero" for e in repo.eventos)


async def test_lid_com_lead_ja_ligado_a_sessao_segue_o_fluxo_normal():
    atendimento, repo, helena = montar(SIMPLES)
    await atendimento.receber(webhook("oi"))                              # o lead já existe, com número e sessão
    await atendimento.aguardar_esperas()
    resultado = await atendimento.receber(_do_lid("tudo bem?"))
    assert resultado["feito"] == "agendado"
    await atendimento.aguardar_esperas()
    assert len(repo.leads) == 1 and next(iter(repo.leads.values())).telefone == LEAD
    assert len(repo.turnos) == 2 and "tudo bem?" in atendimento.modelo.pedidos[-1]["conteudo"]


async def test_ddi_fora_da_lista_do_escritorio_nao_vira_lead():
    atendimento, repo, _helena = montar(SIMPLES)
    repo.escritorios["esc-1"].config["filtro"] = {"ddi_aceitos": ["55"]}
    resultado = await atendimento.receber(webhook("hello", de="351912345678"))
    assert resultado["motivo"] == "contato_sem_numero" and not repo.leads
    assert filtro.ddi_aceito("5511988887777", {"filtro": {"ddi_aceitos": ["55"]}})
    assert filtro.ddi_aceito("351912345678", {})                           # sem lista: aceita todos


# ============================================================================ [2] card na 1ª mensagem do lead
async def test_atendente_fala_primeiro_e_o_card_sai_na_primeira_mensagem_do_lead(monkeypatch):
    atendimento, repo, _helena = montar(SIMPLES)
    chamadas = []

    async def lead_novo(escritorio, agente, lead):
        chamadas.append(lead.id)

    monkeypatch.setattr(atendimento, "_lead_novo", lead_novo)
    humano = webhook("Olá, aqui é a Paula", de=CANAL, para=LEAD, direcao="TO_HUB", origem="DEFAULT", evento="MESSAGE_SENT")
    await atendimento.receber(humano)
    lead = next(iter(repo.leads.values()))
    assert lead.estado == "pausado" and chamadas == []                   # a fala do atendente não cria card
    await atendimento.receber(webhook("oi, quero saber do meu caso"))
    await atendimento.receber(webhook("é sobre auxílio"))
    await atendimento.aguardar_esperas()
    assert chamadas == [lead.id]                                           # uma vez, na primeira mensagem dele


# ============================================================================ [3] mensagem atrasada e fuso
async def test_mensagem_atrasada_deixa_nota_no_chat():
    atendimento, repo, helena = montar(SIMPLES)
    resultado = await atendimento.receber(webhook("oi", quando=datetime.now(timezone.utc) - timedelta(minutes=40)))
    assert resultado["motivo"] == "mensagem_atrasada"
    await atendimento.aguardar_esperas()
    assert helena.enviadas == []
    assert any(t.startswith("⏰ Esta mensagem do lead chegou com 40 min de atraso") for t in _notas(repo))


def test_timestamp_sem_fuso_usa_a_hora_de_chegada():
    corpo = webhook("oi")
    corpo["content"]["timestamp"] = (datetime.now(timezone.utc) - timedelta(hours=3)).replace(tzinfo=None).isoformat()
    evento = ler_webhook(corpo)
    assert abs((datetime.now(timezone.utc) - evento.enviada_em).total_seconds()) < 5
    corpo["content"]["timestamp"] = "2026-01-02T10:00:00+00:00"
    assert ler_webhook(corpo).enviada_em == datetime(2026, 1, 2, 10, tzinfo=timezone.utc)


# ============================================================================ [4] corrida com o eco (memória)
async def test_eco_que_chega_antes_vira_mensagem_da_ia_na_memoria():
    atendimento, repo, _helena = montar(SIMPLES)
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    lead = next(iter(repo.leads.values()))
    eco = webhook("Olá!", de=CANAL, para=LEAD, direcao="TO_HUB", origem="API", evento="MESSAGE_SENT", id_msg="env-x")
    assert (await atendimento.receber(eco))["autor"] == "automacao"
    id_msg = await repo.gravar_mensagem(lead=lead, autor="ia", tipo="texto", texto="Olá!", texto_extraido=None, url_midia=None,
                                        enviada_em=datetime.now(timezone.utc), id_externo="env-x", id_turno="turno-9",
                                        situacao_envio="enviada")
    assert id_msg is not None
    linha = next(m for m in repo.mensagens[lead.id] if m.id_externo == "env-x")
    assert (linha.autor, linha.id_turno) == ("ia", "turno-9")
    assert await repo.mensagem_e_da_ia("esc-1", "env-x")


# ============================================================================ [5] janela de 24 h do número oficial
def _segurar(atendimento, monkeypatch, abre_em):
    from app import horario
    agendados = []
    monkeypatch.setattr(horario, "decidir", lambda _config, quando=None: ("fora_do_horario", abre_em))
    monkeypatch.setattr(atendimento, "_agendar", lambda id_lead, espera: agendados.append((id_lead, espera)))
    return agendados


async def test_numero_oficial_com_janela_fechando_antes_de_abrir_nao_segura_a_resposta(monkeypatch):
    atendimento, repo, helena = montar(SIMPLES, modo="producao")
    repo.canais["canal-1"].tipo = "oficial"
    # Sexta 19h30: o escritório só abre na segunda 8h (mais de 60 h depois).
    agendados = _segurar(atendimento, monkeypatch, datetime.now(timezone.utc) + timedelta(hours=60, minutes=30))
    await atendimento.receber(webhook("oi, preciso de ajuda"))
    lead = next(iter(repo.leads.values()))
    await atendimento.processar(lead.id)
    assert helena.enviadas == [] and len(agendados) == 1                     # não reagendou para segunda-feira
    turno = next(iter(repo.turnos.values()))
    assert (turno["situacao"], turno["motivo"]) == ("silencio", "janela_fechada")
    assert any(e["tipo"] == "janela_fechada" for e in repo.eventos)
    assert any("janela de 24 h do número oficial" in t for t in _notas(repo))


async def test_numero_nao_oficial_ou_janela_aberta_segura_ate_abrir(monkeypatch):
    for tipo, horas in (("nao_oficial", 60), ("oficial", 10)):
        atendimento, repo, helena = montar(SIMPLES, modo="producao")
        repo.canais["canal-1"].tipo = tipo
        agendados = _segurar(atendimento, monkeypatch, datetime.now(timezone.utc) + timedelta(hours=horas))
        await atendimento.receber(webhook("oi"))
        lead = next(iter(repo.leads.values()))
        await atendimento.processar(lead.id)
        assert helena.enviadas == [] and not repo.turnos
        assert agendados[-1][0] == lead.id and agendados[-1][1] > 3600         # segurou para a abertura


# ============================================================================ [6] teto de balões
def _texto(t):
    return {"tipo": "texto", "texto": t, "espera_s": formatador.tempo_de_digitacao(t)}


def test_nove_baloes_viram_no_maximo_cinco_com_link_midia_e_pergunta_sozinhos():
    partes = [_texto(f"Frase número {i} da explicação.") for i in range(5)]
    partes.insert(4, _texto("Veja o vídeo: https://exemplo.com/video"))
    partes.insert(5, {"tipo": "midia", "chave": "audio_honorarios", "espera_s": 2.0})
    partes += [_texto("Mais um detalhe."), _texto("Podemos seguir com a análise?")]
    assert len(partes) == 9
    saida = formatador.juntar_excedente(partes, teto=5)
    assert len(saida) <= 5
    assert {"tipo": "midia", "chave": "audio_honorarios", "espera_s": 2.0} in saida
    assert any(p.get("texto") == "Veja o vídeo: https://exemplo.com/video" for p in saida)
    assert saida[-1]["texto"] == "Podemos seguir com a análise?"
    juntado = "\n\n".join(str(p.get("texto", "")) for p in saida)
    for parte in partes:
        assert str(parte.get("texto", "")) in juntado                           # nada se perde


def test_juntar_respeita_o_limite_por_balao_e_nao_mexe_abaixo_do_teto():
    poucas = [_texto("a"), _texto("b")]
    assert formatador.juntar_excedente(poucas, teto=5) is poucas
    grandes = [_texto("x" * 600) for _ in range(7)]
    saida = formatador.juntar_excedente(grandes, teto=5)
    assert len(saida) == 7 and all(len(p["texto"]) <= 1000 for p in saida)   # não cabe: fica acima do teto


async def test_pipeline_aplica_o_teto_do_agente():
    from tests.test_turno import extrai
    from tests.test_turno import fala
    atendimento, repo, helena = montar({"extrator": extrai(), "etapa": fala(*[f"Parte {i}." for i in range(9)])})
    repo.agentes["canal-1"].config["max_baloes"] = 3
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    assert len(helena.enviadas) == 3 and "Parte 0." in helena.enviadas[0]


# ============================================================================ [7] tipo desconhecido com arquivo
@pytest.mark.parametrize("tipo", ["PTV", "INTERACTIVE"])
async def test_tipo_desconhecido_chega_a_ia_como_marcador(tipo):
    corpo = webhook(None, tipo=tipo, file={"publicUrl": "https://arquivos.invalid/x"})
    evento = ler_webhook(corpo)
    assert evento.tipo == "texto" and f"tipo {tipo.lower()}" in (evento.texto_extraido or "")
    assert filtro.antes_do_banco(evento) is None
    atendimento, _repo, helena = montar(SIMPLES)
    await atendimento.receber(corpo)
    await atendimento.aguardar_esperas()
    conteudo = atendimento.modelo.pedidos[0]["conteudo"]
    assert f"tipo {tipo.lower()}" in conteudo and "(mensagem vazia)" not in conteudo


# ============================================================================ [9] novas tentativas de envio
def _cliente(responder, pausa_s=0.0):
    chamadas = []

    def tratar(pedido):
        chamadas.append(pedido)
        return responder(len(chamadas), pedido)

    return ClienteHelena("https://api.helena.invalid", httpx.AsyncClient(transport=httpx.MockTransport(tratar)),
                         pausa_s=pausa_s), chamadas


async def test_timeout_de_leitura_nao_repete():
    def responder(n, pedido):
        raise httpx.ReadTimeout("demorou", request=pedido)

    cliente, chamadas = _cliente(responder)
    with pytest.raises(ErroHelena, match="sem_confirmacao"):
        await cliente.enviar(token="t", id_sessao="s", id_canal=None, texto="oi")
    assert len(chamadas) == 1


async def test_conexao_recusada_repete_e_devolve_o_id():
    def responder(n, pedido):
        if n < 3:
            raise httpx.ConnectError("recusada", request=pedido)
        return httpx.Response(200, json={"id": "msg-1"})

    cliente, chamadas = _cliente(responder)
    assert await cliente.enviar(token="t", id_sessao="s", id_canal="c", texto="oi") == "msg-1"
    assert len(chamadas) == 3 and json.loads(chamadas[0].content) == {"text": "oi", "channelId": "c"}


async def test_429_respeita_o_retry_after(monkeypatch):
    import asyncio
    esperas = []

    async def dormir(segundos):
        esperas.append(segundos)

    monkeypatch.setattr(asyncio, "sleep", dormir)

    def responder(n, pedido):
        if n == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        if n == 2:
            return httpx.Response(429, headers={"Retry-After": "90"})
        return httpx.Response(200, json={"id": "msg-2"})

    cliente, chamadas = _cliente(responder, pausa_s=2.5)
    assert await cliente.enviar(token="t", id_sessao="s", id_canal=None, texto="oi") == "msg-2"
    assert esperas == [7.0, 10.0] and len(chamadas) == 3                  # limitado a 10 s


async def test_erro_do_pedido_nao_repete():
    cliente, chamadas = _cliente(lambda n, p: httpx.Response(400, json={}))
    with pytest.raises(ErroHelena, match="HTTP 400"):
        await cliente.enviar(token="t", id_sessao="s", id_canal=None, texto="oi")
    assert len(chamadas) == 1


# ============================================================================ [10] token da Helena por escritório
async def test_sem_token_do_escritorio_nao_usa_o_do_env_e_avisa_o_cadastro(monkeypatch):
    monkeypatch.setenv("AGENTESIA_HELENA_TOKEN", "token-global-de-outra-conta")
    monkeypatch.delenv("AGENTESIA_MODO_LAB", raising=False)
    atendimento, repo, helena = montar(SIMPLES)
    repo.segredos.clear()
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    assert helena.enviadas == []
    evento = next(e for e in repo.eventos if e["tipo"] == "escritorio_sem_token_helena")
    assert (evento["gravidade"], evento["responsavel"]) == ("erro", "cadastro")
    assert not any(e["tipo"] == "envio_falhou" for e in repo.eventos)
    lead = next(iter(repo.leads.values()))
    ia = [m for m in repo.mensagens[lead.id] if m.autor == "ia"]
    assert ia and all(repo.situacoes[m.id] == ("falhou", "sem token da Helena") for m in ia)


async def test_envio_agenda_a_conferencia_de_entrega():
    atendimento, repo, helena = montar(SIMPLES)
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    conferir = [a for a in repo.acoes if a["tipo"] == "conferir_entrega"]
    assert len(conferir) == 1 and conferir[0]["dados"]["ids"] == helena.ids and conferir[0]["atraso_s"] == 60
    assert conferir[0]["chave_unica"].endswith(":entrega")


# ============================================================================ banco local (PGlite)
async def _escritorio_pg(pool, *, integracao: bool, coluna: bool, token="token-pg"):
    segredo = await pool.fetchval("select vault.create_secret($1, 'teste')", token)
    esc = await pool.fetchval(
        "insert into agentesia_escritorios (nome, id_conta_helena, id_segredo_helena) values ('Canal', $1::uuid, $2) returning id",
        str(uuid.uuid4()), segredo if coluna else None)
    if integracao:
        await pool.execute("insert into agentesia_integracoes (id_escritorio, tipo, id_segredo_vault, situacao) "
                           "values ($1, 'helena', $2, 'ok')", esc, segredo)
    canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado, tipo) values ($1, $2, 'oficial') "
                                "returning id", esc, "5511" + str(uuid.uuid4().int)[:9])
    contato = await pool.fetchval("insert into agentesia_contatos (id_escritorio, telefone_normalizado) values ($1, $2) returning id",
                                  esc, "5511" + str(uuid.uuid4().int)[:9])
    lead = await pool.fetchval("insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_sessao_helena) "
                               "values ($1, $2, $3, 'sessao-pg') returning id", esc, contato, canal)
    return str(esc), str(canal), str(lead)


@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_postgres_eco_antes_da_ia_vira_ia_e_token_com_reserva_da_coluna():
    from app.banco.postgres import RepositorioPostgres, token_helena

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        esc, canal, id_lead = await _escritorio_pg(pool, integracao=False, coluna=True, token="token-coluna")
        lead = await repo.lead(id_lead)
        eco, do_lead = "eco-" + uuid.uuid4().hex, "lead-" + uuid.uuid4().hex
        # [4] eco (automacao) chega antes: a gravação da IA toma a linha e o turno.
        agora_ = datetime.now(timezone.utc)
        assert await repo.gravar_mensagem(lead=lead, autor="automacao", tipo="texto", texto="Olá!", texto_extraido=None,
                                          url_midia=None, enviada_em=agora_, id_externo=eco)
        assert not await repo.mensagem_e_da_ia(esc, eco)
        turno = await repo.abrir_turno(lead=lead, modo="producao", etapa_antes=None)
        id_ia = await repo.gravar_mensagem(lead=lead, autor="ia", tipo="texto", texto="Olá!", texto_extraido=None, url_midia=None,
                                           enviada_em=agora_, id_externo=eco, id_turno=turno, situacao_envio="enviada")
        assert id_ia is not None
        linha = await pool.fetchrow("select autor, id_turno, situacao_envio from agentesia_mensagens where id_externo = $1", eco)
        assert (linha["autor"], str(linha["id_turno"]), linha["situacao_envio"]) == ("ia", turno, "enviada")
        assert await repo.mensagem_e_da_ia(esc, eco)
        # A mesma gravação de novo (já é da IA): não duplica nem muda nada.
        assert await repo.gravar_mensagem(lead=lead, autor="ia", tipo="texto", texto="Olá!", texto_extraido=None, url_midia=None,
                                          enviada_em=agora_, id_externo=eco, id_turno=turno) is None
        # Mensagem de lead nunca é tomada pela IA.
        await repo.gravar_mensagem(lead=lead, autor="lead", tipo="texto", texto="oi", texto_extraido=None, url_midia=None,
                                   enviada_em=agora_, id_externo=do_lead)
        assert await repo.gravar_mensagem(lead=lead, autor="ia", tipo="texto", texto="x", texto_extraido=None, url_midia=None,
                                          enviada_em=agora_, id_externo=do_lead) is None
        assert await pool.fetchval("select autor from agentesia_mensagens where id_externo = $1", do_lead) == "lead"
        # [2] lead_ja_escreveu ignora a própria mensagem que acabou de chegar.
        id_lead_msg = await pool.fetchval("select id from agentesia_mensagens where id_externo = $1", do_lead)
        assert not await repo.lead_ja_escreveu(id_lead, antes_de=str(id_lead_msg))
        assert await repo.lead_ja_escreveu(id_lead)
        # [5] Canal com tipo; [10] token: só a coluna antiga também vale (mesma fonte do Executor e do follow-up).
        assert (await repo.canal(canal)).tipo == "oficial"
        assert await repo.token_helena(esc) == "token-coluna" == await token_helena(pool, esc)
        esc2, _c, _l = await _escritorio_pg(pool, integracao=True, coluna=False, token="token-integracao")
        assert await repo.token_helena(esc2) == "token-integracao"
        esc3 = await pool.fetchval("insert into agentesia_escritorios (nome) values ('Sem token') returning id")
        assert await repo.token_helena(str(esc3)) is None
        assert await token_helena(pool, "nao-e-uuid") is None
    finally:
        await repo.fechar()


class HelenaStatus:
    def __init__(self, status):
        self.status, self.chamadas = status, []

    def __call__(self, pedido: httpx.Request) -> httpx.Response:
        self.chamadas.append((pedido.method, pedido.url.path))
        if pedido.url.path.startswith("/chat/v1/message/") and pedido.url.path.endswith("/status"):
            id_msg = pedido.url.path.split("/")[4]
            if id_msg not in self.status:
                return httpx.Response(404)
            return httpx.Response(200, json=self.status[id_msg])
        if pedido.url.path.endswith("/note"):
            return httpx.Response(200, json={})
        return httpx.Response(404)


@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_postgres_conferir_entrega_marca_falha_evento_e_nota():
    from app.acoes import Executor
    from app.banco.postgres import RepositorioPostgres
    from app.canal.helena_conta import HelenaConta

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        await pool.execute("update agentesia_acoes set situacao = 'cancelada' where situacao in ('pendente', 'executando')")
        # Só a coluna antiga: o Executor também acha o token (antes lia só a integração e dava ErroDeCadastro).
        esc, _canal, id_lead = await _escritorio_pg(pool, integracao=False, coluna=True)
        lead = await repo.lead(id_lead)
        turno = await repo.abrir_turno(lead=lead, modo="producao", etapa_antes=None)
        agora_ = datetime.now(timezone.utc)
        for id_ext, texto in (("m-ok", "Oi!"), ("m-falha", None), ("m-fila", "Tudo bem?")):
            await repo.gravar_mensagem(lead=lead, autor="ia", tipo="texto" if texto else "video", texto=texto,
                                       texto_extraido=None if texto else "[mídia enviada: audio]",
                                       url_midia=None if texto else "https://midia.invalid/a.mp3", enviada_em=agora_,
                                       id_externo=id_ext, id_turno=turno, situacao_envio="enviada")
        await repo.enfileirar_acoes(id_escritorio=esc, id_lead=id_lead, id_turno=turno, acoes=[{
            "tipo": "conferir_entrega", "chave_unica": f"{turno}:entrega", "atraso_s": 60,
            "dados": {"ids": ["m-ok", "m-falha", "m-fila", "m-sumiu"], "id_turno": turno}}])
        acao = await pool.fetchrow("select situacao, proxima_em > now() + interval '30 seconds' as depois "
                                   "from agentesia_acoes where chave_unica = $1", f"{turno}:entrega")
        assert acao["situacao"] == "pendente" and acao["depois"]               # roda 1 minuto depois do turno
        await pool.execute("update agentesia_acoes set proxima_em = now() where chave_unica = $1", f"{turno}:entrega")

        helena = HelenaStatus({"m-ok": {"status": "DELIVERED"}, "m-falha": {"status": "FAILED", "failureReason": "arquivo não encontrado"},
                               "m-fila": {"status": "QUEUED"}})
        executor = Executor(pool, "https://api.helena.run", helena_por_token=lambda token, url: HelenaConta(
            token, url, httpx.AsyncClient(transport=httpx.MockTransport(helena))))
        await executor.rodar_uma_vez()
        assert await pool.fetchval("select situacao from agentesia_acoes where chave_unica = $1", f"{turno}:entrega") == "feita"
        situacoes = dict(await pool.fetch("select id_externo, situacao_envio from agentesia_mensagens where id_lead = $1::uuid", id_lead))
        assert situacoes == {"m-ok": "enviada", "m-falha": "falhou", "m-fila": "enviada"}
        assert "arquivo não encontrado" in await pool.fetchval("select erro from agentesia_mensagens where id_externo = 'm-falha' and id_lead = $1::uuid", id_lead)
        evento = await pool.fetchrow("select gravidade, responsavel from agentesia_eventos where id_lead = $1::uuid and tipo = 'envio_falhou'", id_lead)
        assert (evento["gravidade"], evento["responsavel"]) == ("erro", "provedor")
        nota = await pool.fetchval("select dados->>'texto' from agentesia_acoes where id_lead = $1::uuid and tipo = 'nota'", id_lead)
        assert nota.startswith("📭 Uma mensagem da IA não chegou ao lead") and "Helena" not in nota
        reconferir = await pool.fetchrow("select dados from agentesia_acoes where chave_unica = $1", f"{turno}:entrega:2")
        dados = reconferir["dados"] if isinstance(reconferir["dados"], dict) else json.loads(reconferir["dados"])
        assert dados["ids"] == ["m-fila"] and dados["reconferencia"] is True
    finally:
        await pool.execute("update agentesia_acoes set situacao = 'cancelada' where situacao in ('pendente', 'executando')")
        await repo.fechar()
