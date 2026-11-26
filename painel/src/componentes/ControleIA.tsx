import { useCallback, useEffect, useLayoutEffect, useRef, useState, type PointerEvent as EventoPonteiro, type RefObject } from "react";
import { Bot, Loader2, PauseCircle, PlayCircle, RefreshCw, Search, X } from "lucide-react";
import { api, enviar } from "../api";
import "./controleIA.css";

/**
 * Controle da IA na Central de Atendimento: bolinha flutuante (arrastável, presa na área da Central) que mostra se a IA
 * do lead da conversa aberta está ligada e deixa desativar/reativar. A conversa aberta vem do app "Controle da IA" da
 * plataforma (página-ponte /controle-ia/ponte, ver PonteControleIA.tsx), que avisa por postMessage com o tipo
 * MENSAGEM_CONVERSA. Sem esse aviso, busca o lead pelo nome ou telefone (plano B).
 * Backend: app/gestao/rotas_controle_ia.py (mesmo serviço da tela Conversas: nota, etiqueta e histórico).
 */

export const MENSAGEM_CONVERSA = "lawchat-conversa-aberta";

export interface Alvo { sessao?: string; contato?: string; telefone?: string; conta?: string }

export interface LeadIA {
  id_lead: string; nome: string; telefone: string | null; agente: string | null; etapa: string | null;
  etapa_nome: string | null; estado: string; ia_ligada: boolean; encerrado: boolean; motivo: string | null;
  pausado_ate: string | null; tem_atendimento: boolean; ia_desligada_escritorio: boolean; por?: string;
}

interface RespostaAcao { ok: boolean; mudou: boolean; mensagem: string; lead: LeadIA }

const PRAZOS: { minutos: number; rotulo: string }[] = [
  { minutos: 0, rotulo: "Até religar" }, { minutos: 30, rotulo: "30 min" }, { minutos: 120, rotulo: "2 h" }, { minutos: 1440, rotulo: "24 h" },
];
const POR: Record<string, string> = { sessao: "pelo atendimento aberto", contato: "pelo contato", telefone: "pelo telefone" };

function dataCurta(iso: string | null): string {
  if (!iso) return "";
  try { return new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }); } catch { return iso; }
}

/** Alvo vindo de um aviso da ponte (só do próprio painel, só com o tipo certo). */
export function alvoDaMensagem(e: MessageEvent): Alvo | null {
  if (e.origin !== window.location.origin) return null;
  const d = e.data as Record<string, unknown> | null;
  if (!d || typeof d !== "object" || d.tipo !== MENSAGEM_CONVERSA) return null;
  const txt = (v: unknown) => (typeof v === "string" && v.trim() ? v.trim().slice(0, 80) : undefined);
  const alvo: Alvo = { sessao: txt(d.sessao), contato: txt(d.contato), telefone: txt(d.telefone), conta: txt(d.conta) };
  return alvo.sessao || alvo.contato || alvo.telefone ? alvo : null;
}

/** Lead do alvo e as ações sobre ele. `ativo`: atualiza o status a cada 20 s. */
export function useLeadIA(alvo: Alvo | null, ativo: boolean) {
  const [lead, setLead] = useState<LeadIA | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [ocupado, setOcupado] = useState(false);
  const [aviso, setAviso] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const escolhido = useRef<string | null>(null);   // lead escolhido na busca (sem alvo)
  const vez = useRef(0);

  const carregar = useCallback(async (silencioso = false) => {
    const minha = ++vez.current;
    if (!silencioso) setCarregando(true);
    try {
      let novo: LeadIA | null = null;
      if (escolhido.current) {
        const lista = await api<LeadIA[]>(`/controle-ia/buscar?q=${encodeURIComponent(escolhido.current)}${alvo?.conta ? `&conta=${encodeURIComponent(alvo.conta)}` : ""}`);
        novo = lista.find((l) => l.id_lead === lead?.id_lead) ?? null;
        if (minha !== vez.current) return;
        if (novo) setLead({ ...novo });
        setErro(null);
        return;
      }
      if (alvo) {
        const p = new URLSearchParams();
        if (alvo.sessao) p.set("sessao", alvo.sessao);
        if (alvo.contato) p.set("contato", alvo.contato);
        if (alvo.telefone) p.set("telefone", alvo.telefone);
        if (alvo.conta) p.set("conta", alvo.conta);
        novo = await api<LeadIA>(`/controle-ia/lead?${p}`);
      }
      if (minha !== vez.current) return;
      setLead(novo);
      setErro(null);
    } catch (e) {
      if (minha !== vez.current) return;
      setLead(null);
      setErro((e as Error).message);
    } finally {
      if (minha === vez.current) setCarregando(false);
    }
  }, [alvo, lead?.id_lead]);

  // Trocou a conversa aberta: busca o lead dela na hora.
  useEffect(() => {
    setAviso(null);
    if (alvo) { escolhido.current = null; setEscolhidoNaBusca(false); void carregar(); } else if (!escolhido.current) { setLead(null); setErro(null); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [alvo]);

  useEffect(() => {
    if (!ativo || (!alvo && !lead)) return;
    const t = window.setInterval(() => { if (document.visibilityState === "visible") void carregar(true); }, 20_000);
    return () => window.clearInterval(t);
  }, [ativo, alvo, lead, carregar]);

  const [escolhidoNaBusca, setEscolhidoNaBusca] = useState(false);
  const escolher = (l: LeadIA) => { vez.current++; escolhido.current = l.nome; setEscolhidoNaBusca(true); setLead(l); setErro(null); setAviso(null); setCarregando(false); };
  const limpar = () => { vez.current++; escolhido.current = null; setEscolhidoNaBusca(false); setLead(null); setAviso(null); if (alvo) void carregar(); };

  const agir = async (acao: "desativar" | "reativar", minutos = 0) => {
    if (!lead || ocupado) return;
    setOcupado(true); setAviso(null);
    try {
      const corpo = acao === "desativar" ? { id_lead: lead.id_lead, minutos, conta: alvo?.conta } : { id_lead: lead.id_lead, conta: alvo?.conta };
      const r = await enviar<RespostaAcao>(`/controle-ia/${acao}`, corpo);
      setLead({ ...r.lead, por: lead.por });
      setAviso({ tipo: "ok", texto: r.mensagem });
    } catch (e) {
      setAviso({ tipo: "erro", texto: (e as Error).message });
    } finally {
      setOcupado(false);
    }
  };

  return { lead, erro, carregando, ocupado, aviso, carregar, escolher, limpar, agir, escolhido: escolhidoNaBusca };
}

/** Status do lead e botões (usado no popup da bolinha e na ponte aberta sozinha). */
export function PainelDoLead({ ctl, alvo, aoBuscar = true }: { ctl: ReturnType<typeof useLeadIA>; alvo: Alvo | null; aoBuscar?: boolean }) {
  const { lead, erro, carregando, ocupado, aviso, agir } = ctl;
  const [prazo, setPrazo] = useState(0);
  const [trocandoPrazo, setTrocandoPrazo] = useState(false);
  useEffect(() => { setTrocandoPrazo(false); }, [lead?.id_lead]);

  if (carregando && !lead) return <div className="cia-vazio"><Loader2 size={18} className="cia-gira" /> Procurando o lead desta conversa…</div>;
  if (!lead) {
    return (
      <>
        {alvo && erro && <div className="cia-aviso erro">{erro}</div>}
        {!alvo && <p className="cia-dica">Não deu para saber qual conversa está aberta. Busque o lead pelo nome ou telefone:</p>}
        {aoBuscar && <BuscaDeLead aoEscolher={ctl.escolher} />}
      </>
    );
  }
  const estado = lead.encerrado ? "cinza" : lead.ia_ligada ? "verde" : "vermelho";
  const seletor = (
    <div className="cia-prazos" role="radiogroup" aria-label="Por quanto tempo">
      {PRAZOS.map((p) => (
        <button key={p.minutos} type="button" role="radio" aria-checked={prazo === p.minutos}
          className={prazo === p.minutos ? "on" : ""} onClick={() => setPrazo(p.minutos)}>{p.rotulo}</button>
      ))}
    </div>
  );
  return (
    <>
      <div className="cia-lead">
        <div className="cia-avatar" aria-hidden>{(lead.nome || "?").trim().charAt(0).toUpperCase()}</div>
        <div className="cia-lead-txt">
          <b title={lead.nome}>{lead.nome}</b>
          <span>{lead.telefone ?? "Sem telefone"}{lead.por ? ` · achado ${POR[lead.por] ?? ""}` : ""}</span>
        </div>
      </div>
      <dl className="cia-info">
        {lead.agente && <><dt>Agente</dt><dd>{lead.agente}</dd></>}
        {lead.etapa_nome && <><dt>Etapa</dt><dd>{lead.etapa_nome}</dd></>}
      </dl>
      <div className={`cia-status ${estado}`}>
        <i aria-hidden />
        <div>
          <b>{lead.encerrado ? "Conversa encerrada" : lead.ia_ligada ? "IA ligada" : "IA desativada"}</b>
          <span>
            {lead.encerrado ? "A IA não atende mais esta conversa."
              : lead.ia_ligada ? "Ela responde as próximas mensagens do lead."
              : lead.pausado_ate ? `Volta sozinha em ${dataCurta(lead.pausado_ate)}.` : (lead.motivo ? `${lead.motivo}. ` : "") + "Fica desligada até alguém religar."}
          </span>
        </div>
      </div>
      {lead.ia_desligada_escritorio && <div className="cia-aviso alerta">A IA está desligada para o escritório inteiro: mesmo ligada aqui, ela não responde.</div>}
      {!lead.encerrado && lead.ia_ligada && (
        <div className="cia-acao">
          <span className="cia-rotulo">Desativar por</span>
          {seletor}
          <button type="button" className="cia-btn perigo" disabled={ocupado} onClick={() => void agir("desativar", prazo)}>
            {ocupado ? <Loader2 size={15} className="cia-gira" /> : <PauseCircle size={15} />} Desativar IA
          </button>
        </div>
      )}
      {!lead.encerrado && !lead.ia_ligada && (
        <div className="cia-acao">
          <button type="button" className="cia-btn sucesso" disabled={ocupado} onClick={() => void agir("reativar")}>
            {ocupado ? <Loader2 size={15} className="cia-gira" /> : <PlayCircle size={15} />} Reativar IA
          </button>
          {trocandoPrazo ? (
            <>
              {seletor}
              <button type="button" className="cia-btn" disabled={ocupado} onClick={() => void agir("desativar", prazo)}>Trocar o prazo</button>
            </>
          ) : (
            <button type="button" className="cia-link" onClick={() => setTrocandoPrazo(true)}>Trocar o prazo da desativação</button>
          )}
        </div>
      )}
      {aviso && <div className={`cia-aviso ${aviso.tipo}`} role="status">{aviso.texto}</div>}
    </>
  );
}

function BuscaDeLead({ aoEscolher }: { aoEscolher: (l: LeadIA) => void }) {
  const [q, setQ] = useState("");
  const [lista, setLista] = useState<LeadIA[]>([]);
  const [buscando, setBuscando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  useEffect(() => {
    const termo = q.trim();
    if (termo.length < 2) { setLista([]); setErro(null); return; }
    let vale = true;
    const t = window.setTimeout(() => {
      setBuscando(true);
      api<LeadIA[]>(`/controle-ia/buscar?q=${encodeURIComponent(termo)}`)
        .then((r) => { if (vale) { setLista(r); setErro(null); } })
        .catch((e) => { if (vale) setErro((e as Error).message); })
        .finally(() => { if (vale) setBuscando(false); });
    }, 300);
    return () => { vale = false; window.clearTimeout(t); };
  }, [q]);
  return (
    <div className="cia-busca">
      <label className="cia-campo">
        <Search size={15} aria-hidden />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Nome ou telefone do lead" aria-label="Buscar lead" autoFocus />
        {buscando && <Loader2 size={14} className="cia-gira" />}
      </label>
      {erro && <div className="cia-aviso erro">{erro}</div>}
      {q.trim().length >= 2 && !buscando && !erro && !lista.length && <p className="cia-dica">Nenhum lead encontrado.</p>}
      {lista.length > 0 && (
        <ul className="cia-lista">
          {lista.map((l) => (
            <li key={l.id_lead}>
              <button type="button" onClick={() => aoEscolher(l)}>
                <i className={l.encerrado ? "cinza" : l.ia_ligada ? "verde" : "vermelho"} aria-hidden />
                <span><b>{l.nome}</b><small>{l.telefone ?? "Sem telefone"}{l.agente ? ` · ${l.agente}` : ""}</small></span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ bolinha
const TAMANHO = 52;
const MARGEM = 8;
const CHAVE_POSICAO = "lawchat_controle_ia_posicao";
const LISTA_DE_CONVERSAS = 400;   // largura da lista de conversas da Central (a bolinha nasce logo à direita dela)

interface Posicao { x: number; y: number }   // x: distância da esquerda da área; y: distância do fundo da área

function lerPosicao(): Posicao | null {
  try {
    const p = JSON.parse(localStorage.getItem(CHAVE_POSICAO) || "null");
    return p && Number.isFinite(p.x) && Number.isFinite(p.y) ? { x: p.x, y: p.y } : null;
  } catch { return null; }
}
function gravarPosicao(p: Posicao) {
  try { localStorage.setItem(CHAVE_POSICAO, JSON.stringify(p)); } catch { /* sem armazenamento: volta ao canto padrão */ }
}

export function BolinhaControleIA({ area }: { area: RefObject<HTMLElement> }) {
  const [caixa, setCaixa] = useState<DOMRect | null>(null);
  const [pos, setPos] = useState<Posicao>(() => lerPosicao() ?? { x: LISTA_DE_CONVERSAS + 20, y: 100 });
  const [aberto, setAberto] = useState(false);
  const [alvo, setAlvo] = useState<Alvo | null>(null);
  const ctl = useLeadIA(alvo, aberto);
  const arrasto = useRef<{ dx: number; dy: number; x0: number; y0: number; moveu: boolean } | null>(null);
  const popup = useRef<HTMLDivElement>(null);
  const botao = useRef<HTMLButtonElement>(null);

  // A área da Central (acompanha tamanho, rolagem e janela).
  useLayoutEffect(() => {
    const el = area.current;
    if (!el) return;
    let quadro = 0;
    const medir = () => { cancelAnimationFrame(quadro); quadro = requestAnimationFrame(() => setCaixa(el.getBoundingClientRect())); };
    medir();
    const obs = new ResizeObserver(medir);
    obs.observe(el);
    window.addEventListener("resize", medir);
    window.addEventListener("scroll", medir, true);
    return () => { cancelAnimationFrame(quadro); obs.disconnect(); window.removeEventListener("resize", medir); window.removeEventListener("scroll", medir, true); };
  }, [area]);

  // Conversa aberta na Central (aviso da ponte): só do próprio painel.
  useEffect(() => {
    const ouvir = (e: MessageEvent) => {
      const novo = alvoDaMensagem(e);
      if (novo) setAlvo((atual) => (JSON.stringify(atual) === JSON.stringify(novo) ? atual : novo));
    };
    window.addEventListener("message", ouvir);
    return () => window.removeEventListener("message", ouvir);
  }, []);

  // Fecha com Esc ou clique fora.
  useEffect(() => {
    if (!aberto) return;
    const tecla = (e: KeyboardEvent) => { if (e.key === "Escape") { setAberto(false); botao.current?.focus(); } };
    const fora = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!popup.current?.contains(t) && !botao.current?.contains(t)) setAberto(false);
    };
    window.addEventListener("keydown", tecla);
    window.addEventListener("pointerdown", fora, true);
    return () => { window.removeEventListener("keydown", tecla); window.removeEventListener("pointerdown", fora, true); };
  }, [aberto]);

  if (!caixa || caixa.width <= 0) return null;
  const limitar = (p: Posicao): Posicao => ({
    x: Math.min(Math.max(MARGEM, p.x), Math.max(MARGEM, caixa.width - TAMANHO - MARGEM)),
    y: Math.min(Math.max(MARGEM, p.y), Math.max(MARGEM, caixa.height - TAMANHO - MARGEM)),
  });
  const p = limitar(pos);
  const esquerda = caixa.left + p.x;
  const topo = caixa.bottom - p.y - TAMANHO;

  const baixar = (e: EventoPonteiro<HTMLButtonElement>) => {
    if (e.button !== 0) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    arrasto.current = { dx: e.clientX - esquerda, dy: e.clientY - topo, x0: e.clientX, y0: e.clientY, moveu: false };
  };
  const mover = (e: EventoPonteiro<HTMLButtonElement>) => {
    const a = arrasto.current;
    if (!a) return;
    if (!a.moveu && Math.hypot(e.clientX - a.x0, e.clientY - a.y0) < 5) return;
    a.moveu = true;
    setPos(limitar({ x: e.clientX - a.dx - caixa.left, y: caixa.bottom - (e.clientY - a.dy) - TAMANHO }));
  };
  const soltar = () => {
    const a = arrasto.current;
    arrasto.current = null;
    if (!a) return;
    if (a.moveu) setPos((atual) => { const l = limitar(atual); gravarPosicao(l); return l; });
    else setAberto((v) => !v);
  };

  const lead = ctl.lead;
  const cor = !lead || lead.encerrado ? "cinza" : lead.ia_ligada ? "verde" : "vermelho";
  const titulo = !lead ? "Controle da IA: conversa não identificada" : lead.encerrado ? "Conversa encerrada" : lead.ia_ligada ? "IA ligada nesta conversa" : "IA desativada nesta conversa";

  // Popup: abre para o lado com mais espaço (em cima ou embaixo; esquerda ou direita da bolinha), dentro da janela.
  const LARGURA = 320;
  const acima = topo - caixa.top > caixa.bottom - (topo + TAMANHO);
  const xPopup = Math.min(Math.max(8, esquerda + TAMANHO / 2 > caixa.left + caixa.width / 2 ? esquerda + TAMANHO - LARGURA : esquerda), window.innerWidth - LARGURA - 8);
  const estiloPopup = acima
    ? { left: xPopup, bottom: window.innerHeight - topo + 10, maxHeight: topo - 16 }
    : { left: xPopup, top: topo + TAMANHO + 10, maxHeight: window.innerHeight - topo - TAMANHO - 26 };

  return (
    <>
      <button ref={botao} type="button" className={`cia-bolinha ${cor}${aberto ? " aberta" : ""}`} style={{ left: esquerda, top: topo }}
        onPointerDown={baixar} onPointerMove={mover} onPointerUp={soltar} onPointerCancel={() => { arrasto.current = null; }}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setAberto((v) => !v); } }}
        aria-haspopup="dialog" aria-expanded={aberto} aria-label={titulo} title={`${titulo} (arraste para mover)`}>
        <Bot size={24} strokeWidth={2} />
        <span className="cia-ponto" aria-hidden />
      </button>
      {aberto && (
        <div ref={popup} className="cia-popup" role="dialog" aria-label="Controle da IA" style={estiloPopup}>
          <header>
            <span className="cia-titulo"><Bot size={16} /> Controle da IA</span>
            <span className="cia-cab-acoes">
              {(alvo || lead) && (
                <button type="button" title="Atualizar" aria-label="Atualizar" onClick={() => void ctl.carregar()} disabled={ctl.carregando}>
                  <RefreshCw size={14} className={ctl.carregando ? "cia-gira" : ""} />
                </button>
              )}
              <button type="button" title="Fechar" aria-label="Fechar" onClick={() => setAberto(false)}><X size={15} /></button>
            </span>
          </header>
          <div className="cia-corpo">
            <PainelDoLead ctl={ctl} alvo={alvo} />
            {ctl.escolhido && lead && (
              <button type="button" className="cia-link cia-outro" onClick={ctl.limpar}><Search size={13} /> Escolher outro lead</button>
            )}
          </div>
        </div>
      )}
    </>
  );
}
