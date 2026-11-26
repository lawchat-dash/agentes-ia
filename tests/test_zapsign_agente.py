"""ZapSign usada pelo agente (docs/ZAPSIGN_CAPACIDADES.md, A1-A10): "já assinei" esperto, assinante certo, cancelar a
versão antiga, recusa/exclusão, contato sem contrato novo, PDF guardado, consulta periódica, normalização, lembrete
contextual, plano/créditos e o resumo do contrato assinado. Nada chama a ZapSign, a Helena ou a IA de verdade
(httpx.MockTransport e ModeloFalso); as partes com banco usam AGENTESIA_TESTE_PG_URL."""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.acoes import Executor
from app.canal.helena_conta import HelenaConta
from app.canal.zapsign import Assinante, DocumentoZapSign, ZapSign, _documento, problema_do_plano
from app.contrato import assinatura, servico
from app.contrato import dados as cdados
from app.contrato import resumo as cresumo
from app.modelo import ModeloFalso

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
precisa_pg = pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
FATOS = {"nome_completo": "Maria da Silva", "cpf": "52998224725", "cep": "01310100", "endereco": "Avenida Paulista",
         "numero_casa": "1000", "bairro": "Bela Vista", "cidade": "São Paulo", "uf": "sp"}
AGORA = datetime(2026, 11, 25, 15, 0, tzinfo=timezone.utc)


# ----------------------------------------------------------------------------- puro
def test_documento_le_visualizacoes_exclusao_e_recusa():
    doc = _documento({"token": "d1", "status": "refused", "deleted": False, "external_id": "c1", "rejected_reason": "desisti",
                      "signers": [{"token": "s1", "name": "Maria", "status": "link-opened", "times_viewed": 3,
                                   "last_view_at": "2026-11-25T14:30:00Z", "phone_number": "11988887777",
                                   "external_id": "lead-1", "email": "m@x.com"}]})
    a = doc.assinantes[0]
    assert (a.vezes_visto, a.ultimo_acesso.hour, a.id_externo, a.email) == (3, 14, "lead-1", "m@x.com")
    assert (doc.id_externo, doc.motivo_recusa, doc.excluido) == ("c1", "desisti", False)
    assert assinatura.situacao_da_assinatura(doc, a) == "cancelado"
    assert assinatura.situacao_da_assinatura(_documento({"status": "pending", "deleted": True, "signers": []}), None) == "excluido"
    vencido = _documento({"status": "pending", "date_limit_to_sign": "2026-11-20T00:00:00Z", "signers": [{"token": "s", "status": "new"}]})
    assert assinatura.situacao_da_assinatura(vencido, vencido.assinantes[0], AGORA) == "expirado"


def test_leitura_e_linha_para_a_ia():
    nunca = Assinante("s", "Maria", "new", None, "https://z/1", None)
    abriu = Assinante("s", "Maria", "link-opened", None, "https://z/1", None, vezes_visto=2,
                      ultimo_acesso=AGORA - timedelta(minutes=20))
    doc = DocumentoZapSign("d", "pending", None, [nunca])
    assert assinatura.ler(doc, nunca).abertura == "nunca_abriu"
    leitura = assinatura.ler(DocumentoZapSign("d", "pending", None, [abriu]), abriu)
    assert leitura.abertura == "abriu_sem_assinar" and leitura.abriu_ha_menos_de(60, AGORA)
    assert not leitura.abriu_ha_menos_de(10, AGORA)
    linha = assinatura.linha_para_ia(leitura, "25/11 12:00")
    assert linha.startswith("ASSINATURA DO CONTRATO (sistema) (conferido na ZapSign 25/11 12:00):") and "selfie" in linha
    cancelado = assinatura.linha_para_ia(assinatura.Leitura("cancelado", "nunca_abriu"))
    assert "NÃO mande o link antigo" in cancelado


def test_assinante_certo_quando_o_advogado_vem_primeiro():
    adv = Assinante("tok-adv", "Dra. Ana Souza", "new", "11911112222", "https://z/adv", None)
    lead = Assinante("tok-lead", "Maria da Silva", "new", "11988887777", "https://z/lead", None, id_externo="c1")
    doc = DocumentoZapSign("d", "pending", None, [adv, lead])
    assert assinatura.assinante_do_lead_na_geracao(doc, nome="Maria da Silva", telefone="11988887777", id_externo=None) is lead
    assert assinatura.identificar_lead(doc, None, None, "c1")[1] == "external_id"
    assert assinatura.identificar_lead(doc, None, None, None, "MARIA DA SILVA")[1] == "nome"
    assert doc.link_de("tok-lead") == "https://z/lead" and doc.link == "https://z/adv"


def test_normalizacao_estado_civil_rg_e_profissao():
    base = cdados.dados_dos_fatos(FATOS)
    casos = {"casada": "Casada", "Casado no civil": "Casado", "solteiro(a)": "Solteiro(a)", "viúva": "Viúva",
             "moro junto com ele": "União estável", "divorciada": "Divorciada", "outro": "outro"}
    for bruto, esperado in casos.items():
        d, erros = cdados.validar_dados({**base, "estado_civil": bruto})
        assert erros == [] and d["estado_civil"] == esperado, bruto
    d, _ = cdados.validar_dados({**base, "rg": " rg: mg 12 . 345 . 678 "})
    assert d["rg"] == "MG 12.345.678"
    d, erros = cdados.validar_dados({**base, "rg": "não tenho"})
    assert "rg" not in d and erros == []
    _, erros = cdados.validar_dados({**base, "rg": "não tenho"}, obrigatorios=cdados.OBRIGATORIOS_PADRAO + ("rg",))
    assert [e.campo for e in erros] == ["rg"]
    for bruto in ("do lar", "Dona de casa", "faço bico", "bicos", "desempregada", "sem emprego"):
        assert cdados.validar_dados({**base, "profissao": bruto})[0]["profissao"] == "Desempregado", bruto
    assert cdados.validar_dados({**base, "profissao": "Pedreiro"})[0]["profissao"] == "Pedreiro"


def test_plano_consulta_periodica_e_config_do_resumo():
    assert problema_do_plano({"number_of_credits": "0", "status": "paid"}) == "sem_credito"
    assert problema_do_plano({"number_of_credits": "100", "status": "overdue"}) == "plano_pendente"
    assert problema_do_plano({"number_of_credits": "100", "status": "paid"}) is None
    assert problema_do_plano({}) is None and problema_do_plano({"number_of_credits": "ilimitado"}) is None
    gerado = AGORA - timedelta(hours=1)
    assert servico.momento_da_consulta(AGORA - timedelta(minutes=10), AGORA) is None
    assert servico.momento_da_consulta(gerado, AGORA).startswith("m")
    assert servico.momento_da_consulta(gerado, AGORA + timedelta(minutes=10)) == servico.momento_da_consulta(gerado, AGORA)
    assert servico.momento_da_consulta(gerado, AGORA + timedelta(minutes=31)) != servico.momento_da_consulta(gerado, AGORA)
    assert servico.momento_da_consulta(AGORA - timedelta(days=3), AGORA) == "d2026-11-25"
    assert servico.momento_da_consulta(AGORA - timedelta(days=31), AGORA) is None
    padrao = cresumo.configuracao({}, {})
    assert padrao["ativo"] and padrao["origem"] == "padrao" and "Pontos de atenção" in padrao["prompt"]
    escritorio = cresumo.configuracao({}, {"resumo": {"prompt": "do escritório", "no_aviso": True}})
    assert (escritorio["prompt"], escritorio["no_aviso"]) == ("do escritório", True)
    agente = cresumo.configuracao({"resumo_contrato": {"prompt": "do agente", "no_aviso": False}}, {"resumo": {"prompt": "x", "no_aviso": True}})
    assert (agente["prompt"], agente["origem"], agente["no_aviso"]) == ("do agente", "agente", False)
    assert not cresumo.configuracao({"resumo_contrato": {"ativo": False}}, {})["ativo"]


async def test_cliente_manda_os_corpos_certos():
    pedidos = []

    def zap(pedido: httpx.Request) -> httpx.Response:
        pedidos.append(pedido)
        if pedido.url.path == "/api/v1/info-plan/":
            return httpx.Response(200, json={"name": "API", "number_of_credits": "7", "status": "paid"})
        if pedido.url.path == "/api/v1/refuse/" and json.loads(pedido.content)["doc_token"] == "assinado":
            return httpx.Response(403, json={"detail": "document_already_signed"})
        return httpx.Response(200, json={"message": "ok"})

    z = ZapSign("tok", http=httpx.AsyncClient(transport=httpx.MockTransport(zap)))
    await z.cancelar("doc-1", "Substituído pela versão 2")
    corpo = json.loads(pedidos[-1].content)
    assert (pedidos[-1].url.path, corpo) == ("/api/v1/refuse/", {"doc_token": "doc-1", "rejected_reason": "Substituído pela versão 2", "notify_signer": False})
    assert pedidos[-1].headers["user-agent"].startswith("LawChat") and pedidos[-1].headers["authorization"] == "Bearer tok"
    with pytest.raises(Exception) as erro:
        await z.cancelar("assinado", "x")
    assert erro.value.motivo == "nao_encontrado"
    assert await z.atualizar_signatario("sig-1", telefone="11977776666")
    assert (pedidos[-1].url.path, json.loads(pedidos[-1].content)) == ("/api/v1/signers/sig-1/", {"phone_country": "55", "phone_number": "11977776666"})
    assert not await z.atualizar_signatario("sig-1")
    assert (await z.plano())["number_of_credits"] == "7"


# ----------------------------------------------------------------------------- com banco
class ZapSignFalsa:
    """Documento com o advogado como 1º signatário (o lead vem depois), estado por documento."""

    def __init__(self):
        self.p = uuid.uuid4().hex[:6]
        self.docs: dict[str, dict] = {}
        self.criados, self.cancelados, self.signatarios, self.baixados = [], [], [], 0
        self.plano = {"name": "API", "number_of_credits": "50", "status": "paid"}

    def __call__(self, pedido: httpx.Request) -> httpx.Response:
        caminho = pedido.url.path
        if pedido.url.host == "arquivos.zapsign.test":
            self.baixados += 1
            assert "authorization" not in pedido.headers           # o token não vai para o host do arquivo
            return httpx.Response(200, content=b"%PDF-1.4 contrato assinado")
        if caminho == "/api/v1/info-plan/":
            return httpx.Response(200, json=self.plano)
        if caminho == "/api/v1/models/create-doc/":
            corpo = json.loads(pedido.content)
            self.criados.append(corpo)
            n = len(self.criados)
            token = f"doc{self.p}-{n}"
            self.docs[token] = {"token": token, "status": "pending", "deleted": False, "external_id": corpo["external_id"],
                                "signers": [
                                    {"token": f"adv-{n}", "name": "Dra. Ana", "status": "new", "phone_number": "11911112222",
                                     "sign_url": f"https://app.zapsign.com.br/verificar/adv-{n}"},
                                    {"token": f"lead-{self.p}-{n}", "name": corpo["signer_name"], "status": "new",
                                     "phone_number": corpo["signer_phone_number"], "times_viewed": 0,
                                     "sign_url": f"https://app.zapsign.com.br/verificar/lead-{n}"}]}
            return httpx.Response(200, json=self.docs[token])
        if caminho == "/api/v1/refuse/":
            corpo = json.loads(pedido.content)
            self.cancelados.append(corpo)
            self.docs[corpo["doc_token"]]["status"] = "refused"
            return httpx.Response(200, json={"message": "Documento cancelado com sucesso!"})
        if caminho.startswith("/api/v1/signers/"):
            self.signatarios.append((caminho.split("/")[-2], json.loads(pedido.content)))
            return httpx.Response(200, json={})
        if caminho.startswith("/api/v1/docs/"):
            token = caminho.rstrip("/").split("/")[-1]
            doc = self.docs.get(token)
            return httpx.Response(200, json={k: v for k, v in doc.items() if k != "sign_url"}) if doc else httpx.Response(404)
        return httpx.Response(404)

    def lead(self, n: int) -> dict:
        return self.docs[f"doc{self.p}-{n}"]["signers"][1]

    def assinar(self, n: int) -> None:
        doc = self.docs[f"doc{self.p}-{n}"]
        doc["status"] = "signed"
        doc["signed_file"] = f"https://arquivos.zapsign.test/{doc['token']}.pdf?assinatura=60min"
        for s in doc["signers"]:
            s.update(status="signed", signed_at="2026-11-25T18:00:00Z")


async def _montar(pool, *, config_zapsign=None, config_agente=None):
    await pool.execute("update agentesia_acoes set situacao = 'cancelada' where situacao in ('pendente', 'executando')")
    token_h = await pool.fetchval("select vault.create_secret('token-helena', 'teste')")
    token_z = await pool.fetchval("select vault.create_secret($1, 'teste')", "token-zapsign-" + uuid.uuid4().hex[:6])
    esc = await pool.fetchval("insert into agentesia_escritorios (nome) values ('ZapSign agente') returning id")
    await pool.execute("insert into agentesia_integracoes (id_escritorio, tipo, id_segredo_vault, situacao) values ($1, 'helena', $2, 'ok')", esc, token_h)
    await pool.execute(
        "insert into agentesia_integracoes (id_escritorio, tipo, id_segredo_vault, situacao, config) values ($1, 'zapsign', $2, 'ok', $3::jsonb)",
        esc, token_z, json.dumps({"modelos": [{"id_modelo": "modelo-1", "padrao": True}], "lembretes": {"ativo": True, "horas": [2]},
                                  **(config_zapsign or {})}))
    canal = await pool.fetchval("insert into agentesia_canais (id_escritorio, numero_normalizado, id_canal_helena) values ($1, $2, $3) returning id",
                                esc, "5511" + str(uuid.uuid4().int)[:9], "ch-" + uuid.uuid4().hex[:6])
    agente = await pool.fetchval(
        "insert into agentesia_agentes (id_escritorio, id_canal, nome, produto, config) values ($1, $2, 'Júlia', 'auxilio_acidente', $3::jsonb) returning id",
        esc, canal, json.dumps({"funcoes": {"contrato_zapsign": True, "avisos": True}, **(config_agente or {})}))
    etapas = {}
    for ordem, (codigo, tipo) in enumerate([("coleta_dados", "conversa"), ("assinatura", "conversa"), ("contrato_assinado", "terminal")]):
        etapas[codigo] = await pool.fetchval(
            "insert into agentesia_agente_etapas (id_agente, codigo, ordem, tipo, principal) values ($1, $2, $3, $4, $5) returning id",
            agente, codigo, ordem, tipo, ordem == 0)
    contato = await pool.fetchval("insert into agentesia_contatos (id_escritorio, nome, telefone_normalizado) values ($1, 'Maria', '5511988887777') returning id", esc)
    lead = await pool.fetchval(
        "insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_agente, id_etapa, id_sessao_helena) values ($1, $2, $3, $4, $5, 'sessao-z') returning id",
        esc, contato, canal, agente, etapas["coleta_dados"])
    return esc, lead, etapas


def _executor(pool, zapsign, mensagens, notas, cards=None, modelo=None):
    def helena(pedido: httpx.Request) -> httpx.Response:
        if pedido.url.path.endswith("/message"):
            mensagens.append(json.loads(pedido.content).get("text") or "")
        if pedido.url.path.endswith("/note"):
            notas.append(json.loads(pedido.content).get("text", ""))
        if "/panel/card/" in pedido.url.path and cards is not None:
            cards.append(json.loads(pedido.content))
        return httpx.Response(200, json={"id": "m"})

    return Executor(pool, "https://api.helena.run",
                    helena_por_token=lambda t, u: HelenaConta(t, u, httpx.AsyncClient(transport=httpx.MockTransport(helena))),
                    zapsign_por_token=lambda t, u: ZapSign(t, u, httpx.AsyncClient(transport=httpx.MockTransport(zapsign))),
                    modelo=modelo)


async def _drenar(executor, vezes=8):
    for _ in range(vezes):
        if not await executor.rodar_uma_vez():
            return


async def _pedir_contrato(repo, esc, lead, fatos):
    dados, _ = cdados.validar_dados(cdados.dados_dos_fatos(fatos), "5511988887777")
    h = cdados.hash_dados(dados)
    await repo.enfileirar_acoes(id_escritorio=str(esc), id_lead=str(lead), id_turno=None, acoes=[
        {"tipo": "gerar_contrato", "chave_unica": f"{lead}:contrato:{h}", "dados": {"dados": dados, "hash": h}}])


async def _ja_assinei(repo, esc, lead):
    await repo.enfileirar_acoes(id_escritorio=str(esc), id_lead=str(lead), id_turno=None, acoes=[
        {"tipo": "verificar_assinatura", "chave_unica": f"{lead}:{uuid.uuid4().hex}:verificar", "dados": {"origem": "verificacao"}}])


@precisa_pg
async def test_ja_assinei_assinante_certo_contato_e_versao_nova_cancela_a_antiga():
    from app.banco.postgres import RepositorioPostgres

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        esc, lead, _ = await _montar(pool)
        zapsign, mensagens, notas = ZapSignFalsa(), [], []
        executor = _executor(pool, zapsign, mensagens, notas)
        await _pedir_contrato(repo, esc, lead, FATOS)
        await _drenar(executor)
        contrato = await pool.fetchrow("select * from agentesia_contratos where id_lead = $1", lead)
        # 2) O lead é o 2º signatário (o advogado vem primeiro no modelo): token e link são os dele.
        assert contrato["id_assinante_externo"] == f"lead-{zapsign.p}-1"
        assert contrato["link"] == "https://app.zapsign.com.br/verificar/lead-1"
        assert "Segue o link de contrato:\nhttps://app.zapsign.com.br/verificar/lead-1" in mensagens

        # 1) "Já assinei" e nunca abriu: link de novo; a leitura vira linha (sistema) nos fatos da IA.
        await _ja_assinei(repo, esc, lead)
        await _drenar(executor)
        assert mensagens[-1] == "Ainda não consta a sua assinatura por aqui. Segue o link novamente:\nhttps://app.zapsign.com.br/verificar/lead-1"
        fatos = await repo.fatos_do_sistema(str(lead))
        assert "AINDA NÃO ABRIU" in fatos["assinatura do contrato (sistema)"]
        # Abriu e não concluiu: pergunta onde travou.
        zapsign.lead(1).update(status="link-opened", times_viewed=2, last_view_at="2026-11-25T10:00:00Z")
        await _ja_assinei(repo, esc, lead)
        await _drenar(executor)
        assert mensagens[-1].startswith("Conferi aqui e vi que você abriu o contrato") and "selfie" in mensagens[-1]
        assert "ABRIU o link 2 vez(es)" in (await repo.fatos_do_sistema(str(lead)))["assinatura do contrato (sistema)"]

        # 5) Corrigiu só o telefone: atualiza o signatário, sem documento novo.
        await _pedir_contrato(repo, esc, lead, {**FATOS, "telefone_contrato": "(11) 97777-6666"})
        await _drenar(executor)
        assert len(zapsign.criados) == 1
        assert zapsign.signatarios == [(f"lead-{zapsign.p}-1", {"phone_country": "55", "phone_number": "11977776666"})]
        assert mensagens[-1].startswith("Pronto, atualizei o seu contato no contrato.")
        assert await pool.fetchval("select dados->>'telefone' from agentesia_contratos where id_lead = $1 and situacao = 'gerado'", lead) == "11977776666"

        # 3) Corrigiu o CPF... digo, o número da casa: versão 2, e a 1 é cancelada na ZapSign depois de gravar a 2.
        await _pedir_contrato(repo, esc, lead, {**FATOS, "telefone_contrato": "(11) 97777-6666", "numero_casa": "2000"})
        await _drenar(executor)
        assert len(zapsign.criados) == 2
        assert zapsign.cancelados == [{"doc_token": f"doc{zapsign.p}-1", "rejected_reason": "Substituído pela versão 2", "notify_signer": False}]
        assert await pool.fetchval("select causa_erro from agentesia_contratos where id_lead = $1 and versao = 1", lead) == "cancelado_na_zapsign"
        # O aviso doc_refused da nossa própria cancelação: só registra (não pausa nem avisa a equipe).
        assert await servico.receber_webhook(pool, str(esc), {"event_type": "doc_refused", "token": f"doc{zapsign.p}-1"}) == "processado"
        await _drenar(executor)
        assert await pool.fetchval("select estado from agentesia_leads where id = $1", lead) == "ativo"
        assert await pool.fetchval("select situacao from agentesia_contratos where id_lead = $1 and versao = 2", lead) == "gerado"
    finally:
        # Não deixa ações vencidas para os outros testes (a fila é do banco inteiro).
        await pool.execute("update agentesia_acoes set situacao = 'cancelada' where situacao in ('pendente', 'executando')")
        await repo.fechar()


@precisa_pg
async def test_geracao_que_volta_tarde_nao_passa_por_cima_da_correcao():
    from app.banco.postgres import RepositorioPostgres

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        esc, lead, _ = await _montar(pool)
        zapsign, mensagens, notas = ZapSignFalsa(), [], []
        executor = _executor(pool, zapsign, mensagens, notas)
        await _pedir_contrato(repo, esc, lead, FATOS)
        # A 1ª geração está esperando nova tentativa (ZapSign fora do ar) quando chega a correção.
        await pool.execute("update agentesia_acoes set proxima_em = now() + interval '1 hour', criado_em = now() - interval '5 minutes' where id_lead = $1", lead)
        await _pedir_contrato(repo, esc, lead, {**FATOS, "numero_casa": "2000"})
        await _drenar(executor)
        assert len(zapsign.criados) == 1 and {"de": "Número", "para": "2000"} in zapsign.criados[0]["data"]
        await pool.execute("update agentesia_acoes set proxima_em = now() where id_lead = $1 and situacao = 'pendente' and tipo = 'gerar_contrato'", lead)
        await _drenar(executor)
        assert len(zapsign.criados) == 1                  # a velha não gerou a versão 2 com o número antigo
        resultado = await pool.fetchval(
            "select resultado->>'situacao' from agentesia_acoes where id_lead = $1 and tipo = 'gerar_contrato' order by criado_em limit 1", lead)
        assert resultado == "obsoleta"
    finally:
        # Não deixa ações vencidas para os outros testes (a fila é do banco inteiro).
        await pool.execute("update agentesia_acoes set situacao = 'cancelada' where situacao in ('pendente', 'executando')")
        await repo.fechar()


@precisa_pg
async def test_recusa_pausa_a_ia_para_lembretes_e_avisa_a_equipe():
    from app.banco.postgres import RepositorioPostgres

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        esc, lead, _ = await _montar(pool)
        zapsign, mensagens, notas = ZapSignFalsa(), [], []
        executor = _executor(pool, zapsign, mensagens, notas)
        await _pedir_contrato(repo, esc, lead, FATOS)
        await _drenar(executor)
        contrato = await pool.fetchrow("select * from agentesia_contratos where id_lead = $1", lead)
        token = contrato["id_documento_externo"]
        assert await servico.receber_webhook(pool, str(esc), {"event_type": "doc_refused", "token": token, "external_id": "outro"}) == "ignorado:external_id"
        zapsign.docs[token].update(status="refused", rejected_reason="Desisti do processo")
        assert await servico.receber_webhook(pool, str(esc), {"event_type": "doc_refused", "token": token, "external_id": str(contrato["id"]),
                                                               "signers": [{"cpf": "529.982.247-25"}]}) == "processado"
        guardado = await pool.fetchval("select payload from agentesia_eventos_recebidos where id_externo = $1", f"{token}:doc_refused:")
        assert "cpf" not in json.dumps(guardado)                                         # LGPD: só o que usamos
        await _drenar(executor)
        contrato = await pool.fetchrow("select * from agentesia_contratos where id_lead = $1", lead)
        assert (contrato["situacao"], contrato["causa_erro"], contrato["erro"]) == ("cancelado", "cancelado", "Desisti do processo")
        linha = await pool.fetchrow("select estado, motivo_estado from agentesia_leads where id = $1", lead)
        assert (linha["estado"], linha["motivo_estado"]) == ("pausado", "contrato_cancelado")
        assert await pool.fetchval("select situacao from agentesia_acoes where id_lead = $1 and tipo = 'lembrar_assinatura'", lead) == "cancelada"
        assert any("foi cancelado ou recusado na ZapSign" in n and "Desisti do processo" in n for n in notas)
        assert await pool.fetchval("select count(*) from agentesia_eventos where id_lead = $1 and tipo = 'contrato_cancelado'", lead) == 1
        # Repetir a releitura (aviso de novo, consulta) não repete nota nem evento; o "já assinei" não manda link velho.
        await _ja_assinei(repo, esc, lead)
        await _drenar(executor)
        assert await pool.fetchval("select count(*) from agentesia_eventos where id_lead = $1 and tipo = 'contrato_cancelado'", lead) == 1
        assert mensagens[-1].startswith("Conferi aqui e esse contrato não está mais disponível") and "http" not in mensagens[-1]
        # Exclusão em outro lead: mesma coisa com a causa 'excluido'.
        esc2, lead2, _ = await _montar(pool)
        await _pedir_contrato(repo, esc2, lead2, FATOS)
        await _drenar(executor)
        token2 = await pool.fetchval("select id_documento_externo from agentesia_contratos where id_lead = $1", lead2)
        zapsign.docs[token2]["deleted"] = True
        await servico.receber_webhook(pool, str(esc2), {"event_type": "doc_deleted", "token": token2})
        await _drenar(executor)
        assert await pool.fetchval("select causa_erro from agentesia_contratos where id_lead = $1", lead2) == "excluido"
    finally:
        # Não deixa ações vencidas para os outros testes (a fila é do banco inteiro).
        await pool.execute("update agentesia_acoes set situacao = 'cancelada' where situacao in ('pendente', 'executando')")
        await repo.fechar()


@precisa_pg
async def test_lembrete_contextual_consulta_periodica_e_sem_credito():
    from app.banco.postgres import RepositorioPostgres

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        esc, lead, _ = await _montar(pool)
        zapsign, mensagens, notas = ZapSignFalsa(), [], []
        executor = _executor(pool, zapsign, mensagens, notas)
        await _pedir_contrato(repo, esc, lead, FATOS)
        await _drenar(executor)
        # 9) Abriu há 10 min: o lembrete não sai agora (adiado 1 h, uma vez).
        zapsign.lead(1).update(status="link-opened", times_viewed=1,
                               last_view_at=(datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat())
        await pool.execute("update agentesia_acoes set proxima_em = now() where id_lead = $1 and tipo = 'lembrar_assinatura'", lead)
        antes = len(mensagens)
        await _drenar(executor)
        assert len(mensagens) == antes
        assert await pool.fetchval("select count(*) from agentesia_acoes where id_lead = $1 and tipo = 'lembrar_assinatura' and situacao = 'pendente'", lead) == 1
        # Abriu há 2 h: o lembrete adiado sai com o texto de "travou?".
        zapsign.lead(1)["last_view_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        await pool.execute("update agentesia_acoes set proxima_em = now() where id_lead = $1 and tipo = 'lembrar_assinatura' and situacao = 'pendente'", lead)
        await _drenar(executor)
        assert mensagens[-1].startswith("Oi! Vi que você chegou a abrir o contrato")

        # 7) Consulta periódica: o webhook não veio, a consulta pega a assinatura.
        await pool.execute("update agentesia_contratos set gerado_em = now() - interval '1 hour' where id_lead = $1", lead)
        zapsign.assinar(1)
        assert await executor.agendar_consultas() >= 1
        assert await executor.agendar_consultas() == 0                     # uma por janela
        await _drenar(executor)
        assert await pool.fetchval("select situacao from agentesia_contratos where id_lead = $1", lead) == "assinado"
        assert any(m.startswith("✅ Assinatura confirmada!") for m in mensagens)

        # 10) Sem crédito: não cria documento, o lead ouve "a equipe envia" e a equipe recebe nota e evento.
        esc2, lead2, _ = await _montar(pool)
        zapsign.plano = {"name": "API", "number_of_credits": "0", "status": "paid"}
        criados = len(zapsign.criados)
        await _pedir_contrato(repo, esc2, lead2, FATOS)
        await _drenar(executor)
        assert len(zapsign.criados) == criados
        assert await pool.fetchval("select count(*) from agentesia_eventos where id_lead = $1 and tipo = 'contrato_sem_credito'", lead2) == 1
        assert any("sem créditos" in n for n in notas)
        assert await pool.fetchval("select situacao from agentesia_contratos where id_lead = $1", lead2) == "erro"
    finally:
        # Não deixa ações vencidas para os outros testes (a fila é do banco inteiro).
        await pool.execute("update agentesia_acoes set situacao = 'cancelada' where situacao in ('pendente', 'executando')")
        await repo.fechar()


@precisa_pg
async def test_assinado_guarda_pdf_e_resumo_com_prompt_do_agente_no_card_e_no_aviso(tmp_path, monkeypatch):
    from app.banco.postgres import RepositorioPostgres

    monkeypatch.setenv("AGENTESIA_MIDIA_ARMAZENAMENTO", "local")
    monkeypatch.setenv("AGENTESIA_PASTA_MIDIA", str(tmp_path))
    monkeypatch.setenv("AGENTESIA_URL_PUBLICA", "https://ia.exemplo.test")
    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        esc, lead, etapas = await _montar(pool, config_agente={"resumo_contrato": {"prompt": "PROMPT DO AGENTE", "no_aviso": True}})
        await pool.execute(
            """insert into agentesia_notificacoes (id_escritorio, tipo_evento, nome, modelo_mensagem, destinatarios)
               values ($1, 'contrato_assinado', 'Assinado', 'Contrato assinado: {{nome}}', $2::jsonb)""",
            esc, json.dumps([{"rotulo": "Dra. Ana", "numero": "5531999990000"}]))
        await pool.execute("insert into agentesia_crm_cards (id_escritorio, id_lead, id_card_helena, situacao) values ($1, $2, $3, 'ok')",
                           esc, lead, "card-" + uuid.uuid4().hex[:6])
        await pool.execute("insert into agentesia_mensagens (id_escritorio, id_lead, autor, texto, enviada_em) values ($1, $2, 'lead', 'caí de moto em 2023', now())", esc, lead)
        modelo = ModeloFalso({"contrato_resumo": {"resumo": "📄 Resumo do caso: queda de moto em 2023, sequela no joelho."}})
        zapsign, mensagens, notas, cards = ZapSignFalsa(), [], [], []
        executor = _executor(pool, zapsign, mensagens, notas, cards, modelo)
        await _pedir_contrato(repo, esc, lead, FATOS)
        await _drenar(executor)
        token = await pool.fetchval("select id_documento_externo from agentesia_contratos where id_lead = $1", lead)
        zapsign.assinar(1)
        corpo = {"event_type": "doc_signed", "token": token, "signer_who_signed": {"token": f"lead-{zapsign.p}-1"}}
        assert await servico.receber_webhook(pool, str(esc), corpo) == "processado"
        await _drenar(executor, 12)
        contrato = await pool.fetchrow("select * from agentesia_contratos where id_lead = $1", lead)
        # 6) PDF no armazenamento (local aqui), link permanente no contrato.
        assert contrato["arquivo_assinado"].startswith(f"https://ia.exemplo.test/midia/contratos/{esc}/{contrato['id']}-")
        assert zapsign.baixados == 1 and list(tmp_path.rglob("*.pdf"))[0].read_bytes().startswith(b"%PDF")
        # Resumo: prompt do agente, uma vez, no banco, na nota, no card e no aviso à equipe.
        assert [p["sistema"] for p in modelo.pedidos] == ["PROMPT DO AGENTE"]
        assert "sequela no joelho" in contrato["resumo"]
        assert any(n.startswith("📄 RESUMO DO CONTRATO ASSINADO") for n in notas)
        assert any("sequela no joelho" in (c.get("description") or "") for c in cards)
        aviso = await pool.fetchval("select dados->>'texto' from agentesia_acoes where id_lead = $1 and tipo = 'notificar'", lead)
        assert aviso.startswith("Contrato assinado: Maria") and "sequela no joelho" in aviso
        assert await pool.fetchval("select count(*) from agentesia_chamadas_ia where id_escritorio = $1 and papel = 'contrato_resumo'", esc) == 1
        # Aviso repetido: nada de novo (nem resumo, nem PDF).
        await servico.receber_webhook(pool, str(esc), {**corpo, "signer_who_signed": {"token": "adv-1"}})
        await _drenar(executor)
        assert len(modelo.pedidos) == 1 and zapsign.baixados == 1
        assert (await pool.fetchrow("select id_etapa from agentesia_leads where id = $1", lead))["id_etapa"] == etapas["contrato_assinado"]
    finally:
        # Não deixa ações vencidas para os outros testes (a fila é do banco inteiro).
        await pool.execute("update agentesia_acoes set situacao = 'cancelada' where situacao in ('pendente', 'executando')")
        await repo.fechar()


@precisa_pg
async def test_falha_da_ia_no_resumo_nao_segura_a_assinatura():
    from app.banco.postgres import RepositorioPostgres

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        esc, lead, _ = await _montar(pool, config_zapsign={"resumo": {"no_aviso": True}, "guardar_pdf": False})
        await pool.execute(
            """insert into agentesia_notificacoes (id_escritorio, tipo_evento, nome, modelo_mensagem, destinatarios)
               values ($1, 'contrato_assinado', 'Assinado', 'Contrato assinado: {{nome}}', $2::jsonb)""",
            esc, json.dumps([{"rotulo": "Dra. Ana", "numero": "5531999990000"}]))
        await pool.execute("insert into agentesia_mensagens (id_escritorio, id_lead, autor, texto, enviada_em) values ($1, $2, 'lead', 'oi', now())", esc, lead)
        modelo = ModeloFalso({})                       # sem resposta: a IA do resumo "cai"
        zapsign, mensagens, notas = ZapSignFalsa(), [], []
        executor = _executor(pool, zapsign, mensagens, notas, modelo=modelo)
        await _pedir_contrato(repo, esc, lead, FATOS)
        await _drenar(executor)
        token = await pool.fetchval("select id_documento_externo from agentesia_contratos where id_lead = $1", lead)
        zapsign.assinar(1)
        await servico.receber_webhook(pool, str(esc), {"event_type": "doc_signed", "token": token})
        for _ in range(4):
            await _drenar(executor)
            await pool.execute("update agentesia_acoes set proxima_em = now() where id_lead = $1 and tipo = 'resumir_contrato' and situacao = 'pendente'", lead)
        assert await pool.fetchval("select situacao from agentesia_contratos where id_lead = $1", lead) == "assinado"
        assert any(m.startswith("✅ Assinatura confirmada!") for m in mensagens)
        assert await pool.fetchval("select resultado->>'resumo' from agentesia_acoes where id_lead = $1 and tipo = 'resumir_contrato'", lead) == "falhou"
        assert await pool.fetchval("select count(*) from agentesia_eventos where id_lead = $1 and tipo = 'resumo_contrato_falhou'", lead) == 1
        aviso = await pool.fetchval("select dados->>'texto' from agentesia_acoes where id_lead = $1 and tipo = 'notificar'", lead)
        assert aviso == "Contrato assinado: Maria"       # o aviso saiu mesmo sem resumo
    finally:
        # Não deixa ações vencidas para os outros testes (a fila é do banco inteiro).
        await pool.execute("update agentesia_acoes set situacao = 'cancelada' where situacao in ('pendente', 'executando')")
        await repo.fechar()
