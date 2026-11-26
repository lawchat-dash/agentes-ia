"""Itens trazidos do fluxo Weaver (n8n): card e etiqueta SDR na chegada do lead, IA que não atende e registra
assim mesmo, central de problemas, classificação do erro da IA e a fala do atendente."""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app import automacoes, central_avisos
from app.banco.tipos import Etapa
from app.canal.helena import ler_webhook
from app.cerebro import turno as cerebro
from app.modelo import ErroModelo, ModeloFalso
from tests.test_pipeline import CANAL, LEAD, SIMPLES, montar, webhook
from tests.test_turno import extrai, fala

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
CRM = {"funcoes": {"crm": True}, "automacoes": {"lead_novo": {"coluna_crm": "col-sdr"}}}


def _com_crm(repo, config=CRM, painel="painel-1"):
    repo.agentes["canal-1"].config.update(json.loads(json.dumps(config)))
    if painel:
        repo.crm["esc-1"] = {"id_painel": painel}


def _do_atendente(texto, **extra):
    return webhook(texto, de=CANAL, para=LEAD, direcao="TO_HUB", origem="DEFAULT", evento="MESSAGE_SENT", **extra)


def _notas(repo):
    return [a["dados"]["texto"] for a in repo.acoes if a["tipo"] == "nota"]


# ----------------------------------------------------------------------------- 1. um lead, um card (na chegada)
async def test_lead_que_chega_com_ia_pausada_ganha_card_e_etiqueta_sdr():
    atendimento, repo, helena = montar(SIMPLES, situacao="pausado")
    _com_crm(repo)
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    lead = next(iter(repo.leads.values()))
    assert helena.enviadas == []
    card, etiquetas = [a for a in repo.acoes if a["tipo"] in ("mover_card", "etiquetar")]
    assert card["chave_unica"] == f"{lead.id}:lead_novo:card" and card["id_turno"] is None
    assert card["dados"] == {"id_painel": "painel-1", "id_etapa_helena": "col-sdr", "gatilho": "lead_novo"}
    assert etiquetas["dados"]["adicionar"] == ["📞 SDR"]                 # sem etiqueta na regra: a SDR padrão


async def test_um_lead_um_card_mesmo_com_a_automacao_da_primeira_resposta():
    atendimento, repo, helena = montar(SIMPLES)
    _com_crm(repo, {"funcoes": {"crm": True}, "automacoes": {"lead_novo": {"coluna_crm": "col-sdr",
                                                                          "adicionar_etiquetas": ["Novo"]}}})
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    assert helena.enviadas                                               # a IA respondeu: o gatilho lead_novo rodou
    assert list(repo.turnos.values())[-1]["contexto"]["automacoes"]["gatilhos"] == ["lead_novo"]
    crm = lambda: [a for a in repo.acoes if a["tipo"] != "conferir_entrega"   # noqa: E731 (sem a conferência de entrega
                   and not a["chave_unica"].endswith(":nota:atendimento_iniciado")]                     # nem a nota interna de atendimento iniciado)
    assert [a["tipo"] for a in crm()] == ["mover_card", "etiquetar"]   # e não duplicou nada
    assert crm()[1]["dados"]["adicionar"] == ["Novo"]
    await atendimento.receber(webhook("oi de novo"))                     # lead que já existe: nada de card novo
    await atendimento.aguardar_esperas()
    assert [a["tipo"] for a in crm()] == ["mover_card", "etiquetar"]


@pytest.mark.parametrize("config, painel, motivo", [
    (CRM, None, "o escritório não tem painel do CRM"),
    ({"funcoes": {"crm": True}, "automacoes": {}}, "painel-1", "o agente não tem a coluna SDR"),
])
async def test_sem_painel_ou_sem_coluna_vira_card_nao_criado_com_nota(config, painel, motivo):
    atendimento, repo, _helena = montar(SIMPLES, situacao="pausado")
    _com_crm(repo, config, painel)
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    evento = next(e for e in repo.eventos if e["tipo"] == "card_nao_criado")
    assert evento["responsavel"] == "cadastro" and motivo in evento["descricao"]
    nota = next(t for t in _notas(repo) if t.startswith("⚠️ Card do lead"))
    assert nota.startswith("⚠️ Card do lead não foi criado no CRM.\nMotivo: " + motivo)
    assert [a["tipo"] for a in repo.acoes if a["tipo"] in ("mover_card", "etiquetar")] == ["etiquetar"]


async def test_sem_a_funcao_crm_nao_ha_card_nem_aviso():
    atendimento, repo, _helena = montar(SIMPLES)
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    assert not [a for a in repo.acoes if a["tipo"] in ("mover_card", "etiquetar")]
    assert not [e for e in repo.eventos if e["tipo"] == "card_nao_criado"]


def test_titulo_e_descricao_do_card():
    assert automacoes.titulo_do_card('"Maria Souza"', "5511988887777") == "👤 Maria Souza | 📞 (11) 98888-7777"
    assert automacoes.titulo_do_card(None, "5511988887777") == "📞 (11) 98888-7777"
    quando = datetime(2026, 11, 24, 15, 30, tzinfo=timezone.utc)
    descricao = automacoes.descricao_do_card({"url": "https://fb.me/ad1", "campanha": "AA nov"}, quando)
    assert descricao == "🕒 Entrou em: 24/11/2026 às 12:30\n\n📣 Origem (UTM)\nCampanha: AA nov\nLink: https://fb.me/ad1"
    anuncio = automacoes.descricao_do_card({"origem": "anuncio", "titulo": "Sequela? Fale com a gente", "fonte": "facebook"}, quando)
    assert anuncio.splitlines()[2:] == ["📣 Veio de anúncio", "Anúncio: Sequela? Fale com a gente", "Fonte: facebook"]
    assert automacoes.descricao_do_card({}, quando) == ("🕒 Entrou em: 24/11/2026 às 12:30\n\n"
                                                        "📣 Origem: contato direto (sem anúncio ou UTM)")


def test_sugestao_padrao_poe_a_etiqueta_sdr_no_lead_novo():
    sugestao = automacoes.sugestao_padrao([{"id": "a", "titulo": "SDR", "inicial": True}])
    assert sugestao["lead_novo"] == {"coluna_crm": "a", "adicionar_etiquetas": ["📞 SDR"]}


# ----------------------------------------------------------------------------- 2. a IA não atende e registra assim mesmo
async def test_agente_pausado_registra_evento_e_nota():
    atendimento, repo, _helena = montar(SIMPLES, situacao="pausado")
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    evento = next(e for e in repo.eventos if e["tipo"] == "agente_pausado")
    assert evento["responsavel"] == "cliente" and evento["id_turno"]
    assert _notas(repo) == [atendimento.NOTAS_DE_PROBLEMA["agente_pausado"].format(detalhe="Júlia")]
    await atendimento.receber(webhook("alô?"))                           # de novo: evento sim, nota não (6 h)
    await atendimento.aguardar_esperas()
    assert len([e for e in repo.eventos if e["tipo"] == "agente_pausado"]) == 2 and len(_notas(repo)) == 1


async def test_ia_desligada_no_escritorio_registra_evento_e_nota():
    atendimento, repo, helena = montar(SIMPLES)
    repo.escritorios["esc-1"].ia_desligada = True
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    assert helena.enviadas == []
    assert [e["responsavel"] for e in repo.eventos if e["tipo"] == "ia_desligada_no_escritorio"] == ["cliente"]
    assert _notas(repo)[0].startswith("⏸️ A IA não respondeu: a IA está desligada neste escritório.")


async def test_etapa_do_catalogo_sem_prompt_nao_chama_a_ia():
    atendimento, repo, helena = montar(SIMPLES)
    agente = repo.agentes["canal-1"]
    agente.produto, agente.etapas = "catalogo", [Etapa("e-sdr", "sdr", principal=True, instrucao="  "),
                                                Etapa("e-closer", "closer", instrucao="Feche o contrato.")]
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    assert helena.enviadas == [] and atendimento.modelo.pedidos == []
    assert next(iter(repo.turnos.values()))["motivo"] == "sem_prompt"
    evento = next(e for e in repo.eventos if e["tipo"] == "sem_prompt")
    assert evento["responsavel"] == "cadastro" and "etapa sdr" in evento["descricao"]
    assert _notas(repo) == [atendimento.NOTAS_DE_PROBLEMA["sem_prompt"]]   # 26/11: a equipe vê no chat por que
    lead = next(iter(repo.leads.values()))
    agente.etapas[0].instrucao = "Você é a SDR."
    assert atendimento._por_que_nao_atende(repo.escritorios["esc-1"], agente, lead, agente.etapas[0], "teste") is None


async def test_contato_sem_numero_deixa_nota_pela_sessao_do_webhook():
    atendimento, repo, _helena = montar(SIMPLES)
    corpo = webhook("oi")
    corpo["content"]["details"]["from"] = ""
    assert (await atendimento.receber(corpo))["motivo"] == "contato_sem_numero"
    segundo = webhook("oi de novo")
    segundo["content"]["details"]["from"] = ""
    await atendimento.receber(segundo)
    assert [e["responsavel"] for e in repo.eventos] == ["lead", "lead"]
    nota, = [a for a in repo.acoes if a["tipo"] == "nota"]               # trava: uma nota por conversa a cada 6 h
    assert nota["id_lead"] is None and nota["dados"]["id_sessao"] == "sessao-1"
    assert nota["dados"]["texto"].startswith("🤖 A IA não iniciou a conversa com este contato")
    assert nota["dados"]["texto"].endswith("Responda manualmente.")


# ----------------------------------------------------------------------------- 3 e 4. erro da IA e central de problemas
def _etapa_que_falha(erro):
    def etapa(_sistema, _conteudo):
        raise erro
    return etapa


async def test_conversa_longa_vira_tipo_proprio_da_lawchat(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "chave-de-teste")
    detalhe = "Error code: 400 - {'error': {'message': \"This model's maximum context length is 128000 tokens\", " \
              "'code': 'context_length_exceeded'}}"
    atendimento, repo, helena = montar({"extrator": extrai(), "etapa": _etapa_que_falha(ErroModelo("pedido_invalido", detalhe))})
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    evento = next(e for e in repo.eventos if e["tipo"] == "ia_conversa_longa")
    assert (evento["responsavel"], evento["gravidade"]) == ("lawchat", "critico")
    assert next(iter(repo.turnos.values()))["motivo"] == "etapa:conversa_longa"
    assert _notas(repo) == [atendimento.NOTAS_DE_PROBLEMA["ia_conversa_longa"]]


@pytest.mark.parametrize("com_chave, responsavel", [(True, "lawchat"), (False, "cliente")])
async def test_sem_credito_com_a_chave_do_servidor_e_da_lawchat(monkeypatch, com_chave, responsavel):
    if com_chave:
        monkeypatch.setenv("OPENAI_API_KEY", "chave-de-teste")
    else:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    atendimento, repo, _helena = montar({"extrator": extrai(), "etapa": _etapa_que_falha(ErroModelo("sem_credito", "insufficient_quota"))})
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    evento = next(e for e in repo.eventos if e["tipo"] == "ia_sem_credito")
    assert evento["responsavel"] == responsavel
    assert _notas(repo) == [atendimento.NOTAS_DE_PROBLEMA["ia_sem_credito"]]


async def test_chave_recusada_continua_ia_nao_respondeu_mas_da_lawchat(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "chave-de-teste")
    atendimento, repo, _helena = montar({"extrator": extrai(), "etapa": _etapa_que_falha(ErroModelo("chave_recusada", "401"))})
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    assert [(e["tipo"], e["responsavel"]) for e in repo.eventos] == [("ia_nao_respondeu", "lawchat")]


async def test_resposta_vazia_vira_evento_e_nota(monkeypatch):
    atendimento, repo, helena = montar(SIMPLES)

    async def processar(_modelo, entrada):
        return cerebro.Saida(etapa_antes=entrada.etapa, etapa_depois=entrada.etapa)

    monkeypatch.setattr(cerebro, "processar", processar)
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    assert helena.enviadas == []
    assert [(e["tipo"], e["responsavel"]) for e in repo.eventos] == [("resposta_vazia", "lawchat")]
    assert _notas(repo) == [atendimento.NOTAS_DE_PROBLEMA["resposta_vazia"]]


def test_texto_do_aviso_de_cadastro():
    texto = central_avisos.texto_do_aviso({"criado_em": datetime.now(timezone.utc), "gravidade": "aviso",
                                           "responsavel": "cadastro", "tipo": "canal_nao_cadastrado", "escritorio": "X"})
    assert "LawChat IA · aviso" in texto and "Problema: canal_nao_cadastrado (cadastro)" in texto


# ----------------------------------------------------------------------------- 5. a fala do atendente
def test_fala_do_atendente_sem_assinatura_e_com_marcadores():
    texto = ler_webhook(_do_atendente("*Paula Souza:* Olá, tudo bem?"))
    assert (texto.classe, texto.texto, texto.texto_extraido) == ("humano", "Olá, tudo bem?", None)
    imagem = ler_webhook(_do_atendente("*Paula:* veja o modelo", tipo="IMAGE"))
    assert imagem.texto_extraido == "[O atendente enviou uma imagem ao lead.]\nveja o modelo"
    audio = ler_webhook(_do_atendente(None, tipo="AUDIO"))
    assert audio.texto_extraido == "[O atendente enviou um áudio ao lead.]"
    transcrito = ler_webhook(_do_atendente(None, tipo="AUDIO", transcription={"text": "pode mandar o laudo"}))
    assert transcrito.texto_extraido == "pode mandar o laudo"
    video = ler_webhook(_do_atendente(None, tipo="VIDEO"))
    assert video.texto_extraido == "[O atendente enviou um vídeo ao lead.]"
    documento = ler_webhook(_do_atendente(None, tipo="DOCUMENT", file={"name": "procuracao.pdf"}))
    assert documento.texto_extraido == "[O atendente enviou um documento (procuracao.pdf) ao lead.]"
    lead = ler_webhook(webhook("*Isto:* é do lead"))
    assert lead.texto == "*Isto:* é do lead"                             # só a fala do atendente perde o prefixo


async def test_ia_volta_sabendo_o_que_o_atendente_mandou():
    atendimento, repo, helena = montar(SIMPLES)
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    await atendimento.receber(_do_atendente("*Paula:* segue o modelo", tipo="IMAGE"))
    lead = next(iter(repo.leads.values()))
    gravada = repo.mensagens[lead.id][-1]
    assert (gravada.autor, gravada.texto) == ("humano", "segue o modelo")
    assert repo.followups[-1] == ("cancelar", lead.id, "equipe_falou") and lead.estado == "pausado"
    lead.pausado_ate = datetime.now(timezone.utc) - timedelta(seconds=1)
    await atendimento.receber(webhook("recebi"))
    await atendimento.aguardar_esperas()
    assert "[atendente] [O atendente enviou uma imagem ao lead.]" in atendimento.modelo.pedidos[-1]["conteudo"]


async def test_pausa_que_falha_vira_evento_critico_e_aceita_o_reenvio():
    atendimento, repo, _helena = montar(SIMPLES)
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    original = repo.registrar_fala_do_atendente

    async def quebrado(**_kwargs):
        raise RuntimeError("banco fora do ar")

    repo.registrar_fala_do_atendente = quebrado
    corpo = _do_atendente("*Paula:* oi, aqui é a Paula")
    assert (await atendimento.receber(corpo))["motivo"] == "pausa_falhou"
    evento = next(e for e in repo.eventos if e["tipo"] == "pausa_falhou")
    assert (evento["gravidade"], evento["responsavel"]) == ("critico", "lawchat")
    repo.registrar_fala_do_atendente = original
    assert (await atendimento.receber(corpo))["feito"] == "pausado"       # o reenvio da Helena não é "repetido"
    assert next(iter(repo.leads.values())).estado == "pausado"


# ----------------------------------------------------------------------------- Postgres de verdade
@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_postgres_card_com_titulo_descricao_falha_e_nota_sem_lead():
    from app.acoes import Executor
    from app.banco.postgres import RepositorioPostgres
    from app.canal.helena_conta import HelenaConta

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        await pool.execute("update agentesia_acoes set situacao = 'cancelada' where situacao in ('pendente', 'executando')")
        segredo = await pool.fetchval("select vault.create_secret('token-card-novo', 'teste')")
        esc = str(await pool.fetchval("insert into agentesia_escritorios (nome) values ('Card novo') returning id"))
        await pool.execute("insert into agentesia_integracoes (id_escritorio, tipo, id_segredo_vault, situacao) "
                           "values ($1, 'helena', $2, 'ok')", esc, segredo)
        canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado) values ($1, $2) returning id",
                                    esc, "5511" + str(uuid.uuid4().int)[:9])
        contato = await pool.fetchval("insert into agentesia_contatos (id_escritorio, nome, telefone_normalizado) "
                                      "values ($1, 'Maria', '5511900000011') returning id", esc)
        lead = str(await pool.fetchval(
            """insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_sessao_helena, origem)
               values ($1, $2, $3, 'sessao-ok', $4::jsonb) returning id""",
            esc, contato, canal, json.dumps({"origem": "anuncio", "url": "https://fb.me/ad9", "campanha": "AA"})))
        contato2 = await pool.fetchval("insert into agentesia_contatos (id_escritorio, telefone_normalizado) "
                                       "values ($1, '5511900000012') returning id", esc)
        lead2 = str(await pool.fetchval("insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_sessao_helena) "
                                        "values ($1, $2, $3, 'sessao-sumiu') returning id", esc, contato2, canal))
        config = {"funcoes": {"crm": True}, "automacoes": {"lead_novo": {"coluna_crm": "col-sdr"}}}
        for id_lead in (lead, lead2):
            acoes, problema = automacoes.acoes_do_lead_novo(config, {"id_painel": "p1"}, id_lead=id_lead)
            assert problema is None
            await repo.enfileirar_acoes(id_escritorio=esc, id_lead=id_lead, id_turno=None, acoes=acoes[:1])
        await repo.enfileirar_acoes(id_escritorio=esc, id_lead=None, id_turno=None, acoes=[{
            "tipo": "nota", "chave_unica": f"sessao:{uuid.uuid4().hex}:problema:contato_sem_numero:1",
            "dados": {"texto": "🤖 A IA não iniciou a conversa", "id_sessao": "sessao-sem-numero"}}])
        chamadas = []

        def helena(pedido: httpx.Request) -> httpx.Response:
            corpo = json.loads(pedido.content) if pedido.content else None
            chamadas.append((pedido.method, pedido.url.path, corpo))
            if pedido.url.path == "/chat/v2/session/sessao-ok":
                return httpx.Response(200, json={"contactId": "contato-ok"})
            if pedido.url.path == "/crm/v2/panel/card":
                return httpx.Response(200, json={"items": []} if pedido.method == "GET" else {"id": "card-novo"})
            if pedido.url.path.endswith("/note"):
                return httpx.Response(200, json={})
            return httpx.Response(404)                                   # a sessão do lead2 sumiu: falha definitiva

        executor = Executor(pool, "https://api.helena.run", helena_por_token=lambda t, u: HelenaConta(
            t, u, httpx.AsyncClient(transport=httpx.MockTransport(helena))))
        await executor.rodar_uma_vez()
        criado = next(c for m, p, c in chamadas if p == "/crm/v2/panel/card" and m == "POST")
        assert criado["title"] == "👤 Maria | 📞 (11) 90000-0011" and criado["stepId"] == "col-sdr"
        assert criado["description"].startswith("🕒 Entrou em: ") and criado["description"].endswith("Campanha: AA\nLink: https://fb.me/ad9")
        assert ("POST", "/chat/v1/session/sessao-sem-numero/note", {"text": "🤖 A IA não iniciou a conversa"}) in chamadas

        evento = await pool.fetchrow("select tipo, responsavel from agentesia_eventos where id_lead = $1::uuid", lead2)
        assert (evento["tipo"], evento["responsavel"]) == ("card_nao_criado", "cadastro")
        nota = await pool.fetchrow("select dados from agentesia_acoes where id_lead = $1::uuid and tipo = 'nota'", lead2)
        texto = json.loads(nota["dados"])["texto"] if isinstance(nota["dados"], str) else nota["dados"]["texto"]
        assert texto.startswith("⚠️ Card do lead não foi criado no CRM.\nMotivo: a Helena não criou o card do lead")
    finally:
        await repo.fechar()


@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_postgres_fala_do_atendente_numa_transacao_so():
    from app.banco.postgres import RepositorioPostgres
    from app.banco.tipos import Lead

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        esc = str(await pool.fetchval("insert into agentesia_escritorios (nome) values ('Atendente') returning id"))
        canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado) values ($1, $2) returning id",
                                    esc, "5511" + str(uuid.uuid4().int)[:9])
        contato = await pool.fetchval("insert into agentesia_contatos (id_escritorio, telefone_normalizado) "
                                      "values ($1, '5511900000021') returning id", esc)
        id_lead = str(await pool.fetchval("insert into agentesia_leads (id_escritorio, id_contato, id_canal) "
                                          "values ($1, $2, $3) returning id", esc, contato, canal))
        await pool.execute("""insert into agentesia_followups (id_escritorio, id_lead, passo, base, agendado_para)
                              values ($1, $2, 0, now(), now() + interval '1 hour')""", esc, id_lead)
        lead = Lead(id=id_lead, id_escritorio=esc, id_canal=str(canal), id_agente=None, id_etapa=None, telefone="5511900000021")
        fala_ = dict(lead=lead, tipo="texto", texto="oi", texto_extraido=None, url_midia=None,
                     enviada_em=datetime.now(timezone.utc), motivo_followup="equipe_falou")

        # Pausa que quebra no meio: nada fica gravado (nem a fala, nem o cancelamento do follow-up).
        with pytest.raises(Exception):
            await repo.registrar_fala_do_atendente(**fala_, id_externo="msg-1",
                                                   pausa={"estado": "pausado", "motivo_estado": "x", "pausado_ate": "não é data"})
        assert await pool.fetchval("select count(*) from agentesia_mensagens where id_lead = $1::uuid", id_lead) == 0
        assert await pool.fetchval("select situacao from agentesia_followups where id_lead = $1::uuid", id_lead) == "pendente"

        volta = datetime.now(timezone.utc) + timedelta(minutes=15)
        assert await repo.registrar_fala_do_atendente(**fala_, id_externo="msg-1",
                                                      pausa={"estado": "pausado", "motivo_estado": "humano_assumiu", "pausado_ate": volta})
        linha = await pool.fetchrow("select estado, motivo_estado from agentesia_leads where id = $1::uuid", id_lead)
        assert (linha["estado"], linha["motivo_estado"]) == ("pausado", "humano_assumiu")
        assert await pool.fetchval("select situacao from agentesia_followups where id_lead = $1::uuid", id_lead) == "cancelado"
        assert await pool.fetchval("select autor from agentesia_mensagens where id_lead = $1::uuid", id_lead) == "humano"

        # Recebido esquecido: o mesmo id volta a ser aceito.
        id_externo = f"wamid-{uuid.uuid4()}"
        assert await repo.registrar_recebido(origem="helena", id_externo=id_externo, tipo="humano", payload={}, id_escritorio=esc)
        await repo.esquecer_recebido(origem="helena", id_externo=id_externo, tipo="humano")
        assert await repo.registrar_recebido(origem="helena", id_externo=id_externo, tipo="humano", payload={}, id_escritorio=esc)
    finally:
        await repo.fechar()


@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_postgres_alerta_de_cadastro_chega_a_central_uma_vez_por_escritorio(monkeypatch):
    from app.banco.postgres import RepositorioPostgres

    monkeypatch.setenv("AGENTESIA_HELENA_TOKEN_LAWCHAT", "token-lawchat")
    monkeypatch.setenv("AGENTESIA_ALERTA_LAWCHAT_DE", "11 90000-0001")
    monkeypatch.setenv("AGENTESIA_ALERTA_LAWCHAT_PARA", "11 90000-0002")
    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        desde = datetime.now(timezone.utc) - timedelta(seconds=1)
        esc = str(await pool.fetchval("insert into agentesia_escritorios (nome) values ('Cadastro') returning id"))
        canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado) values ($1, $2) returning id",
                                    esc, "5511" + str(uuid.uuid4().int)[:9])
        leads = []
        for fone in ("5511900000031", "5511900000032"):
            contato = await pool.fetchval("insert into agentesia_contatos (id_escritorio, telefone_normalizado) "
                                          "values ($1, $2) returning id", esc, fone)
            leads.append(str(await pool.fetchval("insert into agentesia_leads (id_escritorio, id_contato, id_canal) "
                                                 "values ($1, $2, $3) returning id", esc, contato, canal)))
        aviso = {"tipo": "card_nao_criado", "gravidade": "aviso", "responsavel": "cadastro", "descricao": "sem painel"}
        for id_lead in leads:
            await repo.gravar_eventos(id_escritorio=esc, id_lead=id_lead, id_turno=None, eventos=[aviso])
        await repo.gravar_eventos(id_escritorio=esc, id_lead=None, id_turno=None, eventos=[
            {"tipo": "agente_pausado", "gravidade": "aviso", "responsavel": "cliente", "descricao": "do cliente"}])
        await central_avisos.varrer(pool, desde)
        alertas = await pool.fetch(
            "select dados from agentesia_acoes where id_escritorio = $1::uuid and tipo = 'alertar_lawchat'", esc)
        assert len(alertas) == 1                                         # dois leads, um aviso; o do cliente não vai
        dados = alertas[0]["dados"]
        texto = (json.loads(dados) if isinstance(dados, str) else dados)["texto"]
        assert "card_nao_criado (cadastro)" in texto
    finally:
        await repo.fechar()
