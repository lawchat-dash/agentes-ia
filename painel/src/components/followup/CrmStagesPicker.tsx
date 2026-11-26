import { Check, Phone, Handshake, FileText, PenLine } from "lucide-react";
import { cn } from "@/lib/utils";
import { CrmStage, STAGE_LABELS, STAGE_ORDER } from "@/hooks/useFollowups";

const STAGE_ICONS = {
  sdr: Phone,
  closer: Handshake,
  contrato: FileText,
  assinatura: PenLine,
} as const;

interface Props {
  value: CrmStage[];
  onChange: (next: CrmStage[]) => void;
}

export const CrmStagesPicker = ({ value, onChange }: Props) => {
  const toggle = (s: CrmStage) =>
    onChange(value.includes(s) ? value.filter((v) => v !== s) : [...value, s]);
  return (
    <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
      {STAGE_ORDER.map((s) => {
        const Icon = STAGE_ICONS[s];
        const checked = value.includes(s);
        return (
          <button
            type="button"
            key={s}
            onClick={() => toggle(s)}
            className={cn(
              "text-left p-4 rounded-xl cursor-pointer transition-all duration-200 border bg-card",
              checked
                ? "border-success/50 ring-1 ring-success/20"
                : "border-border hover:border-success/30 hover:shadow-sm",
            )}
          >
            <div className="flex items-start justify-between">
              <div className={cn(
                "size-10 rounded-xl grid place-items-center border transition-colors",
                checked ? "bg-success/10 text-success border-success/20" : "bg-muted text-muted-foreground border-border",
              )}>
                <Icon className="size-5" strokeWidth={1.75} />
              </div>
              <div className={cn(
                "size-5 rounded-md border grid place-items-center transition-all duration-200",
                checked ? "bg-success border-success text-success-foreground" : "border-input bg-background",
              )}>
                {checked && <Check className="size-3.5" strokeWidth={3} />}
              </div>
            </div>
            <div className="mt-3 font-bold text-sm">{STAGE_LABELS[s]}</div>
          </button>
        );
      })}
    </div>
  );
};

