"""Medição do turno: quanto tempo cada passo levou e quantas idas ao banco o turno fez.

O pipeline abre uma Medicao por turno (contextvar): as tarefas criadas dentro do turno (asyncio.gather, create_task)
herdam o contexto e somam na mesma medição. As idas ao banco são contadas pelo query logger do asyncpg, ligado em
cada conexão do pool (app/banco/postgres.py). O resultado vai em agentesia_turnos.resposta["tempos"].
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator


class Medicao:
    def __init__(self) -> None:
        self.inicio = time.monotonic()
        self.passos: dict[str, float] = {}          # nome -> milissegundos (somados se o passo se repete)
        self.idas_ao_banco = 0
        self.marcas: dict[str, float] = {}          # nome -> ms desde o início (ex.: primeira parte enviada)

    def somar(self, nome: str, segundos: float) -> None:
        self.passos[nome] = round(self.passos.get(nome, 0.0) + segundos * 1000, 1)

    def marcar(self, nome: str) -> None:
        self.marcas.setdefault(nome, round((time.monotonic() - self.inicio) * 1000, 1))

    def como_dict(self) -> dict[str, Any]:
        return {"passos_ms": dict(self.passos), "marcas_ms": dict(self.marcas),
                "total_ms": round((time.monotonic() - self.inicio) * 1000, 1), "idas_ao_banco": self.idas_ao_banco}


_atual: ContextVar[Medicao | None] = ContextVar("agentesia_medicao", default=None)


def comecar() -> tuple[Medicao, Any]:
    medicao = Medicao()
    return medicao, _atual.set(medicao)


def terminar(ficha: Any) -> None:
    _atual.reset(ficha)


def atual() -> Medicao | None:
    return _atual.get()


@contextmanager
def passo(nome: str) -> Iterator[None]:
    """Soma a duração do bloco no passo `nome` da medição do turno (sem medição aberta, não faz nada)."""
    medicao = _atual.get()
    if medicao is None:
        yield
        return
    comeco = time.monotonic()
    try:
        yield
    finally:
        medicao.somar(nome, time.monotonic() - comeco)


def marcar(nome: str) -> None:
    if (medicao := _atual.get()) is not None:
        medicao.marcar(nome)


def contar_ida(_registro: Any = None) -> None:
    """Query logger do asyncpg: roda no contexto da tarefa que fez a consulta (loop.call_soon copia o contexto)."""
    if (medicao := _atual.get()) is not None:
        medicao.idas_ao_banco += 1
