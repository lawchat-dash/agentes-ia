// Símbolo da LawChat animado, feito sobre a ARTE OFICIAL (assets/lawchat-icone.svg, a mesma das camadas Vector2/Vector3):
// o balão verde surge com mola e "acende" (um reflexo de luz passa por ele); a rede se monta: o anel gira e se fecha,
// as hastes crescem do anel para fora e as três bolinhas estalam no lugar; a sombra suave aparece e um pulso sai do
// anel. Com `loop`, depois disso o símbolo respira devagar e as bolinhas pulsam em sequência, com um pontinho verde
// correndo por cada haste (dados trafegando).
// Cada peça animada é um recorte do MESMO desenho oficial da rede (clip/máscara), então, pronto, o símbolo é idêntico
// à logo. Com prefers-reduced-motion: estático, só esmaece.
import { useEffect, useId, useRef, type CSSProperties } from "react";
import "./SimboloLawchat.css";

/** Duração da entrada (s), sem contar o atraso. */
export const DURACAO_SIMBOLO = 1.9;

// Arte oficial (coordenadas do lawchat-icone.svg, 395 x 407).
const BALAO =
  "M139.461 386.903C124.234 379.429 110.785 382.567 96.3836 389.129C81.5317 395.896 65.4514 400.069 49.7366 404.806C38.6987 408.134 29.975 404.847 24.0741 396.359C19.1206 389.234 19.5591 379.062 25.4697 370.411C27.7992 367.002 30.3731 363.687 33.2552 360.739C48.9565 344.68 64.4966 328.444 80.7079 312.911C88.0211 305.904 92.9883 298.569 94.8105 288.352C97.1645 275.153 101.088 262.234 103.216 248.498C80.5325 270.866 57.8493 293.233 33.8745 316.875C29.2199 309.503 24.6183 303.374 21.2167 296.638C1.18324 256.969 -4.01684 215.12 2.90266 171.388C8.80347 134.094 24.0295 101.344 50.2669 74.2631C81.5318 41.9937 119.494 22.7644 164.466 17.1897C241.514 7.63902 317.798 46.9405 352.698 115.486C369.364 148.219 376.375 183.064 372.825 219.876C365.418 296.704 324.755 349.745 255.15 380.161C218.314 396.257 179.156 396.929 139.461 386.903Z";
const REDE =
  "M226.688 281.758C239.473 292.041 243.907 311.343 237.48 326.936C225.736 355.43 191.993 356.156 175.224 339.44C156.777 321.051 160.859 290.832 185.056 278.88C186.939 277.95 187.293 277.08 187.077 275.205C186.2 267.588 185.335 259.964 184.76 252.32C184.55 249.533 183.534 248.494 180.805 248.065C168.575 246.145 158.466 240.426 151.037 230.413C143.683 220.502 141.12 209.232 142.397 197.084C142.649 194.686 142.055 193.622 139.847 192.796C132.184 189.928 124.565 186.937 116.99 183.844C115.361 183.179 114.344 183.409 113.331 184.693C98.5282 203.444 68.8099 201.651 54.7456 182.575C41.4333 164.519 46.3305 138.518 65.2914 126.634C80.0967 117.355 101.686 120.309 113.874 132.957C120.854 140.2 124.7 148.664 125.708 158.575C125.782 159.306 126.424 160.343 127.06 160.599C135.296 163.925 143.579 167.136 151.022 170.051C156.175 165.412 160.636 160.776 165.715 156.964C174.049 150.708 183.776 148.561 194.092 149.238C203.844 149.878 212.638 153.085 220.225 159.417C220.808 159.903 222.388 159.993 222.975 159.556C230.467 153.984 237.863 148.281 244.882 142.918C244.345 137.709 243.21 132.847 243.455 128.054C244.861 100.467 271.954 84.9074 296.488 94.8406C317.186 103.221 327.481 128.516 316.689 149.726C306.522 169.706 281.315 176.273 262.582 163.956C260.867 162.829 259.989 163.128 258.639 164.173C252.146 169.203 245.634 174.211 239.05 179.122C237.445 180.319 237.272 181.226 238.084 183.145C247.338 205.01 239.092 235.092 211.469 245.02C209.991 245.551 209.562 246.012 209.752 247.557C210.772 255.875 211.643 264.212 212.69 272.526C212.788 273.302 213.619 274.208 214.353 274.643C218.367 277.02 222.457 279.269 226.688 281.758ZM172.744 213.225C181.672 226.194 197.702 225.133 206.423 218.253C218.97 208.356 218.244 189.217 204.508 179.465C197.422 174.434 183.076 174.21 174.76 183.161C166.749 191.785 165.599 203.556 172.744 213.225Z";

/** Medidas tiradas do desenho oficial: anel (raio externo ~50, furo ~26) e as três bolinhas (raio ~41). */
const ANEL = { x: 192.74, y: 199.8, r: 50 };
const BOLINHAS = [
  { x: 84.33, y: 160.42, r: 41 },   // esquerda, em cima
  { x: 283.78, y: 130.41, r: 41 },  // direita, em cima
  { x: 203.69, y: 314.95, r: 41 },  // embaixo
];
/** Caixa quadrada em volta do balão (arte em x 0–374, y 16–406). */
const CAIXA = "-18 6 410 410";

function menosMovimento() {
  try { return window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch { return false; }
}

export default function SimboloLawchat({
  tamanho = 64, loop = true, aoTerminar, atraso = 0, x, y, decorativo = false, className = "",
}: {
  /** Lado em px (o símbolo é quadrado). Dentro de outro SVG, é em unidades desse SVG. */
  tamanho?: number;
  /** Depois da entrada, continua respirando e com as bolinhas pulsando. */
  loop?: boolean;
  /** Chamado quando a entrada termina. */
  aoTerminar?: () => void;
  /** Segundos antes de começar. */
  atraso?: number;
  /** Posição, quando usado dentro de outro <svg> (ex.: a logo com a escrita). */
  x?: number;
  y?: number;
  /** Sem rótulo de acessibilidade (quando o SVG de fora já diz "LawChat"). */
  decorativo?: boolean;
  className?: string;
}) {
  const id = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const u = (n: string) => `sl-${n}-${id}`;
  const terminar = useRef(aoTerminar);
  terminar.current = aoTerminar;

  useEffect(() => {
    const ms = (menosMovimento() ? 0.4 : atraso + DURACAO_SIMBOLO) * 1000;
    const t = window.setTimeout(() => terminar.current?.(), ms);
    return () => window.clearTimeout(t);
  }, [atraso]);

  // Hastes: do centro do anel até o centro de cada bolinha (só revelam o desenho oficial, não desenham por conta própria).
  const hastes = BOLINHAS.map((b) => `M ${ANEL.x} ${ANEL.y} L ${b.x} ${b.y}`);
  const origem = (ox: number, oy: number) => ({ "--ox": `${ox}px`, "--oy": `${oy}px` });

  return (
    <svg
      className={`sl-simbolo${loop ? " sl-loop" : ""} ${className}`.trim()}
      viewBox={CAIXA} x={x} y={y} width={tamanho} height={tamanho} overflow="visible"
      {...(decorativo ? { "aria-hidden": true } : { role: "img", "aria-label": "LawChat" })}
      style={{ "--sl-atraso": `${atraso}s` } as CSSProperties}
    >
      <defs>
        {/* Degradê e sombras exatamente como no arquivo oficial. */}
        <linearGradient id={u("verde")} x1="186.862" y1="15.7704" x2="186.666" y2="406.18" gradientUnits="userSpaceOnUse">
          <stop stopColor="#A7D7A4" /><stop offset="1" stopColor="#00BC33" />
        </linearGradient>
        <filter id={u("sombra-balao")} x="0" y="15.7704" width="373.725" height="390.315" filterUnits="userSpaceOnUse" colorInterpolationFilters="sRGB">
          <feFlood floodOpacity="0" result="fundo" />
          <feBlend mode="normal" in="SourceGraphic" in2="fundo" result="forma" />
          <feColorMatrix in="SourceAlpha" type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 127 0" result="alfa" />
          <feOffset />
          <feGaussianBlur stdDeviation="7.98371" />
          <feComposite in2="alfa" operator="arithmetic" k2="-1" k3="1" />
          <feColorMatrix type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0.5 0" />
          <feBlend mode="normal" in2="forma" />
        </filter>
        <filter id={u("sombra-rede")} x="10" y="60" width="350" height="340" filterUnits="userSpaceOnUse" colorInterpolationFilters="sRGB">
          <feFlood floodOpacity="0" result="fundo" />
          <feColorMatrix in="SourceAlpha" type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 127 0" result="alfa" />
          <feOffset dy="7.88515" />
          <feGaussianBlur stdDeviation="11.1378" />
          <feComposite in2="alfa" operator="out" />
          <feColorMatrix type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0.25 0" />
          <feBlend mode="normal" in2="fundo" result="queda" />
          <feBlend mode="normal" in="SourceGraphic" in2="queda" result="forma" />
          <feColorMatrix in="SourceAlpha" type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 127 0" result="alfa2" />
          <feOffset />
          <feGaussianBlur stdDeviation="7.98371" />
          <feComposite in2="alfa2" operator="arithmetic" k2="-1" k3="1" />
          <feColorMatrix type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0.2 0" />
          <feBlend mode="normal" in2="forma" />
        </filter>
        <linearGradient id={u("luz")} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#fff" stopOpacity="0" /><stop offset=".5" stopColor="#fff" stopOpacity=".5" /><stop offset="1" stopColor="#fff" stopOpacity="0" />
        </linearGradient>
        <clipPath id={u("balao")}><path d={BALAO} /></clipPath>
        <clipPath id={u("anel")}><circle cx={ANEL.x} cy={ANEL.y} r={ANEL.r + 6} /></clipPath>
        {BOLINHAS.map((b, i) => <clipPath key={i} id={u(`b${i}`)}><circle cx={b.x} cy={b.y} r={b.r + 3} /></clipPath>)}
        {/* Hastes: o traço branco cresce do anel para fora; anel e bolinhas ficam de fora (são peças próprias). */}
        <mask id={u("hastes")} maskUnits="userSpaceOnUse" x="-20" y="0" width="420" height="420">
          {hastes.map((d, i) => (
            <path key={i} className="sl-haste" style={{ "--i": i } as CSSProperties} d={d} pathLength={1}
                  stroke="#fff" strokeWidth={64} strokeLinecap="butt" fill="none" />
          ))}
          <circle cx={ANEL.x} cy={ANEL.y} r={ANEL.r + 4} fill="#000" />
          {BOLINHAS.map((b, i) => <circle key={i} cx={b.x} cy={b.y} r={b.r + 1} fill="#000" />)}
        </mask>
        {/* Anel: além de girar, ele "se fecha" (traço circular que revela o anel). */}
        <mask id={u("anel-fecha")} maskUnits="userSpaceOnUse" x="-20" y="0" width="420" height="420">
          <circle className="sl-anel-traco" cx={ANEL.x} cy={ANEL.y} r={38} pathLength={1} fill="none" stroke="#fff" strokeWidth={44}
                  transform={`rotate(-90 ${ANEL.x} ${ANEL.y})`} />
        </mask>
      </defs>

      <g className="sl-respiro">
        {/* Balão: surge com mola, acende (o véu escuro sai) e um reflexo passa por ele. */}
        <g className="sl-balao">
          <path d={BALAO} fill={`url(#${u("verde")})`} filter={`url(#${u("sombra-balao")})`} />
          <g clipPath={`url(#${u("balao")})`}>
            <path className="sl-veu" d={BALAO} fill="#06361A" />
            <g transform="rotate(18 187 211)">
              <rect className="sl-reflexo" x={-140} y={-120} width={130} height={680} fill={`url(#${u("luz")})`} />
            </g>
          </g>
        </g>

        {/* Pulso de sinal saindo do anel. */}
        <g clipPath={`url(#${u("balao")})`}>
          <circle className="sl-pulso" cx={ANEL.x} cy={ANEL.y} r={ANEL.r} fill="none" stroke="#fff" strokeWidth={4} />
        </g>

        {/* Rede: peças recortadas do desenho oficial, com a sombra do arquivo aplicada ao conjunto. */}
        <g className="sl-rede" filter={`url(#${u("sombra-rede")})`}>
          <g mask={`url(#${u("hastes")})`}><path d={REDE} fill="#fff" /></g>
          <g className="sl-anel-giro" style={origem(ANEL.x, ANEL.y) as CSSProperties}>
            <g mask={`url(#${u("anel-fecha")})`}>
              <g clipPath={`url(#${u("anel")})`}><path d={REDE} fill="#fff" /></g>
            </g>
          </g>
          {BOLINHAS.map((b, i) => {
            // Pontinho de "dado": da borda do anel até a borda da bolinha.
            const dx = b.x - ANEL.x, dy = b.y - ANEL.y, dist = Math.hypot(dx, dy);
            const ix = ANEL.x + (dx * ANEL.r) / dist, iy = ANEL.y + (dy * ANEL.r) / dist;
            const curso = (dist - ANEL.r - b.r) / dist;
            return (
              <circle key={`d${i}`} className="sl-dado" cx={ix} cy={iy} r={5.5} fill="#22C94F"
                      style={{ "--i": i, "--dx": `${dx * curso}px`, "--dy": `${dy * curso}px` } as CSSProperties} />
            );
          })}
          {BOLINHAS.map((b, i) => (
            <g key={`b${i}`} className="sl-bolinha" style={{ "--i": i, ...origem(b.x, b.y) } as CSSProperties}>
              <g className="sl-bolinha-forma" style={{ "--i": i, ...origem(b.x, b.y) } as CSSProperties}>
                <g clipPath={`url(#${u(`b${i}`)})`}><path d={REDE} fill="#fff" /></g>
              </g>
            </g>
          ))}
        </g>
      </g>
    </svg>
  );
}
