import { createContext, useCallback, useContext, useEffect, useId, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type MouseEvent as ReactMouseEvent, type ReactNode } from "react";
import { AlertTriangle, Check, CheckCircle2, Copy, Info, Inbox, KeyRound, XCircle } from "lucide-react";
import { createPortal } from "react-dom";
import { toast } from "sonner";
import { api, geracaoAtual, guardarResposta, marcarEsperaSemDado, ultimaResposta } from "../api";

// --------------------------------------------------------------------------- carregar dados
/**
 * GET de uma tela. Stale-while-revalidate: se a tela já foi aberta (nesta aba ou numa abertura anterior do painel, ver
 * cachePersistente.ts), mostra na hora a última resposta (guardada em api.ts) e busca de novo por trás; `carregando`
 * fica true enquanto busca. Sem cópia nenhuma, a tela de abertura espera esta busca (marcarEsperaSemDado). Qualquer escrita (POST/PUT/DELETE) apaga as
 * respostas guardadas. `guardar: false` para dado que não pode aparecer velho nem por um instante (saldo/extrato da
 * carteira, conversa aberta).
 */
export function useCarregar<T>(caminho: string | null, dependencias: unknown[] = [], opcoes: { guardar?: boolean } = {}) {
  const guardar = opcoes.guardar !== false;
  const [dados, setDadosEstado] = useState<T | null>(() => (caminho && guardar ? ultimaResposta<T>(caminho) ?? null : null));
  const [erro, setErro] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(Boolean(caminho));
  // fresco: o dado mostrado já veio do servidor nesta abertura (não é a cópia guardada). Telas com formulário que copiam
  // o dado para o estado delas esperam por ele, para não editar uma cópia velha.
  const [fresco, setFresco] = useState(false);
  const versao = useRef(0);
  const dadosAgora = useRef(dados);
  dadosAgora.current = dados;

  // Trocou o caminho (outro filtro, outro escritório) e já existe resposta guardada para ele: mostra na hora.
  const caminhoAnterior = useRef(caminho);
  if (caminhoAnterior.current !== caminho) {
    caminhoAnterior.current = caminho;
    const guardada = caminho && guardar ? ultimaResposta<T>(caminho) : undefined;
    if (guardada !== undefined) setDadosEstado(guardada);
    setFresco(false);
  }

  // setDados das telas (atualização local depois de salvar) também atualiza a cópia guardada.
  const setDados = useCallback((valor: T | null | ((antes: T | null) => T | null)) => {
    setDadosEstado((antes) => {
      const novo = typeof valor === "function" ? (valor as (a: T | null) => T | null)(antes) : valor;
      if (caminho && guardar && novo != null) guardarResposta(caminho, novo, geracaoAtual());
      return novo;
    });
  }, [caminho, guardar]);

  const recarregar = useCallback(async () => {
    if (!caminho) return;
    const minha = ++versao.current;
    const geracao = geracaoAtual();
    // Nada para mostrar ainda (nem a cópia guardada): a tela de abertura espera por esta busca.
    const semDado = dadosAgora.current == null && !(guardar && ultimaResposta<T>(caminho) !== undefined);
    if (semDado) marcarEsperaSemDado(1);
    setCarregando(true);
    try {
      const resposta = await api<T>(caminho);
      if (guardar) guardarResposta(caminho, resposta, geracao);
      if (minha === versao.current) { setDadosEstado(resposta); setErro(null); setFresco(true); }
    } catch (e) {
      if (minha === versao.current) setErro((e as Error).message);
    } finally {
      if (minha === versao.current) setCarregando(false);
      if (semDado) marcarEsperaSemDado(-1);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caminho, guardar, ...dependencias]);

  useEffect(() => { recarregar(); }, [recarregar]);
  return { dados, erro, carregando, recarregar, setDados, fresco };
}

// --------------------------------------------------------------------------- avisos rápidos
const ContextoAviso = createContext<(texto: string, tipo?: "ok" | "bad") => void>(() => {});

/** Avisos do painel saem pelo sonner, o mesmo das telas do agents-lawchat-main (um estilo só). */
export function ProvedorAvisos({ children }: { children: ReactNode }) {
  const avisar = useCallback((texto: string, tipo: "ok" | "bad" = "ok") => {
    if (tipo === "bad") toast.error(texto, { id: `aviso-bad:${texto}`, duration: 6000 }); // id fixo: o mesmo aviso não empilha
    else toast.success(texto, { id: `aviso-ok:${texto}`, duration: 3000 });
  }, []);
  return <ContextoAviso.Provider value={avisar}>{children}</ContextoAviso.Provider>;
}
export const useAvisar = () => useContext(ContextoAviso);

/** Executa uma ação com estado de "salvando" e aviso de erro. */
export function useAcao() {
  const avisar = useAvisar();
  const [ocupado, setOcupado] = useState(false);
  const executar = useCallback(async <T,>(fn: () => Promise<T>, sucesso?: string): Promise<T | undefined> => {
    setOcupado(true);
    try {
      const resultado = await fn();
      if (sucesso) avisar(sucesso);
      return resultado;
    } catch (e) {
      avisar((e as Error).message, "bad");
      return undefined;
    } finally {
      setOcupado(false);
    }
  }, [avisar]);
  return { ocupado, executar };
}

// --------------------------------------------------------------------------- peças
/** Última palavra do título em itálico serifado, no tom de destaque ("Avisos à *equipe*"). */
function tituloComDestaque(titulo: string): ReactNode {
  const partes = titulo.trim().split(" ");
  if (partes.length < 2) return <em className="destaque">{titulo}</em>;
  const ultima = partes.pop();
  return <>{partes.join(" ")} <em className="destaque">{ultima}</em></>;
}

export function Cabecalho({ eyebrow, titulo, texto, acoes }: { eyebrow?: string; titulo: string; texto?: ReactNode; acoes?: ReactNode }) {
  return (
    <div className="ph">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{tituloComDestaque(titulo)}</h1>
        {texto && <p>{texto}</p>}
      </div>
      {acoes && <div className="act">{acoes}</div>}
    </div>
  );
}

export function Painel({ titulo, acoes, children, sem_corpo }: { titulo?: ReactNode; acoes?: ReactNode; children: ReactNode; sem_corpo?: boolean }) {
  return (
    <section className="panel">
      {(titulo || acoes) && (
        <div className="panel-h">
          {typeof titulo === "string" ? <h3>{titulo}</h3> : titulo}
          {acoes && <div className="more">{acoes}</div>}
        </div>
      )}
      {sem_corpo ? children : <div className="panel-b">{children}</div>}
    </section>
  );
}

/** Alerta em linha. bad/warn são anunciados na hora por leitor de tela (role="alert"); info/ok, de forma educada (role="status"). */
export function Alerta({ tipo = "info", titulo, children }: { tipo?: "info" | "ok" | "warn" | "bad"; titulo?: ReactNode; children: ReactNode }) {
  const Icone = { info: Info, ok: CheckCircle2, warn: AlertTriangle, bad: XCircle }[tipo];
  return (
    <div className={`alerta ${tipo}`} role={tipo === "bad" || tipo === "warn" ? "alert" : "status"}>
      <Icone className="i" aria-hidden />
      <div>{titulo && <strong className="alerta-t">{titulo}</strong>}{children}</div>
    </div>
  );
}

export function Vazio({ children, icone }: { children: ReactNode; icone?: ReactNode }) {
  return <div className="vazio">{icone ?? <Inbox />}<div>{children}</div></div>;
}

export function Carregando({ erro }: { erro?: string | null }) {
  if (erro) return <Alerta tipo="bad">{erro}</Alerta>;
  return (
    <div className="esqueleto" role="status" aria-label="Carregando">
      <div className="carregando-brilho" style={{ height: 28, width: "40%" }} />
      <div className="carregando-brilho" style={{ height: 14, width: "70%" }} />
      <div className="carregando-brilho" style={{ height: 120 }} />
      <div className="carregando-brilho" style={{ height: 120 }} />
    </div>
  );
}

export function Interruptor({ ligado, aoMudar, desligado, rotulo }: { ligado: boolean; aoMudar: (v: boolean) => void; desligado?: boolean; rotulo: string }) {
  return (
    <button type="button" role="switch" aria-checked={ligado} aria-label={rotulo} disabled={desligado}
      className={`sw-t ${ligado ? "on" : ""}`} onClick={() => aoMudar(!ligado)} />
  );
}

// --------------------------------------------------------------------------- janelas (modal)
const FOCAVEIS = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
/** Pilha das janelas abertas: só a de cima responde ao Esc e prende o Tab (uma confirmação sobre outro modal fecha sozinha). */
const pilhaModais: symbol[] = [];

/**
 * Janela do painel. Ao abrir leva o foco para dentro (o elemento com `data-autofocus`, senão o primeiro campo,
 * senão o primeiro botão), prende o Tab lá dentro, fecha com Esc ou clique no fundo e devolve o foco a quem abriu.
 */
export function Modal({ titulo, texto, children, rodape, aoFechar, largura }: {
  titulo: string; texto?: ReactNode; children?: ReactNode; rodape: ReactNode; aoFechar: () => void; largura?: number;
}) {
  const caixa = useRef<HTMLDivElement>(null);
  const fechar = useRef(aoFechar);
  fechar.current = aoFechar;
  const abridor = useRef<HTMLElement | null>(null);
  const idTitulo = useId();
  const idTexto = useId();

  useEffect(() => {
    const eu = Symbol("modal");
    const no = caixa.current;
    pilhaModais.push(eu);
    if (!abridor.current) abridor.current = document.activeElement as HTMLElement | null;
    const anterior = abridor.current;
    const focaveis = () => Array.from(caixa.current?.querySelectorAll<HTMLElement>(FOCAVEIS) ?? [])
      .filter((el) => el.offsetParent !== null || el === document.activeElement);
    const inicial = caixa.current?.querySelector<HTMLElement>("[data-autofocus]")
      ?? caixa.current?.querySelector<HTMLElement>(".modal-b input:not([disabled]):not([type=hidden]):not([type=checkbox]), .modal-b select:not([disabled]), .modal-b textarea:not([disabled])")
      ?? focaveis()[0] ?? caixa.current;
    inicial?.focus({ preventScroll: true });

    const tecla = (e: KeyboardEvent) => {
      if (pilhaModais[pilhaModais.length - 1] !== eu) return;
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); fechar.current(); return; }
      if (e.key !== "Tab") return;
      const lista = focaveis();
      if (lista.length === 0) { e.preventDefault(); caixa.current?.focus(); return; }
      const primeiro = lista[0], ultimo = lista[lista.length - 1];
      const ativo = document.activeElement as HTMLElement | null;
      const dentro = Boolean(ativo && caixa.current?.contains(ativo));
      if (e.shiftKey && (ativo === primeiro || ativo === caixa.current || !dentro)) { e.preventDefault(); ultimo.focus(); }
      else if (!e.shiftKey && (ativo === ultimo || !dentro)) { e.preventDefault(); primeiro.focus(); }
    };
    document.addEventListener("keydown", tecla, true);
    return () => {
      document.removeEventListener("keydown", tecla, true);
      const i = pilhaModais.indexOf(eu);
      if (i >= 0) pilhaModais.splice(i, 1);
      // Devolve o foco a quem abriu, se ainda estiver na tela. (No StrictMode o efeito roda duas vezes com a
      // janela ainda montada; aí a caixa continua no documento e o foco fica onde está.)
      if (anterior && anterior !== document.body) requestAnimationFrame(() => {
        if (!no?.isConnected && document.contains(anterior)) anterior.focus({ preventScroll: true });
      });
    };
  }, []);

  // Desenhada no <body>: dentro da página (que tem animação) o fundo escuro não cobria a tela toda.
  return createPortal(
    <div className="ov" onMouseDown={(e) => { if (e.target === e.currentTarget) aoFechar(); }}>
      <div ref={caixa} className="modal outline-none" role="dialog" aria-modal="true" aria-labelledby={idTitulo} aria-describedby={texto ? idTexto : undefined}
        tabIndex={-1} style={largura ? { width: `min(${largura}px, calc(100% - 32px))` } : undefined}>
        <div className="modal-h"><h2 id={idTitulo}>{titulo}</h2>{texto && <p id={idTexto}>{texto}</p>}</div>
        {children != null && children !== false && <div className="modal-b">{children}</div>}
        <div className="modal-f">{rodape}</div>
      </div>
    </div>,
    document.body,
  );
}

// --------------------------------------------------------------------------- confirmação
export interface OpcoesConfirmar {
  titulo: string;
  texto?: ReactNode;
  /** Texto do botão que confirma (padrão "Confirmar"). */
  confirmar?: string;
  cancelar?: string;
  /** Ação destrutiva ou que mexe com quem está do outro lado: botão vermelho e o foco começa em "Cancelar". */
  perigo?: boolean;
}

/** Confirmação no estilo do painel, no lugar do window.confirm. Prefira o useConfirmar. */
export function ConfirmarModal({ titulo, texto, confirmar = "Confirmar", cancelar = "Cancelar", perigo, aoResponder }: OpcoesConfirmar & { aoResponder: (sim: boolean) => void }) {
  const Icone = perigo ? AlertTriangle : Info;
  const cor = perigo ? "var(--bad)" : "var(--acento-forte)";
  const suave = perigo ? "var(--bad-soft)" : "var(--acento-suave)";
  return (
    <Modal titulo={titulo} largura={460} aoFechar={() => aoResponder(false)}
      rodape={<>
        <span className="sp" />
        <button type="button" className="btn ghost" onClick={() => aoResponder(false)} data-autofocus={perigo ? "" : undefined}>{cancelar}</button>
        <button type="button" className="btn pri" onClick={() => aoResponder(true)} data-autofocus={perigo ? undefined : ""}
          style={perigo ? { background: "var(--bad)", borderColor: "var(--bad)", color: "#fff" } : undefined}>{confirmar}</button>
      </>}>
      {texto && (
        <div className="flex items-start gap-3">
          <span aria-hidden className="grid size-9 shrink-0 place-items-center rounded-xl" style={{ background: suave, color: cor }}><Icone size={18} /></span>
          <div className="pt-1.5 text-[13.5px] leading-relaxed" style={{ color: "var(--ink-2)" }}>{texto}</div>
        </div>
      )}
    </Modal>
  );
}

/**
 * Confirmação que devolve uma Promise<boolean>. Renderize o `janela` em qualquer lugar da tela.
 *   const [confirmar, janela] = useConfirmar();
 *   if (await confirmar({ titulo: "Apagar este aviso?", perigo: true })) ...
 */
export function useConfirmar(): [(opcoes: OpcoesConfirmar) => Promise<boolean>, ReactNode] {
  const [pedido, setPedido] = useState<(OpcoesConfirmar & { responder: (sim: boolean) => void }) | null>(null);
  const confirmar = useCallback((opcoes: OpcoesConfirmar) => new Promise<boolean>((resolver) => {
    setPedido({ ...opcoes, responder: (sim) => { setPedido(null); resolver(sim); } });
  }), []);
  const janela = pedido ? <ConfirmarModal {...pedido} aoResponder={pedido.responder} /> : null;
  return [confirmar, janela];
}

// --------------------------------------------------------------------------- senha provisória
/** Senha que só aparece uma vez: destaque, botão copiar e o aviso de que não volta. Igual em todas as telas. */
export function SenhaProvisoria({ senha, para, nota }: { senha: string; para?: string; nota?: ReactNode }) {
  const [copiada, setCopiada] = useState(false);
  const campo = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!copiada) return;
    const t = window.setTimeout(() => setCopiada(false), 2200);
    return () => window.clearTimeout(t);
  }, [copiada]);
  const copiar = async () => {
    try { await navigator.clipboard.writeText(senha); setCopiada(true); }
    catch {
      // Sem acesso à área de transferência: deixa o texto selecionado para Ctrl+C.
      const el = campo.current; const sel = window.getSelection();
      if (el && sel) { const r = document.createRange(); r.selectNodeContents(el); sel.removeAllRanges(); sel.addRange(r); }
    }
  };
  return (
    <div className="overflow-hidden rounded-2xl border animate-in fade-in zoom-in-95 duration-300"
      style={{ borderColor: "color-mix(in srgb, var(--acento) 35%, var(--line))", background: "linear-gradient(160deg, var(--acento-suave), var(--surface) 70%)" }}>
      <div className="flex items-center gap-3 px-4 pt-4">
        <span aria-hidden className="grid size-9 shrink-0 place-items-center rounded-xl text-white shadow-sm"
          style={{ backgroundImage: "linear-gradient(135deg, #2BD45A, var(--acento-forte))" }}><KeyRound size={17} /></span>
        <div className="min-w-0">
          <div className="text-[13px] font-semibold" style={{ color: "#0B7A2A" }}>Senha provisória{para ? ` de ${para}` : ""}</div>
          <div className="text-[12px]" style={{ color: "var(--ink-2)" }}>A pessoa troca por uma dela no primeiro acesso.</div>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2 px-4 py-3">
        <code ref={campo} className="min-w-0 flex-1 select-all break-all rounded-xl border px-3 py-2 text-[17px] font-semibold tracking-[.08em]"
          style={{ fontFamily: "var(--mono)", background: "var(--surface)", borderColor: "var(--line)", color: "var(--ink)" }}>{senha}</code>
        <button type="button" className={`btn ${copiada ? "" : "pri"}`} onClick={copiar} data-autofocus=""
          style={copiada ? { color: "var(--ok)", borderColor: "color-mix(in srgb, var(--ok) 40%, var(--line))" } : undefined}>
          {copiada ? <Check /> : <Copy />}{copiada ? "Copiada" : "Copiar"}
        </button>
        <span className="sr-only" role="status" aria-live="polite">{copiada ? "Senha copiada." : ""}</span>
      </div>
      <div className="flex items-start gap-2 border-t px-4 py-2.5 text-[12.5px]" style={{ borderColor: "var(--line)", background: "var(--warn-soft)", color: "#8A4B00" }}>
        <AlertTriangle size={14} className="mt-0.5 shrink-0" aria-hidden />
        <span><b>Ela não aparece de novo.</b> Copie agora e mande por um canal seguro.{nota ? <> {nota}</> : null}</span>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- linha de tabela clicável
const CLASSE_LINHA = "click outline-none active:![transform:none] focus-visible:![box-shadow:none] focus-visible:![outline:none] [&:focus-visible>td]:!bg-[var(--acento-suave)] [&:focus-visible>td:first-child]:shadow-[inset_3px_0_0_var(--acento)]";

/**
 * Props para uma <tr> que age como botão ou link: entra no Tab, Enter/Espaço acionam e o foco fica visível.
 *   <tr {...linhaClicavel(() => abrir(x), { rotulo: `Abrir ${x.nome}`, papel: "link" })}>
 */
export function linhaClicavel(acao: () => void, { rotulo, papel = "button", expandida, selecionada, classe = "" }: {
  rotulo?: string; papel?: "button" | "link"; expandida?: boolean; selecionada?: boolean; classe?: string;
} = {}) {
  return {
    tabIndex: 0,
    role: papel,
    "aria-label": rotulo,
    "aria-expanded": expandida,
    "aria-pressed": papel === "button" ? selecionada : undefined,
    className: `${CLASSE_LINHA} ${classe}`.trim(),
    onClick: (e: ReactMouseEvent<HTMLElement>) => {
      // Clique num controle dentro da linha (botão, link, select) não aciona a linha.
      const alvo = e.target as HTMLElement;
      if (alvo !== e.currentTarget && alvo.closest("button, a, select, input, textarea, label")) return;
      acao();
    },
    onKeyDown: (e: ReactKeyboardEvent<HTMLElement>) => {
      if (e.target !== e.currentTarget) return;
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); acao(); }
    },
  };
}

const SITUACOES: Record<string, [string, string]> = {
  ativo: ["ok", "ativo"], pausado: ["warn", "pausado"], encerrado: ["", "encerrado"],
  teste: ["info", "em teste"], producao: ["ok", "para todos"],
  ok: ["ok", "conectado"], erro: ["bad", "com erro"], pendente: ["warn", "pendente"], desligada: ["", "desligada"],
  critico: ["bad", "crítico"], aviso: ["warn", "aviso"], info: ["", "info"],
};

export function Situacao({ valor, texto }: { valor: string | null | undefined; texto?: string }) {
  const [classe, padrao] = SITUACOES[valor ?? ""] ?? ["", valor ?? "—"];
  return <span className={`chip ${classe}`}><span className="d" />{texto ?? padrao}</span>;
}

export function Iniciais({ nome }: { nome: string }) {
  const partes = nome.trim().split(/\s+/);
  const letras = ((partes[0]?.[0] ?? "") + (partes.length > 1 ? partes[partes.length - 1][0] : "")).toUpperCase();
  return <span className="av" aria-hidden>{letras || "?"}</span>;
}
