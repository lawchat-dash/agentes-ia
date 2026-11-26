import { useEffect, useMemo, useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { Sparkles, MessageSquare, Shield, ListChecks, Building2, Loader2 } from "lucide-react";
import { api } from "@/api";
import { toast } from "sonner";

type Faq = { pergunta: string; resposta: string };
type Obj = { titulo: string; resposta: string };

export interface AtualizacaoAplicada {
  objecoesNovas: Obj[];        // adicionar (título inédito)
  objecoesAtualizadas: Obj[];  // substituir a resposta (mesmo título, texto novo)
  faqNovas: Faq[];             // adicionar (pergunta inédita)
  faqAtualizadas: Faq[];       // substituir a resposta (mesma pergunta, texto novo)
  regras?: string;             // presente = substituir regras gerais
  dados?: string;              // presente = substituir dados do escritório
}

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  templateId: string;
  versaoCatalogo?: string | null;
  /** Conteúdo ATUAL do cliente (pra comparar). */
  objecoesAtuais: Obj[];
  faqAtuais: Faq[];
  regrasAtuais: string;
  dadosAtuais: string;
  /** Aplica o que o cliente escolheu (merge no estado do editor). */
  onAplicar: (sel: AtualizacaoAplicada) => void;
}

const norm = (s?: string) => String(s ?? "").trim();
/** Preview limpo: tira marcadores [[...]] e URLs de mídia pra o texto ficar legível. */
const limparPreview = (s?: string) => String(s ?? "")
  .replace(/\[\[[^\]]*\]\]/g, "")
  .replace(/https?:\/\/\S+/g, "")
  .replace(/\s+/g, " ")
  .trim();

/**
 * "Revisar atualização" — quando o admin sobe a versão do produto, o cliente vê aqui o que
 * MUDOU no catálogo (objeções/FAQ novas + regras/dados alterados) e ESCOLHE o que trazer,
 * sem perder o que já personalizou (só adiciona/substitui o marcado). Ver useProducts.compararVersao.
 */
export const RevisarAtualizacao = ({ open, onOpenChange, templateId, versaoCatalogo, objecoesAtuais, faqAtuais, regrasAtuais, dadosAtuais, onAplicar }: Props) => {
  const [loading, setLoading] = useState(false);
  const [cat, setCat] = useState<{ faq: Faq[]; objecoes: Obj[]; regras: string; dados: string } | null>(null);
  // seleção
  const [selObj, setSelObj] = useState<Set<string>>(new Set());       // objeções novas
  const [selObjUpd, setSelObjUpd] = useState<Set<string>>(new Set()); // objeções alteradas
  const [selFaq, setSelFaq] = useState<Set<string>>(new Set());       // FAQ novas
  const [selFaqUpd, setSelFaqUpd] = useState<Set<string>>(new Set()); // FAQ alteradas
  const [selRegras, setSelRegras] = useState(false);
  const [selDados, setSelDados] = useState(false);

  useEffect(() => {
    if (!open || !templateId) return;
    setLoading(true);
    (async () => {
      const data = await api<any>(`/biblioteca/produtos/${encodeURIComponent(templateId)}`).catch(() => null);
      setCat({
        faq: Array.isArray(data?.faq) ? data.faq.map((f: any) => ({ pergunta: f.pergunta ?? f.q ?? "", resposta: f.resposta ?? f.a ?? "" })) : [],
        objecoes: Array.isArray(data?.objecoes) ? data.objecoes.map((o: any) => ({ titulo: o.titulo ?? o.gatilho ?? "", resposta: o.resposta ?? "" })) : [],
        regras: data?.regras_markdown ?? "",
        dados: data?.dados_escritorio ?? "",
      });
      setLoading(false);
    })();
  }, [open, templateId]);

  // Diff: NOVAS (título/pergunta inédito) + ALTERADAS (mesmo título/pergunta, resposta diferente).
  const objNovas = useMemo(() => (cat?.objecoes ?? []).filter((c) => norm(c.titulo) && !objecoesAtuais.some((a) => norm(a.titulo) === norm(c.titulo))), [cat, objecoesAtuais]);
  const objAlteradas = useMemo(() => (cat?.objecoes ?? []).filter((c) => norm(c.titulo) && objecoesAtuais.some((a) => norm(a.titulo) === norm(c.titulo) && norm(a.resposta) !== norm(c.resposta))), [cat, objecoesAtuais]);
  const faqNovas = useMemo(() => (cat?.faq ?? []).filter((c) => norm(c.pergunta) && !faqAtuais.some((a) => norm(a.pergunta) === norm(c.pergunta))), [cat, faqAtuais]);
  const faqAlteradas = useMemo(() => (cat?.faq ?? []).filter((c) => norm(c.pergunta) && faqAtuais.some((a) => norm(a.pergunta) === norm(c.pergunta) && norm(a.resposta) !== norm(c.resposta))), [cat, faqAtuais]);
  const regrasMudou = !!cat && norm(cat.regras) !== "" && norm(cat.regras) !== norm(regrasAtuais);
  const dadosMudou = !!cat && norm(cat.dados) !== "" && norm(cat.dados) !== norm(dadosAtuais);

  // pré-marca só o que é seguro (NOVAS + textos). As ALTERADAS ficam desmarcadas — o cliente
  // pode ter personalizado, então ele OPTA por substituir cada uma.
  useEffect(() => {
    if (!cat) return;
    setSelObj(new Set(objNovas.map((o) => o.titulo)));
    setSelFaq(new Set(faqNovas.map((f) => f.pergunta)));
    setSelObjUpd(new Set());
    setSelFaqUpd(new Set());
    setSelRegras(regrasMudou);
    setSelDados(dadosMudou);
  }, [cat]); // eslint-disable-line react-hooks/exhaustive-deps

  const totalMudancas = objNovas.length + objAlteradas.length + faqNovas.length + faqAlteradas.length + (regrasMudou ? 1 : 0) + (dadosMudou ? 1 : 0);
  const totalSel = selObj.size + selObjUpd.size + selFaq.size + selFaqUpd.size + (selRegras ? 1 : 0) + (selDados ? 1 : 0);

  const aplicar = () => {
    onAplicar({
      objecoesNovas: objNovas.filter((o) => selObj.has(o.titulo)),
      objecoesAtualizadas: objAlteradas.filter((o) => selObjUpd.has(o.titulo)),
      faqNovas: faqNovas.filter((f) => selFaq.has(f.pergunta)),
      faqAtualizadas: faqAlteradas.filter((f) => selFaqUpd.has(f.pergunta)),
      regras: selRegras && cat ? cat.regras : undefined,
      dados: selDados && cat ? cat.dados : undefined,
    });
    toast.success(totalSel > 0 ? `${totalSel} atualização${totalSel > 1 ? "ões" : ""} trazida${totalSel > 1 ? "s" : ""} — salve para confirmar` : "Atualização revisada");
    onOpenChange(false);
  };

  const toggle = (set: React.Dispatch<React.SetStateAction<Set<string>>>, key: string) =>
    set((prev) => { const n = new Set(prev); n.has(key) ? n.delete(key) : n.add(key); return n; });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto" onOpenAutoFocus={(e) => e.preventDefault()}>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="size-4 text-primary" /> Atualização do produto
            {versaoCatalogo && <Badge variant="outline" className="text-[11px]">v{versaoCatalogo}</Badge>}
          </DialogTitle>
          <DialogDescription>
            O administrador atualizou este produto. Escolha o que trazer — o que você já personalizou não é alterado.
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="py-10 grid place-items-center text-sm text-muted-foreground gap-2"><Loader2 className="size-6 animate-spin text-primary" />Carregando o que mudou…</div>
        ) : totalMudancas === 0 ? (
          <div className="py-10 text-center text-sm text-muted-foreground">Nada novo pra trazer — você já tem o conteúdo mais recente deste produto.</div>
        ) : (
          <div className="space-y-4">
            {/* Objeções novas */}
            {objNovas.length > 0 && (
              <Secao Icon={Shield} titulo="Objeções novas" n={objNovas.length}
                onTodos={() => setSelObj(new Set(objNovas.map((o) => o.titulo)))} onNenhum={() => setSelObj(new Set())}>
                {objNovas.map((o) => (
                  <Item key={o.titulo} checked={selObj.has(o.titulo)} onToggle={() => toggle(setSelObj, o.titulo)} titulo={o.titulo} texto={o.resposta} tag="Nova" />
                ))}
              </Secao>
            )}
            {/* Objeções atualizadas (mesmo título, resposta nova — substitui se marcar) */}
            {objAlteradas.length > 0 && (
              <Secao Icon={Shield} titulo="Objeções atualizadas" n={objAlteradas.length}
                onTodos={() => setSelObjUpd(new Set(objAlteradas.map((o) => o.titulo)))} onNenhum={() => setSelObjUpd(new Set())}>
                {objAlteradas.map((o) => (
                  <Item key={o.titulo} checked={selObjUpd.has(o.titulo)} onToggle={() => toggle(setSelObjUpd, o.titulo)} titulo={o.titulo} texto={o.resposta} tag="Atualizada" />
                ))}
              </Secao>
            )}
            {/* FAQ novas */}
            {faqNovas.length > 0 && (
              <Secao Icon={MessageSquare} titulo="Perguntas (FAQ) novas" n={faqNovas.length}
                onTodos={() => setSelFaq(new Set(faqNovas.map((f) => f.pergunta)))} onNenhum={() => setSelFaq(new Set())}>
                {faqNovas.map((f) => (
                  <Item key={f.pergunta} checked={selFaq.has(f.pergunta)} onToggle={() => toggle(setSelFaq, f.pergunta)} titulo={f.pergunta} texto={f.resposta} tag="Nova" />
                ))}
              </Secao>
            )}
            {/* FAQ atualizadas */}
            {faqAlteradas.length > 0 && (
              <Secao Icon={MessageSquare} titulo="Perguntas (FAQ) atualizadas" n={faqAlteradas.length}
                onTodos={() => setSelFaqUpd(new Set(faqAlteradas.map((f) => f.pergunta)))} onNenhum={() => setSelFaqUpd(new Set())}>
                {faqAlteradas.map((f) => (
                  <Item key={f.pergunta} checked={selFaqUpd.has(f.pergunta)} onToggle={() => toggle(setSelFaqUpd, f.pergunta)} titulo={f.pergunta} texto={f.resposta} tag="Atualizada" />
                ))}
              </Secao>
            )}
            {/* Regras / Dados alterados (substituição) */}
            {(regrasMudou || dadosMudou) && (
              <Secao Icon={ListChecks} titulo="Conteúdo alterado" n={(regrasMudou ? 1 : 0) + (dadosMudou ? 1 : 0)}>
                {regrasMudou && <ItemBool checked={selRegras} onToggle={() => setSelRegras((v) => !v)} Icon={ListChecks} titulo="Regras gerais" hint="Substitui as suas regras gerais pela versão nova do catálogo." />}
                {dadosMudou && <ItemBool checked={selDados} onToggle={() => setSelDados((v) => !v)} Icon={Building2} titulo="Dados do Escritório" hint="Substitui os dados do escritório pela versão nova do catálogo." />}
              </Secao>
            )}
          </div>
        )}

        <DialogFooter className="gap-2">
          <Button variant="secondary" onClick={() => onOpenChange(false)}>Fechar</Button>
          <Button onClick={aplicar} disabled={loading || totalMudancas === 0} className="bg-primary text-primary-foreground">
            {totalSel > 0 ? `Trazer selecionados (${totalSel})` : "Marcar como revisado"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

const Secao = ({ Icon, titulo, n, children, onTodos, onNenhum }: { Icon: any; titulo: string; n: number; children: React.ReactNode; onTodos?: () => void; onNenhum?: () => void }) => (
  <div className="rounded-xl border border-border/70 p-3">
    <div className="flex items-center gap-2 mb-2">
      <div className="size-7 rounded-lg grid place-items-center bg-primary/10 text-primary shrink-0"><Icon className="size-3.5" /></div>
      <span className="text-sm font-semibold">{titulo}</span>
      <Badge variant="outline" className="text-[10px]">{n}</Badge>
      {(onTodos || onNenhum) && (
        <div className="ml-auto flex items-center gap-2 text-[11px] font-semibold">
          {onTodos && <button type="button" onClick={onTodos} className="text-primary hover:underline">Todos</button>}
          {onTodos && onNenhum && <span className="text-muted-foreground/40">·</span>}
          {onNenhum && <button type="button" onClick={onNenhum} className="text-muted-foreground hover:underline">Limpar</button>}
        </div>
      )}
    </div>
    <div className="space-y-1.5">{children}</div>
  </div>
);

const Item = ({ checked, onToggle, titulo, texto, tag }: { checked: boolean; onToggle: () => void; titulo: string; texto: string; tag: string }) => (
  <label className="flex items-start gap-2.5 rounded-lg border border-border/60 bg-muted/20 p-2.5 cursor-pointer hover:bg-muted/40 transition-colors">
    <Checkbox checked={checked} onCheckedChange={onToggle} className="mt-0.5" />
    <div className="min-w-0 flex-1">
      <div className="flex items-center gap-2">
        <span className="text-[13px] font-semibold truncate">{titulo}</span>
        <Badge className={`text-[10px] shrink-0 ${tag === "Atualizada" ? "bg-amber-500/10 text-amber-600 border-amber-500/30" : "bg-primary/10 text-primary border-primary/30"}`}>{tag}</Badge>
      </div>
      {limparPreview(texto) && <p className="text-[11.5px] text-muted-foreground mt-0.5 line-clamp-2">{limparPreview(texto)}</p>}
    </div>
  </label>
);

const ItemBool = ({ checked, onToggle, Icon, titulo, hint }: { checked: boolean; onToggle: () => void; Icon: any; titulo: string; hint: string }) => (
  <label className="flex items-start gap-2.5 rounded-lg border border-border/60 bg-muted/20 p-2.5 cursor-pointer hover:bg-muted/40 transition-colors">
    <Checkbox checked={checked} onCheckedChange={onToggle} className="mt-0.5" />
    <div className="min-w-0 flex-1">
      <div className="flex items-center gap-1.5"><Icon className="size-3.5 text-muted-foreground" /><span className="text-[13px] font-semibold">{titulo}</span></div>
      <p className="text-[11.5px] text-muted-foreground mt-0.5">{hint}</p>
    </div>
  </label>
);
