import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRightLeft, Loader2, Settings2 } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { toast } from "sonner";
import { frasesTrocaKey, useFrasesTroca, useIdProdutoFrases, useSalvarFraseTroca } from "@/hooks/useFrasesTroca";
import {
  COR_TRANSFERENCIA, ETAPAS_TROCA, limparTrechoFrase, rotuloFrase, temTokenTransferencia, validarFrase,
} from "@/data/frasesTroca";

interface Props {
  /** Instância do tiptap (a seleção atual é o trecho a marcar). */
  editor: any;
  /** Abre o cadastro completo das frases. */
  onGerenciar?: () => void;
}

interface Selecao { from: number; to: number; frase: string; erro: string | null }

/**
 * "Marcar frase" (só super admin): a frase para transferência já está escrita no prompt — o admin
 * seleciona o trecho, escolhe o departamento e o trecho vira o chip laranja
 * "@Transferência: X". Cria a frase se o departamento não tiver; se já tiver outra, pede
 * confirmação para substituir (a troca propaga para os prompts publicados).
 */
export const MarcarFraseTroca = ({ editor, onGerenciar }: Props) => {
  const [open, setOpen] = useState(false);
  const [sel, setSel] = useState<Selecao | null>(null);
  const [confirmar, setConfirmar] = useState<string | null>(null); // etapa aguardando "substituir?"
  const idProduto = useIdProdutoFrases(); // frases são DESTE produto
  const { data: frases } = useFrasesTroca();
  const salvar = useSalvarFraseTroca();
  const qc = useQueryClient();
  const lista = frases ?? [];

  // Lê a seleção do editor na hora de abrir (o ProseMirror mantém a seleção mesmo sem foco).
  const capturar = () => {
    const { from, to, $from, $to } = editor.state.selection;
    if (from === to) return setSel({ from, to, frase: "", erro: "Selecione no prompt o trecho da frase para transferência e clique aqui de novo." });
    if ($from.parent !== $to.parent) return setSel({ from, to, frase: "", erro: "Selecione um trecho dentro de uma única linha." });
    const bruto: string = editor.state.doc.textBetween(from, to, "\n", "\n");
    if (temTokenTransferencia(bruto)) return setSel({ from, to, frase: "", erro: "Esse trecho já é uma frase para transferência." });
    const { frase, corteInicio, corteFim } = limparTrechoFrase(bruto);
    setSel({ from: from + corteInicio, to: to - corteFim, frase, erro: validarFrase(frase) });
  };

  const aplicar = async (etapa: string, nomePadrao: string) => {
    if (!sel || sel.erro) return;
    if (!idProduto) {
      toast.error("Salve o produto primeiro", { description: "As frases são de cada produto — salve o produto para poder marcar frases." });
      return;
    }
    const atual = lista.find((f) => f.etapa_destino === etapa);
    const dona = lista.find((f) => f.frase === sel.frase);
    if (dona && dona.etapa_destino !== etapa) {
      toast.error("Essa frase já é de outro departamento", { description: `Ela leva o lead para ${dona.nome}.` });
      return;
    }
    // Departamento já tem OUTRA frase → confirma a substituição (2º clique).
    if (atual && atual.frase !== sel.frase && confirmar !== etapa) { setConfirmar(etapa); return; }

    try {
      let r: any = null;
      if (!atual || atual.frase !== sel.frase) {
        r = await salvar.mutateAsync({ id: atual?.id ?? null, id_produto_biblioteca: idProduto, etapa_destino: etapa, frase: sel.frase, descricao: atual?.descricao ?? null });
        await qc.refetchQueries({ queryKey: frasesTrocaKey(idProduto) }); // registro atualizado antes do chip
      }
      const nome = atual?.nome ?? nomePadrao;
      editor.chain().focus().insertContentAt({ from: sel.from, to: sel.to }, "@" + rotuloFrase(nome)).run();
      setOpen(false);
      setConfirmar(null);
      toast.success(`Frase marcada → ${nome}`, {
        description: !atual
          ? "Frase para Transferência criada. Ela vai para a mensagem_troca deste departamento ao publicar."
          : atual.frase !== sel.frase
            ? `Frase substituída — ${r?.prompts_atualizados ?? 0} prompt(s) publicado(s) atualizados.`
            : "Trecho ligado à frase que já estava cadastrada.",
      });
    } catch (e: any) {
      const msg = String(e?.message ?? "");
      toast.error("Não foi possível marcar a frase", {
        description: /duplicate|unique/i.test(msg) ? "Essa frase já é usada por outro departamento." : msg,
      });
    }
  };

  return (
    <Popover open={open} onOpenChange={(v) => { if (v) capturar(); setConfirmar(null); setOpen(v); }}>
      <PopoverTrigger asChild>
        <button
          type="button"
          title="Marcar o trecho selecionado como frase para transferência (fica laranja)"
          className="h-7 px-2 rounded grid grid-flow-col items-center gap-1 text-xs font-semibold transition-colors hover:bg-[#fff7ed]"
          style={{ color: COR_TRANSFERENCIA }}
        >
          <ArrowRightLeft className="size-3.5" />Marcar frase
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 p-0 overflow-hidden">
        <div className="px-3 py-2.5 border-b border-[#eef1f5]">
          <div className="text-[10px] font-bold uppercase tracking-wider" style={{ color: COR_TRANSFERENCIA }}>Marcar frase para transferência</div>
          {sel?.frase ? (
            <p className="mt-1 text-xs text-foreground leading-snug line-clamp-3">“{sel.frase}”</p>
          ) : null}
          {sel?.erro && <p className="mt-1 text-xs text-destructive leading-snug">{sel.erro}</p>}
        </div>

        {!sel?.erro && (
          <div className="p-1">
            <div className="px-2 pt-1.5 pb-1 text-[11px] text-muted-foreground">Esta frase leva o lead para:</div>
            {ETAPAS_TROCA.map(({ etapa, nome }) => {
              const atual = lista.find((f) => f.etapa_destino === etapa);
              const mesma = atual?.frase === sel?.frase;
              const pedindo = confirmar === etapa;
              return (
                <button
                  key={etapa}
                  type="button"
                  disabled={salvar.isPending}
                  onMouseDown={(e) => { e.preventDefault(); aplicar(etapa, nome); }}
                  className={`w-full text-left rounded-lg px-2 py-1.5 text-sm transition-colors ${pedindo ? "bg-[#fff7ed]" : "hover:bg-[#f6f8fb]"}`}
                >
                  <div className="flex items-center gap-2">
                    <span className="flex-1 font-medium text-foreground">{nome}</span>
                    {salvar.isPending && pedindo && <Loader2 className="size-3.5 animate-spin" />}
                    {mesma && <span className="text-[10px] font-bold uppercase tracking-wider text-success">já é esta</span>}
                    {atual && !mesma && !pedindo && <span className="text-[10px] font-semibold text-muted-foreground">tem frase</span>}
                  </div>
                  {pedindo && atual && (
                    <p className="mt-1 text-[11px] leading-snug" style={{ color: COR_TRANSFERENCIA }}>
                      Substituir “{atual.frase}”? Os prompts publicados que usam a frase antiga serão atualizados. Clique de novo para confirmar.
                    </p>
                  )}
                </button>
              );
            })}
          </div>
        )}

        {onGerenciar && (
          <button
            type="button"
            onMouseDown={(e) => { e.preventDefault(); setOpen(false); onGerenciar(); }}
            className="w-full flex items-center gap-1.5 px-3 py-2 border-t border-[#eef1f5] text-xs font-medium text-[#475467] hover:bg-[#f6f8fb] transition-colors"
          >
            <Settings2 className="size-3.5" />Gerenciar frases para transferência
          </button>
        )}
      </PopoverContent>
    </Popover>
  );
};
