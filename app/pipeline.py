"""Pipeline do atendimento: do webhook até a mensagem enviada.

1. Recepção: classifica, descarta repetido, acha ou cria o lead, grava a mensagem.
2. Espera: junta as mensagens seguidas do lead (o relógio reinicia a cada mensagem).
3. Turno: confere se a IA pode atender, chama o cérebro, confere de novo, envia e grava.

Uma resposta por vez por lead. Se chegar mensagem nova enquanto a IA pensa, a
resposta é descartada e o turno roda de novo com tudo.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from app.banco.tipos import Agente, Canal, Escritorio, Lead, Repositorio
from app.canal import filtro
from app.canal.helena import ClienteHelena, ErroHelena, Evento, ler_webhook, normalizar_telefone
from app import automacoes
from app import consumo
from app import memoria
from app import midia as midias
from app.cerebro import formatador
from app.cerebro import turno as cerebro
from app.cerebro import produto as produtos
from app.config import Configuracao
from app.modelo import ErroModelo, Modelo

log = logging.getLogger("agentesia")


def agora() -> datetime:
    return datetime.now(timezone.utc)


class Atendimento:
    def __init__(self, repo: Repositorio, modelo: Modelo, config: Configuracao,
                 helena: ClienteHelena | None = None, digitar: bool = True, visao: Any | None = None,
                 http_midia: Any | None = None, vetorizador: Any | None = None) -> None:
        self.vetorizador = vetorizador               # vetores da base de conhecimento (None = só busca por palavras)
        from app.vetores import CacheDeConsultas
        self._cache_consultas = CacheDeConsultas()           # vetores das consultas à base (LRU, 1 hora)
        self.digitar = digitar                       # pausa entre as partes, como quem digita
        self.visao = visao                           # descreve imagem e transcreve áudio (None = não faz)
        self._http_midia = http_midia                # cliente HTTP para baixar arquivos do lead
        self._midias: dict[str, set[asyncio.Task[None]]] = {}   # leituras de arquivo em andamento, por lead
        self.repo = repo
        self.modelo = modelo
        self.config = config
        self.helena = helena
        self._esperas: dict[str, asyncio.Task[None]] = {}   # uma tarefa por lead
        self._prazos: dict[str, float] = {}                  # quando a espera de cada lead vence
        self._travas: dict[str, asyncio.Lock] = {}
        self._rajada = filtro.ControleDeRajada()
        self._consumo = consumo.ControleDeConsumo()
        self._avisos_de_consumo: set[str] = set()          # faixas já avisadas neste processo
        self._descartes: dict[str, int] = {}               # turnos descartados seguidos por mensagem nova, por lead
        self._falhas_ia: dict[str, int] = {}               # falhas passageiras da IA seguidas, por lead
        self._prazos_gravados: dict[str, datetime] = {}    # último responder_apos que este processo gravou, por lead
        # Novas tentativas depois de falha passageira da IA. Com o modelo falso (testes e demonstração), a falha é
        # roteiro que acabou: não repete.
        from app.modelo import ModeloFalso
        falso = getattr(config, "modelo_falso", False) or isinstance(modelo, ModeloFalso)
        self.esperas_nova_tentativa_ia: tuple[float, ...] = () if falso else self.ESPERAS_NOVA_TENTATIVA_S

    # ------------------------------------------------------------------ recepção
    async def receber(self, corpo: dict[str, Any], id_escritorio_esperado: str | None = None) -> dict[str, Any]:
        """Trata um webhook. Rápido: o turno roda depois, em segundo plano.

        id_escritorio_esperado vem da URL do webhook de cada escritório: a conta da mensagem tem de ser dele.
        """
        evento = ler_webhook(corpo)
        if evento.classe == "rastreio" and not (evento.origem and evento.numero_lead):
            return {"feito": "ignorado", "motivo": "rastreio_sem_dados"}
        if evento.classe == "status":
            return await self._status_de_envio(evento, id_escritorio_esperado)
        if evento.classe == "ignorar":
            return {"feito": "ignorado", "motivo": evento.motivo or evento.classe}
        if motivo := filtro.antes_do_banco(evento):
            return {"feito": "ignorado", "motivo": motivo}

        escritorio = await self.repo.escritorio_por_conta(evento.id_conta or "")
        if id_escritorio_esperado and (not escritorio or escritorio.id != id_escritorio_esperado):
            log.warning("webhook do escritório %s trouxe outra conta", id_escritorio_esperado)
            return {"feito": "ignorado", "motivo": "conta_de_outro_escritorio"}
        nova = await self.repo.registrar_recebido(
            origem="helena", id_externo=evento.id_externo, tipo=evento.classe,
            payload=corpo, id_escritorio=escritorio.id if escritorio else None,
        )
        if not nova:
            return {"feito": "ignorado", "motivo": "repetido"}
        if not escritorio:
            return {"feito": "ignorado", "motivo": "conta_nao_cadastrada"}
        try:
            return await self._receber_do_escritorio(escritorio, evento)
        except Exception:
            # Banco caiu no meio (pool, timeout, reinício): desfaz a marca de recebido e devolve o erro (HTTP 500), para o
            # reenvio da Helena valer. Sem isso a mensagem do lead sumia de vez: o reenvio caía em 'repetido'.
            log.exception("falha ao receber o webhook %s; a marca de recebido foi desfeita", evento.id_externo)
            try:
                await self.repo.esquecer_recebido(origem="helena", id_externo=evento.id_externo, tipo=evento.classe)
            except Exception:
                log.exception("falha ao desfazer a marca de recebido do webhook %s", evento.id_externo)
            raise

    async def _status_de_envio(self, evento: Evento, id_escritorio_esperado: str | None) -> dict[str, Any]:
        """MESSAGE_UPDATED (e outros MESSAGE_*): só FAILED interessa. A mensagem da IA vira 'falhou', com evento
        envio_falhou e nota no chat. Idempotente pela situação (a Helena repete eventos). Entregue/lida: nada no banco."""
        conteudo = (evento.bruto or {}).get("content") or {}
        status = str(conteudo.get("status") or "").upper()
        if status != "FAILED" or not evento.id_externo:
            return {"feito": "ignorado", "motivo": evento.motivo or "status"}
        escritorio = await self.repo.escritorio_por_conta(str(conteudo.get("companyId") or ""))
        if not escritorio and id_escritorio_esperado:
            escritorio = await self.repo.escritorio(id_escritorio_esperado)
        if not escritorio or (id_escritorio_esperado and escritorio.id != id_escritorio_esperado):
            return {"feito": "ignorado", "motivo": "status_sem_escritorio"}
        motivo = str(conteudo.get("failureReason") or (conteudo.get("details") or {}).get("failureReason")
                     or "falha na entrega")[:300]
        linha = await self.repo.marcar_envio_falhou(id_escritorio=escritorio.id, id_externo=str(evento.id_externo),
                                                    erro=f"Helena: {motivo}")
        if not linha:
            return {"feito": "ignorado", "motivo": "status_ja_registrado"}
        id_lead = str(linha.get("id_lead") or "") or None
        await self.repo.gravar_eventos(id_escritorio=escritorio.id, id_lead=id_lead, id_turno=linha.get("id_turno"), eventos=[{
            "tipo": "envio_falhou", "gravidade": "erro", "responsavel": "provedor",
            "descricao": f"A Helena não entregou uma parte da resposta da IA ({motivo}).",
            "detalhe": {"id_externo": evento.id_externo, "trecho": (linha.get("texto") or linha.get("url_midia") or "")[:200]}}])
        lead = await self.repo.lead(id_lead) if id_lead else None
        if lead:
            await self._nota_de_problema(escritorio, lead, "envio_falhou", motivo, inteiro=True)
        return {"feito": "status", "motivo": "envio_falhou", "id_lead": id_lead}

    async def _receber_do_escritorio(self, escritorio: Escritorio, evento: Evento) -> dict[str, Any]:
        canal = await self.repo.canal_por_numero(escritorio.id, evento.numero_canal or "")
        if not canal:
            await self._evento(escritorio.id, None, None, "canal_nao_cadastrado", "aviso", "cadastro",
                               "Mensagem em número que não é canal cadastrado.")
            return {"feito": "ignorado", "motivo": "canal_nao_cadastrado"}
        agente = await self.repo.agente_do_canal(canal.id)
        if evento.numero_lead and not filtro.ddi_aceito(evento.numero_lead, escritorio.config,
                                                         agente.config if agente else None):
            evento.numero_lead = None                    # DDI fora da lista do escritório: não vira lead com número estranho
        if not evento.numero_lead:
            # Sem número (privacidade '@lid' ou número inválido): o lead já ligado a esta sessão segue o fluxo normal.
            lead_da_sessao = await self._lead_da_sessao(escritorio, canal, evento) \
                or await self._lead_do_contato(escritorio, canal, evento)
            if lead_da_sessao is None:
                return await self._sem_numero(escritorio, canal, agente, evento)
            lead = lead_da_sessao
            evento.numero_lead = lead.telefone           # o número que o lead já tinha (filtro, rajada e bloqueio)
        else:
            lead = await self.repo.achar_ou_criar_lead(
                escritorio=escritorio, canal=canal, agente=agente,
                telefone=evento.numero_lead, id_sessao=evento.id_sessao, nome=evento.nome_contato,
            )
        if evento.origem:
            await self._gravar_origem(escritorio, lead, evento.origem)
        if evento.classe == "rastreio":                # só a origem: quem responde é a mensagem do lead
            if agente and await self._primeiro_contato(lead) and self._vira_card(escritorio, agente, evento):
                await self._lead_novo(escritorio, agente, lead)   # card e etiqueta na chegada, sem esperar a IA
            return {"feito": "origem", "id_lead": lead.id}

        if evento.classe == "api":
            if evento.id_externo and await self.repo.mensagem_e_da_ia(escritorio.id, evento.id_externo):
                return {"feito": "ignorado", "motivo": "eco_da_ia"}
            if evento.id_externo and (ligar := getattr(self.repo, "ligar_eco_a_ia", None)) and await ligar(
                    escritorio.id, lead.id, id_externo=evento.id_externo, texto=evento.texto, url_midia=evento.url_midia,
                    minutos=self.JANELA_DO_ECO_MIN):
                # Eco de uma parte que a Helena não confirmou: a parte chegou. A linha da IA ganha o id (sem 'automacao').
                return {"feito": "ignorado", "motivo": "eco_da_ia"}
            await self._gravar(lead, evento, "automacao")
            return {"feito": "gravado", "autor": "automacao", "id_lead": lead.id}

        if evento.classe == "humano":
            return await self._fala_do_atendente(escritorio, agente, lead, evento)

        # Mensagem do lead: grava sempre; o filtro decide se a IA responde.
        id_mensagem = await self._gravar(lead, evento, "lead")
        if id_mensagem is None:
            # Reenvio da Helena depois de uma falha no meio da recepção: a mensagem já está gravada. Se ela ainda não
            # entrou num turno, a recepção segue (agenda a resposta); senão é repetido de verdade.
            existente = await self.repo.mensagem_por_id_externo(escritorio.id, evento.id_externo) \
                if evento.id_externo else None
            if existente is None or existente.autor != "lead" or existente.id_turno is not None:
                return {"feito": "ignorado", "motivo": "repetido"}
            id_mensagem = existente.id
        decisao = filtro.decidir(evento, filtro.Regras.de(escritorio.config, agente.config if agente else None),
                                 self._rajada, agora())
        espera = self._tempo_de_espera(escritorio, agente, lead, evento) if decisao.responder else 0.0
        if decisao.responder:
            # Logo depois de gravar: se o processo cair daqui em diante, retomar_pendentes ainda acha a mensagem.
            await self._marcar_resposta(lead.id, agora() + timedelta(seconds=espera))
        await self.repo.atualizar_lead(lead.id, ultima_mensagem_lead_em=evento.enviada_em)
        await self.repo.cancelar_followups(lead.id, "lead_respondeu")
        # Card e etiqueta SDR na PRIMEIRA mensagem do lead, não só na criação da linha: o lead aberto pela atendente
        # ou por API (campanha) já existe quando o contato responde. A fila é idempotente (chave {id_lead}:lead_novo).
        if agente and await self._primeiro_contato(lead, antes_de=id_mensagem) \
                and self._vira_card(escritorio, agente, evento, decisao.motivo):
            await self._lead_novo(escritorio, agente, lead)       # card e etiqueta na chegada, sem esperar a IA
        if not decisao.responder:
            if decisao.pausar_lead and lead.estado == "ativo":
                await self.repo.atualizar_lead(lead.id, estado="pausado", motivo_estado=decisao.motivo,
                                               pausado_ate=agora() + timedelta(hours=1))
            if decisao.avisar:
                await self._evento(escritorio.id, lead.id, None, decisao.motivo, "aviso", "lead", decisao.avisar)
            if decisao.motivo == "mensagem_atrasada":
                # A equipe vê no chat que o lead ficou sem resposta (1 nota a cada 6 h por conversa). Sem desculpa automática.
                await self._nota_de_problema(escritorio, lead, "mensagem_atrasada", decisao.detalhe, inteiro=True)
            return {"feito": "gravado", "motivo": decisao.motivo, "id_lead": lead.id}
        if self._precisa_ler_midia(evento):
            await self._marcar_midia_pendente(id_mensagem)
            self._ler_em_segundo_plano(id_mensagem, lead, agente, evento)
        self._agendar(lead.id, espera)
        return {"feito": "agendado", "id_lead": lead.id, "espera_s": espera}

    async def _marcar_midia_pendente(self, id_mensagem: str) -> None:
        """Marca no banco que a mídia desta mensagem está sendo lida (outro servidor ou um reinício enxergam)."""
        marcar = getattr(self.repo, "marcar_midia_pendente", None)
        if marcar is None:
            return
        try:
            await marcar(id_mensagem)
        except Exception:                                    # a marca é um extra: nunca derruba a recepção
            log.exception("falha ao marcar a leitura de mídia da mensagem %s", id_mensagem)

    # ------------------------------------------------------------------ mídia do lead
    @staticmethod
    def _detalhes_arquivo(evento: Evento) -> tuple[dict[str, Any], dict[str, Any]]:
        conteudo = (evento.bruto or {}).get("content") or {}
        detalhes = conteudo.get("details") or {}
        return detalhes, detalhes.get("file") or {}

    def _sem_transcricao(self, evento: Evento) -> bool:
        """A Helena não mandou a fala do áudio ou vídeo (ou mandou só ruído, sem fala de verdade)."""
        detalhes, _ = self._detalhes_arquivo(evento)
        return midias.fala_vazia((detalhes.get("transcription") or {}).get("text"))

    def _precisa_ler_midia(self, evento: Evento, de_quem: str = "lead") -> bool:
        """Mídia que vale baixar e ler. Do atendente só áudio, imagem e vídeo (o n8n também não lia o documento dele)."""
        if evento.tipo == "documento":
            return de_quem == "lead"
        if evento.tipo == "imagem":
            return self.visao is not None
        if evento.tipo in ("audio", "video"):
            return self.visao is not None and self._sem_transcricao(evento)
        return False

    def _ler_em_segundo_plano(self, id_mensagem: str, lead: Lead, agente: Agente | None, evento: Evento,
                              quem: str = "o lead") -> None:
        """Lê a mídia como tarefa solta; o próximo turno do lead espera por ela (_esperar_midias)."""
        tarefa = asyncio.create_task(self._ler_midia(id_mensagem, lead, agente, evento, quem=quem))
        self._midias.setdefault(lead.id, set()).add(tarefa)
        tarefa.add_done_callback(lambda t, id_lead=lead.id: self._midias.get(id_lead, set()).discard(t))

    async def _ler_midia(self, id_mensagem: str, lead: Lead, agente: Agente | None, evento: Evento,
                         quem: str = "o lead") -> None:
        """Baixa e lê o arquivo; grava o texto na própria mensagem. Nunca derruba nada.

        Do atendente ('o atendente'), uma falha não sobrescreve o marcador que o webhook já gravou."""
        import httpx

        detalhes, arquivo = self._detalhes_arquivo(evento)
        if self._http_midia is None:
            self._http_midia = httpx.AsyncClient(headers={"User-Agent": "LawChat-IA"})
        nome_modelo = ((agente.config.get("modelos") or {}).get("documento") if agente else None) or "gpt-4.1-mini"
        if (sem_saldo := getattr(self.repo, "bloqueado_por_saldo", None)) and await sem_saldo(lead.id_escritorio):
            # Sem saldo não transcreve nem descreve (custa): o turno fica em silêncio e não espera por esta leitura.
            if quem == "o lead":
                await self.repo.atualizar_texto_extraido(id_mensagem, "[arquivo não lido: o saldo da IA acabou]")
            elif limpar := getattr(self.repo, "limpar_midia_pendente", None):
                await limpar(id_mensagem)
            return
        try:
            resultado = await midias.tratar_midia(
                tipo=evento.tipo, url=evento.url_midia, mime=arquivo.get("mimeType") or arquivo.get("mimetype"),
                nome=arquivo.get("name"), legenda=evento.texto, transcricao_helena=(detalhes.get("transcription") or {}).get("text"),
                http=self._http_midia, modelo=self.modelo, nome_modelo=nome_modelo,
                descrever_imagem=getattr(self.visao, "descrever_imagem", None),
                transcrever_audio=getattr(self.visao, "transcrever_audio", None),
                ler_pdf=getattr(self.visao, "ler_pdf", None), quem=quem)
            await self.repo.gravar_chamadas(id_escritorio=lead.id_escritorio, id_turno=None, chamadas=resultado.chamadas,
                                            id_lead=lead.id)
            if quem != "o lead":
                if not resultado.erro:
                    await self.repo.atualizar_texto_extraido(id_mensagem, resultado.texto)
                return
            await self.repo.atualizar_texto_extraido(id_mensagem, resultado.texto)
            if resultado.erro and resultado.erro not in ("formato_nao_suportado", "sem_texto", "transcricao_vazia",
                                                         "sem_transcritor"):
                await self._evento(lead.id_escritorio, lead.id, None, "midia_" + resultado.erro, "aviso",
                                   "provedor" if resultado.erro in self.ERROS_DE_MIDIA_DO_PROVEDOR else "lead",
                                   f"Não foi possível ler o arquivo do lead ({resultado.erro}); a IA pediu de novo.")
        except Exception as erro:
            log.exception("falha ao ler mídia da mensagem %s", id_mensagem)
            try:
                if limpar := getattr(self.repo, "limpar_midia_pendente", None):
                    await limpar(id_mensagem)                # o turno não espera mais por esta leitura
                await self._evento(lead.id_escritorio, lead.id, None, "leitura_de_midia_falhou", "erro", "lawchat",
                                   f"Erro interno ao ler o arquivo do lead ({type(erro).__name__}): a IA respondeu sem "
                                   "conseguir ler. Confira a conversa.")
            except Exception:
                log.exception("falha ao registrar a leitura de mídia que falhou (%s)", id_mensagem)

    # Erros da leitura de mídia que são do provedor (download, link, OpenAI da visão/transcrição), não do lead.
    ERROS_DE_MIDIA_DO_PROVEDOR = ("link_expirado", "download", "visao", "transcricao", "provedor_fora_do_ar",
                                  "sem_conexao", "limite_de_uso", "chave_recusada", "sem_credito")

    async def _esperar_midias(self, id_lead: str) -> None:
        if tarefas := [t for t in self._midias.get(id_lead, set()) if not t.done()]:
            await asyncio.wait(tarefas, timeout=getattr(self.config, "espera_midia_s", 60))

    async def _gravar(self, lead: Lead, evento: Evento, autor: str) -> str | None:
        return await self.repo.gravar_mensagem(
            lead=lead, autor=autor, tipo=evento.tipo, texto=evento.texto,
            texto_extraido=evento.texto_extraido, url_midia=evento.url_midia,
            enviada_em=evento.enviada_em or agora(), id_externo=evento.id_externo,
        )

    @staticmethod
    def _pausa_por_humano(lead: Lead, agente: Agente | None) -> dict[str, Any] | None:
        """Atendente falou: a IA sai da conversa por um tempo. Cada fala reinicia a contagem. None = não mexe."""
        if lead.estado == "encerrado":
            return None
        if lead.estado == "pausado" and lead.pausado_ate is None:
            return None                              # pausa sem volta automática: só a equipe religa
        minutos = agente.minutos_pausa_humano if agente else 15
        sem_volta = bool(agente and agente.config.get("pausa_sem_volta"))   # só a equipe religa a IA
        if lead.estado == "pausado" and lead.motivo_estado == "desativada_pela_equipe" and not sem_volta \
                and lead.pausado_ate > agora() + timedelta(minutes=minutos):
            return None                              # a equipe desligou por mais tempo (2 h, 24 h): vale o prazo dela
        return {"estado": "pausado", "motivo_estado": "humano_assumiu",
                "pausado_ate": None if sem_volta else agora() + timedelta(minutes=minutos)}

    async def _fala_do_atendente(self, escritorio: Escritorio, agente: Agente | None, lead: Lead,
                                 evento: Evento) -> dict[str, Any]:
        """Grava a fala, cancela o follow-up e pausa a IA de uma vez. Se falhar, nada fica pela metade:
        evento crítico 'pausa_falhou' (vai para a central da LawChat) e o reenvio do webhook volta a valer."""
        try:
            id_mensagem = await self.repo.registrar_fala_do_atendente(
                lead=lead, tipo=evento.tipo, texto=evento.texto, texto_extraido=evento.texto_extraido,
                url_midia=evento.url_midia, enviada_em=evento.enviada_em or agora(), id_externo=evento.id_externo,
                pausa=self._pausa_por_humano(lead, agente), motivo_followup="equipe_falou")
        except Exception as erro:
            log.exception("falha ao registrar a fala do atendente no lead %s", lead.id)
            try:
                await self.repo.esquecer_recebido(origem="helena", id_externo=evento.id_externo, tipo=evento.classe)
                await self._evento(escritorio.id, lead.id, None, "pausa_falhou", "critico", "lawchat",
                                   f"O atendente falou, mas a fala não foi gravada e a IA não foi pausada "
                                   f"({type(erro).__name__}). A IA pode responder por cima; confira e pause manualmente "
                                   "(o webhook devolveu 503 para a Helena tentar de novo, se ela tentar).")
            except Exception:
                log.exception("falha ao registrar o evento pausa_falhou do lead %s", lead.id)
            return {"feito": "erro", "motivo": "pausa_falhou", "id_lead": lead.id}
        if id_mensagem and self._precisa_ler_midia(evento, de_quem="atendente"):
            # Áudio, imagem ou vídeo da equipe: lido depois da pausa, sem segurar o webhook (o n8n transcrevia o áudio e
            # descrevia a imagem). Assim a IA sabe o que a atendente disse quando a conversa voltar para ela.
            self._ler_em_segundo_plano(id_mensagem, lead, agente, evento, quem="o atendente")
        return {"feito": "pausado", "autor": "humano", "id_lead": lead.id}

    async def _lead_novo(self, escritorio: Escritorio, agente: Agente, lead: Lead) -> None:
        """Lead acabou de chegar: card na coluna SDR e etiqueta SDR já, mesmo que a IA não vá responder
        (IA pausada, fora do horário, modo teste, erro). Sem painel ou coluna: evento e nota no chat."""
        try:
            acoes, problema = automacoes.acoes_do_lead_novo(
                agente.config, await self.repo.config_crm(escritorio.id), id_lead=lead.id)
            await self.repo.enfileirar_acoes(id_escritorio=escritorio.id, id_lead=lead.id, id_turno=None, acoes=acoes)
            if problema:
                await self._evento(escritorio.id, lead.id, None, "card_nao_criado", "aviso", "cadastro",
                                   "Card do lead não foi criado no CRM: " + problema)
                await self._nota_de_problema(escritorio, lead, "card_nao_criado", problema, inteiro=True)
        except Exception:                                    # o card é um extra: nunca derruba a recepção
            log.exception("falha ao agendar o card do lead novo %s", lead.id)

    # Mensagem que o filtro barra por não ser de lead: não ganha card nem etiqueta de lead no CRM.
    NAO_E_LEAD = ("numero_bloqueado", "conversa_consigo_mesmo")

    @classmethod
    def _vira_card(cls, escritorio: Escritorio, agente: Agente, evento: Evento, motivo: str | None = None) -> bool:
        """O lead novo ganha card e etiqueta SDR? Não para número bloqueado (da equipe), para o próprio número do canal
        nem para escritório suspenso ou encerrado. `motivo` é o do filtro, quando ele já rodou (mensagem do lead)."""
        if escritorio.situacao != "ativo":
            return False
        if motivo is None:                                   # rastreio: o filtro não roda, confere o mesmo aqui
            regras = filtro.Regras.de(escritorio.config, agente.config)
            if evento.numero_lead == evento.numero_canal:
                motivo = "conversa_consigo_mesmo"
            elif evento.numero_lead in regras.numeros_bloqueados:
                motivo = "numero_bloqueado"
        return motivo not in cls.NAO_E_LEAD

    async def _primeiro_contato(self, lead: Lead, antes_de: str | None = None) -> bool:
        """É a primeira vez que o lead aparece (linha nova) ou que ele mesmo escreve (fora a mensagem `antes_de`)?"""
        if lead.novo:
            return True
        try:
            return not await self.repo.lead_ja_escreveu(lead.id, antes_de=antes_de)
        except Exception:                                    # o card é um extra: nunca derruba a recepção
            log.exception("falha ao conferir a primeira mensagem do lead %s", lead.id)
            return False

    async def _lead_da_sessao(self, escritorio: Escritorio, canal: Canal, evento: Evento) -> Lead | None:
        """Webhook sem número do contato: o lead já ligado a este atendimento da Helena, no mesmo canal.
        Vale para a mensagem do lead e a fala do atendente; API (integração ou a própria IA) não procura."""
        if evento.classe not in ("lead", "humano") or not evento.id_sessao:
            return None
        lead = await self.repo.lead_por_sessao(escritorio.id, evento.id_sessao)
        return lead if lead and lead.id_canal == canal.id else None

    async def _lead_do_contato(self, escritorio: Escritorio, canal: Canal, evento: Evento) -> Lead | None:
        """Sem número e sem lead nesta sessão (lead antigo que volta numa sessão NOVA já como '@lid'): o lead pelo id do
        contato da Helena (contactId -> agentesia_contatos.id_contato_helena) ou, de reserva, pelos dígitos do '@lid'
        (dados antigos gravaram o lead com eles). Achou: o lead passa a apontar para a sessão nova."""
        from app.canal.helena import digitos_do_lid, id_contato_do_webhook

        if evento.classe not in ("lead", "humano") or not (buscar := getattr(self.repo, "lead_do_contato", None)):
            return None
        conteudo = (evento.bruto or {}).get("content") or {}
        id_contato, digitos = id_contato_do_webhook(conteudo), digitos_do_lid(conteudo)
        if not id_contato and not digitos:
            return None
        lead = await buscar(escritorio.id, canal.id, id_contato_helena=id_contato, telefone=digitos)
        if lead and evento.id_sessao and lead.id_sessao_helena != evento.id_sessao:
            await self.repo.atualizar_lead(lead.id, id_sessao_helena=evento.id_sessao)
            lead.id_sessao_helena = evento.id_sessao
        return lead

    async def _sem_numero(self, escritorio: Escritorio, canal: Canal, agente: Agente | None,
                          evento: Evento) -> dict[str, Any]:
        """A Helena não mandou o número do contato e não há lead ligado à sessão (ver _lead_da_sessao). Lead: evento e
        nota. Atendente sem lead: ignora. API (integração ou a própria IA): ignora calado, não é problema de ninguém."""
        if evento.classe == "lead":
            await self._contato_sem_numero(escritorio, evento)
        return {"feito": "ignorado", "motivo": "contato_sem_numero"}

    async def _contato_sem_numero(self, escritorio: Escritorio, evento: Evento) -> None:
        """O WhatsApp escondeu o número do lead: não há lead. Evento e nota pela sessão do webhook."""
        await self._evento(escritorio.id, None, None, "contato_sem_numero", "aviso", "lead",
                           "A Helena não informou o contato desta conversa (privacidade de número). "
                           "O lead não foi criado e a IA não respondeu.")
        if not evento.id_sessao:
            return
        janela = int(agora().timestamp() // (6 * 3600))           # mesma trava das notas: 1 a cada 6 h por conversa
        try:
            await self.repo.enfileirar_acoes(id_escritorio=escritorio.id, id_lead=None, id_turno=None, acoes=[{
                "tipo": "nota", "chave_unica": f"sessao:{evento.id_sessao}:problema:contato_sem_numero:{janela}",
                "dados": {"texto": self.NOTAS_DE_PROBLEMA["contato_sem_numero"], "id_sessao": evento.id_sessao}}])
        except Exception:
            log.exception("falha ao agendar a nota de contato sem número")

    def _tempo_de_espera(self, escritorio: Escritorio, agente: Agente | None, lead: Lead, evento: Evento) -> float:
        if lead.telefone in self._numeros_de_teste(escritorio, agente):
            return float(escritorio.config.get("espera_teste_s", 1))
        if agente and agente.config.get("espera_s"):
            return float(agente.config["espera_s"])         # o escritório escolheu um tempo fixo de resposta
        texto = evento.texto or ""
        if not texto:
            return self.config.espera_padrao_s
        proporcional = len(texto) * self.config.segundos_por_letra
        return max(self.config.espera_minima_s, min(self.config.espera_maxima_s, proporcional))

    @staticmethod
    def _numeros_de_teste(escritorio: Escritorio, agente: Agente | None) -> set[str]:
        """Números de teste do agente e, se houver, os do escritório inteiro."""
        brutos = list(escritorio.config.get("numeros_teste", [])) + list(agente.numeros_teste if agente else [])
        return {n for n in (normalizar_telefone(x) for x in brutos) if n}

    # ------------------------------------------------------------------ espera
    def _agendar(self, id_lead: str, espera: float) -> None:
        """Mensagem nova reinicia o relógio do lead. Nunca interrompe um turno em andamento."""
        self._prazos[id_lead] = asyncio.get_running_loop().time() + espera
        tarefa = self._esperas.get(id_lead)
        if tarefa is None or tarefa.done():
            self._esperas[id_lead] = asyncio.create_task(self._esperar_e_processar(id_lead))

    async def _esperar_e_processar(self, id_lead: str) -> None:
        relogio = asyncio.get_running_loop()
        while (prazo := self._prazos.get(id_lead)) is not None:
            falta = prazo - relogio.time()
            if falta > 0:
                await asyncio.sleep(falta)           # o prazo pode ter mudado: confere de novo
                continue
            del self._prazos[id_lead]
            try:
                await self.processar(id_lead)
            except Exception:                        # nunca deixa a tarefa morrer calada
                log.exception("falha ao processar o lead %s", id_lead)
                lead = await self.repo.lead(id_lead)
                await self._evento(lead.id_escritorio if lead else None, id_lead, None, "erro_no_turno",
                                   "critico", "lawchat", "Erro inesperado ao processar o turno.")

    async def aguardar_esperas(self) -> None:
        """Só para testes: espera todos os turnos agendados terminarem."""
        while tarefas := [t for t in self._esperas.values() if not t.done()]:
            await asyncio.gather(*tarefas, return_exceptions=True)

    # ------------------------------------------------------------------ turno
    # Reserva do lead no banco enquanto o turno roda (renovada antes do envio).
    RESERVA_S = 300
    # Motivos de falha da IA que costumam passar sozinhos: o turno é refeito depois (60 s e 300 s) antes de desistir.
    FALHAS_PASSAGEIRAS = ("provedor_fora_do_ar", "sem_conexao", "limite_de_uso")
    ESPERAS_NOVA_TENTATIVA_S = (60.0, 300.0)

    def _teto_do_turno(self) -> float:
        """Tempo máximo da IA num turno (todas as chamadas). AGENTESIA_TETO_TURNO_S, padrão 180 s."""
        try:
            return max(5.0, float(os.environ.get("AGENTESIA_TETO_TURNO_S", "180")))
        except ValueError:
            return 180.0

    async def _marcar_resposta(self, id_lead: str, quando: datetime | None) -> None:
        """Grava o prazo de resposta no banco (sobrevive a um reinício) e lembra o que este processo gravou."""
        await self.repo.marcar_resposta(id_lead, quando)
        if quando is None:
            self._prazos_gravados.pop(id_lead, None)
        else:
            self._prazos_gravados[id_lead] = quando

    async def _falta_para_responder(self, id_lead: str) -> float:
        """Quanto o prazo do banco passou do que este processo gravou (0 se não passou). O banco é a verdade: a mensagem
        nova pode ter caído em outro servidor, que adiou o prazo. Sem prazo próprio (reinício), compara com agora."""
        ler = getattr(self.repo, "responder_apos", None)
        if ler is None:
            return 0.0
        try:
            quando = await ler(id_lead)
        except Exception:                                    # sem o prazo do banco, segue com o do processo
            log.exception("falha ao ler o prazo de resposta do lead %s", id_lead)
            return 0.0
        if not quando:
            return 0.0
        meu = self._prazos_gravados.get(id_lead)
        falta = (quando - meu).total_seconds() if meu is not None else (quando - agora()).total_seconds()
        if falta > 1:
            self._prazos_gravados[id_lead] = quando          # o novo prazo passa a ser o deste processo também
        return max(0.0, falta)

    async def processar(self, id_lead: str, modo: str | None = None) -> cerebro.Saida | None:
        """Roda o turno do lead. Devolve a saída do cérebro, ou None se a IA não atendeu.

        Reserva o lead no banco antes: com dois servidores, só um responde; o outro tenta de novo em 15 s."""
        trava = self._travas.setdefault(id_lead, asyncio.Lock())
        async with trava:
            if modo != "laboratorio":
                if not await self.repo.reservar_lead(id_lead, self.RESERVA_S):
                    self._agendar(id_lead, 15)
                    return None
                if (falta := await self._falta_para_responder(id_lead)) > 1:
                    # O lead ainda está escrevendo (a mensagem nova pode ter chegado por outro servidor): espera o prazo.
                    await self.repo.liberar_lead(id_lead)
                    self._agendar(id_lead, falta)
                    return None
            saida: cerebro.Saida | None = None
            try:
                for tentativa in range(self.config.max_reprocessos + 1):
                    pode_descartar = tentativa < self.config.max_reprocessos \
                        and self._descartes.get(id_lead, 0) < self.config.max_reprocessos
                    saida, repetir = await self._um_turno(id_lead, modo, pode_descartar=pode_descartar)
                    if not repetir:
                        break
                    if modo != "laboratorio" and (falta := await self._falta_para_responder(id_lead)) > 1:
                        self._agendar(id_lead, falta)        # mensagem nova de outro servidor: responde no prazo dela
                        break
            finally:
                if modo != "laboratorio":
                    await self.repo.liberar_lead(id_lead)
                    if not await self.repo.mensagens_pendentes(id_lead) and id_lead not in self._prazos:
                        await self._marcar_resposta(id_lead, None)
            return saida

    async def retomar_pendentes(self) -> int:
        """Depois de um reinício (e a cada minuto): agenda de novo as respostas que ficaram esperando no banco e fecha os
        turnos que ficaram 'processando' (processo caiu no meio do envio), com evento e nota para a equipe."""
        await self._fechar_turnos_interrompidos()
        if religar := getattr(self.repo, "religar_pausas_vencidas", None):
            try:                                         # desativação com prazo que acabou: a IA volta sozinha
                await religar()
            except Exception:
                log.exception("falha ao religar as desativações vencidas")
        retomados = 0
        for id_lead, quando in await self.repo.leads_aguardando():
            tarefa = self._esperas.get(id_lead)
            if id_lead in self._prazos or (tarefa is not None and not tarefa.done()):
                continue
            if (quando - agora()).total_seconds() > 60:
                # Prazo longe (IA desligada até 14:30): entra numa das próximas voltas. Sem dormir horas em memória,
                # religar antes pelo painel (que adianta o prazo no banco) é atendido na volta seguinte.
                continue
            self._agendar(id_lead, max(0.0, (quando - agora()).total_seconds()))
            retomados += 1
        return retomados

    TURNO_INTERROMPIDO_MIN = 10

    async def _fechar_turnos_interrompidos(self) -> None:
        fechar = getattr(self.repo, "fechar_turnos_interrompidos", None)
        if fechar is None:
            return
        try:
            interrompidos = await fechar(self.TURNO_INTERROMPIDO_MIN)
        except Exception:
            log.exception("falha ao fechar turnos interrompidos")
            return
        for item in interrompidos:                   # o update com returning garante: só um servidor avisa
            try:
                await self._evento(item["id_escritorio"], item["id_lead"], item["id_turno"], "turno_interrompido", "erro",
                                   "lawchat", "O turno da IA foi interrompido no meio (reinício ou queda do servidor): "
                                              "a resposta pode ter saído pela metade. Confira a conversa.")
                lead = await self.repo.lead(item["id_lead"])
                escritorio = await self.repo.escritorio(item["id_escritorio"]) if lead else None
                if lead and escritorio:
                    await self._nota_de_problema(escritorio, lead, "envio_falhou", "turno_interrompido")
            except Exception:
                log.exception("falha ao avisar o turno interrompido %s", item.get("id_turno"))

    async def encerrar(self, teto_s: float = 30.0) -> None:
        """Desligamento: espera os turnos e leituras de mídia em andamento terminarem (até `teto_s`) e cancela o resto.
        O que for cortado vira 'turno_interrompido' na varredura do próximo servidor."""
        vivas = [t for t in self._esperas.values() if not t.done()]
        vivas += [t for tarefas in self._midias.values() for t in tarefas if not t.done()]
        if not vivas:
            return
        feitas, restantes = await asyncio.wait(vivas, timeout=teto_s)
        for tarefa in restantes:
            tarefa.cancel()
        if restantes:
            await asyncio.gather(*restantes, return_exceptions=True)
            log.warning("desligamento: %d tarefa(s) de atendimento cortadas no meio", len(restantes))

    # ------------------------------------------------------------------ mídia pendente (banco)
    MIDIA_RECENTE_S = 60.0                            # marca mais nova que isto: outro servidor pode estar lendo

    async def _adiar_pela_midia(self, lead: Lead, agente: Agente | None, pendentes: list[Any]) -> bool:
        """Mensagem do lead com leitura de mídia pendente no banco. Sem tarefa local (reinício): lê aqui mesmo, com
        teto. Marca recente sem tarefa local (outro servidor lendo): adia 10 s. Ainda pendente e dentro do teto
        (3 x espera_midia_s): adia 15 s em vez de responder com o marcador. Passou do teto: segue com o provisório."""
        marcadas = [m for m in pendentes if getattr(m, "midia_pendente_desde", None)]
        if not marcadas:
            return False
        espera = float(getattr(self.config, "espera_midia_s", 60))
        locais = any(not t.done() for t in self._midias.get(lead.id, set()))
        for m in marcadas:
            idade = (datetime.now(timezone.utc) - m.midia_pendente_desde).total_seconds()
            if locais:
                continue
            if idade < self.MIDIA_RECENTE_S:
                self._agendar(lead.id, 10)
                return True
            if idade < 3 * espera:
                evento = Evento("lead", id_externo=m.id_externo, tipo=m.tipo, texto=m.texto, texto_extraido=m.texto_extraido,
                                url_midia=getattr(m, "url_midia", None), bruto=None)
                try:
                    await asyncio.wait_for(self._ler_midia(m.id, lead, agente, evento), timeout=espera)
                except asyncio.TimeoutError:
                    log.warning("leitura de mídia refeita no turno passou de %.0f s (mensagem %s)", espera, m.id)
        pendentes_agora = await self.repo.mensagens_pendentes(lead.id)
        ainda = [m for m in pendentes_agora if getattr(m, "midia_pendente_desde", None)]
        if not ainda:
            return False
        if all((datetime.now(timezone.utc) - m.midia_pendente_desde).total_seconds() >= 3 * espera for m in ainda):
            limpar = getattr(self.repo, "limpar_midia_pendente", None)
            for m in ainda:
                if limpar:
                    await limpar(m.id)                   # passou do teto: o turno segue com o texto provisório
            return False
        self._agendar(lead.id, 15)
        return True

    async def _reparar_etapa(self, lead: Lead, agente: Agente | None) -> Lead:
        """Lead criado quando o canal ainda não tinha agente (ou com etapa que não é do agente do canal): passa para o
        agente do canal, na etapa principal. Sem isso ficava em 'agente_sem_etapa' para sempre."""
        if agente is None or (lead.id_agente == agente.id and lead.id_etapa is not None):
            return lead                              # etapa de fora da lista (ex.: terminal) não é reparada aqui
        principal = agente.principal()
        if principal is None:
            return lead
        try:
            await self.repo.atualizar_lead(lead.id, id_agente=agente.id, id_etapa=principal.id)
            await self._evento(lead.id_escritorio, lead.id, None, "etapa_reparada", "info", "lawchat",
                               f"O lead estava sem agente ou com etapa de outro agente: foi para a etapa "
                               f"{principal.codigo} do agente {agente.nome}.")
        except Exception:
            log.exception("falha ao reparar a etapa do lead %s", lead.id)
            return lead
        lead.id_agente, lead.id_etapa = agente.id, principal.id
        return lead

    # ------------------------------------------------------------------ turno
    async def _um_turno(self, id_lead: str, modo: str | None, pode_descartar: bool) -> tuple[cerebro.Saida | None, bool]:
        await self._esperar_midias(id_lead)          # arquivo do lead lido antes de a IA responder
        lead = await self.repo.lead(id_lead)
        if not lead:
            return None, False
        pendentes = await self.repo.mensagens_pendentes(id_lead)
        if not pendentes:
            return None, False
        escritorio = await self.repo.escritorio(lead.id_escritorio)
        agente = await self.repo.agente_do_canal(lead.id_canal)
        assert escritorio is not None
        if modo != "laboratorio":
            if await self._adiar_pela_midia(lead, agente, pendentes):
                return None, False
            pendentes = await self.repo.mensagens_pendentes(id_lead) or pendentes   # textos lidos agora
            lead = await self._reparar_etapa(lead, agente)

        lead = await self._religar_se_venceu(lead)
        if modo != "laboratorio" and lead.estado == "pausado" and lead.motivo_estado == "desativada_pela_equipe" \
                and lead.pausado_ate:
            # IA desligada pela equipe até um horário: a mensagem fica guardada e a IA responde quando o prazo acabar
            # (retomar_pendentes religa e agenda). Responder agora passaria por cima da equipe.
            await self._marcar_resposta(id_lead, lead.pausado_ate)
            return None, False
        etapa = agente.etapa_por_id(lead.id_etapa) if agente else None
        modo = modo or (agente.modo if agente else "teste")
        fora_do_horario = None
        if modo == "producao":
            from app import horario
            fora_do_horario, abre_em = horario.decidir(escritorio.config)
            if fora_do_horario == "fora_do_horario" and abre_em \
                    and await self._janela_fecha_antes(lead, pendentes, abre_em):
                # Número oficial: depois de 24 h da última mensagem do lead, só modelo aprovado. Segurar a resposta
                # até segunda-feira faria a Helena aceitar e a Meta recusar, sem ninguém saber. Silêncio com nota.
                fora_do_horario = "janela_fechada"
            if fora_do_horario == "fora_do_horario" and abre_em:
                # Segura a mensagem: a resposta fica marcada no banco para a hora em que o escritório abre.
                await self._marcar_resposta(id_lead, abre_em)
                self._agendar(id_lead, max(1.0, (abre_em - agora()).total_seconds()))
                return None, False
        if modo != "laboratorio" and lead.estado == "ativo" and not fora_do_horario \
                and await self._equipe_falou_por_ultimo(id_lead, pendentes):
            fora_do_horario = "equipe_respondeu"     # guardadas na desativação e já respondidas pela equipe: silêncio
        id_turno = await self.repo.abrir_turno(lead=lead, modo=modo, etapa_antes=etapa.codigo if etapa else None)
        ids_lote = [m.id for m in pendentes]
        try:
            return await self._turno_aberto(escritorio, agente, lead, etapa, modo, fora_do_horario, pendentes, ids_lote,
                                            id_turno, pode_descartar)
        except Exception as erro:
            # Erro inesperado (dado ruim, bug, banco): o turno fecha como 'erro', as mensagens saem da fila (sem laço a
            # cada minuto pagando IA) e a equipe recebe evento e nota para responder manualmente.
            await self._turno_quebrou(escritorio, lead, id_turno, ids_lote, erro)
            if modo == "laboratorio":
                raise
            return None, False

    async def _turno_quebrou(self, escritorio: Escritorio, lead: Lead, id_turno: str, ids_lote: list[str],
                             erro: Exception) -> None:
        log.error("erro inesperado no turno %s do lead %s", id_turno, lead.id, exc_info=erro)
        nome = type(erro).__name__
        try:
            if chamadas := list(getattr(erro, "chamadas", None) or []):
                await self.repo.gravar_chamadas(id_escritorio=escritorio.id, id_turno=id_turno, chamadas=chamadas)
                self._consumo.somar(escritorio.id, sum(c.custo_usd or 0 for c in chamadas))
        except Exception:
            log.exception("falha ao gravar as chamadas do turno quebrado %s", id_turno)
        try:
            await self.repo.marcar_no_turno(ids_lote, id_turno)
            await self.repo.fechar_turno(id_turno, situacao="erro", motivo=f"erro_interno:{nome}", etapa_depois=None,
                                         contexto=None, resposta=None)
            await self._evento(escritorio.id, lead.id, id_turno, "erro_no_turno", "critico", "lawchat",
                               f"Erro inesperado no turno da IA ({nome}). O lead ficou sem resposta.")
            await self._nota_de_problema(escritorio, lead, "ia_nao_respondeu", f"erro interno: {nome}", inteiro=True)
        except Exception:
            log.exception("falha ao fechar o turno quebrado %s", id_turno)
        self._descartes.pop(lead.id, None)
        self._falhas_ia.pop(lead.id, None)

    async def _turno_aberto(self, escritorio: Escritorio, agente: Agente | None, lead: Lead, etapa: Any, modo: str,
                            fora_do_horario: str | None, pendentes: list[Any], ids_lote: list[str], id_turno: str,
                            pode_descartar: bool) -> tuple[cerebro.Saida | None, bool]:
        id_lead = lead.id
        # Primeira conferência: a IA pode atender este lead?
        motivo = self._por_que_nao_atende(escritorio, agente, lead, etapa, modo) or fora_do_horario
        if not motivo:                               # vale também no modo teste: teste também gasta
            motivo = await self._conferir_consumo(escritorio)
        if motivo:
            await self.repo.marcar_no_turno(ids_lote, id_turno)
            await self.repo.fechar_turno(id_turno, situacao="silencio", motivo=motivo,
                                         etapa_depois=etapa.codigo if etapa else None, contexto=None, resposta=None)
            self._descartes.pop(id_lead, None)
            if registro := self.SEM_ATENDIMENTO.get(motivo):
                # A IA não atende, mas registra assim mesmo: evento na central e nota no chat (quando há modelo).
                gravidade, responsavel, descricao = registro
                await self._evento(escritorio.id, lead.id, id_turno, motivo, gravidade, responsavel,
                                   descricao.format(etapa=etapa.codigo if etapa else "-"))
                await self._nota_de_problema(escritorio, lead, motivo, motivo)
            return None, False
        assert agente is not None and etapa is not None

        entrada = await self._montar_entrada(escritorio, agente, lead, etapa.codigo, pendentes)
        try:
            saida = await asyncio.wait_for(cerebro.processar(self.modelo, entrada), timeout=self._teto_do_turno())
        except asyncio.TimeoutError:
            # A IA pendurou (conexão lenta): falha do modelo, pelo mesmo caminho das outras (evento e nota).
            saida = cerebro._falha(cerebro.Saida(etapa_antes=entrada.etapa, etapa_depois=entrada.etapa,
                                                 fatos_depois=dict(entrada.fatos)),
                                   "turno", ErroModelo("sem_conexao", f"a IA passou de {self._teto_do_turno():.0f} s"))
        await self._depois_da_busca(agente, entrada, saida)     # custo do embedding da consulta entra no consumo
        self._classificar_falha_da_ia(saida)
        if saida.situacao == "respondido" and not saida.mensagens and not saida.estado_lead:
            saida.eventos.append({"tipo": "resposta_vazia", "gravidade": "erro", "responsavel": "lawchat",
                                  "descricao": "A IA devolveu uma resposta vazia.", "detalhe": {}})
        await self.repo.gravar_chamadas(id_escritorio=escritorio.id, id_turno=id_turno, chamadas=saida.chamadas)
        self._consumo.somar(escritorio.id, sum(c.custo_usd or 0 for c in saida.chamadas))

        if await self._tentar_de_novo_depois(escritorio, lead, id_turno, saida, modo):
            return None, False

        # Segunda conferência, antes de enviar: chegou mensagem nova? o atendente assumiu? a etapa mudou?
        agora_pendentes = await self.repo.mensagens_pendentes(id_lead)
        lead_agora = await self.repo.lead(id_lead)
        if lead_agora and lead_agora.estado != "ativo":
            await self.repo.marcar_no_turno(ids_lote, id_turno)
            await self._fechar(id_turno, saida, "descartado", "estado_mudou:" + (lead_agora.motivo_estado or lead_agora.estado))
            return None, False
        if lead_agora and lead_agora.id_etapa != lead.id_etapa:
            # Outro processo (contrato gerado, troca pela fila) mudou a etapa enquanto a IA pensava: a resposta foi
            # pensada pelo agente da etapa antiga. O próximo turno relê a etapa.
            if not pode_descartar:
                await self.repo.marcar_no_turno(ids_lote, id_turno)
            await self._fechar(id_turno, saida, "descartado", "etapa_mudou")
            return None, pode_descartar
        if pode_descartar and len(agora_pendentes) > len(pendentes):
            await self._fechar(id_turno, saida, "descartado", "chegou_mensagem_nova")
            self._descartes[id_lead] = self._descartes.get(id_lead, 0) + 1
            # Quem responde é a espera da mensagem nova (o lead ainda pode estar digitando). Só repete aqui quando a
            # mensagem nova caiu em outro servidor (sem prazo neste processo).
            return None, id_lead not in self._prazos

        # Grava o que o turno decidiu e envia.
        self._descartes.pop(id_lead, None)
        self._falhas_ia.pop(id_lead, None)
        await self.repo.marcar_no_turno(ids_lote, id_turno)
        if saida.fatos_novos:
            await self.repo.gravar_fatos(lead=lead, id_turno=id_turno, fatos=saida.fatos_novos)
        campos: dict[str, Any] = {}
        nova_etapa = agente.etapa(saida.etapa_depois)
        if saida.etapa_depois != saida.etapa_antes:
            if nova_etapa:
                campos["id_etapa"] = nova_etapa.id
            else:
                saida.eventos.append({"tipo": "etapa_nao_cadastrada", "gravidade": "erro", "responsavel": "cadastro",
                                      "descricao": f"O agente não tem a etapa {saida.etapa_depois}.", "detalhe": {}})
        if "id_etapa" in campos:
            # A troca de etapa é gravada antes do envio: um reinício no meio do envio não volta o lead para a etapa antiga.
            await self.repo.atualizar_lead(lead.id, id_etapa=campos.pop("id_etapa"))
            trocou_etapa = True
        else:
            trocou_etapa = False
        if saida.estado_lead:
            campos.update(estado=saida.estado_lead, motivo_estado=saida.motivo_estado, pausado_ate=None)

        if saida.mensagens:
            # Teto de balões por turno (agente.config["max_baloes"], padrão 5): 9 balões de até 8 s parecem robô.
            saida.mensagens = formatador.juntar_excedente(
                saida.mensagens, teto=int(agente.config.get("max_baloes") or formatador.TETO_DE_BALOES))
            if modo != "laboratorio" and (renovar := getattr(self.repo, "renovar_reserva", None)):
                try:
                    await renovar(id_lead, self.RESERVA_S)   # o envio (pausas de digitação) não deixa a reserva vencer
                except Exception:
                    log.exception("falha ao renovar a reserva do lead %s", id_lead)
            completo, entregues = await self._enviar(escritorio, agente, lead, id_turno, saida, modo)
            if entregues:
                campos["ultima_resposta_ia_em"] = agora()
            elif trocou_etapa:
                # Nada chegou ao lead (Helena fora, sem token): ele não ouviu a frase de troca. Fica na etapa antiga.
                await self.repo.atualizar_lead(lead.id, id_etapa=lead.id_etapa)
                saida.eventos.append({"tipo": "troca_sem_entrega", "gravidade": "aviso", "responsavel": "provedor",
                                      "descricao": f"A IA ia trocar a etapa ({saida.etapa_antes} → {saida.etapa_depois}), "
                                                   "mas nenhuma parte da resposta foi entregue: o lead ficou na etapa "
                                                   f"{saida.etapa_antes}.", "detalhe": {}})
                saida.etapa_depois = saida.etapa_antes
                trocou_etapa = False
            if not completo:
                # O atendente assumiu no meio do envio: a pausa dele vale (o estado da saída não passa por cima dela).
                for chave in ("estado", "motivo_estado", "pausado_ate"):
                    campos.pop(chave, None)
        if campos:
            await self.repo.atualizar_lead(lead.id, **campos)
        if trocou_etapa:
            # Histórico de trocas de etapa (quem trocou, de onde para onde e por quê), na central de eventos.
            catalogo_ctx = saida.contexto.get("catalogo") or {}
            saida.eventos.append({"tipo": "etapa_trocada", "gravidade": "info", "responsavel": "lawchat",
                                  "descricao": f"Etapa do lead: {saida.etapa_antes} → {saida.etapa_depois}.",
                                  "detalhe": {"de": saida.etapa_antes, "para": saida.etapa_depois,
                                              "origem": catalogo_ctx.get("origem_destino") or "ia",
                                              "id_turno": id_turno, "motivo": saida.motivo}})
        # Depois do envio: cada passo isolado (um que falha não impede os outros nem o fechamento do turno).
        await self._passo_seguro("contrato", self._acoes_do_contrato(escritorio, agente, lead, id_turno, saida, modo),
                                 escritorio, lead, id_turno)
        await self._passo_seguro("automacoes", self._automacoes(escritorio, agente, lead, id_turno, entrada, saida, modo),
                                 escritorio, lead, id_turno)
        if saida.mensagens and modo != "laboratorio":
            # O relógio do follow-up começa na última resposta da IA.
            await self._passo_seguro("followup", self.repo.agendar_followup(lead.id, agora()), escritorio, lead, id_turno)
            # 20+ mensagens antigas fora da janela sem resumo: refaz a ficha pela fila (não atrasa nem derruba nada).
            await self._passo_seguro("resumo", memoria.pedir_resumo_se_preciso(
                self.repo, id_escritorio=escritorio.id, id_lead=lead.id, id_turno=id_turno, comeco=entrada.comeco_conversa),
                escritorio, lead, id_turno)
        await self._passo_seguro("lacuna", self._registrar_lacuna(escritorio, agente, lead, id_turno, saida),
                                 escritorio, lead, id_turno)
        await self._passo_seguro("eventos", self.repo.gravar_eventos(
            id_escritorio=escritorio.id, id_lead=lead.id, id_turno=id_turno, eventos=saida.eventos), escritorio, lead, id_turno)
        for evento in saida.eventos:
            if self._automacao_ja_anota(agente, evento["tipo"], saida.etapa_depois):
                continue                                 # a nota configurada pelo escritório já vai: sem nota dobrada
            await self._nota_de_problema(escritorio, lead, evento["tipo"], evento.get("descricao") or "")
        await self._fechar(id_turno, saida, saida.situacao, saida.motivo)
        return saida, False

    async def _passo_seguro(self, nome: str, passo: Any, escritorio: Escritorio, lead: Lead, id_turno: str) -> None:
        """Roda um passo depois do envio sem deixar a falha dele derrubar o resto do turno."""
        try:
            await passo
        except Exception as erro:
            log.exception("falha no passo %s do turno %s", nome, id_turno)
            try:
                await self._evento(escritorio.id, lead.id, id_turno, "pos_envio_falhou:" + nome, "erro", "lawchat",
                                   f"A resposta saiu, mas o passo '{nome}' falhou ({type(erro).__name__}).")
            except Exception:
                log.exception("falha ao registrar o passo %s que falhou", nome)

    async def _tentar_de_novo_depois(self, escritorio: Escritorio, lead: Lead, id_turno: str, saida: cerebro.Saida,
                                     modo: str) -> bool:
        """IA fora do ar, sem conexão ou no limite de uso: em vez de deixar o lead sem resposta para sempre, fecha o turno
        como 'erro' sem tirar as mensagens da fila e tenta de novo em 60 s e depois em 300 s. Na 3ª falha segue o
        caminho normal (evento e nota 'responda manualmente')."""
        if modo == "laboratorio" or saida.situacao != "erro":
            return False
        if saida.motivo.partition(":")[2] not in self.FALHAS_PASSAGEIRAS:
            return False
        vezes = self._falhas_ia.get(lead.id, 0)
        if vezes >= len(self.esperas_nova_tentativa_ia):
            self._falhas_ia.pop(lead.id, None)
            return False
        espera = self.esperas_nova_tentativa_ia[vezes]
        self._falhas_ia[lead.id] = vezes + 1
        await self._fechar(id_turno, saida, "erro", saida.motivo + ":nova_tentativa")
        await self._marcar_resposta(lead.id, agora() + timedelta(seconds=espera))
        self._agendar(lead.id, espera)
        return True

    # Evento do turno -> gatilhos de automação que já deixam nota no chat quando o escritório os configurou.
    @staticmethod
    def _automacao_ja_anota(agente: Agente, tipo: str, etapa: str | None = None) -> bool:
        if not (agente.config.get("funcoes") or {}).get("avisos"):
            return False                                 # sem a função de avisos a nota da automação não sai
        regras = agente.config.get("automacoes") or {}
        if tipo.startswith("sinal_") and tipo != "sinal_recusado":
            gatilhos = ["sinal:" + tipo.removeprefix("sinal_"), "sinal"]
        else:
            gatilhos = {"pediu_humano": ["pediu_humano"], "trava_persistente": ["trava"],
                        "analise_manual": [f"etapa:{etapa}" if etapa else "etapa:analise_manual"]}.get(tipo, [])
        return any((regras.get(g) or {}).get("nota") for g in gatilhos)

    async def _automacoes(self, escritorio: Escritorio, agente: Agente, lead: Lead, id_turno: str,
                          entrada: cerebro.Entrada, saida: cerebro.Saida, modo: str) -> None:
        """Quando isto acontecer, faça aquilo: põe na fila as ações configuradas no agente (CRM, nota...).

        Os "Avisos à equipe" (sinal de videochamada, não sabe ler...) valem mesmo sem automação nenhuma no agente:
        basta a função de avisos ligada. Cada gatilho gera no máximo um aviso por turno (montar_acoes)."""
        if modo == "laboratorio":
            return
        if not agente.config.get("automacoes") and not (agente.config.get("funcoes") or {}).get("avisos"):
            return
        gatilhos = automacoes.gatilhos_do_turno(
            primeira_resposta=not any(m["autor"] == "você" for m in entrada.historico),
            etapa_antes=saida.etapa_antes, etapa_depois=saida.etapa_depois,
            motivo_estado=saida.motivo_estado, situacao=saida.situacao, sinais=saida.sinais,
            intencoes=saida.intencoes,
        )
        if not gatilhos:
            return
        acoes = automacoes.montar_acoes(
            agente.config, await self.repo.config_crm(escritorio.id), gatilhos,
            id_lead=lead.id, id_turno=id_turno, contexto=f"Motivo: {saida.motivo}" if saida.motivo else "",
            avisos=await self.repo.eventos_com_aviso(escritorio.id),
        )
        await self.repo.enfileirar_acoes(id_escritorio=escritorio.id, id_lead=lead.id, id_turno=id_turno, acoes=acoes)
        saida.contexto["automacoes"] = {"gatilhos": gatilhos, "acoes": [a["tipo"] for a in acoes]}

    async def _acoes_do_contrato(self, escritorio: Escritorio, agente: Agente, lead: Lead, id_turno: str,
                                 saida: cerebro.Saida, modo: str) -> None:
        """Lead confirmou os dados: gera o contrato. Lead disse que assinou: confere na ZapSign. Tudo pela fila."""
        if modo == "laboratorio" or not (agente.config.get("funcoes") or {}).get("contrato_zapsign"):
            return
        from app.contrato import dados as cdados

        acoes: list[dict[str, Any]] = []
        if saida.motivo == "dados_confirmados":
            # Mesmos campos obrigatórios que a ação gerar_contrato usa: com o padrão, um modelo que exige e-mail
            # enfileirava sempre a mesma chave (descartada) e o lead sem e-mail nunca recebia link nem ia à equipe.
            dados, erros = cdados.validar_dados(cdados.dados_dos_fatos(saida.fatos_depois), lead.telefone,
                                                await self._obrigatorios_do_contrato(escritorio, agente))
            if not erros:
                hash_dados = cdados.hash_dados(dados)
                acoes.append({"tipo": "gerar_contrato", "chave_unica": f"{lead.id}:contrato:{hash_dados}",
                              "dados": {"dados": dados, "hash": hash_dados}})
            else:
                # Dado faltando ou inválido para o modelo do agente: pede a correção ao lead (qualquer produto; no clássico
                # nada ia para a fila e o lead ficava mudo, sem link e sem equipe).
                acoes.append({"tipo": "enviar_mensagem", "chave_unica": f"{lead.id}:{id_turno}:corrigir",
                              "dados": {"texto": cdados.pedir_correcao(erros)}})
                if agente.produto != "catalogo" and lead.id_sessao_helena:
                    # No clássico a equipe também fica sabendo, como fazia a ação gerar_contrato (uma nota só).
                    acoes.append({"tipo": "nota", "chave_unica": f"{lead.id}:contrato:nota_corrigir",
                                  "dados": {"texto": "A IA não gerou o contrato porque dados não conferem ("
                                                     + ", ".join(e.campo for e in erros) + "). Ela pediu a correção ao lead."}})
        if saida.intencoes.get("pediu_link") and saida.etapa_depois == "assinatura":
            acoes.append({"tipo": "reenviar_link", "chave_unica": f"{lead.id}:{id_turno}:link", "dados": {}})
        if saida.motivo == "diz_que_assinou":
            acoes.append({"tipo": "verificar_assinatura", "chave_unica": f"{lead.id}:{id_turno}:verificar",
                          "dados": {"origem": "verificacao"}})
        if acoes:
            await self.repo.enfileirar_acoes(id_escritorio=escritorio.id, id_lead=lead.id, id_turno=id_turno, acoes=acoes)
            saida.contexto["contrato"] = [a["tipo"] for a in acoes]

    async def _obrigatorios_do_contrato(self, escritorio: Escritorio, agente: Agente) -> tuple[str, ...]:
        """Campos obrigatórios do modelo de contrato do agente (o mesmo que a ação gerar_contrato escolhe), ou o padrão."""
        from app.acoes import Executor
        from app.contrato import dados as cdados

        modelo = Executor._modelo_do_contrato(await self.repo.config_zapsign(escritorio.id), str(agente.id or ""))
        return tuple((modelo or {}).get("obrigatorios") or cdados.OBRIGATORIOS_PADRAO)

    @staticmethod
    async def _enriquecer_por_cep(fatos: dict[str, Any]) -> list[dict[str, Any]]:
        """Lead passou o CEP e ainda falta endereço: completa rua, bairro, cidade e UF pelo CEP (antigo fluxo BUSCAR CEP)."""
        from app.contrato.dados import normalizar_uf
        from app.ferramentas import cep as ferramenta_cep

        def vazio(chave: str) -> bool:
            # UF que não é sigla nem nome de estado ("XX", texto solto) conta como vazia: o CEP corrige.
            # A cidade NÃO é trocada pela do CEP quando diverge: seria apagar a correção do lead (CEP geral, distrito).
            return not fatos.get(chave) or (chave == "uf" and not normalizar_uf(fatos.get(chave)))

        if not fatos.get("cep") or not any(vazio(k) for k in ("endereco", "bairro", "cidade", "uf")):
            return []
        endereco = await ferramenta_cep.consultar(fatos["cep"])
        # Situação da busca para o turno (não vira fato): sem ela a IA dizia "buscamos nos Correios" sem busca nenhuma.
        situacao = {"chave": "_busca_cep", "valor": {"cep": endereco.cep, "encontrado": bool(endereco.valido),
                                                     "mensagem": endereco.mensagem, "tipo": endereco.tipo,
                                                     "falhou": bool(getattr(endereco, "falhou", False)),
                                                     "cidade": endereco.cidade, "uf": endereco.uf}, "fonte": "sistema"}
        if not endereco.valido:
            if endereco.tipo == "geral":
                # CEP geral da cidade: não tem rua, mas a cidade e a UF valem (só onde o lead não disse outra coisa).
                trecho = f"(pelo CEP geral {endereco.cep}, fonte {endereco.origem})"
                novos = {"cidade": endereco.cidade, "uf": endereco.uf}
                return [{"chave": k, "valor": v, "trecho": trecho, "fonte": "sistema"}
                        for k, v in novos.items() if v and vazio(k)] + [situacao]
            return [situacao]
        trecho = f"(pelo CEP {endereco.cep}, fonte {endereco.origem})"
        novos = {"endereco": endereco.logradouro, "bairro": endereco.bairro, "cidade": endereco.cidade, "uf": endereco.uf}
        return [{"chave": k, "valor": v, "trecho": trecho, "fonte": "sistema"} for k, v in novos.items() if v and vazio(k)] + [situacao]

    async def _gravar_origem(self, escritorio: Escritorio, lead: Lead, origem: dict[str, Any]) -> None:
        """Primeiro toque: guarda a origem uma vez e deixa a nota do anúncio no atendimento."""
        from app.origem import nota_da_origem
        if not await self.repo.gravar_origem(lead.id, origem):
            return
        acoes = []
        if lead.id_sessao_helena:
            acoes.append({"tipo": "nota", "chave_unica": f"{lead.id}:origem", "dados": {"texto": nota_da_origem(origem)}})
        if any(origem.get(c) for c in ("campanha", "titulo", "conteudo", "termo")):
            acoes.append({"tipo": "classificar_origem", "chave_unica": f"{lead.id}:origem:produto", "dados": {}})
        await self.repo.enfileirar_acoes(id_escritorio=escritorio.id, id_lead=lead.id, id_turno=None, acoes=acoes)

    NOTAS_DE_PROBLEMA = {
        "ia_nao_respondeu": "⚠️ A IA não conseguiu responder esta conversa ({detalhe}). Responda manualmente.",
        "envio_falhou": "⚠️ Parte da resposta da IA não foi entregue. Confira a conversa e complete manualmente.",
        "midia_quebrada": "⚠️ A IA não enviou uma mídia do roteiro ({detalhe}). Se precisar, envie manualmente e "
                          "corrija o link no roteiro.",
        "envio_sem_confirmacao": "⚠️ A Helena não confirmou o envio de parte da resposta da IA. Confira se a mensagem "
                                 "chegou ao lead; se não chegou, envie manualmente.",
        "limite_de_consumo": "🚫 A IA não respondeu: o limite de consumo da IA deste mês acabou. Responda manualmente.",
        "sem_saldo": "🚫 A IA não respondeu: o saldo da IA do escritório acabou. Responda manualmente; ela volta sozinha "
                     "quando entrar crédito.",
        "agente_sem_etapa": "⚠️ A IA não respondeu: o agente deste número está sem etapa configurada. Responda manualmente.",
        "canal_sem_agente": "⚠️ A IA não respondeu: este número não tem agente ligado. Responda manualmente.",
        "card_nao_criado": automacoes.NOTA_CARD_NAO_CRIADO,
        "agente_pausado": "🤖 O agente de IA deste canal está pausado.\n"
                          "Este lead mandou mensagem e não foi respondido pela IA. A mensagem ficou registrada.",
        "ia_desligada_no_escritorio": "🤖 A IA está desligada neste escritório.\n"
                                      "Este lead mandou mensagem e não foi respondido pela IA. A mensagem ficou registrada.",
        "contato_sem_numero": "🤖 A IA não iniciou a conversa com este contato: o WhatsApp não informou o número dele "
                              "(privacidade).\nResponda manualmente.",
        "ia_sem_credito": "🤖 A IA não conseguiu responder este lead agora.\nA mensagem do lead ficou registrada. "
                          "A equipe LawChat já foi avisada. Se for urgente, responda manualmente.",
        "ia_conversa_longa": "⚠️ A IA não conseguiu responder esta conversa (a conversa ficou maior que o limite do modelo). "
                             "Responda manualmente.",
        "resposta_vazia": "🤖 A IA não conseguiu montar uma resposta para este lead. A mensagem ficou registrada. "
                          "Vale responder manualmente.",
        "contrato_correcao_repetida": "⚠️ A IA parou de tentar gerar o contrato: pediria ao lead a mesma correção de novo, "
                                      "sem dado novo (campos: {detalhe}). Finalize o contrato manualmente.",
        "pedido_repetido": "⚠️ A IA parou: repetiria ao lead um pedido que ele já respondeu ({detalhe}). "
                           "Continue a conversa manualmente.",
        "mensagem_atrasada": "⏰ Esta mensagem do lead chegou com {detalhe} de atraso e a IA não respondeu para não "
                             "falar fora de hora. Responda manualmente.",
        "janela_fechada": "⏰ O lead escreveu fora do horário e a janela de 24 h do número oficial fecha antes do "
                          "escritório abrir. Responda com modelo aprovado.",
        "etapa_terminal": "🏁 O lead está no fim do funil (contrato assinado) e mandou mensagem: a IA não responde "
                          "nesta etapa. Responda manualmente.",
        # Passagem para humano: a IA saiu da conversa (pausa sem volta automática). Sem a nota ninguém sabia na Helena.
        "pediu_humano": "🙋 O lead pediu para falar com uma pessoa. A IA saiu da conversa: responda manualmente.",
        "trava_persistente": "⚠️ A IA foi barrada duas vezes pelas travas de segurança e saiu da conversa. "
                             "Responda manualmente.",
        "analise_manual": "🔎 Caso para a equipe avaliar ({detalhe}). A IA saiu da conversa: responda manualmente.",
        "sinal": "🔔 O lead precisa de atenção da equipe ({detalhe}). A IA saiu da conversa: responda manualmente.",
    }

    # A IA não atende este lead: (gravidade, responsável, descrição do evento). O motivo vira o tipo do evento.
    SEM_ATENDIMENTO = {
        "agente_sem_etapa": ("aviso", "cadastro", "A IA não respondeu por problema de cadastro: agente_sem_etapa"),
        "canal_sem_agente": ("aviso", "cadastro", "A IA não respondeu por problema de cadastro: canal_sem_agente"),
        "limite_de_consumo": ("info", "cliente", "A IA não respondeu: o limite de consumo do mês acabou."),
        "sem_saldo": ("info", "cliente", "A IA não respondeu: o saldo da IA do escritório acabou."),
        "agente_pausado": ("aviso", "cliente", "Agente pausado: o lead mandou mensagem e não foi respondido."),
        "ia_desligada_no_escritorio": ("aviso", "cliente",
                                       "IA desligada no escritório: o lead mandou mensagem e não foi respondido."),
        "sem_prompt": ("aviso", "cadastro", "A etapa {etapa} do lead não tem prompt: a IA não responde nesta etapa."),
        "etapa_terminal": ("aviso", "cliente", "O lead está na etapa {etapa} (fim do funil): a IA não responde. "
                                               "Responda manualmente."),
        "janela_fechada": ("aviso", "cliente", "O lead escreveu fora do horário no número oficial e a janela de 24 h "
                                               "fecha antes de o escritório abrir: a IA não respondeu (precisa de modelo aprovado)."),
    }

    async def _nota_de_problema(self, escritorio: Escritorio, lead: Lead, tipo: str, detalhe: str,
                                inteiro: bool = False) -> None:
        """Avisa a equipe dentro da conversa, na Helena, no máximo 1 vez a cada 6 h por problema.

        inteiro=True usa o detalhe todo (um motivo escrito para a equipe); senão só o fim do código ('onde:motivo').
        Os sinais ('sinal_quer_videochamada', 'sinal_analise_humana'...) usam um modelo só, com o nome do sinal."""
        if tipo.startswith("sinal_") and tipo != "sinal_recusado":
            sinal = tipo.removeprefix("sinal_")
            tipo, detalhe, inteiro = "sinal", automacoes.NOMES_SINAIS.get(sinal, sinal.replace("_", " ")), True
        modelo = self.NOTAS_DE_PROBLEMA.get(tipo)
        if not modelo or not lead.id_sessao_helena:
            return
        detalhe = detalhe.strip()[:300] if inteiro else detalhe.split(":")[-1].strip()[:120]
        try:
            await self.repo.nota_de_problema(id_escritorio=escritorio.id, id_lead=lead.id, tipo=tipo,
                                             texto=modelo.format(detalhe=detalhe or tipo))
        except Exception:                                    # a nota é um extra: nunca derruba o turno
            log.exception("falha ao agendar a nota de problema %s", tipo)

    # Conversa maior que o limite do modelo (OpenAI: context_length_exceeded; Anthropic: prompt is too long).
    _CONVERSA_LONGA = re.compile(r"context_length_exceeded|maximum context length|context (?:length|window)|"
                                 r"prompt is too long|too many tokens|exceeds? (?:the )?context", re.IGNORECASE)
    _CHAVE_DO_PROVEDOR = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}

    def _classificar_falha_da_ia(self, saida: cerebro.Saida) -> None:
        """Afina o evento 'ia_nao_respondeu' do cérebro: conversa longa e falta de crédito viram tipos próprios,
        e chave recusada/sem crédito com a chave do servidor é problema da LawChat (vai para a central)."""
        for evento in saida.eventos:
            if evento.get("tipo") != "ia_nao_respondeu":
                continue
            onde, _, motivo = (saida.motivo or "").partition(":")
            if self._CONVERSA_LONGA.search(f"{evento.get('descricao') or ''} {evento.get('detalhe') or ''}"):
                motivo = "conversa_longa"
                saida.motivo = f"{onde}:{motivo}"
                evento.update(tipo="ia_conversa_longa", responsavel="lawchat",
                              descricao=f"Falha no {onde}: conversa_longa (a conversa ficou maior que o limite do modelo). "
                                        "O lead ficou sem resposta.")
            elif motivo == "sem_credito":
                evento["tipo"] = "ia_sem_credito"
            if motivo in ("chave_recusada", "sem_credito", "sem_permissao") and self._chave_do_servidor(saida):
                evento["responsavel"] = "lawchat"

    def _chave_do_servidor(self, saida: cerebro.Saida) -> bool:
        """A IA sempre chama o provedor com a chave do .env do servidor (OPENAI_API_KEY / ANTHROPIC_API_KEY)."""
        falhas = [c for c in saida.chamadas if not c.sucesso] or saida.chamadas
        nome = (falhas[-1].modelo if falhas else None) or self.config.modelo_padrao or ""
        provedor = "anthropic" if nome.startswith("claude") else "openai"
        return bool(os.environ.get(self._CHAVE_DO_PROVEDOR[provedor]))

    async def _conferir_consumo(self, escritorio: Escritorio) -> str | None:
        """Limite mensal do escritório: avisa uma vez por faixa e, se configurado, deixa a IA em silêncio."""
        if (sem_saldo := getattr(self.repo, "bloqueado_por_saldo", None)) and await sem_saldo(escritorio.id):
            return "sem_saldo"                       # pré-pago sem saldo (app/cobranca): o bloqueio único
        if not consumo.config_do_limite(escritorio.config)["mensal_usd"]:
            return None
        inicio = consumo.inicio_do_mes()
        mes = inicio.strftime("%Y-%m")
        gasto = self._consumo.em_cache(escritorio.id, mes)
        if gasto is None:
            gasto = await self.repo.gasto_desde(escritorio.id, inicio)
            self._consumo.guardar(escritorio.id, mes, gasto)
        situacao = consumo.avaliar(gasto, escritorio.config)
        chave = f"consumo:{escritorio.id}:{mes}:{situacao.faixa}"
        if situacao.faixa and chave not in self._avisos_de_consumo:
            self._avisos_de_consumo.add(chave)
            await self.repo.enfileirar_acoes(id_escritorio=escritorio.id, id_lead=None, id_turno=None, acoes=[{
                "tipo": "aviso_consumo", "chave_unica": chave,
                "dados": {"texto": consumo.texto_do_aviso(escritorio.nome, situacao, escritorio.config),
                          "faixa": situacao.faixa, "mes": mes, "gasto_usd": situacao.gasto_usd, "limite_usd": situacao.limite_usd}}])
        return "limite_de_consumo" if situacao.bloqueado else None

    JANELA_OFICIAL = timedelta(hours=24)

    async def _janela_fecha_antes(self, lead: Lead, pendentes: list[Any], quando: datetime) -> bool:
        """Canal oficial (API da Meta): em `quando` já terão passado 24 h da última mensagem do lead?"""
        canal = await self.repo.canal(lead.id_canal)
        if not canal or getattr(canal, "tipo", "nao_oficial") != "oficial":
            return False
        ultima = max((m.enviada_em for m in pendentes if m.enviada_em), default=None)
        return ultima is not None and quando - ultima >= self.JANELA_OFICIAL

    async def _religar_se_venceu(self, lead: Lead) -> Lead:
        """A pausa por atendente (ou a desativação com prazo) acabou: a IA volta, sem mandar nada sozinha."""
        if lead.estado == "pausado" and lead.pausado_ate and lead.pausado_ate <= agora():
            religar = getattr(self.repo, "religar_pausas_vencidas", None)
            # Desativação com prazo: mesmo caminho da volta a cada minuto (tira a etiqueta e deixa nota).
            if not (lead.motivo_estado == "desativada_pela_equipe" and religar and await religar(lead.id)):
                await self.repo.atualizar_lead(lead.id, estado="ativo", motivo_estado=None, pausado_ate=None)
            lead.estado, lead.motivo_estado, lead.pausado_ate = "ativo", None, None
        return lead

    async def _equipe_falou_por_ultimo(self, id_lead: str, pendentes: list[Any]) -> bool:
        """A equipe respondeu depois da última mensagem do lead que espera resposta (guardada durante a desativação)."""
        ultima_do_lead = max((m.enviada_em for m in pendentes if m.enviada_em), default=None)
        if ultima_do_lead is None:
            return False
        try:
            historico = await self.repo.historico(id_lead, 20)
        except Exception:
            log.exception("falha ao ler o histórico do lead %s", id_lead)
            return False
        return any(m.autor == "humano" and m.enviada_em and m.enviada_em > ultima_do_lead for m in historico)

    def _por_que_nao_atende(self, escritorio: Escritorio, agente: Agente | None, lead: Lead,
                            etapa: Any, modo: str) -> str | None:
        if modo == "laboratorio":
            return None if (agente and etapa) else "agente_sem_etapa"
        if escritorio.situacao != "ativo":
            return "escritorio_inativo"              # cliente suspenso ou encerrado: silêncio, sem evento nem nota no chat dele
        # IA desligada ou agente pausado só viram nota quando o lead está ativo: com humano ou encerrado,
        # a IA não atenderia de qualquer jeito (como no n8n, que olhava primeiro a IA do próprio lead).
        if escritorio.ia_desligada:
            return "ia_desligada_no_escritorio" if lead.estado == "ativo" else "lead_" + lead.estado
        if not agente:
            return "canal_sem_agente"
        if agente.situacao != "ativo":
            return "agente_pausado" if lead.estado == "ativo" else "lead_" + lead.estado
        if lead.estado != "ativo":
            return "lead_" + lead.estado
        if not etapa:
            return "agente_sem_etapa"
        if modo == "teste" and lead.telefone not in self._numeros_de_teste(escritorio, agente):
            return "modo_teste"
        if agente.produto == "catalogo":
            if etapa.codigo not in produtos.carregar(agente.produto, agente.config).papeis:
                # Contrato assinado (ou outra etapa fora dos papéis): sem papel não há agente. Antes o turno caía no
                # papel inicial, o SDR recomeçava a qualificação e a etapa e o card voltavam para SDR.
                return "etapa_terminal"
            if not self._instrucao_do_catalogo(agente, etapa):
                return "sem_prompt"                  # sem prompt a IA responderia só com o bloco de formato
        return None

    @staticmethod
    def _instrucao_do_catalogo(agente: Agente, etapa: Any) -> str:
        """Instrução do papel do lead no agente do catálogo (vazio quando a etapa não é um papel: nunca o inicial)."""
        produto = produtos.carregar(agente.produto, agente.config)
        if etapa.codigo not in produto.papeis:
            return ""
        usada = agente.etapa(etapa.codigo)
        return ((usada.instrucao if usada else None) or "").strip()

    async def _conhecimento(self, agente: Agente, pendentes: list[Any], historico: list[Any],
                            papel: str | None = None) -> dict[str, Any]:
        """Base de conhecimento do turno (docs/BASE_DE_CONHECIMENTO.md): o que é pequeno fica fixo no sistema; a busca
        pela fala nova do lead começa aqui, como tarefa, e roda junto do extrator (o turno espera em "_busca")."""
        from app import conhecimento as base
        from app import conhecimento_indice as indice

        config = dict(agente.config.get("conhecimento") or {})
        try:
            trechos = await self.repo.trechos_do_agente(agente.id)      # escopo: agente (= escritório + produto)
            sem_indice = await self.repo.documentos_do_agente(agente.id)
            real = self.vetorizador is not None and not getattr(self.vetorizador, "falso", False)
            preparo = indice.preparar(config, papel, indexados=trechos, sem_indice=sem_indice,
                                      modelo_vetor=getattr(self.vetorizador, "modelo", None) if real else None)
            limites = indice.limites(config)
        except Exception:                            # noqa: BLE001 - a base nunca derruba o turno
            log.warning("base de conhecimento indisponível; turno segue com o conhecimento da config", exc_info=True)
            return {k: config[k] for k in ("dados_escritorio", "faq", "objecoes") if config.get(k)}
        ultima = base.ultima_pergunta_da_ia([{"autor": m.autor, "texto": m.para_a_ia()} for m in historico])
        busca = asyncio.create_task(indice.buscar(
            preparo.candidatos, [m.para_a_ia() for m in pendentes if m.para_a_ia()], papel=papel, ultima_pergunta_ia=ultima,
            vetorizador=self.vetorizador, cache=self._cache_consultas, minimo=limites["minimo"], teto=limites["teto"],
            quantos=limites["quantos"]))
        return {**preparo.fixo, "base": True, "_busca": busca}

    async def _depois_da_busca(self, agente: Agente, entrada: cerebro.Entrada, saida: cerebro.Saida) -> None:
        """Custo do embedding da consulta no consumo do turno; busca que o turno não usou é cancelada; dimensão errada avisa."""
        pendente = (entrada.conhecimento or {}).get("_busca")
        if isinstance(pendente, asyncio.Task):
            if not pendente.done():
                pendente.cancel()                    # o turno saiu antes de usar (pedido de humano, sinal, falha)
                return
            pendente = None if pendente.cancelled() or pendente.exception() else pendente.result()
        if pendente is None:
            return
        if pendente.chamada is not None:
            saida.chamadas.append(pendente.chamada)
        saida.contexto.setdefault("conhecimento", pendente.para_contexto())
        if pendente.dimensao_diferente:
            saida.eventos.append({"tipo": "base_dimensao_diferente", "gravidade": "aviso", "responsavel": "lawchat",
                                  "descricao": "Os vetores da base foram gerados com outro modelo; a busca usou palavras "
                                               "e a base volta para a reindexação.", "detalhe": {}})
            if reindexar := getattr(self.repo, "reindexar_base", None):
                await reindexar(agente.id, getattr(self.vetorizador, "modelo", ""), getattr(self.vetorizador, "dimensoes", 0))

    async def _registrar_lacuna(self, escritorio: Escritorio, agente: Agente, lead: Lead, id_turno: str,
                                saida: cerebro.Saida) -> None:
        """Pergunta que a IA não achou na base (base.sem_resposta) vira lacuna para o painel (soma "vezes")."""
        registro = saida.contexto.get("conhecimento") or {}
        registrar = getattr(self.repo, "registrar_lacuna", None)
        if not registro.get("sem_resposta") or registrar is None:
            return
        try:
            await registrar(id_escritorio=escritorio.id, id_agente=agente.id, papel=registro.get("papel"),
                            pergunta=registro["sem_resposta"], id_lead=lead.id, id_turno=id_turno)
        except Exception:                            # noqa: BLE001 - a lacuna nunca derruba o turno
            log.warning("falha ao registrar a pergunta sem resposta", exc_info=True)

    async def _montar_entrada(self, escritorio: Escritorio, agente: Agente, lead: Lead,
                              etapa: str, pendentes: list[Any]) -> cerebro.Entrada:
        historico = await self.repo.historico(lead.id)
        modelos = agente.config.get("modelos", {})
        produto = produtos.carregar(agente.produto, agente.config)
        etapa_atual = agente.etapa(etapa)
        return cerebro.Entrada(
            escritorio=escritorio.nome,
            agente=agente.nome,
            etapa=etapa,
            novas=[m.para_a_ia() for m in pendentes if m.para_a_ia()] or ["(mensagem vazia)"],
            fatos=await self.repo.fatos_vigentes(lead.id),
            historico=[{"autor": "você" if m.autor == "ia" else ("atendente" if m.autor == "humano" else m.autor),
                        "texto": m.para_a_ia()} for m in historico if m.para_a_ia()],
            instrucoes={e.codigo: e.instrucao for e in agente.etapas},
            honorarios=agente.config.get("honorarios") or escritorio.config.get("honorarios"),
            midias={chave: m.get("descricao", "") for chave, m in agente.config.get("midias", {}).items()},
            produto=produto,
            mensagens_fixas=agente.config.get("mensagens_fixas", {}),
            modelo_extrator=modelos.get("extrator") or self.config.modelo_padrao,
            conhecimento=await self._conhecimento(agente, pendentes, historico, papel=(
                etapa if agente.produto != "catalogo" or etapa in produto.papeis else produto.etapa_inicial())),
            fatos_sistema=await self.repo.fatos_do_sistema(lead.id),
            comeco_conversa=await memoria.ler_comeco(self.repo, lead.id),
            temperatura=agente.config.get("temperatura") if agente.produto == "catalogo" else None,
            enriquecer=self._enriquecer_por_cep if (agente.config.get("funcoes") or {}).get("buscar_cep") else None,
            obrigatorios_contrato=await self._obrigatorios_do_contrato(escritorio, agente)
                                  if (agente.config.get("funcoes") or {}).get("contrato_zapsign") else None,
            modelo_auditor=None if (self.config.modelo_falso or agente.config.get("auditor") is False)
                           else (modelos.get("auditor") or os.environ.get("AGENTESIA_MODELO_AUDITOR", "gpt-6-luna")),
            modelo_etapa=(etapa_atual.modelo if etapa_atual and etapa_atual.modelo else None)
                         or modelos.get("etapa") or self.config.modelo_padrao,
            esforco_etapa=modelos.get("esforco", "medium"),
        )

    async def _enviar(self, escritorio: Escritorio, agente: Agente, lead: Lead, id_turno: str,
                      saida: cerebro.Saida, modo: str) -> tuple[bool, int]:
        """Envia cada parte. Uma parte que falha não para as outras. Devolve (completo, partes entregues); completo é False quando o envio parou porque
        o lead saiu da IA (atendente assumiu entre uma parte e outra).

        Token: só o do próprio escritório (integração e, como reserva, a coluna antiga; a mesma fonte do Executor e
        do follow-up). Sem token não há envio nem nota possível: evento de cadastro (vai para a central) e as partes
        ficam gravadas como 'falhou'. O token global do .env só vale no modo de laboratório (AGENTESIA_MODO_LAB=1)."""
        canal = await self.repo.canal(lead.id_canal)
        de_verdade = modo != "laboratorio" and self.helena is not None
        token = await self._token_helena(escritorio) if de_verdade else None
        if de_verdade and not token:
            saida.eventos.append({"tipo": "escritorio_sem_token_helena", "gravidade": "erro", "responsavel": "cadastro",
                                  "descricao": "O escritório não tem token da Helena cadastrado: a resposta da IA não foi "
                                               "enviada. Cadastre a integração da Helena no painel.", "detalhe": {}})
        enviadas: list[str] = []
        entregues = 0
        partes = list(saida.mensagens)
        interrompido = False
        for posicao, parte in enumerate(partes):
            texto = parte.get("texto") if parte["tipo"] == "texto" else None
            url = (parte.get("url") or agente.config.get("midias", {}).get(parte.get("chave", ""), {}).get("url")) if parte["tipo"] == "midia" else None
            if url and self._ptv_fora_do_horario(url, parte, agente, escritorio):
                # Vídeo de apresentação (ptv.mp4) só das 8h às 20h, como no n8n: fora disso a parte é pulada.
                saida.contexto.setdefault("midia_pulada", []).append({"url": url, "motivo": "fora_do_horario_comercial"})
                continue
            if url and de_verdade and token and await self._midia_quebrada(escritorio, lead, url, saida):
                continue                                 # link quebrado: não envia, avisa a equipe e segue com o texto
            id_externo, situacao, erro = None, "enviada", None
            ja_esperou = False
            if de_verdade and token and posicao > 0 and lead.id_sessao_helena:
                # Entre uma parte e outra o atendente pode ter assumido (o webhook dele pausa o lead no banco): a pausa de
                # digitação acontece primeiro e o lead é relido antes de cada parte. As partes que faltam não são
                # gravadas como mensagem (o lead não as viu; situacao_envio não tem 'cancelada') e ficam no contexto.
                if self.digitar:
                    await asyncio.sleep(float(parte.get("espera_s", 0)))
                ja_esperou = True
                atual = await self.repo.lead(lead.id)
                if atual and atual.estado != "ativo":
                    restantes = [p.get("texto") if p["tipo"] == "texto" else (p.get("url") or p.get("chave"))
                                 for p in partes[posicao:]]
                    motivo = atual.motivo_estado or "humano_assumiu_durante_envio"
                    saida.contexto["envio_interrompido"] = {"motivo": motivo, "partes_nao_enviadas": restantes}
                    saida.eventos.append({"tipo": "envio_interrompido", "gravidade": "info", "responsavel": "lawchat",
                                          "descricao": f"A IA parou de enviar a resposta no meio: o lead saiu da IA "
                                                       f"({motivo}). {len(restantes)} parte(s) não foram enviadas.",
                                          "detalhe": {"motivo": motivo, "partes_nao_enviadas": len(restantes)}})
                    interrompido = True
                    break
            if de_verdade and not token:
                situacao, erro = "falhou", "sem token da Helena"
            elif de_verdade:
                try:
                    if not lead.id_sessao_helena:
                        raise ErroHelena("lead sem atendimento aberto")
                    if self.digitar and not ja_esperou:
                        await asyncio.sleep(float(parte.get("espera_s", 0)))
                    id_externo = await self.helena.enviar(           # type: ignore[union-attr]
                        token=token, id_sessao=lead.id_sessao_helena,
                        id_canal=canal.id_canal_helena if canal else None, texto=texto, url_arquivo=url,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as falha:              # ErroHelena e qualquer outro: uma parte nunca para as outras
                    detalhe = str(falha) if isinstance(falha, ErroHelena) else f"erro interno: {type(falha).__name__}"
                    if not isinstance(falha, ErroHelena):
                        log.exception("erro inesperado ao enviar parte do turno %s", id_turno)
                    if detalhe.startswith("sem_confirmacao"):
                        # Timeout depois de enviado, 502/504: a Helena pode já ter aceitado. É 'talvez enviada', não
                        # falha: conta como entregue (não desfaz a troca de etapa nem marca NÃO ENTREGUE no histórico).
                        # O eco MESSAGE_SENT liga a linha ao id real (ligar_eco_a_ia); se ele já chegou, adota o id.
                        id_externo = await self._eco_ja_chegou(lead, texto, url)
                        if id_externo:
                            situacao, erro = "enviada", None
                        else:
                            situacao, erro = "pendente", detalhe
                            saida.eventos.append({
                                "tipo": "envio_sem_confirmacao", "gravidade": "aviso", "responsavel": "provedor",
                                "descricao": f"A Helena não confirmou o envio de uma parte da resposta ({detalhe}); "
                                             "ela pode ter chegado ao lead. Confira a conversa.",
                                "detalhe": {"trecho": (texto or url or "")[:200]}})
                    else:
                        situacao, erro = "falhou", detalhe
                        saida.eventos.append({"tipo": "envio_falhou", "gravidade": "erro", "responsavel": "provedor",
                                              "descricao": f"Parte da resposta não foi enviada ({detalhe}).",
                                              "detalhe": {"trecho": (texto or url or "")[:200]}})
            # Mídia: o tipo pela extensão e a URL inteira no histórico (a regra "não envie de novo se o link já está no
            # histórico" do roteiro compara o link; o prefixo "[mídia enviada:" é lido pelo painel e pela avaliação).
            # Parte que não chegou ao lead entra no histórico marcada: a IA não pode presumir que ele viu.
            if situacao == "falhou":
                extraido = "[NÃO ENTREGUE ao lead] " + (texto if texto is not None else f"mídia {url or parte.get('chave')}")
            else:
                extraido = None if texto is not None else f"[mídia enviada: {url or parte.get('chave')}]"
            try:
                await self.repo.gravar_mensagem(
                    lead=lead, autor="ia", tipo="texto" if texto is not None else self.tipo_da_midia(url),
                    texto=texto, texto_extraido=extraido,
                    url_midia=url, enviada_em=agora(), id_externo=id_externo, id_turno=id_turno,
                    situacao_envio=situacao, erro=erro,
                )
            except Exception:
                log.exception("falha ao gravar a parte enviada no turno %s", id_turno)
            if situacao in ("enviada", "pendente"):           # 'pendente' = talvez enviada (sem confirmação)
                entregues += 1
            if id_externo:
                enviadas.append(id_externo)
                if url and self.digitar and posicao < len(partes) - 1:
                    # A Helena e o WhatsApp baixam o arquivo antes de entregar: sem esta pausa, o texto seguinte chegava
                    # antes do vídeo (o n8n esperava depois de cada envio e 10 s depois do vídeo de apresentação).
                    await asyncio.sleep(self._espera_depois_da_midia(url, parte, agente))
        if enviadas:
            # O envio é assíncrono (a Helena só diz que entrou na fila): 1 min depois, a fila confere a entrega e
            # transforma FAILED em 'falhou' + envio_falhou + nota (mídia apagada, URL renomeada...).
            try:
                await self.repo.enfileirar_acoes(id_escritorio=escritorio.id, id_lead=lead.id, id_turno=id_turno, acoes=[{
                    "tipo": "conferir_entrega", "chave_unica": f"{id_turno}:entrega", "atraso_s": self.ATRASO_CONFERIR_ENTREGA_S,
                    "dados": {"ids": enviadas, "id_turno": id_turno}}])
            except Exception:                                # conferir é um extra: nunca derruba o turno
                log.exception("falha ao agendar a conferência de entrega do turno %s", id_turno)
        return not interrompido, entregues

    ATRASO_CONFERIR_ENTREGA_S = 60
    JANELA_DO_ECO_MIN = 15                                # eco de parte sem confirmação: até 15 min depois

    async def _eco_ja_chegou(self, lead: Lead, texto: str | None, url: str | None) -> str | None:
        """Parte sem confirmação cujo eco (MESSAGE_SENT, origem API) chegou antes e foi gravado como 'automacao':
        devolve o id dele (a parte é gravada com esse id e a linha vira da IA)."""
        if not (buscar := getattr(self.repo, "eco_sem_dono", None)):
            return None
        try:
            return await buscar(lead.id, texto=texto, url_midia=url, minutos=self.JANELA_DO_ECO_MIN)
        except Exception:                                    # reconciliar é um extra: nunca derruba o envio
            log.exception("falha ao procurar o eco da parte sem confirmação do lead %s", lead.id)
            return None

    # Pausa depois de uma mídia enviada, antes da parte seguinte, pelo tipo do arquivo (valor único, sem config).
    # Conferência do link da mídia antes do envio (app/midia/link.py: HEAD curto, com cache). None = não confere
    # (testes, laboratório, avaliação); o app de produção liga em app/main.py.
    conferir_midia: Any | None = None

    async def _midia_quebrada(self, escritorio: Escritorio, lead: Lead, url: str, saida: cerebro.Saida) -> bool:
        """True se o link da mídia não abre (apagada, renomeada, página no lugar do arquivo, grande demais): a parte não
        vai, a equipe recebe nota na conversa e o cadastro recebe o evento. Falha da conferência nunca barra o envio."""
        if self.conferir_midia is None:
            return False
        try:
            motivo = await self.conferir_midia(url, self.tipo_da_midia(url))
        except Exception:
            log.exception("falha ao conferir o link da mídia %s", url)
            return False
        if not motivo:
            return False
        nome = self.tipo_da_midia(url).replace("audio", "áudio").replace("video", "vídeo")
        saida.contexto.setdefault("midia_pulada", []).append({"url": url, "motivo": motivo})
        saida.eventos.append({"tipo": "midia_quebrada", "gravidade": "erro", "responsavel": "cadastro",
                              "descricao": f"A IA não enviou um {nome} do roteiro: {motivo}. Troque o link no roteiro "
                                           "ou suba o arquivo de novo na biblioteca de mídia.",
                              "detalhe": {"url": url, "motivo": motivo}})
        await self._nota_de_problema(escritorio, lead, "midia_quebrada", f"{nome}: {motivo}", inteiro=True)
        return True

    ESPERA_DEPOIS_DA_MIDIA_S = {"video": 8.0, "audio": 3.0, "imagem": 2.0}
    ESPERA_DEPOIS_DO_PTV_S = 10.0                         # vídeo de apresentação (VIDEO INICIAL do n8n)
    HORARIO_DO_PTV = (8, 20)                              # das 8h às 20h, no fuso do escritório
    _EXTENSOES_DA_MIDIA = {"audio": (".ogg", ".oga", ".opus", ".mp3", ".m4a", ".aac", ".wav", ".flac"),
                           "imagem": (".jpg", ".jpeg", ".png", ".webp", ".gif")}

    @classmethod
    def tipo_da_midia(cls, url: str | None) -> str:
        """'audio', 'imagem' ou 'video', pela extensão do caminho da URL (sem a query)."""
        from urllib.parse import unquote, urlparse

        caminho = unquote(urlparse(url or "").path).lower()
        if "/midia/" in caminho and (achado := re.search(r"/midia/[0-9a-f-]{36}/(audio|video|imagem)/", caminho)):
            return achado.group(1)                        # biblioteca do escritório: a pasta já diz o tipo
        return next((tipo for tipo, extensoes in cls._EXTENSOES_DA_MIDIA.items() if caminho.endswith(extensoes)), "video")

    @staticmethod
    def _config_da_midia(url: str, parte: dict[str, Any], agente: Agente) -> dict[str, Any]:
        """A entrada de config.midias desta parte (pela chave ou pela URL), ou {}."""
        midias_cfg = agente.config.get("midias") or {}
        if isinstance(midias_cfg.get(parte.get("chave") or ""), dict):
            return midias_cfg[parte["chave"]]
        return next((m for m in midias_cfg.values() if isinstance(m, dict) and m.get("url") == url), {})

    def _e_ptv(self, url: str, parte: dict[str, Any], agente: Agente) -> bool:
        from urllib.parse import unquote, urlparse

        if bool(self._config_da_midia(url, parte, agente).get("so_horario_comercial")):
            return True
        return unquote(urlparse(url).path).lower().endswith("ptv.mp4")

    def _ptv_fora_do_horario(self, url: str, parte: dict[str, Any], agente: Agente, escritorio: Escritorio) -> bool:
        from app.notificacoes import fuso

        if not self._e_ptv(url, parte, agente):
            return False
        hora = agora().astimezone(fuso(escritorio.config.get("fuso") or "America/Sao_Paulo")).hour
        return not (self.HORARIO_DO_PTV[0] <= hora < self.HORARIO_DO_PTV[1])

    def _espera_depois_da_midia(self, url: str, parte: dict[str, Any], agente: Agente) -> float:
        if self._e_ptv(url, parte, agente):
            return self.ESPERA_DEPOIS_DO_PTV_S
        return self.ESPERA_DEPOIS_DA_MIDIA_S.get(self.tipo_da_midia(url), self.ESPERA_DEPOIS_DA_MIDIA_S["video"])

    async def _token_helena(self, escritorio: Escritorio) -> str | None:
        token = await self.repo.token_helena(escritorio.id)
        if not token and os.environ.get("AGENTESIA_MODO_LAB", "").strip() == "1":
            token = os.environ.get("AGENTESIA_HELENA_TOKEN")       # só demonstração local, nunca em produção
        return token

    async def _fechar(self, id_turno: str, saida: cerebro.Saida, situacao: str, motivo: str) -> None:
        resposta = {
            "mensagens": saida.mensagens, "fatos_novos": saida.fatos_novos, "fatos_rejeitados": saida.fatos_rejeitados,
            "decisoes": saida.decisoes, "faltam": saida.faltam, "reprovacoes": saida.reprovacoes,
            "sinais": saida.sinais, "intencoes": saida.intencoes,
            "estado_lead": saida.estado_lead, "motivo_estado": saida.motivo_estado,
        }
        await self.repo.fechar_turno(id_turno, situacao=situacao, motivo=motivo, etapa_depois=saida.etapa_depois,
                                     contexto=saida.contexto, resposta=resposta)

    async def _evento(self, id_escritorio: str | None, id_lead: str | None, id_turno: str | None,
                      tipo: str, gravidade: str, responsavel: str, descricao: str) -> None:
        await self.repo.gravar_eventos(
            id_escritorio=id_escritorio, id_lead=id_lead, id_turno=id_turno,
            eventos=[{"tipo": tipo, "gravidade": gravidade, "responsavel": responsavel,
                      "descricao": descricao, "detalhe": {}}],
        )
