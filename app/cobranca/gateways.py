"""Gateways de pagamento da recarga. Hoje só o MANUAL funciona; o ASAAS está desenhado e não chama API nenhuma.

Fluxo (docs/COBRANCA_TOKENS.md, "Recarga e pagamento"):
  1. o cliente pede a recarga no painel -> agentesia_recargas 'pendente' (gateway escolhido por AGENTESIA_GATEWAY_RECARGA,
     padrão 'manual') e evento 'pedido_recarga' para a LawChat;
  2. o gateway gera a cobrança (Pix/boleto): grava id_externo, link, Pix copia e cola, QR e vencimento na recarga;
  3. o pagamento é confirmado: no manual, o admin clica "Confirmar pagamento"; no Asaas, o webhook PAYMENT_RECEIVED /
     PAYMENT_CONFIRMED chega em POST /api/pagamentos/asaas/webhook com o token no cabeçalho;
  4. agentesia_confirmar_recarga credita no livro UMA vez (repetição do webhook ou clique duplo não credita de novo);
  5. o saldo fica positivo, a carteira sai da pausa e a IA volta sozinha.
"""

from __future__ import annotations

import hmac
import os
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Cobranca:
    """O que o gateway devolve ao criar a cobrança (vai para a linha da recarga)."""
    id_externo: str | None = None
    metodo: str | None = None              # pix, boleto, cartao, manual
    url_pagamento: str | None = None
    pix_copia_cola: str | None = None
    pix_qr_base64: str | None = None
    vencimento: Any = None
    detalhe: dict[str, Any] = field(default_factory=dict)


@dataclass
class EventoPagamento:
    """Webhook traduzido: o que aconteceu com qual cobrança."""
    id_evento: str
    tipo: str                              # paga | cancelada | expirada | estornada | ignorado
    id_externo: str | None
    id_recarga: str | None = None          # externalReference (o id da nossa recarga)
    bruto: str = ""


class Gateway(Protocol):
    nome: str

    async def criar_cobranca(self, recarga: dict[str, Any], escritorio: dict[str, Any]) -> Cobranca: ...

    def webhook_autentico(self, cabecalhos: dict[str, str], corpo: bytes) -> bool: ...

    def ler_webhook(self, corpo: dict[str, Any]) -> EventoPagamento: ...


class GatewayManual:
    """A LawChat recebe por fora (Pix da conta da empresa, boleto avulso) e confirma no painel admin."""

    nome = "manual"

    async def criar_cobranca(self, recarga: dict[str, Any], escritorio: dict[str, Any]) -> Cobranca:
        return Cobranca(metodo="manual", detalhe={"instrucao": "A equipe LawChat envia os dados de pagamento e "
                                                                "confirma a recarga quando o valor cair."})

    def webhook_autentico(self, cabecalhos: dict[str, str], corpo: bytes) -> bool:
        return False                       # manual não recebe webhook

    def ler_webhook(self, corpo: dict[str, Any]) -> EventoPagamento:
        raise NotImplementedError("o gateway manual não tem webhook")


# Eventos do Asaas -> situação da recarga (https://docs.asaas.com, "Eventos para cobranças").
EVENTOS_ASAAS = {
    "PAYMENT_RECEIVED": "paga", "PAYMENT_CONFIRMED": "paga",
    "PAYMENT_OVERDUE": "expirada", "PAYMENT_DELETED": "cancelada",
    "PAYMENT_REFUNDED": "estornada", "PAYMENT_CHARGEBACK_REQUESTED": "estornada",
}


class GatewayAsaas:
    """DESENHADO, NÃO LIGADO. Falta (ver docs): criar o cliente e a cobrança pela API (POST /v3/customers,
    POST /v3/payments com externalReference = id da recarga, GET /v3/payments/{id}/pixQrCode) e cadastrar o webhook no
    Asaas apontando para /api/pagamentos/asaas/webhook com o token de autenticação.

    O Asaas não assina o corpo com HMAC: ele manda o token configurado no webhook no cabeçalho `asaas-access-token`.
    A conferência é em tempo constante contra AGENTESIA_ASAAS_WEBHOOK_TOKEN (sem o token, todo webhook é recusado)."""

    nome = "asaas"

    def __init__(self, token_webhook: str | None = None) -> None:
        self._token = token_webhook if token_webhook is not None else os.environ.get("AGENTESIA_ASAAS_WEBHOOK_TOKEN", "")

    async def criar_cobranca(self, recarga: dict[str, Any], escritorio: dict[str, Any]) -> Cobranca:
        raise NotImplementedError("integração com o Asaas ainda não ligada (só o desenho): use o gateway manual")

    def webhook_autentico(self, cabecalhos: dict[str, str], corpo: bytes) -> bool:
        recebido = {k.lower(): v for k, v in cabecalhos.items()}.get("asaas-access-token", "")
        return bool(self._token) and hmac.compare_digest(recebido.encode(), self._token.encode())

    def ler_webhook(self, corpo: dict[str, Any]) -> EventoPagamento:
        pagamento = corpo.get("payment") or {}
        bruto = str(corpo.get("event") or "")
        return EventoPagamento(
            id_evento=str(corpo.get("id") or f"{bruto}:{pagamento.get('id')}"),
            tipo=EVENTOS_ASAAS.get(bruto, "ignorado"), id_externo=pagamento.get("id"),
            id_recarga=pagamento.get("externalReference"), bruto=bruto)


def gateway(nome: str | None = None) -> Any:
    nome = (nome or os.environ.get("AGENTESIA_GATEWAY_RECARGA") or "manual").strip().lower()
    if nome == "asaas":
        return GatewayAsaas()
    return GatewayManual()


async def processar_evento(pool: Any, nome_gateway: str, evento: EventoPagamento, payload: dict[str, Any]) -> str:
    """Aplica um webhook uma vez só e numa transação: o evento repetido (mesmo id) não é processado de novo, e se o
    crédito falhar o registro do evento também volta (o gateway reenvia e tentamos de novo)."""
    async with pool.acquire() as conexao, conexao.transaction():
        return await _processar(conexao, nome_gateway, evento, payload)


async def _processar(conexao: Any, nome_gateway: str, evento: EventoPagamento, payload: dict[str, Any]) -> str:
    import json

    from app import cobranca

    novo = await conexao.fetchval(
        """insert into agentesia_pagamento_eventos (gateway, id_evento, tipo, id_externo, payload)
           values ($1, $2, $3, $4, $5::jsonb) on conflict (gateway, id_evento) do nothing returning id""",
        nome_gateway, evento.id_evento, evento.bruto, evento.id_externo, json.dumps(payload, ensure_ascii=False, default=str))
    if not novo:
        return "repetido"
    recarga = await conexao.fetchrow(
        """select id, situacao from agentesia_recargas
           where (gateway = $1 and id_externo = $2) or id::text = $3 order by (id_externo = $2) desc nulls last limit 1""",
        nome_gateway, evento.id_externo or "", evento.id_recarga or "")
    if not recarga:
        resultado = "recarga_nao_encontrada"
    elif evento.tipo == "paga":
        await cobranca.confirmar_recarga(conexao, str(recarga["id"]), id_externo=evento.id_externo,
                                         detalhe={"gateway": nome_gateway, "evento": evento.bruto})
        resultado = "creditada"
    elif evento.tipo == "estornada":
        await conexao.fetchval("select agentesia_estornar_recarga($1, null, $2)", recarga["id"], f"{nome_gateway}: {evento.bruto}")
        cobranca.esquecer()
        resultado = "estornada"
    elif evento.tipo in ("cancelada", "expirada"):
        await conexao.execute(
            """update agentesia_recargas set situacao = $2, encerrada_em = now() where id = $1 and situacao = 'pendente'""",
            recarga["id"], evento.tipo)
        resultado = evento.tipo
    else:
        resultado = "ignorado"
    await conexao.execute("update agentesia_pagamento_eventos set id_recarga = $2, resultado = $3 where id = $1",
                          novo, recarga["id"] if recarga else None, resultado)
    return resultado
