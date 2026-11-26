"""Cenário 03 (catálogo de referência): a pergunta de contribuição não é a pergunta da demissão.

Rodada real de 2026-11-25 (avaliacao/resultados/2026-11-25_0146_agente-referencia): o assunto da demissão tinha a
alternativa "pagou o inss", que também casava com "você pagou o INSS por conta própria, como pelo carnê ou como MEI?".
O LeadCartao escolhe pela posição no texto, e "pagou o INSS" vem antes de "por conta própria": a lead respondia a
demissão como repetição e a checagem pergunta_repetida acusava a IA de uma pergunta nova e legítima (com_seguro t8;
sem_seguro t5 e t6, duas vezes porque a variante soma os seus assuntos aos da base).

Aqui a conversa é repetida offline com os textos da transcrição. Nada chama a API.
"""

import re

import pytest

from app.avaliacao import cenario, leads

# Mensagens da IA na transcrição, turno a turno (o " / " da transcrição é a quebra de linha da mesma mensagem).
COM_SEGURO = [
    "Olá! Aqui é a Júlia, do Escritório Exemplo Advocacia. 😊 Para começar, você pode me contar como foi o seu acidente "
    "e quando aconteceu, mesmo que seja um mês e ano aproximados?",
    "Que situação difícil, ainda bem que você está buscando ajuda! Na época do acidente, você trabalhava de carteira "
    "assinada, era autônoma, estava desempregada ou trabalhava na roça?",
    "Entendi, obrigado por compartilhar. Você ficou com alguma sequela ou limitação depois do acidente?",
    "Sinto muito por essa sequela, deve ser difícil mesmo. Você já está aposentada atualmente?",
    "Você já tem algum advogado cuidando desse seu caso?",
    "Pelo que você me contou, vale a pena a nossa equipe olhar o seu caso com carinho. Vou transferir você para a "
    "equipe especializada agora.",
    "Você mencionou que foi demitida em janeiro de 2023. Você recebeu seguro-desemprego quando saiu desse emprego?",
]
COM_SEGURO_T8 = ("Obrigado por confirmar que recebeu todas as parcelas do seguro-desemprego. Depois disso, você pagou "
                 "o INSS por conta própria, como pelo carnê ou como MEI?")

SEM_SEGURO = [
    "Olá! Aqui é a Júlia, do Escritório Exemplo Advocacia. 😊 Me conta, como foi o seu acidente e quando ele aconteceu "
    "(mês e ano, pode ser aproximado)?",
    "Nossa, que situação difícil! Espero que você esteja se recuperando bem. Na época do acidente, você trabalhava de "
    "carteira assinada, era autônoma, estava desempregada ou trabalhava na roça?",
    "Entendi, você estava desempregada na época do acidente. Vou te fazer mais algumas perguntas sobre o seu trabalho."
    "\nDepois do acidente, você ficou com alguma sequela ou limitação por causa dele?",
    "Obrigada por compartilhar isso. Para ajudar nossa equipe a avaliar seu caso, você recebeu seguro-desemprego quando "
    "saiu do emprego em janeiro de 2023?",
]
SEM_SEGURO_T5 = ("Você pagou o INSS por conta própria depois que saiu do emprego, por exemplo pelo carnê ou como MEI?")
SEM_SEGURO_T6 = ("Desculpe, você já tinha me contado sobre a demissão em janeiro de 2023. Então, para continuar, você "
                 "pagou o INSS por conta própria depois disso, por exemplo pelo carnê ou como MEI?")


def caso(variante):
    return next(c for c in cenario.casos(["03"]) if c.id == f"03_periodo_de_graca[{variante}]")


def indice_de(c, fato):
    return next(i for i, a in enumerate(c.lead.assuntos) if fato in a.fatos)


async def conversar(c, mensagens):
    lead = leads.LeadCartao(c.lead)
    lead.abrir()
    respostas = [(await lead.responder([m]))[0] for m in mensagens]
    return lead, respostas


async def test_com_seguro_t8_a_pergunta_de_contribuicao_nao_e_repeticao():
    c = caso("com_seguro")
    lead, respostas = await conversar(c, COM_SEGURO)
    assert [r.texto for r in respostas] == [
        "fui atropelada de bicicleta em maio de 2024", "não, eu tinha sido demitida em janeiro de 2023",
        "fiquei mancando, a perna direita não firma", "não sou aposentada", "não", "não sei te dizer",
        "recebi sim, as parcelas todas"]
    t8 = (await lead.responder([COM_SEGURO_T8]))[0]
    assert t8.origem == f"assunto:{indice_de(c, 'contribuiu_por_conta_propria')}"
    assert t8.texto == "não paguei, estava procurando emprego"


async def test_sem_seguro_t5_e_t6_a_pergunta_de_contribuicao_nao_e_repeticao():
    c = caso("sem_seguro")
    lead, respostas = await conversar(c, SEM_SEGURO)
    assert [r.texto for r in respostas] == [
        "fui atropelada de bicicleta em maio de 2024", "não, tava parada, a firma me mandou embora em janeiro de 2023",
        "fiquei mancando, a perna direita não firma", "não recebi"]
    contribuiu = f"assunto:{indice_de(c, 'contribuiu_por_conta_propria')}"
    t5 = (await lead.responder([SEM_SEGURO_T5]))[0]
    assert t5.origem == contribuiu and t5.texto == "não paguei, estava procurando emprego"
    # Se a IA pergunta a contribuição de novo, é repetição da contribuição, nunca da demissão.
    t6 = (await lead.responder([SEM_SEGURO_T6]))[0]
    assert t6.origem == contribuiu.replace("assunto:", "repetida:")


@pytest.mark.parametrize("variante", ["com_seguro", "sem_seguro", "extrator_sozinho"])
@pytest.mark.parametrize("pergunta", [COM_SEGURO_T8, SEM_SEGURO_T5, SEM_SEGURO_T6])
def test_assunto_da_demissao_nao_casa_com_pergunta_de_contribuicao(variante, pergunta):
    c = caso(variante)
    demissao = [a for a in c.lead.assuntos if set(a.fatos) == {"demissao_mes", "demissao_ano"}]
    assert demissao
    for assunto in demissao:
        assert not any(re.search(q, pergunta) for q in assunto.quando), (c.id, assunto.quando)


@pytest.mark.parametrize("variante", ["com_seguro", "sem_seguro", "extrator_sozinho"])
@pytest.mark.parametrize("pergunta", [
    "Quando você saiu do seu último emprego?",
    "Você pode me dizer quando saiu do último emprego com carteira assinada ou quando pagou o INSS pela última vez?",
    "Quando foi a última vez que você pagou o INSS?",
    "Quando foi a última vez que contribuiu para o INSS?",
])
def test_assunto_da_demissao_continua_casando_com_a_pergunta_da_data(variante, pergunta):
    """A correção não afrouxa: a pergunta da data da demissão (ou da última contribuição) segue sendo da demissão."""
    c = caso(variante)
    demissao = [a for a in c.lead.assuntos if set(a.fatos) == {"demissao_mes", "demissao_ano"}]
    for assunto in demissao:
        assert any(re.search(q, pergunta) for q in assunto.quando), (c.id, pergunta)


async def test_data_pedida_de_novo_depois_da_carteira_continua_sendo_repeticao():
    for variante in ("com_seguro", "sem_seguro"):
        c = caso(variante)
        lead = leads.LeadCartao(c.lead)
        lead.abrir()
        await lead.responder(["Na época, você trabalhava de carteira assinada?"])
        de_novo = (await lead.responder(["Quando foi a última vez que você pagou o INSS?"]))[0]
        assert de_novo.origem.startswith("repetida:"), c.id
        assert set(c.lead.assuntos[int(de_novo.origem.split(":")[1])].fatos) == {"demissao_mes", "demissao_ano"}
