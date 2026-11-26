import { useEffect, useRef, useState, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { AlertOctagon, BellRing, Bot, Building2, Home, Plus, PlugZap, X } from "lucide-react";
import { useSessao } from "../sessao";

interface Atalho { para: string; rotulo: string; icone: ReactNode; destaque?: boolean }

/** Botão redondo flutuante que abre os atalhos em arco (como um menu radial). Fecha com Esc ou clique fora. */
export function MenuFlutuante() {
  const { admin, podeGerir, escritorio } = useSessao();
  const navegar = useNavigate();
  const { pathname } = useLocation();
  const [aberto, setAberto] = useState(false);
  const raiz = useRef<HTMLDivElement>(null);

  useEffect(() => { setAberto(false); }, [pathname]);
  useEffect(() => {
    if (!aberto) return;
    const tecla = (e: KeyboardEvent) => e.key === "Escape" && setAberto(false);
    const fora = (e: MouseEvent) => raiz.current && !raiz.current.contains(e.target as Node) && setAberto(false);
    window.addEventListener("keydown", tecla);
    window.addEventListener("mousedown", fora);
    return () => { window.removeEventListener("keydown", tecla); window.removeEventListener("mousedown", fora); };
  }, [aberto]);

  const atalhos: Atalho[] = [];
  if (escritorio) {
    if (podeGerir) atalhos.push({ para: "/biblioteca", rotulo: "Criar agente", icone: <Plus />, destaque: true });
    atalhos.push({ para: "/", rotulo: "Início", icone: <Home /> });
    if (podeGerir) atalhos.push({ para: "/agentes", rotulo: "Agentes", icone: <Bot /> });
    if (podeGerir) {
      atalhos.push({ para: "/erros", rotulo: "Erros", icone: <AlertOctagon /> });
      atalhos.push({ para: "/integracoes", rotulo: "Integrações", icone: <PlugZap /> });
      atalhos.push({ para: "/avisos", rotulo: "Avisos à equipe", icone: <BellRing /> });
    }
  }
  if (admin) atalhos.push({ para: "/admin/escritorios", rotulo: "Escritórios", icone: <Building2 /> });
  if (atalhos.length === 0) return null;

  // Arco de 90° (do topo para a esquerda), com raio que cresce se houver muitos atalhos.
  // ~54 px entre os centros dos botões (44 px cada) ao longo do arco: nada se sobrepõe.
  const raio = Math.max(96, Math.round((54 * (atalhos.length - 1)) / (Math.PI / 2)));
  const posicao = (i: number) => {
    const angulo = (Math.PI / 2) * (atalhos.length === 1 ? 0.5 : i / (atalhos.length - 1));
    return { x: -Math.cos(angulo) * raio, y: -Math.sin(angulo) * raio };
  };

  return (
    <div ref={raiz} className={`fab ${aberto ? "aberto" : ""}`}>
      <div className="fab-fundo" aria-hidden onClick={() => setAberto(false)} />
      <nav className="fab-itens" aria-label="Atalhos" aria-hidden={!aberto}>
        {atalhos.map((a, i) => {
          const { x, y } = posicao(i);
          return (
            <button key={a.para} type="button" tabIndex={aberto ? 0 : -1}
              className={`fab-item ${a.destaque ? "destaque" : ""} ${pathname === a.para ? "atual" : ""}`}
              style={{ ["--x" as string]: `${x}px`, ["--y" as string]: `${y}px`, ["--atraso" as string]: `${i * 35}ms` }}
              onClick={() => navegar(a.para)} aria-label={a.rotulo}>
              {a.icone}<span className="fab-rotulo">{a.rotulo}</span>
            </button>
          );
        })}
      </nav>
      <button type="button" className="fab-botao" onClick={() => setAberto(!aberto)}
        aria-expanded={aberto} aria-label={aberto ? "Fechar atalhos" : "Abrir atalhos"}>
        {aberto ? <X /> : <Plus />}
      </button>
    </div>
  );
}
