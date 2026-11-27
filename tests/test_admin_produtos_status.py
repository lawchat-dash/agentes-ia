"""Admin › Produtos: editar o prompt não mexe no status, e trocar o status aparece na hora (com o cache curto LIGADO).

Relato do dono: "quando vou editar o prompt, coloca em rascunho, ele some ... buga e volta". A lista do admin não pode
voltar ao status anterior por uma cópia guardada, o produto em rascunho continua na lista do admin (só sai do catálogo
dos escritórios) e salvar os agentes não despublica nada.
Só roda com AGENTESIA_TESTE_PG_URL (banco local).
"""

import uuid

from app.gestao import cache_curto
from tests.test_gestao import _entrar, ambiente, pytestmark  # noqa: F401  (fixture do painel com Postgres local)


def _status(lista, id_produto):
    return next((p["status"] for p in lista if p["id"] == id_produto), None)


async def test_editar_prompt_e_trocar_status_com_cache_ligado(ambiente, monkeypatch):
    # O app do teste não tem o middleware que apaga o cache ao escrever: a rota precisa se virar sozinha.
    monkeypatch.setattr(cache_curto, "LIGADO", True)
    cache_curto.limpar_todos()
    cliente, _simulada, email_admin, _banco = ambiente
    await _entrar(cliente, email_admin, "senha-admin-123")

    produto = (await cliente.post("/api/admin/biblioteca/produtos/padrao", json={
        "nome": f"Status {uuid.uuid4().hex[:6]}", "area_juridica": "Previdenciário", "descricao": "teste"})).json()
    pid = produto["id"]
    assert (await cliente.patch(f"/api/admin/biblioteca/produtos/{pid}", json={"status": "publicado"})).status_code == 200

    # Leituras que enchem o cache curto (catálogo dos escritórios e lista do admin).
    assert _status((await cliente.get("/api/biblioteca/produtos")).json(), pid) == "publicado"
    assert _status((await cliente.get("/api/biblioteca/produtos?todos=1")).json(), pid) == "publicado"

    # Editar o prompt (o editor salva os agentes com PUT) não despublica o produto.
    agentes = (await cliente.get(f"/api/biblioteca/produtos/{pid}/agentes")).json()
    linhas = [{"papel": a["papel"], "nome_exibicao": a["nome_exibicao"], "ordem": a["ordem"],
               "texto_prompt": (a.get("texto_prompt") or "") + ("\nLinha nova do SDR." if a["papel"] == "sdr" else ""),
               "blocos_prompt": a["blocos_prompt"]} for a in agentes]
    assert (await cliente.put(f"/api/admin/biblioteca/produtos/{pid}/agentes", json=linhas)).status_code == 200
    assert (await cliente.get(f"/api/biblioteca/produtos/{pid}")).json()["status"] == "publicado"
    assert _status((await cliente.get("/api/biblioteca/produtos?todos=1")).json(), pid) == "publicado"
    assert _status((await cliente.get("/api/biblioteca/produtos")).json(), pid) == "publicado"

    # Rascunho pelo select da lista: o produto CONTINUA na lista do admin, já como rascunho (sem voltar a Publicado),
    # e sai do catálogo dos escritórios na hora (a cópia de 60 s do catálogo não segura o status velho).
    assert (await cliente.patch(f"/api/admin/biblioteca/produtos/{pid}", json={"status": "rascunho"})).json()["status"] == "rascunho"
    assert _status((await cliente.get("/api/biblioteca/produtos?todos=1")).json(), pid) == "rascunho"
    assert _status((await cliente.get("/api/biblioteca/produtos")).json(), pid) is None
    # O admin ainda abre o produto e os agentes, com o prompt editado.
    assert (await cliente.get(f"/api/biblioteca/produtos/{pid}")).json()["status"] == "rascunho"
    sdr = next(a for a in (await cliente.get(f"/api/biblioteca/produtos/{pid}/agentes")).json() if a["papel"] == "sdr")
    assert "Linha nova do SDR." in sdr["texto_prompt"]

    # Salvar de novo em rascunho (editor) mantém rascunho; publicar volta ao catálogo na hora.
    assert (await cliente.put(f"/api/admin/biblioteca/produtos/{pid}/agentes", json=linhas)).status_code == 200
    assert _status((await cliente.get("/api/biblioteca/produtos?todos=1")).json(), pid) == "rascunho"
    assert (await cliente.patch(f"/api/admin/biblioteca/produtos/{pid}", json={"status": "publicado"})).status_code == 200
    assert _status((await cliente.get("/api/biblioteca/produtos?todos=1")).json(), pid) == "publicado"
    assert _status((await cliente.get("/api/biblioteca/produtos")).json(), pid) == "publicado"
