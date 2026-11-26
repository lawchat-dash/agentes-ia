import type { CSSProperties, ReactNode } from "react";
import { BookOpen, Bot, FlaskConical, History, Rocket, Send, Wand2, Zap } from "lucide-react";
import type { Agente } from "../api";

export interface SecaoAgente {
  chave: string;                 // pedaço da rota: /agentes/:id/:chave
  rotulo: string;
  etiqueta: string;              // subtítulo colorido do cartão
  cor: string;                   // tom do ícone e da etiqueta
  cor2: string;                  // ponta clara do degradê do ícone
  icone: (tamanho?: number) => ReactNode;
  descricao: string;
  numeros: (a: Agente) => [string | number, string][];
  so_proprio?: boolean;
}

const ligados = (r: Record<string, boolean> | undefined) => Object.values(r ?? {}).filter(Boolean).length;

/** As partes de um agente: viram o submenu lateral e os cartões da página do agente. */
export const SECOES_AGENTE: SecaoAgente[] = [
  {
    chave: "ativacao", rotulo: "Ativação", etiqueta: "Comece aqui", cor: "#00BC33", cor2: "#2BD45A", icone: (t) => <Rocket size={t} />,
    descricao: "Número, comportamento, números de teste e a lista do que falta para ligar o agente.",
    numeros: (a) => [[a.situacao === "ativo" ? "Ativo" : "Pausado", "situação"], [a.modo === "producao" ? "Todos" : "Teste", "responde a"]],
  },
  {
    chave: "instrucoes", rotulo: "Instruções", etiqueta: "Prompt por etapa", cor: "#2563EB", cor2: "#60A5FA", icone: (t) => <Bot size={t} />,
    descricao: "O que a IA faz em cada etapa do atendimento. Vazio usa a instrução padrão.",
    numeros: (a) => [[a.etapas.length, "etapas"], [a.etapas.filter((e) => e.personalizada).length, "personalizadas"]],
  },
  {
    chave: "etapas", rotulo: "Etapas e regras", etiqueta: "Agente próprio", cor: "#0E9F6E", cor2: "#34D399", icone: (t) => <Wand2 size={t} />, so_proprio: true,
    descricao: "Os dados que a IA coleta, as etapas e as regras de passagem entre elas.",
    numeros: (a) => [[a.definicao?.campos.length ?? 0, "campos"], [a.definicao?.regras.length ?? 0, "regras"]],
  },
  {
    chave: "conhecimento", rotulo: "Conhecimento", etiqueta: "Referência", cor: "#0891B2", cor2: "#22D3EE", icone: (t) => <BookOpen size={t} />,
    descricao: "Perguntas frequentes, objeções e dados do escritório que a IA consulta para responder.",
    numeros: (a) => [[a.conhecimento?.faq.length ?? 0, "perguntas"], [a.conhecimento?.objecoes.length ?? 0, "objeções"], [a.documentos ?? 0, "documentos"]],
  },
  {
    chave: "funcoes", rotulo: "Funções e automações", etiqueta: "CRM, departamento, avisos", cor: "#D97706", cor2: "#FBBF24", icone: (t) => <Zap size={t} />,
    descricao: "Quando isto acontecer, faça aquilo: mover card, etiquetas, trocar de departamento, avisar, contrato.",
    numeros: (a) => [[ligados(a.funcoes), "funções ligadas"], [Object.keys(a.automacoes ?? {}).length, "automações"]],
  },
  {
    chave: "followup", rotulo: "Follow-up", etiqueta: "Cadência", cor: "#DB2777", cor2: "#F472B6", icone: (t) => <Send size={t} />,
    descricao: "O agente de follow-up retoma quem parou de responder, no ritmo da cadência e no horário comercial.",
    numeros: (a) => [[a.followup_resumo?.ativo ? "Ligado" : "Desligado", "follow-up"], [a.followup_resumo?.passos ?? 7, "tentativas"]],
  },
  {
    chave: "laboratorio", rotulo: "Laboratório", etiqueta: "Testar", cor: "#7C3AED", cor2: "#A78BFA", icone: (t) => <FlaskConical size={t} />,
    descricao: "Converse com o agente usando a configuração salva, sem mandar nada no WhatsApp.",
    numeros: () => [],
  },
  {
    chave: "historico", rotulo: "Histórico", etiqueta: "Quem mudou o quê", cor: "#64748B", cor2: "#94A3B8", icone: (t) => <History size={t} />,
    descricao: "Cada alteração neste agente, com quem fez e quando.",
    numeros: () => [],
  },
];

export const secoesDo = (proprio: boolean) => SECOES_AGENTE.filter((s) => !s.so_proprio || proprio);

/** Ícone da seção em degradê (claro → tom), branco por cima, com sombra na cor: o mesmo acabamento dos cartões do LawChat. */
export const estiloIconeSecao = (s: Pick<SecaoAgente, "cor" | "cor2">): CSSProperties => ({
  backgroundImage: `linear-gradient(135deg, ${s.cor2}, ${s.cor})`,
  color: "#fff",
  borderColor: "transparent",
  boxShadow: `0 8px 18px -10px ${s.cor}`,
});
