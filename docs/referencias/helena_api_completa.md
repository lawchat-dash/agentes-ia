# API da Helena: referência de integração (leitura de 22/11/2026)

Fonte: https://helena.readme.io (índice em /llms.txt, ~200 páginas; ~40 lidas a fundo). Complementa `docs/HELENA_API.md`.
Princípio do projeto: **atendimento e CRM ficam na Helena (LawChat)**; este sistema é a gestão e a IA, integrado pela API.

## Autenticação, limites, paginação
- Token de conta: Helena › Ajustes › Integrações › Integração via API. Token de parceiro (`pn_`): Admin › Personalizar › Integração; só para Gestão de Contas/Parceiros.
- Cabeçalho `Authorization: Bearer <token>`. Bases: `/core`, `/chat`, `/crm`, `/auth` em `https://api.helena.run`.
- Limite **por conta**: 1.000 req / 5 min (média ~3/s), rajada 200 req / 5 s; excesso = 429 (usar espera crescente). Envio de modelo: 1.000 req / 2 min.
- GET: `PageNumber` (1), `PageSize` (15, máx. 100). POST de filtro: `pageNumber`, `pageSize`. Envelope: `items`, `totalItems`, `totalPages`, `hasMorePages`.
- Erros 400/401/429: ProblemDetails (`type`, `title`, `status`, `detail`). 500: `InternalException` (`text`, `isUnsolvableError`, `id`).

## Chat
| Uso | Chamada | Campos principais |
|---|---|---|
| Listar conversas | `GET /chat/v2/session` | `Status[]` (STARTED, PENDING, IN_PROGRESS, COMPLETED, HIDDEN), `DepartmentId`, `UserId`, `TagsId`, `ChannelsId`, `ContactId`, datas `.Before/.After`, `IncludeDetails` |
| Uma conversa | `GET /chat/v2/session/{id}` | resposta: `status`, `contactId`, `channelId`, `departmentId`, `userId`, `botId`, `utm`, `origin`, `windowStatus` (ACTIVE/EXPIRED), `lastMessageIn/Out`, `metadata` |
| Trocar departamento/atendente | `PUT /chat/v1/session/{id}/transfer` | `type` DEPARTMENT\|USER, `newDepartmentId`, `newUserId`, `options.stopBotInExecution` |
| Atribuir atendente | `PUT /chat/v1/session/{id}/assignee` | `userId` |
| Encerrar | `PUT /chat/v1/session/{id}/complete` | `reactivateOnNewMessage`, `stopBotInExecution` |
| Alterar parcial | `PUT /chat/v2/session/{id}/partial` | `fields[]` (Status, UserId, DepartmentId, Metadata, Classification...), `classification.category` WON/LOST/INFO |
| Histórico | `GET /chat/v1/message?SessionId=` | `type` (TEXT, AUDIO, IMAGE, DOCUMENT, NOTE, TRACK...), `direction` FROM_HUB/TO_HUB, `origin` (DEFAULT, BOT, API, GATEWAY, CAMPAIGN), `status` |
| Enviar no atendimento | `POST /chat/v1/session/{id}/message` | `text` \| `templateId`+`parameters` \| `fileUrl`, `refId` (assíncrono; status em `/chat/v1/message/{id}/status`) |
| Nota interna | `POST /chat/v1/session/{id}/note` | `text`, `filesUrls` |
| Iniciar com modelo | `POST /chat/v1/send/template` | `from`, `to`, `templateId`, `parameters`, `options` (`forceStartSession`, `hiddenSession`, `enableBot`, `department`, `user`) |
| Modelos | `GET /chat/v1/template` | `ApprovedOnly`, `Type` (ATTENDANCE, CAMPAIGN...), `ChannelId`; item: `name`, `text`, `status`, `params` |
| Canais | `GET /chat/v1/channel?ChannelType=All` | `id`, `type`, `number`, `numberFormatted`, `active`, `identity` |
| Não lidos ainda | `/chat/v1/message/send`, `send-sync`, `send/text`, `send/typing`, `send/otp`, chatbots, agendadas, sequências | |

## Core
| Uso | Chamada | Campos |
|---|---|---|
| Buscar contatos | `POST /core/v1/contact/filter` | `phoneNumber`, `tagIds`, `customFields`, `includeDetails` (Tags, CustomFields) |
| Criar/atualizar contato | `POST /core/v1/contact` | `name`, `phoneNumber`, `tagNames`, `customFields`, `options.upsert`, `upsertFields[]`, `getIfExists` |
| Etiquetas do contato | `POST /core/v1/contact/{id ou telefone}/tags` | `tagIds`\|`tagNames`, `operation` InsertIfNotExists/DeleteIfExists/ReplaceAll |
| Etiquetas | `GET/POST /core/v1/tag`, `PUT/DELETE /core/v1/tag/{id}` | `name`, `color` |
| Departamentos | `GET /core/v2/department` (sem paginação) | `id`, `name`, `isDefault`, `agents[]`, `channels[]`, `distributionConfig` |
| Atendentes do departamento | `PUT /core/v1/department/{id}/agents` | `action` ReplaceAll/Upsert/Remove, `items[]` |
| Usuários | `POST /core/v1/agent`, `GET /core/v1/agent[/{id}]` | `name`, `profile` (Admin/Agent/RestrictedAgent), `email` |
| Campos personalizados | `GET /core/v1/custom-field?EntityType=CONTACT\|PANEL` | `key`, `type` (STRING, INTEGER, DATE, SINGLESELECT...), `options` |
| Webhooks | `GET/POST /core/v1/webhook/subscription`, `PUT .../{id}` (`fields` obrigatório) | `name`, `url`, `events[]`, `enabled` |
| Contas (parceiro) | `GET/POST /core/v1/company`, `/core/v1/company/{id}/tokens` | `setupStatus`, `active`, tokens da conta |

## CRM
| Uso | Chamada | Campos |
|---|---|---|
| Painéis e colunas | `GET /crm/v2/panel?IncludeDetails=Steps` | `steps[]`: `id`, `title`, `position`, `isInitial`, `isFinal` |
| Criar card | `POST /crm/v2/panel/card` | `stepId`, `title`, `contactIds`, `sessionId`, `tagNames`, `monetaryAmount`, `customFields` |
| Mover/alterar card | `PUT /crm/v3/panel/card/{id}` | `fields[]` (StepId, Status, MonetaryAmount, CustomFields...), `stepId`, `status` OPEN/WON/LOST |
| Nota no card | `POST /crm/v1/panel/card/{cardId}/note` | `text`, `fileUrls` (até 3) |
| Campos do painel | `GET /crm/v1/panel/{id}/custom-fields` | |

## Webhooks (eventos)
SESSION_NEW, SESSION_UPDATE, SESSION_COMPLETE, MESSAGE_RECEIVED, MESSAGE_UPDATED, MESSAGE_SENT, CONTACT_NEW,
CONTACT_UPDATE, CONTACT_TAG_UPDATE, PAYMENT_NEW, PAYMENT_UPDATE, PANEL_CARD_NEW, PANEL_CARD_UPDATE,
PANEL_CARD_STEP_CHANGE, PANEL_CARD_NOTE_NEW, PANEL_CARD_NOTE_UPDATE, TEMPLATE_NEW, TEMPLATE_UPDATE.
Envelope `{eventType, date, content}`. Sem assinatura de origem documentada: por isso a URL de cada escritório leva segredo próprio.

## Login integrado
`POST /auth/v1/login/authenticate` (backend, token permanente): `phoneNumber`/`email`, `redirectUrl` → `urlRedirect`.

## Pontos a confirmar com chamada real
`from` do envio de modelo (id do canal ou número); payloads dos 17 eventos não documentados; nomes de campo do webhook de contato (`tagsId` x `tagIds`).

## O que isso abre para o sistema (próximos usos)
- **Encerrar** atendimento quando o contrato é assinado (`complete`) e **classificar** WON/LOST (`partial`).
- **Valor no card** (`monetaryAmount`) e **status WON** no card ao assinar.
- **Campos personalizados** do contato/card com dados do lead (CPF, benefício) para a equipe ver na Helena.
- **Follow-up fora da janela de 24 h** no canal oficial: `send/template` com modelo aprovado.
- **Webhook de troca de coluna** (`PANEL_CARD_STEP_CHANGE`): quando a equipe move o card na Helena, o sistema pode reagir.
