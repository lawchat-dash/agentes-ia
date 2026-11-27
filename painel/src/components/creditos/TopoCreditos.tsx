import { useMemo, type CSSProperties } from "react";
import { ArrowRight, Plus } from "lucide-react";
import { reais, type Recarga } from "@/telas/Carteira";
import type { PainelConsumo } from "./tipos";

/** Recarga com o saldo logo depois dela (o servidor manda quando a recarga já entrou). */
type RecargaTopo = Recarga & { saldo_depois_brl?: number | null };
import "./topoCreditos.css";

/*
 * Topo da tela Créditos da IA: faixa escura (saldo + simulador), três números do mês, gasto por dia, por agente e
 * recargas. Recebe o painel dos últimos 30 dias (fixo, não muda com o período das abas). Só CSS/SVG.
 */

const ATALHOS = [50, 150, 500, 1000];
const MIN = 10, MAX = 2000;
const rs = (v: number | null | undefined) => (v == null ? "—" : reais(v, Math.abs(v) > 0 && Math.abs(v) < 0.1 ? 4 : 2));
const inteiro = (v: number) => v.toLocaleString("pt-BR");
const tokensCurto = (v: number) => (v >= 1e6 ? `${(v / 1e6).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} mi`
  : v >= 1000 ? `${(v / 1000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} mil` : inteiro(v));
const nomeMes = (d: Date) => d.toLocaleDateString("pt-BR", { month: "long" });
const pad = (n: number) => String(n).padStart(2, "0");
const FORMA: Record<string, string> = { pix: "Pix", boleto: "Boleto", cartao: "Cartão", manual: "Pela equipe" };
const SITUACAO: Record<string, [string, string]> = {
  paga: ["Pago", "ok"], pendente: ["Aguardando", "aviso"], cancelada: ["Cancelada", "neutra"], expirada: ["Expirada", "neutra"], estornada: ["Estornada", "ruim"],
};

function IconePix() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" aria-hidden>
      <path d="M12 3.5 20.5 12 12 20.5 3.5 12Z" /><path d="m8 12 2.5-2.5h3L16 12l-2.5 2.5h-3Z" />
    </svg>
  );
}

export default function TopoCreditos({ p, recargas, erroRecargas, valor, setValor, aoRecarregar, aoVerRecargas }: {
  p: PainelConsumo; recargas: RecargaTopo[] | null; erroRecargas?: string | null; valor: number; setValor: (v: number) => void;
  aoRecarregar: (v: number) => void; aoVerRecargas: () => void;
}) {
  const c = p.carteira;
  const hoje = new Date();
  const media = p.media_dia_brl && p.media_dia_brl > 0 ? p.media_dia_brl : null;
  const autonomia = media ? Math.max(0, c.disponivel_brl) / media : null;
  const ate = autonomia != null && autonomia < 3650 ? new Date(hoje.getTime() + autonomia * 86400000) : null;
  const negativo = c.disponivel_brl < 0;

  // Simulador: custo real dos últimos 30 dias (ou do histórico, quando o servidor cai para ele).
  const cpl = p.custo_por_lead.valor_brl;
  const cpc = p.totais.custo_por_contrato_brl;
  const leads = cpl ? Math.floor(valor / cpl + 1e-9) : null;
  const contratos = cpc ? Math.floor(valor / cpc + 1e-9) : null;
  const diasMais = media ? Math.round(valor / media) : null;
  const fracao = ((valor - MIN) / (MAX - MIN)) * 100;

  const mes = p.mes;
  const inicioMes = nomeMes(hoje);
  const mesAnterior = nomeMes(new Date(hoje.getFullYear(), hoje.getMonth() - 1, 1));

  return (
    <div className="crt flex flex-col gap-4">
      <header className="crt-cab">
        <h1>Créditos da IA</h1>
        <p>Tudo é cobrado em reais, numa conta só. Cada conversa mostra o custo real dela.</p>
      </header>

      {/* Faixa escura: saldo | simulador */}
      <section className="crt-faixa crt-entra" aria-label="Saldo e simulador de recarga">
        <div className="crt-hero">
          <div className="flex flex-col gap-3.5">
            <span className="crt-rot">Saldo disponível</span>
            <div className={`crt-valor ${negativo ? "neg" : ""}`}>{negativo ? "−" : ""}{reais(Math.abs(c.disponivel_brl))}</div>
            <p className="crt-fraco text-[13.5px]">
              {c.bonus_do_mes_brl > 0 || c.bonus_brl > 0
                ? <>Saldo <span className="crt-mono">{reais(c.saldo_brl)}</span> + bônus do mês <span className="crt-mono">{reais(c.bonus_brl)}</span></>
                : "Saldo de recarga. Não expira."}
            </p>
            {c.bloqueado && (
              <p className="rounded-lg bg-[#ff9b85]/10 px-3 py-2 text-[12.5px] text-[#ffc2b4]">A IA está em pausa porque o saldo acabou. Ela volta sozinha quando a recarga entrar.</p>
            )}
            <div className="mt-1.5 grid gap-2">
              <div className="flex items-baseline justify-between gap-3 text-[12.5px]">
                <span className="crt-fraco">Dura no seu ritmo</span>
                <b className="crt-mono text-right font-medium">
                  {autonomia == null ? "sem consumo recente"
                    : autonomia < 1 ? "menos de 1 dia"
                    : `~${inteiro(Math.floor(autonomia))} ${Math.floor(autonomia) === 1 ? "dia" : "dias"}${ate ? ` · até ${ate.toLocaleDateString("pt-BR")}` : ""}`}
                </b>
              </div>
              <div className={`crt-medidor ${autonomia != null && autonomia < 7 ? "baixo" : ""}`} role="img"
                aria-label={autonomia == null ? "Sem consumo recente para medir" : `O saldo dura cerca de ${Math.floor(autonomia)} dias`}>
                <i style={{ width: `${autonomia == null ? 0 : Math.max(2, Math.min(100, (autonomia / 30) * 100))}%` }} />
              </div>
            </div>
            <div className="mt-auto flex flex-wrap gap-2 pt-2">
              <button type="button" className="crt-btn crt-btn-pri crt-btn-lg" onClick={() => aoRecarregar(valor)}><IconePix />Recarregar com Pix</button>
              <button type="button" className="crt-btn crt-btn-noite crt-btn-lg"
                onClick={() => document.getElementById("crt-recargas")?.scrollIntoView({ behavior: "smooth", block: "start" })}>Histórico</button>
            </div>
          </div>

          <div className="crt-sim">
            <div className="flex items-baseline justify-between gap-3">
              <span className="crt-rot">Simulador de recarga</span>
              <span className="crt-fraco crt-mono text-[12px]">R$ 10 a R$ 2.000</span>
            </div>
            <div className="crt-valor" style={{ fontSize: 34 }} aria-live="polite">{reais(valor)}</div>
            <input type="range" className="crt-range mt-2" min={MIN} max={MAX} step={10} value={valor} aria-label="Valor da recarga"
              aria-valuetext={reais(valor)} onChange={(e) => setValor(Number(e.target.value))}
              style={{ "--p": `${fracao}%` } as CSSProperties} />
            <div className="crt-faixas" role="group" aria-label="Valores rápidos">
              {ATALHOS.map((v) => (
                <button key={v} type="button" aria-pressed={valor === v} onClick={() => setValor(v)}>{reais(v, 0)}</button>
              ))}
            </div>
            <div className="crt-saidas">
              <div><b>{leads != null ? inteiro(leads) : "—"}</b><span>leads atendidos</span></div>
              <div><b>{contratos != null ? `~${inteiro(contratos)}` : "—"}</b><span>contratos estimados</span></div>
              <div><b>{diasMais != null ? `+${inteiro(diasMais)}` : "—"}</b><span>dias a mais</span></div>
            </div>
            <p className="crt-fraco text-[12px] leading-relaxed">{notaSimulador(p)}</p>
          </div>
        </div>
      </section>

      {/* Três números do mês */}
      {mes && (
        <div className="crt-cartao crt-entra">
          <div className="crt-explica">
            <div>
              <span className="crt-rot">Gasto no mês</span>
              <b>{reais(mes.creditos_brl)}</b>
              <span className="crt-nota">desde 1º de {inicioMes}</span>
            </div>
            <div>
              <span className="crt-rot">Tokens usados</span>
              <b>{tokensCurto(mes.tokens)}</b>
              <span className="crt-nota">
                {mes.tokens > 0 ? `≈ ${reais((mes.creditos_brl / mes.tokens) * 1e6)} por milhão. ` : ""}Você não precisa contar tokens: o painel converte para reais.
              </span>
            </div>
            <div>
              <span className="crt-rot">Custo por contrato</span>
              <b>{rs(mes.custo_por_contrato_brl)}</b>
              <span className="crt-nota">{notaContrato(mes, mesAnterior)}</span>
            </div>
          </div>
        </div>
      )}

      <div className="crt-grade">
        <GastoPorDia p={p} />
        <PorAgenteMes p={p} />
      </div>

      <TabelaRecargas recargas={recargas} erro={erroRecargas} aoNova={() => aoRecarregar(valor)} aoVerTodas={aoVerRecargas} />
    </div>
  );
}

function notaSimulador(p: PainelConsumo) {
  const cpl = p.custo_por_lead;
  const cpc = p.totais.custo_por_contrato_brl;
  if (cpl.valor_brl == null) return "Ainda sem consumo para calcular. Assim que seus agentes atenderem os primeiros leads, o simulador usa o seu custo real.";
  if (cpl.fonte === "referencia_modelo")
    return `Estimativa: você ainda não tem histórico, então usamos o custo médio de escritórios com o mesmo modelo de IA (${rs(cpl.valor_brl)} por lead).`;
  const periodo = cpl.fonte === "historico_90d" ? "dos últimos 90 dias" : "dos últimos 30 dias";
  return cpc
    ? `Conta feita com o seu custo real ${periodo}: ${rs(cpl.valor_brl)} por lead e ${rs(cpc)} por contrato.`
    : `Conta feita com o seu custo real ${periodo}: ${rs(cpl.valor_brl)} por lead. Ainda sem contratos assinados nos últimos 30 dias para estimar contratos.`;
}

function notaContrato(mes: NonNullable<PainelConsumo["mes"]>, mesAnterior: string) {
  if (!mes.contratos) return "Nenhum contrato assinado este mês ainda.";
  const base = `${inteiro(mes.contratos)} ${mes.contratos === 1 ? "contrato" : "contratos"}`;
  const ant = mes.anterior.custo_por_contrato_brl;
  if (!ant || mes.custo_por_contrato_brl == null) return base;
  const dif = ((mes.custo_por_contrato_brl - ant) / ant) * 100;
  if (Math.abs(dif) < 0.5) return `${base} · igual a ${mesAnterior}`;
  return `${base} · ${Math.round(Math.abs(dif))}% mais ${dif < 0 ? "barato" : "caro"} que em ${mesAnterior}`;
}

/** Últimos 30 dias, um por dia (dias sem gasto aparecem zerados). Hoje em verde-escuro. */
function GastoPorDia({ p }: { p: PainelConsumo }) {
  const serie = useMemo(() => {
    const mapa = new Map(p.serie.map((s) => [s.quando.slice(0, 10), s.valor_brl]));
    const agora = new Date();
    return Array.from({ length: 30 }, (_, k) => {
      const d = new Date(agora.getFullYear(), agora.getMonth(), agora.getDate() - (29 - k));
      const v = mapa.get(`${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`) ?? 0;
      return { dia: `${pad(d.getDate())}/${pad(d.getMonth() + 1)}`, valor: v };
    });
  }, [p.serie]);
  const max = Math.max(0, ...serie.map((s) => s.valor));
  const media = p.media_dia_brl;
  return (
    <section className="crt-cartao crt-entra p-5">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3>Gasto por dia</h3>
          <p className="crt-sub">Últimos 30 dias{media ? <> · média <span className="crt-mono">{rs(media)}</span>/dia</> : ""}</p>
        </div>
        <div className="crt-legenda"><span><i style={{ background: "var(--sage, #A7D7A4)" }} />Dias</span><span><i style={{ background: "var(--brand-700, #00852A)" }} />Hoje</span></div>
      </div>
      {max === 0 ? <div className="crt-vazio">Sem gasto nos últimos 30 dias.</div> : (
        <>
          <div className="crt-barras" role="list" aria-label="Gasto por dia nos últimos 30 dias">
            {media != null && media <= max && <span className="crt-media" style={{ bottom: `${(media / max) * 100}%` }} aria-hidden />}
            {serie.map((s, i) => (
              <div key={s.dia} role="listitem" tabIndex={0} aria-label={`${s.dia}: ${reais(s.valor)}`}
                className={`${i === serie.length - 1 ? "hoje" : ""} ${s.valor === 0 ? "zero" : ""}`}>
                <i style={{ height: s.valor > 0 ? `${Math.max(3, (s.valor / max) * 100)}%` : "2px", animationDelay: `${i * 12}ms` }} />
                <span className="crt-dica">{i === serie.length - 1 ? "Hoje" : s.dia} · <span className="crt-mono">{rs(s.valor)}</span></span>
              </div>
            ))}
          </div>
          <div className="crt-eixo"><span>{serie[0].dia}</span><span>{serie[14].dia}</span><span>hoje</span></div>
        </>
      )}
    </section>
  );
}

/** Participação de cada agente no gasto do mês (desde o dia 1º). */
function PorAgenteMes({ p }: { p: PainelConsumo }) {
  const lista = p.mes?.por_agente ?? [];
  return (
    <section className="crt-cartao crt-entra p-5">
      <div className="mb-4">
        <h3>Por agente</h3>
        <p className="crt-sub">Participação no gasto do mês</p>
      </div>
      {lista.length === 0 ? <div className="crt-vazio">Nenhum agente gastou neste mês ainda.</div> : (
        <ul className="grid gap-3.5">
          {lista.slice(0, 6).map((a, i) => (
            <li key={a.id_agente ?? `sem-${i}`} className="min-w-0">
              <div className="flex items-baseline justify-between gap-3 text-[13px]">
                <span className="min-w-0 truncate"><b className="font-semibold text-[var(--ink,#0C1811)]">{a.agente}</b>
                  {a.produto && <span className="text-[var(--ink-3,#69786F)]"> · {a.produto}</span>}</span>
                <span className="crt-mono shrink-0 text-[var(--ink,#0C1811)]">{rs(a.valor_brl)}</span>
              </div>
              <div className="crt-barra-ag" title={`${a.participacao_pct.toLocaleString("pt-BR")}% do gasto do mês`}>
                <i style={{ width: `${Math.min(100, Math.max(1, a.participacao_pct))}%`, background: i === 0 ? "var(--brand-700, #00852A)" : "var(--sage, #A7D7A4)", animationDelay: `${i * 60}ms` }} />
              </div>
            </li>
          ))}
          {lista.length > 6 && <li className="text-[12px] text-[var(--ink-3,#69786F)]">+ {lista.length - 6} agentes com gasto menor</li>}
        </ul>
      )}
    </section>
  );
}

function TabelaRecargas({ recargas, erro, aoNova, aoVerTodas }: { recargas: RecargaTopo[] | null; erro?: string | null; aoNova: () => void; aoVerTodas: () => void }) {
  const lista = recargas ?? [];
  const visiveis = lista.slice(0, 6);
  return (
    <section id="crt-recargas" className="crt-cartao crt-entra scroll-mt-4 overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-3 px-5 pb-3.5 pt-5">
        <div>
          <h3>Recargas</h3>
          <p className="crt-sub">Pedidos e pagamentos mais recentes</p>
        </div>
        <button type="button" className="crt-btn crt-btn-sec" onClick={aoNova}><Plus />Nova recarga</button>
      </div>
      {!recargas ? (
        <div className="px-5 pb-5">{erro ? <p className="text-[13px] text-[var(--danger,#BF3520)]">{erro}</p> : <div className="cr-brilho h-24 rounded-xl" />}</div>
      ) : lista.length === 0 ? (
        <div className="px-5 pb-5"><div className="crt-vazio">Nenhum pedido de recarga ainda.</div></div>
      ) : (
        <>
          <div className="crt-tabela">
            <table>
              <thead><tr><th>Data</th><th>Forma</th><th>Situação</th><th className="n">Valor</th><th className="n">Saldo depois</th></tr></thead>
              <tbody>{visiveis.map((r) => {
                const [texto, tom] = SITUACAO[r.situacao] ?? [r.situacao, "neutra"];
                return (
                  <tr key={r.id}>
                    <td className="crt-mono">{new Date(r.paga_em ?? r.criado_em).toLocaleDateString("pt-BR")}</td>
                    <td>{FORMA[r.metodo ?? ""] ?? (r.metodo || "—")}</td>
                    <td><span className={`crt-pilula ${tom}`}>{texto}</span></td>
                    <td className="n">{reais(r.valor_brl)}</td>
                    <td className="n">{r.saldo_depois_brl != null ? reais(r.saldo_depois_brl) : "—"}</td>
                  </tr>
                );
              })}</tbody>
            </table>
          </div>
          {lista.length > visiveis.length || lista.some((r) => r.situacao === "pendente") ? (
            <div className="border-t border-[var(--line,#E2E9E4)] px-5 py-3">
              <button type="button" onClick={aoVerTodas} className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-[var(--brand-700,#00852A)] hover:underline">
                {lista.some((r) => r.situacao === "pendente") ? "Pagar ou cancelar pedidos" : `Ver todas (${lista.length})`}<ArrowRight className="size-3.5" />
              </button>
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}
