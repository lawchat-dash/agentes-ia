"""Cobrança de IA sem furos (auditoria B2-B7): tabela de preços travada, transcrição com áudio e texto separados e sem
estimar vídeo por bytes, chamadas pagas que falham também gravadas (follow-up, origem do anúncio, resumo de documento,
PDF lido vazio, indexação em lotes, memória da conversa), nomes por função e testes do painel (laboratório do agente
salvo e prévia do follow-up) gravando com origem própria e bloqueando sem saldo.

Sem IA de verdade: ModeloFalso e clientes falsos. Os testes do painel rodam com AGENTESIA_TESTE_PG_URL."""

import os
import uuid
import struct
from types import SimpleNamespace

import pytest

from app import cobranca, modelo as mod
from app.modelo import Chamada, ErroModelo, ModeloFalso
from tests.test_gestao import ambiente  # noqa: F401  (fixture do painel com a Helena simulada)

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
com_banco = pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")


class ModeloQueFalha:
    """Gasta duas tentativas (saída inválida) e falha: as chamadas pagas vão no erro, como no ModeloOpenAI."""

    def __init__(self, custo: float = 0.004) -> None:
        self.custo = custo

    async def gerar(self, *, papel, **_kw):
        erro = ErroModelo("saida_invalida", "não é JSON")
        erro.chamadas = [Chamada(papel=papel, modelo="gpt-4.1-mini", tokens_entrada=100, tokens_saida=50,
                                 custo_usd=self.custo, sucesso=False, erro="saida_invalida") for _ in range(2)]
        raise erro


# ============================================================================ tabela de preços
def test_tabela_de_precos_travada():
    """Conferida em developers.openai.com/api/docs/pricing e na página de cada modelo de transcrição (26/11/2026).
    Mudou o preço? Confira na página oficial e atualize aqui junto com app/modelo.py."""
    assert mod.PRECOS_USD_POR_MILHAO == {
        "claude-fable-5-2": (8.00, 40.00, 0.20),
        "claude-opus-5-5": (4.00, 20.00, 0.20),
        "claude-sonnet-5-5": (2.00, 10.00, 0.10),
        "claude-haiku-5-5": (0.10, 0.50, 0.01),
        "gpt-4.1": (2.00, 8.00, 0.50),
        "gpt-4.1-mini": (0.40, 1.60, 0.10),
        "gpt-4.1-nano": (0.10, 0.40, 0.025),
        "gpt-4o": (2.50, 10.00, 1.25),
        "gpt-4o-mini": (0.15, 0.60, 0.075),
        "gpt-6-luna": (0.10, 0.50, 0.01),
        "gpt-6.1-sol": (2.00, 10.00, 0.10),
        "gpt-6.2-sol": (2.00, 10.00, 0.10),
        "gpt-6-astra": (10.00, 50.00, 1.00),
        "gpt-6.2-astra": (8.00, 40.00, 0.40),
        "gpt-4o-mini-transcribe": (1.25, 5.00, 0.0),
        "gpt-4o-transcribe": (2.50, 10.00, 0.0),
        "text-embedding-3-small": (0.02, 0.0, 0.0),
        "text-embedding-3-large": (0.13, 0.0, 0.0),
    }
    assert mod.PRECO_AUDIO_USD_POR_MILHAO == {"gpt-4o-mini-transcribe": 1.25, "gpt-4o-transcribe": 2.50}
    assert mod.USD_POR_MINUTO_TRANSCRICAO == {"gpt-4o-mini-transcribe": 0.003, "gpt-4o-transcribe": 0.006}
    assert mod.FATOR_CACHE_ESCRITA == 1.25


def test_nomes_por_funcao_batem_com_os_papeis_gravados():
    from app.cobranca.rotas import NOMES_PAPEL
    assert "busca_conhecimento" not in NOMES_PAPEL
    for papel in ("conhecimento_consulta", "followup_decisor", "resumo_documento", "followup", "resumo_conversa",
                  "origem_produto", "transcrever_audio", "ler_pdf", "conhecimento"):
        assert NOMES_PAPEL[papel] and NOMES_PAPEL[papel] != papel
    assert all("Helena" not in nome for nome in NOMES_PAPEL.values())


# ============================================================================ transcrição (B3, B4)
def _visao():
    from app.midia.openai_visao import VisaoOpenAI
    visao = VisaoOpenAI.__new__(VisaoOpenAI)
    visao.modelo, visao.modelo_audio = "gpt-4.1-mini", "gpt-4o-mini-transcribe"
    return visao


class _Transcricoes:
    def __init__(self, uso):
        self.uso = uso

    async def create(self, **_kw):
        return SimpleNamespace(text="oi, sofri um acidente", usage=self.uso)


async def _transcrever(uso, dados=b"OggS" + b"\0" * 100, nome="audio.ogg"):
    visao = _visao()
    visao._cliente = SimpleNamespace(audio=SimpleNamespace(transcriptions=_Transcricoes(uso)))
    return await visao.transcrever_audio(dados, nome)


async def test_transcricao_cobra_audio_texto_e_saida_cada_um_pelo_seu_preco(monkeypatch):
    uso = SimpleNamespace(type="tokens", input_tokens=1200, output_tokens=300,
                          input_token_details=SimpleNamespace(audio_tokens=1000, text_tokens=200))
    texto, chamada = await _transcrever(uso)
    assert texto == "oi, sofri um acidente" and chamada.tokens_entrada == 1200 and chamada.tokens_saida == 300
    assert chamada.custo_usd == round((1000 * 1.25 + 200 * 1.25 + 300 * 5.00) / 1e6, 6)
    # Preço do áudio diferente do texto: cada parte pelo seu (é só mudar a tabela, numa Chamada só).
    monkeypatch.setitem(mod.PRECO_AUDIO_USD_POR_MILHAO, "gpt-4o-mini-transcribe", 3.00)
    _, chamada = await _transcrever(uso)
    assert chamada.custo_usd == round((1000 * 3.00 + 200 * 1.25 + 300 * 5.00) / 1e6, 6)
    # Sem o detalhe, a entrada inteira conta como áudio (nunca abaixo do preço).
    _, chamada = await _transcrever(SimpleNamespace(input_tokens=1200, output_tokens=300))
    assert chamada.custo_usd == round((1200 * 3.00 + 300 * 5.00) / 1e6, 6)


def _ogg_opus(segundos: float) -> bytes:
    primeira = b"OggS" + b"\0" * 22 + b"OpusHead" + b"\0" * 20
    ultima = b"OggS\x00\x04" + struct.pack("<q", int(segundos * 48000)) + b"\0" * 30
    return primeira + b"\x01" * 50_000 + ultima


def _mp4(segundos: float, escala: int = 1000) -> bytes:
    mvhd = b"mvhd" + b"\0" + b"\0" * 3 + b"\0" * 8 + struct.pack(">II", escala, int(segundos * escala))
    return b"\0\0\0\x18ftypisom" + b"\0" * 12 + b"\0\0\0\x6c" + mvhd + b"\0" * 900_000


def test_duracao_lida_do_arquivo():
    from app.midia.openai_visao import duracao_em_segundos
    assert duracao_em_segundos(_ogg_opus(42)) == pytest.approx(42)
    assert duracao_em_segundos(_mp4(90)) == pytest.approx(90)
    assert duracao_em_segundos(b"\x1aE\xdf\xa3" + b"\0" * 100) is None


async def test_transcricao_sem_tokens_usa_segundos_ou_duracao_e_nunca_bytes_no_video():
    _, chamada = await _transcrever(SimpleNamespace(type="duration", seconds=120))
    assert chamada.custo_usd == pytest.approx(0.006)                         # 2 min x US$ 0,003
    _, chamada = await _transcrever(None, dados=_ogg_opus(60))
    assert chamada.custo_usd == pytest.approx(0.003)                         # duração real, não os 50 KB
    _, chamada = await _transcrever(None, dados=_mp4(30), nome="video.mp4")
    assert chamada.custo_usd == pytest.approx(0.0015)                        # vídeo de 900 KB: pela duração
    _, chamada = await _transcrever(None, dados=b"\x1aE\xdf\xa3" + b"\0" * 5_000_000, nome="video.webm")
    assert chamada.custo_usd == 0.0                                          # vídeo sem duração: não chuta por bytes
    _, chamada = await _transcrever(None, dados=b"ID3" + b"\0" * 240_000, nome="audio.mp3")
    assert chamada.custo_usd > 0                                             # áudio sem duração: estimativa por bytes


# ============================================================================ mídia (B5)
class _Http:
    """Download falso: devolve os bytes dados."""

    def __init__(self, dados: bytes) -> None:
        self.dados = dados

    def stream(self, *_a, **_kw):
        dados = self.dados

        class _Resposta:
            status_code = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return False

            def raise_for_status(self):
                pass

            async def aiter_bytes(self):
                yield dados

        return _Resposta()


async def test_resumo_de_documento_que_falha_devolve_as_chamadas_pagas(monkeypatch):
    from app import midia
    monkeypatch.setattr(midia, "extrair_texto", lambda _d, _f: "laudo " * 1000)
    monkeypatch.setattr(midia, "detectar_formato", lambda *_a: "texto")
    resultado = await midia.tratar_midia(tipo="documento", url="https://exemplo.com/laudo.txt", mime="text/plain",
                                         nome="laudo.txt", legenda=None, transcricao_helena=None, http=_Http(b"x"),
                                         modelo=ModeloQueFalha())
    assert resultado.erro == "saida_invalida" and "Começo do conteúdo" in resultado.texto
    assert [c.papel for c in resultado.chamadas] == ["resumo_documento", "resumo_documento"]


async def test_pdf_escaneado_lido_vazio_devolve_a_chamada_paga(monkeypatch):
    from app import midia
    from app.midia.extrair import ErroArquivo

    def sem_texto(_d, _f):
        raise ErroArquivo("sem_texto")
    monkeypatch.setattr(midia, "extrair_texto", sem_texto)
    monkeypatch.setattr(midia, "detectar_formato", lambda *_a: "pdf")
    paga = Chamada(papel="ler_pdf", modelo="gpt-4.1-mini", tokens_entrada=3000, custo_usd=0.002)

    async def ler_pdf(_dados):
        return "   ", paga
    resultado = await midia.tratar_midia(tipo="documento", url="https://exemplo.com/a.pdf", mime="application/pdf",
                                         nome="a.pdf", legenda=None, transcricao_helena=None, http=_Http(b"%PDF"),
                                         modelo=ModeloFalso({}), ler_pdf=ler_pdf)
    assert resultado.erro == "sem_texto" and resultado.chamadas == [paga]


# ============================================================================ follow-up e origem (B5)
def _disparador(modelo, gravadas, monkeypatch):
    from app.cerebro import contexto
    from app.followup import agente as agente_fu
    from app.followup.servico import Disparador
    monkeypatch.setattr(agente_fu, "sistema_do_decisor", lambda *_a, **_k: "sistema")
    monkeypatch.setattr(agente_fu, "sistema_do_agente_do_lead", lambda *_a, **_k: "sistema")
    monkeypatch.setattr(contexto, "linha_de_hoje", lambda: "hoje")
    d = Disparador.__new__(Disparador)
    d._modelo, d._modelo_padrao = modelo, "gpt-4.1-mini"

    async def gravar(_lead, chamadas):
        gravadas.extend(chamadas)
    d._gravar_chamadas = gravar
    return d


async def test_followup_decisor_e_agente_que_falham_gravam_as_chamadas(monkeypatch):
    from app.followup import regras
    gravadas: list = []
    d = _disparador(ModeloQueFalha(), gravadas, monkeypatch)
    config = regras.Config.de(regras.validar({"passos": [{"apos_horas": 1, "modo": "ia"}]}))
    lead = {"id": "l", "id_escritorio": "e", "nome": "Maria", "config_agente": {}, "etapa": "sdr"}
    decisao = await d._decidir({"passo": 0}, lead, config, 1, [])
    assert decisao is not None and [c.papel for c in gravadas] == ["followup_decisor"] * 2
    gravadas.clear()
    textos = await d._textos({"passo": 0, "id_lead": "l"}, lead, config, config.passos[0], 1, historico=[], sem_ia=False)
    assert textos and [c.papel for c in gravadas] == ["followup"] * 2                # texto de reserva, gasto gravado


async def test_origem_do_anuncio_que_falha_grava_as_chamadas():
    from app.acoes import Executor
    from app.canal.helena_conta import ErroHelenaApi
    gravadas: list = []
    ex = Executor.__new__(Executor)
    ex._modelo = ModeloQueFalha()

    async def lead_completo(_id):
        return {"id": "l", "origem": {}}

    async def gravar(_ctx, chamadas):
        gravadas.extend(chamadas)
    ex._lead_completo, ex._gravar_chamadas = lead_completo, gravar
    with pytest.raises(ErroHelenaApi):
        await ex._classificar_origem({"id_escritorio": "e", "lead": {"id": "l"}}, {})
    assert [c.papel for c in gravadas] == ["origem_produto"] * 2


# ============================================================================ indexação em lotes (B6)
async def test_vetorizacao_em_lotes_que_falha_no_meio_leva_o_que_ja_foi_pago():
    from app import vetores

    class Embeddings:
        def __init__(self):
            self.vez = 0

        async def create(self, *, model, input):
            self.vez += 1
            if self.vez == 2:
                raise RuntimeError("caiu no segundo lote")
            return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1]) for _ in input],
                                   usage=SimpleNamespace(total_tokens=5000))

    v = vetores.VetorizadorOpenAI(cliente=SimpleNamespace(embeddings=Embeddings()))
    with pytest.raises(vetores.ErroVetorizacao) as erro:
        await v.vetorizar(["trecho"] * 150)
    assert erro.value.tokens == 5000 and erro.value.custo_usd == pytest.approx(5000 * 0.02 / 1e6)
    # Falha no primeiro lote: nada foi pago, o erro original sobe.
    primeiro = Embeddings()
    primeiro.vez = 1
    with pytest.raises(RuntimeError):
        await vetores.VetorizadorOpenAI(cliente=SimpleNamespace(embeddings=primeiro)).vetorizar(["trecho"])


async def test_indexacao_grava_lotes_pagos_mesmo_com_erro(monkeypatch):
    from app import conhecimento_indice as ci
    from app import vetores
    gravadas: list = []

    async def gravar(_conexao, **kw):
        gravadas.extend(kw["chamadas"])
    monkeypatch.setattr(cobranca, "gravar_chamadas", gravar)
    doc = {"id": "d", "id_escritorio": "e", "id_agente": "a"}
    await ci._gravar_indexacao(None, doc, "text-embedding-3-small", 5000, 0.0001, erro="caiu")
    await ci._gravar_indexacao(None, doc, "text-embedding-3-small", 0, 0.0)            # nada pago: não grava
    assert len(gravadas) == 1 and gravadas[0].papel == "conhecimento" and not gravadas[0].sucesso
    assert isinstance(vetores.ErroVetorizacao("x", 1, 0.1), Exception)


# ============================================================================ memória da conversa (B7)
async def test_resumo_da_conversa_grava_as_chamadas_antes_da_ficha():
    from app import memoria
    ordem: list[str] = []

    class Repo:
        async def trecho_para_resumir(self, *_a, **_k):
            return {"resumo": None, "mensagens": [{"id": 1, "autor": "lead", "texto": "caí da moto"}]}

        async def gravar_resumo(self, **_k):
            ordem.append("ficha")
            raise ConnectionError("banco caiu")

    async def gravar(chamadas):
        ordem.append(f"chamadas:{len(chamadas)}")
    modelo = ModeloFalso({memoria.PAPEL: {"resumo": "- Caso: acidente de moto."}})
    with pytest.raises(ConnectionError):
        await memoria.resumir(Repo(), modelo, "lead-1", gravar_chamadas=gravar)
    assert ordem == ["chamadas:1", "ficha"]                                  # o gasto ficou gravado antes da falha


# ============================================================================ testes do painel (B2)
async def test_gravar_teste_ignora_modelo_falso_e_aceita_dict(monkeypatch):
    gravadas: list = []

    async def gravar(_conexao, **kw):
        gravadas.append(kw)
    monkeypatch.setattr(cobranca, "gravar_chamadas", gravar)
    await cobranca.gravar_teste(None, id_escritorio="e", chamadas=[Chamada(papel="etapa", modelo="falso")])
    assert gravadas == []
    await cobranca.gravar_teste(None, id_escritorio="e", origem="previa",
                                chamadas=[{"papel": "followup", "modelo": "gpt-4.1-mini", "custo_usd": 0.01}])
    assert gravadas[0]["origem"] == "previa" and gravadas[0]["chamadas"][0].papel == "followup"


@com_banco
async def test_laboratorio_do_agente_salvo_e_previa_gravam_e_bloqueiam_sem_saldo(ambiente):
    from app.gestao.laboratorio import Laboratorios
    from tests.test_gestao import _entrar
    from tests.test_lixeira_solta_numero import _escritorio, _payload, _produto
    from tests.test_rascunho_versoes import ModeloPago, _app, _modelo

    cliente, _simulada, email_admin, banco = ambiente
    app = _app(cliente)
    pool = banco._pool
    await _entrar(cliente, email_admin, "senha-admin-123")
    esc, h, zapi, _oficial = await _escritorio(cliente, pool, "Lab Salvo Pago", "token-bom-" + uuid.uuid4().hex[:8])
    id_produto, agentes = await _produto(cliente, h, "Salvo")
    ativado = await cliente.post(f"/api/produtos-ativados/{id_produto}/ativar", headers=h, json=_payload(agentes, zapi))
    assert ativado.status_code == 200, ativado.text
    id_agente = str(await pool.fetchval("select id from agentesia_agentes where id_escritorio = $1::uuid limit 1", esc))
    falso = _modelo()
    falso._respostas["followup"] = {"mensagens": ["Oi, Maria! Conseguiu ver?"]}
    app.state.laboratorios = Laboratorios(ModeloPago(falso), app.state.cfg)
    await pool.execute("insert into agentesia_carteiras (id_escritorio, modo) values ($1::uuid, 'pre_pago')", esc)
    cobranca.esquecer()
    previa = {"passo": 0, "config": {"passos": [{"apos_horas": 1, "modo": "ia"}]}}
    try:
        sem = await cliente.post(f"/api/agentes/{id_agente}/laboratorio", headers=h, json={"texto": "oi"})
        assert sem.status_code == 402 and "saldo" in sem.json()["detail"].lower()
        sem = await cliente.post(f"/api/agentes/{id_agente}/followup/previa", headers=h, json=previa)
        assert sem.status_code == 402
        assert not await pool.fetchval("select count(*) from agentesia_chamadas_ia where id_escritorio = $1::uuid", esc)

        await cobranca.lancar(pool, esc, "recarga", 50, motivo="teste do laboratório salvo")
        r = await cliente.post(f"/api/agentes/{id_agente}/laboratorio", headers=h, json={"texto": "oi, caí da moto"})
        assert r.status_code == 200, r.text
        p = await cliente.post(f"/api/agentes/{id_agente}/followup/previa", headers=h, json=previa)
        assert p.status_code == 200 and p.json()["mensagens"] == ["Oi, Maria! Conseguiu ver?"]
        linhas = await pool.fetch("""select origem, papel, cobranca, custo_brl::float8 as brl from agentesia_chamadas_ia
                                     where id_escritorio = $1::uuid""", esc)
        origens = {(l["origem"], l["papel"]) for l in linhas}
        assert ("previa", "followup") in origens and any(o == "laboratorio" for o, _ in origens)
        assert all(l["cobranca"] == "pendente" and l["brl"] > 0 for l in linhas)
        assert not await pool.fetchval("select count(*) from agentesia_leads where id_escritorio = $1::uuid", esc)
    finally:
        cobranca.esquecer()

