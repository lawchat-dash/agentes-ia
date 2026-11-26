"""Agente próprio: o cliente define campos, etapas e regras de passagem no painel.

O código interpreta a definição. A IA só extrai os campos e escreve a mensagem;
quem decide a etapa são as regras, na ordem, sem IA.

Definição (agentesia_agentes.config.definicao):
{
  "objetivo": "Entender o caso trabalhista e marcar uma consulta",
  "contexto": "uma pessoa com dúvida trabalhista",
  "campos": [
    {"chave": "situacao", "nome": "Situação de trabalho", "tipo": "escolha",
     "opcoes": ["clt", "autonomo", "desempregado"], "descricao": "...", "etapa": "triagem"},
    {"chave": "salario", "nome": "Salário", "tipo": "numero", "minimo": 0, "maximo": 100000, "etapa": "triagem"}
  ],
  "intencoes": [{"chave": "quer_agendar", "descricao": "pede para marcar um horário"}],
  "etapas": [
    {"codigo": "triagem", "nome": "Triagem", "tipo": "conversa", "instrucao": "..."},
    {"codigo": "agendamento", "nome": "Agendamento", "tipo": "conversa", "instrucao": "..."},
    {"codigo": "fora_do_perfil", "nome": "Fora do perfil", "tipo": "terminal", "instrucao": "..."}
  ],
  "regras": [
    {"de": "triagem", "quando": {"tipo": "campo", "campo": "situacao", "operador": "igual", "valor": "autonomo"},
     "ir_para": "fora_do_perfil", "motivo": "autônomo não é atendido"},
    {"de": "triagem", "quando": {"tipo": "etapa_completa"}, "ir_para": "agendamento"},
    {"de": null, "quando": {"tipo": "intencao", "intencao": "quer_agendar"}, "ir_para": "agendamento"}
  ],
  "nunca": ["prometer resultado", "falar de valores"]
}
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.cerebro.auxilio_acidente import Decisao, Passo
from app.cerebro.produto import (DESCRICAO_INTENCOES_BASE, INTENCOES_BASE, EtapaDoProduto,
                                 esquema_extrator)

_CHAVE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
RESERVADAS = set(INTENCOES_BASE) | {"fatos", "sinais", "intencoes"}


def chave_de(texto: str) -> str:
    """'Situação de trabalho' -> 'situacao_de_trabalho'."""
    sem = unicodedata.normalize("NFD", texto.lower())
    sem = "".join(c for c in sem if unicodedata.category(c) != "Mn")
    sem = re.sub(r"[^a-z0-9]+", "_", sem).strip("_")
    return (sem or "campo")[:40] if sem[:1].isalpha() else ("c_" + sem)[:40]


# ============================================================================ definição (validada)
class Campo(BaseModel):
    chave: str
    nome: str = Field(min_length=1, max_length=80)
    tipo: Literal["texto", "sim_nao", "escolha", "numero", "data"] = "texto"
    opcoes: list[str] = []
    minimo: float | None = None
    maximo: float | None = None
    descricao: str = Field(default="", max_length=500)
    etapa: str | None = None                  # em qual etapa a IA pergunta

    @field_validator("chave")
    @classmethod
    def _chave(cls, valor: str) -> str:
        if not _CHAVE.match(valor) or valor in RESERVADAS:
            raise ValueError(f"chave inválida: {valor}")
        return valor

    @model_validator(mode="after")
    def _opcoes(self) -> "Campo":
        if self.tipo == "escolha":
            self.opcoes = [chave_de(o) for o in self.opcoes if o.strip()]
            if len(self.opcoes) < 2:
                raise ValueError(f"o campo {self.nome} precisa de pelo menos duas opções")
        return self


class Intencao(BaseModel):
    chave: str
    descricao: str = Field(min_length=3, max_length=200)

    @field_validator("chave")
    @classmethod
    def _chave(cls, valor: str) -> str:
        if not _CHAVE.match(valor) or valor in RESERVADAS:
            raise ValueError(f"chave inválida: {valor}")
        return valor


class EtapaLivre(BaseModel):
    codigo: str
    nome: str = Field(min_length=1, max_length=60)
    tipo: Literal["conversa", "terminal"] = "conversa"
    instrucao: str = Field(default="", max_length=12000)
    pede_dados_pessoais: bool = False          # pode pedir CPF, RG, endereço nesta etapa
    fala_valores: bool = False                 # pode citar os honorários nesta etapa

    @field_validator("codigo")
    @classmethod
    def _codigo(cls, valor: str) -> str:
        if not _CHAVE.match(valor):
            raise ValueError(f"código de etapa inválido: {valor}")
        return valor


class Condicao(BaseModel):
    tipo: Literal["campo", "etapa_completa", "intencao"]
    campo: str | None = None
    operador: Literal["igual", "diferente", "maior", "menor", "respondido"] | None = None
    valor: str | float | None = None
    intencao: str | None = None


class Regra(BaseModel):
    de: str | None = None                      # None = vale em qualquer etapa
    quando: Condicao
    ir_para: str
    motivo: str = Field(default="", max_length=200)


class Definicao(BaseModel):
    objetivo: str = Field(default="", max_length=500)
    contexto: str = Field(default="uma pessoa que procura o escritório", max_length=200)
    campos: list[Campo] = []
    intencoes: list[Intencao] = []
    etapas: list[EtapaLivre] = Field(min_length=1)
    regras: list[Regra] = []
    nunca: list[str] = []                      # orientações ("prometer resultado"): vão para as instruções
    expressoes_proibidas: list[str] = []       # palavras exatas que a trava barra ("garantido", "100%")

    @model_validator(mode="after")
    def _coerente(self) -> "Definicao":
        codigos = [e.codigo for e in self.etapas]
        if len(set(codigos)) != len(codigos):
            raise ValueError("há etapas com o mesmo código")
        if self.etapas[0].tipo != "conversa":
            raise ValueError("a primeira etapa precisa ser de conversa")
        chaves = [c.chave for c in self.campos]
        if len(set(chaves)) != len(chaves):
            raise ValueError("há campos com a mesma chave")
        intencoes = {i.chave for i in self.intencoes} | set(INTENCOES_BASE)
        for campo in self.campos:
            if campo.etapa and campo.etapa not in codigos:
                raise ValueError(f"o campo {campo.nome} aponta para uma etapa que não existe")
        for regra in self.regras:
            if regra.de and regra.de not in codigos:
                raise ValueError(f"regra parte de uma etapa que não existe: {regra.de}")
            if regra.ir_para not in codigos:
                raise ValueError(f"regra leva para uma etapa que não existe: {regra.ir_para}")
            if regra.quando.tipo == "campo" and regra.quando.campo not in chaves:
                raise ValueError(f"regra usa um campo que não existe: {regra.quando.campo}")
            if regra.quando.tipo == "intencao" and regra.quando.intencao not in intencoes:
                raise ValueError(f"regra usa uma intenção que não existe: {regra.quando.intencao}")
        self.nunca = [n.strip()[:120] for n in self.nunca if n.strip()][:20]
        self.expressoes_proibidas = [n.strip()[:60] for n in self.expressoes_proibidas if n.strip()][:30]
        return self


# ============================================================================ motor
@dataclass
class ProdutoLivre:
    definicao: Definicao
    codigo: str = "proprio"
    nome: str = "Agente próprio"
    sinais: tuple[str, ...] = ()
    _campos: dict[str, Campo] = field(default_factory=dict)

    @classmethod
    def da_definicao(cls, dados: dict[str, Any]) -> "ProdutoLivre":
        definicao = Definicao.model_validate(dados or {"etapas": [{"codigo": "conversa", "nome": "Conversa"}]})
        return cls(definicao=definicao, _campos={c.chave: c for c in definicao.campos})

    @property
    def contexto(self) -> str:
        return self.definicao.contexto

    @property
    def termos_proibidos(self) -> tuple[str, ...]:
        return tuple(self.definicao.expressoes_proibidas)

    @property
    def objetivo(self) -> str:
        return self.definicao.objetivo

    @property
    def nunca(self) -> tuple[str, ...]:
        return tuple(self.definicao.nunca)

    @property
    def etapas_com_valores(self) -> tuple[str, ...]:
        return tuple(e.codigo for e in self.definicao.etapas if e.fala_valores)

    @property
    def etapas_com_dados_pessoais(self) -> tuple[str, ...]:
        return tuple(e.codigo for e in self.definicao.etapas if e.pede_dados_pessoais)

    @property
    def intencoes(self) -> tuple[str, ...]:
        return INTENCOES_BASE + tuple(i.chave for i in self.definicao.intencoes)

    @property
    def etapas(self) -> list[EtapaDoProduto]:
        return [EtapaDoProduto(e.codigo, e.nome, e.tipo, e.instrucao) for e in self.definicao.etapas]

    def etapa_inicial(self) -> str:
        return self.definicao.etapas[0].codigo

    def esquema_extrator(self) -> dict[str, Any]:
        return esquema_extrator(list(self._campos) or ["nenhum"], self.sinais, self.intencoes)

    def guia_do_extrator(self) -> str:
        linhas = ["Campos possíveis e valores aceitos:"]
        for c in self.definicao.campos:
            aceita = {"texto": "texto curto, nas palavras do lead", "sim_nao": "sim | nao",
                      "escolha": " | ".join(c.opcoes), "data": "AAAA-MM ou AAAA (aceita data aproximada)",
                      "numero": "número" + (f" de {c.minimo:g}" if c.minimo is not None else "")
                                + (f" até {c.maximo:g}" if c.maximo is not None else "")}[c.tipo]
            linhas.append(f"- {c.chave} ({c.nome}): {aceita}" + (f". {c.descricao}" if c.descricao else ""))
        linhas.append("\nIntenções (true só quando o lead disser com as próprias palavras):")
        for chave in INTENCOES_BASE:
            linhas.append(f"- {chave}: {DESCRICAO_INTENCOES_BASE[chave]}")
        for intencao in self.definicao.intencoes:
            linhas.append(f"- {intencao.chave}: {intencao.descricao}")
        return "\n".join(linhas)

    def validar_valor(self, chave: str, valor: Any) -> Any | None:
        campo = self._campos.get(chave)
        if not campo:
            return None
        texto = str(valor).strip()
        if campo.tipo == "texto":
            return texto[:500] or None
        if campo.tipo == "sim_nao":
            texto = chave_de(texto)
            return texto if texto in ("sim", "nao") else None
        if campo.tipo == "escolha":
            texto = chave_de(texto)
            return texto if texto in campo.opcoes else None
        if campo.tipo == "numero":
            try:
                numero = float(texto.replace(",", "."))
            except ValueError:
                return None
            if (campo.minimo is not None and numero < campo.minimo) or (campo.maximo is not None and numero > campo.maximo):
                return None
            return int(numero) if numero.is_integer() else numero
        if campo.tipo == "data":
            achado = re.fullmatch(r"(\d{4})(?:-(\d{1,2}))?", texto)
            if not achado or not 1900 <= int(achado.group(1)) <= 2100:
                return None
            if achado.group(2) and not 1 <= int(achado.group(2)) <= 12:
                return None
            return f"{achado.group(1)}-{int(achado.group(2)):02d}" if achado.group(2) else achado.group(1)
        return None

    def o_que_perguntar(self, chave: str) -> str:
        campo = self._campos.get(chave)
        if not campo:
            return chave
        if campo.descricao:
            return f"{campo.nome}: {campo.descricao}"
        if campo.tipo == "escolha":
            return f"{campo.nome} (opções: {', '.join(campo.opcoes)})"
        return campo.nome

    def motivo_simples(self, motivo: str) -> str:
        return motivo or "o caso não se encaixa no que o escritório atende"

    def _campos_da_etapa(self, etapa: str) -> list[str]:
        return [c.chave for c in self.definicao.campos if c.etapa == etapa]

    @staticmethod
    def _compara(valor: Any, operador: str | None, esperado: Any) -> bool:
        if operador == "respondido":
            return valor not in (None, "")
        if valor in (None, ""):
            return False
        if operador in ("igual", "diferente"):
            igual = chave_de(str(valor)) == chave_de(str(esperado)) or str(valor) == str(esperado)
            return igual if operador == "igual" else not igual
        try:
            a, b = float(str(valor).replace("-", "")), float(str(esperado).replace("-", ""))
        except ValueError:
            return False
        return a > b if operador == "maior" else a < b

    def decidir_etapa(self, etapa: str, fatos: dict[str, Any], intencoes: dict[str, bool]) -> Passo:
        etapas = {e.codigo: e for e in self.definicao.etapas}
        if etapa not in etapas:
            etapa = self.etapa_inicial()
        atual = etapas[etapa]
        faltam = tuple(c for c in self._campos_da_etapa(etapa) if fatos.get(c) in (None, ""))
        if atual.tipo == "terminal":
            return Passo(etapa, "sem_mudanca", ())
        for indice, regra in enumerate(self.definicao.regras):
            if regra.de not in (None, etapa) or regra.ir_para == etapa:
                continue
            cond = regra.quando
            if cond.tipo == "campo":
                vale = self._compara(fatos.get(cond.campo or ""), cond.operador, cond.valor)
            elif cond.tipo == "etapa_completa":
                vale = not faltam
            else:
                vale = bool(intencoes.get(cond.intencao or ""))
            if vale:
                motivo = regra.motivo or f"regra_{indice + 1}"
                decisao = Decisao("regra_do_agente", regra.ir_para, motivo,
                                  conta={"regra": indice + 1, "condicao": cond.model_dump(exclude_none=True)})
                destino = etapas[regra.ir_para]
                faltam_destino = tuple(c for c in self._campos_da_etapa(destino.codigo) if fatos.get(c) in (None, ""))
                return Passo(destino.codigo, motivo, (decisao,), faltam_destino)
        return Passo(etapa, "faltam_dados" if faltam else "em_andamento", (), faltam)
