import { ResponsiveContainer, PieChart, Pie, Cell } from "recharts";
import { MessagesSquare, TrendingUp, Clock, Users, Target, RefreshCw, ArrowUp, ArrowDown, BarChart3 } from "lucide-react";
import CountUp from "@/components/ui/count-up";

export interface StatusItem {
  label: string;
  value: number;
  pct: number;
  color: string;
  icon: any;
  bg: string;
  desc: string;
}

interface Props {
  total: number;
  donutDelta: number | null;
  items: StatusItem[];
  ops: { evolucao: number | null; tempoResposta: string; conversasDia: string; taxaFinalizacao: number | null };
  onReport?: () => void;
  countKey?: any;
  atualizadoEm?: string;
  className?: string;
}

/** Painel de Saúde Operacional — Conversas por status (donut + barras + KPIs executivos). */
export function StatusPanel({ total, donutDelta, items, ops, onReport, countKey, atualizadoEm, className = "" }: Props) {
  const kpis = [
    { icon: TrendingUp, bg: "#e8f9ee", color: "#16a34a", label: "Evolução", value: ops.evolucao != null ? `${ops.evolucao >= 0 ? "+" : ""}${ops.evolucao}%` : "—", sub: "vs. anterior" },
    { icon: Clock, bg: "#eaf1ff", color: "#2563eb", label: "Resposta média", value: ops.tempoResposta, sub: "1ª resposta" },
    { icon: Users, bg: "#fff4df", color: "#d97706", label: "Conversas/dia", value: ops.conversasDia, sub: "no período" },
    { icon: Target, bg: "#e0f2fe", color: "#0891b2", label: "Finalização", value: ops.taxaFinalizacao != null ? `${ops.taxaFinalizacao}%` : "—", sub: "encerradas" },
  ];

  return (
    <div className={`lc-card lc-metric relative overflow-hidden p-5 flex flex-col ${className}`}>
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-2.5 min-w-0">
          <div className="size-9 rounded-xl grid place-items-center shrink-0" style={{ background: "#e8f9ee", color: "#00bc33" }}><MessagesSquare className="size-[18px]" /></div>
          <div className="min-w-0">
            <h3 className="font-bold text-[15px] tracking-tight text-[#101828] truncate">Conversas por status</h3>
            <p className="text-[12px] text-[#667085] mt-0.5 truncate">Distribuição no período.</p>
          </div>
        </div>
        {onReport && (
          <button onClick={onReport} className="lc-brilho lc-brilho--borda inline-flex items-center gap-1 h-8 px-2.5 rounded-lg border border-[#E2E8F0] bg-white text-[12px] font-semibold text-[#344054] hover:text-[#101828] hover:border-[#cbd5e1] transition-colors shrink-0">
            <BarChart3 className="size-3.5 text-[#00bc33]" /> Ver relatório
          </button>
        )}
      </div>

      {total === 0 ? (
        <div className="flex-1 grid place-items-center text-[12px] text-[#98A2B3] py-8">Nenhuma conversa no período.</div>
      ) : (
        <>
          {/* Donut + lista */}
          <div className="mt-3 grid grid-cols-1 sm:grid-cols-[132px_1fr] gap-3 items-center">
            <div className="relative size-[132px] mx-auto">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={items} dataKey="value" nameKey="label" innerRadius={48} outerRadius={64} paddingAngle={2} stroke="none" cornerRadius={3}>
                    {items.map((s, i) => <Cell key={i} fill={s.color} />)}
                  </Pie>
                </PieChart>
              </ResponsiveContainer>
              <div className="absolute inset-0 grid place-items-center pointer-events-none">
                <div className="text-center leading-none">
                  <div className="text-[22px] font-extrabold tabular-nums text-[#101828] leading-none"><CountUp key={countKey} to={total} duration={1.2} /></div>
                  <div className="text-[10px] text-[#98A2B3] mt-0.5">Total</div>
                  {donutDelta != null && (
                    <div className={`mt-1 inline-flex items-center gap-0.5 px-1.5 py-px rounded-full text-[10px] font-bold ${donutDelta >= 0 ? "bg-[#e8f9ee] text-[#16a34a]" : "bg-[#fef2f2] text-[#dc2626]"}`}>
                      {donutDelta >= 0 ? <ArrowUp className="size-2.5" /> : <ArrowDown className="size-2.5" />}{Math.abs(donutDelta)}%
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className="space-y-2.5">
              {items.map((s) => (
                <div key={s.label} className="min-w-0" title={s.desc}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-semibold text-[13px] text-[#101828] inline-flex items-center gap-1.5 min-w-0"><span className="size-2 rounded-full shrink-0" style={{ background: s.color }} /><span className="truncate">{s.label}</span></span>
                    <span className="flex items-baseline gap-1.5 shrink-0 tabular-nums"><b className="text-[13px] text-[#101828]">{s.value}</b><b className="text-[12px]" style={{ color: s.color }}>{s.pct}%</b></span>
                  </div>
                  <div className="mt-1 h-1.5 rounded-full bg-[#eef1f5] overflow-hidden"><div className="h-full rounded-full transition-all duration-700" style={{ width: `${Math.max(3, s.pct)}%`, background: s.color }} /></div>
                </div>
              ))}
            </div>
          </div>

          {/* KPIs executivos (2x2) */}
          <div className="mt-3 grid grid-cols-2 gap-2">
            {kpis.map((k) => (
              <div key={k.label} className="flex items-center gap-2 p-2 rounded-lg border border-[#eef1f5] bg-[#fafbfc]" title={k.sub}>
                <div className="size-7 rounded-lg grid place-items-center shrink-0" style={{ background: k.bg, color: k.color }}><k.icon className="size-3.5" /></div>
                <div className="min-w-0">
                  <div className="text-[14px] font-bold tracking-tight tabular-nums leading-none" style={{ color: k.color }}>{k.value}</div>
                  <div className="text-[10px] text-[#667085] truncate mt-0.5">{k.label}</div>
                </div>
              </div>
            ))}
          </div>

          <div className="mt-2.5 flex items-center justify-center gap-1.5 text-[11px] text-[#98A2B3]">
            <RefreshCw className="size-3" /> {atualizadoEm ?? "Atualizado há poucos segundos"}
          </div>
        </>
      )}
    </div>
  );
}
