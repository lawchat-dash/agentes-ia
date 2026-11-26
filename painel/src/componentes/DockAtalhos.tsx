// Atalhos do painel num Dock estilo macOS (React Bits): ampliação ao passar o mouse, rótulos, selo de contagem e
// menu de clique direito. Substitui o antigo menu circular flutuante (MenuFlutuante.tsx), com os mesmos atalhos e
// permissões. Fica no rodapé da área de conteúdo e se esconde sozinho: aparece quando o mouse chega perto da borda
// de baixo. No celular não aparece (lá o menu da gaveta já faz esse papel).
import { useLocation, useNavigate } from "react-router-dom";
import { AlertOctagon, BellRing, Bot, Building2, Home, Plus, PlugZap } from "lucide-react";
import Dock, { type DockItemData } from "@/components/reactbits/Dock";
import { useSessao } from "../sessao";
import "./dockAtalhos.css";

export function DockAtalhos({ errosAbertos = 0, impersonando = false }: { errosAbertos?: number; impersonando?: boolean }) {
  const { admin, lawchat, podeGerir, escritorio } = useSessao();
  const navegar = useNavigate();
  const { pathname } = useLocation();

  const itens: DockItemData[] = [];
  const atalho = (para: string, rotulo: string, icone: JSX.Element, extra: Partial<DockItemData> = {}) =>
    itens.push({ label: rotulo, icon: icone, onClick: () => navegar(para), active: para === "/" ? pathname === "/" : pathname.startsWith(para), ...extra });

  if (escritorio) {
    if (podeGerir) atalho("/biblioteca", "Criar agente", <Plus />, { className: "lc-dock-destaque" });
    atalho("/", "Início", <Home />);
    if (podeGerir) atalho("/agentes", "Agentes", <Bot />, {
      menu: [
        { label: "Meus agentes", icon: <Bot />, onClick: () => navegar("/agentes") },
        { label: "Criar a partir da Biblioteca", icon: <Plus />, onClick: () => navegar("/biblioteca") },
      ],
    });
    if (podeGerir) {
      // Erros só para a equipe LawChat na visão LawChat (na visão de cliente, nada de erros).
      if (lawchat && admin && !impersonando) atalho("/erros", "Erros", <AlertOctagon />, { badge: errosAbertos > 0 ? (errosAbertos > 99 ? "99+" : errosAbertos) : undefined });
      atalho("/integracoes", "Integrações", <PlugZap />);
      atalho("/avisos", "Avisos à equipe", <BellRing />);
    }
  }
  if (admin) {
    if (itens.length) itens.push({ separator: true });
    atalho("/admin/escritorios", "Escritórios", <Building2 />);
  }
  if (itens.length === 0) return null;

  return (
    <div className="lc-dock-host" aria-label="Atalhos">
      <Dock items={itens} theme="light" baseItemSize={44} magnification={60} distance={160} panelHeight={60} gap={8}
        autoHide accentColor="#00bc33" badgeColor="#00bc33" showLabels showIndicators showBadges />
    </div>
  );
}
