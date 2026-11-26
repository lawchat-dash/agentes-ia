"""Resumo da conversa quando o contrato é assinado (o "R1-R11" do fluxo CONTRATO ASSINADO do n8n). Puro.

Configuração, da mais forte para a mais fraca (como a contrato_resumo_config do n8n: a linha do agente vale mais que a
do cliente):
  1. agente: agentesia_agentes.config.contrato.resumo = {ligado, prompt, modelo, no_aviso} (tela Ferramentas >
     Resumo de contrato); o formato antigo config.resumo_contrato = {ativo, ...} ainda vale quando o novo não existe
  2. escritório: agentesia_integracoes(zapsign).config.resumo = {ativo, prompt, modelo, no_aviso}
  3. padrão de fábrica: o prompt do produto ("RESUMO PÓS-CONTRATO" do Auxílio-Acidente, ou o geral), gpt-4.1-mini, ligado
Prompt vazio herda o de baixo. `no_aviso` (padrão ligado, como no n8n) põe o resumo no aviso "contrato assinado" à
equipe (WhatsApp): o aviso espera o resumo (ou a falha dele).
"""

from __future__ import annotations

from typing import Any

MODELO_PADRAO = "gpt-4.1-mini"
LIMITE_CARACTERES = 6000
TITULO_NOTA = "📄 Contrato Assinado!"
FIM_NOTA = "Acompanhar lead pois gerou contrato!!"
PAPEL_IA = "contrato_resumo"                 # papel em agentesia_chamadas_ia (consumo e créditos)

# O prompt do fluxo "CONTRATO ASSINADO" do n8n (Auxílio-Acidente).
PROMPT_AUXILIO_ACIDENTE = """## AGENTE: RESUMO PÓS-CONTRATO | Avaliação de Qualidade
Receber o histórico do caso do cliente (contrato fechado e assinado) e retornar:
1. Resumo do caso em poucas palavras: como foi o acidente; ano do acidente; se recebeu auxílio-doença e por quanto tempo; se ficou com limitação e como ela é.
2. Qualidade do contrato: Alta (grande chance de êxito/alto retroativo), Média (boas chances, pontos a confirmar) ou Baixa (chances menores ou valor reduzido), com breve justificativa.
3. Potencial retorno: breve estimativa textual do possível resultado para o escritório.
Formato:
📄 Resumo do caso:
Acidente: [descrição breve] | Ano: [ ] | Auxílio-doença: [Sim/Não, duração] | Limitação: [descrição]

📊 Qualidade do contrato:
[Alta | Média | Baixa] — [breve justificativa]

💰 Potencial retorno:
[breve descrição]
Exemplo — entrada: 'O cliente sofreu acidente de moto em 2017, fraturou a perna, colocou tala e dois parafusos. Recebeu auxílio-doença por 5 meses. Ainda manca e sente dor. Hoje trabalha de carteira assinada como pedreiro.' Saída: 'Acidente: Moto, fratura na perna | Ano: 2017 | Auxílio-doença: Sim, 5 meses | Limitação: Manca e sente dor' / 'Alta — Sequela permanente, auxílio-doença comprovado e vínculo CLT atual.' / 'Alto potencial de êxito e valor retroativo significativo (até 5 anos).'"""

# Os outros benefícios (BPC, aposentadoria...): o resumo geral para o advogado.
PROMPT_GERAL = """Você recebe a conversa de WhatsApp entre a atendente (IA) e um cliente que acabou de ASSINAR o contrato
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

PROMPT_PADRAO = PROMPT_AUXILIO_ACIDENTE

# Aviso "contrato assinado" à equipe quando o escritório não escreveu um modelo próprio (o alerta do n8n).
MODELO_AVISO_ASSINADO = """*📄 Contrato Assinado!*

👤 Cliente: {{nome}}
📞 Telefone de contato: {{telefone}}
🔗 Link do Chat: {{link_conversa}}
📂 Caso: {{caso}}

{{resumo}}

*🚀 Vamos pra cima! 💙*"""


def _bloco(config: Any) -> dict[str, Any]:
    return config if isinstance(config, dict) else {}


def prompt_padrao(caso: str | None = None) -> str:
    """O prompt de fábrica do produto: o do Auxílio-Acidente (o do n8n) ou, para os outros benefícios, o geral."""
    nome = str(caso or "").lower()
    return PROMPT_AUXILIO_ACIDENTE if not nome or "acidente" in nome else PROMPT_GERAL


def bloco_do_agente(config_agente: dict[str, Any] | None) -> dict[str, Any]:
    """A configuração do resumo salva no agente, no formato novo {ligado, prompt, modelo, no_aviso}."""
    config_agente = config_agente or {}
    novo = _bloco(_bloco(config_agente.get("contrato")).get("resumo"))
    if novo:
        return novo
    antigo = _bloco(config_agente.get("resumo_contrato"))
    convertido = {k: v for k, v in antigo.items() if k != "ativo"}
    if "ativo" in antigo:
        convertido["ligado"] = antigo["ativo"]
    return convertido


# Nomes que não dizem o benefício: o agente do catálogo carrega como "Produto do catálogo" (app/cerebro/catalogo.py) e
# grava produto = 'catalogo'. Antes o aviso e a nota saíam com "📂 Caso: Produto do catálogo" e "Produto: catalogo".
_NOMES_GENERICOS = {"catalogo", "catálogo", "produto do catálogo", "produto do catalogo", "proprio", "próprio"}


def _nome_do_slug(slug: Any) -> str:
    texto = " ".join(str(slug or "").replace("-", " ").replace("_", " ").split())
    return texto[:1].upper() + texto[1:]


def nome_do_caso(produto: str | None, config_agente: dict[str, Any] | None, nome_biblioteca: str | None = None) -> str:
    """O benefício do agente (📂 Caso: ...), para a nota e o aviso.

    Agente do catálogo: o nome do produto da biblioteca (nome_biblioteca, ver nome_da_biblioteca), senão o nome ou o
    slug guardados no config.catalogo. Nunca o nome genérico."""
    nome = ""
    try:
        from app.cerebro import produto as produtos
        nome = str(produtos.carregar(produto, config_agente or {}).nome or "").strip()
    except Exception:                                    # produto sem definição válida
        nome = ""
    if not nome or nome.lower() in _NOMES_GENERICOS:
        bloco = _bloco((config_agente or {}).get("catalogo"))
        nome = (str(nome_biblioteca or "").strip() or str(bloco.get("nome") or "").strip()
                or _nome_do_slug(bloco.get("slug")))
    reserva = "" if str(produto or "").lower() in _NOMES_GENERICOS else _nome_do_slug(produto)
    return nome or reserva or "não informado"


async def nome_da_biblioteca(conexao: Any, config_agente: dict[str, Any] | None) -> str | None:
    """Nome do produto da biblioteca do agente do catálogo (config.catalogo.id_produto_biblioteca). Falha = None."""
    id_produto = _bloco(_bloco(config_agente).get("catalogo")).get("id_produto_biblioteca")
    if not id_produto:
        return None
    try:
        nome = await conexao.fetchval("select nome from agentesia_biblioteca_produtos where id::text = $1", str(id_produto))
    except Exception:                                    # o nome é um enfeite: nunca derruba a nota ou o aviso
        return None
    return str(nome).strip() or None if nome else None


def configuracao(config_agente: dict[str, Any] | None, config_zapsign: dict[str, Any] | None,
                 caso: str | None = None) -> dict[str, Any]:
    """{ativo, prompt, modelo, no_aviso, origem}: origem = agente | escritorio | padrao (de onde veio o prompt)."""
    agente = bloco_do_agente(config_agente)
    escritorio = _bloco((config_zapsign or {}).get("resumo"))
    ativo = agente.get("ligado") if agente.get("ligado") is not None else escritorio.get("ativo", True)
    prompt, origem = prompt_padrao(caso), "padrao"
    if str(escritorio.get("prompt") or "").strip():
        prompt, origem = str(escritorio["prompt"]).strip(), "escritorio"
    if str(agente.get("prompt") or "").strip():
        prompt, origem = str(agente["prompt"]).strip(), "agente"
    no_aviso = agente.get("no_aviso") if agente.get("no_aviso") is not None else escritorio.get("no_aviso", True)
    return {"ativo": bool(ativo), "prompt": prompt, "modelo": str(agente.get("modelo") or escritorio.get("modelo") or MODELO_PADRAO),
            "no_aviso": bool(no_aviso), "origem": origem}


def conversa_para_resumo(mensagens: list[dict[str, Any]]) -> str:
    """Mensagens (mais antiga primeiro) em 'Cliente:'/'Atendente:'; longa demais fica com o final (onde estão os dados)."""
    linhas = [f"{'Cliente' if m.get('autor') == 'lead' else 'Atendente'}: {' '.join(str(m.get('texto') or '').split())}"
              for m in mensagens if str(m.get("texto") or "").strip()]
    return "\n".join(linhas)[-60000:]


def nota(resumo: str | None, caso: str | None = None, avisos: list[str] | None = None) -> str:
    """A nota do contrato assinado no atendimento: '📄 Contrato Assinado!', o caso, o resumo (quando houver), os alertas
    (versão substituída, assinatura confirmada pela verificação...) e o 'Acompanhar lead'."""
    partes = [TITULO_NOTA]
    if caso:
        partes.append(f"📂 Caso: {caso}")
    if str(resumo or "").strip():
        partes.append(str(resumo).strip())
    partes += [a for a in avisos or [] if a]
    partes.append(FIM_NOTA)
    return "\n\n".join(partes)


def descricao_do_card(descricao_base: str | None, resumo: str) -> str:
    """Descrição do card no CRM: a de sempre (origem do lead) + o resumo (a Helena corta em 4000)."""
    partes = [p for p in (str(descricao_base or "").strip(), f"{TITULO_NOTA}\n\n{resumo}") if p]
    return "\n\n".join(partes)[:4000]


def com_resumo_no_aviso(texto_aviso: str, resumo: str | None) -> str:
    """O aviso à equipe com o resumo no fim (quando o modelo do aviso não usa {resumo} sozinho)."""
    if not resumo:
        return texto_aviso
    return f"{texto_aviso.rstrip()}\n\n{resumo.strip()}"[:4000]
