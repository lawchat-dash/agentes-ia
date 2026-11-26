"""Correções da revisão: envio sem confirmação (talvez enviada + eco), card da 1ª mensagem com mensagens seguidas,
conferência de entrega que cai no meio, 502/504 sem nova tentativa, '@lid' em sessão nova, etiqueta SDR que segue o
card e segredo do webhook fora do log do httpx. Tudo com fakes; as partes de banco só com AGENTESIA_TESTE_PG_URL."""

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.canal import webhook as canal_webhook
from app.canal.helena import ClienteHelena, ErroHelena
from app.cerebro import turno as cerebro
from tests.test_pipeline import CANAL, LEAD, SIMPLES, montar, webhook
from tests.test_robustez import lead_de, notas, saida_fixa

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
so_pg = pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")


class HelenaSemConfirmacao:
    """A Helena aceita, mas a resposta não volta (ReadTimeout): ErroHelena('sem_confirmacao ...')."""

    def __init__(self, antes_de_falhar=None):
        self.enviadas, self.ids, self.antes_de_falhar = [], [], antes_de_falhar

    async def enviar(self, *, token, id_sessao, id_canal, texto=None, url_arquivo=None):
        self.enviadas.append(texto or url_arquivo)
        if self.antes_de_falhar:
            await self.antes_de_falhar(texto or url_arquivo)
        raise ErroHelena("sem_confirmacao (ReadTimeout)")


def _eco(texto, id_msg):
    return webhook(texto, de=CANAL, para=LEAD, direcao="TO_HUB", origem="API", evento="MESSAGE_SENT", id_msg=id_msg)


# ============================================================================ [0] envio sem confirmação
async def test_sem_confirmacao_e_talvez_enviada_mantem_a_troca_e_o_eco_liga_a_linha(monkeypatch):
    helena = HelenaSemConfirmacao()
    atendimento, repo, _ = montar(SIMPLES, helena=helena)
    monkeypatch.setattr(cerebro, "processar", saida_fixa(["Vou te passar para o time"], etapa_depois="closer"))
    await atendimento.receber(webhook("quero seguir"))
    await atendimento.aguardar_esperas()
    lead = lead_de(repo)
    assert lead.id_etapa == "e-closer"                                    # a troca de etapa não foi desfeita
    tipos = [e["tipo"] for e in repo.eventos]
    assert "troca_sem_entrega" not in tipos and "envio_falhou" not in tipos
    assert "envio_sem_confirmacao" in tipos and "etapa_trocada" in tipos
    assert len(notas(repo, "envio_sem_confirmacao")) == 1                 # a equipe confere no chat
    ia = [m for m in repo.mensagens[lead.id] if m.autor == "ia"]
    assert len(ia) == 1 and ia[0].texto_extraido is None                  # sem '[NÃO ENTREGUE ao lead]'
    assert repo.situacoes[ia[0].id][0] == "pendente"

    # Chega o eco (MESSAGE_SENT de origem API) com o id real: a linha da IA ganha o id, nada de 'automacao'.
    assert (await atendimento.receber(_eco("Vou te passar para o time", "wamid-real-1")))["motivo"] == "eco_da_ia"
    assert [(m.autor, m.id_externo) for m in repo.mensagens[lead.id] if m.autor != "lead"] == [("ia", "wamid-real-1")]
    assert repo.situacoes[ia[0].id] == ("enviada", None)


async def test_eco_que_chega_antes_do_timeout_vira_a_linha_da_ia(monkeypatch):
    estado = {}

    async def eco_chega_durante_o_envio(texto):
        estado["r"] = await estado["atendimento"].receber(_eco(texto, "wamid-real-2"))

    helena = HelenaSemConfirmacao(antes_de_falhar=eco_chega_durante_o_envio)
    atendimento, repo, _ = montar(SIMPLES, helena=helena)
    estado["atendimento"] = atendimento
    monkeypatch.setattr(cerebro, "processar", saida_fixa(["Pode me mandar o laudo?"]))
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    assert estado["r"]["autor"] == "automacao"                            # na hora, ainda não havia linha da IA
    lead = lead_de(repo)
    outras = [(m.autor, m.id_externo) for m in repo.mensagens[lead.id] if m.autor != "lead"]
    assert outras == [("ia", "wamid-real-2")]                             # a parte adotou o id do eco: sem duplicata
    assert not notas(repo, "envio_sem_confirmacao")
    assert any(a["tipo"] == "conferir_entrega" and a["dados"]["ids"] == ["wamid-real-2"] for a in repo.acoes)


async def test_falha_de_verdade_continua_nao_entregue(monkeypatch):
    from tests.test_pipeline import HelenaFalsa

    atendimento, repo, _ = montar(SIMPLES, helena=HelenaFalsa(falhar=True))
    monkeypatch.setattr(cerebro, "processar", saida_fixa(["Vou te passar para o time"], etapa_depois="closer"))
    await atendimento.receber(webhook("quero seguir"))
    await atendimento.aguardar_esperas()
    lead = lead_de(repo)
    assert lead.id_etapa == "e-sdr"
    ia = [m for m in repo.mensagens[lead.id] if m.autor == "ia"]
    assert ia[0].texto_extraido.startswith("[NÃO ENTREGUE ao lead]")


# ============================================================================ [1] card da 1ª mensagem
async def test_duas_mensagens_seguidas_de_lead_ja_existente_so_a_primeira_e_primeiro_contato():
    atendimento, repo, _ = montar(SIMPLES)
    escritorio, canal = repo.escritorios["esc-1"], repo.canais["canal-1"]
    agente = repo.agentes["canal-1"]
    criado = await repo.achar_ou_criar_lead(escritorio=escritorio, canal=canal, agente=agente, telefone=LEAD,
                                            id_sessao="sessao-1")                    # aberto pela atendente
    lead = await repo.lead(criado.id)                                                # novo=False daqui em diante
    agora = datetime.now(timezone.utc)
    a = await repo.gravar_mensagem(lead=lead, autor="lead", tipo="texto", texto="oi", texto_extraido=None, url_midia=None,
                                   enviada_em=agora, id_externo="w-a")
    b = await repo.gravar_mensagem(lead=lead, autor="lead", tipo="texto", texto="tudo bem?", texto_extraido=None,
                                   url_midia=None, enviada_em=agora + timedelta(seconds=1), id_externo="w-b")
    assert await atendimento._primeiro_contato(lead, antes_de=a) is True
    assert await atendimento._primeiro_contato(lead, antes_de=b) is False


# ============================================================================ [3] 502/504 sem nova tentativa
def _cliente(status):
    chamadas = []

    def tratar(pedido):
        chamadas.append(pedido)
        return httpx.Response(status)

    return ClienteHelena("https://api.helena.invalid", httpx.AsyncClient(transport=httpx.MockTransport(tratar)),
                         pausa_s=0), chamadas


@pytest.mark.parametrize("status", [502, 504])
async def test_502_e_504_nao_repetem_e_viram_sem_confirmacao(status):
    cliente, chamadas = _cliente(status)
    with pytest.raises(ErroHelena, match="sem_confirmacao"):
        await cliente.enviar(token="t", id_sessao="s", id_canal=None, texto="oi")
    assert len(chamadas) == 1


async def test_503_ainda_repete():
    cliente, chamadas = _cliente(503)
    with pytest.raises(ErroHelena, match="HTTP 503"):
        await cliente.enviar(token="t", id_sessao="s", id_canal=None, texto="oi")
    assert len(chamadas) == 3


# ============================================================================ [4] '@lid' em sessão nova
def _lid(texto, sessao, **conteudo):
    corpo = webhook(texto, de="123456789012345@lid")
    corpo["content"]["sessionId"] = sessao
    corpo["content"].update(conteudo)
    return corpo


async def test_lead_conhecido_em_sessao_nova_como_lid_com_telefone_no_contato():
    atendimento, repo, helena = montar(SIMPLES)
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    lead = lead_de(repo)
    r = await atendimento.receber(_lid("voltei", "sessao-nova", contact={"phonenumber": "+" + LEAD}))
    assert r["feito"] == "agendado" and r["id_lead"] == lead.id
    await atendimento.aguardar_esperas()
    assert len(repo.leads) == 1 and lead_de(repo).id_sessao_helena == "sessao-nova"
    assert len(helena.enviadas) == 2


async def test_lead_conhecido_em_sessao_nova_como_lid_pelo_id_do_contato():
    atendimento, repo, helena = montar(SIMPLES)
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    lead = lead_de(repo)
    repo.contatos_helena = {"contato-helena-1": LEAD}                     # agentesia_contatos.id_contato_helena
    r = await atendimento.receber(_lid("voltei", "sessao-nova", contactId="contato-helena-1"))
    assert r["feito"] == "agendado" and r["id_lead"] == lead.id
    assert lead_de(repo).id_sessao_helena == "sessao-nova"


async def test_lid_sem_nenhuma_pista_continua_sem_numero():
    atendimento, repo, _ = montar(SIMPLES)
    r = await atendimento.receber(_lid("oi", "sessao-x"))
    assert r["motivo"] == "contato_sem_numero" and not repo.leads


# ============================================================================ [6] segredo fora do log do httpx
async def test_alcance_da_ativacao_nao_vaza_o_segredo_no_log(caplog):
    from app.gestao.ativacao import _alcance

    canal_webhook.proteger_logs_de_acesso()
    segredo = "SEGREDO-DE-TESTE-" + uuid.uuid4().hex
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda p: httpx.Response(200, json={"feito": "teste"})))
    with caplog.at_level(logging.INFO, logger="httpx"):
        ok, _ = await _alcance(f"https://exemplo.invalid/webhook/helena/1111?segredo={segredo}", http)
    await http.aclose()
    assert ok
    assert any(r.name == "httpx" for r in caplog.records)                 # o httpx registrou o pedido
    assert segredo not in caplog.text and all(segredo not in r.getMessage() for r in caplog.records)
    assert "segredo=***" in caplog.text


# ============================================================================ banco (PGlite)
async def _repo_e_base():
    from app.banco.postgres import RepositorioPostgres
    from tests.test_robustez_pg import _base, _limpar_fila

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    await _limpar_fila(repo._pool)
    return repo, await _base(repo._pool)


@so_pg
async def test_pg_so_a_primeira_de_duas_mensagens_seguidas_cria_o_card():
    repo, b = await _repo_e_base()
    try:
        lead = await repo.lead(str(b["lead"]))
        agora = datetime.now(timezone.utc)
        a = await repo.gravar_mensagem(lead=lead, autor="lead", tipo="texto", texto="oi", texto_extraido=None,
                                       url_midia=None, enviada_em=agora, id_externo="w-" + uuid.uuid4().hex)
        b2 = await repo.gravar_mensagem(lead=lead, autor="lead", tipo="texto", texto="tudo bem?", texto_extraido=None,
                                        url_midia=None, enviada_em=agora, id_externo="w-" + uuid.uuid4().hex)
        primeiras = [not await repo.lead_ja_escreveu(lead.id, antes_de=x) for x in (a, b2)]
        assert sorted(primeiras) == [False, True]                         # exatamente uma (mesmo horário: desempata)
        assert await repo.lead_ja_escreveu(lead.id)
    finally:
        await repo.fechar()


@so_pg
async def test_pg_eco_de_parte_sem_confirmacao_e_eco_que_chegou_antes():
    repo, b = await _repo_e_base()
    try:
        lead = await repo.lead(str(b["lead"]))
        agora = datetime.now(timezone.utc)
        await repo.gravar_mensagem(lead=lead, autor="ia", tipo="texto", texto="Pode mandar o laudo?", texto_extraido=None,
                                   url_midia=None, enviada_em=agora, id_externo=None, situacao_envio="pendente",
                                   erro="sem_confirmacao (ReadTimeout)")
        assert not await repo.ligar_eco_a_ia(str(b["esc"]), lead.id, id_externo="w-x", texto="outra frase", url_midia=None)
        assert await repo.ligar_eco_a_ia(str(b["esc"]), lead.id, id_externo="w-eco-1", texto="Pode mandar o laudo?",
                                         url_midia=None)
        linha = await repo._pool.fetchrow("select id_externo, situacao_envio, erro from agentesia_mensagens "
                                          "where id_lead = $1 and autor = 'ia'", b["lead"])
        assert dict(linha) == {"id_externo": "w-eco-1", "situacao_envio": "enviada", "erro": None}
        assert await repo.mensagem_e_da_ia(str(b["esc"]), "w-eco-1")

        await repo.gravar_mensagem(lead=lead, autor="automacao", tipo="texto", texto="Qual a data do acidente?",
                                   texto_extraido=None, url_midia=None, enviada_em=agora, id_externo="w-eco-2")
        assert await repo.eco_sem_dono(lead.id, texto="Qual a data do acidente?", url_midia=None) == "w-eco-2"
        await repo.gravar_mensagem(lead=lead, autor="ia", tipo="texto", texto="Qual a data do acidente?", texto_extraido=None,
                                   url_midia=None, enviada_em=agora, id_externo="w-eco-2", situacao_envio="enviada")
        assert await repo._pool.fetchval("select autor from agentesia_mensagens where id_externo = 'w-eco-2'") == "ia"
    finally:
        await repo.fechar()


@so_pg
async def test_pg_lead_do_contato_pelo_id_da_helena_e_pelo_telefone():
    repo, b = await _repo_e_base()
    try:
        id_contato = await repo._pool.fetchval(
            "select c.id_contato_helena from agentesia_leads l join agentesia_contatos c on c.id = l.id_contato where l.id = $1",
            b["lead"])
        telefone = await repo._pool.fetchval(
            "select c.telefone_normalizado from agentesia_leads l join agentesia_contatos c on c.id = l.id_contato where l.id = $1",
            b["lead"])
        achado = await repo.lead_do_contato(str(b["esc"]), str(b["canal"]), id_contato_helena=id_contato)
        assert achado and achado.id == str(b["lead"])
        assert (await repo.lead_do_contato(str(b["esc"]), str(b["canal"]), telefone=telefone)).id == str(b["lead"])
        assert await repo.lead_do_contato(str(b["esc"]), str(b["canal"]), id_contato_helena="nao-existe") is None
    finally:
        await repo.fechar()


def _executor(pool, tratar):
    from app.acoes import Executor
    from app.canal.helena_conta import HelenaConta

    return Executor(pool, "https://api.helena.run", helena_por_token=lambda t, u: HelenaConta(
        t, u, httpx.AsyncClient(transport=httpx.MockTransport(tratar))))


@so_pg
async def test_pg_conferir_entrega_que_cai_no_meio_ainda_avisa_na_nova_tentativa():
    repo, b = await _repo_e_base()
    pool = repo._pool
    try:
        lead = await repo.lead(str(b["lead"]))
        m1, m2 = "m1-" + uuid.uuid4().hex[:8], "m2-" + uuid.uuid4().hex[:8]
        for i, ident in enumerate((m1, m2)):
            await repo.gravar_mensagem(lead=lead, autor="ia", tipo="texto", texto=f"parte {i}", texto_extraido=None,
                                       url_midia=None, enviada_em=datetime.now(timezone.utc), id_externo=ident,
                                       situacao_envio="enviada")
        await repo.enfileirar_acoes(id_escritorio=str(b["esc"]), id_lead=lead.id, id_turno=None, acoes=[
            {"tipo": "conferir_entrega", "chave_unica": f"{uuid.uuid4().hex}:entrega", "dados": {"ids": [m1, m2]}}])
        estado = {"m2": 0}

        def helena(pedido):
            if pedido.url.path == f"/chat/v1/message/{m1}/status":
                return httpx.Response(200, json={"status": "FAILED", "failureReason": "mídia apagada"})
            if pedido.url.path == f"/chat/v1/message/{m2}/status":
                estado["m2"] += 1
                return httpx.Response(500) if estado["m2"] == 1 else httpx.Response(200, json={"status": "DELIVERED"})
            return httpx.Response(200, json={})

        executor = _executor(pool, helena)
        await executor.rodar_uma_vez()
        assert await pool.fetchval("select situacao from agentesia_acoes where id_lead = $1 and tipo = 'conferir_entrega'",
                                   b["lead"]) == "pendente"
        assert await pool.fetchval("select situacao_envio from agentesia_mensagens where id_externo = $1", m1) == "enviada"
        await pool.execute("update agentesia_acoes set proxima_em = now() where id_lead = $1 and tipo = 'conferir_entrega'",
                           b["lead"])
        await executor.rodar_uma_vez()
        assert await pool.fetchval("select situacao_envio from agentesia_mensagens where id_externo = $1", m1) == "falhou"
        assert await pool.fetchval("select count(*) from agentesia_eventos where id_lead = $1 and tipo = 'envio_falhou'",
                                   b["lead"]) == 1
        assert await pool.fetchval("select count(*) from agentesia_acoes where id_lead = $1 and tipo = 'nota' "
                                   "and chave_unica like '%:problema:envio_falhou:%'", b["lead"]) == 1
    finally:
        await repo.fechar()


async def _etiquetas_do_lead_novo(pool, b, *, card_no_banco=False, card_no_painel=False):
    from app import automacoes
    from app.banco.postgres import RepositorioPostgres

    config = {"funcoes": {"crm": True}, "automacoes": {"lead_novo": {"coluna_crm": "col-sdr"}}}
    acoes, problema = automacoes.acoes_do_lead_novo(config, {"id_painel": "p1"}, id_lead=str(b["lead"]))
    assert problema is None and acoes[1]["dados"]["gatilho"] == "lead_novo"
    if card_no_banco:
        await pool.execute("""insert into agentesia_crm_cards (id_escritorio, id_lead, id_card_helena, id_painel_helena,
                                                                id_etapa_helena, situacao) values ($1, $2, $3, 'p1', 'col-contrato', 'ok')""",
                           b["esc"], b["lead"], "card-" + uuid.uuid4().hex)
    await RepositorioPostgres(pool).enfileirar_acoes(id_escritorio=str(b["esc"]), id_lead=str(b["lead"]), id_turno=None,
                                                     acoes=acoes)
    chamadas = []

    def helena(pedido):
        chamadas.append((pedido.method, pedido.url.path))
        if pedido.url.path == "/crm/v2/panel/card":
            if pedido.method == "GET":
                return httpx.Response(200, json={"items": [{"id": "card-velho", "status": "OPEN"}]} if card_no_painel
                                      else {"items": []})
            return httpx.Response(200, json={"id": "card-novo"})
        return httpx.Response(200, json={})

    await _executor(pool, helena).rodar_uma_vez()
    linha = await pool.fetchrow("select situacao, resultado from agentesia_acoes where id_lead = $1 and tipo = 'etiquetar'",
                                b["lead"])
    resultado = linha["resultado"] if isinstance(linha["resultado"], dict) else json.loads(linha["resultado"])
    return linha["situacao"], resultado, [c for c in chamadas if c[1].endswith("/tags")]


@so_pg
async def test_pg_etiqueta_sdr_nao_vai_para_quem_ja_tem_card():
    repo, b = await _repo_e_base()
    try:
        situacao, resultado, tags = await _etiquetas_do_lead_novo(repo._pool, b, card_no_painel=True)
        assert situacao == "feita" and resultado["acao"] == "ignorada" and tags == []
    finally:
        await repo.fechar()
    repo, b = await _repo_e_base()
    try:
        situacao, resultado, tags = await _etiquetas_do_lead_novo(repo._pool, b, card_no_banco=True)
        assert situacao == "feita" and resultado["acao"] == "ignorada" and tags == []
    finally:
        await repo.fechar()


@so_pg
async def test_pg_etiqueta_sdr_vai_para_o_lead_novo_sem_card():
    repo, b = await _repo_e_base()
    try:
        situacao, resultado, tags = await _etiquetas_do_lead_novo(repo._pool, b)
        assert situacao == "feita" and resultado.get("acao") != "ignorada" and tags
    finally:
        await repo.fechar()
