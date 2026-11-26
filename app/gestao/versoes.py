"""Versões dos prompts de um produto ativado (rascunho -> publicar -> voltar; migração 008).

Cada ativação ou "Salvar" do editor (sincronizar) grava uma versão com o CONTEÚDO dos agentes: nome, boas-vindas,
prompt e frase de troca de cada papel, FAQ, objeções, regras gerais e dados do escritório. A versão é o que foi ao
ar; "Restaurar" só devolve o conteúdo para o rascunho do editor (quem publica é o "Salvar").

Sem a 008 nada quebra: gravar não faz nada e a lista volta vazia (com `disponivel: false`).
Nada aqui importa app.gestao.produtos (produtos chama gravar() de dentro da ativação).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import asyncpg

log = logging.getLogger("agentesia.versoes")

ORDEM_PAPEIS = ("sdr", "periododegraca", "closer", "contratos", "assinatura", "desqualificado")
NOMES_PAPEL = {"sdr": "SDR", "periododegraca": "Período de Graça", "closer": "Closer", "contratos": "Contratos",
               "assinatura": "Assinatura", "desqualificado": "Desqualificado"}
CAMPOS_AGENTE = (("prompt", "Prompt"), ("mensagem_troca", "Frase de troca"), ("boas_vindas", "Boas-vindas"),
                 ("nome", "Nome"))

_TEM_008: dict[str, tuple[float, bool]] = {}


async def tem_versoes(conexao: Any) -> bool:
    """A migração 008 foi aplicada? (guardado por 5 minutos, como a 007 em app/cobranca)."""
    item = _TEM_008.get("v")
    if item and item[0] > time.monotonic():
        return item[1]
    try:
        tem = bool(await conexao.fetchval("select to_regclass('public.agentesia_produto_versoes') is not null"))
    except Exception:
        log.exception("falha ao conferir a migração 008")
        tem = False
    _TEM_008["v"] = (time.monotonic() + 300, tem)
    return tem


def esquecer_cache() -> None:
    _TEM_008.clear()


# ============================================================================ conteúdo
def _texto(valor: Any) -> str:
    return str(valor or "").strip()


def _faq(itens: Any) -> list[dict[str, str]]:
    return [{"pergunta": _texto(f.get("pergunta") or f.get("q")), "resposta": _texto(f.get("resposta") or f.get("a"))}
            for f in (itens or []) if isinstance(f, dict)]


def _objecoes(itens: Any) -> list[dict[str, str]]:
    return [{"titulo": _texto(o.get("titulo") or o.get("gatilho") or o.get("objecao")), "resposta": _texto(o.get("resposta"))}
            for o in (itens or []) if isinstance(o, dict)]


def conteudo(*, agentes: list[dict[str, Any]], faq: Any, objecoes: Any, regras_markdown: Any,
             dados_escritorio: Any) -> dict[str, Any]:
    """O que fica guardado na versão (sempre no mesmo formato, para comparar e restaurar)."""
    por_papel = {a.get("papel"): a for a in agentes if a.get("papel")}
    papeis = [p for p in ORDEM_PAPEIS if p in por_papel] + [p for p in por_papel if p not in ORDEM_PAPEIS]
    return {
        "agentes": [{"papel": p, "nome": _texto(por_papel[p].get("nome")) or NOMES_PAPEL.get(p, p),
                     "boas_vindas": _texto(por_papel[p].get("boas_vindas")), "prompt": _texto(por_papel[p].get("prompt")),
                     "mensagem_troca": _texto(por_papel[p].get("mensagem_troca"))} for p in papeis],
        "faq": _faq(faq),
        "objecoes": _objecoes(objecoes),
        "regras_markdown": _texto(regras_markdown),
        "dados_escritorio": _texto(dados_escritorio),
    }


def _lista_em_texto(itens: list[dict[str, str]], a: str, b: str) -> str:
    return "\n\n".join(f"{i + 1}. {item.get(a, '')}\n   {item.get(b, '')}" for i, item in enumerate(itens))


def diferencas(antes: dict[str, Any] | None, depois: dict[str, Any]) -> list[dict[str, Any]]:
    """O que mudou de `antes` para `depois`, campo a campo, com o texto inteiro dos dois lados (para o lado a lado).
    antes=None: a primeira versão (tudo aparece como novo)."""
    antes = antes or {"agentes": [], "faq": [], "objecoes": [], "regras_markdown": "", "dados_escritorio": ""}
    itens: list[dict[str, Any]] = []
    ag_antes = {a["papel"]: a for a in antes.get("agentes") or []}
    ag_depois = {a["papel"]: a for a in depois.get("agentes") or []}
    papeis = [p for p in ORDEM_PAPEIS if p in ag_antes or p in ag_depois] + \
             [p for p in {**ag_antes, **ag_depois} if p not in ORDEM_PAPEIS]
    for papel in papeis:
        a, d = ag_antes.get(papel), ag_depois.get(papel)
        nome = (d or a or {}).get("nome") or NOMES_PAPEL.get(papel, papel)
        if a is None or d is None:
            itens.append({"chave": f"agente.{papel}", "rotulo": f"Agente {nome}", "tipo": "agente",
                          "mudanca": "entrou" if a is None else "saiu",
                          "antes": (a or {}).get("prompt", ""), "depois": (d or {}).get("prompt", "")})
            continue
        for campo, rotulo in CAMPOS_AGENTE:
            if _texto(a.get(campo)) != _texto(d.get(campo)):
                itens.append({"chave": f"agente.{papel}.{campo}", "rotulo": f"{rotulo} do {nome}", "tipo": "texto",
                              "papel": papel, "antes": _texto(a.get(campo)), "depois": _texto(d.get(campo))})
    for chave, rotulo, x, y in (("faq", "FAQ", "pergunta", "resposta"), ("objecoes", "Objeções", "titulo", "resposta")):
        la, ld = antes.get(chave) or [], depois.get(chave) or []
        if la != ld:
            delta = len(ld) - len(la)
            itens.append({"chave": chave, "rotulo": rotulo + (f" ({'+' if delta > 0 else ''}{delta})" if delta else ""),
                          "tipo": "lista", "antes": _lista_em_texto(la, x, y), "depois": _lista_em_texto(ld, x, y),
                          "quantos_antes": len(la), "quantos_depois": len(ld)})
    for chave, rotulo in (("regras_markdown", "Regras gerais"), ("dados_escritorio", "Dados do escritório")):
        if _texto(antes.get(chave)) != _texto(depois.get(chave)):
            itens.append({"chave": chave, "rotulo": rotulo, "tipo": "texto",
                          "antes": _texto(antes.get(chave)), "depois": _texto(depois.get(chave))})
    return itens


def resumo(itens: list[dict[str, Any]]) -> list[str]:
    """Linhas curtas para a lista: "Prompt do Closer", "FAQ (+2)", "Agente Período de Graça entrou"."""
    saida: list[str] = []
    for item in itens:
        linha = item["rotulo"] + (f" {item['mudanca']}" if item.get("mudanca") else "")
        if linha not in saida:
            saida.append(linha)
    return saida


def _limpar_resumo(valor: Any) -> list[str]:
    if isinstance(valor, str):
        valor = [valor]
    linhas = [str(v).strip()[:200] for v in (valor or []) if str(v or "").strip()]
    return linhas[:40]


def _json(valor: Any) -> Any:
    return json.loads(valor) if isinstance(valor, str) else valor


# ============================================================================ banco
async def ultima(conexao: Any, id_ativado: str) -> dict[str, Any] | None:
    linha = await conexao.fetchrow(
        """select numero, conteudo from agentesia_produto_versoes where id_produto_ativado = $1::uuid
           order by numero desc limit 1""", id_ativado)
    return {"numero": linha["numero"], "conteudo": _json(linha["conteudo"])} if linha else None


async def gravar(pool: asyncpg.Pool, *, id_escritorio: str, id_ativado: str, id_usuario: str | None, autor: str | None,
                 origem: str, novo: dict[str, Any], resumo_cliente: Any = None) -> dict[str, Any] | None:
    """Grava a versão nova. Devolve {numero, resumo} ou None (sem a 008, ou nada mudou desde a última versão).
    O resumo vem do assistente (que já calcula o antes e depois); sem ele, é calculado aqui pela diferença."""
    if not await tem_versoes(pool):
        return None
    for _tentativa in range(3):
        async with pool.acquire() as conexao, conexao.transaction():
            anterior = await ultima(conexao, id_ativado)
            if anterior and anterior["conteudo"] == novo:
                return None                                   # só mexeu no comportamento ou no número
            itens = diferencas(anterior["conteudo"] if anterior else None, novo)
            if anterior:
                padrao = resumo(itens)
            else:                                             # produto ativado antes da 008: a 1ª é a do 1º salvar
                padrao = ["Versão inicial (ativação)" if origem == "ativou" else "Primeira versão guardada"]
            linhas = _limpar_resumo(resumo_cliente) or padrao
            numero = (anterior["numero"] if anterior else 0) + 1
            try:
                await conexao.execute(
                    """insert into agentesia_produto_versoes (id_escritorio, id_produto_ativado, numero, origem, id_usuario,
                                                             autor, resumo, conteudo)
                       values ($1::uuid, $2::uuid, $3, $4, $5::uuid, $6, $7::jsonb, $8::jsonb)""",
                    id_escritorio, id_ativado, numero, origem if origem in ("ativou", "sincronizou") else "sincronizou",
                    id_usuario, (autor or "").strip()[:120] or None, json.dumps(linhas, ensure_ascii=False),
                    json.dumps(novo, ensure_ascii=False))
            except asyncpg.UniqueViolationError:              # outro salvar ao mesmo tempo: tenta com o número seguinte
                continue
            return {"numero": numero, "resumo": linhas}
    return None


async def listar(pool: asyncpg.Pool, id_escritorio: str, id_ativado: str) -> list[dict[str, Any]]:
    linhas = await pool.fetch(
        """select v.numero, v.origem, v.autor, v.resumo, v.criado_em, coalesce(u.nome, v.autor) as autor_nome,
                  jsonb_array_length(coalesce(v.conteudo->'agentes', '[]'::jsonb)) as agentes,
                  jsonb_array_length(coalesce(v.conteudo->'faq', '[]'::jsonb)) as faq,
                  jsonb_array_length(coalesce(v.conteudo->'objecoes', '[]'::jsonb)) as objecoes
           from agentesia_produto_versoes v left join agentesia_usuarios u on u.id = v.id_usuario
           where v.id_produto_ativado = $1::uuid and v.id_escritorio = $2::uuid order by v.numero desc""",
        id_ativado, id_escritorio)
    return [{"numero": r["numero"], "origem": r["origem"], "autor": r["autor_nome"] or "—",
             "resumo": _json(r["resumo"]) or [], "criado_em": r["criado_em"].isoformat(),
             "agentes": r["agentes"], "faq": r["faq"], "objecoes": r["objecoes"]} for r in linhas]


async def uma(pool: asyncpg.Pool, id_escritorio: str, id_ativado: str, numero: int) -> dict[str, Any] | None:
    linha = await pool.fetchrow(
        """select v.numero, v.origem, v.resumo, v.conteudo, v.criado_em, coalesce(u.nome, v.autor) as autor
           from agentesia_produto_versoes v left join agentesia_usuarios u on u.id = v.id_usuario
           where v.id_produto_ativado = $1::uuid and v.id_escritorio = $2::uuid and v.numero = $3""",
        id_ativado, id_escritorio, numero)
    if not linha:
        return None
    return {"numero": linha["numero"], "origem": linha["origem"], "autor": linha["autor"] or "—",
            "resumo": _json(linha["resumo"]) or [], "criado_em": linha["criado_em"].isoformat(),
            "conteudo": _json(linha["conteudo"])}
