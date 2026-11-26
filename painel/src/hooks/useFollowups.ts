// Tipos e constantes do follow-up (copiados do agents-lawchat-main). Aqui o follow-up é por agente
// (telas próprias); o padrão do catálogo fica no jsonb padrao_followup do produto.

export type CrmStage = "sdr" | "closer" | "contrato" | "assinatura";

export const STAGE_LABELS: Record<CrmStage, string> = {
  sdr: "SDR",
  closer: "Closer",
  contrato: "Contrato",
  assinatura: "Etapa de Assinatura",
};

export const STAGE_ORDER: CrmStage[] = ["sdr", "closer", "contrato", "assinatura"];

export const DELAY_OPTIONS: { value: string; label: string }[] = [
  { value: "10m", label: "10 minutos" },
  { value: "20m", label: "20 minutos" },
  { value: "30m", label: "30 minutos" },
  { value: "1h", label: "1 hora" },
  { value: "2h", label: "2 horas" },
  { value: "4h", label: "4 horas" },
  { value: "6h", label: "6 horas" },
  { value: "12h", label: "12 horas" },
  { value: "24h", label: "24 horas" },
  { value: "2d", label: "2 dias" },
  { value: "3d", label: "3 dias" },
  { value: "4d", label: "4 dias" },
  { value: "5d", label: "5 dias" },
  { value: "6d", label: "6 dias" },
  { value: "7d", label: "7 dias" },
  { value: "10d", label: "10 dias" },
  { value: "15d", label: "15 dias" },
  { value: "30d", label: "30 dias" },
  { value: "45d", label: "45 dias" },
  { value: "60d", label: "60 dias" },
];

export const delayLabel = (v: string) =>
  DELAY_OPTIONS.find((o) => o.value === v)?.label ?? v;

export interface FollowupCadenceItem {
  order: number;
  delay: string;
}

export interface FollowupAgentConfig {
  name: string;
  prompt: string;
}

export interface ProductFollowup {
  id: string;
  workspace_id: string;
  agent_group_id: string;
  enabled: boolean;
  restart_on_reply: boolean;
  crm_stages: CrmStage[];
  cadence: FollowupCadenceItem[];
  agents: Partial<Record<CrmStage, FollowupAgentConfig>>;
  provisioning_status?: string;
  created_at: string;
  updated_at: string;
}

