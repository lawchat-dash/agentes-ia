"""Base de conhecimento por papel (docs/BASE_DE_CONHECIMENTO.md), sem API: filtro local, consulta, escopo, cortes,
queda para palavras, cache por hash e de consulta, bloco no prompt, regra anti-invenção, lacuna e custo no consumo."""

from __future__ import annotations

import hashlib
import re

import pytest

from app import conhecimento as base
from app import conhecimento_indice as indice
from app import vetores
from app.cerebro import base_conhecimento
from tests.test_catalogo import montar as montar_catalogo
from tests.test_pipeline import webhook

# ---------------------------------------------------------------------------- vetorizador falso "de verdade"
# Determinístico e sem API, mas com cara de embedding real (falso = False): cada dimensão é um assunto.
ASSUNTOS = [
    ("honorario", "cobra", "cobram", "pagar", "pago", "valor", "custa", "custo", "porcent", "adianta"),
    ("document", "rg", "cnh", "comprovante", "laudo", "foto", "identidade"),
    ("golpe", "seguro", "confian", "medo", "oab", "verdade"),
    ("demora", "prazo", "tempo", "meses", "quando"),
    ("assin", "link", "celular", "zapsign", "certificado"),
    ("estacion", "carro", "vaga"),
    ("perder", "perde", "ganhar", "resultado"),
    ("endereco", "fica", "rua", "visita", "escritorio", "presencial"),
]


class VetorizadorAssuntos:
    """Uma dimensão por assunto; as outras palavras (sem repetir) caem, por hash, em 64 dimensões de "resto"."""
    falso = False

    def __init__(self, dimensoes: int = len(ASSUNTOS) + 64) -> None:
        self.modelo, self.dimensoes = "emb-teste", dimensoes
        self.chamadas = 0
        self.textos: list[str] = []

    def vetor(self, texto: str) -> list[float]:
        palavras = re.findall(r"[a-z0-9]+", base.sem_acento(texto))
        v = [0.0] * self.dimensoes
        assuntos = ASSUNTOS[: self.dimensoes]
        resto = max(1, self.dimensoes - len(assuntos))
        outras = set()
        for p in palavras:
            achado = next((i for i, raizes in enumerate(assuntos) if any(p.startswith(r) for r in raizes)), None)
            if achado is not None:
                v[achado] += 1.0
            elif len(p) >= 3 and self.dimensoes > len(assuntos):
                outras.add(p)
        for p in outras:
            v[len(assuntos) + int(hashlib.md5(p.encode()).hexdigest(), 16) % resto] += 0.3
        return v

    async def vetorizar(self, textos: list[str]) -> vetores.Vetorizado:
        self.chamadas += 1
        self.textos += textos
        tokens = sum(max(1, len(t) // 4) for t in textos)
        return vetores.Vetorizado([self.vetor(t) for t in textos], tokens, vetores.custo(tokens, self.modelo))


class VetorizadorQuebrado(VetorizadorAssuntos):
    async def vetorizar(self, textos):
        raise RuntimeError("provedor fora do ar")


def _item(fonte, titulo, resposta, papeis=()):
    chave = "pergunta" if fonte == "faq" else "objecao"
    return {chave: titulo, "resposta": resposta, **({"papeis": list(papeis)} if papeis else {})}


FAQ_GRANDE = [
    _item("faq", "Quanto o escritório cobra?", "Os honorários são de 30% do retroativo, só no êxito. " + "Detalhe. " * 30),
    _item("faq", "Quais documentos preciso mandar?", "RG ou CNH, comprovante de residência e laudos. " + "Detalhe. " * 30,
          papeis=["contratos"]),
    _item("faq", "Quanto tempo demora?", "Em média de 6 a 12 meses no INSS. " + "Detalhe. " * 30),
    _item("faq", "Como assino pelo celular?", "Abra o link do ZapSign no celular e siga os passos. " + "Detalhe. " * 30,
          papeis=["assinatura"]),
] + [_item("faq", f"Pergunta genérica número {i} sobre rotina", "Resposta genérica de rotina interna. " + "Detalhe. " * 30)
     for i in range(8)]
OBJECOES = [_item("objecao", "Isso é golpe?", "Somos escritório com OAB ativa; você pode conferir no site da OAB.",
                  papeis=["closer"])]


def candidatos_com_vetor(vet: VetorizadorAssuntos, papel=None, conhecimento=None):
    conhecimento = conhecimento or {"faq": FAQ_GRANDE, "objecoes": OBJECOES}
    itens = base.itens_da_config(conhecimento)
    indexados = [{**i, "id": f"t{n}", "hash": vetores.hash_do_texto(vet.modelo, i["conteudo"]), "vetor": vet.vetor(i["conteudo"])}
                 for n, i in enumerate(itens)]
    return indice.preparar(conhecimento, papel, indexados=indexados, modelo_vetor=vet.modelo)


# ---------------------------------------------------------------------------- quando consultar e o texto da consulta
@pytest.mark.parametrize("falas, consulta", [
    (["oi bom dia"], False), (["ok"], False), (["sim"], False), (["2019"], False), (["obrigada!"], False),
    (["quanto vocês cobram?"], True), (["precisa ir aí?"], True), (["tenho medo de ser golpe"], True),
    (["e se eu perder?"], True), (["e se eu perder"], False),
])
def test_filtro_local_decide_se_consulta(falas, consulta):
    assert base.precisa_consultar(falas) is consulta


def test_consulta_usa_a_fala_nova_e_a_ultima_pergunta_da_ia_so_quando_a_fala_e_curta():
    historico = [{"autor": "lead", "texto": "sofri um acidente de moto em 2020"},
                 {"autor": "você", "texto": "Entendi. Você ficou com alguma sequela no braço?"}]
    pergunta = base.ultima_pergunta_da_ia(historico)
    assert pergunta == "Entendi. Você ficou com alguma sequela no braço?"
    curta = base.montar_consulta(["e quanto é?"], pergunta)
    assert curta.startswith("Entendi. Você ficou") and curta.endswith("e quanto é?")
    longa = base.montar_consulta(["quero saber quanto o escritório cobra de honorários no final"], pergunta)
    assert longa == "quero saber quanto o escritório cobra de honorários no final"
    assert "moto" not in curta                               # histórico antigo nunca entra
    assert base.ultima_pergunta_da_ia([{"autor": "você", "texto": "Certo, vou verificar."}]) is None


# ---------------------------------------------------------------------------- trechos e prompt
def test_dividir_com_titulo_e_tamanho():
    texto = "# Contrato padrão\n\n" + "Cláusula de honorários. " * 60 + "\n\n## Documentos necessários\n\n" + "RG e comprovante. " * 80
    trechos = base.dividir_com_titulo("Contrato.pdf", texto)
    assert len(trechos) >= 3 and all(len(t) <= base.TAMANHO_TRECHO + 80 for _, t in trechos)
    assert all(t.startswith("Documento: Contrato.pdf") for _, t in trechos)
    assert trechos[0][0] == "Contrato.pdf > Contrato padrão"
    assert trechos[-1][0] == "Contrato.pdf > Documentos necessários"


def test_bloco_numerado_com_fonte_e_nada_encontrado():
    trechos = [base.Trecho("FAQ", "Pergunta: Quanto cobra?\nResposta: 30%.", "faq", "Quanto cobra?"),
               base.Trecho("Contrato.pdf", "Documento: Contrato.pdf > Documentos\nRG e comprovante.", "documento", "Contrato.pdf > Documentos")]
    bloco = base.montar_bloco(trechos)
    assert bloco.startswith("BASE DE CONHECIMENTO DO ESCRITÓRIO")
    assert "[1] FAQ: Quanto cobra?" in bloco and "[2] Documento: Contrato.pdf > Documentos" in bloco
    assert "Documento: Contrato.pdf > Documentos\n    RG" in bloco                  # cabeçalho do vetor não se repete
    assert base.montar_bloco([], consultou=True) == "BASE DE CONHECIMENTO: nada encontrado para esta mensagem."
    assert base.montar_bloco([], consultou=False) == ""


def test_fixo_ou_buscado_por_papel():
    pequeno = {"dados_escritorio": "Rua A, 10.", "faq": [_item("faq", "Precisa ir aí?", "Não, é tudo online.")],
               "objecoes": OBJECOES}
    preparo = indice.preparar(pequeno, "sdr")
    assert preparo.faq_fixa and preparo.fixo["faq"] and preparo.fixo["objecoes"] == []     # a objeção é só do closer
    assert preparo.candidatos == [] and preparo.fixo["dados_escritorio"] == "Rua A, 10."
    assert indice.preparar(pequeno, "closer").fixo["objecoes"] == OBJECOES
    grande = indice.preparar({"faq": FAQ_GRANDE}, "sdr")
    assert not grande.faq_fixa and "faq" not in grande.fixo
    assert len(grande.candidatos) == len(FAQ_GRANDE) - 2            # itens de contratos e assinatura ficam fora do sdr
    dados = indice.preparar({"dados_escritorio": "Linha de dados.\n" * 200}, "sdr")
    assert len(dados.fixo["dados_escritorio"]) <= base.FIXO_DADOS and dados.candidatos   # o excedente vai para a busca


# ---------------------------------------------------------------------------- busca por vetor: escopo e cortes
async def test_escopo_por_papel_na_busca():
    vet = VetorizadorAssuntos()
    sdr = await indice.buscar(candidatos_com_vetor(vet, "sdr").candidatos, ["quais documentos tenho que mandar?"],
                              papel="sdr", vetorizador=vet)
    assert sdr.modo == "vetor" and all("RG ou CNH" not in t.texto for t in sdr.trechos)
    contratos = await indice.buscar(candidatos_com_vetor(vet, "contratos").candidatos, ["quais documentos tenho que mandar?"],
                                    papel="contratos", vetorizador=vet)
    assert contratos.trechos and "RG ou CNH" in contratos.trechos[0].texto and contratos.trechos[0].nota is not None
    closer = await indice.buscar(candidatos_com_vetor(vet, "closer").candidatos, ["tenho medo de ser golpe"],
                                 papel="closer", vetorizador=vet)
    assert [t.fonte for t in closer.trechos] == ["objecao"]
    nada = await indice.buscar(candidatos_com_vetor(vet, "sdr").candidatos, ["meu cachorro fugiu ontem"], papel="sdr", vetorizador=vet)
    assert nada.consultou and nada.trechos == []


def _trecho(doc, texto, vetor):
    return {"documento": doc, "conteudo": texto, "vetor": vetor, "fonte": "documento", "papeis": [], "id": texto[:8]}


def test_cortes_absoluto_relativo_quantos_por_documento_e_teto():
    consulta = [1.0, 0.0]
    trechos = [_trecho("A", "a1" * 10, [1.0, 0.05]), _trecho("A", "a2" * 10, [1.0, 0.1]), _trecho("A", "a3" * 10, [1.0, 0.12]),
               _trecho("B", "b1" * 10, [1.0, 0.3]), _trecho("C", "c1" * 10, [0.2, 1.0])]
    escolhidos = indice.escolher_por_vetor(trechos, consulta, minimo=0.35, relativo=0.8, quantos=4, por_documento=2, teto=3500)
    assert [t.documento for t in escolhidos] == ["A", "A", "B"]                   # 2 por documento; C abaixo do mínimo
    assert escolhidos[0].nota >= escolhidos[1].nota >= escolhidos[2].nota
    assert indice.escolher_por_vetor(trechos, consulta, minimo=0.999, relativo=0.8) == []        # corte absoluto
    so_os_melhores = indice.escolher_por_vetor(trechos, consulta, minimo=0.0, relativo=0.99, por_documento=4)
    assert {t.documento for t in so_os_melhores} == {"A"}                                       # corte relativo
    assert len(indice.escolher_por_vetor(trechos, consulta, minimo=0.0, relativo=0.0, quantos=2, por_documento=9)) == 2
    assert len(indice.escolher_por_vetor(trechos, consulta, minimo=0.0, relativo=0.0, por_documento=9, teto=45)) == 2   # teto


def test_limites_configuraveis_por_agente():
    assert indice.limites({}) == {"teto": 3500, "quantos": 4, "minimo": vetores.LIMIAR_MINIMO}
    assert indice.limites({"teto_documentos": 99999, "trechos_por_turno": 2, "nota_minima": 0.5}) == {
        "teto": base.TETO_MAXIMO, "quantos": 2, "minimo": 0.5}


async def test_dimensao_diferente_e_falha_caem_na_busca_por_palavras():
    vet = VetorizadorAssuntos()
    preparo = candidatos_com_vetor(vet, "sdr")
    menor = VetorizadorAssuntos(dimensoes=4)                       # índice feito com outro modelo/dimensão
    busca = await indice.buscar(preparo.candidatos, ["quanto vocês cobram de honorários?"], papel="sdr", vetorizador=menor)
    assert busca.dimensao_diferente and busca.modo == "palavras" and menor.chamadas == 0
    assert busca.trechos and "30%" in busca.trechos[0].texto
    quebrado = await indice.buscar(preparo.candidatos, ["quanto vocês cobram de honorários?"], papel="sdr",
                                   vetorizador=VetorizadorQuebrado())
    assert quebrado.modo == "palavras" and quebrado.erro and quebrado.trechos
    assert quebrado.chamada is not None and not quebrado.chamada.sucesso
    falso = await indice.buscar(preparo.candidatos, ["quanto vocês cobram de honorários?"], papel="sdr",
                                vetorizador=vetores.VetorizadorFalso())
    assert falso.modo == "palavras" and falso.chamada is None      # modo falso: direto para palavras


async def test_cache_de_consulta_e_reaproveitamento_por_hash():
    vet = VetorizadorAssuntos()
    cache = vetores.CacheDeConsultas()
    preparo = candidatos_com_vetor(vet, "sdr")
    assert all(c.get("vetor") for c in preparo.candidatos)           # vetor do índice, pelo hash: nada a vetorizar
    primeira = await indice.buscar(preparo.candidatos, ["Quanto vocês cobram?"], papel="sdr", vetorizador=vet, cache=cache)
    segunda = await indice.buscar(preparo.candidatos, ["quanto   vocês cobram?"], papel="sdr", vetorizador=vet, cache=cache)
    assert vet.chamadas == 1 and primeira.chamada is not None and segunda.chamada is None
    assert [t.texto for t in primeira.trechos] == [t.texto for t in segunda.trechos]
    # FAQ editada: só o item novo fica sem vetor (os outros mantêm o hash e o vetor).
    editada = [dict(f) for f in FAQ_GRANDE]
    editada[2] = {**editada[2], "resposta": "Agora a média é de 8 meses."}
    itens_antigos = base.itens_da_config({"faq": FAQ_GRANDE})
    indexados = [{**i, "hash": vetores.hash_do_texto(vet.modelo, i["conteudo"]), "vetor": vet.vetor(i["conteudo"])} for i in itens_antigos]
    novo = indice.preparar({"faq": editada}, "sdr", indexados=indexados, modelo_vetor=vet.modelo)
    assert sum(1 for c in novo.candidatos if not c.get("vetor")) == 1
    cache_pequeno = vetores.CacheDeConsultas(maximo=2)
    for i in range(3):
        cache_pequeno.guardar("m", f"consulta {i}", [float(i)])
    assert len(cache_pequeno) == 2 and cache_pequeno.pegar("m", "consulta 0") is None


# ---------------------------------------------------------------------------- guarda de fonte
def test_valor_porcentagem_ou_prazo_sem_fonte():
    fontes = ["Honorários: 30% do retroativo. Salário mínimo R$ 1.621,00.", "Prazo médio de seis meses."]
    assert base.fato_sem_fonte(["Cobramos 30% só no êxito."], fontes) is None
    assert base.fato_sem_fonte(["O salário mínimo é R$ 1.621,00."], fontes) is None
    assert base.fato_sem_fonte(["Demora uns 6 meses."], fontes) is None
    assert base.fato_sem_fonte(["Cobramos 40% do retroativo."], fontes) == "40%"
    assert base.fato_sem_fonte(["Sai em 90 dias."], fontes) == "90 dias"
    assert base.fato_sem_fonte(["A taxa é R$ 500,00."], fontes) == "R$ 500,00"


# ---------------------------------------------------------------------------- o turno inteiro (catálogo)
def _resposta(texto, usados=(), sem_resposta=""):
    return {"mensagens": [{"texto": texto}], "transferir_para": "", "ferramenta": "",
            "base": {"usados": list(usados), "sem_resposta": sem_resposta}}


async def test_turno_com_vetor_poe_o_bloco_no_conteudo_e_o_custo_no_consumo():
    atendimento, repo, helena, modelo = montar_catalogo(lambda s, c: _resposta("São 30% do retroativo, só no êxito.", [1]))
    agente = repo.agentes["canal-1"]
    agente.config["conhecimento"] = {"dados_escritorio": "Sousa Teste Advogados, Rua das Flores, 100.",
                                     "faq": FAQ_GRANDE, "objecoes": OBJECOES}
    vet = VetorizadorAssuntos()
    itens = base.itens_da_config(agente.config["conhecimento"])
    repo.__dict__.setdefault("trechos", {})["ag-1"] = [
        {**i, "id": f"t{n}", "hash": vetores.hash_do_texto(vet.modelo, i["conteudo"]), "vetor": vet.vetor(i["conteudo"])}
        for n, i in enumerate(itens)]
    atendimento.vetorizador = vet
    await atendimento.receber(webhook("quanto vocês cobram de honorários?"))
    await atendimento.aguardar_esperas()
    assert helena.enviadas == ["São 30% do retroativo, só no êxito."]
    pedido = next(p for p in modelo.pedidos if p["papel"] == "etapa")
    assert "# FATOS DO ESCRITÓRIO: DE ONDE PODEM VIR" in pedido["sistema"]           # regra fixa no sistema
    assert "Quanto o escritório cobra?" not in pedido["sistema"]                      # FAQ grande não vai fixa
    assert "Sousa Teste Advogados" in pedido["sistema"]                               # dados do escritório ficam fixos
    conteudo = pedido["conteudo"]
    assert "[1] FAQ: Quanto o escritório cobra?" in conteudo
    assert conteudo.index("BASE DE CONHECIMENTO DO ESCRITÓRIO") < conteudo.index("MENSAGENS NOVAS DO LEAD")
    assert "base" in pedido["esquema"]["properties"] and "base" in pedido["esquema"]["required"]
    turno = next(iter(repo.turnos.values()))
    registro = turno["contexto"]["conhecimento"]
    assert registro["consultou"] and registro["modo"] == "vetor" and registro["usados"] == [1]
    assert registro["trechos"][0]["fonte"] == "faq" and registro["trechos"][0]["nota"] > vetores.LIMIAR_MINIMO
    consulta = [c for c in repo.chamadas if c["papel"] == "conhecimento_consulta"]
    assert len(consulta) == 1 and consulta[0]["custo_usd"] > 0 and consulta[0]["modelo"] == "emb-teste"
    assert vet.textos == ["quanto vocês cobram de honorários?"]                      # só a fala nova do lead


async def test_saudacao_nao_consulta_e_nao_poe_bloco():
    atendimento, repo, _helena, modelo = montar_catalogo(lambda s, c: _resposta("Oi! Me conta o que aconteceu?"))
    repo.agentes["canal-1"].config["conhecimento"] = {"faq": FAQ_GRANDE}
    vet = VetorizadorAssuntos()
    atendimento.vetorizador = vet
    await atendimento.receber(webhook("oi, bom dia"))
    await atendimento.aguardar_esperas()
    conteudo = next(p for p in modelo.pedidos if p["papel"] == "etapa")["conteudo"]
    assert "BASE DE CONHECIMENTO" not in conteudo and vet.chamadas == 0
    assert next(iter(repo.turnos.values()))["contexto"]["conhecimento"]["modo"] == "pulou"


async def test_pergunta_sem_resposta_vira_lacuna_e_evento_e_soma():
    resposta = _resposta("Vou confirmar com a equipe e te retorno. Você ficou com sequela?",
                         sem_resposta="Tem estacionamento no escritório?")
    atendimento, repo, _helena, modelo = montar_catalogo(lambda s, c: resposta)
    repo.agentes["canal-1"].config["conhecimento"] = {"faq": FAQ_GRANDE}
    await atendimento.receber(webhook("vocês têm estacionamento pra carro?"))
    await atendimento.aguardar_esperas()
    conteudo = next(p for p in modelo.pedidos if p["papel"] == "etapa")["conteudo"]
    assert "BASE DE CONHECIMENTO: nada encontrado para esta mensagem." in conteudo     # consultou (palavras) e nada passou
    assert [l["vezes"] for l in repo.lacunas] == [1] and repo.lacunas[0]["papel"] == "sdr"
    assert any(e["tipo"] == "pergunta_sem_resposta" and e["responsavel"] == "cadastro" for e in repo.eventos)
    await atendimento.receber(webhook("e estacionamento, tem?"))
    await atendimento.aguardar_esperas()
    assert [l["vezes"] for l in repo.lacunas] == [2]                                   # mesma dúvida aberta soma


async def test_valor_inventado_e_refeito_uma_vez():
    respostas = [_resposta("A consulta custa R$ 200,00."), _resposta("Vou confirmar o valor com a equipe.", sem_resposta="valor da consulta")]
    atendimento, repo, helena, modelo = montar_catalogo(respostas)
    repo.agentes["canal-1"].config["conhecimento"] = {"faq": [_item("faq", "Cobra consulta?", "Não, a análise é gratuita.")]}
    await atendimento.receber(webhook("quanto custa a consulta?"))
    await atendimento.aguardar_esperas()
    assert helena.enviadas == ["Vou confirmar o valor com a equipe."]
    segunda = [p for p in modelo.pedidos if p["papel"] == "etapa"][1]
    assert "CORRIJA" in segunda["conteudo"] and "R$ 200,00" in segunda["conteudo"]


def test_base_desligada_nao_muda_o_prompt_antigo():
    """Entrada montada sem o pipeline (testes antigos, laboratório antigo): sem regra, sem campo base."""
    from app.cerebro import agente

    assert "FATOS DO ESCRITÓRIO" not in agente.montar_conhecimento({"faq": [_item("faq", "a?", "b")]})
    esquema = {"type": "object", "properties": {"mensagens": {}}, "required": ["mensagens"]}
    assert base_conhecimento.com_base(esquema, {"faq": []}) is esquema


# ---------------------------------------------------------------------------- revisão: falhas, ruído e guarda pela unidade
class VetorizadorLento(VetorizadorAssuntos):
    async def vetorizar(self, textos):
        import asyncio
        await asyncio.sleep(30)                                     # provedor travado (o cliente esperaria até 10 min)
        return await super().vetorizar(textos)


async def test_embedding_lento_cai_para_palavras_sem_segurar_o_turno():
    import time

    vet = VetorizadorAssuntos()
    preparo = candidatos_com_vetor(vet, "sdr")
    inicio = time.monotonic()
    busca = await indice.buscar(preparo.candidatos, ["quanto vocês cobram de honorários?"], papel="sdr",
                                vetorizador=VetorizadorLento(), tempo_maximo_s=0.05)
    assert time.monotonic() - inicio < 2
    assert busca.modo == "palavras" and "passou de" in busca.erro and busca.trechos
    assert busca.chamada is not None and not busca.chamada.sucesso


async def test_banco_da_base_fora_do_ar_nao_derruba_o_turno():
    atendimento, repo, helena, modelo = montar_catalogo(lambda s, c: _resposta("Não, é tudo online. Você ficou com sequela?"))
    repo.agentes["canal-1"].config["conhecimento"] = {"faq": [_item("faq", "Precisa ir aí?", "Não, é tudo online.")]}

    async def quebrado(*_a, **_k):
        raise RuntimeError("relation agentesia_documento_trechos.papeis does not exist")

    repo.trechos_do_agente = quebrado
    await atendimento.receber(webhook("precisa ir aí no escritório?"))
    await atendimento.aguardar_esperas()
    assert helena.enviadas == ["Não, é tudo online. Você ficou com sequela?"]
    sistema = next(p for p in modelo.pedidos if p["papel"] == "etapa")["sistema"]
    assert "Precisa ir aí?" in sistema                               # a FAQ da config segue no prompt, como antes


def test_faq_curta_mas_numerosa_vai_para_a_busca_em_vez_de_ser_cortada():
    muitas = [_item("faq", f"Atende em {i}?", "Sim.") for i in range(indice.FIXO_MAX_FAQ + 5)]
    preparo = indice.preparar({"faq": muitas}, "sdr")
    assert sum(len(i["conteudo"]) for i in base.itens_da_config({"faq": muitas})) <= base.FIXO_FAQ_OBJECOES
    assert not preparo.faq_fixa and len(preparo.candidatos) == len(muitas)     # antes: as 5 últimas sumiam do prompt


def test_busca_por_palavras_nao_traz_trecho_que_so_divide_uma_palavra_comum():
    conhecimento = {"faq": FAQ_GRANDE + [_item("faq", "Quanto tempo demora o processo?", "Uns meses.")], "objecoes": OBJECOES}
    itens = base.itens_da_config(conhecimento)
    pericia = "meu processo no INSS ficou parado, o que faço com a perícia marcada?"
    assert base.escolher_por_palavras(itens, pericia, cobertura=0.0)          # sem o mínimo, entrava ruído
    assert base.escolher_por_palavras(itens, pericia) == []
    assert [t.titulo for t in base.escolher_por_palavras(itens, "quais documentos preciso mandar?")] == [
        "Quais documentos preciso mandar?"]


def test_guarda_pela_unidade_e_nao_por_qualquer_numero_do_prompt():
    fontes = ["Roteiro: faça no máximo 6 perguntas. Etapa 2 de 4. Honorários: 30% do retroativo.",
              "O processo leva de 8 a 12 meses no INSS."]
    assert base.fato_sem_fonte(["O processo demora uns 6 meses."], fontes) == "6 meses"       # o "6" do roteiro não vale
    assert base.fato_sem_fonte(["Demora seis meses."], fontes) == "6 meses"                  # por extenso também
    assert base.fato_sem_fonte(["Leva entre 8 e 12 meses."], fontes) is None                 # faixa da fonte
    assert base.fato_sem_fonte(["Cobramos 2% ao mês."], fontes) == "2%"                      # "2" existe, "2%" não
    assert base.fato_sem_fonte(["São trinta por cento."], fontes) is None
    # O lead não "confirma" porcentagem perguntando; mas a idade e o salário dele valem.
    assert base.fato_sem_fonte(["Sim, cobramos 10%."], fontes, ["vocês cobram só 10%?"]) == "10%"
    assert base.fato_sem_fonte(["Com 45 anos e salário de R$ 1.800,00, dá para pedir."], fontes,
                               ["tenho 45, ganho 1800"]) is None


def test_fala_antiga_da_ia_nao_vira_fonte_do_proprio_valor():
    from types import SimpleNamespace

    entrada = SimpleNamespace(conhecimento={"base": True}, novas=["e a taxa?"], honorarios="30% do retroativo",
                              historico=[{"autor": "lead", "texto": "quanto custa?"},
                                         {"autor": "você", "texto": "Tem uma taxa de R$ 350,00 na entrada."}], fatos={})
    linhas = "CONVERSA ATÉ AQUI:\nlead: quanto custa?\nvocê: Tem uma taxa de R$ 350,00 na entrada.\n\nMENSAGENS NOVAS DO LEAD:\n- e a taxa?"
    orientacao = base_conhecimento.guarda_de_fonte(entrada, ["A taxa é de R$ 350,00."], "SISTEMA sem valores", linhas)
    assert orientacao and "R$ 350,00" in orientacao
    entrada.historico[1] = {"autor": "atendente", "texto": "Tem uma taxa de R$ 350,00 na entrada."}   # a equipe disse: vale
    linhas = linhas.replace("você:", "atendente:")
    assert base_conhecimento.guarda_de_fonte(entrada, ["A taxa é de R$ 350,00."], "SISTEMA sem valores", linhas) is None
