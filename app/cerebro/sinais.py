"""Sinais de alerta para a equipe no produto do catálogo (antiga tool "Sistema Notificação" do n8n).

O mecanismo é o mesmo do Auxílio-Acidente: o extrator marca o sinal pelas palavras do lead, o auditor confere,
o turno tira a IA da conversa e o gatilho "sinal:x" vira aviso à equipe (automações e "Avisos à equipe").
A exceção é "analise_humana": depende das regras do roteiro do papel, que só o agente lê; por isso é o agente
quem marca, no campo "notificacao" da saída.

Correspondência com os valores do n8n: videochamada = quer_videochamada, leadquerreceberaudio = quer_audio,
naosabeler = nao_sabe_ler, clienteantigo = cliente_antigo, outrobeneficio = outro_beneficio,
dificuldadenaassinatura = dificuldade_assinatura, muitasobjeções = muitas_objecoes, analisehumana = analise_humana.
"""

from __future__ import annotations

import re
from typing import Any

# Marcados pelo extrator (gatilho literal nas palavras do lead).
DO_EXTRATOR = ("quer_videochamada", "quer_audio", "nao_sabe_ler", "cliente_antigo", "outro_beneficio",
               "dificuldade_assinatura", "muitas_objecoes")
# Marcados pelo agente do papel (dependem do roteiro).
DO_AGENTE = ("analise_humana",)
SINAIS = DO_EXTRATOR + DO_AGENTE
# Havendo mais de um, a videochamada vem primeiro (prioridade máxima no n8n); o resto segue a ordem em que veio.
PRIORIDADE = ("quer_videochamada",)


def ordenar(sinais: list[str]) -> list[str]:
    """Videochamada na frente (é dela a mensagem ao lead); os outros na ordem em que apareceram, sem repetir."""
    unicos = list(dict.fromkeys(sinais))
    return [s for s in PRIORIDADE if s in unicos] + [s for s in unicos if s not in PRIORIDADE]


def guia_do_extrator(beneficio: str | None = None) -> str:
    """Regras de cada sinal para o extrator, com os 'NÃO é' do prompt do n8n. Na dúvida, não marque."""
    conversa = f" ({beneficio})" if beneficio else ""
    return "\n".join([
        "Sinais (marque só com gatilho literal e explícito nas palavras do lead; na dúvida, não marque):",
        "- quer_videochamada: pede chamada de vídeo (vídeo, Zoom, Meet, \"te ver por chamada\"). NÃO é: \"deixa eu ver\", "
        "\"ver com a esposa\", \"quero conversar\", pedido de áudio.",
        "- quer_audio: pede áudio ou voz (\"manda um áudio\", \"prefiro voz\", \"explica em áudio\"). NÃO é: \"ouvi falar\", "
        "\"quero ouvir como funciona\", só ter mandado áudios.",
        "- nao_sabe_ler: diz que não sabe ler ou lê com dificuldade. NÃO é: \"não li ainda\", \"não entendi\".",
        "- cliente_antigo: afirma vínculo com ESTE escritório (\"já sou cliente de vocês\", \"vocês já cuidam do meu processo\"). "
        "NÃO é: \"tenho advogado\", \"meu advogado disse\", processo em OUTRO lugar.",
        f"- outro_beneficio: pede um benefício diferente do que está em conversa{conversa}. NÃO é: menção genérica a INSS "
        "ou benefício, nem contar que recebe ou recebeu outro.",
        "- dificuldade_assinatura: problema no ato de assinar (\"link não abre\", \"não consigo assinar\", \"deu erro na "
        "assinatura\"). NÃO é: dúvida geral sobre o contrato.",
        "- muitas_objecoes: resistência repetida 3 ou mais vezes que trava o avanço (inclui a mesma pergunta repetida 3 ou "
        "mais vezes depois de respondida). NÃO é: uma objeção ou dúvida isolada; reclamar que a atendente repetiu a "
        "pergunta (\"já te falei\", \"já respondi\", \"como eu disse\") NÃO é objeção.",
        "Não marcam nada: endereço ou \"onde fica o escritório\", atendimento presencial, preço, prazo, \"como funciona\", "
        "saudações e confirmações (\"ok\", \"blz\", \"sim\").",
    ])


# Ajustes do auditor para o catálogo (mesmo formato de auditor.PARTES).
PARTES_DO_AUDITOR: dict[str, tuple[str, str, str, str, str, str]] = {
    "muitas_objecoes": (
        "LEAD COM MUITAS OBJEÇÕES", "uma pessoa contorna a resistência",
        "resistência repetida 3 ou mais vezes que trava o avanço (medo de golpe, desconfiança, honorários, 'vou pensar', "
        "família, documentos); OU a mesma pergunta repetida 3 ou mais vezes depois de respondida",
        "uma objeção ou dúvida isolada; perguntas normais de interesse; já aceitou seguir; reclamar que a atendente "
        "repetiu a pergunta ('já te falei', 'já respondi', 'como eu disse') NÃO é objeção",
        'Sem discutir nem pressionar; medo de golpe: segurança sem exagero. Tom: "Entendo suas dúvidas! Vou pedir para um '
        'especialista da nossa equipe falar com você e esclarecer tudo direitinho, pode ser?"',
        "Responda à dúvida e siga."),
}


def partes_do_auditor(beneficio: str | None = None) -> dict[str, tuple[str, str, str, str, str, str]]:
    """Ajustes do auditor para o catálogo, com o benefício do produto no outro_beneficio (o texto do Auxílio-Acidente
    traz um exemplo fixo de auxílio-acidente). Sem benefício conhecido, só vale o que o histórico deixar claro."""
    if beneficio:
        valido = (f"benefício em conversa: {beneficio}. O lead pede um benefício DIFERENTE desse (outro nome de benefício "
                  "do INSS, não o mesmo com outro nome); diz que quer outro")
    else:
        valido = ("o benefício em conversa não veio do sistema: só vale quando o histórico deixa claro qual benefício era "
                  "tratado e o lead pede um DIFERENTE dele; diz que quer outro. Sem isso claro, é inválido")
    return {**PARTES_DO_AUDITOR, "outro_beneficio": (
        "LEAD REQUER CONVERSA DE OUTRO BENEFÍCIO", "chama o especialista desse benefício", valido,
        "é o mesmo benefício em conversa, ou o mesmo com outro nome; dúvida sobre o próprio benefício em conversa "
        "(prazo, valor, documentos); dúvida genérica; só comentou que recebe ou recebeu outro",
        'Pode citar o benefício; não diga se tem direito. Tom: "Entendi! Vou solicitar para a nossa equipe responsável '
        'por esse benefício para entender melhor o seu caso, combinado?"',
        "Retome o benefício que estava em conversa.")}


# ---------------------------------------------------------------------------- link da conversa no aviso
_HOST = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$")
_SESSAO = re.compile(r"^[A-Za-z0-9-]{1,80}$")


def dominio_do_escritorio(config_escritorio: dict[str, Any] | None) -> str | None:
    """Endereço da Helena do escritório (config 'dominio_helena'): 'advmidia', 'advmidia.wts.chat' ou a URL inteira."""
    bruto = str((config_escritorio or {}).get("dominio_helena") or "").strip().lower()
    bruto = re.sub(r"^https?://", "", bruto).split("/", 1)[0].strip(".")
    if not bruto:
        return None
    host = bruto if "." in bruto else f"{bruto}.wts.chat"
    return host if _HOST.match(host) else None


def link_da_conversa(config_escritorio: dict[str, Any] | None, id_sessao: str | None) -> str | None:
    """Link que abre a conversa do lead na Helena do próprio escritório (no n8n era fixo em advmidia.wts.chat).

    Sem domínio cadastrado ou sem sessão, devolve None e o marcador {{link_conversa}} some do aviso."""
    host = dominio_do_escritorio(config_escritorio)
    sessao = str(id_sessao or "").strip()
    if not host or not _SESSAO.match(sessao):
        return None
    return f"https://{host}/redirect?type=SESSION&id={sessao}"
