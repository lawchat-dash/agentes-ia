"""Cache curto em memória para as leituras mais chamadas do painel (Início, selo dos números, catálogo, saldo).

Com o banco em us-west-2 cada ida custa ~200 ms; o painel pede as mesmas leituras a cada troca de tela. Regras:
  - cada cache tem um tempo curto (segundos) e uma chave que inclui o escritório (e o papel, quando a resposta muda
    com ele);
  - QUALQUER escrita na API do painel (POST/PUT/PATCH/DELETE em /api/) apaga todos os caches deste processo, antes e
    depois de responder (ver `LimparAoEscrever`): o que a pessoa muda aparece na hora;
  - o que muda por fora (o app "ia" atendendo, um webhook de pagamento) aparece em até o tempo do cache.
Cada processo tem os seus (o painel e a IA são processos separados).
"""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

# Os testes desligam (tests/conftest.py): os apps de teste não passam pelo middleware que limpa ao escrever.
LIGADO = True
_TODOS: list["CacheCurto"] = []
_METODOS_QUE_ESCREVEM = {"POST", "PUT", "PATCH", "DELETE"}
# POSTs que não mudam dado do painel (só geram o link de entrada na LawChat; a camada de telas da LawChat chama vários
# ao abrir o painel). Mesma lista em painel/src/api.ts.
_NAO_ALTERAM = {"/api/atendimento/entrar"}


class CacheCurto:
    def __init__(self, segundos: float, maximo: int = 500) -> None:
        self.segundos = segundos
        self.maximo = maximo
        self._itens: dict[Any, tuple[float, int, Any]] = {}
        _TODOS.append(self)

    async def obter(self, chave: Any, calcular: Callable[[], Awaitable[Any]]) -> Any:
        if not LIGADO:
            return await calcular()
        guardado = self._itens.get(chave)
        if guardado and time.monotonic() - guardado[0] < self.segundos and guardado[1] == _geracao[0]:
            return guardado[2]
        geracao = _geracao[0]
        valor = await calcular()
        # Uma escrita durante o cálculo pode ter deixado o valor velho: só guarda se nada foi escrito no meio.
        if geracao == _geracao[0]:
            if len(self._itens) >= self.maximo:
                self._itens.clear()
            self._itens[chave] = (time.monotonic(), geracao, valor)
        return valor

    def limpar(self) -> None:
        self._itens.clear()


_geracao = [0]


def limpar_todos() -> None:
    _geracao[0] += 1
    for cache in _TODOS:
        cache.limpar()


class LimparAoEscrever:
    """Middleware ASGI: escrita em /api/ apaga os caches curtos (antes de começar e depois de terminar)."""

    def __init__(self, aplicativo: Any) -> None:
        self.aplicativo = aplicativo

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        escreve = (scope["type"] == "http" and scope.get("method") in _METODOS_QUE_ESCREVEM
                   and scope.get("path", "").startswith("/api/") and scope.get("path") not in _NAO_ALTERAM)
        if not escreve:
            await self.aplicativo(scope, receive, send)
            return
        limpar_todos()
        try:
            await self.aplicativo(scope, receive, send)
        finally:
            limpar_todos()

