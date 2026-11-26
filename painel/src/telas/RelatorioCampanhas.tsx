/*
 * Relatórios › Rastreamento de campanhas, no desenho da "Análise de Campanhas" do dashboard original: cabeçalho com o
 * filtro de campanha, cartões de qualificação, funil por campanha + ranking de anúncios, comparação, tabela de
 * campanhas, alertas, tempo até converter + plataformas, horários, leads por dia + teste A/B e o detalhe do anúncio.
 * Dados: GET /api/relatorios/campanhas e /api/relatorios/campanhas/anuncio/{chave}.
 */
import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip as RTooltip, XAxis, YAxis } from "recharts";
import {
  Activity, AlertTriangle, ChevronDown, ChevronUp, FileCheck, FileX, Filter, FlaskConical, GitCompareArrows, Megaphone, Minus,
  PieChart as IconePizza, Search, Table2, Timer, TrendingDown, Trophy, UserCheck, UserX, Users,
} from "lucide-react";
import { Carregando, useCarregar } from "../componentes/ui";
import { useSessao } from "../sessao";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import {
  Abas, BarraFiltros, BotoesExportar, CARTAO, CartaoHorarios, Contador, DetalheDoAnuncio, FunilDegraus, ModalTodosAnuncios, Posicao,
  SeloAtualizado, Vazio, baixarCsv, exportarAnuncios, fmtBRL, fmtData, fmtHoras, fmtNum, fmtPct, infoPlataforma, textoPeriodo,
  useFiltros, useOpcoesFiltro, type Anuncio, type EtapaFunil,
} from "./relatoriosComum";

interface Grupo {
  leads: number; closer: number; contratos: number; assinatura: number; assinados: number; desqualificados: number;
  qualificados: number; conversao: number | null; qualificacao: number | null; desqualificacao: number | null;
  horas_ate_assinar: number | null; custo_brl: number; custo_por_lead: number | null; custo_por_contrato: number | null;
  primeiro_lead: string | null; ultimo_lead: string | null;
}
interface Campanha extends Grupo { campanha: string }
interface Plataforma extends Grupo { plataforma: string; nome: string }
interface Alerta { campanha: string; gravidade: "alta" | "media"; titulo: string; texto: string }
interface TesteAB {
  campanha: string; vencedor: string | null; perdedor: string; diferenca: number; recomendacao: string;
  anuncios: { chave: string; nome: string; leads: number; assinados: number; desqualificados: number; conversao: number | null; plataforma_nome: string }[];
}
interface Campanhas {
  periodo: { de: string; ate: string; dias: number };
  kpis: { leads: number; assinados: number; conversao: number | null; qualificados: number; qualificados_pct: number | null;
          desqualificados: number; desqualificados_pct: number | null; campanhas: number; anuncios: number;
          media_leads_por_anuncio: number | null };
  funil: EtapaFunil[];
  tempo_ate_assinar: { media_horas: number | null; mediana_horas: number | null };
  campanhas: Campanha[]; anuncios: Anuncio[]; plataformas: Plataforma[];
  alertas: Alerta[];
  ab: TesteAB[];
  serie: { dia: string; leads: number; assinados: number }[];
  horarios: { leads: number[][]; assinados: number[][] };
  gerado_em: string;
}

export function TelaRelatorioCampanhas() {
  const { escritorio } = useSessao();
  const { filtros, mudar, consulta } = useFiltros();
  const dados = useCarregar<Campanhas>(escritorio ? `/relatorios/campanhas?${consulta}` : null, [escritorio, consulta]);
  const [anuncioAberto, setAnuncioAberto] = useState<string | null>(null);
  const d = dados.dados;

  const exportarCampanhas = () => {
    if (!d) return;
    baixarCsv(`campanhas-${d.periodo.de}-a-${d.periodo.ate}.csv`,
      ["Campanha", "Leads", "Chegaram ao Closer", "Chegaram a Contratos", "Chegaram à Assinatura", "Contratos assinados", "Desqualificados",
       "Conversão (%)", "Tempo médio até assinar (h)", "Custo da IA (R$)", "Custo por contrato (R$)"],
      d.campanhas.map((c) => [c.campanha, c.leads, c.closer, c.contratos, c.assinatura, c.assinados, c.desqualificados, c.conversao,
                              c.horas_ate_assinar, c.custo_brl, c.custo_por_contrato]));
  };

  return (
    <TooltipProvider delayDuration={150}>
      <div className="rl-relatorio space-y-6 pb-4">
        <BarraFiltros id="campanhas" filtros={filtros} mudar={mudar} aoAtualizar={dados.recarregar} atualizando={dados.carregando} recolhidaDeInicio />

        <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}
          className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="flex items-center gap-2 text-xl font-bold tracking-tight text-foreground">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-[#8ED393] to-[#15BF41] text-white shadow-sm shadow-emerald-500/20">
                <Megaphone className="h-[18px] w-[18px]" />
              </span>
              Rastreamento de campanhas
            </h1>
            <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
              <span className="flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
                {d ? `${fmtNum(d.kpis.leads)} leads de anúncio ou UTM` : "Carregando…"}
              </span>
              <span className="text-muted-foreground/40">·</span>
              {textoPeriodo(filtros.de, filtros.ate)}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <SeloAtualizado data={d?.gerado_em} aoAtualizar={dados.recarregar} atualizando={dados.carregando} />
            <FiltroCampanha valor={filtros.campanha} aoEscolher={(c) => mudar({ campanha: c })} />
          </div>
        </motion.div>

        {!d ? <Carregando erro={dados.erro} /> : (
          <Conteudo d={d} abrir={setAnuncioAberto} filtrarCampanha={(c) => mudar({ campanha: c })}
            exportarCampanhas={exportarCampanhas} exportarAnuncios={() => exportarAnuncios(d.anuncios, d.periodo.de, d.periodo.ate)} />
        )}
        <DetalheDoAnuncio chave={anuncioAberto} consulta={consulta} aoFechar={() => setAnuncioAberto(null)} />
      </div>
    </TooltipProvider>
  );
}

/** Seletor de campanha do original (botão com funil + lista com busca). */
function FiltroCampanha({ valor, aoEscolher }: { valor: string; aoEscolher: (c: string) => void }) {
  const opcoes = useOpcoesFiltro();
  const [aberto, setAberto] = useState(false);
  const [busca, setBusca] = useState("");
  const lista = opcoes.dados?.campanhas ?? [];
  const total = lista.reduce((s, c) => s + c.leads, 0);
  const filtradas = busca ? lista.filter((c) => c.campanha.toLowerCase().includes(busca.toLowerCase())) : lista;
  const escolher = (c: string) => { aoEscolher(c); setAberto(false); setBusca(""); };
  return (
    <Popover open={aberto} onOpenChange={setAberto}>
      <PopoverTrigger asChild>
        <button type="button" className="flex items-center gap-2 rounded-lg border border-border bg-card px-4 py-2.5 text-sm font-medium text-foreground shadow-card transition-colors hover:bg-muted/40 print:hidden">
          <Filter className="h-4 w-4 text-primary" />
          <span className="max-w-[180px] truncate sm:max-w-[250px]">{valor || "Todas as Campanhas"}</span>
          <ChevronDown className="h-4 w-4 text-muted-foreground" />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-[340px] p-0" align="end">
        <div className="border-b border-border p-2">
          <div className="flex items-center gap-2 rounded-md border border-border bg-muted/30 px-2.5 py-1.5">
            <Search className="h-3.5 w-3.5 text-muted-foreground" />
            <input value={busca} onChange={(e) => setBusca(e.target.value)} placeholder="Buscar campanha..."
              className="flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground" />
          </div>
        </div>
        <div className="max-h-[300px] overflow-y-auto p-1">
          <button type="button" onClick={() => escolher("")}
            className={cn("flex w-full items-center justify-between rounded-md px-3 py-2 text-sm transition-colors", !valor ? "bg-primary/10 font-medium text-primary" : "text-foreground hover:bg-muted/40")}>
            Todas as Campanhas<span className="text-xs tabular-nums text-muted-foreground">{fmtNum(total)} leads</span>
          </button>
          {filtradas.map((c) => (
            <button key={c.campanha} type="button" onClick={() => escolher(c.campanha)}
              className={cn("flex w-full items-center justify-between rounded-md px-3 py-2 text-sm transition-colors", valor === c.campanha ? "bg-primary/10 font-medium text-primary" : "text-foreground hover:bg-muted/40")}>
              <span className="mr-2 truncate">{c.campanha}</span><span className="shrink-0 text-xs tabular-nums text-muted-foreground">{fmtNum(c.leads)} leads</span>
            </button>
          ))}
          {!filtradas.length && <p className="px-3 py-4 text-center text-xs text-muted-foreground">Nenhuma campanha encontrada</p>}
        </div>
      </PopoverContent>
    </Popover>
  );
}

// --------------------------------------------------------------------------- cartões de qualificação
const CURVAS = {
  sobe: "M0,62 C40,58 70,46 110,40 C150,34 190,24 230,16 C260,11 290,8 320,5",
  onda: "M0,55 C35,40 70,34 105,40 C140,46 175,56 210,50 C245,44 280,26 320,18",
  arco: "M0,68 C40,52 80,30 130,22 C180,16 230,28 270,38 C290,42 310,46 320,50",
  desce: "M0,18 C40,22 75,30 120,38 C165,46 210,52 255,58 C280,61 300,64 320,66",
};

function CartoesQualificacao({ d }: { d: Campanhas }) {
  const k = d.kpis;
  const itens = [
    { rotulo: "Total de Leads", valor: k.leads, pct: false, sub: `${fmtNum(k.campanhas)} campanhas · ${fmtNum(k.anuncios)} anúncios`, icone: Users, traco: "#3b82f6", fill: "#93c5fd",
      fundoIcone: "bg-blue-100", corIcone: "text-blue-600", corValor: "text-blue-600", tint: "from-blue-50/70", curva: CURVAS.sobe },
    { rotulo: "Qualificados", valor: k.qualificados_pct ?? 0, pct: true, sub: `${fmtNum(k.qualificados)} leads`, icone: UserCheck, traco: "#0ea5e9", fill: "#7dd3fc",
      fundoIcone: "bg-sky-100", corIcone: "text-sky-600", corValor: "text-sky-600", tint: "from-sky-50/70", curva: CURVAS.onda },
    { rotulo: "Contratos Assinados", valor: k.conversao ?? 0, pct: true, sub: `${fmtNum(k.assinados)} leads`, icone: FileCheck, traco: "#15bf41", fill: "#86efac",
      fundoIcone: "bg-emerald-100", corIcone: "text-emerald-600", corValor: "text-emerald-600", tint: "from-emerald-50/70", curva: CURVAS.arco, destaque: true },
    { rotulo: "Desqualificados", valor: k.desqualificados_pct ?? 0, pct: true, sub: `${fmtNum(k.desqualificados)} leads`, icone: UserX, traco: "#ef4444", fill: "#fca5a5",
      fundoIcone: "bg-red-100", corIcone: "text-red-600", corValor: "text-red-600", tint: "from-rose-50/70", curva: CURVAS.desce },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4 md:gap-4">
      {itens.map((it, i) => {
        const gid = `rl-camp-kpi-${i}`;
        return (
          <motion.div key={it.rotulo} initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.07, duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
            className={cn("group relative overflow-hidden rounded-2xl border bg-card bg-gradient-to-br to-transparent transition-all duration-300 hover:-translate-y-1 hover:shadow-md", it.tint,
              it.destaque ? "col-span-2 border-emerald-200 ring-1 ring-emerald-500/20 md:col-span-1" : "border-border/50")}>
            <div className="pointer-events-none absolute -bottom-8 left-1/2 h-16 w-[130%] -translate-x-1/2 opacity-[0.10] blur-2xl transition-opacity duration-500 group-hover:opacity-20"
              style={{ background: it.traco }} />
            <div className="relative px-4 pb-2 pt-4 md:px-5">
              <div className="flex items-start justify-between gap-2">
                <p className="text-[11px] font-semibold text-foreground/75 md:text-xs">{it.rotulo}</p>
                <div className={cn("flex h-9 w-9 items-center justify-center rounded-xl transition-transform duration-300 group-hover:scale-110", it.fundoIcone)}>
                  <it.icone className={cn("h-[18px] w-[18px]", it.corIcone)} />
                </div>
              </div>
              <div className={cn("mt-2 text-2xl font-bold leading-none tracking-tight tabular-nums md:text-[32px]", it.corValor)}>
                <Contador valor={it.valor} casas={it.pct ? 1 : 0} sufixo={it.pct ? "%" : ""} />
              </div>
              <p className="mt-1.5 text-xs text-muted-foreground">{it.sub}</p>
            </div>
            <div className="relative mt-1 h-[42px] w-full" aria-hidden>
              <svg className="absolute inset-0 h-full w-full" viewBox="0 0 320 80" preserveAspectRatio="none" fill="none">
                <defs>
                  <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={it.fill} stopOpacity="0.4" /><stop offset="100%" stopColor={it.fill} stopOpacity="0" />
                  </linearGradient>
                </defs>
                <path d={`${it.curva} L320,80 L0,80 Z`} fill={`url(#${gid})`} />
                <motion.path d={it.curva} stroke={it.traco} strokeWidth={2} strokeLinecap="round" fill="none"
                  initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ delay: i * 0.07 + 0.3, duration: 0.9, ease: "easeInOut" }} />
              </svg>
            </div>
          </motion.div>
        );
      })}
    </div>
  );
}

// --------------------------------------------------------------------------- ranking de anúncios
function RankingAnuncios({ d, abrir }: { d: Campanhas; abrir: (c: string) => void }) {
  const [modo, setModo] = useState<"leads" | "assinados">("leads");
  const [todos, setTodos] = useState(false);
  const ordenados = useMemo(() => {
    const l = modo === "assinados" ? d.anuncios.filter((a) => a.assinados > 0) : [...d.anuncios];
    return l.sort((a, b) => b[modo] - a[modo] || (b.conversao ?? 0) - (a.conversao ?? 0));
  }, [d.anuncios, modo]);
  const visiveis = ordenados.slice(0, 5);
  const max = Math.max(1, ...visiveis.map((a) => a[modo]));
  const totalLeads = d.anuncios.reduce((s, a) => s + a.leads, 0);
  return (
    <div className={cn(CARTAO, "p-5")}>
      <div className="mb-4 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-amber-100 to-yellow-200 shadow-sm">
            <Trophy className="h-[18px] w-[18px] text-amber-600" />
          </span>
          <div>
            <h3 className="text-base font-bold tracking-tight text-foreground">Ranking de Anúncios</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">{fmtNum(totalLeads)} leads de anúncios · média de {fmtNum(d.kpis.media_leads_por_anuncio)} por anúncio</p>
          </div>
        </div>
        {ordenados.length > 5 && (
          <button type="button" onClick={() => setTodos(true)}
            className="flex items-center gap-1 rounded-lg border border-border/60 bg-background px-2.5 py-1.5 text-[11px] font-medium text-muted-foreground transition-all hover:-translate-y-0.5 hover:border-border hover:text-foreground print:hidden">
            Ver mais ({ordenados.length})<ChevronDown className="h-3 w-3" />
          </button>
        )}
      </div>
      <div className="mb-4"><Abas cheia valor={modo} aoMudar={setModo} opcoes={[{ valor: "leads", rotulo: "Leads" }, { valor: "assinados", rotulo: "Contrato Assinado" }]} /></div>
      <div className="space-y-1.5">
        {visiveis.map((a, i) => {
          const p = infoPlataforma(a.plataforma, a.plataforma_nome);
          const valor = a[modo];
          return (
            <motion.button key={a.chave} type="button" initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.06 }}
              onClick={() => abrir(a.chave)}
              className={cn("group flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition-all hover:-translate-y-0.5 hover:shadow-sm",
                i === 0 ? "border-amber-200/60 bg-gradient-to-r from-amber-50/60 to-transparent" : "border-transparent hover:border-border/60 hover:bg-muted/30")}>
              <Posicao i={i} grande />
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-muted/60">{p.icone}</span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-foreground" title={a.nome}>{a.nome}</p>
                <p className="mb-1.5 truncate text-[11px] text-muted-foreground" title={a.campanha}>{a.campanha}</p>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted/70">
                  <motion.div className="h-full rounded-full" style={{ background: p.barra }} initial={{ width: 0 }}
                    animate={{ width: `${Math.round((valor / max) * 100)}%` }} transition={{ delay: i * 0.06 + 0.2, duration: 0.8, ease: "easeOut" }} />
                </div>
              </div>
              <div className="flex shrink-0 flex-col items-end gap-1">
                <span className="text-base font-bold tabular-nums text-foreground">{fmtNum(valor)}</span>
                {modo === "leads" && (a.conversao ?? 0) > 0 && (
                  <span className="rounded-full bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-semibold tabular-nums text-emerald-600">{fmtPct(a.conversao)}</span>
                )}
              </div>
            </motion.button>
          );
        })}
        {!ordenados.length && <Vazio icone={<Megaphone className="h-6 w-6" />}>{modo === "assinados" ? "Nenhum anúncio trouxe contrato assinado no período" : "Nenhum anúncio encontrado"}</Vazio>}
      </div>
      <ModalTodosAnuncios aberto={todos} aoFechar={() => setTodos(false)} anuncios={ordenados} abrir={abrir} titulo="Todos os Anúncios da Campanha"
        ordem={modo === "leads" ? "leads" : "contratos"} />
    </div>
  );
}

// --------------------------------------------------------------------------- comparação e tabela de campanhas
function Comparacao({ d }: { d: Campanhas }) {
  const [escolhidas, setEscolhidas] = useState<string[]>([]);
  const metricas = escolhidas.map((n) => d.campanhas.find((c) => c.campanha === n)).filter(Boolean) as Campanha[];
  const alternar = (n: string) => setEscolhidas((e) => (e.includes(n) ? e.filter((x) => x !== n) : e.length >= 3 ? e : [...e, n]));
  const LINHAS: { rotulo: string; valor: (c: Campanha) => number | null; fmt: (v: number | null) => string; maiorMelhor: boolean }[] = [
    { rotulo: "Total de Leads", valor: (c) => c.leads, fmt: (v) => fmtNum(v), maiorMelhor: true },
    { rotulo: "Taxa Qualificação", valor: (c) => c.qualificacao, fmt: (v) => fmtPct(v ?? 0), maiorMelhor: true },
    { rotulo: "Taxa Conversão", valor: (c) => c.conversao, fmt: (v) => fmtPct(v ?? 0), maiorMelhor: true },
    { rotulo: "Contratos", valor: (c) => c.assinados, fmt: (v) => fmtNum(v), maiorMelhor: true },
    { rotulo: "Tempo Médio", valor: (c) => c.horas_ate_assinar, fmt: (v) => (v != null ? `${(v / 24).toLocaleString("pt-BR", { maximumFractionDigits: 1, minimumFractionDigits: 1 })} dias` : "—"), maiorMelhor: false },
    { rotulo: "Custo da IA", valor: (c) => c.custo_brl, fmt: (v) => fmtBRL(v), maiorMelhor: false },
  ];
  return (
    <div className={cn(CARTAO, "p-5")}>
      <div className="mb-1 flex items-center gap-2"><GitCompareArrows className="h-4 w-4 text-primary" /><h3 className="text-sm font-semibold text-foreground">Comparação de Campanhas</h3></div>
      <p className="mb-3 text-[11px] text-muted-foreground">Selecione 2 ou 3 campanhas para comparar</p>
      <div className="mb-4 flex max-h-[120px] flex-wrap gap-1.5 overflow-y-auto print:hidden">
        {d.campanhas.map((c) => (
          <button key={c.campanha} type="button" onClick={() => alternar(c.campanha)} aria-pressed={escolhidas.includes(c.campanha)}
            className={cn("rounded-full border px-2.5 py-1 text-[11px] transition-colors",
              escolhidas.includes(c.campanha) ? "border-primary bg-primary text-primary-foreground" : "border-border bg-muted/50 text-muted-foreground hover:bg-muted")}>
            {c.campanha.length > 35 ? c.campanha.slice(0, 35) + "…" : c.campanha}
          </button>
        ))}
      </div>
      {metricas.length >= 2 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="py-2 text-left text-xs font-medium text-muted-foreground">Métrica</th>
                {metricas.map((m) => <th key={m.campanha} className="max-w-[180px] truncate py-2 text-right text-xs font-medium text-foreground">{m.campanha}</th>)}
              </tr>
            </thead>
            <tbody>
              {LINHAS.map((l) => {
                const vals = metricas.map(l.valor).filter((v): v is number => v != null);
                const melhor = vals.length ? (l.maiorMelhor ? Math.max(...vals) : Math.min(...vals)) : null;
                return (
                  <tr key={l.rotulo} className="border-b border-border/50">
                    <td className="py-2.5 text-xs text-muted-foreground">{l.rotulo}</td>
                    {metricas.map((m) => (
                      <td key={m.campanha} className={cn("py-2.5 text-right text-sm font-medium tabular-nums", l.valor(m) === melhor ? "text-green-500" : "text-foreground")}>{l.fmt(l.valor(m))}</td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : <p className="py-4 text-center text-xs text-muted-foreground">Selecione pelo menos 2 campanhas acima para ver a comparação</p>}
    </div>
  );
}

type Coluna = "leads" | "closer" | "contratos" | "assinados" | "desqualificados" | "conversao" | "horas_ate_assinar" | "custo_brl";

function TabelaCampanhas({ d, filtrar }: { d: Campanhas; filtrar: (c: string) => void }) {
  const [coluna, setColuna] = useState<Coluna>("leads");
  const lista = useMemo(() => [...d.campanhas].sort((a, b) => ((b[coluna] ?? -1) as number) - ((a[coluna] ?? -1) as number)), [d.campanhas, coluna]);
  const max = Math.max(1, ...d.campanhas.map((c) => c.leads));
  const Cab = ({ c, rotulo }: { c: Coluna; rotulo: string }) => (
    <th className="py-2 text-right text-xs font-medium text-muted-foreground">
      <button type="button" onClick={() => setColuna(c)} title="Ordenar"
        className={cn("inline-flex items-center gap-1 transition-colors", coluna === c ? "text-primary" : "hover:text-foreground")}>
        {rotulo}<ChevronDown className={cn("h-3 w-3", coluna === c ? "opacity-100" : "opacity-30")} />
      </button>
    </th>
  );
  return (
    <div className={cn(CARTAO, "p-5")}>
      <div className="mb-1 flex items-center gap-2"><Table2 className="h-4 w-4 text-primary" /><h3 className="text-sm font-semibold text-foreground">Campanhas</h3></div>
      <p className="mb-3 text-[11px] text-muted-foreground">Quantos leads de cada campanha chegaram a cada etapa. Clique no nome para filtrar a tela pela campanha.</p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] text-sm">
          <thead>
            <tr className="border-b border-border">
              <th className="py-2 text-left text-xs font-medium text-muted-foreground">Campanha</th>
              <Cab c="leads" rotulo="Leads" /><Cab c="closer" rotulo="Closer" /><Cab c="contratos" rotulo="Contratos" /><Cab c="assinados" rotulo="Assinados" />
              <Cab c="desqualificados" rotulo="Desqualif." /><Cab c="conversao" rotulo="Conversão" /><Cab c="horas_ate_assinar" rotulo="Até assinar" /><Cab c="custo_brl" rotulo="Custo da IA" />
            </tr>
          </thead>
          <tbody>
            {lista.map((c) => (
              <tr key={c.campanha} className="border-b border-border/50 transition-colors last:border-0 hover:bg-muted/30">
                <td className="max-w-[300px] py-2.5 pr-3">
                  <button type="button" onClick={() => filtrar(c.campanha)} title="Filtrar por esta campanha" className="block max-w-full truncate text-left font-medium text-foreground hover:text-primary">{c.campanha}</button>
                  <div className="mt-1 h-1.5 w-full max-w-[200px] overflow-hidden rounded-full bg-muted/60">
                    <div className="h-full rounded-full bg-gradient-to-r from-[#8ED393] to-[#15BF41]" style={{ width: `${(c.leads / max) * 100}%` }} />
                  </div>
                  {c.primeiro_lead && <span className="mt-0.5 block text-[10px] text-muted-foreground">{fmtData(c.primeiro_lead)} a {fmtData(c.ultimo_lead)}</span>}
                </td>
                <td className="py-2.5 text-right font-medium tabular-nums text-foreground">{fmtNum(c.leads)}</td>
                <td className="py-2.5 text-right tabular-nums text-foreground">{fmtNum(c.closer)}</td>
                <td className="py-2.5 text-right tabular-nums text-foreground">{fmtNum(c.contratos)}</td>
                <td className="py-2.5 text-right font-semibold tabular-nums text-emerald-600">{fmtNum(c.assinados)}</td>
                <td className="py-2.5 text-right tabular-nums text-red-500">{fmtNum(c.desqualificados)}</td>
                <td className="py-2.5 text-right tabular-nums text-foreground">{fmtPct(c.conversao ?? 0)}</td>
                <td className="py-2.5 text-right tabular-nums text-foreground">{fmtHoras(c.horas_ate_assinar)}</td>
                <td className="py-2.5 text-right tabular-nums text-foreground" title={c.custo_por_contrato != null ? `${fmtBRL(c.custo_por_contrato)} por contrato` : undefined}>{fmtBRL(c.custo_brl)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- alertas
function Alertas({ d }: { d: Campanhas }) {
  const [aberto, setAberto] = useState<Alerta | null>(null);
  const [todos, setTodos] = useState(false);
  if (!d.alertas.length) return null;
  const dados = (a: Alerta) => d.campanhas.find((c) => c.campanha === a.campanha);
  const icone = (a: Alerta) => (/nenhum contrato/i.test(a.titulo) ? <Users className="h-3.5 w-3.5" /> : /desqualific/i.test(a.titulo) ? <FileX className="h-3.5 w-3.5" /> : <TrendingDown className="h-3.5 w-3.5" />);
  const Linha = ({ a, i }: { a: Alerta; i: number }) => {
    const c = dados(a);
    return (
      <motion.button type="button" initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.05 }} onClick={() => setAberto(a)}
        className="flex w-full items-center gap-3 rounded-lg border border-border bg-card p-3 text-left transition-colors hover:border-emerald-500/30 hover:bg-emerald-500/10">
        <div className={cn("flex h-7 w-7 shrink-0 items-center justify-center rounded-full", a.gravidade === "alta" ? "bg-red-500/10 text-red-500" : "bg-yellow-500/10 text-yellow-500")}>{icone(a)}</div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-foreground">{a.campanha}</p>
          <p className="text-xs text-muted-foreground">{c ? `${fmtNum(c.leads)} leads · ${fmtNum(c.assinados)} contratos · ${fmtPct(c.desqualificacao ?? 0)} desqualif.` : a.texto}</p>
        </div>
        <span className={cn("whitespace-nowrap rounded-full border px-2 py-0.5 text-[10px] font-semibold",
          a.gravidade === "alta" ? "border-red-500/20 bg-red-500/10 text-red-500" : "border-yellow-500/20 bg-yellow-500/10 text-yellow-600")}>{a.titulo}</span>
      </motion.button>
    );
  };
  const c = aberto ? dados(aberto) : null;
  return (
    <>
      <div className="rounded-xl border border-yellow-500/30 bg-yellow-500/5 p-4">
        <div className="mb-3 flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-yellow-500" />
          <h3 className="text-sm font-semibold text-foreground">Campanhas que Precisam de Atenção</h3>
          <span className="rounded-full border border-yellow-500/30 bg-yellow-500/20 px-2 py-0.5 text-[10px] font-semibold text-yellow-600">{d.alertas.length} alerta{d.alertas.length > 1 ? "s" : ""}</span>
        </div>
        <div className="space-y-2">{d.alertas.slice(0, 5).map((a, i) => <Linha key={a.campanha} a={a} i={i} />)}</div>
        {d.alertas.length > 5 && (
          <button type="button" onClick={() => setTodos(true)} className="mt-2 flex w-full items-center justify-center gap-1 rounded-lg py-2 text-xs font-medium text-primary transition-colors hover:bg-muted/40 print:hidden">
            Ver mais ({d.alertas.length - 5})<ChevronDown className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
      <Dialog open={todos} onOpenChange={setTodos}>
        <DialogContent className="max-h-[85vh] max-w-2xl">
          <DialogHeader>
            <DialogTitle className="text-base font-bold text-foreground">Todas as Campanhas com Alertas</DialogTitle>
            <DialogDescription className="text-xs text-muted-foreground">{d.alertas.length} campanhas precisam de atenção</DialogDescription>
          </DialogHeader>
          <div className="max-h-[60vh] space-y-2 overflow-y-auto pr-2">{d.alertas.map((a, i) => <Linha key={a.campanha} a={a} i={i} />)}</div>
        </DialogContent>
      </Dialog>
      <Dialog open={Boolean(aberto)} onOpenChange={(v) => !v && setAberto(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="text-base font-bold text-foreground">Detalhes da Campanha</DialogTitle>
            <DialogDescription className="truncate text-xs text-muted-foreground">{aberto?.campanha}</DialogDescription>
          </DialogHeader>
          {aberto && (
            <div className="space-y-4">
              {c && (
                <>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="rounded-lg border border-border bg-muted/30 p-3"><p className="text-xs text-muted-foreground">Total de Leads</p><p className="text-xl font-bold text-foreground">{fmtNum(c.leads)}</p></div>
                    <div className="rounded-lg border border-border bg-muted/30 p-3"><p className="text-xs text-muted-foreground">Contratos</p><p className="text-xl font-bold text-emerald-500">{fmtNum(c.assinados)}</p></div>
                    <div className="rounded-lg border border-border bg-muted/30 p-3"><p className="text-xs text-muted-foreground">Qualificados</p><p className="text-xl font-bold text-blue-500">{fmtNum(c.qualificados)}</p></div>
                    <div className="rounded-lg border border-border bg-muted/30 p-3"><p className="text-xs text-muted-foreground">Desqualificados</p><p className="text-xl font-bold text-red-500">{fmtNum(c.desqualificados)}</p></div>
                  </div>
                  <div className="space-y-2">
                    <div className="flex justify-between text-sm"><span className="text-muted-foreground">Taxa de conversão</span><span className="font-medium text-foreground">{fmtPct(c.conversao ?? 0)}</span></div>
                    <div className="flex justify-between text-sm"><span className="text-muted-foreground">Taxa de desqualificação</span><span className="font-medium text-foreground">{fmtPct(c.desqualificacao ?? 0)}</span></div>
                  </div>
                </>
              )}
              <div className={cn("rounded-lg border p-3", aberto.gravidade === "alta" ? "border-red-500/20 bg-red-500/10" : "border-yellow-500/20 bg-yellow-500/10")}>
                <p className="mb-1 flex items-center gap-1.5 text-xs font-medium text-foreground"><AlertTriangle className="h-3.5 w-3.5 text-yellow-500" />{aberto.titulo}</p>
                <p className="text-xs text-muted-foreground">{aberto.texto}</p>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}

// --------------------------------------------------------------------------- tempo até converter e plataformas
const CORES_TEMPO = ["hsl(134, 60%, 42%)", "hsl(187, 85%, 40%)", "hsl(217, 91%, 50%)", "hsl(32, 95%, 48%)", "hsl(43, 96%, 56%)"];
const LIMITE = 6;

function TempoConversao({ d }: { d: Campanhas }) {
  const [todos, setTodos] = useState(false);
  const dados = d.campanhas.filter((c) => c.horas_ate_assinar != null && c.assinados > 0)
    .map((c) => ({ nome: c.campanha.length > 30 ? c.campanha.slice(0, 30) + "…" : c.campanha, completo: c.campanha, horas: c.horas_ate_assinar as number,
                   dias: (c.horas_ate_assinar as number) / 24, contratos: c.assinados }))
    .sort((a, b) => a.horas - b.horas);
  const visiveis = todos ? dados : dados.slice(0, LIMITE);
  return (
    <div className={cn(CARTAO, "p-5")}>
      <div className="mb-1 flex items-center gap-2"><Timer className="h-4 w-4 text-primary" /><h3 className="text-sm font-semibold text-foreground">Tempo Médio de Conversão</h3></div>
      {!dados.length ? <Vazio>Nenhuma campanha com contratos assinados</Vazio> : (
        <>
          <p className="mb-4 text-[11px] text-muted-foreground">
            Da entrada do lead ao contrato assinado (campanhas mais rápidas primeiro) · média geral {fmtHoras(d.tempo_ate_assinar.media_horas)}, mediana {fmtHoras(d.tempo_ate_assinar.mediana_horas)}
          </p>
          <ResponsiveContainer width="100%" height={Math.max(200, visiveis.length * 48)}>
            <BarChart data={visiveis} layout="vertical" margin={{ left: 10, right: 30, top: 5, bottom: 5 }}>
              <XAxis type="number" hide />
              <YAxis type="category" dataKey="nome" width={150} tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} axisLine={false} tickLine={false} />
              <RTooltip cursor={{ fill: "hsl(var(--muted) / 0.5)" }} content={({ active, payload }) => {
                if (!active || !payload?.[0]) return null;
                const x = payload[0].payload as (typeof dados)[number];
                return (
                  <div className="rounded-lg border border-border bg-card px-3 py-2 shadow-lg">
                    <p className="text-xs font-medium text-foreground">{x.completo}</p>
                    <p className="text-xs text-muted-foreground">Tempo médio: {fmtHoras(x.horas)}</p>
                    <p className="text-xs text-muted-foreground">{x.contratos} contrato{x.contratos > 1 ? "s" : ""}</p>
                  </div>
                );
              }} />
              <Bar dataKey="dias" radius={[0, 6, 6, 0]} barSize={24}>
                {visiveis.map((_, i) => <Cell key={i} fill={CORES_TEMPO[i % CORES_TEMPO.length]} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <div className="mt-3 space-y-1">
            {visiveis.map((x, i) => (
              <div key={x.completo} className="flex items-center justify-between gap-3 px-1 text-xs">
                <span className="truncate text-muted-foreground">{i + 1}. <span className="font-medium text-foreground">{x.completo}</span></span>
                <span className="shrink-0 font-medium tabular-nums text-foreground">{fmtHoras(x.horas)} · {x.contratos} contrato{x.contratos > 1 ? "s" : ""}</span>
              </div>
            ))}
          </div>
          {dados.length > LIMITE && (
            <button type="button" onClick={() => setTodos((v) => !v)}
              className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-lg border border-border bg-background py-2 text-xs font-medium text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground print:hidden">
              {todos ? <><ChevronUp className="h-3.5 w-3.5" /> Ver menos</> : <><ChevronDown className="h-3.5 w-3.5" /> Ver mais {dados.length - LIMITE} campanha{dados.length - LIMITE > 1 ? "s" : ""}</>}
            </button>
          )}
        </>
      )}
    </div>
  );
}

function Plataformas({ d }: { d: Campanhas }) {
  const total = d.plataformas.reduce((s, p) => s + p.leads, 0);
  if (!d.plataformas.length) return null;
  const lista = [...d.plataformas].sort((a, b) => b.leads - a.leads);
  const folga = 2;
  const util = 100 - lista.length * folga;
  let desloc = 0;
  return (
    <div className={cn(CARTAO, "p-5")}>
      <div className="mb-4 flex items-center gap-2"><IconePizza className="h-4 w-4 text-primary" /><h3 className="text-sm font-semibold text-foreground">Distribuição por Plataforma</h3></div>
      <div className="mb-5 flex items-center justify-center">
        <div className="relative h-40 w-40">
          <svg viewBox="0 0 100 100" className="h-full w-full -rotate-90" role="img" aria-label="Leads por plataforma">
            {lista.map((p) => {
              const pct = (p.leads / (total || 1)) * util;
              const el = <circle key={p.plataforma} cx="50" cy="50" r="38" fill="none" stroke={infoPlataforma(p.plataforma, p.nome).cor} strokeWidth="12"
                pathLength={100} strokeDasharray={`${pct} ${100 - pct}`} strokeDashoffset={-desloc} strokeLinecap="round" className="transition-all duration-500" />;
              desloc += pct + folga;
              return el;
            })}
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-2xl font-bold text-foreground">{fmtNum(total)}</span>
            <span className="text-[10px] text-muted-foreground">leads</span>
          </div>
        </div>
      </div>
      <div className="space-y-2">
        {lista.map((p) => {
          const info = infoPlataforma(p.plataforma, p.nome);
          return (
            <div key={p.plataforma} className="flex items-center justify-between gap-2">
              <div className="flex min-w-0 items-center gap-2">
                <div className={cn("h-2.5 w-2.5 shrink-0 rounded-full", info.ponto)} />
                <span className="truncate text-sm text-foreground">{info.nome}</span>
                <span className="shrink-0 text-[11px] text-muted-foreground">{fmtNum(p.assinados)} contr. · {fmtPct(p.conversao ?? 0)}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-bold tabular-nums" style={{ color: info.cor }}>{fmtNum(p.leads)}</span>
                <span className="w-10 text-right text-xs tabular-nums text-muted-foreground">{fmtPct(total ? (p.leads / total) * 100 : 0, 0)}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- leads por dia e A/B
function LeadsPorDia({ d }: { d: Campanhas }) {
  return (
    <div className={cn(CARTAO, "p-5")}>
      <div className="mb-1 flex items-center gap-2"><Activity className="h-4 w-4 text-primary" /><h3 className="text-sm font-semibold text-foreground">Leads de Campanhas por Dia</h3></div>
      <p className="mb-4 text-[11px] text-muted-foreground">Entradas e contratos assinados entre elas</p>
      <div className="mb-2 flex items-center gap-3 text-[10px] text-muted-foreground">
        <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-[#15BF41]" />Leads</span>
        <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-violet-500" />Contratos</span>
      </div>
      <div style={{ height: 260 }}>
        <ResponsiveContainer>
          <AreaChart data={d.serie} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
            <defs>
              <linearGradient id="rl-camp-leads" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#15BF41" stopOpacity={0.3} /><stop offset="100%" stopColor="#15BF41" stopOpacity={0} /></linearGradient>
              <linearGradient id="rl-camp-assin" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#8b5cf6" stopOpacity={0.3} /><stop offset="100%" stopColor="#8b5cf6" stopOpacity={0} /></linearGradient>
            </defs>
            <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="dia" tickFormatter={(v: string) => `${v.slice(8, 10)}/${v.slice(5, 7)}`} tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} minTickGap={18} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} allowDecimals={false} width={40} axisLine={false} tickLine={false} />
            <RTooltip labelFormatter={(v) => fmtData(String(v) + "T12:00:00")} contentStyle={{ borderRadius: 8, fontSize: 12 }} />
            <Area type="monotone" dataKey="leads" name="Leads" stroke="#15BF41" fill="url(#rl-camp-leads)" strokeWidth={2.4} />
            <Area type="monotone" dataKey="assinados" name="Contratos" stroke="#8b5cf6" fill="url(#rl-camp-assin)" strokeWidth={2.4} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function TesteAutomatico({ d, abrir }: { d: Campanhas; abrir: (c: string) => void }) {
  const COLS = "grid-cols-[1fr_56px_56px_56px_64px]";
  return (
    <div className={cn(CARTAO, "p-5")}>
      <div className="mb-1 flex items-center gap-2"><FlaskConical className="h-4 w-4 text-primary" /><h3 className="text-sm font-semibold text-foreground">A/B Test Automático</h3></div>
      {!d.ab.length ? <p className="py-6 text-center text-sm text-muted-foreground">Nenhuma campanha com múltiplos anúncios encontrada (mínimo 3 leads por anúncio)</p> : (
        <>
          <p className="mb-4 text-[11px] text-muted-foreground">
            Comparação de anúncios em {d.ab.length} campanha{d.ab.length > 1 ? "s" : ""} · sem teste estatístico: leia como sinal, não como prova · clique num anúncio para ver detalhes
          </p>
          <div className="space-y-5">
            {d.ab.slice(0, 5).map((t, ci) => (
              <motion.div key={t.campanha} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: ci * 0.05 }}>
                <p className="mb-2 truncate text-xs font-bold uppercase tracking-wide text-foreground" title={t.campanha}>{t.campanha}</p>
                <div className="overflow-hidden rounded-lg border border-border">
                  <div className={cn("grid gap-0 bg-muted/60 px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground", COLS)}>
                    <span>Anúncio</span><span className="text-center">Leads</span><span className="text-center">Conv.</span><span className="text-center">Desq.</span><span className="text-center">Taxa</span>
                  </div>
                  {t.anuncios.slice(0, 4).map((a) => {
                    const vence = t.vencedor === a.chave;
                    const perde = t.perdedor === a.chave && Boolean(t.vencedor);
                    return (
                      <div key={a.chave} role="button" tabIndex={0} onClick={() => abrir(a.chave)} onKeyDown={(e) => { if (e.key === "Enter") abrir(a.chave); }}
                        className={cn("grid cursor-pointer items-center gap-0 border-t border-border/50 px-3 py-2 transition-colors hover:bg-primary/5", COLS, vence ? "bg-emerald-500/5" : perde ? "bg-red-500/5" : "")}>
                        <div className="flex min-w-0 items-center gap-2">
                          {vence ? <Trophy className="h-3.5 w-3.5 shrink-0 text-emerald-500" /> : perde ? <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-red-400" /> : <Minus className="h-3.5 w-3.5 shrink-0 text-muted-foreground/40" />}
                          <div className="min-w-0">
                            <p className="truncate text-xs leading-tight text-foreground" title={a.nome}>{a.nome}</p>
                            <p className="text-[10px] leading-tight text-muted-foreground">{a.plataforma_nome.replace(" / Meta", "")}</p>
                          </div>
                        </div>
                        <span className="text-center text-xs font-medium tabular-nums text-foreground">{fmtNum(a.leads)}</span>
                        <span className="text-center text-xs font-medium tabular-nums text-emerald-600">{fmtNum(a.assinados)}</span>
                        <span className="text-center text-xs font-medium tabular-nums text-red-500">{fmtNum(a.desqualificados)}</span>
                        <span className={cn("text-center text-xs font-bold tabular-nums", (a.conversao ?? 0) > 0 ? "text-emerald-600" : "text-muted-foreground")}>{fmtPct(a.conversao ?? 0)}</span>
                      </div>
                    );
                  })}
                </div>
                <div className="mt-2 rounded-lg border border-primary/10 bg-primary/5 px-3 py-1.5">
                  <p className="text-[11px] leading-relaxed text-foreground">💡 {t.recomendacao}</p>
                </div>
              </motion.div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- página
function Conteudo({ d, abrir, filtrarCampanha, exportarCampanhas, exportarAnuncios: exportarAnunciosCsv }: {
  d: Campanhas; abrir: (chave: string) => void; filtrarCampanha: (c: string) => void; exportarCampanhas: () => void; exportarAnuncios: () => void;
}) {
  const campanhasPorFase = useMemo(() => {
    const top = (campo: keyof Grupo) => [...d.campanhas].filter((c) => (c[campo] as number) > 0)
      .sort((a, b) => (b[campo] as number) - (a[campo] as number)).slice(0, 5).map((c) => ({ nome: c.campanha, total: c[campo] as number }));
    return { sdr: top("leads"), closer: top("closer"), contratos: top("contratos"), assinatura: top("assinatura"), assinado: top("assinados") };
  }, [d.campanhas]);

  if (!d.kpis.leads) {
    return (
      <div className={cn(CARTAO, "p-10 text-center")}>
        <Megaphone className="mx-auto mb-3 h-8 w-8 text-muted-foreground/30" />
        <p className="text-sm font-medium text-foreground">Nenhum lead com origem de anúncio ou UTM no período.</p>
        <p className="mt-1 text-xs text-muted-foreground">A origem é registrada quando o lead chega por um anúncio de clique para WhatsApp ou por um link com UTM.</p>
      </div>
    );
  }
  return (
    <div className="space-y-6">
      <CartoesQualificacao d={d} />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <FunilDegraus etapas={d.funil} total={d.kpis.leads} titulo="Funil de Conversão por Campanha" icone={<Filter className="h-4 w-4 shrink-0 text-primary" />}
          subtitulo="Jornada dos leads de anúncio ou UTM · passe o mouse para ver as campanhas" larguras={[100, 88, 76, 64, 52]} campanhasPorFase={campanhasPorFase} />
        <RankingAnuncios d={d} abrir={abrir} />
      </div>
      <Comparacao d={d} />
      <TabelaCampanhas d={d} filtrar={filtrarCampanha} />
      <Alertas d={d} />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <TempoConversao d={d} />
        <Plataformas d={d} />
      </div>
      <CartaoHorarios horarios={d.horarios} subtitulo="Chegada dos leads de campanha e assinaturas (horário de Brasília)" />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <LeadsPorDia d={d} />
        <TesteAutomatico d={d} abrir={abrir} />
      </div>
      <p className="text-center text-[11px] text-muted-foreground/80">
        A origem é a do primeiro contato do lead (anúncio de clique para WhatsApp ou link com UTM). Atualizado em {new Date(d.gerado_em).toLocaleTimeString("pt-BR")}.
      </p>
      <BotoesExportar csv={[{ rotulo: "CSV das campanhas", aoClicar: exportarCampanhas }, { rotulo: "CSV dos anúncios", aoClicar: exportarAnunciosCsv }]} />
    </div>
  );
}
