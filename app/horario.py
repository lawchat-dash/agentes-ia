"""Horário em que a IA atende (por escritório, horário de Brasília).

config do escritório:
  horario_inicio / horario_fim  hora cheia (padrão 8 e 18)
  horario_dias                  0 = segunda ... 6 = domingo (padrão segunda a sexta)
  modo_ia_horario               "sempre" (padrão) | "so_no_horario" | "so_fora_do_horario"

so_no_horario: fora do horário a IA segura a mensagem e responde quando o escritório abrir.
so_fora_do_horario: no horário quem atende é a equipe; a IA fica em silêncio e não responde depois.
Vale só no modo produção: no teste e no laboratório a IA sempre responde.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.notificacoes import fuso

MODOS = ("sempre", "so_no_horario", "so_fora_do_horario")
DIAS_PADRAO = (0, 1, 2, 3, 4)


def regra(config: dict[str, Any] | None) -> dict[str, Any]:
    config = config or {}
    modo = config.get("modo_ia_horario") if config.get("modo_ia_horario") in MODOS else "sempre"
    inicio = int(config.get("horario_inicio") if config.get("horario_inicio") is not None else 8)
    fim = int(config.get("horario_fim") if config.get("horario_fim") is not None else 18)
    dias = tuple(sorted({int(d) for d in (config.get("horario_dias") or DIAS_PADRAO) if 0 <= int(d) <= 6})) or DIAS_PADRAO
    return {"modo": modo, "inicio": max(0, min(inicio, 23)), "fim": max(1, min(fim, 24)), "dias": dias}


def aberto(config: dict[str, Any] | None, quando: datetime | None = None) -> bool:
    r = regra(config)
    local = (quando or datetime.now(timezone.utc)).astimezone(fuso())
    return local.weekday() in r["dias"] and r["inicio"] <= local.hour < r["fim"]


def proxima_abertura(config: dict[str, Any] | None, quando: datetime | None = None) -> datetime:
    """Próximo instante em que o escritório abre (ou o próprio instante, se já está aberto)."""
    r = regra(config)
    local = (quando or datetime.now(timezone.utc)).astimezone(fuso())
    if aberto(config, local):
        return local
    for dias in range(0, 8):
        dia = (local + timedelta(days=dias)).replace(hour=r["inicio"], minute=0, second=0, microsecond=0)
        if dia.weekday() in r["dias"] and dia > local:
            return dia
    return local + timedelta(days=1)


def decidir(config: dict[str, Any] | None, quando: datetime | None = None) -> tuple[str | None, datetime | None]:
    """(motivo para a IA não responder agora, quando responder). (None, None) = responde agora."""
    r = regra(config)
    if r["modo"] == "sempre" or r["inicio"] >= r["fim"]:
        return None, None
    dentro = aberto(config, quando)
    if r["modo"] == "so_no_horario" and not dentro:
        return "fora_do_horario", proxima_abertura(config, quando)
    if r["modo"] == "so_fora_do_horario" and dentro:
        return "horario_da_equipe", None
    return None, None
