# LíderHub: análise da documentação pública e comparação com o LawChat

25/11/2026. Leitura só da web pública (sem conta, sem login, sem formulário), resumida com as nossas palavras.
Fontes: https://docs.liderhub.ai/ e https://liderhub.mintlify.app/ (índices `/llms.txt` e `/sitemap.xml` dos dois),
mais o nosso repositório (docs listados no fim e o código de `app/pipeline.py`, `app/ia_controle.py`,
`app/followup/`, `app/horario.py`, `app/consumo.py`, `app/gestao/laboratorio.py`).

**Os dois sites são a mesma documentação.** `docs.liderhub.ai` é o domínio próprio do site Mintlify
`liderhub.mintlify.app`: os dois `llms.txt` listam as mesmas 104 entradas e os dois `sitemap.xml` as mesmas URLs (o
sitemap do Mintlify já aponta para `docs.liderhub.ai`). Não achamos página que exista só em um deles. A única
diferença real é de **índice**: a página **"IA e humano"** (`/atendimento/ia-e-humano`, título "Transferir
Responsável") abre nos dois endereços, mas **não está** no `llms.txt` nem no `sitemap.xml` de nenhum. É uma página
"escondida", provavelmente nova. Endereços inventados (`/agentes/triagem`, `/agentes/grupos-de-agentes`,
`/atendimento/kanban`, `/atendimento/modo-foco`) caem na página inicial: não há páginas próprias de triagem, grupo de
agentes, modo foco ou sandbox. Esses assuntos aparecem só dentro de outras páginas (indicado abaixo).

Marcação usada no mapa: **[só fora do índice]** = só se acha pelo endereço direto; **[descontinuado]** = a própria
página diz que não funciona hoje.

---

## 1. Mapa da documentação deles

### 1.1 Introdução e geral
| Página | O que diz, em resumo |
|---|---|
| Introdução (`/`) | Plataforma de WhatsApp para venda e pós-venda, com foco declarado em advocacia **previdenciária e trabalhista**. Recomenda atendimento **passivo** (o lead puxa a conversa), não disparo em massa. Sem teste grátis; garantia de 30 dias. |
| Onboarding | Checklist na primeira entrada, que se marca sozinho: formulário (área, metas, ferramentas anteriores), reunião com especialista (opcional), dados da empresa (nome, CNPJ, OAB, endereço, redes; todos opcionais), conectar WhatsApp, criar e testar agente. Depois: 4 vídeos-modelo, ZapSign, Google Calendar, AdvBox. |
| Notificações e App | Sino no app web recebe tudo; push no celular para quase tudo: contrato gerado, contrato assinado, atribuição de chat, mudança de status, menção em nota, `@notificar` da IA, WhatsApp desconectado, pagamentos, agendamento no Calendar. Só no sino: tarefas e mensagens novas. Sem configuração por usuário documentada. |
| App celular (`/app-celular`, citada pela página de notificações) | iOS e Android: ver e responder conversas, acompanhar a IA, intervir pontualmente, receber push. |
| Novidades (changelog) | Uma entrada só (fev/2026: lançamento da documentação nova). |
| Suporte | WhatsApp em horário comercial, ticket, "LABS" ao vivo todo dia útil às 15h, assistente de IA na própria documentação, grupo de clientes no WhatsApp. Sem SLA. |
| Alterar DNS | Passo a passo para trocar o DNS do computador se a plataforma ficar lenta. |

### 1.2 WhatsApp
| Página | Resumo |
|---|---|
| Estratégias e boas práticas | Ter pelo menos 2 números (comercial e pós-venda); tratar o comercial como "descartável"; um número por produto para isolar banimento. |
| Conexão | Nova conexão por QR Code ou código (não oficial) ou fluxo Meta (oficial). Cada conexão tem **status, departamento e responsável padrão** (o responsável pode ser um agente de IA). Sincroniza 2 dias de histórico; avisa admin quando desconecta. |
| Chip e telefone | Parceria com operadora digital para números (chip, eSIM, Cloud API). |
| API oficial × não oficial | Tabela: custo, estabilidade, risco de banimento, follow-up só com modelo aprovado, histórico de 6 meses só por coexistência. |
| Meta/API oficial, Criar WABA, Importar WABA, Coexistência, Limitações da coexistência | Passo a passo da Business Manager e da WABA; coexistência (app Business e API no mesmo número) com limites: 5 msg/s, sem grupos, sem editar/apagar, mídia antiga não sincroniza. |
| Erros | Tabela de códigos de erro da Meta e do provedor com a ação para cada um (janela fechada, spam, número inválido, modelo pausado...). |
| API de Conversão | Explica a Conversions API da Meta; **não há integração nativa** (roadmap 2026). Alternativa: Custom Tool. |
| Bloqueios e banimento | Causas, tipos, prevenção, recurso à Meta. |

### 1.3 Workspace e migração
| Página | Resumo |
|---|---|
| Workspaces | Ambientes isolados (conexões, contatos, agentes, status, templates, membros). Ao criar, pode copiar configurações do atual. Contato não muda de workspace. |
| Permissões | 3 papéis: Administrador, Gerente, Suporte. Acesso por **departamento** e por **conexão**. Exceções: o responsável sempre vê a conversa; quem é mencionado em nota vê por 24 h. |
| Contatos e conversas / Importar / Exportar contatos | Importa CSV/Excel (nome e telefone obrigatórios; status, departamento, origem, tags por ID); não atualiza contato existente; exporta a lista filtrada (sem mensagens). |
| Importar / Exportar histórico | Migração completa só de plataformas da própria empresa; de terceiros, por ticket. Exportar só conversa a conversa, pelo celular, para usar como **exemplo de treino** do agente. |
| Entenda o Dashboard | Funil comercial por **tipo de status** (Nova conversa, Análise, Qualificado, Proposta, Sucesso, Perdas). Filtro **Cohort × Evento**, origem, agrupamento por dia/semana/mês/trimestre, gráfico "por período" ou "conversões", Sankey por origem. Sem métrica por atendente; sem exportar. |
| Departamento Comercial | Desenho de funil SDR → Closer com status sugeridos, automações recomendadas, técnicas de fechamento e **benchmarks** de conversão (ex.: 2,5 a 5% de sucesso sobre novas conversas). |

### 1.4 Agentes de IA
| Página | Resumo e como se configura |
|---|---|
| O que são | Assistente que responde no WhatsApp, qualifica, agenda, gera contrato e passa a humano. |
| Criar agentes | Em Automações > Agentes, de 3 jeitos: **com IA** (anexa histórico exportado do WhatsApp ou PDF do script, escolhe o objetivo: fechar contrato, agendar, transferir, recepcionar; pode explicar por áudio; gera em até 3 min), **por template da comunidade** (mostra agentes inclusos, quantos usam e instruções de teste; importa numa pasta) ou **do zero**. |
| Testar e ativar | 5 formas de ativar: responsável padrão da conexão, **palavra-chave** na primeira mensagem (uma por campanha), menção de um agente no prompt de outro, ação em massa, troca manual. **Teste**: mandar `/restart` para o número e depois a palavra-chave a partir do celular pessoal. Não há sandbox descrito nesta página. |
| Base de conhecimento | Documentos (FAQ, objeções, informação legal do nicho). A IA **só consulta se o prompt citar a menção** da base. Sem formatos, limites ou custo documentados. |
| Configurações do agente | Prompt à esquerda; à direita: contador de caracteres (conta o JSON das menções), base, delay, agente primário (vem da conexão), palavra-chave (uma palavra), **Referências** (quais agentes citam este), voz, modelo. |
| Modelos de IA | GPT-5.2 (7 créditos/msg, em beta, "pode pular etapas"), GPT-5 Mini (4), GPT-5 Nano (1), GPT-4.1 (8, saindo). Recomenda modelo por papel (triagem barata, fechamento caro). |
| Delay | Tempo de agrupar mensagens do lead (5 s, **15 s padrão**, 30 s, 60 s); cada mensagem reinicia o relógio. |
| O que é um prompt | Mapear perguntas, condicionais, mensagens literais (entre aspas) e cenários alternativos; evitar "pontas soltas"; testar com `/restart`; editar o prompt com a IA da plataforma. |
| Menções (@) | 21 menções inseridas pelo menu (menção para item inexistente fica **vermelha**): status, tag, departamento, responsável (inclui "responsável aleatório" com rodízio entre pessoas escolhidas), template, gerar contrato, calendário (verificar, criar, editar, deletar evento), notificar, resumo (vira nota interna), think, biblioteca, calculadora, data e hora, salvar nome, ativar áudio, desativar áudio, desativar IA, origem, AdvBox, variável personalizada (só texto), Custom Tool. |
| Sobreposição de prompt | Para a troca de agente ser invisível: o agente que passa já envia a **primeira pergunta do próximo**, em vez de avisar "vou transferir". Falha comum: a IA anuncia e não transfere. Exemplo: triagem → renda (BPC). |
| Conflito inicial | A primeira mensagem do lead atropela o roteiro; soluções: prioridade do roteiro, perguntas condicionadas, revisar o texto do anúncio, texto fixo para temas sensíveis. |
| Alucinação | Causas: pergunta sobre dado que o agente não tem (OAB, CNPJ, endereço), assunto fora do agente, menção sem instrução do que dizer. Correção: responder o cenário no prompt ou na base, transferir para humano, testar de novo. |
| Voz clonada e áudio | Automações > Vozes: amostras de 10 s ou mais, nome, processar, ouvir, ligar no agente. Modo áudio ligado e desligado **por menção no prompt**. Custo extra (ver créditos). |

### 1.5 Atendimento (a caixa de entrada deles)
| Página | Resumo |
|---|---|
| Visão geral | Abas **IA** (responsável é agente), **Ativos** (humano aceitou), **Pendentes** (sem IA e sem aceite; inclui o que a IA passou para humano e o arquivado que voltou), **Grupos**, **Arquivados**. Telas Conversas, Contatos (tabela) e **Kanban** por usuário. **Modo Foco** (só as minhas e as pendentes). Assinatura com nome do atendente, resumo simples ou detalhado em nota, trocar o número de envio. Ação em massa não dispara follow-up. |
| **IA e humano** [só fora do índice] | Ver seção 1.9. |
| Aba lateral direita | Favoritos, notas, galeria de mídias, "nuvem" (pasta de arquivos por cliente, converter imagem em PDF), logs e histórico das mudanças de propriedade. |
| Agendar mensagem | Botões "1 h" e "24 h", ou horário em linguagem natural que a IA converte; cancelamento manual. |
| Central de agendamentos | Todas as mensagens futuras (agendadas e follow-up) com **saúde do número por dia** (saudável, risco, crítico), gráfico por hora, reagendar ou cancelar em massa com intervalo entre envios. |
| Enviar template | `/` no campo de texto abre os modelos; na API oficial, fora da janela de 24 h, só modelo aprovado. |
| Filtros e ações em massa | Filtros por status, departamento, responsável, etiqueta, conexão. Ações: status, departamento, responsável, etiquetas (adicionar/remover/definir), **unificar conversas**, arquivar, trocar número, exportar CSV. |
| Notas e menção interna | Nota com texto, áudio ou arquivo; `@pessoa` notifica sem transferir. |
| Propriedades, Status, Departamento, Etiquetas, Origem, Responsável, Variáveis | Status pertence a um departamento (mudar status muda o departamento) e tem um **tipo** que alimenta o dashboard; follow-up mora no status. Origem pode ser marcada sozinha por **palavras-chave da primeira mensagem**. Variáveis: personalizadas (CPF, renda, preenchidas pela IA ou à mão), da conversa e **da empresa** (nome, CNPJ, OAB, endereço, que os agentes leem). |

### 1.6 Templates, follow-up e horário
| Página | Resumo |
|---|---|
| Gerenciar templates | Mensagem rápida com texto e uma mídia (JPG, PNG, MP4, MP3, OGG, PDF), variáveis `{{nome}}`, envio manual por `/`, pela IA (`@template`), no follow-up ou no pós-assinatura. |
| Roteiros de vídeos | 4 vídeos sugeridos: boas-vindas, qualificado → proposta, tutorial de assinatura, escritório/quebra de objeção; mais um roteiro de criativo de anúncio. |
| Solicitar aprovação Meta | Pedir a aprovação de dentro da plataforma; follow-up na categoria Marketing; 24 a 48 h. |
| Follow Up | Sequência **por status**: começa quando o lead entra no status (pela IA, por humano ou pela desistência), não em importação nem em ação em massa. Conteúdo **fixo** (template); a IA não escreve. Resposta do lead **reagenda** a sequência; mudar de status cancela. Sugestão: 1 h, 24 h, 3 d, 7 d. |
| Desistir do lead | No último follow-up: muda o status, define o próximo responsável (IA, pessoa ou ninguém) e arquiva. |
| Horário comercial | Por workspace, em horário de Brasília. Vale **para o follow-up** (fora do horário, reagenda). A página cita opções para a IA fora do horário sem explicar; ela mesma se contradiz sobre follow-up agendado. Sem feriados. |

### 1.7 Integrações
| Página | Resumo |
|---|---|
| ZapSign | Precisa de plano ZapSign com API. Chave em Integrações. Erros 402/403 explicados. Avisa que terão assinatura própria ("LíderSign") e recomenda plano mensal na ZapSign. |
| Modelo de contrato | DOCX com variáveis na ZapSign; documentos complementares (procuração) com as mesmas variáveis; data da assinatura automática. |
| Com API × sem API | Sem API: manda o link do formulário da ZapSign e o lead preenche. Com API: a IA coleta e o contrato sai preenchido. |
| Integração API ZapSign | 3 etapas: sincronizar modelos, ligar **cada agente a um modelo** e usar `@GerarContrato`, configurar o **pós-assinatura** (responsável, status, template, departamento). |
| Google Calendar | OAuth; `@calendario` com verificar, criar (com link do Meet), editar e apagar; disponibilidade e intervalo entre reuniões; mesmo fuso. |
| ADVBox | Chave da API; "Descrever status" (cada etapa do AdvBox em linguagem simples); `@advbox` **consulta processos pelo CPF** e explica a etapa ao cliente. Não cria cliente nem processo. |
| Custom Tools | Só plano Scale. Nome, URL, método, body com JSON Schema (o `description` de cada campo diz à IA o que extrair). Vira uma menção. Funciona com n8n, Make, Zapier. Segurança e autenticação não documentadas. |
| CTWA Clid | O `ctwaClid` do anúncio chega no `metadata` da Custom Tool; sugere mandar para a Conversions API quando o status vira Sucesso. |

### 1.8 Planos, créditos, API
| Página | Resumo |
|---|---|
| Entenda créditos | Toda ação de IA custa créditos: resposta ~9 (de ~6 a ~18 conforme o tamanho do prompt), áudio gerado 120/min, áudio recebido 6/min, imagem recebida ~4; menções pesadas (base, calendário, contrato, calculadora, resumo) ~35% mais caras. Médias: chat 70, qualificado 210, desqualificado até 30. Acima de 500 créditos num chat, **avisa o responsável**. Sem excedente contratado, **troca para um modelo mais barato**. |
| Add-ons | Membro R$ 50/mês, conexão R$ 100/mês, créditos de R$ 0,035 a R$ 0,020 por crédito conforme volume; excedente R$ 0,04. |
| Dashboard de consumo | Configurações > Uso: créditos no período, créditos por chat, consumo por status, **top 10 contatos mais caros**, evolução do custo médio, lista de chats com jornada de status. |
| API | Beta, plano Scale, chave `x-company-key` (mostrada uma vez), 3 req/s. Endpoints: conexões, status/origem/tags/departamentos (listar e atribuir), usuários, agentes, enviar mensagem (texto ou mídia, com agendamento ou como nota), listar/buscar/cancelar mensagens, grupos do WhatsApp (criar, participantes, admins), contatos (listar, criar, marcar lido), templates. Sem webhook de saída documentado. |
| MCP Server [descontinuado] | Servidor MCP com 14 ferramentas (conversas, mensagens, configurações) para Claude e Cursor. A página diz que está fora do ar e em reconstrução. |

### 1.9 A página "IA e humano" em detalhe [só fora do índice]

Quem atende é decidido por **um campo só, o Responsável** (um agente de IA ou uma pessoa).

- **IA → humano**, três jeitos: (1) o prompt manda trocar o responsável, normalmente junto com um resumo (ex.: o lead
  pediu uma pessoa); (2) **intervenção pontual**: o atendente manda uma mensagem e a IA **continua** responsável;
  (3) **"Intervir na conversa"**: o atendente vira responsável, a IA para e a conversa sai da aba IA para Ativos.
- **Humano → IA**: trocar o responsável para um agente (a IA responde na próxima mensagem do cliente, sem mandar nada
  sozinha) ou **arquivar escolhendo o próximo responsável** (pode ser a IA).
- **Ticket**: nasce quando um humano assume. Ciclo: IA → humano intervém (Ativo) → arquivado → cliente volta
  (Pendente) → aceito (Ativo).
- **Arquivar** não avisa o cliente. Se o cliente escreve depois, a conversa volta como **Pendente** e o responsável
  escolhido no arquivamento é **notificado** e precisa aceitar. Sem aceite, fica em Pendentes.
- **Não há tempo**: nenhuma volta automática da IA por prazo, nem alerta de demora. A página não fala de outros
  gatilhos além do pedido de humano.

**Comparação com o nosso** (`app/pipeline.py`, `app/ia_controle.py`, `app/followup/`):

| Ponto | LíderHub | Nós | Situação |
|---|---|---|---|
| Sinal de que o humano assumiu | Botão "Intervir" (troca o responsável) | **Qualquer fala do atendente** na Helena pausa a IA (`_fala_do_atendente` → `_pausa_por_humano`), grava a fala e cancela o follow-up na mesma transação; se falhar, evento crítico `pausa_falhou` | Temos melhor (não depende de clicar; à prova de falha) |
| Intervenção pontual (uma mensagem sem tirar a IA) | Tem | Não temos: toda fala pausa | **Não temos** |
| Volta da IA | Manual (trocar responsável ou arquivar com IA como próximo) | Automática depois de `minutos_pausa_humano` (padrão 15), cada fala reinicia; opção `pausa_sem_volta`; etiqueta "🤖 IA Desativada" e botão da Helena com "pausar N min" (`mudar_ia`); a IA volta calada e só responde à próxima mensagem do lead | Temos melhor (mais opções), com risco conhecido de a IA voltar cedo demais |
| Pedido de humano pelo lead | Prompt troca responsável + resumo | Sinal `pediu_humano` → pausa sem volta + nota "o lead pediu uma pessoa" | Temos igual; resumo para o atendente é parcial |
| Atendente assume no meio do envio | Não documentado | Segunda conferência antes de enviar e entre as partes; a pausa do atendente vence | Temos melhor |
| Registro | Logs na aba lateral | Nota na Helena com código `DES-…`, `agentesia_alteracoes`, nota "IA já estava desligada" | Temos igual ou melhor |
| Conversa encerrada que o cliente reabre | Volta para Pendentes e **avisa** o responsável escolhido | Depende da Helena; nós não avisamos ninguém quando um lead escreve numa conversa pausada (a nota só sai com lead ativo, `pipeline.py` ~1189) | **Não temos** o aviso |
| "Próximo responsável" ao encerrar | Escolhido no arquivamento | Não existe; encerrar atendimento na Helena está proposto em `HELENA_CAPACIDADES.md` | Planejado em parte |
| Rodízio entre pessoas | "Responsável aleatório" | Não temos; responsável (assignee) planejado em `ACOES_COM_ARROBA.md` D1 | Planejado (sem rodízio) |

---

## 2. Tabela função × LíderHub × nós

Legenda: **igual**, **melhor** (o nosso é melhor), **em parte**, **planejado** (doc citado), **não temos**.
Lembrete: a caixa de entrada, o Kanban, as notas, as respostas rápidas e as permissões de atendente **são da Helena**
para nós; não faz sentido reconstruir isso.

| Função | LíderHub | Nós | Situação |
|---|---|---|---|
| Caixa de entrada, abas, Kanban, contatos | Própria | Helena | Não se aplica (Helena) |
| Multiagente com troca invisível | Sobreposição de prompt (depende de o prompt estar certo) | `transferir_para` com `mensagem_troca`, travas `frase_de_outro_destino` e `perguntar_antes_de_transferir`, mesmo nome de atendente | **Melhor** |
| Grupo de agentes livre, agente inicial, criar/duplicar membro | Pastas de agentes, agente primário | 6 papéis fixos (`produtos.py`) | Planejado (`ACOES_COM_ARROBA.md` 4.1, D2) |
| Triagem por número | Agente padrão + palavra-chave | Origem do anúncio + agente de triagem com N perguntas | Planejado, desenho melhor (`AGENTE_TRIAGEM.md`) |
| Palavra-chave de ativação | Tem | Não | Planejado (`ACOES_COM_ARROBA.md` 4.2, D3) |
| Menu "@" com categorias, item vermelho, aba Referências | Tem | Editor com categorias e teclado; tokens com id, Referências e bloqueio ao publicar ainda não | Planejado (`ACOES_COM_ARROBA.md` fases A e B) |
| Ações pelo prompt (status, etiqueta, departamento, responsável, notificar, desativar IA) | Menções executadas | Feitas pelo **código** (automações por evento); pelo prompt, com conferência e idempotência | Em parte + planejado (`ACOES_COM_ARROBA.md` fase C) |
| Variáveis da empresa (CNPJ, OAB, endereço) | Configurações > Contas | Copiadas à mão nos prompts | Planejado (`ACOES_COM_ARROBA.md` A2, C1; `REGRAS_DO_MOTOR_E_CAMPOS.md` 1.10) |
| Variáveis do lead | Variáveis personalizadas (só texto) | Fatos do extrator (tipados, conferidos pelo auditor) | **Melhor** |
| Calculadora | Menção que o modelo usa | O código calcula e entrega como fato (período de graça) | **Melhor** |
| "Think" (raciocínio extra) | `@think` | Auditor e até 2 tentativas por turno | Em parte (outro jeito) |
| Data e hora | `@dataehora` | Vai em todo turno | **Igual** |
| Salvar nome | `@salvarnome` | Extrator grava `nome` | **Igual** |
| Resumo em nota | `@resumo` simples ou detalhado | Notas de passagem; `@Gerar resumo` | Em parte; planejado (`ACOES_COM_ARROBA.md` 0) |
| Base de conhecimento | Só se o prompt citar; sem detalhes | RAG com nota mínima, papéis por documento, regra anti-invenção, **lacunas registradas** e tela "Perguntas sem resposta" | **Melhor** (`BASE_DE_CONHECIMENTO.md`) |
| Anti-alucinação | Orientação de prompt | Regras fixas do motor (`REGRAS_NAO_INVENTAR`), guarda `fato_sem_fonte`, trava de honorários | **Melhor** (`REGRAS_DO_MOTOR_E_CAMPOS.md`) |
| Delay de agrupamento | 5 a 60 s, padrão 15 | `espera_s` 0 a 120, padrão 10 | **Igual** |
| Modelo por agente com custo | Tabela de créditos por modelo | Modelo por etapa e por papel; custo por membro ainda não aparece | Em parte; planejado (`ACOES_COM_ARROBA.md` 4.4) |
| Ler áudio, imagem, PDF, vídeo do lead | Transcreve áudio e imagem | Transcreve áudio e vídeo, lê imagem e PDF, filtra alucinação do transcritor | **Melhor** |
| Responder em áudio (TTS) | Sim, por menção | Não | Planejado (`ACOES_COM_ARROBA.md` 4.3, E1) |
| Voz clonada | Sim | Não | Não temos (ver seção 4) |
| Desativar e religar IA | `@desativarIA`, trocar responsável | Etiqueta, botão com minutos, pausa por fala do atendente | **Melhor**; pelo agente planejado (C4) |
| Responsável (pessoa) e rodízio | Sim, com aleatório | Não | Planejado sem rodízio (`ACOES_COM_ARROBA.md` D1) |
| Departamento | Sim | Transferir para equipe da Helena | Em parte |
| Status / funil | Status com tipo, por departamento | Etapas do agente + colunas do CRM da Helena; fase canônica proposta | Em parte; planejado (`DASHBOARD_IA.md` 3.0) |
| Etiquetas | Sim | Por automação, por nome | Em parte; por id planejado |
| Origem | Palavra-chave na 1ª mensagem ou menção | Anúncio TRACK/UTM/`ctwaClid` guardado e classificado | **Melhor**; origem por palavra-chave não temos |
| Mensagens rápidas com mídia | Templates com mídia, `/` e `@template` | Mídias da Biblioteca no roteiro (`[[audio:Nome]]`); modelo oficial no follow-up | Em parte; `@mensagem` planejado |
| Follow-up | Fixo por status, reagenda quando responde | **A IA escreve** retomando o assunto, passos ia/texto/modelo, horário, intervalo mínimo, janela de 24 h, desistência, cancela se o lead responder durante o envio | **Melhor** |
| Central de agendamentos com saúde do número | Sim | Não | Não temos (aba Follow-up planejada em `DASHBOARD_IA.md` 1.6) |
| Agendar mensagem manual | Sim | Helena | Não se aplica |
| Horário comercial | Só para follow-up | 3 modos para a IA (`sempre`, `so_no_horario`, `so_fora_do_horario`) + horário do follow-up | **Melhor**; feriados nenhum dos dois |
| Notificações à equipe | Sino, push no app | WhatsApp por evento, texto e destinatários configuráveis; central da LawChat | Em parte (sem app, sem sino); caixa de avisos planejada (`DASHBOARD_IA.md` 1.5) |
| ZapSign | Contrato por agente, pós-assinatura configurável | Geração com validação, hash, versões, lembretes, conferência da assinatura, webhook; automação `contrato_assinado` | **Melhor**; modelo por "@" planejado (`ACOES_COM_ARROBA.md` E2, `ZAPSIGN_CAPACIDADES.md`) |
| ZapSign sem API (link de formulário) | Sim | Não | Não temos (pouco valor) |
| Google Calendar | Sim | Não | Planejado (`ACOES_COM_ARROBA.md` E3) |
| AdvBox | Consulta processo por CPF | Criar cliente e processo depois da assinatura | Planejado, outra função (`ACOES_COM_ARROBA.md` E4) |
| Custom Tools / webhook de saída | Sim (plano Scale) | `buscar_cep` fixo | Não temos |
| API pública e MCP | API beta; MCP fora do ar | API só do painel (`API_PRODUTOS.md`) | Não temos |
| Conversions API (Meta) | Não nativo | Proposto | Planejado (`RASTREAMENTO_E_FILTROS.md` item 15) |
| Dashboard de funil | Cohort/Evento, origem, Sankey, conversões | Telas Início e Funil; dashboard completo com anúncios e CSV | Em parte; planejado (`DASHBOARD_IA.md`, `RASTREAMENTO_E_FILTROS.md`) |
| Consumo e custo | Créditos, por chat, por status, top 10 contatos | Custo por chamada em US$, limite mensal com `pausar`/`so_avisar` | Em parte; telas planejadas (`PLANO_PAINEL_CUSTO_DEPLOY.md` frente A) |
| Alerta de conversa cara | Acima de 500 créditos | Não | Não temos |
| Sandbox | `/restart` no WhatsApp real | Laboratório no painel (motor real, nada enviado) + modo teste por números de teste | **Melhor**; Helena falsa, custo em R$ e Resetar planejados (C7) |
| Reset de conversa no número de teste | `/restart` | Não | Não temos |
| Criar agente com IA a partir de histórico ou script | Sim | Não | Não temos |
| Templates de agente prontos | Comunidade, com contagem de uso | Biblioteca de produtos | **Igual** (sem contagem de uso) |
| Onboarding | Checklist que se marca sozinho | Onboarding em passos retomáveis do lado do admin; guiado para o cliente planejado | Em parte; planejado (`DASHBOARD_IA.md` 4.3, `ADMIN_WEAVER_PARA_NOSSO.md` 3.1) |
| Execuções e erros | Não documentado | Tela Erros; Execuções planejada | **Melhor**; planejado (`PLANO_PAINEL_CUSTO_DEPLOY.md` frente B) |
| Multi-escritório | Workspaces | Escritórios isolados, multi-conta na Helena | **Igual** |
| Grupos de WhatsApp pela API | Sim | Não | Não temos (fora do foco) |

---

## 3. O que vale agregar, em ordem de valor × esforço

### 1. Aviso "lead escreveu e ninguém respondeu" (Pendentes com notificação)
- **O que é:** quando o lead manda mensagem numa conversa com a IA pausada (humano assumiu, pediu pessoa, desativada)
  e nenhum atendente responde em X minutos, avisar a equipe; se escreveu depois de a Helena encerrar o atendimento,
  avisar o último responsável.
- **Por quê:** é o buraco mais caro de um escritório: o lead quente que ficou sem resposta porque a IA saiu.
- **Como:** um disparador como o do follow-up (`app/followup/servico.py` como modelo) em `app/notificacoes.py`, com
  evento novo `lead_sem_resposta_humana` no cadastro de avisos (tela `Avisos.tsx`); tempo por agente em `config`.
  O pipeline já grava toda mensagem com autor e o estado `pausado`; basta uma consulta.
- **Depende de:** nada em andamento; só ler `agentesia_mensagens` e `agentesia_leads`. Não mexe em `pipeline.py`.

### 2. Dados do escritório como variáveis (CNPJ, OAB, endereço, redes)
- **O que é:** um formulário em Configurações e `@CNPJ`, `@OAB` no prompt, trocados pelo motor. Campo vazio avisa.
- **Por quê:** é a causa nº 1 de alucinação que eles mesmos documentam (lead pergunta a OAB e a IA inventa), e hoje
  temos esses dados copiados em 6 prompts.
- **Como:** já desenhado: `ACOES_COM_ARROBA.md` A2 + C1 (`agentesia_escritorios.config.informacoes`,
  `Configuracoes.tsx`, `catalogo.montar_sistema`).
- **Depende de:** C1 espera o trabalho em `app/cerebro`. A2 (tela e rota) pode ir antes.

### 3. Intervenção pontual do atendente
- **O que é:** o atendente poder mandar uma mensagem sem tirar a IA (corrigir um dado, mandar um documento).
- **Por quê:** hoje toda fala pausa a IA por 15 min; a equipe evita ajudar para não "quebrar" o fluxo, ou esquece a
  IA pausada.
- **Como:** em `_pausa_por_humano` (`app/pipeline.py`), não pausar quando a mensagem do atendente começar com um
  marcador combinado (ex.: "/ia") ou vier de uma resposta rápida marcada; a IA recebe a fala como contexto
  ("o atendente disse"). Interruptor por agente em `config` e texto de ajuda na aba Ativação de `Agente.tsx`.
- **Depende de:** `app/pipeline.py` está sendo editado por outra frente: esperar a integração.

### 4. Reset da conversa no número de teste ("/restart")
- **O que é:** um número da lista de teste manda `#reiniciar` e o lead dele volta ao início (fatos, etapa, follow-up).
- **Por quê:** o advogado testa no próprio celular, no canal real, sem pedir para a LawChat apagar o lead.
- **Como:** no filtro de entrada (`app/canal/filtro.py`) ou no começo de `receber`, só para
  `_numeros_de_teste`; reaproveita o "Nova conversa" do `app/gestao/laboratorio.py`. Nota na Helena.
- **Depende de:** `app/canal` em edição (espera). Esforço pequeno.

### 5. Teto de custo por conversa e "top contatos mais caros"
- **O que é:** aviso quando uma conversa passa de um valor (ex.: US$ 0,50) e, na tela de consumo, ranking dos leads e
  das etapas que mais gastam.
- **Por quê:** mostra loop, lead que conversa sem fim e prompt grande demais. O escritório entende onde vai o dinheiro.
- **Como:** `app/consumo.py` (somar por `id_lead`), evento novo no cadastro de avisos; tela de consumo de
  `PLANO_PAINEL_CUSTO_DEPLOY.md` A4/A5.
- **Depende de:** `RASTREAMENTO_E_FILTROS.md` item 2 (lead em cada chamada de IA, migração 004). Sem isso o custo por
  lead sai errado.

### 6. Ações pelo prompt com o menu "@" e a aba Referências
- **O que é:** o que já está desenhado em `ACOES_COM_ARROBA.md`: status, etiqueta, notificar, desativar IA, mensagem
  rápida, contrato por modelo, com conferência no código.
- **Por quê:** é o que o cliente vê na concorrente e pede. O nosso desenho é mais seguro (lista fechada, idempotência,
  não andar para trás, falha não derruba a resposta).
- **Como:** fases A → B → C do documento. Do concorrente vale trazer: item vermelho no editor, contador de caracteres
  que inclui o bloco de ações, "Referenciado por N agentes".
- **Depende de:** fase C espera `app/cerebro` e `app/pipeline`.

### 7. Pós-assinatura configurável numa tela só
- **O que é:** ao assinar: próximo responsável, coluna do CRM, mensagem com mídia (vídeo de boas-vindas), equipe.
- **Por quê:** o momento de maior valor do funil; hoje funciona por automação `contrato_assinado`, mas a configuração
  fica escondida.
- **Como:** uma seção "Depois da assinatura" em `IntegracaoZapSign.tsx` gravando as automações de
  `app/automacoes.py`; mensagem pela Biblioteca de mídia.
- **Depende de:** `ZAPSIGN_CAPACIDADES.md` 3.1 (tutorial guiado) e responsável (D1) para a parte de pessoa.

### 8. Dashboard com "Cohort × Evento" e tipo de fase
- **O que é:** o mesmo número pode ser contado pelos leads que **entraram** no período ou pelos que **mudaram de
  fase** no período; e um tipo canônico por etapa.
- **Por quê:** sem isso o dono do escritório compara meses errado (lead de outubro que assinou em novembro).
- **Como:** já temos a fase canônica em `DASHBOARD_IA.md` 3.0 e a linha do tempo em `RASTREAMENTO_E_FILTROS.md`
  (`agentesia_lead_historico`). Acrescentar o seletor na `BarraDeFiltros.tsx` e em `repositorio.funil`.
- **Depende de:** migração 004 (linha do tempo).

### 9. Palavra-chave de ativação e origem por palavra-chave
- **O que é:** "BPC" ou "#acidente" na primeira mensagem manda direto ao grupo certo e marca a origem.
- **Por quê:** campanha de anúncio com mensagem pré-preenchida custa zero de IA para rotear.
- **Como:** camada antes da origem na triagem (`AGENTE_TRIAGEM.md` 5.1; `ACOES_COM_ARROBA.md` 4.2, D3), lista no
  `config` do grupo; `app/origem.py` ganha a regra por palavra.
- **Depende de:** migração da triagem (`id_agente_entrada`, `id_canal` não único).

### 10. Central de follow-ups com saúde do número
- **O que é:** lista de todos os envios futuros por dia e hora, com alerta de pico, e reagendar ou cancelar em massa.
- **Por quê:** banimento do número comercial é o pior dia de um escritório; ver o pico antes evita.
- **Como:** aba Follow-up do `DASHBOARD_IA.md` 1.6 lendo `agentesia_followups`; "saúde" = envios por conexão por hora
  contra um limite configurável; ações em massa por rota nova em `app/gestao/rotas.py`.
- **Depende de:** nada crítico; o disparador já respeita `intervalo_minimo_min`.

### 11. Resposta em áudio (TTS) só onde ajuda
- **O que é:** modo áudio ligado por sinal (`nao_sabe_ler`) ou pelo prompt; link, CPF e valores sempre em texto.
- **Por quê:** público previdenciário tem muita gente com pouca leitura.
- **Como:** `ACOES_COM_ARROBA.md` 4.3 e E1. Mostrar o custo da voz em linha separada no consumo.
- **Depende de:** teste real de mensagem de voz nos dois canais; `app/canal` (espera).

### 12. Google Calendar
- **O que é:** oferecer horários livres e marcar reunião com link do Meet.
- **Por quê:** escritórios que fecham com reunião (casos complexos) precisam; hoje é manual.
- **Como:** `ACOES_COM_ARROBA.md` E3, em duas fases para o modelo nunca inventar horário (melhor que o deles).
- **Depende de:** fase C (ações) e OAuth por escritório.

### 13. Consulta de andamento no AdvBox (pós-venda), com verificação
- **O que é:** o cliente pergunta "como está meu processo?" e recebe a etapa em linguagem simples.
- **Por quê:** é a pergunta mais repetida do pós-venda; libera a equipe.
- **Como:** além do "criar cliente" já planejado (E4), uma consulta só para **o contato já ligado ao cliente** (telefone
  do cadastro + CPF conferido), com "descrição de cada etapa" escrita pelo escritório (ideia boa deles). Nada de
  consulta por CPF solto (seção 4).
- **Depende de:** estudo da API do AdvBox (pendência 6 de `ACOES_COM_ARROBA.md`).

### 14. Webhook de saída (Custom Tool simples)
- **O que é:** o escritório cadastra uma URL que recebe eventos (lead qualificado, contrato assinado) com os dados.
- **Por quê:** integra com o CRM ou planilha do escritório e com a Conversions API sem esperarmos.
- **Como:** só **saída por evento** (não chamada livre decidida pelo modelo): tipo novo em `app/acoes.py`, fila
  com tentativas, assinatura HMAC, lista de campos fixa; tela em `Integracoes.tsx`.
- **Depende de:** nada; fila `agentesia_acoes` já existe.

### 15. Criar agente a partir de conversas exemplares
- **O que é:** o escritório envia 3 a 5 conversas boas exportadas do WhatsApp e o painel sugere o roteiro da etapa.
- **Por quê:** o maior atrito do onboarding é escrever o prompt.
- **Como:** rota nova em `app/gestao/` que gera um rascunho em `EditorDefinicao.tsx`, nunca publicado sem revisão;
  anonimizar nomes, telefones e CPF antes de mandar ao modelo.
- **Depende de:** `REGRAS_DO_MOTOR_E_CAMPOS.md` (o rascunho precisa caber nos campos do cliente, não nas regras fixas).

---

## 4. O que eles fazem pior ou que não devemos copiar

**Ética da OAB (Código de Ética e Provimento 205/2021):**
- A página do Departamento Comercial ensina **técnicas de fechamento** de varejo: explorar a aversão à perda,
  "reduzir opções", perguntas que já pressupõem o fechamento (à vista ou parcelado?). Em advocacia isso é
  mercantilização e captação. Não trazer para os nossos prompts nem para a ajuda.
- **Benchmarks de conversão e "Sucesso = contrato"** como meta do bot incentivam pressão. Podemos mostrar números, mas
  sem metas de venda para a IA.
- **Roteiros de vídeo e criativos** com "condição + direito possível + chame no WhatsApp" podem virar promessa de
  resultado. Se trouxermos modelos de vídeo, com revisão ética e sem promessa.
- **Voz clonada** do advogado falando pela IA: o cliente pode achar que fala com o advogado. Se um dia tivermos, só
  voz genérica ou com consentimento escrito do dono da voz e sem fingir ser pessoa (LGPD: voz é dado biométrico).
- Cálculo de honorários pelo modelo (`@calculadora` em honorários) e "prioridade na fila": já recusados em
  `ACOES_COM_ARROBA.md` 5.4; mantemos.

**Segurança e LGPD:**
- **AdvBox por CPF**: qualquer pessoa que saiba o CPF de outra recebe a lista de processos dela pelo WhatsApp. Fere
  o sigilo profissional e a LGPD. Nossa versão só responde ao contato já ligado ao cliente.
- **Custom Tools com URL livre e body montado pela IA**, sem autenticação documentada: risco de vazar dado para
  endpoint errado e de o modelo mandar o que não devia. Nosso webhook seria só de saída, por evento, com campos fixos.
- **Exportar conversas do WhatsApp para "treinar" o agente** sem anonimizar: são dados de saúde e de terceiros.
- **"Suspeita de golpe" ao reconectar**: a doc ensina a autorizar mesmo assim. É um hábito ruim de segurança para o
  usuário; preferimos explicar o alerta com o dado concreto (cidade e horário) e nunca normalizar aviso de golpe.
- **Ações só pelo prompt**: a IA muda status, responsável e desliga a IA sem trava de código (pode andar para trás,
  repetir, transferir errado). O próprio template deles chama um agente pelo nome errado. Nosso desenho confere no
  código.
- **Número "descartável" e um número por produto para isolar banimento**: é contornar as regras do WhatsApp. Não
  recomendar.

**Custo e qualidade:**
- **Trocar sozinho para um modelo mais barato** quando os créditos acabam: o lead passa a ser atendido por um modelo
  pior sem ninguém saber. Para assunto jurídico, preferimos o nosso `pausar`/`so_avisar` (`app/consumo.py`) e, se
  um dia houver modo econômico, avisando o escritório.
- **Recomendar modelo em beta** que "pode pular etapas" para o agente de fechamento.
- **Follow-up com texto fixo por status**: soa robótico e repete o mesmo para todos; o nosso, escrito pela IA com o
  assunto da conversa e com regras de não prometer, é melhor. Não regredir.
- **Base de conhecimento que só funciona se lembrar de citar a menção**: armadilha. A nossa entra por papel, sozinha.
- **Preço em créditos opaco** (o custo da mensagem varia com o tamanho do prompt e com as menções): se cobrarmos por
  consumo, mostrar em reais e por conversa.
- **Documentação com contradições** (horário comercial e follow-up; pré-requisito da importação). Lição para a nossa
  ajuda: uma regra, um lugar.

---

## 5. Ideias de experiência que valem trazer

1. **Checklist de onboarding que se marca sozinho** (dados do escritório, conectar Helena, ZapSign, primeiro agente,
   primeiro teste), com o passo seguinte sempre visível. Liga com `app/gestao/onboarding.py` e `DASHBOARD_IA.md` 4.3.
2. **Item quebrado em vermelho** no editor e bloqueio ao publicar, com a lista do que corrigir (já desenhado).
3. **"Dúvidas frequentes" curtas no fim de cada tela** do painel (3 perguntas, 1 linha cada), em vez de manual longo.
4. **Páginas de diagnóstico com nome do problema**: "A IA pulou uma pergunta" (conflito inicial), "A IA inventou"
   (alucinação), "A IA avisou que ia transferir e parou". Cada uma com causa, correção e "teste de novo no
   Laboratório". Ótimo para o suporte mandar o link.
5. **Tabela de erros com a ação** (código da Helena/Meta → o que fazer), ligada à tela Erros.
6. **Laboratório com o que "teria acontecido"** (moveria o card, poria a etiqueta) e custo em R$ por mensagem, mais
   o botão Resetar (C7). O deles é só `/restart`; o nosso pode ser bem melhor.
7. **Custo de referência na tela de consumo** ("uma conversa média custa R$ X; a sua está em R$ Y"), para o escritório
   saber se está normal.
8. **Templates de agente com "quantos escritórios usam" e "como testar"** na Biblioteca.
9. **Botão "isso ajudou?" por tela de ajuda** para medir onde o texto falha (sem formulário externo).
10. **Plantão ao vivo** em horário fixo para clientes novos e grupo de clientes: barato e reduz tickets.
11. **Índice da nossa ajuda em `llms.txt`** e um assistente de dúvidas na própria ajuda, se publicarmos documentação.
12. **Explicar o "porquê" das travas** em linguagem simples (ex.: "ação em massa não dispara follow-up para proteger
    seu número"), como eles fazem.

---

## Arquivos lidos do nosso lado

`docs/ACOES_COM_ARROBA.md`, `docs/DASHBOARD_IA.md`, `docs/HELENA_CAPACIDADES.md`, `docs/ZAPSIGN_CAPACIDADES.md`,
`docs/BASE_DE_CONHECIMENTO.md`, `docs/AGENTE_TRIAGEM.md`, `docs/RASTREAMENTO_E_FILTROS.md`,
`docs/REGRAS_DO_MOTOR_E_CAMPOS.md`, `docs/ADMIN_WEAVER_PARA_NOSSO.md`, `docs/PLANO_PAINEL_CUSTO_DEPLOY.md`,
`docs/FLUXO_CONTRATO.md` (cabeçalhos e seções principais); código: `app/ia_controle.py`, `app/pipeline.py`
(pausa do atendente, motivos de não atender), `app/followup/regras.py` e `servico.py`, `app/horario.py`,
`app/consumo.py`, `app/central_avisos.py`, `app/notificacoes.py`, `app/origem.py`, `app/gestao/laboratorio.py`,
`app/gestao/onboarding.py`, `app/banco/tipos.py`.
