# Fluxo do contrato: do "aceito" no Closer até o "contrato assinado"

Este documento junta três levantamentos: como o Weaver faz no n8n, o que o nosso código já faz e o que a documentação oficial da ZapSign garante. Para montá-lo, só lemos os arquivos. Nenhuma API foi chamada. **Atualização (25/11/2026):** a seção 7 lista o que já foi implementado (ZapSign usada pelo agente e resumo do contrato assinado); as lacunas resolvidas estão marcadas com ✅.

**Resposta curta à pergunta principal:** sim, conseguimos receber o aviso de "contrato assinado" da ZapSign e mandar a mensagem ao lead. A rota de entrada, a conferência e a mensagem já existem no código. Faltam três coisas para isso ser confiável na prática:

- cadastrar a URL na conta ZapSign de cada escritório;
- tratar recusa e expiração;
- ter uma consulta periódica para quando o aviso não chegar.

---

## 1. O fluxo completo, passo a passo

Quem faz cada passo:

- **IA**: a atendente virtual que conversa com o lead.
- **Sistema**: o nosso código, rodando sozinho por trás.
- **ZapSign**: a plataforma de assinatura.
- **Helena**: o WhatsApp e o CRM onde estão a conversa, o card e as etiquetas.
- **Equipe**: as pessoas do escritório.

| # | O que acontece | Quem faz |
|---|---|---|
| 1 | **Aceite no Closer.** O lead aceita a proposta e os honorários. A IA avisa que vai precisar de alguns dados para o contrato. | IA |
| 2 | **Troca de etapa.** O lead passa de "Closer" para "Contratos" (na versão clássica, "coleta de dados"). As automações movem o card na Helena e trocam as etiquetas. | Sistema e Helena |
| 3 | **Coleta dos dados.** A IA pede um dado por vez: nome completo, CPF, RG (se o modelo exigir), estado civil, profissão, CEP, número, complemento e e-mail (opcional). O telefone não é pedido: vem do próprio WhatsApp. | IA |
| 4 | **Conferências na hora.** A cada mensagem o sistema guarda o que o lead disse e confere o CPF. Se o CPF estiver errado, a IA pede de novo. Quando chega o CEP, o sistema busca rua, bairro, cidade e UF, e a IA confirma o endereço com o lead. | Sistema e IA |
| 5 | **Resumo e confirmação.** Com tudo preenchido, a IA mostra os dados numa mensagem e pergunta "Está tudo certo? Posso gerar o contrato?". | IA |
| 6 | **O lead diz "sim".** O sistema confere tudo de novo e só então coloca o pedido "gerar contrato" na fila. **A IA não gera o contrato e não manda o link.** Quem faz isso é o sistema. | Sistema |
| 7 | **Reserva.** O sistema escolhe o modelo de contrato do agente (ou o padrão do escritório) e confere os dados pela terceira vez. Depois trava o lead, para que não saiam dois contratos ao mesmo tempo. | Sistema |
| 8 | **Geração na ZapSign.** O sistema pede à ZapSign um documento a partir do modelo, com os dados do lead, e o lead entra como signatário. A ZapSign devolve o documento e o link de assinatura. | Sistema e ZapSign |
| 9 | **Envio do link.** O sistema grava o contrato e manda o link direto ao lead pelo WhatsApp (Helena). Em seguida deixa uma nota no atendimento ("Contrato gerado, versão 1"), move o lead para "Assinatura", move o card, troca as etiquetas e agenda lembretes para 2 h, 24 h e 72 h depois. | Sistema e Helena |
| 10 | **O lead assina** no celular, pela página da ZapSign. Se o modelo tiver o advogado como signatário, ele também assina. | Lead e ZapSign |
| 11 | **Aviso da ZapSign (webhook).** A cada assinatura, a ZapSign avisa o nosso servidor. O servidor confere a senha do aviso, registra o aviso sem duplicar, acha o contrato certo e põe uma "verificação de assinatura" na fila. Depois responde "ok" à ZapSign na hora. | ZapSign e Sistema |
| 12 | **Conferência de verdade.** O sistema não confia no aviso: consulta o documento direto na ZapSign, descobre qual signatário é o lead e confere se ele aparece como "assinado". | Sistema e ZapSign |
| 13 | **Marca como assinado (uma vez só).** O sistema cancela os lembretes e move o lead para "Contrato assinado". A IA para de responder esse lead. | Sistema |
| 14 | **Mensagem ao lead.** O lead recebe o vídeo de pós-assinatura, se estiver configurado, e logo depois a mensagem "Assinatura confirmada! ... Obrigado pela confiança". | Sistema e Helena |
| 15 | **Avisos à equipe.** O sistema faz quatro coisas: deixa uma nota no atendimento ("Contrato assinado pelo lead"); move o card para a coluna "Contrato assinado" e troca as etiquetas; manda o aviso de contrato assinado no WhatsApp da equipe, se estiver ligado no painel; e põe na nota o resumo do caso feito pela IA ("RESUMO DO CONTRATO ASSINADO"). | Sistema, Helena e Equipe |
| 16 | **Equipe assume.** O caso segue para o operacional do escritório. | Equipe |

**Redes de segurança, caso o aviso da ZapSign não chegue:**

- Cada lembrete (2 h, 24 h, 72 h) consulta a ZapSign antes de mandar. Se o lead já assinou, o lembrete não sai e o sistema dispara os passos 12 a 15.
- Quando o lead escreve "já assinei", o sistema faz a mesma consulta.

---

## 2. Verificações

### 2.1 Antes de gerar o contrato

| Verificação | Hoje no nosso código | Observação |
|---|---|---|
| **CPF com dígito verificador** | Sim. Recusa CPF com 11 dígitos iguais e grava no formato 000.000.000-00. A conferência acontece na conversa, na fila e de novo na hora de gerar. | Só confere se o número é matematicamente válido. **Um CPF válido de outra pessoa passa.** Não existe consulta de CPF numa base externa, nem no n8n. |
| **CPF do menor** | Sim. Precisa ser válido e diferente do CPF do titular. | |
| **CEP pela busca** | Sim. Busca em três serviços (ViaCEP, OpenCEP e BrasilAPI). Avisa quando o CEP é geral de cidade, sem rua, e quando não foi encontrado. | Não confere se o CEP bate com a cidade e a UF que o lead disse; nesse caso fica valendo o que o lead disse. |
| **Nome** | Sim. Precisa ter pelo menos 2 palavras e nenhum número. | |
| **Endereço** | Sim. A rua não pode ser só número, e número, bairro e cidade são obrigatórios. | |
| **UF** | Sim. Aceita a sigla ou o nome do estado ("Minas Gerais" vira MG). | O Weaver no n8n não aceitava o nome do estado. |
| **Telefone** | Sim. Precisa ter 10 ou 11 dígitos. Se faltar, usa o número do WhatsApp. | O DDD não é conferido. |
| **E-mail** | Sim. Quando vem, o formato é conferido. Se não for obrigatório e estiver errado, é descartado em vez de travar o lead. | |
| **Campos obrigatórios por modelo** | Sim. Cada modelo de contrato pode exigir campos a mais, como RG, e-mail ou estado civil. A mesma lista vale na conversa, na fila e na geração. | Ainda não conferimos se as variáveis do modelo existem de fato na ZapSign antes de gerar. A função que lê as variáveis já existe; falta usá-la na tela de integração. |
| **Estado civil normalizado** | ✅ **Sim** (seção 7): lista fechada, com o gênero do que o lead escreveu. | Sugestão: lista fechada (solteiro(a), casado(a), divorciado(a), viúvo(a), união estável, separado(a)). |
| **Profissão normalizada** | ✅ **Sim** (seção 7): "do lar", "dona de casa" e "bico" viram "Desempregado" no código; vazia vira "Não informado". "Do lar" virar "Desempregado" e "faço bico" contar como desempregado está só nas instruções da IA, não no código. | Sugestão: passar essa regra para o código. |
| **RG** | ✅ **Sim** (seção 7): sem espaços sobrando, maiúsculas; sem número nenhum é descartado (ou pedido de novo, se obrigatório). | O formato muda de estado para estado; no mínimo, tirar espaços e conferir se tem números. |
| **Confirmação do lead** | **Na versão clássica, sim:** o código só gera depois que o lead confirma os dados. **Na versão catálogo (Weaver), parcial:** quem decide é a IA, ao acionar a ferramenta de contrato. | Se a IA acionar com um dado errado, o lead pode ouvir "vou gerar seu contrato" e logo depois "preciso confirmar uma informação". |
| **Proteção contra repetição** | Sim. Se o lead confirmar duas vezes, sai um contrato só. Dados iguais reenviam o mesmo link. São no máximo 3 versões por lead. | |
| **Trava contra laço** | Sim. Se o sistema pediria a mesma correção de novo e o lead não trouxe dado novo, a IA pausa e passa o lead para a equipe. | |

### 2.2 Depois de gerar (na assinatura)

| Verificação | Hoje no nosso código | Observação |
|---|---|---|
| **Aviso autêntico** | Sim. Cada escritório tem a sua senha na URL do aviso (ou num cabeçalho), conferida de forma segura. | A ZapSign não assina os avisos. A defesa principal é a próxima linha. |
| **Não confiar no aviso** | Sim. A decisão vem sempre da consulta do documento na ZapSign, feita com a chave do próprio escritório. | Igual ao n8n. |
| **Aviso repetido** | Sim. O aviso é registrado uma vez só, a verificação entra na fila uma vez só e "assinado" é marcado uma vez só. Então a mensagem, a nota, o card e o resumo também acontecem uma vez só. | Há um caso raro descrito na seção 4. |
| **Documento é do lead certo** | Sim. O contrato é procurado pelo código do documento **dentro do escritório** dono da URL. Documentos que não conhecemos são ignorados, como os contratos antigos do Weaver ou os feitos à mão na mesma conta. | Ainda não conferimos se o `external_id` do aviso bate com o id do contrato. É uma conferência extra e barata. |
| **Quem assinou é o lead** | Sim. A ordem é: código do signatário guardado, depois os 8 últimos dígitos do telefone, depois o signatário único. O sistema diferencia "só o escritório assinou" (só nota) de "assinatura não reconhecida" (nota e alerta). | Risco: guardamos o **primeiro** signatário da lista. Se o advogado vier primeiro no modelo, o lead recebe o link errado (seção 5). |
| **Versão antiga assinada** | Sim. A assinatura é aceita e a nota avisa a equipe: "o lead assinou uma versão já substituída". | A versão antiga continua assinável na ZapSign. |

---

## 3. Conseguimos receber o aviso de "assinado" e disparar a mensagem?

**Sim.** Como funciona:

- **Rota.** `POST /webhook/zapsign/{id do escritório}`, com a senha do escritório na URL (`?segredo=...`) ou no cabeçalho `x-agentesia-segredo`. O painel mostra a URL pronta para colar na ZapSign.
- **Cadastro.** Na ZapSign, em Configurações > Integrações > API ZapSign > Webhooks. Hoje é **manual**, feito pelo escritório. O ideal é cadastrar a senha como **cabeçalho**, para ela não aparecer em logs.
- **Ligação com o lead.** O aviso traz o código do documento. O sistema acha o contrato, e por ele o lead, na tabela de contratos do escritório.
- **Evento.** A ZapSign manda `doc_signed` **a cada assinatura**, do lead e do advogado. Por isso o sistema sempre confere quem assinou.
- **Mensagem.** O vídeo de pós-assinatura (opcional) e o texto "Assinatura confirmada" vão pelo atendimento do lead na Helena. O texto pode ser configurado por escritório.
- **Troca de etapa.** O lead vai para "Contrato assinado" e a IA para de responder.
- **Nota e card.** Fica uma nota "Contrato assinado pelo lead" com o resumo do caso feito pela IA. O card é movido e as etiquetas são trocadas pelas automações "contrato_assinado". O aviso à equipe sai pelo WhatsApp, se estiver ligado no painel.

**Se o aviso não chegar** (URL não cadastrada, ZapSign com problema, servidor fora do ar):

- **Hoje.** A assinatura só é descoberta no próximo lembrete (2 h, 24 h ou 72 h) ou quando o lead diz "já assinei". Se os lembretes estiverem desligados e o lead não disser nada, **a assinatura nunca é descoberta**.
- **Proposta.** Uma **consulta periódica**: um processo do sistema confere na ZapSign os contratos "gerados e não assinados":
  - a cada 15 a 30 minutos nas primeiras 48 h;
  - depois a cada poucas horas, até 7 dias;
  - depois uma vez por dia, até 30 dias.

  Ela usa a mesma verificação de hoje, que já é à prova de repetição, então não há risco de mensagem dupla. A ZapSign aceita até 500 consultas por minuto, o que dá folga.
- **Também vale:**
  - mostrar no painel um alerta "este escritório não recebe avisos da ZapSign há X dias e tem contratos pendentes";
  - ter um teste de "aviso de exemplo" na tela de integração.

---

## 4. Casos de erro: o que acontece hoje e o que deveria acontecer

| Situação | Hoje no nosso código | O que deveria acontecer |
|---|---|---|
| **Dado inválido** (CPF errado, falta bairro etc.) | A IA ou o sistema pede a correção ao lead, só daquele campo. Na versão clássica sai também uma nota para a equipe. Se a mesma correção se repetir sem dado novo, o lead vai para a equipe. | Está bom. Diferente do n8n, não relemos a conversa com IA para "consertar" o dado sozinho, e preferimos assim: perguntar é mais seguro. |
| **ZapSign com problema na conta** (chave errada, sem pagamento, limite, modelo inválido) | O lead recebe "nossa equipe vai finalizar seu contrato", a equipe recebe uma nota com o motivo e sai um evento no painel. Não há nova tentativa. | Está bom. Falta um detalhe: depois que o escritório arruma a conta, o lead que confirmar de novo **não** recebe contrato (a chave já foi usada). Precisa de um botão "tentar de novo" ou que a chave considere a falha. |
| **ZapSign fora do ar** | O lead recebe "tive um imprevisto, vou tentar novamente". O sistema tenta de novo depois de 1, 5, 30 e 120 minutos. | **Lacuna:** se as quatro tentativas falharem, o lead fica sem link e sem aviso. Deveria cair no "nossa equipe vai finalizar", com nota. |
| **Lead corrige um dado depois de receber o link** | Sai uma versão nova (até 3) e o lead recebe "Contrato atualizado, segue o novo link". A versão antiga vira "substituída" no nosso banco. | **Lacunas:** (a) a versão antiga continua assinável na ZapSign e deveria ser cancelada lá; (b) se uma geração antiga estava esperando nova tentativa, ela pode voltar depois e gerar uma versão com os dados **velhos** por cima da corrigida; (c) se o lead volta ao dado anterior, nada é gerado. |
| **Link expirado** | Os nossos documentos não têm prazo, porque a criação por modelo não define prazo. Então, em geral, o link não expira. Se o escritório definir prazo na ZapSign, o aviso de expiração é **ignorado** e os lembretes continuam mandando um link morto. | Tratar o aviso `doc_expired`: cancelar os lembretes, deixar uma nota para a equipe e, se o escritório quiser, gerar de novo. |
| **Recusa** (o lead recusa, ou o escritório cancela ou exclui) | **Ignorada.** O contrato fica como "gerado" e os lembretes de 24 h e 72 h continuam mandando o link. A equipe não é avisada. | Tratar `doc_refused` e `doc_deleted`: marcar o contrato como cancelado, parar os lembretes, deixar uma nota com o motivo e pausar a IA. Uma pessoa precisa conversar com esse lead. |
| **Aviso repetido** | Ignorado com segurança: não sai mensagem dupla. | Caso raro: se o aviso vier sem a identificação de quem assinou, o aviso do advogado e o do lead podem ser confundidos. O do lead seria descartado, e só o lembrete ou o "já assinei" salvam. A consulta periódica resolve isso também. |
| **Lead diz "já assinei" sem ter assinado** | O sistema consulta a ZapSign e responde "Ainda não consta a sua assinatura. Segue o link novamente". Não muda a etapa. | Está correto. Mas a resposta da IA naquele turno sai junto com essa mensagem do sistema, o que pode gerar contradição ou link em dobro. A IA deveria só dizer "vou conferir" e deixar a resposta para o sistema. |
| **Lead assinou, mas a mensagem não chega** (atendimento fechado na Helena ou mais de 24 h sem o lead falar, no número oficial) | A mensagem falha e vira só um evento. O lead fica sem confirmação. | Reabrir o atendimento ou usar um modelo aprovado pela Meta. Se não der, avisar a equipe por nota e alerta. |
| **Etapa "Contrato assinado" não existe no agente** | O lead não muda de etapa e a IA continua respondendo um lead que já assinou. | Exigir essa etapa na ativação do contrato, ou encerrar a IA mesmo sem ela. |

---

## 5. Weaver (n8n) × nosso código

### 5.1 O que já temos igual ou melhor

| Ponto | Weaver (n8n) | Nosso código |
|---|---|---|
| Quem manda o link | A IA, copiando o texto que a ferramenta devolve. Ela pode reescrever ou esquecer o link. | **O sistema manda direto.** Melhor. |
| Quem decide gerar | A IA chama a ferramenta. | Na versão clássica, o código, depois da confirmação. No catálogo, a IA, com conferência do código. Igual ou melhor. |
| Conferência do CPF | Só na hora de gerar. | **A cada mensagem**, então o lead corrige na hora. Melhor. |
| UF por nome do estado e "não informado" | O Weaver não faz; o Geral faz. | Faz. Melhor que o Weaver. |
| E-mail inválido opcional | Trava. | Descarta. Melhor. |
| Trava contra dois contratos ao mesmo tempo | Sim. | Sim. Igual. |
| Mesmos dados devolvem o mesmo link | Sim. | Sim. Igual. |
| Limite de 3 versões | Sim. | Sim, e pode ser configurado. Igual ou melhor. |
| Erros da ZapSign classificados | Sim. | Sim, com novas tentativas automáticas quando está fora do ar. Melhor. |
| Senha no aviso | **Não confere.** Qualquer um dispara consultas. | **Confere**, por escritório. Melhor. |
| Consulta do documento antes de agir | Sim. | Sim. Igual. |
| Quem assinou (código, telefone, único) | Sim. | Sim. Igual. |
| Efeitos uma vez só | Sim, pela troca de etapa. Se alguém mover o lead à mão antes, nada acontece. | Sim, pela situação do **contrato**, que não depende da etapa. Melhor. |
| Documentos de outros sistemas na mesma conta | Pode confundir. | Ignorados. Melhor. |
| Lembretes de assinatura | Follow-ups gerais. | Lembretes específicos que consultam a ZapSign antes de mandar. Melhor. |
| Mensagem sem atendimento aberto | Não sai, e sem alerta. | Não sai, mas gera evento. Um pouco melhor; ainda é lacuna. |
| Regras de cliente escritas no fluxo (vídeo, credencial) | Escritas nos nós. | Configuração por escritório. Melhor. |
| Releitura da conversa por IA para consertar dados | Sim. | Não: pedimos ao lead. Escolha consciente. |
| `external_id` | Id do **lead**. | Id do **contrato**. Melhor: cada versão é rastreável. |

### 5.2 Lacunas

| # | Lacuna | Gravidade | O que fazer | Arquivos |
|---|---|---|---|---|
| 1 | Recusa, exclusão e expiração ignoradas. Os lembretes mandam o link de um documento morto e a equipe não sabe. | **Alta** | ✅ **Resolvido** (seção 7). Aceitar `doc_refused`, `doc_deleted` e `doc_expired` e pôr a consulta na fila. Na consulta, olhar o status do documento ("refused" ou "recusado"; deleted). Marcar o contrato como "cancelado", cancelar os lembretes, deixar uma nota, pausar a IA. O lembrete também deve olhar o status. Tirar `signer_signed`, que não existe. | app/contrato/servico.py (receber_webhook), app/contrato/assinatura.py (situacao_da_assinatura), app/acoes.py (_verificar_assinatura, _lembrar_assinatura) |
| 2 | O signatário guardado é sempre o primeiro da lista. Se o modelo tiver o advogado primeiro, o lead recebe o link do escritório e a assinatura do advogado conta como a do lead. | **Alta** (confirmar com um documento real no sandbox) | ✅ **Resolvido** (seção 7; falta confirmar a ordem no sandbox). Escolher o signatário pelo nome ou telefone que mandamos na criação, não pela posição. Usar esse mesmo signatário para o link. | app/contrato/servico.py (gravar_gerado), app/canal/zapsign.py (link do documento), app/contrato/assinatura.py |
| 3 | Uma geração antiga, esperando nova tentativa, pode passar por cima de uma correção mais nova e mandar o link com dados velhos. | **Alta** | ✅ **Resolvido** (seção 7). Ao pôr uma geração nova na fila, cancelar as gerações pendentes do mesmo lead. Ou, na hora de gerar, conferir se os dados ainda são os atuais. | app/pipeline.py (_acoes_do_contrato), app/acoes.py (_gerar_contrato) |
| 4 | A mensagem de "assinado" (e os lembretes) pode não chegar: atendimento fechado na Helena ou mais de 24 h sem o lead falar, no número oficial. | **Alta** | Reabrir o atendimento ou usar um modelo aprovado pela Meta para a confirmação. Se falhar, nota e alerta à equipe. Confirmar como o Weaver resolvia. | app/acoes.py (_enviar_mensagem, _lembrar_assinatura), app/canal/helena.py |
| 5 | URL do aviso cadastrada à mão. Na migração, a conta da ZapSign do escritório aponta para o n8n. Os contratos do código novo não chegariam ao nosso servidor, e o n8n procuraria o lead pelo id do contrato. | **Alta** (operacional) | Na ativação, cadastrar um **segundo** aviso na conta (a ZapSign permite vários) apontando para nós, com a senha em cabeçalho, mantendo o do n8n durante a transição. Mostrar no painel se o aviso está chegando. Avaliar o cadastro pela API, com o consentimento do escritório. | app/painel (rotas.py, tela de integrações), app/canal/webhook.py |
| 6 | Não há consulta periódica: sem aviso e sem lembrete, a assinatura nunca é descoberta. | **Média** | ✅ **Resolvido** (seção 7). Tarefa periódica que consulta os contratos "gerados" (15 a 30 min nas primeiras 48 h, depois mais espaçado, até 30 dias), usando a mesma verificação de hoje. | app/acoes.py (nova rotina ou agendador), app/contrato/servico.py |
| 7 | ZapSign fora do ar até acabarem as tentativas: o lead ouviu "vou tentar de novo" e não recebe nada. | **Média** | Na última falha, chamar o mesmo tratamento de "nossa equipe vai finalizar" (mensagem, nota, evento). Corrigir o texto do evento, que termina com "na Helena". | app/acoes.py (executor: fim das tentativas; DESCRICOES) |
| 8 | A versão substituída continua assinável na ZapSign. | **Média** | ✅ **Resolvido** (seção 7). Ao gerar a versão nova, cancelar a antiga na ZapSign (`POST /api/v1/refuse/`, com motivo e cabeçalho User-Agent). | app/canal/zapsign.py (novo método), app/acoes.py (_gerar_contrato) |
| 9 | Voltar a um dado anterior, ou confirmar de novo depois que o escritório arrumou a conta, não gera nada, porque a chave já foi usada. | **Média** | Incluir a versão ou o momento na chave, ou liberar a chave quando a geração terminou em falha ou foi substituída. Botão "gerar de novo" no painel. | app/pipeline.py (_acoes_do_contrato), app/contrato/servico.py |
| 10 | Estado civil, "do lar"/"bico" virando "Desempregado" e RG não são normalizados no código; está só nas instruções da IA. | **Média** | ✅ **Resolvido** (seção 7). Normalizar em `validar_dados`: lista fechada de estado civil, regra de profissão, limpeza do RG. | app/contrato/dados.py |
| 11 | Se o agente não tem a etapa "Contrato assinado", a IA continua respondendo um lead que já assinou. | **Média** | Exigir a etapa na ativação do contrato, ou encerrar a IA mesmo sem a etapa. | app/contrato/servico.py (mover_lead_para_etapa), ativação no painel |
| 12 | No catálogo, gerar depende de a IA acionar a ferramenta. "Já assinei" e "manda o link" saem junto com a resposta da IA, com risco de contradição ou link duplicado. | **Média** | No catálogo, exigir uma confirmação explícita do lead antes de gerar. Nos turnos de "assinei" ou "link", instruir a IA a só dizer "vou conferir" ou "já te mando". | app/cerebro/turno.py, app/cerebro/catalogo.py, app/pipeline.py |
| 13 | Se a criação demorar demais depois de a ZapSign já ter criado o documento, a nova tentativa cria um segundo documento (cobrado). | **Baixa** | Antes de criar de novo, procurar na ZapSign um documento com o mesmo `external_id`. | app/acoes.py (_gerar_contrato), app/canal/zapsign.py |
| 14 | O link do PDF assinado que a ZapSign devolve vale só 60 minutos. | **Baixa** | ✅ **Resolvido** (seção 7). Guardar só o código do documento e consultar de novo quando precisar do PDF, ou baixar e guardar o arquivo. | app/contrato/servico.py (marcar_assinado) |
| 15 | O aviso sem a identificação de quem assinou pode ser tomado como repetido. Não conferimos o `external_id`. | **Baixa** | 🟡 **Em parte**: o `external_id` agora é conferido (seção 7); a chave do aviso ainda não usa status/horário (a consulta periódica cobre o aviso perdido). Na chave do aviso, usar também o status ou o horário. Conferir se o `external_id` bate com o id do contrato. | app/contrato/servico.py (receber_webhook) |
| 16 | Segurança e LGPD: a senha na URL aparece em logs; o aviso guarda nome, telefone e e-mail dos signatários sem prazo, inclusive dos avisos ignorados; JSON quebrado dá erro 500. | **Baixa** | 🟡 **Em parte**: JSON inválido dá 400 e o aviso guarda só os campos usados (seção 7). Senha em cabeçalho continua dependendo do cadastro. Preferir a senha em cabeçalho; não guardar o corpo dos avisos ignorados, ou guardá-lo por prazo curto; responder 400 a JSON inválido. | app/main.py (webhook_zapsign), app/contrato/servico.py |
| 17 | Faltam verificações extras: CEP × cidade/UF, DDD, variáveis do modelo existentes na ZapSign; não há consulta de CPF em base externa. | **Baixa** | Fazer as três primeiras, que são baratas. Consulta de CPF só com um serviço contratado e a base legal na LGPD avaliada. | app/contrato/dados.py, app/ferramentas/cep.py, app/canal/zapsign.py (variaveis_do_modelo), tela de integração |
| 18 | Detalhes: documento apagado (erro 404) é tratado como "fora do ar" e tentado de novo à toa; a lista de modelos só lê a 1ª página (20); atingir o limite de versões não passa o lead para a equipe; o comentário "URL do sandbox a confirmar" já pode sair. | **Baixa** | Tratar 404 como documento inexistente; paginar os modelos; pausar a IA ao atingir o limite. | app/canal/zapsign.py, app/acoes.py |
| 19 | Faltam testes de recusa, expiração, correção depois do link (versão 2) e assinatura de versão substituída. | **Baixa** | Acrescentar esses casos. | tests/test_contrato.py |

**Para confirmar no sandbox da ZapSign antes de ligar para clientes:**

- a ordem dos signatários quando o modelo tem advogado (lacuna 2);
- os nomes exatos dos eventos e os seus corpos;
- quantas vezes a ZapSign reenvia o aviso;
- se o modelo exige código por e-mail, o que impede o lead sem e-mail de assinar;
- se a ZapSign aceita telefone vazio.

---

## 6. Diagrama do fluxo

```mermaid
flowchart TD
    A[Closer: lead aceita a proposta] --> B[Sistema muda a etapa para Contratos<br/>card e etiquetas na Helena]
    B --> C[IA pede os dados, um por vez]
    C --> D{Sistema confere<br/>CPF, CEP, campos do modelo}
    D -- dado errado --> C
    D -- tudo certo --> E[IA mostra o resumo<br/>e pergunta se pode gerar]
    E -- lead corrige --> C
    E -- lead confirma --> F[Sistema confere de novo<br/>e põe 'gerar contrato' na fila]
    F --> G{Reserva<br/>trava o lead}
    G -- mesmos dados --> G1[Reenvia o mesmo link]
    G -- já assinado --> G2[Avisa que já está assinado]
    G -- limite de versões --> G3[Mensagem e nota: equipe assume]
    G -- reservado --> H[ZapSign cria o documento pelo modelo]
    H -- problema na conta --> H1[Lead: equipe vai finalizar<br/>nota e evento]
    H -- fora do ar --> H2[Lead: imprevisto<br/>tenta de novo em 1, 5, 30, 120 min]
    H2 --> H
    H -- criado --> I[Sistema manda o link pela Helena<br/>nota, etapa Assinatura, card e etiquetas<br/>lembretes 2 h, 24 h, 72 h]
    I --> J[Lead assina na ZapSign]
    J --> K[ZapSign avisa o servidor<br/>webhook doc_signed]
    K --> L{Senha confere?<br/>aviso novo?<br/>documento nosso?}
    L -- não --> L1[Ignora e responde ok]
    L -- sim --> M[Sistema consulta o documento na ZapSign]
    I -. lembrete ou lead diz 'já assinei' .-> M
    P[Consulta periódica: 30 min por 48 h, depois diária até 30 dias] -. .-> M
    M --> N{Quem assinou?}
    N -- só o escritório --> N1[Nota: falta o lead]
    N -- não reconhecido --> N2[Nota e alerta]
    N -- pendente e o lead disse que assinou --> N3[Ainda não consta, segue o link]
    N -- recusado, excluído ou vencido --> N4[Cancela lembretes, nota, equipe assume]
    N -- lead assinou, primeira vez --> O[Marca assinado<br/>cancela lembretes<br/>etapa Contrato assinado, IA encerra]
    O --> Q[Vídeo opcional e mensagem 'Assinatura confirmada']
    O --> R[Nota, card e etiquetas, aviso à equipe<br/>resumo do caso pela IA]
    R --> S[Equipe assume o caso]
```

---

## 7. Implementado: a ZapSign usada pelo agente e o resumo do contrato assinado (25/11/2026)

Tudo com o mesmo token do escritório (cofre). Testes: `tests/test_zapsign_agente.py` (httpx.MockTransport, ModeloFalso e
banco local). Nenhuma chamada real.

| # | O que faz agora | Onde |
|---|---|---|
| 1 | **"Já assinei" esperto.** A releitura lê `status`, `deleted`, `signers[].status`, `times_viewed`, `last_view_at`, `rejected_reason` e `date_limit_to_sign`. Assinou: segue o fluxo de assinado. Nunca abriu: reenvia o link. Abriu e não concluiu: pergunta onde travou (selfie, foto do documento, código). Cancelado, excluído ou vencido: não manda link velho, diz ao lead que a equipe vai falar com ele e trata como no item 4. A leitura volta à IA como a linha "ASSINATURA DO CONTRATO (sistema)", que entra nos FATOS DO SISTEMA do turno seguinte ("assinatura do contrato (sistema)"). | `app/contrato/assinatura.py` (`ler`, `linha_para_ia`), `app/acoes.py` (`_verificar_assinatura`), `app/banco/postgres.py` (`fatos_do_sistema`) |
| 2 | **Assinante certo.** Na geração, o lead é achado pelo telefone e pelo nome mandados no create-doc (o advogado do modelo pode vir antes); na leitura, por token guardado, depois telefone, `external_id` do signatário, nome e, por último, assinante único. O link guardado é o do lead. | `assinatura.identificar_lead`, `assinante_do_lead_na_geracao`, `servico.gravar_gerado` |
| 3 | **Versão nova cancela a antiga** (`POST /api/v1/refuse/`, motivo "Substituído pela versão N", sem avisar o lead, com User-Agent), em ação própria `cancelar_contrato`, depois de gravar a nova. Antes de cancelar relê: se o lead assinou a antiga, não cancela e a verificação avisa a equipe. O `doc_refused` da nossa própria cancelação só é registrado. **Geração que volta tarde** (esperando nova tentativa) e já tem pedido mais novo para o lead termina como `obsoleta`, sem gerar. Desligável: `config.cancelar_versao_anterior=false`. | `app/acoes.py` (`_gerar_contrato`, `_cancelar_contrato`), `servico.geracao_obsoleta`, `servico.versoes_para_cancelar` |
| 4 | **Recusa, exclusão e vencimento** (webhook `doc_refused`/`doc_deleted`/`doc_expired` e qualquer releitura: "já assinei", lembrete, reenvio do link, consulta): o contrato vira `cancelado` com `causa_erro` = cancelado, excluido ou expirado, e o motivo em `erro`; lembretes cancelados; nota no atendimento; IA pausada no lead (`motivo_estado` = contrato_<causa>); evento no painel; gatilho `contrato_recusado` (aviso e automação, se configurados). Tudo uma vez só. Aviso com `external_id` diferente do contrato é ignorado (e não bloqueia o verdadeiro). O aviso guarda só os campos usados (LGPD). JSON quebrado: 400. | `servico.receber_webhook`, `servico.marcar_encerrado`, `servico.pausar_ia`, `_contrato_encerrado`, `app/main.py` |
| 5 | **Trocar telefone ou e-mail sem contrato novo.** Se o pedido de contrato difere do vigente SÓ no telefone ou no e-mail, chama `POST /api/v1/signers/{token}/` (phone_country, phone_number, email), atualiza os dados do contrato e manda "atualizei o seu contato, o link continua o mesmo". Sem versão nova e sem crédito. Desligável: `config.atualizar_contato_sem_nova_versao=false`. | `_so_mudou_o_contato` em `app/acoes.py` |
| 6 | **PDF assinado guardado.** Ação `guardar_pdf_assinado`: relê o documento (o `signed_file` vence em 60 min), baixa sem o token, confere que é PDF e grava no bucket de mídia (`app/armazenamento.py`, modo supabase ou local) em `contratos/{escritório}/{contrato}-{aleatório}.pdf`; o link permanente vai para `arquivo_assinado`. Se o documento ainda não concluiu (o advogado não assinou), tenta de novo a cada 6 h, até 8 vezes. Desligável: `config.guardar_pdf=false`. | `_guardar_pdf_assinado`, `ZapSign.baixar` |
| 7 | **Consulta periódica de segurança.** O executor, a cada 5 min, põe na fila a releitura dos contratos `gerado`: a cada 30 min nas primeiras 48 h, depois 1 vez por dia, até 30 dias (uma por janela, pela chave única). Usa a mesma verificação do aviso. | `servico.agendar_consultas`, `servico.momento_da_consulta`, `Executor.rodar` |
| 8 | **Normalização no código**: estado civil (lista fechada: Solteiro(a), Casado(a), Divorciado(a), Separado(a), Viúvo(a), União estável), RG (espaços, maiúsculas, precisa ter número) e profissão ("do lar", "dona de casa", "bico", "desempregado" viram Desempregado). | `app/contrato/dados.py` (`validar_dados`) |
| 9 | **Lembrete contextual.** Abriu o link há menos de 1 h: o lembrete é adiado 1 h (uma vez). Abriu e não concluiu: texto "travou em alguma etapa?". Cancelado, excluído ou vencido: não lembra e encerra (item 4). | `_lembrar_assinatura` |
| 10 | **Plano e créditos antes de gerar** (`GET /api/v1/info-plan/`). `number_of_credits` ≤ 0 vira "sem_credito"; `status` de pagamento pendente vira "plano_pendente": não cria documento, o lead ouve "a equipe vai finalizar", a equipe recebe nota e evento (`contrato_sem_credito` ou `contrato_plano_pendente`). Sem a informação (404, fora do ar), a geração segue. Plano ok fica 5 min em cache. | `_problema_no_plano`, `zapsign.problema_do_plano` |

**Textos novos ao lead** (editáveis em `config.mensagens`): `travou`, `cancelado`, `contato_atualizado`, `lembrete_abriu`.

### 7.1 Resumo da conversa quando o contrato é assinado

**Como o Weaver faz** (n8n "WEAVER - Contrato", nós R1 a R10; o "GERAL - Contrato" é igual): tabela
`contrato_resumo_config` editada pelo front (`ativo`, `prompt`, `modelo`; a linha do agente vale mais que a do cliente;
no GERAL, por canal) e histórico em `contrato_resumo` (resumo, prompt usado, modelo, tokens, erro). Lê as 300 últimas
mensagens, corta em 60 mil caracteres pelo fim, chama a OpenAI e põe a nota "📄 RESUMO DO CONTRATO ASSINADO" no chat da
Helena. Não ia para o card nem para o aviso da equipe. O prompt padrão tinha resumo, qualidade e potencial.

**No nosso, agora:**
- **Prompt por agente**, com um padrão de fábrica novo (`app/contrato/resumo.py`, `PROMPT_PADRAO`): cliente, benefício,
  acidente ou doença, sequela, vínculo, datas, documentos que faltam, pontos de atenção para o advogado e qualidade, sem
  inventar e sem copiar CPF, RG ou endereço. Ordem: `agentesia_agentes.config.resumo_contrato`, depois `config.resumo`
  da integração ZapSign (escritório), depois o padrão. Campos: `ativo`, `prompt`, `modelo`, `no_aviso`.
- **Uma vez só**: a ação `resumir_contrato` nasce na primeira marcação de "assinado" (chave única) e grava em
  `agentesia_contratos.resumo` só se estiver vazio (ligado ao contrato e, por ele, ao lead).
- **Para onde vai**: nota no atendimento (pela fila), descrição do card do CRM (ação nova `descrever_card`: a descrição
  de sempre mais o resumo) e, com `no_aviso` ligado, o aviso "contrato assinado" à equipe (no fim do texto, ou onde o
  modelo do aviso tiver `{{resumo}}`). Com `no_aviso`, as automações do assinado esperam o resumo e disparam no fim dele,
  com ou sem resumo.
- **Custo**: as chamadas vão para `agentesia_chamadas_ia` (papel `contrato_resumo`), o registro usado no consumo.
- **Falha da IA não segura nada**: a confirmação ao lead, a etapa, a nota de assinado e o PDF saem antes; o resumo tenta
  3 vezes e depois termina como `falhou`, com evento `resumo_contrato_falhou`, e o aviso à equipe sai sem resumo.
- **Painel (rotas prontas, tela a fazer)**: `GET /api/leads/{id}/contratos` (versões, situação, PDF guardado, resumo) e
  `GET|PUT /api/agentes/{id}/resumo-contrato` (`app/gestao/rotas_contrato.py`). Tela sugerida: na configuração do
  agente, um bloco "Resumo do contrato assinado" com o interruptor "Gerar resumo com IA", a caixa do prompt (vazia = o
  padrão, com o botão "ver o padrão"), o modelo (gpt-4.1-mini por padrão) e "mandar o resumo no aviso de contrato
  assinado". Em Conversas, no painel do lead, um cartão "Contrato" com a versão, a situação, "Baixar PDF" e o resumo.
  A tela não foi feita agora porque Conversas e as rotas de gestão estão sendo editadas em outro trabalho.

### 7.2 Suposições sobre a API da ZapSign (confirmar no sandbox)

- `number_of_credits` do `info-plan` é o saldo que resta (a documentação só mostra o exemplo "100"), e os valores de
  `status` além de `paid` (`overdue`, `pending`, `canceled`...) não estão documentados.
- O documento recusado fica com `status = "refused"` (aceitamos também `rejected` e `recusado`); vencido é `expired` ou
  `date_limit_to_sign` no passado.
- `doc_refused`, `doc_deleted` e `doc_expired` chegam no mesmo formato do `doc_signed` (`token`, `external_id`).
- O `signed_file` é uma URL assinada que baixa sem o token.
- O `external_id` do signatário só existe se a conta o preencher (o create-doc por modelo não o manda).
- A descrição do card da Helena aceita `PUT crm/v3/panel/card/{id}` com `fields: ["Description"]`.

### 7.3 Pendências em arquivos de outros trabalhos

- `app/cerebro/turno.py` e `app/pipeline.py`: no turno do "já assinei" ou do "manda o link", a IA ainda responde junto
  com a mensagem do sistema (lacuna 12). A linha (sistema) só chega no turno seguinte. Para valer no mesmo turno, o
  pipeline precisaria reler a ZapSign antes do turno (`Executor._ler_documento` e `assinatura.linha_para_ia` estão
  prontos) ou a IA ser instruída a dizer só "vou conferir".
- `app/pipeline.py`: a ação continua `gerar_contrato`; a troca só de contato é decidida no executor. Se o pipeline passar
  a mandar uma ação própria, basta chamar `_so_mudou_o_contato`.
- Painel: o aviso `contrato_recusado` e a variável `{{resumo}}` na tela de avisos à equipe; a tela do resumo (7.1); o
  cartão do contrato em Conversas; mostrar os leads `pausado` com `motivo_estado` = contrato_cancelado, contrato_excluido
  ou contrato_expirado.
- Bucket de mídia é público: o PDF assinado fica numa URL com parte aleatória, mas pública. Para LGPD, o ideal é um bucket
  privado com URL assinada na hora de baixar.
