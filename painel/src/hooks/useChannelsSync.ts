import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { api } from "@/api";

export interface ChannelItem {
  id: string;          // número (formatado) — identificador do canal
  channel_id: string;  // mesmo número (compat)
  label: string;
  tag: string;
  status: string;
  enabled: boolean;    // disponível para uso
  persisted: boolean;  // já está no cache
  /** id do canal no painel (agentesia_canais.id) */
  canal_id?: string;
}

/** Linha de GET /canais/disponiveis. */
export interface CanalDisponivel {
  id: string;
  numero: string;
  numero_formatado: string | null;
  nome: string | null;
  tipo: string | null;
  id_canal_helena: string | null;
  disponivel: boolean;
  em_uso_por: string | null;
}

/** Lista os números (canais) do escritório. */
export const listarCanaisDisponiveis = async (): Promise<CanalDisponivel[]> =>
  ((await api<CanalDisponivel[]>("/canais/disponiveis")) ?? []) as CanalDisponivel[];

/** Atualiza os canais a partir da Helena (token do escritório) e devolve a lista nova. */
export const sincronizarCanaisHelena = async (): Promise<CanalDisponivel[]> => {
  await api("/integracoes/helena/canais", { metodo: "POST" });
  return listarCanaisDisponiveis();
};

// Só canais de WhatsApp aparecem no seletor de canais do agente. A Helena sincroniza
// vários tipos (CLOUDAPI_WHATSAPP, ZAPI_WHATSAPP, INSTAGRAM, MESSENGER) — o agente é de
// WhatsApp, então Instagram/Messenger não devem aparecer na busca de canais.
// Aqui os canais já são só de WhatsApp: o tipo diz se é API oficial ("oficial") ou não ("nao_oficial").
export const ehWhatsapp = (n: any): boolean => {
  const tipo = String(n?.tipo ?? "").toLowerCase();
  return !tipo || tipo === "oficial" || tipo === "nao_oficial" || tipo.includes("whatsapp");
};

/**
 * Canais de WhatsApp do escritório. Fonte: GET /canais/disponiveis (cache dos canais da Helena);
 * "Sincronizar" = POST /integracoes/helena/canais e recarrega a lista.
 */
const mapNumero = (n: CanalDisponivel): ChannelItem => {
  const numero = String(n?.numero_formatado ?? n?.numero ?? "").trim();
  return {
    id: numero,
    channel_id: numero,
    label: String(n?.numero_formatado ?? n?.nome ?? numero),
    tag: n?.disponivel ? "Disponível" : "Em uso por agente",
    status: n?.disponivel ? "ativo" : "inativo",
    enabled: true,
    persisted: true,
    canal_id: n?.id,
  };
};

export const useChannelsSync = () => {
  const { workspace } = useAuth();
  const [channels, setChannels] = useState<ChannelItem[]>([]);
  const [pendingFromSync, setPendingFromSync] = useState<ChannelItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingPersisted, setLoadingPersisted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastSyncAt, setLastSyncAt] = useState<number | null>(null);

  const loadPersisted = useCallback(async () => {
    if (!workspace?.id) return [];
    setLoadingPersisted(true);
    try {
      const data = await listarCanaisDisponiveis().catch(() => [] as CanalDisponivel[]);
      const list = data.filter(ehWhatsapp)
        .sort((a, b) => Number(b.disponivel) - Number(a.disponivel) || String(a.numero).localeCompare(String(b.numero)))
        .map(mapNumero).filter((c) => c.channel_id);
      setChannels(list);
      return list;
    } finally {
      setLoadingPersisted(false);
    }
  }, [workspace?.id]);

  useEffect(() => {
    loadPersisted();
  }, [loadPersisted]);

  /** Sincroniza os números na Helena (com o token do escritório) e regrava o cache. */
  const fetchChannels = useCallback(async () => {
    if (!workspace?.id) return [];
    setLoading(true);
    setError(null);
    try {
      const nums = await sincronizarCanaisHelena();
      const annotated = nums.filter(ehWhatsapp).map(mapNumero).filter((c) => c.channel_id);
      setPendingFromSync(annotated);
      setLastSyncAt(Date.now());
      await loadPersisted();
      return annotated;
    } catch (e: any) {
      setError(e?.message ?? "Erro ao sincronizar");
      return [];
    } finally {
      setLoading(false);
    }
  }, [workspace?.id, loadPersisted]);

  /** No modelo novo os números já vivem no cache; confirmar apenas recarrega. */
  const confirmChannels = useCallback(
    async (_selectedChannelIds: string[]) => {
      setPendingFromSync([]);
      return await loadPersisted();
    },
    [loadPersisted],
  );

  const clearPending = useCallback(() => setPendingFromSync([]), []);

  return {
    channels,
    pendingFromSync,
    loading,
    loadingPersisted,
    error,
    fetchChannels,
    confirmChannels,
    clearPending,
    lastSyncAt,
    reload: loadPersisted,
  };
};
