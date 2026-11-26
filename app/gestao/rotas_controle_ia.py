"""Controle da IA na Central de Atendimento (bolinha flutuante e app "Controle da IA" da plataforma de atendimento).

  GET  /api/controle-ia/lead?sessao=&contato=&telefone=   acha o lead do escritório: pelo atendimento (sessão), pelo
                                                          contato ou pelo telefone (DDD + 8 últimos dígitos, como o
                                                          fluxo antigo); devolve o status da IA e "por" (como achou)
  POST /api/controle-ia/desativar {id_lead, minutos?}     0 = até religar; 30, 120 ou 1440 = volta sozinha depois
  POST /api/controle-ia/reativar  {id_lead}
  GET  /api/controle-ia/buscar?q=                         plano B: até 10 leads do escritório por nome ou telefone

Desativar e reativar passam pelo MESMO serviço da tela Conversas (app/ia_controle.mudar_ia, origem 'painel'): estado
e prazo, follow-ups cancelados, etiqueta "🤖 IA Desativada", nota DES/ATV no atendimento e histórico.
Clique repetido não duplica nota: o mudar_ia, numa conversa que já está no estado pedido, deixaria uma nota
"IA já estava ...". Aqui isso é conferido antes (e o mesmo prazo pedido de novo em segundos vale como repetição).
Telefone sempre mascarado na resposta.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.canal.helena import normalizar_telefone, so_digitos
from app.gestao.rotas import NOMES_ETAPAS, TODOS, Contexto, _repo
from app.gestao.rotas_execucoes import mascarar_telefone

api = APIRouter(prefix="/api/controle-ia")

UUID = re.compile(r"[0-9a-fA-F-]{36}")
ID_EXTERNO = re.compile(r"[0-9A-Za-z_.:-]{1,80}")
REPETICAO_S = 15            # o mesmo prazo pedido de novo dentro disto é clique repetido (não mexe nem deixa nota)
MOTIVOS = {
    "desativada_pela_equipe": "Desativada pela equipe",
    "humano_assumiu": "Um atendente assumiu a conversa",
    "pediu_humano": "O lead pediu um atendente",
    "pediu_parar": "O lead pediu para parar",
    "desqualificado": "Lead desqualificado",
    "encerrado_pela_equipe": "Encerrada pela equipe",
}

_SELECAO = """
    select l.id, l.estado, l.motivo_estado, l.pausado_ate, l.id_sessao_helena, c.nome, c.telefone_normalizado,
           e.codigo as etapa, a.nome as agente,
           (es.ia_desligada or es.situacao <> 'ativo') as ia_desligada_escritorio
    from agentesia_leads l join agentesia_contatos c on c.id = l.id_contato
    join agentesia_escritorios es on es.id = l.id_escritorio
    left join agentesia_agente_etapas e on e.id = l.id_etapa
    left join agentesia_agentes a on a.id = l.id_agente
    where l.id_escritorio = $1::uuid"""
# Mais de um lead (o mesmo contato em dois números do escritório): o que não está encerrado e falou por último.
_ORDEM = " order by (l.estado = 'encerrado'), l.ultima_mensagem_lead_em desc nulls last, l.criado_em desc limit 1"


def _iso(momento: datetime | None) -> str | None:
    return momento.isoformat() if momento else None


async def _escritorio(pool: Any, ctx: Contexto, conta: str | None) -> str:
    """Escritório do pedido. A equipe LawChat pode vir pela ponte aberta fora do painel (sem o escritório escolhido no
    navegador): ali vale a conta da plataforma que veio na URL (id_da_conta). Gestor e atendente: sempre o deles."""
    conta = (conta or "").strip()
    if ctx.lawchat and conta and UUID.fullmatch(conta):
        achado = await pool.fetchval("select id from agentesia_escritorios where id_conta_helena = $1 limit 1", conta)
        if achado:
            return str(achado)
    return ctx.escritorio()


def _resumo(linha: Any, por: str | None = None) -> dict[str, Any]:
    estado = linha["estado"]
    etapa = linha["etapa"]
    return {
        "id_lead": str(linha["id"]), "nome": linha["nome"] or "Sem nome",
        "telefone": mascarar_telefone(linha["telefone_normalizado"]),
        "agente": linha["agente"], "etapa": etapa, "etapa_nome": NOMES_ETAPAS.get(etapa or "", etapa),
        "estado": estado, "ia_ligada": estado == "ativo", "encerrado": estado == "encerrado",
        "motivo": MOTIVOS.get(linha["motivo_estado"] or "", linha["motivo_estado"]),
        "pausado_ate": _iso(linha["pausado_ate"]), "tem_atendimento": bool(linha["id_sessao_helena"]),
        "ia_desligada_escritorio": bool(linha["ia_desligada_escritorio"]), **({"por": por} if por else {}),
    }


def _partes_do_telefone(bruto: str) -> tuple[str | None, str | None, str]:
    """(normalizado, DDD, 8 últimos dígitos). Sem DDD (8 ou 9 dígitos soltos), só os 8 últimos."""
    digitos = so_digitos(bruto).lstrip("0")
    if len(digitos) < 8:
        raise HTTPException(400, "Telefone curto demais: mande pelo menos os 8 últimos dígitos.")
    normalizado = normalizar_telefone(digitos) if len(digitos) >= 10 else None
    ddd = normalizado[2:4] if normalizado and normalizado.startswith("55") and len(normalizado) in (12, 13) else None
    return normalizado, ddd, digitos[-8:]


async def _por_telefone(pool: Any, id_escritorio: str, bruto: str) -> Any:
    normalizado, ddd, oito = _partes_do_telefone(bruto)
    if normalizado:
        exato = await pool.fetchrow(_SELECAO + " and c.telefone_normalizado = $2" + _ORDEM, id_escritorio, normalizado)
        if exato:
            return exato
    # Como o fluxo antigo: DDD + 8 últimos dígitos (a plataforma às vezes manda sem o nono dígito, ou com outro formato).
    contatos = await pool.fetch(
        """select id from agentesia_contatos
           where id_escritorio = $1::uuid and right(telefone_normalizado, 8) = $2
             and ($3::text is null or (telefone_normalizado like '55%' and substr(telefone_normalizado, 3, 2) = $3))
           limit 2""", id_escritorio, oito, ddd)
    if len(contatos) > 1:
        raise HTTPException(409, "Mais de um contato com esse final de telefone. Busque o lead pelo nome.")
    if not contatos:
        return None
    return await pool.fetchrow(_SELECAO + " and l.id_contato = $2" + _ORDEM, id_escritorio, contatos[0]["id"])


@api.get("/lead")
async def lead_da_conversa(pedido: Request, sessao: str = "", contato: str = "", telefone: str = "", conta: str = "",
                           ctx: Contexto = Depends(TODOS)) -> dict[str, Any]:
    """Lead da conversa aberta na Central: pela sessão (atendimento), pelo contato e, por último, pelo telefone."""
    sessao, contato, telefone = sessao.strip(), contato.strip(), telefone.strip()
    if not (sessao or contato or telefone):
        raise HTTPException(400, "Informe o atendimento, o contato ou o telefone da conversa.")
    pool = _repo(pedido).pool
    id_escritorio = await _escritorio(pool, ctx, conta)
    if sessao and ID_EXTERNO.fullmatch(sessao):
        linha = await pool.fetchrow(_SELECAO + " and l.id_sessao_helena = $2" + _ORDEM, id_escritorio, sessao)
        if linha:
            return _resumo(linha, "sessao")
    if contato and ID_EXTERNO.fullmatch(contato):
        linha = await pool.fetchrow(_SELECAO + " and c.id_contato_helena = $2" + _ORDEM, id_escritorio, contato)
        if linha:
            return _resumo(linha, "contato")
    if telefone:
        linha = await _por_telefone(pool, id_escritorio, telefone)
        if linha:
            return _resumo(linha, "telefone")
    raise HTTPException(404, "Esta conversa não tem lead da IA neste escritório (a IA ainda não atendeu este contato).")


@api.get("/buscar")
async def buscar(pedido: Request, q: str = "", conta: str = "", ctx: Contexto = Depends(TODOS)) -> list[dict[str, Any]]:
    """Plano B (a conversa aberta não foi identificada): até 10 leads por nome ou telefone."""
    termo = re.sub(r"[%_\\]", "", q.strip())[:60]
    digitos = so_digitos(termo)
    if len(termo) < 2:
        return []
    pool = _repo(pedido).pool
    linhas = await pool.fetch(
        _SELECAO + """ and (c.nome ilike '%' || $2 || '%' or ($3::text <> '' and c.telefone_normalizado like '%' || $3 || '%'))
        order by (l.estado = 'encerrado'), l.ultima_mensagem_lead_em desc nulls last, l.criado_em desc limit 10""",
        await _escritorio(pool, ctx, conta), termo, digitos if len(digitos) >= 4 else "")
    return [_resumo(linha) for linha in linhas]


class Desativar(BaseModel):
    id_lead: str
    conta: str | None = None
    minutos: Literal[0, 30, 120, 1440] = 0


class Reativar(BaseModel):
    id_lead: str
    conta: str | None = None


async def _lead(pool: Any, id_escritorio: str, id_lead: str) -> Any:
    if not UUID.fullmatch(id_lead or ""):
        raise HTTPException(404, "Conversa não encontrada.")
    linha = await pool.fetchrow(_SELECAO + " and l.id = $2::uuid", id_escritorio, id_lead)
    if not linha:
        raise HTTPException(404, "Conversa não encontrada.")
    if linha["estado"] == "encerrado":
        raise HTTPException(409, "Esta conversa está encerrada: a IA não atende mais. Para voltar, use a tela Conversas.")
    return linha


def _prazo(minutos: int) -> str:
    return {30: "30 minutos", 120: "2 horas", 1440: "24 horas"}.get(minutos, f"{minutos} min")


async def _mudar(pedido: Request, ctx: Contexto, id_lead: str, ligar: bool, minutos: int,
                 conta: str | None) -> dict[str, Any]:
    from app import ia_controle

    pool = _repo(pedido).pool
    id_escritorio = await _escritorio(pool, ctx, conta)
    antes = await _lead(pool, id_escritorio, id_lead)
    desligada_pela_equipe = antes["estado"] == "pausado" and antes["motivo_estado"] == ia_controle.MOTIVO
    repetido = False
    if ligar:
        repetido = antes["estado"] == "ativo"
    elif desligada_pela_equipe and not minutos and antes["pausado_ate"] is None:
        repetido = True
    elif desligada_pela_equipe and minutos:
        repetido = bool(await pool.fetchval(
            """select true from agentesia_alteracoes
               where id_escritorio = $1::uuid and tabela = 'agentesia_leads' and id_registro = $2::uuid
                 and acao = 'desligou_ia' and (depois->>'minutos')::int = $3
                 and criado_em > now() - make_interval(secs => $4) limit 1""",
            id_escritorio, id_lead, minutos, REPETICAO_S))
    if repetido:
        return {"ok": True, "mudou": False, "lead": _resumo(antes),
                "mensagem": "A IA já estava ligada nesta conversa." if ligar else
                ("A IA já estava desativada nesta conversa." if not minutos else
                 f"A IA já foi desativada por {_prazo(minutos)} agora há pouco.")}
    r = await ia_controle.mudar_ia(pool, id_escritorio, ligar=ligar, origem="painel", id_lead=id_lead,
                                   minutos=minutos, id_usuario=ctx.id_usuario)
    depois = await pool.fetchrow(_SELECAO + " and l.id = $2::uuid", id_escritorio, id_lead)
    if not r.get("alterados"):
        raise HTTPException(409, f"Não deu para {'religar' if ligar else 'desativar'} a IA agora. Atualize e tente de novo.")
    if ligar:
        mensagem = "IA religada. Ela volta a responder na próxima mensagem do lead."
    elif minutos:
        mensagem = (f"IA desativada por {_prazo(minutos)} (volta sozinha em {ia_controle._quando(depois['pausado_ate'])}). "
                    "Ficou uma nota no atendimento.")
    else:
        mensagem = "IA desativada até alguém religar. Ficou uma nota no atendimento."
    return {"ok": True, "mudou": True, "codigo": r.get("codigo"), "mensagem": mensagem, "lead": _resumo(depois)}


@api.post("/desativar")
async def desativar(dados: Desativar, pedido: Request, ctx: Contexto = Depends(TODOS)) -> dict[str, Any]:
    return await _mudar(pedido, ctx, dados.id_lead, ligar=False, minutos=dados.minutos, conta=dados.conta)


@api.post("/reativar")
async def reativar(dados: Reativar, pedido: Request, ctx: Contexto = Depends(TODOS)) -> dict[str, Any]:
    return await _mudar(pedido, ctx, dados.id_lead, ligar=True, minutos=0, conta=dados.conta)
