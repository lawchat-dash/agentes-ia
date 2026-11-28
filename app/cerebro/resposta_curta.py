"""Resposta curta do lead ligada à ÚLTIMA pergunta da IA, sem chamar IA nenhuma.

Duas peças, as duas determinísticas (rodam dentro de extrator.extrair, depois da conferência dos trechos):

  A. resolver(): "Sim", "Não", "não sei", "4 meses" sozinhos valem para a última pergunta da IA. Pelas palavras da
     pergunta ("aposentad", "advogad", "sequela"...) o código sabe qual fato é e grava com trecho = resposta do lead
     (fonte extrator). O extrator de IA esquecia esses fatos ("Não" para "Hoje você recebe alguma aposentadoria?") e o
     portão segurava a passagem para o Closer até mandar o lead para a equipe.
  B. fora_do_assunto(): fato que desqualifica (MOTIVOS_DE_DESQUALIFICAR), fato do portão e meses de demissão só valem do
     extrator de IA quando a pergunta da IA antes da resposta (ou a própria mensagem do lead) fala daquele assunto.
     "Não" para "Você tem algum documento médico?" virava documentos_rurais=nao (motivo de desqualificar) e "4 meses"
     para "quanto tempo recebeu auxílio-doença?" virava demissao_meses_antes_do_acidente=4.

Tudo sobre texto normalizado (minúsculo, sem acento, sem pontuação): ver extrator.normalizar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable

AUTORES_DA_IA = ("você", "ia", "atendente")

# ---------------------------------------------------------------------------- sim / não / não sei
_SIM = (r"sim+|s|ss|si|isso|isso mesmo|exato|exatamente|claro|claro que sim|com certeza|certeza|certo|correto|"
        r"positivo|afirmativo|aham|uhum|unhum|sim senhor|sim senhora|pode ser|recebi|recebo|tenho|tive|fiquei|estava|"
        r"era|sou|trabalhava|ja")
_NAO = (r"nao+|n|nn|nunca|jamais|negativo|de jeito nenhum|nem|nada|nenhum|nenhuma|nao senhor|nao senhora|"
        r"nao tenho|nao recebo|nao recebi|nao sou|nao estava|nao era|nao fiquei|nunca tive|nunca recebi")
_NAO_SEI = r"nao sei|sei la|nao lembro|nao me lembro|nao tenho certeza|talvez|nao sei dizer|nao sei te dizer"
# Cortesias que podem vir junto ("não, senhora, obrigado"): não mudam a resposta.
_COMPLEMENTO = r"(?:\s+(?:senhor|senhora|sr|sra|moca|doutor|doutora|obrigad[oa]|obg|viu|ta|tá|ok|kk+|rs+|hein|ne|uai|so|mesmo))*"
_SO_SIM = re.compile(rf"^(?:{_SIM})(?:\s+(?:{_SIM}))*{_COMPLEMENTO}$")
_SO_NAO = re.compile(rf"^(?:{_NAO})(?:\s+(?:{_NAO}))*{_COMPLEMENTO}$")
_SO_NAO_SEI = re.compile(rf"^(?:{_NAO_SEI}){_COMPLEMENTO}$")
# Começo da mensagem, separado do resto por pontuação ("Não, nunca tive advogado", "Sim! Fiquei mancando"). Sem a
# pontuação ("não entendi a pergunta", "sim eu acho que...") fica para o extrator de IA.
_COMECA_SIM = re.compile(r"^\s*(?:sim+|isso|claro|com certeza|exato)\s*(?:[,.!;:\-–—]|\s(?=(?:eu\s+)?(?:j[aá]\s+)?"
                         r"(?:te\s+)?(?:falei|disse|respondi|informei|expliquei|acabei|como)\b))", re.I)
# "Sim falei acima", "sim acabei de falar", "sim já disse": o sim reclamando da repetição, mesmo sem pontuação.
_COMECA_NAO = re.compile(r"^\s*(?:n[aã]o+|nunca)\s*[,.!;:\-–—]", re.I)


def sim_nao(normal: str, bruto: str = "") -> tuple[str, bool] | None:
    """('sim'|'nao'|'nao_sabe', sozinha). sozinha=True: a mensagem é só a resposta; False: começa por ela, separada do
    resto por pontuação (`bruto` é o texto original, para ver essa pontuação)."""
    if not normal:
        return None
    if _SO_NAO_SEI.match(normal):
        return "nao_sabe", True
    if _SO_SIM.match(normal):
        return "sim", True
    if _SO_NAO.match(normal):
        return "nao", True
    if _COMECA_NAO.match(bruto):
        return "nao", False
    if _COMECA_SIM.match(bruto):
        return "sim", False
    return None


# ---------------------------------------------------------------------------- número / tempo
_NUMEROS = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6, "sete": 7,
            "oito": 8, "nove": 9, "dez": 10, "onze": 11, "doze": 12, "treze": 13, "quatorze": 14, "catorze": 14,
            "quinze": 15, "dezesseis": 16, "dezessete": 17, "dezoito": 18, "dezenove": 19, "vinte": 20,
            "trinta": 30, "quarenta": 40, "cinquenta": 50, "meio": 0.5, "meia": 0.5}
_PALAVRA_NUM = r"\d{1,3}|" + "|".join(sorted(_NUMEROS, key=len, reverse=True))
_TEMPO = re.compile(rf"^(?:(?:uns|umas|mais ou menos|quase|cerca de|acho que|faz|fazia|tinha|ha|de)\s+)*"
                    rf"({_PALAVRA_NUM})(?:\s+e\s+(meio|meia))?\s*(mes|meses|ano|anos)?(?:\s+e\s+(meio|meia))?"
                    rf"(?:\s+(?:mais ou menos|antes|atras|antes do acidente|por ai|so))*$")


def tempo_em_meses(normal: str) -> int | None:
    """'4 meses' -> 4, 'uns 2 anos' -> 24, 'ano e meio'... (não), '8' -> 8. Só quando a mensagem é só o tempo."""
    achado = _TEMPO.match(normal or "")
    if not achado:
        return None
    bruto, meio, unidade, meio_depois = achado.groups()
    meio = meio or meio_depois
    numero = float(bruto) if bruto.isdigit() else float(_NUMEROS[bruto])
    if meio:
        numero += 0.5
    if unidade and unidade.startswith("ano"):
        numero *= 12
    return int(round(numero))


# ---------------------------------------------------------------------------- A. resolvedor pela pergunta
@dataclass(frozen=True)
class _Regra:
    chave: str
    pergunta: re.Pattern[str]
    valores: dict[str, str] | None = None        # sim/nao/nao_sabe -> valor gravado (None = o próprio sim/nao)
    numero: bool = False                         # resposta é um tempo em meses
    nao_se: re.Pattern[str] | None = None        # pergunta que parece, mas é de outra coisa


def _re(padrao: str) -> re.Pattern[str]:
    return re.compile(padrao)


_DURACAO = _re(r"\b(?:quanto tempo|quantos meses|quantos anos|por quanto|ate quando|desde quando|ha quanto)\b")
# Ordem importa: a primeira regra que casa com a pergunta decide (as mais específicas primeiro).
REGRAS: tuple[_Regra, ...] = (
    # Salário-Maternidade (só valem onde estes fatos estão no esquema). "Já recebeu o salário-maternidade por este
    # filho?" vem antes do benefício do BPC; "10 anos de contribuição" antes de "contribuiu" (conta própria); o
    # documento rural da família antes do documentos_rurais do Auxílio-Acidente.
    _Regra("ja_recebeu_por_esse_filho",
           _re(r"\breceb\w*\b.*\b(?:esse|este|essa|esta|desse|deste|dessa|desta|mesmo|mesma)\s+"
               r"(?:filh[oa]|bebe|crianca|parto|gravidez|gestacao|adocao)\b")),
    _Regra("menor_16_no_parto", _re(r"\b(?:menos de|menor de|abaixo de)\s+(?:16|dezesseis)\b")),
    _Regra("dez_anos_contribuicao", _re(r"\b(?:10|dez) anos\b"), nao_se=_re(r"\b(?:5|cinco) anos\b")),
    _Regra("rural_tem_documento",
           _re(r"\b(?:documento\w*|comprovante\w*|papel|papeis|nota\w*|bloco|declarac\w*|contrato\w*|itr|ccir|dap|caf)\b"
               r".*\b(?:rural|rurais|roca|lavoura|agricult\w*|sitio|fazenda|terra|produtor\w*|lavrador\w*|campo)\b"
               r"|\b(?:rural|rurais|roca|lavoura|agricult\w*|sitio|fazenda|produtor\w*|lavrador\w*)\b.*"
               r"\b(?:documento\w*|comprovante\w*|papel|papeis|nota\w*|bloco|declarac\w*)\b")),
    _Regra("demissao_meses_antes_do_acidente",
           _re(r"\b(?:sai\w*|demit\w*|demiss\w*|desligad\w*|dispensad\w*|mandad\w* embora|parou de trabalhar|"
               r"sem (?:emprego|trabalho|carteira))\b.*\bantes do acidente\b|\bantes do acidente\b.*\b(?:sai\w*|demit\w*|"
               r"demiss\w*|desligad\w*|dispensad\w*|sem (?:emprego|trabalho|carteira)|parou de trabalhar)\b"),
           numero=True),
    _Regra("documentos_rurais",
           _re(r"\b(?:documento\w*|comprovante\w*|papel|papeis|nota\w*|bloco|declarac\w*|contrato\w*|itr|ccir|dap|caf)\b"
               r".*\b(?:rural|rurais|roca|lavoura|agricult\w*|sitio|fazenda|terra|produtor\w*|lavrador\w*|campo)\b"
               r"|\b(?:rural|rurais|roca|lavoura|agricult\w*|sitio|fazenda|produtor\w*|lavrador\w*)\b.*"
               r"\b(?:documento\w*|comprovante\w*|papel|papeis|nota\w*|bloco|declarac\w*)\b")),
    # BPC: "Hoje ele recebe algum benefício, como aposentadoria ou pensão?" + "Não" = nenhum. "Sim" não diz qual
    # (fica para o extrator de IA). Antes da regra do aposentado: a pergunta do BPC cita aposentadoria como exemplo.
    # Só vale onde recebe_beneficio está no esquema (famílias BPC); no Auxílio-Acidente cai na regra seguinte.
    # "Você já tem advogado cuidando desse pedido do BPC?" cita o BPC mas é a pergunta do advogado (28/11: o "não" virava
    # recebe_beneficio=nenhum e o advogado nunca era gravado).
    _Regra("recebe_beneficio", _re(r"\b(?:beneficio\w*|bpc|loas|pensao|bolsa familia)\b"), valores={"nao": "nenhum"},
           nao_se=_re(r"\badvogad\w*")),
    _Regra("aposentado", _re(r"\baposentad\w*|\baposentadoria\w*")),
    _Regra("tem_advogado_no_caso", _re(r"\badvogad\w*|\bescritorio\w* (?:cuidando|olhando)|\bprocesso\b.*\bcaso\b")),
    _Regra("seguro_desemprego", _re(r"\bseguro desemprego\b")),
    # Pagar o INSS depois de sair do emprego. "Você atuava como MEI/autônomo?" é o vínculo (regra mais abaixo).
    _Regra("contribuiu_por_conta_propria",
           _re(r"\b(?:carne|contribuiu|contribuindo|recolheu|recolhia|pagou o inss|pagava o inss|pagou inss|"
               r"pagando o inss)\b")),
    _Regra("ja_foi_clt", _re(r"\b(?:alguma vez|ja trabalhou|ja teve)\b.*\b(?:carteira|clt|registrad\w*|fichad\w*)\b"),
           ),
    _Regra("vinculo_na_data", _re(r"\b(?:carteira assinada|clt|registrad\w*|fichad\w*)\b"), valores={"sim": "clt"},
           nao_se=_DURACAO),
    _Regra("vinculo_na_data", _re(r"\b(?:mei|autonom\w*|contribuinte individual|por conta propria)\b"),
           valores={"sim": "mei_autonomo_ci"}, nao_se=_DURACAO),
    _Regra("vinculo_na_data",
           _re(r"\b(?:roca|lavoura|agricult\w*|rural|lavrador\w*|trabalho no campo|na terra)\b"), valores={"sim": "rural"},
           nao_se=_DURACAO),
    _Regra("auxilio_doenca",
           _re(r"\b(?:auxilio doenca|beneficio por incapacidade|incapacidade temporaria|afastad\w*|encostad\w*|"
               r"pericia)\b"), nao_se=_DURACAO),
    _Regra("sequela", _re(r"\b(?:sequela\w*|limitac\w*|dificuldade\w*|limitad\w*|ficou com algum\w* problema)\b")),
    _Regra("aceite_honorarios",
           _re(r"\b(?:honorario\w*|nessas condicoes|nestas condicoes|seguir com a contratacao|podemos seguir|"
               r"fechar (?:o contrato|com a gente)|seguir com o contrato)\b"),
           valores={"sim": "sim", "nao": "nao", "nao_sabe": "nao_sabe"}),
)


@dataclass
class Resolvido:
    chave: str
    valor: Any
    trecho: str
    sozinha: bool        # a mensagem era só a resposta ("Não"): vale mais que o extrator de IA


def ultima_pergunta(historico: list[dict[str, Any]]) -> str:
    """Última pergunta da IA antes das mensagens novas: o balão mais recente com "?" do último bloco da IA (senão o
    último balão dela). Vazio quando o lead falou por último antes deste lote sem a IA ter perguntado nada."""
    bloco: list[str] = []
    for mensagem in reversed(historico or []):
        if mensagem.get("autor") in AUTORES_DA_IA:
            bloco.insert(0, str(mensagem.get("texto") or ""))
        elif bloco:
            break
        else:
            return ""          # a última mensagem do histórico é do lead: o lote novo não responde à IA
    for texto in reversed(bloco):
        if "?" in texto:
            return texto
    return bloco[-1] if bloco else ""


def _regra_da_pergunta(pergunta_normal: str, aceitas: set[str]) -> _Regra | None:
    for regra in REGRAS:
        if regra.chave in aceitas and regra.pergunta.search(pergunta_normal) \
                and not (regra.nao_se and regra.nao_se.search(pergunta_normal)):
            return regra
    return None


def resolver(historico: list[dict[str, Any]], novas: list[str], aceitas: Iterable[str],
             normalizar: Callable[[str], str]) -> list[Resolvido]:
    """Fatos da resposta curta à última pergunta da IA. `aceitas` = chaves que o produto grava (o esquema do extrator)."""
    pergunta = normalizar(ultima_pergunta(historico))
    if not pergunta or not novas:
        return []
    # A pergunta só aceita UMA pergunta de verdade: "aposentado ou tem advogado?" fica para o extrator de IA.
    if len(re.findall(r"\?", ultima_pergunta(historico))) > 1:
        return []
    regra = _regra_da_pergunta(pergunta, set(aceitas))
    if regra is None:
        return []
    for texto in novas:                      # a primeira mensagem do lote que é uma resposta curta
        normal = normalizar(texto)
        if regra.numero:
            if (meses := tempo_em_meses(normal)) is not None:
                return [Resolvido(regra.chave, meses, texto.strip(), True)]
            continue
        if (resposta := sim_nao(normal, texto)) is None:
            continue
        valor_sn, sozinha = resposta
        if not sozinha:
            resto = normalizar(texto.strip()[len(re.split(r"[,.!;:\-–—]", texto.strip(), maxsplit=1)[0]):])
            # "Isso, não. Eu era registrada": o começo diz sim e o resto desdiz. Fica para o extrator de IA (lote 1 do
            # teste real, 28/11: virava MEI e o lead de carteira assinada ia para o período de graça).
            if (valor_sn == "sim" and re.search(r"\bnao\b", resto)) or (valor_sn == "nao" and re.match(r"\s*sim\b", resto)):
                continue
        valor = (regra.valores or {"sim": "sim", "nao": "nao", "nao_sabe": "nao_sabe"}).get(valor_sn)
        if valor is None:
            return []                         # "Não" a "estava registrado?" não diz qual era o vínculo
        trecho = texto.strip() if sozinha else re.split(r"[,.!;:\-–—]", texto.strip(), maxsplit=1)[0].strip()
        return [Resolvido(regra.chave, valor, trecho, sozinha)]
    return []


# ---------------------------------------------------------------------------- B. trava do assunto
# Palavras que mostram que a pergunta (ou a mensagem do lead) é daquele assunto. Mais largas que as do resolvedor: aqui
# é só para não aceitar um fato que caiu do céu.
ASSUNTO: dict[str, re.Pattern[str]] = {
    "aposentado": _re(r"\baposent\w*"),
    "tem_advogado_no_caso": _re(r"\b(?:advogad\w*|adv|doutor\w*|dr|dra|escritorio\w*|processo\w*|juridic\w*|"
                                r"defensoria|justica|acao)\b"),
    "sequela": _re(r"\b(?:sequela\w*|limitac\w*|limitad\w*|dificuldade\w*|dor\w*|doi\w*|manc\w*|andar|anda|ando|mexer|"
                   r"moviment\w*|forca|incha\w*|perd\w*|amput\w*|cicatriz\w*|consig\w*|consegu\w*|bengala|muleta\w*|"
                   r"trav\w*|deficien\w*|lesao|lesoes|machuc\w*|problema\w*|recuper\w*|normal|bem|sarou|sarei|curad\w*|"
                   r"pino\w*|placa\w*|platina|fisioterapia|mancando|cirurgia\w*|false\w*|escada\w*|sub\w*|abaix\w*|carreg\w*|"
                   r"peso|fraturad?\w*|quebr\w*|torc\w*|rompi\w*|tendao|joelho|perna|braco|mao|dedo\w*|pe|coluna|ombro|"
                   r"tornozelo|sinto|sente|ruim|piorou|melhorou)\b"),
    "vinculo_na_data": _re(r"\b(?:carteira|clt|registr\w*|trabalh\w*|emprego\w*|empregad\w*|desempreg\w*|autonom\w*|mei|"
                           r"bico\w*|conta propria|roca|lavoura|rural|agricult\w*|concurs\w*|servidor\w*|prefeitura|"
                           r"estatutari\w*|fichad\w*|firma|empresa|patrao|servico|lavrador\w*|sitio|fazenda|"
                           r"vinculo|contratad\w*)\b"),
    "documentos_rurais": _re(r"\b(?:rural|rurais|roca|lavoura|agricult\w*|sitio|fazenda|terra|terreno|plant\w*|"
                             r"colheita|sindicato|produtor\w*|lavrador\w*|itr|ccir|pronaf|dap|caf|incra|campo|"
                             r"rocado|gado|criacao)\b"),
    "demissao_meses_antes_do_acidente": _re(r"\b(?:demit\w*|demiss\w*|sai|saiu|sair|saido|desligad\w*|dispensad\w*|"
                                            r"mandad\w*|embora|desempreg\w*|sem (?:emprego|trabalho|carteira|servico)|"
                                            r"parei|parou|ultimo emprego|emprego)\b"),
    "seguro_desemprego": _re(r"\b(?:seguro\w*|desemprego)\b"),
    "contribuiu_por_conta_propria": _re(r"\b(?:carne\w*|inss|contribu\w*|recolh\w*|mei|pag\w*|guia\w*|gps|"
                                        r"conta propria|autonom\w*)\b"),
    # BPC: recebe_beneficio desqualifica (bpc, aposentadoria, pensão por morte): só vale quando o assunto apareceu.
    "recebe_beneficio": _re(r"\b(?:benefici\w*|bpc|loas|aposent\w*|pensao|pensionista|auxilio\w*|bolsa|inss|"
                            r"receb\w*|ganh\w*|encostad\w*|afastad\w*)\b"),
    # Salário-Maternidade: os fatos que desqualificam só valem quando o assunto apareceu.
    "ja_recebeu_por_esse_filho": _re(r"\b(?:receb\w*|pag\w*|salario\w*|maternidade|licenca|benefici\w*|inss|"
                                     r"dinheiro|parcela\w*)\b"),
    "categoria": _re(r"\b(?:concurs\w*|servidor\w*|servidora\w*|estatutari\w*|prefeitura|publico|publica|efetiv\w*|"
                     r"regime proprio|rpps|estado|municipio|governo|carteira|clt|registr\w*|trabalh\w*|emprego\w*|"
                     r"empregad\w*|desempreg\w*|empresa|firma|patra\w*|mei|autonom\w*|conta propria|domestic\w*|"
                     r"diarista|intermitente|facultativ\w*|bico\w*|rural|roca|lavoura|agricult\w*|pesca\w*|sai|saiu|"
                     r"demit\w*|demiss\w*|dona de casa|do lar|contribu\w*|inss)\b"),
    "rural_tem_documento": _re(r"\b(?:rural|rurais|roca|lavoura|agricult\w*|sitio|fazenda|terra|terreno|plant\w*|"
                               r"colheita|sindicato|produtor\w*|lavrador\w*|itr|ccir|pronaf|dap|caf|incra|campo|"
                               r"documento\w*|papel|papeis|comprovante\w*|pesca\w*)\b"),
    "menor_16_no_parto": _re(r"\b(?:idade|anos|menor|menos|16|dezesseis|nova|novinha|adolescente|nasceu|tinha)\b"),
}
# Fora da trava: aceite_honorarios (portão de Contratos). Não desqualifica ninguém e o aceite é dito de mil jeitos
# ("fechado", "bora", "pode mandar") depois de um vídeo com "O que acha?": a trava seguraria o contrato por engano.


# Chaves que entram na conta do período de graça (a calculadora pode desqualificar por elas): também sob a trava.
DO_PERIODO = ("demissao_meses_antes_do_acidente", "seguro_desemprego", "contribuiu_por_conta_propria")
# Respostas do roteiro que o resolvedor anota mesmo fora do esquema do extrator do catálogo. Com o portão de fatos
# desligado (config.catalogo.portao_de_fatos = false) o extrator de IA nem procura aposentado/advogado/sequela; o "Não"
# anotado pelo código aparece à IA em DADOS JÁ INFORMADOS e ela não pergunta de novo. Sem o portão nada decide por eles.
SO_DO_RESOLVEDOR = ("auxilio_doenca", "aposentado", "tem_advogado_no_caso", "sequela", "vinculo_na_data",
                    "documentos_rurais", "ja_foi_clt")


def chaves_travadas(motivos: Iterable[str], portao: Iterable[str]) -> set[str]:
    """Chaves sob a trava: as que desqualificam, as do portão e os meses de demissão (contas do período de graça)."""
    return {c for c in (*motivos, *portao, *DO_PERIODO) if c in ASSUNTO}


def _contexto_do_trecho(trecho_normal: str, historico: list[dict[str, Any]], novas: list[str],
                        normalizar: Callable[[str], str]) -> tuple[str, str]:
    """(mensagens do lead do bloco que tem o trecho, bloco da IA logo antes dele), normalizados. O bloco do lead são as
    mensagens seguidas dele (o lote: "caí de moto" / "machuquei o joelho" / "até hoje falseia")."""
    linha = [{"autor": str(m.get("autor") or ""), "texto": str(m.get("texto") or "")} for m in historico or []]
    linha += [{"autor": "lead", "texto": t} for t in novas]
    for indice in range(len(linha) - 1, -1, -1):
        mensagem = linha[indice]
        if mensagem["autor"] in AUTORES_DA_IA or f" {trecho_normal} " not in f" {normalizar(mensagem['texto'])} ":
            continue
        inicio = indice
        while inicio > 0 and linha[inicio - 1]["autor"] not in AUTORES_DA_IA:
            inicio -= 1
        fim = indice
        while fim + 1 < len(linha) and linha[fim + 1]["autor"] not in AUTORES_DA_IA:
            fim += 1
        do_lead = " ".join(m["texto"] for m in linha[inicio:fim + 1])
        bloco: list[str] = []
        for anterior in reversed(linha[:inicio]):
            if anterior["autor"] not in AUTORES_DA_IA:
                break
            bloco.insert(0, anterior["texto"])
        return normalizar(do_lead), normalizar(" ".join(bloco))
    return "", ""


def fora_do_assunto(chave: str, trecho: str, historico: list[dict[str, Any]], novas: list[str],
                    normalizar: Callable[[str], str]) -> bool:
    """True quando o fato travado não tem o assunto nem na mensagem do lead nem na pergunta da IA antes dela."""
    padrao = ASSUNTO.get(chave)
    if padrao is None:
        return False
    trecho_normal = normalizar(trecho)
    mensagem, pergunta = _contexto_do_trecho(trecho_normal, historico, novas, normalizar)
    if not mensagem and not pergunta:
        return False                 # sem achar onde está o trecho, a conferência do trecho já decidiu
    return not (padrao.search(mensagem) or padrao.search(pergunta))
