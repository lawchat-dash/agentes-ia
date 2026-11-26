import { useEffect } from "react";

/**
 * MagicBento (adaptado): faz o halo de borda verde dos `.lc-card` seguir o cursor.
 * Calcula a proximidade do mouse a cada card e ajusta as CSS vars
 * --glow-x/--glow-y/--glow-intensity (lidas pelo `.lc-card::after` em index.css).
 * Sem gsap — usa requestAnimationFrame para performance.
 * `pronto`: passe true quando o container já estiver na tela (o efeito liga de novo quando muda).
 */
export function useCardGlow(
  containerRef: React.RefObject<HTMLElement>,
  { radius = 320, selector = ".lc-card", pronto = true }: { radius?: number; selector?: string; pronto?: boolean } = {}
) {
  useEffect(() => {
    const root = containerRef.current;
    if (!root) return;
    if (window.matchMedia("(pointer: coarse)").matches) return; // toque: sem efeito

    let raf = 0;
    const prox = radius * 0.4;
    const fade = radius * 0.95;

    const onMove = (e: PointerEvent) => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const cards = root.querySelectorAll<HTMLElement>(selector);
        cards.forEach((card) => {
          const r = card.getBoundingClientRect();
          const cx = r.left + r.width / 2;
          const cy = r.top + r.height / 2;
          const dist = Math.hypot(e.clientX - cx, e.clientY - cy) - Math.max(r.width, r.height) / 2;
          const d = Math.max(0, dist);
          let g = 0;
          if (d <= prox) g = 1;
          else if (d <= fade) g = (fade - d) / (fade - prox);
          card.style.setProperty("--glow-intensity", g.toFixed(3));
          if (g > 0) {
            card.style.setProperty("--glow-x", `${(((e.clientX - r.left) / r.width) * 100).toFixed(2)}%`);
            card.style.setProperty("--glow-y", `${(((e.clientY - r.top) / r.height) * 100).toFixed(2)}%`);
          }
        });
      });
    };

    const onLeave = () => {
      cancelAnimationFrame(raf);
      root.querySelectorAll<HTMLElement>(selector).forEach((c) => c.style.setProperty("--glow-intensity", "0"));
    };

    root.addEventListener("pointermove", onMove);
    root.addEventListener("pointerleave", onLeave);
    return () => {
      root.removeEventListener("pointermove", onMove);
      root.removeEventListener("pointerleave", onLeave);
      cancelAnimationFrame(raf);
    };
  }, [containerRef, radius, selector, pronto]);
}
