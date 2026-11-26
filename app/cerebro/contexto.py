"""O que o sistema sabe e entrega pronto à IA: a data de hoje, a situação do contrato e as contas.

No n8n o agente usava a tool Calculator e lia "A data de hoje é ..." no topo do prompt. Aqui a conta é
feita no código e entra como fato do sistema; a data vem de um relógio que os testes podem fixar.
Tudo é função pura (a data entra por parâmetro quando o teste quer).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.cerebro import auxilio_acidente as aa

FUSO = "America/Sao_Paulo"
DIAS_DA_SEMANA = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo")


def agora_em_brasilia(agora: datetime | None = None) -> datetime:
    """Momento no fuso de Brasília (America/Sao_Paulo). Sem fuso no valor, ele é tratado como horário de Brasília."""
    from app.notificacoes import fuso

    local = fuso(FUSO)
    if agora is None:
        return datetime.now(local)
    return agora.replace(tzinfo=local) if agora.tzinfo is None else agora.astimezone(local)


def linha_de_hoje(agora: datetime | None = None) -> str:
    """'Hoje é 24/11/2026 (terça-feira), horário de Brasília 14:30.' (mesma ideia do 'A data de hoje é' do n8n)."""
    momento = agora_em_brasilia(agora)
    return (f"Hoje é {momento.strftime('%d/%m/%Y')} ({DIAS_DA_SEMANA[momento.weekday()]}), "
            f"horário de Brasília {momento.strftime('%H:%M')}. Sempre considere esta data como a data atual.")


# ---------------------------------------------------------------------------- contrato
def _data(valor: datetime | None) -> str | None:
    return agora_em_brasilia(valor).strftime("%d/%m/%Y %H:%M") if valor else None


def texto_do_contrato(situacao: str | None, *, versao: int | None = None, link: str | None = None,
                      gerado_em: datetime | None = None, assinado_em: datetime | None = None) -> str:
    """Situação do contrato para os fatos do sistema, como o bloco 'Fatos e resumo' do n8n.

    Assinado: diz que já foi assinado e quando. Gerado e não assinado: versão, data e o link vigente.
    """
    if situacao == "assinado":
        quando = _data(assinado_em)
        return f"JÁ ASSINADO pelo lead{' em ' + quando if quando else ''} (versão {versao})."
    if situacao == "gerado":
        quando = _data(gerado_em)
        texto = f"já foi gerado (versão {versao}){' em ' + quando if quando else ''} e AINDA NÃO foi assinado."
        if link:
            texto += f" Link: {link} (o sistema reenvia o link se pedirem)"
        return texto
    return "não gerado"


# ---------------------------------------------------------------------------- calculadora
# Fatos que a conta usa; o extrator do catálogo pede estes quando o papel de período de graça está ativo.
# Seguro-desemprego e contribuição por conta própria entram para a calculadora dizer se a pessoa estava coberta: sem eles,
# quem comparava os meses com o prazo era o modelo, de cabeça, e desqualificava quem estava dentro (16 meses com seguro).
FATOS_DO_PERIODO = ("acidente_mes", "acidente_ano", "demissao_mes", "demissao_ano",
                    "demissao_meses_antes_do_acidente", "demissao_ha_muitos_anos",
                    "seguro_desemprego", "contribuiu_por_conta_propria")


def _meses(n: float) -> str:
    return f"{int(n)} {'mês' if int(n) == 1 else 'meses'}"


def meses_entre_saida_e_acidente(fatos: dict[str, Any]) -> str | None:
    """Meses entre a saída do último emprego e o acidente, a partir do que o lead disse. None = falta dado.

    Usa a mesma conta do produto Auxílio-Acidente (aceita datas aproximadas e devolve a faixa possível).
    """
    try:
        if fatos.get("demissao_meses_antes_do_acidente") not in (None, ""):
            n = int(fatos["demissao_meses_antes_do_acidente"])
            return f"cerca de {_meses(n)} (o lead disse quanto tempo antes do acidente saiu do emprego)"
        intervalo = aa._intervalo_meses_entre_demissao_e_acidente(
            {chave: fatos.get(chave) for chave in FATOS_DO_PERIODO if fatos.get(chave) not in (None, "")})
    except (TypeError, ValueError):
        return None
    if intervalo is None:
        return None
    menor, maior = intervalo
    if maior == float("inf"):
        return f"mais de {_meses(menor)} (o lead disse que saiu do emprego faz anos)"
    if maior == 0 and fatos.get("demissao_ano") not in (None, "") and fatos.get("acidente_ano") not in (None, ""):
        acidente_ate = int(fatos["acidente_ano"]) * 12 + int(fatos.get("acidente_mes") or 12)
        saida_desde = int(fatos["demissao_ano"]) * 12 + int(fatos.get("demissao_mes") or 1)
        if acidente_ate < saida_desde:
            if fatos.get("vinculo_na_data") in SEM_CARTEIRA_NA_DATA:
                return SAIDA_DEPOIS_DO_ACIDENTE
            return "nenhum: o acidente foi ANTES da saída do último emprego (ainda estava empregado na data do acidente)"
    if menor == maior:
        return _meses(menor)
    return f"entre {int(menor)} e {_meses(maior)} (datas aproximadas; falta o mês exato)"


CHAVE_COBERTURA = "cobertura pelo INSS na data do acidente (calculado pelo sistema)"
# Na data do acidente o lead não tinha carteira (MEI, autônomo, desempregado): uma saída DEPOIS do acidente não cobre nada.
SEM_CARTEIRA_NA_DATA = ("mei_autonomo_ci", "desempregado", "nunca_trabalhou")
SAIDA_DEPOIS_DO_ACIDENTE = ("a saída informada é DEPOIS do acidente, e na data do acidente o lead não tinha carteira "
                            "assinada: pergunte qual foi o último emprego de carteira assinada ANTES do acidente (mês e "
                            "ano, pode ser aproximado). Se não teve nenhum antes, ele não estava coberto")


def _saida_depois_sem_carteira(fatos: dict[str, Any]) -> bool:
    try:
        if fatos.get("vinculo_na_data") not in SEM_CARTEIRA_NA_DATA:
            return False
        if fatos.get("demissao_ano") in (None, "") or fatos.get("acidente_ano") in (None, ""):
            return False
        acidente_ate = int(fatos["acidente_ano"]) * 12 + int(fatos.get("acidente_mes") or 12)
        saida_desde = int(fatos["demissao_ano"]) * 12 + int(fatos.get("demissao_mes") or 1)
        return acidente_ate < saida_desde
    except (TypeError, ValueError):
        return False


def cobertura_na_data_do_acidente(fatos: dict[str, Any], regras: aa.Regras | None = None) -> tuple[str, str] | None:
    """(resultado, texto) da conta do período de graça, sem citar prazo em meses. None = falta a data da saída.

    resultado: dentro | fora | falta_seguro | perto_do_limite. A decisão do que fazer com isso (contribuição por conta
    própria mantém ou não a cobertura, por exemplo) fica com o roteiro do escritório: aqui só vai a conta."""
    if _saida_depois_sem_carteira(fatos):
        return "falta_saida_antes", "ainda não dá para saber: falta o último emprego de carteira ANTES do acidente"
    dados = {chave: fatos.get(chave) for chave in FATOS_DO_PERIODO if fatos.get(chave) not in (None, "")}
    try:
        decisao = aa.calcular_periodo_graca(dados, regras or aa.Regras())
    except (TypeError, ValueError):
        return None
    if decisao.resultado == "dentro":
        return "dentro", "coberta na data do acidente"
    if decisao.resultado == "fora" or "contribuiu_por_conta_propria" in decisao.faltam \
            or decisao.motivo == "contribuiu_por_conta_propria":
        return "fora", "não coberta pelas datas"
    if "seguro_desemprego" in decisao.faltam:
        return "falta_seguro", ("depende de ter recebido seguro-desemprego (falta saber). Se o lead não lembrar, pergunte "
                                "uma vez de outro jeito (\"depois que saiu, você recebeu umas parcelas do governo por "
                                "alguns meses?\"); se continuar sem saber, siga para o Closer: a equipe confere no CNIS "
                                "depois do contrato")
    if decisao.resultado == "analise_manual":
        return "perto_do_limite", "perto do limite: peça análise humana"
    falta = {"demissao_mes": "falta o mês em que saiu do emprego", "acidente_mes": "falta o mês do acidente"}
    if decisao.resultado == "faltam_dados" and any(f in falta for f in decisao.faltam):
        return "perto_do_limite", "perto do limite (" + "; ".join(falta[f] for f in decisao.faltam if f in falta) + ")"
    return None


def fatos_da_calculadora(fatos: dict[str, Any], agora: datetime | None = None,
                         regras: aa.Regras | None = None) -> dict[str, str]:
    """Fatos calculados pelo código para o papel de período de graça (antiga tool Calculator).

    Tudo sai como FATO, nunca como ordem: o SDR de todo escritório tem a calculadora."""
    saida: dict[str, str] = {}
    meses = meses_entre_saida_e_acidente(fatos)
    if meses:
        saida["meses entre a saída do último emprego e o acidente (calculado pelo sistema)"] = meses
        if cobertura := cobertura_na_data_do_acidente(fatos, regras):
            saida[CHAVE_COBERTURA] = cobertura[1]
    tem_demissao = any(fatos.get(c) not in (None, "") for c in FATOS_DO_PERIODO if c.startswith("demissao"))
    if tem_demissao and not meses and fatos.get("acidente_ano") in (None, ""):
        saida["data do acidente (calculado pelo sistema)"] = "não informada pelo lead (sem ela não há conta)"
    hoje = agora_em_brasilia(agora)
    try:
        if fatos.get("acidente_ano") not in (None, "") and fatos.get("acidente_mes") not in (None, ""):
            desde = (hoje.year * 12 + hoje.month) - (int(fatos["acidente_ano"]) * 12 + int(fatos["acidente_mes"]))
            if desde >= 0:
                saida["meses desde o acidente até hoje (calculado pelo sistema)"] = _meses(desde)
            if desde == 0:
                # O mês de hoje como data do acidente quase sempre é "até hoje dói" lido como data.
                saida["data do acidente igual ao mês atual (calculado pelo sistema)"] = "confirme com o lead"
        dito = fatos.get("demissao_meses_antes_do_acidente")
        if dito not in (None, "") and all(fatos.get(c) not in (None, "") for c in
                                          ("acidente_mes", "acidente_ano", "demissao_mes", "demissao_ano")):
            pelas_datas = (int(fatos["acidente_ano"]) * 12 + int(fatos["acidente_mes"])
                           - int(fatos["demissao_ano"]) * 12 - int(fatos["demissao_mes"]))
            if abs(pelas_datas - int(dito)) > 2:
                saida["conflito nas datas (calculado pelo sistema)"] = (
                    f"o lead disse {_meses(int(dito))} entre a saída e o acidente, mas as datas dão {_meses(max(0, pelas_datas))}: confirme")
    except (TypeError, ValueError):
        pass
    return saida
