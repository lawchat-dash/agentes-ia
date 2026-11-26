/**
 * Gating por plano. Aqui NÃO há planos: tudo é liberado. Mantém o mesmo formato do
 * agents-lawchat-main para as telas copiadas compilarem sem mudança.
 */
export interface PlanGate {
  myOrdem: number;
  myPlanName: string | null;
  /** true enquanto a query de plano ainda não retornou */
  isLoading: boolean;
  /** plano da conta cria agentes? */
  canCreateAgents: boolean;
  /** o plano da conta libera envio de áudio? */
  recursoAudio: boolean;
  /** ordem de um plano por slug (default 1) */
  rankOf: (slug?: string | null) => number;
  /** nome de exibição de um plano por slug */
  nameOf: (slug?: string | null) => string;
  /** true se a conta NÃO pode ativar este produto */
  isLocked: (planoMinimo?: string | null) => boolean;
  /** nome do plano que a conta precisa atingir para liberar o produto */
  neededPlan: (planoMinimo?: string | null) => string;
}

const LIBERADO: PlanGate = {
  myOrdem: Number.POSITIVE_INFINITY,
  myPlanName: null,
  isLoading: false,
  canCreateAgents: true,
  recursoAudio: true,
  rankOf: () => 1,
  nameOf: (slug) => slug ?? "",
  isLocked: () => false,
  neededPlan: (planoMinimo) => planoMinimo ?? "",
};

export const usePlanGate = (): PlanGate => LIBERADO;
