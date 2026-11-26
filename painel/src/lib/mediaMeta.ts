/**
 * Overlay de metadados da Biblioteca de Mídia (favoritos, tags, produto atrelado,
 * transcrição) persistido em localStorage por workspace.
 *
 * ⚠️ TEMPORÁRIO / FRONTEND-FIRST: enquanto o backend não existe, guardamos esses
 * campos no navegador. Quando as colunas `tags`, `product_id`, `is_favorite`,
 * `transcription`, `transcription_status` existirem em `media_library`, basta trocar
 * leitura/escrita daqui por chamadas ao Supabase (mesma forma de objeto).
 */

export type TranscriptionStatus = "none" | "processing" | "done" | "error";

export interface MediaMeta {
  favorite: boolean;
  tags: string[];
  productId: string | null;
  transcription: string | null;
  transcriptionStatus: TranscriptionStatus;
}

export const EMPTY_META: MediaMeta = {
  favorite: false,
  tags: [],
  productId: null,
  transcription: null,
  transcriptionStatus: "none",
};

type Store = Record<string, MediaMeta>;

const keyFor = (workspaceId: string) => `lawchat:media-meta:${workspaceId}`;

export const loadMediaMeta = (workspaceId: string): Store => {
  try {
    const raw = localStorage.getItem(keyFor(workspaceId));
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? (parsed as Store) : {};
  } catch {
    return {};
  }
};

export const saveMediaMeta = (workspaceId: string, store: Store) => {
  try {
    localStorage.setItem(keyFor(workspaceId), JSON.stringify(store));
  } catch {
    /* quota / modo privado — ignora */
  }
};

export const getMeta = (store: Store, id: string): MediaMeta => ({
  ...EMPTY_META,
  ...(store[id] ?? {}),
});
