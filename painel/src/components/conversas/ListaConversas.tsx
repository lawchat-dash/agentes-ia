import { Link } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { Bot, ChevronDown, Inbox, MessagesSquare, RefreshCw, Search, SearchX, X } from "lucide-react";
import { formatarTelefone } from "../../api";
import { ESTADOS, corDoAvatar, estadoDaIa, iniciais, momentoCurto, nomeDoLead, nomeEtapa, previaDaConversa, type EstadoLead, type ResumoConversa } from "./tipos";

export type FiltroEstado = "todos" | EstadoLead;
/** Uma opção do filtro por agente: o id vai para a API (GET /api/conversas?id_agente=). */
export interface OpcaoAgente { id: string; nome: string }
const FILTROS: { valor: FiltroEstado; rotulo: string }[] = [
  { valor: "todos", rotulo: "Todas" },
  { valor: "ativo", rotulo: ESTADOS.ativo.plural },
  { valor: "pausado", rotulo: ESTADOS.pausado.plural },
  { valor: "encerrado", rotulo: ESTADOS.encerrado.plural },
];

/** Quantas conversas a API devolve no máximo (app/gestao/repositorio.py, conversas: limite=100). */
export const LIMITE_LISTA = 100;

interface Props {
  itens: ResumoConversa[];
  carregado: boolean;
  erro: string | null;
  atualizando: boolean;
  totalRecebido: number;
  contagens: Record<FiltroEstado, number>;
  busca: string;
  aoBuscar: (texto: string) => void;
  estado: FiltroEstado;
  aoFiltrarEstado: (estado: FiltroEstado) => void;
  /** Id do agente escolhido ("" = todos). */
  agente: string;
  agentes: OpcaoAgente[];
  aoFiltrarAgente: (agente: string) => void;
  selecionado: string | null;
  aoRecarregar: () => void;
  aoLimpar: () => void;
}

/** Coluna da esquerda: busca, filtros e a lista das conversas mais recentes. */
export function ListaConversas(p: Props) {
  const filtrando = p.estado !== "todos" || Boolean(p.agente) || Boolean(p.busca.trim());
  return (
    <section className="cv-lista lc-card relative" aria-label="Lista de conversas">
      <div className="p-3.5 pb-2.5 flex flex-col gap-2.5 border-b border-[#EEF1F5]">
        <div className="flex items-center justify-between gap-2">
          <h2 className="flex items-center gap-2 text-[15px] font-bold tracking-tight text-[#101828]">
            <span className="size-8 rounded-xl grid place-items-center" style={{ background: "#e8f9ee", color: "#00bc33" }}><MessagesSquare className="size-4" /></span>
            Conversas
          </h2>
          <button type="button" className="cv-icone-btn" onClick={p.aoRecarregar} disabled={p.atualizando} aria-label="Atualizar a lista" title="Atualizar">
            <RefreshCw className={p.atualizando ? "animate-spin" : ""} />
          </button>
        </div>

        <label className="cv-busca">
          <Search className="size-4 text-[#98A2B3] shrink-0" aria-hidden />
          <input value={p.busca} onChange={(e) => p.aoBuscar(e.target.value)} placeholder="Buscar por nome ou telefone" aria-label="Buscar por nome ou telefone"
            onKeyDown={(e) => { if (e.key === "Escape" && p.busca) { e.preventDefault(); p.aoBuscar(""); } }} />
          {p.busca && (
            <button type="button" onClick={() => p.aoBuscar("")} className="grid place-items-center size-6 rounded-md text-[#98A2B3] hover:text-[#101828]" aria-label="Limpar busca"><X className="size-3.5" /></button>
          )}
        </label>

        <div className="cv-filtros" role="radiogroup" aria-label="Filtrar pelo estado da conversa">
          {FILTROS.map((f) => {
            const on = p.estado === f.valor;
            return (
              <button key={f.valor} type="button" role="radio" aria-checked={on} className="cv-filtro" onClick={() => p.aoFiltrarEstado(f.valor)}>
                {on && <motion.span layoutId="cv-filtro-ativo" className="cv-filtro-fundo" transition={{ type: "spring", stiffness: 420, damping: 34 }} />}
                {f.valor !== "todos" && <span className="size-1.5 rounded-full" style={{ background: ESTADOS[f.valor].cor }} aria-hidden />}
                <span>{f.rotulo}</span>
                {p.carregado && <span className="cv-cnt">{p.contagens[f.valor]}</span>}
              </button>
            );
          })}
        </div>

        {(p.agentes.length > 1 || Boolean(p.agente)) && (
          <div className="relative">
            <Bot className="size-3.5 text-[#98A2B3] absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" aria-hidden />
            <select className="cv-select" style={{ paddingLeft: 28 }} value={p.agente} onChange={(e) => p.aoFiltrarAgente(e.target.value)} aria-label="Filtrar por agente">
              <option value="">Todos os agentes</option>
              {p.agentes.map((a) => <option key={a.id} value={a.id}>{a.nome}</option>)}
            </select>
            <ChevronDown className="size-3.5 text-[#98A2B3] absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" aria-hidden />
          </div>
        )}
      </div>

      <div className="cv-itens" aria-busy={!p.carregado}>
        {!p.carregado && !p.erro ? (
          <Esqueleto />
        ) : p.erro && !p.carregado ? (
          <div className="cv-vazio">
            <div>
              <div className="mx-auto size-11 rounded-2xl grid place-items-center bg-[#FDE8E8] text-[#DC2626]"><X className="size-5" /></div>
              <p className="mt-3 text-[13px] font-semibold text-[#344054]">Não deu para carregar as conversas</p>
              <p className="mt-1 text-[12px] text-[#667085]">{p.erro}</p>
              <button type="button" className="cv-botao sm mt-3 mx-auto" onClick={p.aoRecarregar}><RefreshCw /> Tentar de novo</button>
            </div>
          </div>
        ) : p.itens.length === 0 ? (
          <div className="cv-vazio">
            {filtrando ? (
              <div>
                <div className="mx-auto size-11 rounded-2xl grid place-items-center bg-[#F1F5F9] text-[#667085]"><SearchX className="size-5" /></div>
                <p className="mt-3 text-[13px] font-semibold text-[#344054]">Nenhuma conversa com esses filtros</p>
                <button type="button" className="cv-botao sm mt-3 mx-auto" onClick={p.aoLimpar}>Limpar filtros</button>
              </div>
            ) : (
              <div>
                <div className="mx-auto size-11 rounded-2xl grid place-items-center bg-[#e8f9ee] text-[#00bc33]"><Inbox className="size-5" /></div>
                <p className="mt-3 text-[13px] font-semibold text-[#344054]">Nenhuma conversa ainda</p>
                <p className="mt-1 text-[12px] text-[#667085] max-w-[15rem] mx-auto">Quando um lead mandar mensagem no WhatsApp de um agente, a conversa aparece aqui.</p>
              </div>
            )}
          </div>
        ) : (
          <ul className="flex flex-col gap-0.5" role="list">
            <AnimatePresence initial={false}>
              {p.itens.map((c, i) => <ItemConversa key={c.id} conversa={c} ativo={c.id === p.selecionado} ordem={i} />)}
            </AnimatePresence>
          </ul>
        )}
        {p.carregado && p.totalRecebido >= LIMITE_LISTA && (
          <p className="px-2 pt-3 text-center text-[11px] text-[#98A2B3]">Mostrando as {LIMITE_LISTA} conversas mais recentes. Use a busca para achar outras.</p>
        )}
      </div>
    </section>
  );
}

function ItemConversa({ conversa: c, ativo, ordem }: { conversa: ResumoConversa; ativo: boolean; ordem: number }) {
  const nome = nomeDoLead(c);
  const estado = estadoDaIa(c);
  const momento = c.ultima_mensagem_lead_em ?? c.ultima_resposta_ia_em ?? c.criado_em;
  return (
    <motion.li layout="position" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
      transition={{ duration: 0.22, delay: Math.min(ordem, 12) * 0.015, ease: [0.22, 1, 0.36, 1] }}>
      <Link to={`/conversas/${c.id}`} className="cv-item" aria-current={ativo ? "page" : undefined}>
        {ativo && <motion.span layoutId="cv-item-ativo" className="cv-item-fundo" transition={{ type: "spring", stiffness: 420, damping: 36 }} />}
        <span className="cv-av" style={{ background: corDoAvatar(c.id) }} aria-hidden>
          {iniciais(nome)}
          <i className="cv-av-ponto" style={{ background: estado.cor }} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline gap-2">
            <span className="flex-1 min-w-0 truncate text-[13.5px] font-semibold text-[#101828]">{nome}</span>
            <span className="shrink-0 text-[11px] text-[#98A2B3] tabular-nums">{momentoCurto(momento)}</span>
          </span>
          <span className="block truncate text-[12.5px] text-[#667085] mt-0.5">{previaDaConversa(c) || <i className="text-[#98A2B3]">sem mensagens</i>}</span>
          <span className="flex items-center gap-1.5 mt-1 min-w-0">
            <span className="inline-flex items-center gap-1 rounded-md px-1.5 py-px text-[10px] font-bold uppercase tracking-wide shrink-0" style={{ background: estado.fundo, color: estado.cor }} title={estado.rotulo}>{estado.rotulo}</span>
            <span className="truncate text-[11px] text-[#98A2B3]">
              {[c.agente, c.etapa ? nomeEtapa(c.etapa) : null, c.nome ? formatarTelefone(c.telefone) : null].filter(Boolean).join(" · ")}
            </span>
          </span>
        </span>
      </Link>
    </motion.li>
  );
}

function Esqueleto() {
  return (
    <div className="flex flex-col gap-1 p-1" role="status" aria-label="Carregando conversas">
      {Array.from({ length: 7 }, (_, i) => (
        <div key={i} className="flex gap-2.5 p-2">
          <div className="carregando-brilho rounded-full" style={{ width: 42, height: 42, flex: "none" }} />
          <div className="flex-1 flex flex-col gap-1.5 pt-1">
            <div className="carregando-brilho" style={{ height: 12, width: `${55 + ((i * 17) % 30)}%` }} />
            <div className="carregando-brilho" style={{ height: 10, width: `${70 + ((i * 11) % 25)}%` }} />
            <div className="carregando-brilho" style={{ height: 9, width: "35%" }} />
          </div>
        </div>
      ))}
    </div>
  );
}
