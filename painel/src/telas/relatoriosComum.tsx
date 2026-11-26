/*
 * Peças comuns das telas de Relatórios (Dashboard e Rastreamento de campanhas), no visual do dashboard comercial
 * original da LawChat: barra de filtros (período em pílulas, "Mais", minimizar), saudação com o selo "Atualizado há",
 * contador animado, funil em degraus coloridos, mapa de calor, mapa do Brasil, detalhe do anúncio, exportar CSV e PDF.
 * Os números vêm prontos do servidor (/api/relatorios/*); aqui só formata e desenha.
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { motion } from "framer-motion";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip as RTooltip, XAxis, YAxis } from "recharts";
import {
  Calendar, Check, ChevronDown, Clock, ChevronUp, Copy, Download, ExternalLink, Facebook, FileCheck, FileDown, FileText, Filter,
  Info, Instagram, Megaphone, PenLine, RefreshCw, Search, Sparkles, TrendingUp, Trophy, UserCheck, Users, X, Youtube,
} from "lucide-react";
import { toast } from "sonner";
import { useCarregar } from "../componentes/ui";
import { useSessao } from "../sessao";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
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

// Cartão padrão (mesmas bordas, raio e sombra do dashboard original)
export const CARTAO = "relative rounded-2xl border border-border/60 bg-card shadow-[0_1px_3px_rgba(15,23,42,0.05)]";

// --------------------------------------------------------------------------- filtros (na URL)
export const PERIODOS: { valor: string; rotulo: string }[] = [
  { valor: "hoje", rotulo: "Hoje" }, { valor: "ontem", rotulo: "Ontem" }, { valor: "7", rotulo: "7 dias" },
  { valor: "30", rotulo: "30 dias" }, { valor: "mes", rotulo: "Este mês" },
  { valor: "90", rotulo: "Últimos 90 dias" }, { valor: "mes_passado", rotulo: "Mês passado" }, { valor: "ano", rotulo: "Últimos 12 meses" },
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
    case "mes": return { de: iso(new Date(hoje.getFullYear(), hoje.getMonth(), 1)), ate: iso(hoje) };
    case "mes_passado": return {
      de: iso(new Date(hoje.getFullYear(), hoje.getMonth() - 1, 1)), ate: iso(new Date(hoje.getFullYear(), hoje.getMonth(), 0)) };
    default: return { de: iso(menos(29)), ate: iso(hoje) };
  }
}

export interface Filtros { periodo: string; de: string; ate: string; agente: string; campanha: string; fonte: string }

export function useFiltros() {
  const [params, setParams] = useSearchParams();
  const filtros: Filtros = useMemo(() => {
    const periodo = params.get("periodo") || (params.get("de") ? "personalizado" : "30");
    const intervalo = periodo === "personalizado"
      ? { de: params.get("de") || intervaloDoPeriodo("30").de, ate: params.get("ate") || iso(new Date()) }
      : intervaloDoPeriodo(periodo);
    return { periodo, ...intervalo, agente: params.get("agente") || "", campanha: params.get("campanha") || "",
             fonte: params.get("fonte") || "" };
  }, [params]);
  const mudar = (novo: Partial<Filtros>) => {
    const proximo = new URLSearchParams(params);
    for (const [chave, valor] of Object.entries(novo)) {
      if (valor) proximo.set(chave, valor); else proximo.delete(chave);
    }
    if (novo.periodo && novo.periodo !== "personalizado") { proximo.delete("de"); proximo.delete("ate"); }
    if (novo.periodo === "30") proximo.delete("periodo");
    setParams(proximo, { replace: true });
  };
  const consulta = new URLSearchParams({ de: filtros.de, ate: filtros.ate,
    ...(filtros.agente ? { agente: filtros.agente } : {}), ...(filtros.campanha ? { campanha: filtros.campanha } : {}),
    ...(filtros.fonte ? { fonte: filtros.fonte } : {}) }).toString();
  return { filtros, mudar, consulta };
}

export interface OpcoesFiltro {
  agentes: { id: string; nome: string; situacao: string }[];
  campanhas: { campanha: string; leads: number }[];
  plataformas: { valor: string; rotulo: string }[];
}

export function useOpcoesFiltro() {
  const { escritorio } = useSessao();
  return useCarregar<OpcoesFiltro>(escritorio ? "/relatorios/filtros" : null, [escritorio]);
}

const PILULA = { background: "linear-gradient(135deg, #8ED393, #15BF41)", boxShadow: "0 4px 10px -3px rgba(21,191,65,0.28)" };
const CAMPO = "h-9 rounded-md border border-border bg-background px-3 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-ring";

function GrupoFiltro({ rotulo, children, className }: { rotulo: string; children: ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-col gap-1 min-w-0", className)}>
      <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">{rotulo}</span>
      <div className="flex items-center gap-1.5 flex-wrap">{children}</div>
    </div>
  );
}

const fmtCurta = (d: string) => `${d.slice(8, 10)}/${d.slice(5, 7)}`;

/** Barra de filtros no desenho do original: período em pílulas + "Mais", campanha; agente e origem; Limpar e Atualizar. */
export function BarraFiltros({ filtros, mudar, aoAtualizar, atualizando, recolhidaDeInicio = false, id }: {
  filtros: Filtros; mudar: (f: Partial<Filtros>) => void; aoAtualizar: () => void; atualizando?: boolean;
  recolhidaDeInicio?: boolean; id: string;
}) {
  const opcoes = useOpcoesFiltro();
  const [recolhida, setRecolhida] = useState(recolhidaDeInicio);
  const [maisAberto, setMaisAberto] = useState(false);
  const qtdFiltros = [filtros.agente, filtros.campanha, filtros.fonte].filter(Boolean).length;
  const ativoNaLinha = NA_LINHA.includes(filtros.periodo);
  const ativoNoMais = !ativoNaLinha && filtros.periodo !== "personalizado";
  const rotuloMais = ativoNoMais ? PERIODOS.find((p) => p.valor === filtros.periodo)?.rotulo ?? "Mais"
    : filtros.periodo === "personalizado" ? `${fmtCurta(filtros.de)} → ${fmtCurta(filtros.ate)}` : "Mais";
  const rotuloPeriodo = filtros.periodo === "personalizado" ? `${fmtCurta(filtros.de)} → ${fmtCurta(filtros.ate)}`
    : PERIODOS.find((p) => p.valor === filtros.periodo)?.rotulo ?? "";
  const limpar = () => mudar({ agente: "", campanha: "", fonte: "", periodo: "30" });

  const BotaoAtualizar = ({ pequeno }: { pequeno?: boolean }) => (
    <button type="button" onClick={aoAtualizar} disabled={atualizando}
      className={cn("btn-lawchat flex items-center gap-1.5 rounded-lg font-semibold", pequeno ? "h-8 px-3 text-xs" : "h-9 px-4 text-sm")}>
      <RefreshCw className={cn("relative z-10 h-3.5 w-3.5", atualizando && "animate-spin")} />
      <span className="relative z-10">Atualizar</span>
    </button>
  );

  if (recolhida) {
    return (
      <div className="relative z-30 flex items-center gap-3 border-b border-border/40 px-0.5 pb-3 print:hidden">
        <Filter className="h-4 w-4 text-muted-foreground" />
        <span className="text-sm font-medium text-foreground">{rotuloPeriodo}</span>
        {qtdFiltros > 0 && (
          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary text-[10px] font-bold text-primary-foreground">{qtdFiltros}</span>
        )}
        <div className="ml-auto flex items-center gap-2">
          <BotaoAtualizar pequeno />
          <button type="button" onClick={() => setRecolhida(false)}
            className="flex h-8 items-center gap-1 rounded-lg border border-border bg-background px-2.5 text-xs text-muted-foreground hover:bg-secondary transition-colors">
            <ChevronDown className="h-3.5 w-3.5" />Expandir
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="relative z-30 space-y-3 border-b border-border/40 px-0.5 pb-4 print:hidden" role="group" aria-label="Filtros do relatório">
      <div className="flex flex-wrap items-end gap-3">
        <Filter className="h-4 w-4 text-muted-foreground self-center mt-3" />
        <GrupoFiltro rotulo="Período">
          <div className="relative flex flex-wrap items-center gap-1" role="radiogroup" aria-label="Período">
            {PERIODOS.filter((p) => NA_LINHA.includes(p.valor)).map((p) => {
              const ativo = filtros.periodo === p.valor;
              return (
                <button key={p.valor} type="button" role="radio" aria-checked={ativo} onClick={() => mudar({ periodo: p.valor })}
                  className={cn("relative z-10 h-8 whitespace-nowrap rounded-md px-2.5 text-xs font-medium transition-colors",
                    ativo ? "text-primary-foreground" : "border border-border bg-background text-muted-foreground hover:bg-secondary")}>
                  {ativo && <motion.div layoutId={`pilula-periodo-${id}`} className="absolute inset-0 rounded-md" style={{ zIndex: -1, ...PILULA }}
                    transition={{ type: "spring", stiffness: 400, damping: 30 }} />}
                  {p.rotulo}
                </button>
              );
            })}
            <Popover open={maisAberto} onOpenChange={setMaisAberto}>
              <PopoverTrigger asChild>
                <button type="button"
                  className={cn("relative z-10 inline-flex h-8 items-center gap-1 rounded-md px-2.5 text-xs font-medium transition-colors",
                    ativoNoMais || filtros.periodo === "personalizado" ? "text-primary-foreground" : "border border-border bg-background text-foreground hover:bg-secondary")}>
                  {(ativoNoMais || filtros.periodo === "personalizado") && (
                    <motion.div layoutId={`pilula-periodo-${id}`} className="absolute inset-0 rounded-md" style={{ zIndex: -1, ...PILULA }}
                      transition={{ type: "spring", stiffness: 400, damping: 30 }} />
                  )}
                  <Calendar className="h-3.5 w-3.5" />{rotuloMais}<ChevronDown className="h-3 w-3" />
                </button>
              </PopoverTrigger>
              <PopoverContent className="w-auto p-0" align="start">
                <div className="min-w-[220px] space-y-0.5 p-2">
                  {PERIODOS.filter((p) => !NA_LINHA.includes(p.valor)).map((p) => (
                    <button key={p.valor} type="button" onClick={() => { mudar({ periodo: p.valor }); setMaisAberto(false); }}
                      className={cn("flex w-full items-center rounded-md px-3 py-2 text-left text-sm transition-colors",
                        filtros.periodo === p.valor ? "bg-primary font-medium text-primary-foreground" : "text-foreground hover:bg-muted")}>
                      {p.rotulo}
                    </button>
                  ))}
                </div>
                <div className="space-y-2 border-t border-border p-3">
                  <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">Intervalo personalizado</span>
                  <div className="flex items-center gap-2">
                    <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">De
                      <input type="date" value={filtros.de} max={filtros.ate} className={cn(CAMPO, "h-8 px-2 text-xs")}
                        onChange={(e) => e.target.value && mudar({ periodo: "personalizado", de: e.target.value, ate: filtros.ate })} />
                    </label>
                    <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">Até
                      <input type="date" value={filtros.ate} min={filtros.de} className={cn(CAMPO, "h-8 px-2 text-xs")}
                        onChange={(e) => e.target.value && mudar({ periodo: "personalizado", de: filtros.de, ate: e.target.value })} />
                    </label>
                  </div>
                  {filtros.periodo === "personalizado" && (
                    <div className="pt-1 text-xs font-medium text-primary">{fmtData(filtros.de + "T12:00:00")} → {fmtData(filtros.ate + "T12:00:00")}</div>
                  )}
                </div>
              </PopoverContent>
            </Popover>
          </div>
        </GrupoFiltro>

        <div className="hidden sm:block h-8 self-end border-l border-border" />

        <GrupoFiltro rotulo="Campanha">
          <select value={filtros.campanha} onChange={(e) => mudar({ campanha: e.target.value })} className={cn(CAMPO, "max-w-[260px]")}>
            <option value="">Todas as campanhas</option>
            {filtros.campanha && !opcoes.dados?.campanhas.some((c) => c.campanha === filtros.campanha) && (
              <option value={filtros.campanha}>{filtros.campanha}</option>
            )}
            {opcoes.dados?.campanhas.map((c) => <option key={c.campanha} value={c.campanha}>{c.campanha} ({fmtNum(c.leads)})</option>)}
          </select>
        </GrupoFiltro>

        <div className="ml-auto self-end">
          <button type="button" onClick={() => setRecolhida(true)}
            className="flex h-8 items-center gap-1 rounded-md border border-border bg-background px-2.5 text-xs text-muted-foreground hover:bg-secondary transition-colors">
            <ChevronUp className="h-3.5 w-3.5" />Minimizar
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-end gap-3 border-t border-border/50 pt-3">
        <GrupoFiltro rotulo="Agente">
          <select value={filtros.agente} onChange={(e) => mudar({ agente: e.target.value })} className={CAMPO}>
            <option value="">Todos os agentes</option>
            {opcoes.dados?.agentes.map((a) => <option key={a.id} value={a.id}>{a.nome}{a.situacao !== "ativo" ? " (pausado)" : ""}</option>)}
          </select>
        </GrupoFiltro>
        <div className="hidden sm:block h-8 self-end border-l border-border" />
        <GrupoFiltro rotulo="Origem">
          <select value={filtros.fonte} onChange={(e) => mudar({ fonte: e.target.value })} className={CAMPO}>
            <option value="">Todas as origens</option>
            {opcoes.dados?.plataformas.map((p) => <option key={p.valor} value={p.valor}>{p.rotulo}</option>)}
          </select>
        </GrupoFiltro>
        <div className="ml-auto flex items-end gap-2">
          <button type="button" onClick={limpar}
            className="flex h-9 items-center gap-1.5 rounded-lg border border-destructive/30 bg-background px-3 text-sm text-destructive transition-all hover:-translate-y-0.5 hover:border-destructive/50 hover:bg-destructive/10">
            <X className="h-3.5 w-3.5" />Limpar
          </button>
          <BotaoAtualizar />
        </div>
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
export function SeloAtualizado({ data, aoAtualizar, atualizando }: { data: string | null | undefined; aoAtualizar: () => void; atualizando?: boolean }) {
  const [, setTique] = useState(0);
  useEffect(() => { const id = window.setInterval(() => setTique((t) => t + 1), 30000); return () => window.clearInterval(id); }, []);
  if (!data) return null;
  const quando = new Date(data);
  const velho = Date.now() - quando.getTime() > 2 * 3600000;
  return (
    <button type="button" onClick={aoAtualizar} title={`Dados de ${quando.toLocaleString("pt-BR")}. Clique para atualizar.`}
      className="flex shrink-0 items-center gap-2 rounded-full border border-border/60 bg-card px-3 py-1.5 text-xs font-medium text-muted-foreground shadow-[0_1px_2px_rgba(15,23,42,0.04)] transition-colors hover:bg-secondary hover:text-foreground print:hidden">
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
export function Contador({ valor, casas = 0, sufixo = "", prefixo = "", duracao = 1000 }: {
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
      const v = de + (valor - de) * (p === 1 ? 1 : 1 - Math.pow(2, -10 * p));
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

/** Abas em "pílula" (fundo cinza, aba ativa branca com sombra). */
export function Abas<T extends string>({ valor, opcoes, aoMudar, cheia }: {
  valor: T; opcoes: { valor: NoInfer<T>; rotulo: ReactNode }[]; aoMudar: (v: NoInfer<T>) => void; cheia?: boolean;
}) {
  return (
    <div className={cn("flex gap-1 rounded-lg bg-muted/50 p-1", !cheia && "w-fit")} role="tablist">
      {opcoes.map((o) => (
        <button key={o.valor} type="button" role="tab" aria-selected={valor === o.valor} onClick={() => aoMudar(o.valor)}
          className={cn("flex items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors", cheia && "flex-1",
            valor === o.valor ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}>
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

interface DetalheAnuncio extends Anuncio {
  funil: { fase: string; nome: string; chegaram: number }[];
  serie: { dia: string; leads: number; assinados: number }[];
  lista_leads: { id: string; nome: string | null; telefone: string | null; criado_em: string; etapa: string; alcancou: string;
           assinado: boolean; desqualificado: boolean; assinado_em: string | null; estado: string }[];
}

const CAIXA = "rounded-lg border border-border bg-muted/30 p-3 text-center";

/** "Detalhes do Anúncio" do original, com o funil, os dias e os leads daquele anúncio. */
export function DetalheDoAnuncio({ chave, consulta, aoFechar }: { chave: string | null; consulta: string; aoFechar: () => void }) {
  const r = useCarregar<DetalheAnuncio>(chave ? `/relatorios/campanhas/anuncio/${chave}?${consulta}` : null, [chave, consulta]);
  const [copiado, setCopiado] = useState(false);
  const a = chave && r.dados?.chave === chave ? r.dados : null;
  const copiar = (texto: string) => navigator.clipboard?.writeText(texto).then(() => { setCopiado(true); window.setTimeout(() => setCopiado(false), 2000); },
    () => toast.error("Não deu para copiar."));
  const exportar = () => {
    if (!a) return;
    baixarCsv(`anuncio-${a.chave}.csv`, ["Lead", "Telefone", "Entrou em", "Etapa atual", "Chegou até", "Assinou", "Desqualificado"],
      a.lista_leads.map((l) => [l.nome, l.telefone, fmtData(l.criado_em), l.etapa, l.alcancou, l.assinado ? "sim" : "não", l.desqualificado ? "sim" : "não"]));
  };
  const url = a?.url ? (/^https?:\/\//.test(a.url) ? a.url : `https://${a.url}`) : null;
  return (
    <Dialog open={Boolean(chave)} onOpenChange={(v) => !v && aoFechar()}>
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-base font-bold text-foreground">Detalhes do Anúncio</DialogTitle>
          <DialogDescription className="text-xs text-muted-foreground">{a ? a.nome : "Carregando os dados do anúncio…"}</DialogDescription>
        </DialogHeader>
        {!a ? (
          r.erro ? <p className="text-sm text-destructive">{r.erro}</p> : <div className="h-40 animate-pulse rounded-lg bg-muted/40" />
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-3 gap-3">
              <div className={CAIXA}><Users className="mx-auto mb-1 h-4 w-4 text-primary" /><p className="text-lg font-bold text-foreground">{fmtNum(a.leads)}</p><p className="text-[11px] text-muted-foreground">Leads</p></div>
              <div className={CAIXA}><FileCheck className="mx-auto mb-1 h-4 w-4 text-emerald-500" /><p className="text-lg font-bold text-foreground">{fmtNum(a.assinados)}</p><p className="text-[11px] text-muted-foreground">Contratos</p></div>
              <div className={CAIXA}><TrendingUp className="mx-auto mb-1 h-4 w-4 text-amber-500" /><p className="text-lg font-bold text-foreground">{fmtPct(a.conversao ?? 0)}</p><p className="text-[11px] text-muted-foreground">Conversão</p></div>
              <div className={CAIXA}><p className="text-lg font-bold text-foreground">{fmtNum(a.closer)}</p><p className="text-[11px] text-muted-foreground">Chegaram ao Closer</p></div>
              <div className={CAIXA}><p className="text-lg font-bold text-red-500">{fmtNum(a.desqualificados)}</p><p className="text-[11px] text-muted-foreground">Desqualificados</p></div>
              <div className={CAIXA}><p className="text-lg font-bold text-foreground">{fmtHoras(a.horas_ate_assinar)}</p><p className="text-[11px] text-muted-foreground">Tempo até assinar</p></div>
            </div>
            <div className="space-y-2 text-sm">
              <div><span className="font-medium text-muted-foreground">Plataforma: </span><span className="text-foreground">{infoPlataforma(a.plataforma, a.plataforma_nome).nome}</span></div>
              <div><span className="font-medium text-muted-foreground">Campanha: </span><span className="text-foreground">{a.campanha}</span></div>
              {a.titulo && <div><span className="font-medium text-muted-foreground">Título: </span><span className="text-foreground">{a.titulo}</span></div>}
              {a.conteudo && <div><span className="font-medium text-muted-foreground">Conteúdo: </span><span className="text-foreground">{a.conteudo}</span></div>}
              {a.fonte && <div><span className="font-medium text-muted-foreground">Fonte: </span><span className="text-foreground">{a.fonte}{a.meio ? ` / ${a.meio}` : ""}</span></div>}
              {a.id_anuncio && <div><span className="font-medium text-muted-foreground">Id do anúncio: </span><span className="font-mono text-xs text-foreground">{a.id_anuncio}</span></div>}
              <div><span className="font-medium text-muted-foreground">Custo da IA: </span><span className="text-foreground">{fmtBRL(a.custo_brl)}{a.custo_por_contrato != null ? ` (${fmtBRL(a.custo_por_contrato)} por contrato)` : ""}</span></div>
            </div>
            {url && (
              <div className="space-y-2">
                <h4 className="text-sm font-semibold text-foreground">Link do anúncio</h4>
                <div className="flex gap-2">
                  <button type="button" onClick={() => window.open(url, "_blank", "noopener,noreferrer")}
                    className="flex flex-1 items-center justify-center gap-2 rounded-lg border border-border bg-muted/30 px-4 py-3 text-sm text-primary transition-colors hover:bg-muted/60">
                    <ExternalLink className="h-4 w-4" />{/instagram\.com/.test(url) ? "Abrir no Instagram" : /fb\.me|facebook\.com/.test(url) ? "Abrir no Facebook" : "Abrir no navegador"}
                  </button>
                  <button type="button" onClick={() => copiar(url)}
                    className="flex items-center gap-1.5 rounded-lg border border-border bg-muted/30 px-3 py-3 text-sm text-muted-foreground transition-colors hover:bg-muted/60">
                    {copiado ? <Check className="h-4 w-4 text-emerald-500" /> : <Copy className="h-4 w-4" />}{copiado ? "Copiado!" : "Copiar"}
                  </button>
                </div>
              </div>
            )}
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2 rounded-xl border border-border/50 bg-muted/20 p-3">
                <p className="text-xs font-semibold text-foreground">Até onde os leads chegaram</p>
                {a.funil.map((e) => {
                  const v = VISUAL_FASE[e.fase] ?? VISUAL_FASE.sdr;
                  return (
                    <div key={e.fase}>
                      <div className="mb-1 flex justify-between text-[11px]"><span className="text-muted-foreground">{e.nome}</span><span className="font-semibold text-foreground">{fmtNum(e.chegaram)}</span></div>
                      <div className="h-1.5 overflow-hidden rounded-full bg-secondary">
                        <div className="h-full rounded-full" style={{ width: `${a.leads ? (e.chegaram / a.leads) * 100 : 0}%`, background: `linear-gradient(90deg, ${v.de}, ${v.ate})` }} />
                      </div>
                    </div>
                  );
                })}
              </div>
              <div className="rounded-xl border border-border/50 bg-muted/20 p-3">
                <p className="mb-2 text-xs font-semibold text-foreground">Leads e contratos por dia</p>
                <div style={{ height: 150 }}>
                  <ResponsiveContainer>
                    <BarChart data={a.serie} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
                      <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" vertical={false} />
                      <XAxis dataKey="dia" tickFormatter={fmtDia} tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} minTickGap={16} axisLine={false} tickLine={false} />
                      <YAxis tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} allowDecimals={false} width={32} axisLine={false} tickLine={false} />
                      <RTooltip labelFormatter={(v) => fmtData(String(v) + "T12:00:00")} contentStyle={{ borderRadius: 8, fontSize: 12 }} />
                      <Bar dataKey="leads" name="Leads" fill="#8b5cf6" radius={[4, 4, 0, 0]} />
                      <Bar dataKey="assinados" name="Contratos" fill="#15BF41" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </div>
            <div className="rounded-xl border border-border/60">
              <div className="flex items-center justify-between border-b border-border p-3">
                <h4 className="text-sm font-semibold text-foreground">Leads deste anúncio ({fmtNum(a.lista_leads.length)})</h4>
                <button type="button" onClick={exportar}
                  className="flex items-center gap-1.5 rounded-lg bg-muted/50 px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground">
                  <Download className="h-3.5 w-3.5" />CSV
                </button>
              </div>
              <div className="max-h-72 overflow-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-secondary/30 text-xs text-muted-foreground">
                      <th className="px-3 py-2 text-left font-medium">Lead</th><th className="px-3 py-2 text-left font-medium">Entrou em</th>
                      <th className="px-3 py-2 text-left font-medium">Etapa atual</th><th className="px-3 py-2 text-right font-medium">Situação</th>
                    </tr>
                  </thead>
                  <tbody>
                    {a.lista_leads.map((l) => (
                      <tr key={l.id} className="border-b border-border/30 transition-colors last:border-0 hover:bg-secondary/30">
                        <td className="px-3 py-2"><Link to={`/conversas/${l.id}`} className="font-medium text-foreground hover:text-primary">{l.nome || "Contato sem nome"}</Link>
                          <span className="block font-mono text-[11px] text-muted-foreground">{l.telefone}</span></td>
                        <td className="px-3 py-2 text-muted-foreground">{fmtData(l.criado_em)}</td>
                        <td className="px-3 py-2 text-foreground">{l.etapa}<span className="block text-[11px] text-muted-foreground">chegou até {l.alcancou}</span></td>
                        <td className="px-3 py-2 text-right">
                          {l.assinado ? <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-[11px] font-semibold text-emerald-600">Assinou</span>
                            : l.desqualificado ? <span className="rounded-full bg-red-500/10 px-2 py-0.5 text-[11px] font-semibold text-red-500">Desqualificado</span>
                            : l.estado === "pausado" ? <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-[11px] font-semibold text-amber-600">Com a equipe</span>
                            : <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-semibold text-muted-foreground">Em andamento</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {a.lista_leads.length >= 100 && <p className="p-3 text-[11px] text-muted-foreground">Mostrando os 100 leads mais recentes.</p>}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
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
