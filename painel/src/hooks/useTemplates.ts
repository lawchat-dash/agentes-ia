import { useQuery } from "@tanstack/react-query";
import { api } from "@/api";
import { resolveModelId } from "@/data/llmModels";

export interface PromptBlock {
  id: string;
  type: string;
  icon: string;
  label: string;
  content: string | string[];
  highlight?: boolean;
}

export interface AgentTemplateRow {
  id: string;
  slug: string;
  name: string;
  category: string;
  icon: string | null;
  cover_gradient: string | null;
  description_short: string;
  description_long: string | null;
  tags: string[];
  recommended_provider: string;
  recommended_model: string;
  prompt_blocks: PromptBlock[];
  n_agentes: number | null;          // agentes do funil cadastrados no produto (lista do catálogo)
  recommended_tools: string[];
  welcome_message: string | null;
  use_cases: string[];
  avg_cost_per_conversation: number;
  installs_count: number;
  rating: number;
  version: string;
  is_published: boolean;
  status: "rascunho" | "em_breve" | "publicado";
  plan_min: string | null;
  modo_midia: "texto" | "audio";     // variante: texto envia texto, audio envia áudio
  id_produto_base: string | null;    // se variante, aponta pro produto-base (texto)
}

/** Mapeia sistemaia_biblioteca_produtos (pt) → shape AgentTemplateRow da UI */
const mapBibliotecaProduto = (t: any): AgentTemplateRow => ({
  id: t.id,
  slug: t.slug,
  name: t.nome,
  category: t.categoria ?? "juridico",
  icon: t.icone,
  cover_gradient: t.capa_gradiente,
  description_short: t.descricao_curta ?? "",
  description_long: t.descricao_longa,
  tags: Array.isArray(t.etiquetas) ? t.etiquetas : [],
  recommended_provider: "lovable",
  recommended_model: resolveModelId(t.modelo_recomendado),
  prompt_blocks: Array.isArray(t.blocos_prompt) ? t.blocos_prompt : [],
  n_agentes: typeof t.n_agentes === "number" ? t.n_agentes : null,
  recommended_tools: [],
  welcome_message: t.mensagem_boas_vindas,
  use_cases: Array.isArray(t.casos_de_uso) ? t.casos_de_uso : [],
  avg_cost_per_conversation: 0,
  installs_count: 0,
  rating: 0,
  version: t.versao ?? "1.0.0",
  status: (t.status ?? (t.publicado ? "publicado" : "rascunho")) as "rascunho" | "em_breve" | "publicado",
  is_published: (t.status ?? (t.publicado ? "publicado" : "rascunho")) === "publicado",
  plan_min: t.plano_minimo ?? null,
  modo_midia: (t.modo_midia === "audio" ? "audio" : "texto") as "texto" | "audio",
  id_produto_base: t.id_produto_base ?? null,
});

export const useTemplates = () => {
  return useQuery({
    queryKey: ["templates"],
    queryFn: async () => {
      const data = await api<any[]>("/biblioteca/produtos");
      return ((data ?? []) as any[]).map(mapBibliotecaProduto);
    },
  });
};

export const useTemplate = (slug: string | undefined) => {
  return useQuery({
    queryKey: ["template", slug],
    enabled: !!slug,
    queryFn: async () => {
      const data = await api<any>(`/biblioteca/produtos/${encodeURIComponent(slug!)}`).catch((e) => {
        if (e?.status === 404) return null;
        throw e;
      });
      return data ? mapBibliotecaProduto(data) : null;
    },
  });
};
