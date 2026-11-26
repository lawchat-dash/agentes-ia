import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useReducedMotion } from "framer-motion";
import {
  Activity, ArrowDownLeft, ArrowDownRight, ArrowRight, ArrowUpRight, BarChart3, BookOpen, Bot, Calendar, CheckCircle2, ChevronLeft,
  ChevronRight, CircleDollarSign, Coins, Cpu, Download, FileSignature, Gauge, Gift, HeartPulse, History, Info, MessageSquare,
  Receipt, Sparkles, Target, Trophy, TrendingUp, Users, Wallet, XCircle, AlertTriangle,
} from "lucide-react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import walletImg from "@/assets/wallet-finance.png";
import { quando } from "../api";
import { useCarregar } from "../componentes/ui";
import { useSessao } from "../sessao";
import { ListaRecargas, PedirRecarga, reais, type Movimento, type Recarga } from "./Carteira";

/*
 * Créditos & Consumo (cliente, /consumo). Foco: quantos leads o saldo atende. Tudo em R$ cobrado (o que sai da
 * carteira, já com o markup); nada de US$. Só dados reais: quando é estimativa, a tela diz; sem dado, estado vazio.
 * Dados: /carteira/painel (uma ida), /carteira/conversas, /carteira/recargas e /carteira/extrato.
 */

interface Agente {
  id_agente: string | null; agente: string; valor_brl: number; tokens: number; chamadas: number; conversas: number; contratos: number;
  custo_por_lead_brl: number | null; custo_por_contrato_brl: number | null; conversao_pct: number | null; participacao_pct: number;
}
interface PainelConsumo {
  dias: number; granularidade: "hora" | "dia";
  carteira: { disponivel_brl: number; saldo_brl: number; bonus_brl: number; bonus_do_mes_brl: number; bonus_usado_pct: number | null;
    consumo_mes_brl: number; modo: string; bloqueado: boolean; pausado_por_saldo: boolean; plano: string | null; mes: string };
  custo_por_lead: { valor_brl: number | null; fonte: "periodo" | "historico_90d" | "referencia_modelo" | null; estimativa: boolean;
    leads_com_saldo: number | null };
  totais: { creditos_brl: number; chamadas: number; tokens: number; tokens_entrada: number; tokens_saida: number; tokens_cache: number;
    conversas: number; contratos: number; custo_por_conversa_brl: number | null; custo_por_contrato_brl: number | null; conversao_pct: number | null };
  serie: { quando: string; valor_brl: number; tokens: number; conversas: number }[];
  por_funcao: { papel: string; nome: string; valor_brl: number; chamadas: number; tokens: number }[];
  por_agente: Agente[];
  comparativo: { ultimos_7_brl: number; anteriores_7_brl: number; ultimos_30_brl: number };
  media_dia_brl: number | null;
  creditos: { recargas_brl: number; recargas: number; bonus_brl: number; bonus: number; outros_brl: number;
    por_mes: { mes: string; recargas_brl: number; bonus_brl: number }[] };
}
interface Conversa {
  id_lead: string; valor_brl: number; tokens: number; chamadas: number; turnos: number; mensagens: number; primeiro_em: string; ultimo_em: string;
  contato: string | null; telefone: string | null; agente: string; id_agente: string | null; contrato_assinado: boolean;
}
interface Conversas { total: number; conversas: Conversa[] }

const VERDE = "#00bc33";
const PERIODOS = [{ d: 1, r: "24h" }, { d: 7, r: "7d" }, { d: 30, r: "30d" }, { d: 90, r: "90d" }];
const ABAS = [{ id: "visao", r: "Visão Geral" }, { id: "agentes", r: "Por agente" }, { id: "historico", r: "Histórico" },
  { id: "recargas", r: "Recargas" }, { id: "avancado", r: "Avançado" }] as const;
type Aba = (typeof ABAS)[number]["id"];
const nomePeriodo = (d: number) => (d === 1 ? "nas últimas 24 horas" : `nos últimos ${d} dias`);
/** Valores pequenos (custo de um lead) com mais casas, para não virar "R$ 0,00". */
const rs = (v: number | null | undefined) => (v == null ? "—" : reais(v, Math.abs(v) > 0 && Math.abs(v) < 0.1 ? 4 : 2));
const inteiro = (v: number | null | undefined) => (v ?? 0).toLocaleString("pt-BR");
const pct = (v: number | null | undefined) => `${(v ?? 0).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`;
const compacto = (v: number) => v.toLocaleString("pt-BR", { notation: "compact", maximumFractionDigits: 1 });

// ============================================================================ tela
export function TelaCreditos() {
  const { escritorio } = useSessao();
  const [busca, setBusca] = useSearchParams();
  const aba = (ABAS.some((a) => a.id === busca.get("aba")) ? busca.get("aba") : "visao") as Aba;
  const irPara = (nova: Aba) => setBusca((b) => { const n = new URLSearchParams(b); n.set("aba", nova); return n; }, { replace: true });
  const [dias, setDias] = useState(30);
  const painel = useCarregar<PainelConsumo>(`/carteira/painel?dias=${dias}`, [escritorio, dias]);
  const caras = useCarregar<Conversas>(`/carteira/conversas?dias=${dias}&ordem=custo&limite=10`, [escritorio, dias]);
  const recargas = useCarregar<Recarga[]>("/carteira/recargas", [escritorio]);
  const [pedir, setPedir] = useState<number | null>(null);
  const aposPedir = () => { painel.recarregar(); recargas.recarregar(); };

  const p = painel.dados;
  return (
    <div className="cr-tela mx-auto w-full max-w-[1320px] pb-10">
      <Topo p={p} aoRecarregar={() => setPedir(300)} />

      {p?.carteira.bloqueado && (
        <Faixa tom="bad" icone={<XCircle />} titulo="A IA está pausada: o saldo acabou">
          As mensagens novas ficam com a sua equipe. Assim que a recarga for confirmada, a IA volta a responder sozinha.
        </Faixa>
      )}
      {(recargas.dados ?? []).some((r) => r.situacao === "pendente") && (
        <Faixa tom="warn" icone={<Receipt />} titulo="Você tem recarga aguardando pagamento">
          <button className="underline font-semibold" onClick={() => irPara("recargas")}>Ver na aba Recargas</button>
        </Faixa>
      )}

      {p ? <Destaque p={p} dias={dias} aoRecarregar={setPedir} /> : <Esqueleto altura={220} erro={painel.erro} />}

      {/* Abas + período + exportar */}
      <div className="mt-6 mb-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1" role="tablist" aria-label="Seções">
          {ABAS.map((a) => (
            <button key={a.id} role="tab" aria-selected={aba === a.id} onClick={() => irPara(a.id)}
              className={`shrink-0 rounded-full border px-4 py-2 text-[13px] font-semibold transition ${aba === a.id
                ? "border-transparent bg-[#00bc33] text-white shadow-[0_6px_18px_-6px_rgba(0,188,51,.6)]"
                : "border-[#e4e7ec] bg-white text-[#344054] hover:border-[#00bc33]/50"}`}>{a.r}</button>
          ))}
        </div>
        <div className="flex items-center gap-1 self-start rounded-full border border-[#e4e7ec] bg-white p-1 lg:self-auto">
          <div role="radiogroup" aria-label="Período" className="flex">
            {PERIODOS.map(({ d, r }) => (
              <button key={d} role="radio" aria-checked={dias === d} onClick={() => setDias(d)}
                className={`rounded-full px-3 py-1.5 text-[12px] font-semibold transition ${dias === d ? "bg-[#101828] text-white" : "text-[#667085] hover:text-[#101828]"}`}>{r}</button>
            ))}
          </div>
          <span className="mx-1 h-5 w-px bg-[#e4e7ec]" />
          <button disabled={!p} onClick={() => p && exportarCsv(p, caras.dados, dias)}
            className="inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[12px] font-semibold text-[#344054] hover:text-[#00bc33] disabled:opacity-40">
            <Download className="size-3.5" />Exportar
          </button>
        </div>
      </div>

      {!p ? <Esqueleto altura={320} erro={painel.erro} /> : (
        <div key={aba} className="cr-entra">
          {aba === "visao" && <VisaoGeral p={p} dias={dias} caras={caras.dados} erroCaras={caras.erro} irPara={irPara} recargas={recargas.dados} aoRecarregar={setPedir} />}
          {aba === "agentes" && <PorAgente p={p} dias={dias} />}
          {aba === "historico" && <Historico dias={dias} />}
          {aba === "recargas" && <Recargas p={p} dias={dias} recargas={recargas.dados} erro={recargas.erro} aoMudar={aposPedir} />}
          {aba === "avancado" && <Avancado p={p} aoRecarregar={setPedir} />}
        </div>
      )}
      {pedir != null && <PedirRecarga valorInicial={pedir} aoFechar={() => setPedir(null)} aoPedir={aposPedir} />}
    </div>
  );
}

// ============================================================================ topo e destaque
function Topo({ p, aoRecarregar }: { p: PainelConsumo | null; aoRecarregar: () => void }) {
  const c = p?.carteira;
  const cor = !c ? "#98A2B3" : c.bloqueado ? "#ef4444" : nivelSaldo(p!) === "baixo" ? "#f59e0b" : VERDE;
  return (
    <header className="mb-5 flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
      <div className="flex items-center gap-4">
        <img src={walletImg} alt="" className="size-16 shrink-0 object-contain drop-shadow-[0_10px_18px_rgba(0,188,51,.3)] md:size-20" />
        <div className="min-w-0">
          <span className="inline-block rounded-md bg-[#e8f9ee] px-2 py-0.5 text-[10px] font-bold tracking-[.12em] text-[#00a02b]">CRÉDITOS</span>
          <h1 className="mt-1 text-[26px] font-bold leading-tight tracking-tight text-[#101828] md:text-[30px]">Créditos &amp; Consumo</h1>
          <p className="mt-1 max-w-xl text-[13.5px] text-[#667085]">Veja quantos leads seu saldo atende, quanto cada agente gasta e para onde vão seus créditos. Créditos de recarga não expiram.</p>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-3 rounded-2xl border border-[#e4e7ec] bg-white px-4 py-2.5 shadow-sm">
          <span className="grid size-9 place-items-center rounded-xl bg-[#e8f9ee] text-[#00bc33]"><Wallet className="size-4" /></span>
          <div>
            <div className="text-[11px] text-[#667085]">Saldo disponível</div>
            <div className="text-[18px] font-bold tabular-nums text-[#101828]">{c ? reais(c.disponivel_brl) : "—"}</div>
          </div>
          <span className="ml-1 size-2.5 rounded-full" style={{ background: cor, boxShadow: `0 0 0 4px ${cor}22` }} aria-hidden />
        </div>
        <button onClick={aoRecarregar}
          className="inline-flex items-center gap-2 rounded-2xl bg-[#00bc33] px-5 py-3 text-[14px] font-semibold text-white shadow-[0_10px_24px_-10px_rgba(0,188,51,.8)] transition hover:bg-[#00a82e] active:scale-[.98]">
          <Sparkles className="size-4" />Recarregar créditos<ArrowUpRight className="size-4" />
        </button>
      </div>
    </header>
  );
}

function nivelSaldo(p: PainelConsumo): "pausado" | "baixo" | "ok" | "sem_ritmo" {
  if (p.carteira.bloqueado) return "pausado";
  const dias = diasDeAutonomia(p);
  if (dias == null) return "sem_ritmo";
  return dias < 7 ? "baixo" : "ok";
}
const diasDeAutonomia = (p: PainelConsumo) =>
  p.media_dia_brl && p.media_dia_brl > 0 ? Math.max(0, p.carteira.disponivel_brl) / p.media_dia_brl : null;

function textoFonte(p: PainelConsumo, dias: number) {
  const cpl = p.custo_por_lead;
  if (cpl.fonte === "periodo") return <>pelo custo médio real de <b className="text-[#101828]">{rs(cpl.valor_brl)} por lead</b> {nomePeriodo(dias)}</>;
  if (cpl.fonte === "historico_90d") return <>pelo seu custo médio real de <b className="text-[#101828]">{rs(cpl.valor_brl)} por lead</b> nos últimos 90 dias</>;
  if (cpl.fonte === "referencia_modelo") return <><b className="text-[#b54708]">Estimativa:</b> você ainda não tem histórico, então usamos o custo médio por lead de escritórios com o mesmo modelo de IA dos seus agentes (<b className="text-[#101828]">{rs(cpl.valor_brl)} por lead</b>, já no seu preço).</>;
  return null;
}

/** O número principal da tela: quantos leads o saldo atende (e por quantos dias, no ritmo atual). */
function Destaque({ p, dias, aoRecarregar }: { p: PainelConsumo; dias: number; aoRecarregar: (v: number) => void }) {
  const c = p.carteira;
  const cpl = p.custo_por_lead;
  const autonomia = diasDeAutonomia(p);
  const nivel = nivelSaldo(p);
  const selo = {
    pausado: { t: "IA pausada por saldo", cor: "#b42318", fundo: "#fef3f2", icone: <XCircle className="size-3.5" /> },
    baixo: { t: "Saldo baixo: recarregue logo", cor: "#b54708", fundo: "#fffaeb", icone: <AlertTriangle className="size-3.5" /> },
    ok: { t: "Operação saudável", cor: "#067647", fundo: "#ecfdf3", icone: <CheckCircle2 className="size-3.5" /> },
    sem_ritmo: { t: "Sem consumo recente", cor: "#475467", fundo: "#f2f4f7", icone: <Info className="size-3.5" /> },
  }[nivel];
  return (
    <section className="lc-hero relative overflow-hidden p-5 md:p-7">
      <div aria-hidden className="pointer-events-none absolute -right-16 -top-16 size-64 rounded-full bg-[#00bc33]/10 blur-3xl" />
      <div className="relative grid gap-6 lg:grid-cols-[1.25fr_1fr]">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[13px] font-medium text-[#475467]">Saldo disponível</span>
            <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11.5px] font-semibold" style={{ color: selo.cor, background: selo.fundo }}>{selo.icone}{selo.t}</span>
          </div>
          <div className="mt-1 text-[38px] font-extrabold leading-none tracking-tight tabular-nums md:text-[46px]" style={{ color: c.disponivel_brl > 0 ? VERDE : "#d92d20" }}>
            <Contador valor={c.disponivel_brl} formato={(v) => reais(v)} />
          </div>
          {c.bonus_do_mes_brl > 0 && (
            <div className="mt-3 max-w-md">
              <div className="flex justify-between text-[12px] text-[#667085]"><span>Bônus do mês: {reais(c.bonus_brl)} restantes</span><span>{pct(c.bonus_usado_pct ?? 0)} usado</span></div>
              <Barra pct={c.bonus_usado_pct ?? 0} cor={(c.bonus_usado_pct ?? 0) >= 80 ? "#f59e0b" : VERDE} />
            </div>
          )}

          <div className="mt-5 rounded-2xl border border-[#d1fadf] bg-white/80 p-4 md:p-5">
            {cpl.leads_com_saldo != null ? (
              <>
                <div className="flex items-center gap-2 text-[13px] font-semibold text-[#067647]"><Users className="size-4" />Seu saldo atende cerca de</div>
                <div className="mt-1 flex flex-wrap items-baseline gap-x-3">
                  <span className="text-[44px] font-extrabold leading-none tracking-tight text-[#101828] tabular-nums md:text-[56px]">
                    {cpl.estimativa && "≈ "}<Contador valor={cpl.leads_com_saldo} formato={(v) => inteiro(Math.round(v))} />
                  </span>
                  <span className="text-[20px] font-bold text-[#101828]">leads</span>
                  {autonomia != null && (
                    <span className="text-[14px] font-medium text-[#475467]">≈ {formatarDias(autonomia)} no seu ritmo atual</span>
                  )}
                </div>
                <p className="mt-2 text-[12.5px] leading-relaxed text-[#667085]">{textoFonte(p, dias)}</p>
              </>
            ) : (
              <div className="flex items-start gap-3">
                <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-[#e8f9ee] text-[#00bc33]"><Users className="size-5" /></span>
                <div>
                  <div className="text-[15px] font-semibold text-[#101828]">Quantos leads seu saldo atende?</div>
                  <p className="text-[13px] text-[#667085]">Assim que seus agentes atenderem os primeiros leads, mostramos aqui quantos leads o seu saldo paga, com o custo real do seu escritório.</p>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 self-start">
          <MiniDado icone={<Target />} rotulo="Custo médio por lead" valor={rs(cpl.valor_brl)} nota={cpl.estimativa && cpl.valor_brl != null ? "estimativa" : cpl.fonte === "historico_90d" ? "últimos 90 dias" : nomePeriodo(dias)} />
          <MiniDado icone={<Calendar />} rotulo="Autonomia estimada" valor={autonomia != null ? formatarDias(autonomia) : "—"} nota={p.media_dia_brl ? `gasto médio ${rs(p.media_dia_brl)}/dia` : "sem consumo nos últimos 30 dias"} />
          <Comparativo atual={p.comparativo.ultimos_7_brl} antes={p.comparativo.anteriores_7_brl} />
          <MiniDado icone={<CircleDollarSign />} rotulo="Consumo do mês" valor={reais(c.consumo_mes_brl)} nota={c.plano ? `plano ${c.plano}` : "desde o dia 1º"} />
          <div className="col-span-2 flex flex-wrap gap-2">
            {[50, 150, 500].map((v) => (
              <button key={v} onClick={() => aoRecarregar(v)}
                className="flex-1 rounded-xl border border-[#d1fadf] bg-white px-3 py-2 text-left text-[12px] text-[#475467] transition hover:border-[#00bc33] hover:shadow-sm">
                <div className="font-bold text-[#101828]">{reais(v, 0)}</div>
                <div>{cpl.valor_brl ? `≈ ${inteiro(Math.floor(v / cpl.valor_brl + 1e-9))} leads` : "recarregar"}</div>
              </button>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function Comparativo({ atual, antes }: { atual: number; antes: number }) {
  const pct = antes > 0 ? ((atual - antes) / antes) * 100 : null;
  const subiu = pct != null && pct > 0;
  return (
    <MiniDado icone={subiu ? <ArrowUpRight /> : <ArrowDownRight />} rotulo="Últimos 7 dias" valor={reais(atual)}
      nota={pct == null ? (atual > 0 ? "sem semana anterior para comparar" : "sem consumo") : `${subiu ? "+" : ""}${pct.toFixed(0)}% vs. semana anterior`}
      tom={pct == null ? undefined : subiu ? "warn" : "ok"} />
  );
}

// ============================================================================ Visão Geral
function VisaoGeral({ p, dias, caras, erroCaras, irPara, recargas, aoRecarregar }: {
  p: PainelConsumo; dias: number; caras: Conversas | null; erroCaras: string | null; irPara: (a: Aba) => void;
  recargas: Recarga[] | null; aoRecarregar: (v: number) => void;
}) {
  const t = p.totais;
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <Kpi icone={<TrendingUp />} cor="green" rotulo="Créditos usados" valor={<Contador valor={t.creditos_brl} formato={(v) => reais(v)} />} nota={nomePeriodo(dias)} />
        <Kpi icone={<Users />} cor="blue" rotulo="Leads atendidos" valor={<Contador valor={t.conversas} formato={(v) => inteiro(Math.round(v))} />} nota="conversas com a IA no período" />
        <Kpi icone={<Target />} cor="amber" rotulo="Custo médio por lead" valor={rs(t.custo_por_conversa_brl)} nota={t.conversas ? `${inteiro(t.conversas)} leads no período` : "sem leads no período"} />
        <Kpi icone={<Coins />} cor="violet" rotulo="Tokens consumidos" valor={<Contador valor={t.tokens} formato={(v) => compacto(Math.round(v))} />} nota={`${inteiro(t.chamadas)} chamadas da IA`} />
        <Kpi icone={<FileSignature />} cor="green" rotulo="Contratos assinados" valor={inteiro(t.contratos)}
          nota={t.contratos ? `${rs(t.custo_por_contrato_brl)} por contrato · ${pct(t.conversao_pct)} conversão` : "sem contratos assinados no período"} />
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
        <Cartao icone={<Activity />} titulo="Consumo ao longo do tempo" sub="Quanto a IA gastou em cada dia do período." direita={<span className="text-[12px] text-[#667085]"><span className="mr-1 inline-block size-2 rounded-full bg-[#00bc33]" />R$ cobrado</span>}>
          <GraficoConsumo p={p} dias={dias} />
        </Cartao>
        <Cartao icone={<Bot />} titulo="Consumo por agente" sub="Quanto cada agente gastou e quantos leads atendeu." direita={<BotaoTexto onClick={() => irPara("agentes")}>Detalhes</BotaoTexto>}>
          {p.por_agente.length === 0 ? <Vazio icone={<Users />}>Nenhum agente consumiu neste período.</Vazio> : (
            <ul className="flex flex-col gap-3.5">
              {p.por_agente.slice(0, 5).map((a) => (
                <li key={a.id_agente ?? "sem"}>
                  <div className="flex items-baseline justify-between gap-2 text-[13px]">
                    <span className="truncate font-semibold text-[#101828]">{a.agente}</span>
                    <span className="shrink-0 font-bold tabular-nums text-[#101828]">{reais(a.valor_brl)}</span>
                  </div>
                  <Barra pct={a.participacao_pct} cor={VERDE} />
                  <div className="mt-1 flex justify-between text-[11.5px] text-[#667085]">
                    <span>{inteiro(a.conversas)} leads · {rs(a.custo_por_lead_brl)} por lead</span><span>{pct(a.participacao_pct)}</span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Cartao>
      </div>

      <TabelaConversas titulo="Conversas que mais gastaram" sub={`As 10 conversas com mais consumo ${nomePeriodo(dias)}.`} dados={caras} erro={erroCaras}
        direita={<BotaoTexto onClick={() => irPara("historico")}>Ver histórico</BotaoTexto>} />

      <div className="grid gap-4 lg:grid-cols-2">
        <Cartao icone={<Sparkles />} titulo="Consumo por função" sub="Para onde foram seus créditos.">
          <PorFuncao p={p} />
        </Cartao>
        <Simulador p={p} aoRecarregar={aoRecarregar} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Saude p={p} />
        <Cartao icone={<Receipt />} titulo="Últimas recargas" direita={<BotaoTexto onClick={() => irPara("recargas")}>Ver todas</BotaoTexto>}>
          {!recargas ? <Linhas /> : recargas.length === 0 ? <Vazio icone={<Receipt />}>Nenhuma recarga ainda.</Vazio> : (
            <ul className="divide-y divide-[#f2f4f7]">
              {recargas.slice(0, 4).map((r) => (
                <li key={r.id} className="flex items-center justify-between gap-2 py-2.5 text-[13px]">
                  <span className="text-[#667085]">{dataCurta(r.criado_em)}</span>
                  <span className="ml-auto font-semibold tabular-nums text-[#101828]">{reais(r.valor_brl)}</span>
                  <SeloSituacao s={r.situacao} />
                </li>
              ))}
            </ul>
          )}
        </Cartao>
      </div>
      <ComoFunciona />
    </div>
  );
}

function GraficoConsumo({ p, dias }: { p: PainelConsumo; dias: number }) {
  const dados = useMemo(() => preencherSerie(p, dias), [p, dias]);
  if (p.totais.creditos_brl === 0) return <Vazio icone={<Activity />}>Sem consumo registrado neste período.</Vazio>;
  return (
    <div className="h-[240px] w-full">
      <ResponsiveContainer>
        <AreaChart data={dados} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="crArea" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={VERDE} stopOpacity={0.32} /><stop offset="100%" stopColor={VERDE} stopOpacity={0} /></linearGradient>
          </defs>
          <CartesianGrid stroke="#f2f4f7" vertical={false} />
          <XAxis dataKey="rotulo" tick={{ fontSize: 11, fill: "#98A2B3" }} tickLine={false} axisLine={false} minTickGap={18} />
          <YAxis tick={{ fontSize: 11, fill: "#98A2B3" }} tickLine={false} axisLine={false} width={58} tickFormatter={(v) => reais(v, v < 1 ? 2 : 0)} />
          <Tooltip cursor={{ stroke: "#d0d5dd" }} contentStyle={{ borderRadius: 12, border: "1px solid #e4e7ec", fontSize: 12 }}
            formatter={(v: number, _n, item: any) => [`${rs(v)} · ${inteiro(item?.payload?.conversas)} leads`, "Consumo"]} labelFormatter={(l) => l} />
          <Area type="monotone" dataKey="valor_brl" stroke={VERDE} strokeWidth={2.2} fill="url(#crArea)" animationDuration={700} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function PorFuncao({ p }: { p: PainelConsumo }) {
  const total = p.por_funcao.reduce((s, f) => s + f.valor_brl, 0);
  if (!total) return <Vazio icone={<Sparkles />}>Sem consumo por função neste período.</Vazio>;
  const cores = [VERDE, "#2e90fa", "#7a5af8", "#f79009", "#ee46bc", "#15b79e", "#98A2B3"];
  return (
    <ul className="flex flex-col gap-3">
      {p.por_funcao.slice(0, 7).map((f, i) => (
        <li key={f.papel}>
          <div className="flex justify-between gap-2 text-[13px]"><span className="text-[#344054]">{f.nome}</span>
            <span className="tabular-nums font-semibold text-[#101828]">{rs(f.valor_brl)} <span className="font-normal text-[#98A2B3]">· {Math.round((f.valor_brl / total) * 100)}%</span></span></div>
          <Barra pct={(f.valor_brl / total) * 100} cor={cores[i % cores.length]} />
          <div className="mt-0.5 text-[11px] text-[#98A2B3]">{inteiro(f.chamadas)} chamadas · {compacto(f.tokens)} tokens</div>
        </li>
      ))}
    </ul>
  );
}

/** Quanto uma recarga compra: leads (pelo custo médio por lead) e dias (pelo gasto médio por dia). */
function Simulador({ p, aoRecarregar }: { p: PainelConsumo; aoRecarregar: (v: number) => void }) {
  const [valor, setValor] = useState(150);
  const cpl = p.custo_por_lead.valor_brl;
  const leads = cpl ? Math.floor(valor / cpl + 1e-9) : null;
  const dias = p.media_dia_brl ? valor / p.media_dia_brl : null;
  return (
    <Cartao icone={<Gauge />} titulo="Simulador de recarga" sub="Veja quantos leads e quantos dias uma recarga compra.">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-[#98A2B3]">Recarregar</span>
        <span className="text-[30px] font-extrabold tabular-nums text-[#101828]">{reais(valor)}</span>
      </div>
      <input type="range" min={10} max={2000} step={10} value={valor} onChange={(e) => setValor(Number(e.target.value))}
        aria-label="Valor da recarga" className="cr-range mt-2 w-full" style={{ ["--pct" as any]: `${((valor - 10) / 1990) * 100}%` }} />
      <div className="mt-1 flex justify-between text-[11px] text-[#98A2B3]"><span>R$ 10</span><span>R$ 2.000</span></div>
      <div className="mt-3 flex flex-wrap gap-2">
        {[50, 150, 500, 1000].map((v) => (
          <button key={v} onClick={() => setValor(v)}
            className={`rounded-full border px-3 py-1 text-[12px] font-semibold transition ${valor === v ? "border-[#00bc33] bg-[#e8f9ee] text-[#067647]" : "border-[#e4e7ec] text-[#475467] hover:border-[#00bc33]/60"}`}>{reais(v, 0)}</button>
        ))}
      </div>
      <div className="mt-4 rounded-2xl bg-gradient-to-br from-[#ecfdf3] to-white p-4 ring-1 ring-[#d1fadf]">
        {leads != null ? (
          <>
            <div className="flex flex-wrap items-baseline gap-x-2 text-[#101828]">
              <span className="text-[15px] font-semibold">{reais(valor)}</span><span className="text-[#98A2B3]">≈</span>
              <span className="text-[26px] font-extrabold tabular-nums text-[#067647]">{inteiro(leads)} leads</span>
              {dias != null && <><span className="text-[#98A2B3]">≈</span><span className="text-[20px] font-bold tabular-nums">{formatarDias(dias)}</span></>}
            </div>
            <p className="mt-1 text-[12px] text-[#667085]">
              {p.custo_por_lead.estimativa ? "Estimativa pelo custo de referência do modelo de IA dos seus agentes. " : `Pelo seu custo médio real de ${rs(cpl)} por lead. `}
              {dias != null ? `Dias pelo seu gasto médio de ${rs(p.media_dia_brl)} por dia.` : "Sem consumo nos últimos 30 dias para estimar os dias."}
            </p>
          </>
        ) : <p className="text-[13px] text-[#667085]">Ainda sem consumo para calcular. Assim que seus agentes atenderem os primeiros leads, o simulador usa o seu custo real.</p>}
      </div>
      <button onClick={() => aoRecarregar(valor)}
        className="mt-4 w-full rounded-xl bg-[#00bc33] py-3 text-[14px] font-semibold text-white shadow-[0_10px_24px_-12px_rgba(0,188,51,.8)] transition hover:bg-[#00a82e]">
        Recarregar {reais(valor)}
      </button>
    </Cartao>
  );
}

function Saude({ p }: { p: PainelConsumo }) {
  const dias = diasDeAutonomia(p);
  const c = p.comparativo;
  const variacao = c.anteriores_7_brl > 0 ? ((c.ultimos_7_brl - c.anteriores_7_brl) / c.anteriores_7_brl) * 100 : null;
  const itens: { ok: boolean | null; texto: string }[] = [
    p.carteira.bloqueado ? { ok: false, texto: "A IA está pausada: o saldo acabou." }
      : dias == null ? { ok: null, texto: "Sem consumo nos últimos 30 dias para medir a autonomia." }
      : dias < 7 ? { ok: false, texto: `O saldo dá para ${formatarDias(dias)} no ritmo atual.` }
      : { ok: true, texto: `Saldo saudável: dá para ${formatarDias(dias)} no ritmo atual.` },
    variacao == null ? { ok: null, texto: "Ainda sem semana anterior para comparar o consumo." }
      : variacao > 50 ? { ok: false, texto: `Consumo ${variacao.toFixed(0)}% maior que na semana anterior.` }
      : { ok: true, texto: `Consumo dentro do esperado (${variacao >= 0 ? "+" : ""}${variacao.toFixed(0)}% vs. semana anterior).` },
  ];
  const topo = p.por_agente[0];
  if (topo && p.por_agente.length > 1 && topo.participacao_pct >= 70)
    itens.push({ ok: null, texto: `${topo.agente} responde por ${pct(topo.participacao_pct)} do consumo do período.` });
  const previsao = dias != null ? new Date(Date.now() + dias * 86400000) : null;
  return (
    <Cartao icone={<HeartPulse />} titulo="Saúde da operação">
      <ul className="flex flex-col gap-2.5">
        {itens.map((i, n) => (
          <li key={n} className="flex items-start gap-2 text-[13px] text-[#344054]">
            {i.ok === true ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-[#00bc33]" /> : i.ok === false ? <AlertTriangle className="mt-0.5 size-4 shrink-0 text-[#f79009]" /> : <Info className="mt-0.5 size-4 shrink-0 text-[#98A2B3]" />}
            {i.texto}
          </li>
        ))}
      </ul>
      <div className="mt-4 flex items-center justify-between rounded-xl bg-[#f9fafb] px-4 py-3">
        <div><div className="text-[11.5px] text-[#667085]">Próxima recarga prevista</div>
          <div className="text-[15px] font-bold text-[#101828]">{previsao ? previsao.toLocaleDateString("pt-BR", { day: "2-digit", month: "long", ...(previsao.getFullYear() !== new Date().getFullYear() ? { year: "numeric" } : {}) }) : "—"}</div></div>
        <Calendar className="size-5 text-[#98A2B3]" />
      </div>
    </Cartao>
  );
}

// ============================================================================ Por agente
function PorAgente({ p, dias }: { p: PainelConsumo; dias: number }) {
  const [escolhido, setEscolhido] = useState<string | null>(null);
  const agente = p.por_agente.find((a) => (a.id_agente ?? "") === escolhido) ?? null;
  const conversas = useCarregar<Conversas>(agente?.id_agente ? `/carteira/conversas?dias=${dias}&ordem=custo&limite=10&id_agente=${agente.id_agente}` : null, [escolhido, dias]);
  if (p.por_agente.length === 0)
    return <Cartao icone={<Users />} titulo="Consumo por agente" sub="Quanto cada agente gastou no período."><Vazio icone={<Users />}>Nenhum agente consumiu neste período.</Vazio></Cartao>;
  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {p.por_agente.map((a, i) => {
          const ativo = (a.id_agente ?? "") === escolhido;
          return (
            <button key={a.id_agente ?? "sem"} onClick={() => setEscolhido(ativo ? null : a.id_agente ?? "")} disabled={!a.id_agente}
              className={`lc-card relative p-5 text-left transition hover:-translate-y-0.5 ${ativo ? "ring-2 ring-[#00bc33]" : ""}`}>
              <div className="flex items-center gap-3">
                <span className="grid size-10 place-items-center rounded-xl bg-[#e8f9ee] text-[13px] font-bold text-[#067647]">{i + 1}º</span>
                <div className="min-w-0"><div className="truncate text-[15px] font-bold text-[#101828]">{a.agente}</div>
                  <div className="text-[12px] text-[#667085]">{pct(a.participacao_pct)} do consumo</div></div>
                <span className="ml-auto text-[18px] font-extrabold tabular-nums text-[#101828]">{reais(a.valor_brl)}</span>
              </div>
              <Barra pct={a.participacao_pct} cor={VERDE} />
              <div className="mt-4 grid grid-cols-3 gap-2 text-center">
                <Numero rotulo="leads" valor={inteiro(a.conversas)} />
                <Numero rotulo="R$ por lead" valor={rs(a.custo_por_lead_brl)} destaque />
                <Numero rotulo="contratos" valor={inteiro(a.contratos)} />
              </div>
              <div className="mt-3 flex flex-wrap justify-between gap-1 text-[11.5px] text-[#667085]">
                <span>{a.contratos ? `${rs(a.custo_por_contrato_brl)} por contrato · ${pct(a.conversao_pct)} conversão` : "sem contrato assinado no período"}</span>
                <span>{compacto(a.tokens)} tokens</span>
              </div>
              {a.id_agente && <div className="mt-3 text-[12px] font-semibold text-[#00a02b]">{ativo ? "Esconder conversas" : "Ver conversas que mais gastaram"} →</div>}
            </button>
          );
        })}
      </div>
      {agente && <TabelaConversas titulo={`Conversas que mais gastaram · ${agente.agente}`} sub={nomePeriodo(dias)} dados={conversas.dados} erro={conversas.erro} />}
    </div>
  );
}

// ============================================================================ Histórico
const POR_PAGINA = 25;
function Historico({ dias }: { dias: number }) {
  const [pagina, setPagina] = useState(0);
  useEffect(() => setPagina(0), [dias]);
  const r = useCarregar<Conversas>(`/carteira/conversas?dias=${dias}&ordem=recente&limite=${POR_PAGINA}&deslocamento=${pagina * POR_PAGINA}`, [dias, pagina]);
  const total = r.dados?.total ?? 0;
  const paginas = Math.max(1, Math.ceil(total / POR_PAGINA));
  return (
    <TabelaConversas titulo="Histórico" sub={`${inteiro(total)} conversas com consumo ${nomePeriodo(dias)}, das mais recentes para as mais antigas.`} dados={r.dados} erro={r.erro}
      rodape={total > POR_PAGINA && (
        <div className="flex items-center justify-end gap-2 px-4 py-3 text-[12.5px] text-[#667085]">
          <button className="cr-pag" disabled={pagina === 0} onClick={() => setPagina(pagina - 1)} aria-label="Página anterior"><ChevronLeft className="size-4" /></button>
          <span>Página {pagina + 1} de {paginas}</span>
          <button className="cr-pag" disabled={pagina + 1 >= paginas} onClick={() => setPagina(pagina + 1)} aria-label="Próxima página"><ChevronRight className="size-4" /></button>
        </div>
      )} />
  );
}

function TabelaConversas({ titulo, sub, dados, erro, direita, rodape }: {
  titulo: string; sub?: string; dados: Conversas | null; erro?: string | null; direita?: ReactNode; rodape?: ReactNode;
}) {
  return (
    <section className="lc-card relative overflow-hidden">
      <div className="flex items-center justify-between gap-3 px-5 pb-3 pt-5">
        <div className="flex items-center gap-3">
          <Icone><MessageSquare /></Icone>
          <div><h3 className="text-[15px] font-bold text-[#101828]">{titulo}</h3>{sub && <p className="text-[12px] text-[#667085]">{sub}</p>}</div>
        </div>
        {direita}
      </div>
      {!dados ? <div className="px-5 pb-5"><Linhas erro={erro} /></div> : dados.conversas.length === 0 ? <div className="px-5 pb-5"><Vazio icone={<MessageSquare />}>Nenhuma conversa com consumo neste período.</Vazio></div> : (
        <>
          {/* Celular: cartões */}
          <ul className="divide-y divide-[#f2f4f7] md:hidden">
            {dados.conversas.map((c) => (
              <li key={c.id_lead} className="flex items-center gap-3 px-5 py-3">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[13.5px] font-semibold text-[#101828]">{c.contato || "Sem nome"} {c.contrato_assinado && <SeloContrato />}</div>
                  <div className="text-[11.5px] text-[#667085]">{c.telefone ?? "—"} · {c.agente}</div>
                  <div className="text-[11.5px] text-[#98A2B3]">{inteiro(c.mensagens)} msgs · {inteiro(c.turnos)} turnos · {compacto(c.tokens)} tokens</div>
                </div>
                <div className="text-right"><div className="text-[14px] font-bold tabular-nums text-[#101828]">{rs(c.valor_brl)}</div>
                  <Link to={`/conversas/${c.id_lead}`} className="text-[12px] font-semibold text-[#00a02b]">Abrir</Link></div>
              </li>
            ))}
          </ul>
          {/* Tela larga: tabela */}
          <div className="hidden overflow-x-auto md:block">
            <table className="w-full text-[13px]">
              <thead><tr className="border-y border-[#f2f4f7] bg-[#f9fafb] text-left text-[11px] font-semibold uppercase tracking-wider text-[#667085]">
                <th className="px-5 py-2.5">Lead</th><th className="px-3 py-2.5">Agente</th><th className="px-3 py-2.5">Última atividade</th>
                <th className="px-3 py-2.5 text-right">Msgs</th><th className="px-3 py-2.5 text-right">Turnos</th><th className="px-3 py-2.5 text-right">Tokens</th>
                <th className="px-3 py-2.5 text-right">Custo</th><th className="px-5 py-2.5" />
              </tr></thead>
              <tbody>{dados.conversas.map((c) => (
                <tr key={c.id_lead} className="border-b border-[#f2f4f7] last:border-0 hover:bg-[#f9fafb]">
                  <td className="px-5 py-3"><div className="font-semibold text-[#101828]">{c.contato || "Sem nome"} {c.contrato_assinado && <SeloContrato />}</div>
                    <div className="text-[11.5px] tabular-nums text-[#667085]">{c.telefone ?? "—"}</div></td>
                  <td className="px-3 py-3 text-[#344054]">{c.agente}</td>
                  <td className="px-3 py-3 tabular-nums text-[#667085]">{quando(c.ultimo_em)}</td>
                  <td className="px-3 py-3 text-right tabular-nums">{inteiro(c.mensagens)}</td>
                  <td className="px-3 py-3 text-right tabular-nums">{inteiro(c.turnos)}</td>
                  <td className="px-3 py-3 text-right tabular-nums">{compacto(c.tokens)}</td>
                  <td className="px-3 py-3 text-right font-bold tabular-nums text-[#101828]">{rs(c.valor_brl)}</td>
                  <td className="px-5 py-3 text-right"><Link to={`/conversas/${c.id_lead}`} className="inline-flex items-center gap-1 whitespace-nowrap rounded-full border border-[#e4e7ec] px-3 py-1 text-[12px] font-semibold text-[#344054] hover:border-[#00bc33] hover:text-[#00a02b]">Abrir conversa<ArrowRight className="size-3" /></Link></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          {rodape}
        </>
      )}
    </section>
  );
}

// ============================================================================ Recargas
function Recargas({ p, dias, recargas, erro, aoMudar }: { p: PainelConsumo; dias: number; recargas: Recarga[] | null; erro: string | null; aoMudar: () => void }) {
  const cr = p.creditos;
  const meses = cr.por_mes.map((m) => ({ ...m, rotulo: `${m.mes.slice(5)}/${m.mes.slice(2, 4)}` }));
  const situacoes = (recargas ?? []).reduce<Record<string, number>>((s, r) => ({ ...s, [r.situacao]: (s[r.situacao] ?? 0) + 1 }), {});
  const pendentes = (recargas ?? []).filter((r) => r.situacao === "pendente");
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <Kpi icone={<TrendingUp />} cor="green" rotulo="Total recarregado" valor={reais(cr.recargas_brl)} nota={nomePeriodo(dias)} />
        <Kpi icone={<Gift />} cor="violet" rotulo="Bônus recebido" valor={reais(cr.bonus_brl)} nota={cr.bonus ? `${cr.bonus} bônus no período` : "sem bônus no período"} />
        <Kpi icone={<CheckCircle2 />} cor="blue" rotulo="Recargas confirmadas" valor={inteiro(cr.recargas)} nota="creditadas no saldo" />
        <Kpi icone={<CircleDollarSign />} cor="amber" rotulo="Ticket médio" valor={cr.recargas ? reais(cr.recargas_brl / cr.recargas) : "—"} nota="por recarga" />
      </div>
      <div className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
        <Cartao icone={<BarChart3 />} titulo="Créditos por mês" sub="Recargas e bônus dos últimos 12 meses.">
          {meses.length === 0 ? <Vazio icone={<BarChart3 />}>Nenhum crédito nos últimos 12 meses.</Vazio> : (
            <div className="h-[230px]"><ResponsiveContainer>
              <BarChart data={meses} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid stroke="#f2f4f7" vertical={false} />
                <XAxis dataKey="rotulo" tick={{ fontSize: 11, fill: "#98A2B3" }} tickLine={false} axisLine={false} />
                <YAxis tick={{ fontSize: 11, fill: "#98A2B3" }} tickLine={false} axisLine={false} width={58} tickFormatter={(v) => reais(v, 0)} />
                <Tooltip contentStyle={{ borderRadius: 12, border: "1px solid #e4e7ec", fontSize: 12 }} formatter={(v: number, n) => [reais(v), n === "recargas_brl" ? "Recargas" : "Bônus"]} />
                <Bar dataKey="recargas_brl" stackId="a" fill={VERDE} maxBarSize={56} />
                <Bar dataKey="bonus_brl" stackId="a" fill="#a6f4c5" radius={[6, 6, 0, 0]} maxBarSize={56} />
              </BarChart>
            </ResponsiveContainer></div>
          )}
        </Cartao>
        <Cartao icone={<Receipt />} titulo="Pedidos de recarga" sub="Situação dos pedidos feitos aqui.">
          {!recargas ? <Linhas erro={erro} /> : recargas.length === 0 ? <Vazio icone={<Receipt />}>Nenhum pedido de recarga ainda.</Vazio> : (
            <ul className="flex flex-col gap-3">
              {Object.entries(situacoes).map(([s, n]) => (
                <li key={s}>
                  <div className="flex justify-between text-[13px]"><SeloSituacao s={s} /><span className="tabular-nums text-[#667085]">{n} ({Math.round((n / recargas.length) * 100)}%)</span></div>
                  <Barra pct={(n / recargas.length) * 100} cor={s === "paga" ? VERDE : s === "pendente" ? "#f79009" : "#98A2B3"} />
                </li>
              ))}
            </ul>
          )}
        </Cartao>
      </div>
      {pendentes.length > 0 && (
        <Cartao icone={<AlertTriangle />} titulo="Aguardando pagamento"><ListaRecargas recargas={pendentes} aoMudar={aoMudar} cancelavel /></Cartao>
      )}
      <Cartao icone={<History />} titulo="Todos os pedidos de recarga">
        {!recargas ? <Linhas erro={erro} /> : recargas.length === 0 ? <Vazio icone={<Receipt />}>Nenhum pedido de recarga ainda.</Vazio> : <ListaRecargas recargas={recargas} aoMudar={aoMudar} />}
      </Cartao>
    </div>
  );
}

// ============================================================================ Avançado
function Avancado({ p, aoRecarregar }: { p: PainelConsumo; aoRecarregar: (v: number) => void }) {
  const { escritorio } = useSessao();
  const extrato = useCarregar<Movimento[]>("/carteira/extrato?limite=300", [escritorio]);
  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <Previsao p={p} />
        <Simulador p={p} aoRecarregar={aoRecarregar} />
      </div>
      <Ranking p={p} />
      <LinhaDoTempo movimentos={extrato.dados} erro={extrato.erro} />
      <ComoFunciona />
    </div>
  );
}

function Previsao({ p }: { p: PainelConsumo }) {
  const media = p.media_dia_brl;
  const disp = p.carteira.disponivel_brl;
  const hoje = new Date();
  const fimMes = new Date(hoje.getFullYear(), hoje.getMonth() + 1, 0);
  const restantes = Math.max(0, Math.ceil((fimMes.getTime() - hoje.getTime()) / 86400000));
  const dias = diasDeAutonomia(p);
  const curva = media ? Array.from({ length: 31 }, (_, i) => {
    const d = new Date(hoje.getTime() + i * 86400000);
    return { rotulo: `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}`, saldo: Math.max(0, disp - media * i) };
  }) : [];
  return (
    <Cartao icone={<Calendar />} titulo="Previsão de 30 dias" sub="Projeção pelo seu gasto médio dos últimos 30 dias.">
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <MiniDado rotulo="Gasto projetado (30d)" valor={media ? reais(media * 30) : "—"} />
        <MiniDado rotulo="Saldo no fim do mês" valor={media ? reais(disp - media * restantes) : reais(disp)} />
        <MiniDado rotulo="Saldo acaba em" valor={dias == null ? "sem consumo" : new Date(hoje.getTime() + dias * 86400000).toLocaleDateString("pt-BR")} />
      </div>
      {media ? (
        <div className="mt-4 h-[170px]"><ResponsiveContainer>
          <AreaChart data={curva} margin={{ top: 6, right: 6, left: 0, bottom: 0 }}>
            <defs><linearGradient id="crPrev" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#2e90fa" stopOpacity={0.25} /><stop offset="100%" stopColor="#2e90fa" stopOpacity={0} /></linearGradient></defs>
            <CartesianGrid stroke="#f2f4f7" vertical={false} />
            <XAxis dataKey="rotulo" tick={{ fontSize: 10.5, fill: "#98A2B3" }} tickLine={false} axisLine={false} minTickGap={24} />
            <YAxis tick={{ fontSize: 10.5, fill: "#98A2B3" }} tickLine={false} axisLine={false} width={58} tickFormatter={(v) => reais(v, 0)} />
            <Tooltip contentStyle={{ borderRadius: 12, border: "1px solid #e4e7ec", fontSize: 12 }} formatter={(v: number) => [reais(v), "Saldo previsto"]} />
            <Area type="monotone" dataKey="saldo" stroke="#2e90fa" strokeWidth={2} strokeDasharray="5 4" fill="url(#crPrev)" />
          </AreaChart>
        </ResponsiveContainer></div>
      ) : <Vazio icone={<Calendar />}>Sem histórico para projetar.</Vazio>}
    </Cartao>
  );
}

function Ranking({ p }: { p: PainelConsumo }) {
  const lista = p.por_agente.filter((a) => a.custo_por_lead_brl).sort((a, b) => (a.custo_por_lead_brl ?? 0) - (b.custo_por_lead_brl ?? 0));
  return (
    <Cartao icone={<Trophy />} titulo="Ranking de eficiência" sub="Quem atende mais leads com o mesmo dinheiro (menor R$ por lead primeiro).">
      {lista.length === 0 ? <Vazio icone={<Trophy />}>Sem dados de eficiência neste período.</Vazio> : (
        <div className="overflow-x-auto"><table className="w-full text-[13px]">
          <thead><tr className="text-left text-[11px] font-semibold uppercase tracking-wider text-[#667085]">
            <th className="py-2 pr-3">#</th><th className="py-2 pr-3">Agente</th><th className="py-2 pr-3 text-right">R$ por lead</th>
            <th className="py-2 pr-3 text-right">Leads com R$ 100</th><th className="py-2 pr-3 text-right">Contratos</th><th className="py-2 text-right">Custo por contrato</th></tr></thead>
          <tbody>{lista.map((a, i) => (
            <tr key={a.id_agente ?? "sem"} className="border-t border-[#f2f4f7]">
              <td className="py-2.5 pr-3">{i === 0 ? <Trophy className="size-4 text-[#f79009]" /> : `${i + 1}º`}</td>
              <td className="py-2.5 pr-3 font-semibold text-[#101828]">{a.agente}</td>
              <td className="py-2.5 pr-3 text-right font-bold tabular-nums">{rs(a.custo_por_lead_brl)}</td>
              <td className="py-2.5 pr-3 text-right tabular-nums text-[#067647]">≈ {inteiro(Math.floor(100 / (a.custo_por_lead_brl ?? 1)))}</td>
              <td className="py-2.5 pr-3 text-right tabular-nums">{inteiro(a.contratos)}</td>
              <td className="py-2.5 text-right tabular-nums">{rs(a.custo_por_contrato_brl)}</td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
    </Cartao>
  );
}

/** Recargas, bônus e ajustes um a um; o consumo (debitado em lotes) somado por dia. */
function LinhaDoTempo({ movimentos, erro }: { movimentos: Movimento[] | null; erro: string | null }) {
  const [mais, setMais] = useState(false);
  const itens = useMemo(() => {
    if (!movimentos) return [];
    const porDia = new Map<string, { valor: number; quando: string }>();
    const lista: { id: string; titulo: string; detalhe: string; valor: number; quando: string; entrada: boolean }[] = [];
    for (const m of movimentos) {
      if (m.tipo === "consumo") {
        const dia = new Date(m.criado_em).toLocaleDateString("pt-BR");
        const atual = porDia.get(dia);
        porDia.set(dia, { valor: (atual?.valor ?? 0) + m.valor_brl, quando: atual?.quando ?? m.criado_em });
      } else {
        lista.push({ id: m.id, titulo: m.nome_tipo, detalhe: m.motivo || (m.valor_brl > 0 ? "Crédito no saldo" : "Débito"), valor: m.valor_brl, quando: m.criado_em, entrada: m.valor_brl > 0 });
      }
    }
    for (const [dia, d] of porDia) lista.push({ id: `c-${dia}`, titulo: "Consumo da IA", detalhe: `Total do dia ${dia}`, valor: d.valor, quando: d.quando, entrada: false });
    return lista.sort((a, b) => b.quando.localeCompare(a.quando));
  }, [movimentos]);
  const visiveis = mais ? itens : itens.slice(0, 8);
  return (
    <Cartao icone={<History />} titulo="Linha do tempo" sub="Recargas, bônus e consumo em ordem cronológica.">
      {!movimentos ? <Linhas erro={erro} /> : itens.length === 0 ? <Vazio icone={<History />}>Nenhum movimento ainda.</Vazio> : (
        <>
          <ol className="relative ml-4 border-l border-[#e4e7ec]">
            {visiveis.map((i) => (
              <li key={i.id} className="relative mb-4 pl-6 last:mb-0">
                <span className={`absolute -left-[13px] top-0.5 grid size-6 place-items-center rounded-full ring-4 ring-white ${i.entrada ? "bg-[#e8f9ee] text-[#00a02b]" : "bg-[#f2f4f7] text-[#667085]"}`}>
                  {i.entrada ? <ArrowDownLeft className="size-3.5" /> : <ArrowUpRight className="size-3.5" />}
                </span>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0"><div className="text-[13.5px] font-semibold text-[#101828]">{i.titulo}</div>
                    <div className="truncate text-[12px] text-[#667085]">{i.detalhe}</div>
                    <div className="text-[11.5px] text-[#98A2B3]">{dataCurta(i.quando)}</div></div>
                  <span className={`shrink-0 font-bold tabular-nums ${i.entrada ? "text-[#00a02b]" : "text-[#344054]"}`}>{i.entrada ? "+" : ""}{rs(i.valor)}</span>
                </div>
              </li>
            ))}
          </ol>
          {itens.length > 8 && <button className="mt-3 text-[12.5px] font-semibold text-[#00a02b]" onClick={() => setMais(!mais)}>{mais ? "Mostrar menos" : `Mostrar todos (${itens.length})`}</button>}
        </>
      )}
    </Cartao>
  );
}

function ComoFunciona() {
  return (
    <section className="lc-card relative overflow-hidden bg-gradient-to-br from-white to-[#f6fef9] p-5 md:p-6">
      <div className="flex items-center gap-3">
        <span className="grid size-11 place-items-center rounded-2xl bg-[#00bc33] text-white shadow-[0_8px_20px_-8px_rgba(0,188,51,.8)]"><BookOpen className="size-5" /></span>
        <h3 className="text-[16px] font-bold text-[#101828]">Como funcionam os créditos</h3>
        <span className="rounded-full border border-[#e4e7ec] bg-white px-2 py-0.5 text-[11px] text-[#475467]">Bom saber</span>
      </div>
      <p className="mt-3 text-[13px] leading-relaxed text-[#475467]">
        Cada vez que um agente lê uma mensagem e responde, a IA processa <b>tokens</b> (pedaços de texto). O custo de cada lead é a soma de todas as respostas,
        leituras de áudio, imagem e documento e follow-ups daquela conversa. Primeiro sai do bônus do mês, depois do saldo. Se o saldo acabar, a IA pausa e volta sozinha quando a recarga entra.
      </p>
      <div className="mt-4 grid gap-3 md:grid-cols-3">
        {[{ i: <ArrowRight />, t: "Entrada", d: "Tudo que a IA lê para responder: instruções do agente, histórico e a mensagem do lead." },
          { i: <Sparkles />, t: "Saída", d: "A resposta escrita pela IA. Costuma custar mais por token que a entrada." },
          { i: <Cpu />, t: "Modelo", d: "Modelos mais inteligentes custam mais por token. Cada agente pode usar um modelo diferente." }].map((c) => (
          <div key={c.t} className="rounded-xl border border-[#e4e7ec] bg-white p-4">
            <div className="flex items-center gap-2 text-[12px] font-bold uppercase tracking-wider text-[#101828]"><span className="text-[#00bc33] [&>svg]:size-4">{c.i}</span>{c.t}</div>
            <p className="mt-1.5 text-[12.5px] text-[#667085]">{c.d}</p>
          </div>
        ))}
      </div>
      <p className="mt-3 flex items-center gap-2 rounded-xl bg-white/70 px-3 py-2 text-[12px] text-[#667085]"><Info className="size-3.5 shrink-0" />Tudo é cobrado em créditos (R$) numa conta só. Cada conversa mostra o custo real dela.</p>
    </section>
  );
}

// ============================================================================ peças
function Cartao({ icone, titulo, sub, direita, children }: { icone: ReactNode; titulo: string; sub?: string; direita?: ReactNode; children: ReactNode }) {
  return (
    <section className="lc-card relative p-5">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className="flex items-center gap-3"><Icone>{icone}</Icone>
          <div><h3 className="text-[15px] font-bold text-[#101828]">{titulo}</h3>{sub && <p className="text-[12px] text-[#667085]">{sub}</p>}</div></div>
        {direita}
      </div>
      {children}
    </section>
  );
}

const CORES_KPI = { green: ["#e8f9ee", "#00a02b"], blue: ["#eff8ff", "#1570ef"], amber: ["#fffaeb", "#dc6803"], violet: ["#f4f3ff", "#6938ef"] } as const;
function Kpi({ icone, cor, rotulo, valor, nota }: { icone: ReactNode; cor: keyof typeof CORES_KPI; rotulo: string; valor: ReactNode; nota?: string }) {
  const [fundo, frente] = CORES_KPI[cor];
  return (
    <div className="lc-card relative p-4 transition hover:-translate-y-0.5">
      <div className="flex items-center gap-2"><span className="grid size-8 place-items-center rounded-lg [&>svg]:size-4" style={{ background: fundo, color: frente }}>{icone}</span>
        <span className="text-[12.5px] font-medium text-[#475467]">{rotulo}</span></div>
      <div className="mt-3 text-[24px] font-extrabold leading-none tracking-tight tabular-nums text-[#101828]">{valor}</div>
      {nota && <div className="mt-1.5 text-[11.5px] text-[#98A2B3]">{nota}</div>}
    </div>
  );
}

function MiniDado({ icone, rotulo, valor, nota, tom }: { icone?: ReactNode; rotulo: string; valor: string; nota?: string; tom?: "ok" | "warn" }) {
  return (
    <div className="rounded-2xl border border-[#eaecf0] bg-white/90 p-3.5">
      <div className="flex items-center gap-1.5 text-[11.5px] text-[#667085]">{icone && <span className="text-[#00bc33] [&>svg]:size-3.5">{icone}</span>}{rotulo}</div>
      <div className="mt-1 text-[17px] font-bold tabular-nums text-[#101828]">{valor}</div>
      {nota && <div className={`mt-0.5 text-[11px] ${tom === "warn" ? "text-[#b54708]" : tom === "ok" ? "text-[#067647]" : "text-[#98A2B3]"}`}>{nota}</div>}
    </div>
  );
}

const Numero = ({ rotulo, valor, destaque }: { rotulo: string; valor: string; destaque?: boolean }) => (
  <div className={`rounded-xl px-2 py-2 ${destaque ? "bg-[#ecfdf3]" : "bg-[#f9fafb]"}`}>
    <div className={`text-[15px] font-extrabold tabular-nums ${destaque ? "text-[#067647]" : "text-[#101828]"}`}>{valor}</div>
    <div className="text-[10.5px] text-[#667085]">{rotulo}</div>
  </div>
);
const Icone = ({ children }: { children: ReactNode }) => <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-[#e8f9ee] text-[#00bc33] [&>svg]:size-[18px]">{children}</span>;
const Barra = ({ pct, cor }: { pct: number; cor: string }) => (
  <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-[#f2f4f7]"><div className="cr-barra h-full rounded-full" style={{ width: `${Math.min(100, Math.max(0, pct))}%`, background: cor }} /></div>
);
const BotaoTexto = ({ onClick, children }: { onClick: () => void; children: ReactNode }) => (
  <button onClick={onClick} className="shrink-0 text-[12.5px] font-semibold text-[#00a02b] hover:underline">{children}</button>
);
const SeloContrato = () => <span className="ml-1 inline-flex items-center rounded-full bg-[#ecfdf3] px-1.5 py-0.5 align-middle text-[10px] font-semibold text-[#067647]">contrato</span>;
const NOME_SITUACAO: Record<string, [string, string, string]> = {
  paga: ["Confirmada", "#ecfdf3", "#067647"], pendente: ["Aguardando", "#fffaeb", "#b54708"], cancelada: ["Cancelada", "#f2f4f7", "#475467"],
  expirada: ["Expirada", "#f2f4f7", "#475467"], estornada: ["Estornada", "#fef3f2", "#b42318"],
};
const SeloSituacao = ({ s }: { s: string }) => {
  const [t, fundo, cor] = NOME_SITUACAO[s] ?? [s, "#f2f4f7", "#475467"];
  return <span className="rounded-full px-2 py-0.5 text-[11px] font-semibold" style={{ background: fundo, color: cor }}>{t}</span>;
};
function Faixa({ tom, icone, titulo, children }: { tom: "bad" | "warn"; icone: ReactNode; titulo: string; children: ReactNode }) {
  const [fundo, borda, cor] = tom === "bad" ? ["#fef3f2", "#fecdca", "#b42318"] : ["#fffaeb", "#fedf89", "#b54708"];
  return (
    <div className="mb-4 flex items-start gap-3 rounded-2xl border px-4 py-3 text-[13px]" style={{ background: fundo, borderColor: borda, color: cor }}>
      <span className="mt-0.5 [&>svg]:size-4">{icone}</span><div><b>{titulo}.</b> {children}</div>
    </div>
  );
}
const Vazio = ({ icone, children }: { icone: ReactNode; children: ReactNode }) => (
  <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-[#eaecf0] bg-[#fcfcfd] px-4 py-10 text-center">
    <span className="grid size-11 place-items-center rounded-2xl bg-[#f2f4f7] text-[#98A2B3] [&>svg]:size-5">{icone}</span>
    <p className="text-[13px] text-[#667085]">{children}</p>
  </div>
);
const Linhas = ({ erro }: { erro?: string | null }) => erro
  ? <p className="text-[13px] text-[#b42318]">{erro}</p>
  : <div className="flex flex-col gap-2">{[0, 1, 2].map((i) => <div key={i} className="cr-brilho h-9 rounded-lg" />)}</div>;
const Esqueleto = ({ altura, erro }: { altura: number; erro?: string | null }) => erro
  ? <div className="lc-card p-5 text-[13px] text-[#b42318]">{erro}</div>
  : <div className="cr-brilho rounded-[28px]" style={{ height: altura }} />;

/** Conta de 0 até o valor (suave; sem animação para quem pediu menos movimento). */
function Contador({ valor, formato }: { valor: number; formato: (v: number) => string }) {
  const reduzir = useReducedMotion();
  const [atual, setAtual] = useState(reduzir ? valor : 0);
  const de = useRef(0);
  useEffect(() => {
    if (reduzir) { setAtual(valor); return; }
    const inicio = performance.now();
    const origem = de.current;
    let quadro = 0;
    const passo = (agora: number) => {
      const t = Math.min(1, (agora - inicio) / 900);
      const v = origem + (valor - origem) * (1 - Math.pow(1 - t, 3));
      setAtual(v);
      if (t < 1) quadro = requestAnimationFrame(passo); else de.current = valor;
    };
    quadro = requestAnimationFrame(passo);
    return () => { cancelAnimationFrame(quadro); de.current = valor; };
  }, [valor, reduzir]);
  return <>{formato(atual)}</>;
}

// ============================================================================ utilitários
function formatarDias(d: number) {
  if (d < 1) return "menos de 1 dia";
  if (d >= 365) return "mais de 1 ano";
  const n = Math.floor(d);
  return `${n} ${n === 1 ? "dia" : "dias"}`;
}
const dataCurta = (iso: string) => new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });

/** Série contínua (dias/horas sem consumo aparecem com zero). As chaves do servidor estão no horário de Brasília. */
function preencherSerie(p: PainelConsumo, dias: number) {
  const mapa = new Map(p.serie.map((s) => [s.quando.slice(0, p.granularidade === "hora" ? 13 : 10), s]));
  const pad = (n: number) => String(n).padStart(2, "0");
  const saida: { rotulo: string; valor_brl: number; conversas: number }[] = [];
  const agora = new Date();
  if (p.granularidade === "hora") {
    for (let i = 23; i >= 0; i--) {
      const d = new Date(agora.getTime() - i * 3600000);
      const chave = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}`;
      const s = mapa.get(chave);
      saida.push({ rotulo: `${pad(d.getHours())}h`, valor_brl: s?.valor_brl ?? 0, conversas: s?.conversas ?? 0 });
    }
  } else {
    for (let i = dias - 1; i >= 0; i--) {
      const d = new Date(agora.getFullYear(), agora.getMonth(), agora.getDate() - i);
      const chave = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
      const s = mapa.get(chave);
      saida.push({ rotulo: `${pad(d.getDate())}/${pad(d.getMonth() + 1)}`, valor_brl: s?.valor_brl ?? 0, conversas: s?.conversas ?? 0 });
    }
  }
  return saida;
}

/** CSV (separador ;, com BOM para o Excel em português) com o resumo, por dia, por agente, por função e as conversas que mais gastaram. */
function exportarCsv(p: PainelConsumo, caras: Conversas | null, dias: number) {
  const num = (v: number | null | undefined, casas = 4) => (v == null ? "" : v.toFixed(casas).replace(".", ","));
  const cel = (v: unknown) => { const s = String(v ?? ""); return /[;"\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const linhas: unknown[][] = [
    ["Créditos & Consumo", `período: ${dias === 1 ? "24 horas" : `${dias} dias`}`, `gerado em ${new Date().toLocaleString("pt-BR")}`], [],
    ["Resumo"], ["Saldo disponível (R$)", num(p.carteira.disponivel_brl, 2)], ["Créditos usados (R$)", num(p.totais.creditos_brl)],
    ["Leads atendidos", p.totais.conversas], ["Custo médio por lead (R$)", num(p.custo_por_lead.valor_brl)],
    ["Leads que o saldo atende", p.custo_por_lead.leads_com_saldo ?? ""], ["Estimativa?", p.custo_por_lead.estimativa ? "sim" : "não"],
    ["Tokens", p.totais.tokens], ["Contratos assinados", p.totais.contratos], ["Custo por contrato (R$)", num(p.totais.custo_por_contrato_brl, 2)], [],
    ["Consumo por " + (p.granularidade === "hora" ? "hora" : "dia")], ["Quando", "R$", "Tokens", "Leads"],
    ...p.serie.map((s) => [s.quando, num(s.valor_brl), s.tokens, s.conversas]), [],
    ["Por agente"], ["Agente", "R$", "Leads", "R$ por lead", "Contratos", "Custo por contrato", "Conversão %", "Tokens"],
    ...p.por_agente.map((a) => [a.agente, num(a.valor_brl), a.conversas, num(a.custo_por_lead_brl), a.contratos, num(a.custo_por_contrato_brl, 2), num(a.conversao_pct, 1), a.tokens]), [],
    ["Por função"], ["Função", "R$", "Chamadas", "Tokens"], ...p.por_funcao.map((f) => [f.nome, num(f.valor_brl), f.chamadas, f.tokens]), [],
    ["Conversas que mais gastaram"], ["Lead", "Telefone", "Agente", "Mensagens", "Turnos", "Tokens", "R$", "Última atividade"],
    ...(caras?.conversas ?? []).map((c) => [c.contato ?? "", c.telefone ?? "", c.agente, c.mensagens, c.turnos, c.tokens, num(c.valor_brl), c.ultimo_em]),
  ];
  const texto = "﻿" + linhas.map((l) => l.map(cel).join(";")).join("\r\n");
  const url = URL.createObjectURL(new Blob([texto], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url; a.download = `creditos-consumo-${dias === 1 ? "24h" : `${dias}d`}-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
