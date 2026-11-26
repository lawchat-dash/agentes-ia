"""Alertas à equipe de ponta a ponta (antiga tool "Sistema Notificação" + fluxo "Alerta Notificação" do n8n).

Cada alerta do n8n: detecção (extrator/agente/contrato) -> auditor -> evento sinal_<x> -> nota no atendimento ->
gatilho sinal:<x> -> preparar_aviso -> notificar (WhatsApp à equipe, pelo número não oficial da conta).
Contra spam: o mesmo aviso para o mesmo lead sai 1 vez na janela (12 h, config "avisos_janela_h").
"""

import json
import os
import uuid

import httpx
import pytest

from app import automacoes, notificacoes
from app.acoes import Executor
from app.banco.postgres import RepositorioPostgres
from app.canal.helena_conta import HelenaConta
from app.cerebro import auditor, auxilio_acidente, sinais
from tests.test_pipeline import montar, webhook
from tests.test_turno import extrai, fala

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")

# Código do n8n (Tipo de Notificação) -> sinal do motor.
DO_N8N = {"videochamada": "quer_videochamada", "leadquerreceberaudio": "quer_audio", "naosabeler": "nao_sabe_ler",
          "clienteantigo": "cliente_antigo", "outrobeneficio": "outro_beneficio",
          "dificuldadenaassinatura": "dificuldade_assinatura", "fotodocontrato": "foto_contrato",
          "muitasobjecoes": "muitas_objecoes", "enderecosemfalar": "endereco_sem_falar",
          "contratomanual": "contrato_manual", "analisehumana": "analise_humana"}


# ----------------------------------------------------------------------------- 1. todo tipo do n8n tem caminho
def test_todo_alerta_do_n8n_tem_sinal_auditor_nome_e_evento():
    for codigo, sinal in DO_N8N.items():
        assert sinal in sinais.SINAIS, codigo                                   # catálogo
        assert sinal in automacoes.NOMES_SINAIS, codigo                         # nota legível
        assert f"sinal:{sinal}" in notificacoes.NOMES_DE_EVENTO, codigo         # cabeçalho do aviso
        if sinal != "analise_humana":                                           # esse o agente marca pelo roteiro
            assert sinal in auditor.PARTES and sinal in auxilio_acidente.SINAIS, codigo
            assert sinal in sinais.DO_EXTRATOR, codigo
    guia = sinais.guia_do_extrator("BPC/LOAS")
    for sinal in ("foto_contrato", "endereco_sem_falar", "contrato_manual"):
        assert f"- {sinal}" in guia
    # Troca de etapa (closer, contratos, assinatura, assinado) também tem nome no aviso.
    for etapa in ("closer", "contratos", "assinatura", "contrato_assinado", "desqualificado"):
        assert not notificacoes.nome_do_evento(f"etapa:{etapa}").startswith("etapa")


def test_sinais_do_contrato_so_nos_papeis_do_contrato():
    sdr = sinais.do_papel(sinais.SINAIS, {"notificacao": True, "acoes": []})
    contratos = sinais.do_papel(sinais.SINAIS, {"notificacao": True, "acoes": ["zapsign", "buscar_cep"]})
    assert "foto_contrato" not in sdr and "contrato_manual" not in sdr and "endereco_sem_falar" not in sdr
    assert "nao_sabe_ler" in sdr and "dificuldade_assinatura" in sdr
    assert {"foto_contrato", "contrato_manual", "endereco_sem_falar"} <= set(contratos)
    assert sinais.do_papel(sinais.SINAIS, {"notificacao": False, "acoes": ["zapsign"]}) == ()


def test_janela_mesmo_fato_e_numero_de_envio():
    assert notificacoes.janela_do_aviso_h({}) == 12
    assert notificacoes.janela_do_aviso_h({"avisos_janela_h": 0}) == 0
    assert notificacoes.janela_do_aviso_h({"avisos_janela_h": "x"}) == 12
    assert notificacoes.eventos_do_mesmo_fato("contrato_assinado") == ["contrato_assinado", "etapa:contrato_assinado"]
    assert notificacoes.eventos_do_mesmo_fato("etapa:contrato_assinado") == ["contrato_assinado", "etapa:contrato_assinado"]
    assert notificacoes.eventos_do_mesmo_fato("sinal:nao_sabe_ler") == ["sinal:nao_sabe_ler"]
    assert notificacoes.canal_envia_aviso("nao_oficial", "ZAPI_WhatsApp")
    assert notificacoes.canal_envia_aviso("nao_oficial", None)
    assert not notificacoes.canal_envia_aviso("oficial", None)
    assert not notificacoes.canal_envia_aviso("nao_oficial", "CloudAPI_WhatsApp")
    assert not notificacoes.canal_envia_aviso("nao_oficial", "Instagram")
    assert "não oficial em Avisos no WhatsApp" in notificacoes.TEXTO_NUMERO_OFICIAL


# ----------------------------------------------------------------------------- 2. turno: válido pausa e avisa
AUDITOR_OK = {"valido": True, "motivo": "pediu", "mensagem": "Combinado! A equipe vai te ajudar por aqui."}
AUDITOR_NAO = {"valido": False, "motivo": "não pediu", "mensagem": "x"}


@pytest.mark.parametrize("sinal", auxilio_acidente.SINAIS)
async def test_auditor_confere_cada_sinal_e_a_chamada_entra_no_custo(sinal):
    from app.cerebro import turno
    from app.modelo import ModeloFalso
    from tests.test_turno import entrada

    modelo = ModeloFalso({"extrator": extrai(sinais=[sinal]), "auditor": AUDITOR_OK})
    saida = await turno.processar(modelo, entrada(["preciso de ajuda"], modelo_auditor="gpt-6-luna"))
    assert saida.estado_lead == "pausado" and saida.sinais == [sinal]
    assert saida.mensagens[0]["texto"] == AUDITOR_OK["mensagem"]
    assert any(e["tipo"] == f"sinal_{sinal}" for e in saida.eventos)
    assert any(c.papel == "auditor" for c in saida.chamadas)                  # vai para agentesia_chamadas_ia

    modelo = ModeloFalso({"extrator": extrai(sinais=[sinal]), "auditor": AUDITOR_NAO, "etapa": fala("Certo, e quando foi?")})
    saida = await turno.processar(modelo, entrada(["preciso de ajuda"], modelo_auditor="gpt-6-luna"))
    assert saida.estado_lead is None and saida.sinais == [] and saida.mensagens[0]["texto"] == "Certo, e quando foi?"


@pytest.mark.parametrize("sinal", auxilio_acidente.SINAIS)
async def test_sinal_confirmado_no_atendimento_pausa_anota_e_pede_o_aviso(sinal):
    atendimento, repo, helena = montar({"extrator": extrai(sinais=[sinal]), "etapa": fala("Certo!")})
    repo.agentes["canal-1"].config.update({"funcoes": {"avisos": True}})
    repo.avisos = {"esc-1": {f"sinal:{sinal}"}}
    await atendimento.receber(webhook("preciso de ajuda"))
    await atendimento.aguardar_esperas()
    lead = next(iter(repo.leads.values()))
    assert lead.estado == "pausado" and helena.enviadas                       # a IA manda a mensagem e sai
    assert [a["dados"]["evento"] for a in repo.acoes if a["tipo"] == "preparar_aviso"] == [f"sinal:{sinal}"]
    notas = [a["dados"]["texto"] for a in repo.acoes if a["tipo"] == "nota"]
    assert any(automacoes.NOMES_SINAIS[sinal] in n and "IA saiu da conversa" in n for n in notas)
    assert any(e["tipo"] == f"sinal_{sinal}" for e in repo.eventos)


# ----------------------------------------------------------------------------- 3. executor (Postgres)
async def _cenario(pool, *, tipo_canal="nao_oficial", config=None):
    segredo = await pool.fetchval("select vault.create_secret('token-alertas', 'teste')")
    esc = await pool.fetchval("insert into agentesia_escritorios (nome, config) values ('Alertas', $1::jsonb) returning id",
                              json.dumps(config or {}))
    await pool.execute("insert into agentesia_integracoes (id_escritorio, tipo, id_segredo_vault, situacao) "
                       "values ($1, 'helena', $2, 'ok')", esc, segredo)
    numero = "5511" + str(uuid.uuid4().int)[:9]
    canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado, tipo) values ($1, $2, $3) "
                                "returning id", esc, numero, tipo_canal)
    contato = await pool.fetchval("insert into agentesia_contatos (id_escritorio, nome, telefone_normalizado) "
                                  "values ($1, 'Rosa', '5511966665555') returning id", esc)
    lead = await pool.fetchval("insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_sessao_helena) "
                               "values ($1, $2, $3, 'sessao-alerta') returning id", esc, contato, canal)
    await pool.execute(
        """insert into agentesia_notificacoes (id_escritorio, tipo_evento, nome, modelo_mensagem, destinatarios)
           values ($1, 'sinal:nao_sabe_ler', 'Não sabe ler', $2, $3::jsonb)""", esc, notificacoes.MODELO_PADRAO,
        json.dumps([{"rotulo": "Dra. Ana", "numero": "(11) 91111-2222"}]))
    return esc, lead, numero


def _executor(pool, enviados):
    def helena(pedido: httpx.Request) -> httpx.Response:
        if pedido.url.path == "/chat/v1/message/send":
            corpo = json.loads(pedido.content)
            enviados.append((corpo["from"], corpo["to"], corpo["body"]["text"]))
            return httpx.Response(200, json={"id": f"msg-{len(enviados)}"})
        return httpx.Response(200, json={})
    return Executor(pool, "https://api.helena.run", helena_por_token=lambda token, url: HelenaConta(
        token, url, httpx.AsyncClient(transport=httpx.MockTransport(helena))))


async def _rodar(executor, vezes=4):
    for _ in range(vezes):
        if not await executor.rodar_uma_vez():
            break


async def _aviso(repo, esc, lead, chave):
    await repo.enfileirar_acoes(id_escritorio=str(esc), id_lead=str(lead), id_turno=None, acoes=[
        {"tipo": "preparar_aviso", "chave_unica": f"{lead}:{chave}:aviso", "dados": {"evento": "sinal:nao_sabe_ler"}}])


@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_um_aviso_por_tipo_e_lead_na_janela():
    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        await pool.execute("update agentesia_acoes set situacao = 'cancelada' where situacao in ('pendente', 'executando')")
        esc, lead, numero = await _cenario(pool)
        enviados = []
        executor = _executor(pool, enviados)
        await _aviso(repo, esc, lead, "t1")
        await _rodar(executor)
        await _aviso(repo, esc, lead, "t2")                     # mesmo sinal, outro turno, minutos depois
        await _rodar(executor)
        assert len(enviados) == 1 and enviados[0][0] == numero and enviados[0][1] == "5511911112222"
        segundo = await pool.fetchval("select resultado->>'motivo' from agentesia_acoes where chave_unica = $1", f"{lead}:t2:aviso")
        assert segundo == "aviso_repetido_na_janela"
        # Escritório sem janela: sai de novo.
        await pool.execute("update agentesia_escritorios set config = '{\"avisos_janela_h\": 0}'::jsonb where id = $1", esc)
        await _aviso(repo, esc, lead, "t3")
        await _rodar(executor)
        assert len(enviados) == 2
    finally:
        await repo.fechar()


@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_numero_oficial_nao_envia_e_avisa_uma_vez():
    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        await pool.execute("update agentesia_acoes set situacao = 'cancelada' where situacao in ('pendente', 'executando')")
        esc, lead, _ = await _cenario(pool, tipo_canal="oficial", config={"avisos_janela_h": 0})
        enviados = []
        executor = _executor(pool, enviados)
        await _aviso(repo, esc, lead, "o1")
        await _aviso(repo, esc, lead, "o2")
        await _rodar(executor, 6)
        assert not [e for e in enviados if e[1] == "5511911112222"]            # nenhum aviso pelo número oficial
        eventos = await pool.fetch("select descricao from agentesia_eventos where id_escritorio = $1 and tipo = 'aviso_numero_oficial'", esc)
        assert len(eventos) == 1 and "não oficial em Avisos no WhatsApp" in eventos[0]["descricao"]
        notas = await pool.fetchval("select count(*) from agentesia_acoes where id_lead = $1 and chave_unica = $2",
                                    lead, f"{lead}:aviso_numero_oficial")
        assert notas == 1
        assert not await pool.fetchval("select count(*) from agentesia_acoes where id_escritorio = $1 and situacao = 'falhou'", esc)

        # Com um número não oficial na conta, o aviso sai por ele (mesmo o lead sendo do número oficial).
        outro = "5511" + str(uuid.uuid4().int)[:9]
        await pool.execute("insert into agentesia_canais (id_escritorio, numero_normalizado, tipo, tipo_helena) "
                           "values ($1, $2, 'nao_oficial', 'ZAPI_WhatsApp')", esc, outro)
        await _aviso(repo, esc, lead, "o3")
        await _rodar(executor)
        assert [e[0] for e in enviados if e[1] == "5511911112222"] == [outro]
    finally:
        await repo.fechar()


@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_dificuldade_na_assinatura_pelo_contrato_anota_e_avisa():
    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        await pool.execute("update agentesia_acoes set situacao = 'cancelada' where situacao in ('pendente', 'executando')")
        esc, lead, _ = await _cenario(pool)
        await pool.execute(
            """insert into agentesia_notificacoes (id_escritorio, tipo_evento, nome, modelo_mensagem, destinatarios)
               values ($1, 'sinal:dificuldade_assinatura', 'Assinatura', $2, $3::jsonb)""", esc, notificacoes.MODELO_PADRAO,
            json.dumps([{"rotulo": "Dra. Ana", "numero": "(11) 91111-2222"}]))
        enviados = []
        executor = _executor(pool, enviados)
        contexto = {"id_escritorio": str(esc), "lead": {"id": str(lead)}}
        dados_lead = {"id": str(lead), "id_sessao_helena": "sessao-alerta", "config_agente": {"funcoes": {"avisos": True}}}
        contrato = {"id": str(uuid.uuid4()), "versao": 1}
        await executor._dificuldade_na_assinatura(contexto, dados_lead, contrato)
        await executor._dificuldade_na_assinatura(contexto, dados_lead, contrato)       # de novo: não repete
        await _rodar(executor)
        assert len([e for e in enviados if e[1] == "5511911112222"]) == 1
        assert "Dificuldade na assinatura" in enviados[0][2]
        notas = await pool.fetch("select dados->>'texto' as t from agentesia_acoes where id_lead = $1 and tipo = 'nota'", lead)
        assert len([n for n in notas if "Dificuldade na assinatura" in n["t"]]) == 1
        assert await pool.fetchval("select count(*) from agentesia_eventos where id_lead = $1 and tipo = 'sinal_dificuldade_assinatura'",
                                   lead) == 1
    finally:
        await repo.fechar()
