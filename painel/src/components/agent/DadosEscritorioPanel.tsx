import { useRef, useState } from "react";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Building2 } from "lucide-react";
import { RichPromptEditor, RichPromptEditorHandle } from "@/components/agent/RichPromptEditor";
import { MediaLibrary } from "@/components/agent/MediaLibrary";
import { useBibliotecaMidia } from "@/hooks/useBibliotecaMidia";
import { usePlanFeatures } from "@/hooks/usePlanFeatures";

interface Props {
  value: string;
  onChange: (markdown: string) => void;
  /** Cor de destaque da categoria do produto. */
  accent?: string;
  /** Labels dos agentes (alimenta o menu @ de handoff). */
  handoffOptions?: string[];
  /** Valores já preenchidos na Edição rápida — realça os {{ }} em roxo. */
  highlights?: string[];
}

/**
 * "Dados do Escritório" — bloco de prompt de NÍVEL PRODUTO (vale p/ todos os agentes).
 * Mesmo editor dos agentes (RichPromptEditor): @ (mídia/handoff) e {{ }} (campos).
 * Guardado separado (sistemaia_produtos_ativados.dados_escritorio) e injetado nos
 * prompts na ativação (prompts.dados_escritorio).
 */
export const DadosEscritorioPanel = ({ value, onChange, accent, handoffOptions = [], highlights = [] }: Props) => {
  const { items: midiaItems } = useBibliotecaMidia();
  const midiaLiberada = usePlanFeatures().has("midia");
  const richRef = useRef<RichPromptEditorHandle>(null);
  const [libraryOpen, setLibraryOpen] = useState(false);

  return (
    <Card className="p-6 lc-card space-y-5">
      <div className="flex items-center gap-3">
        <div
          className="size-9 rounded-xl grid place-items-center text-white shrink-0"
          style={{ backgroundColor: accent ?? "#00bc33" }}
        >
          <Building2 className="size-[18px]" />
        </div>
        <div>
          <Label className="text-sm font-semibold text-[#101828]">Dados do Escritório</Label>
          <p className="text-xs text-muted-foreground mt-0.5">
            Informações da firma que o agente usa em qualquer etapa — nome, endereço, horários,
            áreas de atuação, formas de contato. Vale para todos os agentes.
          </p>
        </div>
      </div>

      <RichPromptEditor
        ref={richRef}
        value={value}
        onChange={onChange}
        handoffOptions={handoffOptions}
        onAbrirMidia={() => setLibraryOpen(true)}
        midiaLiberada={midiaLiberada}
        media={midiaItems}
        highlights={highlights}
      />

      <MediaLibrary
        open={libraryOpen}
        onOpenChange={setLibraryOpen}
        onInsert={(token) => richRef.current?.insertText(token)}
      />
    </Card>
  );
};
