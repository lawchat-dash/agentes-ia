"""Integração da conta não trava por coisa que não é erro: sistema ainda local, etiqueta que já existe."""

import httpx

from app.canal.helena_conta import HelenaConta
from app.gestao import onboarding, sincronizar_conta


def test_endereco_local_nao_vira_erro_de_webhook():
    assert onboarding._endereco_local("http://127.0.0.1:8014/webhook/helena/x?segredo=1")
    assert onboarding._endereco_local("http://localhost:8012/webhook/helena/x")
    assert not onboarding._endereco_local("https://ia.lawchat.com.br/webhook/helena/x")


async def test_etiqueta_que_ja_existe_nao_derruba_a_integracao():
    """A Helena responde 500 ao criar uma etiqueta repetida: conta como 'já existia', sem erro."""
    def helena(pedido: httpx.Request) -> httpx.Response:
        if pedido.method == "POST":
            return httpx.Response(500, text="erro")
        return httpx.Response(200, json=[])

    h = HelenaConta("tok", http=httpx.AsyncClient(transport=httpx.MockTransport(helena)))
    feito = await sincronizar_conta.garantir_etiquetas_padrao(h, [])
    assert feito["criadas"] == [] and len(feito["ja_existiam"]) == len(sincronizar_conta.ETIQUETAS_PADRAO)
