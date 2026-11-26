"""Tela de Funções e automações: o padrão (CRM automático) que o motor roda e a trava das instruções.

- GET /agentes/{id}/automacoes/padrao devolve as regras de automacoes.regras_automaticas, com o tipo de cada uma;
- sem as colunas fixas na conta, as regras vêm iguais, sem coluna (a tela avisa);
- salvar o padrão como regras próprias mantém o "nota_sempre" da nota de troca de agente;
- só a equipe LawChat (visão LawChat) edita a instrução por etapa.
Sem banco: chama as funções da rota direto.
"""

import asyncio

import pytest
from fastapi import HTTPException

from app import automacoes
from app.gestao import rotas

CRM = {"id_painel": "painel-1", "etapas_por_tipo": {
    "SDR": "col-sdr", "COMERCIAL": "col-com", "CONTRATO": "col-con", "AGUARDANDO_ASSINATURA": "col-ass",
    "CONTRATO_ASSINADO": "col-ok", "DESQUALIFICADO": "col-des"}}
AGENTE = {"catalogo": {"papeis": {"sdr": {"nome": "Ana — SDR"}, "closer": {"nome": "Bruno"},
                                  "contratos": {"nome": "Carla"}, "desqualificado": {"nome": "Encerramento"}}}}


def test_padrao_igual_ao_do_motor():
    tela = rotas._automacoes_padrao_tela(AGENTE, CRM, {"col-sdr": "SDR", "col-com": "COMERCIAL"})
    assert tela["regras"] == automacoes.regras_automaticas(AGENTE, CRM)
    assert tela["usa_padrao"] and tela["crm_pronto"] and not tela["crm_desligado"]
    assert tela["regras"]["lead_novo"] == {"coluna_crm": "col-sdr", "adicionar_etiquetas": ["📞 SDR"]}
    closer = tela["regras"]["etapa:closer"]
    assert closer["coluna_crm"] == "col-com" and closer["adicionar_etiquetas"] == ["🛒 Comercial"]
    assert "📞 SDR" in closer["remover_etiquetas"] and closer["nota"] == "🔄 Lead passou para o agente Bruno."
    assert tela["tipos"]["lead_novo"] == "SDR" and tela["tipos"]["etapa:contratos"] == "CONTRATO"
    assert tela["tipos"]["etapa:desqualificado"] == "DESQUALIFICADO"
    assert tela["funcoes_efetivas"]["crm"] is True                        # o motor liga o CRM no padrão
    assert tela["colunas"]["col-sdr"] == "SDR"


def test_regras_proprias_e_crm_desligado():
    proprias = {**AGENTE, "automacoes": {"lead_novo": {"nota": "Oi"}}}
    assert not rotas._automacoes_padrao_tela(proprias, CRM, {})["usa_padrao"]
    desligado = rotas._automacoes_padrao_tela({**AGENTE, "funcoes": {"crm": False}}, CRM, {})
    assert desligado["crm_desligado"] and not desligado["usa_padrao"] and desligado["funcoes_efetivas"]["crm"] is False


def test_sem_colunas_fixas_mostra_o_padrao_sem_coluna():
    tela = rotas._automacoes_padrao_tela(AGENTE, {}, {})
    assert not tela["crm_pronto"] and not tela["tem_painel"]
    assert tela["regras"]["lead_novo"] == {"adicionar_etiquetas": ["📞 SDR"]}
    assert "coluna_crm" not in tela["regras"]["etapa:closer"]
    assert tela["regras"]["etapa:closer"]["adicionar_etiquetas"] == ["🛒 Comercial"]


def test_salvar_padrao_mantem_nota_sempre():
    entrada = {"etapa:closer": {"nota": "🔄 Lead passou para o agente Bruno.", "nota_sempre": True},
               "lead_novo": {"adicionar_etiquetas": ["📞 SDR"], "nota_sempre": True}}
    limpas = rotas._manter_nota_sempre(entrada, automacoes.validar(entrada))
    assert limpas["etapa:closer"]["nota_sempre"] is True
    assert "nota_sempre" not in limpas["lead_novo"]                       # sem nota, não precisa


@pytest.mark.parametrize("usuario,visao", [({"id": "u", "papel": "gestor", "id_escritorio": "e"}, None),
                                           ({"id": "u", "papel": "atendente", "id_escritorio": "e"}, None),
                                           ({"id": "u", "papel": "admin_lawchat", "id_escritorio": None}, "gestor")])
def test_instrucao_so_superadmin(usuario, visao):
    ctx = rotas.Contexto(usuario, "e", visao)
    with pytest.raises(HTTPException) as erro:
        asyncio.run(rotas.alterar_etapa("ag", "sdr", rotas.AlterarEtapa(instrucao="x"), None, ctx))  # type: ignore[arg-type]
    assert erro.value.status_code == 403 and "equipe LawChat" in erro.value.detail
