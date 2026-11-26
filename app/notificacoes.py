"""Avisos à equipe do escritório por WhatsApp (antigo fluxo n8n "WEAVER - Alerta Notificação").

O escritório configura, por evento, o texto do aviso e quem recebe (agentesia_notificacoes).
O evento é o mesmo nome dos gatilhos das automações: etapa:closer, sinal:nao_sabe_ler, contrato_assinado...
Aqui ficam as funções puras (montar o texto, filtrar quem recebe); o envio é ação da fila (app/acoes.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Nomes amigáveis dos eventos mais usados (o legado usava códigos próprios; ver docs/n8n/alerta_notificacao.md).
NOMES_DE_EVENTO: dict[str, str] = {
    "lead_novo": "Lead novo",
    "etapa:closer": "Lead qualificado (proposta)",
    "etapa:coleta_dados": "Lead começou a passar os dados",
    "etapa:assinatura": "Aguardando assinatura",
    "etapa:analise_manual": "Caso para análise da equipe",
    "etapa:desqualificado": "Lead desqualificado",
    "pediu_humano": "Lead pediu uma pessoa",
    "sinal:nao_sabe_ler": "Lead não sabe ler",
    "sinal:quer_audio": "Lead quer receber áudio",
    "sinal:quer_videochamada": "Lead pediu videochamada",
    "sinal:cliente_antigo": "Cliente antigo",
    "sinal:outro_beneficio": "Lead quer outro benefício",
    "sinal:dificuldade_assinatura": "Dificuldade na assinatura",
    "sinal:foto_contrato": "Lead mandou foto do contrato",
    "sinal:muitas_objecoes": "Lead com muitas objeções",
    "sinal:endereco_sem_falar": "Lead não quer passar o endereço",
    "sinal:contrato_manual": "Precisa de contrato manual",
    "sinal:analise_humana": "Pediu análise humana",
    "sinal:atendimento_presencial": "Lead quer atendimento presencial",
    "sinal:ligacao_telefonica": "Lead pediu ligação",
    "sinal:parceria_comercial": "Contato comercial (não é lead)",
    "sinal:deficiencia_auditiva": "Lead com deficiência auditiva",
    # Etapas do catálogo (papéis do n8n): closer -> lead_qualificado, contratos -> lead_iniciou_coleta,
    # assinatura -> aguardando_assinatura, contrato_assinado -> contrato_assinado.
    "etapa:contratos": "Lead começou a passar os dados",
    "etapa:contrato_assinado": "Contrato assinado",
    "etapa:periododegraca": "Lead no período de graça",
    "contrato_gerado": "Contrato gerado",
    "contrato_assinado": "Contrato assinado",
    "contrato_falhou": "Contrato não foi gerado",
    "followup_desistiu": "Lead não respondeu aos follow-ups",
    "lead_parado": "Lead parado: retomar contato",
    "lead_quente": "Lead quente",
    "trava": "IA barrada pela trava",
    "ia_falhou": "IA não conseguiu responder",
    "consumo_limite": "Consumo da IA perto do limite",
}

MARCADORES = ("nome", "telefone", "produto", "etapa", "data_hora", "valor", "link_assinatura",
              "origem", "evento", "link_conversa", "mensagem_lead", "beneficio", "nota", "motivos")

MODELO_PADRAO = """🔔 *{{evento}}*
Lead: {{nome}}
Telefone: {{telefone}}
Etapa: {{etapa}}
Mensagem do lead: {{mensagem_lead}}
Contrato: {{link_assinatura}}
Valor: {{valor}}
Conversa: {{link_conversa}}
{{data_hora}}"""

# Lead quente (nota do lead, app/cerebro/temperatura.py): nome, benefício, nota e motivos. Nunca CPF nem a mensagem do lead.
MODELO_LEAD_QUENTE = """🔥 *{{evento}}*
Lead: {{nome}}
Benefício: {{beneficio}}
Nota: {{nota}}
Motivos: {{motivos}}
Telefone: {{telefone}}
Etapa: {{etapa}}
Conversa: {{link_conversa}}
{{data_hora}}"""

LIMITE_MENSAGEM_LEAD = 500          # o aviso é um resumo: mensagem longa do lead vai cortada

# Contra spam: o mesmo aviso (tipo de evento) para o mesmo lead sai no máximo 1 vez nesta janela. O escritório pode
# mudar em config "avisos_janela_h" (0 = sem janela). O lead_quente já é 1 vez por lead (app/cerebro/temperatura.py).
JANELA_AVISO_H = 12
# Eventos que são o mesmo fato com dois nomes: contam juntos na janela.
MESMO_FATO: dict[str, str] = {"etapa:contrato_assinado": "contrato_assinado"}

# O aviso sai pelo número de WhatsApp da própria conta, e esse número não pode ser da API oficial (conversa nova com
# número da equipe só abre com modelo aprovado pela Meta). Config do escritório "avisos_numero_envio" escolhe o número.
CONFIG_NUMERO_ENVIO = "avisos_numero_envio"
TEXTO_NUMERO_OFICIAL = ("Aviso à equipe não enviado: o número de envio é oficial (API oficial do WhatsApp). "
                        "Escolha um número não oficial em Avisos no WhatsApp.")
NOTA_NUMERO_OFICIAL = "⚠️ " + TEXTO_NUMERO_OFICIAL


def janela_do_aviso_h(config_escritorio: Mapping[str, Any] | None) -> float:
    bruto = (config_escritorio or {}).get("avisos_janela_h")
    try:
        return max(0.0, float(bruto)) if bruto is not None and str(bruto).strip() != "" else float(JANELA_AVISO_H)
    except (TypeError, ValueError):
        return float(JANELA_AVISO_H)


def eventos_do_mesmo_fato(evento: str) -> list[str]:
    """O evento e os outros nomes do mesmo fato (contrato assinado chega como 'contrato_assinado' e como etapa)."""
    base = MESMO_FATO.get(evento, evento)
    return sorted({base, *[k for k, v in MESMO_FATO.items() if v == base]})


def canal_envia_aviso(tipo: str | None, tipo_helena: str | None) -> bool:
    """O canal pode mandar o aviso? Só WhatsApp não oficial. Oficial = agentesia_canais.tipo 'oficial' (a sincronização
    grava assim quando o tipo da Helena começa com 'CloudAPI') ou tipo_helena CloudAPI/WABA; Instagram etc. também não."""
    helena = str(tipo_helena or "").lower()
    if str(tipo or "") == "oficial" or helena.startswith("cloudapi") or "waba" in helena:
        return False
    return not helena or "whatsapp" in helena

_MARCADOR = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")


def fuso(nome: str = "America/Sao_Paulo") -> tzinfo:
    """Fuso do escritório. Sem base de fusos no sistema (Windows sem tzdata), usa UTC-3 (Brasília, sem horário de verão)."""
    try:
        return ZoneInfo(nome)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone(timedelta(hours=-3), "BRT")


@dataclass(frozen=True)
class Destinatario:
    rotulo: str
    numero: str                      # só dígitos, com 55


def normalizar_numero(valor: Any) -> str | None:
    digitos = re.sub(r"\D", "", str(valor or ""))
    if not digitos:
        return None
    return "55" + digitos if len(digitos) <= 11 else digitos


def formatar_telefone(valor: Any) -> str:
    digitos = re.sub(r"\D", "", str(valor or ""))
    if digitos.startswith("55") and len(digitos) in (12, 13):
        digitos = digitos[2:]
    if len(digitos) == 11:
        return f"({digitos[:2]}) {digitos[2:7]}-{digitos[7:]}"
    if len(digitos) == 10:
        return f"({digitos[:2]}) {digitos[2:6]}-{digitos[6:]}"
    return str(valor or "")


def renderizar_modelo(modelo: str, valores: Mapping[str, Any]) -> str:
    """Linha com marcador vazio some inteira; o resto troca {{ chave }} pelo valor."""
    linhas = []
    for linha in (modelo or "").replace("\r\n", "\n").split("\n"):
        chaves = _MARCADOR.findall(linha)
        if chaves and any(not str(valores.get(c) or "").strip() for c in chaves):
            continue
        linhas.append(_MARCADOR.sub(lambda m: str(valores.get(m.group(1)) or "").strip(), linha))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(linhas)).strip()


def filtrar_destinatarios(itens: list[Any], numero_canal: str | None) -> list[Destinatario]:
    """Tira o próprio número do agente, repetidos e números inválidos."""
    canal = normalizar_numero(numero_canal)
    vistos: set[str] = set()
    saida: list[Destinatario] = []
    for item in itens or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") not in (None, "phone"):
            continue
        rotulo = str(item.get("rotulo") or item.get("label") or "").strip()
        if rotulo.lower().startswith("canal:"):
            continue
        numero = normalizar_numero(item.get("numero") or item.get("value"))
        if not numero or len(numero) < 12 or numero == canal or numero in vistos:
            continue
        vistos.add(numero)
        saida.append(Destinatario(rotulo or formatar_telefone(numero), numero))
    return saida


def nome_do_evento(evento: str, gatilhos: Mapping[str, str] | None = None, sinais: list[str] | None = None) -> str:
    """Nome do evento no cabeçalho do aviso: o mesmo rótulo da tela de avisos, nunca o código cru.

    Ordem: NOMES_DE_EVENTO, os gatilhos do produto do agente (`gatilhos`), os gatilhos do agente pronto e, por fim,
    um nome montado pelo tipo (etapa:, sinal:, intencao:). No gatilho genérico "sinal", cita quais sinais foram.
    """
    from app import automacoes

    if evento == "sinal":
        nomes = [automacoes.NOMES_SINAIS.get(s, s.replace("_", " ")) for s in sinais or []]
        return "Sinal confirmado" + (": lead " + ", ".join(nomes) if nomes else "")
    if evento in NOMES_DE_EVENTO:
        return NOMES_DE_EVENTO[evento]
    rotulo = (gatilhos or {}).get(evento) or automacoes.GATILHOS.get(evento)
    if rotulo:
        return rotulo
    tipo, _, codigo = evento.partition(":")
    if tipo == "etapa" and codigo:
        return f"Lead entra na etapa {codigo.replace('_', ' ')}"
    if tipo == "sinal" and codigo:
        return f"Lead {automacoes.NOMES_SINAIS.get(codigo, codigo.replace('_', ' '))}"
    if tipo == "intencao" and codigo:
        return f"Lead demonstra a intenção {codigo.replace('_', ' ')}"
    return evento.replace("_", " ")


def valores_do_aviso(*, evento: str, nome: str | None, telefone: str | None, produto: str | None,
                     etapa: str | None, valor: str | None = None, link_assinatura: str | None = None,
                     origem: str | None = None, link_conversa: str | None = None, mensagem_lead: str | None = None,
                     agora: datetime | None = None, nome_fuso: str = "America/Sao_Paulo",
                     gatilhos: Mapping[str, str] | None = None, sinais: list[str] | None = None) -> dict[str, str]:
    local = fuso(nome_fuso)
    momento = (agora or datetime.now(local)).astimezone(local)
    mensagem = (mensagem_lead or "").strip()
    if len(mensagem) > LIMITE_MENSAGEM_LEAD:
        mensagem = mensagem[:LIMITE_MENSAGEM_LEAD - 1].rstrip() + "…"
    return {
        "evento": nome_do_evento(evento, gatilhos, sinais),
        "nome": (nome or "").strip() or "sem nome",
        "telefone": formatar_telefone(telefone),
        "produto": produto or "",
        "etapa": etapa or "",
        "data_hora": momento.strftime("%d/%m/%Y, %H:%M"),
        "valor": valor or "",
        "link_assinatura": link_assinatura or "",
        "origem": origem or "",
        "link_conversa": link_conversa or "",
        "mensagem_lead": mensagem,
    }


def texto_lead_quente(modelo: str | None, valores: Mapping[str, Any], *, nota: int, faixa: str, motivos: str,
                      beneficio: str) -> str:
    """Aviso de lead quente. Usa o modelo do escritório; se ele não cita a nota ou os motivos (o modelo padrão não cita),
    eles entram no fim. Nunca leva CPF nem a mensagem do lead (que pode ter o CPF)."""
    from app.cerebro.temperatura import sem_cpf

    completos = {**valores, "mensagem_lead": "", "beneficio": beneficio, "nota": f"{nota}/10 ({faixa})", "motivos": motivos}
    base = (modelo or "").strip() or MODELO_LEAD_QUENTE
    texto = renderizar_modelo(base, completos)
    marcadores = set(_MARCADOR.findall(base))
    extras = [f"{rotulo}: {completos[chave]}" for chave, rotulo in (("beneficio", "Benefício"), ("nota", "Nota"), ("motivos", "Motivos"))
              if chave not in marcadores and str(completos[chave] or "").strip()]
    return sem_cpf("\n".join([texto, *extras]).strip())
