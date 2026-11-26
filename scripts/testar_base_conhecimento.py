"""Teste REAL da base de conhecimento com o agente Sousa e Costa (gpt-4.1-mini, temperatura 0,5), COM e SEM a base.

O que faz:
  1. Monta uma base de teste do Sousa e Costa SÓ com o que já está no prompt do agente (avaliacao/agentes/sousa_costa.json:
     dados do escritório, honorários, FAQ, objeções, como funciona o benefício) + algumas entradas INVENTADAS, marcadas
     como teste (só a versão COM base as recebe; servem para ver se a IA usa a base e se a versão SEM inventa).
  2. Roda ~28 perguntas realistas de lead (dentro da base, fora da base, ambíguas; por etapa: sdr, período de graça,
     closer, contratos, assinatura, desqualificado) pelo turno do catálogo (app/cerebro/turno.processar), igual à produção:
       - SEM: o agente como está hoje (dados do escritório no sistema, sem base, sem a regra nova);
       - COM: o caminho do pipeline (conhecimento_indice.preparar + buscar com embedding real, bloco [n] no conteúdo,
         regra "FATOS DO ESCRITÓRIO", campo base.usados/sem_resposta, guarda de fonte).
     O extrator NÃO chama a API (responde "nada novo" localmente): o teste mede só a resposta do agente da etapa.
  3. Um juiz (gpt-4.1-mini) dá nota de concretude (0 a 10) às duas respostas e marca alucinação (fato do escritório que
     não está na base nem no prompt).
  4. Escreve avaliacao/resultados/<data>_base_conhecimento/relatorio.md (+ resultado.json) com a tabela
     pergunta × com/sem base × nota × alucinação e o custo total.

TETO DURO em US$ (--teto-usd, padrão 0,30): ANTES de cada chamada (embedding ou modelo) o pior caso dela é somado ao gasto
(entrada estimada por caracteres/3 e o máximo de saída) pelos preços de app/modelo.PRECOS_USD_POR_MILHAO; se passar do
teto, a chamada não é feita e o teste para, com o relatório do que já rodou.

Uso (da raiz do projeto, com OPENAI_API_KEY no ambiente ou no .env):
  python scripts/testar_base_conhecimento.py --falso                 # sem API: prova o script inteiro (custo simulado)
  python scripts/testar_base_conhecimento.py --teto-usd 0.30         # REAL
  python scripts/testar_base_conhecimento.py --teto-usd 0.10 --perguntas p01,p10,p13
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from app import conhecimento as base                     # noqa: E402
from app import conhecimento_indice as indice           # noqa: E402
from app import vetores                                 # noqa: E402
from app.cerebro import catalogo, turno                 # noqa: E402
from app.cerebro import produto as produtos             # noqa: E402
from app.modelo import PRECOS_USD_POR_MILHAO, ModeloOpenAI, calcular_custo   # noqa: E402

AGENTE = RAIZ / "avaliacao" / "agentes" / "sousa_costa.json"
MODELO_ETAPA = "gpt-4.1-mini"
MODELO_JUIZ = "gpt-4.1-mini"
TEMPERATURA = 0.5
MAX_SAIDA_ETAPA = 1000          # teto de tokens de saída por resposta (as respostas têm ~100-300)
MAX_SAIDA_JUIZ = 700


# ============================================================================ base de teste
# Tudo abaixo (menos INVENTADAS) foi tirado do prompt do agente: nenhuma informação nova sobre o escritório.
FAQ_DO_PROMPT: list[dict[str, Any]] = [
    {"pergunta": "Quanto o escritório cobra (honorários)?",
     "resposta": "5 salários do benefício aprovado, cada um não inferior ao salário mínimo (hoje R$ 1.621,00), mais 30% dos "
                 "atrasados (retroativos), se houver; o cliente fica com 70% dos atrasados. Os valores estão no contrato."},
    {"pergunta": "Tenho que pagar alguma coisa antes ou adiantado?",
     "resposta": "Não. Nada é cobrado antes: os honorários só são pagos depois da concessão do benefício. Você só paga se o "
                 "benefício for aprovado."},
    {"pergunta": "E se o benefício não for aprovado, pago alguma coisa?",
     "resposta": "Não. O escritório conduz até o final (via administrativa, judicial, junta de recursos) e, se esgotar as "
                 "possibilidades e o benefício não for aprovado, você não paga nenhum valor."},
    {"pergunta": "Dá para parcelar os honorários?",
     "resposta": "Sim, em até 12x sem juros no boleto, depois da concessão do benefício."},
    {"pergunta": "O que é retroativo (atrasados)?",
     "resposta": "É o valor que o INSS deveria ter pago desde a data da solicitação ou do período em que já tinha que pagar. "
                 "Pode haver retroativo de até 5 anos se a pessoa recebeu auxílio-doença."},
    {"pergunta": "Quais as vantagens do auxílio-acidente?",
     "resposta": "Renda extra mensal até a aposentadoria; você continua trabalhando normalmente; pode ter retroativo de até "
                 "5 anos se recebeu auxílio-doença."},
    {"pergunta": "Por que fazer com o escritório?",
     "resposta": "Cálculo exato feito por especialista; atendimento simples e 100% online; processo seguro e estratégico; "
                 "você só paga se o benefício for aprovado."},
    {"pergunta": "Preciso ir ao escritório? O atendimento é presencial?",
     "resposta": "O atendimento é online, pelo WhatsApp, sem fila. Presencial só para quem é de Belo Horizonte, depois de "
                 "explicar o atendimento online."},
    {"pergunta": "Onde fica o escritório?",
     "resposta": "R. Rebelo Horta, 104, São José, Belo Horizonte/MG, CEP 31.275-190."},
    {"pergunta": "Quem são os advogados? Vocês têm OAB?",
     "resposta": "Eduardo Costa Oliveira (sócio administrador, OAB/MG 150.650), Pierre Luiz de Sousa (sócio administrador, "
                 "OAB/MG 201.389) e Luciana Rodrigues de Vasconcelos (advogada associada, OAB/MG 245373). CNPJ 44.326.345/0001-05."},
    {"pergunta": "O escritório faz outros benefícios além do auxílio-acidente?",
     "resposta": "Sim. O escritório atua com todos os benefícios previdenciários, com foco principal em auxílio-acidente, e "
                 "também em diversos outros benefícios."},
    {"pergunta": "Preciso mandar RG ou e-mail para o contrato?",
     "resposta": "RG e e-mail são opcionais: se não tiver, seguimos sem. O contrato pode ser gerado sem e-mail e sem RG.",
     "papeis": ["contratos", "assinatura"]},
    {"pergunta": "Preciso imprimir o contrato?",
     "resposta": "Sim, é necessário imprimir todas as páginas, assinar e depois enviar a foto para a equipe.",
     "papeis": ["assinatura"]},
    {"pergunta": "O link do contrato não abre ou demora a carregar.",
     "resposta": "Costuma ser instabilidade na internet: tente atualizar a página, usar outro navegador, testar no Wi-Fi ou em "
                 "outro aparelho.", "papeis": ["assinatura"]},
    {"pergunta": "Minha empresa vai ficar sabendo? Vou perder o emprego?",
     "resposta": "O auxílio-acidente não exige afastamento nem impede de continuar trabalhando; o emprego não é afetado, não "
                 "prejudica a empresa e, se não quiser, a empresa não precisa ficar sabendo."},
    {"pergunta": "Não tenho documentação médica atualizada.",
     "resposta": "A equipe orienta passo a passo para conseguir a documentação médica necessária."},
]
OBJECOES_DO_PROMPT: list[dict[str, Any]] = [
    {"objecao": "Tenho medo de golpe / já fui enganado",
     "resposta": "Entendo o receio. Tudo é feito por contrato e você não paga nada para iniciar. O maior risco é continuar sem "
                 "receber um direito seu. Envie os dados do escritório (CNPJ, OAB dos advogados, endereço)."},
    {"objecao": "Quero presencial / de onde vocês são?",
     "resposta": "O atendimento online existe para agilizar, sem fila. O contrato é formal e o processo é seguro. Envie os dados do escritório."},
    {"objecao": "Vou desistir",
     "resposta": "Desistir agora significa continuar com a sequela e sem o benefício que poderia ajudar; e não paga nada para iniciar."},
    {"objecao": "Outro advogado faz mais barato",
     "resposta": "Comparar é um direito. O auxílio-acidente exige cálculos e estratégia; quando é feito errado, o INSS nega. "
                 "Aqui a equipe é especializada."},
    {"objecao": "Achei caro / não consigo pagar",
     "resposta": "Só paga depois da aprovação e ainda pode parcelar. Nada sai do bolso agora."},
    {"objecao": "Preciso pensar",
     "resposta": "Os retroativos diminuem com o tempo, e você não assume risco para iniciar."},
    {"objecao": "Demora? Não quero perder tempo",
     "resposta": "O processo só anda depois da formalização. Quem inicia cedo recebe cedo."},
    {"objecao": "Já tentei e negaram",
     "resposta": "É comum: normalmente negam porque o pedido foi montado errado. Aqui fazemos de forma estratégica."},
    {"objecao": "Não tenho tempo agora",
     "resposta": "A formalização leva poucos minutos e você resolve pelo celular."},
]
# Entradas INVENTADAS (não existem no prompt do agente): só a versão COM base recebe. Servem de prova de uso da base.
INVENTADAS: list[dict[str, Any]] = [
    {"pergunta": "Qual o horário de atendimento?",
     "resposta": "O atendimento pelo WhatsApp é de segunda a sexta, das 8h às 18h, e aos sábados das 8h às 12h."},
    {"pergunta": "Tem estacionamento no escritório?",
     "resposta": "Sim, há 2 vagas para clientes no estacionamento conveniado ao lado do escritório (presencial só com horário marcado)."},
    {"pergunta": "Vocês ajudam a me preparar para a perícia do INSS?",
     "resposta": "Sim: o escritório envia pelo WhatsApp um roteiro de preparação para a perícia 2 dias antes da data marcada."},
    {"pergunta": "Como vou acompanhar o andamento do processo?",
     "resposta": "O cliente recebe uma atualização do andamento a cada 30 dias pelo WhatsApp."},
    {"pergunta": "O link de assinatura expira?",
     "resposta": "O link de assinatura vale por 7 dias; depois disso a equipe gera um novo.", "papeis": ["contratos", "assinatura"]},
]
DOCUMENTO_BENEFICIO = """# Como funciona o auxílio-acidente (do roteiro do Closer)

## Vantagens
Renda extra mensal até a aposentadoria. Você continua trabalhando normalmente. Pode ter retroativo de até 5 anos se recebeu auxílio-doença.

## Regras de honorários
Os honorários jamais podem ser inferiores a 5 salários mínimos (R$ 1.621,00 em 2026). O escritório recebe 30% dos atrasados
(retroativos) somados a 5 salários do valor do benefício aprovado, não inferiores ao salário mínimo cada um. Sempre recebidos
após a concessão do benefício. Todos os valores são descritos em contrato. Divididos em 12x sem juros no boleto.
Não há taxas, negociação, redução nem valores antecipados.

## Como o escritório conduz
O escritório conduz até o final: via administrativa, via judicial e junta de recursos. Se esgotar todas as possibilidades e o
benefício não for aprovado, o cliente não paga nenhum valor. O retroativo é o valor que o INSS deveria ter pago desde a
solicitação ou desde quando já tinha que pagar; o escritório analisa e, se houver direito, solicita.
"""


def conhecimento_de_teste(dados_escritorio: str) -> dict[str, Any]:
    return {"dados_escritorio": dados_escritorio, "faq": FAQ_DO_PROMPT + INVENTADAS, "objecoes": OBJECOES_DO_PROMPT}


# ============================================================================ perguntas
@dataclass
class Pergunta:
    id: str
    etapa: str
    categoria: str          # dentro | fora | ambigua | teste (só a base inventada responde)
    texto: str
    espera: str             # o que uma boa resposta faz (vai para o juiz)


PERGUNTAS: list[Pergunta] = [
    Pergunta("p01", "sdr", "dentro", "vocês cobram alguma coisa pra analisar meu caso?", "dizer que não paga nada antes; só paga se aprovado"),
    Pergunta("p02", "sdr", "dentro", "onde fica o escritório de vocês?", "endereço em BH ou o áudio do endereço do roteiro; atendimento online"),
    Pergunta("p03", "sdr", "teste", "qual o horário de atendimento de vocês?", "horário só existe na base inventada"),
    Pergunta("p04", "sdr", "dentro", "preciso ir até aí pessoalmente?", "atendimento online; presencial só BH"),
    Pergunta("p05", "sdr", "ambigua", "vocês fazem aposentadoria por invalidez também?", "atuam com benefícios previdenciários; foco em auxílio-acidente"),
    Pergunta("p06", "sdr", "fora", "quanto eu vou receber por mês de auxílio-acidente?", "não inventar valor do benefício; equipe calcula"),
    Pergunta("p07", "sdr", "teste", "vocês têm estacionamento aí?", "estacionamento só existe na base inventada"),
    Pergunta("p08", "periododegraca", "ambigua", "fiquei uns 2 anos sem contribuir, ainda tenho direito?", "não afirmar direito; seguir as perguntas do roteiro"),
    Pergunta("p09", "periododegraca", "fora", "seguro-desemprego conta como contribuição?", "não inventar regra; seguir roteiro ou confirmar com a equipe"),
    Pergunta("p10", "closer", "dentro", "quanto vocês cobram?", "5 salários + 30% dos atrasados, só no êxito"),
    Pergunta("p11", "closer", "dentro", "tenho que pagar alguma coisa adiantado?", "não; só depois da concessão"),
    Pergunta("p12", "closer", "dentro", "e se eu perder, pago alguma coisa?", "não paga nada se não for aprovado"),
    Pergunta("p13", "closer", "dentro", "isso não é golpe não? já me enganaram uma vez", "objeção de golpe + dados do escritório"),
    Pergunta("p14", "closer", "dentro", "outro advogado me falou que cobra menos", "objeção 4 sem desconto"),
    Pergunta("p15", "closer", "dentro", "dá pra parcelar os honorários?", "12x sem juros no boleto"),
    Pergunta("p16", "closer", "fora", "quanto tempo demora pra sair o benefício?", "não inventar prazo"),
    Pergunta("p17", "closer", "dentro", "vocês têm OAB? qual o nome do advogado?", "nomes e OAB dos advogados"),
    Pergunta("p18", "closer", "teste", "como eu vou acompanhar o andamento do processo?", "atualização a cada 30 dias (só na base inventada)"),
    Pergunta("p19", "closer", "teste", "vocês me ajudam a me preparar pra perícia?", "roteiro 2 dias antes (só na base inventada)"),
    Pergunta("p20", "contratos", "dentro", "preciso mandar foto do RG?", "RG opcional; não falar de documentação"),
    Pergunta("p21", "contratos", "dentro", "não tenho e-mail, tem problema?", "segue sem e-mail"),
    Pergunta("p22", "contratos", "fora", "esse contrato tem multa se eu desistir?", "não inventar cláusula; confirmar com a equipe"),
    Pergunta("p23", "assinatura", "dentro", "preciso imprimir o contrato?", "sim, imprimir todas as páginas (roteiro)"),
    Pergunta("p24", "assinatura", "teste", "o link de assinatura expira?", "7 dias (só na base inventada)"),
    Pergunta("p25", "assinatura", "dentro", "minha empresa vai ficar sabendo disso?", "não precisa saber; não afeta o emprego"),
    Pergunta("p26", "assinatura", "dentro", "o link não abre aqui, o que eu faço?", "atualizar, outro navegador, Wi-Fi"),
    Pergunta("p27", "desqualificado", "dentro", "vocês fazem outros tipos de ação?", "diversos outros benefícios"),
    Pergunta("p28", "closer", "fora", "vocês dão desconto se eu pagar à vista?", "sem desconto nem negociação"),
]

# Um pedaço de conversa inventado por etapa (nenhum dado de lead real), para a pergunta cair no meio do atendimento.
HISTORICOS: dict[str, list[dict[str, str]]] = {
    "sdr": [{"autor": "lead", "texto": "oi, vi o anúncio sobre auxílio acidente"},
            {"autor": "você", "texto": "Olá! Me chamo Ana, do escritório Sousa e Costa Advogados. Me conta como aconteceu o acidente?"},
            {"autor": "lead", "texto": "caí de moto indo pro trabalho e quebrei o braço"},
            {"autor": "você", "texto": "Sinto muito por isso. Em qual ano aconteceu o acidente?"}],
    "periododegraca": [{"autor": "você", "texto": "Agora vou confirmar algumas informações importantes sobre seu vínculo com o INSS, tudo bem?"},
                       {"autor": "lead", "texto": "tudo bem"},
                       {"autor": "você", "texto": "Qual foi a data da sua última contribuição ao INSS, mesmo que aproximada?"}],
    "closer": [{"autor": "você", "texto": "Maravilha! Nós podemos te ajudar no seu caso."},
               {"autor": "você", "texto": "Conseguiu entender certinho como funciona o benefício?"},
               {"autor": "lead", "texto": "entendi sim"},
               {"autor": "você", "texto": "Essas vantagens fariam diferença no seu dia a dia?"}],
    "contratos": [{"autor": "você", "texto": "Excelente! Por gentileza, me informe seu nome completo para darmos continuidade à formalização."},
                  {"autor": "lead", "texto": "José da Silva Teste"},
                  {"autor": "você", "texto": "Obrigada, José! Agora me passa o seu CPF?"}],
    "assinatura": [{"autor": "você", "texto": "Prontinho! O contrato foi enviado aqui pelo WhatsApp. É só abrir o link e assinar."},
                   {"autor": "lead", "texto": "recebi"}],
    "desqualificado": [{"autor": "você", "texto": "Analisei com atenção o que você nos contou e, neste momento, pelas regras atuais, "
                                                 "você não se enquadra nos critérios para esse benefício específico."}],
}


# ============================================================================ teto duro
class TetoAtingido(Exception):
    pass


@dataclass
class Caixa:
    """Gasto em US$ pelos preços de app/modelo.PRECOS_USD_POR_MILHAO. `reservar` antes de cada chamada (pior caso)."""
    teto: float
    gasto: float = 0.0
    chamadas: list[dict[str, Any]] = field(default_factory=list)
    parou: str | None = None

    def preco(self, modelo: str) -> tuple[float, float, float]:
        if modelo not in PRECOS_USD_POR_MILHAO:
            raise TetoAtingido(f"modelo sem preço em PRECOS_USD_POR_MILHAO: {modelo} (não dá para garantir o teto)")
        return PRECOS_USD_POR_MILHAO[modelo]

    def reservar(self, modelo: str, tokens_entrada: int, tokens_saida: int) -> float:
        entrada, saida, _cache = self.preco(modelo)
        pior = (tokens_entrada * entrada + tokens_saida * saida) / 1_000_000
        if self.gasto + pior > self.teto:
            self.parou = (f"a próxima chamada ({modelo}, pior caso US$ {pior:.4f}) passaria do teto: "
                          f"gasto US$ {self.gasto:.4f} de US$ {self.teto:.2f}")
            raise TetoAtingido(self.parou)
        return pior

    def somar(self, papel: str, modelo: str, entrada: int, saida: int, cache: int) -> float:
        base_modelo = modelo if modelo in PRECOS_USD_POR_MILHAO else next(
            (m for m in PRECOS_USD_POR_MILHAO if modelo.startswith(m + "-")), modelo)
        custo = calcular_custo(base_modelo, entrada, saida, cache)
        self.gasto += custo
        self.chamadas.append({"papel": papel, "modelo": base_modelo, "entrada": entrada, "saida": saida, "cache": cache,
                              "custo_usd": round(custo, 6)})
        return custo


def _tokens_estimados(texto: str) -> int:
    return math.ceil(len(texto) / 3) + 20                 # conservador: português costuma dar ~4 caracteres por token


class ClienteComTeto:
    """Embrulha o cliente da OpenAI (o de verdade ou o falso): toda chamada passa pela Caixa antes e depois."""

    def __init__(self, interno: Any, caixa: Caixa) -> None:
        self._interno, self.caixa = interno, caixa
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._chat))
        self.embeddings = SimpleNamespace(create=self._embeddings)

    async def _chat(self, **parametros: Any) -> Any:
        modelo = parametros["model"]
        nome = parametros.get("response_format", {}).get("json_schema", {}).get("name", "")
        maximo = int(parametros.get("max_completion_tokens") or 4000)
        teto_saida = MAX_SAIDA_JUIZ if nome == "saida_juiz" else MAX_SAIDA_ETAPA
        if maximo > teto_saida:
            parametros["max_completion_tokens"] = maximo = teto_saida
        texto = "".join(str(m.get("content") or "") for m in parametros["messages"])
        texto += json.dumps(parametros.get("response_format") or {}, ensure_ascii=False)
        self.caixa.reservar(modelo, _tokens_estimados(texto), maximo)
        resposta = await self._interno.chat.completions.create(**parametros)
        uso = resposta.usage
        cache = getattr(getattr(uso, "prompt_tokens_details", None), "cached_tokens", 0) or 0
        self.caixa.somar(nome.replace("saida_", "") or "chat", getattr(resposta, "model", modelo) or modelo,
                         max(0, (uso.prompt_tokens or 0) - cache), uso.completion_tokens or 0, cache)
        return resposta

    async def _embeddings(self, **parametros: Any) -> Any:
        modelo = parametros["model"]
        entradas = parametros["input"] if isinstance(parametros["input"], list) else [parametros["input"]]
        self.caixa.reservar(modelo, sum(_tokens_estimados(t) for t in entradas), 0)
        resposta = await self._interno.embeddings.create(**parametros)
        self.caixa.somar("embedding", modelo, getattr(resposta.usage, "total_tokens", 0) or 0, 0, 0)
        return resposta


# ============================================================================ cliente falso (--falso): mesma rota, sem rede
def _vetor_por_palavras(texto: str, dimensoes: int = vetores.DIMENSOES) -> list[float]:
    v = [0.0] * dimensoes
    for palavra in set(base.palavras_de_conteudo(texto)):
        raiz = palavra[:6]
        v[int(hashlib.md5(raiz.encode()).hexdigest(), 16) % dimensoes] += 1.0
    return v


class ClienteFalso:
    """Imita chat.completions e embeddings da OpenAI: respostas determinísticas e `usage` plausível (custo simulado)."""

    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._chat))
        self.embeddings = SimpleNamespace(create=self._embeddings)

    @staticmethod
    def _uso(entrada: str, saida: str, cache: int = 0) -> Any:
        return SimpleNamespace(prompt_tokens=len(entrada) // 4, completion_tokens=max(1, len(saida) // 4),
                               prompt_tokens_details=SimpleNamespace(cached_tokens=cache), total_tokens=len(entrada) // 4)

    async def _embeddings(self, **parametros: Any) -> Any:
        entradas = parametros["input"]
        dados = [SimpleNamespace(embedding=_vetor_por_palavras(t)) for t in entradas]
        return SimpleNamespace(data=dados, usage=SimpleNamespace(total_tokens=sum(len(t) // 4 for t in entradas)))

    async def _chat(self, **parametros: Any) -> Any:
        sistema, conteudo = (m["content"] for m in parametros["messages"])
        nome = parametros["response_format"]["json_schema"]["name"]
        esquema = parametros["response_format"]["json_schema"]["schema"]
        dados = self._juiz(conteudo) if nome == "saida_juiz" else self._etapa(conteudo, esquema)
        texto = json.dumps(dados, ensure_ascii=False)
        mensagem = SimpleNamespace(content=texto, refusal=None)
        return SimpleNamespace(model=parametros["model"], usage=self._uso(sistema + conteudo, texto),
                               choices=[SimpleNamespace(message=mensagem, finish_reason="stop")])

    @staticmethod
    def _etapa(conteudo: str, esquema: dict[str, Any]) -> dict[str, Any]:
        pergunta = conteudo.split("MENSAGENS NOVAS DO LEAD:")[-1].strip().splitlines()[0].lstrip("- ").strip()
        achado = re.search(r"^\[1\] .*\n((?:    .*\n?)+)", conteudo, re.MULTILINE)
        com_base = "base" in esquema.get("properties", {})
        if achado:
            primeira = achado.group(1).strip().splitlines()[-1].strip()
            primeira = primeira.split(":", 1)[-1].strip() if primeira.lower().startswith(("resposta:", "como responder:")) else primeira
            texto, usados, sem = f"Sobre isso: {primeira}", [1], ""
        else:
            texto, usados, sem = "Vou confirmar essa informação com a equipe e já te retorno.", [], pergunta if com_base else ""
        dados: dict[str, Any] = {"mensagens": [{"texto": texto}], "transferir_para": "", "ferramenta": ""}
        if "notificacao" in esquema.get("properties", {}):
            dados["notificacao"] = ""
        if com_base:
            dados["base"] = {"usados": usados, "sem_resposta": sem}
        return dados

    @staticmethod
    def _juiz(conteudo: str) -> dict[str, Any]:
        fontes = conteudo.split("RESPOSTA SEM BASE:")[0]

        def nota(resposta: str) -> dict[str, Any]:
            inventado = base.fato_sem_fonte([resposta], [fontes]) or ""
            concreta = 3 if "confirmar" in resposta else 7
            return {"nota": concreta, "alucinacao": bool(inventado), "fato_inventado": inventado,
                    "comentario": "juiz falso (heurística local)"}

        sem = conteudo.split("RESPOSTA SEM BASE:")[1].split("RESPOSTA COM BASE:")[0]
        com = conteudo.split("RESPOSTA COM BASE:")[1]
        return {"sem": nota(sem), "com": nota(com), "melhor": "com" if "confirmar" not in com else "empate"}


# ============================================================================ o turno
class SemExtrator:
    """O extrator responde localmente (nada novo, nenhum sinal): o teste mede só o agente da etapa."""

    def __init__(self, interno: Any) -> None:
        self._interno = interno

    async def gerar(self, *, papel: str, **kw: Any) -> Any:
        if papel == "extrator":
            from app.modelo import Resultado
            return Resultado(dados={"fatos": [], "sinais": [], "intencoes": {i: False for i in catalogo.INTENCOES}}, chamadas=[])
        return await self._interno.gerar(papel=papel, **kw)


@dataclass
class Ambiente:
    snapshot: dict[str, Any]
    produto: Any
    instrucoes: dict[str, str]
    honorarios: str
    dados_escritorio: str
    conhecimento: dict[str, Any]
    indexados: list[dict[str, Any]]
    vetorizador: Any
    cache: vetores.CacheDeConsultas
    modelo: Any


async def preparar_ambiente(cliente: Any) -> Ambiente:
    snapshot = json.loads(AGENTE.read_text(encoding="utf-8"))
    agente = snapshot["agente"]
    config = agente["config"]
    produto = produtos.carregar("catalogo", config)
    dados = (config.get("conhecimento") or {}).get("dados_escritorio") or ""
    conhecimento = conhecimento_de_teste(dados)
    vetorizador = vetores.VetorizadorOpenAI(cliente)
    # Indexação: FAQ/objeções (um trecho por item) + o documento do benefício (trechos com título), vetorizados uma vez.
    itens = base.itens_da_config(conhecimento)
    itens += [{"documento": "Como funciona o auxílio-acidente", "fonte": "documento", "titulo": titulo, "conteudo": texto,
               "papeis": [], "id_documento": "doc-beneficio"}
              for titulo, texto in base.dividir_com_titulo("Como funciona o auxílio-acidente", DOCUMENTO_BENEFICIO)]
    resultado = await vetorizador.vetorizar([i["conteudo"] for i in itens])
    indexados = [{**i, "id": f"t{n:02d}", "hash": vetores.hash_do_texto(vetorizador.modelo, i["conteudo"]), "vetor": v}
                 for n, (i, v) in enumerate(zip(itens, resultado.vetores))]
    return Ambiente(snapshot=snapshot, produto=produto,
                    instrucoes={e["codigo"]: e.get("instrucao") for e in agente["etapas"]},
                    honorarios=config.get("honorarios") or "", dados_escritorio=dados, conhecimento=conhecimento,
                    indexados=indexados, vetorizador=vetorizador, cache=vetores.CacheDeConsultas(),
                    modelo=SemExtrator(ModeloOpenAI(cliente)))


async def um_turno(amb: Ambiente, p: Pergunta, com_base: bool) -> dict[str, Any]:
    historico = HISTORICOS.get(p.etapa, [])
    if com_base:
        # O mesmo caminho do pipeline (Atendimento._conhecimento): fixo × buscado e a busca pela fala nova.
        preparo = indice.preparar(amb.conhecimento, p.etapa, indexados=amb.indexados, modelo_vetor=amb.vetorizador.modelo)
        limites = indice.limites(amb.conhecimento)
        busca = await indice.buscar(preparo.candidatos, [p.texto], papel=p.etapa,
                                    ultima_pergunta_ia=base.ultima_pergunta_da_ia(historico), vetorizador=amb.vetorizador,
                                    cache=amb.cache, minimo=limites["minimo"], teto=limites["teto"], quantos=limites["quantos"])
        conhecimento = {**preparo.fixo, "base": True, "_busca": busca}
    else:
        busca = None
        conhecimento = {"dados_escritorio": amb.dados_escritorio}          # o agente como está hoje
    entrada = turno.Entrada(
        escritorio=amb.snapshot["escritorio"]["nome"], agente=amb.snapshot["agente"]["nome"], etapa=p.etapa,
        novas=[p.texto], historico=historico, instrucoes=amb.instrucoes, honorarios=amb.honorarios, produto=amb.produto,
        modelo_extrator=MODELO_ETAPA, modelo_etapa=MODELO_ETAPA, modelo_auditor=None, conhecimento=conhecimento,
        temperatura=TEMPERATURA, agora=datetime(2026, 11, 25, 10, 0))
    inicio = time.monotonic()
    saida = await turno.processar(amb.modelo, entrada)
    textos = [m.get("texto") or f"[mídia: {m.get('chave') or m.get('url')}]" for m in saida.mensagens]
    registro = saida.contexto.get("conhecimento") or {}
    return {"situacao": saida.situacao, "motivo": saida.motivo, "textos": textos, "segundos": round(time.monotonic() - inicio, 1),
            "reprovacoes": [r for tentativa in saida.reprovacoes for r in tentativa],
            "busca": {"modo": busca.modo, "consulta": busca.consulta,
                      "trechos": [{"titulo": t.titulo or t.documento, "fonte": t.fonte, "nota": t.nota} for t in busca.trechos]}
            if busca else None,
            "usados": registro.get("usados", []), "sem_resposta": registro.get("sem_resposta", "")}


# ============================================================================ juiz
ESQUEMA_NOTA = {"type": "object", "properties": {
    "nota": {"type": "integer"}, "alucinacao": {"type": "boolean"}, "fato_inventado": {"type": "string"},
    "comentario": {"type": "string"}}, "required": ["nota", "alucinacao", "fato_inventado", "comentario"],
    "additionalProperties": False}
ESQUEMA_JUIZ = {"type": "object", "properties": {"sem": ESQUEMA_NOTA, "com": ESQUEMA_NOTA,
                                                 "melhor": {"type": "string", "enum": ["sem", "com", "empate"]}},
                "required": ["sem", "com", "melhor"], "additionalProperties": False}
SISTEMA_JUIZ = """Você avalia respostas de uma IA de atendimento (WhatsApp) de um escritório de advocacia previdenciária.
Para a mesma pergunta do lead há duas respostas: SEM base de conhecimento e COM base de conhecimento.

Dê a cada uma:
- "nota" de 0 a 10 de CONCRETUDE: responde de verdade a pergunta, com a informação específica e correta das fontes
  (10); vaga, evasiva ou que ignora a pergunta (0 a 4). Quando a informação NÃO está em nenhuma fonte, dizer com
  honestidade que vai confirmar com a equipe é o certo (6 a 8); inventar é 0 a 2. Quando a informação está nas fontes,
  "vou confirmar com a equipe" vale no máximo 4.
- "alucinacao": true se a resposta afirma um FATO DO ESCRITÓRIO (valor, porcentagem, prazo, horário, endereço, serviço,
  regra de atendimento, documento exigido, condição do contrato) que não está nas fontes que aquela resposta tinha.
  A resposta SEM base tinha só as FONTES DO PROMPT; a resposta COM base tinha as FONTES DO PROMPT e as FONTES SÓ DA BASE.
  Explicação geral sobre o INSS sem número nem promessa não é alucinação. Seguir o roteiro (fazer a pergunta da etapa,
  mandar um link de mídia do roteiro) não é alucinação.
- "fato_inventado": o trecho inventado (vazio se não houver). "comentario": 1 frase.
E "melhor": qual resposta é melhor para o lead (ou "empate")."""


def fontes_do_juiz(amb: Ambiente) -> str:
    do_prompt = [f"- {i['pergunta']}: {i['resposta']}" for i in FAQ_DO_PROMPT]
    do_prompt += [f"- Objeção \"{o['objecao']}\": {o['resposta']}" for o in OBJECOES_DO_PROMPT]
    so_base = [f"- {i['pergunta']}: {i['resposta']}" for i in INVENTADAS]
    return ("FONTES DO PROMPT (o agente tem isto no roteiro):\nDADOS DO ESCRITÓRIO: " + amb.dados_escritorio
            + "\nHONORÁRIOS: " + amb.honorarios + "\n" + "\n".join(do_prompt) + "\n" + DOCUMENTO_BENEFICIO
            + "\n\nFONTES SÓ DA BASE (inventadas para o teste; só a resposta COM base as recebeu):\n" + "\n".join(so_base))


async def julgar(amb: Ambiente, cliente: Any, p: Pergunta, sem: dict[str, Any], com: dict[str, Any], fontes: str) -> dict[str, Any]:
    conteudo = (f"{fontes}\n\nETAPA DO ATENDIMENTO: {p.etapa}\nCONVERSA ANTES:\n"
                + "\n".join(f"{m['autor']}: {m['texto']}" for m in HISTORICOS.get(p.etapa, []))
                + f"\n\nPERGUNTA DO LEAD: {p.texto}\nO QUE SE ESPERA: {p.espera}\n\n"
                + "RESPOSTA SEM BASE:\n" + "\n".join(sem["textos"]) + "\n\nRESPOSTA COM BASE:\n" + "\n".join(com["textos"]))
    resultado = await ModeloOpenAI(cliente).gerar(papel="juiz", sistema=SISTEMA_JUIZ, conteudo=conteudo, esquema=ESQUEMA_JUIZ,
                                                  modelo=MODELO_JUIZ, temperatura=0, max_tokens=MAX_SAIDA_JUIZ)
    return resultado.dados


# ============================================================================ relatório
def _celula(texto: str, limite: int = 220) -> str:
    texto = " ".join(str(texto or "").split()).replace("|", "/")
    return texto if len(texto) <= limite else texto[: limite - 1] + "…"


def escrever_relatorio(pasta: Path, linhas: list[dict[str, Any]], caixa: Caixa, falso: bool, teto: float) -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    julgadas = [l for l in linhas if l.get("juiz")]
    media = lambda lado: (sum(l["juiz"][lado]["nota"] for l in julgadas) / len(julgadas)) if julgadas else 0.0  # noqa: E731
    aluc = lambda lado: sum(1 for l in julgadas if l["juiz"][lado]["alucinacao"])                              # noqa: E731
    por_papel: dict[str, float] = {}
    for c in caixa.chamadas:
        por_papel[c["papel"]] = por_papel.get(c["papel"], 0.0) + c["custo_usd"]
    partes = [f"# Base de conhecimento: COM × SEM — Sousa e Costa ({'FALSO, sem API' if falso else 'REAL'})", "",
              f"{datetime.now():%d/%m/%Y %H:%M}. Agente: `{AGENTE.relative_to(RAIZ)}` · etapa {MODELO_ETAPA} a {TEMPERATURA} · "
              f"juiz {MODELO_JUIZ} · extrator local (sem API).", ""]
    if falso:
        partes += ["> Rodada **falsa**: cliente da OpenAI simulado (respostas e embeddings determinísticos, custo simulado pelos "
                   "tokens estimados). Prova o script e o teto, não a qualidade.", ""]
    partes += ["## Resumo", "",
               "| | SEM base | COM base |", "|---|---|---|",
               f"| Nota média de concretude (0–10) | {media('sem'):.1f} | {media('com'):.1f} |",
               f"| Respostas com alucinação | {aluc('sem')} de {len(julgadas)} | {aluc('com')} de {len(julgadas)} |",
               f"| \"Melhor\" segundo o juiz | {sum(1 for l in julgadas if l['juiz']['melhor'] == 'sem')} | "
               f"{sum(1 for l in julgadas if l['juiz']['melhor'] == 'com')} (empates: {sum(1 for l in julgadas if l['juiz']['melhor'] == 'empate')}) |",
               f"| Perguntas sem resposta registradas (lacunas) | — | {sum(1 for l in linhas if (l.get('com') or {}).get('sem_resposta'))} |",
               "", f"Perguntas rodadas: {len(linhas)} de {len(PERGUNTAS)} · julgadas: {len(julgadas)}.", ""]
    for categoria in ("dentro", "fora", "ambigua", "teste"):
        grupo = [l for l in julgadas if l["categoria"] == categoria]
        if grupo:
            partes.append(f"- **{categoria}** ({len(grupo)}): nota SEM {sum(l['juiz']['sem']['nota'] for l in grupo) / len(grupo):.1f} · "
                          f"COM {sum(l['juiz']['com']['nota'] for l in grupo) / len(grupo):.1f} · alucinações SEM "
                          f"{sum(l['juiz']['sem']['alucinacao'] for l in grupo)} · COM {sum(l['juiz']['com']['alucinacao'] for l in grupo)}")
    partes += ["", "## Custo", "",
               f"**Total: US$ {caixa.gasto:.4f}** (teto US$ {teto:.2f}; {len(caixa.chamadas)} chamadas"
               + (", custo simulado" if falso else "") + ").", ""]
    partes += [f"- {papel}: US$ {valor:.4f}" for papel, valor in sorted(por_papel.items())]
    if caixa.parou:
        partes += ["", f"**Parou pelo teto:** {caixa.parou}."]
    partes += ["", "## Pergunta × com/sem base", "",
               "| # | Etapa | Tipo | Pergunta | Resposta SEM base | Nota | Aluc. | Resposta COM base | Nota | Aluc. | Trechos [nota] / usados |",
               "|---|---|---|---|---|---|---|---|---|---|---|"]
    for l in linhas:
        juiz = l.get("juiz") or {}
        sem, com = l.get("sem") or {}, l.get("com") or {}
        js, jc = juiz.get("sem") or {}, juiz.get("com") or {}
        trechos = "; ".join(f"{t['titulo'][:40]} [{t['nota']}]" for t in (com.get("busca") or {}).get("trechos", [])) or "nada"
        if com.get("usados"):
            trechos += f" · usou {com['usados']}"
        if com.get("sem_resposta"):
            trechos += f" · sem resposta: {com['sem_resposta']}"
        alucina = lambda j: ("**sim**: " + _celula(j.get("fato_inventado"), 60)) if j.get("alucinacao") else ("não" if j else "—")  # noqa: E731
        partes.append(f"| {l['id']} | {l['etapa']} | {l['categoria']} | {_celula(l['pergunta'], 80)} | {_celula(' / '.join(sem.get('textos', [])))} | "
                      f"{js.get('nota', '—')} | {alucina(js)} | {_celula(' / '.join(com.get('textos', [])))} | {jc.get('nota', '—')} | "
                      f"{alucina(jc)} | {_celula(trechos, 200)} |")
    partes += ["", "## Comentários do juiz", ""]
    partes += [f"- **{l['id']}** SEM: {_celula(l['juiz']['sem']['comentario'], 200)} · COM: {_celula(l['juiz']['com']['comentario'], 200)}"
               for l in julgadas]
    partes += ["", "## Base de teste", "",
               f"- {len(FAQ_DO_PROMPT)} perguntas frequentes e {len(OBJECOES_DO_PROMPT)} objeções tiradas do prompt do agente, "
               "mais o documento \"Como funciona o auxílio-acidente\" (do roteiro do Closer).",
               f"- {len(INVENTADAS)} entradas **inventadas, marcadas como teste** (só a versão COM base recebe): "
               + "; ".join(i["pergunta"] for i in INVENTADAS) + "."]
    relatorio = pasta / "relatorio.md"
    relatorio.write_text("\n".join(partes) + "\n", encoding="utf-8")
    (pasta / "resultado.json").write_text(json.dumps({"falso": falso, "teto_usd": teto, "gasto_usd": round(caixa.gasto, 6),
                                                      "parou": caixa.parou, "chamadas": caixa.chamadas, "linhas": linhas},
                                                     ensure_ascii=False, indent=2), encoding="utf-8")
    return relatorio


# ============================================================================ principal
async def rodar(args: argparse.Namespace) -> int:
    caixa = Caixa(teto=args.teto_usd)
    if args.falso:
        interno: Any = ClienteFalso()
    else:
        from app.config import _carregar_env_local
        _carregar_env_local(str(RAIZ / ".env"))
        if not os.environ.get("OPENAI_API_KEY"):
            print("Falta OPENAI_API_KEY (no ambiente ou no .env). Nada foi chamado.")
            return 2
        import openai
        # Sem novas tentativas escondidas no cliente: cada requisição (inclusive a repetida) passa pela Caixa antes.
        interno = openai.AsyncOpenAI(max_retries=0, timeout=90)
    cliente = ClienteComTeto(interno, caixa)
    escolhidas = [p for p in PERGUNTAS if not args.perguntas or p.id in set(args.perguntas.split(","))]
    nome = f"{datetime.now():%Y-%m-%d_%H%M}_base_conhecimento" + ("_falso" if args.falso else "")
    pasta = RAIZ / "avaliacao" / "resultados" / nome
    n = 2
    while pasta.exists():                                   # duas rodadas no mesmo minuto: não sobrescreve
        pasta, n = RAIZ / "avaliacao" / "resultados" / f"{nome}-{n}", n + 1
    linhas: list[dict[str, Any]] = []
    try:
        amb = await preparar_ambiente(cliente)
        fontes = fontes_do_juiz(amb)
        print(f"Base indexada: {len(amb.indexados)} trechos · gasto US$ {caixa.gasto:.5f}")
        for p in escolhidas:
            linha: dict[str, Any] = {"id": p.id, "etapa": p.etapa, "categoria": p.categoria, "pergunta": p.texto}
            linhas.append(linha)
            linha["sem"] = await um_turno(amb, p, com_base=False)
            linha["com"] = await um_turno(amb, p, com_base=True)
            linha["juiz"] = await julgar(amb, cliente, p, linha["sem"], linha["com"], fontes)
            j = linha["juiz"]
            print(f"{p.id} [{p.etapa}/{p.categoria}] SEM {j['sem']['nota']}{' ALUC' if j['sem']['alucinacao'] else ''} · "
                  f"COM {j['com']['nota']}{' ALUC' if j['com']['alucinacao'] else ''} · gasto US$ {caixa.gasto:.4f}")
    except TetoAtingido as erro:
        print(f"PAROU: {erro}")
    relatorio = escrever_relatorio(pasta, linhas, caixa, args.falso, args.teto_usd)
    print(f"\nCusto total: US$ {caixa.gasto:.4f} (teto US$ {args.teto_usd:.2f}{', simulado' if args.falso else ''})")
    print(f"Relatório: {relatorio}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Teste real da base de conhecimento (COM × SEM) com teto duro em US$.")
    parser.add_argument("--teto-usd", type=float, default=0.30, help="para ANTES de passar deste gasto (padrão 0,30)")
    parser.add_argument("--falso", action="store_true", help="sem API: cliente simulado, prova o script e o teto")
    parser.add_argument("--perguntas", help="só estes ids, separados por vírgula (ex.: p01,p10)")
    args = parser.parse_args()
    if args.teto_usd <= 0:
        parser.error("--teto-usd precisa ser maior que zero")
    return asyncio.run(rodar(args))


if __name__ == "__main__":
    sys.exit(main())
