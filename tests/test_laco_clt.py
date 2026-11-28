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
