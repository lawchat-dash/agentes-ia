import { StrictMode, Suspense, lazy, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import "./index.css";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import "./estilo.css";
import "./estilo-navegacao.css";

// Depois de um deploy, uma aba aberta antes ainda pede os arquivos da versão antiga (que não existem mais) ao abrir
// uma tela: a página ficava em branco. Quando isso acontece, recarrega uma vez para pegar a versão nova.
function recarregarParaVersaoNova() {
  try {
    const ultima = Number(sessionStorage.getItem("agentesia_recarga_versao") || 0);
    if (Date.now() - ultima < 30_000) return false;
    sessionStorage.setItem("agentesia_recarga_versao", String(Date.now()));
  } catch { /* sem sessionStorage: recarrega mesmo assim */ }
  window.location.reload();
  return true;
}
window.addEventListener("vite:preloadError", (e) => { if (recarregarParaVersaoNova()) e.preventDefault(); });
import { enviar } from "./api";
import { Estrutura } from "./componentes/Estrutura";
import { Alerta, Carregando, Modal, ProvedorAvisos, useAcao } from "./componentes/ui";
import { ProvedorSessao, useSessao } from "./sessao";
import { CarregandoEntrada, Entrar } from "./telas/Entrar";
// Cada tela vira um arquivo JS próprio, baixado só quando a pessoa abre a tela (antes era um bundle único de ~2,5 MB).
const TelaAdminEscritorios = lazy(() => import("./telas/AdminEscritorios").then((m) => ({ default: m.TelaAdminEscritorios })));
const TelaAdminFollowup = lazy(() => import("./telas/AdminFollowup").then((m) => ({ default: m.TelaAdminFollowup })));
const TelaAgente = lazy(() => import("./telas/Agente").then((m) => ({ default: m.TelaAgente })));
const TelaAgenteNovo = lazy(() => import("./telas/AgenteNovo").then((m) => ({ default: m.TelaAgenteNovo })));
const TelaConfiguracoes = lazy(() => import("./telas/Configuracoes").then((m) => ({ default: m.TelaConfiguracoes })));
const TelaConversas = lazy(() => import("./telas/Conversas").then((m) => ({ default: m.TelaConversas })));
const TelaFerramentas = lazy(() => import("./telas/Ferramentas").then((m) => ({ default: m.TelaFerramentas })));
const TelaRoteiro = lazy(() => import("./telas/Roteiros").then((m) => ({ default: m.TelaRoteiro })));
const TelaRoteiros = lazy(() => import("./telas/Roteiros").then((m) => ({ default: m.TelaRoteiros })));
const TelaMinhaConta = lazy(() => import("./telas/MinhaConta").then((m) => ({ default: m.TelaMinhaConta })));
const TelaCrm = lazy(() => import("./telas/MinhaConta").then((m) => ({ default: m.TelaCrm })));
const TelaCentral = lazy(() => import("./telas/MinhaConta").then((m) => ({ default: m.TelaCentral })));
const TelaChatbots = lazy(() => import("./telas/MinhaConta").then((m) => ({ default: m.TelaChatbots })));
const TelaErros = lazy(() => import("./telas/Erros").then((m) => ({ default: m.TelaErros })));
const TelaExecucoes = lazy(() => import("./telas/Execucoes").then((m) => ({ default: m.TelaExecucoes })));
const TelaHistorico = lazy(() => import("./telas/Historico").then((m) => ({ default: m.TelaHistorico })));
const TelaInicio = lazy(() => import("./telas/Inicio").then((m) => ({ default: m.TelaInicio })));
const TelaIntegracoes = lazy(() => import("./telas/Integracoes").then((m) => ({ default: m.TelaIntegracoes })));
const TelaModelos = lazy(() => import("./telas/Modelos").then((m) => ({ default: m.TelaModelos })));
const TelaModelo = lazy(() => import("./telas/Modelos").then((m) => ({ default: m.TelaModelo })));
const TelaEquipe = lazy(() => import("./telas/Equipe").then((m) => ({ default: m.TelaEquipe })));
const TelaAvisos = lazy(() => import("./telas/Avisos").then((m) => ({ default: m.TelaAvisos })));
const TelaCarteira = lazy(() => import("./telas/Carteira").then((m) => ({ default: m.TelaCarteira })));
const TelaAdminCobranca = lazy(() => import("./telas/AdminCobranca").then((m) => ({ default: m.TelaAdminCobranca })));
const Biblioteca = lazy(() => import("@/pages/Biblioteca"));
const BibliotecaDetalhes = lazy(() => import("@/pages/BibliotecaDetalhes"));
const MeusProdutos = lazy(() => import("@/pages/MeusProdutos"));
const AdminProdutos = lazy(() => import("@/pages/admin/AdminProdutos"));
const AdminProdutoEditor = lazy(() => import("@/pages/admin/AdminProdutoEditor"));
const Ativar = lazy(() => import("@/pages/Ativar"));
const ProdutoEditor = lazy(() => import("@/pages/ProdutoEditor"));

/**
 * Depois que o painel abre, baixa em horário ocioso os arquivos das telas do menu (um por vez): a primeira ida a cada
 * tela deixa de esperar o JS dela. Só as telas que o papel enxerga; falha de rede aqui é ignorada (a tela baixa de novo
 * quando for aberta).
 */
function usePreCarregarTelas(ligado: boolean, podeGerir: boolean, admin: boolean) {
  useEffect(() => {
    if (!ligado) return;
    const telas: (() => Promise<unknown>)[] = [
      () => import("./telas/Inicio"), () => import("./telas/Conversas"), () => import("./telas/MinhaConta"),
      ...(podeGerir ? [
        () => import("@/pages/MeusProdutos"), () => import("./telas/Agente"), () => import("@/pages/Biblioteca"),
        () => import("@/pages/BibliotecaDetalhes"), () => import("./telas/Ferramentas"), () => import("./telas/Carteira"),
        () => import("@/pages/ProdutoEditor"), () => import("./telas/Integracoes"), () => import("./telas/Configuracoes"),
        () => import("./telas/Roteiros"), () => import("./telas/Historico"), () => import("./telas/Erros"),
      ] : []),
      ...(admin ? [() => import("./telas/AdminEscritorios"), () => import("@/pages/admin/AdminProdutos")] : []),
    ];
    let cancelado = false;
    const ocioso = (fn: () => void) => ("requestIdleCallback" in window
      ? (window as any).requestIdleCallback(fn, { timeout: 3000 }) : (window as Window).setTimeout(fn, 300));
    const proxima = (i: number) => {
      if (cancelado || i >= telas.length) return;
      ocioso(() => { telas[i]().catch(() => undefined).finally(() => proxima(i + 1)); });
    };
    const inicio = window.setTimeout(() => proxima(0), 1500);   // deixa a primeira tela terminar de carregar antes
    return () => { cancelado = true; window.clearTimeout(inicio); };
  }, [ligado, podeGerir, admin]);
}

const TITULOS: [RegExp, string][] = [
  [/^\/$/, "Início"], [/^\/agentes\/novo/, "Meus agentes › Criar"], [/^\/agentes\/./, "Meus agentes › Agente"], [/^\/agentes/, "Meus agentes"],
  [/^\/erros/, "Erros"], [/^\/conversas/, "Conversas"], [/^\/atendimento/, "Central de Atendimento"],
  [/^\/biblioteca\/./, "Biblioteca › Produto"], [/^\/biblioteca/, "Biblioteca"], [/^\/meus-produtos/, "Meus agentes"],
  [/^\/integracoes/, "Integrações"], [/^\/avisos/, "Avisos à equipe"], [/^\/configuracoes/, "Escritório"], [/^\/historico/, "Histórico"], [/^\/consumo/, "Créditos"], [/^\/ferramentas/, "Ferramentas"], [/^\/minha-conta/, "Minha Conta"], [/^\/crm/, "CRM"], [/^\/chatbots/, "Chatbots"], [/^\/admin\/cobranca/, "LawChat › Cobrança da IA"],
  [/^\/admin\/escritorios/, "LawChat › Escritórios"], [/^\/admin\/equipe/, "LawChat › Equipe"], [/^\/admin\/modelos/, "LawChat › Modelos de agente"],
  [/^\/admin\/produtos\/./, "LawChat › Produtos › Editar"], [/^\/admin\/produtos/, "LawChat › Produtos (catálogo)"], [/^\/admin\/erros/, "LawChat › Erros"], [/^\/admin\/execucoes/, "LawChat › Execuções"], [/^\/admin\/followup/, "LawChat › Follow-up"],
];

function Titulo() {
  const { pathname } = useLocation();
  const titulo = TITULOS.find(([re]) => re.test(pathname))?.[1] ?? "";
  return <b>{titulo}</b>;
}

function TrocarSenha() {
  const { eu, recarregar } = useSessao();
  const { ocupado, executar } = useAcao();
  const [atual, setAtual] = useState("");
  const [nova, setNova] = useState("");
  // "Depois" vale até fechar o navegador (antes voltava a cada recarga de página).
  const [fechado, setFechadoEstado] = useState(() => { try { return sessionStorage.getItem("agentesia_senha_depois") === "1"; } catch { return false; } });
  const setFechado = (v: boolean) => { try { sessionStorage.setItem("agentesia_senha_depois", v ? "1" : ""); } catch { /* sem armazenamento */ } setFechadoEstado(v); };
  if (!eu?.trocar_senha || fechado || eu.email.endsWith(".helena.local")) return null;
  return (
    <Modal titulo="Crie sua senha" texto="Você entrou com uma senha provisória. Troque por uma sua." aoFechar={() => setFechado(true)}
      rodape={<><span className="sp" /><button className="btn" onClick={() => setFechado(true)}>Depois</button>
        <button className="btn pri" disabled={ocupado || nova.length < 8} onClick={() => executar(async () => { await enviar("/senha", { atual, nova }); await recarregar(); setFechado(true); }, "Senha trocada.")}>Salvar</button></>}>
      <div className="form">
        <label className="field"><span className="lbl">Senha provisória</span><input type="password" value={atual} onChange={(e) => setAtual(e.target.value)} /></label>
        <label className="field"><span className="lbl">Nova senha (mínimo 8 caracteres)</span><input type="password" value={nova} onChange={(e) => setNova(e.target.value)} /></label>
      </div>
    </Modal>
  );
}

function Rotas() {
  const { eu, carregando, admin, podeGerir, escritorio } = useSessao();
  usePreCarregarTelas(Boolean(eu), podeGerir, admin);
  if (carregando) return <CarregandoEntrada />;
  if (!eu) return <Entrar />;
  const precisaEscritorio = (tela: JSX.Element) => escritorio ? tela : <Alerta tipo="info">Abra uma conta em Admin › Contas (botão Acessar).</Alerta>;
  return (
    <Suspense fallback={<CarregandoEntrada />}>
    <Routes>
      {/* Telas de tela cheia (fora da barra lateral), como no agents-lawchat-main */}
      {podeGerir && <>
        <Route path="/ativar/:slug" element={precisaEscritorio(<Ativar />)} />
        <Route path="/meus-produtos/:id" element={precisaEscritorio(<ProdutoEditor />)} />
      </>}
      <Route path="*" element={<ComEstrutura />} />
    </Routes>
    </Suspense>
  );
}

function ComEstrutura() {
  const { admin, podeGerir, escritorio } = useSessao();
  const precisaEscritorio = (tela: JSX.Element) => escritorio ? tela : <Alerta tipo="info">Abra uma conta em Admin › Contas (botão Acessar).</Alerta>;
  return (
    <Estrutura titulo={<Titulo />}>
      <TrocarSenha />
      <Suspense fallback={<Carregando />}>
      <Routes>
        <Route path="/" element={<TelaInicio />} />
        {/* Conversas: todos os papéis do escritório (o atendente pausa e devolve a IA por aqui). */}
        <Route path="/conversas/:id?" element={precisaEscritorio(<TelaConversas />)} />
        <Route path="/atendimento" element={precisaEscritorio(<TelaCentral />)} />
        <Route path="/chatbots" element={precisaEscritorio(<TelaChatbots />)} />
        {podeGerir && <>
          <Route path="/agentes" element={<Navigate to="/meus-produtos" replace />} />
          {/* ↑ "Meus agentes" é a lista única (Meus Produtos + Agentes): o /agentes antigo leva para lá. */}
          <Route path="/agentes/novo" element={precisaEscritorio(<TelaAgenteNovo />)} />
          <Route path="/agentes/:id" element={precisaEscritorio(<TelaAgente />)} />
          <Route path="/agentes/:id/:secao" element={precisaEscritorio(<TelaAgente />)} />
          <Route path="/erros" element={precisaEscritorio(<TelaErros />)} />
          <Route path="/integracoes" element={precisaEscritorio(<TelaIntegracoes />)} />
          <Route path="/avisos" element={precisaEscritorio(<TelaAvisos />)} />
          <Route path="/configuracoes" element={precisaEscritorio(<TelaConfiguracoes />)} />
          <Route path="/historico" element={precisaEscritorio(<TelaHistorico />)} />
          <Route path="/consumo" element={precisaEscritorio(<TelaCarteira />)} />
          <Route path="/ferramentas" element={precisaEscritorio(<TelaFerramentas />)} />
          <Route path="/ferramentas/roteiros" element={precisaEscritorio(<TelaRoteiros />)} />
          <Route path="/ferramentas/roteiros/:id" element={precisaEscritorio(<TelaRoteiro />)} />
          <Route path="/minha-conta" element={precisaEscritorio(<TelaMinhaConta />)} />
          <Route path="/minha-conta/:pagina" element={precisaEscritorio(<TelaMinhaConta />)} />
          <Route path="/crm" element={precisaEscritorio(<TelaCrm />)} />
          <Route path="/crm/:pagina" element={precisaEscritorio(<TelaCrm />)} />
          <Route path="/biblioteca" element={precisaEscritorio(<Biblioteca />)} />
          <Route path="/biblioteca/:slug" element={precisaEscritorio(<BibliotecaDetalhes />)} />
          <Route path="/meus-produtos" element={precisaEscritorio(<MeusProdutos />)} />
        </>}
        {admin && <>
          <Route path="/admin/escritorios" element={<TelaAdminEscritorios />} />
          <Route path="/admin/equipe" element={<TelaEquipe />} />
          <Route path="/admin/modelos" element={<TelaModelos />} />
          <Route path="/admin/modelos/:id" element={<TelaModelo />} />
          <Route path="/admin/erros" element={<TelaErros todos />} />
          <Route path="/admin/execucoes" element={<TelaExecucoes />} />
          <Route path="/admin/execucoes/:id" element={<TelaExecucoes />} />
          <Route path="/admin/cobranca" element={<TelaAdminCobranca />} />
          <Route path="/admin/followup" element={<TelaAdminFollowup />} />
          <Route path="/admin/produtos" element={<AdminProdutos />} />
          <Route path="/admin/produtos/:id" element={<AdminProdutoEditor />} />
        </>}
        <Route path="/entrar" element={<Navigate to="/" replace />} />
        {/* Depois do login da equipe: a LawChat cai na área admin (como no sistema de referência). */}
        <Route path="/login" element={<Navigate to={admin ? "/admin/escritorios" : "/"} replace />} />
        <Route path="/superadmin" element={<Navigate to={admin ? "/admin/escritorios" : "/"} replace />} />
        <Route path="/acesso" element={<Navigate to={admin ? "/admin/escritorios" : "/"} replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      </Suspense>
    </Estrutura>
  );
}

// Telas copiadas do agents-lawchat-main usam React Query (sem nova tentativa automática, como lá). Voltar a uma tela
// mostra o dado guardado na hora: até staleTime nem pergunta ao servidor; depois mostra e atualiza por trás. gcTime
// longo: o dado de uma tela fechada continua guardado por 30 min (o padrão de 5 min fazia a volta cair no esqueleto).
const consultas = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 30_000, gcTime: 30 * 60_000 } } });
// Qualquer POST/PUT/DELETE do painel (inclusive das telas sem React Query) marca tudo como velho, sem buscar agora:
// a próxima abertura de cada tela busca de novo (as mutações continuam invalidando o que é delas, como antes).
window.addEventListener("agentesia:alterou", () => { consultas.invalidateQueries({ refetchType: "none" }); });
// Saiu da conta: nada do usuário anterior fica guardado.
window.addEventListener("agentesia:sair", () => { consultas.clear(); });

createRoot(document.getElementById("raiz")!).render(
  <StrictMode>
    <QueryClientProvider client={consultas}>
      <TooltipProvider delayDuration={200}>
        <BrowserRouter>
          <ProvedorAvisos>
            <ProvedorSessao>
              <Rotas />
            </ProvedorSessao>
          </ProvedorAvisos>
        </BrowserRouter>
        <Toaster position="top-right" closeButton />
      </TooltipProvider>
    </QueryClientProvider>
  </StrictMode>,
);
