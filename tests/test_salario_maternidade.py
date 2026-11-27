"""Família salario_maternidade no motor do catálogo (Salário-Maternidade, INSS).

Fatos da família no extrator, calculadora (período de graça na data do evento e prazo de 5 anos), motivos de
desqualificar com a confirmação em 2 turnos no Closer, bloco nas regras do motor e a trava "gestante nunca é
desqualificada". Tudo com fakes (ModeloFalso); nenhum dado é de lead real.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.cerebro import catalogo, contexto, extrator, turno
from app.modelo import ModeloFalso

AGORA = datetime(2026, 11, 26, 10, 0, tzinfo=timezone(timedelta(hours=-3)))
PAPEIS = ("sdr", "periododegraca", "closer", "contratos", "assinatura", "desqualificado")
FRASES = {"closer": "Maravilha! Nós podemos te ajudar no seu caso.",
          "contratos": "Perfeito! Agora vou pegar os seus dados para o contrato.",
          "desqualificado": "Analisei com atenção o que você nos contou e você não se enquadra nos critérios."}
FATOS_SM = {"situacao", "evento_mes_ano", "categoria", "ultima_contribuicao_mes_ano", "seguro_desemprego",
            "dez_anos_contribuicao", "ja_recebeu_por_esse_filho", "tem_advogado_no_caso", "rural_tem_documento",
            "menor_16_no_parto"}
SM = {"catalogo": {"slug": "salario-maternidade-v2"}}


def produto(slug="salario-maternidade-v2", papeis=PAPEIS, **opcoes):
    cfg = {p: {"destinos": [d for d in papeis if d != p and d != "assinatura"], "mensagem_troca": FRASES.get(p)}
           for p in papeis}
    return catalogo.carregar({"catalogo": {"papeis": cfg, "slug": slug, "portao_de_fatos": False},
                              "funcoes": {"contrato_zapsign": True}, **opcoes})


def enum(prod):
    return set(prod.esquema_extrator()["properties"]["fatos"]["items"]["properties"]["chave"]["enum"])


def extrai(*fatos):
    return {"fatos": [{"chave": c, "valor": v, "trecho": t} for c, v, t in fatos], "sinais": [], "intencoes": {}}


def resposta(*textos, transferir="", notificacao=""):
    return {"mensagens": [{"texto": t} for t in textos], "transferir_para": transferir, "ferramenta": "",
            "notificacao": notificacao}


def entrada(novas, etapa="sdr", prod=None, fatos=None, historico=None):
    return turno.Entrada(escritorio="Escritório Teste", agente="Júlia", etapa=etapa, novas=list(novas),
                         produto=prod or produto(), instrucoes={etapa: "Siga o roteiro do papel."}, agora=AGORA,
                         fatos=dict(fatos or {}), modelo_extrator="gpt-4.1-mini",
                         historico=list(historico or [{"autor": "você", "texto": "Como posso te ajudar?"}]))


def conteudos(modelo):
    return [p["conteudo"] for p in modelo.pedidos if p["papel"] == "etapa"]


def sistemas(modelo):
    return [p["sistema"] for p in modelo.pedidos if p["papel"] == "etapa"]


# ---------------------------------------------------------------------------- família pelo slug
@pytest.mark.parametrize("slug", ["salario-maternidade", "salario_maternidade", "salario-maternidade-v2",
                                  "Salário-Maternidade", "salario-maternidade-rural"])
def test_familia_pelo_slug(slug):
    assert catalogo.familia_do_produto({"catalogo": {"slug": slug}}) == "salario_maternidade"


@pytest.mark.parametrize("slug, familia", [
    ("auxilio-acidente", "auxilio_acidente"), ("bpc-loas-autismo-v2", "bpc_infantil"), ("bpc-loas-idoso", "bpc_idoso"),
    ("bpc", "bpc_geral"), ("salario", "previdenciario"), ("maternidade", "previdenciario"),
    ("aposentadoria-especial", "previdenciario"),
])
def test_outras_familias_nao_mudam(slug, familia):
    assert catalogo.familia_do_produto({"catalogo": {"slug": slug}}) == familia


# ---------------------------------------------------------------------------- fatos do extrator
def test_fatos_da_familia_no_extrator_com_guia_e_sem_os_do_acidente():
    sdr = produto().para_o_papel("sdr")
    chaves = enum(sdr)
    assert FATOS_SM <= chaves
    assert not {"acidente_ano", "demissao_mes", "sequela", "aposentado", "beneficiario_idade"} & chaves
    guia = sdr.guia_do_extrator()
    for fato in FATOS_SM:
        assert f"- {fato}: " in guia, fato
    assert "SINE" in guia and "MM/AAAA" in guia and "Datas do trabalho e do acidente" not in guia


def test_validacao_dos_valores():
    sdr = produto().para_o_papel("sdr")
    assert sdr.validar_valor("evento_mes_ano", "7/2025") == "07/2025"
    assert sdr.validar_valor("evento_mes_ano", "2025-07") == "07/2025"
    assert sdr.validar_valor("evento_mes_ano", "julho de 2025") == "07/2025"
    assert sdr.validar_valor("evento_mes_ano", "13/2025") is None and sdr.validar_valor("evento_mes_ano", "2025") is None
    assert sdr.validar_valor("ultima_contribuicao_mes_ano", "03/2023") == "03/2023"
    assert sdr.validar_valor("seguro_desemprego", "nao_sabe") == "nao_sabe"
    assert sdr.validar_valor("dez_anos_contribuicao", "SIM") == "sim"
    assert sdr.validar_valor("situacao", "gestante") == "gestante" and sdr.validar_valor("situacao", "grávida") is None
    assert sdr.validar_valor("categoria", "estatutaria") == "estatutaria"
    assert sdr.validar_valor("categoria", "concursada") is None
    assert sdr.validar_valor("ja_recebeu_por_esse_filho", "talvez") is None


def test_auxilio_acidente_continua_igual():
    aa = produto("auxilio-acidente").para_o_papel("sdr")
    assert not (FATOS_SM - {"seguro_desemprego", "tem_advogado_no_caso"}) & enum(aa)
    assert aa.validar_valor("seguro_desemprego", "nao_sabe") is None      # no AA o seguro segue só sim/nao
    assert "SINE" not in aa.guia_do_extrator()


def test_resposta_curta_as_perguntas_da_familia():
    sdr = produto().para_o_papel("sdr")

    def curta(pergunta, texto):
        historico = [{"autor": "você", "texto": pergunta}]
        return [(f.chave, f.valor) for f in extrator.pela_pergunta(extrator.Extracao(), historico, [texto], {}, sdr).fatos]

    assert curta("Você já recebeu o salário-maternidade por esse filho?", "Não") == [("ja_recebeu_por_esse_filho", "nao")]
    assert curta("Você contribuiu por 10 anos ou mais?", "não sei") == [("dez_anos_contribuicao", "nao_sabe")]
    assert curta("Você recebeu seguro-desemprego quando saiu?", "sim") == [("seguro_desemprego", "sim")]
    assert curta("Você tinha menos de 16 anos quando o bebê nasceu?", "não") == [("menor_16_no_parto", "nao")]
    assert curta("Você tem algum documento do trabalho na roça?", "tenho") == [("rural_tem_documento", "sim")]


# ---------------------------------------------------------------------------- calculadora: período de graça
def _graca(ultima, evento, seguro="nao", dez="nao", categoria="desempregada"):
    return contexto.periodo_de_graca_maternidade({
        "situacao": "pos_parto", "categoria": categoria, "ultima_contribuicao_mes_ano": ultima,
        "evento_mes_ano": evento, "seguro_desemprego": seguro, "dez_anos_contribuicao": dez})


@pytest.mark.parametrize("ultima, evento, seguro, dez, resultado, meses", [
    ("11/2024", "07/2025", "nao", "nao", "dentro", 8),
    ("03/2023", "01/2025", "nao", "sim", "dentro", 22),
    ("05/2022", "02/2025", "sim", "sim", "dentro", 33),
    ("09/2024", "09/2025", "nao", "nao", "dentro", 12),       # empate = dentro
    ("01/2023", "06/2024", "nao", "nao", "fora", 17),
    ("02/2021", "09/2023", "sim", "nao", "fora", 31),
    ("01/2020", "08/2023", "sim", "sim", "fora", 43),
])
def test_periodo_de_graca_exemplos(ultima, evento, seguro, dez, resultado, meses):
    conta = _graca(ultima, evento, seguro, dez)
    assert (conta["resultado"], conta["meses"]) == (resultado, meses)


def test_periodo_de_graca_maximo_36_e_depende_do_que_falta():
    assert _graca("01/2020", "01/2023", "sim", "sim")["resultado"] == "dentro"          # 36 = máximo, empate
    assert _graca("01/2020", "02/2023", "sim", "sim")["resultado"] == "fora"            # 37
    falta = _graca("01/2023", "06/2024", seguro=None, dez="nao")                       # 17: o seguro decide
    assert falta["resultado"] == "depende" and "seguro-desemprego" in falta["texto"] and "10 anos" not in falta["texto"]
    ambos = _graca("01/2022", "06/2024", seguro="nao_sabe", dez="nao_sabe")            # 29: precisa dos dois
    assert ambos["resultado"] == "depende" and " e " in ambos["texto"]
    assert _graca("01/2021", "06/2024", seguro=None, dez=None)["resultado"] == "fora"  # 41: nem com tudo


def test_cobertura_sem_conta_por_categoria():
    base = {"situacao": "pos_parto", "evento_mes_ano": "07/2025"}
    for categoria in ("clt_ativa", "domestica", "intermitente"):
        assert contexto.periodo_de_graca_maternidade({**base, "categoria": categoria})["resultado"] == "dentro"
    rural = {**base, "categoria": "rural"}
    assert contexto.periodo_de_graca_maternidade({**rural, "rural_tem_documento": "sim"})["resultado"] == "dentro"
    assert contexto.periodo_de_graca_maternidade({**rural, "rural_tem_documento": "nao"})["resultado"] == "fora"
    assert contexto.periodo_de_graca_maternidade(rural)["resultado"] == "depende"
    assert contexto.periodo_de_graca_maternidade({**base, "categoria": "estatutaria"})["resultado"] == "fora"
    # Sem a última contribuição não há conta; contribuição depois do evento pede confirmação.
    assert contexto.periodo_de_graca_maternidade({**base, "categoria": "mei"}) is None
    depois = contexto.periodo_de_graca_maternidade({**base, "categoria": "mei", "ultima_contribuicao_mes_ano": "10/2025"})
    assert depois["resultado"] == "confirmar"


def test_gestante_nao_tem_conta():
    gestante = {"situacao": "gestante", "categoria": "desempregada", "ultima_contribuicao_mes_ano": "01/2020",
                "evento_mes_ano": "01/2027"}
    assert contexto.periodo_de_graca_maternidade(gestante) is None
    assert contexto.fatos_da_calculadora_maternidade(gestante, AGORA) == {}


# ---------------------------------------------------------------------------- calculadora: prazo de 5 anos
@pytest.mark.parametrize("evento, resultado", [
    ("12/2021", "dentro"),       # 59 meses
    ("11/2021", "dentro"),       # 60 meses: o último mês (faltando qualquer coisa = dentro)
    ("10/2021", "fora"),         # 61 meses: passou de 5 anos
    ("07/2025", "dentro"),
])
def test_prazo_de_5_anos_na_borda(evento, resultado):
    assert contexto.prazo_de_5_anos({"situacao": "pos_parto", "evento_mes_ano": evento}, AGORA)["resultado"] == resultado


def test_linhas_do_sistema_so_com_dados():
    assert contexto.fatos_da_calculadora_maternidade({}, AGORA) == {}
    linhas = contexto.fatos_da_calculadora_maternidade(
        {"situacao": "pos_parto", "categoria": "clt_saiu", "evento_mes_ano": "07/2025",
         "ultima_contribuicao_mes_ano": "11/2024", "seguro_desemprego": "nao", "dez_anos_contribuicao": "nao"}, AGORA)
    assert linhas == {contexto.CHAVE_COBERTURA_EVENTO: "coberta na data do evento (dentro do período de graça)",
                      contexto.CHAVE_PRAZO_5_ANOS: "dentro do prazo de 5 anos"}
    so_prazo = contexto.fatos_da_calculadora_maternidade({"evento_mes_ano": "10/2021"}, AGORA)
    assert list(so_prazo) == [contexto.CHAVE_PRAZO_5_ANOS] and "passou de 5 anos" in so_prazo[contexto.CHAVE_PRAZO_5_ANOS]


async def test_turno_do_sdr_e_do_periodo_de_graca_levam_as_linhas():
    fatos = {"situacao": "pos_parto", "categoria": "desempregada", "evento_mes_ano": "06/2024",
             "ultima_contribuicao_mes_ano": "01/2023", "seguro_desemprego": "nao", "dez_anos_contribuicao": "nao"}
    for etapa in ("sdr", "periododegraca"):
        modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Entendi.")})
        await turno.processar(modelo, entrada(["ok"], etapa=etapa, fatos=fatos))
        sistema = sistemas(modelo)[0]
        assert "cobertura pelo INSS na data do evento (calculado pelo sistema)" in sistema
        assert "não coberta pelas datas" in sistema and "prazo de 5 anos (calculado pelo sistema)" in sistema
        assert "Datas e contas (Salário-Maternidade)" in sistema and "data do acidente" not in sistema
    # Closer não tem a calculadora: nada da conta.
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Entendi.")})
    await turno.processar(modelo, entrada(["ok"], etapa="closer", fatos=fatos))
    assert "cobertura pelo INSS na data do evento" not in sistemas(modelo)[0]


async def test_auxilio_acidente_segue_com_a_calculadora_dele():
    prod = produto("auxilio-acidente")
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Entendi.")})
    await turno.processar(modelo, entrada(["ok"], prod=prod, fatos={"acidente_mes": 3, "acidente_ano": 2025,
                                                                     "demissao_mes": 1, "demissao_ano": 2025}))
    sistema = sistemas(modelo)[0]
    assert contexto.CHAVE_COBERTURA in sistema and contexto.CHAVE_COBERTURA_EVENTO not in sistema
    assert "Datas e contas (Salário-Maternidade)" not in sistema and "Salário-Maternidade\n-" not in sistema


# ---------------------------------------------------------------------------- regras da família
def test_bloco_da_familia_nas_regras_do_motor():
    regras = catalogo.regras_do_motor("sdr", {"calculadora": True}, ["closer"], familia="salario_maternidade")
    assert "Salário-Maternidade\n- Nunca mostre ao lead a conta" in regras
    assert "nunca vai para o Período de Graça" in regras and "Não peça certidão" in regras
    assert "O benefício é da mãe (ou de quem adotou)" in regras
    assert "Datas e contas (Salário-Maternidade)" in regras and "cobertura pelo INSS na data do acidente" not in regras
    # Outras famílias: nada novo.
    for familia in ("auxilio_acidente", "bpc_infantil", "previdenciario"):
        assert "Salário-Maternidade" not in catalogo.regras_do_motor("sdr", {"calculadora": True}, ["closer"],
                                                                     familia=familia)
    chaves = [b["chave"] for b in catalogo.blocos_do_sistema()]
    assert "familia_salario_maternidade" in chaves and "calculadora_salario_maternidade" in chaves


# ---------------------------------------------------------------------------- motivos de desqualificar
@pytest.mark.parametrize("fatos, motivo", [
    ({"ja_recebeu_por_esse_filho": "sim"}, "ja_recebeu_por_esse_filho"),
    ({"tem_advogado_no_caso": "sim"}, "tem_advogado_no_caso"),
    ({"categoria": "estatutaria"}, "categoria"),
    ({"categoria": "rural", "rural_tem_documento": "nao"}, "rural_tem_documento"),
    ({"menor_16_no_parto": "sim", "categoria": "mei"}, "menor_16_no_parto"),
])
def test_motivos_da_familia(fatos, motivo):
    assert catalogo.motivo_de_desqualificar(SM, fatos)[0] == motivo


def test_nunca_desqualifica():
    for fatos in ({"menor_16_no_parto": "sim", "categoria": "rural"}, {"aposentado": "sim"},
                  {"categoria": "clt_saiu", "ja_recebeu_por_esse_filho": "nao"}, {"situacao": "gestante"},
                  {"evento_mes_ano": "07/2025"}):
        assert catalogo.motivo_de_desqualificar(SM, fatos) is None, fatos
    # As outras famílias seguem com os motivos de sempre.
    assert catalogo.motivo_de_desqualificar({"catalogo": {"slug": "auxilio-acidente"}}, {"aposentado": "sim"}) == \
        ("aposentado", "sim")
    assert catalogo.motivo_de_desqualificar({"catalogo": {"slug": "auxilio-acidente"}}, {"categoria": "estatutaria"}) is None


@pytest.mark.parametrize("chave, valor, trecho, pergunta", [
    ("ja_recebeu_por_esse_filho", "sim", "já recebi por esse filho", "já recebeu o salário-maternidade por este mesmo filho?"),
    ("tem_advogado_no_caso", "sim", "tenho advogado cuidando disso", "deste mesmo caso?"),
    ("categoria", "estatutaria", "sou concursada da prefeitura", "concursada, servidora pública de regime próprio?"),
])
async def test_closer_confirma_em_2_turnos(chave, valor, trecho, pergunta):
    modelo = ModeloFalso({"extrator": extrai((chave, valor, trecho)),
                          "etapa": resposta("Só pra eu não errar: " + pergunta)})
    saida = await turno.processar(modelo, entrada([trecho], etapa="closer"))
    assert "Só pra eu não errar" in conteudos(modelo)[0] and pergunta in conteudos(modelo)[0]
    assert saida.fatos_depois[turno.MARCA_DESQ_A_CONFIRMAR] == chave and saida.etapa_depois == "closer"
    historico = [{"autor": "lead", "texto": trecho}, {"autor": "você", "texto": "Só pra eu não errar: " + pergunta}]
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta(FRASES["desqualificado"], transferir="desqualificado")})
    saida = await turno.processar(modelo, entrada(["sim"], etapa="closer", historico=historico,
                                                  fatos={chave: valor, turno.MARCA_DESQ_A_CONFIRMAR: chave}))
    assert "Se ele confirmou, marque transferir_para = \"desqualificado\"" in conteudos(modelo)[0]
    assert saida.etapa_depois == "desqualificado"


async def test_closer_nao_confirma_menor_de_16_rural():
    modelo = ModeloFalso({"extrator": extrai(("menor_16_no_parto", "sim", "eu tinha 15 anos quando ele nasceu")),
                          "etapa": resposta("Entendi, seguimos.")})
    saida = await turno.processar(modelo, entrada(["eu tinha 15 anos quando ele nasceu"], etapa="closer",
                                                  fatos={"categoria": "rural"}))
    assert "Só pra eu não errar" not in conteudos(modelo)[0]
    assert not saida.fatos_depois.get(turno.MARCA_DESQ_A_CONFIRMAR)


# ---------------------------------------------------------------------------- trava da gestante
def test_gestante_sem_motivo():
    prod = produto()
    assert turno._gestante_sem_motivo(prod, {"situacao": "gestante"})
    assert turno._gestante_sem_motivo(prod, {"situacao": "gestante", "ultima_contribuicao_mes_ano": "01/2019"})
    assert not turno._gestante_sem_motivo(prod, {"situacao": "gestante", "tem_advogado_no_caso": "sim"})
    assert not turno._gestante_sem_motivo(prod, {"situacao": "gestante", "categoria": "estatutaria"})
    assert not turno._gestante_sem_motivo(prod, {"situacao": "pos_parto"})
    assert not turno._gestante_sem_motivo(produto("bpc-loas-idoso"), {"situacao": "gestante"})


async def test_gestante_desqualificada_refaz_com_orientacao():
    respostas = iter([resposta(FRASES["desqualificado"], transferir="desqualificado"),
                      resposta("Entendi! Vamos seguir com o seu caso.")])
    modelo = ModeloFalso({"extrator": extrai(), "etapa": lambda _s, _c: next(respostas)})
    saida = await turno.processar(modelo, entrada(["tô grávida de 5 meses"], fatos={"situacao": "gestante"}))
    assert len(conteudos(modelo)) == 2 and turno.ORIENTACAO_GESTANTE in conteudos(modelo)[1]
    assert saida.etapa_depois == "sdr"


async def test_gestante_desqualificada_duas_vezes_vira_analise_da_equipe():
    modelo = ModeloFalso({"extrator": extrai(),
                          "etapa": resposta(FRASES["desqualificado"], transferir="desqualificado")})
    saida = await turno.processar(modelo, entrada(["tô grávida"], fatos={"situacao": "gestante"}))
    assert saida.etapa_depois != "desqualificado"
    assert "gestante_nao_desqualifica" in [e["tipo"] for e in saida.eventos]


async def test_gestante_com_advogado_desqualifica():
    modelo = ModeloFalso({"extrator": extrai(),
                          "etapa": resposta(FRASES["desqualificado"], transferir="desqualificado")})
    saida = await turno.processar(modelo, entrada(["tô grávida"], fatos={"situacao": "gestante",
                                                                         "tem_advogado_no_caso": "sim"}))
    assert len(conteudos(modelo)) == 1 and saida.etapa_depois == "desqualificado"


def test_gestante_clt_ativa_pode_ser_desqualificada():
    """Validação 27/11 (sm01): gestante CLT sem 2ª renda recebe pela empresa; a trava não pode impedir a desqualificação."""
    from app.cerebro import turno

    class P:
        config = {"catalogo": {"slug": "salario-maternidade-v2"}}
    assert not turno._gestante_sem_motivo(P(), {"situacao": "gestante", "categoria": "clt_ativa"})
    assert turno._gestante_sem_motivo(P(), {"situacao": "gestante", "categoria": "desempregada"})
