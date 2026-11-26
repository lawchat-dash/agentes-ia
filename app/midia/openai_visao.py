"""Imagem, áudio e PDF escaneado pela OpenAI (novidade: o n8n não lia documento). Usa a chave do servidor (OPENAI_API_KEY)."""

from __future__ import annotations

import base64
import time

from app.modelo import Chamada, ErroModelo, calcular_custo

PROMPT_IMAGEM = """Um lead mandou esta imagem pelo WhatsApp para um escritório de advocacia previdenciária.
Diga em até 6 linhas: que tipo de imagem é (documento, laudo, CAT, carta do INSS, receita, foto de lesão, print de conversa, outra);
o que está escrito de importante (datas, benefício, CID, conclusão); e se está legível.
Não copie CPF, RG, endereço completo nem dados bancários. Não invente o que não dá para ler."""


# Sem o uso na resposta: estimativa pela duração (áudio do WhatsApp em opus ~2 KB por segundo), preço de referência
# por minuto da transcrição (conferir na página da OpenAI).
USD_POR_MINUTO_DE_AUDIO = 0.003


def custo_estimado_do_audio(tamanho_bytes: int) -> float:
    minutos = max(1, tamanho_bytes) / 2000 / 60
    return round(minutos * USD_POR_MINUTO_DE_AUDIO, 6)


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
        uso = getattr(resposta, "usage", None)
        entrada, saida = (getattr(uso, "input_tokens", 0) or 0), (getattr(uso, "output_tokens", 0) or 0)
        if entrada or saida:
            chamada.tokens_entrada, chamada.tokens_saida = int(entrada), int(saida)
            chamada.custo_usd = calcular_custo(self.modelo_audio, chamada.tokens_entrada, chamada.tokens_saida, 0)
        else:
            chamada.custo_usd = custo_estimado_do_audio(len(dados))
        return (getattr(resposta, "text", "") or "").strip(), chamada
