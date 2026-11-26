/*
 * Relatórios › Rastreamento de campanhas: leads que vieram de anúncio ou UTM, por campanha, anúncio e plataforma;
 * quantos avançaram em cada etapa, contratos, conversão, tempo até assinar, custo da IA, ranking dos melhores
 * anúncios, alertas, teste A/B automático e o detalhe de cada anúncio.
 * Dados: GET /api/relatorios/campanhas e /api/relatorios/campanhas/anuncio/{chave}.
 */
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import {
  AlertTriangle, ArrowDownUp, Copy, ExternalLink, FileSignature, FlaskConical, Megaphone, Percent, Trophy, UserCheck, UserX, Users,
} from "lucide-react";
import { toast } from "sonner";
import { Carregando, Modal, useCarregar } from "../componentes/ui";
import { useSessao } from "../sessao";
import {
  Abas, BarraFiltros, Barrinha, BotaoCsv, CORES, Cartao, Funil, Kpi, MapaDeCalor, SemDados, Topo, baixarCsv, fmtBRL, fmtData,
  fmtDia, fmtHoras, fmtNum, fmtPct, textoPeriodo, useFiltros, type EtapaFunil,
} from "./relatoriosComum";

interface Grupo {
  leads: number; closer: number; contratos: number; assinatura: number; assinados: number; desqualificados: number;
  qualificados: number; conversao: number | null; qualificacao: number | null; desqualificacao: number | null;
  horas_ate_assinar: number | null; custo_brl: number; custo_por_lead: number | null; custo_por_contrato: number | null;
  primeiro_lead: string | null; ultimo_lead: string | null;
}
interface Campanha extends Grupo { campanha: string }
interface Anuncio extends Grupo {
  chave: string; nome: string; campanha: string; titulo: string | null; conteudo: string | null; url: string | null;
  fonte: string | null; meio: string | null; id_anuncio: string | null; plataforma: string | null; plataforma_nome: string;
}
interface Plataforma extends Grupo { plataforma: string; nome: string }
interface Campanhas {
  periodo: { de: string; ate: string; dias: number };
  kpis: { leads: number; assinados: number; conversao: number | null; qualificados: number; qualificados_pct: number | null;
          desqualificados: number; desqualificados_pct: number | null; campanhas: number; anuncios: number;
          media_leads_por_anuncio: number | null };
  funil: EtapaFunil[];
  tempo_ate_assinar: { media_horas: number | null; mediana_horas: number | null };
  campanhas: Campanha[]; anuncios: Anuncio[]; plataformas: Plataforma[];
  alertas: { campanha: string; gravidade: "alta" | "media"; titulo: string; texto: string }[];
  ab: { campanha: string; vencedor: string | null; perdedor: string; diferenca: number; recomendacao: string;
        anuncios: { chave: string; nome: string; leads: number; assinados: number; desqualificados: number; conversao: number | null; plataforma_nome: string }[] }[];
  serie: { dia: string; leads: number; assinados: number }[];
  horarios: { leads: number[][]; assinados: number[][] };
  gerado_em: string;
}
interface DetalheAnuncio extends Anuncio {
  funil: { fase: string; nome: string; chegaram: number }[];
  serie: { dia: string; leads: number; assinados: number }[];
  lista_leads: { id: string; nome: string | null; telefone: string | null; criado_em: string; etapa: string; alcancou: string;
           assinado: boolean; desqualificado: boolean; assinado_em: string | null; estado: string }[];
}

type Ordem = "assinados" | "leads" | "conversao";
type Coluna = "leads" | "closer" | "contratos" | "assinados" | "desqualificados" | "conversao" | "horas_ate_assinar" | "custo_brl";
const plataformaCurta = (a: { plataforma_nome: string }) => a.plataforma_nome.replace(" / Meta", "");

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
  const exportarAnuncios = () => {
    if (!d) return;
    baixarCsv(`anuncios-${d.periodo.de}-a-${d.periodo.ate}.csv`,
      ["Anúncio", "Campanha", "Plataforma", "Id do anúncio", "Link", "Leads", "Chegaram ao Closer", "Contratos assinados", "Desqualificados",
       "Conversão (%)", "Tempo médio até assinar (h)", "Custo da IA (R$)"],
      d.anuncios.map((a) => [a.nome, a.campanha, plataformaCurta(a), a.id_anuncio, a.url, a.leads, a.closer, a.assinados, a.desqualificados,
                             a.conversao, a.horas_ate_assinar, a.custo_brl]));
  };

  return (
    <div className="rl">
      <Topo titulo="Rastreamento de campanhas" carregando={dados.carregando} aoAtualizar={dados.recarregar}
        texto={<>Leads que vieram de anúncio ou UTM {textoPeriodo(filtros.de, filtros.ate)}: de qual campanha e anúncio, até onde chegaram e quantos viraram contrato.</>}
        acoes={<><BotaoCsv rotulo="CSV das campanhas" aoClicar={exportarCampanhas} /><BotaoCsv rotulo="CSV dos anúncios" aoClicar={exportarAnuncios} /></>} />
      <BarraFiltros filtros={filtros} mudar={mudar} />
      {!d ? <Carregando erro={dados.erro} /> : (
        <Conteudo d={d} abrir={setAnuncioAberto} filtrarCampanha={(c) => mudar({ campanha: c })} />
      )}
      {anuncioAberto && <DetalheDoAnuncio chave={anuncioAberto} consulta={consulta} aoFechar={() => setAnuncioAberto(null)} />}
    </div>
  );
}

function Conteudo({ d, abrir, filtrarCampanha }: { d: Campanhas; abrir: (chave: string) => void; filtrarCampanha: (c: string) => void }) {
  const k = d.kpis;
  const [ordem, setOrdem] = useState<Ordem>("assinados");
  const [todos, setTodos] = useState(false);
  const [coluna, setColuna] = useState<Coluna>("leads");
  const [calor, setCalor] = useState<"leads" | "assinados">("leads");

  const ranking = useMemo(() => {
    const lista = ordem === "assinados" ? d.anuncios.filter((a) => a.assinados > 0) : [...d.anuncios];
    const valor = (a: Anuncio) => (ordem === "conversao" ? a.conversao ?? 0 : a[ordem]);
    return lista.sort((a, b) => valor(b) - valor(a) || (b.conversao ?? 0) - (a.conversao ?? 0) || b.leads - a.leads);
  }, [d.anuncios, ordem]);
  const campanhas = useMemo(() => [...d.campanhas].sort((a, b) => ((b[coluna] ?? -1) as number) - ((a[coluna] ?? -1) as number)), [d.campanhas, coluna]);
  const tempos = d.campanhas.filter((c) => c.horas_ate_assinar != null).sort((a, b) => (a.horas_ate_assinar ?? 0) - (b.horas_ate_assinar ?? 0)).slice(0, 8);
  const maxLeads = Math.max(1, ...d.anuncios.map((a) => a.leads));
  const melhor = d.anuncios.reduce<Anuncio | null>((m, a) => (!m || a.leads > m.leads ? a : m), null);

  if (!k.leads) {
    return <SemDados>Nenhum lead com origem de anúncio ou UTM no período. A origem é registrada quando o lead chega por um anúncio de clique para WhatsApp ou por um link com UTM.</SemDados>;
  }
  const Cab = ({ c, rotulo }: { c: Coluna; rotulo: string }) => (
    <th className="n"><button type="button" className={coluna === c ? "on" : ""} onClick={() => setColuna(c)} title="Ordenar">{rotulo}{coluna === c && <ArrowDownUp size={11} />}</button></th>
  );
  return (
    <>
      <div className="rl-kpis rl-kpis-6">
        <Kpi rotulo="Leads de campanhas" valor={fmtNum(k.leads)} icone={<Users />} detalhe={`${fmtNum(k.campanhas)} campanhas, ${fmtNum(k.anuncios)} anúncios`} />
        <Kpi rotulo="Qualificados" valor={fmtPct(k.qualificados_pct)} icone={<UserCheck />} tom="azul" detalhe={`${fmtNum(k.qualificados)} chegaram ao Closer ou além`} />
        <Kpi rotulo="Contratos assinados" valor={fmtNum(k.assinados)} icone={<FileSignature />} tom="roxo" detalhe={`conversão de ${fmtPct(k.conversao)}`} />
        <Kpi rotulo="Desqualificados" valor={fmtPct(k.desqualificados_pct)} icone={<UserX />} tom="vermelho" detalhe={`${fmtNum(k.desqualificados)} leads`} />
        <Kpi rotulo="Média por anúncio" valor={fmtNum(k.media_leads_por_anuncio)} icone={<Megaphone />} tom="ambar"
          detalhe={melhor ? `mais leads: ${melhor.nome.slice(0, 28)}` : undefined} />
        <Kpi rotulo="Tempo até assinar" valor={fmtHoras(d.tempo_ate_assinar.media_horas)} icone={<Percent />} tom="cinza"
          detalhe={d.tempo_ate_assinar.mediana_horas != null ? `mediana ${fmtHoras(d.tempo_ate_assinar.mediana_horas)}` : "da entrada à assinatura"} />
      </div>

      <div className="rl-grade">
        <Cartao classe="rl-c7" titulo="Funil das campanhas" subtitulo="Leads de anúncio ou UTM e até onde chegaram">
          <Funil etapas={d.funil} total={k.leads} />
        </Cartao>
        <Cartao classe="rl-c5" titulo="Por plataforma" subtitulo="Leads e contratos de cada origem">
          <div className="rl-dois">
            <div className="rl-grafico rl-grafico-baixo">
              <ResponsiveContainer>
                <PieChart>
                  <Pie data={d.plataformas} dataKey="leads" nameKey="nome" innerRadius="55%" outerRadius="90%" paddingAngle={2}>
                    {d.plataformas.map((p, i) => <Cell key={p.plataforma} fill={CORES[i % CORES.length]} />)}
                  </Pie>
                  <Tooltip formatter={(v: number) => fmtNum(v)} />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div className="rl-lista">
              {d.plataformas.map((p, i) => (
                <div key={p.plataforma} className="rl-crm-coluna">
                  <span><i className="rl-ponto" style={{ background: CORES[i % CORES.length], marginRight: 6 }} />{p.nome}</span>
                  <b className="num">{fmtNum(p.leads)} <small>{fmtPct(p.conversao)} conv.</small></b>
                </div>
              ))}
            </div>
          </div>
        </Cartao>

        <Cartao classe="rl-c12" titulo={<><Trophy size={16} style={{ verticalAlign: -3, color: "#D97706" }} /> Melhores anúncios</>}
          subtitulo="Clique num anúncio para ver o detalhe e os leads dele"
          acoes={<Abas valor={ordem} aoMudar={(v) => { setOrdem(v); setTodos(false); }}
            opcoes={[{ valor: "assinados", rotulo: "Contratos" }, { valor: "leads", rotulo: "Leads" }, { valor: "conversao", rotulo: "Conversão" }]} />}>
          {ranking.length ? (
            <>
              <div className="rl-tabela-caixa">
                <table className="rl-tabela">
                  <thead><tr><th>#</th><th>Anúncio</th><th>Plataforma</th><th className="n">Leads</th><th className="n">Closer</th>
                    <th className="n">Assinados</th><th className="n">Conversão</th><th className="n">Custo da IA</th></tr></thead>
                  <tbody>
                    {(todos ? ranking : ranking.slice(0, 5)).map((a, i) => (
                      <tr key={a.chave} className="rl-clicavel" onClick={() => abrir(a.chave)} tabIndex={0}
                        onKeyDown={(e) => { if (e.key === "Enter") abrir(a.chave); }}>
                        <td><span className={`rl-pos${i < 3 ? ` p${i + 1}` : ""}`}>{i + 1}</span></td>
                        <td className="rl-nome"><b title={a.nome}>{a.nome}</b><small title={a.campanha}>{a.campanha}</small></td>
                        <td><span className="rl-selo">{plataformaCurta(a)}</span></td>
                        <td className="n num">{fmtNum(a.leads)}<Barrinha valor={a.leads} maximo={maxLeads} /></td>
                        <td className="n num">{fmtNum(a.closer)}</td>
                        <td className="n num">{fmtNum(a.assinados)}</td>
                        <td className="n num">{fmtPct(a.conversao)}<Barrinha valor={a.conversao ?? 0} maximo={100} cor="#6366F1" /></td>
                        <td className="n num">{fmtBRL(a.custo_brl)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {ranking.length > 5 && (
                <button type="button" className="rl-btn rl-ver-mais rl-nao-imprimir" onClick={() => setTodos(!todos)}>
                  {todos ? "Ver só os 5 primeiros" : `Ver todos (${ranking.length})`}
                </button>
              )}
            </>
          ) : <SemDados>{ordem === "assinados" ? "Nenhum anúncio trouxe contrato assinado no período." : "Sem anúncios no período."}</SemDados>}
        </Cartao>

        <Cartao classe="rl-c12" titulo="Campanhas" subtitulo="Quantos leads de cada campanha chegaram a cada etapa. Clique no nome para filtrar a tela pela campanha.">
          <div className="rl-tabela-caixa">
            <table className="rl-tabela">
              <thead><tr><th>Campanha</th><Cab c="leads" rotulo="Leads" /><Cab c="closer" rotulo="Closer" /><Cab c="contratos" rotulo="Contratos" />
                <Cab c="assinados" rotulo="Assinados" /><Cab c="desqualificados" rotulo="Desqualif." /><Cab c="conversao" rotulo="Conversão" />
                <Cab c="horas_ate_assinar" rotulo="Até assinar" /><Cab c="custo_brl" rotulo="Custo da IA" /></tr></thead>
              <tbody>
                {campanhas.map((c) => (
                  <tr key={c.campanha}>
                    <td className="rl-nome"><button type="button" className="rl-link-tabela" onClick={() => filtrarCampanha(c.campanha)} title="Filtrar por esta campanha"
                      style={{ border: 0, background: "none", padding: 0, textAlign: "left", color: "var(--ink)" }}><b>{c.campanha}</b></button>
                      <small>{c.primeiro_lead ? `${fmtData(c.primeiro_lead)} a ${fmtData(c.ultimo_lead)}` : ""}</small></td>
                    <td className="n num">{fmtNum(c.leads)}</td><td className="n num">{fmtNum(c.closer)}</td><td className="n num">{fmtNum(c.contratos)}</td>
                    <td className="n num"><b>{fmtNum(c.assinados)}</b></td><td className="n num">{fmtNum(c.desqualificados)}</td>
                    <td className="n num">{fmtPct(c.conversao)}</td><td className="n num">{fmtHoras(c.horas_ate_assinar)}</td>
                    <td className="n num" title={c.custo_por_contrato != null ? `${fmtBRL(c.custo_por_contrato)} por contrato` : undefined}>{fmtBRL(c.custo_brl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Cartao>

        <Cartao classe="rl-c6" titulo={<><AlertTriangle size={16} style={{ verticalAlign: -3, color: "#DC2626" }} /> Campanhas que precisam de atenção</>}
          subtitulo="Muitos leads sem contrato, muitos desqualificados ou conversão muito baixa">
          {d.alertas.length ? (
            <div className="rl-lista">
              {d.alertas.map((a) => (
                <div key={a.campanha} className={`rl-alerta ${a.gravidade}`}>
                  <AlertTriangle size={16} color={a.gravidade === "alta" ? "#DC2626" : "#D97706"} aria-hidden />
                  <div><b>{a.campanha}: {a.titulo}</b><span>{a.texto}</span></div>
                </div>
              ))}
            </div>
          ) : <SemDados>Nenhuma campanha com sinal de alerta no período.</SemDados>}
        </Cartao>

        <Cartao classe="rl-c6" titulo="Tempo até converter por campanha" subtitulo="Média da entrada do lead até a assinatura (mais rápidas primeiro)">
          {tempos.length ? (
            <div className="rl-grafico rl-grafico-baixo">
              <ResponsiveContainer>
                <BarChart data={tempos} layout="vertical" margin={{ top: 0, right: 16, left: 8, bottom: 0 }}>
                  <XAxis type="number" tick={{ fontSize: 11, fill: "#64748B" }} tickFormatter={(v) => fmtHoras(v)} />
                  <YAxis type="category" dataKey="campanha" width={150} tick={{ fontSize: 11, fill: "#475569" }}
                    tickFormatter={(v: string) => (v.length > 24 ? v.slice(0, 23) + "…" : v)} />
                  <Tooltip formatter={(v: number) => [fmtHoras(v), "Tempo médio"]} />
                  <Bar dataKey="horas_ate_assinar" fill="#6366F1" radius={[0, 6, 6, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : <SemDados>Nenhuma campanha com contrato assinado no período.</SemDados>}
        </Cartao>

        <Cartao classe="rl-c12" titulo={<><FlaskConical size={16} style={{ verticalAlign: -3, color: "#6366F1" }} /> Teste A/B automático</>}
          subtitulo="Dentro de cada campanha, compara os anúncios com pelo menos 3 leads (sem teste estatístico: leia como sinal, não como prova)">
          {d.ab.length ? (
            <div className="rl-grade">
              {d.ab.map((t) => (
                <div key={t.campanha} className="rl-ab rl-c6">
                  <div className="rl-ab-cab"><b>{t.campanha}</b><span className="rl-nota">diferença de {fmtPct(t.diferenca)}</span></div>
                  <table className="rl-tabela">
                    <thead><tr><th>Anúncio</th><th className="n">Leads</th><th className="n">Assinados</th><th className="n">Conversão</th></tr></thead>
                    <tbody>
                      {t.anuncios.map((a) => (
                        <tr key={a.chave} className="rl-clicavel" onClick={() => abrir(a.chave)}>
                          <td className="rl-nome"><b title={a.nome}>{a.nome}</b>
                            {a.chave === t.vencedor && <span className="rl-selo ok">vencedor</span>}
                            {a.chave === t.perdedor && t.vencedor && <span className="rl-selo ruim">pior</span>}</td>
                          <td className="n num">{fmtNum(a.leads)}</td><td className="n num">{fmtNum(a.assinados)}</td><td className="n num">{fmtPct(a.conversao)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <div className="rl-ab-rec">{t.recomendacao}</div>
                </div>
              ))}
            </div>
          ) : <SemDados>Ainda não há campanha com dois anúncios de pelo menos 3 leads cada no período.</SemDados>}
        </Cartao>

        <Cartao classe="rl-c7" titulo="Leads de campanhas por dia" subtitulo="Entradas e contratos assinados entre elas">
          <div className="rl-grafico rl-grafico-baixo">
            <ResponsiveContainer>
              <AreaChart data={d.serie} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
                <CartesianGrid stroke="#E2E8F0" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="dia" tickFormatter={fmtDia} tick={{ fontSize: 11, fill: "#64748B" }} minTickGap={18} />
                <YAxis tick={{ fontSize: 11, fill: "#64748B" }} allowDecimals={false} width={40} />
                <Tooltip labelFormatter={(v) => fmtData(String(v) + "T12:00:00")} />
                <Area type="monotone" dataKey="leads" name="Leads" stroke="#00BC33" fill="#00BC33" fillOpacity={0.15} strokeWidth={2} />
                <Area type="monotone" dataKey="assinados" name="Contratos" stroke="#6366F1" fill="#6366F1" fillOpacity={0.15} strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Cartao>
        <Cartao classe="rl-c5" titulo="Horários" subtitulo="Chegada dos leads de campanha e assinaturas"
          acoes={<Abas<"leads" | "assinados"> valor={calor} aoMudar={setCalor} opcoes={[{ valor: "leads", rotulo: "Chegada" }, { valor: "assinados", rotulo: "Assinatura" }]} />}>
          <MapaDeCalor grade={d.horarios[calor]} rotulo={calor === "leads" ? "Chegada de leads" : "Contratos assinados"} />
        </Cartao>
      </div>
      <p className="rl-nota">A origem é a do primeiro contato do lead (anúncio de clique para WhatsApp ou link com UTM). Atualizado em {new Date(d.gerado_em).toLocaleTimeString("pt-BR")}.</p>
    </>
  );
}

function DetalheDoAnuncio({ chave, consulta, aoFechar }: { chave: string; consulta: string; aoFechar: () => void }) {
  const r = useCarregar<DetalheAnuncio>(`/relatorios/campanhas/anuncio/${chave}?${consulta}`, [chave, consulta]);
  const a = r.dados;
  const copiar = (texto: string) => navigator.clipboard?.writeText(texto).then(() => toast.success("Link copiado."), () => toast.error("Não deu para copiar."));
  const exportar = () => {
    if (!a) return;
    baixarCsv(`anuncio-${chave}.csv`, ["Lead", "Telefone", "Entrou em", "Etapa atual", "Chegou até", "Assinou", "Desqualificado"],
      a.lista_leads.map((l) => [l.nome, l.telefone, fmtData(l.criado_em), l.etapa, l.alcancou, l.assinado ? "sim" : "não", l.desqualificado ? "sim" : "não"]));
  };
  return (
    <Modal titulo={a ? a.nome : "Anúncio"} texto={a ? `${a.campanha} · ${plataformaCurta(a)}` : undefined} aoFechar={aoFechar} largura={880}
      rodape={<><span className="sp" />{a && <BotaoCsv rotulo="CSV dos leads" aoClicar={exportar} />}<button type="button" className="btn pri" onClick={aoFechar}>Fechar</button></>}>
      {!a ? <Carregando erro={r.erro} /> : (
        <div className="rl-detalhe">
          <div className="rl-mini">
            <div><small>Leads</small><b className="num">{fmtNum(a.leads)}</b></div>
            <div><small>Chegaram ao Closer</small><b className="num">{fmtNum(a.closer)}</b></div>
            <div><small>Contratos assinados</small><b className="num">{fmtNum(a.assinados)}</b></div>
            <div><small>Conversão</small><b className="num">{fmtPct(a.conversao)}</b></div>
            <div><small>Desqualificados</small><b className="num">{fmtNum(a.desqualificados)}</b></div>
            <div><small>Tempo até assinar</small><b className="num">{fmtHoras(a.horas_ate_assinar)}</b></div>
            <div><small>Custo da IA</small><b className="num">{fmtBRL(a.custo_brl)}</b></div>
            <div><small>Por contrato</small><b className="num">{fmtBRL(a.custo_por_contrato)}</b></div>
          </div>
          <div className="rl-detalhe-atrib">
            <div><small>Campanha</small><span>{a.campanha}</span></div>
            {a.titulo && <div><small>Título do anúncio</small><span>{a.titulo}</span></div>}
            {a.conteudo && <div><small>Conteúdo</small><span>{a.conteudo}</span></div>}
            {a.id_anuncio && <div><small>Id do anúncio</small><span className="mono">{a.id_anuncio}</span></div>}
            {a.fonte && <div><small>Fonte</small><span>{a.fonte}{a.meio ? ` / ${a.meio}` : ""}</span></div>}
            {a.url && (
              <div><small>Link do anúncio</small>
                <span style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  <a href={a.url} target="_blank" rel="noreferrer noopener" className="rl-btn"><ExternalLink size={14} />Abrir</a>
                  <button type="button" className="rl-btn" onClick={() => copiar(a.url!)}><Copy size={14} />Copiar</button>
                </span>
              </div>
            )}
          </div>
          <div className="rl-dois">
            <div className="rl-lista">
              {a.funil.map((e, i) => (
                <div key={e.fase} className="rl-crm-coluna">
                  <span>{e.nome}<Barrinha valor={e.chegaram} maximo={a.leads} cor={CORES[i]} /></span><b className="num">{fmtNum(e.chegaram)}</b>
                </div>
              ))}
            </div>
            <div className="rl-grafico rl-grafico-baixo">
              <ResponsiveContainer>
                <BarChart data={a.serie} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
                  <XAxis dataKey="dia" tickFormatter={fmtDia} tick={{ fontSize: 10, fill: "#64748B" }} minTickGap={16} />
                  <YAxis tick={{ fontSize: 10, fill: "#64748B" }} allowDecimals={false} width={32} />
                  <Tooltip labelFormatter={(v) => fmtData(String(v) + "T12:00:00")} />
                  <Bar dataKey="leads" name="Leads" fill="#00BC33" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="assinados" name="Contratos" fill="#6366F1" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
          <div className="rl-tabela-caixa">
            <table className="rl-tabela">
              <thead><tr><th>Lead</th><th>Entrou em</th><th>Etapa atual</th><th>Chegou até</th><th>Situação</th></tr></thead>
              <tbody>
                {a.lista_leads.map((l) => (
                  <tr key={l.id}>
                    <td className="rl-nome"><Link to={`/conversas/${l.id}`}><b>{l.nome || "Contato sem nome"}</b></Link><small>{l.telefone}</small></td>
                    <td>{fmtData(l.criado_em)}</td><td>{l.etapa}</td><td>{l.alcancou}</td>
                    <td>{l.assinado ? <span className="rl-selo ok">Assinou</span> : l.desqualificado ? <span className="rl-selo ruim">Desqualificado</span>
                      : l.estado === "pausado" ? <span className="rl-selo aviso">Com a equipe</span> : <span className="rl-selo">Em andamento</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {a.lista_leads.length >= 100 && <p className="rl-nota">Mostrando os 100 leads mais recentes.</p>}
        </div>
      )}
    </Modal>
  );
}
