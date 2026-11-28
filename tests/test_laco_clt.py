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


def test_lead_e_chamado_so_pelo_primeiro_nome():
    fatos = {"nome": "Pedro Paulão", "nome_completo": "João Vitor Duarte Souza"}
    m = lambda t: {"tipo": "texto", "texto": t}
    saida = turno._so_o_primeiro_nome([m("Certo, Pedro Paulão. Qual era a sua profissão?"),
                                       m("Ótimo, João Vitor Duarte Souza. Agora me informe seu CPF."),
                                       m("Vamos conferir:\nNome completo: João Vitor Duarte Souza\nEstá tudo certo?"),
                                       m("Confira: João Vitor Duarte Souza, CPF 529.982.247-25. Está certo?")], fatos)
    assert [x["texto"] for x in saida] == [
        "Certo, Pedro. Qual era a sua profissão?", "Ótimo, Pedro. Agora me informe seu CPF.",
        "Vamos conferir:\nNome completo: João Vitor Duarte Souza\nEstá tudo certo?",
        "Confira: João Vitor Duarte Souza, CPF 529.982.247-25. Está certo?"]
    assert turno._primeiro_nome({"nome": "MARIA DAS DORES"}) == "Maria"
    assert turno._so_o_primeiro_nome([m("Oi, Ana!")], {"nome": "Ana"}) == [m("Oi, Ana!")]


# ----------------------------------------------------------------------------- revisão de todos os produtos (28/11)
def test_pergunta_de_dado_informado_nos_outros_produtos():
    assert turno._pergunta_de_dado_informado(["Para começar, você está grávida?"], {"situacao": "gestante"})
    assert turno._pergunta_de_dado_informado(["Você já tem advogado cuidando desse pedido do BPC?"],
                                             {"tem_advogado_no_caso": "nao"})
    assert turno._pergunta_de_dado_informado(["Você recebeu seguro-desemprego?"], {"seguro_desemprego": "nao_sabe"})
    assert not turno._pergunta_de_dado_informado(["Você está grávida?"], {})


def test_nao_ao_advogado_do_bpc_grava_o_advogado():
    hist = [{"autor": "você", "texto": "Você já tem advogado cuidando desse pedido do BPC?"}]
    achados = resposta_curta.resolver(hist, ["Não"], {"tem_advogado_no_caso", "recebe_beneficio"}, normalizar)
    assert [(a.chave, a.valor) for a in achados] == [("tem_advogado_no_caso", "nao")]


def test_balao_ja_enviado_e_pergunta_de_permissao():
    from tests.test_catalogo_weaver import entrada

    bloco = "✅ Renda extra mensal até a aposentadoria. ✅ Você continua trabalhando normalmente."
    antes = [{"autor": "você", "texto": bloco}, {"autor": "lead", "texto": "sim"},
             {"autor": "você", "texto": "Antes de falar em valor, quero te mostrar por que vale a pena."}]
    e = entrada(["Como faço pra dar andamento?"], historico=antes)
    # Repetir a ÚLTIMA resposta fica com as travas de laço próprias:
    assert turno._baloes_ja_enviados(entrada(["ok"], historico=[{"autor": "você", "texto": bloco}]), [bloco], {}) == []
    assert turno._baloes_ja_enviados(e, [bloco, "Vamos seguir?"], {}) == [bloco]
    e2 = entrada(["Não entendi"], historico=antes)
    assert turno._baloes_ja_enviados(e2, [bloco], {}) == []
    saida = turno.Saida()
    msgs = [{"tipo": "texto", "texto": "Maravilha!"}, {"tipo": "texto", "texto": "Posso te explicar como funciona?"},
            {"tipo": "midia", "url": "https://x/a.ogg"}, {"tipo": "texto", "texto": "Conseguiu entender?"}]
    assert [m.get("texto") for m in turno._para_na_pergunta_de_permissao(saida, msgs, "sdr")] == [
        "Maravilha!", "Posso te explicar como funciona?"]
    assert turno._para_na_pergunta_de_permissao(saida, msgs[2:], "closer") == msgs[2:]


def test_diz_que_assinou_pela_frase():
    assert turno._DIZ_QUE_ASSINOU.search(turno._fala_de_quem_assinou("Sim assinei"))
    assert not turno._DIZ_QUE_ASSINOU.search(turno._fala_de_quem_assinou("ainda não assinei"))


# ----------------------------------------------------------------------------- lote 1 do teste real (28/11)
def test_terceira_vez_da_mesma_pergunta_e_isso_nao_e_sim():
    from tests.test_catalogo_weaver import entrada

    p = "Em qual mês de 2007 aconteceu o acidente?"
    hist = [{"autor": "você", "texto": p}, {"autor": "lead", "texto": "Gari"}, {"autor": "você", "texto": "Entendi. " + p},
            {"autor": "lead", "texto": "O que é Rpps."}]
    assert turno._pergunta_pela_terceira_vez(entrada(["Isso"], historico=hist), ["Certo. " + p])
    assert not turno._pergunta_pela_terceira_vez(entrada(["Não entendi"], historico=hist), [p])
    assert not turno._pergunta_pela_terceira_vez(entrada(["Isso"], historico=hist[:2]), [p])
    hist2 = [{"autor": "você", "texto": "Na época do acidente, você atuava como MEI, Autônomo ou Contribuinte Individual?"}]
    achados = resposta_curta.resolver(hist2, ["Isso, não. Eu era registrada"], {"vinculo_na_data"}, normalizar)
    assert achados == []


def test_resumo_aceito_com_tudo_bem():
    from tests.test_catalogo_weaver import entrada
    from tests.test_auditoria_tickets import FATOS_CONTRATO

    resumo = ("Vamos confirmar: Nome completo: Patrícia Souza Lima, CPF 529.982.247-25, Rua das Flores, 12, Centro, "
              "Campinas/SP. Está tudo certo?")
    e = entrada(["tudo bem"], etapa="contratos", fatos=dict(FATOS_CONTRATO), historico=[{"autor": "você", "texto": resumo}])
    s = turno.Saida(); s.fatos_depois = dict(FATOS_CONTRATO)
    assert turno._resumo_aceito(e, s)
    e2 = entrada(["não, o CPF está errado"], etapa="contratos", historico=[{"autor": "você", "texto": resumo}])
    assert not turno._resumo_aceito(e2, s)


def test_renda_por_pessoa_do_bpc():
    prod = catalogo.carregar({"catalogo": {"slug": "bpc-loas-autismo-v2", "papeis": {"sdr": {}, "closer": {}}}})
    assert prod.familia.startswith("bpc")
    assert "renda_total_reais" in prod.esquema_extrator()["properties"]["fatos"]["items"]["properties"]["chave"]["enum"]
    fatos = {"renda_total_reais": 2100, "pessoas_na_casa": 4}
    assert turno._faixa_da_renda_bpc(prod, fatos) == "qualifica"
    assert "R$ 525,00" in turno._linha_da_renda_bpc(prod, fatos).replace(",", "X").replace(".", ",").replace("X", ".") \
        or "525.00" in turno._linha_da_renda_bpc(prod, fatos)
    assert turno._faixa_da_renda_bpc(prod, {"renda_total_reais": 3800, "pessoas_na_casa": 4}) == "gastos"
    assert turno._faixa_da_renda_bpc(prod, {"renda_total_reais": 2100}) is None
    aux = catalogo.carregar({"catalogo": {"slug": "auxilio-acidente-v2", "papeis": {"sdr": {}}}})
    assert turno._faixa_da_renda_bpc(aux, fatos) is None


def test_confirmacao_de_trava_precisa_de_sim_claro():
    assert turno._sim_inequivoco(normalizar("Sim"))
    assert turno._sim_inequivoco(normalizar("tenho sim"))
    assert not turno._sim_inequivoco(normalizar("Pode"))
    assert not turno._sim_inequivoco(normalizar("🤣🤣"))
    assert not turno._sim_inequivoco(normalizar("Sim, moramos em casa própria"))


def test_nome_valido():
    assert catalogo.nome_valido("Pedro Paulo") == "Pedro Paulo"
    assert catalogo.nome_valido("maria das dores") == "maria das dores"
    for ruim in ("Olá", "Eu", "Bati de moto na dutra", "Infelizmente", "Frentista", "Eu estava indo para o serviço"):
        assert catalogo.nome_valido(ruim) is None, ruim


def test_cpf_valido_da_fala_vira_fato():
    from tests.test_catalogo_weaver import entrada

    s = turno.Saida()
    turno._cpf_da_fala(entrada(["Já te passei, 529.982.247.25"], etapa="contratos",
                               historico=[{"autor": "você", "texto": "Qual o seu CPF?"}]), s)
    assert s.fatos_depois.get("cpf") == "529.982.247-25"
    s2 = turno.Saida()
    turno._cpf_da_fala(entrada(["52998224725"], etapa="contratos",
                               historico=[{"autor": "você", "texto": "Qual o CPF do seu filho?"}]), s2)
    assert "cpf" not in s2.fatos_depois
    s3 = turno.Saida()
    turno._cpf_da_fala(entrada(["12345678900"], etapa="contratos", historico=[]), s3)
    assert "cpf" not in s3.fatos_depois


def test_fotos_de_documento_com_texto_do_caso_nao_e_suspeito():
    from datetime import datetime, timedelta
    from app.canal import suspeito

    t0 = datetime(2026, 11, 28, 10, 0)
    fotos = [{"autor": "ia", "tipo": "texto", "texto": "Em qual ano aconteceu o acidente?", "enviada_em": t0}] + [
        {"autor": "lead", "tipo": "imagem", "texto": "", "enviada_em": t0 + timedelta(seconds=10 + i)} for i in range(6)]
    assert suspeito.avaliar(fotos).motivo == "so_midia"
    fotos.append({"autor": "lead", "tipo": "texto", "texto": "Então, foi do acidente, minha mão ficou com dor e limitação",
                  "enviada_em": t0 + timedelta(seconds=30)})
    assert suspeito.avaliar(fotos) is None
