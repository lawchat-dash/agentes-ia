"""Regressões do diagnóstico da rodada real de 2026-11-25 (docs/DIAGNOSTICO_RODADA_REAL_2026-11-25.md, seção 3).

Cada teste prende um falso alarme ou um furo do sistema de teste que a rodada real mostrou: regex de aceite e de
confirmação, lead simulado (padrão, repetição, gatilho), auditor ligado, vazamento, promessa, dado fora de hora,
aceite antes de contratos, oráculo, falhas em cascata, texto barrado pela trava e o roteiro do 06.
Tudo com o modelo roteirizado: nada chama a API.
"""

import json
import re

import pytest

from app.avaliacao import cenario, checagens, custo, executar, falso, leads, oraculo, relatorio, simulador
from app.avaliacao.cenario import Fala
from app.avaliacao.falso import CLOSER, HONORARIOS, PARA_CONTRATOS, passo
from app.avaliacao.simulador import Rodada, TurnoSimulado


def caso(prefixo):
    return cenario.casos([prefixo])[0]


def assunto(c, trecho):
    """O assunto do cartão cujo 'quando' contém o trecho."""
    return next(a for a in c.lead.assuntos if any(trecho in q for q in a.quando))


async def conversar(prefixo, ajustar=None, c=None, sem_portao=False):
    c = c or caso(prefixo)
    roteiro = falso.roteiro_de(c.id)
    if ajustar:
        ajustar(roteiro)
    snap = c.carregar_agente()
    if sem_portao:                                     # leva 1 (B4): para medir a checagem, não o portão do motor
        snap["agente"]["config"].setdefault("catalogo", {})["portao_de_fatos"] = False
    return await simulador.rodar_conversa(c, falso.ModeloRoteirizado(snap, roteiro), snapshot=snap)


# ---------------------------------------------------------------------------- 1. regex de aceite e de confirmação
@pytest.mark.parametrize("prefixo", ["01", "04", "05"])
def test_aceite_e_confirmacao_reconhecem_o_jeito_real_de_perguntar(prefixo):
    c = caso(prefixo)
    aceite = next(a for a in c.lead.assuntos if a.aceite)
    confirma = assunto(c, "confer")
    for frase in ("Quer que a gente siga com o seu caso?", "Você gostaria de seguir com o pedido?",
                  "Podemos dar entrada no seu pedido?", "Vamos prosseguir?", "Topa seguir?"):
        assert any(re.search(q, frase) for q in aceite.quando), frase
    for frase in ("Está tudo correto?", "Ficou tudo ok?", "Está tudo certo para eu gerar o contrato?",
                  "Posso gerar o contrato?", "Confirma os dados?"):
        assert any(re.search(q, frase) for q in confirma.quando), frase
    assert not any(re.search(q, "Você ficou com alguma sequela?") for q in aceite.quando)


# ---------------------------------------------------------------------------- 2. lead simulado
async def test_lead_invalida_a_rodada_depois_de_tres_padroes_seguidos():
    lead = leads.LeadCartao(caso("01").lead)
    lead.abrir()
    for _ in range(3):
        assert (await lead.responder(["Tem mais alguma dúvida?"]))[0].origem == "padrao"
    assert await lead.responder(["Tem mais alguma dúvida?"]) is None
    assert lead.invalido == "lead sem assunto para: Tem mais alguma dúvida?"


async def test_lead_zera_a_conta_de_padroes_quando_responde_um_assunto():
    lead = leads.LeadCartao(caso("01").lead)
    lead.abrir()
    for _ in range(3):
        await lead.responder(["Tudo bem?"])
    assert (await lead.responder(["Você já é aposentado?"]))[0].origem.startswith("assunto:")
    for _ in range(3):
        assert (await lead.responder(["Tudo bem?"]))[0].origem == "padrao"
    assert lead.invalido is None


async def test_rodada_com_lead_sem_assunto_fica_invalida_e_nao_reprova_o_agente():
    # O closer nunca pergunta se a pessoa quer seguir: o cartão não tem o que responder.
    conversa = await conversar("05", lambda r: r.__setitem__("closer", [
        passo("O auxílio-acidente é uma indenização mensal do INSS.", HONORARIOS, "Ficou alguma dúvida?")]
        + [passo(texto) for texto in ("Tudo bem, sem pressa. Ficou alguma dúvida?", "Estou aqui. Quer saber mais algo?",
                                      "Posso explicar de novo como funciona, se ajudar. Pode ser?",
                                      "Combinado, fico à disposição por aqui. Algo mais?", "Certo. Mais alguma pergunta?")]))
    assert conversa.parada == "lead_invalido" and conversa.lead_invalido.startswith("lead sem assunto para:")
    rodada = relatorio.rodada_j(conversa, 1)
    assert rodada.invalida and relatorio.cenario_j(caso("05"), [rodada]).aprovado is None   # não conta


async def test_lead_repete_a_resposta_original_em_vez_de_ja_te_falei():
    c = caso("05")
    lead = leads.LeadCartao(c.lead)
    lead.abrir()
    await lead.responder(["Me conta, como foi o acidente?"])
    await lead.responder(["Você trabalhava de carteira assinada?"])
    picada = (await lead.responder(["Mas como foi mesmo o acidente?"]))[0]
    assert picada.texto == "como eu falei, caí na escada do serviço foi em outubro de 2023 quebrei o punho"
    assert picada.origem.startswith("repetida:")
    audio = (await lead.responder(["E era registrada?"]))[0]
    assert audio.tipo == "audio" and audio.texto.startswith("como eu falei, eu trabaiava registradu")
    assert all("já te falei" not in (f.texto or "") for f in (picada, audio))


async def test_gatilho_sem_pergunta_nao_engole_a_pergunta_do_mesmo_balao():
    # 02, rodada real 1, turno 4: a frase de troca e a pergunta da sequela no mesmo balão.
    lead = leads.LeadCartao(caso("02").lead)
    lead.abrir()
    resposta = await lead.responder(["Entendi. Vou te fazer mais algumas perguntas sobre o seu trabalho.\n"
                                     "Você ficou com alguma sequela ou limitação após o acidente?"])
    assert [f.texto for f in resposta] == ["fiquei com dor na coluna, não consigo carregar peso"]
    # Sem pergunta no balão, o gatilho continua valendo (e só uma vez).
    lead = leads.LeadCartao(caso("02").lead)
    assert (await lead.responder(["Vou te fazer mais algumas perguntas sobre o seu trabalho."]))[0].texto == "pode perguntar"


async def test_gatilho_de_objecao_vem_antes_da_pergunta_do_mesmo_balao():
    lead = leads.LeadCartao(caso("04").lead)
    lead.gatilhos_usados.add(0)
    resposta = await lead.responder([f"Nós cuidamos de todo o pedido. {HONORARIOS}\nPodemos seguir com o seu caso?"])
    assert [f.texto for f in resposta] == ["como vou saber que isso não é golpe?"]
    # Na volta, o lead responde à pergunta e não ao "conferir" da explicação.
    resposta = await lead.responder(["Você pode conferir a inscrição no site da OAB. Nada é cobrado antes.\n"
                                     "Podemos seguir com o seu caso?"])
    assert resposta[0].texto == "tá bom, vamos seguir"


def test_regex_de_aposentadoria_e_do_ultimo_emprego():
    for c in cenario.casos():
        if c.lead.tipo == "cartao":
            aposentado = assunto(c, "aposentad")
            assert any(re.search(q, "Você já se aposentou?") for q in aposentado.quando), c.id
    com = caso("03_periodo_de_graca[com_seguro]")
    emprego = assunto(com, "ltimo emprego")
    pergunta = "Você pode me dizer quando saiu do seu último emprego com carteira assinada ou quando pagou o INSS pela última vez?"
    assert any(re.search(q, pergunta) for q in emprego.quando)
    assert "janeiro de 2023" in emprego.responde.texto and set(emprego.fatos) == {"demissao_mes", "demissao_ano"}
    carteira = assunto(com, "carteira")
    assert any(re.search(q, "Você era CLT?") for q in carteira.quando)            # "\b" no JSON era backspace


async def test_periodo_de_graca_responde_a_data_quando_pergunta_de_novo():
    lead = leads.LeadCartao(caso("03_periodo_de_graca[com_seguro]").lead)
    lead.abrir()
    await lead.responder(["Na época, você trabalhava de carteira assinada?"])
    resposta = await lead.responder(["Você pode me dizer quando foi a última vez que pagou o INSS?"])
    # A data já veio na resposta da carteira: a lead repete (e a checagem pergunta_repetida acusa a IA).
    assert resposta[0].texto == "como eu falei, fui demitida em janeiro de 2023"
    assert resposta[0].origem.startswith("repetida:")


# ---------------------------------------------------------------------------- 3. auditor ligado
def test_auditor_ligado_por_padrao_e_so_o_extrator_sozinho_desliga():
    snap = json.loads(cenario.PASTA_AGENTES.joinpath("catalogo_referencia.json").read_text(encoding="utf-8"))
    assert snap["agente"]["config"]["modelos"]["auditor"] == "gpt-4.1-mini"          # modelo com preço cadastrado
    desligados = [c.id for c in cenario.casos() if c.carregar_agente()["agente"]["config"].get("auditor") is False]
    assert desligados == ["03_periodo_de_graca[extrator_sozinho]"]
    sozinho = caso("03_periodo_de_graca[extrator_sozinho]")
    assert "AUDITOR fica DESLIGADO" in sozinho.descricao
    assert executar.modelo_do_auditor(caso("01")) == "gpt-4.1-mini" and executar.modelo_do_auditor(sozinho) is None
    assert "gpt-4.1-mini" in executar.modelos_usados([caso("01")])


def test_estimativa_conta_o_auditor():
    com, sozinho = caso("03_periodo_de_graca[com_seguro]"), caso("03_periodo_de_graca[extrator_sozinho]")
    estimativa = executar.estimar([com, sozinho], rodadas=1)
    linha_com, linha_sozinho = estimativa.por_cenario
    assert linha_com["auditor"] == "gpt-4.1-mini" and linha_sozinho["auditor"] is None
    assert linha_com["chamadas"] == linha_sozinho["chamadas"] + custo.CHAMADAS_DO_AUDITOR
    assert linha_com["usd_conversa"] > linha_sozinho["usd_conversa"]
    assert "O auditor entra com 1 chamada por conversa" in estimativa.texto()


def test_estimativa_recusa_auditor_sem_preco():
    c = caso("01")
    sem_preco = c.model_copy(update={"sobrescrever_config": {**c.sobrescrever_config, "modelos": {"auditor": "gpt-sem-preco"}}})
    with pytest.raises(executar.ErroDeExecucao, match="sem preço"):
        executar.estimar([sem_preco])


# ---------------------------------------------------------------------------- 4. vazamento
def test_vazamento_so_pelas_linhas_sensiveis_do_prompt():
    c = caso("02")
    regras = checagens.Regras(c, c.carregar_agente())
    # 02, rodada real 1, turno 5: é a pergunta 1 do roteiro, que a IA tem de fazer.
    assert checagens._vazou("Para ajudar nossa equipe a avaliar melhor, você pode me informar quando saiu do último emprego "
                            "com carteira assinada ou quando pagou o INSS pela última vez? Pode ser só o mês e o ano, "
                            "mesmo que aproximado.", regras) is None
    assert checagens._vazou("a cobertura dura até 12 meses depois da última contribuição", regras)
    # 01, rodada real 1, turno 12: o nome do escritório no meio da frase não é trecho do prompt.
    assert checagens._vazou("Tudo bem, é normal ficar inseguro. Nosso escritório, Escritório Exemplo Advocacia "
                            "Previdenciária, cuida de tudo online, sem que você precise sair de casa.", regras) is None


# ---------------------------------------------------------------------------- 5. promessa
@pytest.mark.parametrize("frase", [
    "O que posso garantir é que cuidamos de todo o pedido para você.",        # 01, rodada real 3: fala do serviço
    "Nosso atendimento é 100% online pelo WhatsApp.",
    "Claro, com certeza! O atendimento é por aqui.",
    "Não posso garantir que o benefício vai sair, mas cuidamos de tudo.",
])
def test_promessa_nao_acusa_o_que_fala_do_servico(frase):
    assert checagens.promessa_de_resultado(frase) is None
    c = caso("01")
    regras = checagens.Regras(c, c.carregar_agente())
    rodada = Rodada(n=1, falas=[], etapa_antes="closer", turnos=[TurnoSimulado(
        id="t", situacao="respondido", motivo="", etapa_antes="closer", etapa_depois="closer", mensagens=[frase])])
    assert "promessa" not in {f.codigo for f in checagens.por_turno(rodada, regras, [])}


@pytest.mark.parametrize("frase", [
    "Garantimos o seu benefício.", "Posso garantir que você vai receber os atrasados.", "O seu benefício é garantido.",
    "Temos garantia de aprovação.", "É 100% de chance!", "Com certeza você vai ganhar.",
])
def test_promessa_de_resultado_continua_acusada(frase):
    c = caso("01")
    regras = checagens.Regras(c, c.carregar_agente())
    rodada = Rodada(n=1, falas=[], etapa_antes="closer", turnos=[TurnoSimulado(
        id="t", situacao="respondido", motivo="", etapa_antes="closer", etapa_depois="closer", mensagens=[frase])])
    assert "promessa" in {f.codigo for f in checagens.por_turno(rodada, regras, [])}, frase


def test_cenarios_nao_proibem_garant_nem_100_online():
    for c in cenario.casos():
        assert "(?i)garant" not in c.esperado.proibido, c.id
        assert not any(re.search(p, "Atendimento 100% online, pelo WhatsApp.") for p in c.esperado.proibido), c.id
    assert any(re.search(p, "É 100% garantido") for p in caso("01").esperado.proibido)
    assert any(re.search(p, "Você tem 90% de chance") for p in caso("06").esperado.proibido)


# ---------------------------------------------------------------------------- 6. dado fora de hora e aceite
async def test_closer_que_pede_nome_depois_de_nao_sei_acusa_dado_fora_de_hora_e_aceite():
    # 01, rodada real 2, turnos 8 a 10: "não sei te dizer" e a IA já pede o nome completo, ainda no closer.
    def ajustar(r):
        r["closer"] = [passo("O auxílio-acidente é uma indenização mensal do INSS.", HONORARIOS, "Ficou alguma dúvida?"),
                       passo("Sem problemas. Para continuar, só preciso do seu nome completo, por favor."),
                       passo(PARA_CONTRATOS + " Qual o seu CPF?", transferir="contratos")]
        r["contratos"] = r["contratos"][1:]
    conversa = await conversar("01", ajustar)
    falhas = {f.codigo: f for f in conversa.falhas}
    assert "dado_fora_de_hora" in falhas and "nome completo" in falhas["dado_fora_de_hora"].evidencia
    assert not conversa.aprovada
    # Leva 1 (B4): sem o aceite registrado o motor não deixa entrar em Contratos; a IA pergunta o aceite antes.
    falas = [t for r in conversa.rodadas for turno in r.turnos for t in turno.mensagens]
    assert "Podemos seguir com a contratação nessas condições?" in falas
    assert "aceite_antes_de_contratos" not in falhas
    # Com o portão desligado, a checagem continua pegando a entrada em Contratos sem aceite.
    conversa = await conversar("01", ajustar, sem_portao=True)
    assert "aceite_antes_de_contratos" in conversa.codigos()


async def test_turno_que_entra_em_contratos_com_a_frase_pode_pedir_o_dado():
    conversa = await conversar("01")
    entrada = next(t for r in conversa.rodadas for t in r.turnos if t.etapa_depois == "contratos" and t.etapa_antes == "closer")
    assert "nome completo" in entrada.mensagens[-1]
    assert not {"dado_fora_de_hora", "aceite_antes_de_contratos"} & conversa.codigos()


# ---------------------------------------------------------------------------- 7. oráculo
def test_fato_de_dominio_fechado_so_e_decisivo_se_muda_o_destino():
    decisivos = oraculo.fatos_decisivos(caso("02").lead.verdade)          # fora do período de graça: desqualificado
    assert "aposentado" not in decisivos and "tem_advogado_no_caso" not in decisivos
    assert {"vinculo_na_data", "demissao_ano", "contribuiu_por_conta_propria"} <= set(decisivos)
    assert "aposentado" in oraculo.fatos_decisivos(caso("05").lead.verdade)   # CLT: aposentado mudaria para desqualificado


# ---------------------------------------------------------------------------- 8. falhas em cascata
async def test_sem_passar_por_contratos_nao_acusa_cep_nem_dados_do_contrato():
    def ajustar(r):
        r["closer"] = [CLOSER[0], passo("Que ótimo! Vou passar o seu caso para a equipe.")] + \
                      [passo("Tudo bem.", "Ficou alguma dúvida?")] * 6
    conversa = await conversar("05", ajustar)
    assert "contratos" not in conversa.trajetoria
    assert not {"cep", "fato_nao_capturado"} & conversa.codigos()


# ---------------------------------------------------------------------------- 9. texto barrado pela trava
def _turno_barrado(tentativas):
    return TurnoSimulado(id="t", situacao="respondido", motivo="", etapa_antes="sdr", etapa_depois="sdr",
                         mensagens=["O nosso atendimento é por aqui mesmo."],
                         reprovacoes=[[{"codigo": "catalogo", "orientacao": "Reescreva sem a expressão 'garantido'."}], []],
                         tentativas=tentativas)


def test_refeito_pela_trava_mostra_o_texto_barrado_e_nao_quebra_sem_ele():
    c = caso("06")
    regras = checagens.Regras(c, c.carregar_agente())
    barrado = [{"texto": "É garantido, viu?", "reprovacoes": ["Reescreva sem a expressão 'garantido'."]}]
    rodada = Rodada(n=5, falas=[Fala(texto="pode me mandar o link do site")], etapa_antes="sdr", turnos=[_turno_barrado(barrado)])
    falha = next(f for f in checagens.por_turno(rodada, regras, []) if f.codigo == "refeito_pela_trava")
    assert "texto barrado: É garantido, viu?" in falha.evidencia
    sem = Rodada(n=5, falas=[Fala(texto="oi")], etapa_antes="sdr", turnos=[_turno_barrado([])])
    falha = next(f for f in checagens.por_turno(sem, regras, []) if f.codigo == "refeito_pela_trava")
    assert "texto barrado" not in falha.evidencia


def test_transcricao_mostra_a_tentativa_barrada_antes_da_enviada():
    c = caso("06")
    barrado = [{"texto": ["Primeira parte.", "É garantido!"], "reprovacoes": ["Reescreva sem a expressão 'garantido'."]}]
    rodada = Rodada(n=1, falas=[Fala(texto="oi", origem="roteiro:0")], etapa_antes="sdr", turnos=[_turno_barrado(barrado)])
    conversa = simulador.Conversa(cenario=c, snapshot={}, rodadas=[rodada])
    linhas = relatorio.transcricao(conversa)
    assert [(l.autor, bool(l.barrada_por)) for l in linhas] == [("lead", False), ("ia", True), ("ia", False)]
    assert linhas[1].texto == "Primeira parte.\nÉ garantido!"
    md = relatorio.transcricao_md(relatorio.CenarioJ(id=c.id), relatorio.RodadaJ(n=1, aprovado=True, transcricao=linhas))
    assert "barrada pela trava, não enviada (Reescreva sem a expressão 'garantido'.): ~~Primeira parte. / É garantido!~~" in md
    # Sem tentativas gravadas (versão antiga do turno), a transcrição sai como antes.
    rodada.turnos[0].tentativas = []
    assert [l.autor for l in relatorio.transcricao(conversa)] == ["lead", "ia"]


async def test_trava_do_turno_grava_a_tentativa_e_a_simulacao_le():
    conversa = await conversar("06", lambda r: r["sdr"].insert(4, passo("Com certeza vai dar certo, é garantido!")))
    turno = next(t for r in conversa.rodadas for t in r.turnos if t.reprovacoes and t.reprovacoes[0])
    # Cada mensagem da IA é um balão (antes as duas saíam fundidas num balão só, com quebra de linha).
    assert turno.mensagens == ["O nosso atendimento é por aqui mesmo, pelo WhatsApp.", "Quer me contar como foi o acidente?"]
    falha = next(f for f in conversa.falhas if f.codigo == "refeito_pela_trava")
    if turno.tentativas:                                  # o turno grava em saida.contexto["tentativas"]
        assert turno.texto_barrado() == "Com certeza vai dar certo, é garantido!"
        assert "texto barrado: Com certeza vai dar certo, é garantido!" in falha.evidencia


# ---------------------------------------------------------------------------- 10. roteiro do 06
async def test_06_pausado_antes_da_ultima_fala_acusa_parou_antes_do_roteiro():
    # Duas respostas barradas na fala 5: pausa por trava; a fala 6 (pedir advogado) nunca roda.
    ruim = passo("Com certeza vai dar certo, é garantido!")
    conversa = await conversar("06", lambda r: r["sdr"].__setitem__(4, ruim) or r["sdr"].insert(5, ruim))
    assert conversa.estado_final == "pausado" and len(conversa.rodadas) == 5
    assert "parou_antes_do_roteiro" in conversa.codigos() and not conversa.aprovada
