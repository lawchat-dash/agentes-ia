"""Arquivar um agente (migração 016): para de atender, cancela os follow-ups pendentes, sai da lista principal com
a marca "arquivado" e segura o número. Ligar/pausar com ele arquivado: não. Restaurar volta pausado, no mesmo número.
Só roda com AGENTESIA_TESTE_PG_URL (banco local). A Helena é simulada.
"""

import uuid
from datetime import datetime, timedelta, timezone

from tests.test_gestao import _entrar, ambiente  # noqa: F401  (fixture do painel com a Helena simulada)
from tests.test_lixeira_solta_numero import _disponivel, _escritorio, _payload, _produto, _produto_lido, pytestmark  # noqa: F401


async def test_arquivar_para_de_atender_e_restaurar_volta_pausado(ambiente):
    cliente, _simulada, email_admin, banco = ambiente
    pool = banco._pool
    await _entrar(cliente, email_admin, "senha-admin-123")
    esc, h, zapi, _oficial = await _escritorio(cliente, pool, "Arquivo", "token-bom-" + uuid.uuid4().hex[:8])
    id_p, agentes = await _produto(cliente, h, "Auxílio")
    ativado = await cliente.post(f"/api/produtos-ativados/{id_p}/ativar", headers=h, json=_payload(agentes, zapi))
    assert ativado.status_code == 200, ativado.text
    id_agente = ativado.json()["id_agente"]
    assert (await _produto_lido(cliente, h, id_p))["arquivado"] is False

    escritorio = await banco.escritorio(esc)
    agente = await banco.agente_do_canal(zapi["id"])
    lead = await banco.achar_ou_criar_lead(escritorio=escritorio, canal=await banco.canal(zapi["id"]), agente=agente,
                                           telefone="55119" + str(uuid.uuid4().int)[:8], id_sessao="sessao-arquivo")
    agora = datetime.now(timezone.utc)
    await pool.execute(
        "insert into agentesia_followups (id_escritorio, id_lead, id_agente, passo, base, agendado_para) values ($1::uuid, $2::uuid, $3::uuid, 0, $4, $5)",
        esc, lead.id, id_agente, agora, agora + timedelta(hours=2))

    arquivado = await cliente.post(f"/api/produtos-ativados/{id_p}/arquivar", headers=h)
    assert arquivado.status_code == 200, arquivado.text
    assert arquivado.json()["arquivado"] is True and arquivado.json()["status"] == "pausado"
    assert await pool.fetchval("select situacao from agentesia_agentes where id = $1::uuid", id_agente) == "arquivado"
    assert await pool.fetchval("select situacao from agentesia_followups where id_lead = $1::uuid", lead.id) == "cancelado"
    assert (await banco.agente_do_canal(zapi["id"])).situacao != "ativo"      # o motor não responde
    assert not await _disponivel(cliente, h, zapi)                            # o número continua com ele
    # Ligar ou pausar com ele arquivado: não (nem pela rota antiga do agente).
    assert (await cliente.post(f"/api/produtos-ativados/{id_p}/status", headers=h, json={"status": "ativo"})).status_code == 409
    assert (await cliente.post(f"/api/agentes/{id_agente}/ativacao", headers=h, json={"situacao": "ativo"})).status_code == 409
    assert (await cliente.post(f"/api/produtos-ativados/{id_p}/arquivar", headers=h)).status_code == 200   # de novo: nada muda

    restaurado = await cliente.post(f"/api/produtos-ativados/{id_p}/desarquivar", headers=h)
    assert restaurado.status_code == 200, restaurado.text
    assert restaurado.json()["arquivado"] is False and restaurado.json()["status"] == "pausado"
    assert await pool.fetchval("select situacao from agentesia_agentes where id = $1::uuid", id_agente) == "pausado"
    ligado = await cliente.post(f"/api/produtos-ativados/{id_p}/status", headers=h, json={"status": "ativo"})
    assert ligado.status_code == 200, ligado.text
    assert (await banco.agente_do_canal(zapi["id"])).situacao == "ativo"
