import { useState } from "react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Headphones, Music, Library, Trash2 } from "lucide-react";
import { MediaLibrary } from "./MediaLibrary";

/** Token do MediaLibrary.onInsert é "[tipo:nome](url)" — extrai a URL de QUALQUER mídia
 *  (áudio, vídeo ou imagem). O marcador vira o link inline; o bot envia qualquer mídia do @. */
const urlDoToken = (token: string): string | null => {
  const m = token.match(/\]\(([^)]+)\)/); // pega a url dentro de ...](url)
  if (m) return m[1].trim();
  // fallback: token pode ser a URL pura
  const t = token.trim();
  return /^https?:\/\//.test(t) ? t : null;
};

interface Props {
  /** Marcadores [[midia:nome]] (prefixo:nome) ainda NÃO preenchidos, achados em todos os textos. */
  markers: string[];
  /** Escolheu a mídia → troca [[prefixo:nome]] pela URL no prompt (igual @ → Biblioteca). */
  onFill: (marker: string, url: string) => void;
  /** Excluir → remove o marcador dos textos (pra quem não tem essa mídia). */
  onRemove: (marker: string) => void;
}

/**
 * Edição rápida de ÁUDIOS: lista cada [[audio:nome]] do funil e, ao escolher o áudio na biblioteca
 * de mídia, TROCA o marcador pelo LINK direto no prompt (o bot envia o link, igual o @). Espelha a
 * "Edição rápida de Prompt" ({{ }} → valor).
 */
export const AudioSlotsPanel = ({ markers, onFill, onRemove }: Props) => {
  const [picking, setPicking] = useState<string | null>(null); // marcador em escolha

  return (
    <Card className="lc-card p-5 space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2 min-w-0">
          <div className="size-9 rounded-lg grid place-items-center bg-cyan-500/10 text-cyan-600 shrink-0">
            <Headphones className="size-4" />
          </div>
          <div className="min-w-0">
            <h3 className="font-semibold text-foreground flex items-center gap-2">
              Edição rápida de mídias
              <Badge className="bg-cyan-500/10 text-cyan-600 border-cyan-500/30 text-[11px]">Mídia</Badge>
            </h3>
            <p className="text-xs text-muted-foreground">
              Escolha a mídia (áudio ou vídeo) de cada <code className="text-cyan-600 font-medium">[[midia:nome]]</code> — ela vira o <strong>link</strong> direto no prompt.
            </p>
          </div>
        </div>
        {markers.length > 0 && <Badge variant="outline" className="text-[11px]">{markers.length} pendente{markers.length > 1 ? "s" : ""}</Badge>}
      </div>

      {markers.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border p-6 text-center">
          <div className="size-10 rounded-xl bg-muted grid place-items-center mx-auto mb-2 text-muted-foreground"><Music className="size-5" /></div>
          <p className="text-sm text-muted-foreground">Nenhum marcador de áudio pendente.</p>
          <p className="text-[12px] text-muted-foreground mt-1">
            No prompt, clique no botão <strong>🎵 (mídia)</strong> do editor (ou digite <code className="text-cyan-600">[[midia:nome]]</code>) onde quiser que o agente envie uma mídia.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {markers.map((mk) => (
            <div key={mk} className="rounded-xl border border-border/60 bg-muted/20 p-3 flex items-center justify-between gap-3 flex-wrap">
              <div className="flex items-center gap-2 min-w-0">
                <div className="size-7 rounded-lg grid place-items-center shrink-0 bg-cyan-500/10 text-cyan-600"><Headphones className="size-3.5" /></div>
                <code className="text-[13px] font-semibold text-foreground truncate">{`[[${mk}]]`}</code>
              </div>
              <div className="flex items-center gap-1.5 shrink-0">
                <button
                  type="button"
                  onClick={() => onRemove(mk)}
                  className="size-8 grid place-items-center rounded-lg text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors"
                  title="Excluir marcador (não tenho essa mídia)"
                >
                  <Trash2 className="size-4" />
                </button>
                <Button
                  type="button"
                  size="sm"
                  className="gap-1.5 bg-cyan-600 hover:bg-cyan-600/90 text-white"
                  onClick={() => setPicking(mk)}
                >
                  <Library className="size-3.5" />
                  Escolher da biblioteca
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Popup real da biblioteca de mídia — ao escolher, troca o marcador pela URL */}
      <MediaLibrary
        open={!!picking}
        onOpenChange={(o) => { if (!o) setPicking(null); }}
        onInsert={(token) => {
          const url = urlDoToken(token);
          if (picking && url) onFill(picking, url);
          setPicking(null);
        }}
      />
    </Card>
  );
};
