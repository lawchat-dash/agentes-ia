"""Extrator: lê o que o lead escreveu e devolve fatos, cada um com o trecho que prova.

É a principal defesa contra alucinação. O código confere se o trecho existe mesmo
nas mensagens do lead; fato sem prova é descartado e fica registrado.

Os campos vêm do produto do agente (pronto ou próprio).
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.cerebro import auxilio_acidente as aa
from app.cerebro import resposta_curta
from app.modelo import Chamada, Modelo

if TYPE_CHECKING:
    from app.cerebro.produto import Produto


REGRAS_GERAIS = """Você extrai fatos de uma conversa de WhatsApp entre um escritório de advocacia e {contexto}. \
Você não conversa com ninguém: só preenche campos.

Regras:
1. Registre apenas o que o LEAD disse. Nunca deduza, complete ou suponha. Na dúvida, não registre.
2. Para cada fato, copie em "trecho" as palavras exatas do lead que provam o fato, sem mudar nada. \
O trecho precisa existir, letra por letra, numa mensagem do lead.
3. Olhe só para as MENSAGENS NOVAS. A conversa anterior serve para entender respostas curtas \
("sim", "não", "faz uns 2 anos") à última pergunta feita.
4. Se o lead corrigir algo que já consta nos fatos conhecidos, registre o valor novo.
5. Não repita fato que já consta igual nos fatos conhecidos.
6. Cuidado com o tempo do verbo: o que vale hoje é diferente do que valia na época do fato.
7. Se nada novo foi dito, devolva a lista de fatos vazia e todas as intenções como false.
8. Data dita de forma relativa: converta usando a data de hoje que vem no conteúdo (linha "Hoje é"), só até onde a expressão \
permite saber. "Há 3 meses" ou "mês passado" dão mês e ano. "Ano passado" ou "faz uns 2 anos" dão só o ano: nunca \
preencha o mês (nem chute um). "Faz anos", sem número, não dá data nenhuma. "Hoje", "até hoje" e "hj" falando de \
dor, sequela ou benefício atual ("até hoje dói", "hoje anda de bengala", "recebo até hoje") NÃO são data de nada: \
nunca use a data de hoje como data do acidente ou da saída do emprego.
"""


def _descricao_dos_fatos_aa() -> str:
    linhas = []
    for chave, regra in aa.FATOS.items():
        if regra is None:
            aceita = "texto curto, nas palavras do lead"
        elif isinstance(regra, str):
            aceita = "número inteiro de " + regra[4:].replace("-", " a ")
        else:
            aceita = " | ".join(regra)
        linhas.append(f"- {chave}: {aceita}")
    return "\n".join(linhas)


GUIA_AUXILIO_ACIDENTE = f"""Fatos possíveis e valores aceitos:
{_descricao_dos_fatos_aa()}

Como preencher alguns deles:
- vinculo_na_data é a situação NA DATA DO ACIDENTE ("não trabalho" hoje é diferente de "não trabalhava" na época): \
clt (carteira assinada) | desempregado | mei_autonomo_ci (por conta própria, MEI, bico, autônomo) | \
rural (roça, lavoura, agricultura familiar) | servidor_estatutario (concursado) | nunca_trabalhou | nao_sabe.
- tem_advogado_no_caso é só advogado cuidando DESTE caso. Advogado para outro assunto não conta.
- demissao_meses_antes_do_acidente: quando o lead diz há quanto tempo estava sem emprego ao sofrer o \
acidente ("uns 8 meses antes", "tinha saído fazia 1 ano" = 12).
- demissao_ha_muitos_anos: "sim" quando ele diz que saiu "faz anos", "há muito tempo", sem número.
- Datas: use acidente_mes/acidente_ano e demissao_mes/demissao_ano só com o que foi dito. \
"Em 2021" preenche só o ano. "Até hoje dói/incha/manco" fala da sequela, não é a data do acidente.
- "Fiquei X meses afastado/encostado pelo INSS" é tempo de auxílio-doença: nunca vai para demissao_*. \
"Sou registrado desde 2021" é vínculo, não demissão.

Sinais (marque só se o lead disse com as próprias palavras):
- nao_sabe_ler: diz que não sabe ler ou lê com dificuldade.
- quer_audio: pede para receber áudio.
- quer_videochamada: pede chamada de vídeo.
- cliente_antigo: diz que já é ou foi cliente DESTE escritório.
- outro_beneficio: pede outro benefício (BPC, aposentadoria, pensão...) e não o do acidente.
- dificuldade_assinatura: não consegue assinar o contrato (link não abre, erro, travou na selfie ou no código).
- foto_contrato: mandou foto, print ou arquivo do contrato.
- muitas_objecoes: três ou mais objeções (golpe, honorários, família, 'vou pensar') e segue resistente. \
Reclamar que a atendente repetiu a pergunta ('já te falei', 'já respondi') NÃO é objeção.
- endereco_sem_falar: recusa passar o endereço ou desvia quando pedido.
- contrato_manual: pede contrato impresso, quem assina é representante/curador, ou não consegue assinatura digital.

Intenções (true só quando estiver claro nas mensagens novas):
- pediu_humano: pede uma pessoa no lugar da IA (atendente, humano, 'não quero falar com robô'). NÃO é: a mensagem pronta do anúncio ('Quero falar com um especialista em ...', 'quero mais informações'), querer conhecer o escritório pessoalmente, nem perguntar se são advogados.
- pediu_para_parar: pede para não receber mais mensagens.
- engano: diz que foi engano ou que não procurou o escritório.
- aceitou_honorarios: concorda de forma clara com os honorários apresentados.
- recusou: diz de forma clara que não quer seguir.
- diz_que_assinou: afirma que já assinou o contrato.
- confirmou_dados: confirma de forma clara que os dados do contrato mostrados pela IA estão certos ("sim, está certo").
- pediu_link: pede o link do contrato de novo ("manda o link de novo", "perdi o link").

Dados do contrato (fatos nome_completo, cpf, rg, estado_civil, profissao, cep, endereco, numero_casa, complemento,
bairro, cidade, uf, email, telefone_contrato, nome_menor, cpf_menor): copie como o lead escreveu. endereco é só a rua,
sem o número; numero_casa é só o número ("S/N" se não tiver); complemento é o que vier junto do número (apto 12, \
bloco B, fundos, casa: "13 casa" = numero_casa 13 e complemento "casa"); se o lead disser que não tem complemento ("não \
tem", "só o número", "sem complemento"), complemento = "sem complemento"; uf é a sigla do estado: se o lead escrever o nome \
(Minas Gerais), converta para a sigla (MG), e nome de estado não vai para cidade; cep tem 8 dígitos (00000-000) e não \
se confunde com telefone; telefone_contrato só com DDD e número ("pode ser este do zap" = deixe vazio); email só se \
tiver @ ("não tenho" = deixe vazio, não registre). Se o lead corrigir um dado,
devolva o valor novo.
"""


def sistema_do_extrator(produto: "Produto") -> str:
    return REGRAS_GERAIS.format(contexto=produto.contexto) + "\n" + produto.guia_do_extrator()


def normalizar(texto: str) -> str:
    """Minúsculas, sem acento e sem pontuação: para comparar trechos com justiça."""
    sem_acento = unicodedata.normalize("NFD", texto)
    sem_acento = "".join(c for c in sem_acento if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", sem_acento.lower()).strip()


@dataclass
class FatoExtraido:
    chave: str
    valor: Any
    trecho: str


@dataclass
class Extracao:
    fatos: list[FatoExtraido] = field(default_factory=list)
    rejeitados: list[dict[str, Any]] = field(default_factory=list)
    sinais: list[str] = field(default_factory=list)
    intencoes: dict[str, bool] = field(default_factory=dict)
    bruto: dict[str, Any] = field(default_factory=dict)
    chamadas: list[Chamada] = field(default_factory=list)
    resolvidos: list[dict[str, Any]] = field(default_factory=list)  # fatos da resposta curta à última pergunta (código)
    falha: str | None = None        # motivo do erro do extrator de IA quando o turno seguiu sem ele (tolerar_falha)


def montar_conteudo(fatos_conhecidos: dict[str, Any], historico: list[dict[str, str]], novas: list[str],
                    agora: datetime | None = None) -> str:
    """Conteúdo do extrator. A data de hoje vai junto para ele converter "há 3 meses" em mês e ano.

    Ordem pensada para o cache do provedor (só vale prefixo idêntico): a conversa anterior só cresce no fim de um turno
    para o outro, então vem primeiro; o que muda a cada turno (a hora, os fatos conhecidos, as novas) vem depois."""
    from app.cerebro.contexto import linha_de_hoje

    partes = ["CONVERSA ANTERIOR (mais antiga primeiro):"]
    if historico:
        partes.extend(f"[{m['autor']}] {m['texto']}" for m in historico)
    else:
        partes.append("(nenhuma)")
    partes += ["", linha_de_hoje(agora), "", "FATOS CONHECIDOS:",
               json.dumps(fatos_conhecidos, ensure_ascii=False, sort_keys=True)]
    partes.append("\nMENSAGENS NOVAS DO LEAD:")
    partes.extend(f"[lead] {texto}" for texto in novas)
    return "\n".join(partes)


# Trecho (já normalizado) que diz o mês: nome ou abreviação do mês, "há 3 meses", "semana passada", "03/2024".
_DIZ_O_MES = re.compile(r"\b(janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro|"
                        r"jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez|mes|meses|semana|semanas|dia|dias|ontem|"
                        r"anteontem|hoje)\b|\b\d{1,2} \d{2,4}\b")
_SO_O_ANO = re.compile(r"\banos?\b|\b(?:19|20)\d{2}\b")


def _mes_sem_prova(chave: str, trecho_normalizado: str) -> bool:
    """Mês tirado de um trecho que só diz o ano ("ano passado", "faz uns 2 anos", "em 2021"): o mês foi inventado.
    Com o mês chutado, a conta do período de graça vira um número exato e pode desqualificar o lead por engano."""
    return (chave.endswith("_mes") and not _DIZ_O_MES.search(trecho_normalizado)
            and bool(_SO_O_ANO.search(trecho_normalizado)))


# Campos de data que precisam de um marcador de data no trecho. "ate hj incha" virava acidente em 03/2026 (o mês de hoje)
# e a conta desqualificava o lead. Ficam de fora demissao_ha_muitos_anos ("faz anos", sem número, é válido) e
# demissao_meses_antes_do_acidente ("uns 8 meses" já traz o número).
CAMPOS_DE_DATA = ("acidente_mes", "acidente_ano", "demissao_mes", "demissao_ano")
_NUMERO_POR_EXTENSO = (r"(?:um|uma|dois|duas|tres|quatro|cinco|seis|sete|oito|nove|dez|onze|doze|treze|quatorze|catorze"
                       r"|quinze|dezesseis|dezessete|dezoito|dezenove|vinte|trinta|quarenta|cinquenta|meio|meia)")
# Sobre o trecho normalizado (minúsculo, sem acento nem pontuação). "Hoje"/"hj" sozinho NÃO conta.
_TEM_DATA = re.compile(
    r"\b(?:1\s?9|2\s?0)\d{2}\b"                                                   # ano com 4 dígitos ("2.019" vira "2 019")
    r"|\b(?:dois\s+mil|mil\s+novecentos)\b"                                       # ano por extenso ("dois mil e vinte")
    r"|\b(?:em|de|no|ano)\s+(?:vinte|trinta|quarenta|cinquenta|sessenta|setenta|oitenta|noventa)\b"  # "foi em vinte e um"
    r"|\b(?:em|de|no|ano)\s+\d{2}\b"                                              # "em 19", "de 21"
    r"|\b(?:janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro"
    r"|jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)\b"                        # mês por nome
    r"|\b(?:\d+|" + _NUMERO_POR_EXTENSO + r")\s+(?:e\s+(?:meio|meia)\s+)?(?:dias?|semanas?|mes|meses|anos?)\b"  # "uns 2 anos"
    r"|\b(?:ano|mes|semana)\s+(?:passad[oa]|retrasad[oa])\b|\b(?:esse|este|neste|nesse)\s+(?:ano|mes)\b"
    r"|\b(?:ontem|anteontem)\b"
    r"|\b\d{1,2}\s+\d{1,2}\s+\d{2,4}\b|\b\d{1,2}\s+\d{4}\b|\b\d{1,2}\s+\d{2}\b")   # "10 03 2024", "03 2024", "3 24"


def _data_sem_prova(chave: str, trecho_normalizado: str) -> bool:
    # Só um número ("11", "2019") é resposta curta à pergunta da data (regra 3 do extrator): vale.
    return (chave in CAMPOS_DE_DATA and not re.fullmatch(r"\d{1,4}", trecho_normalizado)
            and not _TEM_DATA.search(trecho_normalizado))


def conferir(dados: dict[str, Any], textos_do_lead: list[str], fatos_conhecidos: dict[str, Any],
             produto: "Produto | None" = None) -> Extracao:
    """Valida cada fato: chave conhecida, valor aceito e trecho presente nas mensagens do lead."""
    if produto is None:
        from app.cerebro.produto import AuxilioAcidente
        produto = AuxilioAcidente()
    base = normalizar(" \n ".join(textos_do_lead))
    extracao = Extracao(bruto=dados)
    for item in dados.get("fatos", []):
        chave, trecho = item.get("chave", ""), str(item.get("trecho", ""))
        valor = produto.validar_valor(chave, item.get("valor"))
        trecho_normalizado = normalizar(trecho)
        if valor is None:
            extracao.rejeitados.append({**item, "motivo": "valor_nao_aceito"})
        elif not trecho_normalizado or trecho_normalizado not in base:
            extracao.rejeitados.append({**item, "motivo": "trecho_nao_encontrado"})
        elif _mes_sem_prova(chave, trecho_normalizado):
            extracao.rejeitados.append({**item, "motivo": "mes_sem_prova"})
        elif _data_sem_prova(chave, trecho_normalizado):
            extracao.rejeitados.append({**item, "motivo": "data_sem_prova"})
        elif chave == "email" and "@" not in str(valor):
            # "não tenho", "não uso": gravado em email, o contrato pedia a correção ao lead sem fim.
            extracao.rejeitados.append({**item, "motivo": "email_sem_arroba"})
        elif fatos_conhecidos.get(chave) == valor:
            continue  # já sabíamos; não é novidade
        else:
            extracao.fatos.append(FatoExtraido(chave, valor, trecho))
    extracao.sinais = [s for s in dados.get("sinais", []) if s in produto.sinais]
    intencoes = dados.get("intencoes", {}) or {}
    extracao.intencoes = {nome: bool(intencoes.get(nome)) for nome in produto.intencoes}
    return extracao


# Teto de tokens de saída do extrator. A saída é curta (alguns fatos com o trecho); numa rodada real o modelo entrou em
# repetição ("autismo" no bairro...) e só parava no teto geral (4000 na OpenAI, 16000 na Anthropic), gastando o turno
# inteiro antes de falhar. Modelos sem raciocínio (gpt-4*) param em 1500; os de raciocínio gastam tokens pensando
# (max_completion_tokens conta o raciocínio), então ficam em 4000.
MAX_TOKENS_EXTRATOR = 1500
MAX_TOKENS_EXTRATOR_RACIOCINIO = 4000
# Falhas do extrator de IA que não derrubam o turno do catálogo (tolerar_falha=True): saída cortada pelo teto ou fora
# do formato, já depois da 2ª tentativa do modelo (app/modelo.py repete uma vez). Antes, o turno ia para
# pipeline._formato_invalido e o lead era pausado já na 1ª falha. Agora o turno segue sem os fatos de IA deste lote
# (a resposta curta à última pergunta continua ligada pelo código) e fica o evento "extrator_falhou". Provedor fora do
# ar, sem crédito ou chave recusada continuam no caminho de sempre (_falha -> nova tentativa do pipeline).
FALHAS_TOLERADAS = ("saida_cortada", "saida_invalida")


def max_tokens_do_extrator(nome_modelo: str) -> int:
    return MAX_TOKENS_EXTRATOR if str(nome_modelo or "").startswith("gpt-4") else MAX_TOKENS_EXTRATOR_RACIOCINIO


def _aceita_max_tokens(modelo: Any) -> bool:
    """O gerar() do modelo aceita max_tokens? (os falsos da avaliação e o cassete não aceitam). Desembrulha o
    pipeline.ModeloQueAnota, que repassa **pedido ao modelo de verdade."""
    import inspect

    alvo = modelo
    for _ in range(5):
        interno = getattr(alvo, "__dict__", {}).get("_modelo")
        if interno is None:
            break
        alvo = interno
    try:
        return "max_tokens" in inspect.signature(alvo.gerar).parameters
    except (TypeError, ValueError, AttributeError):
        return False


async def extrair(
    modelo: Modelo,
    *,
    nome_modelo: str,
    fatos_conhecidos: dict[str, Any],
    historico: list[dict[str, str]],
    novas: list[str],
    produto: "Produto | None" = None,
    agora: datetime | None = None,
    tolerar_falha: bool = False,
) -> Extracao:
    from app.modelo import ErroModelo

    if produto is None:
        from app.cerebro.produto import AuxilioAcidente
        produto = AuxilioAcidente()
    conteudo = montar_conteudo(fatos_conhecidos, historico, novas, agora)
    extras = {"max_tokens": max_tokens_do_extrator(nome_modelo)} if _aceita_max_tokens(modelo) else {}
    textos_do_lead = novas + [m["texto"] for m in historico if m["autor"] == "lead"]
    try:
        resultado = await modelo.gerar(
            papel="extrator", sistema=sistema_do_extrator(produto), conteudo=conteudo,
            esquema=produto.esquema_extrator(), modelo=nome_modelo, esforco="low", **extras,
        )
    except ErroModelo as erro:
        if not tolerar_falha or erro.motivo not in FALHAS_TOLERADAS:
            raise
        extracao = conferir({}, textos_do_lead, fatos_conhecidos, produto)
        extracao.chamadas = list(getattr(erro, "chamadas", None) or [])
        extracao.falha = erro.motivo
        pela_pergunta(extracao, historico, novas, fatos_conhecidos, produto)
        return extracao
    extracao = conferir(resultado.dados, textos_do_lead, fatos_conhecidos, produto)
    extracao.chamadas = resultado.chamadas
    pela_pergunta(extracao, historico, novas, fatos_conhecidos, produto)
    return extracao


def _chaves_do_produto(produto: "Produto") -> set[str]:
    """Chaves que o extrator deste produto pode devolver (o enum do esquema)."""
    try:
        itens = produto.esquema_extrator()["properties"]["fatos"]["items"]["properties"]["chave"]
        return set(itens.get("enum") or [])
    except (KeyError, TypeError, AttributeError):
        return set(aa.FATOS)


def _chaves_travadas(produto: "Produto") -> set[str]:
    from app.cerebro import catalogo

    config = getattr(produto, "config", None) or {}
    motivos = catalogo.motivos_de_desqualificar(config)
    portao = [alt.partition("=")[0] for grupos in catalogo.portao_de_fatos(config).values()
              for grupo in grupos for alt in grupo]
    return resposta_curta.chaves_travadas(motivos, portao)


def pela_pergunta(extracao: Extracao, historico: list[dict[str, str]], novas: list[str],
                  fatos_conhecidos: dict[str, Any], produto: "Produto") -> Extracao:
    """Liga a resposta do lead à última pergunta da IA, sem chamar IA (app/cerebro/resposta_curta.py).

    B. Trava: fato que desqualifica, fato do portão e meses de demissão vindos do extrator de IA só ficam quando a
       pergunta da IA antes da resposta (ou a própria mensagem do lead) fala daquele assunto; senão vão para os
       rejeitados (motivo "fora_do_assunto", vira evento fato_sem_prova no turno).
    A. Resposta curta ("Não", "sim", "4 meses") à última pergunta: o código acha o fato pela pergunta e grava com
       trecho = resposta. Só a resposta (a mensagem inteira é "Não") vale mais que o extrator de IA para a mesma chave;
       começo de mensagem ("Não, nunca tive") só preenche o que o extrator deixou vazio."""
    travadas = _chaves_travadas(produto)
    ficam: list[FatoExtraido] = []
    for fato in extracao.fatos:
        if fato.chave in travadas and resposta_curta.fora_do_assunto(fato.chave, fato.trecho, historico, novas, normalizar):
            extracao.rejeitados.append({"chave": fato.chave, "valor": fato.valor, "trecho": fato.trecho,
                                        "motivo": "fora_do_assunto",
                                        "pergunta": resposta_curta.ultima_pergunta(historico)[-200:]})
        else:
            ficam.append(fato)
    extracao.fatos = ficam
    aceitas = _chaves_do_produto(produto)
    # Respostas do roteiro fora do esquema do catálogo (auxilio_doenca sempre; aposentado, advogado e sequela com o portão
    # desligado): o código anota o "Não" para a IA ver em DADOS JÁ INFORMADOS e não perguntar de novo.
    extras = {c for c in resposta_curta.SO_DO_RESOLVEDOR if c not in aceitas and c in aa.FATOS}
    for achado in resposta_curta.resolver(historico, novas, aceitas | extras, normalizar):
        valor = (aa.validar_valor(achado.chave, achado.valor) if achado.chave in extras
                 else produto.validar_valor(achado.chave, achado.valor))
        if valor is None:
            continue
        do_extrator = next((f for f in extracao.fatos if f.chave == achado.chave), None)
        if do_extrator is not None and (not achado.sozinha or do_extrator.valor == valor):
            continue                                    # o extrator de IA já trouxe (ou a resposta não é só "não")
        if do_extrator is not None:
            extracao.fatos.remove(do_extrator)
            extracao.rejeitados.append({"chave": do_extrator.chave, "valor": do_extrator.valor,
                                        "trecho": do_extrator.trecho, "motivo": "resposta_curta_diz_outro"})
        if fatos_conhecidos.get(achado.chave) == valor:
            continue                                    # já sabíamos
        extracao.fatos.append(FatoExtraido(achado.chave, valor, achado.trecho))
        extracao.resolvidos.append({"chave": achado.chave, "valor": valor, "trecho": achado.trecho,
                                    "pergunta": resposta_curta.ultima_pergunta(historico)[-200:]})
    return extracao
