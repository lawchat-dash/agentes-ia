"""Troca o "envelope" de um áudio WebM/Opus para Ogg/Opus, sem recodificar.

O Chrome e o Edge gravam pelo navegador (MediaRecorder) em audio/webm;codecs=opus. O WhatsApp só entrega como
mensagem de voz o áudio em Ogg/Opus. O som (os pacotes Opus) é o mesmo nos dois formatos: aqui só se lê os pacotes
do WebM (Matroska/EBML) e se escreve num Ogg (RFC 7845), com o cabeçalho OpusHead e as páginas com a posição
(granule) certa. Não usa ffmpeg nem biblioteca de fora.
"""

from __future__ import annotations

import struct

WEBM_ASSINATURA = b"\x1a\x45\xdf\xa3"

# IDs EBML usados (com o marcador de tamanho, como aparecem no arquivo).
_SEGMENTO, _CLUSTER, _TRILHAS, _TRILHA, _GRUPO = 0x18538067, 0x1F43B675, 0x1654AE6B, 0xAE, 0xA0
_AUDIO = 0xE1
_MESTRES = {_SEGMENTO, _CLUSTER, _TRILHAS, _TRILHA, _GRUPO, _AUDIO}
_NUMERO_TRILHA, _CODEC, _CODEC_PRIVADO, _CANAIS = 0xD7, 0x86, 0x63A2, 0x9F
_BLOCO_SIMPLES, _BLOCO = 0xA3, 0xA1


class ErroConversao(ValueError):
    """O arquivo não é um WebM com áudio Opus que dê para converter."""


def eh_webm(dados: bytes) -> bool:
    return dados[:4] == WEBM_ASSINATURA


def _vint(dados: bytes, pos: int, manter_marcador: bool) -> tuple[int, int, bool]:
    """Lê um inteiro de tamanho variável do EBML. Devolve (valor, nova posição, tamanho_desconhecido)."""
    if pos >= len(dados):
        raise ErroConversao("arquivo cortado")
    primeiro = dados[pos]
    largura = 1
    mascara = 0x80
    while largura <= 8 and not primeiro & mascara:
        largura += 1
        mascara >>= 1
    if largura > 8 or pos + largura > len(dados):
        raise ErroConversao("arquivo WebM inválido")
    valor = primeiro if manter_marcador else primeiro & (mascara - 1)
    for b in dados[pos + 1:pos + largura]:
        valor = (valor << 8) | b
    desconhecido = not manter_marcador and valor == (1 << (7 * largura)) - 1
    return valor, pos + largura, desconhecido


def _quadros_do_bloco(corpo: bytes) -> tuple[int, list[bytes]]:
    """(número da trilha, pacotes) de um SimpleBlock/Block."""
    trilha, pos, _ = _vint(corpo, 0, False)
    if pos + 3 > len(corpo):
        raise ErroConversao("bloco cortado")
    flags = corpo[pos + 2]
    pos += 3
    laco = (flags >> 1) & 0x03
    if laco == 0:
        return trilha, [corpo[pos:]]
    quantos = corpo[pos] + 1
    pos += 1
    if laco == 2:                                     # tamanho fixo
        resto = corpo[pos:]
        if len(resto) % quantos:
            raise ErroConversao("bloco com tamanho fixo inválido")
        passo = len(resto) // quantos
        return trilha, [resto[i * passo:(i + 1) * passo] for i in range(quantos)]
    tamanhos: list[int] = []
    if laco == 1:                                     # Xiph
        for _ in range(quantos - 1):
            tamanho = 0
            while True:
                b = corpo[pos]
                pos += 1
                tamanho += b
                if b != 255:
                    break
            tamanhos.append(tamanho)
    else:                                             # EBML
        primeiro, pos, _ = _vint(corpo, pos, False)
        tamanhos.append(primeiro)
        for _ in range(quantos - 2):
            bruto, novo, _ = _vint(corpo, pos, False)
            largura = novo - pos
            diferenca = bruto - ((1 << (7 * largura - 1)) - 1)
            pos = novo
            tamanhos.append(tamanhos[-1] + diferenca)
    quadros = []
    for tamanho in tamanhos:
        quadros.append(corpo[pos:pos + tamanho])
        pos += tamanho
    quadros.append(corpo[pos:])
    return trilha, quadros


def _ler_webm(dados: bytes) -> tuple[bytes | None, int, list[bytes]]:
    """(OpusHead do CodecPrivate ou None, canais, pacotes Opus da primeira trilha Opus)."""
    trilhas: dict[int, dict] = {}
    atual: dict = {}
    blocos: list[bytes] = []
    pos = 0
    while pos < len(dados):
        try:
            ident, pos, _ = _vint(dados, pos, True)
            tamanho, pos, desconhecido = _vint(dados, pos, False)
        except ErroConversao:
            break                                     # gravação cortada no fim: fica com o que já leu
        if ident in _MESTRES:
            if ident == _TRILHA:
                atual = {}
                trilhas[len(trilhas)] = atual
            continue                                  # entra no elemento (lê os filhos em sequência)
        if desconhecido:
            raise ErroConversao("arquivo WebM inválido")
        corpo = dados[pos:pos + tamanho]
        pos += tamanho
        if ident == _NUMERO_TRILHA:
            atual["numero"] = int.from_bytes(corpo, "big")
        elif ident == _CODEC:
            atual["codec"] = corpo.rstrip(b"\x00").decode("ascii", "ignore")
        elif ident == _CODEC_PRIVADO:
            atual["privado"] = corpo
        elif ident == _CANAIS:
            atual["canais"] = int.from_bytes(corpo, "big")
        elif ident in (_BLOCO_SIMPLES, _BLOCO):
            blocos.append(corpo)
    opus = next((t for t in trilhas.values() if t.get("codec") == "A_OPUS"), None)
    if opus is None:
        raise ErroConversao("o arquivo não tem áudio Opus (grave de novo pelo navegador ou envie .ogg/.mp3).")
    numero = opus.get("numero", 1)
    pacotes: list[bytes] = []
    for corpo in blocos:
        try:
            trilha, quadros = _quadros_do_bloco(corpo)
        except (ErroConversao, IndexError):
            continue
        if trilha == numero:
            pacotes.extend(q for q in quadros if q)
    if not pacotes:
        raise ErroConversao("a gravação está vazia.")
    privado = opus.get("privado")
    return (privado if privado and privado[:8] == b"OpusHead" else None), int(opus.get("canais") or 1), pacotes


def amostras_do_pacote(pacote: bytes) -> int:
    """Quantas amostras (a 48 kHz) um pacote Opus tem, pelo byte TOC (RFC 6716, 3.1)."""
    toc = pacote[0]
    config = toc >> 3
    if config < 12:
        duracao = (480, 960, 1920, 2880)[config % 4]
    elif config < 16:
        duracao = (480, 960)[config % 2]
    else:
        duracao = (120, 240, 480, 960)[config % 4]
    codigo = toc & 0x03
    quadros = 1 if codigo == 0 else 2 if codigo in (1, 2) else (pacote[1] & 0x3F if len(pacote) > 1 else 1)
    return duracao * quadros


def _tabela_crc() -> list[int]:
    tabela = []
    for i in range(256):
        r = i << 24
        for _ in range(8):
            r = ((r << 1) ^ 0x04C11DB7) if r & 0x80000000 else (r << 1)
        tabela.append(r & 0xFFFFFFFF)
    return tabela


_CRC = _tabela_crc()


def crc_ogg(dados: bytes) -> int:
    crc = 0
    for b in dados:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ _CRC[((crc >> 24) & 0xFF) ^ b]
    return crc


def _pagina(pacotes: list[bytes], tipo: int, granule: int, serie: int, sequencia: int) -> bytes:
    segmentos = bytearray()
    for pacote in pacotes:
        n = len(pacote)
        segmentos.extend(b"\xff" * (n // 255))
        segmentos.append(n % 255)
    cabeca = struct.pack("<4sBBqIIIB", b"OggS", 0, tipo, granule, serie, sequencia, 0, len(segmentos)) + bytes(segmentos)
    pagina = bytearray(cabeca + b"".join(pacotes))
    pagina[22:26] = struct.pack("<I", crc_ogg(bytes(pagina)))
    return bytes(pagina)


def webm_para_ogg(dados: bytes, serie: int = 0x4C415743) -> bytes:
    """Converte WebM/Opus em Ogg/Opus. Levanta ErroConversao se não der."""
    if not eh_webm(dados):
        raise ErroConversao("o arquivo não é WebM.")
    cabeca, canais, pacotes = _ler_webm(dados)
    if cabeca is None:
        cabeca = b"OpusHead" + struct.pack("<BBHIhB", 1, max(1, min(2, canais)), 312, 48000, 0, 0)
    tags = b"OpusTags" + struct.pack("<I", 7) + b"LawChat" + struct.pack("<I", 0)
    saida = [_pagina([cabeca], 0x02, 0, serie, 0), _pagina([tags], 0x00, 0, serie, 1)]
    sequencia, granule = 2, 0
    lote: list[bytes] = []
    segs = 0
    for i, pacote in enumerate(pacotes):
        precisa = len(pacote) // 255 + 1
        if lote and (segs + precisa > 255 or len(lote) >= 50):
            saida.append(_pagina(lote, 0x00, granule, serie, sequencia))
            sequencia += 1
            lote, segs = [], 0
        lote.append(pacote)
        segs += precisa
        granule += amostras_do_pacote(pacote)
    saida.append(_pagina(lote, 0x04, granule, serie, sequencia))
    return b"".join(saida)
