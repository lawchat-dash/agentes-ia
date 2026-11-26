"""Agentes do catálogo (metodologia do agents-lawchat-main): prompt por papel, transferência e ferramentas."""

from app.banco.memoria import RepositorioMemoria
from app.banco.tipos import Agente, Canal, Escritorio, Etapa
from app.cerebro import catalogo
from app.config import Configuracao
from app.modelo import ModeloFalso
from app.pipeline import Atendimento
from tests.test_pipeline import CANAL, CONTA, LEAD, HelenaFalsa, webhook

SEM_INTENCAO = {"pediu_humano": False, "pediu_para_parar": False, "engano": False, "diz_que_assinou": False, "pediu_link": False}
PROMPT_SDR = """# 1. CONTEXTO
{{NOME AGENTE}} é SDR do escritório {{NOME ESCRITORIO}}.
# 2. OBJETIVO
Qualifique. Se o caso for viável, acionar tool `closer`. Se não for, acionar tool `desqualificado`."""
PROMPT_CONTRATOS = "Peça os dados do contrato. Com a confirmação, acionar tool `zapsign`. Para o endereço, acionar tool `buscarcep`."


def test_le_ferramentas_e_destinos_do_prompt():
    assert catalogo.ferramentas_do_prompt(PROMPT_SDR) == (["closer", "desqualificado"], [])
    assert catalogo.ferramentas_do_prompt(PROMPT_CONTRATOS) == ([], ["zapsign", "buscar_cep"])
    assert catalogo.ferramentas_do_prompt("Passe para @Agente Coleta de Dados. Use @Buscar CEP.") == (["contratos"], ["buscar_cep"])


def test_balao_com_link_de_midia_vira_arquivo_e_travas():
    url = "https://ia.exemplo.com/midia/0f8fad5b-d9cb-469f-a165-70867728950e/audio/1700-explicando.ogg"
    partes = catalogo.separar_midias(["Oi! Escuta esse áudio:", url, "Qualquer dúvida me chama."])
    assert [p["tipo"] for p in partes] == ["texto", "midia", "texto"] and partes[1]["url"] == url
    assert catalogo.conferir([{"tipo": "texto", "texto": "Vou acionar tool `closer`"}])
    assert catalogo.conferir([{"tipo": "texto", "texto": "Seu caso é causa ganha!"}])
    assert catalogo.conferir([{"tipo": "texto", "texto": "Me conta o que aconteceu?"}]) == []
    papeis = {"closer": {"mensagem_troca": "Vou te passar para nossa especialista agora mesmo"}}
    assert catalogo.transferencia_pela_frase(["Certo! Vou te passar para nossa especialista agora mesmo."], ["closer"], papeis) == "closer"


# Leva 1 (B4): o lead destes turnos já respondeu o que o portão de fatos exige para passar ao Closer e a Contratos
# (como se a qualificação tivesse sido feita antes); quem testa o portão está em tests/test_leva1_motor.py.
QUALIFICADO = {"aposentado": "nao", "tem_advogado_no_caso": "nao", "sequela": "sim", "aceite_honorarios": "sim"}


def _ja_qualificado(repo):
    originais = repo.fatos_vigentes

    async def fatos_vigentes(id_lead):
        return {**QUALIFICADO, **await originais(id_lead)}

    repo.fatos_vigentes = fatos_vigentes


def montar(respostas_etapa):
    repo = RepositorioMemoria()
    escritorio = Escritorio(id="esc-1", nome="Escritório Teste", id_segredo_helena="seg-1",
                            config={"numeros_teste": [LEAD], "espera_teste_s": 0})
    canal = Canal(id="canal-1", id_escritorio="esc-1", numero_normalizado=CANAL, id_canal_helena="ch-1")
    config = {"catalogo": {"papeis": {"sdr": {"nome": "SDR", "boas_vindas": "Olá! Sou a Júlia 😊", "destinos": ["closer", "desqualificado"]},
                                      "closer": {"nome": "Closer", "destinos": ["contratos", "desqualificado"]},
                                      "contratos": {"destinos": ["assinatura", "desqualificado"]}, "assinatura": {}, "desqualificado": {}}},
              "funcoes": {"contrato_zapsign": True, "buscar_cep": False}}
    agente = Agente(id="ag-1", id_escritorio="esc-1", id_canal="canal-1", nome="Júlia", situacao="ativo", modo="teste",
                    produto="catalogo", config=config,
                    etapas=[Etapa("e-sdr", "sdr", principal=True, instrucao=PROMPT_SDR), Etapa("e-closer", "closer", instrucao="Feche."),
                            Etapa("e-contratos", "contratos", instrucao=PROMPT_CONTRATOS), Etapa("e-assinatura", "assinatura", instrucao="Ajude."),
                            Etapa("e-desq", "desqualificado", instrucao="Encerre."), Etapa("e-ok", "contrato_assinado")])
    repo.cadastrar(escritorio, canal, agente, id_conta=CONTA)
    repo.segredos["seg-1"] = "token-de-teste"
    _ja_qualificado(repo)
    cfg = Configuracao(banco_url=None, helena_url="http://helena.invalid", modelo_padrao="falso", modelo_falso=True,
                       espera_minima_s=0, espera_maxima_s=0, espera_padrao_s=0, segundos_por_letra=0, max_reprocessos=2)
    extrator = {"fatos": [], "sinais": [], "intencoes": SEM_INTENCAO}
    modelo = ModeloFalso({"extrator": extrator, "etapa": respostas_etapa})
    helena = HelenaFalsa()
    return Atendimento(repo, modelo, cfg, helena, digitar=False), repo, helena, modelo


async def test_sdr_conversa_com_o_prompt_dele_e_passa_para_o_closer():
    url = "https://ia.exemplo.com/midia/0f8fad5b-d9cb-469f-a165-70867728950e/audio/1700-explicando.ogg"
    atendimento, repo, helena, modelo = montar({"mensagens": [{"texto": "Olá! Sou a Júlia 😊 Entendi seu caso."}, {"texto": url}],
                                                "transferir_para": "closer", "ferramenta": ""})
    repo.agentes["canal-1"].config["midias"] = {"explicando": {"url": url}}           # mídia do roteiro (lista permitida)
    # A troca na 1ª resposta da IA é recusada por padrão (tool fantasma); este papel a libera.
    repo.agentes["canal-1"].config["catalogo"]["papeis"]["sdr"]["transferir_na_primeira_resposta"] = True
    await atendimento.receber(webhook("oi, sofri um acidente"))
    await atendimento.aguardar_esperas()
    pedido = next(p for p in modelo.pedidos if p["papel"] == "etapa")
    assert "Júlia é SDR do escritório Escritório Teste" in pedido["sistema"]          # campos do prompt preenchidos
    assert "boas-vindas" in pedido["conteudo"]                                           # primeira resposta
    assert helena.enviadas == ["Olá! Sou a Júlia 😊 Entendi seu caso.", url]           # o link saiu como arquivo
    lead = next(iter(repo.leads.values()))
    assert lead.id_etapa == "e-closer"


async def test_contratos_aciona_zapsign_e_dado_invalido_pede_correcao():
    atendimento, repo, helena, _ = montar({"mensagens": [{"texto": "Perfeito, vou gerar seu contrato."}],
                                           "transferir_para": "", "ferramenta": "zapsign"})
    await atendimento.receber(webhook("pode gerar"))
    await atendimento.aguardar_esperas()
    lead = next(iter(repo.leads.values()))
    repo.leads[lead.id].id_etapa = "e-contratos"
    await atendimento.receber(webhook("sim, pode gerar o contrato"))
    await atendimento.aguardar_esperas()
    acoes = [a["tipo"] for a in repo.acoes]
    assert "enviar_mensagem" in acoes and "gerar_contrato" not in acoes                 # faltam os dados: pede correção
    correcao = next(a for a in repo.acoes if a["tipo"] == "enviar_mensagem")
    assert correcao["dados"]["texto"].startswith("Para finalizar seu contrato")


def test_chips_de_troca_do_painel_no_prompt():
    """"@Agente X" e "@Transferência: X" (chips do painel) viram destinos; "@Agente Financeiro" não é papel e fica de
    fora (com aviso); o chip cru vira a frase de entrada do destino; e o chip com acento não vaza para o lead."""
    prompt = ("Qualificou: @Transferência: Closer. Advogado no caso: @Agente Desqualificado. "
              "Dinheiro: @Agente Financeiro e siga. Outro: @Transferência: Jurídico. Dados: @Agente Coleta de Dados.")
    assert catalogo.ferramentas_do_prompt(prompt) == (["desqualificado", "contratos", "closer"], [])
    assert catalogo.arrobas_sem_destino(prompt) == ["@Agente Financeiro", "@Transferência: Jurídico"]
    assert catalogo.arrobas_sem_destino("Passe para @Agente Closer e depois @Agente Período de Graça.") == []
    papeis = {"closer": {"mensagem_troca": "Maravilha! Nós podemos te ajudar."}}
    expandido = catalogo.expandir_transferencias(prompt, papeis)
    assert 'Qualificou: "Maravilha! Nós podemos te ajudar.".' in expandido and "@Transferência: Closer" not in expandido
    assert catalogo.expandir_transferencias("Vá: @Transferência: Desqualificado", {}) == "Vá: @Desqualificado"
    assert catalogo.conferir([{"tipo": "texto", "texto": "Vou acionar a @Transferência: Closer"}])


def test_chip_curto_do_painel_passa_o_lead_e_o_antigo_continua_valendo():
    """Menu "@" com nomes curtos em português ("@Comercial"): vira destino igual ao antigo "@Agente Closer"."""
    assert catalogo.ferramentas_do_prompt("Com sequela, passe para @Comercial. Sem caso, @Desqualificado.")[0] == ["closer", "desqualificado"]
    assert catalogo.ferramentas_do_prompt("Nome do meio: @Closer")[0] == ["closer"]
    assert catalogo.ferramentas_do_prompt("Dados: @Coleta de Dados. Graça: @Período de Graça.")[0] == ["contratos", "periododegraca"]
    assert catalogo.ferramentas_do_prompt("Antigo: @Agente Closer")[0] == ["closer"]
    assert catalogo.ferramentas_do_prompt("Fale com @fulano e @Closers")[0] == []
