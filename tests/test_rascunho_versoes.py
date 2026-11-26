"""Testar o rascunho antes de publicar e versões dos prompts (app/gestao/rotas_rascunho.py e app/gestao/versoes.py).

Laboratório do rascunho: o motor real (modo laboratório, em memória) roda com o conteúdo que está na tela, sem
número e sem Helena; cada resposta traz etapa, fatos, travas, troca e custo em R$; respeita o "pode gastar?" e o
modelo falso não gasta. Versões: gravar ao ativar e salvar, listar, diferença, restaurar (não publica), permissões e
outro escritório não vê. Só roda com AGENTESIA_TESTE_PG_URL (banco local). A Helena é simulada; a IA é falsa.
"""

import os
import uuid
from dataclasses import replace

import pytest

from app import cobranca
from app.gestao import seguranca, versoes
from app.gestao.laboratorio import Laboratorios
from app.gestao.rotas_rascunho import api as api_rascunho
from app.modelo import ModeloFalso, Resultado
from tests.test_gestao import _entrar, ambiente  # noqa: F401  (fixture do painel com a Helena simulada)
from tests.test_lixeira_solta_numero import _escritorio, _payload, _produto
from tests.test_turno import extrai, fala

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
pytestmark = pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")


def _app(cliente):
    app = cliente._transport.app
    if not any(getattr(r, "path", "").endswith("/laboratorio/recomecar") for r in app.router.routes):
        app.include_router(api_rascunho)
    return app


class ModeloPago:
    """Responde como o falso, mas a chamada sai como de um modelo de verdade, com custo (para testar a cobrança)."""

    def __init__(self, falso: ModeloFalso, custo_usd: float = 0.01) -> None:
        self._falso = falso
        self._custo = custo_usd

    async def gerar(self, **kw):
        r = await self._falso.gerar(**kw)
        return Resultado(dados=r.dados, chamadas=[replace(c, modelo="gpt-4.1-mini", custo_usd=self._custo) for c in r.chamadas])


def _modelo(respostas_etapa=None):
    return ModeloFalso({
        "extrator": lambda _s, _c: extrai([("acidente_descricao", "caí da moto", "caí da moto")]),
        "etapa": respostas_etapa or (lambda _s, _c: fala("Entendi. Ficou com alguma sequela?")),
    })


def _rascunho(agentes, marca):
    """O payload que a tela manda: os prompts AINDA NÃO salvos levam uma marca para achar no prompt enviado à IA."""
    editados = [{**a, "prompt": f"{a['prompt']} [{marca}-{a['papel']}]"} for a in agentes]
    return {"nome": "Júlia", "agentes": editados, "faq": [{"pergunta": "Quanto custa?", "resposta": f"30% no êxito {marca}"}],
            "objecoes": [], "regras_markdown": f"Regra do rascunho {marca}", "dados_escritorio": ""}


async def test_laboratorio_roda_o_motor_com_o_rascunho_sem_numero_e_sem_gastar(ambiente):
    cliente, _simulada, email_admin, banco = ambiente
    app = _app(cliente)
    pool = banco._pool
    await _entrar(cliente, email_admin, "senha-admin-123")
    _esc1, h1, _zapi, _oficial = await _escritorio(cliente, pool, "Lab Rascunho 1", "token-bom-111111")
    _esc2, h2, _z2, _o2 = await _escritorio(cliente, pool, "Lab Rascunho 2", "token-bom-222222")
    id_produto, agentes = await _produto(cliente, h1, "Rascunho")      # nunca ativado: sem agente e sem número
    vezes = {"n": 0}

    def etapa(_s, _c):                     # a 1ª resposta promete resultado (a trava barra) e a IA refaz
        vezes["n"] += 1
        return fala("Você vai receber o benefício com certeza, é garantido!" if vezes["n"] == 1 else "Entendi. Ficou com alguma sequela?")
    falso = _modelo(etapa)
    app.state.laboratorios = Laboratorios(falso, app.state.cfg)

    info = (await cliente.get(f"/api/produtos-ativados/{id_produto}/laboratorio", headers=h1)).json()
    assert info["gasta_creditos"] is False and info["modelo_falso"] is True and info["pode_gastar"] is True

    rascunho = _rascunho(agentes, "R1")
    r = await cliente.post(f"/api/produtos-ativados/{id_produto}/laboratorio", headers=h1,
                           json={"texto": "oi, caí da moto ano passado", "rascunho": rascunho})
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["etapa"] == "sdr" and corpo["etapa_nome"]
    assert [m["texto"] for m in corpo["mensagens"]] == ["Entendi. Ficou com alguma sequela?"]
    assert corpo["fatos"].get("acidente_descricao") == "caí da moto"
    assert any(f["chave"] == "acidente_descricao" for f in corpo["fatos_novos"])
    assert corpo["travas"] and all(t["codigo"] and t["orientacao"] for t in corpo["travas"]), corpo["travas"]
    assert corpo["troca"] is None and corpo["custo_brl"] == 0 and corpo["gastou"] is False and corpo["chamadas"] >= 2
    # O prompt que foi à IA é o do RASCUNHO (não salvo), com FAQ e regras da tela.
    sistemas = "\n".join(p["sistema"] for p in falso.pedidos if p["papel"] == "etapa")
    assert "[R1-sdr]" in sistemas and "Regra do rascunho R1" in sistemas and "30% no êxito R1" in sistemas

    # A mesma conversa continua; o rascunho editado vale na mensagem seguinte.
    r2 = await cliente.post(f"/api/produtos-ativados/{id_produto}/laboratorio", headers=h1,
                            json={"texto": "fiquei com dor no joelho", "id_conversa": corpo["id_conversa"], "rascunho": _rascunho(agentes, "R2")})
    assert r2.status_code == 200 and r2.json()["id_conversa"] == corpo["id_conversa"]
    assert "[R2-sdr]" in falso.pedidos[-1]["sistema"]

    # Nada foi gravado: nem lead, nem conversa, nem chamada (modelo falso não gasta).
    assert not await pool.fetchval("select count(*) from agentesia_leads where id_escritorio = $1::uuid", _esc1)
    assert not await pool.fetchval("select count(*) from agentesia_chamadas_ia where id_escritorio = $1::uuid", _esc1)
    assert (await cliente.get(f"/api/produtos-ativados/{id_produto}", headers=h1)).json()["id_agente"] is None

    # Recomeçar / começar em outra etapa (lead novo = a principal).
    assert (await cliente.post(f"/api/produtos-ativados/{id_produto}/laboratorio/recomecar", headers=h1,
                               json={"id_conversa": corpo["id_conversa"]})).status_code == 200
    closer = await cliente.post(f"/api/produtos-ativados/{id_produto}/laboratorio", headers=h1,
                                json={"texto": "quanto vou pagar?", "id_conversa": corpo["id_conversa"], "etapa_inicial": "closer",
                                      "rascunho": rascunho})
    assert closer.status_code == 200, closer.text
    assert closer.json()["etapa"] == "closer" and closer.json()["id_conversa"] != corpo["id_conversa"]
    ruim = await cliente.post(f"/api/produtos-ativados/{id_produto}/laboratorio", headers=h1,
                              json={"texto": "oi", "etapa_inicial": "inexistente", "rascunho": rascunho})
    assert ruim.status_code == 400
    assert (await cliente.post(f"/api/produtos-ativados/{id_produto}/laboratorio", headers=h1,
                               json={"texto": "oi", "rascunho": {**rascunho, "agentes": []}})).status_code == 400

    # Outro escritório não testa o produto deste; atendente não testa.
    assert (await cliente.post(f"/api/produtos-ativados/{id_produto}/laboratorio", headers=h2,
                               json={"texto": "oi", "rascunho": rascunho})).status_code == 404
    assert (await cliente.post(f"/api/produtos-ativados/{id_produto}/laboratorio", headers={**h1, "x-visao": "atendente"},
                               json={"texto": "oi", "rascunho": rascunho})).status_code == 403


async def test_laboratorio_com_ia_de_verdade_gasta_creditos_e_respeita_o_saldo(ambiente):
    cliente, _simulada, email_admin, banco = ambiente
    app = _app(cliente)
    pool = banco._pool
    await _entrar(cliente, email_admin, "senha-admin-123")
    esc, h, zapi, _oficial = await _escritorio(cliente, pool, "Lab Pago", "token-bom-333333")
    id_produto, agentes = await _produto(cliente, h, "Pago")
    ativado = await cliente.post(f"/api/produtos-ativados/{id_produto}/ativar", headers=h, json=_payload(agentes, zapi))
    assert ativado.status_code == 200, ativado.text
    app.state.laboratorios = Laboratorios(ModeloPago(_modelo()), app.state.cfg)
    await pool.execute("insert into agentesia_carteiras (id_escritorio, modo) values ($1::uuid, 'pre_pago')", esc)
    cobranca.esquecer()

    info = (await cliente.get(f"/api/produtos-ativados/{id_produto}/laboratorio", headers=h)).json()
    assert info["gasta_creditos"] is True and info["pode_gastar"] is False and info["aviso"]
    sem = await cliente.post(f"/api/produtos-ativados/{id_produto}/laboratorio", headers=h,
                             json={"texto": "oi", "rascunho": _rascunho(agentes, "P")})
    assert sem.status_code == 402 and "saldo" in sem.json()["detail"].lower()

    await cobranca.lancar(pool, esc, "recarga", 50, motivo="teste do laboratório")
    r = await cliente.post(f"/api/produtos-ativados/{id_produto}/laboratorio", headers=h,
                           json={"texto": "oi, caí da moto", "rascunho": _rascunho(agentes, "P")})
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["gastou"] is True and corpo["custo_brl"] > 0
    linhas = await pool.fetch("select origem, custo_brl::float8 as brl, cobranca from agentesia_chamadas_ia where id_escritorio = $1::uuid", esc)
    assert linhas and all(l["origem"] == "laboratorio" and l["cobranca"] == "pendente" for l in linhas)
    assert round(sum(l["brl"] for l in linhas), 4) == corpo["custo_brl"]
    # O teste não mexe no agente no ar nem cria lead.
    assert not await pool.fetchval("select count(*) from agentesia_leads where id_escritorio = $1::uuid", esc)
    cobranca.esquecer()


async def test_versoes_gravar_listar_diferenca_restaurar_e_permissoes(ambiente):
    cliente, _simulada, email_admin, banco = ambiente
    _app(cliente)
    pool = banco._pool
    versoes.esquecer_cache()
    await _entrar(cliente, email_admin, "senha-admin-123")
    esc1, h1, zapi, _oficial = await _escritorio(cliente, pool, "Versões 1", "token-bom-444444")
    esc2, h2, zapi2, _o2 = await _escritorio(cliente, pool, "Versões 2", "token-bom-555555")
    id_produto, agentes = await _produto(cliente, h1, "Versões")

    # Ativar grava a versão 1.
    ativado = await cliente.post(f"/api/produtos-ativados/{id_produto}/ativar", headers=h1,
                                 json=_payload(agentes, zapi, faq=[{"pergunta": "Custa?", "resposta": "30%"}], regras_markdown="Regra 1"))
    assert ativado.status_code == 200, ativado.text
    assert ativado.json()["versao"]["numero"] == 1
    lista = (await cliente.get(f"/api/produtos-ativados/{id_produto}/versoes", headers=h1)).json()
    assert lista["disponivel"] is True and [v["numero"] for v in lista["versoes"]] == [1]
    assert lista["versoes"][0]["origem"] == "ativou" and lista["versoes"][0]["resumo"] == ["Versão inicial (ativação)"]
    assert lista["versoes"][0]["autor"] == "Equipe" and lista["versoes"][0]["faq"] == 1

    # Salvar sem mexer no conteúdo (só comportamento): não vira versão nova.
    igual = await cliente.post(f"/api/produtos-ativados/{id_produto}/sincronizar", headers=h1,
                               json=_payload(agentes, zapi, faq=[{"pergunta": "Custa?", "resposta": "30%"}], regras_markdown="Regra 1",
                                             temperatura=0.3))
    assert igual.status_code == 200 and igual.json()["versao"] is None

    # Salvar com prompt do Closer, FAQ e regras novos: versão 2 com o resumo calculado aqui.
    editados = [{**a, "prompt": a["prompt"] + " (novo)"} if a["papel"] == "closer" else a for a in agentes]
    faq2 = [{"pergunta": "Custa?", "resposta": "30%"}, {"pergunta": "Demora?", "resposta": "Uns meses"}]
    v2 = await cliente.post(f"/api/produtos-ativados/{id_produto}/sincronizar", headers=h1,
                            json=_payload(editados, zapi, faq=faq2, regras_markdown="Regra 2"))
    assert v2.status_code == 200, v2.text
    assert v2.json()["versao"]["numero"] == 2
    resumo = v2.json()["versao"]["resumo"]
    assert any(l.startswith("Prompt do") for l in resumo) and "FAQ (+1)" in resumo and "Regras gerais" in resumo

    # O resumo que o assistente manda (antes/depois da Revisão) é o que fica.
    v3 = await cliente.post(f"/api/produtos-ativados/{id_produto}/sincronizar", headers=h1,
                            json=_payload(agentes, zapi, faq=faq2, regras_markdown="Regra 3",
                                          resumo_mudancas=["Regras gerais", "Prompt do Closer"]))
    assert v3.json()["versao"] == {"numero": 3, "resumo": ["Regras gerais", "Prompt do Closer"]}
    salvo = (await cliente.get(f"/api/produtos-ativados/{id_produto}", headers=h1)).json()
    assert "resumo_mudancas" not in (salvo.get("rascunho") or {}).get("payload_ativacao", {})

    lista = (await cliente.get(f"/api/produtos-ativados/{id_produto}/versoes", headers=h1)).json()["versoes"]
    assert [v["numero"] for v in lista] == [3, 2, 1] and all(v["criado_em"] for v in lista)

    # Ver diferenças: v2 contra a anterior (v1), e contra uma escolhida.
    d2 = (await cliente.get(f"/api/produtos-ativados/{id_produto}/versoes/2", headers=h1)).json()
    assert d2["comparada_com"] == 1
    chaves = {d["chave"]: d for d in d2["diferencas"]}
    assert chaves["agente.closer.prompt"]["depois"].endswith("(novo)") and not chaves["agente.closer.prompt"]["antes"].endswith("(novo)")
    assert chaves["regras_markdown"] == {**chaves["regras_markdown"], "antes": "Regra 1", "depois": "Regra 2"}
    assert chaves["faq"]["quantos_antes"] == 1 and chaves["faq"]["quantos_depois"] == 2
    d31 = (await cliente.get(f"/api/produtos-ativados/{id_produto}/versoes/3?com=1", headers=h1)).json()
    assert d31["comparada_com"] == 1 and "agente.closer.prompt" not in {d["chave"] for d in d31["diferencas"]}
    d1 = (await cliente.get(f"/api/produtos-ativados/{id_produto}/versoes/1", headers=h1)).json()
    assert d1["comparada_com"] is None and d1["diferencas"]
    assert (await cliente.get(f"/api/produtos-ativados/{id_produto}/versoes/9", headers=h1)).status_code == 404

    # Restaurar a v2: devolve o conteúdo para o rascunho e NÃO publica (o agente no ar continua com a v3).
    antes = await pool.fetchval("select instrucao from agentesia_agente_etapas e join agentesia_produtos_ativados p on p.id_agente = e.id_agente "
                                "where p.id = $1::uuid and e.codigo = 'closer'", id_produto)
    restaurada = await cliente.post(f"/api/produtos-ativados/{id_produto}/versoes/2/restaurar", headers=h1)
    assert restaurada.status_code == 200, restaurada.text
    conteudo = restaurada.json()["conteudo"]
    assert next(a for a in conteudo["agentes"] if a["papel"] == "closer")["prompt"].endswith("(novo)")
    assert conteudo["regras_markdown"] == "Regra 2" and len(conteudo["faq"]) == 2 and "Confira e salve" in restaurada.json()["aviso"]
    depois = await pool.fetchval("select instrucao from agentesia_agente_etapas e join agentesia_produtos_ativados p on p.id_agente = e.id_agente "
                                 "where p.id = $1::uuid and e.codigo = 'closer'", id_produto)
    assert depois == antes and not depois.endswith("(novo)")
    assert len((await cliente.get(f"/api/produtos-ativados/{id_produto}/versoes", headers=h1)).json()["versoes"]) == 3
    # Salvar o restaurado publica como versão nova (4), sem apagar as antigas.
    v4 = await cliente.post(f"/api/produtos-ativados/{id_produto}/sincronizar", headers=h1,
                            json=_payload(conteudo["agentes"], zapi, faq=conteudo["faq"], objecoes=conteudo["objecoes"],
                                          regras_markdown=conteudo["regras_markdown"], dados_escritorio=conteudo["dados_escritorio"]))
    assert v4.json()["versao"]["numero"] == 4
    d4 = (await cliente.get(f"/api/produtos-ativados/{id_produto}/versoes/4?com=2", headers=h1)).json()
    assert d4["diferencas"] == []

    # Outro escritório não vê nem restaura; atendente não vê.
    assert (await cliente.get(f"/api/produtos-ativados/{id_produto}/versoes", headers=h2)).status_code == 404
    assert (await cliente.get(f"/api/produtos-ativados/{id_produto}/versoes/1", headers=h2)).status_code == 404
    assert (await cliente.post(f"/api/produtos-ativados/{id_produto}/versoes/1/restaurar", headers=h2)).status_code == 404
    assert (await cliente.get(f"/api/produtos-ativados/{id_produto}/versoes", headers={**h1, "x-visao": "atendente"})).status_code == 403
    # Mesmo pelo id do produto do outro escritório no próprio cabeçalho, a versão de lá não aparece aqui.
    id_outro, agentes_outro = await _produto(cliente, h2, "Outro")
    assert (await cliente.post(f"/api/produtos-ativados/{id_outro}/ativar", headers=h2, json=_payload(agentes_outro, zapi2))).status_code == 200
    assert [v["numero"] for v in (await cliente.get(f"/api/produtos-ativados/{id_outro}/versoes", headers=h2)).json()["versoes"]] == [1]
    assert await pool.fetchval("select count(*) from agentesia_produto_versoes where id_escritorio = $1::uuid", esc2) == 1
    assert await pool.fetchval("select count(*) from agentesia_produto_versoes where id_escritorio = $1::uuid", esc1) == 4

    # Gestor do escritório 2 (sem x-escritorio): vê as do dele e não as do 1.
    email = f"gestor-{uuid.uuid4().hex[:6]}@escritorio.com"
    await pool.execute("insert into agentesia_usuarios (email, nome, senha_hash, papel, id_escritorio) values ($1, 'Gestora', $2, 'gestor', $3::uuid)",
                       email, seguranca.gerar_hash("senha-gestor-123"), esc2)
    await _entrar(cliente, email, "senha-gestor-123")
    assert (await cliente.get(f"/api/produtos-ativados/{id_produto}/versoes")).status_code == 404
    assert (await cliente.get(f"/api/produtos-ativados/{id_outro}/versoes")).status_code == 200


async def test_sem_a_008_nada_quebra(ambiente, monkeypatch):
    cliente, _simulada, email_admin, banco = ambiente
    _app(cliente)
    pool = banco._pool
    await _entrar(cliente, email_admin, "senha-admin-123")
    _esc, h, zapi, _oficial = await _escritorio(cliente, pool, "Sem 008", "token-bom-666666")
    id_produto, agentes = await _produto(cliente, h, "Sem")

    async def sem(_conexao):
        return False
    monkeypatch.setattr(versoes, "tem_versoes", sem)
    ativado = await cliente.post(f"/api/produtos-ativados/{id_produto}/ativar", headers=h, json=_payload(agentes, zapi))
    assert ativado.status_code == 200 and ativado.json()["versao"] is None
    assert (await cliente.get(f"/api/produtos-ativados/{id_produto}/versoes", headers=h)).json() == {"disponivel": False, "versoes": []}
    assert (await cliente.get(f"/api/produtos-ativados/{id_produto}/versoes/1", headers=h)).status_code == 404


def test_diferencas_e_resumo():
    a = versoes.conteudo(agentes=[{"papel": "sdr", "nome": "SDR", "prompt": "a"}, {"papel": "closer", "prompt": "b"}],
                         faq=[{"q": "x", "a": "y"}], objecoes=[], regras_markdown="r", dados_escritorio=None)
    b = versoes.conteudo(agentes=[{"papel": "sdr", "nome": "SDR", "prompt": "a2", "mensagem_troca": "vou te passar"},
                                  {"papel": "periododegraca", "prompt": "pg"}],
                         faq=[], objecoes=[{"gatilho": "caro", "resposta": "parcela"}], regras_markdown="r", dados_escritorio="")
    assert a["faq"] == [{"pergunta": "x", "resposta": "y"}] and b["objecoes"] == [{"titulo": "caro", "resposta": "parcela"}]
    assert [x["papel"] for x in b["agentes"]] == ["sdr", "periododegraca"]            # na ordem do funil
    itens = versoes.diferencas(a, b)
    assert versoes.resumo(itens) == ["Prompt do SDR", "Frase de troca do SDR", "Agente Período de Graça entrou",
                                     "Agente Closer saiu", "FAQ (-1)", "Objeções (+1)"]
    assert versoes.diferencas(b, b) == []
    assert versoes.resumo(versoes.diferencas(None, a))[:2] == ["Agente SDR entrou", "Agente Closer entrou"]
