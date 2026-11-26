"""Turno cortado no meio por deploy ou queda do servidor.

Caso real (26/11): o deploy desligou o servidor no meio de um turno; o lead respondeu "João" e a IA ficou 5 minutos
calada, porque a reserva do lead (do processo morto) só vencia depois disso, e nada apareceu na tela de Erros.

Agora:
- a reserva é curta e renovada pelo próprio turno (um processo morto solta o lead em segundos);
- ao desligar, o servidor solta as reservas que ainda segura;
- a varredura acha o turno órfão em ~20 s, grava o erro 'turno_interrompido' (aparece em Erros) dizendo o que já
  tinha saído e quantas mensagens o lead mandou nesse meio tempo, e a IA responde de novo sozinha.
"""

from datetime import datetime, timedelta, timezone

from tests.test_pipeline import SIMPLES, montar, webhook


async def _turno_cortado(segundos_atras=40, ia_ja_enviou=False):
    """Monta o estado que o processo morto deixou: mensagem do lead presa num turno 'processando'."""
    atendimento, repo, helena = montar(SIMPLES)
    await atendimento.receber(webhook("oi, sofri um acidente"))
    for tarefa in list(atendimento._esperas.values()):       # o processo antigo pegou a mensagem e morreu
        tarefa.cancel()
    atendimento._esperas.clear()
    atendimento._prazos.clear()
    id_lead = next(iter(repo.leads))
    lead = repo.leads[id_lead]
    pendentes = await repo.mensagens_pendentes(id_lead)
    id_turno = await repo.abrir_turno(lead=lead, modo="teste", etapa_antes="sdr")
    await repo.marcar_no_turno([m.id for m in pendentes], id_turno)
    if ia_ja_enviou:
        await repo.gravar_mensagem(lead=lead, autor="ia", tipo="texto", texto="Antes de continuar, qual é o seu nome?",
                                   texto_extraido=None, url_midia=None, enviada_em=datetime.now(timezone.utc), id_externo=None,
                                   id_turno=id_turno)
    repo.turnos[id_turno]["iniciado_em"] -= timedelta(seconds=segundos_atras)
    await repo.marcar_resposta(id_lead, None)
    return atendimento, repo, helena, id_lead, id_turno


def _erros(repo, id_turno):
    return [e for e in repo.eventos if e.get("id_turno") == id_turno and e["tipo"] == "turno_interrompido"]


async def test_turno_orfao_vira_erro_e_a_ia_responde_de_novo():
    atendimento, repo, helena, id_lead, id_turno = await _turno_cortado()
    await atendimento.receber(webhook("João"))                 # o lead escreveu enquanto o servidor reiniciava
    for tarefa in list(atendimento._esperas.values()):
        tarefa.cancel()
    atendimento._esperas.clear()
    atendimento._prazos.clear()

    await atendimento.retomar_pendentes()
    await atendimento.aguardar_esperas()

    assert repo.turnos[id_turno]["situacao"] == "erro"
    [erro] = _erros(repo, id_turno)
    assert erro["gravidade"] == "erro"
    assert "responde de novo" in erro["descricao"] and "1 mensagem(ns) nesse meio tempo" in erro["descricao"]
    assert len(helena.enviadas) >= 1                          # a IA respondeu sozinha
    assert not await repo.mensagens_pendentes(id_lead)         # as duas mensagens entraram na resposta


async def test_turno_com_reserva_viva_nao_e_tocado():
    atendimento, repo, _helena, id_lead, id_turno = await _turno_cortado()
    await repo.reservar_lead(id_lead, 90)                       # o processo dono está vivo e renovando
    await atendimento.retomar_pendentes()
    assert repo.turnos[id_turno]["situacao"] == "processando"
    assert not _erros(repo, id_turno)


async def test_turno_recente_espera_um_pouco_antes_de_ser_dado_como_morto():
    atendimento, repo, _helena, _id_lead, id_turno = await _turno_cortado(segundos_atras=2)
    await atendimento.retomar_pendentes()
    assert repo.turnos[id_turno]["situacao"] == "processando"


async def test_se_a_ia_ja_tinha_enviado_nao_repete_e_avisa_para_conferir():
    atendimento, repo, _helena, id_lead, id_turno = await _turno_cortado(ia_ja_enviou=True)
    await atendimento.retomar_pendentes()
    [erro] = _erros(repo, id_turno)
    assert "confira a conversa" in erro["descricao"]
    assert not await repo.mensagens_pendentes(id_lead)         # a mensagem já respondida não volta para a fila


async def test_desligar_solta_a_reserva_e_marca_para_responder_ja():
    atendimento, repo, _helena = montar(SIMPLES)
    await atendimento.receber(webhook("oi"))
    for tarefa in list(atendimento._esperas.values()):
        tarefa.cancel()
    atendimento._esperas.clear()
    id_lead = next(iter(repo.leads))
    await repo.reservar_lead(id_lead, 90)
    atendimento._reservados.add(id_lead)                       # turno deste processo em andamento no desligamento
    await atendimento.encerrar(teto_s=1)
    assert await repo.reservar_lead(id_lead, 1)                # reserva solta: o servidor novo pega na hora
    assert id_lead in repo.esperas                             # e com prazo de resposta para já
