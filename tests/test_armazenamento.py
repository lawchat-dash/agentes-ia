"""Armazenamento da biblioteca de mídia (app/armazenamento.py): disco local e bucket do Supabase Storage.

O Supabase é sempre um httpx.MockTransport: nenhum teste chama a API real. Os testes da rota rodam no Postgres local
(AGENTESIA_TESTE_PG_URL), como os de tests/test_midia_correcoes.py.
"""

import base64
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import httpx
import pytest

from app import armazenamento

SUPA = "https://projeto-teste.supabase.co"
CHAVE = "chave-service-role-de-teste"
OGG = b"OggS" + b"\x00" * 60


class StorageFalso:
    """Faz o papel do /storage/v1 do Supabase."""

    def __init__(self, status_envio: int = 200, status_apagar: int = 200, corpo_apagar: str = "[]") -> None:
        self.pedidos: list[httpx.Request] = []
        self.objetos: dict[str, bytes] = {}
        self.status_envio, self.status_apagar, self.corpo_apagar = status_envio, status_apagar, corpo_apagar

    def __call__(self, pedido: httpx.Request) -> httpx.Response:
        self.pedidos.append(pedido)
        caminho = pedido.url.path.removeprefix("/storage/v1/object/")
        if pedido.method == "POST":
            if self.status_envio >= 300:
                return httpx.Response(self.status_envio, json={"statusCode": str(self.status_envio), "error": "Unauthorized"})
            self.objetos[caminho] = pedido.content
            return httpx.Response(200, json={"Key": caminho})
        if pedido.method == "DELETE":
            self.objetos.pop(caminho, None)
            return httpx.Response(self.status_apagar, text=self.corpo_apagar)
        return httpx.Response(405)


def _supabase(falso: StorageFalso, bucket: str = "agentesia-midia") -> armazenamento.ArmazenamentoSupabase:
    return armazenamento.ArmazenamentoSupabase(SUPA + "/", CHAVE, bucket, transporte=httpx.MockTransport(falso))


# ----------------------------------------------------------------------------- Supabase (unidade)
async def test_supabase_envia_com_service_role_e_content_type_e_devolve_url_publica():
    falso = StorageFalso()
    caminho = "0f8fad5b-d9cb-469f-a165-70867728950e/audio/abc123-objecao.ogg"
    url = await _supabase(falso).enviar(caminho, OGG, "audio/ogg")
    assert url == f"{SUPA}/storage/v1/object/public/agentesia-midia/{caminho}"
    [pedido] = falso.pedidos
    assert pedido.method == "POST" and str(pedido.url) == f"{SUPA}/storage/v1/object/agentesia-midia/{caminho}"
    assert pedido.headers["authorization"] == f"Bearer {CHAVE}" and pedido.headers["apikey"] == CHAVE
    assert pedido.headers["content-type"] == "audio/ogg" and pedido.headers["x-upsert"] == "false"
    assert falso.objetos[f"agentesia-midia/{caminho}"] == OGG


async def test_supabase_recusa_vira_erro_sem_vazar_a_chave():
    with pytest.raises(armazenamento.ErroArmazenamento) as erro:
        await _supabase(StorageFalso(status_envio=403)).enviar("e/video/x-a.mp4", b"x", "video/mp4")
    assert "403" in str(erro.value) and CHAVE not in str(erro.value)
    assert CHAVE not in repr(_supabase(StorageFalso()))

    def fora_do_ar(pedido):
        raise httpx.ConnectError("sem rede", request=pedido)

    fora = armazenamento.ArmazenamentoSupabase(SUPA, CHAVE, transporte=httpx.MockTransport(fora_do_ar))
    with pytest.raises(armazenamento.ErroArmazenamento, match="fora do ar"):
        await fora.enviar("e/imagem/x-a.png", b"x", "image/png")


async def test_supabase_apaga_o_objeto_e_tolera_o_que_ja_nao_existe():
    falso = StorageFalso()
    await _supabase(falso).apagar("e/audio/x-a.ogg")
    [pedido] = falso.pedidos
    assert pedido.method == "DELETE" and str(pedido.url) == f"{SUPA}/storage/v1/object/agentesia-midia/e/audio/x-a.ogg"
    assert pedido.headers["authorization"] == f"Bearer {CHAVE}"
    await _supabase(StorageFalso(status_apagar=404)).apagar("e/audio/sumiu.ogg")
    await _supabase(StorageFalso(status_apagar=400, corpo_apagar='{"error":"not_found","message":"Object not found"}')
                    ).apagar("e/audio/sumiu.ogg")
    with pytest.raises(armazenamento.ErroArmazenamento, match="500"):
        await _supabase(StorageFalso(status_apagar=500, corpo_apagar="erro")).apagar("e/audio/x-a.ogg")


def test_url_publica_e_caminho_da_url():
    supa = armazenamento.ArmazenamentoSupabase(SUPA, CHAVE, "meu-bucket")
    url = supa.url_publica("e/video/1-a.mp4")
    assert url == f"{SUPA}/storage/v1/object/public/meu-bucket/e/video/1-a.mp4"
    assert supa.caminho_da_url(url) == "e/video/1-a.mp4"
    assert supa.caminho_da_url("https://ia.exemplo.com/midia/e/video/1-a.mp4") is None
    assert supa.caminho_da_url(f"{SUPA}/storage/v1/object/public/outro/e/video/1-a.mp4") is None


def test_escolha_pelo_ambiente(monkeypatch, tmp_path):
    for nome in ("AGENTESIA_MIDIA_ARMAZENAMENTO", "AGENTESIA_SUPABASE_URL", "AGENTESIA_SUPABASE_SERVICE_KEY",
                 "AGENTESIA_MIDIA_BUCKET"):
        monkeypatch.delenv(nome, raising=False)
    monkeypatch.setenv("AGENTESIA_PASTA_MIDIA", str(tmp_path))
    assert armazenamento.modo() == "local" and isinstance(armazenamento.do_ambiente(), armazenamento.ArmazenamentoLocal)

    monkeypatch.setenv("AGENTESIA_MIDIA_ARMAZENAMENTO", "supabase")
    with pytest.raises(armazenamento.ErroArmazenamento, match="AGENTESIA_SUPABASE_SERVICE_KEY"):
        armazenamento.do_ambiente()
    monkeypatch.setenv("AGENTESIA_SUPABASE_URL", SUPA)
    monkeypatch.setenv("AGENTESIA_SUPABASE_SERVICE_KEY", CHAVE)
    escolhido = armazenamento.do_ambiente()
    assert isinstance(escolhido, armazenamento.ArmazenamentoSupabase) and escolhido.bucket == "agentesia-midia"
    monkeypatch.setenv("AGENTESIA_MIDIA_BUCKET", "outro-bucket")
    assert armazenamento.do_ambiente().bucket == "outro-bucket"

    # Mídia antiga (URL local) continua no disco; a nova, no bucket.
    assert isinstance(armazenamento.de_uma_midia("https://ia.exemplo.com/midia/e/audio/1700-a.ogg"),
                      armazenamento.ArmazenamentoLocal)
    assert isinstance(armazenamento.de_uma_midia(f"{SUPA}/storage/v1/object/public/outro-bucket/e/audio/a.ogg"),
                      armazenamento.ArmazenamentoSupabase)
    assert armazenamento.de_uma_midia("https://x.supabase.co/storage/v1/object/public/agent-media/a.ogg") is None

    monkeypatch.setenv("AGENTESIA_MIDIA_ARMAZENAMENTO", "s3")
    with pytest.raises(armazenamento.ErroArmazenamento, match="inválido"):
        armazenamento.modo()


# ----------------------------------------------------------------------------- local
async def test_local_grava_serve_pela_url_publica_e_apaga(tmp_path):
    local = armazenamento.ArmazenamentoLocal(tmp_path, "https://ia.exemplo.com/")
    url = await local.enviar("e/audio/1-a.ogg", OGG, "audio/ogg")
    assert url == "https://ia.exemplo.com/midia/e/audio/1-a.ogg"
    assert (tmp_path / "e/audio/1-a.ogg").read_bytes() == OGG
    await local.apagar("e/audio/1-a.ogg")
    assert not (tmp_path / "e/audio/1-a.ogg").exists()
    await local.apagar("e/audio/1-a.ogg")                       # já apagado: sem erro
    with pytest.raises(armazenamento.ErroArmazenamento):
        await local.enviar("../fora.ogg", OGG, "audio/ogg")
    fora = tmp_path.parent / f"nao-apagar-{uuid.uuid4().hex}.txt"
    fora.write_text("x")
    await local.apagar(f"../{fora.name}")                       # caminho fora da pasta: ignora
    assert fora.exists()
    fora.unlink()


def test_midia_local_so_e_montada_no_modo_local():
    """Processo novo: o /midia é montado na importação do app.main, conforme AGENTESIA_MIDIA_ARMAZENAMENTO."""
    codigo = ("from app import servidor; "
              "print(sorted(r for r in servidor.rotas_montadas(servidor.criar_app('{papel}')) if r == '/midia'))")
    raiz = Path(__file__).resolve().parents[1]
    for modo, esperado in (("supabase", "[]"), ("local", "['/midia']")):
        ambiente = {**os.environ, "AGENTESIA_MIDIA_ARMAZENAMENTO": modo, "PYTHONIOENCODING": "utf-8"}
        ambiente.pop("AGENTESIA_SUPABASE_SERVICE_KEY", None)
        for papel in ("ia", "painel"):
            saida = subprocess.run([sys.executable, "-c", codigo.format(papel=papel)], cwd=raiz, env=ambiente,
                                   capture_output=True, text=True, timeout=120)
            assert saida.returncode == 0, saida.stderr[-2000:]
            assert saida.stdout.strip().splitlines()[-1] == esperado, (modo, papel)


# ----------------------------------------------------------------------------- rota da biblioteca (Postgres)
URL_PG = os.environ.get("AGENTESIA_TESTE_PG_URL")
precisa_pg = pytest.mark.skipif(not URL_PG, reason="sem AGENTESIA_TESTE_PG_URL")

if URL_PG:
    from tests.test_gestao import _entrar, ambiente  # noqa: F401  (fixture do painel com Postgres local)


def _b64(dados: bytes) -> str:
    return base64.b64encode(dados).decode()


@precisa_pg
async def test_biblioteca_no_bucket_envia_apaga_e_protege_a_midia_em_uso(ambiente, monkeypatch):
    cliente, _simulada, email_admin, banco = ambiente
    falso = StorageFalso()
    monkeypatch.setattr(armazenamento, "TRANSPORTE", httpx.MockTransport(falso))
    monkeypatch.setenv("AGENTESIA_MIDIA_ARMAZENAMENTO", "supabase")
    monkeypatch.setenv("AGENTESIA_SUPABASE_URL", SUPA)
    monkeypatch.delenv("AGENTESIA_SUPABASE_SERVICE_KEY", raising=False)
    monkeypatch.delenv("AGENTESIA_MIDIA_BUCKET", raising=False)
    await _entrar(cliente, email_admin, "senha-admin-123")
    escritorio = (await cliente.post("/api/admin/escritorios", json={
        "nome": "Bucket Ltda", "id_conta_helena": str(uuid.uuid4()), "token_helena": "token-bom-" + uuid.uuid4().hex[:8]})).json()["escritorio"]
    h = {"x-escritorio": escritorio["id"]}

    async def subir(nome, dados, mime=None):
        return await cliente.post("/api/midia", headers=h, json={"nome": nome, "conteudo_base64": _b64(dados), "mime": mime})

    sem_chave = await subir("objecao.ogg", OGG)                   # modo supabase sem a chave: aviso claro, nada gravado
    assert sem_chave.status_code == 409 and "AGENTESIA_SUPABASE_SERVICE_KEY" in sem_chave.json()["detail"]
    monkeypatch.setenv("AGENTESIA_SUPABASE_SERVICE_KEY", CHAVE)
    monkeypatch.setenv("AGENTESIA_URL_PUBLICA", "")                # no bucket não depende do endereço do app ia

    # Validação de formato e tamanho continua antes de qualquer envio ao Storage.
    assert (await subir("objecao.wav", b"RIFF\x00\x00\x00\x00WAVE")).status_code == 400
    assert (await subir("rg.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * (5 * 1024 * 1024))).status_code == 413
    assert falso.pedidos == []

    resposta = await subir("Objeção Honorários.ogg", OGG, mime="application/octet-stream")
    assert resposta.status_code == 200, resposta.text
    midia = resposta.json()
    assert re.fullmatch(rf"{escritorio['id']}/audio/[0-9a-f]{{32}}-objecao-honorarios\.ogg", midia["caminho_storage"])
    assert midia["url"] == f"{SUPA}/storage/v1/object/public/agentesia-midia/{midia['caminho_storage']}"
    assert midia["mime_type"] == "audio/ogg"
    [envio] = falso.pedidos
    assert envio.method == "POST" and envio.headers["content-type"] == "audio/ogg"
    assert falso.objetos[f"agentesia-midia/{midia['caminho_storage']}"] == OGG

    # Storage recusou: 502 e nenhuma linha nova.
    falso.status_envio = 403
    antes = await banco._pool.fetchval("select count(*) from agentesia_biblioteca_midia where id_escritorio = $1::uuid",
                                       escritorio["id"])
    recusado = await subir("video.mp4", b"\x00\x00\x00\x18ftypisom" + b"\x00" * 60)
    assert recusado.status_code == 502 and CHAVE not in recusado.text
    assert await banco._pool.fetchval("select count(*) from agentesia_biblioteca_midia where id_escritorio = $1::uuid",
                                      escritorio["id"]) == antes
    falso.status_envio = 200

    # Em uso no roteiro: não apaga, nem no bucket.
    pool = banco._pool
    canal = await pool.fetchval(
        "insert into agentesia_canais (id_escritorio, numero_normalizado, id_canal_helena) values ($1::uuid, $2, $3) returning id",
        escritorio["id"], "55119" + str(uuid.uuid4().int)[:8], "ch-" + uuid.uuid4().hex[:10])
    agente = await pool.fetchval(
        "insert into agentesia_agentes (id_escritorio, id_canal, nome, situacao, config) values ($1::uuid, $2, 'Bia', 'ativo', '{}'::jsonb) returning id",
        escritorio["id"], canal)
    await pool.execute("insert into agentesia_agente_etapas (id_agente, codigo, ordem, principal, instrucao) values ($1, 'sdr', 1, true, $2)",
                       agente, f"Envie o áudio:\n{midia['url']}")
    falso.pedidos.clear()
    em_uso = await cliente.delete(f"/api/midia/{midia['id']}", headers=h)
    assert em_uso.status_code == 409 and "Bia" in em_uso.json()["detail"]
    assert falso.pedidos == [] and f"agentesia-midia/{midia['caminho_storage']}" in falso.objetos
    assert await pool.fetchval("select count(*) from agentesia_biblioteca_midia where id = $1::uuid", midia["id"]) == 1

    # Storage fora: a linha fica para tentar de novo.
    await pool.execute("update agentesia_agente_etapas set instrucao = 'Sem áudio.' where id_agente = $1", agente)
    falso.status_apagar, falso.corpo_apagar = 500, "erro"
    assert (await cliente.delete(f"/api/midia/{midia['id']}", headers=h)).status_code == 502
    assert await pool.fetchval("select count(*) from agentesia_biblioteca_midia where id = $1::uuid", midia["id"]) == 1

    falso.status_apagar, falso.corpo_apagar = 200, "[]"
    falso.pedidos.clear()
    livre = await cliente.delete(f"/api/midia/{midia['id']}", headers=h)
    assert livre.status_code == 200
    [apagar] = falso.pedidos
    assert apagar.method == "DELETE" and apagar.url.path.endswith(midia["caminho_storage"])
    assert await pool.fetchval("select count(*) from agentesia_biblioteca_midia where id = $1::uuid", midia["id"]) == 0

    # Mídia antiga, gravada no disco com URL /midia/...: aparece na lista e apaga o arquivo local, sem chamar o bucket.
    pasta = Path(os.environ["AGENTESIA_PASTA_MIDIA"])
    antigo = f"{escritorio['id']}/audio/1700000000000-antigo.ogg"
    (pasta / antigo).parent.mkdir(parents=True, exist_ok=True)
    (pasta / antigo).write_bytes(OGG)
    id_antigo = await pool.fetchval(
        """insert into agentesia_biblioteca_midia (id_escritorio, nome, tipo, url, caminho_storage, mime_type, tamanho_bytes)
           values ($1::uuid, 'antigo', 'audio', $2, $3, 'audio/ogg', $4) returning id""",
        escritorio["id"], f"https://ia.exemplo.com/midia/{antigo}", antigo, len(OGG))
    lista = (await cliente.get("/api/midia", headers=h)).json()["itens"]
    assert any(i["id"] == str(id_antigo) for i in lista)
    falso.pedidos.clear()
    assert (await cliente.delete(f"/api/midia/{id_antigo}", headers=h)).status_code == 200
    assert falso.pedidos == [] and not (pasta / antigo).exists()


@precisa_pg
async def test_biblioteca_no_modo_local_continua_gravando_no_disco(ambiente, monkeypatch):
    cliente, _simulada, email_admin, _banco = ambiente
    monkeypatch.delenv("AGENTESIA_MIDIA_ARMAZENAMENTO", raising=False)
    await _entrar(cliente, email_admin, "senha-admin-123")
    escritorio = (await cliente.post("/api/admin/escritorios", json={
        "nome": "Disco Ltda", "id_conta_helena": str(uuid.uuid4()), "token_helena": "token-bom-" + uuid.uuid4().hex[:8]})).json()["escritorio"]
    h = {"x-escritorio": escritorio["id"]}
    resposta = await cliente.post("/api/midia", headers=h, json={"nome": "foto.png", "conteudo_base64": _b64(b"\x89PNG" + b"\x00" * 40)})
    assert resposta.status_code == 200, resposta.text
    midia = resposta.json()
    assert midia["url"] == f"https://ia.exemplo.com/midia/{midia['caminho_storage']}"
    arquivo = Path(os.environ["AGENTESIA_PASTA_MIDIA"]) / midia["caminho_storage"]
    assert arquivo.exists()
    assert (await cliente.delete(f"/api/midia/{midia['id']}", headers=h)).status_code == 200
    assert not arquivo.exists()
