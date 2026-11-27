"""Central de notificações, aba "Precisa de você" (app/gestao/rotas_central_notificacoes.py): `precisa` só nos avisos
que pedem ação e que a equipe ainda não respondeu, `sessao` para abrir a conversa na Central, e os `alertas` de saldo
acabando e de número desconectado/parado (só para quem gere; saldo zerado todos veem).

Os testes com banco só rodam com AGENTESIA_TESTE_PG_URL (ver tests/test_postgres.py).
"""

import os
import uuid

import pytest

from app.gestao import rotas_central_notificacoes as cn
from app.gestao import seguranca
from tests.test_central_notificacoes import _escritorio, _lead
from tests.test_gestao import _entrar, ambiente  # noqa: F401  (fixture)

URL = os.environ.get("AGENTESIA_TESTE_PG_URL")
pg = pytest.mark.skipif(not URL, reason="sem AGENTESIA_TESTE_PG_URL")


# ------------------------------------------------------------------ sem banco
def test_o_que_pede_acao_e_numero_mascarado():
    assert cn.pede_acao("pediu_humano") and cn.pede_acao("lead_suspeito") and cn.pede_acao("sinal_quer_videochamada")
    assert not cn.pede_acao("lead_qualificado") and not cn.pede_acao("contrato_assinado")
    assert not cn.pede_acao("pediu_para_parar") and not cn.pede_acao("ia_desativada")
    assert cn._numero_mascarado("5511987657788") == "(11) 9••••-7788"
    assert cn._numero_mascarado("") == "Número de WhatsApp"
    assert cn._dias_texto(3 * 24 * 60) == "3 dias" and cn._dias_texto(50 * 60) == "2 dias" and cn._dias_texto(30 * 60) == "30 horas"


# ------------------------------------------------------------------ com banco
@pg
async def test_precisa_de_voce_sessao_e_alertas(ambiente):  # noqa: F811
    cliente, _simulada, _email_admin, banco = ambiente
    cliente._transport.app.include_router(cn.api)
    cn._CACHE_ALERTAS.limpar()
    pool = banco._pool
    marca = uuid.uuid4().hex[:6]
    esc, canal, agente, email = await _escritorio(pool, f"Precisa {marca}")
    ana = await _lead(pool, esc, canal, agente, f"Ana {marca}")
    bia = await _lead(pool, esc, canal, agente, f"Bia {marca}")
    await pool.execute("update agentesia_leads set id_sessao_helena = 'sess-ana-1' where id = $1::uuid", ana)
    await pool.execute("""insert into agentesia_eventos (id_escritorio, id_lead, tipo, gravidade, responsavel, descricao, criado_em)
                          values ($1::uuid, $2::uuid, 'pediu_humano', 'aviso', 'lead', 'x', now() - interval '10 minutes'),
                                 ($1::uuid, $3::uuid, 'pediu_humano', 'aviso', 'lead', 'x', now() - interval '10 minutes')""",
                       esc, ana, bia)
    await pool.execute("""insert into agentesia_lead_etapas (id_escritorio, id_lead, etapa_de, etapa_para, origem)
                          values ($1::uuid, $2::uuid, 'sdr', 'closer', 'ia')""", esc, ana)
    # A equipe já respondeu a Bia depois do aviso: sai de "Precisa de você".
    await pool.execute("""insert into agentesia_mensagens (id_escritorio, id_lead, autor, tipo, texto, enviada_em)
                          values ($1::uuid, $2::uuid, 'humano', 'texto', 'oi', now())""", esc, bia)
    # Número em uso desconectado.
    await pool.execute("update agentesia_canais set ativo = false where id = $1::uuid", canal)

    await _entrar(cliente, email, "senha-gestor-123")
    r = await cliente.get("/api/central-notificacoes")
    assert r.status_code == 200, r.text
    d = r.json()
    por = {(i["tipo"], i["id_lead"]): i for i in d["itens"]}
    assert por[("pediu_humano", ana)]["precisa"] is True and por[("pediu_humano", ana)]["sessao"] == "sess-ana-1"
    assert por[("pediu_humano", bia)]["precisa"] is False and por[("pediu_humano", bia)]["sessao"] is None
    assert por[("lead_qualificado", ana)]["precisa"] is False
    numero = [a for a in d["alertas"] if a["tipo"] == "numero_desconectado"]
    assert len(numero) == 1 and numero[0]["acao"] == {"rotulo": "Ver integração", "destino": "/integracoes"}
    assert numero[0]["titulo"].startswith("Número (11) ") and "Helena" not in r.text

    # Atendente: não vê os alertas de número (é coisa de quem gere).
    cn._CACHE_ALERTAS.limpar()
    email_at = f"atendente-{marca}@escritorio.com"
    await pool.execute(
        """insert into agentesia_usuarios (email, nome, senha_hash, papel, id_escritorio, trocar_senha)
           values ($1, 'Atendente', $2, 'atendente', $3::uuid, false)""", email_at, seguranca.gerar_hash("senha-atend-123"), esc)
    await _entrar(cliente, email_at, "senha-atend-123")
    d = (await cliente.get("/api/central-notificacoes")).json()
    assert not any(a["tipo"].startswith("numero_") for a in d["alertas"])
