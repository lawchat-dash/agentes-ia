import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Rascunho LOCAL (no navegador) de um editor — rede de segurança contra perda de trabalho.
 *
 * O que digitamos num editor vive só na memória da página. Qualquer recarga apaga tudo:
 * o Chrome descartando a aba parada (Economia de memória), o servidor de desenvolvimento
 * recarregando, a sessão caindo, o navegador fechando. Este hook copia o estado do editor
 * para o localStorage:
 *  - a cada INTERVALO_MS, se mudou;
 *  - na hora em que a aba fica oculta / a página vai fechar (visibilitychange, pagehide,
 *    beforeunload) — o último momento antes de um descarte.
 * Ao abrir o editor de novo, se houver um rascunho diferente do que veio do servidor, a tela
 * oferece "Recuperar" / "Descartar" (`pendente`).
 *
 * Fluxo de uso:
 *  1. `obter()` devolve o estado atual (lido de refs/estado — sempre o mais recente);
 *  2. `conteudo(dados)` reduz ao que importa p/ saber se há alteração (sem posição de aba etc.);
 *  3. `habilitado` vira true quando o editor terminou de carregar do servidor — nesse momento o
 *     estado atual vira a BASE (o que está salvo) e o rascunho anterior, se diferente, fica `pendente`;
 *  4. após salvar no servidor com sucesso → `limpar()` (a base passa a ser o estado salvo).
 */

const PREFIXO = "lc-rascunho:";
const INTERVALO_MS = 3000;
const VALIDADE_MS = 7 * 24 * 60 * 60 * 1000; // rascunho mais velho que 7 dias é ignorado

interface Guardado<T> {
  v: 1;
  salvoEm: number;
  dados: T;
}

const ler = <T,>(chave: string): Guardado<T> | null => {
  try {
    const raw = localStorage.getItem(PREFIXO + chave);
    if (!raw) return null;
    const g = JSON.parse(raw) as Guardado<T>;
    if (!g || g.v !== 1 || typeof g.salvoEm !== "number") return null;
    if (Date.now() - g.salvoEm > VALIDADE_MS) {
      localStorage.removeItem(PREFIXO + chave);
      return null;
    }
    return g;
  } catch {
    return null;
  }
};

const gravar = (chave: string, dados: unknown) => {
  try {
    localStorage.setItem(PREFIXO + chave, JSON.stringify({ v: 1, salvoEm: Date.now(), dados }));
  } catch { /* storage cheio/bloqueado — segue sem rede de segurança */ }
};

const remover = (chave: string) => {
  try { localStorage.removeItem(PREFIXO + chave); } catch { /* noop */ }
};

export interface RascunhoLocal<T> {
  /** Rascunho encontrado ao abrir, diferente do que está salvo — aguarda Recuperar/Descartar. */
  pendente: { salvoEm: number; dados: T } | null;
  /** Há alterações ainda não salvas no servidor. */
  sujo: boolean;
  /** Aceita o rascunho pendente: devolve os dados (a tela aplica) e volta a proteger. */
  recuperar: () => T | null;
  /** Descarta o rascunho pendente. */
  descartar: () => void;
  /** Depois de salvar no servidor: apaga o rascunho e o estado atual vira a nova base. */
  limpar: () => void;
  /** Grava agora (ex.: antes de uma navegação programática). */
  gravarAgora: () => void;
}

export function useRascunhoLocal<T>(opts: {
  chave: string | null;
  habilitado: boolean;
  obter: () => T;
  conteudo?: (dados: T) => unknown;
  /** Pede confirmação ao fechar/recarregar com alterações não salvas (desligado em dev). */
  avisarAoSair?: boolean;
}): RascunhoLocal<T> {
  const { chave, habilitado, avisarAoSair = true } = opts;
  const obterRef = useRef(opts.obter);
  obterRef.current = opts.obter;
  const conteudoRef = useRef(opts.conteudo ?? ((d: T) => d));
  conteudoRef.current = opts.conteudo ?? ((d: T) => d);

  const baseRef = useRef<string | null>(null);      // conteúdo salvo no servidor (JSON)
  const ultimoRef = useRef<string | null>(null);     // último conteúdo gravado no storage
  const preparadoRef = useRef<string | null>(null);  // chave para a qual a base já foi tirada
  const [pendente, setPendente] = useState<RascunhoLocal<T>["pendente"]>(null);
  const pendenteRef = useRef(pendente);
  pendenteRef.current = pendente;
  const [sujo, setSujo] = useState(false);
  const sujoRef = useRef(false);

  const assinatura = (dados: T) => {
    try { return JSON.stringify(conteudoRef.current(dados)); } catch { return null; }
  };

  // Ao habilitar (editor carregado do servidor): tira a BASE e procura rascunho anterior.
  useEffect(() => {
    if (!chave || !habilitado || preparadoRef.current === chave) return;
    preparadoRef.current = chave;
    const atual = obterRef.current();
    baseRef.current = assinatura(atual);
    ultimoRef.current = null;
    const g = ler<T>(chave);
    if (g && assinatura(g.dados) !== baseRef.current) {
      setPendente({ salvoEm: g.salvoEm, dados: g.dados });
    } else {
      if (g) remover(chave); // igual ao salvo → nada a recuperar
      setPendente(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chave, habilitado]);

  /** Compara com a base e grava/remove. Não roda enquanto há rascunho pendente de decisão. */
  const verificar = useCallback(() => {
    if (!chave || preparadoRef.current !== chave || baseRef.current === null) return;
    if (pendenteRef.current) return; // não sobrescreve o rascunho antigo antes da decisão
    let dados: T;
    try { dados = obterRef.current(); } catch { return; }
    const sig = assinatura(dados);
    if (sig === null) return;
    const mudou = sig !== baseRef.current;
    if (mudou) {
      if (sig !== ultimoRef.current) {
        gravar(chave, dados);
        ultimoRef.current = sig;
      }
    } else if (ultimoRef.current !== null || sujoRef.current) {
      remover(chave);
      ultimoRef.current = null;
    }
    if (sujoRef.current !== mudou) {
      sujoRef.current = mudou;
      setSujo(mudou);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chave]);

  // Intervalo + eventos de "a página pode sumir agora".
  useEffect(() => {
    if (!chave || !habilitado) return;
    const iv = window.setInterval(verificar, INTERVALO_MS);
    const aoOcultar = () => { if (document.visibilityState === "hidden") verificar(); };
    const aoSair = (e: BeforeUnloadEvent) => {
      verificar();
      if (avisarAoSair && sujoRef.current && !import.meta.env.DEV) {
        e.preventDefault();
        e.returnValue = ""; // navegadores mostram o aviso padrão "Sair do site?"
      }
    };
    document.addEventListener("visibilitychange", aoOcultar);
    window.addEventListener("pagehide", verificar);
    window.addEventListener("beforeunload", aoSair);
    return () => {
      window.clearInterval(iv);
      document.removeEventListener("visibilitychange", aoOcultar);
      window.removeEventListener("pagehide", verificar);
      window.removeEventListener("beforeunload", aoSair);
      verificar(); // desmontando (troca de rota) — guarda o que havia
    };
  }, [chave, habilitado, verificar, avisarAoSair]);

  const recuperar = useCallback(() => {
    const p = pendenteRef.current;
    pendenteRef.current = null;
    setPendente(null);
    return p ? p.dados : null;
  }, []);

  const descartar = useCallback(() => {
    if (chave) remover(chave);
    ultimoRef.current = null;
    pendenteRef.current = null;
    setPendente(null);
  }, [chave]);

  const limpar = useCallback(() => {
    if (chave) remover(chave);
    ultimoRef.current = null;
    try { baseRef.current = assinatura(obterRef.current()); } catch { /* noop */ }
    sujoRef.current = false;
    setSujo(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chave]);

  return { pendente, sujo, recuperar, descartar, limpar, gravarAgora: verificar };
}

/** "há 3 min", "às 14:32 de 12/11" — p/ o banner de recuperação. */
export const quandoFoiSalvo = (ts: number): string => {
  const diff = Date.now() - ts;
  const min = Math.round(diff / 60000);
  if (min < 1) return "agora há pouco";
  if (min < 60) return `há ${min} min`;
  const d = new Date(ts);
  const hh = d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  if (diff < 24 * 60 * 60 * 1000) return `hoje às ${hh}`;
  return `${d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" })} às ${hh}`;
};
