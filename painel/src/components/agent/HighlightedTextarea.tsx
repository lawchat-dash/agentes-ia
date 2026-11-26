import { forwardRef, useRef } from "react";
import { cn } from "@/lib/utils";

/** [[midia:nome]] / [[audio|video:nome]] (ciano), {{ campo }} (roxo) ou @tag (azul) no split.
 *  Aceita QUALQUER mídia (áudio/vídeo/imagem) — o marcador vira um link, não só áudio. */
const MIDIA_PREFIXO = "(?:[aá]udio|v[ií]deo|m[ií]dia|media|imagem)";
const TOKEN_ALT = `\\[\\[${MIDIA_PREFIXO}:[^\\]]*\\]\\]|\\{\\{[^}]*\\}\\}|(?<![\\wÀ-ÿ])@[A-Za-zÀ-ÿ][\\wÀ-ÿ]*`;
const TOKEN_SPLIT = new RegExp(`(${TOKEN_ALT})`, "g");

const isAction = (p: string) => p.startsWith("@");
const isAudioMarker = (p: string) => new RegExp(`^\\[\\[\\s*${MIDIA_PREFIXO}:`, "i").test(p);

interface Props {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  /** Classe extra do textarea (altura, etc). */
  className?: string;
  onDrop?: (e: React.DragEvent<HTMLTextAreaElement>) => void;
  onDragOver?: (e: React.DragEvent<HTMLTextAreaElement>) => void;
  onKeyDown?: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  /** Valores já preenchidos (de campos {{ }}) que devem aparecer em roxo no texto. */
  highlights?: string[];
  /** Limite de caracteres do textarea. */
  maxLength?: number;
}

/**
 * Textarea com realce dos campos {{ ... }} numa cor diferente.
 * Técnica: um "backdrop" atrás do textarea renderiza o mesmo texto, com os
 * tokens coloridos. O textarea fica por cima com texto transparente (só o cursor
 * aparece). O realce usa SÓ cor (sem fundo/peso) para não mudar a métrica das
 * letras e manter o alinhamento perfeito com o que é digitado.
 */
export const HighlightedTextarea = forwardRef<HTMLTextAreaElement, Props>(
  ({ value, onChange, placeholder, className, onDrop, onDragOver, onKeyDown, maxLength }, ref) => {
    const backdropRef = useRef<HTMLDivElement>(null);

    const syncScroll = (e: React.UIEvent<HTMLTextAreaElement>) => {
      const b = backdropRef.current;
      if (b) {
        b.scrollTop = e.currentTarget.scrollTop;
        b.scrollLeft = e.currentTarget.scrollLeft;
      }
    };

    // mesma base tipográfica/caixa nos dois elementos → alinhamento exato.
    // line-height em PX inteiro (não 1.7) evita arredondamento diferente entre
    // <textarea> e <div>, que acumula desalinhamento linha a linha.
    const base = "w-full rounded-xl border px-3 py-2 text-[13.5px] leading-[23px] font-sans whitespace-pre-wrap break-words tracking-normal";
    // Realça SOMENTE os tokens reais: {{ campo }} (roxo) e @tag (azul). NÃO pinta valores
    // já preenchidos como substring solta — isso coloria palavras normais ("antes", "de
    // clientes") e atrapalhava a seleção. Valor preenchido vira texto normal (correto).
    const parts = value.split(TOKEN_SPLIT);
    const isField = (p: string) => p.startsWith("{{") && p.endsWith("}}");

    return (
      <div className="relative">
        <div
          ref={backdropRef}
          aria-hidden
          style={{ scrollbarGutter: "stable" }}
          className={cn(
            base,
            "pointer-events-none absolute inset-0 overflow-y-auto overflow-x-hidden border-transparent bg-[#fafbfc] text-[#1d2433]",
            className,
          )}
        >
          {parts.map((p, i) =>
            p && isAudioMarker(p) ? (
              <span key={i} className="text-[#0891b2] font-medium">{p}</span>
            ) : p && isAction(p) ? (
              <span key={i} className="text-[#2563eb]">{p}</span>
            ) : p && isField(p) ? (
              <span key={i} className="text-[#7c3aed]">{p}</span>
            ) : (
              <span key={i}>{p}</span>
            ),
          )}
          {/* garante que a última linha (newline final) tenha altura */}
          {"​"}
        </div>
        <textarea
          ref={ref}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onScroll={syncScroll}
          onDrop={onDrop}
          onDragOver={onDragOver}
          onKeyDown={onKeyDown}
          placeholder={placeholder}
          maxLength={maxLength}
          spellCheck
          style={{ scrollbarGutter: "stable" }}
          className={cn(
            base,
            "relative resize-y overflow-y-auto overflow-x-hidden border-input bg-transparent text-transparent caret-[#1d2433] selection:text-transparent outline-none ring-offset-background placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
            className,
          )}
        />
      </div>
    );
  },
);

HighlightedTextarea.displayName = "HighlightedTextarea";

/** Extrai os nomes únicos de campos {{ ... }} de um texto, na ordem de aparição. */
export function extractFields(text: string): string[] {
  const re = /\{\{\s*([^}]+?)\s*\}\}/g;
  const seen = new Set<string>();
  const out: string[] = [];
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    const name = m[1].trim();
    if (name && !seen.has(name)) {
      seen.add(name);
      out.push(name);
    }
  }
  return out;
}

/** Extrai o inner ÚNICO (prefixo:nome) dos marcadores de mídia [[midia|audio|video:nome]].
 *  TOLERANTE ao escape do markdown (\[\[...\]\]): o editor rico escapa colchetes ao salvar.
 *  Devolve o inner completo (ex.: "audio:Video Inicial") pra a edição rápida achar/trocar o exato. */
export function extractAudios(text: string): string[] {
  const re = /\\?\[\\?\[\s*((?:[aá]udio|v[ií]deo|m[ií]dia|media|imagem):\s*[^\]\\]+?)\s*\\?\]\\?\]/gi;
  const seen = new Set<string>();
  const out: string[] = [];
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    const inner = m[1].replace(/\s*:\s*/, ":").trim(); // normaliza "audio : X" → "audio:X"
    if (inner && !seen.has(inner)) {
      seen.add(inner);
      out.push(inner);
    }
  }
  return out;
}

/** Normaliza os marcadores de mídia pra forma LIMPA [[prefixo:nome]] (des-escapa \[\[...\]\]). */
export const normalizeAudioMarkers = (text: string): string =>
  text.replace(/\\?\[\\?\[\s*((?:[aá]udio|v[ií]deo|m[ií]dia|media|imagem):[^\]\\]+?)\s*\\?\]\\?\]/gi, "[[$1]]");

/** Marcador de mídia pronto pra inserir (botão do editor e edição rápida). Genérico: [[midia:nome]]. */
export const audioMarker = (nome: string): string => `[[midia:${nome}]]`;

const escapeRegExp = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Substitui todas as ocorrências de {{ campo }} (com espaços variados) por um valor. */
/**
 * Validação leve do valor de um campo {{ }} antes de aplicar no prompt: remove
 * caracteres de controle/quebras, apara espaços e limita o tamanho (evita colar blocos
 * gigantes). NÃO há risco de "injeção" — o valor é só texto no prompt, nunca vai pra SQL.
 */
export const sanitizeFieldValue = (v: string): string =>
  String(v ?? "").replace(/\s+/g, " ").trim().slice(0, 500);

export function fillField(text: string, field: string, value: string): string {
  const re = new RegExp(`\\{\\{\\s*${escapeRegExp(field)}\\s*\\}\\}`, "g");
  // Função de replacement (não string) p/ o valor entrar LITERAL: senão "$$", "$&", "$`", "$'"
  // no valor do usuário viram padrões especiais do String.replace e corrompem o texto salvo.
  return text.replace(re, () => value);
}
