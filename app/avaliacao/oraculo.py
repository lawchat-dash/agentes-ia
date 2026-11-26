"""Oráculo de qualificação: dada a verdade da persona, para onde o lead deveria ir.

Usa as mesmas funções puras do produto Auxílio-Acidente (decidir_qualificacao e calcular_periodo_graca, com
Regras() padrão). Assim o gabarito dos cenários acompanha as regras do código: se alguém mudar as regras,
o cenário com trajetória escrita à mão para de carregar ("cenário inconsistente com Regras()").

Vale para o prompt de referência do Auxílio-Acidente. Escritório com regra própria usa destino fixo no cenário.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.cerebro import auxilio_acidente as aa

# Caminho do funil do catálogo depois que o lead é qualificado.
DEPOIS_DO_CLOSER = ["closer", "contratos", "assinatura", "contrato_assinado"]


class ErroDoOraculo(ValueError):
    pass


@dataclass(frozen=True)
class Destino:
    destino: str                         # closer | desqualificado | analise_humana
    passa_periodo: bool                  # passa pelo papel periododegraca antes de decidir
    motivo: str
    decisoes: list[dict[str, Any]] = field(default_factory=list)

    def trajetoria(self) -> list[str]:
        caminho = ["sdr"] + (["periododegraca"] if self.passa_periodo else [])
        if self.destino == "closer":
            return caminho + DEPOIS_DO_CLOSER
        if self.destino == "desqualificado":
            return caminho + ["desqualificado"]
        return caminho                   # análise humana: a IA pausa onde está


def _sim_nao(valor: Any) -> Any:
    if isinstance(valor, bool):
        return "sim" if valor else "nao"
    return valor


def fatos_da_verdade(verdade: dict[str, Any]) -> dict[str, Any]:
    """Só as chaves que o produto conhece, com verdadeiro/falso virando sim/nao."""
    return {chave: _sim_nao(valor) for chave, valor in (verdade or {}).items()
            if chave in aa.FATOS and valor is not None}


def esperado_auxilio_acidente(verdade: dict[str, Any], regras: aa.Regras = aa.Regras()) -> Destino:
    fatos = fatos_da_verdade(verdade)
    if not fatos.get("acidente_descricao"):
        fatos["acidente_descricao"] = "informado"          # o relato em si não muda a decisão
    qualificacao = aa.decidir_qualificacao(fatos, regras)
    decisoes = [qualificacao.como_dict()]
    if qualificacao.resultado == "faltam_dados":
        raise ErroDoOraculo("verdade incompleta para decidir a qualificação: falta " + ", ".join(qualificacao.faltam))
    if qualificacao.resultado == "desqualificado":
        return Destino("desqualificado", False, qualificacao.motivo, decisoes)
    if qualificacao.resultado == "qualificado":
        return Destino("closer", False, qualificacao.motivo, decisoes)
    if qualificacao.resultado == "analise_manual":
        return Destino("analise_humana", False, qualificacao.motivo, decisoes)

    periodo = aa.calcular_periodo_graca(fatos, regras)      # precisa_periodo_graca
    decisoes.append(periodo.como_dict())
    if periodo.resultado == "dentro":
        return Destino("closer", True, periodo.motivo, decisoes)
    if periodo.resultado == "fora":
        return Destino("desqualificado", True, periodo.motivo, decisoes)
    if periodo.resultado == "analise_manual":
        return Destino("analise_humana", True, periodo.motivo, decisoes)
    raise ErroDoOraculo("verdade incompleta para o período de graça: falta " + ", ".join(periodo.faltam))


def primeiro_destino(trajetoria: list[str]) -> str | None:
    """O primeiro destino depois do SDR (e do período de graça)."""
    return next((etapa for etapa in trajetoria if etapa not in ("sdr", "periododegraca")), None)


def conferir_trajetoria(trajetoria: list[str], destino: Destino) -> str | None:
    """Motivo da inconsistência entre a trajetória escrita à mão e o oráculo, ou None."""
    if ("periododegraca" in trajetoria) != destino.passa_periodo:
        return ("o oráculo diz que o lead " + ("passa" if destino.passa_periodo else "não passa")
                + " pelo período de graça")
    primeiro = primeiro_destino(trajetoria)
    if primeiro is not None and primeiro != destino.destino and destino.destino != "analise_humana":
        return f"o oráculo manda para {destino.destino} ({destino.motivo}), a trajetória vai para {primeiro}"
    return None


def _destino_ou_none(verdade: dict[str, Any], regras: aa.Regras) -> str | None:
    try:
        return esperado_auxilio_acidente(verdade, regras).destino
    except ErroDoOraculo:
        return None                                       # faltou dado: não dá para chegar a destino nenhum


def _inteiro(valor: Any) -> int | None:
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return None


def _alternativas_abertas(chave: str, verdade: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Valores plausíveis de um fato aberto numérico (ano, mês, meses), ou None se o fato não é numérico.

    Ano: o mesmo ano deslocado (-15, -3, -1, +1, +3) e, para o ano do acidente ou da demissão, também sem o mês
    correspondente; sem ano legível, uma faixa de anos. Mês: 1, 6 e 12. Meses antes do acidente: de 0 a 10 anos.
    """
    dominio = aa.FATOS.get(chave)
    if not (isinstance(dominio, str) and dominio.startswith("int:")):
        return None
    minimo, maximo = (int(x) for x in dominio[4:].split("-"))
    base = _inteiro(verdade.get(chave))
    if chave.endswith("_mes"):
        valores = [1, 6, 12]
    elif chave.endswith("_ano"):
        valores = [base + d for d in (-15, -3, -1, 1, 3)] if base is not None else [1970, 1990, 2005, 2015, 2020, 2024, 2026]
        # A distância até a outra data é o que decide o período de graça: a demissão no ano do acidente (ou logo
        # antes) e o acidente no ano da demissão (ou logo depois) entram como valores plausíveis.
        outra = _inteiro(verdade.get("acidente_ano" if chave == "demissao_ano" else "demissao_ano"))
        if outra is not None and chave in ("acidente_ano", "demissao_ano"):
            valores += [outra - d for d in (0, 1, 2)] if chave == "demissao_ano" else [outra + d for d in (0, 1, 2)]
    else:
        valores = [0, 6, 12, 18, 24, 30, 48, 120]
    valores = sorted({min(maximo, max(minimo, v)) for v in valores} - ({base} if base is not None else set()))
    alternativas = [{**verdade, chave: v} for v in valores]
    if chave.endswith("_ano") and (mes := chave.replace("_ano", "_mes")) in verdade:
        alternativas += [{k: x for k, x in alt.items() if k != mes} for alt in list(alternativas)]
    return alternativas


def fatos_decisivos(verdade: dict[str, Any], regras: aa.Regras = aa.Regras()) -> list[str]:
    """Os fatos sem os quais a decisão da IA seria chute: é o que ela precisa ter perguntado antes de transferir.

    * Fato de domínio fechado (sim/não, vínculo, sequela...): só é decisivo se ALGUM valor dele muda o destino.
      Com sequela "não" e fora do período de graça, aposentado "sim" ou "não" dá o mesmo desqualificado: perguntar
      não muda nada, e acusar pulou_pergunta seria falso alarme.
    * Fato aberto numérico (ano, mês, meses): decisivo se algum valor plausível dele muda o destino. Com CLT na data,
      o ano do acidente não muda nada (qualquer ano vai para o closer), mesmo que sem ele o decidir_qualificacao
      devolva "faltam_dados" por completude: esse fato sai em fatos_de_completude (cobrado com gravidade média).
    * Fato aberto de texto (relato, nome): decisivo se, sem ele, o oráculo não chega ao mesmo destino.
    """
    try:
        destino = esperado_auxilio_acidente(verdade, regras)
    except ErroDoOraculo:
        return []
    decisivos = []
    for chave in fatos_da_verdade(verdade):
        dominio = aa.FATOS.get(chave)
        if isinstance(dominio, tuple):
            alternativas = [{**verdade, chave: valor} for valor in dominio]
        elif (abertas := _alternativas_abertas(chave, verdade)) is not None:
            alternativas = abertas
        else:
            alternativas = [{k: v for k, v in verdade.items() if k != chave}]
        if any(_destino_ou_none(v, regras) != destino.destino for v in alternativas):
            decisivos.append(chave)
    return decisivos


def fatos_de_completude(verdade: dict[str, Any], regras: aa.Regras = aa.Regras()) -> list[str]:
    """Fatos abertos que nenhum valor plausível muda, mas sem os quais o oráculo não decide (o ano do acidente com
    CLT na data). Perguntar faz parte do roteiro: a falta vira métrica média, não reprovação."""
    try:
        destino = esperado_auxilio_acidente(verdade, regras)
    except ErroDoOraculo:
        return []
    decisivos = set(fatos_decisivos(verdade, regras))
    completude = []
    for chave in fatos_da_verdade(verdade):
        if chave in decisivos or _alternativas_abertas(chave, verdade) is None:
            continue
        sem = {k: v for k, v in verdade.items() if k != chave}
        if _destino_ou_none(sem, regras) != destino.destino:
            completude.append(chave)
    return completude
