// Menu guiado (coach mark) do painel: escurece a página, recorta e realça o elemento-alvo e mostra um balão com
// "FLUXO · PASSO X DE N", título, texto, progresso em pílulas, "Pular" e o botão da ação. Usado no "Tour do painel"
// e nos botões dos Primeiros passos. Se o alvo está em outra tela, navega e espera o elemento aparecer (com limite).
// Desempenho: sem laço de quadros; o balão só se reposiciona em resize/scroll (um quadro por evento). Esc fecha.
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useLocation, useNavigate } from "react-router-dom";
import { X } from "lucide-react";
import "./guiaRealce.css";

export interface PassoGuia {
  /** Tela onde o alvo fica (prefixo do caminho). Sem rota: a tela atual. */
  rota?: string;
  /** Para onde navegar se a pessoa não está na rota (sem isto, espera ela chegar lá). */
  ir?: string;
  /** Seletores CSS do alvo, em ordem de preferência (o primeiro visível vale). */
  seletores: string[];
  titulo: string;
  texto?: string;
  /** Texto do botão verde (padrão: "Próximo" / "Concluir"). */
  acao?: string;
  /** true: o botão verde também clica no alvo (ex.: "Ativar este"). */
  clicar?: boolean;
}
export interface PedidoGuia { fluxo: string; passos: PassoGuia[] }

const CHAVE = "agentesia_guia_realce";
const EVENTO = "lc-guia-iniciar";
const VALIDADE_MS = 60_000;   // um pedido guardado vale 1 min (se a pessoa não chegar na tela, esquece)
const ESPERA_MS = 8_000;      // procura o elemento por até 8 s (a tela pode estar carregando)
const ESPERA_ROTA_MS = 12_000; // espera chegar na tela do passo por até 12 s
const FOLGA = 6;              // espaço entre o alvo e o recorte
const LARGURA_BALAO = 336;

/** Começa um menu guiado (na tela atual ou em outra). */
export function iniciarGuia(p: PedidoGuia): void {
  if (!p.passos.length) return;
  try { sessionStorage.setItem(CHAVE, JSON.stringify({ ...p, criado: Date.now() })); } catch { /* sem armazenamento */ }
  window.dispatchEvent(new CustomEvent<PedidoGuia>(EVENTO, { detail: p }));
}

/** Compatível com a dica antiga: um passo só, na tela `rota` (quem chama navega). */
export function pedirRealce(p: { rota: string; seletores: string[]; texto: string; fluxo?: string; detalhe?: string }): void {
  iniciarGuia({ fluxo: p.fluxo ?? "Primeiros passos", passos: [{ rota: p.rota, seletores: p.seletores, titulo: p.texto, texto: p.detalhe, acao: "Entendi" }] });
}

function lerPedido(): PedidoGuia | null {
  try {
    const p = JSON.parse(sessionStorage.getItem(CHAVE) ?? "null") as (PedidoGuia & { criado: number }) | null;
    if (!p || !Array.isArray(p.passos) || Date.now() - p.criado > VALIDADE_MS) return null;
    return p;
  } catch { return null; }
}
function apagarPedido(): void { try { sessionStorage.removeItem(CHAVE); } catch { /* ok */ } }

const menosMovimento = () => Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);

interface Caixa { top: number; left: number; width: number; height: number }

export function GuiaRealce() {
  const local = useLocation();
  const navegar = useNavigate();
  const [guia, setGuia] = useState<PedidoGuia | null>(() => lerPedido());
  const [indice, setIndice] = useState(0);
  const [caixa, setCaixa] = useState<Caixa | null>(null);
  const alvo = useRef<HTMLElement | null>(null);
  const navegou = useRef<number>(-1);
  const balaoRef = useRef<HTMLDivElement>(null);
  const acaoRef = useRef<HTMLButtonElement>(null);
  const [posBalao, setPosBalao] = useState<{ top: number; left: number; acima: boolean } | null>(null);

  const fechar = useCallback(() => {
    apagarPedido();
    alvo.current = null;
    setCaixa(null);
    setGuia(null);
    setIndice(0);
  }, []);

  const avancar = useCallback(() => {
    if (!guia || indice + 1 >= guia.passos.length) { fechar(); return; }
    setCaixa(null);
    alvo.current = null;
    setIndice(indice + 1);
  }, [guia, indice, fechar]);

  // Pedido novo (evento) ou guardado (ao montar).
  useEffect(() => {
    const novo = (e: Event) => {
      const p = (e as CustomEvent<PedidoGuia>).detail;
      if (!p?.passos?.length) return;
      navegou.current = -1;
      alvo.current = null;
      setCaixa(null);
      setIndice(0);
      setGuia(p);
    };
    window.addEventListener(EVENTO, novo);
    return () => window.removeEventListener(EVENTO, novo);
  }, []);

  const passo = guia?.passos[indice] ?? null;

  // Acha o alvo do passo atual (navega antes, se precisar).
  useEffect(() => {
    if (!guia || !passo) return;
    if (passo.rota && !local.pathname.startsWith(passo.rota)) {
      if (passo.ir && navegou.current !== indice) { navegou.current = indice; navegar(passo.ir); }
      const t = window.setTimeout(fechar, ESPERA_ROTA_MS);
      return () => window.clearTimeout(t);
    }
    let procura = 0, medir = 0;
    const inicio = Date.now();
    const achar = () => {
      let el: HTMLElement | null = null;
      for (const s of passo.seletores) {
        const candidatos = Array.from(document.querySelectorAll<HTMLElement>(s));
        el = candidatos.find((c) => { const r = c.getBoundingClientRect(); return r.width > 0 && r.height > 0; }) ?? null;
        if (el) break;
      }
      if (!el) {
        if (Date.now() - inicio < ESPERA_MS) procura = window.setTimeout(achar, 250);
        else avancar(); // não apareceu: segue para o próximo passo (ou fecha no último)
        return;
      }
      alvo.current = el;
      el.scrollIntoView({ block: "center", inline: "nearest", behavior: menosMovimento() ? "auto" : "smooth" });
      medir = window.setTimeout(() => {
        const r = el!.getBoundingClientRect();
        setCaixa({ top: r.top - FOLGA, left: r.left - FOLGA, width: r.width + FOLGA * 2, height: r.height + FOLGA * 2 });
      }, menosMovimento() ? 30 : 380);
    };
    procura = window.setTimeout(achar, 200);
    return () => { window.clearTimeout(procura); window.clearTimeout(medir); };
  }, [guia, passo, indice, local.pathname, navegar, fechar, avancar]);

  // Reposiciona só em resize/scroll (um quadro por evento, nada contínuo).
  useEffect(() => {
    if (!caixa) return;
    let quadro = 0;
    const medir = () => {
      cancelAnimationFrame(quadro);
      quadro = requestAnimationFrame(() => {
        const el = alvo.current;
        if (!el || !el.isConnected) return;
        const r = el.getBoundingClientRect();
        setCaixa({ top: r.top - FOLGA, left: r.left - FOLGA, width: r.width + FOLGA * 2, height: r.height + FOLGA * 2 });
      });
    };
    window.addEventListener("scroll", medir, { passive: true, capture: true });
    window.addEventListener("resize", medir, { passive: true });
    return () => {
      cancelAnimationFrame(quadro);
      window.removeEventListener("scroll", medir, { capture: true });
      window.removeEventListener("resize", medir);
    };
  }, [caixa !== null]); // eslint-disable-line react-hooks/exhaustive-deps

  // Esc fecha; clicar no próprio alvo conta como fazer o passo.
  useEffect(() => {
    if (!guia) return;
    const tecla = (e: KeyboardEvent) => { if (e.key === "Escape") fechar(); };
    const clique = (e: PointerEvent) => {
      const el = alvo.current;
      if (el && e.target instanceof Node && el.contains(e.target)) window.setTimeout(avancar, 0);
    };
    document.addEventListener("keydown", tecla);
    document.addEventListener("pointerdown", clique, true);
    return () => { document.removeEventListener("keydown", tecla); document.removeEventListener("pointerdown", clique, true); };
  }, [guia, fechar, avancar]);

  // Balão: abaixo do alvo quando cabe, senão acima; dentro da tela.
  useLayoutEffect(() => {
    if (!caixa) { setPosBalao(null); return; }
    const alturaBalao = balaoRef.current?.offsetHeight ?? 200;
    const vw = window.innerWidth, vh = window.innerHeight;
    const largura = Math.min(LARGURA_BALAO, vw - 32);
    const left = Math.min(Math.max(16, caixa.left), vw - largura - 16);
    const abaixo = caixa.top + caixa.height + 12;
    const acima = abaixo + alturaBalao > vh - 12 && caixa.top - 12 - alturaBalao > 12;
    const top = acima ? caixa.top - 12 - alturaBalao : Math.min(abaixo, vh - alturaBalao - 12);
    setPosBalao({ top: Math.max(12, top), left, acima });
  }, [caixa]);

  useEffect(() => { if (posBalao) acaoRef.current?.focus({ preventScroll: true }); }, [posBalao !== null, indice]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!guia || !passo || !caixa) return null;
  const total = guia.passos.length;
  const ultimo = indice >= total - 1;
  const acao = passo.acao ?? (ultimo ? "Concluir" : "Próximo");
  const agir = () => {
    const el = alvo.current;
    if (passo.clicar && el) el.click();
    avancar();
  };
  const { top, left, width, height } = caixa;
  const vw = window.innerWidth, vh = window.innerHeight;

  return createPortal(
    <div className="lc-guia" aria-live="polite">
      {/* Véu em 4 partes em volta do recorte: o alvo continua clicável. */}
      <div className="lc-guia-veu" style={{ top: 0, left: 0, width: vw, height: Math.max(0, top) }} />
      <div className="lc-guia-veu" style={{ top: top + height, left: 0, width: vw, height: Math.max(0, vh - top - height) }} />
      <div className="lc-guia-veu" style={{ top, left: 0, width: Math.max(0, left), height }} />
      <div className="lc-guia-veu" style={{ top, left: left + width, width: Math.max(0, vw - left - width), height }} />
      <div className="lc-guia-anel" style={{ top, left, width, height }} aria-hidden />
      <div ref={balaoRef} className={`lc-guia-balao${posBalao?.acima ? " acima" : ""}`} role="dialog" aria-modal="false" aria-labelledby="lc-guia-titulo"
        style={{ top: posBalao?.top ?? -9999, left: posBalao?.left ?? 0, width: Math.min(LARGURA_BALAO, vw - 32) }}>
        <div className="lc-guia-topo">
          <span className="lc-guia-rotulo">{guia.fluxo} · {indice + 1} de {total}</span>
          <button type="button" className="lc-guia-x" onClick={fechar} aria-label="Fechar o guia"><X aria-hidden /></button>
        </div>
        <h4 id="lc-guia-titulo" className="lc-guia-titulo">{passo.titulo}</h4>
        {passo.texto && <p className="lc-guia-texto">{passo.texto}</p>}
        <div className="lc-guia-rodape">
          {total > 1 && (
            <span className="lc-guia-pilulas" aria-label={`Passo ${indice + 1} de ${total}`}>
              {guia.passos.map((_, i) => <i key={i} className={i === indice ? "on" : i < indice ? "feito" : undefined} />)}
            </span>
          )}
          <span className="lc-guia-espaco" />
          {!ultimo && <button type="button" className="lc-guia-pular" onClick={fechar}>Pular</button>}
          <button ref={acaoRef} type="button" className="lc-guia-acao" onClick={agir}>{acao}</button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
