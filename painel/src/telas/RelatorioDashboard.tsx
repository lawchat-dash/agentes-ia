/*
 * Relatórios › Dashboard: indicadores da safra de leads do período (funil até o contrato), atendimento da IA
 * (respostas, tempo, erros e custo), agentes, etapas atuais, origem, mapa por estado, horários e os cards do CRM.
 * Dados: GET /api/relatorios/dashboard (só as nossas tabelas; ver app/gestao/rotas_relatorios.py).
 */
import { useState } from "react";
import { Link } from "react-router-dom";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import {
  Bot, CircleDollarSign, Clock, FileSignature, Filter, Gauge, MessageSquare, Percent, ShieldAlert, Sparkles, Target,
  UserCheck, UserX, Users,
} from "lucide-react";
import { toast } from "sonner";
import { enviar } from "../api";
import { Carregando, useCarregar } from "../componentes/ui";
import { useSessao } from "../sessao";
import { ContatosPorEstado } from "@/components/dashboard/ContatosPorEstado";
import {
  Abas, BarraFiltros, Barrinha, BotaoCsv, COR_FASE, CORES, Cartao, Funil, Kpi, MapaDeCalor, SemDados, Topo, baixarCsv,
  fmtBRL, fmtData, fmtDia, fmtHoras, fmtNum, fmtPct, fmtSegundos, textoPeriodo, useFiltros, type EtapaFunil,
} from "./relatoriosComum";

interface Dashboard {
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
  serie: { dia: string; leads: number; assinados: number; respostas_ia: number; mensagens_lead: number; mensagens_equipe: number;
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

type Serie = "leads" | "assinados" | "respostas_ia" | "custo_brl";
const SERIES: { valor: Serie; rotulo: string; cor: string }[] = [
  { valor: "leads", rotulo: "Leads", cor: "#00BC33" }, { valor: "assinados", rotulo: "Contratos", cor: "#6366F1" },
  { valor: "respostas_ia", rotulo: "Respostas da IA", cor: "#0EA5E9" }, { valor: "custo_brl", rotulo: "Custo da IA", cor: "#F59E0B" },
];

export function TelaRelatorioDashboard() {
  const { escritorio } = useSessao();
  const { filtros, mudar, consulta } = useFiltros();
  const dados = useCarregar<Dashboard>(escritorio ? `/relatorios/dashboard?${consulta}` : null, [escritorio, consulta]);
  const [serie, setSerie] = useState<Serie>("leads");
  const [calor, setCalor] = useState<"leads" | "assinados">("leads");
  const [pedindo, setPedindo] = useState(false);
  const d = dados.dados;

  const exportar = () => {
    if (!d) return;
    const k = d.kpis;
    baixarCsv(`dashboard-${d.periodo.de}-a-${d.periodo.ate}.csv`, ["Seção", "Item", "Valor"], [
      ["Indicadores", "Leads", k.leads], ["Indicadores", "Contratos assinados", k.assinados],
      ["Indicadores", "Taxa de conversão (%)", k.conversao], ["Indicadores", "Taxa de eficiência (%)", k.eficiencia],
      ["Indicadores", "Leads qualificados", k.qualificados], ["Indicadores", "Desqualificados", k.desqualificados],
      ["Indicadores", "Respostas da IA", k.respostas_ia], ["Indicadores", "Primeira resposta (s)", k.primeira_resposta_s],
      ["Indicadores", "Custo da IA (R$)", k.custo_brl], ["Indicadores", "Custo por lead (R$)", k.custo_por_lead],
      ["Indicadores", "Custo por contrato (R$)", k.custo_por_contrato],
      ...d.funil.map((e) => ["Funil", e.nome, e.chegaram] as (string | number)[]),
      ...d.agentes.map((a) => ["Agentes", a.nome, `${a.leads} leads, ${a.assinados} contratos`] as (string | number)[]),
      ...d.plataformas.map((p) => ["Origem", p.nome, p.leads] as (string | number)[]),
    ]);
    baixarCsv(`dashboard-por-dia-${d.periodo.de}-a-${d.periodo.ate}.csv`,
      ["Dia", "Leads", "Contratos assinados", "Respostas da IA", "Mensagens dos leads", "Mensagens da equipe", "Respostas com erro", "Custo da IA (R$)"],
      d.serie.map((s) => [s.dia, s.leads, s.assinados, s.respostas_ia, s.mensagens_lead, s.mensagens_equipe, s.erros, s.custo_brl]));
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
    <div className="rl">
      <Topo titulo="Dashboard" carregando={dados.carregando} aoAtualizar={dados.recarregar}
        texto={<>Leads que entraram {textoPeriodo(filtros.de, filtros.ate)} e até onde cada um já chegou; atendimento e custo da IA no mesmo período.</>}
        acoes={<BotaoCsv aoClicar={exportar} />} />
      <BarraFiltros filtros={filtros} mudar={mudar} />
      {!d ? <Carregando erro={dados.erro} /> : <Conteudo d={d} serie={serie} setSerie={setSerie} calor={calor} setCalor={setCalor}
        pedirImportacao={pedirImportacao} pedindo={pedindo} filtrando={Boolean(filtros.agente || filtros.campanha || filtros.fonte)} />}
    </div>
  );
}

function Conteudo({ d, serie, setSerie, calor, setCalor, pedirImportacao, pedindo, filtrando }: {
  d: Dashboard; serie: Serie; setSerie: (s: Serie) => void; calor: "leads" | "assinados"; setCalor: (c: "leads" | "assinados") => void;
  pedirImportacao: () => void; pedindo: boolean; filtrando: boolean;
}) {
  const k = d.kpis;
  const s = SERIES.find((x) => x.valor === serie)!;
  const maxAgente = Math.max(1, ...d.agentes.map((a) => a.leads));
  const totalFaixas = d.tempo_ate_assinar.faixas.reduce((t, f) => t + f.total, 0);
  return (
    <>
      <div className="rl-kpis rl-kpis-5">
        <Kpi rotulo="Leads no período" valor={fmtNum(k.leads)} variacao={k.leads_variacao} icone={<Users />}
          detalhe={`${fmtNum(k.com_origem)} vieram de anúncio ou UTM`} />
        <Kpi rotulo="Contratos assinados" valor={fmtNum(k.assinados)} variacao={k.assinados_variacao} icone={<FileSignature />} tom="roxo"
          detalhe="dos leads que entraram no período" />
        <Kpi rotulo="Taxa de conversão" valor={fmtPct(k.conversao)} icone={<Percent />} tom="azul"
          detalhe={k.conversao_anterior != null ? `antes: ${fmtPct(k.conversao_anterior)}` : "assinados ÷ leads"} />
        <Kpi rotulo="Taxa de eficiência" valor={fmtPct(k.eficiencia)} icone={<Target />} tom="azul"
          detalhe="assinados ÷ leads que passaram do SDR" />
        <Kpi rotulo="Leads qualificados" valor={fmtPct(k.qualificados_pct)} icone={<UserCheck />}
          detalhe={`${fmtNum(k.qualificados)} chegaram ao Closer ou além`} />
        <Kpi rotulo="Desqualificados" valor={fmtPct(k.desqualificados_pct)} icone={<UserX />} tom="vermelho"
          detalhe={`${fmtNum(k.desqualificados)} leads`} />
        <Kpi rotulo="Respostas da IA" valor={fmtNum(k.respostas_ia)} icone={<MessageSquare />} tom="azul"
          detalhe={`${fmtNum(k.mensagens_lead)} mensagens dos leads`} />
        <Kpi rotulo="Primeira resposta" valor={fmtSegundos(k.primeira_resposta_s)} icone={<Clock />} tom="ambar"
          detalhe={k.primeira_resposta_mediana_s != null ? `mediana ${fmtSegundos(k.primeira_resposta_mediana_s)}` : "tempo até a IA responder"} />
        <Kpi rotulo="Custo da IA" valor={fmtBRL(k.custo_brl)} variacao={k.custo_variacao} inverter icone={<CircleDollarSign />} tom="ambar"
          detalhe={`${fmtBRL(k.custo_por_lead)} por lead`} />
        <Kpi rotulo="Custo por contrato" valor={fmtBRL(k.custo_por_contrato)} icone={<Gauge />} tom="cinza"
          detalhe={`${fmtNum(k.chamadas_ia)} chamadas à IA`} />
      </div>

      <div className="rl-grade">
        <Cartao classe="rl-c7" titulo="Funil até o contrato" subtitulo="Quantos leads chegaram a cada etapa (SDR → Closer → Contratos → Assinatura → Assinado)">
          <Funil etapas={d.funil} total={k.leads} />
          <div className="rl-legenda">
            <span><i className="rl-ponto" style={{ background: COR_FASE.desqualificado }} />Desqualificados: <b className="num">{fmtNum(d.desvios.desqualificados)}</b></span>
            <span><i className="rl-ponto" style={{ background: COR_FASE.analise }} />Passaram pela análise da equipe: <b className="num">{fmtNum(d.desvios.analise)}</b></span>
          </div>
        </Cartao>
        <Cartao classe="rl-c5" titulo="Onde os leads estão agora" subtitulo="Etapa atual dos leads do período">
          {d.por_fase.length ? (
            <div className="rl-dois">
              <div className="rl-grafico rl-grafico-baixo">
                <ResponsiveContainer>
                  <PieChart>
                    <Pie data={d.por_fase} dataKey="leads" nameKey="nome" innerRadius="55%" outerRadius="90%" paddingAngle={2}>
                      {d.por_fase.map((f, i) => <Cell key={f.fase} fill={COR_FASE[f.fase] ?? CORES[i % CORES.length]} />)}
                    </Pie>
                    <Tooltip formatter={(v: number) => fmtNum(v)} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <div className="rl-lista">
                {d.por_fase.map((f, i) => (
                  <div key={f.fase} className="rl-crm-coluna">
                    <span><i className="rl-ponto" style={{ background: COR_FASE[f.fase] ?? CORES[i % CORES.length], marginRight: 6 }} />{f.nome}</span>
                    <b className="num">{fmtNum(f.leads)} <small>{fmtPct(k.leads ? (f.leads / k.leads) * 100 : null, 0)}</small></b>
                  </div>
                ))}
              </div>
            </div>
          ) : <SemDados>Sem leads no período.</SemDados>}
        </Cartao>

        <Cartao classe="rl-c12" titulo="Evolução por dia" subtitulo="Leads que entraram, contratos assinados, respostas e custo da IA"
          acoes={<Abas valor={serie} aoMudar={setSerie} opcoes={SERIES.map((x) => ({ valor: x.valor, rotulo: x.rotulo }))} />}>
          <div className="rl-grafico">
            <ResponsiveContainer>
              <AreaChart data={d.serie} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
                <defs>
                  <linearGradient id="rl-grad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={s.cor} stopOpacity={0.35} /><stop offset="100%" stopColor={s.cor} stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="#E2E8F0" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="dia" tickFormatter={fmtDia} tick={{ fontSize: 11, fill: "#64748B" }} minTickGap={18} />
                <YAxis tick={{ fontSize: 11, fill: "#64748B" }} allowDecimals={serie === "custo_brl"} width={48}
                  tickFormatter={(v) => (serie === "custo_brl" ? `R$${v}` : fmtNum(v))} />
                <Tooltip labelFormatter={(v) => fmtData(String(v) + "T12:00:00")}
                  formatter={(v: number) => [serie === "custo_brl" ? fmtBRL(v) : fmtNum(v), s.rotulo]} />
                <Area type="monotone" dataKey={serie} stroke={s.cor} strokeWidth={2} fill="url(#rl-grad)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Cartao>

        <Cartao classe="rl-c7" titulo="Atendimento da IA" subtitulo="Cada vez que a IA processou mensagens de um lead no período">
          <div className="rl-mini">
            <div><small>Respostas enviadas</small><b className="num">{fmtNum(d.ia.respondidos)}</b></div>
            <div><small>Sem resposta (de propósito)</small><b className="num">{fmtNum(d.ia.sem_resposta)}</b></div>
            <div><small>Com erro</small><b className="num">{fmtNum(d.ia.erros)}</b> <span className="muted">{fmtPct(d.ia.taxa_erro)}</span></div>
            <div><small>Trocas de etapa pela IA</small><b className="num">{fmtNum(d.ia.trocas)}</b></div>
            <div><small>Tempo para responder</small><b className="num">{fmtSegundos(d.ia.duracao_media_s)}</b></div>
            <div><small>Mensagens da equipe</small><b className="num">{fmtNum(k.mensagens_equipe)}</b></div>
          </div>
          <div className="rl-grafico rl-grafico-baixo">
            <ResponsiveContainer>
              <BarChart data={d.serie} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
                <CartesianGrid stroke="#E2E8F0" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="dia" tickFormatter={fmtDia} tick={{ fontSize: 11, fill: "#64748B" }} minTickGap={18} />
                <YAxis tick={{ fontSize: 11, fill: "#64748B" }} allowDecimals={false} width={40} />
                <Tooltip labelFormatter={(v) => fmtData(String(v) + "T12:00:00")} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="turnos" name="Respondidas" stackId="a" fill="#0EA5E9" radius={[0, 0, 0, 0]} />
                <Bar dataKey="erros" name="Com erro" stackId="a" fill="#EF4444" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Cartao>

        <Cartao classe="rl-c5" titulo="Tempo até assinar" subtitulo="Da entrada do lead até a assinatura do contrato">
          {k.assinados ? (
            <>
              <div className="rl-mini">
                <div><small>Média</small><b className="num">{fmtHoras(d.tempo_ate_assinar.media_horas)}</b></div>
                <div><small>Mediana</small><b className="num">{fmtHoras(d.tempo_ate_assinar.mediana_horas)}</b></div>
              </div>
              <div className="rl-lista">
                {d.tempo_ate_assinar.faixas.map((f, i) => (
                  <div key={f.faixa} className="rl-crm-coluna">
                    <span>{f.faixa}<Barrinha valor={f.total} maximo={Math.max(1, ...d.tempo_ate_assinar.faixas.map((x) => x.total))} cor={CORES[i]} /></span>
                    <b className="num">{fmtNum(f.total)} <small>{fmtPct(totalFaixas ? (f.total / totalFaixas) * 100 : null, 0)}</small></b>
                  </div>
                ))}
              </div>
            </>
          ) : <SemDados>Nenhum contrato assinado entre os leads do período.</SemDados>}
        </Cartao>

        <Cartao classe="rl-c7" titulo="Desempenho por agente" subtitulo="Leads de cada agente no período e até onde foram">
          {d.agentes.length ? (
            <div className="rl-tabela-caixa">
              <table className="rl-tabela">
                <thead><tr><th>Agente</th><th className="n">Leads</th><th className="n">Qualificados</th><th className="n">Contratos</th>
                  <th className="n">Assinados</th><th className="n">Conversão</th></tr></thead>
                <tbody>
                  {d.agentes.map((a) => (
                    <tr key={a.id_agente ?? "sem"}>
                      <td className="rl-nome">{a.id_agente ? <Link to={`/agentes/${a.id_agente}`}><b>{a.nome}</b></Link> : <b>{a.nome}</b>}</td>
                      <td className="n num">{fmtNum(a.leads)}<Barrinha valor={a.leads} maximo={maxAgente} /></td>
                      <td className="n num">{fmtNum(a.qualificados)}</td>
                      <td className="n num">{fmtNum(a.contratos)}</td>
                      <td className="n num">{fmtNum(a.assinados)}</td>
                      <td className="n num">{fmtPct(a.conversao)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <SemDados>Nenhum agente recebeu leads no período.</SemDados>}
        </Cartao>

        <Cartao classe="rl-c5" titulo="De onde vieram" subtitulo="Origem do primeiro contato (anúncio ou UTM)">
          {d.plataformas.length ? (
            <div className="rl-dois">
              <div className="rl-grafico rl-grafico-baixo">
                <ResponsiveContainer>
                  <PieChart>
                    <Pie data={d.plataformas} dataKey="leads" nameKey="nome" innerRadius="55%" outerRadius="90%" paddingAngle={2}>
                      {d.plataformas.map((p, i) => <Cell key={p.plataforma} fill={p.plataforma === "direto" ? "#CBD5E1" : CORES[i % CORES.length]} />)}
                    </Pie>
                    <Tooltip formatter={(v: number) => fmtNum(v)} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <div className="rl-lista">
                {d.plataformas.map((p, i) => (
                  <div key={p.plataforma} className="rl-crm-coluna">
                    <span><i className="rl-ponto" style={{ background: p.plataforma === "direto" ? "#CBD5E1" : CORES[i % CORES.length], marginRight: 6 }} />{p.nome}</span>
                    <b className="num">{fmtNum(p.leads)} <small>{fmtNum(p.assinados)} contr.</small></b>
                  </div>
                ))}
                <Link to="/relatorios/campanhas" className="rl-nota">Ver o rastreamento de campanhas →</Link>
              </div>
            </div>
          ) : <SemDados>Sem leads no período.</SemDados>}
        </Cartao>

        <div className="rl-c7"><ContatosPorEstado className="h-full" leads={d.uf.leads} contratos={d.uf.contratos} /></div>

        <Cartao classe="rl-c5" titulo="Horários" subtitulo="Quando os leads chegam e quando assinam (horário de Brasília)"
          acoes={<Abas<"leads" | "assinados"> valor={calor} aoMudar={setCalor} opcoes={[{ valor: "leads", rotulo: "Chegada" }, { valor: "assinados", rotulo: "Assinatura" }]} />}>
          <MapaDeCalor grade={d.horarios[calor]} rotulo={calor === "leads" ? "Chegada de leads" : "Contratos assinados"} />
        </Cartao>

        <Cartao classe="rl-c12" titulo="Cards do CRM"
          subtitulo={d.crm?.ultima_varredura ? `Conferido com o CRM em ${new Date(d.crm.ultima_varredura).toLocaleString("pt-BR")}. Inclui os cards antigos e os que a IA não atendeu.`
            : "Cards do painel do CRM da conta, inclusive os de antes da IA."}
          acoes={d.crm && (
            <button type="button" className="rl-btn" onClick={pedirImportacao} disabled={pedindo || d.crm.importacao_pedida}>
              <Sparkles size={15} aria-hidden />{d.crm.importacao_pedida ? "Importação na fila" : d.crm.importado_em ? "Importar de novo" : "Importar cards antigos"}
            </button>
          )}>
          {!d.crm ? <SemDados>O espelho do CRM ainda não está ligado neste servidor.</SemDados>
            : !d.crm.total ? <SemDados>{d.crm.importacao_pedida || !d.crm.importado_em
              ? "Os cards do CRM ainda não foram importados. A conferência roda sozinha a cada 15 minutos quando o CRM está ligado em Integrações."
              : "Nenhum card no painel do CRM."}</SemDados>
            : (
              <>
                <div className="rl-mini">
                  <div><small>Cards abertos no painel</small><b className="num">{fmtNum(d.crm.total)}</b></div>
                  <div><small>Criados no período</small><b className="num">{fmtNum(d.crm.no_periodo)}</b></div>
                  <div><small>Sem conversa com a IA</small><b className="num">{fmtNum(d.crm.sem_lead)}</b></div>
                  <div><small>Em colunas de contrato assinado</small><b className="num">{fmtNum(d.crm.assinados)}</b></div>
                </div>
                <div className="rl-tabela-caixa">
                  <table className="rl-tabela">
                    <thead><tr><th>Coluna no CRM</th><th>Fase</th><th className="n">Cards</th><th className="n">Criados no período</th><th className="n">Sem conversa com a IA</th></tr></thead>
                    <tbody>
                      {d.crm.colunas.map((c, i) => (
                        <tr key={`${c.coluna}-${i}`}>
                          <td>{c.coluna || "Coluna sem nome"}</td>
                          <td><span className="rl-selo"><i className="rl-ponto" style={{ background: COR_FASE[c.fase] ?? "#94A3B8" }} />{c.nome_fase}</span></td>
                          <td className="n num">{fmtNum(c.total)}</td><td className="n num">{fmtNum(c.no_periodo)}</td><td className="n num">{fmtNum(c.sem_lead)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          {d.crm?.erro && <p className="rl-nota"><ShieldAlert size={13} style={{ verticalAlign: -2 }} /> Última conferência falhou ({d.crm.erro}); tentamos de novo sozinhos.</p>}
        </Cartao>
      </div>
      <p className="rl-nota">
        <Bot size={13} style={{ verticalAlign: -2 }} /> Números calculados a partir do que a LawChat registrou (mensagens, etapas, contratos e chamadas da IA).
        {filtrando && <> <Filter size={12} style={{ verticalAlign: -2 }} /> Com filtro de agente, campanha ou origem, a IA e o custo contam só os leads filtrados.</>}
        {" "}Atualizado em {new Date(d.gerado_em).toLocaleTimeString("pt-BR")}.
      </p>
    </>
  );
}
