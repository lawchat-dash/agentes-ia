// Superadmin > Logs: o log da plataforma (o que acontece de administrativo, sem a conversa dos leads).
// Ativação e pausa de produto, IA ligada para todos, conta liberada ou bloqueada, recargas, follow-up, catálogo,
// usuários admin, acesso como cliente... Backend: app/gestao/rotas_log_plataforma.py (só a equipe LawChat).
import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ChevronDown, ChevronLeft, ChevronRight, Copy, Download, History, RefreshCw, Search } from "lucide-react";
import { NOME_PAPEL, quando, type Papel } from "../api";
import { Alerta, Cabecalho, Carregando, Interruptor, Vazio, linhaClicavel, useAvisar, useCarregar } from "../componentes/ui";

interface Item {
  id: string; criado_em: string;
  conta: { id: string | null; nome: string | null; id_conta_helena: string | null };
  executado_por: { id: string | null; nome: string | null; email: string | null; papel: string | null };
  funcao: string; rotulo: string; referencia: string | null; payload: unknown; resultado: unknown;
  status: "ok" | "erro"; erro: string | null; duracao_ms: number | null;
}
interface Lista { itens: Item[]; pagina: number; por_pagina: number; tem_mais: boolean; aviso?: string }
interface Resumo { total: number; sucesso: number; erros: number; taxa_sucesso: number | null; duracao_media_ms: number | null; funcoes: number; aviso?: string }
interface Filtros { contas: { id: string; nome: string }[]; funcoes: { funcao: string; rotulo: string }[] }

const PERIODOS: { valor: string; rotulo: string; horas: number }[] = [
  { valor: "1h", rotulo: "Última hora", horas: 1 }, { valor: "24h", rotulo: "Últimas 24 h", horas: 24 },
  { valor: "7d", rotulo: "Últimos 7 dias", horas: 24 * 7 }, { valor: "30d", rotulo: "Últimos 30 dias", horas: 24 * 30 },
  { valor: "90d", rotulo: "Últimos 90 dias", horas: 24 * 90 },
];
const TEMPO_REAL_MS = 15_000;
const duracao = (ms: number | null | undefined) => ms == null ? "—" : ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} s`;
const dataHora = (iso: string) => new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
const json = (v: unknown) => v == null ? "—" : typeof v === "string" ? v : JSON.stringify(v, null, 2);
const pct = (v: number | null) => v == null ? "—" : (v * 100).toLocaleString("pt-BR", { maximumFractionDigits: 1 }) + "%";
const nomePapel = (p: string | null) => (p && NOME_PAPEL[p as Papel]) || p || "—";
const preEstilo = { margin: 0, whiteSpace: "pre-wrap" as const, wordBreak: "break-word" as const, fontFamily: "var(--mono)", fontSize: 12,
  lineHeight: 1.55, background: "var(--surface-2)", border: "1px solid var(--line)", borderRadius: 10, padding: 10, maxHeight: 320, overflow: "auto" };

export function TelaAdminLogs() {
  const [texto, setTexto] = useState("");
  const [busca, setBusca] = useState("");
  const [periodo, setPeriodo] = useState("7d");
  const [de, setDe] = useState("");
  const [ate, setAte] = useState("");
  const [status, setStatus] = useState("");
  const [funcao, setFuncao] = useState("");
  const [conta, setConta] = useState("");
  const [pagina, setPagina] = useState(1);
  const [aberto, setAberto] = useState<string | null>(null);
  const [tempoReal, setTempoReal] = useState(true);
  const [minuto, setMinuto] = useState(() => Math.floor(Date.now() / 60_000));
  const [baixando, setBaixando] = useState(false);
  const avisar = useAvisar();

  useEffect(() => { const t = window.setTimeout(() => setBusca(texto.trim()), 400); return () => window.clearTimeout(t); }, [texto]);
  useEffect(() => { setPagina(1); }, [busca, periodo, de, ate, status, funcao, conta]);

  const filtrosApi = useMemo(() => {
    const p = new URLSearchParams();
    if (busca) p.set("busca", busca);
    if (status) p.set("status", status);
    if (funcao) p.set("funcao", funcao);
    if (conta) p.set("conta", conta);
    const relativo = PERIODOS.find((x) => x.valor === periodo);
    if (relativo) p.set("de", new Date(minuto * 60_000 - relativo.horas * 3_600_000).toISOString());
    else {
      if (de) p.set("de", new Date(`${de}T00:00:00`).toISOString());
      if (ate) { const fim = new Date(`${ate}T00:00:00`); fim.setDate(fim.getDate() + 1); p.set("ate", fim.toISOString()); }
    }
    return p.toString();
  }, [busca, status, funcao, conta, periodo, de, ate, minuto]);

  const { dados, erro, carregando, recarregar } = useCarregar<Lista>(`/admin/logs?${filtrosApi}&pagina=${pagina}&por_pagina=50`, [], { guardar: true });
  const { dados: resumo, recarregar: recarregarResumo } = useCarregar<Resumo>(`/admin/logs/resumo?${filtrosApi}`, [], { guardar: true });
  const { dados: filtros, recarregar: recarregarFiltros } = useCarregar<Filtros>("/admin/logs/filtros");

  // Tempo real: atualiza a cada 15 s com a aba visível (o período relativo anda junto).
  const atualizar = useRef(() => {});
  atualizar.current = () => {
    const agora = Math.floor(Date.now() / 60_000);
    if (agora !== minuto) setMinuto(agora);
    else { recarregar(); recarregarResumo(); }
  };
  useEffect(() => {
    if (!tempoReal) return;
    const t = window.setInterval(() => { if (document.visibilityState === "visible") atualizar.current(); }, TEMPO_REAL_MS);
    return () => window.clearInterval(t);
  }, [tempoReal]);

  const exportar = async () => {
    setBaixando(true);
    try {
      const resposta = await fetch(`/api/admin/logs/exportar.csv?${filtrosApi}`, { credentials: "same-origin" });
      if (!resposta.ok) {
        const corpo = await resposta.json().catch(() => null);
        throw new Error(typeof corpo?.detail === "string" ? corpo.detail : `Erro ${resposta.status}`);
      }
      const url = URL.createObjectURL(await resposta.blob());
      const a = document.createElement("a");
      a.href = url; a.download = `log-plataforma-${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(a); a.click(); a.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      avisar(e instanceof Error ? e.message : "Não deu para exportar.", "bad");
    } finally { setBaixando(false); }
  };

  const limpar = () => { setTexto(""); setStatus(""); setFuncao(""); setConta(""); setPeriodo("7d"); setDe(""); setAte(""); };
  const temFiltro = Boolean(busca || status || funcao || conta || periodo !== "7d");
  const aviso = dados?.aviso ?? resumo?.aviso;

  const kpi = (rotulo: string, valor: ReactNode, classe = "", filtro?: string) => {
    const miolo = <><span>{rotulo}</span><b>{valor}</b></>;
    if (filtro === undefined) return <div className={`kpi ${classe}`} key={rotulo}>{miolo}</div>;
    const ligado = filtro !== "" && status === filtro;
    return (
      <button type="button" className={`kpi ${classe}`} key={rotulo} onClick={() => setStatus(ligado ? "" : filtro)} aria-pressed={ligado}
        title="Filtrar a lista" style={{ textAlign: "left", cursor: "pointer", font: "inherit", color: "inherit", outline: ligado ? "2px solid var(--acento)" : undefined }}>{miolo}</button>
    );
  };

  return (
    <>
      <Cabecalho eyebrow="Superadmin" titulo="Logs"
        texto="Tudo o que acontece de administrativo na plataforma: ativação e pausa de produtos, IA ligada para todos, conta liberada ou bloqueada, recargas, follow-up, catálogo e usuários admin. Clique numa linha para ver o payload e o resultado."
        acoes={<div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <span className={`chip ${tempoReal ? "ok" : ""}`} title={tempoReal ? "Atualiza sozinho a cada 15 s" : "Atualização automática desligada"}>
            <span className="d" />TEMPO REAL</span>
          <Interruptor ligado={tempoReal} aoMudar={setTempoReal} rotulo="Atualizar a cada 15 s" />
          <button className="btn sm" onClick={() => { recarregar(); recarregarResumo(); recarregarFiltros(); }} disabled={carregando}>
            <RefreshCw className={carregando ? "animate-spin" : ""} />Atualizar</button>
          <button className="btn sm" onClick={exportar} disabled={baixando || !dados?.itens.length}><Download />{baixando ? "Exportando…" : "Exportar CSV"}</button>
        </div>} />

      {aviso && <><Alerta tipo="warn" titulo="Log ainda não ligado">{aviso}</Alerta><div style={{ height: 12 }} /></>}

      {resumo && (
        <div style={{ display: "grid", gap: 10, gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", marginBottom: 14 }}>
          {kpi("Total", resumo.total.toLocaleString("pt-BR"), "", "")}
          {kpi("Sucesso", resumo.sucesso.toLocaleString("pt-BR"), "ok", "ok")}
          {kpi("Erros", resumo.erros.toLocaleString("pt-BR"), resumo.erros ? "bad" : "", "erro")}
          {kpi("% sucesso", pct(resumo.taxa_sucesso), resumo.taxa_sucesso == null ? "" : resumo.taxa_sucesso < 0.95 ? "warn" : "ok")}
          {kpi("Duração média", duracao(resumo.duracao_media_ms))}
          {kpi("Funções", resumo.funcoes.toLocaleString("pt-BR"))}
        </div>
      )}

      <div className="panel" style={{ padding: 14, marginBottom: 14 }}>
        <div style={{ display: "grid", gap: 10, gridTemplateColumns: "repeat(auto-fill, minmax(190px, 1fr))", alignItems: "end" }}>
          <div className="field" style={{ gridColumn: "span 2" }}><label htmlFor="lg-busca">Buscar</label>
            <div style={{ position: "relative" }}>
              <Search style={{ position: "absolute", left: 10, top: 11, width: 15, height: 15, color: "var(--ink-3)" }} />
              <input id="lg-busca" value={texto} onChange={(e) => setTexto(e.target.value)} placeholder="Conta, referência, pessoa, função ou id" style={{ paddingLeft: 32 }} />
            </div></div>
          <div className="field"><label htmlFor="lg-periodo">Período</label>
            <select id="lg-periodo" value={periodo} onChange={(e) => setPeriodo(e.target.value)}>
              {PERIODOS.map((x) => <option key={x.valor} value={x.valor}>{x.rotulo}</option>)}
              <option value="datas">Escolher datas</option>
            </select></div>
          {periodo === "datas" && <>
            <div className="field"><label htmlFor="lg-de">De</label><input id="lg-de" type="date" value={de} onChange={(e) => setDe(e.target.value)} /></div>
            <div className="field"><label htmlFor="lg-ate">Até</label><input id="lg-ate" type="date" value={ate} onChange={(e) => setAte(e.target.value)} /></div>
          </>}
          <div className="field"><label htmlFor="lg-status">Status</label>
            <select id="lg-status" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">Qualquer status</option><option value="ok">Sucesso</option><option value="erro">Erro</option>
            </select></div>
          <div className="field"><label htmlFor="lg-funcao">Função</label>
            <select id="lg-funcao" value={funcao} onChange={(e) => setFuncao(e.target.value)}>
              <option value="">Todas as funções</option>
              {(filtros?.funcoes ?? []).map((f) => <option key={f.funcao} value={f.funcao}>{f.rotulo}</option>)}
            </select></div>
          <div className="field"><label htmlFor="lg-conta">Conta</label>
            <select id="lg-conta" value={conta} onChange={(e) => setConta(e.target.value)}>
              <option value="">Todas as contas</option>
              <option value="plataforma">Só da plataforma (sem conta)</option>
              {(filtros?.contas ?? []).map((c) => <option key={c.id} value={c.id}>{c.nome}</option>)}
            </select></div>
        </div>
        {temFiltro && <div style={{ marginTop: 10 }}><button className="btn ghost sm" onClick={limpar}>Limpar filtros</button></div>}
      </div>

      {!dados ? <Carregando erro={erro} /> : dados.itens.length === 0 ? (
        <div className="panel"><Vazio icone={<History />}>{temFiltro ? "Nada no log com esses filtros." : "Nada registrado no período."}</Vazio></div>
      ) : (
        <>
          <div className="lst"><table>
            <thead><tr><th>Quando</th><th>Conta</th><th>Função</th><th>Referência</th><th>Status</th><th>Duração</th><th /></tr></thead>
            <tbody>{dados.itens.map((i) => {
              const expandida = aberto === i.id;
              return (
                <Fragment key={i.id}>
                  <tr {...linhaClicavel(() => setAberto(expandida ? null : i.id), { rotulo: `Abrir ${i.rotulo}`, expandida })}
                    style={expandida ? { background: "var(--acento-suave)" } : undefined}>
                    <td className="s num" title={dataHora(i.criado_em)}>{quando(i.criado_em)}</td>
                    <td>{i.conta.nome ?? <span className="muted">Plataforma</span>}</td>
                    <td><div className="t">{i.rotulo}</div><div className="s mono muted" style={{ fontSize: 11 }}>{i.funcao}</div></td>
                    <td className="s" style={{ maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={i.referencia ?? ""}>{i.referencia ?? <span className="muted">—</span>}</td>
                    <td>{i.status === "ok" ? <span className="chip ok"><span className="d" />Sucesso</span>
                      : <span className="chip bad" title={i.erro ?? ""}><span className="d" />Erro</span>}</td>
                    <td className="num">{duracao(i.duracao_ms)}</td>
                    <td style={{ width: 28 }}><ChevronDown style={{ width: 16, height: 16, transform: expandida ? "rotate(180deg)" : undefined, transition: "transform .15s" }} /></td>
                  </tr>
                  {expandida && <tr><td colSpan={7} style={{ background: "var(--surface-2)", padding: 0 }}><Detalhe i={i} /></td></tr>}
                </Fragment>
              );
            })}</tbody>
          </table></div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", justifyContent: "flex-end", marginTop: 12 }}>
            <span className="sec" style={{ fontSize: 13 }}>Página {dados.pagina}</span>
            <button className="btn sm" disabled={pagina <= 1} onClick={() => setPagina((p) => Math.max(1, p - 1))}><ChevronLeft />Mais novas</button>
            <button className="btn sm" disabled={!dados.tem_mais} onClick={() => setPagina((p) => p + 1)}>Mais antigas<ChevronRight /></button>
          </div>
        </>
      )}
    </>
  );
}

function Campo({ rotulo, children }: { rotulo: string; children: ReactNode }) {
  return <div style={{ display: "grid", gap: 3, minWidth: 0 }}><span className="lbl">{rotulo}</span><div className="s" style={{ minWidth: 0, wordBreak: "break-word" }}>{children}</div></div>;
}

function BlocoJson({ titulo, valor }: { titulo: string; valor: unknown }) {
  const [copiado, setCopiado] = useState(false);
  const texto = json(valor);
  const copiar = async () => {
    try { await navigator.clipboard.writeText(texto); setCopiado(true); window.setTimeout(() => setCopiado(false), 1500); } catch { /* sem permissão */ }
  };
  return (
    <div style={{ display: "grid", gap: 6, minWidth: 0 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
        <span className="lbl">{titulo}</span>
        <button type="button" className="btn sm" onClick={copiar} disabled={valor == null}><Copy />{copiado ? "Copiado" : "Copiar"}</button>
      </div>
      <pre style={preEstilo}>{texto}</pre>
    </div>
  );
}

function Detalhe({ i }: { i: Item }) {
  return (
    <div style={{ padding: 14, display: "grid", gap: 14 }}>
      <div style={{ display: "grid", gap: 12, gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))" }}>
        <Campo rotulo="Conta">
          {i.conta.nome ?? "Plataforma (sem conta)"}
          {i.conta.id && <div className="mono muted" style={{ fontSize: 11 }}>id {i.conta.id}</div>}
          {i.conta.id_conta_helena && <div className="mono muted" style={{ fontSize: 11 }}>conta LawChat {i.conta.id_conta_helena}</div>}
        </Campo>
        <Campo rotulo="Executado por">
          {i.executado_por.nome ?? <span className="muted">sistema</span>}
          {i.executado_por.email && <div className="muted">{i.executado_por.email}</div>}
          <div className="muted">{nomePapel(i.executado_por.papel)}</div>
        </Campo>
        <Campo rotulo="Função">{i.rotulo}<div className="mono muted" style={{ fontSize: 11 }}>{i.funcao}</div></Campo>
        <Campo rotulo="Quando e duração">{dataHora(i.criado_em)}<div className="muted">{duracao(i.duracao_ms)}</div></Campo>
        <Campo rotulo="Referência"><span className="mono">{i.referencia ?? "—"}</span><div className="mono muted" style={{ fontSize: 11 }}>log {i.id}</div></Campo>
      </div>
      {i.erro && <Alerta tipo="bad" titulo="Erro">{i.erro}</Alerta>}
      <div style={{ display: "grid", gap: 12, gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))" }}>
        <BlocoJson titulo="Payload enviado" valor={i.payload} />
        <BlocoJson titulo="Resultado" valor={i.resultado} />
      </div>
    </div>
  );
}
