import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Lock, Sparkles, ShieldCheck } from "lucide-react";

const REDIRECT_URL = "https://advmidia.wts.chat/chat2/sessions";

interface Props {
  open: boolean;
  account: { nome_fantasia?: string } | null;
  onClose: () => void;
}

export function BlockedAccountDialog({ open, account, onClose }: Props) {
  const handleBack = () => {
    window.location.href = REDIRECT_URL;
  };

  return (
    <Dialog open={open} onOpenChange={() => { /* fixo — não pode fechar */ }}>
      <DialogContent
        onInteractOutside={(e) => e.preventDefault()}
        onEscapeKeyDown={(e) => e.preventDefault()}
        className="sm:max-w-lg p-0 overflow-hidden border-0 shadow-2xl gap-0 bg-transparent outline-none focus:outline-none focus-visible:outline-none ring-0 focus:ring-0 focus-visible:ring-0 [&>button]:hidden"
      >
        <div className="overflow-hidden rounded-lg bg-background">

        {/* Header com gradiente do app */}
        <div className="relative bg-gradient-to-br from-primary via-primary to-primary/80 px-8 pt-10 pb-16 text-center overflow-hidden">
          <div className="absolute inset-0 opacity-20">
            <div className="absolute -top-10 -right-10 size-40 rounded-full bg-primary-foreground/20 blur-3xl" />
            <div className="absolute -bottom-10 -left-10 size-40 rounded-full bg-primary-foreground/10 blur-3xl" />
          </div>
          <div className="relative">
            <div className="mx-auto size-16 rounded-2xl bg-primary-foreground/15 backdrop-blur-sm border border-primary-foreground/20 grid place-items-center mb-4 shadow-lg">
              <Lock className="size-8 text-primary-foreground" />
            </div>
            <h2 className="text-2xl font-semibold text-primary-foreground tracking-tight">
              Acesso ainda não liberado
            </h2>
            <p className="text-primary-foreground/90 text-sm mt-2 max-w-sm mx-auto">
              {account?.nome_fantasia ? (
                <>A conta <strong className="text-primary-foreground">{account.nome_fantasia}</strong> não tem o módulo de agentes habilitado.</>
              ) : (
                <>Sua conta ainda não tem o módulo de agentes habilitado.</>
              )}
            </p>
          </div>
        </div>

        {/* Corpo */}
        <div className="px-8 pt-6 pb-8 bg-background -mt-8 rounded-t-3xl relative">
          <p className="text-center text-muted-foreground text-sm leading-relaxed mb-6">
            Libere o plano completo e comece a construir seus próprios agentes de IA personalizados em minutos.
          </p>

          {/* Benefícios */}
          <div className="space-y-3 mb-7">
            <div className="flex items-start gap-3 p-3 rounded-xl bg-muted/50 border border-border/50">
              <div className="size-8 rounded-lg bg-primary/10 grid place-items-center shrink-0">
                <Sparkles className="size-4 text-primary" />
              </div>
              <div>
                <p className="text-sm font-medium text-foreground">Agentes personalizados</p>
                <p className="text-xs text-muted-foreground">Crie assistentes treinados para o seu negócio</p>
              </div>
            </div>
            <div className="flex items-start gap-3 p-3 rounded-xl bg-muted/50 border border-border/50">
              <div className="size-8 rounded-lg bg-primary/10 grid place-items-center shrink-0">
                <ShieldCheck className="size-4 text-primary" />
              </div>
              <div>
                <p className="text-sm font-medium text-foreground">Suporte dedicado</p>
                <p className="text-xs text-muted-foreground">Atendimento direto com o time comercial</p>
              </div>
            </div>
          </div>
        </div>
        </div>
      </DialogContent>
    </Dialog>

  );
}
