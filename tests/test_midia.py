"""Leitura dos arquivos que o lead manda (antigo fluxo "Arquivos Transcrição PDF"). Arquivos sintéticos."""

import io
import zipfile

import httpx
import pytest

from app import midia
from app.midia import extrair
from app.modelo import Chamada, ModeloFalso


def docx(paragrafos: list[str]) -> bytes:
    corpo = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragrafos)
    xml = ('<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/'
           f'wordprocessingml/2006/main"><w:body>{corpo}</w:body></w:document>')
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", xml)
    return saida.getvalue()


def xlsx(linhas: list[list[str]]) -> bytes:
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    textos = sorted({v for linha in linhas for v in linha})
    indice = {t: i for i, t in enumerate(textos)}
    compartilhadas = f'<sst xmlns="{ns}">' + "".join(f"<si><t>{t}</t></si>" for t in textos) + "</sst>"
    corpo = "".join("<row>" + "".join(f'<c t="s"><v>{indice[v]}</v></c>' for v in linha) + "</row>" for linha in linhas)
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w") as z:
        z.writestr("xl/sharedStrings.xml", compartilhadas)
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{ns}"><sheetData>{corpo}</sheetData></worksheet>')
    return saida.getvalue()


def pdf(texto: str) -> bytes:
    """PDF mínimo de uma página com texto (sem acento: fonte padrão)."""
    conteudo = f"BT /F1 12 Tf 72 720 Td ({texto}) Tj ET".encode()
    objetos = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
               b"<< /Length " + str(len(conteudo)).encode() + b" >>stream\n" + conteudo + b"\nendstream",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    saida, posicoes = io.BytesIO(), []
    saida.write(b"%PDF-1.4\n")
    for i, obj in enumerate(objetos, 1):
        posicoes.append(saida.tell())
        saida.write(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = saida.tell()
    saida.write(f"xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n".encode())
    for p in posicoes:
        saida.write(f"{p:010d} 00000 n \n".encode())
    saida.write(f"trailer << /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    return saida.getvalue()


def test_formato_pelos_bytes_e_nao_pelo_mime():
    assert extrair.detectar_formato(docx(["oi"]), "text/plain", "x.txt") == "docx"
    assert extrair.detectar_formato(xlsx([["a"]]), None, None) == "xlsx"
    assert extrair.detectar_formato(pdf("oi"), "application/octet-stream", None) == "pdf"
    assert extrair.detectar_formato(b"\x89PNG\r\n\x1a\n....", None, None) == "imagem"
    assert extrair.detectar_formato("olá".encode("cp1252"), "text/plain", None) == "texto"


def test_extracoes():
    assert extrair.extrair_texto(docx(["Laudo médico", "CID S82 — fratura"]), "docx") == "Laudo médico\nCID S82 — fratura"
    planilha = extrair.extrair_texto(xlsx([["Data", "Benefício"], ["01/02/2024", "B91"]]), "xlsx")
    assert planilha == "DATA: 01/02/2024\nBENEFÍCIO: B91"
    assert "Comunicacao de acidente" in extrair.extrair_texto(pdf("Comunicacao de acidente"), "pdf")
    assert extrair.extrair_texto("Açúcar e ação".encode("cp1252"), "texto") == "Açúcar e ação"
    assert extrair.corrigir_mojibake("AÃ§Ã£o concedida") == "Ação concedida"


def test_pdf_sem_texto_e_zip_bomba():
    with pytest.raises(extrair.ErroArquivo) as erro:
        extrair.extrair_texto(pdf(""), "pdf")
    assert erro.value.codigo == "sem_texto"
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", "<a>" + " " * (extrair.LIMITE_XML + 10) + "</a>")
    with pytest.raises(extrair.ErroArquivo) as erro:
        extrair.extrair_texto(saida.getvalue(), "docx")
    assert erro.value.codigo == "grande_demais"


def _http(arquivos: dict[str, tuple[int, bytes]]) -> httpx.AsyncClient:
    def tratar(pedido: httpx.Request) -> httpx.Response:
        status, corpo = arquivos.get(pedido.url.path, (404, b""))
        return httpx.Response(status, content=corpo)
    return httpx.AsyncClient(transport=httpx.MockTransport(tratar))


@pytest.mark.asyncio
async def test_tratar_midia_curto_longo_e_link_expirado():
    longo = docx(["Processo 0001234-56.2024 " * 120])
    http = _http({"/curto.docx": (200, docx(["CAT emitida em 03/03/2024"])), "/longo.docx": (200, longo),
                  "/velho.pdf": (403, b"")})
    modelo = ModeloFalso({"resumo_documento": {"resumo": "Processo de auxílio-acidente, perícia pendente."}})

    curto = await midia.tratar_midia(tipo="documento", url="https://cdn.helena.run/curto.docx", mime=None, nome="cat.docx",
                                     legenda=None, transcricao_helena=None, http=http, modelo=modelo)
    assert not curto.resumido and "CAT emitida em 03/03/2024" in curto.texto and '"cat.docx"' in curto.texto

    resumido = await midia.tratar_midia(tipo="documento", url="https://cdn.helena.run/longo.docx", mime=None, nome=None,
                                        legenda="segue o processo", transcricao_helena=None, http=http, modelo=modelo)
    assert resumido.resumido and "perícia pendente" in resumido.texto and "segue o processo" in resumido.texto

    expirado = await midia.tratar_midia(tipo="documento", url="https://cdn.helena.run/velho.pdf", mime=None, nome="x.pdf",
                                        legenda=None, transcricao_helena=None, http=http, modelo=modelo)
    assert expirado.erro == "link_expirado" and "expirou" in expirado.texto


@pytest.mark.asyncio
async def test_url_interna_e_recusada_e_imagem_usa_visao():
    assert not midia.url_permitida("http://cdn.helena.run/a.pdf")
    assert not midia.url_permitida("https://127.0.0.1/a.pdf")
    assert not midia.url_permitida("https://localhost/a.pdf")
    assert midia.url_permitida("https://s3.amazonaws.com/a.pdf?X-Amz-Signature=abc")

    async def descrever(url, mime, legenda):
        return "Carta do INSS negando o benefício em 10/01/2025.", Chamada(papel="descrever_imagem", modelo="gpt-4.1-mini")

    r = await midia.tratar_midia(tipo="imagem", url="https://cdn.helena.run/foto.jpg", mime="image/jpeg", nome=None,
                                 legenda="olha isso", transcricao_helena=None, http=_http({}), modelo=ModeloFalso({}),
                                 descrever_imagem=descrever)
    assert "negando o benefício" in r.texto and len(r.chamadas) == 1
