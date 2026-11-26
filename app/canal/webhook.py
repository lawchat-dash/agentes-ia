"""Endereço do webhook de cada escritório.

URL: {AGENTESIA_URL_PUBLICA}/webhook/helena/{id_escritorio}?segredo={HMAC(AGENTESIA_WEBHOOK_SEGREDO, id)}
Nada a guardar: o segredo sai do segredo geral do servidor e do id do escritório.

O segredo geral (mestre) NUNCA aparece numa URL: dele saem os segredos de todos os escritórios. A rota global
/webhook/helena (legada) fica desligada por padrão e, quando ligada (AGENTESIA_WEBHOOK_GLOBAL=1), usa um segredo
derivado próprio (`segredo_global`), que não abre a URL de nenhum escritório.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
from typing import Any

_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_SEGREDO_NA_URL = re.compile(r"(segredo=)[^&\s\"']+", re.IGNORECASE)


def _derivar(rotulo: str) -> str | None:
    geral = os.environ.get("AGENTESIA_WEBHOOK_SEGREDO", "")
    if not geral:
        return None
    return hmac.new(geral.encode(), rotulo.encode(), hashlib.sha256).hexdigest()[:40]


def segredo_do_escritorio(id_escritorio: str, origem: str = "helena") -> str | None:
    if not _UUID.fullmatch(id_escritorio or ""):
        return None
    return _derivar(f"{origem}:{id_escritorio.lower()}")


def segredo_global() -> str | None:
    """Segredo da rota global /webhook/helena: derivado do mestre, nunca o mestre."""
    return _derivar("global")


def rota_global_ligada() -> bool:
    """A rota global não amarra a conta a um escritório: só atende quando ligada de propósito."""
    return os.environ.get("AGENTESIA_WEBHOOK_GLOBAL", "").strip().lower() in ("1", "true", "sim")


def url_do_escritorio(id_escritorio: str, origem: str = "helena") -> str | None:
    """origem: helena (mensagens) ou zapsign (assinatura). Cada uma com o seu segredo."""
    base = os.environ.get("AGENTESIA_URL_PUBLICA", "").rstrip("/")
    segredo = segredo_do_escritorio(id_escritorio, origem)
    if not base or not segredo:
        return None
    return f"{base}/webhook/{origem}/{id_escritorio.lower()}?segredo={segredo}"


def url_do_botao_ia(id_escritorio: str) -> str | None:
    """Botão/automação da Helena que desliga ou religa a IA (mesmo segredo do webhook de mensagens)."""
    url = url_do_escritorio(id_escritorio)
    return url.replace("?segredo=", "/ia?segredo=", 1) if url else None


def esconder_segredo(texto: str) -> str:
    """Troca o valor de ?segredo=... por *** (para logs)."""
    return _SEGREDO_NA_URL.sub(r"\1***", texto)


class FiltroDeSegredo(logging.Filter):
    """Tira o ?segredo= das linhas do log de acesso (o uvicorn registra o caminho com a query string) e do log do httpx
    (que registra a URL inteira de cada pedido, como httpx.URL e não str: a ativação chama o webhook do escritório)."""

    @staticmethod
    def _limpo(valor: Any) -> Any:
        if isinstance(valor, str):
            return esconder_segredo(valor)
        if isinstance(valor, (int, float, bool)) or valor is None:
            return valor
        texto = str(valor)
        return esconder_segredo(texto) if "segredo=" in texto.lower() else valor

    def filter(self, registro: logging.LogRecord) -> bool:
        try:
            if registro.args:
                registro.args = tuple(self._limpo(a) for a in registro.args) \
                    if isinstance(registro.args, tuple) else registro.args
            if isinstance(registro.msg, str) and "segredo=" in registro.msg.lower():
                registro.msg = esconder_segredo(registro.msg)
        except Exception:                                    # o log nunca derruba o pedido
            pass
        return True


def proteger_logs_de_acesso(nomes: tuple[str, ...] = ("uvicorn.access", "uvicorn.error", "httpx", "httpcore")) -> None:
    """Põe o FiltroDeSegredo nos loggers do uvicorn e do httpx/httpcore (idempotente)."""
    for nome in nomes:
        logger = logging.getLogger(nome)
        if not any(isinstance(f, FiltroDeSegredo) for f in logger.filters):
            logger.addFilter(FiltroDeSegredo())
