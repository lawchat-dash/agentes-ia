import { Check } from "lucide-react";
import { Card } from "@/components/ui/card";
import { ROLE_META, ROLE_ORDER } from "@/hooks/useProducts";
import { getCategoryIcon, resolveGradient } from "@/data/categories";

const STEP_LABELS = ["Identidade", "Comportamento", "Conteúdo", "Integrações", "Follow-up", "Revisão"];

interface Props {
  template: { name: string; category: string; description_short?: string; cover_gradient?: string | null };
  name?: string;
  step: number;
}

/** Painel-resumo lateral do wizard de Ativar — produto, pipeline e progresso. */
export function ActivationSummary({ template, name, step }: Props) {
  const [c1, c2] = resolveGradient(template.cover_gradient, template.category);
  const CatIcon = getCategoryIcon(template.category);

  return (
    <aside className="hidden lg:block lg:sticky lg:top-[5.5rem] space-y-3 self-start">
      <Card className="p-5 lc-card">
        <div className="flex items-center gap-3">
          <div className="size-11 rounded-xl grid place-items-center text-white shrink-0 shadow-sm" style={{ backgroundImage: `linear-gradient(135deg, ${c1}, ${c2})` }}>
            <CatIcon className="size-5" />
          </div>
          <div className="min-w-0">
            <div className="text-[10px] font-bold uppercase tracking-wider" style={{ color: c1 }}>{template.category}</div>
            <div className="font-bold text-sm text-[#101828] truncate">{name?.trim() || template.name}</div>
          </div>
        </div>
        {template.description_short && (
          <p className="text-xs text-[#667085] mt-3 leading-relaxed line-clamp-3">{template.description_short}</p>
        )}
        <div className="mt-4 pt-4 border-t border-[#eef1f5]">
          <div className="text-[10px] font-bold uppercase tracking-wider text-[#98A2B3] mb-2">Pipeline · {ROLE_ORDER.length} agentes</div>
          <div className="flex items-center gap-1">
            {ROLE_ORDER.map((role, i) => {
              const m = ROLE_META[role];
              const Icon = m.Icon;
              return (
                <div key={role} className="flex items-center">
                  <div className="size-7 rounded-lg grid place-items-center text-white" style={{ backgroundImage: `linear-gradient(135deg, ${c1}, ${c2})` }} title={m.label}><Icon className="size-3.5" /></div>
                  {i < ROLE_ORDER.length - 1 && <div className="w-1.5 h-px bg-[#E2E8F0]" />}
                </div>
              );
            })}
          </div>
        </div>
      </Card>

      <Card className="p-5 lc-card">
        <div className="text-[10px] font-bold uppercase tracking-wider text-[#98A2B3] mb-2.5">Progresso da ativação</div>
        <div className="space-y-2">
          {STEP_LABELS.map((lbl, i) => {
            const s = i + 1;
            const done = step > s;
            const active = step === s;
            return (
              <div key={s} className="flex items-center gap-2 text-xs">
                <span
                  className="grid size-4 place-items-center rounded-full text-[9px] shrink-0"
                  style={active || done ? { backgroundColor: c1, color: "#fff" } : { backgroundColor: "#E2E8F0", color: "#667085" }}
                >{done ? <Check className="size-2.5" /> : s}</span>
                <span className={active ? "font-semibold text-[#101828]" : ""} style={done ? { color: c1 } : !active ? { color: "#98A2B3" } : undefined}>{lbl}</span>
              </div>
            );
          })}
        </div>
      </Card>
    </aside>
  );
}
