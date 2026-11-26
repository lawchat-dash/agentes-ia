# API da Helena: o que o sistema usa

22/11/2026. Lido da documentação oficial em https://helena.readme.io (índice em https://helena.readme.io/llms.txt).

Base: `https://api.helena.run/{chat|core|crm}`. Autenticação em todas: `Authorization: Bearer <token>`.
Limite por conta: 1.000 chamadas a cada 5 minutos e 200 a cada 5 segundos. Passou disso: HTTP 429 (esperar e tentar de novo, sem repetir na hora).

## Tokens

| Token | Para quê | Onde se gera |
|---|---|---|
| **Token de Parceiro** (`pn_...`) | Gestão de contas: listar empresas, criar token de uma empresa | Admin > Personalizar > Integração |
| **Token da conta** | Tudo do dia a dia daquela conta: canais, mensagens, contatos, CRM, webhooks | Ajustes > Integrações > Integração via API, ou `POST core/v1/company/{id}/tokens` |

## Contas (Token de Parceiro)

| Uso | Chamada | Campos |
|---|---|---|
| Listar empresas | `GET core/v1/company` | query `SearchableText`, `PageNumber`, `PageSize` (máx. 100). Resposta paginada: `id`, `name`, `legalName`, `active`, `email`, `phoneNumber`, `setupStatus` |
| Obter empresa | `GET core/v1/company/{id}` | mesmos campos |
| Criar token da empresa | `POST core/v1/company/{id}/tokens` | corpo `{name}`. Resposta: `id`, `token` |

## Canais (números de WhatsApp)

`GET chat/v1/channel?ChannelType=All` → lista: `id`, `active`, `type` (`CloudAPI_WhatsApp` = oficial; `ZAPI_WhatsApp`, `Dialog360_WhatsApp`, `EvolutionApi_WhatsApp`, `Instagram`...), `number`, `numberFormatted`, `identity.displayName`. Sem paginação.

## Webhooks (o que avisa o nosso sistema)

| Uso | Chamada | Campos |
|---|---|---|
| Criar assinatura | `POST core/v1/webhook/subscription` | `name`, `url`, `events` (lista), `enabled` |
| Listar | `GET core/v1/webhook/subscription` | `id`, `name`, `url`, `enabled`, `events` (na resposta, objetos `{event, description}`) |
| Alterar | `PUT core/v1/webhook/subscription/{id}` | **`fields` obrigatório** (`Name`, `Url`, `Events`, `Enabled`) + os campos |
| Remover | `DELETE core/v1/webhook/subscription/{id}` | — |

Eventos: `SESSION_NEW`, `SESSION_UPDATE`, `SESSION_COMPLETE`, `MESSAGE_RECEIVED`, `MESSAGE_UPDATED`, `MESSAGE_SENT`, `CONTACT_NEW`, `CONTACT_UPDATE`, `CONTACT_TAG_UPDATE`, `PANEL_CARD_NEW`, `PANEL_CARD_UPDATE`, `PANEL_CARD_STEP_CHANGE`, `PANEL_CARD_NOTE_NEW`, `PANEL_CARD_NOTE_UPDATE`, `TEMPLATE_NEW`, `TEMPLATE_UPDATE`, `PAYMENT_NEW`, `PAYMENT_UPDATE`.
Corpo enviado: `{eventType, date, content}`. **A documentação não traz** o formato de `MESSAGE_RECEIVED`/`MESSAGE_SENT`, nem assinatura (HMAC) ou política de nova tentativa. O formato que usamos (`content.direction`, `content.origin`, `content.details.from/to`, `details.transcription.text`, `details.file.publicUrl`) vem dos fluxos do n8n que já rodam: confirmar no primeiro teste real. Como não há assinatura, protegemos a URL com um segredo próprio na query.

## Atendimentos (sessões)

| Uso | Chamada | Campos |
|---|---|---|
| Obter | `GET chat/v2/session/{id}?includeDetails=ContactDetails&includeDetails=ChannelDetails` | `id`, `status`, `contactId`, `channelId`, `departmentId`, `userId`, `windowStatus` (`ACTIVE`/`EXPIRED`: janela de 24 h), `utm`, `contactDetails`, `channelDetails` |
| Transferir | `PUT chat/v1/session/{id}/transfer` | `type` (`DEPARTMENT`/`USER`), `newDepartmentId`, `newUserId`, `options.stopBotInExecution` |
| Concluir | `PUT chat/v1/session/{id}/complete` | `reactivateOnNewMessage`, `stopBotInExecution` |
| Mudar status | `PUT chat/v1/session/{id}/status` | `newStatus` (`PENDING`, `IN_PROGRESS`, `COMPLETED`...) |
| Listar mensagens | `GET chat/v1/session/{id}/message` | `PageNumber`, `PageSize`, `OrderDirection`. Itens: `id`, `type`, `direction`, `origin`, `text`, `details` |
| Nota interna | `POST chat/v1/session/{id}/note` | `text` |

Não existe "criar atendimento": abre-se mandando mensagem com `options.forceStartSession`.

## Mensagens

| Uso | Chamada | Campos |
|---|---|---|
| Enviar no atendimento | `POST chat/v1/session/{id}/message` | `text`, ou `fileUrl`, ou `templateId` + `parameters`. Resposta: `id` (guardamos para reconhecer o eco), `status` |
| Enviar sem atendimento | `POST chat/v1/message/send` | `to` (telefone), `from` (número do canal), `body` (`text`/`fileUrl`/`templateId`), `options.forceStartSession`. Conversa nova no WhatsApp só começa com modelo aprovado |
| Status | `GET chat/v1/message/{id}/status` | `status` (`QUEUED`, `SENT`, `DELIVERED`, `READ`, `FAILED`), `failureReason` |
| Modelos (templates) | `GET chat/v1/template?Type=ATTENDANCE&ApprovedOnly=true&PageSize=100` | `id`, `name`, `text`, `status`, `channelId`, `params` |

O envio é assíncrono: a resposta diz que entrou na fila; a entrega se confirma pelo status ou pelo webhook.

## Contatos e etiquetas

| Uso | Chamada | Campos |
|---|---|---|
| Buscar por telefone | `GET core/v1/contact/phonenumber/{phone}` | `id`, `name`, `phoneNumber`, `tagIds`, `tagNames`, `customFields`, `utm` |
| Criar | `POST core/v1/contact` | `name`, `phoneNumber`, `tagNames`, `customFields`, `options.upsert`, `options.getIfExists` |
| Etiquetas do contato | `POST core/v1/contact/{id}/tags` | `tagIds` ou `tagNames`, `operation` (`InsertIfNotExists`, `DeleteIfExists`, `ReplaceAll`) |
| Listar etiquetas | `GET core/v1/tag` | `id`, `name`, `color` |
| Criar etiqueta | `POST core/v1/tag` | `name`, `color` (ex.: `GREEN_500`) |

## CRM (painéis e cards)

| Uso | Chamada | Campos |
|---|---|---|
| Listar painéis com etapas | `GET crm/v2/panel?IncludeDetails=Steps&PageSize=100` | painel: `id`, `title`, `type`; etapa: `id`, `title`, `position`, `isInitial`, `isFinal` |
| Detalhe do painel | `GET crm/v1/panel/{id}?IncludeDetails=Steps` | idem |
| Cards de um contato | `GET crm/v2/panel/card?PanelId={id}&ContactId={id}` | `PanelId` obrigatório; não filtra por atendimento |
| Criar card | `POST crm/v2/panel/card` | `stepId`, `title` (obrigatórios), `description`, `contactIds`, `sessionId`, `tagNames`, `monetaryAmount`, `customFields` |
| Mover card | `PUT crm/v3/panel/card/{id}` | `fields: ["StepId"]` + `stepId`. Pela especificação `fields` não é obrigatório (o corpo não tem campo obrigatório), mas diz quais campos mudar; mandamos sempre. Atenção: `options.upsertTagOperation` tem padrão `ReplaceAll` (apaga as etiquetas do card que não forem enviadas) |
| Nota no card | `POST crm/v1/panel/card/{cardId}/note` | `text` |

## Equipes e atendentes

`GET core/v2/department` (equipes: `id`, `name`, `isDefault`) e `GET core/v1/agent` (atendentes: `id`, `name`, `email`). Usados para escolher para onde transferir.

## O que a documentação não responde (testar no primeiro uso real)

- Formato exato de `MESSAGE_RECEIVED` / `MESSAGE_SENT` no webhook.
- Formato aceito de telefone em `phoneNumber` (com ou sem `+55`).
- Se a paginação vai na query (o que as páginas de listagem mostram) ou no corpo (o que a página geral diz).

Capacidades que a API tem e ainda não usamos: ver `docs/HELENA_CAPACIDADES.md` (25/11/2026).
