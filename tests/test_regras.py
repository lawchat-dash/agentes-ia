"""Regras do Auxílio-Acidente: tabelas de casos, sem IA."""

import pytest

from app.cerebro.auxilio_acidente import (
    Regras, calcular_periodo_graca, decidir_etapa, decidir_qualificacao, validar_valor,
)

BASE = {
    "acidente_descricao": "caí da moto", "acidente_ano": 2023, "sequela": "sim",
    "aposentado": "nao", "tem_advogado_no_caso": "nao",
}


@pytest.mark.parametrize("fatos, resultado, motivo", [
    ({**BASE, "vinculo_na_data": "clt"}, "qualificado", "clt_na_data"),
    ({**BASE, "vinculo_na_data": "desempregado"}, "precisa_periodo_graca", "desempregado"),
    ({**BASE, "vinculo_na_data": "mei_autonomo_ci"}, "precisa_periodo_graca", "mei_autonomo_ci"),
    ({**BASE, "vinculo_na_data": "rural", "documentos_rurais": "sim"}, "qualificado", "rural_com_documentos"),
    ({**BASE, "vinculo_na_data": "rural", "documentos_rurais": "nao"}, "analise_manual", "rural_sem_documentos"),
    ({**BASE, "vinculo_na_data": "nao_sabe"}, "analise_manual", "vinculo_incerto"),
    ({**BASE, "vinculo_na_data": "clt", "sequela": "nao_sabe"}, "analise_manual", "sequela_incerta"),
    # O que desqualifica vale mesmo com dados faltando.
    ({"aposentado": "sim"}, "desqualificado", "aposentado"),
    ({"tem_advogado_no_caso": "sim"}, "desqualificado", "ja_tem_advogado"),
    ({"sequela": "nao"}, "desqualificado", "sem_sequela"),
    ({"vinculo_na_data": "servidor_estatutario"}, "desqualificado", "servidor_estatutario"),
    ({"vinculo_na_data": "nunca_trabalhou"}, "desqualificado", "nunca_trabalhou"),
])
def test_qualificacao(fatos, resultado, motivo):
    decisao = decidir_qualificacao(fatos)
    assert (decisao.resultado, decisao.motivo) == (resultado, motivo)


def test_qualificacao_pergunta_na_ordem():
    assert decidir_qualificacao({}).faltam[0] == "acidente_descricao"
    decisao = decidir_qualificacao({"acidente_descricao": "queda", "acidente_ano": 2022})
    assert decisao.resultado == "faltam_dados"
    assert decisao.faltam == ("sequela", "vinculo_na_data", "aposentado", "tem_advogado_no_caso")


def test_rural_pede_documentos():
    decisao = decidir_qualificacao({**BASE, "vinculo_na_data": "rural"})
    assert decisao.faltam == ("documentos_rurais",)


def _datas(demissao, acidente, seguro, **extra):
    fatos = {"acidente_mes": acidente[0], "acidente_ano": acidente[1], **extra}
    if demissao[0]:
        fatos["demissao_mes"] = demissao[0]
    fatos["demissao_ano"] = demissao[1]
    if seguro:
        fatos["seguro_desemprego"] = seguro
    return fatos


@pytest.mark.parametrize("fatos, resultado", [
    # Tabela da seção 12.1 do desenho.
    (_datas((3, 2022), (1, 2023), "nao"), "dentro"),                                          # 10 meses
    (_datas((3, 2022), (5, 2023), "nao", contribuiu_por_conta_propria="nao"), "fora"),         # 14 meses
    (_datas((3, 2022), (5, 2023), "sim"), "dentro"),                                           # 14 de 24
    (_datas((3, 2022), (4, 2024), "sim", contribuiu_por_conta_propria="nao"), "fora"),         # 25 meses
    # Só o ano da demissão: qualquer mês de 2022 fica dentro de 12 meses de 01/2023.
    (_datas((None, 2022), (1, 2023), "nao"), "dentro"),
    # Datas aproximadas.
    ({"demissao_meses_antes_do_acidente": 8}, "dentro"),                                       # de 7 a 9
    ({"demissao_ha_muitos_anos": "sim", "contribuiu_por_conta_propria": "nao"}, "fora"),
    ({"demissao_ha_muitos_anos": "sim", "contribuiu_por_conta_propria": "sim"}, "analise_manual"),
])
def test_periodo_de_graca(fatos, resultado):
    assert calcular_periodo_graca(fatos).resultado == resultado


@pytest.mark.parametrize("fatos, falta", [
    ({}, "demissao_quando"),
    ({"demissao_ha_muitos_anos": "sim"}, "contribuiu_por_conta_propria"),   # antes de desqualificar
    ({"demissao_meses_antes_do_acidente": 18}, "seguro_desemprego"),        # depende do seguro
    (_datas((None, 2021), (6, 2022), "nao"), "demissao_mes"),               # de 6 a 17 meses: perto do limite
])
def test_periodo_de_graca_pede_so_o_que_decide(fatos, falta):
    decisao = calcular_periodo_graca(fatos)
    assert decisao.resultado == "faltam_dados" and decisao.faltam == (falta,)


def test_prazos_sao_parametros():
    fatos = _datas((3, 2022), (5, 2023), "nao", contribuiu_por_conta_propria="nao")
    assert calcular_periodo_graca(fatos, Regras(prazo_sem_seguro_meses=18)).resultado == "dentro"


@pytest.mark.parametrize("etapa, fatos, intencoes, destino", [
    ("sdr", {}, {}, "sdr"),
    ("sdr", {**BASE, "vinculo_na_data": "clt"}, {}, "closer"),
    ("sdr", {**BASE, "vinculo_na_data": "desempregado"}, {}, "periodo_graca"),
    # Tudo dito de uma vez: resolve o período de graça no mesmo turno.
    ("sdr", {**BASE, "vinculo_na_data": "desempregado", "demissao_meses_antes_do_acidente": 8}, {}, "closer"),
    ("sdr", {**BASE, "vinculo_na_data": "mei_autonomo_ci", "demissao_ha_muitos_anos": "sim",
             "contribuiu_por_conta_propria": "nao"}, {}, "desqualificado"),
    ("sdr", {"aposentado": "sim"}, {}, "desqualificado"),
    ("periodo_graca", {**BASE, "vinculo_na_data": "desempregado", "demissao_meses_antes_do_acidente": 20,
                       "seguro_desemprego": "sim"}, {}, "closer"),
    ("periodo_graca", {**BASE, "vinculo_na_data": "desempregado", "aposentado": "sim"}, {}, "desqualificado"),
    ("closer", BASE, {"aceitou_honorarios": True}, "coleta_dados"),
    ("closer", BASE, {}, "closer"),
    ("desqualificado", {**BASE, "vinculo_na_data": "clt"}, {}, "desqualificado"),   # nunca volta sozinho
])
def test_etapa(etapa, fatos, intencoes, destino):
    assert decidir_etapa(etapa, fatos, intencoes).etapa == destino


@pytest.mark.parametrize("chave, valor, esperado", [
    ("sequela", "SIM", "sim"),
    ("sequela", "talvez", None),
    ("acidente_ano", "2021", 2021),
    ("acidente_mes", "13", None),
    ("chave_inventada", "x", None),
    ("acidente_descricao", "  caí da escada  ", "caí da escada"),
])
def test_valores_aceitos(chave, valor, esperado):
    assert validar_valor(chave, valor) == esperado
