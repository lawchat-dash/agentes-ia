// Dica "Clique aqui" do tutorial de Primeiros passos: o botão do passo guarda o que realçar; ao chegar na tela, o
// elemento ganha um contorno pulsando e um balão que somem sozinhos (ou no primeiro clique). Só visual.
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useLocation } from "react-router-dom";

const CHAVE = "agentesia_guia_realce";
const VALIDADE_MS = 30_000;   // o pedido vale por 30 s (se a pessoa não chegar na tela, esquece)
const ESPERA_MS = 8_000;      // procura o elemento por até 8 s (a tela pode estar carregando)
const DURACAO_MS = 7_000;     // a dica fica 7 s na tela

interface Pedido { rota: string; seletores: string[]; texto: string; criado: number }

export function pedirRealce(p: Omit<Pedido, "criado">): void {
  try { sessionStorage.setItem(CHAVE, JSON.stringify({ ...p, criado: Date.now() })); } catch { /* sem armazenamento: sem dica */ }
}

function lerPedido(): Pedido | null {
  try {
    const p = JSON.parse(sessionStorage.getItem(CHAVE) ?? "null") as Pedido | null;
    if (!p || Date.now() - p.criado > VALIDADE_MS) return null;
    return p;
  } catch { return null; }
}

export function GuiaRealce() {
  const local = useLocation();
  const [balao, setBalao] = useState<{ x: number; y: number; texto: string; acima: boolean } | null>(null);

  useEffect(() => {
    const pedido = lerPedido();
    if (!pedido || !local.pathname.startsWith(pedido.rota)) return;
    try { sessionStorage.removeItem(CHAVE); } catch { /* ok */ }
    let alvo: HTMLElement | null = null;
    let fim = 0, procura = 0, raf = 0;
    const inicio = Date.now();
    const posicionar = () => {
      if (!alvo) return;
      const r = alvo.getBoundingClientRect();
      const acima = r.bottom + 70 > window.innerHeight;
      const x = Math.min(Math.max(r.left + r.width / 2, 90), window.innerWidth - 90);
      setBalao({ x, y: acima ? r.top - 12 : r.bottom + 12, texto: pedido.texto, acima });
    };
    const rolando = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(posicionar); };
    const encerrar = () => {
      alvo?.classList.remove("lc-guia-alvo");
      setBalao(null);
      window.removeEventListener("scroll", rolando, true);
      window.removeEventListener("resize", rolando);
      document.removeEventListener("pointerdown", encerrar, true);
    };
    const achar = () => {
      for (const s of pedido.seletores) {
        const el = document.querySelector<HTMLElement>(s);
        if (el && el.getBoundingClientRect().width > 0) { alvo = el; break; }
      }
      if (!alvo) {
        if (Date.now() - inicio < ESPERA_MS) procura = window.setTimeout(achar, 250);
        return;
      }
      alvo.scrollIntoView({ block: "center", behavior: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
      alvo.classList.add("lc-guia-alvo");
      window.setTimeout(posicionar, 350);
      window.addEventListener("scroll", rolando, { passive: true, capture: true });
      window.addEventListener("resize", rolando, { passive: true });
      document.addEventListener("pointerdown", encerrar, true);
      fim = window.setTimeout(encerrar, DURACAO_MS);
    };
    procura = window.setTimeout(achar, 300);
    return () => { window.clearTimeout(procura); window.clearTimeout(fim); cancelAnimationFrame(raf); encerrar(); };
  }, [local.pathname]);

  if (!balao) return null;
  return createPortal(
    <div className={`lc-guia-balao${balao.acima ? " acima" : ""}`} style={{ left: balao.x, top: balao.y }} role="status">
      {balao.texto}
    </div>,
    document.body,
  );
}
