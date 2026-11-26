"""Contrato na ZapSign (antigos fluxos n8n "WEAVER - Contrato" e "Contrato - NOVO").

dados.py       funções puras: validar os dados do lead, montar as variáveis do modelo, textos
servico.py     banco + ZapSign: reservar versão, gravar, processar assinatura (usado pelo Executor)

A IA não gera contrato: os dados são fatos extraídos turno a turno; quando estão completos e o lead
confirma, o turno põe 'gerar_contrato' na fila.
"""
