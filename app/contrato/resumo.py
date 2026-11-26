"""Resumo da conversa quando o contrato é assinado (o "R1-R10" do fluxo WEAVER - Contrato). Puro.

Configuração, da mais forte para a mais fraca (como a contrato_resumo_config do n8n: a linha do agente vale mais que a
do cliente):
  1. agente: agentesia_agentes.config.resumo_contrato = {ativo, prompt, modelo, no_aviso}
  2. escritório: agentesia_integracoes(zapsign).config.resumo = {ativo, prompt, modelo, no_aviso}
  3. padrão de fábrica (PROMPT_PADRAO, gpt-4.1-mini, ligado)
Prompt vazio herda o de baixo. `no_aviso` põe o resumo no aviso "contrato assinado" à equipe (WhatsApp).
"""

from __future__ import annotations

from typing import Any

MODELO_PADRAO = "gpt-4.1-mini"
LIMITE_CARACTERES = 6000
TITULO_NOTA = "📄 RESUMO DO CONTRATO ASSINADO"

PROMPT_PADRAO = """Você recebe a conversa de WhatsApp entre a atendente (IA) e um cliente que acabou de ASSINAR o contrato
com o escritório de advocacia previdenciária. Escreva um resumo para o advogado que vai assumir o caso, em português.

REGRAS
- Use só o que está na conversa. Nunca invente, deduza ou complete datas, valores, diagnósticos ou vínculos.
- O que a conversa não trouxer: escreva "não informado".
- Não copie CPF, RG, endereço completo nem dados de cartão. Nome e cidade podem.
- Frases curtas, sem floreio.

Responda neste formato:

📄 Resumo do caso:
[o que aconteceu e quando, em até 4 linhas]

👤 Cliente:
[nome, idade se dita, cidade/UF, profissão]

🏛️ Benefício:
[benefício buscado (ex.: auxílio-acidente, BPC, aposentadoria) e se já pediu ao INSS / se teve negativa]

🩺 Acidente ou doença:
[o que foi, data, se foi no trabalho ou fora, afastamento e se recebeu auxílio-doença]

🦴 Sequela:
[a limitação que ficou, como afeta o trabalho]

💼 Vínculo:
[carteira assinada, autônomo/contribuinte, desempregado; última empresa e quando saiu]

📅 Datas importantes:
[acidente, afastamento, alta do INSS, demissão, negativa]

📎 Documentos:
[o que o cliente disse que tem e o que FALTA (laudos, CAT, CNIS, carta de indeferimento...)]

⚠️ Pontos de atenção para o advogado:
[dúvidas, contradições, riscos (prazo, qualidade de segurado), pedidos do cliente]

📊 Qualidade do contrato:
[Alta | Média | Baixa] — [justificativa curta]"""


def _bloco(config: Any) -> dict[str, Any]:
    return config if isinstance(config, dict) else {}


def configuracao(config_agente: dict[str, Any] | None, config_zapsign: dict[str, Any] | None) -> dict[str, Any]:
    """{ativo, prompt, modelo, no_aviso, origem}: origem = agente | escritorio | padrao (de onde veio o prompt)."""
    agente = _bloco((config_agente or {}).get("resumo_contrato"))
    escritorio = _bloco((config_zapsign or {}).get("resumo"))
    ativo = agente.get("ativo") if agente.get("ativo") is not None else escritorio.get("ativo", True)
    prompt, origem = PROMPT_PADRAO, "padrao"
    if str(escritorio.get("prompt") or "").strip():
        prompt, origem = str(escritorio["prompt"]).strip(), "escritorio"
    if str(agente.get("prompt") or "").strip():
        prompt, origem = str(agente["prompt"]).strip(), "agente"
    no_aviso = agente.get("no_aviso") if agente.get("no_aviso") is not None else escritorio.get("no_aviso", False)
    return {"ativo": bool(ativo), "prompt": prompt, "modelo": str(agente.get("modelo") or escritorio.get("modelo") or MODELO_PADRAO),
            "no_aviso": bool(no_aviso), "origem": origem}


def conversa_para_resumo(mensagens: list[dict[str, Any]]) -> str:
    """Mensagens (mais antiga primeiro) em 'Cliente:'/'Atendente:'; longa demais fica com o final (onde estão os dados)."""
    linhas = [f"{'Cliente' if m.get('autor') == 'lead' else 'Atendente'}: {' '.join(str(m.get('texto') or '').split())}"
              for m in mensagens if str(m.get("texto") or "").strip()]
    return "\n".join(linhas)[-60000:]


def nota(resumo: str) -> str:
    return f"{TITULO_NOTA}\n\n{resumo}"


def descricao_do_card(descricao_base: str | None, resumo: str) -> str:
    """Descrição do card no CRM: a de sempre (origem do lead) + o resumo (a Helena corta em 4000)."""
    partes = [p for p in (str(descricao_base or "").strip(), nota(resumo)) if p]
    return "\n\n".join(partes)[:4000]


def com_resumo_no_aviso(texto_aviso: str, resumo: str | None) -> str:
    """O aviso à equipe com o resumo no fim (quando o modelo do aviso não usa {resumo} sozinho)."""
    if not resumo:
        return texto_aviso
    return f"{texto_aviso.rstrip()}\n\n{nota(resumo)}"[:4000]
