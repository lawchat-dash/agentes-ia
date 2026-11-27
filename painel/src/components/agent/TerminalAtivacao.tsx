// Janela de "terminal" que aparece por alguns segundos quando o agente é ativado: digita, linha a linha, o que a
// ativação acabou de fazer (número, prompt e etapas, follow-up, avisos) e fecha sozinha (ou no "Fechar").
// Só mostra dados que o cliente já vê na tela (nome, produto, número com o meio escondido). Nada de chave ou código interno.
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import "./TerminalAtivacao.css";

export interface TerminalAtivacaoProps {
  aberto: boolean;
  nome: string;
  produto?: string | null;
  numero?: string | null;
  modo?: "teste" | "producao" | null;
  /** Quantos toques de follow-up; 0 ou null = desligado; undefined = não mostra a linha. */
  followupPassos?: number | null;
  aoFechar: () => void;
}

type Linha = { texto: string; tipo: "comando" | "ok" | "fim" };

const POR_LETRA_MS = 14;
const ENTRE_LINHAS_MS = 220;
const FECHA_DEPOIS_MS = 1400;

/** (31) 98765-4321 vira "(31) 9xxxx-4321": dá para reconhecer o número sem expor ele inteiro. */
function numeroEscondido(numero?: string | null): string | null {
  const d = (numero ?? "").replace(/\D/g, "").replace(/^55(?=\d{10,11}$)/, "");
  if (d.length < 10) return null;
  const ddd = d.slice(0, 2);
  const resto = d.slice(2);
  return `(${ddd}) ${resto[0]}xxxx-${resto.slice(-4)}`;
}

/** "Auxílio-Acidente" vira "auxilio-acidente" (parece um parâmetro de linha de comando). */
function comoParametro(texto: string): string {
  return texto.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "agente";
}

function montarLinhas(p: TerminalAtivacaoProps): Linha[] {
  const produto = (p.produto || p.nome || "agente").trim();
  const numero = numeroEscondido(p.numero);
  const linhas: Linha[] = [
    { tipo: "comando", texto: `lawchat agente ativar --produto ${comoParametro(produto)}${p.modo ? ` --modo ${p.modo === "producao" ? "todos" : "teste"}` : ""}` },
    { tipo: "ok", texto: numero ? `conectando ao número ${numero}` : "conectando ao número de WhatsApp" },
    { tipo: "ok", texto: "carregando prompt e etapas" },
  ];
  if (p.followupPassos !== undefined) {
    linhas.push({ tipo: "ok", texto: p.followupPassos ? `follow-up: ${p.followupPassos} ${p.followupPassos === 1 ? "passo" : "passos"}` : "follow-up: desligado" });
  }
  linhas.push({ tipo: "ok", texto: "avisos ligados" });
  if (p.modo) linhas.push({ tipo: "ok", texto: p.modo === "producao" ? "respondendo a todos os contatos" : "modo teste: só os números de teste" });
  linhas.push({ tipo: "fim", texto: `${p.nome.trim() || "agente"} no ar` });
  return linhas;
}

export function TerminalAtivacao(props: TerminalAtivacaoProps) {
  const { aberto, aoFechar } = props;
  // As linhas são fixadas ao abrir (mudar uma prop no meio não reinicia a digitação).
  const linhas = useMemo(() => (aberto ? montarLinhas(props) : []), [aberto]); // eslint-disable-line react-hooks/exhaustive-deps
  const [linha, setLinha] = useState(0);     // linha sendo digitada
  const [letras, setLetras] = useState(0);   // letras já digitadas dela
  const fecharRef = useRef(aoFechar);
  fecharRef.current = aoFechar;
  const botaoRef = useRef<HTMLButtonElement | null>(null);
  const terminou = aberto && linha >= linhas.length;

  useEffect(() => {
    if (!aberto) return;
    const semMovimento = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (semMovimento) { setLinha(linhas.length); setLetras(0); return; }
    setLinha(0); setLetras(0);
  }, [aberto, linhas]);

  // Digitação: uma letra por vez; no fim da linha, uma pausa e a próxima.
  useEffect(() => {
    if (!aberto || linha >= linhas.length) return;
    const total = linhas[linha].texto.length;
    const id = letras < total
      ? setTimeout(() => setLetras((n) => n + 1), POR_LETRA_MS)
      : setTimeout(() => { setLinha((n) => n + 1); setLetras(0); }, ENTRE_LINHAS_MS);
    return () => clearTimeout(id);
  }, [aberto, linha, letras, linhas]);

  // Terminou: fecha sozinha depois de um instante.
  useEffect(() => {
    if (!terminou) return;
    const id = setTimeout(() => fecharRef.current(), FECHA_DEPOIS_MS);
    return () => clearTimeout(id);
  }, [terminou]);

  useEffect(() => {
    if (!aberto) return;
    botaoRef.current?.focus({ preventScroll: true });
    const tecla = (e: KeyboardEvent) => { if (e.key === "Escape") fecharRef.current(); };
    window.addEventListener("keydown", tecla);
    return () => window.removeEventListener("keydown", tecla);
  }, [aberto]);

  if (!aberto || typeof document === "undefined") return null;

  const prefixo = (l: Linha) => (l.tipo === "comando" ? "$ " : l.tipo === "fim" ? "→ " : "✓ ");
  const visiveis = linhas.slice(0, Math.min(linha + 1, linhas.length));

  return createPortal(
    <div className="term-at__fundo" onClick={(e) => { if (e.target === e.currentTarget) aoFechar(); }}>
      <div className="term-at" role="dialog" aria-modal="true" aria-label="Ativando o agente">
        <div className="term-at__barra" aria-hidden="true">
          <span className="term-at__ponto" style={{ background: "#ff5f57" }} />
          <span className="term-at__ponto" style={{ background: "#febc2e" }} />
          <span className="term-at__ponto" style={{ background: "#28c840" }} />
          <span className="term-at__titulo">lawchat — ativação</span>
        </div>
        <div className="term-at__corpo" aria-live="polite">
          {visiveis.map((l, i) => {
            const atual = i === linha;
            const texto = atual ? l.texto.slice(0, letras) : l.texto;
            const cor = l.tipo === "comando" ? "term-at__comando" : l.tipo === "fim" ? "term-at__fim" : "term-at__ok";
            return (
              <span key={i} className="term-at__linha">
                <span className={l.tipo === "comando" ? "term-at__prompt" : cor}>{prefixo(l)}</span>
                <span className={cor}>{texto}</span>
                {atual && <span className="term-at__cursor" aria-hidden="true" />}
              </span>
            );
          })}
          {terminou && <span className="term-at__linha"><span className="term-at__prompt">$ </span><span className="term-at__cursor" aria-hidden="true" /></span>}
        </div>
        <div className="term-at__rodape">
          <button ref={botaoRef} type="button" className="term-at__fechar" onClick={aoFechar}>Fechar</button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

export default TerminalAtivacao;
