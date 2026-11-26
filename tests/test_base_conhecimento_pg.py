"""Base de conhecimento no Postgres (migração 003): documentos virtuais, reaproveitamento do vetor pelo hash, escopo por
escritório/papel, reindexação por dimensão e lacunas.

Só roda com AGENTESIA_TESTE_PG_URL (ver tests/test_postgres.py): node db/testes/servidor_local.mjs <porta>.
"""

import json
import os
import uuid

import pytest

from app import conhecimento_indice as indice
from app import vetores
from app.banco.postgres import RepositorioPostgres
from tests.test_base_conhecimento import VetorizadorAssuntos
from tests.test_gestao import ambiente  # noqa: F401 - fixture do painel com Postgres

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
pytestmark = pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")


async def _agente(pool, conhecimento):
    escritorio = await pool.fetchval("insert into agentesia_escritorios (nome) values ('Base Ltda') returning id")
    canal = await pool.fetchval(
        "insert into agentesia_canais (id_escritorio, numero_normalizado) values ($1, $2) returning id",
        escritorio, "55119" + str(uuid.uuid4().int)[:8])
    agente = await pool.fetchval(
        "insert into agentesia_agentes (id_escritorio, id_canal, nome, config) values ($1, $2, 'Ana', $3::jsonb) returning id",
        escritorio, canal, json.dumps({"conhecimento": conhecimento}))
    return str(escritorio), str(agente)


async def test_indexa_virtuais_reaproveita_hash_e_registra_lacuna():
    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        faq = [{"pergunta": "Quanto cobra?", "resposta": "30% do retroativo."},
               {"pergunta": "Quais documentos?", "resposta": "RG e comprovante.", "papeis": ["contratos"]}]
        id_escritorio, id_agente = await _agente(pool, {"faq": faq, "objecoes": []})
        assert await indice.sincronizar_virtuais(pool, id_escritorio, id_agente, {"faq": faq}) == 2
        await pool.execute("""insert into agentesia_documentos (id_escritorio, id_agente, tipo, nome, formato, tamanho_bytes,
                                                                 texto, caracteres, papeis)
                              values ($1, $2, 'texto', 'Contrato', 'texto', 10, $3, 10, '{contratos}')""",
                           id_escritorio, id_agente, "# Cláusulas\n\n" + "Honorários de 30%. " * 80)
        vet = VetorizadorAssuntos()
        assert await indice.indexar_pendentes(pool, vet) >= 3          # o banco de teste pode ter outros pendentes
        vet.textos.clear()
        primeira = 0
        trechos = await indice.trechos_do_agente(pool, id_agente)
        assert {t["fonte"] for t in trechos} == {"faq", "documento"}
        assert next(t for t in trechos if t["titulo"] == "Quais documentos?")["papeis"] == ["contratos"]
        assert all(t["dimensoes"] == vet.dimensoes and t["hash"] and abs(sum(x * x for x in t["vetor_n"]) - 1) < 1e-6
                   for t in trechos)
        assert all(t["titulo"].startswith("Contrato") for t in trechos if t["fonte"] == "documento")

        # Edita só 1 FAQ: só ela é vetorizada de novo; o resto reaproveita o vetor pelo hash.
        faq[0] = {**faq[0], "resposta": "30% do retroativo, só no êxito."}
        await pool.execute("update agentesia_agentes set config = $2::jsonb where id = $1::uuid", id_agente,
                           json.dumps({"conhecimento": {"faq": faq}}))
        assert await indice.sincronizar_virtuais(pool, id_escritorio, id_agente, {"faq": faq}) == 1
        assert await indice.indexar_pendentes(pool, vet) == 1
        assert vet.textos[primeira:] == ["Pergunta: Quanto cobra?\nResposta: 30% do retroativo, só no êxito."]
        # Mudar só os papéis não vetoriza nada.
        faq[1] = {**faq[1], "papeis": ["contratos", "assinatura"]}
        await pool.execute("update agentesia_agentes set config = $2::jsonb where id = $1::uuid", id_agente,
                           json.dumps({"conhecimento": {"faq": faq}}))
        await indice.sincronizar_virtuais(pool, id_escritorio, id_agente, {"faq": faq})
        antes = len(vet.textos)
        assert await indice.indexar_pendentes(pool, vet) == 1 and len(vet.textos) == antes
        trechos = await indice.trechos_do_agente(pool, id_agente)
        assert next(t for t in trechos if t["titulo"] == "Quais documentos?")["papeis"] == ["assinatura", "contratos"]

        # Escopo por escritório: outro escritório nunca vê estes trechos.
        outro, _ = await _agente(pool, {})
        assert await indice.trechos_do_agente(pool, id_agente, id_escritorio=outro) == []
        # Documento ainda sem índice gravado com o agente certo e o escritório errado: não entra na busca por palavras.
        await pool.execute("""insert into agentesia_documentos (id_escritorio, id_agente, tipo, nome, formato, tamanho_bytes,
                                                                 texto, caracteres, situacao)
                              values ($1, $2, 'texto', 'De outro escritório', 'texto', 10, 'segredo', 7, 'erro')""",
                           outro, id_agente)
        assert "De outro escritório" not in [nome for nome, _ in await repo.documentos_do_agente(id_agente)]
        # Vetor com outra dimensão: a base volta para a reindexação.
        assert await indice.marcar_para_reindexar(pool, id_agente, vetores.MODELO, vetores.DIMENSOES) >= 1

        # Lacuna: a mesma dúvida aberta soma.
        assert (await repo.registrar_lacuna(id_escritorio=id_escritorio, id_agente=id_agente, papel="sdr",
                                            pergunta="Tem estacionamento?"))["vezes"] == 1
        assert (await repo.registrar_lacuna(id_escritorio=id_escritorio, id_agente=id_agente, papel="closer",
                                            pergunta="tem estacionamento"))["vezes"] == 2
        # Em reindexação, o documento entra pela busca por palavras; os virtuais (FAQ) nunca: vêm da config.
        assert [nome for nome, _ in await repo.documentos_do_agente(id_agente)] == ["Contrato"]
    finally:
        await repo.fechar()


async def test_rotas_do_painel_papeis_faq_e_perguntas_sem_resposta(ambiente):
    """Painel: documento com papéis, FAQ com papéis (documentos virtuais), lista de lacunas, virar FAQ e ignorar."""
    from tests.test_gestao import _entrar

    cliente, _simulada, email_admin, banco = ambiente
    await _entrar(cliente, email_admin, "senha-admin-123")
    escritorio = (await cliente.post("/api/admin/escritorios", json={
        "nome": "Base Rotas", "id_conta_helena": str(uuid.uuid4()), "token_helena": "token-bom-" + uuid.uuid4().hex[:8]})).json()["escritorio"]
    h = {"x-escritorio": escritorio["id"]}
    canal = next(c for c in (await cliente.get("/api/integracoes", headers=h)).json()["canais"] if c["tipo"] != "oficial")
    agente = (await cliente.post("/api/agentes", headers=h, json={"nome": "Ana", "id_canal": canal["id"]})).json()
    base_url = f"/api/agentes/{agente['id']}"

    doc = (await cliente.post(f"{base_url}/documentos", headers=h, json={
        "nome": "Contrato", "tipo": "texto", "texto": "Documentos aceitos: RG ou CNH.", "papeis": ["contratos", "x"]})).json()
    assert doc["papeis"] == ["contratos", "x"]
    assert (await cliente.put(f"{base_url}/documentos/{doc['id']}/papeis", headers=h, json={"papeis": ["contratos"]})).json()["papeis"] == ["contratos"]
    alterado = await cliente.patch(base_url, headers=h, json={"conhecimento": {
        "faq": [{"pergunta": "Precisa ir aí?", "resposta": "Não, é online.", "papeis": ["sdr"]}],
        "objecoes": [], "dados_escritorio": "Rua A, 1", "teto_documentos": 2500}})
    assert alterado.status_code == 200, alterado.text
    config = json.loads(await banco._pool.fetchval("select config from agentesia_agentes where id = $1::uuid", agente["id"]))
    assert config["conhecimento"]["faq"][0]["papeis"] == ["sdr"] and config["conhecimento"]["teto_documentos"] == 2500
    virtuais = await banco._pool.fetch("select tipo, situacao from agentesia_documentos where id_agente = $1::uuid and tipo in ('faq','objecoes')",
                                       agente["id"])
    assert {v["tipo"] for v in virtuais} == {"faq", "objecoes"}
    lista = (await cliente.get(f"{base_url}/documentos", headers=h)).json()
    assert [(d["nome"], d["papeis"]) for d in lista] == [("Contrato", ["contratos"])]       # virtuais não aparecem

    for _ in range(2):
        await banco.registrar_lacuna(id_escritorio=escritorio["id"], id_agente=agente["id"], papel="sdr", pergunta="Tem estacionamento?")
    await banco.registrar_lacuna(id_escritorio=escritorio["id"], id_agente=agente["id"], papel="closer", pergunta="Aceita cartão?")
    abertas = (await cliente.get(f"{base_url}/lacunas", headers=h)).json()
    assert [(l["pergunta"], l["vezes"]) for l in abertas] == [("Tem estacionamento?", 2), ("Aceita cartão?", 1)]
    feito = await cliente.post(f"{base_url}/lacunas/{abertas[0]['id']}/responder", headers=h,
                               json={"resposta": "Sim, há vagas conveniadas.", "papeis": ["sdr"]})
    assert feito.status_code == 200, feito.text
    config = json.loads(await banco._pool.fetchval("select config from agentesia_agentes where id = $1::uuid", agente["id"]))
    assert config["conhecimento"]["faq"][-1] == {"pergunta": "Tem estacionamento?", "resposta": "Sim, há vagas conveniadas.",
                                                 "papeis": ["sdr"]}
    assert (await cliente.post(f"{base_url}/lacunas/{abertas[1]['id']}/ignorar", headers=h)).status_code == 200
    assert (await cliente.get(f"{base_url}/lacunas", headers=h)).json() == []
    assert len((await cliente.get(f"{base_url}/lacunas?situacao=respondida", headers=h)).json()) == 1
    assert (await cliente.post(f"{base_url}/lacunas/{abertas[1]['id']}/ignorar", headers=h)).status_code == 404
