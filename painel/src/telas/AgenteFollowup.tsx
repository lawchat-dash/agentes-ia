import { Fragment, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import {
  Ban, BarChart3, BellRing, CalendarClock, Check, CircleAlert, CirclePause, Clock, Eye, Hand, History, Hourglass, Info, Layers,
  ListOrdered, Lock, MessageCircleOff, MessageSquare, Moon, Plus, Power, Reply, RotateCcw, Save, Send, Settings2, ShieldCheck,
  Smartphone, Sparkles, Trash2, Undo2, UserRound, Workflow,
} from "lucide-react";
import { api, enviar, quando, type Agente } from "../api";
import { Alerta, Carregando, Interruptor, Painel, Vazio, useAcao, useAvisar, useCarregar } from "../componentes/ui";
import { useSessao } from "../sessao";
import { DashboardFollowup, HistoricoFollowup } from "./Followup";
import BotaoBrilho from "@/components/reactbits/BotaoBrilho";
import { LIMITE_ETAPA_FOLLOWUP, LIMITE_PROMPT_FOLLOWUP, PromptFollowupEditor, type VariavelFollowup } from "@/components/followup/PromptFollowupEditor";
import { ROLE_META, type AgentRole } from "@/hooks/useProducts";
import "../estilo-automacao.css";

// Backend: GET/PUT /agentes/:id/followup (app/gestao/rotas.py), motor em app/followup/ (regras.validar é quem manda).
interface Passo { apos_horas: number; modo: "ia" | "texto" | "modelo"; instrucao: string; texto: string }
interface Limites { max_toques_sem_resposta: number; oferecer_parar: boolean; lead_parado_apos: number }
interface Config {
  ativo: boolean; horario: { inicio: number; fim: number; dias: number[] }; intervalo_minimo_min: number; etapas: string[];
  prompt: string; por_etapa: Record<string, string>; passos: Passo[]; modelo_oficial: { id_modelo?: string; nome?: string };
  desistir: { ativo: boolean; apos_horas: number; nota: string }; modelo: string | null;
  decidir?: boolean;   // o agente de follow-up decide antes (enviar, adiar se o lead pediu para esperar, não enviar)
  limites?: Limites;   // regras da OAB e da Meta (quem ligou com o padrão novo)
}
interface Linha { passo: number; situacao: string; motivo: string | null; motivo_texto?: string | null; nome: string | null; desistencia?: boolean }
interface Dados {
  config: Config; configurado?: boolean;
  padrao: { prompt: string; cadencia: number[]; instrucoes: Record<string, string>; por_etapa?: Record<string, string> };
  variaveis?: VariavelFollowup[];
  etapas: { codigo: string; nome: string; tipo: string; pode_followup?: boolean }[]; tipo_canal: string;
  proximos: (Linha & { agendado_para: string; final: string })[];
  recentes: (Linha & { enviado_em: string | null; atualizado_em: string; mensagens: unknown })[];
}
type Resposta = Config & { reprogramacao?: { reprogramados: number; cancelados: number } };

const DIAS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"];
const SEM_FOLLOWUP = new Set(["desqualificado", "contrato_assinado"]);
const MIN_H = 10 / 60;
const MAX_H = 24 * 90;

type Unidade = "minutos" | "horas" | "dias";
const FATOR: Record<Unidade, number> = { minutos: 1 / 60, horas: 1, dias: 24 };
function unidade(horas: number): [number, Unidade] {
  if (!Number.isFinite(horas) || horas <= 0) return [0, "horas"];
  const minutos = Math.round(horas * 60);
  if (minutos < 60 || minutos % 60) return [minutos, "minutos"];
  if (horas >= 24 && horas % 24 === 0) return [horas / 24, "dias"];
  return [Math.round(horas), "horas"];
}
/** "30 min", "1 hora", "3 dias". */
export function tempoLegivel(h: number): string {
  const [n, u] = unidade(h);
  if (u === "minutos") return `${n} min`;
  if (u === "horas") return `${n} ${n === 1 ? "hora" : "horas"}`;
  return `${n} ${n === 1 ? "dia" : "dias"}`;
}
const juntar = (itens: string[]) => (itens.length <= 1 ? itens.join("") : `${itens.slice(0, -1).join(", ")} e ${itens[itens.length - 1]}`);
function diasLegiveis(dias: number[]): string {
  const d = [...dias].sort();
  if (d.length === 7) return "todos os dias";
  if (d.join() === "0,1,2,3,4") return "segunda a sexta";
  if (d.join() === "0,1,2,3,4,5") return "segunda a sábado";
  return juntar(d.map((i) => DIAS[i]));
}

/** Conferência antes de salvar, com a mesma regra do servidor (regras.validar), para a mensagem sair clara na hora. */
function conferir(c: Config, tipoCanal: string): string | null {
  if (c.passos.length === 0) return "Coloque pelo menos uma tentativa na cadência.";
  if (c.passos.length > 12) return "No máximo 12 tentativas.";
  for (const [i, p] of c.passos.entries()) {
    if (!Number.isFinite(p.apos_horas) || p.apos_horas < MIN_H - 1e-9 || p.apos_horas > MAX_H)
      return `A tentativa ${i + 1} precisa de um tempo entre 10 minutos e 90 dias.`;
  }
  const tempos = c.passos.map((p) => Math.round(p.apos_horas * 60));
  const repetido = tempos.findIndex((t, i) => tempos.indexOf(t) !== i);
  if (repetido >= 0) return `As tentativas ${tempos.indexOf(tempos[repetido]) + 1} e ${repetido + 1} estão com o mesmo tempo. Cada uma precisa de um tempo diferente.`;
  if (!(c.horario.inicio < c.horario.fim)) return "Horário permitido: o início precisa ser antes do fim.";
  if (c.horario.dias.length === 0) return "Escolha pelo menos um dia da semana para enviar.";
  if (!Number.isFinite(c.intervalo_minimo_min) || c.intervalo_minimo_min < 5 || c.intervalo_minimo_min > 1440)
    return "Intervalo mínimo entre mensagens: de 5 a 1440 minutos.";
  if (c.desistir.ativo && !(c.desistir.apos_horas >= 1)) return "Desistir do lead: espere pelo menos 1 hora depois da última tentativa.";
  if (c.prompt.length > LIMITE_PROMPT_FOLLOWUP)
    return `O prompt do follow-up passou de ${LIMITE_PROMPT_FOLLOWUP.toLocaleString("pt-BR")} caracteres. Encurte para salvar.`;
  const longa = Object.entries(c.por_etapa).find(([, t]) => (t ?? "").length > LIMITE_ETAPA_FOLLOWUP);
  if (longa) return `A instrução de uma etapa passou de ${LIMITE_ETAPA_FOLLOWUP.toLocaleString("pt-BR")} caracteres. Encurte para salvar.`;
  if (c.ativo && tipoCanal === "oficial" && !c.modelo_oficial.id_modelo)
    return "Número da API oficial: escolha o modelo aprovado (em \"Desistir e número oficial\") antes de ligar.";
  return null;
}

/** O que vai para o servidor: tentativas em ordem, todas escritas pela IA (sem texto fixo). */
const paraSalvar = (c: Config): Config => ({
  ...c, passos: [...c.passos].sort((a, b) => a.apos_horas - b.apos_horas).map((p) => ({ ...p, modo: "ia", texto: "" })),
});

function avisoDoSalvar(r: Resposta): string {
  const partes = [r.ativo ? "Follow-up salvo e ligado." : "Follow-up salvo (desligado)."];
  const rp = r.reprogramacao;
  if (r.ativo && rp?.reprogramados) partes.push(`${rp.reprogramados} agendado(s) passaram para a cadência nova.`);
  if (rp?.cancelados) partes.push(`${rp.cancelados} agendado(s) cancelado(s).`);
  if (r.ativo && !rp?.reprogramados) partes.push("Vale para cada lead a partir da próxima resposta da IA.");
  return partes.join(" ");
}

/** Resumo em palavras: "4 tentativas: 1 hora, 24 horas, 3 dias e 7 dias depois da última resposta da IA". */
function resumoDaConfig(c: Config, etapas: Dados["etapas"]): string[] {
  const passos = [...c.passos].sort((a, b) => a.apos_horas - b.apos_horas);
  const possiveis = etapas.filter((e) => e.pode_followup ?? (e.tipo === "conversa" && !SEM_FOLLOWUP.has(e.codigo)));
  const escolhidas = c.etapas.length ? possiveis.filter((e) => c.etapas.includes(e.codigo)) : possiveis;
  const linhas = [
    `${passos.length} ${passos.length === 1 ? "tentativa" : "tentativas"}: ${juntar(passos.map((p) => tempoLegivel(p.apos_horas)))} depois da última resposta da IA, se o lead não responder.`,
    `Envia de ${c.horario.inicio}h às ${c.horario.fim}h (Brasília), ${diasLegiveis(c.horario.dias)}.`,
    c.etapas.length ? `Só nas etapas: ${juntar(escolhidas.map((e) => e.nome))}.` : `Em todas as etapas de conversa (${juntar(possiveis.map((e) => e.nome))}).`,
  ];
  if (c.limites?.max_toques_sem_resposta) linhas.push(`Quem nunca respondeu à IA recebe no máximo ${c.limites.max_toques_sem_resposta}.`);
  linhas.push(c.desistir.ativo ? `Sem resposta ${tempoLegivel(c.desistir.apos_horas)} depois da última: a IA encerra a conversa.` : "Depois da última tentativa, a conversa fica como está.");
  return linhas;
}

/** Grupo de pílulas (no lugar do <select> nativo): uma escolha, a marcada em verde. */
function Pilulas<T extends string | number>({ rotulo, valor, opcoes, aoMudar, classe = "fu2-pils" }: {
  rotulo: string; valor: T; opcoes: { v: T; t: string }[]; aoMudar: (v: T) => void; classe?: string;
}) {
  return (
    <div className={classe} role="radiogroup" aria-label={rotulo}>
      {opcoes.map((o) => (
        <button key={String(o.v)} type="button" role="radio" aria-checked={o.v === valor} className={o.v === valor ? "on" : ""}
          onClick={() => aoMudar(o.v)}>{o.t}</button>
      ))}
    </div>
  );
}

// --------------------------------------------------------------------------- prévia no calendário
const diaSeg = (d: Date) => (d.getDay() + 6) % 7;             // 0 = segunda, como em horario.dias
const hhmm = (d: Date) => d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
function rotuloDia(d: Date, base: Date): string {
  const zero = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const dd = Math.round((zero(d) - zero(base)) / 864e5);
  if (dd === 0) return "mesmo dia";
  if (dd === 1) return "amanhã";
  return `${DIAS[diaSeg(d)].toLowerCase()} ${d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" })}`;
}
/** Próxima hora permitida a partir de d (a mesma ideia do motor: fora do horário, espera a próxima abertura). */
function abertura(d: Date, h: Config["horario"]): { d: Date; adiou: boolean } {
  const x = new Date(d);
  let adiou = false;
  if (!h.dias.length || !(h.inicio < h.fim)) return { d: x, adiou };
  for (let k = 0; k < 400; k++) {
    const hora = x.getHours() + x.getMinutes() / 60;
    const diaOk = h.dias.includes(diaSeg(x));
    if (diaOk && hora >= h.inicio && hora < h.fim) return { d: x, adiou };
    adiou = true;
    if (diaOk && hora < h.inicio) { x.setHours(h.inicio, 0, 0, 0); continue; }
    x.setDate(x.getDate() + 1); x.setHours(h.inicio, 0, 0, 0);
  }
  return { d: x, adiou };
}
const INICIOS = [{ rot: "Qui 14:00", dia: 3, h: 14, m: 0 }, { rot: "Sex 19:30", dia: 4, h: 19, m: 30 }, { rot: "Sáb 18:00", dia: 5, h: 18, m: 0 }];
function dataInicio(i: number): Date {
  const o = INICIOS[i];
  const d = new Date();
  d.setHours(o.h, o.m, 0, 0);
  d.setDate(d.getDate() + ((o.dia - diaSeg(d) + 7) % 7));
  return d;
}
interface Evento { tipo: "lead" | "envio" | "equipe" | "corte" | "fim"; quando?: Date; titulo: string; texto: string; tags: { cls: string; t: string; lua?: boolean }[] }
function eventosDaPrevia(c: Config, limites: Limites, base: Date): Evento[] {
  const horas = c.passos.map((p) => p.apos_horas).filter((h) => Number.isFinite(h) && h > 0).sort((a, b) => a - b);
  const ev: Evento[] = [{ tipo: "lead", quando: base, titulo: "Última mensagem da IA", texto: "O lead não respondeu. Começa a contar.", tags: [] }];
  const max = limites.max_toques_sem_resposta;
  let ultima = base;
  horas.forEach((h, i) => {
    if (max && i === max) ev.push({ tipo: "corte", titulo: "Quem nunca respondeu para aqui", tags: [],
      texto: `No máximo ${max} ${max === 1 ? "tentativa" : "tentativas"} para quem nunca falou com a IA.` });
    const alvo = new Date(base.getTime() + h * 36e5);
    const { d, adiou } = abertura(alvo, c.horario);
    ultima = d;
    const tags: Evento["tags"] = [];
    if (adiou) tags.push({ cls: "amb", t: `adiada: seria ${rotuloDia(alvo, base)} ${hhmm(alvo)}`, lua: true });
    if (limites.oferecer_parar && horas.length >= 2 && i === horas.length - 2) tags.push({ cls: "az", t: "oferece parar" });
    ev.push({ tipo: "envio", quando: d, titulo: `Tentativa ${i + 1}`, texto: `${tempoLegivel(h)} sem resposta`, tags });
    if (limites.lead_parado_apos && i === limites.lead_parado_apos - 1) ev.push({ tipo: "equipe", quando: d, titulo: "A equipe recebe um aviso",
      texto: "Lead parado. Vira tarefa se ninguém agir em 24 h.", tags: [] });
  });
  if (c.desistir.ativo && c.desistir.apos_horas >= 1) {
    const fim = new Date(ultima.getTime() + c.desistir.apos_horas * 36e5);
    ev.push({ tipo: "fim", quando: fim, titulo: "A IA encerra a conversa", texto: "E dispara a automação “O lead não respondeu a nenhum follow-up”.", tags: [] });
  }
  return ev;
}
const ICONE_EVENTO = { lead: MessageSquare, envio: Send, equipe: BellRing, corte: MessageCircleOff, fim: Ban };

// --------------------------------------------------------------------------- abas com indicador que desliza
type Aba = "cadencia" | "mensagens" | "resultados" | "historico";
const ABAS: { k: Aba; t: string; I: typeof Workflow }[] = [
  { k: "cadencia", t: "Cadência", I: Workflow }, { k: "mensagens", t: "Mensagens", I: MessageSquare },
  { k: "resultados", t: "Resultados", I: BarChart3 }, { k: "historico", t: "Histórico", I: History },
];
function AbasDeslizantes({ atual, aoMudar }: { atual: Aba; aoMudar: (a: Aba) => void }) {
  const caixa = useRef<HTMLDivElement>(null);
  const [ind, setInd] = useState<{ x: number; w: number } | null>(null);
  useLayoutEffect(() => {
    const el = caixa.current;
    if (!el) return;
    const medir = () => {
      const b = el.querySelector<HTMLButtonElement>(`[data-aba="${atual}"]`);
      if (b) setInd({ x: b.offsetLeft, w: b.offsetWidth });
    };
    medir();
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(medir) : null;
    ro?.observe(el);
    return () => ro?.disconnect();
  }, [atual]);
  // Só transform: o indicador tem 100px de base e escala até a largura da aba.
  const estilo: CSSProperties = ind ? { transform: `translateX(${ind.x}px) scaleX(${ind.w / 100})`, opacity: 1 } : { opacity: 0 };
  return (
    <div className="fu2-abas" role="tablist" aria-label="Partes do follow-up" ref={caixa}>
      <span className="fu2-abas-ind" aria-hidden style={estilo} />
      {ABAS.map(({ k, t, I }) => (
        <button key={k} type="button" role="tab" data-aba={k} aria-selected={atual === k} className={atual === k ? "on" : ""} onClick={() => aoMudar(k)}>
          <I size={15} />{t}
        </button>
      ))}
    </div>
  );
}

function Periodo({ dias, aoMudar }: { dias: number; aoMudar: (d: number) => void }) {
  return (
    <div className="fu2-periodo" role="radiogroup" aria-label="Período">
      {[7, 30, 90].map((d) => <button key={d} type="button" role="radio" aria-checked={dias === d} className={dias === d ? "on" : ""} onClick={() => aoMudar(d)}>{d} dias</button>)}
    </div>
  );
}

const NOMES = ["Primeira", "Segunda", "Terceira", "Quarta", "Quinta", "Sexta", "Sétima", "Oitava", "Nona", "Décima", "Décima primeira", "Décima segunda"];
const novoPasso = (h: number): Passo => ({ apos_horas: h, modo: "ia", instrucao: "", texto: "" });
/** Erro de cada tentativa na hora (mesma regra de conferir/regras.validar). */
function errosDosPassos(passos: Passo[]): Record<number, string> {
  const e: Record<number, string> = {};
  passos.forEach((p, i) => { if (!(Number.isFinite(p.apos_horas) && p.apos_horas >= MIN_H - 1e-9 && p.apos_horas <= MAX_H)) e[i] = "Precisa ficar entre 10 minutos e 90 dias."; });
  const t = passos.map((p) => Math.round(p.apos_horas * 60));
  t.forEach((m, i) => { const j = t.indexOf(m); if (j !== i && !e[i]) e[i] = `Mesmo tempo da tentativa ${j + 1}. Cada uma precisa de um tempo diferente.`; });
  return e;
}

// =========================================================================== página Follow-up do agente
/** Follow-up do agente num lugar só: ligar/desligar, cadência, horário, etapas, mensagem, resultados e histórico. */
export function AbaFollowup({ agente }: { agente: Agente }) {
  const { dados, erro, recarregar } = useCarregar<Dados>(`/agentes/${agente.id}/followup`, [], { guardar: false }); // formulário
  const modelos = useCarregar<{ id: string; nome: string; texto: string }[]>(dados?.tipo_canal === "oficial" ? "/integracoes/helena/modelos-aprovados" : null, [dados?.tipo_canal]);
  // Números do herói (o mesmo painel da aba Resultados, fixo em 30 dias).
  const numeros = useCarregar<{ totais: { enviados: number; respondidos: number; taxa_resposta: number } }>(`/followup/dashboard?dias=30&agente=${agente.id}`, [agente.id]);
  const { ocupado, executar } = useAcao();
  const avisar = useAvisar();
  const { catalogo } = useSessao();
  const [c, setC] = useState<Config | null>(null);
  const [previas, setPrevias] = useState<Record<number, string[]>>({});
  const [tentPrevia, setTentPrevia] = useState(0);
  const [dias, setDias] = useState(30);
  const [aba, setAba] = useState<Aba>("cadencia");
  const [inicio, setInicio] = useState(0);
  useEffect(() => { if (dados) setC(dados.config); }, [dados]);
  const mudou = useMemo(() => Boolean(dados && c && JSON.stringify(paraSalvar(c)) !== JSON.stringify(paraSalvar(dados.config))), [dados, c]);
  // Sair da página com alteração não salva: o navegador pergunta antes.
  useEffect(() => {
    if (!mudou) return;
    const segurar = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", segurar);
    return () => window.removeEventListener("beforeunload", segurar);
  }, [mudou]);

  if (!dados || !c) return (
    <div className="stack">
      <Carregando erro={erro ? `Não deu para abrir a configuração do follow-up: ${erro}` : null} />
      {erro && <Painel titulo="Histórico do follow-up"><HistoricoFollowup dias={30} agente={agente.id} compacto /></Painel>}
    </div>
  );

  const etapasPossiveis = dados.etapas.filter((e) => e.pode_followup ?? (e.tipo === "conversa" && !SEM_FOLLOWUP.has(e.codigo)));
  const codigosPossiveis = etapasPossiveis.map((e) => e.codigo);
  const etapasMarcadas = c.etapas.filter((e) => codigosPossiveis.includes(e));
  const mudarPasso = (i: number, p: Partial<Passo>) => setC({ ...c, passos: c.passos.map((x, j) => (j === i ? { ...x, ...p } : x)) });
  const totalPassos = c.passos.length;
  const limites: Limites = c.limites ?? { max_toques_sem_resposta: 0, oferecer_parar: false, lead_parado_apos: 3 };
  const mudarLimites = (l: Partial<Limites>) => setC({ ...c, limites: { ...limites, ...l } });
  const horasOrd = c.passos.map((p) => p.apos_horas).sort((a, b) => a - b);
  const erros = errosDosPassos(c.passos);
  // Ao sair do cartão, as tentativas voltam para a ordem do tempo (a mais cedo primeiro), como o servidor guarda.
  const ordenar = () => setC((v) => {
    if (!v) return v;
    const ord = [...v.passos].sort((a, b) => a.apos_horas - b.apos_horas);
    return ord.every((p, i) => p === v.passos[i]) ? v : { ...v, passos: ord };
  });
  const aplicarCadencia = (horas: number[]) => setC({ ...c, passos: horas.map(novoPasso) });
  const MODELOS: [string, number[]][] = [
    ["Padrão LawChat", dados.padrao.cadencia], ["Mais rápida", [0.5, 4, 24, 72]], ["Mais leve", [24, 72, 168]], ["Insistente", [1, 6, 24, 72, 168]],
  ];
  const chaveCad = (h: number[]) => [...h].sort((a, b) => a - b).map((x) => Math.round(x * 60)).join();

  const salvar = (config: Config) => executar(async () => {
    const problema = conferir(config, dados.tipo_canal);
    if (problema) throw new Error(problema);
    const r = await enviar<Resposta>(`/agentes/${agente.id}/followup`, paraSalvar(config), "PUT");
    recarregar();
    return r;
  }).then((r) => {
    if (r) { const { reprogramacao: _r, ...salva } = r; setC(salva); }   // eslint-disable-line @typescript-eslint/no-unused-vars
    return r;
  });
  const salvarComAviso = (config: Config) => salvar(config).then((r) => { if (r) avisar(avisoDoSalvar(r)); });
  // O interruptor do topo salva na hora (antes ele só mudava a tela e quem saía sem clicar em Salvar ficava desligado).
  const ligar = (v: boolean) => salvarComAviso({ ...(mudou ? c : dados.config), ativo: v });
  const previa = (i: number) => executar(async () => {
    const r = await enviar<{ mensagens: string[]; aviso?: string }>(`/agentes/${agente.id}/followup/previa`,
      { passo: i, config: paraSalvar(c) });
    setPrevias((v) => ({ ...v, [i]: r.aviso ? [...r.mensagens, r.aviso] : r.mensagens }));
  });
  const ligadoSalvo = dados.config.ativo;
  const estado = ligadoSalvo ? "Ligado" : dados.configurado ? "Desligado" : "Não configurado";
  const t30 = numeros.dados?.totais;
  const proximo = dados.proximos[0];
  const eventos = eventosDaPrevia(c, limites, dataInicio(inicio));
  const ultimaH = horasOrd[horasOrd.length - 1] ?? 0;
  const iconeEtapa = (codigo: string) => ROLE_META[codigo as AgentRole]?.Icon ?? Layers;
  const d = (n: number) => ({ "--d": n } as CSSProperties);

  return (
    <div className="fu2">
      {/* ===== Herói: ligado?, resumo e números ===== */}
      <section className="fu2-card fu2-hero" style={d(0)}>
        <div className="fu2-aurora" aria-hidden><i /><i /></div>
        <div className="fu2-hero-esq">
          <span className="fu2-olho"><Sparkles size={13} />Automação{agente.nome ? ` · agente ${agente.nome}` : ""}</span>
          <h1>Follow-up
            <span className={`fu2-pil ${ligadoSalvo ? "verde" : "cinza"}`}>{ligadoSalvo && <em />}{estado}</span>
            {agente.situacao === "pausado" ? <span className="fu2-pil cinza">Agente pausado</span>
              : agente.modo === "teste" ? <span className="fu2-pil azul">Em teste</span> : null}
          </h1>
          <p className="fu2-frase">{ligadoSalvo
            ? <>Quando o lead para de responder, a IA retoma em <b>{totalPassos} {totalPassos === 1 ? "tentativa" : "tentativas"}</b> ({juntar(horasOrd.map(tempoLegivel))} depois da última mensagem dela),
              das <b>{c.horario.inicio}h às {c.horario.fim}h</b>, {diasLegiveis(c.horario.dias)}. Para sozinha quando o lead responde ou a equipe assume.</>
            : dados.configurado
              ? <>O follow-up está <b>desligado</b>: nenhum lead parado recebe retomada. A cadência fica guardada para quando você ligar.</>
              : <>Este agente ainda não tem follow-up. A cadência padrão ({juntar(dados.padrao.cadencia.map(tempoLegivel))}) já está pronta abaixo: ajuste se quiser e ligue aqui.</>}
          </p>
          <div className="fu2-hero-liga">
            <label className="fu2-liga">
              <Interruptor rotulo={ligadoSalvo ? "Desligar o follow-up" : "Ligar o follow-up"} ligado={ligadoSalvo} desligado={ocupado} aoMudar={ligar} />
              <span><b>{ligadoSalvo ? "Retomando leads parados" : "Follow-up desligado"}</b>
                <small>{ligadoSalvo ? "Para sozinho quando o lead responde" : "Ligue para voltar a retomar os leads (salva na hora)"}</small></span>
            </label>
            <button type="button" className="fu2-btn-borda alto" onClick={() => setAba("mensagens")}><Eye size={15} />Ver como o lead recebe</button>
          </div>
          {ligadoSalvo && dados.tipo_canal === "oficial" && <p className="fu2-nota"><Info size={13} />Número oficial: depois de 24 h sem o lead escrever, sai o modelo aprovado.</p>}
        </div>
        <div className="fu2-stats">
          <div className="fu2-stat"><span className="fu2-chip azul"><CalendarClock size={16} /></span><div>
            <b>{dados.proximos.length}</b><small>{proximo ? `agendado${dados.proximos.length === 1 ? "" : "s"} · próximo ${quando(proximo.agendado_para)}` : "agendados agora"}</small></div></div>
          <div className="fu2-stat"><span className="fu2-chip verde"><Send size={16} /></span><div>
            <b>{t30 ? t30.enviados : "…"}</b><small>enviados em 30 dias</small></div></div>
          <div className="fu2-stat"><span className="fu2-chip ambar"><Reply size={16} /></span><div>
            <b>{t30 ? (t30.enviados ? `${t30.taxa_resposta.toLocaleString("pt-BR")}%` : "—") : "…"}</b><small>taxa de resposta</small></div></div>
          <div className="fu2-stat"><span className="fu2-chip roxo"><ListOrdered size={16} /></span><div>
            <b>{totalPassos}</b><small>{totalPassos === 1 ? "tentativa" : "tentativas"} na cadência</small></div></div>
        </div>
      </section>

      <div className="fu2-abas-linha">
        <AbasDeslizantes atual={aba} aoMudar={setAba} />
        <span className="fu2-dica"><Info size={14} />As mudanças valem depois de salvar, a partir da próxima resposta da IA.</span>
      </div>

      {/* ===== Cadência ===== */}
      {aba === "cadencia" && <section className="fu2-aba" key="cadencia">
        <div className="fu2-g2">
          <div className="fu2-col">
            <div className="fu2-card fu2-painel" style={d(1)}>
              <div className="fu2-ph"><h3><Workflow size={16} className="c-verde" />Sequência de tentativas</h3>
                <button type="button" className="fu2-btn-borda" onClick={() => aplicarCadencia(dados.padrao.cadencia)}><RotateCcw size={14} />Cadência padrão</button></div>
              <p className="fu2-sub">Cada tempo conta a partir da <b>última mensagem da IA</b>, não soma com o anterior. Se o lead responder, a sequência para e recomeça depois da próxima resposta da IA.</p>
              <div className="fu2-resumo4">
                {([
                  [Clock, "Primeira mensagem", horasOrd.length ? tempoLegivel(horasOrd[0]) : "—", "depois da IA"],
                  [Clock, "Última mensagem", horasOrd.length ? tempoLegivel(ultimaH) : "—", "depois da IA"],
                  [Hourglass, "Duração total", tempoLegivel(ultimaH + (c.desistir.ativo ? c.desistir.apos_horas || 0 : 0)), c.desistir.ativo ? "até encerrar" : "de sequência"],
                  [Smartphone, "Canal", dados.tipo_canal === "oficial" ? "API oficial" : "WhatsApp", "a IA escreve cada uma"],
                ] as const).map(([I, a, b, s]) => (
                  <div key={a}><span className="fu2-chip claro"><I size={16} /></span><div><small>{a}</small><b>{b}</b><small>{s}</small></div></div>
                ))}
              </div>

              <div className="fu2-passos">
                {c.passos.map((p, i) => {
                  const [n, u] = unidade(p.apos_horas);
                  const max = limites.max_toques_sem_resposta;
                  return (
                    <div key={i} className={`fu2-passo${erros[i] ? " erro" : ""}`}
                      onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) ordenar(); }}>
                      <span className="fu2-num">{i + 1}</span>
                      <div className="fu2-passo-meio">
                        <div className="fu2-tit">{NOMES[i] ?? `${i + 1}ª`} tentativa</div>
                        <div className="fu2-tags">
                          <span className="fu2-tag wa"><MessageSquare size={12} />{dados.tipo_canal === "oficial" ? "API oficial" : "WhatsApp"}</span>
                          <span className="fu2-tag ia"><Sparkles size={12} />IA escreve</span>
                          {max > 0 && i >= max && <span className="fu2-tag cz">só para quem já respondeu</span>}
                          {limites.oferecer_parar && totalPassos >= 2 && i === totalPassos - 2 && <span className="fu2-tag az"><Hand size={12} />oferece parar</span>}
                          {limites.lead_parado_apos > 0 && i === limites.lead_parado_apos - 1 && <span className="fu2-tag amb"><BellRing size={12} />avisa a equipe</span>}
                        </div>
                      </div>
                      <div className="fu2-quando">
                        <span className="fu2-quando-rot">Sem resposta <br />por</span>
                        <span className="fu2-tempo">
                          <input type="number" min={1} step={1} aria-label={`Tempo da tentativa ${i + 1}`} value={n || ""}
                            onChange={(e) => mudarPasso(i, { apos_horas: Number(e.target.value) * FATOR[u] })} />
                          <Pilulas classe="fu2-unid" rotulo={`Unidade da tentativa ${i + 1}`} valor={u}
                            opcoes={[{ v: "minutos", t: "min" }, { v: "horas", t: "horas" }, { v: "dias", t: "dias" }]}
                            aoMudar={(nova) => mudarPasso(i, { apos_horas: n * FATOR[nova as Unidade] })} />
                        </span>
                        <button className="fu2-btn-ico" type="button" aria-label={`Tirar a tentativa ${i + 1}`} title="Tirar esta tentativa"
                          disabled={totalPassos <= 1} onClick={() => setC({ ...c, passos: c.passos.filter((_, j) => j !== i) })}><Trash2 size={15} /></button>
                      </div>
                      {erros[i] && <div className="fu2-erro"><CircleAlert size={14} />{erros[i]}</div>}
                    </div>
                  );
                })}
                <div className={`fu2-passo fim${c.desistir.ativo ? "" : " off"}`}>
                  <span className="fu2-num"><Ban size={16} /></span>
                  <div className="fu2-passo-meio">
                    <div className="fu2-tit">{c.desistir.ativo ? `Encerrar ${tempoLegivel(c.desistir.apos_horas)} depois da última` : "Depois da última, a conversa fica como está"}</div>
                    <div className="fu2-tags"><span className="fu2-tag cz">{c.desistir.ativo ? "a IA encerra e dispara a automação" : "ligue “Desistir do lead” para encerrar"}</span></div>
                  </div>
                </div>
                {totalPassos < 12 && (
                  <button type="button" className="fu2-add" onClick={() => {
                    const ult = Math.max(0, ...c.passos.map((p) => p.apos_horas));
                    setC({ ...c, passos: [...c.passos, novoPasso(Math.min(MAX_H, ult <= 0 ? 1 : ult < 24 ? ult * 2 : ult + 72))] });
                  }}><Plus size={16} />Adicionar tentativa</button>
                )}
              </div>
              <div className="fu2-atalhos"><span>Modelos prontos:</span>
                {MODELOS.map(([t, h]) => (
                  <button key={t} type="button" className={chaveCad(h) === chaveCad(horasOrd) ? "on" : ""} onClick={() => aplicarCadencia(h)}>{t}</button>
                ))}
              </div>
            </div>

            <div className="fu2-card fu2-painel" style={d(2)}>
              <div className="fu2-ph"><h3><ShieldCheck size={16} className="c-ambar" />Regras para não insistir demais</h3></div>
              <div className="fu2-regras">
                <div className="fu2-regra">
                  <span className="fu2-chip cinza"><MessageCircleOff size={16} /></span>
                  <div className="fu2-regra-corpo"><b>Quem nunca respondeu recebe no máximo</b><span className="aj">Para não insistir com quem nunca falou nada com a IA.</span>
                    <Pilulas rotulo="Máximo de tentativas para quem nunca respondeu" valor={limites.max_toques_sem_resposta}
                      opcoes={[{ v: 0, t: "Todas" }, ...Array.from({ length: Math.max(totalPassos, limites.max_toques_sem_resposta, 1) }, (_, k) => ({ v: k + 1, t: `${k + 1}` }))]}
                      aoMudar={(v) => mudarLimites({ max_toques_sem_resposta: v })} /></div>
                </div>
                <div className="fu2-regra">
                  <span className="fu2-chip ambar"><BellRing size={16} /></span>
                  <div className="fu2-regra-corpo"><b>Avisar a equipe quando o lead parar</b><span className="aj">Depois de quantas tentativas sem resposta. 24 h depois, vira tarefa da equipe.</span>
                    <Pilulas rotulo="Avisar a equipe depois de quantas tentativas" valor={limites.lead_parado_apos}
                      opcoes={[{ v: 0, t: "Não avisar" }, ...Array.from({ length: Math.max(totalPassos, limites.lead_parado_apos, 1) }, (_, k) => ({ v: k + 1, t: `${k + 1}` }))]}
                      aoMudar={(v) => mudarLimites({ lead_parado_apos: v })} /></div>
                </div>
                <div className="fu2-regra larga">
                  <span className="fu2-chip verde"><Hand size={16} /></span>
                  <div className="fu2-regra-corpo"><b>Oferecer parar na penúltima tentativa</b>
                    <span className="aj">“Se preferir que eu não mande mais mensagens, é só me avisar.” Recomendado pela OAB e pela Meta.</span></div>
                  <Interruptor rotulo={limites.oferecer_parar ? "Não oferecer parar" : "Oferecer parar"} ligado={limites.oferecer_parar}
                    aoMudar={(v) => mudarLimites({ oferecer_parar: v })} />
                </div>
              </div>
            </div>
          </div>

          <aside className="fu2-col fu2-sticky">
            <div className="fu2-card fu2-painel" style={d(3)}>
              <div className="fu2-ph"><h3><Eye size={16} className="c-azul" />No calendário</h3></div>
              <p className="fu2-sub">O que acontece se o lead parar de responder em:</p>
              <Pilulas rotulo="Quando o lead parou" valor={inicio} opcoes={INICIOS.map((o, i) => ({ v: i, t: o.rot }))} aoMudar={(v) => setInicio(Number(v))} />
              <div className="fu2-linha" key={`${inicio}-${eventos.length}`}>
                {eventos.map((ev, k) => {
                  const I = ICONE_EVENTO[ev.tipo];
                  return (
                    <div key={k} className={`fu2-ev ${ev.tipo}`} style={{ "--k": k } as CSSProperties}>
                      <div className="h">{ev.quando ? <>{hhmm(ev.quando)}<small>{ev.tipo === "lead" ? DIAS[diaSeg(ev.quando)].toLowerCase() : rotuloDia(ev.quando, eventos[0].quando!)}</small></> : null}</div>
                      <span className="bol"><I size={15} /></span>
                      <div className="t"><b>{ev.titulo}</b><span>{ev.texto}</span>
                        {ev.tags.map((g) => <span key={g.t} className={`fu2-tag ${g.cls}`}>{g.lua && <Moon size={12} />}{g.t}</span>)}</div>
                    </div>
                  );
                })}
              </div>
              <div className="fu2-nao-envia"><b>Não envia quando</b>
                <ul>
                  <li><Reply size={14} />o lead responde (a sequência recomeça)</li>
                  <li><UserRound size={14} />alguém da equipe assume a conversa</li>
                  <li><CirclePause size={14} />a IA está desligada nessa conversa</li>
                  <li><Lock size={14} />o lead foi encerrado ou já assinou</li>
                  <li><Hand size={14} />o lead pediu para parar</li>
                </ul></div>
            </div>
          </aside>
        </div>

        <div className="fu2-g2b">
          <div className="fu2-card fu2-painel" style={d(4)}>
            <div className="fu2-ph"><h3><Clock size={16} className="c-azul" />Horário permitido</h3><span className="fu2-tot">horário de Brasília</span></div>
            <div className="fu2-horas">
              <span>Das</span>
              <select className="fu2-campo" aria-label="Início" value={c.horario.inicio} onChange={(e) => setC({ ...c, horario: { ...c.horario, inicio: Number(e.target.value) } })}>
                {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{h}h</option>)}</select>
              <span>às</span>
              <select className="fu2-campo" aria-label="Fim" value={c.horario.fim} onChange={(e) => setC({ ...c, horario: { ...c.horario, fim: Number(e.target.value) } })}>
                {Array.from({ length: 24 }, (_, h) => h + 1).map((h) => <option key={h} value={h}>{h}h</option>)}</select>
            </div>
            <div className="fu2-faixa" aria-hidden>
              <div className="ok" style={{ transform: `translateX(${(c.horario.inicio / 24) * 100}%) scaleX(${Math.max(0, c.horario.fim - c.horario.inicio) / 24})` }} />
              <div className="marcas"><span>0h</span><span>6h</span><span>12h</span><span>18h</span><span>24h</span></div>
            </div>
            {!(c.horario.inicio < c.horario.fim) && <p className="fu2-erro solto"><CircleAlert size={14} />O início precisa ser antes do fim.</p>}
            <div className="fu2-dias">{DIAS.map((nome, i) => {
              const on = c.horario.dias.includes(i);
              return <button key={nome} type="button" className={on ? "on" : ""} aria-pressed={on} onClick={() => {
                if (on && c.horario.dias.length === 1) { avisar("Deixe pelo menos um dia da semana.", "bad"); return; }
                setC({ ...c, horario: { ...c.horario, dias: on ? c.horario.dias.filter((x) => x !== i) : [...c.horario.dias, i].sort() } });
              }}>{nome}</button>;
            })}</div>
            <span className="fu2-ajuda">Fora do horário, a tentativa espera a próxima abertura. Veja na prévia ao lado.</span>
            <div className="fu2-horas" style={{ marginTop: 14 }}>
              <span className="forte">Intervalo mínimo entre mensagens ao mesmo lead</span>
              <input className="fu2-campo" style={{ width: 84 }} type="number" min={5} max={1440} aria-label="Intervalo mínimo em minutos"
                value={c.intervalo_minimo_min} onChange={(e) => setC({ ...c, intervalo_minimo_min: Number(e.target.value) })} />
              <span>minutos</span>
            </div>
          </div>

          <div className="fu2-card fu2-painel" style={d(5)}>
            <div className="fu2-ph"><h3><Workflow size={16} className="c-verde" />Etapas do CRM em que vale</h3>
              <span className="fu2-tot">{etapasMarcadas.length === 0 ? codigosPossiveis.length : etapasMarcadas.length} de {codigosPossiveis.length}</span></div>
            {etapasPossiveis.length === 0 ? <Vazio>Este agente não tem etapa de conversa que recebe follow-up.</Vazio> : (
              <div className="fu2-etapas">{etapasPossiveis.map((e) => {
                const marcada = etapasMarcadas.length === 0 || etapasMarcadas.includes(e.codigo);
                const I = iconeEtapa(e.codigo);
                return <button key={e.codigo} type="button" className={`fu2-etapa${marcada ? " on" : ""}`} aria-pressed={marcada} onClick={() => {
                  const base = etapasMarcadas.length === 0 ? codigosPossiveis : etapasMarcadas;
                  const nova = marcada ? base.filter((x) => x !== e.codigo) : [...base, e.codigo];
                  if (nova.length === 0) { avisar("Deixe pelo menos uma etapa.", "bad"); return; }   // nenhuma marcada seria "todas"
                  setC({ ...c, etapas: nova.length === codigosPossiveis.length ? [] : nova });
                }}>
                  <span className="fu2-chip"><I size={17} /></span>
                  <div><b>{e.nome}</b><small>{marcada ? "recebe follow-up" : "sem follow-up"}</small></div>
                  <span className="ck"><Check size={13} strokeWidth={3} /></span>
                </button>;
              })}</div>
            )}
            <span className="fu2-ajuda">Encerramento e contrato assinado nunca recebem follow-up.</span>

            <div className="fu2-regra" style={{ marginTop: 12 }}>
              <span className="fu2-chip vermelho"><Ban size={16} /></span>
              <div className="fu2-regra-corpo"><b>Desistir do lead</b>
                <span className="aj">Depois da última tentativa sem resposta, a IA encerra a conversa e dispara a automação “O lead não respondeu a nenhum follow-up”.</span>
                {c.desistir.ativo && <>
                  <div className="fu2-horas" style={{ marginTop: 10 }}><span>Esperar</span>
                    <input className="fu2-campo" style={{ width: 76 }} type="number" min={1} aria-label="Horas depois da última tentativa"
                      value={c.desistir.apos_horas} onChange={(e) => setC({ ...c, desistir: { ...c.desistir, apos_horas: Number(e.target.value) } })} />
                    <span>horas depois da última</span></div>
                  <label className="fu2-rotulo" style={{ marginTop: 10 }}>Nota para a equipe
                    <textarea className="fu2-campo area" rows={2} value={c.desistir.nota} onChange={(e) => setC({ ...c, desistir: { ...c.desistir, nota: e.target.value } })} /></label>
                </>}
              </div>
              <Interruptor rotulo="Desistir do lead" ligado={c.desistir.ativo} aoMudar={(v) => setC({ ...c, desistir: { ...c.desistir, ativo: v } })} />
            </div>

            {dados.tipo_canal === "oficial" && (
              <div className="fu2-regra" style={{ marginTop: 10 }}>
                <span className="fu2-chip azul"><Smartphone size={16} /></span>
                <div className="fu2-regra-corpo"><b>Modelo aprovado do número oficial</b>
                  <span className="aj">{modelos.erro ? `Não deu para buscar os modelos aprovados: ${modelos.erro}` : "Na API oficial, depois de 24 h sem o lead escrever, só modelo aprovado pela Meta abre a conversa."}</span>
                  <select className="fu2-campo" style={{ marginTop: 10, maxWidth: 360 }} aria-label="Modelo aprovado" value={c.modelo_oficial.id_modelo ?? ""} onChange={(e) => {
                    const m = (modelos.dados ?? []).find((x) => x.id === e.target.value);
                    setC({ ...c, modelo_oficial: m ? { id_modelo: m.id, nome: m.nome } : {} });
                  }}>
                    <option value="">Escolher…</option>
                    {(modelos.dados ?? []).map((m) => <option key={m.id} value={m.id}>{m.nome}</option>)}
                  </select></div>
              </div>
            )}
          </div>
        </div>
      </section>}

      {/* ===== Mensagens ===== */}
      {aba === "mensagens" && <section className="fu2-aba" key="mensagens">
        <PromptFollowupEditor
          nomeAgente={agente.nome}
          prompt={c.prompt} promptSalvo={dados.config.prompt} promptPadrao={dados.padrao.prompt}
          porEtapa={c.por_etapa} porEtapaSalvo={dados.config.por_etapa} porEtapaPadrao={dados.padrao.por_etapa ?? {}}
          etapas={etapasPossiveis}
          variaveis={dados.variaveis ?? []}
          onPrompt={(t) => setC((v) => (v ? { ...v, prompt: t } : v))}
          onEtapa={(codigo, t) => setC((v) => (v ? { ...v, por_etapa: { ...v.por_etapa, [codigo]: t } } : v))}
          previa={
            <div className="fu2-card fu2-cel">
              <div className="fu2-ph"><h3><Smartphone size={16} className="c-verde" />Como o lead recebe</h3></div>
              <div className="fu2-cel-tela">
                <div className="fu2-cel-topo"><span className="fu2-cel-av">{(agente.nome || "A").slice(0, 1).toUpperCase()}</span>
                  <div><b>{agente.nome || "Agente"}</b><small>{ocupado ? "digitando…" : "online"}</small></div></div>
                <div className="fu2-cel-msgs">
                  <span className="fu2-bal sis">Lead sem responder · tentativa {tentPrevia + 1}</span>
                  {previas[tentPrevia]?.length
                    ? previas[tentPrevia].map((t, j) => <div key={`${tentPrevia}-${j}`} className="fu2-bal ia" style={{ animationDelay: `${j * 120}ms` }}>{t}</div>)
                    : ocupado ? <div className="fu2-digitando"><i /><i /><i /></div>
                    : <p className="fu2-cel-vazio">Clique em <b>Gerar exemplo</b> para ver a mensagem que o agente escreveria nesta tentativa.</p>}
                </div>
              </div>
              <div className="fu2-cel-pe">
                <BotaoBrilho size="sm" radius={10} onClick={() => previa(tentPrevia)} disabled={ocupado}><Sparkles className="size-3.5" />Gerar exemplo</BotaoBrilho>
                <select className="fu2-campo" aria-label="Tentativa do exemplo" value={tentPrevia} onChange={(e) => setTentPrevia(Number(e.target.value))}>
                  {c.passos.map((_, i) => <option key={i} value={i}>{i + 1}ª tentativa</option>)}
                </select>
              </div>
              <span className="fu2-ajuda">O exemplo usa uma conversa de teste e gasta uma chamada de IA. Usa o texto que está na tela, mesmo sem salvar.</span>
            </div>}
          rodape={<>
            <div className="fu2-linha-campos">
              <label className="fu2-rotulo">Modelo de IA do follow-up
                <select className="fu2-campo" value={c.modelo ?? ""} onChange={(e) => setC({ ...c, modelo: e.target.value || null })}>
                  <option value="">Padrão do servidor (GPT-4.1 mini)</option>
                  {(catalogo?.modelos ?? []).map((m) => <option key={m.id} value={m.id}>{m.nome}</option>)}
                </select></label>
              <div className="fu2-regra compacta">
                <div className="fu2-regra-corpo"><b>O agente decide antes de enviar</b>
                  <span className="aj">Lê a conversa: adia se o lead pediu para falar depois e não envia se não fizer sentido.</span></div>
                <Interruptor rotulo="O agente de follow-up decide antes de enviar" ligado={c.decidir !== false} aoMudar={(v) => setC({ ...c, decidir: v })} />
              </div>
            </div>
            <p className="fu2-regras-fixas"><Lock size={14} />Quem escreve é o agente da etapa em que o lead está, com a voz dele. Sempre valem: sem link, sem prometer resultado, prazo ou valor.</p>
          </>}
        />
      </section>}

      {/* ===== Resultados ===== */}
      {aba === "resultados" && <section className="fu2-aba fu2-resultados" key="resultados">
        <div className="fu2-abas-linha topo">
          <span className="fu2-dica">Resultados do follow-up deste agente. Visão de todos os agentes em <Link to="/ferramentas/followup">Ferramentas › Follow-up</Link>.</span>
          <Periodo dias={dias} aoMudar={setDias} />
        </div>
        <DashboardFollowup dias={dias} agente={agente.id} compacto />
        <div className="fu2-g3">
          <div className="fu2-card fu2-painel" style={d(6)}>
            <div className="fu2-ph"><h3><CalendarClock size={16} className="c-azul" />Próximos agendados</h3><span className="fu2-tot">{dados.proximos.length}</span></div>
            {dados.proximos.length === 0 ? <Vazio icone={<CalendarClock />}>{ligadoSalvo
              ? "Nenhum follow-up agendado agora. Ele é agendado depois de cada resposta da IA, para quem está numa etapa com follow-up."
              : "Nada agendado: o follow-up está desligado."}</Vazio> : (
              <div className="fu2-agendados">{dados.proximos.map((p, i) => (
                <div key={i} className="fu2-ag">
                  <span className="av">{(p.nome || "?").slice(0, 1).toUpperCase()}</span>
                  <div><b>{p.nome || "Lead sem nome"}</b>
                    <small>final {p.final} · {p.desistencia ? "Desistência (encerrar a conversa)" : `Tentativa ${p.passo + 1} de ${Math.max(totalPassos, p.passo + 1)}`}</small>
                    {p.motivo_texto && <small>{p.motivo_texto}</small>}</div>
                  <div className="contagem"><b>{p.situacao === "reservado" ? "agora" : quando(p.agendado_para)}</b><small>{p.situacao === "reservado" ? "enviando" : "previsto"}</small></div>
                </div>))}
              </div>)}
          </div>
          <div className="fu2-card fu2-painel" style={d(7)}>
            <div className="fu2-ph"><h3><Send size={16} className="c-verde" />Últimos enviados e cancelados</h3></div>
            {dados.recentes.length === 0 ? <Vazio>Nenhum follow-up enviado ou cancelado ainda.</Vazio> : (
              <div className="fu2-recentes">{dados.recentes.map((r, i) => {
                const textos = Array.isArray(r.mensagens) ? (r.mensagens as unknown[]).filter((m): m is string => typeof m === "string") : [];
                const cls = r.situacao === "enviado" ? "ok" : r.situacao === "falhou" ? "bad" : "no";
                return (
                  <div key={i} className="fu2-it">
                    <div className="l1"><b>{r.nome || "Lead sem nome"}</b>
                      <span className={`fu2-situ ${cls}`}>{r.situacao === "enviado" ? "enviado" : r.situacao === "falhou" ? "falhou" : "não enviado"}</span>
                      <span className="fu2-it-tent">{r.desistencia ? "Desistência" : `Tentativa ${r.passo + 1}`}</span>
                      <span className="hr">{quando(r.enviado_em ?? r.atualizado_em)}</span></div>
                    {(r.situacao !== "enviado" || r.desistencia) && r.motivo_texto && <div className="mot">Motivo: {r.motivo_texto}</div>}
                    {r.situacao === "enviado" && textos.length > 0 && <div className="txt">“{textos.join(" ")}”</div>}
                  </div>);
              })}</div>)}
          </div>
        </div>
      </section>}

      {/* ===== Histórico ===== */}
      {aba === "historico" && <section className="fu2-aba" key="historico">
        <div className="fu2-abas-linha topo">
          <span className="fu2-dica">Cada follow-up deste agente, com filtro por situação. Clique numa linha para ver a mensagem.</span>
          <Periodo dias={dias} aoMudar={setDias} />
        </div>
        <div className="fu2-card fu2-painel"><HistoricoFollowup dias={dias} agente={agente.id} compacto /></div>
      </section>}

      {/* Barra de salvar: aparece quando há alteração. */}
      {mudou && (
        <div className="fu2-salvar-lugar">
          <div className="fu2-salvar" role="region" aria-label="Alterações não salvas">
            <span className="pt" /><span className="txt">Alterações não salvas<span className="ext"> no follow-up</span></span>
            <button type="button" className="des" onClick={() => setC(dados.config)} disabled={ocupado}><Undo2 size={15} />Descartar</button>
            <BotaoBrilho size="sm" radius={10} onClick={() => salvarComAviso(c)} disabled={ocupado}><Save className="size-3.5" />Salvar follow-up</BotaoBrilho>
          </div>
        </div>
      )}
    </div>
  );
}

// =========================================================================== painel na Ativação do agente
/** Na página do agente (Ativação): ver se está ligado, ligar/desligar na hora e ir montar a cadência. */
export function PainelFollowupDoAgente({ agente }: { agente: Agente }) {
  const { dados, erro, recarregar } = useCarregar<Dados>(`/agentes/${agente.id}/followup`, [agente.id], { guardar: false });
  const { ocupado, executar } = useAcao();
  const avisar = useAvisar();
  const link = `/agentes/${agente.id}/followup`;
  const alternar = (ligar: boolean) => executar(async () => {
    const atual = dados ?? await api<Dados>(`/agentes/${agente.id}/followup`);
    const config = { ...atual.config, ativo: ligar };
    const problema = conferir(config, atual.tipo_canal);
    if (problema) throw new Error(`${problema} Abra "Montar cadência" para ajustar.`);
    const r = await enviar<Resposta>(`/agentes/${agente.id}/followup`, paraSalvar(config), "PUT");
    recarregar();
    return r;
  }).then((r) => { if (r) avisar(avisoDoSalvar(r)); });

  if (!dados) return <Painel titulo="Follow-up"><Carregando erro={erro ? `Não deu para abrir o follow-up: ${erro}` : null} /></Painel>;
  const ligado = dados.config.ativo;
  const passos = [...dados.config.passos].sort((a, b) => a.apos_horas - b.apos_horas);
  const enviados = dados.recentes.filter((r) => r.situacao === "enviado").length;
  const naoEnviados = dados.recentes.length - enviados;
  return (
    <Painel titulo={<h3 className="fu-titulo">Follow-up <span className={`chip ${ligado ? "ok" : ""}`}><span className="d" />{ligado ? "Ligado" : dados.configurado ? "Desligado" : "Não configurado"}</span></h3>}
      acoes={<label className="fu-ligar"><span>{ligado ? "Ligado" : "Desligado"}</span>
        <Interruptor rotulo={ligado ? "Desligar o follow-up" : "Ligar o follow-up"} ligado={ligado} desligado={ocupado} aoMudar={alternar} /></label>}>
      <div className="form">
        <div className="fu-cadencia" aria-label="Cadência">
          {passos.map((p, i) => <Fragment key={i}>{i > 0 && <i />}<span>{tempoLegivel(p.apos_horas)}</span></Fragment>)}
        </div>
        <ul className="fu-resumo">{resumoDaConfig(dados.config, dados.etapas).slice(1, 3).map((l) => <li key={l}>{l}</li>)}</ul>
        <div className="fu-numeros-mini">
          <span><b>{dados.proximos.length}</b> agendado{dados.proximos.length === 1 ? "" : "s"}</span>
          <span><b>{enviados}</b> enviado{enviados === 1 ? "" : "s"} recente{enviados === 1 ? "" : "s"}</span>
          <span><b>{naoEnviados}</b> não enviado{naoEnviados === 1 ? "" : "s"}</span>
        </div>
        {!ligado && <Alerta tipo="warn">Desligado: leads que param de responder não recebem lembrete.</Alerta>}
        <Link className="btn" to={link}><Settings2 />Montar cadência e ver agendados</Link>
        {!ligado && !dados.configurado && <span className="muted" style={{ fontSize: 12 }}><Power size={12} style={{ verticalAlign: -2 }} /> Ligar aqui usa a cadência padrão ({juntar(dados.padrao.cadencia.map(tempoLegivel))}).</span>}
      </div>
    </Painel>
  );
}
