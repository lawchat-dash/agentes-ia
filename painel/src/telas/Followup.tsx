// Ferramentas › Follow-up: os agentes com o follow-up de cada um (ligar/desligar e abrir a configuração), o histórico
// (o que saiu, o que não saiu e por quê) e o dashboard. Backend: app/gestao/rotas_followup.py (/followup/*).
// HistoricoFollowup e DashboardFollowup também aparecem na aba Follow-up do agente (AgenteFollowup.tsx), filtrados.
import { Fragment, useMemo, useState, type CSSProperties } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { BarChart3, ChevronDown, ChevronRight, History, LayoutGrid, Repeat, Search, Send, Settings2 } from "lucide-react";
import { api, enviar, formatarTelefone, quando } from "../api";
import { Alerta, Cabecalho, Carregando, Interruptor, Painel, Vazio, useAcao, useCarregar } from "../componentes/ui";
import { useSessao } from "../sessao";
import "../estilo-automacao.css";

// --------------------------------------------------------------------------- tipos
export interface AgenteFu {
  id: string; nome: string; situacao: string; modo: string; numero_canal: string | null; tipo_canal: string | null;
  followup: { ligado: boolean; configurado: boolean; passos: number[]; etapas: string[] };
  pendentes: number; enviados: number; respondidos: number; falhas: number; ultimo_envio: string | null;
}
interface Visao { agentes: AgenteFu[]; dias: number; totais: { agentes: number; ligados: number; desligados: number; pendentes: number; pontos: number } }
interface ItemHistorico {
  id: string; id_lead: string; id_agente: string | null; agente: string | null; nome: string | null; telefone: string | null;
  tentativa: number; desistencia: boolean; situacao: string; motivo: string | null; motivo_texto: string | null;
  mensagens: string[]; agendado_para: string; enviado_em: string | null; atualizado_em: string; respondeu: boolean;
}
interface Linha { enviados: number; respondidos: number; falhas: number; cancelados: number; pendentes: number }
interface DadosPainel {
  dias: number; resposta_h: number;
  totais: { enviados: number; respondidos: number; taxa_resposta: number; falhas: number; nao_enviados: number; pendentes: number };
  por_dia: (Linha & { dia: string })[]; por_passo: (Linha & { tentativa: number })[];
  motivos: { motivo: string | null; texto: string; total: number }[]; por_agente: (Linha & { id_agente: string | null })[];
}

// --------------------------------------------------------------------------- formatos
export const horasLegivel = (h: number) => {
  if (h < 1) return `${Math.round(h * 60)} min`;
  if (h < 24 || h % 24 !== 0) return `${Number.isInteger(h) ? h : h.toFixed(1).replace(".", ",")} h`;
  return `${h / 24} d`;
};
const taxa = (respondidos: number, enviados: number) => (enviados ? `${Math.round((100 * respondidos) / enviados)}%` : "—");
const PERIODOS = [7, 30, 90];
const SITUACAO: Record<string, { rotulo: string; classe: string }> = {
  enviado: { rotulo: "enviado", classe: "ok" }, pendente: { rotulo: "agendado", classe: "info" }, reservado: { rotulo: "enviando", classe: "info" },
  cancelado: { rotulo: "não enviado", classe: "" }, falhou: { rotulo: "falhou", classe: "bad" },
};
const COR = { enviados: "#00BC33", respondidos: "#2563EB", falhas: "#DC2626", cancelados: "#94A3B8" };

function SeletorPeriodo({ dias, aoMudar }: { dias: number; aoMudar: (d: number) => void }) {
  return (
    <div className="seg" role="radiogroup" aria-label="Período">
      {PERIODOS.map((d) => <button key={d} type="button" role="radio" aria-checked={dias === d} className={dias === d ? "on" : ""} onClick={() => aoMudar(d)}>{d} dias</button>)}
    </div>
  );
}

// --------------------------------------------------------------------------- tela
export function TelaFollowup() {
  const { escritorio } = useSessao();
  const [busca, setBusca] = useSearchParams();
  const aba = (["agentes", "historico", "dashboard"] as const).find((a) => a === busca.get("aba")) ?? "agentes";
  const dias = PERIODOS.includes(Number(busca.get("dias"))) ? Number(busca.get("dias")) : 30;
  const mudar = (chave: string, valor: string) => { const p = new URLSearchParams(busca); p.set(chave, valor); setBusca(p, { replace: true }); };
  const visao = useCarregar<Visao>(`/followup/visao?dias=${dias}`, [escritorio]);
  const t = visao.dados?.totais;

  return (
    <>
      <Cabecalho eyebrow="Automação" titulo="Follow-up"
        texto="Quando o lead para de responder, o agente retoma a conversa no ritmo da cadência. Aqui você liga por agente, vê o que foi enviado e acompanha os resultados."
        acoes={<SeletorPeriodo dias={dias} aoMudar={(d) => mudar("dias", String(d))} />} />
      <div className="kpis">
        <div className="kpi"><span>Agentes</span><b>{t ? t.agentes : "…"}</b><small>da conta</small></div>
        <div className="kpi ok"><span>Com follow-up ligado</span><b>{t ? t.ligados : "…"}</b><small>{t ? `${t.desligados} desligado${t.desligados === 1 ? "" : "s"}` : " "}</small></div>
        <div className="kpi"><span>Agendados</span><b>{t ? t.pendentes : "…"}</b><small>próximos envios</small></div>
        <div className="kpi"><span>Pontos de cadência</span><b>{t ? t.pontos : "…"}</b><small>nos agentes ligados</small></div>
      </div>
      <div className="au-barra">
        <div className="seg" role="tablist" aria-label="Seções do follow-up">
          {([["agentes", "Agentes", LayoutGrid], ["historico", "Histórico", History], ["dashboard", "Dashboard", BarChart3]] as const).map(([chave, rotulo, Icone]) => (
            <button key={chave} type="button" role="tab" aria-selected={aba === chave} className={aba === chave ? "on" : ""} onClick={() => mudar("aba", chave)}>
              <Icone size={13} style={{ marginRight: 6, verticalAlign: -2 }} />{rotulo}
            </button>
          ))}
        </div>
      </div>
      {aba === "agentes" && <ListaAgentes visao={visao.dados} erro={visao.erro} aoMudar={visao.recarregar} />}
      {aba === "historico" && <HistoricoFollowup dias={dias} agentes={visao.dados?.agentes} />}
      {aba === "dashboard" && <DashboardFollowup dias={dias} agentes={visao.dados?.agentes} />}
    </>
  );
}

// --------------------------------------------------------------------------- agentes
function ListaAgentes({ visao, erro, aoMudar }: { visao: Visao | null; erro: string | null; aoMudar: () => void }) {
  const [texto, setTexto] = useState("");
  const [filtro, setFiltro] = useState<"todos" | "ligados" | "desligados">("todos");
  const { ocupado, executar } = useAcao();
  const [mexendo, setMexendo] = useState<string | null>(null);
  if (!visao) return <Carregando erro={erro} />;
  const termo = texto.trim().toLowerCase();
  const lista = visao.agentes.filter((a) => (filtro === "todos" || (filtro === "ligados") === a.followup.ligado)
    && (!termo || a.nome.toLowerCase().includes(termo) || (a.numero_canal ?? "").includes(termo)));
  // Liga/desliga com a configuração que o agente já tem (a mesma rota da aba Follow-up do agente).
  const alternar = (a: AgenteFu, ligar: boolean) => {
    setMexendo(a.id);
    executar(async () => {
      const atual = await api<{ config: Record<string, unknown> }>(`/agentes/${a.id}/followup`);
      await enviar(`/agentes/${a.id}/followup`, { ...atual.config, ativo: ligar }, "PUT");
      aoMudar();
    }, ligar ? `Follow-up de ${a.nome} ligado.` : `Follow-up de ${a.nome} desligado.`).finally(() => setMexendo(null));
  };

  if (visao.agentes.length === 0) {
    return <div className="panel"><Vazio icone={<Repeat />}>Nenhum agente ainda. Ative um produto em <Link to="/biblioteca">Biblioteca</Link> para configurar o follow-up.</Vazio></div>;
  }
  return (
    <>
      <div className="au-barra">
        <label className="au-busca"><Search /><input className="inp" placeholder="Buscar agente ou número" aria-label="Buscar agente" value={texto} onChange={(e) => setTexto(e.target.value)} /></label>
        <div className="seg" role="radiogroup" aria-label="Filtrar">
          {([["todos", "Todos", visao.totais.agentes], ["ligados", "Ligados", visao.totais.ligados], ["desligados", "Desligados", visao.totais.desligados]] as const).map(([chave, rotulo, n]) => (
            <button key={chave} type="button" role="radio" aria-checked={filtro === chave} className={filtro === chave ? "on" : ""} onClick={() => setFiltro(chave)}>{rotulo} <span className="muted">{n}</span></button>
          ))}
        </div>
      </div>
      {lista.length === 0 ? <div className="panel"><Vazio icone={<Search />}>Nada com esse filtro.</Vazio></div> : (
        <div className="au-grade tres">
          {lista.map((a) => {
            const fu = a.followup;
            return (
              <div key={a.id} className="au-cartao" style={{ "--au-cor": fu.ligado ? "#DB2777" : "#94A3B8" } as CSSProperties}>
                <div className="au-cartao-corpo">
                  <div className="au-cartao-cab">
                    <span className="au-icone"><Send /></span>
                    <div><b title={a.nome}>{a.nome}</b><small>{a.numero_canal ? formatarTelefone(a.numero_canal) : "sem número"}{a.tipo_canal === "oficial" ? " · oficial" : ""}{a.situacao !== "ativo" ? " · agente pausado" : a.modo === "teste" ? " · em teste" : ""}</small></div>
                    <span className={`chip ${fu.ligado ? "ok" : ""}`}><span className="d" />{fu.ligado ? "Ligado" : fu.configurado ? "Desligado" : "Não configurado"}</span>
                  </div>
                  <div className="fu-cadencia" aria-label="Cadência">
                    {fu.passos.length === 0 ? <span>sem cadência</span> : fu.passos.map((h, i) => <Fragment key={i}>{i > 0 && <i />}<span>{horasLegivel(h)}</span></Fragment>)}
                  </div>
                  <div className="fu-numeros">
                    <div><b>{a.pendentes}</b><span>agendados</span></div>
                    <div><b>{a.enviados}</b><span>enviados</span></div>
                    <div><b>{taxa(a.respondidos, a.enviados)}</b><span>responderam</span></div>
                  </div>
                  {fu.ligado && a.tipo_canal === "oficial" && <span className="muted" style={{ fontSize: 12 }}>Número oficial: depois de 24 h sem o lead escrever, só sai com modelo aprovado.</span>}
                </div>
                <div className="au-cartao-rodape">
                  <Link className="au-link" to={`/agentes/${a.id}/followup`}><Settings2 />Configurar</Link>
                  <span className="sp" />
                  <span className="muted">{fu.ligado ? "Ligado" : "Desligado"}</span>
                  <Interruptor rotulo={`Follow-up de ${a.nome}`} ligado={fu.ligado} desligado={ocupado && mexendo === a.id} aoMudar={(v) => alternar(a, v)} />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}

// --------------------------------------------------------------------------- histórico
export function HistoricoFollowup({ dias, agentes, agente, compacto = false, situacaoInicial = "", comBusca }: {
  dias: number; agentes?: AgenteFu[]; agente?: string; compacto?: boolean; situacaoInicial?: string; comBusca?: boolean;
}) {
  const [situacao, setSituacao] = useState(situacaoInicial);
  const [doAgente, setDoAgente] = useState("");
  const [texto, setTexto] = useState("");
  const [aberto, setAberto] = useState<string | null>(null);
  const filtroAgente = agente ?? doAgente;
  const caminho = useMemo(() => {
    const p = new URLSearchParams({ dias: String(dias), limite: compacto ? "40" : "150" });
    if (situacao) p.set("situacao", situacao);
    if (filtroAgente) p.set("agente", filtroAgente);
    if (texto.trim().length >= 2) p.set("busca", texto.trim());
    return `/followup/historico?${p}`;
  }, [dias, situacao, filtroAgente, texto, compacto]);
  const { dados, erro } = useCarregar<{ itens: ItemHistorico[] }>(caminho);

  return (
    <div className="stack">
      <div className="au-barra" style={{ marginBottom: 0 }}>
        <div className="seg" role="radiogroup" aria-label="Situação">
          {[["", "Todos"], ["enviado", "Enviados"], ["agendado", "Agendados"], ["nao_enviado", "Não enviados"], ["falhou", "Falhas"]].map(([v, r]) => (
            <button key={v} type="button" role="radio" aria-checked={situacao === v} className={situacao === v ? "on" : ""} onClick={() => setSituacao(v)}>{r}</button>
          ))}
        </div>
        {!agente && agentes && agentes.length > 1 && (
          <select className="inp" aria-label="Agente" style={{ maxWidth: 220 }} value={doAgente} onChange={(e) => setDoAgente(e.target.value)}>
            <option value="">Todos os agentes</option>
            {agentes.map((a) => <option key={a.id} value={a.id}>{a.nome}</option>)}
          </select>
        )}
        {(comBusca ?? !compacto) && <label className="au-busca"><Search /><input className="inp" placeholder="Buscar lead (nome ou número)" aria-label="Buscar lead" value={texto} onChange={(e) => setTexto(e.target.value)} /></label>}
      </div>
      {!dados ? <Carregando erro={erro} /> : dados.itens.length === 0 ? (
        <div className="panel"><Vazio icone={<History />}>Nenhum follow-up nesse filtro nos últimos {dias} dias.</Vazio></div>
      ) : (
        <div className="lst"><table>
          <thead><tr><th style={{ width: 28 }} /><th>Lead</th>{!agente && <th>Agente</th>}<th>Tentativa</th><th>Situação</th><th>Quando</th><th>Detalhe</th></tr></thead>
          <tbody>{dados.itens.map((i) => {
            const s = SITUACAO[i.situacao] ?? { rotulo: i.situacao, classe: "" };
            const aberta = aberto === i.id;
            const detalhe = i.situacao === "enviado" ? (i.mensagens[0] ?? "") : i.motivo_texto ?? "";
            const momento = i.situacao === "pendente" || i.situacao === "reservado" ? i.agendado_para : i.enviado_em ?? i.atualizado_em;
            return (
              <Fragment key={i.id}>
                <tr className="click" onClick={() => setAberto(aberta ? null : i.id)} aria-expanded={aberta}>
                  <td>{aberta ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</td>
                  <td><div className="t">{i.nome || "sem nome"}</div><div className="s mono">{formatarTelefone(i.telefone)}</div></td>
                  {!agente && <td className="s">{i.agente ?? "—"}</td>}
                  <td className="num">{i.desistencia ? "encerramento" : `${i.tentativa}ª`}</td>
                  <td><span className={`chip ${s.classe}`}><span className="d" />{s.rotulo}</span>{i.respondeu && <span className="chip info" style={{ marginLeft: 6 }}>respondeu</span>}</td>
                  <td className="s num">{i.situacao === "pendente" ? "para " : ""}{quando(momento)}</td>
                  <td className="s" style={{ maxWidth: 360, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{detalhe || "—"}</td>
                </tr>
                {aberta && (
                  <tr><td /><td colSpan={agente ? 5 : 6}>
                    <div className="fu-detalhe">
                      {i.mensagens.length > 0 ? i.mensagens.map((m, j) => <div key={j} className="fu-mensagem">{m}</div>)
                        : <span className="sec">{i.situacao === "pendente" ? `Agendado para ${new Date(i.agendado_para).toLocaleString("pt-BR")}. O texto é escrito na hora do envio, lendo a conversa.` : `Não foi enviado: ${i.motivo_texto ?? "sem motivo registrado"}.`}</span>}
                      <span className="muted" style={{ fontSize: 12 }}>
                        {i.enviado_em && <>Enviado em {new Date(i.enviado_em).toLocaleString("pt-BR")}. </>}
                        {i.situacao === "enviado" && (i.respondeu ? "O lead respondeu depois deste envio." : "Sem resposta do lead em até 3 dias.")}
                        {" "}<Link to={`/atendimento?lead=${i.id_lead}`}>Abrir a conversa</Link>
                      </span>
                    </div>
                  </td></tr>
                )}
              </Fragment>
            );
          })}</tbody>
        </table></div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- dashboard
export function DashboardFollowup({ dias, agentes, agente, compacto = false }: { dias: number; agentes?: AgenteFu[]; agente?: string; compacto?: boolean }) {
  const caminho = `/followup/dashboard?dias=${dias}${agente ? `&agente=${agente}` : ""}`;
  const { dados, erro } = useCarregar<DadosPainel>(caminho);
  const serie = useMemo(() => {
    if (!dados) return [];
    const mapa = new Map(dados.por_dia.map((d) => [d.dia, d]));
    const fim = new Date();
    return Array.from({ length: dados.dias }, (_, k) => {
      const d = new Date(fim); d.setDate(fim.getDate() - (dados.dias - 1 - k));
      const chave = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
      const v = mapa.get(chave);
      return { dia: `${chave.slice(8)}/${chave.slice(5, 7)}`, enviados: v?.enviados ?? 0, respondidos: v?.respondidos ?? 0, falhas: v?.falhas ?? 0 };
    });
  }, [dados]);
  if (!dados) return <Carregando erro={erro} />;
  const t = dados.totais;
  const nomes = new Map((agentes ?? []).map((a) => [a.id, a.nome]));
  const maxMotivo = Math.max(1, ...dados.motivos.map((m) => m.total));

  return (
    <div className="stack">
      <div className={`kpis ${compacto ? "" : "seis"}`}>
        <div className="kpi ok"><span>Enviados</span><b>{t.enviados}</b><small>últimos {dados.dias} dias</small></div>
        <div className="kpi"><span>Responderam</span><b>{t.respondidos}</b><small>em até {Math.round(dados.resposta_h / 24)} dias</small></div>
        <div className="kpi"><span>Taxa de resposta</span><b>{t.enviados ? `${t.taxa_resposta.toLocaleString("pt-BR")}%` : "—"}</b><small>respondidos ÷ enviados</small></div>
        <div className={`kpi ${t.falhas ? "bad" : ""}`}><span>Falhas</span><b>{t.falhas}</b><small>erro no envio</small></div>
        {!compacto && <div className="kpi"><span>Não enviados</span><b>{t.nao_enviados}</b><small>cancelados (veja o motivo)</small></div>}
        {!compacto && <div className="kpi"><span>Agendados</span><b>{t.pendentes}</b><small>na fila agora</small></div>}
      </div>
      {t.enviados + t.falhas + t.nao_enviados + t.pendentes === 0 ? (
        <div className="panel"><Vazio icone={<BarChart3 />}>Ainda não há follow-up nos últimos {dados.dias} dias. Os números aparecem aqui assim que o primeiro sair.</Vazio></div>
      ) : (
        <>
          <div className="fu-graficos">
            <Painel titulo="Por dia">
              <div className="fu-legenda"><span style={{ "--c": COR.enviados } as CSSProperties}>Enviados</span><span style={{ "--c": COR.respondidos } as CSSProperties}>Responderam</span><span style={{ "--c": COR.falhas } as CSSProperties}>Falhas</span></div>
              <div style={{ height: compacto ? 180 : 230 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={serie} margin={{ top: 4, right: 8, left: -18, bottom: 0 }}>
                    <CartesianGrid stroke="var(--line)" vertical={false} />
                    <XAxis dataKey="dia" tick={{ fontSize: 11, fill: "var(--ink-3)" }} tickLine={false} axisLine={false} interval="preserveStartEnd" minTickGap={18} />
                    <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "var(--ink-3)" }} tickLine={false} axisLine={false} />
                    <Tooltip contentStyle={{ borderRadius: 10, border: "1px solid var(--line)", fontSize: 12 }} />
                    <Area type="linear" dataKey="enviados" name="Enviados" stroke={COR.enviados} fill={COR.enviados} fillOpacity={0.12} strokeWidth={2} />
                    <Area type="linear" dataKey="respondidos" name="Responderam" stroke={COR.respondidos} fill={COR.respondidos} fillOpacity={0.1} strokeWidth={2} />
                    <Area type="linear" dataKey="falhas" name="Falhas" stroke={COR.falhas} fill="transparent" strokeWidth={1.5} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </Painel>
            <Painel titulo="Por tentativa">
              <div style={{ height: compacto ? 180 : 230 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={dados.por_passo.map((p) => ({ ...p, nome: `${p.tentativa}ª` }))} margin={{ top: 4, right: 4, left: -18, bottom: 0 }}>
                    <CartesianGrid stroke="var(--line)" vertical={false} />
                    <XAxis dataKey="nome" tick={{ fontSize: 11, fill: "var(--ink-3)" }} tickLine={false} axisLine={false} />
                    <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "var(--ink-3)" }} tickLine={false} axisLine={false} />
                    <Tooltip contentStyle={{ borderRadius: 10, border: "1px solid var(--line)", fontSize: 12 }} />
                    <Bar dataKey="enviados" name="Enviados" fill={COR.enviados} radius={[4, 4, 0, 0]} />
                    <Bar dataKey="respondidos" name="Responderam" fill={COR.respondidos} radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="s" style={{ fontSize: 12, marginTop: 6 }}>
                {dados.por_passo.filter((p) => p.enviados).map((p) => `${p.tentativa}ª: ${taxa(p.respondidos, p.enviados)}`).join(" · ") || "Nenhum envio ainda."}
              </div>
            </Painel>
          </div>
          <div className={compacto ? "stack" : "two"}>
            <Painel titulo="Por que não foi enviado">
              {dados.motivos.length === 0 ? <span className="sec">Nenhum follow-up cancelado no período.</span> : dados.motivos.map((m) => (
                <div key={m.motivo ?? "—"} className="fu-barra-h" style={{ "--fu-cor": "#94A3B8" } as CSSProperties}>
                  <span>{m.texto}</span><b className="num">{m.total}</b><i><s style={{ width: `${(100 * m.total) / maxMotivo}%` }} /></i>
                </div>
              ))}
            </Painel>
            {!agente && (
              <Painel titulo="Por agente" sem_corpo>
                {dados.por_agente.length === 0 ? <Vazio>Sem dados.</Vazio> : (
                  <div className="lst"><table>
                    <thead><tr><th>Agente</th><th className="num">Enviados</th><th className="num">Resposta</th><th className="num">Falhas</th></tr></thead>
                    <tbody>{dados.por_agente.map((p) => (
                      <tr key={p.id_agente ?? "-"}><td className="t">{(p.id_agente && nomes.get(p.id_agente)) || "agente apagado"}</td>
                        <td className="num">{p.enviados}</td><td className="num">{taxa(p.respondidos, p.enviados)}</td><td className="num">{p.falhas}</td></tr>
                    ))}</tbody>
                  </table></div>
                )}
              </Painel>
            )}
          </div>
        </>
      )}
      {t.falhas > 0 && !compacto && <Alerta tipo="warn">Houve {t.falhas} falha{t.falhas > 1 ? "s" : ""} no envio. Veja o motivo no Histórico (filtro "Falhas").</Alerta>}
    </div>
  );
}
