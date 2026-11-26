"""Ferramentas > Roteiros: conversão WebM/Opus -> Ogg/Opus (gravação do navegador) e as rotas /api/roteiros.

A conversão roda sempre. As rotas rodam no Postgres local (AGENTESIA_TESTE_PG_URL, com a migração 009).
"""

import base64
import os
import struct
import uuid

import pytest

from app.midia.webm_para_ogg import ErroConversao, amostras_do_pacote, crc_ogg, webm_para_ogg


# ---------------------------------------------------------------------------- WebM de mentira
def _tam(n: int | None) -> bytes:
    if n is None:                                         # tamanho desconhecido (como o Chrome grava)
        return b"\x01\xff\xff\xff\xff\xff\xff\xff"
    if n < 127:
        return bytes([0x80 | n])
    return b"\x01" + n.to_bytes(7, "big")


def _el(ident: int, corpo: bytes, desconhecido: bool = False) -> bytes:
    largura = (ident.bit_length() + 7) // 8
    return ident.to_bytes(largura, "big") + _tam(None if desconhecido else len(corpo)) + corpo


OPUS_HEAD = b"OpusHead" + struct.pack("<BBHIhB", 1, 1, 312, 48000, 0, 0)


def _webm(pacotes: list[bytes], trilha: int = 1, codec: bytes = b"A_OPUS") -> bytes:
    cabeca = _el(0x1A45DFA3, _el(0x4282, b"webm"))
    entrada = _el(0xAE, _el(0xD7, bytes([trilha])) + _el(0x86, codec) + _el(0x63A2, OPUS_HEAD) + _el(0xE1, _el(0x9F, b"\x01")))
    trilhas = _el(0x1654AE6B, entrada)
    info = _el(0x1549A966, _el(0x2AD7B1, (1000000).to_bytes(3, "big")))
    blocos = b"".join(_el(0xA3, bytes([0x80 | trilha]) + struct.pack(">h", i * 20) + b"\x80" + p) for i, p in enumerate(pacotes))
    cluster = _el(0x1F43B675, _el(0xE7, b"\x00") + blocos, desconhecido=True)
    return cabeca + _el(0x18538067, info + trilhas + cluster, desconhecido=True)


def _paginas(ogg: bytes) -> list[dict]:
    paginas, pos = [], 0
    while pos < len(ogg):
        assert ogg[pos:pos + 4] == b"OggS"
        tipo, granule, _serie, seq, crc, nseg = struct.unpack("<BqIIIB", ogg[pos + 5:pos + 27])
        segs = list(ogg[pos + 27:pos + 27 + nseg])
        inicio = pos + 27 + nseg
        fim = inicio + sum(segs)
        pagina = bytearray(ogg[pos:fim])
        pagina[22:26] = b"\x00\x00\x00\x00"
        assert crc_ogg(bytes(pagina)) == crc, "CRC errado"
        pacotes, atual, p = [], b"", inicio
        for s in segs:
            atual += ogg[p:p + s]
            p += s
            if s < 255:
                pacotes.append(atual)
                atual = b""
        paginas.append({"tipo": tipo, "granule": granule, "seq": seq, "pacotes": pacotes})
        pos = fim
    return paginas


def test_webm_do_navegador_vira_ogg_opus_com_os_mesmos_pacotes():
    pacotes = [b"\xf8" + bytes([i % 251]) * 59 for i in range(120)] + [b"\xf8" + b"\x07" * 299]   # um maior que 255
    ogg = webm_para_ogg(_webm(pacotes))
    paginas = _paginas(ogg)
    assert paginas[0]["tipo"] == 0x02 and paginas[0]["pacotes"] == [OPUS_HEAD]
    assert paginas[1]["pacotes"][0].startswith(b"OpusTags")
    assert paginas[-1]["tipo"] == 0x04
    assert [p["seq"] for p in paginas] == list(range(len(paginas)))
    de_volta = [pk for p in paginas[2:] for pk in p["pacotes"]]
    assert de_volta == pacotes
    assert paginas[-1]["granule"] == 960 * len(pacotes)                 # 20 ms a 48 kHz por pacote
    granules = [p["granule"] for p in paginas[2:]]
    assert granules == sorted(granules)


def test_amostras_pelo_toc_e_webm_sem_opus_ou_vazio():
    assert amostras_do_pacote(b"\xf8") == 960            # CELT 20 ms
    assert amostras_do_pacote(b"\x08") == 960            # SILK 20 ms
    assert amostras_do_pacote(b"\xf9") == 1920           # dois quadros de 20 ms
    assert amostras_do_pacote(b"\xfb\x03") == 2880       # código 3, três quadros
    with pytest.raises(ErroConversao):
        webm_para_ogg(_webm([b"\xf8\x00"], codec=b"A_VORBIS"))
    with pytest.raises(ErroConversao):
        webm_para_ogg(_webm([]))
    with pytest.raises(ErroConversao):
        webm_para_ogg(b"OggS" + b"\x00" * 30)


def test_gravacao_cortada_no_fim_ainda_converte():
    inteiro = _webm([b"\xf8" + b"\x01" * 40 for _ in range(10)])
    ogg = webm_para_ogg(inteiro[:-20])
    assert 1 <= sum(len(p["pacotes"]) for p in _paginas(ogg)[2:]) <= 10


# ---------------------------------------------------------------------------- rotas (Postgres)
URL_PG = os.environ.get("AGENTESIA_TESTE_PG_URL")
precisa_pg = pytest.mark.skipif(not URL_PG, reason="sem AGENTESIA_TESTE_PG_URL")

if URL_PG:
    from tests.test_gestao import _entrar, ambiente  # noqa: F401  (fixture do painel com Postgres local)

OGG = b"OggS" + b"\x00" * 60


def _b64(dados: bytes) -> str:
    return base64.b64encode(dados).decode()


async def _escritorio(cliente, nome):
    return (await cliente.post("/api/admin/escritorios", json={
        "nome": nome, "id_conta_helena": str(uuid.uuid4()), "token_helena": "token-bom-123456"})).json()["escritorio"]


@precisa_pg
async def test_roteiro_do_texto_ao_audio_na_biblioteca(ambiente):
    cliente, _simulada, email_admin, banco = ambiente
    from app.gestao.rotas_roteiros import api as api_roteiros
    cliente._transport.app.include_router(api_roteiros)
    await _entrar(cliente, email_admin, "senha-admin-123")
    escritorio = await _escritorio(cliente, "Roteiros Ltda")
    h = {"x-escritorio": escritorio["id"]}
    pool = banco._pool

    assert (await cliente.get("/api/roteiros", headers=h)).json() == []
    canal = await pool.fetchval(
        "insert into agentesia_canais (id_escritorio, numero_normalizado, id_canal_helena) values ($1::uuid, $2, $3) returning id",
        escritorio["id"], "55119" + str(uuid.uuid4().int)[:8], "ch-" + uuid.uuid4().hex[:10])
    agente = str(await pool.fetchval(
        "insert into agentesia_agentes (id_escritorio, id_canal, nome, situacao, config) values ($1::uuid, $2, 'Ana', 'ativo', '{}'::jsonb) returning id",
        escritorio["id"], canal))
    await pool.execute("insert into agentesia_agente_etapas (id_agente, codigo, ordem, principal, instrucao) values ($1::uuid, 'closer', 1, true, 'x')", agente)

    opcoes = (await cliente.get("/api/roteiros/opcoes", headers=h)).json()
    assert opcoes["agentes"] == [{"id": agente, "nome": "Ana", "etapas": [{"codigo": "closer", "nome": "Closer"}]}]

    # Agente de outro escritório não vale.
    ruim = await cliente.post("/api/roteiros", headers=h, json={"titulo": "X", "id_agente": str(uuid.uuid4())})
    assert ruim.status_code == 400
    assert (await cliente.post("/api/roteiros", headers=h, json={"titulo": ""})).status_code == 422

    criado = await cliente.post("/api/roteiros", headers=h, json={
        "titulo": "Explicação dos honorários", "texto": "Olá! Os honorários são...", "id_agente": agente, "etapa": "closer"})
    assert criado.status_code == 200, criado.text
    roteiro = criado.json()
    assert roteiro["status"] == "a_gravar" and roteiro["agente_nome"] == "Ana" and roteiro["etapa_nome"] == "Closer"
    assert roteiro["midia"] is None
    rid = roteiro["id"]

    sem_audio = await cliente.patch(f"/api/roteiros/{rid}", headers=h, json={"status": "gravado"})
    assert sem_audio.status_code == 400

    # Gravação do Chrome (WebM/Opus) vira .ogg na biblioteca, com o título do roteiro.
    webm = _webm([b"\xf8" + b"\x02" * 50 for _ in range(25)])
    gravado = await cliente.post(f"/api/roteiros/{rid}/audio", headers=h,
                                 json={"conteudo_base64": _b64(webm), "mime": "audio/webm;codecs=opus"})
    assert gravado.status_code == 200, gravado.text
    g = gravado.json()
    assert g["status"] == "gravado" and g["midia"]["url"].endswith(".ogg") and g["midia"]["mime_type"] == "audio/ogg"
    assert g["midia"]["nome"] == "Explicação dos honorários"
    biblioteca = (await cliente.get("/api/midia", headers=h)).json()["itens"]
    assert [i["id"] for i in biblioteca] == [g["midia"]["id"]] and biblioteca[0]["tipo"] == "audio"

    # Formato que o WhatsApp não entrega é recusado.
    wav = await cliente.post(f"/api/roteiros/{rid}/audio", headers=h,
                             json={"conteudo_base64": _b64(b"RIFF\x00\x00\x00\x00WAVE" + b"\x00" * 20), "mime": "audio/wav", "nome": "a.wav"})
    assert wav.status_code == 400

    # Regravar troca o áudio e tira o antigo da biblioteca (ninguém usava).
    antigo = g["midia"]["id"]
    regravado = (await cliente.post(f"/api/roteiros/{rid}/audio", headers=h, json={"conteudo_base64": _b64(OGG), "mime": "audio/ogg"})).json()
    assert regravado["midia"]["id"] != antigo
    assert await pool.fetchval("select count(*) from agentesia_biblioteca_midia where id = $1::uuid", antigo) == 0

    # Outro escritório não vê nem mexe.
    outro = await _escritorio(cliente, "Outro Ltda")
    h2 = {"x-escritorio": outro["id"]}
    assert (await cliente.get(f"/api/roteiros/{rid}", headers=h2)).status_code == 404
    assert (await cliente.delete(f"/api/roteiros/{rid}", headers=h2)).status_code == 404
    assert (await cliente.get("/api/roteiros", headers=h2)).json() == []

    # Editar campos; tirar o agente com "".
    mudado = (await cliente.patch(f"/api/roteiros/{rid}", headers=h, json={"titulo": "Honorários", "id_agente": "", "etapa": ""})).json()
    assert mudado["titulo"] == "Honorários" and mudado["id_agente"] is None and mudado["etapa"] is None
    assert mudado["texto"] == "Olá! Os honorários são..."
    assert (await cliente.patch(f"/api/roteiros/{rid}", headers=h, json={"status": "qualquer"})).status_code == 400

    # Apagar o áudio na biblioteca devolve o roteiro para "a gravar".
    assert (await cliente.delete(f"/api/midia/{regravado['midia']['id']}", headers=h)).status_code == 200
    depois = (await cliente.get(f"/api/roteiros/{rid}", headers=h)).json()
    assert depois["status"] == "a_gravar" and depois["midia"] is None

    # Soltar o áudio mantém o arquivo na biblioteca.
    de_novo = (await cliente.post(f"/api/roteiros/{rid}/audio", headers=h, json={"conteudo_base64": _b64(OGG)})).json()
    solto = (await cliente.delete(f"/api/roteiros/{rid}/audio", headers=h)).json()
    assert solto["status"] == "a_gravar" and solto["midia"] is None
    assert await pool.fetchval("select count(*) from agentesia_biblioteca_midia where id = $1::uuid", de_novo["midia"]["id"]) == 1

    # Apagar o roteiro não apaga o áudio.
    assert (await cliente.delete(f"/api/roteiros/{rid}", headers=h)).json() == {"ok": True}
    assert (await cliente.get("/api/roteiros", headers=h)).json() == []
    assert await pool.fetchval("select count(*) from agentesia_biblioteca_midia where id = $1::uuid", de_novo["midia"]["id"]) == 1


@precisa_pg
async def test_atendente_nao_mexe_em_roteiro(ambiente):
    cliente, _simulada, email_admin, banco = ambiente
    from app.gestao.rotas_roteiros import api as api_roteiros
    cliente._transport.app.include_router(api_roteiros)
    await _entrar(cliente, email_admin, "senha-admin-123")
    escritorio = await _escritorio(cliente, "Visão Ltda")
    resposta = await cliente.get("/api/roteiros", headers={"x-escritorio": escritorio["id"], "x-visao": "atendente"})
    assert resposta.status_code == 403
