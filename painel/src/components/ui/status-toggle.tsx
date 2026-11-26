import { Power, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

interface StatusToggleProps {
  /** true = agente ativo (verde, knob à direita). */
  active: boolean;
  onToggle: (e: React.MouseEvent) => void;
  loading?: boolean;
  disabled?: boolean;
  className?: string;
  title?: string;
}

/**
 * Switch de ativar/desativar agente.
 * Verde (--primary) quando ativo · âmbar/laranja quando pausado.
 */
export function StatusToggle({ active, onToggle, loading, disabled, className, title }: StatusToggleProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={active}
      aria-label={title ?? (active ? "Pausar agente" : "Ativar agente")}
      title={title ?? (active ? "Pausar agente" : "Ativar agente")}
      onClick={(e) => { if (!disabled && !loading) onToggle(e); }}
      disabled={disabled || loading}
      className={cn(
        "relative h-7 w-[3.25rem] shrink-0 rounded-full border transition-colors duration-500 [transition-timing-function:cubic-bezier(0.68,-0.55,0.265,1.55)] disabled:opacity-60 disabled:cursor-not-allowed",
        active ? "border-primary/40 bg-primary/15" : "border-amber-400/50 bg-amber-400/20",
        className,
      )}
    >
      <span
        className={cn(
          "absolute top-1/2 grid size-5 -translate-y-1/2 place-items-center rounded-full text-white shadow-sm transition-[left,background-color] duration-500 [transition-timing-function:cubic-bezier(0.68,-0.55,0.265,1.55)]",
          active ? "left-[calc(100%-1.375rem)] bg-primary" : "left-0.5 bg-amber-500",
        )}
      >
        {loading ? <Loader2 className="size-3 animate-spin" /> : <Power className="size-3" strokeWidth={2.5} />}
      </span>
    </button>
  );
}
