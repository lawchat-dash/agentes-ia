# Pesquisa: a plataforma do LawChat IA comparada com plataformas abertas

Esta pesquisa compara a **plataforma** do LawChat IA com plataformas abertas e auto-hospedáveis do GitHub. Por plataforma entendemos painel, superadmin com várias contas, conexão com WhatsApp e CRM, ativação de agente por produto, biblioteca, editor de prompt, cobrança e central de atendimento. O motor de conversa foi comparado em outro documento, [PESQUISA_AGENTES_DE_LEADS.md](PESQUISA_AGENTES_DE_LEADS.md). A comparação com o LíderHub está em [LIDERHUB_ANALISE.md](LIDERHUB_ANALISE.md). Para não repetir o que já foi visto, este documento só cita os dois quando precisa.

Foi feita em 25/11/2026 só com leitura. Nenhum código foi alterado e nenhuma API de IA foi chamada.

- **O que li do nosso lado:**
  - `MAPA_DO_SISTEMA.md`, `DESENHO.md`, `docs/PLATAFORMA.md`, `docs/ESTADO.md` e as duas pesquisas anteriores;
  - o menu (`painel/src/componentes/Estrutura.tsx`) e as rotas (`painel/src/main.tsx`);
  - as telas `Inicio`, `Agentes`, `Agente` (Laboratório), `AdminEscritorios`, `Carteira`, `AdminCobranca`, `Atendimento`, `Configuracoes`, `Historico` e `Funil`;
  - `pages/Biblioteca`, `MeusProdutos`, `Ativar` e `ProdutoEditor`, e o assistente `components/agent/ProductConfigurator.tsx` com `TestePrompt.tsx`;
  - do servidor, `app/gestao/laboratorio.py`.
- **Projetos abertos:** a fonte é o README, a documentação pública e a API pública do GitHub. Estrelas e datas do último envio de código foram consultadas em 25/11/2026. O código deles não foi lido.
- **Ressalva:** alguns recursos (por exemplo, telas do superadmin do Chatwoot e planos das versões "SaaS" do Whaticket) vêm da documentação ou de anúncios dos próprios projetos e não foram testados aqui. Quando a fonte é fraca, isso está escrito.

---

## (a) Resumo em 10 linhas

1. **No geral, estamos à frente das plataformas brasileiras abertas e atrás das grandes plataformas de agentes só em ferramentas para quem constrói.** Whaticket, Press Ticket, Ticketz e Izing são caixas de atendimento com um robô simples. Dify, Chatwoot (com o Captain) e Typebot têm um ciclo mais completo de construir, testar, publicar e voltar.
2. **Acima do mercado (1): a ativação por produto.** O escritório escolhe um produto jurídico pronto na Biblioteca e ativa em 6 passos, com revisão e checklist. Nenhuma plataforma aberta tem um catálogo de nicho assim: o que elas oferecem são modelos genéricos.
3. **Acima do mercado (2): o superadmin.** Sincroniza as contas da Helena e habilita a "função de agente" num clique, gerando token, webhook e etiquetas. Também entra na conta do cliente ("Acessar") e cuida de recargas e margem. Só o Chatwoot (console de superadmin) e as versões "SaaS" do Whaticket chegam perto. Nenhum dos dois cria a integração sozinho.
4. **Acima do mercado (3): créditos em reais.** Temos saldo, bônus do mês, extrato, recarga por Pix, limite mensal que pausa a IA ou só avisa, e consumo por agente, etapa e função. As plataformas abertas param em "mensagens por plano" (Whaticket SaaS, Typebot) ou em saldo de tokens (LibreChat).
5. **Abaixo do mercado (1): o teste antes de ativar.** No assistente de 6 passos, o painel "Teste de prompt" aparece como "Em breve" e está desligado. O Laboratório existe, mas só na tela antiga de Agentes. Dify, Chatwoot Captain, Typebot, Langflow e Flowise põem o teste ao lado do editor, e o Captain mostra "por que respondeu assim".
6. **Abaixo do mercado (2): versões.** Dify e Botpress separam "rascunho" e "no ar", guardam cada publicação com autor e data e deixam voltar. Temos histórico de alterações (antes e depois) e aviso de versão nova do catálogo, mas não temos "publicar" nem "voltar para a versão de ontem".
7. **Abaixo do mercado (3): integrar para fora.** Não temos API pública nem webhooks de saída. Chatwoot, Dify, Typebot e Evolution API têm os dois, e até projetos pequenos já trazem webhook assinado com registro de entregas.
8. **Confusão de navegação:** "Biblioteca", "Meus Produtos" e "Agentes" aparecem lado a lado no menu e falam da mesma coisa por dois caminhos. As plataformas boas têm um só objeto central (no Dify, o "App"; no Typebot, o "Bot"; no Captain, o "Assistente").
9. **Diferente de propósito (e certo):** não temos editor visual de fluxo nem caixa de atendimento própria. O funil por produto mais o "@" é mais fácil para advogado do que blocos e setas. A Helena embutida evita refazer o que Chatwoot e Whaticket gastaram anos construindo.
10. **Veredito:** não é preciso mudar a arquitetura da plataforma. Os maiores ganhos são de experiência:
    - religar o teste dentro da ativação, com "detalhes da resposta";
    - publicar com versões e poder voltar;
    - um só caminho no menu para "meus agentes";
    - saúde do número e da conta à vista, para o cliente e para o superadmin;
    - previsão do saldo.

---

## (b) Recurso de plataforma × quem tem × nós temos? × vale fazer?

Legenda de "Nós temos?":
- **sim**: temos;
- **em parte**: temos uma parte;
- **não**: não temos;
- **Helena**: fica com a Helena, de propósito.

Legenda de "Vale fazer?":
- **já feito**: não há nada a fazer;
- **sim, já**: vale fazer logo;
- **sim, depois**: vale fazer mais adiante;
- **não**: não vale fazer.

| Recurso | Quem tem (exemplos) | Nós temos? | Vale fazer? |
|---|---|---|---|
| **Multi-tenant** (várias contas isoladas) | Chatwoot (contas), Izing (tenants), Whaticket SaaS e Ticketz (empresas), Tiledesk (projetos), whatsapp-saas (workspaces isolados no banco) | **sim**: escritórios isolados, superadmin "Contas", "Acessar" como cliente | já feito; falta mostrar a saúde de cada conta (ver c.9) |
| **Onboarding de conta** | Ticketz (cadastro da empresa pelo próprio cliente), whatsapp-saas (instalação guiada), Dify (convite de membros) | **em parte**: o superadmin habilita em passos; o Início mostra alertas com passos. Não há checklist que se marque sozinho | **sim, já** (c.4) |
| **Conexão de número** (QR ou oficial) | Evolution API e Manager (QR pelo Baileys ou API oficial), WPPConnect (QR), Whaticket e Press Ticket (QR), Typebot (só oficial, com o próprio app da Meta), whatsapp-saas (YCloud ou Kapso com botão "testar conexão") | **Helena**: o número vem da Helena e é escolhido no passo 1 | não refazer; **sim, já** mostrar estado e teste da conexão (c.5) |
| **Teste antes de ativar** (playground) | Dify ("Debug e prévia" ao lado do editor), Captain (Playground com mudanças temporárias e "Run details"), Typebot (botão Test, até no WhatsApp real), Langflow e Flowise (chat de teste), Botpress (emulador) | **em parte**: o Laboratório funciona na tela antiga de Agentes; no assistente de 6 passos está "Em breve" | **sim, já** (c.1) |
| **Versões de prompt** | Dify (rascunho, publicar, histórico com autor e data, restaurar), Botpress Cloud (versões publicadas), Langflow (histórico do fluxo) | **em parte**: `/historico` com antes e depois; aviso "o catálogo subiu de versão" com revisão; sem publicar nem voltar | **sim, já** (c.3) |
| **Biblioteca / templates** | Typebot (galeria de modelos), Dify (modelos de app e marketplace), Flowise (marketplace de fluxos), LibreChat (marketplace de agentes) | **sim**: Biblioteca por categoria e "Modelos de agente" no admin | já feito; acrescentar "como testar" e "quantos usam" (já em LIDERHUB) |
| **Editor visual de fluxo** | Typebot, Botpress, Flowise, Langflow, Dify, Tiledesk, versões novas do Whaticket SaaS ("flowbuilder") | **não**, de propósito: funil por produto e "@" | **não** como editor; **sim, depois** um mapa só de leitura do funil (d.4) |
| **Base de conhecimento** | Dify (com "teste de busca"), Captain (documentos e FAQs sugeridas a partir de conversas), Open WebUI, Tiledesk, whatsapp-saas | **sim**: documentos, FAQ, objeções, dados do escritório | **sim, depois**: "testar busca" e FAQ sugerida (c.8) |
| **Métricas / funil** | Chatwoot (relatórios por agente, caixa, etiqueta, CSAT), Typebot (onde as pessoas abandonam, bloco a bloco), ai-whatsapp-bot-builder (tempo de resposta, CSV) | **em parte**: Início, Funil, consumo | **sim, depois** (abandono por etapa; já em `DASHBOARD_IA.md`) |
| **Inbox unificada** | Chatwoot, Whaticket, Ticketz, Izing, Tiledesk | **Helena**: Central de Atendimento com a Helena embutida | não refazer; manter o atalho "abrir a conversa deste lead" |
| **Transferência para humano** | Captain (cenários e mensagem de passagem), Chatwoot (bot entrega à equipe), whatsapp-saas (para quando o humano fala) | **sim**: pausa, etiqueta, aviso, volta sozinha | já feito; resumo "quente" já está na pesquisa anterior |
| **Créditos / cobrança** | Whaticket SaaS (planos com limites e faturas; empresa vencida é bloqueada), LibreChat (saldo de tokens com recarga automática), Captain (créditos por resposta), ai-whatsapp-bot-builder (limites com bloqueio e carência) | **sim**: carteira em R$, Pix, bônus, limite que pausa ou avisa, markup | já feito; **sim, já** a previsão do saldo (c.7) |
| **Papéis e permissões** | Dify (dono, admin, editor, membro), Chatwoot (admin, agente, papéis personalizados no plano pago), Open WebUI (grupos), Captain (agente só testa, admin edita) | **sim**: admin LawChat, gestor, atendente | já feito; **sim, depois** "atendente pode testar, não editar" |
| **Logs de erro** | Dify (registros e rastreio por chamada), Captain ("Run details" por resposta), Evolution (eventos por instância) | **sim**: tela Erros com responsável; histórico de alterações | **sim, já** os detalhes por resposta (c.6) |
| **API pública** | Chatwoot, Dify (API por app com chave), Typebot, Evolution API, ai-whatsapp-bot-builder | **não** (só a do painel) | **sim, depois** (depois dos webhooks) |
| **Webhooks de saída** | Chatwoot, Typebot (bloco Webhook), Evolution API, ai-whatsapp-bot-builder (assinados, com registro e novas tentativas) | **não** | **sim, depois** (c.10) |
| **Marketplace** | Dify (plugins), Flowise e LibreChat (fluxos e agentes da comunidade) | **não** (a Biblioteca é curada por nós) | **não** por enquanto: o valor está na curadoria jurídica |

---

## (c) Os 10 melhores aprendizados de produto e experiência, por valor × esforço

### 1. Testar ao lado do editor, antes de ativar
**Valor alto, esforço médio** (o motor já existe).

**Hoje:**
- No passo 3 do assistente de ativação, o lugar do teste mostra o cartão "Teste de prompt · Em breve" (`components/agent/ProductConfigurator.tsx`, por volta da linha 2021).
- O `TestePrompt.tsx` está pronto, mas desligado. Ele simula o funil no navegador, então não reflete o motor real.
- O Laboratório de verdade (`app/gestao/laboratorio.py`) usa a configuração salva, conversa em memória e não envia nada. Só que ele aparece apenas em `/agentes/:id/laboratorio` (`telas/Agente.tsx`).

**Como os outros fazem:**
- **Dify:** "Debug e prévia" fica ao lado do editor.
- **Chatwoot Captain:** o Playground aceita regras temporárias e tem "Reset test setup". Embaixo de cada resposta, "Run details" mostra os cenários e regras usados, as ferramentas chamadas e se houve passagem para a equipe.
- **Typebot:** "Test" pode rodar no seu WhatsApp de verdade.

**Mudar:**
- Trocar o cartão "Em breve" por um painel que chama o Laboratório do servidor com o rascunho atual.
- Cada resposta mostra a etapa, os fatos extraídos, as travas acionadas, o que teria acontecido (card movido, etiqueta) e o custo em R$.
- Ter os botões "Recomeçar" e "Testar no meu WhatsApp" (só para números de teste).

**Arquivos:**
- `ProductConfigurator.tsx` (passo 3 e passo 6, Revisão);
- substituir a lógica de `TestePrompt.tsx`;
- servidor: `app/gestao/laboratorio.py` precisa aceitar um produto ativado ainda em rascunho.

### 2. Um só caminho para "meus agentes" no menu
**Valor alto, esforço baixo.**

**Hoje:**
- O menu (`componentes/Estrutura.tsx`, linhas 137 a 139) mostra **Biblioteca**, **Meus Produtos** e **Agentes**.
- "Agentes" (`telas/Agentes.tsx`) lista os agentes, com "Criar agente" levando à Biblioteca, e tem o Laboratório.
- "Meus Produtos" (`pages/MeusProdutos.tsx`) lista os produtos ativados, com o editor de 6 passos.
- Para quem não é técnico, são duas portas para a mesma coisa.

**Como os outros fazem:** um objeto central só (Dify: "Apps"; Typebot: "Bots"; Captain: "Assistentes"). A galeria de modelos é um botão "Criar" dentro dessa lista, não um item separado do menu.

**Mudar:**
- Um item "Meus agentes", com a lista e o botão "+ Novo a partir da Biblioteca".
- A Biblioteca fica como página de escolha, alcançada por esse botão ou por um item secundário.
- O Laboratório e as seções avançadas viram abas do mesmo agente.

**Arquivos:** `Estrutura.tsx`, `pages/MeusProdutos.tsx`, `telas/Agentes.tsx` e `telas/agenteSecoes.tsx`.

### 3. Rascunho, publicar e voltar versão
**Valor alto, esforço médio.**

**Hoje:**
- Salvar no editor (`pages/ProdutoEditor.tsx` → `ProductConfigurator` em modo edição) já muda o agente no ar.
- A revisão já calcula o que mudou, campo a campo, com antes e depois (`ProductConfigurator.tsx`, linhas 857 a 886).
- `telas/Historico.tsx` lista as alterações, mas não está no menu e não restaura nada.

**Como os outros fazem:**
- **Dify:** "Publicar" transforma o rascunho em versão no ar. Cada publicação fica na lista com autor e data. "Restaurar" carrega a versão antiga no rascunho, e ela só vai ao ar quando alguém publica.
- **Botpress Cloud:** o mesmo, por publicação.

**Mudar:**
- Botão **Publicar** com o resumo das mudanças que já calculamos.
- Lista "Versões" por agente (data, quem, o que mudou) e **Voltar para esta versão**.
- Aviso "há alterações não publicadas".
- O `MAPA_DO_SISTEMA.md` (seção 3) já previa "rascunho → testes → publicar → voltar versão".

**Arquivos:** `ProdutoEditor.tsx`, `ProductConfigurator.tsx` (passo 6) e `Historico.tsx`.

### 4. Checklist de primeiros passos que se marca sozinho (cliente e superadmin)
**Valor alto, esforço baixo.**

**Hoje:**
- O Início (`telas/Inicio.tsx`, por volta da linha 171) mostra alertas soltos, por exemplo "Conecte a Helena para começar", com os passos "Copie o token na Helena · Cole em Integrações".
- No fluxo novo quem faz essa parte é o superadmin ao habilitar a função de agente. **Vale conferir se esse texto ainda vale para o cliente.**

**Como os outros fazem:** Ticketz e Whaticket SaaS deixam a empresa se cadastrar. O whatsapp-saas guia a instalação inteira. O LíderHub (já citado) tem um checklist que se marca sozinho.

**Mudar:**
- No Início do cliente, um cartão "Primeiros passos", em que cada item se marca sozinho e o próximo passo tem um botão:
  1. conta habilitada;
  2. produto escolhido;
  3. ZapSign e modelo;
  4. primeiro teste no Laboratório;
  5. ativado em teste;
  6. ativado para todos;
  7. primeira conversa real;
  8. saldo.
- Em Contas do superadmin (`telas/AdminEscritorios.tsx`), uma coluna "progresso" com os mesmos passos, para ver quem travou onde.

**Arquivos:** `telas/Inicio.tsx`, `telas/AdminEscritorios.tsx` e `app/gestao/onboarding.py`.

### 5. Saúde do número e da conexão à vista
**Valor alto, esforço baixo.**

**Hoje:**
- O passo 1 lista os números da Helena como "ativo" ou "inativo", e "inativo" quer dizer "já usado por outro agente" (`ProductConfigurator.tsx`, por volta das linhas 434 e 1445).
- O "webhook conectado" e a "última mensagem recebida" só aparecem como alerta no Início.

**Como os outros fazem:**
- **Evolution Manager:** cada instância mostra o estado da conexão (conectado, desconectado, QR) e os eventos.
- **whatsapp-saas:** "Probar conexión" preenche os dados e confirma na hora.
- **Typebot:** testa o número antes de publicar e avisa do problema do nono dígito nos números brasileiros.

**Mudar:**
- No cartão de cada agente em "Meus Produtos" e no passo 1, mostrar:
  - um selo "Recebendo mensagens · última há 3 min";
  - o tipo do número (oficial ou não oficial, com o lembrete da janela de 24 h quando for oficial);
  - um botão **Testar conexão**, que confere a Helena, o webhook e o canal e diz o que fazer quando falha.

**Arquivos:** `pages/MeusProdutos.tsx`, `ProductConfigurator.tsx` (passo 1) e `telas/Integracoes.tsx`.

### 6. "Por que a IA respondeu isso?" em cada mensagem
**Valor alto, esforço médio.**

**Hoje:** a ficha do lead tem fatos e decisões (`telas/Conversas.tsx`, `components/conversas/PainelLateral.tsx`). A tela Erros (`telas/Erros.tsx`) mostra os problemas. Mas não há um "detalhe" ligado a cada resposta da IA.

**Como os outros fazem:** "Run details" do Captain embaixo de cada resposta, e os registros do Dify, com a entrada, os documentos usados e o tempo de cada passo.

**Mudar:** um ícone em cada mensagem da IA abre:
- a etapa e o agente que respondeu;
- os fatos usados;
- os trechos da base de conhecimento;
- as travas acionadas e por quê;
- o tempo e o custo em R$;
- a versão do prompt.

Isso ajuda o suporte da LawChat e o próprio escritório a entender por que a IA agiu de certo jeito, sem abrir o banco.

**Arquivos:** `components/conversas/BolhaMensagem.tsx`, `PainelLateral.tsx` e a API dos turnos gravados.

### 7. Carteira com previsão: "seu saldo dura cerca de X dias"
**Valor médio-alto, esforço baixo.**

**Hoje:** `telas/Carteira.tsx` mostra o disponível, o saldo, o bônus, o consumo do mês, as recargas e o extrato. O aviso de saldo (`componentes/AvisoSaldo.tsx`) só aparece quando já está acabando ou acabou.

**Como os outros fazem:**
- **LibreChat:** saldo com recarga automática.
- **ai-whatsapp-bot-builder:** aviso de cota com período de carência.
- **Whaticket SaaS:** aviso antes da fatura vencer.

**Mudar:**
- "No ritmo dos últimos 7 dias, o saldo dura cerca de 9 dias", com o botão Recarregar.
- Custo médio **por conversa** e **por contrato assinado**, que é o número que o advogado entende.
- Lembrete por WhatsApp quando faltarem 3 dias.
- Mais adiante, a opção "recarregar sozinho quando chegar a R$ X", só com aprovação do cliente a cada vez.

**Arquivos:** `telas/Carteira.tsx`, `components/dashboard/ConsumoCenter.tsx` e `AvisoSaldo.tsx`.

### 8. Base de conhecimento com "testar a busca" e FAQ sugerida
**Valor médio, esforço médio.**

**Hoje:** `components/agent/ConhecimentoManager.tsx` recebe documentos, e a FAQ e as objeções são escritas à mão no passo 3.

**Como os outros fazem:**
- **Dify:** "teste de busca" (digita uma pergunta e vê quais trechos a IA usaria).
- **Captain:** gera FAQs a partir dos documentos e sugere FAQs novas a partir de conversas resolvidas. O admin aprova.

**Mudar:**
- Uma caixa "Pergunte como um lead" que mostra os trechos encontrados e a nota de cada um.
- Uma lista "Perguntas que a IA não soube responder → transformar em FAQ", com aprovar e editar. A lista de lacunas já está planejada em `BASE_DE_CONHECIMENTO.md`.

**Arquivos:** `ConhecimentoManager.tsx` e a aba FAQ do `ProductConfigurator.tsx`.

### 9. Superadmin com semáforo de todas as contas
**Valor alto, esforço médio.**

**Hoje:** Contas (`telas/AdminEscritorios.tsx`) tem sincronizar, habilitar, acessar e limite de consumo. Para saber se uma conta está com problema é preciso entrar nela ou ir a "Erros da IA".

**Como os outros fazem:**
- **Chatwoot:** o console de superadmin lista as contas com os limites de cada uma (caixas, agentes) e liga ou desliga recursos por conta.
- **Whaticket SaaS:** mostra empresas vencidas e bloqueadas.
- **AstraCampaign:** cotas por empresa.

**Mudar:**
- Na lista de Contas, colunas de saúde:
  - webhook recebendo (sim ou não, e quando foi o último evento);
  - erros abertos;
  - saldo e dias restantes;
  - conversas nos últimos 7 dias;
  - agentes no ar.
- Filtros "com problema" e "sem uso há 7 dias".
- Uma chave por conta para recursos em teste, como TTS, triagem e follow-up.
- O "interruptor de emergência" do `MAPA_DO_SISTEMA.md` (seção 5) mora aqui.

**Arquivos:** `telas/AdminEscritorios.tsx` e `app/gestao/rotas_conta.py`.

### 10. Webhooks de saída simples (antes da API pública)
**Valor médio, esforço médio.**

**Hoje:** não há como o escritório avisar outro sistema (AdvBox, planilha, n8n próprio) quando "lead qualificado" ou "contrato assinado" acontece.

**Como os outros fazem:**
- **Chatwoot, Typebot e Evolution:** webhooks por evento.
- **ai-whatsapp-bot-builder:** mostra o jeito certo num projeto pequeno: assinatura HMAC, registro de entregas, novas tentativas e proteção para não chamar endereços internos.

**Mudar:**
- Em Ferramentas ou Integrações, "Avisar outro sistema": escolher o evento, colar a URL e clicar em "Enviar teste".
- Uma tabela das últimas entregas, com o resultado de cada uma.
- A API pública vem depois, com chave por escritório.

**Arquivos:** `telas/Ferramentas.tsx` ou `telas/Integracoes.tsx`; no servidor, reaproveitar a fila de ações (`app/acoes.py`).

---

## (d) Ideias de tela que valem copiar

1. **Editor com teste ao lado (Dify, Captain).**
   - **Esquerda:** o prompt da etapa com o "@".
   - **Direita:** uma conversa de teste.
   - **Topo do painel de teste:** um selo "testando o rascunho (não publicado)" e o seletor "começar na etapa: SDR, Closer…".
   - **Embaixo de cada resposta:** a linha cinza "Etapa SDR · 2 fatos novos · 1 trava (promessa de valor) · R$ 0,04 · ver detalhes".
   - **Botões:** "Recomeçar" e "Salvar esta conversa como cenário de teste".
2. **Painel de versões (Dify).**
   - Uma gaveta à direita com a lista "Rascunho atual", depois "v7, publicada ontem 18:02 por Ana · mudou: Closer, FAQ (+2)" e as versões anteriores.
   - Cada linha tem "Ver diferenças" (antes e depois lado a lado, como já fazemos na revisão) e "Restaurar no rascunho".
   - No topo do editor, o botão verde "Publicar" e um contador "3 mudanças não publicadas".
3. **Cartão de conexão do número (Evolution Manager, whatsapp-saas).**
   - Um cartão por número com:
     - foto e nome do perfil;
     - o selo "Conectado" (verde) ou "Sem mensagens há 2 h" (âmbar);
     - o tipo "API oficial" ou "não oficial";
     - "último evento há 3 min".
   - Embaixo, os botões "Testar conexão" (um passo a passo com ✓ e ✗: Helena, webhook, canal, primeira mensagem de teste) e "Abrir na Central".
4. **Mapa do funil, só de leitura (Typebot, Langflow).**
   - Na aba Agentes do passo 3, os agentes aparecem como caixas ligadas por setas: SDR → Closer → Contratos → Assinatura, com Desqualificado ao lado.
   - Cada seta mostra a condição da troca ("tem CAT e sequela") e quantas conversas passaram por ela nos últimos 30 dias.
   - Clicar numa caixa abre o prompt daquela etapa. Não é editor de fluxo: é para entender.
5. **Typebot, "onde as pessoas param".** Ainda no mapa, cada caixa leva a porcentagem de leads que pararam naquela etapa, para mostrar o gargalo sem precisar de relatório.
6. **Lista de contas com semáforo (console de superadmin do Chatwoot).**
   - Uma tabela com Conta, Agentes no ar, Recebendo, Erros, Saldo (dias), Conversas 7d e Progresso (barra de 8 passos).
   - Em cima, os filtros "Com problema (4)", "Sem uso (2)" e "Em ativação (3)".
   - No fim de cada linha, as ações Acessar, Pausar IA e Ver erros.
7. **Carteira com previsão (LibreChat, Whaticket SaaS).**
   - Um número grande, "R$ 312,40 disponível", e embaixo "dura cerca de 9 dias no ritmo atual".
   - Três números menores: "R$ 1,10 por conversa", "R$ 38 por contrato assinado" e "R$ 0 de bônus restante".
   - Um gráfico de barras por dia com uma linha do limite mensal.
8. **Detalhes da resposta (Captain "Run details").**
   - Uma gaveta aberta a partir de uma mensagem da IA, em seções que se recolhem: Etapa, Fatos usados (com o trecho do lead), Documentos consultados, Travas, Ações (card movido, etiqueta), Tempo e custo, Versão do prompt.
   - Um botão "Abrir no Laboratório a partir daqui".
9. **"Perguntas sem resposta" (sugestões de FAQ do Captain).**
   - Uma lista de cartões: a pergunta do lead, quantas vezes apareceu e uma resposta sugerida a partir dos documentos.
   - Os botões "Aprovar como FAQ", "Editar" e "Ignorar".
10. **Entregas de webhook (Chatwoot, ai-whatsapp-bot-builder).**
    - Uma tabela com Evento, Destino, Quando, Resultado (200, 500 ou tempo esgotado) e Tentativas.
    - Um botão "Reenviar" e, ao clicar na linha, o conteúdo enviado.

---

## (e) Plataformas pesquisadas

Estrelas e último envio de código consultados no GitHub em 25/11/2026.

Legenda de "Multi-conta": **sim** = várias empresas isoladas na mesma instalação.

### Plataformas de agentes e chatbots com painel

| Plataforma | Link | Estrelas | Último envio | Stack | Multi-conta | WhatsApp | Como cria o agente | Cobrança e limites | Admin |
|---|---|---|---|---|---|---|---|---|---|
| **Dify** | [langgenius/dify](https://github.com/langgenius/dify) | 161,9 mil | 26/11/2026 | Python, TypeScript | Espaços de trabalho com membros e papéis; vários espaços no plano Enterprise | Não nativo (via plugins ou pela Evolution API) | Fluxo visual (chatflow e workflow), agente com prompt, base de conhecimento com teste de busca; teste ao lado; versões com publicar e restaurar ([doc](https://docs.dify.ai/en/use-dify/build/version-control)) | Na nuvem, cota por plano; auto-hospedado sem cobrança | Membros, chaves de API por app, registros e anotações |
| **Langflow** | [langflow-ai/langflow](https://github.com/langflow-ai/langflow) | 157,0 mil | 26/11/2026 | Python, React | Usuários e projetos, sem isolamento de empresas | Não | Fluxo visual de componentes; Playground; API e MCP | Não | Simples (usuários) |
| **Open WebUI** | [open-webui/open-webui](https://github.com/open-webui/open-webui) | 159,6 mil | 25/11/2026 | Svelte, Python | Usuários e grupos com permissões, numa organização | Não | "Modelos" do espaço de trabalho com prompt de sistema, conhecimento e ferramentas | Não nativo | Painel admin com usuários, grupos, avaliações e feedback |
| **LibreChat** | [LibreChat-AI/LibreChat](https://github.com/LibreChat-AI/LibreChat) | 47,5 mil | 25/11/2026 | TypeScript | Usuários, com compartilhamento de agentes | Não | Construtor de agentes (prompt, arquivos, ferramentas, MCP) e marketplace de agentes | Saldo de tokens por usuário com recarga automática configurável | Configuração por arquivo |
| **Flowise** | [FlowiseAI/Flowise](https://github.com/FlowiseAI/Flowise) | 55,6 mil | 13/08/2026 (**arquivado**) | TypeScript | Espaços de trabalho na versão Enterprise | Não nativo | Fluxo visual (chatflow e agentflow), chat de teste | Não | O projeto foi comprado pela Workday em 2025 e encerrado em 2026 ([aviso oficial](https://flowiseai.com/sunset)). **Não adotar.** |
| **Botpress** | [botpress/botpress](https://github.com/botpress/botpress) | 15,0 mil | 24/11/2026 | TypeScript | Espaços de trabalho na nuvem | Integração oficial | Studio visual com nós "autônomos", base de conhecimento, emulador, versões publicadas | Na nuvem, cobra o gasto de IA | O repositório aberto hoje é de SDK e integrações; o Studio é da nuvem |
| **Typebot** | [baptisteArno/typebot.io](https://github.com/baptisteArno/typebot.io) | 10,6 mil | 07/11/2026 | TypeScript | Espaços de trabalho com membros | Só a API oficial, com o próprio app da Meta; teste no WhatsApp real ([doc](https://docs.typebot.com/deploy/whatsapp/overview)) | Fluxo visual de blocos, galeria de modelos, bloco Webhook | Planos (pode ficar desligado no auto-hospedado) | Resultados em tabela e abandono por bloco |
| **Rasa** | [RasaHQ/rasa](https://github.com/RasaHQ/rasa) | 21,4 mil | 24/07/2026 | Python | Não | Por conector | Código e YAML; o Rasa X foi descontinuado e o Studio é pago | Não | Pouco para quem não programa |
| **Hexabot** | [Hexastack/Hexabot](https://github.com/Hexastack/Hexabot) | cerca de 1,2 mil | ativo em 2026 | Node.js, TypeScript | Não descrito | Por canal ou extensão | v3: fluxos em YAML com ações, memória, RAG e MCP | Não | Não descrito na v3 |
| **Tiledesk** | [Tiledesk/tiledesk](https://github.com/Tiledesk/tiledesk) | 331 | 04/11/2026 | Node.js, MongoDB | Por projeto | Canal WhatsApp | Design Studio visual, bots com IA, passagem para humano | Versão Enterprise paga | Painel, chat ao vivo, API e webhooks |

### Atendimento com várias contas e IA (inclui os brasileiros)

| Plataforma | Link | Estrelas | Último envio | Stack | Multi-conta | WhatsApp | Como cria o agente | Cobrança e limites | Admin |
|---|---|---|---|---|---|---|---|---|---|
| **Chatwoot + Captain** | [chatwoot/chatwoot](https://github.com/chatwoot/chatwoot) | 40,6 mil | 25/11/2026 | Ruby on Rails, Vue | **sim** (contas) e console de superadmin | API oficial (Cloud, 360dialog, Twilio); não oficial via Evolution | Captain: documentos, FAQs (geradas e sugeridas), cenários com passagem, Playground, "Run details", Copilot para o atendente ([guia](https://www.chatwoot.com/hc/user-guide/articles/1738101547-creating-an-assistant-with-captain)) | Captain com créditos na nuvem; cada mensagem do Playground gasta um | Superadmin com contas, usuários, limites e recursos por conta; relatórios, automações, API e webhooks |
| **Evolution API + Manager** | [evolution-foundation/evolution-api](https://github.com/evolution-foundation/evolution-api) · [manager v2](https://github.com/evolution-foundation/evolution-manager-v2) | 10,2 mil · 26 | 23/11/2026 · 10/06/2026 | Node.js, TypeScript, Prisma | Várias instâncias com token próprio | QR (Baileys) e API oficial (Cloud) | Liga Typebot, Chatwoot, Dify, Flowise, OpenAI e n8n por instância, com gatilho por palavra-chave, espera para juntar mensagens e "parar o robô quando eu falar" | Não | O Manager mostra as instâncias, o estado, o QR e as integrações |
| **Evo AI** | [evolution-foundation/evo-ai](https://github.com/evolution-foundation/evo-ai) | 617 | 02/06/2025 | TypeScript, Python | Não confirmado | Pela Evolution API | Plataforma de agentes da mesma fundação | Não descrito | Sem atualização há mais de 1 ano |
| **Whaticket Community** | [canove/whaticket-community](https://github.com/canove/whaticket-community) | 2,1 mil | 13/10/2026 | Node.js, React | Não (uma empresa) | QR | Filas e respostas rápidas; sem IA no original | Não | Usuários, filas, conexões |
| **Whaticket SaaS** (forks) | ex.: [leopoldohuacasiv/waticketsaas](https://github.com/leopoldohuacasiv/waticketsaas) · [tópico whaticket](https://github.com/topics/whaticket) | dezenas por fork | variado | Node.js, React | **sim** (empresas) | QR (Baileys); alguns forks têm a oficial | Prompt da OpenAI por fila; "flowbuilder" nas versões novas (segundo anúncios) | Planos com limite de usuários, conexões e filas; faturas (Asaas e outros); empresa vencida bloqueada | Painel do superadmin com empresas e planos. Fonte fraca: forks e anúncios, código de origem confusa |
| **Press Ticket** | [rtenorioh/Press-Ticket](https://github.com/rtenorioh/Press-Ticket) | 291 | 27/08/2026 | Node.js, React | Não | QR | Fork brasileiro do Whaticket; chatbot por fila | Não | Usuários, filas, conexões |
| **Ticketz** | [ticketz-oss/ticketz](https://github.com/ticketz-oss/ticketz) | 322 | 25/11/2026 | Node.js, Docker | **sim** (cadastro de empresa) | QR | Herda o Whaticket SaaS; recursos de IA na versão PRO | Planos herdados do Whaticket SaaS (não confirmado na página) | Licença AGPL: quem vender modificado precisa abrir o código |
| **Izing** | [ldurans/izing.open.io](https://github.com/ldurans/izing.open.io) | 626 | 29/06/2024 (parado) | Node.js, Vue | **sim** (tenants) | QR, vários canais | Chatbot de fluxo | Não | Parado há mais de 2 anos |
| **Whazing SaaS** | [cleitonme/Whazing-SaaS](https://github.com/cleitonme/Whazing-SaaS) | 76 | 24/11/2026 | não informado | **sim** (marca própria, várias empresas) | API oficial (com Tech Provider) e outros canais | "Chatbot com IA" e Kanban | Tabela de valores; versão Premium | O repositório traz documentação e instalador; o código não parece estar ali |
| **WPPConnect Server** | [wppconnect-team/wppconnect-server](https://github.com/wppconnect-team/wppconnect-server) | 1,07 mil | 25/11/2026 | TypeScript | Sessões | QR | Não tem agente: é só a ponte | Não | Sem painel de agentes |
| **whatsapp-saas** (agente + inbox) | [Carlos-Dominguez-faber/whatsapp-saas](https://github.com/Carlos-Dominguez-faber/whatsapp-saas) | 46 | 01/10/2026 | Next.js, Supabase | **sim** (espaços isolados no banco, superadmin) | Oficial (YCloud ou Kapso) com "testar conexão" e uso junto com o celular | Prompt, ferramentas que se ligam e desligam, base com busca por vetores, passagem para humano, modelos da janela de 24 h | Não descrito | É o mais parecido com o nosso em stack (Supabase e React) |
| **AI WhatsApp Bot Builder** | [ahmedsaadawi13/ai-whatsapp-bot-builder](https://github.com/ahmedsaadawi13/ai-whatsapp-bot-builder) | 10 | 17/10/2026 | PHP, MySQL | **sim**, com 4 papéis | Provedor configurável (simulado) | Fluxo por palavra-chave e botões, base de conhecimento | Limites por plano com bloqueio e carência | API pública com chave; webhooks de saída assinados com registro e novas tentativas. **Projeto pequeno, mas bom modelo** |
| **AstraCampaign** | [AstraOnlineWeb/astracampaign](https://github.com/AstraOnlineWeb/astracampaign) | 76 | 10/12/2025 | TypeScript | **sim**, com cotas por empresa | Campanhas em massa | Não é atendimento | Cotas | Referência só para cotas e backup por empresa |

### Fontes de apoio
- Chatwoot Captain, guia oficial: [criar assistente](https://www.chatwoot.com/hc/user-guide/articles/1738101547-creating-an-assistant-with-captain) · [introdução](https://www.chatwoot.com/hc/user-guide/articles/1738101283-captain-_-introduction) · [instruções personalizadas](https://www.chatwoot.com/blog/captain-custom-instructions) · análise de terceiros: [eesel.ai](https://www.eesel.ai/blog/chatwoot-captain).
- Dify, controle de versões: [docs.dify.ai](https://docs.dify.ai/en/use-dify/build/version-control).
- Typebot e WhatsApp: [docs.typebot.com](https://docs.typebot.com/deploy/whatsapp/overview).
- Fim do Flowise: [flowiseai.com/sunset](https://flowiseai.com/sunset) · [compra pela Workday](https://newsroom.workday.com/2025-08-14-Workday-Acquires-Flowise,-Bringing-Powerful-AI-Agent-Builder-Capabilities-to-the-Workday-Platform).
- Busca no GitHub usada: `whaticket saas`, `multiatendimento whatsapp`, `atendechat`, `whatsapp saas ia`, `evolution api crm`, `ticketz`, `izing`, `flow builder whatsapp saas`, `chatwoot ai agent`. Os "atendechat" e "ZPRO" que aparecem são cópias de poucas estrelas, sem documentação própria ([busca](https://github.com/search?q=atendechat&type=repositories)), e não entraram na tabela.

### O que **não** copiar
- **Editor de fluxo com blocos e setas** (Typebot, Flowise, flowbuilder do Whaticket): ótimo para quem monta robô de menu, mas difícil para advogado, e quebra a regra "a IA conversa, o código decide".
- **Conexão por QR feita por nós** (Whaticket, Evolution): risco de bloqueio do número e de suporte; a Helena já resolve isso.
- **Código de origem duvidosa** (forks "SaaS" do Whaticket vendidos e vazados) e licença AGPL (Ticketz) não servem de base para o produto; servem só de referência de tela.
- **Plataformas paradas ou encerradas** (Flowise arquivado em 2026, Izing parado desde 2024, Rasa X descontinuado).
