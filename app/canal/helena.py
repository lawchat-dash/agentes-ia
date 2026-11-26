"""Canal Helena (wts.chat): lê o webhook e envia mensagens.

É o único arquivo que conhece o formato da Helena. O resto do sistema recebe um
`Evento` já classificado.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

TIPOS = {
    "TEXT": "texto", "AUDIO": "audio", "PTT": "audio", "VOICE": "audio", "IMAGE": "imagem",
    "VIDEO": "video", "DOCUMENT": "documento", "FILE": "documento", "STICKER": "figurinha",
    "LOCATION": "localizacao", "CONTACT": "contato", "CONTACTS": "contato",
}
IGNORADOS = {"TRANSITION", "NOTE"}

log = logging.getLogger("agentesia.helena")


@dataclass
class Evento:
    """O que aconteceu, já sem o formato da Helena."""

    classe: str                      # lead | humano | api | rastreio | status | ignorar
    id_externo: str | None = None    # id da mensagem na Helena
    id_conta: str | None = None      # companyId
    id_sessao: str | None = None
    numero_canal: str | None = None  # número do escritório, só dígitos
    numero_lead: str | None = None   # número do lead, só dígitos
    tipo: str = "texto"
    texto: str | None = None
    texto_extraido: str | None = None
    url_midia: str | None = None
    enviada_em: datetime | None = None
    motivo: str = ""                 # por que foi ignorado
    nome_contato: str | None = None  # nome do WhatsApp/Helena, quando o webhook traz
    origem: dict[str, Any] | None = None  # anúncio/UTM (app/origem.py)
    bruto: dict[str, Any] | None = None


def so_digitos(valor: Any) -> str:
    return re.sub(r"\D", "", str(valor or ""))


def normalizar_telefone(valor: Any) -> str | None:
    """Telefone brasileiro só com dígitos, com 55 e com o nono dígito do celular."""
    digitos = so_digitos(valor).lstrip("0")
    if not digitos:
        return None
    if len(digitos) in (10, 11):
        digitos = "55" + digitos
    if digitos.startswith("55") and len(digitos) == 12 and digitos[4] in "6789":
        digitos = digitos[:4] + "9" + digitos[4:]      # celular sem o nono dígito
    return digitos


def numero_do_lead(valor: Any) -> str | None:
    """Número do lead, ou None quando o WhatsApp não informou um telefone de verdade.

    '@lid' é o id de privacidade do WhatsApp (não é telefone): sem isso, '123456789012345@lid' virava um lead com
    telefone 123456789012345 (card, contrato e avisos com o número errado, e lead duplicado quando o número aparecesse).
    Não exige 55: lead estrangeiro vale. Só descarta o que não cabe em telefone: sem 55 e com mais de 13 dígitos."""
    bruto = str(valor or "").strip().lower()
    if not bruto or "@lid" in bruto:
        return None
    numero = normalizar_telefone(bruto)
    if not numero or (not numero.startswith("55") and len(numero) > 13) or len(numero) > 15:
        return None
    return numero


def telefone_do_contato(conteudo: dict[str, Any]) -> str | None:
    """Telefone do contato da conversa em campos que não são o from/to (que podem vir como '@lid'): contact.phonenumber
    (o mesmo que o filtro já lê) e contactDetails. Reserva para o WhatsApp que esconde o número no from."""
    for fonte in (conteudo.get("contact"), conteudo.get("contactDetails"), (conteudo.get("details") or {}).get("contactDetails")):
        if not isinstance(fonte, dict):
            continue
        for campo in ("phonenumber", "phoneNumber", "phone"):
            if numero := numero_do_lead(fonte.get(campo)):
                return numero
    return None


def id_contato_do_webhook(conteudo: dict[str, Any]) -> str | None:
    """Id do contato na Helena, quando o webhook traz (contactId ou contact.id)."""
    contato = conteudo.get("contact") if isinstance(conteudo.get("contact"), dict) else {}
    valor = conteudo.get("contactId") or contato.get("id") or (conteudo.get("details") or {}).get("contactId")
    return str(valor) if valor else None


def digitos_do_lid(conteudo: dict[str, Any]) -> str | None:
    """Os dígitos do '@lid' do from/to (dados antigos gravaram o lead com eles como telefone)."""
    detalhes = conteudo.get("details") or {}
    for valor in (detalhes.get("from"), detalhes.get("to")):
        if "@lid" in str(valor or "").lower() and (digitos := so_digitos(str(valor).split("@")[0])):
            return digitos
    return None


_AVISOS_DE_FORMATO: set[str] = set()


def _quando(valor: Any) -> datetime:
    """Hora da mensagem. Sem fuso não dá para saber se é UTC ou hora local: usa a hora de chegada (e avisa uma vez
    no log, com o valor bruto, para confirmar o formato da Helena). Supor UTC deixaria a IA muda se fosse hora local."""
    agora = datetime.now(timezone.utc)
    try:
        momento = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return agora
    if momento.tzinfo:
        return momento
    if "sem_fuso" not in _AVISOS_DE_FORMATO:
        _AVISOS_DE_FORMATO.add("sem_fuso")
        log.warning("timestamp da Helena sem fuso (%r): usando a hora de chegada", valor)
    return agora


def _transcricao(detalhes: dict[str, Any]) -> str:
    """Fala do áudio ou vídeo transcrita pela Helena. Só ruído ou silêncio (".", "Obrigado por assistir") conta como sem transcrição."""
    from app.midia.extrair import fala_vazia

    texto = ((detalhes.get("transcription") or {}).get("text") or "").strip()
    return "" if fala_vazia(texto) else texto


def _texto_para_a_ia(tipo: str, conteudo: dict[str, Any]) -> str | None:
    """Transforma mídia em texto que a IA entende. Texto simples devolve None."""
    detalhes = conteudo.get("details") or {}
    legenda = str(conteudo.get("text") or "").strip()
    transcricao = _transcricao(detalhes)
    if tipo == "texto":
        return None
    if tipo == "audio":
        return transcricao or "[O lead enviou um áudio que não foi possível ouvir. Peça com gentileza para ele escrever ou mandar de novo.]"
    if tipo == "video":
        base = f"[O lead enviou um vídeo. O que ele fala: {transcricao}]" if transcricao else \
            "[O lead enviou um vídeo que não dá para assistir. Se for importante, peça para ele contar por texto ou áudio.]"
        return base + (f"\n{legenda}" if legenda else "")
    if tipo == "imagem":
        return "[O lead enviou uma imagem que não foi possível ver.]" + (f"\nLegenda: {legenda}" if legenda else "")
    if tipo == "figurinha":
        return "[O lead enviou uma figurinha. Trate como reação, não como informação do caso.]"
    if tipo == "documento":
        nome = (detalhes.get("file") or {}).get("name") or ""
        return f"[O lead enviou um documento{f' ({nome})' if nome else ''}. Você não consegue abrir arquivos.]" + \
            (f"\n{legenda}" if legenda else "")
    if tipo == "localizacao":
        return "[O lead enviou uma localização.]"
    if tipo == "contato":
        return "[O lead enviou um contato.]"
    return legenda or "[O lead enviou uma mensagem que não pode ser lida.]"


PREFIXO_DO_ATENDENTE = re.compile(r"^\*[^:*\n]+:\*\s*")     # a Helena assina a fala: "*Paula:* Olá"


def _sem_assinatura(texto: str | None) -> str | None:
    """Tira o "*Nome do atendente:*" do começo do que o atendente escreveu."""
    if not texto:
        return texto
    return PREFIXO_DO_ATENDENTE.sub("", texto, count=1).strip() or None


def _texto_do_atendente(tipo: str, conteudo: dict[str, Any], legenda: str | None) -> str | None:
    """Mídia que o atendente mandou vira um marcador para a IA saber o que a equipe falou. Texto simples devolve None."""
    detalhes = conteudo.get("details") or {}
    transcricao = _transcricao(detalhes)
    extra = f"\n{legenda}" if legenda else ""
    if tipo == "texto":
        return None
    if tipo == "audio":
        return transcricao or "[O atendente enviou um áudio ao lead.]"
    if tipo == "video":
        return "[O atendente enviou um vídeo ao lead.]" + extra
    if tipo == "imagem":
        return "[O atendente enviou uma imagem ao lead.]" + extra
    if tipo == "documento":
        nome = (detalhes.get("file") or {}).get("name") or ""
        return f"[O atendente enviou um documento{f' ({nome})' if nome else ''} ao lead.]" + extra
    if tipo == "figurinha":
        return "[O atendente enviou uma figurinha ao lead.]"
    if tipo == "localizacao":
        return "[O atendente enviou uma localização ao lead.]"
    if tipo == "contato":
        return "[O atendente enviou um contato ao lead.]"
    return legenda or "[O atendente enviou uma mensagem que não pode ser lida.]"


def ler_webhook(corpo: dict[str, Any]) -> Evento:
    """Classifica o webhook da Helena.

    Lead falou:       MESSAGE_RECEIVED, direção FROM_HUB.
    Atendente falou:  direção TO_HUB, origem DEFAULT ou GATEWAY.
    Enviado por API:  direção TO_HUB, origem API (a própria IA ou outra integração;
                      quem separa as duas é o id da mensagem, no pipeline).
    """
    evento_tipo = str(corpo.get("eventType") or "").upper()
    conteudo = corpo.get("content") or {}
    tipo_bruto = str(conteudo.get("type") or "TEXT").upper()
    detalhes = conteudo.get("details") or {}

    if evento_tipo == "TRACK" or tipo_bruto == "TRACK":
        # Anúncio: o lead é quem clicou (from), o canal é o número do escritório (to).
        from app.origem import ler_origem
        return Evento("rastreio", id_externo="track:" + str(conteudo.get("id") or conteudo.get("sessionId") or ""), id_conta=conteudo.get("companyId"),
                      id_sessao=conteudo.get("sessionId"), numero_lead=numero_do_lead(detalhes.get("from")) or telefone_do_contato(conteudo),
                      numero_canal=normalizar_telefone(detalhes.get("to")), origem=ler_origem(conteudo),
                      nome_contato=_nome_do_contato(conteudo, detalhes), bruto=corpo)
    if tipo_bruto in IGNORADOS:
        return Evento("ignorar", motivo=f"tipo {tipo_bruto}", bruto=corpo)
    if not evento_tipo.startswith("MESSAGE"):
        return Evento("ignorar", motivo=f"evento {evento_tipo or 'vazio'}", bruto=corpo)
    if evento_tipo not in ("MESSAGE_RECEIVED", "MESSAGE_SENT"):
        return Evento("status", id_externo=conteudo.get("id"), motivo=evento_tipo, bruto=corpo)

    direcao = str(conteudo.get("direction") or "").upper()
    origem = str(conteudo.get("origin") or "").upper()
    tipo = TIPOS.get(tipo_bruto, "texto")
    do_lead = direcao == "FROM_HUB"
    # Mensagem do lead: from = lead, to = canal. Mensagem enviada: o contrário.
    numero_lead = detalhes.get("from") if do_lead else detalhes.get("to")
    numero_canal = detalhes.get("to") if do_lead else detalhes.get("from")

    if do_lead:
        classe = "lead"
    elif origem in ("DEFAULT", "GATEWAY"):
        classe = "humano"
    elif origem == "API":
        classe = "api"
    else:
        return Evento("ignorar", motivo=f"origem {origem or 'vazia'}", bruto=corpo)

    texto = str(conteudo.get("text")).strip() if conteudo.get("text") else None
    if classe == "humano":
        texto = _sem_assinatura(texto)
        texto_extraido = _texto_do_atendente(tipo, conteudo, texto)
    else:
        texto_extraido = _texto_para_a_ia(tipo, conteudo) if do_lead else None
    if do_lead and tipo_bruto not in TIPOS:
        # Tipo novo ou não mapeado (nota de vídeo redonda, enquete, botão...): fica 'texto' no banco (o CHECK da
        # coluna não aceita outro), mas a IA recebe o que houve em vez de '(mensagem vazia)'.
        log.info("tipo de mensagem desconhecido da Helena: %s", tipo_bruto)
        texto_extraido = texto or (f"[O lead enviou uma mensagem do tipo {tipo_bruto.lower()} que não pode ser lida. "
                                   "Se parecer importante, peça para ele explicar por texto.]")
    return Evento(
        classe=classe,
        id_externo=conteudo.get("id"),
        id_conta=conteudo.get("companyId"),
        id_sessao=conteudo.get("sessionId"),
        numero_canal=normalizar_telefone(numero_canal),
        numero_lead=numero_do_lead(numero_lead) or telefone_do_contato(conteudo),
        tipo=tipo,
        texto=texto,
        texto_extraido=texto_extraido,
        url_midia=(detalhes.get("file") or {}).get("publicUrl"),
        enviada_em=_quando(conteudo.get("timestamp") or conteudo.get("createdAt")),
        nome_contato=_nome_do_contato(conteudo, detalhes) if do_lead else None,
        origem=_origem(conteudo) if do_lead else None,
        bruto=corpo,
    )


def _origem(conteudo: dict[str, Any]) -> dict[str, Any] | None:
    from app.origem import ler_origem
    return ler_origem(conteudo)


def _nome_do_contato(conteudo: dict[str, Any], detalhes: dict[str, Any]) -> str | None:
    """O campo do nome não é documentado no evento da Helena: tenta os nomes mais prováveis."""
    contato = conteudo.get("contact") if isinstance(conteudo.get("contact"), dict) else {}
    for valor in (contato.get("name"), contato.get("nameWhatsapp"), conteudo.get("contactName"), detalhes.get("contactName"),
                  detalhes.get("senderName"), detalhes.get("pushName"), detalhes.get("name")):
        texto = str(valor or "").strip()
        if texto and not texto.replace("+", "").replace(" ", "").isdigit():
            return texto[:120]
    return None


class ErroHelena(Exception):
    pass


# Pedido que com certeza não chegou à Helena: repetir é seguro.
_NAO_CHEGOU = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)


def _autorizacao(token: str) -> str:
    return token if token.lower().startswith("bearer ") else f"Bearer {token}"


class ClienteHelena:
    """Envio de mensagens pela Helena, com até três tentativas por mensagem.

    Só repete o que com certeza não foi aceito (conexão recusada, 429 e os 5xx da própria API: 500, 503...), com pausa
    entre as tentativas (no 429, o Retry-After da Helena, limitado). Timeout de leitura depois de enviado e 502/504 (do
    proxy: o backend pode ter gravado) NÃO repetem: a Helena pode já ter aceitado, e repetir mandaria a mesma frase duas
    ou três vezes ao lead (vira 'sem_confirmacao': o turno trata como talvez enviada e pede conferência)."""

    TALVEZ_ACEITO = (502, 504)

    def __init__(self, url_base: str, http: httpx.AsyncClient | None = None, pausa_s: float = 2.5,
                 pausa_429_s: float = 5.0, pausa_maxima_s: float = 10.0) -> None:
        self._url = url_base.rstrip("/")
        self._http = http or httpx.AsyncClient(timeout=30)
        self._pausa_s = pausa_s
        self._pausa_429_s = pausa_429_s
        self._pausa_maxima_s = pausa_maxima_s
        self._pausa = None                       # testes trocam por um falso; None = asyncio.sleep

    async def fechar(self) -> None:
        await self._http.aclose()

    def _espera_do_429(self, resposta: httpx.Response) -> float:
        try:
            pedida = float(resposta.headers.get("Retry-After", ""))
        except ValueError:
            pedida = self._pausa_429_s
        # Nunca menos que a pausa padrão do 429 (a Helena conta 200 chamadas a cada 5 s), nunca mais que o teto.
        return max(0.0, min(max(pedida, self._pausa_429_s), self._pausa_maxima_s))

    async def enviar(
        self, *, token: str, id_sessao: str, id_canal: str | None,
        texto: str | None = None, url_arquivo: str | None = None,
    ) -> str | None:
        """Envia texto ou arquivo no atendimento. Devolve o id da mensagem criada."""
        corpo: dict[str, Any] = {"text": texto} if texto is not None else {"fileUrl": url_arquivo}
        if id_canal:
            corpo["channelId"] = id_canal
        ultimo_erro = ""
        tentativas = 3
        for tentativa in range(tentativas):
            espera = self._pausa_s
            try:
                resposta = await self._http.post(
                    f"{self._url}/chat/v1/session/{id_sessao}/message",
                    json=corpo, headers={"Authorization": _autorizacao(token), "Accept": "application/json"},
                )
            except _NAO_CHEGOU as erro:
                ultimo_erro = type(erro).__name__
            except httpx.HTTPError as erro:
                # ReadTimeout, WriteTimeout, conexão caída no meio: a Helena pode ter recebido. Não repete.
                raise ErroHelena(f"sem_confirmacao ({type(erro).__name__})") from erro
            else:
                if resposta.status_code < 300:
                    try:
                        dados = resposta.json()
                    except ValueError:
                        return None
                    # Corpo inesperado (lista, texto): o envio foi aceito, só não há id para guardar.
                    return dados.get("id") if isinstance(dados, dict) else None
                ultimo_erro = f"HTTP {resposta.status_code}"
                if resposta.status_code in self.TALVEZ_ACEITO:
                    # 502/504 vêm do proxy na frente da Helena: o backend pode já ter gravado e enfileirado a mensagem.
                    raise ErroHelena(f"sem_confirmacao (HTTP {resposta.status_code})")
                if resposta.status_code < 500 and resposta.status_code != 429:
                    break                      # erro do pedido: repetir não resolve
                if resposta.status_code == 429:
                    espera = self._espera_do_429(resposta)
            if tentativa < tentativas - 1 and espera > 0:
                await (self._pausa or asyncio.sleep)(espera)
        raise ErroHelena(ultimo_erro)
