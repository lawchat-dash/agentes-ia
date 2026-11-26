"""Contrato do BPC infantil: a última pergunta da IA decide se o dado é da criança ou de quem assina."""
from app.cerebro import turno
from app.cerebro.extrator import Extracao, FatoExtraido


class _Produto:
    config = {"catalogo": {"slug": "bpc-loas-autismo-v2"}}


def _rodar(pergunta, fatos, conhecidos=None):
    entrada = turno.Entrada(escritorio="e", agente="a", etapa="contratos", novas=["x"],
                            historico=[{"autor": "ia", "texto": pergunta}], fatos=conhecidos or {})
    extracao = Extracao(fatos=[FatoExtraido(c, v, v) for c, v in fatos])
    saida = turno.Saida()
    turno._dados_da_crianca_pela_pergunta(entrada, _Produto(), extracao, saida)
    return {f.chave: f.valor for f in extracao.fatos}


def test_nome_da_crianca_vai_para_nome_menor():
    assert _rodar("Excelente! Me passa o nome completo do seu filho, do jeito que está no documento?",
                  [("nome_completo", "Pedro Henrique Souza")]) == {"nome_menor": "Pedro Henrique Souza"}


def test_filiacao_da_mae_fica_com_quem_assina():
    assert _rodar("E qual é a sua filiação, o nome dos seus pais?", [("filiacao_menor", "José Souza e Maria Souza")]) \
        == {"filiacao": "José Souza e Maria Souza"}


def test_filiacao_da_crianca():
    assert _rodar("Qual a filiação dele, o nome do pai e da mãe?", [("filiacao", "Carla Souza e João Souza")]) \
        == {"filiacao_menor": "Carla Souza e João Souza"}


def test_nome_da_crianca_ja_gravado_nao_vira_quem_assina():
    assert _rodar("Qual o seu CPF?", [("nome_completo", "Pedro Henrique Souza")],
                  {"nome_menor": "Pedro Henrique Souza"}) == {}


def test_nome_de_quem_assina_continua():
    assert _rodar("Agora, qual é o seu nome completo?", [("nome_completo", "Carla Souza")]) == {"nome_completo": "Carla Souza"}


def test_outra_familia_nao_mexe():
    class P:
        config = {"catalogo": {"slug": "auxilio-acidente-midia"}}
    entrada = turno.Entrada(escritorio="e", agente="a", etapa="contratos", novas=["x"],
                            historico=[{"autor": "ia", "texto": "Nome completo do seu filho?"}])
    extracao = Extracao(fatos=[FatoExtraido("nome_completo", "Fulano", "Fulano")])
    turno._dados_da_crianca_pela_pergunta(entrada, P(), extracao, turno.Saida())
    assert extracao.fatos[0].chave == "nome_completo"


def test_pergunta_do_responsavel_que_cita_a_crianca_e_de_quem_assina():
    assert _rodar("Carlos, qual a nacionalidade e naturalidade (cidade/UF onde nasceu) do responsável que vai assinar o contrato?",
                  [("naturalidade_menor", "Montes Claros/MG")]) == {"naturalidade": "Montes Claros/MG"}


def test_resposta_ao_pedido_de_correcao_vai_para_o_campo_pedido():
    pergunta = ("Para finalizar seu contrato, preciso confirmar uma informação: a sua naturalidade (cidade onde você "
                "nasceu). Pode me enviar novamente, por favor?")
    entrada = turno.Entrada(escritorio="e", agente="a", etapa="contratos", novas=["Montes Claros/MG."],
                            historico=[{"autor": "ia", "texto": pergunta}])
    extracao = Extracao(fatos=[])
    turno._dados_da_crianca_pela_pergunta(entrada, _Produto(), extracao, turno.Saida())
    assert {f.chave: f.valor for f in extracao.fatos} == {"naturalidade": "Montes Claros/MG"}
