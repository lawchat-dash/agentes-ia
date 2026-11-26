import { AlertTriangle, Check, Info, Loader2, X } from "lucide-react";
import { Toaster as Sonner, toast } from "sonner";

type ToasterProps = React.ComponentProps<typeof Sonner>;

/**
 * Avisos rápidos (sonner) no padrão LawChat: card branco, realce lateral colorido por tipo,
 * ícone em círculo, título forte e descrição cinza. O visual fica em estilo.css (.lc-toast*),
 * por isso o sonner roda "unstyled" e sem richColors (que deixava o aviso chapado).
 */
const icone = (tipo: string, el: React.ReactNode) => (
  <span className={`lc-toast-bolha lc-toast-bolha-${tipo}`} aria-hidden="true">{el}</span>
);

const ICONES: NonNullable<ToasterProps["icons"]> = {
  success: icone("success", <Check strokeWidth={3} />),
  error: icone("error", <X strokeWidth={3} />),
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
