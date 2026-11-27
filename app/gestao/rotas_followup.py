"""Rotas do follow-up padrão (docs/FOLLOWUP.md): prévia para a etapa da ativação, "Ligar com o padrão" do cliente e a
visão do admin de todos os escritórios (com a ação em lote). Nada liga sozinho: cada ligação é um clique ou um pedido
explícito, e cada uma fica em agentesia_alteracoes."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.followup import padrao
from app.gestao.log_plataforma import registrado
from app.gestao.rotas import ADMIN, GESTAO, TODOS, Contexto, _repo

api = APIRouter(prefix="/api")


@api.get("/biblioteca/produtos/{id_produto}/followup-padrao")
async def followup_padrao_do_produto(id_produto: str, pedido: Request, ctx: Contexto = Depends(TODOS)) -> dict[str, Any]:
    """A cadência que a ativação vai copiar (etapa "Follow-up" do assistente). Aceita id ou slug."""
    linha = await _repo(pedido).pool.fetchrow(
        "select padrao_followup from agentesia_biblioteca_produtos where id::text = $1 or slug = $1 limit 1", id_produto)
    if not linha:
        raise HTTPException(404, "Produto não encontrado.")
    return padrao.previa_do_produto(dict(linha))


@api.post("/produtos-ativados/{id_ativado}/followup/ligar-padrao")
@registrado("followup.ligado", "Follow-up ligado com o padrão", referencia=lambda a: a["id_ativado"],
            resultado=lambda _a, r: {k: (r or {}).get(k) for k in ("id_ativado", "id_agente", "nome", "aviso")})
async def ligar_padrao(id_ativado: str, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Botão "Ligar com o padrão" (Início, tela do produto, Meus produtos)."""
    feito = await padrao.ligar_com_padrao(_repo(pedido).pool, id_ativado, id_usuario=ctx.id_usuario,
                                          id_escritorio=ctx.escritorio(), origem="painel")
    if not feito:
        raise HTTPException(404, "Produto não encontrado ou ainda não ativado.")
    return feito


@api.get("/admin/followup")
async def visao_admin(pedido: Request, ctx: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    produtos = await padrao.panorama(_repo(pedido).pool)
    ligados = sum(1 for p in produtos if p["followup"]["ligado"])
    return {"produtos": produtos, "totais": {"produtos": len(produtos), "ligados": ligados, "desligados": len(produtos) - ligados}}


class LigarEmLote(BaseModel):
    ids: list[str] = Field(default_factory=list)      # produtos ativados escolhidos
    todos_desligados: bool = False                    # ou: todos os ATIVOS com follow-up desligado
    simular: bool = False                             # só mostra quem seria ligado


@api.post("/admin/followup/ligar")
@registrado(lambda a: None if a["dados"].simular else "followup.ligado_em_lote", "Follow-up ligado com o padrão (admin, em lote)",
            referencia=lambda a: "todos os ativos desligados" if a["dados"].todos_desligados else f"{len(a['dados'].ids)} produto(s)",
            payload=lambda a: a["dados"],
            resultado=lambda _a, r: {"ligados": [f"{x['escritorio']} · {x['nome']}" for x in (r or {}).get("ligados") or []],
                                     "avisos": (r or {}).get("avisos")}, escritorio=None)
async def ligar_em_lote(dados: LigarEmLote, pedido: Request, ctx: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    """Liga com o padrão, um a um ou em lote. Exige a lista ou todos_desligados: nunca liga "tudo" sem pedir."""
    pool = _repo(pedido).pool
    if not dados.ids and not dados.todos_desligados:
        raise HTTPException(400, "Escolha os produtos ou marque todos os desligados.")
    produtos = {p["id_ativado"]: p for p in await padrao.panorama(pool)}
    if dados.todos_desligados:
        alvo = [i for i, p in produtos.items() if p["status"] == "ativo" and not p["followup"]["ligado"]]
    else:
        alvo = [i for i in dict.fromkeys(dados.ids) if i in produtos]
    if dados.simular:
        return {"simulado": True, "ligaria": [{"id_ativado": i, "nome": produtos[i]["nome"], "escritorio": produtos[i]["escritorio"]} for i in alvo]}
    ligados, avisos = [], []
    for id_ativado in alvo:
        feito = await padrao.ligar_com_padrao(pool, id_ativado, id_usuario=ctx.id_usuario, origem="admin")
        if feito:
            ligados.append({"id_ativado": id_ativado, "nome": feito["nome"], "escritorio": produtos[id_ativado]["escritorio"]})
            if feito["aviso"]:
                avisos.append(f"{produtos[id_ativado]['escritorio']} · {feito['nome']}: {feito['aviso']}")
    return {"simulado": False, "ligados": ligados, "avisos": avisos}


# ============================================================================ tela Follow-up do escritório
# Ferramentas › Follow-up (painel/src/telas/Followup.tsx) e a aba Follow-up do agente: lista dos agentes com o
# follow-up de cada um, histórico (o que saiu, o que não saiu e por quê) e o dashboard. Só leitura, uma ida ao banco
# por pedido (agregado no SQL). "Respondeu" = o lead escreveu em até RESPOSTA_H horas depois do envio.
RESPOSTA_H = 72

MOTIVOS: dict[str, str] = {
    "lead_respondeu": "o lead respondeu antes", "respondeu_durante_o_envio": "o lead respondeu na hora do envio",
    "equipe_falou": "alguém da equipe falou com o lead", "nova_resposta_da_ia": "a IA respondeu de novo (a cadência recomeçou)",
    "modo_teste": "agente em teste: o lead não está nos números de teste", "etapa_sem_followup": "etapa sem follow-up",
    "agente_pausado": "agente pausado", "followup_desligado": "follow-up desligado",
    "desistencia": "desistência: a IA encerrou a conversa",
    "janela_fechada_sem_modelo": "número oficial: janela de 24 h fechada e sem modelo aprovado",
    "fora_do_horario": "aguardando o horário de envio", "intervalo_minimo": "aguardando o intervalo mínimo",
    "lead_pediu_para_parar": "o lead pediu para não receber mais mensagens",
    "lead_pediu_para_esperar": "o lead pediu para falar depois",
    "contrato_assinado": "contrato já assinado", "lead_desqualificado": "lead desqualificado",
    "ia_desligada_no_escritorio": "IA desligada no escritório", "lead_sem_atendimento": "lead sem atendimento aberto",
    "lead_inexistente": "lead apagado", "limite_sem_resposta": "limite de toques para quem nunca respondeu",
    "agente_decidiu_nao_enviar": "o agente de follow-up decidiu não enviar",
    "escritorio_sem_conexao_whatsapp": "sem conexão com o WhatsApp",
    "enviado_antes_da_queda": "enviado (confirmado depois de uma queda)",
    "ia_desativada": "a IA foi desligada nesta conversa", "ia_desligada_durante_o_envio": "a IA foi desligada na hora do envio",
    "lead_suspeito": "lead suspeito (robô ou só figurinhas): a IA foi desligada",
    "sem_saldo": "o saldo da IA acabou", "lead_pausado": "conversa pausada (IA desligada ou equipe atendendo)",
    "lead_encerrado": "conversa encerrada", "cadencia_alterada": "a cadência mudou e este toque deixou de existir",
    "produto_na_lixeira": "o produto foi para a lixeira", "produto_excluido": "o produto foi excluído",
}


def motivo_legivel(motivo: str | None) -> str | None:
    """Motivo guardado no banco (código) em português para a tela."""
    if not motivo:
        return None
    if motivo in MOTIVOS:
        return MOTIVOS[motivo]
    if motivo.startswith("envio:"):
        return "falha no envio: " + motivo.split(":", 1)[1].strip()
    return motivo.replace("_", " ")


def resumo_da_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """Ligado?, tempos da cadência (horas) e etapas, sem quebrar com config antiga ou torta."""
    from app.followup import regras
    bruto = (config or {}).get("followup")
    try:
        c = regras.Config.de(bruto if isinstance(bruto, dict) else None)
        return {"ligado": bool(bruto) and c.ativo, "configurado": bool(bruto), "passos": [p.apos_horas for p in c.passos],
                "etapas": list(c.etapas), "horario": {"inicio": c.inicio, "fim": c.fim, "dias": list(c.dias)}}
    except (TypeError, ValueError, AttributeError):
        return {"ligado": False, "configurado": bool(bruto), "passos": [], "etapas": [], "horario": None}


def _dias(dias: int) -> int:
    return max(1, min(int(dias or 30), 180))


def _uuid_ou_400(valor: str) -> str:
    try:
        return str(uuid.UUID(valor))
    except ValueError:
        raise HTTPException(400, "Agente inválido.") from None


_RESPONDEU = f"""(f.situacao = 'enviado' and exists (select 1 from agentesia_mensagens m where m.id_lead = f.id_lead
                  and m.autor = 'lead' and m.enviada_em > f.enviado_em
                  and m.enviada_em < f.enviado_em + interval '{RESPOSTA_H} hours'))"""


@api.get("/followup/visao")
async def followup_visao(pedido: Request, dias: int = 30, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Agentes do escritório com o follow-up de cada um e os números do período (aba "Agentes" da tela)."""
    repo = _repo(pedido)
    esc = ctx.escritorio()
    agentes, numeros = await asyncio.gather(repo.agentes(esc), repo.pool.fetch(
        f"""select f.id_agente,
                   count(*) filter (where f.situacao in ('pendente', 'reservado')) as pendentes,
                   count(*) filter (where f.situacao = 'enviado' and f.enviado_em > now() - make_interval(days => $2)) as enviados,
                   count(*) filter (where f.situacao = 'falhou' and f.atualizado_em > now() - make_interval(days => $2)) as falhas,
                   count(*) filter (where f.enviado_em > now() - make_interval(days => $2) and {_RESPONDEU}) as respondidos,
                   max(f.enviado_em) as ultimo_envio
            from agentesia_followups f where f.id_escritorio = $1::uuid group by f.id_agente""", esc, _dias(dias)))
    por_agente = {str(n["id_agente"]): dict(n) for n in numeros}
    lista = []
    for a in agentes:
        n = por_agente.get(str(a["id"]), {})
        config = a.get("config") if isinstance(a.get("config"), dict) else json.loads(a.get("config") or "{}")
        lista.append({"id": str(a["id"]), "nome": a["nome"], "situacao": a.get("situacao"), "modo": a.get("modo"),
                      "numero_canal": a.get("numero_canal"), "tipo_canal": a.get("tipo_canal"),
                      "followup": resumo_da_config(config),
                      "pendentes": int(n.get("pendentes") or 0), "enviados": int(n.get("enviados") or 0),
                      "respondidos": int(n.get("respondidos") or 0), "falhas": int(n.get("falhas") or 0),
                      "ultimo_envio": n.get("ultimo_envio")})
    ligados = sum(1 for x in lista if x["followup"]["ligado"])
    return {"agentes": lista, "dias": _dias(dias),
            "totais": {"agentes": len(lista), "ligados": ligados, "desligados": len(lista) - ligados,
                       "pendentes": sum(x["pendentes"] for x in lista),
                       "pontos": sum(len(x["followup"]["passos"]) for x in lista if x["followup"]["ligado"])}}


def _textos(mensagens: Any) -> list[str]:
    if isinstance(mensagens, str):
        try:
            mensagens = json.loads(mensagens)
        except ValueError:
            return [mensagens]
    saida = []
    for m in mensagens if isinstance(mensagens, list) else []:
        texto = m.get("texto") if isinstance(m, dict) else m
        if isinstance(texto, str) and texto.strip():
            saida.append(texto.strip())
    return saida


GRUPOS_SITUACAO = {"enviado": ["enviado"], "agendado": ["pendente", "reservado"], "nao_enviado": ["cancelado"], "falhou": ["falhou"]}


@api.get("/followup/historico")
async def followup_historico(pedido: Request, agente: str | None = None, situacao: str | None = None, dias: int = 30,
                             busca: str | None = None, limite: int = 100, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Cada follow-up: para quem, de qual agente, qual tentativa, quando, o que foi enviado ou por que não foi."""
    filtros = ["f.id_escritorio = $1::uuid",
               "(f.situacao in ('pendente', 'reservado') or coalesce(f.enviado_em, f.atualizado_em) > now() - make_interval(days => $2))"]
    valores: list[Any] = [ctx.escritorio(), _dias(dias)]
    if agente:
        valores.append(_uuid_ou_400(agente))
        filtros.append(f"f.id_agente = ${len(valores)}::uuid")
    if situacao in GRUPOS_SITUACAO:
        valores.append(GRUPOS_SITUACAO[situacao])
        filtros.append(f"f.situacao = any(${len(valores)}::text[])")
    if busca and busca.strip():
        valores.append(f"%{busca.strip()[:60]}%")
        filtros.append(f"(ct.nome ilike ${len(valores)} or ct.telefone_normalizado like ${len(valores)})")
    valores.append(max(1, min(int(limite or 100), 300)))
    linhas = await _repo(pedido).pool.fetch(
        f"""select f.id, f.id_lead, f.id_agente, f.passo, f.situacao, f.motivo, f.mensagens, f.agendado_para, f.enviado_em,
                   f.atualizado_em, ct.nome, ct.telefone_normalizado as telefone, ag.nome as agente,
                   jsonb_array_length(case when jsonb_typeof(ag.config->'followup'->'passos') = 'array'
                                           then ag.config->'followup'->'passos' else '[]'::jsonb end) as total_passos,
                   {_RESPONDEU} as respondeu
            from agentesia_followups f join agentesia_leads l on l.id = f.id_lead
            join agentesia_contatos ct on ct.id = l.id_contato left join agentesia_agentes ag on ag.id = f.id_agente
            where {' and '.join(filtros)}
            order by (f.situacao in ('pendente', 'reservado')) desc,
                     case when f.situacao in ('pendente', 'reservado') then f.agendado_para end asc,
                     coalesce(f.enviado_em, f.atualizado_em) desc
            limit ${len(valores)}""", *valores)
    itens = []
    for r in linhas:
        total = int(r["total_passos"] or 0)
        itens.append({
            "id": str(r["id"]), "id_lead": str(r["id_lead"]), "id_agente": str(r["id_agente"]) if r["id_agente"] else None,
            "agente": r["agente"], "nome": r["nome"], "telefone": r["telefone"],
            "tentativa": r["passo"] + 1, "desistencia": bool(total) and r["passo"] >= total,
            "situacao": r["situacao"], "motivo": r["motivo"], "motivo_texto": motivo_legivel(r["motivo"]),
            "mensagens": _textos(r["mensagens"]), "agendado_para": r["agendado_para"], "enviado_em": r["enviado_em"],
            "atualizado_em": r["atualizado_em"], "respondeu": bool(r["respondeu"])})
    return {"itens": itens}


@api.get("/followup/dashboard")
async def followup_dashboard(pedido: Request, agente: str | None = None, dias: int = 30,
                             ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Enviados, respondidos, taxa de resposta, falhas, não enviados (por motivo), por tentativa, por dia e por agente."""
    valores: list[Any] = [ctx.escritorio(), _dias(dias)]
    filtro_agente = ""
    if agente:
        valores.append(_uuid_ou_400(agente))
        filtro_agente = "and f.id_agente = $3::uuid"
    linhas = await _repo(pedido).pool.fetch(
        f"""with base as (
              select f.passo, f.situacao, f.motivo, f.id_agente, coalesce(f.enviado_em, f.atualizado_em) as quando,
                     {_RESPONDEU} as respondeu
              from agentesia_followups f
              where f.id_escritorio = $1::uuid {filtro_agente}
                and (f.situacao in ('pendente', 'reservado')
                     or coalesce(f.enviado_em, f.atualizado_em) > now() - make_interval(days => $2)))
            select 'dia' as tipo, to_char(quando at time zone 'America/Sao_Paulo', 'YYYY-MM-DD') as chave,
                   count(*) filter (where situacao = 'enviado') as enviados, count(*) filter (where respondeu) as respondidos,
                   count(*) filter (where situacao = 'falhou') as falhas, count(*) filter (where situacao = 'cancelado') as cancelados,
                   0::bigint as pendentes
              from base where situacao not in ('pendente', 'reservado') group by 2
            union all
            select 'passo', (passo + 1)::text, count(*) filter (where situacao = 'enviado'), count(*) filter (where respondeu),
                   count(*) filter (where situacao = 'falhou'), count(*) filter (where situacao = 'cancelado'),
                   count(*) filter (where situacao in ('pendente', 'reservado'))
              from base group by 2
            union all
            select 'motivo', coalesce(motivo, ''), 0, 0, 0, count(*), 0 from base where situacao = 'cancelado' group by 2
            union all
            select 'agente', coalesce(id_agente::text, ''), count(*) filter (where situacao = 'enviado'),
                   count(*) filter (where respondeu), count(*) filter (where situacao = 'falhou'),
                   count(*) filter (where situacao = 'cancelado'), count(*) filter (where situacao in ('pendente', 'reservado'))
              from base group by 2""", *valores)
    por_dia, por_passo, motivos, por_agente = [], [], [], []
    for r in linhas:
        item = {k: int(r[k] or 0) for k in ("enviados", "respondidos", "falhas", "cancelados", "pendentes")}
        if r["tipo"] == "dia":
            por_dia.append({"dia": r["chave"], **item})
        elif r["tipo"] == "passo":
            por_passo.append({"tentativa": int(r["chave"]), **item})
        elif r["tipo"] == "motivo":
            motivos.append({"motivo": r["chave"] or None, "texto": motivo_legivel(r["chave"]) or "sem motivo",
                            "total": item["cancelados"]})
        else:
            por_agente.append({"id_agente": r["chave"] or None, **item})
    por_dia.sort(key=lambda x: x["dia"])
    por_passo.sort(key=lambda x: x["tentativa"])
    motivos.sort(key=lambda x: -x["total"])
    enviados = sum(p["enviados"] for p in por_passo)
    respondidos = sum(p["respondidos"] for p in por_passo)
    return {"dias": _dias(dias), "resposta_h": RESPOSTA_H,
            "totais": {"enviados": enviados, "respondidos": respondidos,
                       "taxa_resposta": round(100 * respondidos / enviados, 1) if enviados else 0.0,
                       "falhas": sum(p["falhas"] for p in por_passo), "nao_enviados": sum(p["cancelados"] for p in por_passo),
                       "pendentes": sum(p["pendentes"] for p in por_passo)},
            "por_dia": por_dia, "por_passo": por_passo, "motivos": motivos[:10], "por_agente": por_agente}
