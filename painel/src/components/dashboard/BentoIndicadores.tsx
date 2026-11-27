import { useContagem } from "@/components/graficos/comum";
// Indicadores do Painel Inicial num bento (mesmo visual do MagicBento, tema claro), em grade CSS leve: sem ouvir o
// mouse na janela inteira e sem laço de quadros. Realce verde só no :hover (CSS); entrada em cascata uma vez só.
// Os números sobem com um contador leve ao abrir. Mesmos dados que os KPIs e mini-cartões tinham antes.
import { useMemo, type CSSProperties, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowDown, ArrowUp, Box, ChevronRight, FileSignature, Mail, MessageSquare, Package, Reply, Users, type LucideIcon } from "lucide-react";
/** Cartão do bento (o mesmo formato que o MagicBento recebia). */
interface MagicBentoItem { id: string; title?: string; content: ReactNode; onClick?: () => void; colSpan?: number }
import "./BentoIndicadores.css";

export interface DadosBento {
  dias: number;
  serie: { date: string; conv: number; msgs: number; tokens: number }[];
  conversasHoje: number; conversasHojeVariacao: number | null;
  mensagens: number; mensagensVariacao: number | null;
  tokens: number; tokensVariacao: number | null; tokensSub: string;
  agentesAtivos: number; agentesTotal: number; nomesAgentes: string[];
  contratos: number;
  followup: { pendentes: number; enviados: number; respondidos: number; taxa: number | null; taxaVariacao: number | null };
  produtos: { ativos: number; total: number };
  podeGerir: boolean;
}

const CORES_AGENTES = ["#22c55e", "#0ea5e9", "#2563eb", "#f59e0b", "#ef4444"];

function Variacao({ v, sufixo = "%" }: { v: number | null | undefined; sufixo?: string }) {
  if (v == null) return null;
  return (
    <span className={`lc-bento__delta ${v >= 0 ? "is-up" : "is-down"}`}>
      {v >= 0 ? <ArrowUp aria-hidden /> : <ArrowDown aria-hidden />}{Math.abs(v)}{sufixo}
    </span>
  );
}

// O ícone ganha um jeito próprio de se mexer ao passar o mouse (ver BentoIndicadores.css: is-pulo, is-giro, is-balanco).
type Mexida = "pulo" | "giro" | "balanco";

function Topo({ icone: Icone, rotulo, cor, fundo, acao, mexida = "pulo", vivo }: {
  icone: LucideIcon; rotulo: string; cor: string; fundo: string; acao?: ReactNode; mexida?: Mexida; vivo?: boolean;
}) {
  return (
    <div className="lc-bento__topo">
      <span className={`lc-bento__icone is-${mexida}`} style={{ background: fundo, color: cor }}><Icone aria-hidden /></span>
      <span className="lc-bento__rotulo">{rotulo}</span>
      {vivo && <span className="lc-bento__vivo" title="Atualiza sozinho"><i aria-hidden />ao vivo</span>}
      {acao}
    </div>
  );
}

function Numero({ valor }: { valor: number; chave?: string }) {
  // Contador leve (só este número re-renderiza, ~1 s). O Counter do React Bits animava dígito por dígito com mola.
  const n = useContagem(Math.round(valor) || 0, 900);
  return <>{n.toLocaleString("pt-BR")}</>;
}

function Faixa({ pct, cor }: { pct: number; cor: string }) {
  return (
    <div className="lc-bento__faixa"><span style={{ width: `${Math.max(4, Math.min(100, pct))}%`, background: cor }} /></div>
  );
}

function Linha({ serie, chave, cor }: { serie: DadosBento["serie"]; chave: "conv" | "msgs" | "tokens"; cor: string; id?: string }) {
  // Minicurva em SVG puro, desenhada uma vez por CSS. Antes era um AreaChart do recharts animado (pesado no Painel Inicial).
  const vals = serie.map((x) => Number(x[chave]) || 0);
  if (vals.length < 2) return <div className="lc-bento__linha" aria-hidden />;
  const max = Math.max(1, ...vals);
  const W = 100, H = 40;
  const pts = vals.map((v, k) => [(k / (vals.length - 1)) * W, H - 2 - (v / max) * (H - 8)] as const);
  const linha = pts.map(([x, y], k) => `${k ? "L" : "M"}${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
  return (
    <div className="lc-bento__linha" aria-hidden>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" width="100%" height="100%">
        <path d={`${linha} L${W},${H} L0,${H} Z`} fill={cor} opacity={0.12} />
        <path d={linha} fill="none" stroke={cor} strokeWidth={1.75} vectorEffect="non-scaling-stroke" pathLength={1} className="lc-bento__traco" />
      </svg>
    </div>
  );
}

const corEstado = (p: number) => (p >= 66 ? "#16a34a" : p >= 40 ? "#f59e0b" : "#ef4444");

export function BentoIndicadores({ d, chave }: { d: DadosBento; chave: string }) {
  const navegar = useNavigate();
  const items = useMemo<MagicBentoItem[]>(() => {
    const pctAgentes = d.agentesTotal > 0 ? (d.agentesAtivos / d.agentesTotal) * 100 : 0;
    const pctProdutos = d.produtos.total > 0 ? (d.produtos.ativos / d.produtos.total) * 100 : d.produtos.ativos > 0 ? 100 : 0;
    const pend = d.followup.pendentes;
    const lista: MagicBentoItem[] = [
      {
        id: "mensagens", colSpan: 2,
        content: (
          <div className="lc-bento__corpo">
            <Topo icone={Mail} rotulo={`Mensagens (${d.dias}d)`} cor="#2563eb" fundo="#eaf1ff" mexida="balanco" />
            <div className="lc-bento__valor"><Numero valor={d.mensagens} chave={`${chave}-msgs`} /><Variacao v={d.mensagensVariacao} /></div>
            <span className="lc-bento__sub">trocadas</span>
            <Linha serie={d.serie} chave="msgs" cor="#3b82f6" id="lcb-msgs" />
          </div>
        ),
      },
      {
        id: "tokens",
        content: (
          <div className="lc-bento__corpo">
            <Topo icone={Box} rotulo={`Tokens (${d.dias}d)`} cor="#0891b2" fundo="#e0f2fe" mexida="giro" />
            <div className="lc-bento__valor"><Numero valor={d.tokens} chave={`${chave}-tokens`} /><Variacao v={d.tokensVariacao} /></div>
            <span className="lc-bento__sub">{d.tokensSub}</span>
            <Linha serie={d.serie} chave="tokens" cor="#0ea5e9" id="lcb-tokens" />
          </div>
        ),
      },
      {
        id: "agentes",
        content: (
          <div className="lc-bento__corpo">
            <Topo icone={Users} rotulo="Agentes ativos" cor="#d97706" fundo="#fff4df" />
            <div className="lc-bento__valor">
              <Numero valor={d.agentesAtivos} chave={`${chave}-agentes`} />
              {d.nomesAgentes.length > 0 && (
                <span className="lc-bento__avatares">
                  {d.nomesAgentes.slice(0, 3).map((nome, i) => (
                    <span key={i} title={nome} style={{ background: CORES_AGENTES[i % CORES_AGENTES.length] }}>{nome.charAt(0).toUpperCase()}</span>
                  ))}
                  {d.agentesTotal > 3 && <span className="is-mais">+{d.agentesTotal - 3}</span>}
                </span>
              )}
            </div>
            <span className="lc-bento__sub">de {d.agentesTotal} {d.agentesTotal === 1 ? "agente" : "agentes"}</span>
            <Faixa pct={pctAgentes} cor={corEstado(pctAgentes)} />
          </div>
        ),
      },
      {
        id: "followup", colSpan: 2,
        content: (
          <div className="lc-bento__corpo">
            <Topo icone={Reply} rotulo="Follow-up" cor="#00bc33" fundo="#e8f9ee" mexida="giro" />
            <div className="lc-bento__valor"><Numero valor={pend} chave={`${chave}-followup`} /><span className="lc-bento__unidade">pendentes</span></div>
            <span className="lc-bento__sub">
              {d.followup.enviados ? <>Resposta {d.followup.taxa ?? 0}% · {d.followup.respondidos} de {d.followup.enviados}</> : "sem follow-up enviado"}
              {" "}<Variacao v={d.followup.taxaVariacao} sufixo=" p.p." />
            </span>
            <Faixa pct={Math.min(100, (pend / 40) * 100)} cor={pend <= 10 ? "#16a34a" : pend <= 25 ? "#f59e0b" : "#ef4444"} />
          </div>
        ),
      },
      {
        id: "produtos", colSpan: 2,
        onClick: d.podeGerir ? () => navegar("/meus-produtos") : undefined,
        title: "Produtos ativos",
        content: (
          <div className="lc-bento__corpo">
            <Topo icone={Package} rotulo="Produtos ativos" cor="#00bc33" fundo="#e8f9ee"
              acao={d.podeGerir ? <span className="lc-bento__ver">Ver <ChevronRight aria-hidden /></span> : undefined} />
            <div className="lc-bento__valor"><Numero valor={d.produtos.ativos} chave={`${chave}-produtos`} /></div>
            <span className="lc-bento__sub">de {d.produtos.total} produtos</span>
            <Faixa pct={pctProdutos} cor="#16a34a" />
          </div>
        ),
      },
    ];
    return lista;
  }, [d, chave, navegar]);

  return (
    <div className="lc-bento lc-bento-leve" role="list">
      {items.map((it, n) => {
        const estilo = { "--n": n, gridColumn: it.colSpan ? `span ${it.colSpan}` : undefined } as CSSProperties;
        return it.onClick ? (
          <button key={it.id} type="button" role="listitem" className="magic-bento__card lc-bento-leve__card is-clicavel" style={estilo}
            onClick={it.onClick} aria-label={it.title}>{it.content}</button>
        ) : (
          <div key={it.id} role="listitem" className="magic-bento__card lc-bento-leve__card" style={estilo}>{it.content}</div>
        );
      })}
    </div>
  );
}
