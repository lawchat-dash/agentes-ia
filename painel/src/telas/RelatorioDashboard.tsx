/*
 * Relatórios › Dashboard, no desenho e na lógica do dashboard comercial original: filtros, indicadores com curva e
 * cartões de etapa pelos CARDS do painel do CRM, funil + melhores anúncios, atendimento e custo da IA (pelos leads),
 * tempo até assinar, evolução por dia, origem + estados, horários, agentes, leads por etapa e os cards do CRM.
 * Dados: GET /api/relatorios/dashboard (e /api/relatorios/campanhas para o ranking de anúncios).
 */
import Counter from "@/components/reactbits/Counter";
import BorderGlow from "@/components/reactbits/BorderGlow";
import GooeyNav from "@/components/reactbits/GooeyNav";
import { AoAparecer } from "../componentes/AoAparecer";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { motion, AnimatePresence, MotionConfig } from "framer-motion";
import FaixaMetricas, { type Metrica } from "@/components/graficos/FaixaMetricas";
import AreaCruz from "@/components/graficos/AreaCruz";
import RoscaTotal from "@/components/graficos/RoscaTotal";
import MapaCalor from "@/components/graficos/MapaCalor";
import MedidorMeta from "@/components/graficos/MedidorMeta";
import BarrasTendencia from "@/components/graficos/BarrasTendencia";
import {
  Activity, AlertTriangle, AreaChart as IconeArea, ArrowDownRight, ArrowUpRight, Award, BarChart3, Bot, CalendarDays, ChevronDown,
  CircleDollarSign, Clock, Download, FileSignature, Filter, Flame, Gauge, Layers, LineChart as IconeLinha, MessageSquare, Moon, PieChart as IconePizza,
  Repeat, Search, ShieldAlert, Sparkles, Sun, Sunset, Target, Timer, TrendingDown, TrendingUp, Trophy, UserCheck, UserX, Users, Megaphone,
} from "lucide-react";
import { toast } from "sonner";
import { enviar } from "../api";
import { useCarregar } from "../componentes/ui";
import { useSessao } from "../sessao";
import { TooltipProvider } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import {
  Abas, BarraFiltros, BotoesExportar, CARTAO, Cascata, Contador, DetalheDoAnuncio, Dica, EsqueletoRelatorio, FunilDegraus,
  ITEM_CASCATA, Insight, MapaEstados, ModalTodosAnuncios, Posicao, Vazio, baixarCsv, exportarAnuncios, fmtBRL, fmtData, fmtHoras, fmtNum,
  fmtPct, fmtSegundos, infoPlataforma, useFiltros, useFundoRelatorios, type Anuncio, type EtapaFunil,
} from "./relatoriosComum";

interface CardsCrm {
  total: number; total_variacao: number | null; assinados: number; assinados_variacao: number | null;
  conversao: number | null; conversao_anterior: number | null; eficiencia: number | null; avancaram: number;
  qualificados: number; qualificados_pct: number | null; desqualificados: number; desqualificados_pct: number | null;
  por_fase: { fase: string; nome: string; total: number; pct: number | null }[];
  funil: EtapaFunil[]; modo: "criacao" | "atualizacao"; todo_periodo: boolean; filtros_do_card: boolean;
}

interface Dashboard {
  base: "cards" | "leads";
  cards: CardsCrm | null;
  periodo: { de: string; ate: string; dias: number };
  kpis: {
    leads: number; leads_variacao: number | null; assinados: number; assinados_variacao: number | null;
    conversao: number | null; conversao_anterior: number | null; eficiencia: number | null;
    qualificados: number; qualificados_pct: number | null; desqualificados: number; desqualificados_pct: number | null;
    ativos: number; pausados: number; encerrados: number; com_origem: number;
    respostas_ia: number; mensagens_lead: number; mensagens_equipe: number;
    primeira_resposta_s: number | null; primeira_resposta_mediana_s: number | null;
    custo_brl: number; custo_variacao: number | null; custo_por_lead: number | null; custo_por_contrato: number | null;
    tokens: number; chamadas_ia: number;
  };
  funil: EtapaFunil[];
  desvios: { desqualificados: number; analise: number };
  tempo_ate_assinar: { media_horas: number | null; mediana_horas: number | null; faixas: { faixa: string; total: number }[] };
  ia: { turnos: number; respondidos: number; sem_resposta: number; erros: number; trocas: number; taxa_erro: number | null;
        duracao_media_s: number | null; duracao_mediana_s: number | null };
  serie: { dia: string; cards?: number; leads: number; assinados: number; respostas_ia: number; mensagens_lead: number; mensagens_equipe: number;
           turnos: number; erros: number; custo_brl: number; tokens: number }[];
  agentes: { id_agente: string | null; nome: string; leads: number; qualificados: number; contratos: number; assinados: number;
             desqualificados: number; conversao: number | null }[];
  etapas: { agente: string; etapa: string | null; nome: string; fase: string; leads: number }[];
  por_fase: { fase: string; nome: string; leads: number }[];
  plataformas: { plataforma: string; nome: string; leads: number; assinados: number }[];
  uf: { leads: Record<string, number>; contratos: Record<string, number> };
  horarios: { leads: number[][]; assinados: number[][] };
  crm: null | { colunas: { fase: string; nome_fase: string; coluna: string | null; total: number; no_periodo: number; sem_lead: number }[];
                total: number; sem_lead: number; no_periodo: number; assinados: number; ultima_varredura: string | null;
                importado_em: string | null; importacao_pedida: boolean; erro: string | null };
  gerado_em: string;
}

export function TelaRelatorioDashboard() {
  const { escritorio } = useSessao();
  const { filtros, mudar, consulta } = useFiltros();
  const dados = useCarregar<Dashboard>(escritorio ? `/relatorios/dashboard?${consulta}` : null, [escritorio, consulta]);
  const camp = useCarregar<{ anuncios: Anuncio[] }>(escritorio ? `/relatorios/campanhas?${consulta}` : null, [escritorio, consulta]);
  const [anuncioAberto, setAnuncioAberto] = useState<string | null>(null);
  const [pedindo, setPedindo] = useState(false);
  useFundoRelatorios();
  const d = dados.dados;
  // Cada resposta nova (outro filtro) remonta o conteúdo: os cartões entram de novo e os números contam do zero.
  const chaveDados = useMemo(() => `${consulta}|${d?.gerado_em ?? ""}`, [d]); // eslint-disable-line react-hooks/exhaustive-deps
  const atualizar = () => { dados.recarregar(); camp.recarregar(); };

  const exportar = () => {
    if (!d) return;
    const k = d.kpis, c = d.cards;
    baixarCsv(`dashboard-${d.periodo.de}-a-${d.periodo.ate}.csv`, ["Seção", "Item", "Valor"], [
      ...(c ? [["Cards do CRM", "Cards totais", c.total], ["Cards do CRM", "Contratos assinados", c.assinados],
               ["Cards do CRM", "Taxa de conversão (%)", c.conversao], ["Cards do CRM", "Taxa de eficiência (%)", c.eficiencia],
               ["Cards do CRM", "% lead qualificado", c.qualificados_pct],
               ...c.por_fase.map((f) => ["Cards por etapa", f.nome, f.total] as (string | number)[])] as (string | number | null)[][] : []),
      ["Leads da IA", "Leads", k.leads], ["Leads da IA", "Contratos assinados", k.assinados],
      ["Leads da IA", "Taxa de conversão (%)", k.conversao], ["Leads da IA", "Desqualificados", k.desqualificados],
      ["IA", "Custo da IA (R$)", k.custo_brl], ["IA", "Custo por lead (R$)", k.custo_por_lead],
      ["IA", "Custo por contrato (R$)", k.custo_por_contrato], ["IA", "Chamadas à IA", k.chamadas_ia],
      ...(c?.funil ?? d.funil).map((e) => ["Funil", e.nome, e.chegaram] as (string | number)[]),
      ...d.agentes.map((a) => ["Agentes", a.nome, `${a.leads} leads, ${a.assinados} contratos`] as (string | number)[]),
      ...d.plataformas.map((p) => ["Origem", p.nome, p.leads] as (string | number)[]),
    ]);
    baixarCsv(`dashboard-por-dia-${d.periodo.de}-a-${d.periodo.ate}.csv`,
      ["Dia", "Cards no CRM", "Leads", "Contratos assinados", "Mensagens dos leads", "Mensagens da equipe", "Respostas com erro", "Custo da IA (R$)"],
      d.serie.map((s) => [s.dia, s.cards ?? 0, s.leads, s.assinados, s.mensagens_lead, s.mensagens_equipe, s.erros, s.custo_brl]));
  };

  const pedirImportacao = async () => {
    setPedindo(true);
    try {
      const r = await enviar<{ mensagem: string }>("/relatorios/crm/importar", {});
      toast.success(r.mensagem);
      dados.recarregar();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setPedindo(false);
    }
  };

  return (
    <MotionConfig reducedMotion="user">
      <TooltipProvider delayDuration={150}>
        <div className="rl-relatorio space-y-5 pb-4">
          <BarraFiltros id="dashboard" filtros={filtros} mudar={mudar} aoAtualizar={atualizar} atualizando={dados.carregando}
            gerado={d?.gerado_em} campos={["modo", "campanha", "painel", "etapa", "responsavel", "numero", "origem", "tags"]} />

          <AnimatePresence mode="wait" initial={false}>
            {!d ? (
              <motion.div key="esqueleto" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }}>
                <EsqueletoRelatorio erro={dados.erro} />
              </motion.div>
            ) : (
              <motion.div key={chaveDados} initial={{ opacity: 0.6 }} animate={{ opacity: 1 }} exit={{ opacity: 0.6 }} transition={{ duration: 0.25 }}
                className={cn("transition-opacity", dados.carregando && "opacity-80")}>
                <Conteudo d={d} anuncios={camp.dados?.anuncios ?? null} abrirAnuncio={setAnuncioAberto} pedirImportacao={pedirImportacao}
                  pedindo={pedindo} filtrando={Boolean(filtros.agente || filtros.campanha || filtros.fonte)} exportar={exportar} />
              </motion.div>
            )}
          </AnimatePresence>
          <DetalheDoAnuncio chave={anuncioAberto} consulta={consulta} aoFechar={() => setAnuncioAberto(null)} />
        </div>
      </TooltipProvider>
    </MotionConfig>
  );
}

/** Abas em pílula com o GooeyNav (React Bits): verde LawChat, texto ativo branco. Sem WebGL, cai numa pílula lisa. */
function AbasGooey<T extends string>({ valor, opcoes, aoMudar }: { valor: T; opcoes: { valor: NoInfer<T>; rotulo: string }[]; aoMudar: (v: NoInfer<T>) => void }) {
  const ativo = Math.max(0, opcoes.findIndex((o) => o.valor === valor));
  return (
    // A tela das gotas passa um pouco da pílula: o recorte evita rolagem lateral (as gotas ainda saem 16 px).
    <div style={{ overflow: "clip", overflowClipMargin: 16, maxWidth: "100%" }}>
      <GooeyNav items={opcoes.map((o) => ({ label: o.rotulo }))} activeIndex={ativo} onChange={(i) => aoMudar(opcoes[i].valor)}
        theme="light" color="#00bc33" activeTextColor="#ffffff" colors={["#00bc33", "#34d399", "#a7f3d0", "#0a8f35"]} size="sm" className="rl-abas-gooey" />
    </div>
  );
}

// --------------------------------------------------------------------------- indicadores
const CURVAS = {
  sobe: "M0,65 C40,62 70,55 110,42 C140,32 180,22 220,15 C250,10 280,7 320,4",
  arco: "M0,70 C40,55 75,32 130,22 C180,16 230,28 270,38 C290,42 310,48 320,52",
  onda: "M0,55 C35,38 70,30 105,38 C140,46 175,58 210,52 C245,46 280,28 320,18",
  suave: "M0,50 C45,46 90,38 135,30 C180,24 225,22 270,20 C290,19 310,18 320,18",
  firme: "M0,45 C50,42 100,36 150,33 C200,30 250,30 290,32 C305,33 320,34 320,34",
  desce: "M0,18 C40,22 75,30 120,38 C165,46 210,52 255,58 C280,61 300,64 320,66",
};

interface Indicador {
  rotulo: string; valor: number | null; tipo?: "num" | "pct" | "brl"; sub: string; dica: string; icone: typeof Users;
  cor: [string, string]; curva: string; corValor?: boolean; variacao?: number | null; inverter?: boolean; destaque?: boolean;
}

function ValorIndicador({ i }: { i: Indicador }) {
  if (i.valor == null) return <>–</>;
  if (i.tipo === "pct") return <Contador valor={i.valor} casas={1} sufixo="%" />;
  if (i.tipo === "brl") return <Contador valor={i.valor} casas={2} prefixo="R$ " />;
  // Contagens inteiras: dígitos que rolam (Counter do React Bits).
  return <Counter value={Math.round(i.valor)} locale="pt-BR" fontSize="inherit" fontWeight="inherit" textColor="inherit" />;
}

function CartaoIndicador({ i, n }: { i: Indicador; n: number }) {
  const gid = `rl-kpi-${n}`;
  const [claro, forte] = i.cor;
  const subiu = i.variacao != null && i.variacao > 0;
  const bom = i.variacao == null || i.variacao === 0 ? null : i.inverter ? !subiu : subiu;
  return (
    <motion.div variants={ITEM_CASCATA} whileHover={{ y: -4 }} transition={{ type: "spring", stiffness: 300, damping: 22 }} className="rl-kpi-brilho h-full">
    {/* Brilho na borda que segue o cursor (BorderGlow do React Bits), suave e em verde. */}
    <BorderGlow className="h-full" backgroundColor="#ffffff" borderRadius={16} glowColor="140 70 45" glowIntensity={0.6} glowRadius={22}
      coneSpread={20} edgeSensitivity={28} fillOpacity={0.2} colors={["#00bc33", "#34d399", "#a7f3d0"]}>
    <div
      className={cn("rl-kpi group relative h-full overflow-hidden rounded-2xl border bg-white transition-shadow hover:shadow-[0_18px_40px_-18px_var(--rl-sombra)]",
        i.destaque ? "border-transparent ring-2" : "border-white")}
      style={{ background: `linear-gradient(160deg, ${claro}3d 0%, ${claro}14 42%, #ffffff 78%)`, ["--rl-sombra" as string]: `${forte}66`,
               ...(i.destaque ? { ["--tw-ring-color" as string]: `${forte}55` } : {}) }}>
      <span className="absolute inset-x-0 top-0 h-[3px]" style={{ background: `linear-gradient(90deg, ${claro}, ${forte})` }} />
      <div className="relative flex items-start justify-between gap-2 px-5 pb-2 pt-5">
        <div className="flex min-w-0 items-center gap-1.5">
          <span className="text-[11px] font-semibold text-slate-700 md:text-xs">{i.rotulo}</span>
          <Dica texto={i.dica} />
        </div>
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-white transition-transform duration-300 group-hover:rotate-[-6deg] group-hover:scale-110"
          style={{ background: `linear-gradient(135deg, ${claro}, ${forte})`, boxShadow: `0 8px 16px -8px ${forte}` }}>
          <i.icone className="h-[18px] w-[18px]" />
        </div>
      </div>
      <div className="relative px-5">
        <div className="text-3xl font-extrabold leading-none tracking-tight tabular-nums md:text-[34px]" style={{ color: i.corValor ? forte : "#0f172a" }}>
          <ValorIndicador i={i} />
        </div>
        <p className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
          {i.variacao != null && (
            <span className={cn("inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[10px] font-bold",
              bom === null ? "bg-slate-100 text-slate-500" : bom ? "bg-emerald-500/15 text-emerald-700" : "bg-red-500/15 text-red-600")}
              title="Em relação ao período anterior do mesmo tamanho">
              {subiu ? <ArrowUpRight className="h-3 w-3" /> : i.variacao < 0 ? <ArrowDownRight className="h-3 w-3" /> : null}
              {i.variacao > 0 ? "+" : ""}{i.variacao}%
            </span>
          )}
          <span>{i.sub}</span>
        </p>
      </div>
      <div className="relative mt-3 h-[60px] w-full" aria-hidden>
        <svg className="absolute inset-0 h-full w-full" viewBox="0 0 320 80" preserveAspectRatio="none" fill="none">
          <defs>
            <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={forte} stopOpacity="0.42" /><stop offset="100%" stopColor={claro} stopOpacity="0.02" />
            </linearGradient>
          </defs>
          <motion.path d={`${i.curva} L320,80 L0,80 Z`} fill={`url(#${gid})`} initial={{ opacity: 0 }} animate={{ opacity: 1 }}
            transition={{ delay: 0.35 + n * 0.06, duration: 0.8 }} />
          <motion.path d={i.curva} stroke={forte} strokeWidth={2.6} strokeLinecap="round" strokeLinejoin="round" fill="none"
            initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ delay: 0.2 + n * 0.06, duration: 1.1, ease: [0.65, 0, 0.35, 1] }} />
        </svg>
      </div>
    </div>
    </BorderGlow>
    </motion.div>
  );
}

// Etapas: cor viva de cada fase (mesma do funil e do filtro de etapa)
const ESTILO_FASE: Record<string, { ponto: string; claro: string; dica: string; corValor?: boolean }> = {
  sdr: { ponto: "#2563eb", claro: "#60a5fa", dica: "Na fase inicial de qualificação." },
  closer: { ponto: "#0891b2", claro: "#22d3ee", dica: "Qualificados, sendo atendidos pelo closer." },
  analise: { ponto: "#7c3aed", claro: "#a78bfa", dica: "Em análise manual da equipe." },
  contratos: { ponto: "#ea580c", claro: "#fb923c", dica: "Na coleta de dados e confecção do contrato." },
  assinatura: { ponto: "#16a34a", claro: "#4ade80", dica: "Aguardando a assinatura do contrato." },
  assinado: { ponto: "#ca8a04", claro: "#facc15", dica: "Assinaram o contrato.", corValor: true },
  desqualificado: { ponto: "#dc2626", claro: "#f87171", dica: "Não se encaixaram no perfil.", corValor: true },
  nao_assinou: { ponto: "#db2777", claro: "#f472b6", dica: "Tiveram contrato mas não assinaram." },
  outra: { ponto: "#64748b", claro: "#94a3b8", dica: "Em colunas que não são do funil." },
  sem_etapa: { ponto: "#94a3b8", claro: "#cbd5e1", dica: "Ainda sem etapa." },
};
const ORDEM_FASES = ["sdr", "closer", "analise", "contratos", "assinatura", "assinado", "desqualificado", "nao_assinou"];
const NOME_FASE: Record<string, string> = {
  sdr: "SDR", closer: "Closer", analise: "Análise Manual", contratos: "Confecção de Contrato", assinatura: "Aguardando Assinatura",
  assinado: "Contrato Assinado", desqualificado: "Desqualificado", nao_assinou: "Não Assinou", outra: "Outra etapa", sem_etapa: "Sem etapa",
};
const MINI_CURVA = "M2,20 C12,18 20,14 30,10 C38,7 48,5 58,3";

function Etapas({ d }: { d: Dashboard }) {
  // Pelos cards do CRM (como o original); conta sem cards: pelos leads da IA.
  const lista = d.cards ? d.cards.por_fase.map((f) => ({ fase: f.fase, leads: f.total }))
    : d.por_fase.map((f) => ({ fase: f.fase, leads: f.leads }));
  const contagem = new Map(lista.map((f) => [f.fase, f.leads]));
  const fases = [...ORDEM_FASES, ...lista.map((f) => f.fase).filter((f) => !ORDEM_FASES.includes(f) && (contagem.get(f) ?? 0) > 0)];
  const total = d.cards ? d.cards.total : d.kpis.leads;
  const unidade = d.cards ? "cards" : "leads";
  return (
    <Cascata className="grid grid-cols-2 gap-3 sm:grid-cols-4 xl:grid-cols-8" atraso={0.25} passo={0.05}>
      {fases.map((fase) => {
        const s = ESTILO_FASE[fase] ?? ESTILO_FASE.outra;
        const n = contagem.get(fase) ?? 0;
        const gid = `rl-mini-${fase}`;
        return (
          <motion.div key={fase} variants={ITEM_CASCATA} whileHover={{ y: -3 }}
            className="group relative overflow-hidden rounded-xl border border-white bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04),0_8px_20px_-14px_rgba(15,23,42,0.25)] transition-shadow hover:shadow-[0_14px_30px_-16px_var(--rl-sombra)]"
            style={{ background: `linear-gradient(150deg, ${s.claro}33 0%, ${s.claro}10 45%, #fff 85%)`, ["--rl-sombra" as string]: `${s.ponto}77` }}>
            <span className="absolute inset-y-0 left-0 w-[3px]" style={{ background: `linear-gradient(180deg, ${s.claro}, ${s.ponto})` }} />
            <div className="px-4 py-3.5">
              <div className="mb-2.5 flex items-center gap-1.5">
                <span className="relative flex h-2 w-2 shrink-0">
                  <span className="rl-pulso absolute inline-flex h-full w-full rounded-full opacity-60" style={{ backgroundColor: s.ponto }} />
                  <span className="relative h-2 w-2 rounded-full" style={{ backgroundColor: s.ponto }} />
                </span>
                <span className="line-clamp-2 text-[11px] font-semibold leading-tight text-slate-700">{NOME_FASE[fase] ?? fase}</span>
                <Dica texto={`${s.dica} (${unidade})`} tamanho="h-2.5 w-2.5" />
              </div>
              <div className="flex items-end justify-between gap-2">
                <div className="min-w-0">
                  <div className="text-2xl font-extrabold leading-none tracking-tight tabular-nums" style={{ color: s.corValor ? s.ponto : "#0f172a" }}><Contador valor={n} /></div>
                  <p className="mt-1.5 text-[10.5px] font-medium" style={{ color: s.ponto }}>{fmtPct(total ? (n / total) * 100 : 0)} <span className="text-slate-500">do total</span></p>
                </div>
                <svg className="h-6 w-[56px] shrink-0 transition-transform duration-300 group-hover:scale-110" viewBox="0 0 60 24" fill="none" preserveAspectRatio="none" aria-hidden>
                  <defs>
                    <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={s.ponto} stopOpacity="0.45" /><stop offset="100%" stopColor={s.ponto} stopOpacity="0" />
                    </linearGradient>
                  </defs>
                  <path d={`${MINI_CURVA} L58,24 L2,24 Z`} fill={`url(#${gid})`} />
                  <motion.path d={MINI_CURVA} stroke={s.ponto} strokeWidth={2.2} strokeLinecap="round" fill="none"
                    initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ delay: 0.5, duration: 0.8, ease: "easeInOut" }} />
                </svg>
              </div>
            </div>
          </motion.div>
        );
      })}
    </Cascata>
  );
}

// --------------------------------------------------------------------------- melhores anúncios
function MelhoresAnuncios({ anuncios, abrir, de, ate, gerado }: { anuncios: Anuncio[] | null; abrir: (c: string) => void; de: string; ate: string; gerado: string }) {
  const [modo, setModo] = useState<"leads" | "assinados">("leads");
  const [ordem, setOrdem] = useState<"valor" | "conversao">("valor");
  const [todos, setTodos] = useState(false);
  const lista = anuncios ?? [];
  const ordenados = useMemo(() => {
    const l = modo === "assinados" ? lista.filter((a) => a.assinados > 0) : [...lista];
    const val = (a: Anuncio) => a[modo];
    return ordem === "conversao"
      ? l.sort((a, b) => (b.conversao ?? 0) - (a.conversao ?? 0) || val(b) - val(a))
      : l.sort((a, b) => val(b) - val(a) || (b.conversao ?? 0) - (a.conversao ?? 0));
  }, [lista, modo, ordem]);
  const totalLeads = lista.reduce((s, a) => s + a.leads, 0);
  const comLeads = lista.filter((a) => a.leads > 0);
  const metricas = [
    { rotulo: "Total de Leads", valor: totalLeads, casas: 0, sufixo: "", sub: "de anúncios", icone: Users, fundo: "bg-violet-100", cor: "text-violet-600", tint: "from-violet-50/60" },
    { rotulo: "Média por anúncio", valor: lista.length ? totalLeads / lista.length : 0, casas: 1, sufixo: "", sub: "leads", icone: Target, fundo: "bg-emerald-100", cor: "text-emerald-600", tint: "from-emerald-50/60" },
    { rotulo: "Melhor anúncio", valor: Math.max(0, ...lista.map((a) => a.leads)), casas: 0, sufixo: "", sub: "leads", icone: Award, fundo: "bg-blue-100", cor: "text-blue-600", tint: "from-blue-50/60" },
    { rotulo: "Taxa de conversão média", valor: comLeads.length ? comLeads.reduce((s, a) => s + (a.conversao ?? 0), 0) / comLeads.length : 0, casas: 1, sufixo: "%", sub: "em contrato", icone: TrendingUp, fundo: "bg-amber-100", cor: "text-amber-600", tint: "from-amber-50/60" },
  ];
  const visiveis = ordenados.slice(0, 5);
  const maxValor = Math.max(1, ...visiveis.map((a) => a[modo]));
  const maxConv = Math.max(1, ...visiveis.map((a) => a.conversao ?? 0));
  const COLS = "grid-cols-[28px_minmax(160px,1fr)_100px_110px_100px]";
  return (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}
      className={cn(CARTAO, "flex h-full flex-col overflow-hidden p-5 md:p-6")}>
      <div className="mb-5 flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-100 to-purple-200 shadow-sm">
            <Trophy className="h-5 w-5 text-violet-600" />
          </span>
          <div>
            <h3 className="flex items-center gap-1.5 text-lg font-bold tracking-tight text-foreground">Melhores Anúncios
              <Dica texto="Anúncios de clique para WhatsApp e links com UTM que trouxeram os leads do período." tamanho="h-3.5 w-3.5" /></h3>
            <p className="mt-0.5 text-xs text-muted-foreground">Ranking dos anúncios que mais geraram leads</p>
          </div>
        </div>
        <button type="button" onClick={() => exportarAnuncios(ordenados, de, ate)} disabled={!lista.length}
          className="lc-brilho lc-brilho--borda flex items-center gap-1.5 rounded-xl border border-border/60 bg-background px-3.5 py-2 text-sm font-medium text-muted-foreground transition-all hover:-translate-y-0.5 hover:border-border hover:text-foreground disabled:opacity-50 print:hidden">
          <Download className="h-4 w-4" />Exportar
        </button>
      </div>
      <div className="mb-4 grid grid-cols-2 gap-2.5 lg:grid-cols-4">
        {metricas.map((m, i) => (
          <motion.div key={m.rotulo} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.06 }}
            className={cn("group relative overflow-hidden rounded-xl border border-border/50 bg-gradient-to-br to-transparent p-2.5 transition-all hover:-translate-y-0.5 hover:shadow-sm", m.tint)}>
            <div className="flex items-start justify-between gap-2">
              <p className="text-[10px] font-medium leading-tight text-muted-foreground">{m.rotulo}</p>
              <div className={cn("flex h-6 w-6 shrink-0 items-center justify-center rounded-md transition-transform group-hover:scale-110", m.fundo)}>
                <m.icone className={cn("h-3 w-3", m.cor)} />
              </div>
            </div>
            <div className="mt-1 text-lg font-bold leading-tight tabular-nums text-foreground"><Contador valor={m.valor} casas={m.casas} sufixo={m.sufixo} /></div>
            <p className="text-[10px] text-muted-foreground">{m.sub}</p>
          </motion.div>
        ))}
      </div>
      <div className="mb-3 flex items-center justify-between gap-2">
        <Abas valor={modo} aoMudar={(v) => setModo(v)} opcoes={[
          { valor: "leads", rotulo: <><Trophy className="h-3.5 w-3.5" /> Leads</> },
          { valor: "assinados", rotulo: <><Award className="h-3.5 w-3.5" /> Contrato Assinado</> }]} />
      </div>
      <div className="flex-1 overflow-x-auto">
        <div className="min-w-[620px]">
          <div className={cn("grid gap-3 border-b border-border/50 px-3 py-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60", COLS)}>
            <span>#</span><span>Anúncio</span><span>Plataforma</span>
            <button type="button" onClick={() => setOrdem("valor")} title="Ordenar por quantidade"
              className={cn("flex items-center gap-1 uppercase tracking-wider transition-colors", ordem === "valor" ? "text-primary" : "hover:text-foreground")}>
              {modo === "assinados" ? "Contratos" : "Leads"}<ChevronDown className={cn("h-3 w-3", ordem === "valor" ? "opacity-100" : "opacity-30")} />
            </button>
            <button type="button" onClick={() => setOrdem("conversao")} title="Ordenar por conversão"
              className={cn("flex items-center gap-1 uppercase tracking-wider transition-colors", ordem === "conversao" ? "text-primary" : "hover:text-foreground")}>
              Conversão<ChevronDown className={cn("h-3 w-3", ordem === "conversao" ? "opacity-100" : "opacity-30")} />
            </button>
          </div>
          {visiveis.map((a, i) => {
            const p = infoPlataforma(a.plataforma, a.plataforma_nome);
            const valor = a[modo];
            return (
              <motion.button key={a.chave} type="button" initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.05 }}
                onClick={() => abrir(a.chave)}
                className={cn("group grid w-full items-center gap-3 border-b border-border/40 px-3 py-3 text-left transition-all hover:bg-muted/30", COLS,
                  i === 0 && "bg-gradient-to-r from-amber-50/50 to-transparent")}>
                <Posicao i={i} />
                <div className="flex min-w-0 items-center gap-2.5">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-muted/60">{p.icone}</span>
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-foreground" title={a.nome}>{a.nome}</p>
                    <p className="truncate text-[11px] text-muted-foreground" title={a.campanha}>{a.titulo && a.titulo !== a.nome ? a.titulo : a.campanha}</p>
                  </div>
                </div>
                <div className="flex items-center gap-1.5"><span className={cn("h-1.5 w-1.5 rounded-full", p.ponto)} /><span className="truncate text-xs text-muted-foreground">{p.nome}</span></div>
                <div>
                  <span className="text-sm font-bold tabular-nums text-foreground">{fmtNum(valor)}</span>
                  <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-muted/60">
                    <motion.div className="h-full rounded-full bg-gradient-to-r from-violet-400 to-purple-500" initial={{ width: 0 }}
                      animate={{ width: `${Math.round((valor / maxValor) * 100)}%` }} transition={{ delay: i * 0.05 + 0.2, duration: 0.7, ease: "easeOut" }} />
                  </div>
                </div>
                <div>
                  <span className="flex items-center gap-0.5 text-sm font-bold tabular-nums text-emerald-600">
                    {fmtPct(a.conversao ?? 0)}{(a.conversao ?? 0) > 0 && <TrendingUp className="h-3 w-3" />}
                  </span>
                  <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-muted/60">
                    <motion.div className="h-full rounded-full bg-gradient-to-r from-emerald-400 to-green-500" initial={{ width: 0 }}
                      animate={{ width: `${Math.round(((a.conversao ?? 0) / maxConv) * 100)}%` }} transition={{ delay: i * 0.05 + 0.3, duration: 0.7, ease: "easeOut" }} />
                  </div>
                </div>
              </motion.button>
            );
          })}
          {!ordenados.length && (
            <Vazio icone={<Megaphone className="h-7 w-7" />}>{anuncios == null ? "Carregando os anúncios…"
              : modo === "assinados" ? "Nenhum anúncio trouxe contrato assinado no período" : "Nenhum anúncio encontrado"}</Vazio>
          )}
        </div>
      </div>
      {ordenados.length > 5 && (
        <button type="button" onClick={() => setTodos(true)}
          className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-xl border border-border/50 bg-muted/30 py-2.5 text-sm font-medium text-muted-foreground transition-all hover:bg-muted/50 hover:text-foreground print:hidden">
          Ver mais {ordenados.length - 5} anúncios<ChevronDown className="h-4 w-4" />
        </button>
      )}
      <div className="mt-4 flex items-center gap-1.5 text-[11px] text-muted-foreground/70">
        <span className="flex h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
        <Clock className="h-3 w-3" />Dados atualizados às {new Date(gerado).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}
        <Link to="/relatorios/campanhas" className="ml-auto font-medium text-primary hover:underline print:hidden">Ver campanhas →</Link>
      </div>
      <ModalTodosAnuncios aberto={todos} aoFechar={() => setTodos(false)} anuncios={ordenados} abrir={abrir} titulo="Todos os Anúncios"
        ordem={modo === "leads" ? "leads" : "contratos"} />
    </motion.div>
  );
}

// --------------------------------------------------------------------------- tempo até assinar
const CORES_FAIXA = ["#15803d", "#16a34a", "#22c55e", "#4ade80", "#bbf7d0"];

function TempoAteAssinar({ d }: { d: Dashboard }) {
  const t = d.tempo_ate_assinar;
  const n = t.faixas.reduce((s, f) => s + f.total, 0);
  const dias = t.media_horas != null ? t.media_horas / 24 : 0;
  // curva decorativa: contratos assinados por semana no período
  const semanas: number[] = [];
  d.serie.forEach((p, i) => { const w = Math.floor(i / 7); semanas[w] = (semanas[w] ?? 0) + p.assinados; });
  const area = useMemo(() => {
    const vals = semanas.length > 1 ? semanas : [0, ...(semanas.length ? semanas : [0])];
    const w = 240, h = 96, max = Math.max(...vals, 1), passo = w / (vals.length - 1);
    const pts = vals.map((v, i) => [i * passo, h - (v / max) * (h - 12) - 6]);
    const linha = pts.map((p, i) => `${i === 0 ? "M" : "L"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
    return { linha, fill: `${linha} L${w},${h} L0,${h} Z`, pts, w, h };
  }, [semanas.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className={cn(CARTAO, "flex h-full flex-col overflow-hidden p-5 md:p-6")}>
      <div className="pointer-events-none absolute -right-10 -top-10 h-32 w-32 rounded-full bg-emerald-500/10 blur-3xl" />
      <div className="relative">
        <div className="mb-0.5 flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-100"><Clock className="h-4 w-4 text-emerald-600" /></span>
          <h3 className="text-sm font-semibold text-foreground">Tempo Médio até Fechamento</h3>
          <Dica texto="Média de tempo entre a entrada do lead e a assinatura do contrato (leads que entraram no período)." />
        </div>
        <p className="-mt-0.5 mb-4 ml-10 text-[11px] text-muted-foreground">Quanto tempo leva da entrada até o contrato</p>
      </div>
      <div className="relative flex items-start justify-between gap-4">
        <div>
          <div className="flex items-end gap-1.5">
            <span className="text-5xl font-bold leading-none tracking-tight text-emerald-600">{t.media_horas != null ? <Contador valor={dias} casas={1} duracao={1100} /> : "–"}</span>
            <span className="mb-1 text-base text-muted-foreground">dias</span>
          </div>
          <p className="mt-2 flex items-center gap-1 text-xs font-medium text-muted-foreground">
            <Timer className="h-3.5 w-3.5" />Mediana: <b className="text-foreground">{fmtHoras(t.mediana_horas)}</b>
          </p>
        </div>
        <svg viewBox={`0 0 ${area.w} ${area.h}`} className="h-24 w-44 shrink-0" preserveAspectRatio="none" aria-label="Contratos assinados por semana" role="img">
          <defs>
            <linearGradient id="rl-tempo-area" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#22c55e" stopOpacity="0.28" /><stop offset="100%" stopColor="#22c55e" stopOpacity="0" />
            </linearGradient>
          </defs>
          <path d={area.fill} fill="url(#rl-tempo-area)" />
          <motion.path d={area.linha} fill="none" stroke="#22c55e" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round"
            initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 1.2, ease: "easeOut" }} />
          {area.pts.map((p, i) => <circle key={i} cx={p[0]} cy={p[1]} r={1.8} fill="#16a34a" />)}
        </svg>
      </div>
      <div className="relative mt-3 flex items-center gap-3">
        <span className="inline-flex items-center gap-1.5 rounded-lg border border-border/60 bg-muted/40 px-3 py-1.5 text-sm font-semibold text-foreground">
          <Clock className="h-3.5 w-3.5 text-muted-foreground" />{t.media_horas != null ? `${t.media_horas.toLocaleString("pt-BR", { maximumFractionDigits: 1 })} horas` : "–"}
        </span>
        <span className="text-[11px] text-muted-foreground">Baseado em {fmtNum(n)} contrato{n !== 1 ? "s" : ""} assinado{n !== 1 ? "s" : ""}</span>
      </div>
      <div className="relative mt-5 flex flex-1 flex-col rounded-xl border border-border/50 bg-muted/20 p-4">
        <p className="mb-3 flex items-center gap-1.5 text-xs font-semibold text-foreground">Distribuição do tempo até fechamento
          <Dica texto="Quantos contratos foram assinados em cada faixa de tempo." /></p>
        {!n ? <p className="py-6 text-center text-xs text-muted-foreground">Sem contratos assinados entre os leads do período.</p> : (
          <RoscaTotal className="flex-1" tamanho={160} espessura={18} legenda rotuloTotal={n === 1 ? "contrato" : "contratos"}
            fatias={t.faixas.map((f, i) => ({ rotulo: f.faixa, valor: f.total, cor: CORES_FAIXA[i] }))} />
        )}
      </div>
      <div className="mt-4">
        <Insight>{n ? <>Metade dos contratos é assinada em até <strong className="text-foreground">{fmtHoras(t.mediana_horas)}</strong> depois que o lead chega.
          {t.media_horas != null && t.mediana_horas != null && t.media_horas > t.mediana_horas * 1.5 ? " Alguns contratos demoram bem mais e puxam a média para cima." : ""}</>
          : "Assim que houver contratos assinados, mostramos a análise de tempo aqui."}</Insight>
      </div>
    </motion.div>
  );
}

// --------------------------------------------------------------------------- atendimento da IA (no lugar da "Meta de Vendas")
function AtendimentoIA({ d }: { d: Dashboard }) {
  const ia = d.ia, k = d.kpis;
  const pct = ia.turnos ? (ia.respondidos / ia.turnos) * 100 : 0;
  const cor = (ia.taxa_erro ?? 0) > 5 ? "#ef4444" : (ia.taxa_erro ?? 0) > 1 ? "#f59e0b" : "#16a34a";
  const metricas = [
    { rotulo: "Sem resposta (de propósito)", valor: ia.sem_resposta, sub: "a IA decidiu esperar", icone: Moon, cor: "text-blue-600", fundo: "bg-blue-100" },
    { rotulo: "Com erro", valor: ia.erros, sub: `${fmtPct(ia.taxa_erro ?? 0)} dos atendimentos`, icone: AlertTriangle, cor: "text-red-600", fundo: "bg-red-100" },
    { rotulo: "Trocas de etapa", valor: ia.trocas, sub: "feitas pela IA", icone: Repeat, cor: "text-violet-600", fundo: "bg-violet-100" },
    { rotulo: "Mensagens da equipe", valor: k.mensagens_equipe, sub: `${fmtNum(k.mensagens_lead)} dos leads`, icone: MessageSquare, cor: "text-amber-600", fundo: "bg-amber-100" },
  ];
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className={cn(CARTAO, "flex h-full flex-col overflow-hidden p-5 md:p-6")}>
      <div className="pointer-events-none absolute -left-10 -top-10 h-32 w-32 rounded-full bg-emerald-500/10 blur-3xl" />
      <div className="relative flex items-start gap-2">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-100"><Bot className="h-4 w-4 text-emerald-600" /></span>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-foreground">Atendimento da IA</h3>
            <Dica texto="Cada vez que a IA processou mensagens de um lead no período: respondeu, esperou de propósito ou deu erro." />
          </div>
          <p className="text-[11px] text-muted-foreground">Respostas, tempo e custo da IA no período</p>
        </div>
      </div>
      <div className="relative mt-4 flex items-end justify-between gap-3">
        <div>
          <span className="text-4xl font-extrabold leading-none tracking-tight text-foreground"><Contador valor={ia.turnos} /></span>
          <p className="mt-1 text-xs text-muted-foreground">atendimentos da IA</p>
        </div>
        <div className="text-right">
          <p className="text-sm text-muted-foreground">{fmtNum(ia.respondidos)} com resposta</p>
          <span className="mt-1 inline-block rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-semibold text-emerald-700">
            {fmtPct(pct, 0)} respondidos
          </span>
        </div>
      </div>
      <div className="relative mt-5">
        <div className="relative h-2.5 w-full overflow-visible rounded-full bg-secondary">
          <motion.div className="absolute left-0 top-0 h-full rounded-full" style={{ backgroundColor: cor }}
            initial={{ width: 0 }} animate={{ width: `${Math.min(100, pct)}%` }} transition={{ duration: 1, ease: "easeOut" }} />
        </div>
        <div className="mt-1.5 flex justify-between text-[10px] tabular-nums text-muted-foreground">
          <span>Mediana para responder: <b className="text-foreground">{fmtSegundos(ia.duracao_mediana_s)}</b></span>
          <span>Tempo médio para responder: <b className="text-foreground">{fmtSegundos(ia.duracao_media_s)}</b></span>
        </div>
      </div>
      <div className="relative mt-5 grid grid-cols-2 gap-2.5 lg:grid-cols-4">
        {metricas.map((m, i) => (
          <motion.div key={m.rotulo} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 + i * 0.07 }}
            className="rounded-xl border border-border/50 bg-muted/20 p-3">
            <div className="mb-1.5 flex items-center gap-1.5">
              <span className={cn("flex h-6 w-6 items-center justify-center rounded-md", m.fundo)}><m.icone className={cn("h-3 w-3", m.cor)} /></span>
              <span className="text-[10px] leading-tight text-muted-foreground">{m.rotulo}</span>
            </div>
            <p className="text-xl font-bold leading-none tabular-nums text-foreground"><Contador valor={m.valor} duracao={900} /></p>
            <p className="mt-1 text-[10px] text-muted-foreground">{m.sub}</p>
          </motion.div>
        ))}
      </div>
      <div className="relative mt-5 flex-1 rounded-xl border border-border/50 bg-muted/20 p-4">
        <p className="text-xs font-semibold text-foreground">Atendimentos por dia</p>
        <BarrasTendencia altura={170} rotuloAria="Atendimentos da IA por dia, respondidos e com erro, com a linha de tendência"
          camadas={[{ rotulo: "Respondidos", cor: "#00bc33" }, { rotulo: "Com erro", cor: "#ef4444" }]}
          dados={d.serie.map((s) => ({ rotulo: curta(s.dia), rotuloLongo: longa(s.dia), valores: [s.turnos, s.erros] }))} />
      </div>
      <div className="mt-4">
        <Insight icone={<CircleDollarSign className="h-3.5 w-3.5 text-emerald-600" />}>
          A IA custou <strong className="text-foreground">{fmtBRL(k.custo_brl)}</strong> no período
          {k.custo_por_lead != null && <> (<strong className="text-foreground">{fmtBRL(k.custo_por_lead)}</strong> por lead</>}
          {k.custo_por_contrato != null && <>, {fmtBRL(k.custo_por_contrato)} por contrato</>}{k.custo_por_lead != null && ")"}, em {fmtNum(k.chamadas_ia)} chamadas.
        </Insight>
      </div>
    </motion.div>
  );
}

// --------------------------------------------------------------------------- evolução por dia
type SerieChave = "cards" | "leads" | "assinados" | "custo_brl";
const SERIES: { valor: SerieChave; rotulo: string; unidade: string; cor: string }[] = [
  { valor: "cards", rotulo: "Cards no CRM", unidade: "cards", cor: "#2563eb" },
  { valor: "leads", rotulo: "Novos leads", unidade: "leads", cor: "#15BF41" },
  { valor: "assinados", rotulo: "Contratos", unidade: "contratos", cor: "#8b5cf6" },
  { valor: "custo_brl", rotulo: "Custo da IA", unidade: "", cor: "#f59e0b" },
];
const FAIXAS = [{ valor: "7", rotulo: "7 dias" }, { valor: "30", rotulo: "30 dias" }, { valor: "90", rotulo: "90 dias" }, { valor: "tudo", rotulo: "Tudo" }] as const;
type Faixa = (typeof FAIXAS)[number]["valor"];
const PERIODOS_DIA = [
  { nome: "Manhã", de: 6, ate: 12, icone: Sun, cor: "#f59e0b" }, { nome: "Tarde", de: 12, ate: 18, icone: Sunset, cor: "#22c55e" },
  { nome: "Noite", de: 18, ate: 24, icone: Moon, cor: "#6366f1" }, { nome: "Madrugada", de: 0, ate: 6, icone: Clock, cor: "#94a3b8" },
];
const curta = (dia: string) => `${dia.slice(8, 10)}/${dia.slice(5, 7)}`;
const longa = (dia: string) => fmtData(dia + "T12:00:00");

function Evolucao({ d }: { d: Dashboard }) {
  const [faixa, setFaixa] = useState<Faixa>("tudo");
  const [tipo, setTipo] = useState<"area" | "linha">("area");
  const [chave, setChave] = useState<SerieChave>(d.cards ? "cards" : "leads");
  const series = d.cards ? SERIES : SERIES.filter((x) => x.valor !== "cards");
  const [periodoAtivo, setPeriodoAtivo] = useState<number | null>(null);
  const conf = series.find((s) => s.valor === chave) ?? series[0];
  const brl = chave === "custo_brl";
  const fmtV = (v: number) => (brl ? fmtBRL(v) : fmtNum(v));
  const k = d.kpis;

  const dados = useMemo(() => {
    const tudo = d.serie.map((p) => ({ t: p.dia, v: Number(p[chave]) || 0 }));
    const n = faixa === "tudo" ? tudo.length : Math.min(tudo.length, Number(faixa));
    const pontos = tudo.slice(-n);
    const total = pontos.reduce((s, p) => s + p.v, 0);
    const porDia = n ? total / n : 0;
    const melhor = pontos.reduce<{ t: string; v: number } | null>((m, p) => (!m || p.v > m.v ? p : m), null);
    const ma = pontos.map((_, i) => { const fatia = pontos.slice(Math.max(0, i - 6), i + 1); return fatia.reduce((s, p) => s + p.v, 0) / fatia.length; });
    const terco = Math.max(1, Math.floor(pontos.length / 3));
    const ini = pontos.slice(0, terco).reduce((s, p) => s + p.v, 0) / terco;
    const fim = pontos.slice(-terco).reduce((s, p) => s + p.v, 0) / terco;
    const tendencia = ini > 0 ? ((fim - ini) / ini) * 100 : 0;
    let anterior: number | null = null;
    if (faixa !== "tudo" && tudo.length >= 2 * n) anterior = tudo.slice(-2 * n, -n).reduce((s, p) => s + p.v, 0);
    else if (faixa === "tudo" || n === tudo.length) {
      const varia = chave === "cards" ? d.cards?.total_variacao ?? null : chave === "leads" ? k.leads_variacao : chave === "assinados" ? k.assinados_variacao : chave === "custo_brl" ? k.custo_variacao : null;
      if (varia != null && varia > -100) anterior = total / (1 + varia / 100);
    }
    const crescimento = anterior ? ((total - anterior) / anterior) * 100 : null;
    const top = [...pontos].sort((a, b) => b.v - a.v).slice(0, 5).filter((p) => p.v > 0);
    return { pontos, total, porDia, melhor, ma, tendencia, anterior, crescimento, top, n, previsao: fim * 7 };
  }, [d.serie, d.cards, chave, faixa, k]);


  const horas = Array.from({ length: 24 }, (_, h) => ({ h, v: d.horarios.leads.reduce((s, linha) => s + (linha[h] ?? 0), 0) }));
  const partes = PERIODOS_DIA.map((p) => ({ ...p, n: horas.filter((x) => x.h >= p.de && x.h < p.ate).reduce((s, x) => s + x.v, 0) }));
  const totPartes = partes.reduce((s, p) => s + p.n, 0) || 1;
  const maxHora = Math.max(1, ...horas.map((h) => h.v));
  const picoHora = [...horas].sort((a, b) => b.v - a.v)[0];
  const topParte = [...partes].sort((a, b) => b.n - a.n)[0];
  const subindo = dados.tendencia >= 0;
  const cresceu = (dados.crescimento ?? 0) >= 0;

  const kpis = [
    { rotulo: `Total de ${conf.unidade || "custo"}`, valor: dados.total, casas: brl ? 2 : 0, prefixo: brl ? "R$ " : "", sufixo: "", sub: `nos últimos ${dados.n} dias`, icone: MessageSquare, cor: "text-primary", brilho: "rgba(21,191,65,0.12)" },
    { rotulo: "Média por dia", valor: Math.round(dados.porDia * 100) / 100, casas: brl ? 2 : 1, prefixo: brl ? "R$ " : "", sufixo: "", sub: brl ? "por dia" : `${conf.unidade}/dia`, icone: CalendarDays, cor: "text-blue-500", brilho: "rgba(59,130,246,0.12)" },
    { rotulo: "Pico de volume", valor: dados.melhor?.v ?? 0, casas: brl ? 2 : 0, prefixo: brl ? "R$ " : "", sufixo: "", sub: dados.melhor ? curta(dados.melhor.t) : "—", icone: Flame, cor: "text-orange-500", brilho: "rgba(249,115,22,0.12)" },
    { rotulo: "Tendência", valor: Math.abs(Math.round(dados.tendencia)), casas: 0, prefixo: subindo ? "↑ " : "↓ ", sufixo: "%", sub: subindo ? "crescendo" : "caindo", icone: subindo ? TrendingUp : TrendingDown, cor: subindo ? "text-emerald-500" : "text-red-500", brilho: subindo ? "rgba(16,185,129,0.12)" : "rgba(239,68,68,0.12)" },
  ];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-primary/20 bg-gradient-to-br from-primary/15 to-primary/5">
            <Activity className="h-5 w-5 text-primary" />
          </div>
          <div>
            <h2 className="text-xl font-bold tracking-tight text-foreground">Evolução por dia</h2>
            <p className="text-sm text-muted-foreground">Comportamento, tendências e sazonalidade no período</p>
          </div>
        </div>
        <div className="print:hidden"><AbasGooey valor={faixa} aoMudar={setFaixa} opcoes={FAIXAS.map((f) => ({ valor: f.valor, rotulo: f.rotulo }))} /></div>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {kpis.map((c, i) => (
          <motion.div key={`${chave}-${faixa}-${c.rotulo}`} initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.06, duration: 0.5, ease: [0.16, 1, 0.3, 1] }} whileHover={{ y: -3 }} className={cn(CARTAO, "overflow-hidden p-4")}>
            <div className="absolute -right-8 -top-8 h-24 w-24 rounded-full blur-2xl" style={{ background: c.brilho }} />
            <div className="relative">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-[11px] font-medium text-muted-foreground">{c.rotulo}</span>
                <div className={cn("flex h-7 w-7 items-center justify-center rounded-lg bg-muted/60", c.cor)}><c.icone className="h-3.5 w-3.5" /></div>
              </div>
              <p className={cn("text-2xl font-bold tracking-tight", c.cor)}><Contador valor={c.valor} casas={c.casas} prefixo={c.prefixo} sufixo={c.sufixo} /></p>
              <p className="mt-0.5 text-[10px] text-muted-foreground/70">{c.sub}</p>
            </div>
          </motion.div>
        ))}
      </div>

      <div className={cn(CARTAO, "overflow-hidden p-5")}>
        <div className="pointer-events-none absolute -top-16 left-1/3 h-40 w-80 rounded-full bg-primary/5 blur-3xl" />
        <div className="relative mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground"><Activity className="h-4 w-4 text-primary" /> Evolução de {conf.rotulo.toLowerCase()}</h3>
            <p className="text-[11px] text-muted-foreground">Por dia · linha tracejada = média móvel de 7 dias</p>
          </div>
          <div className="flex flex-wrap items-center gap-2 print:hidden">
            {/* Abas com pílula "gosmenta" (GooeyNav do React Bits). */}
            <AbasGooey valor={chave} aoMudar={setChave} opcoes={series.map((s) => ({ valor: s.valor, rotulo: s.rotulo }))} />
            <Abas valor={tipo} aoMudar={setTipo} opcoes={[
              { valor: "linha", rotulo: <><IconeLinha className="h-3.5 w-3.5" /> Linha</> }, { valor: "area", rotulo: <><IconeArea className="h-3.5 w-3.5" /> Área</> }]} />
          </div>
        </div>
        {!dados.total ? <Vazio>Sem {conf.unidade || "custo"} no período selecionado.</Vazio> : (
          <AreaCruz key={`${chave}-${faixa}`} tipo={tipo} cor={conf.cor} altura={300} media={dados.ma} unidade={brl ? undefined : conf.unidade}
            formatar={fmtV} formatarEixo={(v) => (brl ? `R$${v.toFixed(v < 10 ? 2 : 0)}` : String(Math.round(v)))}
            dados={dados.pontos.map((x) => ({ rotulo: curta(x.t), rotuloLongo: longa(x.t), valor: x.v }))}
            rotuloAria={`Evolução de ${conf.rotulo.toLowerCase()} por dia. Use as setas para ver cada dia.`}
            extraBalao={(i) => {
              const v = dados.pontos[i]?.v ?? 0, m = dados.ma[i] ?? 0;
              return <span className={v >= m ? "text-emerald-600" : "text-red-500"}>{v >= m ? "↑" : "↓"} {m > 0 ? Math.abs(Math.round(((v - m) / m) * 100)) : 0}% vs média</span>;
            }} />
        )}
        {dados.total > 0 && (
          <div className="relative mt-4">
            <Insight tom="primaria">
              {subindo
                ? <>Tendência de <strong className="text-emerald-600">alta de {Math.abs(Math.round(dados.tendencia))}%</strong> em {conf.rotulo.toLowerCase()} no período. Pico de <strong className="text-foreground">{fmtV(dados.melhor?.v ?? 0)}</strong> em {dados.melhor ? curta(dados.melhor.t) : "—"}.</>
                : <>Queda de <strong className="text-red-500">{Math.abs(Math.round(dados.tendencia))}%</strong> em {conf.rotulo.toLowerCase()} no fim do período. Vale revisar as campanhas e o atendimento.</>}
            </Insight>
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className={cn(CARTAO, "p-5")}>
          <h3 className="mb-4 flex items-center gap-2 text-sm font-semibold text-foreground"><Sun className="h-4 w-4 text-amber-500" /> Novos leads por período do dia</h3>
          <div className="flex flex-wrap items-center gap-5">
            <RoscaTotal tamanho={160} espessura={18} rotuloTotal="leads" ativo={periodoAtivo} aoMudarAtivo={setPeriodoAtivo}
              fatias={partes.map((x) => ({ rotulo: x.nome, valor: x.n, cor: x.cor }))} />
            <div className="min-w-[150px] flex-1 space-y-1">
              {partes.map((x, i) => (
                <div key={x.nome} onMouseEnter={() => setPeriodoAtivo(i)} onMouseLeave={() => setPeriodoAtivo(null)}
                  className={cn("flex items-center gap-2.5 rounded-lg px-1.5 py-0.5 transition-colors", periodoAtivo === i && "bg-[#e3f7e8]/70")}>
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg" style={{ background: `${x.cor}1f` }}><x.icone className="h-3.5 w-3.5" style={{ color: x.cor }} /></span>
                  <span className="flex-1 text-xs text-foreground">{x.nome}</span>
                  <span className="text-xs font-semibold tabular-nums text-foreground">{fmtNum(x.n)}</span>
                  <span className="w-10 text-right text-[10px] tabular-nums text-muted-foreground">{fmtPct((x.n / totPartes) * 100)}</span>
                </div>
              ))}
            </div>
          </div>
          {topParte.n > 0 && (
            <div className="mt-4 flex items-start gap-2 rounded-xl border border-border/50 bg-muted/20 p-3">
              <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
              <p className="text-[11px] leading-relaxed text-muted-foreground">O período da <strong className="text-foreground">{topParte.nome.toLowerCase()}</strong> concentra <strong className="text-foreground">{Math.round((topParte.n / totPartes) * 100)}%</strong> dos novos leads.</p>
            </div>
          )}
        </div>
        <div className={cn(CARTAO, "p-5")}>
          <h3 className="mb-4 flex items-center gap-2 text-sm font-semibold text-foreground"><Clock className="h-4 w-4 text-primary" /> Intensidade por horário</h3>
          <div className="grid grid-cols-12 gap-1.5">
            {horas.map((h, i) => {
              const int = h.v / maxHora;
              return (
                <motion.div key={h.h} initial={{ opacity: 0, scale: 0.6 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: i * 0.012 }}
                  className="relative flex aspect-square items-center justify-center rounded-md" title={`${String(h.h).padStart(2, "0")}h · ${h.v} leads`}
                  style={{ background: int > 0 ? `rgba(21,191,65,${0.12 + int * 0.78})` : "hsl(var(--muted))" }}>
                  <span className={cn("text-[8px] font-medium", int > 0.5 ? "text-white" : "text-muted-foreground")}>{h.h}</span>
                </motion.div>
              );
            })}
          </div>
          <div className="mt-3 flex items-center justify-between text-[10px] text-muted-foreground"><span>00h</span><span>06h</span><span>12h</span><span>18h</span><span>23h</span></div>
          {picoHora.v > 0 && (
            <div className="mt-4 flex items-start gap-2 rounded-xl border border-border/50 bg-muted/20 p-3">
              <Flame className="mt-0.5 h-3.5 w-3.5 shrink-0 text-orange-500" />
              <p className="text-[11px] leading-relaxed text-muted-foreground">Pico de chegada às <strong className="text-foreground">{String(picoHora.h).padStart(2, "0")}h</strong> ({fmtNum(picoHora.v)} leads). Concentre a equipe nesse horário.</p>
            </div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className={cn(CARTAO, "p-5")}>
          <h3 className="mb-4 flex items-center gap-2 text-sm font-semibold text-foreground"><TrendingUp className="h-4 w-4 text-primary" /> Comparativo com período anterior</h3>
          <div className="mb-4 flex items-end gap-6">
            <div><p className="text-[11px] text-muted-foreground">Período atual</p><p className="text-3xl font-bold leading-none text-foreground">{fmtV(dados.total)}</p></div>
            <div><p className="text-[11px] text-muted-foreground">Anterior</p><p className="text-2xl font-bold leading-none text-muted-foreground/70">{dados.anterior != null ? fmtV(dados.anterior) : "–"}</p></div>
            {dados.crescimento != null && (
              <div className={cn("ml-auto flex items-center gap-1 rounded-lg px-2.5 py-1 text-sm font-semibold", cresceu ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-600")}>
                {cresceu ? <ArrowUpRight className="h-4 w-4" /> : <ArrowDownRight className="h-4 w-4" />}{Math.abs(Math.round(dados.crescimento))}%
              </div>
            )}
          </div>
          {(() => {
            const mx = Math.max(dados.total, dados.anterior ?? 0, 1);
            return (
              <div className="space-y-2.5">
                <div>
                  <div className="mb-1 flex justify-between text-[11px]"><span className="text-muted-foreground">Atual</span><span className="font-semibold text-foreground">{fmtV(dados.total)}</span></div>
                  <div className="h-2.5 overflow-hidden rounded-full bg-secondary"><motion.div className="h-full rounded-full bg-gradient-to-r from-primary/80 to-primary" initial={{ width: 0 }} animate={{ width: `${(dados.total / mx) * 100}%` }} transition={{ duration: 1, ease: "easeOut" }} /></div>
                </div>
                <div>
                  <div className="mb-1 flex justify-between text-[11px]"><span className="text-muted-foreground">Anterior</span><span className="font-semibold text-muted-foreground">{dados.anterior != null ? fmtV(dados.anterior) : "–"}</span></div>
                  <div className="h-2.5 overflow-hidden rounded-full bg-secondary"><motion.div className="h-full rounded-full bg-muted-foreground/40" initial={{ width: 0 }} animate={{ width: `${((dados.anterior ?? 0) / mx) * 100}%` }} transition={{ duration: 1, delay: 0.15, ease: "easeOut" }} /></div>
                </div>
              </div>
            );
          })()}
          <div className="mt-4 flex items-start gap-2 rounded-xl border border-border/50 bg-muted/20 p-3">
            <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
            <p className="text-[11px] leading-relaxed text-muted-foreground">
              {dados.crescimento == null ? "Sem dados do período anterior para comparar."
                : cresceu ? <>Subiu <strong className="text-emerald-600">{Math.abs(Math.round(dados.crescimento))}%</strong> em relação ao período anterior do mesmo tamanho. No ritmo dos últimos dias: <strong className="text-foreground">~{fmtV(dados.previsao)}</strong> por semana.</>
                : <>Queda de <strong className="text-red-500">{Math.abs(Math.round(dados.crescimento))}%</strong> em relação ao período anterior. No ritmo dos últimos dias: <strong className="text-foreground">~{fmtV(dados.previsao)}</strong> por semana.</>}
            </p>
          </div>
        </div>
        <div className={cn(CARTAO, "p-5")}>
          <h3 className="mb-4 flex items-center gap-2 text-sm font-semibold text-foreground"><Flame className="h-4 w-4 text-orange-500" /> Top {dados.top.length} dias de maior volume</h3>
          {!dados.top.length ? <Vazio>Sem dias com movimento.</Vazio> : (
            <div className="space-y-2.5">
              {dados.top.map((x, i) => {
                const medalha = ["bg-amber-400 text-amber-950", "bg-slate-300 text-slate-800", "bg-orange-400 text-orange-950", "bg-muted text-muted-foreground", "bg-muted text-muted-foreground"][i];
                return (
                  <motion.div key={x.t} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.08 }}
                    className="group flex items-center gap-3 rounded-xl border border-border/50 bg-muted/10 p-2.5 transition-colors hover:bg-muted/30">
                    <span className={cn("flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold", medalha)}>{i + 1}</span>
                    <div className="min-w-0 flex-1">
                      <div className="mb-1 flex items-center justify-between">
                        <span className="text-xs font-medium text-foreground">{longa(x.t)}</span>
                        <span className="text-sm font-bold tabular-nums text-foreground">{fmtV(x.v)}</span>
                      </div>
                      <div className="h-1.5 overflow-hidden rounded-full bg-secondary">
                        <motion.div className="h-full rounded-full bg-gradient-to-r from-primary/70 to-primary" initial={{ width: 0 }} animate={{ width: `${(x.v / (dados.top[0]?.v || 1)) * 100}%` }} transition={{ duration: 0.8, delay: 0.1 + i * 0.08 }} />
                      </div>
                    </div>
                    <span className="w-10 text-right text-[10px] tabular-nums text-muted-foreground">{fmtPct(dados.total ? (x.v / dados.total) * 100 : 0)}</span>
                  </motion.div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- origem dos leads
const COR_PLATAFORMA: Record<string, string> = {
  instagram: "hsl(330, 80%, 55%)", facebook: "hsl(217, 91%, 60%)", google: "hsl(43, 96%, 50%)", youtube: "hsl(0, 80%, 55%)",
  tiktok: "hsl(215, 25%, 27%)", outro: "hsl(187, 72%, 45%)", direto: "hsl(220, 10%, 75%)",
};

function OrigemLeads({ d }: { d: Dashboard }) {
  const [origemAtiva, setOrigemAtiva] = useState<number | null>(null);
  const dados = d.plataformas.map((p) => ({ ...p, cor: COR_PLATAFORMA[p.plataforma] ?? "hsl(220, 10%, 70%)" }));
  const total = dados.reduce((s, p) => s + p.leads, 0);
  const topo = [...dados].filter((p) => p.plataforma !== "direto").sort((a, b) => b.leads - a.leads)[0] ?? dados[0];
  return (
    <div className={cn(CARTAO, "flex h-full flex-col p-6")}>
      <div className="mb-1 flex items-center gap-2">
        <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-violet-100"><IconePizza className="h-4 w-4 text-violet-600" /></span>
        <h3 className="text-base font-bold tracking-tight text-foreground">Origem dos Leads</h3>
      </div>
      <p className="-mt-1 mb-5 ml-11 text-[11px] text-muted-foreground">De onde seus leads estão vindo (anúncio ou UTM do primeiro contato)</p>
      {!total ? <Vazio>Sem leads no período.</Vazio> : (
        <div className="flex min-h-0 flex-1 flex-col justify-center gap-5">
          <div className="flex flex-col items-center gap-6 md:flex-row">
            <RoscaTotal tamanho={224} espessura={26} rotuloTotal="leads" ativo={origemAtiva} aoMudarAtivo={setOrigemAtiva}
              fatias={dados.map((p) => ({ chave: p.plataforma, rotulo: p.nome, valor: p.leads, cor: p.cor }))} />
            <div className="w-full flex-1 space-y-2">
              {dados.map((p, i) => {
                const pct = total ? (p.leads / total) * 100 : 0;
                return (
                  <div key={p.plataforma} onMouseEnter={() => setOrigemAtiva(i)} onMouseLeave={() => setOrigemAtiva(null)}
                    className={cn("group rounded-lg px-1.5 py-1 transition-colors", origemAtiva === i && "bg-[#e3f7e8]/60")}>
                    <div className="mb-1.5 flex items-center gap-3">
                      <div className="h-3 w-3 flex-shrink-0 rounded-full transition-transform group-hover:scale-125" style={{ backgroundColor: p.cor, boxShadow: `0 0 8px ${p.cor}` }} />
                      <span className="flex-1 text-sm text-foreground">{p.nome}<span className="ml-1.5 text-[11px] text-muted-foreground">{fmtNum(p.assinados)} contr.</span></span>
                      <span className="text-lg font-bold tabular-nums text-foreground"><Contador valor={p.leads} duracao={900} /></span>
                      <span className="w-12 text-right text-xs tabular-nums text-muted-foreground">{fmtPct(pct)}</span>
                    </div>
                    <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted/50">
                      <motion.div className="h-full rounded-full" style={{ background: p.cor }} initial={{ width: 0 }} animate={{ width: `${pct}%` }}
                        transition={{ delay: 0.3 + i * 0.12, duration: 0.9, ease: "easeOut" }} />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
          {topo && (
            <Insight tom="violeta">
              <span className="mb-0.5 block text-xs font-semibold text-foreground">Insights</span>
              <strong className="text-foreground">{topo.nome}</strong> é a principal origem de leads, responsável por <strong className="text-foreground">{fmtPct(total ? (topo.leads / total) * 100 : 0)}</strong> do total no período.{" "}
              <Link to="/relatorios/campanhas" className="font-medium text-violet-600 hover:underline print:hidden">Ver o rastreamento de campanhas →</Link>
            </Insight>
          )}
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- agentes, leads por etapa, CRM
function Agentes({ d }: { d: Dashboard }) {
  const max = Math.max(1, ...d.agentes.map((a) => a.leads));
  const melhor = d.agentes.reduce<string | null>((m, a) => (a.leads >= 3 && (!m || (a.conversao ?? 0) > (d.agentes.find((x) => x.nome === m)?.conversao ?? 0)) ? a.nome : m), null);
  return (
    <div className={cn(CARTAO, "p-5")}>
      <div className="mb-1 flex items-center gap-2"><Bot className="h-4 w-4 text-primary" /><h3 className="text-sm font-semibold text-foreground">Desempenho por Agente</h3></div>
      <p className="mb-3 text-[11px] text-muted-foreground">Leads de cada agente no período e até onde foram</p>
      {!d.agentes.length ? <Vazio>Nenhum agente recebeu leads no período.</Vazio> : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="py-2 text-left text-xs font-medium text-muted-foreground">Agente</th>
                <th className="py-2 text-right text-xs font-medium text-muted-foreground">Leads</th>
                <th className="py-2 text-right text-xs font-medium text-muted-foreground">Qualificados</th>
                <th className="py-2 text-right text-xs font-medium text-muted-foreground">Contratos</th>
                <th className="py-2 text-right text-xs font-medium text-muted-foreground">Assinados</th>
                <th className="py-2 text-right text-xs font-medium text-muted-foreground">Desqualif.</th>
                <th className="py-2 text-right text-xs font-medium text-muted-foreground">Conversão</th>
              </tr>
            </thead>
            <tbody>
              {d.agentes.map((a) => (
                <tr key={a.id_agente ?? "sem"} className="border-b border-border/50 last:border-0">
                  <td className="py-2.5 pr-3">
                    {a.id_agente ? <Link to={`/agentes/${a.id_agente}`} className="font-medium text-foreground hover:text-primary">{a.nome}</Link> : <span className="font-medium text-foreground">{a.nome}</span>}
                    <div className="mt-1 h-1.5 w-full max-w-[220px] overflow-hidden rounded-full bg-muted/60">
                      <motion.div className="h-full rounded-full bg-gradient-to-r from-violet-400 to-purple-600" initial={{ width: 0 }}
                        whileInView={{ width: `${(a.leads / max) * 100}%` }} viewport={{ once: true }} transition={{ duration: 0.9, ease: "easeOut" }} />
                    </div>
                  </td>
                  <td className="py-2.5 text-right font-medium tabular-nums text-foreground">{fmtNum(a.leads)}</td>
                  <td className="py-2.5 text-right tabular-nums text-foreground">{fmtNum(a.qualificados)}</td>
                  <td className="py-2.5 text-right tabular-nums text-foreground">{fmtNum(a.contratos)}</td>
                  <td className="py-2.5 text-right font-medium tabular-nums text-emerald-600">{fmtNum(a.assinados)}</td>
                  <td className="py-2.5 text-right tabular-nums text-red-500">{fmtNum(a.desqualificados)}</td>
                  <td className={cn("py-2.5 text-right font-medium tabular-nums", a.nome === melhor ? "text-green-500" : "text-foreground")}>{fmtPct(a.conversao ?? 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function LeadsPorEtapa({ d }: { d: Dashboard }) {
  const [aberta, setAberta] = useState<string | null>(null);
  const [busca, setBusca] = useState("");
  const grupos = useMemo(() => {
    const m = new Map<string, Dashboard["etapas"]>();
    [...ORDEM_FASES, "outra", "sem_etapa"].forEach((f) => m.set(f, []));
    d.etapas.forEach((e) => { if (!m.has(e.fase)) m.set(e.fase, []); m.get(e.fase)!.push(e); });
    return [...m.entries()].filter(([, v]) => v.length > 0);
  }, [d.etapas]);
  const exportar = () => baixarCsv(`leads-por-etapa-${d.periodo.de}-a-${d.periodo.ate}.csv`, ["Fase", "Etapa", "Agente", "Leads"],
    d.etapas.map((e) => [NOME_FASE[e.fase] ?? e.fase, e.nome, e.agente, e.leads]));
  return (
    <div className={CARTAO}>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border p-4">
        <div>
          <h3 className="text-lg font-semibold text-foreground">Leads por Etapa</h3>
          <p className="text-[11px] text-muted-foreground">Onde os leads do período estão agora, por etapa e agente</p>
        </div>
        <div className="flex items-center gap-2 print:hidden">
          <button type="button" onClick={exportar} className="lc-brilho flex items-center gap-1.5 rounded-lg bg-muted/50 px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground">
            <Download className="h-3.5 w-3.5" />CSV
          </button>
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <input type="text" placeholder="Buscar etapa ou agente..." value={busca} onChange={(e) => setBusca(e.target.value)}
              className="h-8 rounded-md border border-border bg-background pl-9 pr-3 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring" />
          </div>
        </div>
      </div>
      {!grupos.length && <Vazio>Sem leads no período.</Vazio>}
      {grupos.map(([fase, linhas]) => {
        const q = busca.toLowerCase();
        const filtradas = q ? linhas.filter((l) => l.nome.toLowerCase().includes(q) || l.agente.toLowerCase().includes(q)) : linhas;
        if (q && !filtradas.length) return null;
        const total = filtradas.reduce((s, l) => s + l.leads, 0);
        const s = ESTILO_FASE[fase] ?? ESTILO_FASE.outra;
        const aberto = aberta === fase || Boolean(q);
        return (
          <div key={fase} className="border-b border-border/50 last:border-0">
            <button type="button" onClick={() => setAberta(aberta === fase ? null : fase)} aria-expanded={aberto}
              className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-medium text-foreground transition-colors hover:bg-secondary/50">
              <span className="flex items-center gap-2"><span className="h-2 w-2 rounded-full" style={{ background: s.ponto }} />{NOME_FASE[fase] ?? fase} ({fmtNum(total)})</span>
              <ChevronDown className={cn("h-4 w-4 text-muted-foreground transition-transform", aberto && "rotate-180")} />
            </button>
            <AnimatePresence initial={false}>
              {aberto && (
                <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="bg-secondary/30 text-xs text-muted-foreground">
                        <th className="px-4 py-2 text-left font-medium">Etapa</th><th className="px-4 py-2 text-left font-medium">Agente</th>
                        <th className="px-4 py-2 text-right font-medium">Leads</th><th className="px-4 py-2 text-right font-medium">% da fase</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filtradas.map((l, i) => (
                        <tr key={`${l.agente}-${l.etapa}-${i}`} className="border-b border-border/30 transition-colors last:border-0 hover:bg-secondary/30">
                          <td className="px-4 py-2 font-medium text-foreground">{l.nome}</td>
                          <td className="px-4 py-2 text-muted-foreground">{l.agente}</td>
                          <td className="px-4 py-2 text-right tabular-nums text-foreground">{fmtNum(l.leads)}</td>
                          <td className="px-4 py-2 text-right tabular-nums text-muted-foreground">{fmtPct(total ? (l.leads / total) * 100 : 0)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        );
      })}
    </div>
  );
}

function CardsDoCrm({ d, pedirImportacao, pedindo }: { d: Dashboard; pedirImportacao: () => void; pedindo: boolean }) {
  const c = d.crm;
  const metricas = c ? [
    { rotulo: "Cards abertos no painel", valor: c.total, icone: Layers, cor: "text-blue-600", fundo: "bg-blue-100" },
    { rotulo: "Criados no período", valor: c.no_periodo, icone: CalendarDays, cor: "text-emerald-600", fundo: "bg-emerald-100" },
    { rotulo: "Sem conversa com a IA", valor: c.sem_lead, icone: UserX, cor: "text-amber-600", fundo: "bg-amber-100" },
    { rotulo: "Em colunas de contrato assinado", valor: c.assinados, icone: FileSignature, cor: "text-violet-600", fundo: "bg-violet-100" },
  ] : [];
  return (
    <div className={cn(CARTAO, "p-5")}>
      <div className="mb-1 flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-2"><BarChart3 className="h-4 w-4 text-primary" /><h3 className="text-sm font-semibold text-foreground">Cards do CRM</h3></div>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            {c?.ultima_varredura ? `Conferido com o CRM em ${new Date(c.ultima_varredura).toLocaleString("pt-BR")}. Inclui os cards antigos e os que a IA não atendeu.`
              : "Cards do painel do CRM da conta, inclusive os de antes da IA."}
          </p>
        </div>
        {c && (
          <button type="button" onClick={pedirImportacao} disabled={pedindo || c.importacao_pedida}
            className="lc-brilho lc-brilho--borda flex items-center gap-1.5 rounded-xl border border-border/60 bg-background px-3.5 py-2 text-sm font-medium text-muted-foreground transition-all hover:-translate-y-0.5 hover:border-border hover:text-foreground disabled:opacity-60 print:hidden">
            <Sparkles className="h-4 w-4 text-primary" />{c.importacao_pedida ? "Importação na fila" : c.importado_em ? "Importar de novo" : "Importar cards antigos"}
          </button>
        )}
      </div>
      <div className="mt-3">
        {!c ? <Vazio>O espelho do CRM ainda não está ligado neste servidor.</Vazio>
          : !c.total ? <Vazio>{c.importacao_pedida || !c.importado_em
            ? "Os cards do CRM ainda não foram importados. A conferência roda sozinha a cada 15 minutos quando o CRM está ligado em Integrações."
            : "Nenhum card no painel do CRM."}</Vazio>
          : (
            <>
              <div className="mb-4 grid grid-cols-2 gap-2.5 lg:grid-cols-4">
                {metricas.map((m) => (
                  <div key={m.rotulo} className="rounded-xl border border-border/50 bg-muted/20 p-3">
                    <div className="mb-1.5 flex items-center gap-1.5">
                      <span className={cn("flex h-6 w-6 items-center justify-center rounded-md", m.fundo)}><m.icone className={cn("h-3 w-3", m.cor)} /></span>
                      <span className="text-[10px] leading-tight text-muted-foreground">{m.rotulo}</span>
                    </div>
                    <p className="text-xl font-bold leading-none tabular-nums text-foreground"><Contador valor={m.valor} duracao={900} /></p>
                  </div>
                ))}
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border">
                      <th className="py-2 text-left text-xs font-medium text-muted-foreground">Coluna no CRM</th>
                      <th className="py-2 text-left text-xs font-medium text-muted-foreground">Fase</th>
                      <th className="py-2 text-right text-xs font-medium text-muted-foreground">Cards</th>
                      <th className="py-2 text-right text-xs font-medium text-muted-foreground">Criados no período</th>
                      <th className="py-2 text-right text-xs font-medium text-muted-foreground">Sem conversa com a IA</th>
                    </tr>
                  </thead>
                  <tbody>
                    {c.colunas.map((col, i) => (
                      <tr key={`${col.coluna}-${i}`} className="border-b border-border/50 last:border-0">
                        <td className="py-2.5 font-medium text-foreground">{col.coluna || "Coluna sem nome"}</td>
                        <td className="py-2.5">
                          <span className="inline-flex items-center gap-1.5 rounded-full bg-muted/60 px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
                            <span className="h-1.5 w-1.5 rounded-full" style={{ background: (ESTILO_FASE[col.fase] ?? ESTILO_FASE.outra).ponto }} />{col.nome_fase}
                          </span>
                        </td>
                        <td className="py-2.5 text-right font-medium tabular-nums text-foreground">{fmtNum(col.total)}</td>
                        <td className="py-2.5 text-right tabular-nums text-foreground">{fmtNum(col.no_periodo)}</td>
                        <td className="py-2.5 text-right tabular-nums text-foreground">{fmtNum(col.sem_lead)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        {c?.erro && <p className="mt-3 flex items-center gap-1.5 text-[11px] text-muted-foreground"><ShieldAlert className="h-3.5 w-3.5 text-amber-500" />Última conferência falhou ({c.erro}); tentamos de novo sozinhos.</p>}
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- faixa da IA, taxas e mapa de calor
/** Leads, custo e custos médios da IA com a minicurva real de cada dia (custos médios: acumulado até o dia). */
function FaixaIA({ d }: { d: Dashboard }) {
  const k = d.kpis;
  const metricas = useMemo<Metrica[]>(() => {
    let cl = 0, cc = 0, ca = 0;
    const porLead: { rotulo: string; valor: number }[] = [], porContrato: { rotulo: string; valor: number }[] = [];
    d.serie.forEach((s) => {
      cl += s.leads; cc += s.custo_brl; ca += s.assinados;
      porLead.push({ rotulo: curta(s.dia), valor: cl ? cc / cl : 0 });
      if (ca) porContrato.push({ rotulo: curta(s.dia), valor: cc / ca });
    });
    return [
      { rotulo: "Leads atendidos pela IA", valor: k.leads, icone: Bot, variacao: k.leads_variacao,
        sub: `${fmtNum(k.assinados)} assinaram · ${fmtNum(k.desqualificados)} desqualificados`,
        dica: <Dica texto="Leads que entraram no período e conversaram com a IA. Passe o mouse na curva para ver cada dia." />,
        serie: d.serie.map((s) => ({ rotulo: curta(s.dia), valor: s.leads })) },
      { rotulo: "Custo da IA", valor: k.custo_brl, formatar: fmtBRL, icone: CircleDollarSign, variacao: k.custo_variacao, inverter: true, cor: "#00a32c",
        sub: `${fmtNum(k.chamadas_ia)} chamadas à IA`, dica: <Dica texto="Quanto as chamadas à IA custaram no período (e em cada dia, na curva)." />,
        serie: d.serie.map((s) => ({ rotulo: curta(s.dia), valor: s.custo_brl })) },
      { rotulo: "Custo por Lead", valor: k.custo_por_lead, formatar: fmtBRL, icone: Gauge, sub: "custo da IA ÷ leads", prefixoDia: "até",
        dica: <Dica texto="Custo da IA ÷ leads que entraram no período. Na curva: o valor acumulado até cada dia." />, serie: porLead },
      { rotulo: "Custo por Contrato", valor: k.custo_por_contrato, formatar: fmtBRL, icone: FileSignature, sub: `${fmtNum(k.assinados)} contratos da IA`, prefixoDia: "até",
        dica: <Dica texto="Custo da IA ÷ contratos assinados pelos leads do período. Na curva: o valor acumulado até cada dia." />, serie: porContrato },
    ];
  }, [d.serie, k]);
  return <FaixaMetricas metricas={metricas} />;
}

/** Anéis das taxas do período (cheio = 100%). Na conversão, o tracinho mostra o período anterior. */
function TaxasDoPeriodo({ d }: { d: Dashboard }) {
  const k = d.kpis, c = d.cards, ia = d.ia;
  const taxas = [
    { rotulo: "Lead qualificado", valor: c ? c.qualificados_pct : k.qualificados_pct, sub: `${fmtNum(c ? c.qualificados : k.qualificados)} qualificados` },
    { rotulo: "Conversão", valor: c ? c.conversao : k.conversao, sub: c ? "cards → assinado" : "leads → assinado",
      referencia: (c ? c.conversao_anterior : k.conversao_anterior) != null ? { valor: (c ? c.conversao_anterior : k.conversao_anterior)!, rotulo: "antes" } : null },
    { rotulo: "Eficiência", valor: c ? c.eficiencia : k.eficiencia, sub: "assinados ÷ passaram do SDR" },
    { rotulo: "Respondidos pela IA", valor: ia.turnos ? (ia.respondidos / ia.turnos) * 100 : null, sub: `${fmtNum(ia.respondidos)} de ${fmtNum(ia.turnos)} atendimentos` },
  ];
  return (
    <div className={cn(CARTAO, "p-5 md:p-6")}>
      <div className="mb-4 flex items-center gap-2">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-100"><Target className="h-4 w-4 text-emerald-600" /></span>
        <div>
          <div className="flex items-center gap-2"><h3 className="text-sm font-semibold text-foreground">Taxas do período</h3>
            <Dica texto="Cada anel cheio é 100%. Na conversão, o tracinho escuro marca o período anterior do mesmo tamanho." /></div>
          <p className="text-[11px] text-muted-foreground">{c ? "Pelos cards do CRM; a última pelos atendimentos da IA" : "Pelos leads da IA no período"}</p>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-6 md:grid-cols-4">
        {taxas.map((x, i) => <MedidorMeta key={x.rotulo} rotulo={x.rotulo} valor={x.valor} sub={x.sub} referencia={x.referencia} atraso={0.1 + i * 0.1} />)}
      </div>
    </div>
  );
}

const DIAS_LONGOS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"];
function picoDaGrade(g: number[][]) {
  let m = { v: 0, dia: 0, hora: 0 };
  g.forEach((l, dia) => l.forEach((v, hora) => { if (v > m.v) m = { v, dia, hora }; }));
  return m;
}

/** Quando os leads chegam e quando assinam: dia da semana × hora (horário de Brasília). */
function CartaoMapaCalor({ d }: { d: Dashboard }) {
  const pl = picoDaGrade(d.horarios.leads), pa = picoDaGrade(d.horarios.assinados);
  return (
    <div className={cn(CARTAO, "p-5")}>
      <div className="mb-1 flex items-center gap-2"><Clock className="h-4 w-4 text-primary" /><h3 className="text-sm font-semibold text-foreground">Mapa de horários</h3></div>
      <p className="mb-4 text-[11px] text-muted-foreground">Quando os leads chegam e quando assinam, por dia da semana e hora (horário de Brasília)</p>
      <div className="grid grid-cols-1 gap-8 xl:grid-cols-2">
        <div>
          <p className="mb-2 text-xs font-semibold text-foreground">Chegada de leads</p>
          <MapaCalor grade={d.horarios.leads} unidade="lead" />
        </div>
        <div>
          <p className="mb-2 text-xs font-semibold text-foreground">Contratos assinados</p>
          <MapaCalor grade={d.horarios.assinados} unidade="contrato" />
        </div>
      </div>
      {(pl.v > 0 || pa.v > 0) && (
        <div className="mt-4">
          <Insight icone={<Flame className="h-3.5 w-3.5 text-emerald-600" />}>
            {pl.v > 0 && <>Mais leads chegam na <strong className="text-foreground">{DIAS_LONGOS[pl.dia]} às {String(pl.hora).padStart(2, "0")}h</strong> ({fmtNum(pl.v)}).</>}
            {pa.v > 0 && <> Mais contratos são assinados na <strong className="text-foreground">{DIAS_LONGOS[pa.dia]} às {String(pa.hora).padStart(2, "0")}h</strong> ({fmtNum(pa.v)}).</>}
          </Insight>
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- página
function Conteudo({ d, anuncios, abrirAnuncio, pedirImportacao, pedindo, filtrando, exportar }: {
  d: Dashboard; anuncios: Anuncio[] | null; abrirAnuncio: (c: string) => void; pedirImportacao: () => void; pedindo: boolean;
  filtrando: boolean; exportar: () => void;
}) {
  const k = d.kpis, c = d.cards;
  const modo = c?.modo === "atualizacao" ? "atualizados" : "criados";
  // Linha 1: pelos cards do CRM (como o original); conta sem cards espelhados: pelos leads da IA.
  const linha1: Indicador[] = c ? [
    { rotulo: "Cards Totais (no painel)", valor: c.total, sub: c.todo_periodo ? "todo o período" : `${modo} no período`,
      dica: "Cards do painel do CRM (todos os painéis da conta, sem os arquivados), pela data escolhida em Modo.", icone: Layers,
      cor: ["#60a5fa", "#2563eb"], curva: CURVAS.sobe, variacao: c.total_variacao },
    { rotulo: "Contratos Assinados", valor: c.assinados, sub: "cards em contrato assinado", dica: "Cards que estão numa coluna de contrato assinado.", icone: Trophy,
      cor: ["#4ade80", "#16a34a"], curva: CURVAS.arco, corValor: true, variacao: c.assinados_variacao, destaque: true },
    { rotulo: "Taxa de Conversão", valor: c.conversao ?? 0, tipo: "pct", sub: c.conversao_anterior != null ? `Total → Fechado (antes ${fmtPct(c.conversao_anterior)})` : "Total → Fechado",
      dica: "Cards em contrato assinado ÷ cards totais.", icone: TrendingUp, cor: ["#a78bfa", "#7c3aed"], curva: CURVAS.onda },
    { rotulo: "Taxa de Eficiência", valor: c.eficiencia ?? 0, tipo: "pct", sub: "Assinados / Avançaram do SDR",
      dica: `Cards assinados ÷ cards que passaram do SDR (${fmtNum(c.avancaram)}: todas as etapas menos SDR, Desqualificado e colunas fora do funil).`,
      icone: Target, cor: ["#22d3ee", "#0891b2"], curva: CURVAS.suave },
    { rotulo: "% Lead Qualificado", valor: c.qualificados_pct ?? 0, tipo: "pct", sub: `${fmtNum(c.qualificados)} qualificados`,
      dica: "Cards em Closer, Análise Manual, Confecção de Contrato, Aguardando Assinatura ou Contrato Assinado ÷ cards totais.",
      icone: UserCheck, cor: ["#fbbf24", "#d97706"], curva: CURVAS.firme },
  ] : [
    { rotulo: "Leads no período", valor: k.leads, sub: `${fmtNum(k.com_origem)} de anúncio ou UTM`, dica: "Leads que entraram no período (primeiro contato). Esta conta ainda não tem cards do CRM conferidos.", icone: Users,
      cor: ["#60a5fa", "#2563eb"], curva: CURVAS.sobe, variacao: k.leads_variacao },
    { rotulo: "Contratos Assinados", valor: k.assinados, sub: "contratos assinados", dica: "Leads do período que já assinaram o contrato.", icone: Trophy,
      cor: ["#4ade80", "#16a34a"], curva: CURVAS.arco, corValor: true, variacao: k.assinados_variacao, destaque: true },
    { rotulo: "Taxa de Conversão", valor: k.conversao ?? 0, tipo: "pct", sub: k.conversao_anterior != null ? `Total → Assinado (antes ${fmtPct(k.conversao_anterior)})` : "Total → Assinado",
      dica: "Contratos assinados ÷ leads do período.", icone: TrendingUp, cor: ["#a78bfa", "#7c3aed"], curva: CURVAS.onda },
    { rotulo: "Taxa de Eficiência", valor: k.eficiencia ?? 0, tipo: "pct", sub: "Assinados / Avançaram do SDR", dica: "Contratos assinados ÷ leads que passaram do SDR (sem os desqualificados).", icone: Target,
      cor: ["#22d3ee", "#0891b2"], curva: CURVAS.suave },
    { rotulo: "% Lead Qualificado", valor: k.qualificados_pct ?? 0, tipo: "pct", sub: `${fmtNum(k.qualificados)} qualificados`, dica: "Leads que chegaram ao Closer ou além ÷ leads do período.", icone: UserCheck,
      cor: ["#fbbf24", "#d97706"], curva: CURVAS.firme },
  ];
  return (
    <div className="space-y-5">
      <Cascata className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5" passo={0.07}>
        {linha1.map((i, n) => <CartaoIndicador key={i.rotulo} i={i} n={n} />)}
      </Cascata>
      <Etapas d={d} />
      <div className="grid grid-cols-1 items-stretch gap-5 lg:grid-cols-5">
        <div className="lg:col-span-3">
          <FunilDegraus etapas={c?.funil ?? d.funil} total={c ? c.total : k.leads} titulo="Funil de Vendas"
            subtitulo={c ? "Fluxo dos cards do CRM por etapa (até onde cada card chegou)" : "Visualização do fluxo de leads por etapa (até onde cada lead já chegou)"}
            dica="Cada etapa conta quem chegou a ela ou foi além. O selo entre as etapas mostra quantos passaram da anterior para esta." classe="lg:min-h-[700px]" />
        </div>
        <div className="lg:col-span-2"><MelhoresAnuncios anuncios={anuncios} abrir={abrirAnuncio} de={d.periodo.de} ate={d.periodo.ate} gerado={d.gerado_em} /></div>
      </div>
      <div>
        <h2 className="mb-3 flex items-center gap-2 text-sm font-bold uppercase tracking-[0.08em] text-slate-500"><Bot className="h-4 w-4 text-emerald-600" />Atendimento da IA</h2>
        <AoAparecer altura={180}><FaixaIA d={d} /></AoAparecer>
      </div>
      <AoAparecer altura={220}><TaxasDoPeriodo d={d} /></AoAparecer>
      <AoAparecer altura={380}>
        <div className="grid grid-cols-1 items-stretch gap-5 lg:grid-cols-2">
          <TempoAteAssinar d={d} />
          <AtendimentoIA d={d} />
        </div>
      </AoAparecer>
      <AoAparecer altura={460}><Evolucao d={d} /></AoAparecer>
      <AoAparecer altura={420}>
        <div className="grid grid-cols-1 items-stretch gap-5 lg:grid-cols-2">
          <OrigemLeads d={d} />
          <MapaEstados leads={d.uf.leads} contratos={d.uf.contratos} />
        </div>
      </AoAparecer>
      <AoAparecer altura={340}><CartaoMapaCalor d={d} /></AoAparecer>
      <AoAparecer altura={320}><Agentes d={d} /></AoAparecer>
      <AoAparecer altura={320}><LeadsPorEtapa d={d} /></AoAparecer>
      <AoAparecer altura={320}><CardsDoCrm d={d} pedirImportacao={pedirImportacao} pedindo={pedindo} /></AoAparecer>
      <p className="flex flex-wrap items-center justify-center gap-1.5 text-center text-[11px] text-muted-foreground/80">
        <Bot className="h-3.5 w-3.5" />
        {c ? "Indicadores principais pelos cards do painel do CRM; quadros da IA pelos leads, mensagens e chamadas da IA."
          : "Números calculados a partir do que a LawChat registrou (mensagens, etapas, contratos e chamadas da IA)."}
        {filtrando && <><Filter className="h-3 w-3" />Com filtro de campanha ou origem, a IA e o custo contam só os leads filtrados.</>}
        <span>Atualizado em {new Date(d.gerado_em).toLocaleTimeString("pt-BR")}.</span>
      </p>
      <BotoesExportar csv={[{ rotulo: "Baixar CSV", aoClicar: exportar }]} />
    </div>
  );
}
