# LíderHub: como funciona a plataforma de agentes (referência, leitura de 22/11/2026)

Fonte: https://docs.liderhub.ai (criar agentes, quando ativar, base de conhecimento, modelos, delay, menções,
sobreposição de prompt, configurações, integrações, API, follow-up). Resumo em paráfrase.

## Como eles fazem
- **Criação**: via IA (sobe conversa exportada ou PDF de script + objetivo: fechar contrato, agendar, transferir, recepcionar),
  por template da comunidade ("Usar Template") ou do zero. Edição manual ou "Modificar com IA".
- **Configurações do agente**: prompt e menções, contagem de caracteres, base de conhecimento, delay, agente primário,
  palavra-chave, referências, voz, modelo de IA.
- **Quando ativar**: responsável padrão da conexão; palavra-chave (uma palavra, só no início da conversa, por campanha);
  menção de outro agente (@agente); ação em massa; manual. Teste com `/restart`.
- **Sobreposição de prompt**: ao passar para outro agente, já mandar a primeira pergunta do próximo no mesmo turno.
- **Menções (@)**: status, tag, departamento, responsável, template, gerarcontrato (ZapSign), calendário, notificar, resumo,
  think, biblioteca, calculadora, dataehora, salvarnome, áudio liga/desliga, desativarIA, origem, advbox, variável, personalizado.
- **Delay**: 5 s (quase imediato), 15 s (padrão), 30 s (áudio, mensagens picadas), 60 s+ (casos específicos). O tempo reinicia a cada mensagem.
- **Base de conhecimento**: documentos consultados sob demanda, só se o prompt pedir (@biblioteca).
- **Modelos**: GPT-5.2 (7 créditos, beta), GPT-5 Mini (4), GPT-5 Nano (1), GPT-4.1 (8, em descontinuação).
- **Follow-up**: por status do funil, templates estáticos com cadência, desistência automática; não dispara em ação em massa.
- **API**: chave `x-company-key`, 3 req/s, paginação até 100; Custom Tools (URL + método + JSON Schema) viram menções.

## Como fica aqui (decisões)
| LíderHub | Sistema LawChat IA |
|---|---|
| A IA aciona menções (@status, @tag...) | **O código age**: gatilho → automação (CRM, etiqueta, departamento, aviso, contrato). Menos risco de a IA "esquecer" ou chamar fora de hora |
| Delay 5/15/30/60 | Comportamento › Tempo de resposta 5–45 s ou automático pelo tamanho da mensagem |
| Palavra-chave por campanha | **A fazer**: palavra-chave/UTM do anúncio escolhe o agente ou a etapa inicial |
| `/restart` para teste | **A fazer**: comando de reinício para números de teste |
| Base de conhecimento por documento | Hoje: FAQ, objeções e dados do escritório no prompt. **A fazer**: documentos com busca por trecho |
| @resumo | **A fazer**: resumo do caso como nota (já existe o do contrato no plano) |
| @calendario | **A fazer**: agendamento (Google Calendar) |
| Modelo por agente | Já existe; **a fazer**: modelo por etapa (barato na triagem, forte no fechamento) |
| Follow-up por status | **A fazer**: módulo de follow-up (cadência do n8n: 1h, 5h, 24h, 72h, 7, 15, 30 dias; seg–sáb 8h–20h) |
| Custom Tool | **A fazer**: ação "chamar webhook" nas automações |

## Ideias anotadas
Palavra-chave por campanha; delay maior para áudio; checagem de elegibilidade com cálculo registrado; checklist de documentos;
consentimento LGPD antes de CPF; follow-up com cadência por estado e limite diário; resumo + aviso de lead de alto potencial;
modelo por etapa com custo estimado por conversa.
