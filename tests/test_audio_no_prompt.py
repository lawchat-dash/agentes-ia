"""Áudio que está no prompt (os áudios gravados pelo escritório que o roteiro manda enviar): docs/AUDIO_NO_PROMPT.md.

Do roteiro ao WhatsApp: a regra fixa do motor, a ordem áudio -> texto, o reenvio, o link do bucket do Supabase, o link
fora do roteiro, o link quebrado (HEAD), o limite de áudios por resposta, o pedido "manda por áudio" e os formatos.
Tudo com fakes: nenhum HEAD, Helena ou modelo de verdade.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app import armazenamento
from app.cerebro import catalogo, turno
from app.gestao import produtos
from app.midia import link
from app.modelo import ModeloFalso
from app.pipeline import Atendimento
from tests.test_midia_correcoes import _envio

AGORA = datetime(2026, 11, 24, 14, 30, tzinfo=timezone(timedelta(hours=-3)))
SEM_INTENCAO = {"pediu_humano": False, "pediu_para_parar": False, "engano": False, "diz_que_assinou": False, "pediu_link": False}
ESCRITORIO = "0f8fad5b-d9cb-469f-a165-70867728950e"
BUCKET = armazenamento.ArmazenamentoSupabase("https://abcd.supabase.co", "chave-falsa")
COMO_FUNCIONA = BUCKET.url_publica(f"{ESCRITORIO}/audio/9f1c-como-funciona.ogg")
ENDERECO = BUCKET.url_publica(f"{ESCRITORIO}/audio/77aa-endereco.mp3")
OBJECAO = BUCKET.url_publica(f"{ESCRITORIO}/audio/1b2c-objecao.m4a")
ROTEIRO = (f"ETAPA 1 — Educação\nEnvie o áudio e depois pergunte:\n{COMO_FUNCIONA}\n\"Conseguiu entender certinho?\"\n"
           f"- Endereço: sozinho {ENDERECO} e \"Conseguiu entender direitinho?\"\n- Objeção de preço: sozinho {OBJECAO}")


def _produto():
    return catalogo.carregar({"catalogo": {"papeis": {p: {} for p in ("sdr", "closer", "contratos", "desqualificado")}},
                              "funcoes": {"contrato_zapsign": False}})


def _extrai(sinais=()):
    return {"fatos": [], "sinais": list(sinais), "intencoes": dict(SEM_INTENCAO)}


def _fala(*textos):
    return {"mensagens": [{"texto": t} for t in textos], "transferir_para": "", "ferramenta": ""}


def _entrada(novas, historico=(), roteiro=ROTEIRO, **extra):
    return turno.Entrada(escritorio="Escritório Teste", agente="Júlia", etapa="closer", novas=list(novas),
                         produto=_produto(), instrucoes={"closer": roteiro}, historico=list(historico), agora=AGORA,
                         **extra)


async def _turno(etapa, novas=("oi",), historico=(), **extra):
    modelo = ModeloFalso({"extrator": _extrai(), "etapa": etapa})
    saida = await turno.processar(modelo, _entrada(novas, historico, **extra))
    return saida, [p for p in modelo.pedidos if p["papel"] == "etapa"]


def _partes(saida):
    return [(m["tipo"], m.get("url") or m.get("texto")) for m in saida.mensagens]


# ---------------------------------------------------------------------------- 1. entrada no prompt e regra fixa
def test_regra_fixa_das_midias_so_entra_no_papel_cujo_roteiro_tem_midia():
    comum = dict(nome_agente="Júlia", escritorio="Escritório", conhecimento_texto="", regras=None, destinos=[],
                 acoes=[], fatos_sistema=None, papel="closer")
    com = catalogo.montar_sistema(prompt=ROTEIRO, **comum)
    assert "Áudios e mídias do roteiro" in com and "sozinho num" in com and "No máximo 2 áudios" in com
    sem = catalogo.montar_sistema(prompt="Pergunte o nome.", **comum)
    assert "Áudios e mídias do roteiro" not in sem
    pela_objecao = catalogo.montar_sistema(prompt="Pergunte o nome.", **{**comum, "conhecimento_texto": f"OBJ 1: {OBJECAO}"})
    assert "Áudios e mídias do roteiro" in pela_objecao                      # áudio só nas objeções também vale


def test_marcador_de_audio_sem_arquivo_nao_chega_a_ia():
    comum = dict(nome_agente="Júlia", escritorio="Escritório", conhecimento_texto="", destinos=[], acoes=[],
                 fatos_sistema=None, papel="closer")
    sistema = catalogo.montar_sistema(prompt="Explique.\n[[audio:Como funciona]]\n\\[\\[midia:nome\\]\\] Pergunte.",
                                      regras="[[vídeo: Honorários]]", **comum)
    assert "audio:" not in sistema and "midia:nome" not in sistema and "Honorários]]" not in sistema
    assert "\\[" not in sistema and "Explique." in sistema and "Pergunte." in sistema
    assert "Áudios e mídias do roteiro" not in sistema                         # marcador vazio não é mídia


# ---------------------------------------------------------------------------- 2/3. URL do bucket do Supabase
@pytest.mark.parametrize("sufixo", ["", "?download=1", "?t=1732550000&v=2"])
def test_url_do_bucket_e_audio_com_ou_sem_query(sufixo):
    url = COMO_FUNCIONA + sufixo
    assert url.startswith("https://abcd.supabase.co/storage/v1/object/public/agentesia-midia/")
    assert catalogo.e_url_de_midia(url) and catalogo.e_audio(url) and Atendimento.tipo_da_midia(url) == "audio"
    assert catalogo.separar_midias([url]) == [{"tipo": "midia", "url": url, "chave": url.rsplit("/", 1)[-1]}]
    assert catalogo.normalizar_url(url) in catalogo.midias_permitidas(f"Envie: {url}")
    # A pasta audio/ da biblioteca já diz o tipo, mesmo com extensão de vídeo ou sem extensão (local ou bucket).
    assert catalogo.e_audio(BUCKET.url_publica(f"{ESCRITORIO}/audio/x-voz.mp4") + sufixo)
    assert catalogo.e_audio(f"https://ia.exemplo.com/midia/{ESCRITORIO}/audio/1700-objecao{sufixo}")
    assert not catalogo.e_audio(BUCKET.url_publica(f"{ESCRITORIO}/video/x-honorarios.mp4") + sufixo)


def test_link_colado_do_sousa_e_costa_com_porcento_20_e_audio():
    colado = "https://mqkgzkzlysvwjjuwvxul.supabase.co/storage/v1/object/public/Audios%20Gerais/objecao_audio.ogg"
    assert catalogo.e_audio(colado) and Atendimento.tipo_da_midia(colado) == "audio"
    assert catalogo.normalizar_url(colado) in catalogo.midias_permitidas(f"- Pede áudio: sozinho: {colado}")


# ---------------------------------------------------------------------------- 3. "envie o áudio X e depois pergunte Y"
async def test_audio_e_depois_a_pergunta_saem_na_ordem_do_roteiro():
    saida, pedidos = await _turno(_fala(COMO_FUNCIONA, "Conseguiu entender certinho?"))
    assert _partes(saida) == [("midia", COMO_FUNCIONA), ("texto", "Conseguiu entender certinho?")]
    assert len(pedidos) == 1 and "Áudios e mídias do roteiro" in pedidos[0]["sistema"]
    # Num balão só ("Escuta: <link> Conseguiu?"): o texto antes, o áudio e a pergunta, cada um no seu balão.
    saida, _ = await _turno(_fala(f"Escuta este áudio: {COMO_FUNCIONA} Conseguiu entender certinho?"))
    assert [t for t, _ in _partes(saida)] == ["texto", "midia", "texto"] and _partes(saida)[1] == ("midia", COMO_FUNCIONA)


async def test_pipeline_envia_o_audio_espera_e_depois_o_texto(monkeypatch):
    linha, *_ = await _envio(monkeypatch, [{"tipo": "midia", "url": COMO_FUNCIONA},
                                           {"tipo": "texto", "texto": "Conseguiu entender certinho?"}])
    assert linha == [("espera", 0), ("envio", COMO_FUNCIONA), ("espera", 3.0), ("espera", 0),
                     ("envio", "Conseguiu entender certinho?")]


# ---------------------------------------------------------------------------- 3. não reenviar o mesmo áudio
HISTORICO = [{"autor": "lead", "texto": "como funciona?"}, {"autor": "você", "texto": f"[mídia enviada: {COMO_FUNCIONA}]"},
             {"autor": "você", "texto": "Conseguiu entender certinho?"}]


async def test_audio_ja_enviado_nao_vai_de_novo_mesmo_se_a_ia_insistir():
    saida, pedidos = await _turno(_fala(COMO_FUNCIONA, "Ficou alguma dúvida?"), ["não entendi direito"], HISTORICO)
    assert "CORRIJA: Essa mídia já foi enviada" in pedidos[1]["conteudo"]
    assert _partes(saida) == [("texto", "Ficou alguma dúvida?")]                 # a mídia saiu, o texto seguiu
    assert any(e["tipo"] == "midia_repetida" for e in saida.eventos)
    assert not any(e["tipo"] == "trava_midia_repetida" for e in saida.eventos)
    assert saida.estado_lead is None                                            # nunca pausa por isso


async def test_audio_ja_enviado_vai_de_novo_quando_o_lead_pede():
    saida, pedidos = await _turno(_fala(COMO_FUNCIONA, "Prontinho, mandei de novo!"), ["não chegou, manda de novo"],
                                  HISTORICO)
    assert len(pedidos) == 1 and ("midia", COMO_FUNCIONA) in _partes(saida)


async def test_audio_repetido_sozinho_na_resposta_ainda_vai():
    saida, _ = await _turno(_fala(COMO_FUNCIONA), ["hm"], HISTORICO)
    assert _partes(saida) == [("midia", COMO_FUNCIONA)]                          # melhor que deixar o lead sem nada
    assert any(e["tipo"] == "trava_midia_repetida" for e in saida.eventos)


# ---------------------------------------------------------------------------- 3. áudio fora do roteiro
async def test_audio_do_mesmo_bucket_que_nao_esta_no_roteiro_e_barrado():
    inventado = BUCKET.url_publica(f"{ESCRITORIO}/audio/0000-honorarios.ogg")    # mesmo bucket, arquivo que não existe
    saida, pedidos = await _turno(_fala("Escuta:", inventado))
    assert "CORRIJA: Use só os links de mídia do roteiro" in pedidos[1]["conteudo"]
    assert _partes(saida) == [("texto", "Escuta:")]
    assert any(e["tipo"] == "midia_desconhecida" for e in saida.eventos)


# ---------------------------------------------------------------------------- 3. limite de áudios por resposta
async def test_no_maximo_dois_audios_por_resposta():
    saida, _ = await _turno(_fala(COMO_FUNCIONA, ENDERECO, OBJECAO, "Conseguiu entender?"))
    assert _partes(saida) == [("midia", COMO_FUNCIONA), ("midia", ENDERECO), ("texto", "Conseguiu entender?")]
    evento = next(e for e in saida.eventos if e["tipo"] == "audios_demais")
    assert evento["detalhe"]["urls"] == [OBJECAO]
    video = BUCKET.url_publica(f"{ESCRITORIO}/video/aa-honorarios.mp4")             # vídeo não conta como áudio
    partes, cortadas = catalogo.limitar_audios([{"tipo": "midia", "url": u} for u in (COMO_FUNCIONA, video, ENDERECO)])
    assert len(partes) == 3 and cortadas == []


# ---------------------------------------------------------------------------- 3. "manda por áudio" (sinal)
async def test_lead_pede_para_falar_por_audio_avisa_e_pausa_sem_mandar_audio():
    modelo = ModeloFalso({"extrator": _extrai(["quer_audio"]), "etapa": _fala(OBJECAO)})
    saida = await turno.processar(modelo, _entrada(["manda por áudio, não gosto de ler"]))
    assert saida.sinais == ["quer_audio"] and (saida.estado_lead, saida.motivo_estado) == ("pausado", "sinal:quer_audio")
    assert all(m["tipo"] == "texto" for m in saida.mensagens)
    assert not [p for p in modelo.pedidos if p["papel"] == "etapa"]                # o agente nem é chamado
    assert any(e["tipo"] == "sinal_quer_audio" for e in saida.eventos)


# ---------------------------------------------------------------------------- 3. link quebrado (HEAD)
def _conferir(responder):
    return link.ConferirLink(transporte=httpx.MockTransport(responder))


@pytest.mark.parametrize("resposta,barra", [
    (httpx.Response(200, headers={"content-type": "audio/ogg", "content-length": "48000"}), False),
    (httpx.Response(404), True),                                                   # apagado da biblioteca
    (httpx.Response(410), True),
    (httpx.Response(400, json={"error": "not_found"}), True),                      # Storage do Supabase: objeto sumiu
    (httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}), True),   # página do Drive
    (httpx.Response(200, headers={"content-type": "audio/mpeg", "content-length": str(17 * 1024 * 1024)}), True),
    (httpx.Response(405), False),                                                  # servidor sem HEAD: na dúvida, envia
    (httpx.Response(503), False),
])
async def test_head_decide_se_o_audio_vai(resposta, barra):
    motivo = await _conferir(lambda _pedido: resposta)(COMO_FUNCIONA, "audio")
    assert bool(motivo) is barra


async def test_head_fora_do_ar_envia_e_resultado_fica_guardado():
    chamadas = []

    def responder(pedido):
        chamadas.append(pedido.method)
        raise httpx.ConnectTimeout("lento", request=pedido)

    conferir = _conferir(responder)
    assert await conferir(COMO_FUNCIONA, "audio") is None and await conferir(COMO_FUNCIONA, "audio") is None
    assert chamadas == ["HEAD"]                                                     # o 2º lead não refaz o HEAD


async def test_audio_com_link_quebrado_nao_vai_avisa_a_equipe_e_o_texto_segue(monkeypatch):
    vistos = []

    async def conferir(url, tipo):
        vistos.append((url, tipo))
        return "o link não abre (HTTP 404): o arquivo foi apagado ou o link mudou" if url == COMO_FUNCIONA else None

    monkeypatch.setattr(Atendimento, "conferir_midia", staticmethod(conferir))
    linha, saida, repo, lead, _ = await _envio(monkeypatch, [{"tipo": "midia", "url": COMO_FUNCIONA},
                                                             {"tipo": "texto", "texto": "Conseguiu entender certinho?"}])
    assert vistos == [(COMO_FUNCIONA, "audio")]
    assert [e for e in linha if e[0] == "envio"] == [("envio", "Conseguiu entender certinho?")]
    evento = next(e for e in saida.eventos if e["tipo"] == "midia_quebrada")
    assert evento["responsavel"] == "cadastro" and evento["gravidade"] == "erro" and "áudio" in evento["descricao"]
    assert saida.contexto["midia_pulada"][0]["url"] == COMO_FUNCIONA
    notas = [a for a in repo.acoes if a["chave_unica"].startswith(f"{lead.id}:problema:midia_quebrada")]
    assert notas and "não enviou uma mídia do roteiro" in notas[0]["dados"]["texto"]
    gravadas = [m for m in repo.mensagens[lead.id] if m.autor == "ia" and m.id_turno == "turno-1"]
    assert [m.texto for m in gravadas] == ["Conseguiu entender certinho?"]           # nada de "[mídia enviada]" falso


async def test_falha_na_conferencia_nunca_barra_o_envio(monkeypatch):
    async def quebrada(url, tipo):
        raise RuntimeError("bug")

    monkeypatch.setattr(Atendimento, "conferir_midia", staticmethod(quebrada))
    linha, *_ = await _envio(monkeypatch, [{"tipo": "midia", "url": COMO_FUNCIONA}])
    assert ("envio", COMO_FUNCIONA) in linha


# ---------------------------------------------------------------------------- 3. formatos e tamanho
def test_formatos_e_tamanho_do_audio_iguais_na_biblioteca_e_no_envio():
    assert produtos.EXTENSOES["audio"] == ("ogg", "oga", "opus", "mp3", "m4a")
    assert produtos.LIMITES_POR_TIPO["audio"] == link.TAMANHO_MAXIMO["audio"] == 16 * 1024 * 1024
    assert all(catalogo.e_audio(f"https://x.co/a.{ext}") for ext in produtos.EXTENSOES["audio"])
    assert {"wav", "flac", "aac"} <= set(produtos.RECUSADOS)                       # o WhatsApp entrega como documento
