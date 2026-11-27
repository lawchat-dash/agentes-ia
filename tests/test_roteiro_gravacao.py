"""Roteiro de gravação por produto (migração 019): partes no admin, gravação do escritório, parte geral e plano."""
import base64
import os
import shutil
import subprocess
import tempfile
import uuid

import pytest

from app.gestao.rotas_roteiro_gravacao import marcadores_do_texto, normalizar

URL_PG = os.environ.get("AGENTESIA_TESTE_PG_URL")
precisa_pg = pytest.mark.skipif(not URL_PG, reason="sem AGENTESIA_TESTE_PG_URL")
precisa_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="sem ffmpeg")

if URL_PG:
    from tests.test_gestao import _entrar, ambiente  # noqa: F401  (fixture do painel com Postgres local)

OGG = b"OggS" + b"\x00" * 60


def test_marcadores_e_normalizacao():
    texto = "Envie [[audio:Honorários]] e depois \\[\\[video:Video Inicial\\]\\]. De novo [[áudio: honorarios ]] [[midia:objecao_caro]]"
    assert marcadores_do_texto(texto) == [("audio", "Honorários"), ("video", "Video Inicial"), ("audio", "objecao_caro")]
    assert normalizar(" Honorários_ ") == "honorarios"


def _b64(dados: bytes) -> str:
    return base64.b64encode(dados).decode()


def _video_webm() -> bytes:
    with tempfile.TemporaryDirectory() as pasta:
        destino = os.path.join(pasta, "v.webm")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15",
                        "-f", "lavfi", "-i", "sine=frequency=440", "-t", "2", "-c:v", "libvpx", "-c:a", "libopus", destino],
                       check=True)
        with open(destino, "rb") as arquivo:
            return arquivo.read()


async def _produto(pool, nome: str) -> str:
    produto = str(await pool.fetchval(
        """insert into agentesia_biblioteca_produtos (slug, nome, status, modo_midia, faq)
           values ($1, $2, 'publicado', 'audio', $3::jsonb) returning id""",
        f"teste-{uuid.uuid4().hex[:8]}", nome, '[{"pergunta": "Quanto custa?", "resposta": "[[audio:Honorários]]"}]'))
    await pool.execute(
        """insert into agentesia_biblioteca_agentes (id_produto_biblioteca, papel, nome_exibicao, texto_prompt)
           values ($1::uuid, 'sdr', 'SDR', $2)""",
        produto, "Comece com [[video:Video Inicial]].\nDepois [[audio:Como funciona]] e se achar caro [[audio:objecao_caro]].")
    return produto


@precisa_pg
async def test_roteiro_do_admin_a_gravacao(ambiente):
    cliente, _simulada, email_admin, banco = ambiente
    from app.gestao.rotas_roteiro_gravacao import api
    cliente._transport.app.include_router(api)
    await _entrar(cliente, email_admin, "senha-admin-123")
    pool = banco._pool
    escritorio = (await cliente.post("/api/admin/escritorios", json={
        "nome": "Roteiro Adv", "id_conta_helena": str(uuid.uuid4()), "token_helena": "token-bom-" + uuid.uuid4().hex[:8]})).json()["escritorio"]
    h = {"x-escritorio": escritorio["id"]}
    a = await _produto(pool, "Auxílio Teste")
    b = await _produto(pool, "BPC Teste")

    # Admin: marcadores achados nos textos do produto e dos agentes; "puxar" cria uma parte para cada.
    r = (await cliente.get(f"/api/admin/biblioteca/produtos/{a}/roteiro")).json()
    assert [(m["tipo"], m["nome"]) for m in r["marcadores"]] == [
        ("audio", "Honorários"), ("video", "Video Inicial"), ("audio", "Como funciona"), ("audio", "objecao_caro")]
    puxado = (await cliente.post(f"/api/admin/biblioteca/produtos/{a}/roteiro/puxar")).json()
    assert puxado["criadas"] == 4 and all(m["tem_parte"] for m in puxado["marcadores"])
    secoes = {p["marcador"]: (p["tipo"], p["secao"]) for p in puxado["partes"]}
    assert secoes["Video Inicial"] == ("video", "videos") and secoes["objecao_caro"] == ("audio", "objecoes")
    assert (await cliente.post(f"/api/admin/biblioteca/produtos/{a}/roteiro/puxar")).json()["criadas"] == 0

    # O vídeo inicial é parte geral (mesma chave nos dois produtos); o texto fica editável.
    video_a = next(p for p in puxado["partes"] if p["marcador"] == "Video Inicial")
    mudada = (await cliente.patch(f"/api/admin/roteiro/partes/{video_a['id']}",
                                  json={"chave_geral": "Vídeo inicial", "texto": "Olá, eu sou..."})).json()
    assert mudada["chave_geral"] == "video_inicial"
    await cliente.post(f"/api/admin/biblioteca/produtos/{b}/roteiro/puxar")
    partes_b = (await cliente.get(f"/api/admin/biblioteca/produtos/{b}/roteiro")).json()["partes"]
    video_b = next(p for p in partes_b if p["marcador"] == "Video Inicial")
    await cliente.patch(f"/api/admin/roteiro/partes/{video_b['id']}", json={"chave_geral": "video_inicial"})
    assert (await cliente.put(f"/api/admin/biblioteca/produtos/{a}/roteiro/orientacoes", json={"texto": "Grave num lugar calmo."})).status_code == 200

    # Escritório: lista com progresso.
    meus = (await cliente.get("/api/roteiro-gravacao", headers=h)).json()
    assert meus["liberado"] is True
    item_a = next(p for p in meus["produtos"] if p["id"] == a)
    assert (item_a["total"], item_a["gravadas"], item_a["videos"], item_a["audios"]) == (4, 0, 1, 3)
    detalhe = (await cliente.get(f"/api/roteiro-gravacao/{a}", headers=h)).json()
    assert detalhe["produto"]["roteiro_orientacoes"] == "Grave num lugar calmo."

    # Grava o áudio dos honorários: entra na biblioteca na pasta do produto, com o nome da parte.
    honorarios = next(p for p in detalhe["partes"] if p["marcador"] == "Honorários")
    g = await cliente.post(f"/api/roteiro-gravacao/partes/{honorarios['id']}", headers=h,
                           json={"conteudo_base64": _b64(OGG), "mime": "audio/ogg", "duracao_s": 12, "qualidade": "boa"})
    assert g.status_code == 200, g.text
    grav = g.json()["gravacao"]
    assert grav["url"].endswith(".ogg") and grav["qualidade"] == "boa"
    midia = await pool.fetchrow("select nome, pasta from agentesia_biblioteca_midia where id = $1::uuid", grav["id_midia"])
    assert midia["pasta"] == "Roteiros gravados/Auxílio Teste" and midia["nome"].endswith("Honorários")

    # Regravar substitui (uma gravação por parte) e apaga o arquivo antigo. As medidas do navegador fora da faixa
    # (MP3/M4A decodificado passa de 1,0 no pico) são ajustadas, nunca barram o envio ("Algum campo está inválido: pico").
    r2 = await cliente.post(f"/api/roteiro-gravacao/partes/{honorarios['id']}", headers=h,
                            json={"conteudo_base64": _b64(OGG), "mime": "audio/ogg", "pico": 1.0234, "silencio_pct": 100.4,
                                  "duracao_s": -0.1})
    assert r2.status_code == 200, r2.text
    g2 = r2.json()["gravacao"]
    medidas = await pool.fetchrow("select pico, silencio_pct, duracao_s from agentesia_roteiro_gravacoes where id_midia = $1::uuid",
                                  g2["id_midia"])
    assert float(medidas["pico"]) == 1 and float(medidas["silencio_pct"]) == 100 and float(medidas["duracao_s"]) == 0
    assert g2["id_midia"] != grav["id_midia"]
    assert not await pool.fetchval("select 1 from agentesia_biblioteca_midia where id = $1::uuid", grav["id_midia"])
    assert await pool.fetchval("select count(*) from agentesia_roteiro_gravacoes where id_escritorio = $1::uuid", escritorio["id"]) == 1

    # Áudio numa parte de vídeo é recusado; com "trocar por áudio" entra.
    assert (await cliente.post(f"/api/roteiro-gravacao/partes/{video_a['id']}", headers=h,
                               json={"conteudo_base64": _b64(OGG), "mime": "audio/ogg"})).status_code == 400
    troca = await cliente.post(f"/api/roteiro-gravacao/partes/{video_a['id']}", headers=h,
                               json={"conteudo_base64": _b64(OGG), "mime": "audio/ogg", "como_audio": True})
    assert troca.status_code == 200, troca.text

    # Parte geral: gravada no produto A, já aparece como feita (reaproveitada) no produto B.
    no_b = (await cliente.get(f"/api/roteiro-gravacao/{b}", headers=h)).json()
    vb = next(p for p in no_b["partes"] if p["marcador"] == "Video Inicial")
    assert vb["gravacao"] and vb["gravacao"]["reaproveitada"] is True
    assert no_b["gravadas"] == 1

    # Apagar a gravação.
    assert (await cliente.delete(f"/api/roteiro-gravacao/partes/{honorarios['id']}", headers=h)).json()["ok"] is True
    assert (await cliente.get(f"/api/roteiro-gravacao/{a}", headers=h)).json()["gravadas"] == 1

    # Plano sem mídia: não grava.
    plano = await pool.fetchval("insert into agentesia_planos (codigo, nome, midia) values ($1, 'Básico', false) returning id",
                                f"p{uuid.uuid4().hex[:6]}")
    await pool.execute("""insert into agentesia_carteiras (id_escritorio, id_plano) values ($1::uuid, $2)
                          on conflict (id_escritorio) do update set id_plano = excluded.id_plano""", escritorio["id"], plano)
    # A equipe LawChat sempre pode; o gestor do escritório não.
    gestor = f"gestor-{uuid.uuid4().hex[:6]}@teste.com"
    from app.gestao import seguranca
    await pool.execute("insert into agentesia_usuarios (email, nome, senha_hash, papel, id_escritorio) values ($1, 'G', $2, 'gestor', $3::uuid)",
                       gestor, seguranca.gerar_hash("senha-gestor-123"), escritorio["id"])
    await cliente.post("/api/sair")
    await _entrar(cliente, gestor, "senha-gestor-123")
    bloqueado = (await cliente.get("/api/roteiro-gravacao")).json()
    assert bloqueado["liberado"] is False and "Básico" in bloqueado["motivo"]
    assert (await cliente.post(f"/api/roteiro-gravacao/partes/{honorarios['id']}",
                               json={"conteudo_base64": _b64(OGG)})).status_code == 403


@precisa_ffmpeg
async def test_video_do_navegador_vira_mp4():
    from app.gestao.rotas_roteiro_gravacao import preparar_arquivo
    mp4, extensao = await preparar_arquivo(_video_webm(), "video", "video/webm", "gravacao.webm")
    assert extensao == "mp4" and mp4[4:8] == b"ftyp"
    ogg, ext_audio = await preparar_arquivo(_video_webm(), "audio", "video/webm", "x.webm")
    assert ext_audio == "ogg" and ogg[:4] == b"OggS"


@precisa_pg
async def test_marcador_escapado_chave_geral_e_pasta(ambiente):
    cliente, _simulada, email_admin, banco = ambiente
    from app.gestao.rotas_roteiro_gravacao import api
    cliente._transport.app.include_router(api)
    await _entrar(cliente, email_admin, "senha-admin-123")
    pool = banco._pool
    escritorio = (await cliente.post("/api/admin/escritorios", json={
        "nome": "Roteiro Chave", "id_conta_helena": str(uuid.uuid4()), "token_helena": "token-bom-" + uuid.uuid4().hex[:8]})).json()["escritorio"]
    h = {"x-escritorio": escritorio["id"]}
    a = await _produto(pool, "INSS / BPC Teste")
    # Marcador escapado (como o editor de markdown grava) no prompt do agente: "puxar" também acha.
    await pool.execute("update agentesia_biblioteca_agentes set texto_prompt = texto_prompt || $2 where id_produto_biblioteca = $1::uuid",
                       a, "\nSe perguntar do prazo: \\[\\[audio:Prazo do INSS\\]\\].")
    r = (await cliente.get(f"/api/admin/biblioteca/produtos/{a}/roteiro")).json()
    assert ("audio", "Prazo do INSS") in [(m["tipo"], m["nome"]) for m in r["marcadores"]]
    puxado = (await cliente.post(f"/api/admin/biblioteca/produtos/{a}/roteiro/puxar")).json()
    assert puxado["criadas"] == 5 and any(p["marcador"] == "Prazo do INSS" for p in puxado["partes"])

    # Gravação entra na pasta do produto sem subpasta falsa pelo "/" do nome.
    honorarios = next(p for p in puxado["partes"] if p["marcador"] == "Honorários")
    g = await cliente.post(f"/api/roteiro-gravacao/partes/{honorarios['id']}", headers=h,
                           json={"conteudo_base64": _b64(OGG), "mime": "audio/ogg"})
    assert g.status_code == 200, g.text
    id_midia = g.json()["gravacao"]["id_midia"]
    assert await pool.fetchval("select pasta from agentesia_biblioteca_midia where id = $1::uuid", id_midia) == \
        "Roteiros gravados/INSS - BPC Teste"

    def gravada(detalhe):
        return next(p for p in detalhe["partes"] if p["id"] == honorarios["id"])["gravacao"]

    # Virar parte geral, trocar a chave e tirar a chave: a gravação continua aparecendo.
    for chave in ("Honorários gerais", "honorarios_outra", ""):
        assert (await cliente.patch(f"/api/admin/roteiro/partes/{honorarios['id']}", json={"chave_geral": chave})).status_code == 200
        visto = gravada((await cliente.get(f"/api/roteiro-gravacao/{a}", headers=h)).json())
        assert visto and visto["id_midia"] == id_midia, chave
    assert await pool.fetchval("select chave from agentesia_roteiro_gravacoes where id_escritorio = $1::uuid",
                               escritorio["id"]) == f"parte:{honorarios['id']}"


def _mp4(codec_video: str) -> bytes:
    with tempfile.TemporaryDirectory() as pasta:
        destino = os.path.join(pasta, "v.mp4")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15",
                        "-f", "lavfi", "-i", "sine=frequency=440", "-t", "2", "-c:v", codec_video, "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-tag:v", "hvc1" if codec_video == "libx265" else "avc1", destino], check=True)
        with open(destino, "rb") as arquivo:
            return arquivo.read()


def _tem_encoder(nome: str) -> bool:
    if not shutil.which("ffmpeg"):
        return False
    saida = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    return nome in saida


@pytest.mark.skipif(not shutil.which("ffprobe") or not _tem_encoder("libx265"), reason="sem ffprobe ou libx265")
async def test_mp4_hevc_vira_h264_e_h264_passa_direto():
    from app.gestao.rotas_roteiro_gravacao import preparar_arquivo
    from app.midia.conversao import codecs
    hevc = _mp4("libx265")
    assert await codecs(hevc, ".mp4") == ("hevc", "aac")
    convertido, extensao = await preparar_arquivo(hevc, "video", "video/mp4", "iphone.mp4")
    assert extensao == "mp4" and await codecs(convertido, ".mp4") == ("h264", "aac")
    h264 = _mp4("libx264")
    passou, _ = await preparar_arquivo(h264, "video", "video/mp4", "ok.mp4")
    assert passou == h264


def test_marcador_escapado_dentro_do_json():
    """O JSON da linha dobra as barras: os marcadores são procurados nos textos já decodificados."""
    import json

    from app.gestao.rotas_roteiro_gravacao import _textos_do_json
    linha = json.loads(json.dumps({"texto_prompt": "Envie \\[\\[audio:Prazo\\]\\]", "faq": [{"resposta": "[[video:Oi]]"}], "n": 3}))
    pedacos: list[str] = []
    _textos_do_json(linha, pedacos)
    assert marcadores_do_texto("\n".join(pedacos)) == [("audio", "Prazo"), ("video", "Oi")]


@precisa_ffmpeg
async def test_ogg_vorbis_vira_opus_e_opus_passa_direto():
    """Mensagem de voz do WhatsApp só em Ogg/Opus: Ogg/Vorbis anexado é convertido; Ogg/Opus passa como veio."""
    from app.gestao.rotas_roteiro_gravacao import preparar_arquivo
    from app.midia.conversao import codecs

    def gerar(codec: str) -> bytes:
        with tempfile.TemporaryDirectory() as pasta:
            destino = os.path.join(pasta, "a.ogg")
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=300",
                            "-t", "2", "-c:a", codec, destino], check=True)
            with open(destino, "rb") as arquivo:
                return arquivo.read()

    vorbis = gerar("libvorbis")
    saida, extensao = await preparar_arquivo(vorbis, "audio", "audio/ogg", "caro.ogg")
    assert extensao == "ogg" and (await codecs(saida, ".ogg"))[1] == "opus"
    opus = gerar("libopus")
    mesma, _ = await preparar_arquivo(opus, "audio", "audio/ogg", "x.ogg")
    assert mesma == opus


@precisa_pg
async def test_contrato_assinado_vira_midia_pos_assinatura_sem_passar_por_cima(ambiente):
    """A parte geral "contrato_assinado" liga a mídia pós-assinatura da ZapSign quando ela está vazia (ou era a gravação
    antiga), nunca troca a que o escritório escolheu, e sai junto quando a gravação é apagada."""
    cliente, _simulada, email_admin, banco = ambiente
    from app.gestao.rotas_roteiro_gravacao import api
    cliente._transport.app.include_router(api)
    await _entrar(cliente, email_admin, "senha-admin-123")
    pool = banco._pool
    produto = await _produto(pool, "Pós-assinatura")
    parte = (await cliente.post(f"/api/admin/biblioteca/produtos/{produto}/roteiro/partes", json={
        "titulo": "Contrato assinado", "tipo": "audio", "chave_geral": "contrato_assinado"})).json()
    esc = (await cliente.post("/api/admin/escritorios", json={
        "nome": "Pos Adv", "id_conta_helena": str(uuid.uuid4()), "token_helena": "token-bom-" + uuid.uuid4().hex[:8]})).json()["escritorio"]
    h = {"x-escritorio": esc["id"]}
    await pool.execute("insert into agentesia_integracoes (id_escritorio, tipo, config, situacao) values ($1::uuid, 'zapsign', '{}'::jsonb, 'ok')", esc["id"])
    url_da_config = lambda: pool.fetchval("select config->'midia_pos_assinatura'->>'url' from agentesia_integracoes "  # noqa: E731
                                          "where id_escritorio = $1::uuid and tipo = 'zapsign'", esc["id"])

    um = (await cliente.post(f"/api/roteiro-gravacao/partes/{parte['id']}", headers=h, json={"conteudo_base64": _b64(OGG)})).json()
    assert um["pos_assinatura"] is True and await url_da_config() == um["gravacao"]["url"]
    assert (await cliente.get("/api/roteiro-gravacao/geral/contrato_assinado", headers=h)).json()["gravacao"]["url"] == um["gravacao"]["url"]
    dois = (await cliente.post(f"/api/roteiro-gravacao/partes/{parte['id']}", headers=h, json={"conteudo_base64": _b64(OGG)})).json()
    assert await url_da_config() == dois["gravacao"]["url"]                    # regravar troca o link antigo pelo novo
    await cliente.delete(f"/api/roteiro-gravacao/partes/{parte['id']}", headers=h)
    assert await url_da_config() is None                                       # apagou: a ZapSign não manda link morto

    await pool.execute("update agentesia_integracoes set config = '{\"midia_pos_assinatura\": {\"url\": \"https://x.com/meu.mp4\"}}'::jsonb "
                       "where id_escritorio = $1::uuid and tipo = 'zapsign'", esc["id"])
    tres = (await cliente.post(f"/api/roteiro-gravacao/partes/{parte['id']}", headers=h, json={"conteudo_base64": _b64(OGG)})).json()
    assert tres["pos_assinatura"] is False and await url_da_config() == "https://x.com/meu.mp4"


@precisa_pg
async def test_roteiro_conclui_so_com_os_obrigatorios(ambiente):
    """Vídeos e áudios principais concluem o roteiro; a quebra de objeção é opcional (fica em aberto para depois)."""
    cliente, _simulada, email_admin, banco = ambiente
    from app.gestao.rotas_roteiro_gravacao import api
    cliente._transport.app.include_router(api)
    await _entrar(cliente, email_admin, "senha-admin-123")
    produto = await _produto(banco._pool, "Obrigatórios")
    partes = (await cliente.post(f"/api/admin/biblioteca/produtos/{produto}/roteiro/puxar")).json()["partes"]
    esc = (await cliente.post("/api/admin/escritorios", json={
        "nome": "Obrig Adv", "id_conta_helena": str(uuid.uuid4()), "token_helena": "token-bom-" + uuid.uuid4().hex[:8]})).json()["escritorio"]
    h = {"x-escritorio": esc["id"]}
    inicio = (await cliente.get(f"/api/roteiro-gravacao/{produto}", headers=h)).json()
    assert (inicio["obrigatorias"], inicio["objecoes"], inicio["concluido"]) == (3, 1, False)
    for p in partes:
        if p["secao"] != "objecoes":
            await cliente.post(f"/api/roteiro-gravacao/partes/{p['id']}", headers=h,
                               json={"conteudo_base64": _b64(OGG), "como_audio": p["tipo"] == "video"})
    depois = (await cliente.get(f"/api/roteiro-gravacao/{produto}", headers=h)).json()
    assert depois["concluido"] is True and depois["obrigatorias_gravadas"] == 3 and depois["objecoes_gravadas"] == 0
    lista = (await cliente.get("/api/roteiro-gravacao", headers=h)).json()["produtos"]
    assert next(x for x in lista if x["id"] == produto)["concluido"] is True
