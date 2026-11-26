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
    id: "gpt-6-luna",
    provider: "openai",
    name: "GPT-6 Luna",
    shortName: "6 Luna",
    costPer1kIn: 0.0001,
    costPer1kOut: 0.0005,
    speed: "fast",
    strengths: ["Nova geração", "Raciocínio", "Mais barato"],
    contextWindow: "—",
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
