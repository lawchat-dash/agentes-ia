import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api, enviar } from "@/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { Switch } from "@/components/ui/switch";
import { ArrowLeft, Save, Loader2, CheckCircle2, AlertCircle, Plus, MessageSquare, Shield, X, ListChecks, Info, Sparkles, Palette, User, Check, Repeat, Circle, Building2, Download, BookOpen, Hourglass, Music, ArrowRightLeft } from "lucide-react";
import BibliotecaConhecimentoManager from "@/components/admin/BibliotecaConhecimentoManager";
import { categories, resolveGradient, GRADIENT_PRESETS } from "@/data/categories";
import { RichPromptEditor, RichPromptEditorHandle } from "@/components/agent/RichPromptEditor";
import { RespostaComMidia } from "@/components/agent/RespostaComMidia";
import { ROLE_ORDER, ROLE_META, ALL_ROLES_ORDERED, AgentRole } from "@/hooks/useProducts";
import { handoffLabelsFor, normalizarRotulosAntigos, TOOL_LABELS } from "@/data/handoffTargets";
import { DEFAULT_ROLE_BLOCKS } from "@/data/roleBlocks";
import { CrmStage, STAGE_ORDER, STAGE_LABELS, FollowupCadenceItem } from "@/hooks/useFollowups";
import { CadenceBuilder } from "@/components/followup/CadenceBuilder";
import { CrmStagesPicker } from "@/components/followup/CrmStagesPicker";
import { FollowupAgentEditor } from "@/components/followup/FollowupAgentEditor";
import { MediaLibrary } from "@/components/agent/MediaLibrary";
import { useBibliotecaMidia } from "@/hooks/useBibliotecaMidia";
import { FrasesTrocaDialog } from "@/components/agent/FrasesTrocaDialog";
import { FraseEntradaCard } from "@/components/agent/FraseEntradaCard";
import { carregarFrasesTroca, FrasesProdutoProvider, useFrasesTroca } from "@/hooks/useFrasesTroca";
import { useRascunhoLocal } from "@/hooks/useRascunhoLocal";
import { RecuperarRascunhoBanner } from "@/components/common/RecuperarRascunhoBanner";
import {
  COR_TRANSFERENCIA, agentesSemFraseDeSaida, trocarTokenPorTexto, expandirFrasesParaBot, fraseDaEtapa, getFrasesTroca, temTokenTransferencia,
} from "@/data/frasesTroca";

// Editor do catálogo. Espelha EXATAMENTE o que o cliente
// edita ao ativar (Ativar.tsx): identidade do produto + os 5 agentes do funil
// (agentesia_biblioteca_agentes) com prompt rico ({{campos}} e @handoff) +
// padrões de FAQ/objeções/regras (agentesia_biblioteca_produtos), via /api/admin/biblioteca.

// ---------- Tipos ----------
type ProdStatus = "rascunho" | "em_breve" | "publicado";

const STATUS_META: Record<ProdStatus, { label: string; hint: string; badge: "default" | "secondary" | "outline" }> = {
  rascunho: { label: "Rascunho", hint: "Só o admin vê. Não aparece no catálogo do cliente.", badge: "outline" },
  em_breve: { label: "Em breve", hint: "Aparece no catálogo apagado, com selo \"Em breve\". Não ativável.", badge: "secondary" },
  publicado: { label: "Publicado", hint: "Disponível para o cliente ativar.", badge: "default" },
};

type Form = {
  id?: string;
  slug: string;
  nome: string;
  categoria: string;
  descricao_curta: string;
  descricao_longa: string;
  etiquetas: string; // csv na UI
  icone: string;
  capa_gradiente: string; // "c1,c2" hex (cor própria) ou vazio = usa categoria
  modelo_recomendado: string;
  plano_minimo: string;
  versao: string;
  status: ProdStatus;
  // Mensagens padrão do produto (fallback)
  mensagem_boas_vindas: string;
  mensagem_despedida: string;
  mensagem_fallback: string;
  mensagem_fora_horario: string;
  // Padrões de conteúdo (semeiam o rascunho do cliente ao ativar)
  regras_markdown: string;
  dados_escritorio: string;
  // Etapa OPCIONAL "Período de Graça" (só o admin liga/desliga): quando true, o produto
  // ganha o 6º agente (após o SDR) e o cliente passa a ver essa etapa no funil.
  oferece_periodo_graca: boolean;
  // Produto com MÍDIA (áudio/vídeo): quando "audio", o cliente (com plano de mídia) ganha
  // a "Edição rápida de mídias" e os marcadores [[midia:]]. "texto" = só texto.
  modo_midia: "texto" | "audio";
};

// Estado editável de cada agente do funil — 1:1 com o que o cliente vê.
type AgenteForm = {
  id: string | null;          // biblioteca_agentes.id (null = ainda não existe)
  papel: AgentRole;
  nome_exibicao: string;
  descricao: string;
  mensagem_boas_vindas: string;
  mensagem_despedida: string;
  mensagem_fallback: string;
  modelo_recomendado: string;
  prompt: string;             // freeform (markdown) — o que o cliente edita
  handoff: string;            // gatilho de transferência
  config_modelo: any;         // preservado
  regras_handoff: any[];      // preservado
  faq: FaqItem[];             // 1ª classe (mig 0079) — antes em config_modelo.faq_items
  objecoes: ObjItem[];        // 1ª classe (mig 0079) — antes em config_modelo.objecoes
  regras_gerais: string;      // 1ª classe (mig 0079) — antes em config_modelo.rules_markdown
};

type FaqItem = { pergunta: string; resposta: string };
type ObjItem = { titulo: string; resposta: string };

const emptyForm: Form = {
  slug: "", nome: "", categoria: "Trabalhista", descricao_curta: "", descricao_longa: "",
  etiquetas: "", icone: "⚖️", capa_gradiente: "", modelo_recomendado: "openai/gpt-4.1-mini", plano_minimo: "start",
  versao: "1.0.0", status: "rascunho", mensagem_boas_vindas: "", mensagem_despedida: "",
  mensagem_fallback: "", mensagem_fora_horario: "", regras_markdown: "", dados_escritorio: "",
  oferece_periodo_graca: false, modo_midia: "texto",
};

const slugify = (s: string) =>
  s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

// Estado de cada agente de follow-up por etapa do CRM (padrão do catálogo).
// Aqui não há tabela de follow-ups do catálogo: fica em padrao_followup.agentes (jsonb do produto).
type FupAgente = { id: string | null; name: string; prompt: string; enabled: boolean };
const emptyFup: Record<CrmStage, FupAgente> = {
  sdr: { id: null, name: "", prompt: "", enabled: false },
  closer: { id: null, name: "", prompt: "", enabled: false },
  contrato: { id: null, name: "", prompt: "", enabled: false },
  assinatura: { id: null, name: "", prompt: "", enabled: false },
};

// ---------- Conversão blocos <-> (prompt freeform + gatilho), igual ao cliente ----------
/** Texto efetivo do prompt: freeform → senão converte blocos estruturados em markdown. */
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
/** Monta os blocos no MESMO shape que o cliente salva (freeform + handoff_trigger). */
const buildBlocks = (prompt: string, handoff: string) => [
  { id: "freeform", type: "freeform", icon: "📝", label: "Prompt", content: prompt },
  { id: "handoff_trigger", type: "handoff_trigger", icon: "🔀", label: "Gatilho de transferência", content: handoff },
];

/** Baixa o prompt de um agente como arquivo .md (só painel admin). */
const baixarPromptMd = (papel: string, nome: string, prompt: string) => {
  const cabecalho = `# Prompt — ${nome || papel}\n\n> Agente: \`${papel}\`\n\n---\n\n`;
  const blob = new Blob([cabecalho + (prompt ?? "")], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `prompt-${papel}.md`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
};

/** Linha do catálogo (ou default por papel) → estado de edição do agente. */
const agenteFromRow = (papel: AgentRole, row: any | null): AgenteForm => {
  const blocosDefault = DEFAULT_ROLE_BLOCKS[papel] ?? [];
  const blocos = Array.isArray(row?.blocos_prompt) && row.blocos_prompt.length ? row.blocos_prompt : blocosDefault;
  return {
    id: row?.id ?? null,
    papel,
    nome_exibicao: row?.nome_exibicao ?? ROLE_META[papel]?.label ?? papel,
    descricao: row?.descricao ?? "",
    mensagem_boas_vindas: row?.mensagem_boas_vindas ?? "",
    mensagem_despedida: row?.mensagem_despedida ?? "",
    mensagem_fallback: row?.mensagem_fallback ?? "",
    modelo_recomendado: row?.modelo_recomendado ?? "",
    prompt: normalizarRotulosAntigos(row?.texto_prompt ?? blocksToText(blocos)),
    handoff: extractHandoffTrigger(blocos),
    config_modelo: row?.config_modelo ?? {},
    regras_handoff: Array.isArray(row?.regras_handoff) ? row.regras_handoff : [],
    // Aqui FAQ/objeções/regras por agente moram no config_modelo (sem colunas próprias).
    faq: Array.isArray(row?.faq) ? row.faq
      : Array.isArray(row?.config_modelo?.faq_items) ? row.config_modelo.faq_items.map((f: any) => ({ pergunta: f?.q ?? "", resposta: f?.a ?? "" })) : [],
    objecoes: Array.isArray(row?.objecoes) ? row.objecoes
      : Array.isArray(row?.config_modelo?.objecoes) ? row.config_modelo.objecoes.map((o: any) => ({ titulo: o?.gatilho ?? "", resposta: o?.resposta ?? "" })) : [],
    regras_gerais: row?.regras_gerais ?? row?.config_modelo?.rules_markdown ?? "",
  };
};

export default function AdminProdutoEditor() {
  const { id } = useParams<{ id: string }>();
  const isNew = !id || id === "novo";
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [tab, setTab] = useState("identidade");
  const [loading, setLoading] = useState(!isNew);
  const [saving, setSaving] = useState(false);
  // Só mostra a pendência de validação depois que o admin mexeu no formulário (saiu de um campo
  // obrigatório) ou tentou salvar — antes disso, um produto novo vazio não "acusa erro".
  const [tocado, setTocado] = useState(false);
  const [form, setForm] = useState<Form>(emptyForm);
  const [agentes, setAgentes] = useState<AgenteForm[]>(ROLE_ORDER.map((r) => agenteFromRow(r, null)));
  const [activeRoleIdx, setActiveRoleIdx] = useState(0);
  // Linha do agente 'periododegraca' já salva — preserva o prompt ao religar o toggle na sessão.
  const pgRowRef = useRef<any | null>(null);
  /** Liga/desliga a etapa Período de Graça (EXCLUSIVO do admin): insere/remove o 6º agente
   *  (após o SDR). Quando ligado, o cliente passa a ver essa etapa no funil do produto. */
  const togglePeriodoGraca = (on: boolean) => {
    setForm((f) => ({ ...f, oferece_periodo_graca: on }));
    setAgentes((arr) => {
      const has = arr.some((a) => a.papel === "periododegraca");
      if (on && !has) {
        const seed = agenteFromRow("periododegraca", pgRowRef.current);
        const out = [...arr];
        const sdrIdx = out.findIndex((a) => a.papel === "sdr");
        out.splice(sdrIdx >= 0 ? sdrIdx + 1 : out.length, 0, seed);
        return out;
      }
      if (!on && has) return arr.filter((a) => a.papel !== "periododegraca");
      return arr;
    });
    setActiveRoleIdx(0);
    setEditorKey((n) => n + 1);
  };
  // Bump força o RichPromptEditor a remontar quando os agentes carregam (senão a key
  // {papel} não muda e o editor fica com o conteúdo vazio inicial, ignorando o prompt salvo).
  const [editorKey, setEditorKey] = useState(0);
  const [faqItems, setFaqItems] = useState<FaqItem[]>([]);
  const [objItems, setObjItems] = useState<ObjItem[]>([]);
  // Follow-up (padrão do catálogo)
  const [fupCadence, setFupCadence] = useState<FollowupCadenceItem[]>([]);
  const [fupRestart, setFupRestart] = useState(true);
  const [fupAgentes, setFupAgentes] = useState<Record<CrmStage, FupAgente>>(emptyFup);
  const [fupActive, setFupActive] = useState<CrmStage>("sdr");
  const richRef = useRef<RichPromptEditorHandle>(null);
  const [libraryOpen, setLibraryOpen] = useState(false);
  // Frases para Transferência (fixas, só super admin): cadastro + categoria "Transferência" no @.
  const [frasesOpen, setFrasesOpen] = useState(false);
  // Frases DESTE produto (cada produto tem as suas — editar aqui não afeta outros produtos).
  const { data: frasesTroca } = useFrasesTroca(form.id ?? null);
  const { items: midiaItems } = useBibliotecaMidia();
  // preservados intactos (não editados aqui), reenviados no save
  const [preserva, setPreserva] = useState<{ config_modelo: any; padrao_followup: any }>({
    config_modelo: { temperature: 0.5, max_tokens: 1024 },
    padrao_followup: {},
  });

  useEffect(() => {
    if (isNew) return;
    (async () => {
      setLoading(true);
      let t: any = null;
      let erro: string | null = null;
      try {
        t = await api<any>(`/biblioteca/produtos/${encodeURIComponent(id!)}`);
      } catch (e: any) {
        erro = e?.status === 404 ? null : (e?.message ?? null);
      }
      if (!t) {
        toast.error(erro ?? "Produto não encontrado");
        navigate("/admin/produtos");
        return;
      }
      setForm({
        id: t.id,
        slug: t.slug ?? "",
        nome: t.nome ?? "",
        categoria: t.categoria ?? "Trabalhista",
        descricao_curta: t.descricao_curta ?? "",
        descricao_longa: t.descricao_longa ?? "",
        etiquetas: Array.isArray(t.etiquetas) ? t.etiquetas.join(", ") : "",
        icone: t.icone ?? "⚖️",
        capa_gradiente: t.capa_gradiente ?? "",
        modelo_recomendado: t.modelo_recomendado ?? "openai/gpt-4.1-mini",
        plano_minimo: t.plano_minimo ?? "starter",
        versao: t.versao ?? "1.0.0",
        status: (t.status ?? (t.publicado ? "publicado" : "rascunho")) as ProdStatus,
        mensagem_boas_vindas: t.mensagem_boas_vindas ?? "",
        mensagem_despedida: t.mensagem_despedida ?? "",
        mensagem_fallback: t.mensagem_fallback ?? "",
        mensagem_fora_horario: t.mensagem_fora_horario ?? "",
        regras_markdown: t.regras_markdown ?? "",
        dados_escritorio: t.dados_escritorio ?? "",
        oferece_periodo_graca: !!t.oferece_periodo_graca,
        modo_midia: (t.modo_midia === "audio" ? "audio" : "texto"),
      });
      setFaqItems(Array.isArray(t.faq) ? t.faq : []);
      setObjItems(Array.isArray(t.objecoes) ? t.objecoes : []);
      setPreserva({
        config_modelo: t.config_modelo ?? { temperature: 0.5, max_tokens: 1024 },
        padrao_followup: t.padrao_followup ?? {},
      });

      // Agentes do funil (o que o cliente realmente consome)
      const ags = await api<any[]>(`/biblioteca/produtos/${t.id}/agentes`).catch(() => [] as any[]);
      const byRole = new Map<string, any>((ags ?? []).map((a: any) => [a.papel, a]));
      // Período de Graça: quando o produto oferece, a lista ganha o 6º papel (após o SDR).
      const oferecePg = !!t.oferece_periodo_graca;
      pgRowRef.current = byRole.get("periododegraca") ?? null;
      const rolesDoProduto = oferecePg ? ALL_ROLES_ORDERED : ROLE_ORDER;
      setAgentes(rolesDoProduto.map((r) => agenteFromRow(r, byRole.get(r) ?? null)));
      setEditorKey((n) => n + 1); // remonta o editor com os prompts recém-carregados

      // Follow-up padrão do catálogo: cadência/restart em padrao_followup + prompts por etapa
      const pf = (t.padrao_followup ?? {}) as any;
      setFupCadence(Array.isArray(pf.cadence) ? pf.cadence : []);
      setFupRestart(pf.restart_on_reply !== false);
      const fupsSalvos = (pf.agentes ?? {}) as Record<string, any>;
      const ag = { ...emptyFup };
      STAGE_ORDER.forEach((st) => {
        const row = fupsSalvos[st];
        ag[st] = {
          id: null,
          name: row?.nome_agente ?? "",
          prompt: row?.prompt ?? "",
          enabled: !!row?.habilitado_padrao,
        };
      });
      setFupAgentes(ag);

      setLoading(false);
    })();
  }, [id, isNew, navigate]);

  // Rede de segurança: copia o que está sendo editado p/ o navegador (a cada 3s e ao ocultar/
  // fechar a aba). Se a página recarregar antes de salvar, oferece "Recuperar alterações".
  const rascunhoLocal = useRascunhoLocal({
    chave: `admin-produto:${isNew ? "novo" : id}`,
    habilitado: !loading,
    obter: () => ({ form, agentes, faqItems, objItems, fupCadence, fupRestart, fupAgentes, tab, activeRoleIdx }),
    // Só conteúdo: sem posição de aba nem ids (ids mudam ao salvar e não são edição do admin).
    conteudo: (d) => JSON.parse(JSON.stringify({ ...d, tab: undefined, activeRoleIdx: undefined },
      (k, v) => (k === "id" ? undefined : v))),
  });
  const aplicarRascunhoLocal = () => {
    const d = rascunhoLocal.recuperar();
    if (!d) return;
    if (d.form) setForm(d.form);
    if (Array.isArray(d.agentes) && d.agentes.length) setAgentes(d.agentes);
    if (Array.isArray(d.faqItems)) setFaqItems(d.faqItems);
    if (Array.isArray(d.objItems)) setObjItems(d.objItems);
    if (Array.isArray(d.fupCadence)) setFupCadence(d.fupCadence);
    if (typeof d.fupRestart === "boolean") setFupRestart(d.fupRestart);
    if (d.fupAgentes) setFupAgentes(d.fupAgentes);
    if (typeof d.tab === "string") setTab(d.tab);
    const n = Array.isArray(d.agentes) ? d.agentes.length : agentes.length;
    if (typeof d.activeRoleIdx === "number") setActiveRoleIdx(Math.min(Math.max(0, d.activeRoleIdx), Math.max(0, n - 1)));
    setEditorKey((k) => k + 1); // remonta o editor de prompt com o texto recuperado
    toast.success("Alterações recuperadas", { description: "Revise e salve para não perder de novo." });
  };

  const updAgente = (idx: number, patch: Partial<AgenteForm>) =>
    setAgentes((arr) => arr.map((a, i) => (i === idx ? { ...a, ...patch } : a)));

  const validate = (): string | null => {
    if (!form.nome.trim()) return "Nome é obrigatório";
    if (!form.slug.trim()) return "Slug é obrigatório";
    if (!form.categoria.trim()) return "Categoria é obrigatória";
    if (!form.descricao_curta.trim()) return "Descrição curta é obrigatória";
    if (agentes.every((a) => !a.prompt.trim())) return "Defina o prompt de pelo menos um agente";
    return null;
  };

  const save = async () => {
    const err = validate();
    if (err) {
      setTocado(true);
      // Campos da aba Identidade: leva o admin até lá para corrigir.
      if (!form.nome.trim() || !form.categoria.trim() || !form.descricao_curta.trim()) setTab("identidade");
      else if (agentes.every((a) => !a.prompt.trim())) setTab("agentes");
      return toast.error("Falta preencher algo antes de salvar", { description: err });
    }

    // TRAVA: agente que passa o lead adiante precisa de Frase para Transferência de saída.
    // Vale p/ produto PUBLICADO ou que JÁ USA frases (protege contra apagar sem querer), sem
    // travar rascunhos que ainda não usam. Prompt vazio = agente não configurado (ignora).
    const lista = await carregarFrasesTroca(form.id).catch(() => getFrasesTroca(form.id ?? null));
    const agentesDoProduto = agentes.filter((a) => a.papel !== "periododegraca" || form.oferece_periodo_graca);
    const usaFrases = agentesDoProduto.some((a) => temTokenTransferencia(a.prompt) || lista.some((f) => a.prompt.includes(f.frase)));
    if (form.status === "publicado" || usaFrases) {
      const faltando = agentesSemFraseDeSaida(
        agentesDoProduto.map((a) => ({ etapa: a.papel as string, prompt: a.prompt, nome: a.nome_exibicao || ROLE_META[a.papel]?.label || a.papel })),
        lista, { ignorarVazios: true },
      );
      if (faltando.length) {
        return toast.error("Não é possível salvar", {
          description: `Falta a Frase para Transferência no prompt de: ${faltando.map((f) => f.nome).join(", ")}. `
            + "Insira com @ → Transferência ou selecione o trecho e use “Marcar frase”.",
        });
      }
    }
    setSaving(true);

    const finalStatus: ProdStatus = form.status;
    const payload: any = {
      slug: slugify(form.slug),
      nome: form.nome.trim(),
      categoria: form.categoria,
      descricao_curta: form.descricao_curta.trim(),
      descricao_longa: form.descricao_longa.trim() || null,
      etiquetas: form.etiquetas.split(",").map((t) => t.trim()).filter(Boolean),
      icone: form.icone || null,
      capa_gradiente: form.capa_gradiente || null,
      modelo_recomendado: form.modelo_recomendado,
      versao: form.versao,
      status: finalStatus,
      config_modelo: preserva.config_modelo,
      // Follow-up padrão: cadência + prompts por etapa, tudo no jsonb do produto.
      padrao_followup: {
        ...(preserva.padrao_followup ?? {}),
        cadence: fupCadence,
        restart_on_reply: fupRestart,
        agentes: Object.fromEntries(STAGE_ORDER.map((st, i) => {
          const a = fupAgentes[st];
          return [st, {
            nome_agente: a.name.trim() || `Follow-up - ${STAGE_LABELS[st]}`,
            prompt: a.prompt || "",
            habilitado_padrao: a.enabled,
            ordem: i,
          }];
        })),
      },
      mensagem_boas_vindas: form.mensagem_boas_vindas || null,
      // Padrões de conteúdo (semeiam o rascunho do cliente)
      regras_markdown: form.regras_markdown.trim() || null,
      dados_escritorio: form.dados_escritorio.trim() || null,
      faq: faqItems.filter((f) => f.pergunta.trim() || f.resposta.trim()),
      objecoes: objItems.filter((o) => o.titulo.trim() || o.resposta.trim()),
      oferece_periodo_graca: form.oferece_periodo_graca,
      modo_midia: form.modo_midia,
    };

    let prodId = form.id;
    if (prodId) {
      try {
        await enviar(`/admin/biblioteca/produtos/${prodId}`, payload, "PATCH");
      } catch (e: any) { toast.error(e?.message); setSaving(false); return; }
    } else {
      // Slug é único — checa antes de inserir para erro claro (em vez de violação genérica)
      const dup = await api<any>(`/biblioteca/produtos/${encodeURIComponent(payload.slug)}`).catch(() => null);
      if (dup) { toast.error("Slug já existe", { description: `Já há um produto com o slug "${payload.slug}". Mude o nome.` }); setSaving(false); return; }
      let data: any = null;
      try {
        data = await enviar("/admin/biblioteca/produtos", payload);
      } catch (e: any) {
        const msg = e?.status === 409 ? "Slug já existe — escolha outro nome." : (e?.message ?? "Erro ao criar");
        toast.error(msg); setSaving(false); return;
      }
      if (!data?.id) { toast.error("Erro ao criar"); setSaving(false); return; }
      prodId = data.id;
    }

    // Agentes do funil (mesmo shape de blocos que o cliente salva). O PUT faz upsert por papel e
    // apaga o papel ausente: com o Período de Graça desligado, a linha dele sai do catálogo.
    const linhasAgentes = agentes
      .filter((a) => a.papel !== "periododegraca" || form.oferece_periodo_graca)
      .map((a, i) => ({
        papel: a.papel,
        nome_exibicao: a.nome_exibicao.trim() || ROLE_META[a.papel]?.label || a.papel,
        descricao: a.descricao.trim() || null,
        icone: ROLE_META[a.papel]?.icon ?? null,
        ordem: i,
        blocos_prompt: buildBlocks(a.prompt, a.handoff),
        texto_prompt: a.prompt,
        mensagem_boas_vindas: a.mensagem_boas_vindas || null,
        // config_modelo guarda FAQ/objeções/regras do agente (remove a chave quando vazio
        // p/ não "ressuscitar" conteúdo apagado).
        config_modelo: (() => {
          const c: any = { ...(a.config_modelo ?? {}) };
          if (a.faq.length) c.faq_items = a.faq.map((f) => ({ q: f.pergunta, a: f.resposta })); else delete c.faq_items;
          if (a.objecoes.length) c.objecoes = a.objecoes.map((o) => ({ gatilho: o.titulo, resposta: o.resposta })); else delete c.objecoes;
          if (a.regras_gerais.trim()) c.rules_markdown = a.regras_gerais.trim(); else delete c.rules_markdown;
          return c;
        })(),
        regras_handoff: a.regras_handoff ?? [],
      }));
    try {
      const salvos = await enviar<any[]>(`/admin/biblioteca/produtos/${prodId}/agentes`, linhasAgentes, "PUT");
      // guarda os ids recém-criados
      const idPorPapel = new Map<string, string>(((salvos ?? []) as any[]).map((r) => [r.papel, r.id]));
      setAgentes((arr) => arr.map((x) => (idPorPapel.has(x.papel) ? { ...x, id: idPorPapel.get(x.papel)! } : x)));
    } catch (e: any) { toast.error(`Agentes: ${e?.message}`); setSaving(false); return; }

    setPreserva((p) => ({ ...p, padrao_followup: payload.padrao_followup }));

    // Invalida o catálogo do cliente (/biblioteca) p/ refletir na hora (staleTime 30s).
    qc.invalidateQueries({ queryKey: ["templates"] });
    qc.invalidateQueries({ queryKey: ["template"] });
    rascunhoLocal.limpar(); // salvo no servidor → nada a recuperar
    toast.success(`Salvo — ${STATUS_META[finalStatus].label}`);
    setSaving(false);
    if (isNew) navigate(`/admin/produtos/${prodId}`);
    else setForm((f) => ({ ...f, status: finalStatus }));
  };

  if (loading) {
    return (
      <div className="grid place-items-center py-20">
        <Loader2 className="size-8 animate-spin text-primary" />
      </div>
    );
  }

  const validationErr = validate();
  // Produto existente com pendência mostra na hora; produto novo só depois de tocar/tentar salvar.
  const mostrarPendencia = !!validationErr && (tocado || !isNew);
  const ag = agentes[activeRoleIdx];
  const AgIcon = ROLE_META[ag.papel].Icon;
  const handoffOptions = handoffLabelsFor(ag.papel);
  // Cor do produto: própria (capa_gradiente hex) se houver, senão a da categoria
  const [catC1, catC2] = resolveGradient(form.capa_gradiente, form.categoria);
  const fupStages = STAGE_ORDER.filter((s) => fupAgentes[s].enabled);
  const fupActiveOk = fupStages.includes(fupActive) ? fupActive : (fupStages[0] ?? "sdr");

  return (
    <FrasesProdutoProvider idProduto={form.id ?? null}>
    <div className="space-y-6">
      {/* HEADER */}
      <div className="sticky top-0 z-20 -mx-4 px-4 py-3 sm:-mx-6 sm:px-6 bg-background/85 backdrop-blur-xl border-b">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3 min-w-0">
            <Button variant="ghost" size="icon" onClick={() => navigate("/admin/produtos")} className="shrink-0">
              <ArrowLeft className="size-4" />
            </Button>
            <div className="size-12 rounded-2xl grid place-items-center text-2xl shrink-0 shadow-sm ring-1 ring-black/5" style={{ backgroundImage: `linear-gradient(135deg, ${catC1}, ${catC2})` }}>
              <span className="drop-shadow-sm">{form.icone || "⚖️"}</span>
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                <span>Admin</span><span>·</span><span>Produtos</span>
                {!isNew && <><span>·</span><span className="font-mono truncate">{form.slug || "—"}</span></>}
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                <h1 className="text-xl font-bold tracking-tight truncate">
                  {isNew ? "Novo produto" : form.nome || "Produto sem nome"}
                </h1>
                {!isNew && (
                  <Badge variant={STATUS_META[form.status].badge} className="font-medium">{STATUS_META[form.status].label}</Badge>
                )}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {mostrarPendencia ? (
              <span role="status" className="text-xs font-medium text-amber-800 inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-amber-50 border border-amber-300/80 animate-fade-in dark:bg-amber-500/10 dark:text-amber-200 dark:border-amber-500/30">
                <AlertCircle className="size-3.5 text-amber-600 dark:text-amber-400" /> {validationErr}
              </span>
            ) : !validationErr ? (
              <span className="text-xs font-medium text-foreground/80 inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border" style={{ backgroundColor: `${catC1}0f`, borderColor: `${catC1}33` }}>
                <CheckCircle2 className="size-3.5" style={{ color: catC1 }} /> Pronto para salvar
              </span>
            ) : null}
            <Button
              disabled={saving}
              onClick={() => save()}
              className="text-white shadow-sm"
              style={{ backgroundImage: "linear-gradient(135deg, #3BE062, #00BC33)" }}
            >
              {saving ? <Loader2 className="size-4 mr-1.5 animate-spin" /> : <Save className="size-4 mr-1.5" />}
              Salvar
            </Button>
          </div>
        </div>
      </div>

      {rascunhoLocal.pendente && (
        <RecuperarRascunhoBanner
          salvoEm={rascunhoLocal.pendente.salvoEm}
          onRecuperar={aplicarRascunhoLocal}
          onDescartar={rascunhoLocal.descartar}
        />
      )}

      <Tabs value={tab} onValueChange={setTab} className="space-y-5">
        <div className="-mx-4 px-4 sm:mx-0 sm:px-0 overflow-x-auto scrollbar-thin [scrollbar-width:thin]">
        <TabsList className="h-auto w-full justify-start gap-6 rounded-none bg-transparent p-0 border-b border-[#eef1f5]">
          {[
            { v: "identidade", l: "Identidade", Icon: User },
            { v: "agentes", l: `Agentes`, count: agentes.length, Icon: MessageSquare },
            { v: "conteudo", l: "Conteúdo", Icon: ListChecks },
            { v: "conhecimento", l: "Conhecimento", Icon: BookOpen },
            { v: "followup", l: "Follow-up", count: fupCadence.length, Icon: Repeat },
          ].map((t) => {
            const active = tab === t.v;
            return (
              <TabsTrigger
                key={t.v}
                value={t.v}
                className="relative shrink-0 rounded-none bg-transparent px-0.5 pb-3 pt-1 text-[14px] font-medium text-[#667085] shadow-none transition-colors hover:text-[#101828] data-[state=active]:bg-transparent data-[state=active]:text-[#101828] data-[state=active]:font-semibold data-[state=active]:shadow-none inline-flex items-center gap-2 after:absolute after:left-0 after:right-0 after:-bottom-px after:h-[2px] after:rounded-full after:bg-transparent data-[state=active]:after:bg-[#00BC33]"
              >
                <t.Icon className="size-4" style={active ? { color: "#00BC33" } : undefined} />
                {t.l}
                {t.count != null && (
                  <span className="text-[11px] font-semibold rounded-full px-1.5 leading-5" style={active ? { backgroundColor: "#e8f9ee", color: "#009926" } : { backgroundColor: "#f2f4f7", color: "#667085" }}>{t.count}</span>
                )}
              </TabsTrigger>
            );
          })}
        </TabsList>
        </div>

        {/* IDENTIDADE */}
        <TabsContent value="identidade" className="mt-0 space-y-4">
          <Card className="p-6 space-y-5">
            <div>
              <h3 className="text-base font-semibold">Identidade do produto</h3>
              <p className="text-xs text-muted-foreground mt-0.5">Nome, slug e como ele aparece no catálogo.</p>
            </div>
            <div className="grid md:grid-cols-2 gap-4">
              <div className="space-y-1.5 md:col-span-2">
                <Label>Nome do produto *</Label>
                <Input
                  value={form.nome}
                  onChange={(e) => {
                    const nome = e.target.value;
                    setForm((f) => ({ ...f, nome, slug: f.id ? f.slug : slugify(nome) }));
                  }}
                  onBlur={() => setTocado(true)}
                  aria-invalid={tocado && !form.nome.trim()}
                  placeholder="Ex.: Rescisão Indireta"
                />
              </div>
              <div className="space-y-1.5">
                <Label>Slug <span className="text-xs text-muted-foreground font-normal">(gerado automaticamente)</span></Label>
                <Input
                  value={form.slug}
                  readOnly
                  tabIndex={-1}
                  placeholder="gerado a partir do nome"
                  className="font-mono text-sm bg-muted/50 text-muted-foreground cursor-not-allowed"
                />
              </div>
              <div className="space-y-1.5">
                <Label>Ícone</Label>
                <Input
                  value={form.icone}
                  onChange={(e) => setForm({ ...form, icone: e.target.value })}
                  maxLength={4}
                  placeholder="⚖️"
                  className="text-center text-lg"
                />
              </div>
            </div>

            {/* Cor do produto */}
            <div className="space-y-2">
              <Label className="flex items-center gap-1.5"><Palette className="size-3.5" /> Cor do produto</Label>
              <div className="flex items-center gap-3 flex-wrap">
                {/* preview */}
                <div className="size-11 rounded-xl grid place-items-center text-xl shrink-0 shadow-sm ring-1 ring-black/5" style={{ backgroundImage: `linear-gradient(135deg, ${catC1}, ${catC2})` }}>
                  <span className="drop-shadow-sm">{form.icone || "⚖️"}</span>
                </div>
                {/* auto */}
                {(() => {
                  const isAuto = !GRADIENT_PRESETS.some((p) => p.value === form.capa_gradiente);
                  return (
                    <button
                      type="button"
                      onClick={() => setForm({ ...form, capa_gradiente: "" })}
                      className={`h-9 px-3 rounded-lg border text-xs font-medium inline-flex items-center gap-1.5 transition-colors ${isAuto ? "border-primary bg-primary/5 text-foreground" : "hover:bg-accent text-muted-foreground"}`}
                      title="Usa a cor da categoria"
                    >
                      {isAuto && <Check className="size-3.5 text-primary" />} Auto (categoria)
                    </button>
                  );
                })()}
                {/* swatches */}
                <div className="flex items-center gap-1.5 flex-wrap">
                  {GRADIENT_PRESETS.map((p) => {
                    const sel = form.capa_gradiente === p.value;
                    return (
                      <button
                        key={p.value}
                        type="button"
                        title={p.name}
                        onClick={() => setForm({ ...form, capa_gradiente: p.value })}
                        className={`size-8 rounded-lg shadow-sm transition-transform hover:scale-110 grid place-items-center ${sel ? "ring-2 ring-offset-2 ring-foreground/60" : "ring-1 ring-black/5"}`}
                        style={{ backgroundImage: `linear-gradient(135deg, ${p.c1}, ${p.c2})` }}
                      >
                        {sel && <Check className="size-4 text-white drop-shadow" strokeWidth={3} />}
                      </button>
                    );
                  })}
                </div>
              </div>
              <p className="text-[11px] text-muted-foreground">Define a cor dos agentes e do card. <strong>Auto</strong> usa a cor da categoria.</p>
            </div>

            <div className="space-y-1.5">
              <Label>Descrição curta * <span className="text-xs text-muted-foreground font-normal">(aparece no card)</span></Label>
              <Input
                value={form.descricao_curta}
                onChange={(e) => setForm({ ...form, descricao_curta: e.target.value })}
                onBlur={() => setTocado(true)}
                aria-invalid={tocado && !form.descricao_curta.trim()}
                placeholder="Assistente para casos de rescisão indireta."
                maxLength={160}
              />
              <p className="text-[10px] text-muted-foreground text-right">{form.descricao_curta.length}/160</p>
            </div>

            <div className="space-y-1.5">
              <Label>Descrição longa</Label>
              <Textarea
                rows={4}
                value={form.descricao_longa}
                onChange={(e) => setForm({ ...form, descricao_longa: e.target.value })}
                placeholder="Detalhe quando usar, o que o produto faz, etc."
              />
            </div>
          </Card>

          <Card className="p-6 space-y-5">
            <div>
              <h3 className="text-base font-semibold">Categorização & acesso</h3>
              <p className="text-xs text-muted-foreground mt-0.5">Onde aparece e quem pode ativar.</p>
            </div>
            <div className="grid md:grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label>Categoria *</Label>
                <Select value={form.categoria} onValueChange={(v) => setForm({ ...form, categoria: v })}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {categories.map((c) => <SelectItem key={c.name} value={c.name}>{c.name}</SelectItem>)}
                    {!categories.some((c) => c.name === form.categoria) && form.categoria && (
                      <SelectItem value={form.categoria}>{form.categoria}</SelectItem>
                    )}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>Versão</Label>
                <Input value={form.versao} onChange={(e) => setForm({ ...form, versao: e.target.value })} className="font-mono text-sm" />
              </div>
            </div>

            {/* Produto com MÍDIA: libera a Edição rápida de mídias / marcadores [[midia:]] no cliente. */}
            <div className="flex items-center justify-between gap-3 rounded-xl border border-sky-200 bg-sky-50/60 p-3">
              <div className="flex items-center gap-2 min-w-0">
                <div className="size-8 rounded-lg grid place-items-center shrink-0 bg-sky-100 text-sky-600"><Music className="size-4" /></div>
                <div className="min-w-0">
                  <div className="text-[13px] font-bold">Produto com mídia (áudio/vídeo)</div>
                  <div className="text-[11px] text-muted-foreground">
                    {form.modo_midia === "audio"
                      ? "Libera a Edição rápida de mídias e os marcadores [[midia:]] no editor do cliente (que precisa de plano com mídia)."
                      : "Só texto — sem seletor de mídias."}
                  </div>
                </div>
              </div>
              <Switch checked={form.modo_midia === "audio"} onCheckedChange={(v) => setForm({ ...form, modo_midia: v ? "audio" : "texto" })} />
            </div>

            <div className="space-y-1.5">
              <Label>Tags <span className="text-xs text-muted-foreground font-normal">(separadas por vírgula)</span></Label>
              <Input
                value={form.etiquetas}
                onChange={(e) => setForm({ ...form, etiquetas: e.target.value })}
                placeholder="trabalhista, rescisao, clt"
              />
            </div>

            <div className="space-y-2 p-3 rounded-lg border bg-muted/30">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-medium">Modo de publicação</div>
                  <div className="text-xs text-muted-foreground">{STATUS_META[form.status].hint}</div>
                </div>
                <Select value={form.status} onValueChange={(v) => setForm({ ...form, status: v as ProdStatus })}>
                  <SelectTrigger className="w-[170px]"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="rascunho">Rascunho</SelectItem>
                    <SelectItem value="em_breve">Em breve</SelectItem>
                    <SelectItem value="publicado">Publicado</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </Card>
        </TabsContent>

        {/* AGENTES — os 5 do funil, com o mesmo editor rico do cliente */}
        <TabsContent value="agentes" className="mt-0">
          <div className="grid lg:grid-cols-[220px_minmax(0,1fr)] gap-5 items-start">
            {/* Nav dos papéis */}
            <Card className="p-2 lg:sticky lg:top-4">
              {/* Toggle EXCLUSIVO do admin: liga/desliga a etapa Período de Graça do produto.
                  Ligado → entra um 6º agente (após o SDR) que o cliente passa a ver no funil. */}
              <div className="mb-1.5 rounded-lg border border-amber-200 bg-amber-50/60 p-2.5">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <div className="size-7 rounded-lg grid place-items-center shrink-0 bg-amber-100 text-amber-600"><Hourglass className="size-4" /></div>
                    <div className="min-w-0">
                      <div className="text-[12px] font-bold truncate">Período de Graça</div>
                      <div className="text-[10px] text-muted-foreground">{form.oferece_periodo_graca ? "Etapa ativa (após o SDR)" : "Etapa desativada"}</div>
                    </div>
                  </div>
                  <Switch checked={form.oferece_periodo_graca} onCheckedChange={togglePeriodoGraca} />
                </div>
              </div>

              {agentes.map((a, i) => {
                const meta = ROLE_META[a.papel];
                const active = activeRoleIdx === i;
                return (
                  <button
                    key={a.papel}
                    onClick={() => setActiveRoleIdx(i)}
                    style={active ? { backgroundColor: `${catC1}14` } : undefined}
                    className={`w-full flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors ${active ? "" : "hover:bg-accent"}`}
                  >
                    <div
                      className="size-8 rounded-lg grid place-items-center shrink-0 transition-colors"
                      style={active
                        ? { backgroundImage: `linear-gradient(135deg, ${catC1}, ${catC2})`, color: "#fff" }
                        : { backgroundColor: "hsl(var(--muted))", color: "hsl(var(--muted-foreground))" }}
                    >
                      <meta.Icon className="size-4" />
                    </div>
                    <div className="min-w-0">
                      <div className="text-sm font-medium truncate" style={active ? { color: catC1 } : undefined}>{meta.label}</div>
                      <div className="text-[10px] text-muted-foreground truncate">{a.prompt.trim() ? "Configurado" : "Vazio"}</div>
                    </div>
                  </button>
                );
              })}
              <p className="text-[10px] text-muted-foreground px-2.5 pt-2 pb-1 leading-snug">
                Os agentes do funil que o cliente recebe ao ativar. O prompt aceita <code className="text-[#7c3aed]">{"{{campo}}"}</code> e <code className="text-[#2563eb]">@agente</code>.
              </p>
            </Card>

            {/* Editor do agente ativo */}
            <div className="space-y-4 min-w-0">
              <Card className="p-5 space-y-4">
                <div className="flex items-center gap-3">
                  <div
                    className="size-11 rounded-2xl grid place-items-center text-white shadow-sm shrink-0"
                    style={{ backgroundImage: `linear-gradient(135deg, ${catC1}, ${catC2})` }}
                  >
                    <AgIcon className="size-5" />
                  </div>
                  <div className="min-w-0">
                    <div className="text-[10px] uppercase tracking-wider font-bold" style={{ color: catC1 }}>{ROLE_META[ag.papel].label}</div>
                    <div className="text-base font-semibold truncate">{ag.nome_exibicao}</div>
                  </div>
                </div>

                <div className="space-y-1.5">
                  <Label>Nome de exibição</Label>
                  <Input value={ag.nome_exibicao} onChange={(e) => updAgente(activeRoleIdx, { nome_exibicao: e.target.value })} placeholder={ROLE_META[ag.papel].label} />
                </div>

                <div className="space-y-1.5">
                  <Label>Descrição <span className="text-xs text-muted-foreground font-normal">(uso interno)</span></Label>
                  <Input value={ag.descricao} onChange={(e) => updAgente(activeRoleIdx, { descricao: e.target.value })} placeholder="O que este agente faz no funil." />
                </div>
              </Card>

              <Card className="p-5 space-y-2.5">
                <div className="flex items-start justify-between gap-3 flex-wrap">
                  <div>
                    <Label className="text-sm font-semibold">Prompt do agente</Label>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      Use a barra para formatar. <code className="text-[#7c3aed]">{"{{campo}}"}</code> vira preenchível pelo cliente; <code className="text-[#2563eb]">@</code> passa o lead adiante ou aciona uma ferramenta (buscar CEP, gerar documento).
                    </p>
                  </div>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="shrink-0"
                    disabled={!ag.prompt.trim()}
                    onClick={() => baixarPromptMd(ag.papel, ag.nome_exibicao, expandirFrasesParaBot(ag.prompt))}
                    title="Baixar este prompt em .md (com as frases para transferência já no texto)"
                  >
                    <Download className="size-3.5 mr-1.5" />
                    Baixar .md
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="shrink-0"
                    onClick={() => setFrasesOpen(true)}
                    title="Cadastrar ou editar as frases para transferência de departamento"
                    style={{ color: COR_TRANSFERENCIA, borderColor: "#fed7aa" }}
                  >
                    <ArrowRightLeft className="size-3.5 mr-1.5" />
                    Frases para Transferência
                  </Button>
                </div>
                <RichPromptEditor
                  key={`${ag.papel}-${editorKey}`}
                  ref={richRef}
                  value={ag.prompt}
                  onChange={(v) => updAgente(activeRoleIdx, { prompt: v })}
                  handoffOptions={handoffOptions}
                  toolOptions={TOOL_LABELS}
                  onAbrirMidia={() => setLibraryOpen(true)}
                  midiaLiberada={true}
                  media={midiaItems}
                  transferencia
                  onGerenciarFrases={() => setFrasesOpen(true)}
                />

                {/* Frases para Transferência deste agente: entrada (mensagem_troca) + saídas (@Transferência). */}
                <FraseEntradaCard role={ag.papel} prompt={ag.prompt} onGerenciar={() => setFrasesOpen(true)} />

                {/* Só no agente de Assinatura: → prompts.mensagem_troca. Com frase para transferência cadastrada,
                    o campo aparece PREENCHIDO com ela (travado; edita em "Frases para Transferência"). Sem frase,
                    é o padrão do catálogo, editável. */}
                {ag.papel === "assinatura" && (() => {
                  const fixa = fraseDaEtapa("assinatura", frasesTroca ?? []);
                  return (
                    <div className="rounded-xl border border-success/25 bg-success/5 p-3.5">
                      <div className="flex items-center gap-2">
                        <Label className="text-[11px] font-bold uppercase tracking-wider text-success">
                          Frase para Transferência
                        </Label>
                        {fixa && (
                          <Button type="button" size="sm" variant="ghost" className="ml-auto h-7 text-xs" onClick={() => setFrasesOpen(true)}>
                            Editar frase
                          </Button>
                        )}
                      </div>
                      <p className="text-[11px] text-muted-foreground mt-1 mb-2">
                        {fixa
                          ? "Preenchida pela frase para transferência da Assinatura — é ela que vai para o bot. Para mudar, edite a frase."
                          : "Frase que passa o lead para a Assinatura (vai para a mensagem_troca). Padrão do catálogo — o cliente pode ajustar na conta dele."}
                      </p>
                      <Textarea
                        rows={3}
                        value={fixa ? fixa.frase : (ag.handoff ?? "")}
                        onChange={(e) => { if (!fixa) updAgente(activeRoleIdx, { handoff: e.target.value }); }}
                        readOnly={!!fixa}
                        placeholder="Ex.: Acabamos de confirmar a assinatura do seu contrato 🎉 Nosso Setor Operacional vai continuar o seu atendimento…"
                        className={`text-sm ${fixa ? "bg-muted/40 cursor-not-allowed" : "bg-white"}`}
                      />
                    </div>
                  );
                })()}
              </Card>

            </div>
          </div>
        </TabsContent>

        {/* CONTEÚDO — padrões de regras, FAQ e objeções */}
        <TabsContent value="conteudo" className="mt-0 space-y-4">
          {/* Aviso de contexto */}
          <div className="flex items-start gap-3 rounded-xl border p-3.5" style={{ borderColor: `${catC1}33`, backgroundColor: `${catC1}0d` }}>
            <div className="size-8 rounded-lg grid place-items-center shrink-0 text-white" style={{ backgroundImage: `linear-gradient(135deg, ${catC1}, ${catC2})` }}>
              <Sparkles className="size-4" />
            </div>
            <p className="text-xs text-muted-foreground leading-relaxed">
              Tudo aqui é <strong className="text-foreground">padrão do catálogo</strong>: ao ativar o produto, o cliente já recebe estas regras, perguntas e objeções pré-preenchidas — e pode ajustar depois.
            </p>
          </div>

          {/* Regras gerais */}
          <Card className="p-6 space-y-3.5">
            <div className="flex items-center gap-3">
              <div className="size-9 rounded-xl grid place-items-center shrink-0 text-white" style={{ backgroundImage: `linear-gradient(135deg, ${catC1}, ${catC2})` }}><ListChecks className="size-[18px]" /></div>
              <div>
                <h3 className="text-base font-semibold">Regras gerais</h3>
                <p className="text-xs text-muted-foreground mt-0.5">Markdown aplicado a todos os agentes.</p>
              </div>
            </div>
            <Textarea
              rows={6}
              value={form.regras_markdown}
              onChange={(e) => setForm({ ...form, regras_markdown: e.target.value })}
              placeholder={"- Sempre confirme dados sensíveis.\n- Nunca prometa resultado.\n- Use {{nome_do_escritorio}} ao se apresentar."}
              className="font-mono text-sm leading-relaxed"
            />
            <p className="text-[11px] text-muted-foreground flex items-center gap-1.5">
              <Info className="size-3 shrink-0" /> Use <code className="text-[#7c3aed]">{"{{campo}}"}</code> para valores que o cliente preenche na ativação.
            </p>
          </Card>

          {/* Dados do Escritório */}
          <Card className="p-6 space-y-3.5">
            <div className="flex items-center gap-3">
              <div className="size-9 rounded-xl grid place-items-center shrink-0 text-white" style={{ backgroundImage: `linear-gradient(135deg, ${catC1}, ${catC2})` }}><Building2 className="size-[18px]" /></div>
              <div>
                <h3 className="text-base font-semibold">Dados do Escritório</h3>
                <p className="text-xs text-muted-foreground mt-0.5">Informações da firma aplicadas a todos os agentes.</p>
              </div>
            </div>
            <RespostaComMidia
              value={form.dados_escritorio}
              onChange={(v) => setForm({ ...form, dados_escritorio: v })}
              showMidia={form.modo_midia === "audio"}
            />
            <p className="text-[11px] text-muted-foreground flex items-center gap-1.5">
              <Info className="size-3 shrink-0" /> Use <code className="text-[#7c3aed]">{"{{campo}}"}</code> para valores que o cliente preenche na ativação.
            </p>
          </Card>

          {/* FAQ */}
          <Card className="p-6 space-y-4">
            <div className="flex items-center gap-3">
              <div className="size-9 rounded-xl grid place-items-center shrink-0 text-white" style={{ backgroundImage: `linear-gradient(135deg, ${catC1}, ${catC2})` }}><MessageSquare className="size-[18px]" /></div>
              <div className="flex-1 min-w-0">
                <h3 className="text-base font-semibold">FAQ padrão</h3>
                <p className="text-xs text-muted-foreground mt-0.5">Dúvidas comuns dos leads e como respondê-las.</p>
              </div>
              {faqItems.length > 0 && (
                <span className="text-xs font-semibold rounded-full px-2 py-0.5 shrink-0" style={{ color: catC1, backgroundColor: `${catC1}14` }}>{faqItems.length}</span>
              )}
            </div>
            {faqItems.length === 0 ? (
              <div className="rounded-xl border border-dashed p-8 text-center">
                <MessageSquare className="size-5 mx-auto text-muted-foreground/50 mb-2" />
                <p className="text-sm text-muted-foreground">Nenhuma pergunta ainda.</p>
                <p className="text-xs text-muted-foreground/70 mt-0.5">Ex.: "Quanto tempo demora o processo?"</p>
              </div>
            ) : (
              <div className="space-y-3">
                {faqItems.map((item, idx) => (
                  <div key={idx} className="group rounded-xl border bg-card p-3.5 space-y-2.5 transition-colors hover:border-[var(--cat)]" style={{ ["--cat" as any]: catC1 }}>
                    <div className="flex items-center justify-between">
                      <span className="inline-flex items-center justify-center size-6 rounded-md text-[11px] font-bold" style={{ color: catC1, backgroundColor: `${catC1}14` }}>{idx + 1}</span>
                      <button onClick={() => setFaqItems((p) => p.filter((_, i) => i !== idx))} className="text-muted-foreground/60 hover:text-destructive transition-colors" title="Remover"><X className="size-4" /></button>
                    </div>
                    <Input value={item.pergunta} onChange={(e) => setFaqItems((p) => p.map((it, i) => i === idx ? { ...it, pergunta: e.target.value } : it))} placeholder="Pergunta (ex: Quanto tempo demora o processo?)" className="font-semibold" />
                    <RespostaComMidia value={item.resposta} onChange={(v) => setFaqItems((p) => p.map((it, i) => i === idx ? { ...it, resposta: v } : it))} placeholder="Como o agente deve responder…" className="min-h-[84px]" showMidia={form.modo_midia === "audio"} />
                  </div>
                ))}
              </div>
            )}
            <Button variant="outline" className="w-full border-dashed" onClick={() => setFaqItems((p) => [...p, { pergunta: "", resposta: "" }])}>
              <Plus className="size-4 mr-1.5" />Adicionar pergunta
            </Button>
          </Card>

          {/* Objeções */}
          <Card className="p-6 space-y-4">
            <div className="flex items-center gap-3">
              <div className="size-9 rounded-xl grid place-items-center shrink-0 text-white" style={{ backgroundImage: `linear-gradient(135deg, ${catC1}, ${catC2})` }}><Shield className="size-[18px]" /></div>
              <div className="flex-1 min-w-0">
                <h3 className="text-base font-semibold">Objeções padrão</h3>
                <p className="text-xs text-muted-foreground mt-0.5">Resistências comuns e como contorná-las com segurança.</p>
              </div>
              {objItems.length > 0 && (
                <span className="text-xs font-semibold rounded-full px-2 py-0.5 shrink-0" style={{ color: catC1, backgroundColor: `${catC1}14` }}>{objItems.length}</span>
              )}
            </div>
            {objItems.length === 0 ? (
              <div className="rounded-xl border border-dashed p-8 text-center">
                <Shield className="size-5 mx-auto text-muted-foreground/50 mb-2" />
                <p className="text-sm text-muted-foreground">Nenhuma objeção cadastrada.</p>
                <p className="text-xs text-muted-foreground/70 mt-0.5">Ex.: "Está caro", "Vou pensar", "Acho que é golpe".</p>
              </div>
            ) : (
              <div className="space-y-3">
                {objItems.map((item, idx) => (
                  <div key={idx} className="group rounded-xl border bg-card p-3.5 space-y-2.5 transition-colors hover:border-[var(--cat)]" style={{ ["--cat" as any]: catC1 }}>
                    <div className="flex items-center justify-between">
                      <span className="inline-flex items-center justify-center size-6 rounded-md text-[11px] font-bold" style={{ color: catC1, backgroundColor: `${catC1}14` }}>{idx + 1}</span>
                      <button onClick={() => setObjItems((p) => p.filter((_, i) => i !== idx))} className="text-muted-foreground/60 hover:text-destructive transition-colors" title="Remover"><X className="size-4" /></button>
                    </div>
                    <Input value={item.titulo} onChange={(e) => setObjItems((p) => p.map((it, i) => i === idx ? { ...it, titulo: e.target.value } : it))} placeholder="Título da objeção (ex: Está caro)" className="font-semibold" />
                    <RespostaComMidia value={item.resposta} onChange={(v) => setObjItems((p) => p.map((it, i) => i === idx ? { ...it, resposta: v } : it))} placeholder="Como o agente deve contornar…" className="min-h-[84px]" showMidia={form.modo_midia === "audio"} />
                  </div>
                ))}
              </div>
            )}
            <Button variant="outline" className="w-full border-dashed" onClick={() => setObjItems((p) => [...p, { titulo: "", resposta: "" }])}>
              <Plus className="size-4 mr-1.5" />Adicionar objeção
            </Button>
          </Card>
        </TabsContent>

        {/* CONHECIMENTO — docs padrão do produto (copiados travados na ativação) */}
        <TabsContent value="conhecimento" className="mt-0 space-y-4">
          <BibliotecaConhecimentoManager idProduto={form.id} />
        </TabsContent>

        {/* FOLLOW-UP — padrão do catálogo (cadência + prompts por etapa) */}
        <TabsContent value="followup" className="mt-0 space-y-4">
          <div className="flex items-start gap-3 rounded-xl border p-3.5" style={{ borderColor: `${catC1}33`, backgroundColor: `${catC1}0d` }}>
            <div className="size-8 rounded-lg grid place-items-center shrink-0 text-white" style={{ backgroundImage: `linear-gradient(135deg, ${catC1}, ${catC2})` }}>
              <Repeat className="size-4" />
            </div>
            <p className="text-xs text-muted-foreground leading-relaxed">
              Padrão de follow-up do produto. Ao ativar, o cliente <strong className="text-foreground">herda</strong> esta cadência e os prompts por etapa (e pode ajustar). Sem prompt, a etapa não dispara.
            </p>
          </div>

          {/* Cadência */}
          <Card className="p-6 space-y-4">
            <div className="flex items-center gap-3">
              <div className="size-9 rounded-xl grid place-items-center shrink-0 text-white" style={{ backgroundImage: `linear-gradient(135deg, ${catC1}, ${catC2})` }}><Repeat className="size-[18px]" /></div>
              <div>
                <h3 className="text-base font-semibold">Cadência padrão</h3>
                <p className="text-xs text-muted-foreground mt-0.5">Pontos de contato em sequência (intervalo a partir da última mensagem do lead).</p>
              </div>
            </div>
            <CadenceBuilder value={fupCadence} onChange={setFupCadence} />
            <div className="flex items-start justify-between gap-4 rounded-lg border p-3 bg-muted/30">
              <div>
                <div className="text-sm font-medium">Reiniciar ao responder</div>
                <div className="text-xs text-muted-foreground">Qualquer resposta do lead reinicia o ciclo do zero.</div>
              </div>
              <Switch checked={fupRestart} onCheckedChange={setFupRestart} className="mt-0.5" />
            </div>
          </Card>

          {/* Etapas */}
          <Card className="p-6 space-y-4">
            <div>
              <h3 className="text-base font-semibold">Etapas com follow-up</h3>
              <p className="text-xs text-muted-foreground mt-0.5">Quais etapas do CRM disparam follow-up por padrão.</p>
            </div>
            <CrmStagesPicker
              value={fupStages}
              onChange={(next) => setFupAgentes((prev) => {
                const upd = { ...prev };
                STAGE_ORDER.forEach((s) => { upd[s] = { ...upd[s], enabled: next.includes(s) }; });
                return upd;
              })}
            />
          </Card>

          {/* Prompts por etapa */}
          <Card className="p-6 space-y-4">
            <div>
              <h3 className="text-base font-semibold">Prompts de follow-up</h3>
              <p className="text-xs text-muted-foreground mt-0.5">O prompt que cada agente usa para reengajar o lead naquela etapa.</p>
            </div>
            {fupStages.length === 0 ? (
              <div className="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">
                Marque ao menos uma etapa acima para escrever os prompts.
              </div>
            ) : (
              <div className="grid lg:grid-cols-[220px_minmax(0,1fr)] gap-5 items-start">
                <div className="space-y-1.5">
                  {fupStages.map((s) => {
                    const has = (fupAgentes[s].prompt ?? "").trim().length > 20;
                    const active = fupActiveOk === s;
                    return (
                      <button
                        key={s}
                        onClick={() => setFupActive(s)}
                        style={active ? { backgroundColor: `${catC1}14`, borderColor: `${catC1}66` } : undefined}
                        className={`w-full text-left px-3 py-2.5 rounded-xl text-sm font-medium border transition-colors flex items-center gap-2.5 ${active ? "" : "bg-card hover:bg-accent border-transparent"}`}
                      >
                        {has ? <CheckCircle2 className="size-4 shrink-0" style={{ color: catC1 }} /> : <Circle className="size-4 shrink-0 text-muted-foreground/40" />}
                        <div className="min-w-0">
                          <div className="truncate" style={active ? { color: catC1 } : undefined}>{STAGE_LABELS[s]}</div>
                          <div className="text-[10px] text-muted-foreground">{has ? "Prompt configurado" : "Prompt pendente"}</div>
                        </div>
                      </button>
                    );
                  })}
                </div>
                <FollowupAgentEditor
                  key={fupActiveOk}
                  stage={fupActiveOk}
                  value={{ name: fupAgentes[fupActiveOk].name, prompt: fupAgentes[fupActiveOk].prompt }}
                  onChange={(next) => setFupAgentes((prev) => ({ ...prev, [fupActiveOk]: { ...prev[fupActiveOk], name: next.name, prompt: next.prompt } }))}
                  handoffOptions={fupStages.filter((s) => s !== fupActiveOk).map((s) => STAGE_LABELS[s])}
                />
              </div>
            )}
          </Card>
        </TabsContent>

      </Tabs>

      <MediaLibrary
        open={libraryOpen}
        onOpenChange={setLibraryOpen}
        onInsert={(token) => richRef.current?.insertText(token)}
      />
      <FrasesTrocaDialog
        open={frasesOpen}
        onOpenChange={setFrasesOpen}
        onExcluida={(f) => {
          setAgentes((lista) => lista.map((ag) => ({ ...ag, prompt: trocarTokenPorTexto(ag.prompt, f) })));
          setEditorKey((n) => n + 1);
        }}
      />
    </div>
    </FrasesProdutoProvider>
  );
}
