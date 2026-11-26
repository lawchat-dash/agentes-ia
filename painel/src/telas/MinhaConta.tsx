import { useContext, useEffect, useRef, useState, type CSSProperties } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Settings, Workflow, ArrowRight, Blocks, Building2, Clock, Contact, MessagesSquare, ExternalLink, FileText, Gauge, KanbanSquare, Plug, RefreshCw, Users, UsersRound } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Alerta } from "../componentes/ui";
import { TelaIntegracoes } from "./Integracoes";
import { estiloDaCentral, estiloDoQuadro, estiloDoQuadroConfig } from "./Atendimento";
import { abrirEmJanela, preabrirLawChat, recarregarLawChat, useVagaLawChat } from "../componentes/camadaLawChat";
import { AcoesDoTopo, NomeDoEscritorio, telaDoPainel } from "../componentes/nomeEscritorio";
import { BolinhaControleIA } from "../componentes/ControleIA";

/** Minha Conta: os ajustes da conta na LawChat (abertos aqui dentro, já logados) + as integrações da IA. */
export interface PaginaConta { codigo: string; rotulo: string; resumo: string; emoji: string; icone: LucideIcon; cor: string; fundo: string }

export const PAGINAS_CONTA: PaginaConta[] = [
  { codigo: "usuarios", rotulo: "Usuários", resumo: "Quem acessa a conta, papéis e convites da equipe.", emoji: "👥", icone: Users, cor: "#2563eb", fundo: "#eff6ff" },
  { codigo: "equipes", rotulo: "Equipes", resumo: "Departamentos e quem atende em cada um.", emoji: "🗂️", icone: UsersRound, cor: "#7c3aed", fundo: "#f5f3ff" },
  { codigo: "modelos", rotulo: "Modelos de mensagens", resumo: "Modelos aprovados do WhatsApp para iniciar conversas.", emoji: "✉️", icone: FileText, cor: "#0891b2", fundo: "#ecfeff" },
  { codigo: "conta", rotulo: "Conta", resumo: "Dados da empresa, horário, canais e consumo.", emoji: "🏢", icone: Building2, cor: "#475467", fundo: "#f2f4f7" },
  { codigo: "integracoes", rotulo: "Integrações", resumo: "Integrações da conta: canais, webhooks e apps.", emoji: "🔗", icone: Blocks, cor: "#16a34a", fundo: "#f0fdf4" },
  { codigo: "ia", rotulo: "Integrações da IA", resumo: "Números de WhatsApp da IA, CRM e ZapSign do contrato.", emoji: "🤖", icone: Plug, cor: "#00a32c", fundo: "#e3f7e8" },
];

/** CRM: contatos e painéis da conta na LawChat, abertos aqui dentro. */
export const PAGINAS_CRM: PaginaConta[] = [
  { codigo: "contatos", rotulo: "Contatos", resumo: "Todos os contatos da conta, com etiquetas e campos.", emoji: "📇", icone: Contact, cor: "#2563eb", fundo: "#eff6ff" },
  { codigo: "paineis", rotulo: "Painéis", resumo: "Os funis do CRM e os cartões de cada etapa.", emoji: "🗃️", icone: KanbanSquare, cor: "#7c3aed", fundo: "#f5f3ff" },
];

/** CRM: sem página escolhida abre os Painéis. */
export function TelaCrm() {
  const { pagina } = useParams();
  const atual = PAGINAS_CRM.find((p) => p.codigo === pagina) ?? PAGINAS_CRM[1];
  return <CrmTelaCheia atual={atual} />;
}

/** CRM em tela cheia, igual à Minha Conta: faixa com "Voltar", Contatos e Painéis no seletor escuro e a tela da
 *  LawChat ocupando o resto (as duas abrem juntas: trocar é instantâneo). */
function CrmTelaCheia({ atual }: { atual: PaginaConta }) {
  useEffect(() => {
    preabrirLawChat(PAGINAS_CRM.map((p) => ({ codigo: p.codigo, titulo: p.rotulo, estilo: estiloDoQuadro })));
  }, []);
  return (
    <div className="lc-tela-lawchat-cheia">
      <VagaDaConta key={atual.codigo} pagina={atual} estilo={estiloDoQuadro} />
    </div>
  );
}

/** Apps › Chatbots: a lista de chatbots da conta na LawChat, embaixo do menu do topo (mantém o menu dela, que tem as
 *  duas opções: atendimento e automação). */
export function TelaChatbots() {
  const vaga = useRef<HTMLDivElement>(null);
  useVagaLawChat(vaga, "chatbots", "Chatbots", estiloDoQuadro);
  return <div className="lc-tela-lawchat-cheia"><div ref={vaga} className="absolute inset-0" /></div>;
}

/** Central de Atendimento: a tela de conversas da LawChat embaixo do menu do topo (fica montada o tempo todo). */
export function TelaCentral() {
  const vaga = useRef<HTMLDivElement>(null);
  useVagaLawChat(vaga, "atendimento", "Central de Atendimento", estiloDaCentral);
  // Bolinha do Controle da IA: só enquanto a Central está na tela, presa na área dela.
  return <div className="lc-tela-lawchat-cheia"><div ref={vaga} className="absolute inset-0" /><BolinhaControleIA area={vaga} /></div>;
}

/** Dentro de "Conta": as telas de Configurações da conta na LawChat, como abas (o menu lateral delas sai). */
export const PAGINAS_CONFIG: PaginaConta[] = [
  { codigo: "conta", rotulo: "Dados da empresa", resumo: "Defina seus dados e os da sua empresa.", emoji: "🏢", icone: Building2, cor: "#475467", fundo: "#f2f4f7" },
  { codigo: "horario", rotulo: "Horário de atendimento", resumo: "Defina quando a empresa atende.", emoji: "🕘", icone: Clock, cor: "#475467", fundo: "#f2f4f7" },
  { codigo: "canais", rotulo: "Canais de atendimento", resumo: "Configure seus canais de atendimento.", emoji: "💬", icone: MessagesSquare, cor: "#475467", fundo: "#f2f4f7" },
  { codigo: "consumo", rotulo: "Consumo de mensagens", resumo: "Quantas mensagens seus canais enviam e quanto custa cada categoria.", emoji: "📊", icone: Gauge, cor: "#ea580c", fundo: "#fff7ed" },
];

export function TelaMinhaConta() {
  const { pagina } = useParams();
  const naConfig = PAGINAS_CONFIG.find((p) => p.codigo === pagina);
  const atual = naConfig ?? PAGINAS_CONTA.find((p) => p.codigo === pagina);
  if (!atual) return <Navigate to="/minha-conta/usuarios" replace />;
  return <ContaTelaCheia atual={atual} />;
}

/** Configurações da conta em tela cheia (como a Central): faixa com "Voltar", menu das configurações à esquerda
 *  (no lugar do menu da própria LawChat, que sai) e a tela escolhida ocupando o resto. */
function ContaTelaCheia({ atual }: { atual: PaginaConta }) {
  const navegar = useNavigate();
  const nomeEscritorio = useContext(NomeDoEscritorio);
  const acoes = useContext(AcoesDoTopo);
  const ehConfig = PAGINAS_CONFIG.some((p) => p.codigo === atual.codigo);
  const [erro, setErro] = useState<string | null>(null);
  // Ao entrar em Minha Conta, todas as telas começam a abrir por trás: trocar de aba depois é instantâneo.
  useEffect(() => {
    preabrirLawChat([
      ...PAGINAS_CONTA.filter((p) => p.codigo !== "ia" && p.codigo !== "conta").map((p) => ({ codigo: p.codigo, titulo: p.rotulo, estilo: estiloDoQuadro })),
      ...PAGINAS_CONFIG.map((p) => ({ codigo: p.codigo, titulo: p.rotulo, estilo: estiloDoQuadroConfig })),
    ]);
  }, []);
  const item = (p: PaginaConta, ativo: boolean, sub = false) => (
    <Link key={p.codigo} to={`/minha-conta/${p.codigo}`} aria-current={ativo ? "page" : undefined}
      className={`lc-conta-item${ativo ? " ativo" : ""}${sub ? " sub" : ""}`}>
      <p.icone size={sub ? 15 : 18} className="lc-conta-ico" />
      <span className="min-w-0">
        <span className="lc-conta-tit">{p.rotulo}</span>
        {!sub && p.resumo && <span className="lc-conta-res">{p.resumo}</span>}
      </span>
    </Link>
  );
  return (
    <div className="lc-tela-lawchat-cheia flex">
      <div className="flex min-h-0 flex-1">
        <aside className="lc-conta-menu" aria-label="Configurações">
          {ehConfig ? (
            // Entrou em "Conta": o menu vira o de Conta (como entrar numa pasta), com o Voltar para as Configurações.
            <div key="conta" className="lc-conta-menu-entra">
              <Link to="/minha-conta/usuarios" className="lc-conta-voltar"><ArrowLeft size={16} /> Voltar para Configurações</Link>
              <div className="lc-conta-menu-tit">Conta</div>
              {PAGINAS_CONFIG.map((c) => item(c, c.codigo === atual.codigo))}
            </div>
          ) : (
            <div key="geral" className="lc-conta-menu-entra">
              <div className="lc-conta-menu-tit">Configurações</div>
              {PAGINAS_CONTA.map((p) => item(p, p.codigo === atual.codigo))}
            </div>
          )}
        </aside>
        <main className="relative min-w-0 flex-1 bg-[var(--lc-fundo-lawchat)]">
          {erro && <div className="absolute left-4 right-4 top-4 z-30"><Alerta tipo="bad">{erro}</Alerta></div>}
          {atual.codigo === "ia" ? (
            <div className="h-full overflow-auto p-6"><TelaIntegracoes /></div>
          ) : (
            <VagaDaConta key={atual.codigo} pagina={atual} estilo={ehConfig ? estiloDoQuadroConfig : estiloDoQuadro} />
          )}
        </main>
      </div>
    </div>
  );
}

function VagaDaConta({ pagina, estilo }: { pagina: PaginaConta; estilo: CSSProperties }) {
  const vaga = useRef<HTMLDivElement>(null);
  useVagaLawChat(vaga, pagina.codigo, pagina.rotulo, estilo);
  return <div ref={vaga} className="absolute inset-0" />;
}

/** Página inicial: um cartão por ajuste. */
function HubDaConta() {
  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-[#eef1f5] bg-white px-6 py-5">
        <h1 className="text-[1.6rem] font-bold tracking-tight text-[#101828]">Minha Conta</h1>
        <p className="text-[13.5px] text-[#667085] mt-1">Usuários, equipes, modelos de mensagens e os dados da conta, direto da LawChat, sem sair do painel.</p>
      </div>
      <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))" }}>
        {PAGINAS_CONTA.map((p) => (
          <Link key={p.codigo} to={`/minha-conta/${p.codigo}`}
            className="group flex flex-col rounded-2xl border border-[#eef1f5] bg-white p-5 transition hover:border-[#d0d5dd] hover:shadow-[0_6px_20px_-12px_rgba(16,24,40,.25)]">
            <div className="flex items-center gap-3">
              <span className="grid size-10 place-items-center rounded-xl text-[20px]" style={{ background: p.fundo }} aria-hidden>{p.emoji}</span>
              <div className="min-w-0">
                <div className="text-[15px] font-semibold text-[#101828]">{p.rotulo}</div>
                <div className="text-[12px] font-medium" style={{ color: p.cor }}>{p.codigo === "ia" ? "Da IA" : "Da conta"}</div>
              </div>
            </div>
            <p className="mt-3 flex-1 text-[13px] leading-relaxed text-[#667085]">{p.resumo}</p>
            <div className="mt-4 flex items-center justify-between border-t border-[#f2f4f7] pt-3 text-[13px] text-[#475467]">
              <span>Abrir</span>
              <span className="grid size-7 place-items-center rounded-full border border-[#eef1f5] transition group-hover:translate-x-0.5" style={{ color: p.cor }}><ArrowRight size={14} /></span>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
