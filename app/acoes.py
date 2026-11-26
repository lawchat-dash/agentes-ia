"""Executor da fila de ações (agentesia_acoes): CRM, etiquetas, nota e transferência na Helena.

Roda em segundo plano no servidor. Cada ação é reservada com "for update skip locked"
(dois executores nunca pegam a mesma), executada, e marcada como feita ou reagendada
(1, 5, 30 e 120 minutos). Na última falha vira evento para a equipe ver em Erros.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import asyncpg

from app import cobranca
from app.canal.helena_conta import ErroHelenaApi, HelenaConta
from app.canal.zapsign import URL_PRODUCAO, URL_SANDBOX, ErroZapSign, ZapSign

log = logging.getLogger("agentesia.acoes")
ESPERAS_MIN = [1, 5, 30, 120]


def _gatilhos_do_agente(produto: str | None, config: Any) -> dict[str, str]:
    """Rótulos dos gatilhos do produto do agente (os mesmos da tela de avisos), para o cabeçalho do aviso."""
    from app import automacoes
    from app.cerebro import produto as produtos

    try:
        if not isinstance(config, dict):
            config = json.loads(config or "{}") if isinstance(config, str) else {}
        return automacoes.gatilhos_do_produto(produtos.carregar(produto, config))
    except Exception:                                    # produto sem definição válida: fica com os nomes padrão
        return {}


def _nome_da_etapa(produto: str | None, config: Any, codigo: str | None) -> str | None:
    """Nome da etapa do lead no aviso ("SDR", "Primeiro atendimento"), não o código cru ("sdr")."""
    from app.cerebro import produto as produtos

    if not codigo:
        return None
    try:
        if not isinstance(config, dict):
            config = json.loads(config or "{}") if isinstance(config, str) else {}
        return next((e.nome for e in produtos.carregar(produto, config).etapas if e.codigo == codigo and e.nome), codigo)
    except Exception:                                    # produto sem definição válida: fica o código
        return codigo


class Executor:
    def __init__(self, pool: asyncpg.Pool, url_helena: str, helena_por_token=HelenaConta, zapsign_por_token=ZapSign,
                 modelo: Any = None, http: Any = None) -> None:
        self._modelo = modelo                         # IA para o resumo do contrato (None = sem resumo)
        self._pool = pool
        self._url = url_helena
        # Um cliente HTTP só para todas as ações (o servidor fecha no desligamento): antes cada ação abria um e nunca
        # fechava (sockets abertos até o GC).
        if http is not None and helena_por_token is HelenaConta:
            helena_por_token = lambda token, url: HelenaConta(token, url, http=http)    # noqa: E731
        if http is not None and zapsign_por_token is ZapSign:
            zapsign_por_token = lambda token, url: ZapSign(token, url, http=http)       # noqa: E731
        self._helena_por_token = helena_por_token
        self._zapsign_por_token = zapsign_por_token
        self._parar = asyncio.Event()

    # ------------------------------------------------------------------ laço
    async def rodar(self, intervalo_s: float = 5.0) -> None:
        import time

        ultima_consulta = float("-inf")
        while not self._parar.is_set():
            if time.monotonic() - ultima_consulta >= CONSULTA_ZAPSIGN_S:
                ultima_consulta = time.monotonic()
                try:
                    await self.agendar_consultas()
                except Exception:
                    log.exception("falha ao agendar a consulta periódica da ZapSign")
            try:
                feitas = await self.rodar_uma_vez()
            except Exception:
                log.exception("falha no executor de ações")
                feitas = 0
            if not feitas:
                try:
                    await asyncio.wait_for(self._parar.wait(), intervalo_s)
                except asyncio.TimeoutError:
                    pass

    def parar(self) -> None:
        self._parar.set()

    async def agendar_consultas(self) -> int:
        """Rede de segurança do aviso da ZapSign: relê os contratos 'gerado' sem resposta (30 em 30 min nas primeiras
        48 h, depois 1 vez por dia até 30 dias). A releitura é a mesma do aviso: à prova de repetição."""
        from app.contrato import servico
        return await servico.agendar_consultas(self._pool)

    async def rodar_uma_vez(self, limite: int = 10) -> int:
        reservadas = await self._pool.fetch(
            """update agentesia_acoes a set situacao = 'executando', travada_ate = now() + interval '5 minutes',
                      tentativas = tentativas + 1
               where a.id in (
                 select id from agentesia_acoes
                 where (situacao = 'pendente' and proxima_em <= now())
                    or (situacao = 'executando' and travada_ate < now())
                 order by criado_em limit $1 for update skip locked)
               returning a.*""", limite)
        for acao in reservadas:
            await self._executar(dict(acao))
        return len(reservadas)

    # ------------------------------------------------------------------ uma ação
    async def _executar(self, acao: dict[str, Any]) -> None:
        dados = acao["dados"] if isinstance(acao["dados"], dict) else json.loads(acao["dados"])
        dados = {**dados, "_id_acao": acao["id"]}            # para ações que criam outras (aviso -> envios)
        try:
            if acao["id_lead"] and not await self._pool.fetchval(
                    "select true from agentesia_leads where id = $1::uuid and id_escritorio = $2::uuid",
                    acao["id_lead"], acao["id_escritorio"]):
                # Isolamento: ação com lead de OUTRO escritório (ou lead apagado) nunca envia nada.
                raise ErroDeCadastro("o lead da ação não é deste escritório (ou não existe mais)")
            if acao["tipo"] == "alertar_lawchat":           # sai pela conta da LawChat, não pela do escritório
                contexto = self._contexto_lawchat(str(acao["id_escritorio"]))
            elif acao["tipo"] in SEM_HELENA:                 # só banco e IA: não precisa do token da Helena
                contexto = {"id_escritorio": str(acao["id_escritorio"]),
                            "lead": {"id": str(acao["id_lead"])} if acao["id_lead"] else None}
            else:
                contexto = await self._contexto(str(acao["id_escritorio"]), str(acao["id_lead"]) if acao["id_lead"] else None)
            if acao["tipo"] in GASTAM_IA_SEM_ESPERA and await cobranca.bloqueado(self._pool, str(acao["id_escritorio"])):
                resultado = {"motivo": cobranca.MOTIVO}       # saldo da IA acabou: não gasta (e não volta em rajada)
            else:
                resultado = await getattr(self, "_" + acao["tipo"])(contexto, dados)
        except ErroDeCadastro as erro:
            await self._falhou(acao, str(erro), definitiva=True, responsavel="cadastro")
            return
        except ErroZapSign as erro:
            await self._falhou(acao, f"ZapSign: {erro}", definitiva=erro.do_escritorio,
                               responsavel="cliente" if erro.do_escritorio else "provedor")
            return
        except ErroHelenaApi as erro:
            if erro.motivo == "talvez_enviado" and acao["tipo"] in ENVIAM_MENSAGEM:
                # A Helena demorou a responder, mas pode ter aceitado: repetir mandaria a mesma mensagem duas vezes.
                await self._falhou(acao, str(erro), definitiva=True, responsavel="provedor")
                await self._conferir_chegada(acao)
                return
            definitiva = erro.motivo in ("token_recusado", "nao_encontrado")
            await self._falhou(acao, str(erro), definitiva=definitiva,
                               responsavel="cliente" if erro.motivo == "token_recusado" else "provedor")
            return
        except AttributeError:
            await self._falhou(acao, f"tipo de ação desconhecido: {acao['tipo']}", definitiva=True, responsavel="lawchat")
            return
        except Exception as erro:                     # nunca deixa a ação presa em "executando"
            log.exception("erro inesperado na ação %s", acao["id"])
            await self._falhou(acao, f"erro interno: {type(erro).__name__}", definitiva=False, responsavel="lawchat")
            return
        await self._pool.execute(
            "update agentesia_acoes set situacao = 'feita', resultado = $2::jsonb, erro = null where id = $1",
            acao["id"], json.dumps(resultado or {}, ensure_ascii=False))

    async def _falhou(self, acao: dict[str, Any], erro: str, definitiva: bool, responsavel: str) -> None:
        tentativa = acao["tentativas"]
        if definitiva or tentativa > len(ESPERAS_MIN):
            await self._pool.execute(
                "update agentesia_acoes set situacao = 'falhou', erro = $2 where id = $1", acao["id"], erro[:500])
            if await self._card_nao_criado(acao, erro):
                return
            await self._pool.execute(
                """insert into agentesia_eventos (id_escritorio, id_lead, id_turno, tipo, gravidade, responsavel, descricao, detalhe)
                   values ($1, $2, $3, $4, 'erro', $5, $6, $7::jsonb)""",
                acao["id_escritorio"], acao["id_lead"], acao["id_turno"], "acao_falhou_" + acao["tipo"],
                responsavel,
                f"Não foi possível {DESCRICOES.get(acao['tipo'], acao['tipo'])} na Helena: {erro[:300]}",
                json.dumps({"id_acao": str(acao["id"]), "tentativas": tentativa}))
            return
        espera = ESPERAS_MIN[tentativa - 1]
        await self._pool.execute(
            """update agentesia_acoes set situacao = 'pendente', erro = $2,
                      proxima_em = now() + make_interval(mins => $3) where id = $1""", acao["id"], erro[:500], espera)

    async def _conferir_chegada(self, acao: dict[str, Any]) -> None:
        """Mensagem ao lead que talvez tenha saído: nota no chat para a equipe conferir (sem nova tentativa)."""
        if not acao.get("id_lead"):
            return
        try:
            await self._pool.execute(
                """insert into agentesia_acoes (id_escritorio, id_lead, tipo, chave_unica, dados)
                   select $1, $2, 'nota', $3, $4::jsonb from agentesia_leads
                   where id = $2 and id_sessao_helena is not null
                   on conflict (chave_unica) do nothing""",
                acao["id_escritorio"], acao["id_lead"], f"{acao['id']}:talvez_enviado",
                json.dumps({"texto": "📭 A IA tentou mandar uma mensagem ao lead e o WhatsApp não confirmou o envio "
                                     f"({DESCRICOES.get(acao['tipo'], acao['tipo'])}). Confira se a mensagem chegou; "
                                     "se não chegou, envie manualmente."}, ensure_ascii=False))
        except Exception:
            log.exception("falha ao agendar a nota de envio sem confirmação da ação %s", acao["id"])

    async def _card_nao_criado(self, acao: dict[str, Any], erro: str) -> bool:
        """Falha definitiva do card quando o lead ainda não tem card: evento 'card_nao_criado' e nota no chat.

        Devolve False quando não é o caso (o card já existe e só não se moveu: segue o evento comum)."""
        if acao["tipo"] != "mover_card" or not acao["id_lead"]:
            return False
        if await self._pool.fetchval("select exists(select 1 from agentesia_crm_cards where id_lead = $1)", acao["id_lead"]):
            return False
        from app import automacoes
        from app.banco.postgres import RepositorioPostgres

        motivo = f"a plataforma de atendimento não criou o card do lead ({erro[:200]})."      # nota do chat: sem "Helena"
        tentativa = acao["tentativas"]
        await self._pool.execute(
            """insert into agentesia_eventos (id_escritorio, id_lead, id_turno, tipo, gravidade, responsavel, descricao, detalhe)
               values ($1, $2, $3, 'card_nao_criado', 'erro', 'cadastro', $4, $5::jsonb)""",
            acao["id_escritorio"], acao["id_lead"], acao["id_turno"], f"Card do lead não foi criado no CRM: {motivo}",
            json.dumps({"id_acao": str(acao["id"]), "tentativas": tentativa}))
        if await self._pool.fetchval("select id_sessao_helena from agentesia_leads where id = $1", acao["id_lead"]):
            await RepositorioPostgres(self._pool).nota_de_problema(
                id_escritorio=str(acao["id_escritorio"]), id_lead=str(acao["id_lead"]), tipo="card_nao_criado",
                texto=automacoes.NOTA_CARD_NAO_CRIADO.format(detalhe=motivo))
        return True

    async def _contexto(self, id_escritorio: str, id_lead: str | None) -> dict[str, Any]:
        from app.banco.postgres import token_helena
        token = await token_helena(self._pool, id_escritorio)     # mesma fonte do envio do turno e do follow-up
        if not token:
            raise ErroDeCadastro("escritório sem token da Helena (cadastro)")
        contexto: dict[str, Any] = {"helena": self._helena_por_token(token, self._url), "id_escritorio": id_escritorio}
        if id_lead:
            lead = await self._pool.fetchrow(
                """select l.id, l.id_sessao_helena, l.id_contato, c.id_contato_helena, c.nome, c.telefone_normalizado,
                          l.origem, l.criado_em
                   from agentesia_leads l join agentesia_contatos c on c.id = l.id_contato
                   where l.id = $1::uuid and l.id_escritorio = $2::uuid""", id_lead, id_escritorio)
            if not lead:
                raise ErroDeCadastro("o lead da ação não é deste escritório (ou não existe mais)")
            contexto["lead"] = dict(lead)
        return contexto

    async def _zapsign(self, id_escritorio: str) -> tuple[ZapSign | None, dict[str, Any]]:
        linha = await self._pool.fetchrow(
            """select i.config, s.decrypted_secret as token from agentesia_integracoes i
               left join vault.decrypted_secrets s on s.id = i.id_segredo_vault
               where i.id_escritorio = $1::uuid and i.tipo = 'zapsign'""", id_escritorio)
        if not linha:
            return None, {}
        config = linha["config"] if isinstance(linha["config"], dict) else json.loads(linha["config"] or "{}")
        if not linha["token"]:
            return None, config
        url = URL_SANDBOX if config.get("ambiente") == "sandbox" else URL_PRODUCAO
        return self._zapsign_por_token(linha["token"], url), config

    async def _lead_completo(self, id_lead: str, id_escritorio: str | None = None) -> dict[str, Any]:
        """Lead com contato, canal e agente. Com id_escritorio, só se o lead for dele (senão a ação falha sem enviar).
        Sem ele, vale o _executar, que já recusa ação cujo lead não é do escritório da ação."""
        linha = await self._pool.fetchrow(
            """select l.*, ct.nome, ct.telefone_normalizado, ca.id_canal_helena, ag.config as config_agente, ag.produto, et.codigo as etapa
               from agentesia_leads l join agentesia_contatos ct on ct.id = l.id_contato
               join agentesia_canais ca on ca.id = l.id_canal
               left join agentesia_agentes ag on ag.id = l.id_agente
               left join agentesia_agente_etapas et on et.id = l.id_etapa
               where l.id = $1::uuid and ($2::uuid is null or l.id_escritorio = $2::uuid)""", id_lead, id_escritorio)
        if not linha:
            raise ErroDeCadastro("lead não encontrado neste escritório")
        lead = dict(linha)
        if isinstance(lead.get("config_agente"), str):
            lead["config_agente"] = json.loads(lead["config_agente"] or "{}")
        return lead

    async def _nome_do_caso(self, produto: str | None, config_agente: Any) -> str:
        """O benefício do agente para a nota e o aviso (agente do catálogo: o nome do produto da biblioteca)."""
        from app.contrato import resumo as cresumo

        if not isinstance(config_agente, dict):
            config_agente = json.loads(config_agente or "{}") if isinstance(config_agente, str) else {}
        return cresumo.nome_do_caso(produto, config_agente, await cresumo.nome_da_biblioteca(self._pool, config_agente))

    async def _enfileirar(self, contexto: dict[str, Any], tipo: str, chave: str, dados: dict[str, Any],
                          minutos: float = 0) -> None:
        await self._pool.execute(
            """insert into agentesia_acoes (id_escritorio, id_lead, tipo, chave_unica, dados, proxima_em)
               values ($1::uuid, $2::uuid, $3, $4, $5::jsonb, now() + make_interval(secs => $6))
               on conflict (chave_unica) do nothing""",
            contexto["id_escritorio"], (contexto.get("lead") or {}).get("id"), tipo, chave,
            json.dumps(dados, ensure_ascii=False), float(minutos * 60))

    async def _disparar(self, contexto: dict[str, Any], lead: dict[str, Any], gatilhos: list[str], origem: str,
                        so_avisos: bool | None = None) -> None:
        """Gatilhos que nascem fora do turno (contrato gerado/assinado): mesmas automações do agente.
        so_avisos: None = tudo; False = tudo menos o aviso à equipe; True = só o aviso (o do contrato assinado espera o
        resumo, o card e as etiquetas não)."""
        from app import automacoes

        crm = await self._pool.fetchval(
            "select config from agentesia_integracoes where id_escritorio = $1::uuid and tipo = 'crm'", contexto["id_escritorio"])
        crm = crm if isinstance(crm, dict) else json.loads(crm or "{}")
        avisos = {r["tipo_evento"] for r in await self._pool.fetch(
            "select tipo_evento from agentesia_notificacoes where id_escritorio = $1::uuid and habilitada", contexto["id_escritorio"])}
        acoes = automacoes.montar_acoes(lead.get("config_agente") or {}, crm, gatilhos, id_lead=str(lead["id"]),
                                        id_turno=origem, avisos=avisos)
        for a in acoes:
            if so_avisos is not None and (a["tipo"] == "preparar_aviso") != so_avisos:
                continue
            await self._enfileirar(contexto, a["tipo"], a["chave_unica"], a["dados"])

    async def _mensagem_ao_lead(self, contexto: dict[str, Any], lead: dict[str, Any], chave: str, texto: str) -> None:
        if lead.get("id_sessao_helena"):
            await self._enfileirar(contexto, "enviar_mensagem", chave, {"texto": texto})

    async def _nota_unica(self, contexto: dict[str, Any], lead: dict[str, Any], chave: str, texto: str) -> None:
        if lead.get("id_sessao_helena"):
            await self._enfileirar(contexto, "nota", chave, {"texto": texto})

    async def _id_contato(self, contexto: dict[str, Any]) -> str:
        id_contato = await self._id_contato_sem_nome(contexto)
        await self._completar_nome(contexto, id_contato)
        return id_contato

    async def _completar_nome(self, contexto: dict[str, Any], id_contato: str) -> None:
        """O webhook da plataforma não traz o nome do lead: busca no cadastro do contato e guarda (sem sobrescrever).
        Sem isso o card, a nota e as telas mostravam 'Sem nome'. Falha aqui nunca derruba a ação."""
        lead = contexto.get("lead") or {}
        if lead.get("nome") or not lead.get("id_contato") or not hasattr(contexto.get("helena"), "nome_do_contato"):
            return
        try:
            nome = await contexto["helena"].nome_do_contato(id_contato)
        except Exception:
            log.info("nome do contato indisponível", exc_info=True)
            return
        if nome:
            await self._pool.execute("update agentesia_contatos set nome = coalesce(nullif(nome, ''), $2) where id = $1",
                                     lead["id_contato"], nome)
            lead["nome"] = nome

    async def _id_contato_sem_nome(self, contexto: dict[str, Any]) -> str:
        lead = contexto.get("lead") or {}
        if lead.get("id_contato_helena"):
            return lead["id_contato_helena"]
        if not lead.get("id_sessao_helena"):
            raise ErroDeCadastro("lead sem atendimento da Helena")
        id_contato = await contexto["helena"].contato_da_sessao(lead["id_sessao_helena"])
        if not id_contato:
            raise ErroHelenaApi("nao_encontrado", "atendimento sem contato")
        await self._pool.execute(
            """update agentesia_contatos set id_contato_helena = $2 where id = $1
               and not exists (select 1 from agentesia_contatos x where x.id_escritorio = agentesia_contatos.id_escritorio
                               and x.id_contato_helena = $2)""", lead["id_contato"], id_contato)
        lead["id_contato_helena"] = id_contato
        return id_contato

    # ------------------------------------------------------------------ tipos
    async def _mover_card(self, contexto: dict[str, Any], dados: dict[str, Any]) -> dict[str, Any]:
        """Um lead, um card: usa o card guardado, procura um aberto do contato, ou cria."""
        lead = contexto["lead"]
        helena: HelenaConta = contexto["helena"]
        gatilho = str(dados.get("gatilho") or "")
        if atual := await self._etapa_mudou(lead["id"], gatilho):
            return {"acao": "ignorada", "motivo": f"o lead já está em {atual}; mover agora levaria o card para trás"}
        card = await self._pool.fetchrow("select * from agentesia_crm_cards where id_lead = $1", lead["id"])
        id_card = card["id_card_helena"] if card and card["id_painel_helena"] == dados["id_painel"] else None
        # Lead novo só cria o card. Se ele já existe (o turno da IA andou com ele enquanto esta ação esperava uma
        # nova tentativa), mover agora levaria o card de volta para a coluna SDR.
        if gatilho == "lead_novo" and id_card:
            return {"acao": "ignorada", "motivo": "o card do lead já existe; o lead novo só cria"}
        acao = "moveu"
        if not id_card:
            id_contato = await self._id_contato(contexto)
            id_card = await helena.card_do_contato(dados["id_painel"], id_contato)
            if id_card and gatilho == "lead_novo":
                return {"acao": "ignorada", "motivo": "o contato já tem card aberto neste painel; o lead novo só cria"}
            if not id_card:
                from app import automacoes

                origem = lead.get("origem")
                origem = json.loads(origem or "{}") if isinstance(origem, str) else (origem or {})
                id_card = await helena.criar_card(
                    id_etapa=dados["id_etapa_helena"], id_contato=id_contato, id_sessao=lead.get("id_sessao_helena"),
                    titulo=automacoes.titulo_do_card(lead.get("nome"), lead.get("telefone_normalizado")),
                    descricao=automacoes.descricao_do_card(origem, lead.get("criado_em")))
                acao = "criou"
        if acao == "moveu":
            await helena.mover_card(id_card, dados["id_etapa_helena"])
        await self._pool.execute(
            """insert into agentesia_crm_cards (id_escritorio, id_lead, id_card_helena, id_painel_helena, id_etapa_helena,
                                                situacao, sincronizado_em)
               values ($1::uuid, $2, $3, $4, $5, 'ok', now())
               on conflict (id_lead) do update set id_card_helena = excluded.id_card_helena,
                 id_painel_helena = excluded.id_painel_helena, id_etapa_helena = excluded.id_etapa_helena,
                 situacao = 'ok', erro = null, sincronizado_em = now()""",
            contexto["id_escritorio"], lead["id"], id_card, dados["id_painel"], dados["id_etapa_helena"])
        return {"card": id_card, "acao": acao}

    async def _etapa_mudou(self, id_lead: Any, gatilho: str) -> str | None:
        """Ação nascida de 'etapa:X' e o lead já está em outra etapa (a ação esperou uma nova tentativa): devolve a etapa
        atual, para a ação ser ignorada em vez de levar card ou etiquetas para trás."""
        if not gatilho.startswith("etapa:"):
            return None
        atual = await self._pool.fetchval(
            """select e.codigo from agentesia_leads l join agentesia_agente_etapas e on e.id = l.id_etapa
               where l.id = $1""", id_lead)
        return atual if atual and atual != gatilho.split(":", 1)[1] else None

    async def _etiquetar(self, contexto: dict[str, Any], dados: dict[str, Any]) -> dict[str, Any]:
        if contexto.get("lead") and (atual := await self._etapa_mudou(contexto["lead"]["id"], str(dados.get("gatilho") or ""))):
            return {"acao": "ignorada", "motivo": f"o lead já está em {atual}; etiquetar agora voltaria as etiquetas"}
        id_contato = await self._id_contato(contexto)
        if dados.get("gatilho") == "lead_novo" and (motivo := await self._ja_tinha_card(contexto, dados, id_contato)):
            return {"acao": "ignorada", "motivo": motivo}
        await contexto["helena"].etiquetar(id_contato, dados.get("remover", []), remover=True)
        await contexto["helena"].etiquetar(id_contato, dados.get("adicionar", []))
        return {"contato": id_contato}

    async def _ja_tinha_card(self, contexto: dict[str, Any], dados: dict[str, Any], id_contato: str) -> str | None:
        """Etiqueta do lead novo: o contato já tinha card (no banco ou aberto no painel) que NÃO foi criado por este
        mesmo lead novo? Devolve o motivo para ignorar, ou None para etiquetar."""
        if chave_card := dados.get("chave_card"):
            # O card do lead novo roda junto com esta etiqueta: espera ele terminar (até ~5 s) antes de decidir. Sem isso,
            # o card gravado antes de a ação dele virar 'feita' fazia a etiqueta achar que o lead "já tinha card".
            for _ in range(10):
                irma = await self._pool.fetchrow(
                    "select situacao, resultado from agentesia_acoes where chave_unica = $1", chave_card)
                if not irma or irma["situacao"] not in ("pendente", "executando"):
                    break
                await asyncio.sleep(0.5)
            if irma and irma["situacao"] == "feita":
                resultado = irma["resultado"] if isinstance(irma["resultado"], dict) else json.loads(irma["resultado"] or "{}")
                if resultado.get("acao") == "criou":
                    return None                          # o card nasceu agora, com este lead: etiqueta SDR vale
        lead = contexto.get("lead") or {}
        if lead.get("id") and await self._pool.fetchval(
                "select exists(select 1 from agentesia_crm_cards where id_lead = $1::uuid)", str(lead["id"])):
            return "o lead já tem card; a etiqueta SDR segue o card do lead novo"
        if dados.get("id_painel") and await contexto["helena"].card_do_contato(dados["id_painel"], id_contato):
            return "o contato já tem card aberto neste painel; a etiqueta SDR segue o card do lead novo"
        return None

    async def _nota(self, contexto: dict[str, Any], dados: dict[str, Any]) -> dict[str, Any]:
        # Sem lead (contato sem número), a nota vai pela sessão que veio no webhook.
        sessao = (contexto.get("lead") or {}).get("id_sessao_helena") or dados.get("id_sessao")
        if not sessao:
            raise ErroDeCadastro("lead sem atendimento da Helena")
        await contexto["helena"].nota(sessao, dados["texto"])
        return {}

    async def _transferir(self, contexto: dict[str, Any], dados: dict[str, Any]) -> dict[str, Any]:
        sessao = (contexto.get("lead") or {}).get("id_sessao_helena")
        if not sessao:
            raise ErroDeCadastro("lead sem atendimento da Helena")
        await contexto["helena"].transferir(sessao, dados["id_equipe"])
        return {"equipe": dados["id_equipe"]}


    # ------------------------------------------------------------------ avisos à equipe
    async def _preparar_aviso(self, contexto: dict[str, Any], dados: dict[str, Any]) -> dict[str, Any]:
        """Lê o aviso configurado para o evento, monta o texto e põe um envio por destinatário na fila.

        Separar em dois passos faz a nova tentativa repetir só o número que falhou."""
        from app import notificacoes

        aviso = await self._pool.fetchrow(
            """select * from agentesia_notificacoes where id_escritorio = $1::uuid and tipo_evento = $2""",
            contexto["id_escritorio"], dados["evento"])
        if not aviso or not aviso["habilitada"]:
            return {"enviados": 0, "motivo": "sem_aviso_configurado"}
        if await self._aviso_na_janela(contexto, dados["evento"], dados.get("_id_acao")):
            return {"enviados": 0, "motivo": "aviso_repetido_na_janela"}
        # A mensagem do lead é o que ele mandou no turno que disparou o aviso (as mensagens juntadas, como no n8n);
        # aviso que não nasce de turno (contrato assinado...) leva a última mensagem dele.
        info = await self._pool.fetchrow(
            """select ct.nome, ct.telefone_normalizado, ca.numero_normalizado as numero_canal, ca.tipo as tipo_canal,
                      ag.produto, ag.nome as agente, ag.config as config_agente, et.codigo as etapa, l.origem,
                      l.id_sessao_helena,
                      es.config as config_escritorio,
                      (select k.link from agentesia_contratos k where k.id_lead = l.id and k.situacao in ('gerado', 'assinado')
                        order by k.versao desc limit 1) as link_assinatura,
                      (select k.dados->>'valor' from agentesia_contratos k where k.id_lead = l.id
                        order by k.versao desc limit 1) as valor,
                      coalesce(
                        (select string_agg(coalesce(nullif(btrim(m.texto), ''), nullif(btrim(m.texto_extraido), '')), chr(10)
                                           order by m.enviada_em)
                           from agentesia_acoes a join agentesia_mensagens m on m.id_turno = a.id_turno
                          where a.id = $2::uuid and m.id_lead = l.id and m.autor = 'lead'),
                        (select coalesce(nullif(btrim(m.texto), ''), nullif(btrim(m.texto_extraido), ''))
                           from agentesia_mensagens m
                          where m.id_lead = l.id and m.autor = 'lead'
                            and coalesce(nullif(btrim(m.texto), ''), nullif(btrim(m.texto_extraido), '')) is not null
                          order by m.enviada_em desc limit 1)) as mensagem_lead
               from agentesia_leads l join agentesia_contatos ct on ct.id = l.id_contato
               join agentesia_canais ca on ca.id = l.id_canal
               join agentesia_escritorios es on es.id = l.id_escritorio
               left join agentesia_agentes ag on ag.id = l.id_agente
               left join agentesia_agente_etapas et on et.id = l.id_etapa
               where l.id = $1::uuid""", (contexto.get("lead") or {}).get("id"), dados.get("_id_acao"))
        if not info:
            raise ErroDeCadastro("lead do aviso não encontrado")
        destinatarios = notificacoes.filtrar_destinatarios(
            aviso["destinatarios"] if isinstance(aviso["destinatarios"], list) else json.loads(aviso["destinatarios"] or "[]"),
            info["numero_canal"])
        if not destinatarios:
            await self._registrar_evento(contexto, "aviso_sem_destinatario", "aviso", "cadastro",
                                         f"O aviso \"{aviso['nome']}\" não tem número para receber.")
            return {"enviados": 0, "motivo": "sem_destinatarios"}
        from app.cerebro import sinais

        origem = info["origem"] if isinstance(info["origem"], dict) else json.loads(info["origem"] or "null") if info["origem"] else None
        config_escritorio = info["config_escritorio"]
        if not isinstance(config_escritorio, dict):
            config_escritorio = json.loads(config_escritorio or "{}")
        # {{produto}} é o nome do benefício (o do painel, "Auxílio-Acidente"), nunca o código ("catalogo").
        nome_produto = await self._nome_do_caso(info["produto"], info["config_agente"])
        valores = notificacoes.valores_do_aviso(
            evento=dados["evento"], nome=info["nome"], telefone=info["telefone_normalizado"],
            produto="" if nome_produto == "não informado" else nome_produto,
            etapa=notificacoes.NOMES_DE_EVENTO.get(f"etapa:{info['etapa']}") or _nome_da_etapa(info["produto"], info["config_agente"], info["etapa"]),
            valor=info["valor"], link_assinatura=info["link_assinatura"],
            origem=(origem or {}).get("origem") if isinstance(origem, dict) else None,
            link_conversa=sinais.link_da_conversa(config_escritorio, info["id_sessao_helena"]),
            mensagem_lead=info["mensagem_lead"], gatilhos=_gatilhos_do_agente(info["produto"], info["config_agente"]),
            sinais=dados.get("sinais"))
        resumo_no_aviso = None
        modelo_aviso = aviso["modelo_mensagem"]
        if dados["evento"] in ("contrato_assinado", "etapa:contrato_assinado"):
            # Modelo do escritório vazio ou o genérico: o aviso do n8n (cliente, telefone, link do chat, caso, resumo e
            # "Vamos pra cima"). {{resumo}}/{{caso}} no modelo próprio, ou o resumo no fim quando "resumo no aviso".
            from app.contrato import resumo as cresumo

            resumo_no_aviso = await self._pool.fetchval(
                """select resumo from agentesia_contratos where id_lead = $1::uuid and situacao = 'assinado'
                   order by versao desc limit 1""", (contexto.get("lead") or {}).get("id"))
            config_agente = info["config_agente"] if isinstance(info["config_agente"], dict) else json.loads(info["config_agente"] or "{}")
            caso = await self._nome_do_caso(info["produto"], config_agente)
            valores["resumo"] = resumo_no_aviso or ""
            valores["caso"] = caso
            _, config_zapsign = await self._zapsign(contexto["id_escritorio"])
            if not str(modelo_aviso or "").strip() or str(modelo_aviso).strip() == notificacoes.MODELO_PADRAO.strip():
                modelo_aviso = cresumo.MODELO_AVISO_ASSINADO
            if "resumo" in notificacoes._MARCADOR.findall(modelo_aviso or "") \
                    or not cresumo.configuracao(config_agente, config_zapsign, caso)["no_aviso"]:
                resumo_no_aviso = None
            if not cresumo.configuracao(config_agente, config_zapsign, caso)["no_aviso"]:
                valores["resumo"] = ""
        texto = notificacoes.renderizar_modelo(modelo_aviso, valores)
        if resumo_no_aviso:
            texto = cresumo.com_resumo_no_aviso(texto, resumo_no_aviso)
        envio = await self._numero_de_envio(contexto["id_escritorio"], info["numero_canal"], config_escritorio)
        if not envio:
            await self._sem_numero_de_envio(contexto)
            return {"enviados": 0, "motivo": "numero_de_envio_oficial"}
        de, tipo_de = envio
        destinatarios = [d for d in destinatarios if d.numero != de]          # nunca para o próprio número que envia
        await self._pool.executemany(
            """insert into agentesia_acoes (id_escritorio, id_lead, id_turno, tipo, chave_unica, dados)
               select id_escritorio, id_lead, id_turno, 'notificar', $2, $3::jsonb from agentesia_acoes where id = $1
               on conflict (chave_unica) do nothing""",
            [(dados["_id_acao"], f"{dados['_id_acao']}:{d.numero}",
              json.dumps({"de": de, "para": d.numero, "rotulo": d.rotulo, "texto": texto,
                          "tipo_canal": tipo_de, "evento": dados["evento"]}, ensure_ascii=False))
             for d in destinatarios])
        return {"enviados": len(destinatarios), "aviso": aviso["nome"]}

    async def _aviso_consumo(self, contexto: dict[str, Any], dados: dict[str, Any]) -> dict[str, Any]:
        """Consumo da IA passou de uma faixa: evento no painel e WhatsApp para o aviso "consumo_limite"."""
        from app import notificacoes

        estourou = dados.get("faixa", 0) >= 100
        await self._registrar_evento(contexto, dados.get("tipo_evento") or ("limite_de_consumo" if estourou else "consumo_alto"),
                                     dados.get("gravidade") or ("critico" if estourou else "aviso"), "cliente",
                                     dados["texto"].replace("*", ""))
        aviso = await self._pool.fetchrow(
            "select * from agentesia_notificacoes where id_escritorio = $1::uuid and tipo_evento = 'consumo_limite' and habilitada",
            contexto["id_escritorio"])
        if not aviso:
            return {"enviados": 0, "motivo": "sem_aviso_configurado"}
        envio = await self._numero_de_envio(contexto["id_escritorio"], None)
        if not envio:
            await self._sem_numero_de_envio(contexto)
            return {"enviados": 0, "motivo": "numero_de_envio_oficial"}
        de, tipo_de = envio
        destinatarios = notificacoes.filtrar_destinatarios(
            aviso["destinatarios"] if isinstance(aviso["destinatarios"], list) else json.loads(aviso["destinatarios"] or "[]"),
            de)
        await self._pool.executemany(
            """insert into agentesia_acoes (id_escritorio, tipo, chave_unica, dados)
               values ($1::uuid, 'notificar', $2, $3::jsonb) on conflict (chave_unica) do nothing""",
            [(contexto["id_escritorio"], f"{dados['_id_acao']}:{d.numero}",
              json.dumps({"de": de, "para": d.numero, "rotulo": d.rotulo, "texto": dados["texto"],
                          "tipo_canal": tipo_de, "evento": "consumo_limite"}, ensure_ascii=False))
             for d in destinatarios])
        return {"enviados": len(destinatarios)}

    def _contexto_lawchat(self, id_escritorio: str) -> dict[str, Any]:
        from app import central_avisos
        cfg = central_avisos.configurada()
        if not cfg:
            raise ErroDeCadastro("central de avisos sem token ou números da LawChat no .env")
        return {"helena": self._helena_por_token(cfg["token"], self._url), "id_escritorio": id_escritorio, "central": cfg}

    async def _alertar_lawchat(self, contexto: dict[str, Any], dados: dict[str, Any]) -> dict[str, Any]:
        cfg = contexto["central"]
        enviados = []
        ja = set(dados.get("enviados_para") or [])           # nova tentativa: não repete quem já recebeu
        for numero in cfg["para"]:
            if numero in ja:
                continue
            await contexto["helena"].enviar_sem_atendimento(de=cfg["de"], para=numero, texto=dados["texto"])
            ja.add(numero)
            enviados.append(numero[-4:])
            if dados.get("_id_acao") is not None:
                await self._pool.execute(
                    """update agentesia_acoes set dados = dados || jsonb_build_object('enviados_para', $2::jsonb)
                       where id = $1""", dados["_id_acao"], json.dumps(sorted(ja)))
        return {"enviados": enviados}

    async def _notificar(self, contexto: dict[str, Any], dados: dict[str, Any]) -> dict[str, Any]:
        """Envia um aviso a um número da equipe. Na API oficial, conversa nova com número da equipe só abre com modelo
        aprovado pela Meta: o aviso nunca sai por número oficial. Se o 'de' gravado é oficial (aviso enfileirado antes,
        ou por outro caminho, como o lead quente), troca por um não oficial da conta; sem nenhum, registra e não envia."""
        de = dados["de"]
        if not await self._numero_envia_aviso(contexto["id_escritorio"], de, dados.get("tipo_canal")):
            envio = await self._numero_de_envio(contexto["id_escritorio"], None)
            if not envio:
                await self._sem_numero_de_envio(contexto)
                return {"enviado": False, "motivo": "numero_de_envio_oficial"}
            de = envio[0]
            if de == dados["para"]:
                return {"enviado": False, "motivo": "destinatario_e_o_numero_de_envio"}
        id_mensagem = await contexto["helena"].enviar_sem_atendimento(de=de, para=dados["para"], texto=dados["texto"])
        return {"id_mensagem": id_mensagem, "para": dados.get("rotulo"), **({"de": de} if de != dados["de"] else {})}

    async def _dificuldade_na_assinatura(self, contexto: dict[str, Any], lead: dict[str, Any], contrato: dict[str, Any]) -> None:
        """O lead diz que assinou, a ZapSign mostra que ele abriu o link e não concluiu: é dificuldade na assinatura
        (no n8n, 'dificuldadenaassinatura'). Nota no atendimento e o gatilho sinal:dificuldade_assinatura (aviso à
        equipe e o que o escritório configurou nele), uma vez por contrato. A IA segue ajudando o lead (não pausa)."""
        from app import automacoes

        base = f"{lead['id']}:assinatura:{contrato['id']}"
        await self._nota_unica(contexto, lead, f"{base}:dificuldade",
                               f"✍️ Dificuldade na assinatura: o lead disse que assinou, mas abriu o contrato e não concluiu. "
                               f"A IA mandou o link de novo; vale ajudar o lead ({automacoes.NOMES_SINAIS['dificuldade_assinatura']}).")
        await self._pool.execute(
            """insert into agentesia_eventos (id_escritorio, id_lead, tipo, gravidade, responsavel, descricao)
               select $1::uuid, $2::uuid, 'sinal_dificuldade_assinatura', 'aviso', 'lead', $3
               where not exists (select 1 from agentesia_eventos where id_lead = $2::uuid and tipo = 'sinal_dificuldade_assinatura'
                                 and descricao = $3)""",
            contexto["id_escritorio"], str(lead["id"]),
            f"Lead abriu o contrato v{contrato.get('versao') or '?'} e não concluiu a assinatura (ZapSign).")
        await self._disparar(contexto, lead, ["sinal:dificuldade_assinatura"], f"assinatura-travou-{contrato['id']}")

    async def _aviso_na_janela(self, contexto: dict[str, Any], evento: str, id_acao: Any) -> bool:
        """O mesmo aviso (evento) já foi para este lead dentro da janela (notificacoes.JANELA_AVISO_H)? Conta o envio
        enfileirado ou feito; não conta os envios desta mesma preparação (nova tentativa) nem os que falharam."""
        from app import notificacoes

        id_lead = (contexto.get("lead") or {}).get("id")
        if not id_lead:
            return False
        config = await self._pool.fetchval("select config from agentesia_escritorios where id = $1::uuid", contexto["id_escritorio"])
        horas = notificacoes.janela_do_aviso_h(config if isinstance(config, dict) else json.loads(config or "{}"))
        if horas <= 0:
            return False
        return bool(await self._pool.fetchval(
            """select exists(select 1 from agentesia_acoes
                             where id_lead = $1::uuid and tipo = 'notificar' and dados->>'evento' = any($2::text[])
                               and situacao in ('pendente', 'executando', 'feita')
                               and coalesce((resultado->>'enviado')::boolean, true)
                               and criado_em > now() - make_interval(secs => $3)
                               and left(chave_unica, length($4) + 1) <> $4 || ':')""",
            id_lead, notificacoes.eventos_do_mesmo_fato(evento), horas * 3600, str(id_acao or "-")))

    async def _numero_envia_aviso(self, id_escritorio: str, numero: str | None, tipo: str | None = None) -> bool:
        if tipo == "oficial" or not numero:
            return False
        from app import notificacoes

        canal = await self._pool.fetchrow(
            "select tipo, tipo_helena from agentesia_canais where id_escritorio = $1::uuid and numero_normalizado = $2 limit 1",
            id_escritorio, numero)
        return notificacoes.canal_envia_aviso(canal["tipo"], canal["tipo_helena"]) if canal else True

    async def _numero_de_envio(self, id_escritorio: str, numero_preferido: str | None,
                               config_escritorio: dict[str, Any] | None = None) -> tuple[str, str] | None:
        """Número de WhatsApp da conta que manda o aviso, nunca oficial. Ordem: o escolhido pelo escritório (config
        'avisos_numero_envio', número ou id do canal; se for oficial, não envia), o canal do lead, outro canal ativo não
        oficial da conta. None = não há número que possa enviar."""
        from app import notificacoes

        if config_escritorio is None:
            bruto = await self._pool.fetchval("select config from agentesia_escritorios where id = $1::uuid", id_escritorio)
            config_escritorio = bruto if isinstance(bruto, dict) else json.loads(bruto or "{}")
        canais = [dict(c) for c in await self._pool.fetch(
            """select id::text, numero_normalizado, tipo, tipo_helena, ativo from agentesia_canais
               where id_escritorio = $1::uuid order by criado_em""", id_escritorio)]
        escolhido = str((config_escritorio or {}).get(notificacoes.CONFIG_NUMERO_ENVIO) or "").strip()
        if escolhido:
            numero = notificacoes.normalizar_numero(escolhido)
            canal = next((c for c in canais if escolhido == c["id"] or (numero and c["numero_normalizado"] == numero)), None)
            if canal:
                return (canal["numero_normalizado"], canal["tipo"]) \
                    if notificacoes.canal_envia_aviso(canal["tipo"], canal["tipo_helena"]) else None
        bons = [c for c in canais if c["numero_normalizado"] and notificacoes.canal_envia_aviso(c["tipo"], c["tipo_helena"])]
        preferido = next((c for c in bons if c["numero_normalizado"] == numero_preferido), None)
        canal = preferido or next((c for c in bons if c["ativo"]), None)
        return (canal["numero_normalizado"], canal["tipo"]) if canal else None

    async def _sem_numero_de_envio(self, contexto: dict[str, Any]) -> None:
        """Aviso que não saiu porque o número de envio é oficial: evento 1 vez por dia no escritório e nota 1 vez no
        atendimento do lead (não repete a cada aviso)."""
        from app import notificacoes

        if not await self._pool.fetchval(
                """select exists(select 1 from agentesia_eventos where id_escritorio = $1::uuid and tipo = 'aviso_numero_oficial'
                                 and criado_em > now() - interval '24 hours')""", contexto["id_escritorio"]):
            await self._registrar_evento(contexto, "aviso_numero_oficial", "aviso", "cadastro", notificacoes.TEXTO_NUMERO_OFICIAL)
        id_lead = (contexto.get("lead") or {}).get("id")
        if id_lead:
            await self._pool.execute(
                """insert into agentesia_acoes (id_escritorio, id_lead, tipo, chave_unica, dados)
                   select $1::uuid, $2::uuid, 'nota', $3, $4::jsonb from agentesia_leads
                   where id = $2::uuid and id_sessao_helena is not null
                   on conflict (chave_unica) do nothing""",
                contexto["id_escritorio"], id_lead, f"{id_lead}:aviso_numero_oficial",
                json.dumps({"texto": notificacoes.NOTA_NUMERO_OFICIAL}, ensure_ascii=False))

    async def _etapa_trocada(self, contexto: dict[str, Any], lead: dict[str, Any], para: str, motivo: str) -> None:
        """Histórico de troca de etapa feita fora do turno (contrato): o mesmo evento 'etapa_trocada' do pipeline."""
        de = lead.get("etapa")
        await self._pool.execute(
            """insert into agentesia_eventos (id_escritorio, id_lead, tipo, gravidade, responsavel, descricao, detalhe)
               values ($1::uuid, $2::uuid, 'etapa_trocada', 'info', 'lawchat', $3, $4::jsonb)""",
            contexto["id_escritorio"], str(lead["id"]), f"Etapa do lead: {de or '-'} → {para} ({motivo}).",
            json.dumps({"de": de, "para": para, "origem": "contrato", "motivo": motivo}, ensure_ascii=False))

    async def _registrar_evento(self, contexto: dict[str, Any], tipo: str, gravidade: str, responsavel: str,
                                descricao: str) -> None:
        await self._pool.execute(
            """insert into agentesia_eventos (id_escritorio, id_lead, tipo, gravidade, responsavel, descricao)
               values ($1::uuid, $2::uuid, $3, $4, $5, $6)""",
            contexto["id_escritorio"], (contexto.get("lead") or {}).get("id"), tipo, gravidade, responsavel, descricao)


    # ------------------------------------------------------------------ entrega das respostas da IA
    STATUS_PENDENTES = {"QUEUED", "PENDING", "SENDING", "PROCESSING"}

    async def _conferir_entrega(self, contexto: dict[str, Any], dados: dict[str, Any]) -> dict[str, Any]:
        """Um minuto depois do turno: a Helena entregou as mensagens da IA? O envio é assíncrono (o POST só diz que
        entrou na fila). FAILED vira 'falhou' na mensagem, evento envio_falhou e nota no chat (1 a cada 6 h).
        Ainda na fila: confere de novo uma vez, 5 minutos depois."""
        from app.banco.postgres import RepositorioPostgres
        from app.pipeline import Atendimento

        repo = RepositorioPostgres(self._pool)
        lead = contexto.get("lead") or {}
        falhas: list[dict[str, Any]] = []
        pendentes: list[str] = []
        # Primeiro consulta todas; só depois marca. Se uma consulta falhar no meio (5xx, limite), nada foi marcado e a
        # nova tentativa enxerga a falha de novo (marcar_envio_falhou só devolve a linha na primeira vez: marcar antes
        # e cair depois perdia o evento e a nota).
        consultas: list[tuple[str, dict[str, Any]]] = []
        for id_mensagem in dados.get("ids") or []:
            try:
                situacao = await contexto["helena"].status_da_mensagem(str(id_mensagem))
            except ErroHelenaApi as erro:
                if erro.motivo == "nao_encontrado":          # a Helena não conhece o id: nada a conferir
                    continue
                raise
            consultas.append((str(id_mensagem), situacao or {}))
        for id_mensagem, situacao in consultas:
            status = str(situacao.get("status") or "").upper()
            if status == "FAILED":
                motivo = str(situacao.get("failureReason") or "falha na entrega")
                linha = await repo.marcar_envio_falhou(id_escritorio=contexto["id_escritorio"], id_externo=str(id_mensagem),
                                                       erro=f"Helena: {motivo}")
                if linha:
                    falhas.append({"id": str(id_mensagem), "motivo": motivo, "trecho": (linha.get("texto") or linha.get("url_midia") or "")[:200]})
            elif status in self.STATUS_PENDENTES:
                pendentes.append(str(id_mensagem))
        if falhas:
            await self._pool.execute(
                """insert into agentesia_eventos (id_escritorio, id_lead, id_turno, tipo, gravidade, responsavel, descricao, detalhe)
                   values ($1::uuid, $2::uuid, $3::uuid, 'envio_falhou', 'erro', 'provedor', $4, $5::jsonb)""",
                contexto["id_escritorio"], lead.get("id"), dados.get("id_turno"),
                f"A Helena não entregou {len(falhas)} parte(s) da resposta da IA ({falhas[0]['motivo'][:200]}).",
                json.dumps({"falhas": falhas}, ensure_ascii=False))
            if lead.get("id") and lead.get("id_sessao_helena"):
                await repo.nota_de_problema(id_escritorio=contexto["id_escritorio"], id_lead=str(lead["id"]),
                                            tipo="envio_falhou", texto=Atendimento.NOTAS_DE_PROBLEMA["envio_falhou"])
        if pendentes and not dados.get("reconferencia"):
            await self._enfileirar(contexto, "conferir_entrega", f"{dados.get('id_turno') or dados.get('_id_acao')}:entrega:2",
                                   {"ids": pendentes, "id_turno": dados.get("id_turno"), "reconferencia": True}, minutos=5)
        return {"falhas": len(falhas), "na_fila": len(pendentes)}

    # ------------------------------------------------------------------ mensagem ao lead
    async def _enviar_mensagem(self, contexto: dict[str, Any], dados: dict[str, Any]) -> dict[str, Any]:
        lead = await self._lead_completo(contexto["lead"]["id"])
        if not lead.get("id_sessao_helena"):
            raise ErroDeCadastro("lead sem atendimento da Helena")
        id_mensagem = await contexto["helena"].enviar_no_atendimento(
            lead["id_sessao_helena"], texto=dados.get("texto"), url_arquivo=dados.get("url_arquivo"), id_canal=lead["id_canal_helena"])
        return {"id_mensagem": id_mensagem}

    # ------------------------------------------------------------------ contrato
    async def _gerar_contrato(self, contexto: dict[str, Any], dados: dict[str, Any]) -> dict[str, Any]:
        """Valida, reserva a versão, cria na ZapSign, grava, manda o link e move o lead para 'assinatura'."""
        from datetime import datetime

        from app.contrato import dados as cdados
        from app.contrato import servico
        from app.notificacoes import fuso

        lead = await self._lead_completo(contexto["lead"]["id"])
        zapsign, config = await self._zapsign(contexto["id_escritorio"])
        chave_base = f"{lead['id']}:contrato:{dados.get('hash', '')[:16]}"
        if dados.get("_id_acao") is not None and await servico.geracao_obsoleta(self._pool, dados["_id_acao"]):
            # Voltou tarde (esperava nova tentativa) e o lead já corrigiu um dado: o pedido mais novo vale.
            return {"situacao": "obsoleta", "motivo": "há um pedido de contrato mais novo para este lead"}
        modelo = self._modelo_do_contrato(config, str(lead.get("id_agente") or ""))
        if zapsign is None or modelo is None:
            await self._contrato_falhou(contexto, lead, chave_base, "sem_integracao")
            return {"situacao": "sem_integracao"}
        valido, erros = cdados.validar_dados(dados.get("dados") or {}, lead.get("telefone_normalizado"),
                                             modelo.get("obrigatorios") or cdados.OBRIGATORIOS_PADRAO)
        if erros:
            await self._mensagem_ao_lead(contexto, lead, f"{chave_base}:corrigir", cdados.pedir_correcao(erros))
            await self._nota_unica(contexto, lead, f"{chave_base}:nota_corrigir",
                                   "A IA não gerou o contrato porque dados não conferem (" + ", ".join(e.campo for e in erros) + "). Ela pediu a correção ao lead.")
            return {"situacao": "dado_invalido", "campos": [e.campo for e in erros]}
        hash_dados = cdados.hash_dados(valido)
        if contato := await self._so_mudou_o_contato(contexto, lead, zapsign, config, valido, hash_dados, chave_base):
            return contato
        reserva = await servico.reservar(self._pool, id_escritorio=contexto["id_escritorio"], id_lead=str(lead["id"]),
                                         dados=valido, hash_dados=hash_dados, limite=int(config.get("limite_versoes") or 3),
                                         id_acao=str(dados["_id_acao"]))
        if reserva.decisao == "mesmo":
            await self._mensagem_ao_lead(contexto, lead, f"{chave_base}:mesmo", cdados.texto(config, "mesmo_link", link=reserva.link_atual))
            return {"situacao": "mesmo_link", "versao": reserva.versao}
        if reserva.decisao == "ja_assinado":
            await self._mensagem_ao_lead(contexto, lead, f"{chave_base}:ja", cdados.texto(config, "ja_assinado"))
            return {"situacao": "ja_assinado"}
        if reserva.decisao == "gerando":
            raise ErroZapSign("fora_do_ar", "outra geração em andamento; tenta de novo em instantes")
        if reserva.decisao == "limite":
            await self._mensagem_ao_lead(contexto, lead, f"{chave_base}:limite", cdados.texto(config, "limite"))
            await self._nota_unica(contexto, lead, f"{chave_base}:nota_limite",
                                   f"O lead pediu mais uma alteração no contrato, mas já foram gerados {reserva.documentos_feitos} contratos. A alteração precisa ser feita pela equipe.")
            return {"situacao": "limite"}
        if problema := await self._problema_no_plano(zapsign):
            # Sem crédito ou plano em atraso: a equipe é avisada em vez de a geração falhar calada (e não gasta tentativa).
            await servico.marcar_falha(self._pool, id_contrato=reserva.id_contrato or "", causa=problema,
                                       erro=cdados.NOTAS_CAUSA[problema])
            await self._contrato_falhou(contexto, lead, chave_base, problema)
            return {"situacao": f"zapsign_{problema}"}
        agora = datetime.now(fuso(config.get("fuso") or "America/Sao_Paulo"))
        variaveis = cdados.montar_variaveis(valido, modelo.get("mapeamento") or cdados.MAPEAMENTO_PADRAO, agora)
        try:
            documento = await zapsign.criar_de_modelo(
                id_modelo=modelo["id_modelo"], id_externo=reserva.id_contrato or "", nome=valido["nome"],
                telefone=valido.get("telefone"), email=valido.get("email"), variaveis=variaveis)
        except ErroZapSign as erro:
            await servico.marcar_falha(self._pool, id_contrato=reserva.id_contrato or "", causa=erro.motivo, erro=str(erro))
            if erro.do_escritorio:
                await self._contrato_falhou(contexto, lead, chave_base, erro.motivo)
                return {"situacao": f"zapsign_{erro.motivo}"}
            await self._mensagem_ao_lead(contexto, lead, f"{chave_base}:imprevisto", cdados.texto(config, "imprevisto"))
            raise                                         # fora do ar: o executor tenta de novo (1, 5, 30, 120 min)
        await servico.gravar_gerado(self._pool, id_contrato=reserva.id_contrato or "", documento=documento,
                                    id_modelo=modelo["id_modelo"])
        link = await self._pool.fetchval("select link from agentesia_contratos where id = $1::uuid", reserva.id_contrato) \
            or documento.link
        await servico.cancelar_lembretes(self._pool, str(lead["id"]))
        if config.get("cancelar_versao_anterior", True):
            # A versão substituída continuava assinável na ZapSign: cancela depois de gravar a nova (fila, sem avisar o lead).
            for antiga in await servico.versoes_para_cancelar(self._pool, id_lead=str(lead["id"]),
                                                              id_contrato_novo=reserva.id_contrato or ""):
                await self._enfileirar(contexto, "cancelar_contrato", f"zapsign:cancelar:{antiga['id_documento_externo']}",
                                       {"id_contrato": str(antiga["id"]), "token_documento": antiga["id_documento_externo"],
                                        "motivo": f"Substituído pela versão {reserva.versao}"})
        chave_versao = f"{lead['id']}:contrato:v{reserva.versao}"
        texto = cdados.texto(config, "link" if (reserva.versao or 1) == 1 else "nova_versao", link=link)
        await self._mensagem_ao_lead(contexto, lead, f"{chave_versao}:link", texto)
        await self._nota_unica(contexto, lead, f"{chave_versao}:nota", "Acompanhar lead pois acabou de gerar um contrato."
                               + (f" (versão {reserva.versao})" if (reserva.versao or 1) > 1 else ""))
        moveu = await servico.mover_lead_para_etapa(self._pool, str(lead["id"]), "assinatura")
        if moveu:
            await self._etapa_trocada(contexto, lead, "assinatura", f"contrato gerado (versão {reserva.versao})")
        await self._disparar(contexto, lead, ["contrato_gerado"] + (["etapa:assinatura"] if moveu else []), f"contrato-v{reserva.versao}")
        lembretes = config.get("lembretes") or {"ativo": True, "horas": [2, 24, 72]}
        if lembretes.get("ativo", True):
            for horas in lembretes.get("horas") or []:
                await self._enfileirar(contexto, "lembrar_assinatura", f"{chave_versao}:lembrete:{horas}",
                                       {"id_contrato": reserva.id_contrato}, minutos=float(horas) * 60)
        return {"situacao": "gerado", "versao": reserva.versao, "link": link}

    async def _so_mudou_o_contato(self, contexto: dict[str, Any], lead: dict[str, Any], zapsign: ZapSign,
                                  config: dict[str, Any], valido: dict[str, str], hash_dados: str,
                                  chave_base: str) -> dict[str, Any] | None:
        """O lead corrigiu só o telefone ou o e-mail depois do link: atualiza o signatário na ZapSign, sem contrato novo
        (sem gastar versão nem crédito). None = não é o caso (segue a geração normal)."""
        from app.contrato import dados as cdados
        from app.contrato import servico

        if config.get("atualizar_contato_sem_nova_versao") is False:
            return None
        vigente = await self._pool.fetchrow(
            """select id, versao, dados, dados_hash, link, id_assinante_externo from agentesia_contratos
               where id_lead = $1 and situacao = 'gerado'""", lead["id"])
        if not vigente or not vigente["id_assinante_externo"] or vigente["dados_hash"] == hash_dados:
            return None
        antigos = vigente["dados"] if isinstance(vigente["dados"], dict) else json.loads(vigente["dados"] or "{}")
        contato = ("telefone", "email")
        if {k: v for k, v in antigos.items() if k not in contato} != {k: v for k, v in valido.items() if k not in contato}:
            return None
        telefone = valido.get("telefone") if valido.get("telefone") != antigos.get("telefone") else None
        email = valido.get("email") if valido.get("email") != antigos.get("email") else None
        if not telefone and not email:
            return None
        try:
            await zapsign.atualizar_signatario(vigente["id_assinante_externo"], telefone=telefone, email=email)
        except ErroZapSign as erro:
            if erro.motivo == "fora_do_ar":
                raise
            return None                     # o signatário não aceita mais mudança (assinou, recusou): versão nova
        await servico.atualizar_contato(self._pool, id_contrato=str(vigente["id"]), dados=valido, hash_dados=hash_dados)
        campos = [n for n, v in (("telefone", telefone), ("e-mail", email)) if v]
        await self._mensagem_ao_lead(contexto, lead, f"{chave_base}:contato",
                                     cdados.texto(config, "contato_atualizado", link=vigente["link"]))
        await self._nota_unica(contexto, lead, f"{chave_base}:nota_contato",
                               f"O lead corrigiu o {' e o '.join(campos)} do contrato. O signatário foi atualizado na ZapSign "
                               f"sem gerar contrato novo (continua a versão {vigente['versao']}). Se o modelo mostra o "
                               "contato no texto, o texto continua com o contato antigo.")
        return {"situacao": "contato_atualizado", "versao": vigente["versao"], "campos": campos}

    async def _problema_no_plano(self, zapsign: ZapSign) -> str | None:
        """Plano e créditos (GET /info-plan) antes de gerar. Só trava com resposta clara (sem crédito, pagamento
        pendente); sem a informação (conta sem o endpoint, 404, fora do ar) a geração segue. Plano ok fica 5 min em cache."""
        import time

        from app.canal.zapsign import problema_do_plano

        chave = getattr(zapsign, "chave_cache", None)
        agora = time.monotonic()
        if chave and agora - _PLANOS_OK.get(chave, float("-inf")) < 300:
            return None
        try:
            plano = await zapsign.plano()
        except ErroZapSign:
            return None
        problema = problema_do_plano(plano)
        if chave and problema is None:
            _PLANOS_OK[chave] = agora
        return problema

    @staticmethod
    def _modelo_do_contrato(config: dict[str, Any], id_agente: str) -> dict[str, Any] | None:
        """O modelo do agente vale mais que o padrão do escritório."""
        modelos = [m for m in config.get("modelos") or [] if m.get("id_modelo")]
        return next((m for m in modelos if id_agente and m.get("id_agente") == id_agente), None) or \
            next((m for m in modelos if m.get("padrao")), None) or (modelos[0] if len(modelos) == 1 else None)

    async def _contrato_falhou(self, contexto: dict[str, Any], lead: dict[str, Any], chave: str, causa: str) -> None:
        from app.contrato import dados as cdados

        _, config = await self._zapsign(contexto["id_escritorio"])
        await self._mensagem_ao_lead(contexto, lead, f"{chave}:equipe", cdados.texto(config, "equipe_envia"))
        await self._nota_unica(contexto, lead, f"{chave}:nota_falha",
                               f"⚠️ A IA tentou gerar o contrato deste lead e NÃO conseguiu: {cdados.NOTAS_CAUSA.get(causa, causa)} "
                               "Enquanto isso, o contrato deste lead precisa ser gerado manualmente.")
        await self._registrar_evento(contexto, f"contrato_{causa}", "erro", "cadastro" if causa == "sem_integracao" else "cliente",
                                     f"Contrato não gerado: {cdados.NOTAS_CAUSA.get(causa, causa)}")
        await self._disparar(contexto, lead, ["contrato_falhou"], f"contrato-falhou-{chave[-16:]}")

    async def _ler_documento(self, zapsign: ZapSign, contrato: dict[str, Any], lead: dict[str, Any]):
        """Relê o documento e acha o lead entre os assinantes (token guardado, telefone, external_id, nome)."""
        from app.contrato import assinatura

        documento = await zapsign.documento(contrato["id_documento_externo"])
        dados = contrato.get("dados")
        dados = dados if isinstance(dados, dict) else json.loads(dados or "{}")
        quem, _como = assinatura.identificar_lead(documento, contrato.get("id_assinante_externo"),
                                                  lead.get("telefone_normalizado"), str(contrato["id"]), dados.get("nome"))
        return documento, quem, assinatura.ler(documento, quem)

    @staticmethod
    def _leitura_para_ia(leitura: Any, config: dict[str, Any]) -> dict[str, Any]:
        """O que fica no resultado da ação: a leitura e a linha (sistema) que vai para a IA no próximo turno."""
        from datetime import datetime

        from app.contrato import assinatura
        from app.notificacoes import fuso

        quando = datetime.now(fuso(config.get("fuso") or "America/Sao_Paulo")).strftime("%d/%m %H:%M")
        return {"leitura": leitura.como_dict(), "linha_ia": assinatura.linha_para_ia(leitura, quando)}

    async def _contrato_encerrado(self, contexto: dict[str, Any], lead: dict[str, Any], contrato: dict[str, Any],
                                  leitura: Any, config: dict[str, Any], *, chave_lead: str | None) -> dict[str, Any]:
        """Documento recusado/cancelado, excluído ou vencido na ZapSign. Contrato vigente: vira 'cancelado', para os
        lembretes, deixa nota, pausa a IA neste lead e avisa a equipe (uma vez). Versão já substituída (o cancelamento
        automático da versão antiga): só registra. chave_lead: manda ao lead o aviso (sem link) com esta chave."""
        from app.contrato import dados as cdados
        from app.contrato import servico

        causa = leitura.situacao
        if contrato["situacao"] == "substituido":
            return {"resultado": f"versao_antiga_{causa}"}
        nomes = {"cancelado": "cancelado ou recusado", "excluido": "excluído", "expirado": "vencido (passou do prazo)"}
        primeira = contrato["situacao"] == "gerado" and await servico.marcar_encerrado(
            self._pool, id_contrato=str(contrato["id"]), causa=causa, motivo=leitura.motivo)
        if primeira:
            await servico.cancelar_lembretes(self._pool, str(lead["id"]))
            pausou = await servico.pausar_ia(self._pool, str(lead["id"]), f"contrato_{causa}")
            motivo = f" Motivo na ZapSign: {leitura.motivo}." if leitura.motivo else ""
            await self._nota_unica(contexto, lead, f"{lead['id']}:contrato:{contrato['id']}:encerrado",
                                   f"⚠️ O contrato (versão {contrato['versao']}) foi {nomes[causa]} na ZapSign e não pode mais "
                                   f"ser assinado.{motivo} Os lembretes foram cancelados"
                                   + (" e a IA foi pausada nesta conversa" if pausou else "")
                                   + ". Uma pessoa da equipe precisa falar com o lead (e gerar um contrato novo, se for o caso).")
            await self._registrar_evento(contexto, f"contrato_{causa}", "aviso", "cliente",
                                         f"Contrato {nomes[causa]} na ZapSign (versão {contrato['versao']}). Lembretes cancelados"
                                         + (" e IA pausada nesse lead." if pausou else "."))
            await self._disparar(contexto, lead, ["contrato_recusado"], f"contrato-encerrado-{contrato['id']}")
        if chave_lead:
            await self._mensagem_ao_lead(contexto, lead, chave_lead, cdados.texto(config, "cancelado"))
        return {"resultado": causa, "primeira": bool(primeira)}

    async def _verificar_assinatura(self, contexto: dict[str, Any], dados: dict[str, Any]) -> dict[str, Any]:
        """Relê o documento na ZapSign (nunca confia só no aviso) e decide: assinado (efeitos uma vez), recusado/excluído/
        vencido (encerra), ou pendente (no "já assinei": nunca abriu -> link de novo; abriu e não concluiu -> onde travou).
        A leitura volta no resultado como a linha (sistema) que a IA recebe no próximo turno."""
        from app.contrato import dados as cdados
        from app.contrato import resumo as cresumo
        from app.contrato import servico

        contrato = await servico.contrato_para_verificar(
            self._pool, id_escritorio=contexto["id_escritorio"], id_lead=(contexto.get("lead") or {}).get("id"),
            token_documento=dados.get("token_documento"))
        if not contrato:
            if dados.get("origem") == "verificacao" and (contexto.get("lead") or {}).get("id"):
                return await self._ja_assinei_sem_documento(contexto)
            return {"resultado": "sem_contrato"}
        if not contexto.get("lead"):
            contexto["lead"] = {"id": str(contrato["id_lead"])}
        lead = await self._lead_completo(str(contrato["id_lead"]), contexto["id_escritorio"])
        verificacao = dados.get("origem") == "verificacao"
        zapsign, config = await self._zapsign(contexto["id_escritorio"])
        if zapsign is None:
            raise ErroDeCadastro("escritório sem chave da ZapSign")
        documento, quem, leitura = await self._ler_documento(zapsign, contrato, lead)
        situacao = leitura.situacao
        para_ia = self._leitura_para_ia(leitura, config)
        base = f"{lead['id']}:assinatura:{contrato['id']}"
        if situacao == "assinado":
            primeira = await servico.marcar_assinado(
                self._pool, id_contrato=str(contrato["id"]), lead_assinou_em=quem.assinou_em if quem else None,
                concluido=documento.status == "signed", arquivo=documento.arquivo_assinado,
                signatarios=[{"nome": a.nome, "status": a.status, "assinou_em": a.assinou_em, "lead": a is quem}
                             for a in documento.assinantes])
            if not primeira:
                if verificacao:
                    await self._mensagem_ao_lead(contexto, lead, f"{base}:ja:{dados['_id_acao']}", cdados.texto(config, "ja_assinado"))
                return {"resultado": "ja_estava_assinado", **para_ia}
            # Fluxo CONTRATO ASSINADO (n8n B5-B13), efeitos uma vez: lembretes e follow-ups cancelados, etapa
            # "contrato assinado" (IA encerrada no lead), mensagem ao lead, transferência, card/etiquetas pelas
            # automações, PDF, resumo pela IA, nota "📄 Contrato Assinado!" e o aviso à equipe (que espera o resumo).
            await servico.cancelar_lembretes(self._pool, str(lead["id"]))
            await servico.cancelar_followups(self._pool, str(lead["id"]))
            if await servico.mover_lead_para_etapa(self._pool, str(lead["id"]), "contrato_assinado",
                                                   estado="encerrado", motivo_estado="contrato_assinado") \
                    and lead.get("etapa") != "contrato_assinado":
                await self._etapa_trocada(contexto, lead, "contrato_assinado", "contrato assinado")
            midia = (config.get("midia_pos_assinatura") or {}).get("url")
            if midia:
                await self._enfileirar(contexto, "enviar_mensagem", f"{base}:video", {"url_arquivo": midia})
            await self._enfileirar(contexto, "enviar_mensagem", f"{base}:confirmacao",
                                   {"texto": self._texto_pos_assinatura(config, lead)}, minutos=0.05 if midia else 0)
            config_contrato = (lead.get("config_agente") or {}).get("contrato")
            id_equipe = (config_contrato if isinstance(config_contrato, dict) else {}).get("id_equipe_assinado") \
                or config.get("id_equipe_assinado")
            if id_equipe and lead.get("id_sessao_helena"):
                await self._enfileirar(contexto, "transferir", f"{base}:transferir", {"id_equipe": str(id_equipe)})
            avisos_nota = []
            if verificacao:
                avisos_nota.append("✔️ Assinatura confirmada pela verificação na ZapSign (o lead disse que assinou).")
            if dados.get("achado_por"):
                avisos_nota.append(f"⚠️ O documento assinado não tinha o id do nosso contrato: foi ligado a este lead pelo "
                                   f"{dados['achado_por']} do signatário. Confira na ZapSign.")
            if contrato["situacao"] == "substituido":
                avisos_nota.append(f"⚠️ Atenção: o lead assinou a versão {contrato['versao']}, que já tinha sido substituída por uma mais nova. Confira qual versão vale.")
            if contrato["situacao"] == "cancelado":
                avisos_nota.append("⚠️ Atenção: este contrato constava como cancelado no sistema. Confira na ZapSign.")
            if config.get("guardar_pdf", True):
                # O signed_file vence em 60 min: o PDF vai para o nosso armazenamento (link permanente no contrato).
                await self._enfileirar(contexto, "guardar_pdf_assinado", f"{contrato['id']}:pdf:1", {"id_contrato": str(contrato["id"])})
            caso = await self._nome_do_caso(lead.get("produto"), lead.get("config_agente"))
            ajustes = cresumo.configuracao(lead.get("config_agente"), config, caso)
            resumir = ajustes["ativo"] and self._modelo is not None
            # Resumo no aviso "contrato assinado": o aviso espera o resumo (que dispara no fim, com ou sem resumo).
            # Card, etiquetas e o resto das automações não esperam.
            aviso_depois = resumir and ajustes["no_aviso"]
            await self._disparar(contexto, lead, ["contrato_assinado", "etapa:contrato_assinado"], f"assinado-{contrato['id']}",
                                 so_avisos=False if aviso_depois else None)
            if resumir:
                await self._enfileirar(contexto, "resumir_contrato", f"{base}:resumo",
                                       {"id_contrato": str(contrato["id"]), "aviso_depois": aviso_depois,
                                        "chave_nota": f"{base}:nota", "avisos_nota": avisos_nota, "caso": caso})
            else:
                await self._nota_unica(contexto, lead, f"{base}:nota", cresumo.nota(None, caso, avisos_nota))
            await self._registrar_evento(contexto, "contrato_assinado", "info", "lead",
                                         f"Contrato assinado (versão {contrato['versao']})"
                                         + (", confirmado pela verificação." if verificacao else "."))
            return {"resultado": "assinado", "versao": contrato["versao"], **para_ia}
        if situacao in ("cancelado", "excluido", "expirado"):
            resultado = await self._contrato_encerrado(
                contexto, lead, contrato, leitura, config,
                chave_lead=f"{base}:encerrado:{dados['_id_acao']}" if verificacao else None)
            return {**resultado, **para_ia}
        if situacao == "so_o_escritorio_assinou":
            await self._nota_unica(contexto, lead, f"{base}:so_escritorio", "O escritório assinou o contrato. A assinatura do lead ainda está pendente.")
        elif situacao == "nao_reconhecido":
            await self._nota_unica(contexto, lead, f"{base}:nao_reconhecido",
                                   "⚠️ Houve uma assinatura neste contrato, mas não foi possível identificar se quem assinou foi o lead. Confira na ZapSign.")
            await self._registrar_evento(contexto, "assinatura_nao_reconhecida", "aviso", "lawchat", "Assinatura não reconhecida na ZapSign.")
        if verificacao:
            link = contrato.get("link") or documento.link_de(contrato.get("id_assinante_externo"))
            chave_texto = "travou" if leitura.abertura == "abriu_sem_assinar" else "pendente"
            await self._mensagem_ao_lead(contexto, lead, f"{base}:pendente:{dados['_id_acao']}",
                                         cdados.texto(config, chave_texto, link=link))
            if chave_texto == "travou":
                await self._dificuldade_na_assinatura(contexto, lead, contrato)
        return {"resultado": situacao, "abertura": leitura.abertura, **para_ia}

    async def _cancelar_contrato(self, contexto: dict[str, Any], dados: dict[str, Any]) -> dict[str, Any]:
        """Cancela na ZapSign uma versão já substituída (POST /refuse/), para o link velho não ser mais assinável.
        Relê antes: se o lead assinou essa versão, não cancela (a verificação decide e avisa a equipe)."""
        contrato = await self._pool.fetchrow("select * from agentesia_contratos where id = $1::uuid and id_escritorio = $2::uuid",
                                             dados["id_contrato"], contexto["id_escritorio"])
        if not contrato or contrato["situacao"] != "substituido":
            return {"cancelado": False, "motivo": f"contrato {contrato['situacao'] if contrato else 'inexistente'}"}
        zapsign, _ = await self._zapsign(contexto["id_escritorio"])
        if zapsign is None:
            raise ErroDeCadastro("escritório sem chave da ZapSign")
        lead = await self._lead_completo(str(contrato["id_lead"]), contexto["id_escritorio"])
        _, _, leitura = await self._ler_documento(zapsign, dict(contrato), lead)
        if leitura.situacao == "assinado":
            await self._enfileirar(contexto, "verificar_assinatura", f"zapsign:{contrato['id_documento_externo']}:antiga-assinada",
                                   {"token_documento": contrato["id_documento_externo"], "origem": "zapsign"})
            return {"cancelado": False, "motivo": "o lead assinou esta versão"}
        if leitura.situacao in ("cancelado", "excluido", "expirado"):
            return {"cancelado": False, "motivo": f"já estava {leitura.situacao}"}
        try:
            await zapsign.cancelar(contrato["id_documento_externo"], dados.get("motivo") or "Substituído por uma versão mais nova")
        except ErroZapSign as erro:
            if erro.motivo == "nao_encontrado":
                return {"cancelado": False, "motivo": "a ZapSign não deixou cancelar (já assinado, já cancelado ou inexistente)"}
            raise
        await self._pool.execute("update agentesia_contratos set causa_erro = 'cancelado_na_zapsign' where id = $1",
                                 contrato["id"])
        return {"cancelado": True, "versao": contrato["versao"]}

    async def _guardar_pdf_assinado(self, contexto: dict[str, Any], dados: dict[str, Any]) -> dict[str, Any]:
        """Baixa o PDF assinado (o signed_file da ZapSign vence em 60 min) e guarda no bucket de mídia (modo supabase ou
        local); o link permanente vai para agentesia_contratos.arquivo_assinado. Espera o documento concluir (todos
        assinarem): tenta de novo a cada 6 h, até 8 vezes."""
        import secrets

        from app import armazenamento
        from app.contrato import servico

        contrato = await self._pool.fetchrow("select * from agentesia_contratos where id = $1::uuid and id_escritorio = $2::uuid",
                                             dados["id_contrato"], contexto["id_escritorio"])
        if not contrato or contrato["situacao"] != "assinado" or not contrato["id_documento_externo"]:
            return {"pdf": "sem_contrato_assinado"}
        if _pdf_guardado(contrato["arquivo_assinado"]):
            return {"pdf": "ja_guardado"}
        zapsign, _ = await self._zapsign(contexto["id_escritorio"])
        if zapsign is None:
            raise ErroDeCadastro("escritório sem chave da ZapSign")
        documento = await zapsign.documento(contrato["id_documento_externo"])
        tentativa = int(dados.get("tentativa") or 1)
        if documento.status != "signed" or not documento.arquivo_assinado:
            if tentativa < 8:
                await self._enfileirar(contexto, "guardar_pdf_assinado", f"{contrato['id']}:pdf:{tentativa + 1}",
                                       {"id_contrato": str(contrato["id"]), "tentativa": tentativa + 1}, minutos=360)
            return {"pdf": "aguardando_conclusao", "tentativa": tentativa}
        bruto = await zapsign.baixar(documento.arquivo_assinado)
        if not bruto.startswith(b"%PDF"):
            raise ErroZapSign("fora_do_ar", "o arquivo baixado da ZapSign não é um PDF")
        caminho = f"contratos/{contexto['id_escritorio']}/{contrato['id']}-{secrets.token_hex(8)}.pdf"
        url = await armazenamento.do_ambiente().enviar(caminho, bruto, "application/pdf")
        await servico.guardar_arquivo(self._pool, id_contrato=str(contrato["id"]), url=url)
        return {"pdf": "guardado", "url": url, "bytes": len(bruto)}

    def _texto_pos_assinatura(self, config: dict[str, Any], lead: dict[str, Any]) -> str:
        """Mensagem ao lead quando o contrato é assinado: a do escritório (Integrações > ZapSign > mensagens), senão a
        frase de entrada (mensagem_troca) do papel "contrato assinado" do agente, senão a padrão."""
        from app.contrato import dados as cdados

        if ((config or {}).get("mensagens") or {}).get("pos_assinatura"):
            return cdados.texto(config, "pos_assinatura")
        papeis = ((lead.get("config_agente") or {}).get("catalogo") or {}).get("papeis") or {}
        cfg = papeis.get("contrato_assinado") if isinstance(papeis, dict) else None
        frase = str((cfg or {}).get("mensagem_troca") or "").strip() if isinstance(cfg, dict) else ""
        if frase and "{{" in frase:
            try:
                from app.cerebro import catalogo
                frase = catalogo.preencher_variaveis(frase, {"nome": str(lead.get("nome") or "").split(" ")[0]})[0].strip()
            except Exception:                            # variável que não dá para trocar: fica a padrão
                frase = ""
        return frase if frase and "{{" not in frase else cdados.texto(config, "pos_assinatura")

    async def _ja_assinei_sem_documento(self, contexto: dict[str, Any]) -> dict[str, Any]:
        """"Já assinei" sem documento nosso para conferir (contrato feito fora da IA): como o n8n, desliga a IA do lead
        (etiqueta "🤖 IA Desativada" e nota DES pelo controle da IA) e pede para a equipe conferir na ZapSign."""
        from app import ia_controle
        from app.contrato import dados as cdados

        lead = await self._lead_completo(contexto["lead"]["id"])
        _, config = await self._zapsign(contexto["id_escritorio"])
        await ia_controle.mudar_ia(self._pool, contexto["id_escritorio"], ligar=False,
                                 origem="porque o lead disse que assinou e não há contrato da IA para conferir",
                                 id_lead=str(lead["id"]))
        base = f"{lead['id']}:ja_assinei_sem_contrato"
        await self._nota_unica(contexto, lead, f"{base}:nota",
                               "Lead disse que assinou o contrato, por favor verifique dentro do ZapSign se o contrato dele está assinado")
        await self._mensagem_ao_lead(contexto, lead, f"{base}:lead", cdados.texto(config, "conferir"))
        await self._registrar_evento(contexto, "ja_assinei_sem_contrato", "aviso", "cliente",
                                     "O lead disse que assinou, mas não há contrato gerado pela IA para conferir. A IA foi desligada nesse lead.")
        return {"resultado": "sem_contrato", "ia": "desligada"}

    async def _resumir_contrato(self, contexto: dict[str, Any], dados: dict[str, Any]) -> dict[str, Any]:
        """Resumo do caso quando o contrato é assinado (uma vez por contrato): lê a conversa (até 300 mensagens), pede o
        resumo à IA com o prompt do agente (ou do escritório, ou o de fábrica), conta os tokens (agentesia_chamadas_ia,
        papel contrato_resumo) e guarda no contrato. No fim, com ou sem resumo: a nota "📄 Contrato Assinado!" no
        atendimento e, com 'aviso_depois', o aviso à equipe. A IA tenta de novo uma vez; depois segue sem resumo
        (nunca trava o contrato assinado)."""
        try:
            resultado = await self._fazer_resumo(contexto, dados)
        except ErroHelenaApi:
            raise                                          # nova tentativa da IA: a nota e o aviso esperam
        except Exception as erro:                          # erro inesperado: segue sem resumo
            log.exception("falha no resumo do contrato assinado")
            resultado = {"resumo": "erro", "motivo": str(erro)[:200]}
            await self._registrar_evento(contexto, "resumo_contrato_falhou", "aviso", "lawchat",
                                         "O resumo do contrato assinado não foi feito (erro interno). O resto da assinatura seguiu normal.")
        await self._depois_do_resumo(contexto, dados)
        return resultado

    async def _depois_do_resumo(self, contexto: dict[str, Any], dados: dict[str, Any]) -> None:
        from app.contrato import resumo as cresumo

        if not contexto.get("lead"):
            return
        try:
            lead = await self._lead_completo(contexto["lead"]["id"])
            resumo = await self._pool.fetchval(
                "select resumo from agentesia_contratos where id = $1::uuid and id_escritorio = $2::uuid",
                dados["id_contrato"], contexto["id_escritorio"])
            if dados.get("chave_nota"):
                caso = dados.get("caso") or await self._nome_do_caso(lead.get("produto"), lead.get("config_agente"))
                await self._nota_unica(contexto, lead, dados["chave_nota"], cresumo.nota(resumo, caso, dados.get("avisos_nota")))
            if dados.get("aviso_depois"):
                await self._disparar(contexto, lead, ["contrato_assinado", "etapa:contrato_assinado"],
                                     f"assinado-{dados['id_contrato']}", so_avisos=True)
            elif dados.get("disparar_depois"):           # ação enfileirada antes desta versão: todas as automações
                await self._disparar(contexto, lead, ["contrato_assinado", "etapa:contrato_assinado"],
                                     f"assinado-{dados['id_contrato']}")
        except Exception:
            log.exception("falha na nota/aviso do contrato assinado depois do resumo")

    async def _fazer_resumo(self, contexto: dict[str, Any], dados: dict[str, Any]) -> dict[str, Any]:
        from app.contrato import resumo as cresumo
        from app.modelo import ErroModelo

        contrato = await self._pool.fetchrow(
            "select id, id_lead, resumo from agentesia_contratos where id = $1::uuid and id_escritorio = $2::uuid",
            dados["id_contrato"], contexto["id_escritorio"])
        if not contrato or contrato["resumo"]:
            return {"resumo": "ja_existe"}
        if self._modelo is None:
            return {"resumo": "sem_modelo_configurado"}
        if await cobranca.bloqueado(self._pool, contexto["id_escritorio"]):
            return {"resumo": cobranca.MOTIVO}             # sem saldo: segue sem resumo (a nota e o aviso saem)
        lead = await self._lead_completo(str(contrato["id_lead"]), contexto["id_escritorio"])
        _, config = await self._zapsign(contexto["id_escritorio"])
        caso = dados.get("caso") or await self._nome_do_caso(lead.get("produto"), lead.get("config_agente"))
        ajustes = cresumo.configuracao(lead.get("config_agente"), config, caso)
        if not ajustes["ativo"]:
            return {"resumo": "desligado"}
        mensagens = await self._pool.fetch(
            """select autor, coalesce(texto_extraido, texto) as texto from agentesia_mensagens
               where id_lead = $1 and coalesce(texto_extraido, texto) is not null order by enviada_em desc limit 300""", lead["id"])
        conversa = cresumo.conversa_para_resumo([dict(m) for m in reversed(mensagens)])
        if not conversa:
            return {"resumo": "sem_conversa"}

        async def gravar(chamadas: list[Any]) -> None:   # custo no consumo do escritório, por agente
            await cobranca.gravar_chamadas(self._pool, id_escritorio=contexto["id_escritorio"], chamadas=chamadas,
                                           id_lead=str(lead["id"]), id_agente=str(lead["id_agente"]) if lead.get("id_agente") else None,
                                           codigo_etapa="contrato_assinado")
        try:
            resultado = await self._modelo.gerar(
                papel=cresumo.PAPEL_IA, sistema=ajustes["prompt"], conteudo="Conversa:\n\n" + conversa,
                esquema={"type": "object", "additionalProperties": False, "properties": {"resumo": {"type": "string"}}, "required": ["resumo"]},
                modelo=ajustes["modelo"], esforco="low")
        except ErroModelo as erro:
            await gravar(getattr(erro, "chamadas", []) or [])
            tentativas = await self._pool.fetchval("select tentativas from agentesia_acoes where id = $1", dados.get("_id_acao")) or 99
            if tentativas < 2:
                raise ErroHelenaApi("indisponivel", f"IA do resumo: {erro.motivo}") from erro
            await self._registrar_evento(contexto, "resumo_contrato_falhou", "aviso", "provedor",
                                         f"O resumo do contrato assinado não foi feito (IA: {erro.motivo}). O resto da assinatura seguiu normal.")
            return {"resumo": "falhou", "motivo": str(erro.motivo)}
        await gravar(resultado.chamadas)
        tokens = {"tokens_entrada": sum(int(getattr(c, "tokens_entrada", 0) or 0) for c in resultado.chamadas),
                  "tokens_saida": sum(int(getattr(c, "tokens_saida", 0) or 0) for c in resultado.chamadas)}
        resumo = str(resultado.dados.get("resumo") or "").strip()[:cresumo.LIMITE_CARACTERES]
        if not resumo:
            return {"resumo": "vazio", **tokens}
        gravou = await self._pool.fetchval(
            "update agentesia_contratos set resumo = $2 where id = $1 and resumo is null returning id", contrato["id"], resumo)
        if not gravou:
            return {"resumo": "ja_existe"}
        if not dados.get("chave_nota") and lead.get("id_sessao_helena"):
            # Ação enfileirada antes desta versão (sem a nota única do assinado): a nota do resumo sozinha.
            await self._enfileirar(contexto, "nota", f"{contrato['id']}:resumo:nota", {"texto": cresumo.nota(resumo, caso)})
        if await self._pool.fetchval("select exists(select 1 from agentesia_crm_cards where id_lead = $1)", lead["id"]):
            await self._enfileirar(contexto, "descrever_card", f"{contrato['id']}:resumo:card", {"resumo": resumo})
        return {"resumo": "feito", "caracteres": len(resumo), "prompt": ajustes["origem"], "modelo": ajustes["modelo"], **tokens}

    async def _descrever_card(self, contexto: dict[str, Any], dados: dict[str, Any]) -> dict[str, Any]:
        """Resumo do contrato na descrição do card do lead no CRM (a descrição de sempre + o resumo)."""
        from app import automacoes
        from app.contrato import resumo as cresumo

        lead = contexto.get("lead") or {}
        card = await self._pool.fetchrow("select id_card_helena from agentesia_crm_cards where id_lead = $1", lead.get("id"))
        if not card or not card["id_card_helena"]:
            return {"card": "sem_card"}
        origem = lead.get("origem")
        origem = json.loads(origem or "{}") if isinstance(origem, str) else (origem or {})
        base = automacoes.descricao_do_card(origem, lead.get("criado_em"))
        await contexto["helena"].descrever_card(card["id_card_helena"], cresumo.descricao_do_card(base, dados["resumo"]))
        return {"card": card["id_card_helena"]}

    async def _resumir_conversa(self, contexto: dict[str, Any], dados: dict[str, Any]) -> dict[str, Any]:
        """Refaz a ficha de memória do lead com as mensagens antigas fora da janela de 40 (bloco 11 do Weaver)."""
        from app import memoria
        from app.banco.postgres import RepositorioPostgres
        from app.modelo import ErroModelo

        if self._modelo is None:
            return {"resumo": "sem_modelo_configurado"}
        if not contexto.get("lead"):
            raise ErroDeCadastro("resumo da conversa sem lead")
        async def gravar(chamadas: list[Any]) -> None:   # antes da ficha: o gasto fica gravado mesmo se a ficha falhar
            await self._gravar_chamadas(contexto, chamadas)

        try:
            resultado, _chamadas = await memoria.resumir(RepositorioPostgres(self._pool), self._modelo,
                                                         contexto["lead"]["id"], gravar_chamadas=gravar)
        except ErroModelo as erro:
            await self._gravar_chamadas(contexto, getattr(erro, "chamadas", []))
            raise ErroHelenaApi("indisponivel", f"IA do resumo da conversa: {erro.motivo}") from erro
        return resultado

    async def _classificar_origem(self, contexto: dict[str, Any], dados: dict[str, Any]) -> dict[str, Any]:
        """Qual benefício o anúncio oferece (o antigo "UTM -> PRODUTO"). Mesmo anúncio = mesma resposta, sem chamar a IA."""
        from app import origem as origens
        from app.modelo import ErroModelo

        lead = await self._lead_completo(contexto["lead"]["id"])
        origem = lead["origem"] if isinstance(lead["origem"], dict) else json.loads(lead["origem"] or "{}")
        if origem.get("produto"):
            return {"produto": origem["produto"], "motivo": "ja_classificado"}
        chave = origens.chave_do_anuncio(origem)
        anterior = await self._pool.fetchrow(
            """select origem->>'produto' as produto, (origem->>'confianca')::float8 as confianca from agentesia_leads
               where id_escritorio = $1::uuid and origem->>'chave_anuncio' = $2 and origem ? 'produto' limit 1""",
            contexto["id_escritorio"], chave) if chave else None
        if anterior:
            produto, confianca, fonte = anterior["produto"], anterior["confianca"], "mesmo_anuncio"
        elif self._modelo is None:
            return {"motivo": "sem_modelo_configurado"}
        else:
            try:
                resultado = await self._modelo.gerar(
                    papel="origem_produto", sistema=origens.PROMPT_PRODUTO, conteudo=origens.dados_para_classificar(origem),
                    esquema=origens.ESQUEMA_PRODUTO, modelo="gpt-4.1-mini", esforco="low")
            except ErroModelo as erro:
                await self._gravar_chamadas(contexto, getattr(erro, "chamadas", []))   # a tentativa que falhou também foi paga
                raise ErroHelenaApi("indisponivel", f"IA da origem: {erro.motivo}") from erro
            await self._gravar_chamadas(contexto, resultado.chamadas)
            produto = resultado.dados.get("produto") if resultado.dados.get("produto") in origens.PRODUTOS else "nao_sei"
            confianca, fonte = float(resultado.dados.get("confianca") or 0), "ia"
        await self._pool.execute(
            """update agentesia_leads set origem = origem || jsonb_build_object('produto', $2::text, 'confianca', $3::float8,
                      'chave_anuncio', $4::text) where id = $1""", lead["id"], produto, confianca, chave)
        if produto in ("nao_sei", "outro") or (confianca or 0) < 0.6:
            return {"produto": produto, "fonte": fonte, "etiqueta": False}
        config = await self._pool.fetchval("select config from agentesia_escritorios where id = $1::uuid", contexto["id_escritorio"])
        config = config if isinstance(config, dict) else json.loads(config or "{}")
        etiqueta = (config.get("etiquetas_por_produto") or {}).get(produto)
        if lead.get("id_sessao_helena"):
            await self._enfileirar(contexto, "nota", f"{lead['id']}:origem:produto:nota",
                                   {"texto": f"🏷️ Anúncio de: {origens.PRODUTOS[produto]}"})
            if etiqueta:
                await self._enfileirar(contexto, "etiquetar", f"{lead['id']}:origem:produto:etiqueta",
                                       {"adicionar": [etiqueta], "remover": []})
        return {"produto": produto, "fonte": fonte, "etiqueta": bool(etiqueta)}

    async def _gravar_chamadas(self, contexto: dict[str, Any], chamadas: list[Any]) -> None:
        await cobranca.gravar_chamadas(self._pool, id_escritorio=contexto["id_escritorio"], chamadas=chamadas,
                                       id_lead=(contexto.get("lead") or {}).get("id"))

    async def _reenviar_link(self, contexto: dict[str, Any], dados: dict[str, Any]) -> dict[str, Any]:
        """Relê o documento antes: não manda link de contrato cancelado, excluído ou vencido (nem de quem já assinou).
        Com a ZapSign fora do ar, manda o link guardado mesmo assim."""
        from app.contrato import dados as cdados

        lead = await self._lead_completo(contexto["lead"]["id"])
        _, config = await self._zapsign(contexto["id_escritorio"])
        contrato = await self._pool.fetchrow(
            "select * from agentesia_contratos where id_lead = $1 and situacao = 'gerado' order by versao desc limit 1", lead["id"])
        if not contrato or not contrato["link"]:
            if await self._pool.fetchval(
                    "select exists(select 1 from agentesia_contratos where id_lead = $1 and situacao = 'cancelado')", lead["id"]):
                await contexto["helena"].enviar_no_atendimento(lead["id_sessao_helena"], texto=cdados.texto(config, "cancelado"),
                                                               id_canal=lead["id_canal_helena"])
                return {"reenviado": False, "motivo": "contrato_encerrado"}
            return {"reenviado": False, "motivo": "sem_contrato_gerado"}
        zapsign, _ = await self._zapsign(contexto["id_escritorio"])
        para_ia: dict[str, Any] = {}
        if zapsign is not None and contrato["id_documento_externo"]:
            try:
                _, _, leitura = await self._ler_documento(zapsign, dict(contrato), lead)
            except ErroZapSign:
                leitura = None
            if leitura is not None:
                para_ia = self._leitura_para_ia(leitura, config)
                if leitura.situacao == "assinado":
                    await self._enfileirar(contexto, "verificar_assinatura", f"{lead['id']}:link-viu-assinado:{contrato['id']}",
                                           {"token_documento": contrato["id_documento_externo"], "origem": "verificacao"})
                    return {"reenviado": False, "motivo": "ja_assinou", **para_ia}
                if leitura.situacao in ("cancelado", "excluido", "expirado"):
                    await self._contrato_encerrado(contexto, lead, dict(contrato), leitura, config, chave_lead=None)
                    await contexto["helena"].enviar_no_atendimento(lead["id_sessao_helena"], texto=cdados.texto(config, "cancelado"),
                                                                   id_canal=lead["id_canal_helena"])
                    return {"reenviado": False, "motivo": leitura.situacao, **para_ia}
        await contexto["helena"].enviar_no_atendimento(lead["id_sessao_helena"], texto=cdados.texto(config, "mesmo_link", link=contrato["link"]),
                                                       id_canal=lead["id_canal_helena"])
        return {"reenviado": True, "versao": contrato["versao"], **para_ia}

    async def _lembrar_assinatura(self, contexto: dict[str, Any], dados: dict[str, Any]) -> dict[str, Any]:
        """Lembrete contextual: relê o documento; assinado -> verificação; cancelado/excluído/vencido -> encerra sem
        lembrar; abriu há menos de 1 h -> adia 1 h (uma vez); abriu e não concluiu -> texto de "travou?"."""
        from app.contrato import dados as cdados

        contrato = await self._pool.fetchrow("select * from agentesia_contratos where id = $1::uuid and id_escritorio = $2::uuid",
                                             dados["id_contrato"], contexto["id_escritorio"])
        lead = await self._lead_completo(contexto["lead"]["id"])
        if not contrato or contrato["situacao"] != "gerado" or lead.get("etapa") != "assinatura" or lead.get("estado") != "ativo":
            return {"lembrete": "nao_precisa"}
        zapsign, config = await self._zapsign(contexto["id_escritorio"])
        if zapsign is None:
            return {"lembrete": "sem_zapsign"}
        _, _, leitura = await self._ler_documento(zapsign, dict(contrato), lead)
        para_ia = self._leitura_para_ia(leitura, config)
        if leitura.situacao == "assinado":
            await self._enfileirar(contexto, "verificar_assinatura", f"{lead['id']}:lembrete-viu-assinado:{contrato['id']}",
                                   {"token_documento": contrato["id_documento_externo"], "origem": "lembrete"})
            return {"lembrete": "ja_assinou", **para_ia}
        if leitura.situacao in ("cancelado", "excluido", "expirado"):
            await self._contrato_encerrado(contexto, lead, dict(contrato), leitura, config, chave_lead=None)
            return {"lembrete": f"contrato_{leitura.situacao}", **para_ia}
        if leitura.abriu_ha_menos_de(60):
            if not dados.get("adiado"):
                await self._enfileirar(contexto, "lembrar_assinatura", f"{dados.get('_id_acao')}:lembrete-adiado",
                                       {"id_contrato": str(contrato["id"]), "adiado": True}, minutos=60)
            return {"lembrete": "adiado", "motivo": "o lead abriu o link há menos de 1 h", **para_ia}
        chave = "lembrete_abriu" if leitura.abertura == "abriu_sem_assinar" else "lembrete"
        await contexto["helena"].enviar_no_atendimento(lead["id_sessao_helena"], texto=cdados.texto(config, chave, link=contrato["link"]),
                                                       id_canal=lead["id_canal_helena"])
        return {"lembrete": "enviado", "texto": chave, **para_ia}


GASTAM_IA_SEM_ESPERA = {"resumir_conversa", "classificar_origem"}    # sem saldo: pula (feita, motivo sem_saldo)
SEM_HELENA = {"resumir_conversa", "cancelar_contrato", "guardar_pdf_assinado"}      # ações que não falam com a Helena
CONSULTA_ZAPSIGN_S = 300               # de quanto em quanto tempo o executor agenda a consulta periódica da ZapSign
_PLANOS_OK: dict[str, float] = {}      # conta ZapSign (resumo do token) -> quando o plano foi visto ok (cache de 5 min)


def _pdf_guardado(url: str | None) -> bool:
    """O arquivo_assinado já é o nosso (bucket ou /midia), não o link de 60 min da ZapSign."""
    return bool(url) and "/contratos/" in str(url) and "zapsign" not in str(url).lower()
# Ações que mandam mensagem a alguém: envio sem confirmação (timeout de leitura) não é repetido.
ENVIAM_MENSAGEM = {"enviar_mensagem", "reenviar_link", "lembrar_assinatura", "notificar", "alertar_lawchat"}


class ErroDeCadastro(Exception):
    """Falta algo no cadastro: repetir não resolve."""


DESCRICOES = {"mover_card": "mover o card do CRM", "etiquetar": "trocar as etiquetas",
              "nota": "escrever a nota no atendimento", "transferir": "transferir o atendimento",
              "preparar_aviso": "preparar o aviso à equipe", "notificar": "enviar o aviso à equipe",
              "enviar_mensagem": "enviar a mensagem ao lead", "gerar_contrato": "gerar o contrato na ZapSign",
              "verificar_assinatura": "conferir a assinatura na ZapSign", "lembrar_assinatura": "lembrar o lead de assinar",
              "reenviar_link": "reenviar o link do contrato", "resumir_contrato": "fazer o resumo do contrato assinado",
              "aviso_consumo": "avisar do consumo da IA", "alertar_lawchat": "avisar a equipe LawChat", "classificar_origem": "descobrir o benefício do anúncio",
              "resumir_conversa": "refazer a ficha de memória da conversa",
              "conferir_entrega": "conferir a entrega das mensagens da IA",
              "cancelar_contrato": "cancelar a versão antiga do contrato na ZapSign",
              "guardar_pdf_assinado": "guardar o PDF do contrato assinado",
              "descrever_card": "pôr o resumo do contrato no card do CRM"}
