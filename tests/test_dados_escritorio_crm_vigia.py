"""Primeiros passos novos: Dados do escritório (GET/PUT /api/escritorio/dados), etapas do CRM marcadas pelo cliente
(PUT /api/integracoes/crm/etapas) e o vigia do webhook (app/vigia.webhooks_ligados).

Os testes com banco só rodam com AGENTESIA_TESTE_PG_URL (ver tests/test_postgres.py).
"""

import json
import os
import uuid
from pathlib import Path

import pytest

from app.canal import helena_conta
from tests.test_gestao import _entrar, ambiente  # noqa: F401  (fixture do painel com a plataforma simulada)

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
RAIZ = Path(__file__).resolve().parent.parent
pg = pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")

PAINEL_6 = {"id": "painel-ia", "titulo": "🤖 CRM COMERCIAL IA", "tipo": "SALE", "etapas": [
    {"id": "c1", "titulo": "📞SDR"}, {"id": "c2", "titulo": "🛒 Comercial"}, {"id": "c3", "titulo": "📄 Contrato em Elaboração"},
    {"id": "c4", "titulo": "✍️ Aguardando Assinatura"}, {"id": "c5", "titulo": "✅ Contrato Assinado"},
    {"id": "c6", "titulo": "❌ Desqualificado"}]}
MAPA = {"SDR": "c1", "COMERCIAL": "c2", "CONTRATO": "c3", "AGUARDANDO_ASSINATURA": "c4", "CONTRATO_ASSINADO": "c5",
        "DESQUALIFICADO": "c6"}


def _incluir_rotas(cliente):
    from app.gestao.rotas_dados_escritorio import api as api_dados
    app = cliente._transport.app
    if not any(getattr(r, "path", "") == "/api/escritorio/dados" for r in app.router.routes):
        app.include_router(api_dados)


async def _conta(cliente, nome):
    escritorio = (await cliente.post("/api/admin/escritorios", json={
        "nome": nome, "id_conta_helena": str(uuid.uuid4()), "token_helena": f"token-bom-{uuid.uuid4().hex[:8]}"})).json()["escritorio"]
    return escritorio["id"], {"x-escritorio": escritorio["id"]}


def _passos(r):
    return {p["codigo"]: p for p in r["passos"]}


def test_campos_e_telas():
    from app.gestao.rotas_dados_escritorio import CAMPOS
    chaves = [c["chave"] for c in CAMPOS]
    assert chaves[0] == "nome" and {"cnpj", "oab", "endereco", "instagram", "facebook", "site", "logo"} <= set(chaves)
    # Os nomes mais usados no catálogo são preenchidos pelo campo certo.
    preenche = {n: c["chave"] for c in CAMPOS for n in c["preenche"]}
    assert preenche["NOME ESCRITORIO"] == "nome" and preenche["CNPJ"] == "cnpj" and preenche["LINK AVALIACAO GOOGLE"] == "avaliacao_google"
    estrutura = (RAIZ / "painel" / "src" / "componentes" / "Estrutura.tsx").read_text(encoding="utf-8")
    assert '{ para: "/dados-escritorio", rotulo: "Dados do escritório"' in estrutura
    ativacao = (RAIZ / "painel" / "src" / "components" / "agent" / "ProductConfigurator.tsx").read_text(encoding="utf-8")
    assert "lerDadosDoEscritorio" in ativacao and "applyGlobalField(nome, valor)" in ativacao


@pg
async def test_dados_do_escritorio_marcam_o_passo(ambiente):  # noqa: F811
    cliente, _simulada, email_admin, banco = ambiente
    _incluir_rotas(cliente)
    await _entrar(cliente, email_admin, "senha-admin-123")
    id_escritorio, h = await _conta(cliente, f"Dados {uuid.uuid4().hex[:4]}")

    vazio = (await cliente.get("/api/escritorio/dados", headers=h)).json()
    assert vazio["preenchido"] is False and vazio["valores"] == {} and vazio["campos"][0]["chave"] == "nome"
    assert _passos((await cliente.get("/api/inicio/primeiros-passos", headers=h)).json())["dados"]["situacao"] == "pendente"

    # Sem nome não salva; campo desconhecido é recusado.
    assert (await cliente.put("/api/escritorio/dados", headers=h, json={"valores": {"cnpj": "1"}})).status_code == 400
    assert (await cliente.put("/api/escritorio/dados", headers=h, json={"valores": {"nome": "X", "senha": "1"}})).status_code == 400

    r = await cliente.put("/api/escritorio/dados", headers=h, json={"valores": {
        "nome": "  Silva   &  Associados ", "cnpj": "00.000.000/0001-00", "instagram": "@silva", "site": ""}})
    assert r.status_code == 200, r.text
    assert r.json()["valores"] == {"nome": "Silva & Associados", "cnpj": "00.000.000/0001-00", "instagram": "@silva"}
    lido = (await cliente.get("/api/escritorio/dados", headers=h)).json()
    assert lido["preenchido"] is True and lido["valores"]["nome"] == "Silva & Associados"
    # Guardado no escritório, sem apagar o resto do config.
    config = await banco._pool.fetchval("select config from agentesia_escritorios where id = $1::uuid", id_escritorio)
    config = json.loads(config) if isinstance(config, str) else config
    assert config["dados_escritorio"]["cnpj"] == "00.000.000/0001-00"
    passo = _passos((await cliente.get("/api/inicio/primeiros-passos", headers=h)).json())["dados"]
    assert passo["situacao"] == "feito" and "Silva & Associados" in passo["detalhe"]

    # Outro escritório não vê estes dados.
    _outro, h2 = await _conta(cliente, f"Outro {uuid.uuid4().hex[:4]}")
    assert (await cliente.get("/api/escritorio/dados", headers=h2)).json()["valores"] == {}


@pg
async def test_etapas_do_crm_marcadas_pelo_cliente(ambiente, monkeypatch):  # noqa: F811
    cliente, _simulada, email_admin, banco = ambiente
    _incluir_rotas(cliente)

    async def paineis(self):
        return [PAINEL_6, {"id": "outro", "titulo": "Outro", "tipo": "SALE", "etapas": [{"id": "x1", "titulo": "Novo"}]}]
    monkeypatch.setattr(helena_conta.HelenaConta, "paineis", paineis)
    await _entrar(cliente, email_admin, "senha-admin-123")
    id_escritorio, h = await _conta(cliente, f"Crm {uuid.uuid4().hex[:4]}")
    assert _passos((await cliente.get("/api/inicio/primeiros-passos", headers=h)).json())["crm"]["situacao"] == "pendente"

    url = "/api/integracoes/crm/etapas"
    # Falta etapa, etapa desconhecida, coluna de outro painel e painel que não existe: tudo recusado.
    assert (await cliente.put(url, headers=h, json={"id_painel": "painel-ia", "etapas_por_tipo": {"SDR": "c1"}})).status_code == 400
    assert (await cliente.put(url, headers=h, json={"id_painel": "painel-ia", "etapas_por_tipo": {**MAPA, "OUTRA": "c1"}})).status_code == 400
    assert (await cliente.put(url, headers=h, json={"id_painel": "painel-ia", "etapas_por_tipo": {**MAPA, "SDR": "x1"}})).status_code == 400
    assert (await cliente.put(url, headers=h, json={"id_painel": "nao-existe", "etapas_por_tipo": MAPA})).status_code == 404

    r = await cliente.put(url, headers=h, json={"id_painel": "painel-ia", "titulo_painel": "🤖 CRM COMERCIAL IA", "etapas_por_tipo": MAPA})
    assert r.status_code == 200, r.text
    crm = (await cliente.get("/api/integracoes", headers=h)).json()["integracoes"]["crm"]
    assert crm["config"]["id_painel"] == "painel-ia" and crm["config"]["etapas_por_tipo"] == MAPA
    passo = _passos((await cliente.get("/api/inicio/primeiros-passos", headers=h)).json())["crm"]
    assert passo["situacao"] == "feito" and "6 etapas" in passo["detalhe"]

    # Escritório sem a coluna "Desqualificado": marca "não uso" e o passo fica pronto; a SDR nunca pode ficar sem coluna.
    sem_desq = {t: c for t, c in MAPA.items() if t != "DESQUALIFICADO"}
    assert (await cliente.put(url, headers=h, json={"id_painel": "painel-ia", "etapas_por_tipo": {t: c for t, c in MAPA.items() if t != "SDR"},
                                                    "etapas_sem_uso": ["SDR"]})).status_code == 400
    assert (await cliente.put(url, headers=h, json={"id_painel": "painel-ia", "etapas_por_tipo": sem_desq})).status_code == 400
    r = await cliente.put(url, headers=h, json={"id_painel": "painel-ia", "etapas_por_tipo": sem_desq, "etapas_sem_uso": ["DESQUALIFICADO"]})
    assert r.status_code == 200, r.text
    crm = (await cliente.get("/api/integracoes", headers=h)).json()["integracoes"]["crm"]
    assert crm["config"]["etapas_por_tipo"] == sem_desq and crm["config"]["etapas_sem_uso"] == ["DESQUALIFICADO"]
    passo = _passos((await cliente.get("/api/inicio/primeiros-passos", headers=h)).json())["crm"]
    assert passo["situacao"] == "feito" and "5 etapas" in passo["detalhe"] and "1 sem uso" in passo["detalhe"]


@pg
async def test_roteiro_so_no_plano_com_midia(ambiente):  # noqa: F811
    cliente, _simulada, email_admin, banco = ambiente
    pool = banco._pool
    await _entrar(cliente, email_admin, "senha-admin-123")
    id_escritorio, h = await _conta(cliente, f"Roteiro {uuid.uuid4().hex[:4]}")
    tem_roteiro = await pool.fetchval(
        """select exists(select 1 from agentesia_biblioteca_produtos b join agentesia_roteiro_partes r on r.id_produto_biblioteca = b.id
                         and r.ativo where b.modo_midia = 'audio' and b.status = 'publicado')""")
    codigos = [p["codigo"] for p in (await cliente.get("/api/inicio/primeiros-passos", headers=h)).json()["passos"]]
    assert ("roteiro" in codigos) == bool(tem_roteiro)            # conta sem plano: liberada
    # Plano sem mídia (Prata): o passo some.
    plano = await pool.fetchval("insert into agentesia_planos (codigo, nome, midia) values ($1, 'Prata', false) returning id",
                                f"p{uuid.uuid4().hex[:6]}")
    await pool.execute("""insert into agentesia_carteiras (id_escritorio, id_plano) values ($1::uuid, $2)
                          on conflict (id_escritorio) do update set id_plano = excluded.id_plano""", id_escritorio, plano)
    codigos = [p["codigo"] for p in (await cliente.get("/api/inicio/primeiros-passos", headers=h)).json()["passos"]]
    assert "roteiro" not in codigos


@pg
async def test_vigia_confere_e_refaz_o_webhook(ambiente):  # noqa: F811
    from app import vigia
    cliente, simulada, email_admin, banco = ambiente
    pool = banco._pool
    await _entrar(cliente, email_admin, "senha-admin-123")
    id_escritorio, h = await _conta(cliente, f"Vigia {uuid.uuid4().hex[:4]}")
    assert (await cliente.post("/api/integracoes/helena/conectar", headers=h)).status_code == 200

    async def config():
        valor = await pool.fetchval("select config from agentesia_integracoes where id_escritorio = $1::uuid and tipo = 'helena'",
                                    id_escritorio)
        return json.loads(valor) if isinstance(valor, str) else valor

    assert (await config())["webhook_situacao"] == "ok"
    # Tudo certo: confere e não mexe.
    assert await vigia.webhooks_ligados(pool, so_escritorio=id_escritorio) == 1
    assert (await config())["webhook_situacao"] == "ok" and (await config())["webhook_conferido_em"]

    # A assinatura sumiu da plataforma: o vigia recria sozinho e avisa a equipe.
    simulada.assinaturas.clear()
    await vigia.webhooks_ligados(pool, so_escritorio=id_escritorio)
    assert len(simulada.assinaturas) == 1 and (await config())["webhook_situacao"] == "corrigido"
    assert await pool.fetchval("select count(*) from agentesia_eventos where id_escritorio = $1::uuid and tipo = 'webhook_refeito'",
                               id_escritorio) == 1

    # Token passou a ser recusado: não dá para refazer -> desconectado, aviso uma vez só (não a cada volta).
    await pool.execute(
        """select vault.update_secret((select id_segredo_vault from agentesia_integracoes
                                        where id_escritorio = $1::uuid and tipo = 'helena'), $2)""",
        id_escritorio, "token-ruim-" + uuid.uuid4().hex[:6])
    await vigia.webhooks_ligados(pool, so_escritorio=id_escritorio)
    await vigia.webhooks_ligados(pool, so_escritorio=id_escritorio)
    c = await config()
    assert c["webhook_situacao"] == "desconectado" and c["webhook_conectado"] is False and "recusou" in c["webhook_erro"]
    assert await pool.fetchval("select count(*) from agentesia_eventos where id_escritorio = $1::uuid and tipo = 'webhook_desconectado'",
                               id_escritorio) == 1

    # Desligado por variável: não confere nada.
    import os as _os
    _os.environ["AGENTESIA_VIGIA_WEBHOOK"] = "0"
    try:
        assert await vigia.webhooks_ligados(pool, so_escritorio=id_escritorio) == 0
    finally:
        _os.environ.pop("AGENTESIA_VIGIA_WEBHOOK", None)
