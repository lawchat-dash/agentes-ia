"""Formatador: deixa o texto com cara de WhatsApp e calcula a pausa antes de cada envio."""

from __future__ import annotations

import re

LIMITE_POR_MENSAGEM = 320


def limpar(texto: str) -> str:
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
    """Parte que não se junta a outra: mídia, link (fica sozinho para o WhatsApp mostrar a prévia) e a pergunta final."""
    if parte.get("tipo") != "texto":
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


def formatar(mensagens: list[dict[str, str]]) -> list[dict[str, object]]:
    saida: list[dict[str, object]] = []
    for mensagem in mensagens:
        if mensagem["tipo"] == "midia":
            saida.append({"tipo": "midia", "chave": mensagem.get("chave", ""), "espera_s": 2.0,
                          **({"url": mensagem["url"]} if mensagem.get("url") else {})})
            continue
        for parte in dividir(limpar(mensagem["texto"])):
            saida.append({"tipo": "texto", "texto": parte, "espera_s": tempo_de_digitacao(parte)})
    return saida
