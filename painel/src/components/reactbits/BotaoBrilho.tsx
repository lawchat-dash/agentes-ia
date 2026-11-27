// Botão de ação estratégico do painel no verde LawChat (botão verde sólido com brilho na borda seguindo o cursor).
// `suave` = versão secundária: fundo verde-claro, texto verde-escuro (para fundo branco).
//
// Antes era o SpecularButton em WebGL: cada botão abria um contexto gráfico, um laço de quadros e um ouvinte de mouse
// na página toda. Com 15 botões espalhados o painel ficava lento. Agora é um <button> comum com o brilho leve em CSS
// (lib/brilhoBotoes.ts + estilo-brilho.css, um só ouvinte para a página inteira). Os props do SpecularButton que só
// serviam ao WebGL são aceitos e ignorados, para nenhuma tela precisar mudar.
import type { ButtonHTMLAttributes, CSSProperties, ReactNode } from "react";
import "./SpecularButton.css";
import "./BotaoBrilho.css";

type Tamanho = "sm" | "md" | "lg";
type Props = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children" | "type"> & {
  children?: ReactNode; size?: Tamanho; radius?: number; type?: "button" | "submit" | "reset";
  cheio?: boolean; suave?: boolean;
  // do SpecularButton (WebGL), sem efeito aqui:
  tint?: string; tintOpacity?: number; blur?: number; textColor?: string; lineColor?: string; baseColor?: string;
  intensity?: number; idleIntensity?: number; shineSize?: number; shineFade?: number; thickness?: number; glow?: number;
  speed?: number; followMouse?: boolean; proximity?: number; autoAnimate?: boolean;
};

export default function BotaoBrilho({
  cheio, suave, className = "", style, size = "md", radius = 12, type = "button", children,
  tint: _t, tintOpacity: _to, blur: _b, textColor: _tc, lineColor: _lc, baseColor: _bc, intensity: _i, idleIntensity: _ii,
  shineSize: _ss, shineFade: _sf, thickness: _th, glow: _g, speed: _sp, followMouse: _fm, proximity: _p, autoAnimate: _aa,
  ...resto
}: Props) {
  const classes = ["specular-button", `specular-button--${size}`, "lc-botao-brilho", "lc-brilho",
    suave ? "lc-botao-brilho--suave" : "", cheio ? "lc-botao-brilho--cheio" : "", className].filter(Boolean).join(" ");
  return (
    <button type={type} className={classes}
            style={{ "--sb-radius": `${radius}px`, "--sb-text-color": suave ? "#00701f" : "#ffffff", ...(style as CSSProperties) } as CSSProperties}
            {...resto}>
      {!suave && <span className="lc-botao-brilho__pontos" aria-hidden="true" />}
      <span className="specular-button__label">{children}</span>
    </button>
  );
}
