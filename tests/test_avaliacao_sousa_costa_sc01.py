"""Cenário sc01 do Sousa e Costa (avaliacao/cenarios_sousa_costa/sc01_audio_codigo_nao_chegou.json).

Inspirado no CHAT 1 do escritório, com fatos, falas e dados 100% inventados (só o jeito do lead foi aproveitado): lead de anúncio que fala por áudio, ano vago, CLT, dados em
formatos estranhos e "o código não chegou" na assinatura. Aqui só se prova, de graça, que o cenário carrega, que o
gabarito segue o prompt do escritório (oráculo genérico desligado) e que o cartão do lead cobre a conversa do fluxo do
Sousa e Costa até a pausa por dificuldade na assinatura (modelo roteirizado). A qualidade do prompt é o modo real.
"""

import json
import re

from app.avaliacao import cenario, falso, simulador
from app.avaliacao.falso import passo
from app.contrato import dados as cdados

PASTA = cenario.PASTA / "cenarios_sousa_costa"
ARQUIVO = PASTA / "sc01_audio_codigo_nao_chegou.json"
MIDIA = "https://mqkgzkzlysvwjjuwvxul.supabase.co/storage/v1/object/public/midia/"


def caso():
    return cenario.expandir(cenario.carregar(ARQUIVO))[0]


def test_sc01_carrega_com_o_gabarito_do_prompt_do_escritorio():
    cen = cenario.carregar(ARQUIVO)
    assert cen.id == "sc01_audio_codigo_nao_chegou" and cen.agente == "avaliacao/agentes/sousa_costa.json"
    assert [c.id for c in cenario.casos(["sc01"], pasta=PASTA)] == [cen.id]
    snap = cen.carregar_agente()
    assert snap["escritorio"]["nome"] == "Sousa e Costa Advogados" and snap["agente"]["nome"] == "Ana"
    # Oráculo genérico desligado: destino fixo, sem fatos decisivos das Regras() (aposentado/advogado não são perguntados
    # pelo SDR do escritório).
    assert cen.esperado.destino_qualificacao == "closer"
    destino = cen.destino_esperado()
    assert destino.destino == "closer" and not destino.passa_periodo
    assert cen.esperado.trajetoria == ["sdr", "closer", "contratos", "assinatura"]
    assert cen.esperado.estado_final == "pausado" and cen.esperado.ferramentas == {"zapsign": 1, "cep_completou_endereco": True}
    assert cen.lead.tipo == "cartao" and cen.lead.ao_receber_link == "trava" and not cen.ferramentas.zapsign.assina
    assert any(a.aceite for a in cen.lead.assuntos)


def test_sc01_dados_sao_sinteticos_e_o_cep_resolve():
    cen = cenario.carregar(ARQUIVO)
    v = cen.lead.verdade
    assert cdados.cpf_valido(v["cpf"]) and re.fullmatch(r"\d{3}\.\d{3}\.\d{3}\.\d{2}", v["cpf"])   # ponto no lugar do hífen
    assert v["email"].endswith("@exemplo.invalid")
    assert re.fullmatch(r"\d{8}", v["cep"]) and v["cep"] in cen.ferramentas.cep                       # CEP sem hífen
    assert cen.ferramentas.cep[v["cep"]]["logradouro"].startswith("Rua Exemplo")
    falas = " ".join(a.responde.texto_corrido() for a in cen.lead.assuntos)
    for formato in ("uniao istavel", "06", "Casa", v["rg"], v["cpf"]):
        assert formato in falas
    assert any(a.responde.tipo == "audio" for a in cen.lead.assuntos)


def test_sc01_proibido_pega_as_invencoes_dos_chats_e_deixa_passar_o_certo():
    proibido = caso().esperado.proibido

    def barra(texto):
        return any(re.search(r, texto) for r in proibido)

    for errado in ("Sim, é preciso imprimir todas as páginas e assinar.",
                   "Para valer, você precisa assinar à mão cada folha.",
                   "Você conseguiu mandar a foto do contrato assinado para a equipe?",
                   "Normalmente o processo leva de 3 a 6 meses.",
                   "A equipe fala com o INSS em até 5 dias úteis.",
                   "Esse problema no ombro vai ser incluído como sequela no seu caso.",
                   "Entendo, mas precisamos fazer isso agora para o processo andar.",
                   "O código vem por e-mail, mas vou ver para te ajudar a receber pelo WhatsApp também.",
                   "Vou gerar um novo contrato para você."):
        assert barra(errado), errado
    for certo in ("Perfeito! Estamos gerando o seu contrato.\n\nEm alguns segundos você vai receber o link para assinatura!",
                  "Não precisa imprimir nada: a assinatura é digital, pelo link.",
                  "Entendi! Vou pedir para a nossa equipe te dar suporte na assinatura agora mesmo, tudo bem?",
                  "O código de assinatura chega por e-mail. Pode olhar a caixa de spam?",
                  "• Pode ter retroativo de até 5 anos se recebeu auxílio-doença.",
                  "Atendimento simples e 100% online.",
                  "Não consigo mandar o código pelo WhatsApp, mas a equipe vai te ajudar.",
                  # Negação com "sem"/"nada" na mesma frase e número sem contexto de prazo (achados do fechamento).
                  "A assinatura é digital, sem imprimir nada.",
                  "Nada de assinar à mão: é tudo pelo link.",
                  "Você ficou uns 2 meses afastado?"):
        assert not barra(certo), certo


def _extrator(sistema, conteudo):
    """O extrator de regras do roteirizado mais o que este lead manda fora do padrão (o extrator de verdade tem de pegar):
    CPF com ponto no lugar do hífen, RG, estado civil, número e complemento soltos, e o sinal de dificuldade na
    assinatura quando o código não chega."""
    dados = falso.extrator_de_regras(sistema, conteudo)
    texto, ultima = falso._secoes(conteudo)
    fatos = dados["fatos"]

    def fato(chave, valor):
        fatos.append({"chave": chave, "valor": valor, "trecho": texto})

    pergunta = ultima.strip().splitlines()[-1] if ultima.strip() else ""     # o último balão da IA
    if re.search(r"(?i)informe seu cpf", pergunta) and re.fullmatch(r"[\d. -]{11,14}", texto):
        fato("cpf", re.sub(r"\D", "", texto))
    elif re.search(r"(?i)informe seu rg", pergunta):
        fato("rg", texto)
    elif re.search(r"(?i)estado civil\?", pergunta):
        fato("estado_civil", "união estável")
    elif re.search(r"(?i)n[úu]mero da sua resid", pergunta):
        fato("numero_casa", texto)
    elif re.search(r"(?i)tem complemento", pergunta):
        fato("complemento", texto)
    if re.search(r"(?i)c[óo]digo[^.?!]{0,40}n[ãa]o veio", texto):
        dados["sinais"] = ["dificuldade_assinatura"]
    return dados


def roteiro_sc01(caso_):
    papeis = caso_.carregar_agente()["agente"]["config"]["catalogo"]["papeis"]
    return {
        "sdr": [
            passo(MIDIA + "PTV.mp4", "Olá! Me chamo Ana, do escritório Sousa e Costa Advogados.",
                  "Me conta como aconteceu o acidente. Caso não se lembre de tudo agora, vamos com calma, tudo bem?"),
            passo("Sinto muito pelo seu acidente.", "Em qual ano isso aconteceu?"),
            passo("Tudo bem, não precisa ser exato.", "Você recebeu auxílio-doença na época do acidente?"),
            passo("Você estava trabalhando de carteira assinada (CLT) quando o acidente aconteceu?"),
            passo(papeis["closer"]["mensagem_troca"], "Posso te explicar como funciona o Auxílio-Acidente?",
                  transferir="closer"),
        ],
        "closer": [
            passo(MIDIA + "Como%20Funciona%20o%20Auxilio%20Acidente.ogg",
                  "Conseguiu entender certinho como funciona o benefício?"),
            passo("Quero te mostrar, de forma bem simples, o que muda na sua vida quando esse benefício é aprovado.",
                  "• Renda extra mensal até a aposentadoria.\n• Você continua trabalhando normalmente.",
                  "Essas vantagens fariam diferença no seu dia a dia?"),
            passo("Antes de falar em valor ou contrato, quero te mostrar por que vale a pena fazer tudo com a gente.",
                  # O tópico fixo do prompt: "100% online" não é honorário (checagens.valores_de_honorario).
                  "• Atendimento simples e 100% online.\n• Você só paga se o benefício for aprovado."),
            passo("Vamos falar sobre os honorários?"),
            passo(MIDIA + "video-honorarios-5salarios.mp4", "Conseguiu entender certinho as condições dos honorários?"),
            passo("Perfeito! Vamos avançar para a formalização da nossa representação. Podemos iniciar a coleta dos seus dados?"),
            passo(papeis["contratos"]["mensagem_troca"], transferir="contratos"),
        ],
        "contratos": [
            passo(MIDIA + "PedidoDocumento.mp4", "Por favor, informe seu CPF. Pode enviar com ou sem pontuação."),
            passo("Agora, por favor, me informe seu RG, se tiver. Caso não tenha, podemos seguir sem ele."),
            passo("Qual seu estado civil?"),
            passo("Agora, por favor, me informe o CEP do seu endereço."),
            passo("Buscamos nos Correios e o seu endereço é: Rua Exemplo dos Coqueiros, Jardim Exemplo, Vila Serena do Sul - BA.",
                  "Qual o número da sua residência?"),
            passo("Tem complemento no seu endereço?"),
            passo("Agora, por favor, me informe seu e-mail para contato. Se não tiver, podemos seguir sem."),
            passo("Vamos confirmar juntos todos os seus dados para garantir que está tudo certinho, tudo bem?"),
            passo("Nome: Valdir Santana Rocha\nCPF: 057.830.862-23\nRG: 27.519.044-81\nEstado civil: união estável\n"
                  "Endereço: Rua Exemplo dos Coqueiros, 06, Casa, Jardim Exemplo, Vila Serena do Sul - BA\n"
                  "CEP: 44999-210\nE-mail: valdir.rocha.teste@exemplo.invalid",
                  "Está tudo correto? Posso gerar o contrato?"),
            # A mensagem obrigatória do prompt passa na trava: "receber o link" é aviso de envio, não promessa.
            passo("Perfeito! Estamos gerando o seu contrato.", "Em alguns segundos você vai receber o link para assinatura!",
                  ferramenta="zapsign"),
        ],
        "assinatura": [passo("Entendi! Vou pedir para a nossa equipe te ajudar com o código agora mesmo, tudo bem?")],
    }


async def test_sc01_roda_no_roteirizado_ate_a_pausa_por_dificuldade_na_assinatura():
    c = caso()
    snap = c.carregar_agente()
    modelo = falso.ModeloRoteirizado(snap, roteiro_sc01(c), extrator=_extrator)
    conversa = await simulador.rodar_conversa(c, modelo, snapshot=snap)
    falhas = [f.como_dict() for f in conversa.falhas]
    assert not conversa.lead_invalido, conversa.lead_invalido
    origens = [f.origem for r in conversa.rodadas for f in r.falas]
    assert "padrao" not in origens, origens                     # o cartão cobre cada pergunta do fluxo do escritório
    assert conversa.trajetoria == ["sdr", "closer", "contratos", "assinatura"], (conversa.trajetoria, falhas)
    assert conversa.parada == "lead_pausado" and conversa.estado_final == "pausado", conversa.parada
    assert conversa.ferramentas["zapsign"] == 1
    assert conversa.aprovada, falhas
    codigos = conversa.codigos()
    # Leva 1 (B4): o prompt do escritório não pergunta aposentadoria (nem o aceite do jeito que o portão reconhece);
    # a única correção aceita é a do portão de fatos, que manda perguntar o que falta antes de passar o lead.
    refeitos = [f for f in conversa.falhas if f.codigo == "refeito_pela_trava"]
    assert all("Ainda falta perguntar antes de passar" in f.evidencia for f in refeitos), falhas
    assert "honorario_divergente" not in codigos, falhas
    dados = conversa.contratos[-1]["dados"]
    assert dados["cpf"] == "057.830.862-23" and dados["cep"] == "44999-210" and dados["numero"] == "06"
    assert dados["cidade"] == "Vila Serena do Sul" and dados["estado"] == "BA"
    assert "objecao_link" in origens                            # o "código não chegou" foi dito depois do link
    assert json.dumps(conversa.fatos_finais, ensure_ascii=False)
