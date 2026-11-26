import * as React from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { motion, useAnimation } from "framer-motion";
import { Trash2Icon, Loader2 } from "lucide-react";
import { useRef, useState } from "react";

interface ButtonHoldAndReleaseProps extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "onClick"> {
  /** Tempo (ms) que o usuário precisa segurar para confirmar. */
  holdDuration?: number;
  /** Disparado quando o hold completa sem soltar antes. */
  onConfirm?: () => void;
  /** true = só ícone (compacto); false = ícone + texto. */
  compact?: boolean;
  /** Texto em repouso (modo não-compacto). */
  label?: string;
  /** Texto enquanto segura (modo não-compacto). */
  holdingLabel?: string;
  loading?: boolean;
}

/** Botão "segure para confirmar": preenche uma barra ao segurar e dispara onConfirm ao completar. */
function ButtonHoldAndRelease({
  className,
  holdDuration = 1600,
  onConfirm,
  compact = false,
  label = "Segure para excluir",
  holdingLabel = "Solte para cancelar…",
  loading = false,
  disabled,
  ...props
}: ButtonHoldAndReleaseProps) {
  const [isHolding, setIsHolding] = useState(false);
  const controls = useAnimation();
  const cancelledRef = useRef(false);

  async function handleHoldStart() {
    if (disabled || loading) return;
    cancelledRef.current = false;
    setIsHolding(true);
    controls.set({ width: "0%" });
    await controls.start({ width: "100%", transition: { duration: holdDuration / 1000, ease: "linear" } });
    setIsHolding(false);
    if (!cancelledRef.current) {
      controls.set({ width: "0%" });
      onConfirm?.();
    }
  }

  function handleHoldEnd() {
    if (!isHolding) return;
    cancelledRef.current = true;
    setIsHolding(false);
    controls.stop();
    controls.start({ width: "0%", transition: { duration: 0.12 } });
  }

  return (
    <Button
      type="button"
      size="sm"
      variant="outline"
      disabled={disabled || loading}
      className={cn(
        "relative overflow-hidden touch-none select-none transition-colors",
        "bg-background text-muted-foreground border-border",
        "hover:bg-destructive/5 hover:text-destructive hover:border-destructive/40",
        isHolding && "bg-destructive/5 text-destructive border-destructive/50",
        compact ? "px-2.5" : "min-w-40",
        className,
      )}
      onMouseDown={handleHoldStart}
      onMouseUp={handleHoldEnd}
      onMouseLeave={handleHoldEnd}
      onTouchStart={handleHoldStart}
      onTouchEnd={handleHoldEnd}
      onTouchCancel={handleHoldEnd}
      {...props}
    >
      <motion.div
        initial={{ width: "0%" }}
        animate={controls}
        className="absolute left-0 top-0 h-full bg-destructive/25"
      />
      <span className="relative z-10 w-full flex items-center justify-center gap-2">
        {loading ? <Loader2 className="size-4 animate-spin" /> : <Trash2Icon className="size-4" />}
        {!compact && (isHolding ? holdingLabel : label)}
      </span>
    </Button>
  );
}

export { ButtonHoldAndRelease };
