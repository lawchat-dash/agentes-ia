import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, enviar, geracaoAtual, guardarResposta, ultimaResposta } from "@/api";
import { useAuth } from "@/contexts/AuthContext";
import { resolveModelId } from "@/data/llmModels";
import { Phone, Handshake, FileText, PenLine, RotateCcw, UserX, Hourglass, type LucideIcon } from "lucide-react";

export type AgentRole = "sdr" | "closer" | "contratos" | "assinatura" | "follow_up" | "desqualificado" | "periododegraca";

export const ROLE_META: Record<AgentRole, { label: string; icon: string; Icon: LucideIcon; color: string }> = {
  sdr:            { label: "SDR",              icon: "📞", Icon: Phone,     color: "from-primary to-primary-glow" },
  periododegraca: { label: "Período de Graça", icon: "⏳", Icon: Hourglass, color: "from-primary to-primary-glow" },
  closer:         { label: "Closer",           icon: "🤝", Icon: Handshake, color: "from-primary to-primary-glow" },
  contratos:      { label: "Contratos",        icon: "📄", Icon: FileText,  color: "from-primary to-primary-glow" },
  assinatura:     { label: "Assinatura",       icon: "✍️", Icon: PenLine,   color: "from-primary to-primary-glow" },
  follow_up:      { label: "Follow-up",        icon: "🔁", Icon: RotateCcw, color: "from-primary to-primary-glow" },
  desqualificado: { label: "Desqualificado",   icon: "🎓", Icon: UserX,     color: "from-primary to-primary-glow" },
};

// Núcleo: os 5 papéis que TODO produto tem (não mexer — vários contadores/resumos dependem disso).
export const ROLE_ORDER: AgentRole[] = ["sdr", "closer", "contratos", "assinatura", "desqualificado"];

// Papéis OPCIONAIS (ligados por produto via flag). "Período de graça" é ramo lateral depois do SDR.
export const OPTIONAL_ROLES: AgentRole[] = ["periododegraca"];

// Ordem COMPLETA (núcleo + opcionais) — só p/ ORDENAR/localizar; não usar como contagem.
export const ALL_ROLES_ORDERED: AgentRole[] = ["sdr", "periododegraca", "closer", "contratos", "assinatura", "desqualificado"];

/** Índice de ordenação de um papel (período de graça cai logo após o SDR). */
export const roleSortIndex = (role: string): number => {
  const i = ALL_ROLES_ORDERED.indexOf(role as AgentRole);
  return i < 0 ? 99 : i;
};

export interface ProductTemplateAgent {
  id: string;
  product_template_id: string;
  role: AgentRole;
  display_name: string;
  description: string | null;
  icon: string | null;
  order: number;
  prompt_blocks: any[];
  prompt_text: string | null;
  welcome_message: string | null;
  recommended_model: string;
  recommended_provider: string;
  default_handoff_rules: any[];
}

/** Carrega os agentes-modelo de um Produto da biblioteca (sistemaia) */
export const useProductTemplateAgents = (productTemplateId: string | undefined) => {
  return useQuery({
    queryKey: ["product-template-agents", productTemplateId],
    enabled: !!productTemplateId,
    queryFn: async () => {
      const data = await api<any[]>(`/biblioteca/produtos/${productTemplateId}/agentes`);
      return ((data ?? []) as any[]).map((a) => ({
        id: a.id,
        product_template_id: a.id_produto_biblioteca,
        role: a.papel,
        display_name: a.nome_exibicao,
        description: a.descricao,
        icon: a.icone,
        order: a.ordem,
        prompt_blocks: Array.isArray(a.blocos_prompt) ? a.blocos_prompt : [],
        prompt_text: a.texto_prompt,
        welcome_message: a.mensagem_boas_vindas,
        farewell_message: a.mensagem_despedida,
        fallback_message: a.mensagem_fallback,
        recommended_model: resolveModelId(a.modelo_recomendado), // só modelos da plataforma (padrão GPT-4.1 Mini)
        recommended_provider: "lovable",
        default_handoff_rules: Array.isArray(a.regras_handoff) ? a.regras_handoff : [],
      })) as ProductTemplateAgent[];
    },
  });
};

// sistemaia_produtos_ativados usa status/provisionamento em pt;
// a UI antiga consome em en — mapeamos nas duas direções.
const STATUS_PT_EN: Record<string, string> = {
  rascunho: "draft", ativo: "active", pausado: "paused", erro: "error",
};
export const STATUS_EN_PT: Record<string, string> = {
  draft: "rascunho", active: "ativo", paused: "pausado", error: "erro",
};
const PROV_PT_EN: Record<string, string> = {
  pendente: "pending", construindo: "building", pronto: "ready", falhou: "failed",
};

/** Compara duas versões "x.y.z" — retorna <0 se a<b, 0 se igual, >0 se a>b. */
export const compararVersao = (a?: string | null, b?: string | null): number => {
  const pa = String(a ?? "0").split(".").map((n) => parseInt(n, 10) || 0);
  const pb = String(b ?? "0").split(".").map((n) => parseInt(n, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pa[i] ?? 0) - (pb[i] ?? 0);
    if (d !== 0) return d;
  }
  return 0;
};

/** Mapeia sistemaia_produtos_ativados (pt) → shape de produto da UI */
const mapProdutoAtivado = (p: any) => ({
  id: p.id,
  workspace_id: p.id_conta,
  weaver_agent_id: p.id_agente ?? p.id_agente_weaver ?? null,
  name: p.nome,
  description: p.descricao,
  status: STATUS_PT_EN[p.status] ?? "draft",
  provisioning_status: PROV_PT_EN[p.status_provisionamento] ?? "pending",
  provisioning_error: p.erro_provisionamento,
  provisioning_started_at: p.provisioning_started_at ?? null,
  deleted_at: p.excluido_em,
  numero_ia: p.numero_ia ?? null,
  // Na lixeira o produto SOLTA o número (outro produto pode usar). Restaurado, volta sem número: precisa
  // escolher o canal e ativar de novo (mesma tela do editor). numero_liberado = o número que ele usava.
  precisa_ativar: !!p.precisa_ativar,
  numero_liberado: p.numero_liberado ?? null,
  channels: Array.isArray(p.canais) ? p.canais : [],
  rules_markdown: p.regras_markdown,
  faq_items: Array.isArray(p.faq) ? p.faq : [],
  objection_items: Array.isArray(p.objecoes) ? p.objecoes : [],
  knowledge_items: Array.isArray(p.conhecimento) ? p.conhecimento : [],
  integrations: p.integracoes ?? {},
  // Campos da nossa API usados pelo assistente no modo edição (comportamento real do agente e rascunho).
  dados_escritorio: p.dados_escritorio ?? null,
  honorarios_texto: p.honorarios_texto ?? null,
  rascunho: p.rascunho ?? null,
  agente: p.agente ?? null,
  id_canal: p.id_canal ?? null,
  source_template_id: p.id_produto_biblioteca,
  source_template_version: p.versao_template,
  // Atualização do catálogo disponível: o admin subiu a versão do produto acima da que o
  // cliente ativou (detecção por VERSÃO — decisão do usuário). Some quando o cliente aplica.
  atualizacao_disponivel: !!p.biblioteca && compararVersao(p.versao_template, p.biblioteca.versao) < 0,
  versao_catalogo: p.biblioteca?.versao ?? null,
  // Período de graça: o produto do catálogo OFERECE? / o cliente LIGOU nesta instância?
  periodo_graca_ativo: !!p.periodo_graca_ativo,
  oferece_periodo_graca: !!p.biblioteca?.oferece_periodo_graca,
  source_template: p.biblioteca
    ? {
        id: p.biblioteca.id,
        name: p.biblioteca.nome,
        icon: p.biblioteca.icone,
        cover_gradient: p.biblioteca.capa_gradiente,
        description_short: p.biblioteca.descricao_curta,
        category: p.biblioteca.categoria,
        version: p.biblioteca.versao,
        oferece_periodo_graca: !!p.biblioteca.oferece_periodo_graca,
        modo_midia: p.biblioteca.modo_midia ?? "texto",
      }
    : null,
  followup: Array.isArray(p.followup) ? p.followup[0] ?? null : p.followup ?? null,
  // Situação do follow-up do agente (docs/FOLLOWUP.md): ligado?, cadência resumida. null = ainda sem agente.
  followup_situacao: p.followup_situacao ?? null,
  agents: [],
  created_at: p.created_at,
  updated_at: p.updated_at,
});

/**
 * Lista de produtos com a mesma cópia guardada das telas (api.ts / cachePersistente.ts): abre na hora com a última
 * resposta (pré-carga da abertura ou abertura anterior) e confere com o servidor por trás (initialDataUpdatedAt 0 =
 * já nasce velha). A resposta do servidor também vai para a cópia.
 */
const listaDeProdutos = (caminho: string) => ({
  queryFn: async () => {
    const geracao = geracaoAtual();
    const data = await api<any[]>(caminho);
    guardarResposta(caminho, data, geracao);
    return ((data ?? []) as any[]).map(mapProdutoAtivado);
  },
  initialData: () => {
    const guardada = ultimaResposta<any[]>(caminho);
    return Array.isArray(guardada) ? guardada.map(mapProdutoAtivado) : undefined;
  },
  initialDataUpdatedAt: 0,
});

/** Lista os produtos ativados da conta (fora da lixeira) */
export const useMyProducts = () => {
  const { workspace } = useAuth();
  return useQuery({
    queryKey: ["my-products", workspace?.id],
    enabled: !!workspace?.id,
    ...listaDeProdutos("/produtos-ativados?lixeira=0"),
  });
};

/** Lista produtos na lixeira (até 30 dias após exclusão) */
export const useTrashedProducts = () => {
  const { workspace } = useAuth();
  return useQuery({
    queryKey: ["trashed-products", workspace?.id],
    enabled: !!workspace?.id,
    ...listaDeProdutos("/produtos-ativados?lixeira=1"),
  });
};

/** Carrega 1 Produto ativado (com etapas do agente Weaver, se vinculado) */
export const useProduct = (id: string | undefined) => {
  return useQuery({
    queryKey: ["product", id],
    enabled: !!id,
    queryFn: async () => {
      // A API devolve o produto + etapas do agente criado + valores {{ }} já aplicados.
      const produto = await api<any>(`/produtos-ativados/${id}`).catch((e) => {
        if (e?.status === 404) return null;
        throw e;
      });
      if (!produto) return null;
      const mapped = mapProdutoAtivado(produto);
      return { ...mapped, etapas: produto.etapas ?? [], variables: produto.variables ?? {} };
    },
  });
};

/** Re-envia o webhook de construção do produto quando o provisionamento ficou travado em "building". */
export const useRetryProductProvisioning = () => {
  const { workspace } = useAuth();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: { agent_group_id: string }) => {
      if (!workspace?.id) throw new Error("Workspace não encontrado");
      // Aqui a ativação é feita na hora pelo servidor: tentar de novo = reenviar o rascunho salvo.
      await enviar(`/produtos-ativados/${payload.agent_group_id}/ativar`, { reenviar: true });
      qc.invalidateQueries({ queryKey: ["my-products"] });
    },
  });
};
