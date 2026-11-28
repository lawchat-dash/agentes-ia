"""Famílias de produto no motor do catálogo (auxilio_acidente, bpc_infantil, bpc_idoso, bpc_geral, previdenciario).

Mesmo funil; cada família tem os seus fatos de qualificação (sempre no extrator, mesmo com o portão desligado), os
seus motivos de desqualificar, o seu bloco nas regras do motor e, no BPC infantil, a qualificação completa do contrato.
Tudo com fakes (ModeloFalso); nenhum dado é de lead real.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import conhecimento
from app.cerebro import catalogo, extrator, resposta_curta, turno
from app.contrato import dados as cdados
from app.modelo import ErroModelo, ModeloFalso

AGORA = datetime(2026, 11, 26, 10, 0, tzinfo=timezone(timedelta(hours=-3)))
PAPEIS = ("sdr", "closer", "contratos", "assinatura", "desqualificado")
FRASES = {"closer": "Maravilha! Nós podemos te ajudar no seu caso.",
          "contratos": "Perfeito! Agora vou pegar os seus dados para o contrato.",
          "desqualificado": "Analisei com atenção o que você nos contou e você não se enquadra nos critérios."}
CONTRATO = {"cpf", "bairro", "profissao", "cidade", "nome_completo", "cep"}


def produto(slug="auxilio-acidente", **opcoes):
    cfg = {p: {"destinos": [d for d in PAPEIS if d != p and d != "assinatura"], "mensagem_troca": FRASES.get(p)}
           for p in PAPEIS}
    return catalogo.carregar({"catalogo": {"papeis": cfg, "slug": slug, "portao_de_fatos": False},
                              "funcoes": {"contrato_zapsign": True}, **opcoes})


def enum(prod):
    return set(prod.esquema_extrator()["properties"]["fatos"]["items"]["properties"]["chave"]["enum"])


def extrai(*fatos):
    return {"fatos": [{"chave": c, "valor": v, "trecho": t} for c, v, t in fatos], "sinais": [], "intencoes": {}}


def resposta(*textos, transferir=""):
    return {"mensagens": [{"texto": t} for t in textos], "transferir_para": transferir, "ferramenta": ""}


def entrada(novas, etapa="sdr", prod=None, fatos=None, historico=None):
    return turno.Entrada(escritorio="Escritório Teste", agente="Júlia", etapa=etapa, novas=list(novas),
                         produto=prod or produto(), instrucoes={etapa: "Siga o roteiro do papel."}, agora=AGORA,
                         fatos=dict(fatos or {}), modelo_extrator="gpt-4.1-mini",
                         historico=list(historico or [{"autor": "você", "texto": "Como posso te ajudar?"}]))


def conteudos(modelo):
    return [p["conteudo"] for p in modelo.pedidos if p["papel"] == "etapa"]


def tipos(saida):
    return [e["tipo"] for e in saida.eventos]


# ---------------------------------------------------------------------------- família pelo slug
@pytest.mark.parametrize("slug, familia", [
    ("auxilio-acidente", "auxilio_acidente"), ("auxilio-acidente-midia", "auxilio_acidente"),
    ("bpc-loas-autismo", "bpc_infantil"), ("bpc-loas-autismo-v2", "bpc_infantil"), ("bpc-loas-infantil", "bpc_infantil"),
    ("bpc-loas-idoso", "bpc_idoso"), ("bpc-loas-geral", "bpc_geral"), ("bpc-loas-geral-idoso", "bpc_geral"),
    ("bpc-deficiente", "bpc_geral"), ("bpc", "bpc_geral"), ("aposentadoria-especial", "previdenciario"), ("", "previdenciario"),
])
def test_familia_pelo_comeco_do_slug(slug, familia):
    assert catalogo.familia_do_produto({"catalogo": {"slug": slug}}) == familia


# ---------------------------------------------------------------------------- 1a/1b: esquema por família e papel
def test_portao_desligado_aa_continua_com_aposentado_e_advogado_e_sem_contrato_no_closer():
    closer = produto().para_o_papel("closer")
    assert {"aposentado", "tem_advogado_no_caso"} <= enum(closer)
    assert not CONTRATO & enum(closer) and "nome" in enum(closer)
    assert catalogo.faltam_para_entrar(closer.config, "closer", {}) == []          # o portão continua desligado
    guia = closer.guia_do_extrator()
    assert "explicitamente, com as próprias palavras" in guia and "ÚLTIMA pergunta" in guia
    assert "Campos possíveis (dados do contrato" not in guia


def test_contratos_e_assinatura_coletam_o_contrato():
    for papel in ("contratos", "assinatura"):
        assert CONTRATO <= enum(produto().para_o_papel(papel))
    # SDR com "@ZapSign" no roteiro também coleta.
    assert "cpf" in enum(produto().para_o_papel("sdr", "Quando confirmar, acione @ZapSign."))
    # Sem papel (chamada direta, como antes): todos os campos.
    assert CONTRATO <= enum(produto())


def test_bpc_tem_os_fatos_da_familia_no_extrator_com_o_portao_desligado():
    sdr = produto("bpc-loas-autismo").para_o_papel("sdr")
    assert {"beneficiario_relacao", "beneficiario_idade", "condicao_saude", "recebe_beneficio", "pessoas_na_casa",
            "renda_casa", "tem_advogado_no_caso"} <= enum(sdr)
    assert not CONTRATO & enum(sdr) and "sequela" not in enum(sdr)
    guia = sdr.guia_do_extrator()
    assert "condicao_saude:" in guia and "Nunca vai para bairro, profissão" in guia
    assert sdr.validar_valor("beneficiario_idade", "70") == 70 and sdr.validar_valor("beneficiario_idade", "setenta") is None
    assert sdr.validar_valor("recebe_beneficio", "BPC") == "bpc" and sdr.validar_valor("recebe_beneficio", "talvez") is None
    assert sdr.validar_valor("beneficiario_relacao", "filho") == "filho"
    assert sdr.validar_valor("condicao_saude", "autismo nível 2") == "autismo nível 2"


def test_bpc_desqualifica_por_beneficio_e_advogado_nunca_por_renda():
    bpc = {"catalogo": {"slug": "bpc-loas-idoso"}}
    for valor in ("bpc", "aposentadoria", "pensao_morte"):
        assert catalogo.motivo_de_desqualificar(bpc, {"recebe_beneficio": valor}) == ("recebe_beneficio", valor)
    assert catalogo.motivo_de_desqualificar(bpc, {"recebe_beneficio": "bolsa_familia"}) is None
    assert catalogo.motivo_de_desqualificar(bpc, {"renda_casa": "6500", "pessoas_na_casa": 2}) is None
    assert catalogo.motivo_de_desqualificar(bpc, {"tem_advogado_no_caso": "sim"}) == ("tem_advogado_no_caso", "sim")


def test_nao_curto_a_pergunta_do_beneficio_vira_nenhum_so_no_bpc():
    historico = [{"autor": "você", "texto": "Hoje ele recebe algum benefício, como aposentadoria ou pensão?"}]
    bpc = produto("bpc-loas-autismo").para_o_papel("sdr")
    extracao = extrator.pela_pergunta(extrator.Extracao(), historico, ["Não"], {}, bpc)
    assert [(f.chave, f.valor) for f in extracao.fatos if f.chave == "recebe_beneficio"] == [("recebe_beneficio", "nenhum")]
    # "Sim" não diz qual benefício: fica para o extrator de IA.
    assert not [f for f in extrator.pela_pergunta(extrator.Extracao(), historico, ["sim"], {}, bpc).fatos
                if f.chave == "recebe_beneficio"]
    # O fato que desqualifica, vindo do extrator de IA, cai se o assunto não apareceu.
    assert resposta_curta.fora_do_assunto("recebe_beneficio", "sim", [{"autor": "você", "texto": "Qual o seu bairro?"}],
                                          ["sim"], extrator.normalizar)


async def test_turno_manda_ao_extrator_o_esquema_do_papel_e_o_teto_de_tokens():
    prod = produto("bpc-loas-autismo")
    modelo = ModeloFalso({"extrator": extrai(("condicao_saude", "autismo", "meu filho tem autismo")),
                          "etapa": resposta("Entendi. Quantos anos ele tem?")})
    saida = await turno.processar(modelo, entrada(["meu filho tem autismo"], prod=prod))
    pedido = next(p for p in modelo.pedidos if p["papel"] == "extrator")
    chaves = set(pedido["esquema"]["properties"]["fatos"]["items"]["properties"]["chave"]["enum"])
    assert "condicao_saude" in chaves and not CONTRATO & chaves
    assert pedido["max_tokens"] == extrator.MAX_TOKENS_EXTRATOR
    assert saida.fatos_depois["condicao_saude"] == "autismo"
    assert extrator.max_tokens_do_extrator("gpt-6-luna") == extrator.MAX_TOKENS_EXTRATOR_RACIOCINIO


# ---------------------------------------------------------------------------- 1c: extrator que falha não pausa
@pytest.mark.parametrize("motivo", ["saida_cortada", "saida_invalida"])
async def test_extrator_cortado_nao_pausa_o_lead_e_o_turno_segue(motivo):
    def quebra(_s, _c):
        raise ErroModelo(motivo)

    modelo = ModeloFalso({"extrator": quebra, "etapa": resposta("Entendi. Quantos anos ele tem?")})
    saida = await turno.processar(modelo, entrada(["é pro meu filho autista"], prod=produto("bpc-loas-autismo")))
    assert saida.situacao == "respondido" and saida.estado_lead is None and "extrator_falhou" in tipos(saida)
    assert [m["texto"] for m in saida.mensagens if m["tipo"] == "texto"]


async def test_extrator_com_provedor_fora_do_ar_segue_o_caminho_de_sempre():
    def fora(_s, _c):
        raise ErroModelo("provedor_fora_do_ar", "503")

    modelo = ModeloFalso({"extrator": fora, "etapa": resposta("não deveria sair")})
    saida = await turno.processar(modelo, entrada(["oi"]))
    assert (saida.situacao, saida.motivo) == ("erro", "extrator:provedor_fora_do_ar")


# ---------------------------------------------------------------------------- 1d: Closer desqualifica com informação nova
async def test_closer_confirma_uma_vez_o_motivo_novo_e_depois_desqualifica():
    modelo = ModeloFalso({"extrator": extrai(("aposentado", "sim", "eu já sou aposentado")),
                          "etapa": resposta("Só pra eu não errar: você já é aposentado hoje?")})
    saida = await turno.processar(modelo, entrada(["eu já sou aposentado"], etapa="closer"))
    assert "Só pra eu não errar" in conteudos(modelo)[0] and "NÃO desqualifica" in conteudos(modelo)[0]
    assert saida.fatos_depois[turno.MARCA_DESQ_A_CONFIRMAR] == "aposentado" and saida.etapa_depois == "closer"
    # Turno seguinte: o lead confirma; a IA recebe a orientação de desqualificar e o lead passa.
    historico = [{"autor": "lead", "texto": "eu já sou aposentado"},
                 {"autor": "você", "texto": "Só pra eu não errar: você já é aposentado hoje?"}]
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta(FRASES["desqualificado"], transferir="desqualificado")})
    saida = await turno.processar(modelo, entrada(["sim"], etapa="closer", historico=historico,
                                                  fatos={"aposentado": "sim", turno.MARCA_DESQ_A_CONFIRMAR: "aposentado"}))
    assert "Se ele confirmou, marque transferir_para = \"desqualificado\"" in conteudos(modelo)[0]
    assert saida.etapa_depois == "desqualificado" and saida.fatos_depois[turno.MARCA_DESQ_A_CONFIRMAR] == ""


async def test_closer_lead_corrigiu_nao_pede_desqualificar():
    historico = [{"autor": "lead", "texto": "tenho advogado"},
                 {"autor": "você", "texto": "Só pra eu não errar: você já tem um advogado cuidando deste mesmo caso?"}]
    modelo = ModeloFalso({"extrator": extrai(("tem_advogado_no_caso", "nao", "não, era de outro processo")),
                          "etapa": resposta("Entendi! Então seguimos.")})
    saida = await turno.processar(modelo, entrada(["não, era de outro processo"], etapa="closer", historico=historico,
                                                  fatos={"tem_advogado_no_caso": "sim",
                                                         turno.MARCA_DESQ_A_CONFIRMAR: "tem_advogado_no_caso"}))
    assert "transferir_para = \"desqualificado\"" not in conteudos(modelo)[0] and saida.etapa_depois == "closer"


async def test_orientacao_so_no_closer_e_o_escritorio_pode_desligar():
    fato = extrai(("aposentado", "sim", "eu já sou aposentado"))
    modelo = ModeloFalso({"extrator": fato, "etapa": resposta("Certo. E como foi o acidente?")})
    await turno.processar(modelo, entrada(["eu já sou aposentado"], etapa="sdr"))
    assert "Só pra eu não errar" not in conteudos(modelo)[0]
    modelo = ModeloFalso({"extrator": fato, "etapa": resposta("Certo.")})
    desligado = produto(confirmar_desqualificacao_no_closer=False)
    await turno.processar(modelo, entrada(["eu já sou aposentado"], etapa="closer", prod=desligado))
    assert "Só pra eu não errar" not in conteudos(modelo)[0]


async def test_closer_do_bpc_orienta_pelo_beneficio():
    prod = produto("bpc-loas-idoso")
    historico = [{"autor": "você", "texto": "Hoje sua mãe recebe algum benefício do INSS?"}]
    modelo = ModeloFalso({"extrator": extrai(("recebe_beneficio", "pensao_morte", "ela recebe pensão do meu pai")),
                          "etapa": resposta("Só pra eu não errar: ela recebe pensão por morte?")})
    await turno.processar(modelo, entrada(["ela recebe pensão do meu pai"], etapa="closer", prod=prod,
                                          historico=historico))
    assert "já recebe um benefício" in conteudos(modelo)[0]


# ---------------------------------------------------------------------------- 2: contrato do BPC infantil
def test_campos_novos_do_contrato_e_variaveis_do_modelo():
    fatos = {"nome_completo": "Ana Paula Souza", "cpf": "52998224725", "cep": "01310100", "endereco": "Avenida Paulista",
             "numero_casa": "1000", "bairro": "Bela Vista", "cidade": "São Paulo", "uf": "SP",
             "nome_menor": "Lucas Souza", "nacionalidade_menor": "brasileira", "naturalidade_menor": "campinas",
             "filiacao_menor": "ana paula souza e carlos souza", "naturalidade": "recife",
             "filiacao": "maria souza e joão souza", "nacionalidade": "brasileira"}
    dados, erros = cdados.validar_dados(cdados.dados_dos_fatos(fatos), "5511988887777")
    assert erros == []
    assert dados["naturalidade"] == "Recife" and dados["filiacao"] == "Maria Souza e João Souza"
    assert dados["naturalidadedomenor"] == "Campinas" and dados["cidade"] == "São Paulo"
    variaveis = dict(cdados.montar_variaveis(dados, cdados.MAPEAMENTO_PADRAO, AGORA))
    assert variaveis["Naturalidade da mae"] == "Recife" and variaveis["filiação da mae"] == "Maria Souza e João Souza"
    assert variaveis["Nacionalidade do(a) menor"] == "brasileira" and variaveis["Naturalidade do(a) menor"] == "Campinas"
    assert variaveis["filiação do(a) menor"] == "Ana Paula Souza e Carlos Souza"
    assert len(cdados.MAPEAMENTO_PADRAO) == 22
    nota = cdados.nota_dos_dados(dados)
    assert "Filiação do menor" in nota and "Naturalidade: Recife" in nota


def test_campos_novos_so_obrigatorios_quando_o_modelo_pede():
    base = {"nome_completo": "Ana Paula Souza", "cpf": "52998224725", "cep": "01310100", "endereco": "Rua A",
            "numero_casa": "10", "bairro": "Centro", "cidade": "Recife", "uf": "PE"}
    assert cdados.validar_dados(cdados.dados_dos_fatos(base))[1] == []
    _, erros = cdados.validar_dados(cdados.dados_dos_fatos(base),
                                    obrigatorios=cdados.OBRIGATORIOS_PADRAO + ("naturalidadedomenor",))
    assert [e.campo for e in erros] == ["naturalidadedomenor"]


def test_guia_do_contrato_diz_quem_assina_e_de_onde_vem_a_cidade():
    contratos = produto("bpc-loas-autismo").para_o_papel("contratos")
    assert {"nacionalidade_menor", "naturalidade_menor", "filiacao_menor", "naturalidade", "filiacao",
            "nacionalidade"} <= enum(contratos)
    guia = contratos.guia_do_extrator()
    assert "nunca um nome tirado de uma filiação" in guia
    assert "só do resultado da busca do CEP ou do endereço que o lead digitou; nunca a naturalidade" in guia
    assert "quem ASSINA é o responsável" in guia
    assert "quem ASSINA é o responsável" not in produto().para_o_papel("contratos").guia_do_extrator()


# ---------------------------------------------------------------------------- 3: trava aceita o número do lead
@pytest.mark.parametrize("dito", ["6500", "6.500", "R$ 6.500,00", "6,500", "6 mil e 500", "seis mil e quinhentos",
                                  "6,5 mil", "a renda é uns 6500 por mês"])
def test_valor_dito_pelo_lead_nao_e_inventado(dito):
    assert conhecimento.fato_sem_fonte(["Só pra eu não errar: a renda da casa é de R$ 6.500, certo?"], ["roteiro"],
                                       [dito]) is None


def test_valor_que_ninguem_disse_continua_barrado():
    assert conhecimento.fato_sem_fonte(["Dá R$ 1.625 por pessoa, certo?"], ["roteiro"], ["6500", "4 pessoas"]) == "R$ 1.625"


# ---------------------------------------------------------------------------- 4: regras do motor da família
def test_bloco_do_bpc_nas_regras_do_motor_e_nada_novo_no_auxilio_acidente():
    for familia in ("bpc_infantil", "bpc_idoso", "bpc_geral"):
        regras = catalogo.regras_do_motor("sdr", {}, ["closer"], familia=familia)
        assert "per capita" in regras and "relatório médico pelo chat" in regras and "não de quem cuida" in regras
    # Desde 28/11 o Auxílio-Acidente tem bloco próprio (lições dos tickets): só ele muda, sem o bloco do BPC.
    aux = catalogo.regras_do_motor("sdr", {}, ["closer"], familia="auxilio_acidente")
    assert "Auxílio-Acidente\n- O benefício é de quem sofreu o acidente" in aux and "per capita" not in aux
    assert aux.replace("\n\n" + catalogo.REGRA_AUXILIO_ACIDENTE, "") == catalogo.regras_do_motor("sdr", {}, ["closer"])


async def test_turno_do_bpc_leva_o_bloco_no_sistema():
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Entendi. Quantos anos ele tem?")})
    await turno.processar(modelo, entrada(["oi"], prod=produto("bpc-loas-infantil")))
    sistema = next(p["sistema"] for p in modelo.pedidos if p["papel"] == "etapa")
    assert "BPC/LOAS\n- Nunca diga \"per capita\"" in sistema
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Entendi. Como foi o acidente?")})
    await turno.processar(modelo, entrada(["oi"]))
    assert "per capita" not in next(p["sistema"] for p in modelo.pedidos if p["papel"] == "etapa")
