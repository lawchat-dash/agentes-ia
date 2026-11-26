// Superadmin > Execuções: cada turno da IA, como as execuções do n8n (lista com filtros e o detalhe num painel lateral).
// Backend: app/gestao/rotas_execucoes.py (só a equipe LawChat).
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { Activity, ChevronDown, ChevronLeft, ChevronRight, Copy, ExternalLink, RefreshCw, Search, X } from "lucide-react";
import { quando } from "../api";
import { Cabecalho, Carregando, Interruptor, Vazio, linhaClicavel, useCarregar } from "../componentes/ui";
import { useSessao } from "../sessao";

// --------------------------------------------------------------------------- tipos
interface Custo { brl: number; usd: number; tokens_entrada: number; tokens_saida: number; chamadas: number }
interface Tool { transferir_para: string | null; ferramenta: string | null; ferramenta_barrada: string | null; chamou: boolean }
interface Item {
  id: string; iniciado_em: string; concluido_em: string | null; duracao_ms: number | null;
  id_escritorio: string; conta: string; id_agente: string | null; agente: string | null; id_lead: string;
  lead: { nome: string | null; telefone: string | null }; modo: string;
  etapa_antes: string | null; etapa_depois: string | null; trocou_etapa: boolean; nome_antes: string | null; nome_depois: string | null;
  situacao: string; grupo: string; rotulo: string; motivo: string | null; tool: Tool; custo: Custo;
}
interface Lista { itens: Item[]; pagina: number; por_pagina: number; tem_mais: boolean }
interface Filtros { contas: { id: string; nome: string }[]; agentes: { id: string; nome: string; id_escritorio: string }[] }
interface Mensagem { id: string; autor: string; tipo: string; texto: string | null; texto_extraido: string | null; url_midia: string | null; enviada_em: string; situacao_envio: string; erro: string | null }
interface Evento { tipo: string; titulo: string; gravidade: string; responsavel: string | null; descricao: string | null; detalhe: unknown; criado_em: string; trava: boolean }
interface Chamada { papel: string; modelo: string; tokens_entrada: number; tokens_saida: number; tokens_cache: number; custo_usd: number; custo_brl: number; duracao_ms: number | null; sucesso: boolean; erro: string | null }
interface Detalhe extends Item {
  entrada: Mensagem[]; saida: Mensagem[]; mensagens_planejadas: { texto?: string }[];
  prompt: { sistema: string | null; conteudo: string | null; resposta_bruta: unknown; extrator: { conteudo: string | null; resposta: unknown } | null; tentativas: unknown[]; barreira: string | null; auditor?: unknown };
  decisao: {
    transferir_para: string | null; ferramenta: string | null; ferramenta_barrada: string | null; origem_destino: string | null;
    notificacao: string | null; destinos: string[]; acoes: string[]; intencoes: Record<string, unknown>;
    fatos_novos: Record<string, unknown>[]; fatos_rejeitados: Record<string, unknown>[]; reprovacoes: unknown[];
    decisoes: unknown[]; faltam: unknown[]; sinais: unknown[]; estado_lead: string | null; motivo_estado: string | null; ficha: string | null;
  };
  eventos: Evento[]; travas: Evento[];
  tempos: { passos_ms?: Record<string, number>; marcas_ms?: Record<string, number>; total_ms?: number; idas_ao_banco?: number } | null;
  chamadas: Chamada[]; navegacao: { anterior: string | null; seguinte: string | null };
}

// --------------------------------------------------------------------------- formatos
const reais = (v: number) => "R$ " + v.toLocaleString("pt-BR", { minimumFractionDigits: 4, maximumFractionDigits: 4 });
const duracao = (ms: number | null | undefined) => ms == null ? "—" : ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} s`;
const dataHora = (iso: string) => new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
const json = (v: unknown) => typeof v === "string" ? v : JSON.stringify(v, null, 2);
const CLASSE_GRUPO: Record<string, string> = { respondido: "ok", sem_resposta: "warn", erro: "bad", processando: "info" };

function ChipSituacao({ item }: { item: Pick<Item, "grupo" | "rotulo" | "motivo"> }) {
  return (
    <span style={{ display: "inline-flex", flexDirection: "column", gap: 2 }}>
      <span className={`chip ${CLASSE_GRUPO[item.grupo] ?? ""}`}><span className="d" />{item.rotulo}</span>
      {item.grupo !== "respondido" && item.motivo && <span className="s mono" style={{ fontSize: 11 }}>{item.motivo}</span>}
    </span>
  );
}

function ChipTool({ tool }: { tool: Tool }) {
  if (!tool.chamou && !tool.ferramenta_barrada) return <span className="muted">—</span>;
  return (
    <span style={{ display: "inline-flex", gap: 4, flexWrap: "wrap" }}>
      {tool.transferir_para && <span className="chip ac">→ {tool.transferir_para}</span>}
      {tool.ferramenta && <span className="chip info">{tool.ferramenta}</span>}
      {tool.ferramenta_barrada && <span className="chip warn">barrada: {tool.ferramenta_barrada}</span>}
    </span>
  );
}

function Etapas({ item }: { item: Item }) {
  const antes = item.nome_antes ?? item.etapa_antes ?? "—";
  const depois = item.nome_depois ?? item.etapa_depois;
  if (!item.trocou_etapa) return <span>{antes}</span>;
  return <span>{antes} <span className="muted">→</span> <b>{depois}</b></span>;
}

// --------------------------------------------------------------------------- tela
export function TelaExecucoes() {
  const { id } = useParams();
  const navegar = useNavigate();
  const local = useLocation();
  const busca0 = new URLSearchParams(local.search);
  const [conta, setConta] = useState(busca0.get("conta") ?? "");
  const [agente, setAgente] = useState(busca0.get("agente") ?? "");
  const [texto, setTexto] = useState(busca0.get("busca") ?? "");
  const [busca, setBusca] = useState(texto);
  const [situacao, setSituacao] = useState(busca0.get("situacao") ?? "");
  const [troca, setTroca] = useState(busca0.get("troca") === "1");
  const [soErro, setSoErro] = useState(busca0.get("erro") === "1");
  const [de, setDe] = useState(busca0.get("de") ?? "");
  const [ate, setAte] = useState(busca0.get("ate") ?? "");
  const [pagina, setPagina] = useState(1);
  const [aoVivo, setAoVivo] = useState(true);

  useEffect(() => { const t = window.setTimeout(() => setBusca(texto.trim()), 400); return () => window.clearTimeout(t); }, [texto]);
  useEffect(() => { setPagina(1); }, [conta, agente, busca, situacao, troca, soErro, de, ate]);

  // Filtros na URL (voltar do detalhe ou recarregar a página mantém a lista como estava).
  const consulta = useMemo(() => {
    const p = new URLSearchParams();
    if (conta) p.set("conta", conta);
    if (agente) p.set("agente", agente);
    if (busca) p.set("busca", busca);
    if (situacao) p.set("situacao", situacao);
    if (troca) p.set("troca", "1");
    if (soErro) p.set("erro", "1");
    if (de) p.set("de", de);
    if (ate) p.set("ate", ate);
    return p;
  }, [conta, agente, busca, situacao, troca, soErro, de, ate]);
  useEffect(() => {
    const alvo = consulta.toString();
    if (alvo !== local.search.replace(/^\?/, "")) navegar({ pathname: local.pathname, search: alvo }, { replace: true });
  }, [consulta]); // eslint-disable-line react-hooks/exhaustive-deps

  const caminho = useMemo(() => {
    const p = new URLSearchParams();
    if (conta) p.set("conta", conta);
    if (agente) p.set("agente", agente);
    if (busca) p.set("busca", busca);
    if (situacao) p.set("situacao", situacao);
    if (troca) p.set("troca", "true");
    if (soErro) p.set("erro", "true");
    if (de) p.set("de", new Date(`${de}T00:00:00`).toISOString());
    if (ate) { const fim = new Date(`${ate}T00:00:00`); fim.setDate(fim.getDate() + 1); p.set("ate", fim.toISOString()); }
    p.set("pagina", String(pagina));
    p.set("por_pagina", "50");
    return `/admin/execucoes?${p.toString()}`;
  }, [conta, agente, busca, situacao, troca, soErro, de, ate, pagina]);

  const { dados, erro, carregando, recarregar } = useCarregar<Lista>(caminho, [], { guardar: true });
  const { dados: filtros } = useCarregar<Filtros>("/admin/execucoes/filtros");
  const agentes = (filtros?.agentes ?? []).filter((a) => !conta || a.id_escritorio === conta);

  // Ao vivo: atualiza a cada 10 s (só com a aba visível).
  const recarregarRef = useRef(recarregar);
  recarregarRef.current = recarregar;
  useEffect(() => {
    if (!aoVivo) return;
    const t = window.setInterval(() => { if (document.visibilityState === "visible") recarregarRef.current(); }, 10_000);
    return () => window.clearInterval(t);
  }, [aoVivo]);

  const abrir = (idTurno: string) => navegar({ pathname: `/admin/execucoes/${idTurno}`, search: local.search });
  const fechar = () => navegar({ pathname: "/admin/execucoes", search: local.search });
  const limparFiltros = () => { setConta(""); setAgente(""); setTexto(""); setSituacao(""); setTroca(false); setSoErro(false); setDe(""); setAte(""); };
  const temFiltro = Boolean(conta || agente || busca || situacao || troca || soErro || de || ate);

  return (
    <>
      <Cabecalho eyebrow="Superadmin" titulo="Execuções"
        texto="Cada turno da IA: o que o lead mandou, o prompt que rodou, o que a IA decidiu e o que saiu. Clique numa linha para abrir."
        acoes={<div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <Interruptor ligado={aoVivo} aoMudar={setAoVivo} rotulo="Atualizar a cada 10 s" />
          <span className="sec" style={{ fontSize: 13 }}>Ao vivo (10 s)</span>
          <button className="btn sm" onClick={() => recarregar()} disabled={carregando}><RefreshCw className={carregando ? "animate-spin" : ""} />Atualizar</button>
        </div>} />

      <div className="panel" style={{ padding: 14, marginBottom: 14 }}>
        <div style={{ display: "grid", gap: 10, gridTemplateColumns: "repeat(auto-fill, minmax(190px, 1fr))", alignItems: "end" }}>
          <div className="field"><label htmlFor="ex-conta">Conta</label>
            <select id="ex-conta" value={conta} onChange={(e) => { setConta(e.target.value); setAgente(""); }}>
              <option value="">Todas as contas</option>
              {(filtros?.contas ?? []).map((c) => <option key={c.id} value={c.id}>{c.nome}</option>)}
            </select></div>
          <div className="field"><label htmlFor="ex-agente">Agente</label>
            <select id="ex-agente" value={agente} onChange={(e) => setAgente(e.target.value)}>
              <option value="">Todos os agentes</option>
              {agentes.map((a) => <option key={a.id} value={a.id}>{a.nome}</option>)}
            </select></div>
          <div className="field"><label htmlFor="ex-busca">Lead (nome ou número)</label>
            <div style={{ position: "relative" }}>
              <Search style={{ position: "absolute", left: 10, top: 11, width: 15, height: 15, color: "var(--ink-3)" }} />
              <input id="ex-busca" value={texto} onChange={(e) => setTexto(e.target.value)} placeholder="Maria, 31 98888…" style={{ paddingLeft: 32 }} />
            </div></div>
          <div className="field"><label htmlFor="ex-situacao">Situação</label>
            <select id="ex-situacao" value={situacao} onChange={(e) => setSituacao(e.target.value)}>
              <option value="">Qualquer situação</option>
              <option value="respondido">Respondido</option>
              <option value="sem_resposta">Sem resposta</option>
              <option value="erro">Erro</option>
              <option value="processando">Processando</option>
            </select></div>
          <div className="field"><label htmlFor="ex-de">De</label><input id="ex-de" type="date" value={de} onChange={(e) => setDe(e.target.value)} /></div>
          <div className="field"><label htmlFor="ex-ate">Até</label><input id="ex-ate" type="date" value={ate} onChange={(e) => setAte(e.target.value)} /></div>
        </div>
        <div style={{ display: "flex", gap: 18, flexWrap: "wrap", alignItems: "center", marginTop: 12 }}>
          <label className="check"><input type="checkbox" checked={troca} onChange={(e) => setTroca(e.target.checked)} /><span>Só com troca de etapa</span></label>
          <label className="check"><input type="checkbox" checked={soErro} onChange={(e) => setSoErro(e.target.checked)} /><span>Só com erro</span></label>
          {temFiltro && <button className="btn ghost sm" onClick={limparFiltros}>Limpar filtros</button>}
        </div>
      </div>

      {!dados ? <Carregando erro={erro} /> : dados.itens.length === 0 ? (
        <div className="panel"><Vazio icone={<Activity />}>{temFiltro ? "Nenhuma execução com esses filtros." : "Nenhuma execução ainda."}</Vazio></div>
      ) : (
        <>
          <div className="lst"><table>
            <thead><tr><th>Quando</th><th>Conta</th><th>Agente</th><th>Lead</th><th>Etapa</th><th>Situação</th><th>Tool</th><th>Duração</th><th>Custo</th></tr></thead>
            <tbody>{dados.itens.map((i) => (
              <tr key={i.id} {...linhaClicavel(() => abrir(i.id), { rotulo: `Abrir execução de ${i.lead.nome ?? "lead"}`, selecionada: i.id === id })}
                style={i.id === id ? { background: "var(--acento-suave)" } : undefined}>
                <td className="s num" title={dataHora(i.iniciado_em)}>{quando(i.iniciado_em)}{i.modo !== "producao" && <div><span className="chip info">{i.modo}</span></div>}</td>
                <td>{i.conta}</td>
                <td>{i.agente ?? <span className="muted">—</span>}</td>
                <td><div className="t">{i.lead.nome || "Sem nome"}</div><div className="s num">{i.lead.telefone ?? "número oculto"}</div></td>
                <td><Etapas item={i} /></td>
                <td><ChipSituacao item={i} /></td>
                <td><ChipTool tool={i.tool} /></td>
                <td className="num">{duracao(i.duracao_ms)}</td>
                <td className="num" title={`${i.custo.chamadas} chamada(s) · ${i.custo.tokens_entrada} + ${i.custo.tokens_saida} tokens`}>{i.custo.chamadas ? reais(i.custo.brl) : "—"}</td>
              </tr>
            ))}</tbody>
          </table></div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", justifyContent: "flex-end", marginTop: 12 }}>
            <span className="sec" style={{ fontSize: 13 }}>Página {dados.pagina}</span>
            <button className="btn sm" disabled={pagina <= 1} onClick={() => setPagina((p) => Math.max(1, p - 1))}><ChevronLeft />Mais novas</button>
            <button className="btn sm" disabled={!dados.tem_mais} onClick={() => setPagina((p) => p + 1)}>Mais antigas<ChevronRight /></button>
          </div>
        </>
      )}

      {id && <PainelDetalhe id={id} aoFechar={fechar} aoAbrir={abrir} />}
    </>
  );
}

// --------------------------------------------------------------------------- detalhe (painel lateral)
function PainelDetalhe({ id, aoFechar, aoAbrir }: { id: string; aoFechar: () => void; aoAbrir: (id: string) => void }) {
  const { dados, erro } = useCarregar<Detalhe>(`/admin/execucoes/${id}`, [id]);
  const { trocarEscritorio } = useSessao();
  const navegar = useNavigate();
  const fecharRef = useRef(aoFechar);
  fecharRef.current = aoFechar;
  useEffect(() => {
    const tecla = (e: KeyboardEvent) => { if (e.key === "Escape") fecharRef.current(); };
    document.addEventListener("keydown", tecla);
    return () => document.removeEventListener("keydown", tecla);
  }, []);
  const d = dados && dados.id === id ? dados : null;

  const abrirConversa = () => {
    if (!d) return;
    trocarEscritorio(d.id_escritorio);
    navegar(`/conversas/${d.id_lead}`);
  };

  return createPortal(
    <div className="ov" style={{ justifyContent: "flex-end" }} onMouseDown={(e) => { if (e.target === e.currentTarget) aoFechar(); }}>
      <aside role="dialog" aria-modal="true" aria-label="Detalhe da execução"
        style={{ width: "min(860px, 100%)", height: "100%", background: "var(--bg)", borderLeft: "1px solid var(--line)", boxShadow: "var(--sombra-lg)", display: "flex", flexDirection: "column" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "14px 18px", borderBottom: "1px solid var(--line)", background: "var(--surface)", flexWrap: "wrap" }}>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div className="mono muted" style={{ fontSize: 11, letterSpacing: ".08em", textTransform: "uppercase" }}>Execução</div>
            <h2 style={{ fontSize: 18 }}>{d ? `${d.lead.nome || "Sem nome"} · ${d.lead.telefone ?? "número oculto"}` : "Carregando…"}</h2>
            {d && <div className="sec" style={{ fontSize: 12.5 }}>{dataHora(d.iniciado_em)} · {d.conta} · {d.agente ?? "sem agente"} · {duracao(d.duracao_ms)}{d.custo.chamadas ? ` · ${reais(d.custo.brl)}` : ""}</div>}
          </div>
          <button className="btn sm" disabled={!d?.navegacao.anterior} onClick={() => d?.navegacao.anterior && aoAbrir(d.navegacao.anterior)} title="Execução anterior do mesmo lead"><ChevronLeft />Anterior</button>
          <button className="btn sm" disabled={!d?.navegacao.seguinte} onClick={() => d?.navegacao.seguinte && aoAbrir(d.navegacao.seguinte)} title="Execução seguinte do mesmo lead">Seguinte<ChevronRight /></button>
          <button className="btn sm" disabled={!d} onClick={abrirConversa}><ExternalLink />Abrir conversa</button>
          <button className="btn ghost sm" onClick={aoFechar} aria-label="Fechar"><X /></button>
        </div>
        <div style={{ overflowY: "auto", padding: 18, flex: 1 }}>
          {!d ? <Carregando erro={erro} /> : <ConteudoDetalhe d={d} />}
        </div>
      </aside>
    </div>,
    document.body,
  );
}

function Bloco({ titulo, extra, children }: { titulo: string; extra?: ReactNode; children: ReactNode }) {
  return (
    <section className="panel" style={{ marginBottom: 14 }}>
      <div className="panel-h"><h3>{titulo}</h3>{extra && <div className="more">{extra}</div>}</div>
      <div className="panel-b">{children}</div>
    </section>
  );
}

function Balao({ m, lado }: { m: { texto?: string | null; texto_extraido?: string | null; tipo?: string; enviada_em?: string; situacao_envio?: string; erro?: string | null }; lado: "lead" | "ia" }) {
  const daIa = lado === "ia";
  return (
    <div style={{ display: "flex", justifyContent: daIa ? "flex-end" : "flex-start" }}>
      <div style={{ maxWidth: "80%", padding: "8px 12px", borderRadius: 14, whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: 13.5,
        background: daIa ? "var(--acento-suave)" : "var(--surface-2)", border: "1px solid var(--line)",
        borderBottomRightRadius: daIa ? 4 : 14, borderBottomLeftRadius: daIa ? 14 : 4 }}>
        {m.tipo && m.tipo !== "texto" && <span className="chip" style={{ marginRight: 6 }}>{m.tipo}</span>}
        {m.texto || m.texto_extraido || <span className="muted">(sem texto)</span>}
        {m.texto && m.texto_extraido && <div className="s muted" style={{ marginTop: 4 }}>Transcrição: {m.texto_extraido}</div>}
        <div className="s muted num" style={{ fontSize: 11, marginTop: 4, textAlign: "right" }}>
          {m.enviada_em ? dataHora(m.enviada_em) : ""}
          {m.situacao_envio && m.situacao_envio !== "recebida" && <> · <span className={m.situacao_envio === "falhou" ? "chip bad" : m.situacao_envio === "pendente" ? "chip warn" : "chip ok"}>{m.situacao_envio}</span></>}
        </div>
        {m.erro && <div className="s" style={{ color: "var(--bad)" }}>{m.erro}</div>}
      </div>
    </div>
  );
}

function ConteudoDetalhe({ d }: { d: Detalhe }) {
  const dec = d.decisao;
  const intencoes = Object.entries(dec.intencoes ?? {}).filter(([, v]) => v !== false && v !== null && v !== "");
  const reprovacoes = (dec.reprovacoes ?? []).map((r) => (Array.isArray(r) ? r : [r])) as Record<string, unknown>[][];
  const passos = Object.entries(d.tempos?.passos_ms ?? {}).sort((a, b) => b[1] - a[1]);
  const maiorPasso = Math.max(1, ...passos.map(([, v]) => v));
  return (
    <>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14, alignItems: "center" }}>
        <ChipSituacao item={d} />
        <span className="sec">Etapa: <Etapas item={d} /></span>
        <ChipTool tool={d.tool} />
        {d.modo !== "producao" && <span className="chip info">{d.modo}</span>}
      </div>

      <Bloco titulo="1. Mensagens do lead que entraram">
        {d.entrada.length === 0 ? <p className="muted" style={{ margin: 0 }}>Nenhuma mensagem do lead ligada a este turno.</p>
          : <div style={{ display: "grid", gap: 8 }}>{d.entrada.map((m) => <Balao key={m.id} m={m} lado="lead" />)}</div>}
      </Bloco>

      <BlocoPrompt d={d} />

      <Bloco titulo="3. Decisão da IA">
        <div style={{ display: "grid", gap: 12 }}>
          <Linha rotulo="Passagem de etapa">{dec.transferir_para ? <><span className="chip ac">→ {dec.transferir_para}</span>{dec.origem_destino && <span className="s muted"> pela {dec.origem_destino === "frase" ? "frase de passagem" : "IA"}</span>}</> : <span className="muted">não pediu</span>}
            {dec.destinos.length > 0 && <div className="s muted">Destinos permitidos: {dec.destinos.join(", ")}</div>}</Linha>
          <Linha rotulo="Ferramenta">{dec.ferramenta ? <span className="chip info">{dec.ferramenta}</span> : <span className="muted">nenhuma</span>}
            {dec.ferramenta_barrada && <span className="chip warn" style={{ marginLeft: 6 }}>barrada: {dec.ferramenta_barrada}</span>}
            {dec.acoes.length > 0 && <div className="s muted">Ferramentas do papel: {dec.acoes.join(", ")}</div>}</Linha>
          {dec.notificacao && <Linha rotulo="Aviso à equipe">{dec.notificacao}</Linha>}
          <Linha rotulo="Intenções">{intencoes.length === 0 ? <span className="muted">nenhuma</span>
            : <span style={{ display: "inline-flex", gap: 4, flexWrap: "wrap" }}>{intencoes.map(([k, v]) => <span key={k} className="chip">{k}{v === true ? "" : `: ${json(v)}`}</span>)}</span>}</Linha>
          {(dec.estado_lead || dec.motivo_estado) && <Linha rotulo="Estado do lead">{dec.estado_lead ?? "—"}{dec.motivo_estado && <span className="s muted"> ({dec.motivo_estado})</span>}</Linha>}
          <TabelaFatos titulo="Fatos novos" fatos={dec.fatos_novos} />
          <TabelaFatos titulo="Fatos rejeitados" fatos={dec.fatos_rejeitados} motivo />
          <div>
            <div className="lbl" style={{ marginBottom: 6 }}>Correções e travas que atuaram</div>
            {reprovacoes.length === 0 && d.travas.length === 0 ? <span className="muted">nenhuma</span> : (
              <div style={{ display: "grid", gap: 6 }}>
                {reprovacoes.map((lista, n) => (
                  <div key={`r${n}`} className="alerta warn"><div><span className="alerta-t">Reprovação na {n + 1}ª resposta</span>
                    {lista.map((r, k) => <div key={k}><b className="mono">{String(r.codigo ?? "trava")}</b>{r.orientacao ? `: ${String(r.orientacao)}` : r.motivo ? `: ${String(r.motivo)}` : ""}</div>)}
                  </div></div>
                ))}
                {d.travas.map((e, n) => (
                  <div key={`t${n}`} className="alerta info"><div><span className="alerta-t">{e.titulo}</span>{e.descricao}<div className="s mono muted">{e.tipo}</div></div></div>
                ))}
              </div>
            )}
          </div>
          {dec.faltam.length > 0 && <Linha rotulo="Faltam">{dec.faltam.map((f) => json(f)).join(", ")}</Linha>}
          {dec.sinais.length > 0 && <Linha rotulo="Sinais">{dec.sinais.map((f) => json(f)).join(", ")}</Linha>}
          {dec.ficha && <Linha rotulo="Ficha"><pre style={preEstilo}>{dec.ficha}</pre></Linha>}
          {dec.decisoes.length > 0 && <Recolhivel titulo={`Decisões do motor (${dec.decisoes.length})`}><pre style={preEstilo}>{json(dec.decisoes)}</pre></Recolhivel>}
        </div>
      </Bloco>

      <Bloco titulo="4. Resposta que saiu">
        {d.saida.length > 0 ? <div style={{ display: "grid", gap: 8 }}>{d.saida.map((m) => <Balao key={m.id} m={m} lado="ia" />)}</div>
          : d.mensagens_planejadas.length > 0 ? (
            <>
              <p className="sec" style={{ marginTop: 0 }}>Nenhuma mensagem gravada como enviada. O que a IA montou:</p>
              <div style={{ display: "grid", gap: 8 }}>{d.mensagens_planejadas.map((m, n) => <Balao key={n} m={{ texto: m.texto ?? json(m) }} lado="ia" />)}</div>
            </>
          ) : <p className="muted" style={{ margin: 0 }}>Nada saiu neste turno{d.motivo ? ` (${d.motivo})` : ""}.</p>}
      </Bloco>

      <Bloco titulo="5. Eventos, tempos e custo">
        <div style={{ display: "grid", gap: 14 }}>
          <div>
            <div className="lbl" style={{ marginBottom: 6 }}>Eventos do turno</div>
            {d.eventos.length === 0 ? <span className="muted">nenhum</span> : (
              <div className="rows" style={{ border: "1px solid var(--line)", borderRadius: 10 }}>
                {d.eventos.map((e, n) => (
                  <div key={n} style={{ alignItems: "flex-start" }}>
                    <span className="s num muted" style={{ minWidth: 70 }}>{new Date(e.criado_em).toLocaleTimeString("pt-BR")}</span>
                    <div style={{ minWidth: 0 }}><b>{e.titulo}</b> <span className={`chip ${e.gravidade === "erro" || e.gravidade === "critico" ? "bad" : e.gravidade === "aviso" ? "warn" : ""}`}>{e.gravidade}</span>
                      {e.descricao && <div className="sec" style={{ fontSize: 13 }}>{e.descricao}</div>}<div className="s mono muted">{e.tipo}</div></div>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div>
            <div className="lbl" style={{ marginBottom: 6 }}>Tempos por passo {d.tempos?.total_ms != null && <span className="muted">· total {duracao(d.tempos.total_ms)}{d.tempos.idas_ao_banco != null ? ` · ${d.tempos.idas_ao_banco} idas ao banco` : ""}</span>}</div>
            {passos.length === 0 ? <span className="muted">sem medição neste turno</span> : (
              <div style={{ display: "grid", gap: 4 }}>
                {passos.map(([nome, ms]) => (
                  <div key={nome} style={{ display: "grid", gridTemplateColumns: "150px 1fr 70px", gap: 8, alignItems: "center", fontSize: 12.5 }}>
                    <span className="mono">{nome}</span>
                    <span style={{ height: 8, borderRadius: 4, background: "var(--surface-3)" }}><span style={{ display: "block", height: 8, borderRadius: 4, width: `${(ms / maiorPasso) * 100}%`, background: "var(--acento)" }} /></span>
                    <span className="num" style={{ textAlign: "right" }}>{duracao(ms)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div>
            <div className="lbl" style={{ marginBottom: 6 }}>Chamadas de IA {d.custo.chamadas > 0 && <span className="muted">· {reais(d.custo.brl)} · US$ {d.custo.usd.toFixed(4)}</span>}</div>
            {d.chamadas.length === 0 ? <span className="muted">nenhuma</span> : (
              <div className="lst"><table>
                <thead><tr><th>Papel</th><th>Modelo</th><th>Tokens</th><th>Duração</th><th>Custo</th><th /></tr></thead>
                <tbody>{d.chamadas.map((c, n) => (
                  <tr key={n}><td className="mono">{c.papel}</td><td className="mono s">{c.modelo}</td>
                    <td className="num s">{c.tokens_entrada} + {c.tokens_saida}{c.tokens_cache ? ` (cache ${c.tokens_cache})` : ""}</td>
                    <td className="num s">{duracao(c.duracao_ms)}</td><td className="num s">{reais(c.custo_brl)}</td>
                    <td>{c.sucesso ? <span className="chip ok">ok</span> : <span className="chip bad" title={c.erro ?? ""}>falhou</span>}</td></tr>
                ))}</tbody>
              </table></div>
            )}
          </div>
        </div>
      </Bloco>
    </>
  );
}

const preEstilo = { margin: 0, whiteSpace: "pre-wrap" as const, wordBreak: "break-word" as const, fontFamily: "var(--mono)", fontSize: 12, lineHeight: 1.55 };

function Linha({ rotulo, children }: { rotulo: string; children: ReactNode }) {
  return <div style={{ display: "grid", gridTemplateColumns: "150px 1fr", gap: 10 }}><span className="lbl">{rotulo}</span><div style={{ minWidth: 0 }}>{children}</div></div>;
}

function TabelaFatos({ titulo, fatos, motivo }: { titulo: string; fatos: Record<string, unknown>[]; motivo?: boolean }) {
  return (
    <div>
      <div className="lbl" style={{ marginBottom: 6 }}>{titulo} <span className="muted">({fatos.length})</span></div>
      {fatos.length === 0 ? <span className="muted">nenhum</span> : (
        <div className="lst"><table>
          <thead><tr><th>Campo</th><th>Valor</th><th>Trecho do lead</th>{motivo && <th>Motivo</th>}</tr></thead>
          <tbody>{fatos.map((f, n) => (
            <tr key={n}><td className="mono s">{String(f.chave ?? "—")}</td><td>{json(f.valor ?? "—")}</td>
              <td className="s">{f.trecho ? `“${String(f.trecho)}”` : "—"}</td>{motivo && <td className="mono s">{String(f.motivo ?? "—")}</td>}</tr>
          ))}</tbody>
        </table></div>
      )}
    </div>
  );
}

function Recolhivel({ titulo, children, aberto = false }: { titulo: ReactNode; children: ReactNode; aberto?: boolean }) {
  const [on, setOn] = useState(aberto);
  useEffect(() => { setOn(aberto); }, [aberto]);
  return (
    <div style={{ border: "1px solid var(--line)", borderRadius: 10, background: "var(--surface)" }}>
      <button type="button" onClick={() => setOn(!on)} aria-expanded={on}
        style={{ display: "flex", gap: 6, alignItems: "center", width: "100%", border: 0, background: "transparent", padding: "8px 10px", textAlign: "left", fontWeight: 600, fontSize: 12.5 }}>
        {on ? <ChevronDown style={{ width: 14, height: 14 }} /> : <ChevronRight style={{ width: 14, height: 14 }} />}{titulo}
      </button>
      {on && <div style={{ padding: "0 10px 10px" }}>{children}</div>}
    </div>
  );
}

// --------------------------------------------------------------------------- prompt
interface Secao { titulo: string; texto: string }

// Cabeçalho de seção: "# REGRAS DO ATENDIMENTO (sistema)" no sistema, "MENSAGENS NOVAS DO LEAD:" no conteúdo.
const CABECALHO = /^\s*(#{1,3}\s+\S.*|[A-ZÀ-Ý][A-ZÀ-Ý0-9 ,./\-]{5,}(\s*\([^)]*\))?\s*:)/;

function dividir(texto: string): Secao[] {
  const secoes: Secao[] = [];
  let atual: Secao = { titulo: "Início", texto: "" };
  for (const linha of texto.split("\n")) {
    const m = linha.match(CABECALHO);
    if (m) {
      if (atual.texto.trim() || atual.titulo !== "Início") secoes.push(atual);
      atual = { titulo: m[1].replace(/^#+\s*/, "").replace(/:\s*$/, "").slice(0, 90), texto: linha + "\n" };
    } else atual.texto += linha + "\n";
  }
  if (atual.texto.trim()) secoes.push(atual);
  return secoes;
}

function Destacar({ texto, termo }: { texto: string; termo: string }) {
  if (!termo) return <>{texto}</>;
  const partes = texto.split(new RegExp(`(${termo.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi"));
  return <>{partes.map((p, n) => (n % 2 === 1 ? <mark key={n} style={{ background: "#FDE68A", color: "inherit", borderRadius: 2 }}>{p}</mark> : p))}</>;
}

function BlocoPrompt({ d }: { d: Detalhe }) {
  const p = d.prompt;
  const abas = useMemo(() => {
    const lista: { chave: string; rotulo: string; texto: string }[] = [];
    if (p.sistema) lista.push({ chave: "sistema", rotulo: "Sistema (roteiro e regras)", texto: p.sistema });
    if (p.conteudo) lista.push({ chave: "conteudo", rotulo: "Conteúdo (dados e conversa)", texto: p.conteudo });
    if (p.resposta_bruta != null) lista.push({ chave: "resposta", rotulo: "Resposta do modelo", texto: json(p.resposta_bruta) });
    if (p.extrator?.conteudo) lista.push({ chave: "extrator", rotulo: "Extrator", texto: p.extrator.conteudo + (p.extrator.resposta != null ? "\n\n# RESPOSTA DO EXTRATOR\n" + json(p.extrator.resposta) : "") });
    if (p.tentativas.length) lista.push({ chave: "tentativas", rotulo: `Tentativas (${p.tentativas.length})`, texto: json(p.tentativas) });
    return lista;
  }, [p]);
  const [aba, setAba] = useState(abas[0]?.chave ?? "");
  const [termo, setTermo] = useState("");
  const [todas, setTodas] = useState<boolean | null>(null);
  const [copiado, setCopiado] = useState(false);
  useEffect(() => { setAba(abas[0]?.chave ?? ""); setTodas(null); }, [d.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const atual = abas.find((a) => a.chave === aba) ?? abas[0];
  const secoes = useMemo(() => (atual ? dividir(atual.texto) : []), [atual]);
  const t = termo.trim();
  const achados = t && atual ? (atual.texto.match(new RegExp(t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi")) ?? []).length : 0;

  const copiar = async () => {
    if (!atual) return;
    try { await navigator.clipboard.writeText(atual.texto); setCopiado(true); window.setTimeout(() => setCopiado(false), 1500); } catch { /* sem permissão de área de transferência */ }
  };

  if (!atual) return <Bloco titulo="2. Prompt que rodou"><p className="muted" style={{ margin: 0 }}>Este turno não chegou a chamar o modelo{p.barreira ? ` (barreira: ${p.barreira})` : ""}.</p></Bloco>;
  return (
    <Bloco titulo="2. Prompt que rodou" extra={<>
      <button className="btn sm" onClick={() => setTodas(true)}>Abrir seções</button>
      <button className="btn sm" onClick={() => setTodas(false)}>Fechar seções</button>
      <button className="btn sm" onClick={copiar}><Copy />{copiado ? "Copiado" : "Copiar"}</button>
    </>}>
      <div className="tabs" style={{ marginBottom: 10 }}>
        {abas.map((a) => <button key={a.chave} className={a.chave === atual.chave ? "on" : ""} onClick={() => { setAba(a.chave); setTodas(null); }}>{a.rotulo}</button>)}
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10 }}>
        <div style={{ position: "relative", flex: 1 }}>
          <Search style={{ position: "absolute", left: 10, top: 10, width: 15, height: 15, color: "var(--ink-3)" }} />
          <input className="inp" value={termo} onChange={(e) => setTermo(e.target.value)} placeholder="Buscar no prompt" style={{ paddingLeft: 32 }} aria-label="Buscar no prompt" />
        </div>
        {t && <span className="s muted num">{achados} achado(s)</span>}
        <span className="s muted num">{atual.texto.length.toLocaleString("pt-BR")} caracteres</span>
      </div>
      <div style={{ maxHeight: "60vh", overflowY: "auto", display: "grid", gap: 6, padding: 2 }}>
        {secoes.length <= 1 ? (
          <pre style={{ ...preEstilo, background: "var(--surface-2)", border: "1px solid var(--line)", borderRadius: 10, padding: 12 }}><Destacar texto={atual.texto} termo={t} /></pre>
        ) : secoes.map((s, n) => {
          const tem = t ? s.texto.toLowerCase().includes(t.toLowerCase()) : false;
          const aberto = todas ?? (t ? tem : false);
          return (
            <Recolhivel key={`${atual.chave}-${n}`} aberto={t ? tem || Boolean(todas) : aberto}
              titulo={<span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>{s.titulo}<span className="s muted num" style={{ fontWeight: 400 }}>{s.texto.length.toLocaleString("pt-BR")}</span>{tem && <span className="chip warn">achado</span>}</span>}>
              <pre style={{ ...preEstilo, background: "var(--surface-2)", borderRadius: 8, padding: 10 }}><Destacar texto={s.texto} termo={t} /></pre>
            </Recolhivel>
          );
        })}
      </div>
    </Bloco>
  );
}
