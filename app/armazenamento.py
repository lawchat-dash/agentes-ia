"""Onde fica a mídia da biblioteca (áudio, vídeo e imagem que o roteiro manda ao lead).

  local     disco do servidor (AGENTESIA_PASTA_MIDIA, padrão <raiz>/dados/midia), servido em /midia pelo próprio app.
            Para desenvolvimento e testes: no Easypanel o disco não é compartilhado entre os apps nem sobrevive ao deploy.
  supabase  bucket público do Supabase Storage (API REST, via httpx). A Helena baixa o arquivo pela URL pública.

Escolha por AGENTESIA_MIDIA_ARMAZENAMENTO=local|supabase (padrão local). No modo supabase:
AGENTESIA_SUPABASE_URL (https://<projeto>.supabase.co), AGENTESIA_SUPABASE_SERVICE_KEY (service role; segredo, só em env)
e AGENTESIA_MIDIA_BUCKET (padrão "agentesia-midia"). O bucket é criado pelo dono (db/exemplos/criar_bucket_midia.sql).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

import httpx

log = logging.getLogger("agentesia")

BUCKET_PADRAO = "agentesia-midia"
MODOS = ("local", "supabase")
# Os testes trocam por um httpx.MockTransport (nenhum teste chama o Supabase de verdade).
TRANSPORTE: httpx.AsyncBaseTransport | None = None


class ErroArmazenamento(Exception):
    """Falha ao gravar ou apagar no armazenamento (mensagem própria para o painel; nunca leva a chave)."""


class Armazenamento(Protocol):
    modo: str

    def url_publica(self, caminho: str) -> str: ...

    async def enviar(self, caminho: str, bruto: bytes, mime: str) -> str: ...

    async def apagar(self, caminho: str) -> None: ...


def modo() -> str:
    escolhido = os.environ.get("AGENTESIA_MIDIA_ARMAZENAMENTO", "").strip().lower() or "local"
    if escolhido not in MODOS:
        raise ErroArmazenamento(f"AGENTESIA_MIDIA_ARMAZENAMENTO inválido: {escolhido!r} (use local ou supabase).")
    return escolhido


def pasta_local() -> Path:
    return Path(os.environ.get("AGENTESIA_PASTA_MIDIA") or Path(__file__).resolve().parents[1] / "dados" / "midia")


class ArmazenamentoLocal:
    """O comportamento de sempre: grava em disco e a URL é {AGENTESIA_URL_PUBLICA}/midia/{caminho}."""

    modo = "local"

    def __init__(self, pasta: Path | None = None, url_base: str | None = None) -> None:
        self.pasta = pasta or pasta_local()
        self.url_base = (url_base if url_base is not None else os.environ.get("AGENTESIA_URL_PUBLICA", "")).rstrip("/")

    def _arquivo(self, caminho: str) -> Path | None:
        arquivo = self.pasta / caminho
        return arquivo if arquivo.resolve().is_relative_to(self.pasta.resolve()) else None   # nada de ../

    def url_publica(self, caminho: str) -> str:
        return f"{self.url_base}/midia/{caminho}"

    async def enviar(self, caminho: str, bruto: bytes, mime: str) -> str:
        arquivo = self._arquivo(caminho)
        if arquivo is None:
            raise ErroArmazenamento("Caminho de arquivo inválido.")
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_bytes(bruto)
        return self.url_publica(caminho)

    async def apagar(self, caminho: str) -> None:
        arquivo = self._arquivo(caminho)
        if arquivo is not None and arquivo.exists():
            arquivo.unlink()


class ArmazenamentoSupabase:
    """Bucket do Supabase Storage. Upload e delete com a service role; leitura pela URL pública (bucket público)."""

    modo = "supabase"

    def __init__(self, url: str, chave: str, bucket: str = BUCKET_PADRAO,
                 transporte: httpx.AsyncBaseTransport | None = None, timeout_s: float = 60.0) -> None:
        self.url = url.rstrip("/")
        self.bucket = bucket
        self._chave = chave
        self._transporte = transporte
        self._timeout_s = timeout_s

    def __repr__(self) -> str:                           # nunca mostra a chave
        return f"ArmazenamentoSupabase(url={self.url!r}, bucket={self.bucket!r})"

    def _objeto(self, caminho: str) -> str:
        return f"{self.url}/storage/v1/object/{quote(self.bucket)}/{quote(caminho)}"

    def prefixo_publico(self) -> str:
        return f"{self.url}/storage/v1/object/public/{quote(self.bucket)}/"

    def url_publica(self, caminho: str) -> str:
        return self.prefixo_publico() + quote(caminho)

    def caminho_da_url(self, url: str | None) -> str | None:
        """O caminho no bucket se a URL é deste bucket; None se é de outro lugar (por exemplo, mídia antiga local)."""
        prefixo = self.prefixo_publico()
        return url[len(prefixo):] if url and url.startswith(prefixo) else None

    def _cabecalhos(self, **extras: str) -> dict[str, str]:
        return {"authorization": f"Bearer {self._chave}", "apikey": self._chave, **extras}

    def _cliente(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self._transporte or TRANSPORTE, timeout=self._timeout_s)

    async def enviar(self, caminho: str, bruto: bytes, mime: str) -> str:
        try:
            async with self._cliente() as http:
                resposta = await http.post(self._objeto(caminho), content=bruto, headers=self._cabecalhos(**{
                    "content-type": mime or "application/octet-stream", "cache-control": "max-age=31536000",
                    "x-upsert": "false"}))
        except httpx.HTTPError as erro:
            log.warning("Storage do Supabase fora do ar no envio de mídia: %s", type(erro).__name__)
            raise ErroArmazenamento("Não foi possível guardar o arquivo agora (Storage fora do ar). Tente de novo.") from erro
        if resposta.status_code >= 300:
            log.warning("Storage do Supabase recusou o envio de mídia: %s %s", resposta.status_code, resposta.text[:300])
            raise ErroArmazenamento(f"O Storage recusou o arquivo (HTTP {resposta.status_code}). Confira o bucket "
                                    f"'{self.bucket}' e a chave de serviço.")
        return self.url_publica(caminho)

    async def apagar(self, caminho: str) -> None:
        """Apagar o que já não existe não é erro (404, ou 400 com "not found", que é como o Storage responde)."""
        try:
            async with self._cliente() as http:
                resposta = await http.delete(self._objeto(caminho), headers=self._cabecalhos())
        except httpx.HTTPError as erro:
            log.warning("Storage do Supabase fora do ar ao apagar mídia: %s", type(erro).__name__)
            raise ErroArmazenamento("Não foi possível apagar o arquivo agora (Storage fora do ar). Tente de novo.") from erro
        if resposta.status_code < 300 or resposta.status_code == 404:
            return
        if resposta.status_code == 400 and "not found" in resposta.text.lower():
            return
        log.warning("Storage do Supabase recusou apagar mídia: %s %s", resposta.status_code, resposta.text[:300])
        raise ErroArmazenamento(f"O Storage recusou apagar o arquivo (HTTP {resposta.status_code}).")


def supabase_do_ambiente() -> ArmazenamentoSupabase | None:
    """O bucket configurado no ambiente, ou None se faltar a URL ou a chave."""
    url = os.environ.get("AGENTESIA_SUPABASE_URL", "").strip()
    chave = os.environ.get("AGENTESIA_SUPABASE_SERVICE_KEY", "").strip()
    if not url or not chave:
        return None
    return ArmazenamentoSupabase(url, chave, os.environ.get("AGENTESIA_MIDIA_BUCKET", "").strip() or BUCKET_PADRAO)


def do_ambiente() -> Armazenamento:
    """O armazenamento escolhido por AGENTESIA_MIDIA_ARMAZENAMENTO. No modo supabase, falta de URL/chave é erro claro."""
    if modo() == "local":
        return ArmazenamentoLocal()
    supabase = supabase_do_ambiente()
    if supabase is None:
        raise ErroArmazenamento("Mídia no Supabase sem configuração: preencha AGENTESIA_SUPABASE_URL e "
                                "AGENTESIA_SUPABASE_SERVICE_KEY (ou use AGENTESIA_MIDIA_ARMAZENAMENTO=local).")
    if not supabase.url.lower().startswith("https://"):
        raise ErroArmazenamento("AGENTESIA_SUPABASE_URL precisa começar com https://.")
    return supabase


def de_uma_midia(url: str | None) -> Armazenamento | None:
    """Onde está guardada uma mídia já gravada, pela URL dela: no bucket (se a URL é do bucket configurado) ou no disco
    local (mídia antiga, com URL /midia/...). None = é do bucket mas o Supabase não está configurado aqui."""
    supabase = supabase_do_ambiente()
    if supabase is not None and supabase.caminho_da_url(url) is not None:
        return supabase
    if url and "/storage/v1/object/public/" in url:
        return None
    return ArmazenamentoLocal()
