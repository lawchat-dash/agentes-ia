"""Troca de departamento (de agente) PONTA A PONTA: webhook da Helena -> FastAPI -> Postgres local -> IA falsa ->
Helena falsa. Mesmo harness de tests/test_e2e_helena.py (PGlite com as migrações, MockTransport, ModeloFalso).

Cada caminho que o dono pediu para ver testado (docs/TROCA_DE_DEPARTAMENTO.md, tabela "caso -> resultado -> teste"):
  a) a IA troca SDR -> Closer -> Contratos -> Assinatura -> Contrato assinado, e SDR -> Desqualificado;
  b) a IA pede análise humana e o atendimento vai para o departamento configurado;
  c) a equipe move o card de coluna na Helena e a IA passa a responder como o agente daquela etapa;
  d) a equipe troca a etapa pelo painel e o card, a etiqueta e a nota acompanham na Helena;
  e) os chips "@Agente X" e "@Transferência: X" do prompt viram destinos válidos; um "@" inválido é barrado;
  f) troca dupla ou concorrente não gera dois cards nem dois movimentos.
Todos os dados de lead são inventados.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from app.cerebro import catalogo
from tests.test_e2e_helena import (CPF_FICTICIO, FRASE_CLOSER, Cenario, _linha_propria, banco_local, e2e,  # noqa: F401
                                   extrai, responde)

ETIQUETAS = {"sdr": "📞 SDR", "closer": "🛒 Comercial", "contratos": "📝 Contrato", "assinatura": "✍️ Assinatura",
             "contrato_assinado": "✅ Assinado", "desqualificado": "❌ Desqualificado"}
COLUNAS = {"sdr": "col-sdr", "closer": "col-closer", "contratos": "col-contratos", "assinatura": "col-assinatura",
           "contrato_assinado": "col-assinado", "desqualificado": "col-desq"}


# ============================================================================ preparação
async def _funil_completo(e2e: Cenario, **extra: Any) -> None:
    """Automações de todas as etapas, como a sugestão do catálogo monta: cada etapa tem a sua coluna, põe a sua
    etiqueta, tira as das outras e deixa uma nota no atendimento."""
    regras: dict[str, Any] = {"lead_novo": {"coluna_crm": COLUNAS["sdr"], "adicionar_etiquetas": [ETIQUETAS["sdr"]]}}
    for etapa in ("closer", "contratos", "assinatura", "contrato_assinado", "desqualificado"):
        regras[f"etapa:{etapa}"] = {"coluna_crm": COLUNAS[etapa], "adicionar_etiquetas": [ETIQUETAS[etapa]],
                                    "remover_etiquetas": [n for p, n in ETIQUETAS.items() if p != etapa],
                                    "nota": f"🔀 Lead passou para {catalogo.NOMES[etapa]}."}
    regras.update(extra)
    await e2e.pool.execute("update agentesia_agentes set config = jsonb_set(config, '{automacoes}', $2::jsonb) where id = $1::uuid",
                           e2e.ids["agente"], json.dumps(regras, ensure_ascii=False))


def _papeis(e2e: Cenario) -> dict[str, Any]:
    return e2e.agente["config"]["catalogo"]["papeis"]


def _linhas(e2e: Cenario) -> dict[str, str]:
    """Uma linha própria do prompt de cada papel (para saber qual agente respondeu)."""
    return {c: _linha_propria(p, [o for k, o in e2e.prompts.items() if k != c]) for c, p in e2e.prompts.items() if p}


def _card_movido(e2e: Cenario, coluna: str, *, id_card: str | None = None, date: str | None = None) -> dict[str, Any]:
    """A equipe arrastou o card para outra coluna na Helena: o webhook PANEL_CARD_STEP_CHANGE."""
    id_card = id_card or next(iter(e2e.helena.cards))
    e2e.helena.cards[id_card] = coluna
    return {"eventType": "PANEL_CARD_STEP_CHANGE", "date": date or datetime.now(timezone.utc).isoformat(),
            "content": {"id": id_card, "companyId": e2e.ids["conta"], "panelId": "painel-comercial", "stepId": coluna,
                        "contactIds": [e2e.helena.id_contato], "sessionId": e2e.sessao}}


async def _entrar_no_painel(e2e: Cenario) -> None:
    from app.gestao import seguranca

    email = f"gestor-{uuid.uuid4().hex[:6]}@exemplo.test"
    await e2e.pool.execute(
        """insert into agentesia_usuarios (email, nome, senha_hash, papel, id_escritorio, trocar_senha)
           values ($1, 'Gestora Teste', $2, 'gestor', $3::uuid, false)""",
        email, seguranca.gerar_hash("senha-de-teste-123"), e2e.ids["escritorio"])
    assert (await e2e.http.post("/api/entrar", json={"email": email, "senha": "senha-de-teste-123"})).status_code == 200


async def _trocar_pelo_painel(e2e: Cenario, etapa: str) -> dict[str, Any]:
    lead = await e2e.lead()
    resposta = await e2e.http.post(f"/api/conversas/{lead['id']}/ia", json={"acao": "trocar_etapa", "etapa": etapa})
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


async def _historico(e2e: Cenario) -> list[tuple[str | None, str, str | None]]:
    lead = await e2e.lead()
    return [(h["etapa_de"], h["etapa_para"], h["origem"]) for h in await e2e.pool.fetch(
        "select etapa_de, etapa_para, origem from agentesia_lead_etapas where id_lead = $1 order by criado_em", lead["id"])]


def _tem(e2e: Cenario, operacao: str, etiqueta: str) -> bool:
    return any(op == operacao and etiqueta in nomes for op, nomes in e2e.helena.etiquetas())


def _nota(e2e: Cenario, etapa: str) -> int:
    return sum(n.startswith(f"🔀 Lead passou para {catalogo.NOMES[etapa]}.") for n in e2e.helena.notas())


# ============================================================================ a) a IA troca de agente no funil todo
async def test_a_ia_leva_o_lead_do_sdr_ao_contrato_assinado(e2e: Cenario):
    """SDR -> Closer -> Contratos (pela IA, com a frase de entrada de cada destino) -> Assinatura (pela geração do
    contrato) -> Contrato assinado (pelo aviso da ZapSign). Em cada passo: etapa no banco, card na coluna certa,
    etiqueta trocada, nota e, no turno seguinte, o prompt do agente novo."""
    await _funil_completo(e2e)
    linhas, papeis = _linhas(e2e), _papeis(e2e)
    frase_contratos = papeis["contratos"]["mensagem_troca"]
    dados = ("Carla Mendes Ribeiro, CPF " + CPF_FICTICIO + ", Rua das Flores 120, bairro Centro, Belo Horizonte MG, "
             "CEP 30110-012")
    fatos = [("nome_completo", "Carla Mendes Ribeiro", "Carla Mendes Ribeiro"), ("cpf", CPF_FICTICIO, CPF_FICTICIO),
             ("endereco", "Rua das Flores", "Rua das Flores"), ("numero_casa", "120", "120"), ("bairro", "Centro", "Centro"),
             ("cidade", "Belo Horizonte", "Belo Horizonte"), ("uf", "MG", "MG"), ("cep", "30110-012", "30110-012")]
    e2e.ia.extrator = lambda _s, c: extrai(fatos) if "Rua das Flores" in c.split("MENSAGENS NOVAS")[-1] else extrai()

    def etapa(sistema: str, conteudo: str) -> dict[str, Any]:
        novas = conteudo.split("MENSAGENS NOVAS")[-1]
        if linhas["contratos"] in sistema:
            return responde("Perfeito, Carla! Vou gerar o seu contrato agora.", ferramenta="zapsign") \
                if "Rua das Flores" in novas else responde("Pode me mandar seus dados?")
        if linhas["closer"] in sistema:
            return responde("Que ótimo que você quer seguir!", frase_contratos, transferir_para="contratos") \
                if "quero seguir" in novas else responde("Carla, vou te explicar como funciona o nosso trabalho.")
        if "sequela" in novas:
            return responde("Entendi, Carla.", FRASE_CLOSER, transferir_para="closer")
        return responde("Oi, Carla! Como foi o acidente?")

    e2e.ia.etapa = etapa
    await e2e.chega(e2e.do_lead("oi, sofri um acidente"))
    assert list(e2e.helena.cards.values()) == [COLUNAS["sdr"]] and _tem(e2e, "InsertIfNotExists", ETIQUETAS["sdr"])

    # SDR -> Closer
    await e2e.chega(e2e.do_lead("caí da escada no trabalho e fiquei com sequela no tornozelo"))
    assert (await e2e.lead())["etapa"] == "closer"
    assert e2e.helena.textos()[-1] == FRASE_CLOSER                          # a frase de entrada do Closer
    card = next(iter(e2e.helena.cards))
    assert e2e.helena.cards[card] == COLUNAS["closer"]
    assert _tem(e2e, "InsertIfNotExists", ETIQUETAS["closer"]) and _tem(e2e, "DeleteIfExists", ETIQUETAS["sdr"])
    assert _nota(e2e, "closer") == 1

    # Closer -> Contratos
    await e2e.chega(e2e.do_lead("gostei, quero seguir"))
    assert linhas["closer"] in e2e.pedidos("etapa")[-1]["sistema"]          # quem respondeu foi o Closer
    assert (await e2e.lead())["etapa"] == "contratos"
    assert catalogo.tem_frase(e2e.helena.textos()[-3:], frase_contratos)
    assert e2e.helena.cards[card] == COLUNAS["contratos"] and _nota(e2e, "contratos") == 1
    assert _tem(e2e, "InsertIfNotExists", ETIQUETAS["contratos"])

    # Contratos -> Assinatura (o contrato é gerado e o link enviado; quem troca é a geração, não a IA)
    await e2e.chega(e2e.do_lead("Confirmo meus dados: " + dados))
    assert linhas["contratos"] in e2e.pedidos("etapa")[-1]["sistema"]
    assert (await e2e.lead())["etapa"] == "assinatura"
    assert e2e.helena.cards[card] == COLUNAS["assinatura"] and _nota(e2e, "assinatura") == 1
    assert _tem(e2e, "InsertIfNotExists", ETIQUETAS["assinatura"])

    # Assinatura -> Contrato assinado (aviso da ZapSign)
    contrato = await e2e.pool.fetchrow("select * from agentesia_contratos where id_lead = $1", (await e2e.lead())["id"])
    e2e.helena.zapsign_assinado = True
    assert (await e2e.zapsign({"event_type": "doc_signed", "token": contrato["id_documento_externo"],
                               "signer_who_signed": {"token": f"signer-{e2e.helena.prefixo}-1"}})).json()["feito"] == "processado"
    await e2e.rodar_fila()
    lead = await e2e.lead()
    assert (lead["etapa"], lead["estado"]) == ("contrato_assinado", "encerrado")
    assert e2e.helena.cards[card] == COLUNAS["contrato_assinado"] and _nota(e2e, "contrato_assinado") == 1
    assert _tem(e2e, "InsertIfNotExists", ETIQUETAS["contrato_assinado"])

    # Um card só, do começo ao fim, e cada coluna uma vez (nenhum movimento repetido).
    assert len(e2e.helena.cards) == 1
    assert [c for _, c in e2e.helena.movimentos_de_card()] == [
        COLUNAS["sdr"], COLUNAS["closer"], COLUNAS["contratos"], COLUNAS["assinatura"], COLUNAS["contrato_assinado"]]
    assert [(de, para) for de, para, _ in await _historico(e2e)] == [
        (None, "sdr"), ("sdr", "closer"), ("closer", "contratos"), ("contratos", "assinatura"),
        ("assinatura", "contrato_assinado")]
    assert "@Agente" not in " ".join(e2e.helena.textos()) and "acionar tool" not in " ".join(e2e.helena.textos())


async def test_a_ia_desqualifica_e_o_agente_desqualificado_assume(e2e: Cenario):
    await _funil_completo(e2e)
    linhas, frase = _linhas(e2e), _papeis(e2e)["desqualificado"]["mensagem_troca"]

    def etapa(sistema: str, conteudo: str) -> dict[str, Any]:
        if linhas["desqualificado"] in sistema:
            return responde("Fico à disposição, Carla.")
        if "aposentad" in conteudo.split("MENSAGENS NOVAS")[-1]:
            return responde(frase, transferir_para="desqualificado")
        return responde("Oi, Carla! Você recebe alguma aposentadoria hoje?")

    e2e.ia.etapa = etapa
    await e2e.chega(e2e.do_lead("oi"))
    await e2e.chega(e2e.do_lead("sou aposentado por idade desde 2019"))
    assert (await e2e.lead())["etapa"] == "desqualificado"
    assert catalogo.tem_frase(e2e.helena.textos(), frase)
    assert e2e.helena.cards[next(iter(e2e.helena.cards))] == COLUNAS["desqualificado"]
    assert _tem(e2e, "InsertIfNotExists", ETIQUETAS["desqualificado"]) and _tem(e2e, "DeleteIfExists", ETIQUETAS["sdr"])
    assert _nota(e2e, "desqualificado") == 1
    await e2e.chega(e2e.do_lead("ok, obrigado"))
    assert linhas["desqualificado"] in e2e.pedidos("etapa")[-1]["sistema"]
    assert e2e.helena.textos()[-1] == "Fico à disposição, Carla."


# ============================================================================ b) análise humana -> departamento
async def test_b_analise_humana_transfere_para_o_departamento_configurado(e2e: Cenario):
    """O roteiro manda "Análise da equipe": a IA marca a notificação, sai da conversa, deixa a nota e o atendimento vai
    para o departamento configurado na regra (ou o padrão do agente)."""
    await _funil_completo(e2e, **{"sinal:analise_humana": {"transferir": True, "id_equipe": "equipe-juridico",
                                                           "nota": "🔎 Caso para análise humana."}})
    await e2e.pool.execute(
        """update agentesia_agentes set config = jsonb_set(jsonb_set(config, '{funcoes,transferir_humano}', 'true'::jsonb),
                  '{id_equipe_transferencia}', '"equipe-padrao"'::jsonb) where id = $1::uuid""", e2e.ids["agente"])

    def etapa(_s: str, conteudo: str) -> dict[str, Any]:
        if "não sei a data" in conteudo.split("MENSAGENS NOVAS")[-1]:
            return {"mensagens": [{"texto": "Vou pedir para a nossa equipe olhar o seu caso com atenção."}],
                    "transferir_para": "", "ferramenta": "", "notificacao": "analise_humana"}
        return responde("Oi, Carla! Quando foi o acidente?")

    e2e.ia.etapa = etapa
    await e2e.chega(e2e.do_lead("oi"))
    await e2e.chega(e2e.do_lead("não sei a data, faz tempo"))
    lead = await e2e.lead()
    assert (lead["etapa"], lead["estado"], lead["motivo_estado"]) == ("sdr", "pausado", "sinal:analise_humana")
    assert e2e.helena.transferencias() == [(e2e.sessao, "equipe-juridico")]         # o departamento da regra
    assert e2e.helena.notas().count("🔎 Caso para análise humana.\nMotivo: sinal:analise_humana") == 1
    assert not any(n.startswith("🔔 O lead precisa de atenção") for n in e2e.helena.notas())   # sem nota dobrada
    # A IA saiu: a próxima mensagem do lead não tem resposta dela.
    antes = len(e2e.helena.textos())
    await e2e.chega(e2e.do_lead("alguém vai me responder?"))
    assert len(e2e.helena.textos()) == antes

    # Sem departamento na regra: vai para o departamento padrão do agente.
    await _funil_completo(e2e, **{"sinal:analise_humana": {"transferir": True}})
    await e2e.pool.execute("update agentesia_leads set estado = 'ativo', motivo_estado = null where id = $1", lead["id"])
    await e2e.chega(e2e.do_lead("ainda não sei a data"))
    assert e2e.helena.transferencias()[-1] == (e2e.sessao, "equipe-padrao")


async def test_b_analise_humana_sem_transferencia_configurada_so_pausa_e_avisa(e2e: Cenario):
    """Sem a regra de transferir: a IA sai da conversa e deixa a nota, mas o atendimento fica na equipe da IA."""
    await _funil_completo(e2e)
    e2e.ia.etapa = lambda _s, c: ({"mensagens": [{"texto": "Vou pedir para a nossa equipe olhar o seu caso."}],
                                   "transferir_para": "", "ferramenta": "", "notificacao": "analise_humana"}
                                  if "não sei" in c.split("MENSAGENS NOVAS")[-1] else responde("Oi! Quando foi?"))
    await e2e.chega(e2e.do_lead("oi"))
    await e2e.chega(e2e.do_lead("não sei"))
    assert (await e2e.lead())["estado"] == "pausado"
    assert e2e.helena.transferencias() == []
    assert any(n.startswith("🔔 O lead precisa de atenção da equipe") for n in e2e.helena.notas())


# ============================================================================ c) a equipe move o card na Helena
async def test_c_equipe_move_o_card_e_a_ia_responde_como_o_agente_da_coluna(e2e: Cenario):
    await _funil_completo(e2e)
    await e2e.pool.execute(
        """update agentesia_agentes set config = jsonb_set(config, '{catalogo,papeis,closer,boas_vindas}',
                  '"Oi! Sou a Ana, do time comercial, e agora sigo com você."'::jsonb) where id = $1::uuid""", e2e.ids["agente"])
    linhas = _linhas(e2e)
    e2e.ia.etapa = lambda s, _c: responde("Sou do comercial." if linhas["closer"] in s else "Oi! Como foi o acidente?")
    await e2e.chega(e2e.do_lead("oi"))
    movimentos = len(e2e.helena.movimentos_de_card())

    resposta = await e2e.chega(_card_movido(e2e, COLUNAS["closer"]))
    assert resposta["feito"] == "trocado" and (resposta["de"], resposta["para"]) == ("sdr", "closer")
    lead = await e2e.lead()
    assert (lead["etapa"], lead["estado"]) == ("closer", "ativo")
    assert (await _historico(e2e))[-1] == ("sdr", "closer", "equipe_crm")
    troca = (await e2e.eventos("etapa_trocada"))[-1]
    detalhe = troca["detalhe"] if isinstance(troca["detalhe"], dict) else json.loads(troca["detalhe"])
    assert detalhe["origem"] == "equipe_crm" and detalhe["coluna"] == COLUNAS["closer"]
    # Na Helena: etiqueta e nota da etapa nova; o card NÃO é movido de novo (a equipe já o pôs lá).
    assert _tem(e2e, "InsertIfNotExists", ETIQUETAS["closer"]) and _tem(e2e, "DeleteIfExists", ETIQUETAS["sdr"])
    assert _nota(e2e, "closer") == 1
    assert len(e2e.helena.movimentos_de_card()) == movimentos
    card = await e2e.pool.fetchrow("select * from agentesia_crm_cards where id_lead = $1", lead["id"])
    assert card["id_etapa_helena"] == COLUNAS["closer"]                      # o espelho do card acompanha

    # A próxima resposta já é do Closer, com as boas-vindas dele.
    await e2e.chega(e2e.do_lead("e agora?"))
    pedido = e2e.pedidos("etapa")[-1]
    assert linhas["closer"] in pedido["sistema"] and "agora sigo com você" in pedido["conteudo"]
    assert e2e.helena.textos()[-1] == "Sou do comercial."


async def test_c_coluna_sem_etapa_card_de_outro_painel_e_lead_encerrado_nao_mudam_nada(e2e: Cenario):
    await _funil_completo(e2e)
    e2e.ia.etapa = lambda _s, _c: responde("Oi!")
    await e2e.chega(e2e.do_lead("oi"))
    assert (await e2e.chega(_card_movido(e2e, "col-arquivo")))["motivo"] == "coluna_sem_etapa"
    outro = _card_movido(e2e, COLUNAS["closer"])
    outro["content"]["panelId"] = "painel-financeiro"
    assert (await e2e.chega(outro))["motivo"] == "outro_painel"
    estranho = _card_movido(e2e, COLUNAS["closer"], id_card="card-de-outro-contato")
    estranho["content"].update(sessionId="sessao-desconhecida", contactIds=["contato-desconhecido"])
    assert (await e2e.chega(estranho))["motivo"] == "card_sem_lead"
    outra_conta = _card_movido(e2e, COLUNAS["closer"])
    outra_conta["content"]["companyId"] = str(uuid.uuid4())
    assert (await e2e.chega(outra_conta))["motivo"] == "conta_de_outro_escritorio"
    assert (await e2e.lead())["etapa"] == "sdr"
    # Contrato assinado é fim de linha: arrastar o card não tira o lead de lá.
    await e2e.por_na_etapa("contrato_assinado")
    assert (await e2e.chega(_card_movido(e2e, COLUNAS["closer"])))["motivo"] == "lead_encerrado"
    assert (await e2e.lead())["etapa"] == "contrato_assinado"


async def test_c_escritorio_pode_desligar_a_troca_pelo_card(e2e: Cenario):
    await _funil_completo(e2e)
    await e2e.pool.execute("update agentesia_agentes set config = config || '{\"seguir_coluna_do_crm\": false}'::jsonb where id = $1::uuid",
                           e2e.ids["agente"])
    e2e.ia.etapa = lambda _s, _c: responde("Oi!")
    await e2e.chega(e2e.do_lead("oi"))
    assert (await e2e.chega(_card_movido(e2e, COLUNAS["closer"])))["motivo"] == "seguir_coluna_desligado"
    assert (await e2e.lead())["etapa"] == "sdr"


# ============================================================================ d) a equipe troca pelo painel
async def test_d_troca_pelo_painel_move_card_etiqueta_e_nota_na_helena(e2e: Cenario):
    await _funil_completo(e2e)
    linhas = _linhas(e2e)
    e2e.ia.etapa = lambda s, _c: responde("Me passa seu nome completo?" if linhas["contratos"] in s else "Oi!")
    await e2e.chega(e2e.do_lead("oi"))
    await _entrar_no_painel(e2e)
    assert (await _trocar_pelo_painel(e2e, "contratos"))["mudou"] is True
    await e2e.rodar_fila()
    lead = await e2e.lead()
    assert lead["etapa"] == "contratos" and (await _historico(e2e))[-1] == ("sdr", "contratos", "equipe")
    card = next(iter(e2e.helena.cards))
    assert e2e.helena.cards[card] == COLUNAS["contratos"]
    assert _tem(e2e, "InsertIfNotExists", ETIQUETAS["contratos"]) and _tem(e2e, "DeleteIfExists", ETIQUETAS["sdr"])
    assert _nota(e2e, "contratos") == 1
    assert await e2e.pool.fetchval(
        "select count(*) from agentesia_alteracoes where id_registro = $1::uuid and acao = 'trocar_etapa'", lead["id"]) == 1

    # A Helena avisa que o card mudou de coluna (foi a LawChat que moveu): nada muda de novo, sem laço.
    assert (await e2e.chega(_card_movido(e2e, COLUNAS["contratos"])))["motivo"] == "ja_estava"
    assert _nota(e2e, "contratos") == 1 and e2e.helena.movimentos_de_card()[-1] == (card, COLUNAS["contratos"])
    await e2e.chega(e2e.do_lead("certo"))
    assert linhas["contratos"] in e2e.pedidos("etapa")[-1]["sistema"]
    # Pedir a mesma etapa de novo não refaz nada.
    assert (await _trocar_pelo_painel(e2e, "contratos"))["mudou"] is False


# ============================================================================ e) chips "@" do prompt
async def test_e_chip_transferencia_cru_vira_destino_e_nunca_vaza(e2e: Cenario):
    """Prompt gravado com o chip "@Transferência: Closer" cru (sem a expansão do painel): o motor oferece o Closer como
    destino, troca o chip pela frase de entrada do Closer no roteiro e a IA não o recebe para copiar."""
    prompt = ("Você é {{NOME AGENTE}}, do escritório {{NOME ESCRITORIO}}. Pergunte como foi o acidente.\n"
              "Quando o lead contar que ficou com sequela, diga @Transferência: Closer")
    await e2e.pool.execute("update agentesia_agente_etapas set instrucao = $2 where id = $1::uuid", e2e.ids["etapas"]["sdr"], prompt)
    await e2e.pool.execute(
        "update agentesia_agentes set config = jsonb_set(config, '{catalogo,papeis,sdr,destinos}', '[]'::jsonb) where id = $1::uuid",
        e2e.ids["agente"])
    e2e.ia.etapa = lambda _s, c: responde("Que bom que me contou.", FRASE_CLOSER, transferir_para="closer") \
        if "sequela" in c.split("MENSAGENS NOVAS")[-1] else responde("Oi! Como foi o acidente?")
    await e2e.chega(e2e.do_lead("oi"))
    pedido = e2e.pedidos("etapa")[0]
    assert pedido["esquema"]["properties"]["transferir_para"]["enum"] == ["", "closer"]
    assert "@Transferência" not in pedido["sistema"] and f'"{FRASE_CLOSER}"' in pedido["sistema"]
    await e2e.chega(e2e.do_lead("fiquei com sequela na mão"))
    assert (await e2e.lead())["etapa"] == "closer"
    assert "@Transfer" not in " ".join(e2e.helena.textos())


async def test_e_arroba_invalido_e_barrado_e_avisado(e2e: Cenario):
    """"@Agente Financeiro" não é agente do produto: não vira destino, a IA que pede esse destino não troca o lead e a
    equipe recebe um aviso de cadastro (uma vez só na conversa). O chip escrito pela IA para o lead é reprovado."""
    prompt = ("Você é {{NOME AGENTE}}. Pergunte como foi o acidente.\n"
              "Se o lead falar de dinheiro, passe para @Agente Financeiro. Com sequela, passe para @Agente Closer.")
    await e2e.pool.execute("update agentesia_agente_etapas set instrucao = $2 where id = $1::uuid", e2e.ids["etapas"]["sdr"], prompt)
    await e2e.pool.execute(
        "update agentesia_agentes set config = jsonb_set(config, '{catalogo,papeis,sdr,destinos}', '[]'::jsonb) where id = $1::uuid",
        e2e.ids["agente"])

    def etapa(_s: str, c: str) -> dict[str, Any]:
        novas = c.split("MENSAGENS NOVAS")[-1]
        if "dinheiro" in novas:
            return responde("Vou ver isso.", transferir_para="financeiro")
        if "vazou" in novas and "CORRIJA" not in c:
            return responde("Vou te passar para o @Agente Closer.")
        return responde("Oi! Como foi o acidente?")

    e2e.ia.etapa = etapa
    await e2e.chega(e2e.do_lead("oi"))
    assert e2e.pedidos("etapa")[0]["esquema"]["properties"]["transferir_para"]["enum"] == ["", "closer"]
    await e2e.chega(e2e.do_lead("e o dinheiro?"))
    assert (await e2e.lead())["etapa"] == "sdr"
    assert [json.loads(e["detalhe"])["destino"] if isinstance(e["detalhe"], str) else e["detalhe"]["destino"]
            for e in await e2e.eventos("destino_recusado")] == ["financeiro"]
    assert len(await e2e.eventos("arroba_sem_destino")) == 1                 # avisou uma vez, não a cada turno
    assert len(e2e.helena.movimentos_de_card()) == 1                         # só o card do lead novo
    await e2e.chega(e2e.do_lead("o texto vazou?"))
    assert "@Agente" not in " ".join(e2e.helena.textos())                    # reprovado e refeito pela CORRIJA


# ============================================================================ f) troca dupla e concorrente
async def test_f_aviso_do_card_repetido_ou_simultaneo_troca_uma_vez_so(e2e: Cenario):
    await _funil_completo(e2e)
    e2e.ia.etapa = lambda _s, _c: responde("Oi!")
    await e2e.chega(e2e.do_lead("oi"))
    corpo = _card_movido(e2e, COLUNAS["closer"])
    outro = _card_movido(e2e, COLUNAS["closer"], date="2026-11-25T18:00:01Z")   # o mesmo arraste, avisado duas vezes
    respostas = await asyncio.gather(e2e.postar(corpo), e2e.postar(outro), e2e.postar(corpo))
    await e2e.rodar_fila()
    feitos = sorted(r.json().get("motivo") or r.json()["feito"] for r in respostas)
    assert feitos == ["ja_estava", "repetido", "trocado"]
    assert (await e2e.lead())["etapa"] == "closer"
    assert _nota(e2e, "closer") == 1
    assert sum(op == "InsertIfNotExists" and ETIQUETAS["closer"] in n for op, n in e2e.helena.etiquetas()) == 1
    assert [(de, para) for de, para, _ in await _historico(e2e)].count(("sdr", "closer")) == 1


async def test_f_aviso_atrasado_do_card_que_a_lawchat_moveu_nao_volta_o_lead(e2e: Cenario):
    """A IA passou SDR -> Closer (a LawChat moveu o card) e a equipe, pelo painel, já pôs o lead em Contratos. O aviso
    da Helena sobre o movimento para a coluna do Closer chega atrasado: o lead não volta (troca dupla barrada)."""
    await _funil_completo(e2e)
    e2e.ia.etapa = lambda _s, c: responde("Entendi.", FRASE_CLOSER, transferir_para="closer") \
        if "sequela" in c.split("MENSAGENS NOVAS")[-1] else responde("Oi!")
    await e2e.chega(e2e.do_lead("oi"))
    await e2e.chega(e2e.do_lead("fiquei com sequela"))
    assert (await e2e.lead())["etapa"] == "closer"
    eco = _card_movido(e2e, COLUNAS["closer"])
    # O aviso logo depois do movimento: o lead está na coluna, nada muda.
    assert (await e2e.chega(eco))["motivo"] == "ja_estava"
    await _entrar_no_painel(e2e)
    assert (await _trocar_pelo_painel(e2e, "contratos"))["mudou"] is True
    await e2e.rodar_fila()
    atrasado = _card_movido(e2e, COLUNAS["closer"], date="2026-11-25T18:30:00Z")
    e2e.helena.cards[atrasado["content"]["id"]] = COLUNAS["contratos"]        # na Helena o card já está em Contratos
    assert (await e2e.chega(atrasado))["motivo"] == "eco_do_sistema"
    assert (await e2e.lead())["etapa"] == "contratos"
    assert await e2e.eventos("card_eco_ignorado")
    assert len(e2e.helena.cards) == 1                                        # um card só


async def test_f_duas_trocas_simultaneas_pelo_painel_valem_uma_vez(e2e: Cenario):
    await _funil_completo(e2e)
    e2e.ia.etapa = lambda _s, _c: responde("Oi!")
    await e2e.chega(e2e.do_lead("oi"))
    await _entrar_no_painel(e2e)
    lead = await e2e.lead()
    pedidos = [e2e.http.post(f"/api/conversas/{lead['id']}/ia", json={"acao": "trocar_etapa", "etapa": "closer"})
               for _ in range(2)]
    respostas = [r.json() for r in await asyncio.gather(*pedidos)]
    await e2e.rodar_fila()
    assert sorted(r["mudou"] for r in respostas) == [False, True]
    assert [c for _, c in e2e.helena.movimentos_de_card()] == [COLUNAS["sdr"], COLUNAS["closer"]]
    assert _nota(e2e, "closer") == 1 and len(e2e.helena.cards) == 1


async def test_f_uma_resposta_da_ia_so_pede_um_destino(e2e: Cenario):
    """O caso do ticket TK-1773 (duas tools de troca na mesma resposta) não tem como acontecer: a saída da IA tem um
    campo só, transferir_para. E a frase de passagem de OUTRO destino na mesma resposta é reprovada e refeita."""
    linhas = _linhas(e2e)
    frase_desq = _papeis(e2e)["desqualificado"]["mensagem_troca"]
    assert e2e.prompts["sdr"]

    def etapa(s: str, c: str) -> dict[str, Any]:
        if "sequela" in c.split("MENSAGENS NOVAS")[-1]:
            if "CORRIJA" in c:
                return responde("Entendi.", FRASE_CLOSER, transferir_para="closer")
            return responde(frase_desq, transferir_para="closer")            # destino e frase contraditórios
        return responde("Oi!") if linhas["sdr"] in s else responde("Sou outro agente.")

    e2e.ia.etapa = etapa
    await e2e.chega(e2e.do_lead("oi"))
    assert e2e.pedidos("etapa")[0]["esquema"]["properties"]["transferir_para"]["type"] == "string"
    await e2e.chega(e2e.do_lead("fiquei com sequela"))
    assert (await e2e.lead())["etapa"] == "closer"
    assert not catalogo.tem_frase(e2e.helena.textos(), frase_desq)
    assert [c for _, c in e2e.helena.movimentos_de_card()] == [COLUNAS.get("sdr"), "col-closer"]
