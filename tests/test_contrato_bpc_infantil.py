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


# Reteste com leads reais (26/11): os pedidos da coleta não têm "?" e o motor lia uma pergunta antiga ("nome completo
# do seu filho"). O nome da mãe ia para nome_menor e o contrato pedia o nome de quem assina sem parar.
def _rodar_historico(historico, fatos, conhecidos=None, novas=("x",)):
    entrada = turno.Entrada(escritorio="e", agente="a", etapa="contratos", novas=list(novas),
                            historico=historico, fatos=conhecidos or {})
    extracao = Extracao(fatos=[FatoExtraido(c, v, v) for c, v in fatos])
    turno._dados_da_crianca_pela_pergunta(entrada, _Produto(), extracao, turno.Saida())
    return {f.chave: f.valor for f in extracao.fatos}


_ANTIGA = {"autor": "você", "texto": "Excelente! Pra começar, me passa o nome completo do(a) seu(sua) filho(a), do jeito que está no documento?"}


def test_pedido_sem_interrogacao_do_responsavel_e_o_que_vale():
    historico = [_ANTIGA, {"autor": "lead", "texto": "Pedro Teste Ribeiro"},
                 {"autor": "você", "texto": "Agora, por favor, me passa o nome completo do responsável que vai assinar o contrato."}]
    assert _rodar_historico(historico, [("nome_menor", "Joana Teste Ribeiro")], {"nome_menor": "Pedro Teste Ribeiro"}) \
        == {"nome_completo": "Joana Teste Ribeiro"}


def test_nome_da_mae_nao_vira_nome_da_crianca_por_pergunta_antiga():
    historico = [_ANTIGA, {"autor": "lead", "texto": "Pedro Teste Ribeiro"},
                 {"autor": "você", "texto": "Certo, a Joana é brasileira. Agora, por favor, me fala o estado civil dela."}]
    assert _rodar_historico(historico, [("nome_completo", "Joana Teste Ribeiro")],
                            {"nome_menor": "Pedro Teste Ribeiro"}) == {"nome_completo": "Joana Teste Ribeiro"}


def test_pais_de_quem_assina_sao_os_avos():
    historico = [{"autor": "você", "texto": "Agora, por favor, me fala o nome completo da mãe e do pai da Joana, que são os avós do Pedro."}]
    assert _rodar_historico(historico, [("filiacao_menor", "Rita Prates e Antonio Brandao")],
                            {"nome_menor": "Pedro Teste Ribeiro", "nome_completo": "Joana Teste Ribeiro"}) \
        == {"filiacao": "Rita Prates e Antonio Brandao"}


def test_pelo_nome_o_cpf_e_da_crianca():
    historico = [{"autor": "você", "texto": "Anotado. Agora, me fala o CPF do Pedro, por favor."}]
    assert _rodar_historico(historico, [("cpf", "935.113.502-04")], {"nome_menor": "Pedro Teste Ribeiro"}) \
        == {"cpf_menor": "935.113.502-04"}


def test_pelo_nome_a_naturalidade_e_de_quem_assina():
    historico = [{"autor": "você", "texto": "Agora me fala a nacionalidade e a naturalidade da Joana, por favor."}]
    assert _rodar_historico(historico, [("naturalidade_menor", "Montes Claros/MG")],
                            {"nome_menor": "Pedro Teste Ribeiro", "nome_completo": "Joana Teste Ribeiro"}) \
        == {"naturalidade": "Montes Claros/MG"}


def test_correcao_do_nome_com_nome_menor_errado_nao_e_descartada():
    pergunta = "Para finalizar seu contrato, preciso confirmar uma informação: seu nome completo. Pode me enviar novamente, por favor?"
    historico = [{"autor": "você", "texto": pergunta}]
    assert _rodar_historico(historico, [("nome_completo", "Joana Teste Ribeiro")], {"nome_menor": "Joana Teste Ribeiro"},
                            novas=["Joana Teste Ribeiro"]) == {"nome_completo": "Joana Teste Ribeiro"}


# Reteste 2 (26/11): pergunta que cita a criança mas pede o nome de um parente.
def test_nome_da_mae_do_pedro_nao_vira_nome_da_crianca():
    historico = [{"autor": "você", "texto": "Perfeito. Qual é o nome completo da mãe do Pedro?"}]
    assert _rodar_historico(historico, [("nome_completo", "Carla Exemplo Moura")], {"nome_menor": "Pedro Teste Ribeiro"}) \
        == {"nome_completo": "Carla Exemplo Moura"}


def test_avo_e_filiacao_de_quem_assina():
    historico = [{"autor": "você", "texto": "Agora me passa o nome completo do seu pai, que é o avô do Pedro."}]
    assert _rodar_historico(historico, [("filiacao_menor", "Antonio Ficticio Brandao")],
                            {"nome_menor": "Pedro Teste Ribeiro"}) == {"filiacao": "Antonio Ficticio Brandao"}


def test_responsavel_pai_ou_mae_continua_sendo_quem_assina():
    historico = [{"autor": "você", "texto": "Qual o nome completo do responsável (pai ou mãe) que vai assinar?"}]
    assert _rodar_historico(historico, [("nome_menor", "Carla Exemplo Moura")], {"nome_menor": "Pedro Teste Ribeiro"}) \
        == {"nome_completo": "Carla Exemplo Moura"}
