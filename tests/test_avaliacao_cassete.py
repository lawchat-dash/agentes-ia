"""Cassete: as respostas reais gravadas tocam de novo, de graça e sem chave.

  * test_cenario_toca_o_cassete: um caso por cenário; pula se o cassete ainda não foi gravado
    (grave com `python -m app.avaliacao gravar <id> --teto-usd 1` e revise a transcrição no diff).
  * o resto usa um cassete sintético gravado com o modelo roteirizado: tocar é determinístico, mudar 1 caractere
    do prompt falha com `cassete_falta` e diff legível (não com silêncio), e o relógio do sistema não entra no prompt.
"""

import json
from datetime import datetime

import pytest

from app.avaliacao import cenario, executar, falso, relatorio, simulador
from app.avaliacao.cassete import CasseteSemResposta, ModeloGravador

CASOS = cenario.casos()


@pytest.mark.parametrize("caso", CASOS, ids=[c.id for c in CASOS])
async def test_cenario_toca_o_cassete(caso):
    arquivo = executar.caminho_do_cassete(caso)
    if not arquivo.exists():
        pytest.skip(f"sem cassete: grave com `python -m app.avaliacao gravar {caso.id.split('[')[0]} --teto-usd 1`")
    bateria = await executar.rodar_bateria([caso], "cassete")
    resultado = bateria.cenarios[0]
    falhas = [f for r in resultado.rodadas for f in r.falhas]
    assert not [f for f in falhas if f.codigo == "cassete_falta"], "cassete desatualizado: regrave e revise a transcrição"
    assert resultado.aprovado, [f.model_dump() for f in falhas]


async def _gravar(caso, pasta):
    gravador = ModeloGravador(falso.modelo_para(caso), executar.caminho_do_cassete(caso, pasta), "gravar")
    conversa = await simulador.rodar_conversa(caso, gravador)
    assert conversa.aprovada and gravador.gravados > 0
    gravador.confirmar()                                         # a gravação vai para o temporário até confirmar
    return gravador


async def test_tocar_duas_vezes_da_o_mesmo_resultado_byte_a_byte(tmp_path):
    caso = cenario.casos(["01"])[0]
    await _gravar(caso, tmp_path)
    primeira = await executar.rodar_bateria([caso], "cassete", pasta_cassetes=tmp_path)
    segunda = await executar.rodar_bateria([caso], "cassete", pasta_cassetes=tmp_path)
    assert primeira.cenarios[0].aprovado is True
    assert relatorio.resultado_json(primeira) == relatorio.resultado_json(segunda)
    assert '"iniciado_em"' not in relatorio.resultado_json(primeira)         # sem horários no contrato


async def test_cassete_toca_sem_o_modelo_de_verdade(tmp_path):
    caso = cenario.casos(["02"])[0]
    gravado = await _gravar(caso, tmp_path)
    tocador = ModeloGravador(None, executar.caminho_do_cassete(caso, tmp_path), "tocar")
    conversa = await simulador.rodar_conversa(caso, tocador)
    assert conversa.aprovada and tocador.tocados == gravado.gravados and tocador.faltas == []


async def test_mudar_um_caractere_do_prompt_falha_com_cassete_falta_e_diff(tmp_path):
    caso = cenario.casos(["01"])[0]
    await _gravar(caso, tmp_path)
    snapshot = caso.carregar_agente()
    sdr = next(e for e in snapshot["agente"]["etapas"] if e["codigo"] == "sdr")
    sdr["instrucao"] = sdr["instrucao"].replace("Mensagens curtas", "Mensagens curtaz", 1)
    arquivo = tmp_path / "agente_alterado.json"
    arquivo.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    alterado = caso.model_copy(update={"agente": str(arquivo)})
    tocador = ModeloGravador(None, executar.caminho_do_cassete(caso, tmp_path), "tocar")
    conversa = await simulador.rodar_conversa(alterado, tocador)
    assert conversa.parada == "cassete_falta" and not conversa.aprovada
    falta = next(f for f in conversa.falhas if f.codigo == "cassete_falta")
    assert falta.gravidade == "critica" and "python -m app.avaliacao gravar" in falta.evidencia
    assert "-- Mensagens curtas" in falta.evidencia and "+- Mensagens curtaz" in falta.evidencia   # diff legível
    assert "silencio" in conversa.codigos()                     # o pipeline engoliu a exceção, o simulador não


async def test_relogio_do_sistema_nao_entra_no_cassete(tmp_path):
    caso = cenario.casos(["06"])[0]
    await _gravar(caso, tmp_path)
    linhas = [json.loads(l) for l in executar.caminho_do_cassete(caso, tmp_path).read_text(encoding="utf-8").splitlines()]
    conteudos = [l["conteudo"] for l in linhas if l["tipo"] == "pedido"]
    assert conteudos and all("Hoje é 10/03/2026" in c for c in conteudos)       # o relógio congelado do cenário
    hoje = datetime.now().strftime("%d/%m/%Y")
    assert hoje == "10/03/2026" or not any(hoje in c for c in conteudos)


async def test_modo_tocar_sem_arquivo_levanta_falta_e_nao_erro_do_modelo(tmp_path):
    tocador = ModeloGravador(None, tmp_path / "vazio.jsonl", "tocar")
    with pytest.raises(CasseteSemResposta):
        await tocador.gerar(papel="etapa", sistema="s", conteudo="c", esquema={}, modelo="gpt-4.1-mini")
    assert len(tocador.faltas) == 1
    with pytest.raises(ValueError):
        ModeloGravador(None, tmp_path / "x.jsonl", "gravar")              # gravar precisa do modelo de verdade
