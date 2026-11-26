export interface EventTypeDef {
  type: string;
  label: string;
  category: string;
  description?: string;
}

export const EVENT_CATALOG: EventTypeDef[] = [
  // Canal
  { type: "channel.whatsapp.requested",    label: "WhatsApp - sincronização solicitada", category: "Canal",     description: "Disparado quando o usuário pede sincronização de números no WhatsApp" },
  { type: "channel.connection_initiated",  label: "Conexão de canal iniciada",           category: "Canal" },

  // Produto / Agente
  { type: "agent.product.created",         label: "Produto criado (provisionar agente)", category: "Produto",   description: "Disparado ao finalizar a criação. n8n deve construir o agente e responder com agent.provisioning.ready" },
  { type: "agent.product.updated",         label: "Produto atualizado",                  category: "Produto" },
  { type: "agent.product.status_changed",  label: "Produto play/pause",                  category: "Produto" },
  { type: "agent.product.deleted",         label: "Produto excluído",                    category: "Produto" },
  { type: "agent.updated",                 label: "Agente individual atualizado",        category: "Agente" },

  // Base de conhecimento
  { type: "kb.item.added",                 label: "Item de conhecimento adicionado",     category: "Conhecimento" },
  { type: "kb.item.removed",               label: "Item de conhecimento removido",       category: "Conhecimento" },

  // Follow-up
  { type: "followup.created",              label: "Follow-up criado",                    category: "Follow-up" },
  { type: "followup.updated",              label: "Follow-up atualizado",                category: "Follow-up" },
  { type: "followup.status_changed",       label: "Follow-up play/pause",                category: "Follow-up" },

  // Notificações
  { type: "notification.created",          label: "Notificação criada",                  category: "Notificações" },
  { type: "notification.updated",          label: "Notificação atualizada",              category: "Notificações", description: "Envia changed_fields indicando o que mudou" },
  { type: "notification.enabled",          label: "Notificação ativada",                 category: "Notificações" },
  { type: "notification.disabled",         label: "Notificação desativada",              category: "Notificações" },
  { type: "notification.deleted",          label: "Notificação excluída",                category: "Notificações" },
  { type: "notification.dispatch",         label: "Notificação disparada",               category: "Notificações" },
  { type: "notification.configured",       label: "Notificação configurada (legado)",    category: "Notificações", description: "DEPRECATED — substituído por notification.created. Mantido por compatibilidade com n8n." },

  // CRM
  { type: "lead.stage_changed",            label: "Lead mudou de etapa",                 category: "CRM" },

  // Diagnóstico
  { type: "test.ping",                     label: "Teste (ping)",                        category: "Diagnóstico" },
];

export const EVENT_CATEGORIES = Array.from(new Set(EVENT_CATALOG.map((e) => e.category)));

export const INBOUND_TYPES = [
  "message.received",
  "agent.response",
  "agent.provisioning.ready",
  "agent.provisioning.failed",
  "followup.provisioning.ready",
  "followup.provisioning.failed",
  "lead.qualified",
  "contract.signed",
  "processo.update",
  "test.ping",
];
