"""Revisão das correções do motor (rodada 2): regressões dos achados confirmados na revisão.

Tudo genérico, multi-escritório (nada de um escritório só):
- cpf_ja_conferido: CPF com pontos citado na resposta, CPF do(a) menor como próximo dado, verbo de pedido sem o CPF como
  objeto (resumo, próximo campo, particípios), erro negado ou assumido pela IA;
- trava dura que só aparece na 2ª tentativa não pausa (a IA não recebeu a CORRIJA dela);
- resposta_repetida: saudação / "não entendi" repetidos, fecho sem pedido, dado repetido em outro formato;
- "você vai receber o contato/ligação/retorno" não é promessa;
- endereço do escritório (base de conhecimento) não é endereço inventado;
- CEP sem rótulo: não pega RG / data de nascimento; troca o CEP antigo; CEP trocado refaz a busca; o mesmo CEP não é
  buscado a cada turno.
"""

import pytest

from app.cerebro import catalogo, travas, turno
from app.contrato import dados as cdados
from app.modelo import ModeloFalso
from tests.test_motor_correcoes_rodada2 import CPF_DO_CASO, conteudos, entrada, extrai, produto, resposta


@pytest.fixture(autouse=True)
def _pausa_por_repeticao_ligada(monkeypatch):
    """Estes testes medem o mecanismo de pausa das travas de repetição; em produção ele vem desligado
    (turno.PAUSAR_EM_REPETICAO = False, ver test_travas_de_repeticao_nao_pausam_por_padrao)."""
    monkeypatch.setattr(turno, "PAUSAR_EM_REPETICAO", True)

CPF = "529.982.247-25"                  # válido


def _codigos(saida):
    return [[r["codigo"] for r in tentativa] for tentativa in saida.reprovacoes]


def _guarda(texto, fatos, novas):
    return turno._cpf_valido_pedido_de_novo(entrada(novas, etapa="contratos"), fatos, [texto])


# ---------------------------------------------------------------------------- [0] [2] [7] [8] [13] [14] [19]
@pytest.mark.parametrize("texto", [
    "Só confirmando: o seu CPF é 529.982.247-25, certo?",
    "Confirme se o seu CPF é 529.982.247-25.",
    "Você informou o CPF 529.982.247-25. Agora me passe o seu CEP.",
    "O CPF que você enviou (529.982.247-25) está certo. Qual o seu CEP?",
    "Confirme seus dados: Nome: Ana Souza; CPF: 529.982.247-25. Está tudo certo?",
    "Vou passar seus dados: CPF 529.982.247-25. Pode confirmar?",
    "Prontinho, atualizei!\nNome: Ana Souza\nCPF: 529.982.247-25\nPode confirmar se o nome e o CPF agora estão corretos?",
    "Perfeito, CPF anotado, agora me passe o número do seu RG.",
    "Obrigada, CPF recebido, agora me passe o seu RG.",
    "Perfeito, anotei o CPF e agora preciso do seu RG.",
    "Perfeito, o CPF informado foi registrado. Qual é o seu RG?",
    "Obrigada, o CPF que você enviou está anotado. Qual é o seu RG?",
    "Perfeito, CPF confirmado! Agora me informe o seu RG.",
    "Pode ficar tranquila, o seu CPF está certinho, não tem nenhum erro.",
    "Desculpe, anotei o CPF errado no resumo; o correto é 529.982.247-25.",
])
async def test_resposta_que_cita_ou_acusa_o_cpf_nao_e_barrada(texto):
    modelo = ModeloFalso({"extrator": extrai([("cpf", CPF, CPF)]), "etapa": resposta(texto)})
    saida = await turno.processar(modelo, entrada([CPF], etapa="contratos"))
    assert saida.reprovacoes == [[]] and saida.estado_lead is None, texto
    assert len(modelo.pedidos) == 2 and saida.mensagens, texto


async def test_cpf_com_pontos_citado_nas_duas_tentativas_nao_pausa():
    confirma = resposta("Confirme se o seu CPF é 057.830.862-23.")
    modelo = ModeloFalso({"extrator": extrai([("cpf", CPF_DO_CASO, CPF_DO_CASO)]), "etapa": [confirma, dict(confirma)]})
    saida = await turno.processar(modelo, entrada([CPF_DO_CASO], etapa="contratos"))
    assert saida.reprovacoes == [[]] and saida.estado_lead is None


@pytest.mark.parametrize("texto", [
    "O CPF informado está incorreto, pois não passou na validação dos dígitos. Por favor, me envie o CPF correto.",
    "Me envie o seu CPF de novo, por favor.",
    "Pode me enviar o seu CPF novamente?",
    "Qual é o seu CPF?",
    "Preciso do seu CPF.",
    "Pode digitar o CPF de novo?",
    "O CPF 529.982.247-25 está incorreto.",
    "Desculpe, mas o CPF está incorreto.",
    "Não está correto, tem um erro no CPF.",
])
def test_pedir_de_novo_ou_dizer_que_o_cpf_valido_esta_errado_continua_barrado(texto):
    guarda = _guarda(texto, {"cpf": CPF}, [CPF])
    assert guarda and guarda.codigo == "cpf_ja_conferido" and guarda.dura, texto
    assert CPF in guarda.orientacao


def test_frase_sem_o_cpf_pedido_nao_conta_mesmo_sem_ponto_entre_as_frases():
    # O ponto entre dígitos não corta a frase, mas o ponto antes de espaço continua cortando.
    assert turno._FIM_DE_FRASE.split("CPF 057.830.862.23. Me envie o RG") == ["CPF 057.830.862.23", " Me envie o RG"]
    assert _guarda("CPF 057.830.862.23. Me envie o RG", {"cpf": "057.830.862-23"}, [CPF_DO_CASO]) is None


# ---------------------------------------------------------------------------- [1] [9] [18] o CPF do(a) menor
@pytest.mark.parametrize("texto", [
    "Obrigada! Agora me envie o CPF da criança, por favor.",
    "Qual o CPF do seu filho?",
    "Agora me passe o CPF do menor.",
    "Perfeito, e agora preciso do CPF do(a) menor.",
    "Obrigada! Agora me envie o CPF do Pedro, por favor.",
    "Recebi o seu CPF, agora me envie o CPF dele.",
])
def test_pedir_o_cpf_do_menor_depois_do_cpf_do_titular_nao_e_barrado(texto):
    assert _guarda(texto, {"cpf": CPF}, [f"{CPF}, o nome dele é Pedro Souza"]) is None, texto


@pytest.mark.parametrize("texto", [
    "Anotado! Agora me informe o CPF do responsável.",
    "Anotado! Agora me envie o seu CPF, de quem vai assinar.",
    "Recebi o CPF do seu filho, agora me envie o seu CPF.",
])
def test_pedir_o_cpf_do_titular_depois_do_cpf_do_menor_nao_e_barrado(texto):
    assert _guarda(texto, {"cpf_menor": CPF}, [f"o cpf do meu filho é {CPF}"]) is None, texto


def test_pedir_de_novo_o_mesmo_cpf_continua_barrado_para_cada_titular():
    menor = _guarda("Me envie o CPF da criança de novo.", {"cpf_menor": CPF}, [CPF])
    assert menor and menor.codigo == "cpf_ja_conferido" and CPF in menor.orientacao
    titular = _guarda("Me envie o seu CPF de novo.", {"cpf": CPF, "cpf_menor": CPF_DO_CASO}, [CPF])
    assert titular and titular.codigo == "cpf_ja_conferido" and CPF in titular.orientacao
    errado = _guarda("O CPF da criança está incorreto.", {"cpf": CPF, "cpf_menor": CPF_DO_CASO}, ["ok"])
    assert errado and "057.830.862-23" in errado.orientacao


async def test_pedir_o_cpf_da_crianca_de_ponta_a_ponta_nao_pausa():
    pede = resposta("Obrigada! Agora me envie o CPF da criança, por favor.")
    modelo = ModeloFalso({"extrator": extrai([("cpf", CPF_DO_CASO, CPF_DO_CASO)]), "etapa": [pede, dict(pede)]})
    saida = await turno.processar(modelo, entrada([CPF_DO_CASO], etapa="contratos"))
    assert len(conteudos(modelo)) == 1 and saida.estado_lead is None
    assert saida.mensagens[0]["texto"].startswith("Obrigada! Agora me envie o CPF da criança")


# ---------------------------------------------------------------------------- [3] trava dura só na 2ª tentativa
async def test_dura_so_na_segunda_tentativa_fica_com_a_primeira_e_nao_pausa():
    primeira = resposta("Buscamos nos Correios e o seu endereço é: Rua Santa Luzia, Bairro Centro, São João do Paraíso, MG.")
    segunda = resposta("O último grupo do CPF deve ter dois dígitos. Pode me enviar o CPF correto?")
    modelo = ModeloFalso({"extrator": extrai(), "etapa": [primeira, segunda]})
    saida = await turno.processar(modelo, entrada([f"como eu falei, {CPF_DO_CASO}"], etapa="contratos",
                                                  fatos={"cpf": "057.830.862-23", "cep": "39999-412"}))
    assert _codigos(saida) == [["endereco_sem_fonte"], ["cpf_ja_conferido"]]
    assert saida.estado_lead is None and saida.motivo_estado is None
    assert saida.mensagens[0]["texto"].startswith("Buscamos nos Correios")
    assert any(e["tipo"] == "trava_endereco_sem_fonte" for e in saida.eventos)
    assert not any(e["tipo"] == "pedido_repetido" for e in saida.eventos)


# ---------------------------------------------------------------------------- [4] [15] [22] anti-laço
async def test_bom_dia_de_novo_com_a_pergunta_pendente_retomada_nao_e_laco():
    pergunta = "Bom dia! Você trabalhava de carteira assinada na época do acidente?"
    historico = [{"autor": "lead", "texto": "Bom dia"},
                 {"autor": "você", "texto": "Bom dia! Sou a Júlia. Me conta como foi o seu acidente?"},
                 {"autor": "lead", "texto": "Caí de moto indo pro trabalho"},
                 {"autor": "você", "texto": pergunta}]
    modelo = ModeloFalso({"extrator": extrai(), "etapa": [resposta(pergunta), resposta(pergunta)]})
    saida = await turno.processar(modelo, entrada(["Bom dia"], historico=historico))
    assert len(conteudos(modelo)) == 1 and saida.estado_lead is None and saida.reprovacoes == [[]]


async def test_nao_entendi_de_novo_com_a_mesma_explicacao_nao_e_laco():
    explica = "O auxílio-acidente é uma indenização paga pelo INSS a quem ficou com sequela. Você ficou com alguma sequela?"
    historico = [{"autor": "você", "texto": explica}, {"autor": "lead", "texto": "Não entendi"},
                 {"autor": "você", "texto": explica}]
    modelo = ModeloFalso({"extrator": extrai(), "etapa": [resposta(explica), resposta(explica)]})
    saida = await turno.processar(modelo, entrada(["Não entendi"], historico=historico))
    assert len(conteudos(modelo)) == 1 and saida.estado_lead is None


async def test_fecho_do_desqualificado_repetido_nao_pausa():
    fecho = "Entendo, mas pelo que você contou o seu caso não se enquadra nos critérios. Obrigada pelo contato."
    historico = [{"autor": "lead", "texto": "mas eu tenho direito sim"}, {"autor": "você", "texto": fecho}]
    modelo = ModeloFalso({"extrator": extrai(), "etapa": [resposta(fecho), resposta(fecho)]})
    saida = await turno.processar(modelo, entrada(["mas eu tenho direito sim"], etapa="desqualificado", historico=historico))
    assert saida.estado_lead is None and saida.mensagens[0]["texto"].startswith("Entendo")


async def test_cortesia_repetida_na_assinatura_nao_pausa():
    cortesia = "Por nada! Qualquer dúvida sobre a assinatura, é só me chamar por aqui."
    historico = [{"autor": "lead", "texto": "obrigado"}, {"autor": "você", "texto": cortesia}]
    modelo = ModeloFalso({"extrator": extrai(), "etapa": [resposta(cortesia), resposta(cortesia)]})
    saida = await turno.processar(modelo, entrada(["obrigado"], etapa="assinatura", historico=historico))
    assert saida.estado_lead is None and len(conteudos(modelo)) == 1


async def test_dado_repetido_em_outro_formato_nao_desliga_o_anti_laco():
    pede = "Para continuar, me informe o seu telefone com DDD, por favor."
    historico = [{"autor": "lead", "texto": "31999991234"}, {"autor": "você", "texto": pede}]
    modelo = ModeloFalso({"extrator": extrai([("telefone_contrato", "(31) 99999-1234", "(31) 99999-1234")]),
                          "etapa": [resposta(pede), resposta(pede)]})
    saida = await turno.processar(modelo, entrada(["já te mandei, (31) 99999-1234"], etapa="contratos",
                                                  fatos={"telefone_contrato": "31999991234"}, historico=historico))
    assert "Sua resposta repete a sua última mensagem" in conteudos(modelo)[1]
    assert (saida.estado_lead, saida.motivo_estado) == ("pausado", "pedido_repetido")


def test_mesmo_valor_compara_digitos_e_caixa():
    assert turno._mesmo_valor("telefone_contrato", "(31) 99999-1234", "31999991234")
    assert turno._mesmo_valor("email", "Ana@Exemplo.com", "ana@exemplo.com")
    assert not turno._mesmo_valor("telefone_contrato", "(31) 99999-0000", "31999991234")
    assert not turno._mesmo_valor("email", "ana@exemplo.com", None)


# ---------------------------------------------------------------------------- [5] "você vai receber" + entrega
@pytest.mark.parametrize("frase", [
    "Você vai receber o contato da nossa equipe ainda hoje.",
    "Você vai receber uma ligação da advogada para tirar suas dúvidas.",
    "Você vai receber o retorno da equipe em breve.",
    "Você vai receber o atendimento da especialista.",
    "Você vai receber uma visita.",
])
def test_voce_vai_receber_contato_da_equipe_nao_e_promessa(frase):
    assert travas.trecho_de_promessa(frase) is None, frase


@pytest.mark.parametrize("frase", ["Você vai receber o benefício.", "Você vai receber uma resposta positiva do INSS."])
def test_voce_vai_receber_resultado_segue_barrado(frase):
    assert travas.trecho_de_promessa(frase) == "voce vai receber", frase


# ---------------------------------------------------------------------------- [6] [16] [23] endereço do escritório
def test_endereco_das_fontes_do_motor_nao_e_inventado():
    texto = ["Nosso escritório fica na Rua Sete de Setembro, 100, Centro."]
    assert catalogo.endereco_sem_fonte(texto, {}, ["onde fica?"]) == "Rua Sete de Setembro"
    assert catalogo.endereco_sem_fonte(texto, {}, ["onde fica?"], ["Rua Sete de Setembro, 100, Centro"]) is None
    # Fonte que não cita a rua (só palavras soltas dela) não libera a rua inventada.
    assert catalogo.endereco_sem_fonte(["Seu endereço é Rua Santa Luzia, 10."], {}, [],
                                       ["Atendemos em Santa Rita e em Luzia."]) == "Rua Santa Luzia"


@pytest.mark.parametrize("etapa, conhecimento", [
    ("contratos", {"dados_escritorio": "Endereço: Rua Tiradentes, 100, Centro, Montes Claros/MG."}),
    ("assinatura", {"faq": [{"pergunta": "Onde fica o escritório?", "resposta": "Na Rua Tiradentes, 100, Centro."}]}),
])
async def test_endereco_do_escritorio_vindo_da_base_nao_e_barrado(etapa, conhecimento):
    texto = "Nosso escritório fica na Rua Tiradentes, 100, no Centro."
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta(texto)})
    saida = await turno.processar(modelo, entrada(["onde fica o escritório?"], etapa=etapa, conhecimento=conhecimento))
    assert saida.reprovacoes == [[]] and len(conteudos(modelo)) == 1
    assert saida.mensagens[0]["texto"].startswith("Nosso escritório fica na Rua Tiradentes")
    # Sem a base, a mesma rua continua sendo tratada como sem fonte.
    modelo = ModeloFalso({"extrator": extrai(), "etapa": [resposta(texto), resposta("Certo!")]})
    saida = await turno.processar(modelo, entrada(["onde fica o escritório?"], etapa=etapa))
    assert _codigos(saida)[0] == ["endereco_sem_fonte"]


# ---------------------------------------------------------------------------- [10] [12] [17] [20] CEP sem rótulo
def _enriquecer_que_anota():
    chamadas = []

    async def enriquecer(fatos):
        chamadas.append(fatos.get("cep"))
        if not fatos.get("cep"):
            return []
        return [{"chave": "_busca_cep", "valor": {"cep": fatos["cep"], "encontrado": False}, "fonte": "sistema"}]
    return enriquecer, chamadas


@pytest.mark.parametrize("pedido, lead, fatos", [
    ("Agora me envie o seu RG e o seu CEP, por favor.", "RG MG12345678", [("rg", "MG12345678", "MG12345678")]),
    ("Agora me envie o seu RG e o seu CEP, por favor.", "meu rg é 12345678", [("rg", "12345678", "12345678")]),
    ("Me informe a sua data de nascimento e o CEP.", "data de nascimento 15031980", []),
    ("Qual o seu CEP?", "nao sei o cep, meu rg é 12.345-678", []),
    ("Me passe o CEP.", "rg 12345678 e o cep já te mando", []),
])
async def test_numero_de_outro_dado_nao_vira_cep(pedido, lead, fatos):
    enriquecer, _ = _enriquecer_que_anota()
    modelo = ModeloFalso({"extrator": extrai(fatos), "etapa": resposta("Certo! E o seu CEP?")})
    saida = await turno.processar(modelo, entrada([lead], etapa="contratos", enriquecer=enriquecer,
                                                  historico=[{"autor": "você", "texto": pedido}]))
    assert "cep" not in saida.fatos_depois, lead
    assert "BUSCA DE CEP" not in conteudos(modelo)[0], lead


@pytest.mark.parametrize("lead", ["39999-412", "meu cep é 39999412", "o cep é 39999412 e o rg 1234567"])
async def test_cep_sem_rotulo_continua_capturado(lead):
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Certo!")})
    saida = await turno.processar(modelo, entrada([lead], etapa="contratos",
                                                  historico=[{"autor": "você", "texto": "Qual o seu CEP?"}]))
    assert saida.fatos_depois["cep"] == "39999-412", lead


async def test_cep_sem_rotulo_troca_o_cep_geral_quando_a_ia_pediu_o_da_rua():
    enriquecer, chamadas = _enriquecer_que_anota()
    historico = [{"autor": "você", "texto": "Esse CEP é geral da cidade. Me envie o CEP da sua rua?"}]
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Certo!")})
    saida = await turno.processar(modelo, entrada(["35501234"], etapa="contratos", fatos={"cep": "39999-000"},
                                                  historico=historico, enriquecer=enriquecer))
    assert saida.fatos_depois["cep"] == "35501-234" and chamadas == ["35501-234"]
    assert "BUSCA DE CEP (sistema): CEP 35501-234" in conteudos(modelo)[0]


async def test_cep_gravado_nao_e_trocado_pelo_mesmo_numero_nem_sem_a_ia_pedir():
    historico = [{"autor": "você", "texto": "Esse CEP é geral da cidade. Me envie o CEP da sua rua?"}]
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Certo!")})
    saida = await turno.processar(modelo, entrada(["39999000"], etapa="contratos", fatos={"cep": "39999-000"},
                                                  historico=historico))
    assert not [f for f in saida.fatos_novos if f["chave"] == "cep"]
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Certo!")})
    saida = await turno.processar(modelo, entrada(["35501234"], etapa="contratos", fatos={"cep": "39999-000"},
                                                  historico=[{"autor": "você", "texto": "Qual é o número da casa?"}]))
    assert saida.fatos_depois["cep"] == "39999-000"


# ---------------------------------------------------------------------------- [11] [21] busca do CEP
def _consultar_falso(monkeypatch, achados):
    from app.ferramentas import cep as ferramenta_cep
    consultas = []

    async def consultar(cep, **_):
        consultas.append(cep)
        if cep in achados:
            return ferramenta_cep.Endereco(cep=cep, valido=True, mensagem="ok", tipo="rua", origem="teste", **achados[cep])
        return ferramenta_cep.Endereco(cep=cep, valido=False, mensagem="CEP geral", tipo="geral")
    monkeypatch.setattr(ferramenta_cep, "consultar", consultar)
    return consultas


FATOS_DO_CEP_ANTIGO = {"cep": "35500-000", "endereco": "Rua do CEP Antigo", "bairro": "Bairro Antigo",
                       "cidade": "Cidade Antiga", "uf": "MG", turno.MARCA_CEP_CONSULTADO: "35500-000",
                       turno.MARCA_ENDERECO_DO_CEP: {"endereco": "Rua do CEP Antigo", "bairro": "Bairro Antigo",
                                                     "cidade": "Cidade Antiga", "uf": "MG"}}


async def test_cep_corrigido_refaz_a_busca_e_troca_o_endereco(monkeypatch):
    from app.pipeline import Atendimento
    consultas = _consultar_falso(monkeypatch, {"35501-234": {"logradouro": "Rua Nova", "bairro": "Bairro Novo",
                                                             "cidade": "Cidade Nova", "uf": "MG"}})
    modelo = ModeloFalso({"extrator": extrai([("cep", "35501-234", "35501-234")]), "etapa": resposta("Certo!")})
    saida = await turno.processar(modelo, entrada(["errei, o cep certo é 35501-234"], etapa="contratos",
                                                  fatos=dict(FATOS_DO_CEP_ANTIGO), enriquecer=Atendimento._enriquecer_por_cep))
    assert consultas == ["35501-234"]
    assert {k: saida.fatos_depois[k] for k in turno.CAMPOS_DO_ENDERECO} == {
        "endereco": "Rua Nova", "bairro": "Bairro Novo", "cidade": "Cidade Nova", "uf": "MG"}
    conteudo = conteudos(modelo)[0]
    assert "BUSCA DE CEP (sistema): CEP 35501-234 encontrado" in conteudo and "Antig" not in conteudo


async def test_cep_corrigido_nao_encontrado_nao_mantem_o_endereco_do_cep_antigo(monkeypatch):
    from app.pipeline import Atendimento
    _consultar_falso(monkeypatch, {})
    modelo = ModeloFalso({"extrator": extrai([("cep", "35501-234", "35501-234")]), "etapa": resposta("Certo!")})
    saida = await turno.processar(modelo, entrada(["errei, o cep certo é 35501-234"], etapa="contratos",
                                                  fatos=dict(FATOS_DO_CEP_ANTIGO), enriquecer=Atendimento._enriquecer_por_cep))
    assert all(saida.fatos_depois[k] == "" for k in turno.CAMPOS_DO_ENDERECO)
    assert "Antig" not in conteudos(modelo)[0] and "BUSCA DE CEP (sistema): CEP 35501-234 não encontrado" in conteudos(modelo)[0]


async def test_mesmo_cep_nao_encontrado_e_buscado_uma_vez_so(monkeypatch):
    from app.pipeline import Atendimento
    consultas = _consultar_falso(monkeypatch, {})
    fatos = {"cep": "39999-412", "endereco": "Rua do Lead", "cidade": "Vale Sereno", "uf": "MG"}   # sem bairro
    saidas = []
    for etapa, fala in (("contratos", "418"), ("contratos", "ok"), ("assinatura", "ok obrigado")):
        modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Certo!")})
        saida = await turno.processar(modelo, entrada([fala], etapa=etapa, fatos=dict(fatos),
                                                      enriquecer=Atendimento._enriquecer_por_cep))
        fatos = dict(saida.fatos_depois)
        saidas.append(conteudos(modelo)[0])
    assert consultas == ["39999-412"]
    assert "BUSCA DE CEP" in saidas[0] and not any("BUSCA DE CEP" in c for c in saidas[1:])
    assert fatos[turno.MARCA_CEP_CONSULTADO] == "39999-412"


# ============================================================================ revisão da rodada 2, 2ª passada
# Regressões dos achados confirmados na 2ª revisão (numeração da revisão entre colchetes). Tudo genérico.
CPF_FORMATADO = "057.830.862-23"
PEDE_RG = "Obrigada! Agora me informe o seu RG, por favor."
HISTORICO_PEDE_RG = [{"autor": "lead", "texto": CPF_FORMATADO}, {"autor": "você", "texto": PEDE_RG}]


def _tipos(saida):
    return [e["tipo"] for e in saida.eventos]


# ---------------------------------------------------------------------------- [0] dura diferente na 2ª tentativa
async def test_dura_nova_na_segunda_tentativa_depois_de_outra_dura_na_primeira_nao_pausa():
    # A 1ª tem cpf_ja_conferido; a 2ª obedece à CORRIJA e retoma o RG, e cai em resposta_repetida (que ela nunca recebeu).
    errada = resposta("O CPF informado está incorreto. Por favor, me envie o CPF correto.")
    modelo = ModeloFalso({"extrator": extrai(), "etapa": [errada, resposta(PEDE_RG)]})
    saida = await turno.processar(modelo, entrada([CPF_FORMATADO], etapa="contratos", fatos={"cpf": CPF_FORMATADO},
                                                  historico=list(HISTORICO_PEDE_RG)))
    assert _codigos(saida) == [["cpf_ja_conferido"], ["resposta_repetida"]]
    assert saida.estado_lead is None and saida.motivo_estado is None
    assert saida.mensagens[0]["texto"] == PEDE_RG
    assert "trava_resposta_repetida" in _tipos(saida) and "pedido_repetido" not in _tipos(saida)


async def test_mesma_dura_nas_duas_tentativas_continua_pausando():
    errada = resposta("O CPF informado está incorreto. Por favor, me envie o CPF correto.")
    modelo = ModeloFalso({"extrator": extrai(), "etapa": [errada, dict(errada)]})
    saida = await turno.processar(modelo, entrada([CPF_FORMATADO], etapa="contratos", fatos={"cpf": CPF_FORMATADO},
                                                  historico=list(HISTORICO_PEDE_RG)))
    assert (saida.estado_lead, saida.motivo_estado) == ("pausado", "pedido_repetido")


async def test_como_eu_falei_o_cpf_e_a_ia_retoma_o_rg_sai_o_pedido_do_rg():
    errada = resposta("O CPF informado está incorreto. Por favor, me envie o CPF correto.")
    modelo = ModeloFalso({"extrator": extrai(), "etapa": [errada, resposta(PEDE_RG)]})
    saida = await turno.processar(modelo, entrada([f"como eu falei meu cpf é {CPF_FORMATADO}"], etapa="contratos",
                                                  fatos={"cpf": CPF_FORMATADO}, historico=list(HISTORICO_PEDE_RG)))
    assert _codigos(saida) == [["cpf_ja_conferido"], []]
    assert saida.estado_lead is None and saida.mensagens[0]["texto"] == PEDE_RG


# ---------------------------------------------------------------------------- [1] lead repete outro dado, não o pedido
async def test_lead_repete_o_cpf_e_a_ia_retoma_o_rg_pendente_nao_e_laco():
    modelo = ModeloFalso({"extrator": extrai(), "etapa": [resposta(PEDE_RG), resposta(PEDE_RG)]})
    novo = entrada([f"meu cpf é {CPF_FORMATADO}"], etapa="contratos", fatos={"cpf": CPF_FORMATADO},
                   historico=list(HISTORICO_PEDE_RG))
    assert turno._lead_repetiu(novo, PEDE_RG) is None
    saida = await turno.processar(modelo, novo)
    assert saida.reprovacoes == [[]] and saida.estado_lead is None
    assert saida.mensagens[0]["texto"] == PEDE_RG


def test_dado_repetido_que_a_resposta_pede_continua_sendo_laco():
    novo = entrada(["como eu falei, ana@exemplo.com"], etapa="contratos", fatos={"email": "ana@exemplo.com"})
    assert turno._lead_repetiu(novo, "Qual é o seu e-mail, por favor?") == "email"
    novo = entrada(["já te mandei, (31) 99999-1234"], etapa="contratos", fatos={"telefone_contrato": "31999991234"})
    assert turno._lead_repetiu(novo, "Me informe o seu telefone com DDD.") == "telefone_contrato"
    novo = entrada([f"meu cpf é {CPF_FORMATADO}"], etapa="contratos", fatos={"cpf": CPF_FORMATADO})
    assert turno._lead_repetiu(novo, "O CPF está incorreto, me envie o CPF correto.") == "cpf"


# ---------------------------------------------------------------------------- [2] pedido de reenvio
RESUMO = ("Confira os seus dados: Nome: Ana Souza; CPF: 529.982.247-25; RG: MG1234567; Endereço: Rua das Flores, 123, "
          "Centro, Itabira/MG; CEP: 35900-000. Está tudo correto?")
FATOS_DO_RESUMO = {"nome_completo": "Ana Souza", "cpf": CPF, "rg": "MG1234567", "endereco": "Rua das Flores",
                   "numero_casa": "123", "bairro": "Centro", "cidade": "Itabira", "uf": "MG", "cep": "35900-000"}


@pytest.mark.parametrize("pedido, abertura", [
    ("manda de novo os dados, não apareceu aqui", "Claro, reenvio aqui! "),
    ("não chegou a mensagem, envia outra vez", "Sem problema, segue de novo. "),
])
async def test_lead_que_pede_o_reenvio_do_resumo_de_novo_nao_e_pausado(pedido, abertura):
    historico = [{"autor": "lead", "texto": pedido}, {"autor": "você", "texto": RESUMO}]
    modelo = ModeloFalso({"extrator": extrai(), "etapa": [resposta(abertura + RESUMO), resposta(abertura + RESUMO)]})
    saida = await turno.processar(modelo, entrada([pedido], etapa="contratos", fatos=dict(FATOS_DO_RESUMO),
                                                  historico=historico))
    assert saida.reprovacoes == [[]] and saida.estado_lead is None and len(conteudos(modelo)) == 1
    assert saida.mensagens[0]["texto"].startswith(abertura.strip())


async def test_manda_de_novo_curto_repetido_nao_e_laco():
    pede = "Qual é o seu RG, por favor?"
    historico = [{"autor": "lead", "texto": "manda de novo"}, {"autor": "você", "texto": pede}]
    modelo = ModeloFalso({"extrator": extrai(), "etapa": [resposta(pede), resposta(pede)]})
    saida = await turno.processar(modelo, entrada(["manda de novo"], etapa="contratos", historico=historico))
    assert saida.reprovacoes == [[]] and saida.estado_lead is None


# ---------------------------------------------------------------------------- [3] promessas frase a frase
@pytest.mark.parametrize("frase", [
    "Então nós vamos analisar o seu caso e entender se você tem direito a esse retroativo.",
    "Vamos analisar o seu caso para ver se você tem direito a esse retroativo.",
    "Para saber se você tem direito, preciso de algumas informações.",
    "Claro, com certeza! Vai ser um prazer te ajudar.",
    "Com certeza! Vai chegar aqui o link.",
    "Assim você vai ganhar tempo.",
    "É sem risco de perder o prazo.",
    "Você tem direito a algum outro benefício do INSS?",
])
def test_condicional_pergunta_e_frases_separadas_nao_sao_promessa(frase):
    assert travas.trecho_de_promessa(frase) is None, frase
    assert catalogo.conferir([{"tipo": "texto", "texto": frase}]) == [], frase
    assert "promessa" not in [r.codigo for r in travas.conferir([{"tipo": "texto", "texto": frase}], etapa="closer",
                                                                honorarios=None, midias={}, faltam=())], frase


@pytest.mark.parametrize("frase, trecho", [
    ("Você tem direito ao auxílio-acidente.", "voce tem direito"),
    ("Pode ficar tranquila, você vai ganhar a causa.", "vai ganhar"),
    ("Com certeza vai sair o benefício.", "com certeza vai"),
    ("É sem risco nenhum.", "sem risco"),
    ("Se você tem direito? Tem sim, você tem direito.", "voce tem direito"),
])
def test_promessa_de_verdade_continua_barrada(frase, trecho):
    assert travas.trecho_de_promessa(frase) == trecho, frase


# ---------------------------------------------------------------------------- [4] ação da IA e explicação do motivo
PERGUNTA_DO_CPF = f"{CPF} pra que vocês precisam do meu cpf?"


@pytest.mark.parametrize("texto", [
    "Precisamos do seu CPF só para preencher o contrato, ele fica em sigilo. Agora me informe o seu RG.",
    "Obrigada! Vou enviar o seu CPF para a equipe gerar o contrato.",
    "Vou confirmar o seu CPF no sistema. Qual é o seu RG?",
    "Nós precisamos do CPF para o contrato.",
])
async def test_ia_explicando_o_cpf_ou_contando_o_que_faz_com_ele_nao_e_pedido(texto):
    assert _guarda(texto, {"cpf": CPF}, [PERGUNTA_DO_CPF]) is None, texto
    modelo = ModeloFalso({"extrator": extrai([("cpf", CPF, CPF)]), "etapa": [resposta(texto), resposta(texto)]})
    saida = await turno.processar(modelo, entrada([PERGUNTA_DO_CPF], etapa="contratos"))
    assert saida.estado_lead is None and saida.reprovacoes == [[]], texto


@pytest.mark.parametrize("texto", ["Vamos, me envie o seu CPF de novo.", "Preciso do seu CPF.", "Me envie o seu CPF."])
def test_pedido_do_cpf_ao_lead_continua_barrado(texto):
    guarda = _guarda(texto, {"cpf": CPF}, [CPF])
    assert guarda and guarda.codigo == "cpf_ja_conferido", texto


# ---------------------------------------------------------------------------- [5] [11] CEP corrigido e endereço do lead
FATOS_DIGITADOS = {"cep": "35900-000", "endereco": "Rua das Flores", "bairro": "Centro", "cidade": "Itabira", "uf": "MG",
                   turno.MARCA_CEP_CONSULTADO: "35900-000"}
DO_LEAD = {"endereco": "Rua das Flores", "bairro": "Centro", "cidade": "Itabira", "uf": "MG"}


@pytest.mark.parametrize("achados", [{}, {"35900-123": {"logradouro": "Rua X", "bairro": "B", "cidade": "Cidade X", "uf": "SP"}}])
async def test_cep_corrigido_nao_apaga_nem_troca_o_endereco_que_o_lead_digitou(monkeypatch, achados):
    from app.pipeline import Atendimento
    _consultar_falso(monkeypatch, achados)
    modelo = ModeloFalso({"extrator": extrai([("cep", "35900-123", "35900-123")]), "etapa": resposta("Certo!")})
    saida = await turno.processar(modelo, entrada(["errei o cep, é 35900-123"], etapa="contratos",
                                                  fatos=dict(FATOS_DIGITADOS), enriquecer=Atendimento._enriquecer_por_cep))
    assert {k: saida.fatos_depois[k] for k in turno.CAMPOS_DO_ENDERECO} == DO_LEAD
    assert not [f for f in saida.fatos_novos if f.get("trecho") == "(CEP trocado)"]
    assert "endereco=Rua das Flores" in conteudos(modelo)[0]


@pytest.mark.parametrize("achados, esperado", [
    ({}, {"endereco": "Rua das Flores", "cidade": "Itabira", "bairro": "", "uf": ""}),
    ({"35900-123": {"logradouro": "Rua X", "bairro": "Bairro Novo", "cidade": "Cidade Nova", "uf": "SP"}},
     {"endereco": "Rua das Flores", "cidade": "Itabira", "bairro": "Bairro Novo", "uf": "SP"}),
])
async def test_cep_corrigido_refaz_so_o_que_veio_do_cep_anterior(monkeypatch, achados, esperado):
    from app.pipeline import Atendimento
    _consultar_falso(monkeypatch, achados)
    fatos = {**FATOS_DIGITADOS, turno.MARCA_ENDERECO_DO_CEP: {"bairro": "Centro", "uf": "MG"}}   # rua e cidade do lead
    modelo = ModeloFalso({"extrator": extrai([("cep", "35900-123", "35900-123")]), "etapa": resposta("Certo!")})
    saida = await turno.processar(modelo, entrada(["errei o cep, é 35900-123"], etapa="contratos", fatos=fatos,
                                                  enriquecer=Atendimento._enriquecer_por_cep))
    assert {k: saida.fatos_depois[k] for k in turno.CAMPOS_DO_ENDERECO} == esperado
    assert saida.fatos_depois[turno.MARCA_ENDERECO_DO_CEP] == {k: v for k, v in esperado.items()
                                                              if k in ("bairro", "uf") and v}


# ---------------------------------------------------------------------------- [6] CPF do(a) menor igual ao do titular
@pytest.mark.parametrize("texto", ["Esse CPF é o mesmo que o seu. Me envie o CPF da criança, por favor.",
                                   "Qual é o CPF da criança?"])
def test_pedir_o_cpf_da_crianca_quando_veio_o_do_titular_nao_e_barrado(texto):
    assert _guarda(texto, {"cpf": CPF, "cpf_menor": CPF}, [CPF]) is None, texto


def test_pedir_de_novo_o_cpf_do_titular_continua_barrado_com_o_menor_igual():
    guarda = _guarda("Me envie o seu CPF de novo.", {"cpf": CPF, "cpf_menor": CPF}, [CPF])
    assert guarda and guarda.codigo == "cpf_ja_conferido"


async def test_cpf_do_menor_igual_ao_do_titular_nao_e_gravado_nem_dito_valido():
    pede = resposta("Esse CPF é o mesmo que o seu. Me envie o CPF da criança, por favor.")
    modelo = ModeloFalso({"extrator": extrai([("cpf_menor", "05783086223", "05783086223")]), "etapa": [pede, dict(pede)]})
    saida = await turno.processar(modelo, entrada(["o cpf dele é 05783086223"], etapa="contratos",
                                                  fatos={"cpf": CPF_FORMATADO}))
    conteudo = conteudos(modelo)[0]
    assert "CONFERÊNCIA DO CPF do(a) menor (sistema): 057.830.862-23 é IGUAL ao CPF do titular" in conteudo
    assert "do(a) menor (sistema): 057.830.862-23 é VÁLIDO" not in conteudo
    assert "cpf_menor" not in saida.fatos_depois and not [f for f in saida.fatos_novos if f["chave"] == "cpf_menor"]
    assert saida.estado_lead is None and saida.reprovacoes == [[]]


def test_contrato_recusa_cpf_do_menor_igual_ao_do_titular():
    from tests.test_correcoes_rodada_real import CONTRATO_SEM_CPF
    fatos = {**CONTRATO_SEM_CPF, "cpf": CPF, "cpf_menor": CPF}
    _, erros = cdados.validar_dados(cdados.dados_dos_fatos(fatos))
    assert [e.campo for e in erros] == ["cpfdomenor"]
    _, erros = cdados.validar_dados(cdados.dados_dos_fatos({**fatos, "cpf_menor": CPF_FORMATADO}))
    assert erros == []


# ---------------------------------------------------------------------------- [7] [12] [15] serviço de CEP fora do ar
import httpx  # noqa: E402

_CLIENTE_HTTPX = httpx.AsyncClient      # o original, antes de qualquer troca (o _rede pode ser chamado mais de uma vez)


def _rede(monkeypatch, tratar):
    from app.ferramentas import cep as ferramenta_cep
    original = _CLIENTE_HTTPX
    pedidos = []

    def anotar(pedido):
        pedidos.append(str(pedido.url))
        return tratar(pedido)

    def cliente(*args, **kwargs):
        kwargs.pop("transport", None)
        return original(*args, transport=httpx.MockTransport(anotar), **kwargs)
    monkeypatch.setattr(ferramenta_cep.httpx, "AsyncClient", cliente)
    return pedidos


def _fora_do_ar(pedido):
    import httpx
    raise httpx.ConnectTimeout("timeout", request=pedido)


def _no_ar(pedido):
    import httpx
    return httpx.Response(200, json={"logradouro": "Rua X", "bairro": "Centro", "localidade": "Belo Horizonte", "uf": "MG"})


async def test_cep_com_todas_as_fontes_fora_do_ar_e_falha_e_nao_nao_encontrado(monkeypatch):
    from app.ferramentas import cep as ferramenta_cep
    _rede(monkeypatch, _fora_do_ar)
    r = await ferramenta_cep.consultar("30140-071")
    assert not r.valido and r.falhou and "não encontrado" not in r.mensagem
    import httpx
    _rede(monkeypatch, lambda pedido: httpx.Response(503, json={}))
    assert (await ferramenta_cep.consultar("30140-071")).falhou
    _rede(monkeypatch, lambda pedido: httpx.Response(404, json={}))
    r = await ferramenta_cep.consultar("30140-071")
    assert not r.falhou and "não encontrado" in r.mensagem


async def test_busca_do_cep_que_falhou_na_rede_e_refeita_no_turno_seguinte(monkeypatch):
    from app.pipeline import Atendimento
    pedidos = _rede(monkeypatch, _fora_do_ar)
    modelo = ModeloFalso({"extrator": extrai([("cep", "30140-071", "30140-071")]), "etapa": resposta("Certo!")})
    saida = await turno.processar(modelo, entrada(["meu cep é 30140-071"], etapa="contratos",
                                                  enriquecer=Atendimento._enriquecer_por_cep))
    conteudo = conteudos(modelo)[0]
    assert len(pedidos) == 3 and turno.MARCA_CEP_CONSULTADO not in saida.fatos_depois
    assert "a busca do CEP 30140071 não pôde ser feita agora" in conteudo and "não encontrado" not in conteudo
    pedidos = _rede(monkeypatch, _no_ar)
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Certo!")})
    saida = await turno.processar(modelo, entrada(["ok, e agora?"], etapa="contratos", fatos=dict(saida.fatos_depois),
                                                  enriquecer=Atendimento._enriquecer_por_cep))
    assert len(pedidos) == 1 and saida.fatos_depois["endereco"] == "Rua X"
    assert saida.fatos_depois[turno.MARCA_CEP_CONSULTADO] == "30140-071"
    assert "BUSCA DE CEP (sistema): CEP 30140071 encontrado" in conteudos(modelo)[0]


# ---------------------------------------------------------------------------- [8] CEP geral da cidade
def _consultar_geral(monkeypatch):
    from app.ferramentas import cep as ferramenta_cep

    async def consultar(cep, **_):
        return ferramenta_cep.Endereco(cep="35500000", valido=False, tipo="geral", origem="teste", cidade="Divinópolis",
                                       uf="MG", mensagem="CEP geral da cidade, sem rua. Peça o CEP da rua.")
    monkeypatch.setattr(ferramenta_cep, "consultar", consultar)


@pytest.mark.parametrize("fatos, cidade", [({}, "Divinópolis"), ({"cidade": "Carmo do Cajuru"}, "Carmo do Cajuru")])
async def test_cep_geral_da_cidade_preenche_cidade_e_uf_e_nao_e_dito_nao_encontrado(monkeypatch, fatos, cidade):
    from app.pipeline import Atendimento
    _consultar_geral(monkeypatch)
    modelo = ModeloFalso({"extrator": extrai([("cep", "35500-000", "35500-000")]), "etapa": resposta("Certo!")})
    saida = await turno.processar(modelo, entrada(["meu cep é 35500-000"], etapa="contratos", fatos=dict(fatos),
                                                  enriquecer=Atendimento._enriquecer_por_cep))
    assert saida.fatos_depois["cidade"] == cidade and saida.fatos_depois["uf"] == "MG"
    assert "endereco" not in saida.fatos_depois
    conteudo = conteudos(modelo)[0]
    assert "BUSCA DE CEP (sistema): CEP 35500000 é o CEP geral de Divinópolis/MG (sem rua)" in conteudo
    assert "não encontrado" not in conteudo


# ---------------------------------------------------------------------------- [9] CPF inválido de um turno anterior
async def test_cpf_invalido_gravado_antes_nao_e_pedido_de_novo_a_cada_turno():
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Certo! E o número da casa?")})
    await turno.processar(modelo, entrada(["Rua das Flores 123"], etapa="contratos", fatos={"cpf": "057.830.862-24"}))
    conteudo = conteudos(modelo)[0]
    assert "uma única vez" not in conteudo and "segue pendente" in conteudo
    # O CPF inválido que chega neste turno continua com o pedido de uma vez.
    modelo = ModeloFalso({"extrator": extrai([("cpf", "057.830.862-24", "057.830.862-24")]), "etapa": resposta("Certo!")})
    await turno.processar(modelo, entrada(["057.830.862-24"], etapa="contratos"))
    assert "Peça o CPF de novo uma única vez" in conteudos(modelo)[0]


# ---------------------------------------------------------------------------- [10] agente clássico com campo extra
def test_produto_classico_pede_o_campo_extra_do_modelo_do_contrato():
    from app.cerebro.produto import AuxilioAcidente
    from tests.test_correcoes_rodada_real import CONTRATO_SEM_CPF
    fatos = {**CONTRATO_SEM_CPF, "cpf": CPF}
    com_email = cdados.OBRIGATORIOS_PADRAO + ("email",)
    passo = AuxilioAcidente(contrato=True, obrigatorios_contrato=com_email).decidir_etapa(
        "coleta_dados", fatos, {"confirmou_dados": True})
    assert (passo.motivo, passo.faltam) == ("faltam_dados_contrato", ("email",))
    assert AuxilioAcidente(contrato=True).decidir_etapa("coleta_dados", fatos, {"confirmou_dados": True}).motivo == \
        "dados_confirmados"


async def test_pipeline_classico_com_dado_faltando_pede_a_correcao_e_avisa_a_equipe():
    from app.banco.tipos import Lead
    from tests.test_catalogo import montar
    from tests.test_correcoes_rodada_real import CONTRATO_SEM_CPF

    atendimento, repo, _, _ = montar({"mensagens": [{"texto": "Certo!"}], "transferir_para": "", "ferramenta": ""})
    repo.zapsign = {"esc-1": {"modelos": [{"id_modelo": "m-1", "id_agente": "ag-1",
                                           "obrigatorios": list(cdados.OBRIGATORIOS_PADRAO + ("email",))}]}}
    escritorio, agente = repo.escritorios["esc-1"], repo.agentes["canal-1"]
    agente.produto = "auxilio_acidente"
    lead = Lead(id="lead-1", id_escritorio="esc-1", id_canal="canal-1", id_agente="ag-1", id_etapa="e-contratos",
                telefone="5511999990000", id_sessao_helena="sessao-1")
    saida = turno.Saida(motivo="dados_confirmados", fatos_depois={**CONTRATO_SEM_CPF, "cpf": CPF})
    await atendimento._acoes_do_contrato(escritorio, agente, lead, "turno-1", saida, "teste")
    assert [a["tipo"] for a in repo.acoes] == ["enviar_mensagem", "nota"]
    assert cdados.PEDIR["email"] in repo.acoes[0]["dados"]["texto"]
    assert repo.acoes[1]["chave_unica"] == "lead-1:contrato:nota_corrigir"


# ---------------------------------------------------------------------------- [13] ano por extenso ou com ponto
@pytest.mark.parametrize("trecho, ano", [("foi em dois mil e vinte", 2020), ("dois mil e vinte", 2020),
                                         ("foi em vinte e um", 2021), ("em 2.019", 2019), ("2.019", 2019),
                                         ("mil novecentos e noventa e oito", 1998), ("foi em noventa e oito", 1998)])
def test_ano_por_extenso_ou_com_ponto_vale(trecho, ano):
    from app.cerebro import extrator
    extracao = extrator.conferir({"fatos": [{"chave": "acidente_ano", "valor": ano, "trecho": trecho}]}, [trecho], {})
    assert [f.valor for f in extracao.fatos] == [ano], (trecho, extracao.rejeitados)


# ---------------------------------------------------------------------------- [14] provedor falha na 2ª tentativa
async def test_falha_do_provedor_na_correcao_de_trava_leve_entrega_a_primeira_resposta():
    prod = produto(closer={"exigir_frase_de_troca": True})
    passa = resposta("Certo! Vou te passar para a especialista.", transferir="closer")
    modelo = ModeloFalso({"extrator": extrai(), "etapa": [passa]})            # a 2ª chamada falha (acabaram as respostas)
    saida = await turno.processar(modelo, entrada(["era registrado sim"], prod=prod))
    assert _codigos(saida) == [["frase_de_troca"]]
    # A 1ª resposta sai, com a frase de troca inserida pelo motor como último balão.
    assert saida.situacao == "respondido" and [m["texto"] for m in saida.mensagens][-2:] == [
        "Certo! Vou te passar para a especialista.", "Maravilha! Nós podemos te ajudar no seu caso."]
    assert {"segunda_tentativa_falhou", "trava_frase_de_troca"} <= set(_tipos(saida))
    assert "ia_nao_respondeu" not in _tipos(saida)


async def test_falha_do_provedor_depois_de_trava_dura_continua_sem_resposta():
    errada = resposta("O CPF informado está incorreto. Por favor, me envie o CPF correto.")
    modelo = ModeloFalso({"extrator": extrai(), "etapa": [errada]})
    saida = await turno.processar(modelo, entrada([CPF_FORMATADO], etapa="contratos", fatos={"cpf": CPF_FORMATADO}))
    assert saida.situacao == "erro" and saida.mensagens == [] and "ia_nao_respondeu" in _tipos(saida)


# ---------------------------------------------------------------------------- [16] mídia repetida sem conteúdo
FOTO_ILEGIVEL = "[O lead enviou uma imagem que não foi possível ver. Se for documento, peça uma foto nítida ou o PDF.]"
FIGURINHA = "[O lead enviou uma figurinha. Trate como reação, não como informação do caso.]"


@pytest.mark.parametrize("midia, pedido", [
    (FOTO_ILEGIVEL, "Não consegui ver a imagem. Pode me enviar uma foto mais nítida do seu RG, por favor?"),
    (FIGURINHA, "Certo! E qual é o seu estado civil?"),
])
async def test_midia_sem_conteudo_repetida_nao_e_laco(midia, pedido):
    historico = [{"autor": "lead", "texto": midia}, {"autor": "você", "texto": pedido}]
    modelo = ModeloFalso({"extrator": extrai(), "etapa": [resposta(pedido), resposta(pedido)]})
    saida = await turno.processar(modelo, entrada([midia], etapa="contratos", historico=historico))
    assert saida.estado_lead is None and len(conteudos(modelo)) == 1 and saida.reprovacoes == [[]]


def test_midia_com_conteudo_repetida_ainda_conta_pelo_conteudo():
    legivel = "[O lead enviou uma imagem. O que dá para ver:]\nRG de Ana Souza, número 12.345.678"
    novo = entrada([legivel], etapa="contratos", historico=[{"autor": "lead", "texto": legivel}])
    assert turno._lead_repetiu(novo, "Pode me enviar o RG?") == "a mesma mensagem"
    assert turno._sem_marca_de_midia("[O lead enviou um vídeo. O que ele fala: caí da moto]").strip() == "caí da moto]"


# ---------------------------------------------------------------------------- frase de troca garantida pelo motor
async def test_passagem_sem_frase_recebe_a_frase_exata_no_ultimo_balao():
    passa = resposta("Obrigado por informar que está registrado desde 2021.", transferir="closer")
    modelo = ModeloFalso({"extrator": extrai(), "etapa": passa})
    saida = await turno.processar(modelo, entrada(["sou registrado desde 2021"]))
    frase = "Maravilha! Nós podemos te ajudar no seu caso."
    # Último balão: depois do texto de saída, a mensagem de entrada do destino fecha a resposta (regra do motor).
    assert saida.etapa_depois == "closer" and saida.mensagens[-1]["texto"] == frase
    assert "frase_de_troca_inserida" in _tipos(saida)


async def test_frase_ja_dita_nao_e_repetida():
    frase = "Maravilha! Nós podemos te ajudar no seu caso."
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta(frase, transferir="closer")})
    saida = await turno.processar(modelo, entrada(["sou registrado sim"]))
    assert [m["texto"] for m in saida.mensagens].count(frase) == 1 and "frase_de_troca_inserida" not in _tipos(saida)


async def test_papel_pode_desligar_a_insercao_da_frase():
    prod = produto(closer={"inserir_frase_de_troca": False})
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Certo, vamos seguir.", transferir="closer")})
    saida = await turno.processar(modelo, entrada(["sou registrado sim"], prod=prod))
    assert "frase_de_troca_inserida" not in _tipos(saida)
