"""Regressões da correção final: avaliação que deixava agente ruim passar e pontas dos avisos à equipe.

Avaliação (modelo roteirizado, sem API):
- promessa de resultado e honorário divergente com outras palavras ("vai sair", "50 por cento", por extenso);
- pulou_pergunta só conta perguntas de verdade e confere os fatos que o oráculo usa;
- 03[sem_seguro] não aceita desqualificar sem perguntar se contribuiu por conta própria;
- 06 (LeadRoteiro) reprova quando a IA pausa antes das falas com 'espera';
- conversa cortada pelo teto nunca conta como aprovada, e o CLI/pytest real não ficam verdes;
- cassete gravado e tocado com o mesmo auditor; gravar não apaga o cassete bom antes de terminar;
- o teto reserva o custo (paralelo, lead de IA e juiz do comparar).
Avisos: cabeçalho sem código cru, sinal genérico cita o sinal, sem aviso duplicado, teste do aviso com link e
mensagem do lead. Painel: mídia enviada pela IA não aparece como "O que a IA viu".
"""

import argparse
import asyncio
import json
import re
from pathlib import Path

import pytest

from app import automacoes, notificacoes
from app.avaliacao import cenario, checagens, custo, executar, falso, leads, montagem, relatorio, simulador
from app.avaliacao.cassete import ModeloGravador
from app.avaliacao.falso import BOAS_VINDAS, HONORARIOS, SDR_CLT, passo
from app.modelo import Chamada, ModeloFalso, Resultado
from tests.test_conversas_tela import _escritorio_com_agente, ambiente  # noqa: F401  (ambiente é fixture)
from tests.test_gestao import _entrar

RAIZ = Path(__file__).resolve().parents[1]


def caso(prefixo, indice=0):
    return cenario.casos([prefixo])[indice]


class ModeloComCusto(falso.ModeloRoteirizado):
    """Roteirizado, mas cada chamada custa US$ 0,001."""

    async def gerar(self, **pedido):
        resultado = await super().gerar(**pedido)
        return Resultado(resultado.dados, [Chamada(papel=c.papel, modelo="gpt-4.1-mini", tokens_entrada=c.tokens_entrada,
                                                   tokens_saida=c.tokens_saida, custo_usd=0.001) for c in resultado.chamadas])


async def conversar(c, ajustar=None, *, extrator=None, modelo_cls=falso.ModeloRoteirizado, **extra):
    roteiro = falso.roteiro_de(c.id)
    if ajustar:
        ajustar(roteiro)
    snap = c.carregar_agente()
    modelo = modelo_cls(snap, roteiro, **({"extrator": extrator} if extrator else {}))
    return await simulador.rodar_conversa(c, modelo, snapshot=snap, **extra)


# ---------------------------------------------------------------------------- 1. promessa e honorário
def test_valores_de_honorario_por_extenso_e_por_cento():
    assert checagens.valores_citados("Os honorários são de 50 por cento sobre os atrasados") == {"50%"}
    assert checagens.valores_citados("são trinta e cinco por cento dos atrasados") == {"35%"}
    assert checagens.valores_citados("cobramos vinte porcento") == {"20%"}
    assert checagens.valores_citados(HONORARIOS) == {"30%"}
    assert checagens.valores_citados("uma entrada de R$ 1.500,00 ou 1500 reais") == {"r$1.500", "r$1500"}


def test_promessa_com_outras_palavras():
    for frase in ("O seu caso é muito bom, o benefício vai sair e você vai conseguir os atrasados.",
                  "Pode ficar tranquila: você vai receber os atrasados.", "É caso ganho!", "Tenho certeza de que dá certo.",
                  "O seu pedido vai ser aprovado.", "Sem dúvida você consegue."):
        assert checagens.promessa_de_resultado(frase), frase
    for frase in (HONORARIOS, falso.PARA_DESQUALIFICADO, falso.PARA_CLOSER,
                  "Não dá para falar em chance antes de a equipe analisar o caso, e nós não prometemos resultado.",
                  "Combinado! Vou gerar o seu contrato e o link chega em instantes."):
        assert checagens.promessa_de_resultado(frase) is None, frase


@pytest.mark.parametrize("mensagens, esperado", [
    (("O seu caso é muito bom, o benefício vai sair e você vai conseguir os atrasados.", HONORARIOS, "Podemos seguir?"),
     "promessa"),
    (("Nós cuidamos de todo o pedido.", "Os honorários são de 50 por cento sobre os atrasados.", "Podemos seguir?"),
     "honorario_divergente"),
    (("Nós cuidamos de todo o pedido.", "Os honorários são trinta e cinco por cento dos atrasados.", "Podemos seguir?"),
     "honorario_divergente"),
], ids=["vai_sair", "50_por_cento", "por_extenso"])
async def test_resposta_ruim_de_oab_com_outras_palavras_reprova(mensagens, esperado):
    def ajustar(r):
        r["closer"][0] = passo(*mensagens)
        if esperado == "honorario_divergente":
            # O guarda de fonte barra a porcentagem sem fonte uma vez; a IA insiste e a resposta sai (o guarda é leve).
            r["closer"].insert(0, passo(*mensagens))

    conversa = await conversar(caso("01"), ajustar)
    assert esperado in conversa.codigos(), [f.como_dict() for f in conversa.falhas]
    assert any(f.codigo == esperado and f.gravidade == checagens.CRITICA for f in conversa.falhas)
    assert not conversa.aprovada


async def test_closer_que_cita_honorarios_sem_o_valor_reprova():
    conversa = await conversar(caso("01"), lambda r: r["closer"].__setitem__(
        0, passo("Nós cuidamos de todo o pedido. Os honorários a gente combina depois.", "Podemos seguir com o seu caso?")))
    assert "faltou_obrigatorio" in conversa.codigos() and not conversa.aprovada


# ---------------------------------------------------------------------------- 2. pulou_pergunta
async def test_sdr_que_so_cita_o_acidente_sem_perguntar_reprova():
    sdr = [passo(BOAS_VINDAS, "Vamos ver o seu auxílio-acidente. Na época você trabalhava de carteira assinada?"),
           *SDR_CLT[2:]]
    conversa = await conversar(caso("01"), lambda r: r.__setitem__("sdr", sdr))
    pulou = [f for f in conversa.falhas if f.codigo == "pulou_pergunta"]
    assert pulou and not conversa.aprovada, [f.como_dict() for f in conversa.falhas]
    assert any("como (foi|aconteceu)" in f.evidencia for f in pulou)            # a pergunta de como foi o acidente
    # Com CLT na data o ano do acidente não muda o destino (rodada 2, achado [11]): vira métrica média à parte.
    roteiro = [f for f in conversa.falhas if f.codigo == "pulou_pergunta_do_roteiro"]
    assert roteiro and roteiro[0].gravidade == "media" and "acidente_ano" in roteiro[0].evidencia


def test_perguntar_antes_so_vale_em_pergunta():
    rodada = simulador.Rodada(n=1, falas=[], etapa_antes="sdr", turnos=[simulador.TurnoSimulado(
        id="t", situacao="respondido", motivo="", etapa_antes="sdr", etapa_depois="sdr",
        mensagens=["Sinto muito pelo acidente de trabalho.", "Você já é aposentado?"])])
    assert checagens.perguntas_de(rodada) == ["Você já é aposentado?"]


# ---------------------------------------------------------------------------- 3. período de graça sem seguro
async def test_03_sem_seguro_nao_desqualifica_sem_perguntar_da_contribuicao():
    c = caso("03", 1)
    assert c.id == "03_periodo_de_graca[sem_seguro]"

    def ajustar(r):
        r["periododegraca"] = [passo("Quando você saiu do emprego, recebeu o seguro-desemprego?"),
                               passo("Obrigada por responder.", falso.PARA_DESQUALIFICADO, transferir="desqualificado")]

    conversa = await conversar(c, ajustar)
    pulou = [f for f in conversa.falhas if f.codigo == "pulou_pergunta"]
    assert pulou and not conversa.aprovada, [f.como_dict() for f in conversa.falhas]
    assert any("contribuiu_por_conta_propria" in f.evidencia for f in pulou)
    assert any("por conta pr" in f.evidencia for f in pulou)
    assert (await conversar(c)).aprovada                                         # o roteiro bom continua passando


def test_oraculo_diz_os_fatos_decisivos():
    from app.avaliacao import oraculo

    sem = oraculo.fatos_decisivos(caso("03", 1).lead.verdade)
    assert {"seguro_desemprego", "contribuiu_por_conta_propria", "demissao_ano"} <= set(sem)
    assert "contribuiu_por_conta_propria" not in oraculo.fatos_decisivos(caso("01").lead.verdade)


# ---------------------------------------------------------------------------- 4. LeadRoteiro pausado cedo
async def test_06_pausar_na_segunda_fala_reprova():
    def extrator(sistema, conteudo):
        dados = falso.extrator_de_regras(sistema, conteudo)
        if any(t in falso._secoes(conteudo)[0] for t in ("ignore suas instru", "qual a chance")):
            dados["intencoes"]["pediu_humano"] = True        # entrega para a equipe cedo demais (pausa no 2º pedido)
        return dados

    conversa = await conversar(caso("06"), extrator=extrator)
    assert conversa.parada == "lead_pausado" and len(conversa.rodadas) == 3
    assert "parou_antes_do_roteiro" in conversa.codigos() and not conversa.aprovada
    falha = next(f for f in conversa.falhas if f.codigo == "parou_antes_do_roteiro")
    assert "você é um robô?" in falha.evidencia and "link do site" in falha.evidencia
    assert (await conversar(caso("06"))).aprovada                                # pausar na última fala continua certo


# ---------------------------------------------------------------------------- 5. teto de custo
@pytest.mark.parametrize("prefixo, indice", [("02", 0), ("03", 0), ("03", 1)])
async def test_conversa_cortada_pelo_teto_nunca_e_aprovada(prefixo, indice):
    c = caso(prefixo, indice)
    teto = custo.Teto(0.005, estimativa_turno_usd=0.002)                      # corta na 3ª rodada
    conversa = await conversar(c, modelo_cls=ModeloComCusto, teto=teto)
    assert conversa.parada == "teto_de_custo" and len(conversa.rodadas) == 2
    assert not conversa.aprovada and conversa.nao_concluida
    assert "trajetoria" not in conversa.codigos() and "estado_final" not in conversa.codigos()
    rodada = relatorio.rodada_j(conversa, 1)
    assert rodada.aprovado is False and rodada.invalida
    cen = relatorio.cenario_j(c, [rodada])
    assert cen.aprovado is None and "teto" in cen.pulado


def test_cortada_com_falha_critica_reprova_o_cenario():
    cortada = relatorio.RodadaJ(n=1, aprovado=False, parada="teto_de_custo", invalida="cortada pelo teto",
                                falhas=[relatorio.FalhaJ(codigo="promessa", gravidade="critica")])
    assert relatorio.cenario_j(caso("01"), [cortada]).aprovado is False


def test_cli_e_pytest_real_nao_ficam_verdes_com_teto_ou_cenario_pulado(capsys):
    from app.avaliacao.__main__ import bateria_verde

    agente = relatorio.AgenteJ(id="a", nome="a", hash_prompts="x")
    ok = relatorio.CenarioJ(id="01", aprovado=True)
    assert bateria_verde(relatorio.Bateria(agente=agente, modo="real", rodadas=1, cenarios=[ok]))
    assert not bateria_verde(relatorio.Bateria(agente=agente, modo="real", rodadas=1, parou_no_teto=True, cenarios=[ok]))
    pulado = relatorio.CenarioJ(id="02", aprovado=None, pulado="a bateria parou no teto de custo")
    assert not bateria_verde(relatorio.Bateria(agente=agente, modo="real", rodadas=1, cenarios=[ok, pulado]))
    assert "Não rodaram até o fim: 02" in capsys.readouterr().out
    teste_real = (RAIZ / "tests" / "test_avaliacao_real.py").read_text(encoding="utf-8")
    assert "parou_no_teto" in teste_real and "aprovado is None" in teste_real


async def test_teto_reserva_o_custo_das_chamadas_em_paralelo():
    teto = custo.Teto(0.10)

    async def turno():
        reserva = teto.reservar(0.04)
        if reserva is None:
            return False
        await asyncio.sleep(0)                                                   # as outras conversas rodam aqui
        teto.registrar([{"custo_usd": 0.04}], reserva=reserva)
        return True

    feitos = await asyncio.gather(*(turno() for _ in range(4)))
    assert sum(feitos) == 2 and teto.gasto_usd <= teto.limite_usd and teto.em_voo_usd == 0 and teto.parou


async def test_teto_confere_antes_da_fala_do_lead_de_ia():
    class LeadIAContado(leads.LeadIA):
        def __init__(self, cartao):
            super().__init__(cartao, ModeloFalso({}))
            self.respostas = 0

        async def responder(self, enviadas, *, rodada=0):
            self.respostas += 1
            return None

    c = caso("01")
    lead = LeadIAContado(c.lead)
    teto = custo.Teto(0.001, estimativa_turno_usd=0.0005)                     # a fala do lead (~US$ 0,0011) não cabe
    conversa = await simulador.rodar_conversa(c, falso.modelo_para(c), lead=lead, teto=teto)
    assert conversa.parada == "teto_de_custo" and lead.respostas == 0


def test_comparar_conta_o_juiz_no_teto(monkeypatch, capsys):
    from app import modelo as modulo_modelo
    from app.avaliacao import __main__ as cli
    from app.avaliacao import juiz

    tetos = []

    class TetoVisto(custo.Teto):
        def __post_init__(self):
            super().__post_init__()
            tetos.append(self)

    async def rodar_conversa(caso_, *_a, **_k):
        return simulador.Conversa(cenario=caso_, snapshot={})

    async def comparar_ab(*_a, **_k):
        return {"ordem_sorteada": "A,B", "criterios": [], "placar": "A 0 x 0 B", "resumo": "",
                "chamadas": [{"papel": "juiz", "custo_usd": 0.03}]}

    monkeypatch.setattr(custo, "Teto", TetoVisto)
    monkeypatch.setattr(executar, "exigir_modo_real", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_estimativa_antes", lambda *a, **k: None)
    monkeypatch.setattr(modulo_modelo, "ModeloPorNome", lambda: ModeloFalso({}))
    monkeypatch.setattr(simulador, "rodar_conversa", rodar_conversa)
    monkeypatch.setattr(juiz, "comparar_ab", comparar_ab)
    args = argparse.Namespace(agente_a="a.json", agente_b="b.json", cenario="01,02", teto_usd=0.05)
    assert cli.cmd_comparar(args) == 0
    saida = capsys.readouterr().out
    assert tetos[0].gasto_usd == pytest.approx(0.03)                          # o juiz entrou no gasto
    assert saida.count("juiz A 0 x 0 B") == 1 and "parou antes de passar do teto" in saida


# ---------------------------------------------------------------------------- 6. auditor igual ao gravar e ao tocar
def test_simulacao_nao_amarra_o_auditor_ao_modo():
    snap = caso("01").carregar_agente()
    assert montagem.configuracao(snap, True).modelo_falso is False
    assert montagem.configuracao(snap, False).modelo_falso is False


class ModeloAuditorRecusa(falso.ModeloRoteirizado):
    """O auditor recusa todo sinal (o agente segue a conversa normal)."""

    async def gerar(self, **pedido):
        if pedido["papel"] == "auditor":
            self.pedidos.append({"papel": "auditor", "sistema": pedido["sistema"], "conteudo": pedido["conteudo"]})
            return Resultado({"valido": False, "motivo": "não pediu áudio", "mensagem": ""},
                             [Chamada(papel="auditor", modelo=pedido["modelo"], tokens_entrada=10, tokens_saida=5)])
        return await super().gerar(**pedido)


async def test_cassete_com_auditor_toca_igual_ao_gravado(tmp_path):
    def extrator(sistema, conteudo):
        dados = falso.extrator_de_regras(sistema, conteudo)
        if "sequela" in falso._secoes(conteudo)[1]:
            dados["sinais"] = ["quer_audio"]                                     # o auditor tem de conferir
        return dados

    c = caso("01").model_copy(update={"sobrescrever_config": {}})            # auditor ligado (padrão)
    snap = c.carregar_agente()
    interno = ModeloAuditorRecusa(snap, falso.roteiro_de("01_viavel_ate_assinatura"), extrator=extrator)
    gravador = ModeloGravador(interno, executar.caminho_do_cassete(c, tmp_path), "gravar")
    gravada = await simulador.rodar_conversa(c, gravador, real=True, snapshot=snap)
    gravador.confirmar()
    assert any(p["papel"] == "auditor" for p in interno.pedidos) and gravada.parada == "contrato_assinado"
    tocador = ModeloGravador(None, executar.caminho_do_cassete(c, tmp_path), "tocar")
    tocada = await simulador.rodar_conversa(c, tocador, real=False, snapshot=snap)
    assert tocador.faltas == [] and tocada.parada == gravada.parada and tocada.trajetoria == gravada.trajetoria


# ---------------------------------------------------------------------------- 7. gravar não apaga o cassete bom
def test_gravar_escreve_no_temporario_e_so_troca_ao_confirmar(tmp_path):
    caminho = tmp_path / "01.jsonl"
    caminho.write_text('{"tipo": "antigo"}\n', encoding="utf-8")
    gravador = ModeloGravador(ModeloFalso({}), caminho, "gravar")
    assert caminho.read_text(encoding="utf-8") == '{"tipo": "antigo"}\n'       # nada apagado ao criar
    gravador.descartar()
    assert caminho.read_text(encoding="utf-8") == '{"tipo": "antigo"}\n' and not gravador.temporario.exists()
    novo = ModeloGravador(ModeloFalso({}), caminho, "gravar")
    novo.temporario.write_text('{"tipo": "novo"}\n', encoding="utf-8")
    novo.confirmar()
    assert caminho.read_text(encoding="utf-8") == '{"tipo": "novo"}\n' and not novo.temporario.exists()


async def test_gravar_cortado_pelo_teto_mantem_o_cassete_e_a_transcricao(tmp_path, monkeypatch):
    monkeypatch.setattr(executar, "PASTA_TRANSCRICOES", tmp_path / "transcricoes")
    c = caso("01")
    caminho = executar.caminho_do_cassete(c, tmp_path)
    caminho.write_text('{"tipo": "antigo"}\n', encoding="utf-8")
    modelo = ModeloComCusto(c.carregar_agente(), falso.roteiro_de(c.id))
    teto = custo.Teto(0.005, estimativa_turno_usd=0.002)
    rodada = await executar._uma_conversa(c, 1, "gravar", teto=teto, lead="cartao", juiz=False, modelo_real=modelo,
                                          pasta_cassetes=tmp_path, roteiros=None, conversas=None)
    assert rodada.parada == "teto_de_custo" and not rodada.aprovado
    assert any(f.codigo == "cassete_nao_gravado" for f in rodada.falhas)
    assert caminho.read_text(encoding="utf-8") == '{"tipo": "antigo"}\n'
    assert not caminho.with_name(caminho.name + ".tmp").exists() and not (tmp_path / "transcricoes").exists()

    completo = await executar._uma_conversa(c, 1, "gravar", teto=None, lead="cartao", juiz=False,
                                            modelo_real=ModeloComCusto(c.carregar_agente(), falso.roteiro_de(c.id)),
                                            pasta_cassetes=tmp_path, roteiros=None, conversas=None)
    assert completo.aprovado and '"tipo": "pedido"' in caminho.read_text(encoding="utf-8")
    assert (tmp_path / "transcricoes" / "01_viavel_ate_assinatura.md").exists()


# ---------------------------------------------------------------------------- 8. avisos à equipe
def _cabecalho(evento, **extra):
    valores = notificacoes.valores_do_aviso(evento=evento, nome="Ana", telefone="5511988887777", produto="x", etapa="y",
                                            **extra)
    return notificacoes.renderizar_modelo(notificacoes.MODELO_PADRAO, valores).splitlines()[0]


def test_cabecalho_do_aviso_nunca_sai_com_o_codigo_cru():
    assert _cabecalho("sinal", sinais=["quer_videochamada", "nao_sabe_ler"]) == \
        "🔔 *Sinal confirmado: lead pede videochamada, diz que não sabe ler*"
    assert _cabecalho("pediu_para_parar") == "🔔 *Lead pede para não receber mais mensagens*"
    assert _cabecalho("intencao:quer_agendar") == "🔔 *Lead demonstra a intenção quer agendar*"
    assert _cabecalho("etapa:triagem") == "🔔 *Lead entra na etapa triagem*"
    assert _cabecalho("etapa:triagem", gatilhos={"etapa:triagem": "Lead entra na etapa Triagem"}) == \
        "🔔 *Lead entra na etapa Triagem*"
    assert _cabecalho("etapa:closer") == "🔔 *Lead qualificado (proposta)*"


def test_rotulos_do_agente_do_catalogo_para_o_aviso():
    from app.acoes import _gatilhos_do_agente

    snap = caso("01").carregar_agente()
    rotulos = _gatilhos_do_agente(snap["agente"]["produto"], json.dumps(snap["agente"]["config"]))
    assert rotulos.get("etapa:sdr", "").startswith("Lead entra na etapa")
    assert _gatilhos_do_agente("catalogo", "{config quebrada") == {}           # nunca derruba o aviso


CONFIG_AVISOS = {"funcoes": {"avisos": True}}


def _avisos(gatilhos, avisos):
    return [a for a in automacoes.montar_acoes(CONFIG_AVISOS, None, gatilhos, id_lead="L", id_turno="T", avisos=avisos)
            if a["tipo"] == "preparar_aviso"]


def test_um_fato_nao_manda_dois_avisos():
    gatilhos = automacoes.gatilhos_do_turno(primeira_resposta=False, etapa_antes="sdr", etapa_depois="sdr",
                                            motivo_estado=None, situacao="respondido", sinais=["nao_sabe_ler"])
    so_um = _avisos(gatilhos, {"sinal", "sinal:nao_sabe_ler"})
    assert [a["dados"]["evento"] for a in so_um] == ["sinal:nao_sabe_ler"]
    # Dois sinais e só um com aviso próprio: o genérico vai, citando só o que ficou sem aviso.
    dois = _avisos(["sinal", "sinal:nao_sabe_ler", "sinal:quer_audio"], {"sinal", "sinal:nao_sabe_ler"})
    assert [(a["dados"]["evento"], a["dados"].get("sinais")) for a in dois] == [("sinal", ["quer_audio"]),
                                                                              ("sinal:nao_sabe_ler", None)]
    assert _avisos(["sinal", "sinal:quer_audio"], {"sinal"})[0]["dados"] == {"evento": "sinal", "sinais": ["quer_audio"]}
    assinado = _avisos(["contrato_assinado", "etapa:contrato_assinado"], {"contrato_assinado", "etapa:contrato_assinado"})
    assert [a["dados"]["evento"] for a in assinado] == ["contrato_assinado"]
    assert [a["dados"]["evento"] for a in _avisos(["contrato_assinado", "etapa:contrato_assinado"],
                                                  {"etapa:contrato_assinado"})] == ["etapa:contrato_assinado"]


# ---------------------------------------------------------------------------- teste do aviso no painel (Postgres)
async def test_teste_do_aviso_mostra_link_da_conversa_e_mensagem_do_lead(ambiente):  # noqa: F811
    cliente, email_admin, _banco = ambiente
    await _entrar(cliente, email_admin, "senha-admin-123")
    _id, _canal, _agente, h = await _escritorio_com_agente(cliente, "Teste do Aviso Ltda")
    salvo = await cliente.put("/api/notificacoes/sinal", headers=h, json={
        "nome": "Qualquer sinal", "modelo_mensagem": notificacoes.MODELO_PADRAO,
        "destinatarios": [{"rotulo": "Dra. Ana", "numero": "(11) 91111-2222"}]})
    assert salvo.status_code == 200, salvo.text

    sem_dominio = (await cliente.post("/api/notificacoes/sinal/teste", headers=h)).json()["texto"]
    assert "Mensagem do lead: Dá para ser por videochamada?" in sem_dominio
    assert "Conversa:" not in sem_dominio                                    # sem domínio a linha some, como no real
    assert sem_dominio.startswith("[TESTE] 🔔 *Sinal confirmado: lead pede videochamada*")

    await cliente.patch("/api/escritorio", headers=h, json={"dominio_helena": "advmidia.wts.chat"})
    com_dominio = (await cliente.post("/api/notificacoes/sinal/teste", headers=h)).json()["texto"]
    assert "Conversa: https://advmidia.wts.chat/redirect?type=SESSION&id=exemplo" in com_dominio


# ---------------------------------------------------------------------------- 9. painel: mídia enviada pela IA