"""Opções do teste do agente (app/avaliacao). Sem --real, nada chama a IA de verdade.

  --real          libera os testes marcados com @pytest.mark.ia (custam)
  --rodadas N     rodadas por cenário no modo real
  --teto-usd X    teto de custo da bateria (obrigatório com --real)
  --regravar      no modo real, regrava os cassetes (avaliacao/cassetes/) e as transcrições
"""

from types import SimpleNamespace

import pytest


def pytest_addoption(parser):
    grupo = parser.getgroup("avaliacao", "teste do agente (app/avaliacao)")
    grupo.addoption("--real", action="store_true", default=False, help="roda os testes que chamam o modelo real (custa)")
    grupo.addoption("--rodadas", type=int, default=1, help="rodadas por cenário no modo real")
    grupo.addoption("--teto-usd", type=float, default=None, dest="teto_usd", help="teto de custo da bateria em US$")
    grupo.addoption("--regravar", action="store_true", default=False, help="regrava os cassetes no modo real")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--real"):
        return
    pular = pytest.mark.skip(reason="chama o modelo real (custa): rode com --real --teto-usd X")
    for item in items:
        if item.get_closest_marker("ia") is not None:
            item.add_marker(pular)


@pytest.fixture
def opcoes_avaliacao(request):
    opcao = request.config.getoption
    return SimpleNamespace(real=opcao("--real"), rodadas=opcao("--rodadas"), teto_usd=opcao("teto_usd"),
                           regravar=opcao("--regravar"))


@pytest.fixture(autouse=True)
def _sem_cache_curto(monkeypatch):
    """Os apps dos testes montam só os routers (sem o middleware que apaga o cache curto ao escrever): sem cache aqui.
    tests/test_cache_curto.py liga de novo para testar o próprio cache."""
    from app.gestao import cache_curto
    monkeypatch.setattr(cache_curto, "LIGADO", False)
    cache_curto.limpar_todos()
