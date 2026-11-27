// Cartão-herói do Painel Inicial: data, "IA atendendo · N agentes no ar", a frase do dia e 4 números em mono.
// Só CSS (entrada uma vez) e contagem que para sozinha (useContagem). Sem efeitos de cursor.
import type { ReactNode } from "react";
import { useContagem } from "@/components/graficos/comum";
import "./inicioNovo.css";

export interface DadosHero {
  nome: string;
  agentesNoAr: number;
  /** Conversas de hoje (pessoas que a IA atendeu). */
  pessoasHoje: number;
  /** Contratos assinados hoje; null quando a pessoa não vê esse número. */
  contratosHoje: number | null;
  qualificadosHoje: number | null;
  respostaMediaS: number | null;
  acao?: ReactNode;
}

export function saudacaoDaHora(hora = new Date().getHours()): string {
  return hora < 12 ? "Bom dia" : hora < 18 ? "Boa tarde" : "Boa noite";
}

/** "quinta, 26 de novembro" (sem o "-feira"). */
export function dataDeHoje(d = new Date()): string {
  return d.toLocaleDateString("pt-BR", { weekday: "long", day: "numeric", month: "long" }).replace("-feira", "");
}

export function tempoCurto(s: number | null): string {
  if (s == null || !Number.isFinite(s)) return "—";
  const t = Math.round(s);
  if (t < 60) return `${t}s`;
  if (t < 3600) return `${Math.floor(t / 60)}m ${String(t % 60).padStart(2, "0")}s`;
  return `${Math.floor(t / 3600)}h ${String(Math.floor((t % 3600) / 60)).padStart(2, "0")}m`;
}

const fmt = (n: number) => Math.round(n).toLocaleString("pt-BR");

function Conta({ v }: { v: number | null }) {
  const n = useContagem(v ?? 0, 900);
  return <>{v == null ? "—" : fmt(n)}</>;
}

/** A frase do topo é sempre uma pequena comemoração do que a IA já fez hoje: nunca "ainda não". Mostra a melhor
 *  conquista primeiro (contrato > lead qualificado > pessoas atendidas); sem conversa ainda, fala que ela está pronta. */
function Frase({ pessoas, contratos, qualificados, noAr }: { pessoas: number; contratos: number | null; qualificados: number | null; noAr: boolean }) {
  const hl = (n: number, um: string, varios: string) => <span className="lc-hero__hl">{fmt(n)} {n === 1 ? um : varios}</span>;
  const c = contratos ?? 0;
  const q = qualificados ?? 0;
  if (c > 0) {
    return <>Hoje a IA já fechou {hl(c, "contrato", "contratos")}{pessoas > 0 && <> e atendeu {hl(pessoas, "pessoa", "pessoas")}</>}. Que dia! 🎉</>;
  }
  if (q > 0) {
    return <>Hoje a IA já qualificou {hl(q, "lead", "leads")}{pessoas > 0 && <> e atendeu {hl(pessoas, "pessoa", "pessoas")}</>}. Contrato a caminho! 🚀</>;
  }
  if (pessoas > 0) {
    return <>Hoje a IA já atendeu {hl(pessoas, "pessoa", "pessoas")}. {pessoas === 1 ? "Cada conversa é um cliente a caminho." : "Seu escritório não parou um minuto."} 👏</>;
  }
  return noAr
    ? <>A IA está no ar e pronta para atender cada lead que chegar hoje. ✨</>
    : <>Sua IA está pronta para entrar no ar e começar a atender. ✨</>;
}

export function SaudacaoHero({ d }: { d: DadosHero }) {
  const noAr = d.agentesNoAr > 0;
  const stats: { rotulo: string; valor: ReactNode }[] = [
    { rotulo: "conversas hoje", valor: <Conta v={d.pessoasHoje} /> },
    { rotulo: "leads qualificados", valor: <Conta v={d.qualificadosHoje} /> },
    { rotulo: "contratos assinados", valor: <Conta v={d.contratosHoje} /> },
    { rotulo: "resposta média", valor: tempoCurto(d.respostaMediaS) },
  ];
  return (
    <section className="lc-hero" aria-label="Resumo de hoje">
      <div className="lc-hero__brilho" aria-hidden />
      <div className="lc-hero__linha">
        <span className="lc-hero__data">{dataDeHoje()}</span>
        <span className={`lc-hero__pilula${noAr ? "" : " is-off"}`}>
          <i aria-hidden />
          {noAr ? `IA atendendo · ${d.agentesNoAr} ${d.agentesNoAr === 1 ? "agente" : "agentes"} no ar` : "IA parada · nenhum agente no ar"}
        </span>
        {d.acao && <span className="lc-hero__acao">{d.acao}</span>}
      </div>
      <h1 className="lc-hero__titulo">{saudacaoDaHora()}, {d.nome}. <Frase pessoas={d.pessoasHoje} contratos={d.contratosHoje} qualificados={d.qualificadosHoje} noAr={noAr} /></h1>
      <dl className="lc-hero__stats">
        {stats.map((s) => (
          <div key={s.rotulo}><dt>{s.rotulo}</dt><dd>{s.valor}</dd></div>
        ))}
      </dl>
    </section>
  );
}
