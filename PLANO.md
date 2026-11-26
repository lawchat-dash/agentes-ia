# Plano: IA de atendimento comercial no WhatsApp

Pesquisa feita em 13/11/2026. Os valores de preço e as datas de regras da Meta vêm de blogs de terceiros que divergem entre si; confirme na página oficial da Meta antes de decidir com base neles.

## 1. O que a pesquisa mostrou

### Regras da Meta
- **IA de negócio é permitida; IA de uso geral não.** Desde 15/01/2026 a Meta proíbe, na API do WhatsApp Business, chatbots cujo produto principal é a conversa genérica (tipo ChatGPT). Atendimento, vendas, agendamento e consulta de pedido continuam permitidos. Consequência para o projeto: a IA precisa ficar restrita ao assunto do negócio e recusar pedidos fora dele.
- **Para atender clientes reais é preciso verificar a empresa** na Meta (documentos do CNPJ), aprovar o nome de exibição e ter um endereço HTTPS público para o webhook. Sem verificação, só dá para falar com números de teste cadastrados.
- **Número**: o modo de coexistência permite usar o mesmo número no aplicativo WhatsApp Business e na API, mas a disponibilidade depende das regras de elegibilidade da Meta.

### Custos do WhatsApp (Brasil)
- A cobrança é **por mensagem entregue**, por categoria (desde julho de 2025).
- **Marketing** (mensagem iniciada pela empresa): cerca de US$ 0,0625, perto de R$ 0,32. É o único valor em que as fontes concordam.
- **Utilidade e autenticação**: entre US$ 0,007 e US$ 0,0225 conforme a fonte.
- **Respostas ao cliente dentro da janela de 24h**: eram gratuitas. Várias fontes dizem que desde 01/10/2026 há 1.000 gratuitas por mês por número e cobrança depois disso; outra fonte dá uma data diferente. **Ponto a confirmar na Meta.**

### LGPD
- Não encontrei orientação da ANPD específica para chatbots de WhatsApp; a LGPD se aplica normalmente.
- Práticas a adotar: avisar na primeira mensagem que é um atendimento automatizado e para que os dados serão usados; guardar só o necessário; ter prazo para apagar conversas antigas; permitir que o cliente peça para parar ou para apagar os dados.
- Isto é um resumo de boas práticas, não um parecer jurídico.

### Lições de quem já colocou em produção
- **Clientes mandam várias mensagens picadas.** O padrão é esperar alguns segundos (os exemplos usam de 1,5 s a 10 s) depois da última mensagem, juntar tudo e responder uma vez só.
- **Áudio é muito comum no Brasil.** É preciso transcrever; os links de mídia do WhatsApp expiram, então o download precisa de nova tentativa.
- **Transferência para humano deve levar contexto**: resumo da conversa, motivo e dados já coletados, para o cliente não repetir tudo.
- **Depois de transferida, a conversa fica com o humano** até ele devolver; a IA não volta a responder sozinha.
- **Monitorar** falhas, limites de taxa e conversas sem resposta.

## 2. Desenho proposto

```
Cliente → WhatsApp → Webhook (FastAPI)
                        │ confere assinatura, descarta duplicada, responde 200
                        ▼
                  Fila por cliente (espera ~5 s e junta as mensagens)
                        ▼
                  Agente
                   ├─ regras fixas (pediu humano? reclamação? fora do horário?)
                   ├─ modelo Claude + conhecimento do negócio + histórico
                   ├─ ferramentas (catálogo, agenda, registrar lead, chamar humano)
                   └─ travas de saída (preço só se veio de consulta)
                        ▼
                  Envio pelo WhatsApp + gravação no banco
```

### Estrutura de pastas
```
app/
  main.py            sobe o servidor
  config.py          chaves e ajustes lidos do .env
  webhook.py         recebe e valida as mensagens
  whatsapp.py        envia texto, botões, "digitando", baixa mídia
  buffer.py          junta mensagens picadas do mesmo cliente
  agent.py           ciclo modelo → ferramentas → resposta
  tools.py           ações disponíveis para a IA
  guards.py          regras fixas e travas de saída
  db.py              clientes, mensagens, leads, transferências
  transcribe.py      áudio para texto
conhecimento/        preços, horários, políticas, FAQ em arquivos .md
prompts/atendente.md
scripts/chat.py      conversar com a IA no terminal, sem WhatsApp
tests/               testes de código + conversas de exemplo
```

### Escolhas técnicas
| Peça | Escolha | Motivo |
|---|---|---|
| Linguagem | Python + FastAPI | É o que os melhores projetos de referência usam |
| WhatsApp | Cloud API oficial da Meta | Sem risco de banimento do número |
| Banco | SQLite no início, Postgres ao crescer | Zero configuração para começar |
| Conhecimento | Arquivos .md carregados no prompt | Simples e suficiente até algumas dezenas de páginas; busca em documentos só se passar disso |
| Áudio | Serviço de transcrição (a definir) | O modelo de texto não recebe áudio direto |
| Hospedagem | Railway, Render ou VPS | HTTPS público pronto |

### Modelo de IA
Padrão proposto: **Claude Opus 5.5** (`claude-opus-5-5`), com cache do prompt para baratear o conhecimento repetido a cada mensagem.

Preços da API por milhão de tokens (tabela de 03/11/2026):

| Modelo | Entrada | Saída |
|---|---|---|
| Opus 5.5 | US$ 4,00 | US$ 20,00 |
| Sonnet 5.5 | US$ 2,00 | US$ 10,00 |
| Haiku 5.5 | US$ 0,10 | US$ 0,50 |

Estimativa minha, não medida: com cerca de 4 mil tokens de contexto (quase todo em cache) e uma resposta curta, cada resposta no Opus 5.5 sai por volta de US$ 0,01 a 0,02, ou seja, uns US$ 10 a 20 por mil respostas. No Haiku 5.5 seria dezenas de vezes menos. A decisão de trocar por um modelo mais barato é sua; o plano prevê medir a qualidade com as conversas de teste antes de trocar.

## 3. Etapas

| # | Etapa | Entrega | Depende de você |
|---|---|---|---|
| 1 | Núcleo no terminal | Conversar com a IA usando o conhecimento do negócio e histórico | Conteúdo do negócio |
| 2 | Ferramentas e travas | Consulta a catálogo, registro de lead, transferência para humano, trava de preço | Lista do que a IA pode fazer |
| 3 | Conversas de teste | 20 a 30 perguntas reais com a resposta esperada, rodadas a cada mudança | Exemplos de conversas reais |
| 4 | Servidor WhatsApp | Webhook, envio, mensagens duplicadas, mensagens picadas, número de teste da Meta | Conta Meta for Developers |
| 5 | Mundo real | Áudio, imagem, fora do horário, aviso à equipe na transferência | Quem recebe as transferências |
| 6 | Produção | Hospedagem, número real, aviso de privacidade, limpeza de dados antigos | Verificação da empresa na Meta |
| 7 | Acompanhamento | Painel simples de conversas, custos e transferências | — |

As etapas 1 a 3 não precisam de conta na Meta nem de servidor.

## 4. Decisões em aberto
1. Qual é o negócio e o que a IA faz: tirar dúvidas, vender, agendar, consultar pedido?
2. O número atual da empresa vai para a API, ou será um número novo?
3. Para onde vai a transferência para humano: um WhatsApp da equipe, e-mail, ou uma caixa de entrada como o Chatwoot?
4. A IA vai iniciar conversas (lembretes, recuperação de venda) ou só responder? Iniciar conversa custa por mensagem e exige modelos aprovados.
5. Volume esperado de conversas por mês, para estimar custo.

## 5. Etapas comerciais, ferramentas e APIs

Segunda rodada de pesquisa (13/11/2026), focada em agentes que conversam, chamam ferramentas, chamam APIs externas e seguem um funil.

### Dois jeitos de controlar as etapas
| Abordagem | Como funciona | Exemplo | Avaliação |
|---|---|---|---|
| **O modelo decide a etapa** | As etapas ficam escritas no prompt e uma chamada extra ao modelo diz em qual etapa a conversa está | [SalesGPT](https://github.com/filip-michalsky/SalesGPT) (2.815 estrelas, MIT) | Boa ideia, código antigo: parado desde 09/2024, usa um formato de ferramentas em texto que os modelos atuais não precisam mais |
| **O modelo extrai, o código decide** | A IA conversa e registra os fatos por uma ferramenta; uma função comum calcula a etapa e o destino do lead | [brax-sdr-agent](https://github.com/michelxxx2323/brax-sdr-agent), [Intelligent-Sales-Agent](https://github.com/Yosra-Megbli/Intelligent-Sales-Agent) | Previsível, testável e auditável; é o que os projetos recentes usam |

Proposta: a segunda. A regra comercial fica em código e muda num lugar só; o modelo cuida da conversa.

### Etapas propostas
Cada lead tem uma etapa gravada no banco. A instrução da etapa atual entra no prompt a cada mensagem.

| Etapa | Objetivo da IA | Sai quando |
|---|---|---|
| `novo` | Cumprimentar, avisar que é assistente virtual | Cliente diz o que quer |
| `descoberta` | Entender a necessidade, uma pergunta por vez | Necessidade registrada |
| `qualificacao` | Coletar os dados que definem se e como atender | Dados mínimos completos |
| `apresentacao` | Recomendar produto ou serviço com dados do catálogo | Cliente reage à oferta |
| `objecao` | Tratar dúvida de preço, prazo ou confiança | Objeção resolvida ou cliente desiste |
| `fechamento` | Propor um próximo passo concreto: agendar, enviar proposta, link de pagamento | Passo confirmado |
| `transferido` | IA em silêncio; humano assume | Humano devolve |
| `nutricao` | Cliente não está pronto; lembrete futuro | Cliente volta |
| `perdido` / `encerrado` | Fora do perfil, sem interesse ou pediu para parar | — |

As etapas do SalesGPT (apresentação, qualificação, proposta de valor, análise de necessidade, solução, objeções, fechamento, fim) serviram de base; a tabela acima adapta para atendimento receptivo no WhatsApp.

### Ferramentas
| Ferramenta | O que faz | Chama API externa? |
|---|---|---|
| `consultar_catalogo` | Busca produto, preço, estoque | Sim, se houver sistema de estoque; senão lê arquivo |
| `registrar_qualificacao` | Grava os dados do lead; o código calcula etapa e prioridade | Não |
| `consultar_agenda` / `agendar` | Vê horários livres e marca | Sim (Google Calendar, Calendly) |
| `gerar_link_pagamento` | Cria cobrança | Sim (Mercado Pago, Stripe, Pix) |
| `solicitar_aprovacao` | Pede a um humano para aprovar desconto ou condição especial | Sim (aviso à equipe) |
| `transferir_para_humano` | Passa a conversa com resumo e motivo | Sim (aviso à equipe) |
| `registrar_opt_out` | Cliente pediu para não receber mais mensagens | Não |
| `encerrar_conversa` | Fecha com o motivo | Não |

O CRM (HubSpot, Pipedrive, RD Station) não é ferramenta da IA: o código sincroniza o lead e a etapa depois de cada mensagem, e uma falha do CRM não derruba a conversa.

### Práticas vistas no código que vale adotar
- **Pontuação do lead em código**, com pesos por sinal (é decisor, tem urgência, porte).
- **Conferência dupla**: o modelo marca um campo e o código confere o texto também. No brax, uma corretora de cripto passou pela marcação do modelo e foi pega pela checagem do código.
- **Limite de tamanho no WhatsApp**: resposta longa é reescrita em versão curta, e a reescrita só vale se mantiver os links e as palavras da original.
- **Lembretes com regras fixas**: só em horário comercial, em dias úteis, com número máximo, e nunca para quem pediu para parar.
- **Limite de desvios**: depois de 3 perguntas seguidas sem a conversa avançar, transfere para humano.
- **Clientes simulados**: cada teste é uma persona ("CEO de empresa com 28 pessoas, responde curto") e o resultado esperado. Outro modelo faz o papel do cliente e o teste confere se o lead terminou na etapa certa.
- **Registro de custo por conversa**, somando os tokens de cada chamada.
- **Um negócio por pasta de configuração** ([langgraph-sales-agent](https://github.com/yerdaulet-damir/langgraph-sales-agent)): catálogo e ajustes em arquivos, o mesmo código serve vários negócios.

### Mudanças na estrutura de pastas
```
app/
  etapas.py        definição das etapas e regras de transição
  qualificacao.py  pontuação e destino do lead
  crm.py           sincronização com o CRM
  followup.py      lembretes
  integracoes/     agenda, pagamento, estoque
testes/
  cenarios.json    personas e resultado esperado
```

## 6. Versão para advocacia previdenciária

Pesquisa de 13/11/2026. As regras da OAB abaixo vêm de blogs e fornecedores, que se contradizem em alguns pontos; o texto do Provimento 205/2021 e da Recomendação 001/2024 do CFOAB precisa ser conferido na fonte oficial. Os roteiros de triagem são uma proposta minha e devem ser validados por um advogado da área.

### O que muda em relação a um atendente comercial comum
| Tema | Atendente comercial | Atendente previdenciário |
|---|---|---|
| Papel | Vender | Fazer a triagem, coletar dados e documentos e levar o caso ao advogado |
| Opinião | Recomenda produto | Não diz se a pessoa tem direito, não calcula benefício, não estima valor |
| Promessa | Pode destacar vantagens | Nunca promete resultado nem prazo de concessão |
| Preço | Informa | Honorários só com o advogado; não usar gratuidade como isca |
| Iniciar conversa | Permitido, pago | Só responde quem procurou o escritório; disparo para desconhecidos é captação vedada |
| Dados | Comuns | Dados de saúde e de renda, que são sensíveis na LGPD, e sigilo profissional |

### Etapas
| Etapa | Objetivo da IA | Sai quando |
|---|---|---|
| `novo` | Identificar o escritório, avisar que é assistente virtual e que o advogado analisa o caso | Pessoa diz o motivo |
| `assunto` | Descobrir o tipo de caso | Tipo registrado |
| `triagem` | Fazer as perguntas do roteiro daquele tipo, uma por vez | Dados mínimos completos |
| `documentos` | Pedir os documentos da lista e receber fotos ou PDFs | Documentos essenciais recebidos ou pessoa não tem |
| `agendamento` | Marcar a conversa com o advogado | Horário confirmado |
| `em_analise` | IA em silêncio sobre o mérito; só confirma recebimento | Advogado decide |
| `cliente` | Caso contratado: lembrar documentos e compromissos, sem falar do andamento por conta própria | — |
| `transferido`, `fora_da_area`, `encerrado` | Saídas | — |

### Roteiros de triagem por tipo de caso (a validar)
- **Aposentadoria** (idade, tempo de contribuição, rural, especial): idade, tempo aproximado de contribuição, tipo de trabalho, períodos sem carteira, trabalho rural ou com agentes nocivos, se já pediu ao INSS.
- **Benefício por incapacidade**: qual a condição de saúde, desde quando não consegue trabalhar, última contribuição ou vínculo, se tem laudos, se já passou por perícia e qual foi o resultado.
- **BPC/LOAS**: idade ou deficiência, quem mora na casa, renda da família, se tem CadÚnico.
- **Pensão por morte**: data do falecimento, relação com a pessoa falecida, se ela contribuía ou era aposentada.
- **Salário-maternidade**: data do parto ou adoção, situação de trabalho na época.
- **Benefício negado ou cortado**: qual benefício, data da carta de decisão, motivo informado.
- **Revisão**: qual benefício recebe e desde quando.

### Regras em código, não no modelo
- **Urgência**: benefício negado ou cortado com data recente, perícia marcada ou pessoa sem renda sobem a prioridade e avisam a equipe na hora. Os prazos exatos são definidos pelo advogado e ficam em arquivo de configuração.
- **Checklist de documentos por tipo de caso**: RG e CPF, CNIS, carteira de trabalho, carta de indeferimento, laudos e exames, PPP para atividade especial, certidões.
- **Trava de opinião**: a resposta é barrada e substituída se disser que a pessoa "tem direito", "vai conseguir", citar valor de benefício ou prazo de concessão.
- **Nunca pedir senha**: a IA não pede senha do gov.br ou do Meu INSS, nem pagamento por Pix. Golpes previdenciários usam exatamente isso; se a pessoa oferecer a senha, a IA recusa e orienta.
- **Assunto fora de previdenciário**: informa que o escritório não atua na área ou transfere.

### Ferramentas
| Ferramenta | O que faz |
|---|---|
| `registrar_triagem` | Grava as respostas; o código classifica o tipo de caso e a prioridade |
| `listar_documentos` | Devolve o checklist do tipo de caso |
| `registrar_documento` | Guarda a foto ou PDF recebido e marca o item do checklist |
| `consultar_agenda` / `agendar` | Horários do advogado |
| `transferir_para_humano` | Passa a conversa com a ficha do caso |
| `registrar_opt_out` | Pessoa pediu para não ser mais contatada |

### O que o advogado recebe
Uma ficha por caso: tipo, prioridade, respostas da triagem, documentos recebidos e faltantes, pontos de atenção (datas, urgência) e a conversa completa. A ficha resume o que a pessoa disse; a análise do direito é do advogado.

Fase posterior: leitura automática do CNIS em PDF para listar vínculos e períodos na ficha, sempre para uso interno e com conferência humana.

### Cuidados com o público
- Muitos atendidos são idosos ou têm pouca familiaridade com tecnologia: frases curtas, sem termos jurídicos, uma pergunta por vez, e aceitar áudio desde a primeira versão.
- Documentos chegam como foto de celular; a IA confirma o recebimento e pede nova foto se estiver ilegível.
- Paciência com respostas incompletas: depois de duas tentativas sem resposta clara, oferece falar com uma pessoa.

### Dados e sigilo
- Aviso de privacidade na primeira mensagem e consentimento antes de receber dados de saúde.
- Documentos em armazenamento com acesso restrito, fora do banco de conversas.
- Prazo de retenção definido para quem não virou cliente.
- Conferir os termos de retenção de dados do provedor do modelo antes de enviar documentos de clientes.

### Projetos encontrados
Quase nada específico no GitHub: [jfprevConecta](https://github.com/giselegoulart/jfprevConecta) (API de chatbot previdenciário), [agente-advocacia-whatsapp](https://github.com/DutraDev9/agente-advocacia-whatsapp) (atendimento de escritório com IA) e [previdenciar.io](https://github.com/ricarossetto/previdenciar.io) (cálculo previdenciário e leitura de CNIS). Não li o código deles. A base técnica continua sendo a dos agentes das seções anteriores.

## Fontes
- Advocacia e OAB: [Telejud](https://telejud.com/advogado-pode-usar-chatbot-whatsapp-oab/), [advogahub](https://advogahub.ai/blog/resposta-automatica-whatsapp-advogados-oab), [guaniweb](https://guaniweb.com.br/agente-de-ia-no-whatsapp-para-advocacia/), [voga](https://voga.adv.br/blog/ia-triagem-leads-whatsapp-provimento-205/), [kivohub](https://kivohub.ai/blog/chatbot-advocacia-conformidade-oab), [unred](https://unred.com.br/blog/marketing-juridico-whatsapp-oab), [Zenvia (caso de escritório)](https://zenvia.com/blog/goncalves-advocacia-chatbot-para-qualificacao-de-leads/)
- Agentes de vendas: [SalesGPT](https://github.com/filip-michalsky/SalesGPT), [brax-sdr-agent](https://github.com/michelxxx2323/brax-sdr-agent), [Intelligent-Sales-Agent](https://github.com/Yosra-Megbli/Intelligent-Sales-Agent), [langgraph-sales-agent](https://github.com/yerdaulet-damir/langgraph-sales-agent), [blackexchange/LANG](https://github.com/blackexchange/LANG), [AgentSDR](https://github.com/Kandid-ai/AgentSDR)
- Política de IA: [respond.io](https://respond.io/blog/whatsapp-general-purpose-chatbots-ban), [Alibaba Cloud](https://www.alibabacloud.com/help/en/chatapp/use-cases/whatsapp-ai-policy-2026-guide), [replypop](https://replypop.com/blog/whatsapp-2026-ai-policy-explained)
- Preços: [activepieces](https://www.activepieces.com/blog/whatsapp-pricing-2026-per-message-rates-by-country), [messagecentral](https://www.messagecentral.com/blog/whatsapp-business-api-pricing-in-brazil), [vectalk](https://vectalk.com.br/blog/en/whatsapp-api-pricing-brazil/), [crminer](https://www.crminer.com.br/en/blog/whatsapp-business-api-cobranca-outubro-2026)
- Requisitos: [wati](https://www.wati.io/blog/whatsapp-api-prerequisites), [baat.ai](https://baat.ai/blog/whatsapp-business-api-access), [chakrahq](https://chakrahq.com/article/whatsapp-api-setup-checklist-business)
- LGPD: [Jornal Contábil](https://jornalcontabil.com.br/noticia/lgpd-e-os-chatbots-confira-algumas-acoes-para-adequar-sua-empresa/), [confidata](https://confidata.com.br/blog/agentes-de-ia-empresa-lgpd-controles)
- Produção: [n8n debounce](https://n8n.io/workflows/19116), [chat-sdk](https://chat-sdk.dev/docs/concurrency), [dev.to (50 mil mensagens)](https://dev.to/richard_sakaguchi_5809b6b/whatsapp-ai-bot-in-production-3-months-50k-messages-zero-downtime-3bn3), [wati (transferência)](https://astra-geo.wati.io/blog/whatsapp-agent-support-routing-surveys)
- Código de referência: [AleBrito124356/whatsapp-ai-agent](https://github.com/AleBrito124356/whatsapp-ai-agent), [subu53/whatsapp-sales-agent](https://github.com/subu53/whatsapp-sales-agent), [onurratarr/retail-whatsapp-llm-agent](https://github.com/onurratarr/retail-whatsapp-llm-agent)
