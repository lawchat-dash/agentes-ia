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

          {/* Só no agente de Assinatura: mensagem → prompts.mensagem_troca. Com frase para transferência
              cadastrada (super admin), o campo aparece PREENCHIDO com ela e travado — é ela que vai
              para o bot. Sem frase, volta a ser editável. */}
          {role === "assinatura" && (() => {
            const fixa = fraseDaEtapa("assinatura", frasesTroca ?? []);
            return (
              <div className="mt-3 rounded-xl border border-success/25 bg-success/5 p-3.5">
                <div className="flex items-center gap-1.5 flex-wrap">
                  <Label className="text-[11px] font-bold uppercase tracking-wider text-success">
                    Frase para Transferência
                  </Label>
                  <span className="text-[9px] font-bold uppercase tracking-wider rounded-full px-1.5 py-0.5 bg-success/15 text-success">
                    {fixa ? "Frase fixa · super admin" : "Obrigatório"}
                  </span>
                </div>
                <p className="text-[11px] text-muted-foreground mt-1 mb-2">
                  {fixa
                    ? "Preenchida pela frase para transferência da Assinatura, definida pelo super admin — é ela que vai para o bot."
                    : "Frase que passa o lead para a Assinatura (vai para a mensagem_troca). Se deixar em branco, usamos uma mensagem padrão — nunca fica vazio."}
                </p>
                <Textarea
                  value={fixa ? fixa.frase : handoffTrigger}
                  onChange={(e) => { if (!fixa) setHandoffTrigger(e.target.value); }}
                  readOnly={!!fixa}
                  rows={3}
                  placeholder="Ex.: Acabamos de confirmar a assinatura do seu contrato 🎉 Nosso Setor Operacional vai continuar o seu atendimento, então já salva esse contato…"
                  className={`text-sm ${fixa ? "bg-muted/40 cursor-not-allowed" : "bg-white"}`}
                />
              </div>
            );
          })()}

          {/* Preenchimento rápido dos campos {{ ... }} */}
          {promptFields.length > 0 && (
            <div className="mt-3 rounded-xl border border-[#ece9fb] bg-[#faf8ff] p-3">
              <div className="flex items-center gap-1.5">
                <span className="text-[11px] font-bold uppercase tracking-wider text-[#7c3aed]">Campos para preencher</span>
                <span className="text-[10px] font-bold rounded-full px-1.5 py-0.5 bg-[#ede9fe] text-[#7c3aed]">{promptFields.length}</span>
              </div>
              <p className="text-[11px] text-[#98A2B3] mt-1 mb-2.5">
                Tudo que está em <code className="text-[#7c3aed]">{"{{ }}"}</code> no prompt. Preencha aqui e o valor substitui no texto.
              </p>
              <div className="space-y-1.5">
                {promptFields.map((f) => (
                  <div key={f} className="flex items-center gap-2">
                    <code className="shrink-0 max-w-[38%] truncate rounded px-1.5 py-1 text-[11px] font-medium text-[#7c3aed] bg-[#ede9fe]" title={`{{${f}}}`}>{`{{${f}}}`}</code>
                    <Input
                      value={fieldDraft[f] ?? ""}
                      onChange={(e) => setFieldDraft((d) => ({ ...d, [f]: e.target.value }))}
                      onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); applyField(f); } }}
                      placeholder="valor…"
                      className="h-8 text-sm bg-white"
                    />
                    <Button size="sm" variant="outline" className="h-8 shrink-0" disabled={!(fieldDraft[f] ?? "").trim()} onClick={() => applyField(f)}>
                      Aplicar
                    </Button>
                    <Button size="sm" variant="ghost" className="h-8 shrink-0 px-2 text-[#98A2B3] hover:text-[#dc2626] hover:bg-[#fef2f2]" title="Remover este campo do prompt (para quem não tem esse dado)" onClick={() => removeField(f)}>
                      <X className="size-3.5" />
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          )}
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

