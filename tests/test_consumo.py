"""Limite de consumo da IA por escritório: faixas de aviso, pausa ao estourar e o caminho pelo pipeline."""

import os
from datetime import datetime, timezone

import pytest

from app import consumo
from tests.test_pipeline import SIMPLES, montar, webhook

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")


def test_faixas_e_pausa():
    cfg = {"limite_consumo": {"mensal_usd": 50}}
    assert consumo.avaliar(10, cfg) == consumo.Situacao(10, 50, 20.0, None, False)
    assert consumo.avaliar(41, cfg).faixa == 80 and not consumo.avaliar(41, cfg).bloqueado
    assert consumo.avaliar(50, cfg).faixa == 100 and consumo.avaliar(50, cfg).bloqueado
    so_avisa = {"limite_consumo": {"mensal_usd": 50, "ao_estourar": "so_avisar"}}
    assert consumo.avaliar(80, so_avisa).faixa == 100 and not consumo.avaliar(80, so_avisa).bloqueado
    assert consumo.avaliar(9999, {}).bloqueado is False and consumo.avaliar(9999, {}).limite_usd is None
    texto = consumo.texto_do_aviso("Sousa e Costa", consumo.avaliar(52, cfg), cfg)
    assert "Limite de consumo da IA atingido" in texto and "US$ 52.00 de US$ 50.00 (104%)" in texto and "parou de responder" in texto
    assert "Consumo da IA em 80%" in consumo.texto_do_aviso("X", consumo.avaliar(41, cfg), cfg)


def test_validacao_do_painel():
    assert consumo.validar({"mensal_usd": "25.5", "ao_estourar": "so_avisar", "avisar_em": [100, 50, 50]}) == {
        "mensal_usd": 25.5, "ao_estourar": "so_avisar", "avisar_em": [50, 100]}
    assert consumo.validar({"mensal_usd": None})["mensal_usd"] is None
    for ruim in ({"mensal_usd": "abc"}, {"mensal_usd": -1}, {"mensal_usd": 10, "ao_estourar": "desligar"}, {"mensal_usd": 10, "avisar_em": [0]}):
        with pytest.raises(ValueError):
            consumo.validar(ruim)


def test_inicio_do_mes_no_horario_de_brasilia():
    # 1º de dezembro às 01:00 UTC ainda é 30 de novembro em Brasília.
    inicio = consumo.inicio_do_mes(datetime(2026, 12, 1, 1, 0, tzinfo=timezone.utc))
    assert (inicio.year, inicio.month, inicio.day, inicio.hour) == (2026, 11, 1, 0)


async def test_limite_estourado_silencia_a_ia_e_avisa_uma_vez():
    atendimento, repo, helena = montar(SIMPLES)
    repo.escritorios["esc-1"].config["limite_consumo"] = {"mensal_usd": 1.0}
    repo.chamadas.append({"id_escritorio": "esc-1", "custo_usd": 1.2})
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    assert helena.enviadas == []
    turno = next(iter(repo.turnos.values()))
    assert (turno["situacao"], turno["motivo"]) == ("silencio", "limite_de_consumo")
    avisos = [a for a in repo.acoes if a["tipo"] == "aviso_consumo"]
    assert len(avisos) == 1 and avisos[0]["dados"]["faixa"] == 100 and avisos[0]["id_lead"] is None

    # Mais uma mensagem no mesmo mês: continua em silêncio e não repete o aviso.
    await atendimento.receber(webhook("alô?"))
    await atendimento.aguardar_esperas()
    assert helena.enviadas == [] and len([a for a in repo.acoes if a["tipo"] == "aviso_consumo"]) == 1

    # A LawChat sobe o limite: a IA volta a responder (o gasto em cache vale por um minuto, mas o limite é lido na hora).
    repo.escritorios["esc-1"].config["limite_consumo"] = {"mensal_usd": 100.0}
    await atendimento.receber(webhook("tem alguém?"))
    await atendimento.aguardar_esperas()
    assert helena.enviadas == ["Oi! Me conta o que aconteceu?"]


async def test_nota_de_problema_sai_uma_vez_a_cada_6_horas():
    atendimento, repo, helena = montar(SIMPLES)
    repo.escritorios["esc-1"].config["limite_consumo"] = {"mensal_usd": 1.0}
    repo.chamadas.append({"id_escritorio": "esc-1", "custo_usd": 5})
    for texto in ("oi", "alô?", "tem alguém?"):
        await atendimento.receber(webhook(texto))
        await atendimento.aguardar_esperas()
    notas = [a for a in repo.acoes if a["tipo"] == "nota"]
    assert len(notas) == 1 and notas[0]["dados"]["texto"].startswith("🚫 A IA não respondeu: o limite de consumo")
    assert len([e for e in repo.eventos if e["tipo"] == "limite_de_consumo"]) == 3        # o histórico grava sempre


@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_nota_de_problema_no_banco_conta_as_ocorrencias():
    import uuid

    from app.banco.postgres import RepositorioPostgres

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        esc = str(await pool.fetchval("insert into agentesia_escritorios (nome) values ('Notas') returning id"))
        canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado) values ($1, $2) returning id",
                                    uuid.UUID(esc), "5521" + str(uuid.uuid4().int)[:9])
        contato = await pool.fetchval("insert into agentesia_contatos (id_escritorio, telefone_normalizado) values ($1, $2) returning id",
                                      uuid.UUID(esc), "55219" + str(uuid.uuid4().int)[:8])
        lead = str(await pool.fetchval("insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_sessao_helena) values ($1, $2, $3, 's') returning id",
                                       uuid.UUID(esc), contato, canal))

        async def ocorre():
            await repo.gravar_eventos(id_escritorio=esc, id_lead=lead, id_turno=None,
                                      eventos=[{"tipo": "envio_falhou", "gravidade": "erro", "responsavel": "provedor", "descricao": "x"}])
            return await repo.nota_de_problema(id_escritorio=esc, id_lead=lead, tipo="envio_falhou", texto="⚠️ Parte da resposta não foi entregue.")

        assert [await ocorre(), await ocorre(), await ocorre()] == [True, False, False]
        await pool.execute("update agentesia_acoes set criado_em = now() - interval '7 hours' where id_lead = $1::uuid and tipo = 'nota'", lead)
        assert await ocorre() is True
        textos = [r["dados"] for r in await pool.fetch("select dados from agentesia_acoes where id_lead = $1::uuid and tipo = 'nota' order by criado_em", lead)]
        assert "Primeiro aviso deste problema" in textos[-1] and "Ocorrências desde então: 4" in textos[-1]
    finally:
        await repo.fechar()
