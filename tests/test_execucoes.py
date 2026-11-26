"""Superadmin > Execuções (app/gestao/rotas_execucoes.py): lista dos turnos da IA, filtros, detalhe e bloqueio.

Os testes com banco só rodam com AGENTESIA_TESTE_PG_URL (ver tests/test_postgres.py). Nenhuma IA é chamada: os turnos,
mensagens, eventos e chamadas são gravados direto no banco.
"""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.gestao import rotas_execucoes as ex
from tests.test_gestao import _entrar, ambiente  # noqa: F401  (fixture)

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
RAIZ = Path(__file__).resolve().parent.parent
pg = pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")


# ------------------------------------------------------------------ sem banco
def test_mascaras_de_privacidade():
    assert ex.mascarar_telefone("5531986936492") == "(31) *****-6492"
    assert ex.mascarar_telefone(None) is None
    limpo = ex.limpar({
        "fatos_novos": [{"chave": "cpf", "valor": "123.456.789-09", "trecho": "meu cpf é 123.456.789-09"},
                        {"chave": "nome", "valor": "Maria", "trecho": "sou a Maria"}],
        "ficha": {"cpf": "12345678909", "rg": "MG-12.345.678"},
        "token_helena": "abc", "access_token": "x", "tokens_entrada": 120,
        "texto": "CPF: 98765432100 e o outro 111.222.333-44; telefone 31986936492",
    })
    assert limpo["fatos_novos"][0]["valor"] == "***09" and "123.456" not in limpo["fatos_novos"][0]["trecho"]
    assert limpo["fatos_novos"][1]["valor"] == "Maria"
    assert limpo["ficha"] == {"cpf": "***09", "rg": "***78"}
    assert limpo["token_helena"] == "[oculto]" and limpo["access_token"] == "[oculto]" and limpo["tokens_entrada"] == 120
    assert "98765432100" not in limpo["texto"] and "111.222.333-44" not in limpo["texto"]
    assert "31986936492" in limpo["texto"]                 # telefone solto no prompt não é confundido com CPF


def test_rota_registrada_e_item_no_menu_superadmin():
    main = (RAIZ / "app" / "main.py").read_text(encoding="utf-8")
    assert "from app.gestao.rotas_execucoes import api as api_execucoes" in main
    estrutura = (RAIZ / "painel" / "src" / "componentes" / "Estrutura.tsx").read_text(encoding="utf-8")
    superadmin = estrutura[estrutura.index('titulo: "Superadmin"'):]
    assert '{ para: "/admin/execucoes", rotulo: "Execuções"' in superadmin[:1200]
    rotas = (RAIZ / "painel" / "src" / "main.tsx").read_text(encoding="utf-8")
    assert 'path="/admin/execucoes"' in rotas
    tela = (RAIZ / "painel" / "src" / "telas" / "Execucoes.tsx").read_text(encoding="utf-8")
    assert "Helena" not in tela


def test_painel_do_servidor_leva_as_rotas():
    from app.servidor import criar_app, rotas_montadas
    caminhos = rotas_montadas(criar_app("painel"))
    assert {"/api/admin/execucoes", "/api/admin/execucoes/filtros", "/api/admin/execucoes/{id_turno}"} <= caminhos
    assert "/api/admin/execucoes" not in rotas_montadas(criar_app("ia"))


# ------------------------------------------------------------------ com banco
async def _semear(cliente, pool, nome_conta, nome_lead, telefone):
    """Conta + agente + lead e 3 turnos: respondido com troca e tool, silêncio, erro."""
    escritorio = (await cliente.post("/api/admin/escritorios", json={
        "nome": nome_conta, "id_conta_helena": str(uuid.uuid4()),
        "token_helena": f"token-bom-{uuid.uuid4().hex[:8]}"})).json()["escritorio"]
    h = {"x-escritorio": escritorio["id"]}
    canal = next(c for c in (await cliente.get("/api/integracoes", headers=h)).json()["canais"] if c["tipo"] != "oficial")
    agente = (await cliente.post("/api/agentes", headers=h, json={"nome": f"Agente {nome_lead}", "id_canal": canal["id"]})).json()
    contato = await pool.fetchval(
        "insert into agentesia_contatos (id_escritorio, nome, telefone_normalizado) values ($1::uuid, $2, $3) returning id",
        escritorio["id"], nome_lead, telefone)
    id_lead = str(await pool.fetchval(
        """insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_agente, estado)
           values ($1::uuid, $2, $3::uuid, $4::uuid, 'ativo') returning id""",
        escritorio["id"], contato, canal["id"], agente["id"]))
    agora = datetime.now(timezone.utc)
    contexto = {
        "etapa": {"sistema": "# REGRAS DO ATENDIMENTO (sistema)\n- seja breve\n# ROTEIRO\nPergunte do acidente.",
                  "conteudo": "MENSAGENS NOVAS DO LEAD:\n- caí da moto\n\nDADOS JÁ INFORMADOS PELO LEAD (não pergunte de novo): CPF 123.456.789-09",
                  "resposta": {"mensagens": [{"texto": "Entendi"}], "transferir_para": "closer"}},
        "extrator": {"conteudo": "fatos...", "resposta": {"fatos": []}},
        "catalogo": {"destinos": ["closer"], "acoes": ["zapsign"], "transferir_para": "closer", "ferramenta": "",
                     "origem_destino": "ia"},
    }
    resposta = {
        "mensagens": [{"texto": "Entendi"}, {"texto": "Vou te passar para a proposta."}],
        "fatos_novos": [{"chave": "cpf", "valor": "123.456.789-09", "trecho": "123.456.789-09"},
                        {"chave": "acidente_descricao", "valor": "caí da moto", "trecho": "caí da moto"}],
        "fatos_rejeitados": [{"chave": "sequela", "valor": "sim", "trecho": "", "motivo": "trecho_nao_encontrado"}],
        "intencoes": {"quer_seguir": True}, "reprovacoes": [[{"codigo": "promessa_valor", "orientacao": "não prometa"}]],
        "decisoes": [], "tempos": {"passos_ms": {"extrator": 812.5, "agente": 1530.2}, "total_ms": 2600.0, "idas_ao_banco": 9},
        "ficha": "Maria, CPF 123.456.789-09",
    }
    t1 = str(await pool.fetchval(
        """insert into agentesia_turnos (id_escritorio, id_lead, modo, etapa_antes, etapa_depois, contexto, resposta,
                                         situacao, motivo, iniciado_em, concluido_em)
           values ($1::uuid, $2::uuid, 'producao', 'sdr', 'closer', $3::jsonb, $4::jsonb, 'respondido',
                   'transferencia:closer', $5::timestamptz, $5::timestamptz + interval '2600 milliseconds') returning id""",
        escritorio["id"], id_lead, json.dumps(contexto, ensure_ascii=False), json.dumps(resposta, ensure_ascii=False),
        agora - timedelta(minutes=30)))
    t2 = str(await pool.fetchval(
        """insert into agentesia_turnos (id_escritorio, id_lead, modo, etapa_antes, etapa_depois, situacao, motivo,
                                         iniciado_em, concluido_em)
           values ($1::uuid, $2::uuid, 'producao', 'closer', 'closer', 'silencio', 'lead_so_agradeceu', $3::timestamptz, $3::timestamptz + interval '1 second')
           returning id""", escritorio["id"], id_lead, agora - timedelta(minutes=20)))
    t3 = str(await pool.fetchval(
        """insert into agentesia_turnos (id_escritorio, id_lead, modo, etapa_antes, situacao, motivo, iniciado_em, concluido_em)
           values ($1::uuid, $2::uuid, 'producao', 'closer', 'erro', 'falha_modelo:etapa', $3::timestamptz, $3::timestamptz + interval '5 seconds')
           returning id""", escritorio["id"], id_lead, agora - timedelta(minutes=10)))
    for autor, texto, seg in (("lead", "caí da moto, meu cpf é 123.456.789-09", 0), ("ia", "Entendi", 2),
                              ("ia", "Vou te passar para a proposta.", 3)):
        await pool.execute(
            """insert into agentesia_mensagens (id_escritorio, id_lead, id_turno, autor, tipo, texto, enviada_em, situacao_envio)
               values ($1::uuid, $2::uuid, $3::uuid, $4, 'texto', $5, $6, $7)""",
            escritorio["id"], id_lead, t1, autor, texto, agora - timedelta(minutes=30) + timedelta(seconds=seg),
            "recebida" if autor == "lead" else "enviada")
    await pool.execute(
        """insert into agentesia_eventos (id_escritorio, id_lead, id_turno, tipo, gravidade, responsavel, descricao, detalhe)
           values ($1::uuid, $2::uuid, $3::uuid, 'pergunta_ja_respondida', 'info', 'lawchat', 'Não repetiu a pergunta', '{}'::jsonb),
                  ($1::uuid, $2::uuid, $3::uuid, 'etapa_trocada', 'info', 'lawchat', 'sdr -> closer', '{"de": "sdr", "para": "closer"}'::jsonb)""",
        escritorio["id"], id_lead, t1)
    await pool.execute(
        """insert into agentesia_chamadas_ia (id_escritorio, id_turno, papel, modelo, tokens_entrada, tokens_saida, custo_usd,
                                              custo_brl, duracao_ms, sucesso)
           values ($1::uuid, $2::uuid, 'extrator', 'gpt-4.1-mini', 1000, 50, 0.001, 0.0060, 800, true),
                  ($1::uuid, $2::uuid, 'etapa', 'gpt-4.1', 3000, 120, 0.010, 0.0600, 1500, true)""",
        escritorio["id"], t1)
    return {"escritorio": escritorio["id"], "agente": agente["id"], "lead": id_lead, "t1": t1, "t2": t2, "t3": t3}


@pg
async def test_lista_filtros_detalhe_e_bloqueio(ambiente):  # noqa: F811
    cliente, _simulada, email_admin, banco = ambiente
    cliente._transport.app.include_router(ex.api)
    pool = banco._pool
    await _entrar(cliente, email_admin, "senha-admin-123")
    marca = uuid.uuid4().hex[:6]                           # o banco de teste é o mesmo entre rodadas
    fone_b = "55119" + str(uuid.uuid4().int)[:8]
    a = await _semear(cliente, pool, "Execuções A", f"Maria Execução {marca}", "5531986936492")
    b = await _semear(cliente, pool, "Execuções B", f"João Execução {marca}", fone_b)

    # Lista: mais novas primeiro, com conta, agente, lead mascarado, etapas, situação, tool, duração e custo.
    r = await cliente.get("/api/admin/execucoes", params={"conta": a["escritorio"]})
    assert r.status_code == 200, r.text
    itens = r.json()["itens"]
    assert [i["id"] for i in itens] == [a["t3"], a["t2"], a["t1"]]
    t1 = itens[2]
    assert t1["conta"] == "Execuções A" and t1["agente"] == f"Agente Maria Execução {marca}"
    assert t1["lead"] == {"nome": f"Maria Execução {marca}", "telefone": "(31) *****-6492"}
    assert (t1["etapa_antes"], t1["etapa_depois"], t1["trocou_etapa"]) == ("sdr", "closer", True)
    assert t1["grupo"] == "respondido" and t1["tool"]["transferir_para"] == "closer" and t1["tool"]["chamou"] is True
    assert t1["duracao_ms"] == 2600
    custo_banco = float(await pool.fetchval("select sum(custo_brl) from agentesia_chamadas_ia where id_turno = $1::uuid", a["t1"]))
    assert custo_banco > 0                                  # o banco calcula o R$ (cotação e markup) ao gravar a chamada
    assert t1["custo"]["chamadas"] == 2 and abs(t1["custo"]["brl"] - custo_banco) < 1e-9 and t1["custo"]["tokens_entrada"] == 4000
    assert itens[1]["grupo"] == "sem_resposta" and itens[1]["motivo"] == "lead_so_agradeceu" and not itens[1]["tool"]["chamou"]
    assert itens[0]["grupo"] == "erro"
    assert "5531986936492" not in r.text and "123.456.789" not in r.text

    # Paginação.
    p1 = (await cliente.get("/api/admin/execucoes", params={"conta": a["escritorio"], "por_pagina": 2})).json()
    p2 = (await cliente.get("/api/admin/execucoes", params={"conta": a["escritorio"], "por_pagina": 2, "pagina": 2})).json()
    assert p1["tem_mais"] is True and len(p1["itens"]) == 2 and p2["tem_mais"] is False and [i["id"] for i in p2["itens"]] == [a["t1"]]

    # Filtros.
    async def ids(**params):
        resp = await cliente.get("/api/admin/execucoes", params=params)
        assert resp.status_code == 200, resp.text
        return {i["id"] for i in resp.json()["itens"]}
    todos = await ids(por_pagina=200)
    assert {a["t1"], a["t2"], a["t3"], b["t1"], b["t2"], b["t3"]} <= todos
    assert await ids(agente=b["agente"]) == {b["t1"], b["t2"], b["t3"]}
    assert await ids(busca=f"Maria Execução {marca}") == {a["t1"], a["t2"], a["t3"]}
    assert await ids(busca=f"({fone_b[2:4]}) {fone_b[4:9]}-{fone_b[9:]}") == {b["t1"], b["t2"], b["t3"]}
    assert await ids(conta=a["escritorio"], situacao="sem_resposta") == {a["t2"]}
    assert await ids(conta=a["escritorio"], situacao="respondido") == {a["t1"]}
    assert await ids(conta=a["escritorio"], erro=True) == {a["t3"]}
    assert await ids(conta=a["escritorio"], troca=True) == {a["t1"]}
    agora = datetime.now(timezone.utc)
    assert await ids(conta=a["escritorio"], de=(agora - timedelta(minutes=25)).isoformat(),
                     ate=(agora - timedelta(minutes=15)).isoformat()) == {a["t2"]}
    assert (await cliente.get("/api/admin/execucoes", params={"situacao": "qualquer"})).status_code == 400
    assert (await cliente.get("/api/admin/execucoes", params={"conta": "x"})).status_code == 400

    filtros = (await cliente.get("/api/admin/execucoes/filtros")).json()
    assert any(c["id"] == a["escritorio"] for c in filtros["contas"])
    assert any(g["id"] == a["agente"] and g["id_escritorio"] == a["escritorio"] for g in filtros["agentes"])

    # Detalhe: entrada, prompt, decisão, saída, travas, tempos, custo e navegação no mesmo lead.
    d = (await cliente.get(f"/api/admin/execucoes/{a['t1']}")).json()
    assert [m["texto"] for m in d["entrada"]] == ["caí da moto, meu cpf é ***.***.***-09"]
    assert [m["texto"] for m in d["saida"]] == ["Entendi", "Vou te passar para a proposta."]
    assert d["prompt"]["sistema"].startswith("# REGRAS DO ATENDIMENTO") and "MENSAGENS NOVAS DO LEAD" in d["prompt"]["conteudo"]
    assert "123.456.789-09" not in json.dumps(d, ensure_ascii=False)
    assert d["decisao"]["transferir_para"] == "closer" and d["decisao"]["intencoes"] == {"quer_seguir": True}
    assert d["decisao"]["fatos_novos"][0]["valor"] == "***09"
    assert d["decisao"]["fatos_rejeitados"][0]["motivo"] == "trecho_nao_encontrado"
    assert d["decisao"]["reprovacoes"][0][0]["codigo"] == "promessa_valor"
    assert [e["tipo"] for e in d["travas"]] == ["pergunta_ja_respondida"]
    assert {e["tipo"] for e in d["eventos"]} == {"pergunta_ja_respondida", "etapa_trocada"}
    assert d["tempos"]["passos_ms"]["agente"] == 1530.2
    assert [c["papel"] for c in d["chamadas"]] == ["extrator", "etapa"]
    assert d["navegacao"] == {"anterior": None, "seguinte": a["t2"]}
    meio = (await cliente.get(f"/api/admin/execucoes/{a['t2']}")).json()
    assert meio["navegacao"] == {"anterior": a["t1"], "seguinte": a["t3"]}
    assert meio["prompt"]["sistema"] is None and meio["entrada"] == []
    assert (await cliente.get(f"/api/admin/execucoes/{uuid.uuid4()}")).status_code == 404

    # Bloqueio: a LawChat na visão do cliente e um gestor de verdade não veem nada.
    visao = {"x-escritorio": a["escritorio"], "x-visao": "gestor"}
    assert (await cliente.get("/api/admin/execucoes", headers=visao)).status_code == 403
    criado = (await cliente.post("/api/admin/escritorios", json={
        "nome": "Execuções C", "id_conta_helena": str(uuid.uuid4()), "token_helena": f"token-bom-{uuid.uuid4().hex[:8]}",
        "email_gestor": f"g-{uuid.uuid4().hex[:6]}@x.com", "nome_gestor": "Dra. C"})).json()
    await cliente.post("/api/sair")
    await _entrar(cliente, criado["gestor"]["email"], criado["senha_provisoria"])
    for caminho in ("/api/admin/execucoes", "/api/admin/execucoes/filtros", f"/api/admin/execucoes/{a['t1']}"):
        assert (await cliente.get(caminho)).status_code == 403, caminho
    await cliente.post("/api/sair")
    assert (await cliente.get("/api/admin/execucoes")).status_code == 401


# ------------------------------------------------------------------ resultado (certo/errado e por quê)
def test_detalhe_do_erro_guarda_tipo_modulo_linha_e_status():
    from app.pipeline import detalhe_do_erro

    class ErroHttp(Exception):
        status_code = 503
    try:
        raise ErroHttp("Service Unavailable")
    except ErroHttp as erro:
        d = detalhe_do_erro(erro)
    assert d["tipo"] == "ErroHttp" and d["status"] == 503 and d["mensagem"] == "Service Unavailable"
    assert d["modulo"] == __name__
    try:
        raise TimeoutError()
    except TimeoutError as erro:
        assert detalhe_do_erro(erro)["status"] is None


async def _turno(pool, base, situacao, motivo, *, minutos, duracao_s=1.0, evento=None, chamada_erro=None,
                 envio_falhou=None, tempos=None):
    resposta = json.dumps({"tempos": tempos}) if tempos else None
    id_turno = str(await pool.fetchval(
        """insert into agentesia_turnos (id_escritorio, id_lead, modo, etapa_antes, situacao, motivo, resposta,
                                         iniciado_em, concluido_em)
           values ($1::uuid, $2::uuid, 'producao', 'sdr', $3, $4, $5::jsonb, now() - make_interval(mins => $6),
                   now() - make_interval(mins => $6) + make_interval(secs => $7)) returning id""",
        base["escritorio"], base["lead"], situacao, motivo, resposta, minutos, float(duracao_s)))
    if evento:
        tipo, detalhe = evento
        await pool.execute(
            """insert into agentesia_eventos (id_escritorio, id_lead, id_turno, tipo, gravidade, responsavel, descricao, detalhe)
               values ($1::uuid, $2::uuid, $3::uuid, $4, 'critico', 'lawchat', 'Erro no turno', $5::jsonb)""",
            base["escritorio"], base["lead"], id_turno, tipo, json.dumps(detalhe))
    if chamada_erro:
        await pool.execute(
            """insert into agentesia_chamadas_ia (id_escritorio, id_turno, papel, modelo, duracao_ms, sucesso, erro)
               values ($1::uuid, $2::uuid, 'etapa', 'gpt-4.1', 30000, false, $3)""", base["escritorio"], id_turno, chamada_erro)
    if envio_falhou:
        await pool.execute(
            """insert into agentesia_mensagens (id_escritorio, id_lead, id_turno, autor, tipo, texto, enviada_em,
                                                situacao_envio, erro)
               values ($1::uuid, $2::uuid, $3::uuid, 'ia', 'texto', 'Oi', now() - make_interval(mins => $4), 'falhou', $5)""",
            base["escritorio"], base["lead"], id_turno, minutos, envio_falhou)
    return id_turno


@pg
async def test_resultado_status_filtro_resumo_e_linha_do_tempo(ambiente):  # noqa: F811
    cliente, _simulada, email_admin, banco = ambiente
    cliente._transport.app.include_router(ex.api)
    pool = banco._pool
    await _entrar(cliente, email_admin, "senha-admin-123")
    marca = uuid.uuid4().hex[:6]
    base = await _semear(cliente, pool, f"Resultados {marca}", f"Ana Resultado {marca}", "55" + str(uuid.uuid4().int)[:11])
    for t in ("t1", "t2", "t3"):                            # os 3 da semeadura saem do período (3 dias atrás)
        await pool.execute("update agentesia_turnos set iniciado_em = now() - interval '3 days', "
                           "concluido_em = now() - interval '3 days' where id = $1::uuid", base[t])
    T = {}
    T["ok"] = await _turno(pool, base, "respondido", "", minutos=100, duracao_s=2, tempos={
        "passos_ms": {"ia_total": 1500.0, "envio": 400.0, "pos_envio": 80.0}, "marcas_ms": {"primeira_parte_enviada": 1700.0}})
    T["ok2"] = await _turno(pool, base, "respondido", "transferencia:closer", minutos=95, duracao_s=4)
    T["timeout_ia"] = await _turno(pool, base, "erro", "turno:sem_conexao", minutos=90, duracao_s=90,
                                   evento=("ia_nao_respondeu", {"detalhe": "a IA passou de 90 s"}))
    T["timeout_openai"] = await _turno(pool, base, "erro", "etapa:sem_conexao:nova_tentativa", minutos=85, duracao_s=60,
                                       chamada_erro="sem_conexao: Request timed out.")
    T["5xx_ia"] = await _turno(pool, base, "erro", "etapa:provedor_fora_do_ar", minutos=80,
                               chamada_erro="provedor_fora_do_ar: 503")
    T["banco"] = await _turno(pool, base, "erro", "erro_interno:TooManyConnectionsError", minutos=75, evento=(
        "erro_no_turno", {"tipo": "TooManyConnectionsError", "modulo": "asyncpg.exceptions",
                          "mensagem": "sorry, too many clients", "onde": "banco/postgres.py:640 (fatos_do_sistema)",
                          "status": None}))
    T["timeout_banco"] = await _turno(pool, base, "erro", "erro_interno:TimeoutError", minutos=70, evento=(
        "erro_no_turno", {"tipo": "TimeoutError", "modulo": "builtins", "mensagem": "", "onde": "banco/postgres.py:12 (lead)"}))
    T["antigo_bug"] = await _turno(pool, base, "erro", "erro_interno:KeyError", minutos=65)
    T["envio_5xx"] = await _turno(pool, base, "respondido", "", minutos=60, envio_falhou="HTTP 503")
    T["interrompido"] = await _turno(pool, base, "erro", "turno_interrompido", minutos=55, evento=(
        "turno_interrompido", {"enviadas": 0, "devolvidas": 2, "novas": 0}))
    T["ignorado"] = await _turno(pool, base, "silencio", "ia_desligada_no_escritorio", minutos=50, duracao_s=0.1)
    T["sem_credito"] = await _turno(pool, base, "silencio", "sem_saldo", minutos=45, duracao_s=0.1)
    T["calada"] = await _turno(pool, base, "silencio", "lead_so_agradeceu", minutos=40)
    T["refeito"] = await _turno(pool, base, "descartado", "chegou_mensagem_nova", minutos=35)
    esperado = {"ok": "sucesso", "ok2": "sucesso", "timeout_ia": "timeout", "timeout_openai": "timeout",
                "5xx_ia": "erro_5xx", "banco": "erro_banco", "timeout_banco": "timeout", "antigo_bug": "erro",
                "envio_5xx": "erro_5xx", "interrompido": "interrompido", "ignorado": "ignorado",
                "sem_credito": "ignorado", "calada": "sem_resposta", "refeito": "descartado"}
    de = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()

    resp = await cliente.get("/api/admin/execucoes", params={"conta": base["escritorio"], "de": de, "por_pagina": 100})
    assert resp.status_code == 200, resp.text
    por_id = {i["id"]: i for i in resp.json()["itens"]}
    assert {nome: por_id[T[nome]]["resultado"]["status"] for nome in T} == esperado

    def r(nome):
        return por_id[T[nome]]["resultado"]
    assert r("banco")["origem"] == "banco" and r("banco")["erro"]["onde"] == "banco/postgres.py:640 (fatos_do_sistema)"
    assert r("banco")["erro"]["mensagem"] == "sorry, too many clients" and r("banco")["causa"] == "Conexões do banco esgotadas"
    assert r("timeout_banco")["origem"] == "banco"
    assert r("timeout_openai")["origem"] == "ia" and r("timeout_openai")["nova_tentativa"] is True
    assert "Vai tentar de novo" in r("timeout_openai")["causa"]
    assert r("5xx_ia")["origem"] == "ia" and r("envio_5xx")["origem"] == "plataforma"
    assert r("interrompido")["retomado"] is True and r("interrompido")["origem"] == "servidor"
    assert r("antigo_bug")["erro"]["tipo"] == "KeyError" and r("antigo_bug")["origem"] == "servidor"
    assert r("sem_credito")["causa"] == "Sem crédito de IA" and r("ok")["erro"] is None
    assert por_id[T["ok"]]["etapas_ms"] == {"contexto": None, "ia": 1500.0, "envio": 400.0, "acoes": 80.0, "gravacoes": None}

    async def ids(**params):
        resp = await cliente.get("/api/admin/execucoes", params={"conta": base["escritorio"], "de": de, "por_pagina": 100,
                                                                 **params})
        assert resp.status_code == 200, resp.text
        return {i["id"] for i in resp.json()["itens"]}
    assert await ids(status="timeout") == {T["timeout_ia"], T["timeout_openai"], T["timeout_banco"]}
    assert await ids(status="erro_banco,erro_5xx") == {T["banco"], T["5xx_ia"], T["envio_5xx"]}
    assert len(await ids(status="erros")) == 8
    assert await ids(status="ignorado", busca=base["lead"]) == {T["ignorado"], T["sem_credito"]}
    assert (await cliente.get("/api/admin/execucoes", params={"status": "nada"})).status_code == 400

    # Resumo: contadores, taxa de erro (sem os ignorados), tempo médio, p95 e série por hora.
    res = (await cliente.get("/api/admin/execucoes/resumo", params={"conta": base["escritorio"], "de": de})).json()
    assert res["total"] == 14 and res["sucesso"] == 2 and res["erros"] == 8 and res["timeouts"] == 3
    assert res["por_status"]["ignorado"] == 2 and res["por_status"]["descartado"] == 1
    assert res["taxa_erro"] == round(8 / 12, 4)
    assert res["p95_ms"] == 90000 and 10000 < res["tempo_medio_ms"] < 20000
    assert res["fatia"] == "hora" and 6 <= len(res["serie"]) <= 7
    assert sum(p["sucesso"] for p in res["serie"]) == 2 and sum(p["erros"] for p in res["serie"]) == 8
    assert sum(p["outros"] for p in res["serie"]) == 4
    so_erros = (await cliente.get("/api/admin/execucoes/resumo", params={
        "conta": base["escritorio"], "de": de, "status": "erros"})).json()
    assert so_erros["total"] == 8
    semana = (await cliente.get("/api/admin/execucoes/resumo", params={
        "conta": base["escritorio"], "de": (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()})).json()
    assert semana["fatia"] == "dia" and semana["total"] == 17
    assert (await cliente.get("/api/admin/execucoes/resumo", params={
        "de": "2026-01-02T00:00:00Z", "ate": "2026-01-01T00:00:00Z"})).status_code == 400

    # Detalhe: resultado, tentativas, ações do turno e a linha do tempo em ordem.
    await pool.execute(
        """insert into agentesia_acoes (id_escritorio, id_lead, id_turno, tipo, dados, situacao, tentativas, erro,
                                        criado_em, atualizado_em)
           values ($1::uuid, $2::uuid, $3::uuid, 'mover_card', '{}'::jsonb, 'feita', 2, null,
                   now() - interval '100 minutes' + interval '2 seconds', now() - interval '100 minutes' + interval '5 seconds')""",
        base["escritorio"], base["lead"], T["ok"])
    d = (await cliente.get(f"/api/admin/execucoes/{T['ok']}")).json()
    assert d["resultado"]["status"] == "sucesso"
    assert d["acoes_turno"][0]["tipo"] == "mover_card" and d["acoes_turno"][0]["duracao_ms"] == 3000
    assert d["tentativas"]["acoes_repetidas"] == 1 and d["tentativas"]["turno"] == 1
    tipos = [p["tipo"] for p in d["linha_do_tempo"]]
    assert tipos[0] == "inicio" and tipos[-1] == "acao" and "fim" in tipos and "marca" in tipos and tipos.count("acao") == 2
    assert [p["ms"] for p in d["linha_do_tempo"]] == sorted(p["ms"] for p in d["linha_do_tempo"])
    seguinte = (await cliente.get(f"/api/admin/execucoes/{T['5xx_ia']}")).json()
    assert seguinte["tentativas"]["turno"] == 2                # o turno antes dele pediu nova tentativa
    assert seguinte["tentativas"]["chamadas_ia_falharam"] == 1
    fim = seguinte["linha_do_tempo"][-1]
    assert fim["tipo"] == "fim" and fim["estado"] == "bad" and "5xx" in fim["titulo"]
