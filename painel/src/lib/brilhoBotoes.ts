// Brilho dos botões (versão leve do SpecularButton, só CSS + um ouvinte).
// Um único "pointermove" para a página toda: a cada quadro, mede só os botões perto do cursor e escreve neles
// --bx/--by (onde o cursor está, em px, relativo ao botão) e --bp (0 = longe, 1 = em cima). O desenho fica em
// estilo-brilho.css: faixa de luz na borda seguindo o cursor, brilho suave por dentro e um reflexo parado no canto
// quando o mouse está longe. Sem WebGL, então dá para usar em dezenas de botões ao mesmo tempo.
import "../estilo-brilho.css";

/** Quem ganha o brilho. Igual à lista de estilo-brilho.css. */
export const SELETOR_BRILHO = ".lc-brilho, .btn:not(.ghost):not(.link), .cv-botao, .cr-botao-verde, .lc-pay-btn, .btn-lawchat";
/** Dentro destes lugares o botão fica sem efeito (tabelas, menus, listas suspensas). */
const SEM_BRILHO = "td, [role='menu'], [role='listbox'], [role='menubar'], [data-radix-popper-content-wrapper], [cmdk-root], .lc-sem-brilho";
const ALCANCE = 115;        // px: a partir daqui o botão começa a acender
const BUSCA_MS = 600;       // de quanto em quanto tempo a lista de botões é relida
const MEDIDA_MS = 220;      // de quanto em quanto tempo as posições são medidas de novo (rolar mede na hora)

let instalado = false;

export function instalarBrilhoBotoes(): void {
  if (instalado || typeof window === "undefined" || typeof document === "undefined") return;
  instalado = true;
  const mm = (q: string) => (typeof window.matchMedia === "function" ? window.matchMedia(q) : null);
  const menosMovimento = mm("(prefers-reduced-motion: reduce)");
  const mouseFino = mm("(hover: hover) and (pointer: fine)");

  let alvos: HTMLElement[] = [];
  let caixas: DOMRect[] = [];
  let ultimaBusca = -Infinity;
  let ultimaMedida = -Infinity;
  let acesos = new Set<HTMLElement>();
  let px = -1e5, py = -1e5;
  let agendado = false;

  const buscar = (agora: number) => {
    if (agora - ultimaBusca >= BUSCA_MS) {
      ultimaBusca = agora;
      ultimaMedida = -Infinity;
      alvos = [];
      document.querySelectorAll<HTMLElement>(SELETOR_BRILHO).forEach((el) => {
        if (!el.closest(SEM_BRILHO)) alvos.push(el);
      });
    }
    // As posições ficam guardadas por alguns quadros: medir todo quadro forçaria o navegador a refazer o layout.
    if (agora - ultimaMedida >= MEDIDA_MS) {
      ultimaMedida = agora;
      caixas = alvos.map((el) => el.getBoundingClientRect());
    }
  };

  const apagarTodos = () => {
    acesos.forEach((el) => el.style.removeProperty("--bp"));
    acesos = new Set();
  };

  const quadro = () => {
    agendado = false;
    if (menosMovimento?.matches) { apagarTodos(); return; }
    buscar(performance.now());
    // 1) só contas com as posições guardadas (nenhuma leitura de layout aqui)
    const perto: Array<[HTMLElement, number, number, number]> = [];
    const vw = window.innerWidth, vh = window.innerHeight;
    for (let i = 0; i < alvos.length; i++) {
      const el = alvos[i], r = caixas[i];
      if (!r) continue;
      if (r.width === 0 || r.bottom < 0 || r.top > vh || r.right < 0 || r.left > vw) continue;
      const dx = Math.max(r.left - px, 0, px - r.right);
      const dy = Math.max(r.top - py, 0, py - r.bottom);
      if (dx > ALCANCE || dy > ALCANCE) continue;
      const d = Math.hypot(dx, dy);
      if (d > ALCANCE) continue;
      const p = 1 - d / ALCANCE;
      perto.push([el, px - r.left, py - r.top, p * p * (3 - 2 * p)]); // suaviza a chegada
    }
    // 2) só escritas
    const novos = new Set<HTMLElement>();
    for (const [el, x, y, p] of perto) {
      el.style.setProperty("--bx", `${x.toFixed(1)}px`);
      el.style.setProperty("--by", `${y.toFixed(1)}px`);
      el.style.setProperty("--bp", p.toFixed(3));
      novos.add(el);
    }
    acesos.forEach((el) => { if (!novos.has(el)) el.style.removeProperty("--bp"); });
    acesos = novos;
  };

  const agendar = () => {
    if (agendado) return;
    agendado = true;
    requestAnimationFrame(quadro);
  };

  window.addEventListener("pointermove", (e) => {
    if (e.pointerType === "touch" || mouseFino?.matches === false) return;
    px = e.clientX; py = e.clientY;
    agendar();
  }, { passive: true });
  // Rolagem muda a posição dos botões debaixo do cursor parado.
  window.addEventListener("scroll", () => { ultimaMedida = -Infinity; if (acesos.size || px > -1e4) agendar(); }, { passive: true, capture: true });
  window.addEventListener("resize", () => { ultimaMedida = -Infinity; }, { passive: true });
  document.addEventListener("pointerleave", () => { px = py = -1e5; apagarTodos(); });
  window.addEventListener("blur", () => { px = py = -1e5; apagarTodos(); });
  // Tela nova: relê a lista no próximo movimento.
  window.addEventListener("popstate", () => { ultimaBusca = -Infinity; });
  document.addEventListener("click", () => { ultimaBusca = -Infinity; }, { passive: true, capture: true });
}

instalarBrilhoBotoes();
