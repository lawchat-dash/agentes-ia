"""Central de notificações do sino do painel: o que está acontecendo dentro da IA, "pingando" no topo.

  GET  /api/central-notificacoes?desde=&limite=   lista (mais novas primeiro) + quantas não lidas
  POST /api/central-notificacoes/lidas {ate?}     marca como lidas até agora (ou até `ate`)

(/api/notificacoes já é a configuração dos Avisos no WhatsApp; esta é outra coisa: a lista do sino.)

Nada é gravado de novo: as notificações saem das MESMAS fontes dos Avisos no WhatsApp (app/notificacoes.py):
  - lead qualificado       agentesia_lead_etapas, troca para o Closer ("etapa:closer" = Lead qualificado)
  - IA pausada / sinal     agentesia_eventos do turno: pediu_humano, pediu_para_parar, lead_suspeito, analise_manual,
                           trava_persistente, pedido_repetido, fora_do_tema_repetido e sinal_* (o lead sinalizou algo)
  - IA desligada à mão     agentesia_alteracoes 'desligou_ia' (app/ia_controle.mudar_ia); a do próprio usuário não entra
  - contrato               agentesia_contratos: gerado_em (enviado) e lead_assinou_em/assinado_em (assinado)
Erros técnicos (agentesia_eventos de erro, responsável LawChat) NUNCA entram aqui: eles ficam na tela de erros da
equipe LawChat. Toda consulta filtra o escritório da sessão (ctx.escritorio()) e confere que o lead é desse mesmo
escritório (join por id e id_escritorio). O "lido" é a data da última leitura do usuário naquele escritório
(agentesia_notificacoes_leitura, migração 015); quem nunca leu tem como lidas as de mais de 24 h.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from app.gestao.rotas import TODOS, Contexto, _repo
from app.notificacoes import NOMES_DE_EVENTO

api = APIRouter(prefix="/api/central-notificacoes")

JANELA_DIAS = 7                 # a lista mostra a última semana
NUNCA_LEU_H = 24                # sem leitura gravada: só as últimas 24 h contam como novas
LIMITE_PADRAO = 30

PAUSAS = {
    "pediu_humano": "IA pausada: o lead pediu um atendente",
    "pediu_para_parar": "IA saiu da conversa: o lead pediu para parar",
    "lead_suspeito": "IA pausada: lead suspeito (robô, repetição ou só figurinhas)",
    "analise_manual": "IA pausada: caso para a equipe analisar",
    "trava_persistente": "IA pausada: a conversa precisa da equipe",
    "pedido_repetido": "IA pausada: o lead repetiu o mesmo pedido",
    "fora_do_tema_repetido": "IA pausada: conversa fora do tema",
}

_SQL = """
with itens as (
  select 'q:' || le.id::text as chave, 'lead_qualificado' as tipo, le.criado_em as momento, l.id as id_lead,
         c.nome, a.nome as extra
    from agentesia_lead_etapas le
    join agentesia_leads l on l.id = le.id_lead and l.id_escritorio = le.id_escritorio
    join agentesia_contatos c on c.id = l.id_contato
    left join agentesia_agentes a on a.id = l.id_agente
   where le.id_escritorio = $1::uuid and le.etapa_para = 'closer' and le.etapa_de is distinct from 'closer'
     and le.criado_em >= $2
  union all
  select 'e:' || ev.id::text, ev.tipo, ev.criado_em, l.id, c.nome, a.nome
    from agentesia_eventos ev
    join agentesia_leads l on l.id = ev.id_lead and l.id_escritorio = ev.id_escritorio
    join agentesia_contatos c on c.id = l.id_contato
    left join agentesia_agentes a on a.id = l.id_agente
   where ev.id_escritorio = $1::uuid and ev.criado_em >= $2
     and (ev.tipo = any($3::text[]) or (ev.tipo like 'sinal\\_%' and ev.tipo <> 'sinal_recusado'))
  union all
  select 'd:' || al.id::text, 'ia_desativada', al.criado_em, l.id, c.nome, u.nome
    from agentesia_alteracoes al
    join agentesia_leads l on l.id_escritorio = al.id_escritorio
     and l.id::text = coalesce(al.id_registro::text, al.depois -> 'leads' ->> 0)
    join agentesia_contatos c on c.id = l.id_contato
    left join agentesia_usuarios u on u.id = al.id_usuario
   where al.id_escritorio = $1::uuid and al.acao = 'desligou_ia' and al.tabela = 'agentesia_leads'
     and al.criado_em >= $2 and al.id_usuario is distinct from $4::uuid
  union all
  select 'g:' || k.id::text, 'contrato_enviado', k.gerado_em, l.id, c.nome, a.nome
    from agentesia_contratos k
    join agentesia_leads l on l.id = k.id_lead and l.id_escritorio = k.id_escritorio
    join agentesia_contatos c on c.id = l.id_contato
    left join agentesia_agentes a on a.id = l.id_agente
   where k.id_escritorio = $1::uuid and k.gerado_em >= $2
  union all
  select 's:' || k.id::text, 'contrato_assinado', coalesce(k.lead_assinou_em, k.assinado_em), l.id, c.nome, a.nome
    from agentesia_contratos k
    join agentesia_leads l on l.id = k.id_lead and l.id_escritorio = k.id_escritorio
    join agentesia_contatos c on c.id = l.id_contato
    left join agentesia_agentes a on a.id = l.id_agente
   where k.id_escritorio = $1::uuid and coalesce(k.lead_assinou_em, k.assinado_em) >= $2
)
"""


def _grupo(tipo: str) -> str:
    if tipo == "lead_qualificado":
        return "qualificado"
    if tipo.startswith("contrato_"):
        return "contrato"
    if tipo.startswith("sinal_"):
        return "sinal"
    return "pausa"


def _texto(tipo: str, nome: str, extra: str | None) -> tuple[str, str]:
    """(título, detalhe) em português simples. O detalhe leva o nome do lead e, quando há, o agente."""
    agente = f" · {extra}" if extra else ""
    if tipo == "lead_qualificado":
        return f"Lead qualificado: {nome}", (extra or "Passou para a proposta")
    if tipo == "contrato_enviado":
        return f"Contrato de honorários enviado para {nome}", (extra or "Aguardando assinatura")
    if tipo == "contrato_assinado":
        return f"Contrato assinado por {nome}", (extra or "Contrato de honorários")
    if tipo == "ia_desativada":
        return "IA desativada em uma conversa", f"{nome} · por {extra}" if extra else f"{nome} · pela equipe"
    if tipo.startswith("sinal_"):
        sinal = tipo.removeprefix("sinal_")
        return NOMES_DE_EVENTO.get(f"sinal:{sinal}", "O lead sinalizou algo para a equipe"), nome + agente
    return PAUSAS.get(tipo, "IA pausada em uma conversa"), nome + agente


def _iso(momento: datetime | None) -> str | None:
    return momento.isoformat() if momento else None


async def _lido_ate(pool: Any, id_usuario: str, id_escritorio: str) -> datetime | None:
    try:
        return await pool.fetchval(
            "select lido_ate from agentesia_notificacoes_leitura where id_usuario = $1::uuid and id_escritorio = $2::uuid",
            id_usuario, id_escritorio)
    except asyncpg.UndefinedTableError:      # migração 015 ainda não aplicada: o sino funciona, só sem guardar o "lido"
        return None


@api.get("")
async def listar(pedido: Request, desde: datetime | None = None, limite: int = Query(LIMITE_PADRAO, ge=1, le=100),
                 ctx: Contexto = Depends(TODOS)) -> dict[str, Any]:
    pool = _repo(pedido).pool
    id_escritorio = ctx.escritorio()
    agora = datetime.now(timezone.utc)
    inicio = agora - timedelta(days=JANELA_DIAS)
    if desde is not None:
        desde = desde if desde.tzinfo else desde.replace(tzinfo=timezone.utc)
        inicio = max(inicio, desde)
    lido = await _lido_ate(pool, ctx.id_usuario, id_escritorio)
    base_nao_lidas = lido or (agora - timedelta(hours=NUNCA_LEU_H))
    params = (id_escritorio, inicio, list(PAUSAS), ctx.id_usuario)
    linhas = await pool.fetch(_SQL + " select * from itens where momento is not null order by momento desc limit $5",
                              *params, limite)
    nao_lidas = await pool.fetchval(
        _SQL + " select count(*)::int from itens where momento > $5", *params, max(base_nao_lidas, inicio))
    itens = []
    for linha in linhas:
        nome = (linha["nome"] or "").strip() or "Lead sem nome"
        titulo, detalhe = _texto(linha["tipo"], nome, linha["extra"])
        itens.append({
            "id": linha["chave"], "tipo": linha["tipo"], "grupo": _grupo(linha["tipo"]),
            "titulo": titulo, "detalhe": detalhe, "nome": nome, "momento": _iso(linha["momento"]),
            "id_lead": str(linha["id_lead"]), "lida": linha["momento"] <= base_nao_lidas,
        })
    return {"itens": itens, "nao_lidas": nao_lidas or 0, "lido_ate": _iso(lido), "agora": _iso(agora)}


class Lidas(BaseModel):
    ate: datetime | None = None


@api.post("/lidas")
async def marcar_lidas(pedido: Request, dados: Lidas | None = None, ctx: Contexto = Depends(TODOS)) -> dict[str, Any]:
    """Marca tudo como lido até agora (ou até `ate`, se vier e não for no futuro). A data só anda para a frente."""
    pool = _repo(pedido).pool
    agora = datetime.now(timezone.utc)
    ate = dados.ate if dados and dados.ate else agora
    ate = ate if ate.tzinfo else ate.replace(tzinfo=timezone.utc)
    ate = min(ate, agora)
    lido = await pool.fetchval(
        """insert into agentesia_notificacoes_leitura (id_usuario, id_escritorio, lido_ate)
           values ($1::uuid, $2::uuid, $3)
           on conflict (id_usuario, id_escritorio)
           do update set lido_ate = greatest(agentesia_notificacoes_leitura.lido_ate, excluded.lido_ate)
           returning lido_ate""", ctx.id_usuario, ctx.escritorio(), ate)
    return {"ok": True, "lido_ate": _iso(lido)}
