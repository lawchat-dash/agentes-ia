export type PlanFeature = "audio" | "midia" | "documentos";

/**
 * Recursos liberados pelo plano. Aqui NÃO há planos: tudo liberado. Mantém o formato do
 * agents-lawchat-main para as telas copiadas compilarem sem mudança.
 */
export const usePlanFeatures = () => {
  const has = (_feature: PlanFeature) => true;
  return {
    planSlug: null as string | null,
    planName: null as string | null,
    /** Cota de armazenamento da biblioteca de mídia em MB (limite do servidor: 200 MB). */
    armazenamentoMb: 200,
    has,
    audio: true,
    midia: true,
    documentos: true,
  };
};
