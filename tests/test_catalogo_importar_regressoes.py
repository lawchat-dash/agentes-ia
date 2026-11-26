"""Regressões da revisão independente do importador do catálogo (cada teste cobre um achado confirmado)."""

import copy
import csv
import io
import json
import os
from pathlib import Path

import pytest

from app import catalogo_importar as imp

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
BRUTO = (Path(__file__).parent / "dados" / "catalogo_exportado.json").read_bytes()
DADOS = json.loads(BRUTO)
ID_AUX = "11111111-1111-4111-8111-111111111111"
ID_MIDIA = "22222222-2222-4222-8222-222222222222"


def test_leitura_robusta_de_arquivos_ruins():
    # Excel pt-BR: Windows-1252 e ";" -> lê com aviso, sem virar produto "produto".
    texto = "id;slug;nome;categoria;publicado\n55555555-5555-4555-8555-555555555555;aux;Auxílio Acidente;Previdenciário;true\n"
    lido = imp.ler_arquivos([("sistemaia_biblioteca_produtos.csv", texto.encode("cp1252"))])
    assert lido["sistemaia_biblioteca_produtos"][0]["nome"] == "Auxílio Acidente"
    assert any("Windows-1252" in a for a in lido["_avisos"])
    # Linha sem slug e sem nome (arquivo estragado) para com mensagem clara.
    with pytest.raises(imp.ErroImportacao, match="sem slug e sem nome"):
        imp.ler_arquivos([("sistemaia_biblioteca_produtos.json", b'[{"id": "x", "categoria": "Civil"}]')])
    # CSV de uma célula com o JSON cortado: mensagem, não erro 500.
    saida = io.StringIO()
    csv.writer(saida).writerows([["catalogo"], ['{"sistemaia_biblioteca_produtos": [']])
    with pytest.raises(imp.ErroImportacao, match="cortado"):
        imp.ler_arquivos([("resultado.csv", saida.getvalue().encode())])
    # Números vindos de planilha.
    assert imp._int("1.0") == 1 and imp._int(" ") == 0 and imp._int("1º") == 0 and imp._int(2.0) == 2
    assert imp.normalizar_agente({"papel": "sdr", "ordem": "3.0"})["ordem"] == 3


def test_slug_nao_e_cortado_e_colisao_para():
    longo = "auxilio-acidente-para-trabalhadores-rurais-e-urbanos-com-sequela-permanente"
    produtos = [{"id": "a", "slug": longo, "nome": "A"}, {"id": "b", "slug": longo + "-midia", "nome": "B"}]
    casamento, _ = imp.casar_produtos(produtos, {})
    assert casamento["a"][0] == longo and casamento["b"][0] == longo + "-midia"
    with pytest.raises(imp.ErroImportacao, match="mesmo endereço"):
        imp.casar_produtos([{"id": "a", "slug": "auxilio_acidente"}, {"id": "b", "slug": "auxilio-acidente"}], {})


def test_formato_e_contagem_da_previa():
    assert imp.formato_do_documento({"tipo": "arquivo", "arquivo_nome": "regras.pdf", "arquivo_mime": "application/pdf"}) == "pdf"
    assert imp.formato_do_documento({"tipo": "arquivo", "arquivo_nome": "x",
                                     "arquivo_mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}) == "docx"
    assert imp.formato_do_documento({"tipo": "arquivo", "arquivo_nome": "notas.md", "arquivo_mime": ""}) == "texto"
    assert imp.formato_do_documento({"tipo": "url"}) == "texto"
    plano = imp.planejar(imp.ler_arquivos([("c.json", BRUTO)]))
    aux = next(p for p in plano.produtos if p["slug"] == "auxilio-acidente")
    assert (aux["documentos"], aux["frases"]) == (2, 1)       # o 103 não tem texto, o 104 está desligado, a frase curta não entra


async def test_texto_do_arquivo_nao_acessa_rede_interna():
    for url in ("http://exemplo.com/a.pdf", "https://127.0.0.1/a.pdf", "https://localhost/a.pdf", "file:///etc/passwd"):
        assert await imp._texto_do_arquivo(url, "a.pdf", "application/pdf") is None


def _arquivo(dados: dict) -> dict:
    return imp.ler_arquivos([("c.json", json.dumps(dados).encode())])


@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_reimportacao_casada_por_id_sincroniza_e_nao_regrava_o_que_nao_mudou():
    from app.banco.postgres import RepositorioPostgres

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        await pool.execute("""delete from agentesia_biblioteca_produtos where id in ('11111111-1111-4111-8111-111111111111',
                              '22222222-2222-4222-8222-222222222222', '33333333-3333-4333-8333-333333333333')""")
        await imp.importar(pool, _arquivo(DADOS), baixar_arquivos=False)
        produto_antes = await pool.fetchval("select atualizado_em from agentesia_biblioteca_produtos where id = $1", ID_AUX)
        sdr = "select atualizado_em from agentesia_biblioteca_agentes where id_produto_biblioteca = $1 and papel = 'sdr'"
        agente_antes = await pool.fetchval(sdr, ID_AUX)

        # Mesmo arquivo de novo: nada muda (não descarta rascunhos de ativação dos escritórios).
        await imp.importar(pool, _arquivo(DADOS), baixar_arquivos=False)
        assert await pool.fetchval("select atualizado_em from agentesia_biblioteca_produtos where id = $1", ID_AUX) == produto_antes
        assert await pool.fetchval(sdr, ID_AUX) == agente_antes

        # Slug trocado aqui: casa pelo id, não quebra; o slug volta para o de lá.
        await pool.execute("update agentesia_biblioteca_produtos set slug = 'aux-renomeado' where id = $1", ID_AUX)
        await imp.importar(pool, _arquivo(DADOS), baixar_arquivos=False)
        assert await pool.fetchval("select slug from agentesia_biblioteca_produtos where id = $1", ID_AUX) == "auxilio-acidente"
        # Slug trocado lá: o mesmo produto muda de endereço (sem duplicar).
        mudado = copy.deepcopy(DADOS)
        mudado["sistemaia_biblioteca_produtos"][0]["slug"] = "auxilio-acidente-v2"
        plano = await imp.importar(pool, _arquivo(mudado), baixar_arquivos=False)
        assert any("muda de 'auxilio-acidente' para 'auxilio-acidente-v2'" in a for a in plano.avisos)
        assert await pool.fetchval(
            "select count(*) from agentesia_biblioteca_produtos where id = $1 and slug = 'auxilio-acidente-v2'", ID_AUX) == 1

        # Documento e frase que saíram de lá saem daqui; formato normalizado.
        mudado["sistemaia_biblioteca_conhecimento"] = [d for d in mudado["sistemaia_biblioteca_conhecimento"] if d["id"] != 101]
        mudado["sistemaia_frases_troca"] = [f for f in mudado["sistemaia_frases_troca"] if f["id"] != "f1"]
        await imp.importar(pool, _arquivo(mudado), baixar_arquivos=False)
        docs = await pool.fetch("select nome, ativo, formato from agentesia_documentos where id_produto_biblioteca = $1", ID_AUX)
        assert {(d["nome"], d["ativo"], d["formato"]) for d in docs} == {("Regras do INSS", True, "pdf"), ("Tabela de honorários", False, "texto")}
        assert await pool.fetchval("select count(*) from agentesia_frases_troca where id_produto_biblioteca = $1", ID_AUX) == 0

        # Re-importar só a tabela de produtos mantém os follow-ups por etapa.
        await imp.importar(pool, _arquivo({"sistemaia_biblioteca_produtos": mudado["sistemaia_biblioteca_produtos"]}), baixar_arquivos=False)
        seguimento = json.loads(await pool.fetchval("select padrao_followup from agentesia_biblioteca_produtos where id = $1", ID_AUX))
        assert set(seguimento["agentes"]) == {"sdr", "assinatura"}

        # Só a variante "· Mídia": acha o produto-base que já está aqui.
        await pool.execute("update agentesia_biblioteca_produtos set id_produto_base = null where id = $1", ID_MIDIA)
        await imp.importar(pool, _arquivo({"sistemaia_biblioteca_produtos": [mudado["sistemaia_biblioteca_produtos"][1]]}), baixar_arquivos=False)
        assert str(await pool.fetchval("select id_produto_base from agentesia_biblioteca_produtos where id = $1", ID_MIDIA)) == ID_AUX

        # Documento enorme é cortado no limite, com aviso.
        grande = copy.deepcopy(mudado)
        grande["sistemaia_biblioteca_conhecimento"][0]["conteudo"] = "x" * (imp.LIMITE_DOCUMENTO + 10)
        plano = await imp.importar(pool, _arquivo(grande), baixar_arquivos=False)
        assert any("entram os primeiros" in a for a in plano.avisos)
        assert await pool.fetchval(
            "select max(caracteres) from agentesia_documentos where id_produto_biblioteca = $1 and ativo", ID_AUX) == imp.LIMITE_DOCUMENTO
    finally:
        await repo.fechar()


# ---------------------------------------------------------------------------- revisão 2
def test_renomeado_la_e_novo_com_o_slug_antigo_nao_se_misturam():
    aqui = [{"id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "slug": "aux", "id_origem": "A"}]
    casamento, avisos = imp.casar_produtos([{"id": "A", "slug": "aux-v2", "nome": "A"}, {"id": "B", "slug": "aux", "nome": "B"}], aqui)
    assert casamento["A"] == ("aux-v2", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    assert casamento["B"] == ("aux", None)
    assert any("muda de 'aux' para 'aux-v2'" in a for a in avisos)
    # Slug de um produto daqui que veio de OUTRO produto de lá: não toma o lugar dele.
    with pytest.raises(imp.ErroImportacao, match="já é de outro produto"):
        imp.casar_produtos([{"id": "C", "slug": "aux", "nome": "C"}], aqui)


def test_produto_sem_id_ou_repetido_para():
    with pytest.raises(imp.ErroImportacao, match="sem id"):
        imp.ler_arquivos([("sistemaia_biblioteca_produtos.json", b'[{"slug": "x", "nome": "X"}]')])
    with pytest.raises(imp.ErroImportacao, match="repetido"):
        imp.ler_arquivos([("sistemaia_biblioteca_produtos.json", b'[{"id": "1", "slug": "x"}, {"id": "1", "slug": "y"}]')])
    # Slug/nome que não são texto (planilha) viram texto.
    n = imp.normalizar_produto({"id": "1", "slug": 123, "nome": 456, "descricao_curta": 7})
    assert (n["slug"], n["nome"], n["descricao_curta"]) == ("123", "456", "7")


def test_csv_do_excel_com_ponto_e_virgula_e_aspas():
    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=";", quotechar='"', doublequote=True, quoting=csv.QUOTE_MINIMAL)
    escritor.writerow(["id", "slug", "nome", "descricao_curta", "publicado", "etiquetas"])
    escritor.writerow(["1", "aux", 'Auxílio "Acidente"', "Texto; com, separadores", "VERDADEIRO", '["a", "b"]'])
    lido = imp.ler_arquivos([("sistemaia_biblioteca_produtos.csv", saida.getvalue().encode("utf-8"))])
    linha = lido["sistemaia_biblioteca_produtos"][0]
    assert linha["nome"] == 'Auxílio "Acidente"' and linha["descricao_curta"] == "Texto; com, separadores"
    assert linha["publicado"] is True and linha["etiquetas"] == ["a", "b"]
    assert imp._verdadeiro("FALSO", True) is False
    # Linha com campo a mais (planilha estragou as aspas): recusa em vez de perder dado em silêncio.
    ruim = "id;slug;nome\n1;aux;Aux;sobrou\n"
    with pytest.raises(imp.ErroImportacao, match="campos para 3 colunas"):
        imp.ler_arquivos([("sistemaia_biblioteca_produtos.csv", ruim.encode())])


def test_download_so_do_storage_do_supabase():
    assert imp._url_permitida("https://abcxyz.supabase.co/storage/v1/object/public/docs/a.pdf")
    for url in ("https://abcxyz.supabase.co/rest/v1/x", "http://abcxyz.supabase.co/storage/v1/object/a.pdf",
                "https://evil.com/storage/v1/object/a.pdf", "https://abc.supabase.co.evil.com/storage/v1/object/a",
                "https://abc.supabase.co:8443/storage/v1/object/a", "https://10.0.0.1/storage/v1/object/a",
                "https://user@abc.supabase.co@127.0.0.1/storage/v1/object/a", "https://[::1]/storage/v1/object/a",
                "https://a.b.supabase.co/storage/v1/object/a"):
        assert not imp._url_permitida(url), url


@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_reimportacao_preserva_o_que_e_daqui(monkeypatch):
    import uuid as _uuid

    from app.banco.postgres import RepositorioPostgres

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    ids = ["11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333",
           "44444444-4444-4444-8444-444444444444"]
    try:
        await pool.execute("delete from agentesia_biblioteca_produtos where id = any($1::uuid[]) or id_origem = any($2::text[])", ids, ids)
        await pool.execute("delete from agentesia_frases_troca where id_produto_biblioteca is null")
        await imp.importar(pool, _arquivo(DADOS), baixar_arquivos=False)

        # Documento padrão criado aqui no admin (sem id_externo) nunca é desligado pela importação.
        id_manual = await pool.fetchval(
            """insert into agentesia_documentos (id_produto_biblioteca, tipo, nome, formato, tamanho_bytes, texto, caracteres,
                                                 situacao, origem, travado)
               values ($1, 'texto', 'Feito aqui', 'texto', 5, 'aqui!', 5, 'pronto', 'produto', true) returning id""", ID_AUX)
        await imp.importar(pool, _arquivo(DADOS), baixar_arquivos=False)
        assert await pool.fetchval("select ativo from agentesia_documentos where id = $1", id_manual) is True

        # Arquivo que não baixou nesta rodada: fica a versão já importada.
        sem_texto = copy.deepcopy(DADOS)
        doc = next(d for d in sem_texto["sistemaia_biblioteca_conhecimento"] if d["id"] == 102)
        doc["conteudo"] = None
        doc["arquivo_url"] = "https://abcxyz.supabase.co/storage/v1/object/public/docs/regras.pdf"

        async def falha(*_a, **_k):
            return None
        monkeypatch.setattr(imp, "_texto_do_arquivo", falha)
        plano = await imp.importar(pool, _arquivo(sem_texto))
        assert any("mantida a versão já importada" in a for a in plano.avisos)
        assert await pool.fetchval("select ativo from agentesia_documentos where id_externo = '102'") is True

        # Frase fora do padrão lá não apaga a que já estava aqui; arquivo sem frases gerais não apaga as gerais daqui.
        curta = copy.deepcopy(DADOS)
        for f in curta["sistemaia_frases_troca"]:
            if f["id"] == "f1":
                f["frase"] = "x"
        curta["sistemaia_frases_troca"] = [f for f in curta["sistemaia_frases_troca"] if f["id"] != "f0"]
        await imp.importar(pool, _arquivo(curta), baixar_arquivos=False)
        assert await pool.fetchval("select frase from agentesia_frases_troca where id_produto_biblioteca = $1 and etapa_destino = 'closer'",
                                   ID_AUX) == "Agora você vai falar com a nossa especialista"
        assert await pool.fetchval("select count(*) from agentesia_frases_troca where id_produto_biblioteca is null") == 1

        # Frase nova lá chega no prompt dos agentes já ativados DAQUELE produto, e só deles.
        escritorio = await pool.fetchval("insert into agentesia_escritorios (nome) values ('Frases') returning id")
        agentes = {}
        for produto in (ID_AUX, ID_MIDIA):
            canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado) values ($1, $2) returning id",
                                        escritorio, "55" + str(_uuid.uuid4().int)[:11])
            agentes[produto] = await pool.fetchval(
                """insert into agentesia_agentes (id_escritorio, id_canal, nome, produto, config)
                   values ($1, $2, 'A', 'catalogo', $3::jsonb) returning id""",
                escritorio, canal, json.dumps({"catalogo": {"id_produto_biblioteca": produto}}))
            await pool.execute("insert into agentesia_agente_etapas (id_agente, codigo, ordem, instrucao) values ($1, 'sdr', 0, $2)",
                               agentes[produto], "Diga: Agora você vai falar com a nossa especialista")
        nova = copy.deepcopy(DADOS)
        next(f for f in nova["sistemaia_frases_troca"] if f["id"] == "f1")["frase"] = "Já te passo para a nossa especialista"
        await imp.importar(pool, _arquivo(nova), baixar_arquivos=False)
        instrucao = "select instrucao from agentesia_agente_etapas where id_agente = $1"
        assert await pool.fetchval(instrucao, agentes[ID_AUX]) == "Diga: Já te passo para a nossa especialista"
        assert await pool.fetchval(instrucao, agentes[ID_MIDIA]) == "Diga: Agora você vai falar com a nossa especialista"
        await pool.execute("delete from agentesia_escritorios where id = $1", escritorio)

        # Sem a coluna padrao_followup no arquivo, a cadência daqui fica.
        sem_coluna = copy.deepcopy(DADOS)
        for p in sem_coluna["sistemaia_biblioteca_produtos"]:
            p.pop("padrao_followup", None)
        await imp.importar(pool, _arquivo(sem_coluna), baixar_arquivos=False)
        seguimento = json.loads(await pool.fetchval("select padrao_followup from agentesia_biblioteca_produtos where id = $1", ID_AUX))
        assert seguimento["cadence"] == [1, 5, 24] and set(seguimento["agentes"]) == {"sdr", "assinatura"}

        # Base nula lá = variante sem vínculo aqui.
        solta = copy.deepcopy(DADOS)
        solta["sistemaia_biblioteca_produtos"][1]["id_produto_base"] = None
        await imp.importar(pool, _arquivo(solta), baixar_arquivos=False)
        assert await pool.fetchval("select id_produto_base from agentesia_biblioteca_produtos where id = $1", ID_MIDIA) is None

        # Renomeado lá + produto novo lá com o slug antigo: dois produtos, nada misturado.
        troca = copy.deepcopy(DADOS)
        troca["sistemaia_biblioteca_produtos"][2]["slug"] = "produto-antigo-v2"
        troca["sistemaia_biblioteca_produtos"].append({"id": "44444444-4444-4444-8444-444444444444", "slug": "produto-antigo",
                                                       "nome": "Novo no lugar", "publicado": True})
        await imp.importar(pool, _arquivo(troca), baixar_arquivos=False)
        linhas = {r["slug"]: str(r["id"]) for r in await pool.fetch(
            "select id, slug from agentesia_biblioteca_produtos where slug like 'produto-antigo%'")}
        assert linhas == {"produto-antigo-v2": "33333333-3333-4333-8333-333333333333",
                          "produto-antigo": "44444444-4444-4444-8444-444444444444"}
        await pool.execute("delete from agentesia_biblioteca_produtos where id = '44444444-4444-4444-8444-444444444444'")
    finally:
        await repo.fechar()


# ---------------------------------------------------------------------------- rodada final
def test_porta_invalida_no_link_vira_recusa_e_nao_erro():
    for url in ("https://abc.supabase.co:99999/storage/v1/object/public/a.pdf", "https://abc.supabase.co:x/storage/v1/object/a.pdf"):
        assert imp._url_permitida(url) is False


def test_csv_com_tab_e_ultima_coluna_vazia_na_ultima_linha():
    texto = b"id\tslug\tnome\tdescricao_curta\np1\ta\tA\t\np2\tb\tB\t\n"
    linhas = imp.ler_arquivos([("sistemaia_biblioteca_produtos.csv", texto)])["sistemaia_biblioteca_produtos"]
    assert [(l["slug"], l["descricao_curta"]) for l in linhas] == [("a", None), ("b", None)]


def test_documento_sem_id_ou_repetido_para():
    base = {"sistemaia_biblioteca_produtos": [{"id": "p1", "slug": "a", "nome": "A"}, {"id": "p2", "slug": "b", "nome": "B"}]}
    sem_id = {**base, "sistemaia_biblioteca_conhecimento": [{"id_produto_biblioteca": "p1", "nome": "x", "conteudo": "texto"}]}
    with pytest.raises(imp.ErroImportacao, match="sem id"):
        imp.ler_arquivos([("c.json", json.dumps(sem_id).encode())])
    repetido = {**base, "sistemaia_biblioteca_conhecimento": [
        {"id": 7, "id_produto_biblioteca": "p1", "nome": "x", "conteudo": "um"},
        {"id": "7", "id_produto_biblioteca": "p2", "nome": "y", "conteudo": "dois"}]}
    with pytest.raises(imp.ErroImportacao, match="repetido"):
        imp.ler_arquivos([("c.json", json.dumps(repetido).encode())])


# ---------------------------------------------------------------------------- rodada final 2
def test_csv_cortado_no_meio_de_um_texto_para():
    cortado = 'id,slug,nome,descricao_longa\r\n1,a,A,"ok"\r\n2,b,Produto B,"texto longo que foi cort'
    with pytest.raises(imp.ErroImportacao, match="cortado"):
        imp.ler_arquivos([("sistemaia_biblioteca_produtos.csv", cortado.encode())])


@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_base_desconhecida_e_documento_que_mudou_de_produto(monkeypatch):
    from app.banco.postgres import RepositorioPostgres

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    ids = ["11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333"]
    try:
        await pool.execute("delete from agentesia_biblioteca_produtos where id = any($1::uuid[]) or id_origem = any($2::text[])", ids, ids)
        await imp.importar(pool, _arquivo(DADOS), baixar_arquivos=False)
        assert str(await pool.fetchval("select id_produto_base from agentesia_biblioteca_produtos where id = $1", ID_MIDIA)) == ID_AUX

        # Base que não está no arquivo nem aqui: a variante fica sem vínculo, como a prévia avisa.
        outra = copy.deepcopy(DADOS)
        outra["sistemaia_biblioteca_produtos"][1]["id_produto_base"] = "99999999-9999-4999-8999-999999999999"
        plano = await imp.importar(pool, _arquivo(outra), baixar_arquivos=False)
        assert any("fica sem vínculo" in a for a in plano.avisos)
        assert await pool.fetchval("select id_produto_base from agentesia_biblioteca_produtos where id = $1", ID_MIDIA) is None

        # Documento que mudou de produto lá e não baixou agora: continua ativo, já no produto novo.
        movido = copy.deepcopy(DADOS)
        doc = next(d for d in movido["sistemaia_biblioteca_conhecimento"] if d["id"] == 102)
        doc["id_produto_biblioteca"] = ID_MIDIA
        doc["conteudo"] = None
        doc["arquivo_url"] = "https://abcxyz.supabase.co/storage/v1/object/public/docs/regras.pdf"

        async def falha(*_a, **_k):
            return None
        monkeypatch.setattr(imp, "_texto_do_arquivo", falha)
        plano = await imp.importar(pool, _arquivo(movido))
        linha = await pool.fetchrow("select id_produto_biblioteca, ativo, texto from agentesia_documentos where id_externo = '102'")
        assert (str(linha["id_produto_biblioteca"]), linha["ativo"]) == (ID_MIDIA, True)
        assert linha["texto"] == "Perícia médica: leve laudos."
        assert any("mantida a versão já importada" in a for a in plano.avisos)
    finally:
        await repo.fechar()


@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_papel_que_saiu_muda_o_carimbo_do_produto():
    from app.banco.postgres import RepositorioPostgres

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    ids = ["11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333"]
    try:
        await pool.execute("delete from agentesia_biblioteca_produtos where id = any($1::uuid[]) or id_origem = any($2::text[])", ids, ids)
        await imp.importar(pool, _arquivo(DADOS), baixar_arquivos=False)
        carimbo = "select atualizado_em from agentesia_biblioteca_produtos where id = $1"
        antes = await pool.fetchval(carimbo, ID_AUX)
        await imp.importar(pool, _arquivo(DADOS), baixar_arquivos=False)
        assert await pool.fetchval(carimbo, ID_AUX) == antes          # nada mudou: nada regravado
        sem_desq = copy.deepcopy(DADOS)
        sem_desq["sistemaia_biblioteca_agentes"] = [a for a in sem_desq["sistemaia_biblioteca_agentes"] if a["papel"] != "desqualificado"]
        await imp.importar(pool, _arquivo(sem_desq), baixar_arquivos=False)
        assert await pool.fetchval(carimbo, ID_AUX) > antes           # papel saiu: carimbo sobe (rascunho antigo é descartado)
        assert await pool.fetchval("select count(*) from agentesia_biblioteca_agentes where id_produto_biblioteca = $1 and papel = 'desqualificado'",
                                   ID_AUX) == 0
    finally:
        await repo.fechar()


def test_texto_json_md_e_corte_no_meio_do_acento_sao_texto():
    from app.midia.extrair import detectar_formato, extrair_texto
    longo = ("a" * 4095 + "ção e previdência").encode()
    assert detectar_formato(longo, "application/octet-stream", "arquivo") == "texto"
    assert detectar_formato('{"t": "atenção"}'.encode("cp1252"), "application/json", "base.json") == "texto"
    assert detectar_formato("# Título\nação".encode("cp1252"), None, "notas.markdown") == "texto"
    assert "atenção" in extrair_texto('{"t": "atenção"}'.encode("cp1252"), "texto")
    assert detectar_formato(b"\x00\x01\x02\xff\xfe" * 10, None, "x.bin") == "desconhecido"
