import { LLMModel } from "@/types/agent";

export const llmModels: LLMModel[] = [
  {
    id: "gpt-4.1-mini",
    provider: "openai",
    name: "GPT-4.1 Mini",
    shortName: "4.1 Mini",
    costPer1kIn: 0.0004,
    costPer1kOut: 0.0016,
    speed: "fast",
    strengths: ["Rápido", "Econômico", "Equilibrado"],
    contextWindow: "128k",
    recommended: true,
  },
  {
    id: "gpt-4.1",
    provider: "openai",
    name: "GPT-4.1",
    shortName: "4.1",
    costPer1kIn: 0.002,
    costPer1kOut: 0.008,
    speed: "balanced",
    strengths: ["Inteligente", "Versátil", "Multimodal"],
    contextWindow: "128k",
  },
  {
    id: "gpt-4.1-nano",
    provider: "openai",
    name: "GPT-4.1 Nano",
    shortName: "4.1 Nano",
    costPer1kIn: 0.0001,
    costPer1kOut: 0.0004,
    speed: "lightning",
    strengths: ["Ultra rápido", "Mais barato"],
    contextWindow: "128k",
  },
  {
    id: "gpt-5.1-mini",
    provider: "openai",
    name: "GPT-5.1 Mini",
    shortName: "5.1 Mini",
    costPer1kIn: 0.0006,
    costPer1kOut: 0.0024,
    speed: "fast",
    strengths: ["Raciocínio melhor", "Econômico"],
    contextWindow: "200k",
  },
  {
    id: "gpt-5.1",
    provider: "openai",
    name: "GPT-5.1",
    shortName: "5.1",
    costPer1kIn: 0.003,
    costPer1kOut: 0.012,
    speed: "balanced",
    strengths: ["Top reasoning", "Mais preciso"],
    contextWindow: "200k",
  },
  {
    id: "gpt-5.1-nano",
    provider: "openai",
    name: "GPT-5.1 Nano",
    shortName: "5.1 Nano",
    costPer1kIn: 0.00015,
    costPer1kOut: 0.0006,
    speed: "lightning",
    strengths: ["Ultra rápido", "Custo mínimo"],
    contextWindow: "128k",
  },
];

/**
 * Normaliza QUALQUER valor de modelo para um ID válido da plataforma (ex.: "GPT-4.1 Mini" →
 * "gpt-4.1-mini", "openai/gpt-4.1-mini" → "gpt-4.1-mini"). Só os modelos de `llmModels` são
 * aceitos: vazio ou qualquer modelo fora da lista vira o padrão (GPT-4.1 Mini). É a forma
 * CERTA que vai para o bot — ele espera o id, não o nome de exibição.
 */
export const resolveModelId = (value?: string | null): string => {
  const DEFAULT = "gpt-4.1-mini";
  const raw = (value ?? "").trim();
  if (!raw) return DEFAULT;
  const low = raw.replace(/^[\w.-]+\//, "").toLowerCase(); // tira o prefixo "openai/" etc.
  const byId = llmModels.find((m) => m.id.toLowerCase() === low);
  if (byId) return byId.id;
  const byName = llmModels.find(
    (m) => m.name.toLowerCase() === raw.toLowerCase() || (m.shortName ?? "").toLowerCase() === raw.toLowerCase(),
  );
  if (byName) return byName.id;
  return DEFAULT; // fora da lista da plataforma → padrão
};

export const providerColors: Record<LLMModel["provider"], string> = {
  openai: "from-emerald-500 to-teal-600",
  anthropic: "from-orange-500 to-amber-600",
  meta: "from-blue-600 to-indigo-700",
  deepseek: "from-violet-500 to-purple-600",
  groq: "from-rose-500 to-pink-600",
};
