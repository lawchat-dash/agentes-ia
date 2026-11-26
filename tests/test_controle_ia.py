"""Controle da IA na Central (app/gestao/rotas_controle_ia.py): achar o lead da conversa aberta, desativar/reativar
pelo mesmo serviço da tela Conversas (nota, etiqueta, histórico) sem nota duplicada no clique repetido, e a busca.

Os testes com banco só rodam com AGENTESIA_TESTE_PG_URL (ver tests/test_postgres.py).
"""

import os
import uuid
from pathlib import Path

import pytest

from app.gestao import rotas_controle_ia as ci
from tests.test_gestao import _entrar, ambiente  # noqa: F401  (fixture)

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
RAIZ = Path(__file__).resolve().parent.parent
pg = pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")


# ------------------------------------------------------------------ sem banco
def test_partes_do_telefone():
    assert ci._partes_do_telefone("5543991398139") == ("5543991398139", "43", "91398139")
    assert ci._partes_do_telefone("554391398139") == ("5543991398139", "43", "91398139")   # sem o nono dígito
    assert ci._partes_do_telefone("(43) 99139-8139") == ("5543991398139", "43", "91398139")
    assert ci._partes_do_telefone("91398139") == (None, None, "91398139")
    with pytest.raises(Exception):
        ci._partes_do_telefone("1234")


def test_rota_registrada_ponte_e_sem_nome_da_plataforma():
    main = (RAIZ / "app" / "main.py").read_text(encoding="utf-8")
    assert "from app.gestao.rotas_controle_ia import api as api_controle_ia" in main
    from app.servidor import criar_app, rotas_montadas
    caminhos = rotas_montadas(criar_app("painel"))
    assert {"/api/controle-ia/lead", "/api/controle-ia/desativar", "/api/controle-ia/reativar",
            "/api/controle-ia/buscar"} <= caminhos
    rotas = (RAIZ / "painel" / "src" / "main.tsx").read_text(encoding="utf-8")
    assert "/controle-ia/ponte" in rotas
    for arquivo in ("ControleIA.tsx", "PonteControleIA.tsx"):
        texto = (RAIZ / "painel" / "src" / "componentes" / arquivo).read_text(encoding="utf-8")
        assert "Helena" not in texto and "MENSAGEM_CONVERSA" in texto
    controle = (RAIZ / "painel" / "src" / "componentes" / "ControleIA.tsx").read_text(encoding="utf-8")
    assert 'MENSAGEM_CONVERSA = "lawchat-conversa-aberta"' in controle
    assert "e.origin !== window.location.origin" in controle          # só aceita aviso do próprio painel


# ------------------------------------------------------------------ com banco
async def _semear(cliente, pool, nome_conta):
    conta = str(uuid.uuid4())
    escritorio = (await cliente.post("/api/admin/escritorios", json={
        "nome": nome_conta, "id_conta_helena": conta,
        "token_helena": f"token-bom-{uuid.uuid4().hex[:8]}"})).json()["escritorio"]
    h = {"x-escritorio": escritorio["id"]}
    canal = next(c for c in (await cliente.get("/api/integracoes", headers=h)).json()["canais"] if c["tipo"] != "oficial")
    agente = (await cliente.post("/api/agentes", headers=h, json={"nome": "Júlia", "id_canal": canal["id"]})).json()
    return escritorio["id"], h, canal["id"], agente["id"], conta


async def _lead(pool, id_escritorio, id_canal, id_agente, nome, telefone, sessao=None, contato_ext=None, estado="ativo"):
    contato = await pool.fetchval(
        """insert into agentesia_contatos (id_escritorio, nome, telefone_normalizado, id_contato_helena)
           values ($1::uuid, $2, $3, $4) returning id""", id_escritorio, nome, telefone, contato_ext)
    return str(await pool.fetchval(
        """insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_agente, estado, id_sessao_helena,
                                        id_etapa)
           values ($1::uuid, $2, $3::uuid, $4::uuid, $5, $6,
                   (select id from agentesia_agente_etapas where id_agente = $4::uuid and principal limit 1))
           returning id""", id_escritorio, contato, id_canal, id_agente, estado, sessao))


async def _notas(pool, id_lead):
    return await pool.fetchval("select count(*) from agentesia_acoes where id_lead = $1::uuid and tipo = 'nota'", id_lead)


@pg
async def test_achar_desativar_reativar_e_buscar(ambiente):  # noqa: F811
    cliente, _simulada, email_admin, banco = ambiente
    cliente._transport.app.include_router(ci.api)
    pool = banco._pool
    await _entrar(cliente, email_admin, "senha-admin-123")
    marca = uuid.uuid4().hex[:6]
    esc, h, canal, agente, conta = await _semear(cliente, pool, f"Controle IA {marca}")
    fone = "55439" + str(uuid.uuid4().int)[:8]
    sessao, contato_ext = f"sess-{marca}", f"cont-{marca}"
    id_lead = await _lead(pool, esc, canal, agente, f"Maria Controle {marca}", fone, sessao, contato_ext)

    # Achar: pela sessão, pelo contato, pelo telefone exato e pelo telefone sem o nono dígito (DDD + 8 últimos).
    async def achar(**params):
        return await cliente.get("/api/controle-ia/lead", params=params, headers=h)
    r = await achar(sessao=sessao, contato="x", telefone="1")
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["id_lead"], d["por"], d["ia_ligada"], d["agente"]) == (id_lead, "sessao", True, "Júlia")
    assert d["telefone"] == f"({fone[2:4]}) *****-{fone[-4:]}" and fone not in r.text
    assert (await achar(sessao="outra", contato=contato_ext)).json()["por"] == "contato"
    assert (await achar(telefone=fone)).json()["por"] == "telefone"
    sem_nono = fone[:4] + fone[5:]
    assert (await achar(sessao="outra", telefone=sem_nono)).json()["id_lead"] == id_lead
    nao = await achar(sessao="nao-existe")
    assert nao.status_code == 404 and "não tem lead" in nao.json()["detail"]
    assert (await achar()).status_code == 400
    # Ponte aberta fora do painel (equipe LawChat sem escritório escolhido): vale a conta da plataforma (id_da_conta).
    pela_conta = await cliente.get("/api/controle-ia/lead", params={"sessao": sessao, "conta": conta})
    assert pela_conta.status_code == 200 and pela_conta.json()["id_lead"] == id_lead, pela_conta.text

    # Outro escritório não acha nem mexe.
    esc2, h2, _c2, _a2, _conta2 = await _semear(cliente, pool, f"Controle IA outro {marca}")
    assert (await cliente.get("/api/controle-ia/lead", params={"sessao": sessao}, headers=h2)).status_code == 404
    assert (await cliente.post("/api/controle-ia/desativar", json={"id_lead": id_lead}, headers=h2)).status_code == 404

    # Desativar até religar: mesmo serviço da tela Conversas (estado, nota, etiqueta, histórico).
    r = await cliente.post("/api/controle-ia/desativar", json={"id_lead": id_lead, "minutos": 0}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["mudou"] is True and r.json()["lead"]["ia_ligada"] is False and "desativada" in r.json()["mensagem"]
    assert await _notas(pool, id_lead) == 1
    assert await pool.fetchval(
        "select count(*) from agentesia_acoes where id_lead = $1::uuid and tipo = 'etiquetar'", id_lead) == 1
    assert (await achar(sessao=sessao)).json()["ia_ligada"] is False

    # Clique repetido: não muda nada e não deixa outra nota.
    r = await cliente.post("/api/controle-ia/desativar", json={"id_lead": id_lead, "minutos": 0}, headers=h)
    assert r.json()["mudou"] is False and "já estava desativada" in r.json()["mensagem"]
    assert await _notas(pool, id_lead) == 1

    # Trocar para um prazo (30 min) vale; o mesmo prazo de novo logo em seguida é repetição.
    r = await cliente.post("/api/controle-ia/desativar", json={"id_lead": id_lead, "minutos": 30}, headers=h)
    assert r.json()["mudou"] is True and r.json()["lead"]["pausado_ate"] and "30 minutos" in r.json()["mensagem"]
    assert await _notas(pool, id_lead) == 2
    r = await cliente.post("/api/controle-ia/desativar", json={"id_lead": id_lead, "minutos": 30}, headers=h)
    assert r.json()["mudou"] is False and await _notas(pool, id_lead) == 2
    assert (await cliente.post("/api/controle-ia/desativar", json={"id_lead": id_lead, "minutos": 45},
                               headers=h)).status_code == 422

    # Reativar (e de novo: sem nota nova).
    r = await cliente.post("/api/controle-ia/reativar", json={"id_lead": id_lead}, headers=h)
    assert r.json()["mudou"] is True and r.json()["lead"]["ia_ligada"] is True and "religada" in r.json()["mensagem"]
    assert await _notas(pool, id_lead) == 3
    r = await cliente.post("/api/controle-ia/reativar", json={"id_lead": id_lead}, headers=h)
    assert r.json()["mudou"] is False and "já estava ligada" in r.json()["mensagem"] and await _notas(pool, id_lead) == 3
    historico = {x["acao"] for x in (await cliente.get("/api/alteracoes", headers=h)).json()}
    assert {"desligou_ia", "religou_ia"} <= historico

    # Conversa encerrada: mensagem clara.
    encerrado = await _lead(pool, esc, canal, agente, f"João Encerrado {marca}", "55439" + str(uuid.uuid4().int)[:8],
                            estado="encerrado")
    r = await cliente.post("/api/controle-ia/desativar", json={"id_lead": encerrado}, headers=h)
    assert r.status_code == 409 and "encerrada" in r.json()["detail"]
    assert (await cliente.post("/api/controle-ia/reativar", json={"id_lead": "x"}, headers=h)).status_code == 404

    # Plano B: busca por nome e por telefone, só do escritório.
    achados = (await cliente.get("/api/controle-ia/buscar", params={"q": f"Controle {marca}"}, headers=h)).json()
    assert [a["id_lead"] for a in achados] == [id_lead]
    assert [a["id_lead"] for a in (await cliente.get("/api/controle-ia/buscar", params={"q": fone[-8:]},
                                                        headers=h)).json()] == [id_lead]
    assert (await cliente.get("/api/controle-ia/buscar", params={"q": f"Controle {marca}"}, headers=h2)).json() == []
    assert (await cliente.get("/api/controle-ia/buscar", params={"q": "%"}, headers=h)).json() == []


# ------------------------------------------------------------------ link da conversa (sem login)
def test_limpo_ignora_variavel_nao_preenchida():
    assert ci._limpo("{{id_do_card}}") == "" and ci._limpo("  ") == "" and ci._limpo(" abc ") == "abc"


def test_rotas_publicas_e_cartao_do_link():
    from app.servidor import criar_app, rotas_montadas
    caminhos = rotas_montadas(criar_app("painel"))
    assert {"/api/controle-ia/publico/lead", "/api/controle-ia/publico/desativar",
            "/api/controle-ia/publico/reativar"} <= caminhos
    cartao = (RAIZ / "painel" / "src" / "componentes" / "LinkControleIA.tsx").read_text(encoding="utf-8")
    assert ("/controle-ia/ponte?" in cartao and "id_da_conta={{id_da_conta}}" in cartao
            and "telefone_do_contato={{telefone_do_contato}}" in cartao and "id_do_usuario={{id_do_usuario}}" in cartao)
    assert "Helena" not in cartao
    assert "LinkControleIA" in (RAIZ / "painel" / "src" / "telas" / "Integracoes.tsx").read_text(encoding="utf-8")
    ponte = (RAIZ / "painel" / "src" / "componentes" / "PonteControleIA.tsx").read_text(encoding="utf-8")
    assert "/api/controle-ia/publico" in ponte and "Não achamos este contato na IA" in ponte


@pg
async def test_link_da_conversa_sem_login(ambiente, monkeypatch):  # noqa: F811
    cliente, _simulada, email_admin, banco = ambiente
    cliente._transport.app.include_router(ci.api)
    pool = banco._pool
    ci._pedidos.clear()
    await _entrar(cliente, email_admin, "senha-admin-123")
    marca = uuid.uuid4().hex[:6]
    esc, _h, canal, agente, conta = await _semear(cliente, pool, f"Link IA {marca}")
    _esc2, _h2, _c2, _a2, conta2 = await _semear(cliente, pool, f"Link IA outro {marca}")
    fone = "55439" + str(uuid.uuid4().int)[:8]
    sessao, contato_ext = f"sess-l-{marca}", f"cont-l-{marca}"
    id_lead = await _lead(pool, esc, canal, agente, f"Ana Link {marca}", fone, sessao, contato_ext)
    usuario_plataforma = str(uuid.uuid4())
    await pool.execute(
        """insert into agentesia_usuarios (email, nome, senha_hash, papel, id_escritorio, id_usuario_helena)
           values ($1, 'Bruna Atendente', 'x', 'atendente', $2::uuid, $3)""",
        f"bruna-{marca}@exemplo.com", esc, usuario_plataforma)
    cliente.cookies.clear()                                    # o link funciona sem sessão do painel

    def q(**extra):
        return {"id_da_conta": conta, "id_do_atendimento": sessao, "id_do_contato": "{{id_do_contato}}",
                "telefone_do_contato": fone, **extra}

    # Conta certa: acha pelo atendimento, sem devolver o id do lead nem o telefone inteiro.
    r = await cliente.get("/api/controle-ia/publico/lead", params=q())
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["por"] == "sessao" and d["ia_ligada"] is True and "id_lead" not in d and fone not in r.text
    # Sem atendimento: pelo telefone.
    assert (await cliente.get("/api/controle-ia/publico/lead",
                              params=q(id_do_atendimento=""))).json()["por"] == "telefone"
    # Conta de outro escritório: o lead não existe lá.
    r = await cliente.get("/api/controle-ia/publico/lead", params=q(id_da_conta=conta2))
    assert r.status_code == 404 and "não tem lead" in r.json()["detail"]
    # Conta desconhecida, inválida ou ausente.
    r = await cliente.get("/api/controle-ia/publico/lead", params=q(id_da_conta=str(uuid.uuid4())))
    assert r.status_code == 404 and "não está ligada" in r.json()["detail"]
    assert (await cliente.get("/api/controle-ia/publico/lead", params=q(id_da_conta="abc"))).status_code == 404
    r = await cliente.get("/api/controle-ia/publico/lead", params=q(id_da_conta="{{id_da_conta}}"))
    assert r.status_code == 400 and "id_da_conta" in r.json()["detail"]
    # Sem dados da conversa.
    assert (await cliente.get("/api/controle-ia/publico/lead", params={"id_da_conta": conta})).status_code == 400
    # id_lead vindo do navegador é ignorado: sem os dados da conversa nada muda.
    r = await cliente.post("/api/controle-ia/publico/desativar", json={"id_da_conta": conta, "id_lead": id_lead})
    assert r.status_code == 400
    assert await _notas(pool, id_lead) == 0

    # Desativar pelo link (2 h) com o atendente da plataforma: nota e histórico dizem "pelo link da conversa".
    corpo = {"id_da_conta": conta, "id_do_atendimento": sessao, "id_do_contato": contato_ext,
             "telefone_do_contato": fone, "id_do_usuario": usuario_plataforma}
    r = await cliente.post("/api/controle-ia/publico/desativar", json={**corpo, "minutos": 120})
    assert r.status_code == 200, r.text
    assert r.json()["mudou"] is True and r.json()["lead"]["ia_ligada"] is False and "id_lead" not in r.json()["lead"]
    nota = await pool.fetchval(
        "select dados->>'texto' from agentesia_acoes where id_lead = $1::uuid and tipo = 'nota'", id_lead)
    assert "pelo link da conversa (Bruna Atendente)" in nota and "120 min" in nota
    alteracao = await pool.fetchrow(
        """select id_usuario, resumo, depois from agentesia_alteracoes
           where id_registro = $1::uuid and acao = 'desligou_ia'""", id_lead)
    assert "pelo link da conversa" in alteracao["resumo"] and alteracao["id_usuario"] is not None
    assert usuario_plataforma in str(alteracao["depois"]) and '"link"' in str(alteracao["depois"])
    # Repetido logo em seguida: sem nota nova.
    r = await cliente.post("/api/controle-ia/publico/desativar", json={**corpo, "minutos": 120})
    assert r.json()["mudou"] is False and await _notas(pool, id_lead) == 1
    # Pela conta de outro escritório não mexe.
    r = await cliente.post("/api/controle-ia/publico/reativar", json={**corpo, "id_da_conta": conta2})
    assert r.status_code == 404 and await _notas(pool, id_lead) == 1

    # Reativar sem id_do_usuario preenchido: nota "pelo link da conversa", sem nome.
    r = await cliente.post("/api/controle-ia/publico/reativar", json={**corpo, "id_do_usuario": "{{id_do_usuario}}"})
    assert r.status_code == 200 and r.json()["mudou"] is True and r.json()["lead"]["ia_ligada"] is True
    notas = [x["t"] for x in await pool.fetch(
        "select dados->>'texto' as t from agentesia_acoes where id_lead = $1::uuid and tipo = 'nota' order by criado_em",
        id_lead)]
    assert len(notas) == 2 and "religada" in notas[1] and "pelo link da conversa." in notas[1]

    # Conversa encerrada: mensagem clara.
    fone2 = "55439" + str(uuid.uuid4().int)[:8]
    await _lead(pool, esc, canal, agente, f"Encerrado Link {marca}", fone2, estado="encerrado")
    r = await cliente.post("/api/controle-ia/publico/desativar", json={"id_da_conta": conta, "telefone_do_contato": fone2})
    assert r.status_code == 409 and "encerrada" in r.json()["detail"]

    # Limite de taxa por conta (a outra conta segue livre).
    ci._pedidos.clear()
    monkeypatch.setattr(ci, "LIMITE_POR_CONTA", 3)
    codigos = [(await cliente.get("/api/controle-ia/publico/lead", params=q())).status_code for _ in range(4)]
    assert codigos == [200, 200, 200, 429]
    assert (await cliente.get("/api/controle-ia/publico/lead", params=q(id_da_conta=conta2))).status_code == 404
    # Limite por IP (contas inventadas não escapam).
    ci._pedidos.clear()
    monkeypatch.setattr(ci, "LIMITE_POR_IP", 2)
    codigos = [(await cliente.get("/api/controle-ia/publico/lead", params=q(id_da_conta=str(uuid.uuid4())))).status_code
               for _ in range(3)]
    assert codigos == [404, 404, 429]
    ci._pedidos.clear()
