"""Modelo de contrato (ZapSign) por produto: salvar o produto B não apaga o do produto A.

Regressão do defeito do sistema antigo: a tela de contrato de cada produto mandava a lista inteira
com um só modelo (padrão, sem id_agente) e apagava o modelo dos outros produtos.
"""

import json
import os
import uuid

import httpx
import pytest

from app.acoes import Executor
from app.contrato import dados as cdados
from app.contrato import modelos as cmodelos
from tests.test_gestao import ambiente  # noqa: F401  (fixture do painel com a Helena simulada)

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
FATOS = {"nome_completo": "Maria da Silva", "cpf": "52998224725", "cep": "01310100", "endereco": "Avenida Paulista",
         "numero_casa": "1000", "bairro": "Bela Vista", "cidade": "São Paulo", "uf": "sp"}


def _item(id_modelo, **extra):
    return cmodelos.normalizar({"id_modelo": id_modelo, "nome": id_modelo.upper(), **extra})


# ----------------------------------------------------------------------------- funções puras
def test_salvar_o_produto_b_nao_apaga_o_a_e_nao_duplica():
    lista = cmodelos.salvar_do_produto([], _item("modelo-a"), "prod-a", None)
    assert lista[0]["padrao"] is True and lista[0]["id_ativado"] == "prod-a"      # o primeiro da conta vira padrão
    lista = cmodelos.salvar_do_produto(lista, _item("modelo-b"), "prod-b", "agente-b")
    assert [(m["id_ativado"], m["id_modelo"], m["padrao"]) for m in lista] == [("prod-a", "modelo-a", True), ("prod-b", "modelo-b", False)]
    # Trocar o modelo do B: o A fica igual, o B não duplica e não rouba o padrão.
    lista = cmodelos.salvar_do_produto(lista, _item("modelo-b2"), "prod-b", "agente-b")
    lista = cmodelos.salvar_do_produto(lista, _item("modelo-b2"), "prod-b", "agente-b")
    assert [(m["id_ativado"], m["id_modelo"], m["padrao"]) for m in lista] == [("prod-a", "modelo-a", True), ("prod-b", "modelo-b2", False)]
    assert cmodelos.modelo_do_produto(lista, "prod-b", None)["id_modelo"] == "modelo-b2"
    assert cmodelos.modelo_do_produto(lista, "prod-c", None) is None and cmodelos.padrao(lista)["id_modelo"] == "modelo-a"


def test_item_antigo_por_agente_e_absorvido_sem_duplicar():
    antigo = _item("modelo-velho", id_agente="agente-a")
    lista = cmodelos.salvar_do_produto([_item("geral", padrao=True), antigo], _item("modelo-novo"), "prod-a", "agente-a")
    assert [(m["id_modelo"], m["id_agente"], m["id_ativado"]) for m in lista] == [("geral", None, None), ("modelo-novo", "agente-a", "prod-a")]
    # Ativação: o item salvo antes de existir o agente ganha o id_agente; o resto não muda.
    salvo_antes = cmodelos.salvar_do_produto(lista, _item("modelo-c"), "prod-c", None)
    ligado = cmodelos.vincular_agente(salvo_antes, "prod-c", "agente-c")
    assert [m["id_agente"] for m in ligado] == [None, "agente-a", "agente-c"]
    assert cmodelos.vincular_agente(ligado, "prod-c", "agente-c") is None                    # reativar: nada muda
    assert cmodelos.vincular_agente(ligado, "prod-x", "agente-x") is None                    # produto sem modelo próprio
    # Um item só com o mesmo agente (sem produto) é absorvido: o agente não fica com dois modelos.
    dois = ligado + [_item("sobra", id_agente="agente-c")]
    assert [m["id_modelo"] for m in cmodelos.vincular_agente(dois, "prod-c", "agente-c")] == ["geral", "modelo-novo", "modelo-c"]


def test_tela_integracoes_troca_so_o_geral():
    lista = [_item("geral-velho", padrao=True), _item("modelo-a", id_ativado="prod-a"), _item("modelo-b", id_ativado="prod-b", id_agente="ag-b")]
    nova = cmodelos.juntar_da_tela(lista, [_item("geral-novo", padrao=True)], lista_completa=False)
    assert [(m["id_modelo"], m["padrao"]) for m in nova] == [("geral-novo", True), ("modelo-a", False), ("modelo-b", False)]
    # Um item de produto enviado troca só o daquele produto.
    nova = cmodelos.juntar_da_tela(nova, [_item("geral-novo", padrao=True), _item("modelo-b2", id_agente="ag-b")], lista_completa=False)
    assert [m["id_modelo"] for m in nova] == ["geral-novo", "modelo-a", "modelo-b2"]
    # Só com lista_completa a lista é substituída.
    assert [m["id_modelo"] for m in cmodelos.juntar_da_tela(nova, [_item("unico")], lista_completa=True)] == ["unico"]
    # Sem geral nenhum: um padrão continua existindo (o do produto que já era).
    so_produto = cmodelos.juntar_da_tela([_item("modelo-a", id_ativado="prod-a", padrao=True)], [], lista_completa=False)
    assert [(m["id_modelo"], m["padrao"]) for m in so_produto] == [("modelo-a", True)]


def test_motor_escolhe_o_modelo_do_agente_do_lead():
    lista = [_item("modelo-a", id_ativado="prod-a", id_agente="ag-a", padrao=True), _item("modelo-b", id_ativado="prod-b", id_agente="ag-b")]
    assert Executor._modelo_do_contrato({"modelos": lista}, "ag-a")["id_modelo"] == "modelo-a"
    assert Executor._modelo_do_contrato({"modelos": lista}, "ag-b")["id_modelo"] == "modelo-b"
    assert Executor._modelo_do_contrato({"modelos": lista}, "ag-sem-modelo")["id_modelo"] == "modelo-a"   # cai no padrão


# ----------------------------------------------------------------------------- API do painel
@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_dois_produtos_com_modelos_diferentes_pela_api(ambiente):
    from tests.test_gestao import _entrar

    cliente, _simulada, email_admin, banco = ambiente
    pool = banco._pool
    await _entrar(cliente, email_admin, "senha-admin-123")
    escritorio = (await cliente.post("/api/admin/escritorios", json={
        "nome": "Dois Produtos", "id_conta_helena": str(uuid.uuid4()), "token_helena": "token-bom-123456"})).json()["escritorio"]
    h = {"x-escritorio": escritorio["id"]}
    segredo = await pool.fetchval("select vault.create_secret('token-zapsign', 'teste')")
    await pool.execute(
        "insert into agentesia_integracoes (id_escritorio, tipo, id_segredo_vault, situacao, config) values ($1::uuid, 'zapsign', $2, 'ok', $3::jsonb)",
        escritorio["id"], segredo, json.dumps({"ambiente": "producao", "limite_versoes": 3}))

    # Dois produtos do catálogo, cada um com o seu rascunho.
    rascunhos = []
    for nome in ("Auxílio", "BPC"):
        produto = (await cliente.post("/api/admin/biblioteca/produtos/padrao", json={
            "nome": f"{nome} {uuid.uuid4().hex[:4]}", "area_juridica": "Previdenciário", "descricao": nome})).json()
        await cliente.patch(f"/api/admin/biblioteca/produtos/{produto['id']}", json={"status": "publicado"})
        rascunhos.append((await cliente.post("/api/produtos-ativados/rascunho", headers=h, json={"id_produto_biblioteca": produto["id"]})).json())
    id_a, id_b = rascunhos[0]["id"], rascunhos[1]["id"]
    rota = "/api/integracoes/zapsign/produtos/"

    assert (await cliente.get(rota + id_a, headers=h)).json() == {"modelo": None, "padrao": None}
    salvo_a = await cliente.put(rota + id_a, headers=h, json={"id_modelo": "modelo-a", "nome": "Contrato A",
                                                              "mapeamento": [{"variavel": "NOME", "campo": "nome"}]})
    assert salvo_a.status_code == 200, salvo_a.text
    assert salvo_a.json()["modelo"]["padrao"] is True                          # o primeiro modelo da conta vira padrão
    leitura_b = (await cliente.get(rota + id_b, headers=h)).json()
    assert leitura_b["modelo"] is None and leitura_b["padrao"]["id_modelo"] == "modelo-a"   # B ainda usa o padrão

    # Salvar o B (duas vezes) não apaga o A e não duplica.
    for _ in range(2):
        assert (await cliente.put(rota + id_b, headers=h, json={"id_modelo": "modelo-b", "nome": "Contrato B"})).status_code == 200
    modelos = (await cliente.get("/api/integracoes", headers=h)).json()["integracoes"]["zapsign"]["config"]["modelos"]
    assert [(m["id_ativado"], m["id_modelo"], m["padrao"]) for m in modelos] == [(id_a, "modelo-a", True), (id_b, "modelo-b", False)]
    assert (await cliente.get(rota + id_a, headers=h)).json()["modelo"]["id_modelo"] == "modelo-a"
    assert (await cliente.get(rota + id_b, headers=h)).json()["modelo"]["id_modelo"] == "modelo-b"

    # Tela Integrações (modelo geral) não apaga os dos produtos e preserva o resto da config.
    tela = await cliente.put("/api/integracoes/zapsign/config", headers=h, json={
        "modelos": [{"id_modelo": "geral", "nome": "Geral", "padrao": True}], "limite_versoes": 4})
    assert tela.status_code == 200, tela.text
    config = tela.json()["config"]
    assert [m["id_modelo"] for m in config["modelos"]] == ["geral", "modelo-a", "modelo-b"]
    assert [m["id_modelo"] for m in config["modelos"] if m["padrao"]] == ["geral"]
    assert config["limite_versoes"] == 4 and config["ambiente"] == "producao"

    # Produto de outro escritório ou id torto: 404.
    assert (await cliente.get(rota + str(uuid.uuid4()), headers=h)).status_code == 404
    assert (await cliente.put(rota + "nao-e-uuid", headers=h, json={"id_modelo": "x"})).status_code == 404

    # Ativar o A: o item dele ganha o id_agente (é por ele que o motor escolhe). Reativar não duplica.
    canais = (await cliente.get("/api/canais/disponiveis", headers=h)).json()
    livre = next(c for c in canais if c["disponivel"] and c["tipo"] != "oficial")
    agentes = (await cliente.get(f"/api/biblioteca/produtos/{rascunhos[0]['id_produto_biblioteca']}/agentes")).json()
    payload = {"nome": "Júlia", "id_canal": livre["id"], "ativar_imediatamente": True,
               "agentes": [{"papel": a["papel"], "nome": a["nome_exibicao"], "prompt": "Prompt"} for a in agentes]}
    ativado = await cliente.post(f"/api/produtos-ativados/{id_a}/ativar", headers=h, json=payload)
    assert ativado.status_code == 200, ativado.text
    id_agente = ativado.json()["id_agente"]
    assert (await cliente.post(f"/api/produtos-ativados/{id_a}/sincronizar", headers=h, json=payload)).status_code == 200
    assert (await cliente.put(rota + id_a, headers=h, json={"id_modelo": "modelo-a", "nome": "Contrato A"})).status_code == 200
    modelos = json.loads(await pool.fetchval(
        "select config from agentesia_integracoes where id_escritorio = $1::uuid and tipo = 'zapsign'", escritorio["id"]))["modelos"]
    assert [(m["id_modelo"], m["id_agente"]) for m in modelos] == [("geral", None), ("modelo-a", id_agente), ("modelo-b", None)]
    assert Executor._modelo_do_contrato({"modelos": modelos}, id_agente)["id_modelo"] == "modelo-a"

    # Trocar o token não apaga a lista de modelos.
    from app.gestao.repositorio import RepositorioGestao
    await RepositorioGestao(pool).salvar_integracao(escritorio["id"], "zapsign", config={"modelos_na_conta": 7})
    modelos = (await cliente.get("/api/integracoes", headers=h)).json()["integracoes"]["zapsign"]["config"]["modelos"]
    assert len(modelos) == 3


# ----------------------------------------------------------------------------- motor
@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_motor_gera_cada_contrato_com_o_modelo_do_seu_produto():
    from app.banco.postgres import RepositorioPostgres
    from app.canal.helena_conta import HelenaConta
    from app.canal.zapsign import ZapSign
    from app.modelo import ModeloFalso
    from tests.test_contrato import ZapSignFalsa

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        await pool.execute("update agentesia_acoes set situacao = 'cancelada' where situacao in ('pendente', 'executando')")
        token_h = await pool.fetchval("select vault.create_secret('token-helena', 'teste')")
        token_z = await pool.fetchval("select vault.create_secret('token-zapsign', 'teste')")
        esc = await pool.fetchval("insert into agentesia_escritorios (nome) values ('Dois produtos') returning id")
        await pool.execute("insert into agentesia_integracoes (id_escritorio, tipo, id_segredo_vault, situacao) values ($1, 'helena', $2, 'ok')", esc, token_h)
        agentes, leads = {}, {}
        for nome in ("a", "b", "c"):
            canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado, id_canal_helena) values ($1, $2, $3) returning id",
                                        esc, "5511" + str(uuid.uuid4().int)[:9], "ch-" + uuid.uuid4().hex[:6])
            agente = await pool.fetchval(
                "insert into agentesia_agentes (id_escritorio, id_canal, nome, produto, config) values ($1, $2, $3, 'auxilio_acidente', $4::jsonb) returning id",
                esc, canal, f"Agente {nome}", json.dumps({"funcoes": {"contrato_zapsign": True}}))
            etapa = await pool.fetchval(
                "insert into agentesia_agente_etapas (id_agente, codigo, ordem, tipo, principal) values ($1, 'coleta_dados', 0, 'conversa', true) returning id", agente)
            await pool.execute("insert into agentesia_agente_etapas (id_agente, codigo, ordem, tipo) values ($1, 'assinatura', 1, 'conversa')", agente)
            contato = await pool.fetchval(
                "insert into agentesia_contatos (id_escritorio, nome, telefone_normalizado) values ($1, 'Maria', $2) returning id", esc, "55119" + str(uuid.uuid4().int)[:8])
            leads[nome] = await pool.fetchval(
                "insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_agente, id_etapa, id_sessao_helena) values ($1, $2, $3, $4, $5, $6) returning id",
                esc, contato, canal, agente, etapa, "sessao-" + nome)
            agentes[nome] = str(agente)
        # Produto A e B com modelo próprio (A é o padrão); o agente C não tem modelo: usa o padrão.
        modelos = cmodelos.salvar_do_produto([], _item("modelo-a"), str(uuid.uuid4()), agentes["a"])
        modelos = cmodelos.salvar_do_produto(modelos, _item("modelo-b"), str(uuid.uuid4()), agentes["b"])
        await pool.execute(
            "insert into agentesia_integracoes (id_escritorio, tipo, id_segredo_vault, situacao, config) values ($1, 'zapsign', $2, 'ok', $3::jsonb)",
            esc, token_z, json.dumps({"modelos": modelos, "lembretes": {"ativo": False}}))

        dados, _ = cdados.validar_dados(cdados.dados_dos_fatos(FATOS), "5511988887777")
        hash_dados = cdados.hash_dados(dados)
        for nome in ("b", "a", "c"):
            await repo.enfileirar_acoes(id_escritorio=str(esc), id_lead=str(leads[nome]), id_turno=None, acoes=[
                {"tipo": "gerar_contrato", "chave_unica": f"{leads[nome]}:contrato:{hash_dados}", "dados": {"dados": dados, "hash": hash_dados}}])

        zapsign = ZapSignFalsa()
        executor = Executor(pool, "https://api.helena.run",
                            helena_por_token=lambda t, u: HelenaConta(t, u, httpx.AsyncClient(transport=httpx.MockTransport(
                                lambda _p: httpx.Response(200, json={"id": "m"})))),
                            zapsign_por_token=lambda t, u: ZapSign(t, u, httpx.AsyncClient(transport=httpx.MockTransport(zapsign))),
                            modelo=ModeloFalso({}))
        for _ in range(6):
            await executor.rodar_uma_vez()
        usados = {}
        for nome in ("a", "b", "c"):
            usados[nome] = await pool.fetchval("select id_modelo from agentesia_contratos where id_lead = $1", leads[nome])
        assert usados == {"a": "modelo-a", "b": "modelo-b", "c": "modelo-a"}, usados
        assert sorted(c["template_id"] for c in zapsign.criados) == ["modelo-a", "modelo-a", "modelo-b"]
    finally:
        await repo.fechar()


# ----------------------------------------------------------------------------- exclusão, corrida e isolamento
def test_excluir_produto_tira_so_o_modelo_dele_e_o_padrao_vira_geral():
    lista = cmodelos.salvar_do_produto([], _item("modelo-a"), "prod-a", "ag-a")
    lista = cmodelos.salvar_do_produto(lista, _item("modelo-b"), "prod-b", None)
    lista = cmodelos.salvar_do_produto(lista, _item("modelo-c"), "prod-c", "ag-c")
    # B (não padrão, rascunho sem agente): sai; os outros ficam como estavam.
    sem_b = cmodelos.remover_do_produto(lista, "prod-b", None)
    assert [(m["id_modelo"], m["id_ativado"], m["padrao"]) for m in sem_b] == [("modelo-a", "prod-a", True), ("modelo-c", "prod-c", False)]
    assert cmodelos.remover_do_produto(sem_b, "prod-b", None) is None                         # nada a mudar
    # A era o padrão: fica como modelo geral; quem não tem modelo próprio continua com o mesmo contrato.
    sem_a = cmodelos.remover_do_produto(sem_b, "prod-a", "ag-a")
    assert [(m["id_modelo"], m["id_ativado"], m["id_agente"], m["padrao"]) for m in sem_a] == [
        ("modelo-a", None, None, True), ("modelo-c", "prod-c", "ag-c", False)]
    assert Executor._modelo_do_contrato({"modelos": sem_a}, "ag-a")["id_modelo"] == "modelo-a"
    assert Executor._modelo_do_contrato({"modelos": sem_a}, "ag-c")["id_modelo"] == "modelo-c"
    assert Executor._modelo_do_contrato({"modelos": sem_a}, "ag-x")["id_modelo"] == "modelo-a"
    # Escritório com um modelo só, do produto excluído: vira o geral (não some o contrato dos outros agentes).
    um = cmodelos.salvar_do_produto([], _item("unico"), "prod-u", "ag-u")
    assert [(m["id_modelo"], m["id_ativado"], m["padrao"]) for m in cmodelos.remover_do_produto(um, "prod-u", "ag-u")] == [("unico", None, True)]


@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_excluir_corrida_da_ativacao_e_outro_escritorio_pela_api(ambiente, monkeypatch):
    from app.gestao import rotas
    from tests.test_gestao import _entrar

    cliente, _simulada, email_admin, banco = ambiente
    pool = banco._pool
    await _entrar(cliente, email_admin, "senha-admin-123")
    escritorios = []
    for nome in ("Três Produtos", "Outro Escritório"):
        esc = (await cliente.post("/api/admin/escritorios", json={
            "nome": nome, "id_conta_helena": str(uuid.uuid4()), "token_helena": "token-bom-123456"})).json()["escritorio"]
        segredo = await pool.fetchval("select vault.create_secret('token-zapsign', 'teste')")
        await pool.execute(
            "insert into agentesia_integracoes (id_escritorio, tipo, id_segredo_vault, situacao, config) values ($1::uuid, 'zapsign', $2, 'ok', $3::jsonb)",
            esc["id"], segredo, json.dumps({"ambiente": "producao"}))
        escritorios.append(esc)
    h, h2 = {"x-escritorio": escritorios[0]["id"]}, {"x-escritorio": escritorios[1]["id"]}

    rascunhos = []
    for nome in ("Auxílio", "BPC", "Pensão", "Outro"):
        produto = (await cliente.post("/api/admin/biblioteca/produtos/padrao", json={
            "nome": f"{nome} {uuid.uuid4().hex[:4]}", "area_juridica": "Previdenciário", "descricao": nome})).json()
        await cliente.patch(f"/api/admin/biblioteca/produtos/{produto['id']}", json={"status": "publicado"})
        cab = h2 if nome == "Outro" else h
        rascunhos.append((await cliente.post("/api/produtos-ativados/rascunho", headers=cab, json={"id_produto_biblioteca": produto["id"]})).json())
    id_a, id_b, id_c, id_outro = (r["id"] for r in rascunhos)
    rota = "/api/integracoes/zapsign/produtos/"

    async def modelos(esc):
        return json.loads(await pool.fetchval(
            "select config from agentesia_integracoes where id_escritorio = $1::uuid and tipo = 'zapsign'", esc["id"])).get("modelos") or []

    for id_p, m in ((id_a, "modelo-a"), (id_b, "modelo-b")):          # o C ainda sem modelo próprio
        assert (await cliente.put(rota + id_p, headers=h, json={"id_modelo": m, "nome": m})).status_code == 200
    assert (await cliente.put(rota + id_outro, headers=h2, json={"id_modelo": "modelo-outro"})).status_code == 200

    # Outro escritório: não lê nem grava o produto deste, e a lista dele não se mistura.
    assert (await cliente.get(rota + id_a, headers=h2)).status_code == 404
    assert (await cliente.put(rota + id_a, headers=h2, json={"id_modelo": "invasor"})).status_code == 404
    assert (await cliente.get(rota + id_outro, headers=h)).status_code == 404
    assert [m["id_modelo"] for m in await modelos(escritorios[0])] == ["modelo-a", "modelo-b"]
    assert [(m["id_modelo"], m["padrao"]) for m in await modelos(escritorios[1])] == [("modelo-outro", True)]

    # Excluir o B (rascunho): só o modelo dele sai.
    assert (await cliente.delete(f"/api/produtos-ativados/{id_b}", headers=h)).status_code == 200
    assert [(m["id_modelo"], m["padrao"]) for m in await modelos(escritorios[0])] == [("modelo-a", True)]

    # Corrida: a tela leu o produto C antes da ativação terminar (id_agente ainda vazio) e grava o
    # primeiro modelo dele depois. Com a trava, relê o produto e o item fica com o id_agente: o motor o acha.
    canais = (await cliente.get("/api/canais/disponiveis", headers=h)).json()
    livre = next(c for c in canais if c["disponivel"] and c["tipo"] != "oficial")
    agentes = (await cliente.get(f"/api/biblioteca/produtos/{rascunhos[2]['id_produto_biblioteca']}/agentes")).json()
    payload = {"nome": "Júlia", "id_canal": livre["id"], "ativar_imediatamente": True,
               "agentes": [{"papel": a["papel"], "nome": a["nome_exibicao"], "prompt": "Prompt"} for a in agentes]}
    ativado = await cliente.post(f"/api/produtos-ativados/{id_c}/ativar", headers=h, json=payload)
    assert ativado.status_code == 200, ativado.text
    id_agente_c = ativado.json()["id_agente"]
    original = rotas._produto_ativado

    async def lido_antes_da_ativacao(repo, id_escritorio, id_ativado):
        return {**await original(repo, id_escritorio, id_ativado), "id_agente": None}

    monkeypatch.setattr(rotas, "_produto_ativado", lido_antes_da_ativacao)
    assert (await cliente.put(rota + id_c, headers=h, json={"id_modelo": "modelo-c2", "nome": "C2"})).status_code == 200
    monkeypatch.setattr(rotas, "_produto_ativado", original)
    lista = await modelos(escritorios[0])
    assert [(m["id_modelo"], m["id_agente"]) for m in lista] == [("modelo-a", None), ("modelo-c2", id_agente_c)]
    assert Executor._modelo_do_contrato({"modelos": lista}, id_agente_c)["id_modelo"] == "modelo-c2"

    # Excluir o A, que era o padrão: o modelo dele vira o geral (o padrão do escritório não some).
    assert (await cliente.delete(f"/api/produtos-ativados/{id_a}", headers=h)).status_code == 200
    lista = await modelos(escritorios[0])
    assert [(m["id_modelo"], m["id_ativado"], m["padrao"]) for m in lista] == [("modelo-a", None, True), ("modelo-c2", id_c, False)]
    # Excluir o C ativado (sem leads: o agente é apagado): o modelo dele sai; o do outro escritório fica.
    assert (await cliente.delete(f"/api/produtos-ativados/{id_c}", headers=h)).status_code == 200
    assert [(m["id_modelo"], m["padrao"]) for m in await modelos(escritorios[0])] == [("modelo-a", True)]
    assert [m["id_modelo"] for m in await modelos(escritorios[1])] == ["modelo-outro"]
    # Produto excluído: a rota dele dá 404.
    assert (await cliente.put(rota + id_c, headers=h, json={"id_modelo": "x"})).status_code == 404
