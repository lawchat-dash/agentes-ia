import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import BotaoBrilho from "@/components/reactbits/BotaoBrilho";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  MessageSquare, Mail, Box, Users, Package, ChevronRight, Reply, ArrowUpRight, Sparkles, Activity, Zap, Trophy,
  CheckCircle2, ArrowUp, ArrowDown, Pause, TrendingUp, ShieldCheck, PlayCircle, Plus, PlugZap, Webhook,
  Ban, Gauge, Bug, BotOff, FileSignature, ChevronDown, RefreshCw, CloudOff,
} from "lucide-react";
import { ResponsiveContainer, XAxis, YAxis, Tooltip, AreaChart, Area, BarChart, Bar } from "recharts";
import { formatDistanceToNowStrict } from "date-fns";
import { ptBR } from "date-fns/locale";
import { formatarTelefone, quando } from "../api";
import { Cabecalho, Carregando, Painel, Vazio, useCarregar } from "../componentes/ui";
import { useSessao } from "../sessao";
import { PainelFunil } from "./Funil";
import BorderGlow from "@/components/ui/border-glow";
import { useCardGlow } from "@/components/dashboard/useCardGlow";
import { SaldoCenter, formatUSD, type ConsumoMes, type CarteiraResumo } from "@/components/dashboard/ConsumoCenter";
import { StatusPanel } from "@/components/dashboard/StatusPanel";
import { ActivityFeed, type ActivityItem } from "@/components/dashboard/ActivityFeed";
import { ContatosPorEstado } from "@/components/dashboard/ContatosPorEstado";
import { AlertaOperacional, type AlertaOperacionalProps, type TomAlerta } from "@/components/dashboard/AlertaOperacional";
import { TEXTO_FOLLOWUP_DESLIGADO, ligarFollowupComPadrao } from "@/components/followup/AvisoFollowupDesligado";
import { BellOff } from "lucide-react";
import { conectarAvisoAssinatura } from "@/hooks/useZapsign";
import { toast } from "sonner";
import { PrimeirosPassos, type PrimeirosPassosDados } from "@/components/dashboard/PrimeirosPassos";
import { BentoIndicadores } from "@/components/dashboard/BentoIndicadores";
import "../estilo-inicio.css";

/* ---------- dados da API ---------- */
interface Inicio {
  resumo: { erros_abertos: number; turnos_com_erro_24h: number; ultimo_webhook: string | null };
  agentes: { id: string; situacao: string }[];
  integracoes: Record<string, { situacao: string; config: Record<string, unknown> }>;
  /** Produtos ativos com follow-up desligado (docs/FOLLOWUP.md). */
  followup_desligado?: { id_ativado: string; nome: string }[];
}

interface Metricas {
  dias: number;
  serie: { date: string; conv: number; msgs: number; tokens: number; custo_usd: number }[];
  conversas_hoje: number; conversas_hoje_variacao: number | null;
  conversas_periodo: number; conversas_variacao: number | null;
  mensagens: number; mensagens_variacao: number | null;
  tokens: number; tokens_variacao: number | null;
  custo_periodo_usd: number;
  agentes_ativos: number; agentes_total: number;
  ranking_agentes: { id: string; nome: string; situacao: string; modo: string; conversas: number; assinados: number; variacao: number | null }[];
  estados: { estado: string; total: number }[];
  resposta_media_s: number | null;
  atividades: { id: string; tipo: string; estado: string; motivo_estado: string | null; nome: string | null; telefone: string | null;
    id_agente: string | null; agente: string | null; etapa: string | null; momento: string; criado_em: string }[];
  followup: { pendentes: number; enviados: number; respondidos: number; taxa_resposta: number | null; taxa_variacao: number | null };
  produtos: { ativos: number; total: number };
  uf: { leads: Record<string, number>; contratos: Record<string, number> };
  consumo: ConsumoMes | null;
}

const AI_FEATURES = [
  { icon: Zap, title: "Respostas instantâneas 24/7", desc: "Atendimento sem parar, todos os dias." },
  { icon: TrendingUp, title: "Mais conversões", desc: "A IA qualifica e conduz até o fechamento." },
  { icon: ShieldCheck, title: "Segurança e conformidade", desc: "Seus dados protegidos e em conformidade." },
];

const TILE = "lc-card lc-metric relative overflow-hidden";
const APP_VERSION = "v0.1.0";
const DIAS = 30;
const ESPERA_ALERTAS_MS = 700;
const CORES_AGENTES = ["#22c55e", "#0ea5e9", "#2563eb", "#f59e0b", "#ef4444"];
const fmtBr = (n: number) => Math.round(Number(n) || 0).toLocaleString("pt-BR");
const fmtK = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(1).replace(".", ",")}M` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : String(Math.round(n)));
const dm = (d: string) => `${String(d).slice(8)}/${String(d).slice(5, 7)}`;
const NOMES_ETAPAS: Record<string, string> = {
  sdr: "Primeiro atendimento", periodo_graca: "Período de graça", closer: "Proposta e honorários",
  coleta_dados: "Dados do contrato", analise_manual: "Análise da equipe", desqualificado: "Encerramento",
};
const MOTIVOS: Record<string, string> = {
  humano_assumiu: "A equipe assumiu o atendimento", desqualificado: "Fora do perfil", pediu_parar: "Pediu para parar",
};

/** ícone/cor/descrição por estado da conversa (Painel de Saúde Operacional) */
const ESTADOS: Record<string, { label: string; color: string; icon: any; bg: string; desc: string }> = {
  ativo: { label: "Em atendimento", color: "#22c55e", icon: MessageSquare, bg: "#e8f9ee", desc: "A IA está conversando com o lead" },
  pausado: { label: "Pausadas", color: "#f59e0b", icon: Pause, bg: "#fff4df", desc: "A equipe assumiu ou a IA foi pausada" },
  encerrado: { label: "Encerradas", color: "#94a3b8", icon: CheckCircle2, bg: "#eef2f7", desc: "Conversas finalizadas" },
};

/** visual de cada atividade recente */
const ATIVIDADES: Record<string, { icon: any; bg: string; color: string; dot: string; title: string; badge?: string }> = {
  nova: { icon: MessageSquare, bg: "#e8f9ee", color: "#16a34a", dot: "#22c55e", title: "Nova conversa iniciada", badge: "Novo" },
  em_andamento: { icon: Mail, bg: "#eaf1ff", color: "#2563eb", dot: "#2563eb", title: "Conversa em andamento" },
  pausada: { icon: Pause, bg: "#fff4df", color: "#d97706", dot: "#f59e0b", title: "IA pausada na conversa" },
  encerrada: { icon: CheckCircle2, bg: "#eef2f7", color: "#475467", dot: "#94a3b8", title: "Conversa finalizada" },
  contrato_assinado: { icon: FileSignature, bg: "#dcfce7", color: "#15803d", dot: "#16a34a", title: "Contrato assinado", badge: "Assinado" },
};

/* Alertas: os mais graves primeiro; só dois à vista, o resto atrás de "Ver mais". */
const ORDEM_TOM: Record<TomAlerta, number> = { critico: 0, atencao: 1, info: 2 };
const MAX_ALERTAS = 2;

/** Alertas de atenção/info que a pessoa dispensou nesta sessão do navegador (por escritório). */
function useAlertasDispensados(escritorio: string | null) {
  const chave = `lc-alertas-dispensados:${escritorio ?? ""}`;
  const ler = (k: string): string[] => {
    try {
      const v = JSON.parse(sessionStorage.getItem(k) || "[]");
      return Array.isArray(v) ? v.filter((x) => typeof x === "string") : [];
    } catch { return []; }
  };
  const [dispensados, setDispensados] = useState<string[]>(() => ler(chave));
  useEffect(() => { setDispensados(ler(chave)); }, [chave]);
  const dispensar = useCallback((id: string) => {
    setDispensados((atual) => {
      const novo = atual.includes(id) ? atual : [...atual, id];
      try { sessionStorage.setItem(chave, JSON.stringify(novo)); } catch { /* sem armazenamento: vale só até recarregar */ }
      return novo;
    });
  }, [chave]);
  return { dispensados, dispensar };
}

function tempo(segundos: number | null): string {
  if (segundos == null) return "—";
  if (segundos < 60) return `${segundos}s`;
  if (segundos < 3600) return `${Math.floor(segundos / 60)}m ${String(segundos % 60).padStart(2, "0")}s`;
  return `${Math.floor(segundos / 3600)}h ${String(Math.floor((segundos % 3600) / 60)).padStart(2, "0")}m`;
}

export function TelaInicio() {
  const { escritorio, podeGerir, admin, eu, lawchat } = useSessao();
  const navegar = useNavigate();
  const inicio = useCarregar<Inicio>(escritorio ? "/inicio" : null, [escritorio]);
  const metricas = useCarregar<Metricas>(escritorio ? `/inicio/metricas?dias=${DIAS}` : null, [escritorio]);
  const carteira = useCarregar<CarteiraResumo>(escritorio && podeGerir ? "/carteira" : null, [escritorio]);
  const passos = useCarregar<PrimeirosPassosDados>(escritorio && podeGerir ? "/inicio/primeiros-passos" : null, [escritorio]);
  const rootRef = useRef<HTMLDivElement>(null);
  const reduzirMovimento = useReducedMotion();
  const [verTodosAlertas, setVerTodosAlertas] = useState(false);
  const { dispensados, dispensar } = useAlertasDispensados(escritorio);
  useCardGlow(rootRef, { pronto: Boolean(metricas.dados) });
  // Os números chegaram e o /inicio (alertas) não: espera no máximo ESPERA_ALERTAS_MS e mostra o resto (os alertas
  // entram depois, com animação). Antes a tela toda ficava no esqueleto esperando a rota mais lenta.
  const [semEsperarAlertas, setSemEsperarAlertas] = useState(false);
  const temNumeros = Boolean(metricas.dados);
  const temAlertas = Boolean(inicio.dados || inicio.erro);
  useEffect(() => {
    if (!temNumeros || temAlertas) return;
    const t = window.setTimeout(() => setSemEsperarAlertas(true), ESPERA_ALERTAS_MS);
    return () => window.clearTimeout(t);
  }, [temNumeros, temAlertas]);

  const firstName = eu?.nome?.split(" ")[0] || "você";
  const hora = new Date().getHours();
  const saudacao = hora < 12 ? "Bom dia" : hora < 18 ? "Boa tarde" : "Boa noite";
  const saudacaoEmoji = hora < 12 ? "🌅" : hora < 18 ? "☀️" : hora < 20 ? "🌆" : "🌙";

  if (!escritorio) {
    return (
      <>
        <Cabecalho eyebrow="Equipe LawChat" titulo={`Olá, ${eu?.nome.split(" ")[0] ?? ""}`} texto="A conta da LawChat ainda não está no sistema." />
        <Painel><Vazio>Abra <Link to="/admin/escritorios">Admin › Contas</Link> e clique em <b>Sincronizar com LawChat</b>: a conta LawChat entra e esta tela passa a mostrar os agentes dela.</Vazio></Painel>
      </>
    );
  }
  const v = metricas.dados;
  // Espera também o /inicio (de onde vêm os alertas), para eles não surgirem depois empurrando os KPIs.
  if (!v || (!temAlertas && !semEsperarAlertas)) return <Carregando erro={metricas.erro} />;

  /* ---------- alertas operacionais (topo) ---------- */
  const alertas: (AlertaOperacionalProps & { chave: string })[] = [];
  const dadosInicio = inicio.dados;
  if (inicio.erro && podeGerir) alertas.push({
    chave: "inicio-erro", tom: "atencao", icone: CloudOff, titulo: "Não foi possível checar as integrações agora",
    texto: "Os números abaixo estão em dia, mas não deu para conferir a LawChat, o webhook e os erros abertos. Tente de novo em instantes.",
    acao: { rotulo: inicio.carregando ? "Checando…" : "Tentar de novo", aoClicar: () => { inicio.recarregar(); }, icone: RefreshCw },
  });
  if (dadosInicio) {
    const helena = dadosInicio.integracoes.helena;
    const semHelena = !helena || helena.situacao !== "ok";
    const semWebhook = !semHelena && !(helena.config as any)?.webhook_conectado;
    // Quem conecta a conta e habilita a IA é a equipe LawChat (função de agente no superadmin), não o cliente.
    if (semHelena && podeGerir) alertas.push({
      chave: "helena", tom: "critico", icone: PlugZap, titulo: "A conta ainda não está habilitada para a IA",
      texto: "Sem a conta habilitada, a IA não lê os números do escritório nem recebe as mensagens dos leads. Fale com a equipe LawChat para habilitar.",
      acao: admin ? { rotulo: "Abrir Contas", para: "/admin/escritorios" } : null,
      nota: admin ? undefined : "Fale com a equipe LawChat para habilitar",
    });
    if (semWebhook && podeGerir) alertas.push({
      chave: "webhook", tom: "atencao", icone: Webhook, titulo: "Falta ligar o recebimento de mensagens",
      texto: <>A LawChat está conectada, mas as mensagens ainda não chegam à IA. Em Integrações, use <b>“Conectar webhook”</b>.</>,
      acao: { rotulo: "Conectar webhook", para: "/integracoes" },
      nota: `Última mensagem recebida: ${quando(dadosInicio.resumo.ultimo_webhook)}`,
    });
    // Erros NÃO aparecem no Início do escritório (nem quando a equipe LawChat entra na conta): ficam só no sino e em
    // Erros da IA, na área da equipe LawChat.
    if (podeGerir && dadosInicio.agentes.length > 0 && !dadosInicio.agentes.some((a) => a.situacao === "ativo")) alertas.push({
      chave: "agentes", tom: "info", icone: BotOff, titulo: "Nenhum agente ativo",
      texto: <>Os leads ainda não estão sendo atendidos pela IA. Em <b>Meus agentes</b>, ligue o agente (ou abra e use <b>“Ativar em teste”</b>).</>,
      acao: { rotulo: "Abrir Meus agentes", para: "/meus-produtos" },
    });
    const semFollowup = dadosInicio.followup_desligado ?? [];
    if (podeGerir && semFollowup.length > 0) alertas.push({
      chave: `followup:${semFollowup.map((p) => p.id_ativado).join(",")}`, tom: "info", icone: BellOff,
      titulo: semFollowup.length === 1 ? `${semFollowup[0].nome}: follow-up desligado` : `Follow-up desligado em ${semFollowup.length} produtos`,
      texto: semFollowup.length === 1 ? `${TEXTO_FOLLOWUP_DESLIGADO}.` : <>{TEXTO_FOLLOWUP_DESLIGADO}: {semFollowup.map((p) => p.nome).join(", ")}.</>,
      acao: semFollowup.length === 1
        ? { rotulo: "Ligar com o padrão", aoClicar: () => { ligarFollowupComPadrao(semFollowup[0].id_ativado).then(() => inicio.recarregar()).catch((e) => toast.error((e as Error).message)); } }
        : { rotulo: "Ver em Meus produtos", para: "/meus-produtos" },
    });
    // ZapSign conectada sem o aviso de assinatura: o lead não avança sozinho, não sai resumo e os lembretes não param.
    const zapsign = dadosInicio.integracoes.zapsign;
    if (podeGerir && zapsign && zapsign.situacao === "ok" && !zapsign.config?.webhook_id) alertas.push({
      chave: "zapsign-aviso-assinatura", tom: "atencao", icone: FileSignature,
      titulo: "ZapSign sem o aviso de contrato assinado",
      texto: "Sem esse aviso, o lead não avança sozinho quando assina, o resumo do contrato não sai e os lembretes continuam indo. Conecte uma vez e vale para todos os produtos.",
      acao: { rotulo: "Conectar aviso", aoClicar: () => {
        conectarAvisoAssinatura().then((r) => {
          if (r.error) toast.error(r.error); else { toast.success("Aviso de assinatura conectado."); inicio.recarregar(); }
        });
      } },
    });
  }
  // O limite mensal em US$ é coisa da equipe LawChat; o cliente vê o saldo em R$ (Consumo e saldo).
  const consumo = admin ? v.consumo : null;
  if (consumo?.bloqueado) alertas.push({
    chave: "consumo", tom: "critico", icone: Ban, titulo: "A IA está pausada: o limite de consumo do mês acabou",
    texto: <>Gasto de <b>{formatUSD(consumo.gasto_usd)}</b> de {formatUSD(consumo.limite_usd)}. As mensagens seguem chegando na LawChat para a equipe; a IA volta no dia 1º ou quando o limite subir.</>,
    progresso: consumo.percentual, acao: admin ? { rotulo: "Ajustar limite", para: "/admin/escritorios" } : null,
    nota: admin ? undefined : "Fale com a LawChat para aumentar o limite",
  });
  else if (consumo?.limite_usd && (consumo.percentual ?? 0) >= 80) alertas.push({
    chave: "consumo", tom: "atencao", icone: Gauge,
    titulo: (consumo.percentual ?? 0) >= 100 ? "O consumo da IA passou do limite do mês" : `O consumo da IA chegou a ${Math.floor(consumo.percentual ?? 0)}% do limite do mês`,
    texto: <>Gasto de <b>{formatUSD(consumo.gasto_usd)}</b> de {formatUSD(consumo.limite_usd)}. {consumo.ao_estourar === "pausar" ? "Ao chegar em 100%, a IA para de responder até o mês virar." : "O limite está só para aviso: a IA continua respondendo."}</>,
    progresso: consumo.percentual, acao: admin ? { rotulo: "Ajustar limite", para: "/admin/escritorios" } : null,
    nota: consumo.previsao_dias != null && (consumo.percentual ?? 0) < 100 ? `No ritmo atual, ${consumo.previsao_dias} ${consumo.previsao_dias === 1 ? "dia" : "dias"} até o limite` : undefined,
  });

  const alertasVisiveis = alertas
    .filter((a) => a.tom === "critico" || !dispensados.includes(a.chave))
    .sort((a, b) => ORDEM_TOM[a.tom] - ORDEM_TOM[b.tom]);
  const alertasMostrados = verTodosAlertas ? alertasVisiveis : alertasVisiveis.slice(0, MAX_ALERTAS);
  const alertasOcultos = alertasVisiveis.length - MAX_ALERTAS;

  /* ---------- números das telas ---------- */
  const series = v.serie;
  const maxAgent = Math.max(1, ...v.ranking_agentes.map((a) => a.conversas));
  const totalConv = v.estados.reduce((s, e) => s + e.total, 0);
  const statusItems = v.estados.map((e) => {
    const m = ESTADOS[e.estado] ?? { label: e.estado, color: "#0ea5e9", icon: MessageSquare, bg: "#f1f5f9", desc: "" };
    return { ...m, value: e.total, pct: totalConv ? Math.round((e.total / totalConv) * 100) : 0 };
  });
  const encerradas = v.estados.find((e) => e.estado === "encerrado")?.total ?? 0;
  const ops = {
    evolucao: v.conversas_variacao,
    tempoResposta: tempo(v.resposta_media_s),
    conversasDia: (v.conversas_periodo / v.dias).toFixed(1).replace(".", ","),
    taxaFinalizacao: totalConv ? Math.round((encerradas / totalConv) * 100) : null,
  };

  const activities: ActivityItem[] = v.atividades.map((a) => {
    const m = ATIVIDADES[a.tipo] ?? ATIVIDADES.em_andamento;
    const etapa = a.etapa ? NOMES_ETAPAS[a.etapa] ?? a.etapa : null;
    const motivo = a.motivo_estado ? MOTIVOS[a.motivo_estado] ?? a.motivo_estado.replace(/_/g, " ") : null;
    return {
      id: a.id, icon: m.icon, bg: m.bg, color: m.color, dot: m.dot, title: m.title, badge: m.badge ?? null,
      who: a.nome || formatarTelefone(a.telefone) || "Contato sem nome",
      channel: a.agente ?? "WhatsApp",
      extra: a.tipo === "pausada" && motivo ? motivo : etapa ? `Etapa: ${etapa}` : formatarTelefone(a.telefone),
      time: formatDistanceToNowStrict(new Date(a.momento), { locale: ptBR, addSuffix: true }), // "há 1 hora" (curto: cabe na coluna)
      action: podeGerir && a.id_agente ? "Ver agente" : null,
      to: a.id_agente ? `/agentes/${a.id_agente}` : null,
    };
  });

  return (
    <div ref={rootRef} className="lc-inicio pb-6 max-w-[1600px] mx-auto overflow-x-clip">
      {/* Header */}
      <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35 }} className="mb-6 flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="flex flex-wrap items-center gap-2 text-[28px] md:text-[33px] font-bold tracking-tight text-[#0b1220]">
            {saudacao}, {firstName}!
            <span className="inline-block animate-[wiggle_2s_ease-in-out_infinite]" aria-hidden>{saudacaoEmoji}</span>
            <span title={`Versão ${APP_VERSION} — em fase beta`} className="inline-flex items-center gap-1 rounded-full border border-[#fde9c8] bg-[#fff4df] px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-[#d97706]">
              <Sparkles className="size-3" /> Beta
            </span>
          </h1>
          <p className="text-[#667085] mt-0.5 text-[13px]">Aqui está o desempenho de hoje<span className="ml-1.5 text-[11px] text-[#98A2B3]">· {APP_VERSION}</span></p>
        </div>
        {podeGerir && (
          <BotaoBrilho size="md" radius={12} onClick={() => navegar("/biblioteca")}><Plus className="size-4" /> Novo a partir da Biblioteca</BotaoBrilho>
        )}
      </motion.div>

      {/* Alertas operacionais */}
      <section aria-label="Avisos do escritório" className={`flex flex-col ${alertasVisiveis.length > 0 ? "mb-1.5" : ""}`}>
        <AnimatePresence initial={false}>
          {alertasMostrados.map(({ chave, ...a }, i) => (
            <motion.div key={chave}
              initial={reduzirMovimento ? { opacity: 0 } : { opacity: 0, height: 0, overflow: "hidden" }}
              animate={reduzirMovimento ? { opacity: 1 } : { opacity: 1, height: "auto", transitionEnd: { overflow: "visible" } }}
              exit={reduzirMovimento ? { opacity: 0 } : { opacity: 0, height: 0, overflow: "hidden" }}
              transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}>
              <div className="pb-2.5">
                <AlertaOperacional {...a} delay={i < MAX_ALERTAS ? i * 0.05 : 0}
                  aoDispensar={a.tom === "critico" ? undefined : () => dispensar(chave)} />
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
        {alertasOcultos > 0 && (
          <button type="button" className="lc-alertas-mais focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00bc33]" aria-expanded={verTodosAlertas} onClick={() => setVerTodosAlertas((x) => !x)}>
            {verTodosAlertas ? "Mostrar menos avisos" : `Ver mais ${alertasOcultos} ${alertasOcultos === 1 ? "aviso" : "avisos"}`}
            <ChevronDown aria-hidden />
          </button>
        )}
      </section>

      {/* Primeiros passos: marcam-se sozinhos e o cartão some quando tudo está feito */}
      {podeGerir && passos.dados && <PrimeirosPassos dados={passos.dados} />}

      {/* Indicadores num bento (MagicBento + Counter, React Bits) */}
      <BentoIndicadores chave={escritorio} d={{
        dias: v.dias, serie: series,
        conversasHoje: v.conversas_hoje, conversasHojeVariacao: v.conversas_hoje_variacao,
        mensagens: v.mensagens, mensagensVariacao: v.mensagens_variacao,
        tokens: v.tokens, tokensVariacao: v.tokens_variacao, tokensSub: admin ? `consumidos · ${formatUSD(v.custo_periodo_usd)}` : "consumidos",
        agentesAtivos: v.agentes_ativos, agentesTotal: v.agentes_total, nomesAgentes: v.ranking_agentes.map((a) => a.nome),
        contratos: v.ranking_agentes.reduce((s, a) => s + (a.assinados || 0), 0),
        followup: { pendentes: v.followup.pendentes, enviados: v.followup.enviados, respondidos: v.followup.respondidos, taxa: v.followup.taxa_resposta, taxaVariacao: v.followup.taxa_variacao },
        produtos: v.produtos, podeGerir,
      }} />

      {/* Bloco superior: charts (esq, 2 sub-colunas) + Atividades (coluna alta à direita) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-3 mt-3 items-stretch">
        <div className="lg:col-span-8 grid grid-cols-1 md:grid-cols-12 gap-3">
          {/* Sub-coluna esquerda: Conversas (cima) + Consumo (baixo) */}
          <div className={`${carteira.dados ? "md:col-span-7" : "md:col-span-12"} flex flex-col gap-3`}>
            <Tile className="p-5 flex flex-col flex-1" delay={0.04}>
              <PanelHead title={`Conversas — últimos ${v.dias} dias`} icon={Activity} iconColor="#00bc33" />
              <div className="flex-1 min-h-[200px] mt-2 -mx-2" style={{ filter: "drop-shadow(0 6px 12px rgba(0,188,51,.14))" }}>
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={series} margin={{ top: 6, right: 6, left: -16, bottom: 0 }}>
                    <defs>
                      <linearGradient id="dConv" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#34e06b" stopOpacity={0.34} /><stop offset="60%" stopColor="#00bc33" stopOpacity={0.1} /><stop offset="100%" stopColor="#00bc33" stopOpacity={0} /></linearGradient>
                      <linearGradient id="dConvStroke" x1="0" y1="0" x2="1" y2="0"><stop offset="0%" stopColor="#009926" /><stop offset="50%" stopColor="#34e06b" /><stop offset="100%" stopColor="#00bc33" /></linearGradient>
                    </defs>
                    <XAxis dataKey="date" tickLine={false} axisLine={false} tick={{ fontSize: 10, fill: "#98A2B3" }} minTickGap={40} tickFormatter={dm} />
                    <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 10, fill: "#98A2B3" }} width={30} allowDecimals={false} />
                    <Tooltip contentStyle={{ background: "#fff", border: "1px solid #E2E8F0", borderRadius: "0.6rem", fontSize: 11, boxShadow: "0 8px 28px rgba(15,23,42,.1)" }} formatter={(val: any) => [`${val} conversas`, ""]} labelFormatter={dm} />
                    <Area type="monotone" dataKey="conv" stroke="url(#dConvStroke)" strokeWidth={2.25} fill="url(#dConv)" dot={false} activeDot={{ r: 4, fill: "#00bc33", stroke: "#fff", strokeWidth: 2 }} isAnimationActive animationDuration={1000} animationEasing="ease-out" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </Tile>

            <Tile className="p-5 flex flex-col flex-1" delay={0.12}>
              <PanelHead title="Consumo — tokens/dia" icon={Zap} iconColor="#8b5cf6" />
              <div className="flex-1 min-h-[200px] mt-2 -mx-2" style={{ filter: "drop-shadow(0 5px 10px rgba(139,92,246,.14))" }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={series} margin={{ top: 6, right: 6, left: -8, bottom: 0 }}>
                    <defs><linearGradient id="dBar" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#c4a5fb" /><stop offset="45%" stopColor="#a855f7" /><stop offset="100%" stopColor="#7c3aed" /></linearGradient></defs>
                    <XAxis dataKey="date" tickLine={false} axisLine={false} tick={{ fontSize: 10, fill: "#98A2B3" }} minTickGap={40} tickFormatter={dm} />
                    <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 10, fill: "#98A2B3" }} width={34} tickFormatter={(n) => fmtK(Number(n))} />
                    <Tooltip cursor={{ fill: "rgba(139,92,246,.07)" }} contentStyle={{ background: "#fff", border: "1px solid #E2E8F0", borderRadius: "0.6rem", fontSize: 11 }}
                      formatter={(val: any, _n: any, item: any) => [admin ? `${fmtBr(Number(val))} · ${formatUSD(item?.payload?.custo_usd)}` : fmtBr(Number(val)), "Tokens"]} labelFormatter={dm} />
                    <Bar dataKey="tokens" fill="url(#dBar)" radius={[4, 4, 0, 0]} maxBarSize={14} isAnimationActive animationDuration={850} animationEasing="ease-out" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Tile>
          </div>

          {/* Sub-coluna direita: Consumo da IA (cima) + Status (baixo) */}
          {carteira.dados ? (
            <div className="md:col-span-5 flex flex-col gap-3">
              <SaldoCenter carteira={carteira.dados} admin={admin} />
              <StatusPanel className="flex-1" total={totalConv} donutDelta={v.conversas_variacao} items={statusItems} ops={ops} countKey={`${escritorio}-status`} />
            </div>
          ) : null}
        </div>

        {/* Atividades recentes — coluna à direita */}
        <div className="lg:col-span-4 flex flex-col gap-3">
          {!carteira.dados && <StatusPanel total={totalConv} donutDelta={v.conversas_variacao} items={statusItems} ops={ops} countKey={`${escritorio}-status`} />}
          <ActivityFeed className="flex-1" items={activities} onRefresh={() => { metricas.recarregar(); inicio.recarregar(); passos.recarregar(); }} atualizando={metricas.carregando}
            verTodas={podeGerir ? "/meus-produtos" : null} />
        </div>
      </div>

      {/* Linha 4: mini-cards + ranking + banner (esquerda) | Contatos por Estado (direita) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-3 mt-3 items-stretch">
        <div className="lg:col-span-8 flex flex-col gap-3">
          {/* Ranking + Banner */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-3 flex-1">
            <Tile className="lg:col-span-7 p-5 flex flex-col" delay={0.2}>
              <PanelHead title="Desempenho dos Agentes" icon={Trophy} iconColor="#d97706" action={podeGerir ? "Ver agentes" : undefined} to="/meus-produtos" />
              {v.ranking_agentes.filter((a) => a.conversas > 0).length === 0 ? (
                <div className="text-[12px] text-[#98A2B3] py-5">{v.agentes_total === 0 ? "Nenhum agente criado ainda." : `Nenhuma conversa nos últimos ${v.dias} dias.`}</div>
              ) : (
                <div className="mt-3 flex flex-col gap-3.5">
                  {v.ranking_agentes.map((a, i) => {
                    const inicial = (a.nome || "?").charAt(0).toUpperCase();
                    return (
                      <div key={a.id} className="grid grid-cols-[160px_1fr_auto] sm:grid-cols-[190px_1fr_84px_50px] items-center gap-3">
                        <div className="flex items-center gap-2.5 min-w-0">
                          <span className="text-[11px] font-bold text-[#cbd5e1] tabular-nums w-3 text-right shrink-0">{i + 1}</span>
                          <div className="size-9 rounded-full grid place-items-center text-[13px] font-bold text-white shrink-0" style={{ background: CORES_AGENTES[i % CORES_AGENTES.length] }}>{inicial}</div>
                          <div className="min-w-0">
                            <div className="text-[13px] font-semibold text-[#101828] truncate leading-tight">{a.nome}</div>
                            <div className="text-[11px] text-[#98A2B3] truncate">{a.conversas} {a.conversas === 1 ? "conversa" : "conversas"} · {a.situacao === "ativo" ? (a.modo === "producao" ? "ativo" : "em teste") : "pausado"}</div>
                          </div>
                        </div>
                        <div className="h-2 rounded-full bg-[#edf2f7] overflow-hidden"><div className="h-full rounded-full" style={{ width: `${Math.round((a.conversas / maxAgent) * 100)}%`, background: "linear-gradient(90deg,#00bc33,#73e793)" }} /></div>
                        <span className="text-[12px] text-[#667085] tabular-nums text-right whitespace-nowrap">{a.assinados} assin.</span>
                        {a.variacao != null ? (
                          <span className={`hidden sm:inline-flex items-center justify-end gap-0.5 text-[11px] font-semibold ${a.variacao >= 0 ? "text-[#16a34a]" : "text-[#dc2626]"}`}>
                            {a.variacao >= 0 ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />}{Math.abs(a.variacao)}%
                          </span>
                        ) : <span className="hidden sm:block" />}
                      </div>
                    );
                  })}
                </div>
              )}
            </Tile>

            <BorderGlow className="lg:col-span-5" backgroundColor="#04140a" borderRadius={20} glowColor="142 72 52" glowIntensity={1.15} glowRadius={32} coneSpread={22} colors={["#22c55e", "#4ade80", "#16a34a"]} animated>
              <div className="relative h-full p-6 flex flex-col overflow-hidden" style={{ background: "radial-gradient(120% 80% at 115% -5%, rgba(34,197,94,.20), transparent 50%), linear-gradient(160deg,#0a2e1a 0%,#04140a 70%)" }}>
                {/* brilho verde sutil */}
                <div className="absolute -left-12 top-10 size-44 rounded-full bg-[#22c55e]/15 blur-3xl pointer-events-none" />
                {/* título */}
                <h3 className="relative text-white font-extrabold text-[21px] leading-[1.15] tracking-tight flex items-start gap-2"><Sparkles className="size-5 text-[#4ade80] shrink-0 mt-0.5" /> <span>Atendimento com <span className="text-[#34e06b]">inteligência artificial</span></span></h3>
                <p className="relative text-white/65 text-[12.5px] mt-2 leading-relaxed max-w-[21rem]">Automatize conversas, responda mais rápido e aumente suas conversões.</p>
                {/* features */}
                <div className="relative mt-4 space-y-2">
                  {AI_FEATURES.map((f) => (
                    <div key={f.title} className="flex items-center gap-3 p-2.5 rounded-xl border border-white/10 bg-white/[0.04] backdrop-blur-sm">
                      <div className="size-9 rounded-lg grid place-items-center border border-[#22c55e]/30 bg-[#22c55e]/10 text-[#4ade80] shrink-0"><f.icon className="size-4" /></div>
                      <div className="min-w-0">
                        <div className="text-white font-semibold text-[12.5px] leading-tight">{f.title}</div>
                        <div className="text-white/50 text-[11px] leading-snug mt-0.5">{f.desc}</div>
                      </div>
                    </div>
                  ))}
                </div>
                {/* CTA */}
                <Link to="/biblioteca" className="lc-pay-btn relative mt-4 inline-flex items-center justify-center gap-1.5 h-11 px-5 rounded-xl font-bold text-[13px] text-white w-full sm:w-fit">Explorar recursos <ArrowUpRight className="size-4" /></Link>
                <Link to="/biblioteca" className="relative mt-3 self-start inline-flex items-center gap-1.5 text-white/55 hover:text-white text-[12px] font-medium transition-colors"><PlayCircle className="size-4 text-[#4ade80]" /> Ver como funciona</Link>
              </div>
            </BorderGlow>
          </div>
        </div>

        <ContatosPorEstado className="lg:col-span-4 h-full" leads={v.uf.leads} contratos={v.uf.contratos} />
      </div>

      {/* Funil do agente */}
      <div className="mt-3"><PainelFunil /></div>
    </div>
  );
}

/* ---------------- helpers ---------------- */

const Tile = ({ className = "", delay = 0, children }: { className?: string; delay?: number; children: React.ReactNode }) => (
  <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay, ease: [0.22, 1, 0.36, 1] }} className={`${TILE} ${className}`}>
    {children}
  </motion.div>
);

const PanelHead = ({ title, icon: Icon, iconColor, action, actionIcon: ActionIcon = ChevronRight, to }: { title: string; icon?: any; iconColor?: string; action?: string; actionIcon?: any; to?: string }) => (
  <div className="flex items-center justify-between">
    <h3 className="font-semibold text-[15px] tracking-tight text-[#101828] flex items-center gap-1.5">
      {Icon && <Icon className="size-4" style={{ color: iconColor }} />} {title}
    </h3>
    {action && to && (
      <Link to={to} className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-[#E2E8F0] bg-white text-[12px] font-semibold text-[#344054] hover:text-[#101828] transition-colors">
        {action} <ActionIcon className="size-3.5" />
      </Link>
    )}
  </div>
);
