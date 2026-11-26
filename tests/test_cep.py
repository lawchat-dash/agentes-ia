import httpx
import pytest

from app.ferramentas import cep


def _cliente(respostas: dict[str, tuple[int, object]]) -> httpx.AsyncClient:
    chamadas: list[str] = []

    def tratar(pedido: httpx.Request) -> httpx.Response:
        url = str(pedido.url)
        chamadas.append(url)
        for trecho, (status, corpo) in respostas.items():
            if trecho in url:
                return httpx.Response(status, json=corpo)
        return httpx.Response(404, json={})

    cliente = httpx.AsyncClient(transport=httpx.MockTransport(tratar))
    cliente.chamadas = chamadas  # type: ignore[attr-defined]
    return cliente


def test_achar_cep_no_texto():
    assert cep.achar_cep("meu cep é 01.310-100, obrigado") == "01310100"
    assert cep.achar_cep("01310100") == "01310100"
    assert cep.achar_cep("telefone 11987654321") is None


@pytest.mark.asyncio
async def test_cep_com_poucos_digitos_nao_chama_nada():
    cliente = _cliente({})
    r = await cep.consultar("1234", cliente=cliente)
    assert not r.valido and "8 dígitos" in r.mensagem
    assert cliente.chamadas == []  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_viacep_responde():
    cliente = _cliente({"viacep": (200, {"logradouro": "Avenida Paulista", "bairro": "Bela Vista",
                                         "localidade": "São Paulo", "uf": "SP"})})
    r = await cep.consultar("01310-100", cliente=cliente)
    assert r.valido and r.origem == "viacep" and r.logradouro == "Avenida Paulista" and r.uf == "SP"


@pytest.mark.asyncio
async def test_cai_para_brasilapi_quando_viacep_e_opencep_falham():
    cliente = _cliente({"viacep": (200, {"erro": True}), "opencep": (500, {}),
                        "brasilapi": (200, {"street": "Rua A", "neighborhood": "Centro", "city": "Recife", "state": "PE"})})
    r = await cep.consultar("50000000", cliente=cliente)
    assert r.valido and r.origem == "brasilapi" and r.cidade == "Recife"


@pytest.mark.asyncio
async def test_cep_geral_sem_rua_e_invalido():
    cliente = _cliente({"viacep": (200, {"logradouro": "", "localidade": "Cidadezinha", "uf": "MG"})})
    r = await cep.consultar("39999000", cliente=cliente)
    assert not r.valido and r.tipo == "geral" and r.cidade == "Cidadezinha"


@pytest.mark.asyncio
async def test_nenhuma_fonte_acha():
    r = await cep.consultar("00000000", cliente=_cliente({}))
    assert not r.valido and "não encontrado" in r.mensagem
