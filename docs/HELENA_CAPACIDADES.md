# O que a Helena deixa o nosso agente fazer

25/11/2026. Leitura função por função da documentação pública (https://helena.readme.io, índice em https://helena.readme.io/llms.txt), comparada com o código atual (`app/canal/helena_conta.py`, `app/canal/helena.py`, `app/canal/webhook.py`, `app/acoes.py`, `app/automacoes.py`, `app/followup/servico.py`).
Nada foi chamado na API real: tudo vem da documentação e do código. O resumo técnico do que já usamos continua em `docs/HELENA_API.md`.

## Em cinco linhas

1. Hoje usamos uns 20% da API: receber mensagens, responder, etiquetar, criar e mover card, nota interna, transferir para equipe, aviso à equipe e modelo aprovado no follow-up.
2. O ganho mais barato é **ler o que a Helena já sabe** antes de responder (atendente humano na conversa, janela de 24 h, etiquetas, campos do contato, notas da equipe) e **assinar mais 3 eventos** (atendimento atualizado, atendimento encerrado, status de entrega).
3. As ações novas de maior valor são: **encerrar atendimento**, **transferir para um atendente específico**, **gravar campos personalizados** (benefício, DER, nº do processo), **card completo** (responsável, valor, ganho/perdido com motivo) e **"digitando..."** no número oficial.
4. **Botões e listas não existem como envio livre na API.** Só vêm de três jeitos: modelo aprovado com botões, chatbot montado na Helena, ou o "Webhook no Chatbot" (perguntas dinâmicas). Detalhes na seção 2.
5. Tudo entra no editor como "@": a IA continua sem chamar a API; ela só marca a intenção, e o código executa a ação liberada pelo escritório (seção 3).

---

## 1. Tabela por área

Legenda da coluna "Usamos": **sim**, **em parte** ou **não**. O caminho é relativo a `https://api.helena.run/`.

### Mensagens e envios

| Função | O que faz | Usamos | O que o agente pode fazer |
|---|---|---|---|
| `POST chat/v1/session/{id}/message` | Envia texto, arquivo (`fileUrl` ou `fileId`), modelo (`templateId` + `parameters`) ou resposta citando (`refId`) dentro do atendimento. Assíncrono (entra em fila). | **sim** (`helena.py:286` `ClienteHelena.enviar`; `helena_conta.py:182` e `:197`) | Já é a fala da IA. Novo: responder **citando** a mensagem do lead (`refId`) quando ele manda várias perguntas; mandar arquivo já guardado na Helena (`fileId`). |
| `POST chat/v1/session/{id}/message/sync` | O mesmo envio, mas espera até 25 s pelo resultado. | não | Envios críticos (link do contrato): saber na hora se falhou e cair para modelo ou avisar a equipe. Não serve para a resposta normal (pode travar 25 s). |
| `POST chat/v1/send/text` | Texto para um telefone ou um atendimento, com `delayTyping` (até 25 s de "digitando..." antes de entregar), `refId`, `senderId` (id nosso), `callbackUrl`, e opções de equipe/atendente/bot. | não | "Digitando..." natural nos números **não oficiais**; `senderId` para ligar o eco à resposta da IA. Alternativa ao envio atual. |
| `POST chat/v1/send/audio`, `/video`, `/image`, `/document` | Mídia por URL pública ou id de arquivo, com legenda (vídeo, imagem, documento). | não (mandamos mídia por `fileUrl` no envio de sessão) | Mandar PDF, vídeo ou áudio **com legenda** numa bolha só ("Segue a lista de documentos"). |
| `POST chat/v1/send/template` | Modelo aprovado para um telefone, mesmo sem atendimento aberto; aceita `sessionMetadata`, equipe e atendente. | não (mandamos modelo pelo envio de sessão) | Retomar lead frio ou lembrar de perícia sem depender de sessão aberta. |
| `POST chat/v1/send/template/batch` | Mesmo modelo para até 100 contatos por chamada. | não | Não é do agente: campanha do painel (reativação de leads parados). |
| `POST chat/v1/send/typing` | Mostra "digitando..." num atendimento ativo. **Só funciona no WhatsApp oficial (CloudAPI) e WebChat**; nos outros aceita e não faz nada. | não | Enquanto o modelo pensa, o lead vê "digitando..." e para de mandar mensagens em sequência. |
| `GET chat/v1/send/message/{id}` | Status de um envio feito pelos `/send/*`. | não | Conferir entrega dos envios novos. |
| `POST chat/v1/message/send` e `/send-sync` | Envio rápido para um telefone, criando contato e sessão se precisar; aceita `botKey`, equipe e atendente (só em sessão nova). | **sim** (`helena_conta.py:210`, aviso à equipe com sessão oculta) | Além do aviso: abrir conversa proativa já atribuída a um atendente. |
| `GET chat/v1/message/{id}` | Mensagem completa: tipo, direção, origem, arquivo, **transcrição de áudio**, UTM, formulário do anúncio. | não (lemos só o corpo do webhook) | Reler um áudio cuja transcrição veio "processando"; abrir a mensagem citada pelo lead. |
| `GET chat/v1/message/{id}/status` | Status enxuto (QUEUED, SENT, DELIVERED, READ, FAILED...) e `failureReason`. | **sim** (`helena_conta.py:191`, usado na ação `conferir_entrega`) | Já confere entrega. "Lida e sem resposta" pode virar gatilho de follow-up. |
| `GET chat/v1/message?SessionId=` | Lista as mensagens de um atendimento (até 100 por página). | não | Reconstruir o histórico quando o lead já conversava antes de a IA ser ligada. |
| `DELETE chat/v1/message/{id}` | Apaga uma mensagem. A doc não diz se apaga para todos nem o prazo. | não | Só como trava do sistema (apagar mensagem duplicada ou errada). Nunca decidido pela IA. |
| `POST chat/v1/send/otp` e `GET .../otp/{id}` | Código de verificação por WhatsApp (modelo de Autenticação). | não | Pouco uso no atendimento de lead. Talvez para confirmar o número antes de dar andamento de processo. |

### Sessões (atendimentos)

| Função | O que faz | Usamos | O que o agente pode fazer |
|---|---|---|---|
| `GET chat/v2/session/{id}` | Atendimento com `status`, `windowStatus` (ACTIVE, EXPIRED, NOT_STARTED), `userId` (atendente), `botId`, `departmentId`, `utm`, `metadata`, `classification`, e com `includeDetails` as etiquetas do contato. | **em parte** (`helena_conta.py:141` lê só `contactId`) | Antes de responder: saber se **já tem humano** atribuído, se outro bot está rodando, em que equipe está e se a **janela de 24 h** está aberta (hoje calculamos por conta própria em `followup/servico.py:163`). |
| `GET chat/v2/session` | Lista atendimentos com filtros (status, equipe, atendente, etiqueta, contato, datas, metadata). | não | Achar atendimentos anteriores do mesmo contato ("você falou conosco em março"). No painel: fila de leads parados. |
| `PUT chat/v1/session/{id}/transfer` | Transfere para equipe (`DEPARTMENT`) **ou para um usuário** (`USER`, `newUserId`). | **em parte** (`helena_conta.py:178`, só equipe) | Mandar o lead qualificado direto para a Dra. Ana, ou de volta ao advogado que já o atendeu. |
| `PUT chat/v1/session/{id}/assignee` | Põe um atendente responsável sem trocar de equipe. | não | Rodízio de advogados; atribuir o dono do card. |
| `PUT chat/v1/session/{id}/complete` | Encerra o atendimento; com `reactivateOnNewMessage: true` reabre se o lead voltar a falar. | não | Encerrar quando o lead é desqualificado, foi engano ou pediu para parar. Hoje a sessão fica aberta na fila da equipe. |
| `PUT chat/v1/session/{id}/status` | Muda status (PENDING, IN_PROGRESS, COMPLETED, HIDDEN...). | não | "Pendente" quando a IA passa para humano sem transferir. |
| `PUT chat/v2/session/{id}/partial` | Muda vários campos de uma vez, inclusive **classificação** (WON, LOST, INFO, OTHER + `amount` + descrição) e `metadata` da sessão. | não | Marcar o atendimento como ganho ou perdido, com valor, e alimentar os relatórios de conversão da própria Helena. |
| `POST chat/v1/session/{id}/note` | Nota interna com texto e anexos (`filesUrls`, `filesIds`). | **em parte** (`helena_conta.py:175`, só texto) | Anexar à nota os documentos que o lead mandou (laudo, CNIS, RG). |
| `GET chat/v1/session/{id}/note` | Lista as notas internas. | não | Ler o que a equipe anotou ("não oferecer BPC", "já tem processo") e usar como instrução. |
| `GET chat/v1/session/{id}/message` | Mensagens do atendimento, paginado. | não | Igual a `GET chat/v1/message?SessionId=`. |
| `GET chat/v1/session/note/{id}`, `DELETE ...` | Lê ou apaga uma nota. | não | Uso interno (trocar resumo antigo pelo novo). |

### Contatos

| Função | O que faz | Usamos | O que o agente pode fazer |
|---|---|---|---|
| `GET core/v1/contact/{id}` e `GET core/v1/contact/phonenumber/{phone}` | Ficha do contato com etiquetas, carteira, **campos personalizados**, anotação, UTM e `metadata` (pedir `IncludeDetails=Tags,CustomFields,Portfolios`). | não | Não perguntar de novo o que o escritório já sabe; regra "se tem etiqueta Cliente, não faça triagem". |
| `PUT core/v2/contact/{id}` (e a versão por telefone) | Atualiza nome, e-mail, anotação, etiquetas, carteira, sequências, status (bloquear), UTM, **campos personalizados** e `metadata`. Muda só o que vai em `fields`. | não | **Gravar o que a IA coletou** (benefício, data do acidente, DER, nº do processo), corrigir o nome, guardar o id do nosso lead em `metadata`. |
| `POST core/v1/contact/{id}/tags` (e por telefone) | Adiciona, remove ou troca etiquetas (`operation`). | **sim** (`helena_conta.py:170`, por nome, nunca `ReplaceAll`) | Já faz. |
| `POST core/v1/contact/filter` | Busca com filtros somados: texto, telefone, e-mail, etiqueta, carteira, **campo personalizado**, metadata. | não | "Já sou cliente": achar o contato por CPF guardado em campo, ou quando escreve de outro número. |
| `POST core/v1/contact` | Cria contato; `options.upsert` atualiza se já existir. | não | Cadastrar um segundo número citado na conversa ("fala com minha esposa"). Raro. |
| `GET core/v1/contact` | Lista contatos, paginado. | não | Bastidor (importação, relatórios). |
| `POST core/v2/contact/batch` | Salva até 100 contatos por chamada. | não | Bastidor (importar base do escritório). |
| `GET core/v1/contact/custom-field` e `GET core/v1/custom-field?EntityType=CONTACT\|PANEL` | Lista os campos personalizados com tipo (texto, número, data, seleção...) e opções. | não | Montar o autocomplete de "@Campo" e validar o valor antes de gravar (a Helena **descarta sem avisar** valor de tipo errado). |

### CRM (painéis e cards)

| Função | O que faz | Usamos | O que o agente pode fazer |
|---|---|---|---|
| `GET crm/v2/panel` | Painéis com etapas (e etiquetas do painel, se pedir `Tags`). Paginado. | **sim** (`helena_conta.py:101`, só a 1ª página) | Autocomplete de painel e etapa. |
| `GET crm/v1/panel/{id}` | Um painel com etapas, campos por etapa, etiquetas e cards. | não | Carregar só o painel escolhido (mais leve). |
| `GET crm/v1/panel/{id}/custom-fields` | Campos personalizados do card, com tipo e opções. | não | Autocomplete de "@Campo do card". |
| `GET crm/v1/panel/{id}/lost-reason` | Motivos de perda do painel de vendas. | não | Escolher o motivo certo ao marcar perdido. |
| `GET crm/v2/panel/card` | Cards com filtros (painel obrigatório, contato, etapa, responsável, status) e detalhes (etapa, campos, responsável). | **em parte** (`helena_conta.py:145`, só o id) | Ler a etapa e os campos do card para responder "seu caso está na etapa Perícia". |
| `GET crm/v2/panel/card/{id}` | Um card com etapa, status, campos, metadata. | não | Conferir na Helena se a equipe já moveu o card antes de a IA mover. |
| `POST crm/v2/panel/card` | Cria card: etapa, título, descrição (até 8.000), contatos, sessão, **responsável**, etiquetas, **valor**, **prazo**, **campos personalizados**, metadata. | **em parte** (`helena_conta.py:153`: etapa, título, descrição cortada em 4.000, contato e sessão) | Card já completo: advogado responsável, valor estimado, prazo, benefício no campo certo. |
| `PUT crm/v3/panel/card/{id}` | Atualiza o card: etapa, responsável, etiquetas, valor, prazo, campos, metadata e **status** (OPEN, WON, LOST com `lostReasonId`, ARCHIVED). | **em parte** (`helena_conta.py:167`, só etapa) | Marcar **ganho** no contrato assinado, **perdido com motivo** na desqualificação, trocar responsável, gravar campos. |
| `POST crm/v2/panel/card/{id}/duplicate` | Copia o card para outra etapa ou painel, podendo arquivar o original. | não | Passar o caso do comercial para o painel jurídico depois de assinar. |
| `POST crm/v1/panel/card/{cardId}/note` | Nota no card (até 8.000 caracteres e até 3 anexos de 25 MB por URL). | não (fazemos nota só na sessão) | Resumo da qualificação e documentos do lead **no card**, que fica para sempre. |
| `GET crm/v1/panel/card/{cardId}/note` | Notas do card. | não | Contexto da equipe para a IA. |
| `DELETE crm/v1/panel/card/{cardId}/note/{noteId}` | Apaga nota do card. | não | Só uso interno. |

### Etiquetas

| Função | O que faz | Usamos | O que o agente pode fazer |
|---|---|---|---|
| `GET core/v1/tag` | Lista todas as etiquetas (sem paginação: vem tudo). | **sim** (`helena_conta.py:113`) | Autocomplete de "@Etiqueta". |
| `POST core/v1/tag`, `PUT core/v1/tag/{id}`, `DELETE core/v1/tag/{id}`, `GET core/v1/tag/color` | Cria, renomeia, apaga etiqueta; lista cores. | não | Onboarding: criar as etiquetas padrão do LawChat ("IA Desativada", "SDR"...) na ativação do escritório. A IA não deve criar etiquetas. |

### Equipes (departamentos) e usuários

| Função | O que faz | Usamos | O que o agente pode fazer |
|---|---|---|---|
| `GET core/v2/department` | Lista equipes com usuários (`agents`), canais e regra de distribuição. Sem paginação. | **sim** (`helena_conta.py:217`) | Autocomplete de "@Equipe". Saber quais equipes atendem qual número. |
| `GET core/v1/department/{id}`, `/{id}/channel`, criar, alterar, excluir, `PUT .../{id}/agents` | Gestão de equipes. | não | Só onboarding. Fora do agente. |
| `GET core/v1/agent` | Lista usuários com `userId`, nome, e-mail, telefone, equipes e **disponibilidade** (AVAILABLE ou UNAVAILABLE). Sem paginação. | **em parte** (`helena_conta.py:117`, só para conferir um usuário) | Autocomplete de "@Atendente". Transferir só para quem está disponível; senão, para a equipe. |
| `GET core/v1/agent/{id}`, criar, alterar, excluir, `POST .../departments`, `.../status`, `.../logout` | Gestão de usuários. | **em parte** (obter por id) | Fora do agente. |

### Modelos e respostas rápidas

| Função | O que faz | Usamos | O que o agente pode fazer |
|---|---|---|---|
| `GET chat/v1/template` | Lista modelos (aprovados ou não) e **respostas rápidas** (`Type=QUICKREPLY`), com texto, parâmetros, mídia, canal e status. Paginado. | **sim** (`helena_conta.py:203`, só aprovados e só a 1ª página) | Autocomplete de "@Modelo" com as variáveis exigidas. Reusar as respostas rápidas do escritório como textos-padrão. |
| Criar ou editar modelo | **Não existe na API.** O escritório cria e manda aprovar na Helena. | — | O painel só lista e escolhe. |

### Mensagens agendadas, sequências e chatbots

| Função | O que faz | Usamos | O que o agente pode fazer |
|---|---|---|---|
| `POST chat/v1/scheduled-message` | Agenda um **modelo aprovado** (ou modelo que liga um chatbot na resposta) para data e hora; pode devolver o lead a uma equipe. | não (temos follow-up próprio no banco) | Lembrete de perícia, consulta, "me chama na segunda": aparece na tela da Helena e sai mesmo se o nosso servidor cair. |
| `GET`, `PUT`, `POST .../{id}/cancel`, `POST .../batch-cancel` | Lista, remarca e cancela agendamentos (só enquanto SCHEDULED). | não | Remarcar quando a data muda; cancelar tudo do contato quando ele fecha, desiste ou pede para parar. |
| `GET chat/v1/sequence` | Lista as sequências (cadências) montadas na Helena. | não | Autocomplete de "@Sequência". |
| `POST` e `DELETE chat/v1/sequence/{id}/contact` | Põe ou tira um contato de uma sequência. | não | Inscrever quem "vai pensar" na cadência de nutrição; tirar quando responde ou fecha. |
| `GET chat/v2/sequence/{id}/contact`, lotes | Contatos de uma sequência; inclusão e remoção em massa. | não | Painel. Cuidado: no lote, telefone inexistente **cria contato**, até na remoção. |
| `GET chat/v1/chatbot` | Lista os chatbots (fluxos) da conta. | não | Autocomplete de "@Chatbot". |
| `POST chat/v1/send/chatbot` (ou `POST chat/v1/chatbot/send`) | Dispara um chatbot para um contato ou atendimento, levando `sessionMetadata` e `contactMetadata`. | não | Passar a vez para um fluxo pronto com **botões e listas** (agendamento, NPS, coleta de documentos). |
| `GET chat/v1/send/chatbot/{id}`, `/send/chatbot/batch` | Status do disparo; disparo em lote. | não | Saber se o fluxo começou ou foi barrado (outro bot rodando). |

### Arquivos e mídia

| Função | O que faz | Usamos | O que o agente pode fazer |
|---|---|---|---|
| `GET core/v2/file` + `PUT` na `urlUpload` + `POST core/v2/file` | Sobe um arquivo para a Helena e devolve um id reaproveitável. | não (mandamos por URL pública) | Mandar PDF gerado na hora (procuração, checklist) sem hospedar; subir uma vez os arquivos fixos do escritório e reusar pelo id. |
| Mídia recebida | Chega com `details.file.publicUrl` (cdn.helena.run, público) e, no áudio, `details.transcription`. | **sim** (`helena.py:228`, `app/midia/`) | Já lê áudio, imagem e vídeo. |

### Webhooks

| Função | O que faz | Usamos | O que o agente pode fazer |
|---|---|---|---|
| `GET core/v1/webhook/event` | Lista os 18 eventos assináveis. | não (lista fixa no código) | Painel. |
| `GET`, `POST`, `PUT`, `DELETE core/v1/webhook/subscription` | Gerencia assinaturas. | **sim** (`helena_conta.py:68-98`) | `enabled: false` pausa a IA da conta inteira sem apagar nada. |
| Webhook no Chatbot | Nó do chatbot da Helena que chama a nossa URL e aceita de volta caminho, metadata, mensagens e **perguntas dinâmicas** (botões, lista, números, até 50 opções). | não | Ver seção 2, item sobre botões. |

### Outros

| Função | O que faz | Usamos | O que o agente pode fazer |
|---|---|---|---|
| `GET chat/v1/channel` | Números conectados e tipo (oficial ou não). | **sim** (`helena_conta.py:53`) | Já decide regra de 24 h por canal. |
| `GET core/v1/company/officehours` | Horário de atendimento da conta (dias, períodos, fuso, mensagem de fora do horário). Sem feriados. | não | Usar o horário que o escritório já cadastrou na Helena (follow-up e "fora do horário") em vez de pedir de novo no painel. |
| `GET core/v1/portfolio` e `.../{id}/contact` | Carteiras (cliente de qual advogado) e seus contatos. | não | Pôr o cliente na carteira do advogado responsável. Valor baixo para lead novo. |
| `POST auth/v1/login/authenticate` | Gera link que entra logado na Helena, inclusive direto numa conversa (`/chat2/sessions/{id}/preview`). | não | Botão "abrir conversa na Helena" no painel e no aviso à equipe. |
| Link UTM `chat/v1/channel/wa/{telefone}?utm_...` | Link de WhatsApp rastreável. | **sim** na leitura (`app/origem.py`) | Gerar links de campanha para o escritório. |
| `core/v1/company` e tokens | Gestão de contas (Token de Parceiro). | **sim** (`helena_conta.py:223`) | Onboarding. |
| `GET core/v2/partner/billing-report` | Relatório de faturamento do parceiro. | não | Só gestão LawChat. |
| Pagamentos | Há eventos `PAYMENT_NEW` e `PAYMENT_UPDATE`, mas **nenhuma página de API** de cobrança. | não | Nada por enquanto. |

---

## 2. O que o nosso agente pode passar a fazer

Ordenado por valor sobre esforço. "Esforço" é a nossa estimativa: **baixo** (até 1 dia, mexe em 1 ou 2 arquivos), **médio** (2 a 4 dias, painel e motor), **alto** (muda arquitetura).

### Prioridade 1: alto valor, esforço baixo

**1. Ler o atendimento antes de responder.** `GET chat/v2/session/{id}?includeDetails=ContactDetails`
- Ganho: a IA sabe se um humano já foi atribuído (`userId`), se outro bot está rodando (`botId`), em que equipe está, e a janela de 24 h real (`windowStatus`).
- Onde: trocar `contato_da_sessao` (`helena_conta.py:141`) por um `sessao()` que devolve tudo; usar no pipeline antes do agente e no follow-up (`followup/servico.py:163`, que hoje estima a janela pela última mensagem do lead).
- Custo: 1 chamada por turno (cabe folgado no limite).

**2. Assinar mais eventos: `SESSION_UPDATE`, `SESSION_COMPLETE`, `MESSAGE_UPDATED` (e `CONTACT_UPDATE`).**
- Ganho: a IA se cala na hora em que a equipe transfere ou assume a conversa, mesmo sem escrever nada; o follow-up para quando a equipe encerra; entrega e leitura chegam sem consulta (polling).
- Onde: `EVENTOS_DO_ATENDIMENTO` (`helena_conta.py:13`); `ler_webhook` (`helena.py:184-187`, que hoje ignora tudo que não é mensagem); `ia_controle.py:84` já trata `CONTACT_UPDATE`, mas esse evento **não está assinado**, então nunca chega.
- Cuidado: `garantir_assinatura` (`helena_conta.py:86-89`) troca a lista inteira de eventos. Mudar só a constante.

**3. Encerrar atendimento.** `PUT chat/v1/session/{id}/complete` com `reactivateOnNewMessage: true`
- Ganho: lead desqualificado, engano ou "pare de me mandar mensagem" sai da fila da equipe; se voltar a falar, reabre sozinho.
- Onde: novo método `encerrar()` em `HelenaConta`; nova ação `encerrar` em `acoes.py`; novo campo `encerrar` nas regras de `automacoes.py` (`CAMPOS`, linha 39), por exemplo em `pediu_para_parar` e `etapa:desqualificado`.

**4. Transferir ou atribuir a um atendente específico.** `PUT .../transfer` com `type: USER` e `newUserId`, ou `PUT .../assignee`
- Ganho: "lead qualificado vai para a Dra. Ana"; devolver ao advogado que já atendeu o contato. Com `GET core/v1/agent` dá para mandar só para quem está `AVAILABLE` e cair para a equipe se não estiver.
- Onde: `transferir()` (`helena_conta.py:178`) aceitar `id_usuario`; regra de automação com `id_atendente` ao lado de `id_equipe`.
- A confirmar no primeiro teste: se `newUserId` é o `userId` ou o `id` do agente (a doc chama de "usuário").

**5. "Digitando..." no número oficial.** `POST chat/v1/send/typing` com `sessionId`
- Ganho: o lead vê que a resposta está vindo e manda menos mensagens picadas.
- Onde: no pipeline, logo antes de chamar o modelo, só quando o canal é oficial. Falha é ignorada (não pode atrasar a resposta).
- Nos números não oficiais o equivalente é o `delayTyping` do `POST chat/v1/send/text`, o que exigiria trocar o envio (item 14).

**6. Card do CRM completo.** `POST crm/v2/panel/card` e `PUT crm/v3/panel/card/{id}`
- Ganho: card com responsável, valor estimado, prazo, campos (benefício, DER) e descrição de até 8.000 caracteres; **ganho** quando o contrato é assinado e **perdido com motivo** quando o lead é desqualificado ou desiste.
- Onde: `criar_card` e `mover_card` (`helena_conta.py:153-168`); `_mover_card` (`acoes.py:247`); regra de automação com `status_card` (ganho ou perdido) e `motivo_perda` (lista de `GET crm/v1/panel/{id}/lost-reason`).
- Cuidado: no `PUT v3`, `upsertTagOperation` vale `ReplaceAll` por padrão. Se um dia mandarmos etiquetas do card, mandar sempre `InsertIfNotExists` ou `DeleteIfExists`.

**7. Classificar o atendimento.** `PUT chat/v2/session/{id}/partial` com `fields: ["Classification"]`
- Ganho: os relatórios da Helena passam a mostrar conversão da IA (WON, LOST, INFO) com valor.
- Onde: mesma regra do item 6 (ganho/perdido marca card e atendimento).

### Prioridade 2: alto valor, esforço médio

**8. Campos personalizados do contato (e do card).** `GET core/v1/custom-field?EntityType=CONTACT` + `PUT core/v2/contact/{id}` com `fields: ["CustomFields"]`
- Ganho: o que o extrator coleta (tipo de benefício, data do acidente, DER, nº do processo, cidade) fica na ficha do contato, visível para a equipe e reaproveitado em outros atendimentos.
- Onde: no painel, um mapa "campo do produto → campo da Helena"; nova ação `gravar_campos` em `acoes.py`, disparada quando o extrator (`app/cerebro/extrator.py`) confirma um campo.
- Cuidados: a Helena descarta sem erro valor de tipo errado (validar pelo `type` e `options`). CPF e dados de saúde são sensíveis (LGPD): só gravar o que o escritório ligou de propósito.

**9. Ler o que o escritório já sabe do contato.** `GET core/v1/contact/{id}?IncludeDetails=Tags,CustomFields`
- Ganho: não perguntar de novo; regras do tipo "se tem a etiqueta Cliente, não faça triagem".
- Onde: contexto do turno (`app/cerebro/contexto.py`), junto com o item 1. Pode ser lido uma vez por conversa e guardado.

**10. Notas da equipe como contexto.** `GET chat/v1/session/{id}/note`, `GET crm/v1/panel/card/{cardId}/note`; evento `PANEL_CARD_NOTE_NEW`
- Ganho: "não oferecer BPC", "cliente já tem processo" passam a valer para a IA.
- Onde: contexto do turno. Separar as notas que nós mesmos criamos (para a IA não ler o próprio resumo como ordem).

**11. Histórico antigo.** `GET chat/v1/message?SessionId=` e `GET chat/v2/session?ContactId=`
- Ganho: quando a IA é ligada no meio de uma conversa (ou na migração do n8n), ela lê o que já foi dito, inclusive pelo atendente.
- Onde: na criação do lead no pipeline, quando o banco não tem histórico; resultado vai para a memória (`app/memoria.py`).

**12. Nota no card e anexos.** `POST crm/v1/panel/card/{cardId}/note` (até 3 URLs) e `filesUrls` na nota da sessão
- Ganho: documentos do lead (laudo, CNIS, RG) e o resumo da qualificação ficam no card.
- Onde: `nota()` (`helena_conta.py:175`) aceitar anexos; nova ação `nota_card`.

**13. Sequências.** `GET chat/v1/sequence`, `POST` e `DELETE chat/v1/sequence/{id}/contact`
- Ganho: o escritório monta a cadência na Helena e a IA só decide quando inscrever ("vai pensar", pós-venda) e quando tirar.
- Onde: regra de automação com `sequencia_entrar` e `sequencia_sair`. Conferir conflito com o nosso follow-up (não rodar os dois no mesmo lead).

### Prioridade 3: valor médio ou esforço alto

**14. Botões e listas.** Não há endpoint para mandar botão ou lista livre. Os três caminhos:
- **Modelo aprovado com botões**: os botões são fixos e aprovados pela Meta. Serve para follow-up ("Sim, quero continuar" / "Não tenho interesse"). Esforço baixo. A resposta do lead chega como mensagem do tipo `BUTTONS` ou `LIST`: hoje `TIPOS` (`helena.py:18`) não mapeia esses tipos; o texto é aproveitado se vier preenchido, mas vale mapear.
- **Chatbot da Helena** (`POST chat/v1/send/chatbot` com `botKey`): o escritório monta um fluxo com menus; a IA passa a vez levando os dados em `sessionMetadata`. Esforço médio. Enquanto o bot roda, nem a equipe nem a IA falam.
- **Webhook no Chatbot com perguntas dinâmicas**: a IA monta na hora uma pergunta com até 50 opções (`BUTTONS`, `LIST` ou `NUMBERS`). Esforço **alto**: o agente teria de rodar dentro do chatbot da Helena, não pela assinatura de eventos como hoje.
- Recomendação: começar por modelo com botões no follow-up; deixar o resto para quando um escritório pedir.

**15. Agendar retorno dentro da Helena.** `POST chat/v1/scheduled-message` (+ cancelar e remarcar)
- Ganho: lembrete de perícia ou consulta visível na Helena, que sai mesmo se o nosso servidor cair.
- Limite: só modelo aprovado (não existe texto livre agendado). Para conversa dentro das 24 h, o nosso follow-up continua melhor.
- Onde: nova ação `agendar_lembrete` com data extraída da conversa; cancelar todos os do contato (`GET` com `To` + `batch-cancel`) no `pediu_para_parar` e no encerramento.

**16. Arquivos pela Helena.** `GET` e `POST core/v2/file`, depois `fileId` no envio
- Ganho: mandar PDF gerado (procuração, checklist) sem URL pública; arquivos da Biblioteca subidos uma vez.
- Hoje a Biblioteca já manda mídia por URL pública e funciona. Só vale quando gerarmos arquivos na hora.

**17. Horário de atendimento da Helena.** `GET core/v1/company/officehours`
- Ganho: um cadastro a menos no painel (`app/horario.py`). Não traz feriados.

**18. Achar cliente existente.** `POST core/v1/contact/filter` por campo personalizado, e-mail ou nome
- Ganho: "já sou cliente" ou contato por outro número. Depende do item 8 (CPF gravado em campo).

**19. Link direto para a conversa.** `POST auth/v1/login/authenticate`
- Ganho: no painel e no aviso à equipe, um link que abre a conversa já logado. Gerar no backend, logo antes de usar (expira).

**20. Fora do agente (painel):** campanha com `send/template/batch`, carteiras, criação de etiquetas padrão no onboarding, OTP, apagar mensagem como trava do auditor.

---

## 3. Como cada capacidade vira "@" no editor de prompt

Não existe `docs/ACOES_COM_ARROBA.md`. O menu "@" de hoje (`painel/src/components/agent/RichPromptEditor.tsx:578`) tem quatro categorias: **Departamento** (os agentes de etapa, `painel/src/data/handoffTargets.ts`), **Transferência** (frases de troca), **Ferramentas** (Buscar CEP, ZapSign) e **Biblioteca** (mídia).

**Regra do desenho (DESENHO.md 7.1): a IA não chama a API.** O "@" escrito no prompt é só um rótulo amigável. Ele significa "quando esta condição acontecer, marque a intenção X". O extrator marca a intenção, vira o gatilho `intencao:X` (`automacoes.py:114`), e a regra de automação daquele gatilho executa a ação com os parâmetros escolhidos no autocomplete (ids da Helena). Assim:
- o modelo nunca inventa id de etiqueta, etapa ou atendente;
- o escritório só consegue pedir ações que nós liberamos (o token da Helena abre a conta inteira, sem escopos);
- cada ação tem nova tentativa, registro e trava como as de hoje.

### Categorias novas propostas

| Categoria | Itens do autocomplete (de onde vêm) | Ação que gera | Exemplo no prompt |
|---|---|---|---|
| **Ações** (nova) | Lista fixa nossa: Encerrar atendimento, Marcar como pendente, Ganhou, Perdeu, Pausar IA | `encerrar`, `status`, `status_card` + classificação | "Se o lead disser que já tem advogado, @Perdeu (motivo: já tem advogado) e @Encerrar atendimento." |
| **Equipe** (hoje "Departamento" mistura agentes de etapa; separar) | `GET core/v2/department` | `transferir` (DEPARTMENT) | "Se pedir revisão de aposentadoria, transfira para @Equipe Revisões." |
| **Atendente** (nova) | `GET core/v1/agent` (nome + disponibilidade) | `transferir` (USER) ou `atribuir` | "Lead qualificado em São Paulo: @Atendente Dra. Ana." |
| **Etiqueta** (nova no editor; já existe nas automações) | `GET core/v1/tag` | `etiquetar` | "Se mandar o laudo, @Etiqueta Documentos recebidos." |
| **Etapa do CRM** (nova no editor) | `GET crm/v2/panel?IncludeDetails=Steps` (painel do escritório) | `mover_card` | "Quando aceitar a proposta, @Etapa Negociação." |
| **Campo** (nova) | `GET core/v1/custom-field?EntityType=CONTACT` e `crm/v1/panel/{id}/custom-fields` | `gravar_campos` | "Guarde o tipo de benefício em @Campo Benefício." |
| **Motivo de perda** (dentro de "Perdeu") | `GET crm/v1/panel/{id}/lost-reason` | `status_card` LOST | ver "Ações" |
| **Modelo** (nova) | `GET chat/v1/template?ApprovedOnly=true` (todas as páginas, filtrado pelo canal) | envio de modelo / `agendar_lembrete` | "Depois de 24 h sem resposta, use @Modelo retomada_contato." |
| **Lembrete** (nova, junto de Modelo) | Modelos aprovados + data extraída da conversa | `agendar_lembrete` / cancelar | "Se informar a data da perícia, @Lembrete um dia antes com @Modelo lembrete_pericia." |
| **Sequência** (nova) | `GET chat/v1/sequence` | `sequencia_entrar` / `sequencia_sair` | "Se disser que vai pensar, @Sequência Nutrição 7 dias." |
| **Chatbot** (nova) | `GET chat/v1/chatbot` (só `Automation`, publicado, uso `Api`) | `disparar_chatbot` | "No fim, dispare @Chatbot Pesquisa de satisfação." |
| **Nota** (nova no editor; já existe nas automações) | Texto livre + opção "anexar documentos recebidos" | `nota` / `nota_card` | "Ao transferir, deixe @Nota com o resumo do caso." |
| **Biblioteca** (já existe) | Mídia do escritório | envio de mídia | já funciona |

### O que NÃO vira "@"

Vira **dado de contexto** que a IA lê, não ação: janela de 24 h, atendente atual, equipe atual, etiquetas e campos do contato, notas da equipe, etapa do card, origem/campanha (UTM), histórico antigo, horário de atendimento. No editor podem aparecer como variáveis (`{{contato.campo.Benefício}}`, `{{atendimento.atendente}}`), nunca como ação.

Fica fora do prompt (só sistema ou painel): status de entrega, envio síncrono, apagar mensagem, OTP, envios em lote, gestão de usuários, equipes, etiquetas e tokens.

### Para implementar o "@" de ação

1. `painel/src/data/handoffTargets.ts`: hoje só agentes e duas ferramentas. Acrescentar as categorias acima, com o id da Helena guardado junto do rótulo (o rótulo pode mudar na Helena; o id não).
2. `app/automacoes.py`: `CAMPOS` (linha 39) e `validar()` ganham `encerrar`, `id_atendente`, `status_card`, `motivo_perda`, `campos_contato`, `sequencia_entrar`, `sequencia_sair`, `id_chatbot`, `id_modelo_lembrete`.
3. `app/acoes.py`: um método `_<tipo>` por ação nova, igual aos existentes (`_etiquetar`, `_transferir`).
4. `app/canal/helena_conta.py`: um método por endpoint novo.
5. Listas do autocomplete: `modelos_aprovados` e `paineis` precisam seguir `hasMorePages` (hoje leem só a 1ª página de 100). Etiquetas, equipes e atendentes vêm inteiros (a Helena não pagina essas listas).

---

## 4. Webhooks, limites e cuidados

### Eventos que existem (18)

| Grupo | Eventos | Assinamos | Devemos assinar? |
|---|---|---|---|
| Mensagem | `MESSAGE_RECEIVED`, `MESSAGE_SENT`, `MESSAGE_UPDATED` | os dois primeiros | **Sim, `MESSAGE_UPDATED`**: entrega, leitura e falha (com `failureReason`) sem consultar. Pode substituir a ação `conferir_entrega`. |
| Sessão | `SESSION_NEW`, `SESSION_UPDATE`, `SESSION_COMPLETE` | nenhum | **Sim, `SESSION_UPDATE` e `SESSION_COMPLETE`**: humano assumiu ou transferiu (IA se cala); atendimento encerrado (para follow-up). `SESSION_NEW` não precisa (a mensagem já chega). |
| Contato | `CONTACT_NEW`, `CONTACT_UPDATE`, `CONTACT_TAG_UPDATE` | `CONTACT_TAG_UPDATE` | **Sim, `CONTACT_UPDATE`**: o código já espera por ele (`ia_controle.py:84`) e para pegar campo personalizado alterado pela equipe. |
| CRM | `PANEL_CARD_NEW`, `PANEL_CARD_UPDATE`, `PANEL_CARD_STEP_CHANGE`, `PANEL_CARD_NOTE_NEW`, `PANEL_CARD_NOTE_UPDATE` | nenhum | **Depois**: `PANEL_CARD_STEP_CHANGE` (equipe moveu o card: manter `agentesia_crm_cards` em dia e, se o escritório quiser, disparar mensagem) e `PANEL_CARD_NOTE_NEW` (nota vira contexto). |
| Modelo | `TEMPLATE_NEW`, `TEMPLATE_UPDATE` | nenhum | Opcional: atualizar a lista de "@Modelo" quando um modelo é aprovado. |
| Pagamento | `PAYMENT_NEW`, `PAYMENT_UPDATE` | nenhum | Não. |

Cada evento assinado é um POST a mais no nosso servidor por acontecimento na conta inteira (a assinatura não filtra por canal nem por equipe). `PANEL_CARD_*` pode ser volumoso: medir antes.

Formato: `POST {eventType, date, content}`, saindo do IP fixo `18.215.79.89`. A doc não traz assinatura (HMAC), nova tentativa nem timeout. Por isso o segredo na URL (`app/canal/webhook.py`) continua necessário; dá para somar um filtro por esse IP.

Fora da assinatura há o `callbackUrl` de cada envio `/send/*` e de chatbot (avisa enviado, falhou ou bot iniciou). A doc não descreve o corpo desse aviso.

### Limites

- **Taxa por conta**: 1.000 chamadas a cada 5 minutos e 200 a cada 5 segundos, somando tudo do escritório (inclusive o n8n antigo, se ainda estiver ligado). Acima disso, HTTP 429.
- Os `/send/*` têm ainda um limite próprio por endpoint: 1.000 a cada 2 minutos.
- O nosso envio (`ClienteHelena.enviar`, `helena.py:264-321`) já espera entre tentativas e respeita o `Retry-After` (até 10 s). O `HelenaConta._pedir` (`helena_conta.py:41`) não repete: devolve `limite_de_uso` e quem chama decide (a fila de ações repete depois).
- Conta de bolso por turno, se tudo for ligado: ler sessão (1) + digitando (1) + resposta em 2 a 3 bolhas (2-3) + etiqueta/card/nota/transferência/campos (até 5) = cerca de 10 chamadas. Com 1.000 a cada 5 min, dá uns 100 turnos a cada 5 minutos por escritório. Folgado hoje, mas a leitura do contato (item 9) deve ser guardada por conversa, não repetida a cada turno.
- **Paginação**: no máximo 100 por página; seguir `hasMorePages`. Etiquetas, equipes, atendentes e canais vêm inteiros.

### Janela de 24 h e modelos (WhatsApp oficial)

- A documentação não tem uma página sobre a janela. O que ela traz: o campo `windowStatus` da sessão (ACTIVE, EXPIRED, NOT_STARTED) e a regra repetida nos envios: "no WhatsApp, uma conversa só pode ser iniciada com modelo de mensagem".
- Na prática, no número oficial (`CloudAPI_WhatsApp`): dentro de 24 h desde a última mensagem do lead, texto livre; fora disso, só modelo aprovado (`templateId` + `parameters`). Mensagens agendadas só aceitam modelo.
- Hoje o follow-up calcula a janela pela última mensagem do lead (`followup/servico.py:163`) e manda o modelo sempre com o parâmetro `nome`. Melhor: usar `windowStatus` e preencher os parâmetros que o modelo pede (`params` da listagem).
- Modelos são criados e aprovados na Helena (não há API para criar). Um modelo reprovado ou pausado some da lista de aprovados.
- Nos números não oficiais não há janela, mas também não há "digitando..." pela API própria (só `delayTyping`).

### Cuidados

- **Etiquetas**: em contato (`POST`/`PUT` com upsert) e no card (`PUT crm/v3`), o padrão é `REPLACEALL`, que apaga as outras etiquetas. Sempre mandar a operação.
- **`channelId` no envio**: mandamos `channelId` no `POST chat/v1/session/{id}/message` (`helena.py:292-293`, `helena_conta.py:186-187`), mas esse campo não está no esquema (que não aceita campos extras). Funciona hoje, segundo o n8n; vale confirmar e, se a Helena ignorar, tirar.
- **`forceStartSession`** encerra a sessão em andamento. Nunca usar num lead em atendimento.
- **Lote de sequência**: telefone inexistente cria contato, até na remoção. Usar ids.
- **Campos personalizados**: valor de tipo errado é descartado sem erro. Validar antes.
- **Token sem escopos**: o token da conta abre tudo. Ação nova só entra pela lista fechada de ações, nunca pela API livre.
- **Erros**: a especificação só documenta 200 e 500. 400, 401, 404 e 429 aparecem na prática e já são tratados em `_pedir`.

### O que a documentação não responde (testar no primeiro uso)

- Corpo de `SESSION_UPDATE`, `SESSION_COMPLETE` e `MESSAGE_UPDATED` no webhook (a doc só mostra o de `CONTACT_UPDATE`).
- Se `newUserId` na transferência é o `userId` ou o `id` do agente.
- Corpo do `callbackUrl` dos `/send/*`.
- Tamanho máximo de arquivo no upload e validade da `urlUpload`.
- Se a Helena aceita ou ignora o `channelId` no envio de sessão.
