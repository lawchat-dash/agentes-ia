"""Contrato assinado completo (o fluxo "CONTRATO ASSINADO" do n8n) e o Resumo de contrato por agente.

Webhook doc_signed: acha o lead (token do documento, external_id, telefone, nome), ignora a assinatura do escritório,
é idempotente, faz o resumo pela IA (ou segue sem ele), nota "📄 Contrato Assinado!", card na coluna Contrato
assinado, follow-ups cancelados, mensagem ao lead, transferência e o aviso à equipe. "Já assinei" responde pelo status
real. Nada chama a ZapSign, a Helena ou a IA de verdade (MockTransport e ModeloFalso); com banco: AGENTESIA_TESTE_PG_URL.
"""

import json
import uuid

import pytest

from app.contrato import resumo as cresumo
from app.contrato import servico
from app.modelo import ModeloFalso
from tests.test_zapsign_agente import (FATOS, URL, ZapSignFalsa, _drenar, _executor, _ja_assinei, _montar, _pedir_contrato,
                                       precisa_pg)

RESUMO = ("📄 Resumo do caso:\nAcidente: Moto, fratura na perna | Ano: 2017 | Auxílio-doença: Sim, 5 meses | Limitação: manca"
          "\n\n📊 Qualidade do contrato:\nAlta — sequela permanente\n\n💰 Potencial retorno:\nAlto")
CRM = {"id_painel": "painel-1", "etapas_por_tipo": {"SDR": "col-sdr", "CONTRATO": "col-contrato",
                                                     "AGUARDANDO_ASSINATURA": "col-assinatura", "CONTRATO_ASSINADO": "col-assinado"}}


# ----------------------------------------------------------------------------- puro
def test_config_do_resumo_no_formato_novo_vale_mais_que_o_antigo():
    padrao = cresumo.configuracao({}, {}, "Auxílio-Acidente")
    assert padrao["ativo"] and padrao["no_aviso"] and padrao["modelo"] == "gpt-4.1-mini"
    assert padrao["prompt"].startswith("## AGENTE: RESUMO PÓS-CONTRATO")
    novo = {"contrato": {"resumo": {"ligado": False, "prompt": "NOVO", "modelo": "gpt-4.1"}}, "resumo_contrato": {"ativo": True, "prompt": "VELHO"}}
    vale = cresumo.configuracao(novo, {"resumo": {"prompt": "ESCRITORIO"}})
    assert (vale["ativo"], vale["prompt"], vale["modelo"], vale["origem"]) == (False, "NOVO", "gpt-4.1", "agente")
    assert cresumo.configuracao({"resumo_contrato": {"ativo": False}}, {})["ativo"] is False       # o antigo ainda vale
    assert cresumo.bloco_do_agente({"resumo_contrato": {"ativo": True, "prompt": "x"}}) == {"prompt": "x", "ligado": True}


def test_nota_caso_e_aviso_do_assinado():
    assert cresumo.nome_do_caso("auxilio_acidente", {}) == "Auxílio-Acidente"
    nota = cresumo.nota(RESUMO, "Auxílio-Acidente", ["⚠️ confira"])
    assert nota.startswith("📄 Contrato Assinado!\n\n📂 Caso: Auxílio-Acidente\n\n📄 Resumo do caso:")
    assert nota.endswith("⚠️ confira\n\nAcompanhar lead pois gerou contrato!!")
    assert cresumo.nota(None, "Auxílio-Acidente") == "📄 Contrato Assinado!\n\n📂 Caso: Auxílio-Acidente\n\nAcompanhar lead pois gerou contrato!!"
    for marcador in ("{{nome}}", "{{telefone}}", "{{link_conversa}}", "{{caso}}", "{{resumo}}"):
        assert marcador in cresumo.MODELO_AVISO_ASSINADO
    assert cresumo.MODELO_AVISO_ASSINADO.endswith("*🚀 Vamos pra cima! 💙*")


def test_assinatura_do_escritorio_e_ignorada():
    corpo = {"signer_who_signed": {"email": "Adv@Escritorio.com"}, "created_by": {"email": "adv@escritorio.com"}}
    assert servico.quem_assinou_e_o_escritorio(corpo)
    assert not servico.quem_assinou_e_o_escritorio({**corpo, "signer_who_signed": {"email": "maria@x.com"}})
    assert not servico.quem_assinou_e_o_escritorio({"signer_who_signed": {"token": "s"}})


# ----------------------------------------------------------------------------- com banco
async def _repo():
    from app.banco.postgres import RepositorioPostgres
    return await RepositorioPostgres.conectar(URL, max_conexoes=1)


async def _preparar(pool, *, config_agente=None, config_zapsign=None, aviso=True):
    esc, lead, etapas = await _montar(pool, config_agente=config_agente,
                                      config_zapsign={"guardar_pdf": False, **(config_zapsign or {})})
    await pool.execute("insert into agentesia_integracoes (id_escritorio, tipo, situacao, config) values ($1, 'crm', 'ok', $2::jsonb)",
                       esc, json.dumps(CRM))
    if aviso:
        await pool.execute(
            """insert into agentesia_notificacoes (id_escritorio, tipo_evento, nome, modelo_mensagem, destinatarios)
               values ($1, 'contrato_assinado', 'Assinado', '', $2::jsonb)""",
            esc, json.dumps([{"rotulo": "Dra. Ana", "numero": "5531999990000"}]))
    await pool.execute("insert into agentesia_mensagens (id_escritorio, id_lead, autor, texto, enviada_em) values ($1, $2, 'lead', 'caí de moto em 2017', now())", esc, lead)
    agente = await pool.fetchval("select id_agente from agentesia_leads where id = $1", lead)
    await pool.execute(
        "insert into agentesia_followups (id_escritorio, id_lead, id_agente, passo, base, agendado_para) values ($1, $2, $3, 0, now(), now() + interval '1 hour')",
        esc, lead, agente)
    return esc, lead, etapas


async def _limpar(pool, repo):
    await pool.execute("update agentesia_acoes set situacao = 'cancelada' where situacao in ('pendente', 'executando')")
    await repo.fechar()


async def _efeitos_do_assinado(pool, lead, notas, mensagens, *, com_resumo: bool):
    contrato = await pool.fetchrow("select * from agentesia_contratos where id_lead = $1 and situacao = 'assinado'", lead)
    assert contrato is not None
    linha = await pool.fetchrow("select l.estado, e.codigo from agentesia_leads l join agentesia_agente_etapas e on e.id = l.id_etapa where l.id = $1", lead)
    assert (linha["estado"], linha["codigo"]) == ("encerrado", "contrato_assinado")
    assert any(m.startswith("✅ Assinatura confirmada!") for m in mensagens)
    assert await pool.fetchval("select situacao from agentesia_followups where id_lead = $1", lead) == "cancelado"
    nota = next(n for n in notas if n.startswith("📄 Contrato Assinado!"))
    assert "📂 Caso: Auxílio-Acidente" in nota and nota.endswith("Acompanhar lead pois gerou contrato!!")
    assert ("Qualidade do contrato" in nota) == com_resumo
    assert sum(1 for n in notas if n.startswith("📄 Contrato Assinado!")) == 1
    assert await pool.fetchval(
        "select count(*) from agentesia_acoes where id_lead = $1 and tipo = 'mover_card' and dados->>'id_etapa_helena' = 'col-assinado'", lead) == 1
    aviso = await pool.fetchval("select dados->>'texto' from agentesia_acoes where id_lead = $1 and tipo = 'notificar'", lead)
    assert aviso.startswith("*📄 Contrato Assinado!*") and "👤 Cliente: Maria" in aviso and "📂 Caso: Auxílio-Acidente" in aviso
    assert aviso.endswith("*🚀 Vamos pra cima! 💙*") and ("Qualidade do contrato" in aviso) == com_resumo
    assert await pool.fetchval("select count(*) from agentesia_eventos where id_lead = $1 and tipo = 'contrato_assinado'", lead) == 1
    return contrato


@precisa_pg
async def test_webhook_pelo_documento_resumo_nota_card_followup_aviso_e_idempotente():
    repo = await _repo()
    pool = repo._pool
    try:
        esc, lead, _ = await _preparar(pool, config_agente={"contrato": {"id_equipe_assinado": "equipe-operacional"}})
        modelo = ModeloFalso({"contrato_resumo": {"resumo": RESUMO}})
        zapsign, mensagens, notas = ZapSignFalsa(), [], []
        executor = _executor(pool, zapsign, mensagens, notas, modelo=modelo)
        await _pedir_contrato(repo, esc, lead, FATOS)
        await _drenar(executor)
        token = await pool.fetchval("select id_documento_externo from agentesia_contratos where id_lead = $1", lead)
        zapsign.assinar(1)
        corpo = {"event_type": "doc_signed", "token": token, "signer_who_signed": {"token": f"lead-{zapsign.p}-1"}}
        assert await servico.receber_webhook(pool, str(esc), corpo) == "processado"
        await _drenar(executor, 20)
        contrato = await _efeitos_do_assinado(pool, lead, notas, mensagens, com_resumo=True)
        assert contrato["resumo"] == RESUMO and contrato["assinado_em"] is not None
        assert [p["sistema"][:30] for p in modelo.pedidos] == ["## AGENTE: RESUMO PÓS-CONTRATO"]
        agente = await pool.fetchval("select id_agente from agentesia_leads where id = $1", lead)
        chamada = await pool.fetchrow("select * from agentesia_chamadas_ia where id_escritorio = $1 and papel = 'contrato_resumo'", esc)
        assert chamada is not None and chamada["codigo_etapa"] == "contrato_assinado"
        if "id_agente" in chamada.keys():
            assert chamada["id_agente"] == agente
        assert await pool.fetchval(
            "select dados->>'id_equipe' from agentesia_acoes where id_lead = $1 and tipo = 'transferir'", lead) == "equipe-operacional"
        # Idempotente: o aviso do advogado e um repetido não refazem nada.
        antes = (len(notas), len(mensagens), len(modelo.pedidos))
        await servico.receber_webhook(pool, str(esc), {**corpo, "signer_who_signed": {"token": "adv-1"}})
        await _drenar(executor)
        assert (len(notas), len(mensagens), len(modelo.pedidos)) == antes
        assert await pool.fetchval("select count(*) from agentesia_acoes where id_lead = $1 and tipo = 'notificar'", lead) == 1
    finally:
        await _limpar(pool, repo)


@precisa_pg
async def test_resumo_falhando_nao_trava_e_a_nota_e_o_aviso_saem_sem_resumo():
    repo = await _repo()
    pool = repo._pool
    try:
        esc, lead, _ = await _preparar(pool)
        modelo = ModeloFalso({})                                   # a IA do resumo cai
        zapsign, mensagens, notas = ZapSignFalsa(), [], []
        executor = _executor(pool, zapsign, mensagens, notas, modelo=modelo)
        await _pedir_contrato(repo, esc, lead, FATOS)
        await _drenar(executor)
        token = await pool.fetchval("select id_documento_externo from agentesia_contratos where id_lead = $1", lead)
        zapsign.assinar(1)
        await servico.receber_webhook(pool, str(esc), {"event_type": "doc_signed", "token": token})
        for _ in range(3):
            await _drenar(executor, 20)
            await pool.execute("update agentesia_acoes set proxima_em = now() where id_lead = $1 and situacao = 'pendente' and tipo <> 'lembrar_assinatura'", lead)
        await _efeitos_do_assinado(pool, lead, notas, mensagens, com_resumo=False)
        assert await pool.fetchval("select resultado->>'resumo' from agentesia_acoes where id_lead = $1 and tipo = 'resumir_contrato'", lead) == "falhou"
        assert await pool.fetchval("select count(*) from agentesia_eventos where id_lead = $1 and tipo = 'resumo_contrato_falhou'", lead) == 1
        assert await pool.fetchval("select resumo from agentesia_contratos where id_lead = $1", lead) is None
    finally:
        await _limpar(pool, repo)


@precisa_pg
async def test_documento_fora_do_cadastro_achado_por_external_id_telefone_e_nome():
    repo = await _repo()
    pool = repo._pool
    try:
        zapsign, mensagens, notas = ZapSignFalsa(), [], []

        def documento(token, telefone="11900000000", nome="Outra Pessoa", externo=""):
            zapsign.docs[token] = {"token": token, "status": "signed", "deleted": False, "external_id": externo, "signers": [
                {"token": f"adv-{token}", "name": "Dra. Ana", "status": "signed", "email": "adv@escritorio.com", "phone_number": "11911112222"},
                {"token": f"s-{token}", "name": nome, "status": "signed", "phone_number": telefone, "signed_at": "2026-11-25T18:00:00Z"}]}
            return {"event_type": "doc_signed", "token": token, "external_id": externo, "created_by": {"email": "adv@escritorio.com"},
                    "signer_who_signed": {"token": f"s-{token}", "email": "lead@x.com", "name": nome, "phone_number": telefone},
                    "signers": zapsign.docs[token]["signers"]}

        # 1) external_id = id do lead (como o n8n gerava): a assinatura liga o documento ao lead.
        esc, lead, etapas = await _preparar(pool, aviso=False)
        executor = _executor(pool, zapsign, mensagens, notas)
        await pool.execute("update agentesia_leads set id_etapa = $2 where id = $1", lead, etapas["assinatura"])
        corpo = documento(f"ext-{zapsign.p}", externo=str(lead))
        assert await servico.receber_webhook(pool, str(esc), corpo) == "processado"
        await _drenar(executor, 20)
        assert await pool.fetchval("select situacao from agentesia_contratos where id_lead = $1 and id_documento_externo = $2", lead, corpo["token"]) == "assinado"

        # 2) telefone do signatário (sem external_id), lead na etapa de assinatura.
        esc2, lead2, etapas2 = await _preparar(pool, aviso=False)
        await pool.execute("update agentesia_leads set id_etapa = $2 where id = $1", lead2, etapas2["assinatura"])
        corpo = documento(f"tel-{zapsign.p}", telefone="(11) 98888-7777")
        assert await servico.receber_webhook(pool, str(esc2), corpo) == "processado"
        await _drenar(executor, 20)
        assert await pool.fetchval("select situacao from agentesia_contratos where id_lead = $1", lead2) == "assinado"
        assert any("ligado a este lead pelo telefone" in n for n in notas)

        # 3) nome do signatário (telefone diferente), lead com contrato reservado sem token (a geração caiu no meio).
        esc3, lead3, etapas3 = await _preparar(pool, aviso=False)
        await pool.execute("update agentesia_contatos set telefone_normalizado = '5521977770000' where id = (select id_contato from agentesia_leads where id = $1)", lead3)
        await pool.execute("update agentesia_contatos set nome = 'Joana Pereira Lima' where id = (select id_contato from agentesia_leads where id = $1)", lead3)
        reservado = await pool.fetchval(
            """insert into agentesia_contratos (id_escritorio, id_lead, versao, dados, dados_hash, situacao)
               values ($1, $2, 1, '{"nome": "Joana Pereira Lima"}'::jsonb, 'h', 'reservado') returning id""", esc3, lead3)
        corpo = documento(f"nome-{zapsign.p}", nome="JOANA PEREIRA LIMA")
        assert await servico.receber_webhook(pool, str(esc3), corpo) == "processado"
        await _drenar(executor, 20)
        linha = await pool.fetchrow("select id, situacao, id_documento_externo from agentesia_contratos where id_lead = $1", lead3)
        assert (linha["id"], linha["situacao"], linha["id_documento_externo"]) == (reservado, "assinado", corpo["token"])

        # Documento de ninguém: ignorado; assinatura do escritório: ignorada; lead já assinado: nada a fazer.
        assert await servico.receber_webhook(pool, str(esc3), documento(f"ninguem-{zapsign.p}")) == "ignorado:documento_desconhecido"
        do_escritorio = {**documento(f"adv-{zapsign.p}"), "signer_who_signed": {"token": "a", "email": "adv@escritorio.com"}}
        assert await servico.receber_webhook(pool, str(esc3), do_escritorio) == "ignorado:escritorio_assinou"
        de_novo = documento(f"nome2-{zapsign.p}", nome="Joana Pereira Lima")
        assert await servico.receber_webhook(pool, str(esc3), {**de_novo, "external_id": str(lead3)}) == "ignorado:documento_desconhecido"
    finally:
        await _limpar(pool, repo)


@precisa_pg
async def test_ja_assinei_conforme_o_status_real():
    repo = await _repo()
    pool = repo._pool
    try:
        esc, lead, _ = await _preparar(pool, aviso=False)
        zapsign, mensagens, notas = ZapSignFalsa(), [], []
        executor = _executor(pool, zapsign, mensagens, notas)
        await _pedir_contrato(repo, esc, lead, FATOS)
        await _drenar(executor)
        # Nunca abriu: manda o link de novo.
        await _ja_assinei(repo, esc, lead)
        await _drenar(executor)
        assert mensagens[-1].startswith("Ainda não consta a sua assinatura") and "verificar/lead-1" in mensagens[-1]
        # Abriu e não concluiu: pergunta onde travou.
        zapsign.lead(1).update(status="link-opened", times_viewed=2)
        await _ja_assinei(repo, esc, lead)
        await _drenar(executor)
        assert mensagens[-1].startswith("Conferi aqui e vi que você abriu o contrato")
        # Assinado: segue o fluxo do contrato assinado (nota com a confirmação pela verificação).
        zapsign.assinar(1)
        await _ja_assinei(repo, esc, lead)
        await _drenar(executor, 20)
        assert await pool.fetchval("select situacao from agentesia_contratos where id_lead = $1", lead) == "assinado"
        assert any(n.startswith("📄 Contrato Assinado!") and "confirmada pela verificação" in n for n in notas)

        # Sem contrato nosso para conferir: desliga a IA, nota para a equipe e etiqueta "🤖 IA Desativada".
        esc2, lead2, _ = await _preparar(pool, aviso=False)
        await _ja_assinei(repo, esc2, lead2)
        await _drenar(executor, 20)
        assert (await pool.fetchrow("select estado from agentesia_leads where id = $1", lead2))["estado"] == "pausado"
        assert any(n == "Lead disse que assinou o contrato, por favor verifique dentro do ZapSign se o contrato dele está assinado" for n in notas)
        assert await pool.fetchval(
            "select count(*) from agentesia_acoes where id_lead = $1 and tipo = 'etiquetar' and dados->'adicionar' ? '🤖 IA Desativada'", lead2) == 1
    finally:
        await _limpar(pool, repo)


# ----------------------------------------------------------------------------- rotas do painel
if URL:
    from tests.test_gestao import _entrar, ambiente  # noqa: F401  (fixture do painel com Postgres local)


@precisa_pg
async def test_rotas_do_resumo_de_contrato_por_agente(ambiente):
    cliente, _simulada, email_admin, banco = ambiente
    from app.gestao.rotas_resumo_contrato import api as api_resumo
    cliente._transport.app.include_router(api_resumo)
    await _entrar(cliente, email_admin, "senha-admin-123")
    escritorio = (await cliente.post("/api/admin/escritorios", json={
        "nome": "Resumo Ltda", "id_conta_helena": str(uuid.uuid4()), "token_helena": "token-bom-123456"})).json()["escritorio"]
    h = {"x-escritorio": escritorio["id"]}
    pool = banco._pool
    canal = await pool.fetchval(
        "insert into agentesia_canais (id_escritorio, numero_normalizado, id_canal_helena) values ($1::uuid, $2, $3) returning id",
        escritorio["id"], "55119" + str(uuid.uuid4().int)[:8], "ch-" + uuid.uuid4().hex[:10])
    agente = str(await pool.fetchval(
        """insert into agentesia_agentes (id_escritorio, id_canal, nome, produto, situacao, config)
           values ($1::uuid, $2, 'Júlia', 'auxilio_acidente', 'ativo', '{"contrato": {"outra": 1}}'::jsonb) returning id""",
        escritorio["id"], canal))
    lista = (await cliente.get("/api/resumo-contrato/agentes", headers=h)).json()
    assert [(a["nome"], a["ligado"], a["caso"]) for a in lista] == [("Júlia", True, "Auxílio-Acidente")]
    visao = (await cliente.get(f"/api/agentes/{agente}/contrato/resumo", headers=h)).json()
    assert visao["agente"]["nome"] == "Júlia" and visao["config"]["prompt"] == "" and visao["config"]["modelo"] == "gpt-4.1-mini"
    assert visao["prompt_padrao"].startswith("## AGENTE: RESUMO PÓS-CONTRATO") and visao["consumo"]["chamadas"] == 0
    salvo = (await cliente.put(f"/api/agentes/{agente}/contrato/resumo", headers=h, json={
        "ligado": False, "prompt": "Resuma em 3 linhas.", "modelo": "gpt-4.1", "no_aviso": False, "id_equipe_assinado": "eq-1"})).json()
    assert (salvo["config"]["ligado"], salvo["config"]["prompt"], salvo["config"]["modelo"], salvo["vale"]["origem"]) == (False, "Resuma em 3 linhas.", "gpt-4.1", "agente")
    config = json.loads(await pool.fetchval("select config::text from agentesia_agentes where id = $1::uuid", agente))
    assert config["contrato"] == {"outra": 1, "id_equipe_assinado": "eq-1",
                                  "resumo": {"ligado": False, "prompt": "Resuma em 3 linhas.", "modelo": "gpt-4.1", "no_aviso": False}}
    # Prompt igual ao padrão: guarda vazio (segue o padrão).
    await cliente.put(f"/api/agentes/{agente}/contrato/resumo", headers=h, json={"ligado": True, "prompt": visao["prompt_padrao"]})
    assert (await cliente.get(f"/api/agentes/{agente}/contrato/resumo", headers=h)).json()["vale"]["origem"] == "padrao"
    assert (await cliente.put(f"/api/agentes/{agente}/contrato/resumo", headers=h, json={"modelo": "o3"})).status_code == 400
    assert (await cliente.get(f"/api/agentes/{uuid.uuid4()}/contrato/resumo", headers=h)).status_code == 404
