"""Agente próprio: definição validada, regras de passagem e um turno completo com o motor genérico."""

import pytest
from pydantic import ValidationError

from app.cerebro import turno
from app.cerebro.produto import carregar
from app.cerebro.produto_livre import Definicao, ProdutoLivre, chave_de
from app.gestao.rotas import DEFINICAO_INICIAL
from app.modelo import ModeloFalso
from tests.test_turno import fala

DEFINICAO = {
    "objetivo": "Triar casos trabalhistas e agendar consulta",
    "contexto": "uma pessoa com dúvida trabalhista",
    "campos": [
        {"chave": "situacao", "nome": "Situação de trabalho", "tipo": "escolha",
         "opcoes": ["CLT", "Autônomo", "Desempregado"], "etapa": "triagem"},
        {"chave": "salario", "nome": "Salário", "tipo": "numero", "minimo": 0, "maximo": 100000, "etapa": "triagem"},
        {"chave": "demissao", "nome": "Data da demissão", "tipo": "data", "etapa": "triagem"},
        {"chave": "aceita_consulta", "nome": "Aceita a consulta", "tipo": "sim_nao", "etapa": "proposta"},
    ],
    "intencoes": [{"chave": "quer_agendar", "descricao": "pede para marcar um horário"}],
    "etapas": [
        {"codigo": "triagem", "nome": "Triagem", "instrucao": "Pergunte com calma."},
        {"codigo": "proposta", "nome": "Proposta", "fala_valores": True},
        {"codigo": "agendado", "nome": "Agendado", "tipo": "terminal"},
        {"codigo": "fora", "nome": "Fora do perfil", "tipo": "terminal"},
    ],
    "regras": [
        {"de": "triagem", "quando": {"tipo": "campo", "campo": "situacao", "operador": "igual", "valor": "autonomo"},
         "ir_para": "fora", "motivo": "autônomo não é atendido"},
        {"de": "triagem", "quando": {"tipo": "campo", "campo": "salario", "operador": "maior", "valor": 50000},
         "ir_para": "fora", "motivo": "salário fora do perfil"},
        {"de": "triagem", "quando": {"tipo": "etapa_completa"}, "ir_para": "proposta"},
        {"de": None, "quando": {"tipo": "intencao", "intencao": "quer_agendar"}, "ir_para": "agendado"},
        {"de": "proposta", "quando": {"tipo": "campo", "campo": "aceita_consulta", "operador": "igual", "valor": "sim"},
         "ir_para": "agendado"},
    ],
    "nunca": ["prometer resultado"],
    "expressoes_proibidas": ["sem dúvida"],
}


def produto():
    return ProdutoLivre.da_definicao(DEFINICAO)


def test_definicao_inicial_do_painel_e_valida():
    assert carregar("proprio", {"definicao": DEFINICAO_INICIAL}).etapa_inicial() == "triagem"


@pytest.mark.parametrize("estrago, mensagem", [
    (lambda d: d["regras"].append({"quando": {"tipo": "etapa_completa"}, "ir_para": "nao_existe"}), "etapa que não existe"),
    (lambda d: d["regras"].append({"quando": {"tipo": "campo", "campo": "x", "operador": "igual", "valor": 1},
                                   "ir_para": "fora"}), "campo que não existe"),
    (lambda d: d["campos"].append({"chave": "situacao", "nome": "De novo"}), "mesma chave"),
    (lambda d: d["campos"].append({"chave": "pediu_humano", "nome": "Reservada"}), "chave inválida"),
    (lambda d: d["campos"].append({"chave": "x1", "nome": "Uma opção", "tipo": "escolha", "opcoes": ["só"]}), "duas opções"),
    (lambda d: d["etapas"].insert(0, {"codigo": "fim", "nome": "Fim", "tipo": "terminal"}), "primeira etapa"),
])
def test_definicao_invalida_e_recusada(estrago, mensagem):
    import copy
    dados = copy.deepcopy(DEFINICAO)
    estrago(dados)
    with pytest.raises(ValidationError) as erro:
        Definicao.model_validate(dados)
    assert mensagem in str(erro.value)


@pytest.mark.parametrize("chave, valor, esperado", [
    ("situacao", "Autônomo", "autonomo"),
    ("situacao", "estagiário", None),
    ("salario", "3.500", 3.5),
    ("salario", "3500", 3500),
    ("salario", "-1", None),
    ("demissao", "2023-4", "2023-04"),
    ("demissao", "2023", "2023"),
    ("demissao", "abril", None),
    ("aceita_consulta", "Sim", "sim"),
    ("inexistente", "x", None),
])
def test_valores(chave, valor, esperado):
    assert produto().validar_valor(chave, valor) == esperado


@pytest.mark.parametrize("etapa, fatos, intencoes, destino, faltam", [
    ("triagem", {}, {}, "triagem", ("situacao", "salario", "demissao")),
    ("triagem", {"situacao": "autonomo"}, {}, "fora", ()),
    ("triagem", {"situacao": "clt", "salario": 60000}, {}, "fora", ()),
    ("triagem", {"situacao": "clt", "salario": 3000, "demissao": "2024-01"}, {}, "proposta", ("aceita_consulta",)),
    ("triagem", {"situacao": "clt"}, {"quer_agendar": True}, "agendado", ()),     # regra de qualquer etapa
    ("proposta", {"aceita_consulta": "sim"}, {}, "agendado", ()),
    ("agendado", {}, {"quer_agendar": True}, "agendado", ()),                    # terminal não sai
])
def test_regras_de_passagem(etapa, fatos, intencoes, destino, faltam):
    passo = produto().decidir_etapa(etapa, fatos, intencoes)
    assert passo.etapa == destino and passo.faltam == faltam


def test_esquema_do_extrator_tem_os_campos_e_as_intencoes():
    esquema = produto().esquema_extrator()
    assert esquema["properties"]["fatos"]["items"]["properties"]["chave"]["enum"] == [
        "situacao", "salario", "demissao", "aceita_consulta"]
    # fora_do_tema e tentativa_de_manipular: as barreiras da leva 1 (B6), em todo produto.
    assert set(esquema["properties"]["intencoes"]["required"]) == {"pediu_humano", "pediu_para_parar", "engano", "quer_agendar",
                                                                   "fora_do_tema", "tentativa_de_manipular"}
    guia = produto().guia_do_extrator()
    assert "situacao (Situação de trabalho): clt | autonomo | desempregado" in guia and "quer_agendar" in guia


def _extrai(fatos=(), **intencoes):
    base = {n: False for n in ("pediu_humano", "pediu_para_parar", "engano", "quer_agendar")}
    return {"fatos": [{"chave": c, "valor": v, "trecho": t} for c, v, t in fatos], "sinais": [],
            "intencoes": {**base, **intencoes}}


async def test_turno_com_agente_proprio():
    modelo = ModeloFalso({
        "extrator": _extrai([("situacao", "autonomo", "sou autônomo")]),
        "etapa": fala("Entendi. Nesse caso o escritório não consegue ajudar, mas fico à disposição."),
    })
    entrada = turno.Entrada(escritorio="Escritório", agente="Ana", etapa="triagem", novas=["sou autônomo"],
                            produto=produto())
    saida = await turno.processar(modelo, entrada)
    assert saida.etapa_depois == "fora" and saida.estado_lead == "encerrado"
    assert saida.motivo_estado == "fora:autônomo não é atendido"
    assert saida.decisoes[0]["funcao"] == "regra_do_agente"
    sistema, conteudo = modelo.pedidos[1]["sistema"], modelo.pedidos[1]["conteudo"]
    assert "OBJETIVO DO AGENTE: Triar casos trabalhistas" in sistema and "- prometer resultado" in sistema
    assert "MOTIVO DO ENCERRAMENTO: autônomo não é atendido" in conteudo


async def test_trava_usa_as_expressoes_do_cliente_e_valores_so_onde_permitido():
    modelo = ModeloFalso({
        "extrator": _extrai(),
        "etapa": [fala("Sem dúvida dá certo!"), fala("A consulta custa R$ 300. Quer agendar?")],
    })
    entrada = turno.Entrada(escritorio="E", agente="Ana", etapa="proposta", novas=["e aí?"], produto=produto(),
                            honorarios="Consulta: R$ 300")
    saida = await turno.processar(modelo, entrada)
    assert saida.reprovacoes[0][0]["codigo"] == "termo_tecnico" and saida.reprovacoes[1] == []
    assert "HONORÁRIOS DO ESCRITÓRIO: Consulta: R$ 300" in modelo.pedidos[1]["conteudo"]


def test_chave_de():
    assert chave_de("Situação de Trabalho!") == "situacao_de_trabalho"
    assert chave_de("2 filhos") == "c_2_filhos"
