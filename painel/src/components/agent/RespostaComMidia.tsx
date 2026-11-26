import { useRef, useState } from "react";
import { RichPromptEditor, RichPromptEditorHandle } from "./RichPromptEditor";
import { MediaLibrary } from "./MediaLibrary";
import { useBibliotecaMidia } from "@/hooks/useBibliotecaMidia";
import { usePlanFeatures } from "@/hooks/usePlanFeatures";
import { HANDOFF_LABELS, TOOL_LABELS } from "@/data/handoffTargets";

interface Props {
  value: string;
  onChange: (v: string) => void;
  /** Valores {{ }} já preenchidos (realce). */
  highlights?: string[];
  /** Labels dos agentes p/ o menu @ (handoff). Default = todos os agentes. */
  handoffOptions?: string[];
  /** Mostra a opção de MÍDIA no menu @ (só produto com mídia). */
  showMidia?: boolean;
  accent?: string;
  /** Aceitos por compat com os callers (o RichPromptEditor tem estilo/altura próprios). */
  placeholder?: string;
  className?: string;
}

/**
 * Resposta de FAQ / Objeção com o MESMO editor dos prompts (RichPromptEditor): menu "@"
 * completo — @Agente (handoff), ferramentas (buscar CEP / ZapSign) e mídia (áudio/vídeo) —
 * além do realce de {{ }} / @ / mídia. Usado no admin e no cliente. Antes as objeções/FAQ
 * usavam textarea simples, sem o menu @; agora têm a mesma experiência do prompt.
 */
export const RespostaComMidia = ({ value, onChange, highlights, handoffOptions = HANDOFF_LABELS, showMidia, accent }: Props) => {
  const richRef = useRef<RichPromptEditorHandle>(null);
  const { items: midiaItems } = useBibliotecaMidia();
  const midiaLiberada = usePlanFeatures().has("midia");
  const [libraryOpen, setLibraryOpen] = useState(false);

  return (
    <>
      <RichPromptEditor
        ref={richRef}
        value={value}
        onChange={onChange}
        handoffOptions={handoffOptions}
        toolOptions={TOOL_LABELS}
        onAbrirMidia={showMidia ? () => setLibraryOpen(true) : undefined}
        midiaLiberada={midiaLiberada}
        media={showMidia ? midiaItems : undefined}
        highlights={highlights}
        accent={accent}
        minHeight="min-h-[96px]"
        compact
      />
      {showMidia && (
        <MediaLibrary
          open={libraryOpen}
          onOpenChange={setLibraryOpen}
          onInsert={(token) => richRef.current?.insertText(token)}
        />
      )}
    </>
  );
};
