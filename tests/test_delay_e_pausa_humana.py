"""Delay de resposta e pausa por intervenção humana (editor do produto) cumpridos pelo motor, e os limites do
follow-up que a aba Follow-up não pode apagar.

- delay (config.espera_s, em segundos): as mensagens do lead dentro do prazo viram UM turno; cada mensagem nova
  reinicia a contagem;
- pausa (agentesia_agentes.minutos_pausa_humano, em minutos): fala do atendente (origem DEFAULT/GATEWAY) pausa a IA
  por esse tempo; vencida, a próxima mensagem do lead é respondida. "Nunca" (pausa_min = -1 -> config.pausa_sem_volta)
  pausa sem prazo: só a equipe religa. O eco da própria IA (origem API) não pausa nada;
- o editor grava delay_s/pausa_min na ativação e lê de volta os mesmos números;
- PUT /agentes/{id}/followup sem o bloco "limites" mantém os limites salvos, e a tela devolve os limites.
Os testes com banco só rodam com AGENTESIA_TESTE_PG_URL (banco local).
"""

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from app import pipeline as modulo_pipeline
from app.followup import regras
from app.gestao import produtos as gprodutos
from tests.test_gestao import ambiente  # noqa: F401  (fixture do painel com a Helena simulada)
from tests.test_pipeline import CANAL, LEAD, SIMPLES, montar, webhook

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
COM_BANCO = pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")


def _producao(**kw):
    """Agente em produção, lead que não é número de teste (número de teste responde em espera_teste_s)."""
    atendimento, repo, helena = montar(SIMPLES, modo="producao", numeros_teste=(), **kw)
    return atendimento, repo, helena, repo.agentes["canal-1"]


def _humano(texto="Oi, aqui é a Paula do escritório", quando=None):
    return webhook(texto, de=CANAL, para=LEAD, direcao="TO_HUB", origem="DEFAULT", evento="MESSAGE_SENT", quando=quando)


# ------------------------------------------------------------------ delay de resposta

async def test_delay_do_produto_e_o_tempo_de_espera_do_lead():
    atendimento, _repo, _helena, agente = _producao()
    agente.config["espera_s"] = 10
    assert (await atendimento.receber(webhook("oi")))["espera_s"] == 10.0
    for tarefa in atendimento._esperas.values():          # não espera 10 s de verdade
        tarefa.cancel()


async def test_duas_mensagens_dentro_do_delay_viram_uma_resposta_so():
    # Escala de tempo: delay 1,5 s, mensagens a 0,45 s uma da outra (equivale a 10 s e 3 s).
    atendimento, repo, helena, agente = _producao()
    agente.config["espera_s"] = 1.5
    await atendimento.receber(webhook("bom dia"))
    await asyncio.sleep(0.45)
    await atendimento.receber(webhook("caí da moto no trabalho"))
    await asyncio.sleep(1.3)                              # 1,75 s depois da 1ª: sem a 2ª, já teria respondido
    assert helena.enviadas == []                          # a 2ª mensagem reiniciou a contagem
    await atendimento.aguardar_esperas()
    assert helena.enviadas == ["Oi! Me conta o que aconteceu?"] and len(repo.turnos) == 1
    assert "[lead] bom dia\n[lead] caí da moto no trabalho" in atendimento.modelo.pedidos[0]["conteudo"]


# ------------------------------------------------------------------ pausa por intervenção humana

async def test_atendente_pausa_30_min_e_depois_a_ia_volta(monkeypatch):
    atendimento, repo, helena, agente = _producao()
    agente.minutos_pausa_humano = 30
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    assert len(helena.enviadas) == 1

    # O eco da própria IA (origem API) não pausa.
    eco = webhook(helena.enviadas[0], de=CANAL, para=LEAD, direcao="TO_HUB", origem="API", evento="MESSAGE_SENT",
                  id_msg=helena.ids[0])
    assert (await atendimento.receber(eco))["motivo"] == "eco_da_ia"
    lead = next(iter(repo.leads.values()))
    assert lead.estado == "ativo"

    inicio = datetime.now(timezone.utc)
    assert (await atendimento.receber(_humano()))["feito"] == "pausado"
    assert (lead.estado, lead.motivo_estado) == ("pausado", "humano_assumiu")
    assert abs((lead.pausado_ate - inicio - timedelta(minutes=30)).total_seconds()) < 5

    # 29 min depois: a IA continua calada.
    quando = inicio + timedelta(minutes=29)
    monkeypatch.setattr(modulo_pipeline, "agora", lambda: quando)
    await atendimento.receber(webhook("alguém aí?", quando=quando))
    await atendimento.aguardar_esperas()
    assert len(helena.enviadas) == 1 and lead.estado == "pausado"

    # 31 min depois: a pausa venceu e a IA volta a responder sozinha.
    quando = inicio + timedelta(minutes=31)
    monkeypatch.setattr(modulo_pipeline, "agora", lambda: quando)
    await atendimento.receber(webhook("ainda estão aí?", quando=quando))
    await atendimento.aguardar_esperas()
    assert len(helena.enviadas) == 2 and lead.estado == "ativo"


async def test_pausa_nunca_so_a_equipe_religa(monkeypatch):
    atendimento, repo, helena, agente = _producao()
    agente.config["pausa_sem_volta"] = True
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    inicio = datetime.now(timezone.utc)
    assert (await atendimento.receber(_humano()))["feito"] == "pausado"
    lead = next(iter(repo.leads.values()))
    assert (lead.estado, lead.motivo_estado, lead.pausado_ate) == ("pausado", "humano_assumiu", None)

    quando = inicio + timedelta(days=3)                   # nem dias depois a IA volta sozinha
    monkeypatch.setattr(modulo_pipeline, "agora", lambda: quando)
    await atendimento.receber(webhook("oi de novo", quando=quando))
    await atendimento.aguardar_esperas()
    assert len(helena.enviadas) == 1 and lead.estado == "pausado"


# ------------------------------------------------------------------ o que o editor grava

def test_ativacao_grava_delay_e_pausa_nas_unidades_do_motor():
    config = gprodutos._config_do_agente(gprodutos.Ativar(delay_s=20, pausa_min=120), {}, {}, False)
    assert config["espera_s"] == 20 and config["pausa_sem_volta"] is False
    nunca = gprodutos._config_do_agente(gprodutos.Ativar(delay_s=5, pausa_min=-1), {}, {}, False)
    assert nunca["espera_s"] == 5 and nunca["pausa_sem_volta"] is True


@COM_BANCO
async def test_editor_ativa_e_le_de_volta_delay_e_pausa(ambiente):
    from tests.test_gestao import _entrar
    from tests.test_lixeira_solta_numero import _escritorio, _payload, _produto

    cliente, _simulada, email_admin, banco = ambiente
    pool = banco._pool
    await _entrar(cliente, email_admin, "senha-admin-123")
    _esc, h, zapi, _oficial = await _escritorio(cliente, pool, "Delay e Pausa", "token-bom-222222")
    id_a, agentes = await _produto(cliente, h, "Delay")

    ativado = await cliente.post(f"/api/produtos-ativados/{id_a}/ativar", headers=h,
                                 json=_payload(agentes, zapi, delay_s=20, pausa_min=120))
    assert ativado.status_code == 200, ativado.text
    id_agente = ativado.json()["id_agente"]
    linha = await pool.fetchrow("select minutos_pausa_humano, config from agentesia_agentes where id = $1::uuid", id_agente)
    config = json.loads(linha["config"]) if isinstance(linha["config"], str) else linha["config"]
    assert (config["espera_s"], config["pausa_sem_volta"], linha["minutos_pausa_humano"]) == (20, False, 120)
    lido = (await cliente.get(f"/api/produtos-ativados/{id_a}", headers=h)).json()["agente"]
    assert (lido["delay_s"], lido["pausa_min"]) == (20, 120)

    sinc = await cliente.post(f"/api/produtos-ativados/{id_a}/sincronizar", headers=h,
                              json=_payload(agentes, zapi, delay_s=45, pausa_min=-1))
    assert sinc.status_code == 200, sinc.text
    lido = (await cliente.get(f"/api/produtos-ativados/{id_a}", headers=h)).json()["agente"]
    assert (lido["delay_s"], lido["pausa_min"]) == (45, -1)


# ------------------------------------------------------------------ limites do follow-up

LIMITES = {"max_toques_sem_resposta": 2, "oferecer_parar": True, "lead_parado_apos": 3}


def test_tela_do_followup_devolve_os_limites():
    from app.gestao.rotas import _followup_para_tela
    salvo = regras.validar({"ativo": True, "limites": LIMITES})
    tela = _followup_para_tela(salvo)
    assert tela["limites"] == LIMITES
    assert regras.validar(tela)["limites"] == LIMITES                       # a tela salva de volta sem perder
    assert "limites" not in _followup_para_tela(regras.validar({"ativo": True}))   # config antiga segue sem limites


@COM_BANCO
async def test_salvar_followup_sem_limites_mantem_os_do_agente(ambiente):
    from tests.test_gestao import _entrar
    from tests.test_lixeira_solta_numero import _escritorio, _payload, _produto

    cliente, _simulada, email_admin, banco = ambiente
    pool = banco._pool
    await _entrar(cliente, email_admin, "senha-admin-123")
    _esc, h, zapi, _oficial = await _escritorio(cliente, pool, "Limites FU", "token-bom-333333")
    id_a, agentes = await _produto(cliente, h, "Limites")
    ativado = await cliente.post(f"/api/produtos-ativados/{id_a}/ativar", headers=h, json=_payload(agentes, zapi))
    assert ativado.status_code == 200, ativado.text
    id_agente = ativado.json()["id_agente"]
    await pool.execute("""update agentesia_agentes set config = jsonb_set(config, '{followup}', $2::jsonb)
                          where id = $1::uuid""", id_agente, json.dumps(regras.validar({"ativo": True, "limites": LIMITES})))

    tela = (await cliente.get(f"/api/agentes/{id_agente}/followup", headers=h)).json()["config"]
    assert tela["limites"] == LIMITES
    sem_limites = {k: v for k, v in tela.items() if k != "limites"}           # tela antiga que não conhece o campo
    salvo = await cliente.put(f"/api/agentes/{id_agente}/followup", headers=h, json={**sem_limites, "ativo": False})
    assert salvo.status_code == 200, salvo.text
    assert salvo.json()["limites"] == LIMITES
    bruto = await pool.fetchval("select config->'followup' from agentesia_agentes where id = $1::uuid", id_agente)
    fu = json.loads(bruto) if isinstance(bruto, str) else bruto
    assert fu["ativo"] is False and fu["limites"] == LIMITES
