"""Dados da demonstração local (banco PGlite na porta 55437 + Helena falsa na 8020). Só para teste local.

O PGlite aceita uma conexão por vez, e o servidor do painel segura a dele. Por isso são três fases:
  python -m db.testes.semear_demo usuario   # servidor DESLIGADO: cria a conta da equipe LawChat
  python -m db.testes.semear_demo painel    # servidor LIGADO (8012): escritório, agente, limite e documento pela API
  python -m db.testes.semear_demo leads     # servidor DESLIGADO: leads, turnos, contratos e consumo para o funil

As credenciais da demonstração ficam em EMAIL e SENHA abaixo (só valem neste banco em memória).
"""

from __future__ import annotations

import asyncio
import base64
import json
import random
import sys
import uuid

import asyncpg
import httpx

BANCO = "postgresql://postgres:postgres@127.0.0.1:55437/postgres"
PAINEL = "http://127.0.0.1:8012"
EMAIL = "demo@lawchat.local"
SENHA = "demo-lawchat-local-2026"
CONTA_HELENA = "00000000-0000-4000-8000-000000000001"


async def usuario() -> None:
    from app.gestao import seguranca

    conexao = await asyncpg.connect(BANCO, statement_cache_size=0)
    try:
        await conexao.execute(
            """insert into agentesia_usuarios (email, nome, senha_hash, papel) values ($1, 'Equipe Demo', $2, 'dono_lawchat')
               on conflict do nothing""", EMAIL, seguranca.gerar_hash(SENHA))
    finally:
        conexao.terminate()                      # o close() do PGlite não responde
    print("usuário pronto")


async def painel() -> None:
    async with httpx.AsyncClient(base_url=PAINEL, timeout=30) as c:
        r = await c.post("/api/entrar", json={"email": EMAIL, "senha": SENHA})
        r.raise_for_status()
        escritorio = (await c.post("/api/admin/escritorios", json={
            "nome": "Escritório Demo", "id_conta_helena": CONTA_HELENA, "token_helena": "token-demo-helena-123"})).json()["escritorio"]
        h = {"x-escritorio": escritorio["id"]}
        canal = next(x for x in (await c.get("/api/integracoes", headers=h)).json()["canais"] if x["tipo"] != "oficial")
        agente = (await c.post("/api/agentes", headers=h, json={"nome": "Júlia", "id_canal": canal["id"]})).json()
        await c.put(f"/api/admin/escritorios/{escritorio['id']}/limite", json={"mensal_usd": 20, "ao_estourar": "pausar"})
        texto = ("Perícia médica do INSS: leve exames, laudos e documento com foto.\n"
                 "Honorários: 30% dos atrasados, só se ganhar.\nAtendimento: segunda a sexta, 8h às 18h.").encode()
        await c.post(f"/api/agentes/{agente['id']}/documentos", headers=h, json={
            "nome": "Perguntas do escritório.txt", "conteudo_base64": base64.b64encode(texto).decode(), "mime": "text/plain"})
        # Catálogo: dois produtos publicados (5 agentes no padrão) e um "em breve".
        for nome, descricao, etiquetas, status in (
                ("BPC/LOAS Autismo, TDAH e TOD", "BPC/LOAS para pessoas com Autismo (TEA), TDAH e TOD.", ["previdenciario", "bpc", "loas"], "publicado"),
                ("Auxílio-Acidente", "Indenização para quem ficou com sequela após acidente que reduz capacidade de trabalho.",
                 ["previdenciario", "auxilio-acidente", "sequela"], "publicado"),
                ("Pensão por Morte", "Benefício para dependentes do segurado que faleceu.", ["previdenciario", "pensao-morte"], "em_breve")):
            produto = (await c.post("/api/admin/biblioteca/produtos/padrao", json={
                "nome": nome, "area_juridica": "Previdenciário", "categoria": "Previdenciário", "descricao": descricao})).json()
            await c.patch(f"/api/admin/biblioteca/produtos/{produto['id']}", json={
                "status": status, "etiquetas": etiquetas, "descricao_longa": descricao,
                "casos_de_uso": ["Triagem qualificada de novos leads pelo WhatsApp", "Apresentação do serviço e quebra de objeções",
                                 "Geração e envio do contrato pronto para assinatura", "Encaminhamento humano apenas dos casos viáveis"],
                "faq": [{"pergunta": "Quanto tempo demora?", "resposta": "Depende do INSS; em média alguns meses."}],
                "objecoes": [{"titulo": "Acho que é golpe", "resposta": "Mostre o site, o CNPJ e o endereço do escritório."}],
                "dados_escritorio": "Site: {{SITE ESCRITÓRIO}}\nCNPJ: {{CNPJ}}\nEndereço: {{Endereço}}"})
    print("escritório, agente e catálogo prontos:", escritorio["id"])


async def leads() -> None:
    conexao = await asyncpg.connect(BANCO, statement_cache_size=0)
    try:
        esc = await conexao.fetchval("select id from agentesia_escritorios where nome = 'Escritório Demo'")
        agente = await conexao.fetchrow("select id, id_canal from agentesia_agentes where id_escritorio = $1 limit 1", esc)
        etapas = {r["codigo"]: r["id"] for r in await conexao.fetch(
            "select id, codigo from agentesia_agente_etapas where id_agente = $1", agente["id"])}
        caminho = [c for c in ("sdr", "periodo_graca", "closer", "coleta_dados", "assinatura", "contrato_assinado") if c in etapas]
        campanhas = [{"origem": "anuncio", "campanha": "auxilio-acidente-mg", "titulo": "Sofreu acidente?"},
                     {"origem": "anuncio", "campanha": "aa-sp-video"}, {}, {}]
        aleatorio = random.Random(7)
        for i in range(60):
            alcance = min(len(caminho) - 1, int(aleatorio.expovariate(0.55)))
            desq = alcance < 2 and aleatorio.random() < 0.3
            contato = await conexao.fetchval(
                "insert into agentesia_contatos (id_escritorio, nome, telefone_normalizado) values ($1, $2, $3) returning id",
                esc, f"Lead {i + 1}", "55119" + str(10000000 + i))
            lead = await conexao.fetchval(
                """insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_agente, id_etapa, origem, criado_em)
                   values ($1, $2, $3, $4, $5, $6::jsonb, now() - make_interval(days => $7)) returning id""",
                esc, contato, agente["id_canal"], agente["id"], etapas["desqualificado" if desq else caminho[alcance]],
                json.dumps(aleatorio.choice(campanhas)), aleatorio.randint(0, 25))
            for codigo in caminho[: alcance + 1]:
                await conexao.execute(
                    "insert into agentesia_turnos (id_escritorio, id_lead, modo, etapa_depois, situacao) values ($1, $2, 'producao', $3, 'respondido')",
                    esc, lead, codigo)
            if caminho[alcance] == "contrato_assinado":
                await conexao.execute(
                    "insert into agentesia_contratos (id_escritorio, id_lead, versao, situacao, dados, dados_hash) values ($1, $2, 1, 'assinado', '{}', $3)",
                    esc, lead, uuid.uuid4().hex)
        await conexao.execute(
            "insert into agentesia_chamadas_ia (id_escritorio, papel, modelo, custo_usd, sucesso) values ($1, 'etapa', 'gpt-4.1', 12.4, true), ($1, 'extrator', 'gpt-4.1-mini', 4.1, true)",
            esc)
    finally:
        conexao.terminate()                      # o close() do PGlite não responde
    print("leads prontos")


if __name__ == "__main__":
    asyncio.run({"usuario": usuario, "painel": painel, "leads": leads}[sys.argv[1]]())
