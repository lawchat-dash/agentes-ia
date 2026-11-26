"""Follow-up: mensagem ao lead que parou de responder (antigos fluxos "Follow Up Unificado" do Weaver e do Geral).

regras.py     configuração, cadência, horário comercial, limites da OAB/Meta e pedido para parar (puro)
padrao.py     padrão do produto (cadência e prompts por etapa), ligar com o padrão, visão do admin
agente.py     os dois agentes: o de follow-up DECIDE (enviar, adiar, não enviar) e o agente da etapa ESCREVE (puro)
servico.py    fila em agentesia_followups: agendar, cancelar, o disparador (confere, decide, escreve, envia) e o lead parado
"""
