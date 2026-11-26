"""Horário em que a IA atende: sempre, só no horário (segura e responde ao abrir) ou só fora (equipe atende)."""

from datetime import datetime, timedelta, timezone

from app import horario
from tests.test_pipeline import SIMPLES, montar, webhook

BR = timezone(timedelta(hours=-3))
SEG_10H = datetime(2026, 11, 23, 10, 0, tzinfo=BR)      # segunda-feira
SEG_22H = datetime(2026, 11, 23, 22, 0, tzinfo=BR)
SAB_10H = datetime(2026, 11, 28, 10, 0, tzinfo=BR)


def test_aberto_e_proxima_abertura():
    cfg = {"horario_inicio": 8, "horario_fim": 18}
    assert horario.aberto(cfg, SEG_10H) and not horario.aberto(cfg, SEG_22H) and not horario.aberto(cfg, SAB_10H)
    assert horario.proxima_abertura(cfg, SEG_22H).astimezone(BR).replace(tzinfo=None) == datetime(2026, 11, 24, 8, 0)
    assert horario.proxima_abertura(cfg, SAB_10H).astimezone(BR).replace(tzinfo=None) == datetime(2026, 11, 30, 8, 0)
    assert horario.aberto({**cfg, "horario_dias": [5]}, SAB_10H)


def test_decidir_por_modo():
    assert horario.decidir({}, SEG_22H) == (None, None)                                   # padrão: sempre
    motivo, quando = horario.decidir({"modo_ia_horario": "so_no_horario"}, SEG_22H)
    assert motivo == "fora_do_horario" and quando.astimezone(BR).hour == 8
    assert horario.decidir({"modo_ia_horario": "so_no_horario"}, SEG_10H) == (None, None)
    assert horario.decidir({"modo_ia_horario": "so_fora_do_horario"}, SEG_10H) == ("horario_da_equipe", None)
    assert horario.decidir({"modo_ia_horario": "so_fora_do_horario"}, SEG_22H) == (None, None)


async def test_fora_do_horario_segura_a_resposta(monkeypatch):
    abre = datetime.now(timezone.utc) + timedelta(hours=9)
    monkeypatch.setattr(horario, "decidir", lambda config, quando=None: ("fora_do_horario", abre))
    atendimento, repo, helena = montar(SIMPLES, modo="producao")
    await atendimento.receber(webhook("oi, de madrugada"))
    await asyncio_esperar_um_pouco()
    lead = next(iter(repo.leads.values()))
    assert helena.enviadas == [] and not repo.turnos
    assert repo.esperas[lead.id] == abre                                        # a resposta fica marcada para quando abrir
    assert [m.texto for m in await repo.mensagens_pendentes(lead.id)] == ["oi, de madrugada"]   # nada se perde


async def test_horario_da_equipe_a_ia_fica_em_silencio(monkeypatch):
    monkeypatch.setattr(horario, "decidir", lambda config, quando=None: ("horario_da_equipe", None))
    atendimento, repo, helena = montar(SIMPLES, modo="producao")
    await atendimento.receber(webhook("bom dia"))
    await atendimento.aguardar_esperas()
    turno = next(iter(repo.turnos.values()))
    assert helena.enviadas == [] and (turno["situacao"], turno["motivo"]) == ("silencio", "horario_da_equipe")


async def asyncio_esperar_um_pouco():
    import asyncio
    for _ in range(20):
        await asyncio.sleep(0.01)
