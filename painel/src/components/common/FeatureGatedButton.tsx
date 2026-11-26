import { Button, ButtonProps } from "@/components/ui/button";
import { Lock } from "lucide-react";
import { toast } from "sonner";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { usePlanFeatures, PlanFeature } from "@/hooks/usePlanFeatures";

interface Props extends Omit<ButtonProps, "onClick"> {
  feature: PlanFeature;
  featureLabel: string;
  onAllowed: () => void;
}

/**
 * Botão que só dispara onAllowed se o plano atual liberar o recurso.
 * Caso contrário mostra cadeado, tooltip e leva o usuário para a página de planos.
 */
export const FeatureGatedButton = ({
  feature,
  featureLabel,
  onAllowed,
  children,
  className,
  disabled,
  ...rest
}: Props) => {
  const features = usePlanFeatures();
  const allowed = features.has(feature);

  if (allowed) {
    return (
      <Button {...rest} className={className} disabled={disabled} onClick={onAllowed}>
        {children}
      </Button>
    );
  }

  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            {...rest}
            variant="outline"
            className={`relative opacity-70 hover:opacity-100 ${className ?? ""}`}
            onClick={(e) => {
              e.preventDefault();
              toast.info(`${featureLabel} não disponível no seu plano`, {
                description: `Faça upgrade para liberar ${featureLabel.toLowerCase()} nos prompts.`,
              });
            }}
          >
            <Lock className="size-3 mr-1 text-muted-foreground" />
            {children}
          </Button>
        </TooltipTrigger>
        <TooltipContent side="top" className="text-xs">
          Recurso não disponível no seu plano.
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
};
