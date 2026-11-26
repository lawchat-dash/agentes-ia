import { useState } from "react";
import { ArrowRight, ArrowRightLeft, Loader2, Pencil, Plus, Trash2 } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { useExcluirFraseTroca, useFrasesTroca, useIdProdutoFrases, useSalvarFraseTroca } from "@/hooks/useFrasesTroca";
import { COR_TRANSFERENCIA, ETAPAS_TROCA, FraseTroca, rotuloFrase, validarFrase } from "@/data/frasesTroca";

const ETAPAS = ETAPAS_TROCA.map((e) => ({ etapa: e.etapa, label: e.nome }));

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  /** Tela aberta troca o chip pelo texto no estado local (senão salvar recolocaria o chip órfão). */
  onExcluida?: (f: FraseTroca) => void;
}

/**
 * Cadastro das FRASES PARA TRANSFERÊNCIA (só super admin). Uma frase por departamento de destino:
 * o agente anterior fala a frase (via @Transferência no prompt dele) e o fluxo passa o
 * lead para este departamento. As frases são DESTE PRODUTO: editar/excluir não afeta outros
 * produtos; editar o texto propaga só para os clientes que ativaram este produto.
 */
export const FrasesTrocaDialog = ({ open, onOpenChange, onExcluida }: Props) => {
  const idProduto = useIdProdutoFrases(); // cadastro é do produto aberto
  const { data: frases, isLoading } = useFrasesTroca();
  const salvar = useSalvarFraseTroca();
  const excluir = useExcluirFraseTroca();
  const [editando, setEditando] = useState<string | null>(null); // etapa em edição
  const [texto, setTexto] = useState("");
  const [descricao, setDescricao] = useState("");
  const [confirmarExclusao, setConfirmarExclusao] = useState<string | null>(null);

  const porEtapa = new Map((frases ?? []).map((f) => [f.etapa_destino, f]));

  const abrirEdicao = (etapa: string, f: FraseTroca | undefined) => {
    setEditando(etapa);
    setTexto(f?.frase ?? "");
    setDescricao(f?.descricao ?? "");
    setConfirmarExclusao(null);
  };

  const salvarEdicao = async (etapa: string, f: FraseTroca | undefined) => {
    const erro = validarFrase(texto);
    if (erro) return toast.error("Frase inválida", { description: erro });
    if (!idProduto) return toast.error("Salve o produto primeiro", { description: "As frases são de cada produto — salve o produto para cadastrar as frases dele." });
    try {
      const r: any = await salvar.mutateAsync({ id: f?.id ?? null, id_produto_biblioteca: idProduto, etapa_destino: etapa, frase: texto, descricao });
      const mudouTexto = !!f && f.frase !== texto.trim();
      toast.success(f ? "Frase atualizada" : "Frase criada", {
        description: mudouTexto
          ? `Atualizada só neste produto: ${r?.prompts_atualizados ?? 0} prompt(s) publicado(s) e ${r?.mensagens_troca_atualizadas ?? 0} mensagem(ns) de troca.`
          : f ? undefined : `Use no prompt digitando @ → Transferência.`,
      });
      setEditando(null);
    } catch (e: any) {
      const msg = String(e?.message ?? "");
      toast.error("Não foi possível salvar", {
        description: /duplicate|unique/i.test(msg) ? "Essa frase já é usada por outro departamento deste produto." : msg,
      });
    }
  };

  const excluirFrase = async (f: FraseTroca) => {
    try {
      if (!idProduto) throw new Error("Salve o produto primeiro.");
      await excluir.mutateAsync({ id: f.id, id_produto_biblioteca: idProduto, etapa_destino: f.etapa_destino });
      onExcluida?.(f);
      toast.success("Frase excluída só deste produto", {
        description: "Os prompts dos clientes não foram alterados. No catálogo, o chip virou o texto da frase.",
      });
      setConfirmarExclusao(null);
    } catch (e: any) {
      toast.error("Não foi possível excluir", { description: e?.message });
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[88vh] flex flex-col gap-0 p-0 overflow-hidden">
        <DialogHeader className="p-6 pb-4 text-left space-y-3 border-b border-border">
          <DialogTitle className="flex items-center gap-2.5">
            <span className="size-9 rounded-xl grid place-items-center shrink-0" style={{ background: "#fff7ed", color: COR_TRANSFERENCIA }}>
              <ArrowRightLeft className="size-[18px]" />
            </span>
            Frases para Transferência
          </DialogTitle>
          <DialogDescription className="text-sm leading-relaxed text-foreground/80">
            Cada agente (departamento) tem a <strong>sua própria frase de entrada</strong>. Quando o agente anterior
            fala exatamente essa frase, o lead passa para aquele agente.
          </DialogDescription>
          {/* O fluxo em uma linha: quem fala, o quê, e para onde o lead vai. */}
          <div className="flex flex-wrap items-center gap-1.5 rounded-xl bg-muted/40 px-3 py-2.5 text-xs text-muted-foreground" aria-hidden>
            <span className="rounded-md border border-border bg-card px-2 py-1 font-semibold text-foreground">Agente anterior</span>
            <span>fala a frase</span>
            <span className="rounded-md px-2 py-1 font-semibold" style={{ color: COR_TRANSFERENCIA, background: "#fff7ed" }}>“Ótimo, vou te passar…”</span>
            <ArrowRight className="size-3.5" />
            <span className="rounded-md border border-border bg-card px-2 py-1 font-semibold text-foreground">o lead entra no agente dono da frase</span>
          </div>
          <ul className="grid gap-1 text-xs text-muted-foreground sm:grid-cols-2">
            <li>• No prompt do agente anterior, insira com <strong className="text-foreground">@ → Transferência</strong>.</li>
            <li>• A frase precisa ser dita igual, palavra por palavra.</li>
            <li>• Vale só para este produto: os outros não mudam.</li>
            <li>• Editar o texto atualiza os prompts que já usam a frase.</li>
          </ul>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-2.5">
          {isLoading ? (
            <div className="grid place-items-center py-12"><Loader2 className="size-6 animate-spin text-primary" /></div>
          ) : (
            ETAPAS.map(({ etapa, label }) => {
              const f = porEtapa.get(etapa);
              const emEdicao = editando === etapa;
              return (
                <div key={etapa} className="rounded-xl border border-border bg-card p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">Frase de entrada do agente <span className="text-foreground">{label}</span></div>
                      {f ? (
                        <code className="mt-1 inline-block rounded px-1.5 py-0.5 text-xs font-semibold" style={{ color: COR_TRANSFERENCIA, background: "#fff7ed" }}>
                          @{rotuloFrase(f.nome)}
                        </code>
                      ) : (
                        <p className="mt-1 text-xs text-muted-foreground">Ainda sem frase: nenhum agente consegue passar o lead para {label}.</p>
                      )}
                    </div>
                    {!emEdicao && (
                      <div className="flex items-center gap-1 shrink-0">
                        {f ? (
                          <>
                            <Button size="sm" variant="outline" onClick={() => abrirEdicao(etapa, f)}>
                              <Pencil className="size-3.5 mr-1.5" />Editar
                            </Button>
                            {confirmarExclusao === f.id ? (
                              <Button size="sm" variant="destructive" disabled={excluir.isPending} onClick={() => excluirFrase(f)}>
                                {excluir.isPending && <Loader2 className="size-3.5 mr-1.5 animate-spin" />}Confirmar exclusão
                              </Button>
                            ) : (
                              <Button size="icon" variant="ghost" className="size-9 text-muted-foreground hover:text-destructive" title="Excluir" onClick={() => setConfirmarExclusao(f.id)}>
                                <Trash2 className="size-4" />
                              </Button>
                            )}
                          </>
                        ) : (
                          <Button size="sm" variant="outline" onClick={() => abrirEdicao(etapa, undefined)}>
                            <Plus className="size-3.5 mr-1.5" />Criar frase
                          </Button>
                        )}
                      </div>
                    )}
                  </div>

                  {confirmarExclusao && confirmarExclusao === f?.id && (
                    <p className="mt-2 text-xs text-destructive">
                      Só neste produto: no catálogo, @{rotuloFrase(f.nome)} vira o texto da frase. Os prompts dos clientes não mudam.
                    </p>
                  )}

                  {emEdicao ? (
                    <div className="mt-3 space-y-3">
                      <div className="space-y-1.5">
                        <Label className="text-xs font-semibold">Frase exata (quando o agente anterior falar isto, o lead vai para {label})</Label>
                        <Textarea
                          value={texto}
                          onChange={(e) => setTexto(e.target.value.replace(/\n/g, " "))}
                          rows={2}
                          placeholder="Ex.: Maravilha! Nós podemos te ajudar no seu caso."
                          className="text-sm"
                        />
                        <p className="text-[11px] text-muted-foreground">
                          Uma linha, sem @, {"{{ }}"}, aspas ou barra — o bot compara o texto literalmente.
                          {f && " Ao salvar, os prompts já publicados que usam esta frase são atualizados juntos."}
                        </p>
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-xs font-semibold">Quando usar (opcional)</Label>
                        <Input value={descricao} onChange={(e) => setDescricao(e.target.value)} placeholder={`Ex.: O agente anterior fala esta frase quando o lead deve ir para ${label}.`} className="text-sm" />
                      </div>
                      <div className="flex justify-end gap-2">
                        <Button size="sm" variant="ghost" onClick={() => setEditando(null)}>Cancelar</Button>
                        <Button size="sm" disabled={salvar.isPending || !texto.trim()} onClick={() => salvarEdicao(etapa, f)}>
                          {salvar.isPending && <Loader2 className="size-3.5 mr-1.5 animate-spin" />}Salvar
                        </Button>
                      </div>
                    </div>
                  ) : f ? (
                    <div className="mt-2.5 space-y-1">
                      <p className="text-sm text-foreground leading-relaxed">“{f.frase}”</p>
                      {f.descricao && <p className="text-xs text-muted-foreground">{f.descricao}</p>}
                    </div>
                  ) : null}
                </div>
              );
            })
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
};
