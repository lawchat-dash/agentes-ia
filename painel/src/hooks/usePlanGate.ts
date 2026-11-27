/**
 * Liberação por plano (mesma regra do Weaver e do servidor, app/cobranca.motivo_bloqueio_produto):
 * - conta sem plano gravado = legado: tudo liberado;
 * - plano que não cria agentes bloqueia todos os produtos;
 * - produto com plano mínimo X só libera para plano de ordem >= a de X (código desconhecido ou vazio não trava).
 * A tela só mostra; quem barra de verdade é o servidor (rascunho e primeira ativação).
 */
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api";

export interface PlanGate {
  myOrdem: number;
  myPlanName: string | null;
  /** true enquanto a query de plano ainda não retornou */
  isLoading: boolean;
  /** plano da conta cria agentes? */
  canCreateAgents: boolean;
  /** o plano da conta libera envio de áudio? (sem regra de áudio por enquanto: sempre true) */
  recursoAudio: boolean;
  /** ordem de um plano por código (sem plano conhecido = 0, não trava) */
  rankOf: (slug?: string | null) => number;
  /** nome de exibição de um plano por código */
  nameOf: (slug?: string | null) => string;
  /** true se a conta NÃO pode ativar este produto */
  isLocked: (planoMinimo?: string | null) => boolean;
  /** nome do plano que a conta precisa atingir para liberar o produto */
  neededPlan: (planoMinimo?: string | null) => string;
}

interface RespostaPlano {
  plano: { codigo: string; nome: string; ordem: number; cria_agentes: boolean } | null;
  planos: { codigo: string; nome: string; ordem: number }[];
}

export const usePlanGate = (): PlanGate => {
  const { data, isLoading } = useQuery({
    queryKey: ["plano-da-conta"],
    queryFn: () => api<RespostaPlano>("/plano"),
    staleTime: 60_000,
  });
  const plano = data?.plano ?? null;
  const planos = data?.planos ?? [];
  const achar = (slug?: string | null) => (slug ? planos.find((p) => p.codigo === slug) : undefined);
  // Ainda carregando ou conta sem plano: libera (o servidor confere de novo na ativação).
  if (!plano) {
    return {
      myOrdem: Number.POSITIVE_INFINITY, myPlanName: null, isLoading, canCreateAgents: true, recursoAudio: true,
      rankOf: (slug) => achar(slug)?.ordem ?? 0, nameOf: (slug) => achar(slug)?.nome ?? slug ?? "",
      isLocked: () => false, neededPlan: (slug) => achar(slug)?.nome ?? slug ?? "",
    };
  }
  const rankOf = (slug?: string | null) => achar(slug)?.ordem ?? 0;
  // Sem criar agentes, o próximo plano que cria é o "necessário" (o Weaver mostra "Disponível no plano Prata").
  const primeiroQueCria = planos.find((p) => p.ordem > plano.ordem);
  return {
    myOrdem: plano.ordem, myPlanName: plano.nome, isLoading, canCreateAgents: plano.cria_agentes, recursoAudio: true,
    rankOf, nameOf: (slug) => achar(slug)?.nome ?? slug ?? "",
    isLocked: (minimo) => !plano.cria_agentes || rankOf(minimo) > plano.ordem,
    neededPlan: (minimo) => {
      const alvo = achar(minimo);
      if (alvo && alvo.ordem > plano.ordem) return alvo.nome;
      return primeiroQueCria?.nome ?? alvo?.nome ?? "superior";
    },
  };
};
