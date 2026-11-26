"""O turno do cérebro com um modelo de mentira: prova o que o CÓDIGO garante."""

from app.cerebro import turno
from app.cerebro.travas import conferir
from app.cerebro.formatador import formatar
from app.modelo import ErroModelo, ModeloFalso

SEM_INTENCAO = {n: False for n in (
    "pediu_humano", "pediu_para_parar", "engano", "aceitou_honorarios", "recusou", "diz_que_assinou")}


def extrai(fatos=(), sinais=(), **intencoes):
    return {
        "fatos": [{"chave": c, "valor": v, "trecho": t} for c, v, t in fatos],
        "sinais": list(sinais),
        "intencoes": {**SEM_INTENCAO, **intencoes},
    }


def fala(*textos):
    return {"mensagens": [{"tipo": "texto", "texto": t, "chave": ""} for t in textos]}


def entrada(novas, etapa="sdr", **extra):
    return turno.Entrada(escritorio="Escritório Teste", agente="Júlia", etapa=etapa, novas=list(novas), **extra)


async def test_fato_com_trecho_e_aceito_e_a_ia_pergunta_o_que_falta():
    modelo = ModeloFalso({
        "extrator": extrai([("acidente_descricao", "caí da moto", "caí da moto"), ("acidente_ano", "2022", "em 2022")]),
        "etapa": fala("Poxa, sinto muito pelo acidente.", "Ficou com alguma sequela ou limitação?"),
    })
    saida = await turno.processar(modelo, entrada(["oi, caí da moto em 2022"]))
    assert saida.situacao == "respondido" and saida.etapa_depois == "sdr"
    assert saida.fatos_depois == {"acidente_descricao": "caí da moto", "acidente_ano": 2022}
    assert saida.faltam[0] == "sequela"
    assert [m["texto"] for m in saida.mensagens] == [
        "Poxa, sinto muito pelo acidente.", "Ficou com alguma sequela ou limitação?"]
    # O agente recebeu só a pergunta do que falta.
    assert "se ficou com alguma sequela" in modelo.pedidos[1]["conteudo"]


async def test_fato_inventado_e_descartado():
    modelo = ModeloFalso({
        "extrator": extrai([("aposentado", "sim", "sou aposentado")]),   # o lead não disse isso
        "etapa": fala("Me conta o que aconteceu?"),
    })
    saida = await turno.processar(modelo, entrada(["bom dia"]))
    assert saida.fatos_depois == {}
    assert saida.fatos_rejeitados[0]["motivo"] == "trecho_nao_encontrado"
    assert saida.etapa_depois == "sdr"                                   # não desqualificou por invenção
    assert saida.eventos[0]["tipo"] == "fato_sem_prova"


async def test_trecho_aceita_diferenca_de_acento_e_maiuscula():
    modelo = ModeloFalso({
        "extrator": extrai([("vinculo_na_data", "clt", "Tinha carteira assinada")]),
        "etapa": fala("Entendi."),
    })
    saida = await turno.processar(modelo, entrada(["tinha  CARTEIRA assinada sim"]))
    assert saida.fatos_depois == {"vinculo_na_data": "clt"}


async def test_troca_de_etapa_vale_no_mesmo_turno():
    fatos = {"acidente_descricao": "queda", "acidente_ano": 2023, "sequela": "sim",
             "aposentado": "nao", "tem_advogado_no_caso": "nao"}
    modelo = ModeloFalso({
        "extrator": extrai([("vinculo_na_data", "clt", "carteira assinada")]),
        "etapa": fala("Pelo que você contou, vale a pena o escritório cuidar do seu caso."),
    })
    saida = await turno.processar(modelo, entrada(["tinha carteira assinada"], fatos=fatos))
    assert (saida.etapa_antes, saida.etapa_depois) == ("sdr", "closer")
    assert "ETAPA: explicar como o escritório pode ajudar" in modelo.pedidos[1]["sistema"]
    assert saida.decisoes[0]["resultado"] == "qualificado"


async def test_desqualificado_encerra_depois_da_mensagem():
    modelo = ModeloFalso({
        "extrator": extrai([("aposentado", "sim", "já sou aposentado")]),
        "etapa": fala("Entendi. Nesse caso o escritório não consegue atuar, mas fico à disposição."),
    })
    saida = await turno.processar(modelo, entrada(["já sou aposentado"]))
    assert saida.etapa_depois == "desqualificado"
    assert (saida.estado_lead, saida.motivo_estado) == ("encerrado", "desqualificado:aposentado")
    assert "já é aposentada" in modelo.pedidos[1]["conteudo"]            # motivo em linguagem simples


async def test_promessa_e_refeita_uma_vez():
    modelo = ModeloFalso({
        "extrator": extrai(),
        "etapa": [fala("Pode ficar tranquilo, você vai ganhar!"), fala("Me conta como foi o acidente?")],
    })
    saida = await turno.processar(modelo, entrada(["tenho direito?"]))
    assert saida.reprovacoes[0][0]["codigo"] == "promessa" and saida.reprovacoes[1] == []
    assert saida.mensagens[0]["texto"] == "Me conta como foi o acidente?"
    assert "SUA RESPOSTA ANTERIOR FOI RECUSADA" in modelo.pedidos[2]["conteudo"]


async def test_reprovou_duas_vezes_nao_manda_o_texto_da_ia():
    modelo = ModeloFalso({"extrator": extrai(), "etapa": [fala("É garantido!"), fala("Com certeza você ganha.")]})
    saida = await turno.processar(modelo, entrada(["e aí?"]))
    assert saida.estado_lead == "pausado" and saida.motivo_estado == "trava_persistente"
    assert saida.mensagens[0]["texto"] == turno.MENSAGENS_FIXAS["seguranca"]
    assert saida.eventos[-1]["tipo"] == "trava_persistente"


async def test_pediu_humano_pausa_sem_chamar_o_agente():
    modelo = ModeloFalso({"extrator": extrai(pediu_humano=True)})
    saida = await turno.processar(modelo, entrada(["quero falar com uma pessoa"]))
    assert (saida.estado_lead, saida.motivo_estado) == ("pausado", "pediu_humano")
    assert len(modelo.pedidos) == 1


async def test_pediu_para_parar_encerra():
    modelo = ModeloFalso({"extrator": extrai(pediu_para_parar=True)})
    saida = await turno.processar(modelo, entrada(["para de me mandar mensagem"]))
    assert saida.estado_lead == "encerrado"


async def test_sinal_passa_para_a_equipe():
    modelo = ModeloFalso({"extrator": extrai(sinais=["quer_videochamada"])})
    saida = await turno.processar(modelo, entrada(["pode ser por chamada de vídeo?"]))
    assert saida.estado_lead == "pausado" and saida.eventos[0]["tipo"] == "sinal_quer_videochamada"


async def test_ia_fora_do_ar_fica_em_silencio_e_avisa():
    def cai(_sistema, _conteudo):
        raise ErroModelo("sem_credito")

    saida = await turno.processar(ModeloFalso({"extrator": cai}), entrada(["oi"]))
    assert saida.situacao == "erro" and saida.mensagens == []
    assert saida.eventos[0]["gravidade"] == "critico" and saida.eventos[0]["responsavel"] == "cliente"


def _texto(t):
    return [{"tipo": "texto", "texto": t}]


def _codigos(texto, etapa="sdr", honorarios=None, faltam=("sequela",)):
    return {r.codigo for r in conferir(_texto(texto), etapa=etapa, honorarios=honorarios, midias={}, faltam=faltam)}


def test_travas():
    assert _codigos("Me conta como foi o acidente?") == set()
    assert "link" in _codigos("Veja em https://exemplo.com")
    assert "termo_tecnico" in _codigos("Você perdeu a qualidade de segurado.")
    assert "dado_pessoal_fora_de_hora" in _codigos("Me passa seu CPF?")
    assert "dado_pessoal_fora_de_hora" not in _codigos("Me passa seu CPF?", etapa="coleta_dados")
    assert "muitas_perguntas" in _codigos("Tudo bem? Como foi o acidente?")
    assert "texto_interno" in _codigos("Vou te passar para o closer.")
    assert "honorarios" in _codigos("Cobramos 20% no final.")                          # fora do closer
    assert "honorarios" in _codigos("Cobramos 20% no final.", etapa="closer", honorarios="30% do valor recebido")
    assert "honorarios" not in _codigos("São 30% só no final.", etapa="closer", honorarios="30% do valor recebido")
    assert "pergunta_no_encerramento" in _codigos("Posso ajudar em algo mais?", etapa="desqualificado", faltam=())
    assert "resposta_vazia" in {r.codigo for r in conferir([], etapa="sdr", honorarios=None, midias={}, faltam=())}


def test_formatador():
    saida = formatar(_texto("**Oi, Maria!**\n\nMe conta — com calma — como foi?"))
    assert [m["texto"] for m in saida] == ["Oi, Maria!", "Me conta, com calma, como foi?"]
    longo = formatar(_texto(" ".join(["Esta é uma frase de tamanho médio para o teste."] * 12)))
    assert len(longo) > 1 and all(len(m["texto"]) <= 320 for m in longo)


async def test_auditor_confirma_recusa_ou_falha():
    # Confirmado: pausa e manda a mensagem do auditor.
    modelo = ModeloFalso({"extrator": extrai(sinais=["nao_sabe_ler"]),
                          "auditor": {"valido": True, "motivo": "disse que não sabe ler", "mensagem": "Sem problema! Vou te mandar um áudio, tá bom?"}})
    saida = await turno.processar(modelo, entrada(["eu nao sei ler"], modelo_auditor="gpt-6-luna"))
    assert saida.estado_lead == "pausado" and saida.sinais == ["nao_sabe_ler"]
    assert saida.mensagens[0]["texto"] == "Sem problema! Vou te mandar um áudio, tá bom?"
    assert saida.contexto["auditor"][0]["valido"] is True

    # Recusado: segue o atendimento normal, sem pausar.
    modelo = ModeloFalso({"extrator": extrai(sinais=["quer_audio"]),
                          "auditor": {"valido": False, "motivo": "só mandou áudio", "mensagem": "x"},
                          "etapa": fala("Entendi. Como foi o acidente?")})
    saida = await turno.processar(modelo, entrada(["(áudio) oi"], modelo_auditor="gpt-6-luna"))
    assert saida.estado_lead is None and saida.sinais == [] and saida.mensagens[0]["texto"] == "Entendi. Como foi o acidente?"
    assert any(e["tipo"] == "sinal_recusado" for e in saida.eventos)

    # Auditor fora do ar: chama a equipe por segurança, com a mensagem fixa.
    modelo = ModeloFalso({"extrator": extrai(sinais=["quer_videochamada"])})
    saida = await turno.processar(modelo, entrada(["dá pra fazer chamada de vídeo?"], modelo_auditor="gpt-6-luna"))
    assert saida.estado_lead == "pausado" and saida.mensagens[0]["texto"] == turno.MENSAGENS_FIXAS["sinal"]
    assert any(e["tipo"] == "auditor_falhou" for e in saida.eventos)
