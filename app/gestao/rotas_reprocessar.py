"""Botão "Responder agora" de uma conversa (POST /api/conversas/{id_lead}/reprocessar).

Para quando o lead ficou sem resposta (webhook perdido no meio, turno que quebrou, IA desligada na hora e religada): as
mensagens do lead depois da última fala da IA ou da equipe (até REPROCESSAR_JANELA_H, padrão 48 h) voltam a esperar
resposta e o lead é marcado para responder agora. Quem responde é o app "ia" (retomar_pendentes, em até ~30 s), pelo
caminho normal do turno: todas as conferências valem (IA desligada, agente pausado, horário, modo teste, saldo).

Pode: equipe LawChat e gestor do próprio escritório. A conversa precisa estar com a IA (estado ativo).
Mensagem que nunca chegou ao banco (webhook que a plataforma não entregou) não é buscada na plataforma: a API usada aqui
não lista as mensagens de um atendimento com segurança. Nesse caso a resposta diz que não há mensagem para responder.
"""

from __future__ import annotations

import os
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.gestao.rotas import GESTAO, Contexto, _repo

api = APIRouter(prefix="/api")


def _janela_h() -> float:
    try:
        return max(1.0, float(os.environ.get("AGENTESIA_REPROCESSAR_JANELA_H", "48")))
    except ValueError:
        return 48.0


@api.post("/conversas/{id_lead}/reprocessar")
async def reprocessar_conversa(id_lead: str, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", id_lead):
        raise HTTPException(404, "Conversa não encontrada.")
    repo = _repo(pedido)
    lead = await repo.pool.fetchrow(
        """select id, estado, coalesce(processando_ate > now(), false) as ocupado from agentesia_leads
           where id = $1::uuid and id_escritorio = $2::uuid""", id_lead, ctx.escritorio())
    if lead is None:
        raise HTTPException(404, "Conversa não encontrada.")
    if lead["estado"] != "ativo":
        raise HTTPException(409, "A IA não está atendendo esta conversa (pausada ou encerrada). Devolva para a IA antes.")
    if lead["ocupado"]:
        raise HTTPException(409, "A IA está respondendo esta conversa agora. Espere um minuto e confira.")
    async with repo.pool.acquire() as conexao, conexao.transaction():
        # As mensagens do lead depois da última fala que chegou a ele (IA entregue ou equipe): as que esperam resposta.
        ids = [r["id"] for r in await conexao.fetch(
            """select m.id from agentesia_mensagens m
               where m.id_lead = $1::uuid and m.autor = 'lead'
                 and m.enviada_em > now() - make_interval(secs => $2)
                 and m.enviada_em > coalesce((select max(s.enviada_em) from agentesia_mensagens s
                                              where s.id_lead = $1::uuid and (s.autor = 'humano' or (s.autor = 'ia'
                                                    and coalesce(s.situacao_envio, 'enviada') <> 'falhou'))),
                                             '-infinity'::timestamptz)""", id_lead, _janela_h() * 3600)]
        if not ids:
            raise HTTPException(409, "Não há mensagem do lead esperando resposta nesta conversa (a última fala é da IA "
                                     "ou da equipe). Se o lead escreveu e a mensagem não aparece aqui, ela não chegou "
                                     "ao sistema: fale com a equipe LawChat.")
        await conexao.execute("update agentesia_mensagens set id_turno = null where id = any($1::uuid[])", ids)
        await conexao.execute("update agentesia_leads set responder_apos = now() where id = $1::uuid", id_lead)
        await conexao.execute(
            """insert into agentesia_eventos (id_escritorio, id_lead, tipo, gravidade, responsavel, descricao, detalhe)
               values ($1::uuid, $2::uuid, 'reprocessado_pelo_painel', 'info', 'lawchat', $3, '{}'::jsonb)""",
            ctx.escritorio(), id_lead, f"Responder agora pelo painel: {len(ids)} mensagem(ns) do lead voltaram para a IA.")
    await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=ctx.escritorio(), tabela="agentesia_leads",
                                   id_registro=id_lead, acao="reprocessar", resumo="IA do lead: responder agora")
    atendimento = getattr(pedido.app.state, "atendimento", None)
    if atendimento is not None:                       # mesmo processo da IA (papel "tudo"): agenda já
        atendimento._agendar(id_lead, 0)
    return {"ok": True, "mensagens": len(ids)}
