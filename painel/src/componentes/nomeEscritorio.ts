import { createContext, type ReactNode } from "react";

/** Nome do escritório em uso, para telas que ficam fora da moldura (Central de Atendimento). */
export const NomeDoEscritorio = createContext<string>("");

/** Última tela do painel antes de abrir a Central. O "voltar" do navegador não serve: o que se clica dentro da
 *  Central também entra no histórico, e voltar só recuaria lá dentro. */
let ultimaTelaDoPainel = "/";
export const guardarTelaDoPainel = (caminho: string) => { ultimaTelaDoPainel = caminho || "/"; };
export const telaDoPainel = () => ultimaTelaDoPainel;

/** Busca, avisos, Admin, ajuda e foto (as ações da barra do topo), para as telas em tela cheia (Minha Conta). */
export const AcoesDoTopo = createContext<ReactNode>(null);
