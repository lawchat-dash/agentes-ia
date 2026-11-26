"""Lacunas achadas na auditoria dos tickets de suporte: sinais novos (cat. 18), desqualificar_modo e permitir_volta_sdr
(cat. 19), desqualificação esquecida (cat. 20), contrato sem confirmação (cat. 23), texto de sistema vazado (cat. 31) e
capitalização dos dados do contrato (cat. 26). Tudo com o ModeloFalso: nenhuma chamada à IA de verdade."""

from datetime import datetime

import pytest

from app import automacoes, notificacoes
from app.cerebro import auditor, catalogo, formatador, sinais, turno
from app.contrato import dados as cdados
from app.modelo import ModeloFalso
from tests.test_catalogo_weaver import entrada, extrai, produto, resposta
from tests.test_correcoes_rodada_real import CONTRATO_SEM_CPF, CPF_VALIDO

NOVOS = ("atendimento_presencial", "ligacao_telefonica", "parceria_comercial", "deficiencia_auditiva")
AUDITOR_OK = {"valido": True, "motivo": "pediu", "mensagem": "Combinado! A equipe vai falar com você por aqui."}
CONVERSA = [{"autor": "lead", "texto": "oi"}, {"autor": "você", "texto": "Oi! Me conta o seu caso?"}]
FATOS_CONTRATO = {**CONTRATO_SEM_CPF, "cpf": CPF_VALIDO}


# ----------------------------------------------------------------------------- cat. 18: sinais novos
@pytest.mark.parametrize("sinal", NOVOS)
def test_sinal_novo_tem_extrator_auditor_nome_e_evento(sinal):
    assert sinal in sinais.SINAIS and sinal in sinais.DO_EXTRATOR
    assert sinal in auditor.PARTES
    assert sinal in automacoes.NOMES_SINAIS
    assert f"sinal:{sinal}" in notificacoes.NOMES_DE_EVENTO
    assert f"- {sinal}" in sinais.guia_do_extrator("BPC/LOAS")
    assert sinal in sinais.do_papel(sinais.SINAIS, {"notificacao": True, "acoes": []})        # vale em todo papel
    assert "Helena" not in auditor.sistema_do_auditor(sinal, "X", sinais.partes_do_auditor("BPC"))


def test_presencial_deixa_de_estar_na_lista_do_que_nao_marca():
    guia = sinais.guia_do_extrator()
    assert "atendimento presencial, preço" not in guia
    assert "NÃO é: só perguntar onde fica o escritório" in guia


@pytest.mark.parametrize("sinal", ("atendimento_presencial", "ligacao_telefonica", "parceria_comercial"))
async def test_sinal_novo_confirmado_pausa_e_avisa(sinal):
    modelo = ModeloFalso({"extrator": extrai(sinais_=[sinal]), "auditor": AUDITOR_OK, "etapa": resposta()})
    saida = await turno.processar(modelo, entrada(["posso ir aí no escritório?"], modelo_auditor="falso",
                                                  historico=list(CONVERSA)))
    assert (saida.estado_lead, saida.motivo_estado) == ("pausado", f"sinal:{sinal}")
    assert saida.sinais == [sinal] and f"sinal_{sinal}" in [e["tipo"] for e in saida.eventos]
    assert [m["texto"] for m in saida.mensagens] == [AUDITOR_OK["mensagem"]]
    assert "etapa" not in [p["papel"] for p in modelo.pedidos]                             # o agente não respondeu
    assert f"sinal:{sinal}" in automacoes.gatilhos_do_turno(
        primeira_resposta=False, etapa_antes="sdr", etapa_depois="sdr", motivo_estado=saida.motivo_estado,
        situacao="respondido", sinais=saida.sinais)


async def test_deficiencia_auditiva_avisa_sem_pausar_e_tira_o_audio():
    audio = "https://x.com/midia/11111111-1111-1111-1111-111111111111/audio/explica.ogg"
    modelo = ModeloFalso({"extrator": extrai(sinais_=["deficiencia_auditiva"]), "auditor": AUDITOR_OK,
                          "etapa": resposta(f"Vou te explicar. {audio}")})
    dados = entrada(["sou surda, não escuto áudio"], modelo_auditor="falso", historico=list(CONVERSA))
    dados.instrucoes = {"sdr": f"Mande o áudio {audio}"}
    saida = await turno.processar(modelo, dados)
    assert saida.estado_lead is None and saida.sinais == ["deficiencia_auditiva"]
    evento = next(e for e in saida.eventos if e["tipo"] == "sinal_deficiencia_auditiva")
    assert evento["detalhe"]["pausa"] is False
    assert saida.fatos_depois[turno.MARCA_SO_TEXTO] is True
    assert "deficiência auditiva" in modelo.pedidos[-1]["conteudo"]
    assert all(m["tipo"] == "texto" for m in saida.mensagens)
    assert "audio_para_lead_surdo" in [e["tipo"] for e in saida.eventos]


# ----------------------------------------------------------------------------- cat. 19: desqualificar_modo e volta ao SDR
def _prod(**config):
    destinos = {"sdr": ["closer", "desqualificado"], "closer": ["contratos", "desqualificado"],
                "contratos": ["desqualificado"], "assinatura": [], "desqualificado": ["sdr"]}
    return catalogo.carregar({"catalogo": {"papeis": {p: {"destinos": d} for p, d in destinos.items()}},
                              "funcoes": {"contrato_zapsign": True}, **config})


def test_opcoes_padrao_e_lidas_do_topo_ou_do_catalogo():
    assert turno.desqualificar_modo({}) == "desqualificar" and turno.permitir_volta_sdr({}) is True
    assert turno.desqualificar_modo({"desqualificar_modo": "analise_manual"}) == "analise_manual"
    assert turno.desqualificar_modo({"catalogo": {"desqualificar_modo": "analise_manual"}}) == "analise_manual"
    assert turno.desqualificar_modo({"desqualificar_modo": "qualquer"}) == "desqualificar"
    assert turno.permitir_volta_sdr({"permitir_volta_sdr": False}) is False
    assert turno.permitir_volta_sdr({"catalogo": {"permitir_volta_sdr": False}}) is False


async def test_desqualificar_em_analise_manual_nao_nega_e_passa_para_a_equipe():
    modelo = ModeloFalso({"extrator": extrai([("aposentado", "sim", "já sou aposentado")]),
                          "etapa": resposta("Infelizmente você não tem direito.", transferir="desqualificado")})
    saida = await turno.processar(modelo, entrada(["já sou aposentado"], prod=_prod(desqualificar_modo="analise_manual"),
                                                  historico=list(CONVERSA)))
    assert saida.etapa_depois == "sdr"
    assert (saida.estado_lead, saida.motivo_estado) == ("pausado", "analise_manual:desqualificacao")
    textos = " ".join(m["texto"] for m in saida.mensagens)
    assert "não tem direito" not in textos and textos == turno.MENSAGENS_FIXAS["analise_manual"]
    evento = next(e for e in saida.eventos if e["tipo"] == "analise_manual")
    assert evento["detalhe"]["causa"] == "desqualificacao"
    assert "etapa:analise_manual" in automacoes.gatilhos_do_turno(
        primeira_resposta=False, etapa_antes="sdr", etapa_depois="sdr", motivo_estado=saida.motivo_estado,
        situacao="respondido", sinais=[])


async def test_modo_padrao_continua_desqualificando():
    modelo = ModeloFalso({"extrator": extrai([("aposentado", "sim", "já sou aposentado")]),
                          "etapa": resposta("Entendi.", transferir="desqualificado")})
    saida = await turno.processar(modelo, entrada(["já sou aposentado"], prod=_prod(), historico=list(CONVERSA)))
    assert saida.etapa_depois == "desqualificado" and saida.estado_lead is None


async def test_sem_volta_ao_sdr_o_desqualificado_fica():
    for config, esperado in (({}, "sdr"), ({"permitir_volta_sdr": False}, "desqualificado")):
        modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Vamos rever.", transferir="sdr")})
        saida = await turno.processar(modelo, entrada(["na verdade não sou aposentado"], etapa="desqualificado",
                                                      prod=_prod(**config), historico=list(CONVERSA)))
        assert saida.etapa_depois == esperado, config
        enum = modelo.pedidos[1]["esquema"]["properties"]["transferir_para"]["enum"]
        assert ("sdr" in enum) == (esperado == "sdr")


# ----------------------------------------------------------------------------- cat. 20: desqualificação esquecida
async def test_desqualificacao_esquecida_corrige_uma_vez_e_a_ia_obedece():
    modelo = ModeloFalso({"extrator": extrai([("aposentado", "sim", "sou aposentado")]),
                          "etapa": [resposta("Que bom! Me conta do acidente?"),
                                    resposta("Entendi.", transferir="desqualificado")]})
    saida = await turno.processar(modelo, entrada(["sou aposentado"], prod=_prod(corrigir_desqualificacao_esquecida=True), historico=list(CONVERSA)))
    assert "aposentado = sim" in modelo.pedidos[-1]["conteudo"] and "CORRIJA" in modelo.pedidos[-1]["conteudo"]
    assert saida.etapa_depois == "desqualificado" and saida.estado_lead is None


async def test_desqualificacao_esquecida_com_insistencia_segue_e_avisa_uma_vez():
    modelo = ModeloFalso({"extrator": extrai([("aposentado", "sim", "sou aposentado")]),
                          "etapa": [resposta("Me conta do acidente?"), resposta("E o acidente, como foi?")]})
    saida = await turno.processar(modelo, entrada(["sou aposentado"], prod=_prod(corrigir_desqualificacao_esquecida=True), historico=list(CONVERSA)))
    assert saida.estado_lead is None and saida.etapa_depois == "sdr"                   # não trava o atendimento
    assert [m["texto"] for m in saida.mensagens] == ["E o acidente, como foi?"]
    assert "desqualificacao_esquecida" in [e["tipo"] for e in saida.eventos]
    assert saida.fatos_depois[turno.MARCA_DESQ_ESQUECIDA] == "aposentado"
    # Já avisado por esse fato: o turno seguinte não manda a correção de novo.
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Certo, seguimos.")})
    fatos = {"aposentado": "sim", turno.MARCA_DESQ_ESQUECIDA: "aposentado"}
    saida = await turno.processar(modelo, entrada(["ok"], prod=_prod(corrigir_desqualificacao_esquecida=True), fatos=fatos, historico=list(CONVERSA)))
    assert saida.estado_lead is None and len([p for p in modelo.pedidos if p["papel"] == "etapa"]) == 1
    # Padrão (desligada no agente): a correção não é mandada.
    modelo = ModeloFalso({"extrator": extrai([("aposentado", "sim", "sou aposentado")]), "etapa": resposta("Certo.")})
    saida = await turno.processar(modelo, entrada(["sou aposentado"], prod=_prod(),
                                                  historico=list(CONVERSA)))
    assert len([p for p in modelo.pedidos if p["papel"] == "etapa"]) == 1


# ----------------------------------------------------------------------------- cat. 23: contrato sem confirmação
def _resumo():
    return [{"autor": "lead", "texto": "é isso"},
            {"autor": "você", "texto": "Confira: Patrícia Souza Lima, CPF 529.982.247-25, Rua das Flores, 12, Centro, "
                                       "Campinas/SP. Está tudo certo?"}]


async def test_zapsign_sem_confirmacao_pede_o_resumo_uma_vez():
    resumo = "Confira: Patrícia Souza Lima, CPF 529.982.247-25, Rua das Flores, 12. Está tudo certo?"
    modelo = ModeloFalso({"extrator": extrai(), "etapa": [resposta("Vou gerar o contrato!", ferramenta="zapsign"),
                                                          resposta(resumo)]})
    saida = await turno.processar(modelo, entrada(["meu cep é 13010-100"], etapa="contratos", fatos=dict(FATOS_CONTRATO),
                                                  historico=list(CONVERSA)))
    assert "não confirmou os dados" in modelo.pedidos[-1]["conteudo"]                     # a CORRIJA foi mandada
    assert saida.motivo != "dados_confirmados" and [m["texto"] for m in saida.mensagens] == [resumo]


async def test_zapsign_insistente_segue_como_antes_e_fica_o_evento():
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Vou gerar o contrato!", ferramenta="zapsign")})
    saida = await turno.processar(modelo, entrada(["meu cep é 13010-100"], etapa="contratos", fatos=dict(FATOS_CONTRATO),
                                                  historico=list(CONVERSA)))
    assert saida.motivo == "dados_confirmados" and saida.estado_lead is None              # não trava o atendimento
    assert "contrato_sem_confirmacao" in [e["tipo"] for e in saida.eventos]
    prod = produto()
    prod.config["confirmar_dados_contrato"] = False                                      # desligada: nem a correção
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Vou gerar o contrato!", ferramenta="zapsign")})
    saida = await turno.processar(modelo, entrada(["ok"], etapa="contratos", prod=prod, fatos=dict(FATOS_CONTRATO),
                                                  historico=list(CONVERSA)))
    assert saida.motivo == "dados_confirmados" and len(modelo.pedidos) == 2


async def test_sim_ao_resumo_ou_intencao_libera_o_contrato():
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Vou gerar o contrato!", ferramenta="zapsign")})
    saida = await turno.processar(modelo, entrada(["Sim, tá tudo certo"], etapa="contratos", fatos=dict(FATOS_CONTRATO),
                                                  historico=_resumo()))
    assert saida.motivo == "dados_confirmados"
    assert saida.fatos_depois[turno.MARCA_DADOS_CONFIRMADOS]
    modelo = ModeloFalso({"extrator": extrai(confirmou_dados=True),
                          "etapa": resposta("Vou gerar o contrato!", ferramenta="zapsign")})
    saida = await turno.processar(modelo, entrada(["pode gerar"], etapa="contratos", fatos=dict(FATOS_CONTRATO),
                                                  historico=list(CONVERSA)))
    assert saida.motivo == "dados_confirmados"


def test_sim_sem_resumo_ou_com_correcao_nao_confirma():
    casos = ((["sim"], list(CONVERSA), False), (["não, o número está errado"], _resumo(), False),
             (["Sim, tá tudo certo"], _resumo(), True), (["isso mesmo, pode gerar"], _resumo(), True))
    for novas, historico, esperado in casos:
        dados = entrada(novas, etapa="contratos", fatos=dict(FATOS_CONTRATO), historico=historico)
        assert turno._lead_confirmou_dados(dados, turno.Saida(fatos_depois=dict(FATOS_CONTRATO))) is esperado, novas


async def test_dados_ja_confirmados_valem_enquanto_nao_mudam():
    marca = cdados.hash_dados(cdados.validar_dados(cdados.dados_dos_fatos(FATOS_CONTRATO))[0])
    fatos = {**FATOS_CONTRATO, turno.MARCA_DADOS_CONFIRMADOS: marca}
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Vou gerar!", ferramenta="zapsign")})
    saida = await turno.processar(modelo, entrada(["e aí?"], etapa="contratos", fatos=fatos, historico=list(CONVERSA)))
    assert saida.motivo == "dados_confirmados"
    dados = entrada(["moro em Sumaré"], etapa="contratos", fatos=fatos, historico=list(CONVERSA))
    # Dado mudou: o resumo novo precisa do "sim".
    assert not turno._lead_confirmou_dados(dados, turno.Saida(fatos_depois={**fatos, "cidade": "Sumaré"}))


# ----------------------------------------------------------------------------- cat. 31: texto de sistema vazado
@pytest.mark.parametrize("bruto, esperado", [
    ('Oi! functions.zapsign({"cpf": "1"}) Tudo certo?', "Oi! Tudo certo?"),
    ("Pronto {} já anotei.", "Pronto já anotei."),
    ('{"transferir_para": "", "ferramenta": ""}', ""),
    ("to=functions.buscar_cep", ""),
    ("Use {{NOME}} aqui", "Use {{NOME}} aqui"),                      # variável: a trava do catálogo cuida
    ("Valor (R$ 100,00).", "Valor (R$ 100,00)."),
])
def test_sobras_de_sistema_saem_do_texto(bruto, esperado):
    assert formatador.limpar(bruto) == esperado


def test_balao_sem_letra_nao_vai():
    saida = formatador.formatar([{"tipo": "texto", "texto": '""'}, {"tipo": "texto", "texto": "{}"},
                                 {"tipo": "texto", "texto": "Oi! 🙏"}, {"tipo": "texto", "texto": "..."}])
    assert [m["texto"] for m in saida] == ["Oi! 🙏"]
    partes = catalogo.separar_midias(['""', "Tudo bem?", '{"ferramenta": "zapsign"}'])
    assert partes == [{"tipo": "texto", "texto": "Tudo bem?"}]
    assert catalogo.conferir(catalogo.separar_midias(['""'])) == ["A resposta veio vazia. Escreva a mensagem para o lead."]


# ----------------------------------------------------------------------------- cat. 26: capitalização do contrato
def test_validar_dados_capitaliza_nome_endereco_bairro_e_cidade():
    brutos = {"nome": "MARIA DAS DORES DA SILVA", "cpf": CPF_VALIDO, "endereco": "rua xv de novembro",
              "numero": "10a", "bairro": "jardim são joão e santa luzia", "cidade": "são josé dos campos",
              "estado": "sp", "cep": "12345678", "complemento": "apto 2"}
    dados, erros = cdados.validar_dados(brutos)
    assert erros == []
    assert dados["nome"] == "Maria das Dores da Silva"
    assert dados["endereco"] == "Rua Xv de Novembro" or dados["endereco"] == "Rua XV de Novembro"
    assert dados["bairro"] == "Jardim São João e Santa Luzia"
    assert dados["cidade"] == "São José dos Campos"
    assert dados["numero"] == "10a" and dados["complemento"] == "Apto 2"
    assert cdados.capitalizar("RUA XV DE NOVEMBRO") == "Rua XV de Novembro"
    assert cdados.capitalizar("ana d'ávila pereira-lima") == "Ana D'Ávila Pereira-Lima"
    assert cdados.capitalizar("de souza") == "De Souza"                                  # partícula no começo


def test_qualificacao_minuscula_onde_o_modelo_pede():
    dados, _ = cdados.validar_dados({**cdados.dados_dos_fatos(FATOS_CONTRATO), "estado_civil": "solteira",
                                     "profissao": "Costureira"})
    agora = datetime(2026, 11, 26, 10, 0)
    padrao = dict(cdados.montar_variaveis(dados, cdados.MAPEAMENTO_PADRAO, agora))
    assert padrao["Estado Civil"] == "Solteira" and padrao["Profissão"] == "Costureira"
    proprio = dict(cdados.montar_variaveis(dados, [
        {"variavel": "estado civil", "campo": "estado_civil", "formato": "minusculas"},
        {"variavel": "Profissão", "campo": "profissao", "formato": "minusculas"},
        {"variavel": "Nacionalidade", "campo": "@fixo", "valor": "Brasileira", "formato": "minusculas"},
        {"variavel": "NOME", "campo": "nome", "formato": "maiusculas"}], agora))
    assert proprio == {"estado civil": "solteira", "Profissão": "costureira", "Nacionalidade": "brasileira",
                       "NOME": "PATRÍCIA SOUZA LIMA"}
