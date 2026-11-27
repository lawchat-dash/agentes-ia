import { useMemo, useRef } from "react";
import { useParams, Link, Navigate } from "react-router-dom";
import { Loader2 } from "lucide-react";
import ProductConfigurator, { ProductConfiguratorEditData } from "@/components/agent/ProductConfigurator";
import { useProduct, useProductTemplateAgents, ROLE_META, ROLE_ORDER, ALL_ROLES_ORDERED, roleSortIndex, AgentRole } from "@/hooks/useProducts";
import { recolherHandoffsDoBot } from "@/data/handoffTargets";
import { llmModels } from "@/data/llmModels";
import { useFrasesTroca } from "@/hooks/useFrasesTroca";
import { setProdutoFrases } from "@/data/frasesTroca";

/** Mapeia um nome/id de modelo (catálogo ou bot) para um id de llmModels; senão undefined. */
const mapModelId = (s: any): string | undefined => {
  const norm = String(s ?? "").toLowerCase().trim();
  if (!norm) return undefined;
  const byId = llmModels.find((m) => m.id.toLowerCase() === norm);
  if (byId) return byId.id;
  const byName = llmModels.find((m) => m.name.toLowerCase() === norm);
  return byName?.id;
};

/**
 * Editor de produto já ativado (/meus-produtos/:id).
 * Reusa o MESMO wizard da ativação (ProductConfigurator) em modo "edit", com PARIDADE
 * de dados ao criar agente: nomes/modelo vêm do catálogo (GET /biblioteca/produtos/{id}/agentes,
 * mesma fonte do create) e o conteúdo customizado (prompts, boas-vindas, frase de troca,
 * comportamento) vem do agente criado (GET /produtos-ativados/{id} → etapas). Salva via
 * POST /produtos-ativados/{id}/sincronizar (mesmo payload da ativação).
 */
const ProdutoEditor = () => {
  const { id } = useParams();
  const { data: product, isLoading } = useProduct(id);
  const { data: catalogAgents, isLoading: catalogLoading } = useProductTemplateAgents(
    (product as any)?.source_template_id,
  );
  // Frases para Transferência: o recolhimento (texto exato do bot → chip "@Transferência") depende do
  // registro carregado — espera antes de montar os dados do editor.
  // Frases do PRODUTO de origem (catálogo) — cada produto tem as suas. Fixa o produto atual do
  // registro ANTES do useMemo abaixo (recolherHandoffsDoBot usa as frases dele).
  const idProdutoCatalogo: string | null = (product as any)?.source_template_id ?? null;
  setProdutoFrases(idProdutoCatalogo);
  const { data: frasesTroca, isLoading: frasesLoading } = useFrasesTroca(idProdutoCatalogo);

  const editData = useMemo<ProductConfiguratorEditData | null>(() => {
    if (!product) return null;
    const p = product as any;

    const etapas = (Array.isArray(p.etapas) ? p.etapas : [])
      .slice()
      .sort((a: any, b: any) => a.ordem - b.ordem);

    const catByRole = new Map<string, any>(
      (Array.isArray(catalogAgents) ? catalogAgents : []).map((c: any) => [c.role, c]),
    );

    // PipelineAgents: config vivo do bot (prompt/gatilho/boas-vindas) + nome do catálogo.
    // Só os papéis conversacionais editáveis. Etapas TERMINAIS (contratoassinado,
    // iadesativada) são fim de funil, sem prompt — não viram agente editável (e não
    // existem no ROLE_META, o que quebrava o render do ícone no ProductConfigurator).
    let pipelineAgents = etapas
      .filter((e: any) => (ALL_ROLES_ORDERED as string[]).includes(e.etapa))
      .map((e: any) => {
        const role = e.etapa as AgentRole;
        const cat = catByRole.get(role) ?? {};
        const cfg = e.config ?? {};
        // O prompt vem do bot já EXPANDIDO ("acionar tool `x`"). No front (edição) mostramos
        // o rótulo amigável "@Agente X", igual à criação — recolherHandoffsDoBot faz o reverso.
        const prompt = recolherHandoffsDoBot(e.prompt ?? cat.prompt_text ?? "");
        return {
          id: role,
          role,
          // Nome gravado no agente (o cliente pode ter renomeado) → senão o do catálogo.
          name: e.nome || cat.display_name || ROLE_META[role]?.label || role,
          welcome: cfg.boas_vindas ?? cfg.welcome_message ?? cat.welcome_message ?? "",
          blocks: [
            { id: "freeform", type: "freeform", icon: "📝", label: "Prompt", content: prompt },
            { id: "handoff_trigger", type: "handoff_trigger", icon: "🔀", label: "Gatilho de transferência", content: recolherHandoffsDoBot(e.mensagem_troca ?? "") },
          ],
          promptText: prompt,
          saved: true,
        };
      })
      .sort((a: any, b: any) => roleSortIndex(a.role) - roleSortIndex(b.role));

    // Período de Graça: etapa que o ADMIN habilitou no produto (oferece_periodo_graca).
    // Para o cliente é só mais um agente do funil (após o SDR) — sem toggle aqui.
    const oferecePeriodoGraca = !!p.oferece_periodo_graca;

    // Produto OFERECE mas o bot ainda não tem a etapa (ativado antes desta feature):
    // semeia um agente do catálogo p/ ela aparecer no funil; salva → o 0123 cria a etapa.
    if (oferecePeriodoGraca && !pipelineAgents.some((a: any) => a.role === "periododegraca")) {
      const cat = catByRole.get("periododegraca") ?? {};
      const seedPrompt = recolherHandoffsDoBot(cat.prompt_text ?? "");
      pipelineAgents = [...pipelineAgents, {
        id: "periododegraca",
        role: "periododegraca" as AgentRole,
        name: cat.display_name ?? ROLE_META.periododegraca.label,
        welcome: cat.welcome_message ?? "",
        blocks: [
          { id: "freeform", type: "freeform", icon: "📝", label: "Prompt", content: seedPrompt },
          { id: "handoff_trigger", type: "handoff_trigger", icon: "🔀", label: "Gatilho de transferência", content: "" },
        ],
        promptText: seedPrompt,
        saved: true,
      }].sort((a: any, b: any) => roleSortIndex(a.role) - roleSortIndex(b.role));
    }

    // config completo da etapa por papel (base p/ regravar no bot sem perder áudio/gatilhos/etc).
    const configByRole: Record<string, any> = {};
    etapas.forEach((e: any) => { configByRole[e.etapa] = e.config ?? {}; });

    // Conteúdo de nível produto: aqui a fonte da verdade são as colunas do produto (o mesmo payload
    // grava as duas coisas), com fallback no config da etapa principal.
    const principal = etapas.find((e: any) => e.etapa === "sdr") ?? etapas[0] ?? {};
    const pcfg = principal.config ?? {};
    const pmc = pcfg.model_config ?? {};
    // Comportamento do agente (modelo/temperatura/delay/pausa/canal): GET /produtos-ativados/{id} → agente.
    const ag = p.agente ?? {};
    const rasc = p.rascunho ?? {};

    const botFaq = Array.isArray(pmc.faq_items) ? pmc.faq_items : [];
    const faqItems = (Array.isArray(p.faq_items) && p.faq_items.length) || !botFaq.length
      ? (Array.isArray(p.faq_items) ? p.faq_items : [])
      : botFaq.map((f: any) => ({ pergunta: f.q ?? f.pergunta ?? "", resposta: f.a ?? f.resposta ?? "" }));

    const botObj = Array.isArray(pmc.objecoes) ? pmc.objecoes : [];
    const objectionItems = (Array.isArray(p.objection_items) && p.objection_items.length) || !botObj.length
      ? (Array.isArray(p.objection_items) ? p.objection_items : [])
      : botObj.map((o: any) => ({ titulo: o.gatilho ?? o.titulo ?? "", resposta: o.resposta ?? "" }));

    const generalRules = (p.rules_markdown && p.rules_markdown.trim())
      ? p.rules_markdown
      : (pmc.rules_markdown ?? "");

    // Dados do Escritório (nível produto): coluna do produto (fallback: etapa / rascunho).
    const dadosEscritorio = p.dados_escritorio
      ?? (etapas.find((e: any) => e.dados_escritorio)?.dados_escritorio)
      ?? (typeof rasc.dadosEscritorio === "string" ? rasc.dadosEscritorio : "");

    // Regras de handoff do CATÁLOGO por papel (com keywords) — fallback p/ o Teste de prompt
    // quando o agente ativado tem config.handoff_rules vazio (produtos antigos).
    const catalogHandoffByRole: Record<string, any[]> = {};
    ALL_ROLES_ORDERED.forEach((r) => {
      const rules = (catByRole.get(r) as any)?.default_handoff_rules;
      catalogHandoffByRole[r] = Array.isArray(rules) ? rules : [];
    });

    // Comportamento real do agente.
    const selectedModel = mapModelId(ag.modelo) ?? mapModelId(pcfg.modelo) ?? mapModelId(principal.modelo)
      ?? mapModelId(rasc.selectedModel)
      ?? mapModelId((catByRole.get("sdr") ?? {}).recommended_model);
    const num = (...vs: any[]): number | undefined => vs.find((v) => typeof v === "number" && !Number.isNaN(v));

    // Template mínimo (o configurator só usa id/name/version/category em edição).
    // modo_midia é essencial: liga a "Edição rápida de mídias" (isAudio) no modo edição.
    const st = p.source_template ?? {};
    const template = {
      id: p.source_template_id ?? st.id,
      name: st.name ?? p.name,
      version: p.source_template_version ?? st.version,
      category: st.category ?? null,
      recommended_model: selectedModel,
      modo_midia: st.modo_midia ?? "texto",
    };

    return {
      template,
      groupId: p.id,
      weaverAgentId: p.weaver_agent_id ?? null,
      name: p.name ?? "",
      numeroIa: p.numero_ia ?? null,
      idCanal: ag.id_canal ?? p.id_canal ?? null,
      pipelineAgents,
      faqItems,
      objectionItems,
      knowledgeItems: Array.isArray(p.knowledge_items) ? p.knowledge_items : [],
      integrations: p.integrations ?? {},
      generalRules,
      dadosEscritorio,
      // Honorários (transcrição do áudio) gravados no agente; undefined = nunca gravado (vale o do produto).
      honorariosTexto: typeof p.honorarios_texto === "string" ? p.honorarios_texto
        : (typeof rasc.honorariosTexto === "string" ? rasc.honorariosTexto : undefined),
      selectedModel,
      temperature: num(ag.temperatura, pcfg.temperatura, pmc.temperature, Array.isArray(rasc.temperature) ? rasc.temperature[0] : undefined),
      // Delay de resposta / pausa: nível AGENTE. Sem isso o wizard caía no default (10s / 30min)
      // e sobrescrevia o valor real ao salvar.
      responseDelay: num(ag.delay_s, pcfg.delay_s, principal.intervalo_entre_mensagens, rasc.responseDelay),
      charsMsg: typeof ag.caracteres_msg === "number" ? ag.caracteres_msg : (typeof rasc.charsMsg === "number" ? rasc.charsMsg : 0),
      humanPause: num(ag.pausa_min, pcfg.pausa_min, pcfg.pausa_humano_min, rasc.humanPause),
      schedule24: pcfg.schedule ? pcfg.schedule.mode === "always" : (typeof rasc.schedule24 === "boolean" ? rasc.schedule24 : undefined),
      configByRole,
      catalogHandoffByRole,
      oferecePeriodoGraca,
      atualizacaoDisponivel: !!p.atualizacao_disponivel,
      versaoCatalogo: p.versao_catalogo ?? null,
      // Voltou da lixeira sem número: o mesmo editor vira a reativação (escolhe o número e ativa).
      precisaAtivar: !!p.precisa_ativar,
      numeroLiberado: p.numero_liberado ?? null,
      followup: p.followup_situacao ?? null,
    };
    // frasesTroca: recalcula quando as frases chegam (recolherHandoffsDoBot lê o registro).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [product, catalogAgents, frasesTroca]);

  // Uma vez aberto, o editor NUNCA volta para o "carregando" (isso o desmontaria e apagaria o que
  // está sendo digitado). Re-buscas em segundo plano (invalidação, reconexão) só atualizam o cache.
  // editData também fica congelado: o wizard usa só os valores iniciais.
  const prontoRef = useRef<ProductConfiguratorEditData | null>(null);
  if (prontoRef.current && prontoRef.current.groupId !== id) prontoRef.current = null; // trocou de produto
  if (!prontoRef.current && editData && !isLoading && !catalogLoading && !frasesLoading) prontoRef.current = editData;
  const dadosEditor = prontoRef.current;

  if (!dadosEditor && (isLoading || catalogLoading || frasesLoading)) return <div className="grid place-items-center py-20"><Loader2 className="size-8 text-primary animate-spin" /></div>;

  // Rascunho nunca ativado (sem agente) NÃO pode ser editado — o Passo 3 ficaria sem etapas e o
  // salvar exige o agente. O certo é RETOMAR a ativação:
  // o wizard de create restaura o rascunho (bootstrapPipeline) e provisiona ao ativar.
  if (product && !(product as any).weaver_agent_id) {
    const slug = (product as any).source_template?.slug;
    if (slug) return <Navigate to={`/ativar/${slug}`} replace />;
    return (
      <div className="p-8 text-center max-w-md mx-auto">
        <p className="text-muted-foreground">Este produto ainda é um rascunho e não foi ativado. Retome a ativação pela biblioteca.</p>
        <Link to="/biblioteca" className="text-primary font-semibold mt-3 inline-block">Ir para a biblioteca</Link>
      </div>
    );
  }

  if (!dadosEditor) return <div className="p-8">Produto não encontrado. <Link to="/meus-produtos" className="text-primary">Voltar</Link></div>;

  // key força remontar quando troca de produto (estado interno do configurator é por-montagem).
  return <ProductConfigurator key={dadosEditor.groupId} mode="edit" editData={dadosEditor} />;
};

export default ProdutoEditor;
