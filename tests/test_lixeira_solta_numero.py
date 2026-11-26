"""Produto na lixeira SOLTA o número de WhatsApp (decisão do dono).

Lixeira: agente pausado e sem número (o anterior fica de histórico), follow-ups cancelados, número disponível para
outro produto. Restaurar: volta pausado e sem número ("precisa ativar"); a ativação pede o número de novo e
reaproveita o agente (prompts, documentos, contrato). Excluir de vez também solta. Um escritório não mexe no outro.
Só roda com AGENTESIA_TESTE_PG_URL (banco local). A Helena é simulada.
"""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from tests.test_gestao import _entrar, ambiente  # noqa: F401  (fixture do painel com a Helena simulada)

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
pytestmark = pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")


async def _escritorio(cliente, pool, nome, token):
    escritorio = (await cliente.post("/api/admin/escritorios", json={
        "nome": nome, "id_conta_helena": str(uuid.uuid4()), "token_helena": token})).json()["escritorio"]
    segredo = await pool.fetchval("select vault.create_secret('token-zapsign', 'teste')")
    await pool.execute(
        "insert into agentesia_integracoes (id_escritorio, tipo, id_segredo_vault, situacao, config) values ($1::uuid, 'zapsign', $2, 'ok', $3::jsonb)",
        escritorio["id"], segredo, json.dumps({"ambiente": "producao"}))
    h = {"x-escritorio": escritorio["id"]}
    canais = (await cliente.get("/api/canais/disponiveis", headers=h)).json()
    return escritorio["id"], h, next(c for c in canais if c["tipo"] != "oficial"), next(c for c in canais if c["tipo"] == "oficial")


async def _produto(cliente, h, nome):
    """Produto do catálogo (publicado, com um documento padrão) e o rascunho do escritório."""
    catalogo = (await cliente.post("/api/admin/biblioteca/produtos/padrao", json={
        "nome": f"{nome} {uuid.uuid4().hex[:4]}", "area_juridica": "Previdenciário", "descricao": nome})).json()
    await cliente.patch(f"/api/admin/biblioteca/produtos/{catalogo['id']}", json={"status": "publicado"})
    documento = await cliente.post(f"/api/admin/biblioteca/produtos/{catalogo['id']}/documentos",
                                   json={"nome": "Tabela", "tipo": "texto", "texto": "Honorários de 30% no êxito."})
    assert documento.status_code == 200, documento.text
    rascunho = (await cliente.post("/api/produtos-ativados/rascunho", headers=h, json={"id_produto_biblioteca": catalogo["id"]})).json()
    agentes = (await cliente.get(f"/api/biblioteca/produtos/{catalogo['id']}/agentes")).json()
    return rascunho["id"], [{"papel": a["papel"], "nome": a["nome_exibicao"], "prompt": f"Prompt {nome} {a['papel']}"} for a in agentes]


def _payload(agentes, canal, **extra):
    return {"nome": "Júlia", "id_canal": canal["id"], "numero_ia": canal["numero"], "agentes": agentes, **extra}


async def _disponivel(cliente, h, canal):
    return next(c for c in (await cliente.get("/api/canais/disponiveis", headers=h)).json() if c["id"] == canal["id"])["disponivel"]


async def _produto_lido(cliente, h, id_produto, lixeira=0):
    return next((p for p in (await cliente.get(f"/api/produtos-ativados?lixeira={lixeira}", headers=h)).json() if p["id"] == id_produto), None)


async def test_lixeira_solta_o_numero_e_restaurar_pede_ativacao(ambiente):
    cliente, _simulada, email_admin, banco = ambiente
    pool = banco._pool
    await _entrar(cliente, email_admin, "senha-admin-123")
    esc1, h1, zapi, oficial = await _escritorio(cliente, pool, "Lixeira 1", "token-bom-123456")
    esc2, h2, zapi2, _oficial2 = await _escritorio(cliente, pool, "Lixeira 2", "token-bom-654321")

    # Escritório 2: um produto ativo no número dele (não pode ser afetado pelo escritório 1).
    id_c, agentes_c = await _produto(cliente, h2, "Outro escritório")
    ativado_c = await cliente.post(f"/api/produtos-ativados/{id_c}/ativar", headers=h2, json=_payload(agentes_c, zapi2))
    assert ativado_c.status_code == 200, ativado_c.text

    # Produto A ativo no número "zapi", com modelo de contrato próprio e um lead com follow-up pendente.
    id_a, agentes_a = await _produto(cliente, h1, "Auxílio")
    assert (await cliente.put(f"/api/integracoes/zapsign/produtos/{id_a}", headers=h1,
                              json={"id_modelo": "modelo-a", "nome": "Contrato A"})).status_code == 200
    ativado = await cliente.post(f"/api/produtos-ativados/{id_a}/ativar", headers=h1, json=_payload(agentes_a, zapi))
    assert ativado.status_code == 200, ativado.text
    id_agente_a = ativado.json()["id_agente"]
    assert not await _disponivel(cliente, h1, zapi)
    escritorio = await banco.escritorio(esc1)
    canal_zapi = await banco.canal(zapi["id"])
    agente_a = await banco.agente_do_canal(zapi["id"])
    assert agente_a.id == id_agente_a
    lead = await banco.achar_ou_criar_lead(escritorio=escritorio, canal=canal_zapi, agente=agente_a,
                                           telefone="55119" + str(uuid.uuid4().int)[:8], id_sessao="sessao-lixeira")
    agora = datetime.now(timezone.utc)
    await pool.execute(
        "insert into agentesia_followups (id_escritorio, id_lead, id_agente, passo, base, agendado_para) values ($1::uuid, $2::uuid, $3::uuid, 0, $4, $5)",
        esc1, lead.id, id_agente_a, agora, agora + timedelta(hours=2))

    # 1. Lixeira (o painel manda o ISO do navegador): solta o número.
    lixo = await cliente.patch(f"/api/produtos-ativados/{id_a}", headers=h1, json={"excluido_em": agora.isoformat()})
    assert lixo.status_code == 200, lixo.text
    agente = await pool.fetchrow("select id_canal, id_canal_anterior, situacao, canal_liberado_em from agentesia_agentes where id = $1::uuid", id_agente_a)
    assert agente["id_canal"] is None and str(agente["id_canal_anterior"]) == zapi["id"]
    assert agente["situacao"] == "pausado" and agente["canal_liberado_em"] is not None
    na_lixeira = await _produto_lido(cliente, h1, id_a, lixeira=1)
    assert na_lixeira["status"] == "pausado" and na_lixeira["numero_ia"] is None
    assert na_lixeira["precisa_ativar"] is True and na_lixeira["numero_liberado"] == zapi["numero"]
    assert "id_canal" not in na_lixeira["rascunho"]["payload_ativacao"] and "numero_ia" not in na_lixeira["rascunho"]["payload_ativacao"]
    assert await pool.fetchval("select situacao from agentesia_followups where id_lead = $1::uuid", lead.id) == "cancelado"
    assert await _disponivel(cliente, h1, zapi)
    assert await banco.agente_do_canal(zapi["id"]) is None          # lead que chega no número solto não cai no agente da lixeira
    # A tela do produto (Conteúdo) continua abrindo a base do agente sem número; as rotas antigas do agente, não.
    docs = await cliente.get(f"/api/agentes/{id_agente_a}/documentos", headers=h1)
    assert docs.status_code == 200, docs.text
    assert (await cliente.get(f"/api/agentes/{id_agente_a}/documentos", headers=h2)).status_code == 404
    assert (await cliente.get(f"/api/agentes/{id_agente_a}/lacunas", headers=h1)).status_code == 200
    # Ligar pelo botão ▶ com o produto na lixeira: não.
    assert (await cliente.post(f"/api/produtos-ativados/{id_a}/status", headers=h1, json={"status": "ativo"})).status_code == 409

    # O escritório 2 continua igual.
    agente_c = await banco.agente_do_canal(zapi2["id"])
    assert agente_c is not None and agente_c.situacao == "ativo"

    # 2. Outro produto ativa no mesmo número e herda o lead (no começo do funil dele).
    id_b, agentes_b = await _produto(cliente, h1, "BPC")
    ativado_b = await cliente.post(f"/api/produtos-ativados/{id_b}/ativar", headers=h1, json=_payload(agentes_b, zapi))
    assert ativado_b.status_code == 200, ativado_b.text
    id_agente_b = ativado_b.json()["id_agente"]
    assert (await banco.agente_do_canal(zapi["id"])).id == id_agente_b
    adotado = await pool.fetchrow(
        "select l.id_agente, e.codigo, e.id_agente as dono_etapa from agentesia_leads l join agentesia_agente_etapas e on e.id = l.id_etapa where l.id = $1::uuid", lead.id)
    assert str(adotado["id_agente"]) == id_agente_b and str(adotado["dono_etapa"]) == id_agente_b and adotado["codigo"] == "sdr"

    # 3. Restaurar: volta pausado e sem número, pedindo ativação. Não rouba o número do B.
    restaurado = await cliente.patch(f"/api/produtos-ativados/{id_a}", headers=h1, json={"excluido_em": None})
    assert restaurado.status_code == 200, restaurado.text
    lido = restaurado.json()
    assert lido["excluido_em"] is None and lido["status"] == "pausado" and lido["precisa_ativar"] is True and lido["numero_ia"] is None
    detalhe = (await cliente.get(f"/api/produtos-ativados/{id_a}", headers=h1)).json()
    assert detalhe["id_canal"] is None and detalhe["agente"]["id_canal"] is None
    assert (await banco.agente_do_canal(zapi["id"])).id == id_agente_b
    assert (await cliente.post(f"/api/produtos-ativados/{id_a}/status", headers=h1, json={"status": "ativo"})).status_code == 409
    sem_numero = await cliente.post(f"/api/produtos-ativados/{id_a}/ativar", headers=h1, json={"reenviar": True})
    assert sem_numero.status_code == 400                               # reenviar a ativação salva não pega o número antigo
    roubo = await cliente.post(f"/api/produtos-ativados/{id_a}/sincronizar", headers=h1, json=_payload(agentes_a, zapi))
    assert roubo.status_code == 409 and "em uso" in roubo.json()["detail"]
    assert (await banco.agente_do_canal(zapi["id"])).id == id_agente_b

    # 4. Reativar com outro número (mesma tela/rota do editor): mesmo agente, prompts, documentos e contrato.
    docs_antes = await pool.fetchval("select count(*) from agentesia_documentos where id_agente = $1::uuid", id_agente_a)
    reativado = await cliente.post(f"/api/produtos-ativados/{id_a}/sincronizar", headers=h1, json=_payload(agentes_a, oficial))
    assert reativado.status_code == 200, reativado.text
    assert reativado.json()["id_agente"] == id_agente_a
    lido = await _produto_lido(cliente, h1, id_a)
    assert lido["status"] == "ativo" and lido["precisa_ativar"] is False and lido["numero_ia"] == oficial["numero"]
    agente = await pool.fetchrow("select id_canal, situacao, canal_liberado_em from agentesia_agentes where id = $1::uuid", id_agente_a)
    assert str(agente["id_canal"]) == oficial["id"] and agente["situacao"] == "ativo" and agente["canal_liberado_em"] is None
    assert await pool.fetchval("select instrucao from agentesia_agente_etapas where id_agente = $1::uuid and codigo = 'sdr'", id_agente_a) == "Prompt Auxílio sdr"
    assert await pool.fetchval("select count(*) from agentesia_documentos where id_agente = $1::uuid", id_agente_a) == docs_antes == 1
    modelos = json.loads(await pool.fetchval(
        "select config from agentesia_integracoes where id_escritorio = $1::uuid and tipo = 'zapsign'", esc1))["modelos"]
    assert [(m["id_modelo"], m["id_agente"]) for m in modelos if m.get("id_ativado") == id_a] == [("modelo-a", id_agente_a)]
    assert (await cliente.post(f"/api/produtos-ativados/{id_a}/status", headers=h1, json={"status": "pausado"})).status_code == 200
    assert (await cliente.post(f"/api/produtos-ativados/{id_a}/status", headers=h1, json={"status": "ativo"})).status_code == 200

    # 5. Isolamento: o escritório 2 não vê, não restaura, não exclui e não usa o número do escritório 1.
    assert (await cliente.get(f"/api/produtos-ativados/{id_a}", headers=h2)).status_code == 404
    assert (await cliente.patch(f"/api/produtos-ativados/{id_b}", headers=h2, json={"excluido_em": agora.isoformat()})).status_code == 404
    assert (await cliente.delete(f"/api/produtos-ativados/{id_b}", headers=h2)).status_code == 404
    alheio = await cliente.post(f"/api/produtos-ativados/{id_c}/sincronizar", headers=h2, json=_payload(agentes_c, oficial))
    assert alheio.status_code == 400
    assert (await banco.agente_do_canal(zapi["id"])).id == id_agente_b and (await banco.agente_do_canal(oficial["id"])).id == id_agente_a
    assert (await banco.agente_do_canal(zapi2["id"])).id == agente_c.id

    # 6. Excluir de vez também solta: B (com lead) fica pausado e sem número; A (sem lead) é apagado.
    assert (await cliente.delete(f"/api/produtos-ativados/{id_b}", headers=h1)).status_code == 200
    agente_b = await pool.fetchrow("select id_canal, id_canal_anterior, situacao from agentesia_agentes where id = $1::uuid", id_agente_b)
    assert agente_b["id_canal"] is None and str(agente_b["id_canal_anterior"]) == zapi["id"] and agente_b["situacao"] == "pausado"
    assert await _disponivel(cliente, h1, zapi) and await banco.agente_do_canal(zapi["id"]) is None
    assert (await cliente.delete(f"/api/produtos-ativados/{id_a}", headers=h1)).status_code == 200
    assert await pool.fetchval("select count(*) from agentesia_agentes where id = $1::uuid", id_agente_a) == 0
    assert await _disponivel(cliente, h1, oficial)
    assert not await _disponivel(cliente, h2, zapi2)                    # o do escritório 2 continua em uso


async def test_restaurar_e_ativar_pausado_e_rascunho_sem_agente(ambiente):
    cliente, _simulada, email_admin, banco = ambiente
    pool = banco._pool
    await _entrar(cliente, email_admin, "senha-admin-123")
    _esc, h, zapi, _oficial = await _escritorio(cliente, pool, "Lixeira 3", "token-bom-777777")

    # Rascunho nunca ativado: lixeira e restaurar não mexem em número nenhum (não há agente).
    id_r, _agentes_r = await _produto(cliente, h, "Rascunho")
    await cliente.post("/api/produtos-ativados/rascunho", headers=h, json={
        "id_produto_biblioteca": (await _produto_lido(cliente, h, id_r))["id_produto_biblioteca"], "numero_ia": zapi["numero"]})
    assert (await cliente.patch(f"/api/produtos-ativados/{id_r}", headers=h, json={"excluido_em": "2026-11-25T10:00:00Z"})).status_code == 200
    assert (await cliente.patch(f"/api/produtos-ativados/{id_r}", headers=h, json={"excluido_em": None})).status_code == 200
    lido = await _produto_lido(cliente, h, id_r)
    assert lido["status"] == "rascunho" and lido["precisa_ativar"] is False and lido["numero_ia"] == zapi["numero"]

    # Ativado → lixeira → restaurado → reativado escolhendo "não ativar agora": volta pausado (nunca rascunho).
    id_a, agentes = await _produto(cliente, h, "Pausado")
    ativado = await cliente.post(f"/api/produtos-ativados/{id_a}/ativar", headers=h, json=_payload(agentes, zapi))
    assert ativado.status_code == 200, ativado.text
    await cliente.patch(f"/api/produtos-ativados/{id_a}", headers=h, json={"excluido_em": "2026-11-25T10:00:00Z"})
    await cliente.patch(f"/api/produtos-ativados/{id_a}", headers=h, json={"excluido_em": None})
    de_novo = await cliente.post(f"/api/produtos-ativados/{id_a}/ativar", headers=h,
                                 json=_payload(agentes, zapi, ativar_imediatamente=False))
    assert de_novo.status_code == 200, de_novo.text
    assert de_novo.json()["id_agente"] == ativado.json()["id_agente"]
    lido = await _produto_lido(cliente, h, id_a)
    assert lido["status"] == "pausado" and lido["precisa_ativar"] is False and lido["numero_ia"] == zapi["numero"]
    assert await pool.fetchval("select situacao from agentesia_agentes where id = $1::uuid", ativado.json()["id_agente"]) == "pausado"


def test_canal_sem_numero_escolhido_nao_trava_a_ativacao():
    """Sem número escolhido, a ativação segue (o número entra depois); número escolhido que não existe continua 400."""
    import asyncio
    from fastapi import HTTPException
    from app.gestao.produtos import Ativar, _canal

    class PoolVazio:
        async def fetchrow(self, *_a):
            return None

    assert asyncio.run(_canal(PoolVazio(), "esc", Ativar(), None)) is None
    try:
        asyncio.run(_canal(PoolVazio(), "esc", Ativar(numero_ia="5511999990000"), None))
        raise AssertionError("devia recusar número que não existe")
    except HTTPException as erro:
        assert erro.status_code == 400
