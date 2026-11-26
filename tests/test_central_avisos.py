"""Central de avisos da equipe LawChat: erro grave vira WhatsApp, 1 por problema a cada 30 min."""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app import central_avisos

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")


@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_erro_grave_vira_aviso_da_equipe_uma_vez_por_janela(monkeypatch):
    from app.acoes import Executor
    from app.banco.postgres import RepositorioPostgres
    from app.canal.helena_conta import HelenaConta

    monkeypatch.setenv("AGENTESIA_HELENA_TOKEN_LAWCHAT", "token-lawchat")
    monkeypatch.setenv("AGENTESIA_ALERTA_LAWCHAT_DE", "11 90000-0001")
    monkeypatch.setenv("AGENTESIA_ALERTA_LAWCHAT_PARA", "11 90000-0002, 11 90000-0003")
    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        await pool.execute("update agentesia_acoes set situacao = 'cancelada' where situacao in ('pendente', 'executando')")
        desde = datetime.now(timezone.utc) - timedelta(seconds=1)
        esc = str(await pool.fetchval("insert into agentesia_escritorios (nome) values ('Central') returning id"))
        evento = {"tipo": "ia_nao_respondeu", "gravidade": "critico", "responsavel": "provedor", "descricao": "OpenAI fora do ar"}
        await repo.gravar_eventos(id_escritorio=esc, id_lead=None, id_turno=None, eventos=[evento, evento])
        await repo.gravar_eventos(id_escritorio=esc, id_lead=None, id_turno=None, eventos=[
            {"tipo": "dado_invalido", "gravidade": "erro", "responsavel": "cliente", "descricao": "do cliente: não vai para a LawChat"}])
        novos, ate = await central_avisos.varrer(pool, desde)
        assert novos == 1 and ate > desde
        assert (await central_avisos.varrer(pool, ate))[0] == 0                       # nada novo desde a última leitura

        enviados = []

        def helena(pedido: httpx.Request) -> httpx.Response:
            enviados.append((pedido.headers.get("authorization"), json.loads(pedido.content)))
            return httpx.Response(200, json={"id": "m"})

        executor = Executor(pool, "https://api.helena.run",
                            helena_por_token=lambda t, u: HelenaConta(t, u, httpx.AsyncClient(transport=httpx.MockTransport(helena))))
        await executor.rodar_uma_vez()
        assert len(enviados) == 2 and all("token-lawchat" in (a or "") for a, _ in enviados)
        assert "OpenAI fora do ar" in json.dumps(enviados[0][1], ensure_ascii=False) and "Central" in json.dumps(enviados[0][1], ensure_ascii=False)
    finally:
        await repo.fechar()


def test_sem_configuracao_fica_desligada(monkeypatch):
    monkeypatch.delenv("AGENTESIA_HELENA_TOKEN_LAWCHAT", raising=False)
    assert central_avisos.configurada() is None
