import { useEffect, useRef, useState, useSyncExternalStore, type CSSProperties, type RefObject } from "react";
import { RefreshCw, ExternalLink } from "lucide-react";
import { Alerta } from "./ui";
import { TelaEntrando, linkDaHelena } from "../telas/Atendimento";

/**
 * Telas da LawChat (CRM, ajustes da conta) abertas dentro do painel, que FICAM MONTADAS depois da 1ª abertura.
 *
 * A página (Minha Conta, CRM) só desenha as abas e uma "vaga" vazia; a camada (montada uma vez na Estrutura, fora das
 * rotas) põe o quadro da LawChat em cima da vaga. Trocar de tela só esconde um quadro e mostra outro: voltar para uma
 * tela já aberta é instantâneo e não faz login de novo. Recomeça ao trocar de escritório ou fechar a aba do navegador.
 */

interface Vaga { codigo: string; titulo: string; estilo: CSSProperties; caixa: DOMRect | null }

let vaga: Vaga | null = null;
let pedidoDeRecarga: { codigo: string; vez: number } | null = null;
const ouvintes = new Set<() => void>();
const avisar = () => ouvintes.forEach((f) => f());
const assinar = (f: () => void) => { ouvintes.add(f); return () => { ouvintes.delete(f); }; };
const lerVaga = () => vaga;
const lerRecarga = () => pedidoDeRecarga;

/** Recarrega (com login novo) o quadro de uma tela. */
/** Telas pedidas para abrir por trás (Minha Conta abre todas de uma vez: trocar de aba já fica instantâneo). */
let preabrir: { codigo: string; titulo: string; estilo: CSSProperties }[] = [];
const lerPreabrir = () => preabrir;
export function preabrirLawChat(lista: { codigo: string; titulo: string; estilo: CSSProperties }[]) {
  const novas = lista.filter((x) => !preabrir.some((p) => p.codigo === x.codigo));
  if (novas.length) { preabrir = [...preabrir, ...novas]; avisar(); }
}

export function recarregarLawChat(codigo: string) {
  pedidoDeRecarga = { codigo, vez: (pedidoDeRecarga?.vez ?? 0) + 1 };
  avisar();
}

/** A página marca onde o quadro da LawChat aparece (a vaga acompanha tamanho, rolagem e janela). */
export function useVagaLawChat(ref: RefObject<HTMLElement>, codigo: string, titulo: string, estilo: CSSProperties) {
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let quadro = 0;
    const medir = () => {
      cancelAnimationFrame(quadro);
      quadro = requestAnimationFrame(() => { vaga = { codigo, titulo, estilo, caixa: el.getBoundingClientRect() }; avisar(); });
    };
    medir();
    const obs = new ResizeObserver(medir);
    obs.observe(el);
    window.addEventListener("resize", medir);
    window.addEventListener("scroll", medir, true);
    return () => {
      cancelAnimationFrame(quadro);
      obs.disconnect();
      window.removeEventListener("resize", medir);
      window.removeEventListener("scroll", medir, true);
      if (vaga?.codigo === codigo) { vaga = null; avisar(); }
    };
    // estilo é constante por tela
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ref, codigo, titulo]);
}

interface Quadro { codigo: string; titulo: string; estilo: CSSProperties; url: string | null; erro: string | null; pronto: boolean; vez: number }

export function CamadaLawChat({ escritorio, escondida }: { escritorio: string | null; escondida: boolean }) {
  const atual = useSyncExternalStore(assinar, lerVaga);
  const recarga = useSyncExternalStore(assinar, lerRecarga);
  const fila = useSyncExternalStore(assinar, lerPreabrir);
  const [quadros, setQuadros] = useState<Record<string, Quadro>>({});
  const vezDaRecarga = useRef(0);

  // Trocou de escritório: começa do zero (as telas eram da outra conta).
  useEffect(() => { setQuadros({}); preabrir = []; }, [escritorio]);

  const abrir = (codigo: string, titulo: string, estilo: CSSProperties) => {
    setQuadros((q) => ({ ...q, [codigo]: { codigo, titulo, estilo, url: null, erro: null, pronto: false, vez: (q[codigo]?.vez ?? 0) + 1 } }));
    linkDaHelena(undefined, codigo === "atendimento" ? undefined : codigo)
      .then((url) => setQuadros((q) => (q[codigo] ? { ...q, [codigo]: { ...q[codigo], url } } : q)))
      .catch((e) => setQuadros((q) => (q[codigo] ? { ...q, [codigo]: { ...q[codigo], erro: (e as Error).message, pronto: true } } : q)));
  };

  // 1ª vez numa tela: pede o link de entrada (uma vez só; depois o quadro fica montado).
  useEffect(() => {
    if (atual && escritorio && !quadros[atual.codigo]) abrir(atual.codigo, atual.titulo, atual.estilo);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [atual?.codigo, escritorio]);

  // Abre por trás as telas pedidas, uma a cada 0,6 s (não disputa com a tela que está na frente).
  useEffect(() => {
    if (!escritorio) return;
    const faltam = fila.filter((p) => !quadros[p.codigo]);
    if (!faltam.length) return;
    // Uma por vez e com folga (1,2 s): o painel continua leve enquanto as telas entram por trás.
    const t = window.setTimeout(() => abrir(faltam[0].codigo, faltam[0].titulo, faltam[0].estilo), 1200);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fila, quadros, escritorio]);

  useEffect(() => {
    if (!recarga || recarga.vez === vezDaRecarga.current) return;
    vezDaRecarga.current = recarga.vez;
    const q = quadros[recarga.codigo];
    if (q) abrir(q.codigo, q.titulo, q.estilo);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recarga]);

  if (!escritorio) return null;
  const caixa = atual?.caixa;
  return (
    <>
      {Object.values(quadros).map((q) => {
        const visivel = !escondida && atual?.codigo === q.codigo && caixa && caixa.width > 0;
        const posicao: CSSProperties = visivel
          ? { position: "fixed", left: caixa.left, top: caixa.top, width: caixa.width, height: caixa.height, zIndex: 25 }
          : { position: "fixed", left: -10000, top: 0, width: 1200, height: 800, visibility: "hidden", pointerEvents: "none" };
        return (
          <div key={q.codigo} className="lc-quadro-lawchat" style={posicao} aria-hidden={!visivel}>
            {q.url && !q.erro && (
              <iframe key={`${q.vez}`} title={q.titulo} src={q.url} className="border-0" style={q.estilo}
                onLoad={() => window.setTimeout(() => setQuadros((s) => (s[q.codigo] ? { ...s, [q.codigo]: { ...s[q.codigo], pronto: true } } : s)), 1200)}
                allow="clipboard-read; clipboard-write; microphone; camera" referrerPolicy="no-referrer" />
            )}
            {/* Central: a faixa verde "Ative as notificações na web" fica no topo da lista de conversas (400px); dentro do
                painel o navegador não deixa ativar notificação, então ela nunca sairia. Fica coberta. */}
            {q.codigo === "atendimento" && <div aria-hidden className="absolute left-0 top-0 z-[5] bg-white" style={{ width: 400, height: 34 }} />}
            {!q.pronto && <TelaEntrando titulo={`Abrindo ${q.titulo}`} />}
            {q.erro && (
              <div className="absolute inset-0 grid place-items-center p-6 bg-[var(--lc-fundo-lawchat)]">
                <div style={{ maxWidth: 520 }}>
                  <Alerta tipo="bad" titulo={`Não deu para abrir ${q.titulo}`}>{q.erro}</Alerta>
                  <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
                    <button type="button" className="btn" onClick={() => abrir(q.codigo, q.titulo, q.estilo)}><RefreshCw size={15} /> Tentar de novo</button>
                    <button type="button" className="btn pri" onClick={() => void abrirEmJanela(q.codigo)}><ExternalLink size={15} /> Abrir em janela separada</button>
                  </div>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </>
  );
}

/** Abre a tela da LawChat numa janela separada (a janela abre no clique para o navegador não bloquear). */
export async function abrirEmJanela(codigo: string) {
  const janela = window.open("about:blank", `lawchat-${codigo}`, "width=1280,height=860");
  try {
    const u = await linkDaHelena(undefined, codigo);
    if (janela) { janela.opener = null; janela.location.href = u; }
  } catch (e) {
    janela?.close();
    throw e;
  }
}
