# Pesquisa: o nosso agente de leads comparado com o mercado

Esta pesquisa compara o motor do LawChat IA com projetos abertos, guias técnicos e produtos comerciais. É para o dono do produto, sem jargão.

Foi feita em 25/11/2026 só com leitura. Nenhum código foi alterado e nenhuma API de IA foi chamada.

- **O que li do nosso lado:** `MAPA_DO_SISTEMA.md`, `DESENHO.md`, os documentos em `docs/`, `app/cerebro/turno.py`, `app/cerebro/catalogo.py`, `app/pipeline.py` e partes de `app/followup/`, `app/memoria.py`, `app/cerebro/travas.py`, `app/cerebro/extrator.py`, `app/avaliacao/juiz.py` e `app/modelo.py`.
- **Projetos abertos:** a fonte é o README e a API pública do GitHub. O código deles não foi lido. Estrelas e datas foram consultadas em 25/11/2026.
- **Produtos comerciais:** os dados vêm das páginas dos próprios fornecedores.

---

## (a) Resumo em 10 linhas

1. **A estrutura está certa.** O padrão mais usado no mercado é um funil de agentes por etapa, com o "agente ativo" gravado no banco e saída em formato fixo (JSON). É o mesmo padrão "swarm" do LangGraph e o dos handoffs do OpenAI Agents SDK. Num teste do LangChain, ele saiu um pouco melhor que o padrão de um agente "chefe" que distribui as tarefas.
2. **Acima do mercado (1):** a camada do WhatsApp. Juntamos as mensagens picadas com o prazo gravado no banco e descartamos a resposta quando chega mensagem nova. Também pausamos a IA quando um humano fala e retomamos os turnos depois de uma queda. A maioria dos projetos abertos guarda isso só na memória do servidor.
3. **Acima do mercado (2):** as travas contra promessa, dado inventado e laço de repetição. O extrator só aceita um fato se vier com o trecho do lead que o prova. Cada decisão fica gravada com o motivo. Nenhum projeto aberto parecido tem as três coisas juntas.
4. **Acima do mercado (3):** o fluxo de contrato pela ZapSign. Ele confere os dados e o CPF, refaz o contrato quando o lead corrige um dado e evita laços. Só um repositório de demonstração chega perto.
5. **Acima do mercado (4):** a janela de 24 h do número oficial. Fora dela, o follow-up sai como modelo aprovado.
6. **Abaixo do mercado (1):** no motor do catálogo, quem decide trocar de etapa é a IA. O código só filtra a troca. Isso contraria a nossa própria regra ("a IA conversa, o código decide"). Rasa CALM e Parlant fazem o contrário: a IA preenche campos e o código decide a passagem.
7. **Abaixo do mercado (2):** a passagem para um humano vai sem um resumo pronto do caso. Também não temos nota de temperatura do lead (quente, morno ou frio) nem um modo de rascunho em que o humano aprova antes de enviar. Intercom, Kommo, Chatwoot e Blip já oferecem isso.
8. **Abaixo do mercado (3):** a avaliação tem cenários e um juiz de IA, o que já está acima da média. Mas ainda falta medir se o agente acerta em todas as repetições do mesmo cenário (o "pass^k"). O juiz dá notas de 1 a 5, quando o recomendado é "passa ou falha", calibrado com uma pessoa.
9. **Riscos de norma:** o follow-up vem ligado por padrão, com 7 toques ao longo de 30 dias, inclusive para quem nunca respondeu. Isso pede cuidado com a regra da OAB contra captação e com a nota de qualidade do número na Meta. Os dados de saúde e o CPF vão ao provedor de IA sem mascaramento.
10. **Veredito:** não é preciso mudar a arquitetura. Os ganhos estão em:
    - pôr a decisão de troca no código, com os fatos que já extraímos;
    - fazer uma passagem "quente" para o humano;
    - endurecer a avaliação;
    - ajustar o follow-up às regras da OAB e da Meta.

---

## (b) Padrão do mercado × como fazemos × veredito

Legenda do veredito:
- **igual**: fazemos como o mercado.
- **melhor**: fazemos acima do padrão.
- **falta**: não temos.
- **diferente de propósito**: escolha consciente.

| Tema | Padrão do mercado (fonte) | Como fazemos | Veredito |
|---|---|---|---|
| Organização da conversa | Agentes especialistas por etapa que passam o lead entre si, com o agente ativo lembrado (langgraph-swarm, openai-cs-agents-demo, chatflow-agent) | Um papel por etapa (SDR, Período de Graça, Closer, Contratos, Assinatura, Desqualificado), com a etapa gravada no lead | **igual** |
| Quem decide a troca de etapa | Rasa CALM e Parlant: a IA emite comandos ou preenche campos, e o código decide. No OpenAI SDK, a troca é uma ferramenta que o código pode barrar (`on_handoff`) | Há dois caminhos. No **motor antigo** (`produto`), o código decide pelos fatos. No **motor do catálogo** (o que os escritórios usam), a IA decide em `transferir_para`, e o código só barra a troca para trás ou cedo demais e uma vez por pergunta aberta | **falta** (no catálogo) |
| Formato da resposta | Saída estruturada com schema estrito, em que o destino é uma lista fechada de opções (OpenAI e Anthropic structured outputs) | Schema estrito (`strict: True`), com `transferir_para`, `ferramenta` e `notificacao` em listas fechadas (`catalogo.esquema`, `modelo.py:338`) | **igual** |
| Ação com efeito real | A ação é uma chamada de ferramenta de verdade, validada em código | `ferramenta: "zapsign"` é um campo da resposta; o pipeline confere os dados e gera o contrato numa fila | **igual** (outra forma, mesmo efeito) |
| "@" para trocar de agente | Os projetos abertos não têm. O equivalente é a "tool de handoff" | O "@" é só a forma de quem escreve o roteiro indicar o destino. Ele vira uma opção da lista fechada e nunca chega ao lead | **diferente de propósito** (bom para quem não programa) |
| Rede de segurança da troca | Não existe no mercado: troca sem tool é tratada como erro | Se a IA escrever a frase de passagem e esquecer o campo, o sistema troca pela frase, mesmo com paráfrase de 85% | **diferente**, e arriscado (ver d.2) |
| Juntar mensagens picadas | Buffer de 3 a 10 s, com teto e trava por conversa (lull, n8n 19116, WalissonVinicius) | Espera de 15 a 90 s conforme o tamanho da mensagem, com prazo gravado no banco, reserva do lead e descarte se chegar mensagem nova | **melhor** |
| Pausa quando o humano fala | Bloqueio de 5 a 30 min ao detectar mensagem do operador (paulogarbo, zappaz-mastra, lull) | Pausa configurável (padrão 15 min), etiqueta e nota na Helena, volta sozinha e não responde por cima da equipe | **melhor** |
| Memória | Janela recente mais um resumo ao passar de um limite, mais fatos estruturados (LangGraph, Anthropic context engineering) | 40 mensagens inteiras, uma ficha do começo refeita a cada 20 mensagens e fatos com trecho de prova | **igual** (os fatos com prova são **melhor**) |
| Barreiras na saída | Em camadas: regras baratas em código primeiro, juiz de IA só onde há nuance, e passagem para humano após falhas repetidas (OpenAI practical guide) | Travas em código (promessa, termos proibidos, endereço inventado, mídia fora do roteiro, CPF pedido de novo), duas tentativas e, se insistir, pausa e passagem à equipe; auditor de IA só para os sinais | **igual**, mas as regex causam falsos positivos (ver d.4) |
| Base de conhecimento | Responder só com o trecho recuperado e dizer "vou confirmar" quando não houver fonte (Anthropic, reduzir alucinação) | Busca por palavras e vetores, regra "só das fontes" e trava `fato_sem_fonte` | **igual** |
| Follow-up | 2 a 3 toques por semana no máximo; reativação em 30, 60 e 90 dias com variação (Conversica); só para quem deu opt-in (Lindy, Meta) | Cadência de 1 h, 5 h, 24 h, 72 h, 7, 15 e 30 dias, texto escrito pela IA, horário comercial, intervalo mínimo e modelo aprovado após 24 h; vem ligado por padrão | **igual** na técnica, **risco** de norma (ver d.7) |
| Opt-out | Atender qualquer pedido de parar (política da Meta) | A intenção `pediu_para_parar` encerra o lead e cancela o follow-up | **igual** |
| Passagem para humano | Passagem "quente", com perfil, resumo e o que o bot já tentou (Twilio, Intercom, Chatwoot) | Pausa, etiqueta e aviso à equipe. O aviso leva a mensagem do lead cortada em 500 caracteres. Não há resumo do caso feito na hora | **falta** |
| Nota do lead (quente, morno, frio) | Padrão nos templates de n8n e no EasyJur; ICP ≥ 7 avisa o dono (b2b-sdr-agent-template) | Não temos; há fatos e decisões, mas não uma nota | **falta** |
| Rascunho para o humano aprovar | Chatwoot Copilot, Kandid AgentSDR, Sara (OFF, OBSERVE, SEMI, FULL), whatsapp-closer-agentkit | Não temos | **falta** (útil em honorários e contrato) |
| Agendamento de reunião | Quase todo SDR comercial (Calendly, Google Calendar) | A regra fixa é "atendimento só por mensagem" | **diferente de propósito** |
| Avaliação | 20 a 50 casos tirados de falhas reais; usuário simulado; pass^k; juiz binário calibrado com humano (Anthropic evals, tau-bench, Hamel Husain); asserção de handoff (Intercom Fin Evals) | 6 cenários base, mais 29 do Sousa & Costa e da triagem; lead simulado; checagens objetivas; juiz de 7 critérios com nota de 1 a 5 (calibração prevista para ≥ 80%) | **igual** a **melhor** que os projetos abertos; **falta** pass^k e juiz binário |
| Custo e latência | Prefixo do prompt estável para o cache; modelo menor para roteamento e extração; medir p50 e p95 | Prompt de sistema fixo por papel, de propósito para o cache; extrator, etapa e auditor com modelos grandes por padrão; limite de 180 s por turno | **igual** no cache, **falta** modelo menor e métrica de latência |
| Guardrail de assunto | A Meta proíbe, desde 15/01/2026, assistentes de IA de uso geral; o bot de empresa precisa ficar no tema do negócio | Regras de conduta e de não inventar; sinal `outro_beneficio` | **igual** |
| Dados sensíveis | Mascarar dados pessoais antes de enviar à IA (Sara); LGPD, art. 11 | CPF e RG não são repetidos na saída, mas vão para a IA na entrada | **falta** (ver d.8) |
| Triagem (vários produtos por número) | Agente de triagem que encaminha a especialistas (openai-cs-agents-demo, Sistema-SDR-Multiagentes) | Desenhado em `docs/AGENTE_TRIAGEM.md`, ainda não implementado | **falta** (já planejado) |

---

## (c) Os 10 aprendizados para aplicar, por valor × esforço

### 1. Trocar de etapa só com as condições cumpridas, conferidas pelo código
**Valor alto, esforço baixo.**

- **De onde vem:** `on_handoff` do OpenAI SDK, Rasa CALM e Parlant.
- **O que fazer:** hoje a IA preenche `transferir_para` e o código só barra a troca para trás ou cedo demais. Já existe a configuração `perguntar_antes_de_transferir` (`app/cerebro/catalogo.py:86`), mas cada escritório precisa ligar.
- **Proposta:** tornar padrão, por produto da biblioteca, uma lista mínima de fatos por destino. Por exemplo:
  - para o Closer: aposentado, advogado no caso e sequela respondidos;
  - para Contratos: aceite registrado pelo extrator.

  Se faltar algum, a troca espera e a IA faz a pergunta que falta.
- **Problema que resolve:** o lead que chega ao Closer sem a checagem de aposentadoria (item 4 do `DIAGNOSTICO_RODADA_REAL`) e o "não sei" tratado como aceite (item 5).
- **Arquivos:** `app/cerebro/turno.py` (`_destinos_permitidos`, l.556, e `_segurar_transferencia`, l.1251), `app/cerebro/catalogo.py` (l.86) e a configuração padrão do produto em `app/catalogo_importar.py`.

### 2. Limitar a "troca pela frase"
**Valor alto, esforço baixo.**

- **De onde vem:** nenhum projeto aberto troca de agente lendo o texto da resposta. A troca é sempre uma ação explícita.
- **O que fazer:** manter a rede de segurança só com a frase **exata** e nunca para `desqualificado`. Desqualificar alguém por paráfrase de 85% é a decisão mais cara de errar.
- **Medida:** o evento `troca_pela_frase` mostra quantas vezes isso acontece; vale medir antes e depois.
- **Arquivos:** `app/cerebro/turno.py` (l.406–410, `parafrase=True`) e `app/cerebro/catalogo.py` (`transferencia_pela_frase`, perto do fim do arquivo).

### 3. Passagem "quente" para o humano
**Valor alto, esforço baixo a médio.**

- **De onde vem:** Twilio, Intercom e Chatwoot; a política da Meta exige caminho claro para humano.
- **O que fazer:** toda pausa (sinal, `analise_manual`, `trava_persistente`, `pedido_repetido`, `pediu_humano`) gera uma nota na Helena com:
  - quem é o lead, o caso e o que já respondeu (a ficha de `app/memoria.py` mais os fatos vigentes);
  - o motivo da pausa, em português;
  - o que falta descobrir;
  - a última pergunta feita pela IA.
- **Arquivos:** `app/notificacoes.py` (hoje corta a mensagem em 500 caracteres, l.58), `app/automacoes.py` e `app/pipeline.py` (`_nota_de_problema`, l.1131).

### 4. Avaliação mais dura: pass^k, juiz "passa ou falha" e checagem da passagem
**Valor alto, esforço médio.**

- **De onde vem:** Anthropic "Demystifying evals", tau-bench, Hamel Husain e Intercom Fin Evals.
- **O que fazer:**
  - Rodar cada cenário 3 vezes e só aprovar com 3 de 3 (pass^3). Um agente que acerta 75% das vezes acerta as 3 rodadas só em cerca de 42% dos casos.
  - Trocar as notas de 1 a 5 do juiz por "passa ou falha" com justificativa, calibrado contra os rótulos do dono.
  - Em todo cenário, conferir a etapa final e se a passagem aconteceu quando devia, e só quando devia.
  - Criar cenários do que **não** pode acontecer: desqualificar quem é viável, chamar a ZapSign sem o "está certo".
- **Arquivos:** `app/avaliacao/juiz.py` (l.30, `CRITERIOS`), `app/avaliacao/executar.py` (l.130, `rodar_bateria`), `app/avaliacao/checagens.py` e `avaliacao/cenarios/`.

### 5. Follow-up dentro das regras da OAB e da Meta
**Valor alto (risco), esforço baixo.**

- **De onde vem:** Provimento OAB 205/2021 (veda captação e mala direta para quem não autorizou), limites de marketing por usuário e nota de qualidade da Meta, e o guia de cadência da Wati.
- **O que fazer:**
  - Cadência padrão de no máximo 4 toques: 1 h, 24 h, 72 h e 7 dias.
  - Para quem **nunca respondeu**, no máximo 2.
  - No penúltimo toque, uma frase do tipo "se preferir que eu não mande mais mensagens, é só dizer".
  - Painel com a taxa de bloqueio e de "pare" por escritório.
- **Ressalva:** o follow-up ligado por padrão foi decisão do dono em 25/11; a mudança está na cadência, não no interruptor.
- **Arquivos:** `app/followup/regras.py` (l.29, `CADENCIA_PADRAO`), `app/followup/padrao.py` e `app/followup/servico.py`.

### 6. Nota de temperatura do lead (quente, morno, frio)
**Valor médio-alto, esforço médio.**

- **De onde vem:** templates de n8n (BANT e seguros), EasyJur Talk e b2b-sdr-agent-template.
- **O que fazer:** calcular **em código**, a partir dos fatos que já extraímos (vínculo, sequela, data, aceite, objeções), uma nota de 0 a 100 e uma faixa.
- **Para que serve:** ordenar a fila da equipe, pôr etiqueta na Helena e priorizar o follow-up. Não é preciso chamar a IA de novo.
- **Arquivos:** novo módulo em `app/cerebro/` chamado pelo `app/cerebro/turno.py` no fim do turno, e etiqueta em `app/automacoes.py`.

### 7. Travas em duas camadas: a regex aponta, o juiz pequeno decide
**Valor médio-alto, esforço médio.**

- **De onde vem:** guardrails do OpenAI SDK e "parallel guardrail" da Anthropic.
- **Problema:** as regex de promessa e de termos proibidos já pausaram leads por frases inocentes, como "100% online" (item 1 do diagnóstico).
- **O que fazer:**
  - A regex continua como filtro barato.
  - Quando ela acusar algo que pode ser falso positivo, um modelo pequeno confirma antes de mandar refazer.
  - Uma trava "leve" nunca pausa o lead.
- **Arquivos:** `app/cerebro/travas.py` (l.17–40, `PROMESSAS` e `TERMOS_PROIBIDOS`), `app/cerebro/catalogo.py` (`conferir`) e `app/cerebro/turno.py` (l.431–463).

### 8. Modelos menores onde dá, e medir o tempo do turno
**Valor médio, esforço baixo.**

- **De onde vem:** guia de latência da OpenAI e "Building effective agents" da Anthropic, que sugere modelo menor para roteamento.
- **O que fazer:**
  - Testar o extrator e o auditor com modelo menor, pela bateria de cenários.
  - Registrar o tempo de cada etapa do turno (extrator, auditor, etapa, envio) e mostrar p50 e p95 no painel.
  - Hoje um turno pode ter de 3 a 5 chamadas de IA.
- **Arquivos:** `app/pipeline.py` (l.1349 extrator, l.1359 auditor, l.1361 etapa) e `app/consumo.py`.

### 9. Modo rascunho (copiloto) nos passos sensíveis
**Valor médio, esforço médio-alto.**

- **De onde vem:** Chatwoot Copilot, Kandid AgentSDR, whatsapp-closer-agentkit e Sara.
- **O que fazer:** uma opção por papel, por exemplo Closer na hora dos honorários ou Contratos. Nela a resposta da IA vira rascunho na Helena (nota privada) e o atendente aprova.
- **Para quem serve:** escritórios novos, enquanto ganham confiança. Também ajuda na exigência da OAB de manter o advogado no comando.
- **Arquivos:** `app/pipeline.py` (`_enviar`, l.1365) e a configuração do papel em `app/cerebro/catalogo.py`.

### 10. Um motor só
**Valor médio (manutenção), esforço alto.**

- **De onde vem:** a lição da Anthropic: a solução mais simples que funciona.
- **Problema:** `turno.py` tem dois caminhos. Um é o produto Auxílio-Acidente, com a etapa decidida pelo código (l.206–283). O outro é o catálogo (l.286–553). Cada um tem as suas travas e a sua forma de passar etapa.
- **O que fazer:** levar o que o primeiro tem de bom para o segundo (a decisão pelos fatos, como no item 1) e aposentar o caminho antigo.
- **Arquivos:** `app/cerebro/turno.py`, `app/cerebro/produto.py`, `app/cerebro/auxilio_acidente.py` e `app/cerebro/agente.py`.

---

## (d) Riscos e erros de arquitetura encontrados no código

Em todos os itens, as linhas são de 25/11/2026.

1. **A regra principal não vale no motor do catálogo.**
   - `turno.py:6` diz "decisão de etapa (código)" e o `DESENHO.md` diz "a IA conversa e extrai; o código decide".
   - Mas `catalogo.py:105` diz "o código não decide etapa (o agente do papel decide)".
   - Em `turno.py:404-410` e `:477`, o destino vem da IA. O código só barra a troca para trás (`_destinos_permitidos`, l.556), cedo demais (`_troca_precoce`, l.611) ou com pergunta em aberto (`_segurar_transferencia`, l.1251).
   - **Efeito real:** o lead chega ao Closer sem a checagem de aposentadoria (diagnóstico, item 4).
2. **A troca pode acontecer pela frase.**
   - Em `turno.py:406-410`, se a IA não marcar o destino mas escrever algo parecido com a frase de passagem (85% das palavras, `catalogo.tem_frase`), a troca acontece.
   - Vale para qualquer destino, inclusive `desqualificado`.
   - **Risco:** troca errada calada, sem a IA ter decidido.
3. **Dois motores no mesmo arquivo.**
   - `turno.py:203-204` desvia para `_turno_catalogo`.
   - O resto de `_processar` (l.206–283) é o motor antigo, com outras travas: `travas.conferir` num, `catalogo.conferir` mais `_guardas_do_catalogo` no outro.
   - Uma correção feita num caminho pode faltar no outro.
4. **Regex que pausam lead por falso positivo.**
   - `travas.py:17-40` (`PROMESSAS`, `TERMOS_PROIBIDOS` com "12 meses", "24 meses") e o fluxo em `turno.py:431-439`: duas reprovações seguidas levam à mensagem fixa e à pausa.
   - O diagnóstico de 25/11 mostrou o cenário 06 pausando 3 de 3 vezes por "100% online".
   - Parte já foi corrigida, mas o desenho continua frágil: cada frase nova de escritório pode disparar a trava.
5. **Custo e tempo por turno.**
   - Um turno chama o extrator, o auditor (um por sinal) e a etapa (até 2 vezes), todos com modelo grande por padrão: `config.py:41` `gpt-4.1`; auditor fixo em `pipeline.py:1359` (`gpt-6-luna`, pela variável de ambiente).
   - O limite do turno é 180 s (`pipeline.py:508`). Não há medição de p95 por etapa.
6. **A janela do histórico está definida em dois lugares.**
   - `turno.py:350` manda as últimas 60 mensagens, mas o repositório só entrega 40 (`banco/postgres.py:460`, `memoria.JANELA = 40`).
   - Hoje não causa erro. Mas quem aumentar um dos números muda o custo sem perceber.
7. **Follow-up forte demais para a norma.**
   - `followup/regras.py:29`: 7 toques até 30 dias, ligado por padrão (`docs/FOLLOWUP.md`), também para quem nunca respondeu.
   - **Riscos:** captação pela OAB (Provimento 205/2021, art. 3º e anexo) e queda da nota de qualidade do número oficial na Meta (bloqueios e denúncias).
8. **Dados sensíveis vão para a IA sem mascaramento.**
   - CPF, RG, laudos e CID entram no conteúdo do extrator e da etapa.
   - Não achei mascaramento em `app/modelo.py` nem em `app/cerebro/`.
   - Pela LGPD, saúde é dado sensível (art. 5º, II, e art. 11).
   - **Mínimo:** contrato de tratamento com o provedor, retenção zero onde houver e mascarar o CPF depois de conferido.
9. **Desqualificação automática.**
   - A IA pode encerrar o lead como desqualificado. A LGPD (art. 20) dá direito a pedir revisão de decisão só automatizada.
   - O sistema já grava o motivo. Falta um caminho simples de revisão pela equipe (lista "desqualificados da semana") e uma frase ao lead dizendo que a equipe pode reavaliar.
10. **Juiz com notas de 1 a 5.**
    - `avaliacao/juiz.py:3` e `:30` usam notas de 1 a 5, e a calibração com o dono ainda não foi feita.
    - Notas assim mudam de uma rodada para outra. Até calibrar, o juiz não deve decidir publicação, como o próprio arquivo já diz.

**O que parece arriscado e não é:**
- A espera e as travas por lead ficam na memória do processo (`pipeline.py:55-57`). Mas a reserva do lead no banco (`pipeline.py:546-556`), o prazo gravado (`_falta_para_responder`) e `retomar_pendentes` cobrem dois servidores e quedas.
- Isso está melhor que a maioria dos projetos abertos.

---

## (e) Projetos abertos e fontes

### Os 5 mais parecidos com o nosso, comparados um a um

| # | Projeto | O que eles fazem melhor | O que nós fazemos melhor |
|---|---|---|---|
| 1 | **andrepdede/agent-handoff-demo** (https://github.com/andrepdede/agent-handoff-demo). TypeScript, 0 estrelas, atualizado em 28/10/2026. WhatsApp pela Evolution API: vendas → jurídico (contrato) → financeiro (link de pagamento), com um orquestrador na frente | <ul><li>Máquina de estados explícita, com registro de cada passagem.</li><li>Estado "humano" quando a confiança fica abaixo de 0,5.</li><li>15 casos que medem a precisão e o recall da passagem para humano.</li></ul> | <ul><li>Estado no banco (o deles é só em memória).</li><li>Fila e novas tentativas.</li><li>Webhook com segredo.</li><li>Travas, extrator com prova, ZapSign de verdade e follow-up.</li></ul> |
| 2 | **GustavoBaranda/chatflow-agent** (https://github.com/GustavoBaranda/chatflow-agent). Python, 24 estrelas, atualizado em 25/11/2026. Agentes em "swarm" para WhatsApp Cloud API e Telegram | <ul><li>A passagem é uma ferramenta tipada (`transfer_to_x`), com limite de 5 passagens por turno.</li><li>O turno que falha desfaz o estado.</li></ul> | <ul><li>Junta mensagens picadas.</li><li>Pausa quando o humano fala.</li><li>Follow-up, base de conhecimento e travas de negócio.</li></ul> |
| 3 | **matheuspimentaa/Sistema-SDR-Multiagentes** (https://github.com/matheuspimentaa/Sistema-SDR-Multiagentes). n8n mais Evolution API, 8 estrelas, de 08/2025. Junto com ele, **WalissonVinicius/chatbot-multiagente-n8n** (https://github.com/WalissonVinicius/chatbot-multiagente-n8n), 0 estrelas, de 10/2026. São o equivalente brasileiro do nosso n8n antigo | <ul><li>No primeiro, um supervisor que encaminha por intenção para especialistas (o que a nossa triagem vai fazer).</li><li>No segundo, a junção de mensagens explicada passo a passo ("a última execução vence" no Redis e reserva atômica no Postgres).</li><li>Também no segundo: resposta fora do formato vai para um humano.</li></ul> | <ul><li>Código testado.</li><li>Funil completo até o contrato assinado.</li><li>Memória com ficha, travas, avaliação e cobrança.</li><li>O primeiro tem 1 commit e não descreve pausa nem follow-up.</li></ul> |
| 4 | **iPythoning/b2b-sdr-agent-template** (https://github.com/iPythoning/b2b-sdr-agent-template). Shell e Node, 192 estrelas, de 09/2026. Funil de SDR B2B em 10 etapas | <ul><li>Nota de cliente ideal (≥ 7 avisa o dono).</li><li>Memória resumida ao chegar a 65% do limite.</li><li>Detecção de lead parado e troca de canal quando a janela do WhatsApp fecha.</li><li>Aprovação do dono antes da cotação.</li></ul> | <ul><li>Junta mensagens recebidas.</li><li>Travas contra promessa e invenção.</li><li>Contrato com assinatura e pausa por humano.</li><li>O deles é um modelo para montar, não um produto em uso.</li></ul> |
| 5 | **openai/openai-cs-agents-demo** (https://github.com/openai/openai-cs-agents-demo). Python e Next.js, cerca de 6,6 mil estrelas, de 12/2025. Triagem → especialistas de companhia aérea, com o OpenAI Agents SDK | <ul><li>Barreiras de relevância e de "jailbreak" rodando em paralelo, com o bloqueio visível na tela.</li><li>Tela que mostra o agente ativo e cada passagem.</li><li>Triagem que já existe (a nossa está só desenhada).</li></ul> | <ul><li>É uma demonstração; nós temos canal real (Helena), espera de mensagens, pausa, follow-up, contrato, cobrança e avaliação.</li></ul> |

**Referência de arquitetura (não é parecido no canal, mas é o melhor modelo de controle):**
- **emcie-co/parlant** (https://github.com/emcie-co/parlant). Python, cerca de 18,3 mil estrelas, atualizado em 24/11/2026.
- Separa "jornadas" (as etapas do funil, como um grafo) de "regras" (condição → ação) e põe no prompt só as regras que valem naquele momento.
- Registra qual regra gerou cada resposta e tem respostas pré-aprovadas.
- É o caminho natural para os aprendizados 1 e 7.

### Lista completa de repositórios

| Repositório | Estrelas | Atualizado | Linguagem | O que faz e como organiza a conversa |
|---|---|---|---|---|
| emcie-co/parlant · https://github.com/emcie-co/parlant | ~18,3 mil | 24/11/2026 | Python | Motor de atendimento; jornadas com estados, regras por contexto, ferramentas revisadas, respostas pré-aprovadas, registro de qual regra agiu |
| openai/openai-cs-agents-demo · https://github.com/openai/openai-cs-agents-demo | ~6,6 mil | 12/2025 | Python e TypeScript | Triagem e especialistas com passagem por ferramenta; barreiras de entrada |
| langchain-ai/langgraph-swarm-py · https://github.com/langchain-ai/langgraph-swarm-py | ~1,6 mil | 10/2026 | Python | Agentes que passam o controle entre si; lembra o último agente ativo |
| langchain-ai/langgraph-supervisor-py · https://github.com/langchain-ai/langgraph-supervisor-py | ~1,65 mil | 07/2026 | Python | Agente "chefe" que distribui para os especialistas |
| filip-michalsky/SalesGPT · https://github.com/filip-michalsky/SalesGPT | ~2,8 mil | 09/2024 (parado) | Python | Etapas de venda inferidas pela IA a cada turno; ferramentas de catálogo, Stripe e Calendly |
| RasaHQ/rasa · https://github.com/RasaHQ/rasa (demo: https://github.com/RasaHQ/rasa-calm-demo) | ~21,4 mil | 07/2026 | Python | CALM: fluxos com campos; a IA só emite comandos e o código decide a passagem; padrões prontos de correção e cancelamento |
| crewAI-examples / lead-score-flow · https://github.com/crewAIInc/crewAI-examples/tree/main/flows/lead-score-flow | — | arquivado | Python | Pontua leads e escreve e-mails, com revisão humana dos melhores |
| chatwoot/chatwoot · https://github.com/chatwoot/chatwoot | ~40,6 mil | 25/11/2026 | Ruby | Atendimento omnichannel; o Captain (IA) tem base, ações e passagem para humano; o Copilot faz rascunho para o atendente |
| EvolutionAPI/evolution-api · https://github.com/EvolutionAPI/evolution-api | ~10,2 mil | 23/11/2026 | TypeScript | API de WhatsApp (Baileys e Cloud API) com integrações de bot (Typebot, Chatwoot, OpenAI, n8n) |
| WhiskeySockets/Baileys · https://github.com/WhiskeySockets/Baileys | ~11,7 mil | 22/11/2026 | TypeScript | Base não oficial do WhatsApp Web (tem risco de banimento) |
| baptisteArno/typebot.io · https://github.com/baptisteArno/typebot.io | ~10,6 mil | 07/11/2026 | TypeScript | Construtor visual de fluxos (blocos fixos), com blocos de IA |
| botpress/botpress · https://github.com/botpress/botpress | ~15 mil | 24/11/2026 | TypeScript | Plataforma de agentes com base de conhecimento, integrações e passagem para humano |
| ladesai123/LangGraph-Lead-Generation · https://github.com/ladesai123/LangGraph-Lead-Generation | pequeno | — | Python | Pesquisa e qualificação de leads em LangGraph (não avaliado) |
| andrepdede/agent-handoff-demo · https://github.com/andrepdede/agent-handoff-demo | 0 | 28/10/2026 | TypeScript | Vendas → jurídico → financeiro no WhatsApp; máquina de estados; humano por confiança baixa; testes de passagem |
| luantaraschi/lull · https://github.com/luantaraschi/lull | 1 | 19/08/2026 | TypeScript | Só a camada da conversa: junta mensagens (5 s, teto de 15 s), descarta repetidas, humano assume por 15 min e o atrasado é descartado |
| GustavoBaranda/chatflow-agent · https://github.com/GustavoBaranda/chatflow-agent | 24 | 25/11/2026 | Python | Swarm para WhatsApp Cloud e Telegram; agente ativo no SQLite; desfaz o turno que falha |
| matheuspimentaa/Sistema-SDR-Multiagentes · https://github.com/matheuspimentaa/Sistema-SDR-Multiagentes | 8 | 16/08/2025 | n8n | Supervisor e especialistas (imobiliária), espera de 10 s, base no Supabase, memória no Postgres |
| WalissonVinicius/chatbot-multiagente-n8n · https://github.com/WalissonVinicius/chatbot-multiagente-n8n | 0 | 28/10/2026 | JavaScript e n8n | Triagem por setor, JSON validado (fora do formato vai para humano), junção de mensagens "a última vence", resumo para a equipe |
| paulogarbo/whatsapp-ai-agent · https://github.com/paulogarbo/whatsapp-ai-agent | 1 | 25/08/2026 | TypeScript | Espera com fila (BullMQ), envio frase a frase, resposta em áudio, pausa de 5 min quando o operador escreve |
| viiniolliveira/zappaz-mastra · https://github.com/viiniolliveira/zappaz-mastra | 0 | ~11/2026 | TypeScript | Agentes Mastra no WhatsApp; pausa de 30 min pelo operador; grava as mensagens durante a pausa |
| Hainrixz/whatsapp-closer-agentkit · https://github.com/Hainrixz/whatsapp-closer-agentkit | 43 | 25/10/2026 | Python | Roteiro de "closer" em 6 passos com agenda e CRM; passagem por raiva ou preço; modo rascunho |
| iPythoning/b2b-sdr-agent-template · https://github.com/iPythoning/b2b-sdr-agent-template | 192 | 29/09/2026 | Shell e Node | Funil de 10 etapas, nota de cliente ideal, memória em 4 camadas, follow-up nos dias 1, 3, 7 e 14 |
| Alessandro114/sara · https://github.com/Alessandro114/sara | 11 | 20/11/2026 | TypeScript | 13 verticais; cada conversa em modo IA, humano ou híbrido; autonomia OFF, OBSERVE, SEMI ou FULL; mascara dados pessoais antes da IA |
| csr1010/whatsapp-ai-agent-sdk · https://github.com/csr1010/whatsapp-ai-agent-sdk | 335 | 02/11/2026 | TypeScript | Kit para WhatsApp Cloud com memória de perfil e base de conhecimento (infraestrutura, sem funil) |
| wassengerhq/whatsapp-chatgpt-bot · https://github.com/wassengerhq/whatsapp-chatgpt-bot | 185 | 18/11/2025 | JavaScript | Bot com ferramentas; ignora conversa atribuída a humano e volta quando ela é desatribuída |
| yerdaulet-damir/langgraph-sales-agent · https://github.com/yerdaulet-damir/langgraph-sales-agent | 50 | 02/03/2026 | Python | Grafo único com persona e catálogo por escritório, configurado em YAML |
| Kandid-ai/AgentSDR · https://github.com/Kandid-ai/AgentSDR | 99 | 25/11/2026 | TypeScript | Prospecção ativa multicanal; a IA classifica as respostas; rascunhos esperam aprovação |
| kaymen99/AI-Sales-agent · https://github.com/kaymen99/AI-Sales-agent | 98 | 09/12/2024 | Python | Agente com base, recomendador, Calendly e Stripe |
| novoaelias/mundo-grafico-agente · https://github.com/novoaelias/mundo-grafico-agente | 0 | 28/10/2026 | Python | LangGraph mais Chatwoot; preços e prazos vêm do banco, não da IA |
| mtorquato1910-cell/SDR-Closer-AI-Agent- · https://github.com/mtorquato1910-cell/SDR-Closer-AI-Agent- | 1 | não verificado | n8n | SDR com nota de 0 a 100, pré-closer, closer com base e follow-up em 6 passos (só o JSON do n8n) |
| askrella/whatsapp-chatgpt · https://github.com/askrella/whatsapp-chatgpt | ~3,8 mil | 12/07/2026 | TypeScript | Ligação simples entre WhatsApp e GPT; não é mantido; sem funil |

**Observações sobre a lista:**
- Os projetos mais parecidos com o nosso têm de 0 a 200 estrelas. Os populares são infraestrutura (canal, plataforma) ou bots simples.
- Nenhum repositório encontrado junta, num sistema só, extração de fatos com prova, etapa de contrato com assinatura, follow-up e pausa por humano.

### Guias técnicos

- **Passagem entre agentes:**
  - OpenAI Agents SDK, handoffs e guardrails: https://openai.github.io/openai-agents-python/handoffs/ e https://openai.github.io/openai-agents-python/guardrails/
  - OpenAI, "A practical guide to building agents": https://openai.com/business/guides-and-resources/a-practical-guide-to-building-ai-agents/ (PDF: https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf)
  - LangChain, "Benchmarking multi-agent architectures": https://www.langchain.com/blog/benchmarking-multi-agent-architectures
  - LangGraph multiagente: https://docs.langchain.com/oss/python/multi-agent
  - Anthropic, "Building effective agents": https://www.anthropic.com/engineering/building-effective-agents
  - Anthropic, "Effective context engineering for AI agents": https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- **Saída estruturada:**
  - OpenAI: https://developers.openai.com/api/docs/guides/structured-outputs
  - Anthropic: https://platform.claude.com/docs/en/build-with-claude/structured-outputs e https://platform.claude.com/docs/en/agents-and-tools/tool-use/strict-tool-use
- **Memória:** LangChain, short-term memory: https://docs.langchain.com/oss/python/langchain/short-term-memory
- **Alucinação:** Anthropic, reduzir alucinação: https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-hallucinations
- **Avaliação:**
  - Anthropic, "Demystifying evals for AI agents": https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
  - tau2-bench: https://github.com/sierra-research/tau2-bench (artigo: https://arxiv.org/abs/2506.07982)
  - Hamel Husain, juiz de IA: https://hamel.dev/blog/posts/llm-judge/
  - Calibrar o juiz: https://docs.langchain.com/langsmith/improve-judge-evaluator-feedback
- **Latência e cache:**
  - OpenAI: https://developers.openai.com/api/docs/guides/latency-optimization e https://developers.openai.com/api/docs/guides/prompt-caching
  - Anthropic: https://platform.claude.com/docs/en/build-with-claude/prompt-caching
- **Juntar mensagens no WhatsApp:**
  - Template n8n 19116: https://n8n.io/workflows/19116-debounce-and-buffer-whatsapp-ai-replies-with-redis-and-google-gemini/
  - Nó brasileiro: https://github.com/uaiautomacao/n8n-nodes-message-debounce
- **WhatsApp oficial (janela de 24 h, preços, limites, opt-in e IA de uso geral):**
  - Preços: https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing
  - Limite de marketing por usuário: https://developers.facebook.com/documentation/business-messaging/whatsapp/templates/marketing-templates/per-user-limits/
  - Opt-in: https://developers.facebook.com/documentation/business-messaging/whatsapp/getting-opt-in
  - Política: https://whatsappbusiness.com/pt-br/policy/
  - Termos: https://www.whatsapp.com/legal/business-solution-terms
  - Proibição de IA de uso geral: https://techcrunch.com/2025/10/18/whatssapp-changes-its-terms-to-bar-general-purpose-chatbots-from-its-platform
  - Desde 01/10/2026, a mensagem "utility" dentro da janela é cobrada, e a "service" é cobrada acima de 1.000 por mês por número. Isso entra no custo do follow-up.
- **Passagem para humano:**
  - https://www.twilio.com/en-us/blog/insights/ai-to-human-handoff-context
  - https://www.nice.com/agentic-ai/ai-to-human-handoff-in-autonomous-service
- **Brasil:**
  - LGPD: https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm
  - OAB, Provimento 205/2021: https://www.oab.org.br/leisnormas/legislacao/provimentos/205-2021
  - Recomendação CFOAB 001/2024 sobre IA: https://www.oab.org.br/noticia/62711/confira-versao-final-da-recomendacao-do-cfoab-sobre-o-uso-de-ia-na-pratica-juridica
  - Plano Nacional de IA da OAB (06/2026): https://www.oab.org.br/noticia/64289/cfoab-lanca-o-plano-nacional-para-orientar-uso-da-ia-e-ampliar-oportunidades-para-a-advocacia
  - Cartilha da OAB-RJ: https://oabrj.org.br/sites/default/files/cartilha_para_o_uso_etico_da_ia_na_pratica_juridica.pdf
  - **Ressalva:** isto é análise geral, não parecer jurídico.

### Produtos comerciais: o que oferecem e nós não temos

| Produto | O que oferece que não temos | Link |
|---|---|---|
| Intercom Fin | "Procedures" passo a passo; simulações antes de publicar; avaliações que conferem se a passagem para humano aconteceu | https://intercom.com/blog/procedures-simulations-updates |
| Qualified Piper | Agenda com quem é o dono da conta e agenda de reserva | https://qualified.com/plus/articles/the-autumn-25-release-is-here |
| Salesloft/Drift | Chama o vendedor ao vivo, com o contexto do lead | https://salesloft.com/platform/drift/chat-agent |
| Conversica | De 7 a 12 toques com variação; reativação em 30, 60 e 90 dias; alerta de intenção de compra | https://conversica.com/products |
| Regie.ai | Limite de contato por perfil; ligação automática para os leads mais quentes | https://regie.ai/auto-pilot |
| Lindy | Critérios de qualificação configuráveis; alerta com contexto; SMS só para quem deu opt-in | https://lindy.ai/templates/lead-qualifier |
| 11x e Artisan | Prospecção ativa, enriquecimento de dados, testes A/B de mensagem (fora do nosso escopo, e a OAB limita) | https://www.11x.ai · https://www.artisan.co/ai-sales-agent |
| Blip | Agentes autônomos, copiloto no atendimento, bot "congelado" durante o transbordo, multicanal | https://www.mobiletime.com.br/noticias/05/09/2025/blip-studio-agentes-ia/ |
| Kommo | Agente de IA dentro do CRM que move o card; vários agentes por função; copiloto | https://www.kommo.com/br/ia/agente-de-ia/ |
| Zenvia | Agente da Meta no WhatsApp para qualificar e encaminhar | https://zenvia.com/whatsapp/meta-agents/ |
| Leadster | Roleta de distribuição entre vendedores; 24 CRMs; agenda | https://www.getapp.com/marketing-software/a/leadster/ |
| EasyJur Talk (jurídico) | Nota do lead por área, urgência e potencial; agendamento; previdenciário configurável | https://easyjur.com/easyjur-talk-crm-no-whatsapp/ |
| Chat Jurídico (jurídico) | Recepção, triagem, qualificação e follow-up com supervisão humana; integra ADVBox, Asaas e ZapSign | https://desmistificando.com.br/hub/marketing-e-atendimento/ |

**Resumo do que o mercado tem e nós não:**
- nota do lead;
- copiloto ou rascunho;
- passagem quente com resumo;
- roleta entre atendentes;
- simulador com checagem da passagem;
- painel de conversão por etapa;
- agendamento.

O agendamento ficou de fora de propósito: o atendimento é só por mensagem.
