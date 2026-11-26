"""Follow-up: configuração e agenda (funções puras, sem banco).

Configuração em agentesia_agentes.config["followup"], editável no painel:
    {
      "ativo": true,
      "horario": {"inicio": 8, "fim": 20, "dias": [0, 1, 2, 3, 4, 5]},     # seg=0 ... dom=6; fuso de Brasília
      "intervalo_minimo_min": 30,
      "etapas": ["sdr", "closer", ...],                                    # vazio = todas as de conversa
      "prompt": "tom e regras gerais da mensagem de retomada",
      "por_etapa": {"closer": "lembre dos honorários combinados"},
      "passos": [{"apos_horas": 1, "modo": "ia", "instrucao": "..."},     # modo: ia | texto | modelo
                 {"apos_horas": 24, "modo": "texto", "texto": "Oi {nome}! ..."}, ...],
      "modelo_oficial": {"id_modelo": "...", "nome": "..."},              # canal oficial com janela de 24 h fechada
      "desistir": {"ativo": true, "apos_horas": 24, "nota": "..."}
    }
Os tempos contam a partir da última resposta da IA (o momento em que o lead parou de responder).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.notificacoes import fuso

# Cadência do sistema atual (GERAL - Follow Up Unificado): 1h, 5h, 24h, 72h, 7, 15 e 30 dias.
CADENCIA_PADRAO = (1, 5, 24, 72, 168, 360, 720)

PROMPT_PADRAO = """Você está retomando uma conversa de WhatsApp com uma pessoa que parou de responder.
- Escreva como a mesma atendente da conversa: curto, gentil, natural, sem pressão.
- Retome pelo último assunto (o que faltou responder ou decidir), sem repetir a última mensagem.
- Uma pergunta simples no fim, fácil de responder.
- Não prometa resultado, prazo ou valor. Não mande link. Não diga que é mensagem automática.
- Nas últimas tentativas, diga que fica à disposição quando a pessoa puder."""

INSTRUCAO_PASSO_PADRAO = {
    0: "Primeira retomada: lembre com leveza onde a conversa parou.",
    1: "Segunda retomada: pergunte se ficou alguma dúvida.",
    2: "Mostre que o caso dela importa e que dá para seguir quando ela puder.",
    3: "Seja breve: pergunte se ainda tem interesse em seguir.",
}

# Nunca recebem follow-up, nem listadas em config.etapas: o lead que ouviu que não tem direito não recebe "ainda tem
# interesse?" e quem já assinou não recebe cobrança de resposta (como ETAPAS_SEM_FOLLOW do Weaver).
ETAPAS_SEM_FOLLOWUP = frozenset({"desqualificado", "contrato_assinado"})

NOTA_DESISTENCIA = "Lead não respondeu aos follow-ups. A IA encerrou a conversa; a equipe pode retomar quando quiser."


@dataclass
class Passo:
    apos_horas: float
    modo: str = "ia"                     # ia | texto | modelo
    instrucao: str = ""
    texto: str = ""


@dataclass
class Config:
    ativo: bool = False
    inicio: int = 8
    fim: int = 20
    dias: tuple[int, ...] = (0, 1, 2, 3, 4, 5)
    intervalo_minimo_min: int = 30
    etapas: tuple[str, ...] = ()
    prompt: str = PROMPT_PADRAO
    por_etapa: dict[str, str] = field(default_factory=dict)
    passos: list[Passo] = field(default_factory=lambda: [Passo(h) for h in CADENCIA_PADRAO])
    modelo_oficial: dict[str, Any] = field(default_factory=dict)
    desistir_ativo: bool = False
    desistir_apos_horas: float = 24
    desistir_nota: str = NOTA_DESISTENCIA
    modelo: str | None = None            # modelo de IA do agente de follow-up (vazio = padrão do servidor)

    @classmethod
    def de(cls, bruto: dict[str, Any] | None) -> "Config":
        b = bruto or {}
        horario = b.get("horario") or {}
        desistir = b.get("desistir") or {}
        passos = [Passo(float(p.get("apos_horas") or 1), str(p.get("modo") or "ia"), str(p.get("instrucao") or ""),
                        str(p.get("texto") or "")) for p in b.get("passos") or [] if isinstance(p, dict)]
        return cls(
            ativo=bool(b.get("ativo")), inicio=int(horario.get("inicio", 8)), fim=int(horario.get("fim", 20)),
            dias=tuple(int(d) for d in horario.get("dias", (0, 1, 2, 3, 4, 5))),
            intervalo_minimo_min=int(b.get("intervalo_minimo_min", 30)), etapas=tuple(b.get("etapas") or ()),
            prompt=str(b.get("prompt") or PROMPT_PADRAO), por_etapa=dict(b.get("por_etapa") or {}),
            passos=sorted(passos, key=lambda p: p.apos_horas) or [Passo(h) for h in CADENCIA_PADRAO],
            modelo_oficial=dict(b.get("modelo_oficial") or {}),
            desistir_ativo=bool(desistir.get("ativo")), desistir_apos_horas=float(desistir.get("apos_horas", 24)),
            desistir_nota=str(desistir.get("nota") or NOTA_DESISTENCIA),
            modelo=str(b.get("modelo") or "") or None,
        )

    def vale_para(self, etapa: str | None, etapas_de_conversa: set[str]) -> bool:
        if not etapa or etapa in ETAPAS_SEM_FOLLOWUP:
            return False
        return etapa in self.etapas if self.etapas else etapa in etapas_de_conversa


def validar(bruto: dict[str, Any]) -> dict[str, Any]:
    """Limpa a configuração vinda do painel. Erro de uso vira ValueError com mensagem para a tela."""
    horario = bruto.get("horario") or {}
    inicio, fim = int(horario.get("inicio", 8)), int(horario.get("fim", 20))
    if not (0 <= inicio < fim <= 24):
        raise ValueError("Horário inválido: o início tem de ser antes do fim (0 a 24 h).")
    dias = sorted({int(d) for d in horario.get("dias", [0, 1, 2, 3, 4, 5]) if 0 <= int(d) <= 6})
    if not dias:
        raise ValueError("Escolha pelo menos um dia da semana.")
    passos = []
    for p in bruto.get("passos") or []:
        horas = float(p.get("apos_horas") or 0)
        if not 10 / 60 - 1e-9 <= horas <= 24 * 90:
            raise ValueError("Cada passo precisa de um tempo entre 10 minutos e 90 dias.")
        modo = p.get("modo") if p.get("modo") in ("ia", "texto", "modelo") else "ia"
        texto = str(p.get("texto") or "").strip()[:1000]
        if modo == "texto" and not texto:
            raise ValueError("Passo com texto fixo precisa do texto.")
        passos.append({"apos_horas": horas, "modo": modo, "instrucao": str(p.get("instrucao") or "").strip()[:1500], "texto": texto})
    if len(passos) > 12:
        raise ValueError("No máximo 12 passos de follow-up.")
    horas = [p["apos_horas"] for p in passos]
    if len(set(horas)) != len(horas):
        raise ValueError("Dois passos com o mesmo tempo: ajuste a cadência.")
    desistir = bruto.get("desistir") or {}
    return {
        "ativo": bool(bruto.get("ativo")), "horario": {"inicio": inicio, "fim": fim, "dias": dias},
        "intervalo_minimo_min": max(5, min(1440, int(bruto.get("intervalo_minimo_min", 30)))),
        "etapas": [str(e) for e in bruto.get("etapas") or []],
        "prompt": str(bruto.get("prompt") or "").strip()[:4000] or PROMPT_PADRAO,
        "por_etapa": {str(k): str(v).strip()[:1500] for k, v in (bruto.get("por_etapa") or {}).items() if str(v).strip()},
        "passos": sorted(passos, key=lambda p: p["apos_horas"]) or [{"apos_horas": h, "modo": "ia", "instrucao": "", "texto": ""} for h in CADENCIA_PADRAO],
        "modelo_oficial": {k: str(v) for k, v in (bruto.get("modelo_oficial") or {}).items() if k in ("id_modelo", "nome") and v},
        "modelo": str(bruto.get("modelo") or "").strip()[:60] or None,
        "desistir": {"ativo": bool(desistir.get("ativo")), "apos_horas": max(1.0, float(desistir.get("apos_horas", 24))),
                     "nota": str(desistir.get("nota") or "").strip()[:500] or NOTA_DESISTENCIA},
    }


def ajustar_ao_horario(momento: datetime, config: Config, semente: str = "") -> datetime:
    """Leva o horário para dentro do expediente. Fora dele, vai para a próxima abertura com alguns minutos de
    espalhamento (pela semente), para não mandar tudo no mesmo segundo."""
    local = fuso()
    atual = momento.astimezone(local)
    for _ in range(15):
        dentro_do_dia = atual.weekday() in config.dias
        if dentro_do_dia and config.inicio <= atual.hour < config.fim:
            return atual
        if dentro_do_dia and atual.hour < config.inicio:
            abertura = atual.replace(hour=config.inicio, minute=0, second=0, microsecond=0)
        else:
            abertura = (atual + timedelta(days=1)).replace(hour=config.inicio, minute=0, second=0, microsecond=0)
            if abertura.weekday() not in config.dias:
                atual = abertura
                continue
        espalhar = int(hashlib.sha256(semente.encode()).hexdigest()[:6], 16) % 40 if semente else 0
        atual = abertura + timedelta(minutes=espalhar)
        if atual.weekday() in config.dias and config.inicio <= atual.hour < config.fim:
            return atual
    return atual


def horario_do_passo(base: datetime, passo: int, config: Config, semente: str = "") -> datetime | None:
    """Quando sai o passo (0, 1, ...). None se acabaram os passos."""
    if passo >= len(config.passos):
        return None
    return ajustar_ao_horario(base + timedelta(hours=config.passos[passo].apos_horas), config, f"{semente}:{passo}")


def preencher(texto: str, *, nome: str | None) -> str:
    primeiro = (nome or "").strip().split(" ")[0] if nome else ""
    return texto.replace("{nome}", primeiro).replace("  ", " ").replace(" !", "!").replace(" ,", ",").strip()
