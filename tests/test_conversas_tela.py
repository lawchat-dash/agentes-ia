"""Tela Conversas do painel (painel/src/telas/Conversas.tsx) contra um Postgres local.

Confere o formato que a tela lê de GET /api/conversas e /api/conversas/{id} (lista, balões, fatos, origem,
turnos e eventos) e os botões pausar/devolver/encerrar (POST /api/conversas/{id}/ia), inclusive pelo atendente.
Só roda com AGENTESIA_TESTE_PG_URL (ver tests/test_postgres.py). A Helena é simulada como em test_gestao.
"""

import json
import os
import tempfile
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from app.banco.postgres import RepositorioPostgres
from app.canal import helena_conta
from app.config import Configuracao
from app.gestao import seguranca
from app.gestao.repositorio import RepositorioGestao
from app.gestao.rotas import api
from tests.test_gestao import HelenaSimulada, _entrar

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
RAIZ = Path(__file__).resolve().parent.parent

# Campos que a lista e a conversa aberta usam (painel/src/components/conversas/tipos.ts).
CAMPOS_LISTA = {"id", "nome", "telefone", "estado", "motivo_estado", "pausado_ate", "etapa", "agente",
                "ultima_mensagem_lead_em", "ultima_resposta_ia_em", "criado_em", "ultima_mensagem"}
CAMPOS_CONVERSA = {"id", "nome", "telefone", "estado", "motivo_estado", "pausado_ate", "etapa", "agente", "origem",
                   "criado_em", "ultima_mensagem_lead_em", "ultima_resposta_ia_em", "mensagens", "fatos", "turnos", "eventos"}
CAMPOS_MENSAGEM = {"id", "autor", "tipo", "texto", "texto_extraido", "enviada_em", "situacao_envio", "erro", "id_turno"}


def test_tela_conhece_os_motivos_gravados_pelos_botoes():
    """Os motivos que os botões gravam têm rótulo em português na tela (senão aparece o código cru)."""
    rotas = (RAIZ / "app" / "gestao" / "rotas.py").read_text(encoding="utf-8")
    controle = (RAIZ / "app" / "ia_controle.py").read_text(encoding="utf-8")
    tipos = (RAIZ / "painel" / "src" / "components" / "conversas" / "tipos.ts").read_text(encoding="utf-8")
    for motivo in ("devolvido_pela_equipe", "encerrado_pela_equipe"):
        assert f'"{motivo}"' in rotas, motivo
        assert f"{motivo}:" in tipos, motivo
    assert '"desativada_pela_equipe"' in controle and "desativada_pela_equipe:" in tipos
    # A tela chama exatamente as três ações que a rota aceita.
    tela = (RAIZ / "painel" / "src" / "telas" / "Conversas.tsx").read_text(encoding="utf-8")
    assert "`/conversas/${id}/ia`" in tela
    for acao in ("desativar", "reativar", "encerrar"):
        assert f'"{acao}"' in rotas and f"{acao}:" in tela


def test_rota_e_menu_da_tela():
    main = (RAIZ / "painel" / "src" / "main.tsx").read_text(encoding="utf-8")
    estrutura = (RAIZ / "painel" / "src" / "componentes" / "Estrutura.tsx").read_text(encoding="utf-8")
    assert 'path="/conversas/:id?"' in main
    # A rota fica fora do bloco de quem gere: o atendente também abre a tela.
    assert main.index('path="/conversas/:id?"') < main.index("{podeGerir && <>\n          <Route path=\"/agentes\"")
    # A pedido do dono, Conversas saiu do menu (a Central de Atendimento ocupa esse lugar); a tela segue pela rota.
    assert '{ para: "/conversas", rotulo: "Conversas"' not in estrutura
    assert '{ para: "/atendimento", rotulo: "Central de Atendimento"' in estrutura


@pytest.fixture
async def ambiente(monkeypatch):
    if not URL:
        pytest.skip("sem AGENTESIA_TESTE_PG_URL")
    simulada = HelenaSimulada()
    original = helena_conta.HelenaConta.__init__

    def init_com_simulacao(self, token, url_base="https://api.helena.run", http=None):
        original(self, token, url_base, httpx.AsyncClient(transport=httpx.MockTransport(simulada)))

    monkeypatch.setattr(helena_conta.HelenaConta, "__init__", init_com_simulacao)
    monkeypatch.setenv("AGENTESIA_URL_PUBLICA", "https://ia.exemplo.com")
    monkeypatch.setenv("AGENTESIA_WEBHOOK_SEGREDO", "segredo-do-webhook")
    monkeypatch.setenv("AGENTESIA_PASTA_MIDIA", tempfile.mkdtemp(prefix="midia-teste-"))

    banco = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    app = FastAPI()
    app.include_router(api)
    app.state.gestao = RepositorioGestao(banco._pool)
    app.state.assinador = seguranca.Assinador("segredo-de-teste")
    app.state.cfg = Configuracao(banco_url=URL, helena_url="https://api.helena.run", modelo_padrao="falso", modelo_falso=True,
                                  espera_minima_s=0, espera_maxima_s=0, espera_padrao_s=0, segundos_por_letra=0, max_reprocessos=2)
    app.state.http_ativacao = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda pedido: httpx.Response(200, json={"ok": True, "feito": "teste"})))

    email_admin = f"admin-{uuid.uuid4().hex[:6]}@lawchat.com"
    await banco._pool.execute(
        "insert into agentesia_usuarios (email, nome, senha_hash, papel) values ($1, 'Equipe', $2, 'admin_lawchat')",
        email_admin, seguranca.gerar_hash("senha-admin-123"))
    cliente = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://painel")
    try:
        yield cliente, email_admin, banco
    finally:
        await cliente.aclose()
        await banco.fechar()


async def _escritorio_com_agente(cliente, nome):
    # Token diferente por escritório: cada conta da Helena simulada tem os próprios canais.
    escritorio = (await cliente.post("/api/admin/escritorios", json={
        "nome": nome, "id_conta_helena": str(uuid.uuid4()), "token_helena": f"token-bom-{uuid.uuid4().hex[:8]}"})).json()["escritorio"]
    h = {"x-escritorio": escritorio["id"]}
    canal = next(c for c in (await cliente.get("/api/integracoes", headers=h)).json()["canais"] if c["tipo"] != "oficial")
    agente = (await cliente.post("/api/agentes", headers=h, json={"nome": "Júlia", "id_canal": canal["id"]})).json()
    return escritorio["id"], canal["id"], agente["id"], h


async def _lead(pool, id_escritorio, id_canal, id_agente, *, nome, telefone, estado="ativo", origem=None):
    contato = await pool.fetchval(
        "insert into agentesia_contatos (id_escritorio, nome, telefone_normalizado) values ($1::uuid, $2, $3) returning id",
        id_escritorio, nome, telefone)
    etapa = await pool.fetchval(
        "select id from agentesia_agente_etapas where id_agente = $1::uuid order by ordem limit 1", id_agente)
    return str(await pool.fetchval(
        """insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_agente, id_etapa, estado, origem,
                                        ultima_mensagem_lead_em, ultima_resposta_ia_em)
           values ($1::uuid, $2, $3::uuid, $4::uuid, $5, $6, $7::jsonb, now() - interval '1 minute', now()) returning id""",
        id_escritorio, contato, id_canal, id_agente, etapa, estado, json.dumps(origem or {})))


async def test_conversa_no_painel(ambiente):
    cliente, email_admin, banco = ambiente
    pool = banco._pool
    await _entrar(cliente, email_admin, "senha-admin-123")
    id_escritorio, id_canal, id_agente, h = await _escritorio_com_agente(cliente, "Conversas Ltda")

    # Escritório sem conversa: lista vazia (a tela mostra "Nenhuma conversa ainda").
    assert (await cliente.get("/api/conversas", headers=h)).json() == []

    telefone = "5511" + str(uuid.uuid4().int)[:9]
    origem = {"origem": "anuncio", "campanha": "Auxílio 2026", "titulo": "Sofreu acidente?", "url": "https://fb.me/x"}
    id_lead = await _lead(pool, id_escritorio, id_canal, id_agente, nome="Maria Souza", telefone=telefone, origem=origem)
    await _lead(pool, id_escritorio, id_canal, id_agente, nome="João Pausado", telefone="5531" + str(uuid.uuid4().int)[:9], estado="pausado")

    turno = await pool.fetchval(
        """insert into agentesia_turnos (id_escritorio, id_lead, modo, etapa_antes, etapa_depois, resposta, situacao, motivo, concluido_em)
           values ($1::uuid, $2::uuid, 'producao', 'sdr', 'closer', $3::jsonb, 'respondido', 'etapa completa', now()) returning id""",
        id_escritorio, id_lead, json.dumps({"fatos_novos": [{"chave": "acidente_descricao", "valor": "caí da moto"}]}))
    # Os quatro tipos de balão: lead (com áudio transcrito), IA, atendente e aviso do sistema.
    await pool.execute(
        """insert into agentesia_mensagens (id_escritorio, id_lead, id_turno, autor, tipo, texto, texto_extraido, enviada_em, situacao_envio, erro) values
             ($1::uuid, $2::uuid, null, 'lead', 'audio', null, 'caí da moto ano passado', now() - interval '5 minutes', 'recebida', null),
             ($1::uuid, $2::uuid, $3, 'ia', 'texto', 'Poxa, sinto muito. Ficou com sequela?', null, now() - interval '4 minutes', 'enviada', null),
             ($1::uuid, $2::uuid, $3, 'ia', 'texto', 'Pode me mandar o laudo?', null, now() - interval '3 minutes', 'falhou', 'Helena recusou'),
             ($1::uuid, $2::uuid, null, 'humano', 'texto', 'Oi Maria, aqui é a Dra. Paula.', null, now() - interval '2 minutes', 'enviada', null),
             ($1::uuid, $2::uuid, null, 'sistema', 'texto', '📣 Lead veio de anúncio', null, now() - interval '1 minute', 'recebida', null)""",
        id_escritorio, id_lead, turno)
    await pool.execute(
        """insert into agentesia_lead_fatos (id_escritorio, id_lead, chave, valor, trecho, fonte, substituido_em) values
             ($1::uuid, $2::uuid, 'tinha_carteira', 'false'::jsonb, 'não tinha', 'extrator', now()),
             ($1::uuid, $2::uuid, 'tinha_carteira', 'true'::jsonb, 'tinha sim, de carteira assinada', 'extrator', null)""",
        id_escritorio, id_lead)
    await pool.execute(
        """insert into agentesia_eventos (id_escritorio, id_lead, id_turno, tipo, gravidade, responsavel, descricao)
           values ($1::uuid, $2::uuid, $3, 'trava_honorarios', 'aviso', 'lead', 'A IA segurou um valor de honorários.')""",
        id_escritorio, id_lead, turno)

    # Lista: o mais recente primeiro, com a última mensagem para a prévia e o nome do agente para o filtro.
    lista = (await cliente.get("/api/conversas", headers=h)).json()
    assert len(lista) == 2 and all(CAMPOS_LISTA <= set(c) for c in lista)
    maria = next(c for c in lista if c["id"] == id_lead)
    assert maria["ultima_mensagem"] == "📣 Lead veio de anúncio" and maria["agente"] == "Júlia" and maria["etapa"]
    assert {c["estado"] for c in lista} == {"ativo", "pausado"}

    # Busca por nome (sem diferenciar maiúscula) e por parte do telefone; curinga do LIKE não vale.
    assert [c["id"] for c in (await cliente.get("/api/conversas", params={"busca": "maria"}, headers=h)).json()] == [id_lead]
    assert [c["id"] for c in (await cliente.get("/api/conversas", params={"busca": telefone[-6:]}, headers=h)).json()] == [id_lead]
    assert len((await cliente.get("/api/conversas", params={"busca": "%"}, headers=h)).json()) == 2

    # Conversa aberta: balões na ordem do WhatsApp, mídia com o texto extraído, falha de envio com o erro.
    conversa = (await cliente.get(f"/api/conversas/{id_lead}", headers=h)).json()
    assert CAMPOS_CONVERSA <= set(conversa)
    assert all(CAMPOS_MENSAGEM <= set(m) for m in conversa["mensagens"])
    assert [m["autor"] for m in conversa["mensagens"]] == ["lead", "ia", "ia", "humano", "sistema"]
    audio = conversa["mensagens"][0]
    assert (audio["tipo"], audio["texto"], audio["texto_extraido"]) == ("audio", None, "caí da moto ano passado")
    falhou = conversa["mensagens"][2]
    assert (falhou["situacao_envio"], falhou["erro"], falhou["id_turno"]) == ("falhou", "Helena recusou", str(turno))
    # Origem e valores dos fatos já chegam como objeto (não como texto JSON), e o fato trocado fica marcado.
    assert conversa["origem"]["campanha"] == "Auxílio 2026" and conversa["origem"]["origem"] == "anuncio"
    vigentes = [f for f in conversa["fatos"] if f["substituido_em"] is None]
    assert [(f["chave"], f["valor"], f["trecho"]) for f in vigentes] == [("tinha_carteira", True, "tinha sim, de carteira assinada")]
    assert len(conversa["fatos"]) == 2
    t = conversa["turnos"][0]
    assert (t["etapa_antes"], t["etapa_depois"], t["situacao"], t["modo"]) == ("sdr", "closer", "respondido", "producao")
    assert t["resposta"]["fatos_novos"][0]["valor"] == "caí da moto" and t["concluido_em"]
    assert conversa["eventos"][0]["tipo"] == "trava_honorarios" and conversa["eventos"][0]["responsavel"] == "lead"

    # Botões da tela: desativar, reativar, encerrar (pausar/devolver são os nomes antigos). Cada um grava o estado e o
    # motivo e entra no histórico. Desativar/reativar seguem o caminho da etiqueta (docs/LIGAR_DESLIGAR_IA.md).
    for acao, estado, motivo in (("pausar", "pausado", "desativada_pela_equipe"), ("devolver", "ativo", None),
                                 ("desativar", "pausado", "desativada_pela_equipe"), ("reativar", "ativo", None),
                                 ("encerrar", "encerrado", "encerrado_pela_equipe")):
        resposta = await cliente.post(f"/api/conversas/{id_lead}/ia", json={"acao": acao}, headers=h)
        assert resposta.status_code == 200 and resposta.json()["estado"] == estado, resposta.text
        depois = (await cliente.get(f"/api/conversas/{id_lead}", headers=h)).json()
        assert (depois["estado"], depois["motivo_estado"], depois["pausado_ate"]) == (estado, motivo, None)
    assert (await cliente.post(f"/api/conversas/{id_lead}/ia", json={"acao": "apagar"}, headers=h)).status_code == 400
    historico = (await cliente.get("/api/alteracoes", headers=h)).json()
    assert {"desligou_ia", "religou_ia", "encerrar"} <= {x["acao"] for x in historico if x["tabela"] == "agentesia_leads"}

    # Conversa de outro escritório: a tela mostra "Conversa não encontrada" (404), sem mexer nela.
    id_outro, _canal, _agente, h_outro = await _escritorio_com_agente(cliente, "Outro Escritório")
    nao = await cliente.get(f"/api/conversas/{id_lead}", headers=h_outro)
    assert nao.status_code == 404 and nao.json()["detail"] == "Conversa não encontrada."
    assert (await cliente.post(f"/api/conversas/{id_lead}/ia", json={"acao": "pausar"}, headers=h_outro)).status_code == 404
    assert (await cliente.get(f"/api/conversas/{uuid.uuid4()}", headers=h)).status_code == 404
    assert (await cliente.get("/api/conversas", headers=h_outro)).json() == []

    # O atendente do escritório abre a tela e devolve a conversa para a IA.
    usuario = (await cliente.post("/api/escritorio/usuarios", headers=h, json={
        "email": f"atendente-{uuid.uuid4().hex[:6]}@escritorio.com", "nome": "Ana", "papel": "atendente"})).json()
    await cliente.post("/api/sair")
    await _entrar(cliente, usuario["usuario"]["email"], usuario["senha_provisoria"])
    assert len((await cliente.get("/api/conversas")).json()) == 2
    assert (await cliente.post(f"/api/conversas/{id_lead}/ia", json={"acao": "devolver"})).json()["estado"] == "ativo"
