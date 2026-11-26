import { useState } from "react";
import { BellOff, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { enviar } from "@/api";

/** Situação do follow-up de um produto ativado (GET /produtos-ativados → followup_situacao). */
export interface FollowupSituacao { ligado: boolean; configurado: boolean; passos: number; resumo: string[] }

export const TEXTO_FOLLOWUP_DESLIGADO = "Follow-up desligado — leads que param de responder não recebem lembrete";

/** Liga o follow-up do produto com a cadência e os prompts padrão do produto da biblioteca. */
export async function ligarFollowupComPadrao(idAtivado: string): Promise<{ followup: FollowupSituacao; aviso: string | null }> {
  const r = await enviar<{ followup: FollowupSituacao; aviso: string | null }>(`/produtos-ativados/${idAtivado}/followup/ligar-padrao`, {});
  toast.success("Follow-up ligado", { description: `Cadência: ${r.followup.resumo.join(", ")}` });
  if (r.aviso) toast.warning(r.aviso);
  return r;
}

/** Aviso discreto (Meus produtos, tela do produto): só aparece quando o follow-up do produto ativo está desligado. */
export function AvisoFollowupDesligado({ idAtivado, situacao, aoLigar, className = "" }: {
  idAtivado: string; situacao: FollowupSituacao | null | undefined; aoLigar?: (s: FollowupSituacao) => void; className?: string;
}) {
  const [ocupado, setOcupado] = useState(false);
  const [ligadoAgora, setLigadoAgora] = useState(false);
  if (!situacao || situacao.ligado || ligadoAgora) return null;
  const ligar = async () => {
    setOcupado(true);
    try {
      const r = await ligarFollowupComPadrao(idAtivado);
      setLigadoAgora(true);
      aoLigar?.(r.followup);
    } catch (e) {
      toast.error((e as Error).message || "Não foi possível ligar o follow-up.");
    } finally {
      setOcupado(false);
    }
  };
  return (
    <div role="status" className={`flex flex-wrap items-center gap-2 rounded-lg border border-amber-200 bg-amber-50/70 px-2.5 py-1.5 text-[11.5px] text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-100 ${className}`}>
      <BellOff className="size-3.5 shrink-0 text-amber-600" aria-hidden />
      <span className="flex-1 min-w-[12rem]">{TEXTO_FOLLOWUP_DESLIGADO}</span>
      <button type="button" onClick={ligar} disabled={ocupado}
        className="inline-flex items-center gap-1 rounded-md border border-amber-300 bg-white px-2 py-0.5 text-[11px] font-semibold text-amber-900 hover:bg-amber-100 disabled:opacity-60 dark:bg-transparent dark:text-amber-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500">
        {ocupado && <Loader2 className="size-3 animate-spin" />}Ligar com o padrão
      </button>
    </div>
  );
}
