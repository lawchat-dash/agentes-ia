"""Notas-ponte no atendimento: a equipe vê no chat por que a IA recebeu a mensagem e não respondeu (ou o que aconteceu).

Cada caminho de "não responder" do pipeline: agente pausado, IA desligada no escritório ou na conversa, créditos
acabando/acabaram, fora do horário, horário da equipe, rajada. Número fora da lista de teste nunca ganha nota.
Nenhuma nota repete a cada mensagem."""

import asyncio
from datetime import datetime, timedelta, timezone

from app import cobranca
from app.notificacoes import fuso
from tests.test_pipeline import LEAD, SIMPLES, montar, webhook
from tests.test_turno import extrai, fala


def _notas(repo):
    return [a["dados"]["texto"] for a in repo.acoes if a["tipo"] == "nota"]


async def _manda(atendimento, *textos):
    for texto in textos:
        await atendimento.receber(webhook(texto))
        await atendimento.aguardar_esperas()


def _lead(repo):
    return next(iter(repo.leads.values()))


# ----------------------------------------------------------------------------- agente pausado / IA desligada
async def test_agente_pausado_nota_com_o_nome_uma_vez():
    atendimento, repo, helena = montar(SIMPLES, situacao="pausado")
    await _manda(atendimento, "oi", "alô?")
    assert helena.enviadas == []
    assert _notas(repo) == ["⏸️ A IA não respondeu: o agente Júlia está pausado. Religue o agente no painel para ela "
                            "voltar a atender."]


async def test_numero_fora_da_lista_de_teste_nao_ganha_nota_nenhuma():
    # Agente em teste, número fora da lista: nem com o agente ativo, nem pausado, nem com rajada.
    atendimento, repo, helena = montar(SIMPLES, numeros_teste=("5511900000000",))
    await _manda(atendimento, "oi")
    assert helena.enviadas == [] and _notas(repo) == []
    assert next(iter(repo.turnos.values()))["motivo"] == "modo_teste"

    atendimento, repo, _ = montar(SIMPLES, situacao="pausado", numeros_teste=("5511900000000",))
    await _manda(atendimento, "oi")
    assert _notas(repo) == []

    atendimento, repo, _ = montar(SIMPLES, numeros_teste=("5511900000000",))
    repo.escritorios["esc-1"].config["filtro"] = {"rajada": {"mensagens": 1, "segundos": 60}}
    await _manda(atendimento, "oi", "oi", "oi")
    assert _notas(repo) == []


async def test_ia_desligada_no_escritorio_nota_clara():
    atendimento, repo, _ = montar(SIMPLES)
    repo.escritorios["esc-1"].ia_desligada = True
    await _manda(atendimento, "oi", "oi de novo")
    assert _notas(repo) == ["⏸️ A IA não respondeu: a IA está desligada neste escritório. Religue no painel para ela "
                            "voltar a atender."]


# ----------------------------------------------------------------------------- IA desativada nesta conversa
async def test_ia_desativada_na_conversa_sem_prazo_nota_uma_vez():
    atendimento, repo, helena = montar(SIMPLES)
    await _manda(atendimento, "oi")
    lead = _lead(repo)
    lead.estado, lead.motivo_estado = "pausado", "desativada_pela_equipe"
    await _manda(atendimento, "tem alguém?", "???")
    assert len(helena.enviadas) == 1
    desativada = [n for n in _notas(repo) if n.startswith("⏸️")]
    assert desativada == [atendimento.NOTAS_DE_PROBLEMA["ia_desativada"]]
    assert "IA Desativada" in desativada[0] and "Helena" not in desativada[0]


async def test_ia_desativada_ha_pouco_nao_repete_a_nota_da_desativacao():
    atendimento, repo, _ = montar(SIMPLES)
    await _manda(atendimento, "oi")
    lead = _lead(repo)
    lead.estado, lead.motivo_estado = "pausado", "desativada_pela_equipe"
    # A nota DES-... que app/ia_controle deixou na hora de desativar.
    await repo.enfileirar_acoes(id_escritorio="esc-1", id_lead=lead.id, id_turno=None, acoes=[
        {"tipo": "nota", "chave_unica": f"{lead.id}:ia:DES-ABC123:nota", "dados": {"texto": "🤖 IA desativada"}}])
    await _manda(atendimento, "oi?")
    assert not any(n.startswith("⏸️") for n in _notas(repo))
    # Mais de 6 h depois da desativação: agora a nota sai.
    repo.acoes[-1]["criada_em"] = datetime.now(timezone.utc) - timedelta(hours=7)
    await _manda(atendimento, "oi??")
    assert [n for n in _notas(repo) if n.startswith("⏸️")] == [atendimento.NOTAS_DE_PROBLEMA["ia_desativada"]]


async def test_ia_desativada_com_prazo_diz_ate_quando_e_guarda_a_mensagem():
    atendimento, repo, helena = montar(SIMPLES)
    await _manda(atendimento, "oi")
    lead = _lead(repo)
    volta = datetime.now(timezone.utc) + timedelta(hours=2)
    lead.estado, lead.motivo_estado, lead.pausado_ate = "pausado", "desativada_pela_equipe", volta
    await _manda(atendimento, "oi?", "alô")
    assert len(helena.enviadas) == 1
    notas = [n for n in _notas(repo) if n.startswith("⏸️")]
    assert len(notas) == 1 and f"às {volta.astimezone(fuso()):%H:%M}" in notas[0] and "ficou guardada" in notas[0]


async def test_pausa_do_atendente_nao_ganha_nota_a_cada_mensagem():
    atendimento, repo, _ = montar(SIMPLES)
    await _manda(atendimento, "oi")
    lead = _lead(repo)
    lead.estado, lead.motivo_estado = "pausado", "humano_assumiu"
    await _manda(atendimento, "ok", "obrigado")
    assert not any(n.startswith("⏸️") for n in _notas(repo))


# ----------------------------------------------------------------------------- créditos da IA
async def test_creditos_acabaram_nota_com_o_caminho_da_recarga():
    atendimento, repo, helena = montar(SIMPLES)
    repo.sem_saldo = {"esc-1"}
    await _manda(atendimento, "oi", "oi?")
    assert helena.enviadas == []
    assert _notas(repo) == ["⛔ A IA recebeu a mensagem mas não respondeu: os créditos da IA acabaram. Recarregue em "
                            "Créditos da IA para ela voltar a atender."]


async def test_creditos_acabando_nota_uma_vez_por_conversa_por_dia():
    atendimento, repo, helena = montar({"extrator": extrai(), "etapa": fala("Oi!")})
    repo.credito = {"esc-1": 12.7}
    await _manda(atendimento, "oi", "tudo bem?")
    assert len(helena.enviadas) == 2                                   # a IA responde normalmente
    acabando = [n for n in _notas(repo) if "Créditos da IA acabando" in n]
    assert acabando == ["⚠️ Créditos da IA acabando (restam 12%). Recarregue para a IA não parar."]


async def test_creditos_com_folga_ou_sem_carteira_nao_anotam():
    for restante in (55.0, None):
        atendimento, repo, _ = montar(SIMPLES)
        repo.credito = {"esc-1": restante}
        await _manda(atendimento, "oi")
        assert not any("Créditos" in n for n in _notas(repo))


def test_percentual_dos_creditos():
    assert cobranca.percentual(20, 80) == 20.0          # tinha 100 depois da recarga, gastou 80
    assert cobranca.percentual(100, 0) == 100.0
    assert cobranca.percentual(0, 0) is None            # sem crédito nenhum: quem fala é o bloqueio
    assert cobranca.percentual(-1, 10) == 0.0


# ----------------------------------------------------------------------------- horário
async def test_fora_do_horario_diz_quando_ela_responde_uma_vez():
    atendimento, repo, helena = montar(SIMPLES, modo="producao")
    amanha = (datetime.now(fuso()) + timedelta(days=1)).weekday()
    repo.escritorios["esc-1"].config.update(modo_ia_horario="so_no_horario", horario_dias=[amanha],
                                            horario_inicio=8, horario_fim=18)
    for texto in ("oi", "alguém?"):                  # a resposta fica para amanhã: não dá para aguardar as esperas
        await atendimento.receber(webhook(texto))
        await asyncio.sleep(0.3)
    for tarefa in atendimento._esperas.values():
        tarefa.cancel()
    assert helena.enviadas == []
    assert _notas(repo) == ["🌙 O lead escreveu fora do horário de atendimento da IA. A mensagem ficou guardada e ela "
                            "responde quando o escritório abrir, amanhã às 08:00."]


async def test_horario_da_equipe_nota_uma_vez_por_dia():
    atendimento, repo, helena = montar(SIMPLES, modo="producao")
    repo.escritorios["esc-1"].config.update(modo_ia_horario="so_fora_do_horario", horario_dias=list(range(7)),
                                            horario_inicio=0, horario_fim=24)
    await _manda(atendimento, "oi", "oi?")
    assert helena.enviadas == []
    assert _notas(repo) == [atendimento.NOTA_HORARIO_DA_EQUIPE]


# ----------------------------------------------------------------------------- rajada, pedidos do lead, desqualificado
async def test_rajada_deixa_nota_quando_a_ia_sai_da_conversa():
    atendimento, repo, _ = montar(SIMPLES)
    repo.escritorios["esc-1"].config["filtro"] = {"rajada": {"mensagens": 2, "segundos": 60}}
    for _ in range(5):
        await atendimento.receber(webhook("spam"))
    await atendimento.aguardar_esperas()
    assert [n for n in _notas(repo) if n.startswith("🚦")] == [atendimento.NOTAS_DE_PROBLEMA["rajada"]]
    assert _lead(repo).estado == "pausado"


async def test_lead_pediu_para_parar_e_engano_ganham_nota():
    for intencao, comeco in (("pediu_para_parar", "🛑 O lead pediu para não receber mais mensagens"),
                             ("engano", "🤷 O lead disse que foi engano")):
        atendimento, repo, helena = montar({"extrator": extrai(**{intencao: True}), "etapa": fala("Oi!")})
        await _manda(atendimento, "não quero mais")
        assert len(helena.enviadas) == 1 and _lead(repo).estado == "encerrado"
        assert any(n.startswith(comeco) for n in _notas(repo)), _notas(repo)


async def test_lead_desqualificado_ganha_nota_com_o_motivo():
    atendimento, repo, _ = montar({"extrator": extrai([("aposentado", "sim", "sou aposentado")]),
                                   "etapa": fala("Entendi. Nesse caso o escritório não consegue atuar.")})
    await _manda(atendimento, "sou aposentado")
    assert _lead(repo).id_etapa == "e-desq"
    assert [n for n in _notas(repo) if n.startswith("🚫")] == [
        "🚫 Lead desqualificado pela IA (motivo: aposentado). Se a equipe discordar, assuma a conversa."]


async def test_desqualificado_com_nota_da_automacao_nao_dobra():
    atendimento, repo, _ = montar({"extrator": extrai([("aposentado", "sim", "sou aposentado")]),
                                   "etapa": fala("Entendi.")})
    repo.agentes["canal-1"].config.update(funcoes={"avisos": True},
                                          automacoes={"etapa:desqualificado": {"nota": "Lead desqualificado pela IA."}})
    await _manda(atendimento, "sou aposentado")
    assert any(n.startswith("Lead desqualificado pela IA.") for n in _notas(repo))
    assert not any(n.startswith("🚫") for n in _notas(repo))


# ----------------------------------------------------------------------------- textos
def test_nenhuma_nota_mostra_helena_nem_o_texto_que_assustava():
    from app.pipeline import Atendimento
    textos = [*Atendimento.NOTAS_DE_PROBLEMA.values(), Atendimento.NOTA_FORA_DO_HORARIO, Atendimento.NOTA_HORARIO_DA_EQUIPE,
              Atendimento.NOTA_CREDITOS_ACABANDO, Atendimento.NOTA_DESQUALIFICADO]
    assert not any("Helena" in t for t in textos)
    assert not any("Parte da resposta da IA não foi entregue" in t for t in textos)


async def test_lead_de_teste_continua_respondido_sem_notas_extras():
    atendimento, repo, helena = montar(SIMPLES)
    await _manda(atendimento, "oi")
    assert helena.enviadas and _lead(repo).telefone == LEAD
    assert all(n.startswith("🤖 Atendimento iniciado") for n in _notas(repo))
