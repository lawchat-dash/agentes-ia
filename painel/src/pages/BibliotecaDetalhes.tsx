import type { CSSProperties } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { useTemplate } from "@/hooks/useTemplates";
import { Button } from "@/components/ui/button";
import {
  ArrowLeft, Rocket, Loader2, Users, Check, CheckCircle2, Zap, Shield, Workflow,
  Bookmark, Sparkles, ChevronRight, Lightbulb, ArrowRight, Lock,
} from "lucide-react";
import { emojiDoProduto, getCategoryIcon, resolveGradient } from "@/data/categories";
import { ROLE_META, ROLE_ORDER } from "@/hooks/useProducts";
import { usePlanGate } from "@/hooks/usePlanGate";

const ROLE_DESC: Record<string, string> = {
  sdr: "Recebe, qualifica e agenda o lead",
  closer: "Apresenta a solução e quebra objeções",
  contratos: "Gera e personaliza o contrato",
  assinatura: "Conduz o cliente até a assinatura",
  desqualificado: "Encerra com educação leads não viáveis",
};

/** Mesmo padrão do card da biblioteca: degradê nas duas cores, brilho interno no topo, sombra colorida suave. */
const iconTileStyle = (c1: string, c2: string): CSSProperties => ({
  backgroundImage: `radial-gradient(130% 90% at 25% 0%, rgba(255,255,255,0.42), rgba(255,255,255,0) 58%), linear-gradient(135deg, ${c1} 0%, ${c2} 100%)`,
  boxShadow: `inset 0 1px 0 rgba(255,255,255,0.5), inset 0 -4px 12px ${c2}66, 0 16px 30px -14px ${c1}cc, 0 3px 8px -3px ${c2}66`,
});

const FOCO = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-success/70 focus-visible:ring-offset-2 focus-visible:ring-offset-background";

const BibliotecaDetalhes = () => {
  const { slug } = useParams();
  const navigate = useNavigate();
  const { data: t, isLoading } = useTemplate(slug);
  const gate = usePlanGate();

  if (isLoading)
    return (
      <div className="grid place-items-center py-24">
        <Loader2 className="size-8 text-primary animate-spin" />
      </div>
    );

  if (!t) {
    return (
      <div className="p-10 text-center">
        <p className="text-muted-foreground">Produto não encontrado.</p>
        <Button asChild variant="outline" className="mt-4">
          <Link to="/biblioteca">Voltar à biblioteca</Link>
        </Button>
      </div>
    );
  }

  const CatIcon = getCategoryIcon(t.category);
  const [c1, c2] = resolveGradient(t.cover_gradient, t.category);
  const agentCount = ROLE_ORDER.length;
  const isComingSoon = t.status === "em_breve";
  const planLocked = gate.isLocked(t.plan_min);
  // Igual ao card da biblioteca: variante com áudio também trava quando o plano não tem áudio.
  const audioLocked = t.modo_midia === "audio" && !gate.recursoAudio;
  const locked = !isComingSoon && (planLocked || audioLocked);
  const planNeeded = gate.neededPlan(t.plan_min);
  const lockLabel = planLocked ? `plano ${planNeeded}` : "plano com áudio";
  const useCases: string[] =
    Array.isArray(t.use_cases) && t.use_cases.length > 0
      ? t.use_cases
      : [
          "Triagem qualificada de novos leads pelo WhatsApp",
          "Apresentação do serviço e quebra de objeções",
          "Geração e envio do contrato pronto para assinatura",
          "Encaminhamento humano apenas dos casos viáveis",
        ];
  const tags: string[] = Array.isArray(t.tags) ? t.tags : [];

  return (
    <div className="px-6 lg:px-8 py-5 lg:py-6 max-w-[1240px] mx-auto space-y-5">
      {/* Voltar */}
      <Button asChild variant="ghost" size="sm" className="-ml-2 text-muted-foreground hover:text-foreground">
        <Link to="/biblioteca"><ArrowLeft className="size-4 mr-1" /> Voltar à biblioteca</Link>
      </Button>

      {/* HERO — card contido (mesmo padding do resto) */}
      <motion.section
        initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
        className="relative overflow-hidden rounded-2xl border p-6 lg:p-8"
        style={{ borderColor: `${c1}33`, backgroundImage: `radial-gradient(120% 120% at 100% 0%, ${c1}22, transparent 55%), linear-gradient(180deg, ${c1}0d, hsl(var(--card)))` }}
      >
        <div className="absolute inset-0 opacity-[0.4] pointer-events-none" style={{ backgroundImage: "linear-gradient(hsl(var(--border)) 1px, transparent 1px), linear-gradient(90deg, hsl(var(--border)) 1px, transparent 1px)", backgroundSize: "32px 32px", maskImage: "radial-gradient(circle at 85% 30%, black, transparent 60%)" }} />
        {/* decoração tingida pela categoria */}
        <div className="hidden lg:block absolute right-8 xl:right-12 top-1/2 -translate-y-1/2 w-52 h-36 pointer-events-none">
          <div className="absolute inset-2 rounded-full blur-2xl" style={{ background: `${c1}22` }} />
          <div className="absolute left-10 top-7 w-32 h-[78px] rounded-2xl bg-card/90 backdrop-blur border border-border shadow-xl p-3.5 flex flex-col gap-2">
            <div className="h-2 w-14 rounded-full" style={{ background: c1 }} />
            <div className="h-1.5 w-24 rounded-full bg-muted" />
            <div className="h-1.5 w-20 rounded-full bg-muted" />
          </div>
          {[
            "top-1 right-10", "top-[3.4rem] right-0", "bottom-1 right-12", "bottom-6 left-3",
          ].map((pos, i) => (
            <span key={i} className={`absolute ${pos} size-6 rounded-full grid place-items-center text-white shadow-md`} style={{ background: c1 }}>
              <Check className="size-3.5" strokeWidth={3} />
            </span>
          ))}
        </div>
        <div className="relative flex flex-col sm:flex-row items-start gap-4 sm:gap-5 lg:max-w-[68%]">
          <div className="group/icone relative size-16 lg:size-20 shrink-0">
            <span aria-hidden className="absolute inset-1 rounded-2xl blur-xl opacity-50 transition-opacity duration-300 group-hover/icone:opacity-80" style={{ backgroundImage: `linear-gradient(135deg, ${c1}, ${c2})` }} />
            <div
              className="relative size-full rounded-2xl grid place-items-center overflow-hidden ring-1 ring-inset ring-white/15 transition-transform duration-300 [transition-timing-function:cubic-bezier(.34,1.56,.64,1)] group-hover/icone:-translate-y-0.5 group-hover/icone:scale-105 motion-reduce:transform-none"
              style={iconTileStyle(c1, c2)}
            >
              {emojiDoProduto(t.icon) ? <span className="text-[34px] lg:text-[42px] leading-none" aria-hidden>{emojiDoProduto(t.icon)}</span> : <CatIcon className="size-8 lg:size-10 text-white drop-shadow-[0_1px_2px_rgba(0,0,0,0.25)]" strokeWidth={1.75} />}
            </div>
          </div>
          <div className="min-w-0">
            <span className="text-[11px] font-bold tracking-[0.16em] uppercase" style={{ color: c1 }}>{t.category}</span>
            <h1 className="flex items-center gap-2 text-2xl sm:text-3xl lg:text-4xl font-bold mt-1 text-foreground tracking-tight break-words">
              {t.name} <CheckCircle2 className="size-6 shrink-0" style={{ color: c1 }} />
            </h1>
            <p className="mt-2 text-[15px] text-muted-foreground max-w-xl leading-relaxed">{t.description_short}</p>
            <div className="mt-4 flex flex-wrap gap-2">
              <Badge icon={Users} text={`${agentCount} agentes`} color={c1} />
              <Badge icon={Zap} text="Setup em ~60s" color={c1} />
              <Badge icon={Shield} text="Pronto para WhatsApp" color={c1} />
              {tags.slice(0, 3).map((tag) => (
                <span key={tag} className="px-2.5 py-1 rounded-full bg-muted text-muted-foreground border border-border text-[11px] font-medium">{tag}</span>
              ))}
            </div>
          </div>
        </div>
      </motion.section>

      {/* CONTENT */}
      <div className="grid lg:grid-cols-[1fr_340px] gap-5 lg:gap-6 items-start">
        <div className="space-y-5 min-w-0">
          {/* Sobre */}
          <section className="rounded-2xl border border-border bg-card p-6">
            <h3 className="font-bold text-base flex items-center gap-2 mb-2"><Sparkles className="size-4" style={{ color: c1 }} /> Sobre este produto</h3>
            <p className="text-[14px] text-muted-foreground leading-relaxed">{t.description_long || t.description_short}</p>
          </section>

          {/* Pipeline */}
          <section className="rounded-2xl border border-border bg-card p-6">
            <h3 className="font-bold text-base flex items-center gap-2"><Workflow className="size-4" style={{ color: c1 }} /> Como o conjunto de agentes funciona</h3>
            <p className="text-[13px] text-muted-foreground mt-1 mb-4">{agentCount} agentes especializados que trabalham em sequência, passando o lead adiante automaticamente.</p>
            <div className="relative">
              <span className="absolute left-[50px] top-6 bottom-6 w-px bg-border hidden sm:block" />
              <div className="space-y-2.5">
                {ROLE_ORDER.map((role, idx) => {
                  const meta = ROLE_META[role];
                  const Icon = meta.Icon;
                  return (
                    <div key={role} className="relative flex items-center gap-3 p-3 rounded-xl border border-border bg-background/40 hover:border-[var(--cat)] hover:bg-[var(--catbg)] transition-colors" style={{ ["--cat" as any]: c1, ["--catbg" as any]: `${c1}10` }}>
                      <span className="text-[11px] font-bold text-muted-foreground/70 w-6 text-center shrink-0 tabular-nums">{String(idx + 1).padStart(2, "0")}</span>
                      <span className="hidden sm:block relative z-10 size-2.5 rounded-full ring-4 ring-card shrink-0" style={{ background: c1 }} />
                      <div className="relative z-10 size-10 rounded-xl grid place-items-center text-white shrink-0" style={{ backgroundImage: `linear-gradient(135deg, ${c1}, ${c2})` }}>
                        <Icon className="size-5" strokeWidth={1.75} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="font-semibold text-[13px]">{meta.label}</div>
                        <div className="text-[12px] text-muted-foreground">{ROLE_DESC[role]}</div>
                      </div>
                      <ChevronRight className="size-4 text-muted-foreground/50 shrink-0" />
                    </div>
                  );
                })}
              </div>
            </div>
          </section>

          {/* Para que serve */}
          <section className="relative overflow-hidden rounded-2xl border border-border bg-card p-6">
            <Shield className="absolute -right-6 -bottom-6 size-40 pointer-events-none" strokeWidth={1} style={{ color: `${c1}14` }} />
            <h3 className="relative font-bold text-base flex items-center gap-2 mb-4"><Bookmark className="size-4" style={{ color: c1 }} /> Para que serve</h3>
            <ul className="relative grid sm:grid-cols-2 gap-x-6 gap-y-3">
              {useCases.map((uc, i) => (
                <li key={i} className="flex items-start gap-2.5 text-[13px]">
                  <div className="size-5 rounded-md grid place-items-center shrink-0 mt-0.5" style={{ background: `${c1}1a`, color: c1 }}><Check className="size-3" strokeWidth={3} /></div>
                  <span className="text-muted-foreground leading-relaxed">{uc}</span>
                </li>
              ))}
            </ul>
          </section>
        </div>

        {/* SIDEBAR */}
        <div className="lg:sticky lg:top-6 lg:self-start space-y-4">
          {/* Ativar */}
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
            className="rounded-2xl border bg-card p-6" style={{ borderColor: `${c1}40`, boxShadow: `0 16px 44px -20px ${c1}88` }}>
            <div className="text-[11px] uppercase tracking-[0.14em] font-bold" style={{ color: c1 }}>Ativar este produto</div>
            <div className="mt-4 space-y-2.5 text-[13px]">
              <Row label="Inclui" value={`${agentCount} agentes`} />
              <Row label="Setup em" value="~60 segundos" />
              <Row label="Canal" value="WhatsApp" />
            </div>
            {isComingSoon ? (
              <>
                <div className="mt-5 h-12 w-full rounded-xl border border-amber-500/30 bg-amber-500/10 text-amber-600 grid place-items-center text-sm font-semibold">
                  <span className="inline-flex items-center gap-1.5"><Sparkles className="size-4" /> Em breve</span>
                </div>
                <p className="text-[11px] text-muted-foreground text-center mt-3">Este produto será disponibilizado em breve. Você já pode conhecer o que ele faz aqui.</p>
              </>
            ) : locked ? (
              <>
                <div className="mt-5 h-12 w-full rounded-xl border border-violet-500/30 bg-violet-500/10 text-violet-600 grid place-items-center text-sm font-semibold">
                  <span className="inline-flex items-center gap-1.5"><Lock className="size-4" /> Requer {lockLabel}</span>
                </div>
                <p className="text-[11px] text-muted-foreground text-center mt-3">
                  {planLocked
                    ? <>Faça upgrade para o plano <strong>{planNeeded}</strong> para ativar este produto.</>
                    : <>Esta versão envia áudios. Ative um plano com <strong>áudio liberado</strong> para usá-la.</>}
                </p>
              </>
            ) : (
              <>
                <Button onClick={() => navigate(`/ativar/${t.slug}`)}
                  className="group relative w-full mt-5 h-12 overflow-hidden rounded-xl text-white text-[15px] font-semibold transition-all duration-200 hover:-translate-y-0.5 hover:brightness-[1.05] active:translate-y-0"
                  style={{ backgroundImage: `linear-gradient(135deg, ${c1}, ${c2})`, boxShadow: `0 12px 28px -8px ${c1}cc`, ["--btn-glow" as any]: `linear-gradient(90deg, ${c1}, ${c2})` }}>
                  <span className="absolute inset-0 -translate-x-full group-hover:translate-x-full transition-transform [transition-duration:900ms] ease-out bg-gradient-to-r from-transparent via-white/30 to-transparent pointer-events-none" />
                  <Rocket className="size-4 mr-1.5 relative transition-transform group-hover:-translate-y-0.5 group-hover:-rotate-12" />
                  <span className="relative">Ativar produto</span>
                </Button>
                <p className="text-[11px] text-muted-foreground text-center mt-3">Você pode personalizar todos os prompts depois.</p>
              </>
            )}
          </motion.div>

          {/* Incluso */}
          <div className="rounded-2xl border border-border bg-card/60 p-5">
            <div className="text-[11px] uppercase tracking-[0.14em] font-bold text-muted-foreground mb-3">O que está incluso</div>
            <ul className="space-y-2.5 text-[13px]">
              {["Prompts profissionais prontos", "Handoff automático entre agentes", "Modelo recomendado pré-configurado", "Mensagens de boas-vindas", "Edição completa após ativar"].map((item) => (
                <li key={item} className="flex items-center gap-2">
                  <Check className="size-3.5 shrink-0" strokeWidth={3} style={{ color: c1 }} />
                  <span className="text-muted-foreground">{item}</span>
                </li>
              ))}
            </ul>
          </div>

          {/* Dica rápida */}
          <div className="rounded-2xl border border-border bg-card p-5 flex items-center gap-3">
            <div className="size-10 rounded-xl grid place-items-center shrink-0" style={{ background: `${c1}1a`, color: c1 }}><Lightbulb className="size-5" /></div>
            <div className="flex-1 min-w-0">
              <div className="text-[11px] uppercase tracking-[0.12em] font-bold text-muted-foreground">Dica rápida</div>
              <p className="text-[12.5px] text-muted-foreground mt-0.5 leading-snug">Você poderá editar fluxos, mensagens e regras após ativar o produto.</p>
            </div>
            {!locked && !isComingSoon && (
              <button type="button" onClick={() => navigate(`/ativar/${t.slug}`)} className={`size-9 rounded-lg grid place-items-center shrink-0 transition-opacity hover:opacity-80 ${FOCO}`} style={{ background: `${c1}1a`, color: c1 }} aria-label="Ativar produto">
                <ArrowRight className="size-4" />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

const Badge = ({ icon: Icon, text, color }: { icon: any; text: string; color: string }) => (
  <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-[11px] font-semibold" style={{ background: `${color}1a`, color, borderColor: `${color}33` }}>
    <Icon className="size-3.5" /> {text}
  </span>
);

const Row = ({ label, value }: { label: string; value: string }) => (
  <div className="flex justify-between">
    <span className="text-muted-foreground">{label}</span>
    <span className="font-semibold text-foreground">{value}</span>
  </div>
);

export default BibliotecaDetalhes;
