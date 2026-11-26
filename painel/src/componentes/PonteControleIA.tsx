import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Bot, Loader2, Power, RefreshCw, SearchX, X } from "lucide-react";
import { MENSAGEM_CONVERSA, MENSAGEM_POPUP_ABERTO, useLeadIA, type Alvo, type LeadIA } from "./ControleIA";
import "./controleIA.css";

/**
 * Página do link "Controle da IA" cadastrado na plataforma de atendimento (cartão em Integrações):
 *   /controle-ia/ponte?segredo=...&id_da_conta=...&id_do_atendimento=...&id_do_contato=...&telefone_do_contato=...&id_do_usuario=...
 *
 * A plataforma abre o link como popup preenchendo as variáveis da conversa. Com id_da_conta e o segredo do escritório,
 * funciona SEM login: as rotas /api/controle-ia/publico acham o escritório pela conta, conferem o segredo e acham o lead
 * pelos dados da conversa (nunca por id de lead). Sem os dois (link antigo, sem segredo), usa a sessão do painel
 * (rotas normais); sem sessão, explica como cadastrar o link.
 * Aberta dentro do próprio painel (iframe), ainda avisa o topo qual conversa está aberta (MENSAGEM_CONVERSA).
 */
interface Parametros extends Alvo { usuario?: string; segredo?: string }
interface RespostaAcao { ok: boolean; mudou: boolean; mensagem: string; lead: LeadIA }

function lerParametros(): Parametros {
  const q = new URLSearchParams(window.location.search);
  const v = (nome: string) => {
    const valor = (q.get(nome) || "").trim().slice(0, 80);
    return valor && !valor.includes("{{") ? valor : undefined;      // variável que a plataforma não preencheu
  };
  return { sessao: v("id_do_atendimento"), contato: v("id_do_contato"), telefone: v("telefone_do_contato"), conta: v("id_da_conta"), usuario: v("id_do_usuario"), segredo: v("segredo") };
}

/** Pedido às rotas públicas, sem cache nem cookie (o link funciona sem login). */
async function pedirPublico<T>(caminho: string, corpo?: unknown): Promise<T> {
  const r = await fetch(`/api/controle-ia/publico${caminho}`, {
    method: corpo === undefined ? "GET" : "POST", credentials: "omit", cache: "no-store",
    headers: { Accept: "application/json", ...(corpo === undefined ? {} : { "Content-Type": "application/json" }) },
    body: corpo === undefined ? undefined : JSON.stringify(corpo),
  });
  const texto = await r.text();
  let dados: any = null;
  try { dados = texto ? JSON.parse(texto) : null; } catch { dados = null; }
  if (!r.ok) {
    const erro = new Error(typeof dados?.detail === "string" ? dados.detail : r.status === 429 ? "Muitos pedidos seguidos. Espere um minuto." : `Não deu certo agora (erro ${r.status}). Tente de novo.`);
    (erro as Error & { status?: number }).status = r.status;
    throw erro;
  }
  return dados as T;
}

/** Mesmo formato do useLeadIA (para reaproveitar o PainelDoLead), falando com as rotas públicas do link. */
function useLeadPublico(p: Parametros) {
  const [lead, setLead] = useState<LeadIA | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [status, setStatus] = useState<number | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [ocupado, setOcupado] = useState(false);
  const [aviso, setAviso] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const vez = useRef(0);
  const dadosDaConversa = useMemo(() => ({
    id_da_conta: p.conta ?? "", segredo: p.segredo ?? "", id_do_atendimento: p.sessao ?? "", id_do_contato: p.contato ?? "", telefone_do_contato: p.telefone ?? "",
  }), [p]);

  const carregar = useCallback(async (silencioso = false) => {
    const minha = ++vez.current;
    if (!silencioso) setCarregando(true);
    try {
      const novo = await pedirPublico<LeadIA>(`/lead?${new URLSearchParams(dadosDaConversa)}`);
      if (minha !== vez.current) return;
      setLead({ ...novo, id_lead: novo.id_lead ?? "" }); setErro(null); setStatus(null);
    } catch (e) {
      if (minha !== vez.current) return;
      if (!silencioso) setLead(null);
      setErro((e as Error).message); setStatus((e as Error & { status?: number }).status ?? null);
    } finally {
      if (minha === vez.current) setCarregando(false);
    }
  }, [dadosDaConversa]);

  useEffect(() => { void carregar(); }, [carregar]);
  useEffect(() => {
    const t = window.setInterval(() => { if (document.visibilityState === "visible") void carregar(true); }, 30_000);
    return () => window.clearInterval(t);
  }, [carregar]);

  const agir = async (acao: "desativar" | "reativar", minutos = 0) => {
    if (!lead || ocupado) return;
    setOcupado(true); setAviso(null);
    try {
      const r = await pedirPublico<RespostaAcao>(`/${acao}`, { ...dadosDaConversa, id_do_usuario: p.usuario ?? "", ...(acao === "desativar" ? { minutos } : {}) });
      setLead({ ...r.lead, id_lead: r.lead.id_lead ?? "" });
      setAviso({ tipo: "ok", texto: r.mensagem });
    } catch (e) {
      setAviso({ tipo: "erro", texto: (e as Error).message });
    } finally {
      setOcupado(false);
    }
  };
  const nada = () => { /* sem busca no link */ };
  return { lead, erro, status, carregando, ocupado, aviso, carregar, escolher: nada as (l: LeadIA) => void, limpar: nada, agir, escolhido: false };
}

export default function PonteControleIA() {
  const p = useMemo(lerParametros, []);
  const temConversa = Boolean(p.sessao || p.contato || p.telefone);

  useEffect(() => {
    document.title = "Controle da IA · LawChat";
    if (!temConversa || window.top === window.self) return;
    const alvo: Alvo = { sessao: p.sessao, contato: p.contato, telefone: p.telefone, conta: p.conta };
    try { window.top?.postMessage({ tipo: MENSAGEM_CONVERSA, ...alvo }, window.location.origin); } catch { /* topo de outro domínio */ }
  }, [p, temConversa]);

  // Aberto dentro da Central (plataforma dentro do painel): a plataforma escurece a lista atrás do popup, mas a tampa
  // branca do painel (que cobre o aviso de notificações) ficava clara por cima. Batimento a cada 1,5 s: enquanto ele
  // chega, o painel esconde a tampa; parou de chegar (popup fechado), ela volta.
  useEffect(() => {
    if (window.top === window.self) return;
    const avisar = () => { try { window.top?.postMessage({ tipo: MENSAGEM_POPUP_ABERTO }, window.location.origin); } catch { /* outro domínio */ } };
    avisar();
    const t = window.setInterval(avisar, 1500);
    return () => window.clearInterval(t);
  }, []);

  return (
    <div className="cia-ponte">
      <div className="cpc-cartao">
        {p.conta && p.segredo ? <ControlePeloLink p={p} temConversa={temConversa} /> : <ControlePelaSessao p={p} temConversa={temConversa} />}
      </div>
      <footer className="cpc-rodape">LawChat © {new Date().getFullYear()}</footer>
    </div>
  );
}

function Cabecalho({ aoAtualizar, carregando }: { aoAtualizar?: () => void; carregando?: boolean }) {
  return (
    <header className="cpc-topo">
      {aoAtualizar && (
        <button type="button" className="cpc-atualizar" title="Atualizar o status" aria-label="Atualizar o status" onClick={aoAtualizar} disabled={carregando}>
          <RefreshCw size={15} className={carregando ? "cia-gira" : ""} />
        </button>
      )}
      <span className="cpc-selo"><Bot size={15} /> CONTROLE DA IA</span>
      <h1>Painel de Controle IA</h1>
      <p>Desative a IA desta conversa quando alguém da equipe for assumir o atendimento.</p>
    </header>
  );
}

interface Controle {
  lead: LeadIA | null; carregando: boolean; ocupado: boolean; erro: string | null;
  aviso: { tipo: "ok" | "erro"; texto: string } | null; agir: (acao: "desativar" | "reativar", minutos?: number) => Promise<void> | void;
}

const DURACOES: { minutos: number; rotulo: string }[] = [
  { minutos: 30, rotulo: "30 minutos" }, { minutos: 120, rotulo: "2 horas" }, { minutos: 1440, rotulo: "24 horas" },
  { minutos: 0, rotulo: "Até alguém religar" },
];

function ate(iso: string | null): string {
  if (!iso) return "até alguém religar";
  try {
    const d = new Date(iso);
    const hoje = new Date().toDateString() === d.toDateString();
    const hora = d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
    return hoje ? `até as ${hora}` : `até ${d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" })} às ${hora}`;
  } catch { return ""; }
}

/** Visual do "Painel de Controle IA": o lead, o status e um botão grande; a duração escolhe numa janela. */
function PainelControle({ ctl }: { ctl: Controle }) {
  const [perguntando, setPerguntando] = useState(false);
  const [duracao, setDuracao] = useState<number | null>(null);
  const lead = ctl.lead;
  if (!lead) return <div className="cpc-carregando"><Loader2 size={22} className="cia-gira" /> Carregando a conversa…</div>;
  const ligada = lead.ia_ligada && !lead.encerrado;
  const continuar = async () => {
    if (duracao === null) return;
    await ctl.agir("desativar", duracao);
    setPerguntando(false); setDuracao(null);
  };
  return (
    <>
      <div className="cpc-lead">
        <span className="cpc-avatar">{(lead.nome || "?").trim().charAt(0).toUpperCase()}</span>
        <div>
          <b>{lead.nome || "Sem nome"}</b>
          <small>{[lead.telefone, lead.agente, lead.etapa_nome || lead.etapa].filter(Boolean).join(" · ")}</small>
        </div>
      </div>
      <div className={`cpc-status ${ligada ? "ligada" : "desligada"}`}>
        <i aria-hidden />
        <div>
          <b>{ligada ? "IA ligada" : lead.encerrado ? "Conversa encerrada" : "IA desativada"}</b>
          <span>{ligada ? "Ela responde as próximas mensagens do lead." : lead.encerrado ? "A IA não atende mais esta conversa."
            : `Atendimento humano ${ate(lead.pausado_ate)}.`}</span>
        </div>
      </div>
      {lead.ia_desligada_escritorio && <div className="cia-aviso erro">A IA está desligada no escritório inteiro.</div>}
      {ligada ? (
        <button type="button" className="cpc-botao desativar" disabled={ctl.ocupado} onClick={() => setPerguntando(true)}>
          <Power size={18} /> Desativar IA
        </button>
      ) : !lead.encerrado && (
        <button type="button" className="cpc-botao reativar" disabled={ctl.ocupado} onClick={() => void ctl.agir("reativar")}>
          {ctl.ocupado ? <Loader2 size={18} className="cia-gira" /> : <Power size={18} />} Reativar IA
        </button>
      )}
      {ctl.aviso && <div className={`cia-aviso ${ctl.aviso.tipo}`} role="status">{ctl.aviso.texto}</div>}
      {perguntando && (
        <div className="cpc-fundo" role="dialog" aria-modal="true" aria-label="Desativar IA nesta conversa">
          <div className="cpc-janela">
            <button type="button" className="cpc-fechar" aria-label="Fechar" onClick={() => { setPerguntando(false); setDuracao(null); }}><X size={18} /></button>
            <h2>Desativar IA nesta conversa?</h2>
            <p>O atendimento passa a ser só humano nesta conversa. A IA para de responder até o prazo acabar ou alguém religar. Fica uma nota no atendimento.</p>
            <span className="cpc-rotulo">DURAÇÃO</span>
            <div className="cpc-opcoes">
              {DURACOES.map((d) => (
                <button type="button" key={d.minutos} className={duracao === d.minutos ? "ativa" : ""} onClick={() => setDuracao(d.minutos)}>{d.rotulo}</button>
              ))}
            </div>
            <div className="cpc-acoes">
              <button type="button" className="cpc-cancelar" onClick={() => { setPerguntando(false); setDuracao(null); }}>Cancelar</button>
              <button type="button" className="cpc-continuar" disabled={duracao === null || ctl.ocupado} onClick={() => void continuar()}>
                {ctl.ocupado ? <Loader2 size={16} className="cia-gira" /> : null} Continuar
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function SemConversa() {
  return (
    <div className="cpc-corpo">
      <div className="cia-explica">
        <SearchX size={28} aria-hidden />
        <b>Abra pelo botão da conversa</b>
        <p>Este link precisa dos dados da conversa, que a plataforma de atendimento preenche quando ele é aberto de dentro de uma conversa.</p>
      </div>
    </div>
  );
}

function ControlePeloLink({ p, temConversa }: { p: Parametros; temConversa: boolean }) {
  if (!temConversa) return <><Cabecalho /><SemConversa /></>;
  return <ControlePeloLinkComConversa p={p} />;
}

function ControlePeloLinkComConversa({ p }: { p: Parametros }) {
  const ctl = useLeadPublico(p);
  const naoAchou = !ctl.lead && !ctl.carregando && ctl.status === 404 && /não tem lead/i.test(ctl.erro || "");
  return (
    <>
      <Cabecalho aoAtualizar={() => void ctl.carregar()} carregando={ctl.carregando} />
      <div className="cpc-corpo">
        {naoAchou ? (
          <div className="cia-explica">
            <SearchX size={28} aria-hidden />
            <b>Não achamos este contato na IA</b>
            <p>A IA ainda não atendeu esta conversa (ou ela é de outro número/escritório). Quando a IA responder este contato, o controle aparece aqui.</p>
          </div>
        ) : !ctl.lead && !ctl.carregando && ctl.erro ? (
          <div className="cia-aviso erro" role="alert">{ctl.erro}</div>
        ) : (
          <PainelControle ctl={ctl} />
        )}
      </div>
    </>
  );
}

function ControlePelaSessao({ p, temConversa }: { p: Parametros; temConversa: boolean }) {
  const alvo = useMemo<Alvo | null>(() => (temConversa ? { sessao: p.sessao, contato: p.contato, telefone: p.telefone } : null), [p, temConversa]);
  const ctl = useLeadIA(alvo, true);
  const semLogin = /entre de novo|usuário desativado/i.test(ctl.erro || "");
  if (!temConversa) return <><Cabecalho /><SemConversa /></>;
  return (
    <>
      <Cabecalho aoAtualizar={semLogin ? undefined : () => void ctl.carregar()} carregando={ctl.carregando} />
      <div className="cpc-corpo">
        {semLogin ? (
          <div className="cia-explica">
            <Bot size={28} aria-hidden />
            <b>Falta cadastrar o link</b>
            <p>Copie o link no painel da LawChat (Integrações › Link do Controle da IA) e cadastre na plataforma de atendimento como botão da conversa. Ele já vem com o segredo do escritório, a conta e os dados da conversa. Link antigo, sem "segredo=", não funciona mais: troque pelo novo.</p>
          </div>
        ) : (
          <PainelControle ctl={ctl} />
        )}
      </div>
    </>
  );
}
