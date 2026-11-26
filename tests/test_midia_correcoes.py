"""Correções da área de mídia: o que chega (lead e atendente) e o que a IA manda (links, espera, horário, biblioteca).

Tudo com fakes (visão, Helena, HTTP). Os testes da biblioteca de mídia rodam no Postgres local (AGENTESIA_TESTE_PG_URL).
"""

import asyncio
import base64
import os
import uuid
from datetime import datetime, timezone

import httpx
import pytest

from app import midia
from app import pipeline as modulo_pipeline
from app.canal.helena import ler_webhook
from app.cerebro import catalogo
from app.cerebro import turno as cerebro
from app.midia import extrair
from app.modelo import Chamada, ErroModelo, ModeloFalso
from tests.test_midia import pdf
from tests.test_pipeline import CANAL, LEAD, SIMPLES, HelenaFalsa, montar, webhook

OGG = b"OggS" + b"\x00" * 60
MP4_VIDEO = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 60
M4A_MP42 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 60
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 60
HEIC = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 60


class VisaoFalsa:
    def __init__(self, fala: str = "Os honorários são 30% do que você receber.", falhar: bool = False,
                 pdf: str = "Laudo pericial: CID S82, sequela permanente no joelho.") -> None:
        self.fala, self.falhar, self.texto_pdf = fala, falhar, pdf
        self.nomes: list[str] = []
        self.urls: list[str] = []
        self.pdfs = 0

    async def transcrever_audio(self, dados: bytes, nome: str):
        self.nomes.append(nome)
        if self.falhar:
            raise ErroModelo("transcricao", "Invalid file format")
        return self.fala, Chamada(papel="transcrever_audio", modelo="falso")

    async def descrever_imagem(self, url: str, mime, legenda):
        self.urls.append(url)
        if self.falhar:
            raise ErroModelo("visao", "invalid image")
        return "Foto do RG, legível.", Chamada(papel="descrever_imagem", modelo="falso")

    async def ler_pdf(self, dados: bytes):
        self.pdfs += 1
        if self.falhar:
            raise ErroModelo("visao", "erro")
        return self.texto_pdf, Chamada(papel="ler_pdf", modelo="falso")


def _http(arquivos: dict[str, bytes]) -> httpx.AsyncClient:
    def tratar(pedido: httpx.Request) -> httpx.Response:
        if pedido.url.path in arquivos:
            return httpx.Response(200, content=arquivos[pedido.url.path])
        return httpx.Response(404)
    return httpx.AsyncClient(transport=httpx.MockTransport(tratar))


async def _tratar(tipo, url, dados=None, visao=None, **extra):
    visao = visao or VisaoFalsa()
    caminho = url.split("cdn.helena.run", 1)[-1] if url else ""
    return await midia.tratar_midia(
        tipo=tipo, url=url, mime=extra.pop("mime", None), nome=extra.pop("nome", None), legenda=extra.pop("legenda", None),
        transcricao_helena=extra.pop("transcricao_helena", None), http=_http({caminho: dados} if dados else {}),
        modelo=ModeloFalso({}), descrever_imagem=visao.descrever_imagem, transcrever_audio=visao.transcrever_audio,
        ler_pdf=visao.ler_pdf, **extra), visao


# ---------------------------------------------------------------------------- [0] mídia do atendente
def _atendente(tipo, **arquivo):
    return webhook("", de=CANAL, para=LEAD, direcao="TO_HUB", origem="GATEWAY", tipo=tipo,
                   file={"publicUrl": "https://cdn.helena.run/equipe", **arquivo})


async def _ler_do_atendente(corpo, arquivo: bytes, visao: VisaoFalsa):
    atendimento, repo, _helena = montar(SIMPLES)
    atendimento.visao = visao
    atendimento._http_midia = _http({"/equipe": arquivo})
    resultado = await atendimento.receber(corpo)
    assert resultado["feito"] == "pausado"                           # a pausa não espera a leitura
    await atendimento._esperar_midias(resultado["id_lead"])
    lead = repo.leads[resultado["id_lead"]]
    assert lead.estado == "pausado" and lead.motivo_estado == "humano_assumiu"
    return repo.mensagens[resultado["id_lead"]][-1], atendimento


async def test_audio_do_atendente_e_transcrito_e_a_ia_sabe_o_que_ele_disse():
    visao = VisaoFalsa()
    mensagem, _ = await _ler_do_atendente(_atendente("AUDIO", name="gravacao.opus"), OGG, visao)
    assert mensagem.autor == "humano"
    assert mensagem.texto_extraido == "[O atendente enviou um áudio. O que ele disse: Os honorários são 30% do que você receber.]"
    assert visao.nomes == ["audio.ogg"]                              # nome pelos bytes, não o .opus da Helena


async def test_falha_na_transcricao_do_atendente_mantem_o_marcador():
    mensagem, _ = await _ler_do_atendente(_atendente("AUDIO"), OGG, VisaoFalsa(falhar=True))
    assert mensagem.texto_extraido == "[O atendente enviou um áudio ao lead.]"


async def test_imagem_do_atendente_e_descrita_e_documento_nao_e_lido():
    visao = VisaoFalsa()
    mensagem, _ = await _ler_do_atendente(_atendente("IMAGE"), JPEG, visao)
    assert mensagem.texto_extraido.startswith("[O atendente enviou uma imagem. O que dá para ver:]\nFoto do RG")
    assert visao.urls[0].startswith("data:image/jpeg;base64,")
    documento, _ = await _ler_do_atendente(_atendente("DOCUMENT", name="procuracao.pdf"), pdf("Procuracao"), VisaoFalsa())
    assert documento.texto_extraido == "[O atendente enviou um documento (procuracao.pdf) ao lead.]"   # como no n8n


async def test_video_do_atendente_vira_fala():
    mensagem, _ = await _ler_do_atendente(_atendente("VIDEO"), MP4_VIDEO, VisaoFalsa(fala="Olha como assina o contrato."))
    assert mensagem.texto_extraido == "[O atendente enviou um vídeo. O que ele fala no vídeo: Olha como assina o contrato.]"


# ---------------------------------------------------------------------------- [14] vídeo do lead
async def test_video_do_lead_sem_transcricao_da_helena_e_transcrito_antes_da_ia_responder():
    atendimento, repo, _helena = montar(SIMPLES)
    visao = VisaoFalsa(fala="Eu caí da moto em 2021 e fiquei com o joelho travado.")
    atendimento.visao = visao
    atendimento._http_midia = _http({"/video": MP4_VIDEO})
    await atendimento.receber(webhook("olha", tipo="VIDEO", file={"publicUrl": "https://cdn.helena.run/video", "name": "v.mp4"}))
    await atendimento.aguardar_esperas()
    pedido_extrator = next(p for p in atendimento.modelo.pedidos if p["papel"] == "extrator")
    assert "O que ele fala no vídeo: Eu caí da moto em 2021" in pedido_extrator["conteudo"]
    assert visao.nomes == ["video.mp4"]


async def test_video_que_falha_fica_com_o_texto_fixo_do_webhook():
    r, _ = await _tratar("video", "https://cdn.helena.run/v", MP4_VIDEO, VisaoFalsa(falhar=True), legenda="veja")
    fixo = ler_webhook(webhook("veja", tipo="VIDEO", file={"publicUrl": "https://x"})).texto_extraido
    assert r.texto == fixo and r.erro == "transcricao"
    webm, visao = await _tratar("video", "https://cdn.helena.run/w", b"\x1aE\xdf\xa3" + b"\x00" * 40)
    assert visao.nomes == ["video.webm"] and "O que ele fala no vídeo" in webm.texto


# ---------------------------------------------------------------------------- [15] [16] áudio em MP4 e nome pelos bytes
def test_audio_em_mp4_isom_ou_mp42_com_mime_de_audio_e_audio():
    assert extrair.detectar_formato(M4A_MP42, "audio/mp4", None) == "audio"
    assert extrair.detectar_formato(MP4_VIDEO, "audio/mp4", None) == "audio"
    assert extrair.detectar_formato(MP4_VIDEO, "video/mp4", None) == "desconhecido"
    assert extrair.nome_para_transcricao(OGG) == "audio.ogg"
    assert extrair.nome_para_transcricao(b"ID3\x03" + b"\x00" * 10) == "audio.mp3"
    assert extrair.nome_para_transcricao(b"\xff\xfb\x90" + b"\x00" * 10) == "audio.mp3"
    assert extrair.nome_para_transcricao(M4A_MP42) == "audio.m4a"
    assert extrair.nome_para_transcricao(b"RIFF\x00\x00\x00\x00WAVE") == "audio.wav"
    assert extrair.nome_para_transcricao(b"\x1aE\xdf\xa3") == "audio.webm"
    assert extrair.nome_para_transcricao(b"qualquer") == "audio.ogg"


async def test_audio_em_mp4_sem_mime_ainda_e_transcrito_e_nunca_pede_pdf():
    r, visao = await _tratar("audio", "https://cdn.helena.run/a", M4A_MP42, nome="gravacao.opus")
    assert visao.nomes == ["audio.m4a"] and r.texto == visao.fala and r.erro is None
    falhou, _ = await _tratar("audio", "https://cdn.helena.run/a", M4A_MP42, VisaoFalsa(falhar=True))
    assert "áudio que não foi possível ouvir" in falhou.texto and "PDF" not in falhou.texto


async def test_nome_da_helena_e_ignorado_na_transcricao():
    _, visao = await _tratar("audio", "https://cdn.helena.run/a", OGG, nome="x.opus")
    assert visao.nomes == ["audio.ogg"]


# ---------------------------------------------------------------------------- [13] transcrição vazia
async def test_transcricao_vazia_vira_aviso_de_audio_que_nao_deu_para_ouvir():
    for fala in ("", " . ", "Legendas pela comunidade Amara.org"):
        r, _ = await _tratar("audio", "https://cdn.helena.run/a", OGG, VisaoFalsa(fala=fala))
        assert r.erro == "transcricao_vazia" and "não foi possível ouvir" in r.texto, fala
    helena, _ = await _tratar("audio", "https://cdn.helena.run/a", OGG, transcricao_helena="..")
    assert helena.erro == "transcricao_vazia"
    # O webhook com transcrição só de ruído: a IA recebe o aviso e o sistema tenta transcrever de novo.
    corpo = webhook("", tipo="AUDIO", file={"publicUrl": "https://cdn.helena.run/a"}, transcription={"text": "."})
    assert "não foi possível ouvir" in ler_webhook(corpo).texto_extraido
    atendimento, _repo, _helena = montar(SIMPLES)
    atendimento.visao = VisaoFalsa()
    assert atendimento._precisa_ler_midia(ler_webhook(corpo))


async def test_audio_mudo_nao_vira_mensagem_vazia_para_a_ia():
    atendimento, _repo, _helena = montar(SIMPLES)
    atendimento.visao = VisaoFalsa(fala="")
    atendimento._http_midia = _http({"/a": OGG})
    await atendimento.receber(webhook("", tipo="AUDIO", file={"publicUrl": "https://cdn.helena.run/a"}))
    await atendimento.aguardar_esperas()
    pedido = next(p for p in atendimento.modelo.pedidos if p["papel"] == "extrator")
    assert "(mensagem vazia)" not in pedido["conteudo"] and "não foi possível ouvir" in pedido["conteudo"]


# ---------------------------------------------------------------------------- [12] [17] imagem e foto como documento
async def test_foto_mandada_como_documento_passa_pela_visao():
    r, visao = await _tratar("documento", "https://cdn.helena.run/rg", JPEG, nome="RG.jpg")
    assert r.erro is None and "Foto do RG" in r.texto and "PDF" not in r.texto
    assert visao.urls[0].startswith("data:image/jpeg;base64,")


async def test_imagem_e_baixada_e_vai_em_data_url_heic_vira_aviso_e_link_ruim_tenta_pela_url():
    r, visao = await _tratar("imagem", "https://cdn.helena.run/foto", JPEG)
    assert visao.urls == ["data:image/jpeg;base64," + base64.b64encode(JPEG).decode()] and r.erro is None
    heic, visao = await _tratar("imagem", "https://cdn.helena.run/foto", HEIC, mime="image/heic")
    assert heic.erro == "formato_nao_suportado" and "imagem que não foi possível ver" in heic.texto and visao.urls == []
    reserva, visao = await _tratar("imagem", "https://cdn.helena.run/sumiu")          # 404 no nosso download
    assert visao.urls == ["https://cdn.helena.run/sumiu"] and reserva.erro is None


# ---------------------------------------------------------------------------- [18] PDF escaneado
async def test_pdf_escaneado_e_lido_pela_visao_e_falha_mantem_o_texto_atual():
    r, visao = await _tratar("documento", "https://cdn.helena.run/laudo", pdf(""), nome="laudo.pdf")
    assert visao.pdfs == 1 and "CID S82" in r.texto and "(escaneado)" in r.texto and r.erro is None
    falha, _ = await _tratar("documento", "https://cdn.helena.run/laudo", pdf(""), VisaoFalsa(falhar=True), nome="laudo.pdf")
    assert falha.erro == "sem_texto" and "PDF escaneado ou sem texto" in falha.texto


# ---------------------------------------------------------------------------- [2] [9] [10] link de mídia no texto
URL = "https://x.supabase.co/storage/v1/object/public/midia/objecao.ogg"


@pytest.mark.parametrize("linha,antes,depois", [
    (f"Ouça este áudio: {URL}", "Ouça este áudio:", None),
    (f"<{URL}>", None, None),
    (f"[áudio]({URL})", None, None),
    (f"`{URL}`", None, None),
    (f"{URL}.", None, None),
    (f"Assista: {URL}, depois me conta", "Assista:", "depois me conta"),
    (f"**{URL}**", None, None),
])
def test_link_de_midia_no_meio_entre_sinais_ou_com_pontuacao_vira_arquivo(linha, antes, depois):
    partes = catalogo.separar_midias([linha])
    midias = [p for p in partes if p["tipo"] == "midia"]
    assert [m["url"] for m in midias] == [URL]
    textos = [p["texto"] for p in partes if p["tipo"] == "texto"]
    assert textos == [t for t in (antes, depois) if t]


def test_bloco_de_codigo_do_roteiro_query_string_e_url_quebrada():
    partes = catalogo.separar_midias(["Mensagem 1:\n```\n" + URL + "\n```\nQualquer dúvida me chama."])
    assert [p["tipo"] for p in partes] == ["texto", "midia", "texto"] and "```" not in str(partes)
    com_query = URL + "?token=abc"
    assert catalogo.separar_midias([com_query])[0] == {"tipo": "midia", "url": com_query, "chave": "objecao.ogg?token=abc"}
    quebrada = "https://x.supabase.co/midia/Como Funciona o Auxilio Acidente.ogg"            # não adivinha a URL
    assert all(p["tipo"] == "texto" for p in catalogo.separar_midias([quebrada]))
    site = catalogo.separar_midias(["Veja https://escritorio.com.br/sobre"])                 # link comum fica no texto
    assert site == [{"tipo": "texto", "texto": "Veja https://escritorio.com.br/sobre"}]
    assert catalogo.conferir([{"tipo": "texto", "texto": "Olá\n```"}])                        # reserva da cerca


# ---------------------------------------------------------------------------- [3] [11] [19] lista permitida e repetida
ROTEIRO = "https://x.supabase.co/storage/v1/object/public/midia/Como%20Funciona.ogg"


def _catalogo_com_roteiro(respostas_etapa):
    from tests.test_catalogo import PROMPT_SDR
    from tests.test_catalogo import montar as montar_catalogo

    atendimento, repo, helena, modelo = montar_catalogo(respostas_etapa)
    repo.agentes["canal-1"].etapas[0].instrucao = PROMPT_SDR + f"\nPara explicar, envie o áudio: ```\n{ROTEIRO}\n```"
    return atendimento, repo, helena, modelo


def _fala(*textos):
    return {"mensagens": [{"texto": t} for t in textos], "transferir_para": "", "ferramenta": ""}


async def test_link_do_roteiro_com_porcento_20_e_aceito():
    atendimento, _repo, helena, modelo = _catalogo_com_roteiro(_fala("Olá! Sou a Júlia 😊 Escuta:", ROTEIRO))
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    assert helena.enviadas == ["Olá! Sou a Júlia 😊 Escuta:", ROTEIRO]
    assert sum(p["papel"] == "etapa" for p in modelo.pedidos) == 1                       # sem CORRIJA


@pytest.mark.parametrize("inventada", [
    "https://escritorio.com.br/audios/beneficio.mp3",
    "https://ia.exemplo.com/midia/0f8fad5b-d9cb-469f-a165-70867728950e/audio/1700-honorarios.ogg",   # outro escritório
])
async def test_link_inventado_pede_correcao_e_se_insistir_sai_da_resposta_sem_pausar(inventada):
    atendimento, repo, helena, modelo = _catalogo_com_roteiro(_fala("Olá! Sou a Júlia 😊 Escuta:", inventada))
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    segundo = [p for p in modelo.pedidos if p["papel"] == "etapa"][1]
    assert "CORRIJA: Use só os links de mídia do roteiro" in segundo["conteudo"]
    assert helena.enviadas == ["Olá! Sou a Júlia 😊 Escuta:"]                              # a mídia não foi para a Helena
    assert any(e["tipo"] == "midia_desconhecida" for e in repo.eventos)
    assert not any(e["tipo"] == "trava_midia_desconhecida" for e in repo.eventos)
    lead = next(iter(repo.leads.values()))
    assert lead.estado == "ativo"


async def test_link_inventado_corrigido_na_segunda_tentativa():
    def etapa(_sistema, conteudo):
        return _fala("Escuta:", ROTEIRO) if "CORRIJA" in conteudo else _fala("Escuta:", "https://inventado.com/a.ogg")

    atendimento, repo, helena, _modelo = _catalogo_com_roteiro(etapa)
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    assert helena.enviadas == ["Escuta:", ROTEIRO] and not any(e["tipo"] == "midia_desconhecida" for e in repo.eventos)


async def test_so_a_midia_inventada_vira_a_mensagem_fixa():
    atendimento, _repo, helena, _modelo = _catalogo_com_roteiro(_fala("https://inventado.com/a.mp4"))
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    assert helena.enviadas == [cerebro.MENSAGENS_FIXAS["seguranca"]]


async def test_midia_ja_enviada_pede_resposta_por_texto_salvo_pedido_de_reenvio():
    atendimento, repo, helena, modelo = _catalogo_com_roteiro(_fala("Escuta:", ROTEIRO))
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    lead = next(iter(repo.leads.values()))
    assert any(m.texto_extraido == f"[mídia enviada: {ROTEIRO}]" for m in repo.mensagens[lead.id])   # [6] URL inteira
    antes = len(modelo.pedidos)
    await atendimento.receber(webhook("como funciona mesmo?"))
    await atendimento.aguardar_esperas()
    pedidos = [p for p in modelo.pedidos[antes:] if p["papel"] == "etapa"]
    assert f"você: [mídia enviada: {ROTEIRO}]" in pedidos[0]["conteudo"]                    # o link está no histórico
    assert "CORRIJA: Essa mídia já foi enviada" in pedidos[1]["conteudo"]
    antes = len(modelo.pedidos)
    await atendimento.receber(webhook("não chegou, manda de novo"))
    await atendimento.aguardar_esperas()
    assert sum(p["papel"] == "etapa" for p in modelo.pedidos[antes:]) == 1                 # reenviar é o que ele pediu


# ---------------------------------------------------------------------------- [4] [5] [6] [20] envio da mídia
class HelenaComRelogio(HelenaFalsa):
    def __init__(self, linha):
        super().__init__()
        self.linha = linha

    async def enviar(self, **dados):
        self.linha.append(("envio", dados.get("texto") or dados.get("url_arquivo")))
        return await super().enviar(**dados)


async def _envio(monkeypatch, mensagens, quando=None):
    linha: list[tuple[str, object]] = []
    atendimento, repo, _ = montar(SIMPLES, helena=HelenaComRelogio(linha))
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    linha.clear()

    async def dormir(segundos):
        linha.append(("espera", segundos))

    monkeypatch.setattr(modulo_pipeline.asyncio, "sleep", dormir)
    if quando:
        monkeypatch.setattr(modulo_pipeline, "agora", lambda: quando)
    atendimento.digitar = True
    lead = next(iter(repo.leads.values()))
    saida = cerebro.Saida(mensagens=[{**m, "espera_s": 0} for m in mensagens])
    try:
        await atendimento._enviar(repo.escritorios["esc-1"], repo.agentes["canal-1"], lead, "turno-1", saida, "teste")
    finally:
        monkeypatch.undo()
    return linha, saida, repo, lead, atendimento


async def test_espera_depois_da_midia_pelo_tipo_e_nada_depois_da_ultima(monkeypatch):
    video, audio = "https://x.co/m/apresentacao.mp4", "https://x.co/m/objecao.ogg"
    linha, *_ = await _envio(monkeypatch, [{"tipo": "midia", "url": video}, {"tipo": "texto", "texto": "Assistiu?"},
                                           {"tipo": "midia", "url": audio}])
    assert linha == [("espera", 0), ("envio", video), ("espera", 8.0), ("espera", 0), ("envio", "Assistiu?"),
                     ("espera", 0), ("envio", audio)]


async def test_video_de_apresentacao_so_no_horario_comercial(monkeypatch):
    ptv = "https://x.co/m/PTV.mp4"
    partes = [{"tipo": "midia", "url": ptv}, {"tipo": "texto", "texto": "Olá! Me chamo Ana."}]
    noite = datetime(2026, 11, 25, 2, 0, tzinfo=timezone.utc)                # 23h em São Paulo
    linha, saida, *_ = await _envio(monkeypatch, partes, noite)
    assert ("envio", ptv) not in linha and ("envio", "Olá! Me chamo Ana.") in linha
    assert saida.contexto["midia_pulada"] == [{"url": ptv, "motivo": "fora_do_horario_comercial"}]
    manha = datetime(2026, 11, 25, 13, 0, tzinfo=timezone.utc)               # 10h em São Paulo
    linha, saida, *_ = await _envio(monkeypatch, partes, manha)
    assert linha[:3] == [("espera", 0), ("envio", ptv), ("espera", 10.0)] and "midia_pulada" not in saida.contexto


async def test_midia_enviada_gravada_com_o_tipo_e_a_url_inteira(monkeypatch):
    nossa = "https://ia.exemplo.com/midia/0f8fad5b-d9cb-469f-a165-70867728950e/audio/1700-objecao"
    urls = {"https://x.co/m/Como%20Funciona.ogg": "audio", "https://x.co/m/foto.PNG": "imagem",
            "https://x.co/m/video.mp4?v=1": "video", nossa: "audio"}
    _, _, repo, lead, atendimento = await _envio(monkeypatch, [{"tipo": "midia", "url": u} for u in urls])
    gravadas = [m for m in repo.mensagens[lead.id] if m.autor == "ia" and m.texto is None]
    assert [(m.tipo, m.texto_extraido) for m in gravadas] == [(t, f"[mídia enviada: {u}]") for u, t in urls.items()]
    historico = [m.para_a_ia() for m in await repo.historico(lead.id)]
    assert "[mídia enviada: https://x.co/m/Como%20Funciona.ogg]" in historico


# ---------------------------------------------------------------------------- [1] [7] [8] [21] biblioteca de mídia (Postgres)
URL_PG = os.environ.get("AGENTESIA_TESTE_PG_URL")
precisa_pg = pytest.mark.skipif(not URL_PG, reason="sem AGENTESIA_TESTE_PG_URL")

if URL_PG:
    from tests.test_gestao import _entrar, ambiente  # noqa: F401  (fixture do painel com Postgres local)


def _b64(dados: bytes) -> str:
    return base64.b64encode(dados).decode()


@precisa_pg
async def test_biblioteca_formatos_limites_url_publica_e_apagar_em_uso(ambiente, monkeypatch):
    cliente, _simulada, email_admin, banco = ambiente
    await _entrar(cliente, email_admin, "senha-admin-123")
    escritorio = (await cliente.post("/api/admin/escritorios", json={
        "nome": "Mídia Ltda", "id_conta_helena": str(uuid.uuid4()), "token_helena": "token-bom-123456"})).json()["escritorio"]
    h = {"x-escritorio": escritorio["id"]}

    async def subir(nome, dados, mime=None):
        return await cliente.post("/api/midia", headers=h, json={"nome": nome, "conteudo_base64": _b64(dados), "mime": mime})

    wav = await subir("objecao.wav", b"RIFF\x00\x00\x00\x00WAVE" + b"\x00" * 20)
    assert wav.status_code == 400 and ".ogg (opus)" in wav.json()["detail"]
    mov = await subir("honorarios.mov", b"\x00" * 30)
    assert mov.status_code == 400 and ".mp4" in mov.json()["detail"]
    assert (await subir("foto.webp", b"RIFF\x00\x00\x00\x00WEBP")).status_code == 400
    grande = await subir("rg.jpg", JPEG + b"\x00" * (5 * 1024 * 1024))
    assert grande.status_code == 413 and "5 MB" in grande.json()["detail"]
    ogg = await subir("objecao.ogg", OGG, mime="application/octet-stream")
    assert ogg.status_code == 200, ogg.text
    midia_ogg = ogg.json()
    assert midia_ogg["mime_type"] == "audio/ogg" and midia_ogg["url"].startswith("https://ia.exemplo.com/midia/")

    monkeypatch.setenv("AGENTESIA_URL_PUBLICA", "")                     # sem endereço público: URL ficaria relativa
    sem_url = await subir("outro.ogg", OGG)
    assert sem_url.status_code == 409 and "endereço público" in sem_url.json()["detail"]
    monkeypatch.setenv("AGENTESIA_URL_PUBLICA", "https://ia.exemplo.com")

    # O roteiro de um agente ainda cita o arquivo: não apaga (o link ficaria morto).
    pool = banco._pool
    canal = await pool.fetchval(
        "insert into agentesia_canais (id_escritorio, numero_normalizado, id_canal_helena) values ($1::uuid, $2, $3) returning id",
        escritorio["id"], "55119" + str(uuid.uuid4().int)[:8], "ch-" + uuid.uuid4().hex[:10])
    agente = await pool.fetchval(
        "insert into agentesia_agentes (id_escritorio, id_canal, nome, situacao, config) values ($1::uuid, $2, 'Ana', 'ativo', '{}'::jsonb) returning id",
        escritorio["id"], canal)
    await pool.execute("insert into agentesia_agente_etapas (id_agente, codigo, ordem, principal, instrucao) values ($1, 'sdr', 1, true, $2)",
                       agente, f"Envie o áudio:\n```\n{midia_ogg['url']}\n```")
    em_uso = await cliente.delete(f"/api/midia/{midia_ogg['id']}", headers=h)
    assert em_uso.status_code == 409 and "Ana" in em_uso.json()["detail"]
    assert await pool.fetchval("select count(*) from agentesia_biblioteca_midia where id = $1::uuid", midia_ogg["id"]) == 1

    await pool.execute("update agentesia_agente_etapas set instrucao = 'Sem áudio.' where id_agente = $1", agente)
    livre = await cliente.delete(f"/api/midia/{midia_ogg['id']}", headers=h)
    assert livre.status_code == 200
    assert await pool.fetchval("select count(*) from agentesia_biblioteca_midia where id = $1::uuid", midia_ogg["id"]) == 0


def test_tipos_de_midia_servidos_com_o_mime_certo():
    import mimetypes

    from app.main import registrar_tipos_de_midia

    registrar_tipos_de_midia()
    assert mimetypes.guess_type("a.webp")[0] == "image/webp"
    assert mimetypes.guess_type("a.opus")[0] == "audio/ogg"
    assert mimetypes.guess_type("a.m4a")[0] == "audio/mp4"
