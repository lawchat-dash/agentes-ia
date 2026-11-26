"""Etiqueta pelo id da conta (26/11): pôr "📄 Contrato em Elaboração" pelo nome criou uma etiqueta repetida, porque a
da conta tinha o nome escrito de outro jeito. Agora acha a da conta pelo nome parecido e manda o id (tagIds)."""

import json

import httpx

from app.canal.helena_conta import HelenaConta

DA_CONTA = [{"id": "id-contrato", "name": "Contrato em Elaboração 📄"}, {"id": "id-sdr", "name": "📞 SDR"}]


def _helena(pedidos):
    def responder(req: httpx.Request) -> httpx.Response:
        if req.method == "GET" and req.url.path.endswith("core/v1/tag"):
            return httpx.Response(200, json=DA_CONTA)
        pedidos.append(json.loads(req.content))
        return httpx.Response(200, json={})
    return HelenaConta("tok", "https://h.invalid", http=httpx.AsyncClient(transport=httpx.MockTransport(responder)))


async def test_poe_pelo_id_da_etiqueta_parecida_da_conta():
    pedidos: list = []
    await _helena(pedidos).etiquetar("c1", ["📄 Contrato em Elaboração"])
    assert pedidos == [{"tagIds": ["id-contrato"], "operation": "InsertIfNotExists"}]


async def test_remove_pelo_id_e_a_que_nao_achou_pelo_nome():
    pedidos: list = []
    await _helena(pedidos).etiquetar("c1", ["📞 SDR", "🛒 Comercial"], remover=True)
    assert pedidos == [{"tagIds": ["id-sdr"], "operation": "DeleteIfExists"},
                       {"tagNames": ["🛒 Comercial"], "operation": "DeleteIfExists"}]


async def test_etiqueta_que_a_conta_nao_tem_e_criada_pelo_nome():
    pedidos: list = []
    await _helena(pedidos).etiquetar("c1", ["🔥 Quente"])
    assert pedidos == [{"tagNames": ["🔥 Quente"], "operation": "InsertIfNotExists"}]
