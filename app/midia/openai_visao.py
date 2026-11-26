"""Imagem, áudio e PDF escaneado pela OpenAI (novidade: o n8n não lia documento). Usa a chave do servidor (OPENAI_API_KEY)."""

from __future__ import annotations

import base64
import logging
import struct
import time

from app.modelo import Chamada, ErroModelo, calcular_custo, calcular_custo_transcricao, custo_por_minuto_transcricao

PROMPT_IMAGEM = """Um lead mandou esta imagem pelo WhatsApp para um escritório de advocacia previdenciária.
Diga em até 6 linhas: que tipo de imagem é (documento, laudo, CAT, carta do INSS, receita, foto de lesão, print de conversa, outra);
o que está escrito de importante (datas, benefício, CID, conclusão); e se está legível.
Não copie CPF, RG, endereço completo nem dados bancários. Não invente o que não dá para ler."""


log = logging.getLogger("agentesia.midia")

# Último recurso, só para ÁUDIO sem o uso na resposta e sem duração legível: áudio do WhatsApp em opus ~2 KB por segundo.
# Vídeo nunca é estimado por bytes (o arquivo é quase todo imagem).
USD_POR_MINUTO_DE_AUDIO = 0.003


def custo_estimado_do_audio(tamanho_bytes: int) -> float:
    minutos = max(1, tamanho_bytes) / 2000 / 60
    return round(minutos * USD_POR_MINUTO_DE_AUDIO, 6)


def duracao_em_segundos(dados: bytes) -> float | None:
    """Duração real lida do próprio arquivo: OGG/Opus (granule da última página), MP4/M4A (mvhd) e WAV. None = não deu."""
    try:
        if dados.startswith(b"OggS") and b"OpusHead" in dados[:200]:
            ultima = dados.rfind(b"OggS")
            granulo = struct.unpack_from("<q", dados, ultima + 6)[0]
            return granulo / 48000 if granulo > 0 else None
        if dados[4:8] == b"ftyp":
            pos = dados.find(b"mvhd")
            if pos < 0:
                return None
            versao = dados[pos + 4]
            if versao == 1:
                escala, duracao = struct.unpack_from(">IQ", dados, pos + 4 + 4 + 16)
            else:
                escala, duracao = struct.unpack_from(">II", dados, pos + 4 + 4 + 8)
            return duracao / escala if escala else None
        if dados[:4] == b"RIFF" and dados[8:12] == b"WAVE":
            bytes_por_segundo = struct.unpack_from("<I", dados, 28)[0]
            pos = dados.find(b"data", 12)
            if bytes_por_segundo and pos > 0:
                return struct.unpack_from("<I", dados, pos + 4)[0] / bytes_por_segundo
    except (struct.error, IndexError):
        return None
    return None


class VisaoOpenAI:
    def __init__(self, modelo: str = "gpt-4.1-mini", modelo_audio: str = "gpt-4o-mini-transcribe") -> None:
        from app.modelo import cliente_openai

        self._cliente = cliente_openai()
        self.modelo = modelo
        self.modelo_audio = modelo_audio

    def _uso(self, chamada: Chamada, resposta: object) -> None:
        uso = getattr(resposta, "usage", None)
        if uso:
            cache = getattr(getattr(uso, "prompt_tokens_details", None), "cached_tokens", 0) or 0
            chamada.tokens_entrada, chamada.tokens_saida, chamada.tokens_cache = uso.prompt_tokens - cache, uso.completion_tokens, cache
            chamada.custo_usd = calcular_custo(self.modelo, chamada.tokens_entrada, chamada.tokens_saida, cache)

    async def _perguntar(self, papel: str, conteudo: list[dict], max_tokens: int) -> tuple[str, Chamada]:
        import openai

        chamada = Chamada(papel=papel, modelo=self.modelo)
        inicio = time.monotonic()
        try:
            resposta = await self._cliente.chat.completions.create(
                model=self.modelo, messages=[{"role": "user", "content": conteudo}], max_completion_tokens=max_tokens)
        except openai.APIError as erro:
            chamada.sucesso, chamada.erro = False, type(erro).__name__
            raise ErroModelo("visao", str(erro)) from erro
        finally:
            chamada.duracao_ms = int((time.monotonic() - inicio) * 1000)
        self._uso(chamada, resposta)
        return (resposta.choices[0].message.content or "").strip(), chamada

    async def descrever_imagem(self, url: str, mime: str | None, legenda: str | None) -> tuple[str, Chamada]:
        """`url`: data URL com os bytes da imagem (o normal; app/midia baixa antes) ou a URL pública (reserva)."""
        conteudo = [{"type": "text", "text": PROMPT_IMAGEM + (f"\nLegenda que o lead escreveu: {legenda}" if legenda else "")},
                    {"type": "image_url", "image_url": {"url": url, "detail": "high"}}]
        return await self._perguntar("descrever_imagem", conteudo, 500)

    async def ler_pdf(self, dados: bytes) -> tuple[str, Chamada]:
        """PDF escaneado (sem texto): o modelo com visão lê as páginas e resume como os documentos com texto."""
        from app.midia import PROMPT_RESUMO

        arquivo = {"filename": "documento.pdf", "file_data": "data:application/pdf;base64," + base64.b64encode(dados).decode()}
        conteudo = [{"type": "file", "file": arquivo},
                    {"type": "text", "text": PROMPT_RESUMO + "\nResponda só com o resumo, em texto corrido."}]
        return await self._perguntar("ler_pdf", conteudo, 900)

    async def transcrever_audio(self, dados: bytes, nome: str) -> tuple[str, Chamada]:
        import openai

        chamada = Chamada(papel="transcrever_audio", modelo=self.modelo_audio)
        inicio = time.monotonic()
        try:
            resposta = await self._cliente.audio.transcriptions.create(
                model=self.modelo_audio, file=(nome, dados), language="pt")
        except openai.APIError as erro:
            chamada.sucesso, chamada.erro = False, type(erro).__name__
            raise ErroModelo("transcricao", str(erro)) from erro
        finally:
            chamada.duracao_ms = int((time.monotonic() - inicio) * 1000)
        self._custo_da_transcricao(chamada, getattr(resposta, "usage", None), dados, nome)
        return (getattr(resposta, "text", "") or "").strip(), chamada

    def _custo_da_transcricao(self, chamada: Chamada, uso: object, dados: bytes, nome: str) -> None:
        """Uma Chamada só, com o custo certo: tokens de áudio a um preço, de texto a outro, saída a outro. Sem tokens:
        segundos do uso, senão a duração lida do arquivo; por bytes só áudio (nunca vídeo)."""
        entrada, saida = int(getattr(uso, "input_tokens", 0) or 0), int(getattr(uso, "output_tokens", 0) or 0)
        if entrada or saida:
            detalhes = getattr(uso, "input_token_details", None)
            audio = int(getattr(detalhes, "audio_tokens", 0) or 0)
            texto = getattr(detalhes, "text_tokens", None)
            texto = int(texto) if texto is not None else max(0, entrada - audio)
            if detalhes is None:
                audio, texto = entrada, 0          # sem o detalhe, a entrada da transcrição é áudio
            chamada.tokens_entrada, chamada.tokens_saida = audio + texto, saida
            chamada.custo_usd = calcular_custo_transcricao(self.modelo_audio, audio, texto, saida)
            return
        segundos = getattr(uso, "seconds", None) or duracao_em_segundos(dados)
        if segundos:
            chamada.custo_usd = custo_por_minuto_transcricao(self.modelo_audio, float(segundos))
        elif not nome.startswith("video"):
            chamada.custo_usd = custo_estimado_do_audio(len(dados))
        else:
            log.warning("transcrição de vídeo sem uso nem duração legível: custo não estimado (%d bytes)", len(dados))
