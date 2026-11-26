import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Bot, Loader2, RefreshCw, SearchX } from "lucide-react";
import { MENSAGEM_CONVERSA, PainelDoLead, useLeadIA, type Alvo, type LeadIA } from "./ControleIA";
import "./controleIA.css";

/**
 * Página do link "Controle da IA" cadastrado na plataforma de atendimento (cartão em Integrações):
 *   /controle-ia/ponte?id_da_conta=...&id_do_atendimento=...&id_do_contato=...&telefone_do_contato=...&id_do_usuario=...
 *
 * A plataforma abre o link como popup preenchendo as variáveis da conversa. Com id_da_conta, funciona SEM login: as
 * rotas /api/controle-ia/publico acham o escritório pela conta e o lead pelos dados da conversa (nunca por id de lead).
 * Sem id_da_conta, usa a sessão do painel (rotas normais); sem sessão, explica como cadastrar o link.
 * Aberta dentro do próprio painel (iframe), ainda avisa o topo qual conversa está aberta (MENSAGEM_CONVERSA).
 */
interface Parametros extends Alvo { usuario?: string }
interface RespostaAcao { ok: boolean; mudou: boolean; mensagem: string; lead: LeadIA }

function lerParametros(): Parametros {
  const q = new URLSearchParams(window.location.search);
  const v = (nome: string) => {
    const valor = (q.get(nome) || "").trim().slice(0, 80);
    return valor && !valor.includes("{{") ? valor : undefined;      // variável que a plataforma não preencheu
  };
  return { sessao: v("id_do_atendimento"), contato: v("id_do_contato"), telefone: v("telefone_do_contato"), conta: v("id_da_conta"), usuario: v("id_do_usuario") };
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
    id_da_conta: p.conta ?? "", id_do_atendimento: p.sessao ?? "", id_do_contato: p.contato ?? "", telefone_do_contato: p.telefone ?? "",
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

  return (
    <div className="cia-ponte">
      <div className="cia-ponte-cartao">
        {p.conta ? <ControlePeloLink p={p} temConversa={temConversa} /> : <ControlePelaSessao p={p} temConversa={temConversa} />}
      </div>
    </div>
  );
}

function Cabecalho({ aoAtualizar, carregando }: { aoAtualizar?: () => void; carregando?: boolean }) {
  return (
    <header>
      <span className="cia-titulo"><Bot size={17} /> Controle da IA</span>
      {aoAtualizar && (
        <button type="button" className="cia-atualizar" title="Atualizar o status" aria-label="Atualizar o status" onClick={aoAtualizar} disabled={carregando}>
          <RefreshCw size={14} className={carregando ? "cia-gira" : ""} />
        </button>
      )}
    </header>
  );
}

function SemConversa() {
  return (
    <div className="cia-corpo">
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
      <div className="cia-corpo">
        {naoAchou ? (
          <div className="cia-explica">
            <SearchX size={28} aria-hidden />
            <b>Não achamos este contato na IA</b>
            <p>A IA ainda não atendeu esta conversa (ou ela é de outro número/escritório). Quando a IA responder este contato, o controle aparece aqui.</p>
          </div>
        ) : !ctl.lead && !ctl.carregando && ctl.erro ? (
          <div className="cia-aviso erro" role="alert">{ctl.erro}</div>
        ) : (
          <PainelDoLead ctl={ctl} alvo={p} aoBuscar={false} />
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
      <div className="cia-corpo">
        {semLogin ? (
          <div className="cia-explica">
            <Bot size={28} aria-hidden />
            <b>Falta cadastrar o link</b>
            <p>Copie o link no painel da LawChat (Integrações › Link do Controle da IA) e cadastre na plataforma de atendimento como botão da conversa. Ele já vem com a conta e os dados da conversa.</p>
          </div>
        ) : (
          <PainelDoLead ctl={ctl} alvo={alvo} aoBuscar={false} />
        )}
      </div>
    </>
  );
}
