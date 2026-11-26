# LíderHub: leitura completa (produto + API), 22/11/2026

Complementa `liderhub_agentes.md`. Fonte: https://docs.liderhub.ai (llms.txt, openapi, ~60 páginas). Paráfrase.

## API (base https://api.liderhub.com.br, header `x-company-key`, 1 chave por workspace)
Paginação `page`/`limit` (20, máx. 100). Erros 400/401/404/500/502/503. Rate limit não documentado aqui (outra página fala 3 req/s).
- Conexões: `GET /v1/connections`, `GET /v1/connections/{id}` (`number`, `connectionStatus`, `agent`, `department`, `integration` WHATSAPP-BUSINESS|NON-OFFICIAL).
- Funil e classes: `GET/PATCH /v1/settings/status`, `/source`, `/tags` (`replace`), `/departamentos` — um contato por vez.
- `GET /v1/users`, `GET /v1/agents` (`id`, `name`, `delayTime`).
- Contatos: `POST /v1/contacts` (valida se é WhatsApp: `exist`), `GET /v1/contacts` (filtros por número, conexão, status, stage Open/Closed/Pending, departamento, tags, datas), `POST /v1/contacts/{id}/mark-read`.
- Mensagens: `POST /v1/send/message` (`messageType` conversation/image/video/audio/document, `scheduledAt`, `note` = nota interna), `GET /v1/message`, `GET /v1/message/{id}` (`errorDetails`), `POST /v1/message/{id}/cancel`, `POST /v1/send/template` (`variables` var1, var2...).
- Templates: `GET /v1/templates`, `GET /v1/templates/{id}` (`metaStatus`, `metaComponents`).
- Grupos: listar/criar/detalhar/editar, modo anúncio, participantes, admins (9 operações).
- MCP: descontinuado (tinha 14 ferramentas de leitura e envio).

## Produto
- **Inbox**: abas IA, Ativos, Pendentes, Grupos, Arquivados; visões Conversas, Contatos, Kanban; intervenção pontual x assumir; modo foco; resumo simples/detalhado como nota; ações em massa (sem disparar follow-up).
- **Propriedades**: status único por conversa (com tipo para métricas e departamento acoplado), departamento, responsável (humano ou agente), etiquetas, origem (automática por palavra-chave), variáveis por lead e da empresa, log de alterações.
- **Permissões**: Administrador, Gerente, Suporte; filtro por departamento e conexão; responsável sempre vê; mencionado em nota vê por 24 h.
- **Workspaces** isolados; um WhatsApp só em um workspace; criação com clonagem de configuração.
- **Agendamentos**: mensagem agendada manual (1 h, 24 h, linguagem natural); central com saúde por conexão (Saudável/Risco/Crítico), reagendamento em massa com intervalo padrão de 30 s.
- **Horário comercial** por workspace (GMT-3); limita follow-ups (fora do horário, vai para o próximo período, distribuído).
- **Templates**: texto, imagem, vídeo, áudio, PDF; aprovação Meta para abrir janela de 24 h (categoria Marketing para follow-up).
- **Follow-up** por status: sequência com cadência a partir da troca de status; lead responde = reagenda; "desistir do lead" no último item (troca status, responsável e arquiva).
- **Voz**: voz clonada (amostra ≥ 10 s), modo áudio; 120 créditos/min gerado, 6/min transcrito.
- **Conflito inicial** e **alucinação**: guias de prompt (roteiro antes da primeira mensagem; completar base; transferir quando não souber).
- **Créditos**: ~9 por resposta da IA (6–13), por tamanho de prompt (5,9 a 17,6), alertas 80%/100%, aviso em chat > 500 créditos, excedente R$ 0,04/crédito ou troca para modelo mais barato.
- **Dashboard comercial**: tipos de status (Nova, Análise, Qualificado, Proposta, Sucesso, Desqualificado, Recusada, Desistência), cohort x evento, conversões, Sankey.
- **Notificações** push/sino: contrato gerado/assinado, atribuição, mudança de status, menção, @notificar, WhatsApp desconectado.
- **Contatos**: importação CSV/Excel com relatório de erros; exportação filtrada.
- **ZapSign**: sincroniza modelos, agente ligado ao modelo, pós-assinatura (responsável, status, template, departamento); sem API = link de formulário.
- **CTWA**: `ctwaClid` do anúncio para devolver conversão à Meta.

## Leitura para o LawChat (lembrete do princípio)
Atendimento, inbox, kanban e CRM continuam na **Helena (LawChat)**. Daqui vêm a IA, a gestão e as automações pela API da Helena.
Do LíderHub vale trazer para a gestão: **follow-up por etapa com desistência**, **horário comercial**, **painel de consumo com
alertas e teto por conversa**, **dashboard de funil (cohort x evento)**, **resumo do caso como nota**, **palavra-chave/UTM por
campanha**, **ctwaClid para conversão Meta**, **pós-assinatura configurável** (já temos parte) e **notificações**.
