"""Relógio da simulação: congelado no `agora` do cenário e andando só quando o simulador manda.

O prompt leva "Hoje é dd/mm/aaaa HH:MM". Sem congelar, o cassete se invalida a cada minuto e o período de graça
muda com o calendário. O patch é feito no módulo de origem (extrator.py e agente.py importam dentro da função):
  - app.cerebro.contexto.agora_em_brasilia (linha_de_hoje usa o mesmo atributo do módulo);
  - app.pipeline.agora;
  - app.followup.servico.agora.

O relógio de cada conversa fica numa ContextVar: as tarefas que o pipeline cria herdam o contexto, então
conversas em paralelo não se misturam. Fora de uma conversa simulada, as funções originais respondem.
"""

from __future__ import annotations

import contextvars
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

_atual: contextvars.ContextVar["Relogio | None"] = contextvars.ContextVar("relogio_da_avaliacao", default=None)
_trava = threading.Lock()
_instalados = 0
_originais: dict[str, Any] = {}


class Relogio:
    def __init__(self, momento: datetime) -> None:
        if momento.tzinfo is None:
            raise ValueError("o relógio da simulação precisa de fuso")
        self.momento = momento

    def agora(self) -> datetime:
        return self.momento

    def agora_utc(self) -> datetime:
        return self.momento.astimezone(timezone.utc)

    def avancar(self, segundos: float = 1) -> datetime:
        self.momento = self.momento + timedelta(seconds=segundos)
        return self.momento


def _alvos() -> list[tuple[Any, str]]:
    from app import pipeline
    from app.cerebro import contexto
    from app.followup import servico

    return [(contexto, "agora_em_brasilia"), (pipeline, "agora"), (servico, "agora")]


def _instalar() -> None:
    global _instalados
    with _trava:
        _instalados += 1
        if _instalados > 1:
            return
        for modulo, nome in _alvos():
            original = getattr(modulo, nome)
            _originais[f"{modulo.__name__}.{nome}"] = original
            setattr(modulo, nome, _substituto(nome, original))


def _desinstalar() -> None:
    global _instalados
    with _trava:
        _instalados -= 1
        if _instalados > 0:
            return
        for modulo, nome in _alvos():
            setattr(modulo, nome, _originais.pop(f"{modulo.__name__}.{nome}"))


def _substituto(nome: str, original: Any) -> Any:
    if nome == "agora_em_brasilia":
        def agora_em_brasilia(agora: datetime | None = None) -> datetime:
            relogio = _atual.get()
            return original(agora if agora is not None or relogio is None else relogio.agora())
        agora_em_brasilia.__wrapped__ = original      # type: ignore[attr-defined]
        return agora_em_brasilia

    def agora() -> datetime:
        relogio = _atual.get()
        return original() if relogio is None else relogio.agora_utc()
    agora.__wrapped__ = original                      # type: ignore[attr-defined]
    return agora


@contextmanager
def congelar(momento: datetime, monkeypatch: Any = None) -> Iterator[Relogio]:
    """Congela o relógio nesta conversa. Com `monkeypatch` (pytest), o patch fica a cargo dele."""
    relogio = Relogio(momento)
    if monkeypatch is not None:
        for modulo, nome in _alvos():
            original = getattr(modulo, nome)
            original = getattr(original, "__wrapped__", original)
            monkeypatch.setattr(modulo, nome, _substituto(nome, original))
        marca = _atual.set(relogio)
        try:
            yield relogio
        finally:
            _atual.reset(marca)
        return
    _instalar()
    marca = _atual.set(relogio)
    try:
        yield relogio
    finally:
        _atual.reset(marca)
        _desinstalar()
