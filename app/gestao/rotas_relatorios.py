"""Relatórios do painel: Dashboard e Rastreamento de campanhas (menu Relatórios). Quem gere o escritório vê.

  GET  /api/relatorios/filtros                     agentes, campanhas e plataformas do escritório (para os filtros)
  GET  /api/relatorios/dashboard                   indicadores, funil, série por dia, IA (respostas, tempo, custo),
                                                   agentes, etapas atuais, mapa por UF, horários e o espelho do CRM
  GET  /api/relatorios/campanhas                   por campanha, anúncio e plataforma: leads, avanço por etapa,
                                                   contratos, conversão, tempo até assinar, custo da IA, ranking,
                                                   alertas e teste A/B automático
  GET  /api/relatorios/campanhas/anuncio/{chave}   detalhe de um anúncio (série, etapas e os leads dele)
  POST /api/relatorios/crm/importar                pede a importação completa dos cards do CRM (roda em segundo plano)

Filtros comuns (query): de, ate (AAAA-MM-DD, horário de Brasília; padrão: últimos 30 dias), agente (id), campanha
(texto exato), fonte (plataforma: instagram, facebook, google, youtube, tiktok, outro, direto).

De onde vem cada número: só das nossas tabelas (nada de chamada externa ao abrir a tela).
  agentesia_leads + agentesia_contatos + agentesia_agente_etapas   o lead, a etapa atual, a origem (UTM/anúncio)
  agentesia_lead_etapas                                            por quais etapas o lead já passou
  agentesia_contratos                                              contrato gerado e assinado (data da assinatura)
  agentesia_turnos / agentesia_mensagens / agentesia_chamadas_ia   respostas, tempos e custo da IA
  agentesia_crm_espelho / agentesia_crm_varredura (migração 012)   cards do CRM, inclusive os antigos

O grupo de leads é a "safra" do período: os leads que ENTRARAM entre de e ate; o funil conta até onde cada um já foi
(a etapa mais adiante que alcançou, hoje). Os números da IA (respostas, turnos, custo) são do que aconteceu no período.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from datetime import time as dtime
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request

from app.gestao.cache_curto import CacheCurto
from app.gestao.metricas import uf_do_telefone, variacao
from app.gestao.rotas import GESTAO, Contexto, _repo
from app.gestao.rotas_execucoes import _nomes_por_agente, mascarar_telefone

api = APIRouter(prefix="/api/relatorios")

FUSO = "America/Sao_Paulo"
_BRASILIA = timezone(timedelta(hours=-3))           # sem horário de verão desde 2019
MAX_DIAS = 400
UUID = re.compile(r"[0-9a-fA-F-]{36}")

# Funil canônico (as etapas do agente de cada produto caem numa destas fases pelo código; ver _FASE).
FUNIL = [("sdr", "SDR"), ("closer", "Closer"), ("contratos", "Contratos"), ("assinatura", "Assinatura"),
         ("assinado", "Contrato assinado")]
NOMES_FASE = dict(FUNIL) | {"desqualificado": "Desqualificado", "analise": "Análise da equipe",
                            "nao_assinou": "Não assinou", "outra": "Outra etapa", "sem_etapa": "Sem etapa"}
PLATAFORMAS = {"instagram": "Instagram", "facebook": "Facebook / Meta", "google": "Google", "youtube": "YouTube",
               "tiktok": "TikTok", "outro": "Outra origem", "direto": "Sem origem (direto)"}

_CACHE = CacheCurto(30.0, maximo=300)


# ------------------------------------------------------------------ SQL reaproveitado
def _normal(coluna: str) -> str:
    return f"regexp_replace(lower(coalesce({coluna}, '')), '[^a-z]', '', 'g')"


_CODIGOS_FASE = {
    "sdr": ("sdr", "periododegraca", "periodograca", "triagem", "primeiroatendimento"),
    "closer": ("closer", "comercial", "qualificado", "proposta"),
    "analise": ("analisemanual", "analise"),
    "contratos": ("contratos", "contrato", "coletadados", "coletadedados", "dadosdocontrato"),
    "assinatura": ("assinatura", "acompanhamentoassinatura", "aguardandoassinatura"),
    "assinado": ("contratoassinado", "assinado"),
    "desqualificado": ("desqualificado", "foradoperfil", "encerramento"),
}
NIVEL = {"sdr": 1, "closer": 2, "analise": 2, "contratos": 3, "assinatura": 4, "assinado": 5}


def _fase(coluna: str) -> str:
    """Código da etapa (sdr, periodo_graca, coleta_dados...) -> fase canônica; null quando não é nenhuma conhecida."""
    casos = " ".join(f"when {_normal(coluna)} in ({', '.join(repr(c) for c in codigos)}) then '{fase}'"
                     for fase, codigos in _CODIGOS_FASE.items())
    return f"(case {casos} else null end)"


def _nivel(expr_fase: str) -> str:
    casos = " ".join(f"when '{f}' then {n}" for f, n in NIVEL.items())
    return f"(case {expr_fase} {casos} else 0 end)"


def fase_do_titulo(titulo: str | None) -> str:
    """Nome de coluna do CRM -> fase (mesma regra do dashboard antigo: SDR, Closer, Contrato assinado, Não assinou...)."""
    import unicodedata
    t = unicodedata.normalize("NFKD", titulo or "").encode("ascii", "ignore").decode().upper()
    t = re.sub(r"[^A-Z ]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if not t:
        return "outra"
    if "SDR" in t or "PERIODO DE GRACA" in t or "TRIAGEM" in t:
        return "sdr"
    if "CLOSER" in t:
        return "closer"
    if "CONTRATO FECHADO" in t or "CONTRATO ASSINADO" in t or t == "ASSINADO":
        return "assinado"
    if "NAO ASSINOU" in t or "NAO SEGUIU" in t:
        return "nao_assinou"
    if "ASSINATURA" in t:
        return "assinatura"
    if "CONTRATO" in t or "ELABORA" in t or "CONFECCAO" in t:
        return "contratos"
    if "DESQUALIFICADO" in t or "DESCARTADO" in t or "NAO TEM INTERESSE" in t:
        return "desqualificado"
    if "COMERCIAL" in t:
        return "closer"
    if "ANALISE" in t:
        return "analise"
    return "outra"


# Plataforma a partir da origem do lead (fonte, meio e link do anúncio). Clique para WhatsApp sem fonte = Meta.
_TEXTO_ORIGEM = ("lower(coalesce(l.origem->>'fonte', '') || ' ' || coalesce(l.origem->>'meio', '') || ' ' || "
                 "coalesce(l.origem->>'url', ''))")
PLATAFORMA_SQL = f"""(case
  when l.origem is null or l.origem = '{{}}'::jsonb then 'direto'
  when {_TEXTO_ORIGEM} ~ 'instagram|(^|[^a-z])ig([^a-z]|$)' then 'instagram'
  when {_TEXTO_ORIGEM} ~ 'facebook|(^|[^a-z])fb([^a-z]|$)|fb\\.|meta' then 'facebook'
  when {_TEXTO_ORIGEM} ~ 'google|gclid|adwords' then 'google'
  when {_TEXTO_ORIGEM} ~ 'youtube|youtu\\.be' then 'youtube'
  when {_TEXTO_ORIGEM} ~ 'tiktok' then 'tiktok'
  when l.origem->>'origem' = 'anuncio' or coalesce(l.origem->>'clid', '') <> '' then 'facebook'
  else 'outro' end)"""
CAMPANHA_SQL = "coalesce(nullif(btrim(l.origem->>'campanha'), ''), '(sem campanha)')"
_IDENT_ANUNCIO = ("coalesce(nullif(btrim(l.origem->>'id_anuncio'), ''), nullif(btrim(l.origem->>'titulo'), ''), "
                  "nullif(btrim(l.origem->>'conteudo'), ''), nullif(btrim(l.origem->>'url'), ''), '')")
CHAVE_ANUNCIO_SQL = f"left(md5({CAMPANHA_SQL} || '|' || {_IDENT_ANUNCIO}), 16)"


def _lead_sql(onde: str, extra: str = "") -> str:
    """CTEs ld (lead do período + filtros), b (histórico e contrato) e n (fase, nível alcançado, assinatura)."""
    passou_assinado = (f"(select min(h.criado_em) from agentesia_lead_etapas h where h.id_lead = l.id "
                       f"and {_fase('h.etapa_para')} = 'assinado')")
    return f"""with b as materialized (
  select l.id, l.criado_em, l.atualizado_em, l.estado, l.motivo_estado, l.id_agente, l.origem,
         ct.telefone_normalizado as tel, e.codigo as etapa, {_fase('e.codigo')} as fase_atual,
         {PLATAFORMA_SQL} as plataforma, {CAMPANHA_SQL} as campanha, {CHAVE_ANUNCIO_SQL} as chave_anuncio,
         (select coalesce(max({_nivel(_fase('h.etapa_para'))}), 0) from agentesia_lead_etapas h where h.id_lead = l.id) as nivel_hist,
         exists (select 1 from agentesia_lead_etapas h where h.id_lead = l.id and {_fase('h.etapa_para')} = 'analise') as passou_analise,
         (select min(coalesce(k.assinado_em, k.concluido_em, k.atualizado_em)) from agentesia_contratos k
           where k.id_lead = l.id and k.situacao = 'assinado') as k_assinado,
         exists (select 1 from agentesia_contratos k where k.id_lead = l.id
                  and k.situacao in ('gerado', 'assinado', 'substituido')) as k_gerado,
         {passou_assinado} as h_assinado{extra}
    from agentesia_leads l
    join agentesia_contatos ct on ct.id = l.id_contato
    left join agentesia_agente_etapas e on e.id = l.id_etapa
   where {onde}
), n as (
  select b.*, a.assinado_em, (a.assinado_em is not null) as assinado,
         greatest(1, {_nivel('b.fase_atual')}, b.nivel_hist, case when b.k_gerado then 4 else 1 end,
                  case when a.assinado_em is not null then 5 else 1 end) as nivel,
         coalesce(a.assinado_em is null and (b.fase_atual = 'desqualificado' or b.motivo_estado = 'desqualificado'), false) as desq,
         coalesce(b.fase_atual = 'analise' or b.passou_analise, false) as analise,
         extract(epoch from (a.assinado_em - b.criado_em)) / 3600.0 as horas_ate_assinar
    from b
    cross join lateral (select coalesce(b.k_assinado, b.h_assinado,
                                        case when b.fase_atual = 'assinado' then b.atualizado_em end) as assinado_em) a
)"""


def _lista(sql: str) -> str:
    return f"(select coalesce(json_agg(t), '[]'::json) from ({sql}) t)"


def _um(sql: str) -> str:
    return f"(select row_to_json(t) from ({sql}) t)"


def _json(valor: Any, vazio: Any) -> Any:
    if valor is None:
        return vazio
    return json.loads(valor) if isinstance(valor, str) else valor


# ------------------------------------------------------------------ filtros
class Filtros:
    def __init__(self, de: str | None, ate: str | None, agente: str | None, campanha: str | None, fonte: str | None) -> None:
        hoje = datetime.now(_BRASILIA).date()
        try:
            self.ate = date.fromisoformat(ate) if ate else hoje
            self.de = date.fromisoformat(de) if de else self.ate - timedelta(days=29)
        except ValueError:
            raise HTTPException(400, "Data inválida (use AAAA-MM-DD).") from None
        if self.de > self.ate:
            raise HTTPException(400, "A data inicial é depois da final.")
        if (self.ate - self.de).days + 1 > MAX_DIAS:
            raise HTTPException(400, f"Escolha um período de até {MAX_DIAS} dias.")
        if agente and not UUID.fullmatch(agente):
            raise HTTPException(400, "Agente inválido.")
        if fonte and fonte not in PLATAFORMAS:
            raise HTTPException(400, "Plataforma inválida.")
        self.agente = agente or None
        self.campanha = (campanha or "").strip()[:500] or None
        self.fonte = fonte or None

    @property
    def dias(self) -> int:
        return (self.ate - self.de).days + 1

    def limites(self) -> tuple[datetime, datetime]:
        return (datetime.combine(self.de, dtime.min, tzinfo=_BRASILIA),
                datetime.combine(self.ate + timedelta(days=1), dtime.min, tzinfo=_BRASILIA))

    def anteriores(self) -> tuple[datetime, datetime]:
        inicio, _ = self.limites()
        return inicio - timedelta(days=self.dias), inicio

    def chave(self) -> tuple[Any, ...]:
        return (self.de, self.ate, self.agente, self.campanha, self.fonte)

    def onde(self, args: list[Any], inicio: datetime, fim: datetime, *, so_com_origem: bool = False) -> str:
        """where dos leads (alias l). args já começa com o escritório em $1."""
        args += [inicio, fim]
        partes = ["l.id_escritorio = $1::uuid", f"l.criado_em >= ${len(args) - 1}", f"l.criado_em < ${len(args)}"]
        if so_com_origem:
            partes.append("l.origem <> '{}'::jsonb")
        return " and ".join(partes + self.condicoes_lead(args))

    def condicoes_lead(self, args: list[Any]) -> list[str]:
        """Filtros de agente, campanha e plataforma sobre o lead (alias l)."""
        def arg(valor: Any) -> str:
            args.append(valor)
            return f"${len(args)}"

        partes: list[str] = []
        if self.agente:
            partes.append(f"l.id_agente = {arg(self.agente)}::uuid")
        if self.campanha:
            partes.append(f"{CAMPANHA_SQL} = {arg(self.campanha)}")
        if self.fonte:
            partes.append(f"{PLATAFORMA_SQL} = {arg(self.fonte)}")
        return partes

    def filtra_lead(self) -> bool:
        return bool(self.agente or self.campanha or self.fonte)


def _filtros(de: str | None = None, ate: str | None = None, agente: str | None = None, campanha: str | None = None,
             fonte: str | None = None) -> Filtros:
    return Filtros(de, ate, agente, campanha, fonte)


def _dias(f: Filtros) -> list[str]:
    return [(f.de + timedelta(days=i)).isoformat() for i in range(f.dias)]


def _pct(parte: float, todo: float) -> float | None:
    return round(parte / todo * 100, 1) if todo else None


def _funil(linha: dict[str, Any], total: int) -> list[dict[str, Any]]:
    etapas = []
    anterior = None
    for i, (fase, nome) in enumerate(FUNIL, start=1):
        chegaram = int(linha.get(f"n{i}") or 0)
        etapas.append({"fase": fase, "nome": nome, "chegaram": chegaram, "agora": int(linha.get(f"a_{fase}") or 0),
                       "pct_total": _pct(chegaram, total),
                       "conversao": _pct(chegaram, anterior) if anterior is not None else None})
        anterior = chegaram
    return etapas


_AGREGADOS_FUNIL = ", ".join(
    [f"count(*) filter (where nivel >= {i})::int as n{i}" for i in range(1, 6)]
    + [f"count(*) filter (where fase_atual = '{f}' and not desq)::int as a_{f}" for f, _ in FUNIL[:-1]]
    + ["count(*) filter (where assinado)::int as a_assinado"])

_TOTAIS = f"""select count(*)::int as leads, count(*) filter (where assinado)::int as assinados,
       count(*) filter (where desq)::int as desqualificados,
       count(*) filter (where (nivel >= 2 or analise) and not desq)::int as qualificados,
       count(*) filter (where nivel <= 1 and not desq and not assinado)::int as ainda_sdr,
       count(*) filter (where analise)::int as analise,
       count(*) filter (where estado = 'ativo')::int as ativos, count(*) filter (where estado = 'pausado')::int as pausados,
       count(*) filter (where estado = 'encerrado')::int as encerrados,
       count(*) filter (where plataforma <> 'direto')::int as com_origem,
       avg(horas_ate_assinar) filter (where assinado and horas_ate_assinar >= 0)::float8 as horas_media,
       percentile_cont(0.5) within group (order by horas_ate_assinar) filter (where assinado and horas_ate_assinar >= 0)::float8 as horas_mediana,
       count(*) filter (where assinado and horas_ate_assinar <= 24)::int as t_24h,
       count(*) filter (where assinado and horas_ate_assinar > 24 and horas_ate_assinar <= 48)::int as t_2d,
       count(*) filter (where assinado and horas_ate_assinar > 48 and horas_ate_assinar <= 120)::int as t_5d,
       count(*) filter (where assinado and horas_ate_assinar > 120 and horas_ate_assinar <= 240)::int as t_10d,
       count(*) filter (where assinado and horas_ate_assinar > 240)::int as t_mais,
       {_AGREGADOS_FUNIL}
  from n"""

_HEATMAP = f"""select extract(isodow from criado_em at time zone '{FUSO}')::int as dia,
       extract(hour from criado_em at time zone '{FUSO}')::int as hora, count(*)::int as leads,
       0 as assinados from n group by 1, 2
 union all
select extract(isodow from assinado_em at time zone '{FUSO}')::int, extract(hour from assinado_em at time zone '{FUSO}')::int,
       0, count(*)::int from n where assinado group by 1, 2"""


def _tempo(t: dict[str, Any]) -> dict[str, Any]:
    return {"media_horas": round(t["horas_media"], 1) if t.get("horas_media") is not None else None,
            "mediana_horas": round(t["horas_mediana"], 1) if t.get("horas_mediana") is not None else None,
            "faixas": [{"faixa": "Até 24 h", "total": t.get("t_24h", 0)}, {"faixa": "1 a 2 dias", "total": t.get("t_2d", 0)},
                       {"faixa": "3 a 5 dias", "total": t.get("t_5d", 0)}, {"faixa": "6 a 10 dias", "total": t.get("t_10d", 0)},
                       {"faixa": "Mais de 10 dias", "total": t.get("t_mais", 0)}]}


def _heatmap(linhas: list[dict[str, Any]]) -> dict[str, list[list[int]]]:
    leads = [[0] * 24 for _ in range(7)]
    assinados = [[0] * 24 for _ in range(7)]
    for r in linhas:
        if r["dia"] is None or r["hora"] is None:
            continue
        leads[r["dia"] - 1][r["hora"]] += r["leads"]
        assinados[r["dia"] - 1][r["hora"]] += r["assinados"]
    return {"leads": leads, "assinados": assinados}


# ------------------------------------------------------------------ rotas
@api.get("/filtros")
async def filtros(pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    pool = _repo(pedido).pool
    id_escritorio = ctx.escritorio()

    async def calcular() -> dict[str, Any]:
        agentes = await pool.fetch(
            "select id::text as id, nome, situacao from agentesia_agentes where id_escritorio = $1::uuid order by nome",
            id_escritorio)
        campanhas = await pool.fetch(
            f"""select {CAMPANHA_SQL} as campanha, count(*)::int as leads from agentesia_leads l
                 where l.id_escritorio = $1::uuid and l.origem <> '{{}}'::jsonb and l.criado_em >= now() - interval '400 days'
                 group by 1 order by 2 desc limit 200""", id_escritorio)
        return {"agentes": [dict(r) for r in agentes], "campanhas": [dict(r) for r in campanhas],
                "plataformas": [{"valor": k, "rotulo": v} for k, v in PLATAFORMAS.items()],
                "fases": [{"valor": k, "rotulo": v} for k, v in FUNIL]}

    return await _CACHE.obter((id(pedido.app), "filtros", id_escritorio), calcular)


@api.get("/dashboard")
async def dashboard(pedido: Request, f: Filtros = Depends(_filtros), ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    id_escritorio = ctx.escritorio()
    return await _CACHE.obter((id(pedido.app), "dashboard", id_escritorio, f.chave()),
                              lambda: _calcular_dashboard(_repo(pedido).pool, id_escritorio, f))


async def _calcular_dashboard(pool: Any, id_escritorio: str, f: Filtros) -> dict[str, Any]:
    inicio, fim = f.limites()
    args: list[Any] = [id_escritorio]
    onde = f.onde(args, inicio, fim)
    extra = """,
         (select min(m.enviada_em) from agentesia_mensagens m where m.id_lead = l.id and m.autor = 'lead') as prim_lead,
         (select min(m.enviada_em) from agentesia_mensagens m where m.id_lead = l.id and m.autor = 'ia') as prim_ia"""
    sql = _lead_sql(onde, extra) + " select " + ",\n".join([
        _um(_TOTAIS) + " as totais",
        _lista(f"""select to_char(criado_em at time zone '{FUSO}', 'YYYY-MM-DD') as dia, count(*)::int as leads,
                          count(*) filter (where assinado)::int as assinados_safra from n group by 1""") + " as leads_dia",
        _lista(f"""select to_char(assinado_em at time zone '{FUSO}', 'YYYY-MM-DD') as dia, count(*)::int as assinados
                     from n where assinado group by 1""") + " as assinados_dia",
        _lista("""select id_agente::text as id_agente, count(*)::int as leads,
                         count(*) filter (where (nivel >= 2 or analise) and not desq)::int as qualificados,
                         count(*) filter (where nivel >= 3)::int as contratos, count(*) filter (where assinado)::int as assinados,
                         count(*) filter (where desq)::int as desqualificados
                    from n group by 1 order by 5 desc, 2 desc""") + " as por_agente",
        _lista("""select id_agente::text as id_agente, etapa, coalesce(fase_atual, case when etapa is null then 'sem_etapa' else 'outra' end) as fase,
                         count(*)::int as leads from n group by 1, 2, 3 order by 4 desc""") + " as por_etapa",
        _lista("select plataforma, count(*)::int as leads, count(*) filter (where assinado)::int as assinados from n group by 1 order by 2 desc") + " as plataformas",
        _lista("select tel, count(*)::int as leads, count(*) filter (where assinado)::int as assinados from n where tel is not null group by 1") + " as por_tel",
        _lista(_HEATMAP) + " as heatmap",
        _um("""select avg(extract(epoch from (prim_ia - prim_lead)))::float8 as media_s,
                      percentile_cont(0.5) within group (order by extract(epoch from (prim_ia - prim_lead)))::float8 as mediana_s,
                      count(*)::int as leads_respondidos
                 from n where prim_lead is not null and prim_ia is not null and prim_ia >= prim_lead""") + " as primeira_resposta",
    ])
    linha = await pool.fetchrow(sql, *args)

    # IA no período (o que aconteceu entre de e ate, com os mesmos filtros de lead quando houver).
    args_ia: list[Any] = [id_escritorio, inicio, fim]
    junta, onde_lead = "", ""
    if f.filtra_lead():
        junta = " join agentesia_leads l on l.id = {alias}.id_lead"
        onde_lead = " and " + " and ".join(f.condicoes_lead(args_ia))
    sql_ia = "select " + ",\n".join([
        _um(f"""select count(*)::int as turnos, count(*) filter (where t.situacao = 'respondido')::int as respondidos,
                       count(*) filter (where t.situacao in ('silencio', 'descartado'))::int as sem_resposta,
                       count(*) filter (where t.situacao = 'erro')::int as erros,
                       count(*) filter (where t.etapa_depois is not null and t.etapa_depois is distinct from t.etapa_antes)::int as trocas,
                       avg(extract(epoch from (t.concluido_em - t.iniciado_em))) filter (where t.situacao = 'respondido' and t.concluido_em is not null)::float8 as duracao_media_s,
                       percentile_cont(0.5) within group (order by extract(epoch from (t.concluido_em - t.iniciado_em))) filter (where t.situacao = 'respondido' and t.concluido_em is not null)::float8 as duracao_mediana_s
                  from agentesia_turnos t{junta.format(alias='t')}
                 where t.id_escritorio = $1::uuid and t.iniciado_em >= $2 and t.iniciado_em < $3 and t.modo = 'producao'{onde_lead}""") + " as turnos",
        _lista(f"""select to_char(t.iniciado_em at time zone '{FUSO}', 'YYYY-MM-DD') as dia,
                          count(*) filter (where t.situacao = 'respondido')::int as respondidos,
                          count(*) filter (where t.situacao = 'erro')::int as erros
                     from agentesia_turnos t{junta.format(alias='t')}
                    where t.id_escritorio = $1::uuid and t.iniciado_em >= $2 and t.iniciado_em < $3 and t.modo = 'producao'{onde_lead}
                    group by 1""") + " as turnos_dia",
        _lista(f"""select to_char(m.enviada_em at time zone '{FUSO}', 'YYYY-MM-DD') as dia, m.autor, count(*)::int as total
                     from agentesia_mensagens m{junta.format(alias='m')}
                    where m.id_escritorio = $1::uuid and m.enviada_em >= $2 and m.enviada_em < $3{onde_lead}
                    group by 1, 2""") + " as mensagens_dia",
        _lista(f"""select to_char(c.criado_em at time zone '{FUSO}', 'YYYY-MM-DD') as dia,
                          coalesce(sum(c.custo_brl), 0)::float8 as custo_brl, coalesce(sum(c.custo_usd), 0)::float8 as custo_usd,
                          coalesce(sum(c.tokens_entrada + c.tokens_saida), 0)::bigint as tokens, count(*)::int as chamadas
                     from agentesia_chamadas_ia c{junta.format(alias='c')}
                    where c.id_escritorio = $1::uuid and c.criado_em >= $2 and c.criado_em < $3{onde_lead}
                    group by 1""") + " as custo_dia",
    ])
    linha_ia = await pool.fetchrow(sql_ia, *args_ia)

    # Período anterior (mesmo tamanho), só os totais para a variação.
    a0, a1 = f.anteriores()
    args_ant: list[Any] = [id_escritorio]
    onde_ant = f.onde(args_ant, a0, a1)
    ant = _json(await pool.fetchval(
        _lead_sql(onde_ant) + " select " + _um("""select count(*)::int as leads, count(*) filter (where assinado)::int as assinados,
                                                     count(*) filter (where (nivel >= 2 or analise) and not desq)::int as qualificados from n"""),
        *args_ant), {}) or {}
    custo_ant = float(await pool.fetchval(
        "select coalesce(sum(custo_brl), 0)::float8 from agentesia_chamadas_ia where id_escritorio = $1::uuid and criado_em >= $2 and criado_em < $3",
        id_escritorio, a0, a1) or 0)

    totais = _json(linha["totais"], {}) or {}
    leads = int(totais.get("leads") or 0)
    assinados = int(totais.get("assinados") or 0)
    base_eficiencia = leads - int(totais.get("ainda_sdr") or 0) - int(totais.get("desqualificados") or 0)

    # Série por dia (dias sem nada aparecem com zero).
    por_dia: dict[str, dict[str, Any]] = {d: {"dia": d, "leads": 0, "assinados": 0, "respostas_ia": 0, "mensagens_lead": 0,
                                              "mensagens_equipe": 0, "turnos": 0, "erros": 0, "custo_brl": 0.0, "tokens": 0}
                                          for d in _dias(f)}
    for r in _json(linha["leads_dia"], []):
        if r["dia"] in por_dia:
            por_dia[r["dia"]]["leads"] = r["leads"]
    for r in _json(linha["assinados_dia"], []):
        if r["dia"] in por_dia:
            por_dia[r["dia"]]["assinados"] = r["assinados"]
    for r in _json(linha_ia["turnos_dia"], []):
        if r["dia"] in por_dia:
            por_dia[r["dia"]]["turnos"] = r["respondidos"]
            por_dia[r["dia"]]["erros"] = r["erros"]
    mensagens = {"lead": 0, "ia": 0, "humano": 0, "automacao": 0, "sistema": 0}
    for r in _json(linha_ia["mensagens_dia"], []):
        mensagens[r["autor"]] = mensagens.get(r["autor"], 0) + r["total"]
        if r["dia"] in por_dia:
            campo = {"ia": "respostas_ia", "lead": "mensagens_lead", "humano": "mensagens_equipe"}.get(r["autor"])
            if campo:
                por_dia[r["dia"]][campo] += r["total"]
    custo = {"brl": 0.0, "usd": 0.0, "tokens": 0, "chamadas": 0}
    for r in _json(linha_ia["custo_dia"], []):
        custo["brl"] += r["custo_brl"]
        custo["usd"] += r["custo_usd"]
        custo["tokens"] += int(r["tokens"] or 0)
        custo["chamadas"] += r["chamadas"]
        if r["dia"] in por_dia:
            por_dia[r["dia"]]["custo_brl"] = round(r["custo_brl"], 4)
            por_dia[r["dia"]]["tokens"] = int(r["tokens"] or 0)

    # Agentes e etapas com os nomes de cada agente.
    por_agente = _json(linha["por_agente"], [])
    por_etapa = _json(linha["por_etapa"], [])
    ids = {r["id_agente"] for r in por_agente + por_etapa if r["id_agente"]}
    nomes_agente = {r["id"]: r["nome"] for r in await pool.fetch(
        "select id::text as id, nome from agentesia_agentes where id = any($1::uuid[])", list(ids))} if ids else {}
    nomes_etapa = await _nomes_por_agente(pool, ids)
    agentes = [{**r, "nome": nomes_agente.get(r["id_agente"] or "", "Sem agente"),
                "conversao": _pct(r["assinados"], r["leads"])} for r in por_agente]
    etapas = []
    for r in por_etapa:
        nome = (nomes_etapa.get(r["id_agente"] or "", {}).get(r["etapa"] or "") if r["etapa"] else None)
        etapas.append({"agente": nomes_agente.get(r["id_agente"] or "", "Sem agente"), "etapa": r["etapa"],
                       "nome": nome or NOMES_FASE.get(r["fase"], r["etapa"] or "Sem etapa"), "fase": r["fase"],
                       "leads": r["leads"]})
    por_fase: dict[str, int] = {}
    for r in por_etapa:
        por_fase[r["fase"]] = por_fase.get(r["fase"], 0) + r["leads"]

    geo_leads: dict[str, int] = {}
    geo_contratos: dict[str, int] = {}
    for r in _json(linha["por_tel"], []):
        uf = uf_do_telefone(r["tel"])
        if uf:
            geo_leads[uf] = geo_leads.get(uf, 0) + r["leads"]
            if r["assinados"]:
                geo_contratos[uf] = geo_contratos.get(uf, 0) + r["assinados"]

    turnos = _json(linha_ia["turnos"], {}) or {}
    primeira = _json(linha["primeira_resposta"], {}) or {}
    custo_brl = round(custo["brl"], 2)
    return {
        "periodo": {"de": f.de.isoformat(), "ate": f.ate.isoformat(), "dias": f.dias},
        "kpis": {
            "leads": leads, "leads_variacao": variacao(leads, ant.get("leads", 0)),
            "assinados": assinados, "assinados_variacao": variacao(assinados, ant.get("assinados", 0)),
            "conversao": _pct(assinados, leads),
            "conversao_anterior": _pct(ant.get("assinados", 0), ant.get("leads", 0)),
            "eficiencia": _pct(assinados, base_eficiencia),
            "qualificados": int(totais.get("qualificados") or 0),
            "qualificados_pct": _pct(int(totais.get("qualificados") or 0), leads),
            "desqualificados": int(totais.get("desqualificados") or 0),
            "desqualificados_pct": _pct(int(totais.get("desqualificados") or 0), leads),
            "ativos": totais.get("ativos", 0), "pausados": totais.get("pausados", 0), "encerrados": totais.get("encerrados", 0),
            "com_origem": totais.get("com_origem", 0),
            "respostas_ia": mensagens.get("ia", 0), "mensagens_lead": mensagens.get("lead", 0),
            "mensagens_equipe": mensagens.get("humano", 0),
            "primeira_resposta_s": round(primeira["media_s"]) if primeira.get("media_s") is not None else None,
            "primeira_resposta_mediana_s": round(primeira["mediana_s"]) if primeira.get("mediana_s") is not None else None,
            "custo_brl": custo_brl, "custo_variacao": variacao(custo["brl"], custo_ant),
            "custo_por_lead": round(custo["brl"] / leads, 2) if leads else None,
            "custo_por_contrato": round(custo["brl"] / assinados, 2) if assinados else None,
            "tokens": custo["tokens"], "chamadas_ia": custo["chamadas"],
        },
        "funil": _funil(totais, leads),
        "desvios": {"desqualificados": int(totais.get("desqualificados") or 0), "analise": int(totais.get("analise") or 0)},
        "tempo_ate_assinar": _tempo(totais),
        "ia": {"turnos": turnos.get("turnos", 0), "respondidos": turnos.get("respondidos", 0),
               "sem_resposta": turnos.get("sem_resposta", 0), "erros": turnos.get("erros", 0), "trocas": turnos.get("trocas", 0),
               "taxa_erro": _pct(turnos.get("erros", 0), turnos.get("turnos", 0)),
               "duracao_media_s": round(turnos["duracao_media_s"], 1) if turnos.get("duracao_media_s") is not None else None,
               "duracao_mediana_s": round(turnos["duracao_mediana_s"], 1) if turnos.get("duracao_mediana_s") is not None else None},
        "serie": list(por_dia.values()),
        "agentes": agentes,
        "etapas": etapas,
        "por_fase": [{"fase": k, "nome": NOMES_FASE.get(k, k), "leads": v} for k, v in sorted(por_fase.items(), key=lambda x: -x[1])],
        "plataformas": [{**r, "nome": PLATAFORMAS.get(r["plataforma"], r["plataforma"])} for r in _json(linha["plataformas"], [])],
        "uf": {"leads": geo_leads, "contratos": geo_contratos},
        "horarios": _heatmap(_json(linha["heatmap"], [])),
        "crm": await _crm(pool, id_escritorio, inicio, fim),
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


async def _crm(pool: Any, id_escritorio: str, inicio: datetime, fim: datetime) -> dict[str, Any] | None:
    """Cards do CRM espelhados (inclui os antigos e os sem lead). None = banco sem a migração 012."""
    try:
        varredura = await pool.fetchrow(
            "select ultima_em, importado_em, importar_pedido_em, cards_vistos, erro from agentesia_crm_varredura where id_escritorio = $1::uuid",
            id_escritorio)
        linhas = await pool.fetch(
            """select coalesce(fase, 'outra') as fase, etapa_titulo, count(*)::int as total,
                      count(*) filter (where criado_em_helena >= $2 and criado_em_helena < $3)::int as no_periodo,
                      count(*) filter (where id_lead is null)::int as sem_lead
                 from agentesia_crm_espelho where id_escritorio = $1::uuid and not arquivado
                group by 1, 2 order by 3 desc""", id_escritorio, inicio, fim)
    except asyncpg.UndefinedTableError:
        return None
    colunas = [{"fase": r["fase"], "nome_fase": NOMES_FASE.get(r["fase"], r["fase"]), "coluna": r["etapa_titulo"],
                "total": r["total"], "no_periodo": r["no_periodo"], "sem_lead": r["sem_lead"]} for r in linhas]
    return {
        "colunas": colunas,
        "total": sum(c["total"] for c in colunas), "sem_lead": sum(c["sem_lead"] for c in colunas),
        "no_periodo": sum(c["no_periodo"] for c in colunas),
        "assinados": sum(c["total"] for c in colunas if c["fase"] == "assinado"),
        "ultima_varredura": varredura["ultima_em"].isoformat() if varredura and varredura["ultima_em"] else None,
        "importado_em": varredura["importado_em"].isoformat() if varredura and varredura["importado_em"] else None,
        "importacao_pedida": bool(varredura and varredura["importar_pedido_em"]),
        "erro": varredura["erro"] if varredura else None,
    }


# ------------------------------------------------------------------ campanhas
_ATRIBUTOS = """min(l_titulo) as titulo, min(l_conteudo) as conteudo, min(l_url) as url, min(l_fonte) as fonte,
                min(l_meio) as meio, min(l_id_anuncio) as id_anuncio, min(plataforma) as plataforma_exemplo"""


def _linha_grupo(r: dict[str, Any]) -> dict[str, Any]:
    leads = int(r["leads"] or 0)
    return {
        "leads": leads, "closer": r["n2"], "contratos": r["n3"], "assinatura": r["n4"], "assinados": r["n5"],
        "desqualificados": r["desq"], "qualificados": r["qualificados"],
        "conversao": _pct(r["n5"], leads), "qualificacao": _pct(r["qualificados"], leads),
        "desqualificacao": _pct(r["desq"], leads),
        "horas_ate_assinar": round(r["horas"], 1) if r["horas"] is not None else None,
        "custo_brl": round(float(r["custo"] or 0), 2),
        "custo_por_lead": round(float(r["custo"] or 0) / leads, 2) if leads else None,
        "custo_por_contrato": round(float(r["custo"] or 0) / r["n5"], 2) if r["n5"] else None,
        "primeiro_lead": r["primeiro"], "ultimo_lead": r["ultimo"],
    }


_EXTRA_CAMPANHA = """,
         (select coalesce(sum(c.custo_brl), 0) from agentesia_chamadas_ia c where c.id_lead = l.id) as custo,
         l.origem->>'titulo' as l_titulo, l.origem->>'conteudo' as l_conteudo, l.origem->>'url' as l_url,
         l.origem->>'fonte' as l_fonte, l.origem->>'meio' as l_meio, l.origem->>'id_anuncio' as l_id_anuncio"""

_AGREGADOS_GRUPO = f"""count(*)::int as leads, {", ".join(f"count(*) filter (where nivel >= {i})::int as n{i}" for i in range(2, 6))},
       count(*) filter (where desq)::int as desq, count(*) filter (where (nivel >= 2 or analise) and not desq)::int as qualificados,
       avg(horas_ate_assinar) filter (where assinado and horas_ate_assinar >= 0)::float8 as horas,
       sum(custo)::float8 as custo, min(criado_em) as primeiro, max(criado_em) as ultimo"""


@api.get("/campanhas")
async def campanhas(pedido: Request, f: Filtros = Depends(_filtros), ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    id_escritorio = ctx.escritorio()
    return await _CACHE.obter((id(pedido.app), "campanhas", id_escritorio, f.chave()),
                              lambda: _calcular_campanhas(_repo(pedido).pool, id_escritorio, f))


async def _calcular_campanhas(pool: Any, id_escritorio: str, f: Filtros) -> dict[str, Any]:
    inicio, fim = f.limites()
    args: list[Any] = [id_escritorio]
    onde = f.onde(args, inicio, fim, so_com_origem=f.fonte != "direto")
    sql = _lead_sql(onde, _EXTRA_CAMPANHA) + " select " + ",\n".join([
        _um(_TOTAIS) + " as totais",
        _lista(f"""select grouping(campanha, chave_anuncio, plataforma)::int as grupo, campanha, chave_anuncio, plataforma,
                          {_AGREGADOS_GRUPO}, {_ATRIBUTOS}
                     from n group by grouping sets ((campanha), (campanha, chave_anuncio), (plataforma))""") + " as grupos",
        _lista(f"""select to_char(criado_em at time zone '{FUSO}', 'YYYY-MM-DD') as dia, count(*)::int as leads,
                          count(*) filter (where assinado)::int as assinados from n group by 1""") + " as leads_dia",
        _lista(_HEATMAP) + " as heatmap",
    ])
    linha = await pool.fetchrow(sql, *args)
    totais = _json(linha["totais"], {}) or {}
    leads = int(totais.get("leads") or 0)

    lista_campanhas: list[dict[str, Any]] = []
    anuncios: list[dict[str, Any]] = []
    plataformas: list[dict[str, Any]] = []
    for r in _json(linha["grupos"], []):
        base = _linha_grupo(r)
        if r["grupo"] == 3:                                    # (campanha)
            lista_campanhas.append({"campanha": r["campanha"], **base})
        elif r["grupo"] == 1:                                  # (campanha, anúncio)
            nome = r["titulo"] or r["conteudo"] or r["id_anuncio"] or r["url"] or "(anúncio sem identificação)"
            anuncios.append({"chave": r["chave_anuncio"], "nome": nome, "campanha": r["campanha"], "titulo": r["titulo"],
                             "conteudo": r["conteudo"], "url": r["url"], "fonte": r["fonte"], "meio": r["meio"],
                             "id_anuncio": r["id_anuncio"], "plataforma": r["plataforma_exemplo"],
                             "plataforma_nome": PLATAFORMAS.get(r["plataforma_exemplo"] or "", "Outra origem"), **base})
        elif r["grupo"] == 6:                                  # (plataforma)
            plataformas.append({"plataforma": r["plataforma"], "nome": PLATAFORMAS.get(r["plataforma"], r["plataforma"]), **base})
    lista_campanhas.sort(key=lambda c: (-c["leads"], -c["assinados"]))
    anuncios.sort(key=lambda a: (-a["assinados"], -(a["conversao"] or 0), -a["leads"]))
    plataformas.sort(key=lambda p: -p["leads"])

    serie = {d: {"dia": d, "leads": 0, "assinados": 0} for d in _dias(f)}
    for r in _json(linha["leads_dia"], []):
        if r["dia"] in serie:
            serie[r["dia"]].update(leads=r["leads"], assinados=r["assinados"])

    return {
        "periodo": {"de": f.de.isoformat(), "ate": f.ate.isoformat(), "dias": f.dias},
        "kpis": {"leads": leads, "assinados": int(totais.get("assinados") or 0),
                 "conversao": _pct(int(totais.get("assinados") or 0), leads),
                 "qualificados": int(totais.get("qualificados") or 0), "qualificados_pct": _pct(int(totais.get("qualificados") or 0), leads),
                 "desqualificados": int(totais.get("desqualificados") or 0),
                 "desqualificados_pct": _pct(int(totais.get("desqualificados") or 0), leads),
                 "campanhas": len(lista_campanhas), "anuncios": len(anuncios),
                 "media_leads_por_anuncio": round(leads / len(anuncios), 1) if anuncios else None},
        "funil": _funil(totais, leads),
        "tempo_ate_assinar": _tempo(totais),
        "campanhas": lista_campanhas,
        "anuncios": anuncios,
        "plataformas": plataformas,
        "alertas": alertas_de_campanhas(lista_campanhas),
        "ab": teste_ab(anuncios),
        "serie": list(serie.values()),
        "horarios": _heatmap(_json(linha["heatmap"], [])),
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def alertas_de_campanhas(campanhas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Campanhas que precisam de atenção (mesmas regras do dashboard antigo)."""
    saida = []
    for c in campanhas:
        total, ganhos, desq = c["leads"], c["assinados"], c["desqualificados"]
        if total > 5 and ganhos == 0:
            saida.append({"campanha": c["campanha"], "gravidade": "alta", "titulo": "Muitos leads e nenhum contrato",
                          "texto": f"{total} leads no período e nenhum contrato assinado."})
        elif total > 3 and desq / total > 0.5:
            saida.append({"campanha": c["campanha"], "gravidade": "alta", "titulo": "Muitos desqualificados",
                          "texto": f"{round(desq / total * 100)}% dos {total} leads saíram desqualificados."})
        elif total > 5 and ganhos > 0 and ganhos / total < 0.05:
            saida.append({"campanha": c["campanha"], "gravidade": "media", "titulo": "Conversão muito baixa",
                          "texto": f"{ganhos} contrato(s) em {total} leads ({round(ganhos / total * 100, 1)}%)."})
    saida.sort(key=lambda a: (a["gravidade"] != "alta", -next(c["leads"] for c in campanhas if c["campanha"] == a["campanha"])))
    return saida


MIN_LEADS_AB = 3


def teste_ab(anuncios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Teste A/B automático: dentro de cada campanha, compara os anúncios com pelo menos MIN_LEADS_AB leads."""
    por_campanha: dict[str, list[dict[str, Any]]] = {}
    for a in anuncios:
        if a["leads"] >= MIN_LEADS_AB:
            por_campanha.setdefault(a["campanha"], []).append(a)
    saida = []
    for campanha, lista in por_campanha.items():
        if len(lista) < 2:
            continue
        lista = sorted(lista, key=lambda a: (-(a["conversao"] or 0), -a["leads"]))
        vencedor, perdedor = lista[0], lista[-1]
        tv, tp = vencedor["conversao"] or 0, perdedor["conversao"] or 0
        if tp == 0 and perdedor["leads"] >= 5 and tv > 0:
            recomendacao = f"Pause \"{perdedor['nome']}\": {perdedor['leads']} leads e nenhum contrato."
        elif tp > 0 and tv > 2 * tp:
            recomendacao = f"\"{vencedor['nome']}\" converte {round(tv / tp, 1)}x mais que \"{perdedor['nome']}\"."
        elif perdedor["leads"] and perdedor["desqualificados"] / perdedor["leads"] > 0.5:
            recomendacao = f"Revise o público de \"{perdedor['nome']}\": mais da metade sai desqualificada."
        elif tv > 0 and tp == 0:
            recomendacao = f"Só \"{vencedor['nome']}\" trouxe contrato até agora."
        else:
            recomendacao = "Desempenho parecido entre os anúncios."
        saida.append({"campanha": campanha, "vencedor": vencedor["chave"] if tv > 0 else None, "perdedor": perdedor["chave"],
                      "diferenca": round(tv - tp, 1), "recomendacao": recomendacao,
                      "anuncios": [{k: a[k] for k in ("chave", "nome", "leads", "assinados", "desqualificados", "conversao",
                                                       "desqualificacao", "plataforma_nome")} for a in lista[:6]]})
    saida.sort(key=lambda t: -t["diferenca"])
    return saida[:10]


@api.get("/campanhas/anuncio/{chave}")
async def anuncio(chave: str, pedido: Request, f: Filtros = Depends(_filtros), ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{16}", chave):
        raise HTTPException(400, "Anúncio inválido.")
    id_escritorio = ctx.escritorio()
    pool = _repo(pedido).pool
    inicio, fim = f.limites()
    args: list[Any] = [id_escritorio]
    onde = f.onde(args, inicio, fim, so_com_origem=True)
    args.append(chave)
    onde += f" and {CHAVE_ANUNCIO_SQL} = ${len(args)}"
    sql = _lead_sql(onde, _EXTRA_CAMPANHA + ", ct.nome as nome_contato") + " select " + ",\n".join([
        _um(f"select {_AGREGADOS_GRUPO}, {_ATRIBUTOS}, min(campanha) as campanha from n") + " as resumo",
        _lista(f"""select to_char(criado_em at time zone '{FUSO}', 'YYYY-MM-DD') as dia, count(*)::int as leads,
                          count(*) filter (where assinado)::int as assinados from n group by 1""") + " as leads_dia",
        _lista("""select id::text as id, nome_contato as nome, tel, criado_em, etapa, fase_atual, id_agente::text as id_agente,
                         assinado, desq, nivel, assinado_em, estado
                    from n order by criado_em desc limit 100""") + " as leads",
    ])
    linha = await pool.fetchrow(sql, *args)
    r = _json(linha["resumo"], None)
    if not r or not r.get("leads"):
        raise HTTPException(404, "Nenhum lead deste anúncio no período.")
    leads = _json(linha["leads"], [])
    nomes = await _nomes_por_agente(pool, {x["id_agente"] for x in leads if x["id_agente"]})
    serie = {d: {"dia": d, "leads": 0, "assinados": 0} for d in _dias(f)}
    for d in _json(linha["leads_dia"], []):
        if d["dia"] in serie:
            serie[d["dia"]].update(leads=d["leads"], assinados=d["assinados"])
    nivel_nome = {i: nome for i, (_, nome) in enumerate(FUNIL, start=1)}
    return {
        "chave": chave, "campanha": r["campanha"],
        "nome": r["titulo"] or r["conteudo"] or r["id_anuncio"] or r["url"] or "(anúncio sem identificação)",
        "titulo": r["titulo"], "conteudo": r["conteudo"], "url": r["url"], "fonte": r["fonte"], "meio": r["meio"],
        "id_anuncio": r["id_anuncio"], "plataforma_nome": PLATAFORMAS.get(r["plataforma_exemplo"] or "", "Outra origem"),
        **_linha_grupo(r),
        "funil": [{"fase": fase, "nome": nome, "chegaram": r[f"n{i}"] if i > 1 else r["leads"]}
                  for i, (fase, nome) in enumerate(FUNIL, start=1)],
        "serie": list(serie.values()),
        "lista_leads": [{"id": x["id"], "nome": x["nome"], "telefone": mascarar_telefone(x["tel"]), "criado_em": x["criado_em"],
                   "etapa": (nomes.get(x["id_agente"] or "", {}).get(x["etapa"] or "") if x["etapa"] else None)
                   or NOMES_FASE.get(x["fase_atual"] or "", x["etapa"] or "Sem etapa"),
                   "alcancou": nivel_nome.get(x["nivel"], "SDR"), "assinado": x["assinado"], "desqualificado": x["desq"],
                   "assinado_em": x["assinado_em"], "estado": x["estado"]} for x in leads],
    }


# ------------------------------------------------------------------ CRM
@api.post("/crm/importar")
async def pedir_importacao(pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Marca a importação completa dos cards do CRM; a varredura de fundo do app da IA faz em até um minuto."""
    id_escritorio = ctx.escritorio()
    try:
        await _repo(pedido).pool.execute(
            """insert into agentesia_crm_varredura (id_escritorio, importar_pedido_em) values ($1::uuid, now())
               on conflict (id_escritorio) do update set importar_pedido_em = now(), atualizado_em = now()""", id_escritorio)
    except asyncpg.UndefinedTableError:
        raise HTTPException(503, "O banco ainda não tem a migração 012 (relatórios).") from None
    return {"ok": True, "mensagem": "Importação pedida. Os cards aparecem aqui em alguns minutos."}
