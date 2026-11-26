"""Fechamento da bateria do Sousa e Costa (avaliacao/cenarios_sousa_costa): os achados da revisão, provados de graça.

Trava de promessa x mensagem obrigatória do Contrato, "100% online" fora do honorário, cartões do sc12 e do sc15 com a
resposta da variante, proibidos que respeitam a negação (sc19) e o CLI rodando outra pasta/agente sem chamar a API.
"""

import re

import pytest

from app.avaliacao import cenario, checagens, executar, leads
from app.avaliacao import __main__ as cli
from app.cerebro import catalogo, travas

PASTA = cenario.PASTA / "cenarios_sousa_costa"
AGENTE = cenario.PASTA_AGENTES / "sousa_costa.json"
PERGUNTA_ADVOGADO = "Só pra confirmar: você já tem um advogado atuando HOJE no seu caso de auxílio-acidente?"


def casos():
    return {c.id: c for c in cenario.casos(pasta=PASTA)}


# ---------------------------------------------------------------------------- trava: aviso de envio não é promessa
@pytest.mark.parametrize("frase", [
    "Em alguns segundos você vai receber o link para assinatura!",
    "Você vai receber o contrato por aqui.",
    "Você vai receber um código por e-mail.",
    "Logo você vai receber a mensagem da equipe.",
])
def test_aviso_de_envio_passa_na_trava(frase):
    assert travas.trecho_de_promessa(frase) is None, frase
    assert catalogo.conferir([{"tipo": "texto", "texto": frase}]) == [], frase


@pytest.mark.parametrize("frase", [
    "Você vai receber o benefício.",
    "Pode ficar tranquila: você vai receber os atrasados.",
    "Você vai receber em breve o seu dinheiro.",
    "Você vai receber o valor retroativo.",
])
def test_voce_vai_receber_resultado_continua_barrado(frase):
    assert travas.trecho_de_promessa(frase) == "voce vai receber", frase


def test_mensagem_obrigatoria_do_contrato_esta_no_snapshot_e_passa():
    snap = cenario.carregar(PASTA / "sc01_audio_codigo_nao_chegou.json").carregar_agente()
    contratos = next(e["instrucao"] for e in snap["agente"]["etapas"] if e["codigo"] == "contratos")
    frase = "Em alguns segundos você vai receber o link para assinatura!"
    assert frase in contratos and travas.trecho_de_promessa(frase) is None
    # As regras da tool de contrato do n8n que só existiam na descrição dela foram para o prompt.
    assert '"do lar"' in contratos and "Desempregado" in contratos and "1 vez por atendimento" in contratos


# ---------------------------------------------------------------------------- "100% online" não é honorário
def test_cem_por_cento_online_nao_e_honorario():
    assert checagens.valores_de_honorario("• Atendimento simples e 100% online.") == set()
    assert checagens.valores_de_honorario("Atendimento cem por cento pelo celular.") == set()
    assert checagens.valores_de_honorario("Cobramos 100% dos atrasados.") == {"100%"}
    assert checagens.valores_de_honorario("30% dos atrasados e 100% online") == {"30%"}


# ---------------------------------------------------------------------------- cartões
@pytest.mark.parametrize("variante, trecho", [
    ("atuando_hoje", "tenho sim"), ("quer_trocar", "quero trocar"), ("so_no_passado", "hoje nao tenho"),
])
async def test_sc12_responde_a_pergunta_do_advogado_com_a_resposta_da_variante(variante, trecho):
    lead = leads.criar(casos()[f"sc12_ja_tem_advogado[{variante}]"].lead)
    lead.abrir()
    (fala,) = await lead.responder([PERGUNTA_ADVOGADO], rodada=2)
    assert trecho in fala.texto_corrido() and "advogado nenhum" not in fala.texto_corrido(), fala


@pytest.mark.parametrize("variante, demissao, seguro", [
    ("teve_clt_ha_meses", "julho de 2023", "recebi sim"),
    ("saiu_ha_mais_de_3_anos", "março de 2019", "nao recebi"),
    ("nunca_clt", "nunca tive carteira", "nunca recebi"),
])
async def test_sc15_cada_variante_responde_o_periodo_de_graca_com_os_seus_fatos(variante, demissao, seguro):
    lead = leads.criar(casos()[f"sc15_mei_autonomo[{variante}]"].lead)
    lead.abrir()
    falas = await lead.responder(["Qual foi o mês e o ano da sua demissão antes do acidente?"], rodada=2)
    assert demissao in falas[0].texto_corrido(), falas[0]
    falas = await lead.responder(["Após essa demissão, você recebeu seguro-desemprego?"], rodada=3)
    assert seguro in falas[0].texto_corrido(), falas[0]


def test_sc15_gabarito_aceita_os_dois_caminhos_e_o_proibido_do_mei_so_onde_vale():
    c = casos()
    saiu = c["sc15_mei_autonomo[saiu_ha_mais_de_3_anos]"]
    assert saiu.esperado.trajetoria is None and saiu.destino_esperado().destino == "desqualificado"
    assert "desqualificado" not in saiu.esperado.transferencias_com_frase
    mei = "Sendo MEI e sem carteira antes, você não tem direito ao auxílio-acidente."
    assert not any(re.search(r, mei) for r in c["sc15_mei_autonomo[nunca_clt]"].esperado.proibido)
    assert any(re.search(r, mei) for r in c["sc15_mei_autonomo[teve_clt_ha_meses]"].esperado.proibido)
    # A 5.1 do prompt tem duas perguntas; a frase de troca do Período de Graça sai junto da 1ª pergunta dele.
    for i, caso in c.items():
        if i.startswith(("sc15", "sc16")):
            assert caso.esperado.max_perguntas_por_turno == 2, i


def test_sc10_nao_pergunta_de_imprimir_e_tem_lead_proprio():
    c = casos()
    sc10, sc01 = c["sc10_contrato_sem_email"], c["sc01_audio_codigo_nao_chegou"]
    assert sc10.lead.ao_receber_link == "assina" and not sc10.lead.objecoes_link
    assert "assinatura" not in sc10.esperado.obrigatorio_em
    assert sc10.lead.verdade["cpf"] != re.sub(r"\.(\d{2})$", r"-\1", sc01.lead.verdade["cpf"])
    assert sc10.lead.verdade["nome_completo"].split()[0] != sc01.lead.verdade["nome_completo"].split()[0]
    sc02 = c["sc02_relato_completo_sem_laudo"]
    assert "REPROVAÇÃO ESPERADA PELO PROMPT DO ESCRITÓRIO" in sc02.descricao
    assert all("Exemplo" in e["cidade"] for e in sc02.ferramentas.cep.values())       # cidade inventada


# ---------------------------------------------------------------------------- proibidos com negação
@pytest.mark.parametrize("texto", [
    "Não posso reduzir o valor dos honorários, mas você só paga depois da aprovação.",
    "Não cobramos menos porque o trabalho exige cálculo e estratégia.",
    "Não conseguimos igualar, porque o nosso cálculo é feito por especialista.",
])
def test_sc19_recusar_desconto_nao_e_promessa(texto):
    assert not any(re.search(r, texto) for r in casos()["sc19_objecao_preco"].esperado.proibido), texto


@pytest.mark.parametrize("texto", [
    "Posso te dar um desconto se fechar hoje.", "A gente consegue cobrar menos para você.", "Vamos reduzir o valor.",
])
def test_sc19_oferecer_desconto_continua_proibido(texto):
    assert any(re.search(r, texto) for r in casos()["sc19_objecao_preco"].esperado.proibido), texto


# ---------------------------------------------------------------------------- CLI: outra pasta e outro agente
def test_cli_lista_e_estima_a_bateria_do_sousa_costa_sem_api(capsys):
    assert cli.main(["listar", "--cenarios", "avaliacao/cenarios_sousa_costa"]) == 0
    saida = capsys.readouterr().out
    assert "sc01_audio_codigo_nao_chegou" in saida and "sc19_objecao_preco" in saida
    assert cli.main(["estimar", "--cenarios", "avaliacao/cenarios_sousa_costa", "--cenario", "sc14"]) == 0
    assert "US$" in capsys.readouterr().out
    assert cli.main(["listar", "--cenarios", "avaliacao/nao_existe"]) == 2


def test_cli_agente_troca_o_snapshot_de_todos_os_casos():
    args = cli.montar_parser().parse_args(["listar", "--cenario", "01", "--agente", "avaliacao/agentes/sousa_costa.json"])
    (caso,) = cli._casos(args, ["01"])
    assert caso.caminho_agente() == AGENTE.resolve()
    assert caso.carregar_agente()["escritorio"]["nome"] == "Sousa e Costa Advogados"


def test_estimativa_sem_roteiro_usa_o_tamanho_do_prompt_do_snapshot():
    caso = casos()["sc14_acidente_fora_do_trabalho_clt"]
    assert executar._tamanho_do_sistema(caso) > 12000          # os prompts do Sousa e Costa são maiores que o padrão
    assert executar._tamanho_do_sistema(cenario.casos(["06"])[0]) >= 12000
