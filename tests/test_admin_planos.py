"""Admin › Planos: recursos do plano (017), preço anual, exclusão protegida e adicionais mensais."""
import uuid

import pytest

from tests.test_cobranca import api_cobranca, com_banco  # noqa: F401  (fixture)


@com_banco
async def test_planos_com_recursos_e_adicionais(api_cobranca):  # noqa: F811
    pool, esc, cliente = api_cobranca
    async with cliente("admin_lawchat") as admin, cliente("gestor") as gestor:
        # Carga da 017: 5 planos e 4 adicionais.
        planos = (await admin.get("/api/admin/planos")).json()
        por_codigo = {p["codigo"]: p for p in planos}
        assert {"start", "pro", "pro_plus", "master", "enterprise"} <= set(por_codigo)
        ouro = por_codigo["master"]
        assert ouro["usuarios"] == 5 and ouro["canais_whatsapp"] == 2 and ouro["ia_inclusa"] and ouro["preco_anual_brl"] is None
        assert por_codigo["enterprise"]["sob_proposta"] is True
        # 019: "Mídia e roteiros" ligado em pro_plus, master e enterprise (sem a 019 o campo não vem).
        tem_019 = bool(await pool.fetchval("select 1 from information_schema.columns where table_schema = 'public' "
                                           "and table_name = 'agentesia_planos' and column_name = 'midia'"))
        if tem_019:
            assert ouro["midia"] is True and por_codigo["pro_plus"]["midia"] is True and por_codigo["enterprise"]["midia"] is True
            assert por_codigo["start"]["midia"] is False
        else:
            assert "midia" not in ouro
        adicionais = (await admin.get("/api/admin/adicionais")).json()
        assert {a["codigo"] for a in adicionais} >= {"ativacao_ia", "usuario", "canal", "automacao"}
        assert (await gestor.get("/api/admin/adicionais")).status_code == 403
        # A tela da conta: sem plano = None; com plano, vem o plano e a escada.
        assert (await gestor.get("/api/plano")).json()["plano"] is None
        await pool.execute("update agentesia_carteiras set id_plano = (select id from agentesia_planos where codigo = 'pro') where id_escritorio = $1::uuid", esc)
        tela = (await gestor.get("/api/plano")).json()
        assert tela["plano"]["nome"] == "Prata" and tela["plano"]["cria_agentes"] and {"start", "pro", "master"} <= {p["codigo"] for p in tela["planos"]}
        await pool.execute("update agentesia_carteiras set id_plano = null where id_escritorio = $1::uuid", esc)

        # Criar com recursos, mudar o anual e voltar para o automático.
        cod = f"t{uuid.uuid4().hex[:6]}"
        novo = (await admin.post("/api/admin/planos", json={"codigo": cod, "nome": "Teste", "preco_mensal_brl": 100,
                                                            "bonus_mensal_brl": 10, "usuarios": 7, "cria_agentes": True,
                                                            "selo": "🥇"})).json()
        assert novo["usuarios"] == 7 and novo["cria_agentes"] and novo["selo"] == "🥇"
        if tem_019:
            assert novo["midia"] is False
            assert (await admin.patch(f"/api/admin/planos/{novo['id']}", json={"midia": True})).json()["midia"] is True
        r = (await admin.patch(f"/api/admin/planos/{novo['id']}", json={"preco_anual_brl": 999, "canais_instagram": 3})).json()
        assert r["preco_anual_brl"] == 999 and r["canais_instagram"] == 3
        r = (await admin.patch(f"/api/admin/planos/{novo['id']}", json={"limpar_preco_anual": True})).json()
        assert r["preco_anual_brl"] is None

        # Plano em uso não é excluído; livre, é.
        await pool.execute("update agentesia_carteiras set id_plano = $1::uuid where id_escritorio = $2::uuid", novo["id"], esc)
        assert (await admin.delete(f"/api/admin/planos/{novo['id']}")).status_code == 409
        await pool.execute("update agentesia_carteiras set id_plano = null where id_escritorio = $1::uuid", esc)
        assert (await admin.delete(f"/api/admin/planos/{novo['id']}")).status_code == 200
        assert not await pool.fetchval("select 1 from agentesia_planos where id = $1::uuid", novo["id"])

        # Adicional: criar, alterar, código repetido, excluir.
        cod_a = f"a{uuid.uuid4().hex[:6]}"
        a = (await admin.post("/api/admin/adicionais", json={"codigo": cod_a, "nome": "Extra", "preco_mensal_brl": 9.9})).json()
        assert (await admin.post("/api/admin/adicionais", json={"codigo": cod_a, "nome": "Extra", "preco_mensal_brl": 1})).status_code == 409
        a = (await admin.patch(f"/api/admin/adicionais/{a['id']}", json={"ativo": False, "preco_mensal_brl": 19.9})).json()
        assert a["ativo"] is False and a["preco_mensal_brl"] == 19.9
        assert (await admin.delete(f"/api/admin/adicionais/{a['id']}")).status_code == 200
