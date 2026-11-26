"""Base de conhecimento: trechos, quando consultar, o texto da consulta e o bloco que entra no prompt.

Sem IO e sem serviço externo. A busca por vetor e a indexação ficam em app/conhecimento_indice.py.
Desenho: docs/BASE_DE_CONHECIMENTO.md.

- Trechos de ~1.000 caracteres (150 de sobreposição), com "Documento > Seção" no começo do texto vetorizado.
  Cada item de FAQ e cada objeção é um trecho próprio.
- Consulta só com a fala nova do lead (mais a última pergunta da IA quando a fala é curta); "oi", "ok", "sim" e
  números soltos não consultam.
- No máximo 4 trechos (2 do mesmo documento) e 3.500 caracteres por turno. Nada passa = nada entra.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

TAMANHO_TRECHO = 1000
SOBRA = 150
TETO_PADRAO = 3500                  # caracteres de base por turno (config.conhecimento.teto_documentos: 1.000 a 8.000)
TETO_MINIMO, TETO_MAXIMO = 1000, 8000
TRECHOS_POR_TURNO = 4
POR_DOCUMENTO = 2
CORTE_RELATIVO = 0.8                # descarta abaixo de 80% da melhor nota
PESO_LEXICO = 0.08                  # nota = cosseno + 0,08 × fração das palavras da consulta presentes no trecho
FIXO_FAQ_OBJECOES = 3000            # FAQ + objeções do papel até isto ficam fixas no sistema; acima, vão para a busca
FIXO_DOCUMENTOS = 2000              # documentos do papel até isto ficam fixos no sistema
FIXO_DADOS = 1500                   # DADOS DO ESCRITÓRIO fixos; o excedente vira trecho buscado
COBERTURA_MINIMA_PALAVRAS = 0.2     # busca por palavras: fração mínima (pesada por idf) da consulta presente no trecho
CONSULTA_MAXIMA = 1500              # caracteres da consulta
PERGUNTA_IA_MAXIMA = 200
LIMITE_DOCUMENTO = 400_000          # texto guardado por documento
LIMITE_ARQUIVO = 8 * 1024 * 1024    # 8 MB por arquivo
LIMITE_FAQ, LIMITE_OBJECOES = 300, 200   # itens guardados na config (antes eram 40 e 30, cortados em silêncio)

PARADAS = set("""a o as os um uma uns umas de do da dos das em no na nos nas por pelo pela pelos pelas para pra pro com sem
e ou mas que se nao sim ja eu tu ele ela nos vos eles elas meu minha seu sua isso isto esse essa este esta aquele aquela
ao aos foi ser ter tem tenho era sao como quando onde qual quais quanto muito mais menos tambem so ai la aqui entao
me te lhe voce voces oi ola bom boa dia tarde noite obrigado obrigada ta to estou esta estao vai vou""".split())

# Falas que não pedem consulta: saudação, confirmação, agradecimento, risada.
_VAZIAS = set("""oi ola opa ok okay blz beleza certo sim nao claro pode isso exato entendi entendo obrigado obrigada obg
vlw valeu tmj bom boa dia tarde noite tudo bem otimo perfeito show top combinado ta to aham uhum hum kkk kkkk kkkkk rs rsrs
haha hahaha ah eh ne sei ah tah oii oiii ola""".split())

FONTES = ("documento", "faq", "objecao")
ROTULO_FONTE = {"documento": "Documento", "faq": "FAQ", "objecao": "Objeção"}

# Regra fixa no SISTEMA (igual em todo turno: aproveita o cache de prompt do provedor).
REGRA_FONTES = """# FATOS DO ESCRITÓRIO: DE ONDE PODEM VIR
Valores, porcentagens, prazos, documentos, endereço, horários, regras do benefício e como o escritório trabalha só podem vir de:
o roteiro desta etapa, DADOS DO ESCRITÓRIO, HONORÁRIOS, FATOS DO SISTEMA ou a BASE DE CONHECIMENTO enviada no turno.
Se o lead perguntar algo que não está em nenhum desses: não invente, não estime, não use conhecimento geral da
internet como se fosse do escritório. Diga em 1 frase que vai confirmar com a equipe, volte para a pergunta da etapa
e preencha "base.sem_resposta" com a pergunta do lead (curta, com as palavras dele).
O roteiro manda mais que a base. Use a base em 1 ou 2 frases, com suas palavras, e volte para a etapa.
Em "base.usados" ponha os números [n] dos trechos da BASE DE CONHECIMENTO que você usou (vazio se nenhum)."""


@dataclass(frozen=True)
class Trecho:
    documento: str
    texto: str
    fonte: str = "documento"
    titulo: str = ""
    nota: float | None = field(default=None, compare=False)
    id: str | None = field(default=None, compare=False)


# ---------------------------------------------------------------------------- palavras
def sem_acento(texto: str) -> str:
    return unicodedata.normalize("NFKD", (texto or "").lower()).encode("ascii", "ignore").decode()


def _palavras(texto: str) -> list[str]:
    return [p for p in re.findall(r"[a-z0-9]{3,}", sem_acento(texto)) if p not in PARADAS]


def _raiz(palavra: str) -> str:
    """Raiz grosseira para o reforço por palavra ("contribuir" ~ "contribuições", "documentos" ~ "documento")."""
    return palavra[:6] if len(palavra) > 6 else palavra


def palavras_de_conteudo(texto: str) -> list[str]:
    """Palavras que dizem algo: sem acento, sem as vazias de conversa e sem números soltos."""
    return [p for p in re.findall(r"[a-z0-9]+", sem_acento(texto))
            if p not in _VAZIAS and p not in PARADAS and not p.isdigit() and len(p) >= 3]


def normalizar_pergunta(texto: str) -> str:
    """Chave da lacuna: a mesma dúvida escrita de jeito parecido soma no mesmo registro."""
    return " ".join(re.findall(r"[a-z0-9]+", sem_acento(texto)))[:300]


# ---------------------------------------------------------------------------- quando consultar e o que consultar
def precisa_consultar(novas: list[str]) -> bool:
    """Regra local, sem IA: consulta se a fala nova tem "?" ou 2+ palavras de conteúdo."""
    texto = " ".join(t for t in novas if t and not t.startswith("(mensagem vazia"))
    conteudo = palavras_de_conteudo(texto)
    if "?" in texto and conteudo:
        return True
    return len(conteudo) >= 2


def montar_consulta(novas: list[str], ultima_pergunta_ia: str | None = None) -> str:
    """Falas novas do lead; se forem curtas (< 4 palavras de conteúdo), a última pergunta da IA vem antes para dar o assunto."""
    fala = " ".join(t.strip() for t in novas if t and t.strip())
    pergunta = (ultima_pergunta_ia or "").strip()
    if pergunta and len(palavras_de_conteudo(fala)) < 4 and pergunta.endswith("?"):
        return (pergunta[-PERGUNTA_IA_MAXIMA:] + "\n" + fala)[-CONSULTA_MAXIMA:]
    return fala[-CONSULTA_MAXIMA:]


def ultima_pergunta_da_ia(historico: list[dict[str, str]] | list[Any]) -> str | None:
    """Última fala da IA no histórico, se terminar em pergunta (até 200 caracteres do fim)."""
    for m in reversed(historico or []):
        autor = m.get("autor") if isinstance(m, dict) else getattr(m, "autor", None)
        if autor not in ("ia", "você"):
            continue
        texto = (m.get("texto") if isinstance(m, dict) else (m.para_a_ia() if hasattr(m, "para_a_ia") else "")) or ""
        texto = texto.strip()
        return texto[-PERGUNTA_IA_MAXIMA:] if texto.endswith("?") else None
    return None


def reforco_lexico(consulta: str, texto: str) -> float:
    """Fração das palavras de conteúdo da consulta que aparecem no trecho (pela raiz)."""
    termos = {_raiz(p) for p in palavras_de_conteudo(consulta)}
    if not termos:
        return 0.0
    presentes = {_raiz(p) for p in _palavras(texto)}
    return sum(1 for t in termos if t in presentes) / len(termos)


# ---------------------------------------------------------------------------- trechos
_TITULO = re.compile(r"^(?:#{1,6}\s+(.+)|([A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9][A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9 ,.()/-]{3,80})|(.{3,80}):)\s*$")


def dividir(texto: str, tamanho: int = TAMANHO_TRECHO, sobra: int = SOBRA) -> list[str]:
    """Trechos de até `tamanho` caracteres, cortando em parágrafo ou frase, com um pouco de sobreposição."""
    texto = re.sub(r"\n{3,}", "\n\n", (texto or "").strip())
    if len(texto) <= tamanho:
        return [texto] if texto else []
    trechos, inicio = [], 0
    while inicio < len(texto):
        fim = min(len(texto), inicio + tamanho)
        if fim < len(texto):
            corte = max(texto.rfind("\n\n", inicio, fim), texto.rfind(". ", inicio, fim), texto.rfind("\n", inicio, fim))
            if corte > inicio + tamanho // 2:
                fim = corte + 1
        trechos.append(texto[inicio:fim].strip())
        if fim >= len(texto):
            break
        inicio = max(fim - sobra, inicio + 1)
    return [t for t in trechos if t]


def _secao_antes(texto: str, posicao: int) -> str:
    """Título da seção mais próxima antes da posição: linha markdown "#", linha em maiúsculas ou linha terminada em ":"."""
    titulo = ""
    for linha in texto[:posicao].splitlines():
        achado = _TITULO.match(linha.strip())
        if achado:
            titulo = next(g for g in achado.groups() if g).strip(" :#")
    return titulo


def dividir_com_titulo(nome: str, texto: str) -> list[tuple[str, str]]:
    """[(título, texto vetorizado)]: o texto começa com "Documento: nome > seção"."""
    texto = re.sub(r"\n{3,}", "\n\n", (texto or "").strip())
    saida, procurar_de = [], 0
    for pedaco in dividir(texto):
        posicao = texto.find(pedaco[:80], procurar_de)
        posicao = posicao if posicao >= 0 else procurar_de
        procurar_de = posicao + 1
        secao = _secao_antes(texto, posicao + 1) or _secao_antes(pedaco, len(pedaco))
        titulo = f"{nome} > {secao}" if secao and secao.lower() != nome.lower() else nome
        saida.append((titulo, f"Documento: {titulo}\n{pedaco}"))
    return saida


def texto_do_item(fonte: str, item: dict[str, Any]) -> str:
    if fonte == "faq":
        return f"Pergunta: {str(item.get('pergunta') or '').strip()}\nResposta: {str(item.get('resposta') or '').strip()}"
    return f"Objeção do lead: {str(item.get('objecao') or '').strip()}\nComo responder: {str(item.get('resposta') or '').strip()}"


def papeis_validos(valor: Any) -> list[str]:
    if isinstance(valor, str):
        valor = [valor]
    if not isinstance(valor, (list, tuple)):
        return []
    return sorted({str(p).strip() for p in valor if str(p or "").strip()})[:20]


def serve_para(papeis: list[str] | tuple[str, ...] | None, papel: str | None) -> bool:
    """Escopo por papel: vazio = todos os papéis."""
    return not papeis or papel is None or papel in papeis


def itens_da_config(conhecimento: dict[str, Any] | None) -> list[dict[str, Any]]:
    """FAQ e objeções da config como trechos (um por item), com o escopo de papel de cada um."""
    conhecimento = conhecimento or {}
    itens: list[dict[str, Any]] = []
    for fonte, chave, campo, documento in (("faq", "faq", "pergunta", "FAQ"), ("objecao", "objecoes", "objecao", "Objeções")):
        for item in conhecimento.get(chave) or []:
            if not isinstance(item, dict):
                continue
            titulo, resposta = str(item.get(campo) or "").strip(), str(item.get("resposta") or "").strip()
            if not titulo or not resposta:
                continue
            itens.append({"documento": documento, "fonte": fonte, "titulo": titulo, "conteudo": texto_do_item(fonte, item),
                          "papeis": papeis_validos(item.get("papeis"))})
    return itens


# ---------------------------------------------------------------------------- busca por palavras (sem vetor)
def escolher(documentos: list[tuple[str, str]], consulta: str, teto: int = TETO_PADRAO) -> list[Trecho]:
    """Busca por palavras em documentos inteiros (sem índice). documentos = [(nome, texto)]."""
    documentos = [(n, t) for n, t in documentos if (t or "").strip()]
    if not documentos:
        return []
    if sum(len(t) for _, t in documentos) <= teto:
        return [Trecho(n, t.strip()) for n, t in documentos]
    trechos = [{"documento": n, "conteudo": pedaco, "titulo": titulo, "fonte": "documento", "papeis": []}
               for n, t in documentos for titulo, pedaco in dividir_com_titulo(n, t)]
    return escolher_por_palavras(trechos, consulta, teto=teto, quantos=TRECHOS_POR_TURNO * 2, por_documento=TRECHOS_POR_TURNO * 2)


def escolher_por_palavras(trechos: list[dict[str, Any]], consulta: str, *, papel: str | None = None,
                          teto: int = TETO_PADRAO, quantos: int = TRECHOS_POR_TURNO,
                          por_documento: int = POR_DOCUMENTO, relativo: float = 0.5,
                          cobertura: float = COBERTURA_MINIMA_PALAVRAS) -> list[Trecho]:
    """Pontuação por palavras em comum, pesando as raras (idf). Mesmo escopo e mesmos limites da busca por vetor.
    Trecho que cobre menos de `cobertura` do peso da consulta (ex.: só "processo" numa pergunta sobre perícia) não entra."""
    candidatos = [t for t in trechos if serve_para(t.get("papeis"), papel) and (t.get("conteudo") or "").strip()]
    termos = Counter(_raiz(p) for p in palavras_de_conteudo(consulta))
    if not candidatos or not termos:
        return []
    palavras = [{_raiz(p) for p in _palavras(t["conteudo"])} for t in candidatos]
    total = len(candidatos)
    idf = {p: math.log(1 + total / (1 + sum(1 for ps in palavras if p in ps))) for p in termos}
    maximo = sum(idf[p] * min(q, 2) for p, q in termos.items()) or 1.0
    pontos = []
    for i, ps in enumerate(palavras):
        bruto = sum(idf[p] * min(q, 2) for p, q in termos.items() if p in ps)
        if bruto > 0 and bruto / maximo >= cobertura:
            pontos.append((bruto / maximo / math.sqrt(1 + len(ps) / 400), i))
    return _cortar(candidatos, pontos, minimo=0.0, relativo=relativo, quantos=quantos, por_documento=por_documento, teto=teto)


def _cortar(candidatos: list[dict[str, Any]], pontos: list[tuple[float, int]], *, minimo: float, relativo: float,
            quantos: int, por_documento: int, teto: int) -> list[Trecho]:
    """Cortes comuns: nota mínima, corte relativo à melhor, limite total, por documento e teto de caracteres."""
    pontos = sorted((p for p in pontos if p[0] >= minimo and p[0] > 0), key=lambda x: (-x[0], x[1]))
    if not pontos:
        return []
    melhor = pontos[0][0]
    escolhidos: list[tuple[float, int]] = []
    usado, por_doc = 0, Counter()
    for nota, i in pontos:
        if len(escolhidos) >= quantos or nota < melhor * relativo:
            break
        t = candidatos[i]
        chave = t.get("id_documento") or t.get("documento")
        if por_doc[chave] >= por_documento or usado + len(t["conteudo"]) > teto:
            continue
        escolhidos.append((nota, i))
        usado += len(t["conteudo"])
        por_doc[chave] += 1
    return [Trecho(candidatos[i].get("documento") or "", candidatos[i]["conteudo"], candidatos[i].get("fonte") or "documento",
                   candidatos[i].get("titulo") or "", round(nota, 4), candidatos[i].get("id"))
            for nota, i in escolhidos]                    # melhor primeiro: [1] é o mais parecido


# ---------------------------------------------------------------------------- prompt
def montar_bloco_fixo(trechos: list[Trecho]) -> str:
    """Documentos pequenos que ficam fixos no SISTEMA (todos os do papel somam até FIXO_DOCUMENTOS)."""
    if not trechos:
        return ""
    partes = ["DOCUMENTOS DO ESCRITÓRIO (consulta: use só o que responde à pergunta, com suas palavras; "
              "o que não estiver aqui, não invente — diga que vai confirmar com a equipe):"]
    for t in trechos:
        partes.append(f"[{t.documento}]\n{t.texto}")
    return "\n\n".join(partes)


def _sem_cabecalho(t: Trecho) -> str:
    texto = t.texto
    if t.fonte == "documento" and texto.startswith("Documento: "):
        texto = texto.split("\n", 1)[1] if "\n" in texto else ""
    return texto.strip()


def rotulo(t: Trecho) -> str:
    if t.fonte == "documento":
        return f"Documento: {t.titulo or t.documento}"
    return f"{ROTULO_FONTE.get(t.fonte, 'Base')}: {t.titulo or t.documento}"


def montar_bloco(trechos: list[Trecho], consultou: bool = True) -> str:
    """Bloco do CONTEÚDO do turno, antes de "MENSAGENS NOVAS DO LEAD": trechos numerados [n] com a fonte.
    Sem trecho: avisa "nada encontrado" quando houve consulta; sem consulta, não aparece."""
    if not trechos:
        return "BASE DE CONHECIMENTO: nada encontrado para esta mensagem." if consultou else ""
    partes = ["BASE DE CONHECIMENTO DO ESCRITÓRIO (achada para a mensagem nova; use só isto para fatos do escritório; "
              "cite em base.usados os números que usar):"]
    for n, t in enumerate(trechos, 1):
        corpo = "\n".join("    " + linha for linha in _sem_cabecalho(t).splitlines() if linha.strip())
        partes.append(f"[{n}] {rotulo(t)}\n{corpo}")
    return "\n".join(partes)


def separar_dados(dados: str) -> tuple[str, str]:
    """DADOS DO ESCRITÓRIO: até FIXO_DADOS caracteres ficam fixos (cortando em parágrafo/linha); o resto vai para a busca."""
    dados = (dados or "").strip()
    if len(dados) <= FIXO_DADOS:
        return dados, ""
    corte = max(dados.rfind("\n\n", 0, FIXO_DADOS), dados.rfind("\n", 0, FIXO_DADOS), dados.rfind(". ", 0, FIXO_DADOS))
    corte = corte + 1 if corte > FIXO_DADOS // 2 else FIXO_DADOS
    return dados[:corte].strip(), dados[corte:].strip()


# ---------------------------------------------------------------------------- guarda de fonte (valor, porcentagem, prazo)
_UNIDADE = r"(?:dias?(?:\s+[úu]teis)?|meses|m[êe]s|anos?|semanas?|horas?)"
_VALOR = re.compile(rf"R\$\s?\d[\d.]*(?:,\d{{2}})?|\b\d{{1,3}}(?:[.,]\d+)?\s?(?:%|por\s+cento\b)|\b\d{{1,4}}\s+{_UNIDADE}\b",
                    re.IGNORECASE)
# Nas fontes (sem acento): "30%", "30 por cento"; "6 meses", "de 6 a 12 meses", "entre 1 e 2 anos", "5 (cinco) anos".
_PORCENTO_NA_FONTE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:%|por\s+cento\b)")
_PRAZO_NA_FONTE = re.compile(r"(\d+)(?:\s*(?:a|e|ou|-|ate)\s*(\d+))?\s*(?:\([a-z0-9 ]+\)\s*)?"
                             r"(?:dias?|meses|mes|anos?|semanas?|horas?)\b")
_NUMEROS_POR_EXTENSO = {"um": "1", "uma": "1", "dois": "2", "duas": "2", "tres": "3", "quatro": "4", "cinco": "5",
                        "seis": "6", "sete": "7", "oito": "8", "nove": "9", "dez": "10", "doze": "12", "quinze": "15",
                        "vinte": "20", "trinta": "30", "sessenta": "60", "noventa": "90"}
# Na resposta da IA: "seis meses" e "trinta por cento" também são prazo/porcentagem ("um"/"uma" não: "um dia desses").
_EXTENSO_NA_RESPOSTA = re.compile(r"\b(dois|duas|tr[eê]s|quatro|cinco|seis|sete|oito|nove|dez|doze|quinze|vinte|trinta|"
                                  r"sessenta|noventa)\b(?=\s+(?:dias?|meses|m[êe]s|anos?|semanas?|horas?|por\s+cento)\b)",
                                  re.IGNORECASE)


def _num(texto: str) -> str:
    return re.sub(r"[^\d]", "", texto.split(",")[0]) if "R$" in texto.upper() else re.sub(r"[^\d,.]", "", texto).replace(",", ".")


def _extenso(texto: str) -> str:
    corrido = sem_acento(texto)
    for palavra, numero in _NUMEROS_POR_EXTENSO.items():
        corrido = re.sub(rf"\b{palavra}\b", numero, corrido)
    return corrido


def _numeros_da_fonte(texto: str) -> set[str]:
    numeros = set(re.findall(r"\d+(?:[.,]\d+)?", _extenso(texto)))
    return numeros | {n.replace(".", "").replace(",", ".") for n in numeros} | {n.split(",")[0].replace(".", "") for n in numeros}


def _pct(numero: str) -> str:
    """'30', '30,0', '30.00' -> '30'; '12,5' -> '12.5'."""
    numero = numero.replace(",", ".")
    return numero.rstrip("0").rstrip(".") if "." in numero else numero


def _porcentagens_da_fonte(texto: str) -> set[str]:
    return {_pct(n) for n in _PORCENTO_NA_FONTE.findall(_extenso(texto))}


def _prazos_da_fonte(texto: str) -> set[str]:
    return {n for par in _PRAZO_NA_FONTE.findall(_extenso(texto)) for n in par if n}


def fato_sem_fonte(textos: list[str], fontes: list[str], livres: list[str] | None = None) -> str | None:
    """Valor em R$, porcentagem ou prazo ("30 dias", "6 meses") da resposta sem fonte = fato do escritório inventado.

    `fontes`: o que o escritório deu ao modelo (roteiro, dados, honorários, fatos do sistema, base). `livres`: o que veio
    do lead (falas e fatos extraídos). Regras, pela unidade (só o número em qualquer lugar do prompt não basta: um
    prompt grande tem quase todo número pequeno):
      - porcentagem: o número precisa estar como porcentagem nas fontes (o lead não "confirma" 10% perguntando);
      - prazo: o número com unidade de tempo nas fontes, ou o número dito pelo lead ("tenho 45" -> "45 anos");
      - R$: o número nas fontes ou nas falas do lead ("ganho R$ 1.800")."""
    escritorio = " ".join(str(f) for f in fontes if f)
    do_lead = " ".join(str(f) for f in livres or [] if f)
    numeros = _numeros_da_fonte(escritorio)
    numeros_lead = _numeros_da_fonte(do_lead)
    porcentagens = _porcentagens_da_fonte(escritorio)
    prazos = _prazos_da_fonte(escritorio)
    resposta = _EXTENSO_NA_RESPOSTA.sub(lambda m: _NUMEROS_POR_EXTENSO[sem_acento(m.group(1))], "\n".join(textos))
    for achado in _VALOR.finditer(resposta):
        bruto = achado.group(0)
        numero = _num(bruto).strip(".")
        if not numero:
            continue
        candidatos = {numero, numero.replace(".", ""), numero.split(".")[0]}
        if "R$" in bruto.upper():
            aceitos = numeros | numeros_lead
        elif "%" in bruto or "cento" in bruto.lower():
            candidatos = {_pct(numero)}
            aceitos = porcentagens
        else:
            aceitos = prazos | numeros_lead
        if not candidatos & aceitos:
            return bruto.strip()
    return None
