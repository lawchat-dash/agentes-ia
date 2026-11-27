import { useEffect, useMemo, useState, type ReactNode } from "react";
import BotaoBrilho from "@/components/reactbits/BotaoBrilho";
import { Link, useSearchParams } from "react-router-dom";
import {
  Activity, AlertTriangle, ArrowDownLeft, ArrowRight, ArrowUpRight, BookOpen, Bot, CalendarDays, CheckCircle2, ChevronLeft, ChevronRight, Clock,
  Cpu, Download, FileCheck2, Heart, History, Info, LineChart as IconeLinha, MessageCircle, Receipt, Sparkles, Target, TrendingUp, Users,
} from "lucide-react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { quando } from "../api";
import { useCarregar } from "../componentes/ui";
import { useSessao } from "../sessao";
import { ListaRecargas, PedirRecarga, reais, type Movimento, type Recarga } from "./Carteira";
import TopoCreditos from "@/components/creditos/TopoCreditos";
import type { Agente, PainelConsumo } from "@/components/creditos/tipos";

/*
 * Créditos & Consumo (cliente, /consumo). Foco: quantos leads o saldo atende. Tudo em R$ cobrado (o que sai da
 * carteira, já com o markup); nada de US$. Só dados reais: quando é estimativa, a tela diz; sem dado, estado vazio.
 * Dados: /carteira/painel (uma ida), /carteira/conversas, /carteira/recargas e /carteira/extrato.
 * Visual: topo em components/creditos/TopoCreditos (faixa escura saldo + simulador, números do mês, gasto por dia,
 * por agente, recargas; sempre 30 dias); abaixo, abas em pílula com o período escolhido; blocos brancos com ícone
 * em caixinha de cor suave. Destaques de texto na mesma fonte do painel (Inter), no verde LawChat.
 */

interface Conversa {
  id_lead: string; valor_brl: number; tokens: number; chamadas: number; turnos: number; mensagens: number; primeiro_em: string; ultimo_em: string;
  contato: string | null; telefone: string | null; agente: string; id_agente: string | null; contrato_assinado: boolean;
}
interface Conversas { total: number; conversas: Conversa[] }

// Paleta: verde LawChat como destaque; cores das funções só na rosca; vermelho/âmbar só em alerta.
const VERDE = "#00bc33";
const VERDE_ESCURO = "#0a8f35";
const CINZA_BARRA = "#d0d5dd";
const CORES_FUNCAO = ["#0a8f35", "#2563eb", "#f59e0b", "#7c3aed", "#667085", "#c7cfd6", "#0ea5e9", "#ec4899"];
const EIXO = { fontSize: 11, fill: "#98A2B3" };
const DICA = { borderRadius: 10, border: "1px solid #e6ebe8", fontSize: 12, boxShadow: "0 8px 24px rgba(16,24,40,.08)" };

const PERIODOS = [{ d: 1, r: "24h" }, { d: 7, r: "7d" }, { d: 30, r: "30d" }, { d: 90, r: "90d" }];
const ABAS = [{ id: "visao", r: "Visão geral", i: Activity }, { id: "agentes", r: "Por agente", i: Bot }, { id: "historico", r: "Histórico", i: Clock },
  { id: "recargas", r: "Recargas", i: Receipt }, { id: "avancado", r: "Avançado", i: TrendingUp }] as const;
type Aba = (typeof ABAS)[number]["id"];
const nomePeriodo = (d: number) => (d === 1 ? "nas últimas 24 horas" : `nos últimos ${d} dias`);
/** Valores pequenos (custo de um lead) com mais casas, para não virar "R$ 0,00". */
const rs = (v: number | null | undefined) => (v == null ? "—" : reais(v, Math.abs(v) > 0 && Math.abs(v) < 0.1 ? 4 : 2));
const inteiro = (v: number | null | undefined) => (v ?? 0).toLocaleString("pt-BR");
const pct = (v: number | null | undefined) => `${(v ?? 0).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`;
const compacto = (v: number) => v.toLocaleString("pt-BR", { notation: "compact", maximumFractionDigits: 1 });
/** Tokens por extenso curto: "813,6 mil", "1,2 mi". */
const tokensCurto = (v: number) => (v >= 1e6 ? `${(v / 1e6).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} mi`
  : v >= 1000 ? `${(v / 1000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} mil` : inteiro(v));

// ============================================================================ tela
export function TelaCreditos() {
  const { escritorio } = useSessao();
  const [busca, setBusca] = useSearchParams();
  const aba = (ABAS.some((a) => a.id === busca.get("aba")) ? busca.get("aba") : "visao") as Aba;
  const irPara = (nova: Aba) => setBusca((b) => { const n = new URLSearchParams(b); n.set("aba", nova); return n; }, { replace: true });
  const [dias, setDias] = useState(30);
  const [valorSim, setValorSim] = useState(150);
  // O topo usa sempre os últimos 30 dias; as abas usam o período escolhido (mesma ida quando é 30d).
  const base30 = useCarregar<PainelConsumo>("/carteira/painel?dias=30", [escritorio]);
  const doPeriodo = useCarregar<PainelConsumo>(dias === 30 ? null : `/carteira/painel?dias=${dias}`, [escritorio, dias]);
  const painel = dias === 30 ? base30 : doPeriodo;
  const caras = useCarregar<Conversas>(`/carteira/conversas?dias=${dias}&ordem=custo&limite=10`, [escritorio, dias]);
  const recargas = useCarregar<Recarga[]>("/carteira/recargas", [escritorio]);
  const [pedir, setPedir] = useState<number | null>(null);
  const aposPedir = () => { base30.recarregar(); if (dias !== 30) doPeriodo.recarregar(); recargas.recarregar(); };
  const verRecargas = () => { irPara("recargas"); document.getElementById("cr-detalhes")?.scrollIntoView({ behavior: "smooth", block: "start" }); };

  const p = painel.dados;
  return (
    <div className="cr-tela mx-auto w-full max-w-[1240px] pb-12">
      {(recargas.dados ?? []).some((r) => r.situacao === "pendente") && (
        <div className="mb-4 flex items-start gap-3 rounded-xl border border-[#fedf89] bg-[#fffaeb] px-4 py-3 text-[13px] text-[#b54708]">
          <Receipt className="mt-0.5 size-4 shrink-0" />
          <div><b>Você tem recarga aguardando pagamento.</b>{" "}
            <button className="font-semibold underline" onClick={verRecargas}>Ver na aba Recargas</button></div>
        </div>
      )}

      {base30.dados ? (
        <TopoCreditos p={base30.dados} recargas={recargas.dados} erroRecargas={recargas.erro} valor={valorSim} setValor={setValorSim}
          aoRecarregar={setPedir} aoVerRecargas={verRecargas} />
      ) : <Esqueleto altura={460} erro={base30.erro} />}

      {/* Detalhes: abas em pílula + período + exportar */}
      <div id="cr-detalhes" className="mb-6 mt-9 flex scroll-mt-4 flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="overflow-x-auto pb-1">
          <div className="cr-abas inline-flex gap-1 rounded-2xl border border-[#e6ebe8] bg-white p-1.5" role="tablist" aria-label="Seções">
            {ABAS.map((a) => {
              const Icone = a.i;
              const ativa = aba === a.id;
              return (
                <button key={a.id} role="tab" aria-selected={ativa} onClick={() => irPara(a.id)}
                  className={`cr-aba inline-flex shrink-0 items-center gap-2 rounded-xl px-4 py-2 text-[14px] font-semibold transition ${ativa ? "cr-aba-ativa text-white" : "text-[#344054] hover:bg-[#f2f5f3]"}`}>
                  <Icone className="size-4" strokeWidth={2} />{a.r}
                </button>
              );
            })}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          <div role="radiogroup" aria-label="Período" className="flex rounded-xl border border-[#e6ebe8] bg-white p-1">
            {PERIODOS.map(({ d, r }) => (
              <button key={d} role="radio" aria-checked={dias === d} onClick={() => setDias(d)}
                className={`rounded-lg px-3 py-1.5 text-[13px] font-semibold transition ${dias === d ? "bg-[#0c111d] text-white" : "text-[#475467] hover:text-[#0c111d]"}`}>{r}</button>
            ))}
          </div>
          <button disabled={!p} onClick={() => p && exportarCsv(p, caras.dados, dias)}
            className="inline-flex items-center gap-2 rounded-xl border border-[#e6ebe8] bg-white px-4 py-2 text-[13.5px] font-semibold text-[#1d2939] transition hover:bg-[#f7f9f8] disabled:opacity-40">
            <Download className="size-4" />Exportar
          </button>
        </div>
      </div>

      {!p ? <Esqueleto altura={320} erro={painel.erro} /> : (
        <div key={aba} className="cr-entra">
          {aba === "visao" && <VisaoGeral p={p} dias={dias} caras={caras.dados} erroCaras={caras.erro} irPara={irPara} recargas={recargas.dados} aoRecarregar={setPedir} />}
          {aba === "agentes" && <PorAgente p={p} dias={dias} />}
          {aba === "historico" && <Historico dias={dias} />}
          {aba === "recargas" && <Recargas p={p} dias={dias} recargas={recargas.dados} erro={recargas.erro} aoMudar={aposPedir} />}
          {aba === "avancado" && <Avancado p={p} />}
        </div>
      )}
      {pedir != null && <PedirRecarga valorInicial={pedir} aoFechar={() => setPedir(null)} aoPedir={aposPedir} />}
    </div>
  );
}

const diasDeAutonomia = (p: PainelConsumo) =>
  p.media_dia_brl && p.media_dia_brl > 0 ? Math.max(0, p.carteira.disponivel_brl) / p.media_dia_brl : null;

// ============================================================================ Visão geral
function VisaoGeral({ p, dias, caras, erroCaras, irPara, recargas, aoRecarregar }: {
  p: PainelConsumo; dias: number; caras: Conversas | null; erroCaras: string | null; irPara: (a: Aba) => void;
  recargas: Recarga[] | null; aoRecarregar: (v: number) => void;
}) {
  const t = p.totais;
  const serie = useMemo(() => preencherSerie(p, dias), [p, dias]);
  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-1 gap-4 min-[480px]:grid-cols-2 md:grid-cols-3 xl:grid-cols-5">
        <Kpi icone={<TrendingUp />} cor="verde" rotulo="Créditos usados" valor={reais(t.creditos_brl)} nota={nomePeriodo(dias)}
          extra={t.creditos_brl > 0 ? <MiniLinha valores={serie.map((s) => s.valor_brl)} /> : undefined} />
        <Kpi icone={<Users />} cor="azul" rotulo="Leads atendidos" valor={inteiro(t.conversas)} nota="conversas com a IA no período" />
        <Kpi icone={<Target />} cor="ambar" rotulo="Custo médio por lead" valor={rs(t.custo_por_conversa_brl)}
          nota={t.conversas ? `${inteiro(t.conversas)} ${t.conversas === 1 ? "lead" : "leads"} no período` : "sem leads no período"} />
        <Kpi icone={<Cpu />} cor="roxo" rotulo="Tokens consumidos" valor={tokensCurto(t.tokens)} nota={`${inteiro(t.chamadas)} chamadas da IA`}
          extra={t.tokens > 0 ? <span className="mt-2 inline-flex rounded-full bg-[#f1f4f2] px-2.5 py-1 text-[11.5px] font-semibold text-[#475467]">≈ {rs((t.creditos_brl / t.tokens) * 1000)} por mil tokens</span> : undefined} />
        <Kpi icone={<FileCheck2 />} cor="verde" rotulo="Contratos assinados" valor={inteiro(t.contratos)}
          nota={t.contratos ? `${rs(t.custo_por_contrato_brl)} por contrato · ${pct(t.conversao_pct)} conversão` : "sem contratos assinados no período"} />
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.45fr)_minmax(0,1fr)]">
        <Bloco icone={<Activity />} titulo="Consumo ao longo do tempo" sub={`Quanto a IA gastou em cada ${p.granularidade === "hora" ? "hora" : "dia"} do período.`}
          direita={<span className="hidden shrink-0 items-center gap-1.5 whitespace-nowrap text-[12px] sm:inline-flex text-[#475467]"><span className="size-2 rounded-full bg-[#0a8f35]" />R$ cobrado</span>}>
          <GraficoConsumo p={p} serie={serie} />
        </Bloco>
        <Bloco icone={<Sparkles />} titulo="Consumo por função" sub="Para onde foram seus créditos.">
          <PorFuncao p={p} />
        </Bloco>
      </div>

      <TabelaConversas icone={<MessageCircle />} titulo="Conversas que mais gastaram" sub={`As 10 conversas com mais consumo ${nomePeriodo(dias)}.`} dados={caras} erro={erroCaras}
        direita={<BotaoTexto onClick={() => irPara("historico")}>Ver histórico</BotaoTexto>} />

      <div className="grid gap-5 lg:grid-cols-2">
        <Bloco icone={<Heart />} titulo="Saúde da operação" sub="O que precisa da sua atenção agora."><Saude p={p} /></Bloco>
        <Bloco icone={<Receipt />} titulo="Últimas recargas" sub="Pedidos e créditos mais recentes." direita={<BotaoTexto onClick={() => irPara("recargas")}>Ver todas</BotaoTexto>}>
          {!recargas ? <Linhas /> : recargas.length === 0 ? (
            <div className="grid place-items-center rounded-2xl border border-dashed border-[#d5ddd8] px-4 py-8 text-center">
              <span className="grid size-10 place-items-center rounded-xl bg-[#f1f4f2] text-[#667085]"><Receipt className="size-4" /></span>
              <p className="mt-3 text-[14px] text-[#475467]">Nenhum pedido de recarga ainda.</p>
              <BotaoBrilho suave size="sm" radius={12} className="mt-3" onClick={() => aoRecarregar(150)}>Pedir a primeira recarga</BotaoBrilho>
            </div>
          ) : (
            <ul className="flex flex-col gap-2">
              {recargas.slice(0, 4).map((r) => (
                <li key={r.id} className="flex items-center gap-3 rounded-xl bg-[#f6f8f7] px-3.5 py-3 text-[13px]">
                  <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-white text-[#0a8f35]"><ArrowDownLeft className="size-4" /></span>
                  <div className="min-w-0 flex-1">
                    <div className="font-bold tabular-nums text-[#0c111d]">{reais(r.valor_brl)}</div>
                    <div className="text-[11.5px] tabular-nums text-[#667085]">{dataCurta(r.criado_em)}</div>
                  </div>
                  <SeloSituacao s={r.situacao} />
                </li>
              ))}
            </ul>
          )}
        </Bloco>
      </div>
      <ComoFunciona />
    </div>
  );
}

function GraficoConsumo({ p, serie }: { p: PainelConsumo; serie: { rotulo: string; valor_brl: number; conversas: number }[] }) {
  if (p.totais.creditos_brl === 0) return <Vazio>Sem consumo registrado neste período.</Vazio>;
  const comConsumo = serie.filter((s) => s.valor_brl > 0);
  const pico = serie.reduce((m, s) => (s.valor_brl > m.valor_brl ? s : m), serie[0]);
  const ultimo = serie.length - 1;
  const unidade = p.granularidade === "hora" ? "hora" : "dia";
  return (
    <>
      <div className="h-[240px] w-full">
        <ResponsiveContainer>
          <AreaChart data={serie} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="crArea" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={VERDE_ESCURO} stopOpacity={0.22} />
                <stop offset="100%" stopColor={VERDE_ESCURO} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#eef2ef" vertical={false} />
            <XAxis dataKey="rotulo" tick={EIXO} tickLine={false} axisLine={false} minTickGap={28} />
            <YAxis tick={EIXO} tickLine={false} axisLine={false} width={62} tickFormatter={(v) => reais(v, Number.isInteger(v) ? 0 : 2)} />
            <Tooltip cursor={{ stroke: "#c9d6ce" }} contentStyle={DICA}
              formatter={(v: number, _n, item: any) => [`${rs(v)} · ${inteiro(item?.payload?.conversas)} leads`, "Consumo"]} />
            <Area type="monotone" dataKey="valor_brl" stroke={VERDE_ESCURO} strokeWidth={2} fill="url(#crArea)" animationDuration={700}
              activeDot={{ r: 4, strokeWidth: 2, stroke: "#fff", fill: VERDE_ESCURO }}
              dot={(d: any) => d.index === ultimo
                ? <circle key="fim" cx={d.cx} cy={d.cy} r={4} fill={VERDE_ESCURO} stroke="#fff" strokeWidth={2} />
                : <g key={d.index} />} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-3 flex items-start gap-2 text-[12.5px] text-[#475467]">
        <Info className="mt-0.5 size-3.5 shrink-0 text-[#667085]" />
        {comConsumo.length === 1
          ? `Todo o consumo do período aconteceu em ${comConsumo[0].rotulo}. Passe o mouse no gráfico para ver cada ${unidade}.`
          : `Pico em ${pico.rotulo}: ${rs(pico.valor_brl)}. Passe o mouse no gráfico para ver cada ${unidade}.`}
      </p>
    </>
  );
}

/** Rosca com o total no centro + legenda com R$, %, chamadas e tokens. */
function PorFuncao({ p }: { p: PainelConsumo }) {
  const total = p.por_funcao.reduce((s, f) => s + f.valor_brl, 0);
  if (!total) return <Vazio>Sem consumo por função neste período.</Vazio>;
  const lista = p.por_funcao.slice(0, CORES_FUNCAO.length);
  return (
    <div className="grid items-center gap-5 sm:grid-cols-[170px_minmax(0,1fr)]">
      <div className="relative mx-auto size-[170px]">
        <ResponsiveContainer>
          <PieChart>
            <Pie data={lista} dataKey="valor_brl" nameKey="nome" innerRadius={56} outerRadius={80} startAngle={90} endAngle={-270} paddingAngle={lista.length > 1 ? 1 : 0}
              stroke="none" animationDuration={700}>
              {lista.map((f, i) => <Cell key={f.papel} fill={CORES_FUNCAO[i]} />)}
            </Pie>
            <Tooltip contentStyle={DICA} formatter={(v: number, n) => [rs(v), n]} />
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 grid place-items-center text-center">
          <div><div className="text-[18px] font-extrabold tracking-tight tabular-nums text-[#0c111d]">{rs(total)}</div>
            <div className="text-[11px] text-[#667085]">total do período</div></div>
        </div>
      </div>
      <ul className="flex min-w-0 flex-col gap-3">
        {lista.map((f, i) => (
          <li key={f.papel} className="min-w-0">
            <div className="flex items-baseline justify-between gap-3 text-[13.5px]">
              <span className="flex min-w-0 items-center gap-2 font-semibold text-[#1d2939]">
                <span className="size-2.5 shrink-0 rounded-[3px]" style={{ background: CORES_FUNCAO[i] }} /><span className="truncate">{f.nome}</span>
              </span>
              <span className="shrink-0 font-semibold tabular-nums text-[#1d2939]">{rs(f.valor_brl)}</span>
            </div>
            <div className="pl-[18px] text-[11.5px] text-[#667085]">{Math.round((f.valor_brl / total) * 100)}% · {inteiro(f.chamadas)} chamadas · {tokensCurto(f.tokens)} tokens</div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Saude({ p }: { p: PainelConsumo }) {
  const dias = diasDeAutonomia(p);
  const c = p.comparativo;
  const variacao = c.anteriores_7_brl > 0 ? ((c.ultimos_7_brl - c.anteriores_7_brl) / c.anteriores_7_brl) * 100 : null;
  const itens: { ok: boolean | null; texto: string }[] = [
    p.carteira.bloqueado ? { ok: false, texto: "A IA está pausada: o saldo acabou. Ela volta sozinha quando a recarga entra." }
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
  const estilo = (ok: boolean | null) => (ok === false ? "bg-[#fff1dc] text-[#93370d]" : ok === true ? "bg-[#e7f7ec] text-[#0a6b2a]" : "bg-[#f1f4f2] text-[#344054]");
  return (
    <ul className="flex flex-col gap-2">
      {itens.map((i, n) => (
        <li key={n} className={`flex items-start gap-2.5 rounded-xl px-3.5 py-3 text-[13.5px] ${estilo(i.ok)}`}>
          {i.ok === true ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-[#0a8f35]" /> : i.ok === false ? <AlertTriangle className="mt-0.5 size-4 shrink-0 text-[#dc6803]" /> : <Info className="mt-0.5 size-4 shrink-0 text-[#475467]" />}
          {i.texto}
        </li>
      ))}
      <li className="flex items-center gap-2.5 rounded-xl bg-[#f1f4f2] px-3.5 py-3 text-[13.5px] text-[#344054]">
        <CalendarDays className="size-4 shrink-0 text-[#475467]" />
        <span className="flex-1">Próxima recarga prevista</span>
        <b className="font-bold text-[#0c111d]">{previsao ? previsao.toLocaleDateString("pt-BR", { day: "numeric", month: "long", ...(previsao.getFullYear() !== new Date().getFullYear() ? { year: "numeric" } : {}) }) : "—"}</b>
      </li>
    </ul>
  );
}

// ============================================================================ Por agente
function PorAgente({ p, dias }: { p: PainelConsumo; dias: number }) {
  const [escolhido, setEscolhido] = useState<string | null>(null);
  const agente = p.por_agente.find((a) => (a.id_agente ?? "") === escolhido) ?? null;
  const conversas = useCarregar<Conversas>(agente?.id_agente ? `/carteira/conversas?dias=${dias}&ordem=custo&limite=10&id_agente=${agente.id_agente}` : null, [escolhido, dias]);
  const maisCaro = [...p.por_agente].filter((a) => a.custo_por_lead_brl).sort((a, b) => (b.custo_por_lead_brl ?? 0) - (a.custo_por_lead_brl ?? 0))[0];
  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-1 gap-4 min-[480px]:grid-cols-2 lg:grid-cols-4">
        <Kpi icone={<Bot />} cor="verde" rotulo="Agentes com consumo" valor={inteiro(p.por_agente.length)} nota={nomePeriodo(dias)} />
        <Kpi icone={<TrendingUp />} cor="azul" rotulo="Quem mais gastou" valor={p.por_agente[0]?.agente ?? "—"} pequeno
          nota={p.por_agente[0] ? `${reais(p.por_agente[0].valor_brl)} · ${pct(p.por_agente[0].participacao_pct)} do total` : "sem consumo"} />
        <Kpi icone={<Target />} cor="ambar" rotulo="Maior custo por lead" valor={maisCaro ? rs(maisCaro.custo_por_lead_brl) : "—"} nota={maisCaro?.agente ?? "sem leads"} />
        <Kpi icone={<FileCheck2 />} cor="roxo" rotulo="Contratos" valor={inteiro(p.totais.contratos)} nota={p.totais.contratos ? `${pct(p.totais.conversao_pct)} conversão` : "sem contratos no período"} />
      </div>
      <Bloco icone={<Bot />} titulo="Consumo por agente" sub={`Quanto cada agente gastou ${nomePeriodo(dias)}. Toque num agente para ver as conversas que mais gastaram.`} corpo="pb-2">
        <TabelaAgentes agentes={p.por_agente} escolhido={escolhido} aoEscolher={setEscolhido} />
      </Bloco>
      {agente && <TabelaConversas icone={<MessageCircle />} titulo={`Conversas que mais gastaram · ${agente.agente}`} sub={nomePeriodo(dias)} dados={conversas.dados} erro={conversas.erro}
        direita={<BotaoTexto onClick={() => setEscolhido(null)} seta={false}>Fechar</BotaoTexto>} />}
    </div>
  );
}

/** Tabela por agente. A maior participação fica em verde; o resto em cinza. */
function TabelaAgentes({ agentes, escolhido, aoEscolher }: { agentes: Agente[]; escolhido?: string | null; aoEscolher?: (id: string | null) => void }) {
  if (agentes.length === 0) return <div className="px-5 pb-3 md:px-6"><Vazio>Nenhum agente consumiu neste período.</Vazio></div>;
  const maior = Math.max(...agentes.map((a) => a.participacao_pct));
  const clicavel = (a: Agente) => !!aoEscolher && !!a.id_agente;
  const alternar = (a: Agente) => aoEscolher && a.id_agente && aoEscolher(escolhido === a.id_agente ? null : a.id_agente);
  return (
    <>
      {/* Celular: lista */}
      <ul className="divide-y divide-[#eef2ef] border-t border-[#eef2ef] md:hidden">
        {agentes.map((a) => (
          <li key={a.id_agente ?? "sem"} onClick={() => alternar(a)}
            className={`px-5 py-3.5 ${clicavel(a) ? "cursor-pointer" : ""} ${escolhido && escolhido === a.id_agente ? "bg-[#f1f8f3]" : ""}`}>
            <div className="flex items-baseline justify-between gap-3 text-[13.5px]">
              <span className="truncate font-semibold text-[#0c111d]">{a.agente}</span>
              <span className="shrink-0 font-bold tabular-nums text-[#0c111d]">{reais(a.valor_brl)}</span>
            </div>
            <div className="mt-2 flex items-center gap-2"><BarraFina pct={a.participacao_pct} destaque={a.participacao_pct === maior} /><span className="w-10 text-right text-[11.5px] tabular-nums text-[#667085]">{pct(a.participacao_pct)}</span></div>
            <div className="mt-1.5 text-[11.5px] text-[#667085]">{inteiro(a.conversas)} leads · {rs(a.custo_por_lead_brl)} por lead · {inteiro(a.contratos)} contratos</div>
            <div className="mt-0.5 text-[11.5px] text-[#98A2B3]">{a.contratos ? `${rs(a.custo_por_contrato_brl)} por contrato · ${pct(a.conversao_pct)} conversão · ` : ""}{compacto(a.tokens)} tokens</div>
          </li>
        ))}
      </ul>
      {/* Tela larga: tabela */}
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full text-[13px]">
          <thead><tr className="cr-thead">
            <th className="pl-6">Agente</th><th className="text-right">Gasto</th><th>Participação</th><th className="text-right">Leads</th>
            <th className="text-right">R$ por lead</th><th className="text-right">Contratos</th><th className="text-right">Por contrato</th>
            <th className="text-right">Conversão</th><th className="pr-6 text-right">Tokens</th>
          </tr></thead>
          <tbody>{agentes.map((a) => {
            const ativo = !!escolhido && escolhido === a.id_agente;
            return (
              <tr key={a.id_agente ?? "sem"} onClick={() => alternar(a)}
                className={`border-t border-[#eef2ef] ${clicavel(a) ? "cursor-pointer hover:bg-[#f6f8f7]" : ""} ${ativo ? "bg-[#f1f8f3]" : ""}`}>
                <td className="py-3 pl-6 pr-3"><SeloAgente nome={a.agente} /></td>
                <td className="px-3 py-3 text-right font-bold tabular-nums text-[#0c111d]">{reais(a.valor_brl)}</td>
                <td className="px-3 py-3"><div className="flex items-center gap-2"><BarraFina pct={a.participacao_pct} destaque={a.participacao_pct === maior} largura="w-28" />
                  <span className="w-11 text-right text-[12px] tabular-nums text-[#667085]">{pct(a.participacao_pct)}</span></div></td>
                <td className="px-3 py-3 text-right tabular-nums text-[#344054]">{inteiro(a.conversas)}</td>
                <td className="px-3 py-3 text-right tabular-nums text-[#344054]">{rs(a.custo_por_lead_brl)}</td>
                <td className="px-3 py-3 text-right tabular-nums text-[#344054]">{inteiro(a.contratos)}</td>
                <td className="px-3 py-3 text-right tabular-nums text-[#344054]">{a.contratos ? rs(a.custo_por_contrato_brl) : "—"}</td>
                <td className="px-3 py-3 text-right tabular-nums text-[#344054]">{a.contratos ? pct(a.conversao_pct) : "—"}</td>
                <td className="py-3 pl-3 pr-6 text-right tabular-nums text-[#667085]">{compacto(a.tokens)}</td>
              </tr>
            );
          })}</tbody>
        </table>
      </div>
    </>
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
    <TabelaConversas icone={<History />} titulo="Histórico" sub={`${inteiro(total)} conversas com consumo ${nomePeriodo(dias)}, das mais recentes para as mais antigas.`} dados={r.dados} erro={r.erro}
      rodape={total > POR_PAGINA && (
        <div className="flex items-center justify-end gap-2 border-t border-[#eef2ef] px-5 py-3 text-[12.5px] text-[#667085]">
          <button className="cr-pag" disabled={pagina === 0} onClick={() => setPagina(pagina - 1)} aria-label="Página anterior"><ChevronLeft className="size-4" /></button>
          <span>Página {pagina + 1} de {paginas}</span>
          <button className="cr-pag" disabled={pagina + 1 >= paginas} onClick={() => setPagina(pagina + 1)} aria-label="Próxima página"><ChevronRight className="size-4" /></button>
        </div>
      )} />
  );
}

function TabelaConversas({ icone, titulo, sub, dados, erro, direita, rodape }: {
  icone: ReactNode; titulo: string; sub?: string; dados: Conversas | null; erro?: string | null; direita?: ReactNode; rodape?: ReactNode;
}) {
  return (
    <Bloco icone={icone} titulo={titulo} sub={sub} direita={direita} corpo="pb-2">
      {!dados ? <div className="px-5 pb-4 md:px-6"><Linhas erro={erro} /></div> : dados.conversas.length === 0 ? <div className="px-5 pb-4 md:px-6"><Vazio>Nenhuma conversa com consumo neste período.</Vazio></div> : (
        <>
          {/* Celular: lista simples */}
          <ol className="divide-y divide-[#eef2ef] border-t border-[#eef2ef] lg:hidden">
            {dados.conversas.map((c) => (
              <li key={c.id_lead}>
                <Link to={`/atendimento?lead=${c.id_lead}`} className="flex items-center gap-3 px-5 py-3">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[13.5px] font-semibold text-[#0c111d]">{c.contato || "Sem nome"}{c.contrato_assinado && <SeloContrato />}</div>
                    <div className="truncate text-[11.5px] text-[#667085]">{c.agente} · {quando(c.ultimo_em)} · {inteiro(c.mensagens)} msgs · {compacto(c.tokens)} tokens</div>
                  </div>
                  <span className="text-[13.5px] font-bold tabular-nums text-[#0c111d]">{rs(c.valor_brl)}</span>
                  <ChevronRight className="size-4 shrink-0 text-[#c9d6ce]" />
                </Link>
              </li>
            ))}
          </ol>
          {/* Tela larga: tabela */}
          <div className="hidden px-2 lg:block">
            <table className="w-full text-[13.5px]">
              <thead><tr className="cr-thead">
                <th className="pl-4">Lead</th><th>Agente</th><th>Última atividade</th><th className="text-right">Msgs</th><th className="text-right">Turnos</th>
                <th className="text-right">Tokens</th><th className="text-right">Custo</th><th className="text-right">Por mensagem</th><th className="pr-4" />
              </tr></thead>
              <tbody>{dados.conversas.map((c) => (
                <tr key={c.id_lead} className="cr-linha">
                  <td className="py-3 pl-4 pr-3"><div className="font-semibold text-[#0c111d]">{c.contato || "Sem nome"}{c.contrato_assinado && <SeloContrato />}</div>
                    <div className="text-[12px] tabular-nums text-[#667085]">{c.telefone ?? "—"}</div></td>
                  <td className="px-3 py-3"><SeloAgente nome={c.agente} /></td>
                  <td className="px-3 py-3 tabular-nums text-[#344054]">{quando(c.ultimo_em)}</td>
                  <td className="px-3 py-3 text-right tabular-nums text-[#344054]">{inteiro(c.mensagens)}</td>
                  <td className="px-3 py-3 text-right tabular-nums text-[#344054]">{inteiro(c.turnos)}</td>
                  <td className="px-3 py-3 text-right tabular-nums text-[#344054]">{tokensCurto(c.tokens)}</td>
                  <td className="px-3 py-3 text-right font-bold tabular-nums text-[#0c111d]">{rs(c.valor_brl)}</td>
                  <td className="px-3 py-3 text-right tabular-nums text-[#475467]">{c.mensagens ? `≈ ${rs(c.valor_brl / c.mensagens)}` : "—"}</td>
                  <td className="py-3 pl-3 pr-4 text-right">
                    <Link to={`/atendimento?lead=${c.id_lead}`} className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-xl border border-[#e6ebe8] bg-white px-3 py-1.5 text-[12.5px] font-semibold text-[#1d2939] transition hover:border-[#c9d6ce]">
                      Ver detalhes<ArrowRight className="size-3.5" /></Link>
                  </td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          {rodape}
        </>
      )}
    </Bloco>
  );
}

// ============================================================================ Recargas
function Recargas({ p, dias, recargas, erro, aoMudar }: { p: PainelConsumo; dias: number; recargas: Recarga[] | null; erro: string | null; aoMudar: () => void }) {
  const cr = p.creditos;
  const meses = cr.por_mes.map((m) => ({ ...m, rotulo: `${m.mes.slice(5)}/${m.mes.slice(2, 4)}` }));
  const situacoes = (recargas ?? []).reduce<Record<string, number>>((s, r) => ({ ...s, [r.situacao]: (s[r.situacao] ?? 0) + 1 }), {});
  const pendentes = (recargas ?? []).filter((r) => r.situacao === "pendente");
  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-1 gap-4 min-[480px]:grid-cols-2 lg:grid-cols-4">
        <Kpi icone={<ArrowDownLeft />} cor="verde" rotulo="Total recarregado" valor={reais(cr.recargas_brl)} nota={nomePeriodo(dias)} />
        <Kpi icone={<Sparkles />} cor="roxo" rotulo="Bônus recebido" valor={reais(cr.bonus_brl)} nota={cr.bonus ? `${cr.bonus} bônus no período` : "sem bônus no período"} />
        <Kpi icone={<CheckCircle2 />} cor="azul" rotulo="Recargas confirmadas" valor={inteiro(cr.recargas)} nota="creditadas no saldo" />
        <Kpi icone={<Receipt />} cor="ambar" rotulo="Ticket médio" valor={cr.recargas ? reais(cr.recargas_brl / cr.recargas) : "—"} nota="por recarga" />
      </div>
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <Bloco icone={<IconeLinha />} titulo="Créditos por mês" sub="Recargas (verde) e bônus (cinza) dos últimos 12 meses.">
          {meses.length === 0 ? <Vazio>Nenhum crédito nos últimos 12 meses.</Vazio> : (
            <div className="h-[220px]"><ResponsiveContainer>
              <BarChart data={meses} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid stroke="#eef2ef" vertical={false} />
                <XAxis dataKey="rotulo" tick={EIXO} tickLine={false} axisLine={false} />
                <YAxis tick={EIXO} tickLine={false} axisLine={false} width={58} tickFormatter={(v) => reais(v, 0)} />
                <Tooltip cursor={{ fill: "#f6f8f7" }} contentStyle={DICA} formatter={(v: number, n) => [reais(v), n === "recargas_brl" ? "Recargas" : "Bônus"]} />
                <Bar dataKey="recargas_brl" stackId="a" fill={VERDE_ESCURO} maxBarSize={40} />
                <Bar dataKey="bonus_brl" stackId="a" fill={CINZA_BARRA} radius={[4, 4, 0, 0]} maxBarSize={40} />
              </BarChart>
            </ResponsiveContainer></div>
          )}
        </Bloco>
        <Bloco icone={<Receipt />} titulo="Pedidos de recarga" sub="Situação dos pedidos feitos aqui.">
          {!recargas ? <Linhas erro={erro} /> : recargas.length === 0 ? <Vazio>Nenhum pedido de recarga ainda.</Vazio> : (
            <ul className="flex flex-col gap-4">
              {Object.entries(situacoes).map(([s, n]) => (
                <li key={s}>
                  <div className="flex justify-between text-[13px]"><SeloSituacao s={s} /><span className="tabular-nums text-[#667085]">{n} ({Math.round((n / recargas.length) * 100)}%)</span></div>
                  <div className="mt-1.5"><BarraFina pct={(n / recargas.length) * 100} destaque={s === "paga"} cor={s === "pendente" ? "#f79009" : undefined} /></div>
                </li>
              ))}
            </ul>
          )}
        </Bloco>
      </div>
      {pendentes.length > 0 && (
        <Bloco icone={<AlertTriangle />} titulo="Aguardando pagamento"><ListaRecargas recargas={pendentes} aoMudar={aoMudar} cancelavel /></Bloco>
      )}
      <Bloco icone={<Receipt />} titulo="Todos os pedidos de recarga">
        {!recargas ? <Linhas erro={erro} /> : recargas.length === 0 ? <Vazio>Nenhum pedido de recarga ainda.</Vazio> : <ListaRecargas recargas={recargas} aoMudar={aoMudar} />}
      </Bloco>
    </div>
  );
}

// ============================================================================ Avançado
function Avancado({ p }: { p: PainelConsumo }) {
  const { escritorio } = useSessao();
  const extrato = useCarregar<Movimento[]>("/carteira/extrato?limite=300", [escritorio]);
  return (
    <div className="flex flex-col gap-5">
      <Previsao p={p} />
      <Ranking p={p} />
      <LinhaDoTempo movimentos={extrato.dados} erro={extrato.erro} />
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
    <Bloco icone={<TrendingUp />} titulo="Previsão de 30 dias" sub="Projeção pelo seu gasto médio dos últimos 30 dias (estimativa).">
      <dl className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        {[["Gasto projetado (30d)", media ? reais(media * 30) : "—"], ["Saldo no fim do mês", media ? reais(disp - media * restantes) : reais(disp)],
          ["Saldo acaba em", dias == null ? "sem consumo" : new Date(hoje.getTime() + dias * 86400000).toLocaleDateString("pt-BR")]].map(([r, v]) => (
          <div key={r} className="rounded-xl bg-[#f1f4f2] px-3.5 py-3"><dt className="text-[12px] text-[#667085]">{r}</dt><dd className="mt-0.5 text-[17px] font-bold tabular-nums text-[#0c111d]">{v}</dd></div>
        ))}
      </dl>
      {media ? (
        <div className="mt-4 h-[190px]"><ResponsiveContainer>
          <LineChart data={curva} margin={{ top: 6, right: 6, left: 0, bottom: 0 }}>
            <CartesianGrid stroke="#eef2ef" vertical={false} />
            <XAxis dataKey="rotulo" tick={EIXO} tickLine={false} axisLine={false} minTickGap={24} />
            <YAxis tick={EIXO} tickLine={false} axisLine={false} width={58} tickFormatter={(v) => reais(v, 0)} />
            <Tooltip cursor={{ stroke: "#c9d6ce" }} contentStyle={DICA} formatter={(v: number) => [reais(v), "Saldo previsto"]} />
            <Line type="monotone" dataKey="saldo" stroke={VERDE_ESCURO} strokeWidth={2} strokeDasharray="5 5" dot={false} activeDot={{ r: 4, strokeWidth: 0, fill: VERDE_ESCURO }} />
          </LineChart>
        </ResponsiveContainer></div>
      ) : <div className="mt-4"><Vazio>Sem histórico para projetar.</Vazio></div>}
    </Bloco>
  );
}

function Ranking({ p }: { p: PainelConsumo }) {
  const lista = p.por_agente.filter((a) => a.custo_por_lead_brl).sort((a, b) => (a.custo_por_lead_brl ?? 0) - (b.custo_por_lead_brl ?? 0));
  return (
    <Bloco icone={<Target />} titulo="Ranking de eficiência" sub="Quem atende mais leads com o mesmo dinheiro (menor R$ por lead primeiro)." corpo="pb-2">
      {lista.length === 0 ? <div className="px-5 pb-3 md:px-6"><Vazio>Sem dados de eficiência neste período.</Vazio></div> : (
        <div className="overflow-x-auto"><table className="w-full min-w-[560px] text-[13px]">
          <thead><tr className="cr-thead">
            <th className="pl-6">#</th><th>Agente</th><th className="text-right">R$ por lead</th>
            <th className="text-right">Leads com R$ 100</th><th className="text-right">Contratos</th><th className="pr-6 text-right">Custo por contrato</th></tr></thead>
          <tbody>{lista.map((a, i) => (
            <tr key={a.id_agente ?? "sem"} className="border-t border-[#eef2ef]">
              <td className="py-3 pl-6 pr-3"><span className={`grid size-6 place-items-center rounded-full text-[11px] font-bold ${i === 0 ? "bg-[#0a8f35] text-white" : "bg-[#f1f4f2] text-[#475467]"}`}>{i + 1}</span></td>
              <td className="px-3 py-3"><SeloAgente nome={a.agente} /></td>
              <td className="px-3 py-3 text-right font-bold tabular-nums text-[#0c111d]">{rs(a.custo_por_lead_brl)}</td>
              <td className="px-3 py-3 text-right tabular-nums text-[#344054]">≈ {inteiro(Math.floor(100 / (a.custo_por_lead_brl ?? 1)))}</td>
              <td className="px-3 py-3 text-right tabular-nums text-[#344054]">{inteiro(a.contratos)}</td>
              <td className="py-3 pl-3 pr-6 text-right tabular-nums text-[#344054]">{rs(a.custo_por_contrato_brl)}</td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
    </Bloco>
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
    <Bloco icone={<History />} titulo="Linha do tempo" sub="Recargas, bônus e consumo em ordem cronológica." corpo="pb-2">
      {!movimentos ? <div className="px-5 pb-4 md:px-6"><Linhas erro={erro} /></div> : itens.length === 0 ? <div className="px-5 pb-4 md:px-6"><Vazio>Nenhum movimento ainda.</Vazio></div> : (
        <>
          <ul className="divide-y divide-[#eef2ef] border-t border-[#eef2ef]">
            {visiveis.map((i) => (
              <li key={i.id} className="flex items-center gap-3 px-5 py-3 md:px-6">
                <span className={`grid size-8 shrink-0 place-items-center rounded-lg ${i.entrada ? "bg-[#e7f7ec] text-[#0a8f35]" : "bg-[#f1f4f2] text-[#667085]"}`}>
                  {i.entrada ? <ArrowDownLeft className="size-4" /> : <ArrowUpRight className="size-4" />}
                </span>
                <div className="min-w-0 flex-1"><div className="text-[13.5px] font-semibold text-[#0c111d]">{i.titulo}</div>
                  <div className="truncate text-[11.5px] text-[#98A2B3]">{i.detalhe} · {dataCurta(i.quando)}</div></div>
                <span className={`shrink-0 text-[13.5px] font-bold tabular-nums ${i.entrada ? "text-[#0a8f35]" : "text-[#0c111d]"}`}>{i.entrada ? "+" : ""}{rs(i.valor)}</span>
              </li>
            ))}
          </ul>
          {itens.length > 8 && <div className="border-t border-[#eef2ef] px-5 py-3 md:px-6"><BotaoTexto onClick={() => setMais(!mais)} seta={false}>{mais ? "Mostrar menos" : `Mostrar todos (${itens.length})`}</BotaoTexto></div>}
        </>
      )}
    </Bloco>
  );
}

function ComoFunciona() {
  const passos = [
    { t: "Bônus do mês", d: "É o primeiro crédito a sair." },
    { t: "Saldo de recarga", d: "Entra depois do bônus e não expira." },
    { t: "Saldo zerado", d: "A IA pausa e volta sozinha quando a recarga entra." },
  ];
  const termos = [
    { i: <ArrowRight />, t: "Entrada", d: "Tudo que a IA lê para responder: instruções do agente, histórico e a mensagem do lead." },
    { i: <Sparkles />, t: "Saída", d: "A resposta escrita pela IA. Costuma custar mais por token que a entrada." },
    { i: <Cpu />, t: "Modelo", d: "Modelos mais inteligentes custam mais por token. Cada agente pode usar um modelo diferente." },
  ];
  return (
    <section className="cr-cartao rounded-[22px] p-5 md:p-6">
      <div className="flex items-start gap-3">
        <IconeCaixa cor="verde"><BookOpen /></IconeCaixa>
        <div className="min-w-0 flex-1">
          <h3 className="text-[16px] font-bold text-[#0c111d]">Como funcionam os créditos</h3>
          <p className="mt-0.5 text-[13px] leading-relaxed text-[#475467]">
            Cada vez que um agente lê uma mensagem e responde, a IA processa tokens (pedaços de texto). O custo de cada lead é a soma de todas as respostas,
            leituras de áudio, imagem e documento e follow-ups daquela conversa.
          </p>
        </div>
        <span className="hidden shrink-0 rounded-full bg-[#e7f7ec] px-2.5 py-1 text-[11.5px] font-bold text-[#0a8f35] sm:inline">Bom saber</span>
      </div>
      <ol className="mt-5 grid gap-3 md:grid-cols-3">
        {passos.map((s, i) => (
          <li key={s.t} className={`flex items-center gap-3.5 rounded-2xl border p-4 ${i === 0 ? "border-[#7fd49a] bg-[#ecf9f0] shadow-[0_10px_24px_-14px_rgba(10,143,53,.45)]" : "border-[#e6ebe8] bg-white"}`}>
            <span className={`cr-passo ${i === 0 ? "cr-passo-ativo" : ""}`} aria-hidden>{i + 1}</span>
            <div className="min-w-0"><div className="text-[14px] font-bold text-[#0c111d]">{s.t}</div><div className="text-[12.5px] text-[#475467]">{s.d}</div></div>
          </li>
        ))}
      </ol>
      <dl className="mt-3 grid gap-3 md:grid-cols-3">
        {termos.map((c) => (
          <div key={c.t} className="rounded-2xl bg-[#f1f4f2] p-4">
            <dt className="flex items-center gap-1.5 text-[12px] font-bold uppercase tracking-[.12em] text-[#1d2939] [&>svg]:size-3.5 [&>svg]:text-[#0a8f35]">{c.i}{c.t}</dt>
            <dd className="mt-1.5 text-[13px] leading-relaxed text-[#475467]">{c.d}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-4 flex items-center gap-2 text-[12.5px] text-[#667085]"><Info className="size-3.5 shrink-0" />Tudo é cobrado em créditos (R$) numa conta só. Cada conversa mostra o custo real dela.</p>
    </section>
  );
}

// ============================================================================ peças
type Cor = "verde" | "azul" | "ambar" | "roxo";
const CORES_ICONE: Record<Cor, string> = {
  verde: "bg-[#e4f6ea] text-[#0a8f35]", azul: "bg-[#e8efff] text-[#2563eb]", ambar: "bg-[#fff1dc] text-[#c2620a]", roxo: "bg-[#f1eaff] text-[#7c3aed]",
};
const IconeCaixa = ({ cor, children }: { cor: Cor; children: ReactNode }) => (
  <span className={`grid size-10 shrink-0 place-items-center rounded-xl [&>svg]:size-[18px] ${CORES_ICONE[cor]}`}>{children}</span>
);

/** Bloco padrão: cartão branco arredondado, ícone em caixinha verde suave, título e subtítulo. `corpo` troca o recuo (tabelas encostam nas bordas). */
function Bloco({ icone, titulo, sub, direita, corpo = "px-5 pb-5 md:px-6 md:pb-6", children }: {
  icone: ReactNode; titulo: string; sub?: string; direita?: ReactNode; corpo?: string; children: ReactNode;
}) {
  return (
    <section className="cr-cartao min-w-0 rounded-[22px]">
      <div className="flex items-start justify-between gap-3 px-5 pb-4 pt-5 md:px-6">
        <div className="flex min-w-0 items-start gap-3">
          <IconeCaixa cor="verde">{icone}</IconeCaixa>
          <div className="min-w-0"><h3 className="text-[16px] font-bold text-[#0c111d]">{titulo}</h3>{sub && <p className="mt-0.5 text-[13px] text-[#667085]">{sub}</p>}</div>
        </div>
        {direita}
      </div>
      <div className={corpo}>{children}</div>
    </section>
  );
}

function Kpi({ icone, cor, rotulo, valor, nota, extra, pequeno }: { icone: ReactNode; cor: Cor; rotulo: string; valor: string; nota?: string; extra?: ReactNode; pequeno?: boolean }) {
  return (
    <div className="cr-cartao relative min-w-0 rounded-[20px] p-4 md:p-5">
      <div className="flex items-center gap-2.5">
        <span className={`grid size-8 shrink-0 place-items-center rounded-lg [&>svg]:size-4 ${CORES_ICONE[cor]}`}>{icone}</span>
        <span className="truncate text-[13.5px] text-[#344054]">{rotulo}</span>
      </div>
      <div className={`mt-3 truncate font-extrabold tracking-[-0.02em] tabular-nums text-[#0c111d] ${pequeno ? "text-[20px]" : "text-[28px] leading-tight"}`}>{valor}</div>
      {nota && <div className="mt-1 text-[12px] leading-snug text-[#667085]">{nota}</div>}
      {extra}
    </div>
  );
}

/** Mini linha do KPI "Créditos usados". */
function MiniLinha({ valores }: { valores: number[] }) {
  if (valores.length < 2) return null;
  const max = Math.max(...valores) || 1;
  const L = 80, A = 26;
  const pts = valores.map((v, i) => `${((i / (valores.length - 1)) * L).toFixed(1)},${(A - 2 - (v / max) * (A - 4)).toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${L} ${A}`} className="absolute bottom-4 right-4 h-[26px] w-[80px]" aria-hidden>
      <polyline points={pts} fill="none" stroke={VERDE_ESCURO} strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

/** Barra fina: verde só quando é o destaque (o maior); cinza no resto. */
const BarraFina = ({ pct, destaque, cor, largura = "flex-1", altura = "h-1.5" }: { pct: number; destaque?: boolean; cor?: string; largura?: string; altura?: string }) => (
  <div className={`${largura} ${altura} min-w-[40px] overflow-hidden rounded-full bg-[#eef2ef]`}>
    <div className="cr-barra h-full rounded-full" style={{ width: `${Math.min(100, Math.max(0, pct))}%`, background: cor ?? (destaque ? VERDE_ESCURO : CINZA_BARRA) }} />
  </div>
);
const BotaoTexto = ({ onClick, children, seta = true }: { onClick: () => void; children: ReactNode; seta?: boolean }) => (
  <button onClick={onClick} className="inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg px-2 py-1 text-[13px] font-semibold text-[#1d2939] transition hover:bg-[#f1f4f2]">
    {children}{seta && <ArrowRight className="size-3.5" />}
  </button>
);
const SeloAgente = ({ nome }: { nome: string }) => (
  <span className="inline-flex max-w-[200px] items-center gap-1.5 rounded-full bg-[#e7f7ec] px-2.5 py-1 text-[12px] font-semibold text-[#0a8f35]">
    <Bot className="size-3.5 shrink-0" /><span className="truncate">{nome}</span>
  </span>
);
const SeloContrato = () => <span className="ml-1.5 inline-flex items-center rounded-full bg-[#e7f7ec] px-1.5 py-px align-middle text-[10px] font-bold text-[#0a8f35]">contrato</span>;
const NOME_SITUACAO: Record<string, [string, string, string]> = {
  paga: ["Confirmada", "#0a6b2a", "#e7f7ec"], pendente: ["Aguardando", "#93370d", "#fff1dc"], cancelada: ["Cancelada", "#475467", "#f1f4f2"],
  expirada: ["Expirada", "#475467", "#f1f4f2"], estornada: ["Estornada", "#b42318", "#fef3f2"],
};
const SeloSituacao = ({ s }: { s: string }) => {
  const [t, cor, fundo] = NOME_SITUACAO[s] ?? [s, "#475467", "#f1f4f2"];
  return <span className="inline-flex shrink-0 items-center rounded-full px-2.5 py-1 text-[11.5px] font-bold" style={{ color: cor, background: fundo }}>{t}</span>;
};
const Vazio = ({ children }: { children: ReactNode }) => (
  <div className="rounded-2xl border border-dashed border-[#d5ddd8] px-4 py-8 text-center text-[13px] text-[#667085]">{children}</div>
);
const Linhas = ({ erro }: { erro?: string | null }) => erro
  ? <p className="text-[13px] text-[#b42318]">{erro}</p>
  : <div className="flex flex-col gap-2">{[0, 1, 2].map((i) => <div key={i} className="cr-brilho h-10 rounded-xl" />)}</div>;
const Esqueleto = ({ altura, erro }: { altura: number; erro?: string | null }) => erro
  ? <div className="cr-cartao rounded-[22px] p-5 text-[13px] text-[#b42318]">{erro}</div>
  : <div className="cr-brilho rounded-[26px]" style={{ height: altura }} />;

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
