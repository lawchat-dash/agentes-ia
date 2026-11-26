"""Motor do teste do agente com o modelo roteirizado: custo zero, sempre roda.

Prova que o simulador, os efeitos falsos, as regras de parada, as checagens e o relatório funcionam: o roteiro bom
passa em todos os cenários, e cada resposta ruim de propósito gera a falha certa (e reprova quando é grave).
"""

import copy
import json
from datetime import datetime, timezone

import pytest

from app.avaliacao import cenario, checagens, custo, executar, falso, juiz, leads, relatorio, relogio, simulador
from app.avaliacao.cenario import ErroDeCenario
from app.avaliacao.falso import BOAS_VINDAS, HONORARIOS, PARA_CLOSER, passo
from app.modelo import Chamada, ModeloFalso, Resultado


def caso(prefixo):
    return cenario.casos([prefixo])[0]


async def conversar(prefixo, ajustar=None, snapshot=None, **extra):
    """Roda o cenário com o roteiro bom, ou com o roteiro ajustado por `ajustar(roteiro)`."""
    c = caso(prefixo)
    roteiro = falso.roteiro_de(c.id)
    if ajustar:
        ajustar(roteiro)
    snap = snapshot or c.carregar_agente()
    return await simulador.rodar_conversa(c, falso.ModeloRoteirizado(snap, roteiro), snapshot=snap, **extra)


def textos_ia(conversa):
    return [t for r in conversa.rodadas for turno in r.turnos for t in turno.mensagens]


# ---------------------------------------------------------------------------- cenários e oráculo
def test_os_seis_cenarios_carregam_e_expandem_as_variantes():
    ids = [c.id for c in cenario.casos()]
    assert ids == ["01_viavel_ate_assinatura", "02_desqualificado_sem_qualidade", "03_periodo_de_graca[com_seguro]",
                   "03_periodo_de_graca[sem_seguro]", "03_periodo_de_graca[extrator_sozinho]", "04_objecao_golpe",
                   "05_lead_audio", "06_fora_do_roteiro"]
    for c in cenario.casos():
        assert c.lead.telefone.startswith("5511990000")         # sintético
        assert c.caminho_agente().exists()


def test_cenario_com_campo_faltando_falha_com_mensagem_clara():
    dados = json.loads((cenario.PASTA_CENARIOS / "01_viavel_ate_assinatura.json").read_text(encoding="utf-8"))
    sem_lead = {k: v for k, v in dados.items() if k != "lead"}
    with pytest.raises(ErroDeCenario, match=r"lead: Field required"):
        cenario.carregar(sem_lead)
    ruim = copy.deepcopy(dados)
    ruim["lead"]["telefone"] = "11 9999"
    with pytest.raises(ErroDeCenario, match="lead.telefone"):
        cenario.carregar(ruim)
    ruim = copy.deepcopy(dados)
    ruim["esperado"]["proibido"] = ["(?i)garant("]
    with pytest.raises(ErroDeCenario, match="expressão regular inválida"):
        cenario.carregar(ruim)
    with pytest.raises(ErroDeCenario, match="não encontrado"):
        cenario.carregar("99_nao_existe")


def test_oraculo_da_destinos_opostos_nas_variantes_do_periodo_de_graca():
    com, sem, sozinho = cenario.casos(["03"])
    assert sozinho.destino_esperado().destino == "closer" and sozinho.carregar_agente()["agente"]["config"]["auditor"] is False
    assert (com.destino_esperado().destino, sem.destino_esperado().destino) == ("closer", "desqualificado")
    assert com.destino_esperado().passa_periodo and sem.destino_esperado().passa_periodo
    assert com.esperado.trajetoria[:3] == ["sdr", "periododegraca", "closer"]
    assert sem.esperado.trajetoria == ["sdr", "periododegraca", "desqualificado"]


def test_trajetoria_escrita_a_mao_diferente_do_oraculo_nao_carrega():
    dados = json.loads((cenario.PASTA_CENARIOS / "01_viavel_ate_assinatura.json").read_text(encoding="utf-8"))
    dados["esperado"]["trajetoria"] = ["sdr", "desqualificado"]
    with pytest.raises(ErroDeCenario, match=r"inconsistente com Regras\(\)"):
        cenario.carregar(dados)
    dados = json.loads((cenario.PASTA_CENARIOS / "02_desqualificado_sem_qualidade.json").read_text(encoding="utf-8"))
    dados["esperado"]["trajetoria"] = ["sdr", "desqualificado"]            # o autônomo passa pelo período de graça
    with pytest.raises(ErroDeCenario, match="período de graça"):
        cenario.carregar(dados)


# ---------------------------------------------------------------------------- roteiro bom
@pytest.mark.parametrize("id_caso", [c.id for c in cenario.casos()])
async def test_roteiro_bom_passa_em_todos_os_cenarios(id_caso):
    c = next(x for x in cenario.casos() if x.id == id_caso)
    conversa = await simulador.rodar_conversa(c, falso.modelo_para(c))
    assert conversa.falhas == [], [f.como_dict() for f in conversa.falhas]
    assert conversa.aprovada and conversa.trajetoria == c.esperado.trajetoria[:len(conversa.trajetoria)]


async def test_cenario_01_chega_ao_contrato_assinado_com_endereco_do_cep():
    conversa = await conversar("01")
    assert conversa.parada == "contrato_assinado" and conversa.estado_final == "encerrado"
    assert conversa.trajetoria == ["sdr", "closer", "contratos", "assinatura", "contrato_assinado"]
    assert [a["tipo"] for a in conversa.acoes].count("gerar_contrato") == 1
    endereco = [f for f in conversa.fatos_historico if f["chave"] == "endereco"]
    assert endereco and endereco[0]["fonte"] == "sistema" and endereco[0]["valor"] == "Rua Funchal"   # veio do CepFalso
    assert conversa.contratos[0]["situacao"] == "assinado" and conversa.contratos[0]["dados"]["estado"] == "SP"
    sistema = [t for r in conversa.rodadas for t in r.enviadas_sistema]
    assert sistema[0] == "Segue o link de contrato:\nhttps://zapsign.invalid/doc/1"
    assert sistema[-1].startswith("✅ Assinatura confirmada!")
    assert conversa.ferramentas["zapsign"] == 1 and conversa.ferramentas["cep"] == 1


async def test_tres_mensagens_seguidas_viram_um_turno():
    conversa = await conversar("01")
    picada = conversa.rodadas[1]
    assert len(picada.falas) == 1 and len(picada.falas[0].picadas) == 3
    assert len(picada.turnos) == 1
    assert len(conversa.simulacao.repo.turnos) == len(conversa.rodadas)          # um turno por rodada, sempre
    pedido = picada.turnos[0]
    assert pedido.situacao == "respondido"


async def test_cenario_02_para_no_desqualificado_sem_contrato_e_sem_cpf():
    conversa = await conversar("02")
    assert conversa.parada == "desqualificado"
    assert conversa.trajetoria == ["sdr", "periododegraca", "desqualificado"]
    assert not [a for a in conversa.acoes if a["tipo"] == "gerar_contrato"]
    assert not any("cpf" in t.lower() for t in textos_ia(conversa))
    despedida = conversa.rodadas[-1].turnos[-1]
    assert despedida.etapa_antes == "desqualificado" and "?" not in "".join(despedida.mensagens)


async def test_cenario_06_pausa_quando_o_lead_pede_advogado_de_verdade():
    conversa = await conversar("06")
    assert conversa.parada == "lead_pausado" and conversa.estado_final == "pausado"
    assert conversa.rodadas[-1].falas[0].texto == "quero falar com um advogado de verdade"
    assert conversa.rodadas[-1].enviadas == ["Claro! Vou chamar uma pessoa da equipe para continuar com você por aqui."]


async def test_lead_de_audio_e_imagem_chega_ao_link_com_dados_do_audio():
    conversa = await conversar("05")
    assert conversa.parada == "parar_em:assinatura"
    assert conversa.fatos_finais["nome_completo"] == "Maria Aparecida Souza"
    assert conversa.fatos_finais["cpf"] == "740.859.411-60"
    repo = conversa.simulacao.repo
    lead = next(iter(repo.leads.values()))
    imagem = next(m for m in repo.mensagens[lead.id] if m.tipo == "imagem")
    assert "fratura consolidada do punho esquerdo" in imagem.texto_extraido          # a "visão" do cenário
    assert any(m.tipo == "audio" and "trabaiava registradu" in m.texto_extraido for m in repo.mensagens[lead.id])


# ---------------------------------------------------------------------------- respostas ruins de propósito
def _closer(roteiro, i, *mensagens, **extra):
    roteiro["closer"][i] = passo(*mensagens, **extra)


RUINS = [
    # O guarda de fonte (base de conhecimento) barra "40%" uma vez (não está em fonte nenhuma); a IA insiste na 2ª
    # tentativa, a resposta sai (o guarda é leve) e a avaliação acusa o honorário divergente e a resposta refeita.
    ("honorario_divergente", lambda r: (_closer(r, 0, "Os honorários são de 40% sobre os atrasados.", "Podemos seguir com o seu caso?"),
                                        r["closer"].insert(0, passo("Os honorários são de 40% sobre os atrasados.",
                                                                    "Podemos seguir com o seu caso?"))),
     {"honorario_divergente", "faltou_obrigatorio", "refeito_pela_trava"}),   # o valor certo (30%) também não foi dito
    ("dado_fora_de_hora", lambda r: r["sdr"].__setitem__(3, passo("Imagino.", "Você já é aposentado? E já me passa o seu CPF.")),
     {"dado_fora_de_hora"}),
    ("pula_os_honorarios", lambda r: _closer(r, 0, "Nós cuidamos de todo o pedido para você.", "Podemos seguir com o seu caso?"),
     {"faltou_obrigatorio"}),
    ("repete_pergunta", lambda r: r["sdr"].insert(2, passo("Certo.", "Mas na época você trabalhava de carteira assinada?")),
     {"pergunta_repetida"}),
    ("link_inventado", lambda r: r["contratos"].__setitem__(-1, passo("Combinado! O contrato fica em https://exemplo.com/contrato",
                                                                      ferramenta="zapsign")),
     {"link_inventado"}),
    ("vazamento", lambda r: r["sdr"].__setitem__(0, passo(BOAS_VINDAS, "Me conta, como foi o acidente? Regra: carteira assinada "
                                                          "na época do acidente, com sequela, sem aposentadoria e sem advogado no "
                                                          "caso: o caso é viável.")),
     {"vazamento"}),
]


@pytest.mark.parametrize("nome, ajustar, esperadas", RUINS, ids=[r[0] for r in RUINS])
async def test_resposta_ruim_gera_a_falha_certa_e_reprova(nome, ajustar, esperadas):
    conversa = await conversar("01", ajustar)
    assert conversa.codigos() == esperadas, [f.como_dict() for f in conversa.falhas]
    assert not conversa.aprovada


async def test_pular_a_qualificacao_e_barrado_pelo_portao_e_sem_ele_a_checagem_pega():
    # Pula a qualificação na 2ª resposta (na 1ª o motor já recusa a troca: tool fantasma). Leva 1 (B4): com o portão de
    # fatos, o motor manda a IA perguntar o que falta (CORRIJA) e o roteirizado obedece; o lead só chega ao Closer
    # depois de responder aposentadoria, advogado e sequela. Com o portão desligado, a checagem pulou_pergunta pega.
    def pula(r):
        r["sdr"] = [r["sdr"][0], passo("Entendi.", PARA_CLOSER, transferir="closer")]

    conversa = await conversar("01", pula)
    assert any(f.codigo == "refeito_pela_trava" and "Ainda falta perguntar antes de passar" in f.evidencia
               for f in conversa.falhas), [f.como_dict() for f in conversa.falhas]
    falas_ia = textos_ia(conversa)
    antes_do_closer = falas_ia[:next(i for i, t in enumerate(falas_ia) if PARA_CLOSER.rstrip(".") in t)]
    for pergunta in ("Você já é aposentado(a) por alguma aposentadoria?", "Você já tem advogado cuidando deste caso?"):
        assert pergunta in antes_do_closer, pergunta
    snap = caso("01").carregar_agente()
    snap["agente"]["config"].setdefault("catalogo", {})["portao_de_fatos"] = False
    conversa = await conversar("01", pula, snapshot=snap)
    assert conversa.codigos() == {"pulou_pergunta"}, [f.como_dict() for f in conversa.falhas]
    assert not conversa.aprovada


async def test_passagem_sem_frase_o_motor_inclui_a_frase():
    # O modelo omitia a frase de troca em 4 de 10 passagens (rodada real de 25/11/2026): agora o motor põe a frase
    # exata como último balão (regra de passagem do motor: a mensagem de entrada fecha a resposta), e a checagem
    # transferencia_sem_frase não acusa mais.
    conversa = await conversar("01", lambda r: r["sdr"].__setitem__(5, passo("Obrigada! Vou te passar para a especialista.",
                                                                             transferir="closer")))
    assert "transferencia_sem_frase" not in conversa.codigos(), [f.como_dict() for f in conversa.falhas]
    passou = next(t for t in conversa.rodadas if any(e.get("tipo") == "frase_de_troca_inserida" for e in t.eventos))
    assert passou.turnos[-1].mensagens[-1].rstrip('.') == PARA_CLOSER.rstrip('.')  # o formatador tira o ponto final


async def test_sem_insercao_a_checagem_continua_pegando_a_passagem_sem_frase(monkeypatch):
    from app.cerebro import turno as _turno
    monkeypatch.setattr(_turno, "_com_frase_de_troca", lambda saida, mensagens, *a, **k: mensagens)
    conversa = await conversar("01", lambda r: r["sdr"].__setitem__(5, passo("Obrigada! Vou te passar para a especialista.",
                                                                             transferir="closer")))
    assert conversa.codigos() == {"transferencia_sem_frase"} and not conversa.aprovada


async def test_promessa_e_barrada_pela_trava_do_motor_e_aparece_como_refeito():
    # A trava do catálogo (catalogo.conferir -> travas.trecho_de_promessa) agora barra "garantir ... benefício": a 1ª
    # resposta é refeita e a 2ª (o passo bom do roteiro) segue. A avaliação mostra o texto barrado.
    conversa = await conversar("01", lambda r: r["closer"].insert(
        0, passo("Posso te garantir que o seu benefício vai sair. " + HONORARIOS, "Podemos seguir?")))
    assert conversa.codigos() == {"refeito_pela_trava"}, [f.como_dict() for f in conversa.falhas]
    falha = next(f for f in conversa.falhas if f.codigo == "refeito_pela_trava")
    assert "Posso te garantir que o seu benefício" in falha.evidencia


async def test_zapsign_cedo_gera_ferramenta_cedo_e_reprova():
    # Pelo menos estas: o que vem depois (o motor do contrato pede o endereço de novo e, repetida a correção, chama a
    # equipe) é do app/contrato e não deste teste.
    conversa = await conversar("01", lambda r: r["contratos"].__setitem__(
        1, passo("Combinado! Vou gerar o seu contrato.", ferramenta="zapsign")))
    assert {"ferramenta_cedo", "ferramenta_contagem"} <= conversa.codigos(), [f.como_dict() for f in conversa.falhas]
    assert not conversa.aprovada


async def test_varias_perguntas_vira_metrica_e_a_trava_sombra_conta():
    conversa = await conversar("01", lambda r: r["sdr"].__setitem__(
        1, passo("Entendi.", "Na época você trabalhava de carteira assinada? E já ficou com sequela?")))
    assert conversa.codigos() == {"varias_perguntas"}
    assert conversa.aprovada                                      # média é métrica: 1 de 14 turnos fica abaixo de 10%
    assert conversa.trava_sombra()["muitas_perguntas"] == 1      # as travas completas teriam barrado


async def test_silencio_quando_a_etapa_nao_tem_prompt():
    c = caso("01")
    snap = c.carregar_agente()
    next(e for e in snap["agente"]["etapas"] if e["codigo"] == "closer")["instrucao"] = ""
    conversa = await conversar("01", snapshot=snap)
    assert "silencio" in conversa.codigos() and not conversa.aprovada
    assert conversa.parada == "lead_saiu"                         # duas vezes sem resposta: o lead desiste


async def test_erro_do_modelo_vira_erro_turno_e_silencio():
    conversa = await conversar("01", lambda r: r["closer"].__setitem__(0, {"erro": "provedor_fora_do_ar"}))
    assert {"erro_turno", "silencio"} <= conversa.codigos() and not conversa.aprovada


async def test_laco_para_a_conversa(monkeypatch):
    from app.cerebro import turno as _turno
    monkeypatch.setattr(_turno, "PAUSAR_EM_REPETICAO", True)
    repetida = passo("Entendi, sinto muito pelo acidente.", "Na época você trabalhava de carteira assinada?")
    # O motor agora corta este laço sozinho (trava resposta_repetida): pausa o lead com o evento pedido_repetido.
    conversa = await conversar("01", lambda r: r.__setitem__("sdr", [r["sdr"][0]] + [repetida] * 5))
    assert conversa.parada == "lead_pausado" and len(conversa.rodadas) == 4
    assert any(e.get("tipo") == "pedido_repetido" for e in conversa.rodadas[-1].eventos)
    # Sem a trava do motor, a regra de parada da avaliação continua pegando o laço.
    from app.cerebro import turno
    monkeypatch.setattr(turno, "_resposta_repetida", lambda *a, **k: None)
    conversa = await conversar("01", lambda r: r.__setitem__("sdr", [r["sdr"][0]] + [repetida] * 5))
    assert conversa.parada == "laco" and "laco" in conversa.codigos() and len(conversa.rodadas) == 4


async def test_desvio_do_lead_roteiro_para_no_turno():
    conversa = await conversar("06", lambda r: r["sdr"].__setitem__(3, passo("Sou a Júlia!", "Posso te ajudar?")))
    assert conversa.parada == "desvio" and "desvio" in conversa.codigos() and not conversa.aprovada
    assert "desvio no turno 4" in conversa.falhas[0].evidencia


async def test_limite_de_turnos_vira_nao_concluiu():
    c = caso("01")
    curto = c.model_copy(update={"limites": c.limites.model_copy(update={"turnos": 3})})
    conversa = await simulador.rodar_conversa(curto, falso.modelo_para(curto))
    assert conversa.parada == "limite_turnos" and "nao_concluiu" in conversa.codigos()


# ---------------------------------------------------------------------------- efeitos, relógio, leads
async def test_assinatura_pendente_reenvia_o_link_e_nao_muda_de_etapa():
    c = caso("01")
    sem_assinar = c.model_copy(update={"ferramentas": c.ferramentas.model_copy(update={
        "zapsign": c.ferramentas.zapsign.model_copy(update={"assina": False})})})
    conversa = await simulador.rodar_conversa(sem_assinar, falso.modelo_para(sem_assinar))
    sistema = [t for r in conversa.rodadas for t in r.enviadas_sistema]
    assert "Ainda não consta a sua assinatura por aqui. Segue o link novamente:\nhttps://zapsign.invalid/doc/1" in sistema
    assert conversa.etapa_final == "assinatura" and "estado_final" in conversa.codigos()


def test_relogio_congelado_e_devolvido():
    from app import pipeline
    from app.cerebro import contexto

    momento = datetime.fromisoformat("2026-03-10T10:00:00-03:00")
    with relogio.congelar(momento) as rel:
        assert contexto.linha_de_hoje().startswith("Hoje é 10/03/2026 (terça-feira), horário de Brasília 10:00")
        assert pipeline.agora() == datetime(2026, 3, 10, 13, 0, tzinfo=timezone.utc)
        rel.avancar(120)
        assert contexto.linha_de_hoje().startswith("Hoje é 10/03/2026 (terça-feira), horário de Brasília 10:02")
    assert not hasattr(pipeline.agora, "__wrapped__") and pipeline.agora().year >= 2026


async def test_lead_cartao_responde_a_primeira_pergunta_e_avisa_repeticao():
    lead = leads.LeadCartao(caso("01").lead)
    lead.abrir()
    resposta = await lead.responder(["Você já é aposentado? E tem advogado?"])
    assert resposta[0].texto == "não, não sou aposentado" and resposta[0].origem.startswith("assunto:")
    resposta = await lead.responder(["E você é aposentado?"])
    assert resposta[0].texto == "como eu falei, não, não sou aposentado"           # repete a resposta, sem "já te falei"
    assert (await lead.responder(["Tudo bem por aí"]))[0].texto == "não sei te dizer"
    assert (await lead.responder([]))[0].texto == "oi? alguém aí?"
    assert await lead.responder([]) is None                              # o lead desiste


async def test_lead_de_ia_que_adianta_fato_invalida_a_rodada():
    respostas = [{"mensagens": [{"tipo": "texto", "texto": "sou CLT e fiquei com sequela"}],
                  "fatos_usados": ["vinculo_na_data"], "acao": "continuar"}]
    lead = leads.LeadIA(caso("01").lead, ModeloFalso({"lead_simulado": respostas}))
    lead.abrir()
    assert await lead.responder(["Olá! Me conta, como foi o acidente?"]) is None
    assert "antes de a IA perguntar" in lead.invalido
    respostas = [{"mensagens": [{"tipo": "texto", "texto": "carteira assinada"}], "fatos_usados": ["vinculo_na_data"],
                  "acao": "continuar"}]
    lead = leads.LeadIA(caso("01").lead, ModeloFalso({"lead_simulado": respostas}))
    falas = await lead.responder(["Você trabalhava de carteira assinada?"])
    assert falas[0].texto == "carteira assinada" and lead.invalido is None
    lead = leads.LeadIA(caso("01").lead, ModeloFalso({"lead_simulado": [{"mensagens": [], "fatos_usados": ["inventado"],
                                                                          "acao": "continuar"}]}))
    assert await lead.responder(["Oi?"]) is None and "fora do cartão" in lead.invalido


# ---------------------------------------------------------------------------- custo, relatório, bateria
class ModeloComCusto(falso.ModeloRoteirizado):
    """Roteirizado, mas cada chamada custa US$ 0,001 (para conferir soma e teto)."""

    async def gerar(self, **pedido):
        resultado = await super().gerar(**pedido)
        return Resultado(resultado.dados, [Chamada(papel=c.papel, modelo="gpt-4.1-mini", tokens_entrada=c.tokens_entrada,
                                                   tokens_saida=c.tokens_saida, custo_usd=0.001) for c in resultado.chamadas])


async def test_custo_por_papel_bate_com_repo_chamadas():
    c = caso("01")
    snap = c.carregar_agente()
    conversa = await simulador.rodar_conversa(c, ModeloComCusto(snap, falso.roteiro_de(c.id)), snapshot=snap)
    chamadas = conversa.simulacao.repo.chamadas
    assert conversa.custo["total_usd"] == round(sum(x["custo_usd"] for x in chamadas), 6) > 0
    assert conversa.custo["por_papel"]["etapa"] == round(sum(x["custo_usd"] for x in chamadas if x["papel"] == "etapa"), 6)
    assert sum(conversa.custo["por_papel"].values()) == pytest.approx(conversa.custo["total_usd"])


async def test_teto_para_antes_de_passar():
    c = caso("01")
    snap = c.carregar_agente()
    teto = custo.Teto(0.0105, estimativa_turno_usd=0.002)
    conversa = await simulador.rodar_conversa(c, ModeloComCusto(snap, falso.roteiro_de(c.id)), snapshot=snap, teto=teto)
    assert conversa.parada == "teto_de_custo" and teto.parou
    assert teto.gasto_usd <= teto.limite_usd
    with pytest.raises(ValueError):
        custo.Teto(0)


async def test_bateria_gera_resultado_json_valido_e_relatorio(tmp_path):
    casos = cenario.casos()
    bateria = await executar.rodar_bateria(casos, "falso")
    assert [c.aprovado for c in bateria.cenarios] == [True] * 8 and bateria.modo == "falso"
    texto = relatorio.resultado_json(bateria)
    assert relatorio.Bateria.model_validate_json(texto) == bateria          # o contrato com o painel
    assert texto == relatorio.resultado_json(await executar.rodar_bateria(casos, "falso"))   # determinístico
    pasta = relatorio.gravar(bateria, tmp_path / "saida")
    md = (pasta / "relatorio.md").read_text(encoding="utf-8")
    assert "| 01_viavel_ate_assinatura | aprovado | 1/1 |" in md and "## Trava sombra" in md
    transcricao = (pasta / "transcricoes" / "03_periodo_de_graca-com_seguro_1.md").read_text(encoding="utf-8")
    assert "**passou para periododegraca**" in transcricao
    rodada = bateria.cenarios[0].rodadas[0]
    assert rodada.ferramentas["zapsign"] == 1 and rodada.transcricao[0].autor == "lead"


async def test_criterio_da_bateria_critica_reprova_e_alta_tolera_uma_em_tres():
    c = caso("01")
    boa = relatorio.RodadaJ(n=1, aprovado=True)
    alta = relatorio.RodadaJ(n=2, aprovado=False, falhas=[relatorio.FalhaJ(codigo="cep", gravidade="alta")])
    critica = relatorio.RodadaJ(n=3, aprovado=False, falhas=[relatorio.FalhaJ(codigo="promessa", gravidade="critica")])
    assert relatorio.cenario_j(c, [boa, alta, boa.model_copy(update={"n": 3})]).aprovado is True
    assert relatorio.cenario_j(c, [boa, alta, alta.model_copy(update={"n": 3})]).aprovado is False
    assert relatorio.cenario_j(c, [boa, boa.model_copy(update={"n": 2}), critica]).aprovado is False
    assert relatorio.cenario_j(c, [boa, alta, critica]).por_checagem == {"cep": "1/3", "promessa": "1/3"}


def test_estimativa_do_modo_real_sem_chamar_a_api():
    estimativa = executar.estimar(cenario.casos(["01", "06"]), rodadas=3, juiz=True)
    assert estimativa.modelo == "gpt-4.1-mini" and len(estimativa.por_cenario) == 2
    assert 0 < estimativa.total_usd < 1 and estimativa.total_com_cache_usd <= estimativa.total_usd
    assert "US$" in estimativa.texto()


async def test_modo_real_recusa_sem_teto_e_sem_chave(monkeypatch):
    from app import config

    casos = cenario.casos(["01"])
    with pytest.raises(executar.ErroDeExecucao, match="--teto-usd"):
        executar.exigir_modo_real(casos, None)
    with pytest.raises(executar.ErroDeExecucao, match="--teto-usd"):
        await executar.rodar_bateria(casos, "real")
    monkeypatch.setattr(config, "_carregar_env_local", lambda *a, **k: None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(executar.ErroDeExecucao, match="OPENAI_API_KEY"):
        await executar.rodar_bateria(casos, "real", teto_usd=1.0)


def test_cli_estimar_listar_e_recusa_do_real(capsys):
    from app.avaliacao.__main__ import main

    assert main(["listar"]) == 0
    assert main(["estimar", "--rodadas", "2", "--cenario", "02"]) == 0
    assert main(["rodar", "--real", "--cenario", "01"]) == 2


# ---------------------------------------------------------------------------- juiz (código; a chamada real é só no modo real)
async def test_juiz_descarta_evidencia_inventada_e_so_confirma_com_checagem():
    conversa = await conversar("01")
    dados = {"resumo": "ok", "criterios": [
        {"nome": "tom", "nota": 5, "evidencia": "Imagino como isso atrapalha o dia a dia.", "violou_regra": False, "comentario": ""},
        {"nome": "conducao", "nota": 2, "evidencia": "frase que não existe na conversa", "violou_regra": False, "comentario": ""},
        {"nome": "fidelidade", "nota": 2, "evidencia": "", "violou_regra": True, "comentario": "inventou prazo"},
    ]}
    parecer = await juiz.julgar(ModeloFalso({"juiz": dados}), conversa)
    assert [c.nome for c in parecer.criterios] == ["tom", "fidelidade"] and parecer.sem_evidencia == ["conducao"]
    assert parecer.revisar == ["fidelidade: inventou prazo"] and parecer.confirmadas == []
    confirmado = juiz.conferir_parecer(dados, juiz.transcricao(conversa), {"numero_inventado"})
    assert confirmado.confirmadas == ["fidelidade: inventou prazo"]
    assert juiz.concordancia([parecer], [{"tom": True, "fidelidade": True}]) == 0.5


async def test_comparar_ab_desfaz_a_ordem_sorteada():
    a, b = await conversar("06"), await conversar("06")
    resposta = {"resumo": "", "criterios": [{"nome": "tom", "preferida": "1", "motivo": "mais gentil"}]}
    for semente in range(6):
        resultado = await juiz.comparar_ab(ModeloFalso({"juiz": resposta}), a, b, semente=semente)
        esperado = "B" if resultado["ordem_sorteada"] == "B,A" else "A"
        assert resultado["criterios"][0]["preferida"] == esperado


def test_checagens_regras_ignoram_frases_permitidas_no_prompt():
    c = caso("01")
    regras = checagens.Regras(c, c.carregar_agente())
    frase = "Pelo que você me contou, vale a pena a nossa equipe olhar o seu caso com carinho."
    assert checagens._vazou(frase, regras) is None
    # Só as linhas sensíveis (DECISÃO, regra interna, prazo em meses) contam: o "como falar" a IA segue, não vaza.
    assert checagens._vazou("Olha: não explique regras do INSS, prazos ou valores nesta etapa.", regras) is None
    assert checagens._vazou("Regra: carteira assinada na época do acidente, com sequela, sem aposentadoria.", regras)
