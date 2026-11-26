import { useEffect, useRef, useState } from "react";
import { Loader2, Music, Image as ImageIcon, Video, UploadCloud, Trash2, Plus, Copy, Pencil, RefreshCw, ShieldCheck, Lightbulb } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { api, enviar } from "@/api";
import { arquivoParaBase64 } from "@/lib/base64";
import { useAuth } from "@/contexts/AuthContext";
import { useQueryClient } from "@tanstack/react-query";
import { bibliotecaMidiaKey } from "@/hooks/useBibliotecaMidia";
import { usePlanFeatures } from "@/hooks/usePlanFeatures";
import { toast } from "sonner";

/** Formata bytes em KB/MB legível. */
const fmtBytes = (b: number) => (b >= 1024 * 1024 ? `${(b / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`);
/** Data de envio: dd/mm/aaaa às hh:mm. */
const fmtDate = (iso: string) => {
  const d = new Date(iso);
  return `${d.toLocaleDateString("pt-BR")} às ${d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`;
};
const TYPE_LABEL: Record<string, string> = { audio: "ÁUDIO", video: "VÍDEO", image: "IMAGEM" };
const TYPE_BADGE: Record<string, string> = {
  audio: "bg-violet-500/12 text-violet-600 border-violet-500/25",
  video: "bg-blue-500/12 text-blue-600 border-blue-500/25",
  image: "bg-emerald-500/12 text-emerald-600 border-emerald-500/25",
};

export interface MediaItem {
  id: string;
  workspace_id: string;
  name: string;
  type: "audio" | "video" | "image";
  url: string;
  storage_path: string | null;
  mime_type: string | null;
  size_bytes: number | null;
  created_at: string;
}

const TYPE_RULES: Record<MediaItem["type"], { ext: string; mime: string; icon: any }> = {
  audio: { ext: ".ogg", mime: "audio/ogg", icon: Music },
  video: { ext: ".mp4", mime: "video/mp4", icon: Video },
  image: { ext: ".jpg", mime: "image/jpeg", icon: ImageIcon },
};

/** Biblioteca de mídia do escritório (API /midia). Compartilhada com /ferramentas. */
const TIPO_DB_TO_UI: Record<string, MediaItem["type"]> = { audio: "audio", video: "video", imagem: "image", documento: "image" };

/** Linha do banco (pt) → MediaItem da UI. */
const rowToItem = (d: any): MediaItem => ({
  id: d.id,
  workspace_id: d.id_conta,
  name: d.nome,
  type: TIPO_DB_TO_UI[d.tipo] ?? "image",
  url: d.url,
  storage_path: d.caminho_storage ?? null,
  mime_type: d.mime_type ?? null,
  size_bytes: d.tamanho_bytes ?? null,
  created_at: d.created_at,
  webhook_response: d.resposta_webhook,
} as MediaItem);

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  /** Optional webhook URL to notify after upload */
  webhookUrl?: string;
  /** Called when user selects an item to insert into the prompt. */
  onInsert?: (token: string) => void;
  /** When set, the library auto-triggers the file picker for that type and inserts after upload. */
  uploadOnly?: MediaItem["type"];
}

export const MediaLibrary = ({ open, onOpenChange, webhookUrl, onInsert, uploadOnly }: Props) => {
  const { workspace } = useAuth();
  const { armazenamentoMb, planName } = usePlanFeatures();
  const qc = useQueryClient();
  /** Sincroniza o submenu @ (useBibliotecaMidia) após mudar a biblioteca. */
  const invalidarMidia = () => { if (workspace) qc.invalidateQueries({ queryKey: bibliotecaMidiaKey(workspace.id) }); };
  const [items, setItems] = useState<MediaItem[]>([]);
  // Cota informada pelo servidor (GET /midia → usado_bytes / limite_bytes).
  const [cota, setCota] = useState<{ usado: number; limite: number } | null>(null);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const autoTriggered = useRef(false);

  const fetchItems = async () => {
    if (!workspace) return;
    setLoading(true);
    try {
      const data = await api<{ itens: any[]; usado_bytes: number; limite_bytes: number }>("/midia");
      const lista = (Array.isArray(data?.itens) ? data.itens : [])
        .slice().sort((a: any, b: any) => String(b.created_at ?? "").localeCompare(String(a.created_at ?? "")));
      setItems(lista.map(rowToItem));
      if (typeof data?.limite_bytes === "number") setCota({ usado: Number(data.usado_bytes ?? 0), limite: data.limite_bytes });
    } catch (e: any) {
      toast.error("Erro ao carregar biblioteca", { description: e?.message });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) {
      fetchItems();
      if (uploadOnly && !autoTriggered.current) {
        autoTriggered.current = true;
        setTimeout(() => fileRef.current?.click(), 100);
      }
    } else {
      autoTriggered.current = false;
    }
  }, [open, workspace?.id, uploadOnly]);

  const handleFiles = async (files: FileList | null) => {
    if (!files || !workspace) return;
    setUploading(true);
    let running = usedBytes;          // controle de cota durante o lote
    try {
      for (const file of Array.from(files)) {
        const ext = file.name.toLowerCase().split(".").pop() ?? "";
        let type: MediaItem["type"] | null = null;
        // Só o que o WhatsApp entrega como mídia (o servidor confere de novo): voz em OGG/OPUS, MP3/M4A, vídeo MP4, JPG/PNG.
        if (["ogg", "oga", "opus", "mp3", "m4a"].includes(ext)) type = "audio";
        else if (["mp4"].includes(ext)) type = "video";
        else if (["jpg", "jpeg", "png"].includes(ext)) type = "image";
        if (!type) {
          toast.error(`Formato não permitido: ${file.name}`, {
            description: "Use áudio .ogg/.opus (chega como mensagem de voz), .mp3 ou .m4a, vídeo .mp4 ou imagem .jpg/.png.",
          });
          continue;
        }
        const limite = type === "image" ? 5 : 16;          // MB, limites do WhatsApp
        if (file.size > limite * 1024 * 1024) {
          toast.error("Arquivo muito grande", { description: `Máximo para ${type === "image" ? "imagem" : type === "video" ? "vídeo" : "áudio"}: ${limite} MB.` });
          continue;
        }
        if (running + file.size > limitBytes) {
          toast.error("Limite de armazenamento atingido", {
            description: `"${file.name}" não cabe no espaço restante (${fmtBytes(Math.max(0, limitBytes - running))}).`,
          });
          continue;
        }

        // O servidor guarda o arquivo (organizado por escritório/tipo) e devolve a URL pública.
        const finalMime = file.type || TYPE_RULES[type].mime;
        let criado: any = null;
        try {
          criado = await enviar("/midia", { nome: file.name, conteudo_base64: await arquivoParaBase64(file), mime: finalMime });
        } catch (e: any) {
          toast.error(`Falha no upload de ${file.name}`, { description: e?.message });
          continue;
        }
        const pub = { publicUrl: String(criado?.url ?? "") };

        // Webhook opcional (se a tela passar webhookUrl) — apenas notificação
        if (webhookUrl) {
          try {
            await fetch(webhookUrl, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                event: "media.uploaded", workspace_id: workspace.id,
                file: { name: file.name, type, size: file.size, url: pub.publicUrl },
              }),
            });
          } catch {/* ignore */}
        }

        running += file.size;
        if (uploadOnly && onInsert) {
          onInsert(`\n[${type}:${file.name}](${pub.publicUrl})\n`);
          onOpenChange(false);
        }
      }
      toast.success("Upload concluído");
      await fetchItems();
      invalidarMidia();
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const [confirmItem, setConfirmItem] = useState<MediaItem | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [renameItem, setRenameItem] = useState<MediaItem | null>(null);
  const [novoNome, setNovoNome] = useState("");
  const [renaming, setRenaming] = useState(false);
  const [syncing, setSyncing] = useState(false);

  const handleSync = async () => {
    setSyncing(true);
    try {
      await fetchItems();
      toast.success("Lista atualizada");
    } finally {
      setSyncing(false);
    }
  };

  // Renomear = apenas o rótulo no banco (storage/URL não mudam).
  const rename = async (item: MediaItem, novo_nome: string) => {
    try {
      await enviar(`/midia/${item.id}`, { nome: novo_nome }, "PATCH");
    } catch (e: any) { toast.error("Falha ao renomear", { description: e?.message }); return false; }
    setItems((p) => p.map((i) => (i.id === item.id ? { ...i, name: novo_nome } : i)));
    invalidarMidia();
    toast.success("Arquivo renomeado");
    return true;
  };

  // Excluir = remove do storage e do banco.
  const remove = async (item: MediaItem) => {
    try {
      await api(`/midia/${item.id}`, { metodo: "DELETE" });
    } catch (e: any) { toast.error("Erro ao excluir", { description: e?.message }); return; }
    setItems((p) => p.filter((i) => i.id !== item.id));
    invalidarMidia();
    toast.success("Arquivo removido");
  };

  const visibleItems = items.filter((it) => !uploadOnly || it.type === uploadOnly);
  const usedBytes = cota?.usado ?? items.reduce((s, i) => s + (i.size_bytes ?? 0), 0);
  const limitBytes = cota?.limite ?? Math.max(1, armazenamentoMb) * 1024 * 1024;
  const freeBytes = Math.max(0, limitBytes - usedBytes);
  const usoPct = Math.min(100, Math.round((usedBytes / limitBytes) * 100));
  const quase = usoPct >= 90;
  const acceptAttr = uploadOnly === "audio" ? ".ogg,.oga,.opus,.mp3,.m4a" : uploadOnly === "video" ? ".mp4" : uploadOnly === "image" ? ".jpg,.jpeg,.png" : ".ogg,.oga,.opus,.mp3,.m4a,.mp4,.jpg,.jpeg,.png";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[1080px] w-[94vw] max-h-[88vh] flex flex-col gap-0 p-0 overflow-hidden">
        {/* Cabeçalho */}
        <DialogHeader className="space-y-0 p-6 pb-4 text-left">
          <div className="flex items-center gap-3.5">
            <div className="size-12 rounded-2xl grid place-items-center shrink-0 text-primary shadow-[0_12px_28px_-12px_hsl(var(--primary)/0.5)]" style={{ background: "linear-gradient(135deg, hsl(var(--primary)/0.18), hsl(var(--primary)/0.06))" }}>
              <ImageIcon className="size-6" />
            </div>
            <div className="min-w-0">
              <DialogTitle className="text-lg font-bold leading-tight">{uploadOnly === "audio" ? "Adicionar áudio" : "Biblioteca de mídia"}</DialogTitle>
              <DialogDescription className="mt-0.5">Gerencie arquivos de áudio, vídeo e imagem para usar nos prompts.</DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <input ref={fileRef} type="file" multiple accept={acceptAttr} className="hidden" onChange={(e) => handleFiles(e.target.files)} />

        <div className="flex-1 overflow-y-auto px-6 pb-4 space-y-5">
          {/* Upload + armazenamento */}
          <div className="grid lg:grid-cols-[minmax(0,1fr)_340px] gap-4">
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              onDragEnter={(e) => { e.preventDefault(); setDragActive(true); }}
              onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
              onDragLeave={(e) => { e.preventDefault(); setDragActive(false); }}
              onDrop={(e) => { e.preventDefault(); setDragActive(false); handleFiles(e.dataTransfer.files); }}
              disabled={uploading}
              className={`group rounded-2xl border-[1.5px] border-dashed transition-all grid place-items-center text-center px-6 py-7 min-h-[176px] disabled:opacity-70 ${dragActive ? "border-primary bg-primary/10 scale-[1.01]" : "border-border hover:border-primary/60"}`}
              style={dragActive ? undefined : { background: "radial-gradient(circle at center, hsl(var(--primary)/0.05), transparent 55%)" }}
            >
              <div>
                <div className={`size-12 rounded-2xl grid place-items-center mx-auto mb-2.5 text-primary transition-transform ${dragActive ? "bg-primary/20 scale-110" : "bg-primary/10 group-hover:scale-105"}`}>
                  {uploading ? <Loader2 className="size-6 animate-spin" /> : <UploadCloud className="size-6" />}
                </div>
                <div className="text-sm font-bold text-foreground">{uploading ? "Enviando…" : dragActive ? "Solte para enviar" : "Adicionar arquivo"}</div>
                <div className="text-xs text-muted-foreground mt-1">Arraste e solte ou <span className="text-primary font-semibold group-hover:underline">clique para selecionar</span></div>
                <div className="mt-3 inline-flex items-center rounded-lg border border-border bg-muted/40 px-2.5 py-1 text-[11px] font-medium text-muted-foreground">
                  {uploadOnly === "audio" ? "OGG/OPUS (voz), MP3, M4A" : "Áudio, vídeo MP4, imagem JPG/PNG"} · máx. 16 MB (imagem 5 MB)
                </div>
              </div>
            </button>

            <div className="rounded-2xl border border-border bg-card p-4 flex flex-col">
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0">
                  <div className="size-8 rounded-lg bg-primary/10 grid place-items-center shrink-0 text-primary"><ShieldCheck className="size-4" /></div>
                  <div className="min-w-0">
                    <div className="text-sm font-semibold leading-tight">Permitido</div>
                    <div className="text-xs text-muted-foreground truncate">áudio, vídeo, imagem</div>
                  </div>
                </div>
                <Button onClick={handleSync} disabled={syncing} variant="outline" size="sm" className="shrink-0">
                  {syncing ? <Loader2 className="size-3.5 mr-1.5 animate-spin" /> : <RefreshCw className="size-3.5 mr-1.5" />}Atualizar
                </Button>
              </div>

              <div className="mt-3.5 grid grid-cols-2 gap-3">
                <div>
                  <div className="text-[11px] text-muted-foreground">Máximo por arquivo</div>
                  <div className="text-sm font-bold">16 MB</div>
                </div>
                <div>
                  <div className="text-[11px] text-muted-foreground truncate">Armazenamento{planName ? ` · ${planName}` : ""}</div>
                  <div className="text-sm font-bold">{fmtBytes(usedBytes)} <span className="text-muted-foreground font-medium">de {armazenamentoMb} MB</span></div>
                </div>
              </div>
              <div className="mt-2.5 h-2 rounded-full bg-muted overflow-hidden">
                <div className="h-full rounded-full transition-all duration-500" style={{ width: `${usoPct}%`, background: quase ? "linear-gradient(90deg,#f59e0b,#ef4444)" : "linear-gradient(90deg, #22c55e, hsl(var(--primary)))" }} />
              </div>
              <div className="mt-1.5 flex items-center justify-between text-[11px]">
                <span className={quase ? "font-semibold text-amber-600" : "text-muted-foreground"}>{fmtBytes(freeBytes)} disponível</span>
                <span className="text-muted-foreground tabular-nums">{usoPct}% usado</span>
              </div>
            </div>
          </div>

          {/* Lista de arquivos */}
          {loading ? (
            <div className="grid place-items-center py-12"><Loader2 className="size-6 animate-spin text-primary" /></div>
          ) : visibleItems.length === 0 ? (
            <div className="text-center text-sm text-muted-foreground py-12 border border-dashed rounded-2xl">
              Nenhum arquivo na biblioteca ainda. Faça upload acima e ele aparece aqui.
            </div>
          ) : (
            <div>
              <div className="text-sm font-bold mb-2.5">Arquivos adicionados ({visibleItems.length})</div>
              <div className="space-y-2">
                {visibleItems.map((it) => {
                  const Icon = TYPE_RULES[it.type].icon;
                  const token = `\n[${it.type}:${it.name}](${it.url})\n`;
                  return (
                    <div key={it.id} className="flex items-center gap-3 p-3 rounded-2xl border border-border bg-card transition-all hover:-translate-y-0.5 hover:shadow-[0_16px_36px_-20px_rgba(15,23,42,0.25)]">
                      <div className="size-14 rounded-xl overflow-hidden shrink-0 grid place-items-center bg-primary/10 text-primary border border-border">
                        {it.type === "image" ? <img src={it.url} alt="" loading="lazy" className="size-full object-cover" /> : <Icon className="size-6" />}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-semibold truncate">{it.name}</div>
                        <div className="flex items-center gap-2 mt-1">
                          <span className={`text-[10px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded-md border ${TYPE_BADGE[it.type]}`}>{TYPE_LABEL[it.type]}</span>
                          <span className="text-[11px] text-muted-foreground">{fmtBytes(it.size_bytes ?? 0)}</span>
                        </div>
                        <div className="text-[11px] text-muted-foreground mt-0.5">Enviado em {fmtDate(it.created_at)}</div>
                      </div>
                      {onInsert && (
                        <Button
                          className="bg-gradient-primary text-white shrink-0 rounded-xl font-semibold shadow-[0_8px_20px_-8px_hsl(var(--primary)/0.6)] hover:shadow-[0_12px_26px_-8px_hsl(var(--primary)/0.7)] hover:-translate-y-0.5 transition-all"
                          onClick={() => { onInsert(token); onOpenChange(false); toast.success("Mídia inserida no prompt"); }}
                        >
                          <Plus className="size-4 mr-1" />Inserir
                        </Button>
                      )}
                      <div className="flex items-center gap-1 shrink-0">
                        <Button size="icon" variant="ghost" className="size-9 rounded-lg text-muted-foreground hover:text-primary hover:bg-primary/10" title="Renomear arquivo" onClick={() => { setRenameItem(it); setNovoNome(it.name); }}>
                          <Pencil className="size-4" />
                        </Button>
                        <Button size="icon" variant="ghost" className="size-9 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted" title="Copiar referência" onClick={() => { navigator.clipboard.writeText(token.trim()); toast.success("Referência copiada"); }}>
                          <Copy className="size-4" />
                        </Button>
                        <Button size="icon" variant="ghost" className="size-9 rounded-lg text-muted-foreground hover:text-destructive hover:bg-destructive/10" title="Excluir" onClick={() => setConfirmItem(it)}>
                          <Trash2 className="size-4" />
                        </Button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Dica */}
          <div className="rounded-xl border border-primary/20 bg-primary/5 px-4 py-2.5 text-xs text-muted-foreground flex items-center gap-2">
            <Lightbulb className="size-4 text-primary shrink-0" />
            <span>Clique em <strong className="text-foreground">Inserir</strong> para colar a mídia no prompt na posição do cursor.</span>
          </div>
        </div>

        {/* Rodapé */}
        <div className="flex justify-end gap-2 px-6 py-4 border-t border-border">
          <Button variant="outline" onClick={() => onOpenChange(false)}>Fechar</Button>
        </div>
      </DialogContent>

      <Dialog open={!!confirmItem} onOpenChange={(v) => !v && !deleting && setConfirmItem(null)}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Você deseja excluir esse arquivo?</DialogTitle>
            {confirmItem && (
              <DialogDescription className="mt-1 break-all rounded-md bg-muted/60 px-2 py-1.5 font-mono text-xs">{confirmItem.name}</DialogDescription>
            )}
          </DialogHeader>
          <DialogFooter className="gap-2 sm:gap-2">
            <Button variant="secondary" disabled={deleting} onClick={() => setConfirmItem(null)}>
              Cancelar
            </Button>
            <Button
              disabled={deleting}
              className="bg-primary text-primary-foreground hover:bg-destructive hover:text-primary-foreground"
              onClick={async () => {
                if (!confirmItem) return;
                setDeleting(true);
                try {
                  await remove(confirmItem);
                } finally {
                  setDeleting(false);
                  setConfirmItem(null);
                }
              }}
            >
              {deleting ? <Loader2 className="size-4 mr-1.5 animate-spin" /> : null}
              Deletar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!renameItem} onOpenChange={(v) => !v && !renaming && setRenameItem(null)}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Renomear arquivo</DialogTitle>
            {renameItem && (
              <DialogDescription className="break-all">Atual: {renameItem.name}</DialogDescription>
            )}
          </DialogHeader>
          <Input
            value={novoNome}
            onChange={(e) => setNovoNome(e.target.value)}
            placeholder="Novo nome do arquivo"
            disabled={renaming}
          />
          <DialogFooter className="gap-2 sm:gap-2">
            <Button variant="secondary" disabled={renaming} onClick={() => setRenameItem(null)}>
              Cancelar
            </Button>
            <Button
              disabled={renaming || !novoNome.trim() || novoNome === renameItem?.name}
              onClick={async () => {
                if (!renameItem) return;
                setRenaming(true);
                try {
                  const ok = await rename(renameItem, novoNome.trim());
                  if (ok) setRenameItem(null);
                } finally {
                  setRenaming(false);
                }
              }}
            >
              {renaming ? <Loader2 className="size-4 mr-1.5 animate-spin" /> : null}
              Salvar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Dialog>
  );
};
