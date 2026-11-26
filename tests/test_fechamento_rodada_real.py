"""Fechamento da rodada REAL de 2026-11-25: os achados confirmados na revisão das correções.

- a trava de "com certeza" barrava frases de serviço ("Com certeza, a equipe vai analisar") e deixava passar a
  promessa com a certeza depois do resultado ("Você vai conseguir o benefício, com certeza!");
- "100% por WhatsApp / virtual / pela internet" ainda caía na trava (pausava o lead como no cenário 06);
- o laço do contrato sem e-mail seguia mudo quando o modelo do contrato exige e-mail (obrigatórios padrão no turno e
  no pipeline);
- a boas-vindas vinha colada no "troque-a pela pergunta do roteiro:" e o modelo a tomava pela pergunta;
- sistema de teste: gatilho de recusa sem "?" engolido, rodada inválida apagando falha crítica, negação de outra
  oração isentando promessa, pergunta repetida do Período de Graça invisível, prompt de referência mandando prometer o
  link e trazendo a resposta literal do cenário 03.
Nada chama a API: ModeloFalso e o modelo roteirizado.
"""

import json
import re
from pathlib import Path

import pytest

from app.avaliacao import cenario, checagens, falso, leads, relatorio, simulador
from app.avaliacao.cenario import Fala
from app.avaliacao.falso import passo
from app.avaliacao.simulador import Rodada, TurnoSimulado
from app.cerebro import catalogo, travas, turno
from app.contrato import dados as cdados
from app.modelo import ModeloFalso
from tests.test_correcoes_rodada_real import (CONTRATO_SEM_CPF, CPF_VALIDO, entrada, extrai, produto, resposta)

RAIZ = Path(__file__).resolve().parent.parent
COM_EMAIL = cdados.OBRIGATORIOS_PADRAO + ("email",)


def _texto(s):
    return [{"tipo": "texto", "texto": s}]


def caso(prefixo, variante=None):
    casos = cenario.casos([prefixo])
    return next(c for c in casos if variante is None or c.id.endswith(f"[{variante}]"))


# ---------------------------------------------------------------------------- trava de promessa
@pytest.mark.parametrize("frase", [
    "Com certeza, a equipe vai analisar o seu caso.",
    "Com certeza, consegue sim enviar pelo WhatsApp.",
    "Com certeza, você recebe o link do contrato por aqui.",
    "Com certeza, você recebe uma resposta da equipe.",
    "Com certeza, você consegue tirar dúvida sobre o seu direito por aqui.",
    "Com certeza, é só aprovar o resumo.",
    "Com certeza! Vou te explicar como funciona o auxílio.",
    "Não tenho certeza de que o benefício sai, isso depende da perícia.",
    "Atendimento 100% por WhatsApp.",
    "Atendimento 100% virtual.",
    "Atendimento 100% pela internet.",
    "Atendimento 100% pelo celular.",
    "Atendemos 100% remotamente.",
])
def test_frase_de_servico_nao_cai_na_trava(frase):
    assert travas.trecho_de_promessa(frase) is None, frase
    assert catalogo.conferir(_texto(frase)) == [], frase
    assert not [r for r in travas.conferir(_texto(frase), etapa="sdr", honorarios=None, midias={}, faltam=())
                if r.codigo == "promessa"], frase


@pytest.mark.parametrize("frase, trecho", [
    ("Você vai conseguir o benefício, com certeza!", "conseguir o benefício, com certeza"),
    ("Seu benefício será aprovado, com certeza.", "aprovado, com certeza"),
    ("Com certeza você terá o benefício.", "com certeza você terá o benefício"),
    ("Com certeza vão aprovar.", "com certeza vão aprovar"),
    ("Com certeza o seu benefício vai sair.", "com certeza o seu benefício vai sair"),
    ("Sem dúvida você recebe os atrasados.", "sem dúvida você recebe os atrasados"),
    ("Seu auxílio sai, com certeza.", "auxílio sai, com certeza"),
    ("Com certeza você ganha.", "com certeza você ganha"),
    ("É 100% gratuito.", "100% gratuito"),
])
def test_promessa_com_certeza_em_qualquer_ordem_e_barrada(frase, trecho):
    assert travas.trecho_de_promessa(frase) == trecho, frase
    assert catalogo.conferir(_texto(frase)) == [f"Reescreva sem a expressão '{trecho}'."], frase


# ---------------------------------------------------------------------------- contrato: obrigatórios do modelo
def _historico_pedindo_email():
    pedido = cdados.pedir_correcao([cdados.CampoInvalido("email", cdados.PEDIR["email"])])
    return [{"autor": "lead", "texto": "pode gerar"}, {"autor": "você", "texto": "Vou gerar o seu contrato."},
            {"autor": "automacao", "texto": pedido}]


async def test_modelo_que_exige_email_corta_o_laco_do_lead_sem_email():
    fatos = {**CONTRATO_SEM_CPF, "cpf": CPF_VALIDO}
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Vou gerar o seu contrato.", ferramenta="zapsign")})
    saida = await turno.processar(modelo, entrada(["não tenho e-mail"], etapa="contratos", fatos=fatos,
                                                  historico=_historico_pedindo_email(), obrigatorios_contrato=COM_EMAIL))
    assert (saida.estado_lead, saida.motivo_estado) == ("pausado", "contrato_correcao_repetida")
    assert saida.eventos[-1]["detalhe"]["campos"] == ["email"]
    assert [m["texto"] for m in saida.mensagens] == [turno.MENSAGENS_FIXAS["contrato_com_a_equipe"]]


async def test_sem_email_e_modelo_padrao_o_contrato_segue():
    fatos = {**CONTRATO_SEM_CPF, "cpf": CPF_VALIDO}
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Vou gerar o seu contrato.", ferramenta="zapsign")})
    saida = await turno.processar(modelo, entrada(["não tenho e-mail"], etapa="contratos", fatos=fatos,
                                                  historico=_historico_pedindo_email()))
    assert saida.motivo == "dados_confirmados" and saida.estado_lead is None


def _atendimento_com_zapsign(obrigatorios):
    from tests.test_catalogo import montar

    atendimento, repo, _, _ = montar({"mensagens": [{"texto": "Vou gerar o seu contrato."}], "transferir_para": "",
                                      "ferramenta": "zapsign"})
    repo.zapsign = {"esc-1": {"modelos": [{"id_modelo": "m-1", "id_agente": "ag-1", "obrigatorios": list(obrigatorios)}]}}
    return atendimento, repo


@pytest.mark.parametrize("obrigatorios, esperado", [(COM_EMAIL, "enviar_mensagem"), ((), "gerar_contrato")])
async def test_pipeline_valida_o_contrato_com_os_obrigatorios_do_modelo(obrigatorios, esperado):
    from app.banco.tipos import Lead

    atendimento, repo = _atendimento_com_zapsign(obrigatorios)
    escritorio, agente = repo.escritorios["esc-1"], repo.agentes["canal-1"]
    lead = Lead(id="lead-1", id_escritorio="esc-1", id_canal="canal-1", id_agente="ag-1", id_etapa="e-contratos",
                telefone="5511999990000")
    saida = turno.Saida(motivo="dados_confirmados", fatos_depois={**CONTRATO_SEM_CPF, "cpf": CPF_VALIDO})
    await atendimento._acoes_do_contrato(escritorio, agente, lead, "turno-1", saida, "teste")
    assert [a["tipo"] for a in repo.acoes] == [esperado]
    if esperado == "enviar_mensagem":
        assert cdados.PEDIR["email"] in repo.acoes[0]["dados"]["texto"]
    assert await atendimento._obrigatorios_do_contrato(escritorio, agente) == (tuple(obrigatorios) or cdados.OBRIGATORIOS_PADRAO)


# ---------------------------------------------------------------------------- boas-vindas
async def test_boas_vindas_vem_logo_depois_do_rotulo_e_antes_da_regra_da_pergunta_generica():
    boas_vindas = "Olá! Aqui é a Júlia, do Escritório Exemplo Advocacia. 😊"
    prod = produto(sdr={"boas_vindas": boas_vindas})
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Olá! Aqui é a Júlia. Como foi o acidente?")})
    await turno.processar(modelo, entrada(["oi"], prod=prod))
    conteudo = modelo.pedidos[1]["conteudo"]
    rotulo = conteudo.index(f"Mensagem de boas-vindas: \"{boas_vindas}\"")
    assert rotulo < conteudo.index("Comece com ela") < conteudo.index("pergunta genérica")
    assert not conteudo.rstrip().endswith(boas_vindas)
    assert not re.search(r"pergunta do roteiro:\s*" + re.escape(boas_vindas), conteudo)


# ---------------------------------------------------------------------------- lead simulado: gatilho de recusa
async def test_recusa_do_cpf_sem_interrogacao_sai_antes_da_resposta():
    lead = leads.LeadCartao(caso("04").lead)
    lead.abrir()
    primeira = (await lead.responder(["Agora me passa o seu CPF, por favor?"]))[0]
    assert (primeira.origem, primeira.texto) == ("gatilho:2", "não vou passar meu CPF pelo WhatsApp")
    segunda = (await lead.responder(["Os seus dados ficam só com o escritório. Pode me passar o CPF?"]))[0]
    assert segunda.origem.startswith("assunto:") and "693.109.802-06" in segunda.texto


def test_gatilho_decide_objecao_pela_fala_ou_pela_marca():
    def gat(texto, **extra):
        return cenario.Gatilho(depois_de="x", fala=Fala(texto=texto), **extra)

    assert gat("não vou passar meu CPF pelo WhatsApp").e_objecao()
    assert gat("como vou saber que não é golpe?").e_objecao()
    assert not gat("pode perguntar").e_objecao() and not gat("poxa, entendi").e_objecao()
    assert gat("pode perguntar", objecao=True).e_objecao() and not gat("e aí?", objecao=False).e_objecao()


# ---------------------------------------------------------------------------- rodada inválida com falha grave
def _rodada(invalida=None, parada="fim", falhas=()):
    return relatorio.RodadaJ(n=1, aprovado=False, invalida=invalida, parada=parada,
                             falhas=[relatorio.FalhaJ(codigo=c, gravidade=g, turno=4, evidencia="x") for c, g in falhas])


def test_falha_critica_antes_da_invalidacao_reprova_o_cenario():
    c = caso("01")
    j = relatorio.cenario_j(c, [_rodada("lead sem assunto para: x?", "lead_invalido", [("promessa", "critica")])])
    assert j.aprovado is False and j.pulado is None and j.por_checagem == {"promessa": "1/1"}


def test_falha_alta_antes_da_invalidacao_tambem_conta():
    c = caso("01")
    j = relatorio.cenario_j(c, [_rodada("lead sem assunto para: x?", "lead_invalido", [("pergunta_repetida", "alta")])])
    assert j.aprovado is False and j.pulado is None


def test_rodada_invalida_sem_falha_grave_fica_pulada_com_o_motivo_certo():
    c = caso("01")
    j = relatorio.cenario_j(c, [_rodada("lead sem assunto para: Ficou alguma dúvida?", "lead_invalido",
                                        [("varias_perguntas", "media")])])
    assert j.aprovado is None and j.pulado == "todas as rodadas foram inválidas: lead sem assunto para: Ficou alguma dúvida?"


def test_invalida_com_falha_alta_nao_derruba_duas_validas_limpas():
    c = caso("01")
    limpa = relatorio.RodadaJ(n=2, aprovado=True)
    j = relatorio.cenario_j(c, [limpa, limpa.model_copy(update={"n": 3}),
                                _rodada("lead sem assunto para: x?", "lead_invalido", [("pergunta_repetida", "alta")])])
    assert j.aprovado is True and j.taxa == "2/2"


# ---------------------------------------------------------------------------- negação de outra oração
@pytest.mark.parametrize("frase", [
    "Não posso garantir, mas o seu benefício vai sair.",
    "Não se preocupe, o seu benefício vai ser aprovado.",
    "Não se preocupe, seu benefício está garantido.",
    "Não precisa ter medo: com certeza você vai receber os atrasados.",
])
def test_negacao_de_outra_oracao_nao_isenta_a_promessa(frase):
    assert checagens.promessa_de_resultado(frase), frase


@pytest.mark.parametrize("frase", [
    "Não posso garantir que o benefício sai.",
    "Não dá para garantir que o seu benefício vai sair.",
    "Ninguém pode garantir que o auxílio vai ser aprovado, porque depende da perícia.",
])
def test_negacao_que_rege_a_promessa_continua_isentando(frase):
    assert checagens.promessa_de_resultado(frase) is None, frase


# ---------------------------------------------------------------------------- 03: pergunta repetida por fato
async def test_lead_responde_como_repeticao_quando_os_fatos_ja_foram_contados():
    lead = leads.LeadCartao(caso("03", "com_seguro").lead)
    lead.abrir()
    await lead.responder(["Na época você trabalhava de carteira assinada?"])
    de_novo = (await lead.responder(["Quando você saiu do seu último emprego com carteira assinada?"]))[0]
    assert de_novo.origem.startswith("repetida:") and de_novo.texto == "como eu falei, fui demitida em janeiro de 2023"


async def test_sem_ter_contado_antes_a_lead_nao_diz_como_te_falei():
    lead = leads.LeadCartao(caso("03", "com_seguro").lead)
    lead.abrir()
    primeira = (await lead.responder(["Quando você saiu do seu último emprego?"]))[0]
    assert primeira.origem.startswith("assunto:") and primeira.texto == "fui demitida em janeiro de 2023"


async def test_reclamacao_do_cartao_nao_ganha_o_prefixo_de_repeticao():
    lead = leads.LeadCartao(caso("03", "extrator_sozinho").lead)
    lead.abrir()
    await lead.responder(["Na época você trabalhava de carteira assinada?"])
    de_novo = (await lead.responder(["Quando você saiu do seu último emprego?"]))[0]
    assert de_novo.texto == "já te falei isso, fui demitida em janeiro de 2023"


def _rodadas_do_pg_repetindo(c):
    carteira = next(i for i, a in enumerate(c.lead.assuntos) if any("carteira" in q for q in a.quando))
    saiu = next(i for i, a in enumerate(c.lead.assuntos) if any("ltimo emprego" in q for q in a.quando))

    def rodada(n, origem, pergunta):
        return Rodada(n=n, falas=[Fala(texto="x", origem=origem)], etapa_antes="sdr",
                      turnos=[TurnoSimulado(id=f"t{n}", situacao="respondido", motivo="catalogo", etapa_antes="sdr",
                                            etapa_depois="sdr", mensagens=[pergunta])])

    return [rodada(1, "abertura", "Na época você trabalhava de carteira assinada, desempregada ou autônoma?"),
            rodada(2, f"assunto:{carteira}", "Quando saiu do seu último emprego com carteira assinada ou pagou o INSS?"),
            rodada(3, f"repetida:{saiu}", "Recebeu o seguro-desemprego?")]


def test_checagem_acusa_o_fato_ja_contado_pedido_de_novo():
    c = caso("03", "com_seguro")
    rodadas = _rodadas_do_pg_repetindo(c)
    assert checagens._perguntas_repetidas(rodadas) == []                 # o texto das perguntas não se parece
    falhas = checagens._fato_pedido_de_novo(rodadas, checagens.Regras(c, c.carregar_agente()))
    assert [(f.codigo, f.gravidade, f.turno) for f in falhas] == [("pergunta_repetida", checagens.ALTA, 2)]
    assert "demissao_mes" in falhas[0].evidencia


async def test_roteiro_falso_que_repete_a_data_reprova_o_03():
    c = caso("03", "com_seguro")
    roteiro = falso.roteiro_de(c.id)
    roteiro["periododegraca"].insert(0, passo("Entendi.", "Quando você saiu do seu último emprego com carteira assinada?"))
    snap = c.carregar_agente()
    conversa = await simulador.rodar_conversa(c, falso.ModeloRoteirizado(snap, roteiro), snapshot=snap)
    assert any(f.codigo == "pergunta_repetida" and "demissao" in f.evidencia for f in conversa.falhas)
    assert not conversa.aprovada


def test_uma_variante_do_03_conta_a_demissao_com_outras_palavras():
    c = caso("03", "sem_seguro")
    textos = [a.responde.texto for a in c.lead.assuntos if set(a.fatos) & {"demissao_mes"}]
    assert any("mandou embora" in t for t in textos)


# ---------------------------------------------------------------------------- prompt de referência e roteiro falso
def _prompt(codigo):
    snap = json.loads((RAIZ / "avaliacao/agentes/catalogo_referencia.json").read_text(encoding="utf-8"))
    return next(e["instrucao"] for e in snap["agente"]["etapas"] if e["codigo"] == codigo)


def test_prompt_de_contratos_nao_manda_prometer_o_link():
    contratos = _prompt("contratos")
    assert "diga que o link do contrato chega em instantes" not in contratos
    assert "diga só que vai gerar o contrato" in contratos
    assert all("instantes" not in m for papel in falso.ROTEIROS.values() for passos in papel.values()
               for p in passos for m in p["mensagens"])


def test_cenarios_com_contrato_proibem_prometer_o_link():
    for prefixo in ("01", "04", "05"):
        assert "(?i)chega em instantes" in caso(prefixo).esperado.proibido, prefixo


def test_prompt_do_periodo_de_graca_nao_traz_a_frase_do_cenario():
    pg = _prompt("periododegraca")
    frases = {a.responde.texto for c in cenario.casos(["03"]) for a in c.lead.assuntos}
    assert "fui demitida em janeiro de 2023" not in pg
    assert not any(len(f or "") >= 20 and f in pg for f in frases)
