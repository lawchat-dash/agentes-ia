"""Filtro de número por agente (botão "Filtrar número" no cartão do agente).

Ligado, o agente responde SÓ aos números da lista (modo "teste" + numeros_teste, que o motor já respeita:
app/pipeline.py, quem não está na lista fica sem resposta da IA, mas a mensagem é registrada). Desligado, volta a
responder todo mundo (modo "producao"). A lista fica guardada mesmo com o filtro desligado.

  GET /api/agentes/{id}/filtro-numeros   {ligado, numeros}
  PUT /api/agentes/{id}/filtro-numeros   {ligado, numeros}
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.canal.helena import normalizar_telefone
from app.gestao.rotas import GESTAO, Contexto, _repo

api = APIRouter(prefix="/api")


class Filtro(BaseModel):
    ligado: bool
    numeros: list[str] = Field(default_factory=list, max_length=20)


def _resposta(agente: dict[str, Any]) -> dict[str, Any]:
    return {"ligado": agente.get("modo") == "teste", "numeros": list(agente.get("numeros_teste") or [])}


@api.get("/agentes/{id_agente}/filtro-numeros")
async def ver_filtro(id_agente: str, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    agente = await _repo(pedido).agente(ctx.escritorio(), id_agente)
    if not agente:
        raise HTTPException(404, "Agente não encontrado.")
    return _resposta(agente)


@api.put("/agentes/{id_agente}/filtro-numeros")
async def salvar_filtro(id_agente: str, dados: Filtro, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    repo = _repo(pedido)
    agente = await repo.agente(ctx.escritorio(), id_agente)
    if not agente:
        raise HTTPException(404, "Agente não encontrado.")
    numeros: list[str] = []
    for bruto in dados.numeros:
        if not bruto.strip():
            continue
        numero = normalizar_telefone(bruto)
        if not numero:
            raise HTTPException(400, f"Número inválido: {bruto.strip()}. Use DDD + número, ex.: (31) 98888-7777.")
        numeros.append(numero)
    numeros = sorted(set(numeros))
    if dados.ligado and not numeros:
        raise HTTPException(400, "Coloque pelo menos um número para ligar o filtro.")
    campos = {"numeros_teste": numeros, "modo": "teste" if dados.ligado else "producao"}
    await repo.alterar_agente(ctx.escritorio(), id_agente, campos)
    await repo.registrar_alteracao(
        id_usuario=ctx.id_usuario, id_escritorio=ctx.escritorio(), tabela="agentesia_agentes", id_registro=id_agente,
        acao="filtro_numeros",
        resumo=(f"Filtro de número ligado em {agente.get('nome')}: responde só a {len(numeros)} número(s)" if dados.ligado
                else f"Filtro de número desligado em {agente.get('nome')}: responde a todos"),
        antes=_resposta(agente), depois={"ligado": dados.ligado, "numeros": numeros})
    return {"ligado": dados.ligado, "numeros": numeros}


class Zerar(BaseModel):
    numero: str


@api.post("/agentes/{id_agente}/filtro-numeros/zerar")
async def zerar_numero(id_agente: str, dados: Zerar, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Só a equipe LawChat: apaga a memória da IA sobre um NÚMERO DE TESTE do agente (conversa, fatos, etapa,
    follow-ups, contrato de teste). A próxima mensagem dele recomeça do primeiro agente (SDR). Só vale para números
    que estão na lista do filtro: nunca apaga um cliente de verdade."""
    if not ctx.lawchat:
        raise HTTPException(403, "Só a equipe LawChat pode zerar um número.")
    repo = _repo(pedido)
    agente = await repo.agente(ctx.escritorio(), id_agente)
    if not agente:
        raise HTTPException(404, "Agente não encontrado.")
    numero = normalizar_telefone(dados.numero or "")
    if not numero or numero not in set(agente.get("numeros_teste") or []):
        raise HTTPException(400, "Só dá para zerar um número que está na lista do filtro deste agente.")
    # O que a plataforma tem deste lead (antes de apagar): atendimento, contato e card, para limpar lá também.
    antes = await repo.pool.fetch(
        """select l.id_sessao_helena, c.id_contato_helena, cc.id_card_helena
             from agentesia_leads l join agentesia_contatos c on c.id = l.id_contato
             left join agentesia_crm_cards cc on cc.id_lead = l.id
            where l.id_escritorio = $1::uuid and c.telefone_normalizado = $2
              and (l.id_agente = $3::uuid or l.id_agente is null)""", ctx.escritorio(), numero, id_agente)
    apagados = await repo.pool.fetch(
        """delete from agentesia_leads l using agentesia_contatos c
            where l.id_contato = c.id and l.id_escritorio = $1::uuid and c.telefone_normalizado = $2
              and (l.id_agente = $3::uuid or l.id_agente is null) returning l.id::text""",
        ctx.escritorio(), numero, id_agente)
    limpeza = await _limpar_na_plataforma(pedido, repo, ctx.escritorio(), antes)
    await repo.registrar_alteracao(
        id_usuario=ctx.id_usuario, id_escritorio=ctx.escritorio(), tabela="agentesia_leads", id_registro=id_agente,
        acao="zerou_numero_teste", resumo=f"Zerou a memória do número de teste em {agente.get('nome')} (volta ao início)",
        depois={"leads_apagados": len(apagados), "plataforma": limpeza})
    return {"zerado": True, "leads_apagados": len(apagados), "plataforma": limpeza}


NOTA_ZERADO = "🔄 Memória da IA zerada (teste): a próxima mensagem deste número recomeça do primeiro agente (SDR)."


async def _limpar_na_plataforma(pedido: Request, repo: Any, id_escritorio: str, linhas: list[Any]) -> dict[str, Any]:
    """Zerar também na plataforma: tira a etiqueta "🤖 IA Desativada" e as das etapas, volta o card para a coluna SDR
    e deixa uma nota. 26/11: o lead zerado continuava com a etiqueta de IA desativada e nada avisava no chat.
    Falha aqui não desfaz o zerar (a memória já foi apagada): só volta o que não deu."""
    from app import automacoes, ia_controle
    from app.banco.postgres import token_helena
    from app.canal.helena_conta import HelenaConta

    feito: dict[str, Any] = {"etiquetas": False, "card": False, "nota": False}
    if not linhas:
        return feito
    token = await token_helena(repo.pool, id_escritorio)
    if not token:
        feito["erro"] = "escritório sem conexão com a plataforma"
        return feito
    crm = await repo.pool.fetchval(
        "select config from agentesia_integracoes where id_escritorio = $1::uuid and tipo = 'crm'", id_escritorio)
    crm = crm if isinstance(crm, dict) else (__import__("json").loads(crm) if crm else {})
    coluna_sdr = ((crm or {}).get("etapas_por_tipo") or {}).get("SDR")
    cfg = getattr(pedido.app.state, "cfg", None)
    helena = HelenaConta(token, getattr(cfg, "helena_url", None) or "https://api.helena.run")
    etiquetas = [ia_controle.ETIQUETA, *[e for e in automacoes.ETIQUETA_DO_TIPO.values() if e != automacoes.ETIQUETA_SDR]]
    for linha in linhas:
        try:
            if linha["id_contato_helena"]:
                await helena.etiquetar(linha["id_contato_helena"], etiquetas, remover=True)
                await helena.etiquetar(linha["id_contato_helena"], [automacoes.ETIQUETA_SDR])
                feito["etiquetas"] = True
        except Exception as erro:                             # noqa: BLE001  a limpeza é um extra
            feito["erro_etiquetas"] = type(erro).__name__
        try:
            if linha["id_card_helena"] and coluna_sdr:
                await helena.mover_card(linha["id_card_helena"], coluna_sdr)
                feito["card"] = True
        except Exception as erro:                             # noqa: BLE001
            feito["erro_card"] = type(erro).__name__
        try:
            if linha["id_sessao_helena"]:
                await helena.nota(linha["id_sessao_helena"], NOTA_ZERADO)
                feito["nota"] = True
        except Exception as erro:                             # noqa: BLE001
            feito["erro_nota"] = type(erro).__name__
    return feito
