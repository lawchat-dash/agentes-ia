/*
 * MapaCalor: grade de atividade (ex.: dia da semana × hora), em células como as do GitHub, com 5 tons de verde,
 * balão ao passar o mouse e entrada em onda. Teclado: Tab até a grade e setas para andar entre as células.
 */
import { useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { cn } from "@/lib/utils";
import { fmtPadrao } from "./comum";
import "./graficos.css";

export const DIAS_SEMANA = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"];
const DIAS_LONGOS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"];
const TONS_VERDE = ["#f1f5f9", "#d3f3db", "#86e0a0", "#2fcb5a", "#00a32c"];
const TONS_AZUL = ["#f1f5f9", "#dbeafe", "#93c5fd", "#3b82f6", "#1d4ed8"];

export default function MapaCalor({
  grade, rotulosLinhas = DIAS_SEMANA, rotulosColunas, unidade = "lead", unidadePlural, tom = "verde", formatar = fmtPadrao,
  descreverCelula, rotuloAria, className,
}: {
  /** grade[linha][coluna]; no padrão, 7 linhas (seg a dom) × 24 colunas (horas). */
  grade: number[][]; rotulosLinhas?: string[]; rotulosColunas?: string[]; unidade?: string; unidadePlural?: string;
  tom?: "verde" | "azul"; formatar?: (v: number) => string;
  /** Texto do balão; o padrão é "terça às 14h". */
  descreverCelula?: (linha: number, coluna: number) => string;
  rotuloAria?: string; className?: string;
}) {
  const [ativo, setAtivo] = useState<[number, number] | null>(null);
  const [pos, setPos] = useState<{ x: number; y: number; lado: "e" | "c" | "d" } | null>(null);
  const caixa = useRef<HTMLDivElement>(null);
  const linhas = grade.length, colunas = Math.max(0, ...grade.map((l) => l.length));
  const cols = rotulosColunas ?? Array.from({ length: colunas }, (_, h) => String(h).padStart(2, "0"));
  const tons = tom === "azul" ? TONS_AZUL : TONS_VERDE;
  const { max, total, pico } = useMemo(() => {
    let max = 0, total = 0, pico: [number, number] | null = null;
    grade.forEach((l, i) => l.forEach((v, j) => { total += v; if (v > max) { max = v; pico = [i, j]; } }));
    return { max, total, pico: pico as [number, number] | null };
  }, [grade]);
  const nivel = (v: number) => (!v || !max ? 0 : Math.min(4, 1 + Math.floor((v / max) * 3.999)));
  const plural = unidadePlural ?? `${unidade}s`;
  const desc = descreverCelula ?? ((i: number, j: number) => `${DIAS_LONGOS[i] ?? rotulosLinhas[i]} às ${cols[j]}h`);
  const nome = (v: number) => `${formatar(v)} ${v === 1 ? unidade : plural}`;

  const tecla = (e: KeyboardEvent<HTMLDivElement>) => {
    const [i, j] = ativo ?? pico ?? [0, 0];
    const mov: Record<string, [number, number]> = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] };
    if (mov[e.key]) {
      e.preventDefault();
      setAtivo([Math.max(0, Math.min(linhas - 1, i + mov[e.key][0])), Math.max(0, Math.min(colunas - 1, j + mov[e.key][1]))]);
    } else if (e.key === "Escape") setAtivo(null);
  };
  const v = ativo ? grade[ativo[0]]?.[ativo[1]] ?? 0 : 0;
  // Posição do balão: pela célula de verdade (funciona com mouse e com teclado).
  useLayoutEffect(() => {
    const el = ativo && caixa.current?.querySelector<HTMLElement>(`[data-c="${ativo[0]}-${ativo[1]}"]`);
    if (!el || !ativo) { setPos(null); return; }
    setPos({ x: el.offsetLeft + el.offsetWidth / 2, y: el.offsetTop, lado: ativo[1] > colunas * 0.75 ? "d" : ativo[1] < colunas * 0.2 ? "e" : "c" });
  }, [ativo, colunas]);

  return (
    <div className={cn("lc-g-calor", className)}>
      <div ref={caixa} className="relative overflow-x-auto pb-1 outline-none focus-visible:ring-2 focus-visible:ring-[#00bc33]/40 rounded-md" tabIndex={0}
        role="img" aria-label={rotuloAria ?? `Mapa de calor: ${nome(total)} no total${pico ? `, pico na ${desc(pico[0], pico[1])}` : ""}`}
        onKeyDown={tecla} onFocus={() => !ativo && pico && setAtivo(pico)} onBlur={() => setAtivo(null)} onPointerLeave={() => setAtivo(null)}>
        <div className="grid min-w-[440px] gap-[3px]" style={{ gridTemplateColumns: `2.25rem repeat(${colunas}, minmax(0, 1fr))` }}>
          <span />
          {cols.map((c, j) => (
            <span key={j} className="pb-1 text-center text-[9px] tabular-nums text-slate-400">{j % 3 === 0 ? c : ""}</span>
          ))}
          {grade.map((linha, i) => (
            <div key={i} className="contents">
              <span className="flex items-center text-[10px] font-medium text-slate-500">{rotulosLinhas[i]}</span>
              {Array.from({ length: colunas }, (_, j) => {
                const val = linha[j] ?? 0, on = ativo?.[0] === i && ativo?.[1] === j;
                return (
                  <span key={j} className={cn("lc-g-celula aspect-square rounded-[4px]", on && "lc-g-celula--ativa")}
                    style={{ background: tons[nivel(val)], animationDelay: `${(i * 0.035 + j * 0.018).toFixed(3)}s` }}
                    data-c={`${i}-${j}`} onPointerEnter={() => setAtivo([i, j])} />
                );
              })}
            </div>
          ))}
        </div>
        {ativo && pos && (
          <div className="pointer-events-none absolute z-10 whitespace-nowrap rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-[11px] shadow-lg"
            style={{ left: pos.x, top: Math.max(0, pos.y - 34), transform: `translateX(${pos.lado === "d" ? "-100%" : pos.lado === "e" ? "-12px" : "-50%"})` }}>
            <span className="font-bold text-[#101828]">{nome(v)}</span>
            <span className="text-slate-500"> · {desc(ativo[0], ativo[1])}</span>
          </div>
        )}
      </div>
      <div className="mt-2 flex items-center justify-end gap-1.5 text-[10px] text-slate-500">
        <span>Menos</span>
        {tons.map((c) => <span key={c} className="h-2.5 w-2.5 rounded-[3px]" style={{ background: c }} />)}
        <span>Mais</span>
      </div>
      <span className="sr-only" aria-live="polite">{ativo ? `${nome(v)}, ${desc(ativo[0], ativo[1])}` : ""}</span>
    </div>
  );
}
