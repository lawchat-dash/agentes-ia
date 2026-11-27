import { forwardRef, useImperativeHandle, useState, useCallback, useRef, useLayoutEffect, useEffect } from "react";
import { createPortal } from "react-dom";
import { useEditor, EditorContent } from "@tiptap/react";
import { Extension } from "@tiptap/core";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import StarterKit from "@tiptap/starter-kit";
import Paragraph from "@tiptap/extension-paragraph";
import { Markdown } from "tiptap-markdown";
import CharacterCount from "@tiptap/extension-character-count";
import Image from "@tiptap/extension-image";
import { Table, TableRow, TableHeader, TableCell } from "@tiptap/extension-table";
import { TaskList, TaskItem } from "@tiptap/extension-list";
import { Bold, Italic, Code, Heading1, Heading2, Heading3, Quote, List, ListOrdered, AtSign, ChevronDown, ChevronRight, ArrowLeft, Music, Image as ImageIcon, Video, Lock, Upload, Users, Wrench, Library, Trash2, ArrowRightLeft, Settings2, Braces } from "lucide-react";
import { useFrasesTroca } from "@/hooks/useFrasesTroca";
import { HANDOFF_LABELS, TOOL_LABELS, LEGACY_TOOL_LABELS } from "@/data/handoffTargets";
import { MarcarFraseTroca } from "./MarcarFraseTroca";
import { rotuloFrase, COR_TRANSFERENCIA, FraseTroca, PREFIXO_TRANSFERENCIA } from "@/data/frasesTroca";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { nomeDaPasta, rotuloDaPasta } from "@/lib/pastasMidia";

// Limite SUAVE (recomendado) — só p/ o contador/barra. NÃO bloqueia mais a digitação/colagem
// (o CharacterCount entra sem `limit`), então prompts grandes podem ser colados sem truncar.
const MAX_PADRAO = 100000;

/* ----------------------------------------------------------------------------
 * Preserva LINHAS EM BRANCO no round-trip markdown. O markdown-it (parser) colapsa
 * QUALQUER sequência de linhas vazias ao recarregar, então os parágrafos vazios que o
 * usuário cria com Enter (p/ dar espaçamento) "voltam tudo junto" ao salvar+reabrir.
 * Solução: serializar o parágrafo vazio como nbsp (U+00A0) — o markdown-it o mantém como
 * parágrafo (cada linha em branco vira 1 parágrafo nbsp), e o nbsp é whitespace invisível,
 * inofensivo p/ o bot. Só afeta parágrafos REALMENTE vazios; os com conteúdo seguem normais.
 * -------------------------------------------------------------------------- */
const ParagraphKeepBlank = Paragraph.extend({
  addStorage() {
    return {
      markdown: {
        serialize(state: any, node: any) {
          if (node.content.size === 0) state.write(String.fromCharCode(0xA0)); // nbsp: linha em branco preservada no markdown
          else state.renderInline(node);
          state.closeBlock(node);
        },
      },
    };
  },
});

/* ----------------------------------------------------------------------------
 * Realce ao vivo dos tokens: {{ campo }} (roxo) e @agente (azul). Usa decorations
 * do ProseMirror — NÃO altera o texto, então o markdown serializado p/ o bot
 * continua literal ("@Closer", "{{teste}}"). Só pinta.
 * -------------------------------------------------------------------------- */
const FIELD_RE = /\{\{[^}]*\}\}/g;
// Marcador de MÍDIA [[midia|audio|video:nome]] (ciano). O markdown escapa colchetes ([→\[) ao
// salvar, mas o des-escape no onUpdate devolve a forma limpa; no editor o texto já é literal.
const AUDIO_RE = /\[\[(?:[aá]udio|v[ií]deo|m[ií]dia|media|imagem):[^\]]*\]\]/g;
const MENTION_RE = /(^|[^A-Za-z0-9_À-ÿ])(@[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9_]*)/g;
const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/* URL de mídia da Biblioteca (agent-media). O TEXTO no prompt é a URL pura (o que o
 * bot recebe); o editor só a pinta como chip @nome via decoração. */
// Pastas: agent-media (antiga), midia (servidor local: /midia/<escritório>/audio/...) e o bucket do Supabase
// (agentesia-midia/<escritório>/audio/...).
const MEDIA_URL_RE = /(https?:\/\/[^\s)]*?\/(?:agent-media|[\w.-]*midia)\/[^\s)/]+\/(audio|video|imagem|image)\/([^\s)]+))/g;
const tipoUiDaUrl = (t: string): "audio" | "video" | "image" => (t === "imagem" ? "image" : (t as any));
const nomeDaUrl = (file: string): string => {
  let f = file;
  try { f = decodeURIComponent(file); } catch { /* mantém */ }
  // Arquivo da biblioteca: "<32 hex>-03-como-funciona-o-auxilio-acidente.m4a" (o código único da conta vem na frente).
  // O chip mostra só "03 - como funciona o auxilio acidente": o nome da parte do roteiro, para achar rápido no prompt.
  const semCodigo = f.replace(/^[0-9a-f]{32}-/i, "").replace(/^\d{10,}-/, "");
  const roteiro = /^(\d{2})-(.+)\.[a-z0-9]{2,4}$/i.exec(semCodigo);
  return roteiro ? `${roteiro[1]} - ${roteiro[2].replace(/-/g, " ")}` : semCodigo;
};

/** Acha a URL de mídia COLADA no cursor (antes/depois) p/ apagar o chip inteiro de uma vez —
 *  senão o Backspace revela e apaga a URL crua caractere a caractere. */
function chipMidiaAdjacente(state: any, dir: "before" | "after"): { from: number; to: number } | null {
  const $f = state.selection.$from;
  const parent = $f.parent;
  if (!parent?.isTextblock) return null;
  const off = $f.parentOffset;
  const base = $f.start();
  if (dir === "before") {
    const before = parent.textBetween(0, off, "\n", "\n");
    const m = new RegExp("(?:" + MEDIA_URL_RE.source + ")$").exec(before);
    return m ? { from: base + off - m[0].length, to: base + off } : null;
  }
  const after = parent.textBetween(off, parent.content.size, "\n", "\n");
  const m = new RegExp("^(?:" + MEDIA_URL_RE.source + ")").exec(after);
  return m ? { from: base + off, to: base + off + m[0].length } : null;
}

function buildTokenDecorations(doc: any, highlights: string[] = [], handoffLabels: string[] = [], toolLabels: string[] = [], mediaNames: Record<string, string> = {}, transferMap: Record<string, string> = {}, rawMap: Record<string, string> = {}): DecorationSet {
  const decos: Decoration[] = [];
  // Valores já preenchidos na Edição rápida — realça em VERDE p/ identificar (vs {{ }} roxo pendente).
  const vals = highlights.filter((s) => s && s.trim().length >= 2);
  const fillRe = vals.length
    ? new RegExp(vals.map(escapeRe).sort((a, b) => b.length - a.length).join("|"), "g")
    : null;
  // Handoff multi-palavra ("@Agente Closer"): realça o token INTEIRO (o MENTION_RE genérico
  // só pegaria "@Agente"). Rótulos mais longos primeiro p/ casar o nome completo.
  // Agentes (azul) e ferramentas (roxo) num só regex; o rótulo casado decide a cor.
  const toolSet = new Set(toolLabels);
  const todosRotulos = [...new Set([...handoffLabels, ...toolLabels])];
  const handoffRe = todosRotulos.length
    ? new RegExp("(?:" + todosRotulos.map((l) => "@" + escapeRe(l)).sort((a, b) => b.length - a.length).join("|") + ")(?![A-Za-zÀ-ÿ0-9])", "g")
    : null;
  // Frase para Transferência "@Transferência: Closer" (laranja) — o title mostra a frase exata.
  const transferLabels = Object.keys(transferMap);
  const transferRe = transferLabels.length
    ? new RegExp("(" + transferLabels.map((l) => "@" + escapeRe(l)).sort((a, b) => b.length - a.length).join("|") + ")(?![A-Za-zÀ-ÿ0-9])", "g")
    : null;
  // Texto EXATO de uma frase cadastrada, mesmo sem estar marcado como token: também fica laranja.
  const rawFrases = Object.keys(rawMap).filter((f) => f.length >= 8);
  const rawRe = rawFrases.length
    ? new RegExp(rawFrases.map(escapeRe).sort((a, b) => b.length - a.length).join("|"), "g")
    : null;
  doc.descendants((node: any, pos: number) => {
    if (!node.isText || !node.text) return;
    const text: string = node.text;
    let m: RegExpExecArray | null;
    FIELD_RE.lastIndex = 0;
    while ((m = FIELD_RE.exec(text))) {
      decos.push(Decoration.inline(pos + m.index, pos + m.index + m[0].length, { class: "lc-tok-field" }));
    }
    // Marcador de áudio [[audio:nome]] (ciano) — variante de mídia.
    AUDIO_RE.lastIndex = 0;
    while ((m = AUDIO_RE.exec(text))) {
      decos.push(Decoration.inline(pos + m.index, pos + m.index + m[0].length, { class: "lc-tok-audio" }));
    }
    const handoffRanges: [number, number][] = [];
    if (transferRe) {
      transferRe.lastIndex = 0;
      while ((m = transferRe.exec(text))) {
        const s = pos + m.index, e = s + m[1].length;
        handoffRanges.push([s, e]); // o MENTION_RE genérico não repinta "@Transferência" de azul
        // data-* alimentam o cartão de hover (frase atual + destino) — ver abrirPreviewFrase.
        decos.push(Decoration.inline(s, e, {
          class: "lc-tok-transfer",
          "data-frase": transferMap[m[1].slice(1)] ?? "",
          "data-destino": m[1].slice(1 + PREFIXO_TRANSFERENCIA.length),
        } as any));
      }
    }
    if (rawRe) {
      rawRe.lastIndex = 0;
      while ((m = rawRe.exec(text))) {
        const s = pos + m.index;
        decos.push(Decoration.inline(s, s + m[0].length, {
          class: "lc-tok-transfer",
          "data-frase": m[0],
          "data-destino": rawMap[m[0]] ?? "",
        } as any));
      }
    }
    if (handoffRe) {
      handoffRe.lastIndex = 0;
      while ((m = handoffRe.exec(text))) {
        if (!m[0]) { handoffRe.lastIndex++; continue; }
        const s = pos + m.index, e = s + m[0].length;
        handoffRanges.push([s, e]);
        decos.push(Decoration.inline(s, e, { class: toolSet.has(m[0].slice(1)) ? "lc-tok-tool" : "lc-tok-mention" }));
      }
    }
    MENTION_RE.lastIndex = 0;
    while ((m = MENTION_RE.exec(text))) {
      const start = pos + m.index + m[1].length;
      // Não duplicar: se o "@palavra" já está dentro de um handoff multi-palavra, pula
      // (senão vira dois spans/pills adjacentes com seam visível).
      if (handoffRanges.some(([s, e]) => start >= s && start < e)) continue;
      decos.push(Decoration.inline(start, start + m[2].length, { class: "lc-tok-mention" }));
    }
    // Mídia: pinta a URL crua do agent-media como chip @nome (texto continua a URL).
    MEDIA_URL_RE.lastIndex = 0;
    while ((m = MEDIA_URL_RE.exec(text))) {
      const url = m[1];
      // Nome do chip: PREFERE o rótulo atual da Biblioteca (por URL) — assim renomear
      // reflete no agente na hora. Só cai no nome-do-arquivo se a mídia não estiver na lista.
      const nome = mediaNames[url] ?? nomeDaUrl(m[3]);
      decos.push(Decoration.inline(pos + m.index, pos + m.index + url.length, {
        nodeName: "span",
        class: "lc-media-chip",
        "data-type": tipoUiDaUrl(m[2]),
        "data-name": "@" + nome,
      } as any));
    }
    if (fillRe) {
      fillRe.lastIndex = 0;
      while ((m = fillRe.exec(text))) {
        if (!m[0]) { fillRe.lastIndex++; continue; }
        decos.push(Decoration.inline(pos + m.index, pos + m.index + m[0].length, { class: "lc-tok-filled" }));
      }
    }
  });
  return DecorationSet.create(doc, decos);
}

const TokenHighlight = Extension.create<{ highlights: string[]; handoffLabels: string[]; toolLabels: string[]; mediaNames: Record<string, string>; transferMap: Record<string, string>; rawMap: Record<string, string> }>({
  name: "tokenHighlight",
  addOptions() { return { highlights: [], handoffLabels: [], toolLabels: [], mediaNames: {}, transferMap: {}, rawMap: {} }; },
  addProseMirrorPlugins() {
    const getH = () => this.options.highlights ?? [];
    const getL = () => this.options.handoffLabels ?? [];
    const getF = () => this.options.toolLabels ?? [];
    const getM = () => this.options.mediaNames ?? {};
    const getT = () => this.options.transferMap ?? {};
    const getR = () => this.options.rawMap ?? {};
    return [
      new Plugin({
        key: new PluginKey("tokenHighlight"),
        props: { decorations: (state) => buildTokenDecorations(state.doc, getH(), getL(), getF(), getM(), getT(), getR()) },
      }),
    ];
  },
});

export interface RichPromptEditorHandle {
  /** Insere texto na posição do cursor (usado pela Biblioteca de mídia). */
  insertText: (t: string) => void;
}

interface Props {
  value: string;
  onChange: (markdown: string) => void;
  /** Labels dos agentes para o menu @ (handoff). */
  handoffOptions?: string[];
  /** Labels das ferramentas para a seção "Ferramenta" do menu @ (acionar tool). */
  toolOptions?: string[];
  /** Cor de destaque (categoria) para a barra do contador. */
  accent?: string;
  /** Abre o popup da Biblioteca (upload/gestão). Vira o rodapé "Enviar/gerenciar" do submenu @. */
  onAbrirMidia?: () => void;
  /** Se o plano libera a Biblioteca de Mídia (senão a opção aparece com cadeado). */
  midiaLiberada?: boolean;
  /** Áudios da Biblioteca p/ o submenu inline do @ (legado — use `media`). */
  audios?: { id: string; name: string; url: string }[];
  /** TODA a mídia da Biblioteca (áudio/vídeo/imagem) p/ o submenu @ — lista e insere por tipo. */
  media?: { id: string; name: string; url: string; type: "audio" | "video" | "image"; pasta?: string | null }[];
  /** Monta o token do áudio inserido no prompt. Default = contrato [audio:nome](url). */
  buildAudioToken?: (a: { name: string; url: string }) => string;
  /** Valores já preenchidos (Edição rápida) — realça em verde no prompt p/ identificar. */
  highlights?: string[];
  /** Classe de altura mínima do editor (default alto p/ prompt; compacto p/ FAQ/objeção). */
  minHeight?: string;
  /** Mostra a categoria "Transferência" (frases para transferência, laranja) no menu @ — SÓ no editor do
   *  super admin (as frases são fixas). Os chips laranja aparecem em qualquer editor. */
  transferencia?: boolean;
  /** Abre o cadastro das frases para transferência (rodapé da categoria Transferência). */
  onGerenciarFrases?: () => void;
  /** Toolbar enxuta (só negrito/itálico + mídia + @) — p/ respostas curtas (FAQ/objeção). */
  compact?: boolean;
  /** Limite recomendado do contador (default 100.000). Ex.: 4.000 no prompt de follow-up. */
  max?: number;
  /** Esconde o botão de marcador de mídia (onde mídia não vale, como o follow-up). */
  semMidia?: boolean;
  /** Variáveis {{nome}} oferecidas no menu @ (categoria "Variáveis") e no botão Inserir. `valor` = o que vale agora. */
  variaveis?: { nome: string; valor: string | null }[];
}

type MediaLite = { id: string; name: string; url: string; type: "audio" | "video" | "image"; pasta?: string | null };
const MEDIA_ICON = { audio: Music, video: Video, image: ImageIcon } as const;

/**
 * Editor rich-text (WYSIWYG) que RENDERIZA markdown (negrito vira negrito etc.)
 * e devolve markdown em onChange — o bot continua lendo o prompt como markdown.
 */
export const RichPromptEditor = forwardRef<RichPromptEditorHandle, Props>(
  ({ value, onChange, handoffOptions = [], toolOptions = [], accent, onAbrirMidia, midiaLiberada, audios = [], media, buildAudioToken, highlights = [], minHeight = "min-h-[280px]", compact = false, transferencia = false, onGerenciarFrases, max: MAX = MAX_PADRAO, semMidia = false, variaveis = [] }, ref) => {
    // Lista unificada de mídia: usa `media` (todos os tipos); cai p/ `audios` (legado) se preciso.
    const mediaList: MediaLite[] = (media && media.length)
      ? media
      : audios.map((a) => ({ ...a, type: "audio" as const }));
    // Mapa URL → nome ATUAL da Biblioteca: o chip mostra o nome de agora (renomear reflete),
    // não o nome-do-arquivo travado na URL. Chave string p/ o efeito só rodar quando muda.
    const mediaNames: Record<string, string> = {};
    for (const a of mediaList) if (a.url) mediaNames[a.url] = a.name;
    // Frases para Transferência: chips laranja em QUALQUER editor; inserir pelo @ só com `transferencia`.
    const { data: frasesData } = useFrasesTroca();
    const frases: FraseTroca[] = frasesData ?? [];
    const transferMap: Record<string, string> = {};
    for (const f of frases) transferMap[rotuloFrase(f.nome)] = f.frase;
    const rawMap: Record<string, string> = {};
    for (const f of frases) rawMap[f.frase] = f.nome;
    const transferKey = frases.map((f) => `${f.nome}=${f.frase}`).join("|");
    const transferOpcoes: FraseTroca[] = transferencia ? frases : [];
    const temTransfer = transferencia && (transferOpcoes.length > 0 || !!onGerenciarFrases);
    const mediaNamesKey = mediaList.map((a) => `${a.url}=${a.name}`).join("");
    // Menu do "@" ancorado no cursor (abre ao digitar "@"): agentes + mídia.
    const [mention, setMention] = useState<{ query: string; from: number; caretLeft: number; caretBottom: number; caretTop: number } | null>(null);
    // Posição final do menu (calculada após render p/ caber na tela — flip p/ cima + clamp).
    const menuRef = useRef<HTMLDivElement>(null);
    const [menuPos, setMenuPos] = useState<{ left: number; top: number } | null>(null);
    // Navegação do menu @: categoria aberta (null = raiz/categorias) + item selecionado (teclado).
    const [menuCat, setMenuCat] = useState<"var" | "dep" | "tra" | "fer" | "bib" | null>(null);
    const [selIdx, setSelIdx] = useState(0);
    // Espelhos p/ o listener de teclado (registrado uma vez por abertura, lê o estado vivo).
    const rowsRef = useRef<any[]>([]);
    const selIdxRef = useRef(0);
    const acionarRef = useRef<(r: any) => void>(() => {});
    const menuCatRef = useRef(menuCat);
    const buscandoRef = useRef(false);
    // Realce: além das opções do menu, reconhece TODOS os rótulos conhecidos — o próprio agente
    // ("@Agente Coleta de Dados" no prompt dele) e os legados ("@Desenvolver Documento") — senão
    // só o "@Agente" ficava pintado e o resto parecia quebrado.
    const rotulosAgente = handoffOptions.length ? [...new Set([...handoffOptions, ...HANDOFF_LABELS])] : [];
    const rotulosFerramenta = toolOptions.length ? [...new Set([...toolOptions, ...TOOL_LABELS, ...LEGACY_TOOL_LABELS])] : [];
    const temMenu = variaveis.length > 0 || handoffOptions.length > 0 || toolOptions.length > 0 || !!onAbrirMidia || mediaList.length > 0 || temTransfer;

    // Preview da mídia ao passar o mouse no chip @nome (imagem/áudio/vídeo).
    const [preview, setPreview] = useState<{ url: string; type: string; name: string; left: number; top: number } | null>(null);
    const previewTimer = useRef<number | undefined>(undefined);
    const abrirPreview = (el: HTMLElement) => {
      window.clearTimeout(previewTimer.current);
      const r = el.getBoundingClientRect();
      setPreview({
        url: el.textContent ?? "",
        type: el.getAttribute("data-type") ?? "image",
        name: (el.getAttribute("data-name") ?? "").replace(/^@/, ""),
        left: Math.max(8, r.left),
        top: r.bottom + 6,
      });
    };
    const agendarFecharPreview = () => {
      window.clearTimeout(previewTimer.current);
      previewTimer.current = window.setTimeout(() => setPreview(null), 160);
    };
    // Cartão de hover do chip laranja (Frase para Transferência): mostra a frase ATUAL do
    // cadastro e o destino — muda na hora se o super admin editar a frase.
    const [previewFrase, setPreviewFrase] = useState<{ frase: string; destino: string; left: number; top: number } | null>(null);
    const previewFraseTimer = useRef<number | undefined>(undefined);
    const abrirPreviewFrase = (el: HTMLElement) => {
      window.clearTimeout(previewFraseTimer.current);
      const r = el.getBoundingClientRect();
      const ALTURA = 140; // estimada; abre p/ cima se não couber embaixo
      setPreviewFrase({
        frase: el.getAttribute("data-frase") ?? "",
        destino: el.getAttribute("data-destino") ?? "",
        left: Math.max(8, Math.min(r.left, window.innerWidth - 336)),
        top: r.bottom + 6 + ALTURA > window.innerHeight ? Math.max(8, r.top - 6 - ALTURA) : r.bottom + 6,
      });
    };
    const agendarFecharPreviewFrase = () => {
      window.clearTimeout(previewFraseTimer.current);
      previewFraseTimer.current = window.setTimeout(() => setPreviewFrase(null), 120);
    };
    // Remove a mídia (a URL inteira) do prompt — botão "apagar" do preview do chip.
    const removerMidiaUrl = (url: string) => {
      if (!editor || !url) return;
      let range: { from: number; to: number } | null = null;
      editor.state.doc.descendants((node: any, pos: number) => {
        if (range || !node.isText || !node.text) return;
        const idx = node.text.indexOf(url);
        if (idx >= 0) { range = { from: pos + idx, to: pos + idx + url.length }; return false; }
      });
      if (range) editor.chain().focus().deleteRange(range).run();
      setPreview(null);
    };

    const detectMention = useCallback((ed: any) => {
      if (!ed || !temMenu) return setMention(null);
      const sel = ed.state.selection;
      if (!sel.empty) return setMention(null);
      const to = sel.from;
      const from = Math.max(0, to - 40);
      const textBefore = ed.state.doc.textBetween(from, to, "\n", "\n");
      const m = /@([A-Za-zÀ-ÿ]*)$/.exec(textBefore);
      if (!m) return setMention(null);
      const atPos = to - m[0].length; // posição do "@"
      const c = ed.view.coordsAtPos(to);
      setMention({ query: m[1], from: atPos, caretLeft: c.left, caretBottom: c.bottom, caretTop: c.top });
    }, [temMenu]);
    // Os handlers do editor (onUpdate/onSelectionUpdate) são criados UMA vez e capturariam a
    // detectMention inicial — se `temMenu` virasse true depois (mídia async), o menu @ não abriria.
    // Ref sempre aponta pra versão atual.
    const detectMentionRef = useRef(detectMention);
    detectMentionRef.current = detectMention;

    const edRef = useRef<any>(null);
    const editor = useEditor({
      extensions: [
        // paragraph: false → usamos ParagraphKeepBlank (preserva linhas em branco no markdown).
        StarterKit.configure({ paragraph: false }),
        ParagraphKeepBlank,
        // Markdown completo (igual a um preview padrão): listas de tarefas, imagens e tabelas (GFM).
        TaskList,
        TaskItem.configure({ nested: true }),
        Image.configure({ inline: false }),
        Table.configure({ resizable: false }),
        TableRow,
        TableHeader,
        TableCell,
        TokenHighlight.configure({ highlights, handoffLabels: rotulosAgente, toolLabels: rotulosFerramenta, mediaNames, transferMap, rawMap }),
        Markdown.configure({ html: false, transformPastedText: true, transformCopiedText: true }),
        CharacterCount,
      ],
      content: value || "",
      editorProps: {
        attributes: { class: `${minHeight} max-h-[520px] overflow-y-auto px-3 py-2 outline-none` },
        handleKeyDown: (view, event) => {
          if (event.key === "Escape") { setMention(null); return false; }
          // Apaga o chip de mídia INTEIRO num toque (Backspace = o de trás; Delete = o da frente).
          if ((event.key === "Backspace" || event.key === "Delete") && view.state.selection.empty) {
            const range = chipMidiaAdjacente(view.state, event.key === "Backspace" ? "before" : "after");
            if (range) {
              view.dispatch(view.state.tr.delete(range.from, range.to));
              event.preventDefault();
              return true;
            }
          }
          return false;
        },
        // Colagem SEMPRE tratada como markdown: converte **negrito**, ## títulos, - listas,
        // [texto](url), > citações etc. mesmo quando o clipboard traz HTML (que deixaria os
        // marcadores literais). Os {{campo}} e @handoff são preservados (sem marcador markdown)
        // e voltam a ser realçados pela decoração. (Digitar já converte via input-rules do StarterKit.)
        handlePaste: (_view, event) => {
          const ed = edRef.current;
          const md = event.clipboardData?.getData("text/plain");
          if (!ed || !md) return false;
          // Só intercepta colagem MULTI-LINHA (prompt inteiro) — aí parseia como markdown
          // (títulos, listas, citações, negrito, links), que o paste padrão deixaria literal
          // quando o clipboard traz HTML. Linha única segue o paste normal + paste-rules do
          // StarterKit (que já convertem **negrito**, *itálico*, `código` sem quebrar a frase).
          if (!md.includes("\n")) return false;
          try {
            // insertContent do tiptap-markdown JÁ parseia markdown (1x). Passar o MD cru —
            // pré-parsear pra HTML aqui causava parse-duplo (o HTML era re-escapado → &lt;h1&gt;).
            const ok = ed.chain().focus().insertContent(md).run();
            return ok !== false;
          } catch {
            return false; // deixa o comportamento padrão se algo falhar
          }
        },
      },
      onCreate: ({ editor }) => { edRef.current = editor; },
      onUpdate: ({ editor }) => {
        // Des-escapa os marcadores de áudio (\[\[audio:...\]\] → [[audio:...]]): o serializador
        // markdown escapa colchetes, o que quebrava o marcador no dado salvo.
        const md = ((editor.storage as any).markdown.getMarkdown() as string)
          .replace(/\\?\[\\?\[\s*((?:[aá]udio|v[ií]deo|m[ií]dia|media|imagem):[^\]\\]+?)\s*\\?\]\\?\]/gi, "[[$1]]");
        onChange(md);
        detectMentionRef.current(editor);
      },
      onSelectionUpdate: ({ editor }) => detectMentionRef.current(editor),
    });

    useImperativeHandle(ref, () => ({
      insertText: (t: string) => editor?.chain().focus().insertContent(t).run(),
    }), [editor]);

    // Sincroniza o `value` EXTERNO → editor. Por padrão o editor é uncontrolled (só semeia o
    // content inicial); se o pai troca o value depois — ex.: remover/reordenar uma objeção
    // (key={idx}) ou aplicar uma atualização — o editor ficava com o conteúdo ANTIGO e salvava
    // errado ("às vezes não salva"). Guarda de foco: NÃO mexe enquanto o usuário digita.
    useEffect(() => {
      if (!editor || editor.isFocused) return;
      const atual = ((editor.storage as any).markdown.getMarkdown() as string)
        .replace(/\\?\[\\?\[\s*((?:[aá]udio|v[ií]deo|m[ií]dia|media|imagem):[^\]\\]+?)\s*\\?\]\\?\]/gi, "[[$1]]");
      if (String(value ?? "").trim() !== String(atual ?? "").trim()) {
        editor.commands.setContent(value || "", { emitUpdate: false } as any);
      }
    }, [value, editor]);

    // Atualiza a decoração AO VIVO quando muda o realce, os handoffs ou os nomes da Biblioteca
    // (renomear mídia → o chip @nome reflete na hora). As options do TokenHighlight ficam
    // congeladas no create; aqui reescrevemos e forçamos um recomputo das decorations.
    useEffect(() => {
      if (!editor) return;
      const ext = (editor.extensionManager.extensions as any[]).find((e) => e.name === "tokenHighlight");
      if (!ext) return;
      ext.options.highlights = highlights;
      ext.options.handoffLabels = rotulosAgente;
      ext.options.toolLabels = rotulosFerramenta;
      ext.options.mediaNames = mediaNames;
      ext.options.transferMap = transferMap;
      ext.options.rawMap = rawMap;
      editor.view.dispatch(editor.state.tr); // no-op tr → re-executa decorations
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [editor, highlights.join(""), [...handoffOptions, ...toolOptions].join(""), mediaNamesKey, transferKey]);

    // Reposiciona o menu @ p/ caber na viewport: abre abaixo do cursor; se não couber,
    // vira p/ cima; sempre faz clamp nas bordas. Roda antes do paint (sem flicker).
    useLayoutEffect(() => {
      if (!mention) { setMenuPos(null); return; }
      const el = menuRef.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const vw = window.innerWidth, vh = window.innerHeight, M = 8;
      let left = mention.caretLeft;
      if (left + rect.width + M > vw) left = vw - rect.width - M;
      if (left < M) left = M;
      let top = mention.caretBottom + 4;                 // padrão: abaixo do cursor
      const espacoAbaixo = vh - top - M;
      if (rect.height > espacoAbaixo && mention.caretTop - 4 - rect.height >= M) {
        top = mention.caretTop - 4 - rect.height;        // não coube → vira p/ cima
      }
      // clamp final SEMPRE (cobre caret fora da viewport e menu maior que o espaço).
      // A altura já é limitada por max-h-[calc(100vh-1rem)] + scroll interno.
      top = Math.max(M, Math.min(top, vh - rect.height - M));
      setMenuPos({ left, top });
    }, [mention]);

    // Ao digitar uma query (ou fechar), volta p/ a raiz de categorias (a busca é global).
    useEffect(() => {
      if (!mention || mention.query.length > 0) setMenuCat(null);
    }, [mention]);

    // Reseta o item destacado quando a visão muda (raiz ↔ categoria ↔ busca).
    useEffect(() => { setSelIdx(0); }, [menuCat, mention?.query]);

    // Navegação por teclado do menu @ (↑↓ mover, Enter selecionar/abrir, ←/Esc voltar ou fechar).
    // Listener em CAPTURE no document p/ rodar antes do ProseMirror (que trataria Enter/setas).
    useEffect(() => {
      if (!mention) return;
      const onKey = (e: KeyboardEvent) => {
        const rs = rowsRef.current;
        if (e.key === "ArrowDown") {
          e.preventDefault(); e.stopPropagation();
          setSelIdx((i) => (rs.length ? (i + 1) % rs.length : 0));
        } else if (e.key === "ArrowUp") {
          e.preventDefault(); e.stopPropagation();
          setSelIdx((i) => (rs.length ? (i - 1 + rs.length) % rs.length : 0));
        } else if (e.key === "Enter") {
          e.preventDefault(); e.stopPropagation();
          const r = rs[selIdxRef.current];
          if (r) acionarRef.current(r);
        } else if (e.key === "ArrowRight") {
          const r = rs[selIdxRef.current];
          if (r?.t === "cat") { e.preventDefault(); e.stopPropagation(); acionarRef.current(r); }
        } else if (e.key === "Escape") {
          e.preventDefault(); e.stopPropagation();
          if (menuCatRef.current && !buscandoRef.current) setMenuCat(null); else setMention(null);
        } else if (e.key === "ArrowLeft") {
          if (menuCatRef.current && !buscandoRef.current) { e.preventDefault(); e.stopPropagation(); setMenuCat(null); }
        }
      };
      document.addEventListener("keydown", onKey, true);
      return () => document.removeEventListener("keydown", onKey, true);
    }, [mention]);

    if (!editor) return null;

    // Remove o "@query" digitado (antes de inserir handoff ou abrir a mídia).
    const limparMencao = () => {
      if (!mention) return;
      const to = editor.state.selection.from;
      editor.chain().focus().deleteRange({ from: mention.from, to }).run();
    };

    const inserirVariavel = (nome: string) => {
      limparMencao();
      editor.chain().focus().insertContent(`{{${nome}}}`).run();
      setMention(null);
    };

    const inserirHandoff = (label: string) => {
      limparMencao();
      editor.chain().focus().insertContent(`@${label} `).run();
      setMention(null);
    };

    // Abre o popup da Biblioteca (upload/gestão) — rodapé do submenu @.
    const abrirMidia = () => {
      limparMencao();
      setMention(null);
      onAbrirMidia?.();
    };

    // Insere a URL PURA da mídia (o bot recebe a URL; o editor pinta como chip @nome no hover).
    const inserirMidia = (a: MediaLite) => {
      limparMencao();
      editor.chain().focus().insertContent(`${a.url} `).run();
      setMention(null);
    };

    // Insere um MARCADOR de áudio [[audio:nome]] e já seleciona "nome" pra renomear na hora.
    // (Variante de mídia — o cliente escolhe o áudio real na "Edição rápida de áudios".)
    const inserirMarcadorAudio = () => {
      const from = editor.state.selection.from;
      editor.chain().focus().insertContent("[[midia:nome]] ").run();
      const s = from + "[[midia:".length;
      editor.chain().setTextSelection({ from: s, to: s + 4 }).run();
    };

    const q = mention?.query.toLowerCase() ?? "";
    const mentionOpts = mention ? handoffOptions.filter((l) => l.toLowerCase().includes(q)) : [];
    const toolOpts = mention ? toolOptions.filter((l) => l.toLowerCase().includes(q)) : [];
    const varOpts = mention ? variaveis.filter((v) => v.nome.toLowerCase().includes(q)) : [];
    const mediaOpts = mention ? mediaList.filter((a) => a.name.toLowerCase().includes(q)) : [];
    const transferOpts = mention
      ? transferOpcoes.filter((f) => rotuloFrase(f.nome).toLowerCase().includes(q) || f.frase.toLowerCase().includes(q))
      : [];
    const temMidia = !!onAbrirMidia || mediaList.length > 0;
    const buscando = !!mention && q.length > 0; // digitou algo após @ → busca global (lista plana)

    // Categorias da raiz (nível 1 do menu @) — só as que têm conteúdo.
    const categorias = [
      variaveis.length > 0 && { t: "cat" as const, cat: "var" as const, label: "Variáveis", count: variaveis.length, Icon: Braces, color: "#7c3aed" },
      handoffOptions.length > 0 && { t: "cat" as const, cat: "dep" as const, label: "Departamento", count: handoffOptions.length, Icon: Users, color: "#2563eb" },
      temTransfer && { t: "cat" as const, cat: "tra" as const, label: "Transferência", count: transferOpcoes.length, Icon: ArrowRightLeft, color: COR_TRANSFERENCIA },
      toolOptions.length > 0 && { t: "cat" as const, cat: "fer" as const, label: "Ferramentas", count: toolOptions.length, Icon: Wrench, color: "#7c3aed" },
      temMidia && { t: "cat" as const, cat: "bib" as const, label: "Biblioteca", count: mediaList.length, Icon: Library, color: "#0d9488" },
    ].filter(Boolean) as any[];

    // Linhas da visão atual: busca global (plana) · raiz (categorias) · drill numa categoria.
    let rows: any[];
    if (buscando) {
      rows = [
        ...varOpts.map((v) => ({ t: "var", v })),
        ...mentionOpts.map((l) => ({ t: "handoff", label: l })),
        ...transferOpts.map((f) => ({ t: "transfer", frase: f })),
        ...toolOpts.map((l) => ({ t: "tool", label: l })),
        ...(midiaLiberada ? mediaOpts.map((a) => ({ t: "media", media: a })) : []),
      ];
    } else if (menuCat === "var") {
      rows = variaveis.map((v) => ({ t: "var", v }));
    } else if (menuCat === "dep") {
      rows = handoffOptions.map((l) => ({ t: "handoff", label: l }));
    } else if (menuCat === "tra") {
      rows = transferOpcoes.map((f) => ({ t: "transfer", frase: f }));
      if (onGerenciarFrases) rows.push({ t: "gerenciar" });
    } else if (menuCat === "fer") {
      rows = toolOptions.map((l) => ({ t: "tool", label: l }));
    } else if (menuCat === "bib") {
      if (!midiaLiberada) rows = [{ t: "locked" }];
      else {
        rows = mediaList.map((a) => ({ t: "media", media: a }));
        if (onAbrirMidia) rows.push({ t: "upload" });
      }
    } else {
      rows = categorias; // raiz
    }

    const acionar = (r: any) => {
      if (r.t === "cat") setMenuCat(r.cat);
      else if (r.t === "var") inserirVariavel(r.v.nome);
      else if (r.t === "handoff" || r.t === "tool") inserirHandoff(r.label);
      else if (r.t === "transfer") inserirHandoff(rotuloFrase(r.frase.nome));
      else if (r.t === "gerenciar") { limparMencao(); setMention(null); onGerenciarFrases?.(); }
      else if (r.t === "media") inserirMidia(r.media);
      else if (r.t === "upload") abrirMidia();
      // locked: sem ação
    };

    // Espelha o estado vivo p/ o listener de teclado (registrado por abertura).
    const selClamped = Math.min(selIdx, Math.max(0, rows.length - 1));
    rowsRef.current = rows;
    selIdxRef.current = selClamped;
    acionarRef.current = acionar;
    menuCatRef.current = menuCat;
    buscandoRef.current = buscando;

    const menuVisivel = !!mention && categorias.length > 0 && (!buscando || rows.length > 0);
    const catMeta = menuCat ? categorias.find((c) => c.cat === menuCat) : null;

    const len = (editor.storage as any).characterCount.characters() as number;
    const pct = Math.min(100, Math.round((len / MAX) * 100));
    const near = len >= MAX * 0.9;
    const barColor = len >= MAX ? "#dc2626" : near ? "#f59e0b" : (accent ?? "#22c55e");

    const Btn = ({ title, onClick, active, children }: { title: string; onClick: () => void; active?: boolean; children: React.ReactNode }) => (
      <button
        type="button"
        title={title}
        onMouseDown={(e) => { e.preventDefault(); onClick(); }}
        className={`size-7 rounded grid place-items-center transition-colors ${active ? "bg-[#e5e8ee] text-[#101828]" : "text-[#475467] hover:bg-[#eef1f5]"}`}
      >{children}</button>
    );

    const Kbd = ({ children }: { children: React.ReactNode }) => (
      <kbd className="inline-grid place-items-center min-w-[16px] h-4 px-1 rounded border border-[#e5e8ee] bg-[#f8fafc] text-[9px] font-semibold text-[#64748b]">{children}</kbd>
    );

    return (
      <div>
        {/* Toolbar */}
        <div className="mb-2 flex flex-wrap items-center gap-0.5 rounded-lg border border-[#eef1f5] bg-[#fafbfc] p-1">
          <Btn title="Negrito" onClick={() => editor.chain().focus().toggleBold().run()} active={editor.isActive("bold")}><Bold className="size-3.5" /></Btn>
          <Btn title="Itálico" onClick={() => editor.chain().focus().toggleItalic().run()} active={editor.isActive("italic")}><Italic className="size-3.5" /></Btn>
          {!compact && (
            <>
              <Btn title="Código" onClick={() => editor.chain().focus().toggleCode().run()} active={editor.isActive("code")}><Code className="size-3.5" /></Btn>
              <div className="mx-1 h-5 w-px bg-[#e5e8ee]" />
              <Btn title="Título 1" onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()} active={editor.isActive("heading", { level: 1 })}><Heading1 className="size-3.5" /></Btn>
              <Btn title="Título 2" onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()} active={editor.isActive("heading", { level: 2 })}><Heading2 className="size-3.5" /></Btn>
              <Btn title="Título 3" onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()} active={editor.isActive("heading", { level: 3 })}><Heading3 className="size-3.5" /></Btn>
              <Btn title="Citação" onClick={() => editor.chain().focus().toggleBlockquote().run()} active={editor.isActive("blockquote")}><Quote className="size-3.5" /></Btn>
              <Btn title="Lista" onClick={() => editor.chain().focus().toggleBulletList().run()} active={editor.isActive("bulletList")}><List className="size-3.5" /></Btn>
              <Btn title="Lista numerada" onClick={() => editor.chain().focus().toggleOrderedList().run()} active={editor.isActive("orderedList")}><ListOrdered className="size-3.5" /></Btn>
            </>
          )}
          {/* Mídia: no modo compacto (FAQ/objeção) abre a Biblioteca p/ ESCOLHER a mídia
              (insere a URL direto — o bot envia). No prompt, insere o marcador [[midia:nome]].
              Compacto SEM mídia (produto texto) = sem botão de mídia. */}
          {((compact && onAbrirMidia) || (!compact && !semMidia)) && <div className="mx-1 h-5 w-px bg-[#e5e8ee]" />}
          {compact && onAbrirMidia ? (
            <Btn title="Inserir mídia (áudio/vídeo) da Biblioteca" onClick={onAbrirMidia}><Music className="size-3.5 text-[#0891b2]" /></Btn>
          ) : !compact && !semMidia ? (
            <Btn title="Inserir marcador de mídia [[midia:nome]]" onClick={inserirMarcadorAudio}><Music className="size-3.5 text-[#0891b2]" /></Btn>
          ) : null}
          {(variaveis.length > 0 || handoffOptions.length > 0 || toolOptions.length > 0 || temTransfer) && (
            <>
              <div className="mx-1 h-5 w-px bg-[#e5e8ee]" />
              <Popover>
                <PopoverTrigger asChild>
                  <button type="button" className="h-7 px-2 rounded grid grid-flow-col items-center gap-1 text-[#475467] hover:bg-[#eef1f5] transition-colors text-xs font-semibold">
                    <AtSign className="size-3.5" />Inserir<ChevronDown className="size-3 opacity-60" />
                  </button>
                </PopoverTrigger>
                <PopoverContent align="start" className="w-64 p-1 max-h-[60vh] overflow-y-auto">
                  {variaveis.length > 0 && (
                    <>
                      <div className="px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-[#7c3aed]">Variáveis</div>
                      {variaveis.map((v) => (
                        <button key={v.nome} type="button" title={v.valor ? `Agora vale: ${v.valor}` : "Ainda sem valor"}
                          onMouseDown={(e) => { e.preventDefault(); inserirVariavel(v.nome); }}
                          className="w-full text-left rounded-lg px-2 py-1.5 flex items-center gap-2 hover:bg-[#faf8ff] transition-colors">
                          <code className="text-[12px] font-semibold text-[#7c3aed] shrink-0">{`{{${v.nome}}}`}</code>
                          <span className={`flex-1 min-w-0 truncate text-[11px] text-right ${v.valor ? "text-[#98a2b3]" : "text-[#c2410c]"}`}>{v.valor ?? "sem valor"}</span>
                        </button>
                      ))}
                      {(handoffOptions.length > 0 || temTransfer || toolOptions.length > 0) && <div className="my-1 h-px bg-[#eef1f5]" />}
                    </>
                  )}
                  {handoffOptions.length > 0 && (
                    <>
                      <div className="px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-[#94a3b8]">Departamento</div>
                      {handoffOptions.map((l) => (
                        <button
                          key={l}
                          type="button"
                          onMouseDown={(e) => { e.preventDefault(); inserirHandoff(l); }}
                          className="w-full text-left rounded-lg px-2 py-1.5 text-sm font-medium text-[#101828] hover:bg-[#f6f8fb] transition-colors"
                        >@{l}</button>
                      ))}
                    </>
                  )}
                  {temTransfer && (
                    <>
                      {handoffOptions.length > 0 && <div className="my-1 h-px bg-[#eef1f5]" />}
                      <div className="px-2 py-1 text-[10px] font-bold uppercase tracking-wider" style={{ color: COR_TRANSFERENCIA }}>Transferência</div>
                      {transferOpcoes.map((f) => (
                        <button
                          key={f.id}
                          type="button"
                          title={f.frase}
                          onMouseDown={(e) => { e.preventDefault(); inserirHandoff(rotuloFrase(f.nome)); }}
                          className="w-full text-left rounded-lg px-2 py-1.5 text-sm font-medium hover:bg-[#fff7ed] transition-colors"
                          style={{ color: COR_TRANSFERENCIA }}
                        >@{rotuloFrase(f.nome)}</button>
                      ))}
                      {onGerenciarFrases && (
                        <button
                          type="button"
                          onMouseDown={(e) => { e.preventDefault(); onGerenciarFrases(); }}
                          className="w-full text-left rounded-lg px-2 py-1.5 text-xs font-medium text-[#475467] hover:bg-[#f6f8fb] transition-colors flex items-center gap-1.5"
                        ><Settings2 className="size-3.5" />Gerenciar frases para transferência</button>
                      )}
                    </>
                  )}
                  {toolOptions.length > 0 && (
                    <>
                      {(handoffOptions.length > 0 || temTransfer) && <div className="my-1 h-px bg-[#eef1f5]" />}
                      <div className="px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-[#94a3b8]">Ferramentas</div>
                      {toolOptions.map((l) => (
                        <button
                          key={l}
                          type="button"
                          onMouseDown={(e) => { e.preventDefault(); inserirHandoff(l); }}
                          className="w-full text-left rounded-lg px-2 py-1.5 text-sm font-medium text-[#101828] hover:bg-[#f6f8fb] transition-colors"
                        >@{l}</button>
                      ))}
                    </>
                  )}
                </PopoverContent>
              </Popover>
            </>
          )}
          {/* Super admin: seleciona a frase já escrita no prompt e marca → chip laranja. */}
          {transferencia && (
            <>
              <div className="mx-1 h-5 w-px bg-[#e5e8ee]" />
              <MarcarFraseTroca editor={editor} onGerenciar={onGerenciarFrases} />
            </>
          )}
        </div>

        {/* Conteúdo renderizado */}
        <div
          className="lc-rich rounded-xl border border-input bg-[#fafbfc] ring-offset-background focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2"
          onMouseOver={(e) => {
            const alvo = e.target as HTMLElement;
            const chip = alvo.closest?.(".lc-media-chip") as HTMLElement | null;
            if (chip) abrirPreview(chip);
            const frase = alvo.closest?.(".lc-tok-transfer") as HTMLElement | null;
            if (frase) abrirPreviewFrase(frase);
          }}
          onMouseOut={(e) => {
            const alvo = e.target as HTMLElement;
            if (alvo.closest?.(".lc-media-chip")) agendarFecharPreview();
            if (alvo.closest?.(".lc-tok-transfer")) agendarFecharPreviewFrase();
          }}
        >
          <EditorContent editor={editor} />
        </div>

        {/* Menu de @handoff ancorado no cursor (abre ao digitar "@").
            Renderizado em PORTAL no body p/ o position:fixed não ser quebrado por
            ancestrais com transform (framer-motion no wizard). */}
        {menuVisivel && createPortal(
          <>
            <div className="fixed inset-0 z-[60]" onMouseDown={() => setMention(null)} />
            <div
              ref={menuRef}
              className="fixed z-[61] w-64 flex flex-col rounded-xl border border-[#e5e8ee] bg-white shadow-xl overflow-hidden max-h-[calc(100vh-1rem)]"
              style={menuPos
                ? { left: menuPos.left, top: menuPos.top }
                : { left: mention.caretLeft, top: mention.caretBottom + 4, visibility: "hidden" }}
            >
              {/* Cabeçalho: raiz (título) ou drill (voltar) */}
              {catMeta ? (
                <button
                  type="button"
                  onMouseDown={(e) => { e.preventDefault(); setMenuCat(null); }}
                  className="flex items-center gap-2 px-2.5 py-2 border-b border-[#eef1f5] text-[11px] font-bold uppercase tracking-wider text-[#475467] hover:bg-[#f6f8fb] transition-colors"
                >
                  <ArrowLeft className="size-3.5 shrink-0" />
                  <catMeta.Icon className="size-3.5 shrink-0" style={{ color: catMeta.color }} />
                  <span className="flex-1 text-left">{catMeta.label}</span>
                  <span className="text-[#cbd5e1] tabular-nums">{catMeta.count}</span>
                </button>
              ) : (
                <div className="px-2.5 py-2 border-b border-[#eef1f5] text-[10px] font-bold uppercase tracking-wider text-[#94a3b8]">
                  {buscando ? "Resultados" : "Inserir no prompt"}
                </div>
              )}

              {/* Corpo (lista da visão atual) */}
              <div className="flex-1 min-h-0 overflow-y-auto p-1">
                {rows.length === 0 ? (
                  <div className="px-2 py-3 text-center text-xs text-[#94a3b8]">Nenhum resultado</div>
                ) : rows.map((r, i) => {
                  const sel = i === selClamped;
                  const base = `w-full text-left rounded-lg px-2 py-1.5 text-sm flex items-center gap-2 transition-colors ${sel ? "bg-[#eef2f7]" : "hover:bg-[#f6f8fb]"}`;
                  if (r.t === "cat") {
                    const Ico = r.Icon;
                    return (
                      <button key={"cat-" + r.cat} type="button" onMouseEnter={() => setSelIdx(i)} onMouseDown={(e) => { e.preventDefault(); acionar(r); }} className={base + " font-medium text-[#101828]"}>
                        <Ico className="size-4 shrink-0" style={{ color: r.color }} />
                        <span className="flex-1">{r.label}</span>
                        <span className="text-[11px] font-semibold text-[#cbd5e1] tabular-nums">{r.count}</span>
                        <ChevronRight className="size-4 text-[#cbd5e1] shrink-0" />
                      </button>
                    );
                  }
                  if (r.t === "var") {
                    return (
                      <button key={"var-" + r.v.nome} type="button" onMouseEnter={() => setSelIdx(i)} onMouseDown={(e) => { e.preventDefault(); acionar(r); }} className={base + " font-medium"}
                        title={r.v.valor ? `Agora vale: ${r.v.valor}` : "Ainda sem valor"}>
                        {buscando && <span className="text-[8px] font-bold uppercase tracking-wider text-[#cbd5e1] shrink-0 w-9">Var.</span>}
                        <code className="text-[12px] font-semibold text-[#7c3aed] shrink-0">{`{{${r.v.nome}}}`}</code>
                        <span className={`flex-1 min-w-0 truncate text-[11px] text-right ${r.v.valor ? "text-[#98a2b3]" : "text-[#c2410c]"}`}>{r.v.valor ?? "sem valor"}</span>
                      </button>
                    );
                  }
                  if (r.t === "handoff" || r.t === "tool") {
                    const cor = r.t === "tool" ? "#7c3aed" : "#2563eb";
                    return (
                      <button key={r.t + "-" + r.label} type="button" onMouseEnter={() => setSelIdx(i)} onMouseDown={(e) => { e.preventDefault(); acionar(r); }} className={base + " font-medium"} style={{ color: cor }}>
                        {buscando && <span className="text-[8px] font-bold uppercase tracking-wider text-[#cbd5e1] shrink-0 w-9">{r.t === "tool" ? "Ferr." : "Depto."}</span>}
                        <span className="flex-1 truncate">@{r.label}</span>
                      </button>
                    );
                  }
                  if (r.t === "transfer") {
                    const f: FraseTroca = r.frase;
                    return (
                      <button key={"tra-" + f.id} type="button" onMouseEnter={() => setSelIdx(i)} onMouseDown={(e) => { e.preventDefault(); acionar(r); }} title={f.frase} className={base + " font-medium"}>
                        {buscando && <span className="text-[8px] font-bold uppercase tracking-wider text-[#cbd5e1] shrink-0 w-9">Transf.</span>}
                        <span className="flex-1 min-w-0">
                          <span className="block truncate" style={{ color: COR_TRANSFERENCIA }}>@{rotuloFrase(f.nome)}</span>
                          <span className="block truncate text-[11px] font-normal text-[#98A2B3]">“{f.frase}”</span>
                        </span>
                      </button>
                    );
                  }
                  if (r.t === "gerenciar") {
                    return (
                      <button key="gerenciar" type="button" onMouseEnter={() => setSelIdx(i)} onMouseDown={(e) => { e.preventDefault(); acionar(r); }} title="Criar ou editar as frases para transferência" className={base + " text-xs font-medium text-[#475467]"}>
                        <Settings2 className="size-3.5 shrink-0" />
                        <span className="flex-1">Gerenciar frases para transferência</span>
                      </button>
                    );
                  }
                  if (r.t === "media") {
                    const a = r.media; const MIcon = MEDIA_ICON[a.type] ?? Music;
                    return (
                      <button key={"media-" + a.id} type="button" onMouseEnter={() => setSelIdx(i)} onMouseDown={(e) => { e.preventDefault(); acionar(r); }} title={`Inserir ${a.type === "image" ? "imagem" : a.type === "video" ? "vídeo" : "áudio"} no prompt`} className={base + " font-medium text-[#101828]"}>
                        <MIcon className="size-3.5 text-[#7c3aed] shrink-0" />
                        <span className="flex-1 truncate">{a.name}</span>
                        {a.pasta && (
                          <span className="max-w-[45%] truncate text-[10.5px] font-normal text-[#69786F] shrink" title={`Pasta: ${rotuloDaPasta(a.pasta)}`}>{nomeDaPasta(a.pasta)}</span>
                        )}
                        <span className="text-[9px] font-bold uppercase tracking-wider text-[#cbd5e1] shrink-0">{a.type === "image" ? "img" : a.type}</span>
                      </button>
                    );
                  }
                  if (r.t === "upload") {
                    return (
                      <button key="upload" type="button" onMouseEnter={() => setSelIdx(i)} onMouseDown={(e) => { e.preventDefault(); acionar(r); }} title="Abrir a Biblioteca para enviar ou gerenciar mídia" className={base + " text-xs font-medium text-[#475467]"}>
                        <Upload className="size-3.5 shrink-0" />
                        <span className="flex-1">Enviar / gerenciar mídia</span>
                      </button>
                    );
                  }
                  return ( // locked
                    <div key="locked" className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm font-medium text-[#94a3b8]">
                      <Lock className="size-3.5 shrink-0" />
                      <span className="flex-1">Disponível em planos superiores</span>
                      <span className="text-[9px] font-bold uppercase tracking-wider bg-[#f1f5f9] rounded px-1 py-0.5">Plano</span>
                    </div>
                  );
                })}
              </div>

              {/* Rodapé de ajuda (atalhos de teclado) */}
              <div className="shrink-0 border-t border-[#eef1f5] px-2.5 py-1.5 text-[10px] text-[#98A2B3] flex items-center gap-1 flex-wrap">
                <Kbd>↑</Kbd><Kbd>↓</Kbd><span>navegar</span>
                <span className="text-[#e5e8ee]">·</span>
                <Kbd>↵</Kbd><span>{rows[selClamped]?.t === "cat" ? "abrir" : "inserir"}</span>
                <span className="text-[#e5e8ee]">·</span>
                <Kbd>esc</Kbd><span>{catMeta ? "voltar" : "fechar"}</span>
              </div>
            </div>
          </>,
          document.body,
        )}

        {/* Preview da mídia no hover do chip */}
        {preview && createPortal(
          <div
            className="fixed z-[62] rounded-xl border border-[#e5e8ee] bg-white shadow-xl p-2"
            style={{ left: preview.left, top: preview.top }}
            onMouseEnter={() => window.clearTimeout(previewTimer.current)}
            onMouseLeave={agendarFecharPreview}
          >
            {preview.type === "image" ? (
              <img src={preview.url} alt={preview.name} className="block max-w-[280px] max-h-[200px] rounded-lg object-contain" />
            ) : preview.type === "video" ? (
              <video src={preview.url} controls className="block max-w-[280px] max-h-[200px] rounded-lg" />
            ) : (
              <audio src={preview.url} controls className="w-[260px]" />
            )}
            <div className="mt-1.5 flex items-center gap-2 max-w-[280px]">
              <span className="flex-1 text-[11px] font-medium text-[#475467] truncate">{preview.name}</span>
              <button
                type="button"
                onMouseDown={(e) => { e.preventDefault(); removerMidiaUrl(preview.url); }}
                title="Apagar esta mídia do prompt"
                className="shrink-0 inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[11px] font-semibold text-[#dc2626] hover:bg-[#fef2f2] transition-colors"
              >
                <Trash2 className="size-3.5" />Apagar
              </button>
            </div>
          </div>,
          document.body,
        )}

        {/* Cartão de hover da Frase para Transferência (chip laranja) */}
        {previewFrase && previewFrase.frase && createPortal(
          <div
            className="fixed z-[62] w-80 rounded-xl border bg-white shadow-xl p-3"
            style={{ left: previewFrase.left, top: previewFrase.top, borderColor: "#fed7aa" }}
            onMouseEnter={() => window.clearTimeout(previewFraseTimer.current)}
            onMouseLeave={agendarFecharPreviewFrase}
          >
            <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider" style={{ color: COR_TRANSFERENCIA }}>
              <ArrowRightLeft className="size-3" />Frase para Transferência
            </div>
            <p className="mt-1.5 text-sm text-[#101828] leading-relaxed">“{previewFrase.frase}”</p>
            {previewFrase.destino && (
              <p className="mt-1.5 text-[11px] text-[#667085] leading-snug">
                A IA fala exatamente esta frase e o lead passa para <strong className="text-[#101828]">{previewFrase.destino}</strong>.
              </p>
            )}
          </div>,
          document.body,
        )}

        {/* Contador */}
        <div className="mt-2">
          <div className="h-1.5 rounded-full bg-[#eef1f5] overflow-hidden">
            <div className="h-full rounded-full transition-[width] duration-200" style={{ width: `${pct}%`, backgroundColor: barColor }} />
          </div>
          <div className="flex items-center justify-between mt-1 text-[10px] font-medium tabular-nums" style={{ color: near ? "#dc2626" : "#98A2B3" }}>
            <span>{len.toLocaleString("pt-BR")} caracteres</span>
            <span>{near ? `${pct}% do recomendado` : `recomendado até ${MAX.toLocaleString("pt-BR")}`}</span>
          </div>
        </div>
      </div>
    );
  },
);

RichPromptEditor.displayName = "RichPromptEditor";
