import {
  Bell, UserCheck, Handshake, ClipboardList, FileSignature,
  AlertTriangle, FileCheck2, BookOpen, Building2, type LucideIcon,
} from "lucide-react";

export type NotificationPhase = "entrada" | "negociacao" | "assinatura" | "alerta";

export interface NotificationEvent {
  id: string;
  label: string;
  description: string;
  emoji: string;
  Icon: LucideIcon;
  /** Container do ícone. NEUTRO por padrão (design system: verde só como acento).
   *  Âmbar discreto só onde há semântica real de atenção. */
  tone: string;
  /** Fase do funil — agrupa os eventos numa linguagem que o advogado reconhece. */
  fase: NotificationPhase;
  /** Avisos essenciais sugeridos no primeiro uso. */
  recomendado?: boolean;
  defaultTemplate: string;
  /** Variáveis realmente disponíveis no payload deste evento */
  availableVars: string[];
}

const tag = (s: string) => "`" + s + "`";

// Ícone sempre neutro; cor só comunica ESTADO (ativa) — não categoria.
const NEUTRO = "bg-muted text-muted-foreground border-border";
// Exceção: eventos que SÃO alertas de atenção ganham um âmbar discreto.
const ALERTA = "bg-amber-50 text-amber-600 border-amber-200";

// Variáveis comuns que aparecem em quase todo evento
const BASE_VARS = ["{{nome}}", "{{telefone}}", "{{produto}}", "{{data_hora}}"];

export const NOTIFICATION_EVENTS: NotificationEvent[] = [
  {
    id: "novo_lead_recebido",
    label: "Novo Lead Recebido",
    description: "Avisa quando um novo lead entra no sistema",
    emoji: "🔔",
    Icon: Bell,
    tone: NEUTRO,
    fase: "entrada",
    recomendado: true,
    availableVars: [...BASE_VARS, "{{origem}}", "{{primeira_mensagem}}"],
    defaultTemplate:
`> ${tag("🔵 NOVO LEAD RECEBIDO")}

👤 *Cliente:* {{nome}}
📞 *WhatsApp:* {{telefone}}
🛒 *Produto:* {{produto}}
🕒 *Recebido em:* {{data_hora}}
🌐 *Origem:* {{origem}}

💬 _Primeira mensagem:_
> {{primeira_mensagem}}`,
  },
  {
    id: "lead_qualificado",
    label: "Lead Qualificado",
    description: "Avisa quando um lead é qualificado pelo agente",
    emoji: "🟢",
    Icon: UserCheck,
    tone: NEUTRO,
    fase: "entrada",
    recomendado: true,
    availableVars: [...BASE_VARS, "{{etapa}}", "{{resumo}}"],
    defaultTemplate:
`> ${tag("🟢 LEAD QUALIFICADO")}

👤 *Cliente:* {{nome}}
📞 *WhatsApp:* {{telefone}}
🛒 *Produto:* {{produto}}
🎯 *Etapa CRM:* {{etapa}}

📋 *Resumo da qualificação:*
{{resumo}}`,
  },
  {
    id: "lead_aceitou_honorarios",
    label: "Lead Aceitou Honorários",
    description: "Avisa quando o lead aceita a proposta de honorários",
    emoji: "🤝",
    Icon: Handshake,
    tone: NEUTRO,
    fase: "negociacao",
    availableVars: [...BASE_VARS, "{{valor}}", "{{forma_pagamento}}", "{{parcelas}}"],
    defaultTemplate:
`> ${tag("🤝 HONORÁRIOS ACEITOS")}

👤 *Cliente:* {{nome}}
📞 *WhatsApp:* {{telefone}}
🛒 *Produto:* {{produto}}

💰 *Valor acordado:* {{valor}}
💳 *Forma de pagamento:* {{forma_pagamento}}
📅 *Parcelas:* {{parcelas}}`,
  },
  {
    id: "lead_iniciou_coleta",
    label: "Lead Iniciou a Coleta de Dados",
    description: "Avisa quando o lead inicia a coleta de dados",
    emoji: "📋",
    Icon: ClipboardList,
    tone: NEUTRO,
    fase: "negociacao",
    availableVars: [...BASE_VARS],
    defaultTemplate:
`> ${tag("📋 COLETA DE DADOS INICIADA")}

👤 *Cliente:* {{nome}}
📞 *WhatsApp:* {{telefone}}
🛒 *Produto:* {{produto}}
🕒 *Início:* {{data_hora}}`,
  },
  {
    id: "aguardando_assinatura",
    label: "Aguardando Assinatura",
    description: "Avisa quando o contrato está aguardando assinatura",
    emoji: "⏳",
    Icon: FileSignature,
    tone: NEUTRO,
    fase: "assinatura",
    availableVars: [...BASE_VARS, "{{link_assinatura}}"],
    defaultTemplate:
`> ${tag("⏳ AGUARDANDO ASSINATURA")}

👤 *Cliente:* {{nome}}
📞 *WhatsApp:* {{telefone}}
🛒 *Produto:* {{produto}}

🔗 *Link de assinatura:* {{link_assinatura}}
📤 *Enviado em:* {{data_hora}}`,
  },
  {
    id: "dificuldade_assinatura",
    label: "Dificuldade na Assinatura",
    description: "Avisa quando o lead tem dificuldade ao assinar",
    emoji: "⚠️",
    Icon: AlertTriangle,
    tone: ALERTA,
    fase: "alerta",
    availableVars: [...BASE_VARS, "{{resumo}}"],
    defaultTemplate:
`> ${tag("⚠️ DIFICULDADE NA ASSINATURA")}

👤 *Cliente:* {{nome}}
📞 *WhatsApp:* {{telefone}}
🛒 *Produto:* {{produto}}

🧩 *Motivo relatado:*
> {{resumo}}

🕒 *Última tentativa:* {{data_hora}}`,
  },
  {
    id: "contrato_assinado",
    label: "Contrato Assinado",
    description: "Avisa quando um contrato é assinado",
    emoji: "✅",
    Icon: FileCheck2,
    tone: NEUTRO,
    fase: "assinatura",
    recomendado: true,
    availableVars: [...BASE_VARS, "{{valor}}"],
    defaultTemplate:
`> ${tag("✅ CONTRATO ASSINADO")}

🎉 *Cliente confirmado!*

👤 *Cliente:* {{nome}}
📞 *WhatsApp:* {{telefone}}
🛒 *Produto:* {{produto}}

💰 *Valor:* {{valor}}
📅 *Assinado em:* {{data_hora}}`,
  },
  {
    id: "lead_nao_sabe_ler",
    label: "Lead Não Sabe Ler",
    description: "Avisa o suporte quando o lead declara não saber ler",
    emoji: "📖",
    Icon: BookOpen,
    tone: ALERTA,
    fase: "alerta",
    availableVars: [...BASE_VARS, "{{etapa}}"],
    defaultTemplate:
`> ${tag("📖 ATENÇÃO: LEAD NÃO SABE LER")}

👤 *Cliente:* {{nome}}
📞 *WhatsApp:* {{telefone}}
🛒 *Produto:* {{produto}}
🎯 *Etapa atual:* {{etapa}}

⚠️ *Atendimento humano necessário* — o agente identificou que o lead não consegue acompanhar mensagens escritas.`,
  },
  {
    id: "cliente_escritorio",
    label: "É Cliente do Escritório",
    description: "Avisa quando o lead já é cliente do escritório",
    emoji: "🏢",
    Icon: Building2,
    tone: ALERTA,
    fase: "alerta",
    availableVars: [...BASE_VARS],
    defaultTemplate:
`> ${tag("🏢 CLIENTE DO ESCRITÓRIO IDENTIFICADO")}

👤 *Cliente:* {{nome}}
📞 *WhatsApp:* {{telefone}}
🛒 *Produto procurado:* {{produto}}

⚠️ *Ação necessária:* direcionar para o responsável atual ao invés de tratar como lead novo.`,
  },
];

/** Rótulos das fases — cabeçalhos de grupo na linguagem do escritório. */
export const PHASE_LABELS: Record<NotificationPhase, string> = {
  entrada: "Entrada de leads",
  negociacao: "Negociação",
  assinatura: "Assinatura",
  alerta: "Alertas",
};

export const PHASE_ORDER: NotificationPhase[] = ["entrada", "negociacao", "assinatura", "alerta"];

/** Cor LEVE (pastel) por fase — dá vida ao card e simboliza o tipo do aviso, sem pesar:
 *  azul = entrada de leads · violeta = negociação · verde = assinatura · âmbar = alertas.
 *  bg-50 (fundo suave) + text-600 (ícone) + border-200. */
export const PHASE_TONES: Record<NotificationPhase, string> = {
  entrada: "bg-blue-50 text-blue-600 border-blue-200",
  negociacao: "bg-violet-50 text-violet-600 border-violet-200",
  assinatura: "bg-emerald-50 text-emerald-600 border-emerald-200",
  alerta: "bg-amber-50 text-amber-600 border-amber-200",
};

/** Catálogo completo (para casos em que precisamos listar tudo) */
export const NOTIFICATION_VARIABLES = Array.from(
  new Set(NOTIFICATION_EVENTS.flatMap((e) => e.availableVars)),
);

/** Nome humano de cada variável (para mostrar como pílula em vez de {{codigo}}). */
export const VARIABLE_LABELS: Record<string, string> = {
  "{{nome}}": "Nome do cliente",
  "{{telefone}}": "WhatsApp do cliente",
  "{{produto}}": "Produto",
  "{{data_hora}}": "Data e hora",
  "{{origem}}": "Origem do lead",
  "{{primeira_mensagem}}": "Primeira mensagem",
  "{{etapa}}": "Etapa do funil",
  "{{resumo}}": "Resumo",
  "{{valor}}": "Valor",
  "{{forma_pagamento}}": "Forma de pagamento",
  "{{parcelas}}": "Parcelas",
  "{{link_assinatura}}": "Link de assinatura",
};
export const varLabel = (v: string) => VARIABLE_LABELS[v] ?? v.replace(/[{}]/g, "");

export const RECIPIENT_TYPE_LABELS: Record<string, string> = {
  phone: "Um número de WhatsApp",
  user: "Um usuário do sistema",
  responsible: "A pessoa responsável pelo cliente",
};

export const getEventById = (id: string) =>
  NOTIFICATION_EVENTS.find((e) => e.id === id);
