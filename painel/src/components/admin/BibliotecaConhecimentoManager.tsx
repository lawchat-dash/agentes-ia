import { useRef, useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Loader2, FileText, Plus, Trash2, Type, BookOpen, Lock } from "lucide-react";
import { toast } from "sonner";
import { useBibliotecaConhecimento } from "@/hooks/useBibliotecaConhecimento";
import { corpoDocumento, CONHECIMENTO_ACCEPT, formatarTamanho } from "@/lib/extrairTexto";

/**
 * Catálogo de conhecimento do ADMIN (docs padrão de um produto). O arquivo vai em base64 e o
 * SERVIDOR extrai o texto. Ao ativar o produto, esses docs
 * são copiados (travados) p/ o agente do cliente — ele vê com cadeado e só adiciona os dele.
 */
export default function BibliotecaConhecimentoManager({ idProduto }: { idProduto: string | null | undefined }) {
  const { data: docs, isLoading, adicionar, remover } = useBibliotecaConhecimento(idProduto);
  const fileRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [modoTexto, setModoTexto] = useState(false);
  const [titulo, setTitulo] = useState("");
  const [texto, setTexto] = useState("");

  if (!idProduto) {
    return <Card className="p-5 text-sm text-muted-foreground">Salve o produto primeiro para anexar documentos padrão.</Card>;
  }

  const enviarArquivo = async (file: File) => {
    setBusy(true);
    try {
      await adicionar.mutateAsync(await corpoDocumento(file));
      toast.success("Documento padrão adicionado");
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
      await adicionar.mutateAsync({ nome: titulo.trim() || "Texto", tipo: "texto", texto: texto.trim() });
      toast.success("Texto padrão adicionado");
      setTitulo(""); setTexto(""); setModoTexto(false);
    } catch (e: any) {
      toast.error("Erro ao adicionar", { description: e?.message ?? String(e) });
    } finally { setBusy(false); }
  };

  const lista = docs ?? [];

  return (
    <Card className="p-6 space-y-4">
      <div className="flex items-start gap-3">
        <div className="size-9 rounded-xl grid place-items-center shrink-0 bg-primary/10 text-primary"><BookOpen className="size-[18px]" /></div>
        <div>
          <h3 className="text-base font-semibold">Conhecimento padrão</h3>
          <p className="text-xs text-muted-foreground mt-0.5 flex items-center gap-1">
            <Lock className="size-3" /> Ao ativar, o cliente já recebe estes documentos (travados) — ele vê e adiciona os dele, mas não remove estes.
          </p>
        </div>
      </div>

      {isLoading ? (
        <div className="grid place-items-center py-8"><Loader2 className="size-5 animate-spin text-muted-foreground" /></div>
      ) : lista.length === 0 ? (
        <div className="text-xs text-muted-foreground border border-dashed border-border rounded-xl p-6 text-center">
          Nenhum documento padrão. Suba PDFs, DOCX ou cole um texto.
        </div>
      ) : (
        <div className="space-y-2">
          {lista.map((d) => (
            <div key={d.id} className="flex items-center gap-3 rounded-xl border p-3 bg-muted/20">
              <div className="size-9 rounded-lg grid place-items-center shrink-0 bg-primary/10 text-primary">
                {d.tipo === "texto" ? <Type className="size-[18px]" /> : <FileText className="size-[18px]" />}
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium truncate">{d.nome}</div>
                <div className="text-[11px] text-muted-foreground">
                  {d.tipo === "texto" ? "Texto" : "Arquivo"}
                  {d.tamanho_bytes ? ` · ${formatarTamanho(d.tamanho_bytes)}` : ""}
                  {d.caracteres ? ` · ${d.caracteres.toLocaleString()} caracteres` : ""}
                </div>
              </div>
              <Button type="button" variant="ghost" size="icon" className="shrink-0 text-muted-foreground hover:text-rose-500"
                disabled={remover.isPending}
                onClick={async () => { try { await remover.mutateAsync(d.id); } catch (e: any) { toast.error("Erro ao remover", { description: e?.message }); } }}>
                <Trash2 className="size-4" />
              </Button>
            </div>
          ))}
        </div>
      )}

      {modoTexto && (
        <div className="rounded-xl border p-3 space-y-2 bg-muted/20">
          <Input value={titulo} onChange={(e) => setTitulo(e.target.value)} placeholder="Título (ex.: Tabela de honorários)" className="text-sm" />
          <Textarea value={texto} onChange={(e) => setTexto(e.target.value)} placeholder="Cole o texto padrão que todo cliente deve ter…" rows={5} className="text-sm" />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" size="sm" onClick={() => { setModoTexto(false); setTitulo(""); setTexto(""); }}>Cancelar</Button>
            <Button type="button" size="sm" onClick={enviarTexto} disabled={busy || !texto.trim()}>
              {busy ? <Loader2 className="size-4 mr-1.5 animate-spin" /> : <Plus className="size-4 mr-1.5" />}Adicionar
            </Button>
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <input ref={fileRef} type="file" accept={CONHECIMENTO_ACCEPT} className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) enviarArquivo(f); }} />
        <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => fileRef.current?.click()}>
          {busy ? <Loader2 className="size-4 mr-1.5 animate-spin" /> : <Plus className="size-4 mr-1.5" />}Enviar documento
        </Button>
        {!modoTexto && (
          <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => setModoTexto(true)}>
            <Type className="size-4 mr-1.5" />Colar texto
          </Button>
        )}
        <span className="text-[11px] text-muted-foreground ml-auto">PDF · DOCX · TXT</span>
      </div>
    </Card>
  );
}
