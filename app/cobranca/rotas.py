"""API da cobrança em R$ (docs/COBRANCA_TOKENS.md).

Cliente (gestor; a LawChat também, olhando o escritório):
  GET  /api/carteira                         saldo, bônus do mês, plano e consumo do mês em R$
  GET  /api/carteira/estado                  todos os papéis: a IA está pausada por saldo? (sem valores para o atendente)
  GET  /api/carteira/consumo?dias=30         por dia, agente, etapa e função em R$ (detalhe=1: + chamadas e tokens)
  GET  /api/carteira/extrato                 movimentos do livro
  GET  /api/carteira/recargas                pedidos de recarga
  POST /api/carteira/recargas                "Pedir recarga" (aviso para a LawChat; sem pagamento online por enquanto)
  POST /api/carteira/recargas/{id}/cancelar
O cliente nunca vê US$, cotação nem markup.

Equipe LawChat (/api/admin/...): carteiras de todos, lançamentos com motivo, planos, cotação e markup com histórico,
recargas (confirmar/cancelar) e consumo por escritório com custo real × cobrado (margem).
Webhook do gateway: POST /api/pagamentos/asaas/webhook (desligado sem AGENTESIA_ASAAS_WEBHOOK_TOKEN).
"""

from __future__ import annotations

import asyncio

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app import cobranca
from app.cobranca import gateways
from app.gestao.cache_curto import CacheCurto
from app.gestao.repositorio import _linha, _linhas
from app.gestao.rotas import ADMIN, GESTAO, TODOS, Contexto, _repo

api = APIRouter(prefix="/api")
FUSO = "America/Sao_Paulo"

NOMES_TIPO = {"recarga": "Recarga", "bonus_plano": "Bônus do plano", "bonus_manual": "Bônus LawChat",
              "consumo": "Consumo da IA", "ajuste": "Ajuste", "expira_bonus": "Bônus expirado", "estorno": "Estorno"}
NOMES_PAPEL = {"etapa": "Conversa", "extrator": "Leitura da mensagem", "auditor": "Revisão da resposta",
               "followup": "Follow-up", "transcrever_audio": "Áudio", "descrever_imagem": "Imagem", "ler_pdf": "Documento",
               "conhecimento": "Base de conhecimento", "busca_conhecimento": "Busca na base", "contrato_resumo": "Resumo do contrato",
               "resumo_conversa": "Memória da conversa", "origem_produto": "Origem do anúncio"}


def _pool(pedido: Request) -> Any:
    return _repo(pedido).pool


async def _exigir_007(pool: Any) -> None:
    if not await cobranca.tem_cobranca(pool):
        raise HTTPException(503, "Cobrança ainda não instalada no banco (migração 007).")


def _inicio_mes_sql() -> str:
    return f"date_trunc('month', now() at time zone '{FUSO}') at time zone '{FUSO}'"


async def _carteira(pool: Any, id_escritorio: str) -> dict[str, Any]:
    linha = _linha(await pool.fetchrow(
        f"""select c.modo, c.saldo_brl::float8 as saldo_brl, c.bonus_brl::float8 as bonus_brl,
                   c.bonus_do_mes_brl::float8 as bonus_do_mes_brl, c.bonus_mes, c.pausado_por_saldo, c.pausado_em,
                   c.religado_em, c.markup::float8 as markup, c.id_plano,
                   p.nome as plano, p.codigo as plano_codigo, p.preco_mensal_brl::float8 as plano_preco_brl,
                   p.bonus_mensal_brl::float8 as plano_bonus_brl, p.bonus_acumula,
                   (select coalesce(sum(ch.custo_brl), 0)::float8 from agentesia_chamadas_ia ch
                     where ch.id_escritorio = c.id_escritorio and ch.cobranca = 'pendente') as pendente_brl,
                   (select coalesce(sum(ch.custo_brl), 0)::float8 from agentesia_chamadas_ia ch
                     where ch.id_escritorio = c.id_escritorio and ch.cobranca <> 'isenta'
                       and ch.criado_em >= {_inicio_mes_sql()}) as consumo_mes_brl
            from agentesia_carteiras c left join agentesia_planos p on p.id = c.id_plano
            where c.id_escritorio = $1::uuid""", id_escritorio))
    if not linha:
        linha = {"modo": "so_registrar", "saldo_brl": 0.0, "bonus_brl": 0.0, "bonus_do_mes_brl": 0.0, "bonus_mes": None,
                 "pausado_por_saldo": False, "pausado_em": None, "religado_em": None, "markup": None, "id_plano": None,
                 "plano": None, "plano_codigo": None, "plano_preco_brl": None, "plano_bonus_brl": None,
                 "bonus_acumula": None, "pendente_brl": 0.0, "consumo_mes_brl": 0.0}
    disponivel = round(linha["saldo_brl"] + linha["bonus_brl"] - linha["pendente_brl"], 2)
    base = linha["bonus_do_mes_brl"] or 0
    return {**linha, "disponivel_brl": disponivel,
            "bonus_usado_pct": round((base - linha["bonus_brl"]) / base * 100, 1) if base > 0 else None,
            "bloqueado": linha["modo"] == "pre_pago" and disponivel <= 0, "mes": cobranca.mes_atual()}


def _para_cliente(carteira: dict[str, Any]) -> dict[str, Any]:
    """Tira markup e o que não é do cliente."""
    return {k: v for k, v in carteira.items() if k not in ("markup", "id_plano")}


# ============================================================================ cliente
@api.get("/carteira")
async def ver_carteira(pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    pool = _pool(pedido)
    await _exigir_007(pool)
    # A carteira e as recargas pendentes são independentes: em paralelo (uma espera pelo banco em vez de duas).
    carteira, pendentes = await asyncio.gather(_carteira(pool, ctx.escritorio()), pool.fetch(
        """select id, valor_brl::float8 as valor_brl, situacao, metodo, url_pagamento, pix_copia_cola, vencimento, criado_em
           from agentesia_recargas where id_escritorio = $1::uuid and situacao = 'pendente' order by criado_em desc""",
        ctx.escritorio()))
    pendentes = _linhas(pendentes)
    return {**_para_cliente(carteira), "recargas_pendentes": pendentes}


@api.get("/carteira/estado")
async def estado_da_carteira(pedido: Request, ctx: Contexto = Depends(TODOS)) -> dict[str, Any]:
    """Para o aviso no topo do painel: todos os papéis veem se a IA está pausada; valores só quem gere.
    Guardado por 15 s por escritório e papel (o topo pede em toda abertura; escrita no painel apaga a cópia)."""
    return await _CACHE_ESTADO.obter((id(pedido.app), ctx.escritorio(), ctx.papel), lambda: _estado_da_carteira(pedido, ctx))


_CACHE_ESTADO = CacheCurto(15)


async def _estado_da_carteira(pedido: Request, ctx: Contexto) -> dict[str, Any]:
    pool = _pool(pedido)
    if not await cobranca.tem_cobranca(pool):
        return {"bloqueado": False, "motivo": None}
    carteira = await _carteira(pool, ctx.escritorio())
    corpo: dict[str, Any] = {"bloqueado": carteira["bloqueado"], "motivo": cobranca.MOTIVO if carteira["bloqueado"] else None,
                             "modo": carteira["modo"], "pode_pedir_recarga": ctx.papel != "atendente"}
    if ctx.papel != "atendente":
        corpo.update(disponivel_brl=carteira["disponivel_brl"], bonus_usado_pct=carteira["bonus_usado_pct"])
    return corpo


@api.get("/carteira/consumo")
async def consumo_da_carteira(pedido: Request, dias: int = 30, detalhe: bool = False,
                              ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Consumo em R$ cobrado (o que sai da carteira). Detalhe: número de chamadas e tokens por função."""
    pool = _pool(pedido)
    await _exigir_007(pool)
    dias = max(1, min(int(dias), 366))
    filtro = "c.id_escritorio = $1::uuid and c.cobranca <> 'isenta' and c.criado_em >= now() - make_interval(days => $2)"
    # As quatro somas são independentes: em paralelo.
    por_dia, por_agente, por_etapa, por_funcao = map(_linhas, await asyncio.gather(pool.fetch(
        f"""select (c.criado_em at time zone '{FUSO}')::date::text as dia, sum(c.custo_brl)::float8 as valor_brl
            from agentesia_chamadas_ia c where {filtro} group by 1 order by 1""", ctx.escritorio(), dias), pool.fetch(
        f"""select coalesce(a.nome, 'Sem agente') as agente, sum(c.custo_brl)::float8 as valor_brl
            from agentesia_chamadas_ia c left join agentesia_agentes a on a.id = c.id_agente
            where {filtro} group by 1 order by 2 desc""", ctx.escritorio(), dias), pool.fetch(
        f"""select coalesce(c.codigo_etapa, 'fora da conversa') as etapa, sum(c.custo_brl)::float8 as valor_brl
            from agentesia_chamadas_ia c where {filtro} group by 1 order by 2 desc""", ctx.escritorio(), dias), pool.fetch(
        f"""select c.papel, sum(c.custo_brl)::float8 as valor_brl, count(*)::int as chamadas,
                   sum(c.tokens_entrada + c.tokens_saida)::bigint as tokens
            from agentesia_chamadas_ia c where {filtro} group by 1 order by 2 desc""", ctx.escritorio(), dias)))
    for f in por_funcao:
        f["nome"] = NOMES_PAPEL.get(f["papel"], f["papel"])
        if not detalhe:
            f.pop("chamadas", None)
            f.pop("tokens", None)
    return {"dias": dias, "total_brl": round(sum(d["valor_brl"] or 0 for d in por_dia), 2), "por_dia": por_dia,
            "por_agente": por_agente, "por_etapa": por_etapa, "por_funcao": por_funcao}


async def _extrato(pool: Any, id_escritorio: str, limite: int, admin: bool) -> list[dict[str, Any]]:
    linhas = _linhas(await pool.fetch(
        """select m.id, m.tipo, m.valor_brl::float8 as valor_brl, m.parte_saldo::float8 as parte_saldo,
                  m.parte_bonus::float8 as parte_bonus, m.saldo_depois::float8 as saldo_depois,
                  m.bonus_depois::float8 as bonus_depois, m.motivo, m.detalhe, m.criado_em, u.nome as usuario
           from agentesia_carteira_movimentos m left join agentesia_usuarios u on u.id = m.id_usuario
           where m.id_escritorio = $1::uuid order by m.criado_em desc limit $2""", id_escritorio, limite))
    for l in linhas:
        l["nome_tipo"] = NOMES_TIPO.get(l["tipo"], l["tipo"])
        detalhe = l.get("detalhe") or {}
        if isinstance(detalhe, str):
            detalhe = json.loads(detalhe or "{}")
        if not admin:                                    # o cliente não vê o custo real em US$ nem em R$
            detalhe = {k: v for k, v in detalhe.items() if k not in ("custo_usd", "custo_brl_real")}
        l["detalhe"] = detalhe
    return linhas


@api.get("/carteira/extrato")
async def extrato_da_carteira(pedido: Request, limite: int = 100, ctx: Contexto = Depends(GESTAO)) -> list[dict[str, Any]]:
    pool = _pool(pedido)
    await _exigir_007(pool)
    return await _extrato(pool, ctx.escritorio(), max(1, min(int(limite), 500)), admin=False)


@api.get("/carteira/recargas")
async def recargas_do_escritorio(pedido: Request, ctx: Contexto = Depends(GESTAO)) -> list[dict[str, Any]]:
    pool = _pool(pedido)
    await _exigir_007(pool)
    return _linhas(await pool.fetch(
        """select r.id, r.valor_brl::float8 as valor_brl, r.situacao, r.gateway, r.metodo, r.url_pagamento,
                  r.pix_copia_cola, r.vencimento, r.paga_em, r.criado_em, r.observacao, u.nome as pedido_por
           from agentesia_recargas r left join agentesia_usuarios u on u.id = r.pedido_por
           where r.id_escritorio = $1::uuid order by r.criado_em desc limit 100""", ctx.escritorio()))


class PedidoRecarga(BaseModel):
    valor_brl: float = Field(gt=0, le=100000)
    observacao: str | None = Field(default=None, max_length=500)


@api.post("/carteira/recargas")
async def pedir_recarga(dados: PedidoRecarga, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Pede a recarga: fica pendente e a LawChat é avisada (central de avisos). O crédito só entra quando a recarga
    for confirmada (manual pelo admin, ou webhook do gateway quando estiver ligado)."""
    pool = _pool(pedido)
    await _exigir_007(pool)
    id_escritorio = ctx.escritorio()
    valor = round(dados.valor_brl, 2)
    repetida = _linha(await pool.fetchrow(
        """select id, valor_brl::float8 as valor_brl, situacao, criado_em from agentesia_recargas
           where id_escritorio = $1::uuid and situacao = 'pendente' and valor_brl = $2 and criado_em > now() - interval '10 minutes'
           order by criado_em desc limit 1""", id_escritorio, valor))
    if repetida:                                        # clique duplo: não cria outro pedido nem outro aviso
        return {**repetida, "repetida": True}
    gw = gateways.gateway()
    escritorio = _linha(await pool.fetchrow("select id, nome from agentesia_escritorios where id = $1::uuid", id_escritorio)) or {}
    try:
        cob = await gw.criar_cobranca({"valor_brl": valor}, escritorio)
    except NotImplementedError:
        gw = gateways.GatewayManual()
        cob = await gw.criar_cobranca({"valor_brl": valor}, escritorio)
    recarga = _linha(await pool.fetchrow(
        """insert into agentesia_recargas (id_escritorio, valor_brl, gateway, metodo, id_externo, url_pagamento,
                                           pix_copia_cola, pix_qr_base64, vencimento, pedido_por, observacao, detalhe)
           values ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9, $10::uuid, $11, $12::jsonb)
           returning id, valor_brl::float8 as valor_brl, situacao, gateway, metodo, url_pagamento, pix_copia_cola,
                     vencimento, criado_em""",
        id_escritorio, valor, gw.nome, cob.metodo, cob.id_externo, cob.url_pagamento, cob.pix_copia_cola,
        cob.pix_qr_base64, cob.vencimento, ctx.id_usuario, dados.observacao, json.dumps(cob.detalhe, ensure_ascii=False)))
    carteira = await _carteira(pool, id_escritorio)
    texto = (f"Pedido de recarga de R$ {valor:.2f} por {ctx.usuario.get('nome') or 'gestor'}. Disponível agora: "
             f"R$ {carteira['disponivel_brl']:.2f}{' (IA pausada por saldo)' if carteira['bloqueado'] else ''}."
             + (f" Obs.: {dados.observacao}" if dados.observacao else ""))
    await pool.execute(
        """insert into agentesia_eventos (id_escritorio, tipo, gravidade, responsavel, descricao, detalhe)
           values ($1::uuid, 'pedido_recarga', 'aviso', 'lawchat', $2, $3::jsonb)""",
        id_escritorio, texto, json.dumps({"id_recarga": str(recarga["id"]), "valor_brl": valor}))
    await _repo(pedido).registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=id_escritorio,
                                            tabela="agentesia_recargas", id_registro=str(recarga["id"]),
                                            acao="pediu_recarga", resumo=f"Pediu recarga de R$ {valor:.2f}")
    return recarga


@api.post("/carteira/recargas/{id_recarga}/cancelar")
async def cancelar_recarga_do_cliente(id_recarga: str, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    pool = _pool(pedido)
    await _exigir_007(pool)
    feita = await pool.fetchval(
        """update agentesia_recargas set situacao = 'cancelada', encerrada_em = now()
           where id = $1::uuid and id_escritorio = $2::uuid and situacao = 'pendente' returning id""", id_recarga, ctx.escritorio())
    if not feita:
        raise HTTPException(404, "Pedido de recarga pendente não encontrado.")
    await _repo(pedido).registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=ctx.escritorio(),
                                            tabela="agentesia_recargas", id_registro=id_recarga, acao="cancelou_recarga",
                                            resumo="Cancelou um pedido de recarga")
    return {"situacao": "cancelada"}


# ============================================================================ admin: cotação e markup
class ConfigCobranca(BaseModel):
    cotacao_usd_brl: float
    markup: float | None = None
    markup_percentual: float | None = None
    motivo: str | None = Field(default=None, max_length=300)


async def _vigente(pool: Any) -> dict[str, Any]:
    linha = _linha(await pool.fetchrow(
        "select cotacao_usd_brl::float8 as cotacao_usd_brl, markup::float8 as markup, vigente_desde from agentesia_cobranca_vigente()"))
    return linha or {"cotacao_usd_brl": cobranca.COTACAO_PADRAO, "markup": cobranca.MARKUP_PADRAO, "vigente_desde": None}


@api.get("/admin/cobranca/config")
async def ver_config(pedido: Request, _: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    pool = _pool(pedido)
    await _exigir_007(pool)
    historico = _linhas(await pool.fetch(
        """select c.id, c.cotacao_usd_brl::float8 as cotacao_usd_brl, c.markup::float8 as markup, c.vigente_desde, c.motivo,
                  c.criado_em, u.nome as usuario
           from agentesia_cobranca_config c left join agentesia_usuarios u on u.id = c.id_usuario
           order by c.vigente_desde desc, c.criado_em desc limit 50"""))
    vigente = await _vigente(pool)
    return {"vigente": {**vigente, "markup_percentual": round((vigente["markup"] - 1) * 100, 2)}, "historico": historico}


@api.post("/admin/cobranca/config")
async def mudar_config(dados: ConfigCobranca, pedido: Request, ctx: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    """Nova cotação/markup (vale para as chamadas a partir de agora; as já gravadas guardam os delas)."""
    pool = _pool(pedido)
    await _exigir_007(pool)
    try:
        cotacao = cobranca.validar_cotacao(dados.cotacao_usd_brl)
        markup = cobranca.markup_de(dados.markup, dados.markup_percentual)
    except ValueError as erro:
        raise HTTPException(400, str(erro)) from erro
    antes = await _vigente(pool)
    await pool.execute(
        "insert into agentesia_cobranca_config (cotacao_usd_brl, markup, motivo, id_usuario) values ($1, $2, $3, $4::uuid)",
        cotacao, markup, dados.motivo, ctx.id_usuario)
    await _repo(pedido).registrar_alteracao(
        id_usuario=ctx.id_usuario, id_escritorio=None, tabela="agentesia_cobranca_config", id_registro=None, acao="alterou",
        resumo=f"Cotação R$ {cotacao:.4f} por US$ e markup {markup:.4f}x", antes=antes,
        depois={"cotacao_usd_brl": cotacao, "markup": markup, "motivo": dados.motivo})
    return await ver_config(pedido, ctx)


# ============================================================================ admin: planos
class Plano(BaseModel):
    codigo: str = Field(pattern=r"^[a-z0-9_-]{2,40}$")
    nome: str = Field(min_length=2, max_length=80)
    descricao: str | None = None
    preco_mensal_brl: float = Field(ge=0, le=1_000_000)
    bonus_mensal_brl: float = Field(ge=0, le=1_000_000)
    bonus_acumula: bool = False
    ativo: bool = True
    ordem: int = 0


class AlterarPlano(BaseModel):
    nome: str | None = Field(default=None, min_length=2, max_length=80)
    descricao: str | None = None
    preco_mensal_brl: float | None = Field(default=None, ge=0, le=1_000_000)
    bonus_mensal_brl: float | None = Field(default=None, ge=0, le=1_000_000)
    bonus_acumula: bool | None = None
    ativo: bool | None = None
    ordem: int | None = None


_COLUNAS_PLANO = """id, codigo, nome, descricao, preco_mensal_brl::float8 as preco_mensal_brl,
                    bonus_mensal_brl::float8 as bonus_mensal_brl, bonus_acumula, ativo, ordem, criado_em, atualizado_em,
                    (select count(*)::int from agentesia_carteiras c where c.id_plano = agentesia_planos.id) as escritorios"""


@api.get("/admin/planos")
async def listar_planos(pedido: Request, _: Contexto = Depends(ADMIN)) -> list[dict[str, Any]]:
    pool = _pool(pedido)
    await _exigir_007(pool)
    return _linhas(await pool.fetch(f"select {_COLUNAS_PLANO} from agentesia_planos order by ordem, nome"))


@api.post("/admin/planos")
async def criar_plano(dados: Plano, pedido: Request, ctx: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    pool = _pool(pedido)
    await _exigir_007(pool)
    if await pool.fetchval("select 1 from agentesia_planos where codigo = $1", dados.codigo):
        raise HTTPException(409, "Já existe um plano com esse código.")
    plano = _linha(await pool.fetchrow(
        f"""insert into agentesia_planos (codigo, nome, descricao, preco_mensal_brl, bonus_mensal_brl, bonus_acumula, ativo, ordem)
            values ($1, $2, $3, $4, $5, $6, $7, $8) returning {_COLUNAS_PLANO}""",
        dados.codigo, dados.nome.strip(), dados.descricao, dados.preco_mensal_brl, dados.bonus_mensal_brl,
        dados.bonus_acumula, dados.ativo, dados.ordem))
    await _repo(pedido).registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=None, tabela="agentesia_planos",
                                            id_registro=str(plano["id"]), acao="criou", resumo=f"Plano {dados.nome} criado",
                                            depois=dados.model_dump())
    return plano


@api.patch("/admin/planos/{id_plano}")
async def alterar_plano(id_plano: str, dados: AlterarPlano, pedido: Request, ctx: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    """Mudar o bônus vale a partir do mês seguinte (o bônus do mês já creditado não muda)."""
    pool = _pool(pedido)
    await _exigir_007(pool)
    antes = _linha(await pool.fetchrow(f"select {_COLUNAS_PLANO} from agentesia_planos where id = $1::uuid", id_plano))
    if not antes:
        raise HTTPException(404, "Plano não encontrado.")
    mudancas = {k: v for k, v in dados.model_dump().items() if v is not None}
    if not mudancas:
        return antes
    sets = ", ".join(f"{k} = ${i}" for i, k in enumerate(mudancas, 2))
    plano = _linha(await pool.fetchrow(
        f"update agentesia_planos set {sets} where id = $1::uuid returning {_COLUNAS_PLANO}", id_plano, *mudancas.values()))
    await _repo(pedido).registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=None, tabela="agentesia_planos",
                                            id_registro=id_plano, acao="alterou", resumo=f"Plano {plano['nome']} alterado",
                                            antes={k: antes.get(k) for k in mudancas}, depois=mudancas)
    return plano


# ============================================================================ admin: carteiras
@api.get("/admin/carteiras")
async def listar_carteiras(pedido: Request, _: Contexto = Depends(ADMIN)) -> list[dict[str, Any]]:
    """Todos os escritórios: saldo, bônus, plano, modo, pausa e o mês (custo real × cobrado)."""
    pool = _pool(pedido)
    await _exigir_007(pool)
    return _linhas(await pool.fetch(
        f"""select e.id as id_escritorio, e.nome, coalesce(c.modo, 'so_registrar') as modo,
                   coalesce(c.saldo_brl, 0)::float8 as saldo_brl, coalesce(c.bonus_brl, 0)::float8 as bonus_brl,
                   coalesce(c.bonus_do_mes_brl, 0)::float8 as bonus_do_mes_brl, coalesce(c.pausado_por_saldo, false) as pausado_por_saldo,
                   c.pausado_em, c.markup::float8 as markup, c.id_plano, p.nome as plano,
                   (select coalesce(sum(ch.custo_brl), 0)::float8 from agentesia_chamadas_ia ch
                     where ch.id_escritorio = e.id and ch.cobranca = 'pendente') as pendente_brl,
                   m.custo_usd, m.custo_brl_real, m.cobrado_brl,
                   (select count(*)::int from agentesia_recargas r where r.id_escritorio = e.id and r.situacao = 'pendente') as recargas_pendentes
            from agentesia_escritorios e
            left join agentesia_carteiras c on c.id_escritorio = e.id
            left join agentesia_planos p on p.id = c.id_plano
            left join lateral (select coalesce(sum(ch.custo_usd), 0)::float8 as custo_usd,
                                      coalesce(sum(ch.custo_brl_real), 0)::float8 as custo_brl_real,
                                      coalesce(sum(ch.custo_brl), 0)::float8 as cobrado_brl
                                 from agentesia_chamadas_ia ch
                                where ch.id_escritorio = e.id and ch.cobranca <> 'isenta'
                                  and ch.criado_em >= {_inicio_mes_sql()}) m on true
            order by e.nome"""))


class AlterarCarteira(BaseModel):
    id_plano: str | None = None
    tirar_plano: bool = False
    modo: str | None = None
    markup: float | None = None
    markup_percentual: float | None = None
    usar_markup_global: bool = False
    perdoar_negativo: bool = False          # ao ligar o pré-pago: zera o saldo negativo do período "só registrar"


@api.get("/admin/carteiras/{id_escritorio}")
async def ver_carteira_admin(id_escritorio: str, pedido: Request, _: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    pool = _pool(pedido)
    await _exigir_007(pool)
    carteira = await _carteira(pool, id_escritorio)
    conferencia = _linha(await pool.fetchrow(
        """select diferenca::float8 as diferenca, movimentos::int as movimentos from agentesia_v_carteira_conferencia
           where id_escritorio = $1::uuid""", id_escritorio)) or {"diferenca": 0.0, "movimentos": 0}
    return {**carteira, "conferencia": conferencia, "extrato": await _extrato(pool, id_escritorio, 200, admin=True)}


@api.patch("/admin/carteiras/{id_escritorio}")
async def alterar_carteira(id_escritorio: str, dados: AlterarCarteira, pedido: Request,
                           ctx: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    pool = _pool(pedido)
    await _exigir_007(pool)
    if not await pool.fetchval("select 1 from agentesia_escritorios where id = $1::uuid", id_escritorio):
        raise HTTPException(404, "Escritório não encontrado.")
    if dados.modo is not None and dados.modo not in cobranca.MODOS:
        raise HTTPException(400, "Modo: pre_pago ou so_registrar.")
    markup = None
    if dados.markup is not None or dados.markup_percentual is not None:
        try:
            markup = cobranca.markup_de(dados.markup, dados.markup_percentual)
        except ValueError as erro:
            raise HTTPException(400, str(erro)) from erro
    if dados.id_plano and not await pool.fetchval("select 1 from agentesia_planos where id = $1::uuid and ativo", dados.id_plano):
        raise HTTPException(400, "Plano não encontrado ou inativo.")
    antes = await _carteira(pool, id_escritorio)
    resumo: list[str] = []
    async with pool.acquire() as conexao, conexao.transaction():
        await conexao.execute("insert into agentesia_carteiras (id_escritorio) values ($1::uuid) on conflict do nothing",
                              id_escritorio)
        if dados.id_plano or dados.tirar_plano:
            await conexao.execute("update agentesia_carteiras set id_plano = $2::uuid where id_escritorio = $1::uuid",
                                  id_escritorio, None if dados.tirar_plano else dados.id_plano)
            resumo.append("sem plano" if dados.tirar_plano else "plano trocado")
        if markup is not None or dados.usar_markup_global:
            await conexao.execute("update agentesia_carteiras set markup = $2 where id_escritorio = $1::uuid",
                                  id_escritorio, None if dados.usar_markup_global else markup)
            resumo.append("markup global" if dados.usar_markup_global else f"markup próprio {markup:.4f}x")
        if dados.perdoar_negativo:
            saldo = await conexao.fetchval("select saldo_brl from agentesia_carteiras where id_escritorio = $1::uuid", id_escritorio)
            if saldo is not None and saldo < 0:
                await cobranca.lancar(conexao, id_escritorio, "ajuste", float(-saldo), id_usuario=ctx.id_usuario,
                                      motivo="Consumo do período 'só registrar' perdoado ao ligar o pré-pago")
                resumo.append(f"perdoado R$ {float(-saldo):.2f} negativo")
        if dados.modo:
            await conexao.execute("update agentesia_carteiras set modo = $2 where id_escritorio = $1::uuid", id_escritorio, dados.modo)
            resumo.append(f"modo {dados.modo}")
    if dados.id_plano:
        await cobranca.renovar_bonus(pool, id_escritorio=id_escritorio)     # bônus do mês na hora, se ainda não teve
    cobranca.esquecer(id_escritorio)
    depois = await _carteira(pool, id_escritorio)
    await _repo(pedido).registrar_alteracao(
        id_usuario=ctx.id_usuario, id_escritorio=id_escritorio, tabela="agentesia_carteiras", id_registro=id_escritorio,
        acao="alterou", resumo="Carteira: " + (", ".join(resumo) or "sem mudança"),
        antes={k: antes.get(k) for k in ("modo", "plano", "markup", "saldo_brl")},
        depois={k: depois.get(k) for k in ("modo", "plano", "markup", "saldo_brl")})
    return depois


class Lancamento(BaseModel):
    tipo: str
    valor_brl: float
    motivo: str = Field(min_length=3, max_length=300)


@api.post("/admin/carteiras/{id_escritorio}/lancamentos")
async def lancar_na_carteira(id_escritorio: str, dados: Lancamento, pedido: Request,
                             ctx: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    """Crédito/bônus/ajuste à mão, sempre com motivo. bonus_manual e recarga entram no saldo (não expiram)."""
    pool = _pool(pedido)
    await _exigir_007(pool)
    if dados.tipo not in cobranca.TIPOS_MANUAIS:
        raise HTTPException(400, "Tipo: bonus_manual, recarga ou ajuste.")
    valor = round(dados.valor_brl, 2)
    if valor == 0 or abs(valor) > 100000 or (dados.tipo != "ajuste" and valor < 0):
        raise HTTPException(400, "Valor inválido (crédito positivo; só o ajuste pode ser negativo).")
    if not await pool.fetchval("select 1 from agentesia_escritorios where id = $1::uuid", id_escritorio):
        raise HTTPException(404, "Escritório não encontrado.")
    movimento = await cobranca.lancar(pool, id_escritorio, dados.tipo, valor, motivo=dados.motivo.strip(),
                                      id_usuario=ctx.id_usuario)
    await _repo(pedido).registrar_alteracao(
        id_usuario=ctx.id_usuario, id_escritorio=id_escritorio, tabela="agentesia_carteira_movimentos",
        id_registro=str(movimento["id"]) if movimento else None, acao="lancou",
        resumo=f"{NOMES_TIPO[dados.tipo]} de R$ {valor:.2f}: {dados.motivo.strip()}", depois=dados.model_dump())
    return {"movimento": movimento, "carteira": await _carteira(pool, id_escritorio)}


# ============================================================================ admin: recargas
@api.get("/admin/recargas")
async def listar_recargas(pedido: Request, situacao: str | None = None, _: Contexto = Depends(ADMIN)) -> list[dict[str, Any]]:
    pool = _pool(pedido)
    await _exigir_007(pool)
    return _linhas(await pool.fetch(
        """select r.id, r.id_escritorio, e.nome as escritorio, r.valor_brl::float8 as valor_brl, r.situacao, r.gateway,
                  r.metodo, r.id_externo, r.vencimento, r.paga_em, r.criado_em, r.observacao, u.nome as pedido_por,
                  c.nome as confirmada_por
           from agentesia_recargas r join agentesia_escritorios e on e.id = r.id_escritorio
           left join agentesia_usuarios u on u.id = r.pedido_por left join agentesia_usuarios c on c.id = r.confirmada_por
           where ($1::text is null or r.situacao = $1) order by (r.situacao = 'pendente') desc, r.criado_em desc limit 300""",
        situacao))


@api.post("/admin/recargas/{id_recarga}/confirmar")
async def confirmar_recarga(id_recarga: str, pedido: Request, ctx: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    """Gateway manual: o dinheiro caiu, a LawChat confirma. Credita uma vez só (clicar de novo não credita)."""
    pool = _pool(pedido)
    await _exigir_007(pool)
    recarga = _linha(await pool.fetchrow(
        "select id, id_escritorio, valor_brl::float8 as valor_brl, situacao from agentesia_recargas where id = $1::uuid", id_recarga))
    if not recarga:
        raise HTTPException(404, "Recarga não encontrada.")
    if recarga["situacao"] in ("cancelada", "estornada"):
        raise HTTPException(409, f"Recarga {recarga['situacao']} não pode ser confirmada.")
    ja_paga = recarga["situacao"] == "paga"
    id_movimento = await cobranca.confirmar_recarga(pool, id_recarga, id_usuario=ctx.id_usuario,
                                                    detalhe={"confirmada_no_painel": True})
    if not ja_paga:
        await _repo(pedido).registrar_alteracao(
            id_usuario=ctx.id_usuario, id_escritorio=str(recarga["id_escritorio"]), tabela="agentesia_recargas",
            id_registro=id_recarga, acao="confirmou_recarga", resumo=f"Recarga de R$ {recarga['valor_brl']:.2f} confirmada")
    return {"id_movimento": id_movimento, "ja_estava_paga": ja_paga,
            "carteira": await _carteira(pool, str(recarga["id_escritorio"]))}


@api.post("/admin/recargas/{id_recarga}/cancelar")
async def cancelar_recarga(id_recarga: str, pedido: Request, ctx: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    pool = _pool(pedido)
    await _exigir_007(pool)
    linha = await pool.fetchrow(
        """update agentesia_recargas set situacao = 'cancelada', encerrada_em = now()
           where id = $1::uuid and situacao in ('pendente', 'expirada') returning id_escritorio""", id_recarga)
    if not linha:
        raise HTTPException(409, "Só recarga pendente ou expirada pode ser cancelada.")
    await _repo(pedido).registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=str(linha["id_escritorio"]),
                                            tabela="agentesia_recargas", id_registro=id_recarga, acao="cancelou_recarga",
                                            resumo="Recarga cancelada pela LawChat")
    return {"situacao": "cancelada"}


# ============================================================================ admin: consumo e margem
@api.get("/admin/cobranca/consumo")
async def consumo_admin(pedido: Request, dias: int = 30, id_escritorio: str | None = None,
                        _: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    """Custo real (US$ e R$) × valor cobrado (R$) e a margem, por escritório e por modelo. 'Sem preço' = chamadas
    com tokens e custo zero (modelo fora da tabela de preços: cobrança subcontada)."""
    pool = _pool(pedido)
    await _exigir_007(pool)
    dias = max(1, min(int(dias), 366))
    filtro = ("c.criado_em >= now() - make_interval(days => $1) and c.cobranca <> 'isenta'"
              " and ($2::uuid is null or c.id_escritorio = $2::uuid)")
    soma = """count(*)::int as chamadas, sum(c.tokens_entrada + c.tokens_saida)::bigint as tokens,
              sum(c.custo_usd)::float8 as custo_usd, sum(c.custo_brl_real)::float8 as custo_brl_real,
              sum(c.custo_brl)::float8 as cobrado_brl, (sum(c.custo_brl) - sum(c.custo_brl_real))::float8 as margem_brl"""
    por_escritorio = _linhas(await pool.fetch(
        f"""select e.id as id_escritorio, e.nome, {soma}
            from agentesia_chamadas_ia c join agentesia_escritorios e on e.id = c.id_escritorio
            where {filtro} group by e.id, e.nome order by cobrado_brl desc nulls last""", dias, id_escritorio))
    por_modelo = _linhas(await pool.fetch(
        f"""select c.modelo, {soma}, count(*) filter (where c.sem_preco)::int as sem_preco
            from agentesia_chamadas_ia c where {filtro} group by 1 order by cobrado_brl desc nulls last""", dias, id_escritorio))
    sem_preco = await pool.fetchval(
        f"select count(*)::int from agentesia_chamadas_ia c where c.sem_preco and c.criado_em >= now() - make_interval(days => $1) "
        "and ($2::uuid is null or c.id_escritorio = $2::uuid)", dias, id_escritorio)
    total = {k: round(sum((l.get(k) or 0) for l in por_escritorio), 6)
             for k in ("custo_usd", "custo_brl_real", "cobrado_brl", "margem_brl")}
    return {"dias": dias, "total": total, "por_escritorio": por_escritorio, "por_modelo": por_modelo,
            "chamadas_sem_preco": sem_preco or 0}


# ============================================================================ webhook do gateway (Asaas)
@api.post("/pagamentos/asaas/webhook")
async def webhook_asaas(pedido: Request) -> dict[str, Any]:
    """Desenhado e testado com payload falso; só vale com AGENTESIA_ASAAS_WEBHOOK_TOKEN (o mesmo token configurado no
    webhook do Asaas). Sem o token: 401 para tudo. Nunca chama a API do Asaas."""
    gw = gateways.GatewayAsaas()
    corpo_bruto = await pedido.body()
    if not gw.webhook_autentico(dict(pedido.headers), corpo_bruto):
        raise HTTPException(401, "Webhook sem o token do Asaas.")
    try:
        corpo = json.loads(corpo_bruto or b"{}")
    except json.JSONDecodeError as erro:
        raise HTTPException(400, "Corpo inválido.") from erro
    pool = _pool(pedido)
    await _exigir_007(pool)
    evento = gw.ler_webhook(corpo)
    resultado = await gateways.processar_evento(pool, gw.nome, evento, corpo)
    return {"recebido": True, "resultado": resultado}

