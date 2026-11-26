"""Regressões da bateria REAL de 2026-11-25 (docs/DIAGNOSTICO_RODADA_REAL_2026-11-25.md, seção 2 e itens 1 a 4 da seção 4).

- a trava barrava "100% online pelo WhatsApp" (dado do escritório) e "com certeza" solto: o lead que perguntou do site
  ficava pausado; a orientação genérica não dizia o que caiu e a 2ª tentativa errava de novo;
- o texto barrado não ficava gravado: agora cada tentativa reprovada vai em contexto["tentativas"];
- lead sem e-mail: "não tenho" no campo email travava o contrato num laço de correções com "o link chega em instantes";
- "já te falei" virava objeção; o bloco de fatos não dizia para não perguntar de novo; a boas-vindas saía sem pergunta.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.cerebro import auditor, catalogo, extrator, sinais, travas, turno
from app.contrato import dados as cdados
from app.modelo import ModeloFalso

AGORA = datetime(2026, 11, 25, 10, 0, tzinfo=timezone(timedelta(hours=-3)))
SEM_INTENCAO = {"pediu_humano": False, "pediu_para_parar": False, "engano": False, "diz_que_assinou": False, "pediu_link": False}
CONTRATO_SEM_CPF = {"nome_completo": "Patrícia Souza Lima", "endereco": "Rua das Flores", "numero_casa": "12",
                    "bairro": "Centro", "cidade": "Campinas", "uf": "SP", "cep": "13010-100"}
CPF_VALIDO = "529.982.247-25"


def _texto(s):
    return [{"tipo": "texto", "texto": s}]


def _promessa_na_trava(s):
    return [r for r in travas.conferir(_texto(s), etapa="sdr", honorarios=None, midias={}, faltam=()) if r.codigo == "promessa"]


def produto(papeis=("sdr", "closer", "contratos", "assinatura", "desqualificado"), **papel_extra):
    return catalogo.carregar({"catalogo": {"papeis": {p: dict(papel_extra.get(p) or {}) for p in papeis}},
                              "funcoes": {"contrato_zapsign": True}})


def extrai(fatos=(), **intencoes):
    return {"fatos": [{"chave": c, "valor": v, "trecho": t} for c, v, t in fatos], "sinais": [],
            "intencoes": {**SEM_INTENCAO, **intencoes}}


def resposta(texto="Certo!", transferir="", ferramenta=""):
    return {"mensagens": [{"texto": texto}], "transferir_para": transferir, "ferramenta": ferramenta}


def entrada(novas, etapa="sdr", prod=None, **extra):
    return turno.Entrada(escritorio="Escritório Teste", agente="Júlia", etapa=etapa, novas=list(novas),
                         produto=prod or produto(), instrucoes={etapa: "Roteiro do papel."}, agora=AGORA, **extra)


# ---------------------------------------------------------------------------- trava de promessa
@pytest.mark.parametrize("frase", [
    "Nosso atendimento é 100% online pelo WhatsApp.",
    "Atendimento 100% on-line, sem sair de casa.",
    "O processo é 100% digital.",
    "Atendemos 100% pelo WhatsApp.",
    "Funciona 100% a distância.",
    "É cem por cento online!",
    "Claro, com certeza! O atendimento é por aqui.",
    "Com certeza. Me conta o que aconteceu?",
    "O que posso garantir é que cuidamos de todo o pedido.",     # serviço, não resultado: "garant" não entra na trava
])
def test_jeito_de_atender_e_com_certeza_solto_nao_sao_promessa(frase):
    assert catalogo.conferir(_texto(frase)) == [], frase
    assert _promessa_na_trava(frase) == [], frase


@pytest.mark.parametrize("frase, trecho", [
    ("É 100% garantido.", "100% garantido"),
    ("Você tem 100% de chance!", "100% de chance"),
    ("Pode ficar tranquilo, você vai ganhar.", "vai ganhar"),
    ("Com certeza vai dar certo.", "com certeza vai"),
    ("Tenho certeza que vai ganhar.", "vai ganhar"),
    ("Com certeza você ganha.", "com certeza você ganha"),
    ("100% online e 100% garantido.", "100% garantido"),
])
def test_promessa_de_resultado_continua_barrada_e_a_orientacao_cita_o_trecho(frase, trecho):
    erros = catalogo.conferir(_texto(frase))
    assert erros == [f"Reescreva sem a expressão '{trecho}'."], frase
    assert "resultado" not in erros[0]
    reprovacao = _promessa_na_trava(frase)
    assert reprovacao and f"'{trecho}'" in reprovacao[0].orientacao, frase


def test_gratuito_nao_fica_isento_do_cem_por_cento():
    assert catalogo.conferir(_texto("É 100% gratuito.")) == ["Reescreva sem a expressão '100% gratuito'."]


# ---------------------------------------------------------------------------- tentativas gravadas
async def test_catalogo_grava_o_texto_reprovado_e_o_motivo():
    modelo = ModeloFalso({"extrator": extrai(),
                          "etapa": [resposta("Pode ficar tranquila, você vai ganhar!"), resposta("Me conta o que aconteceu?")]})
    saida = await turno.processar(modelo, entrada(["tenho direito?"]))
    assert saida.mensagens[0]["texto"] == "Me conta o que aconteceu?"
    assert saida.contexto["tentativas"] == [{"texto": "Pode ficar tranquila, você vai ganhar!",
                                             "reprovacoes": ["Reescreva sem a expressão 'vai ganhar'."]}]
    assert saida.reprovacoes == [[{"codigo": "catalogo", "orientacao": "Reescreva sem a expressão 'vai ganhar'."}], []]
    assert "CORRIJA: Reescreva sem a expressão 'vai ganhar'." in modelo.pedidos[2]["conteudo"]


async def test_catalogo_reprovado_duas_vezes_grava_as_duas_tentativas():
    modelo = ModeloFalso({"extrator": extrai(),
                          "etapa": [resposta("É 100% garantido."), resposta("Com certeza vai dar certo.")]})
    saida = await turno.processar(modelo, entrada(["e aí?"]))
    assert saida.motivo_estado == "trava_persistente"
    assert [t["texto"] for t in saida.contexto["tentativas"]] == ["É 100% garantido.", "Com certeza vai dar certo."]
    assert saida.contexto["tentativas"][1]["reprovacoes"] == ["Reescreva sem a expressão 'com certeza vai'."]


async def test_aprovada_de_primeira_nao_grava_tentativa():
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Nosso atendimento é 100% online pelo WhatsApp.")})
    saida = await turno.processar(modelo, entrada(["vocês têm site?"]))
    assert saida.estado_lead is None and "tentativas" not in saida.contexto


async def test_auxilio_acidente_tambem_grava_a_tentativa():
    modelo = ModeloFalso({"extrator": {"fatos": [], "sinais": [], "intencoes": {}},
                          "etapa": [{"mensagens": [{"tipo": "texto", "texto": "Você vai ganhar!", "chave": ""}]},
                                    {"mensagens": [{"tipo": "texto", "texto": "Me conta como foi o acidente?", "chave": ""}]}]})
    saida = await turno.processar(modelo, turno.Entrada(escritorio="Escritório Teste", agente="Júlia", etapa="sdr",
                                                        novas=["tenho direito?"], agora=AGORA))
    assert saida.contexto["tentativas"] == [{"texto": "Você vai ganhar!",
                                             "reprovacoes": ["Reescreva sem a expressão 'vai ganhar'."]}]


# ---------------------------------------------------------------------------- contrato sem e-mail
def test_email_invalido_nao_obrigatorio_vira_vazio_sem_erro():
    brutos = cdados.dados_dos_fatos({**CONTRATO_SEM_CPF, "cpf": CPF_VALIDO, "email": "não tenho"})
    dados, erros = cdados.validar_dados(brutos)
    assert erros == [] and "email" not in dados


def test_email_invalido_obrigatorio_ainda_pede_correcao():
    brutos = cdados.dados_dos_fatos({**CONTRATO_SEM_CPF, "cpf": CPF_VALIDO, "email": "não tenho"})
    _, erros = cdados.validar_dados(brutos, obrigatorios=cdados.OBRIGATORIOS_PADRAO + ("email",))
    assert [e.campo for e in erros] == ["email"]


def test_email_valido_continua_no_contrato():
    brutos = cdados.dados_dos_fatos({**CONTRATO_SEM_CPF, "cpf": CPF_VALIDO, "email": "Patricia@Exemplo.com"})
    dados, erros = cdados.validar_dados(brutos)
    assert erros == [] and dados["email"] == "patricia@exemplo.com"


def test_extrator_descarta_email_sem_arroba():
    prod = produto()
    extracao = extrator.conferir(
        {"fatos": [{"chave": "email", "valor": "não tenho", "trecho": "não tenho e-mail"}], "sinais": [], "intencoes": {}},
        ["não tenho e-mail"], {}, prod)
    assert extracao.fatos == [] and extracao.rejeitados[0]["motivo"] == "email_sem_arroba"
    certo = extrator.conferir(
        {"fatos": [{"chave": "email", "valor": "ana@exemplo.com", "trecho": "ana@exemplo.com"}], "sinais": [], "intencoes": {}},
        ["meu email é ana@exemplo.com"], {}, prod)
    assert [f.valor for f in certo.fatos] == ["ana@exemplo.com"]


def test_guias_do_extrator_dizem_que_nao_tenho_email_e_vazio():
    assert "só com @" in produto().guia_do_extrator()
    assert "email só se tiver @" in extrator.REGRAS_GERAIS + extrator.GUIA_AUXILIO_ACIDENTE


async def test_prompt_do_zapsign_proibe_prometer_o_link_antes_do_sistema():
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Vou gerar o seu contrato.")})
    await turno.processar(modelo, entrada(["pode gerar"], etapa="contratos"))
    sistema = modelo.pedidos[1]["sistema"]
    assert "Não diga que o link \"chega em instantes\"" in sistema
    assert "não tem e-mail, siga sem ele" in sistema


def test_etapa_de_dados_do_auxilio_acidente_nao_promete_o_link_antes_do_zapsign():
    # Mesma regra do catálogo (FORMATO_FERRAMENTAS): o sistema confere os dados e só então manda o link ou pede o que falta.
    from app.cerebro import agente
    from app.cerebro.produto import AuxilioAcidente

    sistema = agente.montar_sistema(nome="Júlia", escritorio="Escritório Exemplo", etapa="coleta_dados", instrucao=None,
                                    produto=AuxilioAcidente(contrato=True))
    assert "diga só que vai gerar o contrato" in sistema
    assert 'Não diga que o link "chega em instantes" nem que já foi enviado' in sistema
    assert "e que o link chega em instantes" not in sistema
    regra = "o sistema confere os dados antes e ele mesmo manda o link ou pede o dado que faltar"
    assert regra in " ".join(sistema.split()) and regra in " ".join(catalogo.FORMATO_FERRAMENTAS["zapsign"].split())


def _historico_com_correcao():
    pedido = cdados.pedir_correcao([cdados.CampoInvalido("cpf", cdados.PEDIR["cpf"])])
    return [{"autor": "lead", "texto": "pode gerar"},
            {"autor": "você", "texto": "Vou gerar o seu contrato."},
            {"autor": "automacao", "texto": pedido}]


async def test_mesma_correcao_sem_dado_novo_passa_para_a_equipe():
    modelo = ModeloFalso({"extrator": extrai(),
                          "etapa": resposta("Vou gerar o contrato agora. O link chega em instantes!", ferramenta="zapsign")})
    saida = await turno.processar(modelo, entrada(["já te passei tudo"], etapa="contratos", fatos=dict(CONTRATO_SEM_CPF),
                                                  historico=_historico_com_correcao()))
    assert saida.motivo != "dados_confirmados"                 # o pipeline não pede a correção de novo
    assert (saida.estado_lead, saida.motivo_estado) == ("pausado", "contrato_correcao_repetida")
    assert [m["texto"] for m in saida.mensagens] == [turno.MENSAGENS_FIXAS["contrato_com_a_equipe"]]
    assert "instantes" not in saida.mensagens[0]["texto"]
    assert saida.eventos[-1]["tipo"] == "contrato_correcao_repetida" and saida.eventos[-1]["detalhe"]["campos"] == ["cpf"]
    assert saida.contexto["catalogo"]["ferramenta_barrada"] == "correcao_repetida"


async def test_correcao_com_dado_novo_chama_o_zapsign_de_novo():
    modelo = ModeloFalso({"extrator": extrai([("cpf", CPF_VALIDO, CPF_VALIDO)]),
                          "etapa": resposta("Obrigada! Vou gerar o contrato.", ferramenta="zapsign")})
    saida = await turno.processar(modelo, entrada([f"meu cpf é {CPF_VALIDO}"], etapa="contratos",
                                                  fatos=dict(CONTRATO_SEM_CPF), historico=_historico_com_correcao()))
    assert saida.motivo == "dados_confirmados" and saida.estado_lead is None


async def test_primeira_correcao_ainda_e_pedida_pelo_sistema():
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Vou gerar o contrato.", ferramenta="zapsign")})
    saida = await turno.processar(modelo, entrada(["pode gerar"], etapa="contratos", fatos=dict(CONTRATO_SEM_CPF)))
    assert saida.motivo == "dados_confirmados" and saida.estado_lead is None


async def test_lead_sem_email_nao_entra_no_laco():
    """04 R1: "não tenho e-mail" + zapsign. Com o e-mail descartado, os dados conferem e o contrato segue."""
    fatos = {**CONTRATO_SEM_CPF, "cpf": CPF_VALIDO}
    modelo = ModeloFalso({"extrator": extrai([("email", "não tenho", "não tenho e-mail")]),
                          "etapa": resposta("Tudo bem, seguimos sem e-mail. Vou gerar o contrato.", ferramenta="zapsign")})
    saida = await turno.processar(modelo, entrada(["não tenho e-mail"], etapa="contratos", fatos=fatos))
    assert "email" not in saida.fatos_depois and saida.motivo == "dados_confirmados"
    assert cdados.validar_dados(cdados.dados_dos_fatos({**fatos, "email": "não tenho"}))[1] == []


# ---------------------------------------------------------------------------- "já te falei" e fatos já informados
def test_ja_te_falei_nao_e_objecao_no_extrator_e_no_auditor():
    assert "\"já te falei\", \"já respondi\"" in sinais.guia_do_extrator() and "NÃO é objeção" in sinais.guia_do_extrator()
    invalido = sinais.partes_do_auditor()["muitas_objecoes"][3]
    assert "'já te falei', 'já respondi'" in invalido and "NÃO é objeção" in invalido
    assert "NÃO é objeção" in auditor.PARTES["muitas_objecoes"][3]
    assert "NÃO é objeção" in extrator.GUIA_AUXILIO_ACIDENTE


async def test_bloco_de_fatos_pede_para_nao_perguntar_de_novo():
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Entendi. E o acidente, quando foi?")})
    await turno.processar(modelo, entrada(["já te falei, saí em janeiro de 2023"], fatos={"demissao_ano": 2023}))
    assert "DADOS JÁ INFORMADOS PELO LEAD (não pergunte de novo): demissao_ano=2023" in modelo.pedidos[1]["conteudo"]


# ---------------------------------------------------------------------------- boas-vindas com a primeira pergunta
async def test_boas_vindas_vem_com_a_primeira_pergunta_do_roteiro():
    prod = produto(sdr={"boas_vindas": "Olá! Sou a Júlia, do Escritório Teste."})
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Olá! Sou a Júlia. Como foi o acidente?")})
    await turno.processar(modelo, entrada(["oi, tenho direito?"], prod=prod))
    conteudo = modelo.pedidos[1]["conteudo"]
    assert "Mensagem de boas-vindas: \"Olá! Sou a Júlia, do Escritório Teste.\"\nComece com ela" in conteudo
    assert "na mesma resposta, faça a primeira pergunta do roteiro" in conteudo


async def test_boas_vindas_so_na_primeira_resposta():
    prod = produto(sdr={"boas_vindas": "Olá! Sou a Júlia."})
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Certo. E quando foi?")})
    await turno.processar(modelo, entrada(["foi uma queda"], prod=prod,
                                          historico=[{"autor": "você", "texto": "Olá! Sou a Júlia. Como foi?"}]))
    assert "boas-vindas" not in modelo.pedidos[1]["conteudo"]
