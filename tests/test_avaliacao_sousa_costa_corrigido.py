"""Agente CORRIGIDO do Sousa e Costa (avaliacao/agentes/sousa_costa_corrigido.json): provas estruturais.

É o fiel (sousa_costa.json) com a instrução de cada papel trocada por avaliacao/agentes/sousa_costa_corrigido/<papel>.md,
feita a partir dos erros e micro-alucinações das rodadas de 25/11/2026 (ver o LEIA-ME da pasta). Aqui só se prova a
estrutura: modelos, papéis e config iguais ao fiel; nada do n8n; frases de troca no prompt de quem passa; mídias;
montagem pelo motor; nenhuma promessa de resultado. A qualidade é o modo real (pago), rodado pelo usuário.
"""

import copy
import json
import re
from pathlib import Path

from app.avaliacao import cenario, falso, montagem
from app.cerebro import catalogo, travas
from tests.test_avaliacao_sousa_costa import roteiro_01

FIEL = cenario.PASTA_AGENTES / "sousa_costa.json"
CORRIGIDO = cenario.PASTA_AGENTES / "sousa_costa_corrigido.json"
PASTA_MD = cenario.PASTA_AGENTES / "sousa_costa_corrigido"
PAPEIS = ["sdr", "periododegraca", "closer", "contratos", "assinatura", "desqualificado"]
URL = re.compile(r"https?://[^\s\"'<>)\]]+")
# Única troca de mídia, de propósito (MUDANCAS_closer.md, item 8): a 2ª cópia da ETAPA 4 do Closer passou a mandar o
# vídeo "Obrigatório" (com transcrição), como a 1ª cópia, no lugar deste áudio.
MIDIA_TROCADA = "https://mqkgzkzlysvwjjuwvxul.supabase.co/storage/v1/object/public/midia/Horonarios%20AuxAcidente.ogg"


def carregar(caminho):
    return json.loads(Path(caminho).read_text(encoding="utf-8"))


def instrucoes(snap):
    return {e["codigo"]: e["instrucao"] for e in snap["agente"]["etapas"]}


def links(texto):
    return {u.rstrip(".,;:") for u in URL.findall(texto or "")}


def test_corrigido_tem_os_seis_papeis_com_o_modelo_pedido():
    snap = carregar(CORRIGIDO)
    agente, config = snap["agente"], snap["agente"]["config"]
    assert agente["id"] == "agente-sousa-costa-corrigido"
    assert "corrigida" in snap["origem"].lower() and "25/11/2026" in snap["origem"]
    assert snap["escritorio"]["nome"] == "Sousa e Costa Advogados" and agente["nome"] == "Ana"
    assert agente["produto"] == "catalogo" and list(config["catalogo"]["papeis"]) == PAPEIS
    assert config["temperatura"] == 0.5
    assert config["modelos"] == {"etapa": "gpt-4.1-mini", "extrator": "gpt-4.1-mini", "auditor": "gpt-4.1-mini"}
    etapas = {e["codigo"]: e for e in agente["etapas"]}
    assert list(etapas) == PAPEIS + ["contrato_assinado"]
    assert [c for c, e in etapas.items() if e["principal"]] == ["sdr"]
    assert all(etapas[p]["modelo"] == "gpt-4.1-mini" and etapas[p]["instrucao"].strip() for p in PAPEIS)


def test_so_as_instrucoes_mudaram_e_vieram_dos_md():
    fiel, novo = carregar(FIEL), carregar(CORRIGIDO)
    for papel, texto in instrucoes(novo).items():
        if papel in PAPEIS:
            assert texto == (PASTA_MD / f"{papel}.md").read_text(encoding="utf-8"), papel
    # Config (modelos, destinos, ações, mensagem_troca, boas-vindas, honorários, dados do escritório) idêntica ao fiel.
    a, b = copy.deepcopy(fiel), copy.deepcopy(novo)
    for x in (a, b):
        x["origem"], x["agente"]["id"] = "", ""
        for e in x["agente"]["etapas"]:
            e["instrucao"] = ""
    assert a == b


def test_nada_do_n8n_sobrou_e_destinos_e_acoes_batem():
    snap = carregar(CORRIGIDO)
    papeis = snap["agente"]["config"]["catalogo"]["papeis"]
    produto = catalogo.carregar(snap["agente"]["config"])
    for papel, texto in instrucoes(snap).items():
        if not texto:
            continue
        for antigo in ("{{", "$now", "Sistema Notificação", "jatemadvogado", "criardocumento", "BUSCARCEP", "BUSCARCPF",
                       "buscarcep", "`qualificado`", "`contrato`", "‘encerramento’"):
            assert antigo not in texto, (papel, antigo)
        destinos, acoes = catalogo.ferramentas_do_prompt(texto)
        assert set(destinos) - {papel} <= set(papeis[papel]["destinos"]), (papel, destinos)
        assert set(acoes) <= set(produto.ferramentas_do_papel(papel)["acoes"]), (papel, acoes)
    assert produto.ferramentas_do_papel("contratos")["acoes"] == ["zapsign", "buscar_cep"]
    assert produto.ferramentas_do_papel("assinatura")["acoes"] == []


def test_cada_frase_de_troca_esta_no_prompt_de_quem_passa():
    snap = carregar(CORRIGIDO)
    papeis = snap["agente"]["config"]["catalogo"]["papeis"]
    textos = instrucoes(snap)
    for origem in PAPEIS:
        for destino in papeis[origem]["destinos"]:
            frase = papeis[destino]["mensagem_troca"]
            assert frase and frase in textos[origem], (origem, destino)


def test_midias_e_dados_do_escritorio_preservados():
    fiel, novo = instrucoes(carregar(FIEL)), instrucoes(carregar(CORRIGIDO))
    todas_do_fiel = set().union(*(links(t) for t in fiel.values()))
    for papel in PAPEIS:
        assert links(fiel[papel]) - {MIDIA_TROCADA} <= links(novo[papel]), papel     # nenhum link perdido
        assert links(novo[papel]) <= todas_do_fiel, papel                            # nenhum link inventado
        if "44.326.345/0001-05" in fiel[papel]:
            assert "44.326.345/0001-05" in novo[papel], papel
        for obj in set(re.findall(r"OBJ\s*\d+", fiel[papel])):                      # objeções continuam
            assert obj.replace(" ", "") in novo[papel].replace(" ", ""), (papel, obj)
    assert "## Regras da ferramenta `zapsign`" in novo["contratos"]


def test_sem_garantir_ligado_a_resultado_fora_de_proibicao():
    for papel, texto in instrucoes(carregar(CORRIGIDO)).items():
        for linha in (texto or "").splitlines():
            if travas.garantia_de_resultado(linha):
                # Só pode aparecer na linha que PROÍBE a promessa.
                assert re.search(r"(?i)\b(nunca|nada de|n[aã]o|nem)\b", linha), (papel, linha)


def test_faq_de_imprimir_corrigida():
    fiel, novo = instrucoes(carregar(FIEL)), instrucoes(carregar(CORRIGIDO))
    assert "é necessário imprimir" in fiel["assinatura"]                   # o erro estava no fiel
    for papel in PAPEIS:
        assert "é necessário imprimir" not in novo[papel], papel
        assert "enviar a foto para nossa equipe" not in novo[papel], papel
    assert "Não precisa imprimir" in novo["assinatura"]


async def test_montagem_carrega_o_agente_corrigido():
    c = cenario.casos(["01"])[0].model_copy(update={"agente": str(Path(CORRIGIDO).resolve())})
    snap = c.carregar_agente()
    assert snap["agente"]["id"] == "agente-sousa-costa-corrigido"
    sim = montagem.montar(c, falso.ModeloRoteirizado(snap, roteiro_01()), snap)
    try:
        agente = sim.agente()
        assert agente.nome == "Ana" and agente.produto == "catalogo" and agente.modo == "teste"
        assert sim.etapa_do_lead() == "sdr"
        assert {e.codigo for e in agente.etapas} == set(PAPEIS) | {"contrato_assinado"}
        assert sim.atendimento.config.modelo_padrao == "gpt-4.1-mini"
    finally:
        await sim.fechar()
