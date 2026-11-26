// Cliente da API do painel. Todas as chamadas passam pelo servidor Python (/api).

export class ErroApi extends Error {
  constructor(public status: number, mensagem: string) {
    super(mensagem);
  }
}

const CHAVE_ESCRITORIO = "agentesia_escritorio";

/** Escritório escolhido pela equipe LawChat (admin). Gestor e atendente ignoram. */
export function escritorioEscolhido(): string | null {
  try {
    return localStorage.getItem(CHAVE_ESCRITORIO);
  } catch {
    return null;
  }
}

export function escolherEscritorio(id: string | null): void {
  try {
    if (id) localStorage.setItem(CHAVE_ESCRITORIO, id);
    else localStorage.removeItem(CHAVE_ESCRITORIO);
  } catch {
    /* navegador sem armazenamento: o admin escolhe de novo */
  }
}

const CHAVE_VISAO = "agentesia_visao";
export type Visao = "lawchat" | "gestor" | "atendente";

/** Como a equipe LawChat está olhando o escritório: como LawChat ou como o cliente (gestor/atendente). */
export function visaoEscolhida(): Visao {
  try {
    const v = sessionStorage.getItem(CHAVE_VISAO);
    return v === "gestor" || v === "atendente" ? v : "lawchat";
  } catch {
    return "lawchat";
  }
}

export function escolherVisao(v: Visao): void {
  try {
    if (v === "lawchat") sessionStorage.removeItem(CHAVE_VISAO);
    else sessionStorage.setItem(CHAVE_VISAO, v);
  } catch {
    /* sem armazenamento: volta para a visão LawChat ao recarregar */
  }
}

export async function api<T = any>(caminho: string, opcoes: { metodo?: string; corpo?: unknown } = {}): Promise<T> {
  const cabecalhos: Record<string, string> = { Accept: "application/json" };
  if (opcoes.corpo !== undefined) cabecalhos["Content-Type"] = "application/json";
  const escritorio = escritorioEscolhido();
  if (escritorio) cabecalhos["X-Escritorio"] = escritorio;
  const visao = visaoEscolhida();
  // A visão do cliente vale para as telas do escritório; as rotas da LawChat (/admin) seguem como LawChat.
  if (escritorio && visao !== "lawchat" && !caminho.startsWith("/admin")) cabecalhos["X-Visao"] = visao;
  const resposta = await fetch(`/api${caminho}`, {
    method: opcoes.metodo ?? (opcoes.corpo !== undefined ? "POST" : "GET"),
    headers: cabecalhos,
    credentials: "same-origin",
    body: opcoes.corpo !== undefined ? JSON.stringify(opcoes.corpo) : undefined,
  });
  if (resposta.status === 401 && !caminho.startsWith("/entrar")) {
    window.dispatchEvent(new Event("agentesia:sair"));
  }
  const texto = await resposta.text();
  const dados = texto ? (() => { try { return JSON.parse(texto); } catch { return texto; } })() : null;
  if (!resposta.ok) {
    const detalhe = dados && typeof dados === "object" ? (dados as any).detail : null;
    const mensagem = typeof detalhe === "string" ? detalhe
      : Array.isArray(detalhe) ? "Algum campo está inválido: " + detalhe.map((d: any) => d.loc?.slice(-1)[0]).join(", ")
      : `Erro ${resposta.status}`;
    throw new ErroApi(resposta.status, mensagem);
  }
  return dados as T;
}

export const enviar = <T = any>(caminho: string, corpo: unknown, metodo = "POST") => api<T>(caminho, { metodo, corpo });

// --------------------------------------------------------------------------- tipos
export type Papel = "dono_lawchat" | "admin_lawchat" | "gestor" | "atendente";
export const PAPEIS_LAWCHAT: Papel[] = ["dono_lawchat", "admin_lawchat"];
export const NOME_PAPEL: Record<Papel, string> = {
  dono_lawchat: "Dono · LawChat", admin_lawchat: "Equipe LawChat", gestor: "Gestor", atendente: "Atendente",
};

export interface Eu {
  id: string; nome: string; email: string; papel: Papel;
  id_escritorio: string | null; nome_escritorio: string | null; trocar_senha: boolean; visao?: string | null;
  /** Equipe LawChat: o escritório da própria conta LawChat (a "conta" dela). */
  escritorio_lawchat?: string | null;
}

export interface Etapa {
  id: string; codigo: string; nome: string; ordem: number; tipo: "conversa" | "terminal"; principal: boolean;
  instrucao: string | null; instrucao_padrao: string; instrucao_travada: boolean; personalizada: boolean;
}

export interface Regra {
  coluna_crm?: string; adicionar_etiquetas?: string[]; remover_etiquetas?: string[]; transferir?: boolean; id_equipe?: string; nota?: string;
}

export interface Agente {
  documentos?: number;
  id: string; nome: string; produto: string; tipo_produto: "pronto" | "proprio";
  situacao: "ativo" | "pausado"; modo: "teste" | "producao"; modelo: string; honorarios: string;
  minutos_pausa_humano: number; numeros_teste: string[]; numero_canal: string; tipo_canal: string; id_canal: string;
  funcoes: Record<string, boolean>; id_equipe_transferencia: string | null; automacoes: Record<string, Regra>;
  gatilhos: Record<string, string>; definicao: Definicao | null; etapas: Etapa[]; criado_em: string;
  ultima_preparacao?: Preparacao | null; preparacao?: Preparacao;
  espera_s?: number | null; pausa_sem_volta?: boolean; followup_resumo?: { ativo: boolean; passos: number };
  conhecimento?: { faq: ItemBase[]; objecoes: ItemBase[]; dados_escritorio: string; teto_documentos?: number };
}

/** Item da FAQ ({pergunta, resposta}) ou objeção ({objecao, resposta}); `papeis` vazio = todos os papéis. */
export interface ItemBase { pergunta?: string; objecao?: string; resposta: string; papeis?: string[] }

export interface PassoAtivacao { codigo: string; titulo: string; situacao: "ok" | "feito" | "aviso" | "erro" | "pulado" | "pendente"; detalhe: string; }
export interface Preparacao { pronto: boolean; passos: PassoAtivacao[]; conferido_em: string; por?: string; }

export interface CampoDef {
  chave: string; nome: string; tipo: "texto" | "sim_nao" | "escolha" | "numero" | "data";
  opcoes: string[]; minimo?: number | null; maximo?: number | null; descricao: string; etapa: string | null;
}
export interface EtapaDef { codigo: string; nome: string; tipo: "conversa" | "terminal"; instrucao: string; pede_dados_pessoais?: boolean; fala_valores?: boolean; }
export interface CondicaoDef { tipo: "campo" | "etapa_completa" | "intencao"; campo?: string | null; operador?: string | null; valor?: string | number | null; intencao?: string | null; }
export interface RegraDef { de: string | null; quando: CondicaoDef; ir_para: string; motivo: string; }
export interface Definicao {
  objetivo: string; contexto: string; campos: CampoDef[]; intencoes: { chave: string; descricao: string }[];
  etapas: EtapaDef[]; regras: RegraDef[]; nunca: string[]; expressoes_proibidas: string[];
}

export interface Canal {
  id: string; id_canal_helena: string; numero_normalizado: string; tipo: string; ativo: boolean;
  id_agente: string | null; nome_agente: string | null;
}

export interface Catalogo {
  modelos: { id: string; nome: string; provedor: string; padrao?: boolean }[];
  produtos: { id: string; nome: string; tipo: string; descricao: string }[];
  funcoes: { id: string; nome: string; descricao: string; requer: string | null; pronta: boolean }[];
}

export function formatarTelefone(numero: string | null | undefined): string {
  const d = (numero ?? "").replace(/\D/g, "");
  if (d.length === 13) return `+${d.slice(0, 2)} (${d.slice(2, 4)}) ${d.slice(4, 9)}-${d.slice(9)}`;
  if (d.length === 12) return `+${d.slice(0, 2)} (${d.slice(2, 4)}) ${d.slice(4, 8)}-${d.slice(8)}`;
  return numero ?? "";
}

export function quando(data: string | null | undefined): string {
  if (!data) return "—";
  const d = new Date(data);
  const hoje = new Date();
  const mesmoDia = d.toDateString() === hoje.toDateString();
  return mesmoDia ? d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}
