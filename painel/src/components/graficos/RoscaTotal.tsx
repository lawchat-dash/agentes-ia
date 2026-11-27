/*
 * RoscaTotal: rosca com o total no centro. Passar o mouse (ou focar com Tab) numa fatia troca o centro pelo valor,
 * nome e % daquela fatia. As fatias se desenham ao montar e o total conta do zero. Legenda opcional, sincronizada.
 * Pode ser controlada por fora (ativo / aoMudarAtivo) para sincronizar com uma legenda própria da tela.
 */
import { useState, type ReactNode } from "react";
import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { PALETA_VERDE, fmtPadrao, useContagem } from "./comum";
import "./graficos.css";

export interface Fatia { chave?: string; rotulo: string; valor: number; cor?: string; extra?: ReactNode }

function Total({ v, formatar }: { v: number; formatar: (v: number) => string }) {
  return <>{formatar(useContagem(v, 1100))}</>;
}

export default function RoscaTotal({
  fatias, rotuloTotal = "total", formatar = fmtPadrao, tamanho = 200, espessura = 22, legenda = false, ativo: ativoFora, aoMudarAtivo,
  rotuloAria, className,
}: {
  fatias: Fatia[]; rotuloTotal?: string; formatar?: (v: number) => string; tamanho?: number; espessura?: number; legenda?: boolean;
  ativo?: number | null; aoMudarAtivo?: (i: number | null) => void; rotuloAria?: string; className?: string;
}) {
  const [ativoDentro, setAtivoDentro] = useState<number | null>(null);
  const ativo = ativoFora !== undefined ? ativoFora : ativoDentro;
  const mudar = (i: number | null) => { setAtivoDentro(i); aoMudarAtivo?.(i); };
  const comCor = fatias.map((f, i) => ({ ...f, cor: f.cor ?? PALETA_VERDE[i % PALETA_VERDE.length] }));
  const total = comCor.reduce((s, f) => s + Math.max(0, f.valor), 0);
  const vis = 120, R = (vis - espessura * (vis / tamanho)) / 2 - 4, C = 2 * Math.PI * R;
  const traco = espessura * (vis / tamanho);
  const visiveis = comCor.filter((f) => f.valor > 0).length;
  const folga = visiveis > 1 ? Math.min(2.2, C * 0.012) : 0;
  let acum = 0;
  const segs = comCor.map((f, i) => {
    const frac = total ? Math.max(0, f.valor) / total : 0;
    const seg = Math.max(0, frac * C - folga), rot = (acum / (total || 1)) * 360;
    acum += Math.max(0, f.valor);
    return { ...f, i, seg, rot, frac };
  }).filter((s) => s.valor > 0);
  const f = ativo != null ? comCor[ativo] : null;

  return (
    <div className={cn("flex flex-wrap items-center justify-center gap-6", className)}>
      <div className="relative shrink-0" style={{ width: tamanho, height: tamanho }}>
        <motion.svg viewBox={`0 0 ${vis} ${vis}`} className="h-full w-full overflow-visible" role="img"
          aria-label={rotuloAria ?? `${formatar(total)} ${rotuloTotal}: ${comCor.map((x) => `${x.rotulo} ${formatar(x.valor)}`).join(", ")}`}
          initial={{ rotate: -200, scale: 0.88, opacity: 0 }} animate={{ rotate: -90, scale: 1, opacity: 1 }} transition={{ duration: 1, ease: [0.16, 1, 0.3, 1] }}>
          <circle cx={vis / 2} cy={vis / 2} r={R} fill="none" stroke="#f1f5f9" strokeWidth={traco} />
          {segs.map((s, n) => {
            const on = ativo === s.i, apagado = ativo != null && !on;
            return (
              <motion.circle key={s.chave ?? s.rotulo} cx={vis / 2} cy={vis / 2} r={R} fill="none" stroke={s.cor}
                strokeWidth={on ? traco + 5 : traco} strokeLinecap="butt" strokeDasharray={`${s.seg} ${C}`} transform={`rotate(${s.rot} ${vis / 2} ${vis / 2})`}
                initial={{ strokeDashoffset: s.seg }} animate={{ strokeDashoffset: 0, opacity: apagado ? 0.35 : 1 }}
                transition={{ strokeDashoffset: { duration: 0.9, delay: 0.2 + n * 0.1, ease: "easeOut" }, opacity: { duration: 0.2 } }}
                style={{ cursor: "pointer", transition: "stroke-width .2s ease", outline: "none" }} tabIndex={0} role="button"
                aria-label={`${s.rotulo}: ${formatar(s.valor)} (${Math.round(s.frac * 100)}%)`}
                onPointerEnter={() => mudar(s.i)} onPointerLeave={() => mudar(null)} onFocus={() => mudar(s.i)} onBlur={() => mudar(null)} />
            );
          })}
        </motion.svg>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center px-6 text-center" aria-live="polite">
          {f ? (
            <motion.div key={`f-${ativo}`} initial={{ opacity: 0, scale: 0.92 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.18 }}>
              <span className="block max-w-[9rem] truncate text-[11px] font-semibold" style={{ color: f.cor }}>{f.rotulo}</span>
              <span className="block text-2xl font-extrabold leading-tight tabular-nums text-[#101828]">{formatar(f.valor)}</span>
              <span className="block text-[11px] text-slate-500">{total ? Math.round((f.valor / total) * 1000) / 10 : 0}% do total</span>
            </motion.div>
          ) : (
            <motion.div key="total" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.18 }}>
              <span className="block text-[11px] text-slate-500">Total</span>
              <span className="block text-3xl font-extrabold leading-tight tabular-nums text-[#101828]"><Total v={total} formatar={formatar} /></span>
              <span className="block text-[11px] text-slate-500">{rotuloTotal}</span>
            </motion.div>
          )}
        </div>
      </div>
      {legenda && (
        <ul className="min-w-[160px] flex-1 space-y-1">
          {comCor.map((x, i) => (
            <li key={x.chave ?? x.rotulo}>
              <button type="button" onPointerEnter={() => mudar(i)} onPointerLeave={() => mudar(null)} onFocus={() => mudar(i)} onBlur={() => mudar(null)}
                className={cn("flex w-full items-center gap-2.5 rounded-lg px-2 py-1 text-left transition-colors", ativo === i ? "bg-[#e3f7e8]/70" : "hover:bg-slate-50")}>
                <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: x.cor }} />
                <span className="flex-1 truncate text-xs text-[#101828]">{x.rotulo}{x.extra}</span>
                <span className="text-xs font-semibold tabular-nums text-[#101828]">{formatar(x.valor)}</span>
                <span className="w-11 text-right text-[10px] tabular-nums text-slate-500">{total ? `${Math.round((x.valor / total) * 1000) / 10}%` : "0%"}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
