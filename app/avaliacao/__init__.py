"""Teste do agente: simula conversas inteiras pelo caminho real (webhook -> pipeline -> envio) e confere o resultado.

Plano completo em docs/PLANO_TESTE_AGENTE.md; como usar em docs/TESTE_DO_AGENTE.md.

Dois modos, duas perguntas:
  * offline (ModeloFalso ou cassete): o código em volta da IA está certo? De graça, no pytest.
  * real (só com --real e teto de custo): o modelo e o prompt atendem bem? Custa, roda N vezes.

O motor só usa APIs públicas do atendimento e lê o repositório em memória; não depende dos detalhes
internos de app/pipeline.py nem de app/cerebro/.
"""
