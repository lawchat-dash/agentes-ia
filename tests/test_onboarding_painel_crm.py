"""Onboarding da conta (Contas › Onboarding): etapa "Painel do CRM" com as etapas fixas, primeiro produto só informativo,
e o "Avançar" que quebrava (onboarding zerado + canais sem número ou com número repetido = UniqueViolation, erro 500).

Só roda com AGENTESIA_TESTE_PG_URL (banco local: node db/testes/servidor_local.mjs). A Helena é falsa
(httpx.MockTransport de tests/test_conta_helena.py): nenhuma chamada sai da máquina e a API interna nunca é chamada.
"""

import copy
import uuid

import pytest

from app.gestao import onboarding, painel_crm, sincronizar_conta
from tests.test_conta_helena import URL, _criar, ambiente  # noqa: F401  (fixture)

pytestmark = pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")


async def _conta(cliente, falsa, **mudar):
    token = "token-bom-" + uuid.uuid4().hex[:8]
    conta = falsa.conta(token)
    for chave, valor in mudar.items():
        conta[chave] = valor
    resposta = await _criar(cliente, token)
    assert resposta.status_code == 200, resposta.text
    id_escritorio = resposta.json()["escritorio"]["id"]
    return conta, id_escritorio, f"/api/admin/escritorios/{id_escritorio}"


def _situacao(resultado: dict) -> dict:
    return {p["codigo"]: p for p in resultado["passos"]}


def test_reconhece_o_painel_com_as_etapas_fixas():
    padrao = {"id": "p", "etapas": [{"id": f"e{i}", "titulo": t} for i, t in enumerate(
        ["📞SDR", "🛒 Comercial", "📄 Contrato em Elaboração", "✍️ Aguardando Assinatura", "✅ Contrato Assinado",
         "❌ Desqualificado", "Arquivo"])]}
    assert onboarding.etapas_do_painel_padrao(padrao) == {
        "SDR": "e0", "COMERCIAL": "e1", "CONTRATO": "e2", "AGUARDANDO_ASSINATURA": "e3", "CONTRATO_ASSINADO": "e4",
        "DESQUALIFICADO": "e5"}
    # Sem emoji e com outra caixa também vale; faltando uma etapa, não.
    sem_emoji = {"etapas": [{"id": str(i), "titulo": t} for i, t in enumerate(
        ["sdr", "COMERCIAL", "Contrato em Elaboracao", "Aguardando assinatura", "Contrato Assinado", "Desqualificado"])]}
    assert onboarding.etapas_do_painel_padrao(sem_emoji) is not None
    assert onboarding.etapas_do_painel_padrao({"etapas": padrao["etapas"][:5]}) is None
    assert onboarding.etapas_do_painel_padrao({"etapas": None}) is None


async def test_escolhe_sozinho_o_painel_com_as_etapas_fixas(ambiente):
    cliente, falsa, banco = ambiente
    conta, id_escritorio, base = await _conta(cliente, falsa)
    padrao = conta["paineis"][0]                                   # "🤖 CRM COMERCIAL IA" + "Comercial" + "Jurídico"
    sufixo = padrao["id"][3:]

    conferido = (await cliente.post(f"{base}/onboarding/conferir")).json()
    assert _situacao(conferido)["painel"]["situacao"] == "pendente"
    assert "é escolhido ao avançar" in _situacao(conferido)["painel"]["detalhe"]
    assert conferido["painel_sugerido"] == padrao["id"]
    assert [p["padrao"] for p in conferido["paineis"]] == [True, False, False]
    assert conferido["paineis"][0]["sugestao"]["SDR"] == f"w1-{sufixo}"
    assert "produto" not in conferido["obrigatorios"] and "painel" in conferido["obrigatorios"]

    avancado = (await cliente.post(f"{base}/onboarding/avancar", json={})).json()
    painel = _situacao(avancado)["painel"]
    assert painel["situacao"] == "feito" and "sozinho" in painel["detalhe"] and "6/6" in painel["detalhe"]
    esperado = {t: f"w{i}-{sufixo}" for i, t in enumerate(
        ["SDR", "COMERCIAL", "CONTRATO", "AGUARDANDO_ASSINATURA", "CONTRATO_ASSINADO", "DESQUALIFICADO"], 1)}
    ids = avancado["dados_helena"]["ids"]
    assert ids["id_painel"] == padrao["id"] and ids["etapas_por_tipo"] == esperado
    linha = await banco._pool.fetchrow(               # a integração crm (que o motor lê) também ficou com o painel
        "select config from agentesia_integracoes where id_escritorio = $1::uuid and tipo = 'crm'", id_escritorio)
    assert padrao["id"] in str(linha["config"])
    assert _situacao(avancado)["painel_padrao"]["situacao"] == "pulado"
    # A equipe da IA não é criada sem pedir (viraria a equipe PADRÃO da conta do cliente).
    assert ("POST", "/core/v1/department") not in falsa.pedidos
    assert _situacao(avancado)["equipe"]["situacao"] == "pendente"
    com_equipe = (await cliente.post(f"{base}/onboarding/avancar", json={"criar_equipe_ia": True})).json()
    assert _situacao(com_equipe)["equipe"]["situacao"] == "feito" and ("POST", "/core/v1/department") in falsa.pedidos


async def test_mais_de_um_candidato_ou_nenhum_pede_para_escolher(ambiente):
    cliente, falsa, banco = ambiente
    conta, id_escritorio, base = await _conta(cliente, falsa)
    copia = copy.deepcopy(conta["paineis"][0])
    copia["id"], copia["title"] = "p9-" + uuid.uuid4().hex[:8], "CRM antigo"
    for etapa in copia["steps"]:
        etapa["id"] = "x" + etapa["id"]
    conta["paineis"].append(copia)

    avancado = (await cliente.post(f"{base}/onboarding/avancar", json={})).json()
    painel = _situacao(avancado)["painel"]
    assert painel["situacao"] == "pendente" and "2 painéis têm as etapas padrão" in painel["detalhe"]
    assert "painel_sugerido" not in avancado and not avancado["dados_helena"].get("ids", {}).get("id_painel")

    # Escolha manual de um painel sem as etapas fixas, ligando as etapas pela tela.
    comercial = conta["paineis"][1]
    novo, proposta = comercial["steps"][1]["id"], comercial["steps"][0]["id"]
    escolhido = (await cliente.post(f"{base}/onboarding/avancar", json={
        "passos": ["painel"], "id_painel": comercial["id"], "etapas_por_tipo": {"SDR": novo, "COMERCIAL": proposta,
                                                                                "CONTRATO": "coluna-que-nao-existe"}})).json()
    painel = _situacao(escolhido)["painel"]
    assert painel["situacao"] == "aviso" and "2/6" in painel["detalhe"]
    assert escolhido["dados_helena"]["ids"]["id_painel"] == comercial["id"]
    assert escolhido["dados_helena"]["ids"]["etapas_por_tipo"] == {"SDR": novo, "COMERCIAL": proposta}

    # Nenhum painel com as etapas fixas: pede para escolher (não escolhe o único painel sozinho).
    _, _, base2 = await _conta(cliente, falsa, paineis=[copy.deepcopy(conta["paineis"][2])])
    sem = (await cliente.post(f"{base2}/onboarding/avancar", json={})).json()
    assert _situacao(sem)["painel"]["situacao"] == "pendente" and "nenhum dos 1" in _situacao(sem)["painel"]["detalhe"]


async def test_criacao_do_painel_padrao_desligada_explica_o_que_falta(ambiente, monkeypatch):
    cliente, falsa, banco = ambiente
    _, _, base = await _conta(cliente, falsa, paineis=[])
    monkeypatch.delenv("AGENTESIA_PAINEL_CRM_LIGADO", raising=False)
    for nome in painel_crm.VARIAVEIS.values():
        monkeypatch.delenv(nome, raising=False)
    conferido = (await cliente.post(f"{base}/onboarding/conferir")).json()
    assert conferido["painel_crm"]["criar_ligado"] is False
    assert set(conferido["painel_crm"]["falta_configurar"]) == set(painel_crm.VARIAVEIS.values())
    padrao = _situacao(conferido)["painel_padrao"]
    assert padrao["situacao"] == "pulado" and "AGENTESIA_PAINEL_CRM_LIGADO=1" in padrao["detalhe"]
    assert _situacao(conferido)["painel"]["situacao"] == "erro"           # sem painel nenhum na conta

    # Ligado, mas sem as variáveis: diz quais faltam (só os nomes) e não oferece criar.
    monkeypatch.setenv("AGENTESIA_PAINEL_CRM_LIGADO", "1")
    monkeypatch.setenv("AGENTESIA_HELENA_INTERNA_URL", "http://interna.invalid")
    conferido = (await cliente.post(f"{base}/onboarding/conferir")).json()
    assert conferido["painel_crm"]["criar_ligado"] is True
    assert "AGENTESIA_HELENA_INTERNA_URL" not in conferido["painel_crm"]["falta_configurar"]
    assert "AGENTESIA_HELENA_ADMIN_EMAIL" in _situacao(conferido)["painel_padrao"]["detalhe"]
    assert "interna.invalid" not in str(conferido)
    # A API interna nunca é chamada pelo conferir/avançar.
    assert not any("auth/v2" in caminho or "crm/v1/panel" in caminho for _, caminho in falsa.pedidos)


async def test_avancar_com_onboarding_zerado_e_canais_estranhos_nao_quebra(ambiente):
    """O bug do "Avançar": a conta (LawChat) tinha canais sem número (Instagram, Messenger) e o mesmo número duas vezes;
    o insert em agentesia_canais estourava UniqueViolation (id_escritorio, numero_normalizado) e a rota dava 500."""
    cliente, falsa, banco = ambiente
    conta, id_escritorio, base = await _conta(cliente, falsa)
    conta["canais"] += [
        {"id": "ig-" + uuid.uuid4().hex[:6], "active": True, "type": "Instagram", "number": None},
        {"id": "ms-" + uuid.uuid4().hex[:6], "active": True, "type": "Messenger", "number": ""},
        {"id": "dup-" + uuid.uuid4().hex[:6], "active": False, "type": "ZAPI_WhatsApp", "number": "5511912345678"},
    ]
    for zerado in ("'{}'::jsonb", "'\"{}\"'::jsonb", "'[]'::jsonb"):
        await banco._pool.execute(f"update agentesia_escritorios set onboarding = {zerado} where id = $1::uuid", id_escritorio)
        guardado = await cliente.get(f"{base}/onboarding")
        assert guardado.status_code == 200 and len(guardado.json()["passos"]) == len(onboarding.PASSOS)
        avancado = await cliente.post(f"{base}/onboarding/avancar", json={})
        assert avancado.status_code == 200, avancado.text
        passos = _situacao(avancado.json())
        assert passos["canais"]["situacao"] == "feito" and passos["sincronizacao"]["situacao"] == "feito"
    numeros = await banco._pool.fetch(
        "select numero_normalizado, ativo from agentesia_canais where id_escritorio = $1::uuid order by 1", id_escritorio)
    assert [(n["numero_normalizado"], n["ativo"]) for n in numeros] == [("5511912345678", True), ("5511987654321", True)]

    # Mesmo número reconectado na Helena (id de canal novo): o registro passa para o canal novo, sem duplicar.
    novo_id = "ch-novo-" + uuid.uuid4().hex[:6]
    conta["canais"][0]["id"] = novo_id
    assert (await cliente.post(f"{base}/sincronizar")).status_code == 200
    assert await banco._pool.fetchval(
        "select count(*) from agentesia_canais where id_escritorio = $1::uuid and id_canal_helena = $2", id_escritorio,
        novo_id) == 1
    assert (await cliente.post(f"{base}/onboarding/conferir")).status_code == 200


async def test_falha_inesperada_vira_texto_legivel(ambiente, monkeypatch):
    cliente, falsa, banco = ambiente
    _, id_escritorio, base = await _conta(cliente, falsa)

    async def quebra(**_):
        raise RuntimeError("algo deu errado")
    monkeypatch.setattr(sincronizar_conta, "sincronizar", quebra)
    avancado = await cliente.post(f"{base}/onboarding/avancar", json={})
    assert avancado.status_code == 200
    sinc = _situacao(avancado.json())["sincronizacao"]
    assert sinc["situacao"] == "aviso" and "falha inesperada (RuntimeError" in sinc["detalhe"]
    sincronizar = await cliente.post(f"{base}/sincronizar")
    assert sincronizar.status_code == 500 and "Não deu para sincronizar a conta" in sincronizar.json()["detail"]

    async def tudo_quebra(**_):
        raise ValueError("Bearer abcdefghijklmnopqrstuvwxyz0123456789")
    monkeypatch.setattr(onboarding, "conferir", tudo_quebra)
    resposta = await cliente.post(f"{base}/onboarding/avancar", json={})
    assert resposta.status_code == 500
    detalhe = resposta.json()["detail"]
    assert detalhe.startswith("Não deu para avançar o onboarding: falha inesperada (ValueError")
    assert "abcdefghijklmnopqrstuvwxyz" not in detalhe                    # parece token: mascarado
    registro = await banco._pool.fetchval(
        """select erro from agentesia_alteracoes where id_escritorio = $1::uuid and acao = 'onboarding'
           order by criado_em desc limit 1""", id_escritorio)
    assert "ValueError" in registro and "abcdefghijklmnopqrstuvwxyz" not in registro


async def test_primeiro_produto_nao_trava_o_onboarding_da_conta(ambiente):
    cliente, falsa, banco = ambiente
    _, id_escritorio, base = await _conta(cliente, falsa)
    avancado = (await cliente.post(f"{base}/onboarding/avancar", json={})).json()
    passos = _situacao(avancado)
    assert passos["produto"]["situacao"] == "pendente"                    # nenhum agente ainda
    assert all(passos[c]["situacao"] in ("ok", "feito") for c in onboarding.OBRIGATORIOS)
    assert avancado["completo"] is True and avancado["concluido_em"]
    assert onboarding.OBRIGATORIOS == {"token", "webhook", "etiquetas", "painel"}
    guardado = (await cliente.get(f"{base}/onboarding")).json()
    assert guardado["concluido_em"] and "produto" not in guardado["obrigatorios"]


# ------------------------------------------------------------------------------------------- desempenho do Avançar
def _contar_idas_ao_banco(monkeypatch) -> dict:
    """Conta as idas ao banco (cada execute/fetch* de uma conexão asyncpg)."""
    import asyncpg
    contador = {"idas": 0}
    for nome in ("execute", "executemany", "fetch", "fetchval", "fetchrow"):
        original = getattr(asyncpg.connection.Connection, nome)

        def embrulho(original):
            async def contado(self, *a, **k):
                contador["idas"] += 1
                return await original(self, *a, **k)
            return contado
        monkeypatch.setattr(asyncpg.connection.Connection, nome, embrulho(original))
    return contador


async def test_avancar_nao_refaz_os_passos_que_ja_estao_ok(ambiente, monkeypatch):
    cliente, falsa, banco = ambiente
    conta, id_escritorio, base = await _conta(cliente, falsa)
    primeiro = (await cliente.post(f"{base}/onboarding/avancar", json={})).json()
    assert _situacao(primeiro)["sincronizacao"]["situacao"] == "feito" and primeiro["completo"] is True
    copia = "select max(visto_em) from agentesia_helena_recursos where id_escritorio = $1::uuid"
    numeros = "select max(sincronizado_em) from agentesia_canais where id_escritorio = $1::uuid"
    visto, canais = await banco._pool.fetchval(copia, id_escritorio), await banco._pool.fetchval(numeros, id_escritorio)
    assert visto and canais
    # Abrir o modal confere (só lê): não apaga o que já foi aplicado.
    assert (await cliente.post(f"{base}/onboarding/conferir")).status_code == 200

    # De novo, sem forcar: nenhuma escrita na LawChat, a cópia e os números não são regravados, poucas idas ao banco.
    escritas = len([p for p in falsa.pedidos if p[0] != "GET"])
    contador = _contar_idas_ao_banco(monkeypatch)
    de_novo = (await cliente.post(f"{base}/onboarding/avancar", json={"id_painel": conta["paineis"][0]["id"]})).json()
    passos = _situacao(de_novo)
    assert de_novo["pulados"] == ["sincronizacao"] and "Sincronizar conta" in passos["sincronizacao"]["detalhe"]
    codigos = ("token", "webhook", "etiquetas", "painel", "canais", "sincronizacao", "usuarios")
    assert {c: passos[c]["situacao"] for c in codigos} == {c: "ok" for c in codigos}
    assert "já estava escolhido" in passos["painel"]["detalhe"] and de_novo["completo"] is True
    assert len([p for p in falsa.pedidos if p[0] != "GET"]) == escritas
    assert await banco._pool.fetchval(copia, id_escritorio) == visto
    assert await banco._pool.fetchval(numeros, id_escritorio) == canais
    assert contador["idas"] <= 12, contador                       # antes: dezenas (uma por item copiado)

    # O que deixou de estar ok é feito (só ele): a etiqueta padrão apagada na LawChat volta; a cópia continua pulada.
    conta["etiquetas"] = [e for e in conta["etiquetas"] if e["name"] != "🤖 IA Desativada"]
    refeito = (await cliente.post(f"{base}/onboarding/avancar", json={})).json()
    etiquetas = _situacao(refeito)["etiquetas"]
    assert etiquetas["situacao"] == "feito" and "IA Desativada" in etiquetas["detalhe"]
    assert refeito["pulados"] == ["sincronizacao"]
    # Número novo conectado: os números são gravados de novo (mudaram), sem refazer a cópia.
    conta["canais"].append({"id": "ch-c-" + uuid.uuid4().hex[:6], "active": True, "type": "ZAPI_WhatsApp",
                            "number": "5511955550000", "identity": {"displayName": "Novo"}})
    com_numero = (await cliente.post(f"{base}/onboarding/avancar", json={})).json()
    assert _situacao(com_numero)["canais"]["situacao"] == "feito"
    assert await banco._pool.fetchval(
        "select count(*) from agentesia_canais where id_escritorio = $1::uuid and ativo", id_escritorio) == 3

    # forcar refaz tudo, inclusive a cópia.
    forcado = (await cliente.post(f"{base}/onboarding/avancar", json={"forcar": True})).json()
    assert forcado["pulados"] == [] and _situacao(forcado)["sincronizacao"]["situacao"] == "feito"
    assert await banco._pool.fetchval(copia, id_escritorio) > visto
    # A conta pronta aparece como Habilitado na lista.
    lista = (await cliente.get("/api/admin/escritorios")).json()
    assert next(e for e in lista if e["id"] == id_escritorio)["agente_habilitado"] is True


async def test_escolher_o_painel_aplica_so_o_passo_painel(ambiente):
    cliente, falsa, banco = ambiente
    conta, id_escritorio, base = await _conta(cliente, falsa)
    assert (await cliente.post(f"{base}/onboarding/conferir")).status_code == 200
    escritas = len([p for p in falsa.pedidos if p[0] != "GET"])
    juridico = conta["paineis"][2]
    escolhido = (await cliente.post(f"{base}/onboarding/avancar", json={
        "passos": ["painel"], "id_painel": juridico["id"]})).json()
    passos = _situacao(escolhido)
    assert passos["painel"]["situacao"] == "aviso" and "Jurídico escolhido" in passos["painel"]["detalhe"]
    assert escolhido["dados_helena"]["ids"]["id_painel"] == juridico["id"]
    crm = await banco._pool.fetchval(
        "select config->>'id_painel' from agentesia_integracoes where id_escritorio = $1::uuid and tipo = 'crm'", id_escritorio)
    assert crm == juridico["id"]
    # Nada além do painel: nenhuma escrita na LawChat (webhook, etiquetas), sem cópia, sem logins, webhook só conferido.
    assert len([p for p in falsa.pedidos if p[0] != "GET"]) == escritas
    assert await banco._pool.fetchval(
        "select count(*) from agentesia_helena_recursos where id_escritorio = $1::uuid", id_escritorio) == 0
    assert await banco._pool.fetchval(
        "select count(*) from agentesia_usuarios where id_escritorio = $1::uuid", id_escritorio) == 0
    assert passos["webhook"]["situacao"] == "pendente" and passos["sincronizacao"]["situacao"] == "pendente"
    # Trocar de novo pelo select: vale o novo (mesmo com o painel anterior já gravado).
    padrao = conta["paineis"][0]
    trocado = (await cliente.post(f"{base}/onboarding/avancar", json={"passos": ["painel"], "id_painel": padrao["id"]})).json()
    assert _situacao(trocado)["painel"]["situacao"] == "feito" and "6/6" in _situacao(trocado)["painel"]["detalhe"]


async def _copia_linha_a_linha(pool, id_escritorio, recursos, agora):
    """A gravação de antes (uma ida ao banco por item), para comparar com sincronizar_conta.gravar_copia."""
    import json
    tipos = {}
    async with pool.acquire() as conexao, conexao.transaction():
        for tipo in sincronizar_conta.TIPOS:
            if tipo not in recursos:
                continue
            novos, vistos = 0, []
            for item in recursos[tipo]:
                vistos.append(str(item["id"]))
                novo = await conexao.fetchval(
                    """insert into agentesia_helena_recursos
                         (id_escritorio, tipo, id_externo, id_pai_externo, nome, posicao, dados, visto_em, sumiu_em)
                       values ($1::uuid, $2, $3, $4, $5, $6, $7::jsonb, $8, null)
                       on conflict (id_escritorio, tipo, id_externo) do update set
                         id_pai_externo = excluded.id_pai_externo, nome = excluded.nome, posicao = excluded.posicao,
                         dados = excluded.dados, visto_em = excluded.visto_em, sumiu_em = null
                       returning (xmax = 0)""",
                    id_escritorio, tipo, str(item["id"]), item.get("id_pai"), item.get("nome"), item.get("posicao"),
                    json.dumps(item.get("dados") or {}, ensure_ascii=False, default=str), agora)
                novos += 1 if novo else 0
            sumiram = await conexao.fetchval(
                """with marcados as (update agentesia_helena_recursos set sumiu_em = $4
                     where id_escritorio = $1::uuid and tipo = $2 and sumiu_em is null and not (id_externo = any($3::text[]))
                     returning 1) select count(*)::int from marcados""", id_escritorio, tipo, vistos, agora)
            tipos[tipo] = {"total": len(vistos), "novos": novos, "sumiram": sumiram}
        await conexao.execute("update agentesia_escritorios set sincronizado_em = $2 where id = $1::uuid", id_escritorio, agora)
    return tipos


async def test_copia_em_lote_grava_o_mesmo_que_linha_a_linha(ambiente):
    from datetime import datetime, timedelta, timezone

    from app.canal.helena_conta import HelenaConta
    _cliente, falsa, banco = ambiente
    pool = banco._pool
    token = "token-copia-" + uuid.uuid4().hex[:6]
    falsa.conta(token)
    recursos, erros = await sincronizar_conta.ler_conta(HelenaConta(token))
    assert not erros and {t: len(v) for t, v in recursos.items()} == {
        "canal": 2, "painel": 3, "coluna": 9, "etiqueta": 2, "equipe": 1, "usuario": 1}
    antigo = str(await pool.fetchval("insert into agentesia_escritorios (nome) values ('Linha a linha') returning id"))
    lote = str(await pool.fetchval("insert into agentesia_escritorios (nome) values ('Em lote') returning id"))

    async def tabela(id_escritorio):
        linhas = await pool.fetch(
            """select tipo, id_externo, id_pai_externo, nome, posicao, dados::text as dados, visto_em,
                      sumiu_em is not null as sumiu
               from agentesia_helena_recursos where id_escritorio = $1::uuid order by tipo, id_externo""", id_escritorio)
        return [dict(l) for l in linhas]

    agora = datetime.now(timezone.utc)
    sumida = None
    for rodada in range(3):
        quando = agora + timedelta(minutes=rodada)
        esperado = await _copia_linha_a_linha(pool, antigo, recursos, quando)
        feito = await sincronizar_conta.gravar_copia(pool, lote, recursos, quando)
        assert feito == esperado, (rodada, feito, esperado)
        assert await tabela(lote) == await tabela(antigo)
        assert await pool.fetchval("select sincronizado_em from agentesia_escritorios where id = $1::uuid", lote) == quando
        # Próxima rodada: some uma etiqueta e uma coluna, aparece uma equipe; na terceira, a etiqueta volta.
        if rodada == 0:
            sumida = recursos["etiqueta"].pop()
            recursos["coluna"].pop(0)
            recursos["equipe"].append({"id": "d-novo", "nome": "Nova", "dados": {"padrao": False}})
        elif rodada == 1:
            recursos["etiqueta"].append(sumida)
    assert esperado["etiqueta"] == {"total": 2, "novos": 0, "sumiram": 0}
    assert sum(1 for l in await tabela(lote) if l["sumiu"]) == 1                     # a coluna que sumiu
