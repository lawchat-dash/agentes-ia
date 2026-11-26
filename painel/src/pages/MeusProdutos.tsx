import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  Plus, Loader2, Package, CircleDot, CircleDashed, Pause, AlertTriangle,
  Trash2, Search, Settings2, MessageSquare, Sparkles,
  Workflow, Activity, RotateCcw, RotateCw, X, Phone, Bot, Send, BookOpen, FlaskConical,
} from "lucide-react";
import { useMyProducts, useTrashedProducts, useRetryProductProvisioning, ROLE_META, ROLE_ORDER } from "@/hooks/useProducts";
import { getCategoryIcon, resolveGradient } from "@/data/categories";
import { api, enviar } from "@/api";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useProvisioningRealtime } from "@/hooks/useProvisioning";
import folder3d from "@/assets/folder-3d.png";
import { StatusToggle } from "@/components/ui/status-toggle";
import { ButtonHoldAndRelease } from "@/components/ui/hold-and-release-button";
import { AvisoFollowupDesligado } from "@/components/followup/AvisoFollowupDesligado";
import { SeloSaude, TestarConexao, TipoNumero, useSaudeNumeros, type SaudeAgente } from "@/componentes/SaudeNumero";
import { FiltroNumero } from "@/componentes/FiltroNumero";
import { useSessao } from "@/sessao";

/** As abas do agente, direto do cartão (as mesmas rotas do submenu /agentes/:id/:secao). */
const ABAS_DO_AGENTE = [
  { chave: "instrucoes", rotulo: "Prompt", Icone: Bot },
  { chave: "followup", rotulo: "Follow-up", Icone: Send },
  { chave: "conhecimento", rotulo: "Conhecimento", Icone: BookOpen },
  { chave: "laboratorio", rotulo: "Laboratório", Icone: FlaskConical },
] as const;

/** Junta os campos de um erro (message/details/hint/code) para diagnóstico. */
const erroDetalhe = (e: any): string =>
  [e?.message, e?.details, e?.hint, e?.code && `(${e.code})`].filter(Boolean).join(" · ") ||
  "Erro desconhecido";

// Badges de estado: texto em tom ESCURO da cor (contraste ≥ 4.5:1 sobre o fundo claro).
// Antes era text-warning sobre bg-warning/15 (≈2:1, ilegível). A cor viva fica no ícone/borda.
const BADGE = {
  success: "bg-[#00BC33]/10 text-[#0a6b25] border-[#00BC33]/30 dark:bg-success/15 dark:text-green-200 dark:border-success/30",
  warning: "bg-amber-50 text-amber-800 border-amber-300 dark:bg-amber-500/15 dark:text-amber-200 dark:border-amber-500/30",
  danger: "bg-red-50 text-red-700 border-red-200 dark:bg-destructive/15 dark:text-red-200 dark:border-destructive/30",
  muted: "bg-slate-100 text-slate-600 border-slate-200 dark:bg-muted dark:text-muted-foreground dark:border-border",
} as const;

const statusStyle: Record<string, string> = {
  active: BADGE.success,
  draft: BADGE.muted,
  paused: BADGE.warning,
  error: BADGE.danger,
};
const statusMeta: Record<string, { label: string; Icon: any }> = {
  active: { label: "Ativo", Icon: CircleDot },
  draft: { label: "Rascunho", Icon: CircleDashed },
  paused: { label: "Pausado", Icon: Pause },
  error: { label: "Erro", Icon: AlertTriangle },
};

type Filter = "all" | "active" | "paused" | "draft" | "trash";

const MeusProdutos = () => {
  const { data: products, isLoading } = useMyProducts();
  const { data: trashed } = useTrashedProducts();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const retryProduct = useRetryProductProvisioning();
  useProvisioningRealtime();
  const { escritorio } = useSessao();
  // Saúde do número de cada agente: selo da última mensagem recebida, tipo do número e o "Testar conexão".
  const saude = useSaudeNumeros(escritorio);
  const saudePorAgente = useMemo(() => new Map((saude.dados?.agentes ?? []).map((a) => [a.id, a] as [string, SaudeAgente])), [saude.dados]);
  // Agentes criados fora da Biblioteca (o "Criar agente" antigo): sem produto ativado, mas são agentes da conta.
  // Antes apareciam em "Agentes"; com o menu num caminho só, ficam aqui embaixo para não sumirem.
  const avulsos = useMemo(() => {
    const dosProdutos = new Set([...(products ?? []), ...(trashed ?? [])].map((p: any) => p.weaver_agent_id).filter(Boolean));
    return (saude.dados?.agentes ?? []).filter((a) => !dosProdutos.has(a.id));
  }, [saude.dados, products, trashed]);
  const [deleting, setDeleting] = useState<{ id: string; name: string; weaver_agent_id?: string | null } | null>(null);
  const [purging, setPurging] = useState<{ id: string; name: string; source_template_id: string | null; workspace_id: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState("");
  const [purgeConfirm, setPurgeConfirm] = useState("");
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [, setTick] = useState(0);

  // Re-renderiza periodicamente para flipar o estado "stuck" sem reload
  useEffect(() => {
    const anyBuilding = (products ?? []).some((p: any) => p.provisioning_status === "building");
    if (!anyBuilding) return;
    const id = setInterval(() => setTick((t) => t + 1), 15000);
    return () => clearInterval(id);
  }, [products]);

  // A lixeira esvaziou enquanto estava selecionada (restaurou/excluiu o último item):
  // o chip "Lixeira" só existe com itens, então ele some — mas o filtro continuava "trash",
  // exibindo "Nenhum resultado" sem chip visível pra voltar. Volta pra "Todos".
  useEffect(() => {
    if (filter === "trash" && (trashed ?? []).length === 0) setFilter("all");
  }, [filter, trashed]);

  const stats = useMemo(() => {
    const list = (products ?? []) as any[];
    return {
      total: list.length,
      active: list.filter((p) => p.status === "active").length,
      paused: list.filter((p) => p.status === "paused").length,
      draft: list.filter((p) => p.status === "draft").length,
      trash: (trashed ?? []).length,
      configured: list.reduce((acc, p) => acc + (p.agents?.length ?? 0), 0),
    };
  }, [products, trashed]);

  const filtered = useMemo(() => {
    const list = filter === "trash"
      ? (trashed ?? []) as any[]
      : (products ?? []) as any[];
    return list.filter((p) => {
      if (filter !== "all" && filter !== "trash" && p.status !== filter) return false;
      if (search.trim()) {
        const q = search.toLowerCase();
        const hay = `${p.name ?? ""} ${p.source_template?.name ?? ""}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [products, trashed, filter, search]);

  /**
   * Soft delete: envia o produto para a lixeira (30 dias).
   * O servidor pausa o agente, marca excluido_em e LIBERA o número de WhatsApp (outro produto pode usar).
   * Restaurado, o produto volta sem número: escolhe o número e ativa de novo no editor.
   */
  const handleDelete = async (target: { id: string; name: string; weaver_agent_id?: string | null } | null = deleting) => {
    if (!target) return;
    setBusy(true);
    try {
      const atual = (products ?? []).find((x: any) => x.id === target.id) as any;
      // Pausa o agente no servidor antes de ir para a lixeira — só se estava ativo
      if (atual?.status === "active") {
        await enviar(`/produtos-ativados/${target.id}/status`, { status: "pausado" });
      }
      // Marca como excluído (soft delete)
      await enviar(`/produtos-ativados/${target.id}`, { excluido_em: new Date().toISOString() }, "PATCH");

      toast.success("Produto movido para a lixeira", {
        description: atual?.numero_ia
          ? `O número ${atual.numero_ia} foi liberado para outros produtos. Dá para restaurar por 30 dias.`
          : "Disponível para restauração por 30 dias.",
      });
      qc.invalidateQueries({ queryKey: ["my-products"] });
      qc.invalidateQueries({ queryKey: ["trashed-products"] });
      setDeleting(null);

    } catch (e: any) {
      toast.error("Erro ao mover para a lixeira", { description: erroDetalhe(e) });
    } finally {
      setBusy(false);
    }
  };

  /** Restaura um produto da lixeira. Ele volta SEM número (foi liberado na lixeira): leva direto ao editor
   *  para escolher o número e ativar de novo (o agente, os prompts e o contrato são reaproveitados). */
  const handleRestore = async (p: any) => {
    try {
      const restaurado = await enviar<any>(`/produtos-ativados/${p.id}`, { excluido_em: null }, "PATCH");
      qc.invalidateQueries({ queryKey: ["my-products"] });
      qc.invalidateQueries({ queryKey: ["trashed-products"] });
      qc.invalidateQueries({ queryKey: ["product", p.id] });
      if (restaurado?.precisa_ativar) {
        toast.success("Produto restaurado", {
          description: "Escolha o número de WhatsApp e ative de novo.",
        });
        navigate(`/meus-produtos/${p.id}`);
      } else {
        toast.success("Produto restaurado");
      }
    } catch (e: any) {
      toast.error("Erro ao restaurar", { description: erroDetalhe(e) });
    }
  };

  /** Exclusão permanente: o servidor desativa o agente, libera o número e remove a linha. */
  const handlePurge = async () => {
    if (!purging) return;
    setBusy(true);
    try {
      await api(`/produtos-ativados/${purging.id}`, { metodo: "DELETE" });

      toast.success("Produto excluído permanentemente", {
        description: "O agente foi desativado e o número liberado.",
      });
      qc.invalidateQueries({ queryKey: ["my-products"] });
      qc.invalidateQueries({ queryKey: ["trashed-products"] });

      setPurging(null);
    } catch (e: any) {
      toast.error("Erro ao excluir definitivamente", { description: erroDetalhe(e) });
    } finally {
      setBusy(false);
    }
  };

  const [pendingStatus, setPendingStatus] = useState<Record<string, string>>({});

  // Limpa o pending assim que o produto chega no status esperado (via realtime)
  useEffect(() => {
    if (!products || Object.keys(pendingStatus).length === 0) return;
    setPendingStatus((cur) => {
      const next = { ...cur };
      let changed = false;
      for (const p of products as any[]) {
        if (next[p.id] && p.status === next[p.id]) {
          delete next[p.id];
          changed = true;
        }
      }
      return changed ? next : cur;
    });
  }, [products]);

  const togglePause = async (p: any, e: React.MouseEvent) => {
    e.preventDefault(); e.stopPropagation();
    if (p.provisioning_status === "building") {
      toast.info("Aguarde — agente ainda está sendo construído");
      return;
    }
    if (pendingStatus[p.id]) return; // já em andamento — bloqueia cliques concorrentes (#7)
    if (p.precisa_ativar) {
      // Voltou da lixeira sem número: ligar exige escolher o número (o servidor recusaria o ▶).
      navigate(`/meus-produtos/${p.id}`);
      return;
    }
    const next = p.status === "active" ? "paused" : "active";
    setPendingStatus((s) => ({ ...s, [p.id]: next })); // #7: trava o toggle (loading/disabled)
    try {
      // O servidor muda o status do agente e devolve a linha atualizada.
      await enviar(`/produtos-ativados/${p.id}/status`, { status: next === "active" ? "ativo" : "pausado" });
      await qc.invalidateQueries({ queryKey: ["my-products"] });
      toast.success(next === "active" ? "Produto ativado" : "Produto pausado");
    } catch (err: any) {
      toast.error("Falha ao mudar status", { description: err?.message });
    } finally {
      setPendingStatus((s) => { const n = { ...s }; delete n[p.id]; return n; }); // #7: destrava
    }
  };



  return (
    <div className="p-6 lg:p-8 space-y-5 max-w-[1400px] mx-auto">
      {/* Hero — mesma linguagem da Biblioteca */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className="relative overflow-hidden rounded-3xl border border-border bg-gradient-to-br from-card via-card to-success/5 px-6 py-7 lg:px-10 lg:py-9 min-h-[200px]"
      >
        <div className="absolute -top-24 -right-12 size-80 rounded-full bg-success/10 blur-3xl pointer-events-none" />
        <div className="hidden lg:block absolute right-[18rem] top-1/2 -translate-y-1/2 size-28 opacity-50 pointer-events-none" style={{ backgroundImage: "radial-gradient(hsl(var(--success)/0.35) 1.5px, transparent 1.5px)", backgroundSize: "16px 16px" }} />
        <div className="hidden lg:grid absolute right-8 top-7 size-11 rounded-2xl bg-success/10 border border-success/20 place-items-center pointer-events-none">
          <Sparkles className="size-5 text-success" />
        </div>
        <img src={folder3d} alt="" className="hidden md:block absolute right-2 lg:right-8 top-1/2 -translate-y-1/2 w-48 lg:w-64 xl:w-72 select-none pointer-events-none drop-shadow-xl" loading="eager" />

        <div className="relative max-w-[62%]">
          <div className="inline-flex flex-wrap items-center gap-2.5 px-3 py-1.5 rounded-full bg-success/10 border border-success/20 text-success text-[12px] font-semibold">
            <span className="inline-flex items-center gap-1.5"><Package className="size-3.5" /> {stats.total} produto{stats.total === 1 ? "" : "s"} na conta</span>
            <span className="w-px h-3 bg-success/30" />
            <span className="inline-flex items-center gap-1.5"><CircleDot className="size-3.5" /> {stats.active} em operação</span>
          </div>
          <h1 className="text-3xl lg:text-4xl font-bold tracking-tight mt-4 text-foreground">Meus agentes</h1>
          <div className="h-1 w-12 rounded-full bg-success mt-2.5" />
          <p className="text-sm text-muted-foreground mt-3 max-w-lg leading-relaxed">
            Os agentes ativados na sua conta, cada um com o seu número de WhatsApp. Ligue e pause, veja se o número está recebendo mensagens e abra o prompt, o follow-up, o conhecimento e o Laboratório de cada um.
          </p>
          <div className="flex flex-wrap gap-2 mt-5">
            <Button asChild className="bg-success hover:bg-success/90 text-success-foreground shadow-[0_4px_14px_-4px_hsl(var(--success)/0.45)]">
              <Link to="/biblioteca"><Plus className="size-4 mr-1.5" />Novo a partir da Biblioteca</Link>
            </Button>
          </div>
        </div>
      </motion.div>


      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard icon={Package}    label="Produtos" sub="Total ativados na conta"    value={stats.total}      tone="primary" />
        <StatCard icon={CircleDot}  label="Ativos"   sub="Atualmente em execução"     value={stats.active}     tone="success" />
        <StatCard icon={Pause}      label="Pausados" sub="Em modo pausado"            value={stats.paused}     tone="muted" />
      </div>

      {/* Toolbar */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-3">
        <div className="relative flex-1 sm:max-w-md">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Buscar por nome ou produto base..."
            className="pl-10 pr-9 h-11 rounded-xl bg-card border-border/60"
          />
          {search && (
            <button onClick={() => setSearch("")} className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors" aria-label="Limpar busca">
              <X className="size-4" />
            </button>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {([
            { id: "all",    label: "Todos",     count: stats.total },
            { id: "active", label: "Ativos",    count: stats.active },
            { id: "paused", label: "Pausados",  count: stats.paused },
            { id: "draft",  label: "Rascunhos", count: stats.draft },
            ...(stats.trash > 0
              ? [{ id: "trash" as Filter, label: "Lixeira", count: stats.trash }]
              : []),
          ] as { id: Filter; label: string; count: number }[]).map((t) => {
            const isTrash = t.id === "trash";
            const isActive = filter === t.id;
            return (
              <button
                key={t.id}
                onClick={() => setFilter(t.id)}
                className={`${isTrash ? "ml-1.5 pl-1.5 border-l border-border/70" : ""}`}
              >
                <span className={`px-3 py-1.5 rounded-full text-xs font-semibold transition flex items-center gap-1.5 border ${
                  isActive
                    ? isTrash
                      ? "bg-destructive text-destructive-foreground border-destructive shadow-[0_4px_14px_-4px_hsl(var(--destructive)/0.45)]"
                      : "bg-success text-success-foreground border-success shadow-[0_4px_14px_-4px_hsl(var(--success)/0.4)]"
                    : isTrash
                      ? "bg-card text-foreground/80 border-border hover:border-destructive/40 hover:bg-destructive/5 hover:text-destructive"
                      : "bg-card text-foreground/80 border-border hover:border-success/40 hover:bg-success/5 hover:text-foreground"
                }`}>
                  {isTrash && <Trash2 className="size-3.5" />}
                  {t.label}
                  <span className={`text-[10px] font-bold tabular-nums ${isActive ? "opacity-80" : "text-muted-foreground"}`}>{t.count}</span>
                </span>
              </button>
            );
          })}
        </div>
      </div>


      {/* Lista */}
      {isLoading ? (
        <div className="grid place-items-center py-20"><Loader2 className="size-8 text-primary animate-spin" /></div>
      ) : filter !== "trash" && (!products || products.length === 0) ? (avulsos.length > 0 ? null :
        <Card className="p-12 text-center bg-gradient-card backdrop-blur border-dashed">
          <div className="size-16 rounded-2xl bg-primary/10 grid place-items-center mx-auto mb-4">
            <Package className="size-8 text-primary" />
          </div>
          <h3 className="text-lg font-bold">Nenhum agente ativado ainda</h3>
          <p className="text-muted-foreground mt-2 max-w-md mx-auto">
            Escolha um produto da Biblioteca e ative: o agente fica aqui, com o número, o prompt e o follow-up.
          </p>
          <Button asChild className="mt-6 bg-gradient-primary text-white shadow-glow">
            <Link to="/biblioteca"><Plus className="size-4 mr-1.5" />Novo a partir da Biblioteca</Link>
          </Button>
        </Card>
      ) : filtered.length === 0 ? (
        <Card className="p-12 text-center bg-gradient-card backdrop-blur border-dashed">
          <Search className="size-10 text-muted-foreground mx-auto mb-3 opacity-50" />
          <h3 className="font-bold">Nenhum resultado</h3>
          <p className="text-muted-foreground text-sm mt-1">Ajuste a busca ou os filtros para ver mais produtos.</p>
        </Card>
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {filtered.map((p: any, i: number) => {
            const tmpl = p.source_template;
            const agentCount = (p.agents ?? []).length;
            const total = ROLE_ORDER.length;
            const pct = Math.round((agentCount / total) * 100);
            const CatIcon = getCategoryIcon(tmpl?.category);
            const sMeta = statusMeta[p.status] ?? statusMeta.draft;
            const isActive = p.status === "active";
            const building = p.provisioning_status === "building" && !p.deleted_at;
            const buildingSince = p.provisioning_started_at
              ? new Date(p.provisioning_started_at).getTime()
              : (p.updated_at ? new Date(p.updated_at).getTime() : 0);
            const stuck = building && buildingSince > 0 && Date.now() - buildingSince > 3 * 60 * 1000;
            // Cor por categoria (mesma do /biblioteca) — define o visual do card.
            const [c1, c2] = resolveGradient(tmpl?.cover_gradient, tmpl?.category);
            const trashed = !!p.deleted_at;
            // Estados especiais (lixeira/construindo/erro/pausado) sobrescrevem a cor da categoria.
            const special = trashed || stuck || building || p.status === "paused" || p.status === "error" || p.provisioning_status === "failed";

            return (
              <motion.div
                key={p.id}
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.04 }}
                className="group"
              >
                <Card
                  className={`relative overflow-hidden h-full flex flex-col rounded-2xl border transition-all duration-200 ${
                    trashed ? "bg-muted/30 border-border/70 hover:border-border" :
                    building && stuck ? "bg-destructive/5 border-destructive/30 hover:border-destructive/50" :
                    building ? "bg-card border-border hover:border-[var(--cat)]" :
                    p.status === "paused" ? "bg-warning/5 border-warning/30 hover:border-warning/50" :
                    p.status === "error" ? "bg-destructive/5 border-destructive/30 hover:border-destructive/50" :
                    "bg-card border-border hover:border-[var(--cat)] hover:shadow-[0_14px_34px_-16px_var(--catShadow)] hover:-translate-y-1"
                  }`}
                  style={{ ["--cat" as any]: c1, ["--catShadow" as any]: `${c1}59` }}
                >
                  {/* Glow suave da categoria no hover (igual /biblioteca) */}
                  {!special && (
                    <div className="absolute -right-10 -top-10 size-28 rounded-full blur-2xl opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none" style={{ background: `${c1}22` }} />
                  )}

                  {/* Top accent bar — cor da categoria (ou estado) */}
                  <div
                    className={`h-1 w-full ${
                      trashed ? "bg-border" :
                      building && stuck ? "bg-gradient-to-r from-destructive via-destructive/40 to-destructive animate-pulse" :
                      building ? "animate-pulse" :
                      p.provisioning_status === "failed" ? "bg-destructive" :
                      p.status === "paused" ? "bg-warning" :
                      p.status === "error" ? "bg-destructive" : ""
                    }`}
                    style={(building && !stuck) || (!special && p.provisioning_status !== "failed") ? { backgroundImage: `linear-gradient(90deg, ${c1}, ${c2})` } : undefined}
                  />

                  {/* Building overlay */}
                  {building && (
                    <div
                      className={`absolute inset-0 z-20 backdrop-blur-[3px] grid place-items-center ${stuck ? "bg-destructive/5" : "cursor-not-allowed"}`}
                      style={stuck ? undefined : { background: `${c1}0f` }}
                      onClick={(e) => { if (!stuck) { e.preventDefault(); e.stopPropagation(); } }}
                    >
                      <button
                        type="button"
                        aria-label="Cancelar e remover"
                        onClick={(e) => {
                          e.preventDefault(); e.stopPropagation();
                          setDeleting({ id: p.id, name: p.name, weaver_agent_id: (p as any).weaver_agent_id });
                        }}
                        className="absolute top-2 right-2 size-7 rounded-full bg-background border border-border hover:bg-destructive hover:text-destructive-foreground hover:border-destructive grid place-items-center transition-colors cursor-pointer shadow-sm z-10"
                      >
                        <X className="size-3.5" />
                      </button>

                      <div className="flex flex-col items-center gap-2 text-center px-4">
                        {stuck ? (
                          <>
                            <div className="size-10 rounded-full bg-destructive/15 grid place-items-center">
                              <AlertTriangle className="size-5 text-destructive" />
                            </div>
                            <div className="font-bold text-sm text-destructive">A construção demorou demais</div>
                            <div className="text-[11px] text-muted-foreground max-w-[240px]">
                              Algo deu errado no webhook. Tente reenviar ou abrir e salvar de novo.
                            </div>
                            <Button
                              size="sm"
                              variant="destructive"
                              className="mt-1 h-8 gap-1.5"
                              disabled={retryProduct.isPending}
                              onClick={(e) => {
                                e.preventDefault();
                                e.stopPropagation();
                                retryProduct.mutate(
                                  { agent_group_id: p.id },
                                  {
                                    onSuccess: () => toast.success("Webhook reenviado"),
                                    onError: (err: any) => toast.error(err?.message ?? "Falha ao reenviar"),
                                  },
                                );
                              }}
                            >
                              {retryProduct.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <RotateCw className="size-3.5" />}
                              Reenviar
                            </Button>
                          </>
                        ) : (
                          <>
                            {/* Loader premium na cor do produto (continuidade visual) */}
                            <div className="relative size-16 grid place-items-center">
                              {/* halo pulsante */}
                              <span className="absolute inset-0 rounded-full animate-build-halo" style={{ background: c1 }} />
                              {/* anel cônico girando (donut via máscara) */}
                              <span
                                className="absolute inset-0 rounded-full animate-build-spin"
                                style={{
                                  background: `conic-gradient(from 90deg, transparent 0deg, ${c1} 270deg, ${c2} 360deg)`,
                                  WebkitMask: "radial-gradient(farthest-side, transparent calc(100% - 3px), #000 calc(100% - 3px))",
                                  mask: "radial-gradient(farthest-side, transparent calc(100% - 3px), #000 calc(100% - 3px))",
                                }}
                              />
                              {/* núcleo com o ícone da categoria pulsando */}
                              <span className="relative size-11 rounded-full bg-background grid place-items-center shadow-sm">
                                <CatIcon className="size-5 animate-build-pulse" style={{ color: c1 }} />
                              </span>
                            </div>
                            <div>
                              <div className="font-bold text-sm flex items-center justify-center" style={{ color: c1 }}>
                                Construindo seu agente
                                <span className="ml-0.5 inline-flex">
                                  <span className="animate-build-dot">.</span>
                                  <span className="animate-build-dot [animation-delay:200ms]">.</span>
                                  <span className="animate-build-dot [animation-delay:400ms]">.</span>
                                </span>
                              </div>
                              <div className="text-[11px] text-muted-foreground max-w-[220px] mt-1">
                                Você será avisado aqui assim que estiver pronto para responder.
                              </div>
                            </div>
                            {/* barra de progresso indeterminada */}
                            <div className="mt-0.5 h-1 w-36 rounded-full overflow-hidden" style={{ background: `${c1}1f` }}>
                              <span className="block h-full w-1/2 rounded-full animate-build-bar" style={{ background: `linear-gradient(90deg, transparent, ${c1}, ${c2}, transparent)` }} />
                            </div>
                          </>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Header */}
                  <Link to={`/meus-produtos/${p.id}`} className={`block p-4 pb-2.5 ${building && !stuck ? "pointer-events-none" : ""}`}>
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2.5 min-w-0">
                        <div
                          className="size-11 rounded-xl grid place-items-center text-white shrink-0 shadow-sm"
                          style={{ backgroundImage: `linear-gradient(135deg, ${c1}, ${c2})` }}
                        >
                          <CatIcon className="size-[19px]" strokeWidth={2} />
                        </div>
                        <div className="min-w-0">
                          <h3 className="font-semibold text-sm leading-snug truncate">{p.name}</h3>
                          <div className="text-[11px] text-muted-foreground mt-0.5 truncate">
                            {tmpl ? `Baseado em ${tmpl.name}` : "Pipeline personalizado"}
                          </div>
                        </div>
                      </div>
                      {building ? (
                        <span className={`text-[10px] font-bold px-2 py-0.5 rounded-md border inline-flex items-center gap-1 shrink-0 ${
                          stuck ? BADGE.danger : BADGE.warning
                        }`}>
                          {stuck ? <AlertTriangle className="size-3" /> : <Loader2 className="size-3 animate-spin" />}
                          {stuck ? "Travado" : "Construindo"}
                        </span>
                      ) : trashed ? (
                        <span className={`text-[10px] font-bold px-2 py-0.5 rounded-md border inline-flex items-center gap-1 shrink-0 ${BADGE.muted}`}>
                          <Trash2 className="size-3" />
                          Na lixeira
                        </span>
                      ) : p.provisioning_status === "failed" ? (
                        <span className={`text-[10px] font-bold px-2 py-0.5 rounded-md border inline-flex items-center gap-1 shrink-0 ${BADGE.danger}`}>
                          <AlertTriangle className="size-3" />
                          Falhou
                        </span>
                      ) : p.precisa_ativar ? (
                        <span className={`text-[10px] font-bold px-2 py-0.5 rounded-md border inline-flex items-center gap-1 shrink-0 ${BADGE.warning}`}>
                          <Phone className="size-3" />
                          Sem número
                        </span>
                      ) : (
                        <span className={`text-[10px] font-bold px-2 py-0.5 rounded-md border inline-flex items-center gap-1 shrink-0 ${statusStyle[p.status]}`}>
                          <sMeta.Icon className={`size-3 ${isActive ? "animate-pulse" : ""}`} />
                          {sMeta.label}
                        </span>
                      )}
                    </div>
                  </Link>

                  {/* Atualização do catálogo disponível (admin subiu a versão) */}
                  {p.atualizacao_disponivel && !building && !trashed && (
                    <Link
                      to={`/meus-produtos/${p.id}`}
                      className="mx-4 mb-2 flex items-center gap-1.5 rounded-lg border border-primary/30 bg-primary/5 px-2.5 py-1.5 text-[11px] font-semibold text-[#0a6b25] dark:text-green-200 hover:bg-primary/10 transition-colors"
                    >
                      <Sparkles className="size-3.5 shrink-0 text-primary" /> Atualização disponível
                      <span className="ml-auto text-[10px] font-normal opacity-80">v{p.versao_catalogo}</span>
                    </Link>
                  )}

                  {/* Produto ativo com follow-up desligado: aviso discreto + "Ligar com o padrão" (docs/FOLLOWUP.md) */}
                  {isActive && !building && !trashed && !p.precisa_ativar && (
                    <AvisoFollowupDesligado className="mx-4 mb-2" idAtivado={p.id} situacao={(p as any).followup_situacao}
                      aoLigar={() => qc.invalidateQueries({ queryKey: ["my-products"] })} />
                  )}

                  {/* Descrição */}
                  <div className="px-4 pb-3 flex-1">
                    {tmpl?.category && (
                      <div
                        className="inline-flex items-center text-[10px] uppercase tracking-wider font-bold mb-1.5 px-1.5 py-0.5 rounded-md"
                        style={{ background: `${c1}14`, color: c1, border: `1px solid ${c1}26` }}
                      >
                        {tmpl.category}
                      </div>
                    )}
                    <p className="text-xs text-muted-foreground line-clamp-3 leading-relaxed">
                      {tmpl?.description_short ?? "Pipeline de agentes personalizado para a sua conta."}
                    </p>
                  </div>

                  {/* Meta info */}
                  <div className="px-4 py-2.5 border-t border-border/60 bg-muted/20 flex items-center gap-2.5 text-[11px] text-muted-foreground flex-wrap">
                    <span className="inline-flex items-center gap-1">
                      <Activity className="size-3" />
                      {p.channels?.length ?? 0} canal(is)
                    </span>
                    {(p as any).numero_ia && (
                      <>
                        <span className="size-1 rounded-full bg-border" />
                        <span className="inline-flex items-center gap-1 font-mono text-foreground/80">
                          {(p as any).numero_ia}
                        </span>
                      </>
                    )}
                    <span className="size-1 rounded-full bg-border" />
                    <span>
                      {p.created_at ? `Criado ${new Date(p.created_at).toLocaleDateString("pt-BR")}` : "—"}
                    </span>
                  </div>


                  {/* Saúde do número: selo, tipo (oficial = janela de 24 h) e Testar conexão */}
                  {!trashed && !building && (() => {
                    const s = p.weaver_agent_id ? saudePorAgente.get(p.weaver_agent_id) : undefined;
                    const semNumero = p.precisa_ativar || !p.weaver_agent_id || s?.selo.tipo === "sem_numero";
                    if (!s && !semNumero) return null;
                    return (
                      <div className="px-4 pt-3 pb-2 border-t border-border/60 flex items-center gap-1.5 flex-wrap">
                        <SeloSaude selo={semNumero ? { tipo: "sem_numero", minutos: null } : s!.selo} />
                        {!semNumero && <TipoNumero tipo={s!.tipo} aviso={s!.aviso_tipo} />}
                        {!semNumero && s!.id_canal && <span className="ml-auto"><TestarConexao compacto idCanal={s!.id_canal} numero={p.numero_ia ?? undefined} /></span>}
                      </div>
                    );
                  })()}

                  {/* Abas do agente (as mesmas do submenu): Prompt, Follow-up, Conhecimento, Laboratório */}
                  {!trashed && !building && p.weaver_agent_id && (
                    <div className="px-3 pb-3 pt-1 space-y-2">
                      {/* Atalhos do agente: ícone em cima e nome embaixo, os 4 lado a lado (cabem no cartão estreito). */}
                      <nav aria-label={`Abrir ${p.name}`} className="grid grid-cols-4 gap-1.5">
                        {ABAS_DO_AGENTE.map(({ chave, rotulo, Icone }) => (
                          <Link key={chave} to={`/agentes/${p.weaver_agent_id}/${chave}`} title={rotulo}
                            className="flex min-w-0 flex-col items-center gap-1 rounded-xl border border-border/70 bg-muted/20 px-1 py-2 text-[10.5px] font-semibold leading-none text-muted-foreground transition-colors hover:border-[var(--cat)] hover:bg-muted/40 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00bc33]">
                            <Icone className="size-4 shrink-0" aria-hidden />
                            <span className="w-full truncate text-center">{rotulo === "Conhecimento" ? "Base" : rotulo === "Laboratório" ? "Testar" : rotulo}</span>
                          </Link>
                        ))}
                      </nav>
                      {/* Filtro de número numa linha própria, com o estado à vista. */}
                      <FiltroNumero idAgente={p.weaver_agent_id} />
                    </div>
                  )}

                  {/* Actions */}
                  {p.deleted_at ? (() => {
                    const deletedMs = new Date(p.deleted_at).getTime();
                    const daysLeft = Math.max(0, 30 - Math.floor((Date.now() - deletedMs) / 86400000));
                    const urgent = daysLeft <= 7;
                    const warn = daysLeft <= 14 && !urgent;
                    return (
                      <div className="p-3 pt-2 border-t border-border/60 bg-muted/20 space-y-2">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-[11px] text-muted-foreground inline-flex items-center gap-1.5">
                            <Trash2 className="size-3" /> Na lixeira
                          </span>
                          <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-md border inline-flex items-center gap-1 ${
                            urgent ? BADGE.danger :
                            warn ? BADGE.warning :
                            BADGE.muted
                          }`}>
                            restam {daysLeft} {daysLeft === 1 ? "dia" : "dias"}
                          </span>
                        </div>
                        {p.weaver_agent_id && (
                          <p className="text-[11px] leading-snug text-muted-foreground inline-flex items-start gap-1.5">
                            <Phone className="size-3 mt-0.5 shrink-0" />
                            <span>
                              {p.numero_liberado
                                ? <>O número <span className="font-mono text-foreground/80">{p.numero_liberado}</span> foi liberado</>
                                : "O número foi liberado"} e pode ser usado por outro produto. Ao restaurar, escolha o número de novo.
                            </span>
                          </p>
                        )}
                        <div className="flex items-center gap-2">
                          <Button
                            size="sm"
                            variant="outline"
                            className="flex-1 text-success border-success/30 hover:bg-success/10 hover:text-success"
                            onClick={() => handleRestore(p)}
                          >
                            <RotateCcw className="size-3.5 mr-1.5" />Restaurar
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            className="text-destructive border-destructive/30 hover:bg-destructive/10 hover:text-destructive"
                            onClick={() => setPurging({
                              id: p.id,
                              name: p.name,
                              source_template_id: p.source_template_id ?? null,
                              workspace_id: p.workspace_id,
                            })}
                          >
                            <Trash2 className="size-3.5 mr-1.5" />Excluir
                          </Button>
                        </div>
                      </div>
                    );
                  })() : p.precisa_ativar ? (
                    <div className="p-3 pt-2 border-t border-border/60 flex items-center gap-2">
                      <Button
                        size="sm"
                        className="flex-1 bg-gradient-primary text-white"
                        title="Voltou da lixeira sem número: escolha o número de WhatsApp e ative"
                        onClick={() => navigate(`/meus-produtos/${p.id}`)}
                      >
                        <Phone className="size-3.5 mr-1.5" />Escolher número e ativar
                      </Button>
                      <ButtonHoldAndRelease
                        compact
                        loading={busy}
                        title="Segure para mover para a lixeira"
                        onConfirm={() => handleDelete({ id: p.id, name: p.name, weaver_agent_id: (p as any).weaver_agent_id })}
                      />
                    </div>
                  ) : (
                    <div className="p-3 pt-2.5 border-t border-border/60 flex items-center gap-2 [&>*:not(:first-child)]:shrink-0">
                      <Button
                        size="sm"
                        variant="outline"
                        className="flex-1 min-w-0"
                        onClick={() => navigate(`/meus-produtos/${p.id}`)}
                      >
                        <Settings2 className="size-3.5 mr-1.5" />Editar
                      </Button>
                      <StatusToggle
                        active={isActive}
                        loading={!!pendingStatus[p.id]}
                        disabled={!!pendingStatus[p.id]}
                        onToggle={(e) => togglePause(p, e)}
                      />
                      <ButtonHoldAndRelease
                        compact
                        loading={busy}
                        title="Segure para mover para a lixeira"
                        onConfirm={() => handleDelete({ id: p.id, name: p.name, weaver_agent_id: (p as any).weaver_agent_id })}
                      />
                    </div>
                  )}

                </Card>
              </motion.div>
            );
          })}
        </div>
      )}

      {!isLoading && avulsos.length > 0 && filter !== "trash" && <AgentesAvulsos agentes={avulsos} />}

      <AlertDialog open={!!deleting} onOpenChange={(o) => { if (!o) { setDeleting(null); setDeleteConfirm(""); } }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Mover para a lixeira</AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="space-y-3">
                <p>
                  <strong>{deleting?.name}</strong> será pausado e enviado para a lixeira, e o
                  <strong> número de WhatsApp dele fica livre</strong> para outro produto.
                  Você pode restaurá-lo nos próximos <strong>30 dias</strong>: ele volta sem número e você
                  escolhe o número de novo para ativar.
                  Após esse prazo, a exclusão se torna permanente.
                </p>
                <div className="space-y-1.5">
                  <p className="text-sm">Para confirmar, digite <strong>excluir</strong> abaixo:</p>
                  <Input
                    value={deleteConfirm}
                    onChange={(e) => setDeleteConfirm(e.target.value)}
                    placeholder="excluir"
                    autoFocus
                  />
                </div>
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => { e.preventDefault(); handleDelete(); setDeleteConfirm(""); }}
              disabled={busy || deleteConfirm.trim().toLowerCase() !== "excluir"}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {busy ? <Loader2 className="size-4 mr-1.5 animate-spin" /> : <Trash2 className="size-4 mr-1.5" />}
              Mover para lixeira
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>



      <AlertDialog open={!!purging} onOpenChange={(o) => { if (!o) { setPurging(null); setPurgeConfirm(""); } }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Excluir permanentemente</AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="space-y-3">
                <p>
                  <strong>{purging?.name}</strong> e todos os seus agentes serão removidos definitivamente
                  da sua conta e do sistema. Esta ação <strong>não pode ser desfeita</strong>.
                </p>
                <div className="space-y-1.5">
                  <p className="text-sm">Para confirmar, digite <strong>excluir</strong> abaixo:</p>
                  <Input
                    value={purgeConfirm}
                    onChange={(e) => setPurgeConfirm(e.target.value)}
                    placeholder="excluir"
                    autoFocus
                  />
                </div>
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => { e.preventDefault(); handlePurge(); setPurgeConfirm(""); }}
              disabled={busy || purgeConfirm.trim().toLowerCase() !== "excluir"}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {busy ? <Loader2 className="size-4 mr-1.5 animate-spin" /> : <Trash2 className="size-4 mr-1.5" />}
              Excluir permanentemente
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>


    </div>
  );
};

/** Agentes da conta que não vieram de um produto da Biblioteca (criados pelo caminho antigo). */
const AgentesAvulsos = ({ agentes }: { agentes: SaudeAgente[] }) => (
  <section aria-label="Outros agentes" className="space-y-2.5">
    <div>
      <h2 className="text-sm font-bold text-foreground">Outros agentes da conta</h2>
      <p className="text-xs text-muted-foreground">Criados fora da Biblioteca. Abra para editar, ligar ou pausar.</p>
    </div>
    <div className="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
      {agentes.map((a) => (
        <Card key={a.id} className="rounded-2xl border bg-card overflow-hidden flex flex-col" style={{ ["--cat" as any]: "#00BC33" }}>
          <Link to={`/agentes/${a.id}`} className="block p-4 pb-2.5">
            <div className="flex items-start justify-between gap-2">
              <div className="flex items-center gap-2.5 min-w-0">
                <div className="size-11 rounded-xl grid place-items-center text-white shrink-0 shadow-sm bg-gradient-to-br from-[#2BD45A] to-[#00852A]"><Bot className="size-[19px]" /></div>
                <div className="min-w-0">
                  <h3 className="font-semibold text-sm leading-snug truncate">{a.nome}</h3>
                  <div className="text-[11px] text-muted-foreground mt-0.5 truncate font-mono">{a.numero_normalizado ?? "sem número"}</div>
                </div>
              </div>
              <span className={`text-[10px] font-bold px-2 py-0.5 rounded-md border inline-flex items-center gap-1 shrink-0 ${a.situacao === "ativo" ? BADGE.success : BADGE.warning}`}>
                {a.situacao === "ativo" ? <CircleDot className="size-3" /> : <Pause className="size-3" />}{a.situacao === "ativo" ? "Ativo" : "Pausado"}
              </span>
            </div>
          </Link>
          <div className="px-4 py-2 border-t border-border/60 flex items-center gap-1.5 flex-wrap">
            <SeloSaude selo={a.selo} />
            {a.selo.tipo !== "sem_numero" && <TipoNumero tipo={a.tipo} aviso={a.aviso_tipo} />}
            {a.id_canal && <TestarConexao compacto idCanal={a.id_canal} numero={a.numero_normalizado ?? undefined} className="ml-auto" />}
          </div>
          <nav aria-label={`Abrir ${a.nome}`} className="px-3 pb-2.5 pt-1 flex flex-wrap gap-1">
            {ABAS_DO_AGENTE.map(({ chave, rotulo, Icone }) => (
              <Link key={chave} to={`/agentes/${a.id}/${chave}`}
                className="inline-flex items-center gap-1 rounded-md border border-border/70 bg-muted/20 px-2 py-1 text-[11px] font-semibold text-muted-foreground hover:border-[var(--cat)] hover:bg-muted/40 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00bc33] transition-colors">
                <Icone className="size-3 shrink-0" aria-hidden />{rotulo}
              </Link>
            ))}
          </nav>
        </Card>
      ))}
    </div>
  </section>
);

const StatCard = ({
  icon: Icon, label, sub, value, tone,
}: { icon: any; label: string; sub?: string; value: number; tone: "default" | "success" | "muted" | "primary" }) => {
  const toneClass = {
    default: "bg-foreground/5 text-foreground",
    success: "bg-success/10 text-success",
    muted: "bg-muted text-muted-foreground",
    primary: "bg-success/10 text-success",
  }[tone];
  return (
    <div
      className="relative overflow-hidden rounded-xl border border-border bg-card px-3.5 py-2.5 flex items-center gap-3 hover:border-success/30 transition-colors"
      title={sub}
    >
      <div className={`size-9 rounded-lg grid place-items-center shrink-0 ${toneClass}`}>
        <Icon className="size-[18px]" />
      </div>
      <div className="min-w-0 flex-1 flex items-baseline gap-2">
        <span className="text-xl font-bold leading-none tracking-tight tabular-nums">{value}</span>
        <span className="text-[13px] font-semibold text-muted-foreground truncate">{label}</span>
      </div>
    </div>
  );
};

export default MeusProdutos;
