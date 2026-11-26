// Logo LawChat que se escreve: o balão se desenha e enche de verde, a rede se junta, e cada letra tem o contorno
// traçado e depois preenchido, em sequência. Usa os mesmos traços da tela de carregamento
// (componentes/logoLawchatTracos.ts, gerados dos SVGs da pasta "escrita"). Com prefers-reduced-motion: logo pronta.
import { useId, type CSSProperties } from "react";
import { BALAO, CENTRO, LETRAS, PONTAS } from "@/componentes/logoLawchatTracos";
import "./LogoEscrita.css";

export default function LogoEscrita({ altura = 32, atraso = 0.15, brilho = true, className = "" }: {
  /** Altura em px (a largura segue a proporção da logo horizontal, 1959 x 400). */
  altura?: number;
  /** Segundos antes de começar. */
  atraso?: number;
  /** Faixa de luz que passa pela escrita de tempos em tempos, depois de pronta. */
  brilho?: boolean;
  className?: string;
}) {
  const id = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const u = (n: string) => `le-${n}-${id}`;
  return (
    <svg className={`le-logo ${className}`.trim()} viewBox="0 0 1959 400" role="img" aria-label="LawChat"
         style={{ height: altura, width: (altura * 1959) / 400, "--le-atraso": `${atraso}s` } as CSSProperties}>
      <defs>
        <linearGradient id={u("law")} x1="0" y1="0" x2="0" y2="1"><stop stopColor="#A7D7A4" /><stop offset="1" stopColor="#00BC33" /></linearGradient>
        <linearGradient id={u("chat")} x1="0" y1="0" x2="0" y2="1"><stop stopColor="#FFFFFF" /><stop offset="1" stopColor="#E1E4E3" /></linearGradient>
        <linearGradient id={u("verde")} gradientUnits="userSpaceOnUse" x1="790" y1="75" x2="355" y2="920">
          <stop stopColor="#ACF8B6" /><stop offset=".36" stopColor="#42E963" /><stop offset=".72" stopColor="#0AD33D" /><stop offset="1" stopColor="#00B332" />
        </linearGradient>
        <linearGradient id={u("branco")} gradientUnits="userSpaceOnUse" x1="360" y1="245" x2="650" y2="805">
          <stop stopColor="#FFFFFF" /><stop offset=".48" stopColor="#F8F8F8" /><stop offset="1" stopColor="#D9DBDE" />
        </linearGradient>
        <linearGradient id={u("luz")} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#fff" stopOpacity="0" /><stop offset=".5" stopColor="#fff" stopOpacity=".5" /><stop offset="1" stopColor="#fff" stopOpacity="0" />
        </linearGradient>
        <clipPath id={u("recorte")}>
          {LETRAS.map((l, i) => <path key={i} d={l.d} transform={`translate(${410 + l.x} ${25 + l.y})`} />)}
        </clipPath>
      </defs>

      <g transform="translate(0 5) scale(.38)">
        <path className="le-balao" d={BALAO} fill={`url(#${u("verde")})`} />
        <path className="le-traco le-balao-traco" d={BALAO} pathLength={1} />
        {PONTAS.map((p, i) => (
          <path key={`l${i}`} className="le-linha" style={{ "--i": i } as CSSProperties}
                d={`M ${CENTRO.x} ${CENTRO.y} L ${p.x} ${p.y}`} pathLength={1} stroke={`url(#${u("branco")})`} strokeWidth={49} strokeLinecap="round" fill="none" />
        ))}
        <circle className="le-anel" cx={CENTRO.x} cy={CENTRO.y} r={87.5} pathLength={1} fill="none" stroke={`url(#${u("branco")})`} strokeWidth={45} />
        {PONTAS.map((p, i) => (
          <circle key={`n${i}`} className="le-no" cx={p.x} cy={p.y} r={83} fill={`url(#${u("branco")})`}
                  style={{ "--i": i, "--dx": `${(p.x - CENTRO.x) * 0.9}px`, "--dy": `${(p.y - CENTRO.y) * 0.9}px` } as CSSProperties} />
        ))}
      </g>

      <g transform="translate(410 25)">
        {LETRAS.map((l, i) => (
          <g key={i} transform={`translate(${l.x} ${l.y})`}>
            <g className="le-letra" style={{ "--i": i } as CSSProperties}>
              <path className="le-letra-cheia" d={l.d} fill={`url(#${u(l.cor)})`} />
              <path className={`le-traco le-letra-traco le-${l.cor}`} d={l.d} pathLength={1} />
            </g>
          </g>
        ))}
      </g>

      {brilho && (
        <g clipPath={`url(#${u("recorte")})`}>
          <rect className="le-brilho" x={0} y={0} width={320} height={400} fill={`url(#${u("luz")})`} />
        </g>
      )}
    </svg>
  );
}
