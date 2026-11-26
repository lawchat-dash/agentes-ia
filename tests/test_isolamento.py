"""Isolamento entre escritórios (auditoria): ZapSign, executor da fila, token da plataforma, companyId nos eventos de
etiqueta e de card, e as FKs compostas da migração 014. O link do Controle da IA está em tests/test_controle_ia.py.

Os testes com banco só rodam com AGENTESIA_TESTE_PG_URL (ver tests/test_postgres.py).
"""

import json
import os
import uuid

import asyncpg
import pytest

from app import ia_controle, troca_etapa
from app.acoes import Executor
from app.contrato import servico
from tests.test_gestao import _entrar, ambiente, novos_canais  # noqa: F401  (fixture)

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
pytestmark = pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")


async def _conectar():
    from app.banco.postgres import RepositorioPostgres
    return await RepositorioPostgres.conectar(URL, max_conexoes=1)


async def _escritorio(pool, nome, conta=None):
    """Escritório com token da plataforma, um canal, um contato e um lead."""
    esc = str(await pool.fetchval(
        "insert into agentesia_escritorios (nome, id_conta_helena) values ($1, $2::uuid) returning id", nome, conta))
    token = await pool.fetchval("select vault.create_secret($1, 'teste')", f"token-{uuid.uuid4().hex[:8]}")
    await pool.execute("insert into agentesia_integracoes (id_escritorio, tipo, id_segredo_vault, situacao) "
                       "values ($1::uuid, 'helena', $2, 'ok')", esc, token)
    canal = await pool.fetchval(
        "insert into agentesia_canais (id_escritorio, numero_normalizado, id_canal_helena) values ($1::uuid, $2, $3) returning id",
        esc, "5511" + str(uuid.uuid4().int)[:9], "ch-" + uuid.uuid4().hex[:8])
    contato = await pool.fetchval(
        "insert into agentesia_contatos (id_escritorio, nome, telefone_normalizado) values ($1::uuid, 'Maria', $2) returning id",
        esc, "5511" + str(uuid.uuid4().int)[:9])
    lead = await pool.fetchval(
        "insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_sessao_helena) values ($1::uuid, $2, $3, $4) returning id",
        esc, contato, canal, "sess-" + uuid.uuid4().hex[:6])
    return esc, str(lead), str(contato), str(canal)


# ------------------------------------------------------------------ 2. ZapSign
async def test_zapsign_nao_atravessa_escritorio():
    repo = await _conectar()
    pool = repo._pool
    try:
        esc1, lead1, _, _ = await _escritorio(pool, "Iso Zap 1")
        esc2, lead2, _, _ = await _escritorio(pool, "Iso Zap 2")
        token = "doc-" + uuid.uuid4().hex[:8]
        contrato2 = await pool.fetchval(
            """insert into agentesia_contratos (id_escritorio, id_lead, versao, dados, dados_hash, situacao, provedor,
                                                id_documento_externo, gerado_em)
               values ($1::uuid, $2::uuid, 1, '{}'::jsonb, '', 'gerado', 'zapsign', $3, now()) returning id""",
            esc2, lead2, token)
        # Releitura pelo token: só acha no escritório dono.
        assert (await servico.contrato_para_verificar(pool, id_escritorio=esc1, id_lead=None, token_documento=token)) is None
        achado = await servico.contrato_para_verificar(pool, id_escritorio=esc2, id_lead=None, token_documento=token)
        assert achado and str(achado["id"]) == str(contrato2)
        # Pelo lead: lead de outro escritório não devolve contrato.
        assert (await servico.contrato_para_verificar(pool, id_escritorio=esc1, id_lead=lead2, token_documento=None)) is None
        # Vincular: token que já está em OUTRO escritório é ignorado (não devolve o contrato de lá nem cria versão).
        assert (await servico.vincular_documento(pool, id_escritorio=esc1, id_lead=lead1, token_documento=token,
                                                 como="telefone")) is None
        assert await pool.fetchval("select count(*) from agentesia_contratos where id_lead = $1::uuid", lead1) == 0
        # Lead de outro escritório também é ignorado.
        assert (await servico.vincular_documento(pool, id_escritorio=esc1, id_lead=lead2, token_documento="doc-novo-" + token,
                                                 como="telefone")) is None
        # O caso certo continua: token novo, lead do escritório -> versão nova 'gerado'.
        novo = await servico.vincular_documento(pool, id_escritorio=esc1, id_lead=lead1, token_documento="doc-1-" + token,
                                                como="telefone")
        assert novo and await pool.fetchval("select id_escritorio from agentesia_contratos where id = $1::uuid", novo) == uuid.UUID(esc1)
        # Aviso da ZapSign no webhook do escritório 1 com o token do escritório 2: não mexe no contrato de lá.
        corpo = {"event_type": "doc_signed", "token": token, "signer_who_signed": {"token": "s1", "email": "x@y.com"}}
        assert await servico.receber_webhook(pool, esc1, corpo) == "ignorado:documento_desconhecido"
        assert await pool.fetchval("select count(*) from agentesia_acoes where id_lead = $1::uuid", lead2) == 0
    finally:
        await repo.fechar()


# ------------------------------------------------------------------ 3. executor
async def test_executor_recusa_lead_de_outro_escritorio():
    repo = await _conectar()
    pool = repo._pool
    try:
        esc1, _lead1, _, _ = await _escritorio(pool, "Iso Exec 1")
        _esc2, lead2, _, _ = await _escritorio(pool, "Iso Exec 2")
        chamadas = []

        class HelenaQueAnota:
            def __init__(self, token, url):
                chamadas.append(("token", token))

            def __getattr__(self, nome):
                async def qualquer(*a, **k):
                    chamadas.append((nome, a, k))
                return qualquer

        executor = Executor(pool, "https://api.helena.run", helena_por_token=HelenaQueAnota)
        falhas = []

        async def falhou(acao, erro, definitiva, responsavel):
            falhas.append((erro, definitiva, responsavel))
        executor._falhou = falhou
        # A ação nunca chega ao banco assim (a FK da 014 recusa): aqui ela é montada na mão, como viria de um banco
        # sem a migração.
        for tipo in ("nota", "enviar_mensagem", "resumir_conversa", "alertar_lawchat"):
            await executor._executar({"id": uuid.uuid4(), "id_escritorio": uuid.UUID(esc1), "id_lead": uuid.UUID(lead2),
                                      "id_turno": None, "tipo": tipo, "tentativas": 1,
                                      "dados": json.dumps({"texto": "não pode sair"})})
        assert len(falhas) == 4 and all(d and r == "cadastro" and "não é deste escritório" in e for e, d, r in falhas)
        assert [c for c in chamadas if c[0] != "token"] == []            # nada foi enviado à plataforma
        # _contexto e _lead_completo também filtram o escritório.
        with pytest.raises(Exception, match="não é deste escritório"):
            await executor._contexto(esc1, lead2)
        with pytest.raises(Exception, match="não encontrado neste escritório"):
            await executor._lead_completo(lead2, esc1)
        # Contrato por id de outro escritório: a ação não acha (não relê nem cancela o de lá).
        contrato2 = await pool.fetchval(
            """insert into agentesia_contratos (id_escritorio, id_lead, versao, dados, dados_hash, situacao)
               values ((select id_escritorio from agentesia_leads where id = $1::uuid), $1::uuid, 1, '{}'::jsonb, '',
                       'substituido') returning id""", lead2)
        r = await executor._cancelar_contrato({"id_escritorio": esc1}, {"id_contrato": str(contrato2)})
        assert r == {"cancelado": False, "motivo": "contrato inexistente"}
    finally:
        await repo.fechar()


# ------------------------------------------------------------------ 4. token da plataforma
async def test_token_da_plataforma_conferido(ambiente):  # noqa: F811
    cliente, simulada, email_admin, _banco = ambiente
    await _entrar(cliente, email_admin, "senha-admin-123")
    conta_a, conta_b = str(uuid.uuid4()), str(uuid.uuid4())
    token_a = "token-iso-" + uuid.uuid4().hex[:8]
    nome_b = "Iso Token B " + uuid.uuid4().hex[:6]
    a = await cliente.post("/api/admin/escritorios", json={"nome": "Iso Token A", "id_conta_helena": conta_a,
                                                          "token_helena": token_a})
    assert a.status_code == 200, a.text
    # O mesmo token em outro escritório: recusado, com mensagem clara.
    b = await cliente.post("/api/admin/escritorios", json={"nome": nome_b, "id_conta_helena": conta_b,
                                                          "token_helena": token_a})
    assert b.status_code == 409 and "já está ligado a outro escritório" in b.json()["detail"]
    esc_b = (await cliente.get("/api/admin/escritorios")).json()
    id_b = next(e["id"] for e in esc_b if e["nome"] == nome_b)
    r = await cliente.put("/api/integracoes/helena", json={"token": token_a}, headers={"x-escritorio": id_b})
    assert r.status_code == 409 and "outro escritório" in r.json()["detail"]
    # Token cuja conta (companyId lido na API) é outra: recusado; nada fica gravado.
    token_x = "token-iso-" + uuid.uuid4().hex[:8]
    simulada.canais[f"Bearer {token_x}"] = [{**c, "companyId": conta_a} for c in novos_canais()]
    r = await cliente.put("/api/integracoes/helena", json={"token": token_x}, headers={"x-escritorio": id_b})
    assert r.status_code == 409 and "outra conta" in r.json()["detail"], r.text
    assert (await cliente.get("/api/integracoes", headers={"x-escritorio": id_b})).json()["integracoes"].get("helena") is None
    # Token da conta certa: aceito.
    token_b = "token-iso-" + uuid.uuid4().hex[:8]
    simulada.canais[f"Bearer {token_b}"] = [{**c, "companyId": conta_b.upper()} for c in novos_canais()]
    r = await cliente.put("/api/integracoes/helena", json={"token": token_b}, headers={"x-escritorio": id_b})
    assert r.status_code == 200, r.text


# ------------------------------------------------------------------ 5. companyId nos eventos
async def test_eventos_com_conta_de_outro_escritorio_sao_ignorados():
    repo = await _conectar()
    pool = repo._pool
    try:
        conta = str(uuid.uuid4())
        esc, lead, contato, _ = await _escritorio(pool, "Iso Eventos", conta)
        telefone = await pool.fetchval("select telefone_normalizado from agentesia_contatos where id = $1::uuid", contato)
        etiqueta = {"eventType": "CONTACT_TAG_UPDATE",
                    "content": {"companyId": str(uuid.uuid4()), "phonenumber": telefone, "tags": [ia_controle.ETIQUETA]}}
        r = await ia_controle.receber_evento_de_etiqueta(pool, esc, etiqueta)
        assert r == {"feito": "ignorado", "motivo": "conta_de_outro_escritorio"}
        assert await pool.fetchval("select estado from agentesia_leads where id = $1::uuid", lead) == "ativo"
        # A conta certa (em maiúsculas, tanto faz) passa para a decisão de sempre.
        etiqueta["content"]["companyId"] = conta.upper()
        assert (await ia_controle.receber_evento_de_etiqueta(pool, esc, etiqueta))["feito"] == "ia"

        # Card: escritório SEM conta cadastrada e evento com companyId -> ignorado (antes passava).
        sem_conta, _, _, _ = await _escritorio(pool, "Iso Card")
        card = {"eventType": troca_etapa.EVENTO_CARD,
                "content": {"id": "card-" + uuid.uuid4().hex[:6], "stepId": "s1", "companyId": str(uuid.uuid4())}}
        r = await troca_etapa.receber_evento_de_card(pool, sem_conta, card)
        assert r == {"feito": "ignorado", "motivo": "conta_de_outro_escritorio"}
        r = await troca_etapa.receber_evento_de_card(pool, esc, card)
        assert r == {"feito": "ignorado", "motivo": "conta_de_outro_escritorio"}
    finally:
        await repo.fechar()


# ------------------------------------------------------------------ 7. migração 014
async def test_fks_compostas_recusam_lead_de_outro_escritorio():
    repo = await _conectar()
    pool = repo._pool
    try:
        esc1, lead1, contato1, canal1 = await _escritorio(pool, "Iso FK 1")
        esc2, lead2, _, canal2 = await _escritorio(pool, "Iso FK 2")
        validas = {r["conname"]: r["convalidated"] for r in await pool.fetch(
            "select conname, convalidated from pg_constraint where conname like 'agentesia_%_do_escritorio'")}
        assert set(validas) == {"agentesia_mensagens_lead_do_escritorio", "agentesia_turnos_lead_do_escritorio",
                                "agentesia_acoes_lead_do_escritorio", "agentesia_followups_lead_do_escritorio",
                                "agentesia_leads_contato_do_escritorio", "agentesia_leads_canal_do_escritorio"}
        assert all(validas.values())                                    # banco novo: validadas
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await pool.execute("insert into agentesia_mensagens (id_escritorio, id_lead, autor, texto, enviada_em) values ($1::uuid, $2::uuid, 'lead', 'x', now())",
                               esc1, lead2)
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await pool.execute("insert into agentesia_acoes (id_escritorio, id_lead, tipo, dados) values ($1::uuid, $2::uuid, 'nota', '{}')",
                               esc1, lead2)
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await pool.execute("insert into agentesia_leads (id_escritorio, id_contato, id_canal) values ($1::uuid, $2::uuid, $3::uuid)",
                               esc2, contato1, canal2)          # contato do escritório 1 num lead do 2
        # O certo continua: mesmo escritório, e ação sem lead.
        await pool.execute("insert into agentesia_mensagens (id_escritorio, id_lead, autor, texto, enviada_em) values ($1::uuid, $2::uuid, 'lead', 'x', now())",
                           esc1, lead1)
        await pool.execute("insert into agentesia_acoes (id_escritorio, tipo, dados) values ($1::uuid, 'nota', '{}')", esc1)
    finally:
        await repo.fechar()
