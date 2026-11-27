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

"Precisa de você" (aba padrão do sino): cada item traz `precisa` = pede ação da pessoa (IA pausada, pediu atendente,
lead suspeito, sinais) e ninguém da equipe respondeu naquela conversa depois do aviso; e `sessao` (o atendimento do
lead na plataforma, para o painel abrir a conversa direto na Central). Além dos itens, `alertas` traz o que não é de
um lead: saldo acabando/acabou (pré-pago) e número em uso desconectado ou sem receber mensagens há 2 dias ou mais
(só para quem gere; o saldo zerado todos veem). Os alertas ficam guardados 60 s por escritório e papel.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from app.gestao.cache_curto import CacheCurto
from app.gestao.rotas import TODOS, Contexto, _repo
from app.notificacoes import NOMES_DE_EVENTO

api = APIRouter(prefix="/api/central-notificacoes")

JANELA_DIAS = 7                 # a lista mostra a última semana
NUNCA_LEU_H = 24                # sem leitura gravada: só as últimas 24 h contam como novas
LIMITE_PADRAO = 30
SALDO_DIAS_AVISO = 7            # avisa quando, no ritmo dos últimos 7 dias, o saldo acaba em até 7 dias
NUMERO_PARADO_H = 48            # número em uso sem receber mensagem de lead há 48 h ou mais
FUSO = "America/Sao_Paulo"

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


# Pedem ação da pessoa (vão para "Precisa de você"); "pediu para parar" e "IA desativada" são só informação.
PEDEM_ACAO = {"pediu_humano", "lead_suspeito", "analise_manual", "trava_persistente", "pedido_repetido",
              "fora_do_tema_repetido"}


def pede_acao(tipo: str) -> bool:
    return tipo in PEDEM_ACAO or tipo.startswith("sinal_")


def _numero_mascarado(numero: str | None) -> str:
    """5511987657788 -> "(11) 9••••-7788" (o número inteiro não precisa aparecer no sino)."""
    d = "".join(ch for ch in str(numero or "") if ch.isdigit())
    if d.startswith("55") and len(d) >= 12:
        d = d[2:]
    if len(d) < 10:
        return "Número de WhatsApp"
    ddd, resto = d[:2], d[2:]
    return f"({ddd}) {resto[0]}{'•' * 4}-{resto[-4:]}"


def _dias_texto(minutos: int) -> str:
    dias = minutos // (60 * 24)
    return f"{dias} dias" if dias >= 2 else f"{minutos // 60} horas"


async def _alerta_saldo(pool: Any, id_escritorio: str, pode_gerir: bool, agora: datetime) -> dict[str, Any] | None:
    from app import cobranca
    from app.cobranca.rotas import _carteira
    if not await cobranca.tem_cobranca(pool):
        return None
    carteira = await _carteira(pool, id_escritorio)
    if carteira.get("modo") != "pre_pago":
        return None
    acao = {"rotulo": "Recarregar", "destino": "/consumo"} if pode_gerir else None
    if carteira["bloqueado"]:
        return {"id": "saldo:acabou", "tipo": "saldo_acabou", "titulo": "O saldo acabou",
                "detalhe": "A IA está pausada e as mensagens novas ficam com a equipe. Recarregue para ela voltar.",
                "momento": agora.isoformat(), "acao": acao}
    if not pode_gerir:
        return None
    gasto = await pool.fetchval(
        """select coalesce(sum(custo_brl), 0)::float8 from agentesia_chamadas_ia
            where id_escritorio = $1::uuid and cobranca <> 'isenta' and criado_em >= now() - interval '7 days'""",
        id_escritorio)
    por_dia = (gasto or 0) / 7
    if por_dia <= 0:
        return None
    dias = carteira["disponivel_brl"] / por_dia
    if dias > SALDO_DIAS_AVISO:
        return None
    from zoneinfo import ZoneInfo
    fim = (agora + timedelta(days=max(0.0, dias))).astimezone(ZoneInfo(FUSO))
    return {"id": "saldo:acabando", "tipo": "saldo_acabando", "titulo": "Saldo acabando",
            "detalhe": f"No ritmo atual o saldo acaba em {fim:%d/%m}. Recarregue para a IA não parar.",
            "momento": agora.isoformat(), "acao": acao}


async def _alertas_numero(pool: Any, id_escritorio: str) -> list[dict[str, Any]]:
    from app.gestao import saude_numero
    dados = await saude_numero.numeros(pool, id_escritorio)
    saida = []
    for c in dados["canais"]:
        if not c.get("id_agente"):
            continue                                   # número sem agente: não atende ninguém, não é problema
        titulo = f"Número {_numero_mascarado(c.get('numero_normalizado'))}"
        acao = {"rotulo": "Ver integração", "destino": "/integracoes"}
        if not c.get("ativo"):
            saida.append({"id": f"numero:{c['id']}:desconectado", "tipo": "numero_desconectado", "titulo": titulo,
                          "detalhe": (f"Está desconectado: o agente {c['nome_agente']} não recebe mensagens."
                                      if c.get("nome_agente") else "Está desconectado e não recebe mensagens."),
                          "momento": dados["agora"], "acao": acao})
            continue
        selo = c.get("selo") or {}
        minutos = selo.get("minutos")
        if selo.get("tipo") == "parado" and minutos is not None and minutos >= NUMERO_PARADO_H * 60:
            saida.append({"id": f"numero:{c['id']}:parado", "tipo": "numero_parado", "titulo": titulo,
                          "detalhe": f"Sem receber mensagens há {_dias_texto(minutos)}. Vale testar a conexão.",
                          "momento": dados["agora"], "acao": acao})
    return saida


_CACHE_ALERTAS = CacheCurto(60)


async def _alertas(pool: Any, id_escritorio: str, pode_gerir: bool) -> list[dict[str, Any]]:
    """Saldo e números. Cada parte que falhar (tabela que ainda não existe, por exemplo) só fica de fora."""
    agora = datetime.now(timezone.utc)
    saida: list[dict[str, Any]] = []
    try:
        saldo = await _alerta_saldo(pool, id_escritorio, pode_gerir, agora)
        if saldo:
            saida.append(saldo)
    except Exception:  # noqa: BLE001  (o sino nunca quebra por causa do alerta)
        pass
    if pode_gerir:
        try:
            saida.extend(await _alertas_numero(pool, id_escritorio))
        except Exception:  # noqa: BLE001
            pass
    return saida


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
    linhas = await pool.fetch(
        _SQL + """ select i.*, l.id_sessao_helena as sessao,
                          (select max(m.enviada_em) from agentesia_mensagens m
                            where m.id_lead = i.id_lead and m.id_escritorio = $1::uuid and m.autor = 'humano') as ultima_equipe
                     from itens i join agentesia_leads l on l.id = i.id_lead
                    where i.momento is not null order by i.momento desc limit $5""",
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
            "sessao": str(linha["sessao"]) if linha["sessao"] else None,
            "precisa": pede_acao(linha["tipo"]) and (linha["ultima_equipe"] is None or linha["ultima_equipe"] < linha["momento"]),
        })
    pode_gerir = ctx.papel != "atendente"
    alertas = await _CACHE_ALERTAS.obter((id(pedido.app), id_escritorio, pode_gerir),
                                         lambda: _alertas(pool, id_escritorio, pode_gerir))
    return {"itens": itens, "nao_lidas": nao_lidas or 0, "lido_ate": _iso(lido), "agora": _iso(agora),
            "alertas": alertas}


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
