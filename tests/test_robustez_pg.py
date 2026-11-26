"""Robustez com banco local (PGlite): recepção idempotente, turnos interrompidos, mídia pendente, conferência do esquema,
botão de IA sem conversa, etiqueta atrasada, follow-up que não fala por cima do lead e envio sem confirmação.

Só roda com AGENTESIA_TESTE_PG_URL (node db/testes/servidor_local.mjs PORTA)."""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.banco.postgres import RepositorioPostgres
from app.canal.helena_conta import HelenaConta

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
pytestmark = pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")


async def _base(pool, *, followup=None, telefone=None):
    segredo = await pool.fetchval("select vault.create_secret('token-x', 'teste')")
    esc = await pool.fetchval("insert into agentesia_escritorios (nome) values ('Robustez') returning id")
    await pool.execute("insert into agentesia_integracoes (id_escritorio, tipo, id_segredo_vault, situacao) "
                       "values ($1, 'helena', $2, 'ok')", esc, segredo)
    canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado, id_canal_helena) "
                                "values ($1, $2, $3) returning id", esc, "5511" + str(uuid.uuid4().int)[:9], "ch-" + uuid.uuid4().hex[:8])
    config = {"followup": followup} if followup else {}
    telefone = telefone or "55119" + str(uuid.uuid4().int)[:8]
    agente = await pool.fetchval(
        """insert into agentesia_agentes (id_escritorio, id_canal, nome, produto, config, situacao, modo, numeros_teste)
           values ($1, $2, 'Júlia', 'auxilio_acidente', $3::jsonb, 'ativo', 'producao', '{}') returning id""",
        esc, canal, json.dumps(config))
    etapas = {}
    for ordem, codigo in enumerate(("sdr", "closer", "contratos")):
        etapas[codigo] = await pool.fetchval(
            "insert into agentesia_agente_etapas (id_agente, codigo, ordem, principal) values ($1, $2, $3, $4) returning id",
            agente, codigo, ordem, codigo == "sdr")
    contato = await pool.fetchval("insert into agentesia_contatos (id_escritorio, nome, telefone_normalizado, id_contato_helena) "
                                  "values ($1, 'Maria', $2, $3) returning id", esc, telefone, "contato-" + uuid.uuid4().hex[:8])
    sessao = "sessao-" + uuid.uuid4().hex[:6]
    lead = await pool.fetchval(
        """insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_agente, id_etapa, id_sessao_helena)
           values ($1, $2, $3, $4, $5, $6) returning id""", esc, contato, canal, agente, etapas["sdr"], sessao)
    return {"esc": esc, "canal": canal, "agente": agente, "etapas": etapas, "lead": lead, "sessao": sessao}


async def _limpar_fila(pool):
    await pool.execute("update agentesia_acoes set situacao = 'cancelada' where situacao in ('pendente', 'executando')")
    await pool.execute("update agentesia_followups set situacao = 'cancelado' where situacao in ('pendente', 'reservado')")


async def test_metodos_de_robustez_do_repositorio():
    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1, conferir=True)   # esquema completo: sobe
    pool = repo._pool
    try:
        assert repo._midia_pendente                      # o servidor de teste aplica a 005
        b = await _base(pool)
        lead = await repo.lead(str(b["lead"]))
        id_msg = await repo.gravar_mensagem(lead=lead, autor="lead", tipo="documento", texto=None, texto_extraido="[doc]",
                                            url_midia="https://x.invalid/laudo.pdf", enviada_em=datetime.now(timezone.utc),
                                            id_externo="wamid-" + uuid.uuid4().hex)
        mensagem = await repo.mensagem_por_id_externo(str(b["esc"]), (await pool.fetchval(
            "select id_externo from agentesia_mensagens where id = $1", uuid.UUID(id_msg))))
        assert mensagem.id == id_msg and mensagem.id_turno is None and mensagem.url_midia.endswith("laudo.pdf")

        await repo.marcar_midia_pendente(id_msg)
        assert (await repo.mensagens_pendentes(lead.id))[0].midia_pendente_desde is not None
        await repo.atualizar_texto_extraido(id_msg, "[Laudo lido]")
        pendente = (await repo.mensagens_pendentes(lead.id))[0]
        assert pendente.midia_pendente_desde is None and pendente.texto_extraido == "[Laudo lido]"

        quando = datetime.now(timezone.utc) + timedelta(minutes=3)
        await repo.marcar_resposta(lead.id, quando)
        assert abs((await repo.responder_apos(lead.id) - quando).total_seconds()) < 1
        assert await repo.reservar_lead(lead.id, 1)
        await repo.renovar_reserva(lead.id, 300)
        assert await pool.fetchval("select processando_ate > now() + interval '200 seconds' from agentesia_leads where id = $1",
                                   b["lead"])

        await repo.atualizar_lead(lead.id, id_agente=None, id_etapa=None)
        await repo.atualizar_lead(lead.id, id_agente=str(b["agente"]), id_etapa=str(b["etapas"]["sdr"]))
        assert (await repo.lead(lead.id)).id_agente == str(b["agente"])

        id_turno = await repo.abrir_turno(lead=lead, modo="producao", etapa_antes="sdr")
        await pool.execute("update agentesia_turnos set iniciado_em = now() - interval '30 minutes' where id = $1::uuid", id_turno)
        fechados = await repo.fechar_turnos_interrompidos(10)
        assert {"id_turno": id_turno, "id_escritorio": str(b["esc"]), "id_lead": lead.id} in [
            {k: f[k] for k in ("id_turno", "id_escritorio", "id_lead")} for f in fechados]
        assert await pool.fetchval("select situacao from agentesia_turnos where id = $1::uuid", id_turno) == "erro"
        assert id_turno not in [f["id_turno"] for f in await repo.fechar_turnos_interrompidos(10)]   # só uma vez

        # Turno órfão (deploy cortou): 40 s, lead sem reserva viva, mensagem do lead presa e nada da IA enviado.
        await repo.liberar_lead(lead.id)
        await repo.marcar_resposta(lead.id, None)
        orfao = await repo.abrir_turno(lead=lead, modo="producao", etapa_antes="sdr")
        await repo.marcar_no_turno([id_msg], orfao)
        await pool.execute("update agentesia_turnos set iniciado_em = now() - interval '40 seconds' where id = $1::uuid", orfao)
        await repo.reservar_lead(lead.id, 90)                                   # dono vivo: não mexe
        assert orfao not in [f["id_turno"] for f in await repo.fechar_turnos_interrompidos(10)]
        await repo.liberar_lead(lead.id)                                        # dono morreu
        [item] = [f for f in await repo.fechar_turnos_interrompidos(10) if f["id_turno"] == orfao]
        assert item["enviadas"] == 0 and item["devolvidas"] == 1
        assert [m.id for m in await repo.mensagens_pendentes(lead.id)] == [id_msg]  # volta para a fila
        assert await repo.responder_apos(lead.id) is not None                   # e a IA responde já
    finally:
        await repo.fechar()


async def test_conferencia_do_esquema_falha_rapido(monkeypatch):
    from app.banco import postgres

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    try:
        monkeypatch.setitem(postgres.ESQUEMA_ESSENCIAL, "agentesia_leads", ("responder_apos", "coluna_que_nao_existe"))
        with pytest.raises(RuntimeError, match="coluna_que_nao_existe"):
            await repo.conferir_esquema()
    finally:
        await repo.fechar()


async def test_botao_sem_conversa_deixa_nota_pela_sessao():
    from app import ia_controle

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        b = await _base(pool)
        r = await ia_controle.mudar_ia(pool, str(b["esc"]), ligar=True, origem="botao", id_sessao="sessao-desconhecida")
        assert r["encontrados"] == 0
        nota = await pool.fetchrow("select id_lead, dados from agentesia_acoes where id_escritorio = $1 and tipo = 'nota'", b["esc"])
        dados = nota["dados"] if isinstance(nota["dados"], dict) else json.loads(nota["dados"])
        assert nota["id_lead"] is None and dados["id_sessao"] == "sessao-desconhecida"
        assert "Conversa não encontrada" in dados["texto"]
        # Pela etiqueta, nada (a Helena repete eventos).
        await ia_controle.mudar_ia(pool, str(b["esc"]), ligar=True, origem="etiqueta", telefone="5599999999999")
        assert await pool.fetchval("select count(*) from agentesia_acoes where id_escritorio = $1", b["esc"]) == 1
    finally:
        await repo.fechar()


class HelenaGravando:
    def __init__(self, falhar_envio_em=None, timeout_no_envio=False):
        self.chamadas, self.envios = [], 0
        self.falhar_envio_em, self.timeout_no_envio = falhar_envio_em, timeout_no_envio

    def __call__(self, pedido):
        corpo = json.loads(pedido.content) if pedido.content else None
        self.chamadas.append((pedido.method, pedido.url.path, corpo))
        if pedido.url.path.endswith("/message") and pedido.method == "POST":
            self.envios += 1
            if self.timeout_no_envio:
                raise httpx.ReadTimeout("demorou", request=pedido)
            if self.falhar_envio_em == self.envios:
                return httpx.Response(502)
            return httpx.Response(200, json={"id": "msg-" + uuid.uuid4().hex[:8]})
        return httpx.Response(200, json={})


async def test_etiqueta_atrasada_de_etapa_antiga_e_ignorada():
    from app import automacoes
    from app.acoes import Executor

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        await _limpar_fila(pool)
        b = await _base(pool)
        config = {"funcoes": {"crm": True}, "automacoes": {"etapa:closer": {"adicionar_etiquetas": ["🛒 Comercial"]}}}
        acoes = automacoes.montar_acoes(config, {"id_painel": "p1"}, ["etapa:closer"], id_lead=str(b["lead"]),
                                        id_turno=uuid.uuid4().hex)
        assert acoes[0]["dados"]["gatilho"] == "etapa:closer"
        await repo.enfileirar_acoes(id_escritorio=str(b["esc"]), id_lead=str(b["lead"]), id_turno=None, acoes=acoes)
        await pool.execute("update agentesia_leads set id_etapa = $2 where id = $1", b["lead"], b["etapas"]["contratos"])
        helena = HelenaGravando()
        executor = Executor(pool, "https://api.helena.run", helena_por_token=lambda t, u: HelenaConta(
            t, u, httpx.AsyncClient(transport=httpx.MockTransport(helena))))
        await executor.rodar_uma_vez()
        linha = await pool.fetchrow("select situacao, resultado from agentesia_acoes where id_lead = $1 and tipo = 'etiquetar'",
                                    b["lead"])
        resultado = linha["resultado"] if isinstance(linha["resultado"], dict) else json.loads(linha["resultado"])
        assert linha["situacao"] == "feita" and resultado["acao"] == "ignorada"
        assert helena.chamadas == []                       # nenhuma etiqueta voltou para trás
    finally:
        await repo.fechar()


async def test_mensagem_ao_lead_sem_confirmacao_nao_repete_e_pede_conferencia():
    from app.acoes import Executor

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        await _limpar_fila(pool)
        b = await _base(pool)
        await repo.enfileirar_acoes(id_escritorio=str(b["esc"]), id_lead=str(b["lead"]), id_turno=None, acoes=[
            {"tipo": "enviar_mensagem", "chave_unica": f"{b['lead']}:msg:{uuid.uuid4().hex}", "dados": {"texto": "Seu link"}}])
        helena = HelenaGravando(timeout_no_envio=True)
        executor = Executor(pool, "https://api.helena.run", helena_por_token=lambda t, u: HelenaConta(
            t, u, httpx.AsyncClient(transport=httpx.MockTransport(helena))))
        await executor.rodar_uma_vez()
        assert await pool.fetchval("select situacao from agentesia_acoes where id_lead = $1 and tipo = 'enviar_mensagem'",
                                   b["lead"]) == "falhou"                 # definitiva: não reenvia em 1, 5, 30 min
        nota = await pool.fetchval("select dados->>'texto' from agentesia_acoes where id_lead = $1 and tipo = 'nota'", b["lead"])
        assert "Confira se a mensagem chegou" in nota
    finally:
        await repo.fechar()


FOLLOWUP = {"ativo": True, "horario": {"inicio": 0, "fim": 24, "dias": [0, 1, 2, 3, 4, 5, 6]}, "intervalo_minimo_min": 0,
            "passos": [{"apos_horas": 1, "modo": "ia", "instrucao": "retome"}, {"apos_horas": 24, "modo": "texto", "texto": "Oi"}]}


async def _followup_vencido(pool, b):
    base = datetime.now(timezone.utc) - timedelta(hours=2)
    await pool.execute("update agentesia_leads set ultima_mensagem_lead_em = $2 where id = $1", b["lead"], base - timedelta(minutes=5))
    await pool.execute("""insert into agentesia_followups (id_escritorio, id_lead, id_agente, passo, base, agendado_para)
                          values ($1, $2, $3, 0, $4, now() - interval '1 minute')""", b["esc"], b["lead"], b["agente"], base)


async def test_followup_nao_sai_se_o_lead_escreveu_durante_a_geracao():
    from app.followup import servico
    from app.modelo import ModeloFalso

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        await _limpar_fila(pool)
        b = await _base(pool, followup=FOLLOWUP)
        await _followup_vencido(pool, b)

        async def gera_enquanto_o_lead_escreve(_s, _c):
            # Enquanto a IA escreve o follow-up, o lead manda "oi, tô aqui" (e o turno cancela o follow-up).
            await pool.execute(
                """insert into agentesia_mensagens (id_escritorio, id_lead, autor, tipo, texto, enviada_em)
                   values ($1, $2, 'lead', 'texto', 'oi, tô aqui', now())""", b["esc"], b["lead"])
            return {"mensagens": ["Passando para saber se ficou alguma dúvida"]}

        helena = HelenaGravando()
        disparador = servico.Disparador(pool, ModeloFalso({"followup": gera_enquanto_o_lead_escreve}), "https://api.helena.run",
                                        helena_por_token=lambda t, u: HelenaConta(t, u, httpx.AsyncClient(
                                            transport=httpx.MockTransport(helena))))
        await disparador.rodar_uma_vez()
        assert helena.envios == 0
        linhas = [dict(r) for r in await pool.fetch("select situacao, motivo from agentesia_followups where id_lead = $1", b["lead"])]
        assert linhas == [{"situacao": "cancelado", "motivo": "respondeu_durante_o_envio"}]   # sem passo seguinte
    finally:
        await repo.fechar()


async def test_followup_pela_metade_conta_como_enviado_e_nao_reenvia():
    from app.followup import servico
    from app.modelo import ModeloFalso

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        await _limpar_fila(pool)
        b = await _base(pool, followup=FOLLOWUP)
        await _followup_vencido(pool, b)
        helena = HelenaGravando(falhar_envio_em=2)
        disparador = servico.Disparador(pool, ModeloFalso({"followup": {"mensagens": ["Oi Maria!", "Ficou alguma dúvida?"]}}),
                                        "https://api.helena.run", helena_por_token=lambda t, u: HelenaConta(
                                            t, u, httpx.AsyncClient(transport=httpx.MockTransport(helena))))
        await disparador.rodar_uma_vez()
        linhas = [dict(r) for r in await pool.fetch(
            "select passo, situacao from agentesia_followups where id_lead = $1 order by passo", b["lead"])]
        assert linhas == [{"passo": 0, "situacao": "enviado"}, {"passo": 1, "situacao": "pendente"}]
        assert await pool.fetchval("select count(*) from agentesia_eventos where id_lead = $1 and tipo = 'followup_envio_parcial'",
                                   b["lead"]) == 1
    finally:
        await repo.fechar()


async def test_followup_com_limite_de_consumo_estourado_nao_chama_a_ia():
    from app.followup import servico
    from app.modelo import ModeloFalso

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        await _limpar_fila(pool)
        b = await _base(pool, followup=FOLLOWUP)
        await pool.execute("""update agentesia_escritorios set config = '{"limite_consumo": {"mensal_usd": 1, "acao": "pausar"}}'::jsonb
                              where id = $1""", b["esc"])
        await pool.execute("""insert into agentesia_chamadas_ia (id_escritorio, papel, modelo, custo_usd, sucesso)
                              values ($1, 'etapa', 'gpt-4.1', 5, true)""", b["esc"])
        await _followup_vencido(pool, b)
        modelo = ModeloFalso({"followup": {"mensagens": ["texto da IA"]}})
        helena = HelenaGravando()
        disparador = servico.Disparador(pool, modelo, "https://api.helena.run", helena_por_token=lambda t, u: HelenaConta(
            t, u, httpx.AsyncClient(transport=httpx.MockTransport(helena))))
        await disparador.rodar_uma_vez()
        assert modelo.pedidos == [] and helena.envios == 1
        assert "Passando para saber" in helena.chamadas[0][2]["text"]
    finally:
        await repo.fechar()
