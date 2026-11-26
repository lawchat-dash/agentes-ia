"""Limite de consumo da IA por escritório (custo em dólar das chamadas ao modelo, no mês corrente).

Config no escritório (agentesia_escritorios.config.limite_consumo), definida pela equipe LawChat:
  {"mensal_usd": 100, "ao_estourar": "pausar" | "so_avisar", "avisar_em": [80, 100]}
Sem "mensal_usd" (ou 0) não há limite. Ao passar de cada faixa, um aviso por mês: evento no painel e
WhatsApp para quem estiver no aviso "consumo_limite". Com "pausar", a IA fica em silêncio até virar o mês
ou o limite subir; as conversas continuam na Helena com a equipe.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.notificacoes import fuso

FAIXAS_PADRAO = (80, 100)


@dataclass(frozen=True)
class Situacao:
    gasto_usd: float
    limite_usd: float | None
    percentual: float | None
    faixa: int | None            # maior faixa já passada (80, 100...) ou None
    bloqueado: bool              # a IA não deve responder


def config_do_limite(config_escritorio: dict[str, Any] | None) -> dict[str, Any]:
    bruto = (config_escritorio or {}).get("limite_consumo") or {}
    try:
        limite = float(bruto.get("mensal_usd") or 0)
    except (TypeError, ValueError):
        limite = 0.0
    faixas = sorted({int(f) for f in (bruto.get("avisar_em") or FAIXAS_PADRAO) if 0 < int(f) <= 1000})
    return {"mensal_usd": limite if limite > 0 else None,
            "ao_estourar": "so_avisar" if bruto.get("ao_estourar") == "so_avisar" else "pausar",
            "avisar_em": faixas or list(FAIXAS_PADRAO)}


def validar(bruto: dict[str, Any]) -> dict[str, Any]:
    """Confere o que veio do painel. Levanta ValueError com a explicação."""
    limite = bruto.get("mensal_usd")
    if limite not in (None, "", 0):
        try:
            limite = round(float(limite), 2)
        except (TypeError, ValueError):
            raise ValueError("O limite mensal precisa ser um número em dólares.") from None
        if limite < 0 or limite > 100000:
            raise ValueError("O limite mensal precisa estar entre 0 e 100.000 dólares.")
    else:
        limite = None
    if bruto.get("ao_estourar", "pausar") not in ("pausar", "so_avisar"):
        raise ValueError("Ao estourar: escolha pausar a IA ou só avisar.")
    try:
        faixas = sorted({int(f) for f in (bruto.get("avisar_em") or FAIXAS_PADRAO)})
    except (TypeError, ValueError):
        raise ValueError("As faixas de aviso precisam ser porcentagens inteiras.") from None
    if any(f <= 0 or f > 1000 for f in faixas):
        raise ValueError("As faixas de aviso vão de 1% a 1000%.")
    return {"mensal_usd": limite, "ao_estourar": bruto.get("ao_estourar", "pausar"), "avisar_em": faixas}


def inicio_do_mes(agora: datetime | None = None) -> datetime:
    local = (agora or datetime.now(timezone.utc)).astimezone(fuso())
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def avaliar(gasto_usd: float, config_escritorio: dict[str, Any] | None) -> Situacao:
    cfg = config_do_limite(config_escritorio)
    limite = cfg["mensal_usd"]
    if not limite:
        return Situacao(round(gasto_usd, 4), None, None, None, False)
    percentual = gasto_usd / limite * 100
    passadas = [f for f in cfg["avisar_em"] if percentual >= f]
    return Situacao(round(gasto_usd, 4), limite, round(percentual, 1), max(passadas) if passadas else None,
                    cfg["ao_estourar"] == "pausar" and percentual >= 100)


def texto_do_aviso(nome_escritorio: str, situacao: Situacao, config_escritorio: dict[str, Any] | None) -> str:
    pausa = config_do_limite(config_escritorio)["ao_estourar"] == "pausar"
    cabeca = "🚫 *Limite de consumo da IA atingido*" if (situacao.percentual or 0) >= 100 else f"⚠️ *Consumo da IA em {situacao.faixa}%*"
    linhas = [cabeca, f"Escritório: {nome_escritorio}",
              f"Gasto no mês: US$ {situacao.gasto_usd:.2f} de US$ {situacao.limite_usd:.2f} ({situacao.percentual:.0f}%)"]
    if (situacao.percentual or 0) >= 100:
        linhas.append("A IA parou de responder até o mês virar ou o limite subir. A equipe segue atendendo pela Helena."
                      if pausa else "A IA continua respondendo (o limite está só para aviso).")
    return "\n".join(linhas)


class ControleDeConsumo:
    """Guarda o gasto do mês por escritório por um minuto, para não somar as chamadas a cada mensagem."""

    def __init__(self, validade_s: float = 60) -> None:
        self._validade = validade_s
        self._cache: dict[str, tuple[float, float, str]] = {}

    def em_cache(self, id_escritorio: str, mes: str) -> float | None:
        item = self._cache.get(id_escritorio)
        if item and item[0] > time.monotonic() and item[2] == mes:
            return item[1]
        return None

    def guardar(self, id_escritorio: str, mes: str, gasto: float) -> None:
        self._cache[id_escritorio] = (time.monotonic() + self._validade, gasto, mes)

    def somar(self, id_escritorio: str, valor: float) -> None:
        item = self._cache.get(id_escritorio)
        if item:
            self._cache[id_escritorio] = (item[0], item[1] + valor, item[2])

    def esquecer(self, id_escritorio: str) -> None:
        self._cache.pop(id_escritorio, None)
