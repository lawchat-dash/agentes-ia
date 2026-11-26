"""Correções da área "troca": troca entre agentes, pausa pelo atendente, botão e etiqueta da IA, envio em partes,
etapa terminal, histórico de trocas, follow-up de desqualificado, sugestão do CRM e troca pela equipe.

Unitários com fakes (repositório em memória, Helena falsa, ModeloFalso). Os de banco só rodam com
AGENTESIA_TESTE_PG_URL (PGlite local: node db/testes/servidor_local.mjs <porta>).
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app import automacoes, ia_controle
from app.banco.memoria import RepositorioMemoria
from app.banco.tipos import Agente, Canal, Escritorio, Etapa
from app.cerebro import catalogo
from app.cerebro import turno
from app.config import Configuracao
from app.modelo import ModeloFalso
from app.pipeline import Atendimento
from tests.test_conversas_tela import ambiente  # noqa: F401 - fixture do painel com Postgres local
from tests.test_catalogo import SEM_INTENCAO
from tests.test_catalogo import montar as montar_catalogo
from tests.test_pipeline import CANAL, CONTA, LEAD, SIMPLES, HelenaFalsa, montar, webhook
from tests.test_turno import extrai, fala

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
PG = pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")


def _notas(repo):
    return [a["dados"]["texto"] for a in repo.acoes if a["tipo"] == "nota"]


def _tipos(repo):
    return [e["tipo"] for e in repo.eventos]


# ============================================================================ [0] falha ao pausar devolve 503
def _montar_com_uuid(repo_cls=RepositorioMemoria):
    id_esc = str(uuid.uuid4())
    repo = repo_cls()
    escritorio = Escritorio(id=id_esc, nome="Escritório Teste", id_segredo_helena="seg-1",
                            config={"numeros_teste": [LEAD], "espera_teste_s": 0})
    canal = Canal(id="canal-1", id_escritorio=id_esc, numero_normalizado=CANAL, id_canal_helena="ch-1")
    agente = Agente(id="ag-1", id_escritorio=id_esc, id_canal="canal-1", nome="Júlia", situacao="ativo", modo="teste",
                    etapas=[Etapa("e-sdr", "sdr", principal=True)])
    repo.cadastrar(escritorio, canal, agente, id_conta=CONTA)
    repo.segredos["seg-1"] = "token-de-teste"
    config = Configuracao(banco_url=None, helena_url="http://helena.invalid", modelo_padrao="falso", modelo_falso=True,
                          espera_minima_s=0, espera_maxima_s=0, espera_padrao_s=0, segundos_por_letra=0, max_reprocessos=2)
    return Atendimento(repo, ModeloFalso(SIMPLES), config, HelenaFalsa(), digitar=False), repo, id_esc


class RepoQueFalhaAoPausar(RepositorioMemoria):
    falhar = True

    async def registrar_fala_do_atendente(self, **dados):
        if self.falhar:
            raise ConnectionError("queda curta do banco")
        return await super().registrar_fala_do_atendente(**dados)


def test_falha_ao_pausar_devolve_503_e_o_reenvio_volta_a_valer(monkeypatch):
    from fastapi.testclient import TestClient

    from app.canal.webhook import segredo_do_escritorio
    from app.main import app

    monkeypatch.setenv("AGENTESIA_WEBHOOK_SEGREDO", "mestre-de-teste")
    atendimento, repo, id_esc = _montar_com_uuid(RepoQueFalhaAoPausar)
    monkeypatch.setattr(app.state, "atendimento", atendimento, raising=False)
    monkeypatch.setattr(app.state, "gestao", None, raising=False)
    cliente = TestClient(app)
    url = f"/webhook/helena/{id_esc}?segredo={segredo_do_escritorio(id_esc)}"
    fala_humana = webhook("Olá, aqui é a Paula", de=CANAL, para=LEAD, direcao="TO_HUB", origem="DEFAULT",
                          evento="MESSAGE_SENT", id_msg="humano-1")

    resposta = cliente.post(url, json=fala_humana)
    assert resposta.status_code == 503 and resposta.json()["detail"] == "pausa_falhou"
    assert not any("humano-1" in chave for _origem, chave in repo.recebidos)          # o recebido foi apagado
    evento = next(e for e in repo.eventos if e["tipo"] == "pausa_falhou")
    assert "devolveu 503" in evento["descricao"] and "pause manualmente" in evento["descricao"]

    repo.falhar = False                                                              # a Helena reenvia: agora vale
    resposta = cliente.post(url, json=fala_humana)
    assert resposta.status_code == 200 and resposta.json()["feito"] == "pausado"
    assert next(iter(repo.leads.values())).estado == "pausado"


# ============================================================================ [1] etiqueta sem a lista de tags
async def test_evento_de_etiqueta_sem_lista_de_tags_e_ignorado():
    # Sem 'tags' nem 'tagNames' (ou com outro tipo): não decide nada e nem toca no banco (pool None).
    for conteudo in ({"phonenumber": "+5511988887777"}, {"phonenumber": "+5511988887777", "tags": "🤖 IA Desativada"},
                     {"phonenumber": "+5511988887777", "tag": {"name": "📞 SDR"}}):
        for tipo in ("CONTACT_TAG_UPDATE", "CONTACT_UPDATE"):
            r = await ia_controle.receber_evento_de_etiqueta(None, str(uuid.uuid4()), {"eventType": tipo, "content": conteudo})
            assert r == {"feito": "ignorado", "motivo": "evento_sem_lista_de_tags"}


# ============================================================================ [3] corpo do botão da Helena
def test_le_o_corpo_do_botao_nos_dois_formatos():
    from app.main import ler_acao_ia

    botao = {"utm": {"id_da_conta": "c1", "id_do_atendimento": "sess-9", "id_do_contato": "ct",
                     "telefone_do_contato": "+55 11 98888-7777", "id_do_usuario": "u"}, "minutes": "5"}
    assert ler_acao_ia(botao) == {"acao": "desligar", "id_sessao": "sess-9", "telefone": "+55 11 98888-7777", "minutos": 5}
    assert ler_acao_ia({"acao": "ligar", "sessionId": "s1"}) == {"acao": "ligar", "id_sessao": "s1", "telefone": None,
                                                                  "minutos": 0}
    assert ler_acao_ia({"utm": {"id_do_atendimento": "s"}, "acao": "ligar"})["acao"] == "ligar"
    assert ler_acao_ia({"sessionId": "s"})["acao"] == ""                                     # sem ação: 400 na rota


def test_rota_do_botao_aceita_o_corpo_utm(monkeypatch):
    from fastapi.testclient import TestClient

    from app.canal.webhook import segredo_do_escritorio
    from app.main import app

    monkeypatch.setenv("AGENTESIA_WEBHOOK_SEGREDO", "mestre-de-teste")
    monkeypatch.setattr(app.state, "gestao", None, raising=False)
    id_esc = str(uuid.uuid4())
    url = f"/webhook/helena/{id_esc}/ia?segredo={segredo_do_escritorio(id_esc)}"
    cliente = TestClient(app)
    # Antes: 422 (BaseModel exigia 'acao'). Agora o corpo é lido; sem banco a rota responde 503.
    assert cliente.post(url, json={"utm": {"id_do_atendimento": "s1"}, "minutes": 5}).status_code == 503
    assert cliente.post(url, json={"sessionId": "s1"}).status_code == 400


@PG
async def test_etiqueta_sem_lista_nao_religa_e_botao_desliga_por_minutos_e_religa_qualquer_pausa():
    from app.banco.postgres import RepositorioPostgres
    from app.main import ler_acao_ia

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        esc = str(await pool.fetchval("insert into agentesia_escritorios (nome) values ('Troca IA') returning id"))
        canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado) values ($1, $2) returning id",
                                    esc, "5531" + str(uuid.uuid4().int)[:9])
        telefone = "55319" + str(uuid.uuid4().int)[:8]
        contato = await pool.fetchval("insert into agentesia_contatos (id_escritorio, nome, telefone_normalizado) values ($1, 'Ana', $2) returning id",
                                      esc, telefone)
        sessao = "sessao-" + uuid.uuid4().hex[:6]
        lead = await pool.fetchval("insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_sessao_helena) values ($1, $2, $3, $4) returning id",
                                   esc, contato, canal, sessao)

        async def estado():
            return tuple(await pool.fetchrow("select estado, motivo_estado, pausado_ate is not null as prazo from agentesia_leads where id = $1", lead))

        # [1] A equipe desligou pela etiqueta; um evento sem a lista de tags NÃO religa; com lista vazia religa.
        com_tag = {"eventType": "CONTACT_TAG_UPDATE", "content": {"phonenumber": "+" + telefone, "tags": [{"name": "🤖 IA Desativada"}]}}
        assert (await ia_controle.receber_evento_de_etiqueta(pool, esc, com_tag))["alterados"] == 1
        sem_lista = {"eventType": "CONTACT_UPDATE", "content": {"phonenumber": "+" + telefone, "name": "Ana Maria"}}
        assert (await ia_controle.receber_evento_de_etiqueta(pool, esc, sem_lista))["motivo"] == "evento_sem_lista_de_tags"
        assert await estado() == ("pausado", "desativada_pela_equipe", False)
        vazia = {"eventType": "CONTACT_TAG_UPDATE", "content": {"phonenumber": "+" + telefone, "tags": []}}
        assert (await ia_controle.receber_evento_de_etiqueta(pool, esc, vazia))["alterados"] == 1
        assert (await estado())[0] == "ativo"

        # [3] Corpo do botão (utm, minutes=5): desliga com prazo e também põe a etiqueta (docs/LIGAR_DESLIGAR_IA.md:
        # a etiqueta acompanha o estado; sai sozinha quando o prazo acaba).
        dados = ler_acao_ia({"utm": {"id_do_atendimento": sessao, "telefone_do_contato": "+" + telefone}, "minutes": 5})
        r = await ia_controle.mudar_ia(pool, esc, ligar=False, origem="botao", id_sessao=dados["id_sessao"],
                                       telefone=dados["telefone"], minutos=dados["minutos"])
        assert r["alterados"] == 1 and await estado() == ("pausado", "desativada_pela_equipe", True)
        prazo = await pool.fetchval("select pausado_ate - now() from agentesia_leads where id = $1", lead)
        assert timedelta(minutes=4) < prazo <= timedelta(minutes=5)
        acoes = await pool.fetch("select tipo, dados from agentesia_acoes where id_lead = $1 and chave_unica like $2",
                                 lead, f"%{r['codigo']}%")
        assert sorted(a["tipo"] for a in acoes) == ["etiquetar", "nota"]
        assert "5 min" in json.loads(next(a for a in acoes if a["tipo"] == "nota")["dados"])["texto"]

        # [3] Lead que pediu humano: o botão "ligar" religa (antes: alterados 0, calado).
        await pool.execute("update agentesia_leads set estado = 'pausado', motivo_estado = 'pediu_humano', pausado_ate = null where id = $1", lead)
        r = await ia_controle.mudar_ia(pool, esc, ligar=True, origem="botao", id_sessao=sessao)
        assert r["alterados"] == 1 and (await estado())[0] == "ativo"
        # A etiqueta continua só desfazendo o que a etiqueta fez.
        await pool.execute("update agentesia_leads set estado = 'pausado', motivo_estado = 'sinal:quer_videochamada' where id = $1", lead)
        assert (await ia_controle.receber_evento_de_etiqueta(pool, esc, vazia))["alterados"] == 0

        # [3] Botão sem efeito deixa nota explicando ("já estava ligada").
        await pool.execute("update agentesia_leads set estado = 'ativo', motivo_estado = null where id = $1", lead)
        r = await ia_controle.mudar_ia(pool, esc, ligar=True, origem="botao", id_sessao=sessao)
        assert (r["encontrados"], r["alterados"]) == (1, 0)
        nota = await pool.fetchval("select dados from agentesia_acoes where id_lead = $1 and chave_unica like $2", lead, f"%{r['codigo']}%")
        assert "já estava ligada" in json.loads(nota)["texto"]
    finally:
        await repo.fechar()


# ============================================================================ [2][4][18] atendente assume no meio do envio
class HelenaQueOAtendenteInterrompe(HelenaFalsa):
    """Na 1ª parte enviada, o atendente responde: o webhook dele pausa o lead no banco."""

    def __init__(self, repo):
        super().__init__()
        self.repo = repo

    async def enviar(self, **dados):
        id_externo = await super().enviar(**dados)
        if len(self.enviadas) == 1:
            for lead in self.repo.leads.values():
                lead.estado, lead.motivo_estado = "pausado", "humano_assumiu"
                lead.pausado_ate = datetime.now(timezone.utc) + timedelta(minutes=15)
        return id_externo


async def test_envio_em_partes_para_quando_o_atendente_assume():
    repo_ref: dict = {}
    atendimento, repo, _ = montar({"extrator": extrai(), "etapa": fala("Parte 1.", "Parte 2.", "Parte 3.", "Parte 4.")},
                                  helena=HelenaQueOAtendenteInterrompe(repo_ref))
    atendimento.helena.repo = repo
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    assert atendimento.helena.enviadas == ["Parte 1."]
    lead = next(iter(repo.leads.values()))
    assert [(m.autor, m.texto) for m in repo.mensagens[lead.id]] == [("lead", "oi"), ("ia", "Parte 1.")]
    assert (lead.estado, lead.motivo_estado) == ("pausado", "humano_assumiu") and lead.pausado_ate is not None
    turno_ = next(iter(repo.turnos.values()))
    interrompido = turno_["contexto"]["envio_interrompido"]
    assert interrompido == {"motivo": "humano_assumiu", "partes_nao_enviadas": ["Parte 2.", "Parte 3.", "Parte 4."]}
    evento = next(e for e in repo.eventos if e["tipo"] == "envio_interrompido")
    assert evento["gravidade"] == "info"


async def test_envio_em_partes_sem_interrupcao_manda_tudo():
    atendimento, repo, helena = montar({"extrator": extrai(), "etapa": fala("Parte 1.", "Parte 2.", "Parte 3.")})
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    assert helena.enviadas == ["Parte 1.", "Parte 2.", "Parte 3."] and "envio_interrompido" not in _tipos(repo)


# ============================================================================ [17] eco que chega durante o envio
class HelenaComEcoRapido(HelenaFalsa):
    """A Helena manda o MESSAGE_SENT do eco antes de devolver o id do envio."""

    async def enviar(self, **dados):
        id_externo = await super().enviar(**dados)
        eco = webhook(dados.get("texto") or "", de=CANAL, para=LEAD, direcao="TO_HUB", origem="API",
                      evento="MESSAGE_SENT", id_msg=id_externo)
        await self.atendimento.receber(eco)
        return id_externo


async def test_eco_antes_da_gravacao_fica_como_fala_da_ia():
    helena = HelenaComEcoRapido()
    atendimento, repo, _ = montar({"extrator": extrai(), "etapa": fala("Oi! Me conta o que aconteceu?")}, helena=helena)
    helena.atendimento = atendimento
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    lead = next(iter(repo.leads.values()))
    assert [(m.autor, m.texto) for m in repo.mensagens[lead.id]] == [("lead", "oi"), ("ia", "Oi! Me conta o que aconteceu?")]


# ============================================================================ [5] etapa fora dos papéis (contrato assinado)
async def test_lead_em_contrato_assinado_e_religado_nao_volta_para_o_sdr():
    atendimento, repo, helena, modelo = montar_catalogo({"mensagens": [{"texto": "Olá! Sou a assistente..."}],
                                                         "transferir_para": "", "ferramenta": ""})
    lead = await repo.achar_ou_criar_lead(escritorio=repo.escritorios["esc-1"], canal=repo.canais["canal-1"],
                                          agente=repo.agentes["canal-1"], telefone=LEAD, id_sessao="sessao-1")
    repo.leads[lead.id].id_etapa = "e-ok"                     # contrato_assinado, e a equipe devolveu à IA (ativo)
    await atendimento.receber(webhook("oi, tenho uma dúvida"))
    await atendimento.aguardar_esperas()
    assert modelo.pedidos == [] and helena.enviadas == []                                 # nem extrator nem agente
    assert repo.leads[lead.id].id_etapa == "e-ok"
    turno_ = next(iter(repo.turnos.values()))
    assert (turno_["situacao"], turno_["motivo"]) == ("silencio", "etapa_terminal")
    assert "etapa_terminal" in _tipos(repo)
    assert any(n.startswith("🏁 O lead está no fim do funil") for n in _notas(repo))
    assert not any(a["tipo"] == "mover_card" for a in repo.acoes)


async def test_turno_do_catalogo_em_etapa_fora_dos_papeis_fica_em_silencio():
    produto = catalogo.carregar({"catalogo": {"papeis": {"sdr": {}, "closer": {}}}})
    modelo = ModeloFalso({"extrator": {"fatos": [], "sinais": [], "intencoes": SEM_INTENCAO},
                          "etapa": {"mensagens": [{"texto": "Olá!"}], "transferir_para": "", "ferramenta": ""}})
    saida = await turno.processar(modelo, turno.Entrada(escritorio="E", agente="J", etapa="contrato_assinado",
                                                        novas=["oi"], produto=produto, instrucoes={"sdr": "Qualifique."}))
    assert (saida.situacao, saida.motivo, saida.etapa_depois, saida.mensagens) == ("silencio", "etapa_terminal",
                                                                                   "contrato_assinado", [])
    assert not [p for p in modelo.pedidos if p["papel"] == "etapa"]


def test_instrucao_do_catalogo_nao_cai_no_papel_inicial():
    agente = Agente(id="a", id_escritorio="e", id_canal="c", nome="J", produto="catalogo",
                    config={"catalogo": {"papeis": {"sdr": {}}}},
                    etapas=[Etapa("e-sdr", "sdr", principal=True, instrucao="Qualifique."), Etapa("e-ok", "contrato_assinado")])
    assert Atendimento._instrucao_do_catalogo(agente, agente.etapa("contrato_assinado")) == ""
    assert Atendimento._instrucao_do_catalogo(agente, agente.etapa("sdr")) == "Qualifique."


# ============================================================================ [6] sincronizar o produto não apaga funções
def test_reativar_agente_mantem_as_funcoes_ligadas_pelo_escritorio():
    from app.gestao.produtos import juntar_config

    antigo = {"funcoes": {"crm": True, "avisos": True, "transferir_humano": True, "contrato_zapsign": False},
              "automacoes": {"lead_novo": {"coluna_crm": "c1"}}, "temperatura": 0.2}
    novo = {"funcoes": {"contrato_zapsign": True, "buscar_cep": True}, "temperatura": 0.7}
    junto = juntar_config(antigo, novo)
    assert junto["funcoes"] == {"crm": True, "avisos": True, "transferir_humano": True, "contrato_zapsign": True,
                                "buscar_cep": True}
    assert junto["automacoes"] == antigo["automacoes"] and junto["temperatura"] == 0.7
    assert juntar_config({}, novo)["funcoes"] == novo["funcoes"]


# ============================================================================ [7] sugestão do CRM no catálogo
def test_sugestao_do_catalogo_liga_cada_papel_e_troca_as_etiquetas():
    produto = catalogo.carregar({"catalogo": {"papeis": {p: {} for p in
                                                         ("sdr", "periododegraca", "closer", "contratos", "assinatura", "desqualificado")}}})
    colunas = [{"id": "c-sdr", "titulo": "SDR", "inicial": True}, {"id": "c-graca", "titulo": "Período de Graça"},
               {"id": "c-com", "titulo": "Comercial"}, {"id": "c-ok", "titulo": "Contrato Assinado"},
               {"id": "c-elab", "titulo": "Elaboração de Contrato"}, {"id": "c-ass", "titulo": "Assinatura"},
               {"id": "c-desq", "titulo": "Desqualificados"}]
    etiquetas = [{"nome": n} for n in ("❌ Desqualificado", "📞 SDR", "⏳ Graça", "🛒 Comercial", "📝 Elaboração",
                                       "✍️ Assinatura", "✅ Assinado", "🤖 IA Desativada")]
    sugestao = automacoes.sugestao_padrao(colunas, produto, etiquetas)
    colunas_por_gatilho = {g: r.get("coluna_crm") for g, r in sugestao.items()}
    assert colunas_por_gatilho == {"lead_novo": "c-sdr", "etapa:periododegraca": "c-graca", "etapa:closer": "c-com",
                                   "etapa:contratos": "c-elab", "etapa:assinatura": "c-ass",
                                   "etapa:contrato_assinado": "c-ok", "etapa:desqualificado": "c-desq",
                                   "pediu_humano": None}
    assert sugestao["lead_novo"]["adicionar_etiquetas"] == ["📞 SDR"]
    assert sugestao["etapa:closer"]["adicionar_etiquetas"] == ["🛒 Comercial"]
    assert "📞 SDR" in sugestao["etapa:closer"]["remover_etiquetas"]
    assert "🛒 Comercial" not in sugestao["etapa:closer"]["remover_etiquetas"]
    assert "🤖 IA Desativada" not in sugestao["etapa:closer"]["remover_etiquetas"]
    assert sugestao["etapa:contrato_assinado"]["adicionar_etiquetas"] == ["✅ Assinado"]
    # Sem a lista de etiquetas da conta: só as colunas (e a etiqueta padrão do lead novo), nada de nome inventado.
    sem = automacoes.sugestao_padrao(colunas, produto)
    assert "adicionar_etiquetas" not in sem["etapa:closer"] and sem["lead_novo"]["adicionar_etiquetas"] == ["📞 SDR"]
    # Outros produtos continuam com a sugestão de antes.
    assert "etapa:coleta_dados" in automacoes.sugestao_padrao([{"id": "c", "titulo": "Contrato enviado"}])


# ============================================================================ turno do catálogo: destinos e trocas
PAPEIS_FUNIL = {
    "sdr": {"destinos": ["periododegraca", "closer", "desqualificado"]},
    "periododegraca": {"destinos": ["closer", "desqualificado"]},
    "closer": {"destinos": ["contratos", "desqualificado"],
               "mensagem_troca": "Vou te passar para o time de contratos, que vai pegar seus dados",
               "boas_vindas": "Oi, sou a Carla do comercial!"},
    "contratos": {"destinos": ["assinatura", "desqualificado"],
                  "mensagem_troca": "Vou te passar para o time de contratos, que vai pegar seus dados"},
    "assinatura": {"destinos": []},
    "desqualificado": {"destinos": []},
}


def _produto(papeis=None):
    papeis = json.loads(json.dumps(papeis or PAPEIS_FUNIL))
    return catalogo.carregar({"catalogo": {"papeis": papeis}, "funcoes": {"contrato_zapsign": True}})


HISTORICO = [{"autor": "lead", "texto": "oi"}, {"autor": "você", "texto": "Olá! Me conta o que aconteceu?"}]


async def _rodar(etapa, resposta, *, instrucoes=None, historico=HISTORICO, fatos=None, papeis=None):
    modelo = ModeloFalso({"extrator": {"fatos": [], "sinais": [], "intencoes": SEM_INTENCAO}, "etapa": resposta})
    entrada = turno.Entrada(escritorio="E", agente="J", etapa=etapa, novas=["certo"], produto=_produto(papeis),
                            instrucoes=instrucoes or {etapa: "Siga o roteiro."}, historico=list(historico),
                            fatos=dict(fatos or {}))
    return await turno.processar(modelo, entrada), modelo


def _enum_de_destinos(modelo):
    pedido = next(p for p in modelo.pedidos if p["papel"] == "etapa")
    return pedido["esquema"]["properties"]["transferir_para"]["enum"]


async def test_prompt_nao_oferece_destino_para_tras():  # [11]
    saida, modelo = await _rodar("periododegraca", {"mensagens": [{"texto": "Vamos lá."}], "transferir_para": "", "ferramenta": ""},
                                 instrucoes={"periododegraca": "Se precisar, volte para o @Agente SDR."})
    assert "sdr" not in _enum_de_destinos(modelo) and "closer" in _enum_de_destinos(modelo)
    assert "destino_para_tras_ignorado" in [e["tipo"] for e in saida.eventos]
    # Registrado uma vez por conversa: com a marca já gravada, o turno seguinte não repete o evento.
    marca = next(f["valor"] for f in saida.fatos_novos if f["chave"] == turno.MARCA_DESTINOS_IGNORADOS)
    saida2, _ = await _rodar("periododegraca", {"mensagens": [{"texto": "Ok."}], "transferir_para": "", "ferramenta": ""},
                             instrucoes={"periododegraca": "Se precisar, volte para o @Agente SDR."},
                             fatos={turno.MARCA_DESTINOS_IGNORADOS: marca})
    assert "destino_para_tras_ignorado" not in [e["tipo"] for e in saida2.eventos]


async def test_contratos_nao_passa_para_assinatura_pela_ia():  # [8]
    saida, modelo = await _rodar("contratos", {"mensagens": [{"texto": "Vou gerar seu contrato."}],
                                               "transferir_para": "assinatura", "ferramenta": "zapsign"})
    assert _enum_de_destinos(modelo) == ["", "desqualificado"]
    assert saida.etapa_depois == "contratos" and saida.motivo == "dados_confirmados"
    tipos = [e["tipo"] for e in saida.eventos]
    assert "destino_recusado" in tipos and "destino_ignorado" not in tipos       # config antiga: sai calado
    assert saida.contexto["destinos_ignorados"] == ["assinatura"]
    from app.gestao.produtos import DESTINOS
    assert DESTINOS["contratos"] == ["desqualificado"]


async def test_primeira_resposta_nao_troca_de_papel():  # [14]
    saida, _ = await _rodar("sdr", {"mensagens": [{"texto": "Entendi, obrigado pelo contato."}],
                                    "transferir_para": "desqualificado", "ferramenta": ""}, historico=[])
    assert saida.etapa_depois == "sdr"
    assert "troca_precoce_recusada" in [e["tipo"] for e in saida.eventos]
    # Liberado no papel, ou depois da primeira resposta: troca normal.
    papeis = json.loads(json.dumps(PAPEIS_FUNIL))
    papeis["sdr"]["transferir_na_primeira_resposta"] = True
    saida, _ = await _rodar("sdr", {"mensagens": [{"texto": "Entendi."}], "transferir_para": "desqualificado", "ferramenta": ""},
                            historico=[], papeis=papeis)
    assert saida.etapa_depois == "desqualificado"
    saida, _ = await _rodar("sdr", {"mensagens": [{"texto": "Entendi."}], "transferir_para": "desqualificado", "ferramenta": ""})
    assert saida.etapa_depois == "desqualificado"


async def test_minimo_de_mensagens_do_lead_para_transferir():  # [14]
    papeis = json.loads(json.dumps(PAPEIS_FUNIL))
    papeis["sdr"]["min_mensagens_lead_para_transferir"] = 3
    saida, _ = await _rodar("sdr", {"mensagens": [{"texto": "Certo."}], "transferir_para": "closer", "ferramenta": ""},
                            papeis=papeis)
    assert saida.etapa_depois == "sdr"                       # 'oi' + 'certo' = 2 mensagens do lead


def test_frase_de_passagem_parafraseada_e_a_mais_longa():  # [12]
    papeis = {"closer": {"mensagem_troca": "Vou te passar agora para nossa especialista"},
              "contratos": {"mensagem_troca": "Vou te passar para o time de contratos, que vai pegar seus dados"},
              "desqualificado": {"mensagem_troca": "Obrigado"}}
    parafrase = ["Perfeito! Agora vou te passar para o time de contratos que vai pegar todos os seus dados."]
    assert catalogo.transferencia_pela_frase(parafrase, ["closer", "contratos"], papeis, parafrase=True) == "contratos"
    assert catalogo.transferencia_pela_frase(parafrase, ["closer", "contratos"], papeis) is None          # avaliação: exata
    # Frase curta (menos de 6 palavras significativas) só vale exata.
    assert catalogo.transferencia_pela_frase(["Agora vou passar você para nossa especialista."], ["closer"], papeis, parafrase=True) is None
    assert catalogo.transferencia_pela_frase(["Certo! Vou te passar agora para nossa especialista."], ["closer"], papeis) == "closer"
    # As duas casam: vence a mais longa.
    ambas = ["Vou te passar agora para nossa especialista. Vou te passar para o time de contratos, que vai pegar seus dados"]
    assert catalogo.transferencia_pela_frase(ambas, ["closer", "contratos"], papeis) == "contratos"


async def test_troca_pela_frase_parafraseada_registra_evento():  # [12] e [13]
    saida, _ = await _rodar("closer", {"mensagens": [{"texto": "Ótimo! Agora vou te passar para o time de contratos "
                                                                "que vai pegar todos os seus dados."}],
                                       "transferir_para": "", "ferramenta": ""})
    assert saida.etapa_depois == "contratos"
    evento = next(e for e in saida.eventos if e["tipo"] == "troca_pela_frase")
    assert evento["detalhe"]["destino"] == "contratos"
    assert saida.contexto["catalogo"]["origem_destino"] == "frase"


async def test_boas_vindas_do_papel_que_recebe_o_lead():  # [16]
    # SDR passa para o Closer: a marca fica gravada para o Closer.
    saida, _ = await _rodar("sdr", {"mensagens": [{"texto": "Certo, vou te passar."}], "transferir_para": "closer", "ferramenta": ""})
    assert saida.etapa_depois == "closer" and saida.fatos_depois[turno.MARCA_BOAS_VINDAS] == "closer"
    # Próxima mensagem: o Closer usa as boas-vindas dele (não é a 1ª resposta da conversa) e limpa a marca.
    saida, modelo = await _rodar("closer", {"mensagens": [{"texto": "Oi, sou a Carla do comercial!"}], "transferir_para": "",
                                            "ferramenta": ""}, fatos={turno.MARCA_BOAS_VINDAS: "closer"})
    conteudo = next(p for p in modelo.pedidos if p["papel"] == "etapa")["conteudo"]
    assert "Oi, sou a Carla do comercial!" in conteudo and "acabou de assumir" in conteudo
    assert saida.fatos_depois[turno.MARCA_BOAS_VINDAS] == ""
    # Sem a marca, o Closer não repete as boas-vindas.
    _, modelo = await _rodar("closer", {"mensagens": [{"texto": "Certo."}], "transferir_para": "", "ferramenta": ""})
    assert "Oi, sou a Carla" not in next(p for p in modelo.pedidos if p["papel"] == "etapa")["conteudo"]


# ============================================================================ [13] histórico da troca no pipeline
async def test_troca_de_etapa_no_turno_vira_evento_etapa_trocada():
    atendimento, repo, _helena, _ = montar_catalogo({"mensagens": [{"texto": "Entendi seu caso."}],
                                                     "transferir_para": "closer", "ferramenta": ""})
    await atendimento.receber(webhook("oi"))
    await atendimento.aguardar_esperas()
    lead = next(iter(repo.leads.values()))
    assert lead.id_etapa == "e-sdr" and "troca_precoce_recusada" in _tipos(repo)        # 1ª resposta: sem troca
    await atendimento.receber(webhook("sofri um acidente de moto em 2022"))
    await atendimento.aguardar_esperas()
    assert repo.leads[lead.id].id_etapa == "e-closer"
    evento = next(e for e in repo.eventos if e["tipo"] == "etapa_trocada")
    assert evento["detalhe"]["de"] == "sdr" and evento["detalhe"]["para"] == "closer" and evento["detalhe"]["origem"] == "ia"


# ============================================================================ [10] passagem para humano deixa nota
async def test_pediu_humano_e_sinal_deixam_nota_no_chat():
    atendimento, repo, _ = montar({"extrator": extrai(pediu_humano=True), "etapa": fala("Certo!")})
    await atendimento.receber(webhook("quero falar com uma pessoa"))
    await atendimento.aguardar_esperas()
    assert any(n.startswith("🙋 O lead pediu para falar com uma pessoa") for n in _notas(repo))

    atendimento, repo, _ = montar({"extrator": extrai(sinais=["quer_videochamada"]), "etapa": fala("Certo!")})
    await atendimento.receber(webhook("dá pra fazer uma videochamada?"))
    await atendimento.aguardar_esperas()
    nota = next(n for n in _notas(repo) if n.startswith("🔔"))
    assert "pede videochamada" in nota and "responda manualmente" in nota


# ============================================================================ [9] follow-up de desqualificado
def test_followup_nao_vale_para_desqualificado_por_padrao():
    from app.followup import regras
    from app.followup.servico import _etapas_de_conversa

    lead = {"produto": "catalogo", "config_agente": {"catalogo": {"papeis": {"sdr": {}, "closer": {}, "desqualificado": {}}}}}
    etapas = _etapas_de_conversa(lead)
    assert "desqualificado" not in etapas and {"sdr", "closer"} <= etapas
    assert not regras.Config.de({"ativo": True}).vale_para("desqualificado", etapas)
    # Decisão do dono (25/11, docs/FOLLOWUP.md): desqualificado nunca recebe, nem listado em config.etapas.
    assert not regras.Config.de({"ativo": True, "etapas": ["desqualificado"]}).vale_para("desqualificado", etapas)


@PG
async def test_followup_pendente_e_cancelado_quando_o_lead_vai_para_desqualificado():
    from app.banco.postgres import RepositorioPostgres
    from app.followup import servico

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        esc = await pool.fetchval("insert into agentesia_escritorios (nome) values ('Follow Desq') returning id")
        canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado) values ($1, $2) returning id",
                                    esc, "5511" + str(uuid.uuid4().int)[:9])
        config = {"catalogo": {"papeis": {"sdr": {}, "desqualificado": {}}},
                  "followup": {"ativo": True, "horario": {"inicio": 0, "fim": 24, "dias": [0, 1, 2, 3, 4, 5, 6]}}}
        agente = await pool.fetchval("insert into agentesia_agentes (id_escritorio, id_canal, nome, produto, config) "
                                     "values ($1, $2, 'J', 'catalogo', $3::jsonb) returning id", esc, canal, json.dumps(config))
        sdr = await pool.fetchval("insert into agentesia_agente_etapas (id_agente, codigo, ordem, principal) values ($1, 'sdr', 1, true) returning id", agente)
        desq = await pool.fetchval("insert into agentesia_agente_etapas (id_agente, codigo, ordem) values ($1, 'desqualificado', 2) returning id", agente)
        contato = await pool.fetchval("insert into agentesia_contatos (id_escritorio, telefone_normalizado) values ($1, $2) returning id",
                                      esc, "5511" + str(uuid.uuid4().int)[:9])
        lead = await pool.fetchval("insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_agente, id_etapa) "
                                   "values ($1, $2, $3, $4, $5) returning id", esc, contato, canal, agente, sdr)
        agora = datetime.now(timezone.utc)
        assert await servico.agendar(pool, str(lead), agora) is not None                  # em sdr: agenda
        await pool.execute("update agentesia_leads set id_etapa = $2 where id = $1", lead, desq)
        assert await servico.agendar(pool, str(lead), agora) is None                      # desqualificado: não agenda
        situacoes = [r["situacao"] for r in await pool.fetch("select situacao from agentesia_followups where id_lead = $1", lead)]
        assert situacoes == ["cancelado"]
    finally:
        await repo.fechar()


# ============================================================================ [8] e [15] mover etapa só quando muda; troca pela equipe
@PG
async def test_mover_lead_para_etapa_so_devolve_verdadeiro_quando_muda():
    from app.banco.postgres import RepositorioPostgres
    from app.contrato import servico

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        esc = await pool.fetchval("insert into agentesia_escritorios (nome) values ('Mover Etapa') returning id")
        canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado) values ($1, $2) returning id",
                                    esc, "5511" + str(uuid.uuid4().int)[:9])
        agente = await pool.fetchval("insert into agentesia_agentes (id_escritorio, id_canal, nome) values ($1, $2, 'J') returning id", esc, canal)
        contratos = await pool.fetchval("insert into agentesia_agente_etapas (id_agente, codigo, ordem, principal) values ($1, 'contratos', 1, true) returning id", agente)
        await pool.execute("insert into agentesia_agente_etapas (id_agente, codigo, ordem) values ($1, 'assinatura', 2)", agente)
        await pool.execute("insert into agentesia_agente_etapas (id_agente, codigo, ordem, tipo) values ($1, 'contrato_assinado', 3, 'terminal')", agente)
        contato = await pool.fetchval("insert into agentesia_contatos (id_escritorio, telefone_normalizado) values ($1, $2) returning id",
                                      esc, "5511" + str(uuid.uuid4().int)[:9])
        lead = str(await pool.fetchval("insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_agente, id_etapa) "
                                       "values ($1, $2, $3, $4, $5) returning id", esc, contato, canal, agente, contratos))
        assert await servico.mover_lead_para_etapa(pool, lead, "assinatura") is True       # v1: muda e dispara
        assert await servico.mover_lead_para_etapa(pool, lead, "assinatura") is False      # v2: já estava, não repete
        assert await servico.mover_lead_para_etapa(pool, lead, "nao_existe") is False
        assert await servico.mover_lead_para_etapa(pool, lead, "contrato_assinado", estado="encerrado",
                                                   motivo_estado="contrato_assinado") is True
        assert tuple(await pool.fetchrow("select estado, motivo_estado from agentesia_leads where id = $1::uuid", lead)) \
            == ("encerrado", "contrato_assinado")
    finally:
        await repo.fechar()


async def test_equipe_troca_a_etapa_do_lead_pelo_painel(ambiente):  # [15]
    from tests.test_conversas_tela import _escritorio_com_agente, _lead
    from tests.test_gestao import _entrar

    cliente, email_admin, banco = ambiente
    pool = banco._pool
    await _entrar(cliente, email_admin, "senha-admin-123")
    id_escritorio, id_canal, id_agente, h = await _escritorio_com_agente(cliente, "Troca Ltda")
    id_lead = await _lead(pool, id_escritorio, id_canal, id_agente, nome="Rui", telefone="5511" + str(uuid.uuid4().int)[:9])

    async def etapa_do_lead():
        return await pool.fetchval("select e.codigo from agentesia_leads l join agentesia_agente_etapas e on e.id = l.id_etapa "
                                   "where l.id = $1::uuid", id_lead)

    codigos = [r["codigo"] for r in await pool.fetch(
        "select codigo from agentesia_agente_etapas where id_agente = $1::uuid order by ordem", id_agente)]
    antes = await etapa_do_lead()
    alvo = next(c for c in codigos if c != antes)
    r = await cliente.post(f"/api/conversas/{id_lead}/ia", json={"acao": "trocar_etapa", "etapa": alvo}, headers=h)
    assert r.status_code == 200 and r.json() == {"ok": True, "etapa": alvo, "mudou": True}
    assert await etapa_do_lead() == alvo
    detalhe = await pool.fetchval("select detalhe from agentesia_eventos where id_lead = $1::uuid and tipo = 'etapa_trocada'", id_lead)
    detalhe = json.loads(detalhe) if isinstance(detalhe, str) else detalhe
    assert (detalhe["de"], detalhe["para"], detalhe["origem"]) == (antes, alvo, "equipe")
    assert await pool.fetchval("select count(*) from agentesia_alteracoes where id_registro = $1::uuid and acao = 'trocar_etapa'",
                               id_lead) == 1
    # A mesma etapa de novo: nada muda. Etapa que o agente não tem: 400. Lead de outro escritório: 404.
    r = await cliente.post(f"/api/conversas/{id_lead}/ia", json={"acao": "trocar_etapa", "etapa": alvo}, headers=h)
    assert r.json()["mudou"] is False
    r = await cliente.post(f"/api/conversas/{id_lead}/ia", json={"acao": "trocar_etapa", "etapa": "nao_existe"}, headers=h)
    assert r.status_code == 400
    _outro, _c, _a, h_outro = await _escritorio_com_agente(cliente, "Outro Ltda")
    r = await cliente.post(f"/api/conversas/{id_lead}/ia", json={"acao": "trocar_etapa", "etapa": alvo}, headers=h_outro)
    assert r.status_code == 404


