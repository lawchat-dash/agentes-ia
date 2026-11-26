import { useRef, useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Loader2, FileText, Plus, Lock, CheckCircle2, AlertTriangle, Trash2, Type, BookOpen } from "lucide-react";
import { toast } from "sonner";
import { useConhecimento, type ConhecimentoDoc } from "@/hooks/useConhecimento";
import { CONHECIMENTO_ACCEPT, formatarTamanho } from "@/lib/conhecimento";
import { arquivoParaBase64 } from "@/lib/base64";
import { useBibliotecaConhecimento } from "@/hooks/useBibliotecaConhecimento";

/** Badge de status do documento (indexação). */
function StatusBadge({ d }: { d: ConhecimentoDoc }) {
  if (d.status === "processando")
    return <span className="inline-flex items-center gap-1 text-[11px] font-medium text-amber-600"><Loader2 className="size-3 animate-spin" />Indexando…</span>;
  if (d.status === "erro")
    return <span className="inline-flex items-center gap-1 text-[11px] font-medium text-rose-600" title={d.erro_mensagem ?? ""}><AlertTriangle className="size-3" />Erro</span>;
  return <span className="inline-flex items-center gap-1 text-[11px] font-medium text-emerald-600"><CheckCircle2 className="size-3" />Pronto{d.tokens ? ` · ${d.tokens} tokens` : ""}</span>;
}

/**
 * Pré-visualização (read-only) dos docs PADRÃO do catálogo — exibida na ATIVAÇÃO, antes do
 * agente existir. A pessoa vê o que já virá pronto (travado) ao ativar o produto.
 */
function PreviewCatalogo({ idProduto }: { idProduto: string }) {
  const { data: docs, isLoading } = useBibliotecaConhecimento(idProduto);
  const lista = docs ?? [];
  return (
    <Card className="lc-card p-6 space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-[#101828]">Base de conhecimento</h3>
        <p className="text-xs text-muted-foreground mt-0.5">
          {lista.length > 0
            ? "Estes documentos já vêm prontos com o produto. Depois de ativar, você adiciona os seus."
            : "Depois de ativar, você sobe documentos (PDF, DOCX, TXT) e o agente usa como contexto."}
        </p>
      </div>
      {isLoading ? (
        <div className="grid place-items-center py-6"><Loader2 className="size-5 animate-spin text-muted-foreground" /></div>
      ) : lista.length > 0 ? (
        <div className="space-y-2">
          {lista.map((d) => (
            <div key={d.id} className="flex items-center gap-3 rounded-xl border border-[#eef1f5] bg-[#fafbfc] p-3">
              <div className="size-9 rounded-lg grid place-items-center shrink-0 bg-primary/10 text-primary">
                {d.tipo === "texto" ? <Type className="size-[18px]" /> : <FileText className="size-[18px]" />}
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-[#101828] truncate flex items-center gap-1.5">
                  {d.nome}<Lock className="size-3 text-[#98A2B3] shrink-0" />
                </div>
                <div className="text-[11px] text-muted-foreground mt-0.5">Padrão do produto · vem pronto ao ativar</div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-xs text-muted-foreground border border-dashed border-border rounded-xl p-6 text-center">
          Este produto não tem documentos padrão. Você adiciona os seus depois de ativar.
        </div>
      )}
    </Card>
  );
}

/**
 * Gerência da base de conhecimento (RAG) de UM agente. O upload manda o arquivo ao servidor, que
 * extrai o texto (PDF/DOCX/TXT) e indexa; também aceita texto colado. Docs do catálogo (admin)
 * vêm travados (cadeado, sem remover); o cliente só remove os dele.
 */
export default function ConhecimentoManager({ idAgente, idProduto }: { idAgente: string | null | undefined; idProduto?: string | null }) {
  const { data: docs, isLoading, adicionar, remover } = useConhecimento(idAgente);
  const fileRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [modoTexto, setModoTexto] = useState(false);
  const [titulo, setTitulo] = useState("");
  const [texto, setTexto] = useState("");

  // Na ATIVAÇÃO (agente ainda não existe): mostra os docs PADRÃO do catálogo (read-only).
  if (!idAgente) {
    if (idProduto) return <PreviewCatalogo idProduto={idProduto} />;
    return (
      <Card className="lc-card p-8 text-center">
        <div className="size-12 rounded-2xl grid place-items-center mx-auto mb-3 bg-[#F1F5F9] text-[#94A3B8]"><BookOpen className="size-6" /></div>
        <h3 className="text-sm font-semibold text-[#101828]">Base de conhecimento</h3>
        <p className="text-xs text-[#667085] mt-1 max-w-[280px] mx-auto">
          Disponível depois de ativar o produto. Aí você sobe documentos (PDF, DOCX, TXT) e o agente
          usa como contexto nas conversas.
        </p>
      </Card>
    );
  }

  const enviarArquivo = async (file: File) => {
    setBusy(true);
    try {
      // O servidor extrai o texto (PDF/DOCX/TXT) e indexa.
      await adicionar.mutateAsync({
        nome: file.name, conteudo_base64: await arquivoParaBase64(file), mime: file.type || "application/octet-stream",
      });
      toast.success("Documento adicionado", { description: "Indexando para o agente…" });
    } catch (e: any) {
      toast.error("Erro ao adicionar", { description: e?.message ?? String(e) });
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const enviarTexto = async () => {
    if (!texto.trim()) return;
    setBusy(true);
    try {
      await adicionar.mutateAsync({ tipo: "texto", nome: titulo.trim() || "Texto colado", texto: texto.trim() });
      toast.success("Texto adicionado", { description: "Indexando para o agente…" });
      setTitulo(""); setTexto(""); setModoTexto(false);
    } catch (e: any) {
      toast.error("Erro ao adicionar", { description: e?.message ?? String(e) });
    } finally { setBusy(false); }
  };

  const lista = docs ?? [];
  const prontos = lista.filter((d) => d.status === "concluido").length;

  return (
    <Card className="lc-card p-6 space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-[#101828]">Base de conhecimento</h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            PDF, DOCX ou TXT — o texto é extraído e indexado. O agente responde com base nesses documentos.
          </p>
        </div>
        {lista.length > 0 && <span className="text-[11px] text-muted-foreground shrink-0">{prontos}/{lista.length} prontos</span>}
      </div>

      {/* Lista */}
      {isLoading ? (
        <div className="grid place-items-center py-8"><Loader2 className="size-5 animate-spin text-muted-foreground" /></div>
      ) : lista.length === 0 ? (
        <div className="text-xs text-muted-foreground border border-dashed border-border rounded-xl p-6 text-center">
          Nenhum documento ainda. Adicione PDFs, DOCX ou cole um texto.
        </div>
      ) : (
        <div className="space-y-2">
          {lista.map((d) => (
            <div key={d.id} className="flex items-center gap-3 rounded-xl border border-[#eef1f5] bg-[#fafbfc] p-3">
              <div className="size-9 rounded-lg grid place-items-center shrink-0 bg-primary/10 text-primary">
                {d.tipo === "texto" ? <Type className="size-[18px]" /> : <FileText className="size-[18px]" />}
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-[#101828] truncate flex items-center gap-1.5">
                  {d.arquivo_nome ?? d.descricao ?? "Documento"}
                  {d.travado && <Lock className="size-3 text-[#98A2B3] shrink-0" />}
                </div>
                <div className="flex items-center gap-2 mt-0.5">
                  <StatusBadge d={d} />
                  {d.travado && <span className="text-[10px] text-muted-foreground">· padrão</span>}
                  {d.arquivo_tamanho ? <span className="text-[10px] text-muted-foreground">· {formatarTamanho(d.arquivo_tamanho)}</span> : null}
                </div>
              </div>
              {d.travado ? (
                <span className="text-[10px] text-muted-foreground px-2 shrink-0">Bloqueado</span>
              ) : (
                <Button variant="ghost" size="icon" className="shrink-0 text-[#cbd5e1] hover:text-rose-500"
                  disabled={remover.isPending}
                  onClick={async () => { try { await remover.mutateAsync(d.id); } catch (e: any) { toast.error("Erro ao remover", { description: e?.message }); } }}>
                  <Trash2 className="size-4" />
                </Button>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Adicionar texto */}
      {modoTexto && (
        <div className="rounded-xl border border-[#eef1f5] p-3 space-y-2 bg-[#fafbfc]">
          <Input value={titulo} onChange={(e) => setTitulo(e.target.value)} placeholder="Título (ex.: Política de honorários)" className="bg-white text-sm" />
          <Textarea value={texto} onChange={(e) => setTexto(e.target.value)} placeholder="Cole aqui o texto que o agente deve conhecer…" rows={5} className="bg-white text-sm" />
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => { setModoTexto(false); setTitulo(""); setTexto(""); }}>Cancelar</Button>
            <Button size="sm" onClick={enviarTexto} disabled={busy || !texto.trim()}>
              {busy ? <Loader2 className="size-4 mr-1.5 animate-spin" /> : <Plus className="size-4 mr-1.5" />}Adicionar texto
            </Button>
          </div>
        </div>
      )}

      {/* Ações */}
      <div className="flex flex-wrap items-center gap-2">
        <input ref={fileRef} type="file" accept={CONHECIMENTO_ACCEPT} className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) enviarArquivo(f); }} />
        <Button variant="outline" size="sm" disabled={busy} onClick={() => fileRef.current?.click()}>
          {busy ? <Loader2 className="size-4 mr-1.5 animate-spin" /> : <Plus className="size-4 mr-1.5" />}Enviar documento
        </Button>
        {!modoTexto && (
          <Button variant="ghost" size="sm" disabled={busy} onClick={() => setModoTexto(true)}>
            <Type className="size-4 mr-1.5" />Colar texto
          </Button>
        )}
        <span className="text-[11px] text-muted-foreground ml-auto">PDF · DOCX · TXT</span>
      </div>
    </Card>
  );
}
