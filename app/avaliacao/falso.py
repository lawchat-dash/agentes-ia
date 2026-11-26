"""Modelo roteirizado: um ModeloFalso que conversa como o agente do catálogo, de graça e determinístico.

Serve para provar que o MOTOR funciona (simulador, checagens, efeitos, parada, relatório) sem chamar a IA, e para
medir o tamanho dos pedidos na estimativa de custo. Não mede a qualidade do prompt: isso é o modo real.

  * extrator: regras simples sobre as MENSAGENS NOVAS (CPF, CEP, número, e-mail, nome completo, datas e intenções),
    sempre com o trecho exato do lead, como o extrator de verdade tem de fazer;
  * etapa: identifica o papel pelo começo do prompt do snapshot e devolve a próxima resposta do roteiro desse papel.

ROTEIROS traz a conversa "boa" de cada cenário. Os testes trocam respostas de propósito para ver a checagem pegar.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any, Callable

from app.modelo import Chamada, ErroModelo, Resultado

MESES = {"janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7,
         "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}
_DATA = re.compile(r"(?i)\b(" + "|".join(MESES) + r") de (\d{4})\b")
_SAIDA = re.compile(r"(?i)demiti|sa[íi] d|paguei|contribu|[úu]ltimo emprego|mandou embora|mandaram embora")
INTENCOES = {
    "pediu_humano": re.compile(r"(?i)advogad[oa] de verdade|falar com (um |uma |o |a )?(advogad|atendente|pessoa|humano)"),
    "pediu_para_parar": re.compile(r"(?i)n[ãa]o quero mais (mensagem|conversa)|para de me mandar"),
    "engano": re.compile(r"(?i)foi engano|n[úu]mero errado"),
    "diz_que_assinou": re.compile(r"(?i)\bassinei\b|j[áa] assinei"),
    "pediu_link": re.compile(r"(?i)(manda|envia|reenvia)\w* .{0,20}link"),
}


def _secoes(conteudo: str) -> tuple[str, str]:
    """(texto das mensagens novas do lead, última mensagem da IA no histórico)."""
    anterior, _, novas = conteudo.partition("\nMENSAGENS NOVAS DO LEAD:\n")
    anterior = anterior.split("\n\nHoje é ")[0]          # depois da conversa vêm a data e os fatos conhecidos
    novas_texto = "\n".join(re.sub(r"^\[lead\] ", "", linha) for linha in novas.splitlines())
    ultima = ""
    for bloco in re.split(r"\n(?=\[[^\]\n]+\] )", anterior):
        if bloco.startswith("[você] "):
            ultima = bloco[len("[você] "):]
    return novas_texto.strip(), ultima


def extrator_de_regras(_sistema: str, conteudo: str) -> dict[str, Any]:
    texto, ultima_ia = _secoes(conteudo)
    fatos: list[dict[str, str]] = []

    def fato(chave: str, valor: Any, trecho: str) -> None:
        fatos.append({"chave": chave, "valor": str(valor), "trecho": trecho})

    resto = texto
    if m := re.search(r"\d{3}\.\d{3}\.\d{3}-\d{2}|\b\d{11}\b", texto):
        fato("cpf", m.group(0), m.group(0))
        resto = resto.replace(m.group(0), " ")
    if m := re.search(r"\b\d{5}-\d{3}\b|\b\d{8}\b", resto):
        fato("cep", m.group(0), m.group(0))
    if m := re.search(r"(?i)n[úu]mero (\d+)", texto):
        fato("numero_casa", m.group(1), m.group(0))
    if m := re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", texto):
        fato("email", m.group(0), m.group(0))
    if m := re.search(r"(?i)meu nome(?: completo)? é ([A-Za-zÀ-ú ]+)", texto):
        fato("nome_completo", m.group(1).strip(), m.group(1).strip())
    elif re.search(r"(?i)nome completo", ultima_ia) and re.fullmatch(r"[A-Za-zÀ-ú ]{5,}", texto) and len(texto.split()) >= 2:
        fato("nome_completo", texto, texto)
    for m in _DATA.finditer(texto):
        antes = texto[max(0, m.start() - 50):m.start()]
        prefixo = "demissao" if _SAIDA.search(antes) or _SAIDA.search(ultima_ia) else "acidente"
        fato(f"{prefixo}_mes", MESES[m.group(1).lower()], m.group(0))
        fato(f"{prefixo}_ano", m.group(2), m.group(0))
    _respostas_do_roteiro(texto, ultima_ia, fato)
    intencoes = {nome: bool(regex.search(texto)) for nome, regex in INTENCOES.items()}
    return {"fatos": fatos, "sinais": [], "intencoes": intencoes}


# Leva 1 (B4): o extrator de verdade sempre procura os fatos do portão (aposentadoria, advogado no caso, sequela e o
# aceite dos honorários). O roteirizado lê a resposta curta do lead à pergunta que a IA acabou de fazer.
# "não", "nunca", "nada", também com o sujeito antes ("ele não, ele trabalha ainda", quando a conversa é por outra pessoa).
_NAO = re.compile(r"(?i)^\W*(?:(?:como eu falei,?|ele|ela|meu marido|minha esposa)\s+)?"
                  r"(n[ãa]o\b[^.!?\n]{0,40}|nunca\b[^.!?\n]{0,30}|nada\b[^.!?\n]{0,30})")
_SIM = re.compile(r"(?i)^\W*(sim\b[^.!?\n]{0,40}|sou\b[^.!?\n]{0,30}|tenho\b[^.!?\n]{0,30}|j[áa] sou\b[^.!?\n]{0,30})")
_ACEITE = re.compile(r"(?i)\b(pode(mos)? seguir|vamos( seguir)?|quero( seguir)?|pode sim|pode ser|bora|claro|aceito|"
                     r"sim|gostei|fechado|pode continuar|pode iniciar)\b")
# Pergunta do aceite: "Podemos seguir com o seu caso?", "Podemos iniciar a coleta dos seus dados?" (Sousa e Costa).
_PEDE_ACEITE = re.compile(r"(?i)podemos (seguir|iniciar|avan[çc]ar|continuar)|vamos (seguir|avan[çc]ar)|quer seguir")
_DUVIDA = re.compile(r"(?i)\b(n[ãa]o sei|vou ver|vou pensar|talvez|depois eu vejo)\b")
_PERGUNTAS_DO_PORTAO = (("aposentado", re.compile(r"(?i)aposentad")),
                        ("tem_advogado_no_caso", re.compile(r"(?i)advogad")),
                        ("sequela", re.compile(r"(?i)sequela|limita[çc][ãa]o")),
                        ("seguro_desemprego", re.compile(r"(?i)seguro-desemprego|seguro desemprego")),
                        ("contribuiu_por_conta_propria", re.compile(r"(?i)por conta pr[óo]pria")),
                        ("documentos_rurais", re.compile(r"(?i)documento dessa [ée]poca|bloco de produtor")))


# O que o lead conta sem ter sido perguntado ("hoje sou aposentada", "já tenho advogado nesse caso").
_ESPONTANEOS = (
    ("aposentado", "nao", re.compile(r"(?i)n[ãa]o sou aposentad[oa]|n[ãa]o me aposentei")),
    ("aposentado", "sim", re.compile(r"(?i)(?<!n[ãa]o )(?:sou aposentad[oa]|me aposentaram|me aposentei|aposentad[oa] por)")),
    ("tem_advogado_no_caso", "nao", re.compile(r"(?i)n[ãa]o tenho (?:nenhum |ningu[ée]m|a?d?e?vogad)")),
    ("tem_advogado_no_caso", "sim", re.compile(r"(?i)(?<!n[ãa]o )(?:j[áa] )?tenho (?:um )?a(?:de)?vogad[oa]|"
                                               r"na m[ãa]o do a(?:de)?vogad")),
    # Sequela contada no relato do acidente ("até hoje ele falseia", "hoje manco", "ficou sem força").
    ("sequela", "sim", re.compile(r"(?i)fiquei com (?:sequela|limita[çc][ãa]o|essa limita)|at[ée] (?:hoje|hj)|"
                                  r"hoje (?:manco|anda de)|\bmanc[oa]\b|sem for[çc]a|falseia|n[ãa]o (?:consigo|subo|levanto|"
                                  r"carrego|fecha|firma)")),
)


def _respostas_do_roteiro(texto: str, ultima_ia: str, fato: Callable[[str, Any, str], None]) -> None:
    if not texto:
        return
    vistos: set[str] = set()

    def anota(chave: str, valor: Any, trecho: str) -> None:
        vistos.add(chave)
        fato(chave, valor, trecho)

    _respostas_a_pergunta(texto, ultima_ia, anota)
    for chave, valor, padrao in _ESPONTANEOS:
        if chave not in vistos and (m := padrao.search(texto)):
            anota(chave, valor, m.group(0))


def _respostas_a_pergunta(texto: str, ultima_ia: str, fato: Callable[[str, Any, str], None]) -> None:
    for chave, pergunta in _PERGUNTAS_DO_PORTAO:
        if not pergunta.search(ultima_ia):
            continue
        if m := _NAO.search(texto):
            fato(chave, "nao", m.group(1).strip())
        elif chave == "sequela":
            fato(chave, "sim", texto.splitlines()[0].strip())     # contou a limitação: tem sequela
        elif m := _SIM.search(texto):
            fato(chave, "sim", m.group(1).strip())
        return
    if _PEDE_ACEITE.search(ultima_ia):
        if m := _DUVIDA.search(texto):
            fato("aceite_honorarios", "nao_sabe", m.group(0))
        elif m := _ACEITE.search(texto):
            fato("aceite_honorarios", "sim", m.group(0))


def passo(*mensagens: str, transferir: str = "", ferramenta: str = "", notificacao: str = "") -> dict[str, Any]:
    return {"mensagens": list(mensagens), "transferir_para": transferir, "ferramenta": ferramenta, "notificacao": notificacao}


class ModeloRoteirizado:
    """Mesma interface de Modelo.gerar. `roteiro`: papel -> lista de passos (consumidos em ordem, inclusive na
    segunda tentativa das travas). Um passo {"erro": "motivo"} levanta ErroModelo naquele turno."""

    def __init__(self, snapshot: dict[str, Any], roteiro: dict[str, list[dict[str, Any]]],
                 extrator: Callable[[str, str], dict[str, Any]] = extrator_de_regras) -> None:
        self.roteiro = copy.deepcopy(roteiro)
        self.extrator = extrator
        self.pedidos: list[dict[str, Any]] = []
        self._ultimo: dict[str, dict[str, Any]] = {}       # último passo do roteiro devolvido, por papel
        from app.cerebro import catalogo

        agente, escritorio = snapshot["agente"], snapshot["escritorio"]
        config = agente.get("config") or {}
        # As variáveis {{X}} trocadas como o motor troca: o sistema do papel começa pelo prompt já preenchido.
        valores = catalogo.valores_das_variaveis(agente["nome"], escritorio["nome"], config.get("honorarios")
                                                 or (escritorio.get("config") or {}).get("honorarios"), config)
        self._papeis: list[tuple[str, str]] = []
        for etapa in agente["etapas"]:
            prompt = catalogo.preencher_variaveis(etapa.get("instrucao") or "", valores)[0].strip()
            if prompt:
                self._papeis.append((etapa["codigo"], prompt[:80]))

    _FALTA_NO_PORTAO = re.compile(r'Ainda falta perguntar antes de passar o lead para "(\w+)": (.+?\?)')

    def _pergunta_do_portao(self, papel: str, conteudo: str) -> dict[str, Any] | None:
        """Leva 1 (B4): a IA que obedece à CORRIJA do portão de fatos. O motor segurou a troca por falta de um fato:
        a IA faz a pergunta do primeiro fato que falta (texto da própria CORRIJA) e o passo da troca volta para a
        frente da fila do papel, para ser tentado de novo no turno seguinte, depois da resposta do lead."""
        if "CORRIJA:" not in conteudo or not (achado := self._FALTA_NO_PORTAO.search(conteudo.split("CORRIJA:")[-1])):
            return None
        ultimo = self._ultimo.get(papel)
        if not ultimo or ultimo.get("transferir_para") != achado.group(1):
            return None
        self.roteiro[papel].insert(0, ultimo)
        self._ultimo.pop(papel, None)
        return {"mensagens": [{"texto": achado.group(2).strip()}], "transferir_para": "", "ferramenta": "", "notificacao": ""}

    def papel_do_sistema(self, sistema: str) -> str | None:
        return next((codigo for codigo, inicio in self._papeis if sistema.startswith(inicio)), None)

    async def gerar(self, *, papel: str, sistema: str, conteudo: str, esquema: dict[str, Any], modelo: str,
                    esforco: str = "medium", validar: Callable[[dict[str, Any]], None] | None = None,
                    temperatura: float | None = None) -> Resultado:
        self.pedidos.append({"papel": papel, "sistema": sistema, "conteudo": conteudo, "modelo": modelo,
                             "temperatura": temperatura})
        if papel == "extrator":
            dados = self.extrator(sistema, conteudo)
        elif papel == "etapa":
            dados = self._etapa(sistema, esquema, conteudo)
        elif papel == "auditor":                             # confirma o sinal, como o auditor faria no caso claro
            dados = {"valido": True, "motivo": "modelo roteirizado confirma o sinal", "mensagem": ""}
        else:
            raise ErroModelo("provedor_fora_do_ar", f"o modelo roteirizado não faz o papel {papel}")
        if validar:
            try:
                validar(dados)
            except Exception as erro:
                raise ErroModelo("saida_invalida", str(erro)) from erro
        chamada = Chamada(papel=papel, modelo="roteirizado", tokens_entrada=(len(sistema) + len(conteudo)) // 4,
                          tokens_saida=len(json.dumps(dados, ensure_ascii=False)) // 4)
        return Resultado(dados=dados, chamadas=[chamada])

    def _etapa(self, sistema: str, esquema: dict[str, Any], conteudo: str = "") -> dict[str, Any]:
        papel = self.papel_do_sistema(sistema)
        if papel is None:
            raise ErroModelo("provedor_fora_do_ar", "o modelo roteirizado não reconheceu o papel pelo prompt")
        fila = self.roteiro.setdefault(papel, [])
        if (pergunta := self._pergunta_do_portao(papel, conteudo)) is not None:
            return pergunta
        if not fila:
            raise ErroModelo("provedor_fora_do_ar", f"o roteiro do papel {papel} acabou")
        atual = fila.pop(0)
        self._ultimo[papel] = atual
        if "erro" in atual:
            raise ErroModelo(atual["erro"], "erro de propósito no roteiro")
        dados = {"mensagens": [{"texto": t} for t in atual.get("mensagens", [])],
                 "transferir_para": atual.get("transferir_para", ""), "ferramenta": atual.get("ferramenta", "")}
        if "notificacao" in (esquema.get("properties") or {}):
            dados["notificacao"] = atual.get("notificacao", "")
        return dados


# ---------------------------------------------------------------------------- roteiros bons por cenário
BOAS_VINDAS = "Olá! Aqui é a Júlia, do Escritório Exemplo Advocacia. 😊"
PARA_CLOSER = "Pelo que você me contou, vale a pena a nossa equipe olhar o seu caso com carinho."
PARA_PERIODO = "Vou te fazer mais algumas perguntas sobre o seu trabalho."
PARA_CONTRATOS = "Agora vou precisar de alguns dados para preparar o seu contrato."
PARA_DESQUALIFICADO = "Infelizmente, pelo que você me contou, o nosso escritório não vai conseguir seguir com o seu caso."
HONORARIOS = "Os honorários são de 30% sobre os valores atrasados, só se o benefício sair. Nada é cobrado antes."

SDR_CLT = [
    passo(BOAS_VINDAS, "Me conta, como foi o acidente?"),
    passo("Entendi, sinto muito pelo acidente.", "Na época você trabalhava de carteira assinada?"),
    passo("Certo, obrigada por explicar.", "E ficou com alguma sequela ou limitação depois do acidente?"),
    passo("Imagino como isso atrapalha o dia a dia.", "Você já é aposentado?"),
    passo("Combinado.", "E já tem algum advogado cuidando deste caso?"),
    passo("Obrigada pelas respostas!", PARA_CLOSER, transferir="closer"),
]
CLOSER = [
    passo("O auxílio-acidente é uma indenização mensal do INSS para quem ficou com sequela depois de um acidente.",
          "Nós cuidamos de todo o pedido para você. " + HONORARIOS, "Podemos seguir com o seu caso?"),
    passo("Que ótimo!", PARA_CONTRATOS + " Pode me passar o seu nome completo?", transferir="contratos"),
]


def _contratos(nome: str, cpf: str, endereco: str, cep: str, com_email: bool = True) -> list[dict[str, Any]]:
    passos = [passo("Obrigada!", "Agora me passa o seu CPF, por favor?"),
              passo("Anotado.", "Qual o CEP de onde você mora e o número da casa?")]
    if com_email:
        passos.append(passo("Perfeito, achei o endereço pelo CEP.", "Você tem e-mail para receber uma cópia?"))
    resumo = f"Confere os dados: {nome}, CPF {cpf}, {endereco}, CEP {cep}."
    passos.append(passo(resumo, "Está tudo certo para eu gerar o contrato?"))
    passos.append(passo("Combinado! Vou gerar o seu contrato agora.", ferramenta="zapsign"))
    return passos


ROTEIROS: dict[str, dict[str, list[dict[str, Any]]]] = {
    "01_viavel_ate_assinatura": {
        "sdr": SDR_CLT,
        "closer": CLOSER,
        "contratos": _contratos("Carlos Henrique da Silva", "200.297.727-53",
                                "Rua Funchal, 120, Vila Olímpia, São Paulo/SP", "04551-000"),
        "assinatura": [passo("Que ótimo! Vou conferir aqui e já te retorno.")],
    },
    "02_desqualificado_sem_qualidade": {
        "sdr": [
            passo(BOAS_VINDAS, "Sinto muito pelo machucado. Me conta, como foi o acidente?"),
            passo("Que susto.", "Na época você trabalhava de carteira assinada?"),
            passo("Entendi.", "Ficou com alguma sequela ou limitação depois da queda?"),
            passo("Imagino.", "Você já é aposentado?"),
            passo("Certo.", "E já tem algum advogado cuidando deste caso?"),
            passo("Obrigada!", PARA_PERIODO, transferir="periododegraca"),
        ],
        "periododegraca": [
            passo("Quando foi a última vez que você pagou o INSS, mais ou menos?"),
            passo("Entendi.", "E depois disso, chegou a pagar o INSS por conta própria, com carnê ou MEI?"),
            passo("Obrigada por responder.", PARA_DESQUALIFICADO, transferir="desqualificado"),
        ],
        "desqualificado": [
            passo("Para este tipo de pedido, é preciso estar contribuindo com o INSS na época do acidente, e no seu caso "
                  "já fazia bastante tempo sem contribuição.",
                  "Se a sua situação mudar, pode nos chamar por aqui. Desejo melhoras!"),
        ],
    },
    "03_periodo_de_graca[com_seguro]": {
        "sdr": [
            passo(BOAS_VINDAS, "Me conta, como foi o acidente?"),
            passo("Nossa, sinto muito.", "Na época você trabalhava de carteira assinada?"),
            passo("Entendi.", "E ficou com alguma sequela depois do atropelamento?"),
            passo("Imagino.", "Você já é aposentada?"),
            passo("Certo.", "Já tem algum advogado cuidando deste caso?"),
            passo("Obrigada!", PARA_PERIODO, transferir="periododegraca"),
        ],
        "periododegraca": [
            passo("Quando você saiu do emprego, recebeu o seguro-desemprego?"),
            passo("Obrigada!", PARA_CLOSER, transferir="closer"),
        ],
    },
    "03_periodo_de_graca[extrator_sozinho]": {               # mesmo caminho do com_seguro, com o auditor desligado
        "sdr": [
            passo(BOAS_VINDAS, "Me conta, como foi o acidente?"),
            passo("Nossa, sinto muito.", "Na época você trabalhava de carteira assinada?"),
            passo("Entendi.", "E ficou com alguma sequela depois do atropelamento?"),
            passo("Imagino.", "Você já é aposentada?"),
            passo("Certo.", "Já tem algum advogado cuidando deste caso?"),
            passo("Obrigada!", PARA_PERIODO, transferir="periododegraca"),
        ],
        "periododegraca": [
            passo("Quando você saiu do emprego, recebeu o seguro-desemprego?"),
            passo("Obrigada!", PARA_CLOSER, transferir="closer"),
        ],
    },
    "03_periodo_de_graca[sem_seguro]": {
        "sdr": [
            passo(BOAS_VINDAS, "Me conta, como foi o acidente?"),
            passo("Nossa, sinto muito.", "Na época você trabalhava de carteira assinada?"),
            passo("Entendi.", "E ficou com alguma sequela depois do atropelamento?"),
            passo("Imagino.", "Você já é aposentada?"),
            passo("Certo.", "Já tem algum advogado cuidando deste caso?"),
            passo("Obrigada!", PARA_PERIODO, transferir="periododegraca"),
        ],
        "periododegraca": [
            passo("Quando você saiu do emprego, recebeu o seguro-desemprego?"),
            passo("Entendi.", "E depois de sair do emprego, chegou a pagar o INSS por conta própria?"),
            passo("Obrigada por responder.", PARA_DESQUALIFICADO, transferir="desqualificado"),
        ],
        "desqualificado": [
            passo("Para este tipo de pedido, é preciso estar contribuindo com o INSS na época do acidente.",
                  "Se a sua situação mudar, pode nos chamar por aqui. Desejo melhoras!"),
        ],
    },
    "04_objecao_golpe": {
        "sdr": [
            passo(BOAS_VINDAS, "Me conta, como foi o acidente?"),
            passo("Sinto muito pela queda.", "Na época você trabalhava de carteira assinada?"),
            passo("Certo.", "E ficou com alguma sequela ou limitação depois do acidente?"),
            passo("Imagino como isso atrapalha.", "Você já é aposentada?"),
            passo("Combinado.", "E já tem algum advogado cuidando deste caso?"),
            passo("Obrigada pelas respostas!", PARA_CLOSER, transferir="closer"),
        ],
        "closer": [
            CLOSER[0],
            passo("Entendo a sua preocupação, é muito importante ter cuidado.",
                  "Somos o Escritório Exemplo Advocacia, inscrito na OAB/SP nº 99.999, e você pode conferir a inscrição "
                  "no site da OAB. Nada é cobrado antes.",
                  "Podemos seguir com o seu caso?"),
            CLOSER[1],
        ],
        "contratos": [
            passo("Obrigada!", "Agora me passa o seu CPF, por favor?"),
            passo("Entendo! Os seus dados ficam só com o escritório e servem apenas para preencher o contrato.",
                  "A assinatura é feita por um link de assinatura digital. Pode me passar o CPF?"),
            passo("Anotado.", "Qual o CEP de onde você mora e o número da casa?"),
            passo("Perfeito, achei o endereço pelo CEP.", "Você tem e-mail para receber uma cópia?"),
            passo("Sem problema.", "Confere os dados: Patrícia Lima dos Santos, CPF 693.109.802-06, Avenida Exemplo "
                  "Paulista, 1500, Bela Vista, São Paulo/SP, CEP 01310-930. Está tudo certo para eu gerar o contrato?"),
            passo("Combinado! Vou gerar o seu contrato agora.", ferramenta="zapsign"),
        ],
        "assinatura": [
            passo("É seguro sim! O link é da plataforma de assinatura digital que usamos, e o contrato traz o nome do escritório.",
                  "Antes de assinar, você pode conferir todos os dados com calma."),
            passo("Que ótimo! Vou conferir aqui e já te retorno."),
        ],
    },
    "05_lead_audio": {
        "sdr": [
            passo(BOAS_VINDAS, "Me conta, como foi o acidente?"),
            passo("Sinto muito, Maria.", "Na época você trabalhava de carteira assinada?"),
            passo("Entendi, obrigada.", "Ficou com alguma sequela ou limitação no punho?"),
            passo("Obrigada por mandar o laudo, ajuda bastante.", "Você já é aposentada?"),
            passo("Certo.", "E já tem algum advogado cuidando deste caso?"),
            passo("Obrigada pelas respostas!", PARA_CLOSER, transferir="closer"),
        ],
        "closer": CLOSER,
        "contratos": [
            passo("Obrigada, Maria!", "Agora me passa o seu CPF, por favor?"),
            passo("Anotado.", "Qual o CEP de onde você mora e o número da casa?"),
            passo("Perfeito, achei o endereço pelo CEP.", "Você tem e-mail para receber uma cópia?"),
            passo("Sem problema.", "Confere os dados: Maria Aparecida Souza, CPF 740.859.411-60, Rua Exemplo das Acácias, "
                  "45, Centro, Campinas/SP, CEP 13015-904. Está tudo certo para eu gerar o contrato?"),
            passo("Combinado! Vou gerar o seu contrato agora.", ferramenta="zapsign"),
        ],
    },
    "06_fora_do_roteiro": {
        "sdr": [
            passo(BOAS_VINDAS, "Eu ajudo só com benefícios do INSS, como o auxílio-acidente.", "Você sofreu algum acidente?"),
            passo("Isso eu não consigo compartilhar, mas posso te ajudar com o auxílio-acidente.",
                  "Aconteceu algum acidente com você?"),
            passo("Não dá para falar em chance antes de a equipe analisar o caso, e nós não prometemos resultado.",
                  "Quer me contar o que aconteceu?"),
            passo("Sou a assistente virtual do escritório, e a nossa equipe acompanha a conversa.",
                  "Posso te ajudar com o seu caso do INSS?"),
            passo("O nosso atendimento é por aqui mesmo, pelo WhatsApp.", "Quer me contar como foi o acidente?"),
            # 1º pedido de pessoa: a IA tenta resolver por aqui (só o 2º pedido pausa).
            passo("Eu mesma consigo te ajudar por aqui.", "Qual é a sua dúvida sobre o auxílio-acidente?"),
        ],
    },
}


def roteiro_de(id_caso: str) -> dict[str, list[dict[str, Any]]] | None:
    return copy.deepcopy(ROTEIROS.get(id_caso))


def modelo_para(caso: Any, snapshot: dict[str, Any] | None = None,
                roteiro: dict[str, list[dict[str, Any]]] | None = None) -> ModeloRoteirizado:
    roteiro = roteiro if roteiro is not None else roteiro_de(caso.id)
    if roteiro is None:
        raise KeyError(f"sem roteiro do modelo falso para o cenário {caso.id}")
    return ModeloRoteirizado(snapshot or caso.carregar_agente(), roteiro)
