import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ComponentType } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertOctagon, AlertTriangle, ArrowRight, BellRing, BotOff, CheckCheck, ChevronRight, CirclePause, FileCheck2, FileText, Hand,
  Settings, ShieldAlert, Smartphone, UserCheck, Wallet, X,
} from "lucide-react";
import { api, enviar, geracaoAtual, guardarResposta, ultimaResposta } from "../api";
import BellToggle from "@/components/reactbits/BellToggle";
import { pedirConversaNaCentral } from "./camadaLawChat";
import "./centralNotificacoes.css";

/*
 * Sino do topo: central de notificações do que acontece dentro da IA (GET /api/central-notificacoes,
 * app/gestao/rotas_central_notificacoes.py). Busca a cada 45 s (e ao voltar para a aba); o sino balança quando chega
 * uma nova e mostra o número de não lidas.
 *
 * Duas abas:
 *  - "Precisa de você" (padrão): só o que pede ação da pessoa. Avisos de conversa com `precisa` (IA pausada, pediu
 *    atendente, lead suspeito, sinais; some quando a equipe responde) e os `alertas` (saldo acabando, número com
 *    problema). Cada linha tem um botão: "Assumir conversa"/"Abrir conversa" (abre o chat do lead direto na Central de
 *    Atendimento), "Ver integração" ou "Recarregar".
 *  - "Todas": tudo da última semana (qualificados, contratos...). Clique abre a conversa na Central.
 * Rodapé: "Ver central" (lista completa, até 100, no próprio painel) e "Configurar" (tela de Avisos).
 * Erros técnicos NÃO vêm daqui: só a equipe LawChat (na visão dela) vê a linha "Erros abertos" (`mostrarErros`).
 * Desempenho: nada de canvas nem laço; os únicos ouvintes globais (clique fora e Esc) só existem com o painel aberto.
 */

export interface Notificacao {
  id: string; tipo: string; grupo: "qualificado" | "pausa" | "contrato" | "sinal"; titulo: string; detalhe: string;
  nome: string; momento: string; id_lead: string; lida: boolean; sessao?: string | null; precisa?: boolean;
}
interface Alerta {
  id: string; tipo: "saldo_acabou" | "saldo_acabando" | "numero_desconectado" | "numero_parado" | string;
  titulo: string; detalhe: string; momento: string; acao: { rotulo: string; destino: string } | null;
}
interface Resposta { itens: Notificacao[]; nao_lidas: number; lido_ate: string | null; agora: string; alertas?: Alerta[] }

const INTERVALO_MS = 45_000;
const CAMINHO_SINO = "/central-notificacoes?limite=30";
const CAMINHO_COMPLETA = "/central-notificacoes?limite=100";

type Cor = "verde" | "azul" | "laranja" | "vermelho" | "cinza";
function iconeDo(n: Notificacao): { Icone: ComponentType; cor: Cor } {
  if (n.tipo === "lead_qualificado") return { Icone: UserCheck, cor: "verde" };
  if (n.tipo === "contrato_assinado") return { Icone: FileCheck2, cor: "verde" };
  if (n.tipo === "contrato_enviado") return { Icone: FileText, cor: "azul" };
  if (n.tipo === "pediu_humano" || n.grupo === "sinal") return { Icone: Hand, cor: "laranja" };
  if (n.tipo === "lead_suspeito") return { Icone: ShieldAlert, cor: "vermelho" };
  if (n.tipo === "trava_persistente") return { Icone: AlertTriangle, cor: "vermelho" };
  if (n.tipo === "ia_desativada") return { Icone: BotOff, cor: "cinza" };
  return { Icone: CirclePause, cor: "laranja" };
}
function iconeDoAlerta(a: Alerta): { Icone: ComponentType; cor: Cor } {
  if (a.tipo.startsWith("saldo")) return { Icone: a.tipo === "saldo_acabou" ? AlertTriangle : Wallet, cor: a.tipo === "saldo_acabou" ? "vermelho" : "laranja" };
  if (a.tipo === "numero_desconectado") return { Icone: AlertTriangle, cor: "vermelho" };
  return { Icone: Smartphone, cor: "laranja" };
}

/** Tempo curto: "agora", "12 min", "3 h", "1 d", "2 sem". */
function haQuanto(iso: string): string {
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return "";
  const min = Math.floor((Date.now() - t) / 60_000);
  if (min < 1) return "agora";
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h} h`;
  const d = Math.floor(h / 24);
  return d < 7 ? `${d} d` : `${Math.floor(d / 7)} sem`;
}

/** Aba "Todas": nome do lead em negrito + o que aconteceu; embaixo, o complemento (agente, situação). */
function textoDa(n: Notificacao): { acao: string; extra: string } {
  const semNome = (t: string) => {
    const x = n.nome && t.startsWith(n.nome) ? t.slice(n.nome.length).replace(/^\s*·\s*/, "") : t;
    return x.trim();
  };
  switch (n.tipo) {
    case "lead_qualificado": return { acao: "virou lead qualificado", extra: n.detalhe };
    case "contrato_enviado": return { acao: "recebeu o contrato de honorários", extra: n.detalhe };
    case "contrato_assinado": return { acao: "assinou o contrato", extra: n.detalhe };
    case "ia_desativada": return { acao: "teve a IA desativada na conversa", extra: semNome(n.detalhe) };
    default: return { acao: `· ${n.titulo.charAt(0).toLowerCase()}${n.titulo.slice(1)}`, extra: semNome(n.detalhe) };
  }
}

/** Aba "Precisa de você": a frase curta do que aconteceu e o que fazer (2 linhas no máximo). */
const PEDIDOS: Record<string, string> = {
  pediu_humano: "Pediu para falar com uma pessoa. A IA pausou e a conversa está com a equipe.",
  lead_suspeito: "Parece robô, repetição ou só figurinhas. A IA pausou para a equipe conferir.",
  analise_manual: "É um caso para a equipe analisar. A IA pausou nesta conversa.",
  trava_persistente: "A conversa travou e precisa da equipe. A IA pausou.",
  pedido_repetido: "Repetiu o mesmo pedido. A IA pausou para alguém responder.",
  fora_do_tema_repetido: "A conversa saiu do tema do atendimento. A IA pausou.",
};
function pedidoDa(n: Notificacao): { texto: string; botao: string } {
  if (n.grupo === "sinal") return { texto: `${n.titulo}. Vale um contato da equipe.`, botao: "Abrir conversa" };
  return { texto: PEDIDOS[n.tipo] ?? `${n.titulo}.`, botao: "Assumir conversa" };
}

const ENTRADA = (i: number) => ({ delay: 0.04 + Math.min(i, 10) * 0.03, duration: 0.24, ease: [0.23, 1, 0.32, 1] as const });

export function CentralNotificacoes({ escritorio, erros = 0, mostrarErros = false }: {
  escritorio: string; erros?: number; mostrarErros?: boolean;
}) {
  const navegar = useNavigate();
  // Abre com a cópia guardada (pré-carga da abertura ou abertura anterior) e confere com o servidor logo em seguida.
  const [dados, setDados] = useState<Resposta | null>(() => ultimaResposta<Resposta>(CAMINHO_SINO) ?? null);
  const [aberto, setAberto] = useState(false);
  const [marcando, setMarcando] = useState(false);
  const [aba, setAba] = useState<"precisa" | "todas">("precisa");
  // "Ver central": a lista completa (até 100, últimos 7 dias) dentro do próprio painel.
  const [completa, setCompleta] = useState<Notificacao[] | null>(null);
  const [verCompleta, setVerCompleta] = useState(false);
  const botaoRef = useRef<HTMLButtonElement>(null);
  const painelRef = useRef<HTMLDivElement>(null);
  const [posicao, setPosicao] = useState<{ top: number; right: number } | null>(null);

  const carregar = useCallback(async () => {
    const geracao = geracaoAtual();
    try {
      const r = await api<Resposta>(CAMINHO_SINO);
      guardarResposta(CAMINHO_SINO, r, geracao);
      setDados(r);
    } catch { /* sino fica como estava */ }
  }, []);

  // Busca ao abrir o painel do escritório, a cada 45 s e ao voltar para a aba.
  useEffect(() => {
    setDados(ultimaResposta<Resposta>(CAMINHO_SINO) ?? null);   // trocou de escritório: a cópia DELE (ou nada)
    setCompleta(null); setVerCompleta(false);
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

  // Só enquanto aberto: busca na hora, fecha com clique fora ou Esc; ao fechar, volta para a lista curta.
  useEffect(() => {
    if (!aberto) { setVerCompleta(false); setCompleta(null); return; }
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
  const todas = verCompleta && completa ? completa : dados?.itens ?? [];
  const alertas = dados?.alertas ?? [];
  const pedidos = (dados?.itens ?? []).filter((i) => i.precisa);
  const qtdPrecisa = alertas.length + pedidos.length;

  const marcarTodas = async () => {
    setMarcando(true);
    try {
      await enviar("/central-notificacoes/lidas", { ate: dados?.agora ?? null });
      setDados((d) => (d ? { ...d, nao_lidas: 0, itens: d.itens.map((i) => ({ ...i, lida: true })) } : d));
      setCompleta((c) => (c ? c.map((i) => ({ ...i, lida: true })) : c));
    } catch { /* tenta de novo no próximo clique */ } finally { setMarcando(false); }
  };

  // Abre o chat do lead direto na Central de Atendimento (camadaLawChat pede o link com id_lead e troca o quadro dela).
  const abrirConversa = (n: Notificacao) => {
    setAberto(false);
    pedirConversaNaCentral(n.id_lead, n.nome);
    navegar(`/atendimento?lead=${encodeURIComponent(n.id_lead)}`);
  };
  const ir = (destino: string) => { setAberto(false); navegar(destino); };
  const verCentral = async () => {
    setAba("todas"); setVerCompleta(true);
    try { const r = await api<Resposta>(CAMINHO_COMPLETA); setCompleta(r.itens); } catch { setVerCompleta(false); }
  };

  const rotulo = selo ? `Notificações: ${naoLidas} ${naoLidas === 1 ? "nova" : "novas"}${errosVisiveis ? `, ${errosVisiveis} erros abertos` : ""}` : "Notificações";
  const carregando = dados === null || (aba === "todas" && verCompleta && completa === null);

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
              initial={{ opacity: 0, y: -8, scale: 0.95 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -6, scale: 0.97 }}
              transition={{ duration: 0.2, ease: [0.23, 1, 0.32, 1] }}>
              <div className="cn-cab">
                <b className="cn-titulo">Notificações</b>
                <button type="button" className="cn-marcar" onClick={marcarTodas} disabled={!naoLidas || marcando}>
                  <CheckCheck />Marcar como lidas
                </button>
                <button type="button" className="cn-fechar" onClick={() => setAberto(false)} aria-label="Fechar"><X /></button>
              </div>
              <div className="cn-abas" role="tablist" aria-label="Filtrar notificações">
                {([["precisa", "Precisa de você"], ["todas", "Todas"]] as const).map(([v, r]) => (
                  <button key={v} type="button" role="tab" aria-selected={aba === v} className={`cn-aba${aba === v ? " on" : ""}`} onClick={() => setAba(v)}>
                    {r}{v === "precisa" && <span className="cn-aba-n"> · {qtdPrecisa}</span>}
                    {aba === v && <motion.span layoutId="cn-aba-traco" className="cn-aba-traco" transition={{ type: "spring", stiffness: 520, damping: 40 }} />}
                  </button>
                ))}
              </div>

              {errosVisiveis > 0 && (
                <button type="button" className="cn-erros" onClick={() => ir("/admin/erros")}>
                  <span className="cn-ic vermelho"><AlertOctagon /></span>
                  <span className="cn-txt"><b className="cn-nome">{errosVisiveis} {errosVisiveis === 1 ? "erro aberto" : "erros abertos"} da IA</b>
                    <small>Só a equipe LawChat vê esta linha</small></span>
                  <ChevronRight className="cn-seta" />
                </button>
              )}

              {carregando ? (
                <div className="cn-vazio"><span className="cn-carregando" aria-hidden /><p>Carregando…</p></div>
              ) : aba === "precisa" ? (
                qtdPrecisa === 0 ? (
                  <div className="cn-vazio">
                    <span className="cn-vazio-ic" aria-hidden><CheckCheck /></span>
                    <b>Nada esperando por você</b>
                    <p>Quando a IA pausar uma conversa, um lead pedir atendimento ou algo precisar de ajuste, aparece aqui.</p>
                  </div>
                ) : (
                  <ul className="cn-lista" key="precisa">
                    {alertas.map((a, i) => {
                      const { Icone, cor } = iconeDoAlerta(a);
                      return (
                        <motion.li key={a.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={ENTRADA(i)}>
                          <div className="cn-pedido">
                            <span className={`cn-ic ${cor}`}><Icone /></span>
                            <span className="cn-txt"><b className="cn-nome" title={a.titulo}>{a.titulo}</b><span className="cn-desc">{a.detalhe}</span></span>
                            {a.acao && <button type="button" className="cn-acao" onClick={() => ir(a.acao!.destino)}>{a.acao.rotulo}</button>}
                          </div>
                        </motion.li>
                      );
                    })}
                    {pedidos.map((n, j) => {
                      const { Icone, cor } = iconeDo(n);
                      const { texto, botao } = pedidoDa(n);
                      return (
                        <motion.li key={n.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={ENTRADA(alertas.length + j)}>
                          <div className={`cn-pedido${n.lida ? "" : " nova"}`}>
                            <span className={`cn-ic ${cor}`}><Icone /></span>
                            <span className="cn-txt">
                              <span className="cn-topo-linha"><b className="cn-nome" title={n.nome}>{n.nome}</b><span className="cn-quando">{haQuanto(n.momento)}</span></span>
                              <span className="cn-desc">{texto}</span>
                            </span>
                            <button type="button" className="cn-acao" onClick={() => abrirConversa(n)}>{botao}</button>
                          </div>
                        </motion.li>
                      );
                    })}
                  </ul>
                )
              ) : todas.length === 0 ? (
                <div className="cn-vazio">
                  <span className="cn-vazio-ic" aria-hidden><BellRing /></span>
                  <b>Tudo tranquilo por aqui</b>
                  <p>Quando a IA qualificar um lead, pausar uma conversa ou um contrato for enviado ou assinado, avisamos aqui.</p>
                </div>
              ) : (
                <ul className={`cn-lista${verCompleta ? " completa" : ""}`} key={`todas-${verCompleta ? "c" : "r"}`}>
                  {todas.map((n, i) => {
                    const { Icone, cor } = iconeDo(n);
                    const { acao, extra } = textoDa(n);
                    return (
                      <motion.li key={n.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={ENTRADA(i)}>
                        <button type="button" className={`cn-item${n.lida ? "" : " nova"}`} onClick={() => abrirConversa(n)} title="Abrir a conversa">
                          <span className={`cn-ic ${cor}`}><Icone /></span>
                          <span className="cn-txt">
                            <span className="cn-linha"><b>{n.nome}</b> {acao}</span>
                            {extra && <small>{extra}</small>}
                          </span>
                          <span className="cn-lado">
                            <span className="cn-quando">{haQuanto(n.momento)}</span>
                            {!n.lida && <span className="cn-ponto" aria-label="não lida" />}
                          </span>
                        </button>
                      </motion.li>
                    );
                  })}
                </ul>
              )}
              <div className="cn-rodape">
                {verCompleta && aba === "todas" ? (
                  <button type="button" className="cn-rod-link" onClick={() => setVerCompleta(false)}>Ver só as recentes</button>
                ) : (
                  <button type="button" className="cn-rod-link" onClick={() => void verCentral()}>Ver central <ArrowRight /></button>
                )}
                <button type="button" className="cn-rod-config" onClick={() => ir("/avisos")}><Settings />Configurar</button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>,
        document.body,
      )}
    </>
  );
}
