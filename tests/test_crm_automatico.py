"""CRM automático: agente sem regras de CRM numa conta com o painel de colunas fixas do onboarding.

Caso real (26/11): o agente "teste" (catálogo, papéis sdr/closer/contratos/...) trocou SDR → Closer → Contratos e
nada aconteceu no CRM: o agente não tinha "automacoes" nem a função CRM ligada. A conta tinha o painel "CRM Comercial
IA" com as colunas mapeadas por tipo (etapas_por_tipo). Agora o motor usa essas colunas sozinho: card na SDR no lead
novo, card na coluna do papel a cada troca, etiqueta do tipo (tirando as outras) e nota da troca no atendimento.
"""

from app import automacoes

CRM = {"id_painel": "painel-1", "etapas_por_tipo": {
    "SDR": "col-sdr", "COMERCIAL": "col-com", "CONTRATO": "col-ctr", "AGUARDANDO_ASSINATURA": "col-ass",
    "CONTRATO_ASSINADO": "col-ok", "DESQUALIFICADO": "col-dq"}}
AGENTE = {"funcoes": {"buscar_cep": True, "contrato_zapsign": False}, "catalogo": {"papeis": {
    "sdr": {"nome": "SDR — Qualificação"}, "closer": {"nome": "Closer — Fechamento"},
    "contratos": {"nome": "Contratos — Confecção"}, "assinatura": {"nome": "Assinatura — Acompanhamento"},
    "desqualificado": {"nome": "Desqualificado — Educação"}, "periododegraca": {"nome": "Período de Graça"}}}}


def _por_tipo(acoes):
    return {a["tipo"]: a for a in acoes}


def test_lead_novo_cria_card_na_coluna_sdr_com_etiqueta():
    acoes, problema = automacoes.acoes_do_lead_novo(AGENTE, CRM, id_lead="l1")
    assert problema is None
    card = _por_tipo(acoes)["mover_card"]
    assert card["dados"]["id_painel"] == "painel-1" and card["dados"]["id_etapa_helena"] == "col-sdr"
    assert _por_tipo(acoes)["etiquetar"]["dados"]["adicionar"] == ["📞 SDR"]


def test_cada_troca_move_o_card_etiqueta_e_anota():
    esperado = {"closer": ("col-com", "🛒 Comercial", "Closer"), "contratos": ("col-ctr", "📄 Contrato em Elaboração", "Contratos"),
                "assinatura": ("col-ass", "✍️ Etapa de Assinatura", "Assinatura"),
                "desqualificado": ("col-dq", "❌ Desqualificado", "Desqualificado"),
                "periododegraca": ("col-sdr", "📞 SDR", "Período de Graça")}
    for papel, (coluna, etiqueta, nome) in esperado.items():
        acoes = _por_tipo(automacoes.montar_acoes(AGENTE, CRM, [f"etapa:{papel}"], id_lead="l1", id_turno="t1"))
        assert acoes["mover_card"]["dados"]["id_etapa_helena"] == coluna, papel
        assert acoes["etiquetar"]["dados"]["adicionar"] == [etiqueta]
        assert etiqueta not in acoes["etiquetar"]["dados"]["remover"] and "📞 SDR" in acoes["etiquetar"]["dados"]["remover"] \
            or papel == "periododegraca"
        assert acoes["nota"]["dados"]["texto"].startswith(f"🔄 Lead passou para o agente {nome}")


def test_regras_proprias_do_agente_mandam():
    proprio = {**AGENTE, "funcoes": {"crm": True}, "automacoes": {"etapa:closer": {"coluna_crm": "outra"}}}
    acoes = _por_tipo(automacoes.montar_acoes(proprio, CRM, ["etapa:closer"], id_lead="l1", id_turno="t1"))
    assert acoes["mover_card"]["dados"]["id_etapa_helena"] == "outra" and "nota" not in acoes


def test_crm_desligado_no_agente_nao_mexe():
    desligado = {**AGENTE, "funcoes": {"crm": False}}
    assert automacoes.montar_acoes(desligado, CRM, ["etapa:closer"], id_lead="l1", id_turno="t1") == []


def test_conta_sem_colunas_fixas_nao_inventa():
    assert automacoes.montar_acoes(AGENTE, {"id_painel": "p"}, ["etapa:closer"], id_lead="l1", id_turno="t1") == []
    assert automacoes.acoes_do_lead_novo(AGENTE, None, id_lead="l1") == ([], None)


def test_card_movido_na_lawchat_acha_o_agente_da_coluna():
    from app.troca_etapa import etapas_da_coluna
    config = automacoes.config_efetiva(AGENTE, CRM)
    assert etapas_da_coluna(config, "col-com", "sdr") == ["closer"]
    assert set(etapas_da_coluna(config, "col-sdr", "sdr")) == {"sdr", "periododegraca"}
