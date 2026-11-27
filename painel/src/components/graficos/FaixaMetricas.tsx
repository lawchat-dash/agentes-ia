/*
 * FaixaMetricas: faixa de indicadores, cada um com uma minicurva "arrastável" (passar o mouse ou arrastar o dedo
 * pela curva mostra o valor daquele dia no número grande). Teclado: Tab até a curva e setas ← →.
 * Também exporta a MiniCurva sozinha, para usar em outros cartões.
 */
import { useId, useMemo, useState, type ComponentType, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import { motion } from "framer-motion";
import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { VERDE, caminhoSuave, fmtPadrao, indicePorX, useContagem, useLargura } from "./comum";
import "./graficos.css";

export interface PontoSerie { rotulo: string; valor: number }

export interface Metrica {
  rotulo: string;
  /** Valor do período inteiro (o que aparece quando ninguém está passando o mouse). */
  valor: number | null;
  /** Série por dia para a minicurva (rótulo = dia já formatado, ex.: "12/11"). */
  serie: PontoSerie[];
  formatar?: (v: number) => string;
  /** Texto embaixo do número (ex.: "no período"). Ao arrastar, vira o rótulo do dia. */
  sub?: ReactNode;
  /** Variação % em relação ao período anterior. */
  variacao?: number | null;
  /** true quando subir é ruim (ex.: custo). */
  inverter?: boolean;
  cor?: string;
  icone?: ComponentType<{ className?: string }>;
  dica?: ReactNode;
  /** Prefixo do rótulo do dia ao arrastar (ex.: "até" para séries acumuladas). */
  prefixoDia?: string;
}

function ValorContado({ v, formatar }: { v: number; formatar: (v: number) => string }) {
  const n = useContagem(v, 1100);
  return <>{formatar(n)}</>;
}

/** Minicurva com "arrasto": avisa qual ponto está sob o cursor (ou null). */
export function MiniCurva({ serie, cor = VERDE, altura = 44, indice, aoMudar, rotuloAria, atraso = 0, formatar = fmtPadrao }: {
  serie: PontoSerie[]; cor?: string; altura?: number; indice: number | null; aoMudar: (i: number | null) => void;
  rotuloAria: string; atraso?: number; formatar?: (v: number) => string;
}) {
  const [ref, w] = useLargura<HTMLDivElement>();
  const gid = useId().replace(/:/g, "");
  const pad = 4;
  const geo = useMemo(() => {
    if (!w || !serie.length) return null;
    const vals = serie.map((p) => p.valor);
    const max = Math.max(...vals), min = Math.min(0, ...vals);
    const faixa = max - min || 1;
    const x = (i: number) => pad + (serie.length <= 1 ? (w - 2 * pad) / 2 : (i / (serie.length - 1)) * (w - 2 * pad));
    const y = (v: number) => pad + (1 - (v - min) / faixa) * (altura - 2 * pad);
    const pts = serie.map((p, i) => [x(i), y(p.valor)] as [number, number]);
    const linha = caminhoSuave(pts);
    return { x, y, pts, linha, area: `${linha} L${x(serie.length - 1)},${altura} L${x(0)},${altura} Z` };
  }, [w, serie, altura]);

  const mover = (e: PointerEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    aoMudar(indicePorX(e.clientX - r.left, serie.length, pad, r.width - pad));
  };
  const tecla = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!serie.length) return;
    const atual = indice ?? serie.length - 1;
    if (e.key === "ArrowLeft") { e.preventDefault(); aoMudar(Math.max(0, atual - 1)); }
    else if (e.key === "ArrowRight") { e.preventDefault(); aoMudar(Math.min(serie.length - 1, atual + 1)); }
    else if (e.key === "Home") { e.preventDefault(); aoMudar(0); }
    else if (e.key === "End") { e.preventDefault(); aoMudar(serie.length - 1); }
    else if (e.key === "Escape") aoMudar(null);
  };
  const p = indice != null && geo ? geo.pts[indice] : null;
  return (
    <div ref={ref} className="lc-g-curva relative w-full cursor-crosshair rounded-md outline-none focus-visible:ring-2 focus-visible:ring-[#00bc33]/40"
      style={{ height: altura, touchAction: "pan-y" }} tabIndex={serie.length ? 0 : -1} role="slider"
      aria-label={rotuloAria} aria-valuemin={0} aria-valuemax={Math.max(0, serie.length - 1)} aria-valuenow={indice ?? serie.length - 1}
      aria-valuetext={indice != null && serie[indice] ? `${serie[indice].rotulo}: ${formatar(serie[indice].valor)}` : "período inteiro"}
      onPointerMove={mover} onPointerDown={(e) => { e.currentTarget.setPointerCapture?.(e.pointerId); mover(e); }}
      onPointerLeave={() => aoMudar(null)} onPointerUp={(e) => { if (e.pointerType !== "mouse") aoMudar(null); }}
      onKeyDown={tecla} onBlur={() => aoMudar(null)}>
      {geo && (
        <svg width={w} height={altura} className="absolute inset-0 overflow-visible" aria-hidden>
          <defs>
            <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={cor} stopOpacity="0.28" /><stop offset="100%" stopColor={cor} stopOpacity="0" />
            </linearGradient>
          </defs>
          <motion.path d={geo.area} fill={`url(#${gid})`} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: atraso + 0.4, duration: 0.7 }} />
          <motion.path d={geo.linha} fill="none" stroke={cor} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"
            initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ delay: atraso, duration: 1.1, ease: [0.65, 0, 0.35, 1] }} />
          {p && (
            <g className="pointer-events-none">
              <line x1={p[0]} x2={p[0]} y1={0} y2={altura} stroke={cor} strokeOpacity={0.35} strokeDasharray="3 3" />
              <circle cx={p[0]} cy={p[1]} r={7} fill={cor} opacity={0.15} />
              <circle cx={p[0]} cy={p[1]} r={3.5} fill="#fff" stroke={cor} strokeWidth={2} />
            </g>
          )}
        </svg>
      )}
    </div>
  );
}

function ItemMetrica({ m, n }: { m: Metrica; n: number }) {
  const [indice, setIndice] = useState<number | null>(null);
  const formatar = m.formatar ?? fmtPadrao;
  const cor = m.cor ?? VERDE;
  const ponto = indice != null ? m.serie[indice] : null;
  const subiu = m.variacao != null && m.variacao > 0;
  const bom = m.variacao == null || m.variacao === 0 ? null : m.inverter ? !subiu : subiu;
  const Icone = m.icone;
  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: n * 0.06, duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
      className="lc-g-metrica group relative flex min-w-0 flex-col gap-2 p-4 md:p-5">
      <div className="flex items-center justify-between gap-2">
        <span className="flex min-w-0 items-center gap-1.5 text-xs font-semibold text-slate-600">
          {Icone && <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md" style={{ background: `${cor}1a`, color: cor }}><Icone className="h-3.5 w-3.5" /></span>}
          <span className="truncate">{m.rotulo}</span>
          {m.dica}
        </span>
        {m.variacao != null && !ponto && (
          <span className={cn("inline-flex shrink-0 items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[10px] font-bold",
            bom === null ? "bg-slate-100 text-slate-500" : bom ? "bg-[#e3f7e8] text-[#00a32c]" : "bg-red-500/10 text-red-600")}
            title="Em relação ao período anterior do mesmo tamanho">
            {subiu ? <ArrowUpRight className="h-3 w-3" /> : m.variacao < 0 ? <ArrowDownRight className="h-3 w-3" /> : null}
            {m.variacao > 0 ? "+" : ""}{m.variacao}%
          </span>
        )}
      </div>
      <div aria-live="polite">
        <div className="text-[26px] font-extrabold leading-none tracking-tight tabular-nums text-[#101828]">
          {ponto ? formatar(ponto.valor) : m.valor == null ? "–" : <ValorContado v={m.valor} formatar={formatar} />}
        </div>
        <p className="mt-1 h-4 truncate text-[11px] text-slate-500">
          {ponto ? <span className="font-semibold" style={{ color: cor }}>{m.prefixoDia ? `${m.prefixoDia} ` : ""}{ponto.rotulo}</span> : m.sub}
        </p>
      </div>
      {m.serie.length > 1
        ? <MiniCurva serie={m.serie} cor={cor} indice={indice} aoMudar={setIndice} atraso={0.15 + n * 0.06} formatar={formatar} rotuloAria={`${m.rotulo} por dia. Use as setas para ver cada dia.`} />
        : <div className="h-11" />}
    </motion.div>
  );
}

/** Faixa de métricas lado a lado (quebra em 2 colunas no celular). */
export default function FaixaMetricas({ metricas, className }: { metricas: Metrica[]; className?: string }) {
  const colunas = metricas.length >= 4 ? "lg:grid-cols-4" : metricas.length === 3 ? "lg:grid-cols-3" : "lg:grid-cols-2";
  return (
    <div className={cn("lc-g-faixa grid grid-cols-1 overflow-hidden rounded-2xl border border-white/70 bg-white shadow-[0_1px_3px_rgba(15,23,42,0.06),0_8px_24px_-12px_rgba(15,23,42,0.10)] sm:grid-cols-2", colunas, className)}>
      {metricas.map((m, n) => <ItemMetrica key={m.rotulo} m={m} n={n} />)}
    </div>
  );
}
