"""Os dois agentes do follow-up (sem banco): quem DECIDE e quem ESCREVE.

1. Agente de follow-up (papel "followup_decisor"): lê a conversa com o prompt de follow-up do agente (config.prompt) e o
   da etapa (config.por_etapa, vindo do produto da biblioteca) e escolhe UMA das funções de follow-up:
     enviar_followup   retomar agora; diz em "orientacao" por onde retomar (o ponto em que a conversa parou);
     adiar_followup    o lead pediu para ser chamado depois ("to no trabalho", "amanhã", "semana que vem"): em "horas";
     nao_enviar        não faz sentido cobrar resposta agora (a pessoa disse que vai mandar algo, a conversa já foi
                       encerrada, ela está esperando a equipe). O ciclo para; volta na próxima resposta da IA.
   É o antigo "Lead pediu para esperar?" do GERAL - Follow Up Unificado, agora junto da decisão de enviar.
2. Agente do lead (papel "followup"): o agente da etapa atual, com a voz dele (o roteiro da etapa, as regras do
   escritório), escreve a mensagem seguindo a orientação e as regras da retomada. Quem manda é ele.

Sem IA (saldo/limite estourado) nenhum dos dois roda: sai o texto de reserva (servico.TEXTO_RESERVA).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.followup import regras

ADIAR_MIN_H = 1
ADIAR_MAX_H = 720                     # 30 dias, como no n8n
MAX_MENSAGENS = 3
VOZ_MAX = 9000                        # caracteres do roteiro da etapa que entram no sistema do agente do lead

FUNCOES = ("enviar_followup", "adiar_followup", "nao_enviar")

ESQUEMA_DECISAO = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "funcao": {"type": "string", "enum": list(FUNCOES)},
        "horas": {"type": ["number", "null"]},
        "motivo": {"type": "string"},
        "orientacao": {"type": "string"},
    },
    "required": ["funcao", "horas", "motivo", "orientacao"],
}

ESQUEMA_MENSAGENS = {"type": "object", "additionalProperties": False,
                     "properties": {"mensagens": {"type": "array", "items": {"type": "string"}}}, "required": ["mensagens"]}

GUIA_DAS_FUNCOES = """# FUNÇÕES DE FOLLOW-UP (escolha uma em "funcao")
- enviar_followup: a pessoa parou de responder e vale retomar agora. Em "orientacao", diga em 1 a 3 frases por onde
  retomar: o ponto exato em que a conversa parou, o que já foi respondido (não repetir) e o tom desta tentativa. Não
  escreva a mensagem: quem escreve é o agente da conversa.
- adiar_followup: na ÚLTIMA fala da pessoa ela pediu para ser chamada depois ou disse que não pode agora ("estou no
  trabalho", "dirigindo", "amanhã", "semana que vem", "estou viajando", "mais tarde"). Em "horas", quanto esperar
  (número inteiro, de 1 a 720). Referências: "peraí"/"dirigindo" 1; "ocupado"/"no médico" 2; "mais tarde"/"depois" 3;
  "no trabalho" 4; "amanhã" 24 (ou até as 9h de amanhã se disse "amanhã cedo"); "depois de amanhã" 48; dia da
  semana: os dias até lá × 24; "viajando" 72; "semana que vem" 168; "de férias" 168; "mês que vem" 720.
- nao_enviar: cobrar resposta agora seria inconveniente ou não faz sentido: a pessoa disse que vai mandar algo ou
  procurar o escritório quando puder, a conversa já foi encerrada com despedida, ela está esperando um retorno da
  equipe, ou recusou seguir. Diga o porquê em "motivo".
Na dúvida entre enviar e não enviar, envie. "ok", "sim", "não" soltos não são pedido para esperar.
"motivo": uma frase curta para a equipe (sem dados pessoais). "horas": só no adiar_followup; nas outras, null."""

REGRAS_DA_MENSAGEM = """# ESTA MENSAGEM É UMA RETOMADA (follow-up)
A pessoa parou de responder. Você vai mandar uma mensagem curta para retomar a conversa, com a sua voz de sempre.
- Retome pelo ponto em que a conversa parou (veja a orientação abaixo). Não repita a sua última mensagem nem pergunta
  já respondida.
- Uma pergunta simples no fim, fácil de responder. Nada de pressão, urgência, culpa ou cobrança ("você sumiu").
- Não avance de etapa, não transfira, não peça documento, não mande link, áudio ou vídeo. Não prometa resultado,
  prazo ou valor. Não diga que é mensagem automática nem que vai chamar de novo depois.
- Devolva de 1 a 3 mensagens curtas em "mensagens" (texto puro de WhatsApp)."""


@dataclass
class Decisao:
    funcao: str = "enviar_followup"
    horas: float | None = None
    motivo: str = ""
    orientacao: str = ""
    decidiu: bool = False            # False = o agente de follow-up não respondeu (segue enviando, como antes)

    @property
    def enviar(self) -> bool:
        return self.funcao == "enviar_followup"


def ler_decisao(dados: Any) -> Decisao:
    """Saída do agente de follow-up -> Decisao. Qualquer coisa estranha vira "enviar" (o comportamento de antes)."""
    if not isinstance(dados, dict):
        return Decisao()
    funcao = str(dados.get("funcao") or "").strip()
    if funcao not in FUNCOES:
        return Decisao()
    motivo = re.sub(r"\s+", " ", str(dados.get("motivo") or "")).strip()[:300]
    orientacao = str(dados.get("orientacao") or "").strip()[:1200]
    horas: float | None = None
    if funcao == "adiar_followup":
        try:
            horas = float(dados.get("horas"))
        except (TypeError, ValueError):
            horas = 24.0                 # pediu para esperar sem dizer quanto: 1 dia (o padrão do n8n)
        horas = max(ADIAR_MIN_H, min(ADIAR_MAX_H, round(horas)))
    return Decisao(funcao, horas, motivo, orientacao, decidiu=True)


# ------------------------------------------------------------------ variáveis e voz da etapa
def valores(lead: dict[str, Any]) -> dict[str, str]:
    from app.cerebro import catalogo
    config = lead.get("config_agente") or {}
    return catalogo.valores_das_variaveis(lead.get("nome_agente"), lead.get("escritorio"),
                                          config.get("honorarios") or (lead.get("config_escritorio") or {}).get("honorarios"),
                                          config)


def preencher(texto: str | None, vals: dict[str, str]) -> str:
    """{{ Nome do Escritório }} e companhia trocados; linha com variável sem valor sai (o modelo nunca vê "{{")."""
    from app.cerebro import catalogo
    return catalogo.preencher_variaveis(catalogo.sem_marcadores_de_midia(texto or ""), vals)[0].strip()


_LINHA_DE_FERRAMENTA = re.compile(r"(@\s*(agente|transfer|an[aá]lise|zapsign|buscar\s*cep)|acionar\s+(a\s+)?tool)", re.I)


def voz_da_etapa(lead: dict[str, Any]) -> str:
    """O roteiro do agente da etapa atual (catálogo: o prompt do papel; produto próprio: a instrução da etapa ou a
    padrão), sem as linhas de transferência e de ferramenta: na retomada o agente só conversa."""
    from app.cerebro import agente as agente_base, produto as produtos
    texto = lead.get("instrucao_etapa") or ""
    if not texto.strip() and lead.get("produto") != "catalogo":
        try:
            texto = agente_base.instrucao_padrao(lead.get("etapa") or "", produtos.carregar(lead.get("produto"), lead.get("config_agente")))
        except Exception:
            texto = ""
    linhas = [l for l in preencher(texto, valores(lead)).split("\n") if not _LINHA_DE_FERRAMENTA.search(l)]
    return "\n".join(linhas).strip()[:VOZ_MAX]


def _regras_do_escritorio(lead: dict[str, Any]) -> str:
    regras_txt = ((lead.get("config_agente") or {}).get("catalogo") or {}).get("regras")
    return preencher(regras_txt, valores(lead))[:3000] if regras_txt else ""


def _prompts_do_followup(lead: dict[str, Any], config: regras.Config) -> tuple[str, str]:
    vals = valores(lead)
    return preencher(config.prompt, vals), preencher(config.por_etapa.get(lead.get("etapa") or ""), vals)


def instrucao_do_passo(config: regras.Config, passo: int, total: int) -> str:
    instrucao = config.passos[passo].instrucao if passo < len(config.passos) else ""
    instrucao = instrucao or regras.INSTRUCAO_PASSO_PADRAO.get(passo, "Retomada breve e gentil.")
    if passo == total - 1:
        instrucao += " Esta é a última tentativa: diga que fica à disposição quando a pessoa puder."
    return f"Tentativa {passo + 1} de {total}. {instrucao}"


# ------------------------------------------------------------------ sistemas
def sistema_do_decisor(lead: dict[str, Any], config: regras.Config, passo: int, total: int, agora_txt: str) -> str:
    geral, da_etapa = _prompts_do_followup(lead, config)
    etapa = lead.get("etapa") or "conversa"
    return "\n\n".join(filter(None, [
        f"Você é o agente de follow-up do escritório {lead.get('escritorio') or ''}. A pessoa parou de responder na etapa "
        f"\"{etapa}\". Você decide o que fazer agora; quem escreve a mensagem é o agente da conversa "
        f"({lead.get('nome_agente') or 'a atendente'}).",
        f"Agora: {agora_txt}. {instrucao_do_passo(config, passo, total)}",
        "# PROMPT DE FOLLOW-UP\n" + geral if geral else "",
        "# FOLLOW-UP DESTA ETAPA\n" + da_etapa if da_etapa else "",
        GUIA_DAS_FUNCOES,
    ]))


def sistema_do_agente_do_lead(lead: dict[str, Any], config: regras.Config, passo: int, total: int,
                              orientacao: str = "") -> str:
    """O agente da etapa atual escreve a retomada com a voz dele. As regras do follow-up (OAB/Meta) vêm depois."""
    geral, da_etapa = _prompts_do_followup(lead, config)
    voz = voz_da_etapa(lead)
    regras_esc = _regras_do_escritorio(lead)
    return "\n\n".join(filter(None, [
        f"Você é {lead.get('nome_agente') or 'a atendente'}, do escritório {lead.get('escritorio') or ''}, a mesma "
        f"pessoa que está conduzindo esta conversa pelo WhatsApp.",
        "# SEU ROTEIRO NESTA ETAPA (é assim que você conversa; agora você só vai retomar)\n" + voz if voz else "",
        "# REGRAS GERAIS DO ESCRITÓRIO\n" + regras_esc if regras_esc else "",
        REGRAS_DA_MENSAGEM,
        "# COMO RETOMAR (do agente de follow-up)\n" + geral if geral else "",
        "# NESTA ETAPA\n" + da_etapa if da_etapa else "",
        instrucao_do_passo(config, passo, total),
        "Orientação para esta retomada: " + orientacao if orientacao else "",
    ]))


def conversa_em_texto(historico: list[dict[str, Any]]) -> str:
    """Mais antiga primeiro. 'você' é a IA; 'equipe' é alguém do escritório (nome entre asteriscos é da equipe)."""
    rotulo = {"lead": "lead", "ia": "você"}
    return "\n".join(f"{rotulo.get(m['autor'], 'equipe')}: {re.sub(r'\s*\n\s*', ' ', str(m['texto']).strip())}"
                     for m in historico if str(m.get("texto") or "").strip())


# ------------------------------------------------------------------ saída do agente do lead
_PROIBIDO = re.compile(r"https?://|www\.|R\$\s*\d|\{\{|\[\[", re.I)


def limpar_mensagens(brutas: Any) -> list[str]:
    """No máximo 3 mensagens, negrito do Markdown vira o do WhatsApp, sem aspas soltas. Lista vazia = usar a reserva
    (inclusive se alguma tem link, valor em R$ ou marcador do sistema)."""
    textos: list[str] = []
    for t in brutas if isinstance(brutas, list) else []:
        texto = re.sub(r"\*\*(.+?)\*\*", r"*\1*", str(t or "")).replace("\\n", "\n").strip().strip('"').strip()
        texto = re.sub(r"[ \t]{2,}", " ", texto)
        if texto:
            textos.append(texto)
    if len(textos) > MAX_MENSAGENS:
        textos = [*textos[:MAX_MENSAGENS - 1], "\n\n".join(textos[MAX_MENSAGENS - 1:])]
    if any(_PROIBIDO.search(t) for t in textos):
        return []
    return textos
