import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { PAPEIS_LAWCHAT, api, ativarCacheDoUsuario, escolherEscritorio, escolherVisao, escritorioEscolhido, visaoEscolhida, type Catalogo, type Eu, type Visao } from "./api";

interface Sessao {
  eu: Eu | null;
  catalogo: Catalogo | null;
  carregando: boolean;
  admin: boolean;                          // vale para a tela: LawChat olhando como LawChat
  podeGerir: boolean;
  lawchat: boolean;                        // a pessoa é da LawChat (dono ou equipe), qualquer que seja a visão
  dono: boolean;                           // dono da LawChat (cuida da equipe)
  visao: Visao;                            // como a LawChat está olhando o escritório
  trocarVisao: (v: Visao) => void;
  escritorio: string | null;               // escritório em uso (admin escolhe; os outros têm o seu)
  escritorioLawchat: string | null;        // a conta da própria LawChat (para onde "Voltar para a conta" leva)
  trocarEscritorio: (id: string | null) => void;
  recarregar: () => Promise<void>;
  sair: () => Promise<void>;
}

const Contexto = createContext<Sessao | null>(null);

export function ProvedorSessao({ children }: { children: ReactNode }) {
  const [eu, setEu] = useState<Eu | null>(null);
  const [catalogo, setCatalogo] = useState<Catalogo | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [escritorio, setEscritorio] = useState<string | null>(null);
  const [visao, setVisao] = useState<Visao>(visaoEscolhida());

  const recarregar = useCallback(async () => {
    // Quem entrou pela LawChat como equipe LawChat chega com ?escritorio=... na URL.
    const daUrl = new URLSearchParams(window.location.search).get("escritorio");
    if (daUrl) {
      escolherEscritorio(daUrl);
      window.history.replaceState(null, "", window.location.pathname);
    }
    try {
      const [usuario, cat] = await Promise.all([api<Eu>("/eu"), api<Catalogo>("/catalogo")]);
      // Antes de as telas abrirem: põe na memória as respostas guardadas DESTE usuário (abrem na hora, sem esqueleto).
      ativarCacheDoUsuario(usuario.id);
      setEu(usuario);
      setCatalogo(cat);
      // Equipe LawChat: sem escritório escolhido, abre na própria conta LawChat.
      setEscritorio(PAPEIS_LAWCHAT.includes(usuario.papel) ? (escritorioEscolhido() ?? usuario.escritorio_lawchat ?? null) : usuario.id_escritorio);
    } catch {
      setEu(null);
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => {
    recarregar();
    const aoSair = () => setEu(null);
    window.addEventListener("agentesia:sair", aoSair);
    return () => window.removeEventListener("agentesia:sair", aoSair);
  }, [recarregar]);

  const trocarEscritorio = useCallback((id: string | null) => {
    escolherEscritorio(id);
    setEscritorio(id);
    if (!id) { escolherVisao("lawchat"); setVisao("lawchat"); }
  }, []);

  const trocarVisao = useCallback((v: Visao) => {
    escolherVisao(v);
    setVisao(v);
  }, []);

  const sair = useCallback(async () => {
    await api("/sair", { metodo: "POST" }).catch(() => undefined);
    // Avisa todo o painel (cópias guardadas na memória, no navegador e no React Query são apagadas).
    window.dispatchEvent(new Event("agentesia:sair"));
    escolherEscritorio(null);
    escolherVisao("lawchat");
    setVisao("lawchat");
    setEu(null);
  }, []);

  const lawchat = Boolean(eu && PAPEIS_LAWCHAT.includes(eu.papel));
  // A visão do cliente só vale dentro de um escritório.
  const visaoAtual: Visao = lawchat && escritorio ? visao : "lawchat";
  const papel = lawchat ? (visaoAtual === "lawchat" ? "lawchat" : visaoAtual) : eu?.papel;
  const admin = papel === "lawchat";
  return (
    <Contexto.Provider value={{
      eu, catalogo, carregando, admin, podeGerir: admin || papel === "gestor",
      lawchat, dono: eu?.papel === "dono_lawchat", visao: visaoAtual, trocarVisao,
      escritorio, escritorioLawchat: eu?.escritorio_lawchat ?? null, trocarEscritorio, recarregar, sair,
    }}>
      {children}
    </Contexto.Provider>
  );
}

export function useSessao(): Sessao {
  const valor = useContext(Contexto);
  if (!valor) throw new Error("useSessao fora do ProvedorSessao");
  return valor;
}
