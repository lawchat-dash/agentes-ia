"""Cassete: grava as respostas do modelo de verdade e toca de novo, de graça e sem chave.

ModeloGravador(interno, caminho, modo) tem a mesma interface de Modelo.gerar:
  tocar     só toca; pedido sem resposta gravada -> CasseteSemResposta (e fica em `faltas`)
  novos     toca o que existe e grava o que falta (chama o interno)
  gravar    chama o interno em tudo e grava em <id>.jsonl.tmp; só `confirmar()` troca pelo cassete definitivo
            (o anterior fica intacto se a conversa for cortada pelo teto ou der erro: `descartar()`)
  desligado só repassa ao interno

Chave do pedido: sha256 de {papel, modelo, sistema, conteudo, esquema, temperatura, esforco} (uuid normalizado),
mais o número da ocorrência. Formato JSONL:
  {"tipo":"sistema","hash","texto"}                       (uma vez por sistema)
  {"tipo":"pedido","chave","n","papel","modelo","sistema":<hash>,"conteudo","dados","chamadas":[...]}

CasseteSemResposta herda de Exception, não de ErroModelo: ErroModelo viraria o silêncio "IA fora do ar" e o
teste passaria calado. Como o pipeline engole exceções do turno, o simulador confere `faltas` a cada fala.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from app.modelo import Chamada, ErroModelo, Modelo, Resultado

_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE)
MODOS = ("tocar", "novos", "gravar", "desligado")


class CasseteSemResposta(Exception):
    """O cassete não tem a resposta deste pedido (o prompt ou o código mudou). Regrave o cenário."""


def normalizar(texto: str) -> str:
    return _UUID.sub("<uuid>", texto or "")


def _hash(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def chave_do_pedido(*, papel: str, modelo: str, sistema: str, conteudo: str, esquema: dict[str, Any],
                    temperatura: float | None, esforco: str) -> str:
    corpo = json.dumps({"papel": papel, "modelo": modelo, "sistema": normalizar(sistema), "conteudo": normalizar(conteudo),
                        "esquema": esquema, "temperatura": temperatura, "esforco": esforco},
                       sort_keys=True, ensure_ascii=False)
    return _hash(corpo)


class ModeloGravador:
    def __init__(self, interno: Modelo | None, caminho: Path | str, modo: str = "tocar", *, nome: str = "") -> None:
        if modo not in MODOS:
            raise ValueError(f"modo do cassete inválido: {modo} (use {', '.join(MODOS)})")
        if modo != "tocar" and interno is None:
            raise ValueError(f"o modo {modo} precisa de um modelo de verdade por baixo")
        self.interno = interno
        self.caminho = Path(caminho)
        self.modo = modo
        self.nome = nome or self.caminho.stem
        self.faltas: list[str] = []
        self.tocados = 0
        self.gravados = 0
        self._sistemas: dict[str, str] = {}
        self._pedidos: dict[tuple[str, int], dict[str, Any]] = {}
        self._contagem: dict[str, int] = {}
        self._escritos: set[str] = set()                   # sistemas já escritos neste arquivo
        if modo in ("tocar", "novos") and self.caminho.exists():
            self._ler()
        # Ao gravar, escreve num temporário: o cassete bom só é trocado quando a conversa termina (confirmar).
        self.temporario = self.caminho.with_name(self.caminho.name + ".tmp")
        self._destino = self.temporario if modo == "gravar" else self.caminho
        if modo == "gravar":
            self.caminho.parent.mkdir(parents=True, exist_ok=True)
            self.temporario.write_text("", encoding="utf-8")

    @property
    def existe(self) -> bool:
        return self.caminho.exists()

    def _ler(self) -> None:
        for numero, linha in enumerate(self.caminho.read_text(encoding="utf-8").splitlines(), 1):
            if not linha.strip():
                continue
            try:
                item = json.loads(linha)
            except json.JSONDecodeError as erro:
                raise ValueError(f"cassete {self.caminho.name}, linha {numero}: JSON inválido ({erro})") from erro
            if item.get("tipo") == "sistema":
                self._sistemas[item["hash"]] = item["texto"]
                self._escritos.add(item["hash"])
            elif item.get("tipo") == "pedido":
                self._pedidos[(item["chave"], int(item["n"]))] = item

    def confirmar(self) -> None:
        """Gravação completa: troca o cassete definitivo pelo que acabou de ser gravado."""
        if self.modo == "gravar" and self.temporario.exists():
            self.temporario.replace(self.caminho)

    def descartar(self) -> None:
        """Gravação incompleta (teto, erro): apaga o temporário e mantém o cassete anterior."""
        if self.modo == "gravar":
            self.temporario.unlink(missing_ok=True)

    def _escrever(self, *itens: dict[str, Any]) -> None:
        self._destino.parent.mkdir(parents=True, exist_ok=True)
        with self._destino.open("a", encoding="utf-8") as arquivo:
            for item in itens:
                arquivo.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")

    def _diferenca(self, papel: str, sistema: str, conteudo: str) -> str:
        """Diff contra o pedido gravado mais parecido do mesmo papel, para a mensagem de erro."""
        candidatos = [p for p in self._pedidos.values() if p.get("papel") == papel]
        if not candidatos:
            return f"(nenhum pedido do papel {papel} no cassete)"
        atual = (self._sistemas.get(_hash(normalizar(sistema)), normalizar(sistema)) + "\n----\n" + normalizar(conteudo)).splitlines()

        def texto(p: dict[str, Any]) -> list[str]:
            return (self._sistemas.get(p.get("sistema", ""), "") + "\n----\n" + p.get("conteudo", "")).splitlines()

        parecido = max(candidatos, key=lambda p: difflib.SequenceMatcher(None, texto(p), atual).ratio())
        linhas = list(difflib.unified_diff(texto(parecido), atual, "gravado", "agora", n=1, lineterm=""))
        return "\n".join(linhas[:60]) + ("\n(...)" if len(linhas) > 60 else "")

    async def gerar(self, *, papel: str, sistema: str, conteudo: str, esquema: dict[str, Any], modelo: str,
                    esforco: str = "medium", validar: Callable[[dict[str, Any]], None] | None = None,
                    temperatura: float | None = None) -> Resultado:
        if self.modo == "desligado":
            return await self._chamar(papel, sistema, conteudo, esquema, modelo, esforco, validar, temperatura)
        chave = chave_do_pedido(papel=papel, modelo=modelo, sistema=sistema, conteudo=conteudo, esquema=esquema,
                                temperatura=temperatura, esforco=esforco)
        n = self._contagem.get(chave, 0)
        self._contagem[chave] = n + 1
        gravado = self._pedidos.get((chave, n)) if self.modo != "gravar" else None
        if gravado is not None:
            self.tocados += 1
            return self._tocar(gravado, validar)
        if self.modo == "tocar":
            falta = (f"cassete {self.nome}: sem resposta para o pedido {papel} nº {n + 1} (chave {chave[:12]}). "
                     f"Regrave com `python -m app.avaliacao gravar {self.nome}`.\n{self._diferenca(papel, sistema, conteudo)}")
            self.faltas.append(falta)
            raise CasseteSemResposta(falta)
        return await self._gravar(chave, n, papel, sistema, conteudo, esquema, modelo, esforco, validar, temperatura)

    def _tocar(self, item: dict[str, Any], validar: Callable[[dict[str, Any]], None] | None) -> Resultado:
        chamadas = [Chamada(**c) for c in item.get("chamadas") or []]
        if item.get("erro"):
            erro = ErroModelo(item["erro"]["motivo"], item["erro"].get("detalhe", ""))
            erro.chamadas = chamadas  # type: ignore[attr-defined]
            raise erro
        dados = item["dados"]
        if validar:
            try:
                validar(dados)
            except Exception as erro:                       # mesmo comportamento do modelo de verdade
                falha = ErroModelo("saida_invalida", str(erro))
                falha.chamadas = chamadas  # type: ignore[attr-defined]
                raise falha from erro
        return Resultado(dados=json.loads(json.dumps(dados)), chamadas=chamadas)

    async def _chamar(self, papel: str, sistema: str, conteudo: str, esquema: dict[str, Any], modelo: str, esforco: str,
                      validar: Callable[[dict[str, Any]], None] | None, temperatura: float | None) -> Resultado:
        assert self.interno is not None
        extra = {"temperatura": temperatura} if temperatura is not None else {}
        return await self.interno.gerar(papel=papel, sistema=sistema, conteudo=conteudo, esquema=esquema, modelo=modelo,
                                        esforco=esforco, validar=validar, **extra)

    async def _gravar(self, chave: str, n: int, papel: str, sistema: str, conteudo: str, esquema: dict[str, Any],
                      modelo: str, esforco: str, validar: Callable[[dict[str, Any]], None] | None,
                      temperatura: float | None) -> Resultado:
        hash_sistema = _hash(normalizar(sistema))
        item: dict[str, Any] = {"tipo": "pedido", "chave": chave, "n": n, "papel": papel, "modelo": modelo,
                                "sistema": hash_sistema, "conteudo": normalizar(conteudo)}
        try:
            resultado = await self._chamar(papel, sistema, conteudo, esquema, modelo, esforco, validar, temperatura)
        except ErroModelo as erro:
            item.update(erro={"motivo": erro.motivo, "detalhe": erro.detalhe},
                        chamadas=[asdict(c) for c in getattr(erro, "chamadas", [])])
            self._guardar(hash_sistema, sistema, item)
            raise
        item.update(dados=resultado.dados, chamadas=[asdict(c) for c in resultado.chamadas])
        self._guardar(hash_sistema, sistema, item)
        return resultado

    def _guardar(self, hash_sistema: str, sistema: str, item: dict[str, Any]) -> None:
        novos = []
        if hash_sistema not in self._escritos:
            self._escritos.add(hash_sistema)
            self._sistemas[hash_sistema] = normalizar(sistema)
            novos.append({"tipo": "sistema", "hash": hash_sistema, "texto": normalizar(sistema)})
        self._pedidos[(item["chave"], item["n"])] = item
        self.gravados += 1
        self._escrever(*novos, item)


class VisaoGravada:
    """Fase 2: o mesmo cassete para descrever_imagem e transcrever_audio. Hoje a mídia entra com texto pronto."""

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise NotImplementedError("VisaoGravada fica para a fase 2 (docs/PLANO_TESTE_AGENTE.md, seção 8)")
