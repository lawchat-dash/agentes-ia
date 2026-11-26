"""Servidor web: recebe o webhook da Helena, serve a API e o painel de gestão.

Rodar:  .venv/Scripts/python -m uvicorn app.main:app --port 8000
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import config as configuracao
from app.banco.memoria import RepositorioMemoria
from app.banco.tipos import Agente, Canal, Escritorio, Etapa
from app.canal.helena import ClienteHelena
from app.cerebro import agente as agente_ia
from app.cerebro import auxilio_acidente as produto
from app.modelo import Modelo, ModeloFalso, ModeloPorNome
from app.gestao.laboratorio import Laboratorios
from app.gestao.rotas import api as api_gestao
from app.gestao.rotas import entrada as entrada_helena
from app.gestao.seguranca import Assinador
from app.pipeline import Atendimento

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("agentesia")
from app.canal.webhook import proteger_logs_de_acesso  # noqa: E402
proteger_logs_de_acesso()                          # ?segredo= nunca vai para o log de acesso

LAB_ESCRITORIO, LAB_CANAL = "lab-escritorio", "lab-canal"


def _modelo(cfg: configuracao.Configuracao) -> Modelo:
    if cfg.modelo_falso:
        # Sem chamar a IA: serve só para ver a página funcionando.
        return ModeloFalso({
            "extrator": lambda _s, _c: {"fatos": [], "sinais": [], "intencoes": {n: False for n in produto.INTENCOES}},
            "etapa": lambda _s, _c: {"mensagens": [{"tipo": "texto", "chave": "",
                                                    "texto": "(modelo de mentira) Me conta o que aconteceu?"}]},
            "resumo_conversa": lambda _s, _c: {"resumo": "- Caso: (modelo de mentira) resumo do começo da conversa."},
        })
    return ModeloPorNome()


def _montar_laboratorio(repo: RepositorioMemoria) -> None:
    """Escritório e agente fictícios, com as instruções padrão de cada etapa."""
    repo.cadastrar(
        Escritorio(id=LAB_ESCRITORIO, nome="Escritório Modelo", config={}),
        Canal(id=LAB_CANAL, id_escritorio=LAB_ESCRITORIO, numero_normalizado="5500000000000"),
        Agente(
            id="lab-agente", id_escritorio=LAB_ESCRITORIO, id_canal=LAB_CANAL, nome="Júlia",
            situacao="ativo", modo="laboratorio",
            config={"honorarios": "30% do valor recebido, pagos só ao final e só se der certo. Nenhum valor adiantado."},
            etapas=[Etapa(id=f"lab-{codigo}", codigo=codigo, principal=(codigo == "sdr")) for codigo in produto.ETAPAS],
        ),
    )


@asynccontextmanager
async def _ciclo(app: FastAPI):
    cfg = configuracao.carregar()
    modelo = _modelo(cfg)

    # Laboratório: sempre em memória, nunca envia nada.
    repo_lab = RepositorioMemoria()
    _montar_laboratorio(repo_lab)
    app.state.lab = Atendimento(repo_lab, modelo, cfg, helena=None, digitar=False)
    app.state.repo_lab = repo_lab

    # Painel de gestão: sessão assinada e laboratório por agente.
    app.state.assinador = Assinador()
    if app.state.assinador.provisorio:
        log.warning("sem AGENTESIA_SEGREDO_SESSAO: as sessões do painel caem quando o servidor reinicia")
    app.state.laboratorios = Laboratorios(modelo, cfg)

    # Atendimento de verdade e painel: só ligam se houver banco configurado.
    app.state.atendimento = None
    app.state.gestao = None
    app.state.tarefas = {}
    app.state.visao = False
    repo = None
    if cfg.banco_url:
        from app.banco.postgres import RepositorioPostgres
        from app.gestao.repositorio import RepositorioGestao

        import httpx

        # conferir=True: sem as migrações essenciais o servidor não sobe (antes subia e perdia as mensagens).
        repo = await RepositorioPostgres.conectar(cfg.banco_url, int(os.environ.get("AGENTESIA_BANCO_CONEXOES", "10")),
                                                  conferir=True)
        if not repo._midia_pendente:
            log.warning("banco sem a migração 005 (midia_pendente_desde): a leitura de mídia não é vista por outro "
                        "servidor nem refeita depois de um reinício")
        http = httpx.AsyncClient(timeout=20)       # um cliente só para o Executor e o follow-up (fechado no fim)
        visao = None
        if not cfg.modelo_falso and os.environ.get("OPENAI_API_KEY"):
            from app.midia.openai_visao import VisaoOpenAI
            visao = VisaoOpenAI()                  # imagem e áudio do lead viram texto
        elif not cfg.modelo_falso:
            log.warning("visão desligada (sem OPENAI_API_KEY): imagem e áudio sem transcrição da Helena não serão lidos")
        app.state.visao = visao is not None
        from app import central_avisos
        if central_avisos.configurada() is None:
            log.warning("central de avisos da LawChat desligada (AGENTESIA_HELENA_TOKEN_LAWCHAT / "
                        "AGENTESIA_ALERTA_LAWCHAT_DE / AGENTESIA_ALERTA_LAWCHAT_PARA): erros graves não viram WhatsApp")
        from app import vetores
        vetorizador = vetores.VetorizadorFalso() if cfg.modelo_falso else vetores.VetorizadorOpenAI()
        app.state.atendimento = Atendimento(repo, modelo, cfg, helena=ClienteHelena(cfg.helena_url), visao=visao,
                                            vetorizador=vetorizador)
        from app.midia.link import ConferirLink
        app.state.atendimento.conferir_midia = ConferirLink()    # link de mídia quebrado não vai ao lead
        app.state.gestao = RepositorioGestao(repo._pool)
        from app.acoes import Executor

        executor = Executor(repo._pool, cfg.helena_url, modelo=modelo, http=http)
        tarefa_executor = asyncio.create_task(executor.rodar())
        from app.followup.servico import Disparador
        disparador = Disparador(repo._pool, modelo, cfg.helena_url,
                                modelo_padrao=os.environ.get("AGENTESIA_MODELO_FOLLOWUP", "gpt-4.1-mini"), http=http)
        tarefa_followup = asyncio.create_task(disparador.rodar())

        async def retomar_esperas() -> None:
            # Respostas que ficaram agendadas no banco (reinício ou outro servidor que caiu) voltam para a fila.
            while True:
                try:
                    await app.state.atendimento.retomar_pendentes()
                except Exception:
                    log.exception("falha ao retomar respostas pendentes")
                await asyncio.sleep(60)

        tarefa_esperas = asyncio.create_task(retomar_esperas())

        async def central_de_avisos() -> None:
            # Erros graves da LawChat/provedor viram WhatsApp para a equipe (1 por problema a cada 30 min).
            from app import central_avisos
            desde = central_avisos.inicio_padrao()
            while True:
                try:
                    _, desde = await central_avisos.varrer(repo._pool, desde)
                except Exception:
                    log.exception("falha na central de avisos")
                await asyncio.sleep(60)

        tarefa_central = asyncio.create_task(central_de_avisos())

        app.state.indexar_agora = asyncio.Event()

        async def indexar_conhecimento() -> None:
            # Documentos novos da base de conhecimento viram trechos com vetor (na hora do envio ou a cada 30 s).
            from app.conhecimento_indice import indexar_pendentes
            while True:
                try:
                    await indexar_pendentes(repo._pool, vetorizador)
                except Exception:
                    log.exception("falha ao indexar a base de conhecimento")
                try:
                    await asyncio.wait_for(app.state.indexar_agora.wait(), 30)
                except asyncio.TimeoutError:
                    pass
                app.state.indexar_agora.clear()

        tarefa_indice = asyncio.create_task(indexar_conhecimento())
        # Cobrança em R$: débito em lote do consumo, bônus do plano do mês e avisos de saldo (app/cobranca).
        from app.cobranca import Cobrador
        cobrador = Cobrador(repo._pool, float(os.environ.get("AGENTESIA_COBRANCA_INTERVALO_S", "60")))
        tarefa_cobranca = asyncio.create_task(cobrador.rodar())
        app.state.tarefas = {"executor": tarefa_executor, "followup": tarefa_followup, "retomar": tarefa_esperas,
                             "central": tarefa_central, "indice": tarefa_indice, "cobranca": tarefa_cobranca}
        log.info("atendimento, painel e executor de ações ligados ao banco")
    else:
        log.info("sem AGENTESIA_BANCO_URL: só o Laboratório está disponível")
    app.state.cfg = cfg
    yield
    if repo:
        executor.parar()
        disparador.parar()
        tarefa_esperas.cancel()
        tarefa_central.cancel()
        tarefa_indice.cancel()
        cobrador.parar()
        await asyncio.gather(tarefa_executor, tarefa_followup, tarefa_esperas, tarefa_central, tarefa_indice, tarefa_cobranca,
                             return_exceptions=True)
        # Turnos em andamento terminam (até 30 s) antes de fechar o banco; o que for cortado vira 'turno_interrompido'.
        try:
            await app.state.atendimento.encerrar(teto_s=float(os.environ.get("AGENTESIA_DESLIGAR_TETO_S", "30")))
        except Exception:
            log.exception("falha ao encerrar os turnos em andamento")
        for cliente in (http, getattr(app.state.atendimento.helena, "_http", None),
                        getattr(app.state.atendimento, "_http_midia", None)):
            if cliente is not None:
                try:
                    await cliente.aclose()
                except Exception:
                    log.exception("falha ao fechar um cliente HTTP")
        await repo.fechar()


app = FastAPI(title="LawChat IA", lifespan=_ciclo)
# Compacta o painel e a API do painel acima de 1 KB (o JS tem ~2,5 MB sem compressão; o JSON das listas encolhe ~80%).
# Só /assets e /api: a mídia (/midia, áudio com Range) e os webhooks seguem como estão.
from fastapi.middleware.gzip import GZipMiddleware  # noqa: E402


class _GzipDoPainel:
    def __init__(self, aplicativo: Any) -> None:
        self._direto = aplicativo
        self._gzip = GZipMiddleware(aplicativo, minimum_size=1024, compresslevel=6)

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        caminho = scope.get("path", "") if scope["type"] == "http" else ""
        alvo = self._gzip if caminho.startswith(("/assets/", "/api/")) else self._direto
        await alvo(scope, receive, send)


app.add_middleware(_GzipDoPainel)
from app.gestao.cache_curto import LimparAoEscrever  # noqa: E402
app.add_middleware(LimparAoEscrever)                  # escrita em /api/ apaga os caches curtos (app/gestao/cache_curto.py)
app.include_router(api_gestao)
from app.gestao.produtos import api as api_produtos, pasta_midia  # noqa: E402
app.include_router(api_produtos)
from app.gestao.rotas_followup import api as api_followup  # noqa: E402
app.include_router(api_followup)                      # follow-up padrão: ativação, "Ligar com o padrão" e admin
from app.gestao.metricas import api as api_metricas  # noqa: E402
app.include_router(api_metricas)                      # números da tela Início
from app.gestao.rotas_conta import api as api_conta  # noqa: E402
app.include_router(api_conta)                         # onboarding e "Sincronizar conta" da Helena
from app.cobranca.rotas import api as api_cobranca  # noqa: E402
app.include_router(api_cobranca)                      # carteira, recargas, planos, cotação e markup (cobrança em R$)
from app.gestao.rotas_contrato import api as api_contrato  # noqa: E402
app.include_router(api_contrato)                      # contratos do lead e prompt do resumo do contrato assinado
from app.gestao.rotas_rascunho import api as api_rascunho; app.include_router(api_rascunho)  # noqa: E402,E702  testar o rascunho e versões
from app.gestao.rotas_roteiros import api as api_roteiros; app.include_router(api_roteiros)  # noqa: E402,E702  Ferramentas > Roteiros (áudios)
from app.gestao.rotas_filtro import api as api_filtro; app.include_router(api_filtro)  # noqa: E402,E702  filtro de número por agente (teste)
if os.environ.get("AGENTESIA_PAINEL_CRM_LIGADO", "").strip() == "1":
    # Painel padrão do CRM pela API interna da Helena (impersonate): desligado por padrão. Se um dia o recebimento de
    # webhooks virar um app separado, este router NÃO entra nele.
    from app.gestao.rotas_painel_crm import api as api_painel_crm  # noqa: E402
    app.include_router(api_painel_crm)
from app import armazenamento as _armazenamento  # noqa: E402
# Modo supabase: a mídia mora no bucket (URL pública do Storage) e o /midia local não existe. Valor inválido derruba a
# subida com a mensagem do erro.
MIDIA_LOCAL = _armazenamento.modo() == "local"
if MIDIA_LOCAL:
    pasta_midia().mkdir(parents=True, exist_ok=True)


def registrar_tipos_de_midia() -> None:
    """O StaticFiles usa mimetypes, que depende do sistema (no Windows .webp sai None e vira text/plain; .opus/.oga
    variam): o tipo certo de cada formato da biblioteca, para a Helena e o WhatsApp entregarem como mídia."""
    import mimetypes

    for mime, extensao in (("audio/ogg", ".ogg"), ("audio/ogg", ".oga"), ("audio/ogg", ".opus"), ("audio/mpeg", ".mp3"),
                           ("audio/mp4", ".m4a"), ("video/mp4", ".mp4"), ("image/jpeg", ".jpg"), ("image/jpeg", ".jpeg"),
                           ("image/png", ".png"), ("image/webp", ".webp")):
        mimetypes.add_type(mime, extensao)


registrar_tipos_de_midia()
if MIDIA_LOCAL:
    app.mount("/midia", StaticFiles(directory=pasta_midia()), name="midia")   # mídia dos prompts (links públicos)
app.include_router(entrada_helena)


@app.get("/saude")
async def saude() -> Any:
    """Saúde de verdade: banco respondendo, tarefas de fundo vivas e o atraso das filas. 503 quando o banco não responde
    ou uma tarefa de fundo morreu (o monitor do provedor reinicia o servidor)."""
    from fastapi.responses import JSONResponse

    atendimento = app.state.atendimento
    corpo: dict[str, Any] = {"ok": True, "atendimento": atendimento is not None, "modelo": app.state.cfg.modelo_padrao,
                             "visao": bool(getattr(app.state, "visao", False))}
    if atendimento is None:
        return corpo
    from app import central_avisos
    tarefas = getattr(app.state, "tarefas", {}) or {}
    corpo["tarefas"] = {nome: not t.done() for nome, t in tarefas.items()}
    corpo["central"] = central_avisos.configurada() is not None
    pool = atendimento.repo._pool
    try:
        corpo["banco"] = await asyncio.wait_for(pool.fetchval("select 1"), 2) == 1
        corpo["fila_acoes_atraso_s"] = int(await asyncio.wait_for(pool.fetchval(
            """select coalesce(extract(epoch from now() - min(proxima_em)), 0) from agentesia_acoes
               where situacao = 'pendente' and proxima_em <= now()"""), 2) or 0)
        corpo["leads_sem_resposta"] = int(await asyncio.wait_for(pool.fetchval(
            """select count(*) from agentesia_leads where responder_apos < now() - interval '5 minutes'
               and (processando_ate is null or processando_ate < now())"""), 2) or 0)
    except Exception as erro:                                 # banco fora ou pendurado
        corpo.update(ok=False, banco=False, erro=type(erro).__name__)
    if not all(corpo["tarefas"].values()):
        corpo["ok"] = False
    return corpo if corpo["ok"] else JSONResponse(corpo, status_code=503)


# ----------------------------------------------------------------------------- webhook
@app.post("/webhook/helena")
async def webhook_helena(pedido: Request) -> dict[str, Any]:
    """Entrada global (legada). Desligada por padrão: use a URL de cada escritório (/webhook/helena/{id}).

    Só atende com AGENTESIA_WEBHOOK_GLOBAL=1, e com um segredo DERIVADO (canal.webhook.segredo_global), nunca o
    AGENTESIA_WEBHOOK_SEGREDO: com o mestre na URL qualquer um calcularia o segredo de todos os escritórios."""
    from app.canal.webhook import rota_global_ligada, segredo_global
    if not rota_global_ligada():
        raise HTTPException(status_code=404, detail="use a URL de webhook do escritório")
    esperado = segredo_global() or ""
    recebido = pedido.query_params.get("segredo") or pedido.headers.get("x-agentesia-segredo", "")
    if not esperado or not hmac.compare_digest(esperado.encode(), recebido.encode()):
        raise HTTPException(status_code=401, detail="segredo do webhook ausente ou errado")
    if app.state.atendimento is None:
        raise HTTPException(status_code=503, detail="banco não configurado")
    corpo = await pedido.json()
    if not isinstance(corpo, dict):
        raise HTTPException(status_code=400, detail="corpo inválido")
    resultado = await app.state.atendimento.receber(corpo)
    if resultado.get("feito") == "erro":
        raise HTTPException(status_code=503, detail=resultado.get("motivo") or "erro")
    return {"ok": True, **resultado}


@app.post("/webhook/helena/{id_escritorio}")
async def webhook_helena_do_escritorio(id_escritorio: str, pedido: Request) -> dict[str, Any]:
    """Webhook de um escritório só. O segredo é derivado do id: vazar a URL de um escritório não abre os outros,
    e mensagem de outra conta que chegue aqui é descartada."""
    from app.canal.webhook import segredo_do_escritorio
    esperado = segredo_do_escritorio(id_escritorio)
    recebido = pedido.query_params.get("segredo") or pedido.headers.get("x-agentesia-segredo", "")
    if not esperado or not hmac.compare_digest(esperado.encode(), recebido.encode()):
        raise HTTPException(status_code=401, detail="segredo do webhook ausente ou errado")
    if pedido.query_params.get("teste") == "1":
        return {"ok": True, "feito": "teste"}               # usado na ativação para provar que a URL chega aqui
    if app.state.atendimento is None:
        raise HTTPException(status_code=503, detail="banco não configurado")
    corpo = await pedido.json()
    if not isinstance(corpo, dict):
        raise HTTPException(status_code=400, detail="corpo inválido")
    from app import ia_controle
    etiqueta = (await ia_controle.receber_evento_de_etiqueta(app.state.gestao.pool, id_escritorio, corpo)
                if app.state.gestao is not None else None)
    if etiqueta is not None:                                    # etiqueta "IA Desativada" no contato
        return {"ok": True, **etiqueta}
    from app import troca_etapa
    card = (await troca_etapa.receber_evento_de_card(app.state.gestao.pool, id_escritorio, corpo)
            if app.state.gestao is not None else None)
    if card is not None:                                        # a equipe moveu o card de coluna no CRM da Helena
        return {"ok": True, **card}
    resultado = await app.state.atendimento.receber(corpo, id_escritorio_esperado=id_escritorio)
    if resultado.get("feito") == "erro":
        # A fala do atendente não foi gravada e a IA não foi pausada (o recebido já foi apagado): 503 para a Helena
        # reenviar, se ela reenviar. Com 200 o reenvio nunca vinha e a IA seguia ativa por cima do atendente.
        raise HTTPException(status_code=503, detail=resultado.get("motivo") or "erro")
    return {"ok": True, **resultado}


def ler_acao_ia(corpo: dict[str, Any]) -> dict[str, Any]:
    """Corpo do botão "IA" da Helena em qualquer dos dois formatos: o nosso {acao, sessionId, phone, minutes} ou o do
    botão como no n8n {utm: {id_do_atendimento, telefone_do_contato, ...}, minutes} (sem 'acao' = desligar)."""
    utm = corpo.get("utm") if isinstance(corpo.get("utm"), dict) else {}
    acao = str(corpo.get("acao") or ("desligar" if utm else "")).strip().lower()
    try:
        minutos = int(float(corpo.get("minutes") or corpo.get("minutos") or 0))
    except (TypeError, ValueError):
        minutos = 0
    return {"acao": acao,
            "id_sessao": str(corpo.get("sessionId") or utm.get("id_do_atendimento") or "") or None,
            "telefone": str(corpo.get("phone") or utm.get("telefone_do_contato") or "") or None,
            "minutos": max(0, minutos)}


@app.post("/webhook/helena/{id_escritorio}/ia")
async def webhook_ia(id_escritorio: str, pedido: Request) -> dict[str, Any]:
    """Botão ou automação na Helena: desliga ou religa a IA de uma conversa (mesmo segredo do webhook do escritório)."""
    from app import ia_controle
    from app.canal.webhook import segredo_do_escritorio
    esperado = segredo_do_escritorio(id_escritorio)
    recebido = pedido.query_params.get("segredo") or pedido.headers.get("x-agentesia-segredo", "")
    if not esperado or not hmac.compare_digest(esperado.encode(), recebido.encode()):
        raise HTTPException(status_code=401, detail="segredo do webhook ausente ou errado")
    try:
        corpo = await pedido.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="corpo inválido") from None
    if not isinstance(corpo, dict):
        raise HTTPException(status_code=400, detail="corpo inválido")
    dados = ler_acao_ia(corpo)
    if dados["acao"] not in ("desligar", "ligar"):
        raise HTTPException(status_code=400, detail="acao deve ser desligar ou ligar")
    if app.state.gestao is None:
        raise HTTPException(status_code=503, detail="banco não configurado")
    return {"ok": True, **await ia_controle.mudar_ia(app.state.gestao.pool, id_escritorio, ligar=dados["acao"] == "ligar",
                                                     origem="botao", id_sessao=dados["id_sessao"], telefone=dados["telefone"],
                                                     minutos=dados["minutos"])}


@app.post("/webhook/zapsign/{id_escritorio}")
async def webhook_zapsign(id_escritorio: str, pedido: Request) -> dict[str, Any]:
    """Aviso de assinatura da ZapSign. Responde na hora; a releitura do documento roda na fila."""
    from app.canal.webhook import segredo_do_escritorio
    from app.contrato.servico import receber_webhook
    esperado = segredo_do_escritorio(id_escritorio, "zapsign")
    recebido = pedido.query_params.get("segredo") or pedido.headers.get("x-agentesia-segredo", "")
    if not esperado or not hmac.compare_digest(esperado.encode(), recebido.encode()):
        raise HTTPException(status_code=401, detail="segredo do webhook ausente ou errado")
    if app.state.gestao is None:
        raise HTTPException(status_code=503, detail="banco não configurado")
    try:
        corpo = await pedido.json()
    except ValueError:                                   # JSON quebrado: 400 (500 faria a ZapSign repetir à toa)
        raise HTTPException(status_code=400, detail="corpo inválido") from None
    if not isinstance(corpo, dict):
        raise HTTPException(status_code=400, detail="corpo inválido")
    return {"ok": True, "feito": await receber_webhook(app.state.gestao.pool, id_escritorio, corpo)}


# ----------------------------------------------------------------------------- laboratório
def _exigir_senha_do_lab(pedido: Request) -> None:
    senha = os.environ.get("AGENTESIA_LAB_SENHA", "")
    if senha and not hmac.compare_digest(senha.encode(), pedido.headers.get("x-lab-senha", "").encode()):
        raise HTTPException(status_code=401, detail="senha do Laboratório ausente ou errada")


class NovaMensagem(BaseModel):
    id_conversa: str
    texto: str


class NovaConfig(BaseModel):
    honorarios: str | None = None
    instrucoes: dict[str, str] | None = None
    modelo: str | None = None
    nome: str | None = None
    escritorio: str | None = None


@app.get("/lab", response_class=HTMLResponse)
async def pagina_do_lab() -> str:
    return (Path(__file__).parent / "web" / "lab.html").read_text(encoding="utf-8")


def _config_do_lab() -> dict[str, Any]:
    repo: RepositorioMemoria = app.state.repo_lab
    agente = repo.agentes[LAB_CANAL]
    return {
        "nome": agente.nome,
        "escritorio": repo.escritorios[LAB_ESCRITORIO].nome,
        "honorarios": agente.config.get("honorarios") or "",
        "modelo": agente.config.get("modelos", {}).get("etapa") or app.state.cfg.modelo_padrao,
        "instrucoes": {e.codigo: e.instrucao or agente_ia.INSTRUCOES.get(e.codigo, "") for e in agente.etapas},
        "modelo_falso": app.state.cfg.modelo_falso,
    }


@app.get("/lab/api/config")
async def ler_config(pedido: Request) -> dict[str, Any]:
    _exigir_senha_do_lab(pedido)
    return _config_do_lab()


@app.post("/lab/api/config")
async def gravar_config(pedido: Request, nova: NovaConfig) -> dict[str, Any]:
    _exigir_senha_do_lab(pedido)
    repo: RepositorioMemoria = app.state.repo_lab
    agente = repo.agentes[LAB_CANAL]
    if nova.honorarios is not None:
        agente.config["honorarios"] = nova.honorarios.strip() or None
    if nova.modelo:
        agente.config["modelos"] = {"extrator": nova.modelo, "etapa": nova.modelo}
    if nova.nome:
        agente.nome = nova.nome.strip()
    if nova.escritorio:
        repo.escritorios[LAB_ESCRITORIO].nome = nova.escritorio.strip()
    for codigo, texto in (nova.instrucoes or {}).items():
        etapa = agente.etapa(codigo)
        if etapa:
            padrao = agente_ia.INSTRUCOES.get(codigo, "")
            etapa.instrucao = None if texto.strip() == padrao.strip() else texto
    return _config_do_lab()


@app.post("/lab/api/conversa")
async def nova_conversa(pedido: Request) -> dict[str, Any]:
    _exigir_senha_do_lab(pedido)
    repo: RepositorioMemoria = app.state.repo_lab
    lead = await repo.achar_ou_criar_lead(
        escritorio=repo.escritorios[LAB_ESCRITORIO], canal=repo.canais[LAB_CANAL], agente=repo.agentes[LAB_CANAL],
        telefone="lab-" + uuid.uuid4().hex[:10], id_sessao=None,
    )
    return {"id_conversa": lead.id, "etapa": "sdr"}


@app.post("/lab/api/mensagem")
async def mensagem_do_lab(pedido: Request, nova: NovaMensagem) -> dict[str, Any]:
    """Roda um turno na hora, sem espera e sem enviar nada, e devolve tudo o que aconteceu por dentro."""
    _exigir_senha_do_lab(pedido)
    repo: RepositorioMemoria = app.state.repo_lab
    lead = await repo.lead(nova.id_conversa)
    if not lead or not nova.texto.strip():
        raise HTTPException(status_code=400, detail="conversa ou texto inválido")
    await repo.gravar_mensagem(
        lead=lead, autor="lead", tipo="texto", texto=nova.texto.strip(), texto_extraido=None, url_midia=None,
        enviada_em=datetime.now(timezone.utc), id_externo=None,
    )
    saida = await app.state.lab.processar(lead.id, modo="laboratorio")
    lead = await repo.lead(lead.id)
    agente = repo.agentes[LAB_CANAL]
    etapa = agente.etapa_por_id(lead.id_etapa) if lead else None
    return {
        "turno": saida.como_dict() if saida else None,
        "etapa": etapa.codigo if etapa else None,
        "estado": lead.estado if lead else None,
        "motivo_estado": lead.motivo_estado if lead else None,
        "fatos": await repo.fatos_vigentes(nova.id_conversa),
    }


# ----------------------------------------------------------------------------- painel (front compilado)
_PAINEL = Path(__file__).resolve().parent.parent / "painel" / "dist"


class _AssetsImutaveis(StaticFiles):
    """Os arquivos de painel/dist/assets têm o hash no nome: o navegador guarda por 1 ano e não pergunta de novo a cada
    tela (o index.html continua no-cache e aponta para os nomes novos depois de publicar)."""

    def file_response(self, *args: Any, **kwargs: Any) -> Any:
        resposta = super().file_response(*args, **kwargs)
        resposta.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resposta


if (_PAINEL / "assets").is_dir():
    app.mount("/assets", _AssetsImutaveis(directory=_PAINEL / "assets"), name="assets")


# HEAD também: `curl -I` (e alguns monitores) recebiam 405 sem o Cache-Control do index.html.
@app.api_route("/{caminho:path}", methods=["GET", "HEAD"], include_in_schema=False)
async def painel(caminho: str) -> Any:
    """Entrega o painel; rotas do painel (/agentes, /erros...) caem no index.html."""
    if caminho.startswith(("api/", "webhook/", "lab")):
        raise HTTPException(404)
    arquivo = (_PAINEL / caminho).resolve()
    if caminho and arquivo.is_file() and _PAINEL in arquivo.parents:
        # Ícones e imagens da raiz do dist (sem hash no nome): 1 hora, para não perguntar de novo a cada tela.
        return FileResponse(arquivo, headers={"Cache-Control": "public, max-age=3600"})
    indice = _PAINEL / "index.html"
    if not indice.is_file():
        raise HTTPException(404, "Painel ainda não compilado (cd painel && npm run build).")
    # no-cache: depois de publicar uma versão nova, o navegador confere o index.html (que aponta para os assets novos)
    # em vez de seguir com a versão velha do painel. Os assets têm hash no nome e continuam em cache.
    return FileResponse(indice, headers={"Cache-Control": "no-cache"})
