"""Central de avisos da equipe LawChat (antigo "ALERTAS - Central de avisos").

A cada minuto lê os eventos graves (erro/crítico) que são da LawChat ou do provedor, e os alertas de cadastro
(canal não cadastrado, etapa sem prompt, card não criado...) de qualquer gravidade, e põe na fila um aviso por
WhatsApp para a equipe. O mesmo problema (tipo, escritório, lead) passa no máximo 1 vez a cada 30 minutos; o de
cadastro é do escritório, então conta 1 por tipo e escritório (sem repetir lead a lead).
O envio sai pela conta da LawChat na Helena.

.env: AGENTESIA_HELENA_TOKEN_LAWCHAT (token da conta LawChat), AGENTESIA_ALERTA_LAWCHAT_DE (número que envia)
      e AGENTESIA_ALERTA_LAWCHAT_PARA (números que recebem, separados por vírgula). Sem eles a central fica desligada.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg

from app.notificacoes import formatar_telefone, fuso, normalizar_numero

JANELA_S = 30 * 60
# Cobrança: pedido de recarga do cliente e saldo esgotado vão para a LawChat qualquer que seja a gravidade.
TIPOS_COMERCIAIS = ("pedido_recarga", "saldo_esgotado")


def configurada() -> dict[str, Any] | None:
    token = os.environ.get("AGENTESIA_HELENA_TOKEN_LAWCHAT", "").strip()
    de = normalizar_numero(os.environ.get("AGENTESIA_ALERTA_LAWCHAT_DE", ""))
    para = [n for n in (normalizar_numero(x) for x in os.environ.get("AGENTESIA_ALERTA_LAWCHAT_PARA", "").split(",")) if n]
    if not (token and de and para):
        return None
    return {"token": token, "de": de, "para": para}


def texto_do_aviso(evento: dict[str, Any]) -> str:
    quando = evento["criado_em"].astimezone(fuso()).strftime("%d/%m %H:%M")
    gravidade = {"critico": "CRÍTICO", "erro": "erro"}.get(evento["gravidade"], evento["gravidade"] or "aviso")
    quem = {"provedor": "provedor", "cadastro": "cadastro"}.get(evento["responsavel"], "LawChat")
    linhas = [f"🚨 *LawChat IA · {gravidade}*",
              f"Escritório: {evento.get('escritorio') or '—'}",
              f"Problema: {evento['tipo']} ({quem})"]
    if evento.get("descricao"):
        linhas.append(str(evento["descricao"])[:500])
    if evento.get("telefone"):
        linhas.append(f"Lead: {formatar_telefone(evento['telefone'])}")
    linhas.append(quando)
    return "\n".join(linhas)


async def varrer(pool: asyncpg.Pool, desde: datetime) -> tuple[int, datetime]:
    """Põe na fila os avisos dos eventos novos desde `desde`. Devolve (quantos, até onde leu)."""
    cfg = configurada()
    eventos = await pool.fetch(
        """select v.id, v.id_escritorio, v.id_lead, v.tipo, v.gravidade, v.responsavel, v.descricao, v.criado_em,
                  e.nome as escritorio, c.telefone_normalizado as telefone
           from agentesia_eventos v join agentesia_escritorios e on e.id = v.id_escritorio
           left join agentesia_leads l on l.id = v.id_lead left join agentesia_contatos c on c.id = l.id_contato
           where v.criado_em > $1
             and ((v.gravidade in ('erro', 'critico') and v.responsavel in ('lawchat', 'provedor')) or v.responsavel = 'cadastro'
                  or v.tipo = any($2::text[]))
           order by v.criado_em limit 500""", desde, list(TIPOS_COMERCIAIS))
    ate = max([e["criado_em"] for e in eventos], default=desde)
    if not cfg or not eventos:
        return 0, ate
    novos = 0
    for evento in eventos:
        janela = int(evento["criado_em"].timestamp() // JANELA_S)
        lead = "-" if evento["responsavel"] == "cadastro" else (evento["id_lead"] or "-")    # cadastro: 1 por escritório
        chave = f"lawchat:{evento['tipo']}:{evento['id_escritorio']}:{lead}:{janela}"
        feito = await pool.fetchval(
            """insert into agentesia_acoes (id_escritorio, id_lead, tipo, chave_unica, dados)
               values ($1, $2, 'alertar_lawchat', $3, $4::jsonb) on conflict (chave_unica) do nothing returning true""",
            evento["id_escritorio"], evento["id_lead"], chave,
            json.dumps({"texto": texto_do_aviso(dict(evento)), "id_evento": str(evento["id"])}, ensure_ascii=False))
        novos += bool(feito)
    return novos, ate


def inicio_padrao() -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=10)
