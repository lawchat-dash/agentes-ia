"""Conversão de mídia com ffmpeg para os formatos que o WhatsApp entrega (roteiro de gravação).

- Vídeo: WebM (Chrome/Android gravando no navegador), MOV (iPhone) e MP4 de outros codecs viram MP4 H.264/AAC, até
  16 MB (limite do WhatsApp). Se a primeira passada ficar grande, tenta de novo com menos qualidade e menor resolução.
- Áudio: WAV, AAC, WEBM e outros viram Ogg/Opus (chega como mensagem de voz).

ffmpeg vem da imagem (Dockerfile.painel e Dockerfile.ia). Sem ele, ErroConversao com uma mensagem clara.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile

LIMITE_VIDEO = 16 * 1024 * 1024
LIMITE_AUDIO = 16 * 1024 * 1024
_TETO_S = 180   # nenhuma conversão passa disso (vídeo de roteiro tem poucos minutos)


class ErroConversao(Exception):
    pass


def tem_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


async def _rodar(entrada: bytes, sufixo_entrada: str, sufixo_saida: str, argumentos: list[str]) -> bytes:
    if not tem_ffmpeg():
        raise ErroConversao("o servidor ainda não tem o conversor de vídeo (ffmpeg). Envie em .mp4 ou avise a equipe.")
    with tempfile.TemporaryDirectory(prefix="lawchat-conv-") as pasta:
        origem = os.path.join(pasta, f"entrada{sufixo_entrada}")
        destino = os.path.join(pasta, f"saida{sufixo_saida}")
        with open(origem, "wb") as arquivo:
            arquivo.write(entrada)
        processo = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", origem, *argumentos, destino,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        try:
            _, erro = await asyncio.wait_for(processo.communicate(), timeout=_TETO_S)
        except asyncio.TimeoutError as tempo:
            processo.kill()
            raise ErroConversao("a conversão demorou demais. Grave um trecho mais curto.") from tempo
        if processo.returncode != 0 or not os.path.exists(destino):
            detalhe = (erro or b"").decode("utf-8", "replace").strip().splitlines()[-1:] or [""]
            raise ErroConversao(f"não deu para converter o arquivo ({detalhe[0][:160]}).")
        with open(destino, "rb") as arquivo:
            return arquivo.read()


async def codecs(bruto: bytes, sufixo: str = ".mp4") -> tuple[str | None, str | None] | None:
    """(codec do vídeo, codec do áudio) pelo ffprobe, ex.: ("h264", "aac"); None no lugar de uma faixa que não existe.
    None no todo = não deu para saber (sem ffprobe, arquivo que ele não lê ou demorou demais)."""
    if shutil.which("ffprobe") is None:
        return None
    with tempfile.TemporaryDirectory(prefix="lawchat-probe-") as pasta:
        origem = os.path.join(pasta, f"entrada{sufixo}")
        with open(origem, "wb") as arquivo:
            arquivo.write(bruto)
        try:
            processo = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name", "-of", "json", origem,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        except OSError:
            return None
        try:
            saida, _ = await asyncio.wait_for(processo.communicate(), timeout=30)
        except asyncio.TimeoutError:
            processo.kill()
            return None
        if processo.returncode != 0:
            return None
        try:
            faixas = json.loads(saida or b"{}").get("streams") or []
        except ValueError:
            return None
    video = next((f.get("codec_name") for f in faixas if f.get("codec_type") == "video"), None)
    audio = next((f.get("codec_name") for f in faixas if f.get("codec_type") == "audio"), None)
    return video, audio


async def para_mp4(bruto: bytes, sufixo: str = ".webm") -> bytes:
    """Qualquer vídeo → MP4 (H.264 + AAC, faststart) até 16 MB."""
    tentativas = [("720", "26", "96k"), ("540", "30", "80k"), ("480", "34", "64k")]
    saida = b""
    for altura, crf, audio in tentativas:
        saida = await _rodar(bruto, sufixo, ".mp4", [
            "-vf", f"scale=-2:'min({altura},ih)'", "-c:v", "libx264", "-preset", "veryfast", "-crf", crf,
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", audio, "-ac", "1", "-movflags", "+faststart"])
        if len(saida) <= LIMITE_VIDEO:
            return saida
    raise ErroConversao(f"o vídeo ficou com {len(saida) / 1_048_576:.0f} MB depois de convertido e o limite do "
                        "WhatsApp é 16 MB. Grave um vídeo mais curto.")


async def para_ogg(bruto: bytes, sufixo: str = ".wav") -> bytes:
    """Qualquer áudio → Ogg/Opus mono (mensagem de voz)."""
    saida = await _rodar(bruto, sufixo, ".ogg", ["-vn", "-c:a", "libopus", "-b:a", "48k", "-ac", "1", "-application", "voip"])
    if len(saida) > LIMITE_AUDIO:
        raise ErroConversao("o áudio passou de 16 MB. Grave um trecho mais curto.")
    return saida
