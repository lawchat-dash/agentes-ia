"""Cache curto do painel (app/gestao/cache_curto.py): guarda por pouco tempo, apaga ao escrever em /api/, e o app
"painel" (produção) tem os mesmos middlewares do app.main (gzip e limpeza do cache)."""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gestao import cache_curto


@pytest.fixture
def ligado(monkeypatch):
    monkeypatch.setattr(cache_curto, "LIGADO", True)
    cache_curto.limpar_todos()


def test_guarda_e_expira(ligado, monkeypatch):
    cache = cache_curto.CacheCurto(10)
    chamadas = []

    async def calcular():
        chamadas.append(1)
        return len(chamadas)

    async def rodar():
        assert await cache.obter("a", calcular) == 1
        assert await cache.obter("a", calcular) == 1          # guardado
        assert await cache.obter("b", calcular) == 2          # outra chave (outro escritório)
        cache_curto.limpar_todos()
        assert await cache.obter("a", calcular) == 3          # escrita apagou
        relogio = cache_curto.time.monotonic() + 11
        monkeypatch.setattr(cache_curto.time, "monotonic", lambda: relogio)
        assert await cache.obter("a", calcular) == 4          # passou do tempo
    asyncio.run(rodar())


def test_escrita_no_meio_nao_guarda_valor_velho(ligado):
    cache = cache_curto.CacheCurto(10)

    async def calcular_com_escrita():
        cache_curto.limpar_todos()                            # alguém salvou enquanto a leitura rodava
        return "velho"

    async def novo():
        return "novo"

    async def rodar():
        assert await cache.obter("a", calcular_com_escrita) == "velho"
        assert await cache.obter("a", novo) == "novo"
    asyncio.run(rodar())


def test_desligado_nos_testes():
    assert cache_curto.LIGADO is False                         # tests/conftest.py


def test_middleware_limpa_ao_escrever(ligado):
    cache = cache_curto.CacheCurto(60)
    contador = {"n": 0}
    app = FastAPI()
    app.add_middleware(cache_curto.LimparAoEscrever)

    async def ler():
        contador["n"] += 1
        return {"n": contador["n"]}

    @app.get("/api/x")
    async def x():
        return await cache.obter("x", ler)

    @app.post("/api/salvar")
    async def salvar():
        return {"ok": True}

    @app.post("/webhook/y")
    async def webhook():
        return {"ok": True}

    @app.post("/api/atendimento/entrar")
    async def entrar_lawchat():
        return {"url": "https://exemplo"}

    c = TestClient(app)
    assert c.get("/api/x").json() == {"n": 1}
    assert c.get("/api/x").json() == {"n": 1}
    c.post("/webhook/y")                                      # fora de /api/: não mexe no cache do painel
    c.post("/api/atendimento/entrar")                         # só gera o link da LawChat: não muda dado
    assert c.get("/api/x").json() == {"n": 1}
    c.post("/api/salvar")
    assert c.get("/api/x").json() == {"n": 2}


def test_app_do_painel_tem_gzip_e_index_sem_cache():
    from app.servidor import criar_app
    from app import main

    app = criar_app("painel")
    tipos = [m.cls for m in app.user_middleware]
    assert main._GzipDoPainel in tipos and cache_curto.LimparAoEscrever in tipos
    if (main._PAINEL / "index.html").is_file():
        c = TestClient(app)
        for metodo in (c.get, c.head):                       # curl -I (HEAD) recebia 405 sem Cache-Control
            r = metodo("/admin/escritorios")
            assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
