"""Rastro da conversa (item B11 de docs/ANALISE_5_PROJETOS.md): o funil do agente com a etapa ativa e uma linha do
tempo única de quem atendeu, quando e por quê.

Junta, em ordem de horário (o mais recente primeiro), o que já é gravado:
  agentesia_lead_etapas   as passagens (de, para, origem: ia | frase | equipe | equipe_crm | contrato | entrada)
  agentesia_eventos       recusas de troca, barreiras e travas, sinais do lead (e a etapa_trocada, quando o banco ainda
                          não tem o histórico de etapas)
  agentesia_alteracoes    as pausas e religadas da IA pela equipe (painel, etiqueta, botão da Helena)

Cada item: {quando, tipo: entrada|passagem|recusa|barreira|alerta|pausa, titulo, de, para, quem, motivo, evento}.
Só leitura; nada aqui muda a conversa.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import asyncpg

LIMITE = 80

# Nomes legíveis dos tipos de evento que entram no rastro (os que outra frente ainda vai criar já estão aqui).
TITULOS: dict[str, str] = {
    "etapa_trocada": "Passagem de etapa",
    "destino_recusado": "Troca recusada: destino não permitido",
    "troca_precoce_recusada": "Troca recusada: cedo demais",
    "transferencia_adiada_pergunta_aberta": "Troca adiada: havia pergunta em aberto",
    "troca_barrada_faltam_fatos": "Troca barrada: faltam fatos",
    "portao_de_fatos": "Portão de fatos: faltam dados para passar",
    "trocas_demais": "Trocas demais na mesma conversa",
    "troca_pela_frase": "Troca feita pela frase de passagem",
    "destino_ignorado": "Destino ignorado",
    "destino_para_tras_ignorado": "Destino para trás ignorado",
    "sinal_recusado": "Sinal não confirmado",
    "formato_invalido": "Resposta da IA fora do formato",
    "ia_fora_do_formato": "Resposta da IA fora do formato",
    "fora_do_tema": "Mensagem fora do tema",
    "tentativa_de_manipular": "Tentativa de manipular a IA",
    "trava_persistente": "Travas reprovaram duas vezes",
    "pediu_humano": "Lead pediu uma pessoa",
    "lead_quente": "Lead quente",
    "lead_parado": "Lead parado",
}
RECUSAS = {"destino_recusado", "troca_precoce_recusada", "transferencia_adiada_pergunta_aberta",
           "troca_barrada_faltam_fatos", "portao_de_fatos", "trocas_demais", "destino_ignorado",
           "destino_para_tras_ignorado", "sinal_recusado"}
BARREIRAS = {"formato_invalido", "ia_fora_do_formato", "fora_do_tema", "tentativa_de_manipular", "trava_persistente"}
ALERTAS = {"pediu_humano", "lead_quente", "lead_parado"}
PREFIXOS = {"barreira_": "barreira", "trava_": "barreira", "sinal_": "alerta"}
QUEM_DA_ORIGEM = {"ia": "ia", "frase": "frase", "equipe": "painel", "painel": "painel", "equipe_crm": "card",
                  "contrato": "contrato", "entrada": "entrada", "sistema": "sistema"}
NOMES_ETAPAS = {
    "sdr": "SDR", "periodo_graca": "Período de graça", "periododegraca": "Período de graça", "closer": "Closer",
    "contratos": "Contratos", "coleta_dados": "Dados do contrato", "assinatura": "Assinatura",
    "contrato_assinado": "Contrato assinado", "analise_manual": "Análise da equipe", "desqualificado": "Desqualificado",
}
DESVIOS = {"desqualificado", "analise_manual"}
PAUSAS = {"desligou_ia": "IA desligada pela equipe", "religou_ia": "IA religada pela equipe", "pausar": "IA pausada pela equipe",
          "devolver": "Conversa devolvida para a IA", "encerrar": "Conversa encerrada pela equipe",
          "desativar": "IA desligada pela equipe", "reativar": "IA religada pela equipe"}


def _obj(valor: Any) -> dict[str, Any]:
    if isinstance(valor, str):
        try:
            valor = json.loads(valor)
        except json.JSONDecodeError:
            return {}
    return valor if isinstance(valor, dict) else {}


def tipo_do_evento(tipo: str) -> str | None:
    if tipo in RECUSAS:
        return "recusa"
    if tipo in BARREIRAS:
        return "barreira"
    if tipo in ALERTAS:
        return "alerta"
    return next((v for p, v in PREFIXOS.items() if tipo.startswith(p)), None)


def titulo_do_evento(tipo: str) -> str:
    if tipo in TITULOS:
        return TITULOS[tipo]
    if tipo.startswith("trava_"):
        return "Trava: " + tipo[6:].replace("_", " ")
    if tipo.startswith("barreira_"):
        return "Barreira: " + tipo[9:].replace("_", " ")
    if tipo.startswith("sinal_"):
        return "Sinal do lead: " + tipo[6:].replace("_", " ")
    return tipo.replace("_", " ").capitalize()


def nomes_das_etapas(config: dict[str, Any]) -> dict[str, str]:
    nomes = dict(NOMES_ETAPAS)
    for e in (_obj(config.get("definicao")).get("etapas") or []):
        if isinstance(e, dict) and e.get("codigo") and e.get("nome"):
            nomes[e["codigo"]] = e["nome"]
    for codigo, papel in (_obj(config.get("catalogo")).get("papeis") or {}).items():
        if isinstance(papel, dict) and papel.get("nome"):
            nomes[codigo] = papel["nome"]
    return nomes


async def montar(pool: Any, lead: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """(funil, rastro) da conversa. `lead` é a linha de RepositorioGestao.conversa (id, id_escritorio, id_agente, etapa)."""
    id_lead, id_escritorio = str(lead["id"]), str(lead["id_escritorio"])
    config: dict[str, Any] = {}
    etapas: list[dict[str, Any]] = []
    if lead.get("id_agente"):
        config = _obj(await pool.fetchval("select config from agentesia_agentes where id = $1::uuid", str(lead["id_agente"])))
        etapas = [dict(r) for r in await pool.fetch(
            "select codigo, ordem, tipo from agentesia_agente_etapas where id_agente = $1::uuid order by ordem",
            str(lead["id_agente"]))]
    nomes = nomes_das_etapas(config)

    rastro: list[dict[str, Any]] = []
    try:
        trocas = [dict(r) for r in await pool.fetch(
            """select etapa_de, etapa_para, origem, id_turno::text as id_turno, criado_em from agentesia_lead_etapas
               where id_lead = $1::uuid order by criado_em desc limit $2""", id_lead, LIMITE)]
        tem_historico = True
    except asyncpg.UndefinedTableError:                 # banco sem a migração 006
        trocas, tem_historico = [], False
    motivos_turno: dict[str, str] = {}
    ids_turno = [t["id_turno"] for t in trocas if t["id_turno"]]
    if ids_turno:
        motivos_turno = {r["id"]: r["motivo"] for r in await pool.fetch(
            "select id::text as id, motivo from agentesia_turnos where id = any($1::uuid[])", ids_turno) if r["motivo"]}

    eventos = [dict(r) | {"detalhe": _obj(r["detalhe"])} for r in await pool.fetch(
        """select tipo, gravidade, descricao, detalhe, id_turno::text as id_turno, criado_em from agentesia_eventos
           where id_lead = $1::uuid and (tipo = any($2::text[]) or tipo like 'trava\\_%' or tipo like 'barreira\\_%'
                                         or tipo like 'sinal\\_%')
           order by criado_em desc limit $3""",
        id_lead, ["etapa_trocada", "troca_pela_frase", *RECUSAS, *BARREIRAS, *ALERTAS], LIMITE)]
    trocadas = [e for e in eventos if e["tipo"] == "etapa_trocada"]
    pela_frase = [e for e in eventos if e["tipo"] == "troca_pela_frase"]

    def perto(lista: list[dict[str, Any]], quando: Any, para: str | None, id_turno: str | None) -> dict[str, Any] | None:
        for e in lista:
            if id_turno and (e.get("id_turno") == id_turno or e["detalhe"].get("id_turno") == id_turno):
                return e
            if abs(e["criado_em"] - quando) <= timedelta(minutes=2) and e["detalhe"].get("para", e["detalhe"].get("destino")) in (para, None):
                return e
        return None

    for t in trocas:
        evento = perto(trocadas, t["criado_em"], t["etapa_para"], t["id_turno"])
        origem = t["origem"] or (evento or {}).get("detalhe", {}).get("origem") or ("ia" if t["id_turno"] else None)
        if origem == "ia" and perto(pela_frase, t["criado_em"], t["etapa_para"], t["id_turno"]):
            origem = "frase"
        motivo = ((evento or {}).get("detalhe", {}).get("motivo") or motivos_turno.get(t["id_turno"] or "") or None)
        if t["etapa_de"] is None:
            rastro.append({"quando": t["criado_em"], "tipo": "entrada", "titulo": "Entrou no funil", "de": None,
                           "para": t["etapa_para"], "quem": QUEM_DA_ORIGEM.get(origem or "", origem), "motivo": motivo,
                           "evento": None})
        else:
            rastro.append({"quando": t["criado_em"], "tipo": "passagem", "titulo": "Passagem de etapa", "de": t["etapa_de"],
                           "para": t["etapa_para"], "quem": QUEM_DA_ORIGEM.get(origem or "", origem), "motivo": motivo,
                           "evento": None})
    if not tem_historico or not trocas:
        # Sem o histórico de etapas: as passagens vêm do evento etapa_trocada.
        for e in trocadas:
            d = e["detalhe"]
            rastro.append({"quando": e["criado_em"], "tipo": "passagem", "titulo": "Passagem de etapa", "de": d.get("de"),
                           "para": d.get("para"), "quem": QUEM_DA_ORIGEM.get(d.get("origem") or "", d.get("origem")),
                           "motivo": d.get("motivo"), "evento": "etapa_trocada"})

    for e in eventos:
        tipo = tipo_do_evento(e["tipo"])
        if tipo is None:
            continue
        d = e["detalhe"]
        rastro.append({"quando": e["criado_em"], "tipo": tipo, "titulo": titulo_do_evento(e["tipo"]),
                       "de": d.get("etapa"), "para": d.get("destino") or d.get("para"),
                       "quem": "ia" if tipo in ("recusa", "barreira") else "lead",
                       "motivo": e["descricao"], "evento": e["tipo"]})

    for h in await pool.fetch(
            """select h.acao, h.resumo, h.depois, h.criado_em, u.nome as usuario from agentesia_alteracoes h
               left join agentesia_usuarios u on u.id = h.id_usuario
               where h.id_escritorio = $1::uuid and h.tabela = 'agentesia_leads'
                 and (h.id_registro = $2::uuid or coalesce(h.depois -> 'leads', '[]'::jsonb) ? $3)
               order by h.criado_em desc limit $4""", id_escritorio, id_lead, id_lead, LIMITE):
        if h["acao"] not in PAUSAS:
            continue
        depois = _obj(h["depois"])
        origem = depois.get("origem")
        quem = {"etiqueta": "etiqueta", "botao": "botao", "painel": "painel"}.get(origem or "", "painel")
        rastro.append({"quando": h["criado_em"], "tipo": "pausa", "titulo": PAUSAS[h["acao"]], "de": None, "para": None,
                       "quem": quem, "motivo": h["resumo"] + (f" ({h['usuario']})" if h["usuario"] else ""), "evento": h["acao"]})

    rastro.sort(key=lambda i: i["quando"], reverse=True)
    rastro = rastro[:LIMITE]
    for item in rastro:
        item["quando"] = item["quando"].isoformat()
        item["nome_de"] = nomes.get(item["de"] or "", item["de"])
        item["nome_para"] = nomes.get(item["para"] or "", item["para"])

    ativa = lead.get("etapa")
    visitadas = {t["etapa_para"] for t in trocas} | {t["etapa_de"] for t in trocas if t["etapa_de"]}
    ordem = [e["codigo"] for e in etapas]
    posicao = ordem.index(ativa) if ativa in ordem else -1
    alcancaveis = []
    if ativa and posicao >= 0 and lead.get("estado") != "encerrado":
        # Só para a frente no funil (Desqualificado vale sempre); Contratos não passa para Assinatura sozinho.
        for codigo in ordem[posicao + 1:]:
            if codigo in DESVIOS and codigo != "desqualificado":
                continue
            if ativa == "contratos" and codigo == "assinatura":
                continue
            alcancaveis.append(codigo)
        if ativa != "desqualificado" and "desqualificado" in ordem and "desqualificado" not in alcancaveis:
            alcancaveis.append("desqualificado")
    funil = {"etapas": [{"codigo": e["codigo"], "nome": nomes.get(e["codigo"], e["codigo"]), "tipo": e["tipo"],
                         "ativa": e["codigo"] == ativa, "visitada": e["codigo"] in visitadas,
                         "alcancavel": e["codigo"] in alcancaveis} for e in etapas],
             "ativa": ativa, "nome_ativa": nomes.get(ativa or "", ativa), "alcancaveis": alcancaveis}
    return funil, rastro
