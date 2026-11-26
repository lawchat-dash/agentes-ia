/*
 * Tela Conversas: tipos que vêm da API (GET /api/conversas e /api/conversas/{id_lead},
 * em app/gestao/repositorio.py) e os rótulos e formatos usados pelos componentes.
 */
import { formatarTelefone } from "../../api";

export type EstadoLead = "ativo" | "pausado" | "encerrado";
/** Botões da IA (POST /api/conversas/{id}/ia). desativar leva `minutos` (0 = até alguém religar). */
export type AcaoIa = "desativar" | "reativar" | "encerrar";
/** Opções do botão "Desativar IA" (minutos; 0 = até eu religar). */
export const PRAZOS_DESATIVAR: { minutos: number; rotulo: string }[] = [
  { minutos: 30, rotulo: "Por 30 minutos" },
  { minutos: 120, rotulo: "Por 2 horas" },
  { minutos: 1440, rotulo: "Por 24 horas" },
  { minutos: 0, rotulo: "Até eu religar" },
];

/** Uma linha da lista (GET /api/conversas). */
export interface ResumoConversa {
  id: string;
  nome: string | null;
  telefone: string | null;
  estado: EstadoLead;
  motivo_estado: string | null;
  pausado_ate: string | null;
  etapa: string | null;
  id_agente: string | null;
  agente: string | null;
  ultima_mensagem_lead_em: string | null;
  ultima_resposta_ia_em: string | null;
  criado_em: string;
  /** Texto da última mensagem, ou o que foi lido da mídia (transcrição, descrição). */
  ultima_mensagem: string | null;
  /** Tipo da última mensagem (null quando a conversa não tem mensagem). */
  ultima_mensagem_tipo?: TipoMensagem | null;
  /** Situação do agente (produto) da conversa: "pausado" = nenhum lead daquele número recebe resposta. */
  situacao_agente?: string | null;
  /** IA desligada no escritório inteiro (Configurações) ou escritório suspenso. */
  ia_desligada_escritorio?: boolean | null;
}

export type AutorMensagem = "lead" | "ia" | "humano" | "automacao" | "sistema";
export type TipoMensagem = "texto" | "audio" | "imagem" | "video" | "documento" | "figurinha" | "localizacao" | "contato";

export interface Mensagem {
  id: string;
  autor: AutorMensagem;
  tipo: TipoMensagem;
  texto: string | null;
  texto_extraido: string | null;
  /** Endereço do arquivo (áudio, imagem, vídeo, documento), como chegou da Helena ou da pasta de mídia. */
  url_midia: string | null;
  enviada_em: string;
  situacao_envio: "recebida" | "pendente" | "enviada" | "falhou";
  erro: string | null;
  id_turno: string | null;
}

export interface Fato {
  chave: string;
  valor: unknown;
  trecho: string | null;
  fonte: "extrator" | "equipe" | "sistema";
  criado_em: string;
  substituido_em: string | null;
}

export interface Turno {
  id: string;
  modo: "producao" | "teste" | "laboratorio";
  etapa_antes: string | null;
  etapa_depois: string | null;
  situacao: "processando" | "respondido" | "silencio" | "descartado" | "erro";
  motivo: string | null;
  resposta: unknown;
  iniciado_em: string;
  concluido_em: string | null;
}

export interface EventoLead {
  tipo: string;
  gravidade: "info" | "aviso" | "erro" | "critico";
  responsavel: string | null;
  descricao: string | null;
  criado_em: string;
}

/** Ficha de memória: o resumo que a IA faz das mensagens antigas quando a conversa fica longa. */
export interface FichaMemoria {
  resumo: string;
  mensagens_resumidas: number;
  atualizado_em: string;
}

/** A conversa aberta (GET /api/conversas/{id_lead}): o lead inteiro e o que aconteceu nele. */
export interface DetalheConversa extends Omit<ResumoConversa, "ultima_mensagem" | "ultima_mensagem_tipo"> {
  origem: Record<string, unknown> | null;
  atualizado_em: string;
  mensagens: Mensagem[];
  fatos: Fato[];
  turnos: Turno[];
  eventos: EventoLead[];
  /** null enquanto a conversa não ficou longa o bastante para ganhar ficha. */
  memoria: FichaMemoria | null;
}

// --------------------------------------------------------------------------- rótulos
export const ESTADOS: Record<EstadoLead, { rotulo: string; plural: string; cor: string; fundo: string; chip: string }> = {
  ativo: { rotulo: "IA atendendo", plural: "Ativas", cor: "#16a34a", fundo: "#e8f9ee", chip: "ok" },
  pausado: { rotulo: "IA pausada", plural: "Pausadas", cor: "#d97706", fundo: "#fff4df", chip: "warn" },
  encerrado: { rotulo: "Encerrada", plural: "Encerradas", cor: "#64748b", fundo: "#eef2f7", chip: "" },
};

/** Desligada pela equipe (painel, etiqueta "🤖 IA Desativada" ou botão da Helena): app/ia_controle.py. */
export const MOTIVO_DESATIVADA = "desativada_pela_equipe";

/** O que a IA faz NESTA conversa agora, em português. `agora` entra para a desativação vencida voltar a "IA ligada". */
export function estadoDaIa(c: Pick<ResumoConversa, "estado" | "motivo_estado" | "pausado_ate" | "situacao_agente" | "ia_desligada_escritorio">,
  agora: number = Date.now()): { rotulo: string; cor: string; fundo: string; pausada: boolean; daEquipe: boolean } {
  const ate = c.pausado_ate ? new Date(c.pausado_ate) : null;
  const vencida = c.estado === "pausado" && ate != null && ate.getTime() <= agora;
  const verde = { cor: "#16a34a", fundo: "#e8f9ee" };
  const ambar = { cor: "#d97706", fundo: "#fff4df" };
  const cinza = { cor: "#64748b", fundo: "#eef2f7" };
  if (c.estado === "encerrado") return { rotulo: "Encerrada", ...cinza, pausada: false, daEquipe: false };
  if (c.ia_desligada_escritorio) return { rotulo: "IA desligada no escritório", ...cinza, pausada: false, daEquipe: false };
  if (c.situacao_agente && c.situacao_agente !== "ativo") return { rotulo: "Agente pausado", ...cinza, pausada: false, daEquipe: false };
  if (c.estado === "ativo" || vencida) return { rotulo: "IA ligada", ...verde, pausada: false, daEquipe: false };
  const daEquipe = c.motivo_estado === MOTIVO_DESATIVADA || c.motivo_estado === "pausado_pela_equipe";
  const hora = ate ? (rotuloDoDia(ate.toISOString()) === "Hoje" ? horaCurta(ate) : `${ate.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" })} ${horaCurta(ate)}`) : "";
  if (daEquipe) return { rotulo: ate ? `IA desligada até ${hora}` : "IA desligada pela equipe", ...ambar, pausada: true, daEquipe: true };
  if (c.motivo_estado === "humano_assumiu") {
    return { rotulo: `Pausada porque o atendente assumiu${ate ? ` (volta ${hora})` : ""}`, ...ambar, pausada: true, daEquipe: false };
  }
  return { rotulo: "IA pausada", ...ambar, pausada: true, daEquipe: false };
}

function horaCurta(d: Date): string {
  return d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

const MOTIVOS: Record<string, string> = {
  desativada_pela_equipe: "Desligada pela equipe (painel, etiqueta ou botão da Helena)",
  humano_assumiu: "A equipe assumiu o atendimento",
  pausado_pela_equipe: "Pausada pela equipe no painel",
  devolvido_pela_equipe: "Devolvida para a IA pela equipe",
  encerrado_pela_equipe: "Encerrada pela equipe no painel",
  desqualificado: "Fora do perfil",
  pediu_parar: "O lead pediu para parar",
  contrato_assinado: "Contrato assinado",
  trava_persistente: "A IA travou várias vezes seguidas",
  sem_resposta_followup: "Sem resposta aos follow-ups",
};

/** Motivo do estado em português ("analise_manual:x" vira "Análise da equipe: x"). */
export function motivoLegivel(motivo: string | null | undefined): string | null {
  if (!motivo) return null;
  if (MOTIVOS[motivo]) return MOTIVOS[motivo];
  const [prefixo, ...resto] = motivo.split(":");
  const detalhe = resto.join(":").replace(/_/g, " ").trim();
  if (prefixo === "analise_manual") return `Análise da equipe${detalhe ? `: ${detalhe}` : ""}`;
  if (prefixo === "sinal") return `Sinal para a equipe${detalhe ? `: ${detalhe}` : ""}`;
  return motivo.replace(/[_:]/g, " ");
}

const NOMES_ETAPAS: Record<string, string> = {
  sdr: "Primeiro atendimento", periodo_graca: "Período de graça", closer: "Proposta e honorários",
  coleta_dados: "Dados do contrato", analise_manual: "Análise da equipe", desqualificado: "Encerramento",
  contrato_enviado: "Contrato enviado", contratoassinado: "Contrato assinado", contrato_assinado: "Contrato assinado",
};

export function nomeEtapa(codigo: string | null | undefined): string {
  if (!codigo) return "—";
  return NOMES_ETAPAS[codigo] ?? codigo.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

export const TIPOS_MIDIA: Record<Exclude<TipoMensagem, "texto">, { rotulo: string; extraido: string }> = {
  audio: { rotulo: "Áudio", extraido: "Transcrição" },
  imagem: { rotulo: "Imagem", extraido: "O que a IA viu na imagem" },
  video: { rotulo: "Vídeo", extraido: "O que a IA viu no vídeo" },
  documento: { rotulo: "Documento", extraido: "Texto lido do documento" },
  figurinha: { rotulo: "Figurinha", extraido: "Descrição" },
  localizacao: { rotulo: "Localização", extraido: "Endereço" },
  contato: { rotulo: "Contato compartilhado", extraido: "Dados do contato" },
};

// --------------------------------------------------------------------------- mídia
/** Como a mídia aparece no balão: player de áudio, player de vídeo, miniatura ou link para o arquivo. */
export type FormaMidia = "audio" | "video" | "imagem" | "documento";

const EXTENSOES: [RegExp, FormaMidia][] = [
  [/\.(jpe?g|png|gif|webp|bmp|heic|avif)$/, "imagem"],
  [/\.(mp3|ogg|oga|opus|m4a|aac|wav|amr|weba)$/, "audio"],
  [/\.(mp4|webm|mov|m4v|3gp)$/, "video"],
  [/\.(pdf|docx?|xlsx?|pptx?|odt|ods|txt|csv|rtf|zip)$/, "documento"],
];

/** Só endereços que o navegador abre com segurança: http(s) ou caminho do próprio painel ("/midia/..."). */
export function urlSegura(url: string | null | undefined): string | null {
  const u = (url ?? "").trim();
  if (/^https?:\/\//i.test(u)) return u;
  if (u.startsWith("/") && !u.startsWith("//")) return u;
  return null;
}

/** A forma de mostrar a mídia. A extensão do arquivo manda quando existe: a mídia que a IA envia
 *  fica gravada como "video" mesmo quando é uma imagem ou um PDF (app/pipeline.py). */
export function formaDaMidia(tipo: TipoMensagem, url: string): FormaMidia | null {
  const caminho = url.split(/[?#]/)[0].toLowerCase();
  const pelaExtensao = EXTENSOES.find(([re]) => re.test(caminho))?.[1];
  if (pelaExtensao) return pelaExtensao;
  if (tipo === "audio" || tipo === "video" || tipo === "imagem" || tipo === "documento") return tipo;
  if (tipo === "figurinha") return "imagem";
  return null;
}

/** Nome do arquivo tirado do endereço ("laudo%20medico.pdf" vira "laudo medico.pdf"). */
export function nomeDoArquivo(url: string): string {
  const ultimo = url.split(/[?#]/)[0].split("/").filter(Boolean).pop() ?? "";
  try { return decodeURIComponent(ultimo) || "Arquivo"; } catch { return ultimo || "Arquivo"; }
}

export const AUTORES: Record<AutorMensagem, string> = {
  lead: "Lead", ia: "IA", humano: "Atendente", automacao: "Automação", sistema: "Sistema",
};

export const SITUACOES_TURNO: Record<Turno["situacao"], { rotulo: string; chip: string }> = {
  respondido: { rotulo: "respondeu", chip: "ok" },
  silencio: { rotulo: "ficou em silêncio", chip: "" },
  descartado: { rotulo: "descartado", chip: "" },
  erro: { rotulo: "erro", chip: "bad" },
  processando: { rotulo: "processando", chip: "info" },
};

export const MODOS_TURNO: Record<Turno["modo"], string> = { producao: "atendimento real", teste: "número de teste", laboratorio: "laboratório" };

export const RESPONSAVEIS: Record<string, string> = {
  cliente: "Escritório", cadastro: "Cadastro", provedor: "Provedor", lead: "Lead", lawchat: "LawChat",
};

export const FONTES_FATO: Record<Fato["fonte"], string> = { extrator: "lido pela IA", equipe: "pela equipe", sistema: "sistema" };

export const ROTULOS_ORIGEM: [string, string][] = [
  ["campanha", "Campanha"], ["titulo", "Anúncio"], ["conteudo", "Conteúdo"], ["fonte", "Fonte"],
  ["meio", "Meio"], ["termo", "Termo"], ["url", "Link"],
];

// --------------------------------------------------------------------------- formatos
/** Nome para mostrar: o nome do contato, senão o telefone, senão "Contato sem nome". */
export function nomeDoLead(c: { nome: string | null; telefone: string | null }): string {
  return c.nome?.trim() || formatarTelefone(c.telefone) || "Contato sem nome";
}

export function iniciais(nome: string): string {
  const partes = nome.replace(/[^\p{L}\p{N}\s]/gu, "").trim().split(/\s+/).filter(Boolean);
  if (partes.length === 0) return "?";
  return ((partes[0][0] ?? "") + (partes.length > 1 ? partes[partes.length - 1][0] : "")).toUpperCase();
}

const CORES_AVATAR = ["#00BC33", "#0EA5E9", "#8B5CF6", "#F59E0B", "#EF4444", "#14B8A6", "#EC4899", "#2563EB"];
/** Cor estável por lead (a mesma em todas as visitas). */
export function corDoAvatar(semente: string): string {
  let h = 0;
  for (let i = 0; i < semente.length; i++) h = (h * 31 + semente.charCodeAt(i)) >>> 0;
  return CORES_AVATAR[h % CORES_AVATAR.length];
}

export function hora(data: string): string {
  return new Date(data).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

/** "Hoje", "Ontem" ou "12 de março" (com o ano quando não é o atual). */
export function rotuloDoDia(data: string): string {
  const d = new Date(data);
  const hoje = new Date();
  const ontem = new Date(); ontem.setDate(hoje.getDate() - 1);
  if (d.toDateString() === hoje.toDateString()) return "Hoje";
  if (d.toDateString() === ontem.toDateString()) return "Ontem";
  return d.toLocaleDateString("pt-BR", { day: "numeric", month: "long", ...(d.getFullYear() !== hoje.getFullYear() ? { year: "numeric" } : {}) });
}

/** Momento curto para a lista: hora se for hoje, "Ontem", ou a data. */
export function momentoCurto(data: string | null | undefined): string {
  if (!data) return "";
  const d = new Date(data);
  const dia = rotuloDoDia(data);
  if (dia === "Hoje") return hora(data);
  if (dia === "Ontem") return "Ontem";
  return d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit", ...(d.getFullYear() !== new Date().getFullYear() ? { year: "2-digit" } : {}) });
}

export function dataHora(data: string | null | undefined): string {
  if (!data) return "—";
  return new Date(data).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** Duração de um turno ("2,4 s", "1 min 5 s"). */
export function duracao(inicio: string, fim: string | null): string | null {
  if (!fim) return null;
  const ms = new Date(fim).getTime() - new Date(inicio).getTime();
  if (!Number.isFinite(ms) || ms < 0) return null;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1).replace(".", ",")} s`;
  return `${Math.floor(ms / 60_000)} min ${Math.round((ms % 60_000) / 1000)} s`;
}

/** Valor de um fato para leitura (true vira "Sim", listas viram texto). */
export function valorLegivel(valor: unknown): string {
  if (valor === true) return "Sim";
  if (valor === false) return "Não";
  if (valor == null || valor === "") return "—";
  if (Array.isArray(valor)) return valor.map(valorLegivel).join(", ");
  if (typeof valor === "object") return JSON.stringify(valor);
  return String(valor);
}

export function chaveLegivel(chave: string): string {
  return chave.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

/** Prévia de uma linha da lista: texto da última mensagem, já sem quebras. */
export function previa(texto: string | null | undefined): string {
  return (texto ?? "").replace(/\s+/g, " ").trim();
}

/** Prévia da lista: o texto da última mensagem; sem texto (áudio, figurinha), o tipo dela ("Áudio").
 *  Vazio só quando a conversa não tem mensagem nenhuma. */
export function previaDaConversa(c: Pick<ResumoConversa, "ultima_mensagem" | "ultima_mensagem_tipo">): string {
  const texto = previa(c.ultima_mensagem);
  if (texto) return texto;
  const tipo = c.ultima_mensagem_tipo;
  if (!tipo) return "";
  return tipo === "texto" ? "Mensagem" : (TIPOS_MIDIA[tipo]?.rotulo ?? "Mensagem");
}

export const ID_VALIDO = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;

/** Mensagens agrupadas por dia, na ordem do WhatsApp. */
export function porDia(mensagens: Mensagem[]): { dia: string; mensagens: Mensagem[] }[] {
  const grupos: { dia: string; mensagens: Mensagem[] }[] = [];
  for (const m of mensagens) {
    const dia = rotuloDoDia(m.enviada_em);
    const ultimo = grupos[grupos.length - 1];
    if (ultimo && ultimo.dia === dia) ultimo.mensagens.push(m);
    else grupos.push({ dia, mensagens: [m] });
  }
  return grupos;
}
