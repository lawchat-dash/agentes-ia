import { useQuery } from "@tanstack/react-query";
import { api } from "@/api";
import { useAuth } from "@/contexts/AuthContext";

/** Item da Biblioteca de Mídia (sistemaia_biblioteca_midia) no shape da UI. */
export interface MidiaItem {
  id: string;
  name: string;
  type: "audio" | "video" | "image";
  url: string;
  size_bytes: number | null;
  created_at: string;
}

const TIPO_DB_TO_UI: Record<string, MidiaItem["type"]> = {
  audio: "audio", video: "video", imagem: "image", documento: "image",
};

/** queryKey compartilhada — invalidar no upload/rename/excluir para sincronizar o submenu @. */
export const bibliotecaMidiaKey = (workspaceId?: string) => ["biblioteca-midia", workspaceId] as const;

/**
 * Fonte ÚNICA da Biblioteca de Mídia (popup, manager e o submenu @ do prompt).
 * Lê GET /midia do escritório, via React Query.
 */
export function useBibliotecaMidia() {
  const { workspace } = useAuth();
  const query = useQuery({
    queryKey: bibliotecaMidiaKey(workspace?.id),
    enabled: !!workspace?.id,
    staleTime: 30_000,
    queryFn: async () => {
      const resposta = await api<{ itens: any[] }>("/midia");
      const data = (Array.isArray(resposta?.itens) ? resposta.itens : [])
        .slice().sort((a: any, b: any) => String(b.created_at ?? "").localeCompare(String(a.created_at ?? "")));
      return (data as any[]).map((d): MidiaItem => ({
        id: d.id,
        name: d.nome,
        type: TIPO_DB_TO_UI[d.tipo] ?? "image",
        url: d.url,
        size_bytes: d.tamanho_bytes ?? null,
        created_at: d.created_at,
      }));
    },
  });

  const items = query.data ?? [];
  /** Só os áudios, no shape leve do submenu @. */
  const audios = items
    .filter((i) => i.type === "audio")
    .map((i) => ({ id: i.id, name: i.name, url: i.url }));

  return { ...query, items, audios };
}
