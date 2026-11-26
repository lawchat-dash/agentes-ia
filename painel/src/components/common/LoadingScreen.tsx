import logo from "@/assets/lawchat-logo.png";

interface LoadingScreenProps {
  /** Linha principal (ex.: "Carregando", "Validando seu acesso"). */
  texto?: string;
  /** Linha secundária opcional. */
  sub?: string;
  /** "bloqueio" usa vermelho e para a animação (conta não liberada). */
  tom?: "normal" | "bloqueio";
}

/**
 * Tela de carregamento no padrão LawChat: logo da marca num círculo branco com
 * um spinner circular fino girando ao redor (verde de acento), glow sutil de fundo
 * e barra indeterminada. Limpa e discreta — sem gradientes exagerados.
 */
export function LoadingScreen({ texto = "Carregando", sub, tom = "normal" }: LoadingScreenProps) {
  const bloqueio = tom === "bloqueio";
  const cor = bloqueio ? "hsl(0 84% 60%)" : "hsl(var(--primary))";

  return (
    <div className="relative grid min-h-screen w-full place-items-center overflow-hidden bg-background px-6">
      {/* Glow de fundo — bem sutil */}
      <div
        aria-hidden
        className="pointer-events-none absolute -top-40 right-[-10%] size-[420px] rounded-full blur-[120px]"
        style={{ background: bloqueio ? "hsl(0 84% 60% / 0.07)" : "hsl(var(--primary) / 0.09)" }}
      />

      <div className="relative flex flex-col items-center gap-7">
        {/* Logo + spinner circular */}
        <div className="relative grid size-24 place-items-center">
          {!bloqueio && (
            <svg viewBox="0 0 96 96" className="absolute size-24 animate-spin" style={{ animationDuration: "0.95s" }} aria-hidden>
              <circle cx="48" cy="48" r="43" fill="none" stroke="hsl(var(--muted))" strokeWidth="4" />
              <circle cx="48" cy="48" r="43" fill="none" stroke={cor} strokeWidth="4" strokeLinecap="round" strokeDasharray="58 214" />
            </svg>
          )}
          <div
            className="relative grid size-[68px] place-items-center rounded-full border border-[#eef1f5] bg-card"
            style={{ boxShadow: "0 12px 30px -12px rgba(15,23,42,0.28)" }}
          >
            <img src={logo} alt="LawChat" className="size-11 object-contain" draggable={false} />
          </div>
        </div>

        {/* Texto */}
        <div className="space-y-1 text-center">
          <div className="text-[15px] font-semibold tracking-tight text-foreground">{texto}</div>
          {sub ? <p className="max-w-[280px] text-xs text-muted-foreground">{sub}</p> : null}
        </div>

        {/* Barra indeterminada (só no modo normal) */}
        {!bloqueio && (
          <div className="relative h-1 w-44 overflow-hidden rounded-full bg-muted">
            <div
              aria-hidden
              className="absolute inset-y-0 w-1/3 rounded-full"
              style={{ background: "linear-gradient(90deg, transparent, hsl(var(--primary)), transparent)", animation: "lc-load-slide 1.4s ease-in-out infinite" }}
            />
          </div>
        )}
      </div>
    </div>
  );
}
