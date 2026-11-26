"""Confere, logo antes do envio, se o link de uma mídia do roteiro (áudio, vídeo, imagem) ainda abre.

A Helena só diz que a mensagem "entrou na fila": um link quebrado (mídia apagada da biblioteca, arquivo renomeado no
bucket, link colado errado) só aparecia como FAILED um minuto depois, e o lead ficava sem o áudio. Aqui um HEAD curto
decide antes:

  404 / 410 (e 400 do Storage do Supabase, que é como ele responde a objeto que não existe)  -> não envia;
  200 com página HTML (link de página do Drive, do site)                                     -> não envia;
  200 com tamanho acima do que o WhatsApp entrega (áudio e vídeo 16 MB, imagem 5 MB)          -> não envia;
  qualquer outra coisa (405, 403, 5xx, timeout, rede fora)                                   -> envia (na dúvida, a
  Helena tenta; a conferência de entrega de 1 minuto continua valendo).

O resultado fica guardado alguns minutos por URL: o mesmo áudio em vários leads não refaz o HEAD toda vez.
"""

from __future__ import annotations

import time
from urllib.parse import unquote, urlparse

import httpx

# Os testes trocam por um httpx.MockTransport (nenhum teste faz HEAD de verdade).
TRANSPORTE: httpx.AsyncBaseTransport | None = None
# Limites do WhatsApp (os mesmos da biblioteca de mídia, app/gestao/produtos.py LIMITES_POR_TIPO).
TAMANHO_MAXIMO = {"audio": 16 * 1024 * 1024, "video": 16 * 1024 * 1024, "imagem": 5 * 1024 * 1024}
_NAO_EXISTE = (404, 410)


def _do_storage_do_supabase(url: str) -> bool:
    return "/storage/v1/object/" in unquote(urlparse(url).path)


class ConferirLink:
    """Chamável: `await conferir(url, tipo)` -> None (pode enviar) ou o motivo, em português, para não enviar."""

    def __init__(self, *, timeout_s: float = 5.0, validade_s: float = 600.0,
                 transporte: httpx.AsyncBaseTransport | None = None) -> None:
        self.timeout_s = timeout_s
        self.validade_s = validade_s
        self._transporte = transporte
        self._guardados: dict[str, tuple[float, str | None]] = {}

    async def __call__(self, url: str, tipo: str = "audio") -> str | None:
        agora = time.monotonic()
        if (guardado := self._guardados.get(url)) and agora - guardado[0] < self.validade_s:
            return guardado[1]
        motivo = await self._conferir(url, tipo)
        self._guardados[url] = (agora, motivo)
        return motivo

    async def _conferir(self, url: str, tipo: str) -> str | None:
        try:
            async with httpx.AsyncClient(transport=self._transporte or TRANSPORTE, timeout=self.timeout_s,
                                         follow_redirects=True, headers={"User-Agent": "LawChat-IA"}) as http:
                resposta = await http.head(url)
        except httpx.HTTPError:
            return None                                   # rede ou timeout: na dúvida, envia
        codigo = resposta.status_code
        if codigo in _NAO_EXISTE or (codigo == 400 and _do_storage_do_supabase(url)):
            return f"o link não abre (HTTP {codigo}): o arquivo foi apagado ou o link mudou"
        if codigo >= 300:
            return None                                   # 403, 405, 5xx: o servidor não deixa conferir; envia
        if resposta.headers.get("content-type", "").lower().startswith("text/html"):
            return "o link abre uma página, não o arquivo de mídia"
        try:
            tamanho = int(resposta.headers.get("content-length") or 0)
        except ValueError:
            tamanho = 0
        limite = TAMANHO_MAXIMO.get(tipo)
        if limite and tamanho > limite:
            return (f"o arquivo tem {tamanho / 1_048_576:.1f} MB e o WhatsApp só entrega até "
                    f"{limite // 1_048_576} MB")
        return None
