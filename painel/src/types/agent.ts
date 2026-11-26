export type AgentCategory =
  | "Vendas" | "Atendimento" | "Suporte" | "Agendamento"
  | "Marketing" | "RH" | "Educação" | "Saúde"
  | "Jurídico" | "Imobiliário" | "E-commerce" | "Financeiro";

export type LLMProvider = "openai" | "anthropic" | "meta" | "deepseek" | "groq";

export interface PromptBlock {
  id: string;
  type: "persona" | "objective" | "context" | "rules" | "do" | "dont" | "tone" | "format" | "examples" | "ending";
  icon: string;
  label: string;
  content: string | string[];
  highlight?: boolean;
}

export interface AgentTemplate {
  id: string;
  slug: string;
  name: string;
  category: AgentCategory;
  icon: string;
  coverGradient: string;
  shortDescription: string;
  longDescription: string;
  tags: string[];
  recommendedModel: string;
  recommendedProvider: LLMProvider;
  costPerConversation: number;
  rating: number;
  installs: number;
  promptBlocks: PromptBlock[];
  includedTools: string[];
  welcomeMessage: string;
  useCases: string[];
  conversationExamples: { user: string; agent: string }[];
}

export interface ActiveAgent {
  id: string;
  workspaceId: string;
  name: string;
  templateId: string;
  templateName: string;
  templateVersion: string;
  status: "active" | "draft" | "paused" | "error";
  channels: string[];
  model: string;
  conversationsToday: number;
  satisfaction: number;
  monthCost: number;
  createdAt: string;
}

export interface LLMModel {
  id: string;
  provider: LLMProvider;
  name: string;
  shortName: string;
  costPer1kIn: number;
  costPer1kOut: number;
  speed: "lightning" | "fast" | "balanced" | "deep";
  strengths: string[];
  contextWindow: string;
  recommended?: boolean;
}
