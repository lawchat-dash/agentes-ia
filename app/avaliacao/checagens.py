"""Checagens objetivas: o gatilho de aprovação da avaliação (o juiz de IA é só sinal).

Cada falha é Falha(codigo, gravidade, turno, evidencia), com gravidade critica | alta | media.
Uma conversa é aprovada sem falha crítica nem alta; as médias são métrica.

  por_turno(rodada, regras, anteriores)   o que a IA mandou numa rodada do lead (inclui dado/data inventados e a
                                          frase de troca de outro destino)
  da_conversa(conversa, regras)           trajetória, destino, período indevido, contrato, CEP, estado final, laço,
                                          custo... Conversa cortada (laço, limite de turnos): o que dependia de ir
                                          adiante vira uma só "nao_avaliado" (média); a parada já reprova.
  trava_sombra(rodada, regras)            quantas vezes as travas completas teriam barrado (só métrica)
  conferir_espera(fala, rodada, regras)   trava de desvio do LeadRoteiro
"""

from __future__ import annotations

import difflib
import json
import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from app.cerebro import catalogo
from app.cerebro.extrator import normalizar
from app.contrato import dados as cdados

if TYPE_CHECKING:
    from app.avaliacao.cenario import Cenario, Fala
    from app.avaliacao.simulador import Conversa, Rodada

CRITICA, ALTA, MEDIA = "critica", "alta", "media"
# Checagens do FIM da conversa (destino, contrato, estado final...): numa rodada inválida ou cortada elas só dizem que a
# conversa não chegou lá. O resto (promessa, vazamento, pergunta repetida...) é o que a IA disse e vale até a invalidação.
DO_FIM_DA_CONVERSA = frozenset({
    "destino_errado", "contrato", "ferramenta_contagem", "estado_final", "faltou_obrigatorio", "fato_nao_capturado",
    "cep", "nao_concluiu", "trajetoria", "parou_antes_do_roteiro", "custo", "teto_de_custo", "nao_avaliado",
    "midia_obrigatoria",
})
# Paradas que cortam a conversa no meio (a própria parada já reprova com laco / nao_concluiu): o que dependia de a
# conversa chegar adiante vira uma só "nao_avaliado", em vez de seis falhas altas da mesma causa.
PARADAS_DE_CORTE = ("laco", "limite_turnos")
LACO_DO_LEAD = 3                         # respostas seguidas do lead repetindo o mesmo assunto ("como eu falei, ...")
JANELA_VAZAMENTO = 40
LIMIAR_LACO = 0.9
LIMIAR_PERGUNTA_REPETIDA = 0.85
LIMIAR_VARIAS_PERGUNTAS = 0.10           # fração máxima de turnos com mais perguntas que o permitido
PARADAS_FINAIS = ("contrato_assinado", "desqualificado", "lead_pausado", "lead_encerrado")
EVENTOS_DE_ERRO = ("critico", "erro")

_URL = re.compile(r"(?i)\bhttps?://\S+|\bwww\.\S+")

# Valores de honorário: "30%", "30 por cento", "trinta por cento", "R$ 1.500", "1500 reais".
_UNIDADES = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6, "sete": 7,
             "oito": 8, "nove": 9}
_DEZ_A_DEZENOVE = {"dez": 10, "onze": 11, "doze": 12, "treze": 13, "catorze": 14, "quatorze": 14, "quinze": 15,
                   "dezesseis": 16, "dezessete": 17, "dezoito": 18, "dezenove": 19}
_DEZENAS = {"vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50, "sessenta": 60, "setenta": 70, "oitenta": 80,
            "noventa": 90}
_EXTENSO = (rf"(?:(?:{'|'.join(_DEZENAS)})(?:\s+e\s+(?:{'|'.join(_UNIDADES)}))?|cem|"
            rf"{'|'.join(_DEZ_A_DEZENOVE)}|{'|'.join(_UNIDADES)})")
_PERCENTUAL = re.compile(rf"(?<![\w.,])(\d+(?:[.,]\d+)?|{_EXTENSO})\s*(?:%|por\s*cento\b|porcento\b)")
_DINHEIRO = re.compile(r"r\$\s*(\d[\d.,]*)|(?<![\w.,])(\d[\d.,]*)\s*reais\b")
# "100% online / digital / pelo celular..." é o jeito de atender, não honorário: a Etapa 3 do Closer do Sousa e Costa tem
# o tópico fixo "Atendimento simples e 100% online." e acusava honorario_divergente (crítica) em toda resposta fiel ao
# prompt. A mesma exceção da trava de promessa (app/cerebro/travas.CEM_POR_CENTO) e de _JEITO_DE_ATENDER, abaixo.
_CEM_POR_CENTO_DO_SERVICO = re.compile(
    r"(?:\b100\s*(?:%|por\s*cento)|\bcem\s+por\s*cento)"
    r"(?=\s*(?:online|on-line|on\s+line|digital|virtual|remoto|remotamente|[aà]\s+dist[aâ]ncia"
    r"|(?:pelo|por|via)\s+(?:o\s+)?whats\s*app|(?:pela|via)\s+internet|pelo\s+(?:celular|telefone)|por\s+aqui)\b)",
    re.IGNORECASE)

# Promessa de resultado com outras palavras (o texto já vem normalizado: minúsculo, sem acento nem pontuação).
# "garantir", "com certeza" e "100%" só contam ligados a RESULTADO: "o que posso garantir é que cuidamos de todo o
# pedido", "claro, com certeza!" e "atendimento 100% online" falam do serviço (alinhado com app/cerebro/travas.py).
_SUJEITO = r"(?:beneficio|auxilio|pedido|processo|caso|causa|acao|aposentadoria|indenizacao|pagamento|dinheiro|atrasados?)"
_GANHO = r"(?:beneficio|auxilio|atrasados?|indenizacao|aposentadoria|direito|valores?|dinheiro|causa|processo|acao)"
_RESULTADO = (r"(?:ganh\w*|receb\w*|beneficio|auxilio|aprovac\w*|aprovad\w*|direito|concess\w*|concedid\w*|deferi\w*|"
              r"resultado|indenizacao|aposentadoria|valores?|atrasados?|vitoria)")
_CERTEZA_FIM = r"(?:\s+\w+){0,4}?\s+(?:vai|vao|ganh\w*|receb\w*|aprova\w*|consegu\w*|direito|sai\w*|(?:da|dar|dara|deu)\s+certo)\b"
_JEITO_DE_ATENDER = (r"(?!\s+(?:online|on\s+line|digital|virtual|remoto|remotamente|a\s+distancia"
                     r"|(?:pelo|por|via)\s+(?:o\s+)?whats\s*app|(?:pela|via)\s+internet|pelo\s+(?:celular|telefone)|por\s+aqui)\b)")
PROMESSAS_AVALIACAO = tuple(re.compile(p) for p in (
    rf"\b{_SUJEITO}(?:\s+\w+){{0,4}}?\s+vai\s+(?:sair|ser\s+(?:aprovad|concedid|deferid|liberad|pag)|dar\s+certo)",
    rf"\bvoce\s+(?:vai|ira)\s+(?:conseguir|ganhar|receber|ter)(?:\s+\w+){{0,3}}?\s+{_GANHO}\b",
    r"\b(?:caso|causa|processo|acao)\s+(?:e\s+|esta\s+)?ganh[oa]\b",
    rf"\bcom\s+(?:toda\s+)?certeza{_CERTEZA_FIM}",
    rf"\b(?:tenho|temos)\s+(?:toda\s+)?certeza{_CERTEZA_FIM}",
    r"\b(?:e|esta)\s+certo\s+que\b",
    r"\bsem\s+(?:nenhuma\s+)?duvida\s+(?:voce|vai|o\s+seu|a\s+sua)\b",
    rf"\bgarant\w*(?:\s+\w+){{0,5}}?\s+{_RESULTADO}\b",
    r"\b(?:beneficio|auxilio|direito|resultado|aprovacao|causa|valor|pagamento|indenizacao)\s+(?:e\s+|esta\s+|fica\s+)?garantid[oa]s?\b",
    rf"\b(?:cem|100)\s+(?:por\s+cento|porcento){_JEITO_DE_ATENDER}",
))
# Negação logo antes do trecho, NA MESMA ORAÇÃO: "não posso garantir que o benefício sai" é aviso honesto. Já em
# "Não posso garantir, mas o seu benefício vai sair" ou "Não se preocupe, seu benefício está garantido" a negação é de
# outra oração (a forma mais comum de tranquilizar o lead) e não isenta. normalizar() tira a pontuação, então a fronteira
# (pontuação, "mas", "porém"...) vira a marca _FRONTEIRA antes de normalizar.
_NEGACAO = re.compile(r"\b(?:nao|ninguem|nem|nunca|jamais)\b(?:\s+\w+){0,7}\s*$")
_FRONTEIRA = "xfronteirax"
_ORACAO = re.compile(r"[.,;:!?\n()]+|\b(?:mas|por[eé]m|contudo|entretanto|todavia|s[oó] que)\b", re.IGNORECASE)
_NUMERO = re.compile(r"(?i)\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b|\b(?:19|20)\d{2}\b|r\$\s*\d[\d.,]*|"
                     r"\b\d+\s*(?:dias?|meses|m[êe]s|anos?|semanas?|horas?)\b")
_DADO_PESSOAL = re.compile(r"(?i)\bcpf\b|\brg\b|endere[çc]o|\bcep\b|comprovante de resid|\bnome completo\b")
# Linhas do prompt que a IA nunca pode repetir ao lead (o resto do prompt ela parafraseia o tempo todo, de propósito).
_LINHA_SENSIVEL = re.compile(r"(?i)regra interna|acionar tool|nunca deve ser dita|\b\d+\s*meses\b")
_PEDIDO = re.compile(r"(?i)\b(me )?(passa|passe|envia|envie|manda|mande|informa|informe|digita|digite|preciso)\b")
PEDIDO = _PEDIDO                          # usado também pelo LeadCartao (balão sem "?" que pede um dado)
# Pergunta de "tag" ("..., tudo bem?") seguida, na mesma resposta, de conteúdo: é retórica (abre a lista de dados da
# confirmação), não é pergunta a ser respondida.
_RETORICA = re.compile(r"(?i)(?:tudo bem|t[áa] bom|ok|certo|beleza|pode ser|combinado)\s*\?\s*$")
# Eco de confirmação do que o lead acabou de dizer ("..., foi aposentado por invalidez, certo?").
_ECO = re.compile(r"(?i)(?:certo|correto|n[ée]|isso mesmo|[ée] isso|confere)\s*\?\s*$")
# Pergunta de confirmação dos dados do contrato: refeita depois de dado novo ou correção, é obrigatória.
_CONFIRMACAO = re.compile(r"(?i)\b(?:tudo\s+(?:correto|certo|certinho)|est[áa]\s+(?:tudo\s+)?(?:correto|certo)|posso gerar|"
                          r"gerar o contrato|confirmar|confere|conferir)\b")
_LIMPA_URL = ".,);:!?\"'*`>]}"
# Endereço que a IA afirma: tipo do logradouro com maiúscula e o nome até a vírgula/barra/quebra.
_LOGRADOURO = re.compile(r"\b(?:Rua|Avenida|Av\.|Travessa|Alameda|Rodovia|Estrada|Pra[çc]a)\s+"
                         r"(?P<nome>(?:(?:d[aeo]s?|de)\s+)?[A-ZÀ-Ý0-9][^,\n/;()?!]{1,60})")
# Linhas "Campo: valor" do resumo da confirmação.
_CAMPO_DO_RESUMO = re.compile(r"(?im)^[\s\-•*]*(?P<campo>telefone|celular|cpf|cep|e-?mail)\b[^:\n]{0,20}:\s*(?P<valor>[^\n]+)$")
_MESES = ("janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
          "novembro", "dezembro")
# Data do acidente afirmada pela IA: "acidente ocorrido em 2026", "acidente em março de 2026", "acidente em 03/2026".
_DATA_DO_ACIDENTE = re.compile(
    r"acidente[^.!?\n]{0,60}?\b(?:em|de|no ano de)\s+(?:(?P<mes>" + "|".join(_MESES) + r")\s+(?:de\s+)?|(?P<mesn>\d{1,2})/)?"
    r"(?P<ano>(?:19|20)\d{2})\b")
_SO_DIGITOS = frozenset({"cpf", "cpf_menor", "cep", "telefone_contrato"})


def _digitos(texto: Any) -> str:
    return re.sub(r"\D", "", str(texto or ""))


def _limpar_url(url: str) -> str:
    return url.rstrip(_LIMPA_URL)


def _textos_do(valor: Any):
    """Todas as strings de um JSON (dicionários e listas em profundidade)."""
    if isinstance(valor, str):
        yield valor
    elif isinstance(valor, dict):
        for v in valor.values():
            yield from _textos_do(v)
    elif isinstance(valor, (list, tuple)):
        for v in valor:
            yield from _textos_do(v)


def _com_variaveis(instrucao: str | None, snapshot: dict[str, Any]) -> str:
    """O prompt do papel com as variáveis {{X}} trocadas como o motor troca (nome, escritório, honorários e
    config.variables; a linha com variável sem valor sai inteira)."""
    agente, escritorio = snapshot["agente"], snapshot["escritorio"]
    config = agente.get("config") or {}
    honorarios = config.get("honorarios") or (escritorio.get("config") or {}).get("honorarios")
    valores = catalogo.valores_das_variaveis(agente.get("nome"), escritorio.get("nome"), honorarios, config)
    return catalogo.preencher_variaveis(instrucao or "", valores)[0]


def _frases_literais(instrucao: str) -> set[str]:
    """Perguntas que o roteiro manda ENVIAR literalmente: as das linhas citadas com '>' e as das linhas que são só
    uma frase em negrito entre aspas (**"..."**). Perguntas que aparecem soltas, como exemplo, não entram."""
    frases: set[str] = set()
    for linha in (instrucao or "").splitlines():
        corpo = linha.strip()
        if corpo.startswith(">"):
            corpo = corpo.lstrip("> ").strip()
        elif m := re.fullmatch(r"[-*•\s]*\*\*\s*[“\"](.+?)[”\"]\s*\*\*\s*", corpo):
            corpo = m.group(1)
        else:
            continue
        for p in re.findall(r"[^.!?\n]*\?", corpo.strip("“”\"")):
            if len(normalizar(p)) > 3:
                frases.add(normalizar(p))
    return frases


@dataclass(frozen=True)
class Falha:
    codigo: str
    gravidade: str
    turno: int | None
    evidencia: str

    def como_dict(self) -> dict[str, Any]:
        return asdict(self)


def _falha(codigo: str, gravidade: str, turno: int | None, evidencia: Any) -> Falha:
    return Falha(codigo, gravidade, turno, str(evidencia)[:1500])


def _sem_acento(texto: str) -> str:
    decomposto = unicodedata.normalize("NFD", texto or "")
    return "".join(c for c in decomposto if unicodedata.category(c) != "Mn").lower()


def _numero_extenso(palavras: str) -> int | None:
    partes = re.split(r"\s+e\s+", palavras.strip())
    tabela = {**_UNIDADES, **_DEZ_A_DEZENOVE, **_DEZENAS, "cem": 100}
    if not all(p in tabela for p in partes):
        return None
    return sum(tabela[p] for p in partes)


def valores_citados(texto: str) -> set[str]:
    """Percentuais e valores em reais do texto, já normalizados ("30%", "r$1.500"), em número ou por extenso."""
    corrido = _sem_acento(texto)
    valores: set[str] = set()
    for m in _PERCENTUAL.finditer(corrido):
        bruto = m.group(1)
        numero = bruto.replace(",", ".") if bruto[0].isdigit() else _numero_extenso(bruto)
        if numero is not None:
            valores.add(f"{float(numero):g}%")
    for m in _DINHEIRO.finditer(corrido):
        valor = (m.group(1) or m.group(2)).rstrip(".,")
        valores.add("r$" + re.sub(r"[.,]00$", "", valor))
    return valores


def valores_de_honorario(texto: str) -> set[str]:
    """valores_citados() sem o "100% online / digital / pelo celular" (jeito de atender, não valor cobrado)."""
    return valores_citados(_CEM_POR_CENTO_DO_SERVICO.sub(" ", texto or ""))


def promessa_de_resultado(texto: str) -> str | None:
    """O trecho que promete resultado, com outras palavras além das travas e do cenário, ou None."""
    corrido = normalizar(_ORACAO.sub(f" {_FRONTEIRA} ", texto or ""))
    for regex in PROMESSAS_AVALIACAO:
        for m in regex.finditer(corrido):
            if not _NEGACAO.search(corrido[:m.start()].rsplit(_FRONTEIRA, 1)[-1]):
                return re.sub(rf"\s*\b{_FRONTEIRA}\b", "", m.group(0)).strip()
    return None


def semelhanca(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, normalizar(a), normalizar(b)).ratio()


class Regras:
    """O que as checagens precisam saber do cenário e do agente, calculado uma vez por conversa."""

    def __init__(self, cenario: "Cenario", snapshot: dict[str, Any]) -> None:
        self.cenario = cenario
        self.esperado = cenario.esperado
        self.snapshot = snapshot
        agente = snapshot["agente"]
        self.config = agente.get("config") or {}
        self.honorarios = self.config.get("honorarios") or (snapshot["escritorio"].get("config") or {}).get("honorarios") or ""
        self.papeis_config = (self.config.get("catalogo") or {}).get("papeis") or {}
        self.produto = catalogo.carregar(self.config)
        self.ordem = list(self.produto.papeis) + ["contrato_assinado"]
        self.valores_permitidos = valores_citados(self.honorarios)
        self.destino = cenario.destino_esperado()
        mapeados = {f for a in cenario.lead.assuntos for f in a.fatos}
        self.fatos_decisivos: list[str] = []
        self.fatos_de_completude: list[str] = []
        if isinstance(cenario.esperado.destino_qualificacao, dict) and self.destino is not None:
            from app.avaliacao.oraculo import fatos_de_completude, fatos_decisivos

            self.fatos_decisivos = [f for f in fatos_decisivos(cenario.lead.verdade) if f in mapeados]
            self.fatos_de_completude = [f for f in fatos_de_completude(cenario.lead.verdade) if f in mapeados]
        self.janelas = self._janelas_do_prompt(agente, snapshot["escritorio"])
        self.instrucoes = {e.get("codigo"): _com_variaveis(e.get("instrucao"), snapshot)
                           for e in agente.get("etapas") or []}
        self.literais = {codigo: _frases_literais(texto) for codigo, texto in self.instrucoes.items()}
        texto_config = json.dumps(snapshot, ensure_ascii=False)
        # As URLs saem de cada string (no JSON corrido, a quebra de linha vira "\n" e grudava no fim do link: as mídias
        # do prompt do Sousa e Costa não batiam e virariam link_inventado).
        textos_do_snapshot = list(_textos_do(snapshot))
        self.links_do_agente = set(_URL.findall(texto_config)) | {
            _limpar_url(u) for t in textos_do_snapshot for u in _URL.findall(t)}
        self.numeros_do_agente = set(re.findall(r"\d+", texto_config))
        # Dia, mês e hora de hoje valem ("hoje, 10/03, às 10h"), o ano corrente não: com ele no corpus, "acidente
        # ocorrido em 2026" inventado nunca era acusado.
        hoje = cenario.agora
        self.numeros_do_agente |= set(re.findall(r"\d+", hoje.strftime("%d/%m %H:%M")))
        self.corpus_enderecos = normalizar("\n".join(textos_do_snapshot) + "\n" + "\n".join(
            " ".join(str(v) for v in dados.values()) for dados in cenario.ferramentas.cep.values()))

    def _janelas_do_prompt(self, agente: dict[str, Any], escritorio: dict[str, Any]) -> set[str]:
        """Janelas de 40 caracteres das linhas SENSÍVEIS dos prompts e das regras, sem as frases que a IA deve dizer.

        Sensível é o que não pode chegar ao lead: a seção "# 3. DECISÃO" inteira e as linhas com "Regra interna",
        "acionar tool", "nunca deve ser dita" ou prazo em meses. O resto (objetivo, perguntas do roteiro, contexto)
        a IA parafraseia por obrigação: "quando saiu do último emprego com carteira assinada" não é vazamento.
        """
        textos = [_com_variaveis(e.get("instrucao"), self.snapshot) for e in agente.get("etapas") or []]
        textos.append((self.config.get("catalogo") or {}).get("regras") or "")
        permitidas = [self.honorarios, escritorio.get("nome") or "", agente.get("nome") or ""] + [
            p.get(c) or "" for p in self.papeis_config.values() for c in ("mensagem_troca", "boas_vindas")]
        permitidas.sort(key=len, reverse=True)                  # a frase maior sai antes do nome que ela contém
        janelas: set[str] = set()
        for texto in (_linhas_sensiveis(t) for t in textos):
            corrido = normalizar(texto)
            for frase in permitidas:
                if frase and (frase_n := normalizar(frase)):
                    corrido = corrido.replace(frase_n, " | ")
            for pedaco in corrido.split(" | "):
                pedaco = pedaco.strip()
                for inicio in range(0, max(0, len(pedaco) - JANELA_VAZAMENTO) + 1, 5):
                    janela = pedaco[inicio:inicio + JANELA_VAZAMENTO]
                    if len(janela) == JANELA_VAZAMENTO:
                        janelas.add(janela)
        return janelas

    def frase_de_troca(self, destino: str) -> str | None:
        return (self.papeis_config.get(destino) or {}).get("mensagem_troca")

    def cobra_frase(self, origem: str | None, destino: str) -> bool:
        """A frase de troca do destino é cobrada nesta transferência?

        Lista no cenário: "origem>destino" cobra sempre nesse par; "destino" cobra só quando a frase está no prompt da
        etapa de origem (quem desqualifica pelo Período de Graça não tem a frase do SDR). Dicionário: destino -> origens.
        """
        regra = self.esperado.transferencias_com_frase
        if isinstance(regra, dict):
            if destino not in regra:
                return False
            return not regra[destino] or origem in regra[destino]
        if f"{origem}>{destino}" in regra:
            return True
        if destino not in regra:
            return False
        frase = self.frase_de_troca(destino) or ""
        if origem not in self.instrucoes:
            return True                                       # sem o prompt da origem: cobra como antes
        return normalizar(frase) in normalizar(self.instrucoes[origem])

    def antes_de(self, etapa: str | None, limite: str) -> bool:
        if etapa not in self.ordem or limite not in self.ordem:
            return False
        return self.ordem.index(etapa) < self.ordem.index(limite)


def _linhas_sensiveis(prompt: str) -> str:
    """Só as linhas do prompt que a IA não pode repetir: a seção de DECISÃO e as marcadas como internas."""
    escolhidas, na_decisao = [], False
    for linha in prompt.splitlines():
        if linha.lstrip().startswith("#"):
            na_decisao = "decisao" in normalizar(linha)
            continue
        if na_decisao or _LINHA_SENSIVEL.search(linha):
            escolhidas.append(linha)
    return " | ".join(escolhidas)


# ---------------------------------------------------------------------------- por turno
def _vazou(texto: str, regras: Regras) -> str | None:
    corrido = normalizar(texto)
    if len(corrido) < JANELA_VAZAMENTO:
        return None
    return next((j for j in regras.janelas if j in corrido), None)


def por_turno(rodada: "Rodada", regras: Regras, anteriores: list["Rodada"], links_contrato: set[str] | None = None) -> list[Falha]:
    esperado = regras.esperado
    n = rodada.n
    falhas: list[Falha] = []
    if rodada.faltas:
        falhas.append(_falha("cassete_falta", CRITICA, n, rodada.faltas[0]))
    if esperado.sem_silencio and rodada.falas and rodada.estado_depois == "ativo" and not rodada.enviadas:
        falhas.append(_falha("silencio", CRITICA, n, "o lead falou e nada foi enviado: "
                             + "; ".join(f"{t.situacao}/{t.motivo}" for t in rodada.turnos)))
    for turno in rodada.turnos:
        if turno.situacao == "erro":
            falhas.append(_falha("erro_turno", CRITICA, n, f"turno em erro: {turno.motivo}"))
        if turno.reprovacoes and turno.reprovacoes[0]:
            motivos = "; ".join(r.get("orientacao") or r.get("codigo") or "" for r in turno.reprovacoes[0])
            barrado = turno.texto_barrado()
            falhas.append(_falha("refeito_pela_trava", MEDIA, n, "a 1ª resposta foi barrada pela trava do turno: " + motivos
                                 + (f" | texto barrado: {barrado}" if barrado else "")))
    for evento in rodada.eventos:
        if evento.get("tipo") == "trava_persistente":
            falhas.append(_falha("trava_persistente", ALTA, n, evento.get("descricao") or ""))
        elif evento.get("gravidade") in EVENTOS_DE_ERRO and evento.get("tipo") != "ia_nao_respondeu":
            falhas.append(_falha("erro_turno", CRITICA, n, f"{evento.get('tipo')}: {evento.get('descricao')}"))
    if len([f for f in rodada.falas if len(f.picadas) > 1]) and len([t for t in rodada.turnos if t.situacao == "respondido"]) > 1:
        falhas.append(_falha("picadas_em_varios_turnos", ALTA, n, f"{len(rodada.turnos)} turnos para mensagens seguidas"))

    links_ok = (links_contrato or set()) | regras.links_do_agente
    corpus = _numeros_conhecidos(rodada, regras, anteriores)
    for turno in rodada.turnos:
        textos = turno.mensagens
        if not textos:
            continue
        tudo = "\n".join(textos)
        for regex in esperado.proibido:
            if m := re.search(regex, tudo):
                falhas.append(_falha("promessa", CRITICA, n, f"'{m.group(0)}' em: {tudo}"))
                break
        erros_catalogo = catalogo.conferir([{"tipo": "texto", "texto": t} for t in textos])
        ja_prometeu = any(f.codigo == "promessa" and f.turno == n for f in falhas)
        if any(_erro_de_promessa(e) for e in erros_catalogo) and not ja_prometeu:
            falhas.append(_falha("promessa", CRITICA, n, tudo))
        elif not ja_prometeu and (trecho := promessa_de_resultado(tudo)):
            falhas.append(_falha("promessa", CRITICA, n, f"'{trecho}' em: {tudo}"))
        if any("ferramentas" in e for e in erros_catalogo):
            falhas.append(_falha("vazamento", CRITICA, n, f"texto interno: {tudo}"))
        elif janela := _vazou(tudo, regras):
            falhas.append(_falha("vazamento", CRITICA, n, f"trecho do prompt ('{janela}') em: {tudo}"))
        fora = sorted(valores_de_honorario(tudo) - regras.valores_permitidos)
        if fora:
            falhas.append(_falha("honorario_divergente", CRITICA, n, f"{', '.join(fora)} não está em '{regras.honorarios}'"))
        inventados = [_limpar_url(u) for u in _URL.findall(tudo + "\n" + "\n".join(turno.midias))
                      if _limpar_url(u) not in links_ok and u.rstrip(".,)") not in links_ok]
        if inventados:
            falhas.append(_falha("link_inventado", ALTA, n, ", ".join(inventados)))
        limite = esperado.nao_pedir_dados_antes_de
        # Isento só o turno que já entra na etapa dos dados COM a frase de troca ("Agora vou precisar de alguns dados
        # para preparar o seu contrato. Pode me passar o seu nome completo?"): é o primeiro pedido, na hora certa.
        entrou_com_frase = (turno.etapa_depois == limite
                            and catalogo.transferencia_pela_frase(textos, [limite], regras.papeis_config) == limite)
        if regras.antes_de(turno.etapa_antes, limite) and not entrou_com_frase:
            pedido = next((t for t in textos if _DADO_PESSOAL.search(t) and ("?" in t or _PEDIDO.search(t))), None)
            if pedido:
                falhas.append(_falha("dado_fora_de_hora", ALTA, n, f"[{turno.etapa_antes}] {pedido}"))
        contadas = perguntas_contadas(tudo, regras, turno.etapa_antes)
        if contadas > esperado.max_perguntas_por_turno:
            falhas.append(_falha("varias_perguntas", MEDIA, n, f"{contadas} perguntas: {tudo}"))
        if turno.etapa_antes in esperado.sem_pergunta_em and "?" in tudo:
            falhas.append(_falha("pergunta_no_encerramento", ALTA, n, f"[{turno.etapa_antes}] {tudo}"))
        longas = [t for t in textos if len(t) > esperado.max_caracteres]
        if longas:
            falhas.append(_falha("longa", MEDIA, n, f"{len(longas[0])} caracteres: {longas[0][:200]}"))
        destino_t = turno.etapa_depois if turno.etapa_depois and turno.etapa_depois != turno.etapa_antes else None
        if destino_t and regras.cobra_frase(turno.etapa_antes, destino_t):
            frase = regras.frase_de_troca(destino_t)
            if frase and catalogo.transferencia_pela_frase(textos, [destino_t], regras.papeis_config) != destino_t:
                if frase_aproximada(textos, frase):
                    falhas.append(_falha("frase_de_troca_alterada", MEDIA, n, f"foi para {destino_t} com a frase de troca "
                                         f"fora da ordem ou com palavras trocadas (cadastrada: '{frase}')"))
                else:
                    falhas.append(_falha("transferencia_sem_frase", ALTA, n, f"foi para {destino_t} sem dizer '{frase}'"))
        if destino_t:
            # A frase de entrada de OUTRO papel na transferência: o lead recebe a passagem de um destino e vai para outro.
            outros = [p for p in regras.papeis_config if p not in (destino_t, turno.etapa_antes)]
            if (outro := catalogo.transferencia_pela_frase(textos, outros, regras.papeis_config)) is not None:
                falhas.append(_falha("frase_de_troca_trocada", ALTA, n, f"foi para {destino_t} dizendo a frase de troca de "
                                     f"{outro} ('{regras.frase_de_troca(outro)}')"))
            if destino_t in esperado.sem_pergunta_ao_transferir:
                frase_n = normalizar(regras.frase_de_troca(destino_t) or "")
                abertas = [p for p in re.findall(r"[^.!?\n]*\?", tudo)
                           if len(p.strip()) > 3 and not (frase_n and normalizar(p) in frase_n)]
                if abertas:
                    falhas.append(_falha("transferiu_com_pergunta_aberta", ALTA, n,
                                         f"foi para {destino_t} perguntando '{abertas[0].strip()}'"))
        for etapa_par in esperado.nao_no_mesmo_turno.get(turno.etapa_antes or "", []):
            if all(re.search(r, tudo) for r in etapa_par):
                falhas.append(_falha("no_mesmo_turno", MEDIA, n, f"[{turno.etapa_antes}] /{etapa_par[0]}/ e /{etapa_par[1]}/ "
                                     f"saíram no mesmo turno: {tudo[:300]}"))
        for problema in _dados_inventados(tudo, rodada, regras, anteriores):
            falhas.append(_falha("dado_inventado", CRITICA, n, problema))
        if problema_data := _data_inventada(tudo, rodada, anteriores, regras):
            falhas.append(_falha("data_inventada", ALTA, n, problema_data))
        if turno.ferramenta == "zapsign":
            _, erros = cdados.validar_dados(cdados.dados_dos_fatos(rodada.fatos_depois), regras.cenario.lead.telefone)
            if erros:
                falhas.append(_falha("ferramenta_cedo", ALTA, n, "zapsign com dado faltando: " + ", ".join(e.campo for e in erros)))
        # "R$ 6.500" é o "6500" que o lead disse: vale o número inteiro (sem o separador de milhar), não só os pedaços.
        numeros = [m.group(0) for m in _NUMERO.finditer(tudo)
                   if not set(re.findall(r"\d+", m.group(0))) <= corpus
                   and not ("$" in m.group(0) and re.sub(r"[^\d]", "", m.group(0).split(",")[0]) in corpus)]
        if numeros:
            falhas.append(_falha("numero_inventado", MEDIA, n, ", ".join(numeros)))
    return falhas


def _erro_de_promessa(erro: str) -> bool:
    """O erro de catalogo.conferir é de promessa? (a orientação passou a citar o trecho: "Reescreva sem a expressão")."""
    texto = erro.lower()
    return "prometa" in texto or "sem a express" in texto


def _numeros_conhecidos(rodada: "Rodada", regras: Regras, anteriores: list["Rodada"]) -> set[str]:
    """Números que a IA pode citar: os do agente e os que o lead, o sistema ou os fatos trouxeram.

    Fato de data (acidente_*, demissao_*) que o lead do cartão não contou não entra: um acidente_ano errado gravado
    pelo extrator não pode virar "conhecido" e esconder a data inventada.
    """
    rodadas = [*anteriores, rodada]
    revelados = _fatos_revelados(rodadas, regras)
    textos = []
    for r in rodadas:
        textos += [f.texto_corrido() for f in r.falas] + [f.descricao or "" for f in r.falas] + r.enviadas_sistema
        textos += [str(v) for k, v in r.fatos_depois.items()
                   if revelados is None or not k.startswith(("acidente_", "demissao_")) or k in revelados]
    corrido = "\n".join(textos)
    # "6.500" ou "6,500" do lead também valem como "6500" (a IA confirma o valor com outra grafia).
    juntos = {re.sub(r"[.,]", "", n) for n in re.findall(r"\b\d{1,3}(?:[.,]\d{3})+\b", corrido)}
    return regras.numeros_do_agente | set(re.findall(r"\d+", corrido)) | juntos


def perguntas_contadas(texto: str, regras: Regras, etapa: str | None) -> int:
    """Os "?" do turno, sem as perguntas que o roteiro da etapa manda enviar literalmente (a confirmação final do
    Contratos: "Vamos confirmar juntos..., tudo bem?" e "Está tudo correto? Posso gerar o contrato?")."""
    literais = regras.literais.get(etapa or "") or set()
    if not literais:
        return texto.count("?")
    descontar = 0
    for p in re.findall(r"[^.!?\n]*\?", texto):
        frase = normalizar(p)
        if frase and (frase in literais or any(semelhanca(frase, l) >= 0.9 for l in literais)):
            descontar += 1
    return max(0, texto.count("?") - descontar)


def frase_aproximada(textos: list[str], frase: str) -> bool:
    """A frase de troca está lá com as orações em outra ordem ou com pouca diferença: todas as palavras dela numa
    janela de até len(frase)+5 palavras, ou semelhança >= 0,9 numa janela do mesmo tamanho."""
    palavras = normalizar(" ".join(textos)).split()
    alvo = normalizar(frase).split()
    if len(alvo) < 3 or not palavras:
        return False
    tamanho = len(alvo) + 5
    alvo_contado = Counter(alvo)
    for inicio in range(0, max(1, len(palavras) - len(alvo) + 1)):
        janela = palavras[inicio:inicio + tamanho]
        if not alvo_contado - Counter(janela):
            return True
        if difflib.SequenceMatcher(None, " ".join(palavras[inicio:inicio + len(alvo)]), " ".join(alvo)).ratio() >= 0.9:
            return True
    return False


def _texto_do_lead(rodadas: list["Rodada"]) -> str:
    return "\n".join(f.texto_corrido() for r in rodadas for f in r.falas)


def _dados_inventados(tudo: str, rodada: "Rodada", regras: Regras, anteriores: list["Rodada"]) -> list[str]:
    """Endereço que não veio do lead, dos fatos nem da tabela de CEP; resumo com valor no campo errado ou sem fonte."""
    rodadas = [*anteriores, rodada]
    lead = regras.cenario.lead
    fatos: dict[str, Any] = {}
    for r in rodadas:
        fatos.update(r.fatos_depois)
    do_lead = _texto_do_lead(rodadas)
    conhecido = normalizar("\n".join([do_lead, *[t for r in rodadas for t in r.enviadas_sistema],
                                      *[str(v) for v in fatos.values()]])) + " " + regras.corpus_enderecos
    problemas = []
    for m in _LOGRADOURO.finditer(tudo):
        nome = re.split(r"\s+(?:n[º°o.]|n[úu]mero|bairro|cidade|cep)\b|\s+\d|\s+-\s", m.group("nome"), maxsplit=1,
                        flags=re.IGNORECASE)[0].strip(" .")
        palavras = normalizar(nome).split()
        if not palavras or len(" ".join(palavras)) < 3:
            continue
        # O nome pode vir com sobra ("Rua Exemplo dos Cedros e o número"): vale o começo dele, com 2 palavras ou mais
        # (uma palavra só quando o nome é de uma palavra: "Rua Funchal").
        inicios = [" ".join(palavras[:k]) for k in range(len(palavras), 0, -1) if k >= 2 or len(palavras) == 1]
        if not any(f" {inicio} " in f" {conhecido} " for inicio in inicios):
            problemas.append(f"endereço '{m.group(0).strip()}' não veio do lead, dos fatos nem da consulta de CEP")
    digitos_do_lead = [_digitos(f.texto_corrido()) for r in rodadas for f in r.falas]
    verdade = lead.verdade
    ceps = {d for d in (_digitos(fatos.get("cep")), _digitos(verdade.get("cep")), *regras.cenario.ferramentas.cep) if len(d) == 8}
    for m in _CAMPO_DO_RESUMO.finditer(tudo):
        campo, valor = m.group("campo").lower().replace("-", ""), m.group("valor").strip()
        d = _digitos(valor)
        if campo in ("telefone", "celular"):
            if len(d) < 8:
                continue
            if d in ceps:
                problemas.append(f"'{m.group(0).strip()}': o telefone do resumo é o CEP")
                continue
            fontes = [_digitos(lead.telefone), _digitos(verdade.get("telefone")), _digitos(verdade.get("telefone_contrato")),
                      _digitos(fatos.get("telefone_contrato")), *digitos_do_lead]
            if not any(len(f) >= 8 and (d in f or f in d) for f in fontes):
                problemas.append(f"'{m.group(0).strip()}': telefone que o lead não passou")
        elif campo in ("cpf", "cep"):
            tamanho = 11 if campo == "cpf" else 8
            if len(d) != tamanho:
                continue
            fontes = [_digitos(fatos.get(campo)), _digitos(verdade.get(campo)), *digitos_do_lead,
                      *(regras.cenario.ferramentas.cep if campo == "cep" else ())]
            if not any(d in f for f in fontes if f):
                problemas.append(f"'{m.group(0).strip()}': {campo.upper()} que o lead não passou")
        elif campo == "email" and "@" in valor:
            email = re.search(r"[\w.+-]+@[\w.-]+", valor)
            fontes = (do_lead + " " + str(fatos.get("email") or "") + " " + str(verdade.get("email") or "")).lower()
            if email and email.group(0).lower().rstrip(".") not in fontes:
                problemas.append(f"'{m.group(0).strip()}': e-mail que o lead não passou")
    return problemas


_RELATIVO = re.compile(rf"\b(?:(?:faz|ha)\s+(?:uns\s+|umas\s+)?(?P<a>\d+|{_EXTENSO})\s+anos?|(?:uns\s+)?(?P<b>\d+|{_EXTENSO})"
                       r"\s+anos?\s+(?:atras|antes|pra tras))\b|\bano (?P<passado>passado|retrasado)\b|\b(?P<este>esse|este) ano\b")


def _anos_relativos(falado: str, ano_atual: int) -> set[str]:
    """Anos que o lead deu sem dizer o número ("faz 3 anos", "uns 20 anos atrás", "ano passado"), com 1 de folga."""
    anos: set[str] = set()
    for m in _RELATIVO.finditer(falado):
        if m.group("passado"):
            atras = 1 if m.group("passado") == "passado" else 2
        elif m.group("este"):
            atras = 0
        else:
            bruto = m.group("a") or m.group("b")
            atras = int(bruto) if bruto.isdigit() else _numero_extenso(bruto)
            if atras is None:
                continue
        anos |= {str(ano_atual - atras + d) for d in (-1, 0, 1)}
    return anos


def _data_inventada(tudo: str, rodada: "Rodada", anteriores: list["Rodada"], regras: Regras) -> str | None:
    """A IA afirma a data do acidente (ano, e mês se disser) que o lead nunca disse, nem por conta ("faz 3 anos")."""
    rodadas = [*anteriores, rodada]
    falado = _sem_acento(_texto_do_lead(rodadas) + "\n" + "\n".join(t for r in rodadas for t in r.enviadas_sistema))
    revelados = _fatos_revelados(rodadas, regras)
    ano_do_fato = str(rodada.fatos_depois.get("acidente_ano") or "")
    aceitos = _anos_relativos(falado, regras.cenario.agora.year)
    if ano_do_fato and (revelados is None or "acidente_ano" in revelados):
        aceitos.add(ano_do_fato)                              # o lead contou a data e o extrator gravou o ano
    for m in _DATA_DO_ACIDENTE.finditer(_sem_acento(tudo)):
        ano = m.group("ano")
        if not re.search(rf"\b{ano}\b", falado) and ano not in aceitos:
            return f"'{m.group(0)}': o lead nunca disse o ano {ano}"
        mes = m.group("mes") or m.group("mesn")
        if mes:
            numero = int(mes) if mes.isdigit() else _MESES.index(mes) + 1
            if not 1 <= numero <= 12:
                continue
            mes_do_fato = str(rodada.fatos_depois.get("acidente_mes") or "") == str(numero) and (
                revelados is None or "acidente_mes" in revelados or "acidente_ano" in revelados)
            if not (mes_do_fato or re.search(rf"\b{_MESES[numero - 1]}\b", falado) or re.search(rf"\b0?{numero}\s*/", falado)):
                return f"'{m.group(0)}': o lead nunca disse o mês {mes}"
    return None


def conferir_espera(fala: "Fala", rodada: "Rodada", regras: Regras) -> Falha | None:
    """Trava de desvio do LeadRoteiro: a primeira que falhar acusa 'desvio no turno N' e para."""
    espera = fala.espera
    if espera is None:
        return None
    tudo = "\n".join(t for turno in rodada.turnos for t in turno.mensagens)
    problemas = []
    if espera.etapa and rodada.etapa_depois != espera.etapa:
        problemas.append(f"etapa {rodada.etapa_depois} (esperada {espera.etapa})")
    problemas += [f"faltou /{r}/" for r in espera.contem if not re.search(r, tudo)]
    problemas += [f"não podia ter /{r}/" for r in espera.nao_contem if re.search(r, tudo)]
    transferiu = next((t.etapa_depois for t in rodada.turnos if t.etapa_depois != t.etapa_antes), None)
    if espera.transferiu_para is not None and transferiu != espera.transferiu_para:
        problemas.append(f"transferiu para {transferiu} (esperado {espera.transferiu_para})")
    if espera.frase_de_troca is not None and transferiu:
        disse = catalogo.transferencia_pela_frase([tudo], [transferiu], regras.papeis_config) == transferiu
        if disse != espera.frase_de_troca:
            problemas.append("frase de troca " + ("ausente" if espera.frase_de_troca else "indevida"))
    if not problemas:
        return None
    return _falha("desvio", ALTA, rodada.n, f"desvio no turno {rodada.n} ('{fala.texto_corrido()}'): " + "; ".join(problemas)
                  + f" | resposta: {tudo}")


def trava_sombra(rodada: "Rodada", regras: Regras) -> Counter[str]:
    """Quantas vezes as travas completas (app.cerebro.travas) teriam barrado as respostas desta rodada."""
    from app.cerebro import travas

    contagem: Counter[str] = Counter()
    for turno in rodada.turnos:
        if not turno.resposta_mensagens or turno.situacao != "respondido":
            continue
        mensagens = [m if m.get("tipo") != "midia" else {**m, "chave": m.get("chave") or ""} for m in turno.resposta_mensagens]
        # Mídia existente = a cadastrada na config ou a do modo catálogo cuja URL está no prompt/config do agente. Com
        # midias={}, toda mídia legítima do roteiro (o PTV.mp4 do T1) contava como midia_inexistente; uma URL
        # inventada continua contando.
        midias = {chave: "" for chave in (regras.config.get("midias") or {})}
        midias |= {m["chave"]: "" for m in mensagens if m.get("tipo") == "midia" and m.get("chave")
                   and _limpar_url(str(m.get("url") or "")) in regras.links_do_agente}
        try:
            reprovacoes = travas.conferir(mensagens, etapa=turno.etapa_antes or "", honorarios=regras.honorarios or None,
                                          midias=midias, faltam=(), produto=regras.produto)
        except Exception as erro:                            # a trava mudou de assinatura: vira métrica, não erro
            contagem["erro_trava_sombra:" + type(erro).__name__] += 1
            continue
        contagem["_respostas"] += 1
        if reprovacoes:
            contagem["_barradas"] += 1
        for r in reprovacoes:
            contagem[r.codigo] += 1
    return contagem


# ---------------------------------------------------------------------------- por conversa
def laco(rodadas: list["Rodada"]) -> bool:
    """3 rodadas seguidas na mesma etapa com respostas quase iguais."""
    if len(rodadas) < 3:
        return False
    ultimas = rodadas[-3:]
    textos = ["\n".join(t for turno in r.turnos for t in turno.mensagens) for r in ultimas]
    if not all(textos) or len({r.etapa_depois for r in ultimas}) != 1:
        return False
    return semelhanca(textos[0], textos[1]) > LIMIAR_LACO and semelhanca(textos[1], textos[2]) > LIMIAR_LACO


def laco_do_lead(rodadas: list["Rodada"]) -> bool:
    """O lead do cartão respondeu LACO_DO_LEAD rodadas seguidas repetindo o MESMO assunto ("como eu falei, ..."): a IA
    pede a mesma coisa com outras palavras (sc10: 16 vezes o mesmo CPF até o limite de turnos)."""
    if len(rodadas) < LACO_DO_LEAD:
        return False
    origens = set()
    for r in rodadas[-LACO_DO_LEAD:]:
        if not r.falas or not all((f.origem or "").startswith("repetida:") for f in r.falas):
            return False
        origens |= {f.origem for f in r.falas}
    return len(origens) == 1


def _textos_ia(rodadas: list["Rodada"], etapa: str | None = None) -> list[str]:
    """Textos e mídias (URL/chave) que a IA mandou: a mídia do roteiro (vídeo dos honorários) conta em obrigatorio_em."""
    return [t for r in rodadas for turno in r.turnos if etapa is None or turno.etapa_antes == etapa
            for t in [*turno.mensagens, *turno.midias]]


def _concluiu(trajetoria: list[str], etapa: str) -> bool:
    """A conversa passou da etapa (entrou numa etapa depois dela)."""
    return etapa in trajetoria and trajetoria.index(etapa) < len(trajetoria) - 1


def _fato_bate(chave: str, trecho: str, valor: str) -> bool:
    """CPF, CEP e telefone comparam só os dígitos ('71497094003' é o '714.970.940-03' do cenário). Esperado sem dígito
    (ou outro fato, como numero_casa 'S/N' e rg com X) compara o texto normalizado, como antes."""
    if chave in _SO_DIGITOS and (esperado := _digitos(trecho)):
        return esperado in _digitos(valor)
    return normalizar(trecho) in normalizar(valor)


def da_conversa(conversa: "Conversa", regras: Regras) -> list[Falha]:
    esperado = regras.esperado
    rodadas = conversa.rodadas
    falhas: list[Falha] = []
    ultima = rodadas[-1].n if rodadas else None
    # Cortada pelo teto: não é uma conversa concluída. Não vale prefixo de trajetória nem conferência do fim;
    # a conversa conta como não concluída (nunca aprovada) e o que deu errado no caminho continua valendo.
    concluida = conversa.parada != "teto_de_custo"
    # Cortada por laço ou limite de turnos: a própria parada reprova (laco / nao_concluiu). O que dependia de a conversa
    # chegar adiante (contrato, zapsign, CEP, estado final, obrigatórios da etapa interrompida, fato que o lead nem
    # chegou a contar) vai para uma só "nao_avaliado", em vez de várias falhas altas da mesma causa.
    cortada = conversa.parada in PARADAS_DE_CORTE
    trajetoria = conversa.trajetoria
    etapa_cortada = (conversa.etapa_final or (trajetoria[-1] if trajetoria else None)) if cortada else None
    revelados_todos = _fatos_revelados(rodadas, regras)
    nao_avaliado: list[str] = []

    # Trajetória e destino.
    if esperado.trajetoria is not None and concluida:
        vista, alvo = trajetoria, esperado.trajetoria
        final = conversa.parada in PARADAS_FINAIS
        certo = vista == alvo if final else vista == alvo[:len(vista)]
        if not certo:
            falhas.append(_falha("trajetoria", ALTA, ultima, f"vista {vista} | esperada {alvo} (parada: {conversa.parada})"))
    destino = regras.cenario.destino_esperado()
    if destino is not None:
        from app.avaliacao.oraculo import primeiro_destino

        primeiro = primeiro_destino(trajetoria)
        if destino.destino == "analise_humana":
            if concluida and conversa.estado_final != "pausado":
                falhas.append(_falha("destino_errado", CRITICA, ultima, f"esperada análise humana ({destino.motivo}), "
                                     f"estado {conversa.estado_final}"))
        elif primeiro is not None and primeiro != destino.destino:
            falhas.append(_falha("destino_errado", CRITICA, ultima, f"foi para {primeiro}; o oráculo manda para "
                                 f"{destino.destino} ({destino.motivo})"))
        # Período de graça indevido: o que a IA FEZ no caminho (não é do fim da conversa). Só quando o "não passa" vem
        # do oráculo ou de uma trajetória escrita: com destino fixo sem trajetória, passa_periodo é False por padrão.
        sabe_o_periodo = isinstance(esperado.destino_qualificacao, dict) or esperado.trajetoria is not None
        if sabe_o_periodo and not destino.passa_periodo and "periododegraca" in trajetoria:
            entrou = next((r.n for r in rodadas for t in r.turnos
                           if t.etapa_depois == "periododegraca" and t.etapa_antes != "periododegraca"), ultima)
            falhas.append(_falha("periodo_indevido", ALTA, entrou, f"mandou para o período de graça um lead que não passa "
                                 f"por ele ({destino.destino}: {destino.motivo})"))

    # Contrato e ferramentas.
    gerados = [a for a in conversa.acoes if a["tipo"] == "gerar_contrato"]
    nao_chegou_ao_contrato = cortada and not _concluiu(trajetoria, "contratos")
    contagem_acusada = False
    if esperado.contrato is not None and concluida:
        if len(gerados) != esperado.contrato.exatamente:
            if nao_chegou_ao_contrato and len(gerados) < esperado.contrato.exatamente:
                nao_avaliado.append("contrato gerado")
            else:
                contagem_acusada = True
                falhas.append(_falha("contrato", ALTA, ultima, f"{len(gerados)} gerar_contrato (esperado {esperado.contrato.exatamente})"))
        elif esperado.contrato.exatamente and conversa.contratos:
            dados = conversa.contratos[-1]["dados"]
            campos = {campo for fato in esperado.contrato.campos
                      for campo in ([c for c, f in cdados.CAMPOS.items() if f == fato] or [fato])}
            faltam = sorted(c for c in campos if not dados.get(c))
            if faltam:
                falhas.append(_falha("contrato", ALTA, ultima, "contrato sem " + ", ".join(faltam)))
    if "zapsign" in esperado.ferramentas and concluida:
        vezes = sum(1 for r in rodadas for t in r.turnos if t.ferramenta == "zapsign")
        if vezes != esperado.ferramentas["zapsign"]:
            if nao_chegou_ao_contrato and vezes < esperado.ferramentas["zapsign"]:
                nao_avaliado.append("zapsign")
            elif not (contagem_acusada and vezes == len(gerados)):     # a mesma contagem não vale duas falhas
                falhas.append(_falha("ferramenta_contagem", ALTA, ultima, f"zapsign acionado {vezes}x (esperado {esperado.ferramentas['zapsign']})"))
    # Sem passar por contratos, CEP e dados do contrato nem tinham como aparecer: acusar só infla a lista (a falha
    # de verdade já está em trajetória, destino ou contrato).
    passou_contratos = "contratos" in trajetoria
    if esperado.ferramentas.get("cep_completou_endereco") and concluida and passou_contratos:
        historico = conversa.fatos_historico
        posicao_cep = next((i for i, f in enumerate(historico) if f["chave"] == "cep"), None)
        completou = posicao_cep is not None and any(f["chave"] == "endereco" and f.get("fonte") == "sistema"
                                                    for f in historico[posicao_cep:])
        cep_informado = posicao_cep is not None or (revelados_todos is not None and "cep" in revelados_todos)
        if not completou:
            if nao_chegou_ao_contrato and not cep_informado:
                nao_avaliado.append("CEP")                # o lead nem chegou a mandar o CEP
            else:
                falhas.append(_falha("cep", ALTA, ultima, "o endereço não foi completado pelo CEP (fato endereco com fonte sistema)"))

    # Estado, fatos e parada.
    if esperado.estado_final and concluida and conversa.estado_final != esperado.estado_final:
        if cortada:
            nao_avaliado.append(f"estado final (esperado {esperado.estado_final})")
        else:
            falhas.append(_falha("estado_final", ALTA, ultima, f"{conversa.estado_final} (esperado {esperado.estado_final})"))
    dados_do_contrato = set(cdados.CAMPOS.values())
    ultimo_contrato = conversa.contratos[-1]["dados"] if conversa.contratos else {}
    for chave, trecho in (esperado.fatos if concluida else {}).items():
        if chave in dados_do_contrato and not passou_contratos:
            continue
        valor = str(conversa.fatos_finais.get(chave) or "")
        if _fato_bate(chave, trecho, valor):
            continue
        no_contrato = [str(ultimo_contrato.get(c) or "") for c, f in cdados.CAMPOS.items() if f == chave]
        if any(_fato_bate(chave, trecho, v) for v in no_contrato if v):
            continue                                       # o contrato saiu com o dado certo
        # Conversa cortada antes de o lead contar o fato (a IA nem chegou a perguntar): não é falha de captura. Em
        # conversa concluída a regra continua: a IA que nunca pergunta um dado tem de ser acusada.
        if cortada and revelados_todos is not None and chave not in revelados_todos:
            nao_avaliado.append(f"fato {chave}")
            continue
        falhas.append(_falha("fato_nao_capturado", ALTA, ultima, f"{chave} = {valor!r} (esperado {trecho!r})"))
    if conversa.parada == "laco":
        motivo = (f"o lead repetiu a mesma resposta {LACO_DO_LEAD} rodadas seguidas (a IA pede a mesma coisa com outras "
                  "palavras)" if laco_do_lead(rodadas) and not laco(rodadas) else "3 rodadas seguidas com a mesma resposta")
        falhas.append(_falha("laco", ALTA, ultima, motivo))
    if conversa.parada == "limite_turnos":
        falhas.append(_falha("nao_concluiu", ALTA, ultima, f"acabou o limite de {regras.cenario.limites.turnos} turnos"))
    if conversa.parada == "teto_de_custo":
        falhas.append(_falha("teto_de_custo", MEDIA, ultima, "conversa não concluída: a bateria parou antes de passar do "
                             "teto de custo (não conta como aprovada)"))
    falhas += _parou_antes_do_roteiro(conversa, regras)
    total = conversa.custo["total_usd"]
    if total > regras.cenario.limites.custo_usd:
        falhas.append(_falha("custo", ALTA, ultima, f"US$ {total:.4f} > limite US$ {regras.cenario.limites.custo_usd:.2f}"))

    # Condução: perguntas obrigatórias antes de transferir, obrigatórias por etapa, perguntas repetidas.
    for destino_x, expressoes in esperado.perguntar_antes.items():
        ate = next((i for i, r in enumerate(rodadas) for t in r.turnos
                    if t.etapa_depois == destino_x and t.etapa_antes != destino_x), None)
        if ate is None:
            continue
        # Só vale o que foi perguntado: citar "acidente" numa frase qualquer não é perguntar como ele foi.
        perguntas = "\n".join(p for r in rodadas[:ate + 1] for p in perguntas_de(r))
        faltam = [e for e in expressoes if not re.search(e, perguntas)]
        if faltam:
            falhas.append(_falha("pulou_pergunta", ALTA, rodadas[ate].n, f"foi para {destino_x} sem perguntar /{'/, /'.join(faltam)}/"))
    falhas += _sem_os_fatos_do_oraculo(rodadas, regras)
    falhas += _aceite_antes_de_contratos(rodadas, regras)
    for etapa, expressoes in esperado.obrigatorio_em.items():
        ditos = _textos_ia(rodadas, etapa)
        if not ditos:
            continue
        faltam = [e for e in expressoes if not re.search(e, "\n".join(ditos))]
        if faltam:
            if cortada and etapa == etapa_cortada and not _concluiu(trajetoria, etapa):
                nao_avaliado.append(f"obrigatório da etapa {etapa} (/{'/, /'.join(faltam)}/)")
            else:
                falhas.append(_falha("faltou_obrigatorio", ALTA, ultima, f"na etapa {etapa} faltou /{'/, /'.join(faltam)}/"))
    for etapa, expressoes in esperado.midias_em.items():
        if not any(t.etapa_antes == etapa for r in rodadas for t in r.turnos):
            continue                                       # a conversa nem passou pela etapa
        enviadas = "\n".join(m for r in rodadas for t in r.turnos if t.etapa_antes == etapa for m in t.midias)
        faltam = [e for e in expressoes if not re.search(e, enviadas)]
        if faltam:
            if cortada and etapa == etapa_cortada and not _concluiu(trajetoria, etapa):
                nao_avaliado.append(f"mídia da etapa {etapa} (/{'/, /'.join(faltam)}/)")
            else:
                falhas.append(_falha("midia_obrigatoria", ALTA, ultima, f"na etapa {etapa} não saiu a mídia /{'/, /'.join(faltam)}/"))
    repetidas = _perguntas_repetidas(rodadas)
    acusadas = {f.turno for f in repetidas}
    falhas += repetidas + [f for f in _fato_pedido_de_novo(rodadas, regras)
                           if f.codigo != "pergunta_repetida" or f.turno not in acusadas]
    respondidos = [t for r in rodadas for t in r.turnos if t.mensagens]
    muitas = [t for t in respondidos
              if perguntas_contadas("\n".join(t.mensagens), regras, t.etapa_antes) > esperado.max_perguntas_por_turno]
    if respondidos and len(muitas) / len(respondidos) > LIMIAR_VARIAS_PERGUNTAS:
        falhas.append(_falha("varias_perguntas_frequentes", ALTA, ultima,
                             f"{len(muitas)} de {len(respondidos)} turnos com mais de {esperado.max_perguntas_por_turno} pergunta"))
    if nao_avaliado:
        falhas.append(_falha("nao_avaliado", MEDIA, ultima, f"consequência de {conversa.parada} (a conversa parou em "
                             f"{etapa_cortada}): não conferido {', '.join(nao_avaliado)}"))
    return falhas


def _fatos_revelados(rodadas: list["Rodada"], regras: Regras) -> set[str] | None:
    """Fatos do cartão que o lead contou nestas rodadas (pela resposta de cada assunto). None = lead de IA."""
    assuntos = regras.cenario.lead.assuntos
    revelados: set[str] = set()
    for rodada in rodadas:
        for fala in rodada.falas:
            if fala.origem == "ia":
                return None                                   # o LeadIA confere isso ele mesmo (anti-cooperação)
            if fala.origem.startswith("assunto:"):
                indice = int(fala.origem.split(":", 1)[1])
                if 0 <= indice < len(assuntos):
                    revelados.update(assuntos[indice].fatos)
    return revelados


def _sem_os_fatos_do_oraculo(rodadas: list["Rodada"], regras: Regras) -> list[Falha]:
    """A IA decidiu (closer ou desqualificado) sem o lead ter contado os fatos que decidem o destino do oráculo.

    Vale para a PRIMEIRA decisão, seja ela qual for: indo para o destino errado, os fatos que faltaram também têm de
    aparecer (antes só a ida ao destino certo era conferida). Os fatos de completude (o ano do acidente com CLT na
    data: nenhum valor muda o destino, mas o roteiro pergunta) viram métrica média.
    """
    destino = regras.destino
    if destino is None or not (regras.fatos_decisivos or regras.fatos_de_completude):
        return []
    ate, para = next(((i, t.etapa_depois) for i, r in enumerate(rodadas) for t in r.turnos
                      if t.etapa_depois in ("closer", "desqualificado") and t.etapa_antes != t.etapa_depois), (None, None))
    if ate is None:
        return []
    revelados = _fatos_revelados(rodadas[:ate + 1], regras)
    if revelados is None:
        return []
    faltam = [f for f in regras.fatos_decisivos if f not in revelados]
    completude = [f for f in regras.fatos_de_completude if f not in revelados]
    if faltam:
        # Uma falha só: os de completude entram na mesma evidência (pular a qualificação inteira não vale duas).
        extra = f"; também faltou {', '.join(completude)}, que o roteiro pergunta" if completude else ""
        return [_falha("pulou_pergunta", ALTA, rodadas[ate].n, f"foi para {para} sem o lead ter contado "
                       f"{', '.join(faltam)} (o oráculo precisa disso para decidir: {destino.destino}, {destino.motivo}){extra}")]
    if completude:
        return [_falha("pulou_pergunta_do_roteiro", MEDIA, rodadas[ate].n, f"foi para {para} sem o lead ter contado "
                       f"{', '.join(completude)} (não muda o destino, mas o roteiro pergunta)")]
    return []


def _origem(fala: "Fala") -> tuple[str, int | None]:
    tipo, _, indice = (fala.origem or "").partition(":")
    return tipo, int(indice) if indice.isdigit() else None


def _aceite_antes_de_contratos(rodadas: list["Rodada"], regras: Regras) -> list[Falha]:
    """Foi para contratos sem um sim claro do lead.

    Olha as falas do lead na etapa de origem (closer) até a transferência: precisa haver um aceite (assunto marcado
    "aceite") e, depois dele, só falas com dados do contrato (o nome completo), outro aceite ou um gatilho que não é
    objeção. "Não sei" (padrão), objeção ou adiamento depois do sim reprova (01, rodada real 2: "não sei te dizer" e a
    IA já pediu o nome completo). No sc03 o sim veio no T13 e no T14 e a transferência saiu no T15, com o nome: o
    atraso é acusado por dado_fora_de_hora / transferencia_sem_frase, não aqui.
    Vale para o LeadCartao com um assunto marcado "aceite"; o lead de IA não tem origem por assunto.
    """
    assuntos = regras.cenario.lead.assuntos
    aceites = {i for i, a in enumerate(assuntos) if a.aceite}
    if not aceites:
        return []
    dados_do_contrato = set(cdados.CAMPOS.values())
    gatilhos = regras.cenario.lead.gatilhos
    for k, rodada in enumerate(rodadas):
        entrada = next((t for t in rodada.turnos if t.etapa_depois == "contratos" and t.etapa_antes != "contratos"), None)
        if entrada is None:
            continue
        origem = entrada.etapa_antes
        inicio = k
        while inicio > 0 and rodadas[inicio - 1].etapa_antes == origem and rodadas[inicio].etapa_antes == origem:
            inicio -= 1
        falas = [f for r in rodadas[inicio:k + 1] for f in r.falas]
        if not falas or any(f.origem == "ia" for f in falas):
            return []
        ultimo_aceite = max((i for i, f in enumerate(falas)
                             if _origem(f)[0] in ("assunto", "repetida") and _origem(f)[1] in aceites), default=None)

        def neutra(fala: "Fala") -> bool:
            tipo, indice = _origem(fala)
            if tipo in ("assunto", "repetida") and indice is not None and 0 <= indice < len(assuntos):
                fatos = set(assuntos[indice].fatos)
                return indice in aceites or (bool(fatos) and fatos <= dados_do_contrato)
            if tipo == "gatilho" and indice is not None and 0 <= indice < len(gatilhos):
                return not gatilhos[indice].e_objecao()
            return False

        if ultimo_aceite is not None and all(neutra(f) for f in falas[ultimo_aceite + 1:]):
            return []
        ultima = falas[-1]
        motivo = "sem nenhum sim do lead" if ultimo_aceite is None else \
            f"depois do sim veio '{falas[ultimo_aceite + 1:][0].texto_corrido()}'"
        return [_falha("aceite_antes_de_contratos", ALTA, rodada.n, f"foi para contratos {motivo}; a última fala "
                       f"foi '{ultima.texto_corrido()}' ({ultima.origem or 'sem origem'})")]
    return []


def _parou_antes_do_roteiro(conversa: "Conversa", regras: Regras) -> list[Falha]:
    """LeadRoteiro: a conversa parou (pausa, encerramento...) antes de chegar ao fim do roteiro.

    Sem isso, um agente que entrega tudo para a equipe na primeira fala fora do roteiro passa no cenário
    feito para testar justamente essas falas. Conta TODAS as falas que sobraram, com ou sem 'espera': no 06, a pausa
    por trava na fala 5 batia o estado_final "pausado" por coincidência e a fala 6 (pedir advogado) nunca rodava.
    """
    lead = regras.cenario.lead
    if lead.tipo != "roteiro" or conversa.parada in ("desvio", "cassete_falta", "teto_de_custo"):
        return []
    usadas = len(conversa.rodadas)                            # o LeadRoteiro manda uma fala por rodada
    puladas = list(range(usadas, len(lead.falas)))
    if not puladas:
        return []
    textos = "; ".join(f"'{lead.falas[i].texto_corrido()}'" for i in puladas)
    return [_falha("parou_antes_do_roteiro", ALTA, conversa.rodadas[-1].n if conversa.rodadas else None,
                   f"a conversa parou na fala {usadas} de {len(lead.falas)} ({conversa.parada}) e não avaliou: {textos}")]


def perguntas_de(rodada: "Rodada") -> list[str]:
    """As frases com '?' que a IA mandou na rodada."""
    return [p.strip() for turno in rodada.turnos for t in turno.mensagens for p in re.findall(r"[^.!?\n]*\?", t)
            if len(p.strip()) > 3]


def _sobra_conteudo(texto: str) -> bool:
    """Depois da pergunta vem conteúdo que não é pergunta (a lista de dados da confirmação)."""
    return len(re.findall(r"\w", re.sub(r"[^.!?\n]*\?", " ", texto))) >= 15


def perguntas_comparaveis(rodada: "Rodada") -> list[str]:
    """perguntas_de() sem as retóricas: a pergunta de "tag" ("Vamos confirmar juntos..., tudo bem?") seguida, na mesma
    resposta, da lista de dados. Ela abre o que vem depois; não espera resposta e repeti-la a cada confirmação é o
    roteiro. A mesma pergunta sozinha no fim da resposta continua comparável."""
    saida = []
    for turno in rodada.turnos:
        for k, texto in enumerate(turno.mensagens):
            for m in re.finditer(r"[^.!?\n]*\?", texto):
                pergunta = m.group(0).strip()
                if len(pergunta) <= 3:
                    continue
                resto = texto[m.end():] + "\n" + "\n".join(turno.mensagens[k + 1:])
                if _RETORICA.search(pergunta) and _sobra_conteudo(resto):
                    continue
                saida.append(pergunta)
    return saida


def _fatos_do_contrato(fatos: dict[str, Any]) -> dict[str, str]:
    campos = set(cdados.CAMPOS.values())
    return {k: str(v) for k, v in fatos.items() if k in campos}


def _mudou_entre(rodadas: list["Rodada"], j: int, i: int, pergunta: str) -> bool:
    """Entre a resposta à pergunta antiga (rodada j+1) e a atual (rodada i) houve correção do sistema, gatilho do lead
    (correção, objeção) ou, para a pergunta de confirmação do contrato, dado novo do contrato: perguntar de novo é o
    roteiro (o FORMATO manda mostrar o resumo corrigido e pedir confirmação de novo)."""
    if any(r.enviadas_sistema for r in rodadas[j + 1:i]):
        return True
    if any((f.origem or "").startswith("gatilho:") for r in rodadas[j + 1:i + 1] for f in r.falas):
        return True
    if _CONFIRMACAO.search(pergunta) and j + 1 < len(rodadas):
        return _fatos_do_contrato(rodadas[j + 1].fatos_depois) != _fatos_do_contrato(rodadas[i].fatos_depois)
    return False


def _perguntas_repetidas(rodadas: list["Rodada"]) -> list[Falha]:
    """A IA repete uma pergunta que o lead já tinha respondido (resposta do cartão, não 'não sei')."""
    falhas = []
    for i, rodada in enumerate(rodadas):
        for pergunta in perguntas_comparaveis(rodada):
            for j in range(i):
                respondeu = j + 1 < len(rodadas) and any(f.origem.startswith("assunto:") for f in rodadas[j + 1].falas)
                if not respondeu or _mudou_entre(rodadas, j, i, pergunta):
                    continue
                antiga = next((p for p in perguntas_comparaveis(rodadas[j])
                               if semelhanca(p, pergunta) >= LIMIAR_PERGUNTA_REPETIDA), None)
                if antiga:
                    falhas.append(_falha("pergunta_repetida", ALTA, rodada.n,
                                         f"'{pergunta}' repete a do turno {rodadas[j].n} ('{antiga}'), já respondida"))
                    break
    return falhas


def _casam(textos: list[str], regexes: list[str]) -> list[str]:
    return [t for t in textos if any(re.search(r, t) for r in regexes)]


def _eco_de_confirmacao(perguntas: list[str], anterior: "Rodada", assunto: Any, assuntos: list[Any]) -> bool:
    """A pergunta que fez o lead "repetir" é um eco ("..., foi aposentado por invalidez, certo?") do fato que o lead
    contou na fala IMEDIATAMENTE anterior: confirmar o que acabou de ouvir não é pedir de novo."""
    contados_agora: set[str] = set()
    for fala in anterior.falas:
        tipo, indice = _origem(fala)
        if tipo in ("assunto", "repetida") and indice is not None and 0 <= indice < len(assuntos):
            contados_agora |= set(assuntos[indice].fatos)
    if not set(assunto.fatos) & contados_agora:
        return False
    do_assunto = _casam(perguntas, assunto.quando)
    return bool(do_assunto) and all(_ECO.search(p) for p in do_assunto)


def _fato_pedido_de_novo(rodadas: list["Rodada"], regras: Regras) -> list[Falha]:
    """A IA pede um fato que o lead já tinha contado, com outra pergunta ("trabalhava de carteira assinada?" revela a
    demissão; "quando saiu do último emprego?" pede de novo). O texto das perguntas não se parece, então só o
    LeadCartao vê: ele responde como repetição (origem repetida:N) a um assunto que revela fatos já contados.

    Não culpa a IA quando: o balão não tem pergunta nem pedido (recapitulação ou "Vou buscar seu CEP"; o lead leu o
    balão inteiro); a pergunta é eco de confirmação do que o lead acabou de dizer; quem pediu de novo foi a mensagem do
    sistema (pedido de correção do contrato), que vira correcao_pediu_dado_ja_dado, com o texto do sistema.
    """
    assuntos = regras.cenario.lead.assuntos
    falhas = []
    for anterior, rodada in zip(rodadas, rodadas[1:]):
        for fala in rodada.falas:
            tipo, indice = _origem(fala)
            if tipo != "repetida" or indice is None or not 0 <= indice < len(assuntos):
                continue
            assunto = assuntos[indice]
            fatos = assunto.fatos
            if not fatos:
                continue
            perguntas = perguntas_de(anterior)
            pedidos = [t for t in anterior.enviadas_ia if _PEDIDO.search(t)]
            ia_pede = _casam(perguntas, assunto.quando) or _casam(pedidos, assunto.quando)
            sistema_pede = _casam(anterior.enviadas_sistema, assunto.quando)
            if not ia_pede and sistema_pede:
                falhas.append(_falha("correcao_pediu_dado_ja_dado", ALTA, anterior.n, f"o pedido de correção do sistema "
                                     f"pede de novo {', '.join(fatos)}, que o lead já tinha contado: '{sistema_pede[0][:300]}'"))
                break
            if not perguntas and not pedidos:
                continue
            if _eco_de_confirmacao(perguntas, anterior, assunto, assuntos):
                continue
            pergunta = " / ".join(ia_pede or perguntas or pedidos)[:300]
            falhas.append(_falha("pergunta_repetida", ALTA, anterior.n,
                                 f"'{pergunta}' pede de novo {', '.join(fatos)}, que o lead já tinha contado"))
            break
    return falhas


def aprovado(falhas: list[Falha]) -> bool:
    return not any(f.gravidade in (CRITICA, ALTA) for f in falhas)
