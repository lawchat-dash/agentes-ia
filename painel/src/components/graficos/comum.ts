/*
 * Peças comuns dos gráficos próprios (components/graficos): largura medida, contagem animada, menos movimento,
 * curva suave sem "passar do ponto" e média móvel. Sem pacotes novos.
 */
import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";

export const VERDE = "#00bc33";
export const VERDE_ESCURO = "#00a32c";
export const VERDE_CLARO = "#e3f7e8";
export const TINTA = "#101828";
/** Paleta em tons de verde para fatias e séries (do mais forte ao mais claro). */
export const PALETA_VERDE = ["#00a32c", "#00bc33", "#34d399", "#86efac", "#bbf7d0", "#0f766e", "#65a30d", "#a3e635"];

/** true quando a pessoa pediu menos movimento no sistema. */
export function useMenosMovimento() {
  const consulta = "(prefers-reduced-motion: reduce)";
  const [reduz, setReduz] = useState(() => typeof window !== "undefined" && Boolean(window.matchMedia?.(consulta)?.matches));
  useEffect(() => {
    const m = window.matchMedia?.(consulta);
    if (!m) return;
    const mudou = () => setReduz(m.matches);
    m.addEventListener?.("change", mudou);
    return () => m.removeEventListener?.("change", mudou);
  }, []);
  return reduz;
}

/** Largura (px) do elemento, atualizada quando a tela muda de tamanho. */
export function useLargura<T extends HTMLElement>(): [RefObject<T>, number] {
  const ref = useRef<T>(null);
  const [largura, setLargura] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setLargura(el.getBoundingClientRect().width);
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((e) => setLargura(e[0].contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, largura];
}

/** Número que conta até o valor (ease-out). Sem animação quando a pessoa pediu menos movimento. */
export function useContagem(valor: number, duracao = 1000) {
  const reduz = useMenosMovimento();
  const [mostrado, setMostrado] = useState(reduz ? valor : 0);
  const atual = useRef(reduz ? valor : 0);
  useEffect(() => {
    const de = atual.current;
    if (reduz || de === valor || !Number.isFinite(valor)) { atual.current = valor; setMostrado(valor); return; }
    let quadro = 0;
    let inicio: number | null = null;
    const passo = (t: number) => {
      if (inicio === null) inicio = t;
      const p = Math.min(1, (t - inicio) / duracao);
      const v = de + (valor - de) * (1 - Math.pow(1 - p, 3));
      atual.current = v;
      setMostrado(v);
      if (p < 1) quadro = requestAnimationFrame(passo);
    };
    quadro = requestAnimationFrame(passo);
    return () => cancelAnimationFrame(quadro);
  }, [valor, duracao, reduz]);
  return mostrado;
}

/** Caminho SVG suave (cúbica monotônica): a curva não inventa picos nem vales entre os pontos. */
export function caminhoSuave(pts: [number, number][]): string {
  const n = pts.length;
  if (!n) return "";
  if (n === 1) return `M${pts[0][0]},${pts[0][1]}`;
  if (n === 2) return `M${pts[0][0]},${pts[0][1]} L${pts[1][0]},${pts[1][1]}`;
  const dx: number[] = [], m: number[] = [];
  for (let i = 0; i < n - 1; i++) {
    dx.push(pts[i + 1][0] - pts[i][0]);
    m.push(dx[i] === 0 ? 0 : (pts[i + 1][1] - pts[i][1]) / dx[i]);
  }
  const t: number[] = [m[0]];
  for (let i = 1; i < n - 1; i++) t.push(m[i - 1] * m[i] <= 0 ? 0 : (m[i - 1] + m[i]) / 2);
  t.push(m[n - 2]);
  for (let i = 0; i < n - 1; i++) {
    if (m[i] === 0) { t[i] = 0; t[i + 1] = 0; continue; }
    const a = t[i] / m[i], b = t[i + 1] / m[i], h = a * a + b * b;
    if (h > 9) { const k = 3 / Math.sqrt(h); t[i] = k * a * m[i]; t[i + 1] = k * b * m[i]; }
  }
  const f = (v: number) => Number(v.toFixed(2));
  let d = `M${f(pts[0][0])},${f(pts[0][1])}`;
  for (let i = 0; i < n - 1; i++) {
    const [x0, y0] = pts[i], [x1, y1] = pts[i + 1], h = dx[i] / 3;
    d += ` C${f(x0 + h)},${f(y0 + t[i] * h)} ${f(x1 - h)},${f(y1 - t[i + 1] * h)} ${f(x1)},${f(y1)}`;
  }
  return d;
}

/** Média móvel simples (janela para trás), do mesmo tamanho da série. */
export function mediaMovel(valores: number[], janela = 7): number[] {
  return valores.map((_, i) => {
    const fatia = valores.slice(Math.max(0, i - janela + 1), i + 1);
    return fatia.reduce((s, v) => s + v, 0) / (fatia.length || 1);
  });
}

/** Índice do ponto mais próximo da posição x (px) numa série de n pontos espalhados entre x0 e x1. */
export function indicePorX(x: number, n: number, x0: number, x1: number): number {
  if (n <= 1) return 0;
  const p = (x - x0) / Math.max(1, x1 - x0);
  return Math.max(0, Math.min(n - 1, Math.round(p * (n - 1))));
}

export const fmtPadrao = (v: number) => v.toLocaleString("pt-BR", { maximumFractionDigits: 0 });
