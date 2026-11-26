"""Senhas e sessão do painel. Só biblioteca padrão: scrypt e HMAC."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass

_N, _R, _P = 2**14, 8, 1
DURACAO_SESSAO_S = 12 * 3600


def gerar_hash(senha: str) -> str:
    sal = secrets.token_bytes(16)
    chave = hashlib.scrypt(senha.encode(), salt=sal, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${base64.b64encode(sal).decode()}${base64.b64encode(chave).decode()}"


def conferir_senha(senha: str, guardado: str) -> bool:
    try:
        _, n, r, p, sal, chave = guardado.split("$")
        calculada = hashlib.scrypt(senha.encode(), salt=base64.b64decode(sal), n=int(n), r=int(r), p=int(p),
                                   dklen=len(base64.b64decode(chave)))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(calculada, base64.b64decode(chave))


def senha_provisoria() -> str:
    return secrets.token_urlsafe(9)


@dataclass(frozen=True)
class Sessao:
    id_usuario: str
    expira_em: float


class Assinador:
    """Token de sessão assinado: base64(json).assinatura. Não guarda nada no banco."""

    def __init__(self, segredo: str | None = None) -> None:
        self._segredo = (segredo or os.environ.get("AGENTESIA_SEGREDO_SESSAO") or "").encode()
        self.provisorio = not self._segredo
        if self.provisorio:
            self._segredo = secrets.token_bytes(32)   # sessões caem quando o servidor reinicia

    def _assinar(self, corpo: bytes) -> str:
        return base64.urlsafe_b64encode(hmac.new(self._segredo, corpo, hashlib.sha256).digest()).decode().rstrip("=")

    def criar(self, id_usuario: str, duracao_s: int = DURACAO_SESSAO_S) -> str:
        corpo = base64.urlsafe_b64encode(json.dumps(
            {"u": id_usuario, "e": int(time.time()) + duracao_s}).encode()).decode().rstrip("=")
        return f"{corpo}.{self._assinar(corpo.encode())}"

    def ler(self, token: str | None) -> Sessao | None:
        if not token or "." not in token:
            return None
        corpo, assinatura = token.rsplit(".", 1)
        if not hmac.compare_digest(assinatura, self._assinar(corpo.encode())):
            return None
        try:
            dados = json.loads(base64.urlsafe_b64decode(corpo + "=" * (-len(corpo) % 4)))
        except (ValueError, json.JSONDecodeError):
            return None
        if dados.get("e", 0) < time.time():
            return None
        return Sessao(id_usuario=str(dados["u"]), expira_em=float(dados["e"]))
