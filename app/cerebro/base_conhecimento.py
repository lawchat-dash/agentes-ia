"""A base de conhecimento dentro do turno: o bloco do conteúdo, o campo `base` da saída, o registro e o guarda de fonte.

O pipeline começa a busca (app/conhecimento_indice.buscar) antes do cérebro, como tarefa, e a põe em
entrada.conhecimento["_busca"]: ela roda enquanto o extrator pensa. O turno só espera o resultado na hora de montar
o prompt do agente. `entrada.conhecimento["base"]` ligado = regra "FATOS DO ESCRITÓRIO" no sistema e campo `base` na saída.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app import conhecimento as base

log = logging.getLogger("agentesia")

ESQUEMA_BASE: dict[str, Any] = {
    "type": "object",
    "properties": {
        "usados": {"type": "array", "items": {"type": "integer"}},
        "sem_resposta": {"type": "string"},
    },
    "required": ["usados", "sem_resposta"],
    "additionalProperties": False,
}


def ativa(conhecimento: dict[str, Any] | None) -> bool:
    return bool((conhecimento or {}).get("base"))


async def resolver(entrada: Any) -> Any | None:
    """Resultado da busca do turno (espera a tarefa do pipeline uma vez só). Falha da busca = sem base, sem derrubar o turno."""
    conhecimento = getattr(entrada, "conhecimento", None) or {}
    pendente = conhecimento.get("_busca")
    if pendente is None or hasattr(pendente, "trechos"):
        return pendente
    try:
        busca = await pendente if (asyncio.isfuture(pendente) or asyncio.iscoroutine(pendente)) else pendente
    except Exception:                                   # noqa: BLE001 - a busca nunca derruba o turno
        log.warning("busca na base de conhecimento falhou", exc_info=True)
        busca = None
    conhecimento["_busca"] = busca
    return busca


def bloco(busca: Any) -> str:
    if busca is None:
        return ""
    return base.montar_bloco(list(busca.trechos), consultou=bool(busca.consultou))


def com_base(esquema: dict[str, Any], conhecimento: dict[str, Any] | None) -> dict[str, Any]:
    """Esquema de saída com o campo `base` (só quando a base está ligada no turno)."""
    if not ativa(conhecimento):
        return esquema
    propriedades = {**esquema["properties"], "base": ESQUEMA_BASE}
    return {**esquema, "properties": propriedades, "required": list(propriedades)}


def _ler_base(dados: Any, quantos: int) -> tuple[list[int], str]:
    if not isinstance(dados, dict):
        return [], ""
    usados = []
    for n in dados.get("usados") or []:
        try:
            n = int(n)
        except (TypeError, ValueError):
            continue
        if 1 <= n <= quantos and n not in usados:
            usados.append(n)
    return usados, str(dados.get("sem_resposta") or "").strip()[:500]


def registrar(saida: Any, entrada: Any, dados_base: Any, papel: str | None) -> None:
    """Grava em saida.contexto["conhecimento"] o que entrou e o que a IA usou; pergunta sem resposta vira evento
    (o pipeline faz o upsert em agentesia_conhecimento_lacunas)."""
    if not ativa(getattr(entrada, "conhecimento", None)):
        return
    busca = (entrada.conhecimento or {}).get("_busca")
    trechos = list(getattr(busca, "trechos", []) or [])
    usados, sem_resposta = _ler_base(dados_base, len(trechos))
    if busca is not None and hasattr(busca, "para_contexto"):
        registro = busca.para_contexto(usados)
    else:
        registro = {"consultou": False, "modo": "sem_busca", "trechos": [], "usados": usados}
    registro["sem_resposta"] = sem_resposta
    saida.contexto["conhecimento"] = registro
    if sem_resposta:
        saida.eventos.append({"tipo": "pergunta_sem_resposta", "gravidade": "info", "responsavel": "cadastro",
                              "descricao": f"Pergunta sem resposta na base: {sem_resposta[:200]}",
                              "detalhe": {"pergunta": sem_resposta, "papel": papel,
                                          "consulta": registro.get("consulta", "")}})


def textos_da_base(entrada: Any) -> list[str]:
    busca = (getattr(entrada, "conhecimento", None) or {}).get("_busca")
    return [t.texto for t in getattr(busca, "trechos", []) or []]


def guarda_de_fonte(entrada: Any, textos: list[str], *fontes: str) -> str | None:
    """Valor (R$), porcentagem ou prazo da resposta que não está em nada do que o modelo recebeu (sistema, conteúdo,
    base, falas do lead) = fato do escritório inventado. Só com a base ligada. Devolve a orientação para a CORRIJA."""
    if not ativa(getattr(entrada, "conhecimento", None)):
        return None
    # As falas saem das fontes: o que a própria IA disse antes não vira fonte (um valor inventado num turno se
    # "validaria" nos seguintes) e o que o lead disse só vale como dado dele (ver base.fato_sem_fonte).
    historico = [m for m in getattr(entrada, "historico", []) or [] if isinstance(m, dict)]
    novas = [str(t) for t in getattr(entrada, "novas", []) or []]
    falas = [f"{m.get('autor')}: {m.get('texto')}" for m in historico] + [f"- {t}" for t in novas]
    limpas = []
    for fonte in fontes:
        fonte = str(fonte or "")
        for fala in sorted(falas, key=len, reverse=True):
            fonte = fonte.replace(fala, "")
        limpas.append(fonte)
    do_escritorio = limpas + textos_da_base(entrada) + [str(getattr(entrada, "honorarios", "") or "")]
    do_escritorio += [str(m.get("texto") or "") for m in historico if m.get("autor") == "atendente"]
    do_lead = novas + [str(m.get("texto") or "") for m in historico if m.get("autor") not in ("você", "ia", "atendente")]
    do_lead += [str(v) for v in (getattr(entrada, "fatos", None) or {}).values()]
    inventado = base.fato_sem_fonte(textos, do_escritorio, do_lead)
    if not inventado:
        return None
    return (f"Não invente valor, porcentagem ou prazo ('{inventado}'): isso não está no roteiro, nos DADOS DO ESCRITÓRIO, "
            "nos honorários, nos FATOS DO SISTEMA nem na BASE DE CONHECIMENTO. Diga que vai confirmar com a equipe e "
            "preencha base.sem_resposta com a pergunta do lead.")
