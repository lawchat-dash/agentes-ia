import { History } from "lucide-react";
import { quando, type Agente } from "../api";
import { Carregando, Vazio, useCarregar } from "../componentes/ui";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";

interface Alteracao { id: string; id_registro: string; acao: string; resumo: string; usuario: string; criado_em: string }

/** Quem mudou o quê neste agente (o agente e as etapas dele), mais recente primeiro. */
export function HistoricoDoAgente({ agente }: { agente: Pick<Agente, "id" | "etapas"> }) {
  const { dados, erro } = useCarregar<Alteracao[]>("/alteracoes");
  if (!dados) return <Carregando erro={erro} />;
  const ids = new Set([agente.id, ...(agente.etapas ?? []).map((e) => e.id)]);
  const doAgente = dados.filter((h) => ids.has(h.id_registro));
  return (
    <div className="lst">
      {doAgente.length === 0 ? <Vazio>Nenhuma alteração registrada.</Vazio> : (
        <table>
          <thead><tr><th>Quando</th><th>Quem</th><th>O quê</th></tr></thead>
          <tbody>{doAgente.map((h) => (
            <tr key={h.id}><td className="s num">{quando(h.criado_em)}</td><td>{h.usuario ?? "sistema"}</td><td>{h.resumo}</td></tr>
          ))}</tbody>
        </table>
      )}
    </div>
  );
}

/** Só carrega o agente (para saber as etapas) quando o popup abre. */
function CorpoDoPopup({ idAgente }: { idAgente: string }) {
  const { dados: agente, erro } = useCarregar<Agente>(`/agentes/${idAgente}`, [idAgente]);
  if (!agente) return <Carregando erro={erro} />;
  return <HistoricoDoAgente agente={agente} />;
}

/** Popup do histórico de alterações de um agente, aberto direto da lista de agentes. */
export function PopupHistoricoAgente({ idAgente, nome, aberto, aoFechar }: { idAgente: string | null; nome?: string; aberto: boolean; aoFechar: () => void }) {
  return (
    <Dialog open={aberto} onOpenChange={(v) => { if (!v) aoFechar(); }}>
      <DialogContent className="max-w-2xl max-h-[85vh] flex flex-col gap-0 p-0 overflow-hidden">
        <DialogHeader className="p-6 pb-3 text-left space-y-1">
          <DialogTitle className="flex items-center gap-2"><History className="size-5 text-slate-500" />Histórico{nome ? ` · ${nome}` : ""}</DialogTitle>
          <DialogDescription>Cada alteração neste agente, com quem fez e quando.</DialogDescription>
        </DialogHeader>
        <div className="px-6 pb-6 overflow-y-auto">{aberto && idAgente && <CorpoDoPopup idAgente={idAgente} />}</div>
      </DialogContent>
    </Dialog>
  );
}
