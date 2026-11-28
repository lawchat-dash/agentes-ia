"""Laço de 28/11 (Auxílio v2, portão desligado): "Pedreiro clt" não virava vínculo CLT, "Sim falei acima" não era sim e
a IA mandou a mesma pergunta da carteira assinada duas vezes."""
from app.cerebro import catalogo, resposta_curta, turno
from app.cerebro.extrator import Extracao, normalizar, pela_pergunta

CFG = {"catalogo": {"slug": "auxilio-acidente-v2", "familia": "auxilio_acidente", "portao_de_fatos": False}}
PAPEIS = ["sdr", "periododegraca", "closer", "contratos", "assinatura", "desqualificado"]
PERGUNTA_CLT = "Entendi, Pedro. Você estava registrado como pedreiro, com carteira assinada (CLT), na época do acidente?"


def _produto():
    return catalogo.ProdutoCatalogo(papeis=PAPEIS, config=CFG).para_o_papel("sdr")


def test_extrator_do_auxilio_procura_as_respostas_do_roteiro_mesmo_sem_portao():
    p = _produto()
    assert p.familia == "auxilio_acidente"
    chaves = set(p.esquema_extrator()["properties"]["fatos"]["items"]["properties"]["chave"]["enum"])
    assert {"vinculo_na_data", "ja_foi_clt", "auxilio_doenca", "sequela", "aposentado", "tem_advogado_no_caso"} <= chaves
    assert "vinculo_na_data" in p.guia_do_extrator()
    assert p.validar_valor("vinculo_na_data", "clt") == "clt"


def test_sim_reclamando_da_repeticao_vale_como_sim_a_pergunta_da_clt():
    for texto in ("Sim falei acima", "sim acabei de falar", "Sim já disse", "sim eu falei"):
        assert resposta_curta.sim_nao(normalizar(texto), texto) == ("sim", False), texto
    assert resposta_curta.sim_nao(normalizar("sim eu acho que sim"), "sim eu acho que sim") is None
    historico = [{"autor": "lead", "texto": "Pedreiro clt"}, {"autor": "você", "texto": PERGUNTA_CLT}]
    extracao = pela_pergunta(Extracao(), historico, ["Sim falei acima"], {}, _produto())
    assert [(f.chave, f.valor) for f in extracao.fatos] == [("vinculo_na_data", "clt")]


def test_falei_acima_e_acabei_de_falar_ligam_a_trava_da_resposta_repetida():
    for texto in ("Sim falei acima", "Sim acabei de falar", "eu te disse antes", "respondi ali acima"):
        assert turno._REPETICAO_DO_LEAD.search(normalizar(texto)), texto
    assert not turno._REPETICAO_DO_LEAD.search(normalizar("Pedreiro clt"))


async def test_remover_etiqueta_tira_todas_as_copias_com_o_mesmo_nome():
    from app.canal.helena_conta import HelenaConta

    pedidos = []

    class Falsa(HelenaConta):
        async def etiquetas(self):
            return [{"id": "c1", "nome": "🛒 Comercial"}, {"id": "c2", "nome": "🛒 Comercial"},
                    {"id": "e1", "nome": "📄 Contrato em Elaboração"}, {"id": "e2", "nome": "📄 Contrato em Elaboração"}]

        async def _pedir(self, metodo, caminho, **kw):
            pedidos.append(kw["json"])

    h = Falsa("x")
    await h.etiquetar("contato", ["🛒 Comercial"], remover=True)
    await h.etiquetar("contato", ["📄 Contrato em Elaboração"])
    assert pedidos == [{"tagIds": ["c1", "c2"], "operation": "DeleteIfExists"},
                       {"tagIds": ["e2"], "operation": "InsertIfNotExists"}]


async def test_resposta_que_aciona_o_contrato_so_leva_o_aviso_de_gerando():
    """28/11: o prompt antigo do Contratos mandava a IA enviar áudio, vídeo e "documentação pronta" junto com o zapsign;
    a ZapSign recusou e o lead recebeu tudo isso antes de "a equipe vai finalizar o seu contrato"."""
    from app.modelo import ModeloFalso
    from tests.test_auditoria_tickets import FATOS_CONTRATO
    from tests.test_catalogo_weaver import entrada, extrai

    audio = "https://exemplo.supabase.co/storage/v1/object/public/agentesia-midia/x/audio/assinatura.ogg"
    video = "https://exemplo.supabase.co/storage/v1/object/public/agentesia-midia/x/video/como-assinar.mp4"
    etapa = {"mensagens": [{"texto": "Perfeito! Estamos gerando o seu contrato."}, {"texto": audio}, {"texto": video},
                           {"texto": "SUA DOCUMENTAÇÃO JÁ ESTÁ PRONTA PARA ASSINATURA. Por gentileza, assista o vídeo "
                                     "até o final antes de assinar: é só clicar no link que chega logo abaixo 👇"}],
             "transferir_para": "", "ferramenta": "zapsign"}
    modelo = ModeloFalso({"extrator": extrai(confirmou_dados=True), "etapa": etapa})
    e = entrada(["Sim"], etapa="contratos", fatos=dict(FATOS_CONTRATO),
                historico=[{"autor": "você", "texto": "Confira seus dados. Posso gerar o contrato?"}])
    e.instrucoes = {"contratos": f"Roteiro. Áudio: {audio} Vídeo: {video}"}
    saida = await turno.processar(modelo, e)
    assert saida.motivo == "dados_confirmados"
    assert [m.get("texto") for m in saida.mensagens] == ["Perfeito! Estamos gerando o seu contrato."]
    assert "contrato_aviso_antecipado" in [ev["tipo"] for ev in saida.eventos]


# ----------------------------------------------------------------------------- reteste de 28/11 (lead Pedro Paulo)
def test_pergunta_de_dado_ja_informado():
    fatos = {"acidente_mes": 5, "acidente_ano": 2023, "nome": "Pedro Paulo", "vinculo_na_data": "clt"}
    achados = turno._pergunta_de_dado_informado(
        ["Perfeito. E pra eu entender melhor, em qual mês de 2023 aconteceu o acidente?"], fatos)
    assert achados == ["o mês do acidente"]
    assert turno._pergunta_de_dado_informado(
        ["Mais uma informação, você estava registrado com carteira assinada (CLT) quando o acidente aconteceu?"], fatos)
    assert not turno._pergunta_de_dado_informado(["Foi em maio de 2023, certo?"], fatos)      # confirmação
    assert not turno._pergunta_de_dado_informado(["Qual o seu nome completo?"], fatos)        # dado do contrato
    assert not turno._pergunta_de_dado_informado(["Em qual mês aconteceu o acidente?"], {"acidente_ano": 2023})
    assert not turno._pergunta_de_dado_informado(["Você estava registrado?"], {"vinculo_na_data": "mei_autonomo_ci"})


def test_espera_um_sim():
    def m(*textos):
        return [{"tipo": "texto", "texto": t} for t in textos]
    assert turno._espera_um_sim(m("Perfeito! Vamos avançar para a formalização da nossa representação. "
                                  "Podemos iniciar a coleta dos seus dados?"))
    assert turno._espera_um_sim(m("Faz sentido para você?"))
    assert not turno._espera_um_sim(m("Me informe seu nome completo, por favor?"))
    assert not turno._espera_um_sim(m("Certo."))


async def test_closer_que_pergunta_e_passa_no_mesmo_turno_espera_a_resposta():
    from app.modelo import ModeloFalso
    from tests.test_catalogo_weaver import entrada, extrai, resposta

    prod = catalogo.carregar({"catalogo": {"papeis": {
        "sdr": {}, "closer": {}, "contratos": {"mensagem_troca": "Excelente! Por gentileza, me informe seu nome completo."},
        "assinatura": {}, "desqualificado": {}}}, "funcoes": {"contrato_zapsign": True}})
    hist = [{"autor": a, "texto": t} for a, t in (("lead", "oi"), ("você", "Olá!"), ("lead", "caí de moto"),
            ("você", "Entendi."), ("lead", "sim"), ("você", "Conseguiu entender as condições dos honorários?"))]

    def ent(novas, **extra):
        e = entrada(novas, etapa="closer", prod=prod, historico=list(hist), **extra)
        e.instrucoes = {"closer": "Quando o lead aceitar a coleta: acionar tool `contratos`."}
        return e

    pergunta = "Perfeito! Vamos avançar para a formalização. Podemos iniciar a coleta dos seus dados?"
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta(pergunta, transferir="contratos")})
    saida = await turno.processar(modelo, ent(["Sim"]))
    assert saida.etapa_depois == "closer" and [x["texto"] for x in saida.mensagens] == [pergunta]
    assert "transferencia_adiada_pergunta_aberta" in [e["tipo"] for e in saida.eventos]
    # O lead responde: a passagem vale e a frase do Contratos entra.
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Ótimo!", transferir="contratos")})
    saida2 = await turno.processar(modelo, ent(["Sim, pode"], fatos=dict(saida.fatos_depois)))
    assert saida2.etapa_depois == "contratos"
    assert saida2.mensagens[-1]["texto"] == "Excelente! Por gentileza, me informe seu nome completo."


async def test_cpf_respondido_ao_pedido_de_correcao_refaz_o_contrato_mesmo_sem_a_ia_pedir():
    """28/11: o sistema pediu o CPF, o lead mandou e a IA só disse "Recebi seu CPF, está tudo certo": sem contrato."""
    from app.modelo import ModeloFalso
    from tests.test_catalogo_weaver import entrada, extrai, resposta
    from tests.test_correcoes_rodada_real import CONTRATO_SEM_CPF, CPF_VALIDO

    historico = [{"autor": "lead", "texto": "Sim"},
                 {"autor": "automacao", "texto": "Para finalizar seu contrato, preciso confirmar uma informação: o seu "
                                                 "CPF. Pode me enviar novamente, por favor?"}]
    modelo = ModeloFalso({"extrator": extrai(fatos=[("cpf", CPF_VALIDO, CPF_VALIDO)]),
                          "etapa": resposta("Recebi seu CPF e está tudo certo com ele.")})
    saida = await turno.processar(modelo, entrada([CPF_VALIDO], etapa="contratos", fatos=dict(CONTRATO_SEM_CPF),
                                                  historico=historico))
    assert saida.motivo == "dados_confirmados" and saida.contexto["catalogo"]["ferramenta"] == "zapsign"
    assert [m["texto"] for m in saida.mensagens] == ["Perfeito! Estamos gerando o seu contrato."]
    # Sem o pedido de correção antes, a IA decide (nada é forçado).
    modelo = ModeloFalso({"extrator": extrai(fatos=[("cpf", CPF_VALIDO, CPF_VALIDO)]), "etapa": resposta("Anotado!")})
    saida = await turno.processar(modelo, entrada([CPF_VALIDO], etapa="contratos", fatos=dict(CONTRATO_SEM_CPF),
                                                  historico=[{"autor": "você", "texto": "Qual o seu CPF?"}]))
    assert saida.motivo != "dados_confirmados"
