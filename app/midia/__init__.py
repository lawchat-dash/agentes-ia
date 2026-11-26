"""Mídia que o lead manda (documento, imagem, áudio) vira texto para a IA.

Ponto único: `tratar_midia`. Nunca levanta exceção: falha vira um texto de aviso, para a IA pedir de novo.
O resultado vai para agentesia_mensagens.texto_extraido da própria mensagem.

- Documento (PDF, DOCX, XLSX, TXT): extrai o texto; acima de CORTE_RESUMO caracteres, resume.
- Imagem: baixa e descreve com modelo de visão (bytes em data URL); foto mandada "como documento" também.
- Áudio: usa a transcrição da Helena; sem ela, transcreve. Transcrição sem fala vira o aviso de "não foi possível ouvir".
- Vídeo: baixa e transcreve a fala (como o n8n). PDF escaneado: lido pelo modelo com visão, quando houver.
- `quem` = 'o atendente': a mesma leitura para a mídia que a equipe mandou ao lead (só os marcadores mudam).
"""

from __future__ import annotations

import asyncio
import base64
import ipaddress
from dataclasses import dataclass, field
from typing import Awaitable, Callable
from urllib.parse import urlparse

import httpx

from app.midia.extrair import (ErroArquivo, detectar_formato, extrair_texto, fala_vazia, mime_da_imagem,
                               nome_para_transcricao)
from app.modelo import Chamada, ErroModelo, Modelo

LIMITE_BYTES = 20 * 1024 * 1024
LIMITE_VIDEO = 20 * 1024 * 1024          # vídeo do lead para transcrever a fala (o limite de arquivo da OpenAI é 25 MB)
LIMITE_PDF_VISAO = 10 * 1024 * 1024      # PDF escaneado lido pelo modelo com visão
CORTE_RESUMO = 2000
MAX_ENTRADA_RESUMO = 120_000

PROMPT_RESUMO = """Você resume documentos que um lead mandou pelo WhatsApp para um escritório de advocacia previdenciária.
Pode ser laudo médico, CAT, carta ou extrato do INSS (CNIS), processo judicial (PJe), contracheque, receita ou outro.

Diga primeiro que documento é. Depois, em frases curtas, o que importa para o caso previdenciário:
datas (dd/mm/aaaa), benefício (espécie e número, se houver), situação (concedido, negado, cessado),
CID e lesão, nexo com acidente ou trabalho, conclusão de perícia, valores, e o que está pendente.
Se for processo: número, vara, partes, pedido, perícia, decisão e situação atual.

Regras: até 1800 caracteres; não invente; se algo estiver ilegível, escreva "não identificado";
não copie CPF, RG, endereço completo nem dados bancários."""

ESQUEMA_RESUMO = {"type": "object", "additionalProperties": False,
                  "properties": {"resumo": {"type": "string"}}, "required": ["resumo"]}

# (url, mime, legenda) -> (texto, chamada). Injetado para teste; None = não descreve imagem.
DescreverImagem = Callable[[str, str | None, str | None], Awaitable[tuple[str, Chamada]]]
TranscreverAudio = Callable[[bytes, str], Awaitable[tuple[str, Chamada]]]
LerPdf = Callable[[bytes], Awaitable[tuple[str, Chamada]]]          # PDF escaneado -> resumo pelo modelo com visão


@dataclass
class ResultadoMidia:
    texto: str                              # o que vai para texto_extraido
    formato: str                            # pdf, docx, xlsx, texto, imagem, audio, desconhecido
    resumido: bool = False
    erro: str | None = None                 # link_expirado, grande_demais, sem_texto, formato_nao_suportado...
    chamadas: list[Chamada] = field(default_factory=list)


class ErroMidia(Exception):
    def __init__(self, codigo: str, detalhe: str = "") -> None:
        super().__init__(detalhe or codigo)
        self.codigo = codigo


def url_permitida(url: str) -> bool:
    """Só https para fora: nada de localhost, IP interno ou outro esquema (a URL vem de terceiros)."""
    partes = urlparse(url or "")
    if partes.scheme != "https" or not partes.hostname:
        return False
    host = partes.hostname.lower()
    if host in ("localhost",) or host.endswith((".local", ".internal")):
        return False
    try:
        ip = ipaddress.ip_address(host)
        return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved)
    except ValueError:
        return True


async def baixar(url: str, http: httpx.AsyncClient, *, limite: int = LIMITE_BYTES, tentativas: int = 2) -> bytes:
    """GET da URL inteira (URL assinada não pode ser remontada), em pedaços, parando acima do limite."""
    if not url_permitida(url):
        raise ErroMidia("url_recusada", "endereço do arquivo não permitido")
    ultimo = "download"
    for tentativa in range(tentativas):
        try:
            async with http.stream("GET", url, follow_redirects=True, timeout=30) as resposta:
                if resposta.status_code in (401, 403, 404, 410):
                    raise ErroMidia("link_expirado", f"HTTP {resposta.status_code}")
                if resposta.status_code == 429 or resposta.status_code >= 500:
                    ultimo = f"HTTP {resposta.status_code}"
                    await asyncio.sleep(1 + tentativa)
                    continue
                resposta.raise_for_status()
                partes, total = [], 0
                async for pedaco in resposta.aiter_bytes():
                    total += len(pedaco)
                    if total > limite:
                        raise ErroMidia("grande_demais", f"arquivo passa de {limite // 1_048_576} MB")
                    partes.append(pedaco)
                return b"".join(partes)
        except httpx.HTTPError as erro:
            ultimo = type(erro).__name__
            await asyncio.sleep(1 + tentativa)
    raise ErroMidia("download", ultimo)


async def resumir(modelo: Modelo, texto: str, nome_modelo: str) -> tuple[str, list[Chamada]]:
    resultado = await modelo.gerar(papel="resumo_documento", sistema=PROMPT_RESUMO,
                                   conteudo=texto[:MAX_ENTRADA_RESUMO], esquema=ESQUEMA_RESUMO,
                                   modelo=nome_modelo, esforco="low")
    return str(resultado.dados.get("resumo") or "").strip()[:2200], resultado.chamadas


def _rotulo(nome: str | None) -> str:
    return f' "{nome}"' if nome else ""


@dataclass
class _Quem:
    """De quem é a mídia: 'o lead' (o que ele mandou) ou 'o atendente' (o que a equipe mandou ao lead)."""
    quem: str

    @property
    def sujeito(self) -> str:                 # "O lead" / "O atendente"
        return self.quem[:1].upper() + self.quem[1:]

    @property
    def lead(self) -> bool:
        return self.quem == "o lead"

    def sufixo(self, legenda: str | None) -> str:
        return f"\nLegenda do {self.quem.split()[-1]}: {legenda}" if legenda else ""

    def audio_sem_fala(self) -> str:
        if self.lead:
            return "[O lead enviou um áudio que não foi possível ouvir. Peça com gentileza para ele escrever ou mandar de novo.]"
        return f"[{self.sujeito} enviou um áudio ao lead.]"

    def audio_com_fala(self, texto: str) -> str:
        # A fala do lead vai como ele disse (como a transcrição da Helena); a do atendente leva a marca de quem falou.
        return texto if self.lead else f"[{self.sujeito} enviou um áudio. O que ele disse: {texto}]"

    def video_sem_fala(self, legenda: str | None) -> str:
        extra = f"\n{legenda}" if legenda else ""
        if self.lead:                          # o mesmo texto fixo do webhook (app/canal/helena.py)
            return ("[O lead enviou um vídeo que não dá para assistir. Se for importante, peça para ele contar por texto "
                    "ou áudio.]" + extra)
        return f"[{self.sujeito} enviou um vídeo ao lead.]" + extra

    def imagem_sem_ver(self, legenda: str | None) -> str:
        if self.lead:
            return ("[O lead enviou uma imagem que não foi possível ver. Se for documento, peça uma foto nítida ou o PDF.]"
                    + self.sufixo(legenda))
        return f"[{self.sujeito} enviou uma imagem ao lead.]" + self.sufixo(legenda)


def _data_url(dados: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(dados).decode()}"


async def tratar_midia(*, tipo: str, url: str | None, mime: str | None, nome: str | None, legenda: str | None,
                       transcricao_helena: str | None, http: httpx.AsyncClient, modelo: Modelo,
                       nome_modelo: str = "gpt-4.1-mini", descrever_imagem: DescreverImagem | None = None,
                       transcrever_audio: TranscreverAudio | None = None, ler_pdf: LerPdf | None = None,
                       quem: str = "o lead") -> ResultadoMidia:
    """Mídia vira texto para a IA. `quem`: 'o lead' ou 'o atendente' (só muda os marcadores)."""
    autor = _Quem(quem)
    sufixo = autor.sufixo(legenda)
    if tipo == "audio" and transcricao_helena:
        if fala_vazia(transcricao_helena):
            return ResultadoMidia(autor.audio_sem_fala(), "audio", erro="transcricao_vazia")
        return ResultadoMidia(autor.audio_com_fala(transcricao_helena.strip()), "audio")
    if not url:
        return ResultadoMidia(f"[{autor.sujeito} enviou um arquivo{_rotulo(nome)} que não chegou. Peça para mandar de novo.]{sufixo}",
                              "desconhecido", erro="sem_url")
    if tipo == "video":
        return await _video(autor, url, legenda, http, transcrever_audio)

    try:
        dados = await baixar(url, http)
    except ErroMidia as erro:
        if tipo == "imagem" and descrever_imagem and erro.codigo in ("link_expirado", "download"):
            # O nosso download falhou: a visão ainda tenta pela URL (como era antes de baixar aqui).
            return await _descrever(autor, url, mime, legenda, descrever_imagem)
        if tipo == "imagem":
            return ResultadoMidia(autor.imagem_sem_ver(legenda), "imagem", erro=erro.codigo)
        if tipo == "audio":
            return ResultadoMidia(autor.audio_sem_fala(), "audio", erro=erro.codigo)
        texto = (f"[{autor.sujeito} enviou um arquivo{_rotulo(nome)}, mas o link expirou. Peça para mandar de novo.]"
                 if erro.codigo == "link_expirado" else
                 f"[{autor.sujeito} enviou um arquivo{_rotulo(nome)} grande demais para abrir. Peça só as páginas importantes ou fotos.]"
                 if erro.codigo == "grande_demais" else
                 f"[{autor.sujeito} enviou um arquivo{_rotulo(nome)} que não foi possível baixar. Peça para mandar de novo.]")
        return ResultadoMidia(texto + sufixo, "desconhecido", erro=erro.codigo)

    formato = detectar_formato(dados, mime, nome)
    if formato == "imagem" or tipo == "imagem":
        # Imagem (ou foto mandada "como documento"): a visão recebe os bytes em data URL, sem depender do CDN da Helena.
        mime_real = mime_da_imagem(dados) if formato == "imagem" else None
        if mime_real and descrever_imagem:
            return await _descrever(autor, _data_url(dados, mime_real), mime_real, legenda, descrever_imagem,
                                    nome=nome if tipo == "documento" else None)
        if tipo == "imagem":                                  # HEIC e outros formatos que a visão não lê
            return ResultadoMidia(autor.imagem_sem_ver(legenda), "imagem", erro="formato_nao_suportado")
    if (formato == "audio" or tipo == "audio") and transcrever_audio:
        # O nome vai pelos bytes (a extensão da Helena derrubava a transcrição); um áudio em MP4 (isom/mp42) também tenta.
        try:
            texto, chamada = await transcrever_audio(dados, nome_para_transcricao(dados))
        except ErroModelo as erro:
            return ResultadoMidia(autor.audio_sem_fala(), "audio", erro=erro.motivo)
        if fala_vazia(texto):
            return ResultadoMidia(autor.audio_sem_fala(), "audio", erro="transcricao_vazia", chamadas=[chamada])
        return ResultadoMidia(autor.audio_com_fala(texto.strip()), "audio", chamadas=[chamada])
    if tipo == "audio":
        return ResultadoMidia(autor.audio_sem_fala(), "audio", erro="formato_nao_suportado")
    if formato in ("imagem", "audio", "doc", "desconhecido"):
        quais = {"doc": "um documento do Word antigo (.doc)", "imagem": "uma imagem", "audio": "um áudio"}.get(formato, "um arquivo")
        return ResultadoMidia(f"[{autor.sujeito} enviou {quais}{_rotulo(nome)} que não dá para abrir. Peça em PDF, foto ou que ele conte o que diz.]{sufixo}",
                              formato, erro="formato_nao_suportado")
    try:
        texto = await asyncio.to_thread(extrair_texto, dados, formato)
    except ErroArquivo as erro:
        pagas: list[Chamada] = []             # leitura pela visão que voltou vazia ou falhou também foi paga
        if erro.codigo == "sem_texto" and formato == "pdf" and ler_pdf and len(dados) <= LIMITE_PDF_VISAO:
            # PDF escaneado (laudo, CAT, carta do INSS): o modelo com visão lê as páginas.
            try:
                lido, chamada = await ler_pdf(dados)
                pagas = [chamada]
            except ErroModelo as falha:
                lido, pagas = "", list(getattr(falha, "chamadas", []))
            if lido.strip():
                return ResultadoMidia(f"[{autor.sujeito} enviou o documento{_rotulo(nome)} (escaneado). Resumo do conteúdo "
                                      f"(lido pelo sistema):]\n{lido.strip()[:2200]}{sufixo}", formato, resumido=True,
                                      chamadas=pagas)
        motivo = "PDF escaneado ou sem texto" if erro.codigo == "sem_texto" else "arquivo protegido ou com defeito"
        return ResultadoMidia(f"[{autor.sujeito} enviou o documento{_rotulo(nome)}, mas não foi possível ler ({motivo}). "
                              f"Peça para ele contar o que diz ou mandar foto legível.]{sufixo}", formato, erro=erro.codigo,
                              chamadas=pagas)
    if len(texto) < CORTE_RESUMO:
        return ResultadoMidia(f"[{autor.sujeito} enviou o documento{_rotulo(nome)}. Conteúdo:]\n{texto}{sufixo}", formato)
    try:
        resumo, chamadas = await resumir(modelo, texto, nome_modelo)
        return ResultadoMidia(f"[{autor.sujeito} enviou o documento{_rotulo(nome)}. Resumo do conteúdo (feito pelo sistema):]\n{resumo}{sufixo}",
                              formato, resumido=True, chamadas=chamadas)
    except ErroModelo as erro:
        # As tentativas do resumo que falharam (saída inválida, cortada) também foram pagas: vão junto para gravar.
        return ResultadoMidia(f"[{autor.sujeito} enviou o documento{_rotulo(nome)}. Começo do conteúdo:]\n{texto[:CORTE_RESUMO]}…{sufixo}",
                              formato, erro=erro.motivo, chamadas=list(getattr(erro, "chamadas", [])))


async def _descrever(autor: _Quem, url: str, mime: str | None, legenda: str | None, descrever_imagem: DescreverImagem,
                     nome: str | None = None) -> ResultadoMidia:
    """Imagem descrita pela visão. `url`: data URL com os bytes (o normal) ou a URL da Helena (reserva)."""
    try:
        if not url.startswith("data:") and not url_permitida(url):
            raise ErroMidia("url_recusada")
        descricao, chamada = await descrever_imagem(url, mime, legenda)
    except (ErroMidia, ErroModelo) as erro:
        return ResultadoMidia(autor.imagem_sem_ver(legenda), "imagem",
                              erro=getattr(erro, "codigo", None) or getattr(erro, "motivo", "visao"))
    como = f"{_rotulo(nome)} como documento" if nome else ""
    return ResultadoMidia(f"[{autor.sujeito} enviou uma imagem{como}. O que dá para ver:]\n{descricao}{autor.sufixo(legenda)}",
                          "imagem", chamadas=[chamada])


async def _video(autor: _Quem, url: str, legenda: str | None, http: httpx.AsyncClient,
                 transcrever_audio: TranscreverAudio | None) -> ResultadoMidia:
    """Vídeo: baixa (até 20 MB) e transcreve a fala, como o n8n fazia. Sem fala ou com falha, fica o texto fixo."""
    if transcrever_audio is None:
        return ResultadoMidia(autor.video_sem_fala(legenda), "video", erro="sem_transcritor")
    try:
        dados = await baixar(url, http, limite=LIMITE_VIDEO)
        texto, chamada = await transcrever_audio(dados, nome_para_transcricao(dados, video=True))
    except ErroMidia as erro:
        return ResultadoMidia(autor.video_sem_fala(legenda), "video", erro=erro.codigo)
    except ErroModelo as erro:
        return ResultadoMidia(autor.video_sem_fala(legenda), "video", erro=erro.motivo)
    if fala_vazia(texto):
        return ResultadoMidia(autor.video_sem_fala(legenda), "video", erro="transcricao_vazia", chamadas=[chamada])
    return ResultadoMidia(f"[{autor.sujeito} enviou um vídeo. O que ele fala no vídeo: {texto.strip()}]{autor.sufixo(legenda)}",
                          "video", chamadas=[chamada])
