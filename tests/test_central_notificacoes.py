"""Central de notificações do sino (app/gestao/rotas_central_notificacoes.py): lead qualificado, IA pausada, IA
desligada à mão, contrato enviado e assinado; contagem de não lidas e "marcar como lidas"; um escritório nunca vê a
notificação de outro; erro técnico nunca aparece.

Os testes com banco só rodam com AGENTESIA_TESTE_PG_URL (ver tests/test_postgres.py).
"""

import json
import os
import uuid
from pathlib import Path

import pytest

from app.gestao import rotas_central_notificacoes as cn
from app.gestao import seguranca
from tests.test_gestao import _entrar, ambiente  # noqa: F401  (fixture)

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
RAIZ = Path(__file__).resolve().parent.parent
pg = pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")


# ------------------------------------------------------------------ sem banco
def test_textos_em_portugues_simples():
    assert cn._texto("lead_qualificado", "Maria Souza", "Previdenciário BPC") == \
        ("Lead qualificado: Maria Souza", "Previdenciário BPC")
    assert cn._texto("pediu_humano", "Ana", None)[0] == "IA pausada: o lead pediu um atendente"
    assert cn._texto("contrato_assinado", "João", None)[0] == "Contrato assinado por João"
    assert cn._texto("sinal_quer_videochamada", "Ana", None)[0] == "Lead pediu videochamada"
    assert cn._grupo("contrato_enviado") == "contrato" and cn._grupo("lead_suspeito") == "pausa"
    for titulo in [*cn.PAUSAS.values()]:
        assert "Helena" not in titulo


def test_rota_registrada_no_painel():
    main = (RAIZ / "app" / "main.py").read_text(encoding="utf-8")
    assert "from app.gestao.rotas_central_notificacoes import api as api_central_notificacoes" in main
    from app.servidor import criar_app, rotas_montadas
    caminhos = rotas_montadas(criar_app("painel"))
    assert {"/api/central-notificacoes", "/api/central-notificacoes/lidas"} <= caminhos
    assert (RAIZ / "db" / "migracoes" / "015_agentesia_central_notificacoes.sql").exists()


# ------------------------------------------------------------------ com banco
async def _escritorio(pool, nome):
    esc = str(await pool.fetchval("insert into agentesia_escritorios (nome) values ($1) returning id", nome))
    canal = await pool.fetchval(
        "insert into agentesia_canais (id_escritorio, numero_normalizado, id_canal_helena) values ($1::uuid, $2, $3) returning id",
        esc, "5511" + str(uuid.uuid4().int)[:9], "ch-" + uuid.uuid4().hex[:8])
    agente = await pool.fetchval(
        "insert into agentesia_agentes (id_escritorio, id_canal, nome) values ($1::uuid, $2, 'Previdenciário BPC') returning id",
        esc, canal)
    email = f"gestor-{uuid.uuid4().hex[:6]}@escritorio.com"
    await pool.execute(
        """insert into agentesia_usuarios (email, nome, senha_hash, papel, id_escritorio, trocar_senha)
           values ($1, 'Gestor', $2, 'gestor', $3::uuid, false)""", email, seguranca.gerar_hash("senha-gestor-123"), esc)
    return esc, str(canal), str(agente), email


async def _lead(pool, esc, canal, agente, nome):
    contato = await pool.fetchval(
        "insert into agentesia_contatos (id_escritorio, nome, telefone_normalizado) values ($1::uuid, $2, $3) returning id",
        esc, nome, "5511" + str(uuid.uuid4().int)[:9])
    return str(await pool.fetchval(
        """insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_agente)
           values ($1::uuid, $2, $3::uuid, $4::uuid) returning id""", esc, contato, canal, agente))


async def _semear_tudo(pool, esc, canal, agente, marca):
    maria = await _lead(pool, esc, canal, agente, f"Maria Souza {marca}")
    joao = await _lead(pool, esc, canal, agente, f"João {marca}")
    await pool.execute("""insert into agentesia_lead_etapas (id_escritorio, id_lead, etapa_de, etapa_para, origem)
                          values ($1::uuid, $2::uuid, 'sdr', 'closer', 'ia')""", esc, maria)
    await pool.execute("""insert into agentesia_eventos (id_escritorio, id_lead, tipo, gravidade, responsavel, descricao)
                          values ($1::uuid, $2::uuid, 'pediu_humano', 'aviso', 'lead', 'Lead: pediu_humano'),
                                 ($1::uuid, $2::uuid, 'resposta_vazia', 'erro', 'lawchat', 'erro técnico'),
                                 ($1::uuid, $2::uuid, 'sinal_recusado', 'info', 'lawchat', 'recusado')""", esc, joao)
    await pool.execute(
        """insert into agentesia_alteracoes (id_escritorio, tabela, id_registro, acao, resumo, depois)
           values ($1::uuid, 'agentesia_leads', null, 'desligou_ia', 'IA desativada', $2::jsonb)""",
        esc, json.dumps({"leads": [joao]}))
    await pool.execute(
        """insert into agentesia_contratos (id_escritorio, id_lead, versao, dados, dados_hash, situacao, gerado_em,
                                            lead_assinou_em, assinado_em)
           values ($1::uuid, $2::uuid, 1, '{}'::jsonb, 'h', 'assinado', now() - interval '1 minute', now(), now())""",
        esc, joao)
    return maria, joao


@pg
async def test_central_lista_conta_marca_e_isola(ambiente):  # noqa: F811
    cliente, _simulada, _email_admin, banco = ambiente
    cliente._transport.app.include_router(cn.api)
    pool = banco._pool
    marca = uuid.uuid4().hex[:6]
    esc_a, canal_a, agente_a, email_a = await _escritorio(pool, f"Central A {marca}")
    esc_b, canal_b, agente_b, email_b = await _escritorio(pool, f"Central B {marca}")
    maria, joao = await _semear_tudo(pool, esc_a, canal_a, agente_a, marca)

    # Gestor do escritório A: vê as 5 notificações de negócio, nenhuma técnica.
    await _entrar(cliente, email_a, "senha-gestor-123")
    r = await cliente.get("/api/central-notificacoes")
    assert r.status_code == 200, r.text
    d = r.json()
    tipos = sorted(i["tipo"] for i in d["itens"])
    assert tipos == ["contrato_assinado", "contrato_enviado", "ia_desativada", "lead_qualificado", "pediu_humano"]
    assert "resposta_vazia" not in r.text and "erro técnico" not in r.text and "Helena" not in r.text
    assert d["nao_lidas"] == 5 and all(not i["lida"] for i in d["itens"])
    qualificado = next(i for i in d["itens"] if i["tipo"] == "lead_qualificado")
    assert qualificado["titulo"] == f"Lead qualificado: Maria Souza {marca}" and qualificado["id_lead"] == maria
    assert qualificado["detalhe"] == "Previdenciário BPC" and qualificado["grupo"] == "qualificado"
    assinado = next(i for i in d["itens"] if i["tipo"] == "contrato_assinado")
    assert assinado["titulo"] == f"Contrato assinado por João {marca}" and assinado["id_lead"] == joao
    assert d["itens"][0]["momento"] >= d["itens"][-1]["momento"]           # mais novas primeiro
    assert len((await cliente.get("/api/central-notificacoes", params={"limite": 2})).json()["itens"]) == 2

    # Marcar como lidas: zera a contagem; algo novo depois volta a contar 1.
    r = await cliente.post("/api/central-notificacoes/lidas", json={})
    assert r.status_code == 200 and r.json()["lido_ate"]
    d = (await cliente.get("/api/central-notificacoes")).json()
    assert d["nao_lidas"] == 0 and all(i["lida"] for i in d["itens"])
    await pool.execute("""insert into agentesia_eventos (id_escritorio, id_lead, tipo, gravidade, responsavel, descricao)
                          values ($1::uuid, $2::uuid, 'lead_suspeito', 'aviso', 'cliente', 'suspeito')""", esc_a, maria)
    d = (await cliente.get("/api/central-notificacoes")).json()
    assert d["nao_lidas"] == 1 and d["itens"][0]["tipo"] == "lead_suspeito" and not d["itens"][0]["lida"]
    # "ate" no passado não faz a leitura voltar atrás.
    await cliente.post("/api/central-notificacoes/lidas", json={"ate": "2020-01-01T00:00:00Z"})
    assert (await cliente.get("/api/central-notificacoes")).json()["nao_lidas"] == 1

    # Gestor do escritório B: não vê nada do A (nem forçando o cabeçalho de escritório).
    await _entrar(cliente, email_b, "senha-gestor-123")
    d = (await cliente.get("/api/central-notificacoes")).json()
    assert d["itens"] == [] and d["nao_lidas"] == 0
    forcado = await cliente.get("/api/central-notificacoes", headers={"x-escritorio": esc_a})
    assert forcado.status_code in (200, 403) and marca not in forcado.text
    # Um lead do B com evento gravado (por engano) com o escritório A não vaza para o A nem para o B.
    lead_b = await _lead(pool, esc_b, canal_b, agente_b, f"Pedro B {marca}")
    await pool.execute("""insert into agentesia_eventos (id_escritorio, id_lead, tipo, gravidade, responsavel, descricao)
                          values ($1::uuid, $2::uuid, 'pediu_humano', 'aviso', 'lead', 'x')""", esc_a, lead_b)
    await _entrar(cliente, email_a, "senha-gestor-123")
    assert f"Pedro B {marca}" not in (await cliente.get("/api/central-notificacoes")).text

    # A leitura é por usuário: a do gestor A não marca nada para outro usuário do mesmo escritório.
    assert await pool.fetchval("select count(*) from agentesia_notificacoes_leitura where id_escritorio = $1::uuid",
                               esc_b) == 0
