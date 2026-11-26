import { useMemo, useState } from "react";
import { MapPin, ChevronRight, ChevronUp } from "lucide-react";
import brazilMap from "@/data/brazilMap";

interface Props {
  leads: Record<string, number>;
  contratos: Record<string, number>;
  className?: string;
}

const fmt = (n: number) => Math.round(n).toLocaleString("pt-BR");
const hexToRgb = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const lerp = (a: number, b: number, t: number) => Math.round(a + (b - a) * t);
const LOW = hexToRgb("#d6f5e0");
const HIGH = hexToRgb("#009926");
function shade(t: number) {
  const f = Math.pow(Math.max(0, Math.min(1, t)), 0.6);
  return `rgb(${lerp(LOW[0], HIGH[0], f)},${lerp(LOW[1], HIGH[1], f)},${lerp(LOW[2], HIGH[2], f)})`;
}

/** Contatos por Estado — mapa choropleth do Brasil + ranking + toggle Leads/Contratos (UF pelo DDD do telefone). */
export function ContatosPorEstado({ leads, contratos, className = "" }: Props) {
  const [tab, setTab] = useState<"leads" | "contratos">("leads");
  const [todos, setTodos] = useState(false);

  const values = tab === "leads" ? leads : contratos;

  const total = useMemo(() => Object.values(values).reduce((s, v) => s + v, 0), [values]);
  const max = useMemo(() => Math.max(1, ...Object.values(values)), [values]);
  const comValor = useMemo(() => Object.entries(values).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]), [values]);
  const ranking = todos ? comValor : comValor.slice(0, 5);
  const nomePorUf = useMemo(() => {
    const m: Record<string, string> = {};
    (brazilMap as any).locations.forEach((l: any) => (m[l.id] = l.name));
    return m;
  }, []);

  return (
    <div className={`lc-card lc-metric relative overflow-hidden p-5 flex flex-col ${className}`}>
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-2.5">
          <div className="size-9 rounded-xl grid place-items-center shrink-0" style={{ background: "#e8f9ee", color: "#00bc33" }}><MapPin className="size-[18px]" /></div>
          <div>
            <h3 className="font-bold text-[16px] tracking-tight text-[#101828]">Contatos por Estado</h3>
            <p className="text-[12px] text-[#667085] mt-0.5">Distribuição geográfica pelo DDD do telefone.</p>
          </div>
        </div>
        <span className="text-[11px] font-bold px-2 py-1 rounded-lg bg-[#e8f9ee] text-[#16a34a] shrink-0 tabular-nums">{fmt(total)} {tab}</span>
      </div>

      {/* Toggle */}
      <div className="mt-3 inline-flex p-0.5 rounded-xl bg-[#f1f5f9] self-start">
        {(["leads", "contratos"] as const).map((t) => (
          <button key={t} onClick={() => { setTab(t); setTodos(false); }}
            className={`px-3 h-8 rounded-lg text-[12px] font-semibold capitalize transition-all ${tab === t ? "bg-white text-[#101828] shadow-sm" : "text-[#667085] hover:text-[#101828]"}`}>
            {t === "leads" ? "Leads por Estado" : "Contratos por Estado"}
          </button>
        ))}
      </div>

      {total === 0 ? (
        <div className="flex-1 grid place-items-center text-center py-8">
          <div>
            <MapPin className="size-7 text-[#cbd5e1] mx-auto" />
            <div className="text-[13px] font-semibold text-[#344054] mt-2">Sem dados de localização</div>
            <div className="text-[12px] text-[#98A2B3] mt-1">
              {tab === "leads" ? "Nenhum lead com DDD brasileiro no período." : "Nenhum contrato assinado no período."}
            </div>
          </div>
        </div>
      ) : (
        <>
          {/* Mapa */}
          <div className="mt-3 grid place-items-center">
            <svg viewBox={(brazilMap as any).viewBox} className="w-full h-auto max-h-[230px]" role="img" aria-label="Mapa de contatos por estado">
              {(brazilMap as any).locations.map((loc: any) => {
                const val = values[loc.id] ?? 0;
                return (
                  <path key={loc.id} d={loc.path} fill={val > 0 ? shade(val / max) : "#eef1f5"} stroke="#fff" strokeWidth={0.6}
                    className="transition-[fill,opacity] duration-300 hover:opacity-75">
                    <title>{loc.name}: {fmt(val)} {tab}</title>
                  </path>
                );
              })}
            </svg>
          </div>

          {/* Ranking */}
          <div className={`mt-3 space-y-2.5 ${todos ? "max-h-[260px] overflow-y-auto pr-1" : ""}`}>
            {ranking.map(([uf, val]) => {
              const pct = total > 0 ? (val / total) * 100 : 0;
              return (
                <div key={uf} className="flex items-center gap-2.5">
                  <span className="size-7 rounded-lg grid place-items-center text-[11px] font-bold shrink-0" style={{ background: "#e8f9ee", color: "#009926" }}>{uf.toUpperCase()}</span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between text-[12px] mb-1">
                      <span className="font-medium text-[#344054] truncate">{nomePorUf[uf] ?? uf.toUpperCase()}</span>
                      <span className="tabular-nums shrink-0 ml-2"><b className="text-[#101828]">{fmt(val)}</b><span className="text-[#98A2B3]"> · {pct.toFixed(1).replace(".", ",")}%</span></span>
                    </div>
                    <div className="h-1.5 rounded-full bg-[#eef1f5] overflow-hidden"><div className="h-full rounded-full transition-all duration-700" style={{ width: `${Math.max(4, (val / max) * 100)}%`, background: "linear-gradient(90deg,#00bc33,#73e793)" }} /></div>
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}

      {comValor.length > 5 && (
        <button onClick={() => setTodos(!todos)} className="mt-auto pt-3 inline-flex items-center justify-center gap-1 h-10 rounded-xl border border-[#E2E8F0] bg-white text-[12px] font-semibold text-[#344054] hover:text-[#101828] hover:border-[#cbd5e1] transition-colors">
          {todos ? <>Mostrar só os 5 maiores <ChevronUp className="size-3.5" /></> : <>Ver todos os estados ({comValor.length}) <ChevronRight className="size-3.5" /></>}
        </button>
      )}
    </div>
  );
}
