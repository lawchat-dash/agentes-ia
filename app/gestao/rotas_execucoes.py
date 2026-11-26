"""Execuções (Superadmin): cada turno da IA, como as execuções do n8n. Só a equipe LawChat (ADMIN).

  GET /api/admin/execucoes/filtros      contas e agentes para os filtros
  GET /api/admin/execucoes              lista (mais novas primeiro, paginada) com filtros:
        conta, agente, busca (nome ou número), situacao (respondido|sem_resposta|erro|processando),
        troca=1 (só com troca de etapa), erro=1 (só com erro), de/ate (data-hora ISO), pagina, por_pagina
  GET /api/admin/execucoes/{id}         detalhe: mensagens do lead que entraram, o prompt que rodou, a decisão da IA,
                                        as mensagens que saíram, eventos e travas do turno, tempos, chamadas e custo,
                                        e a execução anterior/seguinte do mesmo lead

Dados: agentesia_turnos (+ leads, contatos, agentes, escritórios), agentesia_mensagens e agentesia_eventos por id_turno
(lidos pelo índice do lead), agentesia_chamadas_ia por id_turno (custo e tokens). Só leitura.
Privacidade: telefone mascarado na lista e no detalhe; CPF/RG mascarados nos fatos, na ficha e no texto do prompt;
nenhum campo com cara de token/senha sai (vira "[oculto]").
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.gestao import rastro
from app.gestao.rotas import ADMIN, Contexto, _repo

api = APIRouter(prefix="/api/admin/execucoes")

UUID = re.compile(r"[0-9a-fA-F-]{36}")
SITUACOES = {"respondido": ["respondido"], "sem_resposta": ["silencio", "descartado"], "erro": ["erro"],
             "processando": ["processando"]}
ROTULO_SITUACAO = {"respondido": "Respondido", "silencio": "Sem resposta", "descartado": "Sem resposta",
                   "erro": "Erro", "processando": "Processando"}

# Eventos que mostram uma correção ou trava do motor atuando no turno (vão para "Correções e travas").
TITULOS_EXTRA = {
    "fato_pela_pergunta": "Fato tirado da pergunta da IA",
    "pergunta_ja_respondida": "Pergunta já respondida: a IA não repetiu",
    "segunda_tentativa_falhou": "Correção da IA falhou: seguiu com a 1ª resposta",
    "contrato_correcao_repetida": "Contrato: correção repetida, equipe assume",
}
TRAVAS = {"troca_barrada_faltam_fatos", "fato_pela_pergunta", "pergunta_ja_respondida", "portao_de_fatos",
          "destino_recusado", "troca_precoce_recusada", "transferencia_adiada_pergunta_aberta", "trocas_demais",
          "destino_ignorado", "destino_para_tras_ignorado", "sinal_recusado", "formato_invalido", "ia_fora_do_formato",
          "fora_do_tema", "tentativa_de_manipular", "trava_persistente", "segunda_tentativa_falhou",
          "contrato_correcao_repetida", "troca_pela_frase"}

# ------------------------------------------------------------------ privacidade
# "tokens_entrada"/"tokens_saida" (contagem) não são segredo; "token", "token_helena", "access_token" são.
_CHAVE_SEGREDO = re.compile(r"^(token|token_\w+|\w+_token|\w*senha\w*|\w*segredo\w*|api_?key|\w+_api_?key|chave_api"
                            r"|authorization|cookie|password|secret)$", re.I)
_CHAVE_DOCUMENTO = re.compile(r"cpf|(^|_)rg($|_)|identidade|documento_numero|numero_documento", re.I)
_CPF = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
_DOC_ROTULADO = re.compile(r"(?i)\b(cpf|rg|identidade)(\W{1,15})([0-9][0-9.\-/ xX]{4,18}[0-9xX])")


def _mascara_doc(valor: Any) -> str:
    texto = str(valor if valor is not None else "")
    digitos = re.sub(r"\D", "", texto)
    if not digitos:
        return texto
    return "***" + digitos[-2:] if len(digitos) > 2 else "***"


def mascarar_texto(texto: str) -> str:
    texto = _CPF.sub(lambda m: "***.***.***-" + m.group(0)[-2:], texto)
    return _DOC_ROTULADO.sub(lambda m: m.group(1) + m.group(2) + _mascara_doc(m.group(3)), texto)


def limpar(valor: Any) -> Any:
    """Cópia sem segredos e com CPF/RG mascarados (chaves de documento, fatos {chave: cpf, valor} e texto livre)."""
    if isinstance(valor, dict):
        doc = isinstance(valor.get("chave"), str) and bool(_CHAVE_DOCUMENTO.search(valor["chave"]))
        saida: dict[str, Any] = {}
        for k, v in valor.items():
            if isinstance(k, str) and _CHAVE_SEGREDO.search(k):
                saida[k] = "[oculto]"
            elif isinstance(k, str) and _CHAVE_DOCUMENTO.search(k) and not isinstance(v, (dict, list)):
                saida[k] = _mascara_doc(v)
            elif doc and k in ("valor", "trecho") and not isinstance(v, (dict, list)):
                saida[k] = _mascara_doc(v)
            else:
                saida[k] = limpar(v)
        return saida
    if isinstance(valor, list):
        return [limpar(v) for v in valor]
    if isinstance(valor, str):
        return mascarar_texto(valor)
    return valor


def mascarar_telefone(numero: str | None) -> str | None:
    d = re.sub(r"\D", "", numero or "")
    if not d:
        return None
    if len(d) >= 12 and d.startswith("55"):
        d = d[2:]
    if len(d) >= 10:
        return f"({d[:2]}) *****-{d[-4:]}"
    return "***" + d[-4:]


def _obj(valor: Any) -> Any:
    if isinstance(valor, str):
        try:
            return json.loads(valor)
        except json.JSONDecodeError:
            return valor
    return valor


def _data(texto: str | None, nome: str) -> datetime | None:
    if not texto:
        return None
    try:
        return datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, f"Data inválida em {nome}.") from None


def _uuid(texto: str | None, nome: str) -> str | None:
    if not texto:
        return None
    if not UUID.fullmatch(texto):
        raise HTTPException(400, f"{nome} inválido.")
    return texto


def _situacao(situacao: str, motivo: str | None) -> dict[str, Any]:
    grupo = next((g for g, lista in SITUACOES.items() if situacao in lista), situacao)
    return {"situacao": situacao, "grupo": grupo, "rotulo": ROTULO_SITUACAO.get(situacao, situacao), "motivo": motivo}


def _titulo(tipo: str) -> str:
    return TITULOS_EXTRA.get(tipo) or rastro.titulo_do_evento(tipo)


async def _nomes_por_agente(pool: Any, ids: set[str]) -> dict[str, dict[str, str]]:
    if not ids:
        return {}
    linhas = await pool.fetch("select id::text as id, config from agentesia_agentes where id = any($1::uuid[])", list(ids))
    return {r["id"]: rastro.nomes_das_etapas(rastro._obj(r["config"])) for r in linhas}


# ------------------------------------------------------------------ rotas
@api.get("/filtros")
async def filtros(pedido: Request, _: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    pool = _repo(pedido).pool
    contas = await pool.fetch("select id::text as id, nome from agentesia_escritorios order by nome")
    agentes = await pool.fetch(
        "select id::text as id, nome, id_escritorio::text as id_escritorio from agentesia_agentes order by nome")
    return {"contas": [dict(r) for r in contas], "agentes": [dict(r) for r in agentes],
            "situacoes": [{"valor": "respondido", "rotulo": "Respondido"}, {"valor": "sem_resposta", "rotulo": "Sem resposta"},
                          {"valor": "erro", "rotulo": "Erro"}, {"valor": "processando", "rotulo": "Processando"}]}


_SELECT_LISTA = """
select t.id::text as id, t.id_escritorio::text as id_escritorio, e.nome as conta, t.id_lead::text as id_lead,
       l.id_agente::text as id_agente, a.nome as agente, ct.nome as lead_nome, ct.telefone_normalizado as telefone,
       t.modo, t.etapa_antes, t.etapa_depois, t.situacao, t.motivo, t.iniciado_em, t.concluido_em,
       t.contexto -> 'catalogo' ->> 'transferir_para' as transferir_para,
       t.contexto -> 'catalogo' ->> 'ferramenta' as ferramenta,
       t.contexto -> 'catalogo' ->> 'ferramenta_barrada' as ferramenta_barrada,
       c.custo_brl, c.custo_usd, c.tokens_entrada, c.tokens_saida, c.chamadas
  from agentesia_turnos t
  join agentesia_leads l on l.id = t.id_lead
  join agentesia_contatos ct on ct.id = l.id_contato
  join agentesia_escritorios e on e.id = t.id_escritorio
  left join agentesia_agentes a on a.id = l.id_agente
  left join lateral (
       select coalesce(sum(ci.custo_brl), 0) as custo_brl, coalesce(sum(ci.custo_usd), 0) as custo_usd,
              coalesce(sum(ci.tokens_entrada), 0) as tokens_entrada, coalesce(sum(ci.tokens_saida), 0) as tokens_saida,
              count(*) as chamadas
         from agentesia_chamadas_ia ci where ci.id_turno = t.id) c on true
"""


def _item(r: Any, nomes: dict[str, dict[str, str]]) -> dict[str, Any]:
    nomes_agente = nomes.get(r["id_agente"] or "", rastro.NOMES_ETAPAS)
    duracao = (int((r["concluido_em"] - r["iniciado_em"]).total_seconds() * 1000)
               if r["concluido_em"] and r["iniciado_em"] else None)
    trocou = bool(r["etapa_depois"]) and r["etapa_depois"] != r["etapa_antes"]
    ferramenta = r["ferramenta"] or None
    return {
        "id": r["id"], "iniciado_em": r["iniciado_em"].isoformat(),
        "concluido_em": r["concluido_em"].isoformat() if r["concluido_em"] else None, "duracao_ms": duracao,
        "id_escritorio": r["id_escritorio"], "conta": r["conta"], "id_agente": r["id_agente"], "agente": r["agente"],
        "id_lead": r["id_lead"], "lead": {"nome": r["lead_nome"], "telefone": mascarar_telefone(r["telefone"])},
        "modo": r["modo"],
        "etapa_antes": r["etapa_antes"], "etapa_depois": r["etapa_depois"], "trocou_etapa": trocou,
        "nome_antes": nomes_agente.get(r["etapa_antes"] or "", r["etapa_antes"]),
        "nome_depois": nomes_agente.get(r["etapa_depois"] or "", r["etapa_depois"]),
        **_situacao(r["situacao"], r["motivo"]),
        "tool": {"transferir_para": r["transferir_para"] or None, "ferramenta": ferramenta,
                 "ferramenta_barrada": r["ferramenta_barrada"] or None,
                 "chamou": bool(r["transferir_para"] or ferramenta)},
        "custo": {"brl": float(r["custo_brl"] or 0), "usd": float(r["custo_usd"] or 0),
                  "tokens_entrada": int(r["tokens_entrada"] or 0), "tokens_saida": int(r["tokens_saida"] or 0),
                  "chamadas": int(r["chamadas"] or 0)},
    }


@api.get("")
async def listar(pedido: Request, _: Contexto = Depends(ADMIN), conta: str | None = None, agente: str | None = None,
                 busca: str = "", situacao: str = "", troca: bool = False, erro: bool = False,
                 de: str | None = None, ate: str | None = None, pagina: int = Query(1, ge=1, le=10_000),
                 por_pagina: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
    pool = _repo(pedido).pool
    onde: list[str] = []
    args: list[Any] = []

    def arg(valor: Any) -> str:
        args.append(valor)
        return f"${len(args)}"

    if (id_conta := _uuid(conta, "Conta")):
        onde.append(f"t.id_escritorio = {arg(id_conta)}::uuid")
    if (id_agente := _uuid(agente, "Agente")):
        onde.append(f"l.id_agente = {arg(id_agente)}::uuid")
    if situacao:
        if situacao not in SITUACOES:
            raise HTTPException(400, "Situação inválida.")
        onde.append(f"t.situacao = any({arg(SITUACOES[situacao])}::text[])")
    if erro:
        onde.append("t.situacao = 'erro'")
    if troca:
        onde.append("t.etapa_depois is not null and t.etapa_depois is distinct from t.etapa_antes")
    if (inicio := _data(de, "de")):
        onde.append(f"t.iniciado_em >= {arg(inicio)}")
    if (fim := _data(ate, "ate")):
        onde.append(f"t.iniciado_em < {arg(fim)}")
    busca = busca.strip()[:80]
    if busca:
        digitos = re.sub(r"\D", "", busca)
        partes = [f"ct.nome ilike {arg('%' + busca.replace('%', '').replace('_', '') + '%')}"]
        if len(digitos) >= 4:
            partes.append(f"ct.telefone_normalizado like {arg('%' + digitos + '%')}")
        onde.append("(" + " or ".join(partes) + ")")
    sql = (_SELECT_LISTA + (" where " + " and ".join(onde) if onde else "")
           + f" order by t.iniciado_em desc, t.id desc limit {arg(por_pagina + 1)} offset {arg((pagina - 1) * por_pagina)}")
    linhas = await pool.fetch(sql, *args)
    tem_mais = len(linhas) > por_pagina
    linhas = linhas[:por_pagina]
    nomes = await _nomes_por_agente(pool, {r["id_agente"] for r in linhas if r["id_agente"]})
    return {"itens": [_item(r, nomes) for r in linhas], "pagina": pagina, "por_pagina": por_pagina, "tem_mais": tem_mais}


def _prompt(contexto: Any) -> dict[str, Any]:
    """O que foi ao modelo: o sistema e o conteúdo da etapa (a última tentativa), o extrator e as tentativas."""
    if not isinstance(contexto, dict):
        return {"sistema": None, "conteudo": str(contexto) if contexto else None, "resposta_bruta": None,
                "extrator": None, "tentativas": [], "barreira": None}
    etapa = contexto.get("etapa") if isinstance(contexto.get("etapa"), dict) else {}
    extrator = contexto.get("extrator") if isinstance(contexto.get("extrator"), dict) else None

    def texto(v: Any) -> str | None:
        if v is None:
            return None
        return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, indent=2, default=str)

    return {
        "sistema": texto(etapa.get("sistema")), "conteudo": texto(etapa.get("conteudo")),
        "resposta_bruta": etapa.get("resposta"),
        "extrator": {"conteudo": texto(extrator.get("conteudo")), "resposta": extrator.get("resposta")} if extrator else None,
        "tentativas": contexto.get("tentativas") or [], "barreira": contexto.get("barreira"),
        "auditor": contexto.get("auditor"),
    }


@api.get("/{id_turno}")
async def detalhe(id_turno: str, pedido: Request, _: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    _uuid(id_turno, "Execução")
    pool = _repo(pedido).pool
    r = await pool.fetchrow(_SELECT_LISTA + " where t.id = $1::uuid", id_turno)
    if not r:
        raise HTTPException(404, "Execução não encontrada.")
    linha = await pool.fetchrow("select contexto, resposta from agentesia_turnos where id = $1::uuid", id_turno)
    nomes = await _nomes_por_agente(pool, {r["id_agente"]} if r["id_agente"] else set())
    item = _item(r, nomes)
    contexto = _obj(linha["contexto"])
    resposta = _obj(linha["resposta"]) if linha["resposta"] is not None else {}
    resposta = resposta if isinstance(resposta, dict) else {"bruto": resposta}

    mensagens = [dict(m) for m in await pool.fetch(
        """select id::text as id, autor, tipo, texto, texto_extraido, url_midia, enviada_em, situacao_envio, erro
             from agentesia_mensagens where id_lead = $1::uuid and id_turno = $2::uuid order by enviada_em, registrada_em""",
        r["id_lead"], id_turno)]
    for m in mensagens:
        m["enviada_em"] = m["enviada_em"].isoformat()
    eventos = []
    for e in await pool.fetch(
            """select tipo, gravidade, responsavel, descricao, detalhe, criado_em from agentesia_eventos
                where id_lead = $1::uuid and id_turno = $2::uuid order by criado_em""", r["id_lead"], id_turno):
        eventos.append({"tipo": e["tipo"], "titulo": _titulo(e["tipo"]), "gravidade": e["gravidade"],
                        "responsavel": e["responsavel"], "descricao": e["descricao"],
                        "detalhe": rastro._obj(e["detalhe"]), "criado_em": e["criado_em"].isoformat(),
                        "trava": e["tipo"] in TRAVAS or (rastro.tipo_do_evento(e["tipo"]) in ("recusa", "barreira"))})
    chamadas = [{**dict(c), "custo_usd": float(c["custo_usd"] or 0), "custo_brl": float(c["custo_brl"] or 0),
                 "criado_em": c["criado_em"].isoformat()} for c in await pool.fetch(
        """select papel, modelo, tokens_entrada, tokens_saida, tokens_cache, custo_usd, custo_brl, duracao_ms, sucesso,
                  erro, criado_em from agentesia_chamadas_ia where id_turno = $1::uuid order by criado_em""", id_turno)]
    anterior, seguinte = await pool.fetchval(
        """select id::text from agentesia_turnos where id_lead = $1::uuid and (iniciado_em, id) < ($2, $3::uuid)
            order by iniciado_em desc, id desc limit 1""", r["id_lead"], r["iniciado_em"], id_turno), await pool.fetchval(
        """select id::text from agentesia_turnos where id_lead = $1::uuid and (iniciado_em, id) > ($2, $3::uuid)
            order by iniciado_em, id limit 1""", r["id_lead"], r["iniciado_em"], id_turno)

    catalogo = contexto.get("catalogo") if isinstance(contexto, dict) and isinstance(contexto.get("catalogo"), dict) else {}
    decisao = {
        "transferir_para": catalogo.get("transferir_para") or None, "ferramenta": catalogo.get("ferramenta") or None,
        "ferramenta_barrada": catalogo.get("ferramenta_barrada"), "origem_destino": catalogo.get("origem_destino"),
        "notificacao": catalogo.get("notificacao") or None, "destinos": catalogo.get("destinos") or [],
        "acoes": catalogo.get("acoes") or [],
        "intencoes": resposta.get("intencoes") or {}, "fatos_novos": resposta.get("fatos_novos") or [],
        "fatos_rejeitados": resposta.get("fatos_rejeitados") or [], "reprovacoes": resposta.get("reprovacoes") or [],
        "decisoes": resposta.get("decisoes") or [], "faltam": resposta.get("faltam") or [],
        "sinais": resposta.get("sinais") or [], "estado_lead": resposta.get("estado_lead"),
        "motivo_estado": resposta.get("motivo_estado"), "ficha": resposta.get("ficha"),
    }
    return limpar({
        **item,
        "entrada": [m for m in mensagens if m["autor"] == "lead"],
        "saida": [m for m in mensagens if m["autor"] != "lead"],
        "mensagens_planejadas": resposta.get("mensagens") or [],
        "prompt": _prompt(contexto),
        "decisao": decisao,
        "eventos": eventos,
        "travas": [e for e in eventos if e["trava"]],
        "tempos": resposta.get("tempos"),
        "chamadas": chamadas,
        "navegacao": {"anterior": anterior, "seguinte": seguinte},
    })
