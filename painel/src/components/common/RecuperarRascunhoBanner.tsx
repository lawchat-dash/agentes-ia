import { History, RotateCcw, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { quandoFoiSalvo } from "@/hooks/useRascunhoLocal";

/**
 * Aviso de "alterações não salvas" encontradas ao reabrir um editor (useRascunhoLocal).
 * Aparece quando a página recarregou/fechou antes de salvar (aba descartada pelo navegador,
 * queda de sessão, recarga do servidor de desenvolvimento...).
 */
export function RecuperarRascunhoBanner({
  salvoEm,
  onRecuperar,
  onDescartar,
  className = "",
}: {
  salvoEm: number;
  onRecuperar: () => void;
  onDescartar: () => void;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={`flex flex-col gap-3 rounded-xl border border-primary/30 bg-primary/5 px-4 py-3 sm:flex-row sm:items-center ${className}`}
    >
      <div className="flex min-w-0 flex-1 items-start gap-3">
        <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary">
          <History className="size-4" />
        </span>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-foreground">Você tem alterações que não foram salvas</p>
          <p className="text-xs text-muted-foreground">
            Guardamos o que você estava editando ({quandoFoiSalvo(salvoEm)}) antes de a página recarregar.
            Recupere para continuar de onde parou.
          </p>
        </div>
      </div>
      <div className="flex shrink-0 gap-2">
        <Button size="sm" variant="ghost" onClick={onDescartar} className="text-muted-foreground">
          <Trash2 className="mr-1.5 size-4" />Descartar
        </Button>
        <Button size="sm" onClick={onRecuperar}>
          <RotateCcw className="mr-1.5 size-4" />Recuperar alterações
        </Button>
      </div>
    </div>
  );
}
