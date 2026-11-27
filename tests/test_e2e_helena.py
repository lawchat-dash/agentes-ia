"""Bateria PONTA A PONTA: webhook da Helena -> FastAPI -> Postgres (PGlite local) -> IA falsa -> Helena falsa.

Sobe o app FastAPI de verdade (httpx ASGI, no mesmo laço de eventos do teste), um Postgres local em memória com todas
as migrações (db/testes/servidor_local.mjs, porta AGENTESIA_E2E_PORTA ou 55615), a HELENA FALSA (httpx.MockTransport
que registra cada chamada: texto, arquivo, nota, card, etiqueta, status) e o ModeloFalso no lugar da OpenAI. A
ZapSign também é falsa (mesmo MockTransport). Nada sai para a rede: o único cliente HTTP do sistema é o falso.

O agente é o do catálogo Sousa e Costa (avaliacao/agentes/sousa_costa_corrigido.json): os prompts reais dos papéis,
com as automações de CRM (card, etiqueta e nota) ligadas para o teste. Todos os dados de lead são inventados.

O webhook segue o formato real da Helena (docs/HELENA_API.md e app/canal/helena.py): {eventType, date, content{id,
companyId, sessionId, type, text, direction, origin, timestamp, details{from, to, file, transcription}}}.

Sem node ou sem as dependências do PGlite (db/testes/node_modules), a bateria é pulada.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.modelo import ErroModelo, ModeloFalso

RAIZ = Path(__file__).resolve().parent.parent
PORTA = int(os.environ.get("AGENTESIA_E2E_PORTA", "55615"))
URL_PG = f"postgresql://postgres:postgres@127.0.0.1:{PORTA}/postgres"
URL_HELENA = "https://api.helena.falsa"
HOST_ARQUIVOS = "arquivos.helena.falsa"           # CDN dos arquivos que o lead manda
HOST_ZAPSIGN = "api.zapsign.com.br"                # interceptado pelo MockTransport: nunca sai para a rede
AGENTE_JSON = RAIZ / "avaliacao" / "agentes" / "sousa_costa_corrigido.json"
SEM_INTENCAO = {"pediu_humano": False, "pediu_para_parar": False, "engano": False, "diz_que_assinou": False,
                "pediu_link": False}
# Mídias do roteiro do Closer (estão no prompt real): áudio de voz e vídeo.
AUDIO_ROTEIRO = "https://mqkgzkzlysvwjjuwvxul.supabase.co/storage/v1/object/public/midia/Como%20Funciona%20o%20Auxilio%20Acidente.ogg"
VIDEO_ROTEIRO = "https://mqkgzkzlysvwjjuwvxul.supabase.co/storage/v1/object/public/midia/video-honorarios-5salarios.mp4"
FRASE_CLOSER = "Maravilha! Nós podemos te ajudar no seu caso."
CPF_FICTICIO = "529.982.247-25"                    # CPF de exemplo (dígitos válidos), não é de ninguém do projeto
# Bytes mínimos com a assinatura de cada formato (o código detecta o formato pelos bytes).
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
OGG = b"OggS" + b"\x00" * 64


# ============================================================================ banco local (PGlite)
def _node_pronto() -> str | None:
    if not shutil.which("node"):
        return "sem node no PATH"
    if not (RAIZ / "db" / "testes" / "node_modules" / "@electric-sql").is_dir():
        return "sem db/testes/node_modules (rode npm install em db/testes)"
    return None


@pytest.fixture(scope="module")
def banco_local():
    """Sobe o PGlite com as migrações numa porta própria e derruba no fim do módulo."""
    if motivo := _node_pronto():
        pytest.skip(motivo)
    processo = subprocess.Popen(["node", "servidor_local.mjs", str(PORTA)], cwd=RAIZ / "db" / "testes",
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
    pronto = threading.Event()
    saida: list[str] = []

    def ler() -> None:
        for linha in processo.stdout:                              # type: ignore[union-attr]
            saida.append(linha)
            if "pronto" in linha:
                pronto.set()

    threading.Thread(target=ler, daemon=True).start()
    if not pronto.wait(90):
        processo.kill()
        pytest.fail("PGlite não subiu: " + "".join(saida[-20:]))
    try:
        yield URL_PG
    finally:
        processo.kill()
        processo.wait(10)


# ============================================================================ Helena falsa (+ ZapSign falsa)
class HelenaFalsa:
    """MockTransport: registra cada chamada e responde como a Helena (e a ZapSign) responderiam."""

    def __init__(self) -> None:
        self.chamadas: list[dict[str, Any]] = []
        self.arquivos: dict[str, tuple[bytes, str]] = {}           # url do CDN -> (bytes, content-type)
        self.baixados: list[str] = []
        self.falhar_envio = 0                                       # próximos POST de mensagem que devolvem 500
        self.status_mensagem = "DELIVERED"
        self.id_contato = "contato-" + uuid.uuid4().hex[:8]
        self.cards: dict[str, str] = {}                             # id do card -> etapa
        self.zapsign_criados: list[dict[str, Any]] = []
        self.zapsign_assinado = False
        self.prefixo = uuid.uuid4().hex[:6]                         # ids únicos (o banco é reaproveitado no módulo)
        self._n = 0

    def _id(self, tipo: str) -> str:
        self._n += 1
        return f"{tipo}-{self.prefixo}-{self._n}"

    def __call__(self, pedido: httpx.Request) -> httpx.Response:
        host, caminho, metodo = pedido.url.host, pedido.url.path, pedido.method
        if host == HOST_ARQUIVOS:
            self.baixados.append(str(pedido.url))
            conteudo, tipo = self.arquivos.get(str(pedido.url), (b"", ""))
            return httpx.Response(200 if conteudo else 404, content=conteudo, headers={"content-type": tipo})
        if host == HOST_ZAPSIGN:
            return self._zapsign(pedido)
        if host != "api.helena.falsa":
            raise AssertionError(f"chamada para fora do teste: {pedido.url}")
        corpo = json.loads(pedido.content) if pedido.content else None
        registro = {"metodo": metodo, "caminho": caminho, "corpo": corpo, "auth": pedido.headers.get("authorization"),
                    "params": dict(pedido.url.params)}
        self.chamadas.append(registro)
        if metodo == "POST" and caminho.startswith("/chat/v1/session/") and caminho.endswith("/message"):
            if self.falhar_envio > 0:
                self.falhar_envio -= 1
                registro["falhou"] = True
                return httpx.Response(500, json={"error": True, "text": "erro interno"})
            registro["id"] = self._id("msg")
            return httpx.Response(200, json={"id": registro["id"], "status": "QUEUED"})
        if metodo == "POST" and caminho.endswith("/note"):
            return httpx.Response(200, json={})
        if metodo == "GET" and caminho.startswith("/chat/v2/session/"):
            return httpx.Response(200, json={"id": caminho.rsplit("/", 1)[-1], "contactId": self.id_contato})
        if metodo == "GET" and caminho == "/crm/v2/panel/card":
            return httpx.Response(200, json={"items": []})
        if metodo == "POST" and caminho == "/crm/v2/panel/card":
            id_card = self._id("card")
            self.cards[id_card] = corpo["stepId"]
            return httpx.Response(200, json={"id": id_card})
        if metodo == "PUT" and caminho.startswith("/crm/v3/panel/card/"):
            if "stepId" in (corpo or {}):                # o PUT com Description (resumo do contrato) não move o card
                self.cards[caminho.rsplit("/", 1)[-1]] = corpo["stepId"]
            return httpx.Response(200, json={})
        if metodo == "POST" and caminho.startswith("/core/v1/contact/") and caminho.endswith("/tags"):
            return httpx.Response(200, json={})
        if metodo == "GET" and caminho.startswith("/chat/v1/message/") and caminho.endswith("/status"):
            return httpx.Response(200, json={"status": self.status_mensagem})
        if metodo == "POST" and caminho == "/chat/v1/message/send":
            return httpx.Response(200, json={"id": self._id("aviso")})
        if metodo == "PUT" and caminho.startswith("/chat/v1/session/") and caminho.endswith("/transfer"):
            return httpx.Response(200, json={})                   # transferir o atendimento para um departamento
        return httpx.Response(404, json={"error": True, "text": f"rota falsa não prevista: {metodo} {caminho}"})

    def _zapsign(self, pedido: httpx.Request) -> httpx.Response:
        caminho = pedido.url.path
        if caminho == "/api/v1/models/create-doc/":
            corpo = json.loads(pedido.content)
            self.zapsign_criados.append(corpo)
            n = len(self.zapsign_criados)
            return httpx.Response(200, json={"token": f"doc-{self.prefixo}-{n}", "signers": [
                {"token": f"signer-{self.prefixo}-{n}", "name": corpo["signer_name"], "status": "new",
                 "sign_url": f"https://app.zapsign.com.br/verificar/{self.prefixo}-{n}"}]})
        if caminho.startswith("/api/v1/docs/"):
            token = caminho.rstrip("/").rsplit("/", 1)[-1]
            n = token.rsplit("-", 1)[-1]
            status = "signed" if self.zapsign_assinado else "new"
            return httpx.Response(200, json={
                "token": token, "status": status, "signed_file": "https://zapsign.falsa/assinado.pdf" if self.zapsign_assinado else None,
                "signers": [{"token": f"signer-{self.prefixo}-{n}", "name": "Carla Mendes Ribeiro", "status": status,
                             "phone_number": "31977770000", "signed_at": "2026-11-25T15:00:00Z" if self.zapsign_assinado else None}]})
        return httpx.Response(404, json={"message": "não encontrado"})

    # ---- leitura do que chegou
    def envios(self, sessao: str | None = None) -> list[dict[str, Any]]:
        """Corpos dos POST de mensagem no atendimento (só os aceitos), na ordem."""
        return [c["corpo"] for c in self.chamadas if c["metodo"] == "POST" and c["caminho"].endswith("/message")
                and c["caminho"].startswith("/chat/v1/session/") and not c.get("falhou")
                and (sessao is None or f"/session/{sessao}/" in c["caminho"])]

    def textos(self, sessao: str | None = None) -> list[str]:
        return [e["text"] for e in self.envios(sessao) if "text" in e]

    def arquivos_enviados(self, sessao: str | None = None) -> list[str]:
        return [e["fileUrl"] for e in self.envios(sessao) if "fileUrl" in e]

    def notas(self) -> list[str]:
        return [c["corpo"]["text"] for c in self.chamadas if c["metodo"] == "POST" and c["caminho"].endswith("/note")]

    def etiquetas(self) -> list[tuple[str, tuple[str, ...]]]:
        return [(c["corpo"]["operation"], tuple(c["corpo"]["tagNames"])) for c in self.chamadas
                if c["caminho"].endswith("/tags")]

    def movimentos_de_card(self) -> list[tuple[str, str]]:
        """(card, coluna) de cada card criado (POST) ou movido (PUT), na ordem."""
        saida = []
        for c in self.chamadas:
            if c["metodo"] == "PUT" and c["caminho"].startswith("/crm/v3/panel/card/") and "stepId" in (c["corpo"] or {}):
                saida.append((c["caminho"].rsplit("/", 1)[-1], c["corpo"]["stepId"]))
            elif c["metodo"] == "POST" and c["caminho"] == "/crm/v2/panel/card":
                saida.append(("novo", c["corpo"]["stepId"]))
        return saida

    def transferencias(self) -> list[tuple[str, str]]:
        """(atendimento, departamento) de cada transferência pedida à Helena."""
        return [(c["caminho"].split("/")[4], c["corpo"]["newDepartmentId"]) for c in self.chamadas
                if c["metodo"] == "PUT" and c["caminho"].endswith("/transfer")]


class VisaoFalsa:
    """No lugar da visão e da transcrição da OpenAI."""

    def __init__(self) -> None:
        self.transcricao = "eu caí da escada no trabalho e quebrei o tornozelo"
        self.descricao = "Documento de identidade (RG). Nome: Carla Mendes Ribeiro. CPF: " + CPF_FICTICIO
        self.pedidos: list[str] = []

    async def transcrever_audio(self, dados: bytes, nome: str):
        from app.modelo import Chamada
        self.pedidos.append(f"audio:{nome}:{len(dados)}")
        return self.transcricao, Chamada(papel="transcricao", modelo="falso")

    async def descrever_imagem(self, url: str, mime: str | None, legenda: str | None):
        from app.modelo import Chamada
        self.pedidos.append(f"imagem:{mime}")
        return self.descricao, Chamada(papel="visao", modelo="falso")


# ============================================================================ IA falsa (ModeloFalso por papel)
def extrai(fatos=(), **intencoes) -> dict[str, Any]:
    return {"fatos": [{"chave": c, "valor": v, "trecho": t} for c, v, t in fatos], "sinais": [],
            "intencoes": {**SEM_INTENCAO, **intencoes}}


def responde(*textos: str, transferir_para: str = "", ferramenta: str = "") -> dict[str, Any]:
    return {"mensagens": [{"texto": t} for t in textos], "transferir_para": transferir_para, "ferramenta": ferramenta,
            "notificacao": ""}


QUALIFICADO = (("aposentado", "nao"), ("tem_advogado_no_caso", "nao"), ("sequela", "sim"), ("aceite_honorarios", "sim"))


async def qualificar(e2e: "Cenario", fatos=QUALIFICADO) -> None:
    """Leva 1 (B4): os fatos do portão já respondidos (como se o lead tivesse contado em turnos anteriores). Sem eles o
    motor segura a passagem para o Closer e para Contratos (e o desqualificar sem motivo)."""
    from types import SimpleNamespace

    lead = await e2e.lead()
    await e2e.repo.gravar_fatos(lead=SimpleNamespace(id=str(lead["id"]), id_escritorio=str(lead["id_escritorio"])),
                                id_turno=None, fatos=[{"chave": c, "valor": v, "trecho": f"(teste) {c}", "fonte": "equipe"}
                                                      for c, v in fatos])


class IAFalsa:
    """Roteiro trocável por teste: `extrator` e `etapa` recebem (sistema, conteudo). `falhar` derruba a chamada."""

    def __init__(self) -> None:
        self.extrator = lambda _s, _c: extrai()
        self.etapa = lambda _s, _c: responde("Oi! Aqui é a Ana, do escritório. Como posso te ajudar?")
        self.falhar: dict[str, ErroModelo] = {}

    def _papel(self, nome: str):
        def chamar(sistema: str, conteudo: str) -> dict[str, Any]:
            if nome in self.falhar:
                raise self.falhar[nome]
            return getattr(self, nome)(sistema, conteudo)
        return chamar

    def modelo(self) -> ModeloFalso:
        return ModeloFalso({"extrator": self._papel("extrator"), "etapa": self._papel("etapa"),
                            "contrato_resumo": {"resumo": "Resumo: acidente de trabalho com sequela no tornozelo."},
                            "resumo_conversa": {"resumo": "- Caso: acidente de trabalho."}})


# ============================================================================ cenário (escritório, agente, app)
def _agente_sousa_costa() -> dict[str, Any]:
    dados = json.loads(AGENTE_JSON.read_text(encoding="utf-8"))
    return dados["agente"]


def _linha_propria(instrucao: str, outras: list[str]) -> str:
    """Uma linha do prompt deste papel que não aparece nos outros papéis (para saber qual prompt o turno usou)."""
    for linha in instrucao.splitlines():
        linha = linha.strip()
        if len(linha) > 40 and "{{" not in linha and "http" not in linha and not any(linha in o for o in outras):
            return linha
    raise AssertionError("prompt sem linha própria")


class Cenario:
    def __init__(self, repo, atendimento, executor, helena: HelenaFalsa, ia: IAFalsa, visao: VisaoFalsa,
                 http_app: httpx.AsyncClient, ids: dict[str, Any], agente: dict[str, Any]) -> None:
        self.repo, self.pool, self.atendimento, self.executor = repo, repo._pool, atendimento, executor
        self.helena, self.ia, self.visao, self.http = helena, ia, visao, http_app
        self.ids, self.agente = ids, agente
        self.telefone = "5531977" + str(uuid.uuid4().int)[:6]     # número inventado (31 = BH)
        self.sessao = "sessao-" + uuid.uuid4().hex[:12]
        self._n = 0
        self.prompts = {e["codigo"]: e.get("instrucao") or "" for e in agente["etapas"]}

    # ---- webhooks no formato da Helena
    def _conteudo(self, **extra: Any) -> dict[str, Any]:
        self._n += 1
        return {"id": extra.pop("id_msg", None) or str(uuid.uuid4()), "companyId": self.ids["conta"],
                "sessionId": self.sessao, "channelId": self.ids["id_canal_helena"], "contactId": self.helena.id_contato,
                "timestamp": (extra.pop("quando", None) or datetime.now(timezone.utc)).isoformat(), **extra}

    def do_lead(self, texto: str | None = None, *, tipo: str = "TEXT", arquivo: dict[str, Any] | None = None,
                transcricao: str | None = None, id_msg: str | None = None, quando: datetime | None = None) -> dict[str, Any]:
        detalhes: dict[str, Any] = {"from": "+" + self.telefone, "to": "+" + self.ids["numero_canal"]}
        if arquivo:
            detalhes["file"] = arquivo
        if transcricao is not None:
            detalhes["transcription"] = {"text": transcricao}
        return {"eventType": "MESSAGE_RECEIVED", "date": datetime.now(timezone.utc).isoformat(),
                "content": self._conteudo(id_msg=id_msg, quando=quando, type=tipo, text=texto, direction="FROM_HUB",
                                          origin="GATEWAY", contact={"name": "Carla Mendes"}, details=detalhes)}

    def do_atendente(self, texto: str, *, origem: str = "DEFAULT") -> dict[str, Any]:
        """Mensagem enviada pela equipe na Helena (fromMe): MESSAGE_SENT, direção TO_HUB."""
        return {"eventType": "MESSAGE_SENT", "date": datetime.now(timezone.utc).isoformat(),
                "content": self._conteudo(type="TEXT", text=f"*Paula:* {texto}", direction="TO_HUB", origin=origem,
                                          details={"from": "+" + self.ids["numero_canal"], "to": "+" + self.telefone})}

    def arquivo(self, nome: str, conteudo: bytes, mime: str) -> dict[str, Any]:
        url = f"https://{HOST_ARQUIVOS}/{uuid.uuid4().hex}/{nome}"
        self.helena.arquivos[url] = (conteudo, mime)
        return {"publicUrl": url, "name": nome, "mimeType": mime}

    # ---- rotas do app
    async def postar(self, corpo: dict[str, Any]) -> httpx.Response:
        from app.canal.webhook import segredo_do_escritorio
        esc = self.ids["escritorio"]
        return await self.http.post(f"/webhook/helena/{esc}?segredo={segredo_do_escritorio(esc)}", json=corpo)

    async def botao_ia(self, acao: str) -> httpx.Response:
        from app.canal.webhook import segredo_do_escritorio
        esc = self.ids["escritorio"]
        return await self.http.post(f"/webhook/helena/{esc}/ia?segredo={segredo_do_escritorio(esc)}",
                                    json={"acao": acao, "sessionId": self.sessao})

    async def zapsign(self, corpo: dict[str, Any]) -> httpx.Response:
        from app.canal.webhook import segredo_do_escritorio
        esc = self.ids["escritorio"]
        return await self.http.post(f"/webhook/zapsign/{esc}?segredo={segredo_do_escritorio(esc, 'zapsign')}", json=corpo)

    async def esperar(self) -> None:
        """Turnos agendados (e leituras de mídia) terminam."""
        await asyncio.wait_for(self.atendimento.aguardar_esperas(), 30)

    async def rodar_fila(self, rodadas: int = 12) -> int:
        """Executor da fila (card, etiqueta, nota, contrato...) até não sobrar ação vencida."""
        total = 0
        for _ in range(rodadas):
            feitas = await self.executor.rodar_uma_vez()
            total += feitas
            if not feitas:
                break
        return total

    async def chega(self, corpo: dict[str, Any], fila: bool = True) -> dict[str, Any]:
        resposta = await self.postar(corpo)
        assert resposta.status_code == 200, resposta.text
        await self.esperar()
        if fila:
            await self.rodar_fila()
        return resposta.json()

    # ---- banco
    async def lead(self) -> dict[str, Any] | None:
        linha = await self.pool.fetchrow(
            """select l.*, e.codigo as etapa, c.nome as nome_contato from agentesia_leads l
               join agentesia_contatos c on c.id = l.id_contato
               left join agentesia_agente_etapas e on e.id = l.id_etapa
               where l.id_escritorio = $1::uuid and c.telefone_normalizado = $2""", self.ids["escritorio"], self.telefone)
        return dict(linha) if linha else None

    async def mensagens(self) -> list[dict[str, Any]]:
        lead = await self.lead()
        return [dict(m) for m in await self.pool.fetch(
            "select * from agentesia_mensagens where id_lead = $1 order by enviada_em, registrada_em", lead["id"])]

    async def turnos(self) -> list[dict[str, Any]]:
        lead = await self.lead()
        return [dict(t) for t in await self.pool.fetch(
            "select * from agentesia_turnos where id_lead = $1 order by iniciado_em", lead["id"])]

    async def eventos(self, tipo: str | None = None) -> list[dict[str, Any]]:
        linhas = await self.pool.fetch("select * from agentesia_eventos where id_escritorio = $1::uuid order by criado_em",
                                       self.ids["escritorio"])
        return [dict(e) for e in linhas if tipo is None or e["tipo"] == tipo]

    async def por_na_etapa(self, codigo: str) -> None:
        """Põe o lead numa etapa (como a equipe faria pelo painel)."""
        from app.contrato import servico
        lead = await self.lead()
        assert await servico.mover_lead_para_etapa(self.pool, str(lead["id"]), codigo, origem="equipe")

    def pedidos(self, papel: str) -> list[dict[str, Any]]:
        return [p for p in self.atendimento.modelo.pedidos if p["papel"] == papel]


async def _cadastrar(pool, agente: dict[str, Any]) -> dict[str, Any]:
    """Escritório, canal, integrações (Helena, CRM, ZapSign) e o agente Sousa e Costa, com ids novos."""
    conta = str(uuid.uuid4())
    numero_canal = "5531" + str(uuid.uuid4().int)[:9]
    id_canal_helena = "canal-" + uuid.uuid4().hex[:8]
    token_h = await pool.fetchval("select vault.create_secret($1, 'teste e2e')", "token-helena-falso-" + uuid.uuid4().hex[:6])
    token_z = await pool.fetchval("select vault.create_secret($1, 'teste e2e')", "token-zapsign-falso-" + uuid.uuid4().hex[:8])
    esc = await pool.fetchval(
        "insert into agentesia_escritorios (nome, id_conta_helena, config) values ($1, $2::uuid, $3::jsonb) returning id",
        "Sousa e Costa Advogados", conta, json.dumps({"filtro": {"rajada": {"mensagens": 1000, "segundos": 1}}}))
    await pool.execute("insert into agentesia_integracoes (id_escritorio, tipo, id_segredo_vault, situacao) values ($1, 'helena', $2, 'ok')",
                       esc, token_h)
    await pool.execute("insert into agentesia_integracoes (id_escritorio, tipo, config, situacao) values ($1, 'crm', $2::jsonb, 'ok')",
                       esc, json.dumps({"id_painel": "painel-comercial"}))
    await pool.execute(
        "insert into agentesia_integracoes (id_escritorio, tipo, id_segredo_vault, config, situacao) values ($1, 'zapsign', $2, $3::jsonb, 'ok')",
        esc, token_z, json.dumps({"modelos": [{"id_modelo": "modelo-aa", "padrao": True}],
                                  "lembretes": {"ativo": True, "horas": [2]}}))
    canal = await pool.fetchval(
        "insert into agentesia_canais (id_escritorio, numero_normalizado, id_canal_helena) values ($1, $2, $3) returning id",
        esc, numero_canal, id_canal_helena)
    config = dict(agente["config"])
    config["funcoes"] = {"contrato_zapsign": True, "buscar_cep": False, "crm": True, "avisos": True}
    config["automacoes"] = {
        "lead_novo": {"coluna_crm": "col-sdr", "adicionar_etiquetas": ["📞 SDR"]},
        "etapa:closer": {"coluna_crm": "col-closer", "adicionar_etiquetas": ["🛒 Comercial"], "remover_etiquetas": ["📞 SDR"],
                         "nota": "🔀 Lead passou para o Closer."},
        "etapa:assinatura": {"coluna_crm": "col-assinatura"},
        "etapa:contrato_assinado": {"coluna_crm": "col-assinado", "nota": "✅ Contrato assinado."},
    }
    id_agente = await pool.fetchval(
        """insert into agentesia_agentes (id_escritorio, id_canal, nome, produto, situacao, modo, config)
           values ($1, $2, $3, 'catalogo', 'ativo', 'producao', $4::jsonb) returning id""",
        esc, canal, agente["nome"], json.dumps(config, ensure_ascii=False))
    etapas = {}
    for ordem, e in enumerate(agente["etapas"]):
        etapas[e["codigo"]] = await pool.fetchval(
            """insert into agentesia_agente_etapas (id_agente, codigo, ordem, tipo, principal, instrucao, modelo)
               values ($1, $2, $3, $4, $5, $6, $7) returning id""",
            id_agente, e["codigo"], ordem, "terminal" if e["codigo"] == "contrato_assinado" else "conversa",
            bool(e.get("principal")), e.get("instrucao") or None, e.get("modelo"))
    return {"escritorio": str(esc), "conta": conta, "numero_canal": numero_canal, "id_canal_helena": id_canal_helena,
            "canal": str(canal), "agente": str(id_agente), "etapas": {k: str(v) for k, v in etapas.items()}}


@pytest.fixture
async def e2e(banco_local, monkeypatch):
    from app.acoes import Executor
    from app.banco.postgres import RepositorioPostgres
    from app.canal.helena import ClienteHelena
    from app.config import Configuracao
    from app.gestao.repositorio import RepositorioGestao
    from app.gestao.seguranca import Assinador
    from app.main import app
    from app.pipeline import Atendimento

    monkeypatch.setenv("AGENTESIA_WEBHOOK_SEGREDO", "segredo-mestre-do-teste-e2e")
    for chave in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "AGENTESIA_HELENA_TOKEN_LAWCHAT", "AGENTESIA_MODO_LAB"):
        monkeypatch.delenv(chave, raising=False)
    repo = await RepositorioPostgres.conectar(banco_local, max_conexoes=1)     # o PGlite aceita uma conexão
    pool = repo._pool
    # A fila é do banco inteiro: ação pendente de outro teste não atravessa este.
    await pool.execute("update agentesia_acoes set situacao = 'cancelada' where situacao in ('pendente', 'executando')")
    agente = _agente_sousa_costa()
    ids = await _cadastrar(pool, agente)

    helena, ia, visao = HelenaFalsa(), IAFalsa(), VisaoFalsa()
    http_falso = httpx.AsyncClient(transport=httpx.MockTransport(helena))
    cliente = ClienteHelena(URL_HELENA, http=http_falso)

    async def sem_pausa(_s: float) -> None:
        return None

    cliente._pausa = sem_pausa                                  # novas tentativas sem esperar 2,5 s
    cfg = Configuracao(banco_url=banco_local, helena_url=URL_HELENA, modelo_padrao="gpt-4.1-mini", modelo_falso=True,
                       espera_minima_s=0, espera_maxima_s=0, espera_padrao_s=0, segundos_por_letra=0, max_reprocessos=2,
                       espera_midia_s=10)
    modelo = ia.modelo()
    atendimento = Atendimento(repo, modelo, cfg, helena=cliente, digitar=False, visao=visao, http_midia=http_falso,
                              vetorizador=None)
    executor = Executor(pool, URL_HELENA, modelo=modelo, http=http_falso)
    monkeypatch.setattr(app.state, "atendimento", atendimento, raising=False)
    monkeypatch.setattr(app.state, "gestao", RepositorioGestao(pool), raising=False)
    monkeypatch.setattr(app.state, "assinador", Assinador(), raising=False)
    http_app = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://lawchat.test")
    cenario = Cenario(repo, atendimento, executor, helena, ia, visao, http_app, ids, agente)
    try:
        yield cenario
    finally:
        try:
            await asyncio.wait_for(atendimento.encerrar(teto_s=5), 10)
        finally:
            await http_app.aclose()
            await http_falso.aclose()
            pool.terminate()                                    # o close() do PGlite pode não responder


# ============================================================================ 1) lead novo
async def test_lead_novo_cria_lead_card_etiqueta_e_ia_responde_em_baloes_na_ordem(e2e: Cenario):
    e2e.ia.etapa = lambda _s, _c: responde("Oi, Carla! Aqui é a Ana, do Sousa e Costa Advogados.",
                                           "Me conta: como foi o acidente que você sofreu?")
    resultado = await e2e.chega(e2e.do_lead("Oi, vi o anúncio do auxílio-acidente"))
    assert resultado["feito"] == "agendado"

    # Helena: os dois balões, na ordem, no atendimento certo, com o canal e o token do escritório.
    assert e2e.helena.textos(e2e.sessao) == ["Oi, Carla! Aqui é a Ana, do Sousa e Costa Advogados.",
                                             "Me conta: como foi o acidente que você sofreu?"]
    envio = next(c for c in e2e.helena.chamadas if c["caminho"].endswith("/message"))
    assert envio["corpo"]["channelId"] == e2e.ids["id_canal_helena"] and envio["auth"].startswith("Bearer token-helena-falso")
    # Card do lead na coluna SDR e etiqueta SDR no contato.
    criados = [c for c in e2e.helena.chamadas if c["metodo"] == "POST" and c["caminho"] == "/crm/v2/panel/card"]
    assert len(criados) == 1 and criados[0]["corpo"]["stepId"] == "col-sdr"
    assert criados[0]["corpo"]["sessionId"] == e2e.sessao and criados[0]["corpo"]["contactIds"] == [e2e.helena.id_contato]
    assert ("InsertIfNotExists", ("📞 SDR",)) in e2e.helena.etiquetas()

    # Banco: lead na etapa SDR, ativo, com o nome do WhatsApp; mensagens na ordem; turno respondido; card guardado.
    lead = await e2e.lead()
    assert (lead["etapa"], lead["estado"], lead["id_sessao_helena"], lead["nome_contato"]) == ("sdr", "ativo", e2e.sessao, "Carla Mendes")
    mensagens = await e2e.mensagens()
    assert [(m["autor"], m["situacao_envio"]) for m in mensagens] == [("lead", "recebida"), ("ia", "enviada"), ("ia", "enviada")]
    assert all(m["id_externo"] for m in mensagens)                   # eco da IA é reconhecido pelo id
    turnos = await e2e.turnos()
    assert [(t["situacao"], t["etapa_antes"], t["etapa_depois"]) for t in turnos] == [("respondido", "sdr", "sdr")]
    card = await e2e.pool.fetchrow("select * from agentesia_crm_cards where id_lead = $1", lead["id"])
    assert card["id_etapa_helena"] == "col-sdr" and card["situacao"] == "ok"
    # O prompt usado foi o do SDR do Sousa e Costa.
    sistema = e2e.pedidos("etapa")[0]["sistema"]
    outros = [p for c, p in e2e.prompts.items() if c != "sdr"]
    assert _linha_propria(e2e.prompts["sdr"], outros) in sistema

    # O eco do envio da própria IA (MESSAGE_SENT, origem API) não pausa nem grava de novo.
    eco = e2e.do_atendente("Oi, Carla!", origem="API")
    eco["content"]["id"] = mensagens[1]["id_externo"]
    assert (await e2e.chega(eco))["motivo"] == "eco_da_ia"
    assert (await e2e.lead())["estado"] == "ativo"


# ============================================================================ 2) webhook repetido
async def test_webhook_duplicado_gera_uma_resposta_so(e2e: Cenario):
    e2e.ia.etapa = lambda _s, _c: responde("Oi! Me conta o que aconteceu?")
    corpo = e2e.do_lead("Boa tarde, quero saber do auxílio")
    primeira, segunda = await asyncio.gather(e2e.postar(corpo), e2e.postar(corpo))   # a Helena reenviou junto
    feitos = sorted([primeira.json()["feito"], segunda.json()["feito"]])
    assert feitos == ["agendado", "ignorado"]
    await e2e.esperar()
    assert (await e2e.chega(corpo))["motivo"] == "repetido"             # e de novo, mais tarde
    assert e2e.helena.textos() == ["Oi! Me conta o que aconteceu?"]
    assert [m["autor"] for m in await e2e.mensagens()] == ["lead", "ia"]
    assert await e2e.pool.fetchval(
        "select count(*) from agentesia_eventos_recebidos where origem = 'helena' and id_externo = $1", corpo["content"]["id"]) == 1


# ============================================================================ 3) mensagens rápidas
async def test_duas_mensagens_rapidas_viram_um_turno(e2e: Cenario):
    await e2e.pool.execute("update agentesia_agentes set config = config || '{\"espera_s\": 0.6}'::jsonb where id = $1::uuid",
                           e2e.ids["agente"])
    e2e.ia.etapa = lambda _s, _c: responde("Poxa, sinto muito pela queda. Você ficou com alguma sequela?")
    base = datetime.now(timezone.utc)
    r1 = await e2e.postar(e2e.do_lead("caí da moto indo pro trabalho", quando=base))
    r2 = await e2e.postar(e2e.do_lead("e machuquei o joelho", quando=base + timedelta(seconds=1)))
    assert r1.json()["feito"] == r2.json()["feito"] == "agendado"
    await e2e.esperar()
    assert e2e.helena.textos() == ["Poxa, sinto muito pela queda. Você ficou com alguma sequela?"]
    turnos = [t for t in await e2e.turnos() if t["situacao"] != "descartado"]
    assert len(turnos) == 1 and turnos[0]["situacao"] == "respondido"
    conteudo = e2e.pedidos("etapa")[-1]["conteudo"]
    assert "- caí da moto indo pro trabalho\n- e machuquei o joelho" in conteudo
    mensagens = await e2e.mensagens()
    assert len({m["id_turno"] for m in mensagens if m["autor"] == "lead"}) == 1


# ============================================================================ 4) áudio do lead
async def test_audio_do_lead_e_baixado_transcrito_e_respondido(e2e: Cenario):
    def etapa(_s, conteudo):
        if "escada" in conteudo:
            return responde("Sinto muito pela queda na escada, Carla.", "O tornozelo ainda te limita em alguma coisa?")
        return responde("Não consegui entender o áudio, pode escrever?")

    e2e.ia.etapa = etapa
    arquivo = e2e.arquivo("audio-lead.ogg", OGG, "audio/ogg")
    await e2e.chega(e2e.do_lead(None, tipo="AUDIO", arquivo=arquivo))   # sem transcrição da Helena
    assert e2e.helena.baixados == [arquivo["publicUrl"]]
    assert e2e.visao.pedidos and e2e.visao.pedidos[0].startswith("audio:")
    mensagem = (await e2e.mensagens())[0]
    assert (mensagem["tipo"], mensagem["texto_extraido"]) == ("audio", e2e.visao.transcricao)
    assert e2e.visao.transcricao in e2e.pedidos("extrator")[0]["conteudo"]
    assert e2e.helena.textos() == ["Sinto muito pela queda na escada, Carla.", "O tornozelo ainda te limita em alguma coisa?"]


async def test_video_do_lead_sem_transcricao_e_transcrito(e2e: Cenario):
    e2e.ia.etapa = lambda _s, c: responde("Vi seu vídeo, sinto muito pela queda." if "escada" in c else "Não vi o vídeo.")
    arquivo = e2e.arquivo("video-lead.mp4", b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64, "video/mp4")
    await e2e.chega(e2e.do_lead(None, tipo="VIDEO", arquivo=arquivo))
    assert e2e.helena.baixados == [arquivo["publicUrl"]]
    mensagem = (await e2e.mensagens())[0]
    assert mensagem["tipo"] == "video" and e2e.visao.transcricao in mensagem["texto_extraido"]
    assert e2e.helena.textos() == ["Vi seu vídeo, sinto muito pela queda."]


async def test_audio_do_atendente_e_transcrito_para_a_ia_saber_o_que_a_equipe_disse(e2e: Cenario):
    e2e.ia.etapa = lambda _s, _c: responde("Oi!")
    await e2e.chega(e2e.do_lead("oi"))
    e2e.visao.transcricao = "Carla, o doutor vai te ligar amanhã de manhã"
    arquivo = e2e.arquivo("audio-equipe.ogg", OGG, "audio/ogg")
    fala = e2e.do_atendente("")
    fala["content"].update(type="AUDIO", text=None)
    fala["content"]["details"]["file"] = arquivo
    assert (await e2e.chega(fala))["feito"] == "pausado"
    humano = [m for m in await e2e.mensagens() if m["autor"] == "humano"][0]
    assert humano["texto_extraido"] == "[O atendente enviou um áudio. O que ele disse: Carla, o doutor vai te ligar amanhã de manhã]"


async def test_audio_com_transcricao_da_helena_nao_baixa_nada(e2e: Cenario):
    e2e.ia.etapa = lambda _s, c: responde("Entendi, foi no trabalho então." if "no serviço" in c else "Pode repetir?")
    arquivo = e2e.arquivo("audio-lead.ogg", OGG, "audio/ogg")
    await e2e.chega(e2e.do_lead(None, tipo="AUDIO", arquivo=arquivo, transcricao="me machuquei no serviço ano passado"))
    assert e2e.helena.baixados == [] and e2e.visao.pedidos == []
    assert e2e.helena.textos() == ["Entendi, foi no trabalho então."]


# ============================================================================ 5) imagem de documento
async def test_imagem_de_documento_vira_fato_pela_visao(e2e: Cenario):
    def extrator(_s, conteudo):
        if CPF_FICTICIO in conteudo:
            return extrai([("cpf", CPF_FICTICIO, CPF_FICTICIO), ("nome_completo", "Carla Mendes Ribeiro", "Carla Mendes Ribeiro")])
        return extrai()

    e2e.ia.extrator = extrator
    e2e.ia.etapa = lambda _s, _c: responde("Recebi seu documento, obrigada! Agora me conta como foi o acidente?")
    arquivo = e2e.arquivo("rg.png", PNG, "image/png")
    await e2e.chega(e2e.do_lead("segue meu RG", tipo="IMAGE", arquivo=arquivo))
    assert e2e.visao.pedidos == ["imagem:image/png"]
    mensagem = (await e2e.mensagens())[0]
    assert mensagem["tipo"] == "imagem" and e2e.visao.descricao in mensagem["texto_extraido"]
    fatos = await e2e.repo.fatos_vigentes(str((await e2e.lead())["id"]))
    assert fatos["nome_completo"] == "Carla Mendes Ribeiro" and "".join(c for c in str(fatos["cpf"]) if c.isdigit()) == "52998224725"
    assert e2e.helena.textos() == ["Recebi seu documento, obrigada! Agora me conta como foi o acidente?"]


# ============================================================================ 6) SDR -> Closer
async def test_sdr_qualifica_e_passa_para_o_closer(e2e: Cenario):
    outros = {c: [p for k, p in e2e.prompts.items() if k != c] for c in e2e.prompts}
    linha_sdr = _linha_propria(e2e.prompts["sdr"], outros["sdr"])
    linha_closer = _linha_propria(e2e.prompts["closer"], outros["closer"])

    def etapa(sistema, conteudo):
        if linha_closer in sistema:
            return responde("Carla, vou te explicar como funciona o nosso trabalho.")
        if "sequela" in conteudo:
            return responde("Entendi, Carla. Pelo que você contou, seu caso tem chance.", FRASE_CLOSER, transferir_para="closer")
        return responde("Oi, Carla! Como foi o acidente?")

    e2e.ia.etapa = etapa
    await e2e.chega(e2e.do_lead("oi, sofri um acidente"))
    await qualificar(e2e)                                   # leva 1: fatos do portão
    await e2e.chega(e2e.do_lead("caí da escada no trabalho e fiquei com sequela no tornozelo"))

    lead = await e2e.lead()
    assert lead["etapa"] == "closer" and lead["estado"] == "ativo"
    assert e2e.helena.textos()[-2:] == ["Entendi, Carla. Pelo que você contou, seu caso tem chance.", FRASE_CLOSER]
    turnos = await e2e.turnos()
    assert [(t["etapa_antes"], t["etapa_depois"]) for t in turnos if t["situacao"] == "respondido"] == [("sdr", "sdr"), ("sdr", "closer")]
    troca = (await e2e.eventos("etapa_trocada"))[-1]
    assert json.loads(troca["detalhe"])["para"] == "closer" if isinstance(troca["detalhe"], str) else troca["detalhe"]["para"] == "closer"
    historico = await e2e.pool.fetch("select etapa_de, etapa_para from agentesia_lead_etapas where id_lead = $1 order by criado_em",
                                     lead["id"])
    assert ("sdr", "closer") in [(h["etapa_de"], h["etapa_para"]) for h in historico]
    # Helena: card movido para a coluna do Closer, etiqueta trocada e nota da troca.
    card = next(iter(e2e.helena.cards))
    assert e2e.helena.cards[card] == "col-closer"
    assert any(c["metodo"] == "PUT" and c["caminho"] == f"/crm/v3/panel/card/{card}" for c in e2e.helena.chamadas)
    assert ("DeleteIfExists", ("📞 SDR",)) in e2e.helena.etiquetas() and ("InsertIfNotExists", ("🛒 Comercial",)) in e2e.helena.etiquetas()
    assert any(n.startswith("🔀 Lead passou para o Closer.") for n in e2e.helena.notas())

    # Próximo turno já com o prompt do Closer (e sem o do SDR).
    await e2e.chega(e2e.do_lead("e como funciona?"))
    sistema = e2e.pedidos("etapa")[-1]["sistema"]
    assert linha_closer in sistema and linha_sdr not in sistema
    assert e2e.helena.textos()[-1] == "Carla, vou te explicar como funciona o nosso trabalho."


async def test_troca_pelo_arroba_agente_do_prompt(e2e: Cenario):
    """O roteiro manda passar com o chip "@Agente Closer" (sem destino na config do papel): o motor oferece só esse
    destino à IA, troca quando ela pede e recusa um destino que o roteiro não cita."""
    prompt = ("Você é {{NOME AGENTE}}, do escritório {{NOME ESCRITORIO}}. Pergunte como foi o acidente.\n"
              "Quando o lead contar que ficou com sequela, passe para @Agente Closer.")
    await e2e.pool.execute("update agentesia_agente_etapas set instrucao = $2 where id = $1::uuid", e2e.ids["etapas"]["sdr"], prompt)
    await e2e.pool.execute(
        """update agentesia_agentes set config = jsonb_set(config, '{catalogo,papeis,sdr,destinos}', '[]'::jsonb)
           where id = $1::uuid""", e2e.ids["agente"])

    def etapa(_s, c):
        novas = c.split("MENSAGENS NOVAS")[-1].split("DADOS JÁ INFORMADOS")[0]   # os fatos do portão vêm depois
        if "sequela" in novas:
            return responde("Que bom que me contou.", FRASE_CLOSER, transferir_para="closer")
        if "advogado" in novas:
            return responde("Vou ver isso.", transferir_para="periododegraca")       # o roteiro não manda
        return responde("Oi! Como foi o acidente?")

    e2e.ia.etapa = etapa
    await e2e.chega(e2e.do_lead("oi"))
    await qualificar(e2e)                                   # leva 1: fatos do portão
    assert e2e.pedidos("etapa")[0]["esquema"]["properties"]["transferir_para"]["enum"] == ["", "closer"]
    await e2e.chega(e2e.do_lead("tenho advogado? não sei"))
    assert (await e2e.lead())["etapa"] == "sdr" and await e2e.eventos("destino_recusado")
    await e2e.chega(e2e.do_lead("fiquei com sequela na mão"))
    assert (await e2e.lead())["etapa"] == "closer"
    assert e2e.helena.textos()[-1] == FRASE_CLOSER
    assert "@Agente" not in " ".join(e2e.helena.textos())               # o chip nunca vaza para o lead


async def test_troca_com_a_helena_fora_nao_muda_o_agente(e2e: Cenario):
    """Nada chegou ao lead (Helena fora): ele não ouviu a frase de troca, então continua com o SDR (sem card movido)."""
    e2e.ia.etapa = lambda _s, c: responde("Entendi.", FRASE_CLOSER, transferir_para="closer") if "sequela" in c \
        else responde("Oi! Como foi o acidente?")
    await e2e.chega(e2e.do_lead("oi"))
    await qualificar(e2e)                                   # leva 1: fatos do portão
    e2e.helena.falhar_envio = 6                                         # 2 partes x 3 tentativas
    await e2e.chega(e2e.do_lead("fiquei com sequela no joelho"))
    lead = await e2e.lead()
    assert lead["etapa"] == "sdr"
    assert await e2e.eventos("troca_sem_entrega")
    assert e2e.helena.cards[next(iter(e2e.helena.cards))] == "col-sdr"
    assert not any(n.startswith("🔀 Lead passou para o Closer.") for n in e2e.helena.notas())


async def test_troca_na_primeira_resposta_e_recusada(e2e: Cenario):
    """'Tool fantasma': o SDR não passa o lead adiante na primeira resposta."""
    e2e.ia.etapa = lambda _s, _c: responde("Oi! Já vou te passar.", FRASE_CLOSER, transferir_para="closer")
    await e2e.chega(e2e.do_lead("oi"))
    assert (await e2e.lead())["etapa"] == "sdr"
    assert await e2e.eventos("troca_precoce_recusada")


# ============================================================================ 7) mídia do roteiro
async def test_roteiro_manda_audio_e_video_como_arquivo(e2e: Cenario):
    e2e.ia.etapa = lambda _s, _c: responde("Oi, Carla!")
    await e2e.chega(e2e.do_lead("oi"))
    await e2e.por_na_etapa("closer")
    e2e.ia.etapa = lambda _s, _c: responde("Vou te mandar um áudio explicando como funciona:", AUDIO_ROTEIRO,
                                           "E aqui um vídeo sobre os honorários:", VIDEO_ROTEIRO)
    await e2e.chega(e2e.do_lead("como funciona e quanto custa?"))

    envios = e2e.helena.envios()[1:]
    assert envios == [
        {"text": "Vou te mandar um áudio explicando como funciona:", "channelId": e2e.ids["id_canal_helena"]},
        {"fileUrl": AUDIO_ROTEIRO, "channelId": e2e.ids["id_canal_helena"]},
        {"text": "E aqui um vídeo sobre os honorários:", "channelId": e2e.ids["id_canal_helena"]},
        {"fileUrl": VIDEO_ROTEIRO, "channelId": e2e.ids["id_canal_helena"]},
    ]
    assert not any("http" in t for t in e2e.helena.textos())           # link nunca vai como texto
    ia = [m for m in await e2e.mensagens() if m["autor"] == "ia"][1:]
    assert [(m["tipo"], m["url_midia"], m["texto"]) for m in ia] == [
        ("texto", None, "Vou te mandar um áudio explicando como funciona:"), ("audio", AUDIO_ROTEIRO, None),
        ("texto", None, "E aqui um vídeo sobre os honorários:"), ("video", VIDEO_ROTEIRO, None)]


async def test_link_de_midia_fora_do_roteiro_nao_e_enviado(e2e: Cenario):
    falso = "https://outro-escritorio.exemplo/midia/audio-qualquer.ogg"
    e2e.ia.etapa = lambda _s, _c: responde("Escuta esse áudio:", falso)
    await e2e.chega(e2e.do_lead("oi"))
    assert falso not in e2e.helena.arquivos_enviados() and falso not in " ".join(e2e.helena.textos())
    assert await e2e.eventos("midia_desconhecida")


# ============================================================================ 8) atendente humano
async def test_atendente_assume_ia_pausa_e_botao_religa(e2e: Cenario):
    e2e.ia.etapa = lambda _s, _c: responde("Oi! Como posso ajudar?")
    await e2e.chega(e2e.do_lead("oi"))
    resposta = await e2e.chega(e2e.do_atendente("Oi Carla, aqui é a Paula, vou continuar com você."))
    assert resposta["feito"] == "pausado"
    lead = await e2e.lead()
    assert (lead["estado"], lead["motivo_estado"]) == ("pausado", "humano_assumiu") and lead["pausado_ate"]
    fala = [m for m in await e2e.mensagens() if m["autor"] == "humano"][0]
    assert fala["texto"] == "Oi Carla, aqui é a Paula, vou continuar com você."          # sem a assinatura *Paula:*

    await e2e.chega(e2e.do_lead("ok Paula, obrigada"))
    assert e2e.helena.textos() == ["Oi! Como posso ajudar?"]           # a IA ficou calada
    assert (await e2e.turnos())[-1]["situacao"] == "silencio"

    # Botão "IA" da Helena: religa; nota no chat e etiqueta tirada.
    religar = await e2e.botao_ia("ligar")
    assert religar.status_code == 200 and religar.json()["alterados"] == 1
    await e2e.rodar_fila()
    assert any(n.startswith("🤖 IA religada nesta conversa") for n in e2e.helena.notas())
    assert ("DeleteIfExists", ("🤖 IA Desativada",)) in e2e.helena.etiquetas()
    e2e.ia.etapa = lambda _s, c: responde("Claro, Carla! Me conta como foi o acidente?")
    await e2e.chega(e2e.do_lead("ainda tenho uma dúvida"))
    assert e2e.helena.textos()[-1] == "Claro, Carla! Me conta como foi o acidente?"
    # A IA voltou sabendo o que a atendente falou.
    assert "atendente: Oi Carla, aqui é a Paula" in e2e.pedidos("etapa")[-1]["conteudo"]


async def test_etiqueta_ia_desativada_desliga_e_tirar_religa(e2e: Cenario):
    e2e.ia.etapa = lambda _s, _c: responde("Oi!")
    await e2e.chega(e2e.do_lead("oi"))
    etiqueta = {"eventType": "CONTACT_TAG_UPDATE", "date": datetime.now(timezone.utc).isoformat(),
                "content": {"id": e2e.helena.id_contato, "phonenumber": "+" + e2e.telefone,
                            "tags": [{"name": "📞 SDR"}, {"name": "🤖 IA Desativada"}]}}
    assert (await e2e.chega(etiqueta))["feito"] == "ia"
    assert (await e2e.lead())["motivo_estado"] == "desativada_pela_equipe"
    await e2e.chega(e2e.do_lead("alô?"))
    assert e2e.helena.textos() == ["Oi!"]
    etiqueta["content"]["tags"] = [{"name": "📞 SDR"}]
    await e2e.chega(etiqueta)
    assert (await e2e.lead())["estado"] == "ativo"


async def test_equipe_troca_o_agente_pelo_painel_e_a_ia_segue_com_o_novo_prompt(e2e: Cenario):
    """Troca de agente feita pela equipe (o "@" do lado humano): painel -> etapa nova, card e nota; o próximo turno
    usa o prompt do agente novo."""
    from app.gestao import seguranca

    outros = [p for k, p in e2e.prompts.items() if k != "closer"]
    linha_closer = _linha_propria(e2e.prompts["closer"], outros)
    e2e.ia.etapa = lambda s, _c: responde("Sou do comercial." if linha_closer in s else "Oi! Como foi o acidente?")
    await e2e.chega(e2e.do_lead("oi"))
    email = f"gestor-{uuid.uuid4().hex[:6]}@exemplo.test"
    await e2e.pool.execute(
        """insert into agentesia_usuarios (email, nome, senha_hash, papel, id_escritorio, trocar_senha)
           values ($1, 'Gestora Teste', $2, 'gestor', $3::uuid, false)""",
        email, seguranca.gerar_hash("senha-de-teste-123"), e2e.ids["escritorio"])
    entrar = await e2e.http.post("/api/entrar", json={"email": email, "senha": "senha-de-teste-123"})
    assert entrar.status_code == 200, entrar.text
    lead = await e2e.lead()
    troca = await e2e.http.post(f"/api/conversas/{lead['id']}/ia", json={"acao": "trocar_etapa", "etapa": "closer"})
    assert troca.status_code == 200 and troca.json()["mudou"] is True
    await e2e.rodar_fila()
    assert (await e2e.lead())["etapa"] == "closer"
    assert e2e.helena.cards[next(iter(e2e.helena.cards))] == "col-closer"
    assert any(n.startswith("🔀 Lead passou para o Closer.") for n in e2e.helena.notas())
    await e2e.chega(e2e.do_lead("e agora?"))
    assert linha_closer in e2e.pedidos("etapa")[-1]["sistema"]
    assert e2e.helena.textos()[-1] == "Sou do comercial."


async def test_troca_pela_equipe_faz_o_agente_novo_se_apresentar(e2e: Cenario):
    """Papel de destino com boas-vindas: como na troca feita pela IA, o agente novo se apresenta na primeira resposta
    depois da troca feita pela equipe (antes ele entrava calado, como se já conhecesse o lead)."""
    from app.gestao import seguranca

    await e2e.pool.execute(
        """update agentesia_agentes set config = jsonb_set(config, '{catalogo,papeis,closer,boas_vindas}',
                  '"Oi! Sou a Ana, do time comercial, e agora sigo com você."'::jsonb) where id = $1::uuid""", e2e.ids["agente"])
    e2e.ia.etapa = lambda _s, _c: responde("Oi! Como foi o acidente?")
    await e2e.chega(e2e.do_lead("oi"))
    email = f"gestor-{uuid.uuid4().hex[:6]}@exemplo.test"
    await e2e.pool.execute(
        """insert into agentesia_usuarios (email, nome, senha_hash, papel, id_escritorio, trocar_senha)
           values ($1, 'Gestora Teste', $2, 'gestor', $3::uuid, false)""",
        email, seguranca.gerar_hash("senha-de-teste-123"), e2e.ids["escritorio"])
    assert (await e2e.http.post("/api/entrar", json={"email": email, "senha": "senha-de-teste-123"})).status_code == 200
    lead = await e2e.lead()
    assert (await e2e.http.post(f"/api/conversas/{lead['id']}/ia", json={"acao": "trocar_etapa", "etapa": "closer"})).json()["mudou"]
    await e2e.chega(e2e.do_lead("oi de novo"))
    conteudo = e2e.pedidos("etapa")[-1]["conteudo"]
    assert "Você acabou de assumir esta conversa" in conteudo and "agora sigo com você" in conteudo
    await e2e.chega(e2e.do_lead("certo"))                                # só na primeira resposta do papel
    assert "Mensagem de boas-vindas" not in e2e.pedidos("etapa")[-1]["conteudo"]


# ============================================================================ 9) contrato
async def test_contrato_dados_confirmados_zapsign_link_e_assinatura(e2e: Cenario):
    dados = ("Carla Mendes Ribeiro, CPF " + CPF_FICTICIO + ", Rua das Flores 120, bairro Centro, Belo Horizonte MG, "
             "CEP 30110-012")
    fatos = [("nome_completo", "Carla Mendes Ribeiro", "Carla Mendes Ribeiro"), ("cpf", CPF_FICTICIO, CPF_FICTICIO),
             ("endereco", "Rua das Flores", "Rua das Flores"), ("numero_casa", "120", "120"), ("bairro", "Centro", "Centro"),
             ("cidade", "Belo Horizonte", "Belo Horizonte"), ("uf", "MG", "MG"), ("cep", "30110-012", "30110-012")]
    e2e.ia.extrator = lambda _s, c: extrai(fatos) if "Rua das Flores" in c.split("MENSAGENS NOVAS")[-1] else extrai()
    e2e.ia.etapa = lambda _s, _c: responde("Oi, Carla!")
    await e2e.chega(e2e.do_lead("oi"))
    await e2e.por_na_etapa("contratos")

    e2e.ia.etapa = lambda _s, c: responde("Perfeito, Carla! Vou gerar o seu contrato agora.", ferramenta="zapsign") \
        if "Rua das Flores" in c else responde("Pode me mandar seus dados?")
    await e2e.chega(e2e.do_lead("Confirmo meus dados: " + dados))

    lead = await e2e.lead()
    contrato = await e2e.pool.fetchrow("select * from agentesia_contratos where id_lead = $1", lead["id"])
    assert contrato and contrato["situacao"] == "gerado" and contrato["versao"] == 1
    criado = e2e.helena.zapsign_criados[0]
    assert criado["template_id"] == "modelo-aa" and criado["signer_name"] == "Carla Mendes Ribeiro"
    assert criado["signer_phone_number"] == e2e.telefone[2:]
    link = f"https://app.zapsign.com.br/verificar/{e2e.helena.prefixo}-1"
    assert any(link in t for t in e2e.helena.textos())                  # o link chegou ao lead
    assert lead["etapa"] == "assinatura"
    assert e2e.helena.cards[next(iter(e2e.helena.cards))] == "col-assinatura"

    # Aviso de assinatura da ZapSign (repetido de propósito): relê o documento, marca assinado uma vez só.
    e2e.helena.zapsign_assinado = True
    aviso = {"event_type": "doc_signed", "token": contrato["id_documento_externo"],
             "signer_who_signed": {"token": f"signer-{e2e.helena.prefixo}-1"}}
    assert (await e2e.zapsign(aviso)).json()["feito"] == "processado"
    assert (await e2e.zapsign(aviso)).json()["feito"] == "repetido"
    await e2e.rodar_fila()
    contrato = await e2e.pool.fetchrow("select * from agentesia_contratos where id_lead = $1", lead["id"])
    assert contrato["situacao"] == "assinado"
    lead = await e2e.lead()
    assert (lead["etapa"], lead["estado"], lead["motivo_estado"]) == ("contrato_assinado", "encerrado", "contrato_assinado")
    assert sum(t.startswith("✅ Assinatura confirmada!") for t in e2e.helena.textos()) == 1
    assert e2e.helena.cards[next(iter(e2e.helena.cards))] == "col-assinado"
    assert any(n.startswith("📄 Contrato Assinado!") for n in e2e.helena.notas())
    assert await e2e.pool.fetchval(
        "select count(*) from agentesia_acoes where id_lead = $1 and tipo = 'lembrar_assinatura' and situacao = 'pendente'",
        lead["id"]) == 0

    # Lead escreve depois de assinar: a IA não recomeça o funil (etapa terminal) e não fala por cima da equipe.
    antes = len(e2e.helena.textos())
    await e2e.chega(e2e.do_lead("obrigada!"))
    assert len(e2e.helena.textos()) == antes
    assert (await e2e.turnos())[-1]["situacao"] == "silencio"
    assert (await e2e.lead())["etapa"] == "contrato_assinado"


# ============================================================================ 10) falhas
async def test_falha_da_openai_nao_duplica_e_avisa_a_equipe(e2e: Cenario):
    e2e.atendimento.esperas_nova_tentativa_ia = (0.05,)                 # 1 nova tentativa logo depois (produção: 60 s)
    e2e.ia.falhar["extrator"] = ErroModelo("provedor_fora_do_ar", "HTTP 503 (falso)")
    corpo = e2e.do_lead("oi, preciso de ajuda")
    await e2e.chega(corpo)
    assert (await e2e.chega(corpo))["motivo"] == "repetido"
    assert e2e.helena.textos() == []                                   # nada saiu para o lead
    turnos = await e2e.turnos()
    assert [t["situacao"] for t in turnos] == ["erro", "erro"]          # tentou de novo uma vez, sem laço
    assert turnos[0]["motivo"].endswith(":nova_tentativa")
    eventos = await e2e.eventos("ia_nao_respondeu")
    assert len(eventos) == 1 and eventos[0]["gravidade"] in ("erro", "critico")
    assert sum(n.startswith("⚠️ A IA não conseguiu responder") for n in e2e.helena.notas()) == 1
    assert (await e2e.lead())["responder_apos"] is None                 # a mensagem não fica presa na fila

    # A IA voltou: a mensagem seguinte é respondida uma vez.
    e2e.ia.falhar.clear()
    e2e.ia.etapa = lambda _s, _c: responde("Desculpe a demora! Como posso ajudar?")
    await e2e.chega(e2e.do_lead("alguém aí?"))
    assert e2e.helena.textos() == ["Desculpe a demora! Como posso ajudar?"]


async def test_helena_fora_tenta_de_novo_e_falha_vira_evento_e_nota(e2e: Cenario):
    # 1 erro 500 e depois aceita: a mesma parte sai uma vez só (nova tentativa do cliente).
    e2e.helena.falhar_envio = 1
    e2e.ia.etapa = lambda _s, _c: responde("Oi, Carla!")
    await e2e.chega(e2e.do_lead("oi"))
    assert e2e.helena.textos() == ["Oi, Carla!"]
    tentativas = [c for c in e2e.helena.chamadas if c["caminho"].endswith("/message")]
    assert len(tentativas) == 2 and tentativas[0].get("falhou")

    # Helena fora (3 tentativas com 500): mensagem 'falhou', evento envio_falhou e nota para a equipe.
    e2e.helena.falhar_envio = 3
    e2e.ia.etapa = lambda _s, _c: responde("Como foi o acidente?")
    await e2e.chega(e2e.do_lead("tudo bem?"))
    falhou = [m for m in await e2e.mensagens() if m["autor"] == "ia"][-1]
    assert (falhou["situacao_envio"], falhou["erro"]) == ("falhou", "HTTP 500")
    assert falhou["texto_extraido"].startswith("[NÃO ENTREGUE ao lead]")
    assert await e2e.eventos("envio_falhou")
    assert any(n.startswith("📭 Uma mensagem da IA não chegou ao lead") for n in e2e.helena.notas())
    # A próxima resposta da IA sabe que o lead não viu a parte que falhou.
    e2e.ia.etapa = lambda _s, _c: responde("Desculpe, minha mensagem anterior falhou. Como foi o acidente?")
    await e2e.chega(e2e.do_lead("??"))
    assert "[NÃO ENTREGUE ao lead] Como foi o acidente?" in e2e.pedidos("etapa")[-1]["conteudo"]


async def test_conferencia_de_entrega_pega_failed_um_minuto_depois(e2e: Cenario):
    """O envio é assíncrono: a Helena aceita (QUEUED) e só depois diz FAILED. A fila confere e avisa a equipe."""
    e2e.ia.etapa = lambda _s, _c: responde("Oi!", "Como foi o acidente?")
    await e2e.chega(e2e.do_lead("oi"))
    e2e.helena.status_mensagem = "FAILED"
    lead = await e2e.lead()
    assert await e2e.pool.fetchval(
        "update agentesia_acoes set proxima_em = now() where id_lead = $1 and tipo = 'conferir_entrega' returning 1", lead["id"])
    await e2e.rodar_fila()
    assert [m["situacao_envio"] for m in await e2e.mensagens() if m["autor"] == "ia"] == ["falhou", "falhou"]
    assert await e2e.eventos("envio_falhou")
    assert sum(n.startswith("📭 Uma mensagem da IA não chegou ao lead") for n in e2e.helena.notas()) == 1


async def test_status_failed_da_helena_marca_a_mensagem_e_avisa(e2e: Cenario):
    e2e.ia.etapa = lambda _s, _c: responde("Oi!")
    await e2e.chega(e2e.do_lead("oi"))
    id_msg = [m for m in await e2e.mensagens() if m["autor"] == "ia"][0]["id_externo"]
    status = {"eventType": "MESSAGE_UPDATED", "date": datetime.now(timezone.utc).isoformat(),
              "content": {"id": id_msg, "companyId": e2e.ids["conta"], "sessionId": e2e.sessao, "status": "FAILED",
                          "failureReason": "mídia indisponível", "direction": "TO_HUB", "origin": "API"}}
    assert (await e2e.chega(status))["motivo"] == "envio_falhou"
    assert (await e2e.chega(status))["motivo"] == "status_ja_registrado"
    assert [m for m in await e2e.mensagens() if m["autor"] == "ia"][0]["situacao_envio"] == "falhou"
    assert sum(n.startswith("📭 Uma mensagem da IA não chegou ao lead") for n in e2e.helena.notas()) == 1


# ============================================================================ servidor de verdade (ciclo de vida)
async def test_servidor_sobe_com_o_banco_recebe_webhook_e_a_fila_roda_sozinha(banco_local, monkeypatch):
    """O mesmo `_ciclo` do uvicorn: conecta no banco (conferindo as migrações), liga atendimento, executor, follow-up,
    retomada e índice; um webhook vira resposta na Helena e o card sai pela fila sem ninguém chamar o executor."""
    from app import config as configuracao
    from app.canal.webhook import segredo_do_escritorio
    from app.main import app

    helena, ia = HelenaFalsa(), IAFalsa()
    original = httpx.AsyncClient

    class ClienteSemRede(original):                       # todo cliente HTTP do servidor cai na Helena falsa
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs.setdefault("transport", httpx.MockTransport(helena))
            super().__init__(*args, **kwargs)

    http_app = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://lawchat.test")
    monkeypatch.setattr(httpx, "AsyncClient", ClienteSemRede)
    monkeypatch.setattr(configuracao, "_carregar_env_local", lambda *_a, **_k: None)    # nunca lê o .env real
    for chave in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "AGENTESIA_HELENA_TOKEN_LAWCHAT", "AGENTESIA_MODO_LAB"):
        monkeypatch.delenv(chave, raising=False)
    for chave, valor in {"AGENTESIA_BANCO_URL": banco_local, "AGENTESIA_HELENA_URL": URL_HELENA, "AGENTESIA_MODELO_FALSO": "1",
                         "AGENTESIA_BANCO_CONEXOES": "1", "AGENTESIA_ESPERA_MINIMA": "0", "AGENTESIA_ESPERA_MAXIMA": "0",
                         "AGENTESIA_ESPERA_PADRAO": "0", "AGENTESIA_WEBHOOK_SEGREDO": "segredo-mestre-do-teste-e2e",
                         "AGENTESIA_DESLIGAR_TETO_S": "5"}.items():
        monkeypatch.setenv(chave, valor)
    for nome in ("atendimento", "gestao", "lab", "repo_lab", "assinador", "laboratorios", "tarefas", "visao", "cfg",
                 "indexar_agora"):
        monkeypatch.setattr(app.state, nome, getattr(app.state, nome, None), raising=False)

    async with app.router.lifespan_context(app):
        pool = app.state.atendimento.repo._pool
        await pool.execute("update agentesia_acoes set situacao = 'cancelada' where situacao in ('pendente', 'executando')")
        ids = await _cadastrar(pool, _agente_sousa_costa())
        app.state.atendimento.modelo = ia.modelo()
        ia.etapa = lambda _s, _c: responde("Oi! Aqui é a Ana. Como posso te ajudar?")
        saude = await http_app.get("/saude")
        assert saude.status_code == 200 and saude.json()["banco"] is True and all(saude.json()["tarefas"].values())

        cenario = Cenario(app.state.atendimento.repo, app.state.atendimento, None, helena, ia, VisaoFalsa(), http_app, ids,
                          _agente_sousa_costa())
        resposta = await cenario.postar(cenario.do_lead("oi, boa noite"))
        assert resposta.status_code == 200 and resposta.json()["feito"] == "agendado"
        await cenario.esperar()
        assert helena.textos() == ["Oi! Aqui é a Ana. Como posso te ajudar?"]
        limite = time.monotonic() + 20                    # o executor roda sozinho (a cada 5 s quando a fila está vazia)
        while not helena.cards and time.monotonic() < limite:
            await asyncio.sleep(0.2)
        assert list(helena.cards.values()) == ["col-sdr"]
        esc = ids["escritorio"]
        teste = await http_app.post(f"/webhook/helena/{esc}?segredo={segredo_do_escritorio(esc)}&teste=1", json={})
        assert teste.json() == {"ok": True, "feito": "teste"}
    await http_app.aclose()


def test_cada_mensagem_da_ia_e_um_balao():
    """Regressão: duas mensagens da IA viravam um balão só ("Oi!\\nComo foi o acidente?")."""
    from app.cerebro import catalogo

    assert catalogo.separar_midias(["Oi, Carla!", "Como foi o acidente?"]) == [
        {"tipo": "texto", "texto": "Oi, Carla!"}, {"tipo": "texto", "texto": "Como foi o acidente?"}]
    # Linhas da mesma mensagem continuam juntas; o texto em volta do link de mídia vira balão próprio.
    partes = catalogo.separar_midias(["Escuta:\n" + AUDIO_ROTEIRO + "\ndepois me conta", "Combinado?"])
    assert [(p["tipo"], p.get("texto") or p.get("url")) for p in partes] == [
        ("texto", "Escuta:"), ("midia", AUDIO_ROTEIRO), ("texto", "depois me conta"), ("texto", "Combinado?")]


# ============================================================================ entrada protegida
async def test_webhook_sem_segredo_ou_de_outra_conta_e_recusado(e2e: Cenario):
    esc = e2e.ids["escritorio"]
    assert (await e2e.http.post(f"/webhook/helena/{esc}?segredo=errado", json=e2e.do_lead("oi"))).status_code == 401
    outra = e2e.do_lead("oi")
    outra["content"]["companyId"] = str(uuid.uuid4())
    assert (await e2e.chega(outra))["motivo"] == "conta_de_outro_escritorio"
    assert e2e.helena.chamadas == [] and await e2e.lead() is None
