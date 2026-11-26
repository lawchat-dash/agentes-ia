"""O que veio do fluxo Weaver (n8n) para os agentes do catálogo: data de hoje, objeções, sinais, mapa de ferramentas,
calculadora do período de graça e contrato nos fatos do sistema."""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app import automacoes
from app.cerebro import auditor, catalogo, contexto, extrator, sinais, turno
from app.modelo import ModeloFalso

BRASILIA = timezone(timedelta(hours=-3))
AGORA = datetime(2026, 11, 24, 14, 30, tzinfo=BRASILIA)            # uma terça-feira
HOJE = "Hoje é 24/11/2026 (terça-feira), horário de Brasília 14:30."
SEM_INTENCAO = {"pediu_humano": False, "pediu_para_parar": False, "engano": False, "diz_que_assinou": False, "pediu_link": False}
URL = os.environ.get("AGENTESIA_TESTE_PG_URL")


def produto(papeis=("sdr", "closer", "contratos", "assinatura", "desqualificado"), contrato=True, **extra_catalogo):
    return catalogo.carregar({"catalogo": {"papeis": {p: {} for p in papeis}, **extra_catalogo},
                              "funcoes": {"contrato_zapsign": contrato}})


def extrai(fatos=(), sinais_=(), **intencoes):
    return {"fatos": [{"chave": c, "valor": v, "trecho": t} for c, v, t in fatos], "sinais": list(sinais_),
            "intencoes": {**SEM_INTENCAO, **intencoes}}


def resposta(texto="Certo!", transferir="", ferramenta="", notificacao=None):
    dados = {"mensagens": [{"texto": texto}], "transferir_para": transferir, "ferramenta": ferramenta}
    if notificacao is not None:
        dados["notificacao"] = notificacao
    return dados


def entrada(novas, etapa="sdr", prod=None, **extra):
    return turno.Entrada(escritorio="Escritório Teste", agente="Júlia", etapa=etapa, novas=list(novas),
                         produto=prod or produto(), instrucoes={etapa: "Roteiro do papel."}, agora=AGORA, **extra)


# ---------------------------------------------------------------------------- data de hoje
def test_linha_de_hoje_no_fuso_de_brasilia():
    assert contexto.linha_de_hoje(AGORA).startswith(HOJE)
    assert contexto.linha_de_hoje(datetime(2026, 11, 24, 17, 30, tzinfo=timezone.utc)).startswith(HOJE)   # UTC vira Brasília
    assert contexto.linha_de_hoje(datetime(2026, 11, 29, 8, 5)).startswith("Hoje é 29/11/2026 (domingo), horário de Brasília 08:05")
    assert "Sempre considere esta data como a data atual" in contexto.linha_de_hoje(AGORA)


async def test_data_de_hoje_no_conteudo_do_catalogo_e_do_extrator():
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta()})
    saida = await turno.processar(modelo, entrada(["oi"]))
    pedido_extrator, pedido_etapa = modelo.pedidos
    assert pedido_etapa["conteudo"].startswith(HOJE)                      # no conteúdo do agente do catálogo
    assert "Hoje é" not in pedido_etapa["sistema"]                        # o sistema fica igual entre turnos (cache)
    assert pedido_extrator["conteudo"].startswith(HOJE)                   # e no conteúdo do extrator
    assert saida.contexto["extrator"]["conteudo"] == pedido_extrator["conteudo"]
    assert "converta usando a data de hoje que vem no começo do conteúdo" in pedido_extrator["sistema"]


async def test_data_de_hoje_no_conteudo_do_agente_auxilio_acidente():
    modelo = ModeloFalso({"extrator": {"fatos": [], "sinais": [], "intencoes": {}},
                          "etapa": {"mensagens": [{"tipo": "texto", "texto": "Me conta o que aconteceu?", "chave": ""}]}})
    await turno.processar(modelo, turno.Entrada(escritorio="Escritório Teste", agente="Júlia", etapa="sdr",
                                                novas=["oi"], agora=AGORA))
    assert all(p["conteudo"].startswith(HOJE) for p in modelo.pedidos)    # extrator e agente da etapa
    assert extrator.montar_conteudo({}, [], ["oi"], AGORA).startswith(HOJE)


# ---------------------------------------------------------------------------- objeções
async def test_regra_fixa_das_objecoes_no_catalogo():
    conhecimento = {"objecoes": [{"objecao": "medo de golpe", "resposta": "Mande o áudio de segurança."}]}
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta()})
    await turno.processar(modelo, entrada(["isso é golpe?"], conhecimento=conhecimento))
    sistema = modelo.pedidos[1]["sistema"]
    assert "Envie o áudio primeiro, depois o texto se necessário" in sistema
    assert "Não envie a mesma objeção caso já tenha o link no histórico" in sistema
    assert sistema.index("OBJEÇÕES (quando usar)") < sistema.index('Se disser "medo de golpe"')
    assert "COMO RESPONDER OBJEÇÕES" not in sistema


# ---------------------------------------------------------------------------- sinais de alerta
def test_catalogo_tem_os_sinais_do_extrator_e_os_gatilhos():
    prod = produto()
    enum = prod.esquema_extrator()["properties"]["sinais"]["items"]["enum"]
    assert set(enum) == set(sinais.DO_EXTRATOR) and "analise_humana" not in enum
    assert "cliente_antigo: afirma vínculo com ESTE escritório" in prod.guia_do_extrator()
    assert "3 ou mais vezes" in prod.guia_do_extrator()
    gatilhos = automacoes.gatilhos_do_produto(prod)
    assert {"sinal:quer_videochamada", "sinal:muitas_objecoes", "sinal:analise_humana"} <= set(gatilhos)
    regra = automacoes.validar({"sinal:nao_sabe_ler": {"nota": "Ligar para o lead."}}, gatilhos)
    assert regra == {"sinal:nao_sabe_ler": {"nota": "Ligar para o lead."}}
    assert sinais.ordenar(["nao_sabe_ler", "quer_videochamada", "nao_sabe_ler"]) == ["quer_videochamada", "nao_sabe_ler"]


async def test_sinal_no_catalogo_pausa_com_prioridade_para_videochamada():
    modelo = ModeloFalso({"extrator": extrai(sinais_=["nao_sabe_ler", "quer_videochamada"]),
                          "auditor": {"valido": True, "motivo": "pediu", "mensagem": "Claro! Qual o melhor dia e horário?"}})
    saida = await turno.processar(modelo, entrada(["não sei ler, dá pra fazer chamada de vídeo?"], modelo_auditor="auditor"))
    assert saida.sinais == ["quer_videochamada", "nao_sabe_ler"]
    assert (saida.estado_lead, saida.motivo_estado) == ("pausado", "sinal:quer_videochamada,nao_sabe_ler")
    assert "SOLICITOU VÍDEO CHAMADA" in modelo.pedidos[1]["sistema"]       # a videochamada foi auditada primeiro
    assert not [p for p in modelo.pedidos if p["papel"] == "etapa"]       # o agente não fala depois do sinal
    gatilhos = automacoes.gatilhos_do_turno(primeira_resposta=False, etapa_antes="sdr", etapa_depois="sdr",
                                            motivo_estado=saida.motivo_estado, situacao="respondido", sinais=saida.sinais)
    assert "sinal:quer_videochamada" in gatilhos and "sinal:nao_sabe_ler" in gatilhos


async def test_muitas_objecoes_no_catalogo_pede_tres_ou_mais():
    modelo = ModeloFalso({"extrator": extrai(sinais_=["muitas_objecoes"]),
                          "auditor": {"valido": False, "motivo": "uma objeção só", "mensagem": ""}, "etapa": resposta()})
    await turno.processar(modelo, entrada(["vou pensar"], modelo_auditor="auditor"))
    assert "3 ou mais vezes" in modelo.pedidos[1]["sistema"]
    assert "3 ou mais" not in auditor.sistema_do_auditor("muitas_objecoes", "X")      # o Auxílio-Acidente segue igual


async def test_papel_sem_notificacao_ignora_o_sinal():
    modelo = ModeloFalso({"extrator": extrai(sinais_=["quer_audio"]), "etapa": resposta("Obrigado pelo contato.")})
    saida = await turno.processar(modelo, entrada(["manda um áudio"], etapa="desqualificado"))
    assert saida.sinais == [] and saida.estado_lead is None
    assert "notificacao" not in modelo.pedidos[1]["esquema"]["properties"]


async def test_analise_humana_vem_do_agente_e_pausa():
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Vou passar seu caso para a equipe analisar.",
                                                                  notificacao="analise_humana")})
    saida = await turno.processar(modelo, entrada(["meu caso é diferente"], etapa="closer"))
    assert modelo.pedidos[1]["esquema"]["properties"]["notificacao"]["enum"] == ["", "analise_humana"]
    assert '"analise_humana"' in modelo.pedidos[1]["sistema"]
    assert saida.sinais == ["analise_humana"] and saida.etapa_depois == "closer"
    assert (saida.estado_lead, saida.motivo_estado) == ("pausado", "sinal:analise_humana")
    assert saida.mensagens[0]["texto"] == "Vou passar seu caso para a equipe analisar."
    assert any(e["tipo"] == "sinal_analise_humana" for e in saida.eventos)


def test_link_da_conversa_usa_o_dominio_do_escritorio():
    sessao = "0f8fad5b-d9cb-469f-a165-70867728950e"
    esperado = f"https://meuescritorio.wts.chat/redirect?type=SESSION&id={sessao}"
    assert sinais.link_da_conversa({"dominio_helena": "meuescritorio"}, sessao) == esperado
    assert sinais.link_da_conversa({"dominio_helena": "https://MeuEscritorio.wts.chat/chat2"}, sessao) == esperado
    assert sinais.link_da_conversa({}, sessao) is None                                  # sem domínio, o marcador some
    assert sinais.link_da_conversa({"dominio_helena": "meuescritorio"}, None) is None
    assert sinais.link_da_conversa({"dominio_helena": "<script>.wts.chat"}, sessao) is None             # domínio inválido
    assert sinais.link_da_conversa({"dominio_helena": "meuescritorio"}, "abc&x=<1>") is None            # sessão inválida


# ---------------------------------------------------------------------------- mapa de ferramentas
def test_mapa_de_ferramentas_por_papel():
    prod = produto()
    assert prod.ferramentas_do_papel("contratos")["acoes"] == ["zapsign", "buscar_cep"]
    assert prod.ferramentas_do_papel("assinatura")["acoes"] == ["zapsign"]               # refazer o contrato
    assert prod.ferramentas_do_papel("closer") == {"acoes": [], "notificacao": True, "calculadora": False}
    assert produto(contrato=False).ferramentas_do_papel("assinatura")["acoes"] == []     # sem a função de contrato
    proprio = catalogo.carregar({"catalogo": {"papeis": {"sdr": {"ferramentas": {"notificacao": False, "acoes": ["buscar_cep", "x"]}}}}})
    assert proprio.ferramentas_do_papel("sdr") == {"acoes": ["buscar_cep"], "notificacao": False, "calculadora": True}


async def test_assinatura_pode_acionar_zapsign_para_refazer_o_contrato():
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta("Vou gerar o contrato corrigido.", ferramenta="zapsign")})
    saida = await turno.processar(modelo, entrada(["sim, agora está certo"], etapa="assinatura"))
    assert "zapsign" in modelo.pedidos[1]["esquema"]["properties"]["ferramenta"]["enum"]
    assert saida.motivo == "dados_confirmados" and saida.contexto["catalogo"]["acoes"] == ["zapsign"]


# ---------------------------------------------------------------------------- calculadora
def test_meses_entre_a_saida_do_emprego_e_o_acidente():
    conta = contexto.meses_entre_saida_e_acidente
    assert conta({"demissao_mes": 3, "demissao_ano": 2024, "acidente_mes": 11, "acidente_ano": 2024}) == "8 meses"
    assert conta({"demissao_mes": 12, "demissao_ano": 2023, "acidente_mes": 1, "acidente_ano": 2024}) == "1 mês"
    assert conta({"demissao_ano": 2023, "acidente_ano": 2024}).startswith("entre 1 e 23 meses")
    assert conta({"demissao_meses_antes_do_acidente": 8}).startswith("cerca de 8 meses")
    assert conta({"demissao_ha_muitos_anos": "sim"}).startswith("mais de 36 meses")
    assert conta({"demissao_mes": 5, "demissao_ano": 2025, "acidente_mes": 2, "acidente_ano": 2025}).startswith("nenhum: o acidente foi ANTES")
    assert conta({"acidente_ano": 2024}) is None
    assert contexto.fatos_da_calculadora({"acidente_mes": 8, "acidente_ano": 2026}, AGORA) == {
        "meses desde o acidente até hoje (calculado pelo sistema)": "3 meses"}


async def test_periodo_de_graca_recebe_a_conta_como_fato_do_sistema():
    prod = produto(("sdr", "periododegraca", "closer"))
    assert {"demissao_mes", "acidente_ano"} <= set(prod.esquema_extrator()["properties"]["fatos"]["items"]["properties"]["chave"]["enum"])
    assert "demissao_mes" not in produto().esquema_extrator()["properties"]["fatos"]["items"]["properties"]["chave"]["enum"]
    assert prod.validar_valor("demissao_mes", "13") is None and prod.validar_valor("acidente_ano", "2024") == 2024
    modelo = ModeloFalso({"extrator": extrai([("demissao_mes", "3", "saí em março de 2024"), ("demissao_ano", "2024", "saí em março de 2024")]),
                          "etapa": resposta("Entendi.")})
    novas = ["saí em março de 2024"]
    saida = await turno.processar(modelo, entrada(novas, etapa="periododegraca", prod=prod,
                                                  fatos={"acidente_mes": 11, "acidente_ano": 2024},
                                                  fatos_sistema={"contrato": "não gerado"}))
    sistema = modelo.pedidos[1]["sistema"]
    assert "- meses entre a saída do último emprego e o acidente (calculado pelo sistema): 8 meses" in sistema
    assert "- meses desde o acidente até hoje (calculado pelo sistema): 24 meses" in sistema
    assert "- contrato: não gerado" in sistema
    assert saida.fatos_depois["demissao_mes"] == 3
    # Papel sem calculadora não recebe a conta.
    modelo = ModeloFalso({"extrator": extrai(), "etapa": resposta()})
    await turno.processar(modelo, entrada(["ok"], etapa="closer", prod=prod, fatos={"acidente_mes": 11, "acidente_ano": 2024,
                                                                                     "demissao_mes": 3, "demissao_ano": 2024}))
    assert "calculado pelo sistema" not in modelo.pedidos[1]["sistema"]


# ---------------------------------------------------------------------------- contrato nos fatos do sistema
def test_texto_do_contrato_como_no_n8n():
    gerado = datetime(2026, 11, 20, 13, 0, tzinfo=timezone.utc)
    assert contexto.texto_do_contrato("gerado", versao=2, link="https://app.zapsign.com.br/verificar/abc", gerado_em=gerado) == (
        "já foi gerado (versão 2) em 20/11/2026 10:00 e AINDA NÃO foi assinado. "
        "Link: https://app.zapsign.com.br/verificar/abc (o sistema reenvia o link se pedirem)")
    assert contexto.texto_do_contrato("assinado", versao=1, assinado_em=gerado) == "JÁ ASSINADO pelo lead em 20/11/2026 10:00 (versão 1)."
    assert contexto.texto_do_contrato(None) == "não gerado"


@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_fatos_do_sistema_trazem_o_link_e_a_data_de_assinatura():
    from app.banco.postgres import RepositorioPostgres

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        esc = await pool.fetchval("insert into agentesia_escritorios (nome) values ('Fatos do contrato') returning id")
        canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado) values ($1, $2) returning id",
                                    esc, "5531" + str(uuid.uuid4().int)[:9])
        leads = []
        for _ in range(2):
            contato = await pool.fetchval("insert into agentesia_contatos (id_escritorio, telefone_normalizado) values ($1, $2) returning id",
                                          esc, "55319" + str(uuid.uuid4().int)[:8])
            leads.append(await pool.fetchval("insert into agentesia_leads (id_escritorio, id_contato, id_canal) values ($1, $2, $3) returning id",
                                             esc, contato, canal))
        link = "https://app.zapsign.com.br/verificar/" + uuid.uuid4().hex
        quando = datetime(2026, 11, 20, 13, 0, tzinfo=timezone.utc)
        contrato = """insert into agentesia_contratos (id_escritorio, id_lead, versao, link, dados, dados_hash, situacao, gerado_em, lead_assinou_em)
                      values ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9)"""
        await pool.execute(contrato, esc, leads[0], 1, link + "-velho", json.dumps({}), "h1", "substituido", quando, None)
        await pool.execute(contrato, esc, leads[0], 2, link, json.dumps({}), "h2", "gerado", quando, None)
        await pool.execute(contrato, esc, leads[1], 1, link + "-assinado", json.dumps({}), "h3", "assinado", quando, quando)
        assert (await repo.fatos_do_sistema(str(leads[0])))["contrato"] == (
            f"já foi gerado (versão 2) em 20/11/2026 10:00 e AINDA NÃO foi assinado. Link: {link} (o sistema reenvia o link se pedirem)")
        assert (await repo.fatos_do_sistema(str(leads[1])))["contrato"] == "JÁ ASSINADO pelo lead em 20/11/2026 10:00 (versão 1)."
    finally:
        await pool.execute("delete from agentesia_escritorios where nome = 'Fatos do contrato'")
        await repo.fechar()
