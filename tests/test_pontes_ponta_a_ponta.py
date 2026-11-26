"""Verificação de PONTA A PONTA das pontes (26/11): o que a equipe recebe no chat (notas), no WhatsApp (Avisos) e no
sino do painel, para cada família de produto do catálogo; a cadência do follow-up mudada pelo painel; e o prompt
mudado pelo painel chegando ao modelo.

Mesmo harness de tests/test_e2e_helena.py (app FastAPI de verdade + PGlite local + Helena/ZapSign falsas +
ModeloFalso). Nada sai para a rede e nenhuma IA paga é chamada. O agente é o do catálogo (Sousa e Costa) montado como
o painel monta em produção: produto 'catalogo' sem o nome no config (o nome vem do produto da biblioteca), portão de
fatos desligado e o CRM automático da conta (colunas fixas do onboarding), sem automações próprias.

Bugs que estes testes pegaram (corrigidos):
  1. Aviso e nota do contrato saíam com "🛒 Produto: catalogo" e "📂 Caso: Produto do catálogo" em todo agente do
     catálogo (o nome do produto não fica no config do agente). O resumo do contrato assinado também usava o prompt
     geral no lugar do de auxílio-acidente por causa disso.
  2. {{Nome}} (com maiúscula) no modelo do aviso ia cru para o WhatsApp da equipe.
  3. Mudar o "desistir após X h" do follow-up não valia para a desistência já agendada; encurtar a cadência deixava
     dois lembretes seguidos (sem a folga do intervalo mínimo).
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.modelo import ModeloFalso
from tests.test_e2e_helena import (CPF_FICTICIO, FRASE_CLOSER, Cenario, banco_local, e2e, extrai,  # noqa: F401
                                   responde)

DESTINO = "5531999990000"                          # número inventado de quem recebe os avisos
DOMINIO = "advteste.wts.chat"
SINAIS_DE_DADO_CRU = ("{{", "}}", "None", "null", "Helena", "catalogo", "Produto do catálogo", "sem nome")

# (slug do produto na biblioteca, nome no painel) — uma família de cada (app/cerebro/catalogo.familia_do_produto).
FAMILIAS = [
    ("auxilio-acidente", "Auxílio-Acidente"),
    ("bpc-loas-infantil", "BPC/LOAS Infantil"),
    ("bpc-loas-idoso", "BPC/LOAS Idoso"),
    ("bpc-loas-geral", "BPC/LOAS Pessoa com Deficiência"),
    ("aposentadoria-por-idade", "Aposentadoria por Idade"),
]
COLUNAS = {"SDR": "col-sdr", "COMERCIAL": "col-closer", "CONTRATO": "col-contrato",
           "AGUARDANDO_ASSINATURA": "col-assinatura", "CONTRATO_ASSINADO": "col-assinado", "DESQUALIFICADO": "col-desq"}


# ============================================================================ preparação
async def _como_o_painel_monta(e2e: Cenario, slug: str, nome: str) -> str:
    """O agente do e2e vira o que a ativação do painel grava: catálogo sem nome no config, portão desligado, sem
    automações próprias (CRM automático das colunas fixas) e o produto da biblioteca com o nome do painel."""
    from app.banco.postgres import limpar_cache_da_config

    pool = e2e.pool
    id_bib = await pool.fetchval("insert into agentesia_biblioteca_produtos (slug, nome) values ($1, $2) returning id",
                                 f"{slug}-{uuid.uuid4().hex[:6]}", nome)
    config = json.loads(await pool.fetchval("select config::text from agentesia_agentes where id = $1::uuid", e2e.ids["agente"]))
    catalogo = {k: v for k, v in config["catalogo"].items() if k != "nome"}
    config["catalogo"] = {**catalogo, "slug": slug, "id_produto_biblioteca": str(id_bib), "portao_de_fatos": False}
    config.pop("automacoes", None)
    config["funcoes"] = {**config["funcoes"], "avisos": True, "crm": True}
    await pool.execute("update agentesia_agentes set config = $2::jsonb where id = $1::uuid", e2e.ids["agente"],
                       json.dumps(config, ensure_ascii=False))
    await pool.execute("update agentesia_integracoes set config = $2::jsonb where id_escritorio = $1::uuid and tipo = 'crm'",
                       e2e.ids["escritorio"], json.dumps({"id_painel": "painel-comercial", "etapas_por_tipo": COLUNAS}))
    await pool.execute("update agentesia_escritorios set config = config || $2::jsonb where id = $1::uuid",
                       e2e.ids["escritorio"], json.dumps({"dominio_helena": DOMINIO}))
    limpar_cache_da_config()
    return str(id_bib)


async def _gestor(e2e: Cenario) -> None:
    from app.gestao import seguranca

    email = f"gestor-{uuid.uuid4().hex[:6]}@exemplo.test"
    await e2e.pool.execute(
        """insert into agentesia_usuarios (email, nome, senha_hash, papel, id_escritorio, trocar_senha)
           values ($1, 'Gestora Teste', $2, 'gestor', $3::uuid, false)""",
        email, seguranca.gerar_hash("senha-de-teste-123"), e2e.ids["escritorio"])
    entrar = await e2e.http.post("/api/entrar", json={"email": email, "senha": "senha-de-teste-123"})
    assert entrar.status_code == 200, entrar.text


async def _ligar_avisos_pelo_painel(e2e: Cenario) -> None:
    """Tela Avisos no WhatsApp: número que envia (o do agente), quem recebe e todos os avisos do catálogo ligados."""
    from app.gestao.rotas_avisos import CATALOGO

    conta = await e2e.http.put("/api/avisos/conta", json={"numero_envio": e2e.ids["canal"],
                                                          "destinatarios": [{"rotulo": "Dono", "numero": DESTINO[2:]}]})
    assert conta.status_code == 200, conta.text
    ligados = await e2e.http.put("/api/avisos/ligados", json={"ligados": [i["chave"] for i in CATALOGO]})
    assert ligados.status_code == 200, ligados.text


def _avisos(e2e: Cenario) -> list[dict]:
    return [c["corpo"] for c in e2e.helena.chamadas if c["metodo"] == "POST" and c["caminho"] == "/chat/v1/message/send"]


def _aviso_com(e2e: Cenario, titulo: str) -> str:
    achados = [a["body"]["text"] for a in _avisos(e2e) if titulo in a["body"]["text"]]
    assert len(achados) == 1, (titulo, [a["body"]["text"][:40] for a in _avisos(e2e)])
    return achados[0]


def _sem_dado_cru(texto: str) -> None:
    for cru in SINAIS_DE_DADO_CRU:
        assert cru not in texto, f"{cru!r} no texto enviado:\n{texto}"
    codigo = re.search(r"\b[a-z]+_[a-z_]+\b", texto)              # código interno (contrato_assinado, pediu_humano)
    assert not codigo, f"código cru {codigo.group(0)!r} no texto enviado:\n{texto}"


def _novo_lead(e2e: Cenario) -> None:
    e2e.telefone = "5531977" + str(uuid.uuid4().int)[:6]
    e2e.sessao = "sessao-" + uuid.uuid4().hex[:12]


# ============================================================================ 0) sem banco
def test_textos_das_pontes_sem_codigo_nem_nome_generico():
    from app import automacoes, ia_controle, notificacoes
    from app.contrato import resumo as cresumo
    from app.pipeline import Atendimento

    # {{Nome}} com maiúscula ou espaço vale; marcador desconhecido some com a linha (nunca vai cru).
    assert notificacoes.renderizar_modelo("Oi {{Nome}}\nTel: {{ TELEFONE }}\nCPF: {{cpf}}\nfim",
                                          {"nome": "Ana", "telefone": "(11) 9"}) == "Oi Ana\nTel: (11) 9\nfim"
    # Agente do catálogo: o nome do produto da biblioteca; sem ele, o slug legível; nunca "Produto do catálogo".
    config = {"catalogo": {"slug": "bpc-loas-idoso", "papeis": {"sdr": {}}}}
    assert cresumo.nome_do_caso("catalogo", config, "BPC/LOAS Idoso") == "BPC/LOAS Idoso"
    assert cresumo.nome_do_caso("catalogo", config) == "Bpc loas idoso"
    assert cresumo.nome_do_caso("catalogo", {}) == "não informado"
    assert cresumo.nome_do_caso("auxilio_acidente", {}) == "Auxílio-Acidente"
    # Catálogo de auxílio-acidente: o resumo do contrato usa o prompt do auxílio-acidente (antes caía no geral).
    caso = cresumo.nome_do_caso("catalogo", {"catalogo": {"slug": "auxilio-acidente"}})
    assert cresumo.prompt_padrao(caso) == cresumo.PROMPT_AUXILIO_ACIDENTE
    # Nota das automações: troca comum sem "Motivo: transferencia:closer"; os outros motivos seguem.
    assert Atendimento._motivo_da_nota("transferencia:closer") == "" and Atendimento._motivo_da_nota("catalogo") == ""
    assert Atendimento._motivo_da_nota("sinal:analise_humana") == "Motivo: sinal:analise_humana"
    # Ligar/desligar a IA: a nota nunca cita a plataforma.
    assert not any("Helena" in t for t in ia_controle.ORIGENS.values())
    # CRM automático: o contrato assinado não vira "Lead passou para o agente contrato_assinado".
    crm = {"id_painel": "p", "etapas_por_tipo": COLUNAS}
    regras = automacoes.regras_automaticas({"catalogo": {"papeis": {"sdr": {}, "closer": {}}}}, crm)
    assert "nota" not in regras["etapa:contrato_assinado"]
    assert regras["etapa:closer"]["nota"] == "🔄 Lead passou para o agente Closer."
    # Passagens para a equipe que não tinham aviso na tela: análise manual, ligação, presencial, auditiva, comercial.
    from app.gestao.rotas_avisos import TODAS_AS_CHAVES
    for tipo in ("etapa:analise_manual", "sinal:ligacao_telefonica", "sinal:atendimento_presencial",
                 "sinal:deficiencia_auditiva", "sinal:parceria_comercial", "contrato_falhou", "trava"):
        assert tipo in TODAS_AS_CHAVES, tipo
    gatilhos = automacoes.gatilhos_do_turno(primeira_resposta=False, etapa_antes="sdr", etapa_depois="sdr",
                                            motivo_estado="analise_manual:portao_preso", situacao="respondido", sinais=[])
    acoes = automacoes.montar_acoes({"funcoes": {"avisos": True}}, None, gatilhos, id_lead="l", id_turno="t",
                                    avisos={"etapa:analise_manual"})
    assert [a["dados"]["evento"] for a in acoes if a["tipo"] == "preparar_aviso"] == ["etapa:analise_manual"]


# ============================================================================ 1) funil inteiro, por família
@pytest.mark.parametrize("slug,nome", FAMILIAS, ids=[f[0] for f in FAMILIAS])
async def test_funil_inteiro_notas_avisos_e_sino_por_produto(e2e: Cenario, slug: str, nome: str):
    await _como_o_painel_monta(e2e, slug, nome)
    await _gestor(e2e)
    await _ligar_avisos_pelo_painel(e2e)
    link = f"https://{DOMINIO}/redirect?type=SESSION&id={e2e.sessao}"

    # --- lead novo: nota de início (antes da 1ª mensagem) e aviso "Novo lead"
    e2e.ia.etapa = lambda _s, _c: responde("Oi, Carla! Me conta o que aconteceu?")
    await e2e.chega(e2e.do_lead("Oi, vi o anúncio"))
    notas = e2e.helena.notas()
    assert re.fullmatch(r"🤖 Atendimento iniciado pelo agente Ana \(SDR\) às \d\d:\d\d", notas[0]), notas
    novo = _aviso_com(e2e, "NOVO LEAD")
    assert "👤 *Cliente:* Carla Mendes" in novo and "📞 *WhatsApp:* (31) 977" in novo
    assert f"🛒 *Produto:* {nome}" in novo and f"💬 *Conversa:* {link}" in novo
    assert "🎯 *Etapa:*" not in novo or "sdr" not in novo.split("🎯 *Etapa:*")[1].split("\n")[0]
    _sem_dado_cru(novo)
    assert _avisos(e2e)[0]["to"] == DESTINO and _avisos(e2e)[0]["from"] == e2e.ids["numero_canal"]

    # --- SDR -> Closer: nota da troca, card na coluna Comercial e aviso "Lead qualificado"
    e2e.ia.etapa = lambda _s, _c: responde("Entendi. Seu caso tem chance.", FRASE_CLOSER, transferir_para="closer")
    await e2e.chega(e2e.do_lead("quero saber se tenho direito"))
    assert (await e2e.lead())["etapa"] == "closer"
    assert "🔄 Lead passou para o agente Closer." in e2e.helena.notas()
    qualificado = _aviso_com(e2e, "LEAD QUALIFICADO")
    assert f"🛒 *Produto:* {nome}" in qualificado and "Lead qualificado (proposta)" in qualificado
    _sem_dado_cru(qualificado)

    # --- Closer -> Contratos: aviso "Iniciou a coleta de dados"
    e2e.ia.etapa = lambda _s, _c: responde("Ótimo! Vamos para o contrato.", transferir_para="contratos")
    await e2e.chega(e2e.do_lead("aceito os honorários"))
    assert (await e2e.lead())["etapa"] == "contratos"
    assert "🔄 Lead passou para o agente Contratos." in e2e.helena.notas()
    _sem_dado_cru(_aviso_com(e2e, "INICIOU A COLETA DE DADOS"))

    # --- contrato gerado (ZapSign falsa): link ao lead, nota de acompanhamento e aviso "Aguardando assinatura"
    fatos = [("nome_completo", "Carla Mendes Ribeiro", "Carla Mendes Ribeiro"), ("cpf", CPF_FICTICIO, CPF_FICTICIO),
             ("endereco", "Rua das Flores", "Rua das Flores"), ("numero_casa", "120", "120"), ("bairro", "Centro", "Centro"),
             ("cidade", "Belo Horizonte", "Belo Horizonte"), ("uf", "MG", "MG"), ("cep", "30110-012", "30110-012"),
             ("nome_menor", "Pedro Mendes Ribeiro", "Pedro Mendes Ribeiro")]
    e2e.ia.extrator = lambda _s, c: extrai(fatos) if "Rua das Flores" in c.split("MENSAGENS NOVAS")[-1] else extrai()
    e2e.ia.etapa = lambda _s, c: responde("Perfeito! Vou gerar o seu contrato.", ferramenta="zapsign") \
        if "Rua das Flores" in c else responde("Pode me mandar seus dados?")
    await e2e.chega(e2e.do_lead("Confirmo: Carla Mendes Ribeiro, CPF " + CPF_FICTICIO + ", Rua das Flores 120, Centro, "
                                "Belo Horizonte MG, CEP 30110-012. Meu filho é o Pedro Mendes Ribeiro."))
    lead = await e2e.lead()
    contrato = await e2e.pool.fetchrow("select * from agentesia_contratos where id_lead = $1", lead["id"])
    assert contrato and contrato["situacao"] == "gerado", [n for n in e2e.helena.notas() if "contrato" in n.lower()]
    assert lead["etapa"] == "assinatura"
    assert any(n.startswith("Acompanhar lead pois acabou de gerar um contrato.") for n in e2e.helena.notas())
    assinatura = _aviso_com(e2e, "AGUARDANDO ASSINATURA")
    assert f"✍️ *Link de assinatura:* https://app.zapsign.com.br/verificar/{e2e.helena.prefixo}-1" in assinatura
    _sem_dado_cru(assinatura)

    # --- contrato assinado: nota com o caso certo e aviso "Contrato assinado" com o resumo
    e2e.helena.zapsign_assinado = True
    assert (await e2e.zapsign({"event_type": "doc_signed", "token": contrato["id_documento_externo"],
                               "signer_who_signed": {"token": f"signer-{e2e.helena.prefixo}-1"}})).status_code == 200
    await e2e.rodar_fila()
    nota_assinado = next(n for n in e2e.helena.notas() if n.startswith("📄 Contrato Assinado!"))
    assert f"📂 Caso: {nome}" in nota_assinado
    _sem_dado_cru(nota_assinado)
    assinado = _aviso_com(e2e, "CONTRATO ASSINADO")
    assert f"🛒 *Produto:* {nome}" in assinado and "Resumo: acidente de trabalho" in assinado and link in assinado
    _sem_dado_cru(assinado)

    # Nada saiu duas vezes: um aviso por evento (dedup da fila e da janela).
    titulos = [a["body"]["text"].split("\n")[0] for a in _avisos(e2e)]
    assert len(titulos) == len(set(titulos)), titulos
    for nota in e2e.helena.notas():
        _sem_dado_cru(nota)

    # --- sino do painel: o que aconteceu, com o nome do lead
    sino = (await e2e.http.get("/api/central-notificacoes")).json()
    titulos_sino = [i["titulo"] for i in sino["itens"]]
    assert "Lead qualificado: Carla Mendes" in titulos_sino
    assert "Contrato de honorários enviado para Carla Mendes" in titulos_sino
    assert "Contrato assinado por Carla Mendes" in titulos_sino
    # O assinado entra pela hora da assinatura na ZapSign (a falsa diz "ontem"): já conta como lido.
    assert sino["nao_lidas"] >= 2, [(i["tipo"], i["momento"], i["lida"]) for i in sino["itens"]]
    assert (await e2e.http.post("/api/central-notificacoes/lidas", json={})).json()["ok"]
    assert (await e2e.http.get("/api/central-notificacoes")).json()["nao_lidas"] == 0


# ============================================================================ 2) saídas da IA: humano, desqualificado
@pytest.mark.parametrize("slug,nome", FAMILIAS[:2] + FAMILIAS[4:], ids=["auxilio-acidente", "bpc-loas-infantil", "previdenciario"])
async def test_pediu_humano_desqualificado_pausa_e_religa(e2e: Cenario, slug: str, nome: str):
    await _como_o_painel_monta(e2e, slug, nome)
    await _gestor(e2e)
    await _ligar_avisos_pelo_painel(e2e)

    # Pediu uma pessoa: nota 🙋, IA sai da conversa, aviso com o que o lead disse e item no sino.
    e2e.ia.etapa = lambda _s, _c: responde("Oi! Me conta o que aconteceu?")
    await e2e.chega(e2e.do_lead("oi"))
    e2e.ia.extrator = lambda _s, _c: extrai(pediu_humano=True)
    await e2e.chega(e2e.do_lead("quero falar com um atendente"))          # 1º pedido: a IA tenta resolver
    assert (await e2e.lead())["estado"] == "ativo"
    await e2e.chega(e2e.do_lead("quero falar com uma pessoa de verdade"))  # 2º pedido: a equipe assume
    lead = await e2e.lead()
    assert (lead["estado"], lead["motivo_estado"]) == ("pausado", "pediu_humano")
    assert any(n.startswith("🙋 O lead pediu para falar com uma pessoa. A IA saiu da conversa") for n in e2e.helena.notas())
    humano = _aviso_com(e2e, "PEDIU UMA PESSOA")
    assert "quero falar com uma pessoa de verdade" in humano and f"🛒 *Produto:* {nome}" in humano
    assert "🎯 *Etapa:* SDR\n" in humano                                  # o nome da etapa, não o código "sdr"
    _sem_dado_cru(humano)
    sino = [i["titulo"] for i in (await e2e.http.get("/api/central-notificacoes")).json()["itens"]]
    assert "IA pausada: o lead pediu um atendente" in sino

    # Religada pelo botão da Helena: nota e a IA volta.
    assert (await e2e.botao_ia("ligar")).status_code == 200
    await e2e.rodar_fila()
    assert any(n.startswith("🤖 IA religada nesta conversa") for n in e2e.helena.notas())

    # Outro lead, desqualificado: nota com o motivo e aviso "Lead desqualificado".
    _novo_lead(e2e)
    e2e.ia.extrator = lambda _s, _c: extrai()
    e2e.ia.etapa = lambda _s, _c: responde("Oi! Me conta o que aconteceu?")
    await e2e.chega(e2e.do_lead("oi"))
    e2e.ia.etapa = lambda _s, _c: responde("Entendi. Infelizmente não conseguimos seguir.", transferir_para="desqualificado")
    await e2e.chega(e2e.do_lead("já sou aposentada"))
    assert (await e2e.lead())["etapa"] == "desqualificado"
    desq = [n for n in e2e.helena.notas() if "desqualificado" in n.lower()]
    assert desq and all("Helena" not in n for n in desq), e2e.helena.notas()
    aviso = _aviso_com(e2e, "LEAD DESQUALIFICADO")
    assert "👤 *Cliente:* Carla Mendes" in aviso
    _sem_dado_cru(aviso)

    # Equipe desliga a IA pelo painel: entra no sino como "IA desativada" (o próprio usuário não vê o dele).
    for nota in e2e.helena.notas():
        _sem_dado_cru(nota)


# ============================================================================ 3) prompt mudado pelo painel
async def test_prompt_mudado_pelo_painel_vale_no_proximo_turno_e_troca_a_chave_de_cache(e2e: Cenario):
    """Editor do produto (Sincronizar): o prompt novo vai para o modelo no turno seguinte; o antigo some. A chave de
    cache da OpenAI muda junto (ela é o resumo do começo do sistema), então o cache nunca serve o prompt velho."""
    from app.modelo import chave_de_cache

    id_bib = await _como_o_painel_monta(e2e, "auxilio-acidente", "Auxílio-Acidente")
    await _gestor(e2e)
    pool = e2e.pool
    id_ativado = await pool.fetchval(
        """insert into agentesia_produtos_ativados (id_escritorio, id_produto_biblioteca, nome, status, id_agente)
           values ($1::uuid, $2::uuid, 'Ana', 'ativo', $3::uuid) returning id""",
        e2e.ids["escritorio"], id_bib, e2e.ids["agente"])
    await pool.execute("update agentesia_agentes set id_produto_ativado = $2::uuid where id = $1::uuid", e2e.ids["agente"], id_ativado)

    antigo = "Você é a Ana, do escritório. ROTEIRO ANTIGO: pergunte como foi o acidente."
    novo = "Você é a Ana, do escritório. ROTEIRO NOVO: pergunte primeiro a cidade do lead."
    trecho = "TRECHO ACRESCENTADO: sempre chame o lead pelo primeiro nome."
    papeis = ["sdr", "periododegraca", "closer", "contratos", "assinatura", "desqualificado"]

    async def sincronizar(prompt_sdr: str) -> None:
        resposta = await e2e.http.post(f"/api/produtos-ativados/{id_ativado}/sincronizar", json={
            "nome": "Ana", "id_canal": e2e.ids["canal"], "followup_ativo": False,
            "agentes": [{"papel": p, "nome": p.title(), "prompt": prompt_sdr if p == "sdr" else f"Prompt do {p}."}
                        for p in papeis]})
        assert resposta.status_code == 200, resposta.text

    await sincronizar(antigo)
    e2e.ia.etapa = lambda _s, _c: responde("Oi! Como foi o acidente?")
    await e2e.chega(e2e.do_lead("oi"))
    sistema_1 = e2e.pedidos("etapa")[-1]["sistema"]
    assert "ROTEIRO ANTIGO" in sistema_1

    await sincronizar(novo + "\n" + trecho)
    await e2e.chega(e2e.do_lead("tudo bem?"))
    sistema_2 = e2e.pedidos("etapa")[-1]["sistema"]
    assert "ROTEIRO NOVO" in sistema_2 and trecho in sistema_2 and "ROTEIRO ANTIGO" not in sistema_2
    assert chave_de_cache("etapa", "gpt-4.1-mini", sistema_1) != chave_de_cache("etapa", "gpt-4.1-mini", sistema_2)
    # A versão ficou gravada (Versões do produto) com o prompt novo.
    versoes = (await e2e.http.get(f"/api/produtos-ativados/{id_ativado}/versoes")).json()
    assert versoes and len(versoes if isinstance(versoes, list) else versoes.get("versoes", [])) >= 2

    # Instrução da etapa pela tela da equipe LawChat (PUT /agentes/:id/etapas/:codigo): vale no turno seguinte.
    from app.gestao import seguranca
    email = f"admin-{uuid.uuid4().hex[:6]}@lawchat.test"
    await pool.execute("insert into agentesia_usuarios (email, nome, senha_hash, papel) values ($1, 'Equipe', $2, 'admin_lawchat')",
                       email, seguranca.gerar_hash("senha-admin-123"))
    assert (await e2e.http.post("/api/entrar", json={"email": email, "senha": "senha-admin-123"})).status_code == 200
    terceira = "Você é a Ana. ROTEIRO DA EQUIPE LAWCHAT: confirme o telefone."
    resposta = await e2e.http.put(f"/api/agentes/{e2e.ids['agente']}/etapas/sdr", headers={"x-escritorio": e2e.ids["escritorio"]},
                                  json={"instrucao": terceira})
    assert resposta.status_code == 200, resposta.text
    await e2e.chega(e2e.do_lead("e agora?"))
    sistema_3 = e2e.pedidos("etapa")[-1]["sistema"]
    assert "ROTEIRO DA EQUIPE LAWCHAT" in sistema_3 and "ROTEIRO NOVO" not in sistema_3


async def test_cache_da_config_em_outro_processo_segura_ate_30_s(e2e: Cenario, monkeypatch):
    """Produção roda o painel e a IA em processos separados: a escrita no painel não apaga o cache da IA, que guarda
    o agente do canal por AGENTESIA_CACHE_CONFIG_S (30 s). Simula o outro processo: cache ligado e escrita direta."""
    from app.banco import postgres
    from app.gestao import cache_curto

    monkeypatch.setattr(cache_curto, "LIGADO", True)
    postgres.limpar_cache_da_config()
    e2e.ia.etapa = lambda _s, _c: responde("Oi!")
    await e2e.pool.execute("update agentesia_agente_etapas set instrucao = 'ROTEIRO UM: diga oi.' where id = $1::uuid",
                           e2e.ids["etapas"]["sdr"])
    postgres.limpar_cache_da_config()
    await e2e.chega(e2e.do_lead("oi"))
    assert "ROTEIRO UM" in e2e.pedidos("etapa")[-1]["sistema"]
    await e2e.pool.execute("update agentesia_agente_etapas set instrucao = 'ROTEIRO DOIS: diga olá.' where id = $1::uuid",
                           e2e.ids["etapas"]["sdr"])
    await e2e.chega(e2e.do_lead("oi de novo"))
    ainda = e2e.pedidos("etapa")[-1]["sistema"]
    # Dentro da janela do cache a IA do outro processo ainda usa o prompt anterior (registrado no relatório).
    assert "ROTEIRO UM" in ainda and "ROTEIRO DOIS" not in ainda
    postgres.limpar_cache_da_config()                       # = passaram os 30 s
    await e2e.chega(e2e.do_lead("e agora?"))
    assert "ROTEIRO DOIS" in e2e.pedidos("etapa")[-1]["sistema"]


# ============================================================================ 4) follow-up: cadência mudada pelo painel
async def test_cadencia_mudada_pelo_painel_reprograma_os_agendados_e_vale_para_os_novos(e2e: Cenario, monkeypatch):
    from app.followup import servico
    from app.canal.helena_conta import HelenaConta

    await _como_o_painel_monta(e2e, "auxilio-acidente", "Auxílio-Acidente")
    await _gestor(e2e)
    pool, agente = e2e.pool, e2e.ids["agente"]
    todo_dia = {"inicio": 0, "fim": 24, "dias": [0, 1, 2, 3, 4, 5, 6]}
    tela = (await e2e.http.get(f"/api/agentes/{agente}/followup")).json()["config"]

    async def salvar(passos: list[float], desistir_h: float = 24) -> dict:
        resposta = await e2e.http.put(f"/api/agentes/{agente}/followup", json={
            **tela, "ativo": True, "horario": todo_dia, "intervalo_minimo_min": 10, "decidir": False,
            "desistir": {"ativo": True, "apos_horas": desistir_h, "nota": ""},
            "passos": [{"apos_horas": h, "modo": "texto", "texto": f"Oi {{nome}}! Lembrete de {h:g} h.", "instrucao": ""} for h in passos]})
        assert resposta.status_code == 200, resposta.text
        return resposta.json()

    await salvar([4, 24])
    # Lead A respondeu agora: a IA respondeu e o follow-up foi agendado para daqui 4 h.
    e2e.ia.etapa = lambda _s, _c: responde("Oi! Me conta o que aconteceu?")
    await e2e.chega(e2e.do_lead("oi"))
    lead_a = (await e2e.lead())["id"]
    fu = await pool.fetchrow("select * from agentesia_followups where id_lead = $1 and situacao = 'pendente'", lead_a)
    assert fu and abs((fu["agendado_para"] - (fu["base"] + timedelta(hours=4))).total_seconds()) < 60

    # Lead B já recebeu o último toque e espera a desistência (24 h depois do envio).
    _novo_lead(e2e)
    await e2e.chega(e2e.do_lead("oi"))
    lead_b = (await e2e.lead())["id"]
    await pool.execute("update agentesia_followups set situacao = 'enviado' where id_lead = $1 and situacao = 'pendente'", lead_b)
    enviado_ha = datetime.now(timezone.utc) - timedelta(hours=1)
    await pool.execute(
        """insert into agentesia_followups (id_escritorio, id_lead, id_agente, passo, base, agendado_para, criado_em)
           values ($1::uuid, $2, $3::uuid, 2, $4, $5, $4)""",
        e2e.ids["escritorio"], lead_b, agente, enviado_ha, enviado_ha + timedelta(hours=24))

    # Muda a cadência no painel: 1 h e 3 h; desistência em 2 h.
    corpo = await salvar([1, 3], desistir_h=2)
    assert corpo["reprogramacao"] == {"reprogramados": 2, "cancelados": 0}, corpo["reprogramacao"]
    a = await pool.fetchrow("select * from agentesia_followups where id_lead = $1 and situacao = 'pendente'", lead_a)
    assert abs((a["agendado_para"] - (a["base"] + timedelta(hours=1))).total_seconds()) < 60
    b = await pool.fetchrow("select * from agentesia_followups where id_lead = $1 and situacao = 'pendente'", lead_b)
    assert b["passo"] == 2 and abs((b["agendado_para"] - (enviado_ha + timedelta(hours=2))).total_seconds()) < 60

    # Lead novo depois da mudança: já nasce na cadência nova.
    _novo_lead(e2e)
    await e2e.chega(e2e.do_lead("boa tarde"))
    lead_c = (await e2e.lead())["id"]
    c = await pool.fetchrow("select * from agentesia_followups where id_lead = $1 and situacao = 'pendente'", lead_c)
    assert abs((c["agendado_para"] - (c["base"] + timedelta(hours=1))).total_seconds()) < 60

    # Relógio: passa 1 h para o lead A. O worker manda o texto do passo novo e agenda o seguinte (3 h).
    enviadas: list[dict] = []

    def helena(pedido: httpx.Request) -> httpx.Response:
        enviadas.append({"caminho": pedido.url.path, **json.loads(pedido.content or b"{}")})
        return httpx.Response(200, json={"id": f"fu-{uuid.uuid4().hex[:8]}"})

    disparador = servico.Disparador(pool, ModeloFalso({}), "https://api.helena.falsa", helena_por_token=lambda t, u: HelenaConta(
        t, u, httpx.AsyncClient(transport=httpx.MockTransport(helena))))
    await pool.execute("update agentesia_followups set situacao = 'cancelado' where situacao = 'pendente' and id_lead <> all($1::uuid[])",
                       [lead_a, lead_b, lead_c])
    assert await disparador.rodar_uma_vez() == 0                         # ninguém venceu ainda
    real = servico.agora
    monkeypatch.setattr(servico, "agora", lambda: real() + timedelta(hours=1, minutes=1))
    await pool.execute("update agentesia_followups set agendado_para = agendado_para - interval '61 minutes' where id_lead = $1 and situacao = 'pendente'", lead_a)
    assert await disparador.rodar_uma_vez() >= 1
    textos = [e.get("text") for e in enviadas if e.get("text")]
    assert any(t.startswith("Oi Carla! Lembrete de 1 h.") for t in textos), textos
    proximo = await pool.fetchrow("select * from agentesia_followups where id_lead = $1 and situacao = 'pendente'", lead_a)
    assert proximo["passo"] == 1
    assert abs((proximo["agendado_para"] - (proximo["base"] + timedelta(hours=3))).total_seconds()) < 120
    nota = await pool.fetchval("select dados->>'texto' from agentesia_acoes where id_lead = $1 and tipo = 'nota' "
                               "and dados->>'texto' like '🔁%' order by criado_em desc limit 1", lead_a)
    assert nota and nota.startswith("🔁 Follow-up 1 de 2 enviado às ") and "Helena" not in nota
