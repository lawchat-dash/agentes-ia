"""Desligar e religar a IA de uma conversa (antigo fluxo "IA - Desativar (unificado)"). Ver docs/LIGAR_DESLIGAR_IA.md.

Três jeitos, todos com o MESMO efeito (mudar_ia):
  1. Etiqueta: pôr "🤖 IA Desativada" no contato desliga; tirar religa (evento CONTACT_TAG_UPDATE do webhook).
  2. Botão/automação: POST /webhook/helena/{escritorio}/ia com {acao: desligar|ligar, sessionId?, phone?, minutes?}
     ou o corpo do botão da Helena (como no n8n): {utm: {id_do_atendimento, telefone_do_contato, ...}, minutes?}.
  3. Painel (tela Conversas): POST /api/conversas/{id_lead}/ia com {acao: desativar|reativar, minutos?}.

Desligar grava o estado e o "até quando", cancela os follow-ups pendentes, põe a etiqueta na Helena (pela fila), deixa
nota com código DES-... e registra em agentesia_alteracoes quem fez. Religar faz o inverso (nota ATV-..., tira a
etiqueta). A desativação com prazo volta sozinha (religar_vencidas, a cada minuto), sem mandar mensagem ao lead.

Sem laço etiqueta <-> evento: a etiqueta que a própria LawChat pôs ou tirou volta como evento CONTACT_TAG_UPDATE; esse
eco é reconhecido (ação 'etiquetar' recente da LawChat no mesmo contato com o mesmo resultado) e ignorado.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime
from typing import Any

import asyncpg

from app.canal.helena import normalizar_telefone

ETIQUETA = "🤖 IA Desativada"
MOTIVO = "desativada_pela_equipe"
ECO_MINUTOS = 3                      # etiqueta mexida pela LawChat há menos que isto: o evento é o eco dela
ORIGENS = {"etiqueta": "pela etiqueta na Helena", "botao": "pelo botão da Helena", "painel": "pelo painel",
           "link": "pelo link da conversa", "prazo": "porque o prazo acabou"}


def _tem_etiqueta(tags: Any) -> bool:
    nomes = []
    for t in tags or []:
        nomes.append(str(t.get("name") or t.get("nome") or "") if isinstance(t, dict) else str(t))
    alvo = ETIQUETA.lower().replace("🤖", "").strip()
    return any(alvo in n.lower().replace("🤖", "").strip() for n in nomes)


def _quando(momento: datetime | None) -> str:
    """'25/11 às 14:30' no horário de Brasília."""
    from app.notificacoes import fuso
    return momento.astimezone(fuso()).strftime("%d/%m às %H:%M") if momento else ""


async def _enfileirar(conexao: Any, id_escritorio: str, id_lead: Any, tipo: str, chave: str, dados: dict[str, Any]) -> None:
    await conexao.execute(
        """insert into agentesia_acoes (id_escritorio, id_lead, tipo, chave_unica, dados)
           values ($1::uuid, $2, $3, $4, $5::jsonb) on conflict (chave_unica) do nothing""",
        id_escritorio, id_lead, tipo, chave, json.dumps(dados, ensure_ascii=False))


async def _eco_da_lawchat(conexao: Any, id_contato: Any, desligar: bool) -> bool:
    """Evento de etiqueta que é o eco de uma etiqueta que a LawChat mesma pôs (desligar) ou tirou (religar) há pouco
    em algum lead deste contato. Sem isso, desligar e religar rápido pelo painel virava liga-desliga-liga."""
    return bool(await conexao.fetchval(
        """select true from agentesia_acoes a join agentesia_leads l on l.id = a.id_lead
           where l.id_contato = $1 and a.tipo = 'etiquetar' and a.chave_unica like '%:ia:%'
             and a.atualizado_em > now() - make_interval(mins => $3)
             and (case when $2 then a.dados->'adicionar' else a.dados->'remover' end) ? $4
           limit 1""", id_contato, desligar, ECO_MINUTOS, ETIQUETA))


async def _responder_o_que_esperava(conexao: Any, id_lead: Any) -> bool:
    """Mensagem do lead guardada durante a desativação com prazo: a IA responde já (sem esperar a próxima)."""
    return bool(await conexao.fetchval(
        """update agentesia_leads set responder_apos = now()
           where id = $1 and exists (select 1 from agentesia_mensagens m where m.id_lead = $1 and m.autor = 'lead'
                                     and m.id_turno is null)
           returning true""", id_lead))


async def mudar_ia(pool: asyncpg.Pool, id_escritorio: str, *, ligar: bool, origem: str,
                   id_sessao: str | None = None, telefone: str | None = None, minutos: int = 0,
                   id_lead: str | None = None, id_usuario: str | None = None, de_quem: str | None = None,
                   extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Liga ou desliga a IA dos leads da conversa (pelo atendimento, pelo telefone ou, no painel, pelo id do lead).
    `minutos` > 0 ao desligar = desativação com prazo: depois dele a IA volta sozinha (religar_vencidas).
    `de_quem` troca o "pelo painel" da nota e do histórico (ex.: "pelo link da conversa (Ana)"); `extra` vai junto no
    registro do histórico (ex.: o id do usuário da plataforma que clicou)."""
    telefone = normalizar_telefone(telefone) if telefone else None
    if not id_sessao and not telefone and not id_lead:
        return {"encontrados": 0, "alterados": 0, "motivo": "sem_sessao_nem_telefone"}
    minutos = max(0, min(int(minutos or 0), 10080)) if not ligar else 0
    codigo = ("ATV-" if ligar else "DES-") + secrets.token_hex(3).upper()
    de_quem = de_quem or ORIGENS.get(origem, origem)
    async with pool.acquire() as conexao, conexao.transaction():
        leads = await conexao.fetch(
            """select l.id, l.id_contato, l.estado, l.motivo_estado, l.pausado_ate, l.id_sessao_helena
               from agentesia_leads l join agentesia_contatos c on c.id = l.id_contato
               where l.id_escritorio = $1::uuid and l.estado <> 'encerrado'
                 and (($4::uuid is not null and l.id = $4::uuid)
                      or ($4::uuid is null and (($2::text is not null and l.id_sessao_helena = $2)
                                                or ($3::text is not null and c.telefone_normalizado = $3))))
               for update of l""", id_escritorio, id_sessao, telefone, id_lead)
        alterados: list[dict[str, Any]] = []
        for lead in leads:
            if origem == "etiqueta" and await _eco_da_lawchat(conexao, lead["id_contato"], not ligar):
                continue
            # Pela etiqueta só desfaz o que a equipe fez (mexer em outra etiqueta não encerra a pausa do atendente).
            # Pelo botão e pelo painel é a equipe decidindo: religa qualquer pausa (pediu humano, sinal, trava, rajada...).
            religavel = lead["motivo_estado"] == MOTIVO if origem == "etiqueta" else True
            ja_desligada = lead["estado"] == "pausado" and lead["motivo_estado"] == MOTIVO
            if ligar and lead["estado"] == "pausado" and religavel:
                await conexao.execute(
                    "update agentesia_leads set estado = 'ativo', motivo_estado = null, pausado_ate = null where id = $1",
                    lead["id"])
                esperando = await _responder_o_que_esperava(conexao, lead["id"])
                alterados.append({**dict(lead), "esperando": esperando})
            elif not ligar and not (ja_desligada and (origem == "etiqueta" or (not minutos and lead["pausado_ate"] is None))):
                # Etiqueta repetida não mexe; botão ou painel numa conversa já desligada só valem para trocar o prazo.
                ate = await conexao.fetchval(
                    """update agentesia_leads set estado = 'pausado', motivo_estado = $3,
                              pausado_ate = case when $2::int > 0 then now() + make_interval(mins => $2::int) end,
                              responder_apos = null where id = $1 returning pausado_ate""", lead["id"], minutos, MOTIVO)
                await conexao.execute(
                    """update agentesia_followups set situacao = 'cancelado', motivo = 'ia_desativada'
                       where id_lead = $1 and situacao in ('pendente', 'reservado')""", lead["id"])
                alterados.append({**dict(lead), "ate": ate})
        for lead in alterados:
            if ligar:
                texto = (f"🤖 IA religada nesta conversa ({codigo}), {de_quem}. Ela segue da etapa em que o lead estava, "
                         "sem repetir as boas-vindas, e volta a responder na próxima mensagem do lead.")
                if lead["esperando"]:
                    texto += " O lead escreveu enquanto ela estava desligada: ela responde agora."
            elif minutos:
                texto = (f"🤖 IA desativada nesta conversa até {_quando(lead['ate'])} ({minutos} min, {codigo}), {de_quem}. "
                         "Depois disso ela volta sozinha, sem mandar mensagem; se o lead escrever no meio tempo, "
                         "ela responde quando voltar. Para religar antes, tire a etiqueta \"" + ETIQUETA + "\".")
            else:
                texto = (f"🤖 IA desativada nesta conversa ({codigo}), {de_quem}, até alguém religar. "
                         f"Para religar, tire a etiqueta \"{ETIQUETA}\" do contato ou use o painel.")
            await _enfileirar(conexao, id_escritorio, lead["id"], "nota", f"{lead['id']}:ia:{codigo}:nota", {"texto": texto})
            if origem != "etiqueta":                    # quem veio pela etiqueta já mexeu nela
                await _enfileirar(conexao, id_escritorio, lead["id"], "etiquetar", f"{lead['id']}:ia:{codigo}:etiqueta",
                                  {"adicionar": [] if ligar else [ETIQUETA], "remover": [ETIQUETA] if ligar else []})
        if leads and not alterados and origem != "etiqueta":
            # Botão apertado sem efeito: a equipe vê no chat por quê (antes saía 200 com alterados 0, calado).
            # A etiqueta fica de fora: a Helena repete o evento e cada repetição viraria uma nota.
            for lead in leads:
                if lead["id_sessao_helena"]:
                    await _enfileirar(conexao, id_escritorio, lead["id"], "nota", f"{lead['id']}:ia:{codigo}:nota",
                                      {"texto": f"🤖 IA já estava {'ligada' if ligar else 'desligada'} nesta conversa "
                                                f"({codigo})."})
        if not leads and origem != "etiqueta" and id_sessao:
            # Botão numa conversa que a LawChat não conhece (lead de outro número, encerrado, apagado): a equipe vê no chat.
            await _enfileirar(conexao, id_escritorio, None, "nota", f"sessao:{id_sessao}:ia:{codigo}:nota",
                              {"texto": f"🤖 Conversa não encontrada na LawChat IA ({codigo}): nada foi "
                                        f"{'ligado' if ligar else 'desligado'}. Se o lead já foi encerrado, a IA não atende "
                                        "mais esta conversa.", "id_sessao": id_sessao})
        if alterados:                         # a Helena repete eventos: só registra o que mudou de fato
            await conexao.execute(
                """insert into agentesia_alteracoes (id_escritorio, id_usuario, tabela, id_registro, acao, resumo, depois)
                   values ($1::uuid, $2::uuid, 'agentesia_leads', $3::uuid, $4, $5, $6::jsonb)""",
                id_escritorio, id_usuario, str(alterados[0]["id"]) if len(alterados) == 1 else None,
                "religou_ia" if ligar else "desligou_ia",
                f"IA {'religada' if ligar else 'desativada'} {de_quem} em {len(alterados)} conversa(s)"
                + (f" por {minutos} min" if minutos else "") + f" — {codigo}",
                json.dumps({**(extra or {}), "codigo": codigo, "origem": origem, "minutos": minutos or None,
                            "ate": alterados[0].get("ate").isoformat() if alterados[0].get("ate") else None,
                            "leads": [str(l["id"]) for l in alterados]}))
    primeiro = alterados[0] if alterados else {}
    return {"encontrados": len(leads), "alterados": len(alterados), "codigo": codigo,
            "pausado_ate": primeiro.get("ate").isoformat() if primeiro.get("ate") else None}


async def religar_vencidas(pool: asyncpg.Pool, id_lead: str | None = None) -> list[str]:
    """A desativação com prazo acabou: a IA volta sozinha, sem mandar nada ao lead. Tira a etiqueta, deixa nota ATV-...
    e registra; se o lead escreveu durante a pausa, a resposta fica marcada para já. Devolve os leads religados.
    O update com returning garante que só um servidor (ou só o turno que chegou na hora) faz isso."""
    async with pool.acquire() as conexao, conexao.transaction():
        linhas = await conexao.fetch(
            """update agentesia_leads set estado = 'ativo', motivo_estado = null, pausado_ate = null
               where estado = 'pausado' and motivo_estado = $1 and pausado_ate is not null and pausado_ate <= now()
                 and ($2::uuid is null or id = $2::uuid)
               returning id, id_escritorio""", MOTIVO, id_lead)
        for linha in linhas:
            codigo = "ATV-" + secrets.token_hex(3).upper()
            esperando = await _responder_o_que_esperava(conexao, linha["id"])
            texto = (f"🤖 IA religada sozinha nesta conversa ({codigo}): acabou o prazo da desativação. Ela não mandou "
                     "mensagem ao lead e segue da etapa em que ele estava.")
            texto += " O lead escreveu durante a pausa: ela responde agora." if esperando else \
                " Volta a responder na próxima mensagem do lead."
            await _enfileirar(conexao, str(linha["id_escritorio"]), linha["id"], "nota", f"{linha['id']}:ia:{codigo}:nota",
                              {"texto": texto})
            await _enfileirar(conexao, str(linha["id_escritorio"]), linha["id"], "etiquetar",
                              f"{linha['id']}:ia:{codigo}:etiqueta", {"adicionar": [], "remover": [ETIQUETA]})
            await conexao.execute(
                """insert into agentesia_alteracoes (id_escritorio, tabela, id_registro, acao, resumo, depois)
                   values ($1, 'agentesia_leads', $2, 'religou_ia', $3, $4::jsonb)""",
                linha["id_escritorio"], linha["id"], f"IA religada sozinha (acabou o prazo da desativação) — {codigo}",
                json.dumps({"codigo": codigo, "origem": "prazo", "leads": [str(linha["id"])]}))
    return [str(l["id"]) for l in linhas]


async def receber_evento_de_etiqueta(pool: asyncpg.Pool, id_escritorio: str, corpo: dict[str, Any]) -> dict[str, Any] | None:
    """CONTACT_TAG_UPDATE / CONTACT_UPDATE: a etiqueta "IA Desativada" liga ou desliga a IA daquele contato."""
    tipo = str(corpo.get("eventType") or "").upper()
    if tipo not in ("CONTACT_TAG_UPDATE", "CONTACT_UPDATE"):
        return None
    conteudo = corpo.get("content") or {}
    # Isolamento: veio a conta (companyId) no evento, tem de ser a do escritório desta URL; senão não mexe em nada.
    conta_evento = str(conteudo.get("companyId") or corpo.get("companyId") or "").strip().lower()
    if conta_evento:
        conta = await pool.fetchval("select id_conta_helena::text from agentesia_escritorios where id = $1::uuid",
                                    id_escritorio)
        if conta_evento != str(conta or "").lower():
            return {"feito": "ignorado", "motivo": "conta_de_outro_escritorio"}
    telefone = conteudo.get("phonenumber") or conteudo.get("phoneNumber")
    # Só decide com a lista de etiquetas do contato. Sem ela (evento que traz só a tag alterada, ou CONTACT_UPDATE de
    # outro campo) "sem etiqueta" religaria o lead que a equipe tirou da IA. Lista vazia explícita vale: tiraram todas.
    tags = (conteudo.get("tags") if isinstance(conteudo.get("tags"), list)
            else conteudo.get("tagNames") if isinstance(conteudo.get("tagNames"), list) else None)
    if tags is None:
        return {"feito": "ignorado", "motivo": "evento_sem_lista_de_tags"}
    if not telefone:
        return {"feito": "ignorado", "motivo": "contato_sem_telefone"}
    return {"feito": "ia", **await mudar_ia(pool, id_escritorio, ligar=not _tem_etiqueta(tags), origem="etiqueta", telefone=telefone)}
