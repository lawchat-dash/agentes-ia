"""Automações do agente: "quando isto acontecer, faça aquilo".

Gatilhos saem do turno (lead novo, troca de etapa, pedido de humano, sinal, falha).
Para cada gatilho configurado no agente, viram ações na fila (agentesia_acoes),
que o executor manda para a Helena com novas tentativas.

Configuração (agentesia_agentes.config.automacoes), editável a qualquer hora:
    {
      "lead_novo":        {"coluna_crm": "<stepId>", "adicionar_etiquetas": ["📞 SDR"]},
      "etapa:closer":     {"coluna_crm": "<stepId>", "adicionar_etiquetas": ["🛒 Comercial"],
                           "remover_etiquetas": ["📞 SDR"]},
      "etapa:desqualificado": {"coluna_crm": "<stepId>", "nota": "Lead desqualificado pela IA."},
      "pediu_humano":     {"transferir": true, "nota": "Lead pediu para falar com uma pessoa."}
    }
"""

from __future__ import annotations

from typing import Any

from app.cerebro import auxilio_acidente
from app.cerebro.sinais import DO_AGENTE as SINAIS_DO_AGENTE

ETIQUETA_SDR = "📞 SDR"
NOTA_CARD_NAO_CRIADO = "⚠️ Card do lead não foi criado no CRM.\nMotivo: {detalhe}"

GATILHOS_FIXOS: dict[str, str] = {
    "lead_novo": "Lead novo (card e etiquetas na chegada do lead; nota e aviso na primeira resposta da IA)",
    "pediu_humano": "Lead pede para falar com uma pessoa",
    "pediu_para_parar": "Lead pede para não receber mais mensagens",
    "sinal": "Qualquer sinal confirmado (videochamada, áudio, não sabe ler, cliente antigo, outro benefício...)",
    "contrato_gerado": "Contrato gerado na ZapSign (versão nova)",
    "contrato_assinado": "O lead assinou o contrato",
    "contrato_falhou": "O contrato não pôde ser gerado",
    "followup_desistiu": "O lead não respondeu a nenhum follow-up (desistência)",
    "trava": "A IA foi barrada duas vezes e passou a conversa para a equipe",
    "ia_falhou": "A IA não conseguiu responder (provedor fora do ar, sem crédito...)",
}
CAMPOS = {"coluna_crm", "adicionar_etiquetas", "remover_etiquetas", "transferir", "id_equipe", "nota"}
NOMES_SINAIS = {
    "nao_sabe_ler": "diz que não sabe ler", "quer_audio": "quer receber áudio", "quer_videochamada": "pede videochamada",
    "cliente_antigo": "é cliente antigo", "outro_beneficio": "quer outro benefício",
    "dificuldade_assinatura": "não consegue assinar", "foto_contrato": "manda foto do contrato",
    "muitas_objecoes": "tem muitas objeções", "endereco_sem_falar": "não quer passar o endereço",
    "contrato_manual": "precisa de contrato manual", "analise_humana": "pede análise humana do caso",
}
INTENCOES_FIXAS = {"pediu_humano", "pediu_para_parar", "engano"}


def gatilhos_do_produto(produto: Any) -> dict[str, str]:
    """Gatilhos possíveis para um agente: os fixos, um por etapa e um por intenção própria."""
    gatilhos = dict(GATILHOS_FIXOS)
    for etapa in produto.etapas:
        gatilhos[f"etapa:{etapa.codigo}"] = f"Lead entra na etapa {etapa.nome}"
    for intencao in produto.intencoes:
        if intencao not in INTENCOES_FIXAS:
            gatilhos[f"intencao:{intencao}"] = f"Lead demonstra a intenção {intencao}"
    for sinal in getattr(produto, "sinais", ()):
        quem = "marcado pelo agente" if sinal in SINAIS_DO_AGENTE else "confirmado pelo auditor"
        gatilhos[f"sinal:{sinal}"] = f"Lead {NOMES_SINAIS.get(sinal, sinal)} ({quem})"
    return gatilhos


# Gatilhos do agente pronto (Auxílio-Acidente), usados quando ninguém informa o produto.
GATILHOS: dict[str, str] = {
    **GATILHOS_FIXOS,
    **{f"etapa:{e}": f"Lead entra na etapa {e}" for e in auxilio_acidente.ETAPAS},
    **{f"sinal:{s}": f"Lead {NOMES_SINAIS.get(s, s)}" for s in auxilio_acidente.SINAIS},
}


def validar(automacoes: dict[str, Any], gatilhos: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    """Limpa a configuração vinda do painel: só gatilhos e campos conhecidos."""
    gatilhos = gatilhos or GATILHOS
    limpa: dict[str, dict[str, Any]] = {}
    for gatilho, regra in (automacoes or {}).items():
        if gatilho not in gatilhos or not isinstance(regra, dict):
            continue
        item: dict[str, Any] = {}
        if regra.get("coluna_crm"):
            item["coluna_crm"] = str(regra["coluna_crm"])[:64]
        for campo in ("adicionar_etiquetas", "remover_etiquetas"):
            nomes = [str(n).strip()[:80] for n in regra.get(campo) or [] if str(n).strip()]
            if nomes:
                item[campo] = nomes[:10]
        if regra.get("transferir"):
            item["transferir"] = True
            if regra.get("id_equipe"):
                item["id_equipe"] = str(regra["id_equipe"])[:64]          # departamento desta regra
        if regra.get("nota") and str(regra["nota"]).strip():
            item["nota"] = str(regra["nota"]).strip()[:1000]
        if item:
            limpa[gatilho] = item
    return limpa


def gatilhos_do_turno(*, primeira_resposta: bool, etapa_antes: str, etapa_depois: str,
                      motivo_estado: str | None, situacao: str, sinais: list[str],
                      intencoes: dict[str, bool] | None = None) -> list[str]:
    gatilhos: list[str] = []
    if primeira_resposta and situacao == "respondido":
        gatilhos.append("lead_novo")
    if etapa_depois and etapa_depois != etapa_antes:
        gatilhos.append(f"etapa:{etapa_depois}")
    if motivo_estado in ("pediu_humano", "pediu_para_parar"):
        gatilhos.append(motivo_estado)
    if motivo_estado in ("trava_persistente", "pedido_repetido"):
        gatilhos.append("trava")
    if sinais:
        gatilhos.append("sinal")
        gatilhos.extend(f"sinal:{s}" for s in sinais)
    if situacao == "erro":
        gatilhos.append("ia_falhou")
    for intencao, marcada in (intencoes or {}).items():
        if marcada and intencao not in INTENCOES_FIXAS:
            gatilhos.append(f"intencao:{intencao}")
    return gatilhos


def montar_acoes(config_agente: dict[str, Any], config_crm: dict[str, Any] | None,
                 gatilhos: list[str], *, id_lead: str, id_turno: str, contexto: str = "",
                 avisos: set[str] | frozenset[str] = frozenset()) -> list[dict[str, Any]]:
    """Ações a enfileirar, na ordem em que devem rodar. Respeita as funções ligadas no agente."""
    funcoes = config_agente.get("funcoes") or {}
    automacoes = config_agente.get("automacoes") or {}
    id_painel = (config_crm or {}).get("id_painel")
    acoes: list[dict[str, Any]] = []
    sinais_sem_aviso = [g.split(":", 1)[1] for g in gatilhos if g.startswith("sinal:") and g not in avisos]

    for gatilho in gatilhos:
        chave = f"{id_lead}:{id_turno}:{gatilho}"
        chave_crm = _chave_crm(id_lead, id_turno, gatilho)
        if funcoes.get("avisos") and gatilho in avisos and not aviso_repetido(gatilho, gatilhos, avisos):
            # Aviso por WhatsApp à equipe, configurado pelo escritório em "Avisos à equipe".
            dados: dict[str, Any] = {"evento": gatilho}
            if gatilho == "sinal":
                dados["sinais"] = sinais_sem_aviso                # quais sinais foram (cita no cabeçalho)
            acoes.append({"tipo": "preparar_aviso", "chave_unica": f"{chave}:aviso", "dados": dados})
        regra = automacoes.get(gatilho)
        if not regra:
            continue
        if funcoes.get("crm") and id_painel and regra.get("coluna_crm"):
            acoes.append({"tipo": "mover_card", "chave_unica": f"{chave_crm}:card",
                          "dados": {"id_painel": id_painel, "id_etapa_helena": regra["coluna_crm"], "gatilho": gatilho}})
        if funcoes.get("crm") and (regra.get("adicionar_etiquetas") or regra.get("remover_etiquetas")):
            acoes.append({"tipo": "etiquetar", "chave_unica": f"{chave_crm}:etiquetas",
                          "dados": {"adicionar": regra.get("adicionar_etiquetas", []),
                                    "remover": regra.get("remover_etiquetas", []),
                                    "gatilho": gatilho}})          # o executor ignora se a etapa já mudou
        if funcoes.get("avisos") and regra.get("nota"):
            texto = regra["nota"] + (f"\n{contexto}" if contexto else "")
            acoes.append({"tipo": "nota", "chave_unica": f"{chave}:nota", "dados": {"texto": texto}})
        equipe = regra.get("id_equipe") or config_agente.get("id_equipe_transferencia")
        if funcoes.get("transferir_humano") and regra.get("transferir") and equipe:
            acoes.append({"tipo": "transferir", "chave_unica": f"{chave}:transferir", "dados": {"id_equipe": equipe}})
    return acoes


# Gatilho que repete outro do mesmo fato: se o outro tem aviso, este não manda um segundo WhatsApp.
AVISO_EQUIVALENTE = {"etapa:contrato_assinado": "contrato_assinado"}


def aviso_repetido(gatilho: str, gatilhos: list[str], avisos: set[str] | frozenset[str]) -> bool:
    """O mesmo fato já gera aviso por um gatilho mais específico (ou equivalente) deste turno?

    'sinal' (qualquer sinal) fica de fora quando todos os sinais do turno já têm aviso próprio; quando só alguns
    têm, o genérico vai e cita só os que ficaram sem aviso. 'etapa:contrato_assinado' é o mesmo fato que
    'contrato_assinado'."""
    if gatilho == "sinal":
        especificos = [g for g in gatilhos if g.startswith("sinal:")]
        return bool(especificos) and all(g in avisos for g in especificos)
    equivalente = AVISO_EQUIVALENTE.get(gatilho)
    return equivalente is not None and equivalente in gatilhos and equivalente in avisos


def _chave_crm(id_lead: str, id_turno: str, gatilho: str) -> str:
    """Card e etiquetas do lead novo têm uma chave só por lead: a chegada do lead e a primeira resposta da IA
    disparam o mesmo gatilho, e a fila (on conflict) deixa passar só o primeiro. Um lead, um card."""
    return f"{id_lead}:lead_novo" if gatilho == "lead_novo" else f"{id_lead}:{id_turno}:{gatilho}"


def acoes_do_lead_novo(config_agente: dict[str, Any], config_crm: dict[str, Any] | None,
                       *, id_lead: str) -> tuple[list[dict[str, Any]], str | None]:
    """Card na coluna SDR e etiqueta SDR na chegada do lead, sem depender da resposta da IA.

    Devolve (ações, problema). O problema diz por que o card não sai (sem painel ou sem coluna SDR);
    o pipeline transforma em evento 'card_nao_criado' e nota no chat. Sem a função CRM ligada não faz nada."""
    if not (config_agente.get("funcoes") or {}).get("crm"):
        return [], None
    regra = (config_agente.get("automacoes") or {}).get("lead_novo") or {}
    id_painel = (config_crm or {}).get("id_painel")
    chave = _chave_crm(id_lead, "", "lead_novo")
    acoes: list[dict[str, Any]] = []
    problema = None
    if not id_painel:
        problema = "o escritório não tem painel do CRM escolhido em Integrações, então o card não foi criado."
    elif not regra.get("coluna_crm"):
        problema = "o agente não tem a coluna SDR do CRM escolhida (automação Lead novo), então o card não foi criado."
    else:
        acoes.append({"tipo": "mover_card", "chave_unica": f"{chave}:card",
                      "dados": {"id_painel": id_painel, "id_etapa_helena": regra["coluna_crm"], "gatilho": "lead_novo"}})
    # A etiqueta SDR segue o card: o Executor não etiqueta contato que já tinha card (cliente antigo que respondeu à
    # atendente ou a um disparo por API), só o que não tem card ou cujo card este mesmo lead novo criou.
    acoes.append({"tipo": "etiquetar", "chave_unica": f"{chave}:etiquetas",
                  "dados": {"adicionar": regra.get("adicionar_etiquetas") or [ETIQUETA_SDR],
                            "remover": regra.get("remover_etiquetas", []), "gatilho": "lead_novo",
                            "id_painel": id_painel, "chave_card": f"{chave}:card"}})
    return acoes, problema


def titulo_do_card(nome: str | None, telefone: str | None) -> str:
    """'👤 Maria | 📞 (11) 98888-7777'; sem nome, só o telefone (como no n8n)."""
    from app.notificacoes import formatar_telefone

    nome = (nome or "").strip().strip("\"'“”‘’").strip()
    fone = formatar_telefone(telefone) if telefone else ""
    if nome and fone:
        return f"👤 {nome} | 📞 {fone}"
    return f"📞 {fone}" if fone else f"👤 {nome or 'Lead'}"


def descricao_do_card(origem: dict[str, Any] | None, iniciada_em: Any) -> str:
    """Anúncio (referralUrl), campanha e 'Conversa iniciada dd/mm/aaaa HH:mm' no horário de Brasília."""
    from datetime import datetime, timezone

    from app.notificacoes import fuso

    origem = origem or {}
    linhas = []
    if origem.get("url"):
        linhas.append(f"Anúncio: {origem['url']}")
    if origem.get("campanha"):
        linhas.append(f"Campanha: {origem['campanha']}")
    quando = iniciada_em if isinstance(iniciada_em, datetime) else datetime.now(timezone.utc)
    linhas.append(f"Conversa iniciada: {quando.astimezone(fuso()):%d/%m/%Y %H:%M}")
    return "\n".join(linhas)


# Palavras (sem acento, minúsculas) para achar a coluna e a etiqueta de cada papel do catálogo, e as que excluem
# (a coluna "Contrato assinado" não é a de Contratos). Nada de nome fixo de um escritório: é só a sugestão inicial.
PALAVRAS_DO_PAPEL: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "sdr": (("sdr", "novo", "entrada", "lead"), ()),
    "periododegraca": (("graca", "periodo"), ()),
    "closer": (("comercial", "closer", "proposta", "negocia"), ()),
    "contratos": (("contrato", "elabora", "document", "dados"), ("assinad", "assinatura")),
    "assinatura": (("assinatura",), ()),
    "contrato_assinado": (("assinado", "fechado", "ganho"), ()),
    "desqualificado": (("desqualif", "perdid", "descart"), ()),
}


def _sem_acento(texto: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", str(texto or "").lower()) if unicodedata.category(c) != "Mn")


def _parecido(itens: list[dict[str, Any]], campo: str, papel: str) -> dict[str, Any] | None:
    palavras, excluir = PALAVRAS_DO_PAPEL.get(papel, ((papel,), ()))
    for item in itens:
        nome = _sem_acento(item.get(campo) or "")
        if any(p in nome for p in palavras) and not any(x in nome for x in excluir):
            return item
    return None


def _sugestao_catalogo(etapas_crm: list[dict[str, Any]], produto: Any, inicial: str | None,
                       etiquetas: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    """Catálogo: lead novo na coluna SDR (ou a inicial) e uma regra 'etapa:<papel>' para cada papel depois do inicial,
    contrato assinado incluído. Com a lista de etiquetas da conta, cada etapa põe a etiqueta do papel e tira as das
    outras etapas (só quando a do destino existe, para o contato nunca ficar sem nenhuma), como a Troca do n8n."""
    papeis = [e.codigo for e in produto.etapas]
    nomes_etiqueta: dict[str, str] = {}
    for papel in papeis:
        achada = _parecido([e for e in etiquetas or [] if e.get("nome")], "nome", papel)
        if achada and achada["nome"] not in nomes_etiqueta.values():
            nomes_etiqueta[papel] = str(achada["nome"])
    regras: dict[str, dict[str, Any]] = {}
    coluna_sdr = (_parecido(etapas_crm, "titulo", produto.etapa_inicial()) or {}).get("id") or inicial
    regras["lead_novo"] = {"coluna_crm": coluna_sdr,
                           "adicionar_etiquetas": [nomes_etiqueta.get(produto.etapa_inicial()) or ETIQUETA_SDR]}
    for papel in papeis:
        if papel == produto.etapa_inicial():
            continue
        regra: dict[str, Any] = {"coluna_crm": (_parecido(etapas_crm, "titulo", papel) or {}).get("id")}
        if papel in nomes_etiqueta:
            regra["adicionar_etiquetas"] = [nomes_etiqueta[papel]]
            regra["remover_etiquetas"] = [n for p, n in nomes_etiqueta.items() if p != papel]
        regras[f"etapa:{papel}"] = regra
    regras["pediu_humano"] = {"transferir": True, "nota": "O lead pediu para falar com uma pessoa."}
    return validar(regras, gatilhos_do_produto(produto))


def sugestao_padrao(etapas_crm: list[dict[str, Any]], produto: Any = None,
                    etiquetas: list[dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    """Sugestão inicial quando o cliente escolhe o painel: liga as etapas por nome parecido. `etiquetas` (as da conta
    na Helena, [{nome}]) só é usada no catálogo, para sugerir a troca de etiqueta em cada etapa."""
    def achar(*palavras: str) -> str | None:
        for etapa in etapas_crm:
            titulo = (etapa.get("titulo") or "").lower()
            if any(p in titulo for p in palavras):
                return etapa["id"]
        return None

    inicial = next((e["id"] for e in etapas_crm if e.get("inicial")), etapas_crm[0]["id"] if etapas_crm else None)
    if produto is not None and getattr(produto, "codigo", None) == "catalogo":
        return _sugestao_catalogo(etapas_crm, produto, inicial, etiquetas)
    if produto is not None and produto.codigo == "proprio":
        # Agente próprio: liga cada etapa à coluna de nome parecido, e o lead novo à coluna inicial.
        regras: dict[str, dict[str, Any]] = {"lead_novo": {"coluna_crm": inicial},
                                             "pediu_humano": {"transferir": True, "nota": "O lead pediu para falar com uma pessoa."}}
        for etapa in produto.etapas[1:]:
            palavras = [p for p in etapa.nome.lower().split() if len(p) > 3] or [etapa.nome.lower()]
            regras[f"etapa:{etapa.codigo}"] = {"coluna_crm": achar(*palavras)}
        return validar(regras, gatilhos_do_produto(produto))
    regras = {
        "lead_novo": {"coluna_crm": achar("sdr", "novo", "entrada", "lead") or inicial, "adicionar_etiquetas": [ETIQUETA_SDR]},
        "etapa:closer": {"coluna_crm": achar("comercial", "closer", "proposta", "negocia")},
        "etapa:coleta_dados": {"coluna_crm": achar("contrato", "document", "dados")},
        "etapa:desqualificado": {"coluna_crm": achar("desqualif", "perdid", "descart")},
        "etapa:analise_manual": {"coluna_crm": achar("análise", "analise", "revis"), "transferir": True,
                                 "nota": "Caso para a equipe avaliar."},
        "pediu_humano": {"transferir": True, "nota": "O lead pediu para falar com uma pessoa."},
    }
    return validar(regras)
