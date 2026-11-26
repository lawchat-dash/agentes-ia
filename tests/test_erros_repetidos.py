"""Tela de Erros (26/11): o mesmo erro do mesmo lead gravado duas vezes aparecia em duas linhas; resolver uma deixava
a outra e parecia que o erro "voltou". Agora a lista agrupa (com repeticoes) e resolver fecha as repetições."""

import os
import uuid

import pytest

from app.banco.postgres import RepositorioPostgres
from app.gestao.repositorio import RepositorioGestao

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")


@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_resolver_fecha_as_repeticoes_do_mesmo_lead():
    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        esc = await pool.fetchval("insert into agentesia_escritorios (nome) values ('Erros repetidos') returning id")
        numero = "5511" + str(uuid.uuid4().int)[:9]
        canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado) values ($1, $2) "
                                    "returning id", esc, numero)
        contato = await pool.fetchval("insert into agentesia_contatos (id_escritorio, nome, telefone_normalizado) "
                                      "values ($1, 'Rosa', $2) returning id", esc, numero)
        lead = await pool.fetchval("insert into agentesia_leads (id_escritorio, id_contato, id_canal) values ($1, $2, $3) "
                                   "returning id", esc, contato, canal)
        for _ in range(2):
            await pool.execute("insert into agentesia_eventos (id_escritorio, id_lead, tipo, gravidade, responsavel, descricao) "
                               "values ($1, $2, 'erro_no_turno', 'critico', 'lawchat', 'Erro inesperado')", esc, lead)
        await pool.execute("insert into agentesia_eventos (id_escritorio, tipo, gravidade, responsavel, descricao) "
                           "values ($1, 'outro', 'aviso', 'cliente', 'Sem lead')", esc)
        gestao = RepositorioGestao(pool)
        abertos = await gestao.eventos(str(esc), abertos=True)
        do_lead = [e for e in abertos if e["tipo"] == "erro_no_turno"]
        assert len(do_lead) == 1 and do_lead[0]["repeticoes"] == 2 and len(abertos) == 2

        usuario = await pool.fetchval("select id from agentesia_usuarios limit 1")
        assert await gestao.resolver_evento(str(do_lead[0]["id"]), str(esc), str(usuario) if usuario else None)
        restantes = await gestao.eventos(str(esc), abertos=True)
        assert [e["tipo"] for e in restantes] == ["outro"]                 # as duas repetições fecharam; o outro não
        assert not await gestao.resolver_evento(str(do_lead[0]["id"]), str(esc), None)   # já resolvido
    finally:
        await repo.fechar()
