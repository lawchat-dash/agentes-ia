"""Teste do dono (28/11) e tickets dos escritórios: uma pergunta por vez, sequela contada, advogado de antes e
desconfiança com os dados do escritório."""
from app.cerebro import extrator, turno


def _saida():
    return turno.Saida() if hasattr(turno, "Saida") else None


def test_eco_de_confirmacao_sai_quando_ha_outra_pergunta():
    saida = _saida()
    msgs = [{"tipo": "texto", "texto": "Entendi, João. Você recebeu auxílio-doença por 8 meses, certo?"},
            {"tipo": "texto", "texto": "O acidente gerou alguma sequela ou limitação, mesmo que leve?"}]
    novas = turno._sem_eco_de_confirmacao(saida, msgs, "", False)
    assert [m["texto"] for m in novas] == ["Entendi, João.", msgs[1]["texto"]]


def test_eco_unico_fica_e_confirmacao_de_desqualificar_fica():
    saida = _saida()
    so = [{"tipo": "texto", "texto": "Foi em maio de 2023, certo?"}]
    assert turno._sem_eco_de_confirmacao(saida, so, "", False) == so
    aposentado = [{"tipo": "texto", "texto": "Só pra eu não errar: você é aposentado, certo?"},
                  {"tipo": "texto", "texto": "E qual o seu nome?"}]
    assert turno._sem_eco_de_confirmacao(saida, aposentado, "", False) == aposentado
    assert turno._perguntas_juntas([m["texto"] for m in aposentado], "", False) == 2


def test_duas_perguntas_contam_menos_roteiro_e_contrato():
    assert turno._perguntas_juntas(["Faz sentido pra você? Podemos seguir com sua ficha?"], "", False) == 2
    roteiro = "Envie exatamente: Ficou claro pra você como funciona?"
    assert turno._perguntas_juntas(["Ficou claro pra você como funciona?", "Podemos seguir?"], roteiro, False) == 1
    assert turno._perguntas_juntas(["CPF: 123.456.789-09. Está tudo correto? Posso gerar o contrato?"], "", True) == 0


def test_desconfianca_e_dados_do_escritorio():
    assert turno._lead_desconfia(["eu to achando que isso e golpe nao sei nao"])
    assert not turno._lead_desconfia(["foi engano, desculpa"])
    conhecimento = {"dados_escritorio": "Escritório X\nOAB/SP 123.456\nCNPJ 12.345.678/0001-90"}
    assert turno._faltam_dados_do_escritorio(["Pode confiar, aqui não tem golpe."], conhecimento)
    assert not turno._faltam_dados_do_escritorio(["Somos o Escritório X, OAB/SP 123.456."], conhecimento)
    assert not turno._faltam_dados_do_escritorio(["Pode confiar."], {})


def test_pergunta_de_sequela_ja_informada_e_barrada():
    achados = turno._pergunta_de_dado_informado(["O acidente gerou alguma sequela ou limitação, mesmo que leve?"],
                                                {"sequela": "sim"})
    assert achados == ["a sequela"]


def test_sequela_contada_e_advogado_de_antes():
    n = extrator.normalizar
    assert extrator._SEQUELA_CONTADA.search(n("to ai até hoje com muita dificuldade de andar"))
    assert not extrator._SEQUELA_CONTADA.search(n("caí de moto em 2020"))
    antes = n("a advogada tinha mexido pra mim, mas foi negada, eu falei que ela pode deixar quieta")
    assert extrator._ADVOGADO_DE_ANTES.search(antes) and not extrator._ADVOGADO_HOJE.search(antes)
    assert not extrator._ADVOGADO_DE_ANTES.search(n("tenho advogado sim"))


def test_disse_que_enviou_sem_enviar():
    n = turno.normalizar_texto
    assert turno._DISSE_QUE_ENVIOU.search(n("Enviei o contrato para o seu e-mail"))
    assert turno._DISSE_QUE_ENVIOU.search(n("Já te enviei o áudio explicando, conseguiu ouvir?"))
    assert not turno._DISSE_QUE_ENVIOU.search(n("Você recebeu o áudio?"))
