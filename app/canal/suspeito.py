"""Lead suspeito: conversa com outro robô, só figurinhas e imagens sem contexto, repetição fora do padrão humano.

A IA é desligada ANTES de gastar (antes de chamar o modelo e antes de transcrever áudio, descrever imagem ou ler PDF).
Tudo aqui é barato e determinístico, sem IA: texto normalizado, difflib, contagens e expressões regulares.

Só dispara com evidência forte nas últimas `janela` mensagens do lead (padrão 6), e nunca antes de `minimo` (padrão 5):
  - repetidas: >= `repetidas` (5) mensagens iguais ou quase iguais (semelhança >= 0,88) com pelo menos `min_letras` (12)
    letras. "ok", "sim", "obrigado" não contam (curtos demais).
  - robo:      >= `robo` (3) mensagens com cara de atendimento automático (menu "digite 1", protocolo de atendimento,
    "mensagem automática", "não entendi sua opção", assistente virtual...).
  - robo (rápido): >= `repetidas - 1` quase iguais + >= 3 respostas instantâneas (<= `instantaneas_s`) + a IA respondeu
    >= 3 vezes na janela sem sair disso.
  - so_midia:  >= `midia` (5) figurinhas / imagens / vídeos sem legenda (ou só com "bom dia"), sem a IA ter pedido
    foto ou documento. Áudio e documento nunca contam (lead de verdade manda vários).
Lead em etapa avançada (fora da etapa inicial) só dispara com repetição LITERAL clara (o mesmo texto >= `repetidas`).

Configuração: AGENTESIA_LEAD_SUSPEITO=0 desliga no servidor inteiro (vence tudo); AGENTESIA_LEAD_SUSPEITO_JANELA muda a
janela padrão. Por escritório ou agente, config["lead_suspeito"] = {"ligado": false} ou os limiares acima
({"janela": 8, "repetidas": 6, ...}); o agente vence o escritório.
"""

from __future__ import annotations

import difflib
import os
import re
import unicodedata
from dataclasses import dataclass, field, fields, replace
from datetime import datetime
from typing import Any, Iterable, Mapping

MOTIVO = "lead_suspeito"                 # motivo_estado do lead e tipo do evento

# Mídia que, sem legenda, não traz contexto nenhum. Áudio e documento ficam de fora de propósito.
MIDIAS_SEM_CONTEXTO = {"figurinha", "imagem", "video"}

# Atendimento automático (URA, chatbot de empresa, resposta automática do WhatsApp Business).
PADROES_DE_ROBO = re.compile("|".join([
    r"\bdigite\s+(?:o\s+)?(?:n[uú]mero\s+)?\d",                       # "Digite 1 para..."
    r"\b(?:tecle|pressione|responda\s+com|envie)\s+(?:o\s+)?\d\b",
    r"(?:^|\n)\s*\*?\d{1,2}\s*[-–.)️⃣]\s*\S.*(?:\n\s*\*?\d{1,2}\s*[-–.)️⃣]\s*\S.*){1,}",  # menu numerado (2+ linhas)
    r"\b(?:op[cç][aã]o|resposta|mensagem)\s+inv[aá]lida\b",
    r"\bn[aã]o\s+(?:entendi|compreendi|reconheci)\s+(?:a\s+|sua\s+)?(?:op[cç][aã]o|resposta|mensagem|escolha)",
    r"\bescolha\s+(?:uma\s+)?(?:das\s+)?op[cç](?:[aã]o|[oõ]es)\b",
    r"\bselecione\s+(?:uma\s+)?(?:das\s+)?op[cç](?:[aã]o|[oõ]es)\b",
    r"\bmensagem\s+autom[aá]tica\b",
    r"\bresposta\s+autom[aá]tica\b",
    r"\b(?:sou|aqui\s+[eé])\s+(?:o|a)\s+(?:assistente|atendente)\s+virtual\b",
    r"\bassistente\s+virtual\b",
    r"\b(?:seu|o)\s+(?:n[uú]mero\s+de\s+)?protocolo\s+(?:de\s+atendimento\s+)?(?:[eé]|:)",
    r"\bprotocolo\s+de\s+atendimento\b",
    r"\bnosso\s+hor[aá]rio\s+de\s+atendimento\b",
    r"\b(?:este|esse)\s+(?:[eé]\s+um\s+)?(?:canal|n[uú]mero)\s+(?:[eé]\s+)?(?:autom[aá]tico|exclusivo\s+para)",
    r"\bn[aã]o\s+(?:respondemos|recebemos)\s+(?:mensagens|liga[cç][oõ]es)\b",
    r"\bpara\s+(?:voltar\s+ao\s+)?menu\s+(?:principal|anterior)\b",
    r"\bvoltar\s+ao\s+menu\b",
    r"\bem\s+breve\s+(?:um\s+de\s+nossos\s+)?(?:atendentes?|consultores?)\s+(?:ir[aá]|v[aã]o|entrar[aá])",
    r"\bagradecemos\s+(?:o\s+seu|o|seu)\s+contato\b",
    r"\bobrigad[oa]\s+por\s+entrar\s+em\s+contato\s+com\s+a\b",
]), re.IGNORECASE)

# Legenda que não é contexto: "bom dia", corrente, bênção.
LEGENDA_VAZIA = re.compile(r"^\W*(?:bom\s+dia|boa\s+tarde|boa\s+noite|feliz\s+\w+|deus\s+\w+|am[eé]m|"
                           r"aben[cç]oad[oa]s?|bjs?|beijos?)\b", re.IGNORECASE)

# A IA pediu foto, print ou documento: imagem sem legenda é o que ela pediu, não figurinha de "bom dia".
PEDIU_ARQUIVO = re.compile(r"\b(?:foto|fotos|imagem|imagens|print|documento|documentos|laudo|laudos|exame|exames|rg|cnh|"
                           r"cnis|comprovante|carteira\s+de\s+trabalho|ctps|receita|atestado|envi[ae]|mand[ae])\b",
                           re.IGNORECASE)


@dataclass(frozen=True)
class Regras:
    ligado: bool = True
    janela: int = 6                  # últimas N mensagens do lead avaliadas
    minimo: int = 5                  # nunca avalia antes disto (nunca na 1ª ou 2ª mensagem)
    repetidas: int = 5               # iguais ou quase iguais na janela
    semelhanca: float = 0.88         # ratio do difflib para "quase igual"
    min_letras: int = 12             # textos mais curtos ("ok", "sim") não contam como repetição
    robo: int = 3                    # mensagens com cara de chatbot/URA
    midia: int = 5                   # figurinhas/imagens sem contexto
    instantaneas_s: float = 3.0      # intervalo que conta como resposta instantânea

    @classmethod
    def de(cls, *configs: Mapping[str, Any] | None, ambiente: Mapping[str, str] | None = None) -> "Regras":
        """Ambiente (padrão do servidor) <- escritório <- agente. AGENTESIA_LEAD_SUSPEITO=0 desliga tudo."""
        ambiente = os.environ if ambiente is None else ambiente
        regras = cls()
        if (janela := _inteiro(ambiente.get("AGENTESIA_LEAD_SUSPEITO_JANELA"))) is not None:
            regras = replace(regras, janela=janela)
        tipos = {f.name: f.type for f in fields(cls)}
        for config in configs:
            ajuste = (config or {}).get(MOTIVO)
            if isinstance(ajuste, bool):
                ajuste = {"ligado": ajuste}
            if not isinstance(ajuste, Mapping):
                continue
            mudancas: dict[str, Any] = {}
            for nome, valor in ajuste.items():
                if nome not in tipos:
                    continue
                try:
                    if nome == "ligado":
                        mudancas[nome] = _ligado(valor)
                    elif nome in ("semelhanca", "instantaneas_s"):
                        mudancas[nome] = float(valor)
                    else:
                        mudancas[nome] = int(valor)
                except (TypeError, ValueError):
                    continue
            regras = replace(regras, **mudancas)
        if not _ligado(ambiente.get("AGENTESIA_LEAD_SUSPEITO", "1")):
            regras = replace(regras, ligado=False)
        return regras.conferidas()

    def conferidas(self) -> "Regras":
        """Limites sãos: ninguém configura um detector que dispara na 2ª mensagem."""
        janela = max(4, min(int(self.janela), 30))
        minimo = max(3, min(int(self.minimo), janela))
        teto = lambda v: max(3, min(int(v), janela))   # noqa: E731
        return replace(self, janela=janela, minimo=minimo, repetidas=teto(self.repetidas), robo=teto(self.robo),
                       midia=teto(self.midia), semelhanca=max(0.7, min(float(self.semelhanca), 1.0)),
                       min_letras=max(6, int(self.min_letras)), instantaneas_s=max(0.0, float(self.instantaneas_s)))


@dataclass
class Veredito:
    motivo: str                       # repetidas | robo | so_midia
    janela: int                       # quantas mensagens do lead foram avaliadas
    contagens: dict[str, Any] = field(default_factory=dict)

    RAZOES = {"repetidas": "mensagens repetidas", "robo": "parece outro robô (menus e respostas automáticas)",
              "so_midia": "só figurinhas e imagens sem contexto"}

    @property
    def razao(self) -> str:
        return self.RAZOES.get(self.motivo, self.motivo)

    def nota(self) -> str:
        """Nota interna para a equipe (nada vai para o lead)."""
        return (f"🚫 IA desativada automaticamente: comportamento suspeito do lead ({self.razao} nas últimas "
                f"{self.janela} mensagens). Revise e religue se for um lead real (tire a etiqueta \"🤖 IA Desativada\" "
                "do contato ou use o painel).")

    def descricao(self) -> str:
        return (f"IA desativada automaticamente: {self.razao} nas últimas {self.janela} mensagens do lead. "
                "Nada foi enviado ao lead; revise e religue se for um lead real.")


def _ligado(valor: Any) -> bool:
    if isinstance(valor, bool):
        return valor
    return str(valor).strip().lower() not in ("0", "false", "nao", "não", "off", "desligado", "")


def _inteiro(valor: Any) -> int | None:
    try:
        return int(str(valor).strip()) if valor not in (None, "") else None
    except ValueError:
        return None


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def literal(texto: str | None) -> str:
    """Para repetição literal: minúsculas, sem acento, espaços colapsados (números e pontuação ficam)."""
    return re.sub(r"\s+", " ", _sem_acento(str(texto or "")).lower()).strip()


def normalizar(texto: str | None) -> str:
    """Para 'quase igual': além do literal, números viram '#' (protocolo muda a cada mensagem) e some a pontuação."""
    base = re.sub(r"\d+", "#", literal(texto))
    return re.sub(r"\s+", " ", re.sub(r"[^\w# ]+", " ", base)).strip()


def _letras(texto: str) -> int:
    return sum(c.isalpha() for c in texto)


def _parecidas(a: str, b: str, limite: float) -> bool:
    if a == b:
        return True
    comparador = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return comparador.real_quick_ratio() >= limite and comparador.quick_ratio() >= limite and comparador.ratio() >= limite


def _maior_grupo(textos: list[str], limite: float) -> int:
    """Tamanho do maior grupo de textos parecidos com um mesmo texto (n <= 30: o quadrático é barato)."""
    melhor = 0
    for i, a in enumerate(textos):
        melhor = max(melhor, sum(1 for j, b in enumerate(textos) if i == j or _parecidas(a, b, limite)))
    return melhor


def sem_contexto(tipo: str | None, texto: str | None) -> bool:
    """Figurinha, ou imagem/vídeo sem legenda (ou com legenda de corrente: 'bom dia', 'Deus abençoe')."""
    tipo = (tipo or "").lower()
    if tipo == "figurinha":
        return True
    if tipo not in MIDIAS_SEM_CONTEXTO:
        return False
    legenda = str(texto or "").strip()
    return _letras(legenda) < 4 or bool(LEGENDA_VAZIA.match(_sem_acento(legenda)))


def parece_robo(texto: str | None) -> bool:
    return bool(texto) and bool(PADROES_DE_ROBO.search(_sem_acento(str(texto))) or PADROES_DE_ROBO.search(str(texto)))


def _campo(mensagem: Any, nome: str) -> Any:
    return mensagem.get(nome) if isinstance(mensagem, Mapping) else getattr(mensagem, nome, None)


def avaliar(mensagens: Iterable[Any], regras: Regras | None = None, *, avancado: bool = False) -> Veredito | None:
    """Função pura. `mensagens`: a conversa recente em ordem (objetos ou dicts com autor, tipo, texto, enviada_em),
    só depois do último disparo/religamento. Só as do lead são avaliadas; as da IA contam respostas sem progresso e
    se ela pediu arquivo. `avancado`: lead fora da etapa inicial (só repetição literal dispara). None = segue normal."""
    regras = (regras or Regras()).conferidas()
    if not regras.ligado:
        return None
    conversa = [m for m in mensagens if _campo(m, "autor") in ("lead", "ia")]
    do_lead = [m for m in conversa if _campo(m, "autor") == "lead"][-regras.janela:]
    if len(do_lead) < regras.minimo:
        return None
    primeira = next(i for i, m in enumerate(conversa) if m is do_lead[0])
    da_ia = [m for m in conversa[primeira:] if _campo(m, "autor") == "ia"]
    anterior_da_ia = next((m for m in reversed(conversa[:primeira]) if _campo(m, "autor") == "ia"), None)

    textos = [str(_campo(m, "texto") or "") for m in do_lead]
    literais = [literal(t) for t in textos if _letras(t) >= regras.min_letras]
    normais = [normalizar(t) for t in textos if _letras(t) >= regras.min_letras]
    iguais = max((literais.count(t) for t in literais), default=0)
    parecidas = _maior_grupo(normais, regras.semelhanca)
    robos = sum(1 for t in textos if parece_robo(t))
    midias = sum(1 for m, t in zip(do_lead, textos) if sem_contexto(_campo(m, "tipo"), t))
    instantes = [_campo(m, "enviada_em") for m in do_lead]
    instantaneas = sum(1 for a, b in zip(instantes, instantes[1:])
                       if isinstance(a, datetime) and isinstance(b, datetime)
                       and 0 <= (b - a).total_seconds() <= regras.instantaneas_s)
    pediu_arquivo = any(PEDIU_ARQUIVO.search(_sem_acento(str(_campo(m, "texto") or "")))
                        for m in [*([anterior_da_ia] if anterior_da_ia is not None else []), *da_ia])
    contagens = {"mensagens": len(do_lead), "iguais": iguais, "quase_iguais": parecidas, "robo": robos,
                 "midia_sem_contexto": midias, "instantaneas": instantaneas, "respostas_da_ia": len(da_ia),
                 "ia_pediu_arquivo": pediu_arquivo, "etapa_avancada": avancado}

    def veredito(motivo: str) -> Veredito:
        return Veredito(motivo=motivo, janela=len(do_lead), contagens=contagens)

    if iguais >= regras.repetidas:
        return veredito("repetidas")             # repetição literal clara: vale até em etapa avançada
    if avancado:
        return None
    if parecidas >= regras.repetidas:
        return veredito("repetidas")
    if robos >= regras.robo:
        return veredito("robo")
    if parecidas >= regras.repetidas - 1 and instantaneas >= 3 and len(da_ia) >= 3:
        return veredito("robo")                  # responde na hora, sempre o mesmo, e a IA não sai do lugar
    if midias >= regras.midia and not pediu_arquivo:
        return veredito("so_midia")
    return None
