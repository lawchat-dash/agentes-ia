"""Automações: gatilhos do turno, ações montadas e o executor contra a Helena simulada."""

import json
import os
import uuid

import httpx
import pytest

from app import automacoes
from app.acoes import Executor
from app.banco.postgres import RepositorioPostgres
from app.canal.helena_conta import HelenaConta
from tests.test_pipeline import montar, webhook
from tests.test_turno import extrai, fala

REGRAS = {
    "lead_novo": {"coluna_crm": "s1", "adicionar_etiquetas": ["📞 SDR"]},
    "etapa:closer": {"coluna_crm": "s2", "adicionar_etiquetas": ["🛒 Comercial"], "remover_etiquetas": ["📞 SDR"]},
    "pediu_humano": {"transferir": True, "nota": "O lead pediu uma pessoa."},
}
CONFIG = {"automacoes": REGRAS, "funcoes": {"crm": True, "avisos": True, "transferir_humano": True},
          "id_equipe_transferencia": "equipe-1"}


def test_gatilhos_do_turno():
    g = automacoes.gatilhos_do_turno
    assert g(primeira_resposta=True, etapa_antes="sdr", etapa_depois="sdr", motivo_estado=None,
             situacao="respondido", sinais=[]) == ["lead_novo"]
    assert g(primeira_resposta=False, etapa_antes="sdr", etapa_depois="closer", motivo_estado=None,
             situacao="respondido", sinais=[]) == ["etapa:closer"]
    assert g(primeira_resposta=False, etapa_antes="sdr", etapa_depois="sdr", motivo_estado="pediu_humano",
             situacao="respondido", sinais=["quer_audio"]) == ["pediu_humano", "sinal", "sinal:quer_audio"]
    assert g(primeira_resposta=True, etapa_antes="sdr", etapa_depois="sdr", motivo_estado=None,
             situacao="erro", sinais=[]) == ["ia_falhou"]


def test_acoes_respeitam_as_funcoes_ligadas():
    acoes = automacoes.montar_acoes(CONFIG, {"id_painel": "p1"}, ["etapa:closer", "pediu_humano"],
                                    id_lead="L", id_turno="T")
    assert [a["tipo"] for a in acoes] == ["mover_card", "etiquetar", "nota", "transferir"]
    assert acoes[0]["dados"] == {"id_painel": "p1", "id_etapa_helena": "s2", "gatilho": "etapa:closer"}
    sem_crm = automacoes.montar_acoes({**CONFIG, "funcoes": {"avisos": True}}, {"id_painel": "p1"},
                                      ["etapa:closer", "pediu_humano"], id_lead="L", id_turno="T")
    assert [a["tipo"] for a in sem_crm] == ["nota"]
    sem_painel = automacoes.montar_acoes(CONFIG, None, ["lead_novo"], id_lead="L", id_turno="T")
    assert [a["tipo"] for a in sem_painel] == ["etiquetar"]


def test_validar_descarta_o_desconhecido():
    limpa = automacoes.validar({"lead_novo": {"coluna_crm": "s1", "lixo": 1, "nota": "  "},
                                "inexistente": {"nota": "x"}, "etapa:closer": {}})
    assert limpa == {"lead_novo": {"coluna_crm": "s1"}}


def test_sugestao_liga_por_nome():
    sugestao = automacoes.sugestao_padrao([
        {"id": "a", "titulo": "Novos Leads", "inicial": True}, {"id": "b", "titulo": "Negociação"},
        {"id": "c", "titulo": "Contrato enviado"}, {"id": "d", "titulo": "Perdidos"}])
    assert (sugestao["lead_novo"]["coluna_crm"], sugestao["etapa:closer"]["coluna_crm"],
            sugestao["etapa:coleta_dados"]["coluna_crm"], sugestao["etapa:desqualificado"]["coluna_crm"]) == ("a", "b", "c", "d")


async def test_pipeline_poe_as_acoes_na_fila():
    fatos = [("acidente_descricao", "caí", "caí"), ("acidente_ano", "2023", "2023"), ("sequela", "sim", "sim"),
             ("vinculo_na_data", "clt", "carteira"), ("aposentado", "nao", "não"), ("tem_advogado_no_caso", "nao", "não")]
    atendimento, repo, _helena = montar({"extrator": [extrai(), extrai(fatos)], "etapa": fala("Certo!")})
    repo.agentes["canal-1"].config.update(CONFIG)
    repo.crm["esc-1"] = {"id_painel": "p1"}
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    def crm():                                           # sem a conferência de entrega (fila própria, fora do CRM)
        return [a for a in repo.acoes if a["tipo"] != "conferir_entrega"]
    assert [a["tipo"] for a in crm()] == ["mover_card", "etiquetar"]             # lead novo
    await atendimento.receber(webhook("caí, 2023, sim, carteira, não, não"))
    await atendimento.aguardar_esperas()
    assert [(a["tipo"], a["dados"].get("id_etapa_helena")) for a in crm()[2:]] == [
        ("mover_card", "s2"), ("etiquetar", None)]
    assert list(repo.turnos.values())[-1]["contexto"]["automacoes"]["gatilhos"] == ["etapa:closer"]


# ----------------------------------------------------------------------------- executor contra a Helena simulada
URL = os.environ.get("AGENTESIA_TESTE_PG_URL")


class HelenaGravando:
    def __init__(self, falhar_tags=0):
        self.chamadas, self.falhar_tags = [], falhar_tags
        self.card = "card-" + uuid.uuid4().hex[:8]

    def __call__(self, pedido: httpx.Request) -> httpx.Response:
        corpo = json.loads(pedido.content) if pedido.content else None
        self.chamadas.append((pedido.method, pedido.url.path, corpo))
        caminho = pedido.url.path
        if caminho.startswith("/chat/v2/session/"):
            return httpx.Response(200, json={"id": "sessao-1", "contactId": "contato-helena-1"})
        if caminho == "/crm/v2/panel/card" and pedido.method == "GET":
            return httpx.Response(200, json={"items": []})
        if caminho == "/crm/v2/panel/card" and pedido.method == "POST":
            return httpx.Response(200, json={"id": self.card})
        if caminho.startswith("/crm/v3/panel/card/"):
            return httpx.Response(200, json={"id": self.card})
        if caminho.endswith("/tags"):
            if self.falhar_tags:
                self.falhar_tags -= 1
                return httpx.Response(500, text="erro")
            return httpx.Response(200, json={})
        if caminho.endswith("/note") or caminho.endswith("/transfer"):
            return httpx.Response(200, json={})
        return httpx.Response(404)


@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_executor_cria_move_etiqueta_e_tenta_de_novo():
    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        # A fila do Executor é global (pega as 10 mais antigas de qualquer escritório). Ações pendentes
        # deixadas por outros testes (ou rodadas anteriores no mesmo banco) entrariam na frente e
        # sujariam helena.chamadas: tira-as da fila, como os outros testes do executor já fazem.
        await pool.execute("update agentesia_acoes set situacao = 'cancelada' where situacao in ('pendente', 'executando')")
        segredo = await pool.fetchval("select vault.create_secret('token-x', 'teste')")
        esc = await pool.fetchval("insert into agentesia_escritorios (nome) values ('Exec') returning id")
        await pool.execute("insert into agentesia_integracoes (id_escritorio, tipo, id_segredo_vault, situacao) "
                           "values ($1, 'helena', $2, 'ok')", esc, segredo)
        canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado) values ($1, $2) returning id",
                                    esc, "5511" + str(uuid.uuid4().int)[:9])
        contato = await pool.fetchval("insert into agentesia_contatos (id_escritorio, nome, telefone_normalizado) "
                                      "values ($1, 'Maria', '5511900000001') returning id", esc)
        lead = await pool.fetchval("insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_sessao_helena) "
                                   "values ($1, $2, $3, 'sessao-1') returning id", esc, contato, canal)

        async def enfileirar(id_lead, acoes):
            for a in acoes:
                a["chave_unica"] += uuid.uuid4().hex                  # turno inventado: chave única por teste
            await repo.enfileirar_acoes(id_escritorio=str(esc), id_lead=str(id_lead), id_turno=None, acoes=acoes)

        await enfileirar(lead, automacoes.montar_acoes(CONFIG, {"id_painel": "p1"}, ["lead_novo"],
                                                       id_lead=str(lead), id_turno="t1"))
        helena = HelenaGravando(falhar_tags=1)
        executor = Executor(pool, "https://api.helena.run", helena_por_token=lambda token, url: HelenaConta(
            token, url, httpx.AsyncClient(transport=httpx.MockTransport(helena))))
        await executor.rodar_uma_vez()
        criado = next(c for m, p, c in helena.chamadas if p == "/crm/v2/panel/card" and m == "POST")
        assert criado["stepId"] == "s1" and criado["contactIds"] == ["contato-helena-1"] and criado["sessionId"] == "sessao-1"
        card = await pool.fetchrow("select * from agentesia_crm_cards where id_lead = $1", lead)
        assert card["id_card_helena"] == helena.card and card["situacao"] == "ok"
        assert await pool.fetchval("select id_contato_helena from agentesia_contatos where id = $1", contato) == "contato-helena-1"
        situacoes = dict(await pool.fetch("select tipo, situacao from agentesia_acoes where id_lead = $1", lead))
        assert situacoes == {"mover_card": "feita", "etiquetar": "pendente"}   # etiqueta falhou: tenta de novo depois

        await pool.execute("update agentesia_acoes set proxima_em = now() where id_lead = $1", lead)
        await executor.rodar_uma_vez()
        assert dict(await pool.fetch("select tipo, situacao from agentesia_acoes where id_lead = $1", lead))["etiquetar"] == "feita"

        # Segunda troca de etapa: o card já existe, então só move.
        await enfileirar(lead, automacoes.montar_acoes(CONFIG, {"id_painel": "p1"}, ["etapa:closer"],
                                                       id_lead=str(lead), id_turno="t2")[:1])
        helena.chamadas.clear()
        await executor.rodar_uma_vez()
        assert [(m, p) for m, p, _ in helena.chamadas] == [("PUT", f"/crm/v3/panel/card/{helena.card}")]
        assert helena.chamadas[0][2] == {"fields": ["StepId"], "stepId": "s2"}

        # Lead sem atendimento na Helena: erro de cadastro vira evento na hora, sem repetir.
        contato2 = await pool.fetchval("insert into agentesia_contatos (id_escritorio, telefone_normalizado) "
                                       "values ($1, '5511900000002') returning id", esc)
        lead2 = await pool.fetchval("insert into agentesia_leads (id_escritorio, id_contato, id_canal) "
                                    "values ($1, $2, $3) returning id", esc, contato2, canal)
        await enfileirar(lead2, [{"tipo": "nota", "chave_unica": "nota-", "dados": {"texto": "oi"}}])
        await executor.rodar_uma_vez()
        assert await pool.fetchval("select situacao from agentesia_acoes where id_lead = $1", lead2) == "falhou"
        evento = await pool.fetchrow("select tipo, responsavel from agentesia_eventos where id_lead = $1", lead2)
        assert (evento["tipo"], evento["responsavel"]) == ("acao_falhou_nota", "cadastro")
    finally:
        await repo.fechar()


@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_aviso_a_equipe_monta_texto_e_envia_a_cada_numero():
    import json as _json

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        await pool.execute("update agentesia_acoes set situacao = 'cancelada' where situacao in ('pendente', 'executando')")  # fila global: ver acima
        segredo = await pool.fetchval("select vault.create_secret('token-aviso', 'teste')")
        esc = await pool.fetchval("insert into agentesia_escritorios (nome) values ('Avisos') returning id")
        await pool.execute("insert into agentesia_integracoes (id_escritorio, tipo, id_segredo_vault, situacao) "
                           "values ($1, 'helena', $2, 'ok')", esc, segredo)
        numero_canal = "5511" + str(uuid.uuid4().int)[:9]
        canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado) values ($1, $2) returning id",
                                    esc, numero_canal)
        contato = await pool.fetchval("insert into agentesia_contatos (id_escritorio, nome, telefone_normalizado) "
                                      "values ($1, 'João Lead', '5511977776666') returning id", esc)
        lead = await pool.fetchval("insert into agentesia_leads (id_escritorio, id_contato, id_canal) "
                                   "values ($1, $2, $3) returning id", esc, contato, canal)
        await pool.execute(
            """insert into agentesia_notificacoes (id_escritorio, tipo_evento, nome, modelo_mensagem, destinatarios)
               values ($1, 'sinal:nao_sabe_ler', 'Não sabe ler', $2, $3::jsonb)""", esc,
            "🔔 {{evento}}\nLead: {{nome}} {{telefone}}\nContrato: {{link_assinatura}}",
            _json.dumps([{"rotulo": "Dra. Ana", "numero": "(11) 91111-2222"}, {"rotulo": "Repetido", "numero": "11911112222"},
                         {"rotulo": "Canal: IA", "numero": numero_canal}, {"rotulo": "Beto", "numero": "11933334444"}]))
        assert await repo.eventos_com_aviso(str(esc)) == {"sinal:nao_sabe_ler"}

        config = {"funcoes": {"avisos": True}, "automacoes": {}}
        acoes = automacoes.montar_acoes(config, None, ["sinal", "sinal:nao_sabe_ler"], id_lead=str(lead),
                                        id_turno=uuid.uuid4().hex, avisos={"sinal:nao_sabe_ler"})
        assert [a["tipo"] for a in acoes] == ["preparar_aviso"]
        await repo.enfileirar_acoes(id_escritorio=str(esc), id_lead=str(lead), id_turno=None, acoes=acoes)

        enviados = []

        def helena(pedido: httpx.Request) -> httpx.Response:
            if pedido.url.path == "/chat/v1/message/send":
                enviados.append(_json.loads(pedido.content))
                return httpx.Response(200, json={"id": f"msg-{len(enviados)}"})
            return httpx.Response(404)

        executor = Executor(pool, "https://api.helena.run", helena_por_token=lambda token, url: HelenaConta(
            token, url, httpx.AsyncClient(transport=httpx.MockTransport(helena))))
        await executor.rodar_uma_vez()                     # prepara: um envio por número
        await executor.rodar_uma_vez()                     # envia
        assert sorted(e["to"] for e in enviados) == ["5511911112222", "5511933334444"]
        texto = enviados[0]["body"]["text"]
        assert "Lead não sabe ler" in texto and "João Lead (11) 97777-6666" in texto and "Contrato:" not in texto
        assert all(e["from"] == numero_canal and e["options"]["hiddenSession"] for e in enviados)
        situacoes = [r["situacao"] for r in await pool.fetch("select situacao from agentesia_acoes where id_lead = $1", lead)]
        assert situacoes == ["feita"] * 3
    finally:
        await repo.fechar()


def test_cada_regra_escolhe_o_departamento():
    config = {"funcoes": {"transferir_humano": True}, "id_equipe_transferencia": "dep-geral",
              "automacoes": automacoes.validar({"pediu_humano": {"transferir": True},
                                                "etapa:closer": {"transferir": True, "id_equipe": "dep-comercial"}})}
    acoes = automacoes.montar_acoes(config, None, ["pediu_humano", "etapa:closer"], id_lead="l", id_turno="t")
    assert [a["dados"]["id_equipe"] for a in acoes] == ["dep-geral", "dep-comercial"]


@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_card_nao_volta_quando_o_lead_ja_avancou():
    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        await pool.execute("update agentesia_acoes set situacao = 'cancelada' where situacao in ('pendente', 'executando')")
        segredo = await pool.fetchval("select vault.create_secret('token-card', 'teste')")
        esc = await pool.fetchval("insert into agentesia_escritorios (nome) values ('Card') returning id")
        await pool.execute("insert into agentesia_integracoes (id_escritorio, tipo, id_segredo_vault, situacao) values ($1, 'helena', $2, 'ok')", esc, segredo)
        canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado) values ($1, $2) returning id",
                                    esc, "5511" + str(uuid.uuid4().int)[:9])
        agente = await pool.fetchval("insert into agentesia_agentes (id_escritorio, id_canal, nome) values ($1, $2, 'J') returning id", esc, canal)
        sdr = await pool.fetchval("insert into agentesia_agente_etapas (id_agente, codigo, ordem, principal) values ($1, 'sdr', 0, true) returning id", agente)
        closer = await pool.fetchval("insert into agentesia_agente_etapas (id_agente, codigo, ordem) values ($1, 'closer', 1) returning id", agente)
        contato = await pool.fetchval("insert into agentesia_contatos (id_escritorio, telefone_normalizado) values ($1, '5511900000077') returning id", esc)
        lead = await pool.fetchval("insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_agente, id_etapa, id_sessao_helena) "
                                   "values ($1, $2, $3, $4, $5, 's') returning id", esc, contato, canal, agente, closer)
        await repo.enfileirar_acoes(id_escritorio=str(esc), id_lead=str(lead), id_turno=None, acoes=[
            {"tipo": "mover_card", "chave_unica": f"velho-{uuid.uuid4().hex}", "dados": {"id_painel": "p1", "id_etapa_helena": "s1", "gatilho": "etapa:sdr"}}])
        chamadas = []
        executor = Executor(pool, "https://api.helena.run", helena_por_token=lambda t, u: HelenaConta(
            t, u, httpx.AsyncClient(transport=httpx.MockTransport(lambda p: (chamadas.append(p.url.path), httpx.Response(200, json={}))[1]))))
        await executor.rodar_uma_vez()
        resultado = await pool.fetchval("select resultado from agentesia_acoes where id_lead = $1", lead)
        assert "ignorada" in str(resultado) and chamadas == []
        assert sdr
    finally:
        await repo.fechar()
