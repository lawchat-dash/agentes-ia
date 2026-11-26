"""Números da tela Início (dashboard): série por dia, KPIs, agentes, estados, atividades, UF e consumo.

GET /api/inicio/metricas?dias=30. Tudo sai das tabelas agentesia_* do escritório em uso; nada inventado.
Períodos no horário de Brasília. "Conversa" aqui é um lead (um contato num canal).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from datetime import time as dtime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.gestao.cache_curto import CacheCurto
from app.gestao.rotas import TODOS, Contexto, _repo

api = APIRouter(prefix="/api")

FUSO = "America/Sao_Paulo"
PAPEIS_QUE_VEEM_CONSUMO = ("dono_lawchat", "admin_lawchat", "gestor")

# DDD -> UF (Anatel). O telefone do contato fica como 55 + DDD + número.
_DDD_UF: dict[str, str] = {}
for _uf, _ddds in {
    "sp": "11 12 13 14 15 16 17 18 19", "rj": "21 22 24", "es": "27 28", "mg": "31 32 33 34 35 37 38",
    "pr": "41 42 43 44 45 46", "sc": "47 48 49", "rs": "51 53 54 55", "df": "61", "go": "62 64", "to": "63",
    "mt": "65 66", "ms": "67", "ac": "68", "ro": "69", "ba": "71 73 74 75 77", "se": "79", "pe": "81 87",
    "al": "82", "pb": "83", "rn": "84", "ce": "85 88", "pi": "86 89", "pa": "91 93 94", "am": "92 97",
    "rr": "95", "ap": "96", "ma": "98 99",
}.items():
    for _ddd in _ddds.split():
        _DDD_UF[_ddd] = _uf


def uf_do_telefone(telefone: str | None) -> str | None:
    """UF pelo DDD. Aceita com ou sem o 55 na frente; devolve None se não der para saber."""
    digitos = "".join(c for c in (telefone or "") if c.isdigit())
    if digitos.startswith("55") and len(digitos) >= 12:
        digitos = digitos[2:]
    if len(digitos) < 10:
        return None
    return _DDD_UF.get(digitos[:2])


def variacao(atual: float, anterior: float) -> int | None:
    """Variação percentual inteira; sem base (anterior 0) não há variação."""
    if not anterior:
        return None
    return round((atual - anterior) / anterior * 100)


# Quem volta ao Início (ou recarrega) dentro de METRICAS_CACHE_S recebe a mesma resposta, sem ir ao banco de novo; uma
# escrita no painel apaga a cópia (app/gestao/cache_curto.py). A chave inclui escritório, período e papel (o atendente
# não vê consumo).
METRICAS_CACHE_S = 20.0
_METRICAS_CACHE = CacheCurto(METRICAS_CACHE_S)


@api.get("/inicio/metricas")
async def metricas(pedido: Request, dias: int = 30, ctx: Contexto = Depends(TODOS)) -> dict[str, Any]:
    chave = (id(pedido.app), ctx.escritorio(), max(1, min(int(dias), 365)), ctx.papel)
    return await _METRICAS_CACHE.obter(chave, lambda: _calcular_metricas(pedido, dias, ctx))


# Brasília não tem horário de verão desde 2019: UTC-3 fixo (os limites do período saem daqui, sem ida ao banco).
_BRASILIA = timezone(timedelta(hours=-3))


def _por_dia(tabela: str, coluna: str, valores: str = "count(*)::bigint as n") -> str:
    return (f"select to_char({coluna} at time zone '{FUSO}', 'YYYY-MM-DD') as dia, {valores} "
            f"from {tabela} where id_escritorio = $1::uuid and {coluna} >= $2 group by 1")


def _lista(sql: str) -> str:
    return f"(select coalesce(json_agg(t), '[]'::json) from ({sql}) t)"


def _um(sql: str) -> str:
    return f"(select row_to_json(t) from ({sql}) t)"


# Todos os números do Início numa consulta só (cada parte vira uma coluna JSON): antes eram 12 consultas em sequência,
# e com o banco em us-west-2 cada ida custa ~200 ms. Parâmetros: $1 escritório, $2 início do período, $3 início do
# período anterior, $4 hoje 00:00 e $5 ontem 00:00 (Brasília).
_SQL_METRICAS = "select " + ",\n".join([
    _lista(_por_dia("agentesia_leads", "criado_em")) + " as leads_dia",
    _lista(_por_dia("agentesia_mensagens", "enviada_em")) + " as msgs_dia",
    _lista(_por_dia("agentesia_chamadas_ia", "criado_em",
                    "sum(tokens_entrada + tokens_saida)::bigint as tokens, sum(custo_usd)::float8 as custo")) + " as ia_dia",
    _um("""select
             (select count(*) from agentesia_leads where id_escritorio = $1::uuid and criado_em >= $4)::int as conv_hoje,
             (select count(*) from agentesia_leads where id_escritorio = $1::uuid and criado_em >= $5 and criado_em < $4)::int as conv_ontem,
             (select count(*) from agentesia_leads where id_escritorio = $1::uuid and criado_em >= $2)::int as conv,
             (select count(*) from agentesia_leads where id_escritorio = $1::uuid and criado_em >= $3 and criado_em < $2)::int as conv_antes,
             (select count(*) from agentesia_mensagens where id_escritorio = $1::uuid and enviada_em >= $2)::int as msgs,
             (select count(*) from agentesia_mensagens where id_escritorio = $1::uuid and enviada_em >= $3 and enviada_em < $2)::int as msgs_antes,
             (select coalesce(sum(tokens_entrada + tokens_saida), 0) from agentesia_chamadas_ia where id_escritorio = $1::uuid and criado_em >= $2)::bigint as tokens,
             (select coalesce(sum(tokens_entrada + tokens_saida), 0) from agentesia_chamadas_ia where id_escritorio = $1::uuid and criado_em >= $3 and criado_em < $2)::bigint as tokens_antes,
             (select coalesce(sum(custo_usd), 0) from agentesia_chamadas_ia where id_escritorio = $1::uuid and criado_em >= $2)::float8 as custo_usd""") + " as totais",
    _lista("""select a.id, a.nome, a.situacao, a.modo, a.produto,
                  (select count(*) from agentesia_leads l where l.id_agente = a.id and l.criado_em >= $2)::int as conversas,
                  (select count(*) from agentesia_leads l where l.id_agente = a.id and l.criado_em >= $3 and l.criado_em < $2)::int as conversas_antes,
                  (select count(distinct k.id_lead) from agentesia_contratos k join agentesia_leads l on l.id = k.id_lead
                    where l.id_agente = a.id and k.situacao = 'assinado'
                      and coalesce(k.assinado_em, k.concluido_em, k.atualizado_em) >= $2)::int as assinados
           from agentesia_agentes a where a.id_escritorio = $1::uuid
           order by 6 desc, 8 desc, a.criado_em""") + " as agentes",
    _lista("""select estado, count(*)::int as total from agentesia_leads
           where id_escritorio = $1::uuid and (criado_em >= $2 or ultima_mensagem_lead_em >= $2)
           group by 1 order by 2 desc""") + " as estados",
    """(select avg(extract(epoch from (x.ia - x.lead)))::float8 from (
             select (select min(m.enviada_em) from agentesia_mensagens m where m.id_lead = l.id and m.autor = 'lead') as lead,
                    (select min(m.enviada_em) from agentesia_mensagens m where m.id_lead = l.id and m.autor = 'ia') as ia
             from agentesia_leads l where l.id_escritorio = $1::uuid and l.criado_em >= $2) x
           where x.lead is not null and x.ia is not null and x.ia >= x.lead) as resposta""",
    _lista("""select l.id, l.estado, l.motivo_estado, l.criado_em, c.nome, c.telefone_normalizado as telefone,
                  a.id as id_agente, a.nome as agente, e.codigo as etapa,
                  exists (select 1 from agentesia_contratos k where k.id_lead = l.id and k.situacao = 'assinado') as assinado,
                  l.criado_em > now() - interval '24 hours' as recente,
                  greatest(l.atualizado_em, coalesce(l.ultima_mensagem_lead_em, l.criado_em),
                           coalesce(l.ultima_resposta_ia_em, l.criado_em)) as momento
           from agentesia_leads l
           join agentesia_contatos c on c.id = l.id_contato
           left join agentesia_agentes a on a.id = l.id_agente
           left join agentesia_agente_etapas e on e.id = l.id_etapa
           where l.id_escritorio = $1::uuid
           order by momento desc limit 8""") + " as atividades",
    _um("""select count(*) filter (where f.situacao in ('pendente', 'reservado'))::int as pendentes,
                  count(*) filter (where f.situacao = 'enviado' and f.enviado_em >= $2)::int as enviados,
                  count(*) filter (where f.situacao = 'enviado' and f.enviado_em >= $2 and exists (
                    select 1 from agentesia_mensagens m where m.id_lead = f.id_lead and m.autor = 'lead' and m.enviada_em > f.enviado_em))::int as respondidos,
                  count(*) filter (where f.situacao = 'enviado' and f.enviado_em >= $3 and f.enviado_em < $2)::int as enviados_antes,
                  count(*) filter (where f.situacao = 'enviado' and f.enviado_em >= $3 and f.enviado_em < $2 and exists (
                    select 1 from agentesia_mensagens m where m.id_lead = f.id_lead and m.autor = 'lead' and m.enviada_em > f.enviado_em))::int as respondidos_antes
           from agentesia_followups f where f.id_escritorio = $1::uuid""") + " as followup",
    _um("""select count(*) filter (where status = 'ativo')::int as ativos, count(*)::int as total
           from agentesia_produtos_ativados where id_escritorio = $1::uuid and excluido_em is null""") + " as produtos",
    _lista("""select c.telefone_normalizado as telefone, count(*)::int as leads,
                  count(*) filter (where exists (select 1 from agentesia_contratos k where k.id_lead = l.id and k.situacao = 'assinado'))::int as contratos
           from agentesia_leads l join agentesia_contatos c on c.id = l.id_contato
           where l.id_escritorio = $1::uuid and l.criado_em >= $2 and c.telefone_normalizado is not null
           group by 1""") + " as por_ddd",
])


def _json(valor: Any, vazio: Any) -> Any:
    if valor is None:
        return vazio
    return json.loads(valor) if isinstance(valor, str) else valor


async def _calcular_metricas(pedido: Request, dias: int, ctx: Contexto) -> dict[str, Any]:
    import asyncio

    from app import consumo

    repo = _repo(pedido)
    id_escritorio = ctx.escritorio()
    dias = max(1, min(int(dias), 365))
    hoje = datetime.now(_BRASILIA).date()

    def meia_noite(dia: Any) -> datetime:
        return datetime.combine(dia, dtime.min, tzinfo=_BRASILIA)

    inicio, anterior = meia_noite(hoje - timedelta(days=dias - 1)), meia_noite(hoje - timedelta(days=2 * dias - 1))
    ve_consumo = ctx.papel in PAPEIS_QUE_VEEM_CONSUMO
    inicio_mes = consumo.inicio_do_mes()

    async def sem_consumo() -> None:
        return None

    # Três leituras independentes em paralelo: o escritório (limite), os números (uma consulta) e o consumo do mês.
    escritorio, linha, dados_consumo = await asyncio.gather(
        repo.escritorio(id_escritorio),
        repo.pool.fetchrow(_SQL_METRICAS, id_escritorio, inicio, anterior, meia_noite(hoje), meia_noite(hoje - timedelta(days=1))),
        repo.consumo_do_mes(id_escritorio, inicio_mes) if ve_consumo else sem_consumo())
    if not escritorio:
        raise HTTPException(404, "Escritório não encontrado.")

    leads_dia = {r["dia"]: r["n"] for r in _json(linha["leads_dia"], [])}
    msgs_dia = {r["dia"]: r["n"] for r in _json(linha["msgs_dia"], [])}
    ia_dia = {r["dia"]: (r["tokens"], r["custo"]) for r in _json(linha["ia_dia"], [])}
    serie = []
    for i in range(dias):
        dia = (hoje - timedelta(days=dias - 1 - i)).isoformat()
        tokens, custo = ia_dia.get(dia, (0, 0.0))
        serie.append({"date": dia, "conv": int(leads_dia.get(dia, 0)), "msgs": int(msgs_dia.get(dia, 0)),
                      "tokens": int(tokens or 0), "custo_usd": round(float(custo or 0), 4)})
    totais = _json(linha["totais"], {}) or {}
    agentes = _json(linha["agentes"], [])
    estados = _json(linha["estados"], [])
    resposta = linha["resposta"]
    atividades = _json(linha["atividades"], [])
    for item in atividades:
        if item["assinado"]:
            item["tipo"] = "contrato_assinado"
        elif item["estado"] == "encerrado":
            item["tipo"] = "encerrada"
        elif item["estado"] == "pausado":
            item["tipo"] = "pausada"
        elif item["recente"]:
            item["tipo"] = "nova"
        else:
            item["tipo"] = "em_andamento"
    followup = _json(linha["followup"], {}) or {}
    produtos = _json(linha["produtos"], {}) or {}
    por_ddd = _json(linha["por_ddd"], [])

    geo_leads: dict[str, int] = {}
    geo_contratos: dict[str, int] = {}
    for linha in por_ddd:
        uf = uf_do_telefone(linha["telefone"])
        if uf:
            geo_leads[uf] = geo_leads.get(uf, 0) + linha["leads"]
            if linha["contratos"]:
                geo_contratos[uf] = geo_contratos.get(uf, 0) + linha["contratos"]

    # ---------------------------------------------------------- consumo do mês (só quem gere)
    consumo_mes = None
    if ve_consumo and dados_consumo is not None:
        dados = dados_consumo
        config = escritorio.get("config") or {}
        config = config if isinstance(config, dict) else json.loads(config)
        situacao = consumo.avaliar(dados["gasto_usd"], config)
        limite = consumo.config_do_limite(config)
        dias_no_mes = max(1, hoje.day)
        media = situacao.gasto_usd / dias_no_mes
        previsao = None
        if limite["mensal_usd"] and media > 0:
            previsao = max(0, int((limite["mensal_usd"] - situacao.gasto_usd) / media))
        consumo_mes = {"gasto_usd": situacao.gasto_usd, "limite_usd": limite["mensal_usd"], "ao_estourar": limite["ao_estourar"],
                       "percentual": situacao.percentual, "bloqueado": situacao.bloqueado,
                       "media_dia_usd": round(media, 4), "previsao_dias": previsao, "mes": inicio_mes.strftime("%Y-%m")}

    ativos = [a for a in agentes if a["situacao"] == "ativo"]
    enviados = followup.get("enviados") or 0
    enviados_antes = followup.get("enviados_antes") or 0
    taxa = round((followup.get("respondidos") or 0) / enviados * 100) if enviados else None
    taxa_antes = round((followup.get("respondidos_antes") or 0) / enviados_antes * 100) if enviados_antes else None
    return {
        "dias": dias,
        "serie": serie,
        "conversas_hoje": totais.get("conv_hoje", 0),
        "conversas_ontem": totais.get("conv_ontem", 0),
        "conversas_hoje_variacao": variacao(totais.get("conv_hoje", 0), totais.get("conv_ontem", 0)),
        "conversas_periodo": totais.get("conv", 0),
        "conversas_variacao": variacao(totais.get("conv", 0), totais.get("conv_antes", 0)),
        "mensagens": totais.get("msgs", 0),
        "mensagens_variacao": variacao(totais.get("msgs", 0), totais.get("msgs_antes", 0)),
        "tokens": int(totais.get("tokens") or 0),
        "tokens_variacao": variacao(int(totais.get("tokens") or 0), int(totais.get("tokens_antes") or 0)),
        "custo_periodo_usd": round(float(totais.get("custo_usd") or 0), 4),
        "agentes_ativos": len(ativos),
        "agentes_total": len(agentes),
        "ranking_agentes": [{"id": a["id"], "nome": a["nome"], "situacao": a["situacao"], "modo": a["modo"],
                             "conversas": a["conversas"], "assinados": a["assinados"],
                             "variacao": variacao(a["conversas"], a["conversas_antes"])} for a in agentes[:5]],
        "estados": estados,
        "resposta_media_s": round(resposta) if resposta is not None else None,
        "atividades": [{k: item[k] for k in ("id", "tipo", "estado", "motivo_estado", "nome", "telefone",
                                              "id_agente", "agente", "etapa", "momento", "criado_em")} for item in atividades],
        "followup": {"pendentes": followup.get("pendentes", 0), "enviados": enviados,
                     "respondidos": followup.get("respondidos", 0), "taxa_resposta": taxa,
                     "taxa_variacao": (taxa - taxa_antes) if taxa is not None and taxa_antes is not None else None},
        "produtos": {"ativos": produtos.get("ativos", 0), "total": produtos.get("total", 0)},
        "uf": {"leads": geo_leads, "contratos": geo_contratos},
        "consumo": consumo_mes,
    }
