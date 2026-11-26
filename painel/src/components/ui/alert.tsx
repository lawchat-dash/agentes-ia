import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/**
 * Caixa de aviso do painel (shadcn, adaptada à identidade LawChat).
 *
 * Regra de legibilidade: o TEXTO é sempre escuro (foreground); a cor da variante fica só
 * na borda, no ícone e no título — nunca texto colorido claro sobre fundo colorido claro.
 * O fundo recebe no máximo um véu bem leve da cor, para diferenciar sem cansar a leitura.
 *
 * Variantes:
 *  - default     → neutro (cartão)
 *  - info        → informação (azul)
 *  - success     → deu certo / confirmado (verde LawChat)
 *  - warning     → atenção, exige cuidado (âmbar)
 *  - destructive → erro / algo falhou (vermelho)
 *  - tip         → dica: informativa e calma (neutro com ícone verde)
 *
 * Para o uso do dia a dia prefira <Aviso> (components/common/Aviso.tsx), que já escolhe
 * o ícone e o papel de acessibilidade certos para cada tipo.
 */
const alertVariants = cva(
  [
    "relative w-full rounded-xl border text-foreground",
    // ícone posicionado à esquerda; o conteúdo ganha recuo
    "[&>svg]:absolute [&>svg]:size-4 [&>svg]:shrink-0",
    "[&>svg~*]:pl-7",
  ].join(" "),
  {
    variants: {
      variant: {
        default: "border-border bg-card [&>svg]:text-muted-foreground",
        info:
          "border-sky-200 bg-sky-50/50 [&>svg]:text-sky-600 [&_[data-alert-title]]:text-sky-900 " +
          "dark:border-sky-500/30 dark:bg-sky-500/[0.06] dark:[&>svg]:text-sky-400 dark:[&_[data-alert-title]]:text-sky-200",
        success:
          "border-[#00BC33]/30 bg-[#00BC33]/[0.04] [&>svg]:text-[#00a02b] [&_[data-alert-title]]:text-[#0b5d22] " +
          "dark:border-success/30 dark:bg-success/[0.07] dark:[&>svg]:text-success dark:[&_[data-alert-title]]:text-green-200",
        warning:
          "border-amber-300/80 bg-amber-50/60 [&>svg]:text-amber-600 [&_[data-alert-title]]:text-amber-900 " +
          "dark:border-amber-500/30 dark:bg-amber-500/[0.07] dark:[&>svg]:text-amber-400 dark:[&_[data-alert-title]]:text-amber-200",
        destructive:
          "border-destructive/35 bg-destructive/[0.04] [&>svg]:text-destructive [&_[data-alert-title]]:text-red-800 " +
          "dark:border-destructive/40 dark:bg-destructive/[0.08] dark:[&_[data-alert-title]]:text-red-200",
        tip:
          "border-border bg-muted/40 [&>svg]:text-[#00a02b] dark:[&>svg]:text-success",
      },
      size: {
        default: "px-4 py-3.5 text-sm [&>svg]:left-4 [&>svg]:top-[15px]",
        sm: "px-3 py-2.5 text-xs [&>svg]:left-3 [&>svg]:top-[11px] [&>svg~*]:pl-6 [&>svg]:size-3.5",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

export type AlertProps = React.HTMLAttributes<HTMLDivElement> & VariantProps<typeof alertVariants>;

const Alert = React.forwardRef<HTMLDivElement, AlertProps>(({ className, variant, size, ...props }, ref) => (
  <div ref={ref} role="alert" className={cn(alertVariants({ variant, size }), className)} {...props} />
));
Alert.displayName = "Alert";

const AlertTitle = React.forwardRef<HTMLParagraphElement, React.HTMLAttributes<HTMLHeadingElement>>(
  ({ className, ...props }, ref) => (
    <h5
      ref={ref}
      data-alert-title=""
      className={cn("mb-0.5 font-semibold leading-snug tracking-tight text-foreground", className)}
      {...props}
    />
  ),
);
AlertTitle.displayName = "AlertTitle";

const AlertDescription = React.forwardRef<HTMLParagraphElement, React.HTMLAttributes<HTMLParagraphElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn("leading-relaxed text-foreground/80 [&_p]:leading-relaxed [&_strong]:font-semibold [&_strong]:text-foreground", className)}
      {...props}
    />
  ),
);
AlertDescription.displayName = "AlertDescription";

export { Alert, AlertTitle, AlertDescription, alertVariants };
