"""Pipeline do webhook ao envio, com banco em memória, IA de mentira e Helena de mentira."""

import asyncio
import itertools
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.banco.memoria import RepositorioMemoria
from app.banco.tipos import Agente, Canal, Escritorio, Etapa
from app.canal.helena import ErroHelena, ler_webhook, normalizar_telefone
from app.config import Configuracao
from app.modelo import ModeloFalso
from app.pipeline import Atendimento
from tests.test_turno import extrai, fala

CONTA, CANAL, LEAD = "conta-1", "5511999990000", "5511988887777"
_seq = itertools.count(1)


def webhook(texto="oi", *, de=LEAD, para=CANAL, direcao="FROM_HUB", origem="GATEWAY",
            evento="MESSAGE_RECEIVED", tipo="TEXT", id_msg=None, quando=None, **detalhes):
    return {
        "eventType": evento,
        "content": {
            "id": id_msg or f"wamid-{uuid.uuid4()}", "companyId": CONTA, "sessionId": "sessao-1",
            "type": tipo, "text": texto, "direction": direcao, "origin": origem,
            "timestamp": (quando or datetime.now(timezone.utc)).isoformat(),
            "details": {"from": "+" + de, "to": "+" + para, **detalhes},
        },
    }


class HelenaFalsa:
    def __init__(self, falhar=False):
        self.enviadas, self.falhar, self.ids = [], falhar, []

    async def enviar(self, *, token, id_sessao, id_canal, texto=None, url_arquivo=None):
        if self.falhar:
            raise ErroHelena("HTTP 500")
        self.enviadas.append(texto or url_arquivo)
        self.ids.append(f"env-{uuid.uuid4()}")
        return self.ids[-1]


def montar(respostas, *, modo="teste", situacao="ativo", numeros_teste=(LEAD,), helena=None, max_reprocessos=2):
    repo = RepositorioMemoria()
    escritorio = Escritorio(id="esc-1", nome="Escritório Teste", id_segredo_helena="seg-1",
                            config={"numeros_teste": list(numeros_teste), "espera_teste_s": 0})
    canal = Canal(id="canal-1", id_escritorio="esc-1", numero_normalizado=CANAL, id_canal_helena="ch-1")
    agente = Agente(id="ag-1", id_escritorio="esc-1", id_canal="canal-1", nome="Júlia", situacao=situacao, modo=modo,
                    etapas=[Etapa("e-sdr", "sdr", principal=True), Etapa("e-closer", "closer"),
                            Etapa("e-desq", "desqualificado")])
    repo.cadastrar(escritorio, canal, agente, id_conta=CONTA)
    repo.segredos["seg-1"] = "token-de-teste"
    config = Configuracao(banco_url=None, helena_url="http://helena.invalid", modelo_padrao="falso", modelo_falso=True,
                          espera_minima_s=0, espera_maxima_s=0, espera_padrao_s=0, segundos_por_letra=0,
                          max_reprocessos=max_reprocessos)
    helena = helena or HelenaFalsa()
    return Atendimento(repo, ModeloFalso(respostas), config, helena, digitar=False), repo, helena


SIMPLES = {"extrator": extrai(), "etapa": fala("Oi! Me conta o que aconteceu?")}


async def test_lead_fala_e_a_ia_responde():
    atendimento, repo, helena = montar(SIMPLES)
    resultado = await atendimento.receber(webhook("oi, boa tarde"))
    assert resultado["feito"] == "agendado"
    await atendimento.aguardar_esperas()
    assert helena.enviadas == ["Oi! Me conta o que aconteceu?"]
    lead = next(iter(repo.leads.values()))
    assert [(m.autor, m.texto) for m in repo.mensagens[lead.id]] == [
        ("lead", "oi, boa tarde"), ("ia", "Oi! Me conta o que aconteceu?")]
    turno = next(iter(repo.turnos.values()))
    assert turno["situacao"] == "respondido" and turno["contexto"]["etapa"]["sistema"]
    assert len(repo.chamadas) == 2


async def test_webhook_repetido_e_descartado():
    atendimento, repo, helena = montar(SIMPLES)
    corpo = webhook("oi")
    await atendimento.receber(corpo)
    assert (await atendimento.receber(corpo))["motivo"] == "repetido"
    await atendimento.aguardar_esperas()
    assert len(helena.enviadas) == 1


async def test_mensagens_seguidas_viram_um_turno_na_ordem_do_whatsapp():
    atendimento, repo, helena = montar(SIMPLES)
    base = datetime.now(timezone.utc)
    await atendimento.receber(webhook("e bati a perna", quando=base + timedelta(seconds=2)))   # chegou antes
    await atendimento.receber(webhook("caí da moto", quando=base))                             # mas é mais antiga
    await atendimento.aguardar_esperas()
    assert len(helena.enviadas) == 1 and len(repo.turnos) == 1
    assert "[lead] caí da moto\n[lead] e bati a perna" in atendimento.modelo.pedidos[0]["conteudo"]


async def test_eco_da_ia_e_ignorado_e_outra_integracao_e_gravada():
    atendimento, repo, helena = montar(SIMPLES)
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    eco = webhook("Oi! Me conta o que aconteceu?", de=CANAL, para=LEAD, direcao="TO_HUB", origem="API",
                  evento="MESSAGE_SENT", id_msg=helena.ids[0])
    assert (await atendimento.receber(eco))["motivo"] == "eco_da_ia"
    outra = webhook("Lembrete da agenda", de=CANAL, para=LEAD, direcao="TO_HUB", origem="API", evento="MESSAGE_SENT")
    assert (await atendimento.receber(outra))["autor"] == "automacao"
    lead = next(iter(repo.leads.values()))
    assert lead.estado == "ativo"                                   # outra integração não pausa a IA


async def test_atendente_fala_e_a_ia_pausa_e_depois_volta():
    atendimento, repo, helena = montar(SIMPLES)
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    humano = webhook("Olá, aqui é a Paula", de=CANAL, para=LEAD, direcao="TO_HUB", origem="DEFAULT", evento="MESSAGE_SENT")
    assert (await atendimento.receber(humano))["feito"] == "pausado"
    lead = next(iter(repo.leads.values()))
    assert lead.estado == "pausado" and lead.pausado_ate > datetime.now(timezone.utc)

    await atendimento.receber(webhook("oi Paula"))
    await atendimento.aguardar_esperas()
    assert len(helena.enviadas) == 1                                # a IA ficou calada
    assert [t["situacao"] for t in repo.turnos.values()][-1] == "silencio"

    lead.pausado_ate = datetime.now(timezone.utc) - timedelta(seconds=1)   # a pausa venceu
    await atendimento.receber(webhook("ainda estão aí?"))
    await atendimento.aguardar_esperas()
    assert len(helena.enviadas) == 2 and lead.estado == "ativo"
    # A IA volta sabendo o que a atendente disse, e só com a mensagem nova como novidade.
    conteudo = atendimento.modelo.pedidos[-1]["conteudo"]
    assert "[atendente] Olá, aqui é a Paula" in conteudo
    assert conteudo.rstrip().endswith("[lead] ainda estão aí?")


async def test_modo_teste_so_responde_aos_numeros_de_teste():
    atendimento, repo, helena = montar(SIMPLES, numeros_teste=("5511900001111",))
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    assert helena.enviadas == []
    assert next(iter(repo.turnos.values()))["motivo"] == "modo_teste"
    lead = next(iter(repo.leads.values()))
    assert repo.mensagens[lead.id][0].texto == "oi"                 # a mensagem fica gravada mesmo assim


@pytest.mark.parametrize("ajuste, motivo", [
    ({"situacao": "pausado"}, "agente_pausado"),
])
async def test_agente_pausado_nao_responde(ajuste, motivo):
    atendimento, repo, helena = montar(SIMPLES, **ajuste)
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    assert helena.enviadas == [] and next(iter(repo.turnos.values()))["motivo"] == motivo


async def test_interruptor_do_escritorio():
    atendimento, repo, helena = montar(SIMPLES)
    repo.escritorios["esc-1"].ia_desligada = True
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    assert helena.enviadas == []


async def test_mensagem_nova_enquanto_a_ia_pensa_descarta_e_refaz():
    atendimento, repo, helena = montar({})
    chamadas = {"n": 0}

    async def etapa_lenta(_sistema, conteudo):
        chamadas["n"] += 1
        if chamadas["n"] == 1:                                      # durante a 1ª resposta, chega outra mensagem
            lead = next(iter(repo.leads.values()))
            await repo.gravar_mensagem(lead=lead, autor="lead", tipo="texto", texto="esqueci: foi em 2022",
                                       texto_extraido=None, url_midia=None,
                                       enviada_em=datetime.now(timezone.utc), id_externo="extra-1")
        return fala("Entendi tudo. Ficou com alguma sequela?")

    atendimento.modelo = ModeloFalso({"extrator": extrai(), "etapa": etapa_lenta})
    await atendimento.receber(webhook("caí da moto"))
    await atendimento.aguardar_esperas()
    assert len(helena.enviadas) == 1                                # uma resposta só, para as duas mensagens
    assert [t["situacao"] for t in repo.turnos.values()] == ["descartado", "respondido"]
    assert "esqueci: foi em 2022" in atendimento.modelo.pedidos[-1]["conteudo"]


async def test_webhook_que_chega_durante_o_turno_nao_cancela_o_turno():
    atendimento, repo, helena = montar({})
    chamadas = {"n": 0}

    async def etapa(_sistema, _conteudo):
        chamadas["n"] += 1
        if chamadas["n"] == 1:                                      # o webhook novo chega com o turno em andamento
            await atendimento.receber(webhook("e quebrei o braço"))
            await asyncio.sleep(0)
        return fala("Entendi. Ficou com alguma sequela?")

    atendimento.modelo = ModeloFalso({"extrator": extrai(), "etapa": etapa})
    await atendimento.receber(webhook("caí da moto"))
    await atendimento.aguardar_esperas()
    assert len(helena.enviadas) == 1                                # uma resposta, para as duas mensagens
    assert [t["situacao"] for t in repo.turnos.values()] == ["descartado", "respondido"]
    assert repo.eventos == []                                       # nenhum erro no caminho


async def test_atendente_assume_enquanto_a_ia_pensa():
    atendimento, repo, helena = montar({})

    async def etapa(_sistema, _conteudo):
        next(iter(repo.leads.values())).estado = "pausado"
        return fala("Oi!")

    atendimento.modelo = ModeloFalso({"extrator": extrai(), "etapa": etapa})
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    assert helena.enviadas == [] and next(iter(repo.turnos.values()))["situacao"] == "descartado"


async def test_envio_que_falha_vira_evento_e_nao_derruba_o_turno():
    atendimento, repo, helena = montar(SIMPLES, helena=HelenaFalsa(falhar=True))
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    assert [e["tipo"] for e in repo.eventos] == ["envio_falhou"]
    assert next(iter(repo.turnos.values()))["situacao"] == "respondido"


async def test_fatos_e_etapa_ficam_gravados():
    respostas = {
        "extrator": extrai([("aposentado", "sim", "sou aposentado")]),
        "etapa": fala("Entendi. Nesse caso o escritório não consegue atuar neste caso."),
    }
    atendimento, repo, helena = montar(respostas)
    await atendimento.receber(webhook("sou aposentado"))
    await atendimento.aguardar_esperas()
    lead = next(iter(repo.leads.values()))
    assert await repo.fatos_vigentes(lead.id) == {"aposentado": "sim"}
    assert lead.id_etapa == "e-desq" and lead.estado == "encerrado"
    # Encerrado: a próxima mensagem do lead não tem resposta da IA.
    await atendimento.receber(webhook("mas por quê?"))
    await atendimento.aguardar_esperas()
    assert len(helena.enviadas) == 1


async def test_conta_ou_canal_desconhecido():
    atendimento, repo, _ = montar(SIMPLES)
    assert (await atendimento.receber(webhook("oi", para="5511000000000")))["motivo"] == "canal_nao_cadastrado"
    assert repo.eventos[0]["tipo"] == "canal_nao_cadastrado"
    corpo = webhook("oi")
    corpo["content"]["companyId"] = "outra-conta"
    assert (await atendimento.receber(corpo))["motivo"] == "conta_nao_cadastrada"


def test_leitura_do_webhook():
    audio = ler_webhook(webhook(None, tipo="AUDIO", transcription={"text": "caí da escada"}))
    assert (audio.classe, audio.tipo, audio.texto_extraido) == ("lead", "audio", "caí da escada")
    sem_transcricao = ler_webhook(webhook(None, tipo="PTT"))
    assert "não foi possível ouvir" in sem_transcricao.texto_extraido
    assert ler_webhook({"eventType": "TRACK", "content": {}}).classe == "rastreio"
    assert ler_webhook(webhook("x", tipo="NOTE")).classe == "ignorar"
    assert ler_webhook(webhook("x", evento="MESSAGE_UPDATED")).classe == "status"


@pytest.mark.parametrize("entrada, esperado", [
    ("+55 (11) 98888-7777", "5511988887777"),
    ("11988887777", "5511988887777"),
    ("551188887777", "5511988887777"),       # celular sem o nono dígito
    ("551133334444", "551133334444"),        # fixo fica como está
    ("", None),
])
def test_telefone(entrada, esperado):
    assert normalizar_telefone(entrada) == esperado


async def test_filtro_do_webhook_no_pipeline():
    atendimento, repo, helena = montar(SIMPLES)
    # Grupo: nem grava.
    assert (await atendimento.receber(webhook("oi grupo", de="120363000000000000@g.us")))["motivo"] == "grupo_ou_lista"
    assert not repo.leads
    # URL de outro escritório: descarta.
    assert (await atendimento.receber(webhook("oi"), id_escritorio_esperado="outro"))["motivo"] == "conta_de_outro_escritorio"
    # Número bloqueado: grava, mas a IA não responde.
    repo.escritorios["esc-1"].config["filtro"] = {"numeros_bloqueados": [LEAD]}
    resultado = await atendimento.receber(webhook("oi, sou robô"))
    assert resultado["feito"] == "gravado" and resultado["motivo"] == "numero_bloqueado"
    await atendimento.aguardar_esperas()
    assert helena.enviadas == []
    # Mensagem muito atrasada: grava, avisa a equipe e não responde.
    repo.escritorios["esc-1"].config["filtro"] = {"atraso_maximo_min": 10}
    atrasada = await atendimento.receber(webhook("oi?", quando=datetime.now(timezone.utc) - timedelta(hours=2)))
    assert atrasada["motivo"] == "mensagem_atrasada"
    assert any(e["tipo"] == "mensagem_atrasada" for e in repo.eventos)


async def test_documento_do_lead_e_lido_antes_da_ia_responder():
    import httpx
    from tests.test_midia import docx

    atendimento, repo, helena = montar(SIMPLES)
    atendimento._http_midia = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda pedido: httpx.Response(200, content=docx(["Laudo: CID S82, sequela no joelho"]))))
    corpo = webhook("", tipo="DOCUMENT", file={"publicUrl": "https://cdn.helena.run/laudo.docx", "name": "laudo.docx"})
    assert (await atendimento.receber(corpo))["feito"] == "agendado"
    await atendimento.aguardar_esperas()
    pedido_extrator = next(p for p in atendimento.modelo.pedidos if p["papel"] == "extrator")
    assert "CID S82, sequela no joelho" in pedido_extrator["conteudo"]
    lead = next(iter(repo.leads.values()))
    assert "sequela no joelho" in repo.mensagens[lead.id][0].texto_extraido


async def test_nome_do_contato_vem_do_webhook_e_nao_sobrescreve():
    atendimento, repo, _helena = montar(SIMPLES)
    await atendimento.receber(webhook("oi", contactName="Maria Souza"))
    await atendimento.receber(webhook("de novo", contactName="Outro Nome"))
    await atendimento.aguardar_esperas()
    assert repo.nomes[LEAD] == "Maria Souza"
    assert ler_webhook(webhook("oi", contactName="5511999999999")).nome_contato is None     # número não é nome


async def test_followup_agenda_depois_da_resposta_e_cancela_quando_o_lead_fala():
    atendimento, repo, _helena = montar(SIMPLES)
    await atendimento.receber(webhook("oi, boa tarde"))
    await atendimento.aguardar_esperas()
    acoes = [a[0] for a in repo.followups]
    assert acoes == ["cancelar", "agendar"]            # o lead falou (cancela o antigo) e a IA respondeu (agenda o novo)
    await atendimento.receber(webhook("voltei", de=CANAL, para=LEAD, origem="GATEWAY", direcao="TO_HUB"))   # atendente falou
    assert repo.followups[-1][0] == "cancelar" and repo.followups[-1][2] == "equipe_falou"


async def test_resposta_agendada_sobrevive_a_um_reinicio_e_reserva_evita_resposta_dupla():
    atendimento, repo, helena = montar(SIMPLES)
    repo.escritorios["esc-1"].config["espera_teste_s"] = 3600
    await atendimento.receber(webhook("oi, sofri um acidente"))
    lead = next(iter(repo.leads.values()))
    assert lead.id in repo.esperas                        # a espera ficou no banco
    for tarefa in atendimento._esperas.values():          # o servidor "cai": a tarefa em memória morre
        tarefa.cancel()

    novo = Atendimento(repo, atendimento.modelo, atendimento.config, helena, digitar=False)
    repo.esperas[lead.id] = datetime.now(timezone.utc)    # a espera venceu enquanto estava fora
    await repo.reservar_lead(lead.id, 60)                 # outro servidor está respondendo agora
    assert await novo.retomar_pendentes() == 0
    await repo.liberar_lead(lead.id)
    assert await novo.retomar_pendentes() == 1
    await novo.aguardar_esperas()
    assert helena.enviadas == ["Oi! Me conta o que aconteceu?"]
    assert lead.id not in repo.esperas                    # respondeu: a espera sai do banco
