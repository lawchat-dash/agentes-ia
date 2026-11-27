/*
 * MedidorMeta: anel de progresso até uma meta (ou até 100% numa taxa). O anel enche ao montar e o número conta
 * do zero. Opcional: um tracinho de referência no anel (ex.: o valor do período anterior).
 */
import { useId, type ReactNode } from "react";
import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { VERDE, VERDE_ESCURO, useContagem } from "./comum";
import "./graficos.css";

const fmtPctPadrao = (v: number) => `${v.toLocaleString("pt-BR", { maximumFractionDigits: 1, minimumFractionDigits: v < 10 && v % 1 ? 1 : 0 })}%`;

export default function MedidorMeta({
  rotulo, valor, meta = 100, formatar = fmtPctPadrao, sub, referencia, cor = VERDE, corFim = VERDE_ESCURO, tamanho = 132, espessura = 12,
  atraso = 0, className,
}: {
  rotulo: ReactNode; valor: number | null;
  /** Valor que enche o anel (100 numa taxa em %). */
  meta?: number; formatar?: (v: number) => string; sub?: ReactNode;
  /** Tracinho no anel, ex.: { valor: 12.5, rotulo: "antes" }. */
  referencia?: { valor: number; rotulo: string } | null;
  cor?: string; corFim?: string; tamanho?: number; espessura?: number; atraso?: number; className?: string;
}) {
  const gid = useId().replace(/:/g, "");
  const v = valor ?? 0;
  const mostrado = useContagem(v, 1200);
  const frac = meta > 0 ? Math.max(0, Math.min(1, v / meta)) : 0;
  const s = tamanho, r = (s - espessura) / 2 - 2, C = 2 * Math.PI * r;
  const ref = referencia && meta > 0 ? Math.max(0, Math.min(1, referencia.valor / meta)) : null;
  const ang = ref != null ? ref * 2 * Math.PI - Math.PI / 2 : 0;
  const bateu = meta !== 100 && v >= meta;
  return (
    <div className={cn("lc-g-medidor flex flex-col items-center text-center", className)}>
      <div className="relative" style={{ width: s, height: s }}>
        <svg width={s} height={s} viewBox={`0 0 ${s} ${s}`} role="img"
          aria-label={`${typeof rotulo === "string" ? rotulo : ""}: ${valor == null ? "sem dados" : formatar(v)}${meta !== 100 ? ` de ${formatar(meta)}` : ""}`}>
          <defs>
            <linearGradient id={gid} x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stopColor={cor} /><stop offset="100%" stopColor={corFim} /></linearGradient>
          </defs>
          <circle cx={s / 2} cy={s / 2} r={r} fill="none" stroke="#eef2f6" strokeWidth={espessura} />
          <motion.circle cx={s / 2} cy={s / 2} r={r} fill="none" stroke={`url(#${gid})`} strokeWidth={espessura} strokeLinecap="round"
            strokeDasharray={C} transform={`rotate(-90 ${s / 2} ${s / 2})`}
            initial={{ strokeDashoffset: C }} animate={{ strokeDashoffset: C * (1 - frac) }}
            transition={{ duration: 1.3, delay: atraso, ease: [0.16, 1, 0.3, 1] }}
            style={{ filter: `drop-shadow(0 4px 8px ${cor}40)` }} />
          {ref != null && (
            <line x1={s / 2 + (r - espessura / 2 - 3) * Math.cos(ang)} y1={s / 2 + (r - espessura / 2 - 3) * Math.sin(ang)}
              x2={s / 2 + (r + espessura / 2 + 3) * Math.cos(ang)} y2={s / 2 + (r + espessura / 2 + 3) * Math.sin(ang)}
              stroke="#101828" strokeOpacity={0.55} strokeWidth={2} strokeLinecap="round">
              <title>{`${referencia!.rotulo}: ${formatar(referencia!.valor)}`}</title>
            </line>
          )}
        </svg>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-2xl font-extrabold leading-none tracking-tight tabular-nums text-[#101828]">{valor == null ? "–" : formatar(mostrado)}</span>
          {meta !== 100 && <span className="mt-1 text-[10px] text-slate-500">meta {formatar(meta)}</span>}
          {bateu && <span className="mt-1 rounded-full bg-[#e3f7e8] px-1.5 py-0.5 text-[9px] font-bold text-[#00a32c]">meta batida</span>}
        </div>
      </div>
      <div className="mt-2.5 text-xs font-semibold text-[#101828]">{rotulo}</div>
      {(sub || referencia) && (
        <div className="mt-0.5 text-[11px] leading-snug text-slate-500">
          {sub}{sub && referencia ? " · " : ""}{referencia && <>{referencia.rotulo} {formatar(referencia.valor)}</>}
        </div>
      )}
    </div>
  );
}
