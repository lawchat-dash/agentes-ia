"""Tira texto de arquivo (antigo fluxo n8n "WEAVER - Arquivos Transcrição PDF").

Decide o formato pelos primeiros bytes; o MIME e o nome são só dica. Funções síncronas (CPU):
quem chama usa asyncio.to_thread.
"""

from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree

LIMITE_XML = 10 * 1024 * 1024          # protege contra zip bomba
LIMITE_PAGINAS = 50
LIMITE_LINHAS = 500

MAGICOS: tuple[tuple[bytes, str], ...] = (
    (b"%PDF", "pdf"), (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "doc"), (b"\xff\xd8\xff", "imagem"),
    (b"\x89PNG", "imagem"), (b"GIF8", "imagem"), (b"OggS", "audio"), (b"ID3", "audio"), (b"fLaC", "audio"),
)


class ErroArquivo(Exception):
    def __init__(self, codigo: str, detalhe: str = "") -> None:
        super().__init__(detalhe or codigo)
        self.codigo = codigo


def detectar_formato(dados: bytes, mime: str | None = None, nome: str | None = None) -> str:
    """'pdf' | 'docx' | 'xlsx' | 'doc' | 'texto' | 'imagem' | 'audio' | 'desconhecido'."""
    inicio = dados[:16]
    for magico, formato in MAGICOS:
        if inicio.startswith(magico):
            return formato
    if inicio[:4] == b"RIFF" and dados[8:12] in (b"WEBP", b"WAVE"):
        return "imagem" if dados[8:12] == b"WEBP" else "audio"
    if dados[4:8] == b"ftyp":
        # Contêiner MP4: áudio com a marca M4A ou quando o MIME diz que é áudio (gravador do celular grava isom/mp42).
        return "audio" if b"M4A" in dados[8:16] or (mime or "").strip().lower().startswith("audio/") else "desconhecido"
    if inicio.startswith(b"PK"):
        try:
            with zipfile.ZipFile(io.BytesIO(dados)) as z:
                nomes = set(z.namelist())
        except zipfile.BadZipFile:
            return "desconhecido"
        if "word/document.xml" in nomes:
            return "docx"
        if any(n.startswith("xl/worksheets/") for n in nomes):
            return "xlsx"
        return "desconhecido"
    mime = (mime or "").split(";")[0].strip().lower()
    if mime.startswith("image/"):
        return "imagem"
    if mime.startswith("audio/"):
        return "audio"
    if mime in ("text/plain", "text/markdown", "text/csv", "application/json") or (nome or "").lower().endswith(
            (".txt", ".md", ".markdown", ".csv", ".json")):
        return "texto"                               # texto declarado: o decodificador trata UTF-8 e Windows-1252
    amostra = dados[:4096]
    try:
        amostra.decode("utf-8")
        return "texto"
    except UnicodeDecodeError as erro:
        # Corte dos 4096 bytes no meio de um caractere acentuado (ç = 2 bytes) não faz o texto virar binário.
        if len(dados) > len(amostra) and erro.start >= len(amostra) - 3 and erro.reason == "unexpected end of data":
            return "texto"
        return "desconhecido"


def nome_para_transcricao(dados: bytes, video: bool = False) -> str:
    """Nome do arquivo para a transcrição, pelos primeiros bytes: a OpenAI decide o formato pela extensão do nome, e o
    nome que a Helena manda ('audio.opus', 'audio.oga', sem extensão) derrubava a transcrição com 400."""
    inicio = dados[:16]
    if inicio.startswith(b"OggS"):
        return "audio.ogg"
    if inicio.startswith(b"ID3") or inicio[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "audio.mp3"
    if dados[4:8] == b"ftyp":
        return "video.mp4" if video else "audio.m4a"
    if inicio[:4] == b"RIFF" and dados[8:12] == b"WAVE":
        return "audio.wav"
    if inicio.startswith(b"\x1aE\xdf\xa3"):
        return "video.webm" if video else "audio.webm"
    if inicio.startswith(b"fLaC"):
        return "audio.flac"
    return "video.mp4" if video else "audio.ogg"


def mime_da_imagem(dados: bytes) -> str | None:
    """MIME da imagem pelos bytes (só os formatos que a visão aceita: jpeg, png, webp, gif). None = outro (HEIC...)."""
    if dados.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if dados.startswith(b"\x89PNG"):
        return "image/png"
    if dados.startswith(b"GIF8"):
        return "image/gif"
    if dados[:4] == b"RIFF" and dados[8:12] == b"WEBP":
        return "image/webp"
    return None


# Frases que o transcritor "ouve" no silêncio ou no ruído (alucinação típica do whisper): lista curta e fixa.
_ALUCINACOES = ("legendas pela comunidade amara org", "obrigado por assistir", "obrigada por assistir",
                "inscreva se no canal", "legenda adriana zanotto")


def fala_vazia(texto: str | None) -> bool:
    """Transcrição sem fala de verdade: menos de 2 letras ou números, ou só uma frase de alucinação do transcritor."""
    texto = texto or ""
    if sum(c.isalnum() for c in texto) < 2:
        return True
    normal = " ".join(re.sub(r"[^\w]+", " ", texto.lower()).split())
    return normal in _ALUCINACOES


def limpar(texto: str) -> str:
    texto = texto.replace("\r\n", "\n").replace("\r", "\n").replace("﻿", "").replace("\xa0", " ")
    texto = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", texto)
    texto = re.sub(r"[ \t]+\n", "\n", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


_MARCAS_MOJIBAKE = ("Ã", "Â", "â€", "Íμ")


def corrigir_mojibake(texto: str) -> str:
    """Conserta 'Ã§Ã£o' (UTF-8 lido como Windows-1252). Só mexe se houver marcas e se o conserto melhorar."""
    if not any(m in texto for m in _MARCAS_MOJIBAKE):
        return texto
    try:
        consertado = texto.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        consertado = texto
        for errado, certo in (("Ã§", "ç"), ("Ã£", "ã"), ("Ã¡", "á"), ("Ã©", "é"), ("Ãª", "ê"), ("Ã³", "ó"), ("Ãµ", "õ"),
                              ("Ãº", "ú"), ("Ã­", "í"), ("Ã¢", "â"), ("Ã´", "ô"), ("Ã ", "à"), ("Ã‡", "Ç"), ("Ã‰", "É"),
                              ("Ã“", "Ó"), ("Ãƒ", "Ã"), ("Íμ", "õ"), ("â€™", "’"), ("â€œ", "“"), ("â€¢", "•"),
                              ("â€¦", "…"), ("Â", "")):
            consertado = consertado.replace(errado, certo)
    return consertado if sum(consertado.count(m) for m in _MARCAS_MOJIBAKE) < sum(texto.count(m) for m in _MARCAS_MOJIBAKE) else texto


def decodificar_texto(dados: bytes) -> str:
    if dados.startswith(b"\xef\xbb\xbf"):
        return dados[3:].decode("utf-8", errors="replace")
    if dados.startswith((b"\xff\xfe", b"\xfe\xff")):
        return dados.decode("utf-16", errors="replace")
    try:
        return dados.decode("utf-8")
    except UnicodeDecodeError:
        return dados.decode("cp1252", errors="replace")


def _ler_do_zip(z: zipfile.ZipFile, nome: str) -> bytes:
    info = z.getinfo(nome)
    if info.file_size > LIMITE_XML:
        raise ErroArquivo("grande_demais", f"{nome} descompactado passa de {LIMITE_XML // 1_048_576} MB")
    return z.read(nome)


def extrair_docx(dados: bytes) -> str:
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(io.BytesIO(dados)) as z:
        raiz = ElementTree.fromstring(_ler_do_zip(z, "word/document.xml"))
    linhas = []
    for paragrafo in raiz.iter(w + "p"):
        partes = []
        for no in paragrafo.iter():
            if no.tag == w + "t" and no.text:
                partes.append(no.text)
            elif no.tag == w + "tab":
                partes.append("\t")
            elif no.tag in (w + "br", w + "cr"):
                partes.append("\n")
        linhas.append("".join(partes))
    return limpar(corrigir_mojibake("\n".join(linhas)))


def extrair_xlsx(dados: bytes) -> str:
    """Primeira planilha, linha a linha: 'CABEÇALHO: valor', linhas separadas por linha em branco."""
    s = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with zipfile.ZipFile(io.BytesIO(dados)) as z:
        nomes = z.namelist()
        compartilhadas: list[str] = []
        if "xl/sharedStrings.xml" in nomes:
            for item in ElementTree.fromstring(_ler_do_zip(z, "xl/sharedStrings.xml")).iter(s + "si"):
                compartilhadas.append("".join(t.text or "" for t in item.iter(s + "t")))
        planilhas = sorted(n for n in nomes if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
        if not planilhas:
            raise ErroArquivo("sem_texto", "planilha vazia")
        folha = ElementTree.fromstring(_ler_do_zip(z, planilhas[0]))
    linhas: list[list[str]] = []
    for linha in folha.iter(s + "row"):
        valores = []
        for celula in linha.iter(s + "c"):
            v = celula.find(s + "v")
            texto = "".join(t.text or "" for t in celula.iter(s + "t")) if celula.get("t") == "inlineStr" else (v.text if v is not None else "")
            if celula.get("t") == "s" and texto:
                texto = compartilhadas[int(texto)] if int(texto) < len(compartilhadas) else ""
            valores.append((texto or "").strip())
        linhas.append(valores)
        if len(linhas) > LIMITE_LINHAS:
            break
    if not linhas:
        raise ErroArquivo("sem_texto", "planilha vazia")
    cabecalho, corpo = linhas[0], linhas[1:]
    blocos = []
    for valores in corpo:
        pares = [f"{(cabecalho[i] if i < len(cabecalho) and cabecalho[i] else f'COLUNA {i + 1}').upper()}: {v}"
                 for i, v in enumerate(valores) if v]
        if pares:
            blocos.append("\n".join(pares))
    return limpar("\n\n".join(blocos) or " | ".join(cabecalho))


def extrair_pdf(dados: bytes) -> str:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        leitor = PdfReader(io.BytesIO(dados))
        if leitor.is_encrypted:
            try:
                leitor.decrypt("")
            except Exception as erro:
                raise ErroArquivo("protegido", "PDF com senha") from erro
        paginas = [p.extract_text() or "" for p in leitor.pages[:LIMITE_PAGINAS]]
    except PdfReadError as erro:
        raise ErroArquivo("corrompido", str(erro)) from erro
    return limpar(corrigir_mojibake("\n\n".join(paginas)))


def extrair_texto(dados: bytes, formato: str) -> str:
    """Texto do arquivo. Lança ErroArquivo('formato_nao_suportado' | 'sem_texto' | ...)."""
    try:
        if formato == "pdf":
            texto = extrair_pdf(dados)
        elif formato == "docx":
            texto = extrair_docx(dados)
        elif formato == "xlsx":
            texto = extrair_xlsx(dados)
        elif formato == "texto":
            texto = limpar(corrigir_mojibake(decodificar_texto(dados)))
        else:
            raise ErroArquivo("formato_nao_suportado", formato)
    except (zipfile.BadZipFile, ElementTree.ParseError, KeyError) as erro:
        raise ErroArquivo("corrompido", str(erro)) from erro
    if len(texto) < 3:
        raise ErroArquivo("sem_texto", "o arquivo não tem texto (PDF escaneado ou imagem)")
    return texto
