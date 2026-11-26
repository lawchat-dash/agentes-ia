"""Pontas soltas dos avisos à equipe e da API do painel.

- O aviso leva o link da conversa na Helena do escritório e o que o lead escreveu no turno.
- O sinal analise_humana tem nome legível nos gatilhos e nos avisos.
- O aviso do sinal sai mesmo quando o agente não tem automação nenhuma (e sai uma vez só quando tem).
- gerar() aceita max_tokens (a ficha de memória pede 500, como no n8n).
- GET /api/conversas/{id} traz url_midia e a ficha de memória; GET /api/conversas filtra por agente;
  o domínio da Helena do escritório é gravado (normalizado) por quem gere o escritório.
"""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

from app import automacoes, memoria, notificacoes
from app.acoes import Executor
from app.banco.postgres import RepositorioPostgres
from app.canal.helena_conta import HelenaConta
from app.modelo import ModeloFalso, ModeloOpenAI, ModeloPorNome
from tests.test_conversas_tela import _escritorio_com_agente, _lead, ambiente  # noqa: F401  (ambiente é fixture)
from tests.test_gestao import _entrar
from tests.test_modelo import ESQUEMA, ClienteFalso, ClienteGptFalso, resposta, resposta_gpt
from tests.test_pipeline import montar, webhook
from tests.test_turno import extrai, fala

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")


# ----------------------------------------------------------------------------- 1. texto do aviso
def test_aviso_leva_link_da_conversa_e_mensagem_do_lead():
    valores = notificacoes.valores_do_aviso(
        evento="sinal:quer_videochamada", nome="Maria", telefone="5511977776666", produto=None, etapa=None,
        link_conversa="https://advmidia.wts.chat/redirect?type=SESSION&id=s-1", mensagem_lead="dá pra ser por vídeo?")
    texto = notificacoes.renderizar_modelo(notificacoes.MODELO_PADRAO, valores)
    assert "Mensagem do lead: dá pra ser por vídeo?" in texto
    assert "Conversa: https://advmidia.wts.chat/redirect?type=SESSION&id=s-1" in texto
    assert "mensagem_lead" in notificacoes.MARCADORES and "link_conversa" in notificacoes.MARCADORES
    # Sem link nem mensagem, as linhas somem do aviso.
    vazio = notificacoes.renderizar_modelo(notificacoes.MODELO_PADRAO, notificacoes.valores_do_aviso(
        evento="lead_novo", nome="Maria", telefone=None, produto=None, etapa=None))
    assert "Mensagem do lead" not in vazio and "Conversa:" not in vazio
    # Mensagem comprida vai cortada.
    longa = notificacoes.valores_do_aviso(evento="x", nome=None, telefone=None, produto=None, etapa=None,
                                          mensagem_lead="a" * 2000)["mensagem_lead"]
    assert len(longa) == notificacoes.LIMITE_MENSAGEM_LEAD and longa.endswith("…")


# ----------------------------------------------------------------------------- 2. nome do analise_humana
def test_analise_humana_tem_nome_legivel():
    assert notificacoes.NOMES_DE_EVENTO["sinal:analise_humana"] == "Pediu análise humana"
    assert "analise_humana" in automacoes.NOMES_SINAIS
    produto = SimpleNamespace(etapas=[], intencoes=[], sinais=("nao_sabe_ler", "analise_humana"))
    gatilhos = automacoes.gatilhos_do_produto(produto)
    assert gatilhos["sinal:analise_humana"] == "Lead pede análise humana do caso (marcado pelo agente)"
    assert gatilhos["sinal:nao_sabe_ler"] == "Lead diz que não sabe ler (confirmado pelo auditor)"


# ----------------------------------------------------------------------------- 3. aviso do sinal sem automações
AUDITOR_OK = {"valido": True, "motivo": "disse que não sabe ler", "mensagem": "Sem problema! Vou pedir para a equipe te ligar."}


async def _turno_com_sinal(config_agente, avisos):
    atendimento, repo, _helena = montar({"extrator": extrai(sinais=["nao_sabe_ler"]), "auditor": AUDITOR_OK,
                                         "etapa": fala("Certo!")})
    repo.agentes["canal-1"].config.update(config_agente)
    repo.avisos = {"esc-1": set(avisos)}
    await atendimento.receber(webhook("eu nao sei ler"))
    await atendimento.aguardar_esperas()
    return repo


async def test_aviso_do_sinal_sai_sem_automacoes_configuradas():
    repo = await _turno_com_sinal({"funcoes": {"avisos": True}}, {"sinal:nao_sabe_ler"})
    avisos = [a for a in repo.acoes if a["tipo"] == "preparar_aviso"]
    assert [a["dados"]["evento"] for a in avisos] == ["sinal:nao_sabe_ler"]


async def test_aviso_do_sinal_nao_duplica_com_automacoes():
    config = {"funcoes": {"avisos": True}, "automacoes": {"sinal:nao_sabe_ler": {"nota": "Ligar para o lead."}}}
    repo = await _turno_com_sinal(config, {"sinal:nao_sabe_ler"})
    assert [a["dados"]["evento"] for a in repo.acoes if a["tipo"] == "preparar_aviso"] == ["sinal:nao_sabe_ler"]
    assert [a["tipo"] for a in repo.acoes if a["tipo"] == "nota"] == ["nota"]


async def test_sem_funcao_de_avisos_nao_avisa():
    repo = await _turno_com_sinal({"funcoes": {}}, {"sinal:nao_sabe_ler"})
    assert not [a for a in repo.acoes if a["tipo"] == "preparar_aviso"]


# ----------------------------------------------------------------------------- 4. max_tokens
async def test_gerar_aceita_max_tokens():
    gpt = ClienteGptFalso([resposta_gpt(), resposta_gpt()])
    await ModeloOpenAI(gpt).gerar(papel="extrator", sistema="s", conteudo="c", esquema=ESQUEMA, modelo="gpt-4.1")
    await ModeloOpenAI(gpt).gerar(papel="extrator", sistema="s", conteudo="c", esquema=ESQUEMA, modelo="gpt-4.1",
                                  max_tokens=500)
    assert [p["max_completion_tokens"] for p in gpt.pedidos] == [4000, 500]

    from app.modelo import ModeloAnthropic

    claude = ClienteFalso([resposta(), resposta()])
    await ModeloAnthropic(claude).gerar(papel="extrator", sistema="s", conteudo="c", esquema=ESQUEMA, modelo="claude-opus-5-5")
    await ModeloAnthropic(claude).gerar(papel="extrator", sistema="s", conteudo="c", esquema=ESQUEMA, modelo="claude-opus-5-5",
                                        max_tokens=500)
    assert [p["max_tokens"] for p in claude.pedidos] == [16000, 500]

    # O roteador por nome repassa o teto ao provedor.
    por_nome = ModeloPorNome()
    gpt2 = ClienteGptFalso([resposta_gpt()])
    por_nome._provedores["openai"] = ModeloOpenAI(gpt2)
    await por_nome.gerar(papel="resumo_conversa", sistema="s", conteudo="c", esquema=ESQUEMA, modelo="gpt-4.1-mini",
                         max_tokens=500)
    assert gpt2.pedidos[0]["max_completion_tokens"] == 500


async def test_ficha_de_memoria_pede_500_tokens():
    assert memoria._extras_do_modelo(ModeloPorNome()) == {"temperatura": 0.2, "max_tokens": 500}

    class Repo:
        async def trecho_para_resumir(self, *_a, **_k):
            return {"resumo": None, "mensagens": [{"id": "m1", "autor": "lead", "texto": "caí da moto"}]}

        async def gravar_resumo(self, **_k):
            pass

    modelo = ModeloFalso({"resumo_conversa": {"resumo": "Lead caiu da moto."}})
    await memoria.resumir(Repo(), modelo, "lead-1")
    assert modelo.pedidos[0]["max_tokens"] == 500 and modelo.pedidos[0]["temperatura"] == 0.2


# ----------------------------------------------------------------------------- 1. aviso de verdade (Postgres)
@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_aviso_monta_link_e_mensagens_do_turno():
    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        await pool.execute("update agentesia_acoes set situacao = 'cancelada' where situacao in ('pendente', 'executando')")
        segredo = await pool.fetchval("select vault.create_secret('token-link', 'teste')")
        esc = await pool.fetchval("insert into agentesia_escritorios (nome, config) values ('Link', $1::jsonb) returning id",
                                  json.dumps({"dominio_helena": "advmidia"}))
        await pool.execute("insert into agentesia_integracoes (id_escritorio, tipo, id_segredo_vault, situacao) "
                           "values ($1, 'helena', $2, 'ok')", esc, segredo)
        canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado) values ($1, $2) returning id",
                                    esc, "5511" + str(uuid.uuid4().int)[:9])
        contato = await pool.fetchval("insert into agentesia_contatos (id_escritorio, nome, telefone_normalizado) "
                                      "values ($1, 'Rosa', '5511966665555') returning id", esc)
        lead = await pool.fetchval("insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_sessao_helena) "
                                   "values ($1, $2, $3, 'sessao-abc-1') returning id", esc, contato, canal)
        turno = await pool.fetchval("insert into agentesia_turnos (id_escritorio, id_lead, modo) values ($1, $2, 'producao') "
                                    "returning id", esc, lead)
        agora = datetime.now(timezone.utc)
        await pool.executemany(
            """insert into agentesia_mensagens (id_escritorio, id_lead, id_turno, autor, tipo, texto, texto_extraido, enviada_em)
               values ($1, $2, $3, $4, $5, $6, $7, $8)""",
            [(esc, lead, None, "lead", "texto", "mensagem antiga", None, agora - timedelta(hours=1)),
             (esc, lead, turno, "lead", "texto", "oi", None, agora - timedelta(minutes=2)),
             (esc, lead, turno, "lead", "audio", None, "dá pra ser por chamada de vídeo?", agora - timedelta(minutes=1)),
             (esc, lead, turno, "ia", "texto", "Claro! Vou chamar a equipe.", None, agora)])
        await pool.execute(
            """insert into agentesia_notificacoes (id_escritorio, tipo_evento, nome, modelo_mensagem, destinatarios)
               values ($1, 'sinal:quer_videochamada', 'Videochamada', $2, $3::jsonb)""", esc, notificacoes.MODELO_PADRAO,
            json.dumps([{"rotulo": "Dra. Ana", "numero": "(11) 91111-2222"}]))
        config = {"funcoes": {"avisos": True}}
        acoes = automacoes.montar_acoes(config, None, ["sinal:quer_videochamada"], id_lead=str(lead), id_turno=str(turno),
                                        avisos={"sinal:quer_videochamada"})
        await repo.enfileirar_acoes(id_escritorio=str(esc), id_lead=str(lead), id_turno=str(turno), acoes=acoes)
        # Aviso sem turno (contrato assinado...): vai a última mensagem do lead.
        await repo.enfileirar_acoes(id_escritorio=str(esc), id_lead=str(lead), id_turno=None, acoes=[
            {"tipo": "preparar_aviso", "chave_unica": f"{lead}:sem-turno:aviso", "dados": {"evento": "sinal:quer_videochamada"}}])

        enviados = []

        def helena(pedido: httpx.Request) -> httpx.Response:
            if pedido.url.path == "/chat/v1/message/send":
                enviados.append(json.loads(pedido.content)["body"]["text"])
                return httpx.Response(200, json={"id": f"msg-{len(enviados)}"})
            return httpx.Response(404)

        executor = Executor(pool, "https://api.helena.run", helena_por_token=lambda token, url: HelenaConta(
            token, url, httpx.AsyncClient(transport=httpx.MockTransport(helena))))
        await executor.rodar_uma_vez()                     # prepara
        await executor.rodar_uma_vez()                     # envia
        assert len(enviados) == 2
        do_turno = next(t for t in enviados if "oi\n" in t)
        assert "Lead pediu videochamada" in do_turno
        assert "Mensagem do lead: oi\ndá pra ser por chamada de vídeo?" in do_turno and "antiga" not in do_turno
        assert "Conversa: https://advmidia.wts.chat/redirect?type=SESSION&id=sessao-abc-1" in do_turno
        sem_turno = next(t for t in enviados if t is not do_turno)
        assert "Mensagem do lead: dá pra ser por chamada de vídeo?" in sem_turno

        # Sem domínio cadastrado, a linha do link some.
        await pool.execute("update agentesia_escritorios set config = '{}'::jsonb where id = $1", esc)
        await repo.enfileirar_acoes(id_escritorio=str(esc), id_lead=str(lead), id_turno=None, acoes=[
            {"tipo": "preparar_aviso", "chave_unica": f"{lead}:sem-dominio:aviso", "dados": {"evento": "sinal:quer_videochamada"}}])
        await executor.rodar_uma_vez()
        await executor.rodar_uma_vez()
        assert len(enviados) == 3 and "Conversa:" not in enviados[-1]
    finally:
        await repo.fechar()


# ----------------------------------------------------------------------------- 5. API do painel
async def test_conversa_traz_midia_e_ficha_e_lista_filtra_por_agente(ambiente):  # noqa: F811
    cliente, email_admin, banco = ambiente
    pool = banco._pool
    await _entrar(cliente, email_admin, "senha-admin-123")
    id_escritorio, id_canal, id_agente, h = await _escritorio_com_agente(cliente, "Painel Ltda")
    id_lead = await _lead(pool, id_escritorio, id_canal, id_agente, nome="Carla", telefone="5511" + str(uuid.uuid4().int)[:9])
    await pool.execute(
        """insert into agentesia_mensagens (id_escritorio, id_lead, autor, tipo, texto, texto_extraido, url_midia, enviada_em)
           values ($1::uuid, $2::uuid, 'lead', 'imagem', null, 'foto do laudo', 'https://midia.exemplo/laudo.jpg', now())""",
        id_escritorio, id_lead)

    conversa = (await cliente.get(f"/api/conversas/{id_lead}", headers=h)).json()
    assert conversa["mensagens"][0]["url_midia"] == "https://midia.exemplo/laudo.jpg"
    assert conversa["memoria"] is None                                  # ainda sem ficha

    await pool.execute(
        """insert into agentesia_lead_resumo (id_lead, id_escritorio, resumo, mensagens_resumidas)
           values ($1::uuid, $2::uuid, 'Carla caiu da escada em 2024.', 32)""", id_lead, id_escritorio)
    ficha = (await cliente.get(f"/api/conversas/{id_lead}", headers=h)).json()["memoria"]
    assert (ficha["resumo"], ficha["mensagens_resumidas"]) == ("Carla caiu da escada em 2024.", 32) and ficha["atualizado_em"]

    # Segundo agente no mesmo escritório, com o próprio lead: o filtro separa.
    outro_canal = await pool.fetchval(
        "insert into agentesia_canais (id_escritorio, numero_normalizado) values ($1::uuid, $2) returning id",
        id_escritorio, "5521" + str(uuid.uuid4().int)[:9])
    outro_agente = (await cliente.post("/api/agentes", headers=h, json={"nome": "Bia", "id_canal": str(outro_canal)})).json()
    lead_bia = await _lead(pool, id_escritorio, str(outro_canal), outro_agente["id"], nome="Davi",
                           telefone="5521" + str(uuid.uuid4().int)[:9])
    todas = (await cliente.get("/api/conversas", headers=h)).json()
    assert {c["id"]: c["id_agente"] for c in todas} == {id_lead: id_agente, lead_bia: outro_agente["id"]}
    so_julia = (await cliente.get("/api/conversas", params={"id_agente": id_agente}, headers=h)).json()
    assert [c["id"] for c in so_julia] == [id_lead]
    so_bia = (await cliente.get("/api/conversas", params={"id_agente": outro_agente["id"], "busca": "davi"}, headers=h)).json()
    assert [c["id"] for c in so_bia] == [lead_bia]
    assert (await cliente.get("/api/conversas", params={"id_agente": str(uuid.uuid4())}, headers=h)).json() == []
    assert (await cliente.get("/api/conversas", params={"id_agente": "x'; drop"}, headers=h)).status_code == 400


async def test_dominio_da_helena_do_escritorio(ambiente):  # noqa: F811
    cliente, email_admin, _banco = ambiente
    await _entrar(cliente, email_admin, "senha-admin-123")
    id_escritorio, _canal, _agente, h = await _escritorio_com_agente(cliente, "Domínio Ltda")

    # A equipe LawChat grava; aceita nome curto, endereço ou URL inteira e guarda só o endereço.
    for valor in ("advmidia", "AdvMidia.wts.chat", "https://advmidia.wts.chat/chat2/sessao"):
        salvo = (await cliente.patch("/api/escritorio", headers=h, json={"dominio_helena": valor})).json()
        assert salvo["config"]["dominio_helena"] == "advmidia.wts.chat", valor
    assert (await cliente.get("/api/escritorio", headers=h)).json()["config"]["dominio_helena"] == "advmidia.wts.chat"

    # Quem gere o escritório também grava; o atendente não.
    como_gestor = {**h, "x-visao": "gestor"}
    salvo = (await cliente.patch("/api/escritorio", headers=como_gestor, json={"dominio_helena": "meuescritorio.wts.chat"})).json()
    assert salvo["config"]["dominio_helena"] == "meuescritorio.wts.chat"
    assert (await cliente.patch("/api/escritorio", headers={**h, "x-visao": "atendente"},
                                json={"dominio_helena": "outro"})).status_code == 403

    # Inválido é recusado sem mexer no que estava; vazio apaga.
    ruim = await cliente.patch("/api/escritorio", headers=h, json={"dominio_helena": "<script>"})
    assert ruim.status_code == 400 and "Domínio da Helena" in ruim.json()["detail"]
    assert (await cliente.get("/api/escritorio", headers=h)).json()["config"]["dominio_helena"] == "meuescritorio.wts.chat"
    # Mudar outra coisa não apaga o domínio.
    assert (await cliente.patch("/api/escritorio", headers=h, json={"honorarios": "30%"})).json()["config"]["dominio_helena"]
    apagado = (await cliente.patch("/api/escritorio", headers=h, json={"dominio_helena": "  "})).json()
    assert "dominio_helena" not in apagado["config"]
    historico = (await cliente.get("/api/alteracoes", headers=h)).json()
    assert any(x["tabela"] == "agentesia_escritorios" for x in historico)
