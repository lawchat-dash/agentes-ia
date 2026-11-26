import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import "./index.css";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import "./estilo.css";
import "./estilo-navegacao.css";
import { enviar } from "./api";
import { Estrutura } from "./componentes/Estrutura";
import { Alerta, Modal, ProvedorAvisos, useAcao } from "./componentes/ui";
import { ProvedorSessao, useSessao } from "./sessao";
import { TelaAdminEscritorios } from "./telas/AdminEscritorios";
import { TelaAdminFollowup } from "./telas/AdminFollowup";
import { TelaAgente } from "./telas/Agente";
import { TelaAgenteNovo } from "./telas/AgenteNovo";
import { TelaAgentes } from "./telas/Agentes";
import { TelaConfiguracoes } from "./telas/Configuracoes";
import { TelaConversas } from "./telas/Conversas";
import { TelaAtendimento } from "./telas/Atendimento";
import { TelaFerramentas } from "./telas/Ferramentas";
import { TelaMinhaConta } from "./telas/MinhaConta";
import { CarregandoEntrada, Entrar } from "./telas/Entrar";
import { TelaErros } from "./telas/Erros";
import { TelaHistorico } from "./telas/Historico";
import { TelaInicio } from "./telas/Inicio";
import { TelaIntegracoes } from "./telas/Integracoes";
import { TelaModelos, TelaModelo } from "./telas/Modelos";
import { TelaEquipe } from "./telas/Equipe";
import { TelaAvisos } from "./telas/Avisos";
import { TelaCarteira } from "./telas/Carteira";
import { TelaAdminCobranca } from "./telas/AdminCobranca";
import Biblioteca from "@/pages/Biblioteca";
import BibliotecaDetalhes from "@/pages/BibliotecaDetalhes";
import MeusProdutos from "@/pages/MeusProdutos";
import AdminProdutos from "@/pages/admin/AdminProdutos";
import AdminProdutoEditor from "@/pages/admin/AdminProdutoEditor";
import Ativar from "@/pages/Ativar";
import ProdutoEditor from "@/pages/ProdutoEditor";

const TITULOS: [RegExp, string][] = [
  [/^\/$/, "Início"], [/^\/agentes\/novo/, "Agentes › Criar"], [/^\/agentes\/./, "Agentes › Editar"], [/^\/agentes/, "Agentes"],
  [/^\/erros/, "Erros"], [/^\/conversas/, "Conversas"], [/^\/atendimento/, "Central de Atendimento"],
  [/^\/biblioteca\/./, "Biblioteca › Produto"], [/^\/biblioteca/, "Biblioteca"], [/^\/meus-produtos/, "Meus produtos"],
  [/^\/integracoes/, "Integrações"], [/^\/avisos/, "Avisos à equipe"], [/^\/configuracoes/, "Escritório"], [/^\/historico/, "Histórico"], [/^\/consumo/, "Créditos"], [/^\/ferramentas/, "Ferramentas"], [/^\/minha-conta/, "Minha Conta"], [/^\/admin\/cobranca/, "LawChat › Cobrança da IA"],
  [/^\/admin\/escritorios/, "LawChat › Escritórios"], [/^\/admin\/equipe/, "LawChat › Equipe"], [/^\/admin\/modelos/, "LawChat › Modelos de agente"],
  [/^\/admin\/produtos\/./, "LawChat › Produtos › Editar"], [/^\/admin\/produtos/, "LawChat › Produtos (catálogo)"], [/^\/admin\/erros/, "LawChat › Erros"], [/^\/admin\/followup/, "LawChat › Follow-up"],
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
  if (carregando) return <CarregandoEntrada />;
  if (!eu) return <Entrar />;
  const precisaEscritorio = (tela: JSX.Element) => escritorio ? tela : <Alerta tipo="info">Abra uma conta em Admin › Contas (botão Acessar).</Alerta>;
  return (
    <Routes>
      {/* Telas de tela cheia (fora da barra lateral), como no agents-lawchat-main */}
      {podeGerir && <>
        <Route path="/ativar/:slug" element={precisaEscritorio(<Ativar />)} />
        <Route path="/meus-produtos/:id" element={precisaEscritorio(<ProdutoEditor />)} />
      </>}
      <Route path="*" element={<ComEstrutura />} />
    </Routes>
  );
}

function ComEstrutura() {
  const { admin, podeGerir, escritorio } = useSessao();
  const precisaEscritorio = (tela: JSX.Element) => escritorio ? tela : <Alerta tipo="info">Abra uma conta em Admin › Contas (botão Acessar).</Alerta>;
  return (
    <Estrutura titulo={<Titulo />}>
      <TrocarSenha />
      <Routes>
        <Route path="/" element={<TelaInicio />} />
        {/* Conversas: todos os papéis do escritório (o atendente pausa e devolve a IA por aqui). */}
        <Route path="/conversas/:id?" element={precisaEscritorio(<TelaConversas />)} />
        <Route path="/atendimento" element={escritorio ? null : precisaEscritorio(<span />)} />
        {podeGerir && <>
          <Route path="/agentes" element={precisaEscritorio(<TelaAgentes />)} />
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
          <Route path="/minha-conta" element={precisaEscritorio(<TelaMinhaConta />)} />
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
    </Estrutura>
  );
}

// Telas copiadas do agents-lawchat-main usam React Query (sem nova tentativa automática, como lá).
const consultas = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 30_000 } } });

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
