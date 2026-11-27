"""Verificação de ponta a ponta do roteiro de gravação no ARMAZENAMENTO REAL (bucket do Supabase de produção).

Só roda quando pedida (não entra na suíte normal):
    AGENTESIA_TESTE_PG_URL=postgresql://...  AGENTESIA_VERIFICAR_BUCKET=1  python -m pytest -q tests/test_roteiro_verificacao_real.py -s

Simula o que uma pessoa faz: o superadmin monta o roteiro de um produto; dois escritórios (A e B) gravam/anexam todas as
partes com arquivos de verdade (mp3, wav, ogg/vorbis, mov do iPhone, webm do Chrome); e confere, para cada arquivo:
  - foi para o bucket, na pasta do PRÓPRIO escritório (<id do escritório>/audio|video/<código único>-<nn>-<nome da parte>);
  - o link é público: baixa de fora sem login, com o tipo certo e no formato que o WhatsApp entrega (Opus / H.264+AAC);
  - a conferência de link do motor (a mesma de antes de cada envio) deixa enviar;
  - os links de A e B nunca se misturam: cada um só vê, grava e apaga o que é seu; no prompt de B, o motor só deixa sair
    os links de B (um link de A é barrado como "fora do roteiro");
  - a gravação "Contrato assinado" vira a mídia pós-assinatura da ZapSign do escritório (sem passar por cima da escolhida).
No fim apaga tudo e confere que os arquivos saíram do bucket.

O banco é o de teste (AGENTESIA_TESTE_PG_URL). As chaves do Supabase são lidas do .env.producao local (nunca impressas).
"""
import base64
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

import httpx
import pytest

RAIZ = Path(__file__).resolve().parents[1]
URL_PG = os.environ.get("AGENTESIA_TESTE_PG_URL")
LIGADO = os.environ.get("AGENTESIA_VERIFICAR_BUCKET") == "1"
pytestmark = pytest.mark.skipif(not (URL_PG and LIGADO and shutil.which("ffmpeg")),
                                reason="verificação real: AGENTESIA_TESTE_PG_URL + AGENTESIA_VERIFICAR_BUCKET=1 + ffmpeg")

if URL_PG and LIGADO:
    from tests.test_gestao import _entrar, ambiente  # noqa: F401  (fixture do painel com Postgres local)

CHAVES_SUPABASE = ("AGENTESIA_SUPABASE_URL", "AGENTESIA_SUPABASE_SERVICE_KEY", "AGENTESIA_MIDIA_BUCKET")


def _env_producao() -> dict[str, str]:
    valores = {}
    caminho = RAIZ / ".env.producao"
    if caminho.exists():
        for linha in caminho.read_text(encoding="utf-8").splitlines():
            if "=" in linha and linha.split("=", 1)[0] in CHAVES_SUPABASE:
                valores[linha.split("=", 1)[0]] = linha.split("=", 1)[1].strip().strip('"')
    return valores


def _gerar(destino: str, argumentos: list[str]) -> bytes:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *argumentos, destino], check=True)
    return Path(destino).read_bytes()


def _arquivos(pasta: str) -> dict[str, tuple[bytes, str, str]]:
    """nome -> (bytes, mime, nome do arquivo). Voz de mentira com variação (passa no "ficou bom?")."""
    voz = ["-f", "lavfi", "-i", "sine=frequency=220:duration=5", "-f", "lavfi", "-i", "anoisesrc=d=5:c=pink:a=0.05",
           "-filter_complex", "[0][1]amix=inputs=2,volume=3"]
    video = ["-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30", "-f", "lavfi", "-i", "sine=frequency=330", "-t", "4"]
    p = lambda n: os.path.join(pasta, n)  # noqa: E731
    return {
        "mp3": (_gerar(p("a.mp3"), voz), "audio/mpeg", "honorarios.mp3"),
        "wav": (_gerar(p("a.wav"), voz), "audio/wav", "como-funciona.wav"),
        "vorbis": (_gerar(p("a.ogg"), [*voz, "-c:a", "libvorbis"]), "audio/ogg", "objecao.ogg"),
        "mov": (_gerar(p("v.mov"), [*video, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-f", "mov"]),
                "video/quicktime", "recepcao.mov"),
        "webm": (_gerar(p("v.webm"), [*video, "-c:v", "libvpx", "-c:a", "libopus"]), "video/webm", "gravacao.webm"),
    }


async def _codecs(bruto: bytes, sufixo: str):
    from app.midia.conversao import codecs
    return await codecs(bruto, sufixo)


async def test_roteiro_no_bucket_real_isolado_por_escritorio(ambiente, monkeypatch):  # noqa: F811
    supa = _env_producao()
    if not all(supa.get(k) for k in CHAVES_SUPABASE[:2]):
        pytest.skip("sem as chaves do Supabase no .env.producao")
    for chave, valor in supa.items():
        monkeypatch.setenv(chave, valor)
    monkeypatch.setenv("AGENTESIA_MIDIA_ARMAZENAMENTO", "supabase")
    bucket = supa.get("AGENTESIA_MIDIA_BUCKET") or "agentesia-midia"
    base_publica = f"{supa['AGENTESIA_SUPABASE_URL'].rstrip('/')}/storage/v1/object/public/{bucket}/"

    cliente, _simulada, email_admin, banco = ambiente
    from app.gestao.rotas_roteiro_gravacao import api
    cliente._transport.app.include_router(api)
    await _entrar(cliente, email_admin, "senha-admin-123")
    pool = banco._pool

    # ---------------------------------------------------------------- 1. superadmin monta o roteiro do produto
    produto = str(await pool.fetchval(
        """insert into agentesia_biblioteca_produtos (slug, nome, status, modo_midia, objecoes)
           values ($1, 'Verificação Auxílio', 'publicado', 'audio', $2::jsonb) returning id""",
        f"verif-{uuid.uuid4().hex[:8]}",
        '[{"titulo": "OBJ 3 — Está caro", "resposta": "[[audio:Objeção - Está caro]]\\n\\nVocê não paga nada para iniciar."}]'))
    await pool.execute(
        "insert into agentesia_biblioteca_agentes (id_produto_biblioteca, papel, nome_exibicao, texto_prompt) values ($1::uuid, 'sdr', 'SDR', $2)",
        produto, "Comece com [[audio:Video Inicial]].\nExplique: [[audio:Como Funciona o Auxílio-Acidente]]\nHonorários: [[audio:Honorários]]")
    roteiro = (await cliente.post(f"/api/admin/biblioteca/produtos/{produto}/roteiro/puxar")).json()
    assert roteiro["criadas"] == 4, roteiro
    partes = {p["marcador"]: p for p in roteiro["partes"]}
    assert partes["Video Inicial"]["tipo"] == "video"                     # "vídeo" no nome vira parte de vídeo
    assert partes["Objeção - Está caro"]["secao"] == "objecoes"
    contrato = (await cliente.post(f"/api/admin/biblioteca/produtos/{produto}/roteiro/partes", json={
        "titulo": "Contrato assinado", "tipo": "audio", "secao": "principais", "chave_geral": "contrato_assinado",
        "texto": "Acabei de ver aqui que você assinou o contrato."})).json()

    # ---------------------------------------------------------------- 2. dois escritórios gravam tudo
    escritorios = {}
    for nome in ("A", "B"):
        esc = (await cliente.post("/api/admin/escritorios", json={
            "nome": f"Verificação {nome}", "id_conta_helena": str(uuid.uuid4()),
            "token_helena": "token-bom-" + uuid.uuid4().hex[:8]})).json()["escritorio"]
        escritorios[nome] = esc["id"]
    # A tem ZapSign com a mídia pós-assinatura vazia; B escolheu um vídeo próprio (não pode ser trocado).
    for nome, config in (("A", "{}"), ("B", '{"midia_pos_assinatura": {"url": "https://exemplo.com/escolhido.mp4"}}')):
        await pool.execute("insert into agentesia_integracoes (id_escritorio, tipo, config, situacao) values ($1::uuid, 'zapsign', $2::jsonb, 'ok')",
                           escritorios[nome], config)

    gravado: dict[str, dict[str, dict]] = {"A": {}, "B": {}}
    with tempfile.TemporaryDirectory() as pasta:
        arquivos = _arquivos(pasta)
        plano = {"Video Inicial": "mov", "Como Funciona o Auxílio-Acidente": "wav", "Honorários": "mp3",
                 "Objeção - Está caro": "vorbis"}
        for nome, id_esc in escritorios.items():
            h = {"x-escritorio": id_esc}
            for marcador, formato in plano.items():
                bruto, mime, arquivo = arquivos["webm" if (nome == "B" and formato == "mov") else formato]
                r = await cliente.post(f"/api/roteiro-gravacao/partes/{partes[marcador]['id']}", headers=h, json={
                    "conteudo_base64": base64.b64encode(bruto).decode(), "mime": mime, "nome": arquivo,
                    "duracao_s": 5, "qualidade": "boa"})
                assert r.status_code == 200, (nome, marcador, r.text)
                gravado[nome][marcador] = r.json()["gravacao"]
            r = await cliente.post(f"/api/roteiro-gravacao/partes/{contrato['id']}", headers=h, json={
                "conteudo_base64": base64.b64encode(arquivos["mp3"][0]).decode(), "mime": "audio/mpeg", "nome": "parabens.mp3"})
            assert r.status_code == 200, r.text
            gravado[nome]["Contrato assinado"] = r.json()["gravacao"]
            gravado[nome]["_pos"] = r.json()["pos_assinatura"]

    try:
        # ------------------------------------------------------------ 3. bucket, pasta da conta, link público, formato
        from app.midia.link import ConferirLink
        conferir = ConferirLink(timeout_s=20)
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as internet:
            for nome, id_esc in escritorios.items():
                for marcador, g in gravado[nome].items():
                    if marcador.startswith("_"):
                        continue
                    url = g["url"]
                    assert url.startswith(base_publica + f"{id_esc}/"), f"{nome}/{marcador}: fora da pasta da conta: {url}"
                    assert f"/{id_esc}/{'video' if g['tipo'] == 'video' else 'audio'}/" in url
                    arquivo = url.rsplit("/", 1)[-1]
                    assert arquivo[:32].isalnum() and len(arquivo.split("-", 1)[0]) == 32, f"sem código único: {arquivo}"
                    resposta = await internet.get(url)                          # de fora, sem login
                    assert resposta.status_code == 200, f"{nome}/{marcador}: link não é público ({resposta.status_code})"
                    tipo_http = resposta.headers.get("content-type", "")
                    assert tipo_http.startswith("video/mp4" if g["tipo"] == "video" else "audio/"), (marcador, tipo_http)
                    assert len(resposta.content) == g["tamanho_bytes"] and len(resposta.content) <= 16 * 1024 * 1024
                    sufixo = "." + arquivo.rsplit(".", 1)[-1]
                    video, audio = await _codecs(resposta.content, sufixo) or (None, None)
                    if g["tipo"] == "video":
                        assert (video, audio) == ("h264", "aac"), f"{marcador}: {video}/{audio}"
                    elif sufixo == ".ogg":
                        assert audio == "opus", f"{marcador}: ogg em {audio}"    # mensagem de voz do WhatsApp
                    assert await conferir(url, g["tipo"]) is None, f"{nome}/{marcador}: o motor não deixaria enviar"

        # ------------------------------------------------------------ 4. cada conta só vê e mexe no que é seu
        urls = {n: {m: g["url"] for m, g in gravado[n].items() if not m.startswith("_")} for n in gravado}
        assert not set(urls["A"].values()) & set(urls["B"].values())
        visto_por_b = (await cliente.get(f"/api/roteiro-gravacao/{produto}", headers={"x-escritorio": escritorios["B"]})).json()
        assert {p["gravacao"]["url"] for p in visto_por_b["partes"] if p["gravacao"]} == set(urls["B"].values())
        midia_b = (await cliente.get("/api/midia", headers={"x-escritorio": escritorios["B"]})).json()["itens"]
        assert not {i["url"] for i in midia_b} & set(urls["A"].values())
        pastas_b = {i.get("pasta") for i in midia_b}
        assert pastas_b == {"Roteiros gravados/Verificação Auxílio", "Roteiros gravados/Gerais"}, pastas_b

        # ------------------------------------------------------------ 5. prompt de B: só os links de B saem
        from app.cerebro import catalogo
        texto_sdr = await pool.fetchval("select texto_prompt from agentesia_biblioteca_agentes where id_produto_biblioteca = $1::uuid", produto)
        prompt_b = texto_sdr
        for p in visto_por_b["partes"]:                                         # o que a ativação faz ao confirmar
            if p["marcador"] and p["gravacao"]:
                prompt_b = prompt_b.replace(f"[[audio:{p['marcador']}]]", p["gravacao"]["url"])
        assert "[[" not in prompt_b and urls["B"]["Honorários"] in prompt_b
        permitidas = catalogo.midias_permitidas(prompt_b)
        assert {catalogo.normalizar_url(u) for m, u in urls["B"].items() if m in plano and m != "Objeção - Está caro"} <= permitidas
        fora = catalogo.midias_fora_do_roteiro(
            [{"tipo": "midia", "url": urls["A"]["Honorários"]}, {"tipo": "midia", "url": urls["B"]["Honorários"]}], permitidas)
        assert fora == [urls["A"]["Honorários"]], "o motor deixaria sair o link de outro escritório"

        # ------------------------------------------------------------ 6. contrato assinado -> pós-assinatura da ZapSign
        cfg = lambda n: pool.fetchval("select config->'midia_pos_assinatura'->>'url' from agentesia_integracoes "  # noqa: E731
                                      "where id_escritorio = $1::uuid and tipo = 'zapsign'", escritorios[n])
        assert gravado["A"]["_pos"] is True and await cfg("A") == urls["A"]["Contrato assinado"]
        assert gravado["B"]["_pos"] is False and await cfg("B") == "https://exemplo.com/escolhido.mp4"
    finally:
        # ------------------------------------------------------------ 7. limpeza: apaga e confere que saiu do bucket
        for nome, id_esc in escritorios.items():
            for marcador in list(plano) + ["Contrato assinado"]:
                id_parte = contrato["id"] if marcador == "Contrato assinado" else partes[marcador]["id"]
                await cliente.delete(f"/api/roteiro-gravacao/partes/{id_parte}", headers={"x-escritorio": id_esc})
        # Confere no próprio bucket (rota autenticada): o link público pode seguir abrindo um tempo pelo cache da CDN do
        # Supabase depois de apagado, então ele não serve para provar que o arquivo saiu.
        chave = supa["AGENTESIA_SUPABASE_SERVICE_KEY"]
        async with httpx.AsyncClient(timeout=30, headers={"Authorization": f"Bearer {chave}", "apikey": chave}) as storage:
            for id_esc in escritorios.values():
                for sub in ("audio", "video"):
                    r = await storage.post(f"{supa['AGENTESIA_SUPABASE_URL'].rstrip('/')}/storage/v1/object/list/{bucket}",
                                           json={"prefix": f"{id_esc}/{sub}/", "limit": 100})
                    assert r.status_code == 200 and r.json() == [], f"ficou no bucket: {id_esc}/{sub}: {r.text[:200]}"
        assert await pool.fetchval("select config->'midia_pos_assinatura'->>'url' from agentesia_integracoes "
                                   "where id_escritorio = $1::uuid and tipo = 'zapsign'", escritorios["A"]) is None
        await pool.execute("delete from agentesia_biblioteca_produtos where id = $1::uuid", produto)
