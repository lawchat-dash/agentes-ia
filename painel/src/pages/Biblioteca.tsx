import { useState, useMemo, type CSSProperties } from "react";
import { motion } from "framer-motion";
import { Search, Sparkles, ArrowRight, X, Layers, ArrowDownAZ, ArrowUpAZ, LayoutGrid, Zap, Cpu, Box, Shield, Star, Users, Lock, Headphones, Type } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Link } from "react-router-dom";
import { useTemplates } from "@/hooks/useTemplates";
import { usePlanGate } from "@/hooks/usePlanGate";
import { categories, getCategoryIcon, resolveGradient } from "@/data/categories";
import biblioteca3d from "@/assets/biblioteca-3d.png";

/** Quadrado do ícone em degradê: as duas cores do produto/categoria, brilho interno no topo e sombra colorida suave. */
const iconTileStyle = (c1: string, c2: string): CSSProperties => ({
  backgroundImage: `radial-gradient(130% 90% at 25% 0%, rgba(255,255,255,0.42), rgba(255,255,255,0) 58%), linear-gradient(135deg, ${c1} 0%, ${c2} 100%)`,
  boxShadow: `inset 0 1px 0 rgba(255,255,255,0.5), inset 0 -3px 8px ${c2}66, 0 10px 20px -10px ${c1}cc, 0 2px 5px -2px ${c2}66`,
});

/** Foco visível (teclado) nos botões customizados desta tela. */
const FOCO = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-success/70 focus-visible:ring-offset-2 focus-visible:ring-offset-background";

/** Selo pequeno do card: mesma altura para todos, alinhado ao centro do ícone. */
const SELO = "h-6 inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider leading-none px-2 rounded-md border";

const Biblioteca = () => {
  const [search, setSearch] = useState("");
  const [activeCat, setActiveCat] = useState<string | null>(null);
  const [sort, setSort] = useState<"az" | "za">("az");
  const [modoMidia, setModoMidia] = useState<"all" | "audio" | "texto">("all");
  const { data: templates, isLoading } = useTemplates();
  const gate = usePlanGate();

  const counts = useMemo(() => {
    const m: Record<string, number> = {};
    (templates ?? []).forEach((t) => { m[t.category] = (m[t.category] || 0) + 1; });
    return m;
  }, [templates]);

  // Só mostra o filtro de mídia quando existe ao menos uma variante com áudio na biblioteca.
  const temAudio = useMemo(() => (templates ?? []).some((t) => t.modo_midia === "audio"), [templates]);

  const filtered = useMemo(() => {
    if (!templates) return [];
    const q = search.trim().toLowerCase();
    let list = templates.filter((t) => {
      const matchSearch = !q || t.name.toLowerCase().includes(q) || t.description_short.toLowerCase().includes(q) || t.tags.some((tag) => tag.toLowerCase().includes(q));
      const matchCat = !activeCat || t.category === activeCat;
      const matchModo = modoMidia === "all" || t.modo_midia === modoMidia;
      return matchSearch && matchCat && matchModo;
    });
    // Ordem: DISPONÍVEIS primeiro, BLOQUEADOS por plano no meio, EM BREVE por último.
    // Dentro de cada grupo, respeita a ordenação A–Z / Z–A.
    const prioridade = (t: typeof list[number]) =>
      t.status === "em_breve" ? 2 : (gate.isLocked(t.plan_min) ? 1 : 0);
    list = [...list].sort((a, b) => {
      const pa = prioridade(a), pb = prioridade(b);
      if (pa !== pb) return pa - pb;
      return sort === "az" ? a.name.localeCompare(b.name) : b.name.localeCompare(a.name);
    });
    return list;
  }, [templates, search, activeCat, sort, gate, modoMidia]);

  const limpar = () => { setSearch(""); setActiveCat(null); setModoMidia("all"); };
  const temFiltro = !!search || !!activeCat || modoMidia !== "all";

  return (
    <div className="p-6 lg:p-8 space-y-5 max-w-[1400px] mx-auto">
      {/* Hero */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className="relative overflow-hidden rounded-3xl border border-border bg-gradient-to-br from-card via-card to-success/5 px-6 py-7 lg:px-10 lg:py-9 min-h-[200px]"
      >
        <div className="absolute -top-24 -right-12 size-80 rounded-full bg-success/10 blur-3xl pointer-events-none" />
        {/* grid de pontos */}
        <div className="hidden lg:block absolute right-[19rem] top-1/2 -translate-y-1/2 size-28 opacity-50 pointer-events-none" style={{ backgroundImage: "radial-gradient(hsl(var(--success)/0.35) 1.5px, transparent 1.5px)", backgroundSize: "16px 16px" }} />
        {/* selo estrela */}
        <div className="hidden lg:grid absolute right-8 top-7 size-11 rounded-2xl bg-success/10 border border-success/20 place-items-center pointer-events-none">
          <Star className="size-5 text-success" />
        </div>
        {/* ilustração */}
        <img src={biblioteca3d} alt="" className="hidden md:block absolute right-0 lg:right-2 top-1/2 -translate-y-1/2 w-64 lg:w-[23rem] xl:w-[27rem] select-none pointer-events-none drop-shadow-xl" loading="eager" />

        <div className="relative md:max-w-[58%] lg:max-w-[62%]">
          <div className="inline-flex items-center gap-2.5 px-3 py-1.5 rounded-full bg-success/10 border border-success/20 text-success text-[12px] font-semibold">
            <span className="inline-flex items-center gap-1.5"><Users className="size-3.5" /> {templates?.length ?? 0} produtos oficiais</span>
            <span className="w-px h-3 bg-success/30" />
            <span className="inline-flex items-center gap-1.5"><Zap className="size-3.5" /> Pipeline com 5 agentes cada</span>
          </div>
          <h1 className="text-3xl lg:text-4xl font-bold tracking-tight mt-4 text-foreground">Biblioteca de Produtos</h1>
          <div className="h-1 w-12 rounded-full bg-success mt-2.5" />
          <p className="text-sm text-muted-foreground mt-3 max-w-lg leading-relaxed">
            Cada produto vem com um pipeline pronto — SDR, Closer, Contratos, Assinatura e Desqualificado. Ative em segundos e ajuste o prompt de cada agente.
          </p>
          <div className="flex flex-wrap gap-2 mt-5">
            <FeaturePill icon={Box} text="Estruturado" />
            <FeaturePill icon={Shield} text="Pronto para uso" />
            <FeaturePill icon={Zap} text="Ative em segundos" />
            <FeaturePill icon={Sparkles} text="Personalizável" />
          </div>
        </div>
      </motion.div>

      {/* Toolbar: busca + ordenação */}
      <div className="flex flex-wrap gap-3 items-center sticky top-2 z-20 -mx-2 px-2 py-2 rounded-2xl bg-background/85 backdrop-blur-md supports-[backdrop-filter]:bg-background/70">
        <div className="relative flex-1 min-w-[260px]">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
          <Input
            placeholder="Buscar por nome, categoria ou tag…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-10 pr-9 h-11 rounded-xl bg-card border-border/60"
          />
          {search && (
            <button type="button" onClick={() => setSearch("")} className={`absolute right-2 top-1/2 -translate-y-1/2 size-7 grid place-items-center rounded-full text-muted-foreground hover:text-foreground hover:bg-muted transition-colors ${FOCO}`} aria-label="Limpar busca">
              <X className="size-4" />
            </button>
          )}
        </div>
        <div className="flex rounded-xl bg-muted/60 p-1 border border-border/60" role="radiogroup" aria-label="Ordenar">
          {[
            { v: "az", l: "A–Z", icon: ArrowDownAZ },
            { v: "za", l: "Z–A", icon: ArrowUpAZ },
          ].map((s) => (
            <button
              key={s.v}
              type="button"
              role="radio"
              aria-checked={sort === s.v}
              onClick={() => setSort(s.v as "az" | "za")}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition ${FOCO} ${sort === s.v ? "bg-background shadow-sm text-foreground" : "text-muted-foreground hover:text-foreground"}`}
            >
              <s.icon className="size-3.5" /> {s.l}
            </button>
          ))}
        </div>
        {/* Filtro de mídia — só aparece quando existe variante com áudio publicada */}
        {temAudio && (
          <div className="flex flex-wrap rounded-xl bg-muted/60 p-1 border border-border/60" role="radiogroup" aria-label="Filtrar por mídia">
            {[
              { v: "all", l: "Todos", icon: LayoutGrid },
              { v: "audio", l: "Com biblioteca de mídia", icon: Headphones },
              { v: "texto", l: "Somente texto", icon: Type },
            ].map((s) => (
              <button
                key={s.v}
                type="button"
                role="radio"
                aria-checked={modoMidia === s.v}
                onClick={() => setModoMidia(s.v as "all" | "audio" | "texto")}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition ${FOCO} ${modoMidia === s.v ? "bg-background shadow-sm text-foreground" : "text-muted-foreground hover:text-foreground"}`}
              >
                <s.icon className="size-3.5" /> {s.l}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Category pills */}
      <div className="flex flex-wrap gap-1.5">
        <CategoryPill icon={LayoutGrid} label="Todas" count={templates?.length ?? 0} active={!activeCat} onClick={() => setActiveCat(null)} />
        {categories.map((c) => (
          <CategoryPill key={c.name} icon={c.Icon} label={c.name} count={counts[c.name] ?? 0} active={activeCat === c.name} onClick={() => setActiveCat(c.name)} />
        ))}
      </div>

      {/* Result count */}
      {!isLoading && (
        <div className="flex items-center justify-between gap-2 -mt-1">
          <div className="text-xs text-muted-foreground">
            <span className="font-semibold text-foreground">{filtered.length}</span> {filtered.length === 1 ? "produto" : "produtos"}
            {activeCat && <> em <span className="font-semibold text-foreground">{activeCat}</span></>}
          </div>
          {temFiltro && (
            <button type="button" onClick={limpar} className={`text-xs font-semibold text-muted-foreground hover:text-foreground inline-flex items-center gap-1 rounded-md px-1 transition-colors ${FOCO}`}>
              <X className="size-3" /> Limpar filtros
            </button>
          )}
        </div>
      )}

      {/* Grid */}
      {isLoading ? (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="rounded-2xl border border-border bg-card p-4 h-[210px] animate-pulse">
              <div className="size-11 rounded-xl bg-muted" />
              <div className="h-3.5 w-3/4 bg-muted rounded mt-4" />
              <div className="h-2.5 w-full bg-muted rounded mt-3" />
              <div className="h-2.5 w-5/6 bg-muted rounded mt-2" />
              <div className="flex gap-1.5 mt-4"><div className="h-4 w-12 bg-muted rounded-full" /><div className="h-4 w-14 bg-muted rounded-full" /></div>
            </div>
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-16">
          <div className="size-14 rounded-2xl bg-muted grid place-items-center mx-auto"><Search className="size-6 text-muted-foreground" /></div>
          <div className="text-sm font-semibold text-foreground mt-3">Nenhum produto encontrado</div>
          <div className="text-xs text-muted-foreground mt-1">Tente outra busca ou categoria.</div>
          {temFiltro && <Button onClick={limpar} variant="outline" size="sm" className="mt-4">Limpar filtros</Button>}
        </div>
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {filtered.map((t, i) => {
            const CatIcon = getCategoryIcon(t.category);
            const [c1, c2] = resolveGradient(t.cover_gradient, t.category);
            const nAgentes = t.n_agentes ?? 5;
            const isComingSoon = t.status === "em_breve";
            const audioLocked = t.modo_midia === "audio" && !gate.recursoAudio; // variante áudio sem plano com áudio
            const locked = !isComingSoon && (gate.isLocked(t.plan_min) || audioLocked);
            const dimmed = locked; // em_breve agora é clicável (abre o detalhe); só plano apaga/trava
            const planNeeded = gate.neededPlan(t.plan_min);
            // Trava por TIER de plano → mostra o plano; trava só por áudio → "com áudio".
            const lockLabel = gate.isLocked(t.plan_min) ? planNeeded : "com áudio";

            const cardBody = (
              <div
                className={`relative rounded-2xl border border-border bg-card h-full flex flex-col p-4 overflow-hidden transition-all duration-200 ${
                  locked
                    ? "opacity-60 grayscale-[0.6] cursor-not-allowed"
                    : isComingSoon
                      ? "opacity-65 saturate-[0.85] hover:opacity-100 hover:saturate-100 hover:border-amber-400/60 hover:shadow-[0_14px_34px_-16px_rgba(217,119,6,0.35)] hover:-translate-y-0.5"
                      : "hover:border-[var(--cat)] hover:shadow-[0_14px_34px_-16px_var(--catShadow)] hover:-translate-y-1"
                }`}
                style={{ ["--cat" as any]: c1, ["--catShadow" as any]: `${c1}59` }}
              >
                {!dimmed && <div className="absolute -right-10 -top-10 size-32 rounded-full blur-2xl opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none" style={{ background: `radial-gradient(circle, ${c1}38, ${c1}00 70%)` }} />}
                {/* brilho que atravessa o card no hover */}
                {!dimmed && (
                  <div aria-hidden className="absolute inset-0 pointer-events-none overflow-hidden rounded-2xl motion-reduce:hidden">
                    <span className="absolute -inset-y-6 left-0 w-1/3 rotate-12 bg-gradient-to-r from-transparent via-white/35 to-transparent opacity-0 -translate-x-[150%] group-hover:opacity-100 group-hover:translate-x-[420%] transition-[transform,opacity] duration-700 ease-out" />
                  </div>
                )}
                {/* Top: icon + badge */}
                <div className="relative flex items-center justify-between gap-2 mb-3">
                  <div className="relative size-11 shrink-0">
                    {/* halo colorido que acende no hover */}
                    {!dimmed && <span aria-hidden className="absolute inset-0 rounded-xl blur-md opacity-0 scale-90 group-hover:opacity-60 group-hover:scale-110 transition-all duration-300" style={{ backgroundImage: `linear-gradient(135deg, ${c1}, ${c2})` }} />}
                    <div
                      className="relative size-11 rounded-xl grid place-items-center overflow-hidden ring-1 ring-inset ring-white/15 transition-transform duration-300 [transition-timing-function:cubic-bezier(.34,1.56,.64,1)] group-hover:-translate-y-0.5 group-hover:scale-[1.07] group-hover:-rotate-3 motion-reduce:transform-none"
                      style={iconTileStyle(c1, c2)}
                    >
                      <CatIcon className="size-[19px] text-white drop-shadow-[0_1px_1px_rgba(0,0,0,0.25)]" strokeWidth={2} />
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5 min-w-0">
                    {t.modo_midia === "audio" && (
                      <span className={`${SELO} bg-sky-500/15 text-sky-700 border-sky-500/30`} title="Envia áudios (biblioteca de mídia)"><Headphones className="size-2.5" />Mídia</span>
                    )}
                    {isComingSoon ? (
                      <span className={`${SELO} bg-amber-500/15 text-amber-700 border-amber-500/30`}>Em breve</span>
                    ) : locked ? (
                      <span className={`${SELO} bg-violet-500/15 text-violet-700 border-violet-500/30`}><Lock className="size-2.5" />{lockLabel}</span>
                    ) : (
                      <span className={`${SELO} text-muted-foreground bg-muted/60 border-transparent truncate`}>{t.category}</span>
                    )}
                  </div>
                </div>

                <h3 className="relative font-semibold text-sm leading-snug line-clamp-1">{t.name}</h3>
                <p className="relative text-xs text-muted-foreground mt-1.5 line-clamp-2 leading-relaxed">{t.description_short}</p>

                {/* Tags */}
                {t.tags.length > 0 && (
                  <div className="relative flex flex-wrap gap-1 mt-3">
                    {t.tags.slice(0, 3).map((tag) => (
                      <span key={tag} className="text-[10px] font-medium px-1.5 py-0.5 rounded-md border" style={{ background: `${c1}14`, color: c1, borderColor: `${c1}26` }}>{tag}</span>
                    ))}
                    {t.tags.length > 3 && <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-md bg-muted text-muted-foreground">+{t.tags.length - 3}</span>}
                  </div>
                )}

                {/* Meta: pipeline + modelo */}
                <div className="relative flex items-center gap-3 mt-3 text-[10.5px] text-muted-foreground">
                  <span className="inline-flex items-center gap-1"><Layers className="size-3" /> {nAgentes} {nAgentes === 1 ? "agente" : "agentes"}</span>
                  {t.recommended_model && <span className="inline-flex items-center gap-1 truncate"><Cpu className="size-3" /> {t.recommended_model}</span>}
                </div>

                {/* CTA */}
                <div className="relative mt-auto pt-3 border-t border-border/60 flex items-center justify-between">
                  {isComingSoon ? (
                    <>
                      <span className="text-[11px] font-semibold text-amber-600 group-hover:text-amber-700 transition-colors">Ver detalhes · Em breve</span>
                      <div className="size-7 rounded-full bg-amber-500/15 grid place-items-center text-amber-600 transition-all group-hover:bg-amber-500 group-hover:text-white">
                        <ArrowRight className="size-3.5 group-hover:translate-x-0.5 transition-transform" />
                      </div>
                    </>
                  ) : locked ? (
                    <span className="text-[11px] font-semibold text-violet-600 inline-flex items-center gap-1"><Lock className="size-3" /> Requer plano {lockLabel}</span>
                  ) : (
                    <>
                      <span className="text-[11px] font-semibold text-muted-foreground group-hover:text-[var(--cat)] transition-colors">Ver e ativar</span>
                      <div className="size-7 rounded-full bg-muted grid place-items-center text-muted-foreground group-hover:text-white transition-all group-hover:[background:var(--cat)]">
                        <ArrowRight className="size-3.5 group-hover:translate-x-0.5 transition-transform" />
                      </div>
                    </>
                  )}
                </div>
              </div>
            );

            return (
              <motion.div key={t.id} layout initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: Math.min(i * 0.02, 0.3) }}>
                {locked ? (
                  <div className="block h-full" title={audioLocked && !gate.isLocked(t.plan_min) ? "Disponível em planos com áudio liberado" : `Disponível no plano ${planNeeded}`}>{cardBody}</div>
                ) : (
                  <Link to={`/biblioteca/${t.slug}`} className={`group block h-full rounded-2xl ${FOCO}`} title={isComingSoon ? "Em breve — veja os detalhes" : undefined}>{cardBody}</Link>
                )}
              </motion.div>
            );
          })}
        </div>
      )}

    </div>
  );
};

const FeaturePill = ({ icon: Icon, text }: { icon: any; text: string }) => (
  <span className="inline-flex items-center gap-2 px-3 py-2 rounded-xl border border-border bg-card text-[12px] font-semibold text-foreground/80">
    <Icon className="size-3.5 text-success" /> {text}
  </span>
);

const CategoryPill = ({ icon: Icon, label, count, active, onClick }: { icon: any; label: string; count: number; active: boolean; onClick: () => void }) => (
  <button
    type="button"
    aria-pressed={active}
    onClick={onClick}
    className={`px-3 py-1.5 rounded-full text-xs font-semibold transition flex items-center gap-1.5 border ${FOCO} ${active ? "bg-success text-success-foreground border-success shadow-[0_4px_14px_-4px_hsl(var(--success)/0.4)]" : "bg-card text-foreground/80 border-border hover:border-success/40 hover:bg-success/5 hover:text-foreground"}`}
  >
    <Icon className="size-3.5" /> {label}
    <span className={`text-[10px] tabular-nums ${active ? "text-success-foreground/80" : "text-muted-foreground"}`}>{count}</span>
  </button>
);

export default Biblioteca;
