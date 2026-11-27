/*
 * BarrasTendencia: barras por dia (uma ou mais camadas empilhadas) com a linha de tendência suave por cima
 * (média móvel do total). As barras sobem ao montar e a linha se desenha depois. Passar o mouse numa barra
 * mostra o balão do dia. Teclado: Tab até o gráfico e setas ← →.
 */
import { useId, useMemo, useState, type KeyboardEvent, type PointerEvent } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { TINTA, VERDE, caminhoSuave, fmtPadrao, indicePorX, mediaMovel, useLargura, useMenosMovimento } from "./comum";
import "./graficos.css";

export interface DiaBarras { rotulo: string; rotuloLongo?: string; valores: number[] }
export interface Camada { rotulo: string; cor: string }

export default function BarrasTendencia({
  dados, camadas = [{ rotulo: "Total", cor: VERDE }], janela = 7, altura = 220, formatar = fmtPadrao, corTendencia = TINTA,
  rotuloTendencia, legenda = true, rotuloAria, className,
}: {
  dados: DiaBarras[]; camadas?: Camada[]; janela?: number; altura?: number; formatar?: (v: number) => string;
  corTendencia?: string; rotuloTendencia?: string; legenda?: boolean; rotuloAria: string; className?: string;
}) {
  const [ref, w] = useLargura<HTMLDivElement>();
  const [sobre, setSobre] = useState<number | null>(null);
  const reduz = useMenosMovimento();
  const gid = useId().replace(/:/g, "");
  const pL = 34, pR = 8, pT = 12, pB = 24;
  const nomeTend = rotuloTendencia ?? `Tendência (média de ${janela} dias)`;

  const geo = useMemo(() => {
    if (!w || !dados.length) return null;
    const totais = dados.map((d) => d.valores.reduce((s, v) => s + (v || 0), 0));
    const tend = mediaMovel(totais, janela);
    const max = Math.max(1, ...totais, ...tend);
    const largura = w - pL - pR, passo = largura / dados.length;
    const bw = Math.max(2, Math.min(28, passo * 0.68));
    const cx = (i: number) => pL + passo * (i + 0.5);
    const y = (v: number) => pT + (1 - v / max) * (altura - pT - pB);
    const base = altura - pB;
    const barras = dados.map((d, i) => {
      let topo = base;
      const pedacos = d.valores.map((v, k) => {
        const h = Math.max(0, (v / max) * (altura - pT - pB));
        topo -= h;
        return { k, y: topo, h };
      });
      return { i, x: cx(i) - bw / 2, pedacos, topo };
    });
    const linhaTend = caminhoSuave(tend.map((v, i) => [cx(i), y(v)] as [number, number]));
    const yt = [0, max / 2, max].map((v) => ({ v, y: y(v) }));
    const cabem = Math.max(2, Math.floor(largura / 52));
    const cada = Math.max(1, Math.ceil(dados.length / cabem));
    return { totais, tend, cx, y, base, bw, barras, linhaTend, yt, cada, passo };
  }, [w, dados, janela, altura]);

  const mover = (e: PointerEvent<SVGSVGElement>) => {
    if (!geo) return;
    const r = e.currentTarget.getBoundingClientRect();
    setSobre(indicePorX(e.clientX - r.left, dados.length, pL + geo.passo / 2, r.width - pR - geo.passo / 2));
  };
  const tecla = (e: KeyboardEvent<HTMLDivElement>) => {
    const atual = sobre ?? dados.length - 1;
    if (e.key === "ArrowLeft") { e.preventDefault(); setSobre(Math.max(0, atual - 1)); }
    else if (e.key === "ArrowRight") { e.preventDefault(); setSobre(Math.min(dados.length - 1, atual + 1)); }
    else if (e.key === "Escape") setSobre(null);
  };
  const dia = sobre != null ? dados[sobre] : null;
  const chave = dados.map((d) => d.valores.join("+")).join(",");

  return (
    <div className={cn("lc-g-barras", className)}>
      {legenda && (
        <div className="mb-2 flex flex-wrap items-center justify-end gap-3 text-[10px] text-slate-500">
          {camadas.map((c) => <span key={c.rotulo} className="flex items-center gap-1"><span className="h-2 w-2 rounded-[3px]" style={{ background: c.cor }} />{c.rotulo}</span>)}
          <span className="flex items-center gap-1"><span className="h-[2px] w-3 rounded" style={{ background: corTendencia }} />{nomeTend}</span>
        </div>
      )}
      <div ref={ref} className="relative w-full rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-[#00bc33]/40" style={{ height: altura }}
        tabIndex={0} role="img" aria-label={rotuloAria} onKeyDown={tecla} onBlur={() => setSobre(null)}>
        {geo && (
          <svg width={w} height={altura} className="absolute inset-0 overflow-visible" style={{ touchAction: "pan-y" }}
            onPointerMove={mover} onPointerDown={mover} onPointerLeave={() => setSobre(null)} aria-hidden>
            <defs>
              {camadas.map((c, k) => (
                <linearGradient key={k} id={`${gid}-${k}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={c.cor} stopOpacity={1} /><stop offset="100%" stopColor={c.cor} stopOpacity={0.72} />
                </linearGradient>
              ))}
            </defs>
            {geo.yt.map((t, i) => (
              <g key={i}>
                <line x1={pL} x2={w - pR} y1={t.y} y2={t.y} stroke="#e5e7eb" strokeDasharray={i === 0 ? undefined : "3 4"} />
                <text x={pL - 6} y={t.y + 3} textAnchor="end" fill="#94a3b8" style={{ fontSize: 9 }}>{formatar(t.v)}</text>
              </g>
            ))}
            {sobre != null && (
              <rect x={geo.cx(sobre) - geo.passo / 2} y={pT} width={geo.passo} height={geo.base - pT} rx={6} fill="#00bc33" opacity={0.07} />
            )}
            {geo.barras.map((b) => {
              const apagada = sobre != null && sobre !== b.i;
              return (
                <motion.g key={`${chave}-${b.i}`} style={{ originX: 0.5, originY: 1 }}
                  initial={reduz ? false : { scaleY: 0 }} animate={{ scaleY: 1, opacity: apagada ? 0.45 : 1 }}
                  transition={{ scaleY: { duration: 0.6, delay: Math.min(0.9, b.i * 0.018), ease: [0.16, 1, 0.3, 1] }, opacity: { duration: 0.15 } }}>
                  {b.pedacos.map((p, k) => p.h > 0 && (
                    <rect key={k} x={b.x} y={p.y} width={geo.bw} height={p.h} fill={`url(#${gid}-${p.k})`}
                      rx={k === b.pedacos.length - 1 || b.pedacos.slice(k + 1).every((q) => q.h === 0) ? Math.min(4, geo.bw / 3) : 0} />
                  ))}
                </motion.g>
              );
            })}
            <motion.path key={`t-${chave}`} d={geo.linhaTend} fill="none" stroke={corTendencia} strokeWidth={2.2} strokeLinecap="round" strokeOpacity={0.85}
              initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 1.2, delay: 0.5, ease: "easeInOut" }} />
            {sobre != null && (
              <circle cx={geo.cx(sobre)} cy={geo.y(geo.tend[sobre])} r={4} fill="#fff" stroke={corTendencia} strokeWidth={2} className="pointer-events-none" />
            )}
            {dados.map((d, i) => i % geo.cada === 0 && (
              <text key={i} x={geo.cx(i)} y={altura - 7} textAnchor="middle" fill="#94a3b8" style={{ fontSize: 9 }}>{d.rotulo}</text>
            ))}
          </svg>
        )}
        <AnimatePresence>
          {dia && geo && sobre != null && (
            <motion.div key="balao" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.12 }}
              className="pointer-events-none absolute z-10 min-w-[140px] whitespace-nowrap rounded-xl border border-slate-200/80 bg-white/95 px-3 py-2 text-[11px] shadow-lg backdrop-blur"
              style={{ left: Math.max(76, Math.min(w - 76, geo.cx(sobre))), top: Math.max(0, geo.barras[sobre].topo - 92), transform: "translateX(-50%)" }}>
              <p className="mb-1 font-semibold text-slate-700">{dia.rotuloLongo ?? dia.rotulo}</p>
              {camadas.map((c, k) => (
                <p key={k} className="flex items-center justify-between gap-4">
                  <span className="flex items-center gap-1.5 text-slate-500"><span className="h-2 w-2 rounded-[3px]" style={{ background: c.cor }} />{c.rotulo}</span>
                  <b className="tabular-nums text-[#101828]">{formatar(dia.valores[k] ?? 0)}</b>
                </p>
              ))}
              <p className="mt-0.5 flex items-center justify-between gap-4 border-t border-slate-100 pt-0.5">
                <span className="text-slate-500">Tendência</span><b className="tabular-nums text-[#101828]">{geo.tend[sobre].toLocaleString("pt-BR", { maximumFractionDigits: 1 })}</b>
              </p>
            </motion.div>
          )}
        </AnimatePresence>
        <span className="sr-only" aria-live="polite">
          {dia ? `${dia.rotuloLongo ?? dia.rotulo}: ${camadas.map((c, k) => `${c.rotulo} ${formatar(dia.valores[k] ?? 0)}`).join(", ")}` : ""}
        </span>
      </div>
    </div>
  );
}
