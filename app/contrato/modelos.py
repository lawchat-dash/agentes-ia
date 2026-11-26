"""Lista de modelos de contrato da ZapSign de um escritório (agentesia_integracoes.config.modelos).

Cada item: id_modelo, nome, padrao, id_agente, id_ativado, mapeamento, obrigatorios.
- Item "do produto": tem id_ativado (agentesia_produtos_ativados.id) e/ou id_agente. Vale só para os
  leads daquele agente. Gravado pela tela de contrato do produto, que mexe SÓ no item dele.
- Item "geral": sem id_ativado nem id_agente. É o da tela Integrações > ZapSign.
- padrao: o que vale para o agente que não tem modelo próprio. O primeiro modelo da conta vira padrão.

O motor (Executor._modelo_do_contrato) acha o modelo pelo id_agente do lead. Produto salvo antes de
ser ativado fica só com id_ativado; a ativação copia o id_agente para o item (vincular_agente).

Funções puras: recebem a lista atual e devolvem a nova, sem tocar no banco.
"""

from __future__ import annotations

from typing import Any

from app.contrato import dados as cdados

CAMPOS_VALIDOS = set(cdados.CAMPOS) | {"@data_geracao", "@fixo"}


class ModeloInvalido(ValueError):
    """Item com variável ligada a um campo que o sistema não conhece."""


def normalizar(m: dict[str, Any]) -> dict[str, Any] | None:
    """Item limpo, ou None quando não tem id_modelo."""
    id_modelo = str(m.get("id_modelo") or "").strip()
    if not id_modelo:
        return None
    mapeamento = [{"variavel": str(x.get("variavel") or "").strip(), "campo": str(x.get("campo") or ""),
                   **({"valor": str(x.get("valor") or "")} if x.get("campo") == "@fixo" else {})}
                  for x in m.get("mapeamento") or cdados.MAPEAMENTO_PADRAO if str(x.get("variavel") or "").strip()]
    if any(x["campo"] not in CAMPOS_VALIDOS for x in mapeamento):
        raise ModeloInvalido("Há variável ligada a um campo desconhecido.")
    return {"id_modelo": id_modelo, "nome": str(m.get("nome") or id_modelo)[:120], "padrao": bool(m.get("padrao")),
            "id_agente": str(m["id_agente"]) if m.get("id_agente") else None,
            "id_ativado": str(m["id_ativado"]) if m.get("id_ativado") else None,
            "mapeamento": mapeamento,
            "obrigatorios": [c for c in m.get("obrigatorios") or cdados.OBRIGATORIOS_PADRAO if c in cdados.CAMPOS]}


def validos(modelos: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [m for m in modelos or [] if isinstance(m, dict) and m.get("id_modelo")]


def do_produto(m: dict[str, Any]) -> bool:
    return bool(m.get("id_ativado") or m.get("id_agente"))


def mesmo_produto(m: dict[str, Any], id_ativado: str | None, id_agente: str | None) -> bool:
    return bool((id_ativado and m.get("id_ativado") == id_ativado) or (id_agente and m.get("id_agente") == id_agente))


def modelo_do_produto(modelos: list[dict[str, Any]] | None, id_ativado: str | None,
                      id_agente: str | None) -> dict[str, Any] | None:
    """O item próprio do produto (sem cair no padrão)."""
    return next((m for m in validos(modelos) if mesmo_produto(m, id_ativado, id_agente)), None)


def padrao(modelos: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    lista = validos(modelos)
    return next((m for m in lista if m.get("padrao")), None) or (lista[0] if len(lista) == 1 else None)


def _garantir_um_padrao(lista: list[dict[str, Any]], preferido: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """No máximo um padrão; nenhum -> o primeiro geral (ou o primeiro de todos) vira padrão."""
    marcados = [m for m in lista if m.get("padrao")]
    if len(marcados) > 1:
        fica = preferido if any(m is preferido for m in marcados) else marcados[0]
        for m in marcados:
            if m is not fica:
                m["padrao"] = False
    elif not marcados and lista:
        (next((m for m in lista if not do_produto(m)), None) or lista[0])["padrao"] = True
    return lista


def salvar_do_produto(modelos: list[dict[str, Any]] | None, novo: dict[str, Any], id_ativado: str,
                      id_agente: str | None) -> list[dict[str, Any]]:
    """Troca SÓ o item deste produto (achado por id_ativado ou id_agente); os outros ficam como estão.

    O padrão de outro produto não é tirado: este item só é padrão se já era, ou se ninguém é.
    Itens repetidos do mesmo produto (versões antigas) viram um só.
    """
    atuais = validos(modelos)
    deste = [mesmo_produto(m, id_ativado, id_agente) for m in atuais]
    outros_tem_padrao = any(m.get("padrao") for m, d in zip(atuais, deste) if not d)
    item = {**novo, "id_ativado": id_ativado,
            "id_agente": id_agente or next((m["id_agente"] for m, d in zip(atuais, deste) if d and m.get("id_agente")), None),
            "padrao": any(m.get("padrao") for m, d in zip(atuais, deste) if d) or not outros_tem_padrao}
    lista: list[dict[str, Any]] = []
    colocado = False
    for m, d in zip(atuais, deste):
        if not d:
            lista.append(dict(m))
        elif not colocado:
            lista.append(item)                # no lugar do antigo
            colocado = True
    if not colocado:
        lista.append(item)
    return lista


def juntar_da_tela(modelos: list[dict[str, Any]] | None, enviados: list[dict[str, Any]],
                   lista_completa: bool) -> list[dict[str, Any]]:
    """PUT /integracoes/zapsign/config.

    lista_completa=True: a tela mandou a lista inteira; ela substitui a atual.
    lista_completa=False (padrão, a tela Integrações): os itens gerais enviados substituem os gerais
    atuais; um item de produto enviado troca só o item daquele produto; os itens dos outros produtos
    ficam. Um item enviado marcado padrão tira o padrão dos demais (é a tela do padrão do escritório).
    """
    if lista_completa:
        lista = [dict(m) for m in enviados]
        return _garantir_um_padrao(lista, next((m for m in lista if m.get("padrao")), None))
    lista = []
    usados: list[int] = []
    for m in validos(modelos):
        if not do_produto(m):
            continue                                  # os gerais vêm da tela
        i = next((i for i, e in enumerate(enviados)
                  if i not in usados and do_produto(e) and mesmo_produto(m, e.get("id_ativado"), e.get("id_agente"))), None)
        if i is None:
            lista.append(dict(m))
        else:
            usados.append(i)
            lista.append(dict(enviados[i]))
    gerais = [dict(e) for i, e in enumerate(enviados) if i not in usados]
    lista = gerais + lista                            # os gerais primeiro: o padrão do escritório na frente
    preferido = next((m for m in gerais if m.get("padrao")), None)
    if preferido:
        for m in lista:
            if m is not preferido:
                m["padrao"] = False
    return _garantir_um_padrao(lista, preferido)


def vincular_agente(modelos: list[dict[str, Any]] | None, id_ativado: str, id_agente: str) -> list[dict[str, Any]] | None:
    """Ativação/sincronização: o item salvo pelo produto ganha o id_agente (o motor acha por ele).

    Devolve None quando não há nada a mudar. Um item antigo só com o mesmo id_agente (sem id_ativado)
    é absorvido, para o agente não ter dois modelos.
    """
    atuais = validos(modelos)
    item = next((m for m in atuais if m.get("id_ativado") == id_ativado), None)
    if item is None:
        return None
    sobras = [m for m in atuais if m is not item and m.get("id_agente") == id_agente and not m.get("id_ativado")]
    if item.get("id_agente") == id_agente and not sobras:
        return None
    novo = {**item, "id_agente": id_agente, "padrao": bool(item.get("padrao") or any(m.get("padrao") for m in sobras))}
    return [novo if m is item else dict(m) for m in atuais if not any(m is s for s in sobras)]


def remover_do_produto(modelos: list[dict[str, Any]] | None, id_ativado: str,
                       id_agente: str | None) -> list[dict[str, Any]] | None:
    """Exclusão do produto: o item dele sai da lista (os dos outros produtos ficam).

    Se o item era o padrão do escritório, ele fica como modelo geral (sem id_ativado/id_agente): os
    agentes sem modelo próprio continuam com o mesmo contrato e a tela Integrações passa a mostrá-lo.
    Devolve None quando não há nada a mudar.
    """
    atuais = validos(modelos)
    deste = [mesmo_produto(m, id_ativado, id_agente) for m in atuais]
    if not any(deste):
        return None
    padrao_deste = next((m for m, d in zip(atuais, deste) if d and m.get("padrao")), None)
    lista: list[dict[str, Any]] = []
    for m, d in zip(atuais, deste):
        if not d:
            lista.append(dict(m))
        elif m is padrao_deste:
            lista.append({**m, "id_ativado": None, "id_agente": None})
    return lista
