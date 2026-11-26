/*
 * Peças comuns das telas de Relatórios (Dashboard e Rastreamento de campanhas): filtros na URL, barra de filtros,
 * cartões de indicador, funil, mapa de calor por horário, exportar CSV e imprimir/PDF.
 * Os números vêm prontos do servidor (/api/relatorios/*); aqui só formata e desenha.
 */
import { useMemo, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { ArrowDown, ArrowUp, Download, Printer, RefreshCw, X } from "lucide-react";
import { useCarregar } from "../componentes/ui";
import { useSessao } from "../sessao";
import "../estilo-relatorios.css";

// --------------------------------------------------------------------------- formatos
export const fmtNum = (n: number | null | undefined) => (n == null ? "–" : Math.round(n).toLocaleString("pt-BR"));
export const fmtPct = (n: number | null | undefined, casas = 1) =>
  n == null ? "–" : `${n.toLocaleString("pt-BR", { maximumFractionDigits: casas, minimumFractionDigits: 0 })}%`;
export const fmtBRL = (n: number | null | undefined) =>
  n == null ? "–" : n.toLocaleString("pt-BR", { style: "currency", currency: "BRL", minimumFractionDigits: 2 });
export const fmtDia = (d: string) => `${d.slice(8, 10)}/${d.slice(5, 7)}`;
export const fmtData = (d: string | null | undefined) => (d ? new Date(d).toLocaleDateString("pt-BR") : "–");
export function fmtHoras(h: number | null | undefined): string {
  if (h == null) return "–";
  if (h <= 0) return "0";
  if (h < 1) return `${Math.max(1, Math.round(h * 60))} min`;
  if (h < 48) return `${h.toLocaleString("pt-BR", { maximumFractionDigits: 1 })} h`;
  const dias = Math.floor(h / 24);
  const resto = Math.round(h - dias * 24);
  return resto ? `${dias}d ${resto}h` : `${dias} dias`;
}
export function fmtSegundos(s: number | null | undefined): string {
  if (s == null) return "–";
  if (s < 60) return `${Math.round(s)} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
  return fmtHoras(s / 3600);
}

export const CORES = ["#00BC33", "#0EA5E9", "#6366F1", "#F59E0B", "#EF4444", "#14B8A6", "#A855F7", "#64748B"];
export const COR_FASE: Record<string, string> = {
  sdr: "#0EA5E9", closer: "#6366F1", contratos: "#F59E0B", assinatura: "#A855F7", assinado: "#00BC33",
  desqualificado: "#EF4444", analise: "#14B8A6", nao_assinou: "#F97316", outra: "#94A3B8", sem_etapa: "#CBD5E1",
};

// --------------------------------------------------------------------------- filtros (na URL)
export const PERIODOS: { valor: string; rotulo: string }[] = [
  { valor: "hoje", rotulo: "Hoje" }, { valor: "ontem", rotulo: "Ontem" }, { valor: "7", rotulo: "7 dias" },
  { valor: "30", rotulo: "30 dias" }, { valor: "90", rotulo: "90 dias" }, { valor: "mes", rotulo: "Este mês" },
  { valor: "mes_passado", rotulo: "Mês passado" }, { valor: "ano", rotulo: "12 meses" },
];

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

export function intervaloDoPeriodo(periodo: string): { de: string; ate: string } {
  const hoje = new Date();
  const menos = (dias: number) => { const d = new Date(hoje); d.setDate(d.getDate() - dias); return d; };
  switch (periodo) {
    case "hoje": return { de: iso(hoje), ate: iso(hoje) };
    case "ontem": return { de: iso(menos(1)), ate: iso(menos(1)) };
    case "7": return { de: iso(menos(6)), ate: iso(hoje) };
    case "90": return { de: iso(menos(89)), ate: iso(hoje) };
    case "ano": return { de: iso(menos(364)), ate: iso(hoje) };
    case "mes": return { de: iso(new Date(hoje.getFullYear(), hoje.getMonth(), 1)), ate: iso(hoje) };
    case "mes_passado": return {
      de: iso(new Date(hoje.getFullYear(), hoje.getMonth() - 1, 1)), ate: iso(new Date(hoje.getFullYear(), hoje.getMonth(), 0)) };
    default: return { de: iso(menos(29)), ate: iso(hoje) };
  }
}

export interface Filtros { periodo: string; de: string; ate: string; agente: string; campanha: string; fonte: string }

export function useFiltros() {
  const [params, setParams] = useSearchParams();
  const filtros: Filtros = useMemo(() => {
    const periodo = params.get("periodo") || (params.get("de") ? "personalizado" : "30");
    const intervalo = periodo === "personalizado"
      ? { de: params.get("de") || intervaloDoPeriodo("30").de, ate: params.get("ate") || iso(new Date()) }
      : intervaloDoPeriodo(periodo);
    return { periodo, ...intervalo, agente: params.get("agente") || "", campanha: params.get("campanha") || "",
             fonte: params.get("fonte") || "" };
  }, [params]);
  const mudar = (novo: Partial<Filtros>) => {
    const proximo = new URLSearchParams(params);
    for (const [chave, valor] of Object.entries(novo)) {
      if (valor) proximo.set(chave, valor); else proximo.delete(chave);
    }
    if (novo.periodo && novo.periodo !== "personalizado") { proximo.delete("de"); proximo.delete("ate"); }
    if (novo.periodo === "30") proximo.delete("periodo");
    setParams(proximo, { replace: true });
  };
  const consulta = new URLSearchParams({ de: filtros.de, ate: filtros.ate,
    ...(filtros.agente ? { agente: filtros.agente } : {}), ...(filtros.campanha ? { campanha: filtros.campanha } : {}),
    ...(filtros.fonte ? { fonte: filtros.fonte } : {}) }).toString();
  return { filtros, mudar, consulta };
}

interface OpcoesFiltro {
  agentes: { id: string; nome: string; situacao: string }[];
  campanhas: { campanha: string; leads: number }[];
  plataformas: { valor: string; rotulo: string }[];
}

export function BarraFiltros({ filtros, mudar }: { filtros: Filtros; mudar: (f: Partial<Filtros>) => void }) {
  const { escritorio } = useSessao();
  const opcoes = useCarregar<OpcoesFiltro>(escritorio ? "/relatorios/filtros" : null, [escritorio]);
  const algum = filtros.agente || filtros.campanha || filtros.fonte;
  return (
    <div className="rl-filtros rl-nao-imprimir" role="group" aria-label="Filtros do relatório">
      <div className="rl-chips" role="radiogroup" aria-label="Período">
        {PERIODOS.map((p) => (
          <button key={p.valor} type="button" role="radio" aria-checked={filtros.periodo === p.valor}
            className={`rl-chip${filtros.periodo === p.valor ? " on" : ""}`} onClick={() => mudar({ periodo: p.valor })}>{p.rotulo}</button>
        ))}
      </div>
      <div className="rl-filtros-linha">
        <label className="rl-campo"><span>De</span>
          <input type="date" value={filtros.de} max={filtros.ate}
            onChange={(e) => e.target.value && mudar({ periodo: "personalizado", de: e.target.value, ate: filtros.ate })} />
        </label>
        <label className="rl-campo"><span>Até</span>
          <input type="date" value={filtros.ate} min={filtros.de}
            onChange={(e) => e.target.value && mudar({ periodo: "personalizado", de: filtros.de, ate: e.target.value })} />
        </label>
        <label className="rl-campo"><span>Agente</span>
          <select value={filtros.agente} onChange={(e) => mudar({ agente: e.target.value })}>
            <option value="">Todos os agentes</option>
            {opcoes.dados?.agentes.map((a) => <option key={a.id} value={a.id}>{a.nome}{a.situacao !== "ativo" ? " (pausado)" : ""}</option>)}
          </select>
        </label>
        <label className="rl-campo rl-campo-largo"><span>Campanha</span>
          <select value={filtros.campanha} onChange={(e) => mudar({ campanha: e.target.value })}>
            <option value="">Todas as campanhas</option>
            {filtros.campanha && !opcoes.dados?.campanhas.some((c) => c.campanha === filtros.campanha) && (
              <option value={filtros.campanha}>{filtros.campanha}</option>
            )}
            {opcoes.dados?.campanhas.map((c) => <option key={c.campanha} value={c.campanha}>{c.campanha} ({fmtNum(c.leads)})</option>)}
          </select>
        </label>
        <label className="rl-campo"><span>Origem</span>
          <select value={filtros.fonte} onChange={(e) => mudar({ fonte: e.target.value })}>
            <option value="">Todas as origens</option>
            {opcoes.dados?.plataformas.map((p) => <option key={p.valor} value={p.valor}>{p.rotulo}</option>)}
          </select>
        </label>
        {algum && (
          <button type="button" className="rl-limpar" onClick={() => mudar({ agente: "", campanha: "", fonte: "" })}>
            <X size={14} aria-hidden />Limpar filtros
          </button>
        )}
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- cabeçalho e ações
export function Topo({ titulo, texto, acoes, carregando, aoAtualizar }: {
  titulo: string; texto: ReactNode; acoes?: ReactNode; carregando?: boolean; aoAtualizar?: () => void;
}) {
  return (
    <div className="rl-topo">
      <div>
        <div className="rl-eyebrow">Relatórios</div>
        <h1>{titulo}</h1>
        <p>{texto}</p>
      </div>
      <div className="rl-acoes rl-nao-imprimir">
        {aoAtualizar && (
          <button type="button" className="rl-btn" onClick={aoAtualizar} disabled={carregando} title="Buscar os números de novo">
            <RefreshCw size={15} className={carregando ? "rl-girando" : ""} aria-hidden />Atualizar
          </button>
        )}
        {acoes}
        <button type="button" className="rl-btn" onClick={() => window.print()} title="Imprimir ou salvar em PDF">
          <Printer size={15} aria-hidden />PDF / imprimir
        </button>
      </div>
    </div>
  );
}

export function BotaoCsv({ rotulo = "Baixar CSV", aoClicar }: { rotulo?: string; aoClicar: () => void }) {
  return <button type="button" className="rl-btn" onClick={aoClicar}><Download size={15} aria-hidden />{rotulo}</button>;
}

/** CSV com ";" e BOM (abre certo no Excel em português). */
export function baixarCsv(nome: string, cabecalho: string[], linhas: (string | number | null | undefined)[][]) {
  const celula = (v: string | number | null | undefined) => {
    if (v == null) return "";
    const texto = typeof v === "number" ? String(v).replace(".", ",") : String(v);
    return /[";\n]/.test(texto) ? `"${texto.replace(/"/g, '""')}"` : texto;
  };
  const conteudo = [cabecalho, ...linhas].map((l) => l.map(celula).join(";")).join("\r\n");
  const blob = new Blob(["﻿" + conteudo], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = nome;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// --------------------------------------------------------------------------- cartões
export function Kpi({ rotulo, valor, detalhe, variacao, icone, tom = "verde", inverter }: {
  rotulo: string; valor: ReactNode; detalhe?: ReactNode; variacao?: number | null; icone?: ReactNode;
  tom?: "verde" | "azul" | "roxo" | "ambar" | "vermelho" | "cinza"; inverter?: boolean;
}) {
  const subiu = variacao != null && variacao > 0;
  const bom = variacao == null || variacao === 0 ? null : inverter ? !subiu : subiu;
  return (
    <div className={`rl-kpi rl-tom-${tom}`}>
      <div className="rl-kpi-cab">
        {icone && <span className="rl-kpi-ico" aria-hidden>{icone}</span>}
        <span className="rl-kpi-rot">{rotulo}</span>
      </div>
      <div className="rl-kpi-valor num">{valor}</div>
      <div className="rl-kpi-pe">
        {variacao != null && (
          <span className={`rl-var ${bom === null ? "" : bom ? "bom" : "ruim"}`} title="Em relação ao período anterior do mesmo tamanho">
            {subiu ? <ArrowUp size={12} aria-hidden /> : variacao < 0 ? <ArrowDown size={12} aria-hidden /> : null}
            {variacao > 0 ? "+" : ""}{variacao}%
          </span>
        )}
        {detalhe && <span className="rl-kpi-det">{detalhe}</span>}
      </div>
    </div>
  );
}

export function Cartao({ titulo, subtitulo, acoes, children, classe = "" }: {
  titulo: ReactNode; subtitulo?: ReactNode; acoes?: ReactNode; children: ReactNode; classe?: string;
}) {
  return (
    <section className={`rl-cartao ${classe}`}>
      <div className="rl-cartao-cab">
        <div>
          <h3>{titulo}</h3>
          {subtitulo && <p>{subtitulo}</p>}
        </div>
        {acoes && <div className="rl-cartao-acoes rl-nao-imprimir">{acoes}</div>}
      </div>
      {children}
    </section>
  );
}

export function Abas<T extends string>({ valor, opcoes, aoMudar }: { valor: T; opcoes: { valor: T; rotulo: string }[]; aoMudar: (v: T) => void }) {
  return (
    <div className="rl-abas" role="tablist">
      {opcoes.map((o) => (
        <button key={o.valor} type="button" role="tab" aria-selected={valor === o.valor} className={valor === o.valor ? "on" : ""}
          onClick={() => aoMudar(o.valor)}>{o.rotulo}</button>
      ))}
    </div>
  );
}

export function SemDados({ children }: { children: ReactNode }) {
  return <div className="rl-sem-dados">{children}</div>;
}

// --------------------------------------------------------------------------- funil
export interface EtapaFunil { fase: string; nome: string; chegaram: number; agora?: number; pct_total?: number | null; conversao?: number | null }

export function Funil({ etapas, total }: { etapas: EtapaFunil[]; total: number }) {
  if (!total) return <SemDados>Nenhum lead entrou no período escolhido.</SemDados>;
  const ultimo = etapas[etapas.length - 1];
  return (
    <div className="rl-funil">
      {etapas.map((e, i) => {
        const largura = 42 + (58 * (etapas.length - 1 - i)) / Math.max(1, etapas.length - 1);
        const cheio = total ? Math.max(2, (e.chegaram / total) * 100) : 0;
        return (
          <div key={e.fase} className="rl-funil-linha">
            <div className="rl-funil-rot">
              <span className="rl-ponto" style={{ background: COR_FASE[e.fase] ?? CORES[i] }} aria-hidden />
              <b>{e.nome}</b>
              {e.agora != null && <small title="Leads parados nesta etapa agora">{fmtNum(e.agora)} agora</small>}
            </div>
            <div className="rl-funil-trilho" style={{ width: `${largura}%` }}>
              <div className="rl-funil-barra" style={{ width: `${cheio}%`, background: COR_FASE[e.fase] ?? CORES[i] }} />
              <span className="rl-funil-num num">{fmtNum(e.chegaram)} <em>{fmtPct(e.pct_total, 0)}</em></span>
            </div>
            <div className="rl-funil-conv" title="Dos que chegaram à etapa anterior, quantos chegaram a esta">
              {e.conversao != null ? <span className="num">{fmtPct(e.conversao, 0)}</span> : <span className="muted">entrada</span>}
            </div>
          </div>
        );
      })}
      <div className="rl-funil-pe">Conversão geral: <b className="num">{fmtPct(total ? (ultimo.chegaram / total) * 100 : null)}</b>
        <span className="muted"> · conta até onde cada lead já chegou (inclui quem passou e seguiu adiante)</span></div>
    </div>
  );
}

// --------------------------------------------------------------------------- mapa de calor (dia da semana x hora)
const DIAS_SEMANA = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"];

export function MapaDeCalor({ grade, rotulo }: { grade: number[][]; rotulo: string }) {
  const maximo = Math.max(1, ...grade.flat());
  let pico = { dia: 0, hora: 0, valor: 0 };
  grade.forEach((linha, d) => linha.forEach((v, h) => { if (v > pico.valor) pico = { dia: d, hora: h, valor: v }; }));
  return (
    <div className="rl-calor">
      <div className="rl-calor-grade" role="table" aria-label={`${rotulo} por dia da semana e hora`}>
        <div className="rl-calor-linha" role="row">
          <span className="rl-calor-dia" />
          {Array.from({ length: 24 }, (_, h) => <span key={h} className="rl-calor-hora" role="columnheader">{h % 3 === 0 ? `${h}h` : ""}</span>)}
        </div>
        {grade.map((linha, d) => (
          <div key={d} className="rl-calor-linha" role="row">
            <span className="rl-calor-dia" role="rowheader">{DIAS_SEMANA[d]}</span>
            {linha.map((v, h) => (
              <span key={h} className="rl-calor-cel" role="cell" title={`${DIAS_SEMANA[d]}, ${h}h: ${v}`}
                style={{ background: v ? `rgba(0, 188, 51, ${0.12 + (v / maximo) * 0.88})` : undefined }} />
            ))}
          </div>
        ))}
      </div>
      <p className="rl-nota">{pico.valor ? <>Pico: <b>{DIAS_SEMANA[pico.dia]}, {pico.hora}h</b> ({fmtNum(pico.valor)})</> : "Sem dados no período."}</p>
    </div>
  );
}

/** Barra de proporção simples (tabelas). */
export function Barrinha({ valor, maximo, cor = "#00BC33" }: { valor: number; maximo: number; cor?: string }) {
  return <span className="rl-barrinha"><i style={{ width: `${maximo ? Math.max(3, (valor / maximo) * 100) : 0}%`, background: cor }} /></span>;
}

export function textoPeriodo(de: string, ate: string) {
  return de === ate ? `em ${fmtData(de + "T12:00:00")}` : `de ${fmtData(de + "T12:00:00")} a ${fmtData(ate + "T12:00:00")}`;
}
