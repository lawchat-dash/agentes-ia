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
