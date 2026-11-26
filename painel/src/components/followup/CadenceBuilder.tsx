import { Reorder, useDragControls } from "framer-motion";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Plus, Trash2, Clock, ChevronDown, MessageCircle, Send,
  Hourglass, Lightbulb, Smartphone, GripVertical,
} from "lucide-react";
import {
  DELAY_OPTIONS,
  FollowupCadenceItem,
  delayLabel,
} from "@/hooks/useFollowups";
import { cn } from "@/lib/utils";

interface Props {
  value: FollowupCadenceItem[];
  onChange: (next: FollowupCadenceItem[]) => void;
}

const MAX_POINTS = 5;
const ORDINALS = ["Primeira", "Segunda", "Terceira", "Quarta", "Quinta"];

// Identidade estável por item (objeto) — alimenta a key do Reorder sem alterar
// o shape salvo ({order, delay}). Mantida enquanto o objeto existir.
const _uidMap = new WeakMap<object, string>();
let _uidSeq = 0;
const getUid = (item: object) => {
  let id = _uidMap.get(item);
  if (!id) { id = `cad-${++_uidSeq}`; _uidMap.set(item, id); }
  return id;
};

const delayToMin = (d: string): number => {
  const m = /^(\d+)(m|h|d)$/.exec(d);
  if (!m) return 0;
  const n = parseInt(m[1], 10);
  return m[2] === "d" ? n * 1440 : m[2] === "h" ? n * 60 : n;
};

const fmtDuration = (min: number): string => {
  const d = Math.floor(min / 1440);
  const h = Math.floor((min % 1440) / 60);
  const mm = min % 60;
  const parts: string[] = [];
  if (d) parts.push(`${d} dia${d > 1 ? "s" : ""}`);
  if (h) parts.push(`${h} h`);
  if (mm) parts.push(`${mm} min`);
  if (parts.length === 0) return "0 min";
  if (parts.length === 1) return parts[0];
  if (parts.length === 2) return `${parts[0]} e ${parts[1]}`;
  return `${parts[0]}, ${parts[1]} e ${parts[2]}`;
};

const shortDelay = (d: string): string => {
  const m = /^(\d+)(m|h|d)$/.exec(d);
  if (!m) return delayLabel(d);
  const n = parseInt(m[1], 10);
  return m[2] === "d" ? `${n} dia${n > 1 ? "s" : ""}` : m[2] === "h" ? `${n} h` : `${n} min`;
};

const pad = (n: number) => String(n).padStart(2, "0");
// Prévia ancorada em 14:00 (ponto de partida ilustrativo).
const previewTime = (cumMin: number) => {
  const total = 14 * 60 + cumMin;
  const dayOffset = Math.floor(total / 1440);
  const tod = total % 1440;
  const time = `${pad(Math.floor(tod / 60))}:${pad(tod % 60)}`;
  const day = dayOffset === 0 ? null : dayOffset === 1 ? "Amanhã" : `+${dayOffset}d`;
  return { time, day };
};

/** Popover para escolher o intervalo de uma etapa. */
const DelayPicker = ({ delay, onSelect, children }: { delay: string; onSelect: (d: string) => void; children: React.ReactNode }) => (
  <Popover>
    <PopoverTrigger asChild>{children}</PopoverTrigger>
    <PopoverContent className="p-2 w-56 max-h-72 overflow-y-auto" align="end">
      <div className="grid grid-cols-2 gap-1">
        {DELAY_OPTIONS.map((o) => (
          <button
            key={o.value}
            onClick={() => onSelect(o.value)}
            className={cn(
              "text-xs px-2 py-1.5 rounded-md text-left transition-colors hover:bg-accent",
              delay === o.value && "bg-foreground text-background hover:bg-foreground",
            )}
          >
            {o.label}
          </button>
        ))}
      </div>
    </PopoverContent>
  </Popover>
);

/** Uma etapa da cadência — arrastável pelo grip. */
const CadenceStep = ({
  item, idx, onSetDelay, onRemove,
}: { item: FollowupCadenceItem; idx: number; onSetDelay: (d: string) => void; onRemove: () => void }) => {
  const controls = useDragControls();
  return (
    <Reorder.Item
      as="div"
      value={item}
      dragListener={false}
      dragControls={controls}
      whileDrag={{ scale: 1.015, boxShadow: "0 16px 40px -12px rgba(15,23,42,0.22)" }}
      className="rounded-2xl border border-border bg-card shadow-sm"
    >
      <div className="flex items-center gap-3 p-3">
        {/* Grip de arrastar */}
        <button
          type="button"
          onPointerDown={(e) => controls.start(e)}
          className="shrink-0 -ml-1 p-1 rounded-md text-muted-foreground/45 hover:text-muted-foreground hover:bg-muted cursor-grab active:cursor-grabbing touch-none"
          title="Arraste para reordenar"
          aria-label="Reordenar etapa"
        >
          <GripVertical className="size-5" />
        </button>

        {/* Número */}
        <div className="size-8 rounded-full grid place-items-center text-sm font-bold text-background bg-foreground shrink-0">
          {idx + 1}
        </div>

        {/* Identificação */}
        <div className="min-w-0 flex-1">
          <div className="font-bold text-sm truncate">{ORDINALS[idx] ?? `${idx + 1}ª`} tentativa</div>
          <span className="inline-flex items-center gap-1 mt-1 text-[10px] font-semibold text-success bg-success/10 rounded-md px-1.5 py-0.5">
            <MessageCircle className="size-3" /> WhatsApp
          </span>
        </div>

        {/* Enviar após (clicável) */}
        <div className="text-right shrink-0">
          <div className="text-[10px] uppercase tracking-wider font-bold text-muted-foreground">Enviar após</div>
          <DelayPicker delay={item.delay} onSelect={onSetDelay}>
            <button
              type="button"
              className="mt-0.5 inline-flex items-center gap-1.5 font-bold text-base tabular-nums text-success rounded-md px-1.5 -mx-1.5 py-0.5 hover:bg-success/10 transition-colors"
              title="Alterar intervalo"
            >
              <Clock className="size-4" />
              {delayLabel(item.delay)}
              <ChevronDown className="size-3.5 opacity-60" />
            </button>
          </DelayPicker>
        </div>

        {/* Remover */}
        <Button
          variant="ghost"
          size="icon"
          className="size-8 shrink-0 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
          onClick={onRemove}
          title="Remover etapa"
        >
          <Trash2 className="size-4" />
        </Button>
      </div>
    </Reorder.Item>
  );
};

export const CadenceBuilder = ({ value, onChange }: Props) => {
  const setDelay = (idx: number, delay: string) => {
    const next = [...value];
    next[idx] = { ...next[idx], delay };
    onChange(next);
  };
  const remove = (idx: number) => onChange(value.filter((_, i) => i !== idx));
  const add = () => {
    if (value.length >= MAX_POINTS) return;
    const lastDelay = value.length ? value[value.length - 1].delay : "1h";
    onChange([...value, { order: value.length + 1, delay: lastDelay }]);
  };

  // Cada intervalo conta a partir da ÚLTIMA INTERAÇÃO do lead (não é cumulativo), então
  // o "tempo total da sequência" é o MAIOR intervalo (quando a última msg dispara), não a
  // soma. Ex.: 1h/6h/24h/3d/15d → total 15 dias (não 19d7h).
  const totalMin = value.length ? Math.max(...value.map((c) => delayToMin(c.delay))) : 0;
  const firstDelay = value[0]?.delay;
  const lastDelay = value[value.length - 1]?.delay;

  // Cada etapa dispara a partir do MESMO ponto (última interação do lead), não em
  // cascata — então a prévia usa o delay direto de cada etapa, não o acumulado.
  const previewSteps = value.map((c) => ({ delay: c.delay, min: delayToMin(c.delay) }));

  return (
    <div className="space-y-5">
      {/* Resumo da cadência — largura total no topo */}
      <Card className="lc-card relative overflow-hidden p-5">
        <div className="flex items-center gap-2 mb-4">
          <div className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">Resumo da cadência</div>
          <div className="h-px flex-1 bg-border" />
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-5">
          <ResumoItem Icon={Clock} label="Primeira mensagem" value={firstDelay ? delayLabel(firstDelay) : "—"} sub="após interação" />
          <ResumoItem Icon={Clock} label="Última mensagem" value={lastDelay ? delayLabel(lastDelay) : "—"} sub="após interação" />
          <ResumoItem Icon={Hourglass} label="Tempo total" value={value.length ? fmtDuration(totalMin) : "—"} sub="de sequência" />
          <ResumoItem Icon={Smartphone} label="Canal" value="WhatsApp" sub="automático" accent />
        </div>
      </Card>

      <div className="grid lg:grid-cols-[1fr_320px] gap-5 items-start">
        {/* ============ COLUNA PRINCIPAL ============ */}
        <div className="space-y-6 min-w-0">
        {/* Sequência de mensagens */}
        <div>
          <div className="flex items-center justify-between mb-1.5 gap-2">
            <h3 className="text-base font-bold tracking-tight">Sequência de mensagens</h3>
            <Button variant="outline" size="sm" onClick={add} disabled={value.length >= MAX_POINTS} className="shadow-sm">
              <Plus className="size-4 mr-1.5" /> Nova etapa
            </Button>
          </div>
          <p className="text-xs text-muted-foreground mb-4 inline-flex items-center gap-1.5">
            <GripVertical className="size-3.5 opacity-60" />
            Arraste pelo punho para reordenar · toque no horário para mudar o intervalo
          </p>

          {value.length === 0 ? (
            <Card className="p-8 text-center border-dashed">
              <p className="text-sm text-muted-foreground">Nenhuma etapa ainda. Adicione o primeiro ponto de contato.</p>
              <Button variant="outline" className="mt-3" onClick={add}>
                <Plus className="size-4 mr-1.5" /> Adicionar etapa
              </Button>
            </Card>
          ) : (
            <Reorder.Group as="div" axis="y" values={value} onReorder={onChange} className="space-y-2">
              {value.map((item, idx) => (
                <CadenceStep
                  key={getUid(item)}
                  item={item}
                  idx={idx}
                  onSetDelay={(d) => setDelay(idx, d)}
                  onRemove={() => remove(idx)}
                />
              ))}
            </Reorder.Group>
          )}

          {value.length > 0 && value.length < MAX_POINTS && (
            <button
              onClick={add}
              className="w-full mt-2 rounded-2xl border border-dashed border-border bg-muted/30 py-3 text-sm font-medium text-muted-foreground transition-colors hover:border-foreground/25 hover:text-foreground hover:bg-muted/50 flex items-center justify-center gap-1.5"
            >
              <Plus className="size-4" /> Adicionar nova etapa
            </button>
          )}
        </div>

        {/* Como funciona */}
        <details className="group rounded-2xl border border-border bg-card shadow-sm">
          <summary className="cursor-pointer list-none flex items-center justify-between p-4">
            <span className="flex items-center gap-2 text-sm font-semibold">
              <Lightbulb className="size-4 text-success" /> Como funciona?
            </span>
            <ChevronDown className="size-4 text-muted-foreground transition-transform duration-200 group-open:rotate-180" />
          </summary>
          <div className="px-4 pb-4 text-xs text-muted-foreground space-y-2 leading-relaxed">
            <p>
              As mensagens são disparadas em sequência. Cada <strong>"enviar após"</strong> conta a partir do
              envio anterior — a ordem em que as etapas aparecem é a ordem em que saem.
            </p>
            <p>
              Se o lead responder durante a cadência, o ciclo é{" "}
              <strong className="text-foreground">reiniciado automaticamente</strong> — os próximos follow-ups
              voltam a contar a partir da nova última mensagem.
            </p>
          </div>
        </details>
      </div>

        {/* ============ COLUNA LATERAL ============ */}
        <div className="lg:sticky lg:top-4 space-y-5">
          {/* Prévia da automação */}
          <Card className="lc-card relative overflow-hidden p-5">
            <div className="flex items-center gap-2 mb-4">
              <div className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">Prévia da automação</div>
              <div className="h-px flex-1 bg-border" />
            </div>
            <div className="relative">
              <div className="absolute left-[58px] top-3 bottom-3 w-px bg-border" aria-hidden />
              <div className="space-y-3.5">
                <PreviewRow time="14:00" Icon={MessageCircle} title="Lead enviou mensagem" sub="Ponto de partida" accent />
                {previewSteps.map((s, i) => {
                  const { time, day } = previewTime(s.min);
                  return (
                    <PreviewRow
                      key={i}
                      time={day ? `${time} ${day}` : time}
                      Icon={Send}
                      title={`Etapa ${i + 1}`}
                      badge={`${shortDelay(s.delay)} após`}
                    />
                  );
                })}
              </div>
            </div>
          </Card>

          {/* Dicas para melhores resultados */}
          <Card className="lc-card relative overflow-hidden p-5">
            <div className="flex items-center gap-2 mb-4">
              <div className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">Dicas para melhores resultados</div>
              <div className="h-px flex-1 bg-border" />
            </div>
            <div className="space-y-3">
              <DicaRow text="Use intervalos curtos no início para aumentar as respostas." />
              <DicaRow text="Personalize a mensagem de cada etapa — evite repetir o mesmo texto." />
              <DicaRow text="Evite muitas mensagens em pouco tempo para não soar insistente." />
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
};

/** Linha de dica (coluna lateral). */
const DicaRow = ({ text }: { text: string }) => (
  <div className="flex items-start gap-2.5">
    <div className="size-6 rounded-lg grid place-items-center shrink-0 bg-success/10 text-success">
      <Lightbulb className="size-3.5" />
    </div>
    <span className="text-xs text-muted-foreground leading-relaxed">{text}</span>
  </div>
);

/** Item do "Resumo da sequência". accent = destaque verde (único acento). */
const ResumoItem = ({ Icon, label, value, sub, accent }: { Icon: any; label: string; value: string; sub: string; accent?: boolean }) => (
  <div className="flex items-start gap-2.5 min-w-0">
    <div className={cn("size-9 rounded-xl grid place-items-center shrink-0", accent ? "bg-success/10 text-success" : "bg-muted text-muted-foreground")}>
      <Icon className="size-[18px]" />
    </div>
    <div className="min-w-0">
      <div className="text-[11px] text-muted-foreground truncate">{label}</div>
      <div className="text-sm font-bold leading-tight mt-0.5 truncate">{value}</div>
      <div className="text-[10px] text-muted-foreground/80 mt-0.5 truncate">{sub}</div>
    </div>
  </div>
);

/** Linha da "Prévia da automação". accent = âncora (ponto de partida) em verde. */
const PreviewRow = ({
  time, Icon, title, sub, badge, accent,
}: { time: string; Icon: any; title: string; sub?: string; badge?: string; accent?: boolean }) => (
  <div className="relative flex items-center gap-3">
    <div className="w-[44px] shrink-0 text-right">
      <span className="text-[11px] font-semibold text-muted-foreground tabular-nums leading-tight">{time}</span>
    </div>
    <div className={cn("size-9 rounded-xl grid place-items-center shrink-0 ring-4 ring-card z-10", accent ? "bg-success/10 text-success" : "bg-muted text-muted-foreground")}>
      <Icon className="size-4" />
    </div>
    <div className="min-w-0">
      <div className="text-sm font-semibold truncate">{title}</div>
      {sub && <div className="text-[11px] text-muted-foreground truncate">{sub}</div>}
      {badge && (
        <span className="inline-flex items-center text-[10px] font-semibold rounded-md px-1.5 py-0.5 mt-1 bg-muted text-muted-foreground">
          {badge}
        </span>
      )}
    </div>
  </div>
);
