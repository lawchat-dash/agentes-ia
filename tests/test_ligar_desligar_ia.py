"""Desativar e reativar a IA (docs/LIGAR_DESLIGAR_IA.md), ponta a ponta: painel, etiqueta e botão da Helena, desativação
com prazo vencendo, reativar sem boas-vindas, sem laço etiqueta <-> evento, produto e escritório desligados e permissões.

Usa a bateria ponta a ponta de tests/test_e2e_helena.py: FastAPI de verdade, Postgres local (PGlite, porta
AGENTESIA_E2E_PORTA), IA falsa e HELENA FALSA. Nada sai para a rede.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.gestao import seguranca
from tests.test_e2e_helena import Cenario, _linha_propria, banco_local, e2e, responde  # noqa: F401 (fixtures)

ETIQUETA = "🤖 IA Desativada"
RAIZ = Path(__file__).resolve().parent.parent


async def _entrar(e2e: Cenario, papel: str) -> str:
    """Usuário do escritório (gestor ou atendente) logado no painel. Devolve o id dele."""
    email = f"{papel}-{uuid.uuid4().hex[:6]}@exemplo.test"
    id_usuario = await e2e.pool.fetchval(
        """insert into agentesia_usuarios (email, nome, senha_hash, papel, id_escritorio, trocar_senha)
           values ($1, $2, $3, $4, $5::uuid, false) returning id""",
        email, papel.title() + " Teste", seguranca.gerar_hash("senha-de-teste-123"), papel, e2e.ids["escritorio"])
    e2e.http.cookies.clear()
    resposta = await e2e.http.post("/api/entrar", json={"email": email, "senha": "senha-de-teste-123"})
    assert resposta.status_code == 200, resposta.text
    return str(id_usuario)


def _evento_etiqueta(e2e: Cenario, com_etiqueta: bool) -> dict:
    tags = [{"name": "📞 SDR"}] + ([{"name": ETIQUETA}] if com_etiqueta else [])
    return {"eventType": "CONTACT_TAG_UPDATE", "date": datetime.now(timezone.utc).isoformat(),
            "content": {"id": e2e.helena.id_contato, "phonenumber": "+" + e2e.telefone, "tags": tags}}


async def _painel(e2e: Cenario, acao: str, minutos: int | None = None):
    lead = await e2e.lead()
    corpo = {"acao": acao} if minutos is None else {"acao": acao, "minutos": minutos}
    return await e2e.http.post(f"/api/conversas/{lead['id']}/ia", json=corpo)


async def _vencer_prazo(e2e: Cenario) -> None:
    """O relógio anda: o prazo da desativação passou (e a resposta guardada também)."""
    lead = await e2e.lead()
    await e2e.pool.execute(
        """update agentesia_leads set pausado_ate = now() - interval '1 second',
                  responder_apos = case when responder_apos is null then null else now() - interval '1 second' end
           where id = $1""", lead["id"])


async def _followup_pendente(e2e: Cenario, id_lead, daqui_min: int = 60) -> None:
    """Um follow-up pendente (só um por lead: o que a IA agendou sai antes)."""
    await e2e.pool.execute("update agentesia_followups set situacao = 'cancelado' where id_lead = $1 and situacao in "
                           "('pendente', 'reservado')", id_lead)
    await e2e.pool.execute(
        """insert into agentesia_followups (id_escritorio, id_lead, passo, base, agendado_para)
           values ($1::uuid, $2, 0, now() - interval '2 hours', now() + make_interval(mins => $3))""", e2e.ids["escritorio"], id_lead, daqui_min)


async def _alteracoes(e2e: Cenario, acao: str) -> list[dict]:
    return [dict(x) for x in await e2e.pool.fetch(
        "select * from agentesia_alteracoes where id_escritorio = $1::uuid and acao = $2 order by criado_em",
        e2e.ids["escritorio"], acao)]


# ============================================================================ painel
async def test_painel_desativa_e_reativa_com_o_mesmo_efeito_da_etiqueta_e_sem_boas_vindas(e2e: Cenario):
    await e2e.pool.execute(
        """update agentesia_agentes set config = jsonb_set(config, '{catalogo,papeis,sdr,boas_vindas}',
                  '"Oi! Sou a Ana, do Sousa e Costa."'::jsonb) where id = $1::uuid""", e2e.ids["agente"])
    outros = [p for k, p in e2e.prompts.items() if k != "closer"]
    linha_closer = _linha_propria(e2e.prompts["closer"], outros)
    e2e.ia.etapa = lambda s, _c: responde("Sou do comercial." if linha_closer in s else "Oi! Como foi o acidente?")
    await e2e.chega(e2e.do_lead("oi"))
    assert "Mensagem de boas-vindas" in e2e.pedidos("etapa")[-1]["conteudo"]       # primeira resposta: boas-vindas
    await e2e.por_na_etapa("closer")
    await e2e.chega(e2e.do_lead("e aí?"))
    lead = await e2e.lead()
    await _followup_pendente(e2e, lead["id"])


    # Atendente desativa "até eu religar" pelo painel.
    id_atendente = await _entrar(e2e, "atendente")
    resposta = await _painel(e2e, "desativar", 0)
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert (corpo["estado"], corpo["motivo_estado"], corpo["pausado_ate"]) == ("pausado", "desativada_pela_equipe", None)
    assert corpo["codigo"].startswith("DES-")
    assert await e2e.pool.fetchval("select situacao from agentesia_followups where id_lead = $1", lead["id"]) == "cancelado"
    await e2e.rodar_fila()
    assert ("InsertIfNotExists", (ETIQUETA,)) in e2e.helena.etiquetas()
    assert any(n.startswith("🤖 IA desativada nesta conversa") and corpo["codigo"] in n for n in e2e.helena.notas())
    desligou = (await _alteracoes(e2e, "desligou_ia"))[-1]
    assert str(desligou["id_usuario"]) == id_atendente and str(desligou["id_registro"]) == str(lead["id"])
    # O painel mostra o estado (a tela traduz: "IA desligada pela equipe").
    lista = (await e2e.http.get("/api/conversas")).json()
    item = next(c for c in lista if c["id"] == str(lead["id"]))
    assert (item["estado"], item["motivo_estado"], item["pausado_ate"]) == ("pausado", "desativada_pela_equipe", None)

    # Eco da etiqueta que a própria LawChat pôs: não mexe em nada nem deixa nota nova.
    notas_antes = len(e2e.helena.notas())
    assert (await e2e.chega(_evento_etiqueta(e2e, True)))["alterados"] == 0
    textos = e2e.helena.textos()
    await e2e.chega(e2e.do_lead("alô?"))
    assert e2e.helena.textos() == textos                                     # IA calada
    assert len(e2e.helena.notas()) == notas_antes

    # Reativa: nota ATV, etiqueta tirada, histórico com quem fez.
    resposta = await _painel(e2e, "reativar")
    assert resposta.json()["estado"] == "ativo" and resposta.json()["codigo"].startswith("ATV-")
    await e2e.rodar_fila()
    assert ("DeleteIfExists", (ETIQUETA,)) in e2e.helena.etiquetas()
    assert any(n.startswith("🤖 IA religada nesta conversa") and resposta.json()["codigo"] in n for n in e2e.helena.notas())
    assert str((await _alteracoes(e2e, "religou_ia"))[-1]["id_usuario"]) == id_atendente
    assert (await e2e.chega(_evento_etiqueta(e2e, False)))["alterados"] == 0   # eco da etiqueta tirada

    # Retoma da etapa em que estava (closer), sem repetir as boas-vindas.
    await e2e.chega(e2e.do_lead("voltei, e agora?"))
    assert e2e.helena.textos()[-1] == "Sou do comercial."
    assert (await e2e.lead())["etapa"] == "closer"
    ultimo = e2e.pedidos("etapa")[-1]
    assert linha_closer in ultimo["sistema"] and "Mensagem de boas-vindas" not in ultimo["conteudo"]


async def test_desativar_e_reativar_rapido_nao_entra_em_laco_com_os_ecos_da_etiqueta(e2e: Cenario):
    e2e.ia.etapa = lambda _s, _c: responde("Oi!")
    await e2e.chega(e2e.do_lead("oi"))
    await _entrar(e2e, "gestor")
    assert (await _painel(e2e, "desativar", 0)).status_code == 200
    assert (await _painel(e2e, "reativar")).status_code == 200
    await e2e.rodar_fila()
    notas = len(e2e.helena.notas())
    # A Helena devolve os dois eventos (pôs e tirou), um depois do outro, até repetidos: nada muda.
    for com in (True, False, True, False):
        assert (await e2e.chega(_evento_etiqueta(e2e, com)))["alterados"] == 0
    lead = await e2e.lead()
    assert (lead["estado"], lead["motivo_estado"]) == ("ativo", None)
    assert len(e2e.helena.notas()) == notas
    assert len(await _alteracoes(e2e, "desligou_ia")) == 1 and len(await _alteracoes(e2e, "religou_ia")) == 1


async def test_etiqueta_posta_pela_equipe_na_helena_desliga_e_tirada_religa(e2e: Cenario):
    e2e.ia.etapa = lambda _s, _c: responde("Oi!")
    await e2e.chega(e2e.do_lead("oi"))
    lead = await e2e.lead()
    await _followup_pendente(e2e, lead["id"])

    assert (await e2e.chega(_evento_etiqueta(e2e, True)))["alterados"] == 1
    assert (await e2e.lead())["motivo_estado"] == "desativada_pela_equipe"
    assert await e2e.pool.fetchval("select situacao from agentesia_followups where id_lead = $1", lead["id"]) == "cancelado"
    assert any(n.startswith("🤖 IA desativada nesta conversa") and "DES-" in n for n in e2e.helena.notas())
    # Quem veio pela etiqueta já mexeu nela: a LawChat não põe de novo (senão viraria laço).
    assert not await e2e.pool.fetchval(
        "select count(*) from agentesia_acoes where id_lead = $1 and tipo = 'etiquetar' and chave_unica like '%:ia:%'", lead["id"])
    assert (await e2e.chega(_evento_etiqueta(e2e, False)))["alterados"] == 1
    assert (await e2e.lead())["estado"] == "ativo"
    assert any(n.startswith("🤖 IA religada nesta conversa") and "ATV-" in n for n in e2e.helena.notas())
    assert [a["depois"] for a in await _alteracoes(e2e, "religou_ia")]


# ============================================================================ botão da Helena (webhook) e prazo
async def test_botao_com_prazo_guarda_a_mensagem_e_responde_quando_o_prazo_vence(e2e: Cenario):
    from app.canal.webhook import segredo_do_escritorio

    e2e.ia.etapa = lambda _s, _c: responde("Oi!")
    await e2e.chega(e2e.do_lead("oi"))
    esc = e2e.ids["escritorio"]
    resposta = await e2e.http.post(f"/webhook/helena/{esc}/ia?segredo={segredo_do_escritorio(esc)}",
                                   json={"acao": "desligar", "sessionId": e2e.sessao, "minutes": 30})
    assert resposta.status_code == 200 and resposta.json()["alterados"] == 1 and resposta.json()["pausado_ate"]
    await e2e.rodar_fila()
    assert ("InsertIfNotExists", (ETIQUETA,)) in e2e.helena.etiquetas()          # prazo também põe a etiqueta
    assert any("IA desativada nesta conversa até" in n for n in e2e.helena.notas())
    lead = await e2e.lead()
    assert lead["motivo_estado"] == "desativada_pela_equipe" and lead["pausado_ate"]

    # O lead escreve no meio tempo: nada sai, a mensagem fica guardada para quando o prazo acabar.
    e2e.ia.etapa = lambda _s, _c: responde("Desculpe a demora! Me conta mais?")
    await e2e.chega(e2e.do_lead("tem alguém aí?"))
    assert e2e.helena.textos(e2e.sessao) == ["Oi!"]
    lead = await e2e.lead()
    assert lead["responder_apos"] == lead["pausado_ate"]
    assert await e2e.pool.fetchval(
        "select count(*) from agentesia_mensagens where id_lead = $1 and autor = 'lead' and id_turno is null", lead["id"]) == 1

    # Prazo vence: a IA volta sozinha (nota ATV, etiqueta tirada) e responde o que estava esperando.
    await _vencer_prazo(e2e)
    await e2e.atendimento.retomar_pendentes()
    await e2e.esperar()
    await e2e.rodar_fila()
    lead = await e2e.lead()
    assert (lead["estado"], lead["motivo_estado"], lead["pausado_ate"]) == ("ativo", None, None)
    assert e2e.helena.textos(e2e.sessao) == ["Oi!", "Desculpe a demora! Me conta mais?"]
    assert any(n.startswith("🤖 IA religada sozinha") and "ATV-" in n for n in e2e.helena.notas())
    assert ("DeleteIfExists", (ETIQUETA,)) in e2e.helena.etiquetas()
    assert (await _alteracoes(e2e, "religou_ia"))[-1]["depois"]
    # O eco da etiqueta tirada não muda nada.
    assert (await e2e.chega(_evento_etiqueta(e2e, False)))["alterados"] == 0


async def test_prazo_vence_sem_mensagem_esperando_e_a_ia_nao_manda_nada(e2e: Cenario):
    e2e.ia.etapa = lambda _s, _c: responde("Oi!")
    await e2e.chega(e2e.do_lead("oi"))
    await _entrar(e2e, "atendente")
    corpo = (await _painel(e2e, "desativar", 120)).json()
    assert corpo["estado"] == "pausado" and corpo["pausado_ate"]
    # A tela mostra "IA desligada até HH:MM": o horário vem da API.
    detalhe = (await e2e.http.get(f"/api/conversas/{(await e2e.lead())['id']}")).json()
    assert detalhe["pausado_ate"] and detalhe["motivo_estado"] == "desativada_pela_equipe"
    await _vencer_prazo(e2e)
    await e2e.atendimento.retomar_pendentes()
    await e2e.esperar()
    await e2e.rodar_fila()
    assert (await e2e.lead())["estado"] == "ativo"
    assert e2e.helena.textos(e2e.sessao) == ["Oi!"]                            # volta calada
    assert any(n.startswith("🤖 IA religada sozinha") for n in e2e.helena.notas())


async def test_prazo_vence_mas_a_equipe_ja_respondeu_e_a_ia_fica_calada(e2e: Cenario):
    e2e.ia.etapa = lambda _s, _c: responde("Oi!")
    await e2e.chega(e2e.do_lead("oi"))
    await _entrar(e2e, "gestor")
    await _painel(e2e, "desativar", 30)
    await e2e.chega(e2e.do_lead("qual o valor?"))
    await e2e.chega(e2e.do_atendente("Oi! O valor é combinado na consulta."))
    lead = await e2e.lead()
    assert lead["motivo_estado"] == "desativada_pela_equipe"                  # a fala não encurtou a desativação
    await _vencer_prazo(e2e)
    await e2e.atendimento.retomar_pendentes()
    await e2e.esperar()
    assert e2e.helena.textos(e2e.sessao) == ["Oi!"]
    assert (await e2e.turnos())[-1]["motivo"] == "equipe_respondeu"


async def test_atendente_falando_nao_encurta_a_desativacao_de_24_horas(e2e: Cenario):
    e2e.ia.etapa = lambda _s, _c: responde("Oi!")
    await e2e.chega(e2e.do_lead("oi"))
    await _entrar(e2e, "atendente")
    ate = (await _painel(e2e, "desativar", 1440)).json()["pausado_ate"]
    assert (await e2e.chega(e2e.do_atendente("Pode deixar que eu sigo daqui.")))["feito"] == "pausado"
    lead = await e2e.lead()
    assert (lead["motivo_estado"], lead["pausado_ate"].isoformat()) == ("desativada_pela_equipe", ate)


async def test_atendente_assumiu_aparece_como_pausa_automatica(e2e: Cenario):
    e2e.ia.etapa = lambda _s, _c: responde("Oi!")
    await e2e.chega(e2e.do_lead("oi"))
    await e2e.chega(e2e.do_atendente("Oi, sou a Paula."))
    await _entrar(e2e, "atendente")
    id_lead = str((await e2e.lead())["id"])
    item = next(c for c in (await e2e.http.get("/api/conversas")).json() if c["id"] == id_lead)
    assert (item["estado"], item["motivo_estado"]) == ("pausado", "humano_assumiu") and item["pausado_ate"]
    # Reativar pelo painel tira a pausa automática na hora.
    assert (await _painel(e2e, "reativar")).json()["estado"] == "ativo"


# ============================================================================ produto e escritório
async def test_produto_pausado_e_escritorio_desligado_lead_nao_recebe_nada_e_sem_rajada_ao_religar(e2e: Cenario):
    from app.followup.servico import Disparador

    e2e.ia.etapa = lambda _s, _c: responde("Oi!")
    await e2e.chega(e2e.do_lead("oi"))
    lead = await e2e.lead()
    id_gestor = await _entrar(e2e, "gestor")
    # Gestor pausa o agente (produto): o painel mostra e o lead não recebe nada.
    pausa = await e2e.http.post(f"/api/agentes/{e2e.ids['agente']}/ativacao", json={"situacao": "pausado"})
    assert pausa.status_code == 200, pausa.text
    item = next(c for c in (await e2e.http.get("/api/conversas")).json() if c["id"] == str(lead["id"]))
    assert item["situacao_agente"] == "pausado"
    await e2e.chega(e2e.do_lead("oi? alguém?"))
    await e2e.chega(e2e.do_lead("??"))
    assert e2e.helena.textos(e2e.sessao) == ["Oi!"]
    assert any(n.startswith("⏸️ A IA não respondeu: o agente ") and "está pausado" in n for n in e2e.helena.notas())
    # Follow-up (ligado no agente) que vence com o agente pausado é cancelado, não fica guardado para depois.
    await e2e.pool.execute("""update agentesia_agentes set config = jsonb_set(config, '{followup}', '{"ativo": true}'::jsonb)
                              where id = $1::uuid""", e2e.ids["agente"])
    await e2e.pool.execute("update agentesia_followups set situacao = 'cancelado' where situacao in ('pendente', 'reservado')")
    await e2e.pool.execute(
        """insert into agentesia_followups (id_escritorio, id_lead, passo, base, agendado_para)
           values ($1::uuid, $2, 0, now() - interval '2 hours', now() - interval '1 minute')""", e2e.ids["escritorio"], lead["id"])
    await Disparador(e2e.pool, e2e.atendimento.modelo, "https://api.helena.falsa").rodar_uma_vez()
    assert tuple(await e2e.pool.fetchrow(
        "select situacao, motivo from agentesia_followups where id_lead = $1 order by criado_em desc limit 1", lead["id"])) \
        == ("cancelado", "agente_pausado")
    # Religar o agente: nada do que chegou na pausa dispara de uma vez.
    await e2e.pool.execute("update agentesia_agentes set situacao = 'ativo' where id = $1::uuid", e2e.ids["agente"])
    await e2e.atendimento.retomar_pendentes()
    await e2e.esperar()
    assert e2e.helena.textos(e2e.sessao) == ["Oi!"]

    # Escritório inteiro desligado (Configurações): mesmo comportamento, com histórico de quem desligou.
    desligar = await e2e.http.patch("/api/escritorio", json={"ia_desligada": True})
    assert desligar.status_code == 200
    assert str((await _alteracoes(e2e, "desligou_ia"))[-1]["id_usuario"]) == id_gestor
    item = next(c for c in (await e2e.http.get("/api/conversas")).json() if c["id"] == str(lead["id"]))
    assert item["ia_desligada_escritorio"] is True
    await e2e.chega(e2e.do_lead("e agora?"))
    assert e2e.helena.textos(e2e.sessao) == ["Oi!"]
    assert any(n.startswith("⏸️ A IA não respondeu: a IA está desligada neste escritório") for n in e2e.helena.notas())
    assert (await e2e.http.patch("/api/escritorio", json={"ia_desligada": False})).status_code == 200
    await e2e.atendimento.retomar_pendentes()
    await e2e.esperar()
    assert e2e.helena.textos(e2e.sessao) == ["Oi!"]                            # sem rajada ao religar
    e2e.ia.etapa = lambda _s, _c: responde("Voltei! Me conta?")
    await e2e.chega(e2e.do_lead("oi de novo"))
    assert e2e.helena.textos(e2e.sessao) == ["Oi!", "Voltei! Me conta?"]       # só a mensagem nova é respondida


# ============================================================================ permissões
async def test_quem_pode_desligar_e_religar(e2e: Cenario):
    e2e.ia.etapa = lambda _s, _c: responde("Oi!")
    await e2e.chega(e2e.do_lead("oi"))
    # Atendente: conversa sim; produto e escritório não.
    await _entrar(e2e, "atendente")
    assert (await _painel(e2e, "desativar", 30)).status_code == 200
    assert (await _painel(e2e, "reativar")).status_code == 200
    assert (await e2e.http.patch("/api/escritorio", json={"ia_desligada": True})).status_code == 403
    assert (await e2e.http.post(f"/api/agentes/{e2e.ids['agente']}/ativacao", json={"situacao": "pausado"})).status_code == 403
    assert (await e2e.http.post(f"/api/produtos-ativados/{uuid.uuid4()}/status", json={"status": "pausado"})).status_code == 403
    assert (await e2e.pool.fetchval("select ia_desligada from agentesia_escritorios where id = $1::uuid", e2e.ids["escritorio"])) is False
    # Gestor: tudo.
    await _entrar(e2e, "gestor")
    assert (await _painel(e2e, "desativar", 0)).status_code == 200
    assert (await _painel(e2e, "reativar")).status_code == 200
    assert (await e2e.http.post(f"/api/agentes/{e2e.ids['agente']}/ativacao", json={"situacao": "pausado"})).status_code == 200
    # Sem login: nada.
    e2e.http.cookies.clear()
    assert (await _painel(e2e, "desativar", 0)).status_code == 401
    # Conversa de outro escritório não existe para quem é deste.
    await _entrar(e2e, "gestor")
    assert (await e2e.http.post(f"/api/conversas/{uuid.uuid4()}/ia", json={"acao": "desativar"})).status_code == 404

