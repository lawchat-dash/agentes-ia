import { ReactNode } from "react";
import { motion } from "framer-motion";
import { Braces, Check } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

export interface PromptCampo {
  field: string;
  /** Em quais lugares (agentes/seções) o campo aparece. */
  locs: string[];
}

interface Props {
  /** Campos {{ }} encontrados nos prompts, com onde cada um aparece. */
  fields: PromptCampo[];
  /** Rascunho campo→valor (controlado pelo pai). */
  draft: Record<string, string>;
  onDraftChange: (next: Record<string, string>) => void;
  /** Aplica o valor de um campo de uma vez em todos os lugares. */
  onApply: (field: string, value: string) => void;
  /** Quantos valores já foram aplicados (alimenta o estado "tudo preenchido"). */
  appliedCount: number;
  /** Onde os campos são procurados — ex.: "nos prompts dos agentes". */
  scopeText: ReactNode;
  /** Se true, marca cada campo como "Obrigatório". */
  required?: boolean;
}

/**
 * Painel "Edição rápida de Prompt" — referência validada do editor de produto
 * (ProductConfigurator). Acha os {{ campos }} dos prompts e preenche todos de uma vez.
 */
export const PromptCamposPanel = ({ fields, draft, onDraftChange, onApply, appliedCount, scopeText, required }: Props) => {
  return (
    <Card className="p-6 lc-card" style={{ borderColor: "#ece9fb" }}>
      <div className="flex items-center gap-2">
        <div className="size-7 rounded-lg grid place-items-center shrink-0 bg-[#ede9fe] text-[#7c3aed]"><Braces className="size-4" /></div>
        <span className="text-sm font-semibold text-foreground">Edição rápida de Prompt</span>
        {fields.length > 0 && <span className="text-[10px] font-bold rounded-full px-1.5 py-0.5 bg-[#ede9fe] text-[#7c3aed]">{fields.length}</span>}
        <span className="text-[10px] font-bold uppercase tracking-wider rounded-full px-2 py-0.5 bg-[#f1f5f9] text-[#64748b]">Global</span>
      </div>
      <p className="text-xs text-muted-foreground mt-1.5 mb-3">
        Acha tudo que está em <code className="text-[#7c3aed] font-medium">{"{{ }}"}</code> {scopeText}.
        Preencha <strong>uma vez</strong> aqui e o valor entra em todos os lugares que usam o campo.
        {fields.length > 0 && <span className="text-[#94a3b8]"> Não tem algum (ex.: <code className="text-[#7c3aed]">{"{{Site}}"}</code>, <code className="text-[#7c3aed]">{"{{Canal do Youtube}}"}</code>)? Use <strong>Excluir</strong> — não é obrigatório preencher todos.</span>}
      </p>

      {fields.length === 0 ? (
        appliedCount > 0 ? (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35 }}
            className="rounded-xl border border-[#bbf7d0] bg-[#f0fdf4] p-6 text-center"
          >
            <motion.div
              initial={{ scale: 0, rotate: -20 }}
              animate={{ scale: 1, rotate: 0 }}
              transition={{ type: "spring", stiffness: 320, damping: 16, delay: 0.08 }}
              className="size-12 rounded-full bg-[#22c55e] text-white grid place-items-center mx-auto shadow-[0_6px_16px_-4px_rgba(34,197,94,.55)]"
            >
              <Check className="size-6" strokeWidth={3} />
            </motion.div>
            <div className="text-base font-bold text-foreground mt-3">Tudo preenchido! 🎉</div>
            <p className="text-xs text-[#667085] mt-1 max-w-sm mx-auto leading-relaxed">
              Os valores entraram em <strong>todos os agentes</strong> que usavam os campos. O que você preencheu aparece <span className="text-[#7c3aed] font-semibold">em roxo</span> dentro dos prompts.
            </p>
          </motion.div>
        ) : (
          <div className="rounded-xl border border-dashed border-[#e0d9f7] bg-[#faf8ff] p-5">
            <div className="flex items-start gap-3">
              <div className="size-9 rounded-xl grid place-items-center shrink-0 bg-[#ede9fe] text-[#7c3aed]">
                <Braces className="size-[18px]" />
              </div>
              <div className="min-w-0">
                <div className="text-sm font-semibold text-foreground">Ainda não há campos para preencher</div>
                <p className="text-xs text-[#667085] mt-0.5 leading-relaxed">
                  Campos são "atalhos" do prompt: você escreve uma vez e reaproveita em todos os agentes, sem editar um por um.
                </p>
              </div>
            </div>

            <div className="mt-4 space-y-2.5">
              {[
                <>No prompt de um agente, escreva o que muda de cliente para cliente entre <code className="text-[#7c3aed] font-medium">{"{{ }}"}</code>. Ex: <code className="text-[#7c3aed]">{"{{nome_do_escritorio}}"}</code>, <code className="text-[#7c3aed]">{"{{valor_da_consulta}}"}</code>.</>,
                <>O campo <strong>aparece aqui sozinho</strong>, mostrando em quais agentes ele é usado.</>,
                <>Você <strong>preenche uma vez</strong> e o valor entra em todos os lugares de uma vez.</>,
              ].map((txt, i) => (
                <div key={i} className="flex items-start gap-2.5">
                  <span className="mt-0.5 size-5 shrink-0 rounded-full grid place-items-center text-[11px] font-bold bg-[#ede9fe] text-[#7c3aed]">{i + 1}</span>
                  <span className="text-xs text-[#475467] leading-relaxed">{txt}</span>
                </div>
              ))}
            </div>
          </div>
        )
      ) : (
        <div className="space-y-2.5">
          {fields.map(({ field: f, locs }) => {
            const filled = !!(draft[f] ?? "").trim();
            return (
              <div key={f} className="rounded-xl border border-[#eceaf6] bg-[#fcfbff] p-3">
                <div className="flex items-center gap-2 flex-wrap mb-2">
                  <code className="rounded px-1.5 py-1 text-[12px] font-semibold text-[#7c3aed] bg-[#ede9fe]" title={`{{${f}}}`}>{`{{${f}}}`}</code>
                  {required && <span className="text-[10px] font-bold text-[#dc2626] uppercase tracking-wide">Obrigatório</span>}
                  <span className="text-[10px] text-[#98A2B3]">· usado em</span>
                  {locs.map((l) => (
                    <span key={l} className="text-[10px] font-semibold rounded-md px-1.5 py-0.5 bg-white border border-[#e5e8ee] text-[#64748b]">{l}</span>
                  ))}
                </div>
                <div className="flex items-center gap-2">
                  <Input
                    value={draft[f] ?? ""}
                    onChange={(e) => onDraftChange({ ...draft, [f]: e.target.value })}
                    onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); onApply(f, draft[f] ?? ""); } }}
                    placeholder={`Valor para ${f}…`}
                    className="h-9 text-sm bg-white focus-visible:ring-[#7c3aed]"
                  />
                  <Button
                    size="sm"
                    variant={filled ? "default" : "outline"}
                    className={`h-9 shrink-0 font-semibold disabled:opacity-100 ${filled ? "text-white border-transparent" : "bg-white border-[#d6cdf2] text-[#7c3aed] hover:bg-[#ede9fe]"}`}
                    style={filled ? { backgroundColor: "#7c3aed" } : undefined}
                    disabled={!filled}
                    onClick={() => onApply(f, draft[f] ?? "")}
                  >
                    <Check className="size-4 mr-1" />Aplicar
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
};
