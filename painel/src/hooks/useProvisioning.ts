import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/contexts/AuthContext";

/**
 * No agents-lawchat-main isto assinava o realtime do Supabase em sistemaia_produtos_ativados.
 * Aqui a ativação é síncrona (POST /produtos-ativados/{id}/ativar responde com o agente pronto),
 * então basta revalidar as listas de vez em quando enquanto a tela está aberta.
 */
export const useProvisioningRealtime = () => {
  const { workspace } = useAuth();
  const qc = useQueryClient();

  useEffect(() => {
    if (!workspace?.id) return;
    const atualizar = () => {
      qc.invalidateQueries({ queryKey: ["my-products"] });
      qc.invalidateQueries({ queryKey: ["product"] });
      qc.invalidateQueries({ queryKey: ["followup-products"] });
      qc.invalidateQueries({ queryKey: ["followup"] });
    };
    const iv = setInterval(() => { if (document.visibilityState === "visible") atualizar(); }, 30_000);
    const aoVoltar = () => { if (document.visibilityState === "visible") atualizar(); };
    document.addEventListener("visibilitychange", aoVoltar);
    return () => {
      clearInterval(iv);
      document.removeEventListener("visibilitychange", aoVoltar);
    };
  }, [workspace?.id, qc]);
};
