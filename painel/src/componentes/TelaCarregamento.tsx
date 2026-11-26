import { useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { useIsFetching } from "@tanstack/react-query";
import { useSessao } from "../sessao";
import { FundoVelaris } from "./FundoVelaris";
import { BALAO, CENTRO, LETRAS, PONTAS } from "./logoLawchatTracos";
import "./telaCarregamento.css";

/**
 * Tela de abertura do painel: fundo verde em movimento e a logo LawChat se desenhando (o balão e a rede se juntam,
 * depois cada letra é traçada e preenchida). Fica por cima do app enquanto ele carrega de verdade (ver
 * PortaoCarregamento) e sai com um esmaecer suave.
 */
type Fase = "sessao" | "tela" | "dados" | "pronto";

const TEXTO: Record<Fase, string> = {
  sessao: "Conectando com segurança…",
  tela: "Preparando seu painel…",
  dados: "Buscando suas informações…",
  pronto: "Tudo pronto",
};
const PROGRESSO: Record<Fase, number> = { sessao: 30, tela: 62, dados: 86, pronto: 100 };

function menosMovimento() {
  try { return window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch { return false; }
}

export function TelaCarregamento({ fase, saindo }: { fase: Fase; saindo: boolean }) {
  const parado = useMemo(menosMovimento, []);
  return (
    <div className={`tc-raiz${saindo ? " tc-saindo" : ""}${parado ? " tc-parado" : ""}`} role="status" aria-live="polite" aria-label="Carregando o painel">
      <div className="tc-fundo">
        <FundoVelaris parado={parado} />
        <div className="tc-veu" />
      </div>
      <div className="tc-palco">
        <LogoDesenhada />
        <div className="tc-rodape">
          <p className="tc-frase">{TEXTO[fase]}</p>
          <div className="tc-barra" aria-hidden>
            <span className="tc-barra-cheia" style={{ width: `${PROGRESSO[fase]}%` }} />
          </div>
        </div>
      </div>
    </div>
  );
}

function LogoDesenhada() {
  return (
    <svg className="tc-logo" viewBox="0 0 1959 400" role="img" aria-label="LawChat">
      <defs>
        <linearGradient id="tc-law" x1="0" y1="0" x2="0" y2="1"><stop stopColor="#A7D7A4" /><stop offset="1" stopColor="#00BC33" /></linearGradient>
        <linearGradient id="tc-chat" x1="0" y1="0" x2="0" y2="1"><stop stopColor="#FFFFFF" /><stop offset="1" stopColor="#E1E4E3" /></linearGradient>
        <linearGradient id="tc-verde" gradientUnits="userSpaceOnUse" x1="790" y1="75" x2="355" y2="920">
          <stop stopColor="#ACF8B6" /><stop offset=".36" stopColor="#42E963" /><stop offset=".72" stopColor="#0AD33D" /><stop offset="1" stopColor="#00B332" />
        </linearGradient>
        <linearGradient id="tc-branco" gradientUnits="userSpaceOnUse" x1="360" y1="245" x2="650" y2="805">
          <stop stopColor="#FFFFFF" /><stop offset=".48" stopColor="#F8F8F8" /><stop offset="1" stopColor="#D9DBDE" />
        </linearGradient>
        <linearGradient id="tc-luz" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#fff" stopOpacity="0" /><stop offset=".5" stopColor="#fff" stopOpacity=".55" /><stop offset="1" stopColor="#fff" stopOpacity="0" />
        </linearGradient>
        <clipPath id="tc-recorte">
          {LETRAS.map((l, i) => <path key={i} d={l.d} transform={`translate(${410 + l.x} ${25 + l.y})`} />)}
        </clipPath>
      </defs>

      {/* Ícone: o contorno do balão se desenha, enche de verde, e a rede se junta dentro dele. */}
      <g transform="translate(0 5) scale(.38)">
        <path className="tc-balao" d={BALAO} fill="url(#tc-verde)" />
        <path className="tc-traco tc-balao-traco" d={BALAO} pathLength={1} />
        <g className="tc-rede">
          {PONTAS.map((p, i) => (
            <path key={`l${i}`} className="tc-linha" style={{ "--i": i } as CSSProperties}
              d={`M ${CENTRO.x} ${CENTRO.y} L ${p.x} ${p.y}`} pathLength={1} stroke="url(#tc-branco)" strokeWidth={49} strokeLinecap="round" fill="none" />
          ))}
          <circle className="tc-anel" cx={CENTRO.x} cy={CENTRO.y} r={87.5} pathLength={1} fill="none" stroke="url(#tc-branco)" strokeWidth={45} />
          {PONTAS.map((p, i) => (
            <circle key={`n${i}`} className="tc-no" cx={p.x} cy={p.y} r={83} fill="url(#tc-branco)"
              style={{ "--i": i, "--dx": `${(p.x - CENTRO.x) * 0.9}px`, "--dy": `${(p.y - CENTRO.y) * 0.9}px` } as CSSProperties} />
          ))}
        </g>
      </g>

      {/* Escrita: cada letra é traçada e depois preenchida, uma após a outra. */}
      <g transform="translate(410 25)">
        {LETRAS.map((l, i) => (
          <g key={i} transform={`translate(${l.x} ${l.y})`}>
            <g className="tc-letra" style={{ "--i": i } as CSSProperties}>
              <path className="tc-letra-cheia" d={l.d} fill={`url(#tc-${l.cor})`} />
              <path className={`tc-traco tc-letra-traco tc-${l.cor}`} d={l.d} pathLength={1} />
            </g>
          </g>
        ))}
      </g>

      {/* Brilho que passa pela escrita depois de pronta (repete enquanto o painel termina de carregar). */}
      <g clipPath="url(#tc-recorte)">
        <rect className="tc-brilho" x={0} y={0} width={320} height={400} fill="url(#tc-luz)" />
      </g>
    </svg>
  );
}

// ---------------------------------------------------------------------------------------------------------------
// Ligação com o carregamento real
// ---------------------------------------------------------------------------------------------------------------

const MINIMO_MS = 2000;     // tempo para a logo terminar de se desenhar
const MAXIMO_MS = 9000;     // nunca prende a pessoa: passou disso, sai e deixa o app mostrar o que tiver
const SAIDA_MS = 650;

/** Arquivo da primeira tela que a pessoa vai ver (o mesmo que o React.lazy de main.tsx baixa). */
function baixarPrimeiraTela(caminho: string): Promise<unknown> {
  const telas: [RegExp, () => Promise<unknown>][] = [
    [/^\/$/, () => import("../telas/Inicio")],
    [/^\/conversas/, () => import("../telas/Conversas")],
    [/^\/(minha-conta|crm|atendimento|chatbots)/, () => import("../telas/MinhaConta")],
    [/^\/meus-produtos\/./, () => import("@/pages/ProdutoEditor")],
    [/^\/meus-produtos/, () => import("@/pages/MeusProdutos")],
    [/^\/relatorios\/campanhas/, () => import("../telas/RelatorioCampanhas")],
    [/^\/relatorios/, () => import("../telas/RelatorioDashboard")],
    [/^\/consumo/, () => import("../telas/Creditos")],
    [/^\/agentes/, () => import("../telas/Agente")],
    [/^\/biblioteca\/./, () => import("@/pages/BibliotecaDetalhes")],
    [/^\/biblioteca/, () => import("@/pages/Biblioteca")],
    [/^\/ferramentas$/, () => import("../telas/Ferramentas")],
    [/^\/configuracoes/, () => import("../telas/Configuracoes")],
    [/^\/integracoes/, () => import("../telas/Integracoes")],
    [/^\/admin\/escritorios/, () => import("../telas/AdminEscritorios")],
  ];
  const achada = telas.find(([re]) => re.test(caminho));
  const fontes = (document as Document & { fonts?: { ready: Promise<unknown> } }).fonts?.ready ?? Promise.resolve();
  return Promise.all([achada ? achada[1]() : Promise.resolve(), fontes]);
}

/**
 * Mostra a TelaCarregamento por cima do app ao abrir o painel e logo depois do login (não nas trocas de tela).
 * O app carrega por baixo ao mesmo tempo; a tela sai quando: a sessão (/eu e /catalogo) respondeu, o arquivo da
 * primeira tela chegou e as consultas iniciais (React Query) terminaram, respeitando um tempo mínimo para a
 * animação. Se algo der erro, sai do mesmo jeito e o app mostra o erro como sempre.
 * Em desenvolvimento, `?splash=1` na URL deixa a tela fixa (para ver a animação sem entrar).
 */
export function PortaoCarregamento({ children }: { children: ReactNode }) {
  const { eu, carregando } = useSessao();
  const buscando = useIsFetching();
  const fixa = useMemo(() => import.meta.env.DEV && new URLSearchParams(window.location.search).has("splash"), []);

  const [ciclo, setCiclo] = useState(0);
  const [visivel, setVisivel] = useState(true);
  const [saindo, setSaindo] = useState(false);
  const [minimoOk, setMinimoOk] = useState(false);
  const [telaPronta, setTelaPronta] = useState(false);
  const [dadosOk, setDadosOk] = useState(false);
  const [estourou, setEstourou] = useState(false);
  const euAntes = useRef<boolean | null>(null);

  // Começo de cada abertura: zera e conta o tempo mínimo e o máximo.
  useEffect(() => {
    if (!visivel) return;
    setMinimoOk(false); setTelaPronta(false); setDadosOk(false); setEstourou(false); setSaindo(false);
    const minimo = window.setTimeout(() => setMinimoOk(true), menosMovimento() ? 600 : MINIMO_MS);
    const maximo = window.setTimeout(() => setEstourou(true), MAXIMO_MS);
    return () => { window.clearTimeout(minimo); window.clearTimeout(maximo); };
  }, [ciclo, visivel]);

  // Sessão respondeu: baixa a primeira tela (ou, sem login, a tela de entrar já está no pacote principal).
  useEffect(() => {
    if (!visivel || carregando || telaPronta) return;
    if (!eu) { setTelaPronta(true); return; }
    let vivo = true;
    baixarPrimeiraTela(window.location.pathname).catch(() => undefined).finally(() => { if (vivo) setTelaPronta(true); });
    return () => { vivo = false; };
  }, [visivel, carregando, eu, telaPronta, ciclo]);

  // Consultas iniciais: espera ficarem paradas um instante (a tela recém-montada dispara as dela logo em seguida).
  useEffect(() => {
    if (!visivel || !telaPronta || dadosOk || buscando > 0) return;
    const t = window.setTimeout(() => setDadosOk(true), eu ? 350 : 0);
    return () => window.clearTimeout(t);
  }, [visivel, telaPronta, dadosOk, buscando, eu]);

  // Hora de sair.
  useEffect(() => {
    if (!visivel || saindo || fixa) return;
    if ((minimoOk && dadosOk) || estourou) setSaindo(true);
  }, [visivel, saindo, fixa, minimoOk, dadosOk, estourou]);
  useEffect(() => {
    if (!saindo) return;
    const t = window.setTimeout(() => setVisivel(false), SAIDA_MS);
    return () => window.clearTimeout(t);
  }, [saindo]);

  // Acabou de entrar (estava sem login e agora tem): mostra a abertura de novo (antes de pintar, sem piscar o app).
  useLayoutEffect(() => {
    if (carregando) return;
    const tem = Boolean(eu);
    if (euAntes.current === false && tem && !visivel) { setVisivel(true); setCiclo((c) => c + 1); }
    euAntes.current = tem;
  }, [eu, carregando, visivel]);

  const fase: Fase = carregando ? "sessao" : !telaPronta ? "tela" : !dadosOk ? "dados" : "pronto";
  return (
    <>
      {children}
      {visivel && <TelaCarregamento key={ciclo} fase={fixa ? "tela" : fase} saindo={saindo} />}
    </>
  );
}
