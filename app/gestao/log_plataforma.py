"""Log da plataforma (Superadmin › Logs): o que acontece de ADMINISTRATIVO, sem relação com a conversa dos leads.

Tabela agentesia_log_plataforma (db/migracoes/018). Duas formas de gravar:

  await registrar(pedido, ctx=ctx, funcao="conta.liberada", rotulo="Escritório liberado", referencia=..., payload=...)

  @api.post(...)
  @registrado("produto.arquivado", "Agente arquivado", referencia=lambda a: a["id_ativado"])
  async def rota(...): ...

O decorador mede a duração, pega quem fez (Contexto da rota), grava ok com o resultado ou erro com a mensagem (e deixa
a exceção seguir). Os argumentos da rota chegam às funções de payload/referência/resultado como um dict `a`.

Regras:
  - o log NUNCA derruba a ação principal: qualquer falha ao gravar (banco fora, tabela sem a 018, tempo esgotado) só
    vai para o log do servidor;
  - payload e resultado passam por limpar(): some token, senha, chave, segredo, CPF, telefone, base64 e afins; textos
    longos e listas grandes são cortados.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import json
import logging
import re
import time
from typing import Any, Callable

log = logging.getLogger("agentesia.log_plataforma")

ESPERA_S = 2.0                     # tempo máximo para gravar o log (a rota não fica presa no banco)
TEXTO_MAX = 500                    # caracteres por texto no payload/resultado
LISTA_MAX = 30                     # itens por lista
PROFUNDIDADE_MAX = 6
JSON_MAX = 20_000                  # tamanho máximo do JSON gravado (payload e resultado, cada um)
OCULTO = "***"

# Chaves que nunca vão para o log (comparadas sem acento, em minúsculas, por pedaço do nome).
_CHAVES_SECRETAS = re.compile(
    r"token|senha|password|passwd|secret|segredo|chave|api_?key|apikey|authorization|cookie|hash|credencia|"
    r"cpf|telefone|phone|celular|whatsapp|numero|^number|base64|pix|qr|url_pagamento|link_acesso|^url$",
    re.IGNORECASE)
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_CPF = re.compile(r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)")
_TELEFONE = re.compile(r"(?<![\w])\+?\(?\d{2,3}\)?[\s-]?9?\d{4}[\s-]?\d{4}(?!\d)")
_BEARER = re.compile(r"(bearer\s+)[\w.\-]+", re.IGNORECASE)


def _chave_secreta(chave: str) -> bool:
    return bool(_CHAVES_SECRETAS.search(str(chave)))


def _texto_limpo(texto: str) -> str:
    if _UUID.fullmatch(texto):                            # id: fica como está (os dígitos dele não são telefone)
        return texto
    texto = _BEARER.sub(r"\1" + OCULTO, texto)
    texto = _CPF.sub(OCULTO, texto)
    texto = _TELEFONE.sub(OCULTO, texto)
    if len(texto) > TEXTO_MAX:
        texto = texto[:TEXTO_MAX] + f"… (+{len(texto) - TEXTO_MAX})"
    return texto


def limpar(valor: Any, _nivel: int = 0) -> Any:
    """Cópia do valor pronta para o log: sem segredo nem dado pessoal sensível, cortada no tamanho."""
    if hasattr(valor, "model_dump"):                      # modelos pydantic das rotas
        valor = valor.model_dump()
    if _nivel > PROFUNDIDADE_MAX:
        return "…"
    if isinstance(valor, dict):
        return {str(k): (OCULTO if _chave_secreta(k) and v not in (None, "", [], {}) else limpar(v, _nivel + 1))
                for k, v in list(valor.items())[:80]}
    if isinstance(valor, (list, tuple, set)):
        itens = list(valor)
        saida = [limpar(v, _nivel + 1) for v in itens[:LISTA_MAX]]
        if len(itens) > LISTA_MAX:
            saida.append(f"… (+{len(itens) - LISTA_MAX} itens)")
        return saida
    if isinstance(valor, str):
        return _texto_limpo(valor)
    if valor is None or isinstance(valor, (bool, int, float)):
        return valor
    return _texto_limpo(str(valor))


def _json(valor: Any) -> str | None:
    if valor is None:
        return None
    texto = json.dumps(limpar(valor), ensure_ascii=False, default=str)
    if len(texto) > JSON_MAX:
        texto = json.dumps({"cortado": True, "inicio": texto[:JSON_MAX // 2]}, ensure_ascii=False)
    return texto


def _pool(origem: Any) -> Any:
    """Aceita o Request da rota (app.state.gestao.pool) ou o próprio pool."""
    app = getattr(origem, "app", None)
    if app is not None:
        gestao = getattr(getattr(app, "state", None), "gestao", None)
        return getattr(gestao, "pool", None)
    return origem if hasattr(origem, "execute") else None


_SEM_DADO = object()
_avisou_sem_tabela = False


async def registrar(origem: Any, *, funcao: str, rotulo: str, ctx: Any = None, id_escritorio: Any = _SEM_DADO,
                    id_usuario: str | None = None, papel: str | None = None, referencia: Any = None,
                    payload: Any = None, resultado: Any = None, status: str = "ok", erro: Any = None,
                    duracao_ms: float | None = None) -> bool:
    """Grava uma linha do log. Devolve True se gravou. Nunca levanta exceção."""
    global _avisou_sem_tabela
    try:
        pool = _pool(origem)
        if pool is None:
            return False
        if ctx is not None:
            id_usuario = id_usuario or getattr(ctx, "id_usuario", None)
            usuario = getattr(ctx, "usuario", None) or {}
            papel = papel or usuario.get("papel")
            if id_escritorio is _SEM_DADO:
                id_escritorio = getattr(ctx, "id_escritorio", None)
        if id_escritorio is _SEM_DADO or not (id_escritorio and _UUID.fullmatch(str(id_escritorio))):
            id_escritorio = None
        if id_usuario and not _UUID.fullmatch(str(id_usuario)):
            id_usuario = None
        texto_ref = None if referencia in (None, "") else _texto_limpo(str(referencia))[:200]
        texto_erro = None if erro in (None, "") else _texto_limpo(str(erro))[:2000]
        await asyncio.wait_for(pool.execute(
            """insert into agentesia_log_plataforma (id_escritorio, id_usuario, papel, funcao, rotulo, referencia,
                                                     payload, resultado, status, erro, duracao_ms)
               values ($1::uuid, $2::uuid, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9, $10, $11)""",
            str(id_escritorio) if id_escritorio else None, str(id_usuario) if id_usuario else None, papel,
            funcao[:80], rotulo[:160], texto_ref, _json(payload), _json(resultado),
            "erro" if status == "erro" else "ok", texto_erro,
            None if duracao_ms is None else max(0, int(round(duracao_ms)))), ESPERA_S)
        return True
    except Exception as falha:            # noqa: BLE001  o log nunca derruba a ação principal
        if "agentesia_log_plataforma" in str(falha) and "exist" in str(falha):
            if not _avisou_sem_tabela:
                _avisou_sem_tabela = True
                log.warning("log da plataforma desligado: falta a migração db/migracoes/018_agentesia_log_plataforma.sql")
        else:
            log.warning("não gravou o log da plataforma (%s): %s", funcao, falha)
        return False


def _mensagem_de(erro: BaseException) -> str:
    detalhe = getattr(erro, "detail", None)
    codigo = getattr(erro, "status_code", None)
    texto = detalhe if isinstance(detalhe, str) else (json.dumps(detalhe, ensure_ascii=False, default=str) if detalhe else str(erro))
    return f"{codigo}: {texto}" if codigo else (texto or erro.__class__.__name__)


def _valor(fonte: Any, *args: Any) -> Any:
    if callable(fonte):
        try:
            return fonte(*args)
        except Exception as falha:        # noqa: BLE001  extrator do log com defeito não derruba a rota
            log.warning("log da plataforma: extrator falhou: %s", falha)
            return None
    return fonte


def registrado(funcao: str | Callable[[dict[str, Any]], str | None], rotulo: str | Callable[[dict[str, Any]], str], *,
               referencia: Any = None, payload: Any = None, resultado: Any = None, escritorio: Any = _SEM_DADO,
               falha: Any = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorador de rota: grava a ação no log com a duração. `funcao` callable que devolve None = não grava.

    referencia(a), payload(a) e escritorio(a) recebem os argumentos da rota; resultado(a, r) recebe também o retorno.
    falha(a, r): a rota respondeu, mas a ação não aconteceu (ex.: "não habilitado"). Texto = grava como erro.
    """

    def decorar(rota: Callable[..., Any]) -> Callable[..., Any]:
        assinatura = inspect.signature(rota)

        @functools.wraps(rota)
        async def com_log(*args: Any, **kwargs: Any) -> Any:
            try:
                ligados = assinatura.bind_partial(*args, **kwargs)
                ligados.apply_defaults()
                a = dict(ligados.arguments)
            except TypeError:
                a = dict(kwargs)
            inicio = time.perf_counter()
            try:
                retorno = await rota(*args, **kwargs)
            except Exception as erro:
                await _gravar(a, None, erro, inicio)
                raise
            await _gravar(a, retorno, None, inicio)
            return retorno

        async def _gravar(a: dict[str, Any], retorno: Any, erro: BaseException | None, inicio: float) -> None:
            try:
                codigo = _valor(funcao, a)
                if not codigo:
                    return
                ctx = next((v for v in a.values() if hasattr(v, "id_usuario") and hasattr(v, "usuario")), None)
                pedido = next((v for v in a.values() if hasattr(v, "app") and hasattr(v, "headers")), None)
                if pedido is None:
                    return
                extra: dict[str, Any] = {}
                if escritorio is not _SEM_DADO:
                    # escritorio(a) ou escritorio(a, retorno): a conta criada pela própria rota só existe no retorno
                    duplo = callable(escritorio) and len(inspect.signature(escritorio).parameters) >= 2
                    extra["id_escritorio"] = _valor(escritorio, a, retorno) if duplo else _valor(escritorio, a)
                elif isinstance(a.get("id_escritorio"), str):          # rotas /admin/escritorios/{id_escritorio}/...
                    extra["id_escritorio"] = a["id_escritorio"]
                ref = _valor(referencia, a)
                nome = retorno.get("nome") if isinstance(retorno, dict) else None
                if isinstance(ref, str) and _UUID.fullmatch(ref) and isinstance(nome, str) and nome.strip():
                    ref = f"{nome.strip()} · {ref[:8]}"          # o nome lê melhor na lista; o id fica no começo
                motivo = _mensagem_de(erro) if erro is not None else (_valor(falha, a, retorno) if falha else None)
                await registrar(
                    pedido, ctx=ctx, funcao=codigo, rotulo=str(_valor(rotulo, a) or codigo),
                    referencia=ref, payload=_valor(payload, a),
                    resultado=None if erro is not None else _valor(resultado, a, retorno),
                    status="erro" if motivo else "ok", erro=motivo or None,
                    duracao_ms=(time.perf_counter() - inicio) * 1000, **extra)
            except Exception as problema:  # noqa: BLE001
                log.warning("log da plataforma: %s", problema)

        return com_log

    return decorar
