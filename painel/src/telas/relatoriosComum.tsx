/*
 * Peças comuns das telas de Relatórios (Dashboard e Rastreamento de campanhas), no visual do dashboard comercial
 * original da LawChat: barra de filtros (período em pílulas, "Mais" com calendário, modo e menus próprios com busca,
 * checkboxes e teclado), selo "Atualizado há", contador animado, entrada em cascata, esqueleto com brilho, funil em
 * degraus coloridos, mapa de calor, mapa do Brasil, detalhe do anúncio, exportar CSV e PDF. Animações respeitam
 * prefers-reduced-motion (MotionConfig nas telas + CSS).
 * Os números vêm prontos do servidor (/api/relatorios/*); aqui só formata e desenha.
 */
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { motion, type Variants } from "framer-motion";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip as RTooltip, XAxis, YAxis } from "recharts";
import {
  Bot, Calendar, Check, ChevronDown, ChevronLeft, ChevronRight, Clock, Copy, Download, ExternalLink, Facebook, FileCheck, FileDown, FileText, Filter, Globe,
  Info, Instagram, Kanban, Layers, Megaphone, MessageCircle, MousePointerClick, Music2, PenLine, Phone, RefreshCw, Search, Sparkles, Tag, TrendingUp,
  Trophy, UserCheck, UserRound, UserX, Users, X, Youtube,
} from "lucide-react";
import { toast } from "sonner";
import { useCarregar } from "../componentes/ui";
import { useSessao } from "../sessao";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { CONTORNO_ESTADOS, NOMES_ESTADOS } from "@/data/estadosBrasil";
import "../estilo-relatorios.css";

// --------------------------------------------------------------------------- formatos
export const fmtNum = (n: number | null | undefined) => (n == null ? "–" : Math.round(n).toLocaleString("pt-BR"));
export const fmtPct = (n: number | null | undefined, casas = 1) =>
  n == null ? "–" : `${n.toLocaleString("pt-BR", { maximumFractionDigits: casas, minimumFractionDigits: casas })}%`;
export const fmtBRL = (n: number | null | undefined) =>
  n == null ? "–" : n.toLocaleString("pt-BR", { style: "currency", currency: "BRL", minimumFractionDigits: 2 });
export const fmtDia = (d: string) => `${d.slice(8, 10)}/${d.slice(5, 7)}`;
export const fmtData = (d: string | null | undefined) => (d ? new Date(d).toLocaleDateString("pt-BR") : "–");
export function fmtHoras(h: number | null | undefined): string {
  if (h == null) return "–";
  if (h <= 0) return "0";
  if (h < 1) return `${Math.max(1, Math.round(h * 60))} min`;
  if (h < 24) return `${Math.round(h)}h`;
  const dias = Math.floor(h / 24);
  const resto = Math.round(h - dias * 24);
  return `${dias}d ${resto}h`;
}
export function fmtSegundos(s: number | null | undefined): string {
  if (s == null) return "–";
  if (s < 60) return `${Math.round(s)} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
  return fmtHoras(s / 3600);
}

// Cartão padrão (mesmas bordas, raio e sombra do dashboard original, com elevação no hover)
export const CARTAO = "rl-cartao relative rounded-2xl border border-white/70 bg-card shadow-[0_1px_3px_rgba(15,23,42,0.06),0_8px_24px_-12px_rgba(15,23,42,0.10)]";

// --------------------------------------------------------------------------- movimento
/** true quando a pessoa pediu menos movimento no sistema (prefers-reduced-motion). */
export function useReduzMovimento() {
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

/** Animação dos gráficos do recharts (desligada com prefers-reduced-motion). */
export function useAnimaGrafico(duracao = 1100) {
  const reduz = useReduzMovimento();
  return { isAnimationActive: !reduz, animationDuration: duracao, animationEasing: "ease-out" as const };
}

/** Fundo próprio da área dos Relatórios (só enquanto a tela está aberta; na impressão, branco). */
export function useFundoRelatorios() {
  useEffect(() => {
    document.documentElement.classList.add("rl-fundo-ativo");
    return () => document.documentElement.classList.remove("rl-fundo-ativo");
  }, []);
}

/** Entrada em cascata: cada filho sobe um pouco e aparece, um depois do outro. */
export function Cascata({ children, className, atraso = 0, passo = 0.06 }: { children: ReactNode; className?: string; atraso?: number; passo?: number }) {
  return (
    <motion.div className={className} initial="fora" animate="dentro"
      variants={{ fora: {}, dentro: { transition: { staggerChildren: passo, delayChildren: atraso } } }}>
      {children}
    </motion.div>
  );
}
export const ITEM_CASCATA: Variants = {
  fora: { opacity: 0, y: 16, scale: 0.985 },
  dentro: { opacity: 1, y: 0, scale: 1, transition: { duration: 0.55, ease: [0.16, 1, 0.3, 1] as [number, number, number, number] } },
};

/** Esqueleto com brilho enquanto os números chegam (mesma grade da tela). */
export function EsqueletoRelatorio({ erro, cartoes = 5 }: { erro?: string | null; cartoes?: number }) {
  if (erro) return <div className={cn(CARTAO, "p-6 text-sm text-destructive")}>{erro}</div>;
  const Bloco = ({ className }: { className?: string }) => <div className={cn("rl-brilho rounded-2xl", className)} />;
  return (
    <div className="space-y-5" role="status" aria-label="Carregando os números">
      <div className={cn("grid grid-cols-2 gap-4 md:grid-cols-3", cartoes === 4 ? "lg:grid-cols-4" : "xl:grid-cols-5")}>
        {Array.from({ length: cartoes }, (_, i) => <Bloco key={i} className="h-[150px]" />)}
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 xl:grid-cols-8">
        {Array.from({ length: 8 }, (_, i) => <Bloco key={i} className="h-[86px] rounded-xl" />)}
      </div>
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-5">
        <Bloco className="h-[420px] lg:col-span-3" /><Bloco className="h-[420px] lg:col-span-2" />
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- filtros (na URL)
export const PERIODOS: { valor: string; rotulo: string }[] = [
  { valor: "hoje", rotulo: "Hoje" }, { valor: "ontem", rotulo: "Ontem" }, { valor: "7", rotulo: "7 dias" },
  { valor: "30", rotulo: "30 dias" }, { valor: "mes", rotulo: "Este mês" },
  { valor: "tudo", rotulo: "Todo Período" }, { valor: "90", rotulo: "Últimos 90 dias" }, { valor: "mes_passado", rotulo: "Mês passado" },
  { valor: "ano", rotulo: "Últimos 12 meses" },
];
const NA_LINHA = ["hoje", "ontem", "7", "30", "mes"];

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

export function intervaloDoPeriodo(periodo: string): { de: string; ate: string } {
  const hoje = new Date();
  const menos = (dias: number) => { const d = new Date(hoje); d.setDate(d.getDate() - dias); return d; };
  switch (periodo) {
    case "hoje": return { de: iso(hoje), ate: iso(hoje) };
    case "ontem": return { de: iso(menos(1)), ate: iso(menos(1)) };
    case "7": return { de: iso(menos(6)), ate: iso(hoje) };
    case "90": return { de: iso(menos(89)), ate: iso(hoje) };
    case "ano": return { de: iso(menos(364)), ate: iso(hoje) };
    case "tudo": return { de: iso(menos(399)), ate: iso(hoje) };
    case "mes": return { de: iso(new Date(hoje.getFullYear(), hoje.getMonth(), 1)), ate: iso(hoje) };
    case "mes_passado": return {
      de: iso(new Date(hoje.getFullYear(), hoje.getMonth() - 1, 1)), ate: iso(new Date(hoje.getFullYear(), hoje.getMonth(), 0)) };
    default: return { de: iso(menos(29)), ate: iso(hoje) };
  }
}

export interface Filtros {
  periodo: string; de: string; ate: string; agente: string; campanha: string; fonte: string;
  modo: "criacao" | "atualizacao"; painel: string[]; etapa: string[]; responsavel: string[]; numero: string[]; tag: string[];
}
type Lista = "painel" | "etapa" | "responsavel" | "numero" | "tag";
const LISTAS: Lista[] = ["painel", "etapa", "responsavel", "numero", "tag"];
type Mudanca = Partial<Omit<Filtros, Lista>> & Partial<Record<Lista, string[]>>;

export function useFiltros() {
  const [params, setParams] = useSearchParams();
  const filtros: Filtros = useMemo(() => {
    const periodo = params.get("periodo") || (params.get("de") ? "personalizado" : "30");
    const intervalo = periodo === "personalizado"
      ? { de: params.get("de") || intervaloDoPeriodo("30").de, ate: params.get("ate") || iso(new Date()) }
      : intervaloDoPeriodo(periodo);
    const lista = (k: string) => (params.get(k) || "").split(",").map((x) => x.trim()).filter(Boolean);
    return { periodo, ...intervalo, agente: params.get("agente") || "", campanha: params.get("campanha") || "",
             fonte: params.get("fonte") || "", modo: params.get("modo") === "atualizacao" ? "atualizacao" : "criacao",
             painel: lista("painel"), etapa: lista("etapa"), responsavel: lista("responsavel"), numero: lista("numero"), tag: lista("tag") };
  }, [params]);
  const mudar = (novo: Mudanca) => {
    const proximo = new URLSearchParams(params);
    for (const [chave, valor] of Object.entries(novo)) {
      const texto = Array.isArray(valor) ? valor.join(",") : valor;
      if (texto && !(chave === "modo" && texto === "criacao")) proximo.set(chave, texto); else proximo.delete(chave);
    }
    if (novo.periodo && novo.periodo !== "personalizado") { proximo.delete("de"); proximo.delete("ate"); }
    if (novo.periodo === "30") proximo.delete("periodo");
    setParams(proximo, { replace: true });
  };
  const q = new URLSearchParams({ de: filtros.de, ate: filtros.ate });
  if (filtros.periodo === "tudo") q.set("tudo", "1");
  for (const k of ["agente", "campanha", "fonte"] as const) if (filtros[k]) q.set(k, filtros[k]);
  if (filtros.modo === "atualizacao") q.set("modo", "atualizacao");
  for (const k of LISTAS) for (const v of filtros[k]) q.append(k, v);
  return { filtros, mudar, consulta: q.toString() };
}

export interface OpcoesFiltro {
  agentes: { id: string; nome: string; situacao: string }[];
  campanhas: { campanha: string; leads: number }[];
  plataformas: { valor: string; rotulo: string }[];
  etapas?: { valor: string; rotulo: string }[];
  paineis?: { id: string; titulo: string | null; cards: number }[];
  responsaveis?: { id: string; nome: string; cards: number }[];
  numeros?: { numero: string; cards: number }[];
  tags?: { nome: string; cards: number }[];
}

export function useOpcoesFiltro() {
  const { escritorio } = useSessao();
  return useCarregar<OpcoesFiltro>(escritorio ? "/relatorios/filtros" : null, [escritorio]);
}

/** (31) 95347-1309 a partir de 5531953471309. */
export function fmtTelefone(n: string) {
  const d = n.replace(/\D/g, "").replace(/^55(?=\d{10,11}$)/, "");
  if (d.length === 11) return `(${d.slice(0, 2)}) ${d.slice(2, 7)}-${d.slice(7)}`;
  if (d.length === 10) return `(${d.slice(0, 2)}) ${d.slice(2, 6)}-${d.slice(6)}`;
  return n;
}

/** Selo colorido de cada origem (ícone branco no fundo da cor da plataforma). */
export function SeloOrigem({ valor, tamanho = "h-5 w-5" }: { valor: string; tamanho?: string }) {
  const visual: Record<string, { fundo: string; icone: ReactNode }> = {
    instagram: { fundo: "linear-gradient(135deg,#f58529,#dd2a7b 55%,#8134af)", icone: <Instagram className="h-3 w-3" /> },
    facebook: { fundo: "linear-gradient(135deg,#3b82f6,#1d4ed8)", icone: <Facebook className="h-3 w-3" /> },
    google: { fundo: "conic-gradient(from 200deg,#ea4335,#fbbc05,#34a853,#4285f4,#ea4335)", icone: <span className="text-[10px] font-black leading-none">G</span> },
    youtube: { fundo: "linear-gradient(135deg,#f87171,#dc2626)", icone: <Youtube className="h-3 w-3" /> },
    tiktok: { fundo: "linear-gradient(135deg,#0f172a,#334155)", icone: <Music2 className="h-3 w-3" /> },
    outro: { fundo: "linear-gradient(135deg,#22d3ee,#0891b2)", icone: <Globe className="h-3 w-3" /> },
    direto: { fundo: "linear-gradient(135deg,#cbd5e1,#94a3b8)", icone: <MousePointerClick className="h-3 w-3" /> },
  };
  const v = visual[valor] ?? visual.outro;
  return <span className={cn("flex shrink-0 items-center justify-center rounded-md text-white shadow-sm", tamanho)} style={{ background: v.fundo }}>{v.icone}</span>;
}

export const COR_ETAPA: Record<string, string> = {
  sdr: "#2563eb", closer: "#0891b2", analise: "#7c3aed", contratos: "#ea580c", assinatura: "#16a34a", assinado: "#eab308",
  desqualificado: "#dc2626", nao_assinou: "#db2777", outra: "#64748b",
};

interface OpcaoMenu { valor: string; rotulo: string; sub?: string; icone?: ReactNode }

/**
 * Menu de filtro no estilo do painel: botão com ícone, valor escolhido e seta; painel flutuante arredondado com
 * sombra, item "Todos…" em destaque, busca quando a lista é longa, checkboxes na multi-seleção (com Selecionar
 * todos / Limpar), marcação do escolhido, setas do teclado, Esc e clique fora fecham.
 */
export function MenuFiltro({ icone, textoTodos, opcoes, valor, aoMudar, multi = false, totalTodos, buscaRotulo, largura = 300, vazio, resumo }: {
  icone: ReactNode; textoTodos: string; opcoes: OpcaoMenu[]; valor: string[]; aoMudar: (v: string[]) => void; multi?: boolean;
  totalTodos?: string; buscaRotulo?: string; largura?: number; vazio?: string; resumo?: (escolhidas: OpcaoMenu[]) => string;
}) {
  const [aberto, setAberto] = useState(false);
  const [busca, setBusca] = useState("");
  const lista = useRef<HTMLDivElement>(null);
  const comBusca = opcoes.length > 8;
  const q = busca.trim().toLowerCase();
  const filtradas = q ? opcoes.filter((o) => `${o.rotulo} ${o.sub ?? ""}`.toLowerCase().includes(q)) : opcoes;
  const escolhidas = opcoes.filter((o) => valor.includes(o.valor));
  const texto = !valor.length ? textoTodos
    : resumo ? resumo(escolhidas)
    : escolhidas.length === 1 ? escolhidas[0].rotulo
    : escolhidas.length ? `${escolhidas.length} selecionados` : valor[0];
  const escolher = (v: string) => {
    if (!multi) { aoMudar(v ? [v] : []); setAberto(false); setBusca(""); return; }
    aoMudar(!v ? [] : valor.includes(v) ? valor.filter((x) => x !== v) : [...valor, v]);
  };
  const mover = (e: React.KeyboardEvent) => {
    const itens = Array.from(lista.current?.querySelectorAll<HTMLElement>("[data-opcao]") ?? []);
    if (!itens.length) return;
    const atual = itens.indexOf(document.activeElement as HTMLElement);
    let prox = -1;
    if (e.key === "ArrowDown") prox = atual < 0 ? 0 : Math.min(itens.length - 1, atual + 1);
    else if (e.key === "ArrowUp") prox = atual <= 0 ? 0 : atual - 1;
    else if (e.key === "Home") prox = 0;
    else if (e.key === "End") prox = itens.length - 1;
    if (prox >= 0) { e.preventDefault(); itens[prox].focus(); }
  };
  const Marca = ({ ativo }: { ativo: boolean }) => multi
    ? <span className={cn("flex h-4 w-4 shrink-0 items-center justify-center rounded-[5px] border transition-colors",
        ativo ? "border-emerald-500 bg-emerald-500 text-white" : "border-slate-300 bg-white")}>{ativo && <Check className="h-3 w-3" strokeWidth={3} />}</span>
    : <Check className={cn("h-4 w-4 shrink-0 text-emerald-600 transition-opacity", ativo ? "opacity-100" : "opacity-0")} />;
  return (
    <Popover open={aberto} onOpenChange={(v) => { setAberto(v); if (!v) setBusca(""); }}>
      <PopoverTrigger asChild>
        <button type="button" aria-haspopup="listbox"
          className={cn("rl-menu-botao group inline-flex h-9 max-w-[240px] items-center gap-2 max-sm:w-full max-sm:max-w-none rounded-xl border bg-white px-3 text-sm font-medium text-foreground shadow-[0_1px_2px_rgba(15,23,42,0.05)] transition-all hover:-translate-y-px hover:border-emerald-300 hover:shadow-md data-[state=open]:border-emerald-500 data-[state=open]:ring-2 data-[state=open]:ring-emerald-500/20",
            valor.length ? "border-emerald-300 bg-emerald-50/60" : "border-slate-200")}>
          <span className="shrink-0 text-emerald-600">{icone}</span>
          <span className="truncate">{texto}</span>
          {multi && valor.length > 1 && <span className="rounded-full bg-emerald-500 px-1.5 text-[10px] font-bold text-white">{valor.length}</span>}
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform duration-200 group-data-[state=open]:rotate-180" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" sideOffset={6} className="rl-menu overflow-hidden rounded-2xl border border-slate-200/80 p-0 shadow-[0_18px_48px_-12px_rgba(15,23,42,0.28)]"
        style={{ width: largura }} onKeyDown={mover} onOpenAutoFocus={(e) => { if (!comBusca) { e.preventDefault(); lista.current?.querySelector<HTMLElement>("[data-opcao]")?.focus(); } }}>
        {comBusca && (
          <div className="border-b border-slate-100 p-2">
            <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 focus-within:border-emerald-400 focus-within:ring-2 focus-within:ring-emerald-500/15">
              <Search className="h-3.5 w-3.5 text-muted-foreground" />
              <input value={busca} onChange={(e) => setBusca(e.target.value)} placeholder={buscaRotulo ?? "Buscar…"} aria-label={buscaRotulo ?? "Buscar"}
                className="flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground" />
            </div>
          </div>
        )}
        {multi && (
          <div className="flex items-center justify-between border-b border-slate-100 px-3 py-1.5 text-xs">
            <button type="button" onClick={() => aoMudar(Array.from(new Set([...valor, ...filtradas.map((o) => o.valor)])))}
              className="font-semibold text-emerald-600 transition-colors hover:text-emerald-700">Selecionar todos</button>
            <button type="button" onClick={() => aoMudar([])} className="text-muted-foreground transition-colors hover:text-foreground">Limpar</button>
          </div>
        )}
        <div ref={lista} role="listbox" aria-multiselectable={multi || undefined} className="max-h-[300px] space-y-0.5 overflow-y-auto p-1.5">
          <button type="button" data-opcao role="option" aria-selected={!valor.length} onClick={() => escolher("")}
            className={cn("flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm outline-none transition-colors focus-visible:ring-2 focus-visible:ring-emerald-500/40",
              !valor.length ? "bg-emerald-50 font-semibold text-emerald-700" : "text-foreground hover:bg-slate-50")}>
            <Marca ativo={!valor.length} /><span className="flex-1 truncate">{textoTodos}</span>
            {totalTodos && <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{totalTodos}</span>}
          </button>
          {filtradas.map((o) => {
            const ativo = valor.includes(o.valor);
            return (
              <button key={o.valor} type="button" data-opcao role="option" aria-selected={ativo} onClick={() => escolher(o.valor)} title={o.rotulo}
                className={cn("flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm outline-none transition-colors focus-visible:ring-2 focus-visible:ring-emerald-500/40",
                  ativo ? "bg-emerald-50/70 font-medium text-foreground" : "text-foreground hover:bg-slate-50")}>
                <Marca ativo={ativo} />
                {o.icone}
                <span className="min-w-0 flex-1 truncate">{o.rotulo}</span>
                {o.sub && <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{o.sub}</span>}
              </button>
            );
          })}
          {!filtradas.length && <p className="px-3 py-5 text-center text-xs text-muted-foreground">{q ? "Nada encontrado" : vazio ?? "Nenhuma opção ainda"}</p>}
        </div>
      </PopoverContent>
    </Popover>
  );
}

function GrupoFiltro({ rotulo, children, className }: { rotulo: string; children: ReactNode; className?: string }) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-1", rotulo !== "Período" && "max-sm:basis-[calc(50%-0.5rem)]", className)}>
      <span className="pl-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-slate-500">{rotulo}</span>
      <div className="flex flex-wrap items-center gap-1.5">{children}</div>
    </div>
  );
}

const fmtCurta = (d: string) => `${d.slice(8, 10)}/${d.slice(5, 7)}`;

export type CampoFiltro = "modo" | "campanha" | "painel" | "etapa" | "responsavel" | "numero" | "origem" | "tags" | "agente";

/** Barra de filtros: período em pílulas + "Mais" (com calendário) e os menus, numa barra limpa que quebra no celular. */
export function BarraFiltros({ filtros, mudar, aoAtualizar, atualizando, id, campos, gerado }: {
  filtros: Filtros; mudar: (f: Mudanca) => void; aoAtualizar: () => void; atualizando?: boolean; id: string;
  campos: CampoFiltro[]; gerado?: string | null;
}) {
  const opcoes = useOpcoesFiltro();
  const o = opcoes.dados;
  const [maisAberto, setMaisAberto] = useState(false);
  const tem = (c: CampoFiltro) => campos.includes(c);
  const ativoNaLinha = NA_LINHA.includes(filtros.periodo);
  const rotuloMais = filtros.periodo === "personalizado" ? `${fmtCurta(filtros.de)} → ${fmtCurta(filtros.ate)}`
    : !ativoNaLinha ? PERIODOS.find((p) => p.valor === filtros.periodo)?.rotulo ?? "Mais" : "Mais";
  const qtd = [filtros.agente, filtros.campanha, filtros.fonte, ...LISTAS.map((k) => filtros[k].join(""))].filter(Boolean).length
    + (filtros.modo === "atualizacao" ? 1 : 0);
  const limpar = () => mudar({ agente: "", campanha: "", fonte: "", periodo: "30", modo: "criacao", painel: [], etapa: [], responsavel: [], numero: [], tag: [] });
  const totalCampanhas = (o?.campanhas ?? []).reduce((s, c) => s + c.leads, 0);
  const periodoTexto = filtros.periodo === "tudo" ? "todo o período" : textoPeriodo(filtros.de, filtros.ate);
  const pilula = (ativo: boolean) => cn("relative z-10 inline-flex h-8 items-center gap-1 whitespace-nowrap rounded-lg px-3 text-xs font-semibold transition-colors",
    ativo ? "text-white" : "text-slate-600 hover:bg-white hover:text-foreground");
  const Fundo = () => <motion.span layoutId={`pilula-periodo-${id}`} className="absolute inset-0 -z-10 rounded-lg"
    style={{ background: "linear-gradient(135deg,#34d36b,#0ea64a)", boxShadow: "0 6px 14px -6px rgba(16,185,129,.55)" }}
    transition={{ type: "spring", stiffness: 420, damping: 32 }} />;

  return (
    <div className="rl-barra relative z-30 rounded-2xl border border-white/80 bg-white/75 p-3 shadow-[0_1px_2px_rgba(15,23,42,0.04),0_10px_30px_-18px_rgba(15,23,42,0.25)] backdrop-blur-md print:hidden md:p-4"
      role="group" aria-label="Filtros do relatório">
      <div className="flex flex-wrap items-end gap-x-4 gap-y-3">
        <GrupoFiltro rotulo="Período">
          <div className="flex flex-wrap items-center gap-0.5 rounded-xl bg-slate-100/80 p-0.5" role="radiogroup" aria-label="Período">
            {PERIODOS.filter((p) => NA_LINHA.includes(p.valor)).map((p) => {
              const ativo = filtros.periodo === p.valor;
              return (
                <button key={p.valor} type="button" role="radio" aria-checked={ativo} onClick={() => mudar({ periodo: p.valor })} className={pilula(ativo)}>
                  {ativo && <Fundo />}{p.rotulo}
                </button>
              );
            })}
            <Popover open={maisAberto} onOpenChange={setMaisAberto}>
              <PopoverTrigger asChild>
                <button type="button" className={pilula(!ativoNaLinha)} aria-label="Mais períodos">
                  {!ativoNaLinha && <Fundo />}
                  <Calendar className="h-3.5 w-3.5" />{rotuloMais}<ChevronDown className="h-3 w-3" />
                </button>
              </PopoverTrigger>
              <PopoverContent className="w-auto overflow-hidden rounded-2xl border-slate-200/80 p-0 shadow-[0_18px_48px_-12px_rgba(15,23,42,0.28)]" align="start" sideOffset={6}>
                <div className="min-w-[240px] space-y-0.5 p-1.5">
                  {PERIODOS.filter((p) => !NA_LINHA.includes(p.valor)).map((p) => (
                    <button key={p.valor} type="button" onClick={() => { mudar({ periodo: p.valor }); setMaisAberto(false); }}
                      className={cn("flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition-colors",
                        filtros.periodo === p.valor ? "bg-emerald-50 font-semibold text-emerald-700" : "text-foreground hover:bg-slate-50")}>
                      <Check className={cn("h-4 w-4 text-emerald-600", filtros.periodo === p.valor ? "opacity-100" : "opacity-0")} />{p.rotulo}
                    </button>
                  ))}
                </div>
                <div className="space-y-2 border-t border-slate-100 bg-slate-50/60 p-3">
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Intervalo personalizado</span>
                  <div className="flex items-center gap-2">
                    <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">De
                      <input type="date" value={filtros.de} max={filtros.ate} className="h-8 rounded-lg border border-slate-200 bg-white px-2 text-xs text-foreground focus:border-emerald-400 focus:outline-none focus:ring-2 focus:ring-emerald-500/15"
                        onChange={(e) => e.target.value && mudar({ periodo: "personalizado", de: e.target.value, ate: filtros.ate })} />
                    </label>
                    <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">Até
                      <input type="date" value={filtros.ate} min={filtros.de} className="h-8 rounded-lg border border-slate-200 bg-white px-2 text-xs text-foreground focus:border-emerald-400 focus:outline-none focus:ring-2 focus:ring-emerald-500/15"
                        onChange={(e) => e.target.value && mudar({ periodo: "personalizado", de: filtros.de, ate: e.target.value })} />
                    </label>
                  </div>
                </div>
              </PopoverContent>
            </Popover>
          </div>
        </GrupoFiltro>

        {tem("modo") && (
          <GrupoFiltro rotulo="Modo">
            <div className="flex items-center gap-0.5 rounded-xl bg-slate-100/80 p-0.5 max-sm:w-full" role="radiogroup" aria-label="Data do card que conta">
              {([["criacao", "Criação"], ["atualizacao", "Atualização"]] as const).map(([v, r]) => (
                <button key={v} type="button" role="radio" aria-checked={filtros.modo === v} onClick={() => mudar({ modo: v })} className={pilula(filtros.modo === v)}
                  title={v === "criacao" ? "Conta os cards pela data de criação" : "Conta os cards pela data da última atualização"}>
                  {filtros.modo === v && <motion.span layoutId={`pilula-modo-${id}`} className="absolute inset-0 -z-10 rounded-lg"
                    style={{ background: "linear-gradient(135deg,#34d36b,#0ea64a)" }} transition={{ type: "spring", stiffness: 420, damping: 32 }} />}
                  {r}
                </button>
              ))}
            </div>
          </GrupoFiltro>
        )}

        {tem("campanha") && (
          <GrupoFiltro rotulo="Campanha">
            <MenuFiltro icone={<Filter className="h-4 w-4" />} textoTodos="Todas campanhas" buscaRotulo="Buscar campanha…" largura={360}
              totalTodos={`${fmtNum(totalCampanhas)} leads`} valor={filtros.campanha ? [filtros.campanha] : []}
              aoMudar={(v) => mudar({ campanha: v[0] ?? "" })} vazio="Nenhuma campanha com UTM ainda"
              opcoes={[...(filtros.campanha && !(o?.campanhas ?? []).some((c) => c.campanha === filtros.campanha) ? [{ campanha: filtros.campanha, leads: 0 }] : []),
                ...(o?.campanhas ?? [])].sort((a, b) => b.leads - a.leads).map((c) => ({ valor: c.campanha, rotulo: c.campanha, sub: `${fmtNum(c.leads)} leads` }))} />
          </GrupoFiltro>
        )}
        {tem("painel") && (
          <GrupoFiltro rotulo="Painel CRM">
            <MenuFiltro multi icone={<Kanban className="h-4 w-4" />} textoTodos="Todos os Painéis" valor={filtros.painel} aoMudar={(v) => mudar({ painel: v })}
              vazio="Os painéis aparecem depois da conferência do CRM"
              opcoes={(o?.paineis ?? []).map((p) => ({ valor: p.id, rotulo: p.titulo || "Painel sem nome", sub: fmtNum(p.cards) }))} />
          </GrupoFiltro>
        )}
        {tem("etapa") && (
          <GrupoFiltro rotulo="Etapa">
            <MenuFiltro multi icone={<Layers className="h-4 w-4" />} textoTodos="Todas etapas" valor={filtros.etapa} aoMudar={(v) => mudar({ etapa: v })}
              opcoes={(o?.etapas ?? []).filter((e) => e.valor !== "outra").map((e) => ({ valor: e.valor, rotulo: e.rotulo,
                icone: <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: COR_ETAPA[e.valor] }} /> }))} />
          </GrupoFiltro>
        )}
        {tem("responsavel") && (
          <GrupoFiltro rotulo="Responsável">
            <MenuFiltro multi icone={<UserRound className="h-4 w-4" />} textoTodos="Todos" buscaRotulo="Buscar atendente…" valor={filtros.responsavel}
              aoMudar={(v) => mudar({ responsavel: v })} vazio="Nenhum card com responsável ainda"
              opcoes={(o?.responsaveis ?? []).map((r) => ({ valor: r.id, rotulo: r.nome, sub: fmtNum(r.cards),
                icone: <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-emerald-400 to-teal-500 text-[9px] font-bold text-white">{(r.nome || "?").slice(0, 1).toUpperCase()}</span> }))} />
          </GrupoFiltro>
        )}
        {tem("numero") && (
          <GrupoFiltro rotulo="Número">
            <MenuFiltro multi icone={<Phone className="h-4 w-4" />} textoTodos="Todos os números" buscaRotulo="Buscar número…" valor={filtros.numero}
              aoMudar={(v) => mudar({ numero: v })} vazio="Nenhum número de WhatsApp ligado"
              opcoes={(o?.numeros ?? []).map((n) => ({ valor: n.numero, rotulo: fmtTelefone(n.numero), sub: n.cards ? fmtNum(n.cards) : undefined }))} />
          </GrupoFiltro>
        )}
        {tem("agente") && (
          <GrupoFiltro rotulo="Agente">
            <MenuFiltro icone={<Bot className="h-4 w-4" />} textoTodos="Todos os agentes" valor={filtros.agente ? [filtros.agente] : []}
              aoMudar={(v) => mudar({ agente: v[0] ?? "" })}
              opcoes={(o?.agentes ?? []).map((a) => ({ valor: a.id, rotulo: a.nome, sub: a.situacao !== "ativo" ? "pausado" : undefined }))} />
          </GrupoFiltro>
        )}
        {tem("origem") && (
          <GrupoFiltro rotulo="Origem">
            <MenuFiltro icone={<Megaphone className="h-4 w-4" />} textoTodos="Todas as origens" valor={filtros.fonte ? [filtros.fonte] : []}
              aoMudar={(v) => mudar({ fonte: v[0] ?? "" })}
              opcoes={(o?.plataformas ?? []).map((p) => ({ valor: p.valor, rotulo: p.rotulo, icone: <SeloOrigem valor={p.valor} /> }))} />
          </GrupoFiltro>
        )}
        {tem("tags") && (
          <GrupoFiltro rotulo="Tags">
            <MenuFiltro multi icone={<Tag className="h-4 w-4" />} textoTodos="Todas as tags" buscaRotulo="Buscar tag…" valor={filtros.tag}
              aoMudar={(v) => mudar({ tag: v })} vazio="Nenhuma etiqueta nos cards ainda"
              opcoes={(o?.tags ?? []).map((t) => ({ valor: t.nome, rotulo: t.nome, sub: fmtNum(t.cards),
                icone: <Tag className="h-3.5 w-3.5 shrink-0 text-emerald-500" /> }))} />
          </GrupoFiltro>
        )}

        <div className="ml-auto flex items-end gap-2">
          {qtd > 0 && (
            <button type="button" onClick={limpar}
              className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-red-200 bg-white px-3 text-sm font-medium text-red-600 transition-all hover:-translate-y-px hover:bg-red-50 active:translate-y-0">
              <X className="h-3.5 w-3.5" />Limpar<span className="rounded-full bg-red-100 px-1.5 text-[10px] font-bold">{qtd}</span>
            </button>
          )}
          <button type="button" onClick={aoAtualizar} disabled={atualizando}
            className="btn-lawchat inline-flex h-9 items-center gap-1.5 rounded-xl px-4 text-sm font-semibold active:scale-[0.98]">
            <RefreshCw className={cn("relative z-10 h-3.5 w-3.5", atualizando && "animate-spin")} />
            <span className="relative z-10">Atualizar</span>
          </button>
        </div>
      </div>
      <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-slate-100 pt-2 text-[11px] text-slate-500">
        <span className="inline-flex items-center gap-1.5"><Calendar className="h-3 w-3" />Mostrando {periodoTexto}</span>
        {gerado && <SeloAtualizado data={gerado} aoAtualizar={aoAtualizar} atualizando={atualizando} discreto />}
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- cabeçalho
function relativo(d: Date): string {
  const m = Math.floor((Date.now() - d.getTime()) / 60000);
  if (m < 1) return "agora mesmo";
  if (m < 60) return `há ${m} min`;
  const h = Math.floor(m / 60);
  if (h < 24) return `há ${h}h`;
  return `há ${Math.floor(h / 24)}d`;
}

/** Selo "Atualizado há X min" (verde = recente; âmbar = mais de 2 h). Clique busca os números de novo. */
export function SeloAtualizado({ data, aoAtualizar, atualizando, discreto }: { data: string | null | undefined; aoAtualizar: () => void; atualizando?: boolean; discreto?: boolean }) {
  const [, setTique] = useState(0);
  useEffect(() => { const id = window.setInterval(() => setTique((t) => t + 1), 30000); return () => window.clearInterval(id); }, []);
  if (!data) return null;
  const quando = new Date(data);
  const velho = Date.now() - quando.getTime() > 2 * 3600000;
  return (
    <button type="button" onClick={aoAtualizar} title={`Dados de ${quando.toLocaleString("pt-BR")}. Clique para atualizar.`}
      className={cn("flex shrink-0 items-center gap-2 font-medium transition-colors print:hidden",
        discreto ? "text-[11px] text-slate-500 hover:text-foreground"
          : "rounded-full border border-border/60 bg-card px-3 py-1.5 text-xs text-muted-foreground shadow-[0_1px_2px_rgba(15,23,42,0.04)] hover:bg-secondary hover:text-foreground")}>
      <span className="relative flex h-2 w-2">
        <span className={cn("absolute inline-flex h-full w-full animate-ping rounded-full opacity-75", velho ? "bg-amber-400" : "bg-emerald-400")} />
        <span className={cn("relative inline-flex h-2 w-2 rounded-full", velho ? "bg-amber-500" : "bg-emerald-500")} />
      </span>
      <span>Atualizado {relativo(quando)}</span>
      <RefreshCw className={cn("h-3 w-3", atualizando && "animate-spin")} />
    </button>
  );
}

// --------------------------------------------------------------------------- contador animado
/** Número que conta de 0 até o valor (ao montar) e do valor antigo ao novo; sem animação com prefers-reduced-motion. */
export function Contador({ valor, casas = 0, sufixo = "", prefixo = "", duracao = 1200 }: {
  valor: number; casas?: number; sufixo?: string; prefixo?: string; duracao?: number;
}) {
  const [mostrado, setMostrado] = useState(0);
  const atual = useRef(0);
  useEffect(() => {
    const reduzir = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
    const de = atual.current;
    if (reduzir || de === valor) { atual.current = valor; setMostrado(valor); return; }
    let quadro = 0;
    let inicio: number | null = null;
    const passo = (t: number) => {
      if (inicio === null) inicio = t;
      const p = Math.min((t - inicio) / duracao, 1);
      const v = de + (valor - de) * (p === 1 ? 1 : 1 - Math.pow(1 - p, 4));
      atual.current = v;
      setMostrado(v);
      if (p < 1) quadro = requestAnimationFrame(passo);
    };
    quadro = requestAnimationFrame(passo);
    // Em aba de fundo o requestAnimationFrame para: o valor final aparece mesmo assim.
    const reserva = window.setTimeout(() => { cancelAnimationFrame(quadro); atual.current = valor; setMostrado(valor); }, duracao + 300);
    return () => { cancelAnimationFrame(quadro); window.clearTimeout(reserva); };
  }, [valor, duracao]);
  return <>{prefixo}{mostrado.toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas })}{sufixo}</>;
}

export function Dica({ texto, tamanho = "h-3 w-3" }: { texto: ReactNode; tamanho?: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild><Info className={cn(tamanho, "shrink-0 cursor-help text-muted-foreground/50")} /></TooltipTrigger>
      <TooltipContent className="max-w-[240px] text-xs">{texto}</TooltipContent>
    </Tooltip>
  );
}

export function Vazio({ children, icone }: { children: ReactNode; icone?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center py-8 text-center">
      {icone && <span className="mb-2 text-muted-foreground/30">{icone}</span>}
      <p className="text-sm text-muted-foreground">{children}</p>
    </div>
  );
}

/** Abas em "pílula": a aba ativa desliza (fundo branco com sombra) e o conteúdo troca sem piscar. */
export function Abas<T extends string>({ valor, opcoes, aoMudar, cheia }: {
  valor: T; opcoes: { valor: NoInfer<T>; rotulo: ReactNode }[]; aoMudar: (v: NoInfer<T>) => void; cheia?: boolean;
}) {
  const id = useId();
  return (
    <div className={cn("flex gap-1 rounded-xl bg-slate-100/80 p-1", !cheia && "w-fit")} role="tablist">
      {opcoes.map((o) => (
        <button key={o.valor} type="button" role="tab" aria-selected={valor === o.valor} onClick={() => aoMudar(o.valor)}
          className={cn("relative z-10 flex items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors", cheia && "flex-1",
            valor === o.valor ? "text-foreground" : "text-muted-foreground hover:text-foreground")}>
          {valor === o.valor && <motion.span layoutId={`aba-${id}`} className="absolute inset-0 -z-10 rounded-lg bg-white shadow-[0_1px_3px_rgba(15,23,42,0.12)]"
            transition={{ type: "spring", stiffness: 420, damping: 34 }} />}
          {o.rotulo}
        </button>
      ))}
    </div>
  );
}

/** Botões do fim da página: PDF (imprimir) e CSV. */
export function BotoesExportar({ csv }: { csv: { rotulo: string; aoClicar: () => void }[] }) {
  return (
    <div className="flex flex-wrap justify-center gap-3 pb-4 print:hidden">
      <button type="button" onClick={() => window.print()}
        className="flex items-center gap-2 rounded-lg border border-border bg-card px-6 py-3 text-sm font-medium text-foreground shadow-card transition-colors hover:bg-secondary">
        <FileDown className="h-4 w-4 text-primary" />Exportar Relatório em PDF
      </button>
      {csv.map((c) => (
        <button key={c.rotulo} type="button" onClick={c.aoClicar}
          className="flex items-center gap-2 rounded-lg border border-border bg-card px-6 py-3 text-sm font-medium text-foreground shadow-card transition-colors hover:bg-secondary">
          <Download className="h-4 w-4 text-primary" />{c.rotulo}
        </button>
      ))}
    </div>
  );
}

/** CSV com ";" e BOM (abre certo no Excel em português). */
export function baixarCsv(nome: string, cabecalho: string[], linhas: (string | number | null | undefined)[][]) {
  const celula = (v: string | number | null | undefined) => {
    if (v == null) return "";
    const texto = typeof v === "number" ? String(v).replace(".", ",") : String(v);
    return /[";\n]/.test(texto) ? `"${texto.replace(/"/g, '""')}"` : texto;
  };
  const conteudo = [cabecalho, ...linhas].map((l) => l.map(celula).join(";")).join("\r\n");
  const blob = new Blob(["﻿" + conteudo], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = nome;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function textoPeriodo(de: string, ate: string) {
  return de === ate ? `em ${fmtData(de + "T12:00:00")}` : `de ${fmtData(de + "T12:00:00")} a ${fmtData(ate + "T12:00:00")}`;
}

// --------------------------------------------------------------------------- funil em degraus
export interface EtapaFunil { fase: string; nome: string; chegaram: number; agora?: number; pct_total?: number | null; conversao?: number | null }

export const VISUAL_FASE: Record<string, { de: string; ate: string; brilho: string; icone: typeof Users }> = {
  sdr: { de: "#3b82f6", ate: "#1d4ed8", brilho: "#3b82f6", icone: Users },
  closer: { de: "#22d3ee", ate: "#0891b2", brilho: "#06b6d4", icone: UserCheck },
  analise: { de: "#a78bfa", ate: "#6d28d9", brilho: "#8b5cf6", icone: Search },
  contratos: { de: "#fb923c", ate: "#ea580c", brilho: "#f97316", icone: FileText },
  assinatura: { de: "#34d399", ate: "#15803d", brilho: "#16a34a", icone: PenLine },
  assinado: { de: "#fbbf24", ate: "#f59e0b", brilho: "#f59e0b", icone: Trophy },
};

/** Funil no desenho do original: degraus com gradiente, % de passagem entre eles e a conversão geral no rodapé. */
export function FunilDegraus({ etapas, total, titulo, subtitulo, dica, icone, larguras, campanhasPorFase, classe = "" }: {
  etapas: EtapaFunil[]; total: number; titulo: string; subtitulo: string; dica?: string; icone?: ReactNode;
  larguras?: number[]; campanhasPorFase?: Record<string, { nome: string; total: number }[]>; classe?: string;
}) {
  const [dicaFase, setDicaFase] = useState<{ fase: string; x: number; y: number } | null>(null);
  const raiz = useRef<HTMLDivElement>(null);
  const ultimo = etapas[etapas.length - 1];
  const n = etapas.length;
  const temDados = total > 0;
  const mostrarDica = (fase: string, e: React.MouseEvent<HTMLDivElement>) => {
    if (!campanhasPorFase) return;
    const r = e.currentTarget.getBoundingClientRect();
    const p = raiz.current?.getBoundingClientRect();
    setDicaFase({ fase, x: r.left - (p?.left ?? 0) + r.width / 2, y: r.top - (p?.top ?? 0) - 8 });
  };
  const etapaDica = dicaFase ? etapas.find((e) => e.fase === dicaFase.fase) : null;
  return (
    <div ref={raiz} className={cn(CARTAO, "flex h-full flex-col overflow-hidden p-5 md:p-6", classe)}>
      <div className="mb-1 flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          {icone}
          <h3 className="text-base font-bold tracking-tight text-foreground md:text-lg">{titulo}</h3>
          {dica && <Dica texto={dica} tamanho="h-3.5 w-3.5" />}
        </div>
        {temDados && (
          <div className="flex items-center gap-1.5 rounded-full bg-muted/60 px-3 py-1">
            <span className="text-[11px] font-medium text-muted-foreground">Total</span>
            <span className="text-sm font-bold tabular-nums text-foreground">{fmtNum(total)}</span>
          </div>
        )}
      </div>
      <p className="mb-6 text-[11px] text-muted-foreground">{subtitulo}</p>
      {!temDados ? <Vazio>Nenhum lead entrou no período escolhido.</Vazio> : (
        <div className="relative flex flex-1 flex-col items-center justify-center gap-5">
          {etapas.map((etapa, i) => {
            const v = VISUAL_FASE[etapa.fase] ?? VISUAL_FASE.sdr;
            const Icone = v.icone;
            const largura = larguras?.[i] ?? (n <= 1 ? 100 : 100 - i * (58 / (n - 1)));
            return (
              <motion.div key={etapa.fase} initial={{ opacity: 0, scaleX: 0.5, y: 8 }} animate={{ opacity: 1, scaleX: 1, y: 0 }}
                transition={{ delay: i * 0.08, type: "spring", stiffness: 140, damping: 18 }}
                className="group relative flex justify-center" style={{ width: `${largura}%` }}
                onMouseEnter={(e) => mostrarDica(etapa.fase, e)} onMouseLeave={() => setDicaFase(null)}>
                {i > 0 && etapa.conversao != null && (
                  <span className="absolute -top-2.5 left-1/2 z-10 -translate-x-1/2 rounded-full border border-border/60 bg-card px-1.5 py-0.5 text-[9px] font-semibold tabular-nums text-muted-foreground/80 shadow-sm"
                    title="Dos que chegaram à etapa anterior, quantos chegaram a esta">
                    {fmtPct(etapa.conversao)}
                  </span>
                )}
                <div className="absolute -inset-0.5 rounded-xl opacity-0 blur-md transition-opacity duration-300 group-hover:opacity-20"
                  style={{ background: `linear-gradient(135deg, ${v.de}, ${v.ate})` }} />
                <div className="relative flex w-full items-center justify-between gap-2 rounded-xl px-4 py-3 text-white transition-all duration-300 group-hover:-translate-y-0.5"
                  style={{ background: `linear-gradient(135deg, ${v.de}, ${v.ate})`, boxShadow: `0 2px 8px -3px ${v.brilho}40` }}
                  title={etapa.agora != null ? `${fmtNum(etapa.agora)} parados nesta etapa agora` : undefined}>
                  <div className="pointer-events-none absolute inset-x-0 top-0 h-1/2 rounded-t-xl bg-gradient-to-b from-white/10 to-transparent" />
                  <span className="relative flex min-w-0 items-center gap-2 truncate font-semibold">
                    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-white/20"><Icone className="h-3.5 w-3.5" /></span>
                    <span className="truncate text-xs md:text-sm">{etapa.nome}</span>
                  </span>
                  <span className="relative flex shrink-0 items-baseline gap-1 tabular-nums">
                    <span className="text-base font-bold drop-shadow-sm md:text-xl">{fmtNum(etapa.chegaram)}</span>
                    <span className="text-[10px] font-medium opacity-80 md:text-xs">({fmtPct(etapa.pct_total ?? 0)})</span>
                  </span>
                </div>
              </motion.div>
            );
          })}
        </div>
      )}
      {temDados && n >= 2 && (
        <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: n * 0.08 + 0.15 }}
          className="mt-6 flex flex-wrap items-center justify-center gap-2 rounded-xl border border-border/50 bg-muted/30 px-4 py-2.5">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-100">
            <Trophy className="h-3.5 w-3.5 text-emerald-600" />
          </div>
          <span className="text-xs text-muted-foreground">Conversão geral</span>
          <span className="text-sm font-bold tabular-nums text-emerald-600">{fmtPct(total ? (ultimo.chegaram / total) * 100 : 0)}</span>
          <span className="text-[11px] text-muted-foreground/60">({fmtNum(ultimo.chegaram)} de {fmtNum(total)})</span>
        </motion.div>
      )}
      {dicaFase && etapaDica && campanhasPorFase && (
        <div className="pointer-events-none absolute z-50 min-w-[200px] rounded-lg border border-border bg-popover px-3 py-2.5 shadow-xl"
          style={{ left: Math.min(Math.max(dicaFase.x, 110), 300), top: dicaFase.y, transform: "translate(-50%, -100%)" }}>
          <p className="mb-1 text-xs font-semibold text-foreground">{etapaDica.nome} — {fmtNum(etapaDica.chegaram)} lead{etapaDica.chegaram !== 1 ? "s" : ""}</p>
          {(campanhasPorFase[dicaFase.fase] ?? []).length > 0 && (
            <div className="space-y-0.5">
              <p className="text-[10px] font-medium text-muted-foreground">Top campanhas:</p>
              {campanhasPorFase[dicaFase.fase].map((c) => (
                <div key={c.nome} className="flex justify-between gap-3 text-[10px]">
                  <span className="max-w-[160px] truncate text-foreground">{c.nome}</span>
                  <span className="shrink-0 tabular-nums text-muted-foreground">{fmtNum(c.total)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- mapa de calor (dia da semana x hora)
const DIAS_SEMANA = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"];

function corCalor(v: number, max: number, tom: "azul" | "verde") {
  if (!v || !max) return "bg-muted/30";
  const i = v / max;
  if (tom === "azul") return i < 0.25 ? "bg-blue-500/20" : i < 0.5 ? "bg-blue-500/40" : i < 0.75 ? "bg-blue-500/60" : "bg-blue-500/90";
  return i < 0.25 ? "bg-emerald-500/20" : i < 0.5 ? "bg-emerald-500/40" : i < 0.75 ? "bg-emerald-500/60" : "bg-emerald-500/90";
}

/** Grade de horários do original (segunda a domingo x 0h a 23h), com o pico e a legenda "Menos → Mais". */
export function GradeCalor({ grade, tom, titulo, unidade }: { grade: number[][]; tom: "azul" | "verde"; titulo: string; unidade: string }) {
  const [dica, setDica] = useState<{ dia: number; hora: number; x: number; y: number } | null>(null);
  const caixa = useRef<HTMLDivElement>(null);
  const max = Math.max(0, ...grade.flat());
  let pico = { dia: 0, hora: 0, valor: 0 };
  grade.forEach((linha, d) => linha.forEach((v, h) => { if (v > pico.valor) pico = { dia: d, hora: h, valor: v }; }));
  const legenda = tom === "azul" ? ["bg-blue-500/20", "bg-blue-500/40", "bg-blue-500/60", "bg-blue-500/90"]
    : ["bg-emerald-500/20", "bg-emerald-500/40", "bg-emerald-500/60", "bg-emerald-500/90"];
  return (
    <div className="relative" ref={caixa}>
      <h4 className="mb-1 text-xs font-semibold text-foreground">{titulo}</h4>
      <p className="mb-3 text-[10px] text-muted-foreground">Pico: {pico.valor ? `${DIAS_SEMANA[pico.dia]} ${pico.hora}h (${pico.valor})` : "—"}</p>
      <div className="overflow-x-auto">
        <div className="min-w-[500px]" role="table" aria-label={`${titulo} por dia da semana e hora`}>
          <div className="grid gap-[2px]" style={{ gridTemplateColumns: "48px repeat(24, 1fr)" }} role="row">
            <div />
            {Array.from({ length: 24 }, (_, h) => <div key={h} role="columnheader" className="text-center text-[9px] tabular-nums text-muted-foreground">{h}h</div>)}
          </div>
          {grade.map((linha, d) => (
            <div key={d} className="mt-[2px] grid gap-[2px]" style={{ gridTemplateColumns: "48px repeat(24, 1fr)" }} role="row">
              <div className="flex items-center text-[11px] font-medium text-muted-foreground" role="rowheader">{DIAS_SEMANA[d]}</div>
              {linha.map((v, h) => (
                <div key={h} role="cell" className={cn("relative flex aspect-square cursor-default items-center justify-center rounded-sm transition-colors", corCalor(v, max, tom))}
                  onMouseEnter={(e) => {
                    const r = e.currentTarget.getBoundingClientRect();
                    const p = caixa.current?.getBoundingClientRect();
                    setDica({ dia: d, hora: h, x: r.left - (p?.left ?? 0) + r.width / 2, y: r.top - (p?.top ?? 0) - 8 });
                  }}
                  onMouseLeave={() => setDica(null)}>
                  {v > 0 && <span className="text-[8px] font-medium tabular-nums text-foreground/70">{v}</span>}
                </div>
              ))}
            </div>
          ))}
          <div className="mt-2 flex items-center justify-end gap-2">
            <span className="text-[10px] text-muted-foreground">Menos</span>
            {legenda.map((c) => <div key={c} className={cn("h-3 w-3 rounded-sm", c)} />)}
            <span className="text-[10px] text-muted-foreground">Mais</span>
          </div>
        </div>
      </div>
      {dica && (
        <div className="pointer-events-none absolute z-50 rounded-lg border border-border bg-card px-3 py-2 shadow-lg"
          style={{ left: dica.x, top: dica.y, transform: "translate(-50%, -100%)" }}>
          <p className="text-xs font-semibold text-foreground">{DIAS_SEMANA[dica.dia]} às {dica.hora}h</p>
          <p className="text-xs text-muted-foreground">{grade[dica.dia][dica.hora]} {unidade}{grade[dica.dia][dica.hora] !== 1 ? "s" : ""}</p>
        </div>
      )}
    </div>
  );
}

export function CartaoHorarios({ horarios, subtitulo }: { horarios: { leads: number[][]; assinados: number[][] }; subtitulo?: string }) {
  return (
    <div className={cn(CARTAO, "p-5")}>
      <div className="mb-1 flex items-center gap-2">
        <Clock className="h-4 w-4 text-primary" />
        <h3 className="text-sm font-semibold text-foreground">Heatmap de Horários</h3>
      </div>
      <p className="mb-4 text-[11px] text-muted-foreground">{subtitulo ?? "Horário de Brasília"}</p>
      <div className="grid grid-cols-1 gap-8 lg:grid-cols-2">
        <GradeCalor grade={horarios.leads} tom="azul" titulo="Chegada de Leads" unidade="lead" />
        <GradeCalor grade={horarios.assinados} tom="verde" titulo="Fechamento de Contratos" unidade="contrato" />
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- mapa do Brasil
function corEstado(v: number, max: number): string {
  if (!max || !v) return "hsl(var(--muted))";
  const r = Math.min(v / max, 1);
  return `hsl(210, ${40 + r * 40}%, ${90 - r * 50}%)`;
}

/** "Contatos por Estado" do original: mapa (UF pelo DDD do telefone), alternância Leads/Contratos e o ranking. */
export function MapaEstados({ leads, contratos }: { leads: Record<string, number>; contratos: Record<string, number> }) {
  const [modo, setModo] = useState<"leads" | "contratos">("leads");
  const [sobre, setSobre] = useState<string | null>(null);
  const [todos, setTodos] = useState(false);
  // As UFs chegam em minúsculas ("mg"); o contorno usa maiúsculas.
  const valores = useMemo(() => Object.fromEntries(Object.entries(modo === "leads" ? leads : contratos)
    .map(([uf, v]) => [uf.toUpperCase(), v])) as Record<string, number>, [modo, leads, contratos]);
  const total = Object.values(valores).reduce((s, v) => s + v, 0);
  const max = Math.max(1, ...Object.values(valores));
  const ordenados = Object.entries(valores).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
  const visiveis = todos ? ordenados : ordenados.slice(0, 5);
  const maior = visiveis[0]?.[1] ?? 1;
  return (
    <div className={cn(CARTAO, "p-5")}>
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h3 className="text-base font-semibold text-foreground">Contatos por Estado</h3>
          <p className="text-[11px] text-muted-foreground">Distribuição geográfica dos seus contatos (pelo DDD do telefone)</p>
        </div>
        <span className="rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-semibold text-primary">{fmtNum(total)} {modo}</span>
      </div>
      <div className="mb-4">
        <Abas cheia valor={modo} aoMudar={(v) => { setModo(v); setTodos(false); }}
          opcoes={[{ valor: "leads", rotulo: "Leads por Estado" }, { valor: "contratos", rotulo: "Contratos por Estado" }]} />
      </div>
      <div className="relative mb-4">
        <svg viewBox="0 0 450 460" className="w-full" style={{ maxHeight: 280 }} role="img" aria-label="Mapa do Brasil por estado">
          {Object.entries(CONTORNO_ESTADOS).map(([uf, { d }]) => (
            <path key={uf} d={d} fill={corEstado(valores[uf] ?? 0, max)} stroke="hsl(var(--border))" strokeWidth={sobre === uf ? 2 : 0.8}
              opacity={sobre === uf ? 1 : 0.9} className="cursor-pointer transition-all duration-150"
              onMouseEnter={() => setSobre(uf)} onMouseLeave={() => setSobre(null)} />
          ))}
          {sobre && CONTORNO_ESTADOS[sobre] && (
            <text x={CONTORNO_ESTADOS[sobre].labelX} y={CONTORNO_ESTADOS[sobre].labelY} textAnchor="middle"
              className="pointer-events-none fill-foreground text-[10px] font-bold">{sobre}</text>
          )}
        </svg>
        {sobre && (
          <div className="pointer-events-none absolute left-1/2 top-2 z-10 -translate-x-1/2 rounded-lg border border-border bg-popover px-3 py-1.5 text-xs shadow-md">
            <span className="font-bold text-foreground">{sobre}</span>
            <span className="text-muted-foreground"> — {NOMES_ESTADOS[sobre] ?? sobre}</span>
            <span className="ml-2 font-semibold text-primary">{fmtNum(valores[sobre] ?? 0)}</span>
          </div>
        )}
      </div>
      <div className="space-y-2.5">
        {visiveis.map(([uf, v], i) => (
          <div key={uf} className="group flex items-center gap-2">
            <span className="w-7 text-xs font-bold text-foreground">{uf}</span>
            <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-muted">
              <motion.div className="h-full rounded-full bg-gradient-to-r from-emerald-400 to-green-500" style={{ boxShadow: "0 0 8px rgba(21,191,65,0.3)" }}
                initial={{ width: 0 }} animate={{ width: `${(v / maior) * 100}%` }} transition={{ delay: 0.2 + i * 0.08, duration: 0.8, ease: "easeOut" }} />
            </div>
            <span className="w-10 text-right text-xs font-semibold tabular-nums text-foreground"><Contador valor={v} duracao={900} /></span>
            <span className="w-12 text-right text-[11px] tabular-nums text-muted-foreground">{fmtPct(total ? (v / total) * 100 : 0)}</span>
          </div>
        ))}
        {!visiveis.length && <p className="py-4 text-center text-xs text-muted-foreground">Sem dados de telefone</p>}
      </div>
      {ordenados.length > 5 && (
        <button type="button" onClick={() => setTodos((t) => !t)}
          className="mt-4 flex w-full items-center justify-center gap-1.5 rounded-xl border border-border/50 bg-muted/30 py-2.5 text-sm font-medium text-muted-foreground transition-all hover:bg-muted/50 hover:text-foreground print:hidden">
          {todos ? "Ver menos" : `Ver todos os estados (${ordenados.length})`}
          <ChevronDown className={cn("h-4 w-4 transition-transform", todos && "rotate-180")} />
        </button>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- anúncios
export interface Anuncio {
  chave: string; nome: string; campanha: string; titulo: string | null; conteudo: string | null; url: string | null;
  fonte: string | null; meio: string | null; id_anuncio: string | null; plataforma: string | null; plataforma_nome: string;
  leads: number; closer: number; contratos: number; assinatura: number; assinados: number; desqualificados: number;
  qualificados: number; conversao: number | null; horas_ate_assinar: number | null; custo_brl: number;
  custo_por_lead: number | null; custo_por_contrato: number | null;
}

export function infoPlataforma(plataforma: string | null | undefined, nome?: string) {
  switch (plataforma) {
    case "instagram": return { icone: <Instagram className="h-3.5 w-3.5 text-pink-500" />, nome: "Instagram", ponto: "bg-pink-500", cor: "#ec4899", barra: "linear-gradient(90deg, #f472b6, #db2777)" };
    case "facebook": return { icone: <Facebook className="h-3.5 w-3.5 text-blue-500" />, nome: "Facebook", ponto: "bg-blue-500", cor: "#3b82f6", barra: "linear-gradient(90deg, #60a5fa, #2563eb)" };
    case "google": return { icone: <Megaphone className="h-3.5 w-3.5 text-yellow-500" />, nome: "Google", ponto: "bg-yellow-500", cor: "#eab308", barra: "linear-gradient(90deg, #fde047, #eab308)" };
    case "youtube": return { icone: <Youtube className="h-3.5 w-3.5 text-red-500" />, nome: "YouTube", ponto: "bg-red-500", cor: "#ef4444", barra: "linear-gradient(90deg, #f87171, #dc2626)" };
    case "tiktok": return { icone: <Megaphone className="h-3.5 w-3.5 text-slate-700" />, nome: "TikTok", ponto: "bg-slate-700", cor: "#334155", barra: "linear-gradient(90deg, #64748b, #1e293b)" };
    default: return { icone: <Megaphone className="h-3.5 w-3.5 text-muted-foreground" />, nome: nome ?? "Outra origem", ponto: "bg-muted-foreground", cor: "#94a3b8", barra: "linear-gradient(90deg, #8ED393, #15BF41)" };
  }
}

export const PODIO = [
  { grad: "linear-gradient(135deg, #fde68a, #f59e0b)", anel: "rgba(245,158,11,0.30)" },
  { grad: "linear-gradient(135deg, #e2e8f0, #94a3b8)", anel: "rgba(148,163,184,0.30)" },
  { grad: "linear-gradient(135deg, #fdba74, #c2620c)", anel: "rgba(194,98,12,0.30)" },
];

export function Posicao({ i, grande }: { i: number; grande?: boolean }) {
  const p = PODIO[i];
  const tam = grande ? "h-7 w-7 text-xs" : "h-6 w-6 text-[11px]";
  return p
    ? <span className={cn("flex shrink-0 items-center justify-center rounded-full font-bold text-white shadow-sm", tam)} style={{ background: p.grad, boxShadow: `0 2px 5px -1px ${p.anel}` }}>{i + 1}</span>
    : <span className={cn("flex shrink-0 items-center justify-center rounded-full bg-muted font-bold text-muted-foreground", tam)}>{i + 1}</span>;
}

export function exportarAnuncios(anuncios: Anuncio[], de: string, ate: string) {
  baixarCsv(`anuncios-${de}-a-${ate}.csv`,
    ["Anúncio", "Campanha", "Plataforma", "Id do anúncio", "Link", "Leads", "Chegaram ao Closer", "Contratos assinados", "Desqualificados",
     "Conversão (%)", "Tempo médio até assinar (h)", "Custo da IA (R$)"],
    anuncios.map((a) => [a.nome, a.campanha, infoPlataforma(a.plataforma, a.plataforma_nome).nome, a.id_anuncio, a.url, a.leads, a.closer,
                         a.assinados, a.desqualificados, a.conversao, a.horas_ate_assinar, a.custo_brl]));
}

/** Lista "Todos os anúncios" (o "Ver mais" dos rankings). */
export function ModalTodosAnuncios({ aberto, aoFechar, anuncios, ordem, abrir, titulo }: {
  aberto: boolean; aoFechar: () => void; anuncios: Anuncio[]; ordem: string; abrir: (chave: string) => void; titulo: string;
}) {
  return (
    <Dialog open={aberto} onOpenChange={(v) => !v && aoFechar()}>
      <DialogContent className="max-h-[85vh] max-w-2xl">
        <DialogHeader>
          <DialogTitle className="text-base font-bold text-foreground">{titulo}</DialogTitle>
          <DialogDescription className="text-xs text-muted-foreground">{anuncios.length} anúncios — ordenados por {ordem}</DialogDescription>
        </DialogHeader>
        <div className="max-h-[60vh] space-y-1 overflow-y-auto pr-2">
          {anuncios.map((a, i) => {
            const p = infoPlataforma(a.plataforma, a.plataforma_nome);
            return (
              <button key={a.chave} type="button" onClick={() => { aoFechar(); abrir(a.chave); }}
                className="flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left transition-colors hover:bg-muted/40">
                <Posicao i={i} />
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-muted/60">{p.icone}</span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <p className="truncate text-sm font-medium text-foreground">{a.nome}</p>
                    <span className="shrink-0 rounded-md bg-violet-500/10 px-1.5 py-0.5 text-[11px] font-bold tabular-nums text-violet-600">{fmtNum(a.leads)} leads</span>
                    <span className="shrink-0 rounded-md bg-emerald-500/10 px-1.5 py-0.5 text-[11px] font-bold tabular-nums text-emerald-600">{fmtNum(a.assinados)} contratos</span>
                    <span className="shrink-0 rounded-md bg-muted px-1.5 py-0.5 text-[11px] font-bold tabular-nums text-muted-foreground">{fmtPct(a.conversao ?? 0)}</span>
                  </div>
                  <p className="truncate text-[11px] text-muted-foreground">{a.campanha}</p>
                </div>
              </button>
            );
          })}
        </div>
      </DialogContent>
    </Dialog>
  );
}

// --------------------------------------------------------------------------- detalhe do anúncio (popup central)
interface LeadDoAnuncio {
  id: string; nome: string | null; telefone: string | null; criado_em: string; etapa: string; alcancou: string; fase: string;
  assinado: boolean; desqualificado: boolean; assinado_em: string | null; estado: string;
}
interface DetalheAnuncio extends Anuncio {
  termo: string | null; qualificacao: number | null; desqualificacao: number | null;
  primeiro_lead: string | null; ultimo_lead: string | null; ranking?: { posicao: number | null; posicao_leads?: number | null; total: number };
  funil: { fase: string; nome: string; chegaram: number }[];
  serie: { dia: string; leads: number; assinados: number }[];
  lista_leads: LeadDoAnuncio[]; total_leads?: number;
}

/** Cor e ícone grandes da plataforma (cabeçalho do detalhe). */
const MARCA_PLATAFORMA: Record<string, { icone: typeof Users; fundo: string; sombra: string }> = {
  instagram: { icone: Instagram, fundo: "linear-gradient(135deg, #f58529 0%, #dd2a7b 50%, #8134af 100%)", sombra: "rgba(221,42,123,0.45)" },
  facebook: { icone: Facebook, fundo: "linear-gradient(135deg, #3b8bff 0%, #1460d8 100%)", sombra: "rgba(24,119,242,0.45)" },
  google: { icone: Search, fundo: "linear-gradient(135deg, #4285f4 0%, #34a853 45%, #fbbc05 75%, #ea4335 100%)", sombra: "rgba(66,133,244,0.40)" },
  youtube: { icone: Youtube, fundo: "linear-gradient(135deg, #ff4b4b 0%, #d00000 100%)", sombra: "rgba(220,0,0,0.40)" },
  tiktok: { icone: Music2, fundo: "linear-gradient(135deg, #25f4ee 0%, #111827 45%, #111827 60%, #fe2c55 100%)", sombra: "rgba(254,44,85,0.35)" },
};
const MARCA_OUTRA = { icone: Megaphone, fundo: "linear-gradient(135deg, #8ED393 0%, #15BF41 100%)", sombra: "rgba(21,191,65,0.40)" };

const fmtDataHora = (d: string | null | undefined) =>
  d ? new Date(d).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "–";
const pctDe = (parte: number, todo: number) => (todo > 0 ? Math.round((parte / todo) * 1000) / 10 : null);
const POR_PAGINA = 8;

function Indicador({ icone, rotulo, cor, valor, sub, classe }: {
  icone: ReactNode; rotulo: string; cor: string; valor: ReactNode; sub?: ReactNode; classe?: string;
}) {
  return (
    <motion.div variants={ITEM_CASCATA} className={cn("relative overflow-hidden rounded-2xl border border-border/60 bg-card p-3.5", classe)}>
      <span className="pointer-events-none absolute -right-6 -top-6 h-20 w-20 rounded-full opacity-[0.12]" style={{ background: cor }} />
      <div className="flex items-center gap-2">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-white" style={{ background: cor }}>{icone}</span>
        <span className="text-xs font-semibold leading-tight text-muted-foreground">{rotulo}</span>
      </div>
      <p className="mt-2 text-2xl font-extrabold tabular-nums tracking-tight text-foreground">{valor}</p>
      {sub && <p className="mt-0.5 text-[11px] text-muted-foreground">{sub}</p>}
    </motion.div>
  );
}

function Secao({ titulo, icone, children, direita, classe }: { titulo: string; icone: ReactNode; children: ReactNode; direita?: ReactNode; classe?: string }) {
  return (
    <motion.section variants={ITEM_CASCATA} className={cn("rounded-2xl border border-border/60 bg-card p-4", classe)}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h4 className="flex items-center gap-2 text-sm font-bold text-foreground"><span className="text-primary">{icone}</span>{titulo}</h4>
        {direita}
      </div>
      {children}
    </motion.section>
  );
}

function MiniFunil({ funil, leads }: { funil: DetalheAnuncio["funil"]; leads: number }) {
  return (
    <div className="-mx-1 overflow-x-auto px-1 pb-1">
      <div className="flex min-w-[600px] items-stretch">
        {funil.map((e, i) => {
          const v = VISUAL_FASE[e.fase] ?? VISUAL_FASE.sdr;
          const Icone = v.icone;
          const anterior = i > 0 ? funil[i - 1].chegaram : null;
          const largura = leads ? Math.max(4, (e.chegaram / leads) * 100) : 0;
          return (
            <div key={e.fase} className="flex flex-1 items-stretch">
              {anterior != null && (
                <div className="flex w-12 shrink-0 flex-col items-center justify-center text-center" title={`Passagem de ${funil[i - 1].nome} para ${e.nome}`}>
                  <ChevronRight className="h-4 w-4 text-muted-foreground/50" />
                  <span className={cn("text-[11px] font-bold tabular-nums", anterior ? "text-foreground" : "text-muted-foreground")}>{fmtPct(pctDe(e.chegaram, anterior), 0)}</span>
                </div>
              )}
              <div className="flex min-w-0 flex-1 flex-col rounded-xl border border-border/60 bg-muted/20 p-2.5">
                <div className="flex items-center gap-1.5">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-white" style={{ background: `linear-gradient(135deg, ${v.de}, ${v.ate})` }}>
                    <Icone className="h-3.5 w-3.5" />
                  </span>
                  <span className="truncate text-[11px] font-semibold text-muted-foreground" title={e.nome}>{e.nome}</span>
                </div>
                <p className="mt-1.5 text-lg font-extrabold tabular-nums text-foreground"><Contador valor={e.chegaram} /></p>
                <div className="mt-auto h-1.5 overflow-hidden rounded-full bg-secondary">
                  <motion.div className="h-full rounded-full" style={{ background: `linear-gradient(90deg, ${v.de}, ${v.ate})` }}
                    initial={{ width: 0 }} animate={{ width: `${largura}%` }} transition={{ delay: 0.25 + i * 0.08, duration: 0.8, ease: "easeOut" }} />
                </div>
                <span className="mt-1 text-[10px] tabular-nums text-muted-foreground">{fmtPct(pctDe(e.chegaram, leads), 0)} do total</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function GraficoDoAnuncio({ serie }: { serie: DetalheAnuncio["serie"] }) {
  const anima = useAnimaGrafico(1200);
  const id = useId().replace(/[^a-zA-Z0-9]/g, "");
  return (
    <>
      <div className="mb-2 flex items-center gap-3 text-[10px] text-muted-foreground">
        <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-[#15BF41]" />Leads</span>
        <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-violet-500" />Contratos</span>
      </div>
      <div style={{ height: 200 }}>
        <ResponsiveContainer>
          <AreaChart data={serie} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
            <defs>
              <linearGradient id={`${id}l`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#15BF41" stopOpacity={0.45} /><stop offset="100%" stopColor="#15BF41" stopOpacity={0} /></linearGradient>
              <linearGradient id={`${id}a`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#8b5cf6" stopOpacity={0.45} /><stop offset="100%" stopColor="#8b5cf6" stopOpacity={0} /></linearGradient>
            </defs>
            <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="dia" tickFormatter={fmtDia} tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} minTickGap={18} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} allowDecimals={false} width={40} axisLine={false} tickLine={false} />
            <RTooltip labelFormatter={(v) => fmtData(String(v) + "T12:00:00")} contentStyle={{ borderRadius: 8, fontSize: 12 }} />
            <Area type="monotone" dataKey="leads" name="Leads" stroke="#15BF41" fill={`url(#${id}l)`} strokeWidth={2.6} {...anima} />
            <Area type="monotone" dataKey="assinados" name="Contratos" stroke="#8b5cf6" fill={`url(#${id}a)`} strokeWidth={2.6} {...anima} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </>
  );
}

function SobreOAnuncio({ a }: { a: DetalheAnuncio }) {
  const [copiadoId, setCopiadoId] = useState(false);
  const itens: [string, ReactNode][] = [
    ["Campanha", a.campanha],
    ["Conjunto / anúncio", a.titulo],
    ["Fonte", a.fonte],
    ["Meio", a.meio],
    ["Conteúdo", a.conteudo],
    ["Termo", a.termo],
    ["Id do anúncio", a.id_anuncio && (
      <span className="inline-flex items-center gap-1.5">
        <span className="break-all font-mono text-xs">{a.id_anuncio}</span>
        <button type="button" aria-label="Copiar o id do anúncio" className="rounded p-0.5 text-muted-foreground transition-colors hover:text-foreground"
          onClick={() => navigator.clipboard?.writeText(a.id_anuncio!).then(() => { setCopiadoId(true); window.setTimeout(() => setCopiadoId(false), 1600); })}>
          {copiadoId ? <Check className="h-3.5 w-3.5 text-emerald-500" /> : <Copy className="h-3.5 w-3.5" />}
        </button>
      </span>
    )],
    ["Primeiro lead", fmtDataHora(a.primeiro_lead)],
    ["Último lead", fmtDataHora(a.ultimo_lead)],
  ];
  return (
    <dl className="grid grid-cols-1 gap-2 min-[420px]:grid-cols-2 sm:grid-cols-3">
      {itens.map(([rotulo, valor]) => (
        <div key={rotulo} className="min-w-0 rounded-xl bg-muted/40 px-3 py-2">
          <dt className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{rotulo}</dt>
          <dd className={cn("mt-0.5 break-words text-sm", valor ? "text-foreground" : "text-muted-foreground/60")}>{valor || "não informado"}</dd>
        </div>
      ))}
    </dl>
  );
}

function LeadsDoAnuncio({ a, aoAbrirConversa }: { a: DetalheAnuncio; aoAbrirConversa: () => void }) {
  const [busca, setBusca] = useState("");
  const [pagina, setPagina] = useState(0);
  const filtrados = useMemo(() => {
    const t = busca.trim().toLowerCase();
    const digitos = t.replace(/\D/g, "");
    if (!t) return a.lista_leads;
    return a.lista_leads.filter((l) => (l.nome ?? "").toLowerCase().includes(t) || l.etapa.toLowerCase().includes(t)
      || (digitos.length >= 2 && (l.telefone ?? "").replace(/\D/g, "").includes(digitos)));
  }, [a.lista_leads, busca]);
  const paginas = Math.max(1, Math.ceil(filtrados.length / POR_PAGINA));
  const atual = Math.min(pagina, paginas - 1);
  const visiveis = filtrados.slice(atual * POR_PAGINA, (atual + 1) * POR_PAGINA);
  const total = a.total_leads ?? a.lista_leads.length;
  const exportar = () => baixarCsv(`anuncio-${a.chave}-leads.csv`,
    ["Lead", "Telefone", "Entrou em", "Etapa atual", "Chegou até", "Assinou", "Desqualificado"],
    a.lista_leads.map((l) => [l.nome, l.telefone, fmtDataHora(l.criado_em), l.etapa, l.alcancou, l.assinado ? "sim" : "não", l.desqualificado ? "sim" : "não"]));
  return (
    <Secao titulo={`Leads deste anúncio (${fmtNum(total)})`} icone={<Users className="h-4 w-4" />}
      direita={
        <div className="flex w-full items-center gap-2 sm:w-auto">
          <label className="relative flex-1 sm:w-56 sm:flex-none">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <input value={busca} onChange={(e) => { setBusca(e.target.value); setPagina(0); }} placeholder="Buscar nome, telefone ou etapa"
              aria-label="Buscar nos leads do anúncio"
              className="h-8 w-full rounded-lg border border-border bg-background pl-8 pr-2 text-xs text-foreground outline-none transition-shadow placeholder:text-muted-foreground/70 focus:border-primary/50 focus:ring-2 focus:ring-primary/15" />
          </label>
          <button type="button" onClick={exportar}
            className="flex h-8 shrink-0 items-center gap-1.5 rounded-lg border border-border bg-background px-3 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground">
            <Download className="h-3.5 w-3.5" />Exportar CSV
          </button>
        </div>
      }>
      <div className="overflow-hidden rounded-xl border border-border/60">
        <div className="hidden grid-cols-[minmax(0,1.5fr)_minmax(0,1.2fr)_96px_120px] gap-3 bg-secondary/40 px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground sm:grid">
          <span>Lead</span><span>Etapa atual</span><span>Entrou em</span><span className="text-right">Conversa</span>
        </div>
        {visiveis.map((l) => {
          const cor = COR_ETAPA[l.fase] ?? COR_ETAPA.outra;
          return (
            <div key={l.id} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1.5 border-t border-border/40 px-3 py-2.5 transition-colors first:border-t-0 hover:bg-secondary/30 sm:grid-cols-[minmax(0,1.5fr)_minmax(0,1.2fr)_96px_120px] sm:first:border-t">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-foreground">{l.nome || "Contato sem nome"}</p>
                <p className="font-mono text-[11px] text-muted-foreground">{l.telefone ?? "–"}</p>
              </div>
              <div className="order-3 col-span-2 min-w-0 sm:order-none sm:col-span-1">
                <span className="inline-flex max-w-full items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-semibold"
                  style={{ background: `${cor}17`, color: cor }} title={`Chegou até ${l.alcancou}`}>
                  <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: cor }} />
                  <span className="truncate">{l.etapa}</span>
                </span>
                {l.assinado && <span className="ml-1.5 inline-flex items-center gap-0.5 rounded-full bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-bold text-emerald-600"><Check className="h-3 w-3" />Assinou</span>}
                {l.estado === "pausado" && !l.assinado && <span className="ml-1.5 text-[10px] font-medium text-amber-600">com a equipe</span>}
              </div>
              <span className="order-4 hidden text-xs tabular-nums text-muted-foreground sm:order-none sm:block">{fmtData(l.criado_em)}</span>
              <Link to={`/conversas/${l.id}`} onClick={aoAbrirConversa}
                className="flex items-center justify-end gap-1 text-xs font-semibold text-primary transition-colors hover:text-primary/80">
                <MessageCircle className="h-3.5 w-3.5" />Abrir conversa
              </Link>
            </div>
          );
        })}
        {!visiveis.length && <Vazio icone={<Search className="h-5 w-5" />}>{busca ? "Nenhum lead encontrado nesta busca" : "Nenhum lead"}</Vazio>}
      </div>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-[11px] text-muted-foreground">
        <span>
          {filtrados.length ? `${atual * POR_PAGINA + 1}–${Math.min(filtrados.length, (atual + 1) * POR_PAGINA)} de ${fmtNum(filtrados.length)}` : "0 leads"}
          {total > a.lista_leads.length && ` · lista com os ${fmtNum(a.lista_leads.length)} mais recentes`}
        </span>
        {paginas > 1 && (
          <div className="flex items-center gap-1">
            <button type="button" disabled={atual === 0} onClick={() => setPagina(atual - 1)} aria-label="Página anterior"
              className="flex h-7 w-7 items-center justify-center rounded-lg border border-border bg-background transition-colors hover:bg-muted disabled:opacity-40">
              <ChevronLeft className="h-3.5 w-3.5" />
            </button>
            <span className="min-w-[64px] text-center tabular-nums">Página {atual + 1} de {paginas}</span>
            <button type="button" disabled={atual >= paginas - 1} onClick={() => setPagina(atual + 1)} aria-label="Próxima página"
              className="flex h-7 w-7 items-center justify-center rounded-lg border border-border bg-background transition-colors hover:bg-muted disabled:opacity-40">
              <ChevronRight className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
      </div>
    </Secao>
  );
}

function CorpoDoAnuncio({ a, aoFechar }: { a: DetalheAnuncio; aoFechar: () => void }) {
  const horasTexto = fmtHoras(a.horas_ate_assinar);
  const indicadores = [
    { rotulo: "Leads", cor: "linear-gradient(135deg,#8ED393,#15BF41)", icone: <Users className="h-3.5 w-3.5" />,
      valor: <Contador valor={a.leads} />, sub: a.custo_por_lead != null ? `${fmtBRL(a.custo_por_lead)} de IA por lead` : "no período" },
    { rotulo: "Qualificados", cor: "linear-gradient(135deg,#22d3ee,#0891b2)", icone: <UserCheck className="h-3.5 w-3.5" />,
      valor: <Contador valor={a.qualificados} />, sub: <><b className="text-foreground"><Contador valor={a.qualificacao ?? 0} casas={1} sufixo="%" /></b> dos leads</> },
    { rotulo: "Contratos assinados", cor: "linear-gradient(135deg,#fbbf24,#f59e0b)", icone: <Trophy className="h-3.5 w-3.5" />,
      valor: <Contador valor={a.assinados} />,
      sub: a.qualificados ? <><b className="text-foreground"><Contador valor={pctDe(a.assinados, a.qualificados) ?? 0} casas={1} sufixo="%" /></b> dos qualificados</> : "nenhum qualificado ainda" },
    { rotulo: "Desqualificados", cor: "linear-gradient(135deg,#f87171,#dc2626)", icone: <UserX className="h-3.5 w-3.5" />,
      valor: <Contador valor={a.desqualificados} />, sub: <><b className="text-foreground"><Contador valor={a.desqualificacao ?? 0} casas={1} sufixo="%" /></b> dos leads</> },
    { rotulo: "Conversão", cor: "linear-gradient(135deg,#a78bfa,#7c3aed)", icone: <TrendingUp className="h-3.5 w-3.5" />,
      valor: <Contador valor={a.conversao ?? 0} casas={1} sufixo="%" />, sub: "de lead para contrato" },
    { rotulo: "Tempo até assinar", cor: "linear-gradient(135deg,#60a5fa,#2563eb)", icone: <Clock className="h-3.5 w-3.5" />,
      valor: horasTexto, sub: a.horas_ate_assinar != null ? "média entre a entrada e a assinatura" : "nenhum contrato assinado" },
    ...(a.custo_brl > 0 ? [{ rotulo: "Custo da IA", cor: "linear-gradient(135deg,#94a3b8,#475569)", icone: <Bot className="h-3.5 w-3.5" />,
      valor: <Contador valor={a.custo_brl} casas={2} prefixo="R$ " />,
      sub: a.custo_por_contrato != null ? `${fmtBRL(a.custo_por_contrato)} por contrato` : "nenhum contrato ainda" }] : []),
  ];
  return (
    <Cascata className="space-y-4" passo={0.05} atraso={0.05}>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {indicadores.map((k, i) => (
          <Indicador key={k.rotulo} {...k}
            classe={cn(i === 0 && "sm:col-span-2", indicadores.length === 6 && i === 5 && "sm:col-span-2",
              indicadores.length === 7 && i === 6 && "col-span-2 sm:col-span-1")} />
        ))}
      </div>
      <Secao titulo="Funil do anúncio" icone={<Layers className="h-4 w-4" />}
        direita={<span className="text-[11px] text-muted-foreground">quantos chegaram em cada etapa e a passagem de uma para a outra</span>}>
        <MiniFunil funil={a.funil} leads={a.leads} />
      </Secao>
      <Secao titulo="Leads e contratos por dia" icone={<TrendingUp className="h-4 w-4" />}>
        <GraficoDoAnuncio serie={a.serie} />
      </Secao>
      <Secao titulo="Sobre o anúncio" icone={<Info className="h-4 w-4" />}>
        <SobreOAnuncio a={a} />
      </Secao>
      <LeadsDoAnuncio a={a} aoAbrirConversa={aoFechar} />
    </Cascata>
  );
}

/** Detalhe do anúncio: popup central com indicadores, funil, gráfico, dados do anúncio e os leads dele. */
export function DetalheDoAnuncio({ chave, consulta, aoFechar }: { chave: string | null; consulta: string; aoFechar: () => void }) {
  const r = useCarregar<DetalheAnuncio>(chave ? `/relatorios/campanhas/anuncio/${chave}?${consulta}` : null, [chave, consulta]);
  const [copiado, setCopiado] = useState(false);
  const a = chave && r.dados?.chave === chave ? r.dados : null;
  const url = a?.url ? (/^https?:\/\//.test(a.url) ? a.url : `https://${a.url}`) : null;
  const marca = (a?.plataforma && MARCA_PLATAFORMA[a.plataforma]) || MARCA_OUTRA;
  const IconeMarca = marca.icone;
  const medalhas: [string, number][] = [];
  for (const [onde, n] of [["em contratos", a?.ranking?.posicao], ["em leads", a?.ranking?.posicao_leads]] as [string, number | null | undefined][])
    if (n != null && n <= 3) medalhas.push([onde, n]);
  const copiar = () => url && navigator.clipboard?.writeText(url).then(
    () => { setCopiado(true); toast.success("Link do anúncio copiado."); window.setTimeout(() => setCopiado(false), 2000); },
    () => toast.error("Não deu para copiar."));
  return (
    <DialogPrimitive.Root open={Boolean(chave)} onOpenChange={(v) => !v && aoFechar()}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay onMouseDown={(e) => { if (e.target === e.currentTarget) aoFechar(); }} className="rl-modal-fundo fixed inset-0 z-50 flex items-stretch justify-center bg-slate-900/50 backdrop-blur-[6px] sm:items-center sm:p-6">
          <DialogPrimitive.Content aria-describedby={undefined}
            className="rl-modal relative flex h-full w-full flex-col overflow-hidden bg-background shadow-[0_30px_80px_-20px_rgba(15,23,42,0.45),0_0_0_1px_rgba(15,23,42,0.06)] outline-none sm:h-auto sm:max-h-[min(92vh,960px)] sm:max-w-[880px] sm:rounded-3xl">
            {/* cabeçalho */}
            <div className="relative shrink-0 overflow-hidden border-b border-border/60 px-5 pb-4 pt-5 sm:px-6">
              <div className="pointer-events-none absolute inset-0 opacity-[0.10]" style={{ background: marca.fundo }} />
              <div className="relative flex items-start gap-3.5 pr-10">
                <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl text-white"
                  style={{ background: marca.fundo, boxShadow: `0 10px 22px -10px ${marca.sombra}` }}>
                  <IconeMarca className="h-6 w-6" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                      Detalhe do anúncio{a ? ` · ${infoPlataforma(a.plataforma, a.plataforma_nome).nome}` : ""}
                    </span>
                    {medalhas.map(([onde, n]) => (
                      <span key={onde} className="inline-flex items-center gap-1.5 rounded-full border border-amber-200/70 bg-amber-50 py-0.5 pl-0.5 pr-2 text-[11px] font-bold text-amber-700">
                        <Posicao i={n - 1} />Top {n} {onde}
                      </span>
                    ))}
                  </div>
                  <DialogPrimitive.Title className="mt-0.5 break-words text-lg font-extrabold leading-snug tracking-tight text-foreground sm:text-xl">
                    {a ? a.nome : chave && r.erro ? "Detalhe do anúncio" : "Carregando o anúncio…"}
                  </DialogPrimitive.Title>
                  {a && <p className="mt-0.5 flex items-center gap-1.5 text-xs text-muted-foreground"><Megaphone className="h-3.5 w-3.5 shrink-0" /><span className="truncate">{a.campanha}</span></p>}
                </div>
              </div>
              {a && (
                <div className="relative mt-3.5 flex flex-wrap gap-2 sm:pl-[62px]">
                  <button type="button" disabled={!url} onClick={() => url && window.open(url, "_blank", "noopener,noreferrer")}
                    title={url ? url : "Este anúncio não trouxe link"}
                    className="btn-lawchat flex h-9 items-center gap-2 rounded-xl px-4 text-xs font-semibold">
                    <ExternalLink className="h-3.5 w-3.5" />Abrir anúncio
                  </button>
                  <button type="button" disabled={!url} onClick={copiar}
                    className="flex h-9 items-center gap-2 rounded-xl border border-border bg-background px-4 text-xs font-semibold text-foreground transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50">
                    {copiado ? <Check className="h-3.5 w-3.5 text-emerald-500" /> : <Copy className="h-3.5 w-3.5" />}{copiado ? "Copiado!" : "Copiar link"}
                  </button>
                </div>
              )}
              <DialogPrimitive.Close aria-label="Fechar"
                className="absolute right-4 top-4 flex h-9 w-9 items-center justify-center rounded-full bg-background/80 text-muted-foreground shadow-sm ring-1 ring-border/60 transition-colors hover:bg-muted hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-primary">
                <X className="h-4 w-4" />
              </DialogPrimitive.Close>
            </div>
            {/* corpo com rolagem própria */}
            <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain bg-muted/25 px-4 py-4 sm:px-6 sm:py-5">
              {a ? <CorpoDoAnuncio a={a} aoFechar={aoFechar} />
                : r.erro ? <div className="rounded-2xl border border-destructive/30 bg-destructive/5 p-5 text-sm text-destructive">{r.erro}</div>
                : (
                  <div className="space-y-4" role="status" aria-label="Carregando o anúncio">
                    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">{Array.from({ length: 7 }, (_, i) => <div key={i} className={cn("rl-brilho h-[104px] rounded-2xl", i === 0 && "sm:col-span-2")} />)}</div>
                    <div className="rl-brilho h-[120px] rounded-2xl" />
                    <div className="rl-brilho h-[260px] rounded-2xl" />
                  </div>
                )}
            </div>
          </DialogPrimitive.Content>
        </DialogPrimitive.Overlay>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

/** Caixa de "insight" (ícone + texto curto) usada no rodapé dos cartões. */
export function Insight({ children, tom = "verde", icone }: { children: ReactNode; tom?: "verde" | "violeta" | "primaria"; icone?: ReactNode }) {
  const t = tom === "violeta" ? ["border-violet-200/50 bg-violet-50/40", "bg-violet-100", "text-violet-600"]
    : tom === "primaria" ? ["border-primary/15 bg-primary/[0.04]", "bg-primary/15", "text-primary"]
    : ["border-emerald-200/50 bg-emerald-50/40", "bg-emerald-100", "text-emerald-600"];
  return (
    <div className={cn("relative flex items-start gap-2.5 rounded-xl border p-3.5", t[0])}>
      <span className={cn("flex h-7 w-7 shrink-0 items-center justify-center rounded-lg", t[1])}>
        {icone ?? <Sparkles className={cn("h-3.5 w-3.5", t[2])} />}
      </span>
      <p className="text-xs leading-relaxed text-muted-foreground">{children}</p>
    </div>
  );
}
