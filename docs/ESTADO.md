# Estado do sistema LawChat IA (22/11/2026)

Princípio: **atendimento, inbox e CRM ficam na Helena (LawChat)**. Este sistema é a **IA** e a **gestão de tudo**, integrado pela API da Helena.
Testes: **195 passando** (Python, com Postgres local). A checagem das migrações agora espera 22 tabelas. O painel compila e foi conferido no navegador.

## O que existe

### Atendimento (IA)
- Webhook por escritório com segredo próprio (`/webhook/helena/{id}`); filtro (grupo, lista, reação, vazio, atraso, rajada, bloqueados, conta de outro escritório).
- Espera que junta mensagens **gravada no banco** (`responder_apos`) e trava por lead (`processando_ate`): um reinício não perde resposta e dois servidores não respondem o mesmo lead.
- Pausa quando a equipe fala (volta sozinha ou "só a equipe religa"); dupla conferência antes de enviar.
- Cérebro sem tools: extrator → código decide etapa → agente da etapa escreve → travas. Auditor de sinais (ex.: "não sabe ler") antes de pausar.
- **Fatos do sistema** no prompt (nome, telefone, primeiro contato, situação do contrato): a IA não contradiz o cadastro.
- Mídia: PDF, DOCX, XLSX, TXT (resumo acima de 2.000 caracteres), imagem (visão), áudio (transcrição).
- Conhecimento por agente: FAQ, objeções, dados do escritório e **documentos** (PDF, Word, Excel, texto até 8 MB). Os trechos que combinam com a conversa entram no prompt, até 6.000 caracteres por turno.
- Contrato ZapSign:
  - coleta dos dados como fatos, CEP preenche o endereço, confirmação e geração (versões, reserva, limite de 3 versões);
  - link, lembretes, webhook de assinatura e conferência quando o lead diz "assinei";
  - na assinatura, **reenvia o link** quando pedem e **gera nova versão** se o lead corrige um dado;
  - depois de assinado, **resumo do caso** como nota no atendimento.
- **Desligar/religar a IA pela Helena:**
  - pela etiqueta "🤖 IA Desativada" no contato (evento `CONTACT_TAG_UPDATE`);
  - por botão ou automação, com `POST /webhook/helena/{id}/ia`;
  - em todos os casos deixa nota com o código DES-… e cancela o follow-up.
- **Limite de consumo por escritório** (US$ por mês, definido pela equipe LawChat):
  - aviso em 80% e em 100%, como evento no painel e por WhatsApp no aviso "Consumo da IA perto do limite";
  - ao estourar, pausa a IA ou só avisa, conforme configurado.
- **Nota no chat dos problemas** (IA não respondeu, envio falhou, limite, cadastro):
  - no máximo 1 nota a cada 6 h por conversa;
  - a partir da segunda, mostra o primeiro aviso e o número de ocorrências.
- **Origem do lead:**
  - grava o anúncio (TRACK da Helena: link, clid, campanha, título) e as UTMs no primeiro toque;
  - deixa nota "📣 Lead veio de anúncio";
  - o TRACK nunca cria lead pausado.

### Produtos e criação de agente (cópia do agents-lawchat-main)
- Telas copiadas do sistema de referência com o mesmo visual (Tailwind + shadcn + tema LawChat verde, Inter): Biblioteca de produtos
  (categorias, busca, mídia, em breve), página do produto, assistente de ativação em 5 passos (Identidade com sincronização de
  números, Comportamento com delay/pausa/temperatura/modelo, Conteúdo com editor tiptap, edição rápida de {{campos}} e [[mídias]],
  agentes do funil, FAQ, objeções, dados do escritório e conhecimento, Integrações com ZapSign, Revisão com checklist), Meus produtos
  (pausar, lixeira, excluir, editar) e o admin do catálogo (produtos, agentes por papel, frases de transferência, documentos padrão).
- Login como o da referência: entrada pela Helena com tela de validação, login da equipe em /login e impersonificação
  ("Como cliente" com a faixa "Voltar para admin"); o seletor "Ver como" saiu.
- Motor: agentes do catálogo (produto `catalogo`) usam o prompt completo de cada papel; a resposta diz se transfere o lead
  (só para os destinos do prompt) ou aciona ferramenta (Buscar CEP, ZapSign); a frase exata de transferência também passa o lead;
  balão com link de mídia vira arquivo; temperatura do assistente vai para o modelo.
- Base de conhecimento como a da referência: arquivo ou texto colado, trechos de 3.000 caracteres com vetor
  (text-embedding-3-small), situação Indexando/Pronto/Erro, documentos padrão do produto copiados travados ao ativar.
- Biblioteca de mídia por escritório (até 200 MB, 50 MB por arquivo), servida em /midia para os prompts.
- Contrato da API: `docs/API_PRODUTOS.md`.
- **Importar o catálogo do sistema antigo:** no Supabase (AGENT WEAVER), rode `docs/EXPORTAR_CATALOGO.sql` no SQL Editor
  (só leitura, só catálogo) e baixe o resultado. No painel: LawChat › Produtos (catálogo) › **Importar catálogo** mostra a
  prévia (o que cria e o que atualiza, avisos) e grava ao confirmar. Também por linha de comando:
  `.venv/Scripts/python -m app.catalogo_importar catalogo.json --simular` (sem `--simular` grava).
  Leva produtos, os agentes de cada papel com os prompts, FAQ/objeções/regras (do produto e de cada agente), dados do
  escritório, follow-up por etapa, frases de transferência e documentos padrão. Re-importar atualiza, não duplica.
  Cada produto guarda o id de lá (`id_origem`): renomear lá muda o endereço aqui sem misturar com outro produto.
  Documentos padrão criados aqui no admin nunca são desligados pela importação (só os que vieram de lá, `id_externo`).
  Frase de transferência alterada lá é repassada aos agentes já ativados daquele produto. Arquivo de documento sem texto
  só é baixado do Storage do Supabase (https, `*.supabase.co/storage/v1/object/`), com limite de 8 MB e de tempo.

### Automações ("quando isto acontecer, faça aquilo")
- Gatilhos: lead novo, cada etapa, pedidos do lead, cada sinal, contrato gerado/assinado/falhou, trava, falha da IA.
- Ações pela fila com novas tentativas (1, 5, 30, 120 min): mover card (nunca para trás), etiquetas, nota, **troca de departamento por regra**, aviso à equipe por WhatsApp, mensagens do contrato.

### Gestão (painel)
- Login: "Acesso restrito" (cliente entra pela Helena, sem senha) e "Acesso da equipe". Equipe LawChat também entra pela conta LawChat na Helena.
- Papéis: dono, equipe LawChat, gestor, atendente. **Ver como** gestor/atendente; **Como cliente** na lista de escritórios; responsável LawChat por escritório.
- Assistente de agente: Modelo → Identidade (sincroniza números) → Comportamento → Conteúdo → Integrações → Revisão (checklist + ativar em teste).
- Ativação completa: confere Helena, número, cria/corrige webhook, alcance, etapas, chave de IA, CRM, departamento, ZapSign, números de teste.
- Outras telas:
  - Biblioteca de modelos: criar, publicar, salvar agente como modelo.
  - Avisos à equipe.
  - Integrações: Helena, CRM, OpenAI própria, ZapSign com ligação de variáveis, **Desligar a IA pela Helena**.
  - Erros, Histórico, Equipe LawChat.
- **Início:**
  - consumo do mês com a barra do limite;
  - **funil** por agente, em 7, 30 ou 90 dias: etapa alcançada, conversão e contratos assinados;
  - **leads por origem** (campanha).
- **Escritórios:** coluna "Consumo do mês" e editor do limite.
- Animações em todo o painel e **menu circular flutuante** com atalhos.

## Para rodar de verdade
1. Aplicar no Supabase (SQL Editor): `db/migracoes/001_agentesia_nucleo.sql` e `002_agentesia_gestao.sql` (desfazer: `desfazer_002.sql`).
2. `.env` do servidor:
   - obrigatórias: `AGENTESIA_BANCO_URL`, `AGENTESIA_SEGREDO_SESSAO`, `AGENTESIA_WEBHOOK_SEGREDO`, `AGENTESIA_URL_PUBLICA` (https), `OPENAI_API_KEY`, `AGENTESIA_MODELO`;
   - opcionais: `AGENTESIA_HELENA_HANDOFF_SEGREDO`, `AGENTESIA_HELENA_CONTA_LAWCHAT` + `AGENTESIA_HELENA_TOKEN_LAWCHAT`, `AGENTESIA_HELENA_TOKEN_PARCEIRO`, `AGENTESIA_MODELO_AUDITOR` (padrão `gpt-6-luna`).
3. Criar o dono: `.venv/Scripts/python -m app.gestao.criar_admin email "Nome"`.
4. Escritório (ex.: Sousa e Costa): token da conta Helena em Integrações → agente pelo assistente → ativar em teste com o número de teste.
5. Demonstração local: `db/testes/semear_demo.py` (três fases, explicadas no topo do arquivo).

### Follow-up (pronto)
- Agente de follow-up com prompt próprio (e modelo de IA) por agente, sem mensagem fixa.
- Configura-se o fluxo de cadência (padrão 1h, 5h, 1, 3, 7, 15 e 30 dias), horário (seg–sáb 8h–20h), intervalo mínimo, etapas, instrução extra por etapa e desistência.
- Fila `agentesia_followups`:
  - agenda depois de cada resposta da IA;
  - cancela quando o lead ou a equipe falam;
  - confere tudo na hora do envio;
  - no número oficial, depois de 24 h, usa o modelo aprovado escolhido;
  - 3 falhas pulam o passo.

### Painel
- Conversas saíram do painel (a conversa é na Helena). Agente com página de cartões e submenu no menu lateral.
- Menu lateral flutuante (recolhe para ícones), barra superior em pílula com busca Ctrl K, avisos, ajuda.

## Pendências
0. Trazer os prompts reais do catálogo (BPC/LOAS etc.): a importação está pronta; falta o arquivo exportado do Supabase
   (`docs/EXPORTAR_CATALOGO.sql`) ou o conector do Supabase autorizado.
1. Teste com a conta real do Sousa e Costa: precisa do token da Helena, de uma URL pública e da 001/002 aplicadas no Supabase.
2. Provedor Tramitação (precisa da documentação da API).
3. Classificar o produto pelo anúncio com IA (o legado fazia "UTM → PRODUTO"); hoje a origem é gravada e mostrada, sem classificar.
4. Horário comercial do atendimento da IA; central de avisos da equipe LawChat (1 aviso a cada 30 min por falha).
