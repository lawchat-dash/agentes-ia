"""Contrato na ZapSign (antigos fluxos "WEAVER - Contrato"): dados, assinatura e o caminho inteiro pela fila."""

import json
import os
import uuid
from datetime import datetime, timezone

import httpx
import pytest

from app.acoes import Executor
from app.canal.helena_conta import HelenaConta
from app.canal.zapsign import Assinante, DocumentoZapSign, ZapSign
from app.cerebro.produto import AuxilioAcidente
from app.contrato import assinatura, servico
from app.contrato import dados as cdados
from app.modelo import ModeloFalso

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
CPF = "529.982.247-25"                         # CPF de exemplo com dígito válido
FATOS = {"nome_completo": "Maria da Silva", "cpf": "52998224725", "cep": "01310100", "endereco": "Avenida Paulista",
         "numero_casa": "1000", "bairro": "Bela Vista", "cidade": "São Paulo", "uf": "sp"}


def test_validacao_e_variaveis():
    assert cdados.cpf_valido(CPF) and not cdados.cpf_valido("111.111.111-11") and not cdados.cpf_valido("529.982.247-24")
    dados, erros = cdados.validar_dados(cdados.dados_dos_fatos(FATOS), "5511988887777")
    assert erros == [] and dados["cpf"] == CPF and dados["cep"] == "01310-100" and dados["estado"] == "SP"
    assert dados["telefone"] == "11988887777" and dados["profissao"] == "Não informado"
    _, erros = cdados.validar_dados({**cdados.dados_dos_fatos(FATOS), "cpf": "123", "cep": "123", "nome": "Maria"})
    assert [e.campo for e in erros] == ["nome", "cpf", "cep"]
    assert cdados.pedir_correcao(erros).startswith("Para finalizar seu contrato, preciso confirmar algumas informações: seu nome completo, o seu CPF e o seu CEP.")
    assert cdados.hash_dados({"a": "1", "b": "2"}) == cdados.hash_dados({"b": "2", "a": "1"})
    variaveis = dict(cdados.montar_variaveis(dados, cdados.MAPEAMENTO_PADRAO, datetime(2026, 11, 22, 15, 30)))
    assert variaveis["NOME"] == "Maria da Silva" and variaveis["DATA"] == "22-11-2026 15:30" and variaveis["Complemento"] == ""
    fixo = cdados.montar_variaveis(dados, [{"variavel": "Foro", "campo": "@fixo", "valor": "Belo Horizonte"}], datetime.now())
    assert fixo == [("Foro", "Belo Horizonte")]


def test_quem_assinou():
    lead = Assinante("tok-lead", "Maria", "signed", "5511988887777", "https://z/l", datetime.now(timezone.utc))
    adv = Assinante("tok-adv", "Dra. Ana", "new", "5511911112222", "https://z/a", None)
    doc = DocumentoZapSign("doc", "pending", None, [lead, adv])
    assert assinatura.identificar_lead(doc, "tok-lead", None)[1] == "token"
    assert assinatura.identificar_lead(doc, None, "(11) 98888-7777")[0] is lead
    assert assinatura.situacao_da_assinatura(doc, lead) == "assinado"
    so_adv = DocumentoZapSign("doc", "pending", None, [Assinante("tok-lead", "Maria", "new", None, None, None),
                                                       Assinante("tok-adv", "Ana", "signed", None, None, None)])
    assert assinatura.situacao_da_assinatura(so_adv, so_adv.assinantes[0]) == "so_o_escritorio_assinou"
    assert assinatura.identificar_lead(so_adv, None, None) == (None, None)
    assert assinatura.situacao_da_assinatura(so_adv, None) == "nao_reconhecido"


def test_coleta_pede_o_que_falta_e_confirma():
    produto = AuxilioAcidente(contrato=True)
    assert [e.codigo for e in produto.etapas][-2:] == ["assinatura", "contrato_assinado"]
    passo = produto.decidir_etapa("coleta_dados", {"nome_completo": "Maria da Silva"}, {})
    assert passo.motivo == "faltam_dados_contrato" and passo.faltam[0] == "cpf"
    assert produto.decidir_etapa("coleta_dados", FATOS, {}).motivo == "confirmar_dados"
    assert produto.decidir_etapa("coleta_dados", FATOS, {"confirmou_dados": True}).motivo == "dados_confirmados"
    assert produto.decidir_etapa("assinatura", FATOS, {"diz_que_assinou": True}).motivo == "diz_que_assinou"
    assert [e.codigo for e in AuxilioAcidente().etapas][-1] == "desqualificado"      # sem a função, sem etapas de contrato


class ZapSignFalsa:
    def __init__(self):
        self.criados, self.assinado, self.falhar = [], False, None
        self.p = uuid.uuid4().hex[:6]                    # ids únicos por teste (o banco de teste é reaproveitado)

    def __call__(self, pedido: httpx.Request) -> httpx.Response:
        if self.falhar:
            return httpx.Response(self.falhar, json={"message": "erro"})
        if pedido.url.path == "/api/v1/models/create-doc/":
            corpo = json.loads(pedido.content)
            self.criados.append(corpo)
            n = len(self.criados)
            return httpx.Response(200, json={"token": f"doc{self.p}-{n}", "signers": [
                {"token": f"signer-{n}", "name": corpo["signer_name"], "status": "new", "sign_url": f"https://app.zapsign.com.br/verificar/{n}"}]})
        if pedido.url.path.startswith("/api/v1/docs/"):
            n = pedido.url.path.rstrip("/").split("-")[-1]
            status = "signed" if self.assinado else "new"
            return httpx.Response(200, json={"token": f"doc{self.p}-{n}", "status": status, "signed_file": "https://z/arquivo.pdf" if self.assinado else None,
                                             "signers": [{"token": f"signer-{n}", "name": "Maria", "status": status,
                                                          "phone_number": "11988887777", "signed_at": "2026-11-22T18:00:00Z" if self.assinado else None}]})
        return httpx.Response(404)


@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_gera_manda_link_e_confere_assinatura():
    from app.banco.postgres import RepositorioPostgres

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        # A fila é do banco inteiro: ações pendentes de outros testes não podem atravessar este.
        await pool.execute("update agentesia_acoes set situacao = 'cancelada' where situacao in ('pendente', 'executando')")
        token_h = await pool.fetchval("select vault.create_secret('token-helena', 'teste')")
        token_z = await pool.fetchval("select vault.create_secret($1, 'teste')", "token-zapsign-" + uuid.uuid4().hex[:8])
        esc = await pool.fetchval("insert into agentesia_escritorios (nome) values ('Contratos') returning id")
        await pool.execute("insert into agentesia_integracoes (id_escritorio, tipo, id_segredo_vault, situacao) values ($1, 'helena', $2, 'ok')", esc, token_h)
        await pool.execute(
            "insert into agentesia_integracoes (id_escritorio, tipo, id_segredo_vault, situacao, config) values ($1, 'zapsign', $2, 'ok', $3::jsonb)",
            esc, token_z, json.dumps({"modelos": [{"id_modelo": "modelo-1", "padrao": True}], "lembretes": {"ativo": True, "horas": [2]}}))
        canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado, id_canal_helena) values ($1, $2, $3) returning id",
                                    esc, "5511" + str(uuid.uuid4().int)[:9], "ch-" + uuid.uuid4().hex[:6])
        agente = await pool.fetchval(
            "insert into agentesia_agentes (id_escritorio, id_canal, nome, produto, config) values ($1, $2, 'Júlia', 'auxilio_acidente', $3::jsonb) returning id",
            esc, canal, json.dumps({"funcoes": {"contrato_zapsign": True}}))
        etapas = {}
        for ordem, (codigo, tipo) in enumerate([("coleta_dados", "conversa"), ("assinatura", "conversa"), ("contrato_assinado", "terminal")]):
            etapas[codigo] = await pool.fetchval(
                "insert into agentesia_agente_etapas (id_agente, codigo, ordem, tipo, principal) values ($1, $2, $3, $4, $5) returning id",
                agente, codigo, ordem, tipo, ordem == 0)
        contato = await pool.fetchval("insert into agentesia_contatos (id_escritorio, nome, telefone_normalizado) values ($1, 'Maria', '5511988887777') returning id", esc)
        lead = await pool.fetchval(
            "insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_agente, id_etapa, id_sessao_helena) values ($1, $2, $3, $4, $5, 'sessao-c') returning id",
            esc, contato, canal, agente, etapas["coleta_dados"])

        dados, _ = cdados.validar_dados(cdados.dados_dos_fatos(FATOS), "5511988887777")
        hash_dados = cdados.hash_dados(dados)
        await repo.enfileirar_acoes(id_escritorio=str(esc), id_lead=str(lead), id_turno=None, acoes=[
            {"tipo": "gerar_contrato", "chave_unica": f"{lead}:contrato:{hash_dados}", "dados": {"dados": dados, "hash": hash_dados}}])

        zapsign, mensagens, notas = ZapSignFalsa(), [], []

        def helena(pedido: httpx.Request) -> httpx.Response:
            if pedido.url.path.endswith("/message"):
                mensagens.append(json.loads(pedido.content))
            if pedido.url.path.endswith("/note"):
                notas.append(json.loads(pedido.content).get("text", ""))
            return httpx.Response(200, json={"id": "m"})

        executor = Executor(pool, "https://api.helena.run",
                            helena_por_token=lambda t, u: HelenaConta(t, u, httpx.AsyncClient(transport=httpx.MockTransport(helena))),
                            zapsign_por_token=lambda t, u: ZapSign(t, u, httpx.AsyncClient(transport=httpx.MockTransport(zapsign))),
                            modelo=ModeloFalso({"contrato_resumo": {"resumo": "📄 Resumo do caso: acidente de moto em 2023, sequela no joelho."}}))
        await executor.rodar_uma_vez()          # gera
        await executor.rodar_uma_vez()          # manda link e nota
        assert zapsign.criados[0]["template_id"] == "modelo-1" and zapsign.criados[0]["signer_phone_number"] == "11988887777"
        assert {"de": "CPF", "para": CPF} in zapsign.criados[0]["data"]
        contrato = await pool.fetchrow("select * from agentesia_contratos where id_lead = $1", lead)
        assert (contrato["situacao"], contrato["versao"], contrato["id_documento_externo"]) == ("gerado", 1, f"doc{zapsign.p}-1")
        assert zapsign.criados[0]["external_id"] == str(contrato["id"])
        assert any("Segue o link de contrato:\nhttps://app.zapsign.com.br/verificar/1" == m.get("text") for m in mensagens)
        assert await pool.fetchval("select id_etapa from agentesia_leads where id = $1", lead) == etapas["assinatura"]
        assert await pool.fetchval("select count(*) from agentesia_acoes where id_lead = $1 and tipo = 'lembrar_assinatura' and situacao = 'pendente'", lead) == 1

        # Mesmo pedido de novo: mesma chave, nada novo na ZapSign.
        await repo.enfileirar_acoes(id_escritorio=str(esc), id_lead=str(lead), id_turno=None, acoes=[
            {"tipo": "gerar_contrato", "chave_unica": f"{lead}:contrato:{hash_dados}", "dados": {"dados": dados, "hash": hash_dados}}])
        await executor.rodar_uma_vez()
        assert len(zapsign.criados) == 1

        # Aviso da ZapSign: relê, marca assinado uma vez, encerra a IA e cancela o lembrete.
        zapsign.assinado = True
        await pool.execute("insert into agentesia_mensagens (id_escritorio, id_lead, autor, texto, enviada_em) values ($1, $2, 'lead', 'caí de moto', now())", esc, lead)
        corpo ={"event_type": "doc_signed", "token": f"doc{zapsign.p}-1", "signer_who_signed": {"token": "signer-1"}}
        assert await servico.receber_webhook(pool, str(esc), corpo) == "processado"
        assert await servico.receber_webhook(pool, str(esc), corpo) == "repetido"
        assert await servico.receber_webhook(pool, str(esc), {**corpo, "token": f"doc-do-weaver-{zapsign.p}"}) == "ignorado:documento_desconhecido"
        await executor.rodar_uma_vez()
        await executor.rodar_uma_vez()
        contrato = await pool.fetchrow("select * from agentesia_contratos where id_lead = $1", lead)
        assert contrato["situacao"] == "assinado" and contrato["arquivo_assinado"] == "https://z/arquivo.pdf"
        linha = await pool.fetchrow("select id_etapa, estado, motivo_estado from agentesia_leads where id = $1", lead)
        assert (linha["id_etapa"], linha["estado"], linha["motivo_estado"]) == (etapas["contrato_assinado"], "encerrado", "contrato_assinado")
        assert any((m.get("text") or "").startswith("✅ Assinatura confirmada!") for m in mensagens)
        assert await pool.fetchval("select situacao from agentesia_acoes where id_lead = $1 and tipo = 'lembrar_assinatura'", lead) == "cancelada"
        await executor.rodar_uma_vez()                                          # resumo do contrato assinado
        assert "sequela no joelho" in (await pool.fetchval("select resumo from agentesia_contratos where id_lead = $1", lead) or "")
        await executor.rodar_uma_vez()                                          # a nota do assinado (com o resumo)
        assert any(n.startswith("📄 Contrato Assinado!") and "sequela no joelho" in n for n in notas)

        # ZapSign fora do ar na geração de outro lead: avisa o lead uma vez e tenta de novo depois.
        contato2 = await pool.fetchval("insert into agentesia_contatos (id_escritorio, telefone_normalizado) values ($1, '5511977776666') returning id", esc)
        lead2 = await pool.fetchval(
            "insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_agente, id_etapa, id_sessao_helena) values ($1, $2, $3, $4, $5, 'sessao-d') returning id",
            esc, contato2, canal, agente, etapas["coleta_dados"])
        zapsign.falhar = 503
        await repo.enfileirar_acoes(id_escritorio=str(esc), id_lead=str(lead2), id_turno=None, acoes=[
            {"tipo": "gerar_contrato", "chave_unica": f"{lead2}:contrato:x", "dados": {"dados": dados, "hash": "x" * 16}}])
        await executor.rodar_uma_vez()
        assert await pool.fetchval("select situacao from agentesia_acoes where id_lead = $1 and tipo = 'gerar_contrato'", lead2) == "pendente"
        assert await pool.fetchval("select situacao from agentesia_contratos where id_lead = $1", lead2) == "erro"
        # Chave recusada: falha definitiva, mensagem "equipe vai enviar" e evento do cliente.
        zapsign.falhar = 401
        await pool.execute("update agentesia_acoes set proxima_em = now() where id_lead = $1", lead2)
        await executor.rodar_uma_vez()
        await executor.rodar_uma_vez()
        assert await pool.fetchval("select situacao from agentesia_acoes where id_lead = $1 and tipo = 'gerar_contrato'", lead2) == "feita"
        assert await pool.fetchval("select responsavel from agentesia_eventos where id_lead = $1 and tipo = 'contrato_chave'", lead2) == "cliente"
    finally:
        await repo.fechar()



def test_assinatura_aceita_correcao_e_fatos_do_sistema_vao_no_prompt():
    from app.cerebro import agente
    produto = AuxilioAcidente(contrato=True)
    assert produto.decidir_etapa("assinatura", FATOS, {"confirmou_dados": True}).motivo == "dados_confirmados"
    assert produto.decidir_etapa("assinatura", {**FATOS, "cpf": "123"}, {"confirmou_dados": True}).motivo == "aguardando_assinatura"
    conteudo = agente.montar_conteudo(etapa="assinatura", fatos={}, faltam=(), motivo="", sinais=[], honorarios=None, midias={},
                                      historico=[], novas=["oi"], produto=produto,
                                      fatos_sistema={"contrato": "gerado, aguardando assinatura (versão 1)", "vazio": ""})
    assert "FATOS DO SISTEMA" in conteudo and "versão 1" in conteudo and "vazio" not in conteudo
