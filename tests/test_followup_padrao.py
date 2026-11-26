"""Follow-up ligado por padrão (opt-out) e as regras de não enviar (docs/FOLLOWUP.md).

- a ativação copia a cadência e os prompts padrão do produto da biblioteca e já liga;
- desligar pela aba Follow-up e religar pelo "Ligar com o padrão";
- o aviso (Início, Meus produtos, tela do produto) só aparece quando está desligado;
- o admin vê todos os escritórios e liga em lote (simulação, lista e "todos os desligados"), com registro;
- o disparador não manda para desqualificado, contrato assinado, IA desligada, atendente que assumiu, fora do horário,
  número oficial com a janela de 24 h fechada sem modelo; com o saldo acabado manda o texto de reserva, sem IA.
Os testes com banco só rodam com AGENTESIA_TESTE_PG_URL (banco local). A Helena é simulada.
"""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.followup import padrao, regras
from tests.test_gestao import ambiente  # noqa: F401  (fixture do painel com a Helena simulada)

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
COM_BANCO = pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
PADRAO = {"cadence": [{"order": 3, "delay": "24h"}, {"order": 1, "delay": "10m"}, {"order": 2, "delay": "1h"}, {"order": 4, "delay": "3d"}],
          "restart_on_reply": True,
          "agentes": {"sdr": {"nome_agente": "Retomada SDR", "prompt": "Lembre do caso do acidente.", "habilitado_padrao": True, "ordem": 0},
                      "closer": {"prompt": "Lembre dos honorários só no êxito.", "habilitado_padrao": True, "ordem": 1},
                      "contrato": {"prompt": "Peça os dados que faltam.", "habilitado_padrao": True, "ordem": 2},
                      "assinatura": {"prompt": "", "habilitado_padrao": False, "ordem": 3}}}


# ------------------------------------------------------------------ sem banco
def test_le_a_cadencia_do_produto_em_qualquer_formato():
    assert padrao.horas_do_atraso("10m") == pytest.approx(1 / 6)
    assert [padrao.horas_do_atraso(v) for v in ("1h", "2d", "1sem", 5, {"delay": "30min"})] == [1, 48, 168, 5, 0.5]
    assert padrao.horas_do_atraso("amanhã") is None and padrao.horas_do_atraso(0) is None
    assert padrao.cadencia_do_produto(PADRAO) == [round(1 / 6, 4), 1, 24, 72]          # em ordem, pelo "order"
    assert padrao.cadencia_do_produto({"cadence": [1, 5, 24]}) == [1, 5, 24]             # formato antigo (horas)
    assert padrao.cadencia_do_produto(json.dumps({"cadence": ["1h", "1h"]})) == [1]      # repetido sai
    assert padrao.cadencia_do_produto(None) == []


def test_config_do_produto_mapeia_etapas_e_prompts():
    c = padrao.config_do_produto({"padrao_followup": PADRAO}, ativo=True)
    assert c["ativo"] is True
    assert [p["apos_horas"] for p in c["passos"]] == [round(1 / 6, 4), 1, 24, 72]
    assert c["etapas"] == ["sdr", "periododegraca", "closer", "contratos"]               # assinatura veio desligada
    assert c["por_etapa"] == {"sdr": "Lembre do caso do acidente.", "periododegraca": "Lembre do caso do acidente.",
                              "closer": "Lembre dos honorários só no êxito.", "contratos": "Peça os dados que faltam."}
    assert padrao.resumo(c) == ["10 min", "1 h", "24 h", "72 h"]
    # Produto sem padrão: a cadência do sistema, todas as etapas de conversa.
    vazio = padrao.config_do_produto({}, ativo=False)
    assert not vazio["ativo"] and vazio["etapas"] == [] and [p["apos_horas"] for p in vazio["passos"]] == list(regras.CADENCIA_PADRAO)
    assert padrao.resumo(vazio) == ["1 h", "5 h", "24 h", "72 h", "7 dias", "15 dias", "30 dias"]
    assert padrao.situacao({}) == {"ligado": False, "configurado": False, "passos": 7, "resumo": padrao.resumo(None)}
    assert padrao.situacao({"followup": c})["ligado"] is True


def test_desqualificado_e_contrato_assinado_nunca_recebem():
    conversa = {"sdr", "closer"}
    for etapa in ("desqualificado", "contrato_assinado"):
        assert not regras.Config.de({"ativo": True, "etapas": [etapa]}).vale_para(etapa, conversa | {etapa})
    assert regras.Config.de({"ativo": True}).vale_para("sdr", conversa)
    assert regras.validar({"passos": [{"apos_horas": 1 / 6}]})["passos"][0]["apos_horas"] == pytest.approx(1 / 6)   # 10 min vale
    with pytest.raises(ValueError, match="10 minutos"):
        regras.validar({"passos": [{"apos_horas": 0.1}]})


# ------------------------------------------------------------------ ativação, aviso e admin (banco local)
def _incluir_rotas(cliente):
    from app.gestao.rotas_followup import api as api_followup
    app = cliente._transport.app
    if not any(getattr(r, "path", "") == "/api/admin/followup" for r in app.router.routes):
        app.include_router(api_followup)


async def _produto_com_padrao(cliente, h, nome):
    from tests.test_lixeira_solta_numero import _produto
    id_ativado, agentes = await _produto(cliente, h, nome)
    rascunho = (await cliente.get(f"/api/produtos-ativados/{id_ativado}", headers=h)).json()
    assert (await cliente.patch(f"/api/admin/biblioteca/produtos/{rascunho['id_produto_biblioteca']}",
                                json={"padrao_followup": PADRAO})).status_code == 200
    return id_ativado, agentes, rascunho["id_produto_biblioteca"]


async def _config_fu(pool, id_agente):
    bruto = await pool.fetchval("select config->'followup' from agentesia_agentes where id = $1::uuid", id_agente)
    return json.loads(bruto) if isinstance(bruto, str) else bruto


async def _situacao_na_lista(cliente, h, id_ativado):
    return next(p for p in (await cliente.get("/api/produtos-ativados?lixeira=0", headers=h)).json() if p["id"] == id_ativado)["followup_situacao"]


@COM_BANCO
async def test_ativacao_liga_o_followup_com_o_padrao_desligar_religar_e_aviso(ambiente):
    from tests.test_gestao import _entrar
    from tests.test_lixeira_solta_numero import _escritorio, _payload

    cliente, _simulada, email_admin, banco = ambiente
    pool = banco._pool
    _incluir_rotas(cliente)
    await _entrar(cliente, email_admin, "senha-admin-123")
    esc, h, zapi, oficial = await _escritorio(cliente, pool, "Follow-up Padrão", "token-bom-111111")
    id_a, agentes_a, id_catalogo = await _produto_com_padrao(cliente, h, "Auxílio FU")

    # A etapa "Follow-up" do assistente mostra a cadência que vai ser copiada.
    previa = (await cliente.get(f"/api/biblioteca/produtos/{id_catalogo}/followup-padrao", headers=h)).json()
    assert previa["resumo"] == ["10 min", "1 h", "24 h", "72 h"] and previa["do_produto"] and previa["por_que"]

    # 1. Ativar sem mexer no interruptor: follow-up LIGADO com o padrão do produto.
    ativado = await cliente.post(f"/api/produtos-ativados/{id_a}/ativar", headers=h, json=_payload(agentes_a, zapi))
    assert ativado.status_code == 200, ativado.text
    id_agente = ativado.json()["id_agente"]
    fu = await _config_fu(pool, id_agente)
    assert fu["ativo"] is True and [p["apos_horas"] for p in fu["passos"]] == [round(1 / 6, 4), 1, 24, 72]
    assert fu["etapas"] == ["sdr", "periododegraca", "closer", "contratos"] and fu["por_etapa"]["closer"].startswith("Lembre")
    assert (await _situacao_na_lista(cliente, h, id_a))["ligado"] is True
    assert (await cliente.get(f"/api/produtos-ativados/{id_a}", headers=h)).json()["followup_situacao"]["resumo"] == previa["resumo"]
    assert "follow-up ligado (10 min, 1 h, 24 h, 72 h)" in await pool.fetchval(
        "select resumo from agentesia_alteracoes where id_registro = $1::uuid and acao = 'ativou' order by criado_em desc limit 1", id_a)
    assert (await cliente.get("/api/inicio", headers=h)).json()["followup_desligado"] == []      # ligado: sem aviso

    # 2. Desligar pela aba Follow-up do agente: o aviso aparece (lista, produto e Início).
    tela = (await cliente.get(f"/api/agentes/{id_agente}/followup", headers=h)).json()["config"]
    assert (await cliente.put(f"/api/agentes/{id_agente}/followup", headers=h, json={**tela, "ativo": False})).status_code == 200
    assert (await _situacao_na_lista(cliente, h, id_a)) == {"ligado": False, "configurado": True, "passos": 4, "resumo": previa["resumo"]}
    assert (await cliente.get("/api/inicio", headers=h)).json()["followup_desligado"] == [{"id_ativado": id_a, "nome": "Júlia"}]

    # Sincronizar (salvar a edição do produto) não religa nem desliga: quem manda é a aba Follow-up.
    sinc = await cliente.post(f"/api/produtos-ativados/{id_a}/sincronizar", headers=h, json=_payload(agentes_a, zapi, followup_ativo=True))
    assert sinc.status_code == 200, sinc.text
    assert (await _config_fu(pool, id_agente))["ativo"] is False

    # 3. "Ligar com o padrão": liga de novo e registra.
    religado = await cliente.post(f"/api/produtos-ativados/{id_a}/followup/ligar-padrao", headers=h)
    assert religado.status_code == 200, religado.text
    assert religado.json()["followup"]["ligado"] is True and religado.json()["aviso"] is None
    assert (await _config_fu(pool, id_agente))["ativo"] is True
    assert (await cliente.get("/api/inicio", headers=h)).json()["followup_desligado"] == []
    registro = await pool.fetchrow(
        "select resumo, antes, depois from agentesia_alteracoes where id_registro = $1::uuid and resumo like 'Follow-up de %padrão%' order by criado_em desc limit 1", id_agente)
    assert "ligado com o padrão do produto (painel): 10 min, 1 h, 24 h, 72 h" in registro["resumo"]
    assert json.loads(registro["antes"])["ativo"] is False and json.loads(registro["depois"])["ativo"] is True

    # 4. Quem desliga na ativação (opt-out): nasce desligado, com a cadência pronta para religar.
    id_b, agentes_b, _ = await _produto_com_padrao(cliente, h, "BPC FU")
    ativado_b = await cliente.post(f"/api/produtos-ativados/{id_b}/ativar", headers=h, json=_payload(agentes_b, oficial, followup_ativo=False))
    assert ativado_b.status_code == 200, ativado_b.text
    fu_b = await _config_fu(pool, ativado_b.json()["id_agente"])
    assert fu_b["ativo"] is False and len(fu_b["passos"]) == 4
    assert [p["id_ativado"] for p in (await cliente.get("/api/inicio", headers=h)).json()["followup_desligado"]] == [id_b]
    # Produto pausado não aparece no aviso (o aviso é para produto ativo).
    assert (await cliente.post(f"/api/produtos-ativados/{id_b}/status", headers=h, json={"status": "pausado"})).status_code == 200
    assert (await cliente.get("/api/inicio", headers=h)).json()["followup_desligado"] == []
    # Outro escritório não liga o produto deste.
    _esc2, h2, _z2, _o2 = await _escritorio(cliente, pool, "Follow-up Outro", "token-bom-222222")
    assert (await cliente.post(f"/api/produtos-ativados/{id_b}/followup/ligar-padrao", headers=h2)).status_code == 404


@COM_BANCO
async def test_admin_ve_todos_e_liga_em_lote_com_registro(ambiente):
    from tests.test_gestao import _entrar
    from tests.test_lixeira_solta_numero import _escritorio, _payload

    cliente, _simulada, email_admin, banco = ambiente
    pool = banco._pool
    _incluir_rotas(cliente)
    await _entrar(cliente, email_admin, "senha-admin-123")
    ids = []
    for i, token in enumerate(("token-bom-333333", "token-bom-444444")):
        _esc, h, zapi, _o = await _escritorio(cliente, pool, f"Lote {i} {uuid.uuid4().hex[:4]}", token)
        id_ativado, agentes, _ = await _produto_com_padrao(cliente, h, f"Lote {i}")
        resposta = await cliente.post(f"/api/produtos-ativados/{id_ativado}/ativar", headers=h, json=_payload(agentes, zapi))
        assert resposta.status_code == 200, resposta.text
        # Como os produtos ativados ANTES da regra nova: agente sem config.followup.
        await pool.execute("update agentesia_agentes set config = config - 'followup' where id = $1::uuid", resposta.json()["id_agente"])
        ids.append((id_ativado, resposta.json()["id_agente"]))

    visao = (await cliente.get("/api/admin/followup")).json()
    meus = {p["id_ativado"]: p for p in visao["produtos"] if p["id_ativado"] in {i for i, _ in ids}}
    assert len(meus) == 2 and all(not p["followup"]["ligado"] and not p["followup"]["configurado"] for p in meus.values())
    assert visao["totais"]["desligados"] >= 2 and all(p["escritorio"] for p in meus.values())

    assert (await cliente.post("/api/admin/followup/ligar", json={})).status_code == 400          # nunca "tudo" sem pedir
    simulado = (await cliente.post("/api/admin/followup/ligar", json={"todos_desligados": True, "simular": True})).json()
    assert simulado["simulado"] and {i for i, _ in ids} <= {p["id_ativado"] for p in simulado["ligaria"]}
    assert [await _config_fu(pool, a) for _, a in ids] == [None, None]                                # simular não muda nada

    um = (await cliente.post("/api/admin/followup/ligar", json={"ids": [ids[0][0]]})).json()
    assert [p["id_ativado"] for p in um["ligados"]] == [ids[0][0]]
    assert (await _config_fu(pool, ids[0][1]))["ativo"] is True and await _config_fu(pool, ids[1][1]) is None

    lote = (await cliente.post("/api/admin/followup/ligar", json={"todos_desligados": True})).json()
    assert ids[1][0] in {p["id_ativado"] for p in lote["ligados"]} and ids[0][0] not in {p["id_ativado"] for p in lote["ligados"]}
    assert (await _config_fu(pool, ids[1][1]))["ativo"] is True
    for _, id_agente in ids:
        assert await pool.fetchval(
            "select count(*) from agentesia_alteracoes where id_registro = $1::uuid and resumo like '%ligado com o padrão do produto (admin)%'", id_agente) == 1


@COM_BANCO
async def test_script_so_lista_sem_aplicar_e_liga_com_aplicar(ambiente, capsys):
    from scripts.ligar_followup_padrao import principal
    from tests.test_gestao import _entrar
    from tests.test_lixeira_solta_numero import _escritorio, _payload

    cliente, _simulada, email_admin, banco = ambiente
    pool = banco._pool
    await _entrar(cliente, email_admin, "senha-admin-123")
    esc, h, zapi, _o = await _escritorio(cliente, pool, f"Script {uuid.uuid4().hex[:4]}", "token-bom-555555")
    id_ativado, agentes, _ = await _produto_com_padrao(cliente, h, "Script")
    id_agente = (await cliente.post(f"/api/produtos-ativados/{id_ativado}/ativar", headers=h, json=_payload(agentes, zapi))).json()["id_agente"]
    await pool.execute("update agentesia_agentes set config = config - 'followup' where id = $1::uuid", id_agente)

    assert await principal(["--escritorio", esc, "--todos-desligados"], pool=pool) == 0
    assert "Simulação: ligaria 1" in capsys.readouterr().out and await _config_fu(pool, id_agente) is None
    assert await principal(["--escritorio", esc, "--produto", id_ativado, "--aplicar"], pool=pool) == 0
    assert "ligado: Júlia (10 min, 1 h, 24 h, 72 h)" in capsys.readouterr().out
    assert (await _config_fu(pool, id_agente))["ativo"] is True
    assert await pool.fetchval("select count(*) from agentesia_alteracoes where id_registro = $1::uuid and resumo like '%(script)%'", id_agente) == 1


# ------------------------------------------------------------------ regras de não enviar (banco local)
@pytest.fixture
async def disparo():
    """Escritório, número, agente com follow-up ligado (texto fixo, 24 h por dia) e um lead parado na etapa SDR."""
    from app.banco.postgres import RepositorioPostgres
    from app.canal.helena_conta import HelenaConta
    from app.followup import servico
    from app.modelo import ModeloFalso

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    await pool.execute("update agentesia_followups set situacao = 'cancelado' where situacao in ('pendente', 'reservado')")
    enviadas: list[dict] = []

    def helena(pedido: httpx.Request) -> httpx.Response:
        enviadas.append({"caminho": pedido.url.path, **json.loads(pedido.content or b"{}")})
        return httpx.Response(200, json={"id": f"fu-{uuid.uuid4().hex[:8]}"})

    modelo = ModeloFalso({"followup": {"mensagens": ["Oi Maria! Ficou alguma dúvida?"]}})
    disparador = servico.Disparador(pool, modelo, "https://api.helena.run", helena_por_token=lambda t, u: HelenaConta(
        t, u, httpx.AsyncClient(transport=httpx.MockTransport(helena))))

    async def montar(*, tipo_canal="nao_oficial", modo_passo="texto", horario=None, config_escritorio=None):
        segredo = await pool.fetchval("select vault.create_secret('token-fu', 'teste')")
        esc = await pool.fetchval("insert into agentesia_escritorios (nome, config) values ('Regras FU', $1::jsonb) returning id",
                                  json.dumps(config_escritorio or {}))
        await pool.execute("insert into agentesia_integracoes (id_escritorio, tipo, id_segredo_vault, situacao) values ($1, 'helena', $2, 'ok')", esc, segredo)
        canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado, id_canal_helena, tipo) values ($1, $2, $3, $4) returning id",
                                    esc, "5511" + str(uuid.uuid4().int)[:9], "ch-" + uuid.uuid4().hex[:6], tipo_canal)
        passo = {"apos_horas": 1, "modo": modo_passo, "texto": "Oi {nome}! Conseguiu ver?" if modo_passo == "texto" else ""}
        config = {"followup": {"ativo": True, "horario": horario or {"inicio": 0, "fim": 24, "dias": [0, 1, 2, 3, 4, 5, 6]},
                               "intervalo_minimo_min": 5, "passos": [passo, {"apos_horas": 24, "modo": "ia"}]}}
        agente = await pool.fetchval(
            """insert into agentesia_agentes (id_escritorio, id_canal, nome, produto, config, situacao, modo)
               values ($1, $2, 'Júlia', 'auxilio_acidente', $3::jsonb, 'ativo', 'producao') returning id""", esc, canal, json.dumps(config))
        etapas = {}
        for ordem, (codigo, tipo) in enumerate((("sdr", "conversa"), ("desqualificado", "conversa"), ("contrato_assinado", "terminal"))):
            etapas[codigo] = await pool.fetchval(
                "insert into agentesia_agente_etapas (id_agente, codigo, ordem, tipo, principal) values ($1, $2, $3, $4, $5) returning id",
                agente, codigo, ordem, tipo, ordem == 0)
        contato = await pool.fetchval("insert into agentesia_contatos (id_escritorio, nome, telefone_normalizado) values ($1, 'Maria da Silva', $2) returning id",
                                      esc, "55119" + str(uuid.uuid4().int)[:8])
        base = datetime.now(timezone.utc) - timedelta(hours=2)
        lead = await pool.fetchval(
            """insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_agente, id_etapa, id_sessao_helena, ultima_mensagem_lead_em)
               values ($1, $2, $3, $4, $5, $6, $7) returning id""", esc, contato, canal, agente, etapas["sdr"], "sessao-" + uuid.uuid4().hex[:6],
            base - timedelta(minutes=1))
        await pool.execute(
            "insert into agentesia_followups (id_escritorio, id_lead, id_agente, passo, base, agendado_para) values ($1, $2, $3, 0, $4, now() - interval '1 minute')",
            esc, lead, agente, base)
        return {"esc": esc, "agente": agente, "lead": lead, "etapas": etapas, "base": base}

    async def rodar(d):
        antes = len(enviadas)
        await disparador.rodar_uma_vez()
        linha = await pool.fetchrow("select situacao, motivo from agentesia_followups where id_lead = $1 order by criado_em limit 1", d["lead"])
        return dict(linha), enviadas[antes:]

    try:
        yield pool, montar, rodar, servico
    finally:
        await repo.fechar()


@COM_BANCO
async def test_nao_envia_para_desqualificado_contrato_assinado_ia_desligada_e_atendente(disparo):
    pool, montar, rodar, servico = disparo

    d = await montar()                                           # controle: sai
    linha, saidas = await rodar(d)
    assert linha["situacao"] == "enviado" and saidas[0]["text"] == "Oi Maria! Conseguiu ver?"

    d = await montar()
    await pool.execute("update agentesia_leads set id_etapa = $2 where id = $1", d["lead"], d["etapas"]["desqualificado"])
    assert await rodar(d) == ({"situacao": "cancelado", "motivo": "lead_desqualificado"}, [])
    assert await servico.agendar(pool, str(d["lead"]), datetime.now(timezone.utc)) is None        # nem agenda

    d = await montar()
    await pool.execute(
        """insert into agentesia_contratos (id_escritorio, id_lead, versao, dados, dados_hash, situacao, assinado_em)
           values ($1, $2, 1, '{}'::jsonb, 'h', 'assinado', now())""", d["esc"], d["lead"])
    assert await rodar(d) == ({"situacao": "cancelado", "motivo": "contrato_assinado"}, [])

    d = await montar()
    await pool.execute("update agentesia_leads set id_etapa = $2 where id = $1", d["lead"], d["etapas"]["contrato_assinado"])
    assert await rodar(d) == ({"situacao": "cancelado", "motivo": "contrato_assinado"}, [])

    d = await montar()
    await pool.execute("update agentesia_escritorios set ia_desligada = true where id = $1", d["esc"])
    assert await rodar(d) == ({"situacao": "cancelado", "motivo": "ia_desligada_no_escritorio"}, [])

    d = await montar()
    await pool.execute("update agentesia_agentes set situacao = 'pausado' where id = $1", d["agente"])
    assert await rodar(d) == ({"situacao": "cancelado", "motivo": "agente_pausado"}, [])

    d = await montar()                                           # atendente assumiu: a IA do lead fica pausada
    await pool.execute("update agentesia_leads set estado = 'pausado', motivo_estado = 'humano_assumiu' where id = $1", d["lead"])
    assert await rodar(d) == ({"situacao": "cancelado", "motivo": "lead_pausado"}, [])

    d = await montar()                                           # atendente falou depois da última resposta da IA
    await pool.execute("insert into agentesia_mensagens (id_escritorio, id_lead, autor, tipo, texto, enviada_em) values ($1, $2, 'humano', 'texto', 'deixa comigo', now() - interval '30 minutes')",
                       d["esc"], d["lead"])
    assert await rodar(d) == ({"situacao": "cancelado", "motivo": "equipe_falou"}, [])

    d = await montar()
    await pool.execute("update agentesia_leads set ultima_mensagem_lead_em = now() where id = $1", d["lead"])
    assert await rodar(d) == ({"situacao": "cancelado", "motivo": "lead_respondeu"}, [])

    d = await montar()                                           # follow-up desligado depois de agendado
    await pool.execute("update agentesia_agentes set config = jsonb_set(config, '{followup,ativo}', 'false') where id = $1", d["agente"])
    assert await rodar(d) == ({"situacao": "cancelado", "motivo": "followup_desligado"}, [])


@COM_BANCO
async def test_respeita_horario_janela_oficial_e_saldo(disparo):
    pool, montar, rodar, _servico = disparo
    from app.notificacoes import fuso

    agora_local = datetime.now(timezone.utc).astimezone(fuso())
    hoje = agora_local.weekday()
    d = await montar(horario={"inicio": 8, "fim": 20, "dias": [(hoje + 1) % 7]})     # só amanhã: hoje está fora
    linha, saidas = await rodar(d)
    assert linha == {"situacao": "pendente", "motivo": "fora_do_horario"} and saidas == []
    reagendado = await pool.fetchval("select agendado_para from agentesia_followups where id_lead = $1", d["lead"])
    assert reagendado.astimezone(fuso()).weekday() == (hoje + 1) % 7 and reagendado.astimezone(fuso()).hour == 8

    # Número oficial, lead calado há mais de 24 h e sem modelo aprovado: não manda texto livre.
    d = await montar(tipo_canal="oficial")
    await pool.execute("update agentesia_leads set ultima_mensagem_lead_em = now() - interval '30 hours' where id = $1", d["lead"])
    assert await rodar(d) == ({"situacao": "falhou", "motivo": "janela_fechada_sem_modelo"}, [])
    assert await pool.fetchval("select count(*) from agentesia_eventos where id_lead = $1 and tipo = 'followup_janela_fechada_sem_modelo'", d["lead"]) == 1

    # Dentro da janela de 24 h, o número oficial manda o texto normal.
    d = await montar(tipo_canal="oficial")
    linha, saidas = await rodar(d)
    assert linha["situacao"] == "enviado" and len(saidas) == 1

    # Saldo do mês acabou: a tentativa escrita pela IA sai com o texto de reserva, sem chamar a IA.
    d = await montar(modo_passo="ia", config_escritorio={"limite_consumo": {"mensal_usd": 1, "ao_estourar": "pausar"}})
    await pool.execute(
        """insert into agentesia_chamadas_ia (id_escritorio, papel, modelo, tokens_entrada, tokens_saida, custo_usd, duracao_ms, sucesso)
           values ($1, 'etapa', 'gpt-4.1-mini', 1, 1, 5, 1, true)""", d["esc"])
    chamadas = await pool.fetchval("select count(*) from agentesia_chamadas_ia where id_escritorio = $1", d["esc"])
    linha, saidas = await rodar(d)
    assert linha["situacao"] == "enviado" and saidas[0]["text"].startswith("Oi, Maria! Passando para saber")
    assert await pool.fetchval("select count(*) from agentesia_chamadas_ia where id_escritorio = $1", d["esc"]) == chamadas
