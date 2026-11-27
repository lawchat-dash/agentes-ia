import { useEffect, useRef, useState } from "react";
import {
  Loader2, Music, Image as ImageIcon, Video, UploadCloud, Trash2, Plus, Copy, Pencil, RefreshCw, Search, Mic, FolderOpen,
  Folder, ChevronRight, ArrowLeft,
} from "lucide-react";
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
import { conteudoDaPasta, descreverPasta, normalizarPasta, pastaDeCima, rotuloDaPasta, trilhaDaPasta } from "@/lib/pastasMidia";

/** Formata bytes em KB/MB legível. */
const fmtBytes = (b: number) => (!b ? "0 KB" : b >= 1024 * 1024 ? `${(b / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`);
/** Data de envio: dd/mm/aaaa às hh:mm. */
const fmtDate = (iso: string) => {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${d.toLocaleDateString("pt-BR")} às ${d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`;
};
const TYPE_LABEL: Record<string, string> = { audio: "Áudio", video: "Vídeo", image: "Imagem" };
const TYPE_BADGE: Record<string, string> = {
  audio: "bg-violet-500/10 text-violet-700 border-violet-500/20",
  video: "bg-blue-500/10 text-blue-700 border-blue-500/20",
  image: "bg-emerald-500/10 text-emerald-700 border-emerald-500/20",
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
  /** Pasta da biblioteca ("Roteiros gravados/Auxílio-Acidente"); null = solto na raiz. */
  pasta: string | null;
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
  pasta: normalizarPasta(d.pasta) || null,
  webhook_response: d.resposta_webhook,
} as MediaItem);

type Filtro = "todos" | MediaItem["type"];

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
  // Áudios que vieram de um roteiro (Ferramentas > Roteiros): id da mídia → título do roteiro.
  const [deRoteiro, setDeRoteiro] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [busca, setBusca] = useState("");
  const [filtro, setFiltro] = useState<Filtro>("todos");
  const [pasta, setPasta] = useState("");
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
    // Só um rótulo a mais: se os roteiros não estiverem disponíveis, a biblioteca segue igual.
    api<{ id_midia: string | null; titulo: string }[]>("/roteiros")
      .then((rs) => setDeRoteiro(Object.fromEntries((rs ?? []).filter((r) => r.id_midia).map((r) => [r.id_midia as string, r.titulo]))))
      .catch(() => setDeRoteiro({}));
  };

  useEffect(() => {
    if (open) {
      setBusca("");
      setPasta("");
      setFiltro(uploadOnly ?? "todos");
      fetchItems();
      if (uploadOnly && !autoTriggered.current) {
        autoTriggered.current = true;
        setTimeout(() => fileRef.current?.click(), 100);
      }
    } else {
      autoTriggered.current = false;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, workspace?.id, uploadOnly]);

  const usedBytes = cota?.usado ?? items.reduce((s, i) => s + (i.size_bytes ?? 0), 0);
  const limitBytes = cota?.limite ?? Math.max(1, armazenamentoMb) * 1024 * 1024;
  const freeBytes = Math.max(0, limitBytes - usedBytes);
  const usoPct = Math.min(100, Math.round((usedBytes / limitBytes) * 100));
  const quase = usoPct >= 90;
  const limiteMb = Math.round(limitBytes / 1024 / 1024);

  const handleFiles = async (files: FileList | null) => {
    if (!files || !workspace) return;
    setUploading(true);
    let running = usedBytes;          // controle de cota durante o lote
    let enviados = 0;
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
        enviados += 1;
        if (uploadOnly && onInsert) {
          onInsert(`\n[${type}:${file.name}](${pub.publicUrl})\n`);
          onOpenChange(false);
        }
      }
      if (enviados) toast.success(enviados > 1 ? `${enviados} arquivos enviados` : "Arquivo enviado");
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
    if (item.size_bytes && cota) setCota({ ...cota, usado: Math.max(0, cota.usado - item.size_bytes) });
    invalidarMidia();
    toast.success("Arquivo removido");
  };

  const base = items.filter((it) => !uploadOnly || it.type === uploadOnly);
  const contagem: Record<Filtro, number> = {
    todos: base.length,
    audio: base.filter((i) => i.type === "audio").length,
    video: base.filter((i) => i.type === "video").length,
    image: base.filter((i) => i.type === "image").length,
  };
  const termo = busca.trim().toLowerCase();
  const doTipo = base.filter((it) => filtro === "todos" || it.type === filtro);
  // Sem busca: pastas primeiro (clicar entra) e os arquivos da pasta aberta. Com busca: procura em tudo.
  const conteudo = conteudoDaPasta(doTipo, pasta, (it) => it.pasta, (it) => it.name, (it) => it.created_at);
  const pastasVisiveis = termo ? [] : conteudo.pastas;
  const visibleItems = termo
    ? doTipo.filter((it) => it.name.toLowerCase().includes(termo) || (deRoteiro[it.id] ?? "").toLowerCase().includes(termo)
      || (it.pasta ?? "").toLowerCase().includes(termo))
    : conteudo.arquivos;
  const trilha = trilhaDaPasta(pasta);
  const acceptAttr = uploadOnly === "audio" ? ".ogg,.oga,.opus,.mp3,.m4a" : uploadOnly === "video" ? ".mp4" : uploadOnly === "image" ? ".jpg,.jpeg,.png" : ".ogg,.oga,.opus,.mp3,.m4a,.mp4,.jpg,.jpeg,.png";
  const filtros: { chave: Filtro; rotulo: string }[] = uploadOnly
    ? [{ chave: uploadOnly, rotulo: TYPE_LABEL[uploadOnly] }]
    : [{ chave: "todos", rotulo: "Todos" }, { chave: "audio", rotulo: "Áudio" }, { chave: "video", rotulo: "Vídeo" }, { chave: "image", rotulo: "Imagem" }];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-w-[1000px] w-[94vw] max-h-[88vh] flex flex-col gap-0 p-0 overflow-hidden"
        onOpenAutoFocus={(e) => e.preventDefault()}
      >
        {/* Cabeçalho + espaço usado */}
        <DialogHeader className="space-y-0 px-6 pt-5 pb-4 text-left border-b border-border">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-3 pr-8">
            <div className="flex items-center gap-3 min-w-0 flex-1">
              <div className="size-10 rounded-xl grid place-items-center shrink-0 bg-primary/10 text-primary">
                <FolderOpen className="size-5" />
              </div>
              <div className="min-w-0">
                <DialogTitle className="text-lg font-bold leading-tight">{uploadOnly === "audio" ? "Adicionar áudio" : "Biblioteca de mídia"}</DialogTitle>
                <DialogDescription className="mt-0.5 text-[13px]">Áudios, vídeos e imagens para usar nos prompts dos agentes.</DialogDescription>
              </div>
            </div>
            <div className="w-full sm:w-[230px]" title={`${fmtBytes(freeBytes)} disponível`}>
              <div className="flex items-baseline justify-between text-[11.5px]">
                <span className="text-muted-foreground">Espaço{planName ? ` · ${planName}` : ""}</span>
                <span className={`tabular-nums font-semibold ${quase ? "text-amber-600" : "text-foreground"}`}>{fmtBytes(usedBytes)} de {limiteMb} MB</span>
              </div>
              <div className="mt-1.5 h-1.5 rounded-full bg-muted overflow-hidden">
                <div className="h-full rounded-full transition-all duration-500" style={{ width: `${Math.max(usoPct, usedBytes ? 2 : 0)}%`, background: quase ? "#f59e0b" : "hsl(var(--primary))" }} />
              </div>
            </div>
          </div>
        </DialogHeader>

        <input ref={fileRef} type="file" multiple accept={acceptAttr} className="hidden" onChange={(e) => handleFiles(e.target.files)} />

        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
          {/* Área de envio */}
          <div
            role="button"
            tabIndex={0}
            aria-label="Enviar arquivo: arraste e solte ou clique para escolher"
            onClick={() => !uploading && fileRef.current?.click()}
            onKeyDown={(e) => { if ((e.key === "Enter" || e.key === " ") && !uploading) { e.preventDefault(); fileRef.current?.click(); } }}
            onDragEnter={(e) => { e.preventDefault(); setDragActive(true); }}
            onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
            onDragLeave={(e) => { e.preventDefault(); setDragActive(false); }}
            onDrop={(e) => { e.preventDefault(); setDragActive(false); if (!uploading) handleFiles(e.dataTransfer.files); }}
            className={`group flex flex-col sm:flex-row items-center gap-4 rounded-xl border border-dashed px-5 py-4 cursor-pointer outline-none transition-colors focus-visible:ring-2 focus-visible:ring-primary/30 ${dragActive ? "border-primary bg-primary/5" : "border-slate-300 bg-slate-50/60 hover:border-primary/50 hover:bg-primary/[0.03]"} ${uploading ? "opacity-70 cursor-wait" : ""}`}
          >
            <div className="size-11 rounded-xl grid place-items-center shrink-0 bg-white border border-border text-primary shadow-sm">
              {uploading ? <Loader2 className="size-5 animate-spin" /> : <UploadCloud className="size-5" />}
            </div>
            <div className="flex-1 min-w-0 text-center sm:text-left">
              <div className="text-sm font-semibold text-foreground">
                {uploading ? "Enviando…" : dragActive ? "Solte para enviar" : <>Arraste arquivos aqui ou <span className="text-primary">escolha no computador</span></>}
              </div>
              <div className="text-xs text-muted-foreground mt-0.5">
                {uploadOnly === "audio"
                  ? "Áudio .ogg/.opus (chega como mensagem de voz), .mp3 ou .m4a · até 16 MB"
                  : "Áudio .ogg/.opus, .mp3, .m4a e vídeo .mp4 até 16 MB · imagem .jpg/.png até 5 MB"}
              </div>
            </div>
            <Button type="button" size="sm" className="shrink-0" disabled={uploading} onClick={(e) => { e.stopPropagation(); fileRef.current?.click(); }}>
              <Plus className="size-4 mr-1" />Enviar arquivo
            </Button>
          </div>

          {/* Busca e filtro */}
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative flex-1 min-w-[200px]">
              <Search className="size-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
              <Input value={busca} onChange={(e) => setBusca(e.target.value)} placeholder="Buscar pelo nome" className="pl-9 h-9" aria-label="Buscar mídia pelo nome" />
            </div>
            <div className="inline-flex rounded-lg border border-border bg-card p-0.5" role="tablist" aria-label="Filtrar por tipo">
              {filtros.map((f) => (
                <button key={f.chave} type="button" role="tab" aria-selected={filtro === f.chave} onClick={() => setFiltro(f.chave)}
                  className={`px-2.5 h-8 rounded-md text-xs font-semibold transition-colors ${filtro === f.chave ? "bg-primary/10 text-primary" : "text-muted-foreground hover:text-foreground"}`}>
                  {f.rotulo} <span className="tabular-nums opacity-70">{contagem[f.chave]}</span>
                </button>
              ))}
            </div>
            <Button onClick={handleSync} disabled={syncing || loading} variant="outline" size="sm" className="h-9" title="Atualizar a lista">
              {syncing ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
            </Button>
          </div>

          {/* Pasta aberta: voltar + trilha */}
          {pasta && !termo && (
            <nav className="flex flex-wrap items-center gap-1 text-[13px]" aria-label="Pastas">
              <button type="button" onClick={() => setPasta(pastaDeCima(pasta))}
                className="inline-flex items-center gap-1.5 h-8 px-2.5 mr-1 rounded-lg border border-[#E2E9E4] bg-white font-semibold text-[#00852A] hover:bg-[#E6F5EB]">
                <ArrowLeft className="size-3.5" />Voltar
              </button>
              <button type="button" onClick={() => setPasta("")} className="px-1.5 py-1 rounded-md font-semibold text-[#00852A] hover:bg-[#E6F5EB]">Biblioteca</button>
              {trilha.map((t, n) => (
                <span key={t.caminho} className="inline-flex items-center gap-1 min-w-0">
                  <ChevronRight className="size-3.5 text-[#69786F] shrink-0" aria-hidden />
                  {n === trilha.length - 1
                    ? <span className="px-1.5 py-1 font-semibold text-[#0C1811] truncate" aria-current="page">{t.nome}</span>
                    : <button type="button" onClick={() => setPasta(t.caminho)} className="px-1.5 py-1 rounded-md font-semibold text-[#00852A] hover:bg-[#E6F5EB]">{t.nome}</button>}
                </span>
              ))}
            </nav>
          )}

          {/* Pastas */}
          {pastasVisiveis.length > 0 && (
            <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
              {pastasVisiveis.map((p) => (
                <button key={p.caminho} type="button" onClick={() => setPasta(p.caminho)} aria-label={`Abrir a pasta ${p.nome}`}
                  className="group flex items-center gap-3 rounded-xl border border-[#E2E9E4] bg-card px-3.5 py-3 text-left transition-colors hover:border-[#00BC33] hover:bg-[#E6F5EB]/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00BC33]/30">
                  <span className="size-9 rounded-lg grid place-items-center shrink-0 bg-[#E6F5EB] text-[#00852A]"><Folder className="size-[18px]" /></span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-semibold text-[#0C1811] truncate" title={p.nome}>{p.nome}</span>
                    <span className="block text-[11.5px] text-[#69786F] truncate">{descreverPasta(p)}</span>
                  </span>
                  <ChevronRight className="size-4 shrink-0 text-[#69786F] group-hover:text-[#00852A]" />
                </button>
              ))}
            </div>
          )}

          {/* Arquivos */}
          {loading && items.length === 0 ? (
            <div className="grid place-items-center py-10"><Loader2 className="size-6 animate-spin text-primary" /></div>
          ) : visibleItems.length === 0 ? (pastasVisiveis.length > 0 ? null : (
            <div className="flex items-center justify-center gap-2.5 text-sm text-muted-foreground py-7 rounded-xl bg-muted/40">
              <FolderOpen className="size-4" />
              {base.length === 0 ? "Nenhum arquivo ainda. Envie o primeiro acima."
                : pasta && !termo ? (filtro === "todos" ? "Esta pasta está vazia." : "Nada com esse filtro nesta pasta.") : "Nada encontrado com esse filtro."}
            </div>
          )) : (
            <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
              {visibleItems.map((it) => {
                const Icon = TYPE_RULES[it.type].icon;
                const token = `\n[${it.type}:${it.name}](${it.url})\n`;
                const roteiro = deRoteiro[it.id];
                return (
                  <div key={it.id} className="flex flex-col rounded-xl border border-border bg-card overflow-hidden transition-shadow hover:shadow-[0_10px_28px_-18px_rgba(15,23,42,0.35)]">
                    {/* Prévia */}
                    {it.type === "image" ? (
                      <a href={it.url} target="_blank" rel="noreferrer" className="block h-32 bg-muted/50 border-b border-border">
                        <img src={it.url} alt={it.name} loading="lazy" className="size-full object-cover" />
                      </a>
                    ) : it.type === "video" ? (
                      <video src={it.url} controls preload="metadata" className="h-32 w-full bg-slate-900 object-contain border-b border-border" />
                    ) : (
                      <div className="px-3 pt-3">
                        <audio src={it.url} controls preload="none" className="w-full h-9" />
                      </div>
                    )}
                    <div className="p-3 flex flex-col gap-2 flex-1">
                      <div className="flex items-start gap-2 min-w-0">
                        <Icon className="size-4 mt-0.5 shrink-0 text-muted-foreground" />
                        <div className="min-w-0 flex-1">
                          <div className="text-sm font-semibold truncate" title={it.name}>{it.name}</div>
                          <div className="flex flex-wrap items-center gap-1.5 mt-1">
                            <span className={`text-[10px] font-bold uppercase tracking-wide px-1.5 py-px rounded border ${TYPE_BADGE[it.type]}`}>{TYPE_LABEL[it.type]}</span>
                            {roteiro && (
                              <span className="inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wide px-1.5 py-px rounded border bg-cyan-500/10 text-cyan-700 border-cyan-500/20" title={`Gravado no roteiro "${roteiro}"`}>
                                <Mic className="size-3" />Roteiro
                              </span>
                            )}
                            <span className="text-[11px] text-muted-foreground tabular-nums">{fmtBytes(it.size_bytes ?? 0)}</span>
                          </div>
                          <div className="text-[11px] text-muted-foreground mt-0.5">{fmtDate(it.created_at)}</div>
                          {termo && it.pasta && (
                            <button type="button" onClick={() => { setPasta(it.pasta ?? ""); setBusca(""); }} title="Abrir esta pasta"
                              className="mt-1 inline-flex max-w-full items-center gap-1 text-[11px] font-medium text-[#00852A] hover:underline">
                              <Folder className="size-3 shrink-0" /><span className="truncate">{rotuloDaPasta(it.pasta)}</span>
                            </button>
                          )}
                        </div>
                      </div>
                      <div className="mt-auto flex items-center gap-1 pt-1">
                        {onInsert && (
                          <Button size="sm" className="h-8 rounded-lg font-semibold mr-auto"
                            onClick={() => { onInsert(token); onOpenChange(false); toast.success("Mídia inserida no prompt"); }}>
                            <Plus className="size-3.5 mr-1" />Inserir
                          </Button>
                        )}
                        <div className={`flex items-center gap-0.5 ${onInsert ? "" : "ml-auto"}`}>
                          <Button size="icon" variant="ghost" className="size-8 rounded-lg text-muted-foreground hover:text-primary hover:bg-primary/10" title="Renomear" aria-label={`Renomear ${it.name}`} onClick={() => { setRenameItem(it); setNovoNome(it.name); }}>
                            <Pencil className="size-3.5" />
                          </Button>
                          <Button size="icon" variant="ghost" className="size-8 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted" title="Copiar referência para o prompt" aria-label={`Copiar referência de ${it.name}`} onClick={() => { navigator.clipboard.writeText(token.trim()); toast.success("Referência copiada"); }}>
                            <Copy className="size-3.5" />
                          </Button>
                          <Button size="icon" variant="ghost" className="size-8 rounded-lg text-muted-foreground hover:text-destructive hover:bg-destructive/10" title="Excluir" aria-label={`Excluir ${it.name}`} onClick={() => setConfirmItem(it)}>
                            <Trash2 className="size-3.5" />
                          </Button>
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Rodapé */}
        <div className="flex items-center gap-3 px-6 py-3.5 border-t border-border bg-muted/30">
          <span className="text-xs text-muted-foreground flex-1">
            {onInsert
              ? <>Clique em <strong className="text-foreground">Inserir</strong> para colar a mídia no prompt, na posição do cursor.</>
              : <>Para usar no prompt, abra o editor do agente e insira pela biblioteca, ou copie a referência.</>}
          </span>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Fechar</Button>
        </div>
      </DialogContent>

      <Dialog open={!!confirmItem} onOpenChange={(v) => !v && !deleting && setConfirmItem(null)}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Excluir este arquivo?</DialogTitle>
            {confirmItem && (
              <DialogDescription className="mt-1 break-all rounded-md bg-muted/60 px-2 py-1.5 font-mono text-xs">{confirmItem.name}</DialogDescription>
            )}
          </DialogHeader>
          {confirmItem && deRoteiro[confirmItem.id] && (
            <p className="text-xs text-muted-foreground">O roteiro "{deRoteiro[confirmItem.id]}" volta para "a gravar".</p>
          )}
          <DialogFooter className="gap-2 sm:gap-2">
            <Button variant="secondary" disabled={deleting} onClick={() => setConfirmItem(null)}>
              Cancelar
            </Button>
            <Button
              disabled={deleting}
              variant="destructive"
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
              Excluir
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
