"""Deploy em dois apps (Frente D): app.entrada_ia e app.entrada_painel montam só as rotas de cada papel, o painel não
liga laços de fundo e o app.main:app continua servindo tudo. Sem banco de verdade e sem chamar API nenhuma."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config as configuracao
from app import main as principal
from app import servidor

RAIZ = Path(__file__).resolve().parents[1]
UUID = "11111111-2222-3333-4444-555555555555"


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch):
    """Sem .env local, sem banco e sem IA; o estado compartilhado com o app.main volta como estava no fim."""
    monkeypatch.setattr(configuracao, "_carregar_env_local", lambda *a, **k: None)
    for nome in ("AGENTESIA_BANCO_URL", "AGENTESIA_LAB_SENHA", "AGENTESIA_PAINEL_CRM_LIGADO"):
        monkeypatch.delenv(nome, raising=False)
    monkeypatch.setenv("AGENTESIA_MODELO_FALSO", "1")
    monkeypatch.setenv("AGENTESIA_WEBHOOK_SEGREDO", "mestre-de-teste")
    guardado = dict(principal.app.state._state)
    yield
    principal.app.state._state.clear()
    principal.app.state._state.update(guardado)


def _ultima_rota(app) -> str:
    return getattr(app.router.routes[-1], "path", "")


# ----------------------------------------------------------------------------- rotas de cada papel
def test_app_ia_tem_so_webhooks_saude_e_midia():
    from app.entrada_ia import app

    rotas = servidor.rotas_montadas(app)
    assert {"/webhook/helena", "/webhook/helena/{id_escritorio}", "/webhook/helena/{id_escritorio}/ia",
            "/webhook/zapsign/{id_escritorio}", "/saude", "/midia"} <= rotas
    assert not [r for r in rotas if r.startswith(("/api/", "/entrar/", "/lab", "/assets"))]
    assert "/{caminho:path}" not in rotas                     # sem o painel compilado
    assert "/docs" not in rotas and "/openapi.json" not in rotas


def test_app_painel_tem_api_entrada_e_front_sem_webhooks():
    from app.entrada_painel import app

    rotas = servidor.rotas_montadas(app)
    assert "/saude" in rotas and "/midia" in rotas and "/entrar/helena" in rotas
    assert "/api/inicio/metricas" in rotas and "/api/admin/equipe" in rotas
    assert sum(r.startswith("/api/") for r in rotas) > 20
    assert not [r for r in rotas if r.startswith(("/webhook/", "/lab"))]
    assert _ultima_rota(app) == "/{caminho:path}"             # o catch-all fica por último


def test_lab_antigo_so_sobe_no_painel_com_senha(monkeypatch):
    assert not [r for r in servidor.rotas_montadas(servidor.criar_app("painel")) if r.startswith("/lab")]
    monkeypatch.setenv("AGENTESIA_LAB_SENHA", "senha-de-teste")
    assert "/lab/api/mensagem" in servidor.rotas_montadas(servidor.criar_app("painel"))
    assert not [r for r in servidor.rotas_montadas(servidor.criar_app("ia")) if r.startswith("/lab")]


def test_modo_tudo_continua_sendo_o_app_main():
    assert servidor.criar_app("tudo") is principal.app
    tudo = servidor.rotas_montadas(principal.app)
    assert servidor.rotas_montadas(servidor.criar_app("ia")) <= tudo
    painel = servidor.rotas_montadas(servidor.criar_app("painel"))
    assert painel <= tudo
    with pytest.raises(ValueError):
        servidor.criar_app("outro")                            # type: ignore[arg-type]


def test_api_do_painel_nao_muda_o_app_main():
    """Montar os apps por papel não pode tirar nem duplicar rotas do app.main (modo de desenvolvimento)."""
    antes = len(principal.app.router.routes)
    servidor.criar_app("ia")
    servidor.criar_app("painel")
    assert len(principal.app.router.routes) == antes


# ----------------------------------------------------------------------------- subindo com o TestClient
def test_ia_sobe_e_responde_saude_e_webhook():
    from app.entrada_ia import app

    with TestClient(app) as cliente:
        resposta = cliente.get("/saude")
        assert resposta.status_code == 200
        assert resposta.json()["ok"] is True
        assert app.state.papel == "ia"
        # Webhook do escritório: sem segredo é 401; com o segredo derivado e teste=1 responde na hora.
        assert cliente.post(f"/webhook/helena/{UUID}", json={}).status_code == 401
        from app.canal.webhook import segredo_do_escritorio
        ok = cliente.post(f"/webhook/helena/{UUID}?segredo={segredo_do_escritorio(UUID)}&teste=1", json={})
        assert ok.status_code == 200 and ok.json()["feito"] == "teste"
        # Sem banco, o ZapSign recusa com 503 (e não 404: a rota existe no app ia).
        assert cliente.post(f"/webhook/zapsign/{UUID}?segredo={segredo_do_escritorio(UUID, 'zapsign')}",
                            json={}).status_code == 503
        assert cliente.get("/api/inicio/metricas").status_code == 404
        assert cliente.get("/entrar/helena").status_code == 404
        assert cliente.get("/").status_code == 404             # o front não é servido pelo app ia


def test_painel_sobe_sem_banco_e_nao_atende_webhook():
    from app.entrada_painel import app

    with TestClient(app) as cliente:
        resposta = cliente.get("/saude")
        assert resposta.status_code == 200
        assert resposta.json() == {"ok": True, "papel": "painel", "banco_configurado": False,
                                   "modelo": app.state.cfg.modelo_padrao}
        assert app.state.atendimento is None and app.state.tarefas == {}
        assert cliente.post(f"/webhook/helena/{UUID}", json={}).status_code in (404, 405)
        assert cliente.get(f"/webhook/helena/{UUID}").status_code == 404
        assert cliente.get("/api/inicio/metricas").status_code in (401, 403, 503)   # existe, mas pede login
        assert cliente.get("/").status_code in (200, 404)      # 404 só se o painel ainda não foi compilado


class _PoolFalso:
    def __init__(self, falhar: bool = False) -> None:
        self.falhar = falhar

    async def fetchval(self, *_a, **_k):
        if self.falhar:
            raise ConnectionError("banco fora")
        return 1


class _RepoFalso:
    def __init__(self, pool) -> None:
        self._pool = pool
        self.fechado = False

    async def fechar(self) -> None:
        self.fechado = True


@pytest.mark.parametrize("falhar, status", [(False, 200), (True, 503)])
def test_painel_com_banco_nao_liga_lacos_de_fundo(monkeypatch, falhar, status):
    from app.banco import postgres

    criados: list[tuple[int, bool]] = []
    repo = _RepoFalso(_PoolFalso(falhar))

    async def conectar(cls, url, max_conexoes=10, conferir=False):
        criados.append((max_conexoes, conferir))
        return repo

    monkeypatch.setattr(postgres.RepositorioPostgres, "conectar", classmethod(conectar))
    monkeypatch.setenv("AGENTESIA_BANCO_URL", "postgresql://falso/banco")
    monkeypatch.delenv("AGENTESIA_BANCO_CONEXOES", raising=False)
    app = servidor.criar_app("painel")

    with TestClient(app) as cliente:
        assert criados == [(5, True)]                          # pool menor e migrações conferidas na subida
        assert app.state.gestao is not None and app.state.gestao.pool is repo._pool
        assert app.state.atendimento is None and app.state.tarefas == {}
        assert getattr(app.state, "indexar_agora", None) is None
        resposta = cliente.get("/saude")
        assert resposta.status_code == status
        assert resposta.json()["banco"] is (not falhar)
    assert repo.fechado


# ----------------------------------------------------------------------------- artefatos de deploy
@pytest.mark.parametrize("arquivo, modulo", [("Dockerfile.ia", "app.entrada_ia"),
                                             ("Dockerfile.painel", "app.entrada_painel")])
def test_dockerfiles(arquivo, modulo):
    texto = (RAIZ / arquivo).read_text(encoding="utf-8")
    assert "FROM python:3.12-slim" in texto
    assert "USER lawchat" in texto and "useradd" in texto
    assert "HEALTHCHECK" in texto and "/saude" in texto
    assert "${PORT:-8000}" in texto and "os.environ.get('PORT'" in texto
    assert f"uvicorn {modulo}:app" in texto
    importlib.import_module(modulo)
    if arquivo == "Dockerfile.painel":
        assert "FROM node:" in texto and "npm run build" in texto and "/srv/painel/dist" in texto


def test_dockerignore_deixa_de_fora_segredos_e_lixo():
    linhas = {l.strip() for l in (RAIZ / ".dockerignore").read_text(encoding="utf-8").splitlines()}
    for item in (".env", ".venv/", "**/node_modules/", "avaliacao/resultados/", "scratch/", ".backups/"):
        assert item in linhas, item


def test_env_example_lista_as_variaveis_do_deploy_sem_valores_secretos():
    texto = (RAIZ / ".env.example").read_text(encoding="utf-8")
    valores = dict(l.split("=", 1) for l in texto.splitlines() if l and not l.startswith("#") and "=" in l)
    for nome in ("AGENTESIA_BANCO_URL", "AGENTESIA_URL_PUBLICA", "AGENTESIA_WEBHOOK_SEGREDO", "AGENTESIA_SEGREDO_SESSAO",
                 "AGENTESIA_PASTA_MIDIA", "OPENAI_API_KEY", "AGENTESIA_HELENA_TOKEN_LAWCHAT", "AGENTESIA_LAB_SENHA"):
        assert nome in valores, nome
    for segredo in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "AGENTESIA_BANCO_URL", "AGENTESIA_WEBHOOK_SEGREDO",
                    "AGENTESIA_SEGREDO_SESSAO", "AGENTESIA_HELENA_TOKEN_LAWCHAT", "AGENTESIA_HELENA_TOKEN_PARCEIRO",
                    "AGENTESIA_HELENA_HANDOFF_SEGREDO", "AGENTESIA_LAB_SENHA", "AGENTESIA_HELENA_TOKEN"):
        assert valores.get(segredo, "") == "", segredo
