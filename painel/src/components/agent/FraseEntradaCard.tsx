import { ArrowRightLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useFrasesTroca } from "@/hooks/useFrasesTroca";
import { COR_TRANSFERENCIA, agentesSemFraseDeSaida, fraseDaEtapa, frasesReferenciadas, rotuloFrase } from "@/data/frasesTroca";

interface Props {
  /** Papel do agente (sdr, closer, contratos...). */
  role: string;
  /** Texto do prompt (com os tokens) — p/ listar as frases que ESTE agente usa para passar adiante. */
  prompt?: string;
  /** Só no super admin: abre o cadastro das frases. Sem isso o card é somente leitura. */
  onGerenciar?: () => void;
}

/**
 * Resumo visual das frases para transferência de um agente:
 *  - ENTRADA: a frase que o agente anterior fala para o lead chegar aqui (a mensagem_troca
 *    desta etapa no bot);
 *  - SAÍDA: as @Transferência que este agente usa no prompt para passar o lead adiante.
 * As frases são fixas (super admin).
 */
export const FraseEntradaCard = ({ role, prompt, onGerenciar }: Props) => {
  const { data: frases } = useFrasesTroca();
  const lista = frases ?? [];
  const entrada = fraseDaEtapa(role, lista);
  const saidas = frasesReferenciadas(prompt ?? "", lista).filter((f) => f.etapa_destino !== role);
  // Trava: agente que passa o lead adiante SEM frase de saída (ex.: apagaram o chip) → aviso na
  // hora; o salvamento também é bloqueado (mesma regra de agentesSemFraseDeSaida).
  const semSaida = agentesSemFraseDeSaida([{ etapa: role, prompt: prompt ?? "" }], lista, { ignorarVazios: true }).length > 0;
  if (!entrada && saidas.length === 0 && !onGerenciar && !semSaida) return null;

  return (
    <div className="rounded-xl border p-3.5 space-y-2.5" style={{ borderColor: "#fed7aa", background: "#fff7ed" }}>
      <div className="flex items-center gap-1.5 flex-wrap">
        <ArrowRightLeft className="size-3.5" style={{ color: COR_TRANSFERENCIA }} />
        <span className="text-[11px] font-bold uppercase tracking-wider" style={{ color: COR_TRANSFERENCIA }}>Frases para Transferência</span>
        <span className="text-[9px] font-bold uppercase tracking-wider rounded-full px-1.5 py-0.5 bg-white border" style={{ color: COR_TRANSFERENCIA, borderColor: "#fed7aa" }}>
          Fixas · super admin
        </span>
        {onGerenciar && (
          <Button type="button" size="sm" variant="ghost" className="ml-auto h-7 text-xs" onClick={onGerenciar}>
            Editar frases
          </Button>
        )}
      </div>

      <div>
        <div className="text-[11px] font-semibold text-muted-foreground">Entrada neste agente</div>
        {entrada ? (
          <>
            <p className="mt-0.5 text-sm text-foreground leading-relaxed">“{entrada.frase}”</p>
            <p className="text-[11px] text-muted-foreground mt-0.5">
              O agente anterior fala esta frase e o lead passa para cá (é a <code>mensagem_troca</code> deste agente).
            </p>
          </>
        ) : (
          <p className="mt-0.5 text-[11px] text-muted-foreground">Nenhuma frase cadastrada para este departamento.</p>
        )}
      </div>

      <div>
        <div className="text-[11px] font-semibold text-muted-foreground">Saída deste agente</div>
        {saidas.length > 0 ? (
          <div className="mt-1 flex flex-wrap gap-1.5">
            {saidas.map((f) => (
              <span
                key={f.id}
                title={f.frase}
                className="text-xs font-semibold rounded px-1.5 py-0.5 bg-white border"
                style={{ color: COR_TRANSFERENCIA, borderColor: "#fed7aa" }}
              >
                @{rotuloFrase(f.nome)}
              </span>
            ))}
          </div>
        ) : semSaida ? (
          <div className="mt-1 rounded-lg border border-destructive/30 bg-destructive/5 px-2.5 py-2">
            <p className="text-[11px] font-semibold text-destructive">Falta a Frase para Transferência — não é possível salvar.</p>
            <p className="text-[11px] text-muted-foreground mt-0.5 leading-snug">
              Este agente precisa de uma frase para passar o lead adiante.{" "}
              {onGerenciar
                ? "Insira com @ → Transferência ou selecione o trecho e use “Marcar frase”."
                : "Se apagou sem querer, desfaça (Ctrl+Z) ou fale com o suporte."}
            </p>
          </div>
        ) : (
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            Este prompt não usa nenhuma @Transferência{onGerenciar ? " — insira com @ → Transferência." : "."}
          </p>
        )}
      </div>
    </div>
  );
};
