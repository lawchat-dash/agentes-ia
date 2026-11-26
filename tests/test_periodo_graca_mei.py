"""Período de Graça: MEI sem carteira no acidente, seguro "não lembro" e o presencial na 2ª vez."""
from app.cerebro import contexto


def test_mei_com_saida_depois_do_acidente_nao_fica_coberto():
    fatos = {"acidente_ano": 2014, "acidente_mes": 6, "demissao_ano": 2019, "demissao_mes": 5,
             "vinculo_na_data": "mei_autonomo_ci"}
    resultado, texto = contexto.cobertura_na_data_do_acidente(fatos)
    assert resultado == "falta_saida_antes" and "ANTES do acidente" in texto
    meses = contexto.meses_entre_saida_e_acidente(fatos)
    assert "DEPOIS do acidente" in meses and "não estava coberto" in meses


def test_clt_com_saida_depois_do_acidente_continua_empregado_na_data():
    fatos = {"acidente_ano": 2014, "acidente_mes": 6, "demissao_ano": 2019, "demissao_mes": 5, "vinculo_na_data": "clt"}
    assert "ainda estava empregado" in contexto.meses_entre_saida_e_acidente(fatos)


def test_saida_dois_meses_antes_e_coberta_sem_perguntar_o_seguro():
    fatos = {"acidente_ano": 2013, "acidente_mes": 5, "demissao_ano": 2013, "demissao_mes": 3,
             "vinculo_na_data": "mei_autonomo_ci"}
    assert contexto.cobertura_na_data_do_acidente(fatos)[0] == "dentro"


def test_seguro_incerto_orienta_a_perguntar_de_outro_jeito_e_seguir():
    fatos = {"acidente_ano": 2016, "acidente_mes": 5, "demissao_ano": 2015, "demissao_mes": 3}
    resultado, texto = contexto.cobertura_na_data_do_acidente(fatos)
    assert resultado == "falta_seguro" and "parcelas do governo" in texto and "siga para o Closer" in texto


def test_boas_chances_so_passa_no_closer():
    from app.cerebro import catalogo
    msg = [{"tipo": "texto", "texto": "Pelo que você contou, o caso é bom e há boas chances. Quer seguir?"}]
    assert catalogo.conferir(msg, "closer") == []
    assert catalogo.conferir(msg, "sdr")
    assert catalogo.conferir([{"tipo": "texto", "texto": "Seu caso vai ganhar, é garantido."}], "closer")


def test_chips_do_bpc_da_karina():
    from app.cerebro import catalogo
    assert catalogo.ferramentas_do_prompt("Pergunte o CEP. Depois @Buscar o CEP.")[1] == ["buscar_cep"]
    assert catalogo.ferramentas_do_prompt("Após o sim, @ZapSign Documento.")[1] == ["zapsign"]
    assert catalogo.ferramentas_do_prompt("👉 @Agente Coleta de Dados")[0] == ["contratos"]
