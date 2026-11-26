import * as React from "react";
import { AlertTriangle, CheckCircle2, Info, Lightbulb, XCircle, type LucideIcon } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

/**
 * Aviso padrão do painel — UMA receita para todas as caixas de aviso/alerta/dica.
 *
 *  - info     → informação neutra (azul)
 *  - sucesso  → algo deu certo (verde LawChat)
 *  - atencao  → exige cuidado antes de seguir (âmbar)
 *  - erro     → algo falhou (vermelho)
 *  - dica     → sugestão calma, sem urgência (neutro com ícone verde)
 *
 * Texto sempre escuro e legível; a cor fica no ícone, na borda e no título.
 */
export type AvisoTipo = "info" | "sucesso" | "atencao" | "erro" | "dica";

const MAPA: Record<AvisoTipo, { variant: "info" | "success" | "warning" | "destructive" | "tip"; Icon: LucideIcon; role: string }> = {
  info: { variant: "info", Icon: Info, role: "note" },
  sucesso: { variant: "success", Icon: CheckCircle2, role: "status" },
  atencao: { variant: "warning", Icon: AlertTriangle, role: "note" },
  erro: { variant: "destructive", Icon: XCircle, role: "alert" },
  dica: { variant: "tip", Icon: Lightbulb, role: "note" },
};

export function Aviso({
  tipo = "info",
  titulo,
  icone,
  acoes,
  compacto = false,
  className,
  children,
}: {
  tipo?: AvisoTipo;
  titulo?: React.ReactNode;
  /** Ícone próprio; `null` esconde o ícone. Padrão: o ícone do tipo. */
  icone?: LucideIcon | null;
  /** Botões/links logo abaixo do texto. */
  acoes?: React.ReactNode;
  compacto?: boolean;
  className?: string;
  children?: React.ReactNode;
}) {
  const m = MAPA[tipo];
  const Icon = icone === null ? null : (icone ?? m.Icon);
  return (
    <Alert variant={m.variant} size={compacto ? "sm" : "default"} role={m.role} className={className}>
      {Icon && <Icon aria-hidden="true" />}
      <div>
        {titulo && <AlertTitle className={compacto ? "text-xs" : "text-sm"}>{titulo}</AlertTitle>}
        {children && <AlertDescription className={compacto ? "text-[11.5px]" : "text-[13px]"}>{children}</AlertDescription>}
        {acoes && <div className="mt-2.5 flex flex-wrap items-center gap-2">{acoes}</div>}
      </div>
    </Alert>
  );
}

export default Aviso;
