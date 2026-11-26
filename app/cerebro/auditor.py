"""Auditor de sinais: antes de tirar a IA da conversa e chamar a equipe, confere se o sinal faz sentido.

No n8n eram 10 agentes (um por tipo de aviso). Aqui é uma função com um prompt por sinal e saída
estruturada. Se o auditor falhar, o sinal vale (melhor chamar uma pessoa do que ignorar o lead).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.modelo import Chamada, ErroModelo, Modelo

ESQUEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"valido": {"type": "boolean"}, "motivo": {"type": "string"}, "mensagem": {"type": "string"}},
    "required": ["valido", "motivo", "mensagem"],
}

# sinal: (título, efeito, válido quando, inválido quando, se válido, se inválido)
PARTES: dict[str, tuple[str, str, str, str, str, str]] = {
    "dificuldade_assinatura": (
        "DIFICULDADE NA ASSINATURA", "chama a equipe para ajudar o lead a assinar",
        "não consegue assinar; o link não abre, deu erro ou expirou; não sabe como assinar ou pede ajuda; travou na selfie, na foto do documento, no código ou no token",
        "só não assinou ainda; vai assinar depois; já assinou; nem recebeu o link",
        'Diga que vai pedir para a equipe dar suporte na assinatura agora. Tom: "Entendi! Vou pedir para a nossa equipe te dar suporte na assinatura agora mesmo, tudo bem?"',
        "Conduza ao próximo passo da assinatura; se ele já assinou, agradeça e diga que a equipe vai conferir."),
    "foto_contrato": (
        "FOTO DO CONTRATO IDENTIFICADA", "a equipe confere a documentação",
        "enviou foto, print ou arquivo do contrato (ou de uma página); disse claramente que acabou de enviar",
        "não houve imagem nem arquivo; o que mandou não é o contrato (selfie, figurinha, comprovante sem relação); só falou do contrato",
        'Tom: "Recebi a foto do contrato! Vou pedir para a nossa equipe verificar por aqui e já te retorno, combinado?"',
        "Se mandou outra coisa, agradeça e explique o que falta; senão, siga a conversa."),
    "nao_sabe_ler": (
        "CLIENTE QUE NÃO SABE LER", "a equipe passa a atender por áudio",
        "diz que não sabe ler ou é analfabeto; tem muita dificuldade para ler; não enxerga bem; precisa de alguém para ler",
        "só não leu ou vai ler depois; achou o texto grande ou está sem tempo; só mandou áudios",
        'Frases MUITO curtas e palavras simples. Tom: "Sem problema! Vou verificar aqui para te enviar um áudio explicando tudo direitinho, tá bom?"',
        "Siga a conversa; se o texto era grande, ofereça um resumo."),
    "cliente_antigo": (
        "CLIENTE ANTIGO", "encaminha ao setor operacional",
        "já é cliente do escritório; já tem processo ou contrato com ele; já assinou antes; pergunta do andamento de processo existente",
        "só conhece o escritório ou viu anúncio; é cliente de OUTRO escritório; fez pedido direto no INSS; nenhum sinal de vínculo",
        'Sem excesso de desculpas e sem informar andamento. Tom: "Perfeito! Nosso setor operacional vai entrar em contato com você para te ajudar, tudo certo?"',
        "Siga a conversa."),
    "outro_beneficio": (
        "LEAD REQUER CONVERSA DE OUTRO BENEFÍCIO", "chama o especialista desse benefício",
        "pede um benefício DIFERENTE do que está em conversa (ex.: conversa de auxílio-acidente e pergunta de aposentadoria, BPC, pensão, salário-maternidade); diz que quer outro",
        "é o mesmo benefício com outro nome; dúvida genérica; só comentou que recebe ou recebeu outro",
        'Pode citar o benefício; não diga se tem direito. Tom: "Entendi! Vou solicitar para a nossa equipe responsável por esse benefício para entender melhor o seu caso, combinado?"',
        "Retome o benefício que estava em conversa."),
    "quer_videochamada": (
        "LEAD SOLICITOU VÍDEO CHAMADA", "agenda uma videochamada com prioridade",
        'pede chamada de vídeo; quer "ver" alguém ou falar "olhando no rosto"; aceitou claramente uma videochamada oferecida',
        "pediu só áudio; a videochamada foi sugerida e ele não aceitou ou não respondeu; nenhuma menção",
        'Pergunte o melhor dia e horário; se já disse, repita e diga que a equipe confirma, sem garantir. Tom: "Claro, conseguimos fazer a vídeo chamada sim! Qual o melhor dia e horário para você?"',
        "Siga a conversa; não ofereça videochamada."),
    "quer_audio": (
        "O LEAD QUER RECEBER ÁUDIO", "a equipe explica por áudio",
        'pede áudio ("manda um áudio", "explica por áudio"); prefere áudio; não acompanha bem por texto',
        "só ENVIOU áudios; o motivo real é não saber ler (diga no motivo que o certo seria nao_sabe_ler); nenhum pedido",
        'Se citou um ponto, diga que o áudio cobre esse ponto. Tom: "Certo! Vou verificar por aqui para te enviar um áudio explicando melhor o seu caso, tudo bem?"',
        "Responda, inclusive ao conteúdo do áudio transcrito."),
    "muitas_objecoes": (
        "LEAD COM MUITAS OBJEÇÕES", "uma pessoa contorna a resistência",
        "duas ou mais objeções diferentes (medo de golpe, desconfiança, honorários, 'vou pensar', família, 'já tentei', documentos) e segue resistente; OU repetiu a mesma depois de respondido",
        "dúvida pontual já esclarecida; perguntas normais de interesse; já aceitou seguir; reclamar que a atendente repetiu a pergunta ('já te falei', 'já respondi') NÃO é objeção",
        'Sem discutir nem pressionar; medo de golpe: segurança sem exagero. Tom: "Entendo suas dúvidas! Vou pedir para um especialista da nossa equipe falar com você e esclarecer tudo direitinho, pode ser?"',
        "Responda à dúvida e siga."),
    "endereco_sem_falar": (
        "OBJEÇÃO DE ENDEREÇO", "a equipe explica por que o endereço é necessário",
        "recusou passar o endereço; desviou e não informou; questionou o motivo sem fornecer",
        "já informou (mesmo incompleto); ainda não foi pedido; só pediu tempo para buscar",
        "Respeite sem pressionar, diga que os dados servem só para o processo e que alguém da equipe vai explicar.",
        "Siga; se pediu tempo, diga que pode mandar quando puder."),
    "contrato_manual": (
        "NECESSÁRIO FAZER O CONTRATO MANUALMENTE", "a equipe prepara o contrato fora do fluxo automático",
        "pediu contrato físico ou impresso; quem assina é representante legal, curador, procurador ou responsável por menor; não consegue assinatura digital de jeito nenhum; dados fora do padrão (falta CPF, nome divergente)",
        "o fluxo automático ainda é possível; dificuldade pontual no link (isso seria dificuldade_assinatura)",
        "Diga que a equipe vai preparar o contrato do jeito certo para o caso dele e entrar em contato.",
        "Siga com o fluxo normal de assinatura."),
    "atendimento_presencial": (
        "LEAD QUER ATENDIMENTO PRESENCIAL", "a equipe combina a ida do lead ao escritório",
        "quer ir pessoalmente ao escritório; pede para ser atendido presencialmente; quer marcar um horário para ir lá",
        "só perguntou onde fica o escritório ou o endereço; disse que não pode ir; nenhuma menção a ir pessoalmente",
        'Não marque dia nem hora por conta própria. Tom: "Claro! Vou pedir para a nossa equipe combinar com você o melhor dia e horário para vir até o escritório, tudo bem?"',
        "Responda à dúvida (se perguntou o endereço, use só o que está nos dados do escritório) e siga."),
    "ligacao_telefonica": (
        "LEAD PEDIU LIGAÇÃO", "a equipe liga para o lead",
        'pede uma ligação de telefone ("me liga", "pode me ligar?", "prefiro falar por telefone"); aceitou claramente uma ligação oferecida',
        "pediu chamada de vídeo (isso seria quer_videochamada); só passou o número de telefone; pediu áudio; nenhuma menção",
        'Pergunte o melhor horário, sem garantir. Tom: "Claro! Vou pedir para a nossa equipe te ligar. Qual o melhor horário para você?"',
        "Siga a conversa; não ofereça ligação."),
    "parceria_comercial": (
        "CONTATO COMERCIAL (NÃO É LEAD)", "encaminha o contato ao responsável do escritório",
        "oferece serviço, parceria, indicação paga, anúncio, sistema ou venda ao escritório; não procura benefício para si nem para alguém da família",
        "procura benefício para si; indica um parente ou conhecido que precisa do benefício; só perguntou como o escritório trabalha",
        'Sem falar de benefício. Tom: "Obrigado pelo contato! Vou repassar a sua mensagem para o responsável do escritório, que retorna por aqui, combinado?"',
        "Siga a conversa do benefício."),
    "deficiencia_auditiva": (
        "LEAD COM DEFICIÊNCIA AUDITIVA", "avisa a equipe e a conversa segue só por texto",
        "diz que é surdo, tem deficiência auditiva ou não consegue ouvir áudios por causa da audição",
        "está sem fone ou em lugar barulhento; não pode ouvir agora; só prefere texto; nenhuma menção à audição",
        'Frases claras e curtas, só por texto, e siga a conversa. Tom: "Sem problema! Vamos conversar só por mensagem escrita, tudo bem?"',
        "Siga a conversa."),
}


@dataclass
class Auditoria:
    sinal: str
    valido: bool
    motivo: str
    mensagem: str
    falhou: bool = False
    chamadas: list[Chamada] = field(default_factory=list)


def sistema_do_auditor(sinal: str, escritorio: str, partes: dict[str, tuple[str, ...]] | None = None) -> str:
    titulo, efeito, valido, invalido, se_valido, se_invalido = {**PARTES, **(partes or {})}[sinal]
    return f"""# PAPEL
Você é um auditor de qualidade do atendimento via WhatsApp do escritório {escritorio}, de advocacia previdenciária.
O sistema marcou o aviso "{titulo}", que {efeito} e tira a IA da conversa.
Sua função: (1) conferir se esse aviso faz sentido e (2) escrever a mensagem que vai para o lead.

# PASSO 1: CONFERIR
Leia todo o histórico, dando mais peso às mensagens mais recentes do lead.
VÁLIDO quando: {valido}.
INVÁLIDO quando: {invalido}.
Na dúvida, considere inválido.

# PASSO 2: MENSAGEM PARA O LEAD
Responda diretamente à ÚLTIMA mensagem do lead.
Se válido: {se_valido}
Se inválido: {se_invalido} Não diga que a equipe vai assumir o atendimento.

# REGRAS DA MENSAGEM
- Português do Brasil, tom humano e acolhedor de WhatsApp. No máximo 2 frases.
- Não prometa prazos, valores ou resultados.
- Não diga que é uma IA e não use termos internos ("notificação", "aviso", "sistema", "válido").

# SAÍDA
valido (true/false), motivo (1 a 2 frases citando o que o lead disse ou enviou) e mensagem."""


def conteudo_do_auditor(historico: list[dict[str, Any]], novas: list[str], limite: int = 30) -> str:
    linhas = [f"{m.get('autor', '?')}: {m.get('texto', '')}" for m in historico[-limite:]]
    linhas += [f"lead: {texto}" for texto in novas]
    return "Conversa (mais antiga primeiro):\n" + "\n".join(linhas)


async def auditar_sinal(modelo: Modelo, *, sinal: str, historico: list[dict[str, Any]], novas: list[str],
                        nome_modelo: str, escritorio: str, partes: dict[str, tuple[str, ...]] | None = None) -> Auditoria:
    """Confere um sinal. `partes` troca o texto de algum sinal (ex.: o catálogo pede 3+ objeções, como no n8n)."""
    if sinal not in PARTES and sinal not in (partes or {}):
        return Auditoria(sinal, True, "sinal sem auditor", "", falhou=True)
    try:
        resultado = await modelo.gerar(papel="auditor", sistema=sistema_do_auditor(sinal, escritorio, partes),
                                       conteudo=conteudo_do_auditor(historico, novas), esquema=ESQUEMA,
                                       modelo=nome_modelo, esforco="low")
    except ErroModelo as erro:
        return Auditoria(sinal, True, f"auditor falhou ({erro.motivo})", "", falhou=True,
                         chamadas=list(getattr(erro, "chamadas", [])))
    dados = resultado.dados
    return Auditoria(sinal, bool(dados.get("valido")), str(dados.get("motivo") or "").strip(),
                     str(dados.get("mensagem") or "").strip(), chamadas=resultado.chamadas)
