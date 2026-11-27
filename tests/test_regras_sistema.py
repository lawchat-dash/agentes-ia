"""Regras do sistema editáveis por produto (aba "Regras do sistema" do super admin) e honorários do produto.

- sem regras_sistema, o sistema é idêntico ao de antes (vazio, chave ausente ou texto em branco = o padrão do código);
- cada bloco editado troca só o seu texto, no lugar certo; passagem_<destino> só entra onde o papel passa para ele;
- notificacao_<sinal> troca a descrição do sinal no guia do extrator;
- a conferência recusa bloco desconhecido, o FORMATO base (só leitura) e o texto sem placeholder obrigatório;
- a ativação copia config_modelo.regras_sistema e honorarios_texto do produto para a config do agente;
- a prévia usa a montagem real e deixa as variáveis {{ }} à mostra;
- honorários (transcrição do áudio) entram só em Closer, Contratos e Assinatura, com as variáveis trocadas.
"""

import pytest

from app.cerebro import catalogo, sinais, turno
from app.gestao import produtos as gprodutos
from app.modelo import ModeloFalso
from tests.test_motor_correcoes_rodada2 import TROCAS, entrada, extrai, produto, resposta

PAPEIS = ("sdr", "periododegraca", "closer", "contratos", "assinatura", "desqualificado")


def sistema(papel, regras_sistema=None, honorarios_texto=None, familia=None, conhecimento="OBJ: caro → explique",
            variaveis=None):
    prod = produto()
    papeis = prod.config["catalogo"]["papeis"]
    ferramentas = prod.ferramentas_do_papel(papel)
    destinos = gprodutos.DESTINOS[papel]                    # os destinos que a ativação grava para cada papel
    return catalogo.montar_sistema(
        prompt="Roteiro. https://x.com/a.mp3", nome_agente="Júlia", escritorio="Escritório Teste",
        conhecimento_texto=conhecimento, regras="Regra do escritório.", destinos=destinos, acoes=ferramentas["acoes"],
        fatos_sistema={"nome": "Jo"}, notificacoes=("analise_humana",), papel=papel, ferramentas=ferramentas,
        papeis=papeis, honorarios="30%", familia=familia, regras_sistema=regras_sistema,
        honorarios_texto=honorarios_texto, variaveis=variaveis)


# ---------------------------------------------------------------------------- padrão = comportamento de antes
@pytest.mark.parametrize("papel", PAPEIS)
@pytest.mark.parametrize("familia", ["auxilio_acidente", "bpc_infantil"])
def test_sem_regras_sistema_o_sistema_nao_muda(papel, familia):
    base = sistema(papel, None, familia=familia)
    em_branco = {b["chave"]: "  " for b in catalogo.blocos_do_sistema()}
    assert sistema(papel, {}, familia=familia) == base
    assert sistema(papel, em_branco, familia=familia) == base
    # Os blocos padrão são os textos de sempre do código.
    assert catalogo.REGRAS_CONVERSA in base and catalogo.FORMATO_NOTIFICACAO in base
    assert catalogo.texto_do_bloco("objecoes") == catalogo.REGRA_OBJECOES
    assert catalogo.texto_do_bloco("ferramenta_zapsign") == catalogo.FORMATO_FERRAMENTAS["zapsign"]


def test_guia_do_extrator_padrao_igual_ao_de_antes():
    prod = produto()
    padrao = prod.para_o_papel("contratos").guia_do_extrator()
    assert "- quer_videochamada: pede chamada de vídeo" in padrao
    assert "- foto_contrato (só na fase do contrato): manda foto" in padrao
    assert sinais.guia_do_extrator("x") == sinais.guia_do_extrator("x", {})
    assert "em conversa (x). NÃO é" in sinais.guia_do_extrator("x")


# ---------------------------------------------------------------------------- override
def test_bloco_editado_troca_so_o_seu_texto():
    editado = sistema("sdr", {"conversa": "# CONVERSA NOVA\n- Seja breve.", "nao_inventar": "Nunca invente nada."})
    assert "# CONVERSA NOVA\n- Seja breve." in editado and "Nunca invente nada." in editado
    assert catalogo.REGRAS_CONVERSA not in editado and catalogo.REGRAS_NAO_INVENTAR not in editado
    assert "# FORMATO DA RESPOSTA (sistema)" in editado          # o resto continua


def test_placeholders_continuam_trocados_no_texto_editado():
    editado = sistema("closer", {"entrada": "Você chegou aqui com: {frase}. Não repita."})
    assert f"Você chegou aqui com: {TROCAS['closer']}. Não repita." in editado
    assinatura = sistema("assinatura", {"papel_assinatura": "Assinatura nova ({dado_errado})."})
    assert "Assinatura nova (aí vale a regra do zapsign)." in assinatura
    passagem = sistema("sdr", {"passagem": "Para onde passar:\n{destinos}\nFim."})
    assert 'Para onde passar:\n  · Período de Graça = "periododegraca"' in passagem and "{destinos}" not in passagem


def test_bloco_de_papel_e_familia_so_no_seu_lugar():
    rs = {"papel_contratos": "Coleta nova.", "familia_bpc_infantil": "BPC novo.", "midia": "Mídia nova."}
    assert "Coleta nova." in sistema("contratos", rs) and "Coleta nova." not in sistema("closer", rs)
    assert "BPC novo." in sistema("sdr", rs, familia="bpc_infantil")
    assert "BPC novo." not in sistema("sdr", rs, familia="bpc_idoso")
    assert catalogo.REGRA_BPC in sistema("sdr", rs, familia="bpc_idoso")
    assert "Mídia nova." in sistema("sdr", rs)


def test_ferramentas_e_aviso_editados_so_onde_o_papel_aciona():
    rs = {"ferramenta_zapsign": "  · zapsign: gera o contrato quando o lead confirmar.",
          "ferramenta_buscar_cep": "  · buscar_cep: busca nova.", "notificacao_analise_humana": "- \"notificacao\": aviso novo."}
    contratos = sistema("contratos", rs)
    assert "  · zapsign: gera o contrato quando o lead confirmar.\n" in contratos and "· buscar_cep: busca nova.\n" in contratos
    assert catalogo.FORMATO_FERRAMENTAS["zapsign"] not in contratos
    assert "zapsign: gera o contrato" not in sistema("sdr", rs)
    assert '- "notificacao": aviso novo.\n' in sistema("sdr", rs) and catalogo.FORMATO_NOTIFICACAO not in sistema("sdr", rs)


def test_descricao_da_passagem_entra_so_em_quem_passa_para_o_destino():
    rs = {"passagem_closer": "Quando o lead tiver sequela e qualidade de segurado.",
          "passagem_desqualificado": "Quando não atender aos requisitos."}
    sdr = sistema("sdr", rs)
    assert 'Closer = "closer": "Maravilha! Nós podemos te ajudar no seu caso."\n    Quando passar para Closer: ' \
           "Quando o lead tiver sequela e qualidade de segurado." in sdr
    assert "Quando passar para Desqualificado: Quando não atender aos requisitos." in sdr
    # Assinatura não passa para ninguém; o padrão (sem texto) não acrescenta nada.
    assert "Quando passar para" not in sistema("assinatura", rs)
    assert "Quando passar para" not in sistema("sdr")
    assert catalogo.texto_do_bloco("passagem_closer") == ""


def test_descricao_do_sinal_editada_vai_para_o_extrator():
    prod = catalogo.carregar({"catalogo": {"papeis": {"sdr": {}}, "regras_sistema": {
        "notificacao_quer_videochamada": "pede vídeo ou Meet, nada além disso."}}})
    guia = prod.para_o_papel("sdr").guia_do_extrator()
    assert "- quer_videochamada: pede vídeo ou Meet, nada além disso." in guia
    assert "- quer_audio: pede áudio ou voz" in guia


async def test_turno_usa_as_regras_do_sistema_da_config():
    prod = produto()
    prod.config["catalogo"]["regras_sistema"] = {"conversa": "CONVERSA DO PRODUTO X.", "objecoes": "OBJEÇÕES DO PRODUTO X:"}
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Qual é o seu nome?")})
    dados = entrada(["oi"], prod=prod, conhecimento={"objecoes": [{"objecao": "caro", "resposta": "explique"}]})
    await turno.processar(modelo, dados)
    enviado = next(p["sistema"] for p in modelo.pedidos if p["papel"] == "etapa")
    assert "CONVERSA DO PRODUTO X." in enviado and catalogo.REGRAS_CONVERSA not in enviado
    assert "OBJEÇÕES DO PRODUTO X:\n- Se disser \"caro\"" in enviado


# ---------------------------------------------------------------------------- conferência ao salvar
def test_conferencia_recusa_placeholder_tirado_bloco_desconhecido_e_formato():
    for chave, texto, trecho in (("entrada", "Começo sem a frase.", "{frase}"),
                                 ("papel_assinatura", "Sem o dado errado.", "{dado_errado}"),
                                 ("passagem", "Passe quando der.", "{destinos}")):
        limpo, erros = catalogo.limpar_regras_sistema({chave: texto})
        assert not limpo and erros and trecho in erros[0]
    assert catalogo.limpar_regras_sistema({"inventado": "x"})[1]
    assert catalogo.limpar_regras_sistema({"formato": "outro JSON"})[1]
    assert catalogo.limpar_regras_sistema({"conversa": 3})[1]
    assert catalogo.limpar_regras_sistema(["x"])[1]


def test_conferencia_tira_vazio_e_igual_ao_padrao():
    limpo, erros = catalogo.limpar_regras_sistema({
        "conversa": "", "nao_inventar": catalogo.REGRAS_NAO_INVENTAR, "formato": catalogo.FORMATO.strip(),
        "entrada": "  Nova com {frase}.  ", "passagem_closer": "Quando qualificar."})
    assert not erros and limpo == {"entrada": "  Nova com {frase}.", "passagem_closer": "Quando qualificar."}


def test_lista_de_blocos():
    blocos = catalogo.blocos_do_sistema()
    chaves = [b["chave"] for b in blocos]
    assert len(chaves) == len(set(chaves))
    for chave in ("conversa", "nao_inventar", "entrada", "desqualificar", "calculadora", "papel_contratos",
                  "papel_assinatura", "papel_desqualificado", "familia_bpc_infantil", "midia", "passagem",
                  "ferramenta_zapsign", "ferramenta_buscar_cep", "notificacao_analise_humana", "formato",
                  "passagem_closer", "passagem_periododegraca", "passagem_contratos", "passagem_desqualificado",
                  "passagem_sdr", "passagem_assinatura", "notificacao_outro_beneficio", "notificacao_quer_videochamada"):
        assert chave in chaves, chave
    por_chave = {b["chave"]: b for b in blocos}
    assert por_chave["formato"]["editavel"] is False
    assert por_chave["entrada"]["obrigatorios"] == ["{frase}"]
    assert all(b["quando_entra"] and b["titulo"] for b in blocos)
    assert por_chave["passagem_closer"]["padrao"] == ""


# ---------------------------------------------------------------------------- ativação e prévia
def test_ativacao_copia_regras_sistema_e_honorarios_do_produto():
    catalogo_produto = {"id": "x", "slug": "auxilio-acidente", "config_modelo": {
        "temperature": 0.5, "honorarios_texto": "Você paga {{HONORARIOS QTD SALARIOS}} salários.",
        "regras_sistema": {"conversa": "Conversa nova.", "entrada": "sem o placeholder"}}}
    config = gprodutos._config_do_agente(gprodutos.Ativar(), catalogo_produto, {}, False)
    assert config["catalogo"]["regras_sistema"] == {"conversa": "Conversa nova."}      # o inválido cai no padrão
    assert config["conhecimento"]["honorarios"] == "Você paga {{HONORARIOS QTD SALARIOS}} salários."
    proprio = gprodutos._config_do_agente(gprodutos.Ativar(honorarios_texto="Texto do cliente."), catalogo_produto, {}, False)
    assert proprio["conhecimento"]["honorarios"] == "Texto do cliente."
    vazio = gprodutos._config_do_agente(gprodutos.Ativar(), {}, {}, False)
    assert vazio["catalogo"]["regras_sistema"] == {} and "honorarios" not in vazio["conhecimento"]


def test_previa_usa_a_montagem_real_com_variaveis_a_mostra():
    papeis = {p: {"mensagem_troca": TROCAS.get(p), "destinos": [d for d in PAPEIS if d != p]} for p in PAPEIS}
    config = {"catalogo": {"slug": "auxilio-acidente", "papeis": papeis, "regras": "Regra {{NOME ESCRITORIO}}.",
                           "regras_sistema": {"conversa": "Conversa da prévia."}}, "funcoes": {"contrato_zapsign": True}}
    conhecimento = {"faq": [{"pergunta": "Quanto custa?", "resposta": "Nada antes."}],
                    "objecoes": [{"objecao": "golpe", "resposta": "Somos reais."}], "dados_escritorio": "OAB {{OAB}}",
                    "honorarios": "Recebe {{HONORARIOS QTD SALARIOS}} salários."}
    previa = catalogo.previa_do_sistema(config, "closer", "Você é {{NOME AGENTE}}. Apresente.", conhecimento)
    ordem = ["Você é {{NOME AGENTE}}. Apresente.", "# REGRAS GERAIS DO ESCRITÓRIO\nRegra {{NOME ESCRITORIO}}.",
             catalogo.TITULO_HONORARIOS_TEXTO + "\nRecebe {{HONORARIOS QTD SALARIOS}} salários.",
             "# USO DA BASE", "DADOS DO ESCRITÓRIO", "OAB {{OAB}}", "PERGUNTAS FREQUENTES", catalogo.REGRA_OBJECOES,
             "Conversa da prévia.", "# FORMATO DA RESPOSTA (sistema)", "# FATOS DO SISTEMA"]
    posicoes = [previa.index(t) for t in ordem]
    assert posicoes == sorted(posicoes)
    assert 'Contratos = "contratos"' in previa and 'SDR = "sdr"' not in previa        # só para a frente
    assert "· zapsign:" not in previa                                                   # o Closer não gera contrato
    # Igual ao sistema do turno para o mesmo papel (a não ser pelas variáveis e fatos).
    sdr = catalogo.previa_do_sistema(config, "sdr", "Roteiro.", {})
    assert "Conversa da prévia." in sdr and catalogo.TITULO_HONORARIOS_TEXTO not in sdr


# ---------------------------------------------------------------------------- honorários (transcrição do áudio)
@pytest.mark.parametrize("papel", PAPEIS)
def test_honorarios_do_produto_nas_etapas_que_falam_de_valor(papel):
    texto = "Você só paga se aprovar: {{HONORARIOS QTD SALARIOS}} salários, em {{HONORARIOS VEZES SEM JUROS}}x."
    valores = {"HONORARIOS QTD SALARIOS": "3", "HONORARIOS VEZES SEM JUROS": "10"}
    com = sistema(papel, honorarios_texto=texto, variaveis=valores)
    assert (catalogo.TITULO_HONORARIOS_TEXTO + "\nVocê só paga se aprovar: 3 salários, em 10x." in com) == \
        (papel in catalogo.PAPEIS_COM_HONORARIOS_TEXTO)
    assert sistema(papel, honorarios_texto="", variaveis=valores) == sistema(papel, variaveis=valores)
    if papel not in catalogo.PAPEIS_COM_HONORARIOS_TEXTO:
        assert com == sistema(papel, variaveis=valores)


async def test_turno_le_honorarios_da_config_do_agente():
    prod = produto()
    prod.config["conhecimento"] = {"honorarios": "O escritório recebe {{HONORARIOS QTD SALARIOS}} salários."}
    prod.config["variables"] = {"HONORARIOS QTD SALARIOS": "3"}
    # SDR também: quem pergunta o preço antes da hora recebe os números (no teste, sem eles a lead desistiu).
    for etapa, deve in (("closer", True), ("sdr", True), ("desqualificado", False)):
        modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Certo.")})
        await turno.processar(modelo, entrada(["quanto custa?"], etapa=etapa, prod=prod))
        enviado = next(p["sistema"] for p in modelo.pedidos if p["papel"] == "etapa")
        assert ("O escritório recebe 3 salários." in enviado) == deve


# ---------------------------------------------------------------------------- salvar (PATCH) e aba Conhecimento
class _PoolFalso:
    def __init__(self, salvo):
        self.salvo = salvo

    async def fetchval(self, *_args):
        return self.salvo


async def test_patch_junta_config_modelo_e_confere_regras():
    from fastapi import HTTPException

    pool = _PoolFalso('{"temperature": 0.5, "faq_items": [1], "regras_sistema": {"conversa": "Velha."}}')
    juntado = await gprodutos._config_modelo_juntado(pool, "id", {"regras_sistema": {"midia": "Mídia nova."}})
    assert juntado == {"temperature": 0.5, "faq_items": [1], "regras_sistema": {"midia": "Mídia nova."}}
    so_temperatura = await gprodutos._config_modelo_juntado(pool, "id", {"temperature": 0.2})
    assert so_temperatura["regras_sistema"] == {"conversa": "Velha."} and so_temperatura["faq_items"] == [1]
    with pytest.raises(HTTPException) as erro:
        await gprodutos._config_modelo_juntado(pool, "id", {"regras_sistema": {"passagem": "sem destinos"}})
    assert erro.value.status_code == 400 and "{destinos}" in erro.value.detail


def test_aba_conhecimento_mantem_os_honorarios():
    from app.gestao.rotas import _limpar_conhecimento

    assert _limpar_conhecimento({"faq": [], "honorarios": " Paga só se ganhar. "})["honorarios"] == "Paga só se ganhar."
    assert "honorarios" not in _limpar_conhecimento({"faq": []})


def test_previa_mostra_onde_entra_a_midia():
    from app.cerebro import catalogo
    texto = catalogo.mostrar_midias_na_previa("Mensagem 1:\n\n[[audio:Video Inicial]]\n\n[[video: como_assinar]]")
    assert "[[" not in texto
    assert "‹audio: Video Inicial — aqui entra o link" in texto and "‹video: como_assinar —" in texto
