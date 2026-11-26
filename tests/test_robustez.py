"""Robustez do motor: webhook que falha no meio, turno que quebra, IA lenta ou fora do ar, envio pela metade,
etapa que muda durante o turno, mídia pendente, desligamento e saúde. Tudo com fakes (nada real)."""

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app import pipeline as modulo_pipeline
from app.canal.helena import ClienteHelena, ErroHelena
from app.canal.helena_conta import EVENTOS_DO_ATENDIMENTO, ErroHelenaApi, HelenaConta
from app.cerebro import turno as cerebro
from app.modelo import ErroModelo, ModeloFalso, calcular_custo
from tests.test_pipeline import CONTA, HelenaFalsa, SIMPLES, montar, webhook
from tests.test_turno import extrai, fala


class Falha(ConnectionError):
    pass


def falhar_uma_vez(repo, metodo):
    """O método do repositório levanta ConnectionError na primeira chamada (pool do banco caiu)."""
    original = getattr(repo, metodo)
    estado = {"falhou": False}

    async def quebrado(*args, **kwargs):
        if not estado["falhou"]:
            estado["falhou"] = True
            raise Falha("pool caiu")
        return await original(*args, **kwargs)

    setattr(repo, metodo, quebrado)


def lead_de(repo):
    return next(iter(repo.leads.values()))


def notas(repo, tipo=None):
    return [a for a in repo.acoes if a["tipo"] == "nota" and (tipo is None or f":problema:{tipo}:" in a["chave_unica"])]


# ============================================================================ [0]/[17] recepção que falha no meio
async def test_falha_ao_gravar_desfaz_a_marca_e_o_reenvio_responde():
    atendimento, repo, helena = montar(SIMPLES)
    falhar_uma_vez(repo, "gravar_mensagem")
    corpo = webhook("oi, sofri um acidente")
    with pytest.raises(Falha):
        await atendimento.receber(corpo)                  # vira HTTP 500: a Helena reenvia
    assert repo.recebidos == set()                        # a marca de recebido foi desfeita
    assert (await atendimento.receber(corpo))["feito"] == "agendado"
    await atendimento.aguardar_esperas()
    assert helena.enviadas == ["Oi! Me conta o que aconteceu?"]


async def test_falha_depois_de_gravar_o_reenvio_nao_cai_em_repetido():
    atendimento, repo, helena = montar(SIMPLES)
    falhar_uma_vez(repo, "cancelar_followups")
    corpo = webhook("oi, sofri um acidente")
    with pytest.raises(Falha):
        await atendimento.receber(corpo)
    lead = lead_de(repo)
    assert [m.autor for m in repo.mensagens[lead.id]] == ["lead"]       # a mensagem ficou gravada
    assert lead.id in repo.esperas                                       # e com o prazo de resposta no banco
    resultado = await atendimento.receber(corpo)                          # reenvio da Helena
    assert resultado["feito"] == "agendado"
    await atendimento.aguardar_esperas()
    assert helena.enviadas == ["Oi! Me conta o que aconteceu?"]
    assert [m.autor for m in repo.mensagens[lead.id]] == ["lead", "ia"]   # sem mensagem dobrada
    assert (await atendimento.receber(corpo))["motivo"] == "repetido"     # já respondida: repetido de verdade


# ============================================================================ [5] MESSAGE_UPDATED com FAILED
async def test_status_failed_da_helena_marca_falhou_e_avisa_uma_vez():
    assert "MESSAGE_UPDATED" in EVENTOS_DO_ATENDIMENTO
    atendimento, repo, helena = montar(SIMPLES)
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    lead = lead_de(repo)
    id_ia = helena.ids[0]
    status = {"eventType": "MESSAGE_UPDATED", "content": {"id": id_ia, "companyId": CONTA, "status": "failed",
                                                          "failureReason": "arquivo grande demais"}}
    assert (await atendimento.receber(status))["motivo"] == "envio_falhou"
    mensagem = next(m for m in repo.mensagens[lead.id] if m.id_externo == id_ia)
    assert repo.situacoes[mensagem.id][0] == "falhou"
    assert any(e["tipo"] == "envio_falhou" and e["responsavel"] == "provedor" for e in repo.eventos)
    assert len(notas(repo, "envio_falhou")) == 1
    assert (await atendimento.receber(status))["motivo"] == "status_ja_registrado"     # a Helena repete eventos
    entregue = {"eventType": "MESSAGE_UPDATED", "content": {"id": id_ia, "companyId": CONTA, "status": "READ"}}
    assert (await atendimento.receber(entregue))["feito"] == "ignorado"


# ============================================================================ [1] mensagem nova durante o turno
async def test_mensagem_nova_durante_o_turno_espera_o_prazo_dela():
    async def extrator_lento(_s, _c):
        await asyncio.sleep(0.4)
        return extrai()

    atendimento, repo, helena = montar({"extrator": extrator_lento, "etapa": fala("Entendi, me conta mais.")})
    repo.escritorios["esc-1"].config["espera_teste_s"] = 0.3
    momentos = []
    enviar = helena.enviar

    async def enviar_com_hora(**kw):
        momentos.append(time.monotonic())
        return await enviar(**kw)

    helena.enviar = enviar_com_hora
    await atendimento.receber(webhook("oi"))
    await asyncio.sleep(0.45)                             # o 1º turno está no extrator
    segunda = time.monotonic()
    await atendimento.receber(webhook("caí da moto"))
    await atendimento.aguardar_esperas()
    etapas = [p for p in atendimento.modelo.pedidos if p["papel"] == "etapa"]
    assert len(etapas) <= 2                               # no máximo uma chamada a mais
    assert helena.enviadas == ["Entendi, me conta mais."]
    assert momentos[0] >= segunda + 0.3 - 0.05            # respondeu depois do prazo da 2ª mensagem
    situacoes = sorted(t["situacao"] for t in repo.turnos.values())
    assert situacoes == ["descartado", "respondido"]


# ============================================================================ [3]/[19] erro inesperado no turno
async def test_erro_inesperado_fecha_o_turno_avisa_e_nao_vira_laco():
    def extrator_quebrado(_s, _c):
        raise KeyError("campo")

    atendimento, repo, helena = montar({"extrator": extrator_quebrado, "etapa": fala("nunca")})
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    lead = lead_de(repo)
    turnos = list(repo.turnos.values())
    assert [(t["situacao"], t["motivo"]) for t in turnos] == [("erro", "erro_interno:KeyError")]
    assert not await repo.mensagens_pendentes(lead.id)    # saiu da fila
    assert any(e["tipo"] == "erro_no_turno" and e["gravidade"] == "critico" for e in repo.eventos)
    assert len(notas(repo, "ia_nao_respondeu")) == 1
    assert await atendimento.retomar_pendentes() == 0      # nada para refazer a cada minuto
    await atendimento.aguardar_esperas()
    assert len(repo.turnos) == 1 and helena.enviadas == []


async def test_chamadas_pagas_antes_do_erro_sao_gravadas(monkeypatch):
    def etapa_quebrada(_s, _c):
        raise ValueError("parse")

    atendimento, repo, _ = montar({"extrator": extrai(), "etapa": etapa_quebrada})
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    assert [c["papel"] for c in repo.chamadas] == ["extrator"]          # o extrator foi pago e ficou registrado


# ============================================================================ [18] IA pendurada
async def test_ia_pendurada_vira_falha_do_modelo_com_nota(monkeypatch):
    async def extrator_pendurado(_s, _c):
        await asyncio.sleep(5)
        return extrai()

    atendimento, repo, helena = montar({"extrator": extrator_pendurado, "etapa": fala("x")})
    monkeypatch.setattr(atendimento, "_teto_do_turno", lambda: 0.2)
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    turno = next(iter(repo.turnos.values()))
    assert (turno["situacao"], turno["motivo"]) == ("erro", "turno:sem_conexao")
    assert len(notas(repo, "ia_nao_respondeu")) == 1 and helena.enviadas == []


# ============================================================================ [21] IA fora do ar por pouco tempo
async def test_falha_passageira_da_ia_tenta_de_novo_antes_de_desistir():
    tentativas = {"n": 0}

    def etapa_instavel(_s, _c):
        tentativas["n"] += 1
        if tentativas["n"] == 1:
            raise ErroModelo("provedor_fora_do_ar", "503")
        return fala("Oi! Me conta o que aconteceu?")

    atendimento, repo, helena = montar({"extrator": extrai(), "etapa": etapa_instavel})
    atendimento.esperas_nova_tentativa_ia = (0.05, 0.05)
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    assert helena.enviadas == ["Oi! Me conta o que aconteceu?"]
    assert notas(repo, "ia_nao_respondeu") == []          # passou sozinho: sem nota para a equipe
    assert sorted(t["situacao"] for t in repo.turnos.values()) == ["erro", "respondido"]


async def test_falha_passageira_repetida_desiste_com_nota():
    def etapa_fora(_s, _c):
        raise ErroModelo("provedor_fora_do_ar", "503")

    atendimento, repo, helena = montar({"extrator": extrai(), "etapa": etapa_fora})
    atendimento.esperas_nova_tentativa_ia = (0.02, 0.02)
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    assert len(repo.turnos) == 3 and helena.enviadas == []
    assert len(notas(repo, "ia_nao_respondeu")) == 1
    assert not await repo.mensagens_pendentes(lead_de(repo).id)


# ============================================================================ [12] etapa muda durante o turno
def saida_fixa(mensagens, etapa_depois=None, ao_chamar=None):
    async def processar(_modelo, entrada):
        if ao_chamar:
            ao_chamar()
        saida = cerebro.Saida(etapa_antes=entrada.etapa, etapa_depois=etapa_depois or entrada.etapa,
                              fatos_depois=dict(entrada.fatos))
        saida.mensagens = [{"tipo": "texto", "texto": t, "espera_s": 0} for t in mensagens]
        return saida
    return processar


async def test_etapa_mudou_durante_o_turno_nao_envia_a_resposta_velha(monkeypatch):
    atendimento, repo, helena = montar(SIMPLES)
    chamadas = {"n": 0}

    def contrato_moveu_o_lead():
        chamadas["n"] += 1
        if chamadas["n"] == 1:                            # o executor moveu o lead enquanto a IA pensava
            lead_de(repo).id_etapa = "e-closer"

    monkeypatch.setattr(cerebro, "processar", saida_fixa(["Vou gerar seu contrato agora"], ao_chamar=contrato_moveu_o_lead))
    await atendimento.receber(webhook("ok"))
    await atendimento.aguardar_esperas()
    turnos = list(repo.turnos.values())
    assert (turnos[0]["situacao"], turnos[0]["motivo"]) == ("descartado", "etapa_mudou")
    assert turnos[1]["etapa_antes"] == "closer"           # o turno refeito já é do agente da etapa nova
    assert helena.enviadas == ["Vou gerar seu contrato agora"] and chamadas["n"] == 2


# ============================================================================ [13] troca de etapa sem entrega
async def test_troca_de_etapa_sem_nada_entregue_fica_na_etapa_antiga(monkeypatch):
    atendimento, repo, helena = montar(SIMPLES, helena=HelenaFalsa(falhar=True))
    monkeypatch.setattr(cerebro, "processar", saida_fixa(["Vou te passar para o time"], etapa_depois="closer"))
    await atendimento.receber(webhook("quero seguir"))
    await atendimento.aguardar_esperas()
    lead = lead_de(repo)
    assert lead.id_etapa == "e-sdr"
    assert any(e["tipo"] == "troca_sem_entrega" for e in repo.eventos)
    assert not any(e["tipo"] == "etapa_trocada" for e in repo.eventos)


async def test_troca_de_etapa_entregue_e_gravada_antes_do_envio(monkeypatch):
    atendimento, repo, helena = montar(SIMPLES)
    vista = {}
    enviar = helena.enviar

    async def enviar_e_olhar(**kw):
        vista["etapa_no_envio"] = lead_de(repo).id_etapa
        return await enviar(**kw)

    helena.enviar = enviar_e_olhar
    monkeypatch.setattr(cerebro, "processar", saida_fixa(["Vou te passar para o time"], etapa_depois="closer"))
    await atendimento.receber(webhook("quero seguir"))
    await atendimento.aguardar_esperas()
    assert vista["etapa_no_envio"] == "e-closer" and lead_de(repo).id_etapa == "e-closer"
    assert any(e["tipo"] == "etapa_trocada" for e in repo.eventos)


# ============================================================================ [8]/[9] envio pela metade
async def test_erro_inesperado_numa_parte_nao_para_as_outras_e_marca_nao_entregue(monkeypatch):
    atendimento, repo, helena = montar(SIMPLES)
    enviar = helena.enviar

    async def quebra_a_primeira(**kw):
        if kw.get("texto") == "parte 1":
            raise AttributeError("corpo inesperado")
        return await enviar(**kw)

    helena.enviar = quebra_a_primeira
    monkeypatch.setattr(cerebro, "processar", saida_fixa(["parte 1", "parte 2"]))
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    assert helena.enviadas == ["parte 2"]
    lead = lead_de(repo)
    historico = await repo.historico(lead.id)
    textos = [m.para_a_ia() for m in historico if m.autor == "ia"]
    assert textos == ["[NÃO ENTREGUE ao lead] parte 1", "parte 2"]
    assert any(e["tipo"] == "envio_falhou" and "AttributeError" in e["descricao"] for e in repo.eventos)


# ============================================================================ [14] lead sem agente nem etapa
async def test_lead_criado_sem_agente_e_reparado_no_turno():
    atendimento, repo, helena = montar(SIMPLES)
    lead = await repo.achar_ou_criar_lead(escritorio=repo.escritorios["esc-1"], canal=repo.canais["canal-1"],
                                          agente=None, telefone="5511988887777", id_sessao="sessao-1")
    assert (lead.id_agente, lead.id_etapa) == (None, None)
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    lead = lead_de(repo)
    assert (lead.id_agente, lead.id_etapa) == ("ag-1", "e-sdr")
    assert helena.enviadas == ["Oi! Me conta o que aconteceu?"]
    assert any(e["tipo"] == "etapa_reparada" for e in repo.eventos)


# ============================================================================ [24] passo depois do envio que falha
async def test_followup_que_falha_nao_derruba_o_resto_do_turno():
    atendimento, repo, helena = montar(SIMPLES)

    async def agendar_quebrado(*_a, **_k):
        raise RuntimeError("config de follow-up inválida")

    repo.agendar_followup = agendar_quebrado
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    turno = next(iter(repo.turnos.values()))
    assert turno["situacao"] == "respondido" and helena.enviadas
    assert any(e["tipo"] == "pos_envio_falhou:followup" for e in repo.eventos)


# ============================================================================ [2] prazo do banco manda
async def test_prazo_no_futuro_no_banco_adia_o_turno():
    atendimento, repo, helena = montar(SIMPLES)
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    lead = lead_de(repo)
    await repo.gravar_mensagem(lead=lead, autor="lead", tipo="texto", texto="mais uma", texto_extraido=None,
                               url_midia=None, enviada_em=datetime.now(timezone.utc), id_externo="outro-servidor")
    await repo.marcar_resposta(lead.id, datetime.now(timezone.utc) + timedelta(seconds=1.5))   # outro servidor adiou
    assert await atendimento.processar(lead.id) is None
    assert len(repo.turnos) == 1                          # não rodou turno antes do prazo
    assert lead.id in atendimento._prazos
    await atendimento.aguardar_esperas()
    assert len(repo.turnos) == 2 and len(helena.enviadas) == 2


# ============================================================================ [15] mídia pendente depois de reinício
async def test_midia_pendente_sem_leitura_viva_e_lida_no_turno(monkeypatch):
    atendimento, repo, helena = montar(SIMPLES)
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    lead = lead_de(repo)
    id_msg = await repo.gravar_mensagem(lead=lead, autor="lead", tipo="documento", texto=None,
                                        texto_extraido="[O lead enviou um documento. Você não consegue abrir arquivos.]",
                                        url_midia="https://arquivos.invalid/laudo.pdf",
                                        enviada_em=datetime.now(timezone.utc), id_externo="doc-1")
    await repo.marcar_midia_pendente(id_msg)
    mensagem = next(m for m in repo.mensagens[lead.id] if m.id == id_msg)
    mensagem.midia_pendente_desde -= timedelta(seconds=90)    # o processo que lia caiu há 90 s
    lidas = []

    async def ler(id_mensagem, lead_, agente, evento, quem="o lead"):
        lidas.append((id_mensagem, evento.url_midia))
        await repo.atualizar_texto_extraido(id_mensagem, "[Laudo: CID S82, sequela no joelho]")

    monkeypatch.setattr(atendimento, "_ler_midia", ler)
    await atendimento.processar(lead.id)
    assert lidas == [(id_msg, "https://arquivos.invalid/laudo.pdf")]
    assert "Laudo: CID S82" in atendimento.modelo.pedidos[-1]["conteudo"] or \
        any("Laudo: CID S82" in p["conteudo"] for p in atendimento.modelo.pedidos)


async def test_midia_pendente_recente_de_outro_servidor_adia():
    atendimento, repo, helena = montar(SIMPLES)
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    lead = lead_de(repo)
    id_msg = await repo.gravar_mensagem(lead=lead, autor="lead", tipo="imagem", texto=None, texto_extraido="[imagem]",
                                        url_midia="https://arquivos.invalid/foto.jpg",
                                        enviada_em=datetime.now(timezone.utc), id_externo="img-1")
    await repo.marcar_midia_pendente(id_msg)
    assert await atendimento.processar(lead.id) is None
    assert len(repo.turnos) == 1 and lead.id in atendimento._prazos      # esperou o outro servidor ler
    for tarefa in atendimento._esperas.values():
        tarefa.cancel()


async def test_falha_na_leitura_de_midia_gera_evento_para_a_lawchat():
    atendimento, repo, _ = montar(SIMPLES)
    atendimento.visao = object()
    lead = await repo.achar_ou_criar_lead(escritorio=repo.escritorios["esc-1"], canal=repo.canais["canal-1"],
                                          agente=repo.agentes["canal-1"], telefone="5511988887777", id_sessao="s")

    async def quebra(**_k):
        raise RuntimeError("bug")

    original = modulo_pipeline.midias.tratar_midia
    modulo_pipeline.midias.tratar_midia = quebra
    try:
        from app.canal.helena import Evento
        id_msg = await repo.gravar_mensagem(lead=lead, autor="lead", tipo="imagem", texto=None, texto_extraido="[img]",
                                            url_midia="https://x.invalid/a.jpg", enviada_em=datetime.now(timezone.utc),
                                            id_externo="i")
        await repo.marcar_midia_pendente(id_msg)
        await atendimento._ler_midia(id_msg, lead, repo.agentes["canal-1"],
                                     Evento("lead", tipo="imagem", url_midia="https://x.invalid/a.jpg"))
    finally:
        modulo_pipeline.midias.tratar_midia = original
    evento = next(e for e in repo.eventos if e["tipo"] == "leitura_de_midia_falhou")
    assert (evento["gravidade"], evento["responsavel"]) == ("erro", "lawchat")
    assert next(m for m in repo.mensagens[lead.id] if m.id == id_msg).midia_pendente_desde is None


# ============================================================================ [20] turno interrompido e desligamento
async def test_turno_processando_antigo_vira_erro_com_evento_e_nota():
    atendimento, repo, _ = montar(SIMPLES)
    lead = await repo.achar_ou_criar_lead(escritorio=repo.escritorios["esc-1"], canal=repo.canais["canal-1"],
                                          agente=repo.agentes["canal-1"], telefone="5511988887777", id_sessao="s")
    id_turno = await repo.abrir_turno(lead=lead, modo="teste", etapa_antes="sdr")
    repo.turnos[id_turno]["iniciado_em"] -= timedelta(minutes=30)
    await atendimento.retomar_pendentes()
    assert (repo.turnos[id_turno]["situacao"], repo.turnos[id_turno]["motivo"]) == ("erro", "turno_interrompido")
    assert any(e["tipo"] == "turno_interrompido" for e in repo.eventos)
    assert len(notas(repo, "envio_falhou")) == 0            # só em Erros: a nota no chat assustava
    await atendimento.retomar_pendentes()                 # já fechado: não avisa de novo
    assert sum(e["tipo"] == "turno_interrompido" for e in repo.eventos) == 1


async def test_encerrar_espera_o_turno_e_corta_o_que_passa_do_teto():
    atendimento, _, _ = montar(SIMPLES)
    rapida = asyncio.create_task(asyncio.sleep(0.05))
    lenta = asyncio.create_task(asyncio.sleep(10))
    atendimento._esperas.update({"a": rapida, "b": lenta})
    await atendimento.encerrar(teto_s=0.3)
    assert rapida.done() and not rapida.cancelled() and lenta.cancelled()


# ============================================================================ [6]/[7]/[8] cliente da Helena
async def test_429_espera_ao_menos_a_pausa_padrao_e_corpo_estranho_nao_quebra():
    respostas = [httpx.Response(429, headers={"Retry-After": "1"}), httpx.Response(200, json=["inesperado"])]
    cliente = ClienteHelena("https://helena.invalid",
                            httpx.AsyncClient(transport=httpx.MockTransport(lambda _p: respostas.pop(0))))
    esperas = []

    async def pausa(segundos):
        esperas.append(segundos)

    cliente._pausa = pausa
    assert await cliente.enviar(token="t", id_sessao="s", id_canal=None, texto="oi") is None
    assert esperas and esperas[0] >= 5


async def test_timeout_de_leitura_num_post_e_talvez_enviado_e_nao_repete():
    pedidos = []

    def tratar(pedido):
        pedidos.append(pedido.method)
        raise httpx.ReadTimeout("demorou", request=pedido)

    conta = HelenaConta("t", "https://helena.invalid", http=httpx.AsyncClient(transport=httpx.MockTransport(tratar)))
    with pytest.raises(ErroHelenaApi) as erro:
        await conta.enviar_no_atendimento("s", texto="oi")
    assert erro.value.motivo == "talvez_enviado" and pedidos == ["POST"]
    with pytest.raises(ErroHelenaApi) as erro:
        await conta.contato_da_sessao("s")
    assert erro.value.motivo == "sem_conexao"


# ============================================================================ [27] custo
def test_modelo_sem_preco_avisa_no_log_e_transcricao_tem_custo(caplog):
    from app.midia.openai_visao import custo_estimado_do_audio

    with caplog.at_level("WARNING", logger="agentesia.modelo"):
        assert calcular_custo("modelo-sem-preco-x", 1000, 1000, 0) == 0.0
        calcular_custo("modelo-sem-preco-x", 1000, 1000, 0)
    assert sum("modelo-sem-preco-x" in r.message for r in caplog.records) == 1     # uma vez por modelo
    assert calcular_custo("gpt-4o-mini-transcribe", 1000, 100, 0) > 0
    assert custo_estimado_do_audio(240_000) > 0         # ~2 min de áudio


# ============================================================================ [25] saúde
async def test_saude_devolve_503_quando_o_banco_nao_responde():
    from types import SimpleNamespace

    from app import main

    class PoolFora:
        async def fetchval(self, *_a):
            raise ConnectionError("fora")

    class PoolOk:
        async def fetchval(self, sql, *_a):
            return 1 if sql == "select 1" else 0

    tarefa = asyncio.create_task(asyncio.sleep(5))
    estado_antigo = dict(main.app.state._state)
    try:
        main.app.state.cfg = SimpleNamespace(modelo_padrao="gpt-4.1")
        main.app.state.tarefas = {"executor": tarefa}
        main.app.state.visao = True
        transporte = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transporte, base_url="http://teste") as cliente:
            main.app.state.atendimento = SimpleNamespace(repo=SimpleNamespace(_pool=PoolOk()))
            ok = await cliente.get("/saude")
            assert ok.status_code == 200 and ok.json()["banco"] is True and ok.json()["tarefas"] == {"executor": True}
            main.app.state.atendimento = SimpleNamespace(repo=SimpleNamespace(_pool=PoolFora()))
            fora = await cliente.get("/saude")
            assert fora.status_code == 503 and fora.json()["banco"] is False
    finally:
        tarefa.cancel()
        main.app.state._state.clear()
        main.app.state._state.update(estado_antigo)


# ============================================================================ [7] executor não repete envio sem confirmação
def test_acoes_que_mandam_mensagem_nao_repetem_sem_confirmacao():
    from app.acoes import ENVIAM_MENSAGEM

    assert {"enviar_mensagem", "reenviar_link", "notificar"} <= ENVIAM_MENSAGEM
    assert "nota" not in ENVIAM_MENSAGEM and "etiquetar" not in ENVIAM_MENSAGEM
