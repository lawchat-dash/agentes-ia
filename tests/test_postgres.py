"""O mesmo pipeline, agora gravando num Postgres de verdade (local, em memória).

Só roda quando AGENTESIA_TESTE_PG_URL está definida. Para subir o banco local:
    node db/testes/servidor_local.mjs
    AGENTESIA_TESTE_PG_URL=postgresql://postgres:postgres@127.0.0.1:55432/postgres pytest tests/test_postgres.py
"""

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.banco.postgres import RepositorioPostgres
from app.config import Configuracao
from app.modelo import ModeloFalso
from app.pipeline import Atendimento
from tests.test_pipeline import HelenaFalsa, webhook
from tests.test_turno import extrai, fala

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
pytestmark = pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")


async def _cenario(repo: RepositorioPostgres):
    """Cadastra um escritório, canal, agente e etapas novos e devolve os identificadores."""
    conta, numero_canal = str(uuid.uuid4()), "55119" + str(uuid.uuid4().int)[:8]
    pool = repo._pool
    segredo = await pool.fetchval("insert into vault.decrypted_secrets (decrypted_secret) values ('token-x') returning id")
    escritorio = await pool.fetchval(
        """insert into agentesia_escritorios (nome, id_conta_helena, id_segredo_helena, config)
           values ('Escritório Teste', $1::uuid, $2, $3::jsonb) returning id""",
        conta, segredo, '{"numeros_teste": ["5511988887777"], "espera_teste_s": 0}')
    canal = await pool.fetchval(
        "insert into agentesia_canais (id_escritorio, numero_normalizado, id_canal_helena) values ($1, $2, $3) returning id",
        escritorio, numero_canal, "ch-" + conta[:8])
    agente = await pool.fetchval(
        """insert into agentesia_agentes (id_escritorio, id_canal, nome, situacao, config)
           values ($1, $2, 'Júlia', 'ativo', '{"honorarios": "30% do valor recebido"}'::jsonb) returning id""",
        escritorio, canal)
    for ordem, (codigo, principal) in enumerate([("sdr", True), ("closer", False), ("desqualificado", False)], 1):
        await pool.execute(
            "insert into agentesia_agente_etapas (id_agente, codigo, ordem, principal) values ($1, $2, $3, $4)",
            agente, codigo, ordem, principal)
    return conta, numero_canal, str(escritorio)


def _config():
    return Configuracao(banco_url=URL, helena_url="http://helena.invalid", modelo_padrao="falso", modelo_falso=True,
                        espera_minima_s=0, espera_maxima_s=0, espera_padrao_s=0, segundos_por_letra=0, max_reprocessos=2)


async def test_conversa_completa_no_postgres():
    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)  # o servidor de teste só aceita uma
    try:
        conta, numero_canal, id_escritorio = await _cenario(repo)
        helena = HelenaFalsa()
        # Respostas pelo conteúdo, e não pela ordem: com banco de verdade um turno pode ser refeito.
        def extrator(_sistema, conteudo):
            novas = conteudo.split("MENSAGENS NOVAS DO LEAD:")[1]
            if "sou aposentado" in novas:
                return extrai([("aposentado", "sim", "sou aposentado")])
            fatos = []
            if "caí da moto" in novas:
                fatos.append(("acidente_descricao", "caí da moto", "caí da moto"))
            if "em 2022" in novas:
                fatos.append(("acidente_ano", "2022", "em 2022"))
            return extrai(fatos)

        def etapa(sistema, _conteudo):
            if "ETAPA: encerramento" in sistema:
                return fala("Entendi. Nesse caso o escritório não consegue atuar.")
            return fala("Poxa, sinto muito. Ficou com alguma sequela?")

        modelo = ModeloFalso({"extrator": extrator, "etapa": etapa})
        atendimento = Atendimento(repo, modelo, _config(), helena, digitar=False)

        def chega(texto, **extra):
            corpo = webhook(texto, para=numero_canal, **extra)
            corpo["content"]["companyId"] = conta
            return corpo

        # 1º turno: duas mensagens fora de ordem viram um lote só, na ordem do WhatsApp.
        base = datetime.now(timezone.utc)
        await atendimento.receber(chega("em 2022", quando=base - timedelta(seconds=1)))
        repetida = chega("oi, caí da moto", quando=base - timedelta(seconds=2))
        await atendimento.receber(repetida)
        assert (await atendimento.receber(repetida))["motivo"] == "repetido"
        await atendimento.aguardar_esperas()
        assert helena.enviadas == ["Poxa, sinto muito. Ficou com alguma sequela?"]
        assert any("[lead] oi, caí da moto\n[lead] em 2022" in p["conteudo"] for p in modelo.pedidos)

        pool = repo._pool
        lead = await pool.fetchrow("select * from agentesia_leads where id_escritorio = $1::uuid", id_escritorio)
        assert await repo.fatos_vigentes(str(lead["id"])) == {"acidente_descricao": "caí da moto", "acidente_ano": 2022}

        # Eco da própria IA é reconhecido pelo id devolvido no envio.
        eco = chega("Poxa...", de=numero_canal, direcao="TO_HUB", origem="API", evento="MESSAGE_SENT", id_msg=helena.ids[0])
        eco["content"]["details"] = {"from": "+" + numero_canal, "to": "+5511988887777"}
        assert (await atendimento.receber(eco))["motivo"] == "eco_da_ia"

        # 2º turno: o fato desqualifica, a etapa muda e o lead é encerrado.
        await atendimento.receber(chega("na verdade sou aposentado"))
        await atendimento.aguardar_esperas()
        lead = await pool.fetchrow(
            """select l.estado, l.motivo_estado, e.codigo from agentesia_leads l
               join agentesia_agente_etapas e on e.id = l.id_etapa where l.id = $1""", lead["id"])
        assert (lead["estado"], lead["motivo_estado"], lead["codigo"]) == ("encerrado", "desqualificado:aposentado", "desqualificado")

        turnos = await pool.fetch(
            "select situacao, etapa_antes, etapa_depois, contexto is not null as tem_contexto from agentesia_turnos "
            "where id_escritorio = $1::uuid and situacao <> 'descartado' order by iniciado_em", id_escritorio)
        assert [(t["situacao"], t["etapa_antes"], t["etapa_depois"], t["tem_contexto"]) for t in turnos] == [
            ("respondido", "sdr", "sdr", True), ("respondido", "sdr", "desqualificado", True)]
        autores = await pool.fetch(
            "select autor, id_turno is not null as no_turno from agentesia_mensagens where id_escritorio = $1::uuid "
            "order by enviada_em, registrada_em", id_escritorio)
        assert [a["autor"] for a in autores] == ["lead", "lead", "ia", "lead", "ia"] and all(a["no_turno"] for a in autores)
        assert await pool.fetchval("select count(*) from agentesia_chamadas_ia where id_escritorio = $1::uuid", id_escritorio) >= 4
        assert await pool.fetchval(
            "select count(*) from agentesia_lead_fatos where id_escritorio = $1::uuid and trecho is not null", id_escritorio) == 3

        # Atendente fala: pausa com data de volta.
        humano = chega("Oi, aqui é a Paula", de=numero_canal, direcao="TO_HUB", origem="DEFAULT", evento="MESSAGE_SENT")
        humano["content"]["details"] = {"from": "+" + numero_canal, "to": "+5511988887777"}
        await atendimento.receber(humano)
        assert await pool.fetchval("select estado from agentesia_leads where id_escritorio = $1::uuid", id_escritorio) == "encerrado"
    finally:
        await repo.fechar()


async def test_campo_de_lead_desconhecido_e_recusado():
    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)  # o servidor de teste só aceita uma
    try:
        with pytest.raises(ValueError):
            await repo.atualizar_lead(str(uuid.uuid4()), **{"estado = 'x'; --": 1})
    finally:
        await repo.fechar()
