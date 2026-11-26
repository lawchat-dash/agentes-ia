"""Cenário sc02 do Sousa e Costa (avaliacao/cenarios_sousa_costa/sc02_relato_completo_sem_laudo.json), de graça.

Inspirado no CHAT 2 real, com fatos, falas e dados inventados (só o jeito do lead foi aproveitado): o lead conta tudo na 1ª resposta, não tem mais
documentação médica, manda o RG por foto e "Número 318 Fundos" numa mensagem só, e assina pela ZapSign. Aqui se prova
que o cenário carrega, que o cartão e os 'proibido' pegam os erros do chat (pergunta repetida, imprimir/assinar à mão/
foto do contrato, prazo inventado) e que o caminho bom roda do SDR ao contrato assinado com o modelo roteirizado.
A qualidade do prompt é o modo real (pago), rodado pelo orquestrador.
"""

import re
from pathlib import Path

import pytest

from app.avaliacao import cenario, falso, leads, simulador
from app.avaliacao.falso import passo

ARQUIVO = cenario.RAIZ / "avaliacao" / "cenarios_sousa_costa" / "sc02_relato_completo_sem_laudo.json"
MIDIA = "https://mqkgzkzlysvwjjuwvxul.supabase.co/storage/v1/object/public/midia/"
TRAJETORIA = ["sdr", "closer", "contratos", "assinatura", "contrato_assinado"]


def carregar():
    return cenario.carregar(ARQUIVO)


def proibido(texto: str) -> list[str]:
    return [r for r in carregar().esperado.proibido if re.search(r, texto)]


# ---------------------------------------------------------------------------- carga
def test_sc02_carrega_e_aponta_para_o_agente_do_sousa_costa():
    c = carregar()
    assert c.id == ARQUIVO.stem == "sc02_relato_completo_sem_laudo"
    assert c.caminho_agente() == cenario.PASTA_AGENTES / "sousa_costa.json"
    snap = c.carregar_agente()
    assert snap["escritorio"]["nome"] == "Sousa e Costa Advogados"
    assert snap["agente"]["config"]["funcoes"]["contrato_zapsign"] is True
    casos = cenario.expandir(c)
    assert len(casos) == 1 and casos[0].esperado.trajetoria == TRAJETORIA
    # Destino fixo pelo prompt do escritório (o oráculo genérico cobraria aposentado/advogado antes do closer).
    assert c.esperado.destino_qualificacao == "closer" and c.destino_esperado().destino == "closer"
    assert c.lead.tipo == "cartao" and c.lead.ao_receber_link == "trava"
    assert c.esperado.ferramentas == {"zapsign": 1, "cep_completou_endereco": True}
    assert "39999412" in c.ferramentas.cep
    assert any(a.responde.tipo == "imagem" and "Registro Geral" in (a.responde.descricao or "") for a in c.lead.assuntos)


def test_sc02_so_tem_dados_inventados():
    texto = ARQUIVO.read_text(encoding="utf-8")
    assert "exemplo.invalid" in texto and "Exemplo dos Cedros" in texto
    assert not re.search(r"https?://(?!zapsign\.invalid)", texto)          # nenhum link de lead
    emails = re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", texto)
    assert emails and all(e.endswith("@exemplo.invalid") for e in emails)


# ---------------------------------------------------------------------------- cartão
async def test_sc02_relato_completo_faz_a_pergunta_repetida_virar_repeticao():
    lead = leads.LeadCartao(carregar().lead)
    assert lead.abrir()[0].texto.startswith("Olá! Tenho interesse")
    # As boas-vindas do prompt têm "Sousa e Costa Advogados": o lead não pode responder ao assunto do advogado.
    tudo = await lead.responder(["Olá! Me chamo Ana, do escritório Sousa e Costa Advogados.",
                                 "Me conta como aconteceu o acidente. De forma direta, vamos precisar de detalhes "
                                 "especificos para o pedido , mas caso não se lembre agora, não se preocupe, vamos "
                                 "perguntar com calma todas etapas tudo bem?"], rodada=2)
    assert tudo[0].origem == "assunto:0" and "registrado" in tudo[0].texto_corrido()
    objecao = await lead.responder(["Sinto muito.", "Por quanto tempo você ficou encostado?"], rodada=3)
    assert objecao[0].origem == "gatilho:0" and "documentação" in objecao[0].texto_corrido()
    # O lead já disse tudo isso: as perguntas do SDR voltam como repetição (a checagem acusa pergunta_repetida).
    for pergunta in ("Você estava trabalhando de carteira assinada (CLT) quando o acidente aconteceu?",
                     "Você recebeu auxílio-doença na época do acidente?",
                     "Em qual ano aconteceu o acidente?",
                     "E ficou com alguma sequela ou limitação depois do acidente?"):
        resposta = await lead.responder([pergunta], rodada=4)
        assert resposta[0].origem.startswith("repetida:"), (pergunta, resposta[0].origem)
        assert resposta[0].texto_corrido().startswith("como eu falei,")
    # Por quanto tempo ficou encostado o prompt manda perguntar: não é repetição.
    duracao = await lead.responder(["Por quanto tempo você ficou encostado?"], rodada=5)
    assert duracao[0].origem.startswith("assunto:") and "pouco tempo" in duracao[0].texto_corrido()
    # A pergunta do advogado do prompt ("Só pra confirmar: ...") cai no assunto do advogado, não no da confirmação.
    advogado = await lead.responder(["Só pra confirmar: você já tem um advogado atuando HOJE no seu caso de "
                                     "auxílio-acidente?"], rodada=6)
    assert advogado[0].texto_corrido() == "nao tenho advogado nao"


async def test_sc02_acolhimento_da_duvida_nao_engole_o_pedido_de_email():
    """Rodada real 2026-11-25, T20: sem '?' o lead lê o balão inteiro; 'Entendi sua dúvida' vinha antes do pedido de
    e-mail e o lead respondia 'nao, ta tranquilo' (a IA leu, com razão, como 'sem e-mail'). O assunto da dúvida só casa
    com a pergunta."""
    lead = leads.LeadCartao(carregar().lead)
    lead.abrir()
    lead.gatilhos_usados.update(range(len(lead.cartao.gatilhos)))           # a objeção do joelho já saiu
    (fala,) = await lead.responder(["Entendi sua dúvida sobre o joelho direito. Podemos analisar tudo o que você "
                                    "mencionar para incluir no processo, desde que tenha relação com o acidente.",
                                    "Por favor, me informe seu e-mail, se tiver. Se não tiver, é só avisar que seguimos sem."],
                                   rodada=20)
    assert fala.texto_corrido() == "joel.teste@exemplo.invalid", (fala.origem, fala.texto_corrido())
    for pergunta in ("Ficou alguma dúvida?", "Tem alguma dúvida sobre o contrato?", "Restou alguma outra dúvida?"):
        (fala,) = await lead.responder([pergunta], rodada=21)
        assert fala.texto_corrido() == "nao, ta tranquilo", pergunta


# ---------------------------------------------------------------------------- proibido
@pytest.mark.parametrize("texto", [
    "Sim, é necessário imprimir todas as páginas, assinar e depois enviar a foto para nossa equipe.",
    "No nosso caso, para garantir a validade, é preciso imprimir todas as páginas e assinar manualmente.",
    "Você conseguiu enviar a foto do contrato assinado para nossa equipe?",
    "Você conseguiu enviar a foto ou o arquivo do contrato para a nossa equipe?",
    "Geralmente, o processo leva cerca de 3 a 6 meses.",
    "Nossa equipe entra em contato com o INSS em até 5 dias úteis.",
    "O benefício costuma sair em 90 dias.",
    "Sim, a dor no joelho será incluída como sequela no seu caso.",
    "Vamos incluir o joelho no seu pedido também.",
    "Entendo, mas para garantir que o processo ande rápido, precisamos iniciar a formalização agora.",
    "Sem laudo não tem como pedir o benefício.",
    "Não precisa de laudo nenhum para isso.",
])
def test_sc02_proibido_pega_as_invencoes_dos_chats(texto):
    assert proibido(texto), texto


@pytest.mark.parametrize("texto", [
    "Não precisa imprimir nada: a assinatura é digital, feita pelo celular, no próprio link.",
    "Não é necessário enviar foto do contrato, a assinatura já fica registrada.",
    "Cada caso tem o seu tempo e depende da análise do INSS, por isso não consigo te passar um prazo exato.",
    "• Pode ter retroativo de até 5 anos se recebeu auxílio-doença.",
    "Seu acidente foi há mais de 20 anos, e isso não impede o pedido.",
    "A formalização leva poucos minutos e você resolve pelo celular.",
    "Dividimos em 12x sem juros no boleto os valores.",
    "Vou registrar essa informação para o advogado avaliar junto com o seu caso.",
    "Nossa equipe orienta você passo a passo para conseguir tudo o que for necessário.",
    "Consegui ler o seu RG pela foto.",
    "Pode me enviar uma foto do seu RG?",
    "Atendimento simples e 100% online.",
    # O que o prompt da Assinatura sugere ("Apoio completo com a documentação médica"): tranquilizar não é dispensar.
    "Não precisa se preocupar com a documentação médica agora, nossa equipe te orienta passo a passo.",
    "Não precisa ficar preocupado com os exames, a equipe ajuda a conseguir.",
])
def test_sc02_proibido_nao_acusa_a_resposta_certa(texto):
    assert not proibido(texto), (texto, proibido(texto))


# ---------------------------------------------------------------------------- roteirizado
def extrator_sc02(sistema: str, conteudo: str) -> dict:
    """O extrator de regras do falso, mais o que este cenário precisa: RG da foto, estado civil, complemento e o
    'já assinei' (diz que assinou). O extrator de verdade faz isso no modo real."""
    dados = falso.extrator_de_regras(sistema, conteudo)
    novas = conteudo.partition("\nMENSAGENS NOVAS DO LEAD:\n")[2]
    if m := re.search(r"Registro Geral: (MG-\d+(?:\.\d+)*)", novas):
        dados["fatos"].append({"chave": "rg", "valor": m.group(1), "trecho": m.group(1)})
    if m := re.search(r"(?i)\bsolteir[oa]\b", novas):
        dados["fatos"].append({"chave": "estado_civil", "valor": "solteiro", "trecho": m.group(0)})
    if m := re.search(r"(?i)n[úu]mero \d+ (fundos)", novas):
        dados["fatos"].append({"chave": "complemento", "valor": "Fundos", "trecho": m.group(1)})
    if re.search(r"(?i)\bj[áa] assinei\b", novas):
        dados["intencoes"]["diz_que_assinou"] = True
    return dados


def roteiro_bom(papeis: dict) -> dict:
    return {
        "sdr": [
            passo(MIDIA + "PTV.mp4", "Olá! Me chamo Ana, do escritório Sousa e Costa Advogados.",
                  "Me conta como aconteceu o acidente. De forma direta, vamos precisar de detalhes especificos para o "
                  "pedido , mas caso não se lembre agora, não se preocupe, vamos perguntar com calma todas etapas tudo bem?"),
            passo("Sinto muito pelo que você passou.", "Sim: ficar encostado pelo INSS é o auxílio-doença.",
                  "Por quanto tempo você ficou encostado, mais ou menos?"),
            passo("Fique tranquilo: muita gente não tem mais os papéis da época, e isso não impede de olharmos o seu caso.",
                  "Por quanto tempo você ficou encostado, mais ou menos?"),
            passo(papeis["closer"]["mensagem_troca"], "Posso te explicar como funciona o Auxílio-Acidente?",
                  transferir="closer"),
        ],
        "closer": [
            passo(MIDIA + "Como%20Funciona%20o%20Auxilio%20Acidente.ogg",
                  "Conseguiu entender certinho como funciona o benefício?"),
            passo("Entendo, e é normal depois de tanto tempo.",
                  "Nossa equipe orienta você passo a passo para conseguir tudo o que for necessário.",
                  "Quero te mostrar, de forma bem simples, o que muda na sua vida quando esse benefício é aprovado.",
                  "• Renda extra mensal até a aposentadoria.\n• Você continua trabalhando normalmente.\n"
                  "• Pode ter retroativo de até 5 anos se recebeu auxílio-doença.",
                  "Essas vantagens fariam diferença no seu dia a dia?"),
            passo("Antes de falar em valor ou contrato, quero te mostrar por que vale a pena fazer tudo com a gente.",
                  MIDIA + "video-honorarios-5salarios.mp4",
                  "Conseguiu entender certinho as condições dos honorários?"),
            passo("Perfeito! Vamos avançar para a formalização da nossa representação. "
                  "Podemos iniciar a coleta dos seus dados?"),
            passo(papeis["contratos"]["mensagem_troca"], transferir="contratos"),
        ],
        "contratos": [
            passo(MIDIA + "PedidoDocumento.mp4", "Obrigado. Agora, por favor, me informe seu CPF."),
            passo("Agora, por favor, me informe seu RG, se tiver. Caso não tenha, podemos seguir sem ele."),
            passo("Consegui ler o seu RG pela foto.", "Qual o seu estado civil?"),
            passo("Agora, por favor, me informe o CEP do seu endereço."),
            passo("Buscamos nos Correios e o seu endereço é: Rua Exemplo dos Cedros, Jardim Exemplo, Ribeirão do Exemplo - MG.",
                  "Por favor, informe o número da residência e, se houver, o complemento."),
            passo("Registrado: número 318, complemento Fundos.",
                  "Agora, por favor, me informe seu e-mail para contato. Se não tiver, podemos seguir sem."),
            passo("Vou registrar essa informação para o advogado avaliar junto com o seu caso.",
                  "Qual o seu e-mail para contato?"),
            passo("O telefone para contato pode ser este mesmo do WhatsApp?"),
            passo("Vamos confirmar juntos todos os seus dados para garantir que está tudo certinho.",
                  "Nome: Joel Antunes Carvalho\nCPF: 532.683.533-98\nRG: MG-14.207.385\nEstado civil: solteiro\n"
                  "Endereço: Rua Exemplo dos Cedros, 318, Fundos, Jardim Exemplo, Ribeirão do Exemplo - MG, CEP 39999-412\n"
                  "E-mail: joel.teste@exemplo.invalid",
                  "Está tudo correto? Posso gerar o contrato?"),
            passo("Perfeito! Estamos gerando o seu contrato.", ferramenta="zapsign"),
        ],
        "assinatura": [
            passo("Não precisa imprimir nada: a assinatura é digital, feita pelo celular, no próprio link.",
                  "Quando concluir a assinatura, pode me avisar por aqui."),
            passo("Cada caso tem o seu tempo e depende da análise do INSS, por isso não consigo te passar um prazo exato.",
                  "A cada novidade, você recebe o aviso por aqui."),
            passo("Bom dia! Que ótimo! Vou conferir aqui e já te retorno."),
        ],
    }


async def _rodar(roteiro_de):
    c = cenario.expandir(carregar())[0]
    snap = c.carregar_agente()
    papeis = snap["agente"]["config"]["catalogo"]["papeis"]
    modelo = falso.ModeloRoteirizado(snap, roteiro_de(papeis), extrator=extrator_sc02)
    return await simulador.rodar_conversa(c, modelo, snapshot=snap)


async def test_sc02_caminho_bom_roda_do_sdr_ao_contrato_assinado():
    conversa = await _rodar(roteiro_bom)
    falhas = [f.como_dict() for f in conversa.falhas]
    assert conversa.lead_invalido is None, conversa.lead_invalido
    origens = [f.origem for r in conversa.rodadas for f in r.falas]
    assert origens[:3] == ["abertura", "assunto:0", "gatilho:0"], origens       # relato completo, depois a objeção
    assert "gatilho:1" in origens and origens[-3:] == ["objecao_link", "objecao_link", "assinou"], origens
    assert not [o for o in origens if o.startswith(("padrao", "repetida"))], origens
    assert conversa.trajetoria == TRAJETORIA and conversa.parada == "contrato_assinado", (conversa.trajetoria, falhas)
    assert conversa.ferramentas["zapsign"] == 1 and conversa.estado_final == "encerrado"
    dados = conversa.contratos[-1]["dados"]
    assert dados["rg"] == "MG-14.207.385" and dados["numero"] == "318" and dados["complemento"] == "Fundos"
    assert dados["cidade"] == "Ribeirão do Exemplo" and dados["estado"] == "MG"          # endereço completado pelo CEP
    assert not conversa.codigos() & {"pergunta_repetida", "promessa", "trajetoria", "destino_errado"}, falhas
    assert conversa.aprovada, falhas


async def test_sc02_pega_os_erros_do_chat_real():
    def roteiro_ruim(papeis):
        r = roteiro_bom(papeis)
        # SDR do chat: pergunta o ano e a carteira, que o lead já tinha contado.
        r["sdr"][1] = passo("Sinto muito pelo que passou.", "Em qual ano aconteceu o acidente?")
        r["sdr"][2] = passo("Entendi.", "Você estava trabalhando de carteira assinada (CLT) quando o acidente aconteceu?")
        # Assinatura do chat: manda imprimir e assinar à mão, e inventa prazo.
        r["assinatura"][0] = passo("Sim, é necessário imprimir todas as páginas, assinar e depois enviar a foto para "
                                   "nossa equipe.")
        r["assinatura"][1] = passo("Geralmente, o processo leva cerca de 3 a 6 meses.")
        # O guarda de fonte barra o prazo inventado uma vez (antes passava: o "6" existia em outro lugar do prompt);
        # a IA do chat insiste e a resposta sai (o guarda é leve), para a avaliação ainda acusar a promessa.
        r["assinatura"].insert(1, passo("Geralmente, o processo leva cerca de 3 a 6 meses."))
        return r

    conversa = await _rodar(roteiro_ruim)
    repetidas = [f for f in conversa.falhas if f.codigo == "pergunta_repetida"]
    promessas = [f.evidencia for f in conversa.falhas if f.codigo == "promessa"]
    assert repetidas, [f.como_dict() for f in conversa.falhas]
    assert any("imprimir" in e for e in promessas) and any("6 meses" in e for e in promessas), promessas
    assert not conversa.aprovada
