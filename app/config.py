"""Configuração lida das variáveis de ambiente. Nenhum segredo fica no código."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _carregar_env_local(caminho: str = ".env") -> None:
    """Lê um arquivo .env simples (CHAVE=valor), sem sobrescrever o ambiente."""
    if not os.path.exists(caminho):
        return
    with open(caminho, encoding="utf-8") as arquivo:
        for linha in arquivo:
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            chave, valor = linha.split("=", 1)
            os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Configuracao:
    banco_url: str | None          # Postgres do Supabase; vazio = só Laboratório em memória
    helena_url: str
    modelo_padrao: str             # modelo usado quando o agente não define outro
    modelo_falso: bool             # True = não chama a IA (testes e demonstração sem chave)
    espera_minima_s: float
    espera_maxima_s: float
    espera_padrao_s: float
    segundos_por_letra: float
    max_reprocessos: int
    espera_midia_s: float = 60     # quanto o turno espera a leitura de arquivo/imagem do lead


def carregar() -> Configuracao:
    _carregar_env_local()
    return Configuracao(
        banco_url=os.environ.get("AGENTESIA_BANCO_URL") or None,
        helena_url=os.environ.get("AGENTESIA_HELENA_URL", "https://api.helena.run"),
        modelo_padrao=os.environ.get("AGENTESIA_MODELO", "gpt-4.1"),
        modelo_falso=os.environ.get("AGENTESIA_MODELO_FALSO", "").lower() in ("1", "true", "sim"),
        espera_minima_s=float(os.environ.get("AGENTESIA_ESPERA_MINIMA", "15")),
        espera_maxima_s=float(os.environ.get("AGENTESIA_ESPERA_MAXIMA", "90")),
        espera_padrao_s=float(os.environ.get("AGENTESIA_ESPERA_PADRAO", "40")),
        segundos_por_letra=float(os.environ.get("AGENTESIA_SEGUNDOS_POR_LETRA", "0.5")),
        max_reprocessos=int(os.environ.get("AGENTESIA_MAX_REPROCESSOS", "2")),
    )
