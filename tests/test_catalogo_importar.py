"""Importação do catálogo do agents-lawchat-main (exportado de docs/EXPORTAR_CATALOGO.sql)."""

import csv
import io
import json
import os
from pathlib import Path

import pytest

from app import catalogo_importar as imp

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
ARQUIVO = Path(__file__).parent / "dados" / "catalogo_exportado.json"
BRUTO = ARQUIVO.read_bytes()
DADOS = json.loads(BRUTO)


def test_le_o_json_em_todos_os_formatos_do_supabase():
    direto = imp.ler_arquivos([("catalogo.json", BRUTO)])
    assert len(direto["sistemaia_biblioteca_produtos"]) == 3 and len(direto["sistemaia_biblioteca_agentes"]) == 9
    embrulhado = imp.ler_arquivos([("x.json", json.dumps({"catalogo": DADOS}).encode())])
    linha_do_editor = imp.ler_arquivos([("resultado.json", json.dumps([{"catalogo": json.dumps(DADOS)}]).encode())])
    assert embrulhado == direto == linha_do_editor
    # CSV de uma célula (download do resultado no SQL Editor).
    saida = io.StringIO()
    csv.writer(saida).writerows([["catalogo"], [json.dumps(DADOS, ensure_ascii=False)]])
    assert imp.ler_arquivos([("Supabase Snippet.csv", saida.getvalue().encode())]) == direto
    # Uma tabela por arquivo (JSON) e CSV do Table Editor com jsonb em texto.
    tabelas = imp.ler_arquivos([("sistemaia_biblioteca_produtos.json", json.dumps(DADOS["sistemaia_biblioteca_produtos"]).encode()),
                                ("sistemaia_biblioteca_agentes_rows.json", json.dumps(DADOS["sistemaia_biblioteca_agentes"]).encode())])
    assert len(tabelas["sistemaia_biblioteca_agentes"]) == 9
    saida = io.StringIO()
    escritor = csv.DictWriter(saida, fieldnames=["id", "slug", "nome", "categoria", "etiquetas", "publicado", "status"])
    escritor.writeheader()
    escritor.writerow({"id": "44444444-4444-4444-8444-444444444444", "slug": "csv", "nome": "Do CSV", "categoria": "Civil",
                       "etiquetas": '["a","b"]', "publicado": "true", "status": ""})
    lido = imp.ler_arquivos([("sistemaia_biblioteca_produtos_rows.csv", saida.getvalue().encode())])
    linha = lido["sistemaia_biblioteca_produtos"][0]
    assert linha["etiquetas"] == ["a", "b"] and linha["publicado"] is True and linha["status"] is None
    assert imp.normalizar_produto(linha)["status"] == "publicado"
    with pytest.raises(imp.ErroImportacao):
        imp.ler_arquivos([("sem_nome.json", b"[]")])
    with pytest.raises(imp.ErroImportacao):
        imp.ler_arquivos([("x.json", b"{quebrado")])


def test_plano_e_mapeamento():
    plano = imp.planejar(imp.ler_arquivos([("c.json", BRUTO)]), existentes={"66666666-6666-4666-8666-666666666666": "produto-antigo"})
    por_slug = {p["slug"]: p for p in plano.produtos}
    assert por_slug["auxilio-acidente"]["papeis"] == ["sdr", "periododegraca", "closer", "contratos", "assinatura", "desqualificado"]
    assert por_slug["auxilio-acidente"]["acao"] == "criar" and por_slug["produto-antigo"]["acao"] == "atualizar"
    assert por_slug["produto-antigo"]["status"] == "publicado"            # linha antiga: vem de "publicado"
    assert por_slug["auxilio-acidente-midia"]["modo_midia"] == "audio"
    avisos = " | ".join(plano.avisos)
    for trecho in ("papel 'follow_up'", "desqualificado está vazio", "'Arquivo sem texto' sem texto", "para contratos fora do padrão",
                   "1 linha(s) apontam para produto"):
        assert trecho in avisos, trecho
    assert plano.frases_globais == 1
    agente = imp.normalizar_agente(DADOS["sistemaia_biblioteca_agentes"][0])
    assert agente["config_modelo"]["faq_items"] == [{"q": "Atende sábado?", "a": "Sim, até meio-dia."}]
    assert agente["config_modelo"]["objecoes"] == [{"gatilho": "Vou pensar", "resposta": "Sem pressa, fico à disposição."}]
    assert agente["config_modelo"]["rules_markdown"] == "Uma pergunta por vez." and agente["config_modelo"]["temperature"] == 0.6


@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_importa_reimporta_sem_duplicar_e_o_produto_ativa():
    from app.banco.postgres import RepositorioPostgres

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        await pool.execute("delete from agentesia_biblioteca_produtos where slug in ('auxilio-acidente', 'auxilio-acidente-midia', 'produto-antigo')")
        await pool.execute("delete from agentesia_frases_troca where id_produto_biblioteca is null")
        dados = imp.ler_arquivos([("c.json", BRUTO)])
        previa = await imp.importar(pool, dados, simular=True)
        assert not previa.aplicado and await pool.fetchval(
            "select count(*) from agentesia_biblioteca_produtos where slug = 'auxilio-acidente'") == 0

        feito = await imp.importar(pool, dados, baixar_arquivos=False)
        assert feito.aplicado
        produto = await pool.fetchrow("select * from agentesia_biblioteca_produtos where slug = 'auxilio-acidente'")
        assert str(produto["id"]) == "11111111-1111-4111-8111-111111111111"           # mantém o id de lá
        assert (produto["status"], produto["versao"], produto["oferece_periodo_graca"], produto["mensagem_fora_horario"]) == (
            "publicado", "1.2.0", True, "Voltamos às 8h.")
        assert json.loads(produto["faq"]) == [{"pergunta": "Quanto custa?", "resposta": "30% dos atrasados, só se ganhar."}]
        seguimento = json.loads(produto["padrao_followup"])
        assert seguimento["cadence"] == [1, 5, 24] and seguimento["agentes"]["assinatura"]["habilitado_padrao"] is False
        midia = await pool.fetchrow("select modo_midia, status, id_produto_base from agentesia_biblioteca_produtos where slug = 'auxilio-acidente-midia'")
        assert (midia["modo_midia"], midia["status"], str(midia["id_produto_base"])) == ("audio", "em_breve", str(produto["id"]))
        agentes = await pool.fetch("select papel, blocos_prompt, config_modelo from agentesia_biblioteca_agentes where id_produto_biblioteca = $1 order by ordem",
                                   produto["id"])
        assert [a["papel"] for a in agentes] == ["sdr", "periododegraca", "closer", "contratos", "assinatura", "desqualificado"]
        assert "@Transferência: Closer" in json.loads(agentes[0]["blocos_prompt"])[0]["content"]
        assert json.loads(agentes[4]["blocos_prompt"])[0]["content"] == "Acompanhe a assinatura."   # jsonb que veio como texto
        assert json.loads(agentes[0]["config_modelo"])["faq_items"][0]["q"] == "Atende sábado?"
        frases = {r["etapa_destino"]: r["frase"] for r in await pool.fetch(
            "select etapa_destino, frase from agentesia_frases_troca where id_produto_biblioteca = $1", produto["id"])}
        assert frases == {"closer": "Agora você vai falar com a nossa especialista"}            # a frase curta não entra
        assert await pool.fetchval("select count(*) from agentesia_frases_troca where id_produto_biblioteca is null") == 1
        docs = await pool.fetch("select nome, texto, travado, situacao from agentesia_documentos where id_produto_biblioteca = $1 order by ordem",
                                produto["id"])
        assert [d["nome"] for d in docs] == ["Tabela de honorários", "Regras do INSS"] and all(d["travado"] for d in docs)

        # Re-importar com um prompt mudado: atualiza, não duplica.
        dados["sistemaia_biblioteca_agentes"][2]["blocos_prompt"][0]["content"] = "Prompt novo do closer."
        await imp.importar(pool, dados, baixar_arquivos=False)
        assert await pool.fetchval("select count(*) from agentesia_biblioteca_produtos where slug like 'auxilio-acidente%'") == 2
        assert await pool.fetchval("select count(*) from agentesia_biblioteca_agentes where id_produto_biblioteca = $1", produto["id"]) == 6
        assert await pool.fetchval("select count(*) from agentesia_documentos where id_produto_biblioteca = $1", produto["id"]) == 2
        closer = await pool.fetchval("select blocos_prompt from agentesia_biblioteca_agentes where id_produto_biblioteca = $1 and papel = 'closer'",
                                     produto["id"])
        assert json.loads(closer)[0]["content"] == "Prompt novo do closer."
    finally:
        await repo.fechar()
