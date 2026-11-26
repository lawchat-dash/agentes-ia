"""Cenários de variação sc10 a sc19 do Sousa e Costa (avaliacao/cenarios_sousa_costa/sc1*.json).

Cada cenário testa uma regra do prompt do escritório (SDR, Período de Graça, Closer, Contrato, Assinatura): sem e-mail,
CEP não encontrado, advogado, aposentado, acidente fora do trabalho, MEI, desempregado, rural, sinais e objeção de preço.
Dados 100% inventados. Aqui só se prova, de graça: que todos carregam (cenario.carregar), que o gabarito segue o prompt
do escritório (e não as Regras() genéricas quando elas divergem), que o cartão do lead responde às perguntas literais do
prompt e, com o modelo roteirizado se comportando como o prompt manda, que o gabarito não acusa falha à toa.
A qualidade do prompt com o modelo de verdade é o modo real (pago), que o orquestrador roda.
"""

import re

import pytest

from app.avaliacao import cenario, falso, leads, simulador
from app.avaliacao.falso import passo
from app.contrato import dados as cdados

PASTA = cenario.PASTA / "cenarios_sousa_costa"
AGENTE = "avaliacao/agentes/sousa_costa.json"
MIDIA = "https://mqkgzkzlysvwjjuwvxul.supabase.co/storage/v1/object/public/midia/"

# id do caso -> (trajetória, destino de qualificação, estado final). None = o cenário não confere.
GABARITO = {
    "sc10_contrato_sem_email": (["sdr", "closer", "contratos", "assinatura", "contrato_assinado"], "closer", "encerrado"),
    "sc11_cep_nao_encontrado": (["sdr", "closer", "contratos", "assinatura", "contrato_assinado"], "closer", "encerrado"),
    "sc12_ja_tem_advogado[atuando_hoje]": (["sdr", "desqualificado"], "desqualificado", "ativo"),
    "sc12_ja_tem_advogado[quer_trocar]": (["sdr"], "analise_humana", "pausado"),
    "sc12_ja_tem_advogado[so_no_passado]": (["sdr", "closer"], "closer", None),
    "sc13_aposentado[aposentada_por_invalidez]": (["sdr", "desqualificado"], "desqualificado", "ativo"),
    "sc13_aposentado[ja_recebe_auxilio_acidente]": (["sdr", "desqualificado"], "desqualificado", "ativo"),
    "sc14_acidente_fora_do_trabalho_clt": (["sdr", "closer"], "closer", None),
    "sc15_mei_autonomo[teve_clt_ha_meses]": (["sdr", "periododegraca", "closer"], "closer", None),
    "sc15_mei_autonomo[nunca_clt]": (["sdr", "desqualificado"], "desqualificado", None),
    # Prompt ambíguo (5.1 x TRAVAS): vale direto do SDR ou pelo período de graça; só o destino é conferido.
    "sc15_mei_autonomo[saiu_ha_mais_de_3_anos]": (None, "desqualificado", None),
    "sc16_desempregado_periodo_de_graca[com_seguro]": (["sdr", "periododegraca", "closer"], "closer", None),
    "sc16_desempregado_periodo_de_graca[sem_seguro]": (["sdr", "periododegraca", "desqualificado"], "desqualificado", "ativo"),
    "sc17_segurado_especial_rural[com_documentos]": (["sdr", "closer"], "closer", None),
    "sc17_segurado_especial_rural[sem_documentos]": (["sdr", "desqualificado"], "desqualificado", "ativo"),
    "sc18_sinais_video_audio_leitura[videochamada_prioridade]": (["sdr", "closer"], None, "pausado"),
    "sc18_sinais_video_audio_leitura[pede_audio]": (["sdr"], None, "pausado"),
    "sc18_sinais_video_audio_leitura[nao_sabe_ler]": (["sdr"], None, "pausado"),
    "sc19_objecao_preco": (["sdr", "closer", "contratos"], "closer", None),
}


def arquivos():
    return sorted(PASTA.glob("sc1[0-9]_*.json"))


def casos():
    return {c.id: c for p in arquivos() for c in cenario.expandir(cenario.carregar(p))}


def test_os_dez_cenarios_carregam_e_apontam_para_o_agente_do_sousa_costa():
    nomes = [p.stem.split("_")[0] for p in arquivos()]
    assert nomes == [f"sc{n}" for n in range(10, 20)]
    telefones = set()
    for p in arquivos():
        cen = cenario.carregar(p)
        assert cen.id == p.stem and cen.agente == AGENTE and cen.lead.tipo == "cartao"
        assert "prompt" in cen.descricao.lower()                # a descrição cita a regra do prompt do escritório
        assert cen.carregar_agente()["escritorio"]["nome"] == "Sousa e Costa Advogados"
        telefones.add(cen.lead.telefone)
    assert len(telefones) == 10                                  # cada lead com um número inventado próprio
    assert set(casos()) == set(GABARITO)
    assert [c.id for c in cenario.casos(["sc15"], pasta=PASTA)] == [i for i in GABARITO if i.startswith("sc15")]


@pytest.mark.parametrize("id_caso", list(GABARITO))
def test_gabarito_segue_o_prompt_do_escritorio(id_caso):
    caso = casos()[id_caso]
    trajetoria, destino, estado = GABARITO[id_caso]
    assert caso.esperado.trajetoria == trajetoria
    alvo = caso.destino_esperado()
    assert (alvo.destino if alvo else None) == destino
    assert caso.esperado.estado_final == estado
    # Desqualificado do escritório pede confirmação e nota de 1 a 5: a regra genérica "sem pergunta" fica desligada.
    if "desqualificado" in (trajetoria or []) or destino == "desqualificado":
        assert caso.esperado.sem_pergunta_em == []
    # As invenções dos chats reais ficam proibidas em todos.
    assert len(caso.esperado.proibido) >= 7


def test_oraculo_so_onde_concorda_com_o_prompt():
    """Onde as Regras() divergem do prompt do escritório, o destino é fixo (e a descrição explica)."""
    fixos = {i for i, c in casos().items() if isinstance(c.esperado.destino_qualificacao, str)}
    assert fixos == {"sc12_ja_tem_advogado[atuando_hoje]", "sc12_ja_tem_advogado[quer_trocar]",
                     "sc12_ja_tem_advogado[so_no_passado]", "sc13_aposentado[ja_recebe_auxilio_acidente]",
                     "sc15_mei_autonomo[nunca_clt]", "sc15_mei_autonomo[saiu_ha_mais_de_3_anos]",
                     "sc17_segurado_especial_rural[sem_documentos]"}
    for i in fixos:
        assert "fixo" in casos()[i].descricao.lower()
    # Aposentado e advogado não são perguntados pelo SDR do escritório no caminho CLT: o cartão responde se a IA
    # perguntar, mas sem 'fatos', então o oráculo não cobra essas perguntas (pulou_pergunta).
    for i, c in casos().items():
        if isinstance(c.esperado.destino_qualificacao, dict) and not i.startswith("sc13"):
            for a in c.lead.assuntos:
                if any(re.search(q, "Você já é aposentado?") for q in a.quando):
                    assert not a.fatos, i


def test_dados_sao_inventados():
    for c in casos().values():
        v = c.lead.verdade
        if "cpf" in v:
            assert cdados.cpf_valido(v["cpf"])
        if "email" in v:
            assert v["email"].endswith("@exemplo.invalid")
        assert re.fullmatch(r"55319900001[0-9]{2}", c.lead.telefone)
        for endereco in c.ferramentas.cep.values():
            assert "Exemplo" in endereco["logradouro"] and "Exemplo" in endereco["cidade"]
    sc10, sc11 = casos()["sc10_contrato_sem_email"], casos()["sc11_cep_nao_encontrado"]
    assert re.sub(r"\D", "", sc10.lead.verdade["cep"]) in sc10.ferramentas.cep           # o CepFalso resolve
    assert re.sub(r"\D", "", sc11.lead.verdade["cep"]) not in sc11.ferramentas.cep       # o CepFalso não encontra


def test_proibido_pega_as_invencoes_dos_chats_e_deixa_passar_o_certo():
    proibido = casos()["sc10_contrato_sem_email"].esperado.proibido

    def barra(texto):
        return any(re.search(r, texto) for r in proibido)

    for errado in ("Sim, é necessário imprimir todas as páginas, assinar e enviar a foto para nossa equipe.",
                   "Para garantir a validade, é preciso assinar manualmente.",
                   "Você conseguiu enviar a foto do contrato assinado para nossa equipe?",
                   "Geralmente, o processo leva cerca de 3 a 6 meses.",
                   "Nossa equipe entra em contato com o INSS em até 5 dias úteis.",
                   "Sim, o rompimento do tendão será incluído como sequela no seu caso.",
                   "Entendo, mas precisamos iniciar a formalização agora.",
                   "Quando você criar um e-mail me manda, por favor.",
                   "O contrato vai ser enviado por e-mail."):
        assert barra(errado), errado
    for certo in ("Não precisa imprimir nem assinar à mão: a assinatura é digital, pelo link.",
                  "Sem problema, seguimos sem.", "Pode assinar pelo celular mesmo.",
                  "Qual o seu e-mail? Se não tiver, seguimos sem.",
                  "Excelente! Por gentileza, me informe seu nome completo para darmos continuidade à formalização."):
        assert not barra(certo), certo


# ---------------------------------------------------------------------------- cartão x perguntas literais do prompt
BOAS_VINDAS = [MIDIA + "PTV.mp4", "Olá! Me chamo Ana, do escritório Sousa e Costa Advogados.\n\nMe conta como aconteceu o "
               "acidente. De forma direta, vamos precisar de detalhes especificos para o pedido , mas caso não se lembre "
               "agora, não se preocupe, vamos perguntar com calma todas etapas tudo bem?"]
CLT = ["Você estava trabalhando de carteira assinada (CLT) quando o acidente aconteceu?"]
MEI = ["Na época do acidente, você atuava como MEI, Autônomo ou Contribuinte Individual?"]
RURAL = ["Você é segurado especial (trabalhador rural, agricultor, pescador artesanal)?"]
PG_DEMISSAO = ["Qual foi o mês e o ano da sua demissão antes do acidente?"]


async def _respostas(id_caso, roteiro):
    lead = leads.criar(casos()[id_caso].lead)
    lead.abrir()
    saida = []
    for n, enviadas in enumerate(roteiro, start=2):
        falas = await lead.responder(enviadas, rodada=n)
        assert falas is not None, (id_caso, lead.invalido)
        saida.append(falas[0])
    return saida


async def test_cartao_responde_a_boas_vindas_com_o_acidente_e_nao_com_o_nome_do_escritorio():
    # "Sousa e Costa Advogados" no balão de boas-vindas não pode casar com a pergunta do advogado.
    for id_caso in GABARITO:
        if "[pede_audio]" in id_caso or "[nao_sabe_ler]" in id_caso:
            continue
        (fala,) = await _respostas(id_caso, [BOAS_VINDAS])
        assert "advogado nenhum" not in fala.texto_corrido() and fala.origem.startswith("assunto:"), (id_caso, fala)


async def test_perguntas_obrigatorias_do_prompt_nao_contam_como_repetidas():
    # Depois do "não" na carteira, o prompt manda perguntar MEI (5), rural (6) e desempregado (7.1): não é repetição.
    falas = await _respostas("sc16_desempregado_periodo_de_graca[com_seguro]",
                             [BOAS_VINDAS, CLT, MEI, RURAL, ["Então você estava desempregado na época do acidente?"],
                              PG_DEMISSAO])
    assert all(f.origem.startswith("assunto:") for f in falas), [(f.origem, f.texto_corrido()) for f in falas]
    assert "março de 2023" in falas[-1].texto_corrido()
    falas = await _respostas("sc15_mei_autonomo[teve_clt_ha_meses]", [BOAS_VINDAS, CLT, MEI])
    assert falas[-1].origem.startswith("assunto:") and "mei" in falas[-1].texto_corrido()


# ---------------------------------------------------------------------------- roteirizado: o gabarito não acusa à toa
def _extrator(sistema, conteudo):
    """O extrator de regras do roteirizado, mais o CPF com ponto no lugar do hífen, o número solto da casa e o pedido
    de áudio (sinal quer_audio), que os cartões destes cenários usam."""
    dados = falso.extrator_de_regras(sistema, conteudo)
    texto, ultima = falso._secoes(conteudo)
    chaves = {f["chave"] for f in dados["fatos"]}
    if "cpf" not in chaves and (m := re.search(r"\d{3}\.\d{3}\.\d{3}\.\d{2}", texto)):
        d = re.sub(r"\D", "", m.group(0))
        dados["fatos"].append({"chave": "cpf", "valor": f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}", "trecho": m.group(0)})
    if "numero_casa" not in chaves and re.search(r"(?i)n[úu]mero", ultima) and (m := re.match(r"\s*(\d{1,5})\b", texto)):
        dados["fatos"].append({"chave": "numero_casa", "valor": m.group(1), "trecho": m.group(1)})
    if re.search(r"(?i)manda\w* [áa]udio", texto):
        dados["sinais"] = ["quer_audio"]
    return dados


def _boas_vindas():
    return passo(MIDIA + "PTV.mp4", "Olá! Me chamo Ana, do escritório Sousa e Costa Advogados.",
                 "Me conta como aconteceu o acidente?")


DESQ = ("Analisei com atenção o que você nos contou e, neste momento, pelas regras atuais, você não se enquadra nos critérios "
        "para esse benefício específico. Sei que essa não é a resposta que muita gente espera receber, De toda forma, se sua "
        "situação mudar no futuro ou se surgir outro direito que possamos avaliar, será um prazer te ajudar novamente. "
        "Conte conosco!")
NOTA = passo("Antes de encerrar, pode me avaliar com uma nota de 1 a 5 sobre o atendimento?")
PARA_CLOSER = passo("Maravilha! Nós podemos te ajudar no seu caso.", "Posso te explicar como funciona o Auxílio-Acidente?",
                    transferir="closer")

ROTEIROS = {
    "sc10_contrato_sem_email": {
        "sdr": [_boas_vindas(), passo("Sinto muito pelo acidente.", "Em qual ano aconteceu o acidente?"),
                passo("Você recebeu auxílio-doença na época do acidente?"),
                passo("Você estava trabalhando de carteira assinada (CLT) quando o acidente aconteceu?"), PARA_CLOSER],
        "closer": [
            passo(MIDIA + "Como%20Funciona%20o%20Auxilio%20Acidente.ogg", "Conseguiu entender certinho como funciona o benefício?"),
            passo("Quero te mostrar, de forma bem simples, o que muda na sua vida quando esse benefício é aprovado.",
                  "Essas vantagens fariam diferença no seu dia a dia?"),
            passo("Antes de falar em valor ou contrato, quero te mostrar por que vale a pena fazer tudo com a gente.",
                  MIDIA + "video-honorarios-5salarios.mp4", "Conseguiu entender certinho as condições dos honorários?"),
            passo("Perfeito! Vamos avançar para a formalização da nossa representação. Podemos iniciar a coleta dos seus dados?"),
            passo("Excelente! Por gentileza, me informe seu nome completo para darmos continuidade à formalização.",
                  transferir="contratos"),
        ],
        "contratos": [
            passo(MIDIA + "PedidoDocumento.mp4", "Agora me informe o seu CPF, por favor."),
            passo("Você tem RG? Se não tiver, seguimos sem."),
            passo("Sem problema, seguimos sem.", "Qual o seu estado civil?"),
            passo("Qual o seu CEP?"),
            passo("Buscamos nos Correios e o seu endereço é: Rua Exemplo dos Ipês, Jardim Exemplo, Serra Azul do Exemplo/MG.",
                  "Qual o número da casa?"),
            passo("Tem complemento? Se não tiver, é só me dizer."),
            passo("Qual o seu e-mail? Se não tiver, seguimos sem."),
            passo("Sem problema, seguimos sem.", "Qual o seu telefone para contato?"),
            passo("Vamos confirmar juntos todos os seus dados.", "Nome: Osvaldo Brito Lacerda\nCPF: 205.096.961-98\nE-mail: não "
                  "informado\nRG: não informado", "Está tudo correto? Posso gerar o contrato?"),
            passo("Perfeito! Estamos gerando o seu contrato.", ferramenta="zapsign"),
        ],
        # O lead assina sem perguntar nada (a dúvida de imprimir ficou só no sc02).
        "assinatura": [passo("Que ótimo! Vou conferir aqui e já te retorno.")],
    },
    "sc12_ja_tem_advogado[atuando_hoje]": {
        "sdr": [_boas_vindas(),
                passo("Só pra confirmar: você já tem um advogado atuando HOJE no seu caso de auxílio-acidente?"),
                passo("Entendo. Como seu caso já está com um advogado na mesma causa, por ética não posso seguir agora. "
                      "Se encerrar esse contrato no futuro, conte com a gente.", transferir="desqualificado")],
        "desqualificado": [NOTA],
    },
    "sc12_ja_tem_advogado[quer_trocar]": {
        "sdr": [_boas_vindas(),
                passo("Só pra confirmar: você já tem um advogado atuando HOJE no seu caso de auxílio-acidente?"),
                passo("Entendi. Para seguirmos, primeiro é preciso encerrar o contrato com o advogado atual.",
                      notificacao="analise_humana")],
    },
    "sc13_aposentado[aposentada_por_invalidez]": {
        "sdr": [_boas_vindas(), passo("Sinto muito.", "Em qual ano aconteceu o acidente?"),
                passo("Você recebeu auxílio-doença na época do acidente?"), passo(DESQ, transferir="desqualificado")],
        "desqualificado": [NOTA],
    },
    "sc15_mei_autonomo[teve_clt_ha_meses]": {
        "sdr": [_boas_vindas(), passo("Sinto muito.", "Em qual ano aconteceu o acidente?"),
                passo("Você recebeu auxílio-doença na época do acidente?"),
                passo("Você estava trabalhando de carteira assinada (CLT) quando o acidente aconteceu?"),
                passo("Na época do acidente, você atuava como MEI, Autônomo ou Contribuinte Individual?"),
                passo("Quando você sofreu o acidente, há quanto tempo havia saído da última empresa? Eram meses ou já eram anos?"),
                passo("Agora vou confirmar algumas informações importantes sobre seu vínculo com o INSS, tudo bem?",
                      transferir="periododegraca")],
        "periododegraca": [passo("Qual foi a última vez que trabalhou de carteira assinada ( CLT ) antes do acidente ?"),
                           passo("Qual foi o mês e o ano da sua demissão antes do acidente?"),
                           passo("Após essa demissão, você recebeu seguro-desemprego?"), PARA_CLOSER],
    },
    "sc18_sinais_video_audio_leitura[pede_audio]": {"sdr": [_boas_vindas()]},
}


@pytest.mark.parametrize("id_caso", list(ROTEIROS))
async def test_roteirizado_seguindo_o_prompt_passa_no_gabarito(id_caso):
    caso = casos()[id_caso]
    snap = caso.carregar_agente()
    modelo = falso.ModeloRoteirizado(snap, ROTEIROS[id_caso], extrator=_extrator)
    conversa = await simulador.rodar_conversa(caso, modelo, snapshot=snap)
    assert conversa.lead_invalido is None, conversa.lead_invalido
    assert conversa.trajetoria == GABARITO[id_caso][0], (conversa.trajetoria, conversa.parada)
    graves = [f.como_dict() for f in conversa.falhas if f.gravidade in ("critica", "alta")]
    assert conversa.aprovada, graves
    if id_caso == "sc10_contrato_sem_email":
        assert conversa.ferramentas["zapsign"] == 1 and len(conversa.contratos) == 1
        assert "email" not in conversa.contratos[0]["dados"]                      # contrato gerado sem e-mail
        assert conversa.estado_final == "encerrado"


# ---------------------------------------------------------------------------- achados da rodada real 2026-11-25
# A pergunta 2 do SDR ("Em qual ano aconteceu o acidente?"), exigida onde o destino é fixo e o oráculo não cobra a data.
ANO_DO_ACIDENTE = [
    "Em qual ano aconteceu o acidente?", "Em qual ano exatamente aconteceu esse acidente?", "Você lembra o ano do acidente?",
    "Quando foi o acidente?", "Em que ano foi o acidente?", "Qual a data do acidente?",
]
NAO_E_O_ANO = [
    # Perguntas que aparecem em quase toda conversa: não podem satisfazer a exigência do ano.
    "Você estava trabalhando de carteira assinada (CLT) quando o acidente aconteceu?",
    "Quando você sofreu o acidente, há quanto tempo havia saído da última empresa? Eram meses ou já eram anos?",
    "Qual foi o mês e o ano da sua demissão antes do acidente?", "Em que mês você saiu da empresa?",
    "Qual foi a última vez que trabalhou de carteira assinada ( CLT ) antes do acidente ?",
    "Você recebeu auxílio-doença na época do acidente?",
    "Só pra confirmar: você já tem um advogado atuando HOJE no seu caso de auxílio-acidente?",
]
FIXOS_DO_ROTEIRO_COMPLETO = {"sc12_ja_tem_advogado[so_no_passado]": "closer",
                             "sc15_mei_autonomo[nunca_clt]": "desqualificado",
                             "sc15_mei_autonomo[saiu_ha_mais_de_3_anos]": "desqualificado",
                             "sc17_segurado_especial_rural[sem_documentos]": "desqualificado"}


@pytest.mark.parametrize("id_caso", list(FIXOS_DO_ROTEIRO_COMPLETO))
def test_destino_fixo_do_roteiro_completo_exige_o_ano_do_acidente(id_caso):
    caso, destino = casos()[id_caso], FIXOS_DO_ROTEIRO_COMPLETO[id_caso]
    assert isinstance(caso.esperado.destino_qualificacao, str)              # fixo: o oráculo não cobra a data
    regras = caso.esperado.perguntar_antes[destino]
    ano = [r for r in regras if re.search(r, ANO_DO_ACIDENTE[0])]
    assert len(ano) == 1, regras
    for frase in ANO_DO_ACIDENTE:
        assert re.search(ano[0], frase), frase
    for frase in NAO_E_O_ANO:
        assert not re.search(ano[0], frase), frase


def test_travas_imediatas_nao_exigem_o_ano():
    # Aposentado (sc13) desqualifica de imediato: o roteiro completo não vale.
    for i, c in casos().items():
        if i.startswith("sc13"):
            assert not any(re.search(r, ANO_DO_ACIDENTE[0]) for rs in c.esperado.perguntar_antes.values() for r in rs), i


def test_pergunta_ja_respondida_pelo_lead_nao_fica_em_perguntar_antes():
    """SDR linha 54: 'Caso o Lead já tenha informado alguma resposta, não pergunte novamente'. O MEI do sc15 vem na
    abertura ('eu sou mei') e a roça do sc17 na resposta da CLT ('sempre trabalhou na roça')."""
    rural = "Você é segurado especial (trabalhador rural, agricultor, pescador artesanal)?"
    for i, c in casos().items():
        exigidas = [r for rs in c.esperado.perguntar_antes.values() for r in rs]
        if i.startswith("sc15"):
            assert "mei" in c.lead.abertura[0].texto
            assert not any(re.search(r, MEI[0]) for r in exigidas), i
        if i.startswith("sc17"):
            assert not any(re.search(r, rural) for r in exigidas), i
            assert any(re.search(r, "Você tem algum documento dessa época?") for r in exigidas), i


PROVA_RURAL = ("Agora a última coisa que preciso saber é sobre prova do trabalho rural. Você tem algum documento dessa "
               "época? Pode ser:\n• Bloco de produtor\n• Nota de venda da produção\n• Declaração de sindicato\n• PRONAF\n"
               "• Ou até documento de algum parente com quem você trabalhava junto\n\nTem algum desses?")


def test_sc17_aceita_as_duas_interrogacoes_da_mensagem_literal_do_prompt():
    snap = casos()["sc17_segurado_especial_rural[com_documentos]"].carregar_agente()
    sdr = next(e for e in snap["agente"]["etapas"] if e["id"] == "et-sdr")["instrucao"]
    assert "Tem algum desses?" in sdr and PROVA_RURAL.count("?") == 2
    for i, c in casos().items():
        if i.startswith("sc17"):
            assert c.esperado.max_perguntas_por_turno == 2, i


async def test_sc10_pedido_de_cpf_com_numeros_e_digitos_nao_vira_numero_da_casa():
    """T13: '...o CPF completo e correto, com os números e dígitos verificadores.' (sem '?') não é o número da casa."""
    for id_caso in ("sc10_contrato_sem_email", "sc11_cep_nao_encontrado"):
        lead = leads.LeadCartao(casos()[id_caso].lead)
        lead.abrir()
        await lead.responder(["Agora me informe o seu CPF, por favor."], rodada=12)
        (fala,) = await lead.responder(["Por favor, verifique e me envie novamente o CPF completo e correto, com os "
                                        "números e dígitos verificadores."], rodada=13)
        assert fala.origem.startswith("repetida:"), (id_caso, fala.origem, fala.texto_corrido())
        (fala,) = await lead.responder(["Qual o número da casa?"], rodada=14)
        numero = casos()[id_caso].lead.verdade["numero_casa"]
        assert fala.origem.startswith("assunto:") and numero in fala.texto_corrido(), (id_caso, fala.texto_corrido())


def test_sc10_manda_o_cpf_limpo_e_a_variacao_tem_cenario_proprio():
    sc10 = casos()["sc10_contrato_sem_email"]
    cpf = next(a for a in sc10.lead.assuntos if "cpf" in a.fatos).responde.texto_corrido()
    assert cpf == sc10.lead.verdade["cpf"] == sc10.esperado.fatos["cpf"]
    sc20 = cenario.carregar(PASTA / "sc20_cpf_pontuacao_torta.json")
    torto = next(a for a in sc20.lead.assuntos if "cpf" in a.fatos).responde.texto_corrido()
    assert re.fullmatch(r"\d{3}\.\d{3}\.\d{3}\.\d{2}", torto) and "ponto no lugar do hífen" in sc20.descricao.lower()


ETAPA3 = ["Antes de falar em valor ou contrato, quero te mostrar por que vale a pena fazer tudo com a gente.",
          "Cálculo exato feito por especialista.", "Atendimento simples e 100% online.", "Processo seguro e estratégico.",
          "Você só paga se o benefício for aprovado."]
OFERTA = ["Entendo sua dúvida. Nosso trabalho é seguro e você não paga nada se não conseguir o benefício.",
          "Quer que eu te mostre as condições dos honorários para você entender melhor?"]
ETAPA4 = [MIDIA + "video-honorarios-5salarios.mp4", "Conseguiu entender certinho as condições dos honorários?"]


@pytest.mark.parametrize("id_caso", ["sc19_objecao_preco", "sc18_sinais_video_audio_leitura[videochamada_prioridade]"])
async def test_objecao_dos_honorarios_so_depois_do_video(id_caso):
    lead = leads.LeadCartao(casos()[id_caso].lead)
    lead.abrir()
    (fala,) = await lead.responder(ETAPA3, rodada=8)
    assert fala.texto_corrido() == "entendi, ok", fala.texto_corrido()       # não o 'sei nao' do padrão
    (fala,) = await lead.responder(OFERTA, rodada=9)
    assert fala.texto_corrido() == "pode mandar", fala.texto_corrido()       # aceita ver, não objeta a um preço que não viu
    (fala,) = await lead.responder(ETAPA4, rodada=10)
    assert fala.origem == "gatilho:0", fala.origem
    texto = fala.texto_corrido()
    assert ("caro" in texto) if id_caso.startswith("sc19") else ("video chamada" in texto), texto


def _desq_rural():
    return {
        "sdr": [_boas_vindas(), passo("Sinto muito pelo seu pai.", "Em qual ano aconteceu o acidente?"),
                passo("Ele recebeu auxílio-doença na época do acidente?"),
                passo("Ele estava trabalhando de carteira assinada (CLT) quando o acidente aconteceu?"),
                # A roça já foi dita na resposta da CLT: o prompt pula a 6 e vai à mensagem literal da prova rural.
                passo(PROVA_RURAL), passo(DESQ, transferir="desqualificado")],
        "desqualificado": [NOTA],
    }


def _so_no_passado():
    return {"sdr": [_boas_vindas(),
                    passo("Sinto muito.", "Só pra confirmar: você já tem um advogado atuando HOJE no seu caso de "
                          "auxílio-acidente?"),
                    passo("Em qual ano aconteceu o acidente?"),
                    passo("Você recebeu auxílio-doença na época do acidente?"),
                    passo("Você estava trabalhando de carteira assinada (CLT) quando o acidente aconteceu?"),
                    PARA_CLOSER]}


async def _rodar_roteiro(id_caso, roteiro):
    caso = casos()[id_caso]
    snap = caso.carregar_agente()
    modelo = falso.ModeloRoteirizado(snap, roteiro, extrator=_extrator)
    return await simulador.rodar_conversa(caso, modelo, snapshot=snap)


@pytest.mark.parametrize("id_caso,roteiro", [("sc17_segurado_especial_rural[sem_documentos]", _desq_rural),
                                             ("sc12_ja_tem_advogado[so_no_passado]", _so_no_passado)])
async def test_roteiro_completo_seguindo_o_prompt_passa_e_sem_o_ano_reprova(id_caso, roteiro):
    conversa = await _rodar_roteiro(id_caso, roteiro())
    assert conversa.lead_invalido is None, conversa.lead_invalido
    assert conversa.trajetoria == GABARITO[id_caso][0], (conversa.trajetoria, conversa.parada)
    graves = [f.como_dict() for f in conversa.falhas if f.gravidade in ("critica", "alta")]
    assert conversa.aprovada, graves
    assert not conversa.codigos() & {"pulou_pergunta", "varias_perguntas", "varias_perguntas_frequentes"}, graves
    # O erro da rodada real: a IA pula a pergunta 2 (o ano) e a conversa passava.
    sem_ano = roteiro()
    sem_ano["sdr"] = [p for p in sem_ano["sdr"] if not any("Em qual ano" in str(m) for m in p["mensagens"])]
    conversa = await _rodar_roteiro(id_caso, sem_ano)
    puladas = [f for f in conversa.falhas if f.codigo == "pulou_pergunta"]
    assert puladas and not conversa.aprovada, [f.como_dict() for f in conversa.falhas]
