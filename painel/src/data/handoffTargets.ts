// Alvos de handoff do prompt (menu "@" do editor de agente).
//
// MODELO: no EDITOR mostramos um rótulo amigável ("@Agente Closer"); no ENVIO AO BOT
// (criação do agente) o token é expandido para a instrução real ("acionar tool `closer`").
// Assim o cliente vê algo simples e o bot recebe o comando completo. O editor e o
// rascunho SEMPRE mantêm o token amigável — a expansão acontece só no payload.
//
// As FRASES DE TROCA ("@Transferência: Closer", data/frasesTroca) seguem o mesmo modelo e
// são expandidas/recolhidas junto, nas mesmas funções.

import { expandirFrasesParaBot, recolherFrasesDoBot } from "./frasesTroca";

export interface HandoffTarget {
  /** Rótulo amigável exibido no editor (vira "@<label>"). */
  label: string;
  /** Nome EXATO da tool no bot/n8n (o que entra em "acionar tool `<tool>`"). */
  tool: string;
}

// Nomes curtos no menu "@" ("@Closer"). Os antigos ("@Agente Closer") continuam valendo (LEGACY_TARGETS)
// e viram o nome curto sozinhos quando o prompt é aberto no editor (normalizarRotulosAntigos).
export const HANDOFF_TARGETS: HandoffTarget[] = [
  { label: "SDR", tool: "sdr" },
  { label: "Comercial", tool: "closer" },
  { label: "Coleta de Dados", tool: "coletadedados" },
  { label: "Assinatura", tool: "assinatura" },
  { label: "Desqualificado", tool: "desqualificado" },
  { label: "Período de Graça", tool: "periododegraca" },
];

/** Rótulos para o menu "@" (handoffOptions do RichPromptEditor). */
export const HANDOFF_LABELS = HANDOFF_TARGETS.map((t) => t.label);

/**
 * FERRAMENTAS (seção "Ferramenta" do menu "@"): ações que o agente pode acionar
 * — mesmo modelo dos handoffs (rótulo amigável no editor, "acionar tool `x`" só no
 * envio ao bot). Disponíveis para todos os papéis.
 */
export const TOOL_TARGETS: HandoffTarget[] = [
  { label: "Buscar CEP", tool: "buscarcep" },
  { label: "ZapSign", tool: "zapsign" },
];

/**
 * Aliases LEGADOS: rótulos/tools antigos que precisam continuar funcionando (migração).
 * NÃO aparecem no menu "@" — só garantem que texto/prompt antigo (catálogo, rascunho ou
 * prompt já gravado no bot) seja reconhecido e migre para o nome novo no próximo save.
 * Ex.: a tool "criardocumento" virou "zapsign" (rótulo "Desenvolver Documento" → "ZapSign").
 */
const LEGACY_TARGETS: HandoffTarget[] = [
  { label: "Desenvolver Documento", tool: "zapsign" }, // rótulo antigo → tool nova
  // Nomes compridos antigos do menu "@" (antes de virarem "@SDR", "@Closer"...).
  { label: "Agente SDR", tool: "sdr" },
  { label: "Agente Closer", tool: "closer" },
  { label: "Closer", tool: "closer" },
  { label: "Agente Coleta de Dados", tool: "coletadedados" },
  { label: "Agente Acompanhamento Assinatura", tool: "assinatura" },
  { label: "Agente Desqualificado", tool: "desqualificado" },
  { label: "Agente Período de Graça", tool: "periododegraca" },
];
/** Rótulos legados (só p/ realçar texto antigo no editor — fora do menu "@"). */
export const LEGACY_TOOL_LABELS = LEGACY_TARGETS.map((t) => t.label);
/** tool antiga (no bot / prompt gravado) → tool canônica atual. */
const LEGACY_TOOL_ALIASES: Record<string, string> = {
  criardocumento: "zapsign",
};

/** Rótulos para a seção "Ferramenta" do menu "@" (toolOptions do RichPromptEditor). */
export const TOOL_LABELS = TOOL_TARGETS.map((t) => t.label);

/** Rótulo de handoff correspondente a cada papel editável (p/ não oferecer @ pra si mesmo). */
export const ROLE_HANDOFF_LABEL: Record<string, string> = {
  sdr: "SDR",
  periododegraca: "Período de Graça",
  closer: "Comercial",
  contratos: "Coleta de Dados",
  assinatura: "Assinatura",
  desqualificado: "Desqualificado",
};

/** "@Agente Closer" (nome antigo) → "@Closer". Roda quando o prompt é aberto: corrige o texto sozinho. */
export const normalizarRotulosAntigos = (texto: string): string => {
  if (!texto) return texto;
  let out = texto;
  const antigos = LEGACY_TARGETS.filter((t) => t.label.startsWith("Agente ") || t.label === "Closer").sort((a, b) => b.label.length - a.label.length);
  for (const t of antigos) {
    const novo = HANDOFF_TARGETS.find((h) => h.tool === t.tool)?.label;
    if (novo) out = out.replace(new RegExp("@" + escapeRe(t.label) + "(?![A-Za-zÀ-ÿ0-9])", "g"), "@" + novo);
  }
  return out;
};

/** Rótulos do menu "@" para um papel — todos menos o próprio. */
export const handoffLabelsFor = (role: string): string[] =>
  HANDOFF_LABELS.filter((l) => l !== ROLE_HANDOFF_LABEL[role]);

const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/**
 * Expande os tokens amigáveis "@Agente X" para "acionar tool `x`" — usado SÓ no
 * texto enviado ao bot (criação do agente). Faz match dos rótulos mais longos
 * primeiro para não cortar nomes que são prefixo de outro.
 */
export const expandirHandoffsParaBot = (texto: string): string => {
  if (!texto) return texto;
  // Frases de troca primeiro ("@Transferência: X" → texto exato), depois os handoffs/tools.
  let out = expandirFrasesParaBot(texto);
  // Handoffs + ferramentas (+ rótulos legados): todos viram "acionar tool `x`". Rótulos
  // mais longos primeiro p/ não cortar nomes que são prefixo de outro. Incluir os legados
  // garante que "@Desenvolver Documento" antigo também expanda para a tool nova (zapsign).
  const ordenado = [...HANDOFF_TARGETS, ...TOOL_TARGETS, ...LEGACY_TARGETS].sort((a, b) => b.label.length - a.label.length);
  for (const t of ordenado) {
    const re = new RegExp("@" + escapeRe(t.label), "g");
    out = out.replace(re, "acionar tool `" + t.tool + "`");
  }
  return out;
};

/**
 * Versão para os prompt_blocks enviados ao bot: copia os blocos expandindo o texto
 * (content string) de "@Agente X" → "acionar tool `x`". NÃO muta o original (o
 * editor/rascunho continuam com o token amigável).
 */
export const expandirBlocosParaBot = (blocks: any): any => {
  if (!Array.isArray(blocks)) return blocks;
  return blocks.map((b) =>
    b && typeof b.content === "string" ? { ...b, content: expandirHandoffsParaBot(b.content) } : b,
  );
};

/** tool → alvo (handoff ou ferramenta), para o caminho reverso. */
const ALVO_POR_TOOL = new Map<string, HandoffTarget>(
  [...HANDOFF_TARGETS, ...TOOL_TARGETS].map((t) => [t.tool, t]),
);

/**
 * REVERSO de expandirHandoffsParaBot: "acionar tool `x`" → "@Agente X". Usado na CARGA
 * do modo edição — o prompt vem do bot já expandido, mas o editor (front) deve mostrar o
 * rótulo amigável, igual à criação. Tool desconhecida fica como está (não quebra o texto).
 */
export const recolherHandoffsDoBot = (texto: string): string => {
  if (!texto) return texto;
  const handoffs = texto.replace(/acionar\s+tool\s*`?\s*([a-z0-9_-]+)\s*`?/gi, (full, tool) => {
    const t = String(tool).toLowerCase();
    const canon = LEGACY_TOOL_ALIASES[t] ?? t;   // criardocumento → zapsign
    const alvo = ALVO_POR_TOOL.get(canon);
    return alvo ? "@" + alvo.label : full;
  });
  // Texto exato de uma frase de troca → "@Transferência: X" (chip laranja no editor).
  return normalizarRotulosAntigos(recolherFrasesDoBot(handoffs));
};

// ============================================================================
// INTERPRETAÇÃO (Teste de prompt): reconhecer @ e "acionar tool `x`" na RESPOSTA do
// agente, classificar como handoff (→ papel do funil) ou ferramenta de ação, e limpar
// o sinal do texto exibido. Igual ao que o bot faz, mas pra mostrar no teste.
// ============================================================================

/** Tool de handoff → papel do funil (closer→closer, coletadedados→contratos, etc.). */
export const ROLE_BY_HANDOFF_TOOL: Record<string, string> = {
  sdr: "sdr",
  periododegraca: "periododegraca",
  closer: "closer",
  coletadedados: "contratos",
  assinatura: "assinatura",
  desqualificado: "desqualificado",
};

const TODOS = [...HANDOFF_TARGETS, ...TOOL_TARGETS, ...LEGACY_TARGETS].sort((a, b) => b.label.length - a.label.length);
// "acionar tool `x`" (com ou sem crases/espaços) e os @Label amigáveis.
const ACIONAR_RE = /acionar\s+tool\s*`?\s*([a-z0-9_-]+)\s*`?/i;

/** Detecta o 1º sinal de ação na resposta do agente e classifica. */
export function detectarAcaoNoTexto(texto: string):
  | { kind: "handoff"; role: string; tool: string }
  | { kind: "tool"; tool: string; label: string }
  | null {
  if (!texto) return null;
  let tool: string | null = null;
  const m = texto.match(ACIONAR_RE);
  if (m) tool = m[1].toLowerCase();
  if (!tool) {
    for (const t of TODOS) {
      if (new RegExp("@" + escapeRe(t.label), "i").test(texto)) { tool = t.tool; break; }
    }
  }
  if (!tool) return null;
  tool = LEGACY_TOOL_ALIASES[tool] ?? tool;   // criardocumento → zapsign
  if (ROLE_BY_HANDOFF_TOOL[tool]) return { kind: "handoff", role: ROLE_BY_HANDOFF_TOOL[tool], tool };
  const acao = TOOL_TARGETS.find((t) => t.tool === tool);
  if (acao) return { kind: "tool", tool, label: acao.label };
  const hd = HANDOFF_TARGETS.find((t) => t.tool === tool);
  return hd ? { kind: "handoff", role: tool, tool } : null;
}

/** Remove os sinais (@Label e "acionar tool `x`") do texto exibido ao lead. */
export function limparAcoesDoTexto(texto: string): string {
  if (!texto) return texto;
  let out = texto.replace(/acionar\s+tool\s*`?\s*[a-z0-9_-]+\s*`?/gi, "");
  for (const t of TODOS) out = out.replace(new RegExp("@" + escapeRe(t.label), "gi"), "");
  return out.replace(/[ \t]{2,}/g, " ").replace(/\n{3,}/g, "\n\n").trim();
}
