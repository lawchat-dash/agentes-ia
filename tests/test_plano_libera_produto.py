"""Plano da conta libera produtos (mesma regra do Weaver): sem plano = tudo liberado; plano que não cria agentes
bloqueia; plano mínimo do produto pela ordem. A trava vale no rascunho e na primeira ativação. Banco local + Helena simulada."""

import uuid

from app import cobranca

from tests.test_gestao import _entrar, ambiente  # noqa: F401  (fixture do painel com a Helena simulada)
from tests.test_lixeira_solta_numero import _escritorio, _payload, _produto, pytestmark  # noqa: F401


async def _plano(pool, esc, codigo):
    await pool.execute("insert into agentesia_carteiras (id_escritorio) values ($1::uuid) on conflict do nothing", esc)
    await pool.execute("update agentesia_carteiras set id_plano = (select id from agentesia_planos where codigo = $2) where id_escritorio = $1::uuid",
                       esc, codigo)


async def test_plano_trava_e_libera_a_ativacao(ambiente):
    cliente, _simulada, email_admin, banco = ambiente
    pool = banco._pool
    await _entrar(cliente, email_admin, "senha-admin-123")
    esc, h, zapi, _oficial = await _escritorio(cliente, pool, "Planos", "token-bom-" + uuid.uuid4().hex[:8])

    # Sem plano: liberado (a rota /api/plano manda plano = None para a tela).
    assert await cobranca.plano_da_conta(pool, esc) is None
    id_p, agentes = await _produto(cliente, h, "Auxílio")
    id_catalogo = await pool.fetchval("select id_produto_biblioteca::text from agentesia_produtos_ativados where id = $1::uuid", id_p)

    # Bronze (não cria agentes): bloqueia a ativação e um rascunho novo.
    await _plano(pool, esc, "start")
    r = await cliente.post(f"/api/produtos-ativados/{id_p}/ativar", headers=h, json=_payload(agentes, zapi))
    assert r.status_code == 403 and "não permite criar agentes" in r.text
    plano = await cobranca.plano_da_conta(pool, esc)
    assert plano["codigo"] == "start" and plano["cria_agentes"] is False

    # Prata com produto que pede Ouro: inferior.
    await _plano(pool, esc, "pro")
    await pool.execute("update agentesia_biblioteca_produtos set plano_minimo = 'master' where id = $1::uuid", id_catalogo)
    r = await cliente.post(f"/api/produtos-ativados/{id_p}/ativar", headers=h, json=_payload(agentes, zapi))
    assert r.status_code == 403 and "inferior ao plano mínimo" in r.text
    r = await cliente.post("/api/produtos-ativados/rascunho", headers=h, json={"id_produto_biblioteca": id_catalogo})
    assert r.status_code == 403

    # Produto que pede Prata: ativa.
    await pool.execute("update agentesia_biblioteca_produtos set plano_minimo = 'pro' where id = $1::uuid", id_catalogo)
    r = await cliente.post(f"/api/produtos-ativados/{id_p}/ativar", headers=h, json=_payload(agentes, zapi))
    assert r.status_code == 200, r.text

    # Caiu para Bronze depois de ativado: o agente que existe continua (só barra novas ativações).
    await _plano(pool, esc, "start")
    r = await cliente.post(f"/api/produtos-ativados/{id_p}/sincronizar", headers=h, json=_payload(agentes, zapi))
    assert r.status_code == 200, r.text
