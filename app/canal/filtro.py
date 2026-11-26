"""Filtro do webhook: o que chega da Helena e não deve virar atendimento da IA.

Duas camadas:
  - antes do banco (`antes_do_banco`): coisas que nem gravamos, por não serem conversa com lead
    (grupo, lista de transmissão, canal de novidades, reação, mensagem apagada, chamada, vazio).
    Não grava o conteúdo: mensagem de grupo é de terceiros.
  - depois de achar escritório e canal (`decidir`): gravamos a mensagem, mas a IA não responde
    (número bloqueado, mensagem muito atrasada, rajada de mensagens, conversa consigo mesmo).

Regras de cada escritório ficam em escritorio.config["filtro"] e podem ser ajustadas por agente em
agente.config["filtro"]:
    {"atraso_maximo_min": 30, "numeros_bloqueados": ["5511..."], "rajada": {"mensagens": 20, "segundos": 60}}
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.canal.helena import Evento, normalizar_telefone, so_digitos

# Tipos de conteúdo da Helena que não são mensagem do lead para a IA.
TIPOS_SEM_CONVERSA = {"REACTION", "REVOKED", "REVOKE", "DELETED", "EDITED", "CALL", "CALL_LOG", "POLL_UPDATE",
                      "SYSTEM", "NOTIFICATION", "E2E_NOTIFICATION", "PROTOCOL"}
SUFIXOS_DE_GRUPO = ("@g.us", "@broadcast", "@newsletter", "@lid-group")


@dataclass
class Regras:
    atraso_maximo_min: float = 30
    numeros_bloqueados: set[str] = field(default_factory=set)
    rajada_mensagens: int = 20
    rajada_segundos: float = 60

    @classmethod
    def de(cls, *configs: dict[str, Any] | None) -> "Regras":
        """Junta as regras do escritório e do agente (o agente vence; bloqueados somam)."""
        regras = cls()
        for config in configs:
            filtro = (config or {}).get("filtro") or {}
            if "atraso_maximo_min" in filtro:
                regras.atraso_maximo_min = float(filtro["atraso_maximo_min"])
            for numero in filtro.get("numeros_bloqueados") or []:
                if normalizado := normalizar_telefone(numero):
                    regras.numeros_bloqueados.add(normalizado)
            rajada = filtro.get("rajada") or {}
            regras.rajada_mensagens = int(rajada.get("mensagens", regras.rajada_mensagens))
            regras.rajada_segundos = float(rajada.get("segundos", regras.rajada_segundos))
        return regras


def _texto(valor: Any) -> str:
    return str(valor or "").lower()


def antes_do_banco(evento: Evento) -> str | None:
    """Motivo para descartar sem gravar nada, ou None. Só olha o próprio webhook."""
    bruto = evento.bruto or {}
    conteudo = bruto.get("content") or {}
    detalhes = conteudo.get("details") or {}
    tipo = str(conteudo.get("type") or "").upper()

    if tipo in TIPOS_SEM_CONVERSA:
        return "sem_conversa:" + tipo.lower()
    contato = " ".join(_texto(x) for x in (detalhes.get("from"), detalhes.get("to"), conteudo.get("chatId"),
                                            (conteudo.get("contact") or {}).get("phonenumber")))
    if any(s in contato for s in SUFIXOS_DE_GRUPO) or detalhes.get("isGroup") or conteudo.get("isGroup") \
            or _texto(conteudo.get("chatType")) in ("group", "grupo", "broadcast"):
        return "grupo_ou_lista"
    if evento.classe == "lead":
        numero = so_digitos(detalhes.get("from"))
        if numero and len(numero) > 15:          # id de grupo/lista que veio sem o sufixo
            return "grupo_ou_lista"
        if not (evento.texto or "").strip() and not (evento.texto_extraido or "").strip() \
                and not evento.url_midia and evento.tipo == "texto":
            return "mensagem_vazia"
    return None


def ddi_aceito(numero: str | None, *configs: dict[str, Any] | None) -> bool:
    """O número do lead começa com um DDI aceito pelo escritório? Sem lista (padrão), aceita todos.

    escritorio.config["filtro"]["ddi_aceitos"] = ["55", "351"]: fora disso o contato é tratado como sem número
    (nota no chat), em vez de virar lead com telefone estranho."""
    aceitos: list[str] = []
    for config in configs:
        aceitos += [so_digitos(d) for d in ((config or {}).get("filtro") or {}).get("ddi_aceitos") or [] if so_digitos(d)]
    if not aceitos or not numero:
        return True
    return any(numero.startswith(d) for d in aceitos)


class ControleDeRajada:
    """Conta mensagens recentes por lead, em memória. Serve para frear robô ou spam, não para cobrar."""

    def __init__(self) -> None:
        self._marcas: dict[str, deque[float]] = {}

    def registrar(self, chave: str, regras: Regras, agora: float | None = None) -> bool:
        """Registra uma mensagem; devolve True se passou do limite na janela."""
        instante = time.monotonic() if agora is None else agora
        fila = self._marcas.setdefault(chave, deque())
        fila.append(instante)
        while fila and instante - fila[0] > regras.rajada_segundos:
            fila.popleft()
        if len(self._marcas) > 50_000:             # não cresce sem limite
            for velha in [k for k, f in self._marcas.items() if not f or instante - f[-1] > regras.rajada_segundos][:10_000]:
                del self._marcas[velha]
        return len(fila) > regras.rajada_mensagens


@dataclass
class Decisao:
    responder: bool                      # agenda o turno da IA
    motivo: str = ""                     # por que não
    pausar_lead: bool = False            # tira a IA da conversa (rajada)
    avisar: str | None = None            # texto de evento para a equipe
    detalhe: str = ""                    # para a nota no chat (ex.: "40 min" de atraso)


def decidir(evento: Evento, regras: Regras, rajada: ControleDeRajada, agora: datetime) -> Decisao:
    """Mensagem do lead já gravada: a IA deve responder?"""
    if evento.numero_lead and evento.numero_lead == evento.numero_canal:
        return Decisao(False, "conversa_consigo_mesmo")
    if evento.numero_lead in regras.numeros_bloqueados:
        return Decisao(False, "numero_bloqueado")
    if evento.enviada_em and agora - evento.enviada_em > timedelta(minutes=regras.atraso_maximo_min):
        atraso = int((agora - evento.enviada_em).total_seconds() // 60)
        return Decisao(False, "mensagem_atrasada", detalhe=f"{atraso} min",
                       avisar=f"Mensagem chegou {atraso} min depois de enviada; a IA não respondeu para não falar fora de hora.")
    if rajada.registrar(f"{evento.numero_canal}:{evento.numero_lead}", regras):
        return Decisao(False, "rajada", pausar_lead=True,
                       avisar=f"Mais de {regras.rajada_mensagens} mensagens em {int(regras.rajada_segundos)} s: "
                              "a IA saiu da conversa por 1 hora (parece robô ou spam).")
    return Decisao(True)
