import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { motion, useReducedMotion } from "framer-motion";
import { ArrowRight, X } from "lucide-react";

export type TomAlerta = "critico" | "atencao" | "info";

export interface AcaoAlerta {
  rotulo: string;
  /** Rota do painel para resolver. */
  para?: string;
  /** Ou uma ação na própria tela (ex.: tentar de novo). */
  aoClicar?: () => void;
  icone?: any;
}

export interface AlertaOperacionalProps {
  tom: TomAlerta;
  icone: any;
  titulo: string;
  texto: ReactNode;
  /** Passos curtos de como resolver (opcional). */
  passos?: string[];
  acao?: AcaoAlerta | null;
  /** Linha pequena à direita/abaixo: "Último webhook: 10:32", "Fale com a LawChat"... */
  nota?: ReactNode;
  /** Barra de progresso (0–100+), usada no alerta de consumo. */
  progresso?: number | null;
  /** Mostra um X para esconder o alerta (não usar no tom crítico). */
  aoDispensar?: () => void;
  delay?: number;
}

/* Mesma paleta do .alerta e do toast (estilo.css): --bad, --warn, --acento e os tons suaves.
   Os textos usam versões mais escuras do tom para passar de 4,5:1 sobre o fundo claro. */
const TONS: Record<TomAlerta, { cor: string; suave: string; titulo: string; seloTxt: string; rotulo: string; botao: string }> = {
  critico: {
    cor: "var(--bad)", suave: "var(--bad-soft)", titulo: "#7f1d1d", seloTxt: "#b91c1c", rotulo: "Ação urgente",
    botao: "linear-gradient(135deg, #dc2626 0%, #b91c1c 100%)",
  },
  atencao: {
    cor: "var(--warn)", suave: "var(--warn-soft)", titulo: "#78350f", seloTxt: "#92400e", rotulo: "Precisa de atenção",
    botao: "linear-gradient(135deg, #b45309 0%, #92400e 100%)",
  },
  info: {
    cor: "var(--acento)", suave: "var(--acento-suave)", titulo: "#14532d", seloTxt: "#0b7a2a", rotulo: "Próximo passo",
    botao: "linear-gradient(135deg, #00d23a 0%, #00bc33 45%, #009926 100%)",
  },
};

const FOCO = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-[#00bc33]";

/** Alerta operacional do topo do Início: faixa colorida, ícone, o que está acontecendo, como resolver e o botão para resolver. */
export function AlertaOperacional({ tom, icone: Icone, titulo, texto, passos, acao, nota, progresso, aoDispensar, delay = 0 }: AlertaOperacionalProps) {
  const t = TONS[tom];
  const reduzir = useReducedMotion();
  const barra = progresso == null ? null : Math.max(3, Math.min(100, progresso));
  const IconeAcao = acao?.icone ?? ArrowRight;
  const classeBotao = `lc-alerta-btn ${FOCO} inline-flex w-full sm:w-auto items-center justify-center gap-1.5 h-10 px-4 rounded-xl text-white font-bold text-[13px] whitespace-nowrap`;

  return (
    <motion.div
      role={tom === "critico" ? "alert" : "status"}
      initial={reduzir ? false : { opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay, duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
      className={`lc-alerta relative overflow-hidden rounded-[18px] border pl-5 py-4 ${aoDispensar ? "pr-11 sm:pr-12" : "pr-4 sm:pr-5"}`}
      style={{
        background: `linear-gradient(100deg, color-mix(in srgb, ${t.suave} 75%, var(--surface)) 0%, var(--surface) 62%)`,
        borderColor: `color-mix(in srgb, ${t.cor} 24%, var(--surface))`,
      }}
    >
      <span className="absolute left-0 top-0 bottom-0 w-[5px]" style={{ background: t.cor }} aria-hidden />
      {aoDispensar && (
        <button type="button" onClick={aoDispensar} aria-label={`Dispensar aviso: ${titulo}`} title="Dispensar"
          className={`absolute top-2.5 right-2.5 size-8 rounded-lg grid place-items-center text-[#667085] hover:text-[#101828] hover:bg-black/[0.04] transition-colors ${FOCO}`}>
          <X className="size-4" />
        </button>
      )}
      <div className="flex flex-col sm:flex-row sm:items-center gap-3.5">
        <div className="flex items-start gap-3 flex-1 min-w-0">
          <div className={`relative size-10 rounded-xl grid place-items-center shrink-0 ${tom === "critico" ? "lc-alerta-pulso" : ""}`} style={{ background: t.suave, color: t.cor, ["--pulso" as any]: t.cor }} aria-hidden>
            <Icone className="size-5" strokeWidth={2.2} />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[10px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded-md" style={{ background: t.suave, color: t.seloTxt }}>{t.rotulo}</span>
              <h3 className="text-[15px] font-bold tracking-tight leading-snug" style={{ color: t.titulo }}>{titulo}</h3>
            </div>
            <p className="text-[13px] text-[#475467] mt-1 leading-relaxed">{texto}</p>
            {passos && passos.length > 0 && (
              <ol className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-[#475467] list-none p-0 m-0">
                {passos.map((p, i) => (
                  <li key={p} className="inline-flex items-center gap-1.5">
                    <span className="size-[18px] rounded-full grid place-items-center text-[10px] font-bold shrink-0" style={{ background: t.suave, color: t.seloTxt }} aria-hidden>{i + 1}</span>
                    {p}
                  </li>
                ))}
              </ol>
            )}
            {barra != null && (
              <div role="progressbar" aria-label="Consumo do limite do mês" aria-valuemin={0} aria-valuemax={100}
                aria-valuenow={Math.round(Math.min(100, progresso ?? 0))} aria-valuetext={`${Math.round(progresso ?? 0)}% do limite`}
                className="mt-2.5 h-1.5 max-w-[360px] rounded-full bg-[#eef1f5] overflow-hidden">
                <motion.div className="h-full rounded-full" style={{ background: t.cor }}
                  initial={reduzir ? false : { width: 0 }} animate={{ width: `${barra}%` }}
                  transition={{ delay: delay + 0.2, duration: 0.8, ease: [0.22, 1, 0.36, 1] }} />
              </div>
            )}
          </div>
        </div>
        {(acao || nota) && (
          <div className="flex flex-col items-stretch sm:items-end gap-2 shrink-0">
            {acao && (acao.para ? (
              <Link to={acao.para} className={classeBotao} style={{ background: t.botao }}>
                {acao.rotulo} <IconeAcao className="size-4" aria-hidden />
              </Link>
            ) : (
              <button type="button" onClick={acao.aoClicar} className={classeBotao} style={{ background: t.botao }}>
                {acao.rotulo} <IconeAcao className="size-4" aria-hidden />
              </button>
            ))}
            {nota && <span className="text-[12px] leading-snug text-[#667085] text-center sm:text-right sm:whitespace-nowrap">{nota}</span>}
          </div>
        )}
      </div>
    </motion.div>
  );
}
