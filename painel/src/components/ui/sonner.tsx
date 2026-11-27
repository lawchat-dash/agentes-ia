import { AlertCircle, AlertTriangle, Check, Info, Loader2, X } from "lucide-react";
import { Toaster as Sonner, toast } from "sonner";
import "./sonner.css";

type ToasterProps = React.ComponentProps<typeof Sonner>;

/**
 * Avisos rápidos (sonner) no visual do SwipeToast do React Bits: card escuro, ícone por tipo
 * (check verde, alerta vermelho...), botão de ação claro e o pavio queimando embaixo no tempo do aviso.
 * Base em estilo.css (.lc-toast*), sobreposta por ./sonner.css. Todas as chamadas toast.* continuam iguais.
 */
const icone = (tipo: string, el: React.ReactNode) => (
  <span className={`lc-toast-bolha lc-toast-bolha-${tipo}`} aria-hidden="true">{el}</span>
);

const ICONES: NonNullable<ToasterProps["icons"]> = {
  success: icone("success", <Check strokeWidth={3} />),
  error: icone("error", <AlertCircle strokeWidth={2.5} />),
  warning: icone("warning", <AlertTriangle strokeWidth={2.5} />),
  info: icone("info", <Info strokeWidth={2.5} />),
  loading: icone("loading", <Loader2 className="animate-spin" strokeWidth={2.5} />),
  close: <X strokeWidth={2.25} />,
};

const Toaster = ({ toastOptions, icons, ...props }: ToasterProps) => {
  return (
    <Sonner
      theme="light"
      className="toaster lc-toaster"
      closeButton
      gap={10}
      swipeDirections={["right", "bottom", "top"]}
      {...props}
      richColors={false}
      icons={{ ...ICONES, ...icons }}
      toastOptions={{
        ...toastOptions,
        unstyled: true,
        classNames: {
          toast: "lc-toast",
          content: "lc-toast-conteudo",
          title: "lc-toast-titulo",
          description: "lc-toast-desc",
          icon: "lc-toast-icone",
          closeButton: "lc-toast-fechar",
          actionButton: "lc-toast-btn lc-toast-btn-acao",
          cancelButton: "lc-toast-btn",
          ...toastOptions?.classNames,
        },
      }}
    />
  );
};

export { Toaster, toast };
