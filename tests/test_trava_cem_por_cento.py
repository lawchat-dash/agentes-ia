"""Regressão: "100%" é promessa, mas um 100 qualquer (CEP, número da casa, CPF) não é.

Antes, a trava normalizava o texto (o que tira o "%") e procurava "100": o resumo dos dados do contrato de um lead
com CEP 13010-100 era reprovado duas vezes, o turno caía em trava_persistente e o lead ficava pausado.
"""

from app.cerebro import catalogo, travas


def _texto(s: str) -> list[dict[str, str]]:
    return [{"tipo": "texto", "texto": s}]


def _codigos(s: str) -> list[str]:
    return [r.codigo for r in travas.conferir(_texto(s), etapa="sdr", honorarios=None, midias={}, faltam=())]


def test_numero_100_em_endereco_nao_e_promessa():
    for frase in ("Seu CEP é 13010-100, certo?", "Rua das Flores, número 100.", "CPF 123.100.789-00 confere?"):
        assert catalogo.conferir(_texto(frase)) == []
        assert "promessa" not in _codigos(frase)


def test_cem_por_cento_continua_barrado():
    for frase in ("É 100% garantido.", "Isso é 100 por cento.", "Cem por cento de chance!"):
        assert catalogo.conferir(_texto(frase)), frase
        assert "promessa" in _codigos(frase), frase


def test_valores_reconhecem_por_cento():
    assert travas._valores("30 por cento") == {"30%"}
