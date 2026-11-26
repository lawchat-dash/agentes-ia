"""Formato do cenário de teste (JSON) e carregamento.

Um cenário diz quem é o lead (roteiro fixo, cartão determinístico ou IA), com qual agente ele conversa
(snapshot em avaliacao/agentes/), o que as ferramentas falsas devolvem e o que se espera da conversa.
Tudo é sintético: nada de dado real de lead no repositório.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

RAIZ = Path(__file__).resolve().parents[2]
PASTA = RAIZ / "avaliacao"
PASTA_CENARIOS = PASTA / "cenarios"
PASTA_AGENTES = PASTA / "agentes"
PASTA_CASSETES = PASTA / "cassetes"
PASTA_TRANSCRICOES = PASTA / "transcricoes"
PASTA_RESULTADOS = PASTA / "resultados"

AGORA_PADRAO = "2026-03-10T10:00:00-03:00"


class ErroDeCenario(ValueError):
    pass


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _regex(valor: str) -> str:
    try:
        re.compile(valor)
    except re.error as erro:
        raise ValueError(f"expressão regular inválida {valor!r}: {erro}") from erro
    return valor


# ---------------------------------------------------------------------------- lead
# Recusa do lead numa fala de gatilho: é objeção, mesmo sem "?" (Gatilho.e_objecao).
_RECUSA = re.compile(r"(?i)\bn[aã]o\s+(?:vou|quero|passo|mando|envio|confio|aceito|dou|posso\s+passar)\b|\brecuso\b|\bnem pensar\b")


class Espera(_Base):
    """Trava de desvio do LeadRoteiro: o que precisa ser verdade depois da resposta a esta fala."""
    etapa: str | None = None
    contem: list[str] = Field(default_factory=list)          # regex que a resposta precisa ter
    nao_contem: list[str] = Field(default_factory=list)      # regex que a resposta não pode ter
    transferiu_para: str | None = None
    frase_de_troca: bool | None = None                       # a frase de troca do destino apareceu

    @field_validator("contem", "nao_contem")
    @classmethod
    def _regexes(cls, valores: list[str]) -> list[str]:
        return [_regex(v) for v in valores]


class Fala(_Base):
    tipo: Literal["texto", "audio", "imagem"] = "texto"
    texto: str | None = None                                 # no áudio, é a transcrição da Helena
    picadas: list[str] = Field(default_factory=list)         # várias mensagens seguidas (viram 1 turno)
    descricao: str | None = None                             # imagem: o que a visão "vê" (dia 1: pronto no cenário)
    espera: Espera | None = None
    origem: str = ""                                         # preenchido na simulação: abertura, assunto:N, padrao...

    @model_validator(mode="after")
    def _conteudo(self) -> "Fala":
        if self.tipo == "imagem":
            if not self.descricao:
                raise ValueError("fala do tipo imagem precisa de 'descricao'")
        elif not (self.texto or "").strip() and not self.picadas:
            raise ValueError("fala precisa de 'texto' ou 'picadas'")
        if self.picadas and self.tipo != "texto":
            raise ValueError("'picadas' só vale para fala de texto")
        return self

    def partes(self) -> list[str]:
        return list(self.picadas) if self.picadas else [self.texto or ""]

    def texto_corrido(self) -> str:
        return " ".join(p for p in self.partes() if p) or (self.descricao or "")


class Assunto(_Base):
    quando: list[str]                                        # regex sobre a pergunta da IA
    responde: Fala
    uma_vez: bool = True
    fatos: list[str] = Field(default_factory=list)           # chaves da verdade que esta resposta revela
    aceite: bool = False                                     # é o "sim" do lead para seguir (checagem aceite_antes_de_contratos)

    @field_validator("quando")
    @classmethod
    def _regexes(cls, valores: list[str]) -> list[str]:
        if not valores:
            raise ValueError("'quando' precisa de pelo menos uma expressão")
        return [_regex(v) for v in valores]


class Gatilho(_Base):
    depois_de: str | None = None                             # regex sobre o que a IA mandou
    turno: int | None = None                                 # número da rodada do lead (1 = abertura)
    fala: Fala | None = None                                 # None = não fala nada de especial
    # Objeção ou recusa ("não vou passar meu CPF pelo WhatsApp") sai antes de qualquer resposta, mesmo com a pergunta
    # que a dispara no balão. Não objeção ("pode perguntar") cede a vez à pergunta do mesmo balão. None = decide pela
    # fala: pergunta ("?") ou recusa ("não vou", "não quero"...) é objeção.
    objecao: bool | None = None

    def e_objecao(self) -> bool:
        if self.objecao is not None:
            return self.objecao
        texto = self.fala.texto_corrido() if self.fala else ""
        return "?" in texto or bool(_RECUSA.search(texto))

    @model_validator(mode="after")
    def _um_so(self) -> "Gatilho":
        if (self.depois_de is None) == (self.turno is None):
            raise ValueError("gatilho precisa de 'depois_de' ou de 'turno' (só um)")
        if self.depois_de is not None:
            _regex(self.depois_de)
        return self


class Lead(_Base):
    tipo: Literal["roteiro", "cartao", "ia"] = "cartao"
    telefone: str
    nome_whatsapp: str | None = None
    abertura: list[Fala] = Field(default_factory=list)
    falas: list[Fala] = Field(default_factory=list)          # LeadRoteiro: na ordem
    verdade: dict[str, Any] = Field(default_factory=dict)    # o que é verdade sobre a persona (para o oráculo e o LeadIA)
    assuntos: list[Assunto] = Field(default_factory=list)
    gatilhos: list[Gatilho] = Field(default_factory=list)
    ao_receber_link: Literal["assina", "trava", "nada"] = "assina"
    objecoes_link: list[Fala] = Field(default_factory=list)  # 'trava': o que diz antes de assinar
    assinou: Fala = Field(default_factory=lambda: Fala(texto="pronto, assinei"))
    padrao: str = "não sei te dizer"
    # Prefixo da resposta repetida: a IA pergunta de novo e o lead repete a resposta original ("como eu falei, ...").
    # Um "já te falei isso" seco empacava a conversa e virava sinal de objeção (pausa), o que não é realista.
    repetida: str = "como eu falei,"
    # Resposta a um balão sem pergunta nem pedido que só retoma um assunto já respondido ("Ok, você foi demitido em
    # março e não recebeu seguro-desemprego..."): a pessoa diz "ok", não "como eu falei, ...". Origem "ack".
    reconhece: str = "ok"
    sem_resposta: str = "oi? alguém aí?"
    persona: str = ""                                        # estilo de escrita, para o LeadIA

    @field_validator("telefone")
    @classmethod
    def _telefone(cls, valor: str) -> str:
        if not re.fullmatch(r"55\d{10,11}", valor):
            raise ValueError("telefone precisa ser 55 + DDD + número, só dígitos")
        return valor

    @model_validator(mode="after")
    def _por_tipo(self) -> "Lead":
        if self.tipo == "roteiro" and not self.falas:
            raise ValueError("lead do tipo roteiro precisa de 'falas'")
        if self.tipo in ("cartao", "ia") and not self.abertura:
            raise ValueError(f"lead do tipo {self.tipo} precisa de 'abertura'")
        if self.tipo == "ia" and not self.verdade:
            raise ValueError("lead do tipo ia precisa de 'verdade' (o cartão da persona)")
        return self


# ---------------------------------------------------------------------------- ferramentas falsas
class ZapSignFalso(_Base):
    assina: bool = True                                      # a verificação encontra a assinatura do lead


class Ferramentas(_Base):
    cep: dict[str, dict[str, str]] = Field(default_factory=dict)   # "04551000" -> {logradouro, bairro, cidade, uf}
    zapsign: ZapSignFalso = Field(default_factory=ZapSignFalso)

    @field_validator("cep")
    @classmethod
    def _ceps(cls, tabela: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
        return {re.sub(r"\D", "", chave): valor for chave, valor in tabela.items()}


# ---------------------------------------------------------------------------- esperado
class Contrato(_Base):
    exatamente: int = 1
    campos: list[str] = Field(default_factory=list)          # fatos (nome_completo, uf...) ou campos (nome, estado...)


class Esperado(_Base):
    trajetoria: list[str] | None = None                      # None = vem do oráculo
    destino_qualificacao: dict[str, str] | str | None = None # {"oraculo": "auxilio_acidente"} ou destino fixo
    # Destinos em que a frase de troca é cobrada. Lista: "destino" (cobrada quando a frase está no prompt da etapa de
    # origem) ou "origem>destino" (cobrada sempre nesse par). Dicionário: destino -> origens ([] = qualquer origem).
    transferencias_com_frase: list[str] | dict[str, list[str]] = Field(default_factory=list)
    ferramentas: dict[str, Any] = Field(default_factory=dict)        # {"zapsign": 1, "cep_completou_endereco": true}
    contrato: Contrato | None = None
    estado_final: Literal["ativo", "pausado", "encerrado"] | None = None
    proibido: list[str] = Field(default_factory=list)
    obrigatorio_em: dict[str, list[str]] = Field(default_factory=dict)   # etapa -> regex que a IA tem de dizer nela
    perguntar_antes: dict[str, list[str]] = Field(default_factory=dict)  # destino -> regex perguntadas antes de ir
    fatos: dict[str, str] = Field(default_factory=dict)      # fato -> trecho esperado em repo.fatos no fim
    nao_pedir_dados_antes_de: str = "contratos"
    max_perguntas_por_turno: int = 1
    max_caracteres: int = 600
    sem_silencio: bool = True
    sem_pergunta_em: list[str] = Field(default_factory=lambda: ["desqualificado"])
    midias_em: dict[str, list[str]] = Field(default_factory=dict)        # etapa -> regex de mídia (chave/URL) obrigatória
    # etapa -> pares [regexA, regexB] que não podem sair no MESMO turno (ex.: pedir confirmação do resumo e a nota).
    nao_no_mesmo_turno: dict[str, list[list[str]]] = Field(default_factory=dict)
    # Destinos em que a IA não pode transferir deixando pergunta aberta (fora a da própria frase de troca). Desligado
    # por padrão: no Sousa e Costa a frase de troca para o Período de Graça termina em "tudo bem?".
    sem_pergunta_ao_transferir: list[str] = Field(default_factory=list)

    @field_validator("proibido")
    @classmethod
    def _regexes(cls, valores: list[str]) -> list[str]:
        return [_regex(v) for v in valores]

    @field_validator("obrigatorio_em", "perguntar_antes", "midias_em")
    @classmethod
    def _mapas(cls, mapa: dict[str, list[str]]) -> dict[str, list[str]]:
        return {chave: [_regex(v) for v in valores] for chave, valores in mapa.items()}

    @field_validator("nao_no_mesmo_turno")
    @classmethod
    def _pares(cls, mapa: dict[str, list[list[str]]]) -> dict[str, list[list[str]]]:
        for pares in mapa.values():
            for par in pares:
                if len(par) != 2:
                    raise ValueError("nao_no_mesmo_turno: cada item é um par [regexA, regexB]")
        return {chave: [[_regex(a), _regex(b)] for a, b in pares] for chave, pares in mapa.items()}


class Limites(_Base):
    turnos: int = 25
    custo_usd: float = 0.25
    parar_em: list[str] = Field(default_factory=list)        # etapas em que a simulação para (encurta o cenário)


class Variante(_Base):
    nome: str
    descricao: str | None = None
    verdade: dict[str, Any] = Field(default_factory=dict)    # mesclada na verdade do lead
    assuntos: list[Assunto] = Field(default_factory=list)    # entram antes dos do lead (têm prioridade)
    gatilhos: list[Gatilho] = Field(default_factory=list)
    esperado: dict[str, Any] = Field(default_factory=dict)   # mesclado no esperado
    sobrescrever_config: dict[str, Any] = Field(default_factory=dict)   # mesclado no do cenário (ex.: auditor desligado)
    # Jeitos diferentes de COMEÇAR a mesma conversa (sc30): a abertura da variante substitui a do lead (vazia = a do
    # lead); persona e nome do WhatsApp idem (None = os do lead).
    abertura: list[Fala] = Field(default_factory=list)
    persona: str | None = None
    nome_whatsapp: str | None = None


class Cenario(_Base):
    id: str
    descricao: str = ""
    agente: str = "avaliacao/agentes/catalogo_referencia.json"
    sobrescrever_config: dict[str, Any] = Field(default_factory=dict)
    agora: datetime = Field(default_factory=lambda: datetime.fromisoformat(AGORA_PADRAO))
    lead: Lead
    ferramentas: Ferramentas = Field(default_factory=Ferramentas)
    esperado: Esperado = Field(default_factory=Esperado)
    limites: Limites = Field(default_factory=Limites)
    variantes: list[Variante] = Field(default_factory=list)

    @field_validator("agora")
    @classmethod
    def _com_fuso(cls, valor: datetime) -> datetime:
        if valor.tzinfo is None:
            raise ValueError("'agora' precisa de fuso (ex.: 2026-03-10T10:00:00-03:00)")
        return valor

    def caminho_agente(self) -> Path:
        caminho = Path(self.agente)
        return caminho if caminho.is_absolute() else RAIZ / caminho

    def carregar_agente(self) -> dict[str, Any]:
        """Snapshot {escritorio, agente}, já com o que o cenário sobrescreve na config do agente."""
        caminho = self.caminho_agente()
        try:
            snap = json.loads(caminho.read_text(encoding="utf-8"))
        except FileNotFoundError as erro:
            raise ErroDeCenario(f"cenário {self.id}: snapshot do agente não existe: {caminho}") from erro
        for chave in ("escritorio", "agente"):
            if chave not in snap:
                raise ErroDeCenario(f"cenário {self.id}: snapshot sem '{chave}': {caminho}")
        snap["agente"]["config"] = _mesclar(snap["agente"].get("config") or {}, self.sobrescrever_config)
        return snap

    def destino_esperado(self) -> Any:
        """Destino do oráculo (ou fixo), ou None quando o cenário não confere qualificação."""
        from app.avaliacao import oraculo

        alvo = self.esperado.destino_qualificacao
        if alvo is None:
            return None
        if isinstance(alvo, str):
            return oraculo.Destino(alvo, "periododegraca" in (self.esperado.trajetoria or []), "fixo no cenário")
        if alvo.get("oraculo") != "auxilio_acidente":
            raise ErroDeCenario(f"cenário {self.id}: oráculo desconhecido {alvo!r}")
        return oraculo.esperado_auxilio_acidente(self.lead.verdade)


def _mesclar(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    """Mescla dicionários em profundidade (o extra vence)."""
    saida = dict(base)
    for chave, valor in (extra or {}).items():
        if isinstance(valor, dict) and isinstance(saida.get(chave), dict):
            saida[chave] = _mesclar(saida[chave], valor)
        else:
            saida[chave] = valor
    return saida


def _explicar(erro: ValidationError, nome: str) -> str:
    linhas = [f"cenário {nome} inválido:"]
    for item in erro.errors():
        onde = ".".join(str(p) for p in item["loc"]) or "(raiz)"
        linhas.append(f"  - {onde}: {item['msg']}")
    return "\n".join(linhas)


def _conferir_oraculo(cen: Cenario) -> Cenario:
    """Preenche a trajetória pelo oráculo, ou falha se a escrita à mão não bate com as Regras()."""
    from app.avaliacao import oraculo

    try:
        destino = cen.destino_esperado()
    except oraculo.ErroDoOraculo as erro:
        raise ErroDeCenario(f"cenário {cen.id}: {erro}") from erro
    if destino is None or not isinstance(cen.esperado.destino_qualificacao, dict):
        return cen
    if cen.esperado.trajetoria is None:
        cen.esperado.trajetoria = destino.trajetoria()
    elif motivo := oraculo.conferir_trajetoria(cen.esperado.trajetoria, destino):
        raise ErroDeCenario(f"cenário {cen.id}: cenário inconsistente com Regras(): {motivo}")
    return cen


def expandir(cen: Cenario) -> list[Cenario]:
    """Um caso por variante (id 'base[variante]'); sem variantes, o próprio cenário."""
    if not cen.variantes:
        return [_conferir_oraculo(cen.model_copy(deep=True))]
    casos = []
    for variante in cen.variantes:
        dados = cen.model_dump(mode="json", exclude={"variantes"})
        dados["id"] = f"{cen.id}[{variante.nome}]"
        if variante.descricao:
            dados["descricao"] = f"{cen.descricao} Variante: {variante.descricao}"
        dados["lead"]["verdade"] = {**dados["lead"]["verdade"], **variante.verdade}
        dados["lead"]["assuntos"] = [a.model_dump(mode="json") for a in variante.assuntos] + dados["lead"]["assuntos"]
        dados["lead"]["gatilhos"] = [g.model_dump(mode="json") for g in variante.gatilhos] + dados["lead"]["gatilhos"]
        if variante.abertura:
            dados["lead"]["abertura"] = [f.model_dump(mode="json") for f in variante.abertura]
        if variante.persona is not None:
            dados["lead"]["persona"] = variante.persona
        if variante.nome_whatsapp is not None:
            dados["lead"]["nome_whatsapp"] = variante.nome_whatsapp
        dados["esperado"] = _mesclar(dados["esperado"], variante.esperado)
        dados["sobrescrever_config"] = _mesclar(dados["sobrescrever_config"], variante.sobrescrever_config)
        try:
            caso = Cenario.model_validate(dados)
        except ValidationError as erro:
            raise ErroDeCenario(_explicar(erro, dados["id"])) from erro
        casos.append(_conferir_oraculo(caso))
    return casos


def carregar(origem: str | Path | dict[str, Any]) -> Cenario:
    """Lê um cenário de arquivo, de id (procura em avaliacao/cenarios/) ou de dicionário, e confere tudo."""
    if isinstance(origem, dict):
        dados, nome = origem, str(origem.get("id") or "(dicionário)")
    else:
        caminho = Path(origem)
        if not caminho.suffix:
            caminho = PASTA_CENARIOS / f"{origem}.json"
        elif not caminho.is_absolute() and not caminho.exists():
            caminho = RAIZ / caminho
        try:
            dados = json.loads(caminho.read_text(encoding="utf-8"))
        except FileNotFoundError as erro:
            raise ErroDeCenario(f"cenário não encontrado: {caminho}") from erro
        except json.JSONDecodeError as erro:
            raise ErroDeCenario(f"cenário {caminho.name}: JSON inválido ({erro})") from erro
        nome = caminho.name
    try:
        cen = Cenario.model_validate(dados)
    except ValidationError as erro:
        raise ErroDeCenario(_explicar(erro, nome)) from erro
    expandir(cen)                                            # confere as variantes e o oráculo já no carregamento
    return cen


def listar(pasta: Path = PASTA_CENARIOS) -> list[Cenario]:
    return [carregar(caminho) for caminho in sorted(pasta.glob("*.json"))]


def casos(ids: list[str] | None = None, pasta: Path = PASTA_CENARIOS) -> list[Cenario]:
    """Casos prontos para rodar (variantes expandidas). `ids` aceita o id inteiro ou o prefixo ("01", "03")."""
    todos = [caso for cen in listar(pasta) for caso in expandir(cen)]
    if not ids:
        return todos
    escolhidos = [c for c in todos if any(c.id == i or c.id.split("[")[0] == i or c.id.startswith(i + "_")
                                          or c.id.startswith(i) for i in ids)]
    if not escolhidos:
        raise ErroDeCenario(f"nenhum cenário com id {', '.join(ids)}")
    return escolhidos
