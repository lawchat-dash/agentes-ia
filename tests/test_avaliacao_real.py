"""Modo real: o modelo e o prompt de verdade, N rodadas, com custo. Só roda com --real.

  pytest -m ia --real --teto-usd 2 [--rodadas 3] [--regravar]

Sem --real, o conftest pula estes testes; sem --teto-usd, o teste falha antes de qualquer chamada.
"""

import pytest

from app.avaliacao import cenario, executar, relatorio

pytestmark = pytest.mark.ia


async def test_bateria_real_aprova_os_cenarios(opcoes_avaliacao):
    if opcoes_avaliacao.teto_usd is None:
        pytest.fail("o modo real exige --teto-usd (ex.: pytest -m ia --real --teto-usd 2)")
    casos = cenario.casos()
    modo = "gravar" if opcoes_avaliacao.regravar else "real"
    estimativa = executar.estimar(casos, 1 if modo == "gravar" else opcoes_avaliacao.rodadas)
    print("\n" + estimativa.texto())
    bateria = await executar.rodar_bateria(casos, modo, opcoes_avaliacao.rodadas, opcoes_avaliacao.teto_usd)
    pasta = relatorio.gravar(bateria)
    print(f"\nRelatório: {pasta / 'relatorio.md'}  (US$ {bateria.custo_total_usd:.4f})")
    assert bateria.custo_total_usd <= opcoes_avaliacao.teto_usd
    assert not bateria.parou_no_teto, "a bateria parou no teto de custo: aumente --teto-usd para testar tudo"
    pulados = [f"{c.id}: {c.pulado}" for c in bateria.cenarios if c.aprovado is None]
    assert not pulados, "cenários que não rodaram até o fim:\n" + "\n".join(pulados)
    reprovados = [f"{c.id} ({c.taxa}): {c.por_checagem}" for c in bateria.cenarios if c.aprovado is False]
    assert not reprovados, "\n".join(reprovados)
