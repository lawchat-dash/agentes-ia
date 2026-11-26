from datetime import datetime, timedelta, timezone

from app.canal import filtro
from app.canal.helena import ler_webhook


def webhook(texto="oi", tipo="TEXT", de="5511988887777", para="5511912345678", direcao="FROM_HUB", **extra):
    return {"eventType": "MESSAGE_RECEIVED", "content": {
        "id": "m1", "companyId": "c1", "sessionId": "s1", "type": tipo, "text": texto, "direction": direcao,
        "origin": "DEFAULT", "timestamp": datetime.now(timezone.utc).isoformat(),
        "details": {"from": de, "to": para, **extra}}}


def test_grupo_lista_e_reacao_nem_entram():
    assert filtro.antes_do_banco(ler_webhook(webhook(de="120363000000000000@g.us"))) == "grupo_ou_lista"
    assert filtro.antes_do_banco(ler_webhook(webhook(de="5511900000000-1600000000"))) == "grupo_ou_lista"
    assert filtro.antes_do_banco(ler_webhook(webhook(isGroup=True))) == "grupo_ou_lista"
    assert filtro.antes_do_banco(ler_webhook(webhook(tipo="REACTION"))) == "sem_conversa:reaction"
    assert filtro.antes_do_banco(ler_webhook(webhook(texto=""))) == "mensagem_vazia"
    assert filtro.antes_do_banco(ler_webhook(webhook())) is None


def test_decisao_depois_de_gravar():
    agora = datetime.now(timezone.utc)
    regras = filtro.Regras.de({"filtro": {"numeros_bloqueados": ["(11) 97777-6666"], "atraso_maximo_min": 10}},
                              {"filtro": {"rajada": {"mensagens": 3, "segundos": 60}}})
    rajada = filtro.ControleDeRajada()
    evento = ler_webhook(webhook())
    assert filtro.decidir(evento, regras, rajada, agora).responder

    bloqueado = ler_webhook(webhook(de="5511977776666"))
    assert filtro.decidir(bloqueado, regras, rajada, agora).motivo == "numero_bloqueado"

    atrasado = ler_webhook(webhook())
    atrasado.enviada_em = agora - timedelta(minutes=45)
    d = filtro.decidir(atrasado, regras, rajada, agora)
    assert d.motivo == "mensagem_atrasada" and "45 min" in d.avisar

    proprio = ler_webhook(webhook(de="5511912345678"))
    assert filtro.decidir(proprio, regras, rajada, agora).motivo == "conversa_consigo_mesmo"


def test_rajada_pausa_o_lead():
    regras = filtro.Regras(rajada_mensagens=3, rajada_segundos=60)
    rajada = filtro.ControleDeRajada()
    chave = "canal:lead"
    assert [rajada.registrar(chave, regras, agora=t) for t in (0, 1, 2)] == [False, False, False]
    assert rajada.registrar(chave, regras, agora=3) is True
    assert rajada.registrar(chave, regras, agora=200) is False          # janela passou


def test_segredo_do_webhook_e_por_escritorio(monkeypatch):
    from app.canal import webhook as wh
    monkeypatch.setenv("AGENTESIA_WEBHOOK_SEGREDO", "geral")
    monkeypatch.setenv("AGENTESIA_URL_PUBLICA", "https://ia.exemplo.com/")
    a, b = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
    assert wh.segredo_do_escritorio(a) != wh.segredo_do_escritorio(b)
    assert wh.url_do_escritorio(a).startswith(f"https://ia.exemplo.com/webhook/helena/{a}?segredo=")
    assert wh.segredo_do_escritorio("nao-e-uuid") is None
