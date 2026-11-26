"""Follow-up contra o banco: agendar, cancelar e o disparador (roda em segundo plano no servidor).

O disparador reserva até 5 envios vencidos ("for update skip locked": dois servidores nunca pegam o mesmo),
confere TUDO de novo na hora (lead respondeu? equipe falou? IA desligada? etapa mudou? fora do horário?),
escreve a mensagem (IA, texto fixo ou modelo aprovado) e envia pela Helena. Depois agenda o passo seguinte
ou, no fim, a desistência.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg

from app.canal.helena import normalizar_telefone
from app.canal.helena_conta import ErroHelenaApi, HelenaConta
from app.followup import regras
from app.modelo import ErroModelo, Modelo

log = logging.getLogger("agentesia.followup")
RESERVA_MIN = 15
MAX_TENTATIVAS = 3
TEXTO_RESERVA = "Oi{virgula}{nome}! Passando para saber se ficou alguma dúvida. Quando puder, é só me responder por aqui."

ESQUEMA = {"type": "object", "additionalProperties": False,
           "properties": {"mensagens": {"type": "array", "items": {"type": "string"}}}, "required": ["mensagens"]}


def agora() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------ agendar / cancelar
async def cancelar(pool: asyncpg.Pool, id_lead: str, motivo: str) -> int:
    resultado = await pool.execute(
        """update agentesia_followups set situacao = 'cancelado', motivo = $2
           where id_lead = $1::uuid and situacao in ('pendente', 'reservado')""", id_lead, motivo)
    return int(resultado.split()[-1])


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


async def agendar(pool: asyncpg.Pool, id_lead: str, base: datetime) -> datetime | None:
    """Depois de cada resposta da IA: troca o follow-up pendente pelo primeiro passo a partir de agora."""
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

    async def rodar(self, intervalo_s: float = 60.0) -> None:
        while not self._parar.is_set():
            try:
                await self.rodar_uma_vez()
            except Exception:
                log.exception("falha no disparador de follow-up")
            try:
                await asyncio.wait_for(self._parar.wait(), intervalo_s)
            except asyncio.TimeoutError:
                pass

    def parar(self) -> None:
        self._parar.set()

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
        if motivo:
            return await self._fechar(f, "cancelado", motivo)
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
            return await self._fechar(f, "falhou", "escritorio_sem_token_helena", evento=("cadastro", "Follow-up sem token da Helena."))
        passo = config.passos[f["passo"]]
        janela_fechada = lead["tipo_canal"] == "oficial" and (
            not lead["ultima_mensagem_lead_em"] or momento - lead["ultima_mensagem_lead_em"] >= timedelta(hours=24))
        modelo_aprovado = janela_fechada or passo.modo == "modelo"
        id_modelo = config.modelo_oficial.get("id_modelo")
        if modelo_aprovado and not id_modelo:
            return await self._fechar(f, "falhou", "janela_fechada_sem_modelo", evento=(
                "cadastro", "Follow-up no número oficial depois de 24 h precisa de modelo aprovado (Agente › Follow-up)."))
        textos = [] if modelo_aprovado else await self._textos(f, lead, config, passo)
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
                return await self._adiar_ou_falhar(f, f"helena: {erro.motivo}")
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
            await self._proximo(f, lead, config)

    async def _ainda_vale(self, f: dict[str, Any]) -> bool:
        """Ainda reservado e ninguém falou desde a base? Renova a reserva no mesmo comando. Se o lead ou a equipe falou,
        cancela (sem enviar)."""
        ok = await self._pool.fetchval(
            """update agentesia_followups set reservado_ate = now() + make_interval(mins => $4)
               where id = $1 and situacao = 'reservado'
                 and not exists (select 1 from agentesia_mensagens m where m.id_lead = $2 and m.autor in ('lead', 'humano')
                                 and m.enviada_em > $3)
               returning id""", f["id"], f["id_lead"], f["base"], RESERVA_MIN)
        if ok:
            return True
        await self._pool.execute(
            """update agentesia_followups set situacao = 'cancelado', motivo = 'respondeu_durante_o_envio'
               where id = $1 and situacao = 'reservado'""", f["id"])
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
            return "lead_sem_atendimento_na_helena"
        from app import cobranca
        if await cobranca.bloqueado(self._pool, lead["id_escritorio"]):
            # Saldo da IA acabou: cancela (não adia). Quando o crédito voltar não sai uma rajada de follow-ups
            # atrasados; a cadência recomeça na próxima resposta da IA.
            return cobranca.MOTIVO
        return None

    async def _textos(self, f: dict[str, Any], lead: dict[str, Any], config: regras.Config, passo: regras.Passo) -> list[str]:
        if passo.modo == "texto" and passo.texto:
            return [regras.preencher(passo.texto, nome=lead["nome"])]
        historico = await self._pool.fetch(
            """select autor, coalesce(texto_extraido, texto) as texto from agentesia_mensagens
               where id_lead = $1 and coalesce(texto_extraido, texto) is not null order by enviada_em desc limit 24""", f["id_lead"])
        conversa = "\n".join(f"{'lead' if m['autor'] == 'lead' else 'você' if m['autor'] == 'ia' else 'equipe'}: {m['texto']}"
                             for m in reversed(historico))
        instrucao = passo.instrucao or regras.INSTRUCAO_PASSO_PADRAO.get(f["passo"], "Retomada breve e gentil.")
        if f["passo"] == len(config.passos) - 1:
            instrucao += " Esta é a última tentativa: diga que fica à disposição quando a pessoa puder."
        sistema = "\n\n".join(filter(None, [
            f"Você é {lead['nome_agente'] or 'a atendente'}, do escritório {lead['escritorio']}.",
            config.prompt,
            config.por_etapa.get(lead["etapa"] or ""),
            f"Tentativa {f['passo'] + 1} de {len(config.passos)}. {instrucao}",
            "Devolva de 1 a 3 mensagens curtas em 'mensagens'.",
        ]))
        nome_modelo = config.modelo or (lead["config_agente"].get("modelos") or {}).get("followup") or self._modelo_padrao
        if await self._consumo_estourado(lead):
            # Limite de consumo do mês acabou: o follow-up sai com o texto de reserva, sem gastar IA.
            primeiro = (lead["nome"] or "").split(" ")[0]
            return [TEXTO_RESERVA.format(virgula=", " if primeiro else "", nome=primeiro)]
        try:
            resultado = await self._modelo.gerar(papel="followup", sistema=sistema, conteudo="Conversa até aqui:\n" + conversa,
                                                 esquema=ESQUEMA, modelo=nome_modelo, esforco="low")
            await self._gravar_chamadas(lead, resultado.chamadas)
            textos = [t.strip() for t in resultado.dados.get("mensagens") or [] if str(t).strip()][:3]
        except ErroModelo:
            textos = []
        if not textos or any(re.search(r"https?://|R\$\s*\d", t) for t in textos):
            primeiro = (lead["nome"] or "").split(" ")[0]
            return [TEXTO_RESERVA.format(virgula=", " if primeiro else "", nome=primeiro)]
        return textos

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

    async def _proximo(self, f: dict[str, Any], lead: dict[str, Any], config: regras.Config) -> None:
        seguinte = f["passo"] + 1
        if seguinte < len(config.passos):
            quando = regras.horario_do_passo(f["base"], seguinte, config, str(f["id_lead"]))
        elif seguinte == len(config.passos) and config.desistir_ativo:
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

    async def _fechar(self, f: dict[str, Any], situacao: str, motivo: str, evento: tuple[str, str] | None = None) -> None:
        await self._pool.execute("update agentesia_followups set situacao = $2, motivo = $3 where id = $1", f["id"], situacao, motivo)
        if evento:
            await self._pool.execute(
                """insert into agentesia_eventos (id_escritorio, id_lead, tipo, gravidade, responsavel, descricao)
                   values ($1, $2, $3, 'aviso', $4, $5)""", f["id_escritorio"], f["id_lead"], f"followup_{motivo}", evento[0], evento[1])

    async def _reagendar(self, f: dict[str, Any], quando: datetime, motivo: str) -> None:
        await self._pool.execute(
            """update agentesia_followups set situacao = 'pendente', agendado_para = $2, motivo = $3, reservado_ate = null,
                      tentativas = greatest(tentativas - 1, 0) where id = $1""", f["id"], quando, motivo)

    async def _adiar_ou_falhar(self, f: dict[str, Any], erro: str) -> None:
        """Falha de envio: tenta de novo em 1 hora; na 3ª, desiste deste passo e segue a cadência."""
        if f["tentativas"] >= MAX_TENTATIVAS:
            await self._fechar(f, "falhou", erro[:200], evento=("provedor", f"Follow-up não enviado depois de {MAX_TENTATIVAS} tentativas ({erro[:120]})."))
            lead = await _contexto_do_lead(self._pool, str(f["id_lead"]))
            if lead:
                await self._proximo(f, lead, regras.Config.de(lead["config_agente"].get("followup")))
            return
        await self._pool.execute(
            """update agentesia_followups set situacao = 'pendente', agendado_para = now() + interval '1 hour', motivo = $2,
                      reservado_ate = null where id = $1""", f["id"], erro[:200])
