"""Agente sob teste do Sousa e Costa (avaliacao/agentes/sousa_costa.json): carrega no motor e roda um cenário de graça.

O snapshot traz os 6 prompts reais do fluxo n8n com as conversões descritas em avaliacao/agentes/sousa_costa_NOTAS.md.
Aqui só se prova que ele monta (montagem.montar, a mesma do Laboratório) e que o cenário 01 roda do SDR à assinatura com
o modelo roteirizado, sem erro. A qualidade do prompt é o modo real (pago), rodado pelo usuário.
"""

import json
from pathlib import Path

from app.avaliacao import cenario, falso, montagem, simulador
from app.avaliacao.falso import passo
from app.cerebro import catalogo

SNAPSHOT = cenario.PASTA_AGENTES / "sousa_costa.json"
MIDIA = "https://mqkgzkzlysvwjjuwvxul.supabase.co/storage/v1/object/public/midia/"
PAPEIS = ["sdr", "periododegraca", "closer", "contratos", "assinatura", "desqualificado"]


def snapshot():
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def caso_01():
    """Cenário 01 (CLT viável até a assinatura) apontando para o agente do Sousa e Costa, como o `comparar` faz."""
    return cenario.casos(["01"])[0].model_copy(update={"agente": str(Path(SNAPSHOT).resolve())})


def roteiro_01():
    """O cenário 01 com as falas do fluxo do Sousa e Costa (frases de troca do 'Definir departamento' do n8n)."""
    papeis = snapshot()["agente"]["config"]["catalogo"]["papeis"]
    return {
        "sdr": [
            passo(MIDIA + "PTV.mp4", "Olá! Me chamo Ana, do escritório Sousa e Costa Advogados.",
                  "Me conta como aconteceu o acidente?"),
            passo("Sinto muito pelo acidente.", "Você estava trabalhando de carteira assinada (CLT) quando o acidente aconteceu?"),
            passo("Entendi.", "E ficou com alguma sequela ou limitação depois do acidente?"),
            passo("Imagino como isso atrapalha.", "Você já é aposentado?"),
            # Sem o "Só pra confirmar" do prompt: no cartão do 01, "confirm" casa antes de "advogad" (ver as notas).
            passo("Combinado.", "Você já tem um advogado atuando HOJE no seu caso de auxílio-acidente?"),
            passo(papeis["closer"]["mensagem_troca"], transferir="closer"),
        ],
        "closer": [
            passo(MIDIA + "Como%20Funciona%20o%20Auxilio%20Acidente.ogg",
                  "Os honorários são 5 salários do benefício aprovado mais 30% dos atrasados, só depois da concessão. "
                  "Nada é cobrado antes.",
                  "Vamos avançar para a formalização. Podemos seguir com a coleta dos seus dados?"),
            passo(papeis["contratos"]["mensagem_troca"], transferir="contratos"),
        ],
        "contratos": [
            passo(MIDIA + "PedidoDocumento.mp4", "Agora me informe o seu CPF, por favor."),
            passo("Qual o seu CEP e o número da casa?"),
            passo("Buscamos nos Correios e o seu endereço é: Rua Funchal, Vila Olímpia, São Paulo/SP.", "Você tem e-mail?"),
            passo("Nome: Carlos Henrique da Silva\nCPF: 200.297.727-53\nEndereço: Rua Funchal, 120, Vila Olímpia, "
                  "São Paulo/SP, CEP 04551-000", "Está tudo correto para eu gerar o contrato?"),
            passo("Perfeito! Estamos gerando o seu contrato.", ferramenta="zapsign"),
        ],
        "assinatura": [passo("Que ótimo! Vou conferir aqui e já te retorno.")],
    }


def test_snapshot_tem_os_seis_papeis_com_o_modelo_pedido():
    snap = snapshot()
    agente, config = snap["agente"], snap["agente"]["config"]
    assert snap["escritorio"]["nome"] == "Sousa e Costa Advogados" and agente["nome"] == "Ana"
    assert agente["produto"] == "catalogo" and list(config["catalogo"]["papeis"]) == PAPEIS
    assert config["temperatura"] == 0.5
    assert config["modelos"] == {"etapa": "gpt-4.1-mini", "extrator": "gpt-4.1-mini", "auditor": "gpt-4.1-mini"}
    etapas = {e["codigo"]: e for e in agente["etapas"]}
    assert list(etapas) == PAPEIS + ["contrato_assinado"]
    assert [c for c, e in etapas.items() if e["principal"]] == ["sdr"]
    assert all(etapas[p]["modelo"] == "gpt-4.1-mini" and etapas[p]["instrucao"].strip() for p in PAPEIS)


def test_prompts_convertidos_para_o_motor():
    snap = snapshot()
    papeis = snap["agente"]["config"]["catalogo"]["papeis"]
    produto = catalogo.carregar(snap["agente"]["config"])
    for etapa in snap["agente"]["etapas"]:
        texto, papel = etapa["instrucao"], etapa["codigo"]
        if not texto:
            continue
        # Nada do n8n que o motor não entende: expressão de data, tools com nome antigo, Sistema Notificação.
        for antigo in ("{{", "$now", "Sistema Notificação", "jatemadvogado", "criardocumento", "BUSCARCEP", "BUSCARCPF",
                       "`qualificado`", "`contrato`", "‘encerramento’"):
            assert antigo not in texto, (papel, antigo)
        destinos, acoes = catalogo.ferramentas_do_prompt(texto)
        # O prompt não abre destino que o agente do n8n não tinha (as seções copiadas do SDR no Closer e na Assinatura).
        assert set(destinos) - {papel} <= set(papeis[papel]["destinos"]), (papel, destinos)
        assert set(acoes) <= set(produto.ferramentas_do_papel(papel)["acoes"]), (papel, acoes)
    # Cada frase de troca está, literal, no prompt de quem passa o lead adiante.
    instrucoes = {e["codigo"]: e["instrucao"] for e in snap["agente"]["etapas"]}
    for origem, destino in (("sdr", "closer"), ("sdr", "periododegraca"), ("periododegraca", "closer"),
                            ("closer", "contratos"), ("sdr", "desqualificado")):
        assert papeis[destino]["mensagem_troca"] in instrucoes[origem], (origem, destino)
    assert produto.ferramentas_do_papel("contratos")["acoes"] == ["zapsign", "buscar_cep"]
    assert produto.ferramentas_do_papel("assinatura")["acoes"] == []          # no n8n a Assinatura não gerava contrato


async def test_montagem_carrega_o_agente_do_sousa_costa():
    c = caso_01()
    snap = c.carregar_agente()
    sim = montagem.montar(c, falso.ModeloRoteirizado(snap, roteiro_01()), snap)
    try:
        agente = sim.agente()
        assert agente.nome == "Ana" and agente.produto == "catalogo" and agente.modo == "teste"
        assert sim.etapa_do_lead() == "sdr"
        assert {e.codigo for e in agente.etapas} == set(PAPEIS) | {"contrato_assinado"}
        assert sim.atendimento.config.modelo_padrao == "gpt-4.1-mini"
    finally:
        await sim.fechar()


async def test_cenario_01_roda_com_o_roteirizado_do_sdr_a_assinatura():
    c = caso_01()
    snap = c.carregar_agente()
    modelo = falso.ModeloRoteirizado(snap, roteiro_01())
    conversa = await simulador.rodar_conversa(c, modelo, snapshot=snap)
    codigos = conversa.codigos()
    assert not codigos & {"erro_turno", "silencio", "trava_persistente", "cassete_falta"}, \
        [f.como_dict() for f in conversa.falhas]
    assert conversa.trajetoria == ["sdr", "closer", "contratos", "assinatura", "contrato_assinado"]
    assert conversa.parada == "contrato_assinado" and conversa.ferramentas["zapsign"] == 1
    assert conversa.aprovada, [f.como_dict() for f in conversa.falhas]
    etapa = [p for p in modelo.pedidos if p["papel"] == "etapa"]
    assert etapa and all(p["modelo"] == "gpt-4.1-mini" and p["temperatura"] == 0.5 for p in etapa)
    # O sistema de cada papel é o prompt real do fluxo (o roteirizado reconheceu o papel pelo começo dele).
    assert {modelo.papel_do_sistema(p["sistema"]) for p in etapa} == {"sdr", "closer", "contratos", "assinatura"}
