import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { formatDistanceToNowStrict } from "date-fns";
import { ptBR } from "date-fns/locale";
import {
  AlertOctagon, BellRing, BotOff, CheckCheck, ChevronRight, CirclePause, FileCheck2, FileText, Flag, Hand, ShieldAlert, UserCheck, X,
} from "lucide-react";
import { api, enviar } from "../api";
import BellToggle from "@/components/reactbits/BellToggle";
import "./centralNotificacoes.css";

/*
 * Sino do topo: central de notificações do que acontece dentro da IA (GET /api/central-notificacoes,
 * app/gestao/rotas_central_notificacoes.py). Lead qualificado, IA pausada numa conversa, contrato enviado ou assinado.
 * Busca a cada 45 s (e ao voltar para a aba); o sino balança (React Bits BellToggle) quando chega uma nova.
 * Clique numa notificação abre a conversa. Os erros técnicos NÃO vêm daqui: só a equipe LawChat (na visão dela) vê a
 * linha "Erros abertos", que leva à tela de erros (`erros` > 0 e `mostrarErros`).
 */

export interface Notificacao {
  id: string; tipo: string; grupo: "qualificado" | "pausa" | "contrato" | "sinal"; titulo: string; detalhe: string;
  nome: string; momento: string; id_lead: string; lida: boolean;
}
interface Resposta { itens: Notificacao[]; nao_lidas: number; lido_ate: string | null; agora: string }

const INTERVALO_MS = 45_000;

function iconeDo(n: Notificacao) {
  if (n.tipo === "lead_qualificado") return { Icone: UserCheck, cor: "verde" };
  if (n.tipo === "contrato_assinado") return { Icone: FileCheck2, cor: "verde" };
  if (n.tipo === "contrato_enviado") return { Icone: FileText, cor: "azul" };
  if (n.tipo === "pediu_humano") return { Icone: Hand, cor: "ambar" };
  if (n.tipo === "lead_suspeito") return { Icone: ShieldAlert, cor: "vermelho" };
  if (n.tipo === "ia_desativada") return { Icone: BotOff, cor: "cinza" };
  if (n.grupo === "sinal") return { Icone: Flag, cor: "roxo" };
  return { Icone: CirclePause, cor: "ambar" };
}

function haQuanto(iso: string): string {
  try {
    const d = new Date(iso);
    if (Date.now() - d.getTime() < 60_000) return "agora";
    return formatDistanceToNowStrict(d, { locale: ptBR, addSuffix: true });
  } catch { return ""; }
}

export function CentralNotificacoes({ escritorio, erros = 0, mostrarErros = false }: {
  escritorio: string; erros?: number; mostrarErros?: boolean;
}) {
  const navegar = useNavigate();
  const [dados, setDados] = useState<Resposta | null>(null);
  const [aberto, setAberto] = useState(false);
  const [marcando, setMarcando] = useState(false);
  const botaoRef = useRef<HTMLButtonElement>(null);
  const painelRef = useRef<HTMLDivElement>(null);
  const [posicao, setPosicao] = useState<{ top: number; right: number } | null>(null);

  const carregar = useCallback(async () => {
    try { setDados(await api<Resposta>("/central-notificacoes?limite=30")); } catch { /* sino fica como estava */ }
  }, []);

  // Busca ao abrir o painel do escritório, a cada 45 s e ao voltar para a aba.
  useEffect(() => {
    setDados(null);
    void carregar();
    const t = window.setInterval(() => { if (document.visibilityState === "visible") void carregar(); }, INTERVALO_MS);
    const voltou = () => { if (document.visibilityState === "visible") void carregar(); };
    document.addEventListener("visibilitychange", voltou);
    return () => { window.clearInterval(t); document.removeEventListener("visibilitychange", voltou); };
  }, [escritorio, carregar]);

  // O painel abre embaixo do sino (no celular, ocupa a largura com 12 px de margem: ver o CSS).
  useLayoutEffect(() => {
    if (!aberto) return;
    const medir = () => {
      const r = botaoRef.current?.getBoundingClientRect();
      if (r) setPosicao({ top: r.bottom + 10, right: Math.max(12, window.innerWidth - r.right - 6) });
    };
    medir();
    window.addEventListener("resize", medir);
    return () => window.removeEventListener("resize", medir);
  }, [aberto]);

  useEffect(() => {
    if (!aberto) return;
    void carregar();
    const fora = (e: MouseEvent) => {
      const alvo = e.target as Node;
      if (painelRef.current?.contains(alvo) || botaoRef.current?.contains(alvo)) return;
      setAberto(false);
    };
    const tecla = (e: KeyboardEvent) => { if (e.key === "Escape") { setAberto(false); botaoRef.current?.focus(); } };
    document.addEventListener("mousedown", fora);
    document.addEventListener("keydown", tecla);
    return () => { document.removeEventListener("mousedown", fora); document.removeEventListener("keydown", tecla); };
  }, [aberto, carregar]);

  const naoLidas = dados?.nao_lidas ?? 0;
  const errosVisiveis = mostrarErros ? erros : 0;
  const selo = naoLidas + errosVisiveis;
  const itens = dados?.itens ?? [];

  const marcarTodas = async () => {
    setMarcando(true);
    try {
      await enviar("/central-notificacoes/lidas", { ate: dados?.agora ?? null });
      setDados((d) => (d ? { ...d, nao_lidas: 0, itens: d.itens.map((i) => ({ ...i, lida: true })) } : d));
    } catch { /* tenta de novo no próximo clique */ } finally { setMarcando(false); }
  };

  const abrirConversa = (n: Notificacao) => { setAberto(false); navegar(`/conversas/${n.id_lead}`); };

  const rotulo = selo ? `Notificações: ${naoLidas} ${naoLidas === 1 ? "nova" : "novas"}${errosVisiveis ? `, ${errosVisiveis} erros abertos` : ""}` : "Notificações";

  return (
    <>
      <button ref={botaoRef} type="button" className={`lc-ico cn-sino${aberto ? " ativo" : ""}`} aria-label={rotulo} title="Notificações"
        aria-haspopup="dialog" aria-expanded={aberto} onClick={() => setAberto((v) => !v)}>
        <BellToggle count={selo} iconSize={18} clapper waves />
      </button>
      {createPortal(
        <AnimatePresence>
          {aberto && posicao && (
            <motion.div ref={painelRef} role="dialog" aria-label="Notificações" className="cn-painel"
              style={{ top: posicao.top, right: posicao.right }}
              initial={{ opacity: 0, y: -6, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -6, scale: 0.98 }}
              transition={{ duration: 0.18, ease: [0.23, 1, 0.32, 1] }}>
              <div className="cn-cab">
                <div className="cn-cab-txt">
                  <b>Notificações</b>
                  <small>{naoLidas ? `${naoLidas} ${naoLidas === 1 ? "nova" : "novas"} · ` : ""}o que a IA fez nos últimos 7 dias</small>
                </div>
                <button type="button" className="cn-marcar" onClick={marcarTodas} disabled={!naoLidas || marcando}>
                  <CheckCheck />Marcar todas como lidas
                </button>
                <button type="button" className="cn-fechar" onClick={() => setAberto(false)} aria-label="Fechar"><X /></button>
              </div>

              {errosVisiveis > 0 && (
                <button type="button" className="cn-erros" onClick={() => { setAberto(false); navegar("/admin/erros"); }}>
                  <span className="cn-ic vermelho"><AlertOctagon /></span>
                  <span className="cn-txt"><b>{errosVisiveis} {errosVisiveis === 1 ? "erro aberto" : "erros abertos"} da IA</b>
                    <small>Só a equipe LawChat vê esta linha</small></span>
                  <ChevronRight className="cn-seta" />
                </button>
              )}

              {dados === null ? (
                <div className="cn-vazio"><span className="cn-carregando" aria-hidden /><p>Carregando…</p></div>
              ) : itens.length === 0 ? (
                <div className="cn-vazio">
                  <span className="cn-vazio-ic" aria-hidden><BellRing /></span>
                  <b>Tudo tranquilo por aqui</b>
                  <p>Quando a IA qualificar um lead, pausar uma conversa ou um contrato for enviado ou assinado, avisamos aqui.</p>
                </div>
              ) : (
                <ul className="cn-lista">
                  {itens.map((n, i) => {
                    const { Icone, cor } = iconeDo(n);
                    return (
                      <motion.li key={n.id} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: Math.min(i, 8) * 0.025, duration: 0.2 }}>
                        <button type="button" className={`cn-item${n.lida ? "" : " nova"}`} onClick={() => abrirConversa(n)}>
                          <span className={`cn-ic ${cor}`}><Icone /></span>
                          <span className="cn-txt">
                            <b>{n.titulo}</b>
                            <small>{n.detalhe}</small>
                          </span>
                          <span className="cn-quando">{haQuanto(n.momento)}</span>
                          {!n.lida && <span className="cn-ponto" aria-label="nova" />}
                        </button>
                      </motion.li>
                    );
                  })}
                </ul>
              )}
              {itens.length > 0 && <p className="cn-rodape">Clique para abrir a conversa.</p>}
            </motion.div>
          )}
        </AnimatePresence>,
        document.body,
      )}
    </>
  );
}
