"""API do painel de gestão (/api). Cada rota confere quem é o usuário e de qual escritório.

Papéis:
  dono_lawchat   tudo da equipe LawChat e, além disso, cuida da própria equipe (quem entra, papel, desativar)
  admin_lawchat  equipe LawChat: vê e edita todos os escritórios (escolhe qual pelo cabeçalho X-Escritorio)
  gestor         vê e edita só o próprio escritório
  atendente      vê conversas e pausa ou devolve a IA de um lead

Visão do cliente: quem é da LawChat pode mandar X-Visao: gestor|atendente junto com X-Escritorio.
A API passa a responder com as permissões desse papel (o que o cliente vê e pode fazer). O histórico
continua com o nome de quem fez a alteração.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app import automacoes, notificacoes
from app.canal.helena import normalizar_telefone
from app.canal.helena_conta import ErroHelenaApi, HelenaConta, HelenaParceiro
from app.canal.webhook import segredo_do_escritorio, url_do_botao_ia, url_do_escritorio
from app.cerebro import agente as agente_ia
from app.cerebro import auxilio_acidente, sinais
from app.cerebro import produto as produtos
from app.cerebro.produto_livre import Definicao
from app.gestao import ativacao, seguranca
from app.gestao.cache_curto import CacheCurto
from app.gestao.repositorio import RepositorioGestao, _linhas

COOKIE = "agentesia_sessao"
# Modelos oferecidos na escolha do agente (fase de testes: só estes dois).
MODELOS = [
    {"id": "gpt-4.1-mini", "nome": "GPT-4.1 mini", "provedor": "openai", "padrao": True},
    {"id": "gpt-6-luna", "nome": "GPT-6 Luna", "provedor": "openai"},
]
# Aceitos ao salvar: os oferecidos e os que agentes antigos ainda usam (não quebra quem já está em outro modelo).
IDS_MODELOS = {m["id"] for m in MODELOS} | {"gpt-4.1", "claude-opus-5-5", "claude-sonnet-5-5"}
PRODUTOS = [
    {"id": "auxilio_acidente", "nome": "Auxílio-Acidente", "tipo": "pronto",
     "descricao": "Agente pronto da LawChat: qualificação e período de graça com as regras validadas.",
     "etapas": list(auxilio_acidente.ETAPAS)},
    {"id": "proprio", "nome": "Começar do zero", "tipo": "proprio",
     "descricao": "Você define os dados que a IA coleta, as etapas e as regras de passagem."},
]

# Ponto de partida do agente próprio: três etapas simples que o cliente edita.
DEFINICAO_INICIAL: dict[str, Any] = {
    "objetivo": "Entender o caso da pessoa e, se fizer sentido, encaminhar para a equipe do escritório.",
    "contexto": "uma pessoa que procura o escritório de advocacia",
    "campos": [
        {"chave": "assunto", "nome": "Assunto", "tipo": "texto", "etapa": "triagem",
         "descricao": "o que aconteceu, com as palavras da pessoa"},
        {"chave": "ja_tem_advogado", "nome": "Já tem advogado", "tipo": "sim_nao", "etapa": "triagem",
         "descricao": "se já tem advogado cuidando deste caso"},
    ],
    "intencoes": [{"chave": "quer_agendar", "descricao": "pede para marcar uma conversa ou consulta"}],
    "etapas": [
        {"codigo": "triagem", "nome": "Triagem", "tipo": "conversa",
         "instrucao": "ETAPA: triagem.\nObjetivo: entender o caso com calma, uma pergunta por vez."},
        {"codigo": "encaminhamento", "nome": "Encaminhamento", "tipo": "terminal",
         "instrucao": "ETAPA: encaminhamento.\nAgradeça, diga que a equipe vai analisar e retornar por aqui. Não faça pergunta."},
        {"codigo": "fora_do_perfil", "nome": "Fora do perfil", "tipo": "terminal",
         "instrucao": "ETAPA: encerramento.\nExplique com respeito que o escritório não consegue atuar neste caso. Não faça pergunta."},
    ],
    "regras": [
        {"de": "triagem", "quando": {"tipo": "campo", "campo": "ja_tem_advogado", "operador": "igual", "valor": "sim"},
         "ir_para": "fora_do_perfil", "motivo": "já existe um advogado cuidando do caso"},
        {"de": "triagem", "quando": {"tipo": "intencao", "intencao": "quer_agendar"}, "ir_para": "encaminhamento",
         "motivo": "pediu para agendar"},
        {"de": "triagem", "quando": {"tipo": "etapa_completa"}, "ir_para": "encaminhamento", "motivo": "triagem completa"},
    ],
    "nunca": ["prometer resultado ou prazo"],
    "expressoes_proibidas": ["garantido", "com certeza vai ganhar"],
}
# Funções que o agente pode usar. A IA não as aciona sozinha: o código decide quando, pelas regras de cada uma.
FUNCOES = [
    {"id": "crm", "nome": "Etapa do CRM e etiquetas",
     "descricao": "Cria o card do lead, muda a etapa (coluna) do CRM e põe ou tira etiquetas do contato quando uma regra manda.",
     "requer": "crm", "pronta": True},
    {"id": "transferir_humano", "nome": "Troca de departamento",
     "descricao": "Transfere o atendimento para um departamento da LawChat quando uma regra manda (pediu uma pessoa, qualificou, foi para análise...). Cada regra pode escolher o seu departamento.",
     "requer": "helena", "pronta": True},
    {"id": "avisos", "nome": "Avisar a equipe",
     "descricao": "WhatsApp para a equipe quando acontece algo configurado em \"Avisos à equipe\" (qualificou, não sabe ler, contrato assinado...), e as notas das automações.",
     "requer": "helena", "pronta": True},
    {"id": "buscar_cep", "nome": "Completar endereço pelo CEP",
     "descricao": "Na coleta de dados, o endereço é preenchido sozinho a partir do CEP (ViaCEP, OpenCEP, BrasilAPI).", "requer": None, "pronta": True},
    {"id": "contrato_zapsign", "nome": "Gerar contrato na ZapSign",
     "descricao": "Pede os dados do contrato, gera na ZapSign quando o lead confirma, manda o link, lembra e confere a assinatura.",
     "requer": "zapsign", "pronta": True},
]
IDS_FUNCOES = {f["id"] for f in FUNCOES}

NOMES_ETAPAS = {
    "sdr": "Primeiro atendimento", "periodo_graca": "Período de graça", "closer": "Proposta e honorários",
    "coleta_dados": "Dados do contrato", "analise_manual": "Análise da equipe", "desqualificado": "Encerramento",
}

api = APIRouter(prefix="/api")

PAPEIS_LAWCHAT = ("dono_lawchat", "admin_lawchat")
PAPEIS_CLIENTE = ("gestor", "atendente")


# ============================================================================ contexto
class Contexto:
    def __init__(self, usuario: dict[str, Any], id_escritorio: str | None, visao: str | None = None) -> None:
        self.usuario = usuario
        self.id_escritorio = id_escritorio
        self.visao = visao                  # gestor/atendente quando a LawChat olha como o cliente

    @property
    def papel(self) -> str:
        """Papel que vale para permissões: o da visão escolhida, se houver."""
        return self.visao or self.usuario["papel"]

    @property
    def lawchat(self) -> bool:
        return self.usuario["papel"] in PAPEIS_LAWCHAT

    @property
    def admin(self) -> bool:
        return self.papel in PAPEIS_LAWCHAT

    @property
    def dono(self) -> bool:
        return self.papel == "dono_lawchat"

    @property
    def id_usuario(self) -> str:
        return self.usuario["id"]

    def escritorio(self) -> str:
        if not self.id_escritorio:
            raise HTTPException(400, "Escolha um escritório.")
        return self.id_escritorio


def _repo(pedido: Request) -> RepositorioGestao:
    repo = getattr(pedido.app.state, "gestao", None)
    if repo is None:
        raise HTTPException(503, "Banco não configurado (AGENTESIA_BANCO_URL).")
    return repo


async def contexto(pedido: Request) -> Contexto:
    sessao = pedido.app.state.assinador.ler(pedido.cookies.get(COOKIE))
    if not sessao:
        raise HTTPException(401, "Entre de novo.")
    usuario = await _repo(pedido).usuario(sessao.id_usuario)
    if not usuario or not usuario["ativo"]:
        raise HTTPException(401, "Usuário desativado.")
    if usuario["papel"] in PAPEIS_LAWCHAT:
        escolhido = pedido.headers.get("x-escritorio") or None
        if escolhido and not re.fullmatch(r"[0-9a-fA-F-]{36}", escolhido):
            raise HTTPException(400, "Escritório inválido.")
        visao = (pedido.headers.get("x-visao") or "").strip() or None
        if visao and visao not in PAPEIS_CLIENTE:
            raise HTTPException(400, "Visão inválida.")
        return Contexto(usuario, escolhido, visao if escolhido else None)
    return Contexto(usuario, usuario["id_escritorio"])


def exigir(*papeis: str):
    async def _dep(ctx: Contexto = Depends(contexto)) -> Contexto:
        if ctx.papel not in papeis:
            raise HTTPException(403, "Sem permissão para esta ação."
                                + (" Você está na visão do cliente." if ctx.visao else ""))
        return ctx
    return _dep


GESTAO = exigir("dono_lawchat", "admin_lawchat", "gestor")
TODOS = exigir("dono_lawchat", "admin_lawchat", "gestor", "atendente")
ADMIN = exigir("dono_lawchat", "admin_lawchat")
DONO = exigir("dono_lawchat")


def _erro_helena(erro: ErroHelenaApi) -> HTTPException:
    mensagens = {
        "token_recusado": "A LawChat recusou o token. Confira se ele foi copiado inteiro e se ainda vale.",
        "sem_conexao": "Não foi possível falar com a LawChat agora. Tente de novo em instantes.",
        "limite_de_uso": "A LawChat pediu para esperar: muitas chamadas seguidas. Tente em alguns minutos.",
        "nao_encontrado": "A LawChat não encontrou o que foi pedido.",
    }
    return HTTPException(502, mensagens.get(erro.motivo, f"A LawChat respondeu com erro ({erro.detalhe})."))


def _final(token: str) -> str:
    return token.strip()[-4:]


async def _helena_do_escritorio(pedido: Request, repo: RepositorioGestao, id_escritorio: str) -> HelenaConta:
    integracao = await repo.integracao(id_escritorio, "helena")
    token = await repo.ler_segredo((integracao or {}).get("id_segredo_vault"))
    if not token:
        raise HTTPException(409, "Cadastre o token da LawChat em Integrações.")
    return HelenaConta(token, pedido.app.state.cfg.helena_url)


# Listas da Helena que o painel só consulta (etiquetas, equipes, painéis do CRM): guardadas por escritório por
# HELENA_CACHE_S. Antes cada abertura da aba Funções esperava duas chamadas à api.helena.run (1 s ou mais cada,
# até 20 s se a Helena demorasse) e duas idas ao banco pelo token.
HELENA_CACHE_S = 120.0
HELENA_TIMEOUT_PAINEL_S = 8.0
_HELENA_CACHE: dict[tuple[str, str], tuple[float, Any]] = {}


async def _consulta_helena(pedido: Request, id_escritorio: str, chave: str, ler: Any, recarregar: bool = False) -> Any:
    """`ler(helena)` com cache curto e tempo-limite de painel. recarregar=True ignora a cópia guardada."""
    import httpx
    agora = time.monotonic()
    guardado = _HELENA_CACHE.get((id_escritorio, chave))
    if guardado and not recarregar and agora - guardado[0] < HELENA_CACHE_S:
        return guardado[1]
    repo = _repo(pedido)
    integracao = await repo.integracao(id_escritorio, "helena")
    token = await repo.ler_segredo((integracao or {}).get("id_segredo_vault"))
    if not token:
        raise HTTPException(409, "Cadastre o token da LawChat em Integrações.")
    async with httpx.AsyncClient(timeout=HELENA_TIMEOUT_PAINEL_S) as http:
        try:
            valor = await ler(HelenaConta(token, pedido.app.state.cfg.helena_url, http=http))
        except ErroHelenaApi as erro:
            raise _erro_helena(erro) from erro
    if len(_HELENA_CACHE) > 500:
        _HELENA_CACHE.clear()
    _HELENA_CACHE[(id_escritorio, chave)] = (time.monotonic(), valor)
    return valor


def _esquecer_helena(id_escritorio: str) -> None:
    for chave in [c for c in _HELENA_CACHE if c[0] == id_escritorio]:
        _HELENA_CACHE.pop(chave, None)


# ============================================================================ sessão
class Entrar(BaseModel):
    email: str
    senha: str
    # Página /superadmin: só a equipe LawChat entra (quem é de escritório é recusado sem abrir sessão).
    superadmin: bool = False


# Tentativas erradas de login por e-mail e por IP (memória do processo): 10 em 15 min bloqueiam por 15 min.
_FALHAS_LOGIN: dict[str, list[float]] = {}
_JANELA_LOGIN_S, _MAX_FALHAS_LOGIN = 15 * 60, 10


def _chaves_login(pedido: Request, email: str) -> list[str]:
    ip = (pedido.headers.get("x-forwarded-for", "").split(",")[0].strip() or (pedido.client.host if pedido.client else "?"))
    return [f"email:{email.lower()}", f"ip:{ip}"]


def _login_bloqueado(chaves: list[str]) -> bool:
    agora = time.time()
    for chave in chaves:
        recentes = [t for t in _FALHAS_LOGIN.get(chave, []) if agora - t < _JANELA_LOGIN_S]
        _FALHAS_LOGIN[chave] = recentes
        if len(recentes) >= _MAX_FALHAS_LOGIN:
            return True
    return False


def _anotar_falha_login(chaves: list[str]) -> None:
    for chave in chaves:
        _FALHAS_LOGIN.setdefault(chave, []).append(time.time())


class TrocarSenha(BaseModel):
    atual: str
    nova: str = Field(min_length=8)


@api.post("/entrar")
async def entrar(dados: Entrar, pedido: Request, resposta: Response) -> dict[str, Any]:
    repo = _repo(pedido)
    chaves = _chaves_login(pedido, dados.email.strip())
    if _login_bloqueado(chaves):
        raise HTTPException(429, "Muitas tentativas erradas. Espere 15 minutos e tente de novo.")
    usuario = await repo.usuario_por_email(dados.email.strip())
    if not usuario or not usuario["ativo"] or not seguranca.conferir_senha(dados.senha, usuario["senha_hash"]):
        _anotar_falha_login(chaves)
        raise HTTPException(401, "E-mail ou senha incorretos.")
    if dados.superadmin and usuario["papel"] not in PAPEIS_LAWCHAT:
        _anotar_falha_login(chaves)
        raise HTTPException(403, "Este acesso é só da equipe LawChat. Quem é de escritório entra pela conta.")
    for chave in chaves:
        _FALHAS_LOGIN.pop(chave, None)
    _gravar_sessao(pedido, resposta, usuario["id"])
    await repo.registrar_acesso(usuario["id"])
    return {"ok": True, "trocar_senha": usuario["trocar_senha"]}


def _gravar_sessao(pedido: Request, resposta: Response, id_usuario: str) -> None:
    https = pedido.url.scheme == "https" or pedido.headers.get("x-forwarded-proto") == "https"
    resposta.set_cookie(
        COOKIE, pedido.app.state.assinador.criar(id_usuario), httponly=True, max_age=seguranca.DURACAO_SESSAO_S,
        # Dentro da Helena o painel abre num iframe: o cookie precisa de SameSite=None (só vale em https).
        samesite="none" if https else "lax", secure=https)


def _handoff_valido(id_conta: str, ts: str | None, sig: str | None) -> str | None:
    """Se AGENTESIA_HELENA_HANDOFF_SEGREDO existir, exige sig = HMAC-SHA256(segredo, f"{id_conta}.{ts}"), válida por 5 min."""
    segredo = os.environ.get("AGENTESIA_HELENA_HANDOFF_SEGREDO")
    if not segredo:
        return None
    try:
        momento = int(ts or "")
    except ValueError:
        return "assinatura_ausente"
    if abs(time.time() * 1000 - momento) > 5 * 60 * 1000:
        return "assinatura_expirada"
    esperado = hmac.new(segredo.encode(), f"{id_conta}.{momento}".encode(), hashlib.sha256).hexdigest()
    return None if sig and hmac.compare_digest(esperado, sig) else "assinatura_invalida"


def _parametro(pedido: Request, *nomes: str) -> str | None:
    """A Helena manda os ids com nomes variados (company_id, companyId, id_da_conta...)."""
    procurados = {n.lower().replace("_", "") for n in nomes}
    for chave, valor in pedido.query_params.items():
        if chave.lower().replace("_", "") in procurados and valor.strip():
            return valor.strip()
    return None


_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")

entrada = APIRouter()


@entrada.get("/entrar/helena", include_in_schema=False)
async def entrar_pela_helena(pedido: Request) -> Response:
    """Entrada sem senha, a partir de um botão ou app dentro da Helena.

    Recebe a conta (company_id) e o usuário da Helena. Só aceita se:
      - a conta tem escritório ativo aqui, com o token da Helena funcionando;
      - a API da Helena, com o token DESSA conta, confirma que o usuário existe nela;
      - quando configurado, a assinatura do handoff confere.
    """
    from fastapi.responses import RedirectResponse

    def recusar(motivo: str) -> Response:
        return RedirectResponse(f"/entrar?erro={motivo}", status_code=303)

    id_conta = _parametro(pedido, "company_id", "id_da_conta", "conta")
    id_usuario = _parametro(pedido, "user_id", "id_do_usuario", "usuario", "agent_id")
    if not id_conta or not _UUID.fullmatch(id_conta) or not id_usuario or not _UUID.fullmatch(id_usuario):
        return recusar("link_incompleto")
    motivo = _handoff_valido(id_conta, pedido.query_params.get("ts"), pedido.query_params.get("sig"))
    if motivo:
        return recusar(motivo)

    repo = _repo(pedido)
    conta_lawchat = os.environ.get("AGENTESIA_HELENA_CONTA_LAWCHAT", "").strip().lower()
    if conta_lawchat and id_conta.lower() == conta_lawchat:
        return await _entrar_como_lawchat(pedido, repo, id_usuario, recusar)
    escritorio = await repo.escritorio_por_conta_helena(id_conta)
    if not escritorio:
        return recusar("conta_sem_ia")
    if escritorio.get("situacao", "ativo") != "ativo":
        return recusar("conta_suspensa")
    integracao = await repo.integracao(escritorio["id"], "helena")
    token = await repo.ler_segredo((integracao or {}).get("id_segredo_vault"))
    if not token:
        return recusar("helena_nao_conectada")
    try:
        atendente = await HelenaConta(token, pedido.app.state.cfg.helena_url).atendente(id_usuario)
    except ErroHelenaApi:
        return recusar("helena_indisponivel")
    if not atendente:
        return recusar("usuario_nao_encontrado")

    usuario = await repo.usuario_da_helena(escritorio["id"], atendente["id_usuario"])
    destino = "/"
    if not usuario and atendente["email"]:
        existente = await repo.usuario_por_email(atendente["email"])
        if existente and existente["papel"] in PAPEIS_LAWCHAT:
            usuario, destino = existente, f"/?escritorio={escritorio['id']}"     # equipe LawChat entrando na conta
        elif existente and existente["id_escritorio"] == escritorio["id"]:
            await repo.vincular_usuario_helena(existente["id"], atendente["id_usuario"], atendente["nome"])
            usuario = existente
    if not usuario:
        email = atendente["email"]
        if not email or await repo.usuario_por_email(email):
            email = f"helena-{atendente['id_usuario']}@{escritorio['id'][:8]}.helena.local"
        papel = (escritorio.get("config") or {}).get("papel_entrada_helena", "gestor")
        usuario = await repo.criar_usuario_da_helena(
            id_escritorio=escritorio["id"], id_usuario_helena=atendente["id_usuario"], email=email,
            nome=atendente["nome"], papel=papel if papel in ("gestor", "atendente") else "gestor",
            senha_hash=seguranca.gerar_hash(seguranca.senha_provisoria()))
        await repo.registrar_alteracao(id_usuario=usuario["id"], id_escritorio=escritorio["id"],
                                       tabela="agentesia_usuarios", id_registro=usuario["id"], acao="criou",
                                       resumo=f"{atendente['nome']} entrou pela primeira vez pela LawChat")
    if not usuario["ativo"]:
        return recusar("usuario_desativado")
    resposta = RedirectResponse(destino, status_code=303)
    _gravar_sessao(pedido, resposta, usuario["id"])
    await repo.registrar_acesso(usuario["id"])
    return resposta


async def _entrar_como_lawchat(pedido: Request, repo: RepositorioGestao, id_usuario: str, recusar: Any) -> Response:
    """A equipe LawChat entra pela própria conta da Helena (como no Weaver) e cai no admin.

    Quem é da conta da LawChat na Helena e ainda não tem acesso aqui entra como equipe; o dono promove depois.
    Quem tem usuário de cliente com o mesmo e-mail é recusado (não mistura papéis).
    """
    from fastapi.responses import RedirectResponse

    token = os.environ.get("AGENTESIA_HELENA_TOKEN_LAWCHAT", "")
    if not token:
        return recusar("helena_nao_conectada")
    try:
        atendente = await HelenaConta(token, pedido.app.state.cfg.helena_url).atendente(id_usuario)
    except ErroHelenaApi:
        return recusar("helena_indisponivel")
    if not atendente or not atendente.get("email"):
        return recusar("usuario_nao_encontrado")
    usuario = await repo.usuario_por_email(atendente["email"])
    if usuario and usuario["papel"] not in PAPEIS_LAWCHAT:
        return recusar("usuario_de_cliente")
    if not usuario:
        usuario = await repo.criar_usuario(email=atendente["email"], nome=atendente["nome"] or atendente["email"],
                                           senha_hash=seguranca.gerar_hash(seguranca.senha_provisoria()),
                                           papel="admin_lawchat", id_escritorio=None)
        await repo.registrar_alteracao(id_usuario=usuario["id"], id_escritorio=None, tabela="agentesia_usuarios",
                                       id_registro=usuario["id"], acao="criou",
                                       resumo=f"{usuario['nome']} entrou na equipe LawChat pela LawChat")
    if not usuario["ativo"]:
        return recusar("usuario_desativado")
    resposta = RedirectResponse("/admin/escritorios", status_code=303)
    _gravar_sessao(pedido, resposta, usuario["id"])
    await repo.registrar_acesso(usuario["id"])
    return resposta


@api.post("/sair")
async def sair(resposta: Response) -> dict[str, Any]:
    resposta.delete_cookie(COOKIE)
    return {"ok": True}


@api.get("/eu")
async def eu(pedido: Request, ctx: Contexto = Depends(contexto)) -> dict[str, Any]:
    u = ctx.usuario
    resposta = {"id": u["id"], "nome": u["nome"], "email": u["email"], "papel": u["papel"],
                "id_escritorio": u["id_escritorio"], "nome_escritorio": u.get("nome_escritorio"),
                "trocar_senha": u["trocar_senha"], "visao": ctx.visao, "escritorio_lawchat": None}
    # Equipe LawChat: o escritório da própria conta LawChat na Helena é a "conta" dela (Voltar para a conta).
    conta = os.environ.get("AGENTESIA_HELENA_CONTA_LAWCHAT", "").strip()
    if ctx.lawchat and conta and re.fullmatch(r"[0-9a-fA-F-]{36}", conta):
        repo = _repo(pedido)
        # Quase nunca muda: guardado por 60 s (o /eu roda em toda abertura do painel).
        guardado = getattr(repo, "_escritorio_lawchat", None)
        if guardado and guardado[0] == conta and time.monotonic() - guardado[1] < 60:
            resposta["escritorio_lawchat"] = guardado[2]
        else:
            id_esc = await repo.pool.fetchval(
                "select id from agentesia_escritorios where id_conta_helena = $1::uuid order by criado_em limit 1", conta)
            resposta["escritorio_lawchat"] = str(id_esc) if id_esc else None
            # Guarda também o "não tem" (antes cada /eu ia ao banco enquanto a conta LawChat não existia).
            repo._escritorio_lawchat = (conta, time.monotonic(), resposta["escritorio_lawchat"])
    return resposta


@api.post("/senha")
async def trocar_senha(dados: TrocarSenha, pedido: Request, ctx: Contexto = Depends(contexto)) -> dict[str, Any]:
    repo = _repo(pedido)
    completo = await repo.usuario_por_email(ctx.usuario["email"])
    if not completo or not seguranca.conferir_senha(dados.atual, completo["senha_hash"]):
        raise HTTPException(400, "Senha atual incorreta.")
    await repo.trocar_senha(ctx.id_usuario, seguranca.gerar_hash(dados.nova))
    return {"ok": True}


@api.get("/catalogo")
async def catalogo(_: Contexto = Depends(contexto)) -> dict[str, Any]:
    return {"modelos": MODELOS, "produtos": PRODUTOS, "nomes_etapas": NOMES_ETAPAS, "funcoes": FUNCOES}


# ============================================================================ admin LawChat
class NovoEscritorio(BaseModel):
    nome: str = Field(min_length=2)
    id_conta_helena: str | None = None
    gerar_token_helena: bool = False
    token_helena: str | None = None
    email_gestor: str | None = None
    nome_gestor: str | None = None
    # Primeira criação (como o "Habilitar funções" do Weaver): etiquetas padrão na Helena e painel do CRM.
    # A API da Helena não cria painel: só escolhe um existente (GET crm/v2/panel).
    criar_etiquetas_padrao: bool = False
    criar_equipe_ia: bool = False          # "🤖 Comercial IA" (isDefault=true), como o fluxo n8n de admin
    id_painel: str | None = None
    titulo_painel: str | None = None


NOME_DO_TOKEN_HELENA = "IA LawChat"        # nome do token da conta na Helena (pedido do dono)


class NovoUsuario(BaseModel):
    email: str
    nome: str = Field(min_length=2)
    papel: str = "gestor"


@api.get("/admin/escritorios")
async def listar_escritorios(pedido: Request, _: Contexto = Depends(ADMIN)) -> list[dict[str, Any]]:
    """Tela Contas: cada conta (escritório) com os dados da empresa na Helena, o "Criar Agente" e a última sync.
    A conta da própria LawChat (AGENTESIA_HELENA_CONTA_LAWCHAT) vem marcada e primeiro."""
    conta_lawchat = os.environ.get("AGENTESIA_HELENA_CONTA_LAWCHAT", "").strip().lower()
    linhas = await _repo(pedido).escritorios()
    for e in linhas:
        e["conta_lawchat"] = bool(conta_lawchat) and str(e.get("id_conta_helena") or "").lower() == conta_lawchat
        marcado = e.get("criar_agente") if isinstance(e.get("criar_agente"), dict) else None
        # Sem marca (contas de antes da tela Contas): habilitado se a Helena já está conectada.
        e["agente_habilitado"] = bool(marcado.get("habilitado")) if marcado else e.get("helena") == "ok"
        sync = e.get("sync_helena") if isinstance(e.get("sync_helena"), dict) else {}
        e["webhook"] = ("error" if sync.get("situacao") == "erro" else
                        "synced" if (e.get("conta_helena") or sync.get("situacao") == "ok") else "pending")
    linhas.sort(key=lambda e: not e["conta_lawchat"])
    return linhas


@api.get("/admin/helena/empresas")
async def empresas_helena(pedido: Request, busca: str = "", _: Contexto = Depends(ADMIN)) -> list[dict[str, Any]]:
    token = os.environ.get("AGENTESIA_HELENA_TOKEN_PARCEIRO")
    if not token:
        raise HTTPException(409, "Configure AGENTESIA_HELENA_TOKEN_PARCEIRO no servidor para buscar contas da LawChat.")
    try:
        return await HelenaParceiro(token, pedido.app.state.cfg.helena_url).empresas(busca)
    except ErroHelenaApi as erro:
        raise _erro_helena(erro) from erro


@api.post("/admin/escritorios")
async def criar_escritorio(dados: NovoEscritorio, pedido: Request, ctx: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    repo = _repo(pedido)
    escritorio = await repo.criar_escritorio(dados.nome.strip(), dados.id_conta_helena or None)
    resultado: dict[str, Any] = {"escritorio": escritorio}

    async def falhou(acao: str, resumo: str, erro: str) -> None:
        # O escritório já existe: a falha fica no histórico (situacao='erro') antes de voltar para a tela.
        await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=escritorio["id"],
                                       tabela="agentesia_escritorios", id_registro=escritorio["id"], acao=acao,
                                       resumo=resumo, situacao="erro", erro=erro)

    token = (dados.token_helena or "").strip() or None
    if not token and dados.gerar_token_helena and dados.id_conta_helena:
        parceiro = os.environ.get("AGENTESIA_HELENA_TOKEN_PARCEIRO")
        if not parceiro:
            await falhou("gerar_token", f"Token da LawChat de {escritorio['nome']} não gerado", "sem token de parceiro")
            raise HTTPException(409, "Sem token de parceiro para gerar o token da conta.")
        try:
            token = await HelenaParceiro(parceiro, pedido.app.state.cfg.helena_url).criar_token(
                dados.id_conta_helena, NOME_DO_TOKEN_HELENA)
        except ErroHelenaApi as erro:
            await falhou("gerar_token", f"Token da LawChat de {escritorio['nome']} não gerado", f"{erro.motivo}: {erro.detalhe}")
            raise _erro_helena(erro) from erro
    if token:
        try:
            resultado["helena"] = await _salvar_token_helena(pedido, repo, escritorio["id"], token)
        except HTTPException as erro:
            await falhou("conectou", f"Token da LawChat de {escritorio['nome']} recusado", str(erro.detail))
            raise
        resultado.update(await _primeira_criacao_na_helena(pedido, repo, ctx, escritorio, token, dados))

    if dados.email_gestor:
        senha = seguranca.senha_provisoria()
        resultado["gestor"] = await repo.criar_usuario(
            email=dados.email_gestor.strip(), nome=(dados.nome_gestor or dados.email_gestor).strip(),
            senha_hash=seguranca.gerar_hash(senha), papel="gestor", id_escritorio=escritorio["id"])
        resultado["senha_provisoria"] = senha
    await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=escritorio["id"],
                                   tabela="agentesia_escritorios", id_registro=escritorio["id"], acao="criou",
                                   resumo=f"Escritório {escritorio['nome']} criado", depois=escritorio)
    return resultado


async def _primeira_criacao_na_helena(pedido: Request, repo: RepositorioGestao, ctx: Contexto, escritorio: dict[str, Any],
                                      token: str, dados: NovoEscritorio) -> dict[str, Any]:
    """Etiquetas padrão e painel do CRM na criação do escritório. Não derruba a criação: o que falhar volta no
    resultado, fica no histórico com situacao='erro' e pode ser refeito em Onboarding (Avançar)."""
    from app.gestao import sincronizar_conta

    saida: dict[str, Any] = {}
    parceiro = os.environ.get("AGENTESIA_HELENA_TOKEN_PARCEIRO")
    if parceiro and dados.id_conta_helena:
        # Dados cadastrais da empresa (CNPJ, razão social, endereço, plano/recursos), sem e-mail/telefone.
        try:
            conta = await sincronizar_conta.dados_da_empresa(
                HelenaParceiro(parceiro, pedido.app.state.cfg.helena_url), dados.id_conta_helena)
            if conta:
                await sincronizar_conta.salvar_dados_helena(repo.pool, escritorio["id"], conta=conta)
                saida["empresa"] = conta
        except ErroHelenaApi as erro:
            saida["erro_empresa"] = erro.motivo
    if not dados.criar_etiquetas_padrao and not dados.id_painel and not dados.criar_equipe_ia:
        return saida
    helena = HelenaConta(token, pedido.app.state.cfg.helena_url)
    if dados.criar_equipe_ia:
        try:
            equipe = await sincronizar_conta.criar_equipe_ia(helena)
            if equipe.get("id"):
                await sincronizar_conta.salvar_dados_helena(repo.pool, escritorio["id"], ids={"id_departamento": equipe["id"]})
            saida["equipe"] = equipe
            await repo.registrar_alteracao(
                id_usuario=ctx.id_usuario, id_escritorio=escritorio["id"], tabela="agentesia_escritorios",
                id_registro=escritorio["id"], acao="criou_equipe",
                resumo=f"Equipe {equipe['nome']} na LawChat: {'criada' if equipe['criada'] else 'já existia'}")
        except ErroHelenaApi as erro:
            saida["equipe"] = {"erro": erro.motivo}
            await repo.registrar_alteracao(
                id_usuario=ctx.id_usuario, id_escritorio=escritorio["id"], tabela="agentesia_escritorios",
                id_registro=escritorio["id"], acao="criou_equipe", resumo="Equipe da IA na LawChat",
                situacao="erro", erro=f"{erro.motivo}: {erro.detalhe}")
    try:
        paineis = await helena.paineis()
        saida["paineis"] = [{"id": p["id"], "titulo": p["titulo"], "colunas": len(p["etapas"])} for p in paineis]
    except ErroHelenaApi as erro:
        paineis, saida["erro_paineis"] = [], erro.motivo
    if dados.criar_etiquetas_padrao:
        try:
            feitas = await sincronizar_conta.garantir_etiquetas_padrao(helena)
            saida["etiquetas"] = {"criadas": [e["nome"] for e in feitas["criadas"]], "ja_existiam": feitas["ja_existiam"]}
            ids_etiquetas = sincronizar_conta.ids_das_etiquetas_padrao(await helena.etiquetas())
            await sincronizar_conta.salvar_dados_helena(repo.pool, escritorio["id"], ids={"etiquetas": ids_etiquetas})
            await repo.registrar_alteracao(
                id_usuario=ctx.id_usuario, id_escritorio=escritorio["id"], tabela="agentesia_escritorios",
                id_registro=escritorio["id"], acao="criou_etiquetas",
                resumo=f"Etiquetas padrão na LawChat: {len(feitas['criadas'])} criada(s), {len(feitas['ja_existiam'])} já existia(m)")
        except ErroHelenaApi as erro:
            saida["etiquetas"] = {"erro": erro.motivo}
            await repo.registrar_alteracao(
                id_usuario=ctx.id_usuario, id_escritorio=escritorio["id"], tabela="agentesia_escritorios",
                id_registro=escritorio["id"], acao="criou_etiquetas", resumo="Etiquetas padrão na LawChat",
                situacao="erro", erro=f"{erro.motivo}: {erro.detalhe}")
    if dados.id_painel:
        painel = next((p for p in paineis if p["id"] == dados.id_painel), None)
        if painel:
            from app.gestao import onboarding
            config = await onboarding.guardar_painel(repo, escritorio["id"], painel,
                                                     sincronizar_conta.mapear_etapas(painel), dados.titulo_painel)
            saida["crm"] = config
            await repo.registrar_alteracao(
                id_usuario=ctx.id_usuario, id_escritorio=escritorio["id"], tabela="agentesia_integracoes",
                id_registro=None, acao="alterou", resumo=f"Painel do CRM da LawChat escolhido: {painel['titulo']}",
                depois=config)
        else:
            saida["crm"] = {"erro": "painel_nao_encontrado"}
            await repo.registrar_alteracao(
                id_usuario=ctx.id_usuario, id_escritorio=escritorio["id"], tabela="agentesia_integracoes",
                id_registro=None, acao="alterou", resumo="Painel do CRM da LawChat", situacao="erro",
                erro=f"o painel {dados.id_painel} não existe nesta conta da LawChat")
    return saida


class Responsavel(BaseModel):
    id_usuario: str | None = None


@api.put("/admin/escritorios/{id_escritorio}/responsavel")
async def definir_responsavel(id_escritorio: str, dados: Responsavel, pedido: Request,
                              ctx: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    repo = _repo(pedido)
    if not await repo.escritorio(id_escritorio):
        raise HTTPException(404, "Escritório não encontrado.")
    nome = None
    if dados.id_usuario:
        membro = await repo.membro_lawchat(dados.id_usuario)
        if not membro or not membro["ativo"]:
            raise HTTPException(400, "Escolha alguém ativo da equipe LawChat.")
        nome = membro["nome"]
    await repo.definir_responsavel(id_escritorio, dados.id_usuario)
    await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=id_escritorio, tabela="agentesia_escritorios",
                                   id_registro=id_escritorio, acao="alterou",
                                   resumo=f"Responsável na LawChat: {nome or 'ninguém'}")
    return {"ok": True}


async def _agente_do_escritorio(repo: Any, ctx: Contexto, id_agente: str) -> dict[str, Any]:
    """Base de conhecimento e perguntas sem resposta: valem também para o agente sem número (produto que voltou da
    lixeira e ainda não escolheu o número). repo.agente() só acha agente com número (junta com o canal), e a tela
    do produto, que reaproveita os documentos na reativação, recebia 404."""
    agente = await repo.agente(ctx.escritorio(), id_agente)
    if not agente and getattr(repo, "pool", None) is not None:
        from app.gestao.repositorio import _linha
        agente = _linha(await repo.pool.fetchrow(
            """select a.* from agentesia_agentes a where a.id = $1::uuid and a.id_escritorio = $2::uuid and a.id_canal is null""",
            id_agente, ctx.escritorio()))
        if agente and isinstance(agente.get("config"), str):
            agente["config"] = json.loads(agente["config"] or "{}")
    if not agente:
        raise HTTPException(404, "Agente não encontrado.")
    return agente


@api.get("/agentes/{id_agente}/documentos")
async def listar_documentos(id_agente: str, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> list[dict[str, Any]]:
    repo = _repo(pedido)

    async def ler_papeis() -> dict[str, list[str]]:
        try:
            return {str(l["id"]): list(l["papeis"] or []) for l in await repo.pool.fetch(
                "select id, papeis from agentesia_documentos where id_agente = $1::uuid", id_agente)}
        except Exception:                              # noqa: BLE001 - banco sem a migração 003
            return {}

    # A conferência do agente e as duas leituras em paralelo (o resultado só sai se o agente for deste escritório).
    _, todos, papeis = await asyncio.gather(_agente_do_escritorio(repo, ctx, id_agente), repo.documentos(id_agente), ler_papeis())
    # FAQ e objeções (documentos virtuais) são editados na aba Conhecimento: não aparecem na lista de documentos.
    documentos = [d for d in todos if d.get("tipo") in ("arquivo", "texto", None)]
    return [{**d, "papeis": papeis.get(str(d["id"]), [])} for d in documentos]


@api.post("/agentes/{id_agente}/documentos")
async def enviar_documento(id_agente: str, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Arquivo (PDF, Word, planilha, texto) ou texto colado. Guarda só o texto e indexa em segundo plano."""
    from app import conhecimento as base
    from app.gestao.produtos import DocumentoNovo, ler_documento

    corpo = await pedido.json()
    dados = DocumentoNovo(**corpo)
    papeis = base.papeis_validos(corpo.get("papeis"))    # escopo: vazio = todos os papéis
    repo = _repo(pedido)
    await _agente_do_escritorio(repo, ctx, id_agente)
    texto, formato, tamanho = ler_documento(dados)
    documento = await repo.criar_documento(id_escritorio=ctx.escritorio(), id_agente=id_agente, nome=dados.nome.strip(),
                                           formato=formato, tamanho_bytes=tamanho, texto=texto, criado_por=ctx.id_usuario,
                                           tipo="texto" if dados.tipo == "texto" else "arquivo")
    if papeis:
        await repo.pool.execute("update agentesia_documentos set papeis = $2::text[] where id = $1::uuid",
                                documento["id"], papeis)
    documento = {**documento, "papeis": papeis}
    await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=ctx.escritorio(), tabela="agentesia_documentos",
                                   id_registro=documento["id"], acao="criou",
                                   resumo=f"Documento \"{documento['nome']}\" na base de conhecimento ({len(texto)} caracteres)")
    sinal = getattr(pedido.app.state, "indexar_agora", None)
    if sinal is not None:
        sinal.set()
    return {**documento, "previa": texto[:600], "trechos": len(base.dividir(texto))}


@api.post("/agentes/{id_agente}/documentos/{id_documento}/reprocessar")
async def reprocessar_documento(id_agente: str, id_documento: str, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    repo = _repo(pedido)
    await _agente_do_escritorio(repo, ctx, id_agente)
    feito = await repo.pool.fetchval(
        """update agentesia_documentos set situacao = 'processando', erro = null
           where id = $1::uuid and id_agente = $2::uuid returning true""", id_documento, id_agente)
    if not feito:
        raise HTTPException(404, "Documento não encontrado.")
    sinal = getattr(pedido.app.state, "indexar_agora", None)
    if sinal is not None:
        sinal.set()
    return {"ok": True}


@api.delete("/agentes/{id_agente}/documentos/{id_documento}")
async def apagar_documento(id_agente: str, id_documento: str, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    repo = _repo(pedido)
    await _agente_do_escritorio(repo, ctx, id_agente)
    nome = await repo.apagar_documento(id_agente, id_documento)
    if not nome:
        raise HTTPException(404, "Documento não encontrado (os documentos padrão do produto não podem ser removidos).")
    await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=ctx.escritorio(), tabela="agentesia_documentos",
                                   id_registro=id_documento, acao="apagou", resumo=f"Documento \"{nome}\" tirado da base")
    return {"ok": True}


class PapeisDoDocumento(BaseModel):
    papeis: list[str] = Field(default_factory=list)     # vazio = todos os papéis


@api.put("/agentes/{id_agente}/documentos/{id_documento}/papeis")
async def papeis_do_documento(id_agente: str, id_documento: str, dados: PapeisDoDocumento, pedido: Request,
                              ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Escopo do documento por papel. Só troca o filtro dos trechos: não vetoriza de novo."""
    from app import conhecimento as base

    repo = _repo(pedido)
    await _agente_do_escritorio(repo, ctx, id_agente)
    papeis = base.papeis_validos(dados.papeis)
    async with repo.pool.acquire() as conexao, conexao.transaction():
        nome = await conexao.fetchval(
            """update agentesia_documentos set papeis = $3::text[]
               where id = $1::uuid and id_agente = $2::uuid and tipo in ('arquivo', 'texto') returning nome""",
            id_documento, id_agente, papeis)
        if not nome:
            raise HTTPException(404, "Documento não encontrado.")
        await conexao.execute("update agentesia_documento_trechos set papeis = $2::text[] where id_documento = $1::uuid",
                              id_documento, papeis)
    await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=ctx.escritorio(), tabela="agentesia_documentos",
                                   id_registro=id_documento, acao="alterou",
                                   resumo=f"Documento \"{nome}\": papéis {', '.join(papeis) or 'todos'}")
    return {"ok": True, "papeis": papeis}


# ---------------------------------------------------------------------------- perguntas sem resposta na base
@api.get("/agentes/{id_agente}/lacunas")
async def listar_lacunas(id_agente: str, pedido: Request, situacao: str = "aberta",
                         ctx: Contexto = Depends(GESTAO)) -> list[dict[str, Any]]:
    """Perguntas que a IA não achou na base nem no prompt (a mais repetida primeiro)."""
    repo = _repo(pedido)
    if situacao not in ("aberta", "respondida", "ignorada"):
        raise HTTPException(400, "Situação inválida.")
    _, linhas = await asyncio.gather(_agente_do_escritorio(repo, ctx, id_agente), repo.pool.fetch(
        """select id, papel, pergunta, vezes, situacao, resposta, ultimo_lead, criado_em, ultima_em
           from agentesia_conhecimento_lacunas
           where id_agente = $1::uuid and id_escritorio = $2::uuid and situacao = $3
           order by vezes desc, ultima_em desc limit 200""", id_agente, ctx.escritorio(), situacao))
    return _linhas(linhas)


class RespostaDaLacuna(BaseModel):
    resposta: str = Field(min_length=2, max_length=1500)
    pergunta: str | None = Field(default=None, max_length=300)   # vazio = a pergunta como a IA anotou
    papeis: list[str] = Field(default_factory=list)


@api.post("/agentes/{id_agente}/lacunas/{id_lacuna}/responder")
async def responder_lacuna(id_agente: str, id_lacuna: str, dados: RespostaDaLacuna, pedido: Request,
                           ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Responde a pergunta e ela vira um item da FAQ do agente (entra na base no próximo turno)."""
    from app import conhecimento as base

    repo = _repo(pedido)
    agente = await _agente_do_escritorio(repo, ctx, id_agente)
    lacuna = await repo.pool.fetchrow(
        """select pergunta from agentesia_conhecimento_lacunas
           where id = $1::uuid and id_agente = $2::uuid and id_escritorio = $3::uuid and situacao = 'aberta'""",
        id_lacuna, id_agente, ctx.escritorio())
    if not lacuna:
        raise HTTPException(404, "Pergunta não encontrada (ou já respondida).")
    config = dict(agente.get("config") or {})
    conhecimento = dict(config.get("conhecimento") or {})
    item = {"pergunta": (dados.pergunta or lacuna["pergunta"]).strip()[:300], "resposta": dados.resposta.strip()}
    if papeis := base.papeis_validos(dados.papeis):
        item["papeis"] = papeis
    conhecimento = _limpar_conhecimento({**conhecimento, "faq": list(conhecimento.get("faq") or []) + [item]})
    config["conhecimento"] = conhecimento
    await repo.alterar_agente(ctx.escritorio(), id_agente, {"config": config})
    await repo.pool.execute(
        """update agentesia_conhecimento_lacunas set situacao = 'respondida', resposta = $2, respondida_por = $3::uuid
           where id = $1::uuid""", id_lacuna, item["resposta"], ctx.id_usuario)
    await _sincronizar_base(pedido, repo, ctx.escritorio(), id_agente, conhecimento)
    await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=ctx.escritorio(), tabela="agentesia_agentes",
                                   id_registro=id_agente, acao="alterou",
                                   resumo=f"Pergunta sem resposta virou FAQ: {item['pergunta'][:80]}")
    return {"ok": True, "faq": item}


@api.post("/agentes/{id_agente}/lacunas/{id_lacuna}/ignorar")
async def ignorar_lacuna(id_agente: str, id_lacuna: str, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    repo = _repo(pedido)
    await _agente_do_escritorio(repo, ctx, id_agente)
    feito = await repo.pool.fetchval(
        """update agentesia_conhecimento_lacunas set situacao = 'ignorada'
           where id = $1::uuid and id_agente = $2::uuid and id_escritorio = $3::uuid and situacao = 'aberta' returning true""",
        id_lacuna, id_agente, ctx.escritorio())
    if not feito:
        raise HTTPException(404, "Pergunta não encontrada (ou já tratada).")
    return {"ok": True}


class LimiteConsumo(BaseModel):
    mensal_usd: float | None = None
    ao_estourar: str = "pausar"
    avisar_em: list[int] = Field(default_factory=lambda: [80, 100])


@api.put("/admin/escritorios/{id_escritorio}/limite")
async def definir_limite(id_escritorio: str, dados: LimiteConsumo, pedido: Request,
                         ctx: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    """Limite mensal de consumo da IA (em dólar). Só a equipe LawChat define."""
    from app import consumo

    repo = _repo(pedido)
    if not await repo.escritorio(id_escritorio):
        raise HTTPException(404, "Escritório não encontrado.")
    try:
        limite = consumo.validar(dados.model_dump())
    except ValueError as erro:
        raise HTTPException(400, str(erro)) from erro
    await repo.salvar_limite_consumo(id_escritorio, limite)
    texto = (f"US$ {limite['mensal_usd']:.2f} por mês, {'pausa a IA' if limite['ao_estourar'] == 'pausar' else 'só avisa'} ao estourar"
             if limite["mensal_usd"] else "sem limite")
    await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=id_escritorio, tabela="agentesia_escritorios",
                                   id_registro=id_escritorio, acao="alterou", resumo=f"Limite de consumo da IA: {texto}")
    return {"limite_consumo": limite}


@api.get("/consumo")
async def ver_consumo(pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Gasto da IA no mês (dia a dia e por função) e o limite do escritório."""
    from app import consumo

    repo = _repo(pedido)
    escritorio = await repo.escritorio(ctx.escritorio())
    if not escritorio:
        raise HTTPException(404, "Escritório não encontrado.")
    inicio = consumo.inicio_do_mes()
    dados = await repo.consumo_do_mes(ctx.escritorio(), inicio)
    config = escritorio.get("config") or {}
    config = config if isinstance(config, dict) else json.loads(config)
    situacao = consumo.avaliar(dados["gasto_usd"], config)
    return {**dados, "mes": inicio.strftime("%Y-%m"), "limite": consumo.config_do_limite(config),
            "percentual": situacao.percentual, "bloqueado": situacao.bloqueado}


# ============================================================================ equipe LawChat
class NovoMembro(BaseModel):
    email: str = Field(min_length=5)
    nome: str = Field(min_length=2)
    papel: str = "admin_lawchat"


class AlterarMembro(BaseModel):
    nome: str | None = None
    papel: str | None = None
    ativo: bool | None = None


@api.get("/admin/equipe")
async def listar_equipe(pedido: Request, _: Contexto = Depends(ADMIN)) -> list[dict[str, Any]]:
    """Quem é da LawChat: todo mundo da equipe vê; só o dono muda."""
    return await _repo(pedido).equipe_lawchat()


@api.post("/admin/equipe")
async def adicionar_membro(dados: NovoMembro, pedido: Request, ctx: Contexto = Depends(DONO)) -> dict[str, Any]:
    if dados.papel not in PAPEIS_LAWCHAT:
        raise HTTPException(400, "Papel inválido.")
    repo = _repo(pedido)
    email = dados.email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(400, "E-mail inválido.")
    if await repo.usuario_por_email(email):
        raise HTTPException(409, "Já existe alguém com este e-mail.")
    senha = seguranca.senha_provisoria()
    membro = await repo.criar_usuario(email=email, nome=dados.nome.strip(), senha_hash=seguranca.gerar_hash(senha),
                                      papel=dados.papel, id_escritorio=None)
    await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=None, tabela="agentesia_usuarios",
                                   id_registro=membro["id"], acao="criou",
                                   resumo=f"{membro['nome']} entrou na equipe LawChat ({_NOME_PAPEL[dados.papel]})")
    return {"membro": membro, "senha_provisoria": senha}


_NOME_PAPEL = {"dono_lawchat": "dono", "admin_lawchat": "equipe", "gestor": "gestor", "atendente": "atendente"}


@api.patch("/admin/equipe/{id_usuario}")
async def alterar_membro(id_usuario: str, dados: AlterarMembro, pedido: Request,
                         ctx: Contexto = Depends(DONO)) -> dict[str, Any]:
    repo = _repo(pedido)
    membro = await repo.membro_lawchat(id_usuario)
    if not membro:
        raise HTTPException(404, "Pessoa não encontrada na equipe LawChat.")
    if dados.papel is not None and dados.papel not in PAPEIS_LAWCHAT:
        raise HTTPException(400, "Papel inválido.")
    perde_dono = membro["papel"] == "dono_lawchat" and membro["ativo"] and (
        dados.ativo is False or (dados.papel is not None and dados.papel != "dono_lawchat"))
    if id_usuario == ctx.id_usuario and (dados.ativo is False or perde_dono):
        raise HTTPException(400, "Você não pode tirar o próprio acesso de dono nem se desativar.")
    if perde_dono and await repo.donos_ativos() <= 1:
        raise HTTPException(400, "A LawChat precisa de pelo menos um dono ativo.")
    alterado = await repo.alterar_membro_lawchat(
        id_usuario, nome=(dados.nome or "").strip() or None, papel=dados.papel, ativo=dados.ativo)
    mudancas = []
    if dados.papel and dados.papel != membro["papel"]:
        mudancas.append(f"papel: {_NOME_PAPEL[membro['papel']]} → {_NOME_PAPEL[dados.papel]}")
    if dados.ativo is not None and dados.ativo != membro["ativo"]:
        mudancas.append("reativado" if dados.ativo else "desativado")
    if mudancas:
        await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=None, tabela="agentesia_usuarios",
                                       id_registro=id_usuario, acao="alterou",
                                       resumo=f"{membro['nome']}: " + ", ".join(mudancas))
    return {"membro": alterado}


@api.post("/admin/equipe/{id_usuario}/senha")
async def nova_senha_membro(id_usuario: str, pedido: Request, ctx: Contexto = Depends(DONO)) -> dict[str, Any]:
    repo = _repo(pedido)
    membro = await repo.membro_lawchat(id_usuario)
    if not membro:
        raise HTTPException(404, "Pessoa não encontrada na equipe LawChat.")
    senha = seguranca.senha_provisoria()
    await repo.redefinir_senha(id_usuario, seguranca.gerar_hash(senha))
    await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=None, tabela="agentesia_usuarios",
                                   id_registro=id_usuario, acao="alterou", resumo=f"Nova senha provisória para {membro['nome']}")
    return {"senha_provisoria": senha}


# ============================================================================ escritório
class AlterarEscritorio(BaseModel):
    nome: str | None = None
    ia_desligada: bool | None = None
    situacao: str | None = None
    horario_inicio: int | None = Field(default=None, ge=0, le=23)
    horario_fim: int | None = Field(default=None, ge=1, le=24)
    horario_dias: list[int] | None = None
    modo_ia_horario: str | None = None
    etiquetas_por_produto: dict[str, str] | None = None
    honorarios: str | None = None
    # Endereço da Helena do escritório, para o link da conversa nos avisos: "advmidia", "advmidia.wts.chat" ou a URL.
    # Vazio apaga. Grava só o endereço (advmidia.wts.chat).
    dominio_helena: str | None = Field(default=None, max_length=300)


@api.get("/escritorio")
async def ver_escritorio(pedido: Request, ctx: Contexto = Depends(TODOS)) -> dict[str, Any]:
    repo = _repo(pedido)
    escritorio, usuarios = await asyncio.gather(repo.escritorio(ctx.escritorio()), repo.usuarios_do_escritorio(ctx.escritorio()))
    if not escritorio:
        raise HTTPException(404, "Escritório não encontrado.")
    escritorio["usuarios"] = usuarios
    return escritorio


@api.patch("/escritorio")
async def alterar_escritorio(dados: AlterarEscritorio, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    repo = _repo(pedido)
    antes = await repo.escritorio(ctx.escritorio())
    if not antes:
        raise HTTPException(404, "Escritório não encontrado.")
    campos: dict[str, Any] = {}
    if dados.nome is not None:
        campos["nome"] = dados.nome.strip()
    if dados.ia_desligada is not None:
        campos["ia_desligada"] = dados.ia_desligada
    if dados.situacao is not None:
        if not ctx.admin:
            raise HTTPException(403, "Só a equipe LawChat muda a situação do escritório.")
        campos["situacao"] = dados.situacao
    config = dict(antes.get("config") or {})
    if dados.modo_ia_horario is not None and dados.modo_ia_horario not in ("sempre", "so_no_horario", "so_fora_do_horario"):
        raise HTTPException(400, "Horário da IA: escolha sempre, só no horário ou só fora do horário.")
    if dados.horario_dias is not None and (not dados.horario_dias or any(d < 0 or d > 6 for d in dados.horario_dias)):
        raise HTTPException(400, "Escolha pelo menos um dia da semana.")
    inicio = dados.horario_inicio if dados.horario_inicio is not None else (antes.get("config") or {}).get("horario_inicio", 8)
    fim = dados.horario_fim if dados.horario_fim is not None else (antes.get("config") or {}).get("horario_fim", 18)
    if inicio >= fim:
        raise HTTPException(400, "O horário de início precisa ser antes do fim.")
    if dados.etiquetas_por_produto is not None:
        from app.origem import PRODUTOS
        dados.etiquetas_por_produto = {p: e.strip()[:80] for p, e in dados.etiquetas_por_produto.items() if p in PRODUTOS and e.strip()}
    for chave in ("horario_inicio", "horario_fim", "horario_dias", "modo_ia_horario", "etiquetas_por_produto", "honorarios"):
        valor = getattr(dados, chave)
        if valor is not None:
            config[chave] = valor
    if dados.dominio_helena is not None:
        if not dados.dominio_helena.strip():
            config.pop("dominio_helena", None)
        else:
            dominio = sinais.dominio_do_escritorio({"dominio_helena": dados.dominio_helena})
            if not dominio:
                raise HTTPException(400, "Domínio da LawChat inválido. Use, por exemplo, meuescritorio ou meuescritorio.wts.chat.")
            config["dominio_helena"] = dominio
    if config != (antes.get("config") or {}):
        campos["config"] = config
    depois = await repo.alterar_escritorio(antes["id"], campos)
    acao = "desligou_ia" if campos.get("ia_desligada") else ("ligou_ia" if campos.get("ia_desligada") is False else "alterou")
    await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=antes["id"], tabela="agentesia_escritorios",
                                   id_registro=antes["id"], acao=acao, resumo="Dados do escritório alterados",
                                   antes={k: antes.get(k) for k in campos}, depois={k: (depois or {}).get(k) for k in campos})
    return depois or {}


@api.post("/escritorio/usuarios")
async def criar_usuario(dados: NovoUsuario, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    if dados.papel not in ("gestor", "atendente"):
        raise HTTPException(400, "Papel inválido.")
    repo = _repo(pedido)
    if await repo.usuario_por_email(dados.email.strip()):
        raise HTTPException(409, "Já existe um usuário com este e-mail.")
    senha = seguranca.senha_provisoria()
    usuario = await repo.criar_usuario(email=dados.email.strip(), nome=dados.nome.strip(),
                                       senha_hash=seguranca.gerar_hash(senha), papel=dados.papel,
                                       id_escritorio=ctx.escritorio())
    await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=ctx.escritorio(), tabela="agentesia_usuarios",
                                   id_registro=usuario["id"], acao="criou", resumo=f"Usuário {usuario['email']} criado")
    return {"usuario": usuario, "senha_provisoria": senha}


# ============================================================================ integrações
class TokenHelena(BaseModel):
    token: str = Field(min_length=10)


class TokenSimples(BaseModel):
    token: str = Field(min_length=8)


class ConfigCrm(BaseModel):
    id_painel: str
    titulo_painel: str | None = None


TOKEN_DE_OUTRO_ESCRITORIO = ("Este token da LawChat já está ligado a outro escritório. Cada escritório usa o token da "
                             "própria conta: gere um token na conta deste escritório (Ajustes › Integrações › Integração via API).")


def _token_de_outra_conta(conta_do_token: str, conta_do_escritorio: str) -> str:
    return (f"Este token é de outra conta da LawChat (conta {conta_do_token[:8]}…), não da conta deste escritório "
            f"({conta_do_escritorio[:8]}…). Gere o token dentro da conta certa e cole de novo.")


async def _salvar_token_helena(pedido: Request, repo: RepositorioGestao, id_escritorio: str, token: str) -> dict[str, Any]:
    """Isolamento: o token não pode estar ligado a outro escritório, e a conta dona do token (companyId lido pela
    API) tem de ser a do escritório (id_conta_helena). Recusado, nada muda no cadastro."""
    token = token.strip()
    if await repo.pool.fetchval(
            """select true from agentesia_integracoes i join vault.decrypted_secrets s on s.id = i.id_segredo_vault
               where i.tipo = 'helena' and i.id_escritorio <> $1::uuid and s.decrypted_secret = $2 limit 1""",
            id_escritorio, token):
        raise HTTPException(409, TOKEN_DE_OUTRO_ESCRITORIO)
    atual = await repo.integracao(id_escritorio, "helena")
    helena = HelenaConta(token, pedido.app.state.cfg.helena_url)
    try:
        canais = await helena.canais()
        conta_do_token = await helena.id_da_conta()
    except ErroHelenaApi as erro:
        id_segredo = await repo.guardar_segredo(f"agentesia_helena_{id_escritorio}", token,
                                                (atual or {}).get("id_segredo_vault"))
        await repo.salvar_integracao(id_escritorio, "helena", id_segredo_vault=id_segredo,
                                     final_segredo=_final(token), situacao="erro", erro=str(erro))
        raise _erro_helena(erro) from erro
    conta_do_escritorio = str(await repo.pool.fetchval(
        "select id_conta_helena from agentesia_escritorios where id = $1::uuid", id_escritorio) or "").lower()
    if conta_do_token and conta_do_escritorio and conta_do_token != conta_do_escritorio:
        raise HTTPException(409, _token_de_outra_conta(conta_do_token, conta_do_escritorio))
    if conta_do_token and not conta_do_escritorio and await repo.pool.fetchval(
            "select true from agentesia_escritorios where id_conta_helena::text = $1 and id <> $2::uuid limit 1",
            conta_do_token, id_escritorio):
        raise HTTPException(409, TOKEN_DE_OUTRO_ESCRITORIO)
    if not conta_do_token:
        import logging
        logging.getLogger(__name__).warning("token da Helena salvo sem conferir a conta: a API não mandou companyId (escritório %s)", id_escritorio)
    _esquecer_helena(id_escritorio)          # token novo: etiquetas/equipes guardadas eram da conta antiga
    id_segredo = await repo.guardar_segredo(f"agentesia_helena_{id_escritorio}", token,
                                            (atual or {}).get("id_segredo_vault"))
    await repo.sincronizar_canais(id_escritorio, [
        {**c, "numero_normalizado": normalizar_telefone(c["numero"]) or c["numero"]} for c in canais if c["id"]])
    return await repo.salvar_integracao(id_escritorio, "helena", id_segredo_vault=id_segredo,
                                        final_segredo=_final(token), situacao="ok",
                                        config={"canais_encontrados": len(canais)})


@api.get("/integracoes")
async def ver_integracoes(pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    repo = _repo(pedido)
    integracoes, canais = await asyncio.gather(repo.integracoes(ctx.escritorio()), repo.canais(ctx.escritorio()))
    return {"integracoes": integracoes, "canais": canais,
            "url_webhook_configurada": bool(_url_webhook(pedido, ctx.escritorio())),
            "url_webhook_zapsign": url_do_escritorio(ctx.escritorio(), "zapsign"),
            "url_botao_ia": url_do_botao_ia(ctx.escritorio()),
            # segredo do link do Controle da IA (rotas_controle_ia /publico): sem ele o link não funciona
            "segredo_controle_ia": segredo_do_escritorio(ctx.escritorio(), "controle")}


@api.put("/integracoes/helena")
async def salvar_helena(dados: TokenHelena, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    repo = _repo(pedido)
    integracao = await _salvar_token_helena(pedido, repo, ctx.escritorio(), dados.token)
    await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=ctx.escritorio(),
                                   tabela="agentesia_integracoes", id_registro=integracao["id"], acao="conectou",
                                   resumo=f"Token da LawChat salvo (final {integracao['final_segredo']})")
    return {"integracao": integracao, "canais": await repo.canais(ctx.escritorio())}


def _url_webhook(pedido: Request, id_escritorio: str) -> str | None:
    """Cada escritório tem a própria URL (e o próprio segredo, derivado do id)."""
    return url_do_escritorio(id_escritorio)


@api.post("/integracoes/helena/conectar")
async def conectar_webhook(pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Cria ou corrige na Helena a assinatura que traz as mensagens para este servidor."""
    url = _url_webhook(pedido, ctx.escritorio())
    if not url:
        raise HTTPException(409, "O servidor ainda não tem endereço público (AGENTESIA_URL_PUBLICA e AGENTESIA_WEBHOOK_SEGREDO).")
    repo = _repo(pedido)
    helena = await _helena_do_escritorio(pedido, repo, ctx.escritorio())
    integracao = await repo.integracao(ctx.escritorio(), "helena") or {}
    try:
        assinatura = await helena.garantir_assinatura(url, (integracao.get("config") or {}).get("id_assinatura"))
    except ErroHelenaApi as erro:
        raise _erro_helena(erro) from erro
    await repo.salvar_integracao(ctx.escritorio(), "helena", situacao="ok",
                                 config={"id_assinatura": assinatura["id"], "webhook_conectado": True})
    await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=ctx.escritorio(),
                                   tabela="agentesia_integracoes", id_registro=integracao.get("id"), acao="conectou",
                                   resumo=f"Webhook da LawChat {assinatura['acao'].replace('_', ' ')}")
    assinatura.pop("url", None)                 # a URL leva o segredo: não volta para o navegador
    return {"assinatura": assinatura}


@api.post("/integracoes/helena/canais")
async def atualizar_canais(pedido: Request, ctx: Contexto = Depends(GESTAO)) -> list[dict[str, Any]]:
    repo = _repo(pedido)
    helena = await _helena_do_escritorio(pedido, repo, ctx.escritorio())
    try:
        canais = await helena.canais()
    except ErroHelenaApi as erro:
        raise _erro_helena(erro) from erro
    return await repo.sincronizar_canais(ctx.escritorio(), [
        {**c, "numero_normalizado": normalizar_telefone(c["numero"]) or c["numero"]} for c in canais if c["id"]])


@api.get("/integracoes/helena/paineis")
async def paineis_crm(pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    # Botão "Carregar painéis" da tela Integrações: sempre lê de novo (e renova a cópia das etiquetas).
    import asyncio
    paineis, etiquetas = await asyncio.gather(
        _consulta_helena(pedido, ctx.escritorio(), "paineis", lambda h: h.paineis(), recarregar=True),
        _consulta_helena(pedido, ctx.escritorio(), "etiquetas", lambda h: h.etiquetas(), recarregar=True))
    return {"paineis": paineis, "etiquetas": etiquetas}


@api.get("/integracoes/helena/etiquetas")
async def etiquetas_helena(pedido: Request, recarregar: bool = False, ctx: Contexto = Depends(GESTAO)) -> list[dict[str, Any]]:
    return await _consulta_helena(pedido, ctx.escritorio(), "etiquetas", lambda h: h.etiquetas(), recarregar)


@api.get("/integracoes/helena/equipes")
async def equipes_helena(pedido: Request, recarregar: bool = False, ctx: Contexto = Depends(GESTAO)) -> list[dict[str, Any]]:
    return await _consulta_helena(pedido, ctx.escritorio(), "equipes", lambda h: h.equipes(), recarregar)


@api.put("/integracoes/crm")
async def salvar_crm(dados: ConfigCrm, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    repo = _repo(pedido)
    antes = await repo.integracao(ctx.escritorio(), "crm")
    config = {"id_painel": dados.id_painel, "titulo_painel": dados.titulo_painel}
    integracao = await repo.salvar_integracao(ctx.escritorio(), "crm", situacao="ok", config=config)
    await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=ctx.escritorio(),
                                   tabela="agentesia_integracoes", id_registro=integracao["id"], acao="alterou",
                                   resumo="Painel do CRM da LawChat escolhido",
                                   antes=(antes or {}).get("config"), depois=config)
    return integracao


@api.put("/integracoes/openai")
async def salvar_openai(pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Chave própria da OpenAI (BYOK) saiu: a IA usa sempre a chave da LawChat e o consumo vira débito na carteira.
    Chave já salva fica onde está (não é apagada) e é ignorada."""
    raise HTTPException(410, "A chave própria da OpenAI não é mais usada: a IA usa a chave da LawChat e o consumo sai "
                             "do saldo do escritório.")


class TokenZapSign(BaseModel):
    token: str = Field(min_length=8)
    ambiente: str = "producao"


class ConfigZapSign(BaseModel):
    modelos: list[dict[str, Any]] | None = None
    # False (padrão): "modelos" traz os modelos GERAIS (tela Integrações) e/ou itens de produto a trocar;
    # os itens dos outros produtos ficam. True: "modelos" é a lista inteira e substitui a atual.
    lista_completa: bool = False
    limite_versoes: int | None = Field(default=None, ge=1, le=10)
    mensagens: dict[str, str] | None = None
    lembretes: dict[str, Any] | None = None
    midia_pos_assinatura: dict[str, Any] | None = None


async def _zapsign_do_escritorio(repo: RepositorioGestao, id_escritorio: str):
    from app.canal.zapsign import URL_PRODUCAO, URL_SANDBOX, ZapSign
    integracao = await repo.integracao(id_escritorio, "zapsign") or {}
    token = await repo.ler_segredo(integracao.get("id_segredo_vault"))
    if not token:
        raise HTTPException(409, "Cadastre o token da ZapSign.")
    ambiente = (integracao.get("config") or {}).get("ambiente")
    # Só para teste local (ZapSign de mentira em db/testes/helena_falsa.py); em produção a variável não existe.
    url_teste = os.environ.get("AGENTESIA_ZAPSIGN_URL_TESTE", "").strip()
    return ZapSign(token, url_teste or (URL_SANDBOX if ambiente == "sandbox" else URL_PRODUCAO))


@api.put("/integracoes/zapsign")
async def salvar_zapsign(dados: TokenZapSign, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Guarda o token no cofre e testa lendo os modelos da conta."""
    from app.canal.zapsign import ErroZapSign
    repo = _repo(pedido)
    atual = await repo.integracao(ctx.escritorio(), "zapsign")
    id_segredo = await repo.guardar_segredo(f"agentesia_zapsign_{ctx.escritorio()}", dados.token.strip(),
                                            (atual or {}).get("id_segredo_vault"))
    ambiente = "sandbox" if dados.ambiente == "sandbox" else "producao"
    await repo.salvar_integracao(ctx.escritorio(), "zapsign", id_segredo_vault=id_segredo, final_segredo=_final(dados.token),
                                 situacao="pendente", config={"ambiente": ambiente})
    try:
        modelos = await (await _zapsign_do_escritorio(repo, ctx.escritorio())).modelos()
        integracao = await repo.salvar_integracao(ctx.escritorio(), "zapsign", situacao="ok", config={"modelos_na_conta": len(modelos)})
    except ErroZapSign as erro:
        integracao = await repo.salvar_integracao(ctx.escritorio(), "zapsign", situacao="erro",
                                                  erro={"chave": "A ZapSign recusou o token.", "pagamento": "A conta da ZapSign está com pagamento pendente."}
                                                  .get(erro.motivo, f"A ZapSign não respondeu ({erro.motivo})."))
    await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=ctx.escritorio(), tabela="agentesia_integracoes",
                                   id_registro=integracao["id"], acao="conectou",
                                   resumo=f"Token da ZapSign salvo (final {integracao['final_segredo']}): {integracao['situacao']}")
    return integracao


@api.get("/integracoes/zapsign/modelos")
async def modelos_zapsign(pedido: Request, id_modelo: str | None = None, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Modelos da conta; com id_modelo, também as variáveis dele (para ligar aos dados do lead)."""
    from app.canal.zapsign import ErroZapSign
    from app.contrato import dados as cdados
    zapsign = await _zapsign_do_escritorio(_repo(pedido), ctx.escritorio())
    try:
        resposta: dict[str, Any] = {"modelos": await zapsign.modelos()}
        if id_modelo:
            resposta["variaveis"] = await zapsign.variaveis_do_modelo(id_modelo)
    except ErroZapSign as erro:
        raise HTTPException(502, f"A ZapSign respondeu com erro ({erro.motivo}).") from erro
    resposta["campos"] = {**{k: cdados.PEDIR.get(k, k) for k in cdados.CAMPOS},
                          "@data_geracao": "data e hora da geração", "@fixo": "texto fixo"}
    resposta["mapeamento_padrao"] = cdados.MAPEAMENTO_PADRAO
    return resposta


def _normalizar_modelos(enviados: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from app.contrato import modelos as cmodelos
    try:
        return [m for m in (cmodelos.normalizar(x) for x in enviados) if m]
    except cmodelos.ModeloInvalido as erro:
        raise HTTPException(400, str(erro)) from erro


async def _mudar_config_zapsign(repo: RepositorioGestao, id_escritorio: str, mudar,
                                ao_travar=None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Lê e grava a config da ZapSign com a linha travada: dois salvamentos ao mesmo tempo (produto A e
    produto B) não apagam um ao outro. mudar(config) devolve a config nova. Devolve (config antes, integração).
    ao_travar(conexao), se vier, roda logo depois da trava (para reler o que a ativação pode ter mudado)."""
    from app.gestao.repositorio import _j, _linha
    async with repo.pool.acquire() as conexao, conexao.transaction():
        linha = _linha(await conexao.fetchrow(
            "select * from agentesia_integracoes where id_escritorio = $1::uuid and tipo = 'zapsign' for update", id_escritorio))
        if not linha:
            raise HTTPException(409, "Cadastre o token da ZapSign antes.")
        if ao_travar is not None:
            await ao_travar(conexao)
        antes = dict(linha.get("config") or {})
        integracao = _linha(await conexao.fetchrow(
            "update agentesia_integracoes set config = $2::jsonb where id = $1::uuid returning *",
            linha["id"], _j(mudar(dict(antes)))))
    return antes, integracao  # type: ignore[return-value]


@api.put("/integracoes/zapsign/config")
async def configurar_zapsign(dados: ConfigZapSign, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Configuração do contrato do escritório (tela Integrações > ZapSign).

    "modelos" NÃO apaga o modelo de outro produto: sem lista_completa, os itens gerais enviados trocam
    os gerais e um item de produto troca só o daquele produto. O modelo de UM produto se grava em
    PUT /integracoes/zapsign/produtos/{id_ativado}."""
    from app.contrato import dados as cdados
    from app.contrato import modelos as cmodelos
    repo = _repo(pedido)
    config: dict[str, Any] = {}
    enviados = _normalizar_modelos(dados.modelos) if dados.modelos is not None else None
    if dados.limite_versoes is not None:
        config["limite_versoes"] = dados.limite_versoes
    if dados.mensagens is not None:
        config["mensagens"] = {k: v.strip() for k, v in dados.mensagens.items() if k in cdados.TEXTOS and v.strip()}
    if dados.lembretes is not None:
        horas = sorted({float(h) for h in dados.lembretes.get("horas") or [] if 0.5 <= float(h) <= 240})[:5]
        config["lembretes"] = {"ativo": bool(dados.lembretes.get("ativo", True)), "horas": horas}
    if dados.midia_pos_assinatura is not None:
        url = str(dados.midia_pos_assinatura.get("url") or "").strip()
        if url and not url.startswith("https://"):
            raise HTTPException(400, "O vídeo pós-assinatura precisa ser um link https.")
        config["midia_pos_assinatura"] = {"url": url or None}

    def mudar(atual: dict[str, Any]) -> dict[str, Any]:
        novo = {**atual, **config}
        if enviados is not None:
            novo["modelos"] = cmodelos.juntar_da_tela(atual.get("modelos"), enviados, dados.lista_completa)
        return novo

    antes, integracao = await _mudar_config_zapsign(repo, ctx.escritorio(), mudar)
    await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=ctx.escritorio(), tabela="agentesia_integracoes",
                                   id_registro=integracao["id"], acao="alterou", resumo="Configuração do contrato (ZapSign) alterada",
                                   antes=antes, depois=integracao.get("config"))
    return integracao


@api.post("/integracoes/zapsign/aviso-assinatura")
async def conectar_aviso_assinatura(pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Cadastra na conta ZapSign do escritório o aviso (webhook) que chega em /webhook/zapsign/{id}.
    Uma vez só por escritório: se já está cadastrado, devolve o que existe. A senha vai em cabeçalho."""
    from app.canal.webhook import segredo_do_escritorio
    from app.canal.zapsign import ErroZapSign
    repo = _repo(pedido)
    integracao = await repo.integracao(ctx.escritorio(), "zapsign")
    if not integracao:
        raise HTTPException(409, "Cadastre o token da ZapSign antes.")
    atual = (integracao.get("config") or {}).get("webhook_id")
    if atual:
        return {"webhook_id": atual, "ja_existia": True}
    url = url_do_escritorio(ctx.escritorio(), "zapsign")
    segredo = segredo_do_escritorio(ctx.escritorio(), "zapsign")
    if not url or not segredo:
        raise HTTPException(409, "O servidor ainda não tem endereço público (AGENTESIA_URL_PUBLICA e AGENTESIA_WEBHOOK_SEGREDO).")
    zapsign = await _zapsign_do_escritorio(repo, ctx.escritorio())
    try:
        ident = await zapsign.criar_webhook(url.split("?", 1)[0], {"x-agentesia-segredo": segredo})
    except ErroZapSign as erro:
        raise HTTPException(502, f"A ZapSign não aceitou o cadastro do aviso ({erro.motivo}).") from erro
    from datetime import datetime, timezone
    marca = ident or "cadastrado"

    def mudar(cfg: dict[str, Any]) -> dict[str, Any]:
        return {**cfg, "webhook_id": cfg.get("webhook_id") or marca,
                "webhook_em": cfg.get("webhook_em") or datetime.now(timezone.utc).isoformat()}

    antes, integracao = await _mudar_config_zapsign(repo, ctx.escritorio(), mudar)
    await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=ctx.escritorio(), tabela="agentesia_integracoes",
                                   id_registro=integracao["id"], acao="conectou",
                                   resumo="Aviso de assinatura da ZapSign cadastrado na conta",
                                   antes={"webhook_id": antes.get("webhook_id")},
                                   depois={"webhook_id": (integracao.get("config") or {}).get("webhook_id")})
    return {"webhook_id": (integracao.get("config") or {}).get("webhook_id"), "ja_existia": False}


class ContratoDoProduto(BaseModel):
    id_modelo: str = Field(min_length=1, max_length=200)
    nome: str | None = None
    mapeamento: list[dict[str, Any]] | None = None
    obrigatorios: list[str] | None = None


async def _produto_ativado(repo: RepositorioGestao, id_escritorio: str, id_ativado: str) -> dict[str, Any]:
    """O produto ativado (ou rascunho) do escritório: id e o id_agente, que só existe depois de ativar."""
    import uuid as _uuid
    try:
        _uuid.UUID(id_ativado)
    except ValueError as erro:
        raise HTTPException(404, "Produto não encontrado.") from erro
    linha = await repo.pool.fetchrow(
        "select id, id_agente, nome from agentesia_produtos_ativados where id = $1::uuid and id_escritorio = $2::uuid",
        id_ativado, id_escritorio)
    if not linha:
        raise HTTPException(404, "Produto não encontrado.")
    return {"id": str(linha["id"]), "id_agente": str(linha["id_agente"]) if linha["id_agente"] else None, "nome": linha["nome"]}


@api.get("/integracoes/zapsign/produtos/{id_ativado}")
async def contrato_do_produto(id_ativado: str, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """O modelo de contrato DESTE produto (modelo) e o padrão do escritório, que vale enquanto ele não tem um."""
    from app.contrato import modelos as cmodelos
    repo = _repo(pedido)
    produto = await _produto_ativado(repo, ctx.escritorio(), id_ativado)
    modelos = ((await repo.integracao(ctx.escritorio(), "zapsign") or {}).get("config") or {}).get("modelos")
    proprio = cmodelos.modelo_do_produto(modelos, produto["id"], produto["id_agente"])
    padrao = cmodelos.padrao(modelos)
    return {"modelo": proprio, "padrao": None if proprio is not None and padrao is proprio else padrao}


@api.put("/integracoes/zapsign/produtos/{id_ativado}")
async def salvar_contrato_do_produto(id_ativado: str, dados: ContratoDoProduto, pedido: Request,
                                     ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Grava o modelo de contrato de UM produto: mexe só no item dele, nunca no dos outros."""
    from app.contrato import modelos as cmodelos
    repo = _repo(pedido)
    produto = await _produto_ativado(repo, ctx.escritorio(), id_ativado)
    normalizados = _normalizar_modelos([dados.model_dump()])
    if not normalizados:
        raise HTTPException(400, "Escolha um modelo.")
    novo = normalizados[0]

    async def reler_produto(conexao: Any) -> None:
        # Com a linha da ZapSign travada: a ativação que terminou no meio tempo já gravou o id_agente
        # (sem isso o item ficaria só com id_ativado e o motor não o acharia). Produto excluído: 404.
        linha = await conexao.fetchrow("select id_agente from agentesia_produtos_ativados where id = $1::uuid and id_escritorio = $2::uuid",
                                       produto["id"], ctx.escritorio())
        if not linha:
            raise HTTPException(404, "Produto não encontrado.")
        produto["id_agente"] = str(linha["id_agente"]) if linha["id_agente"] else None

    def mudar(atual: dict[str, Any]) -> dict[str, Any]:
        return {**atual, "modelos": cmodelos.salvar_do_produto(atual.get("modelos"), novo, produto["id"], produto["id_agente"])}

    antes, integracao = await _mudar_config_zapsign(repo, ctx.escritorio(), mudar, ao_travar=reler_produto)
    modelos = (integracao.get("config") or {}).get("modelos")
    await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=ctx.escritorio(), tabela="agentesia_integracoes",
                                   id_registro=integracao["id"], acao="alterou",
                                   resumo=f"Contrato (ZapSign) do produto {produto['nome']}: modelo {novo['nome']}",
                                   antes={"modelos": antes.get("modelos")}, depois={"modelos": modelos})
    return {"modelo": cmodelos.modelo_do_produto(modelos, produto["id"], produto["id_agente"])}


# ============================================================================ agentes
class NovoAgente(BaseModel):
    nome: str = Field(min_length=2, max_length=60)
    id_canal: str
    produto: str = "auxilio_acidente"
    modelo: str = "gpt-4.1-mini"
    definicao: dict[str, Any] | None = None   # só no agente próprio
    id_modelo: str | None = None               # modelo da biblioteca escolhido no assistente
    espera_s: int | None = Field(default=None, ge=0, le=120)          # tempo antes de responder
    minutos_pausa_humano: int | None = Field(default=None, ge=0, le=10080)
    pausa_sem_volta: bool | None = None        # atendente falou: IA só volta quando a equipe religar
    conhecimento: dict[str, Any] | None = None # faq, objecoes, dados_escritorio
    instrucoes: dict[str, str] | None = None   # instrução por etapa (vazio = padrão)
    funcoes: dict[str, bool] | None = None
    honorarios: str | None = None
    numeros_teste: list[str] | None = None


def _limpar_conhecimento(bruto: dict[str, Any]) -> dict[str, Any]:
    """FAQ, objeções e dados do escritório da aba Conhecimento. Cada item pode ter `papeis` (vazio = todos os papéis).
    Sem o corte antigo de 40 FAQ / 30 objeções: o que não cabe fixo no prompt vai para a busca (app/conhecimento.py).
    Mantém os limites da busca do agente (teto_documentos, trechos_por_turno, nota_minima) quando vierem."""
    from app import conhecimento as base

    def com_papeis(item: dict[str, Any], limpo: dict[str, Any]) -> dict[str, Any]:
        papeis = base.papeis_validos(item.get("papeis"))
        return {**limpo, "papeis": papeis} if papeis else limpo

    faq = [com_papeis(f, {"pergunta": str(f.get("pergunta") or "").strip()[:300], "resposta": str(f.get("resposta") or "").strip()[:1500]})
           for f in bruto.get("faq") or [] if isinstance(f, dict) and str(f.get("pergunta") or "").strip()][:base.LIMITE_FAQ]
    objecoes = [com_papeis(o, {"objecao": str(o.get("objecao") or "").strip()[:300], "resposta": str(o.get("resposta") or "").strip()[:1500]})
                for o in bruto.get("objecoes") or [] if isinstance(o, dict) and str(o.get("objecao") or "").strip()][:base.LIMITE_OBJECOES]
    limpo: dict[str, Any] = {"faq": faq, "objecoes": objecoes,
                             "dados_escritorio": str(bruto.get("dados_escritorio") or "").strip()[:4000]}
    if honorarios := str(bruto.get("honorarios") or "").strip():
        limpo["honorarios"] = honorarios[:6000]      # honorários do produto (transcrição do áudio), vindos da ativação
    for chave, menor, maior in (("teto_documentos", base.TETO_MINIMO, base.TETO_MAXIMO), ("trechos_por_turno", 1, 8),
                                ("nota_minima", 0.0, 0.95)):
        valor = bruto.get(chave)
        if isinstance(valor, (int, float)) and not isinstance(valor, bool):
            limpo[chave] = type(menor)(max(menor, min(valor, maior)))
    return limpo


async def _sincronizar_base(pedido: Request, repo: Any, id_escritorio: str, id_agente: str,
                            conhecimento: dict[str, Any] | None) -> None:
    """FAQ/objeções mudaram: os documentos virtuais voltam para 'processando' (reindexa só o que mudou, pelo hash)."""
    from app.conhecimento_indice import sincronizar_virtuais

    pool = getattr(repo, "pool", None)
    if pool is None:
        return
    try:
        if await sincronizar_virtuais(pool, id_escritorio, id_agente, conhecimento):
            sinal = getattr(pedido.app.state, "indexar_agora", None)
            if sinal is not None:
                sinal.set()
    except Exception:                                  # noqa: BLE001 - sem a migração 003 a busca usa só a config
        import logging
        logging.getLogger("agentesia").warning("não deu para sincronizar a base do agente %s", id_agente, exc_info=True)


class AlterarAgente(BaseModel):
    nome: str | None = Field(default=None, min_length=2, max_length=60)
    espera_s: int | None = Field(default=None, ge=0, le=120)
    pausa_sem_volta: bool | None = None
    conhecimento: dict[str, Any] | None = None
    modelo: str | None = None
    honorarios: str | None = None
    minutos_pausa_humano: int | None = Field(default=None, ge=0, le=10080)
    numeros_teste: list[str] | None = None
    id_canal: str | None = None
    funcoes: dict[str, bool] | None = None
    id_equipe_transferencia: str | None = None


class AlterarEtapa(BaseModel):
    instrucao: str | None = None          # vazio = volta ao padrão
    travada: bool | None = None


class Ativacao(BaseModel):
    situacao: str                          # ativo | pausado
    modo: str | None = None                # teste | producao


def _produto_do(agente: dict[str, Any]) -> produtos.Produto:
    try:
        return produtos.carregar(agente.get("produto"), agente.get("config") or {})
    except ValueError:                        # definição salva ficou inválida: mostra a inicial
        return produtos.carregar("proprio", {"definicao": DEFINICAO_INICIAL})


def _validar_definicao(dados: dict[str, Any]) -> Definicao:
    from pydantic import ValidationError
    try:
        return Definicao.model_validate(dados)
    except ValidationError as erro:
        primeiro = erro.errors()[0]
        raise HTTPException(400, "Definição do agente inválida: " + str(primeiro.get("msg", "")).replace("Value error, ", ""))


def _agente_para_tela(agente: dict[str, Any]) -> dict[str, Any]:
    config = agente.get("config") or {}
    produto = _produto_do(agente)
    etapas_produto = {e.codigo: e for e in produto.etapas}
    agente["tipo_produto"] = "proprio" if agente.get("produto") == "proprio" else "pronto"
    agente["definicao"] = config.get("definicao") if agente["tipo_produto"] == "proprio" else None
    agente["gatilhos"] = automacoes.gatilhos_do_produto(produto)
    agente["modelo"] = (config.get("modelos") or {}).get("etapa") or "gpt-4.1"
    agente["honorarios"] = config.get("honorarios") or ""
    agente["funcoes"] = {f["id"]: bool((config.get("funcoes") or {}).get(f["id"])) for f in FUNCOES}
    agente["id_equipe_transferencia"] = config.get("id_equipe_transferencia")
    agente["automacoes"] = config.get("automacoes") or {}
    agente["ultima_preparacao"] = config.get("ultima_preparacao")
    from app.followup import padrao as padrao_fu
    situacao_fu = padrao_fu.situacao(config)          # sem config: desligado e a cadência padrão (4 toques), não "7"
    agente["followup_resumo"] = {"ativo": situacao_fu["ligado"], "passos": situacao_fu["passos"], "resumo": situacao_fu["resumo"]}
    agente["espera_s"] = config.get("espera_s")
    agente["pausa_sem_volta"] = bool(config.get("pausa_sem_volta"))
    agente["conhecimento"] = config.get("conhecimento") or {"faq": [], "objecoes": [], "dados_escritorio": ""}
    for etapa in agente.get("etapas", []):
        da_definicao = etapas_produto.get(etapa["codigo"])
        etapa["nome"] = da_definicao.nome if da_definicao else NOMES_ETAPAS.get(etapa["codigo"], etapa["codigo"])
        etapa["instrucao_padrao"] = agente_ia.instrucao_padrao(etapa["codigo"], produto)
        etapa["personalizada"] = bool(etapa.get("instrucao"))
    return agente


@api.get("/agentes")
async def listar_agentes(pedido: Request, ctx: Contexto = Depends(TODOS)) -> list[dict[str, Any]]:
    return [_agente_para_tela(a) for a in await _repo(pedido).agentes(ctx.escritorio())]


@api.get("/agentes/{id_agente}")
async def ver_agente(id_agente: str, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    agente = await _repo(pedido).agente(ctx.escritorio(), id_agente)
    if not agente:
        raise HTTPException(404, "Agente não encontrado.")
    return _agente_para_tela(agente)


@api.post("/agentes")
async def criar_agente(dados: NovoAgente, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    repo = _repo(pedido)
    modelo_biblioteca = None
    if dados.id_modelo:
        modelo_biblioteca = await repo.modelo(dados.id_modelo)
        if not modelo_biblioteca or (modelo_biblioteca["situacao"] != "publicado" and not ctx.admin):
            raise HTTPException(404, "Modelo de agente não encontrado.")
        dados.produto = modelo_biblioteca["produto"]
        base = modelo_biblioteca.get("config") or {}
        dados.definicao = base.get("definicao") if dados.produto == "proprio" else None
        if base.get("modelo_ia") in IDS_MODELOS and dados.modelo == "gpt-4.1-mini":
            dados.modelo = base["modelo_ia"]
    if dados.modelo not in IDS_MODELOS:
        raise HTTPException(400, "Modelo de IA desconhecido.")
    if dados.produto not in {p["id"] for p in PRODUTOS}:
        raise HTTPException(400, "Produto desconhecido.")
    canal = next((c for c in await repo.canais(ctx.escritorio()) if c["id"] == dados.id_canal), None)
    if not canal or not canal["ativo"]:
        raise HTTPException(400, "Escolha um número de WhatsApp ativo deste escritório.")
    if canal["id_agente"]:
        raise HTTPException(409, f"Este número já tem o agente {canal['nome_agente']}.")
    escritorio = await repo.escritorio(ctx.escritorio()) or {}
    config: dict[str, Any] = {"modelos": {"extrator": dados.modelo, "etapa": dados.modelo},
                              "honorarios": (escritorio.get("config") or {}).get("honorarios")}
    if dados.produto == "proprio":
        config["definicao"] = _validar_definicao(dados.definicao or DEFINICAO_INICIAL).model_dump()
    if modelo_biblioteca:
        base = modelo_biblioteca.get("config") or {}
        if base.get("honorarios"):
            config["honorarios"] = base["honorarios"]
        config["funcoes"] = {k: bool(v) for k, v in (base.get("funcoes") or {}).items()}
    if dados.espera_s is not None:
        config["espera_s"] = dados.espera_s
    if dados.pausa_sem_volta is not None:
        config["pausa_sem_volta"] = dados.pausa_sem_volta
    if dados.conhecimento is not None:
        config["conhecimento"] = _limpar_conhecimento(dados.conhecimento)
    if dados.honorarios is not None:
        config["honorarios"] = dados.honorarios.strip() or None
    if dados.funcoes is not None:
        prontas = {f["id"] for f in FUNCOES if f["pronta"]}
        config["funcoes"] = {**(config.get("funcoes") or {}), **{k: bool(v) for k, v in dados.funcoes.items() if k in prontas}}
    produto = produtos.carregar(dados.produto, config)
    if modelo_biblioteca:
        # Automações do modelo vêm sem coluna do CRM: cada escritório tem o próprio painel.
        sem_coluna = {g: {k: v for k, v in r.items() if k != "coluna_crm"}
                      for g, r in ((modelo_biblioteca.get("config") or {}).get("automacoes") or {}).items()}
        config["automacoes"] = automacoes.validar(sem_coluna, automacoes.gatilhos_do_produto(produto))
    agente = await repo.criar_agente(id_escritorio=ctx.escritorio(), id_canal=dados.id_canal,
                                     nome=dados.nome.strip(), produto=dados.produto, config=config,
                                     etapas=[(e.codigo, e.tipo) for e in produto.etapas])
    if modelo_biblioteca:
        await repo.aplicar_instrucoes(agente["id"], (modelo_biblioteca.get("config") or {}).get("instrucoes") or {})
        await repo.marcar_modelo(agente["id"], modelo_biblioteca["id"])
    if dados.instrucoes:
        codigos = {e.codigo for e in produto.etapas}
        await repo.aplicar_instrucoes(agente["id"], {k: v.strip() for k, v in dados.instrucoes.items()
                                                     if k in codigos and v.strip() and v.strip() != agente_ia.instrucao_padrao(k, produto).strip()})
    extras: dict[str, Any] = {}
    if dados.minutos_pausa_humano is not None:
        extras["minutos_pausa_humano"] = dados.minutos_pausa_humano
    if dados.numeros_teste:
        numeros = [normalizar_telefone(n) for n in dados.numeros_teste if n.strip()]
        if any(n is None for n in numeros):
            raise HTTPException(400, "Algum número de teste está inválido.")
        extras["numeros_teste"] = sorted(set(numeros))  # type: ignore[arg-type]
    if extras:
        await repo.alterar_agente(ctx.escritorio(), agente["id"], extras)
    agente = await repo.agente(ctx.escritorio(), agente["id"]) or agente
    if dados.conhecimento is not None:
        await _sincronizar_base(pedido, repo, ctx.escritorio(), agente["id"], config.get("conhecimento"))
    await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=ctx.escritorio(), tabela="agentesia_agentes",
                                   id_registro=agente["id"], acao="criou",
                                   resumo=f"Agente {agente['nome']} criado no número {canal['numero_normalizado']}")
    return _agente_para_tela(agente)


@api.patch("/agentes/{id_agente}")
async def alterar_agente(id_agente: str, dados: AlterarAgente, pedido: Request,
                         ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    repo = _repo(pedido)
    antes = await repo.agente(ctx.escritorio(), id_agente)
    if not antes:
        raise HTTPException(404, "Agente não encontrado.")
    campos: dict[str, Any] = {}
    config = dict(antes.get("config") or {})
    if dados.nome is not None:
        campos["nome"] = dados.nome.strip()
    if dados.minutos_pausa_humano is not None:
        campos["minutos_pausa_humano"] = dados.minutos_pausa_humano
    if dados.numeros_teste is not None:
        numeros = [normalizar_telefone(n) for n in dados.numeros_teste if n.strip()]
        if any(n is None for n in numeros):
            raise HTTPException(400, "Algum número de teste está inválido.")
        campos["numeros_teste"] = sorted(set(numeros))  # type: ignore[arg-type]
    if dados.modelo is not None:
        if dados.modelo not in IDS_MODELOS:
            raise HTTPException(400, "Modelo de IA desconhecido.")
        config["modelos"] = {"extrator": dados.modelo, "etapa": dados.modelo}
    if dados.honorarios is not None:
        config["honorarios"] = dados.honorarios.strip() or None
    if dados.espera_s is not None:
        config["espera_s"] = dados.espera_s or None
    if dados.pausa_sem_volta is not None:
        config["pausa_sem_volta"] = dados.pausa_sem_volta
    if dados.conhecimento is not None:
        # Os honorários do produto (vindos da ativação) ficam quando a aba Conhecimento não os manda.
        config["conhecimento"] = _limpar_conhecimento(
            {"honorarios": (config.get("conhecimento") or {}).get("honorarios"), **dados.conhecimento})
    if dados.funcoes is not None:
        prontas = {f["id"] for f in FUNCOES if f["pronta"]}
        config["funcoes"] = {k: bool(v) for k, v in dados.funcoes.items() if k in prontas}
        contrato_antes = bool(((antes.get("config") or {}).get("funcoes") or {}).get("contrato_zapsign"))
        if bool(config["funcoes"].get("contrato_zapsign")) != contrato_antes and antes.get("produto") != "proprio":
            # Liga ou desliga as etapas "Assinatura do contrato" e "Contrato assinado" no agente.
            em_uso = await repo.sincronizar_etapas(id_agente, [(e.codigo, e.tipo) for e in produtos.carregar(antes.get("produto"), config).etapas])
            if em_uso:
                raise HTTPException(409, "Há leads nas etapas de contrato (" + ", ".join(em_uso) + "): conclua ou mova antes de desligar.")
    if dados.id_equipe_transferencia is not None:
        config["id_equipe_transferencia"] = dados.id_equipe_transferencia or None
    if dados.id_canal is not None and dados.id_canal != antes["id_canal"]:
        canal = next((c for c in await repo.canais(ctx.escritorio()) if c["id"] == dados.id_canal), None)
        if not canal or not canal["ativo"] or canal["id_agente"]:
            raise HTTPException(400, "Este número não está livre.")
        campos["id_canal"] = dados.id_canal
    if config != (antes.get("config") or {}):
        campos["config"] = config
    await repo.alterar_agente(ctx.escritorio(), id_agente, campos)
    if dados.conhecimento is not None:
        await _sincronizar_base(pedido, repo, ctx.escritorio(), id_agente, config.get("conhecimento"))
    depois = await repo.agente(ctx.escritorio(), id_agente)
    await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=ctx.escritorio(), tabela="agentesia_agentes",
                                   id_registro=id_agente, acao="alterou", resumo=f"Agente {antes['nome']} alterado",
                                   antes={k: antes.get(k) for k in campos}, depois={k: (depois or {}).get(k) for k in campos})
    return _agente_para_tela(depois or {})


@api.put("/agentes/{id_agente}/etapas/{codigo}")
async def alterar_etapa(id_agente: str, codigo: str, dados: AlterarEtapa, pedido: Request,
                        ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    # A instrução (prompt por etapa) é da equipe LawChat: o escritório não vê nem edita essa tela.
    if not ctx.admin:
        raise HTTPException(403, "Só a equipe LawChat edita as instruções do agente.")
    repo = _repo(pedido)
    agente = await repo.agente(ctx.escritorio(), id_agente)
    etapa = next((e for e in (agente or {}).get("etapas", []) if e["codigo"] == codigo), None)
    if not agente or not etapa:
        raise HTTPException(404, "Etapa não encontrada.")
    if etapa["instrucao_travada"] and not ctx.admin:
        raise HTTPException(403, "Esta instrução foi travada pela equipe LawChat. Fale com o suporte para mudar.")
    if dados.travada is not None and not ctx.admin:
        raise HTTPException(403, "Só a equipe LawChat trava instruções.")
    texto = (dados.instrucao or "").strip()
    padrao = agente_ia.instrucao_padrao(codigo, _produto_do(agente)).strip()
    nova = None if not texto or texto == padrao else texto
    if nova and len(nova) > 12000:
        raise HTTPException(400, "Instrução longa demais (máximo 12 mil caracteres).")
    depois = await repo.alterar_etapa(id_agente, codigo, instrucao=nova, travada=dados.travada)
    await repo.registrar_alteracao(
        id_usuario=ctx.id_usuario, id_escritorio=ctx.escritorio(), tabela="agentesia_agente_etapas",
        id_registro=etapa["id"], acao="alterou",
        resumo=f"Instrução da etapa {etapa['codigo']} de {agente['nome']} "
               + ("voltou ao padrão" if nova is None else "personalizada"),
        antes={"instrucao": etapa["instrucao"], "travada": etapa["instrucao_travada"]},
        depois={"instrucao": nova, "travada": (depois or {}).get("instrucao_travada")})
    return {**(depois or {}), "instrucao_padrao": padrao}


async def _preparar(pedido: Request, repo: RepositorioGestao, id_escritorio: str, agente: dict[str, Any],
                    modo: str, aplicar: bool) -> ativacao.Resultado:
    return await ativacao.preparar(
        repo=repo, id_escritorio=id_escritorio, agente=agente, modo=modo, aplicar=aplicar,
        helena_de=lambda id_esc: _helena_do_escritorio(pedido, repo, id_esc),
        http=getattr(pedido.app.state, "http_ativacao", None))


@api.get("/agentes/{id_agente}/ativacao/checagem")
async def checar_ativacao(id_agente: str, pedido: Request, modo: str | None = None,
                          ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Confere tudo o que a ativação precisa, sem mudar nada na Helena."""
    repo = _repo(pedido)
    agente = await repo.agente(ctx.escritorio(), id_agente)
    if not agente:
        raise HTTPException(404, "Agente não encontrado.")
    return (await _preparar(pedido, repo, ctx.escritorio(), agente, modo or agente["modo"], aplicar=False)).como_dict()


@api.post("/agentes/{id_agente}/ativacao/preparar")
async def preparar_ativacao(id_agente: str, pedido: Request, modo: str | None = None,
                            ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Faz o que dá para fazer sozinho (sincroniza o número, cria ou corrige o webhook) e mostra o que falta."""
    repo = _repo(pedido)
    agente = await repo.agente(ctx.escritorio(), id_agente)
    if not agente:
        raise HTTPException(404, "Agente não encontrado.")
    resultado = await _preparar(pedido, repo, ctx.escritorio(), agente, modo or agente["modo"], aplicar=True)
    await _guardar_preparacao(repo, ctx, agente, resultado)
    return resultado.como_dict()


async def _guardar_preparacao(repo: RepositorioGestao, ctx: Contexto, agente: dict[str, Any],
                              resultado: ativacao.Resultado) -> None:
    config = {**(agente.get("config") or {}), "ultima_preparacao": {**resultado.como_dict(), "por": ctx.usuario["nome"]}}
    await repo.alterar_agente(ctx.escritorio(), agente["id"], {"config": config})
    feitos = [p.detalhe for p in resultado.passos if p.situacao == "feito"]
    if feitos:
        await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=ctx.escritorio(),
                                       tabela="agentesia_agentes", id_registro=agente["id"], acao="preparou",
                                       resumo=f"Ativação de {agente['nome']}: " + "; ".join(feitos))


@api.post("/agentes/{id_agente}/ativacao")
async def ativar_agente(id_agente: str, dados: Ativacao, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Pausar é imediato. Ativar roda a preparação completa (Helena, número, webhook, CRM, chave de IA)
    e só liga se nada estiver com erro."""
    if dados.situacao not in ("ativo", "pausado") or dados.modo not in (None, "teste", "producao"):
        raise HTTPException(400, "Situação ou modo inválido.")
    repo = _repo(pedido)
    agente = await repo.agente(ctx.escritorio(), id_agente)
    if not agente:
        raise HTTPException(404, "Agente não encontrado.")
    if agente["situacao"] == "arquivado":
        raise HTTPException(409, "Este agente está arquivado. Restaure em Meus agentes antes de ligar ou pausar.")
    preparacao: dict[str, Any] | None = None
    if dados.situacao == "ativo":
        modo = dados.modo or agente["modo"]
        resultado = await _preparar(pedido, repo, ctx.escritorio(), agente, modo, aplicar=True)
        await _guardar_preparacao(repo, ctx, agente, resultado)
        if not resultado.pronto:
            raise HTTPException(409, "Antes de ativar, falta: " + "; ".join(resultado.pendencias) + ".")
        preparacao = resultado.como_dict()
        agente = await repo.agente(ctx.escritorio(), id_agente) or agente
    campos: dict[str, Any] = {"situacao": dados.situacao}
    if dados.modo:
        campos["modo"] = dados.modo
    await repo.alterar_agente(ctx.escritorio(), id_agente, campos)
    acao = "pausou" if dados.situacao == "pausado" else ("ativou_producao" if dados.modo == "producao" else "ativou")
    await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=ctx.escritorio(), tabela="agentesia_agentes",
                                   id_registro=id_agente, acao=acao,
                                   resumo=f"Agente {agente['nome']}: {dados.situacao}" + (f" em {dados.modo}" if dados.modo else ""),
                                   antes={"situacao": agente["situacao"], "modo": agente["modo"]}, depois=campos)
    tela = _agente_para_tela(await repo.agente(ctx.escritorio(), id_agente) or {})
    if preparacao:
        tela["preparacao"] = preparacao
    return tela


class Automacoes(BaseModel):
    automacoes: dict[str, dict[str, Any]]


class NovaDefinicao(BaseModel):
    definicao: dict[str, Any]


@api.get("/produtos/{codigo}/etapas")
async def etapas_do_produto(codigo: str, contrato: bool = False, _: Contexto = Depends(GESTAO)) -> list[dict[str, Any]]:
    """Etapas e instrução padrão de cada uma, para o assistente mostrar antes de criar o agente."""
    if codigo not in {p["id"] for p in PRODUTOS} or codigo == "proprio":
        raise HTTPException(404, "Produto sem etapas fixas.")
    produto = produtos.carregar(codigo, {"funcoes": {"contrato_zapsign": contrato}})
    return [{"codigo": e.codigo, "nome": e.nome, "tipo": e.tipo, "instrucao_padrao": agente_ia.instrucao_padrao(e.codigo, produto)}
            for e in produto.etapas]


@api.get("/modelo-inicial-proprio")
async def modelo_inicial(_: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    return DEFINICAO_INICIAL


@api.put("/agentes/{id_agente}/definicao")
async def salvar_definicao(id_agente: str, dados: NovaDefinicao, pedido: Request,
                           ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Campos, etapas e regras do agente próprio. Vale também com o agente rodando."""
    repo = _repo(pedido)
    agente = await repo.agente(ctx.escritorio(), id_agente)
    if not agente:
        raise HTTPException(404, "Agente não encontrado.")
    if agente["produto"] != "proprio":
        raise HTTPException(400, "Agentes prontos têm as etapas definidas pela LawChat.")
    definicao = _validar_definicao(dados.definicao)
    em_uso = await repo.sincronizar_etapas(id_agente, [(e.codigo, e.tipo) for e in definicao.etapas])
    if em_uso:
        raise HTTPException(409, "Há conversas paradas nestas etapas, que por isso não podem sair: " + ", ".join(em_uso))
    antes = (agente.get("config") or {}).get("definicao")
    config = {**(agente.get("config") or {}), "definicao": definicao.model_dump()}
    produto = produtos.carregar("proprio", config)
    config["automacoes"] = automacoes.validar(config.get("automacoes") or {}, automacoes.gatilhos_do_produto(produto))
    await repo.alterar_agente(ctx.escritorio(), id_agente, {"config": config})
    await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=ctx.escritorio(), tabela="agentesia_agentes",
                                   id_registro=id_agente, acao="alterou",
                                   resumo=f"Campos, etapas e regras de {agente['nome']} alterados",
                                   antes=antes, depois=config["definicao"])
    return _agente_para_tela(await repo.agente(ctx.escritorio(), id_agente) or {})


@api.put("/agentes/{id_agente}/automacoes")
async def salvar_automacoes(id_agente: str, dados: Automacoes, pedido: Request,
                            ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Regras "quando isto acontecer, faça aquilo". Valem também para agentes que já estão rodando."""
    repo = _repo(pedido)
    agente = await repo.agente(ctx.escritorio(), id_agente)
    if not agente:
        raise HTTPException(404, "Agente não encontrado.")
    antes = (agente.get("config") or {}).get("automacoes") or {}
    limpas = _manter_nota_sempre(dados.automacoes,
                                 automacoes.validar(dados.automacoes, automacoes.gatilhos_do_produto(_produto_do(agente))))
    config = {**(agente.get("config") or {}), "automacoes": limpas}
    await repo.alterar_agente(ctx.escritorio(), id_agente, {"config": config})
    await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=ctx.escritorio(), tabela="agentesia_agentes",
                                   id_registro=id_agente, acao="alterou",
                                   resumo=f"Automações de {agente['nome']} ({len(limpas)} regras)", antes=antes, depois=limpas)
    return _agente_para_tela(await repo.agente(ctx.escritorio(), id_agente) or {})


# ============================================================================ follow-up
def _followup_para_tela(bruto: dict[str, Any] | None) -> dict[str, Any]:
    from app.followup import regras
    c = regras.Config.de(bruto)
    tela = {"ativo": c.ativo, "horario": {"inicio": c.inicio, "fim": c.fim, "dias": list(c.dias)},
            "intervalo_minimo_min": c.intervalo_minimo_min, "etapas": list(c.etapas), "prompt": c.prompt,
            "por_etapa": c.por_etapa, "passos": [vars(p) for p in c.passos], "modelo_oficial": c.modelo_oficial,
            "desistir": {"ativo": c.desistir_ativo, "apos_horas": c.desistir_apos_horas, "nota": c.desistir_nota},
            "modelo": c.modelo, "decidir": c.decidir}
    if (limites := regras._limites((bruto or {}).get("limites"))) is not None:
        tela["limites"] = limites            # quem ligou com o padrão novo: a tela devolve e os limites não somem
    return tela


@api.get("/agentes/{id_agente}/followup")
async def ver_followup(id_agente: str, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    from app.followup import regras
    repo = _repo(pedido)
    # O agente e as duas listas em paralelo (as listas só saem se o agente for deste escritório).
    agente, proximos, recentes = await asyncio.gather(repo.agente(ctx.escritorio(), id_agente), repo.pool.fetch(
        """select f.passo, f.agendado_para, f.situacao, f.motivo, ct.nome, right(ct.telefone_normalizado, 4) as final
           from agentesia_followups f join agentesia_leads l on l.id = f.id_lead join agentesia_contatos ct on ct.id = l.id_contato
           where f.id_agente = $1::uuid and f.situacao in ('pendente', 'reservado') order by f.agendado_para limit 30""", id_agente),
        repo.pool.fetch(
        """select f.passo, f.enviado_em, f.atualizado_em, f.situacao, f.motivo, f.mensagens, ct.nome
           from agentesia_followups f join agentesia_leads l on l.id = f.id_lead join agentesia_contatos ct on ct.id = l.id_contato
           where f.id_agente = $1::uuid and f.situacao in ('enviado', 'falhou', 'cancelado') order by f.atualizado_em desc limit 30""", id_agente))
    if not agente:
        raise HTTPException(404, "Agente não encontrado.")
    from app.gestao.rotas_followup import _textos as textos_fu, motivo_legivel
    produto = _produto_do(agente)
    bruto = (agente.get("config") or {}).get("followup")
    total = len(regras.Config.de(bruto if isinstance(bruto, dict) else None).passos)
    proximos, recentes = _linhas(proximos), _linhas(recentes)
    for linha in proximos + recentes:
        linha["motivo_texto"] = motivo_legivel(linha.get("motivo"))
        linha["desistencia"] = linha["passo"] >= total
    for linha in recentes:
        linha["mensagens"] = textos_fu(linha.get("mensagens"))
    variaveis, por_etapa_padrao = await _extras_do_editor_followup(repo, ctx.escritorio(), agente)
    # Etapas em que o follow-up PODE valer: as de conversa, menos desqualificado e contrato assinado (regras.vale_para).
    conversa = {e.codigo for e in produto.etapas if e.tipo == "conversa"} - regras.ETAPAS_SEM_FOLLOWUP
    return {"config": _followup_para_tela(bruto),
            "configurado": isinstance(bruto, dict),
            "padrao": {"prompt": regras.PROMPT_PADRAO, "cadencia": list(regras.CADENCIA_PADRAO),
                       "instrucoes": {str(k): v for k, v in regras.INSTRUCAO_PASSO_PADRAO.items()},
                       "por_etapa": por_etapa_padrao},
            "variaveis": variaveis,
            "etapas": [{"codigo": e.codigo, "nome": e.nome, "tipo": e.tipo, "pode_followup": e.codigo in conversa} for e in produto.etapas],
            "tipo_canal": agente.get("tipo_canal"), "proximos": proximos, "recentes": recentes}


async def _extras_do_editor_followup(repo: Any, id_escritorio: str, agente: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Para o editor do prompt de follow-up: as variáveis que o motor preenche (app/followup/agente.valores, com o valor
    de agora) e as instruções por etapa do padrão do produto da biblioteca (para "Restaurar padrão"). Falha = vazio."""
    from app.cerebro import catalogo
    from app.followup import agente as fagente, padrao
    variaveis: list[dict[str, Any]] = []
    por_etapa: dict[str, str] = {}
    try:
        escritorio = await repo.escritorio(id_escritorio) or {}
        config = agente.get("config") or {}
        vals = fagente.valores({"nome_agente": agente.get("nome"), "escritorio": escritorio.get("nome", ""),
                                "config_agente": config, "config_escritorio": escritorio.get("config") or {}})
        proprias = config.get("variables") if isinstance(config.get("variables"), dict) else {}
        vistos: set[str] = set()
        for rotulo in ("Nome Agente", "Nome Escritório", "Honorários",
                       *[str(k) for k, v in proprias.items() if not isinstance(v, (dict, list))]):
            chave = catalogo.chave_da_variavel(rotulo)
            if chave in vistos:
                continue
            vistos.add(chave)
            variaveis.append({"nome": rotulo, "valor": vals.get(chave) or None})
    except Exception:  # noqa: BLE001 - extra da tela; o editor funciona sem
        variaveis = []
    try:
        linha = await repo.pool.fetchrow(
            """select b.padrao_followup from agentesia_produtos_ativados p
               join agentesia_biblioteca_produtos b on b.id = p.id_produto_biblioteca
               where p.id_agente = $1::uuid and p.excluido_em is null limit 1""", agente["id"])
        if linha and linha["padrao_followup"]:
            por_etapa = padrao.config_do_produto({"padrao_followup": linha["padrao_followup"]}, ativo=False)["por_etapa"]
    except Exception:  # noqa: BLE001
        por_etapa = {}
    return variaveis, por_etapa


@api.put("/agentes/{id_agente}/followup")
async def salvar_followup(id_agente: str, dados: dict[str, Any], pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    from app.followup import regras
    repo = _repo(pedido)
    agente = await repo.agente(ctx.escritorio(), id_agente)
    if not agente:
        raise HTTPException(404, "Agente não encontrado.")
    try:
        novo = regras.validar(dados, anterior=(agente.get("config") or {}).get("followup"))
    except (ValueError, TypeError) as erro:
        raise HTTPException(400, str(erro)) from erro
    if novo.get("modelo") and novo["modelo"] not in IDS_MODELOS:
        raise HTTPException(400, "Modelo de IA desconhecido.")
    codigos = {e.codigo for e in _produto_do(agente).etapas}
    novo["etapas"] = [e for e in novo["etapas"] if e in codigos]
    novo["por_etapa"] = {k: v for k, v in novo["por_etapa"].items() if k in codigos}
    if novo["ativo"] and agente.get("tipo_canal") == "oficial" and not novo["modelo_oficial"].get("id_modelo"):
        raise HTTPException(400, "Número da API oficial: escolha um modelo aprovado para quando a janela de 24 h fechar.")
    antes = (agente.get("config") or {}).get("followup")
    config = {**(agente.get("config") or {}), "followup": novo}
    await repo.alterar_agente(ctx.escritorio(), id_agente, {"config": config})
    reprogramacao = {"reprogramados": 0, "cancelados": 0}
    if not novo["ativo"]:
        reprogramacao["cancelados"] = int((await repo.pool.execute(
            "update agentesia_followups set situacao = 'cancelado', motivo = 'followup_desligado' where id_agente = $1::uuid and situacao in ('pendente', 'reservado')",
            id_agente)).split()[-1])
    else:
        # Os já agendados passam a seguir a cadência nova (tempo novo; toque que sumiu é cancelado).
        from app.followup import servico as servico_fu
        reprogramacao = await servico_fu.reprogramar_do_agente(repo.pool, id_agente, antes if isinstance(antes, dict) else None, novo)
    await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=ctx.escritorio(), tabela="agentesia_agentes",
                                   id_registro=id_agente, acao="alterou",
                                   resumo=f"Follow-up de {agente['nome']} {'ligado' if novo['ativo'] else 'desligado'}: "
                                          + ", ".join(f"{p['apos_horas']:g}h" for p in novo["passos"]),
                                   antes=antes, depois=novo)
    return {**_followup_para_tela(novo), "reprogramacao": reprogramacao}


class PreviaFollowup(BaseModel):
    passo: int = 0
    config: dict[str, Any]
    etapa: str | None = None


@api.post("/agentes/{id_agente}/followup/previa")
async def previa_followup(id_agente: str, dados: PreviaFollowup, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Mostra como fica a mensagem do passo com uma conversa de exemplo (gasta uma chamada de IA no modo IA: entra na
    carteira com origem 'previa' e é bloqueada no pré-pago sem saldo, como o laboratório)."""
    from app import cobranca
    from app.followup import regras
    from app.followup.servico import ESQUEMA, TEXTO_RESERVA
    from app.gestao.rotas_rascunho import SEM_SALDO, _modelo_falso
    repo = _repo(pedido)
    agente = await repo.agente(ctx.escritorio(), id_agente)
    if not agente:
        raise HTTPException(404, "Agente não encontrado.")
    try:
        config = regras.Config.de(regras.validar(dados.config))
    except (ValueError, TypeError) as erro:
        raise HTTPException(400, str(erro)) from erro
    if not 0 <= dados.passo < len(config.passos):
        raise HTTPException(400, "Passo inexistente.")
    passo = config.passos[dados.passo]
    if passo.modo == "texto":
        return {"mensagens": [regras.preencher(passo.texto, nome="Maria")]}
    if passo.modo == "modelo":
        return {"mensagens": [f"[modelo aprovado: {config.modelo_oficial.get('nome') or 'escolha um modelo'}]"]}
    escritorio = await repo.escritorio(ctx.escritorio()) or {}
    # O mesmo prompt do envio de verdade: o agente da etapa escreve com a voz dele (app/followup/agente.py).
    from app.followup import agente as fagente
    etapa = dados.etapa or next(iter(config.etapas), "") or ""
    instrucao_etapa = await repo.pool.fetchval(
        "select instrucao from agentesia_agente_etapas where id_agente = $1::uuid and codigo = $2", id_agente, etapa) if etapa else None
    lead_exemplo = {"nome": "Maria", "nome_agente": agente.get("nome"), "escritorio": escritorio.get("nome", ""),
                    "produto": agente.get("produto"), "config_agente": agente.get("config") or {},
                    "config_escritorio": escritorio.get("config") or {}, "etapa": etapa, "instrucao_etapa": instrucao_etapa}
    sistema = fagente.sistema_do_agente_do_lead(lead_exemplo, config, dados.passo, len(config.passos))
    conversa = ("lead: oi, sofri um acidente de moto ano passado\nvocê: Poxa, sinto muito. Ficou com alguma sequela ou limitação?\n"
                "lead: fiquei com dor no joelho\nvocê: Entendi. Na época do acidente você trabalhava de carteira assinada?")
    modelo = pedido.app.state.laboratorios._modelo
    if not _modelo_falso(pedido) and await cobranca.bloqueado(repo.pool, ctx.escritorio()):
        raise HTTPException(402, SEM_SALDO)
    try:
        resultado = await modelo.gerar(papel="followup", sistema=sistema, conteudo="Conversa até aqui:\n" + conversa, esquema=ESQUEMA,
                                       modelo=config.modelo or (agente.get("config") or {}).get("modelos", {}).get("followup") or "gpt-4.1-mini", esforco="low")
        await cobranca.gravar_teste(repo.pool, id_escritorio=ctx.escritorio(), chamadas=resultado.chamadas, origem="previa",
                                    id_agente=id_agente, codigo_etapa=etapa or None)
        return {"mensagens": resultado.dados.get("mensagens") or [], "exemplo": conversa}
    except Exception as erro:
        # Tentativas que falharam (saída inválida, cortada) também foram pagas.
        await cobranca.gravar_teste(repo.pool, id_escritorio=ctx.escritorio(), chamadas=getattr(erro, "chamadas", []),
                                    origem="previa", id_agente=id_agente, codigo_etapa=etapa or None)
        return {"mensagens": [TEXTO_RESERVA.format(virgula=", ", nome="Maria")], "exemplo": conversa, "aviso": "A IA não respondeu; este é o texto de reserva."}


@api.get("/integracoes/helena/modelos-aprovados")
async def modelos_aprovados_helena(pedido: Request, ctx: Contexto = Depends(GESTAO)) -> list[dict[str, Any]]:
    repo = _repo(pedido)
    helena = await _helena_do_escritorio(pedido, repo, ctx.escritorio())
    try:
        return await helena.modelos_aprovados()
    except ErroHelenaApi as erro:
        raise _erro_helena(erro) from erro


def _manter_nota_sempre(entrada: dict[str, Any], limpas: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """A nota da troca de agente (padrão) sai mesmo sem "Avisar a equipe" ligada: ao salvar o padrão como regras
    próprias, o "nota_sempre" vem junto (o validar comum não conhece esse campo)."""
    for gatilho, regra in limpas.items():
        if isinstance(entrada.get(gatilho), dict) and entrada[gatilho].get("nota_sempre") and regra.get("nota"):
            regra["nota_sempre"] = True
    return limpas


def _automacoes_padrao_tela(config: dict[str, Any], crm: dict[str, Any], colunas: dict[str, str]) -> dict[str, Any]:
    """O CRM automático deste agente, como o motor roda (automacoes.regras_automaticas / config_efetiva).

    Sem as colunas fixas na conta (etapas_por_tipo), as regras vêm iguais, mas sem coluna: a tela mostra o padrão
    e avisa que falta o painel do CRM."""
    por_tipo = crm.get("etapas_por_tipo") or {}
    crm_pronto = bool(por_tipo and crm.get("id_painel"))
    base = crm if crm_pronto else {"id_painel": crm.get("id_painel") or "-",
                                   "etapas_por_tipo": {t: por_tipo.get(t) for t in automacoes.ETIQUETA_DO_TIPO}}
    regras = automacoes.regras_automaticas(config, base)
    tipos: dict[str, str] = {}
    for gatilho, regra in regras.items():
        if not regra.get("coluna_crm"):
            regra.pop("coluna_crm", None)
        tipo = "SDR" if gatilho == "lead_novo" else automacoes._tipo_do_papel(gatilho.split(":", 1)[-1])
        if tipo:
            tipos[gatilho] = tipo
    funcoes = config.get("funcoes") or {}
    proprias = config.get("automacoes") or {}
    efetiva = automacoes.config_efetiva(config, crm)
    return {
        "regras": regras, "tipos": tipos,
        "usa_padrao": not proprias and funcoes.get("crm") is not False,
        "crm_desligado": funcoes.get("crm") is False,
        "crm_pronto": crm_pronto, "tem_painel": bool(crm.get("id_painel")),
        "etapas_por_tipo": por_tipo, "colunas": colunas,
        "funcoes_efetivas": {f["id"]: bool((efetiva.get("funcoes") or {}).get(f["id"])) for f in FUNCOES},
    }


@api.get("/agentes/{id_agente}/automacoes/padrao")
async def automacoes_padrao(id_agente: str, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """As regras automáticas calculadas para o agente (o que o motor roda quando ele não tem regras próprias)."""
    repo = _repo(pedido)
    agente = await repo.agente(ctx.escritorio(), id_agente)
    if not agente:
        raise HTTPException(404, "Agente não encontrado.")
    crm = (await repo.integracao(ctx.escritorio(), "crm") or {}).get("config") or {}
    colunas: dict[str, str] = {}
    if crm.get("id_painel"):
        try:                                       # só para dar nome às colunas; sem a LawChat, a tela mostra o tipo
            helena = await _helena_do_escritorio(pedido, repo, ctx.escritorio())
            painel = next((p for p in await helena.paineis() if p["id"] == crm["id_painel"]), None)
            colunas = {e["id"]: e["titulo"] for e in (painel or {}).get("etapas", [])}
        except (ErroHelenaApi, HTTPException):
            colunas = {}
    return _automacoes_padrao_tela(agente.get("config") or {}, crm, colunas)


@api.get("/agentes/{id_agente}/automacoes/sugestao")
async def sugerir_automacoes(id_agente: str, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Sugestão a partir do painel escolhido: liga as etapas por nome parecido."""
    repo = _repo(pedido)
    crm = (await repo.integracao(ctx.escritorio(), "crm") or {}).get("config") or {}
    if not crm.get("id_painel"):
        raise HTTPException(409, "Escolha antes o painel do CRM em Integrações.")
    helena = await _helena_do_escritorio(pedido, repo, ctx.escritorio())
    try:
        painel = next((p for p in await helena.paineis() if p["id"] == crm["id_painel"]), None)
    except ErroHelenaApi as erro:
        raise _erro_helena(erro) from erro
    if not painel:
        raise HTTPException(404, "O painel escolhido não existe mais na LawChat.")
    agente = await repo.agente(ctx.escritorio(), id_agente)
    if not agente:
        raise HTTPException(404, "Agente não encontrado.")
    produto = _produto_do(agente)
    etiquetas: list[dict[str, Any]] | None = None
    if produto.codigo == "catalogo":
        try:                                       # as etiquetas da conta afinam a sugestão; sem elas, só as colunas
            etiquetas = await helena.etiquetas()
        except ErroHelenaApi:
            etiquetas = None
    return {"painel": painel, "automacoes": automacoes.sugestao_padrao(painel["etapas"], produto, etiquetas)}


# ============================================================================ biblioteca de modelos
class ModeloAgente(BaseModel):
    nome: str = Field(min_length=2, max_length=80)
    descricao: str = Field(default="", max_length=600)
    produto: str = "proprio"
    situacao: str = "rascunho"
    definicao: dict[str, Any] | None = None
    instrucoes: dict[str, str] = {}
    funcoes: dict[str, bool] = {}
    automacoes: dict[str, dict[str, Any]] = {}
    honorarios: str | None = None
    modelo_ia: str = "gpt-4.1-mini"


def _modelo_para_tela(modelo: dict[str, Any]) -> dict[str, Any]:
    config = modelo.get("config") or {}
    produto = produtos.carregar(modelo["produto"], config if modelo["produto"] == "proprio" else {})
    modelo["etapas"] = [{"codigo": e.codigo, "nome": e.nome, "tipo": e.tipo, "instrucao_padrao": e.instrucao_padrao}
                        for e in produto.etapas]
    modelo["gatilhos"] = automacoes.gatilhos_do_produto(produto)
    return modelo


@api.get("/modelos")
async def modelos_publicados(pedido: Request, _: Contexto = Depends(GESTAO)) -> list[dict[str, Any]]:
    """Modelos que o cliente pode ativar no assistente de criação."""
    return [{"id": m["id"], "nome": m["nome"], "descricao": m["descricao"], "produto": m["produto"]}
            for m in await _repo(pedido).modelos(so_publicados=True)]


@api.get("/admin/modelos")
async def listar_modelos(pedido: Request, _: Contexto = Depends(ADMIN)) -> list[dict[str, Any]]:
    return await _repo(pedido).modelos(so_publicados=False)


@api.get("/admin/modelos/{id_modelo}")
async def ver_modelo(id_modelo: str, pedido: Request, _: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    modelo = await _repo(pedido).modelo(id_modelo)
    if not modelo:
        raise HTTPException(404, "Modelo não encontrado.")
    return _modelo_para_tela(modelo)


async def _gravar_modelo(pedido: Request, ctx: Contexto, id_modelo: str | None, dados: ModeloAgente) -> dict[str, Any]:
    if dados.produto not in {p["id"] for p in PRODUTOS}:
        raise HTTPException(400, "Produto desconhecido.")
    if dados.situacao not in ("rascunho", "publicado", "arquivado"):
        raise HTTPException(400, "Situação inválida.")
    if dados.modelo_ia not in IDS_MODELOS:
        raise HTTPException(400, "Modelo de IA desconhecido.")
    config: dict[str, Any] = {"honorarios": (dados.honorarios or "").strip() or None, "modelo_ia": dados.modelo_ia}
    if dados.produto == "proprio":
        config["definicao"] = _validar_definicao(dados.definicao or DEFINICAO_INICIAL).model_dump()
    produto = produtos.carregar(dados.produto, config)
    codigos = {e.codigo for e in produto.etapas}
    config["instrucoes"] = {k: v.strip() for k, v in dados.instrucoes.items() if k in codigos and v.strip()}
    prontas = {f["id"] for f in FUNCOES if f["pronta"]}
    config["funcoes"] = {k: bool(v) for k, v in dados.funcoes.items() if k in prontas}
    config["automacoes"] = automacoes.validar(dados.automacoes, automacoes.gatilhos_do_produto(produto))
    repo = _repo(pedido)
    antes = await repo.modelo(id_modelo) if id_modelo else None
    if id_modelo and not antes:
        raise HTTPException(404, "Modelo não encontrado.")
    salvo = await repo.salvar_modelo(id_modelo, nome=dados.nome.strip(), descricao=dados.descricao.strip(),
                                     produto=dados.produto, config=config, situacao=dados.situacao, id_usuario=ctx.id_usuario)
    await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=None, tabela="agentesia_modelos_agente",
                                   id_registro=salvo["id"], acao="alterou" if id_modelo else "criou",
                                   resumo=f"Modelo de agente {salvo['nome']} ({salvo['situacao']})",
                                   antes=(antes or {}).get("config"), depois=config)
    return _modelo_para_tela(salvo)


@api.post("/admin/modelos")
async def criar_modelo(dados: ModeloAgente, pedido: Request, ctx: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    return await _gravar_modelo(pedido, ctx, None, dados)


@api.put("/admin/modelos/{id_modelo}")
async def alterar_modelo(id_modelo: str, dados: ModeloAgente, pedido: Request, ctx: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    return await _gravar_modelo(pedido, ctx, id_modelo, dados)


@api.post("/admin/modelos/do-agente/{id_agente}")
async def modelo_do_agente(id_agente: str, pedido: Request, ctx: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    """Transforma um agente que funciona bem num modelo da biblioteca (em rascunho)."""
    agente = await _repo(pedido).agente(ctx.escritorio(), id_agente)
    if not agente:
        raise HTTPException(404, "Agente não encontrado.")
    config = agente.get("config") or {}
    return await _gravar_modelo(pedido, ctx, None, ModeloAgente(
        nome=f"{agente['nome']} (modelo)", produto=agente["produto"], situacao="rascunho",
        definicao=config.get("definicao"), honorarios=config.get("honorarios"),
        instrucoes={e["codigo"]: e["instrucao"] for e in agente["etapas"] if e.get("instrucao")},
        funcoes=config.get("funcoes") or {}, automacoes=config.get("automacoes") or {},
        modelo_ia=(config.get("modelos") or {}).get("etapa") or "gpt-4.1",
        descricao=f"Criado a partir do agente {agente['nome']}."))


class MensagemLab(BaseModel):
    texto: str = Field(min_length=1, max_length=4000)
    id_conversa: str | None = None


@api.post("/agentes/{id_agente}/laboratorio")
async def laboratorio(id_agente: str, dados: MensagemLab, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Conversa de teste com a configuração salva do agente. Não envia nada e a conversa fica só em memória; o gasto de
    IA entra na carteira (origem 'laboratorio') e o pré-pago sem saldo é bloqueado, como no laboratório do rascunho."""
    from app import cobranca
    from app.gestao.rotas_rascunho import SEM_SALDO, _modelo_falso
    repo = _repo(pedido)
    agente = await repo.agente(ctx.escritorio(), id_agente)
    escritorio = await repo.escritorio(ctx.escritorio())
    if not agente or not escritorio:
        raise HTTPException(404, "Agente não encontrado.")
    if not _modelo_falso(pedido) and await cobranca.bloqueado(repo.pool, ctx.escritorio()):
        raise HTTPException(402, SEM_SALDO)
    resultado = await pedido.app.state.laboratorios.mensagem(
        escritorio=escritorio, agente=agente, id_conversa=dados.id_conversa, texto=dados.texto.strip())
    turno = resultado.get("turno") or {}
    await cobranca.gravar_teste(repo.pool, id_escritorio=ctx.escritorio(), chamadas=turno.get("chamadas") or [],
                                origem="laboratorio", id_agente=id_agente, codigo_etapa=turno.get("etapa_antes") or None)
    return resultado


# ============================================================================ avisos à equipe
class Aviso(BaseModel):
    nome: str = Field(min_length=2, max_length=120)
    habilitada: bool = True
    modelo_mensagem: str = Field(min_length=3, max_length=2000)
    destinatarios: list[dict[str, str]] = []


def _eventos_do_escritorio(agentes: list[dict[str, Any]]) -> dict[str, str]:
    """Eventos que podem gerar aviso: os gatilhos de todos os agentes do escritório, com nome amigável."""
    eventos: dict[str, str] = {}
    for agente in agentes:
        eventos.update(automacoes.gatilhos_do_produto(_produto_do(agente)))
    eventos.update({k: v for k, v in automacoes.GATILHOS.items() if k not in eventos})
    return {k: notificacoes.NOMES_DE_EVENTO.get(k, v) for k, v in eventos.items()}


@api.get("/notificacoes")
async def listar_avisos(pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    repo = _repo(pedido)
    agentes, avisos = await asyncio.gather(repo.agentes(ctx.escritorio()), repo.notificacoes(ctx.escritorio()))
    return {"eventos": _eventos_do_escritorio(agentes),
            "avisos": avisos,
            "modelo_padrao": notificacoes.MODELO_PADRAO, "marcadores": list(notificacoes.MARCADORES)}


@api.put("/notificacoes/{tipo_evento}")
async def salvar_aviso(tipo_evento: str, dados: Aviso, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    repo = _repo(pedido)
    if tipo_evento not in _eventos_do_escritorio(await repo.agentes(ctx.escritorio())):
        raise HTTPException(400, "Evento desconhecido.")
    destinatarios = [{"rotulo": d.rotulo, "numero": d.numero}
                     for d in notificacoes.filtrar_destinatarios(dados.destinatarios, None)]
    if dados.habilitada and not destinatarios:
        raise HTTPException(400, "Cadastre pelo menos um número para receber o aviso (com DDD).")
    antes = await repo.notificacao(ctx.escritorio(), tipo_evento)
    salvo = await repo.salvar_notificacao(ctx.escritorio(), tipo_evento, nome=dados.nome.strip(), habilitada=dados.habilitada,
                                          modelo_mensagem=dados.modelo_mensagem.strip(), destinatarios=destinatarios)
    await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=ctx.escritorio(), tabela="agentesia_notificacoes",
                                   id_registro=salvo["id"], acao="alterou" if antes else "criou",
                                   resumo=f"Aviso à equipe \"{salvo['nome']}\" " + ("ligado" if dados.habilitada else "desligado"),
                                   antes=antes, depois=salvo)
    return salvo


@api.delete("/notificacoes/{tipo_evento}")
async def apagar_aviso(tipo_evento: str, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    repo = _repo(pedido)
    antes = await repo.notificacao(ctx.escritorio(), tipo_evento)
    if not antes:
        raise HTTPException(404, "Aviso não encontrado.")
    await repo.apagar_notificacao(ctx.escritorio(), tipo_evento)
    await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=ctx.escritorio(), tabela="agentesia_notificacoes",
                                   id_registro=antes["id"], acao="apagou", resumo=f"Aviso à equipe \"{antes['nome']}\" apagado",
                                   antes=antes)
    return {"ok": True}


@api.post("/notificacoes/{tipo_evento}/teste")
async def testar_aviso(tipo_evento: str, pedido: Request, enviar: bool = False,
                       ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Mostra como o aviso fica com dados de exemplo; com enviar=true, manda de verdade aos números cadastrados."""
    repo = _repo(pedido)
    aviso = await repo.notificacao(ctx.escritorio(), tipo_evento)
    if not aviso:
        raise HTTPException(404, "Salve o aviso antes de testar.")
    escritorio = await repo.escritorio(ctx.escritorio()) or {}
    config_escritorio = escritorio.get("config") if isinstance(escritorio.get("config"), dict) else json.loads(escritorio.get("config") or "{}")
    # Mesmos marcadores do aviso de verdade: o link da conversa só aparece com o domínio da Helena cadastrado
    # (sem ele a linha some, como no aviso real, e mostra que falta cadastrar).
    valores = notificacoes.valores_do_aviso(evento=tipo_evento, nome="Maria Exemplo (teste)", telefone="5511988887777",
                                            produto="Auxílio-Acidente", etapa="Proposta e honorários", valor="30% no final",
                                            link_assinatura="https://app.zapsign.com.br/verificar/exemplo",
                                            link_conversa=sinais.link_da_conversa(config_escritorio, "exemplo"),
                                            mensagem_lead="Dá para ser por videochamada?",
                                            gatilhos=_eventos_do_escritorio(await repo.agentes(ctx.escritorio())),
                                            sinais=["quer_videochamada"] if tipo_evento == "sinal" else None)
    texto = "[TESTE] " + notificacoes.renderizar_modelo(aviso["modelo_mensagem"], valores)
    destinatarios = notificacoes.filtrar_destinatarios(aviso["destinatarios"] if isinstance(aviso["destinatarios"], list)
                                                       else json.loads(aviso["destinatarios"] or "[]"), None)
    if not enviar:
        return {"texto": texto, "destinatarios": [d.rotulo for d in destinatarios]}
    canal = next((c for c in await repo.canais(ctx.escritorio()) if c["ativo"] and c["tipo"] != "oficial"), None)
    if not canal:
        raise HTTPException(409, "Para enviar o teste, o escritório precisa de um número não oficial conectado.")
    marca = int(time.time())
    for d in destinatarios:
        await repo.enfileirar_acao(id_escritorio=ctx.escritorio(), tipo="notificar", chave_unica=f"teste:{aviso['id']}:{d.numero}:{marca}",
                                   dados={"de": canal["numero_normalizado"], "para": d.numero, "rotulo": d.rotulo,
                                          "texto": texto, "tipo_canal": canal["tipo"], "evento": tipo_evento})
    return {"texto": texto, "destinatarios": [d.rotulo for d in destinatarios], "enfileirados": len(destinatarios)}


# ============================================================================ acompanhamento
class AcaoLead(BaseModel):
    acao: str                              # desativar | reativar | encerrar | trocar_etapa (pausar/devolver: nomes antigos)
    etapa: str | None = None               # código da etapa (só em trocar_etapa)
    minutos: int | None = Field(default=None, ge=0, le=10080)   # desativar: 30, 120, 1440... (vazio/0 = até religar)


# Leituras do Início e do menu guardadas por poucos segundos por escritório (app/gestao/cache_curto.py: qualquer escrita
# no painel apaga). Com o banco em us-west-2 cada ida custa ~200 ms e o painel pede estas a cada troca de tela.
_CACHE_INICIO = CacheCurto(15)
_CACHE_CONTADORES = CacheCurto(15)
_CACHE_PASSOS = CacheCurto(30)
_CACHE_SAUDE = CacheCurto(30)


@api.get("/inicio")
async def inicio(pedido: Request, ctx: Contexto = Depends(TODOS)) -> dict[str, Any]:
    return await _CACHE_INICIO.obter((id(pedido.app), ctx.escritorio()), lambda: _calcular_inicio(pedido, ctx))


async def _calcular_inicio(pedido: Request, ctx: Contexto) -> dict[str, Any]:
    import asyncio
    repo = _repo(pedido)
    # As cinco leituras são independentes: em paralelo, o tempo é o da mais lenta e não a soma das idas ao banco.
    resumo, agentes, erros, integracoes, followup = await asyncio.gather(
        repo.resumo(ctx.escritorio()), repo.agentes(ctx.escritorio()),
        repo.eventos(ctx.escritorio(), abertos=True, limite=8), repo.integracoes(ctx.escritorio()),
        _followup_desligado(repo, ctx.escritorio()))
    return {"resumo": resumo, "agentes": [_agente_para_tela(a) for a in agentes], "erros": erros,
            "integracoes": integracoes, "followup_desligado": followup}


@api.get("/inicio/contadores")
async def contadores(pedido: Request, ctx: Contexto = Depends(TODOS)) -> dict[str, Any]:
    """Contador do menu (erros abertos): uma consulta só. Antes o menu pedia o /inicio inteiro em toda tela."""
    async def calcular() -> dict[str, Any]:
        erros = await _repo(pedido).pool.fetchval(
            """select count(*)::int from agentesia_eventos where id_escritorio = $1::uuid and resolvido_em is null
               and gravidade in ('erro', 'critico')""", ctx.escritorio())
        return {"erros_abertos": erros or 0}
    return await _CACHE_CONTADORES.obter((id(pedido.app), ctx.escritorio()), calcular)


@api.get("/inicio/primeiros-passos")
async def primeiros_passos(pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Cartão "Primeiros passos" do Início: 7 passos que se marcam sozinhos (app/gestao/primeiros_passos.py)."""
    from app.gestao import primeiros_passos as pp
    return await _CACHE_PASSOS.obter((id(pedido.app), ctx.escritorio()), lambda: pp.calcular(_repo(pedido).pool, ctx.escritorio()))


@api.get("/admin/escritorios/primeiros-passos")
async def progresso_das_contas(pedido: Request, _: Contexto = Depends(ADMIN)) -> dict[str, Any]:
    """Coluna "Progresso" das Contas: por escritório, quantos dos 7 passos estão feitos e quais faltam."""
    from app.gestao import primeiros_passos as pp
    return await pp.de_todos(_repo(pedido).pool)


@api.get("/saude/numeros")
async def saude_dos_numeros(pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Selo de cada número e agente: recebendo mensagens, sem mensagens há X dias ou sem número; e o tipo do número."""
    from app.gestao import saude_numero
    return await _CACHE_SAUDE.obter((id(pedido.app), ctx.escritorio()), lambda: saude_numero.numeros(_repo(pedido).pool, ctx.escritorio()))


@api.post("/saude/numeros/{id_canal}/testar")
async def testar_conexao(id_canal: str, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    """Testar conexão: conta (token), número, webhook e endereço público, só lendo (nada muda na Helena)."""
    from app.gestao import saude_numero
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", id_canal):
        raise HTTPException(404, "Número não encontrado.")
    repo = _repo(pedido)

    async def _helena(id_escritorio: str) -> HelenaConta:
        return await _helena_do_escritorio(pedido, repo, id_escritorio)

    resultado = await saude_numero.testar(repo=repo, id_escritorio=ctx.escritorio(), id_canal=id_canal, helena_de=_helena,
                                          http=getattr(pedido.app.state, "http_ativacao", None))
    if resultado is None:
        raise HTTPException(404, "Número não encontrado.")
    return resultado


async def _followup_desligado(repo: Any, id_escritorio: str) -> list[dict[str, Any]]:
    """Produtos ativos com follow-up desligado (aviso discreto do Início, docs/FOLLOWUP.md). Sem banco: lista vazia."""
    from app.followup import padrao
    pool = getattr(repo, "pool", None)
    if pool is None:
        return []
    try:
        return await padrao.desligados_do_escritorio(pool, id_escritorio)
    except Exception:                       # o aviso nunca derruba o Início
        import logging
        logging.getLogger("agentesia").exception("falha ao conferir o follow-up dos produtos")
        return []


@api.get("/funil")
async def funil(pedido: Request, dias: int = 30, id_agente: str | None = None, ctx: Contexto = Depends(TODOS)) -> dict[str, Any]:
    """Funil do agente no período: quantos leads chegaram a cada etapa, conversão e origem."""
    repo = _repo(pedido)
    dias = max(1, min(int(dias), 365))
    agentes = await repo.agentes(ctx.escritorio())
    if not agentes:
        return {"agente": None, "agentes": [], "dias": dias, "etapas": [], "totais": {}, "origens": []}
    escolhido = next((a for a in agentes if str(a["id"]) == id_agente), None) \
        or next((a for a in agentes if a.get("situacao") == "ativo"), agentes[0])
    dados = await repo.funil(str(escolhido["id"]), dias)
    nomes = {e.codigo: e.nome for e in _produto_do(escolhido).etapas}
    inicio = dados["etapas"][0]["leads"] if dados["etapas"] else 0
    anterior = None
    for etapa in dados["etapas"]:
        etapa["nome"] = nomes.get(etapa["codigo"], etapa["codigo"])
        etapa["do_inicio"] = round(etapa["leads"] / inicio * 100, 1) if inicio else None
        etapa["da_anterior"] = round(etapa["leads"] / anterior * 100, 1) if anterior else None
        anterior = etapa["leads"]
    return {"agente": {"id": escolhido["id"], "nome": escolhido["nome"]},
            "agentes": [{"id": a["id"], "nome": a["nome"]} for a in agentes], "dias": dias, **dados}


@api.get("/eventos")
async def eventos(pedido: Request, abertos: bool = True, todos_escritorios: bool = False,
                  ctx: Contexto = Depends(GESTAO)) -> list[dict[str, Any]]:
    if not ctx.lawchat:                      # a tela de Erros é só da equipe LawChat (o cliente não vê)
        raise HTTPException(403, "Só a equipe LawChat vê os erros.")
    escopo = None if (ctx.admin and todos_escritorios) else ctx.escritorio()
    return await _repo(pedido).eventos(escopo, abertos=abertos)


@api.post("/eventos/{id_evento}/resolver")
async def resolver_evento(id_evento: str, pedido: Request, ctx: Contexto = Depends(GESTAO)) -> dict[str, Any]:
    if not ctx.lawchat:
        raise HTTPException(403, "Só a equipe LawChat vê os erros.")
    escopo = None if ctx.admin else ctx.escritorio()
    if not await _repo(pedido).resolver_evento(id_evento, escopo, ctx.id_usuario):
        raise HTTPException(404, "Erro não encontrado ou já resolvido.")
    return {"ok": True}


@api.get("/conversas")
async def conversas(pedido: Request, busca: str = "", id_agente: str | None = None,
                    ctx: Contexto = Depends(TODOS)) -> list[dict[str, Any]]:
    id_agente = (id_agente or "").strip() or None
    if id_agente and not re.fullmatch(r"[0-9a-fA-F-]{36}", id_agente):
        raise HTTPException(400, "Agente inválido.")
    return await _repo(pedido).conversas(ctx.escritorio(), re.sub(r"[%_]", "", busca.strip())[:60], id_agente=id_agente)


@api.get("/conversas/{id_lead}")
async def conversa(id_lead: str, pedido: Request, ctx: Contexto = Depends(TODOS)) -> dict[str, Any]:
    lead = await _repo(pedido).conversa(ctx.escritorio(), id_lead)
    if not lead:
        raise HTTPException(404, "Conversa não encontrada.")
    return lead


async def _trocar_etapa_do_lead(pedido: Request, ctx: Contexto, id_lead: str, codigo: str) -> dict[str, Any]:
    """A equipe põe o lead noutra etapa do agente dele (qualificou por telefone e quer que Contratos colete os dados).
    Mesmo caminho da troca feita pelo card do CRM (app/troca_etapa.py): grava a etapa, deixa o histórico (alteração e
    evento 'etapa_trocada', origem 'equipe') e põe na fila as automações do gatilho 'etapa:<codigo>' (card, etiquetas,
    nota, aviso)."""
    from app import troca_etapa

    if not re.fullmatch(r"[0-9a-fA-F-]{36}", id_lead):
        raise HTTPException(404, "Conversa não encontrada.")
    if not codigo:
        raise HTTPException(400, "Informe a etapa.")
    repo = _repo(pedido)
    lead = await repo.pool.fetchrow(
        """select l.id, l.id_agente, et.codigo as etapa, ag.config as config_agente
           from agentesia_leads l left join agentesia_agentes ag on ag.id = l.id_agente
           left join agentesia_agente_etapas et on et.id = l.id_etapa
           where l.id = $1::uuid and l.id_escritorio = $2::uuid""", id_lead, ctx.escritorio())
    if not lead:
        raise HTTPException(404, "Conversa não encontrada.")
    if not lead["id_agente"] or not await repo.pool.fetchval(
            "select true from agentesia_agente_etapas where id_agente = $1 and codigo = $2", lead["id_agente"], codigo):
        raise HTTPException(400, f"O agente desta conversa não tem a etapa {codigo}.")
    if lead["etapa"] == codigo:
        return {"ok": True, "etapa": codigo, "mudou": False}
    config_agente = lead["config_agente"]
    config_agente = json.loads(config_agente) if isinstance(config_agente, str) else (config_agente or {})
    if not await troca_etapa.trocar_pela_equipe(repo.pool, id_escritorio=ctx.escritorio(), id_lead=id_lead,
                                                de=lead["etapa"], codigo=codigo, config_agente=config_agente,
                                                origem="equipe", quem="equipe, pelo painel", id_usuario=ctx.id_usuario):
        return {"ok": True, "etapa": codigo, "mudou": False}            # outra troca chegou antes (corrida)
    await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=ctx.escritorio(), tabela="agentesia_leads",
                                   id_registro=id_lead, acao="trocar_etapa",
                                   resumo=f"Etapa do lead: {lead['etapa'] or '-'} → {codigo}",
                                   antes={"etapa": lead["etapa"]}, depois={"etapa": codigo})
    return {"ok": True, "etapa": codigo, "mudou": True}


class EntrarNaHelena(BaseModel):
    id_lead: str | None = None
    # Tela de ajustes da conta aberta dentro do painel (Minha Conta). Só as da lista abaixo.
    pagina: str | None = None


# Minha Conta › telas de ajustes da conta na LawChat (abertas já logadas dentro do painel). Lista fechada: o painel
# manda só o código; o caminho nunca vem do navegador.
PAGINAS_DE_AJUSTES = {
    "usuarios": "/settings/core/agents",
    "equipes": "/settings/core/departments",
    "modelos": "/settings/chat/templates",
    "conta": "/settings/core/company",
    "horario": "/settings/core/company/office-hours",
    "canais": "/settings/core/company/channels",
    "consumo": "/settings/core/company/balance",
    "integracoes": "/integration",
    "contatos": "/contacts",
    "paineis": "/panels",
    "chatbots": "/chatbots/list",
}


def _link_da_helena_e_seguro(url: str, url_api_helena: str = "") -> bool:
    """O link de entrada tem de ser https e da Helena (domínio próprio do white-label incluído: wts.chat, helena.run).
    Também vale o próprio endereço configurado da Helena (no teste local, a Helena de mentira)."""
    from urllib.parse import urlparse
    partes = urlparse(url or "")
    host = (partes.hostname or "").lower()
    api_helena = urlparse(url_api_helena or "")
    if api_helena.hostname and host == api_helena.hostname.lower() and partes.scheme == api_helena.scheme:
        return True
    return partes.scheme == "https" and any(host == d or host.endswith("." + d) for d in ("helena.run", "wts.chat"))


@api.post("/atendimento/entrar")
async def entrar_na_helena(dados: EntrarNaHelena, pedido: Request, ctx: Contexto = Depends(TODOS)) -> dict[str, Any]:
    """Login integrado da Helena: devolve o link de uso único que abre a tela de atendimento já logada, como o usuário
    do painel (pelo e-mail dele), na conta Helena do escritório. Com id_lead, abre direto a conversa daquele lead
    (só ela, sem o menu da Helena). O token da conta nunca sai do servidor e o link não vai para log."""
    repo = _repo(pedido)
    id_escritorio = ctx.escritorio()
    escritorio = await repo.escritorio(id_escritorio) or {}
    id_conta = escritorio.get("id_conta_helena")
    if not id_conta:
        raise HTTPException(409, "Este escritório ainda não tem a conta da LawChat ligada.")
    helena = await _helena_do_escritorio(pedido, repo, id_escritorio)
    email = str(ctx.usuario.get("email") or "").strip().lower()
    id_helena = ctx.usuario.get("id_usuario_helena")
    if id_helena and (not email or email.endswith(".helena.local")):
        # Quem entrou pelo login da Helena: vale o e-mail que a própria Helena tem para essa pessoa.
        try:
            atendente = await helena.atendente(str(id_helena))
        except ErroHelenaApi as erro:
            raise _erro_helena(erro) from erro
        email = (atendente or {}).get("email") or ""
    if not email or email.endswith(".helena.local"):
        raise HTTPException(409, "Seu usuário não tem um e-mail na LawChat. Peça para cadastrar seu e-mail como usuário da conta.")
    # Conta da própria LawChat: a equipe LawChat entra no atendimento sempre com o usuário definido para isso
    # (AGENTESIA_HELENA_EMAIL_ATENDIMENTO; padrão: o e-mail do administrador da conta, vindo da sincronização).
    # O login do painel (ex.: admin@lawchat.com.br) é do parceiro e a Helena não faz o login integrado com ele.
    conta_lawchat = os.environ.get("AGENTESIA_HELENA_CONTA_LAWCHAT", "").strip().lower()
    if ctx.lawchat and conta_lawchat and str(id_conta).lower() == conta_lawchat:
        fixo = os.environ.get("AGENTESIA_HELENA_EMAIL_ATENDIMENTO", "").strip().lower()
        if not fixo:
            from app.gestao import sincronizar_conta
            conta_dados = (await sincronizar_conta.ler_dados_helena(repo.pool, id_escritorio)).get("conta") or {}
            fixo = str(conta_dados.get("email_contato") or conta_dados.get("email") or "").strip().lower()
        if fixo:
            email = fixo
    destino = "/chat2/sessions"
    if dados.pagina:
        if dados.pagina not in PAGINAS_DE_AJUSTES:
            raise HTTPException(404, "Tela de ajustes não encontrada.")
        destino = PAGINAS_DE_AJUSTES[dados.pagina]
    if dados.id_lead:
        if not re.fullmatch(r"[0-9a-fA-F-]{36}", dados.id_lead):
            raise HTTPException(404, "Conversa não encontrada.")
        id_sessao = await repo.pool.fetchval(
            "select id_sessao_helena from agentesia_leads where id = $1::uuid and id_escritorio = $2::uuid",
            dados.id_lead, id_escritorio)
        if not id_sessao:
            raise HTTPException(404, "Esta conversa ainda não tem atendimento aberto na LawChat.")
        if not re.fullmatch(r"[0-9A-Za-z-]{1,64}", str(id_sessao)):
            raise HTTPException(409, "Atendimento da LawChat com identificador inesperado.")
        destino = f"/chat2/sessions/{id_sessao}"          # a conversa normal (sem o modo preview), já aberta
    try:
        resposta = await helena.login_integrado(email=email, id_conta=str(id_conta), destino=destino)
    except ErroHelenaApi as erro:
        if not _usuario_fora_da_conta(erro):
            raise _erro_helena(erro) from erro
        # Equipe LawChat na CONTA DA PRÓPRIA LAWCHAT: o super administrador do parceiro não pertence à conta, e a
        # Helena só faz o login integrado com usuário da conta. Ali (só ali) entra como o administrador da conta.
        # Em conta de cliente isso seria se passar pelo cliente: não faz.
        conta_lawchat = os.environ.get("AGENTESIA_HELENA_CONTA_LAWCHAT", "").strip().lower()
        admin_da_conta = None
        if ctx.lawchat and conta_lawchat and str(id_conta).lower() == conta_lawchat:
            from app.gestao import sincronizar_conta
            conta = (await sincronizar_conta.ler_dados_helena(repo.pool, id_escritorio)).get("conta") or {}
            admin_da_conta = str(conta.get("email_contato") or conta.get("email") or "").strip().lower() or None
        if not admin_da_conta or admin_da_conta == email:
            raise HTTPException(409, f"O e-mail {email} não é usuário desta conta na LawChat (super administrador do "
                                     "parceiro não entra pelo atendimento). Cadastre esse e-mail como usuário da conta "
                                     "em Ajustes › Usuários, ou entre com um usuário da conta.") from erro
        try:
            resposta = await helena.login_integrado(email=admin_da_conta, id_conta=str(id_conta), destino=destino)
        except ErroHelenaApi as erro2:
            if _usuario_fora_da_conta(erro2):
                raise HTTPException(409, f"Nem {email} nem o administrador da conta ({admin_da_conta}) entram pelo "
                                         "atendimento. Cadastre um usuário da conta em Ajustes › Usuários.") from erro2
            raise _erro_helena(erro2) from erro2
        email = admin_da_conta
    url = str(resposta.get("urlRedirect") or "")
    if not _link_da_helena_e_seguro(url, pedido.app.state.cfg.helena_url):
        raise HTTPException(502, "A LawChat não devolveu um link de entrada válido.")
    await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=id_escritorio, tabela="agentesia_escritorios",
                                   id_registro=id_escritorio, acao="abriu_atendimento",
                                   resumo=f"Abriu {'os ajustes (' + dados.pagina + ')' if dados.pagina else 'o atendimento'} da LawChat{' (conversa de um lead)' if dados.id_lead else ''}"
                                          + (f" como {email}" if email != str(ctx.usuario.get("email") or "").lower() else ""),
                                   depois={"id_lead": dados.id_lead, "pagina": dados.pagina, "entrou_como": email})
    return {"url": url, "expira_em": resposta.get("expiresIn")}


def _usuario_fora_da_conta(erro: ErroHelenaApi) -> bool:
    """A Helena responde 400 OTP_USER_NOT_FOUND quando o e-mail não é usuário da conta (ou é só do parceiro)."""
    return (erro.status or 0) in (400, 404, 422) and erro.motivo in ("nao_encontrado", "erro_helena")


@api.post("/conversas/{id_lead}/ia")
async def acao_na_conversa(id_lead: str, dados: AcaoLead, pedido: Request, ctx: Contexto = Depends(TODOS)) -> dict[str, Any]:
    """Botões da IA na tela Conversas (gestor e atendente). Desativar e reativar passam pelo mesmo caminho da etiqueta e
    do botão da Helena (app/ia_controle.py): estado e prazo, follow-ups cancelados, etiqueta, nota DES/ATV e histórico."""
    from app import ia_controle

    estados = {"devolver": ("ativo", "devolvido_pela_equipe"), "encerrar": ("encerrado", "encerrado_pela_equipe")}
    acao = {"pausar": "desativar", "devolver": "reativar"}.get(dados.acao, dados.acao)
    if dados.acao == "trocar_etapa":
        return await _trocar_etapa_do_lead(pedido, ctx, id_lead, (dados.etapa or "").strip())
    if acao not in ("desativar", "reativar", "encerrar"):
        raise HTTPException(400, "Ação inválida.")
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", id_lead):
        raise HTTPException(404, "Conversa não encontrada.")
    repo = _repo(pedido)
    atual = await repo.pool.fetchval(
        "select estado from agentesia_leads where id = $1::uuid and id_escritorio = $2::uuid", id_lead, ctx.escritorio())
    if atual is None:
        raise HTTPException(404, "Conversa não encontrada.")
    if acao in ("desativar", "reativar") and atual != "encerrado":
        r = await ia_controle.mudar_ia(repo.pool, ctx.escritorio(), ligar=acao == "reativar", origem="painel",
                                       id_lead=id_lead, minutos=dados.minutos or 0, id_usuario=ctx.id_usuario)
        lead = await repo.pool.fetchrow(
            "select estado, motivo_estado, pausado_ate from agentesia_leads where id = $1::uuid", id_lead)
        return {"ok": True, "estado": lead["estado"], "motivo_estado": lead["motivo_estado"],
                "pausado_ate": lead["pausado_ate"].isoformat() if lead["pausado_ate"] else None,
                "codigo": r.get("codigo"), "mudou": bool(r.get("alterados"))}
    if acao == "desativar":
        raise HTTPException(409, "A conversa está encerrada: a IA já não responde. Para voltar, use Devolver para a IA.")
    estado, motivo = estados["devolver" if acao == "reativar" else acao]
    if not await repo.mudar_estado_lead(ctx.escritorio(), id_lead, estado, motivo):
        raise HTTPException(404, "Conversa não encontrada.")
    await repo.registrar_alteracao(id_usuario=ctx.id_usuario, id_escritorio=ctx.escritorio(), tabela="agentesia_leads",
                                   id_registro=id_lead, acao=dados.acao, resumo=f"IA do lead: {dados.acao}")
    return {"ok": True, "estado": estado}


@api.get("/alteracoes")
async def alteracoes(pedido: Request, todos_escritorios: bool = False, ctx: Contexto = Depends(GESTAO)) -> list[dict[str, Any]]:
    escopo = None if (ctx.admin and todos_escritorios) else ctx.escritorio()
    return await _repo(pedido).alteracoes(escopo)
