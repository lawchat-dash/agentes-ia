import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowRight, CheckCircle2, Circle, MinusCircle, Rocket } from "lucide-react";

/** GET /api/inicio/primeiros-passos (app/gestao/primeiros_passos.py). */
export interface PassoInicial {
  codigo: string; titulo: string; situacao: "feito" | "pendente" | "nao_se_aplica"; detalhe: string;
  para: string | null; acao: string | null;
}
export interface PrimeirosPassosDados { passos: PassoInicial[]; feitos: number; total: number; completo: boolean; proximo: string | null }

/** Cartão "Primeiros passos" do Início: cada passo se marca sozinho; some quando tudo está feito. */
export function PrimeirosPassos({ dados }: { dados: PrimeirosPassosDados }) {
  if (dados.completo) return null;
  const pct = Math.round((dados.feitos / Math.max(1, dados.total)) * 100);
  return (
    <motion.section initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}
      aria-label="Primeiros passos" className="lc-card relative overflow-hidden p-5 mb-3">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2.5">
          <div className="size-9 rounded-xl grid place-items-center bg-[#e8f9ee] text-[#00bc33]"><Rocket className="size-[17px]" /></div>
          <div>
            <h3 className="m-0 font-semibold text-[15px] tracking-tight text-[#101828]">Primeiros passos</h3>
            <p className="m-0 text-[12px] text-[#667085]">Cada passo se marca sozinho. Este cartão some quando tudo estiver pronto.</p>
          </div>
        </div>
        <div className="flex items-center gap-2 min-w-[160px]">
          <div className="h-2 flex-1 rounded-full bg-[#eef1f5] overflow-hidden" role="progressbar" aria-valuenow={dados.feitos} aria-valuemin={0} aria-valuemax={dados.total} aria-label="Passos feitos">
            <div className="h-full rounded-full transition-all duration-700" style={{ width: `${Math.max(4, pct)}%`, background: "linear-gradient(90deg,#00bc33,#73e793)" }} />
          </div>
          <span className="text-[12px] font-bold tabular-nums text-[#344054]">{dados.feitos}/{dados.total}</span>
        </div>
      </div>
      <ol className="m-0 mt-4 p-0 list-none grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {dados.passos.map((p, i) => {
          const feito = p.situacao === "feito";
          const naoSeAplica = p.situacao === "nao_se_aplica";
          const proximo = p.codigo === dados.proximo;
          return (
            <li key={p.codigo} className={`rounded-xl border p-3 flex flex-col gap-1.5 ${proximo ? "border-[#00bc33]/50 bg-[#f3fdf6]" : "border-[#EAECF0] bg-white"}`}>
              <div className="flex items-center gap-2">
                {feito ? <CheckCircle2 className="size-4 text-[#00a32c] shrink-0" aria-label="feito" />
                  : naoSeAplica ? <MinusCircle className="size-4 text-[#98A2B3] shrink-0" aria-label="não se aplica" />
                  : <Circle className="size-4 text-[#cbd5e1] shrink-0" aria-label="falta" />}
                <span className={`text-[13px] font-semibold ${feito || naoSeAplica ? "text-[#667085]" : "text-[#101828]"}`}>{i + 1}. {p.titulo}</span>
              </div>
              <p className="m-0 text-[11.5px] leading-snug text-[#667085] break-words">{naoSeAplica ? `Não se aplica: ${p.detalhe}` : p.detalhe}</p>
              {!feito && !naoSeAplica && p.para && p.acao && (
                <Link to={p.para} className={`mt-auto self-start inline-flex items-center gap-1 rounded-lg px-2.5 py-1 text-[12px] font-semibold transition-colors ${proximo ? "lc-pay-btn text-white" : "border border-[#E2E8F0] bg-white text-[#344054] hover:text-[#101828]"}`}>
                  {p.acao} <ArrowRight className="size-3.5" />
                </Link>
              )}
            </li>
          );
        })}
      </ol>
    </motion.section>
  );
}
