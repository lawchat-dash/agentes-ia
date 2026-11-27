/*
 * AreaCruz: gráfico de área (ou linha) com mira: linha vertical + ponto + balão que seguem o mouse (ou o dedo).
 * A curva se desenha ao montar. Teclado: Tab até o gráfico e setas ← →. Opcional: linha tracejada de média
 * móvel e destaque pulsante no maior valor.
 */
import { useId, useMemo, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { VERDE, caminhoSuave, fmtPadrao, indicePorX, useLargura } from "./comum";
import "./graficos.css";

export interface PontoArea {
  /** Rótulo curto no eixo (ex.: "12/11"). */
  rotulo: string;
  /** Rótulo do balão (ex.: "12 de novembro"). Sem ele, usa o curto. */
  rotuloLongo?: string;
  valor: number;
}

export default function AreaCruz({
  dados, cor = VERDE, altura = 300, formatar = fmtPadrao, formatarEixo, tipo = "area", media, destacarMaior = true,
  unidade, extraBalao, rotuloAria, className,
}: {
  dados: PontoArea[]; cor?: string; altura?: number; formatar?: (v: number) => string; formatarEixo?: (v: number) => string;
  tipo?: "area" | "linha"; media?: number[]; destacarMaior?: boolean; unidade?: string;
  /** Linha extra no balão (ex.: comparação com a média). */
  extraBalao?: (i: number) => ReactNode;
  rotuloAria: string; className?: string;
}) {
  const [ref, w] = useLargura<HTMLDivElement>();
  const [sobre, setSobre] = useState<number | null>(null);
  const gid = useId().replace(/:/g, "");
  const pL = 44, pR = 12, pT = 14, pB = 26;
  const chaveDesenho = dados.map((p) => p.valor).join(",") + tipo;

  const geo = useMemo(() => {
    if (!w || !dados.length) return null;
    const max = Math.max(...dados.map((p) => p.valor), ...(media ?? []), 0) || 1;
    const x = (i: number) => pL + (dados.length <= 1 ? (w - pL - pR) / 2 : (i / (dados.length - 1)) * (w - pL - pR));
    const y = (v: number) => pT + (1 - v / max) * (altura - pT - pB);
    const pts = dados.map((p, i) => [x(i), y(p.valor)] as [number, number]);
    const linha = caminhoSuave(pts);
    const area = `${linha} L${x(dados.length - 1)},${altura - pB} L${x(0)},${altura - pB} Z`;
    const linhaMedia = media?.length === dados.length ? caminhoSuave(media.map((v, i) => [x(i), y(v)] as [number, number])) : null;
    const yt = [0, max / 2, max].map((v) => ({ v, y: y(v) }));
    const cabem = Math.max(2, Math.floor((w - pL - pR) / 56));
    const cada = Math.max(1, Math.ceil(dados.length / cabem));
    const xt = dados.map((p, i) => ({ i, t: p.rotulo })).filter((_, i) => i % cada === 0);
    let iMax = -1;
    dados.forEach((p, i) => { if (p.valor > 0 && (iMax < 0 || p.valor > dados[iMax].valor)) iMax = i; });
    return { x, y, pts, linha, area, linhaMedia, yt, xt, iMax };
  }, [w, dados, media, altura]);

  const mover = (e: PointerEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    setSobre(indicePorX(e.clientX - r.left, dados.length, pL, r.width - pR));
  };
  const tecla = (e: KeyboardEvent<HTMLDivElement>) => {
    const atual = sobre ?? dados.length - 1;
    if (e.key === "ArrowLeft") { e.preventDefault(); setSobre(Math.max(0, atual - 1)); }
    else if (e.key === "ArrowRight") { e.preventDefault(); setSobre(Math.min(dados.length - 1, atual + 1)); }
    else if (e.key === "Escape") setSobre(null);
  };
  const fmtEixo = formatarEixo ?? formatar;
  const p = sobre != null ? dados[sobre] : null;
  const pos = sobre != null && geo ? geo.pts[sobre] : null;

  return (
    <div ref={ref} className={cn("lc-g-area relative w-full rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-[#00bc33]/40", className)}
      style={{ height: altura }} tabIndex={0} role="img" aria-label={rotuloAria} onKeyDown={tecla} onBlur={() => setSobre(null)}>
      {geo && (
        <svg width={w} height={altura} className="absolute inset-0 cursor-crosshair overflow-visible" style={{ touchAction: "pan-y" }}
          onPointerMove={mover} onPointerDown={mover} onPointerLeave={() => setSobre(null)} aria-hidden>
          <defs>
            <linearGradient id={`${gid}-a`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={cor} stopOpacity="0.30" /><stop offset="100%" stopColor={cor} stopOpacity="0" />
            </linearGradient>
          </defs>
          {geo.yt.map((t, i) => (
            <g key={i}>
              <line x1={pL} x2={w - pR} y1={t.y} y2={t.y} stroke="#e5e7eb" strokeDasharray={i === 0 ? undefined : "3 4"} />
              <text x={pL - 8} y={t.y + 3} textAnchor="end" fill="#94a3b8" style={{ fontSize: 10 }}>{fmtEixo(t.v)}</text>
            </g>
          ))}
          {geo.xt.map((t) => (
            <text key={t.i} x={geo.x(t.i)} y={altura - 7} textAnchor="middle" fill="#94a3b8" style={{ fontSize: 10 }}>{t.t}</text>
          ))}
          {tipo === "area" && (
            <motion.path key={`a-${chaveDesenho}`} d={geo.area} fill={`url(#${gid}-a)`} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.3, duration: 0.8 }} />
          )}
          {geo.linhaMedia && (
            <motion.path key={`m-${chaveDesenho}`} d={geo.linhaMedia} fill="none" stroke="#64748b" strokeOpacity={0.55} strokeWidth={1.5} strokeDasharray="5 4"
              initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 1.4, delay: 0.3 }} />
          )}
          <motion.path key={`l-${chaveDesenho}`} d={geo.linha} fill="none" stroke={cor} strokeWidth={2.6} strokeLinecap="round" strokeLinejoin="round"
            initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 1.4, ease: [0.65, 0, 0.35, 1] }} />
          {destacarMaior && geo.iMax >= 0 && (
            <g className="pointer-events-none">
              <circle className="lc-g-pulso" cx={geo.pts[geo.iMax][0]} cy={geo.pts[geo.iMax][1]} r={9} fill={cor} />
              <circle cx={geo.pts[geo.iMax][0]} cy={geo.pts[geo.iMax][1]} r={3.5} fill={cor} stroke="#fff" strokeWidth={1.5} />
            </g>
          )}
          {pos && (
            <g className="pointer-events-none">
              <line x1={pos[0]} x2={pos[0]} y1={pT} y2={altura - pB} stroke={cor} strokeOpacity={0.45} strokeDasharray="3 3" />
              <line x1={pL} x2={w - pR} y1={pos[1]} y2={pos[1]} stroke={cor} strokeOpacity={0.15} />
              <circle cx={pos[0]} cy={pos[1]} r={9} fill={cor} opacity={0.15} />
              <circle cx={pos[0]} cy={pos[1]} r={4.5} fill={cor} stroke="#fff" strokeWidth={2} />
            </g>
          )}
        </svg>
      )}
      <AnimatePresence>
        {p && pos && (
          <motion.div key="balao" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.12 }}
            className="pointer-events-none absolute z-10 whitespace-nowrap rounded-xl border border-slate-200/80 bg-white/95 px-3 py-2 shadow-lg backdrop-blur"
            style={{ left: Math.max(70, Math.min(w - 70, pos[0])), top: Math.max(0, pos[1] - 76), transform: "translateX(-50%)" }}>
            <p className="text-[11px] font-semibold text-slate-700">{p.rotuloLongo ?? p.rotulo}</p>
            <p className="text-lg font-bold leading-tight tabular-nums" style={{ color: cor }}>
              {formatar(p.valor)}{unidade && <span className="ml-1 text-[11px] font-normal text-slate-500">{unidade}</span>}
            </p>
            {extraBalao && sobre != null && <div className="text-[10px] font-medium">{extraBalao(sobre)}</div>}
          </motion.div>
        )}
      </AnimatePresence>
      <span className="sr-only" aria-live="polite">{p ? `${p.rotuloLongo ?? p.rotulo}: ${formatar(p.valor)}${unidade ? ` ${unidade}` : ""}` : ""}</span>
    </div>
  );
}
