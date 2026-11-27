"""Primeiros passos do escritório: a lista que se marca sozinha no Início do cliente e a coluna "Progresso" das Contas.

Cada passo é lido do que já existe no banco (nada chama a Helena), na ordem do processo da LawChat (o dono pediu para
"forçar" esse caminho: número, CRM com as etapas certas, roteiro, dados da firma e só então ativar):

  conta       a equipe LawChat habilitou a função de agente da conta (Contas › Criar agente)
  whatsapp    há pelo menos um número de WhatsApp conectado na conta (botão: /minha-conta/canais)
  crm         painel do CRM escolhido e as 6 etapas da IA marcadas (config do CRM "etapas_por_tipo")
  roteiro     só no plano com mídia (Ouro para cima; conta sem plano também): um produto com os materiais
              principais gravados. No plano sem mídia (ou sem produto com roteiro) o passo nem aparece.
  dados       Dados do escritório preenchidos (nome do escritório no mínimo): valem para todos os agentes
  produto     há um agente ligado
  followup    o follow-up está ligado nos agentes ligados

Saíram (pedido do dono): ZapSign (fica dentro da ativação do agente), conversa de teste e primeira recarga.
Situações: feito | pendente | nao_se_aplica (conta como feito). Cada passo leva `para`, a tela onde se resolve, e
`acao`, o texto do botão.
"""

from __future__ import annotations

import json
from typing import Any

import asyncpg

PASSOS: list[tuple[str, str]] = [
    ("conta", "Conta habilitada"),
    ("whatsapp", "WhatsApp conectado"),
    ("crm", "CRM criado com as etapas"),
    ("roteiro", "Roteiro gravado"),
    ("dados", "Dados do escritório"),
    ("produto", "Primeiro agente ativado"),
    ("followup", "Follow-up ligado"),
]
FEITOS = ("feito", "nao_se_aplica")
INTEGRACOES = "/minha-conta?aba=integracoes"
CANAIS = "/minha-conta/canais"
# As 6 colunas fixas do CRM da IA (app/gestao/painel_crm_padrao.TIPOS_NA_ORDEM).
TIPOS_CRM = ("SDR", "COMERCIAL", "CONTRATO", "AGUARDANDO_ASSINATURA", "CONTRATO_ASSINADO", "DESQUALIFICADO")


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


async def _roteiro(pool: Any, id_escritorio: str) -> dict[str, Any] | None:
    """None = o passo não aparece (plano sem mídia, ou nenhum produto com roteiro). Senão {"concluido": nome do 1º
    produto com os materiais principais gravados, ou None}. Mesma regra da tela do roteiro (rotas_roteiro_gravacao):
    obrigatórias = partes ativas fora de "objecoes"; conta sem plano é liberada."""
    try:
        plano = await pool.fetchrow(
            """select p.midia from agentesia_carteiras c join agentesia_planos p on p.id = c.id_plano
                where c.id_escritorio = $1::uuid""", id_escritorio)
        if plano is not None and not plano["midia"]:
            return None
        linhas = await pool.fetch(
            """select b.nome,
                      count(*) filter (where r.secao <> 'objecoes') as obrigatorias,
                      count(*) filter (where r.secao <> 'objecoes' and exists (
                          select 1 from agentesia_roteiro_gravacoes g where g.id_escritorio = $1::uuid
                             and g.chave = case when nullif(r.chave_geral, '') is not null then 'geral:' || r.chave_geral
                                                else 'parte:' || r.id::text end)) as gravadas
                 from agentesia_biblioteca_produtos b
                 join agentesia_roteiro_partes r on r.id_produto_biblioteca = b.id and r.ativo
                where b.modo_midia = 'audio' and b.status = 'publicado'
                group by b.id, b.nome order by b.nome""", id_escritorio)
    except (asyncpg.UndefinedTableError, asyncpg.UndefinedColumnError):
        return None
    if not linhas:
        return None
    pronto = next((l["nome"] for l in linhas if l["obrigatorias"] and l["gravadas"] >= l["obrigatorias"]), None)
    return {"concluido": pronto}


_SQL_PASSOS = """
select exists(select 1 from agentesia_escritorios where id = $1::uuid) as existe,
       (select e.config from agentesia_escritorios e where e.id = $1::uuid) as config,
       (select i.situacao from agentesia_integracoes i where i.id_escritorio = $1::uuid and i.tipo = 'helena') as helena,
       (select coalesce(json_agg(json_build_object('tipo', i.tipo, 'situacao', i.situacao, 'config', i.config)), '[]'::json)
          from agentesia_integracoes i where i.id_escritorio = $1::uuid) as integracoes,
       (select coalesce(json_agg(json_build_object('id', a.id::text, 'nome', a.nome, 'situacao', a.situacao, 'config', a.config,
                                                   'tem_numero', a.id_canal is not null) order by a.criado_em), '[]'::json)
          from agentesia_agentes a where a.id_escritorio = $1::uuid) as agentes,
       (select count(*) from agentesia_canais where id_escritorio = $1::uuid and ativo) as numeros
"""


def _lista(valor: Any) -> list[dict[str, Any]]:
    if isinstance(valor, str):
        valor = json.loads(valor)
    return valor if isinstance(valor, list) else []


async def calcular(pool: Any, id_escritorio: str) -> dict[str, Any]:
    """Os passos do escritório (6 ou 7: o roteiro só no plano com mídia), com o próximo a fazer e o total."""
    import asyncio
    # Uma consulta só (escritório, integrações, agentes, números e primeira mensagem) em paralelo com a do saldo: antes
    # eram 6 a 7 idas ao banco em sequência (~200 ms cada com o banco em us-west-2).
    linha, roteiro = await asyncio.gather(pool.fetchrow(_SQL_PASSOS, id_escritorio), _roteiro(pool, id_escritorio))
    escritorio = {"helena": linha["helena"]} if linha["existe"] else None
    config_escritorio = _obj(linha["config"]) if escritorio else {}
    integracoes = {r["tipo"]: {"situacao": r["situacao"], "config": _obj(r["config"])}
                   for r in _lista(linha["integracoes"])}
    agentes = [dict(r) | {"config": _obj(r["config"])} for r in _lista(linha["agentes"])]
    numeros = linha["numeros"] or 0

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
          else "conecte o WhatsApp do escritório na plataforma de atendimento",
          CANAIS, "Ver números" if numeros else "Conectar o número")

    # 3. CRM com as etapas da IA marcadas
    crm = (integracoes.get("crm") or {}).get("config") or {}
    por_tipo = crm.get("etapas_por_tipo") if isinstance(crm.get("etapas_por_tipo"), dict) else {}
    marcadas = [t for t in TIPOS_CRM if por_tipo.get(t)]
    if crm.get("id_painel") and len(marcadas) == len(TIPOS_CRM):
        passo("crm", "feito", f"painel {crm.get('titulo_painel') or 'escolhido'} com as {len(TIPOS_CRM)} etapas marcadas",
              "/crm", "Ver o CRM")
    elif crm.get("id_painel"):
        passo("crm", "pendente", f"faltam {len(TIPOS_CRM) - len(marcadas)} etapa(s) para marcar no painel", "/crm", "Marcar etapas")
    else:
        passo("crm", "pendente", "crie o painel do CRM com as etapas sugeridas e marque cada uma aqui", "/crm", "Criar o CRM")

    # 4. Roteiro (só no plano com mídia)
    if roteiro is not None:
        pronto = roteiro.get("concluido")
        passo("roteiro", "feito" if pronto else "pendente",
              f"roteiro de {pronto} gravado" if pronto
              else "escolha um produto e grave o roteiro (vídeos e áudios principais)", "/roteiros",
              "Ver roteiros" if pronto else "Gravar o roteiro")

    # 5. Dados do escritório
    dados = _obj(config_escritorio.get("dados_escritorio"))
    if str(dados.get("nome") or "").strip():
        passo("dados", "feito", f"{dados['nome']}: valem para todos os agentes", None, "Editar dados")
    else:
        passo("dados", "pendente", "preencha uma vez os dados da firma: entram em todos os agentes", None, "Preencher dados")

    # 6. Primeiro agente ativado (agente sem número é sobra de produto excluído: não conta)
    ligados = [a for a in agentes if a["situacao"] == "ativo"]
    com_numero = [a for a in agentes if a.get("tem_numero")]
    if ligados:
        passo("produto", "feito", f"{ligados[0]['nome']} ligado", "/meus-produtos", "Meus agentes")
    elif com_numero:
        passo("produto", "pendente", f"{com_numero[0]['nome']} criado, mas ainda desligado", "/meus-produtos", "Ativar")
    else:
        passo("produto", "pendente", "escolha um produto na Biblioteca e ative", "/biblioteca", "Abrir a Biblioteca")

    # 7. Follow-up ligado (nos agentes ligados)
    sem_followup = [a for a in ligados if not _followup_ligado(a["config"])]
    if not ligados:
        passo("followup", "pendente", "ligue um agente primeiro", "/meus-produtos", "Meus agentes")
    elif sem_followup:
        passo("followup", "pendente", f"desligado em {', '.join(a['nome'] for a in sem_followup[:3])}",
              f"/agentes/{sem_followup[0]['id']}/followup", "Ligar follow-up")
    else:
        passo("followup", "feito", "ligado em todos os agentes ativos", f"/agentes/{ligados[0]['id']}/followup", "Ver follow-up")

    lista = [passos[c] for c, _ in PASSOS if c in passos]
    feitos = sum(1 for p in lista if p["situacao"] in FEITOS)
    proximo = next((p["codigo"] for p in lista if p["situacao"] not in FEITOS), None)
    return {"passos": lista, "feitos": feitos, "total": len(lista), "completo": proximo is None, "proximo": proximo}


async def de_todos(pool: Any) -> dict[str, dict[str, Any]]:
    """Progresso de cada escritório (coluna "Progresso" das Contas): feitos, total e os títulos que faltam.
    Até 2 escritórios ao mesmo tempo (cada um usa 2 conexões; o pool do painel é pequeno) (antes um depois do outro: N contas x idas ao banco em sequência)."""
    import asyncio
    import logging
    saida: dict[str, dict[str, Any]] = {}
    vagas = asyncio.Semaphore(2)

    async def um(id_escritorio: str) -> None:
        async with vagas:
            try:
                r = await calcular(pool, id_escritorio)
            except Exception:                           # uma conta com dado estranho não derruba a tabela
                logging.getLogger("agentesia").exception("falha nos primeiros passos de %s", id_escritorio)
                return
        saida[id_escritorio] = {"feitos": r["feitos"], "total": r["total"], "completo": r["completo"],
                                "faltam": [f"{p['titulo']}: {p['detalhe']}" for p in r["passos"] if p["situacao"] not in FEITOS]}

    ids = [linha["id"] for linha in await pool.fetch("select id::text as id from agentesia_escritorios order by criado_em")]
    await asyncio.gather(*(um(i) for i in ids))
    return {i: saida[i] for i in ids if i in saida}
