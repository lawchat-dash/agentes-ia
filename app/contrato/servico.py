"""Contrato: reserva da versão, gravação e assinatura, contra o banco. Usado pelo Executor (app/acoes.py).

Reserva e gravação são transações curtas com o lead travado (for update): dois pedidos ao mesmo tempo
nunca criam dois documentos na ZapSign.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg

from app.canal.zapsign import DocumentoZapSign
from app.contrato.assinatura import assinante_do_lead_na_geracao

# Eventos que pedem a releitura do documento. A decisão é sempre da releitura (nunca do aviso).
EVENTOS_QUE_RELEEM = ("doc_signed", "doc_refused", "doc_deleted", "doc_expired")

RESERVA_MINUTOS = 3


@dataclass
class Reserva:
    decisao: str              # reservado | mesmo | gerando | limite | ja_assinado
    id_contrato: str | None = None
    versao: int | None = None
    link_atual: str | None = None
    documentos_feitos: int = 0


async def reservar(pool: asyncpg.Pool, *, id_escritorio: str, id_lead: str, dados: dict[str, str], hash_dados: str,
                   limite: int = 3, id_acao: str | None = None) -> Reserva:
    async with pool.acquire() as conexao, conexao.transaction():
        await conexao.execute("select 1 from agentesia_leads where id = $1::uuid for update", id_lead)
        linhas = [dict(r) for r in await conexao.fetch(
            "select * from agentesia_contratos where id_lead = $1::uuid order by versao desc", id_lead)]
        ultimo = linhas[0] if linhas else None
        vigente = next((x for x in linhas if x["situacao"] == "gerado"), None)
        feitos = sum(1 for x in linhas if x["situacao"] in ("gerado", "substituido", "assinado"))
        if any(x["situacao"] == "assinado" for x in linhas):
            return Reserva("ja_assinado", link_atual=(vigente or ultimo or {}).get("link"), documentos_feitos=feitos)
        if vigente and vigente["dados_hash"] == hash_dados:
            return Reserva("mesmo", str(vigente["id"]), vigente["versao"], vigente["link"], feitos)
        reservado = next((x for x in linhas if x["situacao"] == "reservado"), None)
        if reservado and reservado["reservado_ate"] and reservado["reservado_ate"] > await conexao.fetchval("select now()"):
            return Reserva("gerando", str(reservado["id"]), reservado["versao"], (vigente or {}).get("link"), feitos)
        if feitos >= limite:
            return Reserva("limite", link_atual=(vigente or {}).get("link"), documentos_feitos=feitos)
        reaproveitar = reservado or (ultimo if ultimo and ultimo["situacao"] == "erro" else None)
        if reaproveitar:
            await conexao.execute(
                """update agentesia_contratos set situacao = 'reservado', dados = $2::jsonb, dados_hash = $3, erro = null,
                          causa_erro = null, reservado_ate = now() + make_interval(mins => $4), id_acao = $5::uuid
                   where id = $1""", reaproveitar["id"], json.dumps(dados, ensure_ascii=False), hash_dados,
                RESERVA_MINUTOS, id_acao)
            return Reserva("reservado", str(reaproveitar["id"]), reaproveitar["versao"], (vigente or {}).get("link"), feitos)
        versao = (ultimo["versao"] if ultimo else 0) + 1
        novo = await conexao.fetchval(
            """insert into agentesia_contratos (id_escritorio, id_lead, versao, dados, dados_hash, situacao, reservado_ate, id_acao)
               values ($1::uuid, $2::uuid, $3, $4::jsonb, $5, 'reservado', now() + make_interval(mins => $6), $7::uuid)
               returning id""", id_escritorio, id_lead, versao, json.dumps(dados, ensure_ascii=False), hash_dados,
            RESERVA_MINUTOS, id_acao)
        return Reserva("reservado", str(novo), versao, (vigente or {}).get("link"), feitos)


async def gravar_gerado(pool: asyncpg.Pool, *, id_contrato: str, documento: DocumentoZapSign, id_modelo: str) -> int:
    """Grava o documento e substitui a versão anterior, na mesma transação. Devolve quantas foram substituídas."""
    async with pool.acquire() as conexao, conexao.transaction():
        linha = await conexao.fetchrow("select id_lead, dados from agentesia_contratos where id = $1::uuid", id_contrato)
        id_lead = linha["id_lead"]
        dados = linha["dados"] if isinstance(linha["dados"], dict) else json.loads(linha["dados"] or "{}")
        substituidas = await conexao.execute(
            "update agentesia_contratos set situacao = 'substituido' where id_lead = $1 and situacao = 'gerado' and id <> $2::uuid",
            id_lead, id_contrato)
        # O signatário do lead é o que criamos (nome e telefone do create-doc), não o primeiro da lista: no modelo com
        # o advogado como signatário fixo, o [0] pode ser o escritório (o lead recebia o link do advogado).
        lead = assinante_do_lead_na_geracao(documento, nome=dados.get("nome"), telefone=dados.get("telefone"),
                                            id_externo=id_contrato)
        await conexao.execute(
            """update agentesia_contratos set situacao = 'gerado', id_documento_externo = $2, link = $3,
                      id_assinante_externo = $4, id_modelo = $5, gerado_em = now(), reservado_ate = null, erro = null
               where id = $1::uuid""", id_contrato, documento.token, (lead.link if lead else None) or documento.link,
            lead.token if lead else None, id_modelo)
    return int(substituidas.split()[-1])


async def versoes_para_cancelar(pool: asyncpg.Pool, *, id_lead: str, id_contrato_novo: str) -> list[dict[str, Any]]:
    """Versões substituídas deste lead que ainda têm documento na ZapSign (o cancelamento é idempotente pela chave)."""
    linhas = await pool.fetch(
        """select id, versao, id_documento_externo from agentesia_contratos
           where id_lead = $1::uuid and id <> $2::uuid and situacao = 'substituido' and id_documento_externo is not null""",
        id_lead, id_contrato_novo)
    return [dict(x) for x in linhas]


async def geracao_obsoleta(pool: asyncpg.Pool, id_acao: Any) -> bool:
    """Uma geração que voltou tarde (esperava nova tentativa) e já tem um pedido MAIS NOVO de contrato para o mesmo lead
    (o lead corrigiu um dado): gerar agora mandaria um link com os dados velhos por cima da correção."""
    return bool(await pool.fetchval(
        """select exists(select 1 from agentesia_acoes a join agentesia_acoes n
                         on n.id_lead = a.id_lead and n.tipo = 'gerar_contrato' and n.id <> a.id
                        and n.criado_em > a.criado_em and n.situacao in ('pendente', 'executando', 'feita')
                         where a.id = $1::uuid)""", str(id_acao)))


async def atualizar_contato(pool: asyncpg.Pool, *, id_contrato: str, dados: dict[str, str], hash_dados: str) -> None:
    """Telefone ou e-mail trocados no signatário: o contrato vigente passa a ter os dados novos (o mesmo pedido de novo
    cai em 'mesmo link'), sem versão nova."""
    await pool.execute(
        "update agentesia_contratos set dados = $2::jsonb, dados_hash = $3 where id = $1::uuid and situacao = 'gerado'",
        id_contrato, json.dumps(dados, ensure_ascii=False), hash_dados)


async def marcar_encerrado(pool: asyncpg.Pool, *, id_contrato: str, causa: str, motivo: str | None) -> bool:
    """Contrato vigente recusado, cancelado, excluído ou vencido na ZapSign: vira 'cancelado' com a causa
    (cancelado | excluido | expirado). Verdadeiro só na primeira vez (efeitos uma vez)."""
    linha = await pool.fetchrow(
        """update agentesia_contratos set situacao = 'cancelado', causa_erro = $2, erro = $3, reservado_ate = null
           where id = $1::uuid and situacao = 'gerado' returning id""", id_contrato, causa, (motivo or "")[:500] or None)
    return linha is not None


async def pausar_ia(pool: asyncpg.Pool, id_lead: str, motivo: str) -> bool:
    """A IA para de responder este lead (uma pessoa precisa conversar). Não mexe em quem já está pausado/encerrado."""
    resultado = await pool.execute(
        """update agentesia_leads set estado = 'pausado', motivo_estado = $2, pausado_ate = null, responder_apos = null
           where id = $1::uuid and estado = 'ativo'""", id_lead, motivo)
    return resultado.endswith("1")


async def guardar_arquivo(pool: asyncpg.Pool, *, id_contrato: str, url: str) -> None:
    await pool.execute("update agentesia_contratos set arquivo_assinado = $2 where id = $1::uuid", id_contrato, url)


def momento_da_consulta(gerado_em: datetime, agora: datetime) -> str | None:
    """Rede de segurança (o aviso da ZapSign pode não chegar): de 30 em 30 min nas primeiras 48 h, depois 1 vez por dia
    até 30 dias. Devolve a 'janela' da consulta (vira a chave única: uma consulta por janela) ou None (fora do prazo)."""
    idade = (agora - gerado_em).total_seconds()
    if idade < 30 * 60 or idade > 30 * 86400:
        return None
    if idade < 48 * 3600:
        return f"m{int(agora.timestamp() // 1800)}"
    return f"d{agora.date().isoformat()}"


async def agendar_consultas(pool: asyncpg.Pool, agora: datetime | None = None) -> int:
    """Põe na fila a releitura dos contratos 'gerado' sem resposta (no máximo uma por janela de cada contrato)."""
    agora = agora or await pool.fetchval("select now()")
    linhas = await pool.fetch(
        """select id, id_escritorio, id_lead, id_documento_externo, gerado_em from agentesia_contratos
           where provedor = 'zapsign' and situacao = 'gerado' and id_documento_externo is not null
             and gerado_em between $1::timestamptz - interval '30 days' and $1::timestamptz - interval '30 minutes'""", agora)
    novas = 0
    for k in linhas:
        janela = momento_da_consulta(k["gerado_em"], agora)
        if not janela:
            continue
        resultado = await pool.execute(
            """insert into agentesia_acoes (id_escritorio, id_lead, tipo, chave_unica, dados)
               values ($1, $2, 'verificar_assinatura', $3, $4::jsonb) on conflict (chave_unica) do nothing""",
            k["id_escritorio"], k["id_lead"], f"zapsign:consulta:{k['id']}:{janela}",
            json.dumps({"token_documento": k["id_documento_externo"], "origem": "consulta"}))
        novas += int(resultado.split()[-1])
    return novas


async def marcar_falha(pool: asyncpg.Pool, *, id_contrato: str, causa: str, erro: str) -> None:
    await pool.execute(
        """update agentesia_contratos set situacao = 'erro', causa_erro = $2, erro = $3, reservado_ate = null
           where id = $1::uuid and situacao = 'reservado'""", id_contrato, causa, erro[:500])


async def mover_lead_para_etapa(pool: asyncpg.Pool, id_lead: str, codigo: str, *, estado: str | None = None,
                                motivo_estado: str | None = None, origem: str | None = "contrato") -> bool:
    """Põe o lead na etapa do agente com este código. Falso se o agente não tem a etapa ou se, sem mudar o estado, o
    lead já estava nela: quem chama dispara 'etapa:<codigo>' só quando a etapa mudou de fato (a geração da v2, v3 do
    contrato com o lead já em assinatura repetia o aviso e a nota a cada versão).
    `origem` vai para o histórico de etapa (agentesia_lead_etapas, migração 006) pelo set_config local da própria
    instrução: o gatilho do banco lê 'agentesia.origem_etapa' (contrato, equipe...)."""
    resultado = await pool.execute(
        """with origem as (select set_config('agentesia.origem_etapa', coalesce($5::text, ''), true) as valor)
           update agentesia_leads l set id_etapa = e.id,
                  estado = coalesce($3::text, l.estado), motivo_estado = case when $3::text is null then l.motivo_estado else $4::text end
           from agentesia_agente_etapas e, origem
           where l.id = $1::uuid and e.id_agente = l.id_agente and e.codigo = $2
             and ($3::text is not null or l.id_etapa is distinct from e.id)""",
        id_lead, codigo, estado, motivo_estado, origem)
    return resultado.endswith("1")


async def contrato_para_verificar(pool: asyncpg.Pool, *, id_lead: str | None, token_documento: str | None) -> dict[str, Any] | None:
    if token_documento:
        linha = await pool.fetchrow(
            "select * from agentesia_contratos where provedor = 'zapsign' and id_documento_externo = $1", token_documento)
    else:
        linha = await pool.fetchrow(
            """select * from agentesia_contratos where id_lead = $1::uuid and situacao in ('gerado', 'assinado', 'substituido', 'cancelado')
               order by (situacao = 'assinado') desc, versao desc limit 1""", id_lead)
    return dict(linha) if linha else None


async def marcar_assinado(pool: asyncpg.Pool, *, id_contrato: str, lead_assinou_em: datetime | None,
                          concluido: bool, arquivo: str | None, signatarios: list[dict[str, Any]]) -> bool:
    """Passa a 'assinado' uma vez só. Verdadeiro se foi esta chamada que marcou (efeitos só uma vez)."""
    linha = await pool.fetchrow(
        """update agentesia_contratos set situacao = 'assinado', assinado_em = coalesce(assinado_em, now()),
                  lead_assinou_em = coalesce($2, now()), concluido_em = case when $3 then coalesce(concluido_em, now()) else concluido_em end,
                  arquivo_assinado = coalesce($4, arquivo_assinado), signatarios = $5::jsonb
           where id = $1::uuid and situacao <> 'assinado' returning id""",
        id_contrato, lead_assinou_em, concluido, arquivo, json.dumps(signatarios, ensure_ascii=False, default=str))
    return linha is not None


async def cancelar_lembretes(pool: asyncpg.Pool, id_lead: str) -> int:
    resultado = await pool.execute(
        """update agentesia_acoes set situacao = 'cancelada', erro = 'cancelado: contrato assinado, substituído ou encerrado'
           where id_lead = $1::uuid and tipo = 'lembrar_assinatura' and situacao = 'pendente'""", id_lead)
    return int(resultado.split()[-1])


async def receber_webhook(pool: asyncpg.Pool, id_escritorio: str, corpo: dict[str, Any]) -> str:
    """Aviso da ZapSign: registra (sem duplicar) e põe a verificação na fila. Quem decide é a releitura do documento.

    Assinatura, recusa/cancelamento, exclusão e vencimento relêem o documento. O external_id do aviso, quando vem,
    tem de ser o id do nosso contrato. Só guardamos os campos que usamos (o corpo traz CPF, telefone, geolocalização)."""
    evento = str(corpo.get("event_type") or "")
    doc = corpo.get("doc") if isinstance(corpo.get("doc"), dict) else {}
    token_doc = str(corpo.get("token") or doc.get("token") or "")
    externo = str(corpo.get("external_id") or doc.get("external_id") or "")
    assinante = str((corpo.get("signer_who_signed") or {}).get("token") or "") if isinstance(corpo.get("signer_who_signed"), dict) else ""
    resumo = {"event_type": evento, "token": token_doc, "external_id": externo or None, "status": corpo.get("status"),
              "signer_who_signed": assinante or None}
    linha = await pool.fetchrow(
        """insert into agentesia_eventos_recebidos (id_escritorio, origem, id_externo, tipo, payload, situacao, processado_em)
           values ($1::uuid, 'zapsign', $2, $3, $4::jsonb, 'processado', now())
           on conflict (origem, id_externo) do nothing returning id""",
        id_escritorio, f"{token_doc}:{evento}:{assinante}", evento, json.dumps(resumo, ensure_ascii=False))
    if not linha:
        return "repetido"
    if evento not in EVENTOS_QUE_RELEEM or not token_doc:
        await pool.execute("update agentesia_eventos_recebidos set situacao = 'ignorado', motivo = 'evento sem efeito' where id = $1", linha["id"])
        return "ignorado:evento"
    contrato = await pool.fetchrow(
        "select id, id_lead from agentesia_contratos where id_escritorio = $1::uuid and provedor = 'zapsign' and id_documento_externo = $2",
        id_escritorio, token_doc)
    if not contrato:
        # Documento de outro sistema (ex.: contrato antigo do Weaver na mesma conta ZapSign): não mexe.
        await pool.execute("update agentesia_eventos_recebidos set situacao = 'ignorado', motivo = 'documento desconhecido' where id = $1", linha["id"])
        return "ignorado:documento_desconhecido"
    if externo and externo != str(contrato["id"]):
        # Libera a chave do aviso: um aviso com external_id trocado não pode barrar o verdadeiro como "repetido".
        await pool.execute(
            """update agentesia_eventos_recebidos set situacao = 'ignorado', motivo = 'external_id não confere',
                      id_externo = id_externo || ':divergente:' || id::text where id = $1""", linha["id"])
        return "ignorado:external_id"
    await pool.execute(
        """insert into agentesia_acoes (id_escritorio, id_lead, tipo, chave_unica, dados)
           values ($1::uuid, $2, 'verificar_assinatura', $3, $4::jsonb) on conflict (chave_unica) do nothing""",
        id_escritorio, contrato["id_lead"], f"zapsign:{token_doc}:{assinante or evento}",
        json.dumps({"token_documento": token_doc, "origem": "zapsign", "evento": evento}))
    return "processado"
