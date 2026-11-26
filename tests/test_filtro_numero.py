"""Filtro de número do agente (botão "Filtrar número"): ligado, o agente responde SÓ aos números da lista.

Caso do dono: agente em modo teste com 1 número na lista do PRÓPRIO agente (o escritório sem lista). Outro número
manda mensagem: fica gravada, mas a IA não responde nada; o número da lista é respondido. Vale para o número como
chega do WhatsApp (com 55 e 9) e como foi digitado no painel (com máscara).
"""

import pytest

from tests.test_pipeline import SIMPLES, montar, webhook

MEU = "5531986936492"            # o número de teste, como o WhatsApp manda
OUTRO = "5531999990000"          # qualquer outra pessoa


def _montar_com_filtro_no_agente(lista):
    atendimento, repo, helena = montar(SIMPLES, numeros_teste=())        # escritório SEM lista
    agente = next(iter(repo.agentes.values()))
    agente.modo = "teste"
    agente.numeros_teste = list(lista)                                   # a lista do botão Filtrar número
    return atendimento, repo, helena


@pytest.mark.parametrize("como_salvo", [MEU, "(31) 98693-6492", "31986936492"])
async def test_filtro_ligado_so_o_meu_numero_recebe_resposta(como_salvo):
    atendimento, repo, helena = _montar_com_filtro_no_agente([como_salvo])
    await atendimento.receber(webhook("oi, quero saber do auxílio", de=OUTRO))
    await atendimento.aguardar_esperas()
    assert helena.enviadas == []                                          # outro número: nada sai
    await atendimento.receber(webhook("oi", de=MEU))
    await atendimento.aguardar_esperas()
    assert len(helena.enviadas) >= 1                                       # o meu: respondido
    destinos = {str(e) for e in helena.enviadas}
    assert not any(OUTRO in d for d in destinos)


async def test_filtro_ligado_com_lista_vazia_nao_responde_ninguem():
    atendimento, _repo, helena = _montar_com_filtro_no_agente([])
    await atendimento.receber(webhook("oi", de=OUTRO))
    await atendimento.aguardar_esperas()
    assert helena.enviadas == []


async def test_filtro_desligado_responde_todo_mundo():
    atendimento, repo, helena = _montar_com_filtro_no_agente([MEU])
    next(iter(repo.agentes.values())).modo = "producao"
    await atendimento.receber(webhook("oi", de=OUTRO))
    await atendimento.aguardar_esperas()
    assert len(helena.enviadas) >= 1
