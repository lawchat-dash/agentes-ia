import { Link } from "react-router-dom";
import { Activity, RefreshCw, ChevronRight, List } from "lucide-react";

export interface ActivityItem {
  id: string;
  icon: any;
  bg: string;
  color: string;
  dot: string;
  title: string;
  who: string;
  channel: string;
  extra?: string;
  time: string;
  badge?: string | null;
  action?: string | null;
  to?: string | null;
}

interface Props {
  items: ActivityItem[];
  onRefresh?: () => void;
  atualizando?: boolean;
  verTodas?: string | null;
  className?: string;
}

/** Central de Eventos — timeline vertical das atividades recentes. */
export function ActivityFeed({ items, onRefresh, atualizando, verTodas, className = "" }: Props) {
  return (
    <div className={`lc-card lc-metric relative overflow-hidden p-5 flex flex-col ${className}`}>
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-2.5">
          <div className="size-9 rounded-xl grid place-items-center shrink-0" style={{ background: "#e8f9ee", color: "#00bc33" }}><Activity className="size-[18px]" /></div>
          <div>
            <h3 className="font-bold text-[16px] tracking-tight text-[#101828]">Atividades recentes</h3>
            <p className="text-[12px] text-[#667085] mt-0.5">Acompanhe o que está acontecendo agora.</p>
          </div>
        </div>
        {onRefresh && (
          <button onClick={onRefresh} disabled={atualizando} className="lc-brilho lc-brilho--borda inline-flex items-center gap-1.5 h-9 px-3 rounded-xl border border-[#E2E8F0] bg-white text-[12px] font-semibold text-[#344054] hover:text-[#101828] hover:border-[#cbd5e1] transition-colors shrink-0 disabled:opacity-60">
            <RefreshCw className={`size-3.5 ${atualizando ? "animate-spin" : ""}`} /> Atualizar <span className="size-1.5 rounded-full bg-[#22c55e]" />
          </button>
        )}
      </div>

      {/* Timeline */}
      {items.length === 0 ? (
        <div className="flex-1 grid place-items-center text-center py-8">
          <div>
            <div className="text-[13px] font-semibold text-[#344054]">Nenhuma atividade recente</div>
            <div className="text-[12px] text-[#98A2B3] mt-1">Sua operação está tranquila neste momento.</div>
          </div>
        </div>
      ) : (
        <div className="relative mt-2 flex-1">
          <span className="absolute left-[17px] top-2 bottom-2 w-px bg-[#eef1f5]" />
          {items.map((a) => (
            <div key={a.id} className="relative pl-8 py-2 border-b border-dashed border-[#eef1f5] last:border-0 group">
              {/* dot da timeline */}
              <span className="absolute left-[13px] top-[16px] size-2.5 rounded-full ring-4 ring-white" style={{ background: a.dot }} />
              <div className="flex items-start gap-2.5 -mx-2 px-2 py-1 rounded-lg transition-all group-hover:translate-x-1 group-hover:bg-[rgba(0,188,51,.04)]">
                <div className="size-9 rounded-lg grid place-items-center shrink-0 transition-transform group-hover:scale-105" style={{ background: a.bg, color: a.color }}><a.icon className="size-4" /></div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="font-bold text-[14px] leading-tight text-[#101828] line-clamp-2">{a.title}</span>
                    {a.badge && <span className="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wide bg-[#e8f9ee] text-[#16a34a] shrink-0">{a.badge}</span>}
                  </div>
                  <div className="text-[12px] text-[#667085] mt-0.5 truncate">{a.who} • {a.channel}</div>
                  {a.extra && <div className="text-[11px] text-[#98A2B3] mt-0.5 truncate">{a.extra}</div>}
                </div>
                <div className="flex flex-col items-end gap-1.5 shrink-0">
                  <span className="text-[11px] inline-flex items-center gap-1 whitespace-nowrap" style={{ color: a.color }}>{a.time} <span className="size-1.5 rounded-full" style={{ background: a.dot }} /></span>
                  {a.action && a.to && (
                    <Link to={a.to} className="inline-flex items-center gap-0.5 text-[11px] font-bold transition-colors" style={{ color: a.color }}>{a.action} <ChevronRight className="size-3" /></Link>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {verTodas && (
        <Link to={verTodas} className="lc-brilho lc-brilho--borda mt-3 inline-flex items-center justify-center gap-2 h-10 rounded-xl border border-[#E2E8F0] bg-white text-[12px] font-semibold text-[#344054] hover:text-[#101828] hover:border-[#cbd5e1] transition-colors">
          <List className="size-4 text-[#98A2B3]" /> Ver agentes <ChevronRight className="size-3.5" />
        </Link>
      )}
    </div>
  );
}
