// Gráficos leves (SVG/CSS, components/graficos) do Painel Inicial, com os dados de GET /api/relatorios/dashboard
// (últimos 30 dias): faixa de Leads/Contratos/Custo da IA, anel da conversão e "Quando seus leads chegam".
import { useMemo } from "react";
import { Link } from "react-router-dom";
import { Bot, CircleDollarSign, Clock, FileSignature, Target } from "lucide-react";
import FaixaMetricas, { type Metrica } from "@/components/graficos/FaixaMetricas";
import MedidorMeta from "@/components/graficos/MedidorMeta";
import MapaCalor from "@/components/graficos/MapaCalor";
import "./inicioNovo.css";

/** Só o que o Painel Inicial usa do dashboard de relatórios. */
export interface DashboardResumo {
  periodo: { de: string; ate: string; dias: number };
  kpis: {
    leads: number; leads_variacao: number | null; assinados: number; assinados_variacao: number | null;
    conversao: number | null; conversao_anterior: number | null; qualificados: number;
    primeira_resposta_s: number | null; custo_brl: number; custo_variacao: number | null;
  };
  serie: { dia: string; leads: number; assinados: number; custo_brl: number }[];
  horarios: { leads: number[][]; assinados: number[][] };
}

const curta = (d: string) => `${d.slice(8, 10)}/${d.slice(5, 7)}`;
const fmtBRL = (v: number) => v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
const DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"];

export function GraficosInicio({ d, mostrarCusto }: { d: DashboardResumo; mostrarCusto: boolean }) {
  const k = d.kpis;
  const metricas = useMemo<Metrica[]>(() => {
    const lista: Metrica[] = [
      { rotulo: "Leads", valor: k.leads, icone: Bot, variacao: k.leads_variacao, sub: `nos últimos ${d.periodo.dias} dias`,
        serie: d.serie.map((s) => ({ rotulo: curta(s.dia), valor: s.leads })) },
      { rotulo: "Contratos assinados", valor: k.assinados, icone: FileSignature, variacao: k.assinados_variacao, sub: `nos últimos ${d.periodo.dias} dias`,
        serie: d.serie.map((s) => ({ rotulo: curta(s.dia), valor: s.assinados })) },
    ];
    if (mostrarCusto) lista.push({ rotulo: "Custo da IA", valor: k.custo_brl, formatar: fmtBRL, icone: CircleDollarSign, variacao: k.custo_variacao,
      inverter: true, cor: "#00852A", sub: `nos últimos ${d.periodo.dias} dias`, serie: d.serie.map((s) => ({ rotulo: curta(s.dia), valor: s.custo_brl })) });
    return lista;
  }, [d, k, mostrarCusto]);

  const pico = useMemo(() => {
    let m = { v: 0, dia: 0, hora: 0 };
    d.horarios.leads.forEach((l, dia) => l.forEach((v, hora) => { if (v > m.v) m = { v, dia, hora }; }));
    return m;
  }, [d.horarios.leads]);

  return (
    <div className="lc-ini-graficos">
      <FaixaMetricas metricas={metricas} />
      <div className="lc-ini-graficos__linha">
        <section className="lc-ini-cartao lc-ini-cartao--calor" aria-label="Quando seus leads chegam">
          <header className="lc-ini-cartao__cab">
            <h3><Clock aria-hidden /> Quando seus leads chegam</h3>
            <Link to="/relatorios/dashboard" className="lc-ini-link">Ver relatórios</Link>
          </header>
          <p className="lc-ini-cartao__sub">
            {pico.v > 0
              ? <>Mais leads chegam na <b>{DIAS[pico.dia]} às {String(pico.hora).padStart(2, "0")}h</b>. Dia da semana × hora, horário de Brasília.</>
              : "Dia da semana × hora, horário de Brasília. Ainda não chegaram leads no período."}
          </p>
          <MapaCalor grade={d.horarios.leads} unidade="lead" />
        </section>
        <section className="lc-ini-cartao lc-ini-cartao--meta" aria-label="Conversão">
          <header className="lc-ini-cartao__cab"><h3><Target aria-hidden /> Conversão</h3></header>
          <p className="lc-ini-cartao__sub">Leads que viraram contrato assinado</p>
          <div className="lc-ini-cartao__centro">
            <MedidorMeta rotulo="Leads → contrato" valor={k.conversao} tamanho={148} atraso={0.15}
              sub={`${k.assinados.toLocaleString("pt-BR")} de ${k.leads.toLocaleString("pt-BR")} leads`}
              referencia={k.conversao_anterior != null ? { valor: k.conversao_anterior, rotulo: "antes" } : null} />
          </div>
        </section>
      </div>
    </div>
  );
}
