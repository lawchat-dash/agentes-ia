"""Primeiros passos do escritório: a lista que se marca sozinha no Início do cliente e a coluna "Progresso" das Contas.

Cada passo é lido do que já existe no banco (nada chama a Helena), na ordem em que o cliente faz:

  conta       a equipe LawChat habilitou a função de agente da conta (Contas › Criar agente)
  whatsapp    há pelo menos um número de WhatsApp conectado na conta
  produto     há um produto (agente) ligado
  zapsign     ZapSign conectada e com modelo, só se algum agente gera contrato (senão "não se aplica")
  followup    o follow-up está ligado nos agentes ligados
  conversa    chegou a primeira mensagem de um lead de verdade (o Laboratório não grava no banco)
  saldo       a carteira tem saldo (pré-pago) ou o escritório não é cobrado por saldo

Situações: feito | pendente | nao_se_aplica (conta como feito: "4/7" é sempre de 7). Cada passo leva `para`, a tela
onde se resolve, e `acao`, o texto do botão.
"""

from __future__ import annotations

import json
from typing import Any

import asyncpg

PASSOS: list[tuple[str, str]] = [
    ("conta", "Conta habilitada"),
    ("whatsapp", "WhatsApp conectado"),
    ("produto", "Primeiro produto ativado"),
    ("zapsign", "ZapSign conectada"),
    ("followup", "Follow-up ligado"),
    ("conversa", "Primeira conversa real"),
    ("saldo", "Saldo de créditos"),
]
FEITOS = ("feito", "nao_se_aplica")
INTEGRACOES = "/minha-conta?aba=integracoes"


def _obj(valor: Any) -> dict[str, Any]:
    if isinstance(valor, str):
        try:
            valor = json.loads(valor)
        except json.JSONDecodeError:
            return {}
    return valor if isinstance(valor, dict) else {}


def _followup_ligado(config: dict[str, Any]) -> bool:
    try:
        from app.followup import padrao
        return bool(padrao.situacao(config)["ligado"])
    except Exception:                                   # sem o módulo (ou config estranha): lê o campo direto
        return bool(_obj(config.get("followup")).get("ativo"))


async def _saldo(pool: Any, id_escritorio: str) -> tuple[str, str]:
    try:
        from app import cobranca
        atual = await cobranca.situacao(pool, id_escritorio)
    except (asyncpg.UndefinedTableError, asyncpg.UndefinedColumnError):
        atual = None
    if atual is None:
        return "nao_se_aplica", "o escritório ainda não usa carteira de créditos"
    if atual.modo != "pre_pago":
        return "nao_se_aplica", "o consumo da IA é cobrado à parte, sem saldo pré-pago"
    if atual.disponivel_brl > 0:
        return "feito", f"R$ {atual.disponivel_brl:,.2f} disponível".replace(",", "X").replace(".", ",").replace("X", ".")
    return "pendente", "sem saldo: a IA para de responder até entrar uma recarga"


async def calcular(pool: Any, id_escritorio: str) -> dict[str, Any]:
    """Os 7 passos do escritório, com o próximo a fazer e o total."""
    escritorio = await pool.fetchrow(
        """select e.config, (select situacao from agentesia_integracoes i where i.id_escritorio = e.id and i.tipo = 'helena') as helena
           from agentesia_escritorios e where e.id = $1::uuid""", id_escritorio)
    config_escritorio = _obj(escritorio["config"]) if escritorio else {}
    integracoes = {r["tipo"]: {"situacao": r["situacao"], "config": _obj(r["config"])} for r in await pool.fetch(
        "select tipo, situacao, config from agentesia_integracoes where id_escritorio = $1::uuid", id_escritorio)}
    agentes = [dict(r) | {"config": _obj(r["config"])} for r in await pool.fetch(
        """select a.id::text as id, a.nome, a.situacao, a.config, a.id_canal is not null as tem_numero
           from agentesia_agentes a where a.id_escritorio = $1::uuid order by a.criado_em""", id_escritorio)]
    numeros = await pool.fetchval(
        "select count(*) from agentesia_canais where id_escritorio = $1::uuid and ativo", id_escritorio) or 0
    primeira = await pool.fetchval(
        """select min(m.enviada_em) from agentesia_mensagens m
           where m.id_escritorio = $1::uuid and m.autor = 'lead'""", id_escritorio)

    passos: dict[str, dict[str, Any]] = {}

    def passo(codigo: str, situacao: str, detalhe: str, para: str | None, acao: str | None) -> None:
        passos[codigo] = {"codigo": codigo, "titulo": dict(PASSOS)[codigo], "situacao": situacao, "detalhe": detalhe,
                          "para": para, "acao": acao}

    # 1. Conta habilitada (mesma regra da tela Contas: sem marca, vale a Helena conectada).
    marca = _obj(config_escritorio.get("criar_agente"))
    habilitada = bool(marca.get("habilitado")) if marca else (escritorio is not None and escritorio["helena"] == "ok")
    passo("conta", "feito" if habilitada else "pendente",
          "a equipe LawChat habilitou a função de agente" if habilitada
          else "Fale com a equipe LawChat para habilitar", None if habilitada else INTEGRACOES,
          None if habilitada else "Ver integrações")

    # 2. WhatsApp conectado
    passo("whatsapp", "feito" if numeros else "pendente",
          f"{numeros} número(s) conectado(s)" if numeros
          else "nenhum WhatsApp conectado na conta: conecte o número e peça à equipe LawChat para sincronizar",
          INTEGRACOES, "Ver números")

    # 3. Primeiro produto ativado
    ligados = [a for a in agentes if a["situacao"] == "ativo"]
    if ligados:
        passo("produto", "feito", f"{ligados[0]['nome']} ligado", "/meus-produtos", "Meus agentes")
    elif agentes:
        passo("produto", "pendente", f"{agentes[0]['nome']} criado, mas ainda desligado", "/meus-produtos", "Ativar")
    else:
        passo("produto", "pendente", "escolha um produto na Biblioteca e ative", "/biblioteca", "Abrir a Biblioteca")

    # 4. ZapSign (só se algum agente gera contrato)
    com_contrato = [a for a in agentes if _obj(a["config"].get("funcoes")).get("contrato_zapsign")]
    zapsign = integracoes.get("zapsign") or {}
    modelos = [m for m in (zapsign.get("config") or {}).get("modelos") or [] if isinstance(m, dict) and m.get("id_modelo")]
    if not com_contrato:
        passo("zapsign", "nao_se_aplica", "nenhum agente gera contrato pela IA", INTEGRACOES, "Ver ZapSign")
    elif zapsign.get("situacao") == "ok" and modelos:
        passo("zapsign", "feito", f"conectada, {len(modelos)} modelo(s) de contrato", INTEGRACOES, "Ver ZapSign")
    elif zapsign.get("situacao") == "ok":
        passo("zapsign", "pendente", "conectada; falta escolher o modelo de contrato", INTEGRACOES, "Escolher modelo")
    else:
        passo("zapsign", "pendente", f"{com_contrato[0]['nome']} gera contrato: conecte a ZapSign", INTEGRACOES, "Conectar ZapSign")

    # 5. Follow-up ligado (nos agentes ligados)
    sem_followup = [a for a in ligados if not _followup_ligado(a["config"])]
    if not ligados:
        passo("followup", "pendente", "ligue um produto primeiro", "/meus-produtos", "Meus agentes")
    elif sem_followup:
        passo("followup", "pendente", f"desligado em {', '.join(a['nome'] for a in sem_followup[:3])}",
              f"/agentes/{sem_followup[0]['id']}/followup", "Ligar follow-up")
    else:
        passo("followup", "feito", "ligado em todos os agentes ativos", f"/agentes/{ligados[0]['id']}/followup", "Ver follow-up")

    # 6. Primeira conversa real
    passo("conversa", "feito" if primeira else "pendente",
          f"primeira mensagem em {primeira:%d/%m/%Y}" if primeira
          else "ainda não chegou mensagem de lead; teste mandando uma mensagem para o número do agente",
          "/atendimento", "Abrir a Central")

    # 7. Saldo
    situacao, detalhe = await _saldo(pool, id_escritorio)
    passo("saldo", situacao, detalhe, "/consumo", "Ver créditos")

    lista = [passos[c] for c, _ in PASSOS]
    feitos = sum(1 for p in lista if p["situacao"] in FEITOS)
    proximo = next((p["codigo"] for p in lista if p["situacao"] not in FEITOS), None)
    return {"passos": lista, "feitos": feitos, "total": len(lista), "completo": proximo is None, "proximo": proximo}


async def de_todos(pool: Any) -> dict[str, dict[str, Any]]:
    """Progresso de cada escritório (coluna "Progresso" das Contas): feitos, total e os títulos que faltam."""
    saida: dict[str, dict[str, Any]] = {}
    for linha in await pool.fetch("select id::text as id from agentesia_escritorios"):
        try:
            r = await calcular(pool, linha["id"])
        except Exception:                               # uma conta com dado estranho não derruba a tabela
            import logging
            logging.getLogger("agentesia").exception("falha nos primeiros passos de %s", linha["id"])
            continue
        saida[linha["id"]] = {"feitos": r["feitos"], "total": r["total"], "completo": r["completo"],
                              "faltam": [f"{p['titulo']}: {p['detalhe']}" for p in r["passos"] if p["situacao"] not in FEITOS]}
    return saida
