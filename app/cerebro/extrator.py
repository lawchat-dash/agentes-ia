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
8. Data dita de forma relativa: converta usando a data de hoje que vem no começo do conteúdo, só até onde a expressão \
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
- muitas_objecoes: duas ou mais objeções diferentes (golpe, honorários, família, 'vou pensar') e segue resistente. \
Reclamar que a atendente repetiu a pergunta ('já te falei', 'já respondi') NÃO é objeção.
- endereco_sem_falar: recusa passar o endereço ou desvia quando pedido.
- contrato_manual: pede contrato impresso, quem assina é representante/curador, ou não consegue assinatura digital.

Intenções (true só quando estiver claro nas mensagens novas):
- pediu_humano: pede para falar com uma pessoa, atendente ou advogado.
- pediu_para_parar: pede para não receber mais mensagens.
- engano: diz que foi engano ou que não procurou o escritório.
- aceitou_honorarios: concorda de forma clara com os honorários apresentados.
- recusou: diz de forma clara que não quer seguir.
- diz_que_assinou: afirma que já assinou o contrato.
- confirmou_dados: confirma de forma clara que os dados do contrato mostrados pela IA estão certos ("sim, está certo").
- pediu_link: pede o link do contrato de novo ("manda o link de novo", "perdi o link").

Dados do contrato (fatos nome_completo, cpf, rg, estado_civil, profissao, cep, endereco, numero_casa, complemento,
bairro, cidade, uf, email, telefone_contrato, nome_menor, cpf_menor): copie como o lead escreveu. endereco é só a rua,
sem o número; numero_casa é só o número ("S/N" se não tiver); uf é a sigla do estado: se o lead escrever o nome \
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


def montar_conteudo(fatos_conhecidos: dict[str, Any], historico: list[dict[str, str]], novas: list[str],
                    agora: datetime | None = None) -> str:
    """Conteúdo do extrator. A data de hoje vai no começo para ele converter "há 3 meses" em mês e ano."""
    from app.cerebro.contexto import linha_de_hoje

    partes = [linha_de_hoje(agora), "", "FATOS CONHECIDOS:", json.dumps(fatos_conhecidos, ensure_ascii=False, sort_keys=True)]
    partes.append("\nCONVERSA ANTERIOR (mais antiga primeiro):")
    if historico:
        partes.extend(f"[{m['autor']}] {m['texto']}" for m in historico)
    else:
        partes.append("(nenhuma)")
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


async def extrair(
    modelo: Modelo,
    *,
    nome_modelo: str,
    fatos_conhecidos: dict[str, Any],
    historico: list[dict[str, str]],
    novas: list[str],
    produto: "Produto | None" = None,
    agora: datetime | None = None,
) -> Extracao:
    if produto is None:
        from app.cerebro.produto import AuxilioAcidente
        produto = AuxilioAcidente()
    conteudo = montar_conteudo(fatos_conhecidos, historico, novas, agora)
    resultado = await modelo.gerar(
        papel="extrator", sistema=sistema_do_extrator(produto), conteudo=conteudo,
        esquema=produto.esquema_extrator(), modelo=nome_modelo, esforco="low",
    )
    textos_do_lead = novas + [m["texto"] for m in historico if m["autor"] == "lead"]
    extracao = conferir(resultado.dados, textos_do_lead, fatos_conhecidos, produto)
    extracao.chamadas = resultado.chamadas
    return extracao
