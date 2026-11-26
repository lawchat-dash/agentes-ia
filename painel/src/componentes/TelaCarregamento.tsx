import { useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore, type CSSProperties, type ReactNode } from "react";
import { useIsFetching } from "@tanstack/react-query";
import { assinarEsperas, esperasSemDado } from "../api";
import { preCarregar } from "../preCarga";
import { useSessao } from "../sessao";
import { FundoVelaris } from "./FundoVelaris";
import { BALAO, CENTRO, LETRAS, PONTAS } from "./logoLawchatTracos";
import SimboloLawchat from "@/components/marca/SimboloLawchat";
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

/** `deCara`: aberta já no carregamento da página (reabrir logado) — sem o esmaecer de entrada, para a carga de entrada
 * que fica por baixo não aparecer através dela. */
export function TelaCarregamento({ fase, saindo, deCara = false }: { fase: Fase; saindo: boolean; deCara?: boolean }) {
  const parado = useMemo(menosMovimento, []);
  return (
    <div className={`tc-raiz${saindo ? " tc-saindo" : ""}${parado ? " tc-parado" : ""}${deCara ? " tc-de-cara" : ""}`} role="status" aria-live="polite" aria-label="Carregando o painel">
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

      {/* Ícone: símbolo animado (balão + rede), na mesma posição e escala de antes; respira enquanto carrega. */}
      <SimboloLawchat decorativo x={19.3} y={15.5} tamanho={357} />

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
 * Mostra a TelaCarregamento por cima do app logo depois do login e ao reabrir o painel já logado (não nas trocas de
 * tela, e nunca para quem não está logado: esse vai direto para a tela de entrar).
 * O app carrega por baixo ao mesmo tempo; a tela sai quando: a sessão (/eu e /catalogo) respondeu, o arquivo da
 * primeira tela chegou, a pré-carga (preCarga.ts: dados da tela da URL e da moldura) chegou e nenhuma tela está
 * esperando um dado que ainda não tem cópia (useCarregar ou React Query), respeitando um tempo mínimo para a animação.
 * O que já tem cópia guardada (cachePersistente.ts) aparece na hora e é conferido por trás, sem segurar a abertura.
 * Passou do máximo, sai do mesmo jeito e a tela mostra o que tiver. Se algo der erro, o app mostra o erro como sempre.
 * Em desenvolvimento, `?splash=1` na URL deixa a tela fixa (para ver a animação sem entrar).
 */
/**
 * Marca "esta aba/navegador estava logado" (só um sinal, sem dado nenhum). Com ela, reabrir o painel (F5, aba nova) já
 * começa na abertura enquanto a sessão confere; sem ela, quem não está logado vai direto para a tela de entrar, sem
 * animação (a carga de entrada antiga, CarregandoEntrada, cobre a conferência da sessão).
 */
const MARCA_SESSAO = "agentesia_sessao_ativa";
function estavaLogado(): boolean {
  try { return localStorage.getItem(MARCA_SESSAO) === "1"; } catch { return false; }
}
function marcarLogado(sim: boolean): void {
  try { if (sim) localStorage.setItem(MARCA_SESSAO, "1"); else localStorage.removeItem(MARCA_SESSAO); } catch { /* sem armazenamento */ }
}
window.addEventListener("agentesia:sair", () => marcarLogado(false));

export function PortaoCarregamento({ children }: { children: ReactNode }) {
  const { eu, carregando, escritorio, podeGerir, lawchat, admin } = useSessao();
  // Só conta consulta do React Query que ainda não tem dado nenhum (com cópia, a tela já aparece pronta).
  const buscando = useIsFetching({ predicate: (q) => q.state.data === undefined });
  const esperas = useSyncExternalStore(assinarEsperas, esperasSemDado);
  const fixa = useMemo(() => import.meta.env.DEV && new URLSearchParams(window.location.search).has("splash"), []);

  const [ciclo, setCiclo] = useState(0);
  // Só abre de cara se a pessoa estava logada (reabrir); sem login, nada de abertura.
  const [visivel, setVisivel] = useState(() => fixa || estavaLogado());
  const [saindo, setSaindo] = useState(false);
  const [minimoOk, setMinimoOk] = useState(false);
  const [telaPronta, setTelaPronta] = useState(false);
  const [preCargaOk, setPreCargaOk] = useState(false);
  const [dadosOk, setDadosOk] = useState(false);
  const [estourou, setEstourou] = useState(false);
  const euAntes = useRef<boolean | null>(null);

  // Começo de cada abertura: zera e conta o tempo mínimo e o máximo.
  useEffect(() => {
    if (!visivel) return;
    setMinimoOk(false); setTelaPronta(false); setPreCargaOk(false); setDadosOk(false); setEstourou(false); setSaindo(false);
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

  // Ao mesmo tempo, os dados da tela da URL e da moldura (pré-carga, uma vez por abertura).
  useEffect(() => {
    if (!visivel || carregando) return;
    if (!eu) { setPreCargaOk(true); return; }
    let vivo = true;
    preCarregar(window.location.pathname, { escritorio, podeGerir, lawchat, admin }).finally(() => { if (vivo) setPreCargaOk(true); });
    return () => { vivo = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visivel, carregando, Boolean(eu), ciclo]);

  // Dados: pré-carga pronta e nenhuma tela esperando dado sem cópia, parado um instante (a tela recém-montada e as
  // partes que só aparecem depois do primeiro dado disparam as delas logo em seguida).
  useEffect(() => {
    if (!visivel || !telaPronta || !preCargaOk || dadosOk || buscando > 0 || esperas > 0) return;
    const t = window.setTimeout(() => setDadosOk(true), eu ? 350 : 0);
    return () => window.clearTimeout(t);
  }, [visivel, telaPronta, preCargaOk, dadosOk, buscando, esperas, eu]);

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
  // Sessão confirmada (acabou de entrar, ou reabriu logado sem a marca): mostra a abertura enquanto os dados iniciais
  // chegam, antes de pintar (da carga de entrada direto para a abertura, sem piscar o app). Sem sessão: some na hora e
  // a tela de entrar aparece, sem animação.
  useLayoutEffect(() => {
    if (carregando) return;
    const tem = Boolean(eu);
    marcarLogado(tem);
    if (tem && euAntes.current !== true && !visivel) { setVisivel(true); setCiclo((c) => c + 1); }
    if (!tem && visivel && !fixa) { setVisivel(false); setSaindo(false); }
    euAntes.current = tem;
  }, [eu, carregando, visivel, fixa]);

  const fase: Fase = carregando ? "sessao" : !telaPronta ? "tela" : !dadosOk ? "dados" : "pronto";
  return (
    <>
      {children}
      {visivel && <TelaCarregamento key={ciclo} fase={fixa ? "tela" : fase} saindo={saindo} deCara={ciclo === 0} />}
    </>
  );
}
