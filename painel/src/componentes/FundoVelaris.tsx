import { useEffect, useRef, useState } from "react";

/**
 * Fundo "Velaris": ruído verde que se move devagar (WebGL), com vinheta, brilho no centro e um pouco de grão.
 * Sem WebGL (ou se o shader falhar) o canvas some e fica só o gradiente CSS do contêiner (.tc-fundo).
 * `parado`: desenha um quadro só (para quem pediu menos movimento no sistema).
 */
const VERTICE = `
attribute vec2 position;
varying vec2 vUv;
void main() { vUv = position * 0.5 + 0.5; gl_Position = vec4(position, 0.0, 1.0); }`;

const FRAGMENTO = `
precision highp float;
varying vec2 vUv;
uniform float u_time;
uniform vec2 u_res;
uniform vec3 u_bg;
uniform vec3 u_c0;
uniform vec3 u_c1;
uniform vec3 u_c2;
uniform vec3 u_c3;
uniform float u_grain;

vec3 permute(vec3 x) { return mod(((x * 34.0) + 1.0) * x, 289.0); }
float snoise(vec2 v) {
  const vec4 C = vec4(0.211324865405187, 0.366025403784439, -0.577350269189626, 0.024390243902439);
  vec2 i = floor(v + dot(v, C.yy));
  vec2 x0 = v - i + dot(i, C.xx);
  vec2 i1 = (x0.x > x0.y) ? vec2(1.0, 0.0) : vec2(0.0, 1.0);
  vec4 x12 = x0.xyxy + C.xxzz;
  x12.xy -= i1;
  i = mod(i, 289.0);
  vec3 p = permute(permute(i.y + vec3(0.0, i1.y, 1.0)) + i.x + vec3(0.0, i1.x, 1.0));
  vec3 m = max(0.5 - vec3(dot(x0, x0), dot(x12.xy, x12.xy), dot(x12.zw, x12.zw)), 0.0);
  m = m * m; m = m * m;
  vec3 x = 2.0 * fract(p * C.www) - 1.0;
  vec3 h = abs(x) - 0.5;
  vec3 ox = floor(x + 0.5);
  vec3 a0 = x - ox;
  m *= 1.79284291400159 - 0.85373472095314 * (a0 * a0 + h * h);
  vec3 g;
  g.x = a0.x * x0.x + h.x * x0.y;
  g.yz = a0.yz * x12.xz + h.yz * x12.yw;
  return 130.0 * dot(m, g);
}

void main() {
  vec2 uv = vUv;
  vec2 p = uv - 0.5;
  p.x *= u_res.x / u_res.y;
  float t = u_time * 0.1;
  float n1 = snoise(p * 0.4 + vec2(t * 0.2, -t * 0.3));
  float n2 = snoise(p * 0.55 + vec2(-t * 0.15, t * 0.25) + n1 * 0.25);
  float n3 = snoise(p * 0.75 + vec2(t * 0.1, -t * 0.2) + n2 * 0.2);
  vec3 col = u_bg;
  float dist = length(p) * 1.5;
  float vignette = 1.0 - smoothstep(0.3, 1.2, dist);
  col = mix(col, u_c0, smoothstep(-0.2, 0.5, n1) * 0.85);
  col = mix(col, u_c1, smoothstep(-0.1, 0.6, n2) * 0.7);
  col = mix(col, u_c2, smoothstep(-0.3, 0.4, n3) * 0.6);
  col = mix(col, u_c3, smoothstep(0.0, 0.7, n1 * n2) * 0.5);
  col += u_c1 * smoothstep(0.8, 0.0, dist) * 0.3;
  col = mix(col * 0.2, col, vignette);
  float grain = fract(sin(dot(uv, vec2(12.9898, 78.233))) * 43758.5453 + u_time);
  col += (grain - 0.5) * u_grain * 0.1;
  gl_FragColor = vec4(col, 1.0);
}`;

function rgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  const n = parseInt(h.length === 3 ? h.split("").map((c) => c + c).join("") : h, 16);
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
}

interface Props {
  fundo?: string;
  cores?: [string, string, string, string];
  velocidade?: number;
  grao?: number;
  parado?: boolean;
}

export function FundoVelaris({
  fundo = "#010a05",
  cores = ["#0a4a22", "#0a7a30", "#04301a", "#010a05"],
  velocidade = 2,
  grao = 0.3,
  parado = false,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [semWebgl, setSemWebgl] = useState(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let gl: WebGLRenderingContext | null = null;
    try { gl = canvas.getContext("webgl", { antialias: false, premultipliedAlpha: false }) as WebGLRenderingContext | null; } catch { gl = null; }
    if (!gl) { setSemWebgl(true); return; }

    const compilar = (tipo: number, fonte: string) => {
      const s = gl!.createShader(tipo)!;
      gl!.shaderSource(s, fonte);
      gl!.compileShader(s);
      return gl!.getShaderParameter(s, gl!.COMPILE_STATUS) ? s : null;
    };
    const vs = compilar(gl.VERTEX_SHADER, VERTICE);
    const fs = compilar(gl.FRAGMENT_SHADER, FRAGMENTO);
    const prog = gl.createProgram();
    if (!vs || !fs || !prog) { setSemWebgl(true); return; }
    gl.attachShader(prog, vs);
    gl.attachShader(prog, fs);
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) { setSemWebgl(true); return; }
    gl.useProgram(prog);

    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const pos = gl.getAttribLocation(prog, "position");
    gl.enableVertexAttribArray(pos);
    gl.vertexAttribPointer(pos, 2, gl.FLOAT, false, 0, 0);

    const u = (n: string) => gl!.getUniformLocation(prog, n);
    const uTempo = u("u_time"), uRes = u("u_res");
    gl.uniform3fv(u("u_bg"), rgb(fundo));
    cores.forEach((c, i) => gl!.uniform3fv(u(`u_c${i}`), rgb(c)));
    gl.uniform1f(u("u_grain"), grao);

    const ajustar = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = Math.max(1, Math.floor(canvas.clientWidth * dpr));
      const h = Math.max(1, Math.floor(canvas.clientHeight * dpr));
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
      gl!.viewport(0, 0, w, h);
      gl!.uniform2f(uRes, w, h);
    };
    const desenhar = (ms: number) => {
      ajustar();
      gl!.uniform1f(uTempo, ms * 0.001 * velocidade);
      gl!.drawArrays(gl!.TRIANGLE_STRIP, 0, 4);
    };

    let quadro = 0;
    const inicio = performance.now();
    const laco = (agora: number) => { desenhar(agora - inicio + 4000); quadro = requestAnimationFrame(laco); };
    if (parado) desenhar(4000); else quadro = requestAnimationFrame(laco);
    const obs = new ResizeObserver(() => { if (parado) desenhar(4000); });
    obs.observe(canvas);

    return () => {
      cancelAnimationFrame(quadro);
      obs.disconnect();
      gl!.deleteBuffer(buf);
      gl!.deleteProgram(prog);
      gl!.deleteShader(vs);
      gl!.deleteShader(fs);
    };
    // As cores e a velocidade são fixas durante a vida da tela.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [parado]);

  return <canvas ref={canvasRef} className="tc-canvas" aria-hidden style={semWebgl ? { display: "none" } : undefined} />;
}
