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
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

from app.banco.tipos import Agente, Canal, Escritorio, Lead, Repositorio
from app.canal import filtro
from app.canal.helena import ClienteHelena, ErroHelena, Evento, ler_webhook, normalizar_telefone
from app import automacoes
from app import tempos
from app import consumo
from app import memoria
from app import midia as midias
from app.cerebro import formatador
from app.cerebro import turno as cerebro
from app.cerebro import produto as produtos
from app.config import Configuracao
from app.modelo import ErroModelo, Modelo

log = logging.getLogger("agentesia")


def detalhe_do_erro(erro: BaseException) -> dict[str, Any]:
    """O que a tela Execuções precisa para classificar um erro (timeout, 5xx, banco): tipo, módulo, mensagem curta,
    a linha do nosso código onde estourou e o status HTTP quando houver (vai no detalhe do evento 'erro_no_turno')."""
    import traceback
    quadro = next((q for q in reversed(traceback.extract_tb(erro.__traceback__))
                   if "/app/" in q.filename.replace("\\", "/")), None)
    arquivo = quadro.filename.replace("\\", "/").split("/app/")[-1] if quadro else ""
    onde = f"{arquivo}:{quadro.lineno} ({quadro.name})" if quadro else None
    status = getattr(erro, "status_code", None) or getattr(erro, "status", None)
    if status is None and (resposta := getattr(erro, "response", None)) is not None:
        status = getattr(resposta, "status_code", None)
    return {"tipo": type(erro).__name__, "modulo": type(erro).__module__, "mensagem": str(erro)[:300], "onde": onde,
            "status": status if isinstance(status, int) else None}


def agora() -> datetime:
    return datetime.now(timezone.utc)


def _inteiro_do_env(nome: str, padrao: int) -> int:
    try:
        return max(1, int(os.environ.get(nome, padrao)))
    except ValueError:
        return padrao


def turnos_simultaneos() -> int:
    """AGENTESIA_TURNOS_SIMULTANEOS (padrão 5): turnos rodando ao mesmo tempo neste processo; os outros esperam a vez."""
    return _inteiro_do_env("AGENTESIA_TURNOS_SIMULTANEOS", 5)


def consultas_paralelas() -> int:
    """AGENTESIA_TURNO_CONSULTAS_PARALELAS (padrão 3): idas ao banco em paralelo dentro de um turno."""
    return _inteiro_do_env("AGENTESIA_TURNO_CONSULTAS_PARALELAS", 3)


async def _em_paralelo(*aguardaveis: Any, limite: int | None = None, return_exceptions: bool = False) -> list[Any]:
    """asyncio.gather com no máximo `limite` (consultas_paralelas()) rodando ao mesmo tempo: um turno não ocupa
    9 conexões do pool de uma vez. A ordem dos resultados é a dos aguardáveis."""
    vagas = asyncio.Semaphore(limite or consultas_paralelas())

    async def na_vez(aguardavel: Any) -> Any:
        async with vagas:
            return await aguardavel
    return list(await asyncio.gather(*(na_vez(a) for a in aguardaveis), return_exceptions=return_exceptions))


class ModeloQueAnota:
    """Embrulho do modelo que anota cada chamada de IA (com sucesso ou com erro) numa lista própria, que sobrevive ao
    cancelamento do turno (teto AGENTESIA_TETO_TURNO_S). O resto passa direto para o modelo de verdade."""

    def __init__(self, modelo: Any) -> None:
        self._modelo = modelo
        self.chamadas: list[Any] = []

    async def gerar(self, **pedido: Any) -> Any:
        try:
            resultado = await self._modelo.gerar(**pedido)
        except BaseException as erro:
            self.chamadas.extend(getattr(erro, "chamadas", None) or [])
            raise
        self.chamadas.extend(getattr(resultado, "chamadas", None) or [])
        return resultado

    def __getattr__(self, nome: str) -> Any:
        return getattr(self._modelo, nome)


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
        self._fundo: set[asyncio.Task[None]] = set()       # notas e extras em segundo plano (não atrasam o lead)
        self._reservados: set[str] = set()                 # leads com reserva deste processo (soltas ao desligar)
        self._preparo_do_envio: dict[str, tuple[Any, float | None]] = {}   # por turno: (canal, token), resposta pronta
        self._nota_antes_do_envio: dict[str, tuple[str, str]] = {}          # por turno: (chave, texto) da nota de início
        # Turnos ao mesmo tempo neste processo (AGENTESIA_TURNOS_SIMULTANEOS, padrão 5): cada turno abre várias idas ao
        # banco em paralelo; sem teto, uma rajada de leads esgotava o pool e todo mundo esperava conexão.
        self._turnos_simultaneos = asyncio.Semaphore(turnos_simultaneos())
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
        # Relógio da espera: conta da CHEGADA do webhook. Antes contava do fim da recepção (≈17 idas ao banco depois),
        # e o lead esperava o delay + o tempo da recepção.
        chegada = (asyncio.get_running_loop().time(), agora())
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
            return await self._receber_do_escritorio(escritorio, evento, chegada)
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
            "descricao": f"O WhatsApp não entregou uma parte da resposta da IA ({motivo}).",
            "detalhe": {"id_externo": evento.id_externo, "trecho": (linha.get("texto") or linha.get("url_midia") or "")[:200]}}])
        lead = await self.repo.lead(id_lead) if id_lead else None
        if lead:
            await self._nota_de_problema(escritorio, lead, "envio_falhou", motivo, inteiro=True)
        return {"feito": "status", "motivo": "envio_falhou", "id_lead": id_lead}

    async def _receber_do_escritorio(self, escritorio: Escritorio, evento: Evento,
                                     chegada: tuple[float, datetime] | None = None) -> dict[str, Any]:
        canal = await self.repo.canal_por_numero(escritorio.id, evento.numero_canal or "")
        if not canal:
            await self._evento(escritorio.id, None, None, "canal_nao_cadastrado", "aviso", "cadastro",
                               "Mensagem em número que não é canal cadastrado.")
            return {"feito": "ignorado", "motivo": "canal_nao_cadastrado"}
        if evento.classe == "api" and evento.id_externo and not evento.origem \
                and await self.repo.mensagem_e_da_ia(escritorio.id, evento.id_externo):
            # Eco (MESSAGE_SENT) de uma parte que a IA já gravou com o id: nada a fazer, nem achar/criar o lead (antes
            # gastava ~4 idas ao banco por parte enviada).
            return {"feito": "ignorado", "motivo": "eco_da_ia"}
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
            if evento.id_externo and evento.origem and await self.repo.mensagem_e_da_ia(escritorio.id, evento.id_externo):
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
        if decisao.responder and (resultado := await self._barrar_lead_suspeito(escritorio, agente, lead, evento)):
            return resultado                     # IA desligada (ou já estava) por suspeita: sem ler mídia, sem turno
        espera = self._tempo_de_espera(escritorio, agente, lead, evento) if decisao.responder else 0.0
        relogio, chegou_em = chegada or (asyncio.get_running_loop().time(), agora())
        if decisao.responder:
            # Logo depois de gravar: se o processo cair daqui em diante, retomar_pendentes ainda acha a mensagem.
            await self._marcar_resposta(lead.id, chegou_em + timedelta(seconds=espera))
        # Independentes entre si: juntas (uma ida ao banco de espera em vez de três).
        _, _, primeiro = await self._juntos(
            self.repo.atualizar_lead(lead.id, ultima_mensagem_lead_em=evento.enviada_em),
            self.repo.cancelar_followups(lead.id, "lead_respondeu"),
            self._primeiro_contato(lead, antes_de=id_mensagem) if agente else self._nada(False))
        # Card e etiqueta SDR na PRIMEIRA mensagem do lead, não só na criação da linha: o lead aberto pela atendente
        # ou por API (campanha) já existe quando o contato responde. A fila é idempotente (chave {id_lead}:lead_novo).
        if agente and primeiro and self._vira_card(escritorio, agente, evento, decisao.motivo):
            await self._lead_novo(escritorio, agente, lead)       # card e etiqueta na chegada, sem esperar a IA
        if not decisao.responder:
            if decisao.pausar_lead and lead.estado == "ativo":
                await self.repo.atualizar_lead(lead.id, estado="pausado", motivo_estado=decisao.motivo,
                                               pausado_ate=agora() + timedelta(hours=1))
            if decisao.avisar:
                await self._evento(escritorio.id, lead.id, None, decisao.motivo, "aviso", "lead", decisao.avisar)
            if decisao.motivo in ("mensagem_atrasada", "rajada") and not self._fora_do_teste(escritorio, agente, lead):
                # A equipe vê no chat que o lead ficou sem resposta (1 nota a cada 6 h por conversa). Sem desculpa automática.
                # Número fora da lista de teste (agente em teste) não ganha nota: é conversa que a IA nem atenderia.
                await self._nota_de_problema(escritorio, lead, decisao.motivo, decisao.detalhe, inteiro=True)
            return {"feito": "gravado", "motivo": decisao.motivo, "id_lead": lead.id}
        if self._precisa_ler_midia(evento):
            await self._marcar_midia_pendente(id_mensagem)
            self._ler_em_segundo_plano(id_mensagem, lead, agente, evento)
        # O prazo conta da chegada: o tempo da recepção já gasto sai da espera (assinatura de _agendar inalterada).
        self._agendar(lead.id, max(0.0, espera - (asyncio.get_running_loop().time() - relogio)))
        return {"feito": "agendado", "id_lead": lead.id, "espera_s": espera}

    # ------------------------------------------------------------------ lead suspeito (app/canal/suspeito.py)
    async def _barrar_lead_suspeito(self, escritorio: Escritorio, agente: Agente | None, lead: Lead,
                                    evento: Evento) -> dict[str, Any] | None:
        """Antes de gastar (modelo, transcrição, visão, PDF): o lead já marcado como suspeito só tem a mensagem gravada;
        o que dispara agora desliga a IA (etiqueta, follow-ups cancelados, evento e nota interna). None = segue normal.
        Nunca derruba a recepção: falha na checagem vira log e o atendimento segue."""
        from app.canal import suspeito
        if lead.estado == "pausado" and lead.motivo_estado == suspeito.MOTIVO:
            await self.repo.atualizar_lead(lead.id, ultima_mensagem_lead_em=evento.enviada_em)
            return {"feito": "gravado", "motivo": suspeito.MOTIVO, "id_lead": lead.id}
        if lead.novo or lead.estado != "ativo" or not agente or agente.situacao != "ativo" or escritorio.situacao != "ativo" \
                or escritorio.ia_desligada or self._fora_do_teste(escritorio, agente, lead):
            return None                              # a IA não atenderia de qualquer jeito: nada a economizar
        ler = getattr(self.repo, "mensagens_para_suspeita", None)
        regras = suspeito.Regras.de(escritorio.config, agente.config)
        if ler is None or not regras.ligado:
            return None
        try:
            veredito = suspeito.avaliar(await ler(lead.id, regras.janela * 3), regras,
                                        avancado=self._etapa_avancada(agente, lead))
            if veredito is None:
                return None
            await self._desligar_por_suspeita(escritorio, lead, evento, veredito)
        except Exception:
            log.exception("falha na checagem de lead suspeito do lead %s", lead.id)
            return None
        return {"feito": "gravado", "motivo": suspeito.MOTIVO, "suspeita": veredito.motivo, "id_lead": lead.id}

    @staticmethod
    def _etapa_avancada(agente: Agente, lead: Lead) -> bool:
        """Lead fora da etapa inicial (já qualificado, com dados): só repetição literal clara desliga a IA."""
        principal = agente.principal()
        return bool(lead.id_etapa and principal and lead.id_etapa != principal.id)

    async def _desligar_por_suspeita(self, escritorio: Escritorio, lead: Lead, evento: Evento, veredito: Any) -> None:
        """Mesmo efeito do desligar da equipe (app/ia_controle.py), sem prazo: só a equipe religa. Nada vai ao lead."""
        from app import ia_controle
        from app.canal import suspeito
        if self._prazos.pop(lead.id, None) is not None and (espera := self._esperas.get(lead.id)) and not espera.done():
            espera.cancel()                          # ainda esperando (não começou o turno): acaba sem processar
        for tarefa in list(self._midias.get(lead.id, ())):
            tarefa.cancel()                          # leitura de mídia em andamento: não transcreve nem descreve
        await self._juntos(
            self.repo.atualizar_lead(lead.id, estado="pausado", motivo_estado=suspeito.MOTIVO, pausado_ate=None,
                                     ultima_mensagem_lead_em=evento.enviada_em),
            self._marcar_resposta(lead.id, None),
            self.repo.cancelar_followups(lead.id, suspeito.MOTIVO))
        if limpar := getattr(self.repo, "limpar_midia_pendente", None):
            for mensagem in await self.repo.mensagens_pendentes(lead.id):
                if mensagem.midia_pendente_desde is not None:
                    await limpar(mensagem.id)        # o turno de depois do religamento não espera leitura cancelada
        await self.repo.gravar_eventos(id_escritorio=escritorio.id, id_lead=lead.id, id_turno=None, eventos=[{
            "tipo": suspeito.MOTIVO, "gravidade": "aviso", "responsavel": "cliente", "descricao": veredito.descricao(),
            "detalhe": {"motivo": veredito.motivo, "razao": veredito.razao, **veredito.contagens}}])
        carimbo = self._carimbo()
        # Chave com ':ia:' como no ia_controle: o CONTACT_TAG_UPDATE que a etiqueta gera é reconhecido como eco.
        acoes = [{"tipo": "etiquetar", "chave_unica": f"{lead.id}:ia:suspeito-{carimbo}:etiqueta",
                  "dados": {"adicionar": [ia_controle.ETIQUETA], "remover": []}}]
        if lead.id_sessao_helena:
            acoes.append({"tipo": "nota", "chave_unica": f"{lead.id}:nota:lead_suspeito:{carimbo}",
                          "dados": {"texto": veredito.nota()}})
        await self.repo.enfileirar_acoes(id_escritorio=escritorio.id, id_lead=lead.id, id_turno=None, acoes=acoes)

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

    async def _lead_ja_falou(self, lead: Lead) -> bool:
        """O contato já mandou alguma mensagem como lead (a IA esteve ou estaria nessa conversa)."""
        try:
            return any(m.autor == "lead" for m in await self.repo.historico(lead.id, 40)) \
                or bool(await self.repo.mensagens_pendentes(lead.id))
        except Exception:
            log.exception("falha ao conferir se o lead %s já falou", lead.id)
            return True

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
        pausa = self._pausa_por_humano(lead, agente)
        try:
            id_mensagem = await self.repo.registrar_fala_do_atendente(
                lead=lead, tipo=evento.tipo, texto=evento.texto, texto_extraido=evento.texto_extraido,
                url_midia=evento.url_midia, enviada_em=evento.enviada_em or agora(), id_externo=evento.id_externo,
                pausa=pausa, motivo_followup="equipe_falou")
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
        if pausa and not (lead.estado == "pausado" and lead.motivo_estado == "humano_assumiu") \
                and not self._fora_do_teste(escritorio, agente, lead) and await self._lead_ja_falou(lead):
            # Primeira fala da equipe que pausa a IA (pausa só renovada não repete): nota interna em segundo plano.
            # Sem nota em conversa que o lead nunca abriu (disparo automático para a equipe, "NOVA DEMANDA"...)
            # nem em número fora da lista de teste (26/11: notas "IA pausada" nos chats da própria equipe).
            volta = pausa.get("pausado_ate")
            texto = (self.NOTA_PAUSA_HUMANO.format(hora=self._hora(escritorio, volta)) if volta
                     else self.NOTA_PAUSA_HUMANO_SEM_VOLTA)
            self._em_segundo_plano("nota_pausa_humano", self._nota_interna(
                escritorio, lead, f"{lead.id}:nota:pausa_humano:{id_mensagem or self._carimbo()}", texto),
                escritorio, lead, None)
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
                           "O WhatsApp não informou o contato desta conversa (privacidade de número). "
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

    def _fora_do_teste(self, escritorio: Escritorio, agente: Agente | None, lead: Lead) -> bool:
        """Agente em modo teste e este número não está na lista de teste: a IA não atenderia (sem nota no chat)."""
        return bool(agente and agente.modo == "teste"
                    and lead.telefone not in self._numeros_de_teste(escritorio, agente))

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
            except Exception as erro:                # nunca deixa a tarefa morrer calada
                log.exception("falha ao processar o lead %s", id_lead)
                # Tipo, mensagem e a linha do código onde falhou: aparece na tela de Erros (sem precisar do log).
                import traceback
                quadro = next((q for q in reversed(traceback.extract_tb(erro.__traceback__))
                               if "/app/" in q.filename.replace("\\", "/")), None)
                onde = f" em {q_arquivo}:{quadro.lineno} ({quadro.name})" if quadro and (
                    q_arquivo := quadro.filename.replace("\\", "/").split("/app/")[-1]) else ""
                lead = await self.repo.lead(id_lead)
                await self._evento(lead.id_escritorio if lead else None, id_lead, None, "erro_no_turno",
                                   "critico", "lawchat",
                                   f"Erro inesperado ao processar o turno: {type(erro).__name__}: {str(erro)[:200]}{onde}.")

    async def aguardar_esperas(self) -> None:
        """Só para testes: espera todos os turnos agendados (e as notas em segundo plano) terminarem."""
        while tarefas := [t for t in [*self._esperas.values(), *self._fundo] if not t.done()]:
            await asyncio.gather(*tarefas, return_exceptions=True)

    @staticmethod
    async def _juntos(*aguardaveis: Any) -> list[Any]:
        """asyncio.gather que espera TODOS terminarem antes de subir o primeiro erro: nada fica rodando solto depois de
        uma falha (o desfazer do turno, por exemplo, só roda com as gravações paradas)."""
        resultados = await asyncio.gather(*aguardaveis, return_exceptions=True)
        for resultado in resultados:
            if isinstance(resultado, BaseException):
                raise resultado
        return list(resultados)

    @staticmethod
    async def _nada(valor: Any = None) -> Any:
        return valor

    def _em_segundo_plano(self, nome: str, passo: Any, escritorio: Escritorio, lead: Lead, id_turno: str | None) -> None:
        """Extra que não pode atrasar o lead nem derrubar nada (nota interna): roda como tarefa; a falha vira log e
        evento (_passo_seguro), nunca some calada. O desligamento (encerrar) espera estas tarefas também."""
        tarefa = asyncio.create_task(self._passo_seguro(nome, passo, escritorio, lead, id_turno))  # type: ignore[arg-type]
        self._fundo.add(tarefa)
        tarefa.add_done_callback(self._fundo.discard)

    # ------------------------------------------------------------------ turno
    # Reserva do lead no banco enquanto o turno roda: curta e renovada a cada RENOVAR_S pelo próprio turno. Se o
    # processo morrer (deploy, queda), ela vence em segundos e outro servidor retoma o lead.
    RESERVA_S = 90
    RENOVAR_S = 30.0
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
            if modo == "laboratorio":
                return await self._processar_na_vez(id_lead, modo)
            async with self._turnos_simultaneos:         # teto de turnos ao mesmo tempo (o banco tem 10 conexões)
                return await self._processar_na_vez(id_lead, modo)

    async def _processar_na_vez(self, id_lead: str, modo: str | None) -> cerebro.Saida | None:
        if modo != "laboratorio":
            # A reserva e a leitura do prazo vão juntas (uma ida ao banco de espera em vez de duas).
            reservou, falta = await self._juntos(self.repo.reservar_lead(id_lead, self.RESERVA_S),
                                                 self._falta_para_responder(id_lead))
            if not reservou:
                self._agendar(id_lead, 15)
                return None
            if falta > 1:
                # O lead ainda está escrevendo (a mensagem nova pode ter chegado por outro servidor): espera o prazo.
                await self.repo.liberar_lead(id_lead)
                self._agendar(id_lead, falta)
                return None
        saida: cerebro.Saida | None = None
        batimento: asyncio.Task[None] | None = None
        if modo != "laboratorio":
            self._reservados.add(id_lead)
            if getattr(self.repo, "renovar_reserva", None):
                batimento = asyncio.create_task(self._manter_reserva(id_lead))
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
            if batimento is not None:
                batimento.cancel()
            self._reservados.discard(id_lead)
            if modo != "laboratorio":
                _, restantes = await self._juntos(self.repo.liberar_lead(id_lead),
                                                  self.repo.mensagens_pendentes(id_lead))
                if not restantes and id_lead not in self._prazos:
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
                await self.repo.gravar_eventos(
                    id_escritorio=item["id_escritorio"], id_lead=item["id_lead"], id_turno=item["id_turno"], eventos=[{
                        "tipo": "turno_interrompido", "gravidade": "erro", "responsavel": "lawchat",
                        "descricao": self.texto_do_corte(item),
                        "detalhe": {k: item.get(k) for k in ("enviadas", "devolvidas", "novas")}}])
                # Sem nota no chat (26/11: "Parte da resposta não foi entregue" assustava): fica só em Erros.
            except Exception:
                log.exception("falha ao avisar o turno interrompido %s", item.get("id_turno"))

    @staticmethod
    def texto_do_corte(item: dict[str, Any]) -> str:
        """Texto do erro 'turno_interrompido' na tela de Erros: o que aconteceu, o que já saiu e o que a IA vai fazer."""
        partes = ["O servidor reiniciou (deploy ou queda) no meio da resposta da IA."]
        if item.get("enviadas", 1):
            partes.append("Parte da resposta já tinha saído e pode ter ficado pela metade: confira a conversa.")
        else:
            partes.append("Nenhuma mensagem da IA tinha saído: ela responde de novo agora, sozinha.")
        if item.get("novas"):
            partes.append(f"O lead mandou {item['novas']} mensagem(ns) nesse meio tempo: entram na resposta.")
        return " ".join(partes)

    async def _manter_reserva(self, id_lead: str) -> None:
        """Batimento do turno: renova a reserva do lead enquanto o turno roda (a IA pode levar minutos)."""
        while True:
            await asyncio.sleep(self.RENOVAR_S)
            await self._renovar_reserva(id_lead)

    async def encerrar(self, teto_s: float = 30.0) -> None:
        """Desligamento: espera os turnos e leituras de mídia em andamento terminarem (até `teto_s`) e cancela o resto.
        O que for cortado vira 'turno_interrompido' na varredura do próximo servidor."""
        vivas = [t for t in self._esperas.values() if not t.done()]
        vivas += [t for tarefas in self._midias.values() for t in tarefas if not t.done()]
        vivas += [t for t in self._fundo if not t.done()]
        if not vivas:
            await self._soltar_reservas()
            return
        feitas, restantes = await asyncio.wait(vivas, timeout=teto_s)
        for tarefa in restantes:
            tarefa.cancel()
        if restantes:
            await asyncio.gather(*restantes, return_exceptions=True)
            log.warning("desligamento: %d tarefa(s) de atendimento cortadas no meio", len(restantes))
        await self._soltar_reservas()

    async def _soltar_reservas(self) -> None:
        """Desligando: solta as reservas que este processo ainda segura, para o servidor novo retomar esses leads em
        segundos (e não esperar a reserva vencer). O turno cortado vira 'turno_interrompido' na varredura dele."""
        for id_lead in list(self._reservados):
            try:
                await self.repo.liberar_lead(id_lead)
                if await self.repo.mensagens_pendentes(id_lead):
                    await self.repo.marcar_resposta(id_lead, agora())
            except Exception:
                log.exception("desligamento: falha ao soltar a reserva do lead %s", id_lead)
        self._reservados.clear()

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
        """Um turno, medido: a duração de cada passo e as idas ao banco vão em resposta["tempos"] (app/tempos.py)."""
        _medicao, ficha = tempos.comecar()
        try:
            return await self._um_turno_medido(id_lead, modo, pode_descartar)
        finally:
            tempos.terminar(ficha)

    async def _um_turno_medido(self, id_lead: str, modo: str | None,
                               pode_descartar: bool) -> tuple[cerebro.Saida | None, bool]:
        with tempos.passo("esperar_midias"):
            await self._esperar_midias(id_lead)          # arquivo do lead lido antes de a IA responder
        with tempos.passo("carregar_contexto"):
            # Leituras independentes juntas: cada ida ao banco custa ~200 ms em produção.
            lead, pendentes = await self._juntos(self.repo.lead(id_lead), self.repo.mensagens_pendentes(id_lead))
            if not lead or not pendentes:
                return None, False
            escritorio, agente = await self._juntos(self.repo.escritorio(lead.id_escritorio),
                                                    self.repo.agente_do_canal(lead.id_canal))
            assert escritorio is not None
            historico: list[Any] | None = None
            if modo != "laboratorio":
                if await self._adiar_pela_midia(lead, agente, pendentes):
                    return None, False
                # Releitura das pendentes (textos lidos agora), reparo da etapa e o histórico do turno, juntos. O histórico
                # serve à conferência "a equipe falou por último" (as 20 últimas) e ao prompt (as 40).
                relidas, lead, historico = await self._juntos(
                    self.repo.mensagens_pendentes(id_lead), self._reparar_etapa(lead, agente), self.repo.historico(id_lead))
                pendentes = relidas or pendentes

            pausa_antes = lead.motivo_estado if lead.estado == "pausado" else None
            lead = await self._religar_se_venceu(lead)
        if pausa_antes == "humano_assumiu" and lead.estado == "ativo":
            # A pausa do atendente acabou e a IA volta sozinha: nota interna (segundo plano, não atrasa a resposta).
            self._em_segundo_plano("nota_ia_voltou", self._nota_interna(
                escritorio, lead, f"{lead.id}:nota:ia_voltou:{self._carimbo()}", self.NOTA_IA_VOLTOU), escritorio, lead, None)
        return await self._um_turno_decidir(escritorio, agente, lead, pendentes, historico, modo, pode_descartar)

    async def _um_turno_decidir(self, escritorio: Escritorio, agente: Agente | None, lead: Lead, pendentes: list[Any],
                                historico: list[Any] | None, modo: str | None,
                                pode_descartar: bool) -> tuple[cerebro.Saida | None, bool]:
        id_lead = lead.id
        if modo != "laboratorio" and lead.estado == "pausado" and lead.motivo_estado == "desativada_pela_equipe" \
                and lead.pausado_ate:
            # IA desligada pela equipe até um horário: a mensagem fica guardada e a IA responde quando o prazo acabar
            # (retomar_pendentes religa e agenda). Responder agora passaria por cima da equipe.
            await self._marcar_resposta(id_lead, lead.pausado_ate)
            await self._nota_ia_desativada(escritorio, agente, lead, modo)
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
                if not self._por_que_nao_atende(escritorio, agente, lead, etapa, modo):
                    # Uma nota por abertura (as mensagens seguintes até lá não repetem): a equipe sabe quando ela responde.
                    await self._nota_segura(escritorio, lead, f"{lead.id}:nota:fora_do_horario:{abre_em:%Y%m%d%H%M}",
                                            self.NOTA_FORA_DO_HORARIO.format(quando=self._quando(escritorio, abre_em)))
                return None, False
        if modo != "laboratorio" and lead.estado == "ativo" and not fora_do_horario \
                and await self._equipe_falou_por_ultimo(id_lead, pendentes, historico):
            fora_do_horario = "equipe_respondeu"     # guardadas na desativação e já respondidas pela equipe: silêncio
        abrir = self.repo.abrir_turno(lead=lead, modo=modo, etapa_antes=etapa.codigo if etapa else None)
        preparo: dict[str, Any] | None = None
        if self._por_que_nao_atende(escritorio, agente, lead, etapa, modo) or fora_do_horario:
            id_turno = await abrir                   # a IA não atende: nada mais a ler
        else:
            # Abre o turno e, junto, confere o saldo e lê o que o prompt precisa (fatos, ficha, base, contrato). Erro de
            # leitura fica guardado e sobe dentro do turno aberto (mesmo caminho de antes: turno fecha como 'erro').
            with tempos.passo("carregar_contexto"):
                assert agente is not None
                id_turno, preparo = await self._juntos(abrir, self._ler_para_o_turno(escritorio, agente, lead, historico))
        ids_lote = [m.id for m in pendentes]
        try:
            return await self._turno_aberto(escritorio, agente, lead, etapa, modo, fora_do_horario, pendentes, ids_lote,
                                            id_turno, pode_descartar, preparo=preparo)
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
            detalhe = detalhe_do_erro(erro)          # tipo, módulo, linha e status: a tela Execuções classifica
            await self.repo.gravar_eventos(id_escritorio=escritorio.id, id_lead=lead.id, id_turno=id_turno, eventos=[{
                "tipo": "erro_no_turno", "gravidade": "critico", "responsavel": "lawchat", "detalhe": detalhe,
                "descricao": f"Erro inesperado no turno da IA ({nome}). O lead ficou sem resposta."}])
            await self._nota_de_problema(escritorio, lead, "ia_nao_respondeu", f"erro interno: {nome}", inteiro=True)
        except Exception:
            log.exception("falha ao fechar o turno quebrado %s", id_turno)
        self._descartes.pop(lead.id, None)
        self._falhas_ia.pop(lead.id, None)

    async def _turno_aberto(self, escritorio: Escritorio, agente: Agente | None, lead: Lead, etapa: Any, modo: str,
                            fora_do_horario: str | None, pendentes: list[Any], ids_lote: list[str], id_turno: str,
                            pode_descartar: bool, preparo: dict[str, Any] | None = None
                            ) -> tuple[cerebro.Saida | None, bool]:
        id_lead = lead.id
        # Primeira conferência: a IA pode atender este lead?
        motivo = self._por_que_nao_atende(escritorio, agente, lead, etapa, modo) or fora_do_horario
        if not motivo:                               # vale também no modo teste: teste também gasta
            motivo = self._valor(preparo["consumo"]) if preparo else await self._conferir_consumo(escritorio)
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
                if not (motivo in self.SO_QUEM_ELA_ATENDERIA and self._fora_do_teste(escritorio, agente, lead)):
                    if motivo == "agente_pausado" and agente:
                        await self._nota_de_problema(escritorio, lead, motivo, agente.nome, inteiro=True)
                    else:
                        await self._nota_de_problema(escritorio, lead, motivo, motivo)
            elif motivo == "lead_pausado" and lead.motivo_estado == self.DESATIVADA_PELA_EQUIPE:
                await self._nota_ia_desativada(escritorio, agente, lead, modo)
            elif motivo == "horario_da_equipe":
                # Modo "só fora do horário": no horário quem atende é a equipe. Uma nota por conversa por dia.
                await self._nota_segura(escritorio, lead, f"{lead.id}:nota:horario_da_equipe:{self._dia(escritorio)}",
                                        self.NOTA_HORARIO_DA_EQUIPE)
            return None, False
        if modo != "laboratorio" and preparo:
            self._avisar_credito(escritorio, lead, preparo.get("credito"))
        assert agente is not None and etapa is not None

        with tempos.passo("carregar_contexto"):
            entrada = await self._montar_entrada(escritorio, agente, lead, etapa.codigo, pendentes, lidos=preparo)
        # Caderno das chamadas de IA do turno, fora do cérebro: se o teto do turno cortar no meio, as chamadas já pagas
        # (extrator, auditor...) ainda são gravadas e cobradas (antes sumiam junto com a tarefa cancelada).
        caderno = ModeloQueAnota(self.modelo)
        try:
            with tempos.passo("ia_total"):           # extrator + auditor + agente (+ correção), detalhados no cérebro
                saida = await asyncio.wait_for(cerebro.processar(caderno, entrada), timeout=self._teto_do_turno())
        except asyncio.TimeoutError:
            # A IA pendurou (conexão lenta): falha do modelo, pelo mesmo caminho das outras (evento e nota).
            saida = cerebro._falha(cerebro.Saida(etapa_antes=entrada.etapa, etapa_depois=entrada.etapa,
                                                 fatos_depois=dict(entrada.fatos)),
                                   "turno", ErroModelo("sem_conexao", f"a IA passou de {self._teto_do_turno():.0f} s"))
            saida.chamadas = list(caderno.chamadas) + list(saida.chamadas)
        pronta_em = asyncio.get_running_loop().time()      # a resposta existe: a pausa de digitação conta daqui
        with tempos.passo("conferencia"):
            await self._depois_da_busca(agente, entrada, saida)     # custo do embedding da consulta entra no consumo
            self._classificar_falha_da_ia(saida)
            if saida.situacao == "respondido" and not saida.mensagens and not saida.estado_lead:
                saida.eventos.append({"tipo": "resposta_vazia", "gravidade": "erro", "responsavel": "lawchat",
                                      "descricao": "A IA devolveu uma resposta vazia.", "detalhe": {}})
            # As chamadas pagas são gravadas junto da segunda conferência (chegou mensagem nova? o atendente assumiu? a
            # etapa mudou?): três idas ao banco ao mesmo tempo.
            _, agora_pendentes, lead_agora = await self._juntos(
                self.repo.gravar_chamadas(id_escritorio=escritorio.id, id_turno=id_turno, chamadas=saida.chamadas),
                self.repo.mensagens_pendentes(id_lead), self.repo.lead(id_lead))
        self._consumo.somar(escritorio.id, sum(c.custo_usd or 0 for c in saida.chamadas))

        if await self._tentar_de_novo_depois(escritorio, lead, id_turno, saida, modo):
            return None, False
        self._formato_invalido(entrada, saida)              # B3: fora do formato vira mensagem fixa + equipe

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
        with tempos.passo("gravacoes"):
            await self._juntos(self.repo.marcar_no_turno(ids_lote, id_turno),
                               self._limitar_trocas(entrada, lead, saida))   # B7: no máximo 4 trocas da IA por lead em 24 h
        if saida.estado_lead == "pausado":
            self._por_ficha(agente, entrada, saida)         # B2: ficha do caso em toda passagem para humano
        saida.contexto["partes_entregues"] = 0
        try:
            return await self._gravar_e_enviar(escritorio, agente, lead, etapa, modo, entrada, saida, id_turno,
                                               pronta_em=pronta_em)
        except Exception:
            if not saida.contexto.get("partes_entregues") and not saida.contexto.get("envio_feito"):
                await self._desfazer_turno(escritorio, lead, id_turno, saida)
            raise

    async def _gravar_e_enviar(self, escritorio: Escritorio, agente: Agente, lead: Lead, etapa: Any, modo: str,
                               entrada: cerebro.Entrada, saida: cerebro.Saida, id_turno: str,
                               pronta_em: float | None = None) -> tuple[cerebro.Saida | None, bool]:
        id_lead = lead.id
        self._guardar_link_de_avaliacao(agente, entrada, saida)   # link do Google: uma vez e nunca a desqualificado
        # Gravações antes do envio (fatos, troca de etapa, renovação da reserva) e as leituras do envio (canal, token),
        # todas juntas: elas correm enquanto a pausa de digitação da 1ª parte já conta (pronta_em). Uma falha em fatos ou
        # etapa ainda impede o envio (o turno é desfeito com tudo parado: _juntos espera todas terminarem).
        escritas: list[Any] = []
        if saida.fatos_novos:
            escritas.append(self.repo.gravar_fatos(lead=lead, id_turno=id_turno, fatos=saida.fatos_novos))
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
            escritas.append(self.repo.atualizar_lead(lead.id, id_etapa=campos.pop("id_etapa")))
            trocou_etapa = True
        else:
            trocou_etapa = False
        if not saida.mensagens:
            with tempos.passo("gravacoes"):
                await self._juntos(*escritas)
        if saida.estado_lead:
            campos.update(estado=saida.estado_lead, motivo_estado=saida.motivo_estado, pausado_ate=None)

        if saida.mensagens:
            # A frase de entrada de outro agente ("Maravilha!…") sai sempre sozinha, numa mensagem só dela.
            papeis_cfg = ((agente.config.get("catalogo") or {}).get("papeis") or {})
            saida.mensagens = formatador.isolar_frases(
                saida.mensagens, [str((c or {}).get("mensagem_troca") or "") for c in papeis_cfg.values() if isinstance(c, dict)])
            # Tamanho das mensagens escolhido no agente (Curtas/Médias/Longas/Uma só): reparte os textos nesse tamanho.
            tamanho = int(agente.config.get("caracteres_por_mensagem") or 0)
            if tamanho > 0:
                saida.mensagens = formatador.redividir(saida.mensagens, tamanho)
            # Teto de balões por turno (agente.config["max_baloes"], padrão 5): 9 balões de até 8 s parecem robô.
            # Com tamanho escolhido, juntar nunca passa desse tamanho (pode sobrar balão: conteúdo nunca é cortado).
            saida.mensagens = formatador.juntar_excedente(
                saida.mensagens, teto=int(agente.config.get("max_baloes") or formatador.TETO_DE_BALOES),
                limite=tamanho if tamanho > 0 else formatador.LIMITE_DO_BALAO_JUNTADO)
            if modo != "laboratorio" and getattr(self.repo, "renovar_reserva", None):
                escritas.append(self._renovar_reserva(id_lead))  # o envio (pausas de digitação) não deixa a reserva vencer
            de_verdade = modo != "laboratorio" and self.helena is not None
            with tempos.passo("gravacoes"):
                _, canal, token = await self._juntos(
                    self._juntos(*escritas), self.repo.canal(lead.id_canal),
                    self._token_helena(escritorio) if de_verdade else self._nada(None))
            # Canal e token já lidos e o instante da resposta pronta vão por fora da assinatura de _enviar (os testes
            # trocam _enviar por uma função com a assinatura antiga).
            self._preparo_do_envio[id_turno] = ((canal, token), pronta_em)
            if de_verdade and lead.id_sessao_helena and not any(m.get("autor") == "você" for m in entrada.historico):
                # Primeira resposta da IA a este lead: a nota "Atendimento iniciado" vai ANTES da 1ª parte (_enviar).
                self._nota_antes_do_envio[id_turno] = (f"{lead.id}:nota:atendimento_iniciado",
                                                       self._texto_atendimento_iniciado(escritorio, agente, entrada, saida))
            try:
                with tempos.passo("envio"):
                    completo, entregues = await self._enviar(escritorio, agente, lead, id_turno, saida, modo)
            finally:
                self._preparo_do_envio.pop(id_turno, None)
                self._nota_antes_do_envio.pop(id_turno, None)
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
        saida.contexto["envio_feito"] = True                 # daqui em diante o turno não é mais desfeito (B7)
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
        # Depois do envio: cada passo isolado (um que falha não impede os outros nem o fechamento do turno) e todos ao
        # mesmo tempo (antes, um atrás do outro: ~25 idas ao banco em fila). Continuam dentro do turno, com o lead
        # reservado: um follow-up agendado depois da próxima mensagem do lead (que cancela os follow-ups) seria errado.
        def seguro(nome: str, passo: Any) -> Any:
            return self._passo_seguro(nome, passo, escritorio, lead, id_turno)

        passos = [seguro("contrato", self._acoes_do_contrato(escritorio, agente, lead, id_turno, saida, modo)),
                  seguro("automacoes", self._automacoes(escritorio, agente, lead, id_turno, entrada, saida, modo))]
        parou_antes_de_tudo = bool(saida.contexto.get("envio_interrompido")) and not saida.contexto.get("partes_entregues")
        if saida.mensagens and modo != "laboratorio" and not parou_antes_de_tudo:
            # O relógio do follow-up começa na última resposta da IA (envio parado antes da 1ª parte: nada saiu).
            passos.append(seguro("followup", self.repo.agendar_followup(lead.id, agora())))
            # 20+ mensagens antigas fora da janela sem resumo: refaz a ficha pela fila (não atrasa nem derruba nada).
            passos.append(seguro("resumo", memoria.pedir_resumo_se_preciso(
                self.repo, id_escritorio=escritorio.id, id_lead=lead.id, id_turno=id_turno, comeco=entrada.comeco_conversa)))
        passos.append(seguro("lacuna", self._registrar_lacuna(escritorio, agente, lead, id_turno, saida)))
        notas = []
        for evento in saida.eventos:
            if self._automacao_ja_anota(agente, evento["tipo"], saida.etapa_depois):
                continue                                 # a nota configurada pelo escritório já vai: sem nota dobrada
            ficha_do_caso = saida.ficha if self._e_passagem(evento["tipo"]) else None
            notas.append((evento["tipo"], evento.get("descricao") or "", ficha_do_caso))

        async def eventos_e_notas() -> None:
            # Os eventos antes das notas: a nota repetida conta as ocorrências do problema na tabela de eventos.
            await seguro("eventos", self.repo.gravar_eventos(
                id_escritorio=escritorio.id, id_lead=lead.id, id_turno=id_turno, eventos=saida.eventos))
            await _em_paralelo(*(self._nota_de_problema(escritorio, lead, tipo, descricao, ficha=ficha)
                                 for tipo, descricao, ficha in notas))
        passos.append(eventos_e_notas())
        if modo != "laboratorio" and saida.contexto.get("partes_entregues") \
                and not any(m.get("autor") == "você" for m in entrada.historico):
            # Primeira resposta da IA a este lead (lead novo ou número de teste zerado): nota interna, uma vez por lead.
            passos.append(seguro("nota_atendimento_iniciado", self._nota_interna(
                escritorio, lead, f"{lead.id}:nota:atendimento_iniciado",
                self._texto_atendimento_iniciado(escritorio, agente, entrada, saida))))
        if modo != "laboratorio" and lead.id_sessao_helena:
            passos.append(seguro("nota_dados_contrato", self._nota_dados_contrato(escritorio, agente, lead, saida)))
        with tempos.passo("pos_envio"):
            await _em_paralelo(*passos)              # cada um já se protege; no máximo 3 ao mesmo tempo
        await self._fechar(id_turno, saida, saida.situacao, saida.motivo)
        return saida, False

    async def _renovar_reserva(self, id_lead: str) -> None:
        try:
            await self.repo.renovar_reserva(id_lead, self.RESERVA_S)     # type: ignore[attr-defined]
        except Exception:
            log.exception("falha ao renovar a reserva do lead %s", id_lead)

    # ------------------------------------------------------------------ notas internas do atendimento
    NOTA_ATENDIMENTO_INICIADO = "🤖 Atendimento iniciado pelo agente {agente} às {hora}"
    NOTA_PAUSA_HUMANO = "🙋 IA pausada: alguém da equipe entrou no atendimento. Ela volta a responder às {hora}"
    NOTA_PAUSA_HUMANO_SEM_VOLTA = "🙋 IA pausada: alguém da equipe entrou no atendimento. Ela só volta quando a equipe religar"
    NOTA_IA_VOLTOU = "🤖 IA voltou a atender"
    # Ponte para a equipe quando a IA recebeu a mensagem e não respondeu (ou algo relevante aconteceu sem nota).
    NOTA_FORA_DO_HORARIO = ("🌙 O lead escreveu fora do horário de atendimento da IA. A mensagem ficou guardada e ela "
                            "responde quando o escritório abrir, {quando}.")
    NOTA_HORARIO_DA_EQUIPE = ("👥 A IA não respondeu: neste horário quem atende é a equipe (a IA só atende fora do "
                              "horário do escritório). Responda manualmente.")
    NOTA_CREDITOS_ACABANDO = "⚠️ Créditos da IA acabando (restam {restam}). Recarregue para a IA não parar."
    NOTA_DESQUALIFICADO = "🚫 Lead desqualificado pela IA{motivo}. Se a equipe discordar, assuma a conversa."
    CREDITO_AVISAR_PCT = 20                      # restando isto ou menos, nota "créditos acabando" (1 por conversa por dia)
    DESATIVADA_PELA_EQUIPE = "desativada_pela_equipe"     # app.ia_controle.MOTIVO
    # Motivos cuja nota só faz sentido se a IA atenderia este número (agente em teste: só a lista de teste).
    SO_QUEM_ELA_ATENDERIA = ("agente_pausado", "ia_desligada_no_escritorio", "agente_sem_etapa")

    @staticmethod
    def _carimbo() -> str:
        return agora().strftime("%Y%m%d%H%M%S%f")

    @staticmethod
    def _local(escritorio: Escritorio, quando: datetime) -> datetime:
        from app.notificacoes import fuso
        return quando.astimezone(fuso(escritorio.config.get("fuso") or "America/Sao_Paulo"))

    def _dia(self, escritorio: Escritorio) -> str:
        return self._local(escritorio, agora()).strftime("%Y-%m-%d")

    def _quando(self, escritorio: Escritorio, quando: datetime) -> str:
        """'hoje às 08:00', 'amanhã às 08:00' ou '01/12 às 08:00' no fuso do escritório."""
        local, hoje = self._local(escritorio, quando), self._local(escritorio, agora()).date()
        dias = (local.date() - hoje).days
        dia = "hoje" if dias == 0 else "amanhã" if dias == 1 else local.strftime("%d/%m")
        return f"{dia} às {local:%H:%M}"

    async def _nota_segura(self, escritorio: Escritorio, lead: Lead, chave: str, texto: str) -> None:
        """Nota interna que nunca derruba o turno (a nota é um extra)."""
        try:
            await self._nota_interna(escritorio, lead, chave, texto)
        except Exception:
            log.exception("falha ao agendar a nota %s", chave)

    async def _nota_ia_desativada(self, escritorio: Escritorio, agente: Agente | None, lead: Lead,
                                  modo: str | None) -> None:
        """O lead escreveu com a IA desativada nesta conversa pela equipe. Sem nota se a equipe desativou (ou mexeu na
        IA desta conversa) há menos de 6 h (a nota DES-... está logo acima) e no máximo 1 a cada 6 h (_nota_de_problema).
        Número fora da lista de teste ou IA que não atenderia de qualquer jeito (agente pausado...): sem nota."""
        modo = modo or (agente.modo if agente else "teste")
        if modo == "laboratorio" or not lead.id_sessao_helena:
            return
        etapa = agente.etapa_por_id(lead.id_etapa) if agente else None
        if self._por_que_nao_atende(escritorio, agente, replace(lead, estado="ativo", motivo_estado=None), etapa, modo):
            return
        try:
            recente = getattr(self.repo, "nota_recente", None)
            if recente and await recente(lead.id, [f"{lead.id}:ia:%"], 6):
                return
        except Exception:
            log.exception("falha ao conferir as notas recentes do lead %s", lead.id)
            return
        if lead.pausado_ate:
            await self._nota_de_problema(escritorio, lead, "ia_desativada_ate", self._quando(escritorio, lead.pausado_ate),
                                         inteiro=True)
        else:
            await self._nota_de_problema(escritorio, lead, "ia_desativada", "", inteiro=True)

    @staticmethod
    def _motivo_da_nota(motivo: str | None) -> str:
        """Linha "Motivo:" das notas das automações. A troca de agente comum ("transferencia:closer", "catalogo") não
        leva motivo: a nota já diz para onde o lead foi, e o código cru ficava no chat da equipe em toda troca."""
        motivo = str(motivo or "").strip()
        if not motivo or motivo == "catalogo" or motivo.startswith("transferencia:"):
            return ""
        return f"Motivo: {motivo}"

    def _texto_desqualificado(self, agente: Agente, saida: cerebro.Saida) -> str:
        """Nota do lead desqualificado, com o motivo legível quando há (fato que desqualificou ou motivo do funil)."""
        motivo = ""
        try:
            if agente.produto == "catalogo":
                from app.cerebro import catalogo
                if achado := catalogo.motivo_de_desqualificar(agente.config, saida.fatos_depois or {}):
                    motivo = f"{achado[0]}: {achado[1]}"
            if not motivo:
                bruto = (saida.motivo_estado or "").partition(":")[2]
                motivo = "" if bruto in ("", "catalogo") or bruto.startswith("transferencia") else bruto
        except Exception:
            log.exception("falha ao ler o motivo da desqualificação")
        motivo = motivo.replace("_", " ").strip()
        return self.NOTA_DESQUALIFICADO.format(motivo=f" (motivo: {motivo})" if motivo else "")

    def _avisar_credito(self, escritorio: Escritorio, lead: Lead, restante: Any) -> None:
        """Créditos da IA acabando (pré-pago): nota no atendimento, uma vez por conversa por dia (segundo plano)."""
        if isinstance(restante, BaseException) or restante is None or restante > self.CREDITO_AVISAR_PCT:
            return
        restam = "menos de 1%" if restante < 1 else f"{int(restante)}%"
        self._em_segundo_plano("nota_creditos", self._nota_interna(
            escritorio, lead, f"{lead.id}:nota:creditos_acabando:{self._dia(escritorio)}",
            self.NOTA_CREDITOS_ACABANDO.format(restam=restam)), escritorio, lead, None)

    @staticmethod
    def _hora(escritorio: Escritorio, quando: datetime) -> str:
        """HH:MM no fuso do escritório (padrão: Brasília)."""
        from app.notificacoes import fuso
        return quando.astimezone(fuso(escritorio.config.get("fuso") or "America/Sao_Paulo")).strftime("%H:%M")

    def _texto_atendimento_iniciado(self, escritorio: Escritorio, agente: Agente, entrada: cerebro.Entrada,
                                    saida: cerebro.Saida) -> str:
        codigo = saida.etapa_antes or entrada.etapa
        if agente.produto == "catalogo":
            from app.cerebro import catalogo
            etapa = catalogo.NOMES.get(codigo, codigo)
        else:
            etapa = next((e.nome for e in getattr(entrada.produto, "etapas", []) if e.codigo == codigo), codigo)
        nome = f"{agente.nome} ({etapa})" if etapa and etapa != agente.nome else agente.nome
        return self.NOTA_ATENDIMENTO_INICIADO.format(agente=nome, hora=self._hora(escritorio, agora()))

    async def _nota_dados_contrato(self, escritorio: Escritorio, agente: Agente, lead: Lead, saida: cerebro.Saida) -> None:
        """O lead terminou de mandar os dados do contrato (todos os obrigatórios válidos): nota organizada no atendimento,
        uma vez por conjunto de dados (se ele corrigir algo, sai outra com o dado novo)."""
        from app.contrato import dados as cdados
        brutos = cdados.dados_dos_fatos(saida.fatos_depois or {})
        if not brutos.get("nome") or not brutos.get("cpf"):
            return
        dados, erros = cdados.validar_dados(brutos, lead.telefone, await self._obrigatorios_do_contrato(escritorio, agente))
        if erros:
            return
        await self._nota_interna(escritorio, lead, f"{lead.id}:nota:dados_contrato:{cdados.hash_dados(dados)[:16]}",
                                 cdados.nota_dos_dados(dados))

    async def _nota_interna(self, escritorio: Escritorio, lead: Lead, chave: str, texto: str) -> None:
        """Nota interna no atendimento da Helena, pela fila (mesmo caminho das notas de aviso): não gasta IA e a chave
        única impede a nota repetida. Sem atendimento aberto na Helena não há onde anotar."""
        if not lead.id_sessao_helena:
            return
        await self.repo.enfileirar_acoes(id_escritorio=escritorio.id, id_lead=lead.id, id_turno=None, acoes=[
            {"tipo": "nota", "chave_unica": chave, "dados": {"texto": texto}}])

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

    # ------------------------------------------------------------------ leva 1 (25/11): B2, B3 e B7
    # Erros de formato da resposta da IA (depois das tentativas do modelo): melhor uma pessoa do que silêncio.
    FORMATO_QUEBRADO = ("saida_invalida", "saida_cortada", "recusa_do_modelo")
    # Trocas de etapa feitas pela IA por lead em 24 h; a seguinte é segurada e a conversa vai para a equipe.
    LIMITE_TROCAS_IA_24H = 4
    # Eventos de passagem para humano: a nota deles leva a ficha do caso e o detalhe ganha o campo "ficha".
    PASSAGENS = ("pediu_humano", "trava_persistente", "pedido_repetido", "analise_manual", "contrato_correcao_repetida",
                 "formato_invalido", "trocas_demais", "fora_do_tema_repetido")

    @classmethod
    def _e_passagem(cls, tipo: str) -> bool:
        return tipo in cls.PASSAGENS or (tipo.startswith("sinal_") and tipo != "sinal_recusado")

    def _formato_invalido(self, entrada: cerebro.Entrada, saida: cerebro.Saida) -> None:
        """B3. A IA respondeu fora do formato (JSON inválido, cortado ou recusa) mesmo depois das tentativas: em vez de
        silêncio, o lead recebe a mensagem fixa e educada e a IA pausa neste lead, com a ficha para a equipe."""
        if saida.situacao != "erro" or saida.motivo.partition(":")[2] not in self.FORMATO_QUEBRADO:
            return
        original = saida.motivo
        detalhe = next((e.get("detalhe") for e in saida.eventos if e.get("tipo") == "ia_nao_respondeu"), None)
        saida.eventos = [e for e in saida.eventos if e.get("tipo") != "ia_nao_respondeu"]
        saida.situacao, saida.motivo = "respondido", "formato_invalido"
        saida.estado_lead, saida.motivo_estado = "pausado", "formato_invalido"
        saida.etapa_depois = saida.etapa_antes
        saida.mensagens = cerebro._fixa(entrada, "formato_invalido")
        saida.eventos.append({"tipo": "formato_invalido", "gravidade": "erro", "responsavel": "provedor",
                              "descricao": f"A IA respondeu fora do formato depois das tentativas ({original}); o lead "
                                           "recebeu a mensagem padrão e a conversa foi para a equipe.",
                              "detalhe": {"motivo": original, "erro": detalhe}})

    async def _limitar_trocas(self, entrada: cerebro.Entrada, lead: Lead, saida: cerebro.Saida) -> None:
        """B7. Pingue-pongue de etapa: com 4 trocas feitas pela IA neste lead nas últimas 24 h, a 5ª é segurada e a
        conversa vai para a equipe com a ficha (evento trocas_demais). Trocas da equipe e do contrato não contam."""
        if saida.etapa_depois == saida.etapa_antes or saida.estado_lead:
            return
        contar = getattr(self.repo, "trocas_da_ia", None)
        if contar is None:
            return
        try:
            feitas = await contar(lead.id, 24)
        except Exception:                                    # a contagem nunca derruba o turno
            log.exception("falha ao contar as trocas de etapa do lead %s", lead.id)
            return
        if feitas < self.LIMITE_TROCAS_IA_24H:
            return
        destino = saida.etapa_depois
        saida.etapa_depois = saida.etapa_antes
        saida.estado_lead, saida.motivo_estado = "pausado", "trocas_demais"
        saida.motivo = "trocas_demais"
        saida.mensagens = cerebro._fixa(entrada, "equipe_continua")
        saida.fatos_novos = [f for f in saida.fatos_novos if f.get("chave") != cerebro.MARCA_BOAS_VINDAS]
        saida.eventos.append({"tipo": "trocas_demais", "gravidade": "aviso", "responsavel": "lawchat",
                              "descricao": f"A IA já trocou este lead de etapa {feitas} vezes em 24 h; a troca "
                                           f"{saida.etapa_antes} → {destino} foi segurada e a conversa foi para a equipe.",
                              "detalhe": {"de": saida.etapa_antes, "para": destino, "trocas_24h": feitas}})

    def _por_ficha(self, agente: Agente, entrada: cerebro.Entrada, saida: cerebro.Saida) -> None:
        """B2. Ficha do caso na passagem para humano: vai em saida.ficha, no detalhe dos eventos de passagem ("ficha",
        para os avisos à equipe) e na nota da Helena."""
        from app import conhecimento
        from app.cerebro import catalogo, ficha

        try:
            produto = entrada.produto
            etapa = saida.etapa_depois or saida.etapa_antes
            faltando = list(saida.faltam)
            if agente.produto == "catalogo" and not faltando:
                faltando = catalogo.faltam_para_seguir(getattr(produto, "config", {}), etapa, saida.fatos_depois)
            nome_etapa = catalogo.NOMES.get(etapa, etapa) if agente.produto == "catalogo" else \
                next((e.nome for e in getattr(produto, "etapas", []) if e.codigo == etapa), etapa)
            # O nome do contato vem em fatos_do_sistema como "nome no WhatsApp" (não "nome"): sem isto a ficha dizia
            # "Lead: sem nome" em toda passagem para humano em que o lead não digitou o nome. O nome dito na conversa
            # (fato nome / nome_completo) continua valendo antes do nome do WhatsApp.
            sistema = entrada.fatos_sistema or {}
            do_whatsapp = str(sistema.get("nome") or sistema.get("nome no WhatsApp") or "").split(" (pode não ser")[0].strip()
            dito = (saida.fatos_depois or {}).get("nome_completo") or (saida.fatos_depois or {}).get("nome")
            lead = {"nome": None if dito else (do_whatsapp or None),
                    "beneficio": getattr(produto, "beneficio", None) or getattr(produto, "nome", None)}
            texto = ficha.montar_ficha(lead, saida.fatos_depois, nome_etapa, saida.motivo_estado,
                                       conhecimento.ultima_pergunta_da_ia(entrada.historico), faltando)
        except Exception:                                    # a ficha é um extra: nunca derruba a passagem
            log.exception("falha ao montar a ficha do caso")
            return
        saida.ficha = texto
        for evento in saida.eventos:
            if self._e_passagem(str(evento.get("tipo") or "")):
                evento.setdefault("detalhe", {})
                if isinstance(evento["detalhe"], dict):
                    evento["detalhe"]["ficha"] = texto

    async def _desfazer_turno(self, escritorio: Escritorio, lead: Lead, id_turno: str, saida: cerebro.Saida) -> None:
        """B7. O turno quebrou depois de gravar etapa/fatos e antes de qualquer mensagem chegar ao lead: a etapa volta
        e cada fato do turno devolve a vigência à versão anterior (uma transação no banco). Falha aqui só registra."""
        desfazer = getattr(self.repo, "desfazer_turno", None)
        if desfazer is None:
            return
        try:
            await desfazer(lead=lead, id_turno=id_turno, id_etapa=lead.id_etapa)
            await self._evento(escritorio.id, lead.id, id_turno, "turno_desfeito", "erro", "lawchat",
                               "O turno quebrou antes de qualquer mensagem chegar ao lead: a etapa e os fatos do turno "
                               "voltaram ao que eram.")
        except Exception:
            log.exception("falha ao desfazer o turno %s", id_turno)

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
                        "pediu_para_parar": ["pediu_para_parar"],
                        "analise_manual": [f"etapa:{etapa}" if etapa else "etapa:analise_manual"]}.get(tipo, [])
        return any((regras.get(g) or {}).get("nota") for g in gatilhos)

    async def _automacoes(self, escritorio: Escritorio, agente: Agente, lead: Lead, id_turno: str,
                          entrada: cerebro.Entrada, saida: cerebro.Saida, modo: str) -> None:
        """Quando isto acontecer, faça aquilo: põe na fila as ações configuradas no agente (CRM, nota...).

        Os "Avisos à equipe" (sinal de videochamada, não sabe ler...) valem mesmo sem automação nenhuma no agente:
        basta a função de avisos ligada. Cada gatilho gera no máximo um aviso por turno (montar_acoes)."""
        if modo == "laboratorio":
            return
        # Sem regras no agente, o CRM automático (colunas fixas da conta) ainda vale: montar_acoes decide.
        gatilhos = automacoes.gatilhos_do_turno(
            primeira_resposta=not any(m["autor"] == "você" for m in entrada.historico),
            etapa_antes=saida.etapa_antes, etapa_depois=saida.etapa_depois,
            motivo_estado=saida.motivo_estado, situacao=saida.situacao, sinais=saida.sinais,
            intencoes=saida.intencoes,
        )
        if not gatilhos:
            return
        config_crm, avisos = await self._juntos(self.repo.config_crm(escritorio.id),
                                                self.repo.eventos_com_aviso(escritorio.id))
        acoes = automacoes.montar_acoes(
            agente.config, config_crm, gatilhos,
            id_lead=lead.id, id_turno=id_turno, contexto=self._motivo_da_nota(saida.motivo), avisos=avisos,
        )
        if lead.id_sessao_helena and "desqualific" in (saida.etapa_depois or "") \
                and saida.etapa_depois != saida.etapa_antes and not any(a["tipo"] == "nota" for a in acoes):
            # Lead desqualificado sem nota de automação (a do CRM automático ou a configurada já explicam): ponte própria.
            acoes.append({"tipo": "nota", "chave_unica": f"{lead.id}:{id_turno}:nota:desqualificado",
                          "dados": {"texto": self._texto_desqualificado(agente, saida)}})
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
        # A cidade vem do CEP agora: a UF que já estava gravada não é do endereço (veio da naturalidade, "nasceu em
        # Montes Claros/MG"); vale a do CEP. Reteste BPC de 26/11: contrato com "São Paulo/MG".
        troca_uf = bool(vazio("cidade") and endereco.uf and normalizar_uf(fatos.get("uf")) not in (None, endereco.uf))
        return [{"chave": k, "valor": v, "trecho": trecho, "fonte": "sistema"} for k, v in novos.items()
                if v and (vazio(k) or (k == "uf" and troca_uf))] + [situacao]

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
        # Sem o código técnico no chat (o detalhe fica em Erros): a equipe só precisa saber o que fazer.
        "ia_nao_respondeu": "⚠️ A IA não conseguiu responder esta mensagem agora. O problema ficou registrado em Erros; "
                            "por favor, responda manualmente.",
        "envio_falhou": "📭 Uma mensagem da IA não chegou ao lead (o WhatsApp não entregou). Vale dar uma olhada na "
                        "conversa e reenviar, se fizer falta.",
        "midia_quebrada": "⚠️ A IA não enviou uma mídia do roteiro ({detalhe}). Se precisar, envie manualmente e "
                          "corrija o link no roteiro.",
        "envio_sem_confirmacao": "📭 O WhatsApp não confirmou a entrega de uma mensagem da IA. Vale conferir se ela "
                                 "chegou ao lead; se não chegou, envie manualmente.",
        "limite_de_consumo": "🚫 A IA não respondeu: o limite de consumo da IA deste mês acabou. Responda manualmente.",
        "sem_saldo": "⛔ A IA recebeu a mensagem mas não respondeu: os créditos da IA acabaram. Recarregue em Créditos "
                     "da IA para ela voltar a atender.",
        "agente_sem_etapa": "⚠️ A IA não respondeu: o agente deste número está sem etapa configurada. Responda manualmente.",
        "canal_sem_agente": "⚠️ A IA não respondeu: este número não tem agente ligado. Responda manualmente.",
        "sem_prompt": "⚠️ A IA não respondeu: a etapa em que este lead está não tem instruções no agente. Responda "
                      "manualmente; a configuração do agente precisa ser completada.",
        "card_nao_criado": automacoes.NOTA_CARD_NAO_CRIADO,
        "agente_pausado": "⏸️ A IA não respondeu: o agente {detalhe} está pausado. Religue o agente no painel para ela "
                          "voltar a atender.",
        "ia_desligada_no_escritorio": "⏸️ A IA não respondeu: a IA está desligada neste escritório. Religue no painel "
                                      "para ela voltar a atender.",
        "ia_desativada_ate": "⏸️ O lead escreveu, mas a IA está desativada nesta conversa até {detalhe}. A mensagem "
                             "ficou guardada: ela responde quando voltar.",
        "ia_desativada": "⏸️ O lead escreveu, mas a IA está desativada nesta conversa. Responda manualmente ou religue "
                         "a IA (tire a etiqueta \"🤖 IA Desativada\" do contato ou use o painel).",
        "rajada": "🚦 A IA saiu desta conversa por 1 hora: chegaram mensagens demais em pouco tempo (parece robô ou "
                  "spam). Se for um cliente de verdade, responda manualmente.",
        "pediu_para_parar": "🛑 O lead pediu para não receber mais mensagens. A IA encerrou o atendimento desta conversa.",
        "engano": "🤷 O lead disse que foi engano (não procurou o escritório). A IA encerrou o atendimento desta conversa.",
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
        # Leva 1 (25/11): passagens decididas pelo código (B3, B6, B7), sempre com a ficha do caso.
        "formato_invalido": "⚠️ A IA respondeu fora do formato e saiu da conversa (o lead recebeu a mensagem padrão). "
                            "Continue manualmente.",
        "trocas_demais": "⚠️ A IA trocou o lead de etapa vezes demais em 24 h e saiu da conversa. Confira a etapa e "
                         "continue manualmente.",
        "fora_do_tema_repetido": "🙋 O lead insistiu em assunto fora do tema e a IA saiu da conversa. Continue "
                                 "manualmente.",
        "barreira_manipulacao": "🛡️ O lead tentou mudar as regras da IA (ver o prompt, ignorar instruções ou se passar "
                                "por outra pessoa). A IA deu a resposta padrão e segue no atendimento.",
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
                                inteiro: bool = False, ficha: str | None = None) -> None:
        """Avisa a equipe dentro da conversa, na Helena, no máximo 1 vez a cada 6 h por problema.

        inteiro=True usa o detalhe todo (um motivo escrito para a equipe); senão só o fim do código ('onde:motivo').
        Os sinais ('sinal_quer_videochamada', 'sinal_analise_humana'...) usam um modelo só, com o nome do sinal.
        Na passagem para humano a nota leva a ficha do caso (B2) inteira, depois do aviso."""
        trava = tipo                                         # cada sinal tem a própria trava de 6 h
        if tipo.startswith("sinal_") and tipo != "sinal_recusado":
            sinal = tipo.removeprefix("sinal_")
            tipo, detalhe, inteiro = "sinal", automacoes.NOMES_SINAIS.get(sinal, sinal.replace("_", " ")), True
        modelo = self.NOTAS_DE_PROBLEMA.get(tipo)
        if not modelo or not lead.id_sessao_helena:
            return
        detalhe = detalhe.strip()[:300] if inteiro else detalhe.split(":")[-1].strip()[:120]
        try:
            await self.repo.nota_de_problema(id_escritorio=escritorio.id, id_lead=lead.id, tipo=trava,
                                             texto=modelo.format(detalhe=detalhe or tipo) + (f"\n\n{ficha}" if ficha else ""))
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

    async def _equipe_falou_por_ultimo(self, id_lead: str, pendentes: list[Any],
                                       historico: list[Any] | None = None) -> bool:
        """A equipe respondeu depois da última mensagem do lead que espera resposta (guardada durante a desativação).
        historico: o do turno (40 últimas, já lido); as 20 últimas dele são exatamente historico(id_lead, 20)."""
        ultima_do_lead = max((m.enviada_em for m in pendentes if m.enviada_em), default=None)
        if ultima_do_lead is None:
            return False
        if historico is not None:
            return any(m.autor == "humano" and m.enviada_em and m.enviada_em > ultima_do_lead for m in historico[-20:])
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

    async def _ler_base(self, agente: Agente) -> tuple[Any, Any]:
        """Trechos indexados e documentos ainda sem índice do agente, juntos."""
        trechos, sem_indice = await self._juntos(self.repo.trechos_do_agente(agente.id),
                                                 self.repo.documentos_do_agente(agente.id))
        return trechos, sem_indice

    async def _conhecimento(self, agente: Agente, pendentes: list[Any], historico: list[Any],
                            papel: str | None = None, lidos_base: Any = None) -> dict[str, Any]:
        """Base de conhecimento do turno (docs/BASE_DE_CONHECIMENTO.md): o que é pequeno fica fixo no sistema; a busca
        pela fala nova do lead começa aqui, como tarefa, e roda junto do extrator (o turno espera em "_busca")."""
        from app import conhecimento as base
        from app import conhecimento_indice as indice
        from app.cerebro.sinais import tem_audio_de_pedido

        config = dict(agente.config.get("conhecimento") or {})
        try:
            if lidos_base is None:
                lidos_base = await self._ler_base(agente)               # escopo: agente (= escritório + produto)
            if isinstance(lidos_base, BaseException):
                raise lidos_base
            trechos, sem_indice = lidos_base
            real = self.vetorizador is not None and not getattr(self.vetorizador, "falso", False)
            preparo = indice.preparar(config, papel, indexados=trechos, sem_indice=sem_indice,
                                      modelo_vetor=getattr(self.vetorizador, "modelo", None) if real else None)
            limites = indice.limites(config)
        except Exception:                            # noqa: BLE001 - a base nunca derruba o turno
            log.warning("base de conhecimento indisponível; turno segue com o conhecimento da config", exc_info=True)
            return {**{k: config[k] for k in ("dados_escritorio", "faq", "objecoes") if config.get(k)},
                    "_tem_audio_de_pedido": tem_audio_de_pedido(config)}
        ultima = base.ultima_pergunta_da_ia([{"autor": m.autor, "texto": m.para_a_ia()} for m in historico])
        busca = asyncio.create_task(indice.buscar(
            preparo.candidatos, [m.para_a_ia() for m in pendentes if m.para_a_ia()], papel=papel, ultima_pergunta_ia=ultima,
            vetorizador=self.vetorizador, cache=self._cache_consultas, minimo=limites["minimo"], teto=limites["teto"],
            quantos=limites["quantos"]))
        return {**preparo.fixo, "base": True, "_busca": busca, "_tem_audio_de_pedido": tem_audio_de_pedido(config)}

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

    async def _ler_para_o_turno(self, escritorio: Escritorio, agente: Agente, lead: Lead,
                                historico: list[Any] | None, consumo: bool = True) -> dict[str, Any]:
        """Tudo o que o turno lê do banco antes da IA, ao mesmo tempo (antes: ~9 idas em fila). Cada resultado pode ser
        a exceção da leitura: quem usa decide (_valor sobe o erro; a base cai no conhecimento da config, como antes)."""
        funcoes = agente.config.get("funcoes") or {}
        nomes = ("consumo", "historico", "fatos", "fatos_sistema", "comeco", "base", "obrigatorios", "credito")
        credito = getattr(self.repo, "credito_restante", None)
        resultados = await _em_paralelo(
            self._conferir_consumo(escritorio) if consumo else self._nada(None),
            self._nada(historico) if historico is not None else self.repo.historico(lead.id),
            self.repo.fatos_vigentes(lead.id),
            self.repo.fatos_do_sistema(lead.id),
            memoria.ler_comeco(self.repo, lead.id),
            self._ler_base(agente),
            self._obrigatorios_do_contrato(escritorio, agente) if funcoes.get("contrato_zapsign") else self._nada(None),
            credito(escritorio.id) if (consumo and credito) else self._nada(None),     # créditos acabando: nota
            return_exceptions=True)
        for resultado in resultados:
            if isinstance(resultado, asyncio.CancelledError):
                raise resultado
        return dict(zip(nomes, resultados))

    @staticmethod
    def _valor(resultado: Any) -> Any:
        if isinstance(resultado, BaseException):
            raise resultado
        return resultado

    async def _montar_entrada(self, escritorio: Escritorio, agente: Agente, lead: Lead,
                              etapa: str, pendentes: list[Any], lidos: dict[str, Any] | None = None) -> cerebro.Entrada:
        if lidos is None:
            lidos = await self._ler_para_o_turno(escritorio, agente, lead, None, consumo=False)
        historico = self._valor(lidos["historico"])
        modelos = agente.config.get("modelos", {})
        produto = produtos.carregar(agente.produto, agente.config)
        etapa_atual = agente.etapa(etapa)
        return cerebro.Entrada(
            escritorio=escritorio.nome,
            agente=agente.nome,
            etapa=etapa,
            novas=[m.para_a_ia() for m in pendentes if m.para_a_ia()] or ["(mensagem vazia)"],
            fatos=self._valor(lidos["fatos"]),
            historico=[{"autor": "você" if m.autor == "ia" else ("atendente" if m.autor == "humano" else m.autor),
                        "texto": m.para_a_ia()} for m in historico if m.para_a_ia()],
            instrucoes={e.codigo: e.instrucao for e in agente.etapas},
            honorarios=agente.config.get("honorarios") or escritorio.config.get("honorarios"),
            midias={chave: m.get("descricao", "") for chave, m in agente.config.get("midias", {}).items()},
            produto=produto,
            mensagens_fixas=agente.config.get("mensagens_fixas", {}),
            modelo_extrator=modelos.get("extrator") or self.config.modelo_padrao,
            conhecimento=await self._conhecimento(agente, pendentes, historico, papel=(
                etapa if agente.produto != "catalogo" or etapa in produto.papeis else produto.etapa_inicial()),
                lidos_base=lidos["base"]),
            fatos_sistema=self._valor(lidos["fatos_sistema"]),
            comeco_conversa=self._valor(lidos["comeco"]),
            temperatura=agente.config.get("temperatura") if agente.produto == "catalogo" else None,
            enriquecer=self._enriquecer_por_cep if (agente.config.get("funcoes") or {}).get("buscar_cep") else None,
            obrigatorios_contrato=self._valor(lidos["obrigatorios"])
                                  if (agente.config.get("funcoes") or {}).get("contrato_zapsign") else None,
            modelo_auditor=None if (self.config.modelo_falso or agente.config.get("auditor") is False)
                           else (modelos.get("auditor") or os.environ.get("AGENTESIA_MODELO_AUDITOR", "gpt-6-luna")),
            modelo_etapa=(etapa_atual.modelo if etapa_atual and etapa_atual.modelo else None)
                         or modelos.get("etapa") or self.config.modelo_padrao,
            esforco_etapa=modelos.get("esforco", "medium"),
        )

    async def _enviar(self, escritorio: Escritorio, agente: Agente, lead: Lead, id_turno: str,
                      saida: cerebro.Saida, modo: str, lidos: tuple[Any, str | None] | None = None,
                      pronta_em: float | None = None) -> tuple[bool, int]:
        """Envia cada parte. Uma parte que falha não para as outras. Devolve (completo, partes entregues); completo é False quando o envio parou porque
        o lead saiu da IA (atendente assumiu entre uma parte e outra).

        Token: só o do próprio escritório (integração e, como reserva, a coluna antiga; a mesma fonte do Executor e
        do follow-up). Sem token não há envio nem nota possível: evento de cadastro (vai para a central) e as partes
        ficam gravadas como 'falhou'. O token global do .env só vale no modo de laboratório (AGENTESIA_MODO_LAB=1).

        lidos: (canal, token) já lidos junto das gravações do turno. pronta_em: instante (relógio do loop) em que a
        resposta ficou pronta; a pausa de digitação da 1ª parte conta dali (o tempo das gravações entra nela)."""
        de_verdade = modo != "laboratorio" and self.helena is not None
        if lidos is None and id_turno in self._preparo_do_envio:
            lidos, pronta_em = self._preparo_do_envio[id_turno]
        if lidos is None:
            canal, token = await self._juntos(self.repo.canal(lead.id_canal),
                                              self._token_helena(escritorio) if de_verdade else self._nada(None))
        else:
            canal, token = lidos
        relogio = asyncio.get_running_loop()
        gravando: list[asyncio.Future[Any]] = []             # gravação de cada parte, enquanto a próxima "digita"
        primeira = [True]

        async def pausar(parte: dict[str, Any]) -> None:
            # Pausa de digitação. A da 1ª parte conta de quando a resposta ficou pronta: as gravações do turno já
            # gastaram parte dela (o lead não espera as duas coisas uma depois da outra).
            espera = float(parte.get("espera_s", 0))
            if primeira[0] and pronta_em is not None:
                espera = max(0.0, espera - (relogio.time() - pronta_em))
            primeira[0] = False
            await asyncio.sleep(espera)
        if de_verdade and not token:
            saida.eventos.append({"tipo": "escritorio_sem_token_helena", "gravidade": "erro", "responsavel": "cadastro",
                                  "descricao": "O escritório não tem a integração do WhatsApp cadastrada: a resposta da IA "
                                               "não foi enviada. Cadastre a integração no painel.", "detalhe": {}})
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
            if de_verdade and token and lead.id_sessao_helena:
                # Antes de CADA parte (a 1ª também: a IA pensou por segundos e as gravações correram) o atendente pode ter
                # assumido ou a equipe desligado a IA (no lead, no agente ou no escritório): a pausa de digitação
                # acontece primeiro e lead, agente e escritório são relidos frescos. As partes que faltam não são
                # gravadas como mensagem (o lead não as viu; situacao_envio não tem 'cancelada') e ficam no contexto.
                if self.digitar:
                    await pausar(parte)
                ja_esperou = True
                if motivo := await self._parar_o_envio(lead):
                    restantes = [p.get("texto") if p["tipo"] == "texto" else (p.get("url") or p.get("chave"))
                                 for p in partes[posicao:]]
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
                        await pausar(parte)
                    if id_turno in self._nota_antes_do_envio:
                        await self._nota_antes_da_primeira_parte(escritorio, lead, id_turno, token)
                    id_externo = await self.helena.enviar(           # type: ignore[union-attr]
                        token=token, id_sessao=lead.id_sessao_helena,
                        id_canal=canal.id_canal_helena if canal else None, texto=texto, url_arquivo=url,
                    )
                    tempos.marcar("primeira_parte_enviada")
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
                                "descricao": f"O WhatsApp não confirmou o envio de uma parte da resposta ({detalhe}); "
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
            # A gravação da parte corre enquanto a próxima parte "digita" (enviada_em é o de agora: a ordem fica certa).
            gravando.append(asyncio.ensure_future(self._gravar_parte(
                lead=lead, autor="ia", tipo="texto" if texto is not None else self.tipo_da_midia(url),
                texto=texto, texto_extraido=extraido,
                url_midia=url, enviada_em=agora(), id_externo=id_externo, id_turno=id_turno,
                situacao_envio=situacao, erro=erro,
            )))
            if situacao in ("enviada", "pendente"):           # 'pendente' = talvez enviada (sem confirmação)
                entregues += 1
                # B7: o turno que quebrar depois daqui não é desfeito (o lead já ouviu parte da resposta).
                saida.contexto["partes_entregues"] = int(saida.contexto.get("partes_entregues") or 0) + 1
            if id_externo:
                enviadas.append(id_externo)
                if url and self.digitar and posicao < len(partes) - 1:
                    # A Helena e o WhatsApp baixam o arquivo antes de entregar: sem esta pausa, o texto seguinte chegava
                    # antes do vídeo (o n8n esperava depois de cada envio e 10 s depois do vídeo de apresentação).
                    await asyncio.sleep(self._espera_depois_da_midia(url, parte, agente))
        if gravando:
            await asyncio.gather(*gravando)                  # cada uma já registra a própria falha
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

    VARIAVEL_LINK_AVALIACAO = "LINK AVALIACAO GOOGLE"

    def _guardar_link_de_avaliacao(self, agente: Agente, entrada: cerebro.Entrada, saida: cerebro.Saida) -> None:
        """O link de avaliação do Google (variável {{LINK AVALIACAO GOOGLE}} do agente) sai no máximo uma vez por
        conversa e nunca para quem foi desqualificado (nesta resposta ou antes). A linha com o link sai do balão; o
        balão que fica vazio sai da resposta. agente.config["avaliacao_google_ao_desqualificado"] = true libera o envio
        ao desqualificado (o padrão é bloquear)."""
        from app.cerebro import catalogo

        link = catalogo.valores_das_variaveis(None, None, None, agente.config).get(self.VARIAVEL_LINK_AVALIACAO, "")
        chave = self._chave_do_link(link)
        if len(chave) < 8 or not saida.mensagens:
            return
        com_link = [m for m in saida.mensagens if m.get("tipo") == "texto" and chave in self._chave_do_link(m.get("texto"))]
        if not com_link:
            return
        desqualificado = ("desqualificado" in (saida.etapa_antes, saida.etapa_depois, entrada.etapa)
                          and not agente.config.get("avaliacao_google_ao_desqualificado"))
        ja_enviado = any(m.get("autor") == "você" and chave in self._chave_do_link(m.get("texto"))
                         for m in entrada.historico)
        if not (desqualificado or ja_enviado):
            return
        mensagens: list[dict[str, Any]] = []
        for m in saida.mensagens:
            if m in com_link:
                linhas = [l for l in str(m.get("texto") or "").split("\n") if chave not in self._chave_do_link(l)]
                texto = "\n".join(linhas).strip()
                if not texto:
                    continue
                m = {**m, "texto": texto}
            mensagens.append(m)
        saida.mensagens = mensagens
        motivo = "lead desqualificado" if desqualificado else "o link já tinha sido enviado nesta conversa"
        saida.contexto["link_avaliacao_bloqueado"] = motivo
        saida.eventos.append({"tipo": "link_avaliacao_bloqueado", "gravidade": "info", "responsavel": "lawchat",
                              "descricao": f"O link de avaliação do Google saiu da resposta da IA ({motivo}).",
                              "detalhe": {"motivo": motivo}})

    @staticmethod
    def _chave_do_link(texto: Any) -> str:
        """Texto para comparar links: sem protocolo, sem www, sem barra final, em minúsculas."""
        return re.sub(r"https?://(www\.)?", "", str(texto or "").strip().lower()).rstrip("/")

    NOTA_ANTES_TETO_S = 4.0

    async def _nota_antes_da_primeira_parte(self, escritorio: Escritorio, lead: Lead, id_turno: str, token: str) -> None:
        """A nota "Atendimento iniciado" direto na Helena, logo antes da 1ª parte (pela fila ela chegava DEPOIS da
        mensagem). A chave da fila é reservada como 'feita' antes (nunca sai duas vezes); se a nota falhar ou passar de
        NOTA_ANTES_TETO_S, volta para a fila (sai depois, como antes) e o envio da resposta segue sem esperar."""
        chave, texto = self._nota_antes_do_envio.pop(id_turno)
        nota = getattr(self.helena, "nota", None)
        reservar = getattr(self.repo, "reservar_acao_feita", None)
        if nota is None or reservar is None:
            return                                       # sem nota direta: a nota vai pela fila depois do envio
        try:
            if not await reservar(id_escritorio=escritorio.id, id_lead=lead.id, tipo="nota", chave_unica=chave,
                                  dados={"texto": texto}):
                return                                   # já anotada (ou na fila) por outro turno
        except Exception:
            log.exception("falha ao reservar a nota de início do lead %s", lead.id)
            return
        try:
            await asyncio.wait_for(nota(token=token, id_sessao=lead.id_sessao_helena, texto=texto), self.NOTA_ANTES_TETO_S)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("nota de início direta falhou no lead %s: vai pela fila", lead.id, exc_info=True)
            try:
                await self.repo.devolver_acao_para_fila(chave)   # type: ignore[attr-defined]
            except Exception:
                log.exception("falha ao devolver a nota de início do lead %s para a fila", lead.id)

    async def _parar_o_envio(self, lead: Lead) -> str | None:
        """Motivo para parar o envio agora (lead saiu da IA, IA desligada no escritório, agente pausado), ou None.
        Leitura fresca (sem cache). Falha na leitura não para o envio (o turno já conferiu tudo antes da IA)."""
        try:
            if ler := getattr(self.repo, "situacao_para_enviar", None):
                atual = await ler(lead.id)
                if not atual:
                    return None
                estado, motivo_estado = atual.get("estado"), atual.get("motivo_estado")
                ia_desligada = bool(atual.get("ia_desligada")) or (atual.get("situacao_escritorio") or "ativo") != "ativo"
                agente_parado = (atual.get("situacao_agente") or "ativo") != "ativo"
            else:                                        # repositório sem a leitura junta
                atual_lead = await self.repo.lead(lead.id)
                if not atual_lead:
                    return None
                estado, motivo_estado = atual_lead.estado, atual_lead.motivo_estado
                ia_desligada = agente_parado = False
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("falha ao reler o lead %s antes de enviar uma parte", lead.id)
            return None
        if estado != "ativo":
            return motivo_estado or "humano_assumiu_durante_envio"
        if ia_desligada:
            return "ia_desligada_no_escritorio"
        if agente_parado:
            return "agente_pausado"
        return None

    async def _gravar_parte(self, **campos: Any) -> None:
        try:
            await self.repo.gravar_mensagem(**campos)
        except Exception:
            log.exception("falha ao gravar a parte enviada no turno %s", campos.get("id_turno"))

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

    # O WhatsApp baixa o arquivo antes de entregar: áudio e vídeo chegavam DEPOIS do texto seguinte (26/11: áudio de
    # 1:49 dos honorários chegou depois da pergunta "Conseguiu entender?"). Só depois de mídia, nunca depois do último.
    ESPERA_DEPOIS_DA_MIDIA_S = {"video": 12.0, "audio": 10.0, "imagem": 3.0}
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
            "estado_lead": saida.estado_lead, "motivo_estado": saida.motivo_estado, "ficha": saida.ficha,
        }
        if (medicao := tempos.atual()) is not None:
            resposta["tempos"] = medicao.como_dict()       # duração de cada passo e idas ao banco do turno
        await self.repo.fechar_turno(id_turno, situacao=situacao, motivo=motivo, etapa_depois=saida.etapa_depois,
                                     contexto=saida.contexto, resposta=resposta)

    async def _evento(self, id_escritorio: str | None, id_lead: str | None, id_turno: str | None,
                      tipo: str, gravidade: str, responsavel: str, descricao: str) -> None:
        await self.repo.gravar_eventos(
            id_escritorio=id_escritorio, id_lead=id_lead, id_turno=id_turno,
            eventos=[{"tipo": tipo, "gravidade": gravidade, "responsavel": responsavel,
                      "descricao": descricao, "detalhe": {}}],
        )
