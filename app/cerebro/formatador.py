"""Formatador: deixa o texto com cara de WhatsApp e calcula a pausa antes de cada envio."""

from __future__ import annotations

import re

LIMITE_POR_MENSAGEM = 320


# Chips internos do prompt (nunca chegam ao lead): "@Comercial", "@Agente Closer", "@Transferência: X",
# "→ @Análise da equipe", "acionar tool `x`". Se a IA copiar um deles na resposta, ele sai aqui, antes do envio.
_PAPEIS_CHIP = (r"SDR|Comercial|Closer|Coleta de Dados|Acompanhamento Assinatura|Assinatura|Desqualificado|"
                r"Per[ií]odo de Gra[cç]a|An[aá]lise da equipe|Buscar CEP|ZapSign")
_CHIP_INTERNO = re.compile(
    r"(?:→\s*)?@(?:Transfer[eê]ncia:\s*[\wÀ-ÿ ]+?(?=[.,;!?\n]|$)|(?:Agente\s+)?(?:" + _PAPEIS_CHIP + r")(?![\wÀ-ÿ]))"
    r"|acionar\s+(?:a\s+)?tool\s+`[^`]*`", re.IGNORECASE)


def tirar_chips(texto: str) -> str:
    """Tira os chips internos do prompt de um texto que vai para o lead (e-mail com @ não é chip: fica)."""
    if "@" not in texto and "tool" not in texto.lower():
        return texto
    limpo = _CHIP_INTERNO.sub("", texto)
    limpo = re.sub(r"[ \t]+([,.;!?])", r"\1", limpo)
    limpo = re.sub(r"(?:\s*\b(?:para|pro|pra|com|o|a|ao)\b)+\s*([.!?])", r"\1", limpo)  # "para o ." que sobrou
    return re.sub(r"[ \t]{2,}", " ", limpo).strip()


# Sobras de sistema que o modelo às vezes escreve no texto (cat. 31 da auditoria): chamada de função
# ("functions.zapsign({...})", "to=functions.x"), chaves vazias "{}" / "[]" e JSON solto ({"transferir_para": ""}).
_CHAMADA_DE_FUNCAO = re.compile(r"(?:\bto=)?\b(?:functions|multi_tool_use)\.[A-Za-z_][\w.]*"
                                r"(?:\s*\((?:[^()]|\([^()]*\))*\))?")
_JSON_INLINE = re.compile(r"\{\s*\"[^\"{}\n]*\"\s*:[^{}\n]*\}")
_VAZIOS = re.compile(r"(?<![{\[])(?:\{\s*\}|\[\s*\])(?![}\]])")


def _linha_e_json(linha: str) -> bool:
    import json

    linha = linha.strip()
    if not linha or linha[0] not in "{[" or linha[-1] not in "}]":
        return False
    if linha.startswith("{{") or linha.startswith("[["):        # variável {{X}} e marcador [[audio:x]]: outras travas
        return False
    try:
        json.loads(linha)
        return True
    except ValueError:
        return bool(re.search(r"\"\w+\"\s*:", linha))


def tirar_sobras_de_sistema(texto: str) -> str:
    """Tira do texto ao lead as sobras de sistema: chamada de função, JSON solto e chaves vazias."""
    if not any(c in texto for c in "{[."):
        return texto
    limpo = "\n".join(linha for linha in texto.split("\n") if not _linha_e_json(linha))
    limpo = _CHAMADA_DE_FUNCAO.sub("", limpo)
    limpo = _JSON_INLINE.sub("", limpo)
    limpo = _VAZIOS.sub("", limpo)
    limpo = re.sub(r"[ \t]+([,.;!?])", r"\1", limpo)
    return re.sub(r"[ \t]{2,}", " ", limpo).strip()


def tem_conteudo(texto: str) -> bool:
    """Balão com alguma letra, número ou emoji. Só aspas, pontuação ou chaves ('""', '{}', '...') não vai ao lead."""
    import unicodedata

    return any(c.isalnum() or unicodedata.category(c) == "So" for c in texto or "")


def limpar(texto: str) -> str:
    texto = tirar_sobras_de_sistema(tirar_chips(texto))
    texto = re.sub(r"\*\*(.+?)\*\*", r"\1", texto)            # negrito de Markdown
    texto = re.sub(r"^#{1,6}\s*", "", texto, flags=re.MULTILINE)  # títulos
    texto = re.sub(r"^\s*[-•]\s+", "", texto, flags=re.MULTILINE)  # marcadores de lista
    # Travessão colado a pontuação ("[período] —, esse benefício", vaga vazia do modelo do prompt): some antes da troca
    # geral. Sem isso, "—," virava ", ," e o lead recebia "auxílio-doença , , esse benefício".
    texto = re.sub(r"[ \t]*[—–][ \t]*(?=[,.;:!?])", "", texto)
    texto = texto.replace(" — ", ", ").replace("—", ", ").replace(" – ", ", ")
    texto = re.sub(r"[ \t]*,(?:[ \t]*,)+", ",", texto)                # ", ," -> ","
    texto = re.sub(r"[ \t]+([,.;!?])", r"\1", texto)                 # espaço antes da pontuação ([ \t]: não junta linhas)
    texto = re.sub(r"[ \t]+", " ", texto)
    return re.sub(r"\n{3,}", "\n\n", texto).strip()


def dividir(texto: str, limite: int = LIMITE_POR_MENSAGEM) -> list[str]:
    """Quebra texto longo em mensagens menores, primeiro por parágrafo e depois por frase."""
    partes: list[str] = []
    for paragrafo in (p.strip() for p in texto.split("\n\n")):
        if not paragrafo:
            continue
        if len(paragrafo) <= limite:
            partes.append(paragrafo)
            continue
        atual = ""
        for frase in re.split(r"(?<=[.!?])\s+", paragrafo):
            if atual and len(atual) + 1 + len(frase) > limite:
                partes.append(atual)
                atual = frase
            else:
                atual = f"{atual} {frase}".strip()
        if atual:
            partes.append(atual)
    return partes


def tempo_de_digitacao(texto: str) -> float:
    """Pausa antes de enviar, proporcional ao tamanho, entre 1,5 e 8 segundos."""
    return round(min(8.0, max(1.5, len(texto) * 0.04)), 1)


TETO_DE_BALOES = 5
LIMITE_DO_BALAO_JUNTADO = 1000
_LINK = re.compile(r"https?://|www\.", re.IGNORECASE)


def _fixa(parte: dict[str, object], ultima_pergunta: bool) -> bool:
    """Parte que não se junta a outra: mídia, link (fica sozinho para o WhatsApp mostrar a prévia), a frase de entrada
    de outro agente (marcada "fixa") e a pergunta final."""
    if parte.get("tipo") != "texto" or parte.get("fixa"):
        return True
    texto = str(parte.get("texto") or "")
    return bool(_LINK.search(texto)) or ultima_pergunta


def juntar_excedente(partes: list[dict[str, object]], teto: int = TETO_DE_BALOES,
                     limite: int = LIMITE_DO_BALAO_JUNTADO) -> list[dict[str, object]]:
    """Mais de `teto` balões: junta textos vizinhos (com linha em branco) até caber, sem passar de `limite` caracteres
    por balão. Mídia e link ficam sozinhos; a última pergunta fica isolada. Junta primeiro os pares menores, na
    ordem; nunca corta conteúdo (se não houver par que caiba, fica acima do teto)."""
    if teto < 1 or len(partes) <= teto:
        return partes
    saida = [dict(p) for p in partes]
    textos = [i for i, p in enumerate(saida) if p.get("tipo") == "texto"]
    ultima = textos[-1] if textos and str(saida[textos[-1]].get("texto") or "").rstrip().endswith("?") else None
    fixas = {id(p) for i, p in enumerate(saida) if _fixa(p, i == ultima)}
    while len(saida) > teto:
        melhor: tuple[int, int] | None = None                    # (tamanho juntado, posição)
        for i in range(len(saida) - 1):
            a, b = saida[i], saida[i + 1]
            if id(a) in fixas or id(b) in fixas:
                continue
            tamanho = len(str(a["texto"])) + 2 + len(str(b["texto"]))
            if tamanho <= limite and (melhor is None or tamanho < melhor[0]):
                melhor = (tamanho, i)
        if melhor is None:
            break
        i = melhor[1]
        texto = f"{saida[i]['texto']}\n\n{saida[i + 1]['texto']}"
        saida[i:i + 2] = [{**saida[i], "texto": texto, "espera_s": tempo_de_digitacao(texto)}]
    return saida


def redividir(partes: list[dict[str, object]], limite: int) -> list[dict[str, object]]:
    """Tamanho das mensagens escolhido no agente (config["caracteres_por_mensagem"]): junta os textos vizinhos e quebra
    de novo em mensagens de até `limite` caracteres, por parágrafo e frase (sem cortar palavra). Mídia e link ficam
    sozinhos, como sempre. limite <= 0: deixa como está."""
    if limite <= 0:
        return partes
    saida: list[dict[str, object]] = []
    bloco: list[str] = []

    def fechar() -> None:
        if bloco:
            for parte in dividir("\n\n".join(bloco), limite):
                saida.append({"tipo": "texto", "texto": parte, "espera_s": tempo_de_digitacao(parte)})
            bloco.clear()

    for parte in partes:
        texto = str(parte.get("texto") or "")
        if parte.get("tipo") != "texto" or _LINK.search(texto) or parte.get("fixa"):
            fechar()
            saida.append(parte)
        else:
            bloco.append(texto)
    fechar()
    return saida


def _sem_espaco(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip()


def isolar_frases(partes: list[dict[str, object]], frases: list[str]) -> list[dict[str, object]]:
    """A frase de entrada de outro agente ("Maravilha! Nós podemos te ajudar…") sai SEMPRE sozinha, numa mensagem só
    dela, e não se junta a outra depois. O texto antes e depois dela vira mensagem própria."""
    frases = [f for f in (_sem_espaco(str(x or "")) for x in frases) if len(f) >= 12 and "{{" not in f]
    if not frases:
        return partes
    saida: list[dict[str, object]] = []
    for parte in partes:
        texto = _sem_espaco(str(parte.get("texto") or ""))
        achada = next((f for f in sorted(frases, key=len, reverse=True) if parte.get("tipo") == "texto" and f in texto), None)
        if not achada:
            saida.append(parte)
            continue
        antes, _, depois = texto.partition(achada)
        for pedaco, fixa in ((antes.strip(), False), (achada, True), (depois.strip(), False)):
            if pedaco:
                saida.append({**parte, "texto": pedaco, "espera_s": tempo_de_digitacao(pedaco), **({"fixa": True} if fixa else {})})
    return saida


def formatar(mensagens: list[dict[str, str]]) -> list[dict[str, object]]:
    saida: list[dict[str, object]] = []
    for mensagem in mensagens:
        if mensagem["tipo"] == "midia":
            saida.append({"tipo": "midia", "chave": mensagem.get("chave", ""), "espera_s": 2.0,
                          **({"url": mensagem["url"]} if mensagem.get("url") else {})})
            continue
        for parte in dividir(limpar(mensagem["texto"])):
            if not tem_conteudo(parte):
                continue                                  # sobra sem nenhuma letra (só aspas, chaves): não vai
            saida.append({"tipo": "texto", "texto": parte, "espera_s": tempo_de_digitacao(parte)})
    return saida
