"""Correções do motor (rodada 2 dos achados das rodadas 2026-11-25_0317 Sousa e Costa e 2026-11-25_0146 referência).

Tudo genérico, multi-escritório: o que é de um escritório só fica na config dele (papeis[x]...), nunca no código.
- CPF conferido pelo sistema no turno (antiga BUSCARCPF): válido sai formatado e não é pedido de novo;
- anti-laço: resposta igual à anterior + lead repetindo = CORRIJA e, se insistir, a equipe assume;
- CEP sem rótulo capturado pelo código, resultado da busca dito ao modelo, endereço inventado barrado;
- UF por extenso vira sigla; CEP e telefone só com dígitos certos;
- "garantir o direito" barrado na trava de produção; "100% online" não é honorário;
- "até hoje dói" não vira data do acidente; calculadora diz a cobertura e avisa data faltando/conflito;
- travas de transferência: pergunta exigida antes de passar, frase de outro destino, frase obrigatória (opt-in),
  passagem com pergunta em aberto, desqualificar quem estava coberto;
- formatador: travessão antes de pontuação não vira ", ,".
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.cerebro import catalogo, contexto, extrator, formatador, travas, turno
from app.cerebro import auxilio_acidente as aa
from app.contrato import dados as cdados
from app.modelo import ModeloFalso


@pytest.fixture(autouse=True)
def _pausa_por_repeticao_ligada(monkeypatch):
    """Estes testes medem o mecanismo de pausa das travas de repetição; em produção ele vem desligado
    (turno.PAUSAR_EM_REPETICAO = False, ver test_travas_de_repeticao_nao_pausam_por_padrao)."""
    monkeypatch.setattr(turno, "PAUSAR_EM_REPETICAO", True)

AGORA = datetime(2026, 3, 10, 10, 0, tzinfo=timezone(timedelta(hours=-3)))
SEM_INTENCAO = {"pediu_humano": False, "pediu_para_parar": False, "engano": False, "diz_que_assinou": False, "pediu_link": False}
CPF_DO_CASO = "057.830.862.23"           # válido: os dígitos 2 e 3 conferem (o ponto está no lugar do traço)
PAPEIS = ("sdr", "periododegraca", "closer", "contratos", "assinatura", "desqualificado")
TROCAS = {"periododegraca": "Agora vou confirmar algumas informações importantes sobre seu vínculo com o INSS, tudo bem?",
          "closer": "Maravilha! Nós podemos te ajudar no seu caso.",
          "desqualificado": "Analisei com atenção o que você nos contou e você não se enquadra nos critérios."}


def produto(papeis=PAPEIS, **extra):
    # Estes turnos são do meio da conversa, montados sem histórico: a trava da troca na 1ª resposta (tool fantasma,
    # ver tests/test_troca_correcoes.py) fica liberada para medir só a lógica da passagem.
    cfg = {p: {"destinos": [d for d in papeis if d != p], "mensagem_troca": TROCAS.get(p),
               "transferir_na_primeira_resposta": True} for p in papeis}
    for papel, valores in extra.items():
        cfg[papel].update(valores)
    return catalogo.carregar({"catalogo": {"papeis": cfg}, "funcoes": {"contrato_zapsign": True}})


def extrai(fatos=(), **intencoes):
    return {"fatos": [{"chave": c, "valor": v, "trecho": t} for c, v, t in fatos], "sinais": [],
            "intencoes": {**SEM_INTENCAO, **intencoes}}


def resposta(texto="Certo!", transferir="", ferramenta=""):
    return {"mensagens": [{"texto": texto}], "transferir_para": transferir, "ferramenta": ferramenta}


# Leva 1 (B4): estes turnos são do meio da conversa; o lead já respondeu o que o portão de fatos exige para o Closer e
# para Contratos (aposentadoria, advogado no caso, sequela e o aceite). Quem testa desqualificar dá o motivo.
QUALIFICADO = {"aposentado": "nao", "tem_advogado_no_caso": "nao", "sequela": "sim", "aceite_honorarios": "sim"}


def entrada(novas, etapa="sdr", prod=None, fatos=None, **extra):
    return turno.Entrada(escritorio="Escritório Teste", agente="Júlia", etapa=etapa, novas=list(novas),
                         produto=prod or produto(), instrucoes={etapa: "Roteiro do papel."}, agora=AGORA,
                         fatos={**QUALIFICADO, **(fatos or {})}, **extra)


def conteudos(modelo):
    return [p["conteudo"] for p in modelo.pedidos if p["papel"] == "etapa"]


# ---------------------------------------------------------------------------- [0] [12] CPF conferido no turno
def test_cpf_do_caso_e_valido_e_sai_formatado():
    assert cdados.cpf_valido(CPF_DO_CASO) and cdados.cpf_valido("205.096.961.98")
    assert cdados.formatar_cpf(CPF_DO_CASO) == "057.830.862-23"
    assert cdados.formatar_cpf("205.096.961.98") == "205.096.961-98"
    assert cdados.formatar_cpf("123.456.789-00") is None


async def test_cpf_valido_vai_formatado_e_conferido_para_o_modelo():
    modelo = ModeloFalso({"extrator": extrai([("cpf", CPF_DO_CASO, CPF_DO_CASO)]),
                          "etapa": resposta("Obrigada! Agora me informe o seu RG.")})
    saida = await turno.processar(modelo, entrada([CPF_DO_CASO], etapa="contratos"))
    conteudo = conteudos(modelo)[0]
    assert "CONFERÊNCIA DO CPF (sistema): 057.830.862-23 é VÁLIDO" in conteudo
    assert "cpf=057.830.862-23" in conteudo and "057.830.862.23;" not in conteudo
    assert saida.fatos_depois["cpf"] == "057.830.862-23"
    assert [f["valor"] for f in saida.fatos_novos if f["chave"] == "cpf"] == ["057.830.862-23"]
    assert len(modelo.pedidos) == 2 and saida.estado_lead is None


async def test_cpf_invalido_pode_ser_pedido_de_novo():
    modelo = ModeloFalso({"extrator": extrai([("cpf", "123.456.789-00", "123.456.789-00")]),
                          "etapa": resposta("Os números do CPF não conferem. Pode me enviar de novo?")})
    saida = await turno.processar(modelo, entrada(["123.456.789-00"], etapa="contratos"))
    assert "é INVÁLIDO (os dígitos verificadores não conferem)" in conteudos(modelo)[0]
    assert len(conteudos(modelo)) == 1 and saida.estado_lead is None


async def test_ia_que_inventa_cpf_errado_e_corrigida_uma_vez():
    errada = "O CPF informado está incorreto, pois não passou na validação dos dígitos. Por favor, me envie o CPF correto."
    modelo = ModeloFalso({"extrator": extrai([("cpf", CPF_DO_CASO, CPF_DO_CASO)]),
                          "etapa": [resposta(errada), resposta("Recebido! Agora me informe o seu RG.")]})
    saida = await turno.processar(modelo, entrada([CPF_DO_CASO], etapa="contratos"))
    assert saida.mensagens[0]["texto"] == "Recebido! Agora me informe o seu RG."
    assert "CORRIJA: O sistema já conferiu o CPF (057.830.862-23): é VÁLIDO" in conteudos(modelo)[1]
    assert saida.reprovacoes[0][0]["codigo"] == "cpf_ja_conferido" and saida.estado_lead is None


async def test_ia_que_insiste_no_cpf_errado_passa_para_a_equipe():
    errada = resposta("O último grupo do CPF deve ter dois dígitos. Pode me enviar o CPF correto?")
    modelo = ModeloFalso({"extrator": extrai(), "etapa": [errada, dict(errada)]})
    saida = await turno.processar(modelo, entrada([f"como eu falei, {CPF_DO_CASO}"], etapa="contratos",
                                                  fatos={"cpf": "057.830.862-23"}))
    assert (saida.estado_lead, saida.motivo_estado) == ("pausado", "pedido_repetido")
    assert [m["texto"] for m in saida.mensagens] == [turno.MENSAGENS_FIXAS["contrato_com_a_equipe"]]
    assert saida.eventos[-1]["tipo"] == "pedido_repetido"


@pytest.mark.parametrize("texto", [
    "Confira os seus dados: Nome: Ana Souza; CPF: 057.830.862-23. Está tudo correto?",
    "Perfeito, recebi o CPF. Agora me passe o seu RG, por favor.",
    "Se o CPF estiver errado no contrato, é só me avisar.",
])
async def test_resumo_e_proximo_campo_nao_sao_barrados(texto):
    modelo = ModeloFalso({"extrator": extrai([("cpf", CPF_DO_CASO, CPF_DO_CASO)]), "etapa": resposta(texto)})
    saida = await turno.processar(modelo, entrada([CPF_DO_CASO], etapa="contratos"))
    assert len(conteudos(modelo)) == 1 and saida.mensagens and saida.estado_lead is None, texto


async def test_mesmo_cpf_em_outro_formato_nao_e_dado_novo():
    modelo = ModeloFalso({"extrator": extrai([("cpf", CPF_DO_CASO, CPF_DO_CASO)]), "etapa": resposta("Certo! E o seu RG?")})
    saida = await turno.processar(modelo, entrada([CPF_DO_CASO], etapa="contratos", fatos={"cpf": "057.830.862-23"}))
    assert not [f for f in saida.fatos_novos if f["chave"] == "cpf"]


# ---------------------------------------------------------------------------- [0](3) anti-laço genérico
def _historico_pedindo_email():
    return [{"autor": "lead", "texto": "meu email é ana@exemplo.com"},
            {"autor": "você", "texto": "Qual é o seu e-mail, por favor? Preciso dele para o contrato."}]


async def test_resposta_repetida_com_lead_repetindo_e_corrigida_e_depois_vai_para_a_equipe():
    igual = resposta("Qual é o seu e-mail, por favor? Preciso dele para o contrato.")
    modelo = ModeloFalso({"extrator": extrai(), "etapa": [igual, dict(igual)]})
    saida = await turno.processar(modelo, entrada(["como eu falei, ana@exemplo.com"], etapa="contratos",
                                                  fatos={"email": "ana@exemplo.com"}, historico=_historico_pedindo_email()))
    assert "Sua resposta repete a sua última mensagem" in conteudos(modelo)[1]
    assert saida.motivo_estado == "pedido_repetido"


async def test_resposta_repetida_mas_lead_trouxe_dado_novo_nao_e_laco():
    igual = resposta("Qual é o seu e-mail, por favor? Preciso dele para o contrato.")
    modelo = ModeloFalso({"extrator": extrai([("numero_casa", "318", "318")]), "etapa": igual})
    saida = await turno.processar(modelo, entrada(["318"], etapa="contratos", historico=_historico_pedindo_email()))
    assert len(conteudos(modelo)) == 1 and saida.estado_lead is None


async def test_resumo_corrigido_que_cita_o_dado_repetido_nao_e_laco():
    resumo = "Pronto, corrigi. Bairro: Vila Esperança. Cidade: Vale Sereno. Posso gerar o contrato?"
    historico = [{"autor": "lead", "texto": "o bairro é Vila Esperança"},
                 {"autor": "você", "texto": "Pronto. Bairro: Vila Esperança Vila Esperança. Cidade: Vale Sereno. Posso gerar o contrato?"}]
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta(resumo)})
    saida = await turno.processar(modelo, entrada(["o bairro ta repetido, é só Vila Esperança"], etapa="contratos",
                                                  fatos={"bairro": "Vila Esperança"}, historico=historico))
    assert len(conteudos(modelo)) == 1 and saida.estado_lead is None


# ---------------------------------------------------------------------------- [2] [3] [13] CEP
def test_validar_valor_do_catalogo_cep_telefone_e_uf():
    prod = produto()
    assert prod.validar_valor("cep", "39999412") == "39999-412"
    assert prod.validar_valor("cep", "pode ser esse do zap") is None
    assert prod.validar_valor("telefone_contrato", "39999-412") is None            # um CEP não é telefone
    assert prod.validar_valor("telefone_contrato", "(33) 99000-0302") == "(33) 99000-0302"
    assert prod.validar_valor("telefone_contrato", "pode ser esse mesmo do zap") is None
    assert prod.validar_valor("uf", "Minas gerais") == "MG" and prod.validar_valor("uf", "Vale Sereno") is None
    assert "não confunda com telefone" in prod.guia_do_extrator() and "grave a sigla MG" in prod.guia_do_extrator()
    assert cdados.PEDIR["telefone"]


def _enriquecer(encontrado=True):
    async def enriquecer(fatos):
        if not fatos.get("cep"):
            return []
        situacao = {"chave": "_busca_cep", "valor": {"cep": fatos["cep"], "encontrado": encontrado}, "fonte": "sistema"}
        if not encontrado:
            return [situacao]
        trecho = "(pelo CEP)"
        return [{"chave": "endereco", "valor": "Rua Exemplo dos Cedros", "trecho": trecho, "fonte": "sistema"},
                {"chave": "bairro", "valor": "Jardim Exemplo", "trecho": trecho, "fonte": "sistema"},
                {"chave": "cidade", "valor": "Ribeirão do Exemplo", "trecho": trecho, "fonte": "sistema"},
                {"chave": "uf", "valor": "MG", "trecho": trecho, "fonte": "sistema"}, situacao]
    return enriquecer


async def test_cep_sem_rotulo_respondendo_ao_pedido_vira_fato_e_a_busca_roda_no_mesmo_turno():
    historico = [{"autor": "você", "texto": "Agora me informe o seu CEP, por favor."}]
    modelo = ModeloFalso({"extrator": extrai([("telefone_contrato", "39999-412", "39999-412")]),
                          "etapa": resposta("Obrigada! Qual é o número da sua casa?")})
    saida = await turno.processar(modelo, entrada(["39999-412"], etapa="contratos", historico=historico,
                                                  enriquecer=_enriquecer()))
    assert saida.fatos_depois["cep"] == "39999-412" and "telefone_contrato" not in saida.fatos_depois
    assert saida.fatos_depois["endereco"] == "Rua Exemplo dos Cedros"
    conteudo = conteudos(modelo)[0]
    assert "BUSCA DE CEP (sistema): CEP 39999-412 encontrado: Rua Exemplo dos Cedros, Jardim Exemplo, Ribeirão do Exemplo/MG" in conteudo
    assert "endereco=Rua Exemplo dos Cedros (pelo CEP)" in conteudo
    # A situação da busca não vira fato; só ficam as marcas de controle: o endereço que veio do CEP (para o CEP corrigido
    # não apagar o que o lead digitou) e o CEP já buscado (revisão rodada 2, [21]).
    assert "_busca_cep" not in saida.fatos_depois
    assert [f["chave"] for f in saida.fatos_novos if f["chave"].startswith("_")] == [turno.MARCA_ENDERECO_DO_CEP,
                                                                                       turno.MARCA_CEP_CONSULTADO]
    assert saida.fatos_depois[turno.MARCA_ENDERECO_DO_CEP] == {"endereco": "Rua Exemplo dos Cedros", "bairro": "Jardim Exemplo",
                                                              "cidade": "Ribeirão do Exemplo", "uf": "MG"}


async def test_cep_nao_encontrado_vai_dito_e_endereco_digitado_e_do_lead():
    modelo = ModeloFalso({"extrator": extrai([("cep", "39115990", "39115-990"),
                                              ("endereco", "Rua Exemplo do Cascalho", "Rua Exemplo do Cascalho")]),
                          "etapa": resposta("Anotei o endereço. Qual é o número da casa?")})
    saida = await turno.processar(modelo, entrada(["39115-990 é Rua Exemplo do Cascalho"], etapa="contratos",
                                                  enriquecer=_enriquecer(encontrado=False)))
    conteudo = conteudos(modelo)[0]
    assert "BUSCA DE CEP (sistema): CEP 39115-990 não encontrado" in conteudo
    assert "endereco=Rua Exemplo do Cascalho (dito pelo lead)" in conteudo
    assert saida.estado_lead is None


async def test_formato_do_buscar_cep_diz_que_a_busca_e_automatica():
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Certo!")})
    await turno.processar(modelo, entrada(["oi"], etapa="contratos"))
    sistema = modelo.pedidos[1]["sistema"]
    assert "a busca do endereço pelo CEP é automática" in sistema and "Nunca diga que está buscando" in sistema
    assert "peça só os campos que ele citou" in sistema                       # [6]
    assert "aceite o CPF" in sistema and "em qualquer formato" in sistema       # [0]


async def test_endereco_inventado_e_corrigido_sem_pausar():
    inventada = resposta("Buscamos nos Correios e o seu endereço é: Rua Santa Luzia, Bairro Centro, São João do Paraíso, MG.")
    modelo = ModeloFalso({"extrator": extrai(), "etapa": [inventada, dict(inventada)]})
    saida = await turno.processar(modelo, entrada(["39999-412"], etapa="contratos", fatos={"cep": "39999-412"}))
    assert "Não invente o endereço ('Rua Santa Luzia')" in conteudos(modelo)[1]
    assert saida.estado_lead is None and saida.mensagens                         # trava leve: nunca pausa
    assert any(e["tipo"] == "trava_endereco_sem_fonte" for e in saida.eventos)


def test_endereco_dos_fatos_ou_do_lead_nao_e_inventado():
    assert catalogo.endereco_sem_fonte(["Seu endereço é Rua Santa Luzia, 10"], {"endereco": "Rua Santa Luzia"}, []) is None
    assert catalogo.endereco_sem_fonte(["Endereço: Rua Exemplo do Cascalho, 77"], {}, ["é Rua Exemplo do Cascalho 77"]) is None
    assert catalogo.endereco_sem_fonte(["Me informe o nome da sua rua ou avenida."], {}, []) is None


# ---------------------------------------------------------------------------- [7] UF por extenso
@pytest.mark.parametrize("valor, sigla", [("Minas gerais", "MG"), ("MG", "MG"), ("mg.", "MG"), ("Minas Gerais/MG", "MG"),
                                          ("Estado de São Paulo", "SP"), ("rio grande do sul", "RS"),
                                          ("Mato Grosso do Sul", "MS"), ("XX", None), ("Vale Sereno", None)])
def test_normalizar_uf(valor, sigla):
    assert cdados.normalizar_uf(valor) == sigla


def test_contrato_aceita_uf_por_extenso_e_continua_pedindo_uf_invalida():
    base = {"nome_completo": "Josimar dos Santos", "cpf": "529.982.247-25", "endereco": "Rua das Paineiras",
            "numero_casa": "418", "bairro": "Vila Esperança", "cidade": "Vale Sereno", "cep": "39999-100"}
    dados, erros = cdados.validar_dados(cdados.dados_dos_fatos({**base, "uf": "Minas gerais"}))
    assert erros == [] and dados["estado"] == "MG"
    _, erros = cdados.validar_dados(cdados.dados_dos_fatos({**base, "uf": "XX"}))
    assert [e.campo for e in erros] == ["estado"]
    assert aa.validar_valor("uf", "minas gerais") == "MG"


async def test_cep_corrige_uf_que_nao_e_estado(monkeypatch):
    from app.ferramentas import cep as ferramenta_cep
    from app.pipeline import Atendimento

    async def consultar(cep, **_):
        return ferramenta_cep.Endereco(cep="39999100", valido=True, mensagem="ok", tipo="rua", logradouro="Rua X",
                                       bairro="Centro", cidade="Vale Sereno", uf="MG", origem="teste")
    monkeypatch.setattr(ferramenta_cep, "consultar", consultar)
    novos = await Atendimento._enriquecer_por_cep({"cep": "39999-100", "endereco": "Rua das Paineiras", "bairro": "Vila",
                                                   "cidade": "Cidade do Lead", "uf": "XX"})
    fatos = {f["chave"]: f["valor"] for f in novos}
    assert fatos["uf"] == "MG" and "cidade" not in fatos                # a cidade dita pelo lead não é trocada
    assert fatos["_busca_cep"]["encontrado"] is True


# ---------------------------------------------------------------------------- [9] [14] [17] "garantir" ligado a resultado
@pytest.mark.parametrize("frase", [
    "Vamos incluir essa sequela no pedido para garantir o direito dele.",
    "Vamos cuidar de tudo para garantir seu direito com segurança e tranquilidade.",
    "Estamos aqui para garantir que você receba tudo que tem direito.",
    "Garanto que você vai ter o benefício.",
])
def test_garantir_resultado_e_barrado(frase):
    assert travas.trecho_de_promessa(frase), frase
    assert catalogo.conferir([{"tipo": "texto", "texto": frase}]), frase


@pytest.mark.parametrize("frase", [
    "Vou te mostrar um resumo para garantir que está tudo certinho.",
    "Isso é para garantir que o contrato seja gerado corretamente.",
    "O que posso garantir é que cuidamos do pedido.",
    "Não podemos garantir o benefício, isso depende da perícia.",
    "É para garantir que você receba o link certinho.",
    "Para garantir que o seu pedido de benefício seja bem feito, preciso de alguns dados.",
])
def test_garantir_servico_continua_livre(frase):
    assert travas.trecho_de_promessa(frase) is None, frase
    assert catalogo.conferir([{"tipo": "texto", "texto": frase}]) == [], frase


# ---------------------------------------------------------------------------- [27] "100% online" não é honorário
@pytest.mark.parametrize("etapa", ["sdr", "closer"])
def test_cem_por_cento_online_nao_cai_em_honorarios(etapa):
    honorarios = "30% sobre os valores atrasados, só se o benefício sair."
    for frase in ("Nosso atendimento é 100% online pelo WhatsApp.", "Fazemos tudo de forma 100% online."):
        codigos = [r.codigo for r in travas.conferir([{"tipo": "texto", "texto": frase}], etapa=etapa,
                                                     honorarios=honorarios, midias={}, faltam=())]
        assert "honorarios" not in codigos, (frase, codigos)
    codigos = [r.codigo for r in travas.conferir([{"tipo": "texto", "texto": "Cobramos 100% dos atrasados."}], etapa="closer",
                                                 honorarios=honorarios, midias={}, faltam=())]
    assert {"honorarios", "promessa"} <= set(codigos)


# ---------------------------------------------------------------------------- [15] [18] [21] datas
@pytest.mark.parametrize("trecho", ["ate hj incha e doi", "hoje anda de bengala", "recebo ele ate hoje"])
def test_ate_hoje_nao_vira_data_do_acidente(trecho):
    extracao = extrator.conferir({"fatos": [{"chave": "acidente_mes", "valor": 3, "trecho": trecho},
                                            {"chave": "acidente_ano", "valor": 2026, "trecho": trecho}]}, [trecho], {})
    assert extracao.fatos == [] and {r["motivo"] for r in extracao.rejeitados} <= {"data_sem_prova", "mes_sem_prova"}


@pytest.mark.parametrize("trecho, ano", [("foi em março de 2024", 2024), ("faz uns 2 anos", 2024), ("em 2019", 2019),
                                         ("uns 12 anos", 2014), ("2015", 2015)])
def test_data_dita_continua_valendo(trecho, ano):
    extracao = extrator.conferir({"fatos": [{"chave": "acidente_ano", "valor": ano, "trecho": trecho}]}, [trecho], {})
    assert [f.valor for f in extracao.fatos] == [ano], trecho


def test_guias_dizem_que_ate_hoje_e_afastamento_nao_sao_data_nem_demissao():
    guia = produto().guia_do_extrator()
    assert "\"Até hoje dói/incha\"" in guia and "nunca demissão" in guia
    assert "NÃO são data de nada" in extrator.REGRAS_GERAIS
    assert "{contexto}" in extrator.REGRAS_GERAIS and extrator.sistema_do_extrator(produto())   # o .format continua certo
    assert "é tempo de auxílio-doença" in extrator.GUIA_AUXILIO_ACIDENTE
    assert {"seguro_desemprego", "contribuiu_por_conta_propria"} <= set(
        produto().esquema_extrator()["properties"]["fatos"]["items"]["properties"]["chave"]["enum"])


def test_calculadora_avisa_data_faltando_mes_atual_e_conflito():
    assert contexto.fatos_da_calculadora({"demissao_ano": 2019}, AGORA) == {
        "data do acidente (calculado pelo sistema)": "não informada pelo lead (sem ela não há conta)"}
    atual = contexto.fatos_da_calculadora({"acidente_mes": 3, "acidente_ano": 2026}, AGORA)
    assert atual["data do acidente igual ao mês atual (calculado pelo sistema)"] == "confirme com o lead"
    conflito = contexto.fatos_da_calculadora({"demissao_meses_antes_do_acidente": 8, "demissao_mes": 7, "demissao_ano": 2023,
                                              "acidente_mes": 3, "acidente_ano": 2026}, AGORA)
    assert "o lead disse 8 meses" in conflito["conflito nas datas (calculado pelo sistema)"]


async def test_conteudo_diz_que_a_data_do_acidente_nao_foi_informada():
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Entendi. E em que ano foi o acidente?")})
    await turno.processar(modelo, entrada(["caí da escada, até hj dói"]))
    assert "Data do acidente: o lead ainda não informou (nunca use a data de hoje" in conteudos(modelo)[0]


# ---------------------------------------------------------------------------- [24] cobertura do período de graça
def test_calculadora_diz_que_estava_coberto_com_seguro():
    fatos = {"demissao_mes": 1, "demissao_ano": 2023, "acidente_mes": 5, "acidente_ano": 2024, "seguro_desemprego": "sim"}
    assert contexto.fatos_da_calculadora(fatos, AGORA)[contexto.CHAVE_COBERTURA] == "coberta na data do acidente"
    sem = contexto.fatos_da_calculadora({**fatos, "seguro_desemprego": "nao", "contribuiu_por_conta_propria": "nao"}, AGORA)
    assert sem[contexto.CHAVE_COBERTURA] == "não coberta pelas datas"
    falta = contexto.fatos_da_calculadora({k: v for k, v in fatos.items() if k != "seguro_desemprego"}, AGORA)
    assert "seguro-desemprego" in falta[contexto.CHAVE_COBERTURA]
    assert not any(c.isdigit() for c in falta[contexto.CHAVE_COBERTURA])         # nunca cita o prazo em meses


async def test_desqualificar_quem_estava_coberto_ganha_uma_correcao_neutra_e_nao_pausa():
    fatos = {"demissao_mes": 1, "demissao_ano": 2023, "acidente_mes": 5, "acidente_ano": 2024, "seguro_desemprego": "sim"}
    desq = resposta("Infelizmente não vai dar para seguir com o seu caso.", transferir="desqualificado")
    modelo = ModeloFalso({"extrator": extrai(), "etapa": [desq, dict(desq)]})
    saida = await turno.processar(modelo, entrada(["não paguei"], etapa="periododegraca", fatos=fatos))
    assert "estava coberta na data do acidente: só desqualifique por outro motivo" in conteudos(modelo)[1]
    # Leva 1 (B4): sem motivo comprovado por fato do lead (e coberto pela conta), o portão segura a desqualificação.
    assert saida.etapa_depois == "periododegraca" and saida.estado_lead is None
    assert any(e["tipo"] == "troca_barrada_faltam_fatos" for e in saida.eventos)
    # Com um motivo dito pelo lead, a 2ª resposta decide, como antes (nunca pausa).
    modelo = ModeloFalso({"extrator": extrai(), "etapa": [desq, dict(desq)]})
    saida = await turno.processar(modelo, entrada(["não paguei"], etapa="periododegraca",
                                                  fatos={**fatos, "tem_advogado_no_caso": "sim"}))
    assert saida.etapa_depois == "desqualificado" and saida.estado_lead is None


# ---------------------------------------------------------------------------- [1] [8] [26] pergunta exigida antes de passar
def _prod_com_ano():
    return produto(sdr={"perguntar_antes_de_transferir": {"closer": ["acidente_ano|acidente_quando_incerto"]}})


def test_fatos_exigidos_entram_no_extrator_so_com_a_config():
    enum = lambda p: p.esquema_extrator()["properties"]["fatos"]["items"]["properties"]["chave"]["enum"]  # noqa: E731
    sem_periodo = produto(("sdr", "closer", "contratos"),
                          sdr={"perguntar_antes_de_transferir": {"closer": ["acidente_ano|acidente_quando_incerto", "sequela"]}})
    assert {"acidente_ano", "acidente_quando_incerto", "sequela"} <= set(enum(sem_periodo))
    # Leva 1 (B4): o portão de fatos põe sequela, aposentadoria e advogado no extrator sempre que o Closer existe;
    # só com o portão desligado o extrator fica sem eles.
    assert "sequela" in enum(produto(("sdr", "closer", "contratos")))
    sem_portao = catalogo.carregar({"catalogo": {"papeis": {p: {} for p in ("sdr", "closer", "contratos")},
                                                 "portao_de_fatos": False}})
    assert "sequela" not in enum(sem_portao)
    assert sem_periodo.validar_valor("acidente_quando_incerto", "sim") == "sim"
    assert sem_periodo.validar_valor("sequela", "talvez") is None


async def test_transferir_sem_o_ano_pede_a_pergunta_uma_vez():
    modelo = ModeloFalso({"extrator": extrai(),
                          "etapa": [resposta(TROCAS["closer"], transferir="closer"),
                                    resposta("Entendi! E em que ano foi o acidente, mais ou menos?")]})
    saida = await turno.processar(modelo, entrada(["era registrado sim"], prod=_prod_com_ano()))
    assert "Antes de passar o lead adiante, faça a pergunta do roteiro sobre: quando foi o acidente" in conteudos(modelo)[1]
    assert saida.etapa_depois == "sdr" and saida.fatos_depois[turno.MARCA_PERGUNTOU] == ["sdr>closer"]
    assert "_perguntou" not in conteudos(modelo)[1].split("DADOS JÁ INFORMADOS")[-1].split("\n")[0]


async def test_com_a_marca_ou_com_o_nao_lembro_transfere_direto():
    for fatos in ({turno.MARCA_PERGUNTOU: ["sdr>closer"]}, {"acidente_quando_incerto": "sim"}, {"acidente_ano": 2014}):
        modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta(TROCAS["closer"], transferir="closer")})
        saida = await turno.processar(modelo, entrada(["não lembro o ano"], prod=_prod_com_ano(), fatos=dict(fatos)))
        assert saida.etapa_depois == "closer" and len(conteudos(modelo)) == 1, fatos


async def test_insistir_na_transferencia_passa_e_nao_pausa():
    passa = resposta(TROCAS["closer"], transferir="closer")
    modelo = ModeloFalso({"extrator": extrai(), "etapa": [passa, dict(passa)]})
    saida = await turno.processar(modelo, entrada(["era registrado sim"], prod=_prod_com_ano()))
    assert saida.etapa_depois == "closer" and saida.estado_lead is None
    assert any(e["tipo"] == "trava_perguntar_antes_de_transferir" for e in saida.eventos)


# ---------------------------------------------------------------------------- [22] [25] frase de outro destino; [16] opt-in
async def test_frase_de_outro_destino_ganha_correcao_e_nao_pausa():
    errada = resposta(TROCAS["periododegraca"], transferir="desqualificado")
    certa = resposta(TROCAS["desqualificado"], transferir="desqualificado")
    modelo = ModeloFalso({"extrator": extrai(), "etapa": [errada, certa]})
    motivo = {"vinculo_na_data": "nunca_trabalhou"}            # leva 1 (B4): desqualificar exige um motivo comprovado
    saida = await turno.processar(modelo, entrada(["sou mei"], fatos=motivo))
    assert "mas escreveu a frase de passagem de \"periododegraca\"" in conteudos(modelo)[1]
    assert saida.etapa_depois == "desqualificado" and saida.mensagens[0]["texto"].startswith("Analisei")
    modelo = ModeloFalso({"extrator": extrai(), "etapa": [errada, dict(errada)]})
    saida = await turno.processar(modelo, entrada(["sou mei"], fatos=motivo))
    assert saida.estado_lead is None and any(e["tipo"] == "trava_frase_de_outro_destino" for e in saida.eventos)


def test_frase_com_ordem_trocada_conta_como_dita():
    assert catalogo.tem_frase(["Nós podemos te ajudar no seu caso. Maravilha!"], TROCAS["closer"])
    assert not catalogo.tem_frase(["Ótimo! Com esses documentos, podemos ajudar."], TROCAS["closer"])


async def test_frase_obrigatoria_so_com_a_opcao_no_destino():
    parafrase = resposta("Analisei o seu caso e não dá para seguir.", transferir="desqualificado")
    aposentado = extrai([("aposentado", "sim", "sou aposentado")])     # leva 1 (B4): o motivo vem do lead
    modelo = ModeloFalso({"extrator": aposentado, "etapa": parafrase})
    saida = await turno.processar(modelo, entrada(["sou aposentado"]))
    assert len(conteudos(modelo)) == 1 and saida.etapa_depois == "desqualificado"
    prod = produto(desqualificado={"exigir_frase_de_troca": True})
    modelo = ModeloFalso({"extrator": aposentado, "etapa": [parafrase, resposta(TROCAS["desqualificado"], transferir="desqualificado")]})
    saida = await turno.processar(modelo, entrada(["sou aposentado"], prod=prod))
    assert f"envie exatamente esta frase: \"{TROCAS['desqualificado']}\"" in conteudos(modelo)[1]
    assert saida.etapa_depois == "desqualificado"


# ---------------------------------------------------------------------------- [19] passagem com pergunta em aberto
async def test_passagem_sem_frase_e_com_pergunta_espera_um_turno():
    pergunta = resposta("Você já trabalhou de carteira assinada alguma vez?", transferir="periododegraca")
    modelo = ModeloFalso({"extrator": extrai(), "etapa": pergunta})
    saida = await turno.processar(modelo, entrada(["sou autônomo"]))
    assert saida.etapa_depois == "sdr" and saida.fatos_depois[turno.MARCA_ADIADA] == "periododegraca"
    assert saida.eventos[-1]["tipo"] == "transferencia_adiada_pergunta_aberta"
    # No turno seguinte, a mesma situação passa (uma vez seguida só) e a marca é limpa.
    modelo = ModeloFalso({"extrator": extrai(), "etapa": dict(pergunta)})
    saida = await turno.processar(modelo, entrada(["nunca"], fatos={turno.MARCA_ADIADA: "periododegraca"}))
    assert saida.etapa_depois == "periododegraca" and saida.fatos_depois[turno.MARCA_ADIADA] == ""


async def test_passagem_com_a_frase_nao_espera():
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta(TROCAS["periododegraca"], transferir="periododegraca")})
    saida = await turno.processar(modelo, entrada(["sou autônomo"]))
    assert saida.etapa_depois == "periododegraca"


async def test_closer_para_contratos_com_pergunta_do_destino_nao_espera():
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Ótimo! Qual é o seu nome completo?", transferir="contratos")})
    saida = await turno.processar(modelo, entrada(["pode seguir"], etapa="closer"))
    assert saida.etapa_depois == "contratos"


# ---------------------------------------------------------------------------- [5] [10] [11] formato
async def test_formato_pede_para_nao_repetir_e_retomar_a_pergunta_pendente():
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Certo!")})
    await turno.processar(modelo, entrada(["oi"]))
    sistema = modelo.pedidos[1]["sistema"]
    assert "confira na CONVERSA ATÉ AQUI e nos DADOS JÁ INFORMADOS se o lead já respondeu" in sistema
    assert "retome a pergunta pendente da etapa" in sistema


# ---------------------------------------------------------------------------- [20] [23] formatador
@pytest.mark.parametrize("bruto, limpo", [
    ("auxílio-doença por 6 meses —, esse benefício", "auxílio-doença por 6 meses, esse benefício"),
    ("auxílio-doença —, esse benefício", "auxílio-doença, esse benefício"),
    ("não tendo recebido auxílio-doença , , esse benefício", "não tendo recebido auxílio-doença, esse benefício"),
    ("Pelo que você me contou — acidente", "Pelo que você me contou, acidente"),
    ("Me conta — com calma — como foi?", "Me conta, com calma, como foi?"),
])
def test_travessao_antes_de_pontuacao_nao_vira_virgula_solta(bruto, limpo):
    assert formatador.limpar(bruto) == limpo


def test_formatador_nao_junta_linhas():
    assert formatador.limpar("Nome: Ana\nCPF: 1 ,\nOk") == "Nome: Ana\nCPF: 1,\nOk"


async def test_travas_de_repeticao_nao_pausam_por_padrao(monkeypatch):
    """Em produção (PAUSAR_EM_REPETICAO = False) a IA que insiste no CPF errado é corrigida e o turno segue, sem pausar."""
    monkeypatch.setattr(turno, "PAUSAR_EM_REPETICAO", False)
    errada = resposta("O último grupo do CPF deve ter dois dígitos. Pode me enviar o CPF correto?")
    modelo = ModeloFalso({"extrator": extrai(), "etapa": [errada, dict(errada)]})
    saida = await turno.processar(modelo, entrada([f"como eu falei, {CPF_DO_CASO}"], etapa="contratos",
                                                  fatos={"cpf": "057.830.862-23"}))
    assert saida.estado_lead is None and saida.motivo_estado != "pedido_repetido"
    assert len(conteudos(modelo)) == 2          # a CORRIJA continua: houve a 2ª tentativa


async def test_uf_da_naturalidade_da_lugar_a_do_cep(monkeypatch):
    """Reteste BPC 26/11: "nasceu em Montes Claros/MG" gravou uf=MG e o contrato saiu "São Paulo/MG"."""
    from app.ferramentas import cep as ferramenta_cep
    from app.pipeline import Atendimento

    async def consultar(cep, **_):
        return ferramenta_cep.Endereco(cep="01310100", valido=True, mensagem="ok", tipo="rua", logradouro="Avenida Paulista",
                                       bairro="Bela Vista", cidade="São Paulo", uf="SP", origem="teste")
    monkeypatch.setattr(ferramenta_cep, "consultar", consultar)
    fatos = {f["chave"]: f["valor"] for f in await Atendimento._enriquecer_por_cep({"cep": "01310-100", "uf": "MG"})}
    assert fatos["cidade"] == "São Paulo" and fatos["uf"] == "SP"


async def test_uf_com_cidade_do_lead_nao_e_trocada(monkeypatch):
    from app.ferramentas import cep as ferramenta_cep
    from app.pipeline import Atendimento

    async def consultar(cep, **_):
        return ferramenta_cep.Endereco(cep="01310100", valido=True, mensagem="ok", tipo="rua", logradouro="Avenida Paulista",
                                       bairro="Bela Vista", cidade="São Paulo", uf="SP", origem="teste")
    monkeypatch.setattr(ferramenta_cep, "consultar", consultar)
    fatos = {f["chave"]: f["valor"] for f in await Atendimento._enriquecer_por_cep(
        {"cep": "01310-100", "cidade": "Osasco", "uf": "SP"})}
    assert "uf" not in fatos
