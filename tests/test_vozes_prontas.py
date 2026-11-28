"""Vozes prontas do roteiro de gravação (migração 020): a LawChat sobe os áudios de uma voz e o escritório usa sem gravar."""
import base64
import os
import uuid
from pathlib import Path

import pytest

URL_PG = os.environ.get("AGENTESIA_TESTE_PG_URL")
precisa_pg = pytest.mark.skipif(not URL_PG, reason="sem AGENTESIA_TESTE_PG_URL")

if URL_PG:
    from tests.test_gestao import _entrar, ambiente  # noqa: F401  (fixture do painel com Postgres local)

OGG = b"OggS" + b"\x00" * 60


def _b64(dados: bytes) -> str:
    return base64.b64encode(dados).decode()


def _arquivo_local(url: str) -> Path:
    """Onde o modo local guardou o arquivo da URL ({AGENTESIA_URL_PUBLICA}/midia/<caminho>)."""
    return Path(os.environ["AGENTESIA_PASTA_MIDIA"]) / url.split("/midia/", 1)[1]


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


async def _escritorio(cliente, nome: str) -> dict:
    return (await cliente.post("/api/admin/escritorios", json={
        "nome": nome, "id_conta_helena": str(uuid.uuid4()), "token_helena": "token-bom-" + uuid.uuid4().hex[:8]})).json()["escritorio"]


@precisa_pg
async def test_voz_pronta_do_admin_ao_escritorio(ambiente):
    cliente, _simulada, email_admin, banco = ambiente
    from app.gestao.rotas_roteiro_gravacao import api as api_roteiro
    from app.gestao.rotas_vozes_prontas import TEXTO_ACEITE
    from app.gestao.rotas_vozes_prontas import api as api_vozes
    cliente._transport.app.include_router(api_roteiro)
    cliente._transport.app.include_router(api_vozes)
    await _entrar(cliente, email_admin, "senha-admin-123")
    pool = banco._pool
    produto = await _produto(pool, "Auxílio Vozes")
    partes = (await cliente.post(f"/api/admin/biblioteca/produtos/{produto}/roteiro/puxar")).json()["partes"]
    por_marcador = {p["marcador"]: p for p in partes}

    # Admin: cria a voz e sobe os áudios (o de boas-vindas é um áudio OGG na parte de vídeo).
    voz = (await cliente.post("/api/admin/vozes-prontas", json={
        "nome": "Clara — acolhedora", "tom": "acolhedora", "genero": "feminina", "descricao": "Voz calma"})).json()
    assert voz["origem"] == "ia" and voz["ativo"] is True
    enviados = {}
    for marcador in ("Video Inicial", "Como funciona", "objecao_caro"):
        r = await cliente.post(f"/api/admin/vozes-prontas/{voz['id']}/partes/{por_marcador[marcador]['id']}",
                               json={"conteudo_base64": _b64(OGG), "mime": "audio/ogg", "nome": "a.ogg"})
        assert r.status_code == 200, r.text
        enviados[marcador] = r.json()
        assert enviados[marcador]["tipo"] == "audio" and "/vozes-prontas/" in enviados[marcador]["url"]
        assert _arquivo_local(enviados[marcador]["url"]).exists()
    # Subir de novo troca o arquivo e apaga o antigo (ninguém usa ainda).
    antigo = enviados["objecao_caro"]["url"]
    enviados["objecao_caro"] = (await cliente.post(
        f"/api/admin/vozes-prontas/{voz['id']}/partes/{por_marcador['objecao_caro']['id']}",
        json={"conteudo_base64": _b64(OGG), "mime": "audio/ogg"})).json()
    assert enviados["objecao_caro"]["url"] != antigo and not _arquivo_local(antigo).exists()

    admin = (await cliente.get(f"/api/admin/biblioteca/produtos/{produto}/vozes-prontas")).json()
    assert len(admin["partes"]) == 4
    da_voz = next(v for v in admin["vozes"] if v["id"] == voz["id"])
    assert set(da_voz["audios"]) == {por_marcador[m]["id"] for m in enviados}
    assert da_voz["audios"][por_marcador["Video Inicial"]["id"]]["tipo"] == "audio"

    # Escritório: vê a voz com a amostra do "Como funciona".
    a = await _escritorio(cliente, "Vozes A")
    b = await _escritorio(cliente, "Vozes B")
    ha, hb = {"x-escritorio": a["id"]}, {"x-escritorio": b["id"]}
    lista = (await cliente.get(f"/api/roteiro-gravacao/{produto}/vozes", headers=ha)).json()
    assert lista["texto_aceite"] == TEXTO_ACEITE
    clara = next(v for v in lista["vozes"] if v["id"] == voz["id"])
    assert (clara["partes_cobertas"], clara["total_partes"], clara["em_uso"]) == (3, 4, False)
    assert clara["amostra"]["titulo"] == por_marcador["Como funciona"]["titulo"]
    assert clara["amostra"]["url"] == enviados["Como funciona"]["url"]

    # Sem o aceite, não usa.
    sem = await cliente.post(f"/api/roteiro-gravacao/{produto}/vozes/{voz['id']}/usar", headers=ha, json={"aceite": False})
    assert sem.status_code == 400 and "aceite" in sem.json()["detail"]

    usou = await cliente.post(f"/api/roteiro-gravacao/{produto}/vozes/{voz['id']}/usar", headers=ha, json={"aceite": True})
    assert usou.status_code == 200, usou.text
    assert usou.json() == {"usadas": 3, "mantidas": 0, "puladas": 0, "total": 3}
    assert await pool.fetchval("select texto from agentesia_voz_pronta_aceites where id_escritorio = $1::uuid", a["id"]) == TEXTO_ACEITE
    detalhe = (await cliente.get(f"/api/roteiro-gravacao/{produto}", headers=ha)).json()
    gravadas = {p["marcador"]: p["gravacao"] for p in detalhe["partes"]}
    assert gravadas["Honorários"] is None                      # esta voz ainda não tem áudio de honorários
    for marcador in enviados:
        g = gravadas[marcador]
        assert (g["origem"], g["id_voz"], g["voz_nome"]) == ("pronta", voz["id"], "Clara — acolhedora")
        assert g["url"] == enviados[marcador]["url"]
        midia = await pool.fetchrow("select pasta, tags, caminho_storage, nome from agentesia_biblioteca_midia where id = $1::uuid",
                                    g["id_midia"])
        assert midia["pasta"] == "Roteiros prontos/Clara — acolhedora" and midia["caminho_storage"] is None
        assert "voz_pronta" in str(midia["tags"]) and midia["nome"].split(" - ", 1)[0].isdigit()
    assert detalhe["obrigatorias_gravadas"] == 2                # vídeo inicial (por áudio) + como funciona; falta honorários

    # A voz pronta não gasta a cota do escritório.
    assert (await cliente.get("/api/midia", headers=ha)).json()["usado_bytes"] == 0
    assert (await cliente.get(f"/api/roteiro-gravacao/{produto}/vozes", headers=ha)).json()["vozes"][0]["em_uso"] is True

    # Grava a própria voz por cima do "Como funciona": vira gravação própria; o arquivo compartilhado continua lá.
    como = por_marcador["Como funciona"]
    propria = await cliente.post(f"/api/roteiro-gravacao/partes/{como['id']}", headers=ha,
                                 json={"conteudo_base64": _b64(OGG), "mime": "audio/ogg"})
    assert propria.status_code == 200, propria.text
    gp = propria.json()["gravacao"]
    assert (gp["origem"], gp["id_voz"], gp["voz_nome"]) == ("propria", None, None)
    assert _arquivo_local(enviados["Como funciona"]["url"]).exists()
    assert not await pool.fetchval("select 1 from agentesia_biblioteca_midia where id = $1::uuid", gravadas["Como funciona"]["id_midia"])

    # Usar a voz de novo sem substituir_minhas mantém a própria.
    de_novo = (await cliente.post(f"/api/roteiro-gravacao/{produto}/vozes/{voz['id']}/usar", headers=ha,
                                  json={"aceite": True})).json()
    assert de_novo == {"usadas": 2, "mantidas": 1, "puladas": 0, "total": 3}
    depois = {p["marcador"]: p["gravacao"] for p in (await cliente.get(f"/api/roteiro-gravacao/{produto}", headers=ha)).json()["partes"]}
    assert depois["Como funciona"]["origem"] == "propria" and depois["Como funciona"]["id_midia"] == gp["id_midia"]
    assert depois["objecao_caro"]["id_midia"] == gravadas["objecao_caro"]["id_midia"]   # a mesma voz não duplica
    assert await pool.fetchval("select count(*) from agentesia_biblioteca_midia where id_escritorio = $1::uuid "
                               "and tags ? 'voz_pronta'", a["id"]) == 2

    # Admin: o texto que a voz fala e o aviso dos honorários; a voz ganha o áudio de honorários (valor padrão).
    hon = por_marcador["Honorários"]
    mudou = await cliente.patch(f"/api/admin/roteiro-partes/{hon['id']}/texto-pronto",
                                json={"texto_pronto": "  Hoje você não paga nada.  ", "aviso_pronto": "Fala: 30% dos atrasados"})
    assert mudou.status_code == 200 and mudou.json()["texto_pronto"] == "Hoje você não paga nada."
    assert (await cliente.post(f"/api/admin/vozes-prontas/{voz['id']}/partes/{hon['id']}",
                               json={"conteudo_base64": _b64(OGG), "mime": "audio/ogg"})).status_code == 200
    admin = (await cliente.get(f"/api/admin/biblioteca/produtos/{produto}/vozes-prontas")).json()
    assert next(p for p in admin["partes"] if p["id"] == hon["id"])["aviso_pronto"] == "Fala: 30% dos atrasados"
    clara_b = next(v for v in (await cliente.get(f"/api/roteiro-gravacao/{produto}/vozes", headers=hb)).json()["vozes"]
                   if v["id"] == voz["id"])
    assert clara_b["avisos"] == [{"id_parte": hon["id"], "titulo": hon["titulo"], "aviso": "Fala: 30% dos atrasados"}]

    # Outra conta usa a mesma voz, sem o áudio de honorários (fica em texto); apagar a gravação pronta numa conta não
    # apaga o arquivo da outra.
    assert (await cliente.post(f"/api/roteiro-gravacao/{produto}/vozes/{voz['id']}/usar", headers=hb,
                               json={"aceite": True, "pular_partes": [hon["id"]]})).json() == {
        "usadas": 3, "mantidas": 0, "puladas": 1, "total": 4}
    assert {p["marcador"]: p["gravacao"] for p in (await cliente.get(f"/api/roteiro-gravacao/{produto}", headers=hb)).json()[
        "partes"]}["Honorários"] is None
    # Primeiros passos: usar a voz pronta cumpre o passo do roteiro, mesmo com os honorários em texto.
    passos = (await cliente.get("/api/inicio/primeiros-passos", headers=hb)).json()["passos"]
    assert next(x for x in passos if x["codigo"] == "roteiro")["situacao"] == "feito"
    caro = por_marcador["objecao_caro"]
    apagou = (await cliente.delete(f"/api/roteiro-gravacao/partes/{caro['id']}", headers=ha)).json()
    assert apagou["ok"] is True and apagou["arquivo_ficou"] is False
    url_caro = enviados["objecao_caro"]["url"]
    assert _arquivo_local(url_caro).exists()
    em_b = {p["marcador"]: p["gravacao"] for p in (await cliente.get(f"/api/roteiro-gravacao/{produto}", headers=hb)).json()["partes"]}
    assert em_b["objecao_caro"]["url"] == url_caro

    # Admin: a lista conta os escritórios; voz em uso não se apaga (desativa).
    vozes = (await cliente.get("/api/admin/vozes-prontas")).json()
    assert next(v for v in vozes if v["id"] == voz["id"])["escritorios"] == 2
    bloqueado = await cliente.delete(f"/api/admin/vozes-prontas/{voz['id']}")
    assert bloqueado.status_code == 409 and "Desative em vez de apagar" in bloqueado.json()["detail"]
    assert (await cliente.patch(f"/api/admin/vozes-prontas/{voz['id']}", json={"ativo": False, "tom": ""})).json()["tom"] is None
    assert all(v["id"] != voz["id"] for v in (await cliente.get(f"/api/roteiro-gravacao/{produto}/vozes", headers=ha)).json()["vozes"])
    assert (await cliente.post(f"/api/roteiro-gravacao/{produto}/vozes/{voz['id']}/usar", headers=ha,
                               json={"aceite": True})).status_code == 404


@precisa_pg
async def test_voz_sem_uso_apaga_com_os_arquivos(ambiente):
    cliente, _simulada, email_admin, banco = ambiente
    from app.gestao.rotas_vozes_prontas import api as api_vozes
    from app.gestao.rotas_roteiro_gravacao import api as api_roteiro
    cliente._transport.app.include_router(api_roteiro)
    cliente._transport.app.include_router(api_vozes)
    await _entrar(cliente, email_admin, "senha-admin-123")
    produto = await _produto(banco._pool, "Apagar Voz")
    parte = (await cliente.post(f"/api/admin/biblioteca/produtos/{produto}/roteiro/puxar")).json()["partes"][0]
    voz = (await cliente.post("/api/admin/vozes-prontas", json={"nome": "Rafael", "genero": "masculina", "origem": "equipe"})).json()
    up = (await cliente.post(f"/api/admin/vozes-prontas/{voz['id']}/partes/{parte['id']}",
                             json={"conteudo_base64": _b64(OGG), "mime": "audio/ogg"})).json()
    assert _arquivo_local(up["url"]).exists()
    assert (await cliente.delete(f"/api/admin/vozes-prontas/{voz['id']}/partes/{parte['id']}")).json() == {"ok": True}
    assert not _arquivo_local(up["url"]).exists()
    up2 = (await cliente.post(f"/api/admin/vozes-prontas/{voz['id']}/partes/{parte['id']}",
                              json={"conteudo_base64": _b64(OGG), "mime": "audio/ogg"})).json()
    assert (await cliente.delete(f"/api/admin/vozes-prontas/{voz['id']}")).json() == {"ok": True}
    assert not _arquivo_local(up2["url"]).exists()
    assert not await banco._pool.fetchval("select 1 from agentesia_voz_pronta_audios where id_voz = $1::uuid", voz["id"])
    assert (await cliente.post("/api/admin/vozes-prontas", json={"nome": "X", "genero": "outra"})).status_code == 422
