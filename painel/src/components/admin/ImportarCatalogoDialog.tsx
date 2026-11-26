import { useRef, useState } from "react";
import { toast } from "sonner";
import { AlertTriangle, CheckCircle2, FileJson, Loader2, Upload, X } from "lucide-react";
import { enviar } from "@/api";
import { arquivoParaBase64 } from "@/lib/base64";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";

/** Resposta de POST /admin/biblioteca/importar (prévia ou aplicado). */
interface Plano {
  produtos: {
    slug: string; nome: string; status: string; categoria: string; modo_midia: string; acao: "criar" | "atualizar";
    agentes: number; papeis: string[]; documentos: number; frases: number; followups: number;
  }[];
  frases_globais: number;
  avisos: string[];
  aplicado: boolean;
}

const STATUS: Record<string, string> = { publicado: "Publicado", em_breve: "Em breve", rascunho: "Rascunho" };

/**
 * Importa o catálogo exportado do sistema antigo (docs/EXPORTAR_CATALOGO.sql no Supabase AGENT WEAVER).
 * 1) escolhe o(s) arquivo(s) → prévia do que vai ser criado/atualizado; 2) confirma → grava.
 */
export function ImportarCatalogoDialog({ open, onOpenChange, onImportado }: {
  open: boolean; onOpenChange: (v: boolean) => void; onImportado: () => void;
}) {
  const entrada = useRef<HTMLInputElement>(null);
  const [arquivos, setArquivos] = useState<{ nome: string; conteudo_base64: string; tamanho: number }[]>([]);
  const [plano, setPlano] = useState<Plano | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const limpar = () => { setArquivos([]); setPlano(null); setErro(null); };
  // Fechar sempre zera o diálogo; durante a leitura/gravação não fecha (a resposta chegaria num diálogo já fechado).
  const fechar = () => { if (ocupado) return; onOpenChange(false); limpar(); };

  const escolher = async (lista: FileList | null) => {
    if (!lista?.length) return;
    setErro(null); setPlano(null); setOcupado(true);
    try {
      const lidos = await Promise.all(Array.from(lista).map(async (f) => ({ nome: f.name, conteudo_base64: await arquivoParaBase64(f), tamanho: f.size })));
      setArquivos(lidos);
      setPlano(await enviar<Plano>("/admin/biblioteca/importar", { arquivos: lidos.map(({ nome, conteudo_base64 }) => ({ nome, conteudo_base64 })), aplicar: false }));
    } catch (e: any) {
      setErro(e?.message ?? "Não foi possível ler o arquivo.");
    } finally {
      setOcupado(false);
    }
  };

  const importar = async () => {
    setOcupado(true);
    try {
      const feito = await enviar<Plano>("/admin/biblioteca/importar", { arquivos: arquivos.map(({ nome, conteudo_base64 }) => ({ nome, conteudo_base64 })), aplicar: true });
      toast.success("Catálogo importado", { description: `${feito.produtos.length} produto(s) criados ou atualizados.` });
      onImportado();
      // Avisos que só aparecem ao gravar (ex.: arquivo de documento que não baixou): o diálogo fica aberto mostrando.
      const novos = feito.avisos.filter((a) => !(plano?.avisos ?? []).includes(a));
      if (novos.length) { setPlano({ ...feito }); toast.warning("Importado com avisos", { description: novos.join(" ") }); return; }
      onOpenChange(false);
      limpar();
    } catch (e: any) {
      toast.error("Erro ao importar", { description: e?.message });
    } finally {
      setOcupado(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) fechar(); else onOpenChange(true); }}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><Upload className="size-5 text-primary" />Importar catálogo</DialogTitle>
        </DialogHeader>
        <p className="text-sm text-muted-foreground -mt-1">
          Traz os produtos do sistema antigo com os prompts dos agentes, FAQ, objeções, dados do escritório, frases de transferência,
          follow-up e documentos padrão. No Supabase, rode a consulta de <code className="text-[#7c3aed]">docs/EXPORTAR_CATALOGO.sql</code> e
          envie o resultado (.json ou .csv). Importar de novo atualiza, não duplica.
        </p>

        {!plano && (
          <button type="button" onClick={() => entrada.current?.click()} disabled={ocupado}
            className="w-full rounded-xl border-2 border-dashed border-border hover:border-primary/60 hover:bg-primary/5 transition-colors p-8 flex flex-col items-center gap-2 text-sm">
            {ocupado ? <Loader2 className="size-6 animate-spin text-primary" /> : <FileJson className="size-7 text-primary" />}
            <span className="font-semibold">{ocupado ? "Lendo o arquivo…" : "Escolher arquivo do catálogo"}</span>
            <span className="text-xs text-muted-foreground">JSON ou CSV · até 40 MB · pode enviar um arquivo por tabela</span>
          </button>
        )}
        <input ref={entrada} type="file" hidden multiple accept=".json,.csv,application/json,text/csv"
          onChange={(e) => { void escolher(e.target.files); e.target.value = ""; }} />

        {erro && (
          <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive flex gap-2">
            <AlertTriangle className="size-4 shrink-0 mt-0.5" /><span>{erro}</span>
          </div>
        )}

        {plano && (
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-sm">
              <CheckCircle2 className="size-4 text-primary" />
              <span><strong>{plano.produtos.length}</strong> produto(s) em {arquivos.map((a) => a.nome).join(", ")}</span>
              {!plano.aplicado && (
                <button type="button" disabled={ocupado} className="ml-auto text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1" onClick={limpar}>
                  <X className="size-3" />Trocar arquivo
                </button>
              )}
            </div>
            <div className="max-h-72 overflow-y-auto rounded-lg border border-border divide-y divide-border">
              {plano.produtos.map((p, i) => (
                <div key={`${p.slug}-${i}`} className="p-3 text-sm flex items-start gap-3">
                  <span className={`text-[10px] font-bold uppercase rounded-full px-2 py-0.5 shrink-0 ${p.acao === "criar" ? "bg-primary/10 text-primary" : "bg-amber-500/10 text-amber-700"}`}>
                    {p.acao === "criar" ? "Novo" : "Atualiza"}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="font-semibold truncate">{p.nome}</div>
                    <div className="text-xs text-muted-foreground">
                      {p.categoria} · {STATUS[p.status] ?? p.status}{p.modo_midia === "audio" ? " · Mídia" : ""} · {p.agentes} agentes
                      {p.papeis.length ? ` (${p.papeis.join(", ")})` : ""} · {p.documentos} documento(s) · {p.frases} frase(s) · {p.followups} follow-up(s)
                    </div>
                  </div>
                </div>
              ))}
            </div>
            {plano.frases_globais > 0 && <p className="text-xs text-muted-foreground">Também vêm {plano.frases_globais} frase(s) de transferência gerais.</p>}
            {plano.avisos.length > 0 && (
              <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-xs space-y-1 max-h-40 overflow-y-auto">
                <div className="font-semibold text-amber-800 flex items-center gap-1.5"><AlertTriangle className="size-3.5" />Atenção ({plano.avisos.length})</div>
                {plano.avisos.map((a, i) => <div key={i} className="text-amber-900">• {a}</div>)}
              </div>
            )}
          </div>
        )}

        <DialogFooter>
          {plano?.aplicado ? (
            <Button onClick={fechar}><CheckCircle2 className="size-4 mr-1.5" />Fechar</Button>
          ) : (
            <>
              <Button variant="ghost" onClick={fechar} disabled={ocupado}>Cancelar</Button>
              <Button onClick={importar} disabled={ocupado || !plano || plano.produtos.length === 0}>
                {ocupado && plano ? <Loader2 className="size-4 mr-1.5 animate-spin" /> : <Upload className="size-4 mr-1.5" />}
                {`Importar ${plano ? `${plano.produtos.length} produto(s)` : ""}`}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
