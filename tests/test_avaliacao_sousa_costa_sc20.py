"""Cenário sc20 do Sousa e Costa (avaliacao/cenarios_sousa_costa/sc20_cpf_pontuacao_torta.json), de graça.

O lead manda o CPF com ponto no lugar do hífen ('386.417.259.46'). É a regressão do laço de CPF da rodada real de
2026-11-25: no sc10 o cartão mandava o CPF assim sem a descrição prever, a IA pediu o CPF 'correto' em laço e a regra do
e-mail, que o sc10 testa, nem foi exercida. O sc10 passou a mandar o CPF limpo e a variação ficou aqui. Aqui só se prova
que o cenário carrega, que os dados são inventados, que o 'proibido' pega o 'CPF incorreto/verifique e reenvie' e que,
com o modelo roteirizado, aceitar o CPF passa e pedir de novo reprova. A qualidade do prompt é o modo real (pago).
"""

import re

import pytest

from app.avaliacao import cenario, falso, leads, simulador
from app.avaliacao.falso import passo
from app.contrato import dados as cdados
from tests.test_avaliacao_sousa_costa_sc10_19 import ROTEIROS, _extrator

PASTA = cenario.PASTA / "cenarios_sousa_costa"
ARQUIVO = PASTA / "sc20_cpf_pontuacao_torta.json"
CPF = "386.417.259-46"
CPF_TORTO = "386.417.259.46"


def caso():
    return cenario.expandir(cenario.carregar(ARQUIVO))[0]


def test_sc20_carrega_com_o_gabarito_do_prompt():
    c = caso()
    assert c.id == ARQUIVO.stem and c.agente == "avaliacao/agentes/sousa_costa.json" and c.lead.tipo == "cartao"
    assert c.carregar_agente()["escritorio"]["nome"] == "Sousa e Costa Advogados"
    assert "prompt" in c.descricao.lower() and "ponto no lugar do hífen" in c.descricao.lower()
    assert c.destino_esperado().destino == "closer"                   # oráculo: CLT na data
    assert c.esperado.trajetoria == ["sdr", "closer", "contratos", "assinatura", "contrato_assinado"]
    assert c.esperado.fatos["cpf"] == CPF and "cpf" in c.esperado.contrato.campos
    assert c.esperado.ferramentas == {"zapsign": 1, "cep_completou_endereco": True}
    assert [x.id for x in cenario.casos(["sc20"], pasta=PASTA)] == [c.id]


def test_sc20_dados_inventados_e_so_o_cpf_torto():
    c = caso()
    v = c.lead.verdade
    assert cdados.cpf_valido(v["cpf"]) and v["cpf"] == CPF and v["cpf_como_digita"] == CPF_TORTO
    assert re.sub(r"\D", "", CPF_TORTO) == re.sub(r"\D", "", CPF)       # mesmos dígitos: só a pontuação muda
    assert v["email"].endswith("@exemplo.invalid") and re.fullmatch(r"55319900001[0-9]{2}", c.lead.telefone)
    outros = [cenario.carregar(p) for p in sorted(PASTA.glob("sc*.json")) if p != ARQUIVO]
    assert c.lead.telefone not in {o.lead.telefone for o in outros}
    assert v["cpf"] not in {o.lead.verdade.get("cpf") for o in outros}
    for endereco in c.ferramentas.cep.values():
        assert "Exemplo" in endereco["logradouro"] and "Exemplo" in endereco["cidade"]
    cpf = next(a for a in c.lead.assuntos if "cpf" in a.fatos).responde.texto_corrido()
    assert cpf == CPF_TORTO


@pytest.mark.parametrize("texto", [
    "O CPF informado está incorreto, pois não passou na validação dos dígitos. Por favor, me envie o CPF correto.",
    "Por favor, verifique e me envie novamente o CPF completo e correto, com os números e dígitos verificadores.",
    "Seu CPF parece inválido.",
])
def test_sc20_proibido_pega_o_cpf_pedido_de_novo(texto):
    assert any(re.search(r, texto) for r in caso().esperado.proibido), texto


@pytest.mark.parametrize("texto", [
    "Agora me informe o seu CPF, por favor.",
    "Recebi o seu CPF: 386.417.259-46.",
    "Nome: Gilmar Teixeira Prado\nCPF: 386.417.259-46\nEstá tudo correto? Posso gerar o contrato?",
])
def test_sc20_proibido_deixa_passar_o_certo(texto):
    assert not any(re.search(r, texto) for r in caso().esperado.proibido), texto


async def test_sc20_cartao_responde_o_cpf_torto_e_o_pedido_de_novo_e_repeticao():
    lead = leads.LeadCartao(caso().lead)
    lead.abrir()
    (fala,) = await lead.responder(["Agora me informe o seu CPF, por favor."], rodada=12)
    assert fala.texto_corrido() == CPF_TORTO
    (fala,) = await lead.responder(["Por favor, verifique e me envie novamente o CPF completo e correto, com os números "
                                    "e dígitos verificadores."], rodada=13)
    assert fala.origem.startswith("repetida:") and CPF_TORTO in fala.texto_corrido()


def _roteiro(contratos_do_meio):
    """O roteiro do sc10 (o mesmo fluxo do prompt), com o e-mail informado e a confirmação com o CPF normalizado."""
    r = {papel: list(passos) for papel, passos in ROTEIROS["sc10_contrato_sem_email"].items()}
    r["contratos"] = [
        passo(falso_midia("PedidoDocumento.mp4"), "Agora me informe o seu CPF, por favor."),
        *contratos_do_meio,
        passo("Você tem RG? Se não tiver, seguimos sem."),
        passo("Sem problema, seguimos sem.", "Qual o seu estado civil?"),
        passo("Qual o seu CEP?"),
        passo("Buscamos nos Correios e o seu endereço é: Rua Exemplo dos Ipês, Jardim Exemplo, Serra Azul do Exemplo/MG.",
              "Qual o número da casa?"),
        passo("Tem complemento? Se não tiver, é só me dizer."),
        passo("Qual o seu e-mail? Se não tiver, seguimos sem."),
        passo("Qual o seu telefone para contato?"),
        passo("Vamos confirmar juntos todos os seus dados.", f"Nome: Gilmar Teixeira Prado\nCPF: {CPF}\n"
              "E-mail: gilmar.teste@exemplo.invalid", "Está tudo correto? Posso gerar o contrato?"),
        passo("Perfeito! Estamos gerando o seu contrato.", ferramenta="zapsign"),
    ]
    return r


def falso_midia(nome):
    return "https://mqkgzkzlysvwjjuwvxul.supabase.co/storage/v1/object/public/midia/" + nome


async def _rodar(roteiro):
    c = caso()
    snap = c.carregar_agente()
    modelo = falso.ModeloRoteirizado(snap, roteiro, extrator=_extrator)
    return await simulador.rodar_conversa(c, modelo, snapshot=snap)


async def test_sc20_aceitar_o_cpf_torto_passa_e_o_contrato_sai_com_o_hifen():
    conversa = await _rodar(_roteiro([]))
    falhas = [f.como_dict() for f in conversa.falhas]
    assert conversa.lead_invalido is None, conversa.lead_invalido
    assert conversa.trajetoria == caso().esperado.trajetoria, (conversa.trajetoria, conversa.parada, falhas)
    assert conversa.aprovada, falhas
    assert conversa.ferramentas["zapsign"] == 1 and len(conversa.contratos) == 1
    assert conversa.contratos[0]["dados"]["cpf"] == CPF


async def test_sc20_pedir_o_cpf_de_novo_reprova_se_chegar_ao_lead():
    errado = passo("O CPF informado está incorreto, pois não passou na validação dos dígitos.",
                   "Por favor, verifique e me envie novamente o CPF completo e correto.")
    conversa = await _rodar(_roteiro([errado]))
    chegou = any("incorreto" in t for r in conversa.rodadas for t in r.enviadas)
    if not chegou:
        # O motor pode barrar a mensagem antes do envio (trava do turno): aí o lead nunca a vê.
        assert "refeito_pela_trava" in conversa.codigos(), [f.como_dict() for f in conversa.falhas]
        return
    assert {"promessa", "pergunta_repetida"} & conversa.codigos(), [f.como_dict() for f in conversa.falhas]
    assert not conversa.aprovada
