"""Agente ENXUTO do Sousa e Costa (avaliacao/agentes/sousa_costa_enxuto.json): provas estruturais, sem API.

É o corrigido (sousa_costa_corrigido.json) com a instrução de cada papel trocada por
avaliacao/agentes/sousa_costa_enxuto/<papel>.md, no formato dos modelos enxutos do dono: o campo tem só o roteiro do
escritório (contexto, objetivo, perguntas, textos exatos, decisões "→ @Agente X" / "→ @Análise da equipe", mídias e
variáveis {{...}}). Tudo o que é técnico é regra fixa do motor (tests/test_regras_do_motor.py). Aqui se prova:
config igual ao corrigido (fora variables e as mensagens de entrada do Closer e do Desqualificado); nenhuma regra
técnica nos .md; cada frase de troca chega ao modelo pela regra do motor; variáveis todas preenchidas pelo motor;
mídias sem invenção; as correções de ROTEIRO das rodadas de 25/11/2026 continuam; montagem pela avaliação.
"""

import copy
import json
import re
from pathlib import Path

import pytest

from app.avaliacao import cenario, falso, montagem
from app.cerebro import catalogo, travas
from tests.test_avaliacao_sousa_costa import roteiro_01

CORRIGIDO = cenario.PASTA_AGENTES / "sousa_costa_corrigido.json"
ENXUTO = cenario.PASTA_AGENTES / "sousa_costa_enxuto.json"
PASTA_MD = cenario.PASTA_AGENTES / "sousa_costa_enxuto"
PAPEIS = ["sdr", "periododegraca", "closer", "contratos", "assinatura", "desqualificado"]
URL = re.compile(r"https?://[^\s\"'<>)\]]+")
VARIAVEL = re.compile(r"\{\{\s*[^{}\s][^{}]*\}\}")
MIDIA = "https://mqkgzkzlysvwjjuwvxul.supabase.co/storage/v1/object/public/midia/"
# Texto técnico que é do motor, nunca do campo do cliente (o aviso do painel usa a mesma ideia).
TECNICO = ("transferir_para", "json", "acione", "acionar", "tool", "ferramenta", "(sistema)", "notificacao",
           "notificação", "analise_humana", "zapsign", "buscar_cep", "buscar cep", "\\n", "exemplo literal",
           "nota interna", "link_documentos", "link_assinatura", "fatos do sistema", "dados já informados",
           "conversa até aqui", "mensagem de entrada", "frase de troca", "frase de passagem", "vou calcular")


def carregar(caminho):
    return json.loads(Path(caminho).read_text(encoding="utf-8"))


def instrucoes(snap):
    return {e["codigo"]: e["instrucao"] for e in snap["agente"]["etapas"]}


def links(texto):
    return {u.rstrip(".,;:") for u in URL.findall(texto or "")}


def valores(snap):
    agente, config = snap["agente"], snap["agente"]["config"]
    return catalogo.valores_das_variaveis(agente["nome"], snap["escritorio"]["nome"], config.get("honorarios"), config)


def sistema_do_papel(snap, papel):
    """O sistema como o turno do catálogo monta (destinos do config + chips do roteiro, ações do mapa do papel)."""
    config = snap["agente"]["config"]
    produto = catalogo.carregar(config)
    papeis = catalogo.papeis_com_variaveis(config["catalogo"]["papeis"], valores(snap))
    prompt = instrucoes(snap)[papel]
    do_prompt, acoes = catalogo.ferramentas_do_prompt(prompt)
    destinos = [d for d in dict.fromkeys(papeis[papel]["destinos"] + do_prompt) if d != papel]
    ferramentas = produto.ferramentas_do_papel(papel)
    return catalogo.montar_sistema(
        prompt=prompt, nome_agente=snap["agente"]["nome"], escritorio=snap["escritorio"]["nome"],
        conhecimento_texto="", regras=None, destinos=destinos, acoes=list(dict.fromkeys(acoes + ferramentas["acoes"])),
        fatos_sistema={}, notificacoes=("analise_humana",) if ferramentas["notificacao"] else (), papel=papel,
        ferramentas=ferramentas, papeis=papeis, honorarios=config.get("honorarios"), variaveis=valores(snap))


def test_enxuto_tem_os_seis_papeis_com_o_modelo_pedido():
    snap = carregar(ENXUTO)
    agente, config = snap["agente"], snap["agente"]["config"]
    assert agente["id"] == "agente-sousa-costa-enxuto" and "enxuta" in snap["origem"].lower()
    assert snap["escritorio"]["nome"] == "Sousa e Costa Advogados" and agente["nome"] == "Ana"
    assert agente["produto"] == "catalogo" and list(config["catalogo"]["papeis"]) == PAPEIS
    assert config["temperatura"] == 0.5
    assert config["modelos"] == {"etapa": "gpt-4.1-mini", "extrator": "gpt-4.1-mini", "auditor": "gpt-4.1-mini"}
    etapas = {e["codigo"]: e for e in agente["etapas"]}
    assert list(etapas) == PAPEIS + ["contrato_assinado"]
    assert all(etapas[p]["modelo"] == "gpt-4.1-mini" and etapas[p]["instrucao"].strip() for p in PAPEIS)


def test_so_as_instrucoes_as_variaveis_e_duas_mensagens_de_entrada_mudaram():
    corrigido, novo = carregar(CORRIGIDO), carregar(ENXUTO)
    for papel, texto in instrucoes(novo).items():
        if papel in PAPEIS:
            assert texto == (PASTA_MD / f"{papel}.md").read_text(encoding="utf-8"), papel
    papeis = novo["agente"]["config"]["catalogo"]["papeis"]
    assert papeis["closer"]["mensagem_troca"].endswith("Posso te explicar como funciona o Auxílio-Acidente?")
    assert papeis["desqualificado"]["mensagem_troca"].startswith(
        corrigido["agente"]["config"]["catalogo"]["papeis"]["desqualificado"]["mensagem_troca"])
    assert novo["agente"]["config"]["variables"] == {"LINK AVALIACAO GOOGLE": "https://g.page/r/CVq6HvUsPt0IEBM/review"}
    a, b = copy.deepcopy(corrigido), copy.deepcopy(novo)
    for x in (a, b):
        x["origem"], x["agente"]["id"] = "", ""
        x["agente"]["config"].pop("variables", None)
        for papel in ("closer", "desqualificado"):
            x["agente"]["config"]["catalogo"]["papeis"][papel]["mensagem_troca"] = ""
        for e in x["agente"]["etapas"]:
            e["instrucao"] = ""
    assert a == b


@pytest.mark.parametrize("papel", PAPEIS)
def test_nenhuma_regra_tecnica_no_campo_do_cliente(papel):
    texto = (PASTA_MD / f"{papel}.md").read_text(encoding="utf-8")
    baixo = texto.lower()
    for termo in TECNICO:
        assert termo not in baixo, (papel, termo)
    assert "```" not in texto and '{"' not in texto and "[[" not in texto      # sem exemplo JSON nem marcador cru
    assert len(texto) < 9000, (papel, len(texto))                               # enxuto de verdade
    # O que sobra de "técnico" é só o chip de decisão, que o motor lê.
    chips = ("Agente SDR", "Agente Closer", "Agente Contratos", "Agente Desqualificado", "Agente Período de Graça",
             "Análise da equipe")
    for achado in re.finditer("@", texto):
        assert texto[achado.end():].startswith(chips), (papel, texto[achado.start():achado.start() + 30])


def test_decisoes_do_roteiro_batem_com_os_destinos():
    snap = carregar(ENXUTO)
    papeis = snap["agente"]["config"]["catalogo"]["papeis"]
    for papel, texto in instrucoes(snap).items():
        if not texto:
            continue
        destinos, acoes = catalogo.ferramentas_do_prompt(texto)
        permitidos = set(papeis[papel]["destinos"]) | ({"sdr"} if papel == "desqualificado" else set())  # volta 1x
        assert set(destinos) - {papel} <= permitidos, (papel, destinos)
        assert acoes == [], (papel, acoes)                                        # ferramentas são do mapa do papel
    assert catalogo.pede_analise_da_equipe(instrucoes(snap)["periododegraca"])


def test_cada_frase_de_troca_chega_ao_modelo_pela_regra_do_motor():
    snap = carregar(ENXUTO)
    papeis = snap["agente"]["config"]["catalogo"]["papeis"]
    md = instrucoes(snap)
    for origem in PAPEIS:
        sistema = sistema_do_papel(snap, origem)
        for destino in papeis[origem]["destinos"]:
            frase = " ".join(papeis[destino]["mensagem_troca"].split())
            assert frase not in " ".join(md[origem].split()), (origem, destino)       # não está no campo do cliente...
            assert f'= "{destino}": "{frase}"' in sistema, (origem, destino)        # ...chega pelo motor
        if frase_propria := papeis[origem].get("mensagem_troca"):
            assert " ".join(frase_propria.split()) in sistema and "Começo desta etapa" in sistema, origem


def test_variaveis_todas_preenchidas_pelo_motor():
    snap = carregar(ENXUTO)
    usadas = {catalogo.chave_da_variavel(v[2:-2]) for t in instrucoes(snap).values() for v in VARIAVEL.findall(t)}
    assert usadas == {"NOME AGENTE", "NOME ESCRITORIO", "HONORARIOS", "LINK AVALIACAO GOOGLE"}
    assert catalogo.variaveis_sem_valor(list(instrucoes(snap).values()), valores(snap)) == []
    for papel in PAPEIS:
        sistema = sistema_do_papel(snap, papel)
        assert not VARIAVEL.search(sistema), papel
        assert sistema.startswith(instrucoes(snap)[papel].split("{{")[0]) and "Ana" in sistema, papel
    closer, desq = sistema_do_papel(snap, "closer"), sistema_do_papel(snap, "desqualificado")
    assert "Honorários: 5 salários do benefício aprovado" in closer and "# HONORÁRIOS DO ESCRITÓRIO" in closer
    assert "https://g.page/r/CVq6HvUsPt0IEBM/review" in desq
    # A avaliação (modelo roteirizado e checagens) troca igual ao motor: o papel do sistema é reconhecido.
    modelo = falso.ModeloRoteirizado(snap, {})
    assert all(modelo.papel_do_sistema(sistema_do_papel(snap, p)) == p for p in PAPEIS)


def test_midias_sem_invencao_e_as_do_roteiro_no_lugar():
    corrigido, novo = instrucoes(carregar(CORRIGIDO)), instrucoes(carregar(ENXUTO))
    todas = set().union(*(links(t) for t in corrigido.values()))
    for papel in PAPEIS:
        assert links(novo[papel]) <= todas, papel                                    # nenhum link inventado
    esperadas = {"sdr": ["PTV.mp4"], "closer": ["Como%20Funciona%20o%20Auxilio%20Acidente.ogg",
                                                "video-honorarios-5salarios.mp4"],
                 "contratos": ["PedidoDocumento.mp4"], "desqualificado": ["Diversos-outros-beneficioss.jpeg"]}
    for papel, arquivos in esperadas.items():
        for arquivo in arquivos:
            assert MIDIA + arquivo in novo[papel], (papel, arquivo)
    # O áudio "como funciona" é da ETAPA 1 do Closer: o SDR e o Período de Graça não o mandam (saía duas vezes).
    assert "Como%20Funciona" not in novo["sdr"] and "Como%20Funciona" not in novo["periododegraca"]


def test_correcoes_de_roteiro_continuam():
    md = instrucoes(carregar(ENXUTO))
    sdr, pg, closer, contratos, assinatura, desq = (md[p] for p in PAPEIS)
    # SDR: ano obrigatório com saída para "não sei", respostas que já contam, MEI não é trava, advogado sem presumir.
    assert "Obrigatória" in sdr and "Mais ou menos em que ano foi?" in sdr and "terceira vez" in sdr
    assert "RESPOSTAS QUE JÁ CONTAM" in sdr and "encostado pelo INSS" in sdr and "Sou MEI\" no presente" in sdr
    assert "Ser ou ter sido MEI" in sdr and "Não sabe → peça para verificar" in sdr
    assert sdr.index("Em que mês e ano aconteceu o acidente?") < sdr.index("qual era a sua profissão")
    # Período de Graça: data aproximada, mês uma vez, saída para "não sei", sem o termo técnico na frase ao lead.
    assert "Carteira de Trabalho Digital" in pg and "Lembra mais ou menos o mês?" in pg
    assert "ainda estava protegido pelo INSS" in pg and "Para não ter erro nas datas" in pg
    # Closer: "não sei" não é objeção, objeções sem pressão, honorários pela variável.
    assert "não são objeção" in closer and "{{HONORARIOS}}" in closer
    assert "continuar com a sequela" not in closer
    assert all(f"OBJ {n} " in closer for n in range(1, 11))
    # FAQ de imprimir corrigida (o fiel mandava imprimir e mandar foto).
    for papel in PAPEIS:
        assert "é necessário imprimir" not in md[papel] and "enviar a foto para nossa equipe" not in md[papel]
    assert "Não precisa imprimir nada" in assinatura and "Não precisa imprimir nada" in contratos
    # Contratos: "Buscamos nos Correios" só com o endereço encontrado; frase de geração sem prazo.
    assert "Endereço que o próprio lead digitou" in contratos
    assert "Perfeito! Estamos gerando o seu contrato." in contratos and "alguns segundos" not in contratos
    # Assinatura: no máximo 2 orientações do código, depois a equipe.
    assert "2ª vez" in assinatura and "@Análise da equipe" in assinatura
    # Desqualificado: motivo real por tabela, nunca MEI por si só; uma etapa por resposta; volta ao SDR.
    assert "o motivo real" in desq and "nunca é o motivo" in desq and "@Agente SDR" in desq
    assert "uma etapa por resposta" in desq.lower()


def test_sem_garantir_ligado_a_resultado():
    for papel, texto in instrucoes(carregar(ENXUTO)).items():
        for linha in (texto or "").splitlines():
            assert not travas.garantia_de_resultado(linha), (papel, linha)
            assert travas.trecho_de_promessa(linha) in (None, "voce tem direito") or "nunca" in linha.lower(), (papel, linha)


async def test_montagem_carrega_o_agente_enxuto():
    c = cenario.casos(["01"])[0].model_copy(update={"agente": str(Path(ENXUTO).resolve())})
    snap = c.carregar_agente()
    assert snap["agente"]["id"] == "agente-sousa-costa-enxuto"
    sim = montagem.montar(c, falso.ModeloRoteirizado(snap, roteiro_01()), snap)
    try:
        agente = sim.agente()
        assert agente.nome == "Ana" and agente.produto == "catalogo" and agente.modo == "teste"
        assert sim.etapa_do_lead() == "sdr"
        assert {e.codigo for e in agente.etapas} == set(PAPEIS) | {"contrato_assinado"}
        assert (agente.config.get("variables") or {}).get("LINK AVALIACAO GOOGLE")
    finally:
        await sim.fechar()


def test_correcoes_que_tinham_se_perdido_na_passagem_para_o_enxuto():
    md = instrucoes(carregar(ENXUTO))
    # Closer: "não sei" na pergunta da coleta é a OBJ 8 (não passa o lead para Contratos).
    assert '"não sei" ou "sei lá" é a OBJ 8' in md["closer"]
    # Closer: regra de honorários e de mídia repetida ficam só no motor (BLOCO_HONORARIOS e FORMATO).
    assert "não negocie" not in md["closer"] and "não reenvie mídia" not in md["closer"]
    # SDR: o "registrado desde o mesmo ano" tem saída para as duas respostas.
    assert "entrou depois do acidente = NÃO" in md["sdr"]
    # Desqualificado: serviços e encerramento só depois da resposta à nota.
    assert "nunca junto com o pedido da nota" in md["desqualificado"]
    assert "na mesma resposta da etapa 3" not in md["desqualificado"]


def test_assinatura_do_enxuto_sem_regra_de_zapsign_que_o_papel_nao_tem():
    snap = carregar(ENXUTO)
    sistema = sistema_do_papel(snap, "assinatura")
    assert "zapsign" not in sistema.lower()                  # papel sem a ação: dado errado vai pelo roteiro (@Análise)
    assert "vai conferir e já retorna" not in sistema
    assert "Assim que a assinatura for confirmada" in sistema    # a frase do roteiro manda no "já assinei"
