import { Navigate } from "react-router-dom";

/**
 * A lista de agentes virou "Meus agentes" (pages/MeusProdutos.tsx): um só caminho no menu, com o
 * "+ Novo a partir da Biblioteca" e, em cada cartão, as abas do agente (Prompt, Follow-up, Conhecimento, Laboratório).
 * Quem chega em /agentes (link antigo, favorito) vai para lá. O agente aberto continua em /agentes/:id/:secao.
 */
export function TelaAgentes() {
  return <Navigate to="/meus-produtos" replace />;
}
