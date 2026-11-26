"""Corpo do POST crm/v1/panel que o fluxo n8n de admin usa em produção para criar o painel padrão do CRM.

NÃO MEXER sem conferir com o fluxo n8n: o texto é enviado byte a byte (só "<userId>" é trocado pelo id do usuário
admin da conta). tests/test_painel_crm.py compara o que sai com esta constante.
"""

from __future__ import annotations

import json

MARCADOR_USUARIO = '"<userId>"'

CORPO_PAINEL_PADRAO = (
    '{"available":false,"title":"🤖 CRM COMERCIAL IA","key":"CCI","description":"A IA analisa o histórico de '
    'interações de cada lead — mensagens, respostas, qualificação e avanços nas etapas e posiciona automaticamente o '
    'contato na etapa correta do funil","scope":"COMPANY","adminUserIds":["<userId>"],"departmentIds":null,'
    '"customType":"UNDEFINED","type":"SALE","autoLossDays":60,"steps":[{"title":"📞SDR","type":0,"primaryColor":'
    '"rgb(102, 204, 255)","secondaryColor":"white","position":1,"isInitial":true,"isFinal":false},{"title":'
    '"🛒 Comercial","type":2,"primaryColor":"rgb(120, 75, 209)","secondaryColor":"white","position":2,"isInitial":'
    'false,"isFinal":false},{"title":"📄 Contrato em Elaboração","type":2,"primaryColor":"rgb(253, 171, 61)",'
    '"secondaryColor":"#4F4F4F","position":3,"isInitial":false,"isFinal":false},{"title":"✍️ Aguardando Assinatura",'
    '"type":2,"position":4,"primaryColor":"rgb(255, 203, 0)","secondaryColor":"#4F4F4F","isInitial":false,"isFinal":'
    'false},{"title":"✅ Contrato Assinado","type":2,"position":5,"primaryColor":"rgb(0, 200, 117)","secondaryColor":'
    '"white","isInitial":false,"isFinal":false},{"title":"❌ Desqualificado","type":2,"position":6,"primaryColor":'
    '"rgb(226, 68, 92)","secondaryColor":"white","isInitial":false,"isFinal":false}],"details":{"viewMode":"ALL",'
    '"allowRestrictedAgent":false,"celebrateOnWin":true,"celebrationSound":true}}'
)

# Tipos na ordem do array "steps" (igual ao n8n: steps[0..5]).
TIPOS_NA_ORDEM = ["SDR", "COMERCIAL", "CONTRATO", "AGUARDANDO_ASSINATURA", "CONTRATO_ASSINADO", "DESQUALIFICADO"]
TITULO = json.loads(CORPO_PAINEL_PADRAO)["title"]
TITULOS_DAS_ETAPAS = [s["title"] for s in json.loads(CORPO_PAINEL_PADRAO)["steps"]]


def corpo_para(id_usuario: str) -> bytes:
    """O corpo exato, com o id do usuário admin em adminUserIds."""
    assert CORPO_PAINEL_PADRAO.count(MARCADOR_USUARIO) == 1
    return CORPO_PAINEL_PADRAO.replace(MARCADOR_USUARIO, json.dumps(str(id_usuario))).encode("utf-8")
