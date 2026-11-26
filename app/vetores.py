"""Vetores (embeddings) da base de conhecimento.

Modelo: OpenAI text-embedding-3-small (1536 dimensões), como no sistema de referência.
Os vetores ficam como real[] no Postgres e a semelhança é calculada aqui: a base de um agente tem poucas centenas de
trechos, então não precisa de extensão no banco. Os vetores são normalizados uma vez (no cache) e a semelhança vira
um produto escalar (`math.sumprod`), ~3x mais rápido que o cosseno completo.
"""

from __future__ import annotations

import hashlib
import math
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Protocol

MODELO = "text-embedding-3-small"
DIMENSOES = 1536
PRECO_USD_POR_MILHAO = 0.02
# Nota mínima (cosseno + reforço por palavra) para um trecho entrar no prompt. Valor inicial para o 3-small:
# calibrar com perguntas reais (docs/BASE_DE_CONHECIMENTO.md, seção 8). Por agente: config.conhecimento.nota_minima.
LIMIAR_MINIMO = 0.35


@dataclass
class Vetorizado:
    vetores: list[list[float]]
    tokens: int
    custo_usd: float


class ErroVetorizacao(Exception):
    """Um lote falhou depois de outros já pagos: `tokens` e `custo_usd` são dos lotes que a OpenAI já cobrou."""

    def __init__(self, mensagem: str, tokens: int, custo_usd: float) -> None:
        super().__init__(mensagem)
        self.tokens, self.custo_usd = tokens, custo_usd


class Vetorizador(Protocol):
    modelo: str
    dimensoes: int

    async def vetorizar(self, textos: list[str]) -> Vetorizado: ...


def custo(tokens: int, modelo: str = MODELO) -> float:
    from app.modelo import calcular_custo

    return calcular_custo(modelo, tokens, 0, 0) or round(tokens / 1_000_000 * PRECO_USD_POR_MILHAO, 8)


class VetorizadorOpenAI:
    falso = False

    def __init__(self, cliente=None, modelo: str = MODELO, dimensoes: int = DIMENSOES) -> None:
        if cliente is None:
            from app.modelo import cliente_openai
            cliente = cliente_openai()
        self._cliente = cliente
        self.modelo, self.dimensoes = modelo, dimensoes

    async def vetorizar(self, textos: list[str]) -> Vetorizado:
        vetores: list[list[float]] = []
        tokens = 0
        for inicio in range(0, len(textos), 96):                 # lotes: limite de entrada da API
            try:
                resposta = await self._cliente.embeddings.create(model=self.modelo, input=textos[inicio:inicio + 96])
            except Exception as erro:
                if tokens:                                        # os lotes anteriores já foram cobrados
                    raise ErroVetorizacao(str(erro), tokens, custo(tokens, self.modelo)) from erro
                raise
            vetores.extend(item.embedding for item in resposta.data)
            tokens += getattr(resposta.usage, "total_tokens", 0) or 0
        return Vetorizado(vetores, tokens, custo(tokens, self.modelo))


class VetorizadorFalso:
    """Para testes e demonstração: vetor por palavras (com hash), parecido com uma busca por termos.
    Não serve para calibrar a nota mínima: no modo falso a busca usa só palavras (ver conhecimento_indice.buscar)."""

    falso = True

    def __init__(self, dimensoes: int = 256) -> None:
        self._dim = dimensoes
        self.dimensoes = dimensoes
        self.modelo = "falso"
        self.chamadas = 0
        self.textos: list[str] = []

    async def vetorizar(self, textos: list[str]) -> Vetorizado:
        self.chamadas += 1
        self.textos.extend(textos)
        vetores = []
        for texto in textos:
            v = [0.0] * self._dim
            for palavra in re.findall(r"[a-zà-ú0-9]{3,}", texto.lower()):
                v[int(hashlib.md5(palavra.encode()).hexdigest(), 16) % self._dim] += 1.0
            vetores.append(v)
        tokens = sum(len(t) // 4 for t in textos)
        return Vetorizado(vetores, tokens, 0.0)


def cosseno(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    produto_ = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return produto_ / (na * nb) if na and nb else 0.0


def normalizar(v: list[float]) -> list[float]:
    """Vetor com norma 1 (o produto escalar de dois normalizados é o cosseno)."""
    norma = math.sqrt(math.sumprod(v, v)) if v else 0.0
    return [x / norma for x in v] if norma else list(v)


def produto(a: list[float], b: list[float]) -> float:
    """Produto escalar (= cosseno, se os dois estão normalizados). Dimensões diferentes = 0."""
    if not a or not b or len(a) != len(b):
        return 0.0
    return math.sumprod(a, b)


def hash_do_texto(modelo: str, texto: str) -> str:
    """Chave do cache de embedding de trecho: texto igual com o mesmo modelo não é vetorizado de novo."""
    return hashlib.sha256(f"{modelo}\n{texto}".encode("utf-8")).hexdigest()


class CacheDeConsultas:
    """LRU dos vetores de consulta ("quanto custa?" se repete muito): até 2.000 entradas, 1 hora cada."""

    def __init__(self, maximo: int = 2000, validade_s: float = 3600.0) -> None:
        self._itens: OrderedDict[tuple[str, str], tuple[float, list[float]]] = OrderedDict()
        self.maximo, self.validade_s = maximo, validade_s
        self.acertos = self.faltas = 0

    @staticmethod
    def _chave(modelo: str, consulta: str) -> tuple[str, str]:
        return modelo, " ".join(consulta.lower().split())

    def pegar(self, modelo: str, consulta: str) -> list[float] | None:
        chave = self._chave(modelo, consulta)
        item = self._itens.get(chave)
        if item is None or item[0] < time.monotonic():
            if item is not None:
                del self._itens[chave]
            self.faltas += 1
            return None
        self._itens.move_to_end(chave)
        self.acertos += 1
        return item[1]

    def guardar(self, modelo: str, consulta: str, vetor: list[float]) -> None:
        chave = self._chave(modelo, consulta)
        self._itens[chave] = (time.monotonic() + self.validade_s, vetor)
        self._itens.move_to_end(chave)
        while len(self._itens) > self.maximo:
            self._itens.popitem(last=False)

    def __len__(self) -> int:
        return len(self._itens)
