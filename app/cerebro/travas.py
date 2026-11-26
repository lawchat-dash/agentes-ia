"""Travas de saída: conferem o que a IA escreveu antes de qualquer envio.

Cada reprovação tem um código (para o histórico) e uma orientação (para a IA refazer).
"""

from __future__ import annotations

import re
from typing import Any
from dataclasses import dataclass

from app.cerebro.extrator import normalizar

# "com certeza" sozinho é só um "claro!" ("Claro, com certeza! O atendimento é por aqui"): só vira promessa ligado a
# resultado ("com certeza vai", "certeza que vai ganhar"; o resto fica com _certeza_de_resultado, abaixo).
# O radical "garant" NÃO entra nesta lista: "o que posso garantir é que cuidamos do pedido" fala do serviço, não do
# resultado. "Garantir" ligado a um resultado ("garantir o direito dele") fica com garantia_de_resultado(), abaixo.
PROMESSAS = (
    "vai ganhar", "garantido", "garantia de", "garantimos", "com certeza vai",
    "certeza que vai", "certeza de que vai", "causa ganha", "direito garantido", "sem risco",
    "voce tem direito", "tem direito sim",
    # Avaliar as chances ou garantir em 1ª pessoa (regra fixa do motor: quem avalia é a equipe). "Não garanto" é
    # aviso honesto e passa (exceção abaixo).
    "boas chances", "garanto",
)
# Estratégia de vendas decidida pelo dono (26/11): no Closer o roteiro diz "o caso é bom e há boas chances". Só lá passa;
# "vai ganhar", "garantido" e "100% garantido" continuam barrados em qualquer etapa.
PERMITIDAS_NO_CLOSER = ("boas chances",)
# "Você vai receber" é promessa, menos quando o que chega é uma ENTREGA do atendimento (aviso de envio, não resultado):
# "Em alguns segundos você vai receber o link para assinatura!" é a mensagem obrigatória do Agente Contrato do Sousa e
# Costa e era barrada (refeita e, repetida, pausa por trava_persistente). "Você vai receber o benefício / os atrasados /
# o valor" continua barrado. Contato, ligação, retorno, visita ou atendimento da equipe também são serviço, não resultado
# ("você vai receber o contato da nossa equipe"); "resposta" fica de fora ("uma resposta positiva do INSS" é resultado).
# O texto já vem normalizado (minúsculo, sem acento nem pontuação).
_VOCE_VAI_RECEBER = re.compile(
    r"\bvoce vai receber\b(?!(?:\s+(?:o|a|os|as|seu|sua|seus|suas|um|uma|esse|essa|este|esta|agora|aqui|ja|logo|tambem"
    r"|em|alguns|instantes|segundos|minutos|por|pelo|no))*\s+(?:links?|contratos?|documentos?|mensage(?:m|ns)|codigos?|e ?mails?"
    r"|videos?|audios?|arquivos?|pdf|avisos?|notificac(?:ao|oes)|resumos?|instruc(?:ao|oes)|orientac(?:ao|oes)"
    r"|contatos?|ligac(?:ao|oes)|retornos?|visitas?|atendimentos?|chamadas?)\b)")
TERMOS_PROIBIDOS = (
    "qualidade de segurado", "periodo de graca", "12 meses", "24 meses", "36 meses",
)
TEXTO_INTERNO = (
    "sdr", "closer", "periodo_graca", "coleta_dados", "analise_manual", "desqualificado",
    "vinculo_na_data", "tool", "json", "prompt", "extrator",
)
DADOS_PESSOAIS = ("cpf", "rg", "endereco", "cep", "comprovante de residencia")
ETAPAS_COM_DADOS = ("coleta_dados", "assinatura")

_LINK = re.compile(r"(https?://|www\.)\S+", re.IGNORECASE)
_VALOR = re.compile(r"(r\$\s*\d[\d.,]*|\d+(?:[.,]\d+)?\s*(?:%|por\s*cento)|\d+\s*(?:x|vezes|parcelas?))", re.IGNORECASE)
# "100%" é procurado no texto ORIGINAL: normalizar() tira o "%" e qualquer "100" (CEP, número da casa, CPF) virava promessa.
# "100% online / digital / virtual / por WhatsApp / pela internet / a distância" fala do jeito de atender (vem dos dados do
# escritório, e a IA reescreve com outras palavras), não do resultado: barrar isso pausava o lead que só perguntou do site.
# "Gratuito" e "sem custo" NÃO ficam isentos (há honorários).
CEM_POR_CENTO = re.compile(
    r"(?:\b100\s*(?:%|por\s*cento)|\bcem\s+por\s*cento)"
    r"(?!\s*(?:online|on-line|on\s+line|digital|virtual|remoto|remotamente|[aà]\s+dist[aâ]ncia"
    r"|(?:pelo|por|via)\s+(?:o\s+)?whats\s*app|(?:pela|via)\s+internet|pelo\s+(?:celular|telefone)|por\s+aqui)\b)",
    re.IGNORECASE)
# Certeza ligada a RESULTADO, na mesma frase e em qualquer ordem: "com certeza você ganha", "com certeza você terá o
# benefício", "você vai conseguir o benefício, com certeza!", "seu benefício será aprovado, com certeza".
# Só a certeza não basta ("Com certeza, a equipe vai analisar o seu caso", "Com certeza, você recebe o link por aqui"
# são serviço): o resultado é ganhar, aprovar/conceder, ou receber/conseguir/ter/sair com um objeto de resultado
# (benefício, causa, direito, atrasados...). Frase de serviço barrada refazia a resposta e, repetida, pausava o lead.
_CERTEZA = re.compile(r"\b(?:com\s+(?:toda\s+)?certeza|(?:tenho\s+)?certeza\s+(?:de\s+)?que|sem\s+d[uú]vida)\b",
                      re.IGNORECASE)
_OBJETO_DE_RESULTADO = r"(?:benef[ií]cio|aux[ií]lio|aposentadoria|pens[aã]o|causa|direito|atrasados|indeniza[çc][aã]o|aprova[çc][aã]o)"
# Entre o verbo e o objeto só cabem artigos e afins ("vai receber o seu benefício"): "consegue tirar dúvida sobre o seu
# direito" ou "recebe o link do contrato" não são resultado.
_ENCHIMENTO = r"(?:\s+(?:o|a|os|as|seu|sua|seus|suas|esse|essa|este|esta|um|uma|de|do|da|dos|das|valor|sim|tamb[eé]m|j[aá]|mesmo|todo|toda))*"
_RESULTADO = re.compile(
    r"\bganh\w*\b(?!\s+(?:tempo|praticidade))"
    r"|\baprov(?:a|ad[oa]s?|ar|ar[áa]|ar[ãa]o|am|e|em|ou)\b(?!" + _ENCHIMENTO + r"\s+(?:resumo|contrato|dados|documento))"
    r"|\b(?:deferid|concedid)\w*"
    r"|\b(?:receb\w*|consegu\w*|ter|ter[áa]|ter[ãa]o|tem|t[eê]m|sai|sair[áa]?)" + _ENCHIMENTO + r"\s+" + _OBJETO_DE_RESULTADO + r"\b"
    r"|\b" + _OBJETO_DE_RESULTADO + r"(?:\s+[\w-]+){0,2}?\s+(?:sai|sair[áa]|vai\s+sair|ser[áa]\s+liberad\w*|liberad\w*)\b",
    re.IGNORECASE)


# "100% online / digital / pelo WhatsApp..." (o jeito de atender, que vem dos dados do escritório): não é honorário nem
# promessa. Forma POSITIVA da exceção de CEM_POR_CENTO, para tirar do texto antes de contar valores de honorário
# (sem isso, "Nosso atendimento é 100% online" era reprovado como honorário fora da tabela e, repetido, pausava o lead).
# Fonte única: a avaliação (app/avaliacao/checagens.py) deve importar daqui.
CEM_POR_CENTO_DO_SERVICO = re.compile(
    r"(?:\b100\s*(?:%|por\s*cento)|\bcem\s+por\s*cento)"
    r"(?=\s*(?:online|on-line|on\s+line|digital|virtual|remoto|remotamente|[aà]\s+dist[aâ]ncia"
    r"|(?:pelo|por|via)\s+(?:o\s+)?whats\s*app|(?:pela|via)\s+internet|pelo\s+(?:celular|telefone)|por\s+aqui)\b)",
    re.IGNORECASE)

# "Garantir" ligado a um RESULTADO, sobre o texto normalizado: "para garantir o direito dele", "garantir seu direito",
# "garantir que você receba tudo que tem direito", "garanto que você vai ter o benefício". O verbo sozinho continua livre:
# "para garantir que está tudo certinho" (frase obrigatória da confirmação do contrato), "garantir que o contrato seja
# gerado corretamente", "garantir que você receba o link" e "o que posso garantir é que cuidamos do pedido" falam do
# serviço. Até 6 palavras entre o verbo e o objeto, na mesma oração; negação na mesma oração isenta ("não podemos
# garantir o benefício" é aviso honesto). Fonte única: a avaliação deve importar daqui (PROMESSA_GARANTIR).
_OBJETO_GARANTIDO = (r"(?:beneficios?|auxilios?|aposentadorias?|pensao|pensoes|causas?|direitos?|atrasados|"
                     r"indenizac(?:ao|oes)|aprovac(?:ao|oes)|resultados?|vitorias?|ganhos?|concessao)")
PROMESSA_GARANTIR = re.compile(r"\bgarant\w*(?:\s+\w+){0,6}?\s+" + _OBJETO_GARANTIDO + r"\b"
                               r"|\bgarant\w*(?:\s+\w+){0,3}?\s+(?:ganh\w*|aprovad[oa]s?|concedid[oa]s?|deferid[oa]s?)\b")
_NEGACAO_NA_ORACAO = re.compile(r"\b(?:nao|ninguem|nem|nunca|jamais)\b(?:\s+\w+){0,7}\s*$")
_FIM_DE_ORACAO = re.compile(r"[.,;:!?\n()]+|\b(?:mas|por[eé]m|contudo|entretanto|todavia|s[oó] que)\b", re.IGNORECASE)


# Objeto qualificado por uma palavra de SERVIÇO ("garantir que o seu pedido de benefício seja bem feito"): não é resultado.
_SERVICO_ANTES_DO_OBJETO = {"pedido", "processo", "analise", "requerimento", "documento", "documentos", "cadastro",
                            "contrato", "laudo", "pericia", "atendimento"}


def garantia_de_resultado(texto: str) -> str | None:
    """Trecho (normalizado) que liga "garantir" a um resultado, fora de negação na mesma oração. None = nenhum."""
    for oracao in _FIM_DE_ORACAO.split(texto or ""):
        normal = normalizar(oracao)
        for achado in PROMESSA_GARANTIR.finditer(normal):
            if _NEGACAO_NA_ORACAO.search(normal[:achado.start()]):
                continue
            if _SERVICO_ANTES_DO_OBJETO & set(achado.group(0).split()[-4:-1]):
                continue
            return achado.group(0)
    return None


def _certeza_de_resultado(texto: str) -> str | None:
    """Trecho da frase que junta certeza e resultado, do primeiro ao último dos dois. None = nenhuma frase junta.
    A certeza negada ("não tenho certeza de que...") não conta."""
    for frase in re.split(r"[.!?\n]+", texto):
        certeza = next((c for c in _CERTEZA.finditer(frase)
                        if not re.search(r"\bn[aã]o\b[^,;:]{0,15}$", frase[:c.start()], re.IGNORECASE)), None)
        resultado = _RESULTADO.search(frase) if certeza else None
        if certeza and resultado:
            return frase[min(certeza.start(), resultado.start()):max(certeza.end(), resultado.end())].strip(" ,;:").lower()
    return None


# Exceções por item da lista PROMESSAS, sobre a frase normalizada (a expressão casada é o "achado"):
# - "você tem direito" condicional ("entender se você tem direito a esse retroativo", texto do próprio roteiro do Closer;
#   "para saber se você tem direito") ou numa pergunta não afirma o direito;
# - "vai ganhar tempo / praticidade / agilidade" é serviço (a mesma exceção de _RESULTADO);
# - "sem risco de perder o prazo" fala do prazo, não do resultado.
_ITENS_COM_EXCECAO: dict[str, re.Pattern[str]] = {
    "vai ganhar": re.compile(r"\bvai ganhar\b(?!\s+(?:tempo|praticidade|agilidade)\b)"),
    "sem risco": re.compile(r"\bsem risco\b(?!\s+de\s+perder\s+(?:o\s+|os\s+|seu\s+|seus\s+)?prazos?\b)"),
    "garanto": re.compile(r"(?<!\bnao )(?<!\bnunca )(?<!\bjamais )\bgaranto\b"),
}
_DIREITO_CONDICIONAL = re.compile(r"\bse\s+$")


def _promessa_da_lista(texto: str, permitidas: tuple[str, ...] = ()) -> str | None:
    """Item de PROMESSAS achado numa frase do texto. Frase a frase, divididas no texto ORIGINAL: normalizar() tira a
    pontuação e "Claro, com certeza! Vai ser um prazer" virava "com certeza vai"."""
    for achado in re.finditer(r"[^.!?\n]+[.!?\n]*", texto or ""):
        bruta = achado.group(0)
        frase = normalizar(bruta)
        if not frase:
            continue
        pergunta = "?" in bruta
        for item in PROMESSAS:
            if item in permitidas:
                continue
            alvo = normalizar(item)
            if item in _ITENS_COM_EXCECAO:
                if _ITENS_COM_EXCECAO[item].search(frase):
                    return item
                continue
            if item == "voce tem direito":
                if pergunta:
                    continue
                if any(not _DIREITO_CONDICIONAL.search(frase[:m.start()]) for m in re.finditer(re.escape(alvo), frase)):
                    return item
                continue
            if alvo in frase:
                return item
    return None


@dataclass(frozen=True)
class Reprovacao:
    codigo: str
    orientacao: str


def trecho_de_promessa(texto: str, permitidas: tuple[str, ...] = ()) -> str | None:
    """O trecho exato que soa como promessa de resultado, para a orientação dizer o que reescrever. None = nenhum."""
    if achado := CEM_POR_CENTO.search(texto):
        # Cita o "100%" com a palavra seguinte ("100% garantido"; "100% de chance" se ela for curta): a IA vê o que
        # caiu e não repete. Vem antes da lista para citar "100% garantido" inteiro, e não só "garantido".
        seguinte = re.match(r"\s*[\w-]{4,}|\s*[\w-]{1,3}(?:\s+[\w-]+)?", texto[achado.end():])
        return (achado.group(0) + (seguinte.group(0) if seguinte else "")).strip().lower()
    normal = normalizar(texto)
    if expressao := _promessa_da_lista(texto, permitidas):
        return expressao
    if _VOCE_VAI_RECEBER.search(normal):
        return "voce vai receber"
    return _certeza_de_resultado(texto) or garantia_de_resultado(texto)


def _valores(texto: str) -> set[str]:
    """Valores em dinheiro, percentuais e parcelas, normalizados para comparar."""
    return {re.sub(r"\s+", "", v.lower()).replace("vezes", "x").replace("porcento", "%").rstrip(".,") for v in _VALOR.findall(texto)}


def conferir(
    mensagens: list[dict[str, str]],
    *,
    etapa: str,
    honorarios: str | None,
    midias: dict[str, str],
    faltam: tuple[str, ...],
    max_perguntas: int = 1,
    produto: Any = None,
) -> list[Reprovacao]:
    if produto is None:
        from app.cerebro.produto import AuxilioAcidente
        produto = AuxilioAcidente()
    terminais = {e.codigo for e in produto.etapas if e.tipo == "terminal"}
    reprovacoes: list[Reprovacao] = []
    textos = [m["texto"] for m in mensagens if m["tipo"] == "texto"]
    tudo = "\n".join(textos)
    normal = normalizar(tudo)

    if not textos and not [m for m in mensagens if m["tipo"] == "midia"]:
        return [Reprovacao("resposta_vazia", "A resposta veio vazia. Escreva a mensagem para o lead.")]

    for m in mensagens:
        if m["tipo"] == "midia" and m["chave"] not in midias:
            reprovacoes.append(Reprovacao("midia_inexistente", f"A mídia '{m['chave']}' não existe. Use só as chaves listadas."))

    if _LINK.search(tudo):
        reprovacoes.append(Reprovacao("link", "Não escreva links."))

    if promessa := trecho_de_promessa(tudo):
        reprovacoes.append(Reprovacao("promessa", f"Reescreva sem a expressão '{promessa}'."))

    for termo in produto.termos_proibidos:
        if normalizar(termo) in normal:
            reprovacoes.append(Reprovacao("termo_tecnico", f"Não use esta expressão, proibida pelo escritório (trecho: \"{termo}\")."))
            break

    palavras = set(re.findall(r"[a-z_]+", tudo.lower()))
    interno = [t for t in TEXTO_INTERNO if t in palavras]
    if interno or "{" in tudo or "}" in tudo:
        reprovacoes.append(Reprovacao("texto_interno", "Não escreva nomes internos, códigos ou marcações: só a mensagem para o lead."))

    if etapa not in produto.etapas_com_dados_pessoais:
        palavras_normais = set(normal.split())
        pedido = [d for d in DADOS_PESSOAIS if (d in palavras_normais if " " not in d else d in normal)]
        if pedido:
            reprovacoes.append(Reprovacao("dado_pessoal_fora_de_hora", "Não peça nem mencione CPF, RG, endereço ou documentos nesta etapa."))

    valores = _valores(CEM_POR_CENTO_DO_SERVICO.sub(" ", tudo))     # "100% online" é o jeito de atender, não valor
    if valores:
        permitidos = _valores(honorarios or "")
        if etapa not in produto.etapas_com_valores or not valores <= permitidos:
            fora = ", ".join(sorted(valores - permitidos)) or ", ".join(sorted(valores))
            reprovacoes.append(Reprovacao(
                "honorarios",
                f"Valor ou percentual que não está nos honorários do escritório ({fora}). "
                "Use exatamente o que foi informado, ou diga que a equipe confirma os valores.",
            ))

    perguntas = tudo.count("?")
    if perguntas > max_perguntas:
        reprovacoes.append(Reprovacao("muitas_perguntas", f"Faça no máximo {max_perguntas} pergunta por resposta."))
    if not faltam and etapa in terminais and perguntas:
        reprovacoes.append(Reprovacao("pergunta_no_encerramento", "Não faça pergunta nesta mensagem."))

    if any(len(t) > 600 for t in textos):
        reprovacoes.append(Reprovacao("mensagem_longa", "Mensagem longa demais para WhatsApp. Escreva mais curto."))

    return reprovacoes
