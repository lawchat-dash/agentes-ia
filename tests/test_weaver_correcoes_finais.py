"""Regressões da correção final do Weaver: card de lead só para lead de verdade, card do lead novo que não volta
para SDR, nota de IA desligada só para lead ativo, contato sem número por classe, mês inventado pelo extrator,
data fora do sistema do catálogo (cache), zapsign sem a função de contrato, COMEÇO DA CONVERSA com as antigas mais
recentes, auditor do outro_beneficio com o benefício do produto e a tela Conversas (gaveta, busca e prévia)."""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from app import memoria
from app.cerebro import auditor, catalogo, extrator, sinais, turno
from app.cerebro.auxilio_acidente import calcular_periodo_graca
from app.cerebro.produto import AuxilioAcidente
from app.modelo import ModeloFalso
from tests.test_catalogo_weaver import AGORA, entrada, extrai as extrai_catalogo, produto, resposta
from tests.test_pipeline import CANAL, LEAD, SIMPLES, montar, webhook
from tests.test_turno import extrai

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
RAIZ = Path(__file__).resolve().parent.parent
CRM = {"funcoes": {"crm": True}, "automacoes": {"lead_novo": {"coluna_crm": "col-sdr"}}}
TRACK = {"pageUtm": {"referralUrl": "https://fb.me/abc", "clid": "ARAkLm123", "campaign": "aa-mg"}}


def _com_crm(repo, filtro=None):
    repo.agentes["canal-1"].config.update(json.loads(json.dumps(CRM)))
    repo.crm["esc-1"] = {"id_painel": "painel-1"}
    if filtro:
        repo.escritorios["esc-1"].config["filtro"] = filtro


def _do_crm(repo):
    return [a["tipo"] for a in repo.acoes if a["tipo"] in ("mover_card", "etiquetar")]


def _notas(repo):
    return [a["dados"]["texto"] for a in repo.acoes if a["tipo"] == "nota"]


# ----------------------------------------------------------------------------- 1. card só para lead de verdade
async def test_numero_bloqueado_nao_ganha_card_nem_etiqueta_sdr():
    atendimento, repo, _helena = montar(SIMPLES)
    _com_crm(repo, {"numeros_bloqueados": [LEAD]})
    resultado = await atendimento.receber(webhook("oi, aqui é da equipe"))
    assert resultado["motivo"] == "numero_bloqueado"
    assert _do_crm(repo) == [] and not [e for e in repo.eventos if e["tipo"] == "card_nao_criado"]


async def test_proprio_numero_do_canal_nao_ganha_card():
    atendimento, repo, _helena = montar(SIMPLES, numeros_teste=(CANAL,))
    _com_crm(repo)
    resultado = await atendimento.receber(webhook("teste", de=CANAL))
    assert resultado["motivo"] == "conversa_consigo_mesmo" and _do_crm(repo) == []


async def test_rastreio_de_numero_bloqueado_ou_do_canal_nao_ganha_card():
    atendimento, repo, _helena = montar(SIMPLES)
    _com_crm(repo, {"numeros_bloqueados": [LEAD]})
    assert (await atendimento.receber(webhook("", tipo="TRACK", track=TRACK)))["feito"] == "origem"
    assert (await atendimento.receber(webhook("", tipo="TRACK", track=TRACK, de=CANAL)))["feito"] == "origem"
    assert _do_crm(repo) == []


async def test_lead_de_verdade_continua_ganhando_card_na_chegada_e_no_rastreio():
    atendimento, repo, _helena = montar(SIMPLES)
    _com_crm(repo)
    await atendimento.receber(webhook("", tipo="TRACK", track=TRACK))
    assert _do_crm(repo) == ["mover_card", "etiquetar"]


# ----------------------------------------------------------------------------- 3. IA desligada ou pausada só nota lead ativo
async def _lead_existente(atendimento, repo, estado, motivo):
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    lead = next(iter(repo.leads.values()))
    lead.estado, lead.motivo_estado, lead.pausado_ate = estado, motivo, None
    repo.acoes.clear()
    repo.eventos.clear()
    return lead


@pytest.mark.parametrize("estado, motivo", [("pausado", "humano_assumiu"), ("encerrado", "pediu_para_parar")])
async def test_agente_pausado_nao_deixa_nota_em_lead_com_humano_ou_encerrado(estado, motivo):
    atendimento, repo, helena = montar(SIMPLES)
    await _lead_existente(atendimento, repo, estado, motivo)
    repo.agentes["canal-1"].situacao = "pausado"
    enviadas = list(helena.enviadas)
    await atendimento.receber(webhook("alô?"))
    await atendimento.aguardar_esperas()
    assert helena.enviadas == enviadas and _notas(repo) == []
    assert not [e for e in repo.eventos if e["tipo"] == "agente_pausado"]
    assert list(repo.turnos.values())[-1]["motivo"] == "lead_" + estado


async def test_ia_desligada_nao_deixa_nota_em_lead_com_humano():
    atendimento, repo, _helena = montar(SIMPLES)
    await _lead_existente(atendimento, repo, "pausado", "humano_assumiu")
    repo.escritorios["esc-1"].ia_desligada = True
    await atendimento.receber(webhook("alô?"))
    await atendimento.aguardar_esperas()
    assert _notas(repo) == [] and not [e for e in repo.eventos if e["tipo"] == "ia_desligada_no_escritorio"]


@pytest.mark.parametrize("situacao", ["suspenso", "encerrado"])
async def test_escritorio_inativo_fica_em_silencio_sem_nota_nem_card(situacao):
    atendimento, repo, helena = montar(SIMPLES)
    _com_crm(repo)
    repo.escritorios["esc-1"].situacao = situacao
    repo.escritorios["esc-1"].ia_desligada = True                     # como o banco devolve (situacao <> 'ativo')
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    assert helena.enviadas == [] and repo.acoes == [] and repo.eventos == []
    assert next(iter(repo.turnos.values()))["motivo"] == "escritorio_inativo"


# ----------------------------------------------------------------------------- 4. contato sem número, por classe
def _sem_to(corpo):
    corpo["content"]["details"]["to"] = ""
    return corpo


async def test_atendente_sem_numero_acha_o_lead_pela_sessao_e_pausa_a_ia():
    atendimento, repo, _helena = montar(SIMPLES)
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    corpo = _sem_to(webhook("*Paula:* oi, aqui é a Paula", de=CANAL, para=LEAD, direcao="TO_HUB", origem="DEFAULT",
                            evento="MESSAGE_SENT"))
    assert (await atendimento.receber(corpo))["feito"] == "pausado"
    lead = next(iter(repo.leads.values()))
    assert lead.estado == "pausado" and lead.motivo_estado == "humano_assumiu"
    assert (repo.mensagens[lead.id][-1].autor, repo.mensagens[lead.id][-1].texto) == ("humano", "oi, aqui é a Paula")
    assert not [e for e in repo.eventos if e["tipo"] == "contato_sem_numero"]


async def test_atendente_sem_numero_e_sem_lead_e_api_sem_numero_nao_geram_evento():
    atendimento, repo, _helena = montar(SIMPLES)
    humano = _sem_to(webhook("*Paula:* oi", de=CANAL, para=LEAD, direcao="TO_HUB", origem="DEFAULT", evento="MESSAGE_SENT"))
    api = _sem_to(webhook("Lembrete", de=CANAL, para=LEAD, direcao="TO_HUB", origem="API", evento="MESSAGE_SENT"))
    assert (await atendimento.receber(humano))["motivo"] == "contato_sem_numero"
    assert (await atendimento.receber(api))["motivo"] == "contato_sem_numero"
    assert repo.eventos == [] and repo.acoes == [] and repo.leads == {}


# ----------------------------------------------------------------------------- 5. o extrator não inventa o mês
def test_mes_tirado_de_ano_passado_e_rejeitado():
    dados = {"fatos": [{"chave": "acidente_mes", "valor": 11, "trecho": "ano passado"},
                       {"chave": "acidente_ano", "valor": 2025, "trecho": "ano passado"},
                       {"chave": "demissao_mes", "valor": 5, "trecho": "em 2024"}]}
    extracao = extrator.conferir(dados, ["o acidente foi ano passado", "saí em 2024"], {})
    assert [(f.chave, f.valor) for f in extracao.fatos] == [("acidente_ano", 2025)]
    assert {r["chave"]: r["motivo"] for r in extracao.rejeitados} == {"acidente_mes": "mes_sem_prova",
                                                                       "demissao_mes": "mes_sem_prova"}


def test_mes_dito_continua_valendo():
    textos = ["saí da firma em março de 2024", "o acidente foi há 3 meses", "foi em 11/2025", "11"]
    dados = {"fatos": [{"chave": "demissao_mes", "valor": 3, "trecho": "em março de 2024"},
                       {"chave": "acidente_mes", "valor": 8, "trecho": "há 3 meses"}]}
    assert [f.chave for f in extrator.conferir(dados, textos, {}).fatos] == ["demissao_mes", "acidente_mes"]
    for trecho in ("11/2025", "11"):
        assert extrator.conferir({"fatos": [{"chave": "acidente_mes", "valor": 11, "trecho": trecho}]}, textos, {}).fatos


def test_regra_8_nao_manda_converter_ano_passado_em_mes():
    sistema = extrator.sistema_do_extrator(AuxilioAcidente())
    assert "converta para mês e ano" not in sistema
    assert '"Ano passado" ou "faz uns 2 anos" dão só o ano: nunca preencha o mês' in sistema


async def test_ano_passado_deixa_o_periodo_de_graca_na_duvida():
    """24/11/2026: saiu em 03/2024, sem seguro; acidente "ano passado". Com o mês inventado (11) daria 20 meses e
    desqualificaria; sem o mês, a faixa é de 10 a 21 meses e o sistema pergunta o mês."""
    fatos = {"demissao_mes": 3, "demissao_ano": 2024, "seguro_desemprego": "nao", "contribuiu_por_conta_propria": "nao"}
    extracao = extrator.conferir({"fatos": [{"chave": "acidente_mes", "valor": 11, "trecho": "ano passado"},
                                            {"chave": "acidente_ano", "valor": 2025, "trecho": "ano passado"}]},
                                 ["o acidente foi ano passado"], fatos)
    depois = {**fatos, **{f.chave: f.valor for f in extracao.fatos}}
    assert "acidente_mes" not in depois and depois["acidente_ano"] == 2025
    duvida = calcular_periodo_graca(depois)
    assert (duvida.resultado, duvida.faltam) == ("faltam_dados", ("acidente_mes",))
    assert calcular_periodo_graca({**depois, "acidente_mes": 11}).resultado == "fora"   # o que o mês inventado fazia


# ----------------------------------------------------------------------------- 6. data fora do sistema do catálogo
async def test_sistema_do_catalogo_igual_em_minutos_diferentes():
    sistemas, conteudos = [], []
    for minutos in (0, 7):
        modelo = ModeloFalso({"extrator": extrai_catalogo(), "etapa": resposta()})
        dados = entrada(["oi"])
        dados.agora = AGORA + timedelta(minutes=minutos)
        await turno.processar(modelo, dados)
        sistemas.append(modelo.pedidos[1]["sistema"])
        conteudos.append(modelo.pedidos[1]["conteudo"])
    assert sistemas[0] == sistemas[1] and "14:30" not in sistemas[0]
    assert conteudos[0].startswith("Hoje é 24/11/2026 (terça-feira), horário de Brasília 14:30.")
    assert conteudos[1].startswith("Hoje é 24/11/2026 (terça-feira), horário de Brasília 14:37.")


# ----------------------------------------------------------------------------- 7. zapsign sem a função de contrato
async def test_prompt_com_zapsign_nao_liga_a_ferramenta_sem_a_funcao_de_contrato():
    roteiro = "Confirme os dados e gere o contrato com @ZapSign. Depois acionar tool `Desenvolver Documento`."
    modelo = ModeloFalso({"extrator": extrai_catalogo(), "etapa": resposta("Vou gerar seu contrato.", ferramenta="zapsign")})
    dados = entrada(["sim, está certo"], etapa="contratos", prod=produto(contrato=False))
    dados.instrucoes = {"contratos": roteiro}
    saida = await turno.processar(modelo, dados)
    pedido = modelo.pedidos[1]
    assert "zapsign" not in pedido["esquema"]["properties"]["ferramenta"]["enum"]
    assert "zapsign: o sistema gera o contrato" not in pedido["sistema"]
    assert saida.motivo != "dados_confirmados" and saida.contexto["catalogo"]["acoes"] == ["buscar_cep"]
    # Com a função ligada, o mesmo prompt continua acionando o contrato.
    modelo = ModeloFalso({"extrator": extrai_catalogo(), "etapa": resposta("Vou gerar seu contrato.", ferramenta="zapsign")})
    dados = entrada(["sim, está certo"], etapa="contratos", prod=produto(contrato=True))
    dados.instrucoes = {"contratos": roteiro}
    saida = await turno.processar(modelo, dados)
    assert saida.motivo == "dados_confirmados" and "zapsign: o sistema gera o contrato" in modelo.pedidos[1]["sistema"]


# ----------------------------------------------------------------------------- 8. COMEÇO DA CONVERSA: as antigas mais recentes
async def test_comeco_da_conversa_traz_as_60_antigas_mais_perto_da_janela():
    atendimento, repo, _helena = montar(SIMPLES)
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    lead = next(iter(repo.leads.values()))
    repo.mensagens[lead.id].clear()
    inicio = datetime.now(timezone.utc) - timedelta(days=2)
    for i in range(180):
        await repo.gravar_mensagem(lead=lead, autor="lead" if i % 2 == 0 else "ia", tipo="texto", texto=f"msg {i}",
                                   texto_extraido=None, url_midia=None, enviada_em=inicio + timedelta(minutes=i),
                                   id_externo=None, id_turno="turno-velho")
    comeco = await memoria.ler_comeco(repo, lead.id)
    assert comeco.pendentes == 140 and len(comeco.antigas) == 60
    assert comeco.antigas[0]["texto"] == "msg 80" and comeco.antigas[-1]["texto"] == "msg 139"   # sem buraco até a janela
    trecho = await repo.trecho_para_resumir(lead.id)
    assert trecho["mensagens"][0]["texto"] == "msg 0"                    # a ficha continua em ordem, do começo


@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_postgres_comeco_da_conversa_traz_as_antigas_mais_recentes():
    from app.banco.postgres import RepositorioPostgres
    from tests.test_memoria_conversa import _cenario_pg

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        _esc, lead = await _cenario_pg(pool, "Antigas recentes", 180)
        comeco = await memoria.ler_comeco(repo, lead)
        assert comeco.pendentes == 140 and len(comeco.antigas) == 60
        assert comeco.antigas[0]["texto"] == "antiga 80" and comeco.antigas[-1]["texto"] == "antiga 139"
        assert (await repo.historico(lead))[0].texto == "antiga 140"
        trecho = await repo.trecho_para_resumir(lead)
        assert trecho["mensagens"][0]["texto"] == "antiga 0" and len(trecho["mensagens"]) == 140
    finally:
        await pool.execute("delete from agentesia_escritorios where nome = 'Antigas recentes'")
        await repo.fechar()


# ----------------------------------------------------------------------------- 9. auditor do outro_beneficio no catálogo
def test_auditor_do_outro_beneficio_recebe_o_beneficio_do_produto():
    com = auditor.sistema_do_auditor("outro_beneficio", "X", sinais.partes_do_auditor("aposentadoria por idade"))
    assert "benefício em conversa: aposentadoria por idade" in com
    assert "conversa de auxílio-acidente e pergunta de aposentadoria" not in com
    sem = auditor.sistema_do_auditor("outro_beneficio", "X", sinais.partes_do_auditor(None))
    assert "o benefício em conversa não veio do sistema" in sem and "Sem isso claro, é inválido" in sem
    assert "3 ou mais vezes" in auditor.sistema_do_auditor("muitas_objecoes", "X", sinais.partes_do_auditor("BPC"))
    # O Auxílio-Acidente segue com o texto dele.
    assert "conversa de auxílio-acidente e pergunta de aposentadoria" in auditor.sistema_do_auditor("outro_beneficio", "X")


async def test_turno_do_catalogo_passa_o_beneficio_ao_auditor():
    prod = produto(nome="Aposentadoria por idade")
    modelo = ModeloFalso({"extrator": extrai_catalogo(sinais_=["outro_beneficio"]),
                          "auditor": {"valido": False, "motivo": "é o mesmo benefício", "mensagem": ""}, "etapa": resposta()})
    saida = await turno.processar(modelo, entrada(["e a aposentadoria, quanto tempo demora?"], prod=prod, modelo_auditor="auditor"))
    assert "benefício em conversa: Aposentadoria por idade" in modelo.pedidos[1]["sistema"]
    assert saida.sinais == [] and saida.estado_lead is None


# ----------------------------------------------------------------------------- 10 e 11. tela Conversas (painel)
def test_gaveta_de_detalhes_sem_os_botoes_da_ia():
    tela = (RAIZ / "painel" / "src" / "telas" / "Conversas.tsx").read_text(encoding="utf-8")
    gaveta = tela[tela.index("<SheetContent"):tela.index("</SheetContent>")]
    assert "<PainelLateral detalhe={detalhe} ocupado={ocupado} aoAgir={agir} semBotoes />" in gaveta
    assert "<BotoesIa conversa={detalhe} ocupado={ocupado} aoAgir={agir} compacto />" in tela   # ficam no cabeçalho


def test_busca_por_telefone_formatado_manda_os_digitos_e_previa_de_midia():
    tela = (RAIZ / "painel" / "src" / "telas" / "Conversas.tsx").read_text(encoding="utf-8")
    assert "setBuscaAplicada(termoDaBusca(busca))" in tela and 'b.replace(/\\D/g, "")' in tela
    tipos = (RAIZ / "painel" / "src" / "components" / "conversas" / "tipos.ts").read_text(encoding="utf-8")
    lista = (RAIZ / "painel" / "src" / "components" / "conversas" / "ListaConversas.tsx").read_text(encoding="utf-8")
    assert "ultima_mensagem_tipo?: TipoMensagem | null;" in tipos and "TIPOS_MIDIA[tipo]?.rotulo" in tipos
    assert "{previaDaConversa(c) || <i" in lista


@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_postgres_busca_por_telefone_formatado_e_previa_do_audio():
    from app.banco.postgres import RepositorioPostgres
    from app.gestao.repositorio import RepositorioGestao

    banco = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = banco._pool
    try:
        esc = str(await pool.fetchval("insert into agentesia_escritorios (nome) values ('Busca formatada') returning id"))
        canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado) values ($1, $2) returning id",
                                    esc, "5511" + str(uuid.uuid4().int)[:9])
        sufixo = str(uuid.uuid4().int)[:8]
        telefone = "55119" + sufixo
        leads = {}
        for nome, fone in (("Maria Souza", telefone), ("Sem Mensagem", "5531" + str(uuid.uuid4().int)[:9])):
            contato = await pool.fetchval("insert into agentesia_contatos (id_escritorio, nome, telefone_normalizado) "
                                          "values ($1, $2, $3) returning id", esc, nome, fone)
            leads[nome] = str(await pool.fetchval("insert into agentesia_leads (id_escritorio, id_contato, id_canal) "
                                                  "values ($1, $2, $3) returning id", esc, contato, canal))
        await pool.execute(
            """insert into agentesia_mensagens (id_escritorio, id_lead, autor, tipo, texto, texto_extraido, enviada_em) values
                 ($1::uuid, $2::uuid, 'lead', 'texto', 'oi', null, now() - interval '2 minutes'),
                 ($1::uuid, $2::uuid, 'lead', 'audio', null, null, now() - interval '1 minute')""", esc, leads["Maria Souza"])
        gestao = RepositorioGestao(pool)
        formatado = f"(11) 9{sufixo[:4]}-{sufixo[4:]}"
        for busca in (formatado, f"+55 11 9{sufixo[:4]}", f"9{sufixo[:4]}-{sufixo[4:]}", "maria"):
            assert [c["id"] for c in await gestao.conversas(esc, busca)] == [leads["Maria Souza"]], busca
        assert await gestao.conversas(esc, "Maria 11") == []                # com letra é nome: o número não vira telefone
        por_id = {c["id"]: c for c in await gestao.conversas(esc)}
        audio = por_id[leads["Maria Souza"]]
        assert (audio["ultima_mensagem"], audio["ultima_mensagem_tipo"]) == (None, "audio")   # a tela mostra "Áudio"
        vazia = por_id[leads["Sem Mensagem"]]
        assert (vazia["ultima_mensagem"], vazia["ultima_mensagem_tipo"]) == (None, None)       # só aqui "sem mensagens"
        await pool.execute("update agentesia_mensagens set texto_extraido = 'quero saber do meu benefício' "
                           "where id_lead = $1::uuid and tipo = 'audio'", leads["Maria Souza"])
        transcrito = next(c for c in await gestao.conversas(esc) if c["id"] == leads["Maria Souza"])
        assert transcrito["ultima_mensagem"] == "quero saber do meu benefício"
    finally:
        await pool.execute("delete from agentesia_escritorios where nome = 'Busca formatada'")
        await banco.fechar()


# ----------------------------------------------------------------------------- 2. card do lead novo não volta para SDR
@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_postgres_nova_tentativa_do_lead_novo_nao_move_card_que_ja_existe():
    from app import automacoes
    from app.acoes import Executor
    from app.banco.postgres import RepositorioPostgres
    from app.canal.helena_conta import HelenaConta

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        await pool.execute("update agentesia_acoes set situacao = 'cancelada' where situacao in ('pendente', 'executando')")
        segredo = await pool.fetchval("select vault.create_secret('token-card-volta', 'teste')")
        esc = str(await pool.fetchval("insert into agentesia_escritorios (nome) values ('Card não volta') returning id"))
        await pool.execute("insert into agentesia_integracoes (id_escritorio, tipo, id_segredo_vault, situacao) "
                           "values ($1, 'helena', $2, 'ok')", esc, segredo)
        canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado) values ($1, $2) returning id",
                                    esc, "5511" + str(uuid.uuid4().int)[:9])
        ids = []
        for i in range(3):
            contato = await pool.fetchval("insert into agentesia_contatos (id_escritorio, telefone_normalizado, id_contato_helena) "
                                          "values ($1, $2, $3) returning id", esc, "5511" + str(uuid.uuid4().int)[:9], f"contato-{i}")
            ids.append(str(await pool.fetchval("insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_sessao_helena) "
                                               "values ($1, $2, $3, $4) returning id", esc, contato, canal, f"sessao-{i}")))
        com_card, card_do_contato, sem_card = ids
        novo, closer = "card-novo-" + uuid.uuid4().hex[:8], "card-closer-" + uuid.uuid4().hex[:8]
        # O turno da IA já levou o card do primeiro lead para o closer enquanto o lead novo esperava a nova tentativa.
        await pool.execute("""insert into agentesia_crm_cards (id_escritorio, id_lead, id_card_helena, id_painel_helena,
                                                                 id_etapa_helena, situacao, sincronizado_em)
                              values ($1::uuid, $2, $3, 'p1', 'col-closer', 'ok', now())""", esc, com_card, closer)
        config = {"funcoes": {"crm": True}, "automacoes": {"lead_novo": {"coluna_crm": "col-sdr"}}}
        for id_lead in ids:
            acoes, _ = automacoes.acoes_do_lead_novo(config, {"id_painel": "p1"}, id_lead=id_lead)
            await repo.enfileirar_acoes(id_escritorio=esc, id_lead=id_lead, id_turno=None, acoes=acoes[:1])
        chamadas = []

        def helena(pedido: httpx.Request) -> httpx.Response:
            chamadas.append((pedido.method, pedido.url.path, dict(pedido.url.params)))
            if pedido.url.path == "/crm/v2/panel/card" and pedido.method == "GET":
                aberto = [{"id": "card-antigo", "status": "OPEN"}] if pedido.url.params.get("ContactId") == "contato-1" else []
                return httpx.Response(200, json={"items": aberto})
            if pedido.url.path == "/crm/v2/panel/card" and pedido.method == "POST":
                return httpx.Response(200, json={"id": novo})
            return httpx.Response(200, json={})

        executor = Executor(pool, "https://api.helena.run", helena_por_token=lambda t, u: HelenaConta(
            t, u, httpx.AsyncClient(transport=httpx.MockTransport(helena))))
        await executor.rodar_uma_vez()
        assert not [c for c in chamadas if c[0] == "PUT"]                  # nada foi movido de volta para SDR
        assert [c for c in chamadas if c[0] == "POST"] == [("POST", "/crm/v2/panel/card", {})]   # só o lead sem card
        linhas = {str(l["id_lead"]): l for l in await pool.fetch(
            "select id_lead, situacao, resultado from agentesia_acoes where id_escritorio = $1::uuid", esc)}

        def resultado(id_lead):
            bruto = linhas[id_lead]["resultado"]
            return bruto if isinstance(bruto, dict) else json.loads(bruto)

        assert {l["situacao"] for l in linhas.values()} == {"feita"}
        assert resultado(com_card)["acao"] == resultado(card_do_contato)["acao"] == "ignorada"
        assert resultado(sem_card)["acao"] == "criou"
        assert await pool.fetchval("select id_etapa_helena from agentesia_crm_cards where id_lead = $1", com_card) == "col-closer"
    finally:
        await pool.execute("delete from agentesia_escritorios where nome = 'Card não volta'")
        await repo.fechar()


@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_postgres_escritorio_traz_a_situacao_e_lead_pela_sessao():
    from app.banco.postgres import RepositorioPostgres

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        esc = str(await pool.fetchval("insert into agentesia_escritorios (nome, situacao) values ('Suspenso', 'suspenso') returning id"))
        escritorio = await repo.escritorio(esc)
        assert (escritorio.situacao, escritorio.ia_desligada) == ("suspenso", True)
        canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado) values ($1, $2) returning id",
                                    esc, "5511" + str(uuid.uuid4().int)[:9])
        contato = await pool.fetchval("insert into agentesia_contatos (id_escritorio, telefone_normalizado) "
                                      "values ($1, '5511900000099') returning id", esc)
        sessao = "sessao-" + uuid.uuid4().hex
        id_lead = str(await pool.fetchval("insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_sessao_helena) "
                                          "values ($1, $2, $3, $4) returning id", esc, contato, canal, sessao))
        assert (await repo.lead_por_sessao(esc, sessao)).id == id_lead
        assert await repo.lead_por_sessao(esc, "outra") is None
    finally:
        await pool.execute("delete from agentesia_escritorios where nome = 'Suspenso'")
        await repo.fechar()
