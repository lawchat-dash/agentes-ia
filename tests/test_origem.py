"""Origem do lead: anúncio (TRACK da Helena) e UTMs, gravada no primeiro toque."""

import os

import pytest

from app.canal.helena import ler_webhook
from app.origem import ler_origem, nota_da_origem
from tests.test_pipeline import CANAL, LEAD, SIMPLES, montar, webhook

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
TRACK = {"pageUtm": {"referralUrl": "https://fb.me/abc", "clid": "ARAkLm123", "source": "facebook", "medium": "paid",
                     "campaign": "auxilio-acidente-mg", "headline": "Sofreu acidente? Você pode ter direito", "term": None}}


def test_le_o_anuncio_e_as_utms():
    origem = ler_origem({"details": {"track": TRACK}})
    assert origem["origem"] == "anuncio" and origem["clid"] == "ARAkLm123" and origem["campanha"] == "auxilio-acidente-mg"
    assert "termo" not in origem
    assert ler_origem({"utm": {"utm_source": "google", "utm_campaign": "bpc"}})["origem"] == "utm"
    assert ler_origem({"details": {}}) is None
    nota = nota_da_origem(origem)
    assert nota.startswith("📣 Lead veio de anúncio") and "Campanha: auxilio-acidente-mg" in nota and "Link: https://fb.me/abc" in nota


def test_evento_track_vira_rastreio_com_numeros():
    evento = ler_webhook(webhook("", evento="MESSAGE_RECEIVED", tipo="TRACK", track=TRACK))
    assert evento.classe == "rastreio" and evento.numero_lead == LEAD and evento.numero_canal == CANAL
    assert evento.origem["fonte"] == "facebook" and evento.id_externo.startswith("track:")


async def test_track_grava_a_origem_sem_pausar_e_a_mensagem_e_respondida():
    atendimento, repo, helena = montar(SIMPLES)
    resultado = await atendimento.receber(webhook("", tipo="TRACK", track=TRACK))
    assert resultado["feito"] == "origem"
    lead = repo.leads[resultado["id_lead"]]
    assert lead.estado == "ativo" and repo.origens[lead.id]["campanha"] == "auxilio-acidente-mg"
    assert [a["dados"]["texto"].splitlines()[0] for a in repo.acoes if a["tipo"] == "nota"] == ["📣 Lead veio de anúncio"]
    assert helena.enviadas == []

    # A mensagem do lead vem depois e é respondida normalmente; outro anúncio não troca a origem (primeiro toque).
    await atendimento.receber(webhook("oi, vi o anúncio"))
    await atendimento.aguardar_esperas()
    assert helena.enviadas == ["Oi! Me conta o que aconteceu?"]
    outro = {"pageUtm": {**TRACK["pageUtm"], "campaign": "bpc"}}
    await atendimento.receber(webhook("", tipo="TRACK", track=outro))
    assert repo.origens[lead.id]["campanha"] == "auxilio-acidente-mg"
    assert len([a for a in repo.acoes if a["tipo"] == "nota"]) == 1


@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_ia_classifica_o_produto_do_anuncio_uma_vez_por_anuncio():
    import json
    import uuid

    import httpx

    from app.acoes import Executor
    from app.banco.postgres import RepositorioPostgres
    from app.canal.helena_conta import HelenaConta
    from app.modelo import ModeloFalso

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        await pool.execute("update agentesia_acoes set situacao = 'cancelada' where situacao in ('pendente', 'executando')")
        token = await pool.fetchval("select vault.create_secret('token-helena', $1)", "t-" + uuid.uuid4().hex[:6])
        esc = await pool.fetchval("insert into agentesia_escritorios (nome, config) values ('Anúncios', $1::jsonb) returning id",
                                  json.dumps({"etiquetas_por_produto": {"bpc_loas": "BPC"}}))
        await pool.execute("insert into agentesia_integracoes (id_escritorio, tipo, id_segredo_vault, situacao) values ($1, 'helena', $2, 'ok')", esc, token)
        canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado) values ($1, $2) returning id",
                                    esc, "5531" + str(uuid.uuid4().int)[:9])
        origem = ler_origem({"details": {"track": {"pageUtm": {**TRACK["pageUtm"], "campaign": "bpc-idoso", "headline": "Idoso de baixa renda tem direito"}}}})
        leads = []
        for _ in range(2):
            contato = await pool.fetchval("insert into agentesia_contatos (id_escritorio, telefone_normalizado) values ($1, $2) returning id",
                                          esc, "55319" + str(uuid.uuid4().int)[:8])
            leads.append(await pool.fetchval(
                "insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_sessao_helena) values ($1, $2, $3, 's') returning id", esc, contato, canal))
            assert await repo.gravar_origem(str(leads[-1]), origem)
            await repo.enfileirar_acoes(id_escritorio=str(esc), id_lead=str(leads[-1]), id_turno=None, acoes=[
                {"tipo": "classificar_origem", "chave_unica": f"{leads[-1]}:origem:produto", "dados": {}}])
        modelo = ModeloFalso({"origem_produto": {"produto": "bpc_loas", "confianca": 0.9}})
        executor = Executor(pool, "https://api.helena.run", modelo=modelo,
                            helena_por_token=lambda t, u: HelenaConta(t, u, httpx.AsyncClient(transport=httpx.MockTransport(lambda p: httpx.Response(200, json={})))))
        await executor.rodar_uma_vez()
        produtos = [json.loads(await pool.fetchval("select origem from agentesia_leads where id = $1", l))["produto"] for l in leads]
        assert produtos == ["bpc_loas", "bpc_loas"]
        assert len([p for p in modelo.pedidos if p["papel"] == "origem_produto"]) == 1          # o 2º lead reaproveitou
        assert "Idoso de baixa renda" in modelo.pedidos[0]["conteudo"]
        etiquetas = [json.loads(r["dados"]) for r in await pool.fetch("select dados from agentesia_acoes where id_lead = any($1) and tipo = 'etiquetar'", leads)]
        assert etiquetas == [{"adicionar": ["BPC"], "remover": []}] * 2
        fatos = await repo.fatos_do_sistema(str(leads[0]))
        assert fatos["veio de anúncio"] == "Idoso de baixa renda tem direito · BPC/LOAS"
    finally:
        await repo.fechar()
