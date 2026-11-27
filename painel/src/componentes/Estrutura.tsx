import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import AnimatedList from "@/components/reactbits/AnimatedList";
import { NomeDoEscritorio } from "./nomeEscritorio";
import { PAGINAS_CONFIG, PAGINAS_CONTA, PAGINAS_CRM } from "../telas/MinhaConta";
import { CamadaLawChat, preabrirLawChat } from "./camadaLawChat";
import { estiloDaCentral, estiloDoQuadro, estiloDoQuadroConfig } from "../telas/Atendimento";
import { createPortal } from "react-dom";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import { MotionConfig, motion } from "framer-motion";
import {
  BarChart3, Cpu, Workflow, Activity, AlertOctagon, Headset, BellRing, BookOpen, Bot, Building2, ChevronDown, ChevronRight, History, Home, LayoutGrid, Library,
  CreditCard, LogOut, Target, Menu, MessagesSquare, Package, ShieldCheck, Wrench, PanelLeftClose, PanelLeftOpen, PlugZap, Search, Settings, Users, Wallet, X,
  Mic,
} from "lucide-react";
import { NOME_PAPEL, type Agente } from "../api";
import iconeLawChat from "@/assets/lawchat-icone.svg";
import escritaLawChat from "@/assets/lawchat-escrita.svg";
import fotoLawChat from "@/assets/lawchat-perfil.jpg";
import { ImpersonationBanner } from "@/components/admin/ImpersonationBanner";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { secoesDo } from "../telas/agenteSecoes";
import { useSessao } from "../sessao";
import { Modal, useCarregar } from "./ui";
import { AvisoSaldo } from "./AvisoSaldo";
import { SaldoTopo } from "./SaldoTopo";
import { CentralNotificacoes } from "./CentralNotificacoes";
// Visual: brilho dos botões (um ouvinte só) e o acabamento geral (fundo, cartões, cabeçalhos, estados vazios).
import "@/lib/brilhoBotoes";
import "../estilo-polimento.css";
import { GuiaRealce } from "./GuiaRealce";

/*
 * Casca do painel: menu lateral, barra do topo e gaveta do celular.
 * O desenho segue o do LawChat Gestão (menu que flutua a 12px da borda, seleção que desliza
 * entre os itens, ícone ativo que se desenha, cartão do usuário com brilho, topo de vidro),
 * na cor de marca verde LawChat. O visual mora em estilo-navegacao.css (classes "lc-*").
 * No celular (até 820px) o menu vira gaveta por cima do conteúdo, que ocupa a largura toda.
 */

export { NomeDoEscritorio } from "./nomeEscritorio";

interface Item { para: string; rotulo: string; icone: ReactNode; contador?: number; grupo?: string; selo?: string }
const CHAVE_RECOLHIDO = "agentesia_menu_recolhido";
const CELULAR = "(max-width: 820px)";

function lerRecolhido(): boolean {
  try { return localStorage.getItem(CHAVE_RECOLHIDO) === "1"; } catch { return false; }
}

/** Tela estreita: o menu é gaveta (e nunca fica recolhido em ícones). */
function useCelular(): boolean {
  const [celular, setCelular] = useState(() => typeof window !== "undefined" && window.matchMedia(CELULAR).matches);
  useEffect(() => {
    const m = window.matchMedia(CELULAR);
    const mudou = () => setCelular(m.matches);
    mudou();
    m.addEventListener("change", mudou);
    return () => m.removeEventListener("change", mudou);
  }, []);
  return celular;
}

function iniciaisDe(nome: string): string {
  const partes = nome.trim().split(/\s+/);
  return ((partes[0]?.[0] ?? "") + (partes.length > 1 ? partes[partes.length - 1][0] : "")).toUpperCase() || "?";
}

function emCampoDeTexto(alvo: EventTarget | null): boolean {
  const el = alvo as HTMLElement | null;
  if (!el) return false;
  return el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName);
}

export function Estrutura({ titulo, children }: { titulo: ReactNode; children: ReactNode }) {
  const { eu, admin, lawchat, podeGerir, escritorio, escritorioLawchat, trocarEscritorio, trocarVisao, visao, sair } = useSessao();
  const local = useLocation();
  // Central de Atendimento (LawChat embutida): ocupa a tela inteira.
  // Telas da LawChat (Central, CRM, Ajustes): abrem embaixo do menu do topo, ocupando a altura toda.
  const telaLawChat = /^\/(atendimento|crm|minha-conta|chatbots)(\/|$)/.test(local.pathname);
  // Ao abrir o sistema, as telas da LawChat entram por trás, uma de cada vez (Central primeiro), e ficam montadas:
  // ao clicar, já estão prontas. Atualizar a página (F5) faz de novo.
  const { podeGerir: gestorDaConta } = useSessao();
  useEffect(() => {
    if (!escritorio) return;
    const t = window.setTimeout(() => {
      preabrirLawChat([{ codigo: "atendimento", titulo: "Central de Atendimento", estilo: estiloDaCentral }]);
      if (!gestorDaConta) return;
      // Todas as telas da LawChat entram por trás (uma de cada vez, a Central primeiro), já durante a tela de
      // carregamento: ao clicar, já estão prontas. O dono prefere isso a abrir no clique.
      preabrirLawChat([
        { codigo: "chatbots", titulo: "Chatbots", estilo: estiloDoQuadro },
        ...PAGINAS_CRM.map((p) => ({ codigo: p.codigo, titulo: p.rotulo, estilo: estiloDoQuadro })),
        ...PAGINAS_CONTA.filter((p) => p.codigo !== "ia" && p.codigo !== "conta").map((p) => ({ codigo: p.codigo, titulo: p.rotulo, estilo: estiloDoQuadro })),
        ...PAGINAS_CONFIG.map((p) => ({ codigo: p.codigo, titulo: p.rotulo, estilo: estiloDoQuadroConfig })),
      ]);
    }, 300);
    return () => window.clearTimeout(t);
  }, [escritorio, gestorDaConta]);
  const celular = useCelular();
  const [abertos, setAbertos] = useState(false);
  const [recolhido, setRecolhido] = useState(lerRecolhido());
  const [busca, setBusca] = useState(false);
  const [ajuda, setAjuda] = useState(false);
  const escritorios = useCarregar<{ id: string; nome: string }[]>(lawchat ? "/admin/escritorios" : null, [escritorio, local.pathname === "/admin/escritorios"]);
  // Só o contador de erros do menu (uma consulta). Antes pedia o /inicio inteiro, que a tela Início também pede.
  const resumo = useCarregar<{ erros_abertos: number }>(escritorio && podeGerir ? "/inicio/contadores" : null, [escritorio, visao]);
  // Agente aberto: vira um submenu embaixo de "Agentes" (no lugar das abas da página).
  const idAgente = /^\/agentes\/([0-9a-fA-F-]{36})/.exec(local.pathname)?.[1] ?? null;
  const agenteAberto = useCarregar<Agente>(idAgente && podeGerir ? `/agentes/${idAgente}` : null, [idAgente, escritorio]);
  const [submenuAberto, setSubmenuAberto] = useState(true);
  const nomeEscritorio = (escritorios.dados ?? []).find((e) => e.id === escritorio)?.nome ?? eu?.nome_escritorio ?? "este escritório";
  // Equipe LawChat "como cliente": vê exatamente o que o cliente vê (sem seletor nem grupo LawChat).
  const impersonando = lawchat && Boolean(escritorio) && visao !== "lawchat";
  // Recolhido em ícones só no computador; a gaveta do celular sempre abre inteira.
  // Telas da LawChat abertas aqui dentro (CRM, ajustes da conta): o menu recolhe para ícones e dá a largura para elas,
  // que têm o próprio menu de ajustes; as abas do grupo ficam na faixa de cima da tela.
  const telaDaLawChat = /^\/crm(\/|$)/.test(local.pathname) || /^\/minha-conta\/(?!ia$)[^/]+$/.test(local.pathname);
  // A navegação entre essas telas é pelo submenu do menu lateral (CRM, Minha Conta): ele fica aberto.
  void telaDaLawChat;
  const compacto = recolhido && !celular;

  useEffect(() => { setAbertos(false); }, [local.pathname]);
  useEffect(() => { if (!celular) setAbertos(false); }, [celular]);
  // Troca de tela: o conteúdo entra com um fade curto subindo (só visual; não remonta nada).
  const refPagina = useRef<HTMLElement>(null);
  const primeiraTela = useRef(true);
  const chaveTela = local.pathname.split("/").filter((p) => p && !/^[0-9a-f-]{20,}$/i.test(p)).slice(0, 2).join("/");
  useEffect(() => {
    if (primeiraTela.current) { primeiraTela.current = false; return; }
    const el = refPagina.current;
    if (!el || telaLawChat || typeof el.animate !== "function") return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    el.animate([{ opacity: 0, transform: "translateY(8px)" }, { opacity: 1, transform: "none" }], { duration: 300, easing: "cubic-bezier(.22, 1, .36, 1)" });
  }, [chaveTela]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    document.body.classList.toggle("nav-aberta", abertos);
    return () => document.body.classList.remove("nav-aberta");
  }, [abertos]);
  const alternarRecolhido = () => {
    setRecolhido((v) => { try { localStorage.setItem(CHAVE_RECOLHIDO, v ? "0" : "1"); } catch { /* só nesta sessão */ } return !v; });
  };
  useEffect(() => {
    const tecla = (e: KeyboardEvent) => {
      const chave = e.key.toLowerCase();
      if ((e.ctrlKey || e.metaKey) && chave === "k") { e.preventDefault(); setBusca(true); return; }
      // Ctrl+B: recolhe o menu (computador) ou abre a gaveta (celular). Não rouba o negrito dos editores.
      if ((e.ctrlKey || e.metaKey) && chave === "b" && !emCampoDeTexto(e.target)) {
        e.preventDefault();
        if (window.matchMedia(CELULAR).matches) setAbertos((v) => !v);
        else alternarRecolhido();
        return;
      }
      if (e.key === "Escape") setAbertos(false);
    };
    window.addEventListener("keydown", tecla);
    return () => window.removeEventListener("keydown", tecla);
  }, []);

  const navegarConta = useNavigate();
  // Sai do superadmin para a conta da própria LawChat (ou fica no escritório aberto, se não houver).
  const voltarParaConta = () => {
    if (escritorioLawchat) trocarEscritorio(escritorioLawchat);
    trocarVisao("lawchat");
    navegarConta("/");
  };
  const erros = resumo.dados?.erros_abertos ?? 0;
  // Modo superadmin: a equipe LawChat clicou em "Admin" (telas /admin/...). O menu troca para as funções de admin.
  const modoAdmin = lawchat && !impersonando && local.pathname.startsWith("/admin");
  const grupos: { titulo: string; itens: Item[] }[] = [];
  if (modoAdmin) {
    grupos.push({ titulo: "Superadmin", itens: [
      { para: "/admin/escritorios", rotulo: "Contas", icone: <Building2 className="i" /> },
      { para: "/admin/produtos", rotulo: "Produtos", icone: <LayoutGrid className="i" /> },
      { para: "/admin/modelos", rotulo: "Modelos de agente", icone: <BookOpen className="i" /> },
      { para: "/admin/planos", rotulo: "Planos", icone: <Package className="i" /> },
      { para: "/admin/cobranca?aba=recargas", rotulo: "Recargas", icone: <CreditCard className="i" /> },
      { para: "/admin/cobranca?aba=carteiras", rotulo: "Financeiro", icone: <Wallet className="i" /> },
      { para: "/admin/erros", rotulo: "Erros da IA", icone: <AlertOctagon className="i" /> },
      { para: "/admin/execucoes", rotulo: "Execuções", icone: <Activity className="i" /> },
      { para: "/admin/logs", rotulo: "Logs", icone: <History className="i" /> },
      { para: "/admin/equipe", rotulo: "Usuários admin", icone: <Users className="i" /> },
    ] });
  } else {
    const itens: Item[] = [];
    if (escritorio) {
      itens.push({ para: "/", rotulo: "Painel Inicial", icone: <Home className="i" /> });
      itens.push({ para: "/atendimento", rotulo: "Atendimento", icone: <Headset className="i" /> });
      itens.push({ para: "/crm/paineis", rotulo: "CRM", icone: <Workflow className="i" /> });
      if (podeGerir) itens.push({ para: "/relatorios/dashboard", rotulo: "Relatórios", icone: <BarChart3 className="i" /> });
      // Apps (selo NOVO): Meus agentes, Biblioteca e Ferramentas numa lista só (os agentes de IA ficam aqui dentro).
      if (podeGerir) itens.push(
        { para: "/meus-produtos", rotulo: "Apps", icone: <LayoutGrid className="i" />, selo: "NOVO" },
        { para: "/minha-conta/usuarios", rotulo: "Ajustes", icone: <Settings className="i" /> },
      );
    }
    grupos.push({ titulo: "Menu", itens });
  }
  const todosItens = grupos.flatMap((g) => g.itens.map((i) => ({ ...i, grupo: g.titulo })));
  // Busca (Ctrl K): também as telas de dentro de CRM, Apps e Ajustes (o grupo aparece ao lado de cada uma).
  const itensDaBusca: Item[] = todosItens.flatMap((i) => {
    const grupo = GRUPOS_DO_MENU[i.para];
    if (!grupo) return [{ ...i, grupo: "Menu" }];
    return grupo.filhos.map((f) => ({ para: f.para, rotulo: f.rotulo, icone: f.icone, grupo: i.rotulo }));
  });
  const subtitulo = lawchat && !impersonando ? "Equipe LawChat" : impersonando ? nomeEscritorio : eu?.nome_escritorio ?? "";

  // Busca, avisos, Admin, ajuda e a foto: na barra do topo e também na faixa da Central de Atendimento.
  const acoesTopo = (
    <>
        <button type="button" className="lc-busca" onClick={() => setBusca(true)} aria-label="Buscar em tudo (Ctrl K)">
          <Search /><span>Buscar em tudo</span><kbd>Ctrl K</kbd>
        </button>
        <div className="lc-pilula">
          {/* Sino: central de notificações da IA (lead qualificado, IA pausada, contrato). Os erros técnicos entram só
              para a equipe LawChat na visão dela; na visão de cliente (e para o cliente), só as notificações de negócio. */}
          {escritorio && <CentralNotificacoes escritorio={escritorio} erros={erros} mostrarErros={lawchat && !impersonando} />}
          {lawchat && !impersonando && !modoAdmin && (
            <Link to="/admin/escritorios" className="lc-btn-admin" title="Entrar no modo superadmin"><ShieldCheck />Admin</Link>
          )}
          {eu && <span className="lc-topo-av" title={`${eu.nome} · ${NOME_PAPEL[eu.papel]}`}>{lawchat ? <img src={fotoLawChat} alt="" className="lc-av-foto" /> : iniciaisDe(eu.nome)}</span>}
        </div>
    </>
  );

  return (<>
    <CamadaLawChat escritorio={escritorio || null} escondida={false} />
        {busca && createPortal(<BuscaRapida itens={itensDaBusca} aoFechar={() => setBusca(false)} />, document.body)}
        {ajuda && (
          <Modal titulo="Ajuda rápida" aoFechar={() => setAjuda(false)} rodape={<><span className="sp" /><button className="btn pri" onClick={() => setAjuda(false)}>Entendi</button></>}>
            <div className="form">
              <p className="sec" style={{ margin: 0 }}><b>Ctrl K</b> abre a busca de telas. <b>Ctrl B</b> recolhe o menu lateral. O <b>botão redondo</b> no canto abre os atalhos.</p>
              <p className="sec" style={{ margin: 0 }}>Para colocar um agente no ar: <b>Meus agentes</b> → <b>Novo a partir da Biblioteca</b> → escolha o produto → <b>Ativar</b>. Prompt, follow-up, conhecimento e Laboratório ficam no cartão de cada agente.</p>
              <p className="sec" style={{ margin: 0 }}>As conversas ficam na <b>Central de Atendimento</b>. Aqui ficam a IA, a configuração e o acompanhamento.</p>
            </div>
          </Modal>
        )}
    {(
    <MotionConfig reducedMotion="user">
      <div className={`lc-casca${compacto ? " recolhido" : ""}${abertos ? " gaveta-aberta" : ""}`}>
        {/* Degradê verde usado pelos ícones ativos (stroke: url(#lc-grad-icone)). */}
        <svg className="lc-defs" width="0" height="0" aria-hidden="true" focusable="false">
          <defs>
            <linearGradient id="lc-grad-icone" gradientUnits="userSpaceOnUse" x1="2" y1="2" x2="22" y2="22">
              <stop offset="0" stopColor="#3BE062" />
              <stop offset="0.5" stopColor="#00BC33" />
              <stop offset="1" stopColor="#00852A" />
            </linearGradient>
          </defs>
        </svg>

        <aside className="lc-menu" id="lc-menu" aria-label="Navegação">
          <div className="lc-menu-cab">
            <Link to="/" className="lc-marca" title="Painel Inicial">
              <img src={iconeLawChat} alt="" className="lc-marca-logo" width={30} height={31} />
              {!compacto && <span className="lc-marca-txt"><b>LawChat IA</b>{subtitulo && <small>{subtitulo}</small>}</span>}
            </Link>
            {!compacto && (
              <button type="button" className="lc-cab-btn lc-recolher" onClick={alternarRecolhido} aria-label="Recolher menu lateral" title="Recolher menu (Ctrl+B)">
                <PanelLeftClose />
              </button>
            )}
            <button type="button" className="lc-cab-btn lc-fechar" onClick={() => setAbertos(false)} aria-label="Fechar menu"><X /></button>
          </div>
          {compacto && (
            <button type="button" className="lc-cab-btn lc-expandir" onClick={alternarRecolhido} aria-label="Abrir menu lateral" title="Abrir menu (Ctrl+B)">
              <PanelLeftOpen />
            </button>
          )}

          <motion.nav layoutScroll className="lc-nav">
            {grupos.map((g) => (
              <div className="lc-secao" key={g.titulo}>
                {!compacto && g.titulo !== "Menu" && <p className="lc-secao-titulo">{g.titulo}</p>}
                <ul className="lc-lista">
                  {g.itens.map((i) => (
                    <li key={i.para}>
                      {GRUPOS_DO_MENU[i.para] && !compacto ? (
                        <GrupoMenu item={i} grupo={GRUPOS_DO_MENU[i.para]} />
                      ) : (
                        <ItemMenu item={i} compacto={compacto} end={i.para === "/"} ativo={i.para === "/meus-produtos" && Boolean(idAgente)} />
                      )}
                      {i.para === "/meus-produtos" && idAgente && agenteAberto.dados && !compacto && (
                        <div className="lc-sub">
                          <button type="button" className="lc-sub-cab" onClick={() => setSubmenuAberto(!submenuAberto)} aria-expanded={submenuAberto}>
                            <span className="lc-sub-ponto" data-ativo={agenteAberto.dados.situacao === "ativo"} />
                            <span className="lc-sub-nome">{agenteAberto.dados.nome}</span>
                            <ChevronDown size={14} className={`lc-sub-seta${submenuAberto ? " aberta" : ""}`} />
                          </button>
                          {submenuAberto && (
                            <div className="lc-sub-itens">
                              {secoesDo(agenteAberto.dados.tipo_produto === "proprio", admin).map((s) => (
                                <NavLink key={s.chave} to={`/agentes/${idAgente}/${s.chave}`}>{s.icone(14)}<span>{s.rotulo}</span></NavLink>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </motion.nav>

          {eu && (
            <div className="lc-rodape">
              {compacto ? (
                <div className="lc-usuario-mini">
                  <span className="lc-av" title={`${eu.nome} · ${NOME_PAPEL[eu.papel]}`}>
                    {lawchat ? <img src={fotoLawChat} alt="" className="lc-av-foto" /> : <span className="lc-av-letras">{iniciaisDe(eu.nome)}</span>}<i className="lc-online" aria-hidden />
                  </span>
                  <button type="button" className="lc-cab-btn" onClick={sair} aria-label="Sair" title="Sair"><LogOut /></button>
                </div>
              ) : (
                <div className="lc-usuario">
                  <span className="lc-usuario-brilho" aria-hidden />
                  <div className="lc-usuario-id">
                    <span className="lc-av">{lawchat ? <img src={fotoLawChat} alt="" className="lc-av-foto" /> : <span className="lc-av-letras">{iniciaisDe(eu.nome)}</span>}<i className="lc-online" aria-hidden /></span>
                    <div className="lc-usuario-txt"><b>{eu.nome}</b><span>{NOME_PAPEL[eu.papel]}</span></div>
                  </div>
                  <div className="lc-usuario-acoes">
                    <button type="button" className="lc-sair" onClick={sair}><LogOut /><span>Sair</span></button>
                    {podeGerir && escritorio && (
                      <Link className="lc-config" to="/configuracoes" aria-label="Configurações do escritório" title="Configurações"><Settings /></Link>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
        </aside>

        <div className="lc-veu" onClick={() => setAbertos(false)} aria-hidden />

        <div className="lc-conteudo">
          <header className="lc-topo">
            <button type="button" className="lc-topo-menu" onClick={() => setAbertos(true)} aria-label="Abrir menu" aria-expanded={abertos} aria-controls="lc-menu">
              <Menu />
            </button>
            <Link to="/" className="lc-topo-marca" title="Painel Inicial"><img src={iconeLawChat} alt="" className="lc-topo-simbolo" /><img src={escritaLawChat} alt="LawChat" className="lc-topo-escrita" /></Link>
            <MenuDoTopo itens={todosItens} />
            <nav className="lc-crumb" aria-label="Você está em">
              <span className="lc-crumb-esc">{escritorio ? nomeEscritorio : "LawChat"}</span>
              <ChevronRight className="lc-crumb-sep" aria-hidden />
              <span className="lc-crumb-atual">{titulo}</span>
            </nav>
            <div className="lc-sp" />
            {escritorio && podeGerir && !modoAdmin && <SaldoTopo escritorio={escritorio} />}
            {acoesTopo}
          </header>
          {/* A barra de abas do agente no topo saiu (pedido do dono): navega-se pelos cartões da página do agente e
              pelo "← voltar" de cada tela. */}
          <ImpersonationBanner nomeEscritorio={nomeEscritorio} />
          {modoAdmin && (
            <div className="lc-faixa-superadmin" role="status">
              <ShieldCheck aria-hidden />
              <span><b>Modo superadmin</b> · as ações aqui valem para todos os escritórios</span>
              <button type="button" className="lc-faixa-voltar" onClick={voltarParaConta}>Voltar para a conta</button>
            </div>
          )}
          {escritorio && <AvisoSaldo escritorio={escritorio} podeGerir={podeGerir} />}
          <div className="scroll"><main ref={refPagina} className={`page${telaLawChat ? " page-lawchat" : ""}`} key={`${escritorio}-${visao}`}>{children}</main></div>
          <GuiaRealce />
          {/* Atalhos num Dock (React Bits) no rodapé da área de conteúdo; aparece com o mouse perto da borda de baixo. */}
        </div>

      </div>
    </MotionConfig>
    )}
  </>);
}

/** Menu no topo (como o da LawChat, com as nossas cores): itens lado a lado; CRM e Ajustes abrem uma lista embaixo. */
function MenuDoTopo({ itens }: { itens: Item[] }) {
  const local = useLocation();
  const [aberto, setAberto] = useState<string | null>(null);
  useEffect(() => { setAberto(null); }, [local.pathname, local.search]);
  useEffect(() => {
    if (!aberto) return;
    const fechar = (e: MouseEvent) => { if (!(e.target as HTMLElement).closest?.(".lc-mt-grupo")) setAberto(null); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setAberto(null); };
    document.addEventListener("mousedown", fechar);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", fechar); document.removeEventListener("keydown", esc); };
  }, [aberto]);
  const caminho = local.pathname;
  const busca = local.search;
  const ativo = (para: string) => {
    const [base, consulta] = para.split("?");
    // Itens com ?aba= (Recargas, Financeiro, Planos) dividem a mesma tela: aceso só o da aba aberta.
    if (consulta) {
      const aba = new URLSearchParams(consulta).get("aba");
      return caminho === base && (new URLSearchParams(busca).get("aba") ?? "carteiras") === aba;
    }
    if (base === "/") return caminho === "/";
    if (base === "/meus-produtos") return caminho.startsWith("/meus-produtos") || caminho.startsWith("/agentes");
    return caminho === base || caminho.startsWith(base + "/");
  };
  return (
    <nav className="lc-menu-topo" aria-label="Menu">
      {itens.map((i) => {
        const grupo = GRUPOS_DO_MENU[i.para];
        if (!grupo) {
          return (
            <Link key={i.para} to={i.para} className={`lc-mt-item${ativo(i.para) ? " on" : ""}`} aria-current={ativo(i.para) ? "page" : undefined}>
              {i.icone}<span>{i.rotulo}</span>
              {i.contador ? <em className="num">{i.contador > 99 ? "99+" : i.contador}</em> : null}
            </Link>
          );
        }
        const dentro = dentroDo(grupo, caminho);
        return (
          <div key={i.para} className="lc-mt-grupo">
            <button type="button" className={`lc-mt-item${dentro ? " on" : ""}${aberto === i.para ? " aberto" : ""}`}
              onClick={() => setAberto(aberto === i.para ? null : i.para)} aria-expanded={aberto === i.para} aria-haspopup="menu">
              {i.icone}<span>{i.rotulo}</span>{i.selo && <b className="lc-mt-selo">{i.selo}</b>}<ChevronDown size={14} className="lc-mt-seta" aria-hidden />
            </button>
            {aberto === i.para && (
              <div className="lc-mt-lista" role="menu">
                {grupo.filhos.map((f) => (
                  <NavLink key={f.para} to={f.para} role="menuitem" className={({ isActive }) => (isActive ? "on" : "")}>
                    {f.icone}<span>{f.rotulo}</span>
                  </NavLink>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </nav>
  );
}

/** CRM e Minha Conta abrem uma lista no próprio menu: clica e vai direto para a tela. */
interface GrupoDoMenu { prefixo: string | string[]; filhos: { para: string; rotulo: string; icone: ReactNode }[] }
const dentroDo = (g: GrupoDoMenu, caminho: string) => (Array.isArray(g.prefixo) ? g.prefixo : [g.prefixo]).some((p) => caminho.startsWith(p));
const GRUPOS_DO_MENU: Record<string, GrupoDoMenu> = {
  "/meus-produtos": {
    prefixo: ["/meus-produtos", "/agentes", "/biblioteca", "/ferramentas", "/ativar", "/produtos", "/chatbots", "/roteiros"],
    filhos: [
      { para: "/meus-produtos", rotulo: "Agentes Inteligentes", icone: <Bot size={16} /> },
      { para: "/biblioteca", rotulo: "Biblioteca", icone: <Library size={16} /> },
      { para: "/roteiros", rotulo: "Roteiros de gravação", icone: <Mic size={16} /> },
      { para: "/ferramentas", rotulo: "Ferramentas", icone: <Wrench size={16} /> },
      { para: "/chatbots", rotulo: "Chatbots", icone: <Cpu size={16} /> },
    ],
  },
  "/relatorios/dashboard": {
    prefixo: "/relatorios",
    filhos: [
      { para: "/relatorios/dashboard", rotulo: "Dashboard", icone: <BarChart3 size={15} /> },
      { para: "/relatorios/campanhas", rotulo: "Rastreamento de campanhas", icone: <Target size={15} /> },
    ],
  },
  "/crm/paineis": { prefixo: "/crm", filhos: PAGINAS_CRM.map((p) => ({ para: `/crm/${p.codigo}`, rotulo: p.rotulo, icone: <p.icone size={15} /> })) },
  "/minha-conta/usuarios": {
    prefixo: ["/minha-conta", "/consumo"],
    filhos: [
      ...PAGINAS_CONTA.map((p) => ({ para: `/minha-conta/${p.codigo}`, rotulo: p.rotulo, icone: <p.icone size={15} /> })),
      { para: "/consumo", rotulo: "Créditos da IA", icone: <Wallet size={15} /> },
    ],
  },
};

function GrupoMenu({ item, grupo }: { item: Item; grupo: GrupoDoMenu }) {
  const local = useLocation();
  const dentro = dentroDo(grupo, local.pathname);
  const [aberto, setAberto] = useState(dentro);
  useEffect(() => { if (dentro) setAberto(true); }, [dentro]);
  return (
    <>
      <button type="button" className={`lc-item lc-item-grupo${dentro ? " active" : ""}`} onClick={() => setAberto(!aberto)} aria-expanded={aberto}>
        {dentro && <span className="lc-item-ativo" />}
        <span className="lc-item-icone">{item.icone}</span>
        <span className="lc-item-rot">{item.rotulo}</span>
        <ChevronDown size={15} className={`lc-grupo-seta${aberto ? " aberta" : ""}`} aria-hidden />
      </button>
      {aberto && (
        <div className="lc-sub">
          <div className="lc-sub-itens">
            {grupo.filhos.map((f) => (
              <NavLink key={f.para} to={f.para}>{f.icone}<span>{f.rotulo}</span></NavLink>
            ))}
          </div>
        </div>
      )}
    </>
  );
}

/** Um item do menu. A seleção é um único fundo (layoutId) que desliza de um item para o outro. */
function ItemMenu({ item, compacto, end, ativo = false }: { item: Item; compacto: boolean; end: boolean; ativo?: boolean }) {
  const local = useLocation();
  // Itens com ?aba= (Planos, Recargas, Financeiro) dividem a mesma tela: ativo só o da aba aberta.
  const comAba = item.para.includes("?");
  const abaAtual = new URLSearchParams(local.search).get("aba") ?? "carteiras";
  const ativoPorAba = comAba && local.pathname === item.para.split("?")[0] && new URLSearchParams(item.para.split("?")[1]).get("aba") === abaAtual;
  // "Meus agentes" fica aceso também com um agente aberto (/agentes/:id/...), que aparece como submenu dele.
  const aceso = (padrao: boolean) => ativo || (comAba ? ativoPorAba : padrao);
  const link = (
    <NavLink to={item.para} end={end} aria-label={compacto ? item.rotulo : undefined}
      className={({ isActive: ativoPadrao }) => `lc-item${aceso(ativoPadrao) ? " active" : ""}`}
      aria-current={comAba ? (ativoPorAba ? "page" : undefined) : ativo ? "page" : undefined}>
      {({ isActive: ativoPadrao }) => { const isActive = aceso(ativoPadrao); return (
        <>
          {isActive && (
            <motion.span layoutId="lc-menu-ativo" className="lc-item-ativo" transition={{ type: "spring", stiffness: 420, damping: 34 }} />
          )}
          <span className="lc-item-icone">
            {item.icone}
            {compacto && item.contador ? <i className="lc-item-ponto" aria-hidden /> : null}
          </span>
          {!compacto && <span className="lc-item-rot">{item.rotulo}</span>}
          {!compacto && item.contador ? <span className="lc-item-cnt num">{item.contador > 99 ? "99+" : item.contador}</span> : null}
        </>
      ); }}
    </NavLink>
  );
  if (!compacto) return link;
  return (
    <Tooltip>
      {/* Embrulho próprio: o TooltipTrigger (asChild) junta o className e estragava o className-função do NavLink
          (os itens do menu recolhido ficavam sem a classe lc-item). */}
      <TooltipTrigger asChild><span className="lc-item-dica">{link}</span></TooltipTrigger>
      <TooltipContent side="right" sideOffset={12} className="lc-dica">
        {item.rotulo}{item.contador ? ` · ${item.contador}` : ""}
      </TooltipContent>
    </Tooltip>
  );
}

/** Busca de telas (Ctrl K): digita e vai. */
function BuscaRapida({ itens, aoFechar }: { itens: Item[]; aoFechar: () => void }) {
  const navegar = useNavigate();
  const [texto, setTexto] = useState("");
  const [indice, setIndice] = useState(0);
  const achados = useMemo(() => {
    const t = texto.trim().toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
    return itens.filter((i) => !t || `${i.rotulo} ${i.grupo}`.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").includes(t));
  }, [itens, texto]);
  const ir = (i: Item | undefined) => { if (i) { navegar(i.para); aoFechar(); } };
  const entradas = useMemo(() => achados.map((i) => ({ id: i.para, icon: i.icone, title: i.rotulo, meta: i.grupo })), [achados]);
  return (
    <div className="ov busca-ov" onMouseDown={(e) => e.target === e.currentTarget && aoFechar()}>
      <div className="busca-caixa" role="dialog" aria-label="Buscar em tudo">
        <div className="busca-campo"><Search size={17} />
          <input autoFocus value={texto} placeholder="Buscar telas: agentes, integrações, avisos…" aria-label="Buscar"
            onChange={(e) => { setTexto(e.target.value); setIndice(0); }}
            onKeyDown={(e) => {
              if (e.key === "Escape") aoFechar();
              if (e.key === "ArrowDown") { e.preventDefault(); setIndice((x) => Math.min(x + 1, achados.length - 1)); }
              if (e.key === "ArrowUp") { e.preventDefault(); setIndice((x) => Math.max(x - 1, 0)); }
              if (e.key === "Enter") ir(achados[indice]);
            }} />
          <kbd>Esc</kbd>
        </div>
        <div className="busca-lista busca-lista-animada">
          {/* Lista animada (AnimatedList do React Bits): entrada em cascata e seleção que desliza; as setas do campo movem a seleção. */}
          {achados.length === 0 ? <p className="muted" style={{ padding: 14, margin: 0 }}>Nada encontrado.</p> : (
            <AnimatedList items={entradas} selectedIndex={indice} onSelectedChange={(n) => { if (n >= 0) setIndice(n); }}
              onItemSelect={(_, n) => ir(achados[n])} enableArrowNavigation={false} theme="light" accentColor="#00bc33"
              frame={false} animation="slide" stagger={0.03} radius={10} gap={4} width="100%" maxHeight={420} fadeSize={28} />
          )}
        </div>
      </div>
    </div>
  );
}
