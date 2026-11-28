"""Regras fixas do motor (docs/REGRAS_DO_MOTOR_E_CAMPOS.md, seção 1): o campo do cliente tem só o roteiro do escritório;
formato, passagem de etapa, ferramentas, contas e anti-invenção entram no sistema pelo motor, por papel e ferramenta,
iguais para todo escritório. Sem API: ModeloFalso.

- cada papel recebe as camadas certas (calculadora só em SDR e Período de Graça, coleta só em Contratos, zapsign só
  com a ação, desqualificação só com o destino) mesmo com um roteiro de uma linha, sem nada técnico;
- o sistema é idêntico entre dois turnos do mesmo papel (cache do provedor);
- variáveis {{X}} trocadas pelo motor (grafias variadas), linha sem valor sai inteira e vira evento uma vez;
- a mensagem de entrada de cada destino chega ao modelo pela regra de passagem; HONORÁRIOS entram no catálogo;
- passagem: desqualificado volta ao SDR uma vez; frase de troca inserida como último balão; chip "→ @Análise da equipe";
- linha DADOS DO CONTRATO QUE FALTAM (sistema); travas "boas chances" e "garanto"; "Tool `qualificado`" = closer.
"""

import re

import pytest

from app.cerebro import catalogo, travas, turno
from app.modelo import ModeloFalso
from tests.test_motor_correcoes_rodada2 import TROCAS, conteudos, entrada, extrai, produto, resposta

ROTEIRO = "Faça as perguntas do escritório."          # um campo de cliente sem nenhuma regra técnica
VARIAVEL = re.compile(r"\{\{\s*[^{}\s][^{}]*\}\}")


def sistema_do_papel(papel, prod=None, roteiro=ROTEIRO, honorarios=None, config_extra=None):
    prod = prod or produto()
    papeis = (prod.config.get("catalogo") or {}).get("papeis") or {}
    ferramentas = prod.ferramentas_do_papel(papel)
    destinos = [d for d in papeis[papel]["destinos"] if not (papel == "contratos" and d == "assinatura")]
    return catalogo.montar_sistema(
        prompt=roteiro, nome_agente="Júlia", escritorio="Escritório Teste", conhecimento_texto="", regras=None,
        destinos=destinos, acoes=ferramentas["acoes"], fatos_sistema={}, notificacoes=("analise_humana",),
        papel=papel, ferramentas=ferramentas, papeis=papeis, honorarios=honorarios)


# ---------------------------------------------------------------------------- camadas por papel
@pytest.mark.parametrize("papel", ["sdr", "periododegraca", "closer", "contratos", "assinatura", "desqualificado"])
def test_cada_papel_recebe_as_camadas_certas_sem_o_cliente_escrever(papel):
    sistema = sistema_do_papel(papel)
    # Universais: conduta e anti-invenção, formato e passagem, em todo papel.
    for trecho in ("# REGRAS DO ATENDIMENTO (sistema)", "O que você nunca inventa", "# FORMATO DA RESPOSTA (sistema)",
                   'Passagem de etapa ("transferir_para")', "Não prometa resultado"):
        assert trecho in sistema, (papel, trecho)
    assert ("Datas e contas" in sistema) == (papel in ("sdr", "periododegraca"))           # calculadora
    assert ("Coleta dos dados do contrato" in sistema) == (papel == "contratos")
    assert ("Etapa de assinatura" in sistema) == (papel == "assinatura")
    assert ("\nEncerramento\n" in sistema) == (papel == "desqualificado")
    assert ("· zapsign:" in sistema) == (papel in ("contratos", "assinatura"))              # ação do mapa do papel
    assert ("· buscar_cep:" in sistema) == (papel == "contratos")
    assert ("\nDesqualificação\n" in sistema) == (papel != "desqualificado")                 # destino "desqualificado"
    assert ("Começo desta etapa" in sistema) == bool(TROCAS.get(papel))                      # papel com mensagem de entrada
    assert '"notificacao": preencha "analise_humana"' in sistema
    # O roteiro do cliente continua no começo, e as regras vêm depois dele.
    assert sistema.startswith(ROTEIRO) and sistema.index("# REGRAS DO ATENDIMENTO") < sistema.index("# FORMATO DA RESPOSTA")


def test_zapsign_some_sem_a_funcao_de_contrato():
    prod = catalogo.carregar({"catalogo": {"papeis": {"contratos": {"destinos": []}}}, "funcoes": {}})
    assert "· zapsign:" not in sistema_do_papel("contratos", prod) and "· buscar_cep:" in sistema_do_papel("contratos", prod)


def test_regras_novas_de_ferramenta_e_aviso_a_equipe():
    cep, zap = catalogo.FORMATO_FERRAMENTAS["buscar_cep"], catalogo.FORMATO_FERRAMENTAS["zapsign"]
    assert "pergunte só número e" in cep and "Não pergunte de novo rua, bairro, cidade ou estado" in cep
    assert "uma vez só" in zap and "não diga em quanto tempo o link chega" in zap
    assert "Análise da equipe" in catalogo.FORMATO_NOTIFICACAO and "sem prazo de retorno" in catalogo.FORMATO_NOTIFICACAO


# ---------------------------------------------------------------------------- passagem: a frase vem do motor
def test_a_mensagem_de_entrada_de_cada_destino_esta_na_regra_de_passagem():
    for papel in ("sdr", "periododegraca", "closer"):
        sistema = sistema_do_papel(papel)
        for destino, frase in TROCAS.items():
            if destino != papel:
                assert f'= "{destino}": "{frase}"' in sistema, (papel, destino)
    assert '= "contratos": (sem mensagem de entrada)' in sistema_do_papel("closer")
    sem_destino = catalogo.formato([], [], ())
    assert "Esta etapa não passa o lead para outra" in sem_destino


def test_honorarios_entram_no_catalogo():
    sistema = sistema_do_papel("closer", honorarios="30% dos atrasados, só no êxito.")
    assert "# HONORÁRIOS DO ESCRITÓRIO" in sistema and "30% dos atrasados, só no êxito." in sistema
    assert "# HONORÁRIOS DO ESCRITÓRIO" not in sistema_do_papel("closer")


async def test_sistema_identico_entre_dois_turnos_do_mesmo_papel():
    sistemas = []
    for novas in (["oi"], ["caí da moto em 2020"]):
        modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Em que mês foi?")})
        await turno.processar(modelo, entrada(novas, etapa="closer"))
        sistemas.append(next(p["sistema"] for p in modelo.pedidos if p["papel"] == "etapa"))
    assert sistemas[0] == sistemas[1] and "# REGRAS DO ATENDIMENTO (sistema)" in sistemas[0]


# ---------------------------------------------------------------------------- variáveis
@pytest.mark.parametrize("escrita", ["{{NOME AGENTE}}", "{{ nome agente }}", "{{Nome_Agente}}", "{{nome do agente}}"])
def test_variavel_aceita_espaco_caixa_e_acento(escrita):
    texto, faltam = catalogo.preencher_variaveis(f"Olá, sou {escrita}.", {"NOME AGENTE": "Ana"})
    assert texto == "Olá, sou Ana." and faltam == []


def test_variavel_sem_valor_tira_a_linha_inteira_e_o_apelido_do_google():
    valores = catalogo.valores_das_variaveis("Ana", "Sousa", None, {"variables": {"Link Avaliação Google": "https://g.page/x"}})
    texto, faltam = catalogo.preencher_variaveis(
        "Linha 1\nAvalie: {{Google Meu Negócio}}\nHonorários: {{HONORARIOS}}\nCNPJ: {{ CNPJ }}\nFim", valores)
    assert texto == "Linha 1\nAvalie: https://g.page/x\nFim" and faltam == ["HONORARIOS", "CNPJ"]
    # O que o motor sabe vale mais que config.variables.
    assert catalogo.valores_das_variaveis("Ana", "Sousa", "10%", {"variables": {"NOME AGENTE": "Outra"}})["NOME AGENTE"] == "Ana"
    # "{{ }}" sem nome (texto do FORMATO) não é variável.
    assert catalogo.preencher_variaveis("campos {{ }}", {})[0] == "campos {{ }}"


async def test_motor_troca_as_variaveis_e_registra_a_que_falta_uma_vez():
    roteiro = ("Você é {{ nome agente }}, do {{NOME ESCRITORIO}}.\nHonorários: {{HONORARIOS}}\n"
               "Link: {{Google Meu Negócio}}\nCNPJ: {{CNPJ}}\nPergunte o nome.")
    prod = produto(sdr={"boas_vindas": "Oi! Aqui é a {{NOME AGENTE}}."})
    prod.config["variables"] = {"LINK AVALIACAO GOOGLE": "https://g.page/r/abc/review"}
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Qual é o seu nome?")})
    dados = entrada(["oi"], prod=prod, honorarios="5 salários do benefício.")
    dados.instrucoes = {"sdr": roteiro}
    saida = await turno.processar(modelo, dados)
    sistema = next(p["sistema"] for p in modelo.pedidos if p["papel"] == "etapa")
    assert sistema.startswith("Você é Júlia, do Escritório Teste.\nHonorários: 5 salários do benefício.\n"
                              "Link: https://g.page/r/abc/review\nPergunte o nome.")
    assert not VARIAVEL.search(sistema) and "CNPJ:" not in sistema  # a linha sem valor saiu                     # nenhum {{X}} chega ao modelo
    assert 'Mensagem de boas-vindas: "Oi! Aqui é a Júlia."' in conteudos(modelo)[0]
    eventos = [e for e in saida.eventos if e["tipo"] == "variavel_sem_valor"]
    assert [e["detalhe"]["variavel"] for e in eventos] == ["CNPJ"]
    marca = saida.fatos_depois[turno.MARCA_VARIAVEIS_SEM_VALOR]
    modelo2 = ModeloFalso({"extrator": extrai(), "etapa": resposta("Qual é o seu nome?")})
    dados2 = entrada(["oi"], prod=prod, honorarios="5 salários do benefício.",
                     fatos={turno.MARCA_VARIAVEIS_SEM_VALOR: marca})
    dados2.instrucoes = {"sdr": roteiro}
    saida2 = await turno.processar(modelo2, dados2)
    assert not [e for e in saida2.eventos if e["tipo"] == "variavel_sem_valor"]       # uma vez por conversa


# ---------------------------------------------------------------------------- passagem (turno)
async def test_frase_inserida_vai_como_ultimo_balao_depois_do_texto_de_saida():
    saida_pg = "Pelas datas que você me passou, quando o acidente aconteceu você ainda estava protegido pelo INSS."
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta(saida_pg, transferir="closer")})
    saida = await turno.processar(modelo, entrada(["recebi seguro sim"], etapa="periododegraca"))
    assert [m["texto"] for m in saida.mensagens] == [saida_pg.rstrip("."), TROCAS["closer"]] or \
        [m["texto"] for m in saida.mensagens][-1] == TROCAS["closer"]
    assert saida.etapa_depois == "closer"


async def test_desqualificado_volta_ao_sdr_uma_vez_so():
    roteiro = "Algo mudou → \"Qual informação seria diferente agora?\" → @Agente SDR"
    prod = produto(desqualificado={"destinos": []})
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Obrigada por avisar!", transferir="sdr")})
    dados = entrada(["na verdade eu era registrado"], etapa="desqualificado", prod=prod)
    dados.instrucoes = {"desqualificado": roteiro}
    saida = await turno.processar(modelo, dados)
    assert saida.etapa_depois == "sdr" and saida.fatos_depois[turno.MARCA_VOLTOU_AO_SDR] is True
    # Segunda vez na mesma conversa: o destino é ignorado e registrado.
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Obrigada por avisar!", transferir="sdr")})
    dados = entrada(["mudou de novo"], etapa="desqualificado", prod=prod, fatos={turno.MARCA_VOLTOU_AO_SDR: True})
    dados.instrucoes = {"desqualificado": roteiro}
    saida = await turno.processar(modelo, dados)
    assert saida.etapa_depois == "desqualificado"
    assert "destino_para_tras_ignorado" in [e["tipo"] for e in saida.eventos]


async def test_chip_analise_da_equipe_liga_o_aviso_no_papel_sem_notificacao():
    prod = produto()
    assert prod.ferramentas_do_papel("desqualificado")["notificacao"] is False               # mapa padrão: desligado
    modelo = ModeloFalso({"extrator": extrai(), "etapa": {**resposta("Vou pedir para a equipe olhar."),
                                                          "notificacao": "analise_humana"}})
    dados = entrada(["não sei"], etapa="desqualificado", prod=prod)
    dados.instrucoes = {"desqualificado": "Se travar → @Análise da equipe"}
    saida = await turno.processar(modelo, dados)
    pedido = next(p for p in modelo.pedidos if p["papel"] == "etapa")
    assert "notificacao" in pedido["esquema"]["properties"]
    assert saida.estado_lead == "pausado" and saida.motivo_estado == "sinal:analise_humana"
    assert catalogo.pede_analise_da_equipe("→ @Analise da equipe") and not catalogo.pede_analise_da_equipe("equipe")


# ---------------------------------------------------------------------------- linha do turno no Contratos
async def test_contratos_recebe_a_linha_dos_dados_que_faltam():
    modelo = ModeloFalso({"extrator": extrai([("nome_completo", "Ana Souza", "Ana Souza")]),
                          "etapa": resposta("Qual é o seu CPF?")})
    await turno.processar(modelo, entrada(["Ana Souza"], etapa="contratos"))
    conteudo = conteudos(modelo)[0]
    assert "DADOS DO CONTRATO QUE FALTAM (sistema): CPF, rua, número, bairro, cidade, estado, CEP." in conteudo
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Qual é o seu CEP?")})
    await turno.processar(modelo, entrada(["oi"], etapa="closer"))
    assert "DADOS DO CONTRATO QUE FALTAM" not in conteudos(modelo)[0]


# ---------------------------------------------------------------------------- travas e apelidos
@pytest.mark.parametrize("frase, trecho", [
    ("Pelo que você contou, o seu caso tem boas chances.", "boas chances"),
    ("Eu garanto que vai dar certo.", "garanto"),
])
def test_trava_pega_avaliacao_de_chances_e_garanto(frase, trecho):
    assert travas.trecho_de_promessa(frase) == trecho


def test_nao_garanto_e_aviso_honesto():
    assert travas.trecho_de_promessa("Eu não garanto resultado: quem avalia é a equipe.") is None


def test_tool_qualificado_passa_para_o_closer():
    destinos, _ = catalogo.ferramentas_do_prompt("Qualificou: acionar a Tool `qualificado`. Senão, acionar tool `desqualificado`.")
    assert destinos == ["closer", "desqualificado"]


# ---------------------------------------------------------------------------- revisão enxuto x corrigido (25/11/2026)
def test_assinatura_so_cita_o_zapsign_quando_o_papel_pode_aciona_lo():
    com = catalogo.regras_do_motor("assinatura", {"acoes": ["zapsign"]}, [])
    sem = catalogo.regras_do_motor("assinatura", {"acoes": []}, [])
    assert "aí vale a regra do zapsign" in com and "zapsign" not in sem and "roteiro para dado errado" in sem
    assert "{dado_errado}" not in com + sem


def test_ja_assinei_segue_o_roteiro_sem_dizer_que_conferiu_nem_prazo():
    regra = catalogo.regras_do_motor("assinatura", {"acoes": []}, [])
    assert "vai conferir e já retorna" not in regra
    assert "responda pelo roteiro" in regra and "Não diga que conferiu" in regra and "não cite prazo" in regra


def test_calculadora_perto_do_limite_com_pedido_de_analise_vai_para_a_equipe():
    regra = catalogo.REGRA_CALCULADORA
    # As duas linhas que a calculadora escreve (contexto.cobertura_na_data_do_acidente) têm caminho próprio.
    assert '"perto do limite: peça análise humana" → "Análise da equipe"' in regra
    assert '"perto do limite (falta ...)" → pergunte uma vez o mês que falta' in regra


def test_passagem_agradece_quando_o_lead_ja_mandou_o_que_a_entrada_pede():
    assert "já mandou o que a mensagem de entrada pede" in catalogo.REGRA_PASSAGEM
