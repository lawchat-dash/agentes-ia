// Botão de ação estratégico do painel: o SpecularButton do React Bits no verde LawChat (botão verde sólido,
// com o brilho correndo pela borda e seguindo o cursor). Só para os poucos CTAs principais.
import type { CSSProperties } from "react";
import SpecularButton, { type SpecularButtonProps } from "./SpecularButton";
import "./BotaoBrilho.css";

type Props = SpecularButtonProps & { cheio?: boolean };

export default function BotaoBrilho({ cheio, className = "", style, size = "md", radius = 12, ...resto }: Props) {
  return (
    <SpecularButton
      size={size}
      radius={radius}
      tint="#00bc33"
      tintOpacity={1}
      textColor="#ffffff"
      lineColor="#eafff0"
      baseColor="#0a8f35"
      intensity={1}
      idleIntensity={0.3}
      thickness={1.3}
      glow={0.9}
      proximity={180}
      className={`lc-botao-brilho${cheio ? " lc-botao-brilho--cheio" : ""} ${className}`.trim()}
      style={style as CSSProperties}
      {...resto}
    />
  );
}
