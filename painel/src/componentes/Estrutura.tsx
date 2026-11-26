import { useEffect, useMemo, useState, type ReactNode } from "react";
import { AcoesDoTopo, NomeDoEscritorio, guardarTelaDoPainel } from "./nomeEscritorio";
import { PAGINAS_CONTA, PAGINAS_CRM } from "../telas/MinhaConta";
import { CamadaLawChat } from "./camadaLawChat";
import { TelaAtendimento } from "../telas/Atendimento";
import { createPortal } from "react-dom";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import { MotionConfig, motion } from "framer-motion";
import {
  Workflow, Activity, AlertOctagon, Headset, Bell, BellRing, BookOpen, Bot, Building2, ChevronDown, ChevronRight, CircleHelp, History, Home, LayoutGrid, Library,
  CreditCard, LogOut, Menu, MessagesSquare, Package, ShieldCheck, Wrench, PanelLeftClose, PanelLeftOpen, PlugZap, Search, Settings, Users, Wallet, X,
} from "lucide-react";
import { NOME_PAPEL, type Agente } from "../api";
import iconeLawChat from "@/assets/lawchat-icone.svg";
import fotoLawChat from "@/assets/lawchat-perfil.jpg";
import { ImpersonationBanner } from "@/components/admin/ImpersonationBanner";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { secoesDo } from "../telas/agenteSecoes";
import { useSessao } from "../sessao";
import { Modal, useCarregar } from "./ui";
import { MenuFlutuante } from "./MenuFlutuante";
import { AvisoSaldo } from "./AvisoSaldo";
import { SaldoTopo } from "./SaldoTopo";

/*
 * Casca do painel: menu lateral, barra do topo e gaveta do celular.
 * O desenho segue o do LawChat Gestão (menu que flutua a 12px da borda, seleção que desliza
 * entre os itens, ícone ativo que se desenha, cartão do usuário com brilho, topo de vidro),
 * na cor de marca verde LawChat. O visual mora em estilo-navegacao.css (classes "lc-*").
 * No celular (até 820px) o menu vira gaveta por cima do conteúdo, que ocupa a largura toda.
 */

export { NomeDoEscritorio } from "./nomeEscritorio";

interface Item { para: string; rotulo: string; icone: ReactNode; contador?: number; grupo?: string }
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
  const telaCheia = local.pathname.startsWith("/atendimento");
  // Minha Conta: também em tela cheia, como a Central (as configurações da conta, com o menu delas e o "Voltar").
  const telaConta = /^\/(minha-conta|crm)(\/|$)/.test(local.pathname);
  const [visitou, setVisitou] = useState(false);
  useEffect(() => { if (telaCheia) setVisitou(true); }, [telaCheia]);
  useEffect(() => { if (!telaCheia && !telaConta) guardarTelaDoPainel(local.pathname + local.search); }, [telaCheia, telaConta, local.pathname, local.search]);
  const atendimentoVisitado = visitou || telaCheia;
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
      { para: "/admin/cobranca?aba=recargas", rotulo: "Recargas", icone: <CreditCard className="i" /> },
      { para: "/admin/cobranca?aba=carteiras", rotulo: "Financeiro", icone: <Wallet className="i" /> },
      { para: "/admin/erros", rotulo: "Erros da IA", icone: <AlertOctagon className="i" /> },
      { para: "/admin/equipe", rotulo: "Usuários admin", icone: <Users className="i" /> },
    ] });
  } else {
    const itens: Item[] = [];
    if (escritorio) {
      itens.push({ para: "/", rotulo: "Dashboard", icone: <Home className="i" /> });
      // Um só caminho para os agentes: "Meus agentes" (os produtos ativados) com o "+ Novo a partir da Biblioteca".
      // A Biblioteca fica como página de escolha; /agentes leva para cá e o agente aberto vira submenu deste item.
      if (podeGerir) itens.push(
        { para: "/meus-produtos", rotulo: "Meus agentes", icone: <Bot className="i" /> },
        { para: "/biblioteca", rotulo: "Biblioteca", icone: <Library className="i" /> },
      );
      itens.push({ para: "/atendimento", rotulo: "Central de Atendimento", icone: <Headset className="i" /> });
      itens.push({ para: "/crm/paineis", rotulo: "CRM", icone: <Workflow className="i" /> });
      if (podeGerir) itens.push(
        { para: "/ferramentas", rotulo: "Ferramentas", icone: <Wrench className="i" /> },
        { para: "/consumo", rotulo: "Créditos", icone: <Wallet className="i" /> },
        { para: "/minha-conta/usuarios", rotulo: "Minha Conta", icone: <Settings className="i" /> },
      );
    }
    grupos.push({ titulo: "Menu", itens });
  }
  const todosItens = grupos.flatMap((g) => g.itens.map((i) => ({ ...i, grupo: g.titulo })));
  const subtitulo = lawchat && !impersonando ? "Equipe LawChat" : impersonando ? nomeEscritorio : eu?.nome_escritorio ?? "";

  // Busca, avisos, Admin, ajuda e a foto: na barra do topo e também na faixa da Central de Atendimento.
  const acoesTopo = (
    <>
        <button type="button" className="lc-busca" onClick={() => setBusca(true)} aria-label="Buscar em tudo (Ctrl K)">
          <Search /><span>Buscar em tudo</span><kbd>Ctrl K</kbd>
        </button>
        <div className="lc-pilula">
          {podeGerir && escritorio && (
            <Link to={lawchat ? "/admin/erros" : "/erros"} className="lc-ico" aria-label={erros ? `${erros} erros abertos` : "Erros"} title="Erros abertos">
              <Bell className="lc-sino" />{erros > 0 && <span className="lc-badge num">{erros > 9 ? "9+" : erros}</span>}
            </Link>
          )}
          {lawchat && !impersonando && !modoAdmin && (
            <Link to="/admin/escritorios" className="lc-btn-admin" title="Entrar no modo superadmin"><ShieldCheck />Admin</Link>
          )}
          <button type="button" className="lc-ico" onClick={() => setAjuda(true)} aria-label="Ajuda" title="Ajuda"><CircleHelp /></button>
          {eu && <span className="lc-topo-av" title={`${eu.nome} · ${NOME_PAPEL[eu.papel]}`}>{lawchat ? <img src={fotoLawChat} alt="" className="lc-av-foto" /> : iniciaisDe(eu.nome)}</span>}
        </div>
    </>
  );

  // Central de Atendimento: tela própria, sem menu lateral, barra do topo nem atalhos (a tela traz o "Voltar").
  // A Central de Atendimento fica montada depois da 1ª visita (só escondida quando você sai): voltar para ela
  // mantém a conversa aberta. Recomeça só ao trocar de escritório ou fechar a aba do navegador.
  const atendimento = atendimentoVisitado && escritorio ? (
    <NomeDoEscritorio.Provider value={nomeEscritorio}>
      <div className="lc-modo-atendimento" key={`${escritorio}-${visao}`} style={telaCheia ? undefined : { display: "none" }} aria-hidden={!telaCheia}>
        <TelaAtendimento acoes={acoesTopo} />
      </div>
    </NomeDoEscritorio.Provider>
  ) : null;

  return (<>
    {atendimento}
    <CamadaLawChat escritorio={escritorio || null} escondida={telaCheia} />
        {busca && createPortal(<BuscaRapida itens={todosItens} aoFechar={() => setBusca(false)} />, document.body)}
        {ajuda && (
          <Modal titulo="Ajuda rápida" aoFechar={() => setAjuda(false)} rodape={<><span className="sp" /><button className="btn pri" onClick={() => setAjuda(false)}>Entendi</button></>}>
            <div className="form">
              <p className="sec" style={{ margin: 0 }}><b>Ctrl K</b> abre a busca de telas. <b>Ctrl B</b> recolhe o menu lateral. O <b>botão redondo</b> no canto abre os atalhos.</p>
              <p className="sec" style={{ margin: 0 }}>Para colocar um agente no ar: <b>Meus agentes</b> → <b>Novo a partir da Biblioteca</b> → escolha o produto → <b>Ativar</b>. Prompt, follow-up, conhecimento e Laboratório ficam no cartão de cada agente.</p>
              <p className="sec" style={{ margin: 0 }}>As conversas ficam na <b>Central de Atendimento</b>. Aqui ficam a IA, a configuração e o acompanhamento.</p>
            </div>
          </Modal>
        )}
    {telaCheia ? (escritorio ? null : children) : telaConta && escritorio ? (
      <NomeDoEscritorio.Provider value={nomeEscritorio}>
        <AcoesDoTopo.Provider value={acoesTopo}>
          <div className="lc-modo-atendimento lc-modo-conta" key={`${escritorio}-${visao}`}>{children}</div>
        </AcoesDoTopo.Provider>
      </NomeDoEscritorio.Provider>
    ) : (
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
            <Link to="/" className="lc-marca" title="Início">
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
                      <ItemMenu item={i} compacto={compacto} end={i.para === "/"} ativo={i.para === "/meus-produtos" && Boolean(idAgente)} />
                      {i.para === "/crm" && local.pathname.startsWith("/crm") && !compacto && (
                        <div className="lc-sub">
                          <div className="lc-sub-itens">
                            {PAGINAS_CRM.map((p) => (
                              <NavLink key={p.codigo} to={`/crm/${p.codigo}`}><p.icone size={14} /><span>{p.rotulo}</span></NavLink>
                            ))}
                          </div>
                        </div>
                      )}
                      {i.para === "/minha-conta" && local.pathname.startsWith("/minha-conta") && !compacto && (
                        <div className="lc-sub">
                          <div className="lc-sub-itens">
                            {PAGINAS_CONTA.map((p) => (
                              <NavLink key={p.codigo} to={`/minha-conta/${p.codigo}`}><p.icone size={14} /><span>{p.rotulo}</span></NavLink>
                            ))}
                          </div>
                        </div>
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
                              <NavLink to={`/agentes/${idAgente}`} end><LayoutGrid size={14} /><span>Visão geral</span></NavLink>
                              {secoesDo(agenteAberto.dados.tipo_produto === "proprio").map((s) => (
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
            <nav className="lc-crumb" aria-label="Você está em">
              <span className="lc-crumb-esc">{escritorio ? nomeEscritorio : "LawChat"}</span>
              <ChevronRight className="lc-crumb-sep" aria-hidden />
              <span className="lc-crumb-atual">{titulo}</span>
            </nav>
            <div className="lc-sp" />
            {escritorio && podeGerir && !modoAdmin && <SaldoTopo escritorio={escritorio} />}
            {acoesTopo}
          </header>
          <ImpersonationBanner nomeEscritorio={nomeEscritorio} />
          {modoAdmin && (
            <div className="lc-faixa-superadmin" role="status">
              <ShieldCheck aria-hidden />
              <span><b>Modo superadmin</b> · as ações aqui valem para todos os escritórios</span>
              <button type="button" className="lc-faixa-voltar" onClick={voltarParaConta}>Voltar para a conta</button>
            </div>
          )}
          {escritorio && <AvisoSaldo escritorio={escritorio} podeGerir={podeGerir} />}
          <div className="scroll"><main className="page" key={`${escritorio}-${visao}`}>{children}</main></div>
        </div>

      </div>
    </MotionConfig>
    )}
  </>);
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
        <div className="busca-lista">
          {achados.length === 0 ? <p className="muted" style={{ padding: 14, margin: 0 }}>Nada encontrado.</p> : achados.map((i, n) => (
            <button key={i.para} className={n === indice ? "on" : ""} onMouseEnter={() => setIndice(n)} onClick={() => ir(i)}>
              {i.icone}<span>{i.rotulo}</span><small>{i.grupo}</small>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
