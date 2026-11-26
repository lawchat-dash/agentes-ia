import { useRef, useState } from "react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Library, Repeat, RotateCcw, Sparkles } from "lucide-react";
import { MediaLibrary } from "@/components/agent/MediaLibrary";
import { RichPromptEditor, RichPromptEditorHandle } from "@/components/agent/RichPromptEditor";
import { extractFields, fillField, sanitizeFieldValue } from "@/components/agent/HighlightedTextarea";
import { useBibliotecaMidia } from "@/hooks/useBibliotecaMidia";
import { usePlanFeatures } from "@/hooks/usePlanFeatures";
import { CrmStage, STAGE_LABELS, FollowupAgentConfig } from "@/hooks/useFollowups";

interface Props {
  stage: CrmStage;
  value: FollowupAgentConfig;
  onChange: (next: FollowupAgentConfig) => void;
  /** Padrão herdado do produto-mãe (template). Habilita badge "Herdado" e botão "Restaurar padrão". */
  templateDefault?: { agent_name: string; prompt: string };
  /** Labels dos OUTROS agentes de follow-up — alimenta o menu @ (handoff). */
  handoffOptions?: string[];
  /** Valores já preenchidos (Edição rápida global) — realça em roxo no prompt. */
  highlights?: string[];
  /** Cor de destaque do PRODUTO (categoria) — continuidade visual com o agente. */
  accent?: string;
}

export const FollowupAgentEditor = ({ stage, value, onChange, templateDefault, handoffOptions = [], highlights = [], accent }: Props) => {
  const { items: midiaItems } = useBibliotecaMidia();
  const midiaLiberada = usePlanFeatures().has("midia");
  const hasTemplate = !!(templateDefault && (templateDefault.prompt?.trim() || templateDefault.agent_name?.trim()));
  const isInherited =
    hasTemplate &&
    value.prompt.trim() === (templateDefault?.prompt ?? "").trim() &&
    value.name.trim() === (templateDefault?.agent_name ?? "").trim();
  const restoreFromTemplate = () => {
    if (!templateDefault) return;
    onChange({
      name: templateDefault.agent_name || value.name,
      prompt: templateDefault.prompt || value.prompt,
    });
    setEditorVersion((n) => n + 1); // remonta o editor com o texto restaurado
  };

  const richRef = useRef<RichPromptEditorHandle>(null);
  const [libraryOpen, setLibraryOpen] = useState(false);
  // Preenchimento rápido dos campos {{ ... }} deste agente.
  const [fieldDraft, setFieldDraft] = useState<Record<string, string>>({});
  // Bump força remontar o RichPromptEditor quando o texto muda por fora (aplicar campo / restaurar).
  const [editorVersion, setEditorVersion] = useState(0);

  const promptFields = extractFields(value.prompt);
  const applyField = (field: string) => {
    const val = sanitizeFieldValue(fieldDraft[field] ?? "");
    if (!val) return;
    onChange({ ...value, prompt: fillField(value.prompt, field, val) });
    setFieldDraft((d) => { const n = { ...d }; delete n[field]; return n; });
    setEditorVersion((n) => n + 1);
  };

  return (
    <div className="space-y-4">
      <Card className="lc-card p-0 overflow-hidden">
        {/* Identidade do agente — atrelada ao produto (nome não é editável aqui) */}
        <div className="flex items-center gap-3 p-5">
          <div
            className="size-12 rounded-2xl grid place-items-center text-white shadow-sm shrink-0"
            style={accent ? { backgroundImage: `linear-gradient(135deg, ${accent}, ${accent}b3)` } : undefined}
          >
            <Repeat className="size-6" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-[10px] uppercase tracking-wider font-bold" style={{ color: accent ?? "hsl(var(--success))" }}>
              Follow-up da etapa
            </div>
            <div className="mt-0.5 flex items-center gap-2 flex-wrap">
              <div className="text-base font-bold text-[#101828] truncate">{STAGE_LABELS[stage]}</div>
              {isInherited && (
                <Badge variant="outline" className="bg-success/5 border-success/30 text-success text-[10px] h-5">
                  <Sparkles className="size-2.5 mr-1" />
                  Herdado do produto-mãe
                </Badge>
              )}
              {hasTemplate && !isInherited && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-6 px-2 text-[10px] text-muted-foreground hover:text-success"
                  onClick={restoreFromTemplate}
                >
                  <RotateCcw className="size-3 mr-1" />
                  Restaurar padrão
                </Button>
              )}
            </div>
          </div>
        </div>

        {/* Prompt */}
        <div className="px-5 pb-5 pt-4 border-t border-[#eef1f5]">
          <div className="flex items-center justify-between mb-2.5 flex-wrap gap-2">
            <div>
              <Label className="text-sm font-semibold text-[#101828]">
                Prompt de Follow-Up · {STAGE_LABELS[stage]}
              </Label>
              <p className="text-xs text-muted-foreground mt-0.5">
                Texto usado quando o lead não responder. Use a barra para formatar (negrito, títulos, listas).
              </p>
            </div>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => setLibraryOpen(true)}
            >
              <Library className="size-3.5 mr-1.5" />
              Biblioteca
            </Button>
          </div>

          <RichPromptEditor
            key={`${stage}-${editorVersion}`}
            ref={richRef}
            value={value.prompt}
            onChange={(markdown) => onChange({ ...value, prompt: markdown })}
            handoffOptions={handoffOptions}
            onAbrirMidia={() => setLibraryOpen(true)}
            midiaLiberada={midiaLiberada}
            media={midiaItems}
            highlights={highlights}
          />

          {/* Legenda */}
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-[#98A2B3]">
            <span><code className="text-[#7c3aed]">{"{{ }}"}</code> campo (preenche na Edição rápida)</span>
            {handoffOptions.length > 0 && (
              <span><code className="text-[#2563eb]">@agente</code> passa o lead adiante (use o botão Handoff)</span>
            )}
            <span>Digite <code className="text-[#2563eb]">@</code> para inserir <strong className="text-[#475467] font-semibold">mídia</strong> (áudio/vídeo/imagem) da Biblioteca</span>
          </div>

          {/* Preenchimento rápido dos campos {{ ... }} deste agente */}
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
