# Dashboard da IA dentro do painel

Documento de desenho para o dono do produto. Mostra como levar para o nosso painel (IA de atendimento) o dashboard que já existe no projeto "Buscar da helena", agora ligado ao agente: rastreio de cada conversa até o anúncio, central de avisos, análise de campanhas, follow-up, execuções e custo.

Nada foi alterado no código para escrever este documento. Só leitura dos dois projetos, sem chamar a Helena, o Supabase ou a OpenAI.

---

## Resumo em dez linhas

1. O dashboard atual calcula tudo **no navegador**: baixa todos os cards e sessões do cliente direto do Supabase com a chave pública e soma ali. No nosso painel, quem calcula é a **FastAPI, com SQL agregado**, e o escritório vem da sessão do usuário, nunca da URL.
2. O visual vale copiar quase inteiro (cards de KPI, cards por etapa, funil, melhores anúncios, barra de filtros, central de notificações). A camada de dados e o login **não** valem copiar.
3. Temos duas fontes: **as nossas tabelas** (`agentesia_*`: lead, etapa da IA, origem do anúncio, contratos, follow-up, custo) e **o CRM da Helena** (cards, etapas, responsáveis, etiquetas, sessões com UTM). Elas se ligam pela tabela `agentesia_crm_cards` (lead e card), pelo contato da Helena e pela sessão.
4. Criamos uma **fase canônica do funil** (8 fases, as mesmas dos prints) e um mapa por escritório que traduz para ela tanto as etapas do nosso agente quanto as etapas do CRM. Assim todas as telas mostram o mesmo número.
5. **MVP sem nada novo da Helena**: funil, KPIs, cards por etapa e melhores anúncios só com os leads que a IA atendeu (já temos origem, etapa e contrato), mais a central de avisos lendo o que o motor já dispara.
6. Depois, um **espelho do CRM da Helena** no nosso banco (webhook de card como caminho principal, sync incremental de reserva reaproveitando a lógica do `server.js`, com token no Vault e teto de cota que deixa a maior parte para o atendimento). Só então entram os filtros Painel CRM, Responsável e Tags, e o modo "CRM inteiro".
7. A **central de avisos** vira uma caixa de entrada de verdade (novas, minhas, resolvidas), com tipo canônico em vez de texto, ligada aos avisos de WhatsApp que já temos.
8. A aba **Follow-up** mostra o agente responsável (que no nosso motor é um agente de verdade, com regras por etapa), a fila, e os resultados até o contrato.
9. **Ativação de conta**: hoje a LawChat cadastra à mão e o cliente entra pelo botão da Helena. Propomos um onboarding guiado e corrigir antes alguns buracos de segurança da entrada.
10. Plano em fases curtas (0 a 7), com a segurança da entrada na fase 0 e a ordem das migrações combinada com o plano de custo e execuções e com o rastreamento.

**Revisão (25/11/2026)**, depois de conferir com o código e com os prints:

- **Segurança da entrada vem antes do dashboard**: as correções do botão da Helena saíram da fase 6 e foram para a fase 0, porque o dashboard põe dado comercial dentro do iframe da Helena.
- **Não duplicar o que já existe**: o painel já tem a tela Funil (`repositorio.funil`, com "etapa mais adiante alcançada" pelos turnos) e o Início já soma follow-up, assinados e UF (`metricas.py`). O `RASTREAMENTO_E_FILTROS.md` já propõe `BarraDeFiltros.tsx`, `app/gestao/filtros.py`, `agentesia_v_leads` e a lista fechada de motivos de perda. O dashboard usa essas peças, não cria versões paralelas.
- **A cota da Helena é uma só por conta (1.000 chamadas a cada 5 min) e é dividida com o motor que atende o lead**. O sync tem orçamento fixo e cede a vez ao atendimento.
- **Limite do MVP**: sem o espelho do CRM, o que a equipe faz na Helena depois que a IA passa o lead (mover card, assinar fora da ZapSign) não aparece. O MVP precisa dizer isso na tela.

---

## 1. Visão geral e telas

### 1.1 Onde fica no menu

Um grupo novo no menu lateral, **Resultados**, com as telas abaixo. As telas que já existem (Início, Conversas, Avisos, Erros) continuam onde estão. Quando a tela nova cobrir a antiga, a antiga vira atalho.

| Tela | Rota no painel | Quem vê | Substitui ou completa |
|---|---|---|---|
| Dashboard | `/resultados` | gestor, dono, admin LawChat | Completa o Início (o Início fica como resumo do dia) |
| Rastreio de anúncios | `/resultados/anuncios` e `/resultados/anuncios/:chave` | gestor, dono | Novo |
| Campanhas | `/resultados/campanhas` | gestor, dono | **Substitui a tela Funil atual** (`Funil.tsx`): o "agrupar por" e os filtros que o `RASTREAMENTO_E_FILTROS.md` previa para o Funil moram aqui. `/funil` vira atalho. Um endpoint só, não dois |
| Central de avisos | `/avisos` (caixa de entrada) e `/avisos/config` (o que existe hoje) | todos; "minhas" por usuário | A tela Avisos atual vira a aba de configuração |
| Follow-up | `/resultados/followup` e a seção do agente que já existe | gestor, dono | Completa `AgenteFollowup.tsx` |
| Execuções e erros | `/execucoes`, `/erros` | gestor, admin | Frente B do `PLANO_PAINEL_CUSTO_DEPLOY.md` |
| Custo | `/consumo` | papéis que veem consumo | Frente A do mesmo plano |

O atendente não vê custo, como já é regra no `metricas.py` (`PAPEIS_QUE_VEEM_CONSUMO`).

**Reaproveitar, não duplicar**: a barra de filtros é a `painel/src/componentes/BarraDeFiltros.tsx` e o `where` sai de `app/gestao/filtros.py`, as duas peças do `RASTREAMENTO_E_FILTROS.md` (2.1). Conversas, Dashboard, Campanhas e Rastreio usam as mesmas. O Início continua com os números do dia, mas "contratos assinados" e "follow-up respondido" passam a vir da mesma função do dashboard (ver 3.0), para a mesma palavra não ter dois números.

### 1.2 Dashboard (igual ao print do dashboard atual)

De cima para baixo:

**a) Saudação e versão.** "Boa tarde, {nome do escritório}" e a data da última atualização dos dados (importante quando entrar o espelho do CRM: "CRM sincronizado há 12 min"). O subtítulo acompanha o período escolhido ("desempenho dos últimos 30 dias"); no atual ele diz "de hoje" mesmo com "Todo período", não copiar. Selo "Beta" opcional. No universo IA, uma faixa fixa explica o limite: "Mostra só os leads atendidos pela IA; o que a equipe fez na Helena depois da passagem entra quando o CRM for ligado".

**b) Barra de filtros** (mesmo desenho do `FiltersBar.tsx`). Todos os filtros vão para o endereço da página (query string), para dar para compartilhar o link e voltar com o botão do navegador.

| Filtro | Opções | De onde vem no MVP | Depois do espelho do CRM |
|---|---|---|---|
| Período | Hoje, Ontem, 7 dias, 30 dias, Este mês, Mês passado, Todo período, intervalo | `agentesia_leads.criado_em` | `criado_em_helena` do card |
| Modo | Criação / Atualização | Só Criação (data de entrada do lead). Atualização fica escondida até existir `agentesia_lead_historico` (migração 007, fase 3); os turnos não servem, porque a mudança feita por humano não gera turno | Atualização = `atualizado_em_helena` do card (qualquer mudança no card, não só de etapa: dizer isso no ícone de informação) |
| Universo (novo) | Atendidos pela IA / CRM inteiro | Só "Atendidos pela IA" | Os dois |
| Campanha | lista das campanhas do período | `origem->>'campanha'` | mais `utm_campaign` das sessões |
| Painel CRM | painéis liberados para o escritório | escondido | `agentesia_crm_paineis` |
| Etapa | as 8 fases canônicas (e, abaixo, as etapas de origem agrupadas por fase; o atual lista as etapas do CRM) | fase da etapa atual do lead | fase da etapa do card |
| Responsável | atendentes e agentes de IA | só agente de IA (`id_agente`); atendente humano depende dos campos de atendente em `agentesia_mensagens` do rastreamento (fase 3) | `responsavel_nome` do card |
| Número | números do escritório | `agentesia_canais` | o mesmo, mais `channel_phone` das sessões |
| Origem | Facebook, Instagram, Google, Site, Orgânico, Outro | `origem->>'fonte'` e tipo da origem | mais `utm_source` das sessões |
| Tags | etiquetas da Helena | escondido | etiquetas do contato no espelho |

Botões: **Limpar**, **Atualizar** (só refaz a consulta; nunca dispara sync com a Helena) e **Minimizar**.

**c) Cinco KPIs**: Cards totais (no MVP o rótulo é "Leads"), Contratos assinados, Taxa de conversão, Taxa de eficiência, % qualificado. Definições na seção 3. Cada card tem o subtítulo do print ("no painel", "contratos assinados", "Total → Fechado", "Assinados / Avançaram do SDR", "N qualificados") e o ícone de informação com a fórmula escrita, em todos os cinco, não só na eficiência. A curva pequena de cada card **tem que ser dado real** (série por dia do período). No dashboard atual essas curvas são desenhos fixos; não copiar isso. Clique no KPI abre a lista dos leads que compõem o número.

Aviso de expectativa: o print mostra o CRM inteiro (dezenas de milhares de cards). No universo IA o total será bem menor, porque só conta quem a IA atendeu. Não é erro; o rótulo "Leads atendidos pela IA" precisa deixar isso óbvio.

**d) Oito cards por fase**: SDR, Closer, Análise manual, Confecção de contrato, Aguardando assinatura, Contrato assinado, Desqualificado, Não assinou. Contagem, % do total e curva por dia. Clique abre a lista filtrada pela fase.

**e) Funil de vendas** (3/5 da largura): as seis fases de avanço, sem Desqualificado e Não assinou. O funil é **acumulado** (cada barra conta quem está naquela fase ou em qualquer fase depois dela), com a taxa de passagem entre barras, o selo "Total N" no canto e, no rodapé, a conversão geral ("4,9% · 1.479 de 30.141"). Conferido no print: as barras batem com a soma dos cards por fase (SDR = total − Desqualificado − Não assinou).

**f) Melhores anúncios** (2/5 da largura): quatro mini-cards (total de leads com anúncio, média de leads por anúncio, melhor anúncio, conversão média), abas Leads / Contrato assinado, ordenação pela coluna (o print tem a seta em "Leads"), top 5 com pódio, "ver mais N anúncios" e **Exportar** (CSV com `;` e BOM, como o atual). Cada linha: id do anúncio, título do anúncio (o texto do criativo, cortado com reticências), plataforma, leads com barra, conversão com barra. No celular a tabela rola na horizontal dentro do card, nunca a página. No nosso painel cada linha leva para o detalhe do anúncio (1.3). O mini-card de conversão diz "dos leads", não "dos cliques" como no atual: não temos clique, só lead.

**g) Abaixo** (fase 3 em diante): tempo médio entre fases (com mediana), meta de vendas, evolução diária, leads por origem e mapa por UF (já temos `uf_do_telefone`), e a tabela de leads.

### 1.3 Rastreio de anúncios (novo, "cada conversa até o anúncio")

**Tabela por anúncio**, uma linha por anúncio (chave na seção 2.4):

| Coluna | O que é |
|---|---|
| Anúncio | título e id; ícone da plataforma |
| Campanha / conjunto / criativo | quando houver (ver 2.3e) |
| Produto | benefício anunciado, classificado pela IA (`origem.produto`) |
| Leads | leads distintos cujo primeiro toque foi este anúncio |
| Responderam | leads que mandaram ao menos uma mensagem **depois da primeira resposta da IA** (no anúncio de clique para WhatsApp a primeira mensagem é o texto pronto do anúncio, então ela não conta) |
| Qualificados | leads que chegaram a Closer ou depois |
| Contratos gerados / assinados | de `agentesia_contratos` |
| Conversão | assinados ÷ leads |
| Custo de IA | soma do custo das chamadas de IA desses leads |
| Custo de IA por lead e por contrato | custo ÷ leads, custo ÷ assinados |
| Gasto com anúncio, CPL, CAC | só quando houver gasto cadastrado (2.3f); sem isso a coluna fica escondida, com o aviso "custo do anúncio não informado" |
| Tempo até assinar | mediana, em dias |

**Detalhe do anúncio** (`/resultados/anuncios/:chave`): cabeçalho com título, link do anúncio, campanha e produto; mini-funil só desse anúncio; motivos de perda mais comuns; e a **lista de conversas** (nome, etapa atual, estado, assinou ou não, custo de IA, data de entrada). Clique na conversa abre a tela Conversas já existente, com a linha do tempo do lead (a partir da migração de rastreamento).

**Leads sem anúncio** aparecem numa linha "Sem anúncio identificado", para o total sempre bater com o Dashboard.

### 1.4 Campanhas

Mesmo conteúdo da aba Campanhas do projeto atual, calculado no servidor:

- agrupamento escolhível: campanha, conjunto, criativo, plataforma, produto do anúncio;
- funil por grupo, ranking, comparação lado a lado de até 4 grupos;
- **alertas de campanha** (regras do `CampaignAlerts` atual, que funcionam bem): mais de 5 leads e nenhum contrato (alta); desqualificação acima de 50% com mais de 3 leads (alta); conversão abaixo de 5% com mais de 5 leads (média). Esses alertas também entram na central de avisos como tipo `campanha`, uma vez por dia por campanha;
- tempo até converter por campanha (mediana);
- mapa de calor dia da semana × hora de entrada dos leads;
- atribuição de vários toques (primeiro, último, assistido) quando existir `agentesia_lead_toques`.

### 1.5 Central de avisos (igual ao print da central de notificações)

- Abas **Novas**, **Minhas**, **Resolvidas**.
- Círculo central com "N grupos aguardando" (um grupo = um lead com avisos abertos).
- Botões **Atualizar** e **Avisos no WhatsApp** (abre a configuração que já existe em `Avisos.tsx`).
- Filtro de período (Hoje, Ontem, 7d, 30d, Todos; abre em **Hoje**, como no print) e chips de tipo com contagem: **Assinado, Assinatura, Elaboração, Qualificado, Intervenção**, um sexto chip **Sistema** (erros de cadastro e consumo do próprio escritório, visível só para gestor e admin) e um sétimo **Campanha** (alertas da 1.4). Botão **Limpar** zera período e chips.
- Lista com o título de seção "Pendentes (N)" e estado vazio "Nenhuma notificação nesta aba", como no print. Na aba Resolvidas o círculo diz "N resolvidos", não "aguardando".
- Cada grupo mostra nome do lead, telefone mascarado, etapa, anúncio de origem, linha do tempo dos avisos, e botões: abrir conversa (na Helena e no painel), assumir, avaliar (novo, resolvendo, aguardando, resolvido), marcar como lida, resolver. Apagar só para admin e só como "arquivar".
- Trava anti-roubo igual à atual: só quem assumiu, o gestor ou o admin transferem.
- Cada ação gera uma linha de registro (quem, o quê, quando), base para uma futura tela de Supervisão.
- Atualização ao vivo por SSE (ou consulta a cada 15 s no MVP), **sempre filtrada pelo escritório no servidor**. Som opcional por tipo.

Mapa dos tipos (o nosso motor já produz esses eventos em `app/notificacoes.py`):

| Chip | Eventos do motor |
|---|---|
| Assinado | `contrato_assinado`, `etapa:contrato_assinado` |
| Assinatura | `etapa:assinatura`, `contrato_gerado`, `sinal:dificuldade_assinatura`, `sinal:foto_contrato`. **Novo**: "contrato gerado e não assinado depois de X horas" não existe no motor; precisa de uma tarefa agendada que crie o evento `assinatura_atrasada` |
| Elaboração | `etapa:coleta_dados`, `etapa:analise_manual`, `sinal:contrato_manual`, `sinal:analise_humana` |
| Qualificado | `etapa:closer` |
| Intervenção | `pediu_humano`, os demais `sinal:*` (não sabe ler, quer áudio, videochamada, cliente antigo, outro benefício, objeções, endereço), `trava`, `contrato_falhou`, `followup_desistiu` |
| Sistema | `ia_falhou`, `consumo_limite`, eventos de `agentesia_eventos` **com `id_escritorio` igual ao do escritório e `responsavel = 'cadastro'`** |
| (fora da central) | `lead_novo` e `etapa:desqualificado`: vão para o WhatsApp se o escritório quiser, mas não abrem item na caixa (seria um item por lead, sem ação a fazer) |

Tipo novo que não estiver no mapa cai em Intervenção e gera um evento `info` para alguém classificar. A classificação é pela **chave do evento**, nunca pelo texto (é o ponto fraco da central atual).

Eventos que o motor dispara em par (`contrato_gerado` + `etapa:assinatura` em `app/acoes.py`; `contrato_assinado` + `etapa:contrato_assinado`) viram **um** aviso: o anti-duplicado é por lead + categoria, não por chave de evento.

A central da equipe LawChat que já existe (`app/central_avisos.py`: erros da LawChat, do provedor e de cadastro de todos os escritórios, enviados ao WhatsApp da LawChat) **não** entra na caixa do escritório e continua como está (a tela Erros do admin já mostra esses eventos). `agentesia_avisos` tem `id_escritorio not null`; aviso sem escritório não existe nela. Só os eventos de cadastro do próprio escritório aparecem para o gestor.

### 1.6 Follow-up

No nosso motor o follow-up é enviado por nós, então "o agente responsável" é um agente de verdade (o `id_agente` do lead) com a configuração `config.followup` (prompt geral, instrução por etapa, passos, horário, desistência, modelo de IA).

A aba tem quatro blocos:

1. **Responsável e regras**: por agente, mostra se o follow-up está ligado, o horário, os passos (1h, 5h, 24h...), a instrução por etapa e o modelo. Botão "editar" leva para a seção do agente que já existe (`AgenteFollowup.tsx`).
2. **Fila**: próximos envios (`agentesia_followups` pendentes), com lead, passo, horário agendado e motivo se adiado. Ação: cancelar um envio.
3. **Resultados**: enviados, respondidos, taxa de resposta, tempo até responder (mediana), leads que **avançaram de fase** depois de um follow-up, **contratos assinados** depois de um follow-up, desistências. Por passo da cadência e por etapa.
4. **Histórico**: últimos envios com o texto enviado e o que aconteceu depois.

Lacuna encontrada e que precisa de decisão: o modelo de follow-up do catálogo de produtos (`padrao_followup.agentes`, editado no admin) parece **não ser copiado** para o agente quando o produto é ativado (`app/gestao/produtos.py` devolve `followup=None`). É defeito do produto, não do dashboard: a correção entra já na fase 1, separada.

Não duplicar: o Início já conta pendentes, enviados e respondidos (`metricas.py`), com "respondido" = qualquer mensagem do lead depois do envio, sem limite de tempo. A aba Follow-up e o Início passam a usar **uma** função com a definição da 3.6.

### 1.7 Execuções, erros e custo

Não desenhamos de novo aqui: são as frentes A (custo por mensagem, etapa, lead) e B (Execuções e Erros) do `docs/PLANO_PAINEL_CUSTO_DEPLOY.md`. O Dashboard depende de duas peças delas:

- `agentesia_chamadas_ia.id_lead` (A1/A2), para o custo de IA por anúncio e por contrato;
- erros com `id_turno` (B1), para a central de avisos mostrar "o que falhou" ligado ao lead.

---

## 2. Dados

### 2.1 O que já temos nas nossas tabelas

| Tabela | O que dá para o dashboard |
|---|---|
| `agentesia_leads` | lead, escritório, canal (número), agente, etapa atual (`id_etapa`), estado e motivo, `origem` (primeiro toque do anúncio), `id_sessao_helena`, datas |
| `agentesia_contatos` | `id_contato_helena`, telefone normalizado |
| `agentesia_agente_etapas` | código da etapa (`sdr`, `closer`...), ordem, tipo (conversa ou terminal) |
| `agentesia_turnos` | etapa antes e depois em cada turno (dá para montar o passado das trocas de fase) |
| `agentesia_mensagens` | autor (lead, ia, humano, automação), horários: resposta, tempo de primeira resposta |
| `agentesia_contratos` | gerado, assinado, cancelado, com datas |
| `agentesia_crm_cards` | **a ponte** lead ↔ card da Helena (`id_card_helena`, `id_painel_helena`, `id_etapa_helena`) |
| `agentesia_followups` | fila e envios de follow-up |
| `agentesia_chamadas_ia` | tokens e custo (sem `id_lead` ainda) |
| `agentesia_eventos` | erros e problemas, com "resolver" |
| `agentesia_acoes` | fila de ações, inclusive `notificar` (cada aviso que foi para o WhatsApp) |
| `agentesia_notificacoes` | configuração dos avisos por tipo de evento |

### 2.2 O que vem da Helena e como entra

**O que precisamos da Helena** (só o que o dashboard usa):

| Recurso | Endpoint (o mesmo que o `server.js` já usa) | Para quê |
|---|---|---|
| Painéis e etapas | `GET /crm/v1/panel` e `/crm/v1/panel/{id}?IncludeDetails=Steps` | filtro Painel CRM, mapa etapa → fase |
| Cards | `GET /crm/v1/panel/card?PanelId&UpdatedAt.After&IncludeDetails=StepTitle,StepPhase,PanelTitle,ResponsibleUser,CustomFields,Contacts` | universo "CRM inteiro", etapa, responsável, valor |
| Contatos | `GET /core/v1/contact` (lote) | etiquetas, UTM do contato |
| Sessões | `GET /chat/v2/session?IncludeDetails=...` (lote, ~100 por requisição) | número do canal, atendente, UTM da sessão |
| Atendentes | `GET /core/v1/agent` | filtro Responsável, "Minhas" na central |

**Como entra: um worker de sync nosso**, em Python, rodando no app "IA" (ou no worker de fila, conforme a frente D do plano de deploy), não no navegador. Copiamos do `server.js` a **lógica**, não o código:

1. **Webhook primeiro**: o que já recebemos (mensagens, etiqueta do contato, TRACK de anúncio) atualiza na hora o que é nosso. Os eventos de CRM **existem** (`PANEL_CARD_NEW`, `PANEL_CARD_UPDATE`, `PANEL_CARD_STEP_CHANGE`, ver `HELENA_CAPACIDADES.md` seção 4) e custam zero da cota de leitura, então são o caminho principal para o card; o incremental vira rede de segurança. Cuidados: a assinatura vale para a conta inteira e pode ser volumosa (medir num piloto antes), e esses eventos vão para uma fila própria, **nunca** processados no mesmo caminho das mensagens que o lead espera resposta. Assinar `SESSION_UPDATE` também traz atendente e encerramento sem consulta.
2. **Incremental a cada 30 a 60 min por escritório** (15 min só se o webhook de card não estiver ligado), num minuto fixo por escritório (hash do id, como o `server.js`), com no máximo 4 escritórios ao mesmo tempo:
   - cards por `UpdatedAt.After` = último cursor salvo menos 5 min (o cursor fica numa tabela, não em memória, e **não** é limitado à meia-noite);
   - sessões e contatos em lote, das páginas mais novas para trás, parando depois de 2 páginas sem novidade (a listagem é `ASCENDING`: ler a contagem na 1ª página e começar pela última);
   - sessão por id **só** para card novo ou que trocou de contato, com teto de 50 por rodada; o resto espera a próxima rodada ou a reconciliação. Nunca uma chamada por card em carga grande (30 mil cards = 30 mil chamadas = cota de 2,5 horas da conta inteira).
3. **Reconciliação noturna às 3h de Brasília** (`America/Sao_Paulo` fixo): **só cards**, listados com o mínimo de `IncludeDetails` (id, etapa, atualizado em), cerca de 1 chamada por 100 cards; marca como apagados os cards que sumiram da listagem, com a trava do atual (aborta se sumir mais de 20% ou mais de 25 cards). Grava só o que mudou (compara `atualizado_em_helena`), para não reescrever 30 mil linhas toda noite. Sessões e contatos não têm varredura completa diária; no máximo semanal, fatiada. Nunca confirmar card morto pelo GET de detalhe (a Helena responde 200 com o card que sobreviveu à fusão).
4. **Primeira carga** ao ativar o escritório: completa, **retomável** (cursor de página na `agentesia_crm_sync`) e dentro do orçamento abaixo; por isso pode levar dezenas de minutos num escritório grande. Barra de progresso na tela de ativação.

**Orçamento da cota (o ponto mais importante)**: a Helena permite **1.000 chamadas a cada 5 min e 200 a cada 5 s por conta**, somando tudo: o nosso motor respondendo leads (cerca de 10 chamadas por turno), o follow-up, o n8n antigo se ainda ligado e o `server.js` do dashboard antigo. O sync é o menos urgente, então:

- teto do sync: **300 chamadas a cada 5 min e 40 a cada 5 s por conta** (ajustável por escritório), o resto fica para o atendimento;
- se o motor receber um 429, o sync daquela conta para por 10 min;
- primeira carga e reconciliação só fora do horário de atendimento do escritório, quando possível;
- o botão "sincronizar agora" do admin passa pelo mesmo limitador e não pode ser apertado de novo enquanto a rodada anterior não terminar.

**Endpoints**: o `server.js` usa `crm/v1`; o nosso código (`helena_conta.py`) já usa `crm/v2` e `crm/v3`. Usar a versão que o nosso cliente já usa e conferir os nomes dos parâmetros (`UpdatedAt.After`, `IncludeDetails`) nela.

**Custo de banco do espelho**: guardar o jsonb bruto só dos cards (ajuda a depurar). Sessões e contatos guardam só as colunas usadas; o bruto de sessão pode trazer muita coisa e multiplica o tamanho do banco por escritório.

Regras que levamos do atual e regras que corrigimos:

| Levar | Corrigir |
|---|---|
| Upsert com `COALESCE` para não apagar dado bom quando a listagem vem pobre | Erro em uma página **não** marca como sincronizado: grava a falha e tenta de novo |
| `jsonb` bruto guardado separado das colunas | Cursor e trava no banco (tabela `agentesia_crm_sync`), não em memória |
| Backfill do número do canal nas sessões | Respeitar `Retry-After` do 429, com espera crescente, sem prender a vaga por 28 min |
| Escalonamento por minuto e lote de 4 | Um **limitador por conta** no nosso Postgres (a ideia de `helena-fetch-all/_sql/rate_limit.sql`), usado pelo sync **e** pelo motor, com prioridade para o motor. Com o `server.js` não dá para dividir (banco diferente): ver "Atenção" abaixo |
| Espera fixa de 4 min no 429 (`LIMIT_WAIT_MS`) | Espera crescente e sync da conta pausado, sem segurar vaga de outros escritórios |
| Log de cada rodada | Token sempre lido do Vault, por escritório |

**Atenção**: enquanto o dashboard antigo estiver ligado, os dois syncs batem na mesma conta Helena. O limitador em Postgres só é "único" se os dois lerem **o mesmo banco**; o dashboard antigo tem o seu próprio Postgres, então, na prática, não dá para dividir a cota por ele sem mexer no `server.js`. Regra: **para cada escritório migrado, desligar o sync antigo daquele escritório antes de ligar o nosso**. Se os dois precisarem rodar juntos, cada um fica com teto fixo (ex.: 200 + 200 a cada 5 min), configurado nos dois lados.

**Alternativa de curto prazo** (decisão do dono, ver seção 7): ler em modo só leitura o banco do dashboard antigo, que já tem `helena_cards` e `helena_sessions`. É mais rápido, mas herda as fraquezas do sync antigo (sessões antigas só atualizam à noite, funil por título da etapa, cliente identificado por `helena_company_id` numa tabela sem isolamento). Recomendação: usar só para validar números na fase 4, não como fonte permanente.

### 2.3 Tabelas e views novas

Tudo aditivo, com arquivo de desfazer e teste, como as migrações anteriores. **Numeração**: já existem 001 a 004 (`004_agentesia_canal_liberado`). O `RASTREAMENTO_E_FILTROS.md` propõe uma "004" e o `PLANO_PAINEL_CUSTO_DEPLOY.md` propõe "003" e "004"; todas precisam ser renumeradas. Sugestão de ordem (ajustar se outra frente pegar um número antes):

| Migração | Conteúdo | Dono |
|---|---|---|
| 005 consumo | colunas de atribuição em `agentesia_chamadas_ia` (inclui `id_lead`) | plano de custo (A1) |
| 006 execuções | campos de erro em turnos, índices | plano de custo (B1) |
| 007 rastreamento | histórico do lead, marcos, toques, anúncios, gasto, `agentesia_v_leads` | `RASTREAMENTO_E_FILTROS.md` |
| 008 painel | fases canônicas, central de avisos, índices do dashboard | este documento |
| 009 espelho CRM | tabelas do espelho da Helena e cursores de sync | este documento |

**008 painel**

a) `agentesia_fases_funil` (tabela de referência, igual para todos):
`codigo` (`sdr`, `closer`, `analise_manual`, `confeccao_contrato`, `aguardando_assinatura`, `contrato_assinado`, `desqualificado`, `nao_assinou`), `nome`, `ordem`, `tipo` (`avanco` ou `perda`), `qualificado` (true de `closer` a `contrato_assinado`), `cor`.

b) `agentesia_mapa_fases` (por escritório):
`id_escritorio`, `origem` (`etapa_agente` ou `etapa_crm`), `id_origem` (id da etapa do agente ou `step_id` da Helena), `fase`, `definido_por` (`automatico` ou `usuario`), `atualizado_em`. Único por `(id_escritorio, origem, id_origem)`.
Preenchimento: os códigos das etapas do agente **não** são as 8 fases (o banco tem `sdr`, `periodo_graca`, `closer`, `coleta_dados`, `assinatura`, `analise_manual`, `desqualificado`, `contrato_assinado` e outros, livres por agente). Por isso: um dicionário padrão em Python (ex.: `periodo_graca` → `sdr`, `coleta_dados` → `confeccao_contrato`, `assinatura` → `aguardando_assinatura`), aplicado na criação da etapa; etapa sem correspondência fica **sem fase** e o gestor escolhe numa tela simples "Mapear etapas" que entra já na **fase 1** (não só com o CRM). Enquanto houver etapa sem fase, o dashboard mostra "N leads em etapas sem fase" para o total continuar batendo. Para etapas do CRM, sugestão a partir do título, **confirmada pelo gestor**. É a **única fonte da fase**; o título da etapa nunca decide sozinho.

c) `agentesia_avisos` (a caixa de entrada):
`id`, `id_escritorio`, `id_lead`, `tipo_evento` (chave do motor, ex.: `contrato_assinado`), `categoria` (`assinado`, `assinatura`, `elaboracao`, `qualificado`, `intervencao`, `sistema`, `campanha`), `titulo`, `resumo`, `dados` jsonb (etapa, anúncio, link da conversa), `situacao` (`novo`, `resolvendo`, `aguardando`, `resolvido`, `arquivado`), `id_usuario_responsavel`, `assumido_em`, `lido_em`, `lido_por`, `resolvido_em`, `resolvido_por`, `id_acao_whatsapp` (a ação `notificar` que mandou no grupo, se houve), `resultado_whatsapp` (enviado, falhou, desligado), `criado_em`.
Índices: `(id_escritorio, situacao, criado_em desc)`, `(id_escritorio, id_usuario_responsavel) where situacao <> 'resolvido'`, `(id_lead)`.
Anti-duplicado: mesmo lead + mesma `categoria` com aviso aberto (ou criado nas últimas 24 h) atualiza aquele aviso e acrescenta o evento na linha do tempo dele, em vez de criar outro.

d) `agentesia_avisos_registro`: `id_aviso`, `id_usuario`, `acao` (assumir, transferir, avaliar, ler, resolver, arquivar), `de`, `para`, `criado_em`.

e) Índices do dashboard em `agentesia_leads`: `(id_escritorio, criado_em desc)`, `(id_escritorio, id_etapa)`, `(id_escritorio, ((origem->>'id_anuncio')))`, `(id_escritorio, ((origem->>'campanha')))`. Alguns já estão na 007; não duplicar.

f) View: **uma só**, a `agentesia_v_leads` do `RASTREAMENTO_E_FILTROS.md` (1.3h). Se a fase 1 vier antes da 007, a 008 cria `agentesia_v_leads` com as colunas abaixo e a 007 a estende (não existem duas views). Uma linha por lead com `id_escritorio`, `id_lead`, `id_canal`, `id_agente`, `fase` (via mapa), `qualificado`, `assinado`, `assinado_em`, `chave_anuncio`, `id_anuncio`, `campanha`, `fonte`, `produto`, `custo_ia_usd`, `criado_em`, `fase_mudou_em`. Todas as consultas do dashboard leem dela; filtro vira `where` montado por `app/gestao/filtros.py`. A coluna `fase` já aplica a ordem de precedência da 3.0, então "assinado" e "fase = contrato_assinado" nunca divergem.

**009 espelho do CRM** (prefixo `agentesia_crm_`, sempre com `id_escritorio`):

| Tabela | Colunas principais | Chave |
|---|---|---|
| `agentesia_crm_paineis` | `id_painel_helena`, título, etapas jsonb | `(id_escritorio, id_painel_helena)` |
| `agentesia_crm_cards_espelho` | `id_card_helena`, painel, `id_etapa_helena`, título da etapa, responsável (id e nome), valor, `ids_contatos_helena` text[], `ids_etiquetas` text[], campos personalizados jsonb, arquivado, `criado_em_helena`, `atualizado_em_helena`, `visto_em`, `apagado_em`, bruto jsonb | `(id_escritorio, id_card_helena)` |
| `agentesia_crm_contatos` | `id_contato_helena`, telefone normalizado, etiquetas (ids e nomes), UTM jsonb, `atualizado_em_helena` | `(id_escritorio, id_contato_helena)` |
| `agentesia_crm_sessoes` | `id_sessao_helena`, `id_contato_helena`, `id_card_helena`, número do canal, atendente (id e nome), departamento, UTM jsonb (e colunas `utm_source`, `utm_campaign`, `utm_source_id` para índice), datas | `(id_escritorio, id_sessao_helena)` |
| `agentesia_crm_atendentes` | `id_usuario_helena`, nome, e-mail, perfil, dono/supervisor | `(id_escritorio, id_usuario_helena)` |
| `agentesia_crm_sync` | recurso (cards, contatos, sessões, atendentes), cursor (página e `atualizado_em`), trava com validade, última rodada, último erro, contagens | `(id_escritorio, recurso)` |

O nome `agentesia_crm_cards_espelho` evita confusão com a `agentesia_crm_cards` que já existe (essa é a ponte do lead da IA com o card que ele criou ou moveu). Telefone não vai para colunas extras sem necessidade; o bruto fica no jsonb e some quando o escritório for apagado (`on delete cascade`).

### 2.4 Como juntar

```
agentesia_leads ──(id)──> agentesia_crm_cards ──(id_card_helena)──> agentesia_crm_cards_espelho
       │                                                                   │
       ├──(id_contato)──> agentesia_contatos ──(id_contato_helena)──> agentesia_crm_contatos
       │                                   └──(telefone_normalizado, reserva)
       └──(id_sessao_helena)──> agentesia_crm_sessoes ──(id_card_helena)──┘
```

Ordem de prioridade para ligar um lead da IA a um card do CRM:

1. `agentesia_crm_cards.id_card_helena` (o card que o nosso motor criou ou moveu);
2. o card cujas `ids_contatos_helena` contêm o `id_contato_helena` do lead, no painel configurado do escritório;
3. a sessão `id_sessao_helena` do lead e o `id_card_helena` dessa sessão;
4. por último, o telefone normalizado (nunca comparar só os 8 últimos dígitos, como faz o `server.js`).

Todos os quatro passos rodam **dentro do mesmo `id_escritorio`**; nenhum join do espelho pode ser feito só por id da Helena ou por telefone. Hoje `agentesia_crm_cards.id_card_helena` é único no banco todo e `id_conta_helena` é único por escritório (uma conta Helena = um escritório), o que ajuda, mas a consulta não deve depender disso.

**Chave do anúncio** (uma só, usada em todas as telas): o `id_anuncio` (sourceId do TRACK, já calculado em `app/origem.py` por `chave_do_anuncio`). Sem id de anúncio: `campanha`. Sem campanha: `fonte`. Sem nada: "Sem anúncio identificado". Para cards do CRM que a IA não atendeu: `utm_source_id` da sessão mais antiga do card; se não houver, `utm_campaign`.

**Primeiro toque manda.** Um lead conta em um anúncio só (o primeiro). Isso evita o problema do ranking atual, em que um card com várias sessões conta em vários anúncios. A atribuição de vários toques fica numa visão separada na aba Campanhas.

### 2.5 Multi-escritório e isolamento

- Toda consulta recebe `id_escritorio` do **contexto da sessão** (`ctx.escritorio()`), nunca de parâmetro da URL. O admin LawChat escolhe o escritório pelo seletor que já existe.
- Toda tabela nova tem `id_escritorio not null` com `on delete cascade` e índice começando por ele.
- O navegador **não** fala com o Supabase direto. Nada de chave pública, Realtime aberto ou `select('*')` no front (no dashboard atual isso pode expor o token da Helena e os dados de outros clientes).
- RLS ligada nas tabelas novas negando tudo para `anon` e `authenticated`; só o papel do backend acessa.
- O aviso em tempo real (SSE) é por escritório e por usuário no servidor.
- Exportação CSV só para gestor e dono, com telefone mascarado por padrão.
- **Cache de 60 s**: a chave é (escritório, papel, usuário quando a tela tiver "minhas", filtros). Sem o papel, um atendente receberia do cache a resposta com custo montada para o gestor; sem o escritório, o admin que troca de escritório no seletor veria o anterior.
- **Tabelas de anúncio** (`agentesia_anuncios`, `agentesia_gasto_anuncios`, da 007) também por escritório: dois escritórios podem anunciar com o mesmo id de anúncio em teste ou agência; título e gasto de um não podem aparecer para o outro.
- **Eventos sem escritório** (`agentesia_eventos` com `id_escritorio` nulo, os da LawChat e do provedor) nunca entram em consulta do escritório; o filtro é `id_escritorio = $1`, não `id_escritorio = $1 or id_escritorio is null`.
- **Pedidos de acesso** (4.3) não têm escritório ainda: ficam numa tabela da plataforma que só o admin LawChat lê, nunca na caixa de avisos de um escritório.
- Teste de isolamento em **cada** rota nova (`/api/painel/*`, `/api/avisos/*`, CSV e SSE): usuário do escritório A pedindo com id de lead, aviso ou anúncio do escritório B recebe 404.

---

## 3. Cada métrica dos prints: definição e de onde sai

Regras para todas:

- Fuso `America/Sao_Paulo`.
- Modo Criação: conta os leads (ou cards) **criados** no período, na fase em que estão hoje (é o que o dashboard atual faz). Modo Atualização: conta os que **mudaram** no período.
- Cards arquivados no CRM ficam fora, como no atual.
- "Fase" = fase canônica via `agentesia_mapa_fases`.
- Universo IA: base `agentesia_v_leads`. Universo CRM: base `agentesia_crm_cards_espelho` com a fase do mapa. O universo IA conta **leads**; o CRM conta **cards** (um contato com dois cards conta dois, como no atual). O rótulo muda junto ("Leads" ou "Cards").

### 3.0 Fase de cada lead: ordem de precedência

Sem regra única, o KPI "Contratos assinados" e o card "Contrato assinado" dão números diferentes, e a soma dos 8 cards deixa de dar o total. A coluna `fase` da view segue esta ordem, a primeira que valer:

1. contrato com situação `assinado` em `agentesia_contratos` → `contrato_assinado`;
2. contrato cancelado, ou gerado e não assinado depois do prazo do escritório (decisão 7.4) → `nao_assinou`;
3. lead encerrado com `motivo_perda` (lista fechada do `RASTREAMENTO_E_FILTROS.md` 1.5) diferente de `nao_respondeu` → `desqualificado`. Até a 007 existir: etapa de código `desqualificado` ou `motivo_estado` começando por `desqualificado`;
4. com o espelho ligado e card ligado ao lead (2.4): a fase da etapa do card, **se for mais adiante** que a do agente (a equipe moveu depois da passagem). Se o card estiver numa fase de perda, vale a perda;
5. a fase da etapa atual do agente pelo mapa; etapa sem fase → `sem_fase` (contada à parte, 2.3b).

Leads encerrados por outro motivo (sem resposta ao follow-up, pediu para parar, engano) **ficam na fase em que pararam**, como um card esquecido no CRM. Isso infla o SDR; por isso o card SDR mostra, no subtítulo, "N parados" (encerrados ou sem mensagem há mais de 7 dias).

"Contratos assinados" tem **dois sentidos** e o painel já usa os dois: o Início conta por **data da assinatura** (`assinado_em` no período, `metricas.py`); o dashboard, no modo Criação, conta os leads **criados** no período que estão assinados hoje. Os rótulos ficam distintos: "Assinados no período" (Início, e modo Atualização) e "Assinados dos leads do período" (modo Criação). A função que calcula é uma só.

Custo de IA fica em dólar (`custo_usd`) como no resto do painel; se mostrar em real, a cotação usada aparece na tela.

### 3.1 KPIs

| Métrica | Definição exata | No nosso modelo |
|---|---|---|
| Cards totais (Leads no universo IA) | quantidade no período, sem arquivados | `count(*)` na base filtrada |
| Contratos assinados | quantos estão na fase `contrato_assinado` | universo IA: `fase = 'contrato_assinado'` pela precedência da 3.0 (o contrato assinado já força a fase, então não há "ou"). Universo CRM: fase do card. Limite do MVP: assinatura feita fora da ZapSign só aparece com o espelho |
| Taxa de conversão | assinados ÷ total | as duas contagens acima |
| Taxa de eficiência | assinados ÷ quem **avançou do SDR** = assinados ÷ (total − SDR − Desqualificado) | o denominador inclui Não assinou, como no atual. Mostrar a fórmula no ícone de informação |
| % lead qualificado | quem está de Closer em diante ÷ total; fases com `qualificado = true` (closer, análise manual, confecção de contrato, aguardando assinatura, contrato assinado) | `count(*) filter (where qualificado)` ÷ total. Subtítulo: "N qualificados" |
| Curva de cada KPI | o mesmo número calculado por dia do período, agrupado pelo dia de **criação** do lead (modo Criação) | `generate_series` por dia, mesma consulta agrupada. Com "Todo período", agrupar por semana ou mês para não desenhar centenas de pontos |

Com a migração 007, passamos a oferecer também a versão "safra" ao clicar no KPI: "dos leads que entraram no período, quantos **chegaram** a assinar", usando `qualificado_em` e `contrato_assinado_em` em vez da fase atual. Fica claro no rótulo qual das duas está na tela.

### 3.2 Cards por fase

| Card | Definição | % mostrado |
|---|---|---|
| SDR, Closer, Análise manual, Confecção de contrato, Aguardando assinatura, Contrato assinado, Desqualificado, Não assinou | contagem de leads (ou cards) **hoje** naquela fase | ÷ total do período |

No universo IA, a fase segue a precedência da 3.0. Lead pausado por humano conserva a fase da etapa em que parou. A soma dos 8 cards mais "sem fase" é sempre igual ao total (teste automático).

`nao_assinou` depende do relógio (o prazo vence sem nenhum evento novo), então a view calcula com `now()`; o número de ontem pode mudar hoje sem ninguém mexer. Dizer isso no ícone de informação do card.

### 3.3 Funil de vendas

- Usa as seis fases de avanço, na ordem.
- **Acumulado**: barra da fase N = leads em N + leads em todas as fases depois de N. Assim a barra SDR = total − Desqualificado − Não assinou.
- Selo entre barras = barra N ÷ barra N−1.
- Percentual dentro da barra = barra ÷ total.
- Rodapé "Conversão geral" = assinados ÷ total (o mesmo número da Taxa de conversão).
- Largura das barras: proporcional ao valor com mínimo de 40% (o atual usa larguras fixas; proporcional informa mais, mas deixar fixo é aceitável se o dono preferir o visual idêntico).

Observação para não confundir: o acumulado supõe que quem está numa fase passou pelas anteriores. O funil "real" (quem de fato passou por cada fase) **já existe** na tela Funil atual: `repositorio.funil` calcula a etapa mais adiante alcançada pelos turnos (`agentesia_turnos.etapa_depois`). Reaproveitar essa consulta, traduzida para fases, como segunda opção já na fase 1; a linha do tempo da 007 só a completa com as mudanças feitas por humano.

### 3.4 Melhores anúncios

| Métrica | Definição | No nosso modelo |
|---|---|---|
| Leads do anúncio | leads distintos com aquela chave de anúncio (primeiro toque) | `count(*) group by chave_anuncio` |
| Contratos do anúncio | leads do anúncio com `assinado` | `count(*) filter (where assinado)` |
| Conversão do anúncio | contratos ÷ leads do anúncio | divisão |
| Plataforma | Facebook, Instagram, Google, Outro, a partir da fonte | `origem->>'fonte'` normalizada (mesma regra do `classifySource`). **A confirmar**: `app/origem.py` tira a fonte de `source`, `utm_source` ou `sourceType`; o TRACK do anúncio de clique para WhatsApp pode não separar Facebook de Instagram. Se não separar, mostrar "Meta" em vez de chutar |
| Total de leads (mini-card) | soma dos leads com anúncio identificado | soma |
| Média por anúncio | total de leads ÷ número de anúncios | divisão |
| Melhor anúncio | o de mais leads (aba Leads) ou mais contratos (aba Contrato assinado) | `order by ... limit 1` |
| Conversão média | **ponderada**: total de contratos ÷ total de leads com anúncio. O atual usa a média simples das taxas, que engana quando há anúncio pequeno com 100%. Se o dono quiser manter a simples, mostrar as duas | soma ÷ soma |
| Ver mais N anúncios | número de anúncios além dos 5 primeiros | contagem |
| Exportar | CSV com todas as linhas do filtro atual | rota `GET /api/painel/anuncios.csv` |

### 3.5 Central de avisos

| Número | Definição |
|---|---|
| Grupos aguardando | leads distintos com ao menos um aviso aberto (situação diferente de resolvido e arquivado) na aba e no período escolhidos |
| Novas | avisos abertos sem responsável |
| Minhas | avisos abertos com `id_usuario_responsavel` = usuário logado |
| Resolvidas | situação `resolvido` ou `arquivado` |
| Contagem de cada chip | avisos da categoria no período, dentro da aba atual |

### 3.6 Follow-up

| Número | Definição |
|---|---|
| Pendentes | `agentesia_followups` com situação pendente ou reservado |
| Enviados | situação `enviado` no período |
| Respondidos | envios seguidos de mensagem do lead antes do próximo passo **ou em até 48 h**, o que vier primeiro (o último passo não tem "próximo"). Mensagem do lead conta uma vez só, para o envio mais recente antes dela. Substitui a regra do Início, que hoje conta qualquer mensagem posterior, mesmo semanas depois |
| Taxa de resposta | respondidos ÷ enviados |
| Avançaram depois do follow-up | leads que mudaram para fase mais adiante em até 7 dias depois de responder a um follow-up (precisa da linha do tempo, 007) |
| Assinaram depois do follow-up | leads com contrato assinado depois de terem recebido ao menos um follow-up |
| Desistências | leads encerrados com motivo `sem_resposta_followup` |

---

## 4. Ativação de conta pela Helena

### 4.1 Como é hoje no nosso sistema

1. **A LawChat cadastra o escritório** em `/admin/escritorios`: escolhe a conta da Helena na lista (token de parceiro), gera ou cola o token (vai para o Vault), opcionalmente cria o gestor com senha provisória.
2. **O token é testado e os números são sincronizados** (`_salvar_token_helena`).
3. **O cliente entra pelo botão da Helena** (`GET /entrar/helena`): confere a conta e o usuário na API da Helena e cria o usuário no primeiro acesso, com papel gestor por padrão.
4. **Ativação do agente**: checagem em 10 passos (`app/gestao/ativacao.py`): conta, número, webhook, alcance da URL, etapas, chave de IA, CRM, equipe, ZapSign, números de teste.

No dashboard antigo é bem mais frágil: cadastro manual com token em texto puro, acesso pelo link `/d/{conta}&{usuario}` sem senha nem assinatura, API sem autenticação.

### 4.2 Lacunas

**Do fluxo:**
1. Sem autoatendimento: conta não cadastrada que clica no botão só vê "conta sem IA", sem pedido de acesso.
2. `id_conta_helena` é opcional na criação e não dá para editar pelo painel; sem ele o login e todos os webhooks falham.
3. Token colado não é conferido contra a conta do escritório (pode apontar para outra conta).
4. Não há escolha de painel do CRM nem **mapeamento de etapas para as fases do funil** na ativação (o dashboard depende disso).
5. Não há primeira carga do CRM nem indicação de "dados prontos".
6. Ativação de produto liga o agente antes da checagem; a ativação pelo agente bloqueia. Dois comportamentos.
7. O follow-up do produto não chega ao agente (ver 1.6).
8. Webhook da ZapSign é passo manual.

**De segurança (corrigir antes de abrir o dashboard dentro da Helena):**
1. A assinatura do link de entrada é opcional e, quando ligada, cobre só conta e horário, não o usuário; não há proteção contra reuso.
2. Qualquer usuário da conta Helena da LawChat vira admin LawChat automaticamente.
3. Ligar contas pelo e-mail que vem da Helena permite entrar como outra pessoa.
4. Papel padrão gestor para todo atendente novo.
5. Painel em iframe sem `frame-ancestors` e sem proteção contra requisições de outro site nos POST sem corpo.
6. A senha provisória do gestor volta na resposta da API.

### 4.3 Fluxo proposto: onboarding guiado

Uma tela de **Ativação** com passos e barra de progresso, que a LawChat e o gestor veem igual:

1. **Conta Helena** (LawChat ou, no futuro, o próprio cliente com aprovação): escolher a conta pela lista do parceiro; token gerado pelo parceiro e guardado no Vault; **conferir que o token é daquela conta**. Campo `id_conta_helena` obrigatório e editável pelo admin.
2. **Pedido de acesso**: se uma conta não cadastrada clicar no botão da Helena, gravar um pedido (conta, usuário, data) numa tabela da plataforma (`agentesia_pedidos_acesso`, sem escritório) e avisar a equipe LawChat pelo canal que já existe em `app/central_avisos.py` (WhatsApp da LawChat), nunca pela caixa de um escritório. Limitar a um pedido por conta por dia, para o botão não virar fonte de spam. A LawChat aprova com um clique, que cai no passo 1.
3. **Números e webhook**: sincronizar números, criar ou corrigir a assinatura do webhook, testar o alcance da URL. Igual ao que a ativação do agente já faz.
4. **CRM**: escolher o painel (ou painéis) do escritório; carregar as etapas; **mapear cada etapa para uma fase canônica** com sugestão automática pelo título, confirmada pelo gestor. Grava em `agentesia_mapa_fases`.
5. **Primeira carga do CRM**: dispara o sync completo em segundo plano, dentro do teto de cota da 2.2, com progresso ("1.240 de 30.000 cards") e previsão de término. Pode levar dezenas de minutos; se cair, retoma de onde parou. O dashboard mostra "carregando" no universo CRM até terminar, mas o universo IA já funciona.
6. **Equipe e papéis**: puxa os atendentes da Helena; o gestor escolhe quem é gestor, quem é atendente. Papel padrão de quem entra pelo botão: **atendente**.
7. **Avisos**: escolher quais tipos vão para o WhatsApp e para quem; mandar um aviso de teste.
8. **Agente e produto**: a ativação começa **sempre em modo teste** com os números de teste; só passa para produção quando a checagem não tiver erro.
9. **Pronto**: link do dashboard e do botão da Helena (com a URL assinada).

Pré-requisitos de segurança desta fase: assinatura do link obrigatória, cobrindo conta + usuário + horário, com uso único; nada de criar admin LawChat automaticamente; não ligar contas por e-mail; `frame-ancestors` só para os domínios da Helena; senha provisória mostrada uma vez na tela, não na resposta da API.

---

## 5. O que copiar, o que reescrever, riscos

### 5.1 Copiar do projeto atual

Caminhos relativos a `Buscar da helena/dashboard-app/src`.

| Peça | Como copiar |
|---|---|
| `components/KPICards.tsx`, `StageMetrics.tsx`, `SalesFunnel.tsx`, `BestAdsRanking.tsx`, `AdDetailModal.tsx` | Quase literal, trocando o cálculo interno e o `useClassify()` por **props com números prontos** vindos da API. Trocar as curvas fixas por série real |
| `components/FiltersBar.tsx` | Só o layout e os presets de período; o estado vira query string e parâmetro de API |
| `components/NotificationsPage.tsx` | O agrupamento, as abas, os chips, a trava anti-roubo e o registro de ações; os dados vêm da nossa API |
| `components/notifications/WhatsAppAlertsConfig.tsx` | Só como referência de tela; a nossa configuração é a `Avisos.tsx` |
| Aba Campanhas: `CampaignAdRanking`, `CampaignFunnel`, `CampaignAlerts`, `CampaignComparison`, `CampaignHeatmap` | Visual e regras de alerta; cálculo no servidor |
| `AnimatedCounter.tsx` | Ou usar o `count-up` que já temos em `painel/src/components/ui` |
| `utils/exportCsv.ts`, `formatters.ts`, cores das fases (`STAGE_STYLE`) | Literal |
| Tokens `--kpi-*`, `--funnel-1..6`, `--conv-*` de `index.css` e `tailwind.config.ts` | Literal no nosso `index.css` e `tailwind.config.ts` |
| Do `frontend/server.js` | A **lógica** do sync (endpoints, `IncludeDetails`, transformadores, upsert com `COALESCE`, reconciliação com trava, backfill do número, escalonamento), reescrita em Python |
| `helena-fetch-all/_sql/rate_limit.sql` | A ideia do limitador por hash do token, como função SQL nossa |
| Catálogo de tipos de aviso (`ALERT_TYPES` do `server.js`) | Como lista de tipos e textos padrão, mapeados para as nossas chaves de evento |

A pilha do nosso painel já é a mesma (Radix, Tailwind, lucide, recharts, framer-motion, react-query), então os componentes entram sem dependência nova.

### 5.2 Não copiar (reescrever)

- `api/helena.ts`, `hooks/useCards.ts`, `hooks/useFilters.ts`, cache em IndexedDB: download em massa e cálculo no navegador.
- `hooks/useClient.ts`, `hooks/useCurrentUser.ts`, `pages/ClientDashboard.tsx`: identificação por URL, sem login.
- `utils/normalizeStep.ts` e o `classifyFunnel` do servidor: fase pelo texto do título.
- O Realtime do Supabase sem filtro de cliente.
- As rotas abertas do `server.js` e as políticas "qualquer um lê e escreve" das migrações do Lovable.
- As gerações mortas de sync (n8n, edge functions, pg_cron do Lovable): não religar.

### 5.3 Riscos

| Risco | Como tratar |
|---|---|
| **Segredos**: o projeto atual tem token da Helena em texto puro na tabela de clientes e num JSON do n8n, e telefones de alerta no código | Nada disso vem para cá. Token só no Vault. Recomendação ao dono: **trocar o token que está no JSON do n8n** e revisar a política de leitura da tabela de clientes do banco antigo |
| **RLS e isolamento** no banco antigo (leitura pública de tabelas com nome e telefone de leads) | No nosso banco: RLS fechada, acesso só pelo backend, escritório sempre do contexto |
| **Rate limit da Helena** (1.000 por 5 min por conta, dividido com o motor) | Teto do sync de 300 por 5 min, motor com prioridade, pausa do sync quando o motor toma 429; webhook de card no lugar de consulta; nunca sessão por id em carga grande; desligar o sync antigo do escritório antes de ligar o nosso (bancos diferentes, não há limitador comum) |
| **Lead some do funil depois da passagem para humano** (MVP) | Faixa explicando na tela; fase 4 corrige com o card do CRM (precedência 3.0, item 4) |
| **Mesma palavra, dois números** (assinados e respondidos no Início e no Dashboard) | Uma função por métrica, rótulos distintos para "no período" e "dos leads do período" (3.0) |
| **Custo de banco** (consultas pesadas no dashboard) | Agregação em SQL com índices; cache de 60 s por (escritório, filtros) no backend; views materializadas só se a consulta passar de 1 s em escritório grande |
| **Custo de IA** | O dashboard não chama IA. O "agente de vendas" do projeto atual (chat que analisa campanhas) fica para depois, com limite de consumo (frente C do plano de custo) |
| **Números diferentes entre telas** | Fase canônica única + uma view base; teste automático que compara Dashboard, Funil e Rastreio |
| **Formato do evento TRACK** não documentado pela Helena | Confirmar com um anúncio real antes da fase 2; reserva: UTM da sessão e do contato |
| **Leads sem UTM** somem do ranking | Linha "Sem anúncio identificado" e o mesmo total em todas as telas |
| **Custo por anúncio subestimado** enquanto `agentesia_chamadas_ia` não tiver `id_lead` | Coluna de custo só aparece depois de A2; até lá, rótulo "parcial" |
| **Gasto com anúncio** não existe | Sem CPL/CAC até haver cadastro manual ou ligação com a API de Marketing da Meta (decisão de produto) |
| **Fuso**: o cron antigo provavelmente roda em UTC | Nosso worker e nossas consultas fixam `America/Sao_Paulo` |
| **Dados pessoais** na exportação e no espelho | Telefone mascarado na tela e no CSV por padrão; espelho apagado junto com o escritório |

---

## 6. Plano em fases

Cada fase termina com testes passando e algo visível no painel. Os testes seguem o padrão do projeto (`pytest` com banco de teste e respostas falsas da Helena; `npm run build` no painel).

### Fase 0. Decisões e segurança da entrada

- **Decisões** (seção 7), um dia, sem código. Bloqueia a fase 4 em diante.
- **Segurança da entrada pelo botão da Helena** (antes estava na fase 6): assinatura obrigatória cobrindo conta + usuário + horário, com uso único; sem admin LawChat automático; sem ligar contas por e-mail; papel padrão atendente; `frame-ancestors` só para os domínios da Helena; proteção contra requisição de outro site nos POST; senha provisória fora da resposta da API. Motivo da mudança: a fase 1 já põe funil, contratos e anúncios dentro do iframe da Helena; com a entrada como está, qualquer usuário da conta da LawChat vira admin e um link reaproveitado abre o painel de outra pessoa. Não dá para abrir o dashboard antes disso.
- **Testes**: `tests/test_entrar_helena.py` com cada recusa.
- **Depende de**: combinar com o que o botão da Helena consegue mandar na URL.

### Fase 1. MVP do Dashboard com o que já temos

**Objetivo**: KPIs, cards por fase, funil (acumulado e "real" pelos turnos) e melhores anúncios, universo "Atendidos pela IA", filtros Período, Modo (só Criação), Campanha, Etapa, Agente, Número, Origem.

- **Banco** (008, parte 1): `agentesia_fases_funil`, `agentesia_mapa_fases` (dicionário padrão + "sem fase", 2.3b), índices em `agentesia_leads`, view `agentesia_v_leads` com a precedência da 3.0 (sem custo ainda; a 007 a estende depois).
- **Backend**: `app/gestao/filtros.py` (o módulo de filtros do `RASTREAMENTO_E_FILTROS.md`, criado aqui se ainda não existir, e usado também por Conversas) e `app/gestao/painel.py` (novo, para não inchar `rotas.py`) com
  - `GET /api/painel/resumo?de&ate&modo&campanha&fases&agente&canal&origem` → KPIs, série por dia, fases, funil;
  - `GET /api/painel/anuncios?...&ordem=leads|conversao&limite` → ranking e mini-cards;
  - `GET /api/painel/anuncios.csv`;
  - `GET /api/painel/filtros` → opções dos filtros (campanhas, agentes, números, origens do período);
  - `GET /api/painel/leads?fase=&...` → lista para os cliques (paginada por cursor).
- **Painel**: `painel/src/telas/Resultados.tsx`, a barra comum `painel/src/componentes/BarraDeFiltros.tsx` (a mesma do rastreamento, não uma cópia em `resultados/`), `painel/src/components/resultados/` (`KpiCards.tsx`, `CardsDeFase.tsx`, `FunilDeVendas.tsx`, `MelhoresAnuncios.tsx`, `ListaDeLeads.tsx`), tela simples "Mapear etapas" do agente, tokens de cor no `index.css` e `tailwind.config.ts`, rota e menu em `main.tsx`, chamadas em `api.ts`. O Início passa a ler "assinados" e "follow-up respondido" das mesmas funções.
- **Correção avulsa**: cópia do `padrao_followup` do produto para `config.followup` na ativação (`app/gestao/produtos.py`), com teste. Não depende do dashboard e o defeito já afeta os clientes.
- **Testes**: `tests/test_painel_metricas.py` com leads de exemplo cobrindo cada fase: total, assinados, conversão, eficiência (com Não assinou no denominador), % qualificado, soma dos 8 cards + sem fase = total, contrato assinado com etapa atrasada conta uma vez só, funil acumulado, ranking por anúncio, conversão ponderada, isolamento (escritório A não vê B), cache não mistura papel nem escritório, atendente sem custo, fuso de Brasília na virada do dia.
- **Depende de**: fase 0 para ir a produção dentro da Helena. Não toca `pipeline.py`. Combinar com a frente de rastreamento quem cria `filtros.py`, `BarraDeFiltros.tsx` e `agentesia_v_leads` primeiro.

### Fase 2. Central de avisos (caixa de entrada)

- **Banco** (008, parte 2): `agentesia_avisos`, `agentesia_avisos_registro`.
- **Backend**: em `app/notificacoes.py`, quando um evento do motor acontece, **gravar o aviso na caixa de entrada sempre** (mesmo com o WhatsApp desligado) e ligar `id_acao_whatsapp` quando a ação `notificar` for criada. Rotas: `GET /api/avisos?aba&de&ate&categorias`, `POST /api/avisos/{id}/assumir|transferir|avaliar|ler|resolver|arquivar`, `GET /api/avisos/ao-vivo` (SSE; MVP com consulta a cada 15 s, que só pergunta "tem aviso mais novo que o id X?" em vez de refazer a lista). Avisos `sistema` saem dos eventos de cadastro do próprio escritório (1.5); `app/central_avisos.py`, que é da equipe LawChat, não grava na caixa do escritório. Tarefa agendada nova para `assinatura_atrasada`.
- **Passado**: preencher uma vez a partir de `agentesia_acoes` do tipo `notificar` e de `agentesia_eventos` dos últimos 30 dias.
- **Painel**: `painel/src/telas/CentralAvisos.tsx`; `Avisos.tsx` vira `/avisos/config` e é o destino do botão "Avisos no WhatsApp". Selo com o número de novas no menu.
- **Testes**: `tests/test_central_avisos_caixa.py`: evento gera aviso; par `contrato_gerado` + `etapa:assinatura` gera um só; duplicado em 24 h atualiza; trava anti-roubo; abas; chips; registro de ações; evento sem escritório ou de outro escritório nunca aparece; isolamento.
- **Follow-up, primeira parte** (sai da fase 5, porque só lê o que já existe): aba `ResultadosFollowup.tsx` com os blocos Responsável e regras, Fila, Histórico e os resultados que não precisam da linha do tempo (enviados, respondidos com a regra da 3.6, assinaram depois de follow-up, desistências). Rota `GET /api/painel/followup`.
- **Depende de**: fase 0 (mesma razão da fase 1). Coordenar com o B5 do `PLANO_PAINEL_CUSTO_DEPLOY.md`, que também mexe em `app/notificacoes.py`, `Avisos.tsx` e `app/central_avisos.py`: um dos dois faz primeiro e o outro rebaseia. Fica melhor com B1 (erro ligado ao turno).

### Fase 3. Rastreio de anúncios e linha do tempo

- **Banco**: a migração 007 do `RASTREAMENTO_E_FILTROS.md` (renumerada): histórico do lead por gatilho, marcos, toques, `agentesia_anuncios`, `agentesia_gasto_anuncios`; estender a view com marcos.
- **Backend**: `GET /api/painel/anuncios/{chave}` (cabeçalho, mini-funil, motivos de perda, conversas), modo Atualização no `resumo`, versão "safra" dos KPIs, funil "real". Cadastro de gasto por planilha colada (`POST /api/painel/gasto`).
- **Painel**: `RastreioAnuncios.tsx` e `AnuncioDetalhe.tsx`; linha do tempo no painel lateral de Conversas.
- **Testes**: gatilho grava cada mudança com o autor certo; mesmo total entre Dashboard e Rastreio; lead sem anúncio na linha própria.
- **Depende de**: frente de rastreamento; custo de IA por anúncio só depois de A1/A2 do plano de custo (antes disso a coluna fica escondida). O gatilho não mexe em `pipeline.py`, mas os campos de atendente humano em `agentesia_mensagens` tocam o caminho do webhook: combinar com a frente de produção.

### Fase 4. Espelho do CRM da Helena

- **Banco**: migração 009.
- **Ordem dentro da fase**: (a) limitador por conta usado também pelo motor; (b) assinar `PANEL_CARD_*` num escritório piloto e medir o volume; (c) só então incremental e primeira carga.
- **Backend**: `app/crm_sync/` (novo): `cliente.py` (chamadas com limitador por conta, teto do sync e `Retry-After`), `webhook_crm.py` (eventos de card numa fila própria, separada das mensagens), `transformar.py` (Helena → linha), `gravar.py` (upsert com `COALESCE`), `incremental.py`, `reconciliar.py`, `agenda.py` (minuto por escritório, lote de 4, trava no banco). Laço no worker (ou no app "IA", conforme a frente D). Token sempre do Vault. Rota admin para "sincronizar agora" e "ver última rodada", protegida.
- **Painel**: universo "CRM inteiro", filtros Painel CRM, Responsável e Tags; tela "Mapear etapas" (etapas do CRM → fases).
- **Testes**: transformadores com respostas falsas guardadas em `tests/dados/helena_*.json` (montadas à mão, sem dado real); falha numa página não marca como feito; reconciliação respeita a trava de 20%/25 e não regrava card sem mudança; 429 respeita `Retry-After`; sync nunca passa do teto e para quando o motor toma 429; primeira carga retoma do cursor; nenhuma chamada de sessão por id acima do teto da rodada; cursor sobrevive a reinício; isolamento.
- **Validação**: para um escritório piloto, comparar os números do universo CRM com o dashboard antigo (leitura só, sem escrever no banco antigo). Diferenças esperadas por causa da fase canônica precisam ser explicadas antes de desligar o antigo.
- **Depende de**: decisão de rate limit e de desligar o sync antigo (seção 7); frente D (onde roda o worker).

### Fase 5. Follow-up (segunda parte) e Campanhas

- **Follow-up**: o que precisa da linha do tempo: "avançou de fase depois do follow-up" e resultados por etapa em que o lead estava no envio.
- **Campanhas**: `GET /api/painel/campanhas?agrupar=campanha|conjunto|criativo|plataforma|produto`, comparação, mapa de calor, alertas de campanha (gravados na central uma vez por dia). Tela `Campanhas.tsx`, que **substitui** `Funil.tsx` (a rota `/funil` e `repositorio.funil` passam a ser este endpoint; o item 6 do `RASTREAMENTO_E_FILTROS.md` vira esta tarefa, não uma segunda).
- **Testes**: resultados de follow-up a partir de dados de exemplo; regras dos três alertas; alerta não repete no mesmo dia; `/funil` antigo devolve o mesmo que Campanhas agrupado por campanha.
- **Depende de**: fase 3 (linha do tempo).

### Fase 6. Onboarding guiado

- **Cadastro**: `id_conta_helena` obrigatório e editável; token conferido contra a conta. (O resto da segurança da entrada já foi na fase 0.)
- **Fluxo**: tela `Ativacao.tsx` com os 9 passos da seção 4.3; tabela de pedidos de acesso da plataforma; ativação de produto começando em teste.
- **Testes**: pedido de acesso avisa a LawChat e não aparece em nenhum escritório; limite de um pedido por conta por dia; token de outra conta recusado.
- **Depende de**: fase 4 só para o passo de primeira carga; os demais passos podem sair antes, se o dono preferir.

### Fase 7. Execuções e custo dentro do Dashboard

Ligar os números das frentes A e B: coluna de custo de IA no Rastreio e nas Campanhas, custo por contrato no KPI (só para quem vê consumo), atalho de "erros deste lead" na central de avisos. Sem código novo de coleta; só leitura do que A e B criarem.

### Mapa de dependências

| Fase | Depende de | Toca arquivos de outra frente? |
|---|---|---|
| 0 Decisões e segurança da entrada | nada | `app/gestao/rotas.py` e `seguranca.py` (entrada) |
| 1 Dashboard MVP | fase 0 para produção | `filtros.py`, `BarraDeFiltros.tsx`, `agentesia_v_leads`: frente de rastreamento; `app/gestao/produtos.py` (correção do follow-up) |
| 2 Central de avisos e follow-up (1ª parte) | fase 0 (melhor com B1) | `app/notificacoes.py`, `Avisos.tsx`, `app/central_avisos.py`: frente de produção e B5 do plano de custo |
| 3 Rastreio | frente de rastreamento; A1/A2 para custo | Webhook (atendente humano): frente de produção |
| 4 Espelho CRM | decisões 7.2, 7.3 e 7.12; frente D | Cliente Helena do motor (limitador comum) |
| 5 Follow-up (2ª parte) e Campanhas | fase 3 | `Funil.tsx` e `repositorio.funil` (substituídos) |
| 6 Onboarding | fase 4 (só primeira carga) | `app/gestao/rotas.py` (cadastro) |
| 7 Custo e execuções | frentes A e B | Não |

O que dá para começar já: fase 0 (segurança) e, em paralelo, o código das fases 1 e 2 (que só vão a produção depois da fase 0), sem conflito em `pipeline.py`.

---

## 7. Decisões que dependem do dono

1. **Universo padrão do Dashboard**: abrir em "Atendidos pela IA" ou em "CRM inteiro" (como o atual)? Sugestão: IA, com o CRM a um clique.
2. **Fonte do CRM**: espelho próprio (recomendado) ou ler o banco do dashboard antigo enquanto isso?
3. **Os dois dashboards ao mesmo tempo**: por quanto tempo, e quem desliga o sync antigo de cada escritório migrado (por causa da cota da Helena)?
4. **Regra de "Não assinou"**: depois de quantos dias com contrato gerado e não assinado o lead conta como Não assinou?
5. **Conversão média dos anúncios**: ponderada (recomendado) ou simples, como hoje?
6. **Gasto com anúncio**: começar com planilha colada ou esperar a ligação com a Meta? Devolver conversões para a Meta fica para depois?
7. **Quem pode exportar** e se o telefone sai mascarado no CSV.
8. **Autoatendimento**: o cliente pode pedir acesso sozinho pelo botão da Helena, com aprovação da LawChat?
9. **Papel padrão** de quem entra pela Helena: atendente (recomendado) ou gestor?
10. **Ordem das migrações** 005 a 009, combinada com o plano de custo e com o rastreamento.
11. **Segurança do projeto antigo**: trocar o token exposto no JSON do n8n e revisar a leitura pública da tabela de clientes, independente da migração.
12. **Teto de cota do sync**: 300 chamadas a cada 5 min por conta (sugestão) ou outro valor? Vale o mesmo para todos os escritórios?
13. **CRM ou agente decide a fase** quando os dois existem: sugestão da 3.0 é "o mais adiante vence, perda do CRM vence". Alternativa: o CRM sempre vence depois da passagem para humano.
14. **Desqualificado**: quais motivos da lista fechada contam como desqualificado (sugestão: todos menos `nao_respondeu`, `pediu_para_parar` e `engano`, que ficam na fase em que pararam).
15. **Tela Funil atual**: some (vira atalho para Campanhas) ou fica como está por um tempo?

---

## Arquivos de referência

Projeto atual (só leitura): `Buscar da helena/dashboard-app/src/pages/Index.tsx`, `components/KPICards.tsx`, `StageMetrics.tsx`, `SalesFunnel.tsx`, `BestAdsRanking.tsx`, `FiltersBar.tsx`, `CampaignPage.tsx`, `NotificationsPage.tsx`, `utils/normalizeStep.ts`, `index.css`, `tailwind.config.ts`; `Buscar da helena/frontend/server.js`; `Buscar da helena/helena-fetch-all/_sql/rate_limit.sql`.

Nosso projeto: `app/gestao/metricas.py`, `app/gestao/rotas.py`, `app/gestao/repositorio.py` (`funil`), `app/acoes.py` (eventos disparados em par), `app/gestao/ativacao.py`, `app/gestao/produtos.py`, `app/notificacoes.py`, `app/central_avisos.py`, `app/origem.py`, `app/followup/`, `app/canal/helena_conta.py`, `db/migracoes/`, `painel/src/telas/` (Inicio, Funil, Avisos, Erros, AgenteFollowup, Entrar, AdminEscritorios), `docs/RASTREAMENTO_E_FILTROS.md`, `docs/PLANO_PAINEL_CUSTO_DEPLOY.md`, `docs/HELENA_CAPACIDADES.md`.

## Decisões do dono (25/11/2026)

1. **Universo:** o dashboard mostra o CRM inteiro, com um filtro "atendidos pela IA" que liga as tabelas do CRM às nossas (lead, turnos, eventos, contratos).
2. **Dados do CRM:** não usar nem copiar o banco do dashboard antigo (está desatualizado). Fazer a leitura da Helena do jeito certo, no nosso motor: sincronização incremental própria, com cursor, limite de taxa e reconciliação, e não o esquema antigo.
3. **"Não assinou":** contrato gerado e não assinado há **30 dias**.
4. **Conversão média dos anúncios:** ponderada pelo número de leads.
5. **Gasto com anúncio:** fica para a integração com a Meta, depois. Sem planilha colada agora.
6. **Exportar CSV:** liberado para todos os usuários, com o telefone. O export do dashboard antigo tem defeito: o nosso precisa sair correto (UTF-8 com BOM, separador ";", todas as linhas do filtro, sem cortar).
7. **Acesso:** mesmo esquema do login pelo botão da Helena. Quem entra por ali já cai dentro da conta do escritório; não há fluxo separado de "pedir acesso".
