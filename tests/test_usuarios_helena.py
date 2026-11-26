"""Usuários da conta na LawChat → agentesia_usuarios (app/gestao/usuarios_helena.py).

Criar, atualizar, desativar, não tocar na equipe LawChat, casar por e-mail, idempotente, paginação e erro legível.
Só roda com AGENTESIA_TESTE_PG_URL (banco local: node db/testes/servidor_local.mjs). A Helena é falsa
(httpx.MockTransport, a mesma de tests/test_conta_helena.py): nenhuma chamada sai da máquina.
"""

import json
import os
import uuid

import httpx
import pytest

from app.canal.helena_conta import ErroHelenaApi, HelenaConta
from app.gestao import seguranca, usuarios_helena
from tests.test_conta_helena import _criar, ambiente  # noqa: F401 — fixture

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")


def _u(nome: str, email: str | None, perfil: str | None = "AGENT", **extra) -> dict:
    sufixo = uuid.uuid4().hex[:8]
    return {"id": f"a-{sufixo}", "userId": f"u-{sufixo}", "name": nome, "email": email,
            **({"profile": perfil} if perfil else {}), **extra}


async def _locais(banco, id_escritorio: str) -> dict[str, dict]:
    linhas = await banco._pool.fetch(
        """select id::text as id, email, nome, papel, ativo, id_usuario_helena, senha_hash, trocar_senha
           from agentesia_usuarios where id_escritorio = $1::uuid""", id_escritorio)
    return {(l["id_usuario_helena"] or l["email"]): dict(l) for l in linhas}


async def _sincronizar(cliente, id_escritorio: str) -> dict:
    resposta = await cliente.post(f"/api/admin/escritorios/{id_escritorio}/sincronizar")
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


# ------------------------------------------------------------------------------------------- sem banco
def test_papel_da_lawchat():
    assert usuarios_helena.papel_da_lawchat({"profile": "ADMIN"}) == "gestor"
    assert usuarios_helena.papel_da_lawchat({"profile": "AGENT", "isOwner": True}) == "gestor"
    assert usuarios_helena.papel_da_lawchat({"profile": "agent"}) == "atendente"
    assert usuarios_helena.papel_da_lawchat({"profile": "SUPERVISOR"}) == "atendente"
    assert usuarios_helena.papel_da_lawchat({}) is None
    assert usuarios_helena.papel_da_lawchat({"profile": "OUTRA_COISA"}) is None


async def test_listar_percorre_todas_as_paginas_com_timeout_curto():
    todos = [_u(f"Pessoa {i}", f"p{i}@x.com") for i in range(230)]
    pedidos: list[dict] = []

    def falsa(pedido: httpx.Request) -> httpx.Response:
        pagina, tamanho = int(pedido.url.params["PageNumber"]), int(pedido.url.params["PageSize"])
        pedidos.append({"pagina": pagina, "timeout": pedido.extensions.get("timeout")})
        lote = todos[(pagina - 1) * tamanho: pagina * tamanho]
        return httpx.Response(200, json={"items": lote, "hasMorePages": pagina * tamanho < len(todos)})

    helena = HelenaConta("t", http=httpx.AsyncClient(transport=httpx.MockTransport(falsa)))
    lista = await usuarios_helena.listar(helena)
    assert len(lista) == 230 and [p["pagina"] for p in pedidos] == [1, 2, 3]
    assert pedidos[0]["timeout"]["read"] == usuarios_helena.TIMEOUT_S

    # Resposta em lista que ignora a paginação: para na segunda página (ninguém novo), sem repetir.
    def ignora(pedido: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=todos[:100])
    lista = await usuarios_helena.listar(HelenaConta("t", http=httpx.AsyncClient(transport=httpx.MockTransport(ignora))))
    assert len(lista) == 100

    # Erro vira texto legível.
    def recusa(pedido: httpx.Request) -> httpx.Response:
        return httpx.Response(401)
    with pytest.raises(ErroHelenaApi) as erro:
        await usuarios_helena.listar(HelenaConta("t", http=httpx.AsyncClient(transport=httpx.MockTransport(recusa))))
    assert usuarios_helena.erro_legivel(erro.value) == "a LawChat recusou o token"


# ------------------------------------------------------------------------------------------- com banco
pytestmark_banco = pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")


@pytestmark_banco
async def test_cria_atualiza_desativa_e_e_idempotente(ambiente):  # noqa: F811
    cliente, falsa, banco = ambiente
    token = "token-bom-" + uuid.uuid4().hex[:8]
    conta = falsa.conta(token)
    dona = _u("Dra. Ana", f"ana-{uuid.uuid4().hex[:6]}@esc.com", "ADMIN", isOwner=True)
    joao = _u("João", f"joao-{uuid.uuid4().hex[:6]}@esc.com", "AGENT")
    sem_perfil = _u("Sem Perfil", None, None)
    conta["usuarios"] = [dona, joao, sem_perfil]
    id_escritorio = (await _criar(cliente, token)).json()["escritorio"]["id"]

    feita = await _sincronizar(cliente, id_escritorio)
    assert {k: feita["usuarios"][k] for k in ("criados", "atualizados", "desativados")} == \
        {"criados": 3, "atualizados": 0, "desativados": 0}
    locais = await _locais(banco, id_escritorio)
    assert locais[dona["userId"]]["papel"] == "gestor" and locais[dona["userId"]]["email"] == dona["email"]
    assert locais[joao["userId"]]["papel"] == "atendente" and locais[joao["userId"]]["nome"] == "João"
    # Sem perfil: o padrão do login integrado (gestor); sem e-mail: o e-mail de reserva do login integrado.
    assert locais[sem_perfil["userId"]]["papel"] == "gestor"
    assert locais[sem_perfil["userId"]]["email"].endswith(".helena.local")
    # Sem senha: entram pelo login da LawChat; nenhuma senha confere.
    for linha in locais.values():
        assert linha["senha_hash"] == usuarios_helena.SEM_SENHA and linha["trocar_senha"] is False
        assert not seguranca.conferir_senha("", linha["senha_hash"])
    entrar = await cliente.post("/api/entrar", json={"email": dona["email"], "senha": usuarios_helena.SEM_SENHA})
    assert entrar.status_code != 200

    # Idempotente: a segunda vez não muda nada.
    de_novo = await _sincronizar(cliente, id_escritorio)
    assert (de_novo["usuarios"]["criados"], de_novo["usuarios"]["atualizados"], de_novo["usuarios"]["desativados"]) == (0, 0, 0)
    assert len(await _locais(banco, id_escritorio)) == 3

    # Atualiza nome, e-mail e papel.
    joao.update(name="João Silva", email=f"joao.silva-{uuid.uuid4().hex[:6]}@esc.com", profile="ADMIN")
    feita = await _sincronizar(cliente, id_escritorio)
    assert (feita["usuarios"]["criados"], feita["usuarios"]["atualizados"], feita["usuarios"]["desativados"]) == (0, 1, 0)
    linha = (await _locais(banco, id_escritorio))[joao["userId"]]
    assert (linha["nome"], linha["email"], linha["papel"]) == ("João Silva", joao["email"], "gestor")

    # Saiu da LawChat: desativa, não apaga. Voltou: reativa.
    conta["usuarios"].remove(joao)
    feita = await _sincronizar(cliente, id_escritorio)
    assert feita["usuarios"]["desativados"] == 1
    linha = (await _locais(banco, id_escritorio))[joao["userId"]]
    assert linha["ativo"] is False
    conta["usuarios"].append(joao)
    feita = await _sincronizar(cliente, id_escritorio)
    assert feita["usuarios"]["atualizados"] == 1
    assert (await _locais(banco, id_escritorio))[joao["userId"]]["ativo"] is True

    # Histórico sem e-mail.
    historico = await banco._pool.fetch(
        "select acao, resumo, antes, depois from agentesia_alteracoes where id_escritorio = $1::uuid and tabela = 'agentesia_usuarios'",
        id_escritorio)
    assert {h["acao"] for h in historico} >= {"criou", "alterou", "desativou"}
    texto = json.dumps([dict(h) for h in historico], ensure_ascii=False, default=str)
    assert "@esc.com" not in texto and "senha" not in texto.lower().replace("sem senha", "")
    sinc = await banco._pool.fetchval(
        """select resumo from agentesia_alteracoes where id_escritorio = $1::uuid and acao = 'sincronizou'
           order by criado_em desc limit 1""", id_escritorio)
    assert "logins:" in sinc


@pytestmark_banco
async def test_nao_toca_na_equipe_lawchat_nem_em_quem_foi_criado_no_painel(ambiente):  # noqa: F811
    cliente, falsa, banco = ambiente
    token = "token-bom-" + uuid.uuid4().hex[:8]
    conta = falsa.conta(token)
    equipe = await banco._pool.fetchrow(
        "select id::text as id, email, nome, papel, ativo from agentesia_usuarios where papel = 'admin_lawchat' order by criado_em desc limit 1")
    da_equipe = _u("Alguém da LawChat", equipe["email"], "ADMIN")
    cliente_x = _u("Cliente X", f"x-{uuid.uuid4().hex[:6]}@esc.com", "AGENT")
    conta["usuarios"] = [da_equipe, cliente_x]
    id_escritorio = (await _criar(cliente, token)).json()["escritorio"]["id"]
    # Criado só no painel, sem id da LawChat e com outro e-mail: nunca desativado.
    so_painel = f"so-painel-{uuid.uuid4().hex[:6]}@esc.com"
    await banco._pool.execute(
        """insert into agentesia_usuarios (email, nome, senha_hash, papel, id_escritorio)
           values ($1, 'Só no painel', 'x', 'gestor', $2::uuid)""", so_painel, id_escritorio)

    feita = await _sincronizar(cliente, id_escritorio)
    assert feita["usuarios"]["criados"] == 1 and feita["usuarios"]["ignorados"] == 1
    depois = await banco._pool.fetchrow(
        "select email, nome, papel, ativo, id_escritorio, id_usuario_helena from agentesia_usuarios where id = $1::uuid", equipe["id"])
    assert (depois["papel"], depois["nome"], depois["ativo"], depois["id_escritorio"], depois["id_usuario_helena"]) == \
        (equipe["papel"], equipe["nome"], True, None, None)
    locais = await _locais(banco, id_escritorio)
    assert set(locais) == {cliente_x["userId"], so_painel}

    # Todos saem da LawChat menos um: o do painel continua ativo; o que veio da LawChat é desativado.
    conta["usuarios"] = [da_equipe]
    feita = await _sincronizar(cliente, id_escritorio)
    locais = await _locais(banco, id_escritorio)
    assert locais[so_painel]["ativo"] is True and locais[cliente_x["userId"]]["ativo"] is False

    # Lista vazia (suspeita): ninguém é desativado.
    conta["usuarios"] = [cliente_x]
    await _sincronizar(cliente, id_escritorio)
    conta["usuarios"] = []
    feita = await _sincronizar(cliente, id_escritorio)
    assert feita["usuarios"]["desativados"] == 0 and feita["usuarios"]["aviso"]
    assert (await _locais(banco, id_escritorio))[cliente_x["userId"]]["ativo"] is True


@pytestmark_banco
async def test_casa_por_email_quem_foi_criado_no_painel(ambiente):  # noqa: F811
    cliente, falsa, banco = ambiente
    token = "token-bom-" + uuid.uuid4().hex[:8]
    conta = falsa.conta(token)
    email = f"gestora-{uuid.uuid4().hex[:6]}@esc.com"
    gestora = _u("Gestora da LawChat", email.upper(), "AGENT")
    conta["usuarios"] = [gestora]
    criado = (await _criar(cliente, token, email_gestor=email, nome_gestor="Gestora")).json()
    id_escritorio = criado["escritorio"]["id"]
    antes = await banco._pool.fetchrow("select id::text as id, senha_hash from agentesia_usuarios where email = $1", email)
    assert antes

    feita = await _sincronizar(cliente, id_escritorio)
    assert (feita["usuarios"]["criados"], feita["usuarios"]["atualizados"]) == (0, 1)
    depois = await banco._pool.fetchrow(
        "select id::text as id, id_usuario_helena, nome, papel, senha_hash from agentesia_usuarios where email = $1", email)
    assert depois["id"] == antes["id"] and depois["id_usuario_helena"] == gestora["userId"]
    assert depois["nome"] == "Gestora da LawChat" and depois["papel"] == "atendente"
    assert depois["senha_hash"] == antes["senha_hash"]           # quem tinha senha continua com ela
    assert await banco._pool.fetchval(
        "select count(*) from agentesia_usuarios where id_escritorio = $1::uuid", id_escritorio) == 1


@pytestmark_banco
async def test_onboarding_tem_o_passo_usuarios_opcional(ambiente):  # noqa: F811
    cliente, falsa, banco = ambiente
    token = "token-bom-" + uuid.uuid4().hex[:8]
    conta = falsa.conta(token)
    conta["usuarios"] = [_u("Dra. Beatriz", f"bia-{uuid.uuid4().hex[:6]}@esc.com", "ADMIN")]
    id_escritorio = (await _criar(cliente, token)).json()["escritorio"]["id"]
    base = f"/api/admin/escritorios/{id_escritorio}/onboarding"

    # Conferir só conta (não cria ninguém).
    conferido = (await cliente.post(f"{base}/conferir")).json()
    passo = next(p for p in conferido["passos"] if p["codigo"] == "usuarios")
    assert passo["situacao"] == "pendente" and "1 criados" in passo["detalhe"]
    assert "usuarios" not in conferido["obrigatorios"]
    assert not await _locais(banco, id_escritorio)

    # Avançar só o passo usuarios.
    avancado = (await cliente.post(f"{base}/avancar", json={"passos": ["usuarios"]})).json()
    passo = next(p for p in avancado["passos"] if p["codigo"] == "usuarios")
    assert passo["situacao"] == "feito" and passo["detalhe"].startswith("1 criados, 0 atualizados, 0 desativados")
    assert avancado["usuarios"]["criados"] == 1
    assert len(await _locais(banco, id_escritorio)) == 1

    # A LawChat falha: o passo vira aviso legível e não trava nada.
    falsa.falhar.add("/core/v1/agent")
    avancado = (await cliente.post(f"{base}/avancar", json={"passos": ["usuarios"]})).json()
    passo = next(p for p in avancado["passos"] if p["codigo"] == "usuarios")
    assert passo["situacao"] == "aviso" and "a LawChat não respondeu (erro_helena)" in passo["detalhe"]
