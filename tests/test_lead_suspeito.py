"""Lead suspeito (app/canal/suspeito.py): a IA é desligada antes de gastar com outro robô, só figurinhas ou repetição.

Unitários da função pura + o pipeline com banco em memória, IA de mentira e visão de mentira (nada custa).
"""

import json
from datetime import datetime, timedelta, timezone

from app.canal import suspeito
from app.canal.suspeito import Regras, avaliar
from tests.test_midia_correcoes import JPEG, OGG, VisaoFalsa, _http
from tests.test_pipeline import SIMPLES, montar, webhook

T0 = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)


def conversa(*itens, passo_s=60):
    """itens: ('lead'|'ia', tipo, texto). Um minuto entre mensagens (passo_s muda)."""
    return [{"autor": a, "tipo": t, "texto": x, "enviada_em": T0 + timedelta(seconds=i * passo_s)}
            for i, (a, t, x) in enumerate(itens)]


def do_lead(*textos, tipo="texto", **kw):
    return conversa(*[("lead", tipo, t) for t in textos], **kw)


CLARO = "Olá! Sou a assistente virtual da Claro. Para segunda via digite 1, para falar com atendente digite 2."
URA = ("Bem-vindo ao atendimento.\n1 - Segunda via\n2 - Suporte técnico\n3 - Falar com atendente",
       "Opção inválida. Escolha uma das opções do menu.",
       "Não entendi sua opção. Digite 1 para segunda via ou 2 para suporte.",
       "Seu protocolo de atendimento é 20261126001. Obrigado por entrar em contato com a Claro.",
       "Bem-vindo ao atendimento.\n1 - Segunda via\n2 - Suporte técnico\n3 - Falar com atendente",
       "Opção inválida. Escolha uma das opções do menu.")


# ---------------------------------------------------------------------------- função pura
def test_robo_da_claro_repetindo_dispara():
    veredito = avaliar(do_lead(*[CLARO] * 6))
    assert veredito and veredito.motivo == "repetidas" and veredito.contagens["iguais"] == 6
    assert "mensagens repetidas" in veredito.nota() and "últimas 6 mensagens" in veredito.nota()


def test_quase_iguais_com_protocolo_mudando_dispara():
    textos = [f"Recebemos sua mensagem. Protocolo {1000 + i}. Aguarde o retorno da nossa equipe." for i in range(6)]
    veredito = avaliar(do_lead(*textos))
    assert veredito and veredito.motivo == "repetidas" and veredito.contagens["quase_iguais"] == 6
    assert veredito.contagens["iguais"] == 1


def test_menu_de_ura_dispara_como_robo():
    veredito = avaliar(do_lead(*URA[:5], "ok"))
    assert veredito and veredito.motivo in ("robo", "repetidas") and veredito.contagens["robo"] >= 3
    so_padrao = avaliar(do_lead(URA[0], URA[1], URA[3], "quero cancelar", "alô", "tem alguém aí"))
    assert so_padrao and so_padrao.motivo == "robo"


def test_so_figurinhas_e_bom_dia_dispara():
    itens = [("lead", "figurinha", None), ("lead", "imagem", None), ("lead", "figurinha", None),
             ("lead", "imagem", "Bom dia! Deus abençoe seu dia 🌻"), ("lead", "video", ""), ("lead", "figurinha", None)]
    veredito = avaliar(conversa(*itens))
    assert veredito and veredito.motivo == "so_midia" and veredito.contagens["midia_sem_contexto"] == 6
    assert "só figurinhas e imagens sem contexto" in veredito.nota()


def test_humano_que_repete_sim_e_ok_nao_dispara():
    assert avaliar(do_lead("sim", "ok", "sim", "ok", "sim", "ok")) is None
    assert avaliar(do_lead("oi", "tudo bem?", "sim", "sim", "sim", "obrigado")) is None
    assert avaliar(do_lead("Sofri um acidente de moto", "sim", "ok", "sim", "Fiquei afastado 3 meses", "ok")) is None


def test_varios_audios_reais_nao_disparam():
    itens = [("lead", "audio", None)] * 6
    assert avaliar(conversa(*itens, passo_s=2)) is None
    assert avaliar(conversa(*([("lead", "documento", None)] * 6))) is None


def test_fotos_de_documento_que_a_ia_pediu_nao_disparam():
    itens = [("ia", "texto", "Pode me mandar a foto do RG e do laudo?")] + [("lead", "imagem", None)] * 6
    veredito = avaliar(conversa(*itens))
    assert veredito is None


def test_nunca_nas_primeiras_mensagens():
    assert avaliar(do_lead(CLARO)) is None
    assert avaliar(do_lead(CLARO, CLARO)) is None
    assert avaliar(do_lead(*[CLARO] * 4)) is None
    assert avaliar(do_lead(*[CLARO] * 5)).motivo == "repetidas"
    assert avaliar(do_lead(*[CLARO] * 6), Regras(minimo=1, repetidas=1)) is None or \
        avaliar(do_lead(*[CLARO] * 2), Regras(minimo=1, repetidas=1)) is None   # limites mínimos sãos


def test_etapa_avancada_so_repeticao_literal():
    quase = [f"Recebemos sua mensagem. Protocolo {1000 + i}. Aguarde o retorno da nossa equipe." for i in range(6)]
    assert avaliar(do_lead(*quase), avancado=True) is None
    assert avaliar(do_lead(*URA), avancado=True) is None             # menu de URA sem repetição literal: não
    assert avaliar(do_lead(*[CLARO] * 6), avancado=True).motivo == "repetidas"
    itens = [("lead", "figurinha", None)] * 6
    assert avaliar(conversa(*itens), avancado=True) is None


def test_robo_rapido_que_a_ia_nao_tira_do_lugar():
    eco = "Recebemos sua mensagem e logo um consultor vai falar com você, aguarde por favor"
    itens = []
    for i in range(6):
        itens += [("lead", "texto", eco if i != 2 else "alô? tem alguém aí?"), ("ia", "texto", "Me conta o que aconteceu?")]
    mensagens = conversa(*itens, passo_s=1)
    veredito = avaliar(mensagens, Regras(repetidas=6))
    assert veredito and veredito.motivo == "robo" and veredito.contagens["respostas_da_ia"] >= 3


def test_regras_configuraveis_e_desligaveis():
    assert Regras.de({}, {}, ambiente={}).ligado
    assert not Regras.de({}, {"lead_suspeito": {"ligado": False}}, ambiente={}).ligado
    assert not Regras.de({"lead_suspeito": False}, None, ambiente={}).ligado
    assert not Regras.de({}, {"lead_suspeito": {"ligado": True}}, ambiente={"AGENTESIA_LEAD_SUSPEITO": "0"}).ligado
    assert Regras.de({}, ambiente={"AGENTESIA_LEAD_SUSPEITO_JANELA": "8"}).janela == 8
    regras = Regras.de({"lead_suspeito": {"repetidas": 4}}, {"lead_suspeito": {"repetidas": 6, "janela": 8}}, ambiente={})
    assert (regras.repetidas, regras.janela) == (6, 8)
    assert Regras.de({"lead_suspeito": {"minimo": 1, "repetidas": 1}}, ambiente={}).minimo >= 3
    assert avaliar(do_lead(*[CLARO] * 6), Regras(ligado=False)) is None


# ---------------------------------------------------------------------------- pipeline
def _imagem(texto=""):
    return webhook(texto, tipo="IMAGE", file={"publicUrl": "https://cdn.helena.run/foto.jpg", "mimeType": "image/jpeg"})


def _audio():
    return webhook("", tipo="AUDIO", file={"publicUrl": "https://cdn.helena.run/a.ogg", "mimeType": "audio/ogg"})


def _montar_com_visao(espera_s=0):
    """espera_s > 0: o turno fica esperando (como em produção, onde a espera junta as mensagens do lead)."""
    atendimento, repo, helena = montar(SIMPLES)
    repo.escritorios["esc-1"].config["espera_teste_s"] = espera_s
    visao = VisaoFalsa()
    atendimento.visao = visao
    atendimento._http_midia = _http({"/foto.jpg": JPEG, "/a.ogg": OGG})
    return atendimento, repo, helena, visao


async def test_pipeline_robo_repetindo_desliga_a_ia_antes_de_gastar():
    atendimento, repo, helena, visao = _montar_com_visao(espera_s=30)
    for _ in range(4):
        assert (await atendimento.receber(webhook(CLARO)))["feito"] == "agendado"
    lead = next(iter(repo.leads.values()))
    lead.id_sessao_helena = "sessao-1"
    pedidos_antes = len(atendimento.modelo.pedidos)
    resultado = await atendimento.receber(webhook(CLARO))           # 5ª igual: dispara
    assert resultado["motivo"] == "lead_suspeito" and resultado["suspeita"] == "repetidas"
    await atendimento.aguardar_esperas()

    assert lead.estado == "pausado" and lead.motivo_estado == "lead_suspeito" and lead.pausado_ate is None
    assert len(atendimento.modelo.pedidos) == pedidos_antes == 0    # nem o turno agendado chamou a IA
    assert visao.urls == [] and visao.nomes == []
    enviadas = list(helena.enviadas)
    assert ("cancelar", lead.id, "lead_suspeito") in repo.followups
    evento = next(e for e in repo.eventos if e["tipo"] == "lead_suspeito")
    assert evento["gravidade"] == "aviso" and evento["responsavel"] == "cliente"
    assert evento["detalhe"]["motivo"] == "repetidas" and evento["detalhe"]["iguais"] == 5
    notas = [a for a in repo.acoes if a["tipo"] == "nota" and "lead_suspeito" in a["chave_unica"]]
    assert len(notas) == 1 and notas[0]["dados"]["texto"].startswith("🚫 IA desativada automaticamente")
    assert "Helena" not in notas[0]["dados"]["texto"]
    etiqueta = next(a for a in repo.acoes if a["tipo"] == "etiquetar")
    assert etiqueta["dados"]["adicionar"] == ["🤖 IA Desativada"] and ":ia:" in etiqueta["chave_unica"]

    # Já marcado: imagem nova só é gravada (nada de visão, nada de turno, nada de nota nova).
    resultado = await atendimento.receber(_imagem())
    assert resultado["motivo"] == "lead_suspeito" and "suspeita" not in resultado
    await atendimento.aguardar_esperas()
    assert visao.urls == [] and len(atendimento.modelo.pedidos) == pedidos_antes and helena.enviadas == enviadas
    assert len([a for a in repo.acoes if a["tipo"] == "nota" and "lead_suspeito" in a["chave_unica"]]) == 1


async def test_pipeline_so_figurinhas_nao_descreve_imagem_quando_dispara():
    atendimento, repo, helena, visao = _montar_com_visao(espera_s=30)
    figurinha = lambda: webhook("", tipo="STICKER", file={"publicUrl": "https://cdn.helena.run/f.webp"})   # noqa: E731
    for corpo in (figurinha(), figurinha(), figurinha(), figurinha()):
        await atendimento.receber(corpo)
    pedidos_antes = len(atendimento.modelo.pedidos)
    resultado = await atendimento.receber(_imagem())                  # 5ª sem contexto: dispara antes da visão
    assert resultado.get("suspeita") == "so_midia"
    await atendimento.aguardar_esperas()
    assert visao.urls == [] and len(atendimento.modelo.pedidos) == pedidos_antes


async def test_pipeline_religado_nao_dispara_pelas_mensagens_antigas():
    atendimento, repo, helena, visao = _montar_com_visao()
    for _ in range(5):
        await atendimento.receber(webhook(CLARO))
    await atendimento.aguardar_esperas()
    lead = next(iter(repo.leads.values()))
    assert lead.motivo_estado == "lead_suspeito"
    # A equipe religa (mesmo efeito do ia_controle no banco em memória).
    await repo.atualizar_lead(lead.id, estado="ativo", motivo_estado=None, pausado_ate=None)
    resultado = await atendimento.receber(webhook("Oi, desculpa, sou eu mesmo. Sofri um acidente de trabalho."))
    assert resultado["feito"] == "agendado"
    await atendimento.aguardar_esperas()
    assert lead.estado == "ativo" and helena.enviadas                # respondeu: as 5 antigas não contam mais
    assert len([e for e in repo.eventos if e["tipo"] == "lead_suspeito"]) == 1


async def test_pipeline_lead_humano_com_audios_e_respostas_curtas_segue_normal():
    atendimento, repo, helena, visao = _montar_com_visao()
    for corpo in (webhook("oi"), _audio(), webhook("sim"), _audio(), webhook("ok"), _audio()):
        assert (await atendimento.receber(corpo))["feito"] == "agendado"
    await atendimento.aguardar_esperas()
    lead = next(iter(repo.leads.values()))
    assert lead.estado == "ativo" and not [e for e in repo.eventos if e["tipo"] == "lead_suspeito"]
    assert visao.nomes and helena.enviadas                           # áudio transcrito e a IA respondeu


async def test_pipeline_detector_desligado_no_agente():
    atendimento, repo, helena, visao = _montar_com_visao()
    agente = await repo.agente_do_canal("canal-1")
    agente.config[suspeito.MOTIVO] = {"ligado": False}
    for _ in range(6):
        assert (await atendimento.receber(webhook(CLARO)))["feito"] == "agendado"
    await atendimento.aguardar_esperas()
    assert not [e for e in repo.eventos if e["tipo"] == "lead_suspeito"]


# ---------------------------------------------------------------------------- Postgres local
import os  # noqa: E402

import pytest  # noqa: E402

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")


@pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")
async def test_postgres_dispara_eco_da_etiqueta_ignorado_e_religar_pela_etiqueta_zera_a_contagem():
    from app import ia_controle
    from app.banco.postgres import RepositorioPostgres
    from app.config import Configuracao
    from app.modelo import ModeloFalso
    from app.pipeline import Atendimento
    from tests.test_pipeline import HelenaFalsa
    from tests.test_postgres import _cenario

    repo = await RepositorioPostgres.conectar(URL, max_conexoes=1)
    pool = repo._pool
    try:
        conta, numero_canal, id_escritorio = await _cenario(repo)
        await pool.execute("""update agentesia_escritorios set config = config || '{"espera_teste_s": 30}'::jsonb
                              where id = $1::uuid""", id_escritorio)
        config = Configuracao(banco_url=URL, helena_url="http://helena.invalid", modelo_padrao="falso", modelo_falso=True,
                              espera_minima_s=0, espera_maxima_s=0, espera_padrao_s=0, segundos_por_letra=0,
                              max_reprocessos=2)
        modelo, helena = ModeloFalso(SIMPLES), HelenaFalsa()
        atendimento = Atendimento(repo, modelo, config, helena, digitar=False)

        def chega(texto):
            corpo = webhook(texto, para=numero_canal)
            corpo["content"]["companyId"] = conta
            return corpo

        for _ in range(4):
            assert (await atendimento.receber(chega(CLARO)))["feito"] == "agendado"
        resultado = await atendimento.receber(chega(CLARO))
        assert resultado["suspeita"] == "repetidas"
        await atendimento.aguardar_esperas()
        id_lead = resultado["id_lead"]
        linha = await pool.fetchrow("select estado, motivo_estado, pausado_ate, responder_apos from agentesia_leads "
                                    "where id = $1::uuid", id_lead)
        assert (linha["estado"], linha["motivo_estado"], linha["pausado_ate"], linha["responder_apos"]) == \
            ("pausado", "lead_suspeito", None, None)
        assert modelo.pedidos == [] and helena.enviadas == []
        evento = await pool.fetchrow("select gravidade, responsavel, detalhe from agentesia_eventos "
                                     "where id_lead = $1::uuid and tipo = 'lead_suspeito'", id_lead)
        assert (evento["gravidade"], evento["responsavel"]) == ("aviso", "cliente")
        assert json.loads(evento["detalhe"])["iguais"] == 5
        tipos = {r["tipo"] for r in await pool.fetch("select tipo from agentesia_acoes where id_lead = $1::uuid", id_lead)}
        assert "etiquetar" in tipos

        telefone = await pool.fetchval("""select c.telefone_normalizado from agentesia_leads l
                                          join agentesia_contatos c on c.id = l.id_contato where l.id = $1::uuid""", id_lead)
        # O CONTACT_TAG_UPDATE da etiqueta que a própria LawChat pôs é eco: não vira 'desativada_pela_equipe'.
        tag = {"eventType": "CONTACT_TAG_UPDATE", "content": {"phonenumber": "+" + telefone,
                                                              "tags": [{"name": ia_controle.ETIQUETA}]}}
        assert (await ia_controle.receber_evento_de_etiqueta(pool, id_escritorio, tag))["alterados"] == 0
        assert await pool.fetchval("select motivo_estado from agentesia_leads where id = $1::uuid", id_lead) == "lead_suspeito"
        # A equipe tira a etiqueta: religa.
        tag["content"]["tags"] = []
        assert (await ia_controle.receber_evento_de_etiqueta(pool, id_escritorio, tag))["alterados"] == 1
        assert await pool.fetchval("select estado from agentesia_leads where id = $1::uuid", id_lead) == "ativo"
        # Só o que veio depois do disparo conta: as 5 antigas não disparam de novo.
        assert await repo.mensagens_para_suspeita(id_lead, 18) == []
        assert (await atendimento.receber(chega(CLARO)))["feito"] == "agendado"
        assert len(await repo.mensagens_para_suspeita(id_lead, 18)) == 1
        for tarefa in list(atendimento._esperas.values()):
            tarefa.cancel()
    finally:
        await repo.fechar()
