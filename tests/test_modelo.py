"""Camada de modelo com um cliente de mentira: confere leitura da resposta, custo e erros."""

from types import SimpleNamespace

import pytest

from app.modelo import ErroModelo, ModeloAnthropic, calcular_custo

ESQUEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}


def resposta(texto='{"ok": true}', parada="end_turn", modelo="claude-opus-5-5"):
    return SimpleNamespace(
        model=modelo, stop_reason=parada,
        usage=SimpleNamespace(input_tokens=1000, output_tokens=200, cache_read_input_tokens=3000),
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=texto)],
    )


class ClienteFalso:
    def __init__(self, respostas):
        self.respostas, self.pedidos = list(respostas), []
        criar = SimpleNamespace(create=self._criar)
        self.messages, self.beta = criar, SimpleNamespace(messages=criar)

    async def _criar(self, **parametros):
        self.pedidos.append(parametros)
        item = self.respostas.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


async def gerar(cliente, modelo="claude-opus-5-5", validar=None):
    return await ModeloAnthropic(cliente).gerar(
        papel="extrator", sistema="instruções", conteudo="mensagens", esquema=ESQUEMA, modelo=modelo,
        esforco="low", validar=validar)


async def test_le_o_json_e_mede_tokens_e_custo():
    cliente = ClienteFalso([resposta()])
    resultado = await gerar(cliente)
    assert resultado.dados == {"ok": True}
    chamada = resultado.chamadas[0]
    assert (chamada.tokens_entrada, chamada.tokens_saida, chamada.tokens_cache) == (1000, 200, 3000)
    assert chamada.custo_usd == pytest.approx((1000 * 4 + 200 * 20 + 3000 * 0.20) / 1_000_000)
    pedido = cliente.pedidos[0]
    assert pedido["output_config"] == {"effort": "low", "format": {"type": "json_schema", "schema": ESQUEMA}}
    assert pedido["fallbacks"] == "default" and pedido["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "temperature" not in pedido and "thinking" not in pedido


async def test_modelo_sem_reserva_usa_a_chamada_comum():
    cliente = ClienteFalso([resposta(modelo="claude-haiku-5-5")])
    await gerar(cliente, modelo="claude-haiku-5-5")
    assert "fallbacks" not in cliente.pedidos[0] and "betas" not in cliente.pedidos[0]


async def test_saida_invalida_tenta_mais_uma_vez():
    cliente = ClienteFalso([resposta("isto não é json"), resposta()])
    resultado = await gerar(cliente)
    assert resultado.dados == {"ok": True} and [c.sucesso for c in resultado.chamadas] == [False, True]


async def test_validacao_do_chamador_tambem_refaz():
    def so_aceita_true(dados):
        assert dados["ok"] is True

    cliente = ClienteFalso([resposta('{"ok": false}'), resposta()])
    assert (await gerar(cliente, validar=so_aceita_true)).dados == {"ok": True}


async def test_recusa_nao_repete_e_vira_erro_com_motivo():
    cliente = ClienteFalso([resposta(parada="refusal"), resposta()])
    with pytest.raises(ErroModelo) as erro:
        await gerar(cliente)
    assert erro.value.motivo == "recusa_do_modelo" and len(cliente.pedidos) == 1


def test_custo_de_modelo_fora_da_tabela_e_zero():
    assert calcular_custo("modelo-desconhecido", 1000, 1000, 0) == 0.0


# ----------------------------------------------------------------------------- OpenAI (GPT)
from app.modelo import ModeloOpenAI, ModeloPorNome  # noqa: E402


def resposta_gpt(texto='{"ok": true}', parada="stop", recusa=None, modelo="gpt-4.1-2025-04-14"):
    return SimpleNamespace(
        model=modelo,
        usage=SimpleNamespace(prompt_tokens=4000, completion_tokens=200,
                              prompt_tokens_details=SimpleNamespace(cached_tokens=3000)),
        choices=[SimpleNamespace(finish_reason=parada, message=SimpleNamespace(content=texto, refusal=recusa))],
    )


class ClienteGptFalso:
    def __init__(self, respostas):
        self.respostas, self.pedidos = list(respostas), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._criar))

    async def _criar(self, **parametros):
        self.pedidos.append(parametros)
        return self.respostas.pop(0)


async def gerar_gpt(cliente, papel="extrator", modelo="gpt-4.1"):
    return await ModeloOpenAI(cliente).gerar(
        papel=papel, sistema="instruções", conteudo="mensagens", esquema=ESQUEMA, modelo=modelo, esforco="low")


async def test_gpt_le_o_json_e_mede_tokens_e_custo():
    cliente = ClienteGptFalso([resposta_gpt()])
    resultado = await gerar_gpt(cliente)
    assert resultado.dados == {"ok": True}
    chamada = resultado.chamadas[0]
    # 4000 de entrada, dos quais 3000 vieram do cache.
    assert (chamada.tokens_entrada, chamada.tokens_cache, chamada.tokens_saida) == (1000, 3000, 200)
    assert chamada.custo_usd == pytest.approx((1000 * 2 + 200 * 8 + 3000 * 0.50) / 1_000_000)
    pedido = cliente.pedidos[0]
    assert pedido["response_format"]["json_schema"] == {"name": "saida_extrator", "schema": ESQUEMA, "strict": True}
    assert [m["role"] for m in pedido["messages"]] == ["system", "user"]
    assert "tools" not in pedido                               # a IA não aciona ferramenta


async def test_gpt_temperatura_baixa_por_papel():
    cliente = ClienteGptFalso([resposta_gpt(), resposta_gpt()])
    await gerar_gpt(cliente, papel="extrator")
    await gerar_gpt(cliente, papel="etapa")
    assert [p["temperature"] for p in cliente.pedidos] == [0, 0.4]


async def test_gpt_modelo_de_raciocinio_nao_recebe_temperatura():
    cliente = ClienteGptFalso([resposta_gpt(modelo="gpt-5-mini")])
    await gerar_gpt(cliente, modelo="gpt-5-mini")
    assert "temperature" not in cliente.pedidos[0] and cliente.pedidos[0]["reasoning_effort"] == "low"


async def test_gpt_saida_cortada_tenta_de_novo_e_recusa_nao():
    cliente = ClienteGptFalso([resposta_gpt(parada="length"), resposta_gpt()])
    assert (await gerar_gpt(cliente)).dados == {"ok": True}
    cliente = ClienteGptFalso([resposta_gpt(texto=None, recusa="não posso ajudar"), resposta_gpt()])
    with pytest.raises(ErroModelo) as erro:
        await gerar_gpt(cliente)
    assert erro.value.motivo == "recusa_do_modelo" and len(cliente.pedidos) == 1


def test_preco_do_modelo_com_data_usa_o_modelo_base():
    assert calcular_custo("gpt-4.1-mini-2025-04-14", 1_000_000, 0, 0) == pytest.approx(0.40)
    assert calcular_custo("gpt-4.1-2025-04-14", 1_000_000, 0, 0) == pytest.approx(2.00)
    assert calcular_custo("gpt-4.1-pico", 1_000_000, 0, 0) == 0.0      # fora da tabela: não chuta preço


async def test_provedor_escolhido_pelo_nome_do_modelo():
    roteador = ModeloPorNome()
    gpt, claude = ClienteGptFalso([resposta_gpt()]), ClienteFalso([resposta()])
    roteador._provedores = {"openai": ModeloOpenAI(gpt), "anthropic": ModeloAnthropic(claude)}
    for modelo in ("gpt-4.1", "claude-opus-5-5"):
        await roteador.gerar(papel="etapa", sistema="s", conteudo="c", esquema=ESQUEMA, modelo=modelo)
    assert gpt.pedidos[0]["model"] == "gpt-4.1" and claude.pedidos[0]["model"] == "claude-opus-5-5"
