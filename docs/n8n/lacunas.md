# Lacunas do sistema novo em relação ao n8n

Feito em 22/11/2026. Base de conhecimento do sistema atual (n8n, famílias Weaver e Geral) e o que o sistema em Python ainda não faz para substituí-lo.

- **Fonte do n8n:** pasta `Fluxos N8N` (raiz e subpastas `00` a `10`, `ENTREGA - WEAVER`, `ENTREGA - GERAL`, `Fluxo Principal (em espera)`). Os JSONs só foram abertos onde o texto não bastava: `WEAVER - Fluxo Principal.json` e `WEAVER - Agentes (subfluxo).json`, para conferir espera, divisão da resposta, vídeo inicial, saldo, ficha de memória e notificação.
- **Fonte do sistema novo:** `app/`, `db/migracoes/001_*.sql` e `002_*.sql`, e as especificações já escritas em `docs/n8n/` (`alerta_notificacao.md`, `contar_token.md`, `contrato_zapsign.md`, `arquivos_transcricao_pdf.md`).
- Nenhum segredo nem dado de lead foi copiado. Clientes aparecem como "um cliente".
- Quando este texto diz "parte do que está descrito ainda não está no ar", vale o mesmo aviso de `CONTEXTO_DO_SISTEMA.md` §10: a maior parte dos fluxos refeitos só existe em arquivo. A comparação é com o comportamento **desenhado** no n8n, que é o que o sistema novo precisa igualar.

---

## 1. Funções do sistema atual

### 1.1 Entrada da mensagem
A Helena chama o webhook (`wts-inbound-weaver` no Weaver, `/v1/zapi/recebermensagem-geral` no Geral). O fluxo principal só trata mensagem do lead. Cada mensagem é marcada pelo id no Redis por **24 horas**; repetida para no começo. O canal é achado pelo número que recebeu e o lead pelo número que enviou, dentro do canal, com ou sem o nono dígito (no Geral, pelos **8 últimos dígitos**). Número que não é canal vira aviso (Weaver) ou só histórico (Geral, nó `G5`). Contato com número oculto gera nota no chat pedindo resposta manual. Fonte: `CONTEXTO_DO_SISTEMA.md` §2; `08/FUNCOES_NOVAS.md` §1; `ESTRATEGIA_SUBFLUXOS.md` parte 2.

### 1.2 Leitura de mídia
Subfluxo `Ler mídia` (8 nós por família). Áudio transcrito; do vídeo, transcreve o áudio ("o lead enviou um vídeo, o que ele fala: …"); imagem descrita; figurinha descrita e tratada como reação; documento, localização e contato viram aviso em texto. Falha na leitura não derruba: a IA pede para o lead escrever. No Geral a chave da OpenAI é a do cliente (10 de 46 sem chave). Documento com **2.000 caracteres ou mais** é resumido (autos do PJe). Fonte: `CONTEXTO_DO_SISTEMA.md` §2 e atualização de 22/11; `docs/n8n/arquivos_transcricao_pdf.md` §1.

### 1.3 Lead novo e card do CRM
Weaver: cria contato, lead e conversa primeiro; card e tag depois, sem travar a resposta. **Um lead, um card**: só cria se não existir no Weaver nem na Helena, liga o que já existe na Helena, trava no Redis contra dois cards simultâneos, mesmo painel na busca e na criação. Se a Helena não responde a consulta, não cria e avisa. Card que não sai vira nota com o motivo (sem painel, sem etapa SDR, recusa). Nome do contato gravado sem aspas; telefone só atualizado se válido. Geral: ordem card → lead mantida, lead só criado se não existir no canal. Fonte: `08/FUNCOES_NOVAS.md` §2; `08/O_QUE_FAZER.md`.

### 1.4 Anúncio (TRACK / UTM)
No evento TRACK da Helena, o Weaver baixa a imagem do anúncio, manda UTM (`clid`, `medium`, `campaign`, `content`, `headline`, `term`) e imagem a um agente classificador ("UTM -> PRODUTO"), que devolve o benefício em JSON; hoje só a saída BPC põe tag. Vale para **um cliente só** (id fixo no nó). Há corrida com a primeira mensagem: o TRACK cria o lead com IA desligada, a mensagem cria com IA ligada. Fonte: `NARRATIVA_E_FUNCOES.md` §3.1; `08/ANALISE_E_PROBLEMAS.md` §5; nó `UTM -> PRODUTO`.

### 1.5 A IA atende? (incluindo saldo)
Weaver: só se o agente está ativo, `ia_ligada` do lead é verdadeiro e a etapa tem prompt. Nos outros casos a mensagem é gravada e a IA cala. Agente pausado **por falta de saldo** (`sistemaia_saldos.pausado_por_saldo`, nó `R0 - Saldo da conta`) gera a nota "IA pausada porque o saldo acabou" no máximo **1 vez a cada 6 horas** por conversa, mais aviso. Geral: sem controle de saldo; com o lead em `iadesativada`, a mensagem entra na memória do canal para a IA ter contexto quando voltar. Fonte: `CONTEXTO_DO_SISTEMA.md` §2.6; `08/O_QUE_FAZER.md`.

### 1.6 Espera (buffer) e conferências
Mensagens seguidas são juntadas no Redis. Weaver: **0,5 s por letra** da última mensagem, mínimo **15 s** (abaixo de 10 letras), teto **90 s**, **40 s** quando não dá para calcular (nó `TempoDeEspera`). Geral: fixo **40 s**. Três conferências: antes da espera, depois da espera (IA ligada? agente ativo?) e antes de enviar (chegou mensagem nova? atendente assumiu?). Se chegou mensagem nova, a resposta é apagada da memória e não sai; a execução nova responde tudo junto. O buffer só é apagado por quem envia. Fonte: `CONTEXTO_DO_SISTEMA.md` §2.7 e §2.9.

### 1.7 Agentes e ferramentas
Weaver: 5 agentes (SDR, Período de Graça, Closer, Contrato, Assinatura) num subfluxo; Geral: um subfluxo por canal (7 arquivos). Ferramentas de troca de etapa, `Sistema Notificação`, calculadora (período de graça), `BUSCA CONHECIMENTOS` (busca vetorial em `sistemaia_conhecimento_vetores`, **topK 100**), CEP (`BUSCAR CEP FINAL`), `zapsign`/`criardocumento` e verificação de assinatura. Uma nova tentativa se o agente falha; no máximo **8 passos de ferramenta**; temperatura com teto **1** (Geral fixa em **0,4**). O subfluxo devolve `ok`, `output`, `tools_chamadas`, `error` e nunca envia nada. Fonte: `CONTEXTO_DO_SISTEMA.md` §3; nós do subfluxo de agentes.

### 1.8 Memória
**Janela de 40 mensagens** (antes 200), calculada pelo nó `A1 - Janela segura da memória` para nunca começar no meio de uma chamada de ferramenta (erro `tool_calls must be followed by tool messages`, visto em 21/11). **Ficha de resumo** só no Weaver (`lead_memoria_resumo`): quem é, o caso, trabalho e INSS, o que já respondeu, dados informados, combinados e objeções, atendimento humano; refeita com `gpt-4.1-mini` depois do envio quando juntam **20 mensagens antigas** fora da ficha; as antigas ainda sem resumo (até 60) vão junto no prompt. **Fatos do sistema** no fim do prompt, lidos do banco a cada resposta: nome no WhatsApp, telefone, etapa, data do primeiro contato e situação do contrato (não gerado, gerado com versão e link, assinado); a IA é instruída a não contrariá-los. Fala do atendente e follow-up enviado entram na memória. Fonte: `CONTEXTO_DO_SISTEMA.md` §3; `08/O_QUE_FAZER.md` "Memória estruturada"; nó `M0 - Fatos e resumo (banco)`.

### 1.9 Conferência e envio da resposta
Erro do agente vira nota e aviso com o motivo (sem crédito, chave recusada, limite, provedor fora, conversa longa, memória cortada). Resposta vazia não sai. Nome de ferramenta escrito como texto é retirado (no Geral, para `contrato`, `qualificado` e `desqualificado`, só quando tem formato de chamada). A resposta é dividida em partes; cada parte tenta **3 vezes**; uma parte que falha não para as outras e gera nota. Imagem reconhecida por `.jpg/.jpeg/.png/.webp`; mídia só quando a parte é link puro. Lead que chegou há **mais de 3 dias** recebe menos partes (até 4, ~350 caracteres, teto 1.000). Pausas entre balões (3 s). Vídeo inicial só das **8h às 20h** de Brasília, todos os dias. Fonte: `CONTEXTO_DO_SISTEMA.md` §2.9–2.10; nós `Ta fora do Tempo?`, `Divide mensagem em menor quantidade`, `Horário Comercial1`.

### 1.10 Troca de etapa (troca de departamento)
Acionada pela tool da IA. Só avança (pode pular para frente), "já estava" não mexe em nada, destino terminal (`contratoassinado`, `iadesativada`) recusado. **Trava de troca dupla**: recusa a segunda troca sem mensagem nova do lead desde a anterior (até **10 minutos**), caso da IA chamar duas tools na mesma resposta. Aceita variações de escrita. Weaver: troca num comando só com a linha travada; move **todos os cards** do lead (até 10), cada um no seu painel; tags, nota e notificação com 3 tentativas cada; tags antigas só saem se a nova existir; cancela follow-up ao ir para `desqualificado`; histórico `lead_etapa_historico` com `trocado`, `ja_estava`, `nao_permitido` etc. Geral: **trava de 7 mensagens** (1 para desqualificado; memória vazia recusa sempre); data na coluna da etapa (`closer_at`, `contrato_at`, `desqualificado_at`); ao ir para o comercial, uma IA lê a conversa e decide **tags de qualificação**; alerta no **grupo do cliente** ("Lead qualificado" no comercial, "Proposta aceita" no contrato). Fonte: `CONTEXTO_DO_SISTEMA.md` §4; `02/MUDANCAS_TROCA_DEPARTAMENTO.md`; `04/MUDANCAS_TROCA_GERAL.md`; `02/TICKET_TK-1773.md`.

### 1.11 Rede de segurança pela frase de passagem
Só Weaver. Se a IA escreveu a frase de passagem cadastrada (`sistemaia_frases_troca`) e não acionou a tool, o principal faz a troca. Aceita a frase inteira ou **85% das palavras na ordem**. Cada caso fica como `troca_pela_frase`. A passagem contrato → assinatura não é feita pela frase. Fonte: `CONTEXTO_DO_SISTEMA.md` §4; `08/O_QUE_FAZER.md` item 3.

### 1.12 Repescagem do CRM
Só Weaver. A cada **15 minutos**, pega trocas das últimas **48 horas** cujo card não moveu, confere se o lead **ainda está** naquela etapa e tenta de novo. Até **6 tentativas** com espera crescente (15 min, 30 min, 1 h, 2 h, 4 h). Só mexe em card; ao desistir, avisa. Fonte: `02/MUDANCAS_TROCA_DEPARTAMENTO.md` §4b.

### 1.13 Follow-up do Weaver
Fila por passo (`followup_queue`), recalculada a cada resposta da IA (gatilho `Follow-UP 99`), sem duplicar (índice único por lead e passo, só mexe nos pendentes). Cadência do cadastro (`followups`, `followup_cadences`), em minutos, horas, dias ou semanas. **Segunda a sábado, 8h às 20h**, Brasília (decidido em 22/11). Despacho a cada minuto: até **5** por rodada, **um por lead**, reserva de **15 min**, atraso de mais de **24 h** vira `expired`, mínimo de **30 min** entre dois follow-ups do mesmo lead. Cancela se a etapa não tem follow-up, a IA foi desligada, ou o lead/atendente falou depois do agendamento (conferido duas vezes). Mensagem gerada com o prompt da etapa **atual**, no máximo **3 mensagens** por parágrafo, trava `processing → sending`, marca `sent` logo após enviar e grava na memória. Status: `pending`, `processing`, `sending`, `sent`, `failed`, `cancelled`, `expired`. Fonte: `01/Weaver/MUDANCAS_FOLLOWUP.md`.

### 1.14 Follow-up do Geral
Uma linha por lead em `followups`. Cadência **1h, 5h, 24h, 72h, 7, 15 e 30 dias**, sempre a seguinte à mais alta já feita; segunda a sábado, 8h–20h; só nas etapas `sdr`, `periododegraca`, `closer`, `contrato`, `etapadeassinatura`. Antes de enviar, relê lead, cliente, canal e prompt; pergunta à OpenAI se o **lead pediu para ser chamado depois** e, se pediu, guarda a data e o lead volta quando a data chega ou quando escreve. Em **canal oficial com 24 h ou mais** desde a última mensagem, usa **template da Helena** (`[etapa]_..._3dias_lawchat`) e confere a resposta; senão, o agente de follow-up do cliente, em até 3 mensagens. Registra em `followup_events`, nota no chat, grava na memória. Falha (sem template ou sem resposta do agente): alerta, nova tentativa em **1 hora**, pula a cadência na **3ª falha**. Lê as 100 mensagens mais recentes. Fonte: `CONTEXTO_DO_SISTEMA.md` §5; `01/Geral/MUDANCAS_FOLLOWUP_GERAL.md`; `01/Geral/PROBLEMAS_ENCONTRADOS.md`.

### 1.15 Mensagem do atendente e pausa da IA
Weaver, `Mensagem Enviada` (`wts-outbound-weaver`): ignora mensagem da própria IA; num comando só pausa a IA (`ia_ligada = false`), grava `reativar_em = agora + minutos_pausa` do agente (**15** se vazio), atualiza a conversa, grava a mensagem e põe a fala do atendente na memória (sem o nome do atendente). Nunca altera o telefone do lead (antes eram 5.757 trocas em 7 dias). Número oculto: acha o lead pelo contato da Helena. Transcreve áudio e imagem do atendente. Se a pausa falha, avisa. A **volta** não existe no ar: só um SQL opcional que religa a cada minuto os leads com data vencida. O tempo de 5 ou 15 minutos do painel é ignorado. Fonte: `CONTEXTO_DO_SISTEMA.md` §7; `08/FUNCOES_NOVAS.md` §9–10.

### 1.16 Botão "Desativar IA" (webhook `desativariageral`)
Acionado pelo botão do painel dentro da Helena, vale para Weaver, Geral, um banco de cliente específico e tabelas antigas. (1) Abre o registro em `ia_desativacao_log`; clique repetido em **20 s** para ali. (2) Pergunta à Helena quem é a conversa e confere a conta; nota "⏳ Desativando a IA nesta conversa...". (3) Procura o lead nesta ordem: **atendimento → contato + número da IA → telefone + número da IA → só contato → só telefone** (8 últimos dígitos e DDD); desliga em todos os lugares em que achar. Não achou: espera **20 s** e procura de novo; em Weaver e Geral cria o lead já desligado. (4) Nota final sempre: desativada, já estava, ou "a IA NÃO foi desativada" com código `DES-<número da execução>`. (5) Se desligou, tag 🤖 IA Desativada (e a de 5 ou 15 minutos); se não, execução termina em erro. (6) **1 minuto depois** confere se continua desligada; se religou, registra `religou_sozinha` e alerta no chat. Fonte: `03/MUDANCAS_DESATIVAR_IA.md` §2; `CONTEXTO_DO_SISTEMA.md` §7.

### 1.17 Gerar contrato
Tool `zapsign` (Weaver) / `criardocumento` (Geral). Valida CPF (dígito), nome e sobrenome, CEP, UF, e-mail, endereço; se algo está errado, uma IA relê a conversa, troca só o campo errado e valida de novo. Reserva num comando só ("já está sendo preparado" para a segunda chamada); reserva vence em **3 minutos**. Gera com o id do lead em `external_id`, grava o link na ficha (`contrato_documento`) e **só então** muda a etapa e faz card, tags, nota (Geral: alerta no grupo). Mesmos dados = mesmo link; dado corrigido = versão nova, **até 3** por lead (a anterior fica `substituido`, mas continua assinável na ZapSign). Respostas prontas por caso (dado inválido, provedor fora do ar, sem pagamento/limite/chave recusada → equipe finaliza, com nota e alerta). Em 22/11 a tool passou a existir também na etapa de assinatura, para o lead corrigir um dado. Fonte: `06/O_QUE_FAZER.md`; `07/O_QUE_FAZER.md`; `CONTEXTO_DO_SISTEMA.md` §6.

### 1.18 Provedor Tramitação
Só no Geral, para um cliente. Cria o cliente por CPF, documentos e envelope; se o link não vem em **30 s**, espera mais 30 e lê de novo; campo em branco no cadastro da Tramitação vira nota dizendo qual. No aviso de assinatura, o lead também é achado pelo envelope. É a parte menos testada. Fonte: `07/O_QUE_FAZER.md`; `07/PROBLEMAS_ENCONTRADOS.md` itens 11–13 e 24.

### 1.19 Contrato assinado e verificação
Duas entradas: webhook do provedor e a tool de verificação ("já assinei"). Acha o lead (Geral: ficha → `external_id` → documento no lead → envelope → telefone dentro do cliente) e **consulta o provedor para saber quem assinou**. Só quando foi o lead, e só na primeira vez: muda para contrato assinado, move o card, troca tags, encerra follow-ups, manda a confirmação, faz o resumo e avisa. Só o escritório assinou: nota, nada para o lead. A verificação não desliga mais a IA; sem contrato gravado, a IA diz que a equipe vai conferir, com nota e alerta. Geral em canal Z-API: confirmação com texto fixo, áudio e o contato do operacional. Fonte: `CONTEXTO_DO_SISTEMA.md` §6; `06/ANALISE_E_PROPOSTA.md` §6.

### 1.20 Resumo do contrato assinado
Quando o lead assina (primeira vez), o fluxo lê a conversa, pede o resumo à OpenAI e escreve a nota "📄 RESUMO DO CONTRATO ASSINADO" (Geral: no card e no chat). Configuração em `contrato_resumo_config` (`ativo`, `prompt`, `modelo`, por cliente ou por agente; a do agente vale mais). Histórico em `contrato_resumo` (texto, prompt usado, modelo, mensagens lidas, tokens, erro). Weaver: só para quem tem linha ativa; Geral: para todos. O resumo vai na notificação de contrato assinado (campo `resumo_contrato`). Fonte: `06/O_QUE_FAZER.md` "Resumo do contrato assinado".

### 1.21 Notificação à equipe (`99 - Alerta Notificação`)
Três entradas: tool da IA (10 tipos com auditor: `dificuldadenaassinatura`, `fotodocontrato`, `naosabeler`, `clienteantigo`, `outrobeneficio`, `videochamada`, `leadquerreceberaudio`, `muitasobjecoes`, `enderecosemfalar`, `contratomanual`), troca de etapa (`lead_qualificado`, `lead_iniciou_coleta`, `aguardando_assinatura`, `contrato_assinado`) e ZapSign. O auditor confere no histórico; se vale, desliga a IA do lead, grava nota, avisa os números configurados e devolve à IA a mensagem para o lead. Texto do aviso escrito pelo escritório com marcadores (`{{nome}}`, `{{telefone}}`, `{{etapa}}`, `{{link_assinatura}}`, `{{resumo}}`…). Fonte: `docs/n8n/alerta_notificacao.md` §1 e §7.

### 1.22 Histórico, nota no chat e central de avisos
Cada fluxo grava problemas numa tabela própria (`atendimento_evento`, `contrato_evento`…) com **responsável** (cliente, cadastro, provedor, lead, LawChat). Quando o cliente precisa saber, sai **nota no chat** do lead (saldo acabou, card não criado, provedor recusou, resposta não enviada); a partir da segunda vez: "Primeiro aviso deste problema: [data]. Ocorrências desde então: N". **Trava de 6 horas**: nota e aviso do mesmo problema no máximo 1 vez a cada 6 h por conversa (o histórico grava sempre). **Central de avisos** (`ALERTAS - Central de avisos`, 3 webhooks: `AlertaFalhaTrocaDepartamento`, `AlertaFalhaFollowup`, `AlertaLawchat`): padroniza e deixa o mesmo aviso (origem, cliente, lead, falha) passar **1 vez a cada 30 minutos**; o nó de envio ainda não foi ligado. Fonte: `CONTEXTO_DO_SISTEMA.md` §8; `05/O_QUE_FAZER.md`.

### 1.23 Contagem de tokens e cobrança
`99 - CONTAR TOKEN`, chamado no fim do principal: espera a execução terminar, lê o `runData` pela API do n8n, soma os tokens por modelo e grava em `consumo_tokens`; o preço e o débito do saldo são feitos por gatilho no banco (`sistemaia_*`). Execução de teste não é cobrada. Fonte: `docs/n8n/contar_token.md` §1–3.

### 1.24 Outros
- **Re-Execução**: botão no painel da Helena que reposta a última mensagem do lead no webhook. Fonte: `Fluxo Principal (em espera)/ANALISE_FLUXO_PRINCIPAL.md` §8.2.
- **Sincronizar canais** (Geral, manual). Fonte: `10/LEIA-ME.md`.
- **Bloqueio por frase** ("SAIR") e **por suspeita de robô**: estavam desligados e saíram do Geral. Fonte: `10/ANALISE_E_PROBLEMAS.md`.
- **Monitor de follow-up** (fila parada ou acumulando): nunca feito. Fonte: `LEIA-ME.md`.
- **Análise manual** (`analisemanual`) como etapa fora da sequência no Geral. Fonte: `CONTEXTO_DO_SISTEMA.md` §1.

---

## 2. Lacunas

Legenda da situação: **tem** = o sistema novo já faz; **parcial** = faz parte; **falta** = não faz; **não se aplica** = a arquitetura nova torna desnecessário ("a IA conversa, o código age": sem tools, etapa decidida em código, histórico em texto).

### 2.1 Entrada, cadastro e mídia

| Função | Como é no n8n | Situação no sistema novo | O que fazer | Prioridade |
|---|---|---|---|---|
| Descarte de mensagem repetida | Redis, 24 h por id | **tem** | `agentesia_eventos_recebidos` único por (origem, id_externo) e índice único em `agentesia_mensagens` | — |
| Canal, lead e nono dígito; isolamento por cliente | Busca por número, 8 últimos dígitos; trava de canal | **tem** | `normalizar_telefone`, `canal_por_numero`, `id_escritorio_esperado` na URL do webhook | — |
| Número que não é canal | Aviso / histórico | **tem** | Evento `canal_nao_cadastrado` | — |
| Contato com número oculto | Nota pedindo resposta manual; no Mensagem Enviada, acha o lead pelo contato da Helena | **parcial**: grava evento `contato_sem_numero` e descarta | Em `pipeline.receber`, procurar o lead por `agentesia_contatos.id_contato_helena` quando não há número; se não achar, enfileirar ação `nota` ("contato sem número, responda manualmente") com a trava de 6 h | média |
| Nome do contato do WhatsApp | Gravado (sem aspas) e usado em card, nota e fatos | **falta**: `achar_ou_criar_lead` só grava o telefone | Ler o nome do webhook (`content.contact`/`details`) e gravar em `agentesia_contatos.nome`; sem nome, "Sem nome" | média |
| Grupos, mensagem atrasada, rajada, bloqueados | Parcial (bloqueio por frase e por robô desligados) | **tem** | `app/canal/filtro.py` (atraso 30 min, rajada 20/60 s com pausa de 1 h) | — |
| Lead novo sem card duplicado; liga card existente | Trava no Redis; busca no Weaver e na Helena | **tem** | `Executor._mover_card` procura card do contato antes de criar; `agentesia_crm_cards` único por lead | — |
| Áudio, imagem, PDF/DOCX/XLSX, resumo de documento ≥ 2.000 caracteres | Subfluxo `Ler mídia` e `Arquivos Transcrição PDF` | **tem** | `app/midia/` (`CORTE_RESUMO = 2000`) | — |
| Vídeo | Transcreve o áudio do vídeo | **parcial**: só usa a transcrição da Helena; sem ela, pede para o lead contar por texto | Em `app/midia`, baixar o vídeo, extrair o áudio e transcrever com `transcrever_audio`; incluir `video` em `_precisa_ler_midia` | baixa |
| Figurinha, localização, contato | Aviso em texto | **tem** | `canal/helena.py` (figurinha como reação) | — |
| Mídia enviada pelo atendente | Áudio e imagem do atendente transcritos para a memória | **falta** | Em `pipeline.receber`, ramo `humano`, chamar `_ler_midia` como no ramo do lead | baixa |

### 2.2 Decisão de atender, espera e cérebro

| Função | Como é no n8n | Situação no sistema novo | O que fazer | Prioridade |
|---|---|---|---|---|
| Corte por saldo e limites | `pausado_por_saldo`; nota "IA pausada porque o saldo acabou" 1×/6 h e aviso | **falta**: custo existe em `agentesia_chamadas_ia.custo_usd`, mas nada barra o atendimento | Migração 003: `agentesia_saldos` (id_escritorio, saldo, limite_diario, limite_mensal, pausado_por_saldo) ou leitura da plataforma; motivo `sem_saldo` em `pipeline._por_que_nao_atende`; nota no chat com a trava de 6 h e evento responsável `cliente` | alta |
| Interruptor por escritório, agente e lead | `ia_ligada`, agente pausado | **tem** | `ia_desligada`, `situacao`, `estado` do lead, modo teste | — |
| Mensagem gravada com a IA desligada | Gravada; Geral põe na memória do canal | **tem** | Grava sempre; turno `silencio` marca o lote e ele entra no histórico | — |
| Espera pelo tamanho da mensagem | 0,5 s/letra, 15–90 s, 40 s padrão | **tem** | `pipeline._tempo_de_espera`, `config.py` | — |
| Conferência antes de enviar e descarte se chegou mensagem nova | Redis + banco, resposta apagada da memória | **tem** | `_um_turno` relê pendentes e estado; reprocessa até 2 vezes | — |
| Espera e trava por lead fora do processo | Redis, compartilhado pelos 2 workers do n8n | **parcial**: `_esperas`, `_prazos`, `_travas` e `ControleDeRajada` vivem na memória de um processo. Reinício perde turnos agendados; duas instâncias podem responder em dobro | (a) Na subida, varrer leads com mensagem de lead sem turno e agendar; (b) trava por lead no Postgres (`pg_advisory_xact_lock` sobre o id do lead) no turno; (c) até lá, rodar com 1 processo só | alta |
| Janela segura da memória (tool_calls) | Nó `A1` calcula a janela para não cortar chamada de ferramenta | **não se aplica**: não há tools; o histórico é texto de `agentesia_mensagens` | — | — |
| Limite de 8 passos de ferramenta | Nos agentes | **não se aplica**: sem tools; cada turno tem número fixo de chamadas (extrator, auditor, etapa, até 2 tentativas) | — | — |
| Teto de temperatura | Teto 1 (Geral 0,4) | **tem** | `check (temperatura between 0 and 1)`, padrão 0,4 | — |
| Nome de ferramenta escrito no texto | Filtro retira o trecho | **não se aplica / tem**: não há ferramenta para vazar; a trava `texto_interno` barra nomes internos e `{}` | — | — |
| Resposta vazia | Nota e aviso | **tem** | Trava `resposta_vazia`; reprovação dupla vira mensagem segura e pausa | — |
| Erro do agente com motivo e nova tentativa | Nota e aviso | **tem** (falta a nota no chat, ver 2.6) | `ErroModelo.motivo`, 2 tentativas, evento `ia_nao_respondeu` | — |
| Frase de passagem (rede de segurança) | 85% das palavras, `troca_pela_frase` | **não se aplica**: a etapa é decidida por `produto.decidir_etapa` a partir dos fatos; não depende de a IA chamar tool nem dizer frase | — | — |
| Trava de troca dupla | Recusa a 2ª troca sem mensagem nova (10 min) | **não se aplica**: uma decisão por turno, sob trava do lead, e só para frente | — | — |
| Regra das 7 mensagens (Geral) | Barra tool chamada cedo demais | **não se aplica**: transição exige fatos com trecho do lead; o extrator rejeita fato sem prova (`fato_sem_prova`) | — | — |
| Troca só vale na mensagem seguinte | Quem responde é o agente da etapa antiga | **não se aplica** (resolvido): o agente da etapa nova responde no mesmo turno | — | — |
| Calculadora do período de graça | Tool `Calculator` | **não se aplica**: `calcular_periodo_graca` em código | — | — |
| Busca de CEP | `BUSCAR CEP FINAL` | **tem** | `app/ferramentas/cep.py`, via `enriquecer` | — |
| Base de conhecimento | Busca vetorial, topK 100 | **parcial**: FAQ (até 40), objeções (até 30) e dados do escritório no prompt | Só se um escritório precisar de base grande: tabela `agentesia_conhecimento` com pgvector (rascunho `002_conhecimento`) e busca de 4 a 8 trechos | baixa |
| Janela de 40 mensagens | 40 últimas inteiras | **tem** | `historico(limite=40)` | — |
| Ficha de resumo da conversa | `lead_memoria_resumo`, refeita a cada 20 antigas | **parcial**: os fatos com trecho (`agentesia_lead_fatos`) guardam os dados do caso para sempre; combinados, objeções e o que o atendente disse antes das 40 últimas se perdem | Tabela `agentesia_lead_resumo` (id_lead, resumo, ate_mensagem, atualizado_em); ação de fila `resumir_conversa` quando houver 20 ou mais mensagens fora da janela; bloco "RESUMO DO COMEÇO DA CONVERSA" em `agente.montar_conteudo` | média |
| Fatos do sistema no prompt | Nome, telefone, primeiro contato, situação do contrato com link | **parcial**: só os fatos ditos pelo lead; a instrução da assinatura diz "não mande link", mas a IA não sabe se o contrato foi gerado, qual versão, nem se foi assinado | Campo `fatos_sistema` em `cerebro.Entrada`, montado em `pipeline._montar_entrada` (nome do contato, `criado_em` do lead, último `agentesia_contratos`: situação, versão, link, `lead_assinou_em`); bloco "FATOS DO SISTEMA (não contrarie)" em `agente.montar_conteudo`; intenção `pediu_link` que enfileira `enviar_mensagem` com o link vigente | alta |

### 2.3 Envio

| Função | Como é no n8n | Situação no sistema novo | O que fazer | Prioridade |
|---|---|---|---|---|
| Partes, 3 tentativas, parte que falha não para as outras | Sim | **tem** | `formatador.formatar`; `ClienteHelena.enviar` com 3 tentativas; evento `envio_falhou` | — |
| Pausa entre balões | 3 s | **tem** | `espera_s` por parte (tempo de digitação) | — |
| Imagem por extensão; mídia só como link puro | Regras de extensão | **não se aplica**: mídia sai por chave cadastrada, e a trava `link` barra links no texto | — | — |
| Vídeo inicial só das 8h às 20h | Brasília, todos os dias | **falta**: a IA escolhe a mídia sem regra de horário | `agente.config.midias[chave].horario` (padrão 8–20, fuso do escritório) e trava `midia_fora_do_horario` em `travas.conferir` | baixa |
| Menos partes para lead com mais de 3 dias | Teto 4 partes, ~350 caracteres | **falta** | Parâmetro `max_partes` em `formatador.formatar`, escolhido pela idade do lead | baixa |

### 2.4 Troca de etapa e CRM

| Função | Como é no n8n | Situação no sistema novo | O que fazer | Prioridade |
|---|---|---|---|---|
| Card, tags, nota e aviso na troca | Fluxo de troca, 3 tentativas cada | **tem** | Automações `etapa:<codigo>` → `mover_card`, `etiquetar`, `nota`, `preparar_aviso`; fila com novas tentativas 1/5/30/120 min | — |
| Histórico de trocas, inclusive recusas | `lead_etapa_historico` / `troca_departamento_historico` | **tem** | `agentesia_turnos` (`etapa_antes`, `etapa_depois`, decisões com motivo) | — |
| Mover todos os cards do lead (até 10) | Weaver | **não se aplica**: um card por lead (`agentesia_crm_cards` único) | — | — |
| Repescagem do card que não moveu | 15 min, 48 h, 6 tentativas, confere se o lead ainda está na etapa | **parcial**: o executor tenta de novo (1, 5, 30, 120 min), mas uma tentativa atrasada não confere a etapa atual e pode mover o card para trás | Em `Executor._mover_card`, comparar `dados.gatilho` (`etapa:x`) com a etapa atual do lead e terminar como `obsoleta` se mudou; ou usar `chave_unica` por lead para o card e cancelar o pendente anterior ao enfileirar outro | média |
| Tags antigas só saem se a nova existir | Weaver e Geral | **parcial**: `_etiquetar` remove e depois adiciona sem conferir | Resolver nomes em ids antes; só remover se todas as novas existirem; evento `etiqueta_inexistente` (responsável `cadastro`) | baixa |
| Tags de qualificação ao ir para o comercial | Geral: IA lê a conversa e escolhe tags (vínculo, documentos médicos…) | **falta** | Não precisa de IA: gatilho `fato:<chave>=<valor>` em `automacoes.gatilhos_do_turno` e no painel, ligado a `etiquetar` | baixa |
| Alerta no grupo do WhatsApp do cliente | "Lead qualificado", "Proposta aceita" | **parcial**: avisos só para números (`filtrar_destinatarios` aceita `phone`) | Destinatário tipo `grupo` em `agentesia_notificacoes.destinatarios` e envio pela Helena ao grupo em `Executor._notificar` | média |
| Cancelar follow-up ao desqualificar | Fluxo de troca | **não se aplica ainda**: não há follow-up (ver 2.5); entra na regra de cancelamento do follow-up | — | — |

### 2.5 Follow-up

| Função | Como é no n8n | Situação no sistema novo | O que fazer | Prioridade |
|---|---|---|---|---|
| Follow-up do lead que parou de responder | Weaver (fila por passo) e Geral (1h/5h/24h/72h/7d/15d/30d) | **falta**: só existem lembretes de assinatura (2, 24 e 72 h) | Módulo `app/followup.py` e migração 003: `agentesia_followup_cadencias` (id_agente, etapa, passos em minutos, ativo, dias seg–sáb, 8h–20h, fuso) e `agentesia_followups` (id_lead, passo, agendado_para, situação `pendente/reservado/enviando/enviado/falhou/cancelado/expirado`, motivo, id_mensagem; único por lead+passo pendente). Agendar ao fim de cada turno respondido (refaz só os pendentes). Laço a cada 1 min, como o `Executor`: até 5 por rodada, um por lead, 30 min entre envios, expira com 24 h de atraso, reserva de 15 min. Antes de enviar relê o lead: estado ativo (ou pausa vencida), etapa com cadência, nenhuma mensagem do lead ou do atendente depois do agendamento. Texto pelo agente da etapa atual com papel `followup` (saída estruturada, até 3 mensagens), passa pelas travas, grava em `agentesia_mensagens` como `ia`. Cancela em etapa terminal, lead encerrado e contrato assinado | alta |
| Template no canal oficial após 24 h | Template da Helena `[etapa]_..._3dias_lawchat`, resposta conferida | **falta** (o canal já tem `tipo = 'oficial'`) | Se a última mensagem do lead passou de 24 h em canal oficial: enviar template configurado por etapa (`agente.config.followup.templates`); conferir a entrega; sem template ou recusa: falha, nova tentativa em 1 h, pula o passo na 3ª falha, evento responsável `cadastro` | alta |
| "Lead pediu para ser chamado depois" | Geral pergunta à OpenAI e guarda a data | **falta** | Intenção `adiou` e fato `retornar_em` (data) no extrator (`produto.INTENCOES_BASE`); o follow-up agenda nessa data e cancela se o lead escrever antes | média |
| Monitor do follow-up | Não feito | **falta** | Evento quando há mais de N follow-ups vencidos há 15 min ou o laço não roda há 5 min | baixa |

### 2.6 Atendente, botão de desativar e avisos

| Função | Como é no n8n | Situação no sistema novo | O que fazer | Prioridade |
|---|---|---|---|---|
| Pausa quando o atendente fala, com volta automática | `reativar_em` gravado, ninguém lê | **tem** | `pipeline._pausar_por_humano` (cada fala reinicia; `minutos_pausa_humano`, padrão 15; `pausa_sem_volta`); a volta acontece na próxima mensagem do lead (`_religar_se_venceu`). O follow-up deve tratar pausa vencida como ativa | — |
| Fala do atendente na memória | Sim, sem o nome | **tem** | Histórico com autor `atendente` | — |
| Botão "Desativar IA" pela Helena | Webhook `desativariageral`: ordem de busca em 5 tentativas, nova busca em 20 s, cria lead desligado, nota ⏳ e nota final com código, tag 🤖 IA Desativada, clique repetido em 20 s, conferência 1 min depois | **parcial**: o painel tem pausar/devolver/encerrar pelo id do lead (`POST /api/conversas/{id}/ia`), mas não há entrada a partir da conversa na Helena, nem notas, tag ou conferência | Rota `POST /webhook/helena/{id_escritorio}/ia` com o segredo do escritório (`action` desligar/religar, `minutes`); achar o lead pela sessão → contato + canal → telefone + canal → contato → telefone; não achou: nova busca em 20 s e criar o lead pausado se o canal existir; `minutes` → `pausado_ate` (0 = sem volta); ações `nota` (⏳ e final com o id da ação como código) e `etiquetar` (🤖 IA Desativada); `chave_unica` por sessão e janela de 20 s; ação `conferir_desativacao` +1 min que grava evento `religou_sozinha`; registro em `agentesia_alteracoes` | alta |
| Notificação à equipe por sinal, com auditor | 10 tipos; desliga a IA; mensagem ao lead | **tem** | `app/cerebro/auditor.py`, sinais do extrator, pausa `sinal:*`, `preparar_aviso`/`notificar` | — |
| Aviso de troca de etapa e de contrato assinado | Webhooks da notificação | **tem** | Gatilhos `etapa:*`, `contrato_assinado` e `agentesia_notificacoes` | — |
| Aviso para a equipe pelo canal oficial | — | **parcial**: `_notificar` recusa canal oficial (precisa de modelo aprovado) | Aceitar template da Meta para aviso à equipe, ou exigir número não oficial na ativação | baixa |
| Nota no chat para o cliente, trava de 6 h e "primeiro aviso" | Saldo, card, provedor, resposta não enviada | **parcial**: os problemas ficam em `agentesia_eventos` (tela Erros), mas não viram nota na conversa da Helena | Ao gravar evento de responsável `cliente`, `cadastro` ou `provedor` com lead (lista: `sem_saldo`, `envio_falhou`, `ia_nao_respondeu`, `acao_falhou_*`, `contrato_*`), enfileirar `nota` com `chave_unica` = lead + tipo + janela de 6 h; texto com "Primeiro aviso deste problema: [data]. Ocorrências desde então: N", contado em `agentesia_eventos` | alta |
| Central de avisos para a equipe LawChat | 3 webhooks, mesmo aviso 1×/30 min | **falta** | Ação `alertar_lawchat` para eventos `erro`/`critico` com responsável `lawchat` ou `provedor`; destino configurável (número ou grupo da equipe); trava de 30 min por (tipo, escritório, lead) | média |
| Monitor por conta | Não existe no n8n | **falta** | Laço que cria evento quando um lead fica 10 min sem resposta ou chegam mensagens sem turno (desenho em `MAPA_DO_SISTEMA.md` §7) | baixa |

### 2.7 Contrato

| Função | Como é no n8n | Situação no sistema novo | O que fazer | Prioridade |
|---|---|---|---|---|
| Gerar na ZapSign: validação, reserva, versão (até 3), mesmo link, link antes da etapa, lembretes, webhook, quem assinou, mover para contrato assinado | Fluxos de contrato refeitos | **tem** | `app/contrato/*`, `app/canal/zapsign.py`, `Executor._gerar_contrato`, `_verificar_assinatura`, `_lembrar_assinatura` | — |
| Releitura da conversa por IA para corrigir campo errado | IA troca só o campo errado | **não se aplica**: os dados vêm de fatos com trecho; dado inválido gera pedido de correção ao lead (`cdados.pedir_correcao`) | — | — |
| Correção do contrato na etapa de assinatura | Tool liberada na assinatura (22/11) | **falta**: em `assinatura`, `produto.decidir_etapa` só olha `diz_que_assinou`; dado corrigido não gera versão nova | Em `AuxilioAcidente.decidir_etapa` (e no produto livre), se os fatos de contrato diferem do `dados_hash` do contrato vigente, pedir confirmação (`confirmar_correcao`) e, com `confirmou_dados`, devolver `dados_confirmados` para `_acoes_do_contrato` (o `servico.reservar` já cria a versão nova até 3) | alta |
| Resumo do contrato assinado | Nota "📄 RESUMO DO CONTRATO ASSINADO", config por cliente/agente, histórico com tokens | **falta** | Ação `resumir_contrato` enfileirada em `_verificar_assinatura` na primeira assinatura: modelo lê histórico e fatos; nota no chat; config em `agentesia_integracoes(zapsign).config.resumo` (`ativo`, `prompt`, `modelo`) com sobreposição por agente; coluna `resumo` em `agentesia_contratos`; custo em `agentesia_chamadas_ia`; marcador `{{resumo}}` no aviso `contrato_assinado` | média |
| Provedor Tramitação | Um cliente do Geral | **falta**: `agentesia_contratos.provedor` só aceita `zapsign` | `app/canal/tramitacao.py` (cliente por CPF, documentos, envelope, link com 2 leituras de 30 s); `provedor` e `agentesia_integracoes.tipo` com `tramitacao`; webhook `/webhook/tramitacao/{id_escritorio}`; busca do lead pelo envelope | média |
| Verificação sem contrato gravado | IA diz que a equipe confere; nota e alerta | **parcial**: `_verificar_assinatura` devolve `sem_contrato` sem nota | Nota no chat e evento responsável `cadastro` | baixa |
| Confirmação com texto, áudio e contato do operacional | Geral, canal Z-API | **parcial**: `midia_pos_assinatura` e texto `pos_assinatura` existem | Enviar o cartão de contato do operacional (`config.contato_operacional`) | baixa |
| Mensagens do contrato e lembretes no histórico da IA | Gravados na memória | **parcial**: `_enviar_mensagem` e `_lembrar_assinatura` não gravam em `agentesia_mensagens`; só entram se a Helena devolver o eco (classe `api`, autor `automacao`) | Gravar a mensagem com autor `automacao` e o `id_externo` logo após enviar | média |

### 2.8 Origem, custo e operação

| Função | Como é no n8n | Situação no sistema novo | O que fazer | Prioridade |
|---|---|---|---|---|
| Anúncio TRACK / UTM | Classifica UTM + imagem em produto com IA, põe tag; um cliente só | **falta**: `ler_webhook` marca `rastreio` e o pipeline ignora; `agentesia_leads.origem` nunca é preenchido | Módulo `app/origem.py`: gravar UTM e anúncio em `agentesia_leads.origem`; classificar o produto com saída estruturada e cache por anúncio (tabela `agentesia_anuncios`: id do anúncio, UTMs, produto, etiqueta); gatilho `origem:<produto>` nas automações; o TRACK nunca cria lead pausado (evita a corrida) | média |
| Contagem de tokens e custo | `99 - CONTAR TOKEN` lê a execução depois | **tem** | `agentesia_chamadas_ia` gravado na própria chamada | — |
| Reprocessar atendimento (Re-Execução) | Botão reposta a última mensagem | **falta** | Rota no painel que chama `Atendimento.processar(id_lead)` se a última mensagem for do lead | baixa |
| Sincronizar canais | Fluxo manual do Geral | **tem** | `POST /api/integracoes/helena/canais` | — |
| Análise manual | Etapa fora da sequência | **tem** | Etapa `analise_manual` com pausa e evento | — |
| Quatro lugares, tabelas antigas, fluxos "únicos" | Desativar IA trata todos | **não se aplica**: um esquema só (`agentesia_*`); clientes entram pela ativação | — | — |
| Virada dos leads em andamento | — | **falta** (a importação saiu do escopo em 22/11) | Regra de corte por canal: o canal só passa para o sistema novo com a IA do n8n desligada nele; decidir se leads em assinatura e follow-ups pendentes terminam no n8n ou ganham um script de importação mínima (contrato vigente e estado) | média |

---

## 3. Ordem sugerida

1. **Follow-up com cadência, fila e templates do canal oficial** (`app/followup.py` + migração 003). É a maior função do n8n sem equivalente; sem ela os leads que param de responder esfriam.
2. **Espera e trava por lead fora da memória do processo, com varredura na subida.** Hoje um reinício perde turnos e duas instâncias podem responder em dobro; o n8n usa Redis e 2 workers.
3. **Botão "Desativar IA" pela Helena** (busca em 5 tentativas, notas com código, tag, conferência em 1 min). É o fluxo de uso diário da equipe e o único com ticket aberto no n8n.
4. **Corte por saldo e limites, com nota no chat.** Sem isso a IA atende escritório sem crédito e ninguém fica sabendo.
5. **Nota no chat dos problemas do cliente com trava de 6 h e "primeiro aviso".** Hoje o escritório só vê o problema se abrir a tela Erros do painel.
6. **Fatos do sistema no prompt e reenvio do link do contrato.** Evita a IA contradizer o banco sobre contrato gerado, versão e assinatura.
7. **Correção do contrato na etapa de assinatura.** O lead que aponta um dado errado depois do link não ganha versão nova; no n8n isso foi liberado em 22/11.
8. **Resumo do contrato assinado.** Os escritórios já recebem no n8n, e o resumo também alimenta o aviso de contrato assinado.

Logo depois: anúncio TRACK/UTM para todos os clientes, provedor Tramitação (antes de migrar o cliente que usa), central de avisos da equipe LawChat e gravação das mensagens do contrato no histórico.
