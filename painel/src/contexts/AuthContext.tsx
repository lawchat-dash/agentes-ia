/**
 * Ponte para as telas copiadas do agents-lawchat-main: o `useAuth()` de lá vira a nossa sessão.
 * workspace = escritório em uso; user = usuário logado. Não há Supabase aqui: os dados vêm da API do painel.
 *
 * Os objetos são memorizados: as telas de lá têm efeitos que dependem de `workspace`/`user`, e um objeto
 * novo a cada render fazia esses efeitos rodarem sem parar (consultas em laço).
 */
import { ReactNode, useMemo } from "react";
import { useSessao } from "@/sessao";

export interface Workspace {
  id: string;
  idCliente: string | null;
  name: string;
  plan: string;
  credits: number;
  timezone: string;
  logo_url: string | null;
}

export interface Usuario {
  id: string;
  email: string;
  user_metadata: { nome?: string };
}

export const AuthProvider = ({ children }: { children: ReactNode }) => <>{children}</>;

export const useAuth = () => {
  const { eu, escritorio, catalogo, admin, lawchat, carregando, sair } = useSessao() as any;
  const nomeEscritorio: string =
    (catalogo?.escritorios ?? []).find?.((e: any) => e.id === escritorio)?.nome ?? eu?.nome_escritorio ?? "";
  const workspace = useMemo<Workspace | null>(
    () => (escritorio
      ? { id: escritorio, idCliente: escritorio, name: nomeEscritorio, plan: "enterprise", credits: 0, timezone: "America/Sao_Paulo", logo_url: null }
      : null),
    [escritorio, nomeEscritorio],
  );
  const user = useMemo<Usuario | null>(
    () => (eu ? { id: eu.id, email: eu.email, user_metadata: { nome: eu.nome } } : null),
    [eu?.id, eu?.email, eu?.nome],
  );
  const session = useMemo(() => (user ? { user } : null), [user]);
  return { user, session, workspace, loading: !!carregando, signOut: sair, isAdmin: !!admin, isLawchat: !!lawchat };
};
