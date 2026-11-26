"""Ferramentas › Follow-up (visão, histórico, dashboard) e Avisos no WhatsApp (conta + catálogo dos avisos reais).

Backend: app/gestao/rotas_followup.py (/followup/*) e app/gestao/rotas_avisos.py (/avisos*). Os testes com banco só
rodam com AGENTESIA_TESTE_PG_URL (ver tests/test_postgres.py). Nenhuma IA é chamada.
"""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import automacoes
from app.cerebro import auxilio_acidente, sinais
from app.gestao import rotas_avisos, rotas_followup
from tests.test_gestao import _entrar, ambiente  # noqa: F401  (fixture)

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
RAIZ = Path(__file__).resolve().parent.parent
pg = pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")


# ------------------------------------------------------------------ sem banco
def test_motivos_em_portugues_e_config_torta_nao_quebra():
    assert rotas_followup.motivo_legivel("lead_respondeu") == "o lead respondeu antes"
    assert rotas_followup.motivo_legivel("envio: canal caiu") == "falha no envio: canal caiu"
    assert rotas_followup.motivo_legivel("algo_novo") == "algo novo"
    assert rotas_followup.motivo_legivel(None) is None
    assert rotas_followup.resumo_da_config({})["ligado"] is False
    torta = rotas_followup.resumo_da_config({"followup": {"ativo": True, "horario": {"inicio": "x"}}})
    assert torta["ligado"] is False and torta["configurado"] is True
    certo = rotas_followup.resumo_da_config({"followup": {"ativo": True, "passos": [{"apos_horas": 24}, {"apos_horas": 1}]}})
    assert certo["ligado"] is True and certo["passos"] == [1.0, 24.0]


def test_catalogo_de_avisos_so_tem_gatilhos_reais():
    chaves = [i["chave"] for i in rotas_avisos.CATALOGO]
    assert len(chaves) == len(set(chaves))
    tipos = [c for i in rotas_avisos.CATALOGO for c in i["chaves"]]
    assert len(tipos) == len(set(tipos)), "o mesmo tipo de evento em dois avisos vira aviso duplicado"
    etapas = set(auxilio_acidente.ETAPAS) | set(auxilio_acidente.ETAPAS_CONTRATO) | {"closer", "contratos", "assinatura", "desqualificado"}
    for tipo in tipos:
        prefixo, _, codigo = tipo.partition(":")
        if prefixo == "sinal":
            assert codigo in sinais.SINAIS, tipo
        elif prefixo == "etapa":
            assert codigo in etapas, tipo
        elif prefixo == "intencao":
            assert codigo in auxilio_acidente.INTENCOES, tipo
        else:
            assert tipo in automacoes.GATILHOS_FIXOS, tipo
    # Nada de genérico/duplicado: "sinal" (qualquer sinal), contrato gerado e a etapa do contrato assinado ficam de fora.
    assert not {"sinal", "contrato_gerado", "etapa:contrato_assinado"} & set(tipos)
    assert {i["grupo"] for i in rotas_avisos.CATALOGO} == {g for g, _ in rotas_avisos.GRUPOS}
    for item in rotas_avisos.CATALOGO:
        assert "Helena" not in item["nome"] + item["descricao"] + item["modelo"]


def test_rotas_e_telas_registradas():
    from app.servidor import criar_app, rotas_montadas
    caminhos = rotas_montadas(criar_app("painel"))
    assert {"/api/followup/visao", "/api/followup/historico", "/api/followup/dashboard",
            "/api/avisos", "/api/avisos/conta", "/api/avisos/ligados", "/api/avisos/item/{chave}"} <= caminhos
    rotas = (RAIZ / "painel" / "src" / "main.tsx").read_text(encoding="utf-8")
    for caminho in ('path="/ferramentas/followup"', 'path="/ferramentas/midia"', 'path="/avisos"'):
        assert caminho in rotas
    ferramentas = (RAIZ / "painel" / "src" / "telas" / "Ferramentas.tsx").read_text(encoding="utf-8")
    assert "MediaLibrary" not in ferramentas and "EscolherAgenteFollowup" not in ferramentas   # sem pop-up duplicado
    for tela in ("Followup.tsx", "Avisos.tsx", "BibliotecaMidia.tsx", "AgenteFollowup.tsx"):
        assert "Helena" not in (RAIZ / "painel" / "src" / "telas" / tela).read_text(encoding="utf-8")


# ------------------------------------------------------------------ com banco
async def _conta(cliente, nome):
    escritorio = (await cliente.post("/api/admin/escritorios", json={
        "nome": nome, "id_conta_helena": str(uuid.uuid4()), "token_helena": f"token-bom-{uuid.uuid4().hex[:8]}"})).json()["escritorio"]
    h = {"x-escritorio": escritorio["id"]}
    canais = (await cliente.get("/api/integracoes", headers=h)).json()["canais"]
    comum = next(c for c in canais if c["tipo"] != "oficial")
    agente = (await cliente.post("/api/agentes", headers=h, json={"nome": "Júlia", "id_canal": comum["id"]})).json()
    return escritorio["id"], h, canais, agente


@pg
async def test_followup_visao_historico_e_dashboard(ambiente):  # noqa: F811
    cliente, _simulada, email_admin, banco = ambiente
    cliente._transport.app.include_router(rotas_followup.api)
    pool = banco._pool
    await _entrar(cliente, email_admin, "senha-admin-123")
    esc, h, canais, agente = await _conta(cliente, f"Follow {uuid.uuid4().hex[:5]}")
    comum = next(c for c in canais if c["tipo"] != "oficial")

    async def lead(nome, tel):
        contato = await pool.fetchval("insert into agentesia_contatos (id_escritorio, nome, telefone_normalizado) values ($1::uuid, $2, $3) returning id",
                                      esc, nome, tel)
        return await pool.fetchval("""insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_agente, estado)
                                      values ($1::uuid, $2, $3::uuid, $4::uuid, 'ativo') returning id""", esc, contato, comum["id"], agente["id"])

    ana, bia, caio, davi = (await lead("Ana", "5511900000001"), await lead("Bia", "5511900000002"),
                            await lead("Caio", "5511900000003"), await lead("Davi", "5511900000004"))
    inserir = """insert into agentesia_followups (id_escritorio, id_lead, id_agente, passo, base, agendado_para, situacao, motivo, mensagens, enviado_em)
                 values ($1::uuid, $2, $3::uuid, $4, now() - interval '2 days', now() - interval '2 days', $5, $6, $7::jsonb, $8)"""
    await pool.execute(inserir, esc, ana, agente["id"], 0, "enviado", None, json.dumps(["Oi, Ana! Ficou alguma dúvida?"]),
                       datetime.now(timezone.utc) - timedelta(days=2))
    await pool.execute(inserir, esc, bia, agente["id"], 1, "enviado", None, json.dumps([{"texto": "Oi, Bia!"}]),
                       datetime.now(timezone.utc) - timedelta(days=1))
    await pool.execute(inserir, esc, caio, agente["id"], 0, "cancelado", "equipe_falou", None, None)
    await pool.execute("""insert into agentesia_followups (id_escritorio, id_lead, id_agente, passo, base, agendado_para)
                          values ($1::uuid, $2, $3::uuid, 2, now(), now() + interval '3 hours')""", esc, davi, agente["id"])
    # Ana respondeu 1 h depois do follow-up; Bia não.
    await pool.execute("""insert into agentesia_mensagens (id_escritorio, id_lead, autor, tipo, texto, enviada_em)
                          values ($1::uuid, $2, 'lead', 'texto', 'oi!', now() - interval '2 days' + interval '1 hour')""", esc, ana)

    visao = (await cliente.get("/api/followup/visao", headers=h)).json()
    linha = next(a for a in visao["agentes"] if a["id"] == agente["id"])
    assert (linha["enviados"], linha["respondidos"], linha["pendentes"]) == (2, 1, 1)
    assert visao["totais"]["agentes"] == 1

    itens = (await cliente.get("/api/followup/historico", headers=h)).json()["itens"]
    assert [i["situacao"] for i in itens][0] == "pendente"                         # agendados primeiro
    por_nome = {i["nome"]: i for i in itens}
    assert por_nome["Ana"]["respondeu"] is True and por_nome["Ana"]["mensagens"] == ["Oi, Ana! Ficou alguma dúvida?"]
    assert por_nome["Bia"]["respondeu"] is False and por_nome["Bia"]["mensagens"] == ["Oi, Bia!"] and por_nome["Bia"]["tentativa"] == 2
    assert por_nome["Caio"]["motivo_texto"] == "alguém da equipe falou com o lead"
    so_falhas = (await cliente.get("/api/followup/historico?situacao=nao_enviado", headers=h)).json()["itens"]
    assert [i["nome"] for i in so_falhas] == ["Caio"]
    assert len((await cliente.get("/api/followup/historico?busca=Bia", headers=h)).json()["itens"]) == 1
    assert (await cliente.get("/api/followup/historico?agente=nao-e-uuid", headers=h)).status_code == 400

    painel = (await cliente.get(f"/api/followup/dashboard?agente={agente['id']}", headers=h)).json()
    assert painel["totais"] == {"enviados": 2, "respondidos": 1, "taxa_resposta": 50.0, "falhas": 0, "nao_enviados": 1, "pendentes": 1}
    assert {p["tentativa"]: p["enviados"] for p in painel["por_passo"]} == {1: 1, 2: 1, 3: 0}
    assert painel["motivos"][0]["motivo"] == "equipe_falou"
    assert sum(d["enviados"] for d in painel["por_dia"]) == 2

    # Outro escritório não vê nada deste.
    _, h2, _, _ = await _conta(cliente, f"Outra {uuid.uuid4().hex[:5]}")
    assert (await cliente.get("/api/followup/historico", headers=h2)).json()["itens"] == []


@pg
async def test_avisos_conta_catalogo_e_formato_guardado(ambiente):  # noqa: F811
    cliente, _simulada, email_admin, banco = ambiente
    cliente._transport.app.include_router(rotas_avisos.api)
    pool = banco._pool
    await _entrar(cliente, email_admin, "senha-admin-123")
    esc, h, canais, _agente = await _conta(cliente, f"Avisos {uuid.uuid4().hex[:5]}")
    comum = next(c for c in canais if c["tipo"] != "oficial")
    oficial = next(c for c in canais if c["tipo"] == "oficial")
    # Aviso antigo, de um tipo que não existe mais: aparece em "antigos".
    await pool.execute("""insert into agentesia_notificacoes (id_escritorio, tipo_evento, nome, modelo_mensagem, destinatarios)
                          values ($1::uuid, 'sinal', 'Qualquer sinal', 'x {{nome}}', '[{"rotulo": "Ana", "numero": "5511977776666"}]')""", esc)

    tela = (await cliente.get("/api/avisos", headers=h)).json()
    assert tela["numero_envio"]["id"] == comum["id"] and tela["numero_escolhido"] is False
    assert {c["id"]: c["oficial"] for c in tela["canais"]} == {comum["id"]: False, oficial["id"]: True}
    assert [a["tipo_evento"] for a in tela["antigos"]] == ["sinal"]
    assert tela["destinatarios"] == [{"rotulo": "Ana", "numero": "5511977776666"}]      # veio do aviso antigo
    assert [g["titulo"] for g in tela["grupos"]] == ["Etapas do funil", "Pedidos de atenção", "Problemas"]
    assert not any(i["ligado"] for g in tela["grupos"] for i in g["itens"])

    # Número oficial não pode enviar; o próprio número de envio não pode receber; número sem DDD é recusado.
    r = await cliente.put("/api/avisos/conta", headers=h, json={"numero_envio": oficial["id"]})
    assert r.status_code == 400 and "oficial" in r.json()["detail"]
    assert (await cliente.put("/api/avisos/conta", headers=h, json={"numero_envio": comum["id"]})).status_code == 200
    r = await cliente.put("/api/avisos/conta", headers=h, json={"destinatarios": [{"rotulo": "Eu", "numero": comum["numero_normalizado"]}]})
    assert r.status_code == 400
    assert (await cliente.put("/api/avisos/conta", headers=h, json={"destinatarios": [{"rotulo": "X", "numero": "1234"}]})).status_code == 400
    pessoas = [{"rotulo": "Dra. Ana", "numero": "(11) 97777-6666"}, {"rotulo": "João", "numero": "11 96666-5555"}]
    assert (await cliente.put("/api/avisos/conta", headers=h, json={"destinatarios": pessoas})).status_code == 200

    # Gerenciar: liga três; o resto fica desligado. Coleta de dados grava no gatilho que o agente da conta tem.
    r = await cliente.put("/api/avisos/ligados", headers=h, json={"ligados": ["lead_qualificado", "contrato_assinado", "coleta_dados"]})
    assert r.status_code == 200
    assert (await cliente.put("/api/avisos/ligados", headers=h, json={"ligados": ["nao_existe"]})).status_code == 400
    linhas = {r["tipo_evento"]: dict(r) for r in await pool.fetch(
        "select tipo_evento, habilitada, destinatarios, modelo_mensagem from agentesia_notificacoes where id_escritorio = $1::uuid", esc)}
    assert {k for k, v in linhas.items() if v["habilitada"]} == {"etapa:closer", "contrato_assinado", "etapa:coleta_dados"}
    # Formato que o envio (app/acoes.py) lê: a lista de quem recebe está em cada aviso, igual à da conta.
    assert linhas["sinal"]["habilitada"] is False                                   # genérico desliga junto
    for tipo in ("etapa:closer", "contrato_assinado", "etapa:coleta_dados", "sinal"):
        lista = linhas[tipo]["destinatarios"]
        lista = json.loads(lista) if isinstance(lista, str) else lista
        assert [d["numero"] for d in lista] == ["5511977776666", "5511966665555"], tipo
    config = await pool.fetchval("select config from agentesia_escritorios where id = $1::uuid", esc)
    config = json.loads(config) if isinstance(config, str) else config
    assert config["avisos_numero_envio"] == comum["id"] and len(config["avisos_destinatarios"]) == 2

    # Editar a mensagem de um aviso desligado não liga; desligar pelo cartão desliga.
    assert (await cliente.put("/api/avisos/item/videochamada", headers=h, json={"modelo": "📹 {{nome}} quer vídeo"})).status_code == 200
    video = await pool.fetchrow("select habilitada, modelo_mensagem from agentesia_notificacoes where id_escritorio = $1::uuid and tipo_evento = 'sinal:quer_videochamada'", esc)
    assert video["habilitada"] is False and video["modelo_mensagem"] == "📹 {{nome}} quer vídeo"
    assert (await cliente.put("/api/avisos/item/lead_qualificado", headers=h, json={"ligado": False})).status_code == 200
    tela = (await cliente.get("/api/avisos", headers=h)).json()
    ligados = {i["chave"] for g in tela["grupos"] for i in g["itens"] if i["ligado"]}
    assert ligados == {"contrato_assinado", "coleta_dados"}
    assert tela["numero_escolhido"] is True and len(tela["destinatarios"]) == 2

    # Teste: sai pelo número de envio da conta para cada pessoa.
    r = await cliente.post("/api/avisos/item/contrato_assinado/teste", headers=h)
    assert r.status_code == 200 and r.json()["enfileirados"] == 2 and r.json()["texto"].startswith("🧪 *TESTE*\n")
    acoes = await pool.fetch("select dados from agentesia_acoes where id_escritorio = $1::uuid and tipo = 'notificar'", esc)
    dados = [json.loads(a["dados"]) if isinstance(a["dados"], str) else a["dados"] for a in acoes]
    assert {d["de"] for d in dados} == {comum["numero_normalizado"]}
