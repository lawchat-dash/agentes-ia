"""Vigia: varreduras leves e conservadoras para o que escapou do fluxo normal (roda no laço do follow-up).

A cada AGENTESIA_VIGIA_INTERVALO_MIN (padrão 10) minutos, com uma trava no banco (dois servidores não varrem juntos):

1. Follow-up ausente: lead ativo, IA ligada (escritório, agente em produção), a ÚLTIMA mensagem da conversa é da IA,
   dita há mais de AGENTESIA_FOLLOWUP_AUSENTE_H horas (padrão 2) e há menos de AGENTESIA_FOLLOWUP_AUSENTE_JANELA_H
   (padrão 24: só leads recentes), sem follow-up pendente e sem nenhum follow-up criado depois dessa resposta (a cadência
   que já correu, foi cancelada ou terminou não recomeça). Agenda pelo mesmo caminho do turno (followup._agendar: as
   regras do agente decidem — etapa sem follow-up, follow-up desligado e "pediu para parar" continuam valendo).
   No máximo AGENTESIA_FOLLOWUP_AUSENTE_LIMITE (padrão 10) por rodada. Lead com fala da equipe depois da IA, pausado
   ou encerrado nunca entra. AGENTESIA_FOLLOWUP_AUSENTE_H=0 desliga.
2. Follow-up desligado em produção: agente ativo em produção com o follow-up desligado vira evento de cadastro
   (vai para a central de avisos da equipe LawChat), no máximo 1 por agente a cada AGENTESIA_AVISO_FOLLOWUP_DESLIGADO_DIAS
   (padrão 7; 0 desliga).
3. Escritório sem webhook: escritório ativo, com agente ativo em produção, que recebeu mensagem nos últimos 14 dias mas
   está há AGENTESIA_SEM_WEBHOOK_H horas (padrão 4; 0 desliga) sem nenhuma, contadas dentro do horário comercial de hoje
   (AGENTESIA_SEM_WEBHOOK_HORARIO, padrão "9-18", segunda a sexta, no fuso do escritório): evento 'escritorio_sem_webhook'
   para a equipe LawChat, no máximo 1 por escritório a cada 24 h.
4. Webhook ligado: em cada escritório ativo com a LawChat conectada e o webhook já ligado uma vez, confere na
   plataforma se a assinatura que traz as mensagens continua lá, ativa, com o endereço e os eventos certos. Sumiu ou
   mudou: recria/corrige sozinho. Não deu (token recusado, plataforma fora): marca o webhook como desconectado — a tela
   Integrações e o Início mostram "Reconectar webhook" — e avisa a equipe LawChat. Sem IA, só a API da plataforma.
   AGENTESIA_VIGIA_WEBHOOK=0 desliga.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

log = logging.getLogger("agentesia.vigia")

_ultima_rodada = [time.monotonic()]          # a 1ª rodada vem um intervalo depois da subida (sem pico no deploy)
# (id_lead, última resposta da IA) já tentados neste processo: lead cuja etapa não tem follow-up não é relido a cada volta.
_tentados: set[tuple[str, str]] = set()


def _numero(nome: str, padrao: float) -> float:
    try:
        return max(0.0, float(os.environ.get(nome, padrao)))
    except ValueError:
        return padrao


def agora() -> datetime:
    return datetime.now(timezone.utc)


async def rodar_se_for_hora(pool: Any) -> dict[str, int] | None:
    """Chamado a cada volta do Disparador: roda as varreduras de AGENTESIA_VIGIA_INTERVALO_MIN em
    AGENTESIA_VIGIA_INTERVALO_MIN minutos. Devolve o que fez (None = não era hora ou outro servidor está varrendo)."""
    intervalo = _numero("AGENTESIA_VIGIA_INTERVALO_MIN", 10) * 60
    if intervalo <= 0 or time.monotonic() - _ultima_rodada[0] < intervalo:
        return None
    _ultima_rodada[0] = time.monotonic()
    return await rodar(pool)


async def rodar(pool: Any) -> dict[str, int] | None:
    feito = {"followups_recuperados": 0, "avisos_followup_desligado": 0, "avisos_sem_webhook": 0, "webhooks_conferidos": 0}
    async with pool.acquire() as trava, trava.transaction():
        if not await trava.fetchval("select pg_try_advisory_xact_lock(hashtext('agentesia_vigia'))"):
            return None
        for nome, varrer in (("followups_recuperados", followup_ausente),
                             ("avisos_followup_desligado", followup_desligado),
                             ("avisos_sem_webhook", escritorio_sem_webhook),
                             ("webhooks_conferidos", webhooks_ligados)):
            try:
                feito[nome] = await varrer(pool)
            except Exception:                            # uma varredura nunca derruba as outras nem o follow-up
                log.exception("falha na varredura %s", nome)
    return feito


# ---------------------------------------------------------------------------- 1. follow-up ausente
async def followup_ausente(pool: Any, *, horas: float | None = None, janela_h: float | None = None,
                           limite: int | None = None) -> int:
    horas = _numero("AGENTESIA_FOLLOWUP_AUSENTE_H", 2) if horas is None else horas
    if horas <= 0:
        return 0
    janela_h = max(horas, _numero("AGENTESIA_FOLLOWUP_AUSENTE_JANELA_H", 24) if janela_h is None else janela_h)
    limite = int(_numero("AGENTESIA_FOLLOWUP_AUSENTE_LIMITE", 10) if limite is None else limite)
    if limite <= 0:
        return 0
    linhas = await pool.fetch(
        """select l.id, l.id_escritorio, l.ultima_resposta_ia_em
           from agentesia_leads l
           join agentesia_agentes a on a.id = l.id_agente
           join agentesia_escritorios e on e.id = l.id_escritorio
           where l.estado = 'ativo' and a.situacao = 'ativo' and a.modo = 'producao'
             and not e.ia_desligada and e.situacao = 'ativo'
             and l.ultima_resposta_ia_em < now() - make_interval(secs => $1)
             and l.ultima_resposta_ia_em > now() - make_interval(secs => $2)
             and l.responder_apos is null and (l.processando_ate is null or l.processando_ate < now())
             and not exists (select 1 from agentesia_followups f where f.id_lead = l.id
                             and (f.situacao in ('pendente', 'reservado')
                                  or f.criado_em >= l.ultima_resposta_ia_em - interval '1 minute'))
             and not exists (select 1 from agentesia_mensagens m where m.id_lead = l.id and m.autor <> 'ia'
                             and m.enviada_em > l.ultima_resposta_ia_em)
             and not (l.id::text = any($4::text[]))
           order by l.ultima_resposta_ia_em desc
           limit $3""", horas * 3600, janela_h * 3600, limite, [i for i, _ in _tentados])
    from app.followup import servico
    recuperados = 0
    for linha in linhas:
        id_lead, base = str(linha["id"]), linha["ultima_resposta_ia_em"]
        _tentados.add((id_lead, base.isoformat()))
        if len(_tentados) > 5000:
            _tentados.clear()
        quando = await servico._agendar(pool, id_lead, base)
        if quando is None:
            continue                                     # as regras do agente não agendam (etapa sem follow-up etc.)
        recuperados += 1
        await pool.execute(
            """insert into agentesia_eventos (id_escritorio, id_lead, tipo, gravidade, responsavel, descricao, detalhe)
               values ($1, $2, 'followup_recuperado', 'info', 'lawchat', $3, $4::jsonb)""",
            linha["id_escritorio"], linha["id"],
            "O follow-up deste lead não estava agendado depois da última resposta da IA: a varredura agendou.",
            json.dumps({"base": base.isoformat(), "agendado_para": quando.isoformat()}))
    return recuperados


# ---------------------------------------------------------------------------- 2. follow-up desligado em produção
async def followup_desligado(pool: Any, *, dias: float | None = None) -> int:
    dias = _numero("AGENTESIA_AVISO_FOLLOWUP_DESLIGADO_DIAS", 7) if dias is None else dias
    if dias <= 0:
        return 0
    from app.followup import regras
    linhas = await pool.fetch(
        """select a.id, a.id_escritorio, a.nome, a.config
           from agentesia_agentes a join agentesia_escritorios e on e.id = a.id_escritorio
           where a.situacao = 'ativo' and a.modo = 'producao' and e.situacao = 'ativo' and not e.ia_desligada
             and not exists (select 1 from agentesia_eventos v where v.id_escritorio = a.id_escritorio
                             and v.tipo = 'followup_desligado' and v.detalhe ->> 'id_agente' = a.id::text
                             and v.criado_em > now() - make_interval(secs => $1))""", dias * 86400)
    avisos = 0
    for linha in linhas:
        config = linha["config"]
        config = json.loads(config) if isinstance(config, str) else dict(config or {})
        if regras.Config.de(config.get("followup")).ativo:
            continue
        avisos += 1
        await pool.execute(
            """insert into agentesia_eventos (id_escritorio, tipo, gravidade, responsavel, descricao, detalhe)
               values ($1, 'followup_desligado', 'aviso', 'cadastro', $2, $3::jsonb)""",
            linha["id_escritorio"],
            f"O agente {linha['nome']} está em produção com o follow-up desligado: os leads que param de responder "
            "não recebem retomada. Confira em Agente › Follow-up.",
            json.dumps({"id_agente": str(linha["id"])}))
    return avisos


# ---------------------------------------------------------------------------- 3. escritório sem webhook
def _horario_comercial() -> tuple[int, int]:
    bruto = os.environ.get("AGENTESIA_SEM_WEBHOOK_HORARIO", "9-18")
    try:
        inicio, fim = (int(x) for x in bruto.split("-", 1))
        if 0 <= inicio < fim <= 24:
            return inicio, fim
    except ValueError:
        pass
    return 9, 18


def silencio_conta(fuso_escritorio: str | None, ultima: datetime, horas: float, momento: datetime | None = None) -> bool:
    """True se agora é horário comercial (seg-sex) e já passaram `horas` de silêncio DENTRO do expediente de hoje."""
    from app.notificacoes import fuso
    momento = momento or agora()
    local = momento.astimezone(fuso(fuso_escritorio or "America/Sao_Paulo"))
    inicio, fim = _horario_comercial()
    if local.weekday() >= 5 or not (inicio <= local.hour < fim):
        return False
    abertura = local.replace(hour=inicio, minute=0, second=0, microsecond=0)
    desde = max(abertura, ultima.astimezone(local.tzinfo))
    return (local - desde) >= timedelta(hours=horas)


async def escritorio_sem_webhook(pool: Any, *, horas: float | None = None, momento: datetime | None = None) -> int:
    horas = _numero("AGENTESIA_SEM_WEBHOOK_H", 4) if horas is None else horas
    if horas <= 0:
        return 0
    linhas = await pool.fetch(
        """select e.id, e.nome, e.config,
                  (select max(r.recebido_em) from agentesia_eventos_recebidos r where r.id_escritorio = e.id
                     and r.recebido_em > now() - interval '14 days') as ultima
           from agentesia_escritorios e
           where e.situacao = 'ativo' and not e.ia_desligada
             and exists (select 1 from agentesia_agentes a join agentesia_canais c on c.id = a.id_canal and c.ativo
                         where a.id_escritorio = e.id and a.situacao = 'ativo' and a.modo = 'producao')
             and not exists (select 1 from agentesia_eventos v where v.id_escritorio = e.id
                             and v.tipo = 'escritorio_sem_webhook' and v.criado_em > now() - interval '24 hours')""")
    avisos = 0
    for linha in linhas:
        if linha["ultima"] is None:
            continue                                     # sem nada em 14 dias: não é queda, é escritório parado
        config = linha["config"]
        config = json.loads(config) if isinstance(config, str) else dict(config or {})
        if not silencio_conta(config.get("fuso"), linha["ultima"], horas, momento):
            continue
        avisos += 1
        parado_h = max(0, int(((momento or agora()) - linha["ultima"]).total_seconds() // 3600))
        await pool.execute(
            """insert into agentesia_eventos (id_escritorio, tipo, gravidade, responsavel, descricao, detalhe)
               values ($1, 'escritorio_sem_webhook', 'erro', 'lawchat', $2, $3::jsonb)""",
            linha["id"],
            f"Nenhuma mensagem chega deste escritório há {parado_h} h, em horário comercial. Confira o webhook da "
            "conta (Minha Conta › Integrações › Testar conexão) e se o número está conectado.",
            json.dumps({"ultima_recebida": linha["ultima"].isoformat(), "horas": horas}))
    return avisos


# ---------------------------------------------------------------------------- 4. webhook ligado
async def webhooks_ligados(pool: Any, *, helena_por_token: Any = None, url_helena: str | None = None,
                           so_escritorio: str | None = None) -> int:
    """Confere (e refaz) a assinatura do webhook de cada escritório que já ligou o recebimento. Devolve quantos conferiu.
    Resultado no config da integração helena: webhook_situacao ok | corrigido | desconectado, webhook_conferido_em
    e webhook_erro. webhook_conectado acompanha (false enquanto estiver desconectado)."""
    if os.environ.get("AGENTESIA_VIGIA_WEBHOOK", "1").strip() == "0":
        return 0
    from app.banco.postgres import token_helena
    from app.canal.helena_conta import ErroHelenaApi, HelenaConta
    from app.canal.webhook import url_do_escritorio
    criar = helena_por_token or HelenaConta
    base = url_helena or os.environ.get("AGENTESIA_HELENA_URL", "https://api.helena.run")
    linhas = await pool.fetch(
        """select e.id::text as id, i.config
           from agentesia_escritorios e join agentesia_integracoes i on i.id_escritorio = e.id and i.tipo = 'helena'
           where e.situacao = 'ativo' and i.situacao = 'ok' and ($1::uuid is null or e.id = $1::uuid)
             and (coalesce(i.config ->> 'webhook_conectado', 'false') = 'true' or i.config ->> 'webhook_situacao' = 'desconectado')""",
        so_escritorio)
    conferidos = 0
    for linha in linhas:
        id_escritorio = linha["id"]
        config = linha["config"]
        config = json.loads(config) if isinstance(config, str) else dict(config or {})
        url = url_do_escritorio(id_escritorio)
        token = await token_helena(pool, id_escritorio)
        if not url or not token:
            continue
        helena = criar(token, base)
        mudar: dict[str, Any] = {"webhook_conferido_em": agora().isoformat()}
        try:
            assinatura = await helena.garantir_assinatura(url, config.get("id_assinatura"))
            mudar.update({"webhook_situacao": "ok" if assinatura.get("acao") == "ja_estava_certa" else "corrigido",
                          "webhook_conectado": True, "webhook_erro": None})
            if assinatura.get("id"):
                mudar["id_assinatura"] = assinatura["id"]
            if assinatura.get("acao") in ("criada", "corrigida"):
                await pool.execute(
                    """insert into agentesia_eventos (id_escritorio, tipo, gravidade, responsavel, descricao, detalhe)
                       values ($1::uuid, 'webhook_refeito', 'aviso', 'lawchat', $2, $3::jsonb)""",
                    id_escritorio, "O webhook da LawChat tinha caído e foi refeito sozinho pelo vigia.",
                    json.dumps({"acao": assinatura.get("acao")}))
        except (ErroHelenaApi, Exception) as erro:          # qualquer falha da plataforma: marca e segue para o próximo
            motivo = getattr(erro, "motivo", None) or type(erro).__name__
            mudar.update({"webhook_situacao": "desconectado", "webhook_conectado": False,
                          "webhook_erro": "a LawChat recusou o token" if motivo == "token_recusado"
                          else f"a LawChat não respondeu ({motivo})"})
            if config.get("webhook_situacao") != "desconectado":     # avisa a equipe só na virada, não a cada volta
                await pool.execute(
                    """insert into agentesia_eventos (id_escritorio, tipo, gravidade, responsavel, descricao, detalhe)
                       values ($1::uuid, 'webhook_desconectado', 'erro', 'lawchat', $2, $3::jsonb)""",
                    id_escritorio, "O webhook da LawChat caiu e não deu para refazer sozinho: as mensagens não chegam à IA. "
                    "Abra Integrações e use Reconectar webhook.", json.dumps({"motivo": motivo}))
        finally:
            fechar = getattr(getattr(helena, "_http", None), "aclose", None)
            if fechar:
                try:
                    await fechar()
                except Exception:
                    pass
        await pool.execute(
            """update agentesia_integracoes set config = coalesce(config, '{}'::jsonb) || $2::jsonb
               where id_escritorio = $1::uuid and tipo = 'helena'""", id_escritorio, json.dumps(mudar))
        conferidos += 1
    return conferidos
