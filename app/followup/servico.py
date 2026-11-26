"""Follow-up contra o banco: agendar, cancelar e o disparador (roda em segundo plano no servidor).

A cada AGENTESIA_FOLLOWUP_INTERVALO_S (padrão 60 s) o disparador:
1. reserva até 5 envios vencidos ("for update skip locked": dois servidores nunca pegam o mesmo);
2. confere TUDO de novo na hora (lead respondeu? equipe falou? lead pausado/encerrado/desqualificado? IA ou agente
   desligado? saldo acabou? limite de tentativas? fora do horário? intervalo mínimo?);
3. roda o agente de follow-up (agente.py), que DECIDE com as funções de follow-up: enviar, adiar (o lead pediu para
   ser chamado depois) ou não enviar;
4. o agente do lead (o da etapa atual, com a voz dele) escreve a mensagem (ou sai o texto fixo / modelo aprovado);
5. confere de novo logo antes de enviar, envia pela conta do escritório, grava na conversa (memória da IA), deixa a
   nota "Follow-up N de T enviado" no atendimento e agenda o passo seguinte (ou, no fim, a desistência).
Lead parado (todas as tentativas sem resposta) vira tarefa da equipe em varrer_parados.

Regras da OAB e da Meta (regras.py): quem nunca respondeu à IA recebe no máximo `max_toques_sem_resposta`; o penúltimo
toque oferece parar; pedido para parar na última mensagem do lead cancela tudo (lead_pediu_para_parar). Lead parado:
24 h depois do 3º toque sem resposta vira tarefa da equipe (varrer_parados).
Depois de cada turno o agendar também chama o gancho da nota do lead (automacoes.depois_do_turno).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg

from app.canal.helena import normalizar_telefone
from app.canal.helena_conta import ErroHelenaApi, HelenaConta
from app.followup import agente as agente_fu, regras
from app.modelo import ErroModelo, Modelo

log = logging.getLogger("agentesia.followup")
RESERVA_MIN = 15
MAX_TENTATIVAS = 3
TEXTO_RESERVA = "Oi{virgula}{nome}! Passando para saber se ficou alguma dúvida. Quando puder, é só me responder por aqui."

ESQUEMA = agente_fu.ESQUEMA_MENSAGENS
INTERVALO_PADRAO_S = 60.0
HISTORICO = 40                       # mensagens da conversa que os dois agentes leem
NOTA_ENVIO = "🔁 Follow-up {n} de {total} enviado às {hora} pelo agente {agente} (etapa {etapa})."


def agora() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------ agendar / cancelar
async def cancelar(pool: asyncpg.Pool, id_lead: str, motivo: str) -> int:
    resultado = await pool.execute(
        """update agentesia_followups set situacao = 'cancelado', motivo = $2
           where id_lead = $1::uuid and situacao in ('pendente', 'reservado')""", id_lead, motivo)
    return int(resultado.split()[-1])


async def ultima_do_lead(conexao: Any, id_lead: Any) -> str | None:
    return await conexao.fetchval(
        """select coalesce(nullif(btrim(texto), ''), texto_extraido) from agentesia_mensagens
           where id_lead = $1::uuid and autor = 'lead' order by enviada_em desc limit 1""", str(id_lead))


async def respondeu_a_ia(conexao: Any, id_lead: Any) -> bool:
    """O lead já mandou alguma mensagem depois da primeira mensagem da IA? (quem nunca respondeu tem menos toques)"""
    return bool(await conexao.fetchval(
        """select exists(select 1 from agentesia_mensagens m where m.id_lead = $1::uuid and m.autor = 'lead'
                         and m.enviada_em > (select min(i.enviada_em) from agentesia_mensagens i
                                             where i.id_lead = $1::uuid and i.autor = 'ia'))""", str(id_lead)))


async def _contexto_do_lead(conexao: Any, id_lead: str) -> dict[str, Any] | None:
    linha = await conexao.fetchrow(
        """select l.id, l.id_escritorio, l.id_agente, l.estado, l.ultima_mensagem_lead_em, l.id_sessao_helena,
                  ct.nome, ct.telefone_normalizado, ca.tipo as tipo_canal, ca.id_canal_helena,
                  ag.config as config_agente, ag.situacao as situacao_agente, ag.modo, ag.numeros_teste, ag.nome as nome_agente,
                  ag.produto, et.codigo as etapa, et.tipo as tipo_etapa, et.instrucao as instrucao_etapa,
                  es.nome as escritorio, es.ia_desligada, es.situacao as situacao_escritorio, es.config as config_escritorio
           from agentesia_leads l join agentesia_contatos ct on ct.id = l.id_contato
           join agentesia_canais ca on ca.id = l.id_canal
           join agentesia_escritorios es on es.id = l.id_escritorio
           left join agentesia_agentes ag on ag.id = l.id_agente
           left join agentesia_agente_etapas et on et.id = l.id_etapa
           where l.id = $1::uuid""", id_lead)
    if not linha:
        return None
    lead = dict(linha)
    for chave in ("config_agente", "config_escritorio"):
        if isinstance(lead.get(chave), str):
            lead[chave] = json.loads(lead[chave] or "{}")
        lead[chave] = lead.get(chave) or {}
    return lead


def _etapas_de_conversa(lead: dict[str, Any]) -> set[str]:
    """Etapas em que o follow-up vale por padrão. Desqualificado fica de fora (no catálogo é um papel de conversa, e o
    lead que acabou de ouvir que não tem direito recebia "ainda tem interesse?"); listado em config.etapas, vale."""
    from app.cerebro import produto as produtos
    produto = produtos.carregar(lead.get("produto"), lead.get("config_agente"))
    return {e.codigo for e in produto.etapas if e.tipo == "conversa" and e.codigo != "desqualificado"}


def _nome_da_etapa(lead: dict[str, Any]) -> str:
    from app.cerebro import produto as produtos
    codigo = lead.get("etapa") or ""
    try:
        produto = produtos.carregar(lead.get("produto"), lead.get("config_agente"))
        return next((e.nome for e in produto.etapas if e.codigo == codigo), codigo) or "conversa"
    except Exception:
        return codigo or "conversa"


async def agendar(pool: asyncpg.Pool, id_lead: str, base: datetime) -> datetime | None:
    """Depois de cada resposta da IA: troca o follow-up pendente pelo primeiro passo a partir de agora. Depois (fora da
    transação, sem derrubar o agendamento) roda o gancho de fim de turno: a nota do lead."""
    quando = await _agendar(pool, id_lead, base)
    from app import automacoes
    try:
        await automacoes.depois_do_turno(pool, str(id_lead))
    except Exception:                                  # a nota do lead nunca atrapalha o follow-up
        log.exception("falha ao calcular a nota do lead %s", id_lead)
    return quando


async def _agendar(pool: asyncpg.Pool, id_lead: str, base: datetime) -> datetime | None:
    async with pool.acquire() as conexao, conexao.transaction():
        lead = await _contexto_do_lead(conexao, id_lead)
        await conexao.execute(
            """update agentesia_followups set situacao = 'cancelado', motivo = 'nova_resposta_da_ia'
               where id_lead = $1::uuid and situacao in ('pendente', 'reservado')""", id_lead)
        if not lead:
            return None
        config = regras.Config.de(lead["config_agente"].get("followup"))
        if not config.ativo or lead["estado"] != "ativo" or not config.vale_para(lead["etapa"], _etapas_de_conversa(lead)):
            return None
        if regras.pediu_para_parar(await ultima_do_lead(conexao, id_lead)):
            # Pediu para parar: não agenda e deixa marcado (o painel mostra o motivo na lista do follow-up).
            await conexao.execute(
                """insert into agentesia_followups (id_escritorio, id_lead, id_agente, passo, base, agendado_para, situacao, motivo)
                   values ($1, $2, $3, 0, $4, $4, 'cancelado', 'lead_pediu_para_parar')""",
                lead["id_escritorio"], lead["id"], lead["id_agente"], base)
            return None
        quando = regras.horario_do_passo(base, 0, config, str(id_lead))
        if quando is None:
            return None
        await conexao.execute(
            """insert into agentesia_followups (id_escritorio, id_lead, id_agente, passo, base, agendado_para)
               values ($1, $2, $3, 0, $4, $5)""", lead["id_escritorio"], lead["id"], lead["id_agente"], base, quando)
        return quando


# ------------------------------------------------------------------ disparador
class Disparador:
    def __init__(self, pool: asyncpg.Pool, modelo: Modelo, url_helena: str, helena_por_token=HelenaConta,
                 modelo_padrao: str = "gpt-4.1-mini", http: Any = None) -> None:
        if http is not None and helena_por_token is HelenaConta:     # cliente HTTP compartilhado (fechado no desligamento)
            helena_por_token = lambda token, url: HelenaConta(token, url, http=http)    # noqa: E731
        self._pool = pool
        self._modelo = modelo
        self._url = url_helena
        self._helena_por_token = helena_por_token
        self._modelo_padrao = modelo_padrao
        self._parar = asyncio.Event()

    async def rodar(self, intervalo_s: float | None = None) -> None:
        """Laço de fundo (app/main.py, lifespan): de intervalo_s em intervalo_s confere a fila e os leads parados."""
        if intervalo_s is None:
            try:
                intervalo_s = max(5.0, float(os.environ.get("AGENTESIA_FOLLOWUP_INTERVALO_S", INTERVALO_PADRAO_S)))
            except ValueError:
                intervalo_s = INTERVALO_PADRAO_S
        while not self._parar.is_set():
            try:
                await self.rodar_uma_vez()
            except Exception:
                log.exception("falha no disparador de follow-up")
            try:
                await self.varrer_parados()
            except Exception:
                log.exception("falha na varredura de leads parados")
            try:                                       # follow-up ausente e avisos (app/vigia.py), de 10 em 10 min
                from app import vigia
                await vigia.rodar_se_for_hora(self._pool)
            except Exception:
                log.exception("falha na vigia (follow-up ausente / avisos)")
            try:
                await asyncio.wait_for(self._parar.wait(), intervalo_s)
            except asyncio.TimeoutError:
                pass

    def parar(self) -> None:
        self._parar.set()

    async def varrer_parados(self, limite: int = 20) -> int:
        return await varrer_parados(self._pool, limite)

    async def rodar_uma_vez(self, limite: int = 5) -> int:
        reservados = await self._pool.fetch(
            """update agentesia_followups f set situacao = 'reservado', reservado_ate = now() + make_interval(mins => $2),
                      tentativas = tentativas + 1
               where f.id in (select id from agentesia_followups
                              where (situacao = 'pendente' and agendado_para <= now())
                                 or (situacao = 'reservado' and reservado_ate < now())
                              order by agendado_para limit $1 for update skip locked)
               returning f.*""", limite, RESERVA_MIN)
        for linha in reservados:
            try:
                await self._processar(dict(linha))
            except Exception as erro:                  # nunca deixa preso em "reservado"
                log.exception("erro no follow-up %s", linha["id"])
                await self._adiar_ou_falhar(dict(linha), f"erro interno: {type(erro).__name__}")
        return len(reservados)

    # ---------------------------------------------------------------- um envio
    async def _processar(self, f: dict[str, Any]) -> None:
        lead = await _contexto_do_lead(self._pool, str(f["id_lead"]))
        if not lead:
            return await self._fechar(f, "cancelado", "lead_inexistente")
        config = regras.Config.de(lead["config_agente"].get("followup"))
        motivo = await self._por_que_nao(f, lead, config)
        if motivo == "lead_pediu_para_parar":
            return await self._fechar(f, "cancelado", motivo, evento=(
                "lead", "O lead pediu para não receber mais mensagens: os follow-ups dele foram cancelados."))
        if motivo:
            return await self._fechar(f, "cancelado", motivo)
        total = config.total_de_toques(await respondeu_a_ia(self._pool, f["id_lead"]))
        if total <= f["passo"] < len(config.passos):
            # Nunca respondeu à IA e já recebeu o máximo (regras da OAB e da Meta): para aqui.
            return await self._fechar(f, "cancelado", "limite_sem_resposta")
        if f["passo"] < len(config.passos) and f["tentativas"] > 1 and await self._ja_saiu(f):
            # O servidor caiu entre o envio e a marcação: a mensagem deste passo já está na conversa. Não reenvia.
            await self._pool.execute("update agentesia_followups set situacao = 'enviado', enviado_em = now(), motivo = 'enviado_antes_da_queda' "
                                     "where id = $1 and situacao = 'reservado'", f["id"])
            return await self._proximo(f, lead, config, total)
        momento = agora()
        dentro = regras.ajustar_ao_horario(momento, config, str(f["id_lead"]))
        if dentro > momento + timedelta(minutes=1):
            return await self._reagendar(f, dentro, "fora_do_horario")
        ultima_saida = await self._pool.fetchval(
            "select max(enviada_em) from agentesia_mensagens where id_lead = $1 and autor in ('ia', 'automacao', 'humano')", f["id_lead"])
        if ultima_saida and momento - ultima_saida < timedelta(minutes=config.intervalo_minimo_min):
            return await self._reagendar(f, ultima_saida + timedelta(minutes=config.intervalo_minimo_min), "intervalo_minimo")

        if f["passo"] >= len(config.passos):
            return await self._desistir(f, lead, config)

        helena = await self._helena(lead)
        if helena is None:
            return await self._fechar(f, "falhou", "escritorio_sem_conexao_whatsapp", evento=(
                "cadastro", "Follow-up não enviado: a conexão do WhatsApp do escritório não está configurada."))
        passo = config.passos[f["passo"]]
        janela_fechada = lead["tipo_canal"] == "oficial" and (
            not lead["ultima_mensagem_lead_em"] or momento - lead["ultima_mensagem_lead_em"] >= timedelta(hours=24))
        modelo_aprovado = janela_fechada or passo.modo == "modelo"
        id_modelo = config.modelo_oficial.get("id_modelo")
        if modelo_aprovado and not id_modelo:
            return await self._fechar(f, "falhou", "janela_fechada_sem_modelo", evento=(
                "cadastro", "Follow-up no número oficial depois de 24 h precisa de modelo aprovado (Agente › Follow-up)."))
        sem_ia = await self._consumo_estourado(lead)
        historico = await self._historico(f["id_lead"])
        decisao = agente_fu.Decisao() if sem_ia or not config.decidir else await self._decidir(f, lead, config, total, historico)
        if decisao.funcao == "adiar_followup" and not await self._ja_adiou(f):
            return await self._adiar(f, config, decisao)
        if decisao.funcao == "nao_enviar":
            return await self._fechar(f, "cancelado", "agente_decidiu_nao_enviar", evento=(
                "lead", "O agente de follow-up decidiu não mandar a retomada agora"
                        + (f": {decisao.motivo}" if decisao.motivo else ".") + " A cadência volta na próxima resposta da IA."),
                gravidade="info")
        textos = [] if modelo_aprovado else await self._textos(f, lead, config, passo, total, historico=historico,
                                                                orientacao=decisao.orientacao, sem_ia=sem_ia)
        if textos and config.leva_opcao_de_parar(f["passo"], total):
            textos = regras.com_opcao_de_parar(textos)         # penúltimo toque: "se preferir que eu não mande mais..."
        # A IA levou segundos escrevendo: o lead (ou a equipe) pode ter falado nesse meio tempo, ou o follow-up pode ter
        # sido cancelado. Confere tudo num comando só, logo antes de enviar.
        if not await self._ainda_vale(f):
            return
        enviadas: list[str] = []
        try:
            if modelo_aprovado:
                id_msg = await helena.enviar_modelo_no_atendimento(lead["id_sessao_helena"], id_modelo, {"nome": (lead["nome"] or "").split(" ")[0]})
                await self._gravar_mensagem(lead, f"[modelo aprovado: {config.modelo_oficial.get('nome') or id_modelo}]", id_msg)
                enviadas.append(f"modelo:{id_modelo}")
            else:
                for texto in textos:
                    id_msg = await helena.enviar_no_atendimento(lead["id_sessao_helena"], texto=texto, id_canal=lead["id_canal_helena"])
                    await self._gravar_mensagem(lead, texto, id_msg)
                    enviadas.append(texto)
        except ErroHelenaApi as erro:
            if not enviadas and erro.motivo != "talvez_enviado":
                return await self._adiar_ou_falhar(f, f"envio: {erro.motivo}")
            # Uma parte saiu (ou pode ter saído): a cadência conta como feita e nada é reenviado (senão o lead
            # receberia a 1ª mensagem de novo uma hora depois). A equipe fica sabendo pelo evento.
            await self._pool.execute(
                """insert into agentesia_eventos (id_escritorio, id_lead, tipo, gravidade, responsavel, descricao)
                   values ($1, $2, 'followup_envio_parcial', 'aviso', 'provedor', $3)""", f["id_escritorio"], f["id_lead"],
                f"Follow-up enviado pela metade ({len(enviadas)} de {len(textos) or 1} mensagem(ns)): {erro.motivo}. "
                "Não será reenviado; confira a conversa.")
        atualizado = await self._pool.fetchval(
            """update agentesia_followups set situacao = 'enviado', enviado_em = now(), mensagens = $2::jsonb, motivo = null
               where id = $1 and situacao = 'reservado' returning id""", f["id"], json.dumps(enviadas, ensure_ascii=False))
        if atualizado:                                 # cancelado no meio do envio: não agenda o passo seguinte
            await self._nota_do_envio(f, lead, total)
            await self._proximo(f, lead, config, total)

    # ---------------------------------------------------------------- agente de follow-up (decide)
    async def _decidir(self, f: dict[str, Any], lead: dict[str, Any], config: regras.Config, total: int,
                       historico: list[dict[str, Any]]) -> agente_fu.Decisao:
        """Roda o agente de follow-up. Sem resposta dele (erro, saída estranha), segue enviando como antes."""
        from app.cerebro import contexto
        sistema = agente_fu.sistema_do_decisor(lead, config, f["passo"], total, contexto.linha_de_hoje())
        try:
            resultado = await self._modelo.gerar(
                papel="followup_decisor", sistema=sistema, esquema=agente_fu.ESQUEMA_DECISAO,
                conteudo="Conversa até aqui (mais antiga primeiro):\n" + (agente_fu.conversa_em_texto(historico) or "(vazia)"),
                modelo=self._nome_modelo(lead, config), esforco="low")
        except ErroModelo as erro:
            await self._gravar_chamadas(lead, getattr(erro, "chamadas", []))     # a tentativa que falhou também foi paga
            return agente_fu.Decisao()
        await self._gravar_chamadas(lead, resultado.chamadas)
        return agente_fu.ler_decisao(resultado.dados)

    async def _ja_adiou(self, f: dict[str, Any]) -> bool:
        """Adia uma vez só por ciclo (desde a última resposta da IA): depois disso o agente não adia de novo."""
        return bool(await self._pool.fetchval(
            "select 1 from agentesia_eventos where id_lead = $1 and tipo = 'followup_adiado' and criado_em > $2 limit 1",
            f["id_lead"], f["base"]))

    async def _adiar(self, f: dict[str, Any], config: regras.Config, decisao: agente_fu.Decisao) -> None:
        quando = regras.ajustar_ao_horario(agora() + timedelta(hours=decisao.horas or 24), config, str(f["id_lead"]))
        await self._reagendar(f, quando, "lead_pediu_para_esperar")
        await self._pool.execute(
            """insert into agentesia_eventos (id_escritorio, id_lead, tipo, gravidade, responsavel, descricao, detalhe)
               values ($1, $2, 'followup_adiado', 'info', 'lead', $3, $4::jsonb)""", f["id_escritorio"], f["id_lead"],
            f"O lead pediu para ser chamado depois: o follow-up {f['passo'] + 1} foi adiado"
            + (f" ({decisao.motivo})" if decisao.motivo else "") + ".",
            json.dumps({"id_followup": str(f["id"]), "horas": decisao.horas, "para": quando.isoformat()}, ensure_ascii=False))

    async def _ja_saiu(self, f: dict[str, Any]) -> bool:
        """Reserva retomada depois de vencer: a IA já escreveu ao lead depois que esta linha nasceu?"""
        return bool(await self._pool.fetchval(
            "select 1 from agentesia_mensagens where id_lead = $1 and autor = 'ia' and enviada_em > $2 limit 1",
            f["id_lead"], f["criado_em"]))

    async def _nota_do_envio(self, f: dict[str, Any], lead: dict[str, Any], total: int) -> None:
        """Nota no atendimento para a equipe ver que o follow-up saiu (como o "realizado na cadência" do n8n)."""
        try:
            from app.notificacoes import fuso
            hora = agora().astimezone(fuso((lead.get("config_escritorio") or {}).get("fuso") or "America/Sao_Paulo"))
            texto = NOTA_ENVIO.format(n=f["passo"] + 1, total=total, etapa=_nome_da_etapa(lead),
                                      hora=f"{hora:%H:%M}", agente=lead.get("nome_agente") or "da IA")
            await self._pool.execute(
                """insert into agentesia_acoes (id_escritorio, id_lead, tipo, chave_unica, dados)
                   values ($1, $2, 'nota', $3, $4::jsonb) on conflict (chave_unica) do nothing""",
                f["id_escritorio"], f["id_lead"], f"{f['id_lead']}:followup:{f['id']}:enviado",
                json.dumps({"texto": texto}, ensure_ascii=False))
        except Exception:                                  # a nota nunca desfaz o envio
            log.exception("falha ao pôr a nota do follow-up %s", f["id"])

    async def _ainda_vale(self, f: dict[str, Any]) -> bool:
        """Ainda reservado e ninguém falou desde a base? Renova a reserva no mesmo comando. Se o lead ou a equipe falou,
        cancela (sem enviar)."""
        ok = await self._pool.fetchval(
            """update agentesia_followups set reservado_ate = now() + make_interval(mins => $4)
               where id = $1 and situacao = 'reservado'
                 and not exists (select 1 from agentesia_mensagens m where m.id_lead = $2 and m.autor in ('lead', 'humano')
                                 and m.enviada_em > $3)
                 and exists (select 1 from agentesia_leads l join agentesia_escritorios e on e.id = l.id_escritorio
                             left join agentesia_agentes a on a.id = l.id_agente
                             where l.id = $2 and l.estado = 'ativo' and not e.ia_desligada and e.situacao = 'ativo'
                               and coalesce(a.situacao, 'ativo') = 'ativo')
               returning id""", f["id"], f["id_lead"], f["base"], RESERVA_MIN)
        if ok:
            return True
        # IA desligada (lead, agente ou escritório) enquanto a IA escrevia também cancela: o follow-up não sai.
        await self._pool.execute(
            """update agentesia_followups set situacao = 'cancelado',
                      motivo = case when exists (select 1 from agentesia_leads l
                                                 join agentesia_escritorios e on e.id = l.id_escritorio
                                                 left join agentesia_agentes a on a.id = l.id_agente
                                                 where l.id = $2 and l.estado = 'ativo' and not e.ia_desligada
                                                   and e.situacao = 'ativo' and coalesce(a.situacao, 'ativo') = 'ativo')
                                    then 'respondeu_durante_o_envio' else 'ia_desligada_durante_o_envio' end
               where id = $1 and situacao = 'reservado'""", f["id"], f["id_lead"])
        return False

    async def _por_que_nao(self, f: dict[str, Any], lead: dict[str, Any], config: regras.Config) -> str | None:
        if not config.ativo:
            return "followup_desligado"
        if lead["estado"] != "ativo":
            return f"lead_{lead['estado']}"
        if lead["ia_desligada"] or lead["situacao_escritorio"] != "ativo":
            return "ia_desligada_no_escritorio"
        if lead["situacao_agente"] != "ativo":
            return "agente_pausado"
        if lead["modo"] == "teste":
            teste = {normalizar_telefone(n) for n in list(lead["numeros_teste"] or []) + list(lead["config_escritorio"].get("numeros_teste") or [])}
            if lead["telefone_normalizado"] not in teste:
                return "modo_teste"
        if lead["etapa"] == "desqualificado":
            return "lead_desqualificado"
        if regras.pediu_para_parar(await ultima_do_lead(self._pool, f["id_lead"])):
            return "lead_pediu_para_parar"
        if lead["etapa"] == "contrato_assinado" or await self._pool.fetchval(
                "select 1 from agentesia_contratos where id_lead = $1 and situacao = 'assinado' limit 1", f["id_lead"]):
            return "contrato_assinado"
        if not config.vale_para(lead["etapa"], _etapas_de_conversa(lead)):
            return "etapa_sem_followup"
        if lead["ultima_mensagem_lead_em"] and lead["ultima_mensagem_lead_em"] > f["base"]:
            return "lead_respondeu"
        equipe = await self._pool.fetchval(
            "select 1 from agentesia_mensagens where id_lead = $1 and autor = 'humano' and enviada_em > $2 limit 1", f["id_lead"], f["base"])
        if equipe:
            return "equipe_falou"
        if not lead["id_sessao_helena"]:
            return "lead_sem_atendimento"
        from app import cobranca
        if await cobranca.bloqueado(self._pool, lead["id_escritorio"]):
            # Saldo da IA acabou: cancela (não adia). Quando o crédito voltar não sai uma rajada de follow-ups
            # atrasados; a cadência recomeça na próxima resposta da IA.
            return cobranca.MOTIVO
        return None

    async def _historico(self, id_lead: Any) -> list[dict[str, Any]]:
        linhas = await self._pool.fetch(
            """select autor, coalesce(texto_extraido, texto) as texto from agentesia_mensagens
               where id_lead = $1 and coalesce(texto_extraido, texto) is not null order by enviada_em desc limit $2""",
            id_lead, HISTORICO)
        return [dict(m) for m in reversed(linhas)]

    def _nome_modelo(self, lead: dict[str, Any], config: regras.Config) -> str:
        return config.modelo or (lead["config_agente"].get("modelos") or {}).get("followup") or self._modelo_padrao

    async def _textos(self, f: dict[str, Any], lead: dict[str, Any], config: regras.Config, passo: regras.Passo,
                      total: int | None = None, *, historico: list[dict[str, Any]] | None = None, orientacao: str = "",
                      sem_ia: bool | None = None) -> list[str]:
        """A mensagem: texto fixo do passo ou o agente do lead (o da etapa, com a voz dele) escrevendo a retomada."""
        if passo.modo == "texto" and passo.texto:
            return [regras.preencher(passo.texto, nome=lead["nome"])]
        primeiro = (lead["nome"] or "").split(" ")[0]
        reserva = [TEXTO_RESERVA.format(virgula=", " if primeiro else "", nome=primeiro)]
        if sem_ia if sem_ia is not None else await self._consumo_estourado(lead):
            return reserva                    # limite de consumo do mês acabou: texto de reserva, sem gastar IA
        historico = historico if historico is not None else await self._historico(f["id_lead"])
        total = total or len(config.passos)
        sistema = agente_fu.sistema_do_agente_do_lead(lead, config, f["passo"], total, orientacao)
        try:
            resultado = await self._modelo.gerar(papel="followup", sistema=sistema, esquema=ESQUEMA,
                                                 conteudo="Conversa até aqui:\n" + agente_fu.conversa_em_texto(historico),
                                                 modelo=self._nome_modelo(lead, config), esforco="low")
            await self._gravar_chamadas(lead, resultado.chamadas)
            textos = agente_fu.limpar_mensagens(resultado.dados.get("mensagens"))
        except ErroModelo as erro:
            await self._gravar_chamadas(lead, getattr(erro, "chamadas", []))     # a tentativa que falhou também foi paga
            textos = []
        return textos or reserva

    async def _consumo_estourado(self, lead: dict[str, Any]) -> bool:
        from app import consumo

        config = lead.get("config_escritorio") or {}
        try:
            if not consumo.config_do_limite(config)["mensal_usd"]:
                return False
            gasto = float(await self._pool.fetchval(
                "select coalesce(sum(custo_usd), 0) from agentesia_chamadas_ia where id_escritorio = $1 and criado_em >= $2",
                lead["id_escritorio"], consumo.inicio_do_mes()) or 0)
            return bool(consumo.avaliar(gasto, config).bloqueado)
        except Exception:                                # sem conseguir conferir, segue como antes
            log.exception("falha ao conferir o consumo no follow-up")
            return False

    async def _proximo(self, f: dict[str, Any], lead: dict[str, Any], config: regras.Config, total: int | None = None) -> None:
        """Agenda o toque seguinte ou, depois do último (do total deste lead), a desistência (passo = nº de passos)."""
        total = len(config.passos) if total is None else total
        seguinte = f["passo"] + 1
        if seguinte < total:
            quando = regras.horario_do_passo(f["base"], seguinte, config, str(f["id_lead"]))
            if quando is not None and f["passo"] < len(config.passos):
                # Atrasou (servidor fora do ar, adiamento): o toque seguinte guarda pelo menos metade do espaço da
                # cadência, em vez de sair logo depois (dois lembretes seguidos).
                metade = (config.passos[seguinte].apos_horas - config.passos[f["passo"]].apos_horas) / 2
                quando = max(quando, regras.ajustar_ao_horario(agora() + timedelta(hours=metade), config, f"{f['id_lead']}:{seguinte}"))
        elif seguinte == total and config.desistir_ativo:
            seguinte = len(config.passos)
            quando = regras.ajustar_ao_horario(agora() + timedelta(hours=config.desistir_apos_horas), config, str(f["id_lead"]))
        else:
            return
        quando = max(quando or agora(), agora() + timedelta(minutes=config.intervalo_minimo_min))
        await self._pool.execute(
            """insert into agentesia_followups (id_escritorio, id_lead, id_agente, passo, base, agendado_para)
               values ($1, $2, $3, $4, $5, $6) on conflict do nothing""",
            f["id_escritorio"], f["id_lead"], f["id_agente"], seguinte, f["base"], quando)

    async def _desistir(self, f: dict[str, Any], lead: dict[str, Any], config: regras.Config) -> None:
        """Último passo sem resposta: encerra a IA para o lead, deixa nota e dispara as automações de desistência."""
        from app import automacoes

        await self._pool.execute(
            "update agentesia_leads set estado = 'encerrado', motivo_estado = 'sem_resposta_followup' where id = $1 and estado = 'ativo'",
            f["id_lead"])
        acoes = [{"tipo": "nota", "chave_unica": f"{f['id_lead']}:followup:{f['id']}:nota", "dados": {"texto": config.desistir_nota}}]
        crm = await self._pool.fetchval(
            "select config from agentesia_integracoes where id_escritorio = $1 and tipo = 'crm'", f["id_escritorio"])
        avisos = {r["tipo_evento"] for r in await self._pool.fetch(
            "select tipo_evento from agentesia_notificacoes where id_escritorio = $1 and habilitada", f["id_escritorio"])}
        acoes += automacoes.montar_acoes(lead["config_agente"], crm if isinstance(crm, dict) else json.loads(crm or "{}"),
                                         ["followup_desistiu"], id_lead=str(f["id_lead"]), id_turno=f"followup-{f['id']}", avisos=avisos)
        for a in acoes:
            await self._pool.execute(
                """insert into agentesia_acoes (id_escritorio, id_lead, tipo, chave_unica, dados)
                   values ($1, $2, $3, $4, $5::jsonb) on conflict (chave_unica) do nothing""",
                f["id_escritorio"], f["id_lead"], a["tipo"], a["chave_unica"], json.dumps(a["dados"], ensure_ascii=False))
        await self._fechar(f, "enviado", "desistencia")

    # ---------------------------------------------------------------- apoio
    async def _helena(self, lead: dict[str, Any]) -> HelenaConta | None:
        from app.banco.postgres import token_helena
        token = await token_helena(self._pool, lead["id_escritorio"])   # mesma fonte do envio do turno e do Executor
        return self._helena_por_token(token, self._url) if token else None

    async def _gravar_mensagem(self, lead: dict[str, Any], texto: str, id_externo: str | None) -> None:
        await self._pool.execute(
            """insert into agentesia_mensagens (id_escritorio, id_lead, id_externo, autor, tipo, texto, enviada_em, situacao_envio)
               values ($1, $2, $3, 'ia', 'texto', $4, now(), 'enviada')
               on conflict (id_escritorio, id_externo) where id_externo is not null do update
                 set autor = 'ia', situacao_envio = 'enviada', texto = coalesce(excluded.texto, agentesia_mensagens.texto)
                 where agentesia_mensagens.autor = 'automacao'""",
            lead["id_escritorio"], lead["id"], id_externo, texto)

    async def _gravar_chamadas(self, lead: dict[str, Any], chamadas: list[Any]) -> None:
        from app import cobranca
        await cobranca.gravar_chamadas(self._pool, id_escritorio=str(lead["id_escritorio"]), chamadas=chamadas,
                                       id_lead=str(lead["id"]), id_agente=str(lead["id_agente"]) if lead.get("id_agente") else None,
                                       codigo_etapa=lead.get("etapa"))

    async def _fechar(self, f: dict[str, Any], situacao: str, motivo: str, evento: tuple[str, str] | None = None,
                      gravidade: str = "aviso") -> None:
        await self._pool.execute("update agentesia_followups set situacao = $2, motivo = $3 where id = $1", f["id"], situacao, motivo)
        if evento:
            await self._pool.execute(
                """insert into agentesia_eventos (id_escritorio, id_lead, tipo, gravidade, responsavel, descricao)
                   values ($1, $2, $3, $4, $5, $6)""", f["id_escritorio"], f["id_lead"], f"followup_{motivo}", gravidade,
                evento[0], evento[1])

    async def _reagendar(self, f: dict[str, Any], quando: datetime, motivo: str) -> None:
        await self._pool.execute(
            """update agentesia_followups set situacao = 'pendente', agendado_para = $2, motivo = $3, reservado_ate = null,
                      tentativas = greatest(tentativas - 1, 0) where id = $1""", f["id"], quando, motivo)

    async def _adiar_ou_falhar(self, f: dict[str, Any], erro: str) -> None:
        """Falha de envio: tenta de novo em 1 hora; na 3ª, desiste deste passo e segue a cadência."""
        if await self._pool.fetchval("select situacao from agentesia_followups where id = $1", f["id"]) != "reservado":
            return                                     # já foi enviado/cancelado (erro depois do envio): não mexe
        if f["tentativas"] >= MAX_TENTATIVAS:
            await self._fechar(f, "falhou", erro[:200], evento=("provedor", f"Follow-up não enviado depois de {MAX_TENTATIVAS} tentativas ({erro[:120]})."))
            lead = await _contexto_do_lead(self._pool, str(f["id_lead"]))
            if lead:
                config = regras.Config.de(lead["config_agente"].get("followup"))
                await self._proximo(f, lead, config, config.total_de_toques(await respondeu_a_ia(self._pool, f["id_lead"])))
            return
        await self._pool.execute(
            """update agentesia_followups set situacao = 'pendente', agendado_para = now() + interval '1 hour', motivo = $2,
                      reservado_ate = null where id = $1 and situacao = 'reservado'""", f["id"], erro[:200])


# ------------------------------------------------------------------ lead parado (B12)
_PARADOS = """
    select f.id, f.id_escritorio, f.id_lead, f.passo, f.base, f.enviado_em, a.config as config_agente
    from agentesia_followups f
    join agentesia_leads l on l.id = f.id_lead
    join agentesia_agentes a on a.id = f.id_agente
    cross join lateral (select coalesce((a.config->'followup'->'limites'->>'lead_parado_apos')::int, $2) as apos) lp
    left join agentesia_agente_etapas et on et.id = l.id_etapa
    where f.situacao = 'enviado' and f.enviado_em <= now() - make_interval(hours => $1)
      and f.enviado_em > now() - interval '30 days'
      and lp.apos > 0 and f.passo < jsonb_array_length(coalesce(a.config->'followup'->'passos', '[]'::jsonb))
      -- o toque lead_parado_apos (3º) ou o último que este lead recebeu, se o ciclo acabou antes (quem nunca respondeu
      -- recebe só 2; o agente de follow-up decidiu não enviar; falhou sem próximo)
      and (f.passo + 1 = lp.apos
           or (f.passo + 1 < lp.apos and not exists (
                 select 1 from agentesia_followups g where g.id_lead = f.id_lead and g.base = f.base and g.passo > f.passo
                   and g.situacao in ('pendente', 'reservado', 'enviado'))))
      and a.situacao = 'ativo' and coalesce(a.config->'followup'->>'ativo', 'false') = 'true'
      and l.estado = 'ativo' and coalesce(et.codigo, '') not in ('desqualificado', 'contrato_assinado')
      and not exists (select 1 from agentesia_mensagens m where m.id_lead = f.id_lead and m.autor in ('lead', 'humano')
                      and m.enviada_em > f.base)
      and not exists (select 1 from agentesia_contratos k where k.id_lead = f.id_lead and k.situacao = 'assinado')
      and not exists (select 1 from agentesia_acoes x where x.chave_unica = f.id_lead::text || ':lead_parado:' || f.id::text)
    order by f.enviado_em limit $3"""


async def varrer_parados(pool: asyncpg.Pool, limite: int = 20) -> int:
    """Lead parado vira tarefa da equipe: 24 h depois do 3º toque (lead_parado_apos) sem resposta do lead nem da equipe
    (ou do último toque, se este lead recebeu menos: quem nunca respondeu à IA fica nos 2),
    põe na fila a nota "Lead parado: retomar contato", a etiqueta/coluna/aviso do gatilho "lead_parado" e grava o
    evento lead_parado. Uma vez por ciclo de follow-up (a chave da nota leva o id do toque). Devolve quantos."""
    from app import automacoes

    linhas = await pool.fetch(_PARADOS, regras.LEAD_PARADO_ESPERA_H, regras.LEAD_PARADO_APOS, limite)
    feitos = 0
    for r in linhas:
        config_agente = r["config_agente"] if isinstance(r["config_agente"], dict) else json.loads(r["config_agente"] or "{}")
        crm = await pool.fetchval("select config from agentesia_integracoes where id_escritorio = $1 and tipo = 'crm'", r["id_escritorio"])
        avisos = {x["tipo_evento"] for x in await pool.fetch(
            "select tipo_evento from agentesia_notificacoes where id_escritorio = $1 and habilitada", r["id_escritorio"])}
        acoes = automacoes.acoes_do_lead_parado(config_agente, crm if isinstance(crm, dict) else json.loads(crm or "{}"),
                                                id_lead=str(r["id_lead"]), id_followup=str(r["id"]), avisos=avisos)
        async with pool.acquire() as conexao, conexao.transaction():
            primeira = await conexao.fetchval(
                """insert into agentesia_acoes (id_escritorio, id_lead, tipo, chave_unica, dados)
                   values ($1, $2, $3, $4, $5::jsonb) on conflict (chave_unica) do nothing returning true""",
                r["id_escritorio"], r["id_lead"], acoes[0]["tipo"], acoes[0]["chave_unica"], json.dumps(acoes[0]["dados"], ensure_ascii=False))
            if not primeira:                           # outro servidor já fez este ciclo
                continue
            for a in acoes[1:]:
                await conexao.execute(
                    """insert into agentesia_acoes (id_escritorio, id_lead, tipo, chave_unica, dados)
                       values ($1, $2, $3, $4, $5::jsonb) on conflict (chave_unica) do nothing""",
                    r["id_escritorio"], r["id_lead"], a["tipo"], a["chave_unica"], json.dumps(a["dados"], ensure_ascii=False))
            await conexao.execute(
                """insert into agentesia_eventos (id_escritorio, id_lead, tipo, gravidade, responsavel, descricao, detalhe)
                   values ($1, $2, 'lead_parado', 'info', 'lead', $3, $4::jsonb)""", r["id_escritorio"], r["id_lead"],
                f"Lead parado: {r['passo'] + 1} follow-ups sem resposta. Tarefa para a equipe retomar o contato.",
                json.dumps({"id_followup": str(r["id"]), "passo": r["passo"] + 1}, ensure_ascii=False))
            feitos += 1
    return feitos
