"""Log da plataforma (Superadmin › Logs): helper de gravação, mascaramento de segredos, filtros, CSV e acesso só admin.

A maior parte roda sem banco (pool falso). O final (jornada) usa o Postgres local, com AGENTESIA_TESTE_PG_URL.
"""

import json
import uuid

import httpx
import pytest
from fastapi import Depends, FastAPI, HTTPException, Request

from app.gestao import log_plataforma, rotas_log_plataforma, seguranca
from app.gestao.log_plataforma import OCULTO, limpar, registrado, registrar
from app.gestao.rotas import COOKIE, Contexto, contexto
from tests.test_gestao import URL, _entrar, ambiente  # noqa: F401  (fixture do painel com Postgres local)


class PoolFalso:
    def __init__(self, falhar: Exception | None = None, linhas=None):
        self.chamadas: list[tuple] = []
        self.falhar = falhar
        self.linhas = linhas or []

    async def execute(self, sql, *args):
        if self.falhar:
            raise self.falhar
        self.chamadas.append((sql, args))
        return "INSERT 0 1"

    async def fetch(self, sql, *args):
        self.chamadas.append((sql, args))
        return self.linhas

    async def fetchrow(self, sql, *args):
        self.chamadas.append((sql, args))
        return {"total": 0, "sucesso": 0, "erros": 0, "duracao_media_ms": None, "funcoes": 0}


class Estado:
    pass


class PedidoFalso:
    """Só o que o log lê do Request: app.state.gestao.pool (e headers, para o decorador achar o pedido)."""

    def __init__(self, pool):
        self.app = Estado()
        self.app.state = Estado()
        self.app.state.gestao = Estado()
        self.app.state.gestao.pool = pool
        self.headers = {}


ID_ADMIN = str(uuid.uuid4())
ID_ESC = str(uuid.uuid4())


def _ctx(papel="admin_lawchat", id_escritorio=ID_ESC):
    return Contexto({"id": ID_ADMIN, "papel": papel, "nome": "Equipe", "ativo": True}, id_escritorio)


def _gravado(pool):
    sql, args = pool.chamadas[-1]
    assert "insert into agentesia_log_plataforma" in sql
    nomes = ["id_escritorio", "id_usuario", "papel", "funcao", "rotulo", "referencia", "payload", "resultado",
             "status", "erro", "duracao_ms"]
    linha = dict(zip(nomes, args))
    linha["payload"] = json.loads(linha["payload"]) if linha["payload"] else None
    linha["resultado"] = json.loads(linha["resultado"]) if linha["resultado"] else None
    return linha


# ------------------------------------------------------------------ mascaramento
def test_limpar_tira_segredos_e_dados_pessoais():
    sujo = {
        "token_helena": "pn_abc123456789", "senha": "segredo-forte", "senha_provisoria": "Xy12", "api_key": "sk-123",
        "chave": "k-1", "Authorization": "Bearer abc.def", "cpf": "123.456.789-09", "telefone": "+55 31 98888-7777",
        "numero_ia": "5531988887777", "conteudo_base64": "AAAA", "pix_copia_cola": "000201...",
        "nome": "Escritório Silva", "modelo": "gpt-4.1-mini", "ativo": True, "delay_s": 10,
        "observacao": "cliente 123.456.789-09 ligou de (31) 98888-7777 com Bearer xyz.abc",
        "id": ID_ESC, "agentes": [{"papel": "sdr", "token": "t"}],
    }
    limpo = limpar(sujo)
    for chave in ("token_helena", "senha", "senha_provisoria", "api_key", "chave", "Authorization", "cpf", "telefone",
                  "numero_ia", "conteudo_base64", "pix_copia_cola"):
        assert limpo[chave] == OCULTO, chave
    assert limpo["nome"] == "Escritório Silva" and limpo["modelo"] == "gpt-4.1-mini"
    assert limpo["ativo"] is True and limpo["delay_s"] == 10
    assert limpo["id"] == ID_ESC                                   # id não é telefone
    assert "123.456.789-09" not in limpo["observacao"] and "98888" not in limpo["observacao"]
    assert "xyz.abc" not in limpo["observacao"]
    assert limpo["agentes"] == [{"papel": "sdr", "token": OCULTO}]
    texto = json.dumps(limpo, ensure_ascii=False)
    for segredo in ("pn_abc123456789", "segredo-forte", "sk-123", "5531988887777"):
        assert segredo not in texto


def test_limpar_corta_textos_e_listas_e_aceita_pydantic():
    from pydantic import BaseModel

    class Dados(BaseModel):
        nome: str
        senha: str

    assert limpar(Dados(nome="A", senha="x")) == {"nome": "A", "senha": OCULTO}
    longo = limpar({"texto": "a" * 2000, "lista": list(range(100))})
    assert len(longo["texto"]) < 600 and longo["texto"].startswith("a" * 100)
    assert len(longo["lista"]) == log_plataforma.LISTA_MAX + 1 and "itens" in longo["lista"][-1]
    assert limpar({"vazio": None, "senha": ""}) == {"vazio": None, "senha": ""}   # nada a esconder


# ------------------------------------------------------------------ registrar
async def test_registrar_grava_com_quem_fez_e_sem_segredo():
    pool = PoolFalso()
    ok = await registrar(PedidoFalso(pool), ctx=_ctx(), funcao="conta.liberada", rotulo="Conta liberada",
                         referencia="Silva", payload={"situacao": "ativo", "token": "abc"}, resultado={"ok": True},
                         duracao_ms=12.6)
    assert ok
    linha = _gravado(pool)
    assert linha["id_escritorio"] == ID_ESC and linha["id_usuario"] == ID_ADMIN and linha["papel"] == "admin_lawchat"
    assert linha["funcao"] == "conta.liberada" and linha["status"] == "ok" and linha["duracao_ms"] == 13
    assert linha["payload"] == {"situacao": "ativo", "token": OCULTO}


async def test_registrar_sem_conta_e_id_invalido_viram_nulo():
    pool = PoolFalso()
    await registrar(pool, ctx=_ctx(), id_escritorio=None, funcao="catalogo.publicado", rotulo="Publicado")
    assert _gravado(pool)["id_escritorio"] is None
    await registrar(pool, funcao="x.y", rotulo="X", id_escritorio="nao-e-uuid", id_usuario="tambem-nao")
    linha = _gravado(pool)
    assert linha["id_escritorio"] is None and linha["id_usuario"] is None


async def test_registrar_nunca_levanta():
    import asyncpg
    for falha in (RuntimeError("banco fora"), asyncpg.UndefinedTableError('relation "agentesia_log_plataforma" does not exist')):
        assert await registrar(PedidoFalso(PoolFalso(falhar=falha)), funcao="a.b", rotulo="A") is False
    assert await registrar(object(), funcao="a.b", rotulo="A") is False           # sem pool
    pedido = PedidoFalso(None)
    assert await registrar(pedido, funcao="a.b", rotulo="A") is False


# ------------------------------------------------------------------ decorador
async def test_decorador_grava_sucesso_com_duracao_e_resultado():
    pool = PoolFalso()

    @registrado("produto.arquivado", "Agente arquivado", referencia=lambda a: a["id_ativado"],
                resultado=lambda _a, r: {"status": r["status"], "senha": "x"})
    async def rota(id_ativado: str, pedido, ctx):
        return {"status": "pausado", "nome": "Júlia"}

    id_ativado = str(uuid.uuid4())
    assert await rota(id_ativado, PedidoFalso(pool), _ctx()) == {"status": "pausado", "nome": "Júlia"}
    linha = _gravado(pool)
    assert linha["funcao"] == "produto.arquivado" and linha["status"] == "ok"
    assert linha["referencia"] == f"Júlia · {id_ativado[:8]}"            # id vira nome + começo do id
    assert linha["resultado"] == {"status": "pausado", "senha": OCULTO}
    assert linha["duracao_ms"] is not None and linha["duracao_ms"] >= 0


async def test_decorador_grava_erro_e_deixa_a_excecao_seguir():
    pool = PoolFalso()

    @registrado("produto.retomado", "Produto ligado")
    async def rota(pedido, ctx):
        raise HTTPException(409, "Este agente está arquivado.")

    with pytest.raises(HTTPException):
        await rota(pedido=PedidoFalso(pool), ctx=_ctx())
    linha = _gravado(pool)
    assert linha["status"] == "erro" and "409" in linha["erro"] and "arquivado" in linha["erro"]
    assert linha["resultado"] is None


async def test_decorador_falha_de_negocio_e_funcao_none():
    pool = PoolFalso()

    @registrado(lambda a: None if a["simular"] else "followup.ligado_em_lote", "Lote",
                falha=lambda _a, r: None if r["ok"] else "não ligou")
    async def rota(pedido, ctx, simular: bool = False, ok: bool = True):
        return {"ok": ok}

    await rota(PedidoFalso(pool), _ctx(), simular=True)
    assert pool.chamadas == []                                         # simulação não vai para o log
    await rota(PedidoFalso(pool), _ctx(), ok=False)
    assert _gravado(pool)["status"] == "erro" and _gravado(pool)["erro"] == "não ligou"


async def test_decorador_nao_derruba_a_rota_quando_o_log_falha():
    @registrado("conta.criada", "Conta criada", payload=lambda a: 1 / 0)     # extrator com defeito
    async def rota(pedido, ctx):
        return {"ok": True}

    assert await rota(PedidoFalso(PoolFalso(falhar=RuntimeError("fora"))), _ctx()) == {"ok": True}


async def test_decorador_mantem_a_rota_do_fastapi():
    """A assinatura (Depends, corpo, caminho) continua a mesma para o FastAPI depois do decorador."""
    from pydantic import BaseModel

    class Corpo(BaseModel):
        status: str

    pool = PoolFalso()
    app = FastAPI()

    async def ctx_falso() -> Contexto:
        return _ctx()

    @app.post("/x/{id_ativado}")
    @registrado("produto.pausado", "Pausado", payload=lambda a: a["dados"])
    async def rota(id_ativado: str, dados: Corpo, pedido: Request, ctx: Contexto = Depends(ctx_falso)):
        return {"id": id_ativado, "status": dados.status}

    app.state.gestao = Estado()
    app.state.gestao.pool = pool
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as cliente:
        resposta = await cliente.post("/x/abc", json={"status": "pausado"})
    assert resposta.status_code == 200 and resposta.json() == {"id": "abc", "status": "pausado"}
    assert _gravado(pool)["payload"] == {"status": "pausado"}


# ------------------------------------------------------------------ filtros e CSV
def test_filtros_sql_com_parametros():
    args: list = []
    onde = rotas_log_plataforma.filtros_sql(args, de="2026-11-01T00:00:00Z", ate="2026-11-02T00:00:00Z", status="erro",
                                            funcao="produto.ativado", conta=ID_ESC, busca="50%_off")
    assert len(onde) == 6 and len(args) == 6
    assert args[2] == "erro" and args[3] == "produto.ativado" and args[4] == ID_ESC
    assert args[5] == "%50\\%\\_off%"                                  # busca escapada
    assert all("50%" not in o for o in onde)                            # nada colado no SQL
    args2: list = []
    assert rotas_log_plataforma.filtros_sql(args2, conta="plataforma") == ["l.id_escritorio is null"] and args2 == []


@pytest.mark.parametrize("campo,valor", [("status", "talvez"), ("funcao", "drop table;"), ("conta", "x"), ("de", "ontem")])
def test_filtros_invalidos(campo, valor):
    with pytest.raises(HTTPException) as erro:
        rotas_log_plataforma.filtros_sql([], **{campo: valor})
    assert erro.value.status_code == 400


def test_csv_com_bom_e_ponto_e_virgula():
    item = {"criado_em": "2026-11-27T10:00:00+00:00", "conta": {"id": ID_ESC, "nome": "Silva; Souza", "id_conta_helena": None},
            "executado_por": {"id": ID_ADMIN, "nome": "Equipe", "email": "eq@lawchat.com", "papel": "admin_lawchat"},
            "funcao": "conta.liberada", "rotulo": "Conta liberada", "referencia": "Silva", "payload": {"a": 1},
            "resultado": None, "status": "ok", "erro": None, "duracao_ms": 12}
    texto = rotas_log_plataforma.linhas_csv([item])
    assert texto.startswith("﻿")
    cabecalho, linha = texto.lstrip("﻿").strip().split("\r\n")
    assert cabecalho.split(";")[:4] == ["quando", "conta", "id_conta", "funcao"]
    assert '"Silva; Souza"' in linha and "conta.liberada" in linha and '{""a"": 1}' in linha


# ------------------------------------------------------------------ só admin
class RepoFalso:
    def __init__(self, usuarios, pool):
        self.usuarios = usuarios
        self.pool = pool

    async def usuario(self, id_usuario):
        return self.usuarios.get(id_usuario)

    async def escritorio(self, id_escritorio):
        return {"id": id_escritorio, "nome": "Silva"}


@pytest.fixture
async def app_logs():
    pool = PoolFalso()
    ids = {"admin": str(uuid.uuid4()), "gestor": str(uuid.uuid4()), "atendente": str(uuid.uuid4())}
    usuarios = {
        ids["admin"]: {"id": ids["admin"], "papel": "admin_lawchat", "ativo": True, "nome": "Equipe", "id_escritorio": None},
        ids["gestor"]: {"id": ids["gestor"], "papel": "gestor", "ativo": True, "nome": "G", "id_escritorio": ID_ESC},
        ids["atendente"]: {"id": ids["atendente"], "papel": "atendente", "ativo": True, "nome": "A", "id_escritorio": ID_ESC},
    }
    app = FastAPI()
    app.include_router(rotas_log_plataforma.api)
    app.state.gestao = RepoFalso(usuarios, pool)
    app.state.assinador = seguranca.Assinador("segredo-de-teste")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://painel") as cliente:
        yield cliente, app, ids, pool


def _sessao(app, id_usuario=None, **extra):
    """Cabeçalhos do pedido com a sessão de quem pede (sem guardar cookie no cliente entre um pedido e outro)."""
    cab = dict(extra)
    if id_usuario:
        cab["Cookie"] = f"{COOKIE}={app.state.assinador.criar(id_usuario)}"
    return cab


async def test_rotas_so_para_a_equipe_lawchat(app_logs):
    cliente, app, ids, _pool = app_logs
    caminhos = ["/api/admin/logs", "/api/admin/logs/resumo", "/api/admin/logs/filtros", "/api/admin/logs/exportar.csv"]
    for caminho in caminhos:
        assert (await cliente.get(caminho, headers=_sessao(app))).status_code == 401
        for papel in ("gestor", "atendente"):
            assert (await cliente.get(caminho, headers=_sessao(app, ids[papel]))).status_code == 403, (caminho, papel)
        resposta = await cliente.get(caminho, headers=_sessao(app, ids["admin"]))
        assert resposta.status_code == 200, (caminho, resposta.text)
    corpo = {"id_escritorio": ID_ESC, "visao": "gestor"}
    assert (await cliente.post("/api/admin/logs/acesso-cliente", json=corpo, headers=_sessao(app, ids["gestor"]))).status_code == 403
    # A visão do cliente (X-Visao) também não abre o log: a permissão é a do papel da visão.
    resposta = await cliente.get("/api/admin/logs", headers=_sessao(app, ids["admin"], **{"X-Escritorio": ID_ESC, "X-Visao": "gestor"}))
    assert resposta.status_code == 403


async def test_acesso_como_cliente_grava_no_log(app_logs):
    cliente, app, ids, pool = app_logs
    resposta = await cliente.post("/api/admin/logs/acesso-cliente", json={"id_escritorio": ID_ESC, "visao": "atendente"},
                                  headers=_sessao(app, ids["admin"]))
    assert resposta.status_code == 200 and resposta.json()["registrado"] is True
    linha = _gravado(pool)
    assert linha["funcao"] == "acesso.como_cliente" and linha["id_escritorio"] == ID_ESC and linha["id_usuario"] == ids["admin"]


async def test_lista_e_csv_passam_os_filtros(app_logs):
    cliente, app, ids, pool = app_logs
    admin = _sessao(app, ids["admin"])
    resposta = await cliente.get(f"/api/admin/logs?status=erro&funcao=produto.ativado&conta={ID_ESC}&busca=silva&pagina=2&por_pagina=10",
                                 headers=admin)
    assert resposta.status_code == 200 and resposta.json()["itens"] == []
    sql, args = pool.chamadas[-1]
    assert "l.status = $1" in sql and "l.funcao = $2" in sql and "limit $5 offset $6" in sql
    assert list(args) == ["erro", "produto.ativado", ID_ESC, "%silva%", 11, 10]
    csv = await cliente.get("/api/admin/logs/exportar.csv?status=ok", headers=admin)
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    assert csv.text.lstrip("\ufeff").startswith("quando;conta")
    assert (await cliente.get("/api/admin/logs?status=x", headers=admin)).status_code == 400


# ------------------------------------------------------------------ jornada com o Postgres local
pg = pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")


@pg
async def test_jornada_criar_conta_liberar_e_ver_no_log(ambiente):
    cliente, _simulada, email_admin, banco = ambiente
    cliente._transport.app.include_router(rotas_log_plataforma.api)      # o app do fixture monta só as rotas da gestão
    await _entrar(cliente, email_admin, "senha-admin-123")
    nome = f"Log {uuid.uuid4().hex[:6]}"
    criada = await cliente.post("/api/admin/escritorios", json={"nome": nome, "token_helena": None})
    assert criada.status_code == 200, criada.text
    id_esc = criada.json()["escritorio"]["id"]

    # Bloquear e liberar a conta (situação) e desligar a IA da conta inteira.
    cab = {"X-Escritorio": id_esc}
    assert (await cliente.patch("/api/escritorio", json={"situacao": "suspenso"}, headers=cab)).status_code == 200
    assert (await cliente.patch("/api/escritorio", json={"situacao": "ativo", "ia_desligada": True}, headers=cab)).status_code == 200
    # Limite de consumo com valor inválido: fica como erro no log.
    ruim = await cliente.put(f"/api/admin/escritorios/{id_esc}/limite", json={"mensal_usd": -5})
    assert ruim.status_code == 400

    lista = (await cliente.get(f"/api/admin/logs?conta={id_esc}")).json()
    funcoes = [i["funcao"] for i in lista["itens"]]
    for esperada in ("conta.criada", "conta.bloqueada", "conta.liberada", "ia.desligada_conta", "conta.limite_consumo"):
        assert esperada in funcoes, (esperada, funcoes)
    criacao = next(i for i in lista["itens"] if i["funcao"] == "conta.criada")
    assert criacao["conta"]["id"] == id_esc and criacao["conta"]["nome"] == nome
    assert criacao["executado_por"]["email"] == email_admin and criacao["executado_por"]["papel"] == "admin_lawchat"
    assert criacao["duracao_ms"] is not None
    erro = next(i for i in lista["itens"] if i["funcao"] == "conta.limite_consumo")
    assert erro["status"] == "erro" and "400" in erro["erro"]

    resumo = (await cliente.get(f"/api/admin/logs/resumo?conta={id_esc}")).json()
    assert resumo["total"] == len(lista["itens"]) and resumo["erros"] == 1 and resumo["funcoes"] == len(set(funcoes))
    so_erros = (await cliente.get(f"/api/admin/logs?conta={id_esc}&status=erro")).json()["itens"]
    assert [i["funcao"] for i in so_erros] == ["conta.limite_consumo"]
    busca = (await cliente.get("/api/admin/logs?busca=" + nome)).json()["itens"]
    assert any(i["funcao"] == "conta.criada" for i in busca)
    filtros = (await cliente.get("/api/admin/logs/filtros")).json()
    assert any(f["funcao"] == "conta.liberada" for f in filtros["funcoes"])
    csv = await cliente.get(f"/api/admin/logs/exportar.csv?conta={id_esc}")
    assert csv.status_code == 200 and nome in csv.text
