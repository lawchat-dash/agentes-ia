import { useRef, useState, type CSSProperties } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowRight, Blocks, Building2, Clock, Contact, MessagesSquare, ExternalLink, FileText, Gauge, KanbanSquare, Plug, RefreshCw, Users, UsersRound } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Alerta } from "../componentes/ui";
import { TelaIntegracoes } from "./Integracoes";
import { estiloDoQuadro, estiloDoQuadroConfig } from "./Atendimento";
import { abrirEmJanela, recarregarLawChat, useVagaLawChat } from "../componentes/camadaLawChat";

/** Minha Conta: os ajustes da conta na LawChat (abertos aqui dentro, já logados) + as integrações da IA. */
export interface PaginaConta { codigo: string; rotulo: string; resumo: string; emoji: string; icone: LucideIcon; cor: string; fundo: string }

export const PAGINAS_CONTA: PaginaConta[] = [
  { codigo: "usuarios", rotulo: "Usuários", resumo: "Quem acessa a conta, papéis e convites da equipe.", emoji: "👥", icone: Users, cor: "#2563eb", fundo: "#eff6ff" },
  { codigo: "equipes", rotulo: "Equipes", resumo: "Departamentos e quem atende em cada um.", emoji: "🗂️", icone: UsersRound, cor: "#7c3aed", fundo: "#f5f3ff" },
  { codigo: "modelos", rotulo: "Modelos de mensagens", resumo: "Modelos aprovados do WhatsApp para iniciar conversas.", emoji: "✉️", icone: FileText, cor: "#0891b2", fundo: "#ecfeff" },
  { codigo: "conta", rotulo: "Conta", resumo: "Dados da empresa, endereço e plano da conta.", emoji: "🏢", icone: Building2, cor: "#475467", fundo: "#f2f4f7" },
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
  return <AjusteDaConta key={atual.codigo} pagina={atual} grupo={PAGINAS_CRM} base="/crm" />;
}

/** Dentro de "Conta": as telas de Configurações da conta na LawChat, como abas (o menu lateral delas sai). */
export const PAGINAS_CONFIG: PaginaConta[] = [
  { codigo: "conta", rotulo: "Dados da empresa", resumo: "", emoji: "🏢", icone: Building2, cor: "#475467", fundo: "#f2f4f7" },
  { codigo: "horario", rotulo: "Horário de atendimento", resumo: "", emoji: "🕘", icone: Clock, cor: "#475467", fundo: "#f2f4f7" },
  { codigo: "canais", rotulo: "Canais de atendimento", resumo: "", emoji: "💬", icone: MessagesSquare, cor: "#475467", fundo: "#f2f4f7" },
  { codigo: "consumo", rotulo: "Consumo de mensagens", resumo: "", emoji: "📊", icone: Gauge, cor: "#ea580c", fundo: "#fff7ed" },
];

export function TelaMinhaConta() {
  const { pagina } = useParams();
  const config = PAGINAS_CONFIG.find((p) => p.codigo === pagina);
  if (config) {
    return <AjusteDaConta key={config.codigo} pagina={config} grupo={PAGINAS_CONTA.filter((p) => p.codigo !== "ia")} base="/minha-conta"
      ativo="conta" subgrupo={PAGINAS_CONFIG} estilo={estiloDoQuadroConfig} />;
  }
  const atual = PAGINAS_CONTA.find((p) => p.codigo === pagina);
  if (!atual) return <HubDaConta />;
  if (atual.codigo === "ia") return <TelaIntegracoes />;
  return <AjusteDaConta key={atual.codigo} pagina={atual} grupo={PAGINAS_CONTA.filter((p) => p.codigo !== "ia")} base="/minha-conta" />;
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

/** Uma tela da LawChat dentro do painel: as abas do grupo e a vaga onde a camada (sempre montada) mostra o quadro.
 *  Sem moldura e no mesmo fundo da LawChat, para parecer uma tela só. */
function AjusteDaConta({ pagina, grupo, base, ativo, subgrupo, estilo = estiloDoQuadro }: {
  pagina: PaginaConta; grupo: PaginaConta[]; base: string; ativo?: string; subgrupo?: PaginaConta[]; estilo?: CSSProperties;
}) {
  const aceso = ativo ?? pagina.codigo;
  const vaga = useRef<HTMLDivElement>(null);
  useVagaLawChat(vaga, pagina.codigo, pagina.rotulo, estilo);
  const [erro, setErro] = useState<string | null>(null);
  return (
    <div className="lc-tela-lawchat">
      <div className="lc-tela-lawchat-abas">
        {/* Abas do grupo (o menu lateral fica recolhido nestas telas). */}
        <nav className="flex min-w-0 items-center gap-1 overflow-x-auto" aria-label="Telas">
          {grupo.map((p) => (
            <Link key={p.codigo} to={`${base}/${p.codigo}`} aria-current={p.codigo === aceso ? "page" : undefined}
              className={`inline-flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[13px] font-semibold transition ${p.codigo === aceso ? "bg-white text-[#101828] shadow-[0_1px_3px_rgba(16,24,40,.12)]" : "text-[#667085] hover:text-[#101828]"}`}>
              <span aria-hidden>{p.emoji}</span>{p.rotulo}
            </Link>
          ))}
        </nav>
        <span className="flex shrink-0 gap-1">
          <button type="button" className="btn ghost sm" onClick={() => recarregarLawChat(pagina.codigo)} title="Recarregar esta tela"><RefreshCw size={14} /></button>
          <button type="button" className="btn ghost sm" onClick={() => abrirEmJanela(pagina.codigo).catch((e) => setErro((e as Error).message))} title="Use se a tela ficar em branco ou pedir login"><ExternalLink size={14} /> Janela separada</button>
        </span>
      </div>
      {erro && <div className="px-1 pb-2"><Alerta tipo="bad">{erro}</Alerta></div>}
      {subgrupo && (
        <nav className="lc-tela-lawchat-sub" aria-label="Configurações da conta">
          {subgrupo.map((p) => (
            <Link key={p.codigo} to={`${base}/${p.codigo}`} aria-current={p.codigo === pagina.codigo ? "page" : undefined}
              className={`-mb-px inline-flex shrink-0 items-center gap-1.5 border-b-2 py-2.5 text-[13px] font-semibold transition ${p.codigo === pagina.codigo ? "border-[#00bc33] text-[#101828]" : "border-transparent text-[#667085] hover:text-[#101828]"}`}>
              <p.icone size={14} />{p.rotulo}
            </Link>
          ))}
        </nav>
      )}
      <div ref={vaga} className="lc-tela-lawchat-vaga" />
    </div>
  );
}
