"""Correções das checagens da avaliação depois das rodadas de 2026-11-25 (agente Sousa e Costa e agente de referência).

Cada achado tem o caso que dava falso alarme (passa a não acusar) e um erro real equivalente (continua acusado).
Nada chama a API: as rodadas são montadas à mão, com os textos das transcrições.
"""

import re

import pytest

from app.avaliacao import cenario, checagens, juiz, leads, oraculo, relatorio, simulador
from app.avaliacao.cenario import Fala
from app.avaliacao.checagens import ALTA, CRITICA, MEDIA
from app.avaliacao.simulador import Rodada, TurnoSimulado

PASTA_SC = cenario.PASTA / "cenarios_sousa_costa"
URL_MIDIA = "https://mqkgzkzlysvwjjuwvxul.supabase.co/storage/v1/object/public/midia/"
CONFIRMAR = "Vamos confirmar juntos todos os seus dados para garantir que está tudo certinho, tudo bem?"
RESUMO_SC02 = ("Nome completo: Joel Antunes Carvalho\nCPF: 53268353398\nEndereço: Rua Exemplo dos Cedros, Jardim Exemplo\n"
               "Número: 318\nTelefone: (32) 99000-0202\nEstá tudo correto? Posso gerar o contrato?")


def sc(prefixo, variante=None):
    casos = cenario.casos([prefixo], pasta=PASTA_SC)
    return next(c for c in casos if variante is None or f"[{variante}" in c.id)


def ref(prefixo, variante=None):
    casos = cenario.casos([prefixo])
    return next(c for c in casos if variante is None or f"[{variante}" in c.id)


def rod(n, etapa, falas, mensagens, depois=None, sistema=(), fatos=None, midias=(), ferramenta="", resposta=None):
    depois = depois or etapa
    turno = TurnoSimulado(id=f"t{n}", situacao="respondido", motivo="catalogo", etapa_antes=etapa, etapa_depois=depois,
                          mensagens=list(mensagens), midias=list(midias), ferramenta=ferramenta,
                          resposta_mensagens=list(resposta or []))
    return Rodada(n=n, falas=[Fala(texto=t, origem=o) for o, t in falas], etapa_antes=etapa, etapa_depois=depois,
                  estado_depois="ativo", turnos=[turno], enviadas=list(mensagens) + list(sistema),
                  enviadas_ia=list(mensagens), enviadas_sistema=list(sistema), fatos_depois=dict(fatos or {}))


def conversa_de(c, rodadas, parada, trajetoria, **extra):
    snap = c.carregar_agente()
    conversa = simulador.Conversa(
        cenario=c, snapshot=snap, rodadas=rodadas, parada=parada, trajetoria=trajetoria,
        estado_final=extra.get("estado_final", "ativo"), etapa_final=trajetoria[-1],
        fatos_finais=extra.get("fatos", {}), fatos_historico=extra.get("historico", []), acoes=extra.get("acoes", []),
        contratos=extra.get("contratos", []), custo={"total_usd": 0.0})
    return conversa, checagens.Regras(c, snap)


def codigos(falhas):
    return {f.codigo for f in falhas}


# ---------------------------------------------------------------------------- [0] conversa cortada por laço
PEDIDO_CPF = ("O CPF informado está incorreto, pois não passou na validação dos dígitos. Por favor, me envie o CPF correto "
              "para continuarmos.")


def _sc01(parada, email_dito=False, ferramentas=0):
    c = sc("sc01")
    rodadas = [rod(1, "closer", [("assunto:17", "sim, pode")],
                   ["Os honorários são combinados no contrato.", "Excelente! Por gentileza, me informe seu nome completo "
                    "para darmos continuidade à formalização."], depois="contratos"),
               rod(2, "contratos", [("assunto:18", "Valdir Santana Rocha")], ["Agora me informe o seu CPF."])]
    if email_dito:
        rodadas.append(rod(3, "contratos", [("assunto:26", "valdir.rocha.teste@exemplo.invalid")], ["Anotado."]))
    n = len(rodadas)
    rodadas += [rod(n + 1, "contratos", [("assunto:19", "057.830.862.23")], [PEDIDO_CPF],
                    ferramenta="zapsign" if ferramentas else ""),
                rod(n + 2, "contratos", [("repetida:19", "como eu falei, 057.830.862.23")], [PEDIDO_CPF],
                    ferramenta="zapsign" if ferramentas > 1 else ""),
                rod(n + 3, "contratos", [("repetida:19", "como eu falei, 057.830.862.23")], [PEDIDO_CPF])]
    conversa, regras = conversa_de(c, rodadas, parada, ["sdr", "closer", "contratos"],
                                   fatos={"nome_completo": "Valdir Santana Rocha"})
    return checagens.da_conversa(conversa, regras)


def test_cortada_por_laco_vira_uma_so_nao_avaliado():
    falhas = _sc01("laco")
    assert "laco" in codigos(falhas) and not checagens.aprovado(falhas)            # o laço continua reprovando
    assert not codigos(falhas) & {"contrato", "ferramenta_contagem", "cep", "estado_final", "fato_nao_capturado",
                                  "faltou_obrigatorio"}, [f.como_dict() for f in falhas]
    nao = [f for f in falhas if f.codigo == "nao_avaliado"]
    assert len(nao) == 1 and nao[0].gravidade == MEDIA
    for item in ("contrato gerado", "zapsign", "CEP", "estado final", "fato email", "obrigatório da etapa contratos"):
        assert item in nao[0].evidencia, nao[0].evidencia


def test_limite_de_turnos_tambem_corta():
    falhas = _sc01("limite_turnos")
    assert "nao_concluiu" in codigos(falhas) and "nao_avaliado" in codigos(falhas)
    assert "contrato" not in codigos(falhas)


def test_conversa_que_terminou_sem_contrato_continua_acusada():
    falhas = _sc01("lead_pausado")
    assert {"contrato", "cep", "fato_nao_capturado", "faltou_obrigatorio"} <= codigos(falhas)
    assert "nao_avaliado" not in codigos(falhas)


def test_cortada_mas_o_lead_tinha_dito_o_email_continua_acusada():
    falhas = _sc01("laco", email_dito=True)
    assert any(f.codigo == "fato_nao_capturado" and "email" in f.evidencia for f in falhas)


def test_zapsign_com_a_mesma_contagem_zero_nao_vale_duas_falhas():
    falhas = _sc01("lead_pausado")
    assert "contrato" in codigos(falhas) and "ferramenta_contagem" not in codigos(falhas)
    falhas = _sc01("lead_pausado", ferramentas=2)                    # 2 zapsign, 0 contrato: contagens diferentes
    assert {"contrato", "ferramenta_contagem"} <= codigos(falhas)


# ---------------------------------------------------------------------------- [10] CPF só com dígitos
@pytest.mark.parametrize("chave, trecho, valor, bate", [
    ("cpf", "714.970.940-03", "71497094003", True),
    ("cpf", "714.970.940-03", "714.970.940-03", True),
    ("cpf", "714.970.940-03", "71497094004", False),
    ("cpf", "714.970.940-03", "", False),
    ("cep", "39999-412", "39999412", True),
    ("numero_casa", "S/N", "", False),
    ("rg", "MG-14.207.385", "MG-14.207.385", True),
])
def test_fato_compara_cpf_cep_e_telefone_pelos_digitos(chave, trecho, valor, bate):
    assert checagens._fato_bate(chave, trecho, valor) is bate


def test_sc11_cpf_sem_pontuacao_nao_e_fato_nao_capturado():
    c = sc("sc11")
    fatos = {"nome_completo": "Rosângela Pires Moura", "cpf": "71497094003", "endereco": "Rua Exemplo do Cascalho",
             "bairro": "Vila Exemplo Nova", "cidade": "Pedra Branca do Exemplo"}
    conversa, regras = conversa_de(c, [rod(1, "contratos", [("assunto:14", "71497094003")], ["Anotado."])],
                                   "contrato_assinado", ["sdr", "closer", "contratos", "assinatura", "contrato_assinado"],
                                   fatos=fatos)
    assert not [f for f in checagens.da_conversa(conversa, regras) if f.codigo == "fato_nao_capturado"]
    conversa.fatos_finais = {**fatos, "cpf": "71497094004"}
    assert [f for f in checagens.da_conversa(conversa, regras) if f.codigo == "fato_nao_capturado"]


# ---------------------------------------------------------------------------- [1][6][9][25] mídias
def test_transcricao_e_juiz_mostram_a_midia_na_ordem():
    c = sc("sc01")
    r = rod(1, "sdr", [("abertura", "oi")], ["Olá! Me chamo Ana."])
    r.turnos[0].envios = [("midia", URL_MIDIA + "PTV.mp4"), ("texto", "Olá! Me chamo Ana.")]
    r.turnos[0].midias = [URL_MIDIA + "PTV.mp4"]
    conversa, _ = conversa_de(c, [r], "lead_saiu", ["sdr"])
    linhas = [l for l in relatorio.transcricao(conversa) if l.autor == "ia"]
    assert [(l.tipo, l.texto) for l in linhas] == [("midia", URL_MIDIA + "PTV.mp4"), ("texto", "Olá! Me chamo Ana.")]
    texto = juiz.transcricao(conversa)
    assert "[mídia enviada: PTV.mp4]" in texto and texto.index("PTV.mp4") < texto.index("Me chamo Ana")


def test_turno_montado_a_mao_ainda_mostra_as_midias_depois_dos_textos():
    c = sc("sc01")
    r = rod(1, "closer", [("abertura", "oi")], ["Conseguiu entender?"], midias=[URL_MIDIA + "video-honorarios-5salarios.mp4"])
    conversa, _ = conversa_de(c, [r], "lead_saiu", ["closer"])
    assert [l.tipo for l in relatorio.transcricao(conversa) if l.autor == "ia"] == ["texto", "midia"]


def test_midia_do_prompt_nao_e_link_inventado_e_a_inventada_e():
    c = sc("sc01")
    regras = checagens.Regras(c, c.carregar_agente())
    assert URL_MIDIA + "Como%20Funciona%20o%20Auxilio%20Acidente.ogg" in regras.links_do_agente     # antes grudava o "\n"
    boa = rod(1, "closer", [("abertura", "oi")], ["Veja o áudio."], midias=[URL_MIDIA + "Como%20Funciona%20o%20Auxilio%20Acidente.ogg"])
    assert "link_inventado" not in codigos(checagens.por_turno(boa, regras, []))
    ruim = rod(1, "closer", [("abertura", "oi")], ["Veja o áudio."], midias=[URL_MIDIA + "inventado.ogg"])
    assert "link_inventado" in codigos(checagens.por_turno(ruim, regras, []))


def test_trava_sombra_so_conta_midia_inexistente_para_url_fora_do_prompt():
    c = sc("sc01")
    regras = checagens.Regras(c, c.carregar_agente())

    def sombra(url):
        r = rod(1, "sdr", [("abertura", "oi")], ["Olá! Me chamo Ana."],
                resposta=[{"tipo": "midia", "url": url, "chave": url.rsplit("/", 1)[-1]},
                          {"tipo": "texto", "texto": "Olá! Me chamo Ana."}])
        return checagens.trava_sombra(r, regras)

    assert "midia_inexistente" not in sombra(URL_MIDIA + "PTV.mp4")
    assert sombra(URL_MIDIA + "inventado.mp4")["midia_inexistente"] == 1


def test_midia_conta_em_obrigatorio_em_e_midias_em():
    c = sc("sc19").model_copy(deep=True)
    c.esperado.obrigatorio_em = {"closer": ["(?i)video-honorarios"]}
    c.esperado.midias_em = {"closer": ["(?i)video-honorarios"]}
    sem = [rod(1, "closer", [("abertura", "oi")], ["Conseguiu entender certinho as condições dos honorários?"])]
    conversa, regras = conversa_de(c, sem, "lead_saiu", ["closer"])
    assert {"faltou_obrigatorio", "midia_obrigatoria"} <= codigos(checagens.da_conversa(conversa, regras))
    com = [rod(1, "closer", [("abertura", "oi")], ["Conseguiu entender certinho as condições dos honorários?"],
               midias=[URL_MIDIA + "video-honorarios-5salarios.mp4"])]
    conversa, regras = conversa_de(c, com, "lead_saiu", ["closer"])
    assert not {"faltou_obrigatorio", "midia_obrigatoria"} & codigos(checagens.da_conversa(conversa, regras))


# ---------------------------------------------------------------------------- [2] dado inventado
def _sc02_turno(texto):
    c = sc("sc02")
    regras = checagens.Regras(c, c.carregar_agente())
    anteriores = [rod(1, "contratos", [("assunto:19", "39999-412")], ["Recebi seu CEP."], fatos={"cep": "39999-412"})]
    r = rod(2, "contratos", [("assunto:20", "Número 318 Fundos")], [texto], fatos={"cep": "39999-412"})
    return [f for f in checagens.por_turno(r, regras, anteriores) if f.codigo == "dado_inventado"]


def test_endereco_que_nao_veio_do_cep_e_inventado():
    falhas = _sc02_turno("Buscamos nos Correios e o seu endereço é: Rua Santa Luzia, Bairro Centro, Cidade São João do "
                         "Paraíso, MG.\nQual o número do seu imóvel?")
    assert falhas and falhas[0].gravidade == CRITICA and "Santa Luzia" in falhas[0].evidencia
    assert not _sc02_turno("Buscamos nos Correios e o seu endereço é: Rua Exemplo dos Cedros, Bairro Jardim Exemplo, "
                           "Ribeirão do Exemplo, MG.\nQual o número do seu imóvel?")
    assert not _sc02_turno("Anotei: Rua Exemplo dos Cedros e o número 318.")           # sobra depois do nome
    assert _sc02_turno("Anotei: Rua Santa Catarina, 318.")                              # uma palavra igual não basta


def test_resumo_com_o_cep_no_telefone_e_troca_de_campo():
    falhas = _sc02_turno(RESUMO_SC02.replace("(32) 99000-0202", "39999-412"))
    assert falhas and "é o CEP" in falhas[0].evidencia
    assert not _sc02_turno(RESUMO_SC02)
    assert _sc02_turno(RESUMO_SC02.replace("53268353398", "11122233344"))                      # CPF que o lead não passou


# ---------------------------------------------------------------------------- [3][18] balão sem pergunta nem pedido
async def test_lead_diz_ok_a_um_aviso_que_so_retoma_o_assunto():
    lead = leads.LeadCartao(sc("sc02").lead)
    lead.abrir()
    assert (await lead.responder(["Qual o seu CEP?"]))[0].origem == "assunto:19"
    aviso = (await lead.responder(["Recebi seu CEP: 39999-412. Vou buscar os dados do seu endereço nos Correios."]))[0]
    assert (aviso.origem, aviso.texto) == ("ack", "ok")
    de_novo = (await lead.responder(["Por favor, me informe o seu CEP de novo."]))[0]          # pedido sem "?"
    assert de_novo.origem == "repetida:19"


def test_recapitulacao_sem_pergunta_nao_e_pergunta_repetida():
    c = sc("sc16", "com_seguro")
    regras = checagens.Regras(c, c.carregar_agente())
    recap = ("Ótimo, você recebeu seguro-desemprego após a demissão em março de 2023.\nAgora vou calcular o período de "
             "graça para verificar se você mantinha a qualidade de segurado.")
    rodadas = [rod(1, "periododegraca", [("assunto:0", "recebi sim as parcela tudo")], [recap]),
               rod(2, "periododegraca", [("repetida:0", "como eu falei, recebi sim as parcela tudo")], ["Certo."])]
    assert checagens._fato_pedido_de_novo(rodadas, regras) == []
    pedido = "Por favor, informe o mês e o ano da sua demissão da transportadora antes do acidente."
    rodadas = [rod(1, "periododegraca", [("assunto:5", "fui mandado embora em março de 2023")], [pedido]),
               rod(2, "periododegraca", [("repetida:5", "como eu falei, fui mandado embora em março de 2023")], ["Certo."])]
    assert codigos(checagens._fato_pedido_de_novo(rodadas, regras)) == {"pergunta_repetida"}


def test_aviso_de_busca_do_cep_nao_e_pergunta_repetida():
    c = sc("sc02")
    regras = checagens.Regras(c, c.carregar_agente())
    aviso = "Recebi seu CEP: 39999-412. Vou buscar os dados do seu endereço nos Correios."
    rodadas = [rod(1, "contratos", [("assunto:19", "39999-412")], [aviso]),
               rod(2, "contratos", [("repetida:19", "como eu falei, 39999-412")], ["Qual o número do seu imóvel?"])]
    assert checagens._fato_pedido_de_novo(rodadas, regras) == []


# ---------------------------------------------------------------------------- [4] pedido de correção do sistema
def test_pedido_de_correcao_do_sistema_tem_codigo_proprio():
    c = sc("sc02")
    regras = checagens.Regras(c, c.carregar_agente())
    sistema = ("Para finalizar seu contrato, preciso confirmar algumas informações: o nome da sua rua ou avenida, o seu "
               "bairro, a sua cidade, o seu estado (a sigla, como MG ou SP) e o seu CEP. Pode me enviar novamente, por favor?")
    rodadas = [rod(1, "contratos", [("assunto:24", "Tudo certo")],
                   ["Perfeito! Estamos gerando o seu contrato.\nEm alguns segundos você vai receber o link para assinatura!"],
                   sistema=[sistema]),
               rod(2, "contratos", [("repetida:19", "como eu falei, 39999-412")], ["Recebi seu CEP."])]
    falhas = checagens._fato_pedido_de_novo(rodadas, regras)
    assert [(f.codigo, f.gravidade) for f in falhas] == [("correcao_pediu_dado_ja_dado", ALTA)]
    assert "Para finalizar seu contrato" in falhas[0].evidencia
    rodadas[0].enviadas_ia = rodadas[0].turnos[0].mensagens = ["Me manda o seu CEP de novo, por favor?"]
    assert codigos(checagens._fato_pedido_de_novo(rodadas, regras)) == {"pergunta_repetida"}     # a IA também pediu


# ---------------------------------------------------------------------------- [5][8] confirmação refeita
def test_confirmacao_refeita_depois_de_dado_novo_nao_e_repeticao():
    sistema = "Para finalizar seu contrato, preciso confirmar o seu CEP. Pode me enviar novamente, por favor?"
    rodadas = [rod(1, "contratos", [("assunto:22", "pode ser esse mesmo do zap")], [CONFIRMAR, RESUMO_SC02],
                   fatos={"cpf": "53268353398"}),
               rod(2, "contratos", [("assunto:24", "Tudo certo")], ["Perfeito! Estamos gerando o seu contrato."],
                   sistema=[sistema], fatos={"cpf": "53268353398"}),
               rod(3, "contratos", [("assunto:21", "joel.teste@exemplo.invalid")],
                   ["Anotei seu e-mail. " + CONFIRMAR, RESUMO_SC02],
                   fatos={"cpf": "53268353398", "email": "joel.teste@exemplo.invalid"})]
    assert checagens._perguntas_repetidas(rodadas) == []


def test_confirmacao_sem_nada_novo_continua_repeticao():
    rodadas = [rod(1, "contratos", [("assunto:22", "pode ser")], [CONFIRMAR, RESUMO_SC02], fatos={"cpf": "1"}),
               rod(2, "contratos", [("assunto:24", "Tudo certo")], [RESUMO_SC02], fatos={"cpf": "1"})]
    assert codigos(checagens._perguntas_repetidas(rodadas)) == {"pergunta_repetida"}


def test_tudo_bem_que_abre_a_lista_e_retorico():
    rodadas = [rod(1, "contratos", [("assunto:34", "foi um tempo depois")], ["Sobre o joelho, anotado. " + CONFIRMAR]),
               rod(2, "contratos", [("assunto:35", "agora sim, pode gerar")],
                   [CONFIRMAR, "Nome completo: Josimar Aparecido dos Santos Moura\nTelefone: (33) 99000-0302"])]
    assert checagens._perguntas_repetidas(rodadas) == []


def test_pergunta_do_roteiro_sozinha_e_repetida_continua_acusada():
    pergunta = "Perfeito! Vamos avançar para a formalização da nossa representação. Podemos iniciar a coleta dos seus dados?"
    rodadas = [rod(1, "closer", [("assunto:16", "pode ss")], [pergunta]),
               rod(2, "closer", [("assunto:23", "pode sim")], [pergunta])]
    assert codigos(checagens._perguntas_repetidas(rodadas)) == {"pergunta_repetida"}


def test_dado_novo_do_contrato_nao_libera_pergunta_de_dado():
    rodadas = [rod(1, "contratos", [("assunto:16", "x")], ["Qual o seu CPF?"]),
               rod(2, "contratos", [("assunto:16", "53268353398")], ["Qual o seu RG?"], fatos={"cpf": "53268353398"}),
               rod(3, "contratos", [("assunto:17", "MG-14.207.385")], ["Qual o seu CPF?"],
                   fatos={"cpf": "53268353398", "rg": "MG-14.207.385"})]
    assert codigos(checagens._perguntas_repetidas(rodadas)) == {"pergunta_repetida"}


# ---------------------------------------------------------------------------- [7] aceite antes de contratos
def _sc03_aceite(falas_closer):
    c = sc("sc03")
    rodadas = [rod(i + 1, "closer", [fala], ["Certo."]) for i, fala in enumerate(falas_closer[:-1])]
    rodadas.append(rod(len(falas_closer), "closer", [falas_closer[-1]], ["Agora vou iniciar a formalização."],
                       depois="contratos"))
    return checagens._aceite_antes_de_contratos(rodadas, checagens.Regras(c, c.carregar_agente()))


def test_sim_dois_turnos_antes_da_transferencia_conta():
    assert _sc03_aceite([("assunto:22", "bom dia, vamos fazer sim"), ("assunto:23", "pode sim"),
                         ("assunto:24", "ah, ele rompeu o ligamento também. Josimar Aparecido dos Santod Mpura")]) == []


def test_nao_sei_depois_do_sim_ou_sem_sim_continua_acusado():
    assert _sc03_aceite([("assunto:23", "pode sim"), ("padrao", "não sei te dizer"),
                         ("assunto:24", "Josimar Aparecido dos Santos Moura")])
    assert _sc03_aceite([("assunto:21", "dá pra eu te mandar amanhã?"), ("assunto:24", "Josimar Aparecido dos Santos Moura")])
    assert _sc03_aceite([("assunto:23", "pode sim"), ("assunto:21", "dá pra eu te mandar amanhã ou depois?"),
                         ("assunto:24", "Josimar Aparecido dos Santos Moura")])          # adiamento depois do sim


# ---------------------------------------------------------------------------- [11] oráculo: ano do acidente com CLT
def test_ano_do_acidente_nao_e_decisivo_com_clt_mas_e_com_desempregado():
    clt = sc("sc10").lead.verdade
    assert "acidente_ano" not in oraculo.fatos_decisivos(clt)
    assert "acidente_ano" in oraculo.fatos_de_completude(clt)
    assert "acidente_ano" in oraculo.fatos_decisivos(sc("sc16", "com_seguro").lead.verdade)
    assert {"vinculo_na_data", "demissao_ano", "contribuiu_por_conta_propria"} <= set(
        oraculo.fatos_decisivos(ref("02").lead.verdade))


def test_clt_sem_o_ano_vira_metrica_media_e_sem_o_vinculo_continua_alta():
    c = sc("sc11")
    regras = checagens.Regras(c, c.carregar_agente())
    indices = {f: i for i, a in enumerate(c.lead.assuntos) for f in reversed(a.fatos) if "acidente_ano" not in a.fatos}
    assert regras.fatos_decisivos[0] == "vinculo_na_data" and "acidente_ano" not in regras.fatos_decisivos
    contou = [(f"assunto:{indices[f]}", "x") for f in regras.fatos_decisivos]
    rodadas = [rod(i + 1, "sdr", [fala], ["Certo?"]) for i, fala in enumerate(contou)]
    rodadas[-1].turnos[0].etapa_depois = "closer"
    falhas = checagens._sem_os_fatos_do_oraculo(rodadas, regras)
    assert [(f.codigo, f.gravidade) for f in falhas] == [("pulou_pergunta_do_roteiro", MEDIA)]
    assert "acidente_ano" in falhas[0].evidencia
    falhas = checagens._sem_os_fatos_do_oraculo(rodadas[1:], regras)            # sem o vínculo
    assert [(f.codigo, f.gravidade) for f in falhas] == [("pulou_pergunta", ALTA)]
    assert "vinculo_na_data" in falhas[0].evidencia and "acidente_ano" in falhas[0].evidencia


# ---------------------------------------------------------------------------- [12] perguntas literais do roteiro
def test_confirmacao_literal_do_contratos_nao_e_varias_perguntas():
    c = sc("sc11")
    regras = checagens.Regras(c, c.carregar_agente())
    texto = CONFIRMAR + "\nNome completo: Rosângela Pires Moura\nEstá tudo correto? Posso gerar o contrato?"
    assert texto.count("?") == 3 and checagens.perguntas_contadas(texto, regras, "contratos") == 0
    assert checagens.perguntas_contadas("Qual o seu CPF? E o seu RG?", regras, "contratos") == 2
    assert checagens.perguntas_contadas("Qual o bairro? Qual a cidade e estado?", regras, "contratos") == 2   # só exemplo
    r = rod(1, "contratos", [("assunto:21", "pode ser esse")], [texto])
    assert "varias_perguntas" not in codigos(checagens.por_turno(r, regras, []))


# ---------------------------------------------------------------------------- [13] laço pelo lead
def test_lead_repetindo_o_mesmo_assunto_para_a_conversa():
    c = sc("sc10")
    rodadas = [rod(n, "contratos", [("repetida:14", "como eu falei, 205.096.961.98")], [f"CPF inválido, versão {n}."])
               for n in range(1, 4)]
    assert checagens.laco_do_lead(rodadas)
    conversa, _ = conversa_de(c, rodadas, "", ["contratos"])
    assert simulador._parada(rodadas[-1], conversa, c) == "laco"
    rodadas[1].falas[0].origem = "repetida:13"
    assert not checagens.laco_do_lead(rodadas)


# ---------------------------------------------------------------------------- [14] período de graça indevido
def test_lead_clt_mandado_ao_periodo_de_graca_e_acusado():
    c = sc("sc14")
    rodadas = [rod(1, "sdr", [("abertura", "oi")], ["Agora vou confirmar algumas informações importantes sobre seu "
                                                     "vínculo com o INSS, tudo bem?"], depois="periododegraca")]
    conversa, regras = conversa_de(c, rodadas, "lead_invalido", ["sdr", "periododegraca"])
    falhas = checagens.da_conversa(conversa, regras)
    assert any(f.codigo == "periodo_indevido" and f.gravidade == ALTA for f in falhas)
    assert "periodo_indevido" not in checagens.DO_FIM_DA_CONVERSA


def test_destino_fixo_sem_trajetoria_nao_acusa_periodo():
    c = sc("sc15", "saiu_ha_mais_de_3_anos")
    rodadas = [rod(1, "sdr", [("abertura", "oi")], ["Certo."], depois="periododegraca")]
    conversa, regras = conversa_de(c, rodadas, "desqualificado", ["sdr", "periododegraca", "desqualificado"])
    assert "periodo_indevido" not in codigos(checagens.da_conversa(conversa, regras))


def test_rodada_invalida_com_trajetoria_desviada_conta_no_cenario():
    c = sc("sc14")

    def rodada(evidencia):
        return relatorio.RodadaJ(n=1, aprovado=False, invalida="lead sem assunto para: demissão", parada="lead_invalido",
                                 falhas=[relatorio.FalhaJ(codigo="trajetoria", gravidade="alta", turno=11, evidencia=evidencia)])

    desviou = relatorio.cenario_j(c, [rodada("vista ['sdr', 'periododegraca'] | esperada ['sdr', 'closer'] (parada: x)")])
    assert desviou.aprovado is False and desviou.pulado is None and desviou.por_checagem == {"trajetoria": "1/1"}
    curta = relatorio.cenario_j(c, [rodada("vista ['sdr'] | esperada ['sdr', 'closer'] (parada: x)")])
    assert curta.aprovado is None and curta.pulado                               # só ficou curta: continua pulada


# ---------------------------------------------------------------------------- [15] eco de confirmação
def test_eco_do_que_o_lead_acabou_de_dizer_nao_e_pedido_de_novo():
    c = sc("sc13", "aposentada_por_invalidez")
    regras = checagens.Regras(c, c.carregar_agente())
    eco = "Entendi, você recebeu auxílio-doença e depois foi aposentado por invalidez, certo?"
    rodadas = [rod(1, "sdr", [("assunto:2", "recebi uns seis meses, depois em 2021 me aposentaram por invalidez")], [eco]),
               rod(2, "desqualificado", [("repetida:4", "como eu falei, sou sim, me aposentaram")], ["Certo."])]
    assert checagens._fato_pedido_de_novo(rodadas, regras) == []


def test_eco_de_fato_dito_turnos_antes_continua_acusado():
    c = sc("sc13", "aposentada_por_invalidez")
    regras = checagens.Regras(c, c.carregar_agente())
    rodadas = [rod(1, "sdr", [("assunto:2", "recebi uns seis meses, depois me aposentaram")], ["E tem advogado?"]),
               rod(2, "sdr", [("assunto:5", "nao tenho")], ["Você é aposentada, certo?"]),
               rod(3, "sdr", [("repetida:4", "como eu falei, sou sim")], ["Certo."])]
    assert codigos(checagens._fato_pedido_de_novo(rodadas, regras)) == {"pergunta_repetida"}


# ---------------------------------------------------------------------------- [17] fatos do oráculo no destino errado
def test_decidir_errado_sem_os_fatos_tambem_acusa_os_que_faltaram():
    c = sc("sc16", "com_seguro")                                  # o oráculo manda ao closer (dentro do período)
    regras = checagens.Regras(c, c.carregar_agente())
    rodadas = [rod(1, "sdr", [("assunto:1", "caí da moto")], ["Certo."], depois="periododegraca"),
               rod(2, "periododegraca", [("assunto:5", "fui mandado embora em março de 2023")], ["Certo."],
                   depois="desqualificado")]
    falhas = checagens._sem_os_fatos_do_oraculo(rodadas, regras)
    assert falhas and falhas[0].codigo == "pulou_pergunta" and "acidente_ano" in falhas[0].evidencia
    assert "foi para desqualificado" in falhas[0].evidencia


# ---------------------------------------------------------------------------- [19] lead: assunto novo no mesmo balão
async def test_lead_responde_a_demissao_pedida_junto_da_carteira_ja_respondida():
    lead = leads.LeadCartao(sc("sc16", "com_seguro").lead)
    lead.abrir()
    assert (await lead.responder(["Você já teve carteira assinada (CLT) antes do acidente?"]))[0].origem == "assunto:6"
    resposta = (await lead.responder(["Qual foi a última vez que você trabalhou de carteira assinada (CLT) antes do "
                                      "acidente? Por favor, me informe o mês e o ano da sua demissão."]))[0]
    assert resposta.origem == "assunto:5" and "março de 2023" in resposta.texto
    de_novo = (await lead.responder(["Você já teve carteira assinada (CLT) antes do acidente?"]))[0]
    assert de_novo.origem == "repetida:6"                         # sem assunto novo no balão: continua repetição


# ---------------------------------------------------------------------------- [20][23][26] frase de troca
def _transferencia(c, origem, destino, texto):
    regras = checagens.Regras(c, c.carregar_agente())
    r = rod(1, origem, [("abertura", "x")], [texto], depois=destino)
    return [f for f in checagens.por_turno(r, regras, []) if "frase" in f.codigo]


def test_frase_do_sdr_nao_e_cobrada_de_quem_desqualifica_pelo_periodo_de_graca():
    c = sc("sc15", "nunca_clt")
    texto = "Infelizmente você não mantém a qualidade de segurado."
    assert _transferencia(c, "periododegraca", "desqualificado", texto) == []
    assert codigos(_transferencia(c, "sdr", "desqualificado", texto)) == {"transferencia_sem_frase"}
    assert c.esperado.transferencias_com_frase == ["desqualificado"]
    c2 = c.model_copy(deep=True)
    c2.esperado.transferencias_com_frase = ["periododegraca>desqualificado"]        # par explícito cobra sempre
    assert codigos(_transferencia(c2, "periododegraca", "desqualificado", texto)) == {"transferencia_sem_frase"}


def test_frase_de_troca_de_outro_destino_e_acusada():
    c = sc("sc15", "saiu_ha_mais_de_3_anos")
    frase_pg = "Agora vou confirmar algumas informações importantes sobre seu vínculo com o INSS, tudo bem?"
    falhas = _transferencia(c, "sdr", "desqualificado", "Entendi, já faz bastante tempo.\n" + frase_pg)
    assert [(f.codigo, f.gravidade) for f in falhas] == [("frase_de_troca_trocada", ALTA)]
    assert _transferencia(c, "sdr", "periododegraca", "Entendi.\n" + frase_pg) == []


def test_frase_com_as_oracoes_trocadas_vira_media():
    c = ref("03", "extrator_sozinho")
    alterada = ("Entendi, obrigada por responder com clareza. Pelo que você me contou, infelizmente, o nosso escritório "
                "não vai conseguir seguir com o seu caso.")
    falhas = _transferencia(c, "periododegraca", "desqualificado", alterada)
    assert [(f.codigo, f.gravidade) for f in falhas] == [("frase_de_troca_alterada", MEDIA)]
    falhas = _transferencia(c, "periododegraca", "desqualificado", "Entendi. Não vamos seguir com o seu caso.")
    assert [(f.codigo, f.gravidade) for f in falhas] == [("transferencia_sem_frase", ALTA)]


# ---------------------------------------------------------------------------- [22] data do acidente inventada
def _data(c, falas_lead, texto):
    regras = checagens.Regras(c, c.carregar_agente())
    anteriores = [rod(i + 1, "sdr", [fala], ["Certo."]) for i, fala in enumerate(falas_lead)]
    r = rod(len(anteriores) + 1, "desqualificado", [("assunto:5", "nao tenho")], [texto])
    return [f for f in checagens.por_turno(r, regras, anteriores) if f.codigo == "data_inventada"]


def test_ano_do_acidente_que_o_lead_nunca_disse_e_inventado():
    c = sc("sc13", "ja_recebe_auxilio_acidente")
    falhas = _data(c, [("assunto:0", "caí na calçada e machuquei a mão")],
                   "Pelo que você me contou, acidente ocorrido em 2026, do tipo queda na calçada.")
    assert falhas and falhas[0].gravidade == ALTA and "2026" in falhas[0].evidencia
    assert "2026" not in re.findall(r"\d+", c.agora.strftime("%d/%m %H:%M"))


def test_data_que_o_lead_disse_ou_deu_por_conta_vale():
    c = sc("sc13", "aposentada_por_invalidez")
    assert not _data(c, [("assunto:1", "foi em maio de 2018")],
                     "Pelo que você me contou, acidente ocorrido em maio de 2018, do tipo queda na calçada.")
    assert _data(c, [("assunto:1", "foi em maio de 2018")],
                 "Pelo que você me contou, acidente ocorrido em junho de 2018.")                 # o mês errado
    assert not _data(c, [("assunto:1", "faz uns 2 anos")], "Certo, o acidente foi em 2024.")   # agora: março de 2026


# ---------------------------------------------------------------------------- [24][27] chaves opcionais do cenário
def test_confirmacao_e_nota_no_mesmo_turno():
    c = sc("sc13", "ja_recebe_auxilio_acidente").model_copy(deep=True)
    c.esperado.nao_no_mesmo_turno = {"desqualificado": [["(?i)me avisa se algo mudou", "(?i)nota de 1 a 5"]]}
    regras = checagens.Regras(c, c.carregar_agente())
    juntos = rod(1, "desqualificado", [("abertura", "x")],
                 ["Só quero confirmar se entendi tudo certo, então me avisa se algo mudou.",
                  "Antes de encerrar, pode me avaliar com uma nota de 1 a 5 sobre o atendimento?"])
    assert "no_mesmo_turno" in codigos(checagens.por_turno(juntos, regras, []))
    separado = rod(1, "desqualificado", [("abertura", "x")], ["Só quero confirmar se entendi tudo certo, então me avisa se algo mudou."])
    assert "no_mesmo_turno" not in codigos(checagens.por_turno(separado, regras, []))


def test_transferir_com_pergunta_aberta_so_quando_o_cenario_pede():
    c = ref("03", "sem_seguro").model_copy(deep=True)
    texto = "Vou te fazer mais algumas perguntas sobre o seu trabalho.\nDepois do acidente, você ficou com alguma sequela?"
    assert not [f for f in checagens.por_turno(rod(1, "sdr", [("abertura", "x")], [texto], depois="periododegraca"),
                                               checagens.Regras(c, c.carregar_agente()), [])
                if f.codigo == "transferiu_com_pergunta_aberta"]
    c.esperado.sem_pergunta_ao_transferir = ["periododegraca"]
    regras = checagens.Regras(c, c.carregar_agente())
    assert "transferiu_com_pergunta_aberta" in codigos(
        checagens.por_turno(rod(1, "sdr", [("abertura", "x")], [texto], depois="periododegraca"), regras, []))
    sousa = sc("sc16", "com_seguro").model_copy(deep=True)                       # a frase de troca termina em "tudo bem?"
    sousa.esperado.sem_pergunta_ao_transferir = ["periododegraca"]
    frase = "Agora vou confirmar algumas informações importantes sobre seu vínculo com o INSS, tudo bem?"
    assert "transferiu_com_pergunta_aberta" not in codigos(checagens.por_turno(
        rod(1, "sdr", [("abertura", "x")], ["Entendi.\n" + frase], depois="periododegraca"),
        checagens.Regras(sousa, sousa.carregar_agente()), []))


# ---------------------------------------------------------------------------- [28] 100% online
@pytest.mark.parametrize("texto", [
    "Fique tranquilo: cuidamos de todo o pedido para você, de forma 100% online.",
    "Nosso atendimento é 100% online pelo WhatsApp e não enviamos links do site.",
])
def test_cem_por_cento_online_do_catalogo_nao_e_honorario(texto):
    assert checagens.valores_de_honorario(texto) == set() and checagens.promessa_de_resultado(texto) is None


def test_cem_por_cento_dos_atrasados_continua_honorario():
    assert checagens.valores_de_honorario("Cobramos 100% dos atrasados.") == {"100%"}


# ---------------------------------------------------------------------------- [21][29] juiz
def test_juiz_nao_recebe_as_falhas_que_o_confirmam_e_ve_a_tabela_de_cep():
    c = sc("sc02")
    conversa, _ = conversa_de(c, [rod(1, "sdr", [("abertura", "oi")], ["Olá!"])], "lead_saiu", ["sdr"])
    conversa.falhas = [checagens.Falha("honorario_divergente", CRITICA, 5, "100% não está em '30%'"),
                       checagens.Falha("varias_perguntas", MEDIA, 6, "2 perguntas: x")]
    contexto = juiz._contexto(conversa)
    assert "honorario_divergente" not in contexto and "varias_perguntas" in contexto
    assert "Rua Exemplo dos Cedros" in contexto and "NÃO foi dito ao atendente" in contexto
    assert "NÃO foi dita ao atendente" in juiz.RUBRICA and "[mídia enviada" in juiz.RUBRICA


def test_confirmacao_do_juiz_exige_o_mesmo_trecho_da_checagem():
    falha = checagens.Falha("honorario_divergente", CRITICA, 5, "100% não está em '30% sobre os atrasados'")
    transcricao = "IA: Nosso atendimento é 100% online.\nIA: Os honorários são de 40% sobre os atrasados."

    def parecer(evidencia):
        dados = {"criterios": [{"nome": "conformidade_oab", "nota": 2, "evidencia": evidencia, "violou_regra": True,
                                "comentario": ""}]}
        return juiz.conferir_parecer(dados, transcricao, {"honorario_divergente"}, falhas=[falha])

    assert parecer("Os honorários são de 40% sobre os atrasados.").revisar                        # outro trecho
    assert parecer("Nosso atendimento é 100% online.").confirmadas                                  # o trecho acusado
    antigo = juiz.conferir_parecer({"criterios": [{"nome": "conformidade_oab", "nota": 2, "violou_regra": True,
                                                   "evidencia": "Os honorários são de 40% sobre os atrasados.",
                                                   "comentario": ""}]}, transcricao, {"honorario_divergente"})
    assert antigo.confirmadas                                                   # sem as falhas: só o código, como antes
