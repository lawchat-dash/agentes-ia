import { useState, useRef, useEffect, useMemo } from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Send, RotateCcw, Loader2, FlaskConical, BrainCircuit, ArrowRight, CheckCircle2, UserRound, Wrench } from "lucide-react";
import { toast } from "sonner";
import { ROLE_META, ROLE_ORDER, type AgentRole } from "@/hooks/useProducts";
import { detectarAcaoNoTexto, limparAcoesDoTexto, TOOL_TARGETS } from "@/data/handoffTargets";
import { expandirFrasesParaBot } from "@/data/frasesTroca";
import { useFrasesTroca } from "@/hooks/useFrasesTroca";
import { buscarCep, extrairCep, formatarEndereco } from "@/lib/buscarCep";

/**
 * TESTE DE PROMPT — funil multi-agente com memória e transições automáticas.
 *
 * Orquestra o funil inteiro no front (sem mexer na edge): a cada turno chama a edge
 * `agent-chat` com o prompt da ETAPA ATUAL + o histórico inteiro (memória) + uma
 * instrução de handoff. Quando o agente decide avançar, emite o marcador
 * `[[HANDOFF:<papel>]]` (igual ao Switch do n8n) — detectamos, trocamos de agente
 * mantendo a memória, e seguimos até a etapa final.
 */

type AgentLite = {
  role: AgentRole;
  name?: string | null;
  welcome?: string | null;
  promptText?: string | null;
  blocks?: any[] | null;
};

type ChatItem =
  | { kind: "msg"; role: "user" | "assistant"; content: string; agent?: AgentRole }
  | { kind: "transition"; to: AgentRole }
  | { kind: "tool"; label: string; agent?: AgentRole };

// Para onde cada etapa pode transferir (só entram as que existem no produto).
const FUNNEL_NEXT: Record<string, AgentRole[]> = {
  sdr: ["closer", "desqualificado"],
  closer: ["contratos", "desqualificado"],
  contratos: ["assinatura", "desqualificado"],
  assinatura: [],
  follow_up: [],
  desqualificado: [],
};

const HANDOFF_RE = /\[\[\s*HANDOFF\s*:\s*([a-z0-9_-]+)\s*\]\]/i;

const blocosParaTexto = (blocks?: any[] | null): string => {
  if (!Array.isArray(blocks)) return "";
  return blocks
    .map((b) => {
      const c = b?.content;
      const corpo = Array.isArray(c) ? c.map((x) => `- ${x}`).join("\n") : (c ?? "");
      return b?.label ? `## ${b.label}\n${corpo}` : String(corpo);
    })
    .filter(Boolean)
    .join("\n\n");
};

/** Limpeza do texto (igual ao fluxo do bot no n8n): aspas, chamadas de função, \n, espaços, negrito. */
const limparTexto = (s: string) =>
  s.replace(/^"|"$/g, "")
    .replace(/functions?\.\w+\(\)/g, "")
    .replace(/\\n/g, "\n")
    .replace(/[ \t]{2,}/g, " ")
    .replace(/\*\*(.*?)\*\*/g, "*$1*")
    .trim();

const URL_RE = /(https?:\/\/[^\s]+)/g;
const ehUrl = (s: string) => /^https?:\/\/\S/.test(s.trim());

/** Quebra a resposta em várias mensagens (igual ao bot): links viram mensagem isolada,
 *  texto quebra por \n. Cada item vira um balão separado no teste. */
const quebrarMensagem = (texto: string): string[] => {
  const t = limparTexto(texto);
  if (!t) return [];
  const out: string[] = [];
  t.split(URL_RE).forEach((seg) => {
    if (ehUrl(seg)) {
      const url = seg.replace(/\n/g, "").trim();
      if (url) out.push(url);
    } else {
      seg.split("\n").forEach((l) => { const c = l.trim(); if (c) out.push(c); });
    }
  });
  return out;
};

/** Tipo de mídia pela URL (extensão ou pasta agent-media). */
const tipoMidia = (url: string): "image" | "video" | "audio" | null => {
  const u = url.toLowerCase().split("?")[0];
  if (/\.(png|jpe?g|webp|gif|svg)$/.test(u) || /\/(image|imagem)\//.test(u)) return "image";
  if (/\.(mp4|webm|mov|m4v)$/.test(u) || /\/video\//.test(u)) return "video";
  if (/\.(ogg|oga|opus|mp3|wav|m4a|aac|flac)$/.test(u) || /\/audio\//.test(u)) return "audio";
  return null;
};

export const TestePrompt = ({
  agents,
  startRole,
  generalRules,
  dadosEscritorio,
  faqItems = [],
  objectionItems = [],
  model,
  handoffByRole,
  handoffRulesByRole,
  c1,
  c2,
}: {
  agents: AgentLite[];
  startRole?: AgentRole;
  generalRules?: string | null;
  dadosEscritorio?: string | null;
  faqItems?: { pergunta: string; resposta: string }[];
  objectionItems?: { titulo: string; resposta: string }[];
  model?: string;
  /** Transições REAIS do produto por papel (target_role dos handoff_rules). Cai no FUNNEL_NEXT se ausente. */
  handoffByRole?: Record<string, string[]>;
  /** Regras de handoff COMPLETAS por papel (com keywords/trigger) — alimentam o "quando" no system prompt. */
  handoffRulesByRole?: Record<string, { target_role?: string; keywords?: string[]; trigger?: string }[]>;
  c1: string;
  c2: string;
}) => {
  const byRole = useMemo(() => new Map(agents.map((a) => [a.role, a])), [agents]);
  // Próximas etapas REAIS de um papel: usa as transições do produto (handoffByRole) e cai no
  // FUNNEL_NEXT como fallback; sempre filtrando por etapas que EXISTEM no produto (= no n8n,
  // agente_etapas.find(e => e.etapa === alvo)).
  // Frases para Transferência (registro p/ expandir o prompt de teste + detectar a troca na resposta).
  const { data: frasesTroca } = useFrasesTroca();

  const nextOf = (role: string): AgentRole[] => {
    // Papel PRESENTE no mapa (mesmo com []) = autoridade do produto → etapa final é respeitada.
    // Só cai no FUNNEL_NEXT quando o papel está AUSENTE do mapa (produto sem dados de handoff).
    const temNoMapa = !!handoffByRole && Object.prototype.hasOwnProperty.call(handoffByRole, role);
    const base = (temNoMapa ? (handoffByRole![role] ?? []) : (FUNNEL_NEXT[role] ?? [])) as string[];
    return base.filter((r) => byRole.has(r as AgentRole)) as AgentRole[];
  };

  // Começo do funil (etapa principal = primeira presente em ROLE_ORDER → sdr).
  const funnelStart = (ROLE_ORDER.find((r) => byRole.has(r)) as AgentRole) ?? agents[0]?.role;
  // Toggle: testar o funil do INÍCIO vs. testar a etapa que está sendo editada.
  const [fromStart, setFromStart] = useState(true);
  const firstRole = fromStart ? funnelStart : (startRole ?? funnelStart);

  const [activeRole, setActiveRole] = useState<AgentRole>(firstRole);
  const [items, setItems] = useState<ChatItem[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  // Geração da conversa: ao resetar, incrementa e invalida qualquer stream em andamento.
  const genRef = useRef(0);
  const ctrlRef = useRef<AbortController | null>(null);
  const transitionsRef = useRef(0); // teto anti-loop de transições por sessão

  // Antes de começar a conversa, o teste acompanha o papel inicial (recomputa no toggle).
  useEffect(() => {
    if (items.length === 0 && firstRole) setActiveRole(firstRole);
  }, [firstRole, items.length]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [items, streaming]);

  const reset = () => {
    genRef.current++;            // invalida qualquer stream em andamento
    ctrlRef.current?.abort();    // aborta o request atual (agente lento/travado)
    ctrlRef.current = null;
    setStreaming(false);
    setInput("");
    setItems([]);
    setActiveRole(firstRole);
    transitionsRef.current = 0;
  };

  // Troca o modo de teste (funil do início ↔ esta etapa) e reinicia a conversa.
  const setModo = (v: boolean) => {
    setFromStart(v);
    genRef.current++;
    ctrlRef.current?.abort();
    ctrlRef.current = null;
    setStreaming(false);
    setInput("");
    setItems([]);
    transitionsRef.current = 0;
    setActiveRole(v ? funnelStart : (startRole ?? funnelStart));
  };

  // Modo "Esta etapa": se o usuário navega para outro agente no editor (startRole muda) com a
  // conversa já iniciada, reinicia o teste — senão continuaria testando o papel anterior.
  const prevStartRef = useRef(startRole);
  useEffect(() => {
    if (!fromStart && startRole && startRole !== prevStartRef.current && items.length > 0) reset();
    prevStartRef.current = startRole;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [startRole, fromStart]);

  const msgCount = items.filter((i) => i.kind === "msg").length;
  const activeMeta = ROLE_META[activeRole];
  const ActiveIcon = activeMeta?.Icon ?? FlaskConical;
  const isFinal = nextOf(activeRole).length === 0;

  // Etapas para o stepper (caminho principal presente no produto).
  const funnelPath = ROLE_ORDER.filter((r) => r !== "desqualificado" && byRole.has(r));

  // "Lead (teste)" = o lead.id_etapa_atual do bot, mas em memória (pelo NOME da etapa, sem DB).
  // Trilha = caminho REAL percorrido (inclui desqualificado/voltas que o stepper linear não mostra).
  const transicoes = items.filter((i): i is Extract<ChatItem, { kind: "transition" }> => i.kind === "transition");
  const trilha = [firstRole, ...transicoes.map((t) => t.to)].filter(Boolean) as AgentRole[];
  const veioDe = trilha.length > 1 ? trilha[trilha.length - 2] : null;
  const labelDe = (r: AgentRole) => ROLE_META[r]?.label ?? r;

  // Monta o system prompt da etapa: prompt do agente + contexto global + instrução de handoff.
  const buildSystem = (role: AgentRole): string => {
    const a = byRole.get(role);
    // @Transferência → texto exato da frase (igual ao que vai pro bot): a IA precisa ver a frase real.
    const base = expandirFrasesParaBot((a?.promptText && a.promptText.trim()) || blocosParaTexto(a?.blocks) || `Você é o agente da etapa ${role}.`);
    // Gatilho de transferência DESTA etapa (bloco handoff_trigger / mensagem_troca): o critério
    // REAL de "quando" passar adiante. Não vem no promptText, então injetamos na orquestração —
    // sem isso o LLM decidiria o momento por conta própria, não pelo gatilho configurado.
    const gatilho = (Array.isArray(a?.blocks) ? a!.blocks : [])
      .find((b: any) => b?.type === "handoff_trigger")?.content;
    const gatilhoTxt = typeof gatilho === "string" ? gatilho.trim() : "";
    const targets = nextOf(role);
    const partes: string[] = [base];
    if (generalRules && generalRules.trim()) partes.push(`# REGRAS GERAIS\n${generalRules.trim()}`);
    if (dadosEscritorio && dadosEscritorio.trim()) partes.push(`# DADOS DO ESCRITÓRIO\n${dadosEscritorio.trim()}`);
    if (faqItems.length) partes.push(`# FAQ\n${faqItems.map((f) => `P: ${f.pergunta}\nR: ${f.resposta}`).join("\n\n")}`);
    if (objectionItems.length) partes.push(`# OBJEÇÕES\n${objectionItems.map((o) => `- ${o.titulo}: ${o.resposta}`).join("\n")}`);
    if (TOOL_TARGETS.length) {
      partes.push(
        `# FERRAMENTAS (TESTE)\nQuando o contexto pedir, acione uma ferramenta escrevendo em uma linha ` +
        `isolada: acionar tool \`nome\` (para o CEP, inclua o número: acionar tool \`buscarcep\` 30130-000). ` +
        `Disponíveis: ` +
        TOOL_TARGETS.map((t) => `${t.label} → acionar tool \`${t.tool}\``).join("; ") +
        `. O resultado da ferramenta volta pra você na mensagem seguinte; nunca mostre o comando ao lead.`
      );
    }
    if (targets.length) {
      const lista = targets.map((r) => `${r} (${ROLE_META[r]?.label ?? r})`).join(", ");
      // Regras REAIS do produto (regras_handoff): trigger por palavra-chave → target_role.
      // Injetar as keywords é o que dá ao LLM o "quando" certo (= o que o bot faz por on_keyword).
      const regras = (handoffRulesByRole?.[role] ?? []) as any[];
      const regrasTxt = regras
        .filter((r) => r?.target_role && byRole.has(r.target_role as AgentRole) && Array.isArray(r?.keywords) && r.keywords.length)
        .map((r) => `- → ${r.target_role}: quando o lead disser ou demonstrar algo como ${r.keywords.map((k: string) => `"${k}"`).join(", ")}.`)
        .join("\n");
      partes.push(
        `# ORQUESTRAÇÃO DO FUNIL (TESTE)\nVocê é a etapa "${ROLE_META[role]?.label ?? role}". ` +
        `Pode transferir o atendimento para: ${lista}.\n` +
        (regrasTxt ? `Regras de transferência configuradas (o "quando" certo de cada destino):\n${regrasTxt}\n` : "") +
        (gatilhoTxt ? `Critério adicional desta etapa: ${gatilhoTxt}\n` : "") +
        `Assim que o lead atender a uma dessas regras (avançar de etapa ou ser desqualificado), ` +
        `TRANSFIRA — não fique insistindo na sua etapa. Responda normalmente ao lead e ACRESCENTE no final, ` +
        `em uma linha isolada, o marcador exato [[HANDOFF:papel]] (ex.: [[HANDOFF:${targets[0]}]]) usando o ` +
        `papel EXATO do destino. Nunca explique nem mostre o marcador ao lead; se ainda não é hora, não inclua o marcador.`
      );
    } else {
      partes.push(`# ETAPA FINAL (TESTE)\nVocê é a última etapa do funil. Conduza até o encerramento; não transfira para ninguém.`);
    }
    return partes.join("\n\n");
  };

  const historyFor = (): { role: "user" | "assistant"; content: string }[] =>
    items.filter((i): i is Extract<ChatItem, { kind: "msg" }> => i.kind === "msg")
      .map((m) => ({ role: m.role, content: m.content }));

  // esconde o [[HANDOFF]] (mesmo parcial) E os sinais @ / "acionar tool `x`" do texto exibido
  const limparExibicao = (full: string) =>
    limparAcoesDoTexto(full.replace(/\[\[\s*HANDOFF[^\]]*\]?\]?\s*$/i, "").replace(HANDOFF_RE, ""));

  /** Papel de handoff a partir de um texto: pelo [[HANDOFF:role]] OU pelo @ / "acionar tool `x`". */
  const handoffRoleDe = (texto: string): string | undefined => {
    const mm = texto.match(HANDOFF_RE);
    if (mm?.[1]) return mm[1].toLowerCase();
    const a = detectarAcaoNoTexto(texto);
    if (a?.kind === "handoff") return a.role.toLowerCase();
    // Frase para Transferência: igual ao bot — a IA falou a frase exata de outra etapa → o lead vai para ela.
    const f = (frasesTroca ?? []).find((x) => x.etapa_destino !== activeRole && texto.includes(x.frase));
    return f?.etapa_destino;
  };

  /** Streama UM turno do agente (escreve no último balão do assistente) e devolve o texto cru. */
  const streamTurn = async (
    hist: { role: "user" | "assistant"; content: string }[],
    message: string,
    myGen: number,
    controller: AbortController,
  ): Promise<string> => {
    // Teste de prompt está "EM BREVE" (o painel não renderiza este componente). Sem endpoint de chat aqui.
    const res = await fetch(`/api/teste-prompt`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ system_prompt: buildSystem(activeRole), history: hist, message, model }),
      signal: controller.signal,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: res.statusText }));
      throw new Error(err.error || `HTTP ${res.status}`);
    }
    if (!res.body) throw new Error("Sem corpo de resposta");

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let raw = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      if (genRef.current !== myGen) break; // resetado durante o stream → para de escrever
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        try {
          const payload = JSON.parse(line.slice(6));
          if (payload.type === "delta") {
            raw += payload.content;
            const shown = limparExibicao(raw);
            setItems((prev) => {
              const copy = [...prev];
              copy[copy.length - 1] = { kind: "msg", role: "assistant", content: shown, agent: activeRole };
              return copy;
            });
          }
        } catch { /* ignora */ }
      }
    }
    return raw;
  };

  const send = async () => {
    if (!input.trim() || streaming) return;
    const userMsg = input.trim();
    const history = historyFor();
    setInput("");
    setItems((prev) => [...prev, { kind: "msg", role: "user", content: userMsg }, { kind: "msg", role: "assistant", content: "", agent: activeRole }]);
    setStreaming(true);

    const myGen = ++genRef.current;
    const controller = new AbortController();
    ctrlRef.current = controller;

    try {
      const raw1 = await streamTurn(history, userMsg, myGen, controller);
      if (genRef.current !== myGen) return;
      let raw2 = ""; // resposta do auto-continue (depois de rodar uma ferramenta)

      // FERRAMENTA DE AÇÃO: roda de verdade e devolve o resultado pro agente continuar.
      const acao = detectarAcaoNoTexto(raw1);
      if (acao?.kind === "tool" && acao.tool === "buscarcep") {
        // CEP: na própria chamada da tool OU na conversa (o lead acabou de informar).
        const cep = extrairCep(raw1) ?? extrairCep([...history.map((h) => h.content), userMsg].join("  "));
        const endereco = cep ? await buscarCep(cep) : null;
        const resumo = endereco
          ? `${formatarEndereco(endereco)} (CEP ${endereco.cep})`
          : cep ? `CEP ${cep} não encontrado` : "CEP não informado";
        if (genRef.current !== myGen) return;
        setItems((prev) => [...prev, { kind: "tool", label: `Buscar CEP → ${resumo}`, agent: activeRole }]);
        // auto-continue: alimenta o resultado e o agente responde usando o endereço.
        const histTool = [
          ...history,
          { role: "user" as const, content: userMsg },
          { role: "assistant" as const, content: limparExibicao(raw1) },
        ];
        setItems((prev) => [...prev, { kind: "msg", role: "assistant", content: "", agent: activeRole }]);
        raw2 = await streamTurn(
          histTool,
          `[RESULTADO DA FERRAMENTA buscarcep] ${resumo}. Responda ao lead usando esse endereço; não repita o comando da ferramenta.`,
          myGen,
          controller,
        );
        if (genRef.current !== myGen) return;
      } else if (acao?.kind === "tool") {
        // outras ferramentas (ex.: Desenvolver Documento): só mostra que foi acionada.
        setItems((prev) => [...prev, { kind: "tool", label: acao.label, agent: activeRole }]);
      }

      // HANDOFF (mantendo a memória): no turno principal OU no auto-continue.
      if (genRef.current !== myGen) return;
      const alvo = handoffRoleDe(raw1) ?? handoffRoleDe(raw2);
      if (alvo && byRole.has(alvo as AgentRole) && alvo !== activeRole && transitionsRef.current < 12) {
        transitionsRef.current++;
        setItems((prev) => [...prev, { kind: "transition", to: alvo as AgentRole }]);
        setActiveRole(alvo as AgentRole);
      }
    } catch (e: any) {
      // Abort (reset) ou geração antiga → silencioso, sem tocar no estado novo.
      if (e?.name === "AbortError" || genRef.current !== myGen) return;
      toast.error("Erro no teste", { description: e.message });
      setItems((prev) => prev.slice(0, -1)); // remove o balão vazio do assistente
    } finally {
      if (genRef.current === myGen) setStreaming(false);
    }
  };

  const welcome = byRole.get(activeRole)?.welcome;

  return (
    <div className="rounded-2xl border border-[#E6EAF0] bg-white shadow-sm flex flex-col h-[620px] max-h-[calc(100vh-6rem)] min-h-[480px] overflow-hidden">
      {/* Header — agente atual + memória */}
      <div className="px-4 py-3 border-b border-[#EEF1F5]" style={{ background: `linear-gradient(180deg, ${c1}10, transparent)` }}>
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <div className="size-8 rounded-lg grid place-items-center text-white shrink-0" style={{ backgroundImage: `linear-gradient(135deg, ${c1}, ${c2})` }}>
              <ActiveIcon className="size-4" />
            </div>
            <div className="min-w-0">
              <div className="text-[10px] font-bold uppercase tracking-wide text-[#98A2B3] leading-none flex items-center gap-1">
                <FlaskConical className="size-3" /> Teste de prompt
              </div>
              <div className="text-sm font-bold text-[#101828] truncate leading-tight mt-0.5">
                {activeMeta?.label ?? activeRole}{isFinal && <span className="ml-1.5 text-[10px] font-semibold text-[#98A2B3]">· etapa final</span>}
              </div>
            </div>
          </div>
          <Button size="sm" variant="ghost" onClick={reset} className="shrink-0 text-[#667085]">
            <RotateCcw className="size-3.5 mr-1" />Reiniciar
          </Button>
        </div>

        {/* Stepper do funil */}
        <div className="flex items-center gap-1 mt-2.5">
          {funnelPath.map((r, i) => {
            const done = funnelPath.indexOf(activeRole) > i;
            const here = r === activeRole;
            return (
              <div key={r} className="flex items-center gap-1 min-w-0">
                <span
                  className="text-[10px] font-semibold px-1.5 py-0.5 rounded-md whitespace-nowrap transition-colors"
                  style={here ? { backgroundImage: `linear-gradient(135deg, ${c1}, ${c2})`, color: "#fff" }
                    : done ? { backgroundColor: `${c1}1a`, color: c1 }
                    : { backgroundColor: "#F2F4F7", color: "#98A2B3" }}
                >
                  {ROLE_META[r]?.label ?? r}
                </span>
                {i < funnelPath.length - 1 && <ArrowRight className="size-3 text-[#D0D5DD] shrink-0" />}
              </div>
            );
          })}
          {activeRole === "desqualificado" && (
            <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-md" style={{ backgroundImage: `linear-gradient(135deg, ${c1}, ${c2})`, color: "#fff" }}>
              {ROLE_META.desqualificado?.label ?? "Desqualificado"}
            </span>
          )}
        </div>

        {/* Modo: testa o funil do início (sdr→…) ou só a etapa em edição */}
        <div className="flex items-center gap-0.5 mt-2.5 rounded-lg bg-[#F2F4F7] p-0.5 w-fit">
          {[{ v: true, label: "Funil do início" }, { v: false, label: "Esta etapa" }].map((opt) => (
            <button
              key={String(opt.v)}
              type="button"
              onClick={() => setModo(opt.v)}
              title={opt.v ? "Começa pelo SDR e avança sozinho pelas etapas" : "Testa só a etapa que você está editando"}
              className={`text-[10px] font-semibold px-2 py-1 rounded-md transition-colors ${fromStart === opt.v ? "bg-white text-[#101828] shadow-sm" : "text-[#98A2B3] hover:text-[#475467]"}`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Lead (teste) — espelha o lead.id_etapa_atual do bot, em memória (nome da etapa, sem DB) */}
      <div className="px-4 py-2 border-b border-[#EEF1F5] bg-[#FBFCFD] flex items-center gap-x-2 gap-y-1 flex-wrap text-[11px]">
        <span className="inline-flex items-center gap-1 font-semibold text-[#475467] shrink-0">
          <UserRound className="size-3" /> Lead (teste)
        </span>
        <span className="text-[#D0D5DD]">·</span>
        <span className="text-[#667085]">etapa atual: <b className="text-[#101828]">{labelDe(activeRole)}</b></span>
        {veioDe && (
          <>
            <span className="text-[#D0D5DD]">·</span>
            <span className="text-[#667085]">veio de: {labelDe(veioDe)}</span>
          </>
        )}
        {trilha.length > 1 && (
          <span className="ml-auto inline-flex items-center gap-1 text-[10px] text-[#98A2B3] min-w-0 overflow-x-auto scrollbar-thin">
            {trilha.map((r, i) => (
              <span key={i} className="inline-flex items-center gap-1 shrink-0">
                {i > 0 && <ArrowRight className="size-2.5 text-[#D0D5DD]" />}
                <span className={r === activeRole ? "font-semibold text-[#475467]" : ""}>{labelDe(r)}</span>
              </span>
            ))}
          </span>
        )}
      </div>

      {/* Conversa */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto scrollbar-thin p-3 space-y-2.5 bg-[#FAFBFC]">
        {items.length === 0 && (
          <div className="h-full grid place-items-center text-center px-4">
            <div>
              <div className="size-12 rounded-2xl grid place-items-center text-white mx-auto mb-3" style={{ backgroundImage: `linear-gradient(135deg, ${c1}, ${c2})` }}>
                <FlaskConical className="size-6" />
              </div>
              <div className="text-sm font-semibold text-[#101828]">Inicie uma conversa de teste</div>
              <div className="text-xs text-[#667085] mt-1 max-w-[240px] mx-auto">
                Mande uma mensagem como um lead. O funil avança sozinho pelas etapas ({funnelPath.map((r) => ROLE_META[r]?.label).join(" → ")}) com memória contínua.
              </div>
              {welcome && (
                <div className="mt-3 text-left px-3 py-2 rounded-2xl rounded-bl-sm text-[#101828] text-xs max-w-[85%] bg-[#f1f3f5] border border-[#E6EAF0]">
                  {welcome.replace(/\{\{\s*[\w-]+\s*\}\}/g, "…")}
                </div>
              )}
            </div>
          </div>
        )}

        {items.map((it, i) => {
          if (it.kind === "transition") {
            const meta = ROLE_META[it.to];
            const TIcon = meta?.Icon ?? ArrowRight;
            return (
              <div key={i} className="flex items-center gap-2 my-2">
                <div className="h-px flex-1 bg-[#E6EAF0]" />
                <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wide px-2 py-1 rounded-full" style={{ backgroundColor: `${c1}14`, color: c1 }}>
                  <TIcon className="size-3" /> Transferido para {meta?.label ?? it.to}
                </div>
                <div className="h-px flex-1 bg-[#E6EAF0]" />
              </div>
            );
          }
          if (it.kind === "tool") {
            return (
              <div key={i} className="flex items-center gap-2 my-2">
                <div className="h-px flex-1 bg-[#E6EAF0]" />
                <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wide px-2 py-1 rounded-full bg-[#F1F5F9] text-[#475467]">
                  <Wrench className="size-3" /> Ferramenta acionada: {it.label}
                </div>
                <div className="h-px flex-1 bg-[#E6EAF0]" />
              </div>
            );
          }
          const mine = it.role === "user";
          // Lead (pergunta) — balão cinza mais escuro, à direita.
          if (mine) {
            return (
              <div key={i} className="flex justify-end">
                <div className="px-3 py-2 rounded-2xl rounded-br-sm text-sm max-w-[88%] whitespace-pre-wrap break-words bg-[#dde1e6] text-[#101828]">
                  {it.content}
                </div>
              </div>
            );
          }
          // Assistente: ainda streamando e vazio → loader.
          if (!it.content) {
            return (
              <div key={i} className="flex justify-start">
                <div className="px-3 py-2 rounded-2xl rounded-bl-sm bg-[#f1f3f5]"><Loader2 className="size-4 animate-spin text-[#98A2B3]" /></div>
              </div>
            );
          }
          // Assistente: quebra em vários balões (igual ao bot) + mídia como preview.
          const partes = quebrarMensagem(it.content);
          return (
            <div key={i} className="flex flex-col items-start gap-1.5">
              {partes.map((seg, j) => {
                const mt = ehUrl(seg) ? tipoMidia(seg) : null;
                if (mt === "image") {
                  return <div key={j} className="max-w-[78%] rounded-2xl rounded-bl-sm overflow-hidden border border-[#E6EAF0] bg-[#f1f3f5]"><img src={seg} alt="" loading="lazy" className="block max-w-full max-h-[220px] object-cover" /></div>;
                }
                if (mt === "video") {
                  return <div key={j} className="max-w-[78%] rounded-2xl rounded-bl-sm overflow-hidden border border-[#E6EAF0] bg-black"><video src={seg} controls className="block max-w-full max-h-[220px]" /></div>;
                }
                if (mt === "audio") {
                  return <div key={j} className="max-w-[88%] rounded-2xl rounded-bl-sm bg-[#f1f3f5] border border-[#E6EAF0] px-2 py-1.5"><audio src={seg} controls className="w-[230px] max-w-full" /></div>;
                }
                if (ehUrl(seg)) {
                  return <a key={j} href={seg} target="_blank" rel="noreferrer" className="max-w-[88%] px-3 py-2 rounded-2xl rounded-bl-sm text-sm bg-[#f1f3f5] text-[#2563eb] underline break-all">{seg}</a>;
                }
                return <div key={j} className="px-3 py-2 rounded-2xl rounded-bl-sm text-sm max-w-[88%] whitespace-pre-wrap break-words bg-[#f1f3f5] text-[#101828]">{seg}</div>;
              })}
            </div>
          );
        })}

        {isFinal && msgCount > 1 && !streaming && (
          <div className="flex items-center justify-center gap-1.5 text-[11px] text-[#667085] pt-2">
            <CheckCircle2 className="size-3.5" style={{ color: c1 }} /> Fim do funil — etapa final ({activeMeta?.label}).
          </div>
        )}
      </div>

      {/* Rodapé — memória + input */}
      <div className="border-t border-[#EEF1F5]">
        <div className="px-3 pt-2 flex items-center gap-1.5 text-[10px] text-[#98A2B3]">
          <BrainCircuit className="size-3" style={{ color: c1 }} />
          Memória ativa · {msgCount} mensage{msgCount === 1 ? "m" : "ns"} no contexto
        </div>
        <div className="p-3 flex gap-2">
          <Input
            placeholder="Escreva como um lead…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && (e.preventDefault(), send())}
            disabled={streaming}
            className="text-sm"
          />
          <Button size="icon" onClick={send} disabled={streaming || !input.trim()} className="shrink-0 text-white" style={{ backgroundImage: `linear-gradient(135deg, ${c1}, ${c2})` }}>
            {streaming ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
          </Button>
        </div>
      </div>
    </div>
  );
};
