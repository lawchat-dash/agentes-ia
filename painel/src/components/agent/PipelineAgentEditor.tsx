import { useState, useEffect, useRef } from "react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Library, X } from "lucide-react";
import { extractFields, fillField, sanitizeFieldValue } from "@/components/agent/HighlightedTextarea";
import { RichPromptEditor, RichPromptEditorHandle } from "@/components/agent/RichPromptEditor";
import { ROLE_META, AgentRole } from "@/hooks/useProducts";
import { handoffLabelsFor, TOOL_LABELS } from "@/data/handoffTargets";
import { MediaLibrary } from "@/components/agent/MediaLibrary";
import { FeatureGatedButton } from "@/components/common/FeatureGatedButton";
import { usePlanFeatures } from "@/hooks/usePlanFeatures";
import { useBibliotecaMidia } from "@/hooks/useBibliotecaMidia";
import { FraseEntradaCard } from "@/components/agent/FraseEntradaCard";
import { useFrasesTroca } from "@/hooks/useFrasesTroca";
import { fraseDaEtapa } from "@/data/frasesTroca";

interface Props {
  role: AgentRole;
  initialName: string;
  initialWelcome: string;
  initialBlocks: any[];
  initialPromptText?: string | null;
  saving: boolean;
  saved: boolean;
  agentId?: string | null;
  onSave: (payload: { name: string; welcome: string; blocks: any[] }) => Promise<void> | void;
  registerSaveHandler?: (fn: () => Promise<void> | void) => void;
  /** Captura leve (estado, sem rede): chamado ao trocar de agente para não perder edições. */
  onFlush?: (payload: { name: string; welcome: string; blocks: any[] }) => void;
  registerFlushHandler?: (fn: () => void) => void;
  /** Leitura SEM efeito colateral do que está sendo digitado (rascunho local). null = desmontado. */
  registerSnapshotHandler?: (fn: (() => { role: AgentRole; name: string; welcome: string; blocks: any[] }) | null) => void;
  /** Avisa o pai quando o conteúdo difere do original (padrão → personalizado). */
  onDirty?: (role: AgentRole, dirty: boolean) => void;
  /** Cor de destaque da categoria do produto. */
  accent?: string;
  accentTo?: string;
  /** Valores já preenchidos (Edição rápida) para realçar em roxo no prompt. */
  highlights?: string[];
}

export const PipelineAgentEditor = ({
  role,
  initialName,
  initialWelcome,
  initialBlocks,
  initialPromptText,
  saving,
  saved,
  agentId,
  onSave,
  registerSaveHandler,
  onFlush,
  registerFlushHandler,
  registerSnapshotHandler,
  onDirty,
  accent,
  accentTo,
  highlights,
}: Props) => {
  const meta = ROLE_META[role];
  const [name, setName] = useState(initialName);
  const [welcome, setWelcome] = useState(initialWelcome);
  const [freeText, setFreeText] = useState<string>(initialPromptText ?? blocksToText(initialBlocks));
  const [handoffTrigger, setHandoffTrigger] = useState<string>(extractHandoffTrigger(initialBlocks));
  const [libraryOpen, setLibraryOpen] = useState(false);
  // Preenchimento rápido dos campos {{ ... }} do prompt.
  const [fieldDraft, setFieldDraft] = useState<Record<string, string>>({});
  const richRef = useRef<RichPromptEditorHandle>(null);
  const { data: frasesTroca } = useFrasesTroca();

  // Labels dos agentes para o menu @ (handoff), exceto o próprio.
  const handoffOptions = handoffLabelsFor(role);
  // Biblioteca de Mídia (no menu @) — só liberada nos planos com o recurso.
  const midiaLiberada = usePlanFeatures().has("midia");
  // Áudios da biblioteca para o submenu inline do @ (fonte única, sincronizada).
  const { items: midiaItems } = useBibliotecaMidia();

  const promptFields = extractFields(freeText);
  const applyField = (field: string) => {
    const val = sanitizeFieldValue(fieldDraft[field] ?? "");
    if (!val) return;
    setFreeText((t) => fillField(t, field, val));
    setFieldDraft((d) => {
      const n = { ...d };
      delete n[field];
      return n;
    });
  };
  // Excluir o campo {{ }}: remove o token do prompt (para quem não tem esse dado).
  const removeField = (field: string) => {
    setFreeText((t) => fillField(t, field, ""));
    setFieldDraft((d) => { const n = { ...d }; delete n[field]; return n; });
  };

  useEffect(() => {
    setName(initialName);
    setWelcome(initialWelcome);
    setFreeText(initialPromptText ?? blocksToText(initialBlocks));
    setHandoffTrigger(extractHandoffTrigger(initialBlocks));
  }, [role]);

  const buildPayload = () => ({
    name,
    welcome,
    blocks: [
      { id: "freeform", type: "freeform", icon: "📝", label: "Prompt", content: freeText },
      { id: "handoff_trigger", type: "handoff_trigger", icon: "🔀", label: "Gatilho de transferência", content: handoffTrigger },
    ],
  });

  const handleSave = () => onSave(buildPayload());

  useEffect(() => {
    registerSaveHandler?.(handleSave);
    registerFlushHandler?.(() => onFlush?.(buildPayload()));
    registerSnapshotHandler?.(() => ({ role, ...buildPayload() }));
  });
  // Desmontou (trocou de aba/agente): o pai não pode ler um editor que não existe mais.
  useEffect(() => () => registerSnapshotHandler?.(null), []); // eslint-disable-line react-hooks/exhaustive-deps

  // Detecta personalização: compara o conteúdo atual com o original deste agente.
  // (o componente remonta por agente via key={role}, então o ref é por-agente)
  const originalRef = useRef({
    name: initialName,
    welcome: initialWelcome,
    freeText: initialPromptText ?? blocksToText(initialBlocks),
    handoff: extractHandoffTrigger(initialBlocks),
  });
  useEffect(() => {
    const o = originalRef.current;
    const dirty = name.trim() !== o.name.trim() || welcome.trim() !== o.welcome.trim() || freeText.trim() !== o.freeText.trim() || handoffTrigger.trim() !== o.handoff.trim();
    onDirty?.(role, dirty);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name, welcome, freeText, handoffTrigger, role]);

  return (
    <div className="space-y-4">
      <Card className="lc-card p-0 overflow-hidden">
        {/* Identidade do agente */}
        <div className="flex items-center gap-3 p-5">
          <div
            className={`size-12 rounded-2xl grid place-items-center text-white shadow-sm ${accent ? "" : `bg-gradient-to-br ${meta.color}`}`}
            style={accent ? { backgroundImage: `linear-gradient(135deg, ${accent}, ${accentTo ?? accent})` } : undefined}
          >
            <meta.Icon className="size-6" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-[10px] uppercase tracking-wider font-bold" style={{ color: accent ?? "hsl(var(--muted-foreground))" }}>Nome do agente</div>
            <div className="mt-0.5 text-base font-bold text-[#101828] truncate">{name}</div>
          </div>
        </div>

        {/* Prompt */}
        <div className="px-5 pb-5 pt-4 border-t border-[#eef1f5]">
          <div className="flex items-center justify-between mb-2.5 flex-wrap gap-2">
            <div>
              <Label className="text-sm font-semibold text-[#101828]">Prompt do agente</Label>
              <p className="text-xs text-muted-foreground mt-0.5">
                Use a barra para formatar (negrito, títulos, listas). O texto é renderizado.
              </p>
            </div>
            <div className="flex gap-2">
              <FeatureGatedButton
                size="sm"
                variant="outline"
                feature="midia"
                featureLabel="Biblioteca de mídia"
                onAllowed={() => setLibraryOpen(true)}
              >
                <Library className="size-3.5 mr-1.5" />Biblioteca
              </FeatureGatedButton>
            </div>
          </div>

          <RichPromptEditor
            ref={richRef}
            value={freeText}
            onChange={setFreeText}
            handoffOptions={handoffOptions}
            toolOptions={TOOL_LABELS}
            accent={accent}
            onAbrirMidia={() => setLibraryOpen(true)}
            midiaLiberada={midiaLiberada}
            media={midiaItems}
            highlights={highlights}
          />

          {/* Legenda */}
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-[#98A2B3]">
            <span><code className="text-[#7c3aed]">{"{{ }}"}</code> campo (preenche na Edição rápida)</span>
            <span>Digite <code className="text-[#2563eb]">@</code> para passar o lead a outro agente, <strong>acionar uma ferramenta</strong> (buscar CEP, gerar documento) <strong>ou inserir mídia</strong> da Biblioteca</span>
          </div>

          {/* Frases para Transferência deste agente (fixas — só o super admin altera): somente leitura. */}
          <div className="mt-3">
            <FraseEntradaCard role={role} prompt={freeText} />
          </div>

          {/* A frase para transferência da Assinatura (fixa, do super admin) e os campos {{ }} saíram daqui: a frase é
              coisa de admin e os campos já são preenchidos na Edição rápida. */}
        </div>
      </Card>

      <MediaLibrary
        open={libraryOpen}
        onOpenChange={setLibraryOpen}
        onInsert={(token) => richRef.current?.insertText(token)}
      />
    </div>
  );
};

function blocksToText(blocks: any): string {
  if (!Array.isArray(blocks) || blocks.length === 0) return "";
  const freeform = blocks.find((b) => b?.type === "freeform");
  if (freeform) return freeform.content ?? "";
  return blocks
    .filter((b) => b?.type !== "faq" && b?.type !== "objections" && b?.type !== "handoff_trigger")
    .map((b) => {
      const content = Array.isArray(b.content)
        ? b.content.map((c: string) => `- ${c}`).join("\n")
        : (b.content ?? "");
      return `## ${b.label ?? b.type ?? "Bloco"}\n${content}`;
    })
    .join("\n\n");
}

function extractHandoffTrigger(blocks: any): string {
  if (!Array.isArray(blocks)) return "";
  const b = blocks.find((x) => x?.type === "handoff_trigger");
  return (b?.content as string) ?? "";
}

