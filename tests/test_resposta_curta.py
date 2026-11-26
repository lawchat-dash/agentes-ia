"""Resposta curta ligada à última pergunta da IA (app/cerebro/resposta_curta.py, extrator.pela_pergunta).

Bug real (Auxílio-Acidente, SDR): "Não" para "Hoje você recebe alguma aposentadoria?" e para "você já tem advogado?"
não gravava nada; "Não" para "documento médico?" virava documentos_rurais=nao (motivo de desqualificar) e "4 meses" de
auxílio-doença virava demissao_meses_antes_do_acidente=4. O portão segurou a passagem para o Closer duas vezes e o lead
foi para a equipe. Todos os dados de lead são inventados. Nenhuma IA de verdade é chamada.
"""

from __future__ import annotations

import json

import pytest

from app.cerebro import catalogo, extrator, resposta_curta as rc, turno
from tests.test_e2e_helena import FRASE_CLOSER, Cenario, banco_local, e2e, extrai, responde  # noqa: F401
from tests.test_e2e_troca_departamento import COLUNAS, ETIQUETAS, _funil_completo

AGENTE_JSON = "avaliacao/agentes/sousa_costa_corrigido.json"


def _produto():
    from pathlib import Path
    raiz = Path(__file__).resolve().parents[1]
    config = json.loads((raiz / AGENTE_JSON).read_text(encoding="utf-8"))["agente"]["config"]
    return catalogo.carregar(config)


def _hist(pergunta: str) -> list[dict[str, str]]:
    return [{"autor": "lead", "texto": "oi, sofri um acidente"}, {"autor": "você", "texto": "Entendi."},
            {"autor": "você", "texto": pergunta}]


def _resolve(pergunta: str, resposta: str) -> list[tuple]:
    aceitas = extrator._chaves_do_produto(_produto())
    return [(r.chave, r.valor, r.trecho) for r in rc.resolver(_hist(pergunta), [resposta], aceitas, extrator.normalizar)]


# ============================================================================ A. normalização e resolvedor
@pytest.mark.parametrize("texto, esperado", [
    ("Sim", ("sim", True)), ("s", ("sim", True)), ("isso", ("sim", True)), ("Claro!", ("sim", True)),
    ("sim sim", ("sim", True)), ("Não", ("nao", True)), ("nao", ("nao", True)), ("n", ("nao", True)),
    ("Nunca", ("nao", True)), ("não senhora", ("nao", True)), ("Não sei", ("nao_sabe", True)),
    ("não lembro", ("nao_sabe", True)), ("Não, nunca tive", ("nao", True)), ("Sim! fiquei mancando", ("sim", False)),
    ("Não entendi a pergunta", None), ("sim eu acho que foi em 2020", None), ("", None),
])
def test_sim_nao(texto, esperado):
    assert rc.sim_nao(extrator.normalizar(texto), texto) == esperado


@pytest.mark.parametrize("texto, meses", [("4 meses", 4), ("uns 8 meses", 8), ("2 anos", 24), ("um ano e meio", 18),
                                          ("8", 8), ("faz uns 3 meses", 3), ("não sei", None), ("em 2021", None)])
def test_tempo_em_meses(texto, meses):
    assert rc.tempo_em_meses(extrator.normalizar(texto)) == meses


@pytest.mark.parametrize("pergunta, resposta, esperado", [
    ("Hoje você recebe alguma aposentadoria do INSS?", "Não", [("aposentado", "nao", "Não")]),
    ("Você já é aposentado por alguma aposentadoria?", "não", [("aposentado", "nao", "não")]),
    ("você já tem advogado cuidando do seu Auxílio-Acidente?", "Não", [("tem_advogado_no_caso", "nao", "Não")]),
    ("O acidente deixou alguma sequela ou limitação, mesmo que leve?", "Sim", [("sequela", "sim", "Sim")]),
    ("Ficou com alguma limitação?", "não sei", [("sequela", "nao_sabe", "não sei")]),
    ("você estava registrado com carteira assinada (CLT) quando o acidente aconteceu?", "Sim",
     [("vinculo_na_data", "clt", "Sim")]),
    ("você estava registrado com carteira assinada (CLT) quando o acidente aconteceu?", "Não", []),  # não diz o vínculo
    ("Você tem documentos do trabalho na roça?", "Não", [("documentos_rurais", "nao", "Não")]),
    ("Quanto tempo antes do acidente você saiu do emprego?", "uns 8 meses",
     [("demissao_meses_antes_do_acidente", 8, "uns 8 meses")]),
    ("Podemos seguir com a contratação nessas condições?", "sim", [("aceite_honorarios", "sim", "sim")]),
    # Sem fato do produto para a pergunta: nada (o extrator de IA decide).
    ("Você tem algum documento médico da época do acidente?", "Não", []),
    ("Por quanto tempo, mais ou menos, você ficou recebendo auxílio-doença?", "4 meses", []),
    ("Você já tem advogado?", "Não entendi", []),
    ("Você é aposentado? E tem advogado no caso?", "Não", []),              # duas perguntas: ambíguo
])
def test_resolver_pela_ultima_pergunta(pergunta, resposta, esperado):
    assert _resolve(pergunta, resposta) == esperado


def test_resolver_ignora_lote_que_nao_responde_a_ia():
    historico = [{"autor": "você", "texto": "Você já tem advogado?"}, {"autor": "lead", "texto": "oi"}]
    assert rc.resolver(historico, ["Não"], {"tem_advogado_no_caso"}, extrator.normalizar) == []


# ============================================================================ B. trava do assunto (sobre conferir)
def _pela_pergunta(pergunta: str, resposta: str, fatos: list[tuple[str, str, str]]):
    produto = _produto()
    extracao = extrator.conferir(extrai(fatos), [resposta], {}, produto)
    return extrator.pela_pergunta(extracao, _hist(pergunta), [resposta], {}, produto)


def test_nao_para_documento_medico_nao_vira_documentos_rurais():
    extracao = _pela_pergunta("Você tem algum documento médico da época do acidente?", "Não",
                              [("documentos_rurais", "nao", "Não")])
    assert extracao.fatos == []
    assert [(r["chave"], r["motivo"]) for r in extracao.rejeitados] == [("documentos_rurais", "fora_do_assunto")]


def test_meses_de_auxilio_doenca_nao_viram_demissao():
    extracao = _pela_pergunta("Por quanto tempo, mais ou menos, você ficou recebendo auxílio-doença?", "4 meses",
                              [("demissao_meses_antes_do_acidente", "4", "4 meses")])
    assert extracao.fatos == [] and extracao.rejeitados[0]["motivo"] == "fora_do_assunto"


def test_fato_travado_fica_quando_a_pergunta_ou_a_mensagem_e_do_assunto():
    pela_pergunta = _pela_pergunta("Você tem documentos do trabalho na roça?", "Não", [("documentos_rurais", "nao", "Não")])
    assert [(f.chave, f.valor) for f in pela_pergunta.fatos] == [("documentos_rurais", "nao")]
    pela_mensagem = _pela_pergunta("Me conta como foi o acidente?", "caí da moto e não sou aposentado",
                                   [("aposentado", "nao", "não sou aposentado")])
    assert [(f.chave, f.valor) for f in pela_mensagem.fatos] == [("aposentado", "nao")]
    sequela = _pela_pergunta("O acidente deixou alguma sequela ou limitação, mesmo que leve?",
                             "Sim eu não consigo mais andar fixo só mancando",
                             [("sequela", "sim", "Sim eu não consigo mais andar fixo só mancando")])
    assert [(f.chave, f.valor) for f in sequela.fatos] == [("sequela", "sim")]


def test_resposta_so_nao_vale_mais_que_o_extrator_e_vazio_e_preenchido():
    trocado = _pela_pergunta("Você já tem advogado cuidando do seu caso?", "Não", [("tem_advogado_no_caso", "sim", "Não")])
    assert [(f.chave, f.valor) for f in trocado.fatos] == [("tem_advogado_no_caso", "nao")]
    assert trocado.rejeitados[-1]["motivo"] == "resposta_curta_diz_outro"
    vazio = _pela_pergunta("Hoje você recebe alguma aposentadoria do INSS?", "Não", [])
    assert [(f.chave, f.valor, f.trecho) for f in vazio.fatos] == [("aposentado", "nao", "Não")]
    assert vazio.resolvidos[0]["pergunta"] == "Hoje você recebe alguma aposentadoria do INSS?"


# ============================================================================ C. a conversa inteira, ponta a ponta
ROTEIRO_SDR = [
    "Entendi. E você recebeu auxílio-doença na época do acidente?",
    "Por quanto tempo, mais ou menos, você ficou recebendo auxílio-doença?",
    "O acidente deixou alguma sequela ou limitação, mesmo que leve?",
    "Você tem algum documento médico da época do acidente?",
    "Certo. E você estava registrado com carteira assinada (CLT) quando o acidente aconteceu?",
    "Hoje você recebe alguma aposentadoria do INSS?",
    "Entendi. E você já tem advogado cuidando do seu Auxílio-Acidente?",
]
RESPOSTAS = ["Sim", "4 meses", "Sim eu não consigo mais andar fixo só mancando", "Não", "Sim", "Não", "Não"]


def _ultima_da_ia(conteudo: str) -> str:
    antes = conteudo.split("MENSAGENS NOVAS")[0]
    linhas = [linha for linha in antes.splitlines() if linha.startswith(("[você]", "você:"))]
    return linhas[-1].split("]", 1)[-1].split(":", 1)[-1].strip() if linhas else ""


def _novas(conteudo: str) -> str:
    return conteudo.split("MENSAGENS NOVAS")[-1]


def _extrator_com_o_erro_do_llm(_sistema: str, conteudo: str):
    """Reproduz o extrator de produção: acerta sequela e CLT, erra documentos_rurais e demissão, esquece os 'Não'."""
    pergunta, novas = _ultima_da_ia(conteudo), _novas(conteudo)
    if "Por quanto tempo" in pergunta and "4 meses" in novas:
        return extrai([("demissao_meses_antes_do_acidente", "4", "4 meses")])
    if "sequela" in pergunta and "mancando" in novas:
        return extrai([("sequela", "sim", "Sim eu não consigo mais andar fixo só mancando")])
    if "documento médico" in pergunta:
        return extrai([("documentos_rurais", "nao", "Não")])
    if "carteira assinada" in pergunta:
        return extrai([("vinculo_na_data", "clt", "Sim")])
    return extrai()                                 # aposentadoria e advogado: nada (o erro do LLM)


def _sdr_falso(_sistema: str, conteudo: str):
    """O SDR segue o roteiro; respondida a pergunta do advogado, passa ao Comercial com a frase de entrada."""
    conversa = conteudo.split("MENSAGENS NOVAS")[0]
    if ROTEIRO_SDR[-1] in conversa:
        return responde("Perfeito, obrigado pelas respostas!", FRASE_CLOSER, transferir_para="closer")
    proxima = next(p for p in ROTEIRO_SDR if p not in conversa)
    return responde(proxima)


async def test_conversa_do_bug_passa_para_o_closer_sem_ir_para_a_equipe(e2e: Cenario):
    await _funil_completo(e2e, **{"etapa:closer": {
        "coluna_crm": COLUNAS["closer"], "adicionar_etiquetas": [ETIQUETAS["closer"]],
        "remover_etiquetas": [ETIQUETAS["sdr"]], "nota": "🔀 Lead passou para o Closer.",
        "transferir": True, "id_equipe": "equipe-comercial"}})
    # Departamento do Comercial na Helena (como a config do escritório liga a troca de departamento).
    await e2e.pool.execute("""update agentesia_agentes set config = jsonb_set(config, '{funcoes,transferir_humano}',
                              'true'::jsonb) where id = $1::uuid""", e2e.ids["agente"])
    e2e.ia.extrator = _extrator_com_o_erro_do_llm
    e2e.ia.etapa = _sdr_falso
    await e2e.chega(e2e.do_lead("Oi, sofri um acidente de moto indo pro trabalho"))
    for resposta in RESPOSTAS:
        await e2e.chega(e2e.do_lead(resposta))

    lead = await e2e.lead()
    vigentes = await e2e.repo.fatos_vigentes(str(lead["id"]))
    assert vigentes["aposentado"] == "nao" and vigentes["tem_advogado_no_caso"] == "nao"
    assert vigentes["sequela"] == "sim" and vigentes["vinculo_na_data"] == "clt"
    assert "documentos_rurais" not in vigentes and "demissao_meses_antes_do_acidente" not in vigentes
    fontes = {f["chave"]: (f["fonte"], f["trecho"]) for f in await e2e.pool.fetch(
        "select chave, fonte, trecho from agentesia_lead_fatos where id_lead = $1", lead["id"])}
    assert fontes["aposentado"] == ("extrator", "Não") and fontes["tem_advogado_no_caso"] == ("extrator", "Não")

    # (1) a etapa vira closer no mesmo turno do "Não" do advogado, sem pausa e sem equipe.
    assert (lead["etapa"], lead["estado"]) == ("closer", "ativo")
    turnos = await e2e.turnos()
    assert (turnos[-1]["etapa_antes"], turnos[-1]["etapa_depois"]) == ("sdr", "closer")
    assert not await e2e.eventos("troca_barrada_faltam_fatos") and not await e2e.eventos("analise_manual")
    # (2) o lead recebe a frase de entrada do Closer (cadastrada no papel) como último balão.
    assert e2e.helena.textos()[-1] == FRASE_CLOSER
    assert catalogo.PERGUNTA_DO_PORTAO["aposentado"] not in e2e.helena.textos()       # não perguntou de novo
    # (3) a troca na LawChat: card para a coluna do Comercial, etiqueta e departamento do Comercial.
    assert e2e.helena.movimentos_de_card()[-1][1] == COLUNAS["closer"]
    assert ("InsertIfNotExists", (ETIQUETAS["closer"],)) in e2e.helena.etiquetas()
    assert e2e.helena.transferencias()[-1] == (e2e.sessao, "equipe-comercial")
    # Rastro: o que o código gravou pela pergunta e o que a trava descartou.
    pela_pergunta = {json.loads(e["detalhe"])["fato"]["chave"] if isinstance(e["detalhe"], str) else e["detalhe"]["fato"]["chave"]
                     for e in await e2e.eventos("fato_pela_pergunta")}
    assert pela_pergunta == {"auxilio_doenca", "aposentado", "tem_advogado_no_caso"}
    descartes = [json.loads(e["detalhe"]) if isinstance(e["detalhe"], str) else e["detalhe"]
                 for e in await e2e.eventos("fato_sem_prova")]
    assert {(d["fato"]["chave"], d["fato"]["motivo"]) for d in descartes} >= {
        ("documentos_rurais", "fora_do_assunto"), ("demissao_meses_antes_do_acidente", "fora_do_assunto")}
    assert turno.MARCA_PORTAO not in vigentes or not vigentes[turno.MARCA_PORTAO]


# ============================================================================ D. segundo caso real (auxílio-doença)
ROTEIRO_CASO_2 = [
    ("Você recebeu auxílio-doença na época do acidente?",),
    # O que a IA de produção mandou: repetiu a pergunta já respondida antes da próxima.
    ("Você recebeu auxílio-doença na época do acidente? Você comentou que não recebeu.",
     "O acidente gerou alguma sequela ou limitação?"),
    ("Você possui algum documento médico da época do acidente?",),
    ("Certo, obrigado!", "Hoje você recebe alguma aposentadoria do INSS?"),
]


def _extrator_caso_2(_sistema: str, conteudo: str):
    pergunta, novas = _ultima_da_ia(conteudo), _novas(conteudo)
    if "auxílio-doença" in pergunta and "Não" in novas:
        return extrai([("seguro_desemprego", "nao", "Não")])           # o erro do LLM em produção
    if "documento médico" in pergunta and "Não" in novas:
        return extrai([("documentos_rurais", "nao", "Não")])
    if "sequela" in pergunta and "mancando" in novas:
        return extrai([("sequela", "sim", "Sim, fiquei mancando")])
    return extrai()


def _sdr_caso_2(_sistema: str, conteudo: str):
    conversa = conteudo.split("MENSAGENS NOVAS")[0]
    respondidas = sum(1 for linha in conversa.splitlines() if linha.startswith("lead:"))
    return responde(*ROTEIRO_CASO_2[min(respondidas, len(ROTEIRO_CASO_2) - 1)])


async def test_segundo_caso_auxilio_doenca_nao_vira_seguro_e_a_pergunta_nao_se_repete(e2e: Cenario):
    e2e.ia.extrator = _extrator_caso_2
    e2e.ia.etapa = _sdr_caso_2
    for texto in ("Oi, me acidentei no serviço", "Não", "Sim, fiquei mancando", "Não"):
        await e2e.chega(e2e.do_lead(texto))

    lead = await e2e.lead()
    vigentes = await e2e.repo.fatos_vigentes(str(lead["id"]))
    assert vigentes["auxilio_doenca"] == "nao" and vigentes["sequela"] == "sim"
    assert "seguro_desemprego" not in vigentes and "documentos_rurais" not in vigentes
    enviados = e2e.helena.textos()
    assert not any("Você comentou que não recebeu" in t for t in enviados)
    assert enviados.count("Você recebeu auxílio-doença na época do acidente?") == 1
    assert "O acidente gerou alguma sequela ou limitação?" in enviados
    assert len(await e2e.eventos("pergunta_ja_respondida")) == 1
    descartes = {(d["fato"]["chave"], d["fato"]["motivo"]) for d in (
        json.loads(e["detalhe"]) if isinstance(e["detalhe"], str) else e["detalhe"] for e in await e2e.eventos("fato_sem_prova"))}
    assert {("seguro_desemprego", "fora_do_assunto"), ("documentos_rurais", "fora_do_assunto")} <= descartes
    assert (lead["etapa"], lead["estado"]) == ("sdr", "ativo")


async def test_trava_da_pergunta_repetida_no_turno():
    """Unidade da trava: sai só o balão que repete pergunta respondida, e só se sobrar outro com pergunta."""
    entrada = turno.Entrada(escritorio="E", agente="A", etapa="sdr", novas=["Não"], historico=[
        {"autor": "você", "texto": "Você recebeu auxílio-doença na época do acidente?"}, {"autor": "lead", "texto": "Não"}])
    saida = turno.Saida()
    repetida = {"tipo": "texto", "texto": "Você recebeu auxílio-doença na época do acidente? Você comentou que não."}
    proxima = {"tipo": "texto", "texto": "O acidente gerou alguma sequela?"}
    assert turno._sem_pergunta_ja_respondida(entrada, saida, [repetida, proxima], "", "sdr") == [proxima]
    assert [e["tipo"] for e in saida.eventos] == ["pergunta_ja_respondida"]
    sozinha = turno._sem_pergunta_ja_respondida(entrada, turno.Saida(), [repetida, {"tipo": "texto", "texto": "Certo."}], "", "sdr")
    assert len(sozinha) == 2                                         # sem outra pergunta: não tira
    entrada.novas = ["não entendi, pode repetir?"]
    assert len(turno._sem_pergunta_ja_respondida(entrada, turno.Saida(), [repetida, proxima], "", "sdr")) == 2


# ============================================================================ E. portão de fatos desligado (decisão do dono)
@pytest.mark.parametrize("como", ["transferir_para", "frase_exata"])
async def test_portao_desligado_a_passagem_marcada_pela_ia_acontece_direto(e2e: Cenario, como: str):
    """Com config.catalogo.portao_de_fatos = false (o que a ativação grava hoje): quem decide passar é o SDR pelo
    prompt. A passagem que ele marca (transferir_para, ou só a frase de entrada exata) vale no mesmo turno, com a frase e
    a troca na Helena. As respostas curtas continuam anotadas pelo código e o fato fora do assunto continua descartado."""
    await _funil_completo(e2e, **{"etapa:closer": {
        "coluna_crm": COLUNAS["closer"], "adicionar_etiquetas": [ETIQUETAS["closer"]],
        "remover_etiquetas": [ETIQUETAS["sdr"]], "transferir": True, "id_equipe": "equipe-comercial"}})
    await e2e.pool.execute("""update agentesia_agentes set config = jsonb_set(jsonb_set(config,
                              '{funcoes,transferir_humano}', 'true'::jsonb), '{catalogo,portao_de_fatos}', 'false'::jsonb)
                              where id = $1::uuid""", e2e.ids["agente"])

    def sdr(_s: str, conteudo: str):
        conversa = conteudo.split("MENSAGENS NOVAS")[0]
        if ROTEIRO_SDR[-1] in conversa:
            return responde("Perfeito, obrigado pelas respostas!", FRASE_CLOSER,
                            transferir_para="closer" if como == "transferir_para" else "")
        return responde(next(p for p in ROTEIRO_SDR if p not in conversa))

    e2e.ia.extrator = _extrator_com_o_erro_do_llm
    e2e.ia.etapa = sdr
    await e2e.chega(e2e.do_lead("Oi, sofri um acidente de moto indo pro trabalho"))
    for resposta in RESPOSTAS:
        await e2e.chega(e2e.do_lead(resposta))

    lead = await e2e.lead()
    assert (lead["etapa"], lead["estado"]) == ("closer", "ativo")
    turnos = await e2e.turnos()
    assert (turnos[-1]["etapa_antes"], turnos[-1]["etapa_depois"]) == ("sdr", "closer")
    assert e2e.helena.textos()[-1] == FRASE_CLOSER
    assert e2e.helena.movimentos_de_card()[-1][1] == COLUNAS["closer"]
    assert ("InsertIfNotExists", (ETIQUETAS["closer"],)) in e2e.helena.etiquetas()
    assert e2e.helena.transferencias()[-1] == (e2e.sessao, "equipe-comercial")
    assert not await e2e.eventos("troca_barrada_faltam_fatos") and not await e2e.eventos("analise_manual")
    vigentes = await e2e.repo.fatos_vigentes(str(lead["id"]))
    assert vigentes["aposentado"] == "nao" and vigentes["tem_advogado_no_caso"] == "nao"
    assert "documentos_rurais" not in vigentes and "demissao_meses_antes_do_acidente" not in vigentes
