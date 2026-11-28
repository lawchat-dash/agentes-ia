import { useState, useEffect, useRef } from "react";
import { lerDadosDoEscritorio } from "@/components/dashboard/DadosEscritorio";
import iconeLawChat from "@/assets/lawchat-icone.svg";
import { useParams, useNavigate, Link, useSearchParams } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowLeft, ArrowRight, Check, MessageSquare, Globe, Send, Plus, ChevronDown, Rocket, Bot, Loader2, RefreshCw, Shield, FlaskConical, FileSignature, ExternalLink, Settings2, Braces, AlertTriangle, X, Sparkles, Building2, Headphones, BellRing, History, PencilLine, Scale } from "lucide-react";
import { useTemplate } from "@/hooks/useTemplates";
import { ActivationSummary } from "@/components/agent/ActivationSummary";
import { TerminalAtivacao } from "@/components/agent/TerminalAtivacao";
import { emojiDoProduto, getCategoryIcon, resolveGradient } from "@/data/categories";
import { extractFields, extractAudios, fillField, sanitizeFieldValue, HighlightedTextarea } from "@/components/agent/HighlightedTextarea";
import { RespostaComMidia } from "@/components/agent/RespostaComMidia";
import { RevisarAtualizacao, AtualizacaoAplicada } from "@/components/agent/RevisarAtualizacao";
import { DadosEscritorioPanel } from "@/components/agent/DadosEscritorioPanel";
import zapsignLogo from "@/assets/zapsign-logo.png";
import advboxLogo from "@/assets/advbox-logo.svg";
import googleCalendarLogo from "@/assets/google-calendar.png";
import asaasLogo from "@/assets/asaas.png";
import customToolLogo from "@/assets/custom-tool-logo.svg";
import { ZapsignDialog } from "@/components/integrations/ZapsignDialog";
import { llmModels, providerColors, resolveModelId } from "@/data/llmModels";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { toast } from "sonner";
import { Slider } from "@/components/ui/slider";
import { api, enviar } from "@/api";
import { useAuth } from "@/contexts/AuthContext";
import { useQueryClient } from "@tanstack/react-query";
import { ROLE_META, ROLE_ORDER, ALL_ROLES_ORDERED, AgentRole, roleSortIndex } from "@/hooks/useProducts";
import { PipelineAgentEditor } from "@/components/agent/PipelineAgentEditor";
import { TestePrompt } from "@/components/agent/TestePrompt";

// "Testar o rascunho" escondido por enquanto (pedido do dono, 26/11). Para voltar, é só trocar para true.
const MOSTRAR_TESTE_RASCUNHO = false;
import { VersoesProduto, type ConteudoVersao } from "@/components/agent/VersoesProduto";
import ConhecimentoManager from "@/components/agent/ConhecimentoManager";
import { buildBlocksForRole } from "@/data/roleBlocks";
import { expandirBlocosParaBot, expandirHandoffsParaBot, recolherHandoffsDoBot } from "@/data/handoffTargets";
import { agentesSemFraseDeSaida, expandirFrasesParaBot, fraseDaEtapa, setProdutoFrases, temTokenTransferencia } from "@/data/frasesTroca";
import { carregarFrasesTroca, FrasesProdutoProvider } from "@/hooks/useFrasesTroca";
import { CardRoteiroAtivacao, sugestoesDeMidia, useRoteiroDoProduto } from "@/components/roteiro/RoteiroNaAtivacao";
import { AudioSlotsPanel } from "./AudioSlotsPanel";
import { listarCanaisDisponiveis, sincronizarCanaisHelena, ehWhatsapp } from "@/hooks/useChannelsSync";
import { useRascunhoLocal } from "@/hooks/useRascunhoLocal";
import { RecuperarRascunhoBanner } from "@/components/common/RecuperarRascunhoBanner";
import { Aviso } from "@/components/common/Aviso";
import { AvisoFollowupDesligado, type FollowupSituacao } from "@/components/followup/AvisoFollowupDesligado";
import { AbaFollowup, tempoLegivel } from "@/telas/AgenteFollowup";
import type { Agente } from "@/api";

// (sem dados mockados — tudo vem da API do painel: docs/API_PRODUTOS.md)

interface PipelineAgent {
  id: string | null;          // agent.id no banco (após salvar a primeira vez)
  role: AgentRole;
  name: string;
  welcome: string;
  blocks: any[];
  promptText: string | null;
  saved: boolean;
}

/** Texto do bloco freeform (prompt em texto livre) de um agente. */
const freeformOf = (blocks: any[]): string => {
  const b = Array.isArray(blocks) ? blocks.find((x) => x?.type === "freeform") : null;
  return typeof b?.content === "string" ? b.content : "";
};
/** Devolve os blocos com o conteúdo do freeform substituído (cria se não existir). */
const setFreeformIn = (blocks: any[], text: string): any[] => {
  const arr = Array.isArray(blocks) ? [...blocks] : [];
  const idx = arr.findIndex((x) => x?.type === "freeform");
  if (idx >= 0) arr[idx] = { ...arr[idx], content: text };
  else arr.unshift({ id: "freeform", type: "freeform", icon: "📝", label: "Prompt", content: text });
  return arr;
};
/** Texto efetivo do prompt de um agente (promptText canônico → fallback freeform). */
const agentPromptText = (a: PipelineAgent): string => a.promptText ?? freeformOf(a.blocks);
/** Conteúdo de um bloco por tipo (ex: handoff_trigger). */
const blockOf = (blocks: any[], type: string): string => {
  const b = Array.isArray(blocks) ? blocks.find((x) => x?.type === type) : null;
  return typeof b?.content === "string" ? b.content : "";
};
/** Mensagem PADRÃO enviada após a assinatura do contrato (passa o lead ao operacional).
 *  Obrigatória no bot: se o cliente deixar o campo vazio, gravamos este texto na tabela. */
export const MSG_POS_ASSINATURA_PADRAO =
  "Acabamos de confirmar a assinatura do seu contrato! ✅ Nosso Setor Operacional vai continuar o seu atendimento a partir de agora. Pode salvar este contato. 🙏";
/** mensagem_troca a gravar no bot (prompts.mensagem_troca desta etapa).
 *  1) FRASE PARA TRANSFERÊNCIA cadastrada pelo super admin para esta etapa (sistemaia_frases_troca): é a
 *     frase que o agente ANTERIOR fala (via @Transferência no prompt dele) e que o fluxo compara
 *     para trocar o departamento — tem que ser idêntica à expandida no prompt.
 *  2) Senão, o bloco handoff_trigger (com frases expandidas); Assinatura nunca fica vazia. */
const mensagemTrocaParaBot = (a: PipelineAgent): string | null => {
  const fixa = fraseDaEtapa(a.role);
  if (fixa) return fixa.frase;
  const txt = expandirFrasesParaBot(blockOf(a.blocks, "handoff_trigger")).trim();
  if (txt) return txt;
  return a.role === "assinatura" ? MSG_POS_ASSINATURA_PADRAO : null;
};
/** Texto do prompt que VAI para o bot (blocos, sem o handoff_trigger = frase de entrada). */
const textoDoPromptEnviado = (a: PipelineAgent): string => {
  const partes = (Array.isArray(a.blocks) ? a.blocks : [])
    .filter((b: any) => b?.type !== "handoff_trigger")
    .map((b: any) => (typeof b?.content === "string" ? b.content : Array.isArray(b?.content) ? b.content.join("\n") : ""));
  const txt = partes.join("\n");
  return txt.trim() ? txt : agentPromptText(a);
};
/** TRAVA: não salva/ativa se um agente que passa o lead adiante ficou SEM Frase para
 *  Transferência de saída no prompt (ex.: alguém apagou o chip sem querer). */
const erroSemFraseDeSaida = (agents: PipelineAgent[]): string | null => {
  const faltando = agentesSemFraseDeSaida(agents.map((a) => ({ etapa: a.role as string, prompt: textoDoPromptEnviado(a), nome: a.name })));
  if (faltando.length === 0) return null;
  return `Falta a Frase para Transferência no prompt de: ${faltando.map((f) => f.nome || f.etapa).join(", ")}. `
    + "Sem ela o agente não passa o lead adiante. Se apagou sem querer, desfaça a alteração (Ctrl+Z).";
};
/** Token "@Transferência" que ficou sem frase cadastrada (excluída / não carregou) no payload. */
const payloadComTokenSolto = (agents: any[]): boolean =>
  agents.some((ag) =>
    temTokenTransferencia(typeof ag.prompt === "string" ? ag.prompt : "")
    || temTokenTransferencia(ag.mensagem_troca ?? ""),
  );
/** Texto do prompt que o bot recebe (agentes[].prompt): os blocos expandidos (@Transferência → frase
 *  exata, @Agente X / ferramentas → "acionar tool `x`"), sem o handoff_trigger (frase de entrada),
 *  unidos por quebra de linha — o mesmo texto que o bot montava a partir dos prompt_blocks. */
const promptParaBot = (a: PipelineAgent): string => {
  const partes = (expandirBlocosParaBot(Array.isArray(a.blocks) ? a.blocks : []) as any[])
    .filter((b: any) => b?.type !== "handoff_trigger")
    .map((b: any) => (typeof b?.content === "string" ? b.content : Array.isArray(b?.content) ? b.content.join("\n") : ""));
  const txt = partes.join("\n");
  return txt.trim() ? txt : expandirHandoffsParaBot(agentPromptText(a));
};
/** Só os dígitos de um número de WhatsApp (é como numero_ia é gravado). */
const digitosNumero = (s: string | null | undefined) => String(s ?? "").replace(/\D/g, "");
/** Todo o texto de um agente onde pode haver {{ }} ou [[audio:]] (prompt canônico + bloco freeform
 *  editado + gatilho + boas-vindas). Inclui o freeform explicitamente: se promptText ficou velho
 *  vs o bloco em edição, o marcador recém-digitado ainda é varrido. */
const agentScanText = (a: PipelineAgent): string =>
  [agentPromptText(a), freeformOf(a.blocks), blockOf(a.blocks, "handoff_trigger"), a.welcome ?? ""].join("\n");
/** Substitui {{ campo }} em todo o conteúdo de um agente (prompt + gatilho + boas-vindas). */
const fillAgentField = (a: PipelineAgent, field: string, value: string): PipelineAgent => {
  const newPrompt = fillField(agentPromptText(a), field, value);
  const mapped = (Array.isArray(a.blocks) ? a.blocks : []).map((b) =>
    b?.type === "handoff_trigger" && typeof b?.content === "string"
      ? { ...b, content: fillField(b.content, field, value) }
      : b,
  );
  return { ...a, promptText: newPrompt, blocks: setFreeformIn(mapped, newPrompt), welcome: fillField(a.welcome ?? "", field, value) };
};

/** Substitui [[prefixo:nome]] (áudio/vídeo/mídia) pela URL num texto (tolerante ao escape do
 *  markdown). Resultado: o link fica inline no prompt, igual ao @ → Biblioteca (o bot envia). */
const fillAudioInText = (text: string, inner: string, url: string): string => {
  // inner = "audio:Video Inicial" (prefixo:nome). Escapa e permite espaços variados ao redor do ":".
  const esc = inner.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/:/, "\\s*:\\s*");
  const re = new RegExp(`\\\\?\\[\\\\?\\[\\s*${esc}\\s*\\\\?\\]\\\\?\\]`, "gi");
  return text.replace(re, () => url); // replacement literal ($ na URL não vira padrão especial)
};
/** Substitui [[audio:marcador]] pela URL em todo o conteúdo de um agente (prompt + gatilho + boas-vindas). */
const fillAgentAudio = (a: PipelineAgent, marker: string, url: string): PipelineAgent => {
  const newPrompt = fillAudioInText(agentPromptText(a), marker, url);
  const mapped = (Array.isArray(a.blocks) ? a.blocks : []).map((b) =>
    b?.type === "handoff_trigger" && typeof b?.content === "string"
      ? { ...b, content: fillAudioInText(b.content, marker, url) }
      : b,
  );
  return { ...a, promptText: newPrompt, blocks: setFreeformIn(mapped, newPrompt), welcome: fillAudioInText(a.welcome ?? "", marker, url) };
};

/** Converte hex (#rrggbb) para a string "H S% L%" usada na CSS var --primary. */
const hexToHsl = (hex: string): string => {
  let h = hex.replace("#", "");
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");
  const r = parseInt(h.slice(0, 2), 16) / 255;
  const g = parseInt(h.slice(2, 4), 16) / 255;
  const b = parseInt(h.slice(4, 6), 16) / 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  let hh = 0, s = 0;
  const l = (max + min) / 2;
  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    switch (max) {
      case r: hh = (g - b) / d + (g < b ? 6 : 0); break;
      case g: hh = (b - r) / d + 2; break;
      default: hh = (r - g) / d + 4;
    }
    hh /= 6;
  }
  return `${Math.round(hh * 360)} ${Math.round(s * 100)}% ${Math.round(l * 100)}%`;
};

const STEP_LABELS = ["Identidade", "Comportamento", "Conteúdo", "Integrações", "Follow-up", "Revisão"];
const STEP_COUNT = STEP_LABELS.length;
// Transição entre etapas: entra devagar (ease-out suave) e sai rápido, para o mode="wait"
// do AnimatePresence não deixar a troca de etapa arrastada.
const STEP_ENTER = { duration: 0.38, ease: [0.16, 1, 0.3, 1] as const };
const STEP_EXIT = { duration: 0.16, ease: [0.4, 0, 1, 1] as const };

// Etapas da animação de construção (otimista — o provisionamento é síncrono).
const BUILD_STEPS = [
  { label: "Criando os agentes do funil", Icon: Bot },
  { label: "Aplicando prompts e regras", Icon: Settings2 },
  { label: "Conectando o WhatsApp", Icon: MessageSquare },
  { label: "Configurando integrações", Icon: Globe },
  { label: "Finalizando o provisionamento", Icon: Rocket },
];

/** Temperatura padrão e indicada para atendimento jurídico (segue o roteiro sem soar robótica). */
const TEMPERATURA_INDICADA = 0.5;

/** Opções de "Tamanho das mensagens" (caracteres por balão). 0 = o padrão do sistema (~320). */
const TAMANHOS_MSG = [
  { valor: 160, rotulo: "Curtas", resumo: "até ~160 caracteres", baloes: 4, largura: 10 },
  { valor: 0, rotulo: "Médias", resumo: "até ~320 (padrão)", baloes: 3, largura: 16 },
  { valor: 600, rotulo: "Longas", resumo: "até ~600 caracteres", baloes: 2, largura: 26 },
  { valor: 2000, rotulo: "Uma só", resumo: "não divide", baloes: 1, largura: 46 },
];

/** Dados de um produto JÁ ativado para abrir o configurador em modo edição. */
export interface ProductConfiguratorEditData {
  /** Template-mãe (shape de useTemplate): id, name, version, category, recommended_model, slug. */
  template: any;
  groupId: string;
  weaverAgentId: string | null;
  name: string;
  numeroIa: string | null;
  /** id do canal atual (agentesia_canais.id), quando a API informa. */
  idCanal?: string | null;
  pipelineAgents: PipelineAgent[];
  faqItems: { pergunta: string; resposta: string }[];
  objectionItems: { titulo: string; resposta: string }[];
  knowledgeItems: { id: string; name: string; url: string; size: number; type: string; created_at: string }[];
  integrations: Record<string, any>;
  generalRules: string;
  dadosEscritorio?: string;
  /** Honorários (transcrição do áudio) do agente: config.conhecimento.honorarios. undefined = nunca gravado. */
  honorariosTexto?: string;
  selectedModel?: string;
  temperature?: number;
  responseDelay?: number;
  /** Tamanho das mensagens da IA (caracteres por balão; 0 = padrão). */
  charsMsg?: number;
  humanPause?: number;
  schedule24?: boolean;
  /** config COMPLETO da etapa por papel (agente_etapas.config) — base p/ regravar no bot. */
  configByRole?: Record<string, any>;
  /** Regras de handoff do CATÁLOGO por papel (com keywords) — fallback do Teste de prompt
   *  quando o config.handoff_rules do agente ativado está vazio (produtos antigos). */
  catalogHandoffByRole?: Record<string, any[]>;
  /** O produto OFERECE a etapa "Período de Graça" (flag do catálogo, definida pelo admin)?
   *  Quando true, o Período de Graça aparece como mais um agente do funil (após o SDR). */
  oferecePeriodoGraca?: boolean;
  /** O admin subiu a versão do produto no catálogo (há atualização pra revisar)? */
  atualizacaoDisponivel?: boolean;
  /** Versão atual do produto no catálogo (mostrada na revisão + gravada ao aplicar). */
  versaoCatalogo?: string | null;
  /** Voltou da lixeira: o número foi liberado. Para funcionar de novo, escolhe o número e ATIVA
   *  (mesma tela; o servidor reaproveita o agente, prompts, documentos e contrato). */
  precisaAtivar?: boolean;
  /** Número que o produto usava antes da lixeira (só informação; pode estar com outro produto). */
  numeroLiberado?: string | null;
  /** Follow-up do agente (ligado?, cadência resumida). Desligado = aviso + "Ligar com o padrão". */
  followup?: FollowupSituacao | null;
}

interface ProductConfiguratorProps {
  /** "create" = wizard de ativação (Ativar); "edit" = editar produto já ativado. */
  mode?: "create" | "edit";
  /** Dados pré-carregados (obrigatório no modo edição). */
  editData?: ProductConfiguratorEditData;
  /** Salvar no modo edição: recebe o payload montado (mesmo shape do n8n agent_product_updated). */
  onUpdate?: (payload: any) => Promise<void>;
}

export const ProductConfigurator = ({ mode = "create", editData, onUpdate }: ProductConfiguratorProps) => {
  const isEdit = mode === "edit";
  const { slug } = useParams();
  const navigate = useNavigate();
  const { workspace } = useAuth();
  const queryClient = useQueryClient();
  const { data: createTemplate, isLoading: createLoading } = useTemplate(isEdit ? undefined : slug);
  const template: any = isEdit ? editData?.template : createTemplate;
  const isLoading = isEdit ? false : createLoading;

  const [step, setStep] = useState(1);
  const [name, setName] = useState(editData?.name ?? "");
  const saveHandlerRef = useRef<(() => Promise<void> | void) | null>(null);
  // Captura leve (sem rede/toast) das edições do agente em foco — usado ao trocar
  // de seção/agente para não perder o que está sendo digitado.
  const flushHandlerRef = useRef<(() => void) | null>(null);
  const [selectedWhatsapp, setSelectedWhatsapp] = useState<string>(editData?.numeroIa ?? "");
  const selectedChannels = ["whatsapp"];
  const [schedule24, setSchedule24] = useState(editData?.schedule24 ?? true);
  const [selectedModel, setSelectedModel] = useState(resolveModelId(editData?.selectedModel));
  const [byok, setByok] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [temperature, setTemperature] = useState([editData?.temperature ?? TEMPERATURA_INDICADA]);
  const [responseDelay, setResponseDelay] = useState<number>(editData?.responseDelay ?? 10); // segundos
  const [charsMsg, setCharsMsg] = useState<number>(editData?.charsMsg ?? 0); // caracteres por mensagem (0 = padrão)
  const [humanPause, setHumanPause] = useState<number>(editData?.humanPause ?? 30); // minutos (-1 = nunca)
  const [activateNow, setActivateNow] = useState(true);
  // Etapa "Follow-up": vem LIGADO (opt-out, docs/FOLLOWUP.md); a cadência é a padrão do produto da biblioteca.
  const [followupLigado, setFollowupLigado] = useState(true);
  const [followupEdicao, setFollowupEdicao] = useState<FollowupSituacao | null>(editData?.followup ?? null);
  const [followupPopup, setFollowupPopup] = useState(false);
  // Fechou o popup do follow-up: relê a situação para o resumo e a revisão mostrarem o que ficou salvo.
  const fecharFollowupPopup = async () => {
    setFollowupPopup(false);
    const id = editData?.weaverAgentId;
    if (!id) return;
    try {
      const d = await api<{ config: { ativo: boolean; passos: { apos_horas: number }[] }; configurado?: boolean }>(`/agentes/${id}/followup`);
      setFollowupEdicao({ ligado: d.config.ativo, configurado: d.configurado ?? true, passos: d.config.passos.length,
                          resumo: d.config.passos.map((p) => tempoLegivel(p.apos_horas)) });
    } catch { /* mantém o resumo de antes */ }
  };
  const [fuPrevia, setFuPrevia] = useState<{ resumo: string[]; passos?: number[]; por_que: string; aviso_oficial: string; do_produto: boolean } | null>(null);
  // Cadência escolhida na ativação (horas de cada tentativa). null = a padrão do produto, sem mexer.
  const [fuHoras, setFuHoras] = useState<number[] | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Pipeline (step 3)
  const [groupId, setGroupId] = useState<string | null>(editData?.groupId ?? null);
  const [pipelineAgents, setPipelineAgents] = useState<PipelineAgent[]>(editData?.pipelineAgents ?? []);
  // Espelho síncrono do state: saveAllAgents roda logo após saveCurrentAgent,
  // antes do React re-renderizar, e precisa enxergar as edições mais recentes
  const pipelineAgentsRef = useRef<PipelineAgent[]>(editData?.pipelineAgents ?? []);
  useEffect(() => { pipelineAgentsRef.current = pipelineAgents; }, [pipelineAgents]);
  // Agentes "molde" do catálogo (sistemaia_biblioteca_agentes) — defaults p/ o payload
  const bibAgentsRef = useRef<any[]>([]);
  const [activeRoleIdx, setActiveRoleIdx] = useState(0);
  // Versão do editor: bump força remontar o PipelineAgentEditor após preenchimento global.
  const [editorVersion, setEditorVersion] = useState(0);
  const [globalDraft, setGlobalDraft] = useState<Record<string, string>>({});
  // Valores já aplicados pela Edição rápida — usados para (a) realçar em roxo nos
  // prompts e (b) saber que o usuário concluiu (tela de sucesso).
  const [appliedValues, setAppliedValues] = useState<string[]>([]);
  // Mapa campo→valor das variáveis {{ }} preenchidas (vai no payload do webhook).
  const [fieldValues, setFieldValues] = useState<Record<string, string>>({});
  // Etapa da animação de construção (0..N) durante a ativação.
  const [buildStage, setBuildStage] = useState(0);
  const [terminalAtivacao, setTerminalAtivacao] = useState(false);
  // Quando a ativação falha/expira, guarda a mensagem — o overlay vira tela de ERRO
  // (não volta pro wizard) e o produto fica salvo como falhou/rascunho com as edições.
  const [buildError, setBuildError] = useState<string | null>(null);
  // Carimbo do catálogo (max updated_at de produto+agentes) — detecta rascunho obsoleto.
  const catalogStampRef = useRef<string | null>(null);
  // Papéis que o usuário REALMENTE personalizou — o editor compara o conteúdo atual com
  // o original e avisa. cinza = padrão do catálogo · cor = personalizado.
  const [customizedRoles, setCustomizedRoles] = useState<Set<string>>(new Set());
  // Atualização do catálogo (admin subiu a versão): banner + modal "revisar e escolher".
  const [revisarOpen, setRevisarOpen] = useState(false);
  const [updateRevisado, setUpdateRevisado] = useState(false); // aplicou/revisou → grava versão no save
  const [savingAgent, setSavingAgent] = useState(false);
  const [bootstrapping, setBootstrapping] = useState(false);
  // Onde a pessoa parou no rascunho do servidor (passo): usado ao retomar com ?continuar=1.
  const passoSalvo = useRef<number | null>(null);
  // Pergunta "Áudio de objeções não encontrado" antes de ativar/salvar (ver pedirAtivar).
  const [perguntaObjecoes, setPerguntaObjecoes] = useState(false);
  const objecoesEmTextoOk = useRef(false);
  const depoisDaPergunta = useRef<() => void>(() => {});
  type Step3Tab = "campos" | "regras" | "agente" | "faq" | "objecoes" | "dados_escritorio" | "honorarios" | "conhecimento" | "integracoes" | "audios";
  const [step3Tab, setStep3Tab] = useState<Step3Tab>("agente");
  const [generalRules, setGeneralRules] = useState<string>(editData?.generalRules ?? "");
  const [testOpen, setTestOpen] = useState(false);
  // Modo edição: aba "Versões" (lista, diferenças, restaurar no rascunho) ao lado do editor.
  const [aba, setAba] = useState<"editar" | "versoes">("editar");
  const [versaoRestaurada, setVersaoRestaurada] = useState<number | null>(null);

  // config completo da etapa por papel (modo edição) — base para regravar no bot via 0021.
  const configByRoleRef = useRef<Record<string, any>>(editData?.configByRole ?? {});

  // Tab data (product-level, shared across agents)
  const [faqItems, setFaqItems] = useState<{ pergunta: string; resposta: string }[]>(editData?.faqItems ?? []);
  const [objectionItems, setObjectionItems] = useState<{ titulo: string; resposta: string }[]>(editData?.objectionItems ?? []);
  const [dadosEscritorio, setDadosEscritorio] = useState<string>(editData?.dadosEscritorio ?? ""); // prompt nível produto
  // Honorários do produto (transcrição do áudio, com {{campos}}): entra no Closer, Contratos e Assinatura.
  const [honorariosTexto, setHonorariosTexto] = useState<string>(editData?.honorariosTexto ?? "");
  const [knowledgeItems, setKnowledgeItems] = useState<{ id: string; name: string; url: string; size: number; type: string; created_at: string }[]>(editData?.knowledgeItems ?? []);
  const [integrations, setIntegrations] = useState<Record<string, any>>(editData?.integrations ?? {});

  // Variante de MÍDIA: quando o produto é modo áudio, a pessoa escolhe o áudio de cada
  // [[audio:marcador]] e o marcador vira o LINK inline no prompt (igual @ → Biblioteca).
  const isAudio = (template as any)?.modo_midia === "audio";
  const [zapsignOpen, setZapsignOpen] = useState(false);
  const [savingTab, setSavingTab] = useState(false);
  const [uploadingKnowledge, setUploadingKnowledge] = useState(false);
  // Modo edição: troca de número só após o usuário pedir "Alterar número".
  // Produto que voltou da lixeira (sem número): a escolha do número já começa aberta.
  const reativando = isEdit && !!editData?.precisaAtivar;
  const [changingNumber, setChangingNumber] = useState(reativando);

  // Salva o estado completo do wizard no rascunho (sistemaia_produtos_ativados).
  // Preserva tudo caso o usuário volte/atualize.
  const salvarRascunho = async (extra: Record<string, any> = {}) => {
    if (!groupId) return;
    // EDIÇÃO de produto já ativo: NÃO grava nas colunas do produto antes do "Salvar alterações".
    // Gravar aqui deixava o app diferente do bot (ex.: numero_ia novo no app e o agente no número
    // antigo). Enquanto não salva, o que foi editado fica protegido no rascunho LOCAL.
    if (isEdit) { rascunhoLocal.gravarAgora(); return; }
    const rascunho = {
      name, selectedWhatsapp, selectedModel, temperature, responseDelay, humanPause, schedule24,
      pipelineAgents: pipelineAgentsRef.current,
      faqItems, objectionItems, knowledgeItems, integrations, generalRules, dadosEscritorio, honorariosTexto,
      catalogStamp: catalogStampRef.current, // carimbo do catálogo no momento do salvamento
      // Onde a pessoa parou (passo, aba do conteúdo, agente) e os campos já aplicados: ao reabrir o rascunho em
      // Produtos ela continua dali, sem refazer nada.
      step, step3Tab, activeRoleIdx, fieldValues, appliedValues,
      // Follow-up e "ativar agora" (passos 5 e 6): a retomada volta com o que a pessoa escolheu.
      followupLigado, fuHoras, activateNow,
      ...extra,
    };
    try {
      await enviar(`/produtos-ativados/${groupId}`, {
        nome: name || template.name,
        regras_markdown: generalRules || null,
        faq: faqItems, objecoes: objectionItems, conhecimento: knowledgeItems,
        dados_escritorio: dadosEscritorio || null,
        integracoes: integrations, numero_ia: selectedWhatsapp || null,
        rascunho,
      }, "PATCH");
      // Salvo no servidor: o rascunho local não tem mais nada a recuperar (evita oferecer uma versão mais velha).
      rascunhoLocal.limpar();
    } catch (e: any) {
      console.warn("[rascunho] falha ao salvar", e?.message);
    }
  };

  // Aplica a atualização do catálogo escolhida pelo cliente (só ADICIONA/substitui o marcado —
  // não mexe no resto). Marca updateRevisado → o save grava a versão nova (some a badge).
  const aplicarAtualizacao = (sel: AtualizacaoAplicada) => {
    const nt = (s: string) => String(s ?? "").trim();
    if (sel.objecoesNovas.length) setObjectionItems((prev) => [...prev, ...sel.objecoesNovas]);
    if (sel.objecoesAtualizadas.length) setObjectionItems((prev) => prev.map((it) => {
      const u = sel.objecoesAtualizadas.find((o) => nt(o.titulo) === nt(it.titulo));
      return u ? { ...it, resposta: u.resposta } : it;
    }));
    if (sel.faqNovas.length) setFaqItems((prev) => [...prev, ...sel.faqNovas]);
    if (sel.faqAtualizadas.length) setFaqItems((prev) => prev.map((it) => {
      const u = sel.faqAtualizadas.find((f) => nt(f.pergunta) === nt(it.pergunta));
      return u ? { ...it, resposta: u.resposta } : it;
    }));
    if (typeof sel.regras === "string") setGeneralRules(sel.regras);
    if (typeof sel.dados === "string") setDadosEscritorio(sel.dados);
    setUpdateRevisado(true);
    setTimeout(() => void salvarRascunho(), 0);
  };

  // Compat: as abas chamam persistGroupField(patch, label). No modelo novo o
  // estado já está no React; só persistimos o rascunho.
  const persistGroupField = async (_patch: Record<string, any>, label: string) => {
    if (!groupId) return;
    setSavingTab(true);
    await salvarRascunho();
    setSavingTab(false);
    if (isEdit) toast.success(`${label} guardado`, { description: "Clique em Salvar alterações para aplicar no agente." });
    else toast.success(`${label} salvo`);
  };

  const initializedTemplateId = useRef<string | null>(null);
  useEffect(() => {
    if (template && initializedTemplateId.current !== template.id) {
      initializedTemplateId.current = template.id;
      document.title = isEdit ? `Editar ${template.name} — LawChat IA` : `Ativar ${template.name} — LawChat IA`;
      // No modo edição o modelo vem do editData; não sobrescrever com o padrão do template.
      if (!isEdit) setSelectedModel(resolveModelId(template.recommended_model));
    }
  }, [template, isEdit]);

  // Guard: produto "em breve" não pode ser ativado (proteção contra URL direta — o catálogo já
  // mostra em breve). SÓ no modo CRIAR. Aqui não há planos: nenhum produto fica bloqueado por plano.
  const comingSoon = !isEdit && template?.status === "em_breve";
  // Roteiro de gravação do produto (produtos de mídia): card da lateral e gravações que combinam com os marcadores.
  const roteiro = useRoteiroDoProduto(template?.id, isAudio && step >= 3);

  // Retomar o rascunho: se o escritório já tem um rascunho deste produto com conteúdo (Meus agentes › Rascunho, a volta do
  // Roteiro de gravação, ou abrir o produto de novo pela Biblioteca), carrega na hora e abre no passo onde a pessoa parou
  // (pelo menos o Conteúdo), sem refazer Identidade e Comportamento. Não depende só do ?continuar=1 do endereço: depois de
  // recarregar a página o componente pode montar de novo, e o rascunho continua sendo a fonte de onde parou.
  const [busca, setBusca] = useSearchParams();
  const retomou = useRef(false);
  useEffect(() => {
    if (isEdit || retomou.current || !template?.id || groupId || bootstrapping) return;
    retomou.current = true;
    const pediu = !!busca.get("continuar");
    void (async () => {
      let temRascunho = pediu;
      if (!temRascunho) {
        try {
          const meus = await api<any[]>("/produtos-ativados?lixeira=0");
          temRascunho = (meus ?? []).some((p) => p.id_produto_biblioteca === template.id && p.status === "rascunho"
            && Array.isArray(p.rascunho?.pipelineAgents) && p.rascunho.pipelineAgents.length > 0);
        } catch { /* sem a lista: começa do passo 1, como antes */ }
      }
      if (!temRascunho) return;
      if (!(await bootstrapPipeline())) return;
      setStep(Math.max(3, passoSalvo.current ?? 3));
      if (pediu) {
        const sem = new URLSearchParams(busca);
        sem.delete("continuar");
        setBusca(sem, { replace: true });
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [template?.id, isEdit, groupId]);
  // Trocou de passo depois do Conteúdo (Integrações, Follow-up, Revisão): guarda a posição no rascunho, para quem sair e
  // voltar cair no mesmo passo (só mexer no conteúdo é que salvava antes).
  useEffect(() => {
    if (isEdit || !groupId || bootstrapping || step < 3) return;
    void salvarRascunho();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step]);
  useEffect(() => {
    if (!template?.id) return;
    let vivo = true;
    api<{ resumo: string[]; passos?: number[]; por_que: string; aviso_oficial: string; do_produto: boolean }>(`/biblioteca/produtos/${template.id}/followup-padrao`)
      .then((r) => { if (vivo) setFuPrevia(r); }).catch(() => { /* sem prévia: a etapa mostra só o interruptor */ });
    return () => { vivo = false; };
  }, [template?.id]);
  useEffect(() => {
    if (!template) return;
    if (comingSoon) {
      toast.error("Este produto ainda está em breve", { id: "ativar-em-breve", description: "Em breve você poderá ativá-lo." });
      navigate(`/biblioteca/${template.slug}`, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [comingSoon, template, navigate]);

  // WhatsApp sync state
  const [waNumbers, setWaNumbers] = useState<{ id: string; label: string; tag: string; status: "ativo" | "inativo"; canalId?: string }[]>([]);
  const [syncingWa, setSyncingWa] = useState(false);
  // Erro/aviso da sincronização: `title`/`detail` são para o cliente (linguagem simples);
  // `tecnico` guarda a mensagem crua (só aparece recolhida, para o suporte).
  const [waSyncError, setWaSyncError] = useState<{
    tipo: "erro" | "atencao";
    title: string;
    detail?: string;
    tecnico?: string;
  } | null>(null);
  const syncWhatsapp = async () => {
    setSyncingWa(true);
    setWaSyncError(null);
    try {
      if (!workspace?.id) throw new Error("Sem conta ativa");
      // Atualiza os canais a partir da LawChat (token do escritório) e lista os números.
      const data = await sincronizarCanaisHelena();

      const normalized = ((data ?? []) as any[])
        // Só canais WhatsApp (CLOUDAPI/ZAPI) — Instagram/Messenger NÃO valem como número da IA.
        .filter(ehWhatsapp)
        .map((n: any) => {
          const id = digitosNumero(n.numero) || String(n.numero ?? "").trim();
          if (!id) return null;
          // Número atual DESTE agente (edição) não é "de outro agente": pode continuar selecionado.
          const doProprio = isEdit && (
            (n.em_uso_por != null && String(n.em_uso_por) === String(editData?.weaverAgentId ?? ""))
            || (!!editData?.idCanal && String(n.id) === String(editData.idCanal))
            || (!!editData?.numeroIa && digitosNumero(editData.numeroIa) === id)
          );
          const status: "ativo" | "inativo" = n.disponivel || doProprio ? "ativo" : "inativo";
          return {
            id,
            label: n.numero_formatado || id,
            tag: doProprio ? "Número atual deste agente" : n.disponivel ? (n.nome || "Disponível") : "Em uso por outro agente",
            status,
            canalId: n.id,
          };
        })
        .filter(Boolean) as { id: string; label: string; tag: string; status: "ativo" | "inativo"; canalId?: string }[];

      setWaNumbers(normalized);
      // Na edição NÃO pré-seleciona: o canal só muda quando o usuário escolhe outro número.
      const firstActive = normalized.find((n) => n.status === "ativo");
      if (firstActive && !isEdit) setSelectedWhatsapp(firstActive.id);

      if (normalized.length === 0) {
        setWaSyncError({
          tipo: "atencao",
          title: "Nenhum número de WhatsApp encontrado",
          detail: "Não achamos nenhum número de WhatsApp conectado à sua conta. Confira se o número está conectado na LawChat e tente de novo.",
        });
        toast.warning("Nenhum número encontrado", { id: "ativar-sync-whatsapp" });
      } else {
        toast.success(`${normalized.length} número(s) sincronizado(s)`, { id: "ativar-sync-whatsapp" });
      }
    } catch (e: any) {
      setWaNumbers([]);
      const tecnico = [e?.status && `HTTP ${e.status}`, e?.message ?? String(e)].filter(Boolean).join(" · ");
      setWaSyncError({
        tipo: "erro",
        title: "Não conseguimos buscar seus números agora",
        detail: "Pode ser uma instabilidade momentânea na conexão com o WhatsApp. Tente de novo em alguns segundos — se continuar, fale com o suporte.",
        tecnico,
      });
      toast.error("Não conseguimos buscar seus números", { id: "ativar-sync-whatsapp", description: "Tente sincronizar de novo em alguns segundos." });
    } finally {
      setSyncingWa(false);
    }
  };

  // Voltou da lixeira: já busca os números (o anterior pode estar com outro produto).
  useEffect(() => {
    if (reativando) syncWhatsapp();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }, [slug, step]);

  // Avança a animação pelos passos de DISPARO (rápidos) e segura no último — que é o
  // de "aguardando o servidor", onde o overlay mostra o tempo real decorrido.
  useEffect(() => {
    if (!submitting) { setBuildStage(0); return; }
    setBuildStage(0);
    const iv = setInterval(() => setBuildStage((s) => Math.min(s + 1, BUILD_STEPS.length - 1)), 1300);
    return () => clearInterval(iv);
  }, [submitting]);

  // Marca se o componente ainda está montado — o polling de provisionamento (até 5 min)
  // roda fora de efeito, então checamos isto antes de continuar/navegar para não mexer
  // num componente desmontado se o usuário sair do wizard no meio.
  const mountedRef = useRef(true);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  // ---------------------------------------------------------------------------------------
  // RASCUNHO LOCAL (rede de segurança): copia o estado do wizard p/ o navegador a cada 3s e
  // quando a aba fica oculta/fecha. Se a página recarregar (aba descartada pelo Chrome, queda
  // de sessão, recarga do servidor de dev), ao reabrir oferecemos "Recuperar alterações".
  // Inclui o texto que está sendo DIGITADO no agente em foco (snapshotHandlerRef), que ainda
  // não foi capturado em pipelineAgents.
  // ---------------------------------------------------------------------------------------
  const snapshotHandlerRef = useRef<(() => { role: AgentRole; name: string; welcome: string; blocks: any[] }) | null>(null);
  const obterRascunhoLocal = () => {
    const snap = snapshotHandlerRef.current?.() ?? null;
    const agentes = snap
      ? pipelineAgentsRef.current.map((a) => (a.role === snap.role
        ? { ...a, name: snap.name, welcome: snap.welcome, blocks: snap.blocks, promptText: freeformOf(snap.blocks) }
        : a))
      : pipelineAgentsRef.current;
    return {
      name, selectedWhatsapp, selectedModel, temperature, responseDelay, humanPause, schedule24,
      pipelineAgents: agentes, faqItems, objectionItems, knowledgeItems, integrations,
      generalRules, dadosEscritorio, honorariosTexto, fieldValues, appliedValues,
      followupLigado, fuHoras, activateNow,
      // posição na tela (não conta como alteração)
      step, step3Tab, activeRoleIdx,
    };
  };
  type RascunhoWizard = ReturnType<typeof obterRascunhoLocal>;
  const rascunhoLocal = useRascunhoLocal<RascunhoWizard>({
    chave: isEdit
      ? (editData?.groupId ? `produto:${editData.groupId}` : null)
      // Uma chave por ATIVAÇÃO (o rascunho do servidor, groupId): antes era por produto, e o rascunho local de uma
      // ativação antiga aparecia como "alterações não salvas" numa nova e, recuperado, trocava o trabalho atual.
      : (workspace?.id && template?.id && groupId ? `ativar:${workspace.id}:${template.id}:${groupId}` : null),
    // Edição: o estado inicial já vem do servidor. Ativação: só depois do bootstrap do rascunho.
    habilitado: isEdit ? !!editData : !!groupId && !bootstrapping,
    obter: obterRascunhoLocal,
    conteudo: (d) => ({
      ...d, step: undefined, step3Tab: undefined, activeRoleIdx: undefined,
      pipelineAgents: (d.pipelineAgents ?? []).map((a: any) => ({
        role: a.role,
        name: String(a.name ?? "").trim(),
        welcome: String(a.welcome ?? "").trim(),
        prompt: String(a.promptText ?? freeformOf(a.blocks) ?? "").trim(),
        handoff: blockOf(a.blocks, "handoff_trigger").trim(),
      })),
    }),
  });
  const aplicarRascunhoLocal = () => {
    const d = rascunhoLocal.recuperar();
    if (!d) return;
    if (typeof d.name === "string") setName(d.name);
    if (typeof d.selectedWhatsapp === "string") {
      setSelectedWhatsapp(d.selectedWhatsapp);
      if (isEdit && d.selectedWhatsapp && d.selectedWhatsapp !== (editData?.numeroIa ?? "")) setChangingNumber(true);
    }
    if (d.selectedModel) setSelectedModel(resolveModelId(d.selectedModel));
    if (Array.isArray(d.temperature)) setTemperature(d.temperature);
    if (typeof d.responseDelay === "number") setResponseDelay(d.responseDelay);
    if (typeof d.humanPause === "number") setHumanPause(d.humanPause);
    if (typeof d.schedule24 === "boolean") setSchedule24(d.schedule24);
    if (Array.isArray(d.pipelineAgents) && d.pipelineAgents.length) {
      pipelineAgentsRef.current = d.pipelineAgents;
      setPipelineAgents(d.pipelineAgents);
    }
    if (Array.isArray(d.faqItems)) setFaqItems(d.faqItems);
    if (Array.isArray(d.objectionItems)) setObjectionItems(d.objectionItems);
    if (Array.isArray(d.knowledgeItems)) setKnowledgeItems(d.knowledgeItems);
    if (d.integrations) setIntegrations(d.integrations);
    if (typeof d.generalRules === "string") setGeneralRules(d.generalRules);
    if (typeof d.dadosEscritorio === "string") setDadosEscritorio(d.dadosEscritorio);
    if (typeof d.honorariosTexto === "string") setHonorariosTexto(d.honorariosTexto);
    if (d.fieldValues) setFieldValues(d.fieldValues);
    if (Array.isArray(d.appliedValues)) setAppliedValues(d.appliedValues);
    if (typeof d.followupLigado === "boolean") setFollowupLigado(d.followupLigado);
    if (d.fuHoras === null || Array.isArray(d.fuHoras)) setFuHoras(d.fuHoras);
    if (typeof d.activateNow === "boolean") setActivateNow(d.activateNow);
    if (typeof d.step === "number") setStep(Math.min(STEP_COUNT, Math.max(1, d.step)));
    if (d.step3Tab) setStep3Tab(d.step3Tab);
    const nAg = Array.isArray(d.pipelineAgents) ? d.pipelineAgents.length : pipelineAgentsRef.current.length;
    if (typeof d.activeRoleIdx === "number") setActiveRoleIdx(Math.min(Math.max(0, d.activeRoleIdx), Math.max(0, nAg - 1)));
    setEditorVersion((v) => v + 1); // remonta o editor do agente com o texto recuperado
    toast.success("Alterações recuperadas", { description: "Revise e salve para não perder de novo." });
  };

  // Salvar o rascunho DEPOIS que as trocas entram no estado: quem troca textos com setState funcional
  // (mídias, campos {{ }}) pede aqui em vez de chamar salvarRascunho() na hora — na hora ele leria o
  // estado velho do closure e gravaria o texto de antes. O efeito roda com o estado novo, uma vez só.
  const [pedidoSalvar, setPedidoSalvar] = useState(0);
  useEffect(() => {
    if (pedidoSalvar) void salvarRascunho();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pedidoSalvar]);

  if (isLoading) return <div className="grid place-items-center py-20"><Loader2 className="size-8 text-primary animate-spin" /></div>;
  if (!template) {
    return (
      <div className="p-8 text-center">
        <p>Produto não encontrado.</p>
        <Button asChild className="mt-4"><Link to="/biblioteca">Voltar</Link></Button>
      </div>
    );
  }

  /** Carrega os 5 agentes do catálogo novo (sistemaia_biblioteca_agentes) e
   *  cria/restaura o rascunho em sistemaia_produtos_ativados. Sem agent_groups/agents. */
  const bootstrapPipeline = async (): Promise<boolean> => {
    if (!workspace) {
      toast.error("Conta não carregada", { id: "ativar-conta", description: "Recarregue a página e tente novamente." });
      return false;
    }
    if (groupId) return true; // já carregado numa passagem anterior
    setBootstrapping(true);
    try {
      // 1) Agentes-molde do produto (catálogo)
      const bibAgents = ((await api<any[]>(`/biblioteca/produtos/${template.id}/agentes`)) ?? [])
        .slice().sort((a: any, b: any) => (a.ordem ?? 0) - (b.ordem ?? 0));
      if (!bibAgents?.length) throw new Error("Este produto ainda não tem agentes configurados no catálogo.");
      bibAgentsRef.current = bibAgents;

      // 1b) Padrões de conteúdo do catálogo (FAQ/objeções/regras definidos no admin) —
      // semeiam o rascunho do cliente para ele já começar com algo preenchido.
      const catDefaults: any = await api<any>(`/biblioteca/produtos/${template.id}`).catch(() => null);
      const defFaq = Array.isArray(catDefaults?.faq) ? catDefaults.faq : [];
      const defObj = Array.isArray(catDefaults?.objecoes) ? catDefaults.objecoes : [];
      const defRegras = (catDefaults?.regras_markdown as string) ?? "";
      const defDados = (catDefaults?.dados_escritorio as string) ?? "";
      const defHonorarios = typeof catDefaults?.config_modelo?.honorarios_texto === "string" ? catDefaults.config_modelo.honorarios_texto : "";
      // Carimbo do catálogo = a edição mais recente entre o produto e seus agentes.
      // Se o rascunho guardou um carimbo mais antigo, o modelo mudou → recarregar do catálogo.
      const catalogStamp = [catDefaults?.updated_at, ...bibAgents.map((b: any) => b.updated_at)]
        .filter(Boolean).sort().pop() ?? null;
      catalogStampRef.current = catalogStamp;

      // Follow-up e "ativar agora" são ESCOLHAS da pessoa (não conteúdo): voltam nos dois casos.
      const restaurarEscolhasFinais = (r: any) => {
        if (typeof r.followupLigado === "boolean") setFollowupLigado(r.followupLigado);
        if (r.fuHoras === null || Array.isArray(r.fuHoras)) setFuHoras(r.fuHoras);
        if (typeof r.activateNow === "boolean") setActivateNow(r.activateNow);
      };

      // Reconstrói os agentes a partir do MODELO do catálogo (a fonte da verdade).
      const montarAgentesDoCatalogo = (): PipelineAgent[] => {
        // ALL_ROLES_ORDERED inclui 'periododegraca' (após o SDR). Só existe no catálogo
        // dos produtos que oferecem — nos demais o find retorna undefined e é filtrado.
        const ordered = ALL_ROLES_ORDERED.map((role) => bibAgents.find((b: any) => b.papel === role)).filter(Boolean);
        const base = ordered.length ? ordered : bibAgents;
        return base.map((b: any) => ({
          id: b.papel,
          role: b.papel as AgentRole,
          name: b.nome_exibicao ?? ROLE_META[b.papel as AgentRole]?.label ?? b.papel,
          welcome: b.mensagem_boas_vindas ?? "",
          blocks: Array.isArray(b.blocos_prompt) ? b.blocos_prompt : buildBlocksForRole(b.papel, [], b.texto_prompt),
          promptText: b.texto_prompt ?? null,
          saved: true,
        }));
      };

      // 2) Busca rascunho existente ou cria um novo (o servidor já copia os padrões do catálogo)
      const draft: any = await enviar(`/produtos-ativados/rascunho`, { id_produto_biblioteca: template.id, nome: name?.trim() || undefined, numero_ia: selectedWhatsapp || undefined });
      if (!draft?.id) throw new Error("Não foi possível criar o rascunho do produto.");

      // 3) Restaura o rascunho SÓ se existir E o catálogo NÃO tiver mudado desde então.
      //    Se o modelo do catálogo foi atualizado (carimbo mais novo), recarrega o
      //    conteúdo do catálogo (prompts/FAQ/objeções/regras) — o modelo é a fonte da
      //    verdade — preservando as escolhas do usuário (nome, número, modelo, comportamento).
      const r = (draft.rascunho ?? {}) as any;
      const hadDraft = Array.isArray(r.pipelineAgents) && r.pipelineAgents.length > 0;
      const draftStale = !!catalogStamp && (!r.catalogStamp || r.catalogStamp < catalogStamp);

      if (hadDraft && !draftStale) {
        setPipelineAgents(r.pipelineAgents);
        pipelineAgentsRef.current = r.pipelineAgents;
        if (r.name) setName(r.name);
        if (Array.isArray(r.faqItems)) setFaqItems(r.faqItems);
        if (Array.isArray(r.objectionItems)) setObjectionItems(r.objectionItems);
        if (typeof r.dadosEscritorio === "string") setDadosEscritorio(r.dadosEscritorio);
        setHonorariosTexto(typeof r.honorariosTexto === "string" ? r.honorariosTexto : defHonorarios);
        if (Array.isArray(r.knowledgeItems)) setKnowledgeItems(r.knowledgeItems);
        if (r.integrations) setIntegrations(r.integrations);
        if (typeof r.generalRules === "string") setGeneralRules(r.generalRules);
        if (r.selectedWhatsapp) setSelectedWhatsapp(r.selectedWhatsapp);
        if (r.selectedModel) setSelectedModel(resolveModelId(r.selectedModel));
        if (Array.isArray(r.temperature)) setTemperature(r.temperature);
        if (typeof r.responseDelay === "number") setResponseDelay(r.responseDelay);
        if (typeof r.humanPause === "number") setHumanPause(r.humanPause);
        if (typeof r.schedule24 === "boolean") setSchedule24(r.schedule24);
        if (r.fieldValues && typeof r.fieldValues === "object") setFieldValues(r.fieldValues);
        if (Array.isArray(r.appliedValues)) setAppliedValues(r.appliedValues);
        restaurarEscolhasFinais(r);
        // Continua de onde parou.
        passoSalvo.current = typeof r.step === "number" ? Math.min(STEP_COUNT, Math.max(1, r.step)) : null;
        if (r.step3Tab) setStep3Tab(r.step3Tab);
        if (typeof r.activeRoleIdx === "number") setActiveRoleIdx(Math.min(Math.max(0, r.activeRoleIdx), Math.max(0, r.pipelineAgents.length - 1)));
      } else {
        // Conteúdo SEMPRE do catálogo (modelo manda).
        const pa = montarAgentesDoCatalogo();
        setPipelineAgents(pa);
        pipelineAgentsRef.current = pa;
        setGeneralRules(defRegras || (draft.regras_markdown as string) || "");
        setFaqItems(defFaq.length ? defFaq : (Array.isArray(draft.faq) ? draft.faq : []));
        setObjectionItems(defObj.length ? defObj : (Array.isArray(draft.objecoes) ? draft.objecoes : []));
        setDadosEscritorio(defDados || (typeof draft.dados_escritorio === "string" ? draft.dados_escritorio : ""));
        setHonorariosTexto(defHonorarios);
        setKnowledgeItems(Array.isArray(draft.conhecimento) ? draft.conhecimento : []);
        setIntegrations(draft.integracoes ?? {});
        // Preserva as ESCOLHAS do usuário (não-conteúdo). Cai pras COLUNAS do produto (nome/número)
        // quando o jsonb do rascunho não as tem — ex. rascunho retomado após cancelar a ativação.
        if (r.name) setName(r.name); else if (draft.nome) setName(draft.nome);
        if (r.selectedWhatsapp) setSelectedWhatsapp(r.selectedWhatsapp); else if (draft.numero_ia) setSelectedWhatsapp(draft.numero_ia);
        if (r.selectedModel) setSelectedModel(resolveModelId(r.selectedModel));
        if (Array.isArray(r.temperature)) setTemperature(r.temperature);
        if (typeof r.responseDelay === "number") setResponseDelay(r.responseDelay);
        if (typeof r.humanPause === "number") setHumanPause(r.humanPause);
        if (typeof r.schedule24 === "boolean") setSchedule24(r.schedule24);
        restaurarEscolhasFinais(r);
        if (hadDraft && draftStale) {
          toast.info("O modelo do catálogo foi atualizado", { description: "Recarregamos os prompts e o conteúdo padrão." });
        }
      }

      setGroupId(draft.id);
      // Dados do escritório (Ajustes › Dados do escritório): preenchem sozinhos os {{...}} que pedem a mesma coisa,
      // em todo o produto, para a pessoa não digitar de novo. Só os campos que aparecem no texto; falha = segue sem.
      if (!isEdit) {
        const dadosEsc = await lerDadosDoEscritorio();
        if (dadosEsc) {
          const textoTodo = JSON.stringify([pipelineAgentsRef.current, r, draft, defRegras, defDados, defHonorarios, defFaq, defObj]);
          const pede = (nome: string) => new RegExp("\\{\\{\\s*" + nome.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\s*\\}\\}").test(textoTodo);
          for (const campo of dadosEsc.campos) {
            const valor = (dadosEsc.valores[campo.chave] ?? "").trim();
            if (!valor) continue;
            for (const nome of campo.preenche) if (pede(nome)) applyGlobalField(nome, valor);
          }
        }
      }
      return true;
    } catch (e: any) {
      toast.error("Erro ao preparar pipeline", { id: "ativar-pipeline", description: e.message });
      return false;
    } finally {
      setBootstrapping(false);
    }
  };

  const saveCurrentAgent = async (payload: { name: string; welcome: string; blocks: any[] }) => {
    const cur = pipelineAgentsRef.current[activeRoleIdx];
    if (!cur?.id) return;
    // Atualiza o espelho síncrono antes do await: saveAllAgents lê daqui
    const updated = pipelineAgentsRef.current.map((a, i) =>
      i === activeRoleIdx ? { ...a, name: payload.name, welcome: payload.welcome, blocks: payload.blocks, promptText: freeformOf(payload.blocks) } : a
    );
    const marcado = updated.map((a, i) => (i === activeRoleIdx ? { ...a, saved: true } : a));
    pipelineAgentsRef.current = marcado;
    setPipelineAgents(marcado);
    setSavingAgent(true);
    try {
      await salvarRascunho();
      if (isEdit) toast.success(`${ROLE_META[cur.role].label} guardado`, { description: "Clique em Salvar alterações para aplicar no agente." });
      else toast.success(`${ROLE_META[cur.role].label} salvo`);
    } catch (e: any) {
      toast.error("Erro ao salvar", { description: e.message });
      throw e;
    } finally {
      setSavingAgent(false);
    }
  };

  /** Salva o agente atual (capturando o form em edição) + todos os demais de uma vez. */
  const saveAllAgents = async (): Promise<boolean> => {
    setSavingAgent(true);
    try {
      // 1) Captura edições do agente em foco SÓ se o editor está montado (aba "agente").
      //    Em outra aba o handler está obsoleto e reverteria a Edição rápida.
      if (step3Tab === "agente" && saveHandlerRef.current) {
        try { await saveHandlerRef.current(); } catch { /* re-persiste no lote abaixo */ }
      }
      // 2) Persiste o rascunho completo (estado local — sem agent_groups/agents)
      const marcado = pipelineAgentsRef.current.map((a) => ({ ...a, saved: true }));
      pipelineAgentsRef.current = marcado;
      setPipelineAgents(marcado);
      await salvarRascunho();
      // Edição: nada foi aplicado no bot ainda (só no "Salvar alterações" do fim).
      if (!isEdit) toast.success("Todos os agentes foram salvos");
      return true;
    } catch (e: any) {
      toast.error("Erro ao salvar agentes", { description: e.message });
      return false;
    } finally {
      setSavingAgent(false);
    }
  };


  /** Salva o estado em edição do agente em foco no estado local (sem rede/toast). */
  const captureAgentEdits = (payload: { name: string; welcome: string; blocks: any[] }) => {
    const updated = pipelineAgentsRef.current.map((a, i) =>
      i === activeRoleIdx ? { ...a, name: payload.name, welcome: payload.welcome, blocks: payload.blocks, promptText: freeformOf(payload.blocks) } : a
    );
    pipelineAgentsRef.current = updated;
    setPipelineAgents(updated);
  };

  /** Navega entre seções do passo 3 preservando edições e salvando o rascunho em silêncio. */
  const goToSection = (next: Step3Tab, roleIdx?: number) => {
    // Captura o agente em edição SÓ se o editor estava montado (aba "agente").
    // Em outras abas o handler está obsoleto e reverteria mudanças da Edição rápida.
    if (step3Tab === "agente") flushHandlerRef.current?.();
    if (typeof roleIdx === "number") setActiveRoleIdx(roleIdx);
    setStep3Tab(next);
    // persiste o rascunho sem toast (autosave)
    void salvarRascunho();
  };

  // Campos {{ }} de TODO o produto (regras + 5 agentes + FAQ + objeções),
  // guardando ONDE cada um aparece para mostrar na UI.
  // Computação direta (NÃO useMemo): este componente tem returns antecipados acima
  // (isLoading/!template); um hook aqui seria condicional e quebraria a ordem de hooks.
  const productFields = (() => {
    const map = new Map<string, Set<string>>();
    const add = (txt: string, loc: string) =>
      extractFields(txt).forEach((f) => {
        if (!map.has(f)) map.set(f, new Set());
        map.get(f)!.add(loc);
      });
    add(generalRules, "Regras");
    add(dadosEscritorio, "Dados do Escritório");
    add(honorariosTexto, "Honorários");
    pipelineAgents.forEach((a) => add(agentScanText(a), ROLE_META[a.role]?.label ?? a.role));
    faqItems.forEach((it) => add(`${it.pergunta ?? ""}\n${it.resposta ?? ""}`, "FAQ"));
    objectionItems.forEach((it) => add(`${it.titulo ?? ""}\n${it.resposta ?? ""}`, "Objeções"));
    return [...map.entries()].map(([field, locs]) => ({ field, locs: [...locs] }));
  })();

  // Marcadores [[audio:nome]] em TODOS os textos (mesma abrangência do {{ }}): prompts, FAQ,
  // objeções, regras e dados. Alimentam a "Edição rápida de áudios" (variante mídia).
  const audioMarkers = (() => {
    const set = new Set<string>();
    const add = (txt: string) => extractAudios(txt).forEach((m) => set.add(m));
    add(generalRules);
    add(dadosEscritorio);
    add(honorariosTexto);
    pipelineAgents.forEach((a) => add(agentScanText(a)));
    faqItems.forEach((it) => add(`${it.pergunta ?? ""}\n${it.resposta ?? ""}`));
    objectionItems.forEach((it) => add(`${it.titulo ?? ""}\n${it.resposta ?? ""}`));
    return [...set];
  })();

  // Roteiro de gravação do produto (produtos de mídia): o card da lateral e as gravações que combinam com os marcadores.
  const sugestoesRoteiro = sugestoesDeMidia(audioMarkers, roteiro);
  /** Salva o rascunho onde parou e abre o roteiro (tela única de gravação); a volta retoma daqui. */
  // "Áudio de objeções não encontrado": antes de ativar (ou salvar), pergunta se as objeções sem áudio vão em texto.
  // Sim → segue; o marcador fica guardado e, quando a pessoa gravar, a Edição rápida de mídias oferece confirmar
  // e o áudio volta a valer. "Gravar agora" → salva onde parou e abre o roteiro.
  const perguntarObjecoes = (seguir: () => void) => {
    if (isAudio && objecoesSemAudio.length > 0 && !objecoesEmTextoOk.current) {
      depoisDaPergunta.current = seguir;
      setPerguntaObjecoes(true);
      return;
    }
    seguir();
  };
  const pedirAtivar = () => perguntarObjecoes(() => { void activate(); });
  // Saindo do Conteúdo (onde ficam as mídias): pergunta já aqui, uma vez; ao ativar não pergunta de novo.
  const sairDoConteudo = async () => {
    const ok = await saveAllAgents();
    if (ok) perguntarObjecoes(() => setStep(4));
  };

  const gravarRoteiro = async () => {
    if (!template?.id) return;
    // Captura o texto que está sendo digitado no agente em foco (só com o editor montado, aba "agente").
    if (step === 3 && step3Tab === "agente") flushHandlerRef.current?.();
    if (isEdit) {
      // Edição: a volta do roteiro não retoma o que ainda não foi salvo — pede para salvar antes de sair.
      // (mesmos critérios do editChanges: nome, boas-vindas, prompt e gatilho de transferência, sem espaços nas pontas)
      const t = (v: any) => String(v ?? "").trim();
      const digitouAgora = pipelineAgentsRef.current.some((a, i) => {
        const b = pipelineAgents[i];
        return !b || a.role !== b.role || t(a.name) !== t(b.name) || t(a.welcome) !== t(b.welcome)
          || t(freeformOf(a.blocks)) !== t(freeformOf(b.blocks))
          || t(blockOf(a.blocks, "handoff_trigger")) !== t(blockOf(b.blocks, "handoff_trigger"));
      });
      if (digitouAgora || rascunhoLocal.sujo || (editChanges?.total ?? 0) > 0) {
        rascunhoLocal.gravarAgora(); // guarda no navegador o que foi editado (rede de segurança)
        toast.warning("Salve as alterações antes de ir gravar o roteiro.", { id: "roteiro-salvar-antes" });
        return;
      }
    }
    await salvarRascunho();
    if (isEdit) rascunhoLocal.gravarAgora();
    const aqui = isEdit ? window.location.pathname : `${window.location.pathname}?continuar=1`;
    navigate(`/roteiros/${template.id}?voltar=${encodeURIComponent(aqui)}`);
  };

  // Checklist da REVISÃO (passo 6): valida cada etapa. obrig=true bloqueia ativar.
  const zapCfg: any = (integrations as any)?.zapsign;
  const zapStatus: "ok" | "pending" | "none" = zapCfg?.enabled ? (zapCfg.template_id ? "ok" : "pending") : "none";
  const zapModelo = (zapCfg?.templates ?? []).find((m: any) => m.id === zapCfg?.template_id)?.name;
  // Áudio de objeção sem gravação: o motor tira o marcador vazio e o agente responde a objeção com o texto curto que já
  // vem logo abaixo dele no roteiro. Marcadores do resto do prompt são os materiais obrigatórios do roteiro.
  const marcadoresDeObjecao = new Set<string>();
  objectionItems.forEach((it) => extractAudios(`${it.titulo ?? ""}\n${it.resposta ?? ""}`).forEach((m) => marcadoresDeObjecao.add(m)));
  const objecoesSemAudio = objectionItems
    .map((it) => ({ titulo: String(it.titulo ?? "").replace(/^OBJ\s*\d+\s*[—-]\s*/i, ""), marcadores: extractAudios(it.resposta ?? "") }))
    .filter((it) => it.marcadores.length > 0);
  const principaisSemAudio = audioMarkers.filter((m) => !marcadoresDeObjecao.has(m));
  const nomeDoMarcador = (m: string) => (m.includes(":") ? m.slice(m.indexOf(":") + 1) : m);

  const revisao = [
    { key: "identidade", obrig: true, opcional: false, vazio: false, ok: !!name.trim(), label: "Identidade", det: !name.trim() ? "Defina o nome do agente" : !selectedWhatsapp ? `${name} · sem número ainda (conecte depois)` : `${name} · ${selectedWhatsapp}`, ir: () => setStep(1) },
    { key: "comportamento", obrig: false, opcional: false, vazio: false, ok: true, label: "Comportamento", det: llmModels.find((m) => m.id === selectedModel)?.name ?? "Modelo padrão", ir: () => setStep(2) },
    { key: "conteudo", obrig: false, opcional: true, vazio: false, ok: productFields.length === 0, label: "Conteúdo · campos {{ }}", det: productFields.length === 0 ? "Todos os campos aplicados" : `${productFields.length} campo${productFields.length > 1 ? "s" : ""} {{ }} — na Edição rápida: Aplicar o valor ou Excluir os que não usar`, ir: () => { setStep(3); setStep3Tab("campos"); } },
    // ZapSign é opcional na ativação: dá para ativar e treinar sem conta; sem ele a IA não gera o contrato sozinha
    // (na Coleta de Dados a equipe recebe o caso para mandar o contrato).
    { key: "integracao", obrig: false, opcional: true, vazio: zapStatus !== "ok", ok: zapStatus === "ok", label: "Integração ZapSign", det: zapStatus === "ok" ? `Contrato: ${zapModelo ?? "modelo selecionado"}` : zapStatus === "pending" ? "Conectada, mas falta selecionar o modelo do contrato (pode ser depois)" : "Sem ZapSign por enquanto: a IA não gera o contrato sozinha (pode conectar depois)", ir: () => setStep(4) },
    { key: "faq", obrig: false, opcional: true, vazio: faqItems.length === 0, ok: true, label: "FAQ", det: faqItems.length ? `${faqItems.length} pergunta${faqItems.length > 1 ? "s" : ""}` : "Nenhuma (opcional)", ir: () => { setStep(3); setStep3Tab("faq"); } },
    { key: "followup", obrig: false, opcional: true, vazio: isEdit ? !followupEdicao?.ligado : !followupLigado, ok: true, label: "Follow-up", det: (isEdit ? followupEdicao?.ligado : followupLigado) ? `Ligado · ${(isEdit ? followupEdicao?.resumo ?? [] : fuHoras ? fuHoras.map(rotuloHoras) : fuPrevia?.resumo ?? []).join(", ") || "cadência padrão"}` : "Desligado — leads que param de responder não recebem lembrete", ir: () => setStep(5) },
    ...(isAudio ? [{ key: "midias", obrig: false, opcional: true, vazio: principaisSemAudio.length > 0, ok: principaisSemAudio.length === 0,
      label: "Mídias do roteiro",
      det: principaisSemAudio.length === 0
        ? (objecoesSemAudio.length ? `Materiais obrigatórios no lugar · ${objecoesSemAudio.length} objeç${objecoesSemAudio.length > 1 ? "ões" : "ão"} em texto até gravar` : "Todas as mídias no lugar")
        : `Falta${principaisSemAudio.length > 1 ? "m" : ""} ${principaisSemAudio.length} material${principaisSemAudio.length > 1 ? "is" : ""} obrigatório${principaisSemAudio.length > 1 ? "s" : ""}: ${principaisSemAudio.map(nomeDoMarcador).join(", ")} (nesses pontos o agente segue só com texto)`,
      ir: () => { setStep(3); setStep3Tab("audios"); } }] : []),
    { key: "objecoes", obrig: false, opcional: true, vazio: objectionItems.length === 0, ok: true, label: "Objeções", det: objectionItems.length ? `${objectionItems.length} cadastrada${objectionItems.length > 1 ? "s" : ""}` : "Nenhuma (opcional)", ir: () => { setStep(3); setStep3Tab("objecoes"); } },
  ];
  const pendencias = revisao.filter((i) => i.obrig && !i.ok);
  const podeAtivar = pendencias.length === 0;

  // MODO EDIÇÃO: diff do estado atual vs. o original (editData) para a Revisão.
  const editChanges = (() => {
    if (!isEdit || !editData) return null;
    const origByRole = new Map((editData.pipelineAgents ?? []).map((a: any) => [a.role, a]));
    const promptChanges = pipelineAgents
      .map((a) => {
        const orig: any = origByRole.get(a.role);
        const before = String(orig?.promptText ?? "").trim();
        const after = String(freeformOf(a.blocks) ?? "").trim();
        // Detecta TAMBÉM mudança em boas-vindas, gatilho de transferência (mensagem_troca —
        // ex.: "msg após contrato assinado") e nome do agente — senão editar SÓ esses campos
        // não conta como alteração e o botão de salvar fica travado (mesmo bug do Dados).
        const welcomeMudou = String(orig?.welcome ?? "").trim() !== String(a.welcome ?? "").trim();
        const trocaMudou = String(blockOf(orig?.blocks ?? [], "handoff_trigger")).trim() !== String(blockOf(a.blocks, "handoff_trigger")).trim();
        const nomeMudou = String(orig?.name ?? "").trim() !== String(a.name ?? "").trim();
        const changed = before !== after || welcomeMudou || trocaMudou || nomeMudou;
        return { role: a.role, label: a.name, changed, before, after, delta: after.length - before.length };
      })
      .filter((c) => c.changed);

    const norm = (v: any) => JSON.stringify(v ?? null);
    const modelName = (id?: string) => llmModels.find((m) => m.id === id)?.name ?? (id || "—");
    const pausaStr = (h: number) => (h === -1 ? "nunca" : h >= 60 ? `${h / 60}h` : `${h}min`);
    const comportamentoStr = (t: number, d: number, h: number, s: boolean) =>
      `temp ${t.toFixed(1)} · delay ${d}s · pausa ${pausaStr(h)} · ${s ? "24h" : "horário comercial"}`;
    const ePlural = (n: number, sing: string, plur: string) => `${n} ${n === 1 ? sing : plur}`;

    const items = [
      { key: "nome", label: "Nome do produto", changed: String(name).trim() !== String(editData.name ?? "").trim(),
        before: editData.name || "—", after: name || "—" },
      { key: "numero", label: "Número de WhatsApp", changed: (selectedWhatsapp || "") !== (editData.numeroIa || ""),
        before: editData.numeroIa || "—", after: selectedWhatsapp || "—" },
      { key: "modelo", label: "Modelo de IA", changed: selectedModel !== editData.selectedModel,
        before: modelName(editData.selectedModel), after: modelName(selectedModel) },
      { key: "comportamento", label: "Comportamento", changed: (temperature[0] !== (editData.temperature ?? TEMPERATURA_INDICADA)) || (humanPause !== (editData.humanPause ?? 30)) || (schedule24 !== (editData.schedule24 ?? true)) || (responseDelay !== (editData.responseDelay ?? 10)),
        before: comportamentoStr(editData.temperature ?? TEMPERATURA_INDICADA, editData.responseDelay ?? 10, editData.humanPause ?? 30, editData.schedule24 ?? true),
        after: comportamentoStr(temperature[0], responseDelay, humanPause, schedule24) },
      { key: "faq", label: "FAQ", changed: norm(faqItems) !== norm(editData.faqItems),
        before: ePlural((editData.faqItems ?? []).length, "pergunta", "perguntas"), after: ePlural(faqItems.length, "pergunta", "perguntas") },
      { key: "objecoes", label: "Objeções", changed: norm(objectionItems) !== norm(editData.objectionItems),
        before: ePlural((editData.objectionItems ?? []).length, "cadastrada", "cadastradas"), after: ePlural(objectionItems.length, "cadastrada", "cadastradas") },
      { key: "regras", label: "Regras gerais", changed: String(generalRules).trim() !== String(editData.generalRules ?? "").trim(),
        before: ePlural(String(editData.generalRules ?? "").trim().length, "caractere", "caracteres"), after: ePlural(String(generalRules).trim().length, "caractere", "caracteres") },
      { key: "dados_escritorio", label: "Dados do Escritório", changed: String(dadosEscritorio).trim() !== String(editData.dadosEscritorio ?? "").trim(),
        before: ePlural(String(editData.dadosEscritorio ?? "").trim().length, "caractere", "caracteres"), after: ePlural(String(dadosEscritorio).trim().length, "caractere", "caracteres") },
      { key: "honorarios", label: "Honorários", changed: String(honorariosTexto).trim() !== String(editData.honorariosTexto ?? "").trim(),
        before: ePlural(String(editData.honorariosTexto ?? "").trim().length, "caractere", "caracteres"), after: ePlural(String(honorariosTexto).trim().length, "caractere", "caracteres") },
      { key: "integracoes", label: "Integração ZapSign", changed: norm(integrations) !== norm(editData.integrations),
        before: (editData.integrations as any)?.zapsign?.enabled ? "conectado" : "não conectado", after: (integrations as any)?.zapsign?.enabled ? "conectado" : "não conectado" },
    ].filter((i) => i.changed);

    return { promptChanges, changedItems: items, total: items.length + promptChanges.length };
  })();

  /** Resumo das mudanças que vai para a versão gravada no salvar ("Prompt do Closer", "FAQ (+2)"). */
  const resumoDasMudancas = (): string[] => {
    if (!editChanges || !editData) return [];
    const linhas = editChanges.promptChanges.map((pc) => (pc.before !== pc.after ? `Prompt do ${pc.label}` : `Agente ${pc.label}`));
    const delta = (n: number) => (n ? ` (${n > 0 ? "+" : ""}${n})` : "");
    editChanges.changedItems.forEach((it) => {
      if (it.key === "faq") linhas.push(`FAQ${delta(faqItems.length - (editData.faqItems ?? []).length)}`);
      else if (it.key === "objecoes") linhas.push(`Objeções${delta(objectionItems.length - (editData.objectionItems ?? []).length)}`);
      else linhas.push(it.label);
    });
    if (versaoRestaurada) linhas.unshift(`Restaurada da v${versaoRestaurada}`);
    return linhas;
  };

  /** Payload do TESTE do rascunho: o mesmo do ativar/sincronizar, com o que está na tela agora (mesmo sem salvar). */
  const obterRascunhoTeste = async () => {
    if (step === 3 && step3Tab === "agente") flushHandlerRef.current?.();
    await carregarFrasesTroca(template?.id).catch(() => null);
    setProdutoFrases(template?.id ?? null);
    return montarPayloadProduto();
  };
  const etapasTeste = pipelineAgents.map((a) => ({ role: a.role as string, name: a.name || ROLE_META[a.role]?.label || a.role }));

  /** "Restaurar" uma versão: o conteúdo dela vira o rascunho do editor. Nada vai ao ar até salvar. */
  const aplicarVersao = (c: ConteudoVersao, numero: number) => {
    const atuais = new Map(pipelineAgentsRef.current.map((a) => [a.role, a]));
    const restaurados: PipelineAgent[] = (c.agentes ?? [])
      .filter((v) => (ALL_ROLES_ORDERED as string[]).includes(v.papel))
      .map((v) => {
        const role = v.papel as AgentRole;
        const prompt = recolherHandoffsDoBot(v.prompt ?? "");
        return {
          id: atuais.get(role)?.id ?? role,
          role,
          name: v.nome || atuais.get(role)?.name || ROLE_META[role]?.label || role,
          welcome: v.boas_vindas ?? "",
          blocks: [
            { id: "freeform", type: "freeform", icon: "📝", label: "Prompt", content: prompt },
            { id: "handoff_trigger", type: "handoff_trigger", icon: "🔀", label: "Gatilho de transferência", content: recolherHandoffsDoBot(v.mensagem_troca ?? "") },
          ],
          promptText: prompt,
          saved: true,
        };
      })
      .sort((a, b) => roleSortIndex(a.role) - roleSortIndex(b.role));
    if (restaurados.length) {
      pipelineAgentsRef.current = restaurados;
      setPipelineAgents(restaurados);
      setActiveRoleIdx(0);
    }
    setFaqItems((c.faq ?? []).map((f) => ({ pergunta: f.pergunta ?? "", resposta: f.resposta ?? "" })));
    setObjectionItems((c.objecoes ?? []).map((o) => ({ titulo: o.titulo ?? "", resposta: o.resposta ?? "" })));
    setGeneralRules(c.regras_markdown ?? "");
    setDadosEscritorio(c.dados_escritorio ?? "");
    setEditorVersion((n) => n + 1);             // remonta o editor do agente com o texto restaurado
    setVersaoRestaurada(numero);
    setAba("editar");
    setStep(6);                                 // a Revisão mostra o antes e depois contra o que está no ar
  };

  /** Preenche um campo {{ }} de uma vez em TODO o produto: regras + agentes + FAQ + objeções. */
  const applyGlobalField = (field: string, value: string) => {
    const v = sanitizeFieldValue(value); // validação leve: apara/colapsa espaços, limita tamanho
    if (!v) return;
    // Obs: ao chegar na aba "campos" o agente em foco já foi capturado (goToSection),
    // então NÃO chamamos o flush aqui (evita reaplicar um estado antigo do editor).
    setGeneralRules((g) => fillField(g, field, v));
    setDadosEscritorio((d) => fillField(d, field, v));
    setHonorariosTexto((d) => fillField(d, field, v));
    const next = pipelineAgentsRef.current.map((a) => fillAgentField(a, field, v));
    pipelineAgentsRef.current = next;
    setPipelineAgents(next);
    setFaqItems((prev) => prev.map((it) => ({ pergunta: fillField(it.pergunta ?? "", field, v), resposta: fillField(it.resposta ?? "", field, v) })));
    setObjectionItems((prev) => prev.map((it) => ({ titulo: fillField(it.titulo ?? "", field, v), resposta: fillField(it.resposta ?? "", field, v) })));
    setGlobalDraft((d) => { const n = { ...d }; delete n[field]; return n; });
    setFieldValues((d) => ({ ...d, [field]: v }));
    setAppliedValues((prev) => (prev.includes(v) ? prev : [...prev, v]));
    setEditorVersion((n) => n + 1); // remonta o editor com o texto novo
    setPedidoSalvar((n) => n + 1); // salva depois do commit, com os textos já trocados
  };

  /** Escolheu o áudio de um [[audio:marcador]] → troca o marcador pela URL em TODO o produto
   *  (prompts + FAQ + objeções + regras + dados). O link fica inline, igual ao @ (o bot envia). */
  const fillAudioMarker = (marker: string, url: string) => fillAudioMarkers([{ marcador: marker, url }]);

  /** Várias trocas de uma vez ("Confirmar todas" do roteiro): encadeia todas sobre o mesmo texto,
   *  num só render, e salva o rascunho UMA vez, já com os textos novos (pedido para depois do commit). */
  const fillAudioMarkers = (lista: { marcador: string; url: string }[]) => {
    const trocas = lista.filter((t) => t.marcador && t.url);
    if (!trocas.length) return;
    const noTexto = (txt: string) => trocas.reduce((t, { marcador, url }) => fillAudioInText(t, marcador, url), txt);
    setGeneralRules((g) => noTexto(g));
    setDadosEscritorio((d) => noTexto(d));
    setHonorariosTexto((d) => noTexto(d));
    const next = pipelineAgentsRef.current.map((a) => trocas.reduce((ag, { marcador, url }) => fillAgentAudio(ag, marcador, url), a));
    pipelineAgentsRef.current = next;
    setPipelineAgents(next);
    setFaqItems((prev) => prev.map((it) => ({ pergunta: noTexto(it.pergunta ?? ""), resposta: noTexto(it.resposta ?? "") })));
    setObjectionItems((prev) => prev.map((it) => ({ titulo: noTexto(it.titulo ?? ""), resposta: noTexto(it.resposta ?? "") })));
    setEditorVersion((n) => n + 1); // remonta o editor com o link inserido
    setPedidoSalvar((n) => n + 1);  // salva com o estado novo (salvarRascunho() aqui gravaria o texto de antes)
  };

  /** "Excluir" um [[prefixo:nome]] — remove o marcador de TODO o conteúdo (pra quem não tem essa
   *  mídia). O marcador some da lista de pendentes. Espelha o excludeGlobalField dos campos {{ }}. */
  const excludeAudioMarker = (marker: string) => {
    setGeneralRules((g) => fillAudioInText(g, marker, ""));
    setDadosEscritorio((d) => fillAudioInText(d, marker, ""));
    setHonorariosTexto((d) => fillAudioInText(d, marker, ""));
    const next = pipelineAgentsRef.current.map((a) => fillAgentAudio(a, marker, ""));
    pipelineAgentsRef.current = next;
    setPipelineAgents(next);
    setFaqItems((prev) => prev.map((it) => ({ pergunta: fillAudioInText(it.pergunta ?? "", marker, ""), resposta: fillAudioInText(it.resposta ?? "", marker, "") })));
    setObjectionItems((prev) => prev.map((it) => ({ titulo: fillAudioInText(it.titulo ?? "", marker, ""), resposta: fillAudioInText(it.resposta ?? "", marker, "") })));
    setEditorVersion((n) => n + 1);
    setPedidoSalvar((n) => n + 1); // salva depois do commit, com os textos já trocados
  };

  // "Excluir" um campo {{ }} — remove o token de TODO o conteúdo (pra quem não tem aquele
  // dado, ex.: sem canal do YouTube). O campo some da lista → deixa de ser pendência.
  const excludeGlobalField = (field: string) => {
    setGeneralRules((g) => fillField(g, field, ""));
    setDadosEscritorio((d) => fillField(d, field, ""));
    setHonorariosTexto((d) => fillField(d, field, ""));
    const next = pipelineAgentsRef.current.map((a) => fillAgentField(a, field, ""));
    pipelineAgentsRef.current = next;
    setPipelineAgents(next);
    setFaqItems((prev) => prev.map((it) => ({ pergunta: fillField(it.pergunta ?? "", field, ""), resposta: fillField(it.resposta ?? "", field, "") })));
    setObjectionItems((prev) => prev.map((it) => ({ titulo: fillField(it.titulo ?? "", field, ""), resposta: fillField(it.resposta ?? "", field, "") })));
    setGlobalDraft((d) => { const n = { ...d }; delete n[field]; return n; });
    setEditorVersion((n) => n + 1);
    setPedidoSalvar((n) => n + 1); // salva depois do commit, com os textos já trocados
  };

  // O editor avisa quando o conteúdo do agente difere do original (personalizado).
  const handleAgentDirty = (role: string, dirty: boolean) => {
    setCustomizedRoles((prev) => {
      if (dirty === prev.has(role)) return prev;
      const nextSet = new Set(prev);
      if (dirty) nextSet.add(role); else nextSet.delete(role);
      return nextSet;
    });
  };
  const isAgentCustomized = (a: PipelineAgent) => customizedRoles.has(a.role);

  const next = async () => {
    if (step === 1) {
      if (!name.trim()) {
        toast.error("Informe o nome do agente", { id: "ativar-validacao", description: "O nome é obrigatório para continuar." });
        return;
      }
      // Sem número dá para seguir: o agente é criado e configurado; o número entra quando o WhatsApp for conectado.
    }
    if (step === 2 && !isEdit) {
      // Entrando no step 3 → bootstrap; falha bloqueia o avanço (só no create)
      if (!(await bootstrapPipeline())) return;
    }
    setStep((s) => Math.min(STEP_COUNT, s + 1));
  };

  const prev = () => setStep((s) => Math.max(1, s - 1));

  const allSaved = pipelineAgents.length > 0 && pipelineAgents.every((a) => a.saved);

  /** Payload único de ativar/sincronizar (docs/API_PRODUTOS.md → "Payload de ativar/sincronizar"). */
  const montarPayloadProduto = async () => {
    // id do canal escolhido: da lista sincronizada; senão, busca na lista do servidor pelo número.
    const numero = digitosNumero(selectedWhatsapp);
    let idCanal: string | null = waNumbers.find((n) => digitosNumero(n.id) === numero)?.canalId ?? null;
    if (!idCanal && isEdit && numero && numero === digitosNumero(editData?.numeroIa)) idCanal = editData?.idCanal ?? null;
    if (!idCanal && numero) {
      const canais = await listarCanaisDisponiveis().catch(() => [] as Awaited<ReturnType<typeof listarCanaisDisponiveis>>);
      idCanal = canais.find((c) => digitosNumero(c.numero) === numero)?.id ?? null;
    }
    const agentes = pipelineAgentsRef.current.map((a) => ({
      papel: a.role,
      nome: a.name,
      boas_vindas: a.welcome ?? "",
      prompt: promptParaBot(a),                 // @Agente X → acionar tool `x`; @Transferência → frase exata
      mensagem_troca: mensagemTrocaParaBot(a),  // frase de entrada da etapa (Assinatura nunca vazia)
    }));
    return {
      nome: name,
      numero_ia: numero || null,
      id_canal: idCanal,
      delay_s: responseDelay,
      caracteres_msg: charsMsg,
      pausa_min: humanPause,
      temperatura: temperature[0],
      modelo: selectedModel,
      // Edição não mexe no status (pausado continua pausado): só a ativação decide. Exceção: o produto que
      // voltou da lixeira está sendo ATIVADO de novo (o cliente escolhe se já liga ou deixa pausado).
      ...(isEdit && !reativando ? {} : { ativar_imediatamente: activateNow }),
      // Follow-up: só a ativação escolhe (agente que já tem follow-up não muda; quem manda é a aba Follow-up).
      ...(isEdit && !reativando ? {} : { followup_ativo: followupLigado, ...(followupLigado && fuHoras ? { followup_horas: fuHoras } : {}) }),
      periodo_graca_ativo: pipelineAgentsRef.current.some((a) => a.role === "periododegraca"),
      agentes,
      faq: faqItems,
      objecoes: objectionItems,
      regras_markdown: generalRules || "",
      dados_escritorio: dadosEscritorio || "",
      // Agente antigo sem honorários gravados e nada escrito: não manda (o servidor usa o texto do produto).
      ...(honorariosTexto.trim() || !isEdit || editData?.honorariosTexto !== undefined ? { honorarios_texto: honorariosTexto } : {}),
      variables: { ...fieldValues },
    };
  };

  /** MODO EDIÇÃO: regrava o agente (POST /produtos-ativados/{id}/sincronizar). Destrutivo. */
  const salvarEdicao = async () => {
    if (step3Tab === "agente") flushHandlerRef.current?.();
    if (!editData?.weaverAgentId) {
      toast.error("Produto sem agente vinculado no bot", { id: "ativar-validacao", description: "Aguarde a ativação terminar." });
      return;
    }
    setSubmitting(true);
    try {
      // Frases para Transferência carregadas ANTES do payload: expandem "@Transferência" e definem a
      // mensagem_troca de cada etapa. (Se falhar, a guarda abaixo barra token solto.)
      await carregarFrasesTroca(template?.id).catch(() => null);
      setProdutoFrases(template?.id ?? null); // frases DESTE produto no payload
      const semFraseEdit = erroSemFraseDeSaida(pipelineAgentsRef.current);
      if (semFraseEdit) {
        toast.error("Não é possível salvar", { id: "ativar-validacao", description: semFraseEdit });
        return; // finally libera o botão
      }

      // CONTEÚDO de NÍVEL PRODUTO (aba "Conteúdo": FAQ + objeções + regras gerais) vai IGUAL para
      // todos os agentes — o servidor regrava prompts e configurações do agente a cada save.
      const payload = { ...(await montarPayloadProduto()), resumo_mudancas: resumoDasMudancas() };
      // Não envia token "@Transferência" cru: o bot compararia o texto errado e não trocaria
      // o departamento.
      if (payloadComTokenSolto(payload.agentes)) {
        throw new Error("Há uma @Transferência sem frase cadastrada. Revise as frases para transferência (super admin) e tente de novo.");
      }

      // CANAL: número trocado vai no próprio payload (numero_ia + id_canal) — o servidor troca o
      // canal do agente. Se falhar (ex.: número em uso por outro agente), nada é salvo.
      if (onUpdate) {
        await onUpdate(payload);
      } else {
        await enviar(`/produtos-ativados/${groupId}/sincronizar`, payload);
      }

      // Persiste colunas do produto (app). Se o cliente revisou a atualização do catálogo,
      // grava a versão nova → some a badge "Atualização disponível".
      await enviar(`/produtos-ativados/${groupId}`, {
        nome: name, faq: faqItems, objecoes: objectionItems,
        conhecimento: knowledgeItems, integracoes: integrations,
        // numero_ia: gravado pelo servidor no sincronizar (em dígitos, igual à ativação).
        regras_markdown: generalRules || null,
        dados_escritorio: dadosEscritorio || null,
        ...(updateRevisado && editData?.versaoCatalogo ? { versao_template: editData.versaoCatalogo } : {}),
      }, "PATCH");

      queryClient.invalidateQueries({ queryKey: ["product", groupId] });
      queryClient.invalidateQueries({ queryKey: ["my-products"] });
      rascunhoLocal.limpar(); // salvo no servidor → nada a recuperar
      toast.success(reativando
        ? (activateNow ? "Produto ativado de novo no número escolhido" : "Número escolhido: o produto ficou pausado")
        : "Produto atualizado e sincronizado com o agente");
      setTimeout(() => navigate("/meus-produtos"), 600);
    } catch (e: any) {
      toast.error("Erro ao salvar", { description: e.message });
    } finally {
      setSubmitting(false);
    }
  };

  const activate = async () => {
    if (isEdit) { await salvarEdicao(); return; }
    if (!groupId) {
      toast.error("Pipeline não foi criado", { id: "ativar-pipeline" });
      return;
    }
    // TRAVA: todo agente que passa o lead adiante precisa da Frase para Transferência.
    await carregarFrasesTroca(template?.id).catch(() => null);
    setProdutoFrases(template?.id ?? null); // frases DESTE produto no payload
    const semFraseAtivar = erroSemFraseDeSaida(pipelineAgentsRef.current);
    if (semFraseAtivar) {
      toast.error("Não é possível ativar", { id: "ativar-validacao", description: semFraseAtivar });
      setStep(3);
      return;
    }
    setSubmitting(true);
    setBuildError(null);
    try {
      await salvarRascunho();

      // Frases para Transferência ANTES do payload (expandem "@Transferência" + mensagem_troca por etapa).
      await carregarFrasesTroca(template?.id).catch(() => null);
      setProdutoFrases(template?.id ?? null); // frases DESTE produto no payload

      // Payload do assistente (docs/API_PRODUTOS.md): o ZapSign (token + modelo) já está no servidor.
      const payload = await montarPayloadProduto();
      if (payloadComTokenSolto(payload.agentes)) {
        throw new Error("Há uma @Transferência sem frase cadastrada. Avise o suporte para revisar as frases para transferência.");
      }
      queryClient.invalidateQueries({ queryKey: ["my-products"] });

      // O servidor cria o agente, as etapas e copia os documentos padrão NA HORA (sem polling).
      const resp = await enviar<{ ok: boolean; id_agente?: string; verificacao?: any; erro?: string; detail?: string }>(
        `/produtos-ativados/${groupId}/ativar`, payload,
      );
      if (!resp?.ok) throw new Error(resp?.erro ?? resp?.detail ?? "Não foi possível concluir a ativação.");

      queryClient.invalidateQueries({ queryKey: ["my-products"] });
      rascunhoLocal.limpar(); // agente criado → o rascunho local da ativação não vale mais
      if (!mountedRef.current) return; // usuário saiu do wizard — não navega/atualiza UI
      setBuildStage(BUILD_STEPS.length);
      if (activateNow) {
        // Ligado na hora: mostra o terminal da ativação; ao fechar, vai para Meus agentes.
        setTerminalAtivacao(true);
      } else {
        toast.success("🎉 Seu agente está pronto!", { description: "Abrindo Meus Produtos…" });
        setTimeout(() => { if (mountedRef.current) navigate(`/meus-produtos`); }, 900);
      }
    } catch (e: any) {
      // O servidor marca o produto como falhou quando a ativação não termina; só atualizamos a lista.
      queryClient.invalidateQueries({ queryKey: ["my-products"] });
      // Mostra o ERRO no próprio overlay (não volta pro wizard). O produto fica salvo
      // como "falhou" em Meus Produtos com todas as edições — o usuário decide o próximo passo.
      setBuildError(e?.message ?? "Não foi possível concluir a ativação.");
    } finally {
      setSubmitting(false);
    }
  };

  const currentAgent = pipelineAgents[activeRoleIdx];
  const [catC1, catC2] = resolveGradient(template?.cover_gradient, template?.category ?? null);

  // Transições REAIS por papel (target_role dos handoff_rules) p/ o Teste de prompt orquestrar
  // o funil como o n8n (ProxAgente_Etapa = nome da etapa). EDIT: config.handoff_rules;
  // CREATE: bibAgentsRef.regras_handoff.
  const handoffByRole: Record<string, string[]> = (() => {
    const acc: Record<string, string[]> = {};
    const tgt = (rules: any): string[] =>
      (Array.isArray(rules) ? rules : []).map((r: any) => r?.target_role ?? r?.to_role).filter(Boolean);
    if (isEdit) {
      const cbr = editData?.configByRole ?? {};
      for (const [role, cfg] of Object.entries(cbr)) {
        const t = tgt((cfg as any)?.handoff_rules);
        // Fallback: agentes ativados antes têm config.handoff_rules vazio → usa o catálogo.
        acc[role] = t.length ? t : tgt(editData?.catalogHandoffByRole?.[role]);
      }
    } else {
      for (const b of (bibAgentsRef.current ?? [])) acc[b.papel] = tgt(b.regras_handoff);
    }
    return acc;
  })();

  // Regras de handoff COMPLETAS por papel (com keywords/trigger) p/ o Teste injetar o "quando"
  // certo no system prompt — o handoffByRole acima só carrega o destino (target_role).
  const handoffRulesByRole: Record<string, any[]> = (() => {
    const acc: Record<string, any[]> = {};
    const norm = (r: any): any[] => (Array.isArray(r) ? r : []);
    if (isEdit) {
      const cbr = editData?.configByRole ?? {};
      for (const [role, cfg] of Object.entries(cbr)) {
        const r = norm((cfg as any)?.handoff_rules);
        // Fallback p/ o catálogo (com keywords) quando o agente ativado não tem regras no config.
        acc[role] = r.length ? r : norm(editData?.catalogHandoffByRole?.[role]);
      }
    } else {
      for (const b of (bibAgentsRef.current ?? [])) acc[b.papel] = norm(b.regras_handoff);
    }
    return acc;
  })();

  return (
    <FrasesProdutoProvider idProduto={template?.id ?? null}>
    <div className="min-h-screen bg-[#f5f7fb]">
      {/* Overlay de construção — cobre a tela enquanto aguarda o provisionamento (ou mostra o erro) */}
      <AnimatePresence>
        {(submitting || buildError) && !isEdit && (
          <BuildingOverlay
            c1={catC1} c2={catC2} stage={buildStage} emoji={emojiDoProduto(template.icon)} categoria={template.category ?? undefined}
            productName={name || template.name} agentCount={pipelineAgents.length}
            error={buildError}
            onGoProducts={() => { setBuildError(null); navigate(`/meus-produtos`); }}
            onClose={() => setBuildError(null)}
          />
        )}
      </AnimatePresence>

      <TerminalAtivacao
        aberto={terminalAtivacao}
        nome={name || template?.name || "Agente"}
        produto={template?.name}
        numero={selectedWhatsapp}
        followupPassos={followupLigado ? (fuHoras?.length || fuPrevia?.resumo?.length || 4) : 0}
        aoFechar={() => { setTerminalAtivacao(false); if (mountedRef.current) navigate(`/meus-produtos`); }}
      />

      {/* Header / stepper — fixo no topo */}
      <div className="sticky top-0 z-30 overflow-hidden border-b border-[#E6EAF0] bg-white/85 backdrop-blur-xl">
        <div className="absolute inset-x-0 top-0 h-[3px] bg-[#EEF2F6]">
          <div
            className="h-full transition-[width] duration-500 [transition-timing-function:cubic-bezier(0.16,1,0.3,1)]"
            style={{ width: `${(step / STEP_COUNT) * 100}%`, background: `linear-gradient(90deg, ${catC1}, ${catC2})` }}
          />
        </div>
        <div className={`mx-auto flex items-center gap-4 px-4 py-3 sm:px-6 ${step === 3 ? "max-w-[1400px]" : "max-w-6xl"}`}>
          <Button asChild variant="ghost" size="sm" className="shrink-0 -ml-2 text-[#667085] hover:text-[#101828]">
            <Link to={isEdit ? "/meus-produtos" : `/biblioteca/${slug}`}>
              <ArrowLeft className="size-4 sm:mr-1" />
              <span className="hidden sm:inline">{isEdit ? "Voltar" : "Cancelar"}</span>
            </Link>
          </Button>

          <div className="min-w-0 flex-1">
            <div className="text-[10px] font-bold uppercase leading-tight tracking-wider text-[#98A2B3]">{reativando ? "Ativar de novo" : isEdit ? "Editando produto" : "Produto"}</div>
            <div className="truncate text-sm font-bold text-[#101828] sm:text-base">{name || template.name}</div>
          </div>

          {/* Stepper estilo tubelight (desktop) */}
          <div className={`hidden items-center gap-1 rounded-full border border-[#E6EAF0] bg-white/70 p-1 shadow-sm backdrop-blur ${isEdit && aba === "versoes" ? "" : "md:flex"}`}>
            {STEP_LABELS.map((lbl, idx) => {
              const s = idx + 1;
              const done = step > s;
              const active = step === s;
              const reachable = s <= step;
              return (
                <button
                  key={s}
                  type="button"
                  onClick={() => reachable && setStep(s)}
                  disabled={!reachable}
                  style={active || done ? { color: catC1 } : undefined}
                  className={`relative rounded-full px-3.5 py-1.5 text-xs font-semibold transition-colors ${active || done ? "" : "text-[#98A2B3] cursor-default"}`}
                >
                  <span className="relative z-10 inline-flex items-center gap-1.5">
                    <span className="grid size-4 place-items-center rounded-full text-[9px] transition-colors" style={active || done ? { backgroundColor: catC1, color: "#fff" } : { backgroundColor: "#E2E8F0", color: "#667085" }}>
                      {done ? <Check className="size-2.5" /> : s}
                    </span>
                    {lbl}
                  </span>
                  {active && (
                    <motion.div layoutId="lamp" className="absolute inset-0 rounded-full" style={{ backgroundColor: `${catC1}1a` }} transition={{ type: "spring", stiffness: 300, damping: 30 }}>
                      <div className="absolute -top-[5px] left-1/2 h-1 w-8 -translate-x-1/2 rounded-full" style={{ backgroundColor: catC1 }}>
                        <div className="absolute -left-2 -top-2 h-6 w-12 rounded-full blur-md" style={{ backgroundColor: `${catC1}40` }} />
                        <div className="absolute -top-1 h-6 w-8 rounded-full blur-md" style={{ backgroundColor: `${catC1}33` }} />
                      </div>
                    </motion.div>
                  )}
                </button>
              );
            })}
          </div>

          {isEdit && groupId && (
            <div className="flex shrink-0 items-center gap-1 rounded-full border border-[#E6EAF0] bg-white/70 p-1 shadow-sm" role="tablist" aria-label="Editor ou versões">
              {([["editar", "Editar", PencilLine], ["versoes", "Versões", History]] as const).map(([id, rotulo, Icone]) => (
                <button key={id} type="button" role="tab" aria-selected={aba === id} aria-label={rotulo} title={rotulo} onClick={() => { if (step === 3 && step3Tab === "agente") flushHandlerRef.current?.(); setAba(id); }}
                        className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold transition-colors ${aba === id ? "" : "text-[#98A2B3] hover:text-[#667085]"}`}
                        style={aba === id ? { color: catC1, backgroundColor: `${catC1}1a` } : undefined}>
                  <Icone className="size-3.5" /><span className={aba === "versoes" ? "" : "hidden xl:inline"}>{rotulo}</span>
                </button>
              ))}
            </div>
          )}

          <div className="shrink-0 rounded-full border border-[#E2E8F0] bg-white px-3 py-1 text-xs font-medium text-[#667085] md:hidden">
            {step}/{STEP_COUNT} · {STEP_LABELS[step - 1]}
          </div>
        </div>
      </div>

      <div className={`mx-auto w-full px-4 pb-6 pt-12 sm:px-6 lg:px-8 lg:pb-8 lg:pt-14 ${step === 3 ? "max-w-[1400px]" : "max-w-6xl"}`}>
        {/* Página recarregou antes de salvar → oferece recuperar o que estava sendo editado */}
        {rascunhoLocal.pendente && (
          <RecuperarRascunhoBanner
            className="mb-5"
            salvoEm={rascunhoLocal.pendente.salvoEm}
            onRecuperar={aplicarRascunhoLocal}
            onDescartar={rascunhoLocal.descartar}
          />
        )}
        {/* Banner de atualização do catálogo (admin subiu a versão) — só no modo edição */}
        {isEdit && editData?.atualizacaoDisponivel && !updateRevisado && (
          <Aviso
            tipo="info"
            icone={Sparkles}
            className="mb-5"
            titulo={`Atualização do produto disponível${editData?.versaoCatalogo ? ` (v${editData.versaoCatalogo})` : ""}`}
            acoes={<Button size="sm" onClick={() => setRevisarOpen(true)}>Revisar o que mudou</Button>}
          >
            A equipe LawChat atualizou este produto. Revise as mudanças e escolha o que trazer para o seu agente.
          </Aviso>
        )}
        {isEdit && updateRevisado && (
          <Aviso tipo="sucesso" className="mb-5" titulo="Atualização revisada">
            Falta só salvar para confirmar as mudanças no agente.
          </Aviso>
        )}
        {isEdit && editData && !editData.precisaAtivar && (
          <AvisoFollowupDesligado className="mb-5" idAtivado={editData.groupId} situacao={followupEdicao} aoLigar={setFollowupEdicao} />
        )}
        {isEdit && versaoRestaurada && aba === "editar" && (
          <Aviso tipo="info" icone={History} className="mb-5" titulo={`Versão ${versaoRestaurada} carregada no rascunho`}
                 acoes={<Button size="sm" variant="outline" onClick={() => setStep(6)}>Ver o que vai mudar</Button>}>
            Confira e salve para publicar. Até lá, o agente no ar continua como está.
          </Aviso>
        )}
        {isEdit && aba === "versoes" && groupId ? (
          <VersoesProduto idProduto={groupId} mudancasNaoSalvas={editChanges?.total ?? 0} onRestaurar={aplicarVersao} c1={catC1}
            onIrParaRevisao={() => { setAba("editar"); setStep(STEP_COUNT); }} />
        ) : (
        <div className={step === 3 ? "" : "grid lg:grid-cols-[minmax(0,1fr)_320px] gap-6 lg:gap-8 items-start"}>
        <div className="min-w-0">
          {/* mode="wait": a etapa atual sai (exit) antes da próxima entrar */}
          <AnimatePresence mode="wait" initial={false}>
          {step === 1 && (
            <motion.div key="s1" className="w-full" initial={{ opacity: 0, x: 24, filter: "blur(4px)" }} animate={{ opacity: 1, x: 0, filter: "blur(0px)" }} exit={{ opacity: 0, x: -24, filter: "blur(4px)", transition: STEP_EXIT }} transition={STEP_ENTER}>
              <div className="max-w-2xl space-y-2">
                <h1 className="text-[1.8rem] font-bold tracking-tight text-[#101828]">Dê uma identidade ao seu agente</h1>
                <p className="text-[#667085]">Um nome para identificar e o número de WhatsApp onde ele vai atender.</p>
              </div>

              <div className="mt-8 space-y-6">
                <Card className="p-6 lc-card">
                  <Label className="text-sm font-semibold flex items-center gap-2">
                    Nome do agente <span className="text-destructive">*</span>
                    <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-muted text-muted-foreground uppercase tracking-wide">Uso interno</span>
                  </Label>
                  <Input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Ex: Distrato Imobiliário, Comercial Trabalhista..."
                    required
                    aria-required="true"
                    aria-invalid={!name.trim()}
                    className="mt-2 text-lg h-12"
                  />
                  <p className="text-xs text-muted-foreground mt-2">
                    É só uma etiqueta <strong>interna</strong> para você e sua equipe acharem este agente no painel. <strong>O cliente não vê</strong> esse nome. Ajuda quando você tem mais de um produto ativo.
                  </p>

                  <div className="mt-3 flex flex-wrap items-center gap-1.5">
                    <span className="text-[11px] font-semibold text-muted-foreground mr-0.5 inline-flex items-center gap-1">
                      <Sparkles className="size-3 text-primary" />Sugestões:
                    </span>
                    {["Sofia", "LawChat", "Laura", "Alice", "Beatriz", "Valentina", "Lorena", "Júlia", "Marina", "Clara"].map((n) => (
                      <button
                        key={n}
                        type="button"
                        onClick={() => setName(n)}
                        className="text-xs font-medium rounded-full px-2.5 py-1 border border-border bg-background text-foreground/80 hover:border-primary hover:text-primary hover:bg-primary/5 transition-colors"
                      >
                        {n}
                      </button>
                    ))}
                  </div>
                </Card>

                <Card className="p-6 lc-card">
                  <div className="flex items-center justify-between gap-3 mb-3">
                    <Label className="text-sm font-semibold flex items-center gap-2 min-w-0">
                      <MessageSquare className="size-4 text-primary shrink-0" />
                      <span className="truncate">Canal: WhatsApp</span>
                      <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-[#f2f4f7] text-[#667085] border border-[#e4e7ec] uppercase shrink-0">
                        Pode ser depois
                      </span>
                    </Label>
                    {(!isEdit || changingNumber) && (
                      <Button onClick={syncWhatsapp} disabled={syncingWa} variant="outline" size="sm" className="shrink-0">
                        {syncingWa ? <Loader2 className="size-3.5 mr-1.5 animate-spin" /> : <RefreshCw className="size-3.5 mr-1.5" />}
                        Sincronizar
                      </Button>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground mb-3">
                    É o número onde a IA vai <strong>atender e responder sozinha</strong>. Ao ativar, ela passa a responder as mensagens que chegarem aqui. Sincronize e escolha um número disponível.
                  </p>

                  {/* MODO EDIÇÃO: número já conectado (preview) — só troca se pedir. */}
                  {isEdit && !changingNumber && (
                    <div className="rounded-xl border border-primary/30 bg-primary/5 p-4 flex items-center gap-3">
                      <div className="size-10 rounded-lg grid place-items-center bg-primary/15 shrink-0">
                        <MessageSquare className="size-5 text-primary" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="font-mono font-semibold text-sm">{selectedWhatsapp || "— sem número —"}</div>
                        <div className="text-[11px] text-success font-semibold flex items-center gap-1">
                          <Check className="size-3" strokeWidth={3} /> Conectado e atendendo neste agente
                        </div>
                      </div>
                      <Button variant="outline" size="sm" className="shrink-0" onClick={() => { setChangingNumber(true); syncWhatsapp(); }}>
                        <RefreshCw className="size-3.5 mr-1.5" /> Alterar número
                      </Button>
                    </div>
                  )}

                  {/* Voltou da lixeira: o número foi liberado; precisa escolher um para ativar de novo. */}
                  {reativando && (
                    <Aviso tipo="atencao" compacto className="mb-3" titulo="Escolha o número para ativar de novo">
                      Quando este produto foi para a lixeira, o número{editData?.numeroLiberado ? <> <strong className="font-mono">{editData.numeroLiberado}</strong></> : null} foi <strong>liberado</strong> para outros produtos.
                      Escolha um número disponível (pode ser o mesmo, se ninguém estiver usando) e ative. Prompts, documentos e contrato continuam os mesmos.
                    </Aviso>
                  )}

                  {/* MODO EDIÇÃO: aviso ao trocar para um número diferente do atual. */}
                  {isEdit && !reativando && changingNumber && selectedWhatsapp && selectedWhatsapp !== (editData?.numeroIa ?? "") && (
                    <Aviso
                      tipo="atencao"
                      compacto
                      className="mb-3"
                      titulo="Você vai trocar o número da IA"
                      acoes={
                        <Button type="button" size="sm" variant="outline" className="h-7 text-xs" onClick={() => { setSelectedWhatsapp(editData?.numeroIa ?? ""); setChangingNumber(false); }}>
                          Cancelar troca
                        </Button>
                      }
                    >
                      De <strong className="font-mono">{editData?.numeroIa || "—"}</strong> para <strong className="font-mono">{selectedWhatsapp}</strong>. Ao salvar, o canal é <strong>reconfigurado</strong> e a IA passa a atender só no número novo.
                    </Aviso>
                  )}

                  {(!isEdit || changingNumber) && (<>
                  {/* Dica: número novo evita confusão com conversas antigas */}
                  <Aviso tipo="dica" compacto className="mb-3" titulo="Dica rápida">
                    Prefira um número <strong>novo ou dedicado</strong> só para a IA. Num número com conversas antigas em andamento, ela pode se confundir com o histórico e dar respostas estranhas. Número limpo = atendimento mais previsível.
                  </Aviso>
                  <div className="space-y-2">
                    {waNumbers.length === 0 ? (
                      waSyncError ? (
                        <Aviso
                          tipo={waSyncError.tipo}
                          titulo={waSyncError.title}
                          acoes={
                            <Button type="button" size="sm" variant="outline" onClick={syncWhatsapp} disabled={syncingWa}>
                              {syncingWa ? <Loader2 className="size-3.5 mr-1.5 animate-spin" /> : <RefreshCw className="size-3.5 mr-1.5" />}
                              {syncingWa ? "Tentando..." : "Tentar de novo"}
                            </Button>
                          }
                        >
                          {waSyncError.detail}
                          {waSyncError.tecnico && (
                            <details className="group mt-2">
                              <summary className="cursor-pointer select-none list-none text-[11px] font-medium text-muted-foreground hover:text-foreground inline-flex items-center gap-1 [&::-webkit-details-marker]:hidden">
                                <ChevronDown className="size-3 transition-transform group-open:rotate-180" />
                                Detalhes técnicos (para o suporte)
                              </summary>
                              <pre className="mt-1.5 max-h-40 overflow-auto rounded-lg border border-border bg-background p-2.5 text-[11px] leading-relaxed text-muted-foreground whitespace-pre-wrap break-all font-mono">{waSyncError.tecnico}</pre>
                            </details>
                          )}
                        </Aviso>
                      ) : (
                        <div className="text-sm text-muted-foreground text-center py-8 border border-dashed rounded-xl">
                          {syncingWa ? "Sincronizando números..." : "Clique em \"Sincronizar\" para listar os números disponíveis."}
                        </div>
                      )
                    ) : (
                      waNumbers.map((n) => {
                        const checked = selectedWhatsapp === n.id;
                        const isInactive = n.status === "inativo";
                        return (
                          <button
                            key={n.id}
                            onClick={() => { if (!isInactive) setSelectedWhatsapp(n.id); }}
                            disabled={isInactive}
                            aria-disabled={isInactive}
                            title={isInactive ? "Este número já está sendo usado por outro agente" : undefined}
                            className={`w-full p-4 rounded-xl border text-left flex items-center gap-3 transition ${
                              isInactive
                                ? "border-border bg-muted/40 opacity-60 cursor-not-allowed"
                                : checked
                                  ? "border-primary bg-primary/10"
                                  : "border-border hover:bg-muted/50"
                            }`}
                          >
                            <div className={`size-5 rounded-full border-2 grid place-items-center transition ${
                              isInactive ? "border-border bg-muted" : checked ? "bg-primary border-primary" : "border-border"
                            }`}>
                              {checked && !isInactive && <div className="size-2 rounded-full bg-white" />}
                            </div>
                            <div className={`size-9 rounded-lg grid place-items-center ${isInactive ? "bg-muted" : "bg-primary/15"}`}>
                              <MessageSquare className={`size-4 ${isInactive ? "text-muted-foreground" : "text-primary"}`} />
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className={`font-mono font-semibold text-sm ${isInactive ? "text-muted-foreground line-through" : ""}`}>{n.label}</div>
                              <div className="text-[11px] text-muted-foreground">{n.tag}</div>
                            </div>
                            {isInactive ? (
                              <span className="text-[10px] font-bold px-2 py-1 rounded-md bg-muted text-muted-foreground border border-border whitespace-nowrap">
                                EM USO
                              </span>
                            ) : (
                              <span className="text-[10px] font-bold px-2 py-1 rounded-md bg-success/15 text-success border border-success/30">
                                DISPONÍVEL
                              </span>
                            )}
                          </button>
                        );
                      })
                    )}
                  </div>
                  </>)}
                </Card>
              </div>
            </motion.div>
          )}

          {step === 2 && (
            <motion.div key="s2" initial={{ opacity: 0, x: 24, filter: "blur(4px)" }} animate={{ opacity: 1, x: 0, filter: "blur(0px)" }} exit={{ opacity: 0, x: -24, filter: "blur(4px)", transition: STEP_EXIT }} transition={STEP_ENTER}>
              <h1 className="text-[1.8rem] font-bold tracking-tight text-[#101828]">Comportamento do agente</h1>
              <p className="text-[#667085] mt-1.5">Defina como o agente reage no atendimento. O modelo de IA já vem otimizado para este produto. Você pode ajustá-lo no final, se quiser.</p>

              <div className="mt-8 space-y-5" style={{ ["--cat" as any]: catC1 }}>
                {/* Delay de resposta */}
                <Card className="p-6 lc-card">
                  <div className="flex items-center justify-between gap-3 flex-wrap">
                    <div>
                      <Label className="text-sm font-semibold text-[#101828]">Delay de resposta</Label>
                      <p className="text-xs text-[#667085] mt-1">Tempo que o agente espera juntando as mensagens do lead antes de responder de uma vez.</p>
                    </div>
                    <span className="text-xs font-semibold px-2.5 py-1 rounded-md" style={{ color: catC1, backgroundColor: `${catC1}14` }}>{responseDelay}s</span>
                  </div>
                  <div className="mt-4 flex flex-wrap gap-2">
                    {[5, 10, 15, 20, 30, 45].map((s) => (
                      <button
                        key={s}
                        onClick={() => setResponseDelay(s)}
                        style={responseDelay === s ? { backgroundColor: catC1, borderColor: catC1, boxShadow: `0 4px 12px -4px ${catC1}80` } : undefined}
                        className={`px-3.5 py-2 rounded-full text-xs font-semibold border transition-all ${
                          responseDelay === s
                            ? "text-white"
                            : "border-[#E2E8F0] text-[#475467] hover:border-[var(--cat)]"
                        }`}
                      >
                        {s}s
                      </button>
                    ))}
                  </div>

                  {/* Por que esse tempo existe */}
                  <Aviso tipo="dica" compacto className="mt-4" titulo="Dica rápida: por que não responder na hora?">
                    Resposta instantânea denuncia que é um robô. Um pequeno atraso imita o tempo natural de uma pessoa lendo e
                    digitando, e ainda deixa o lead terminar de mandar tudo antes de o agente responder.
                  </Aviso>
                  <div>
                    <div className="mt-2.5 grid sm:grid-cols-2 gap-2.5">
                      <div className="flex items-start gap-2.5 rounded-lg border border-[#eef1f5] bg-white p-2.5">
                        <div className="size-7 rounded-lg grid place-items-center shrink-0" style={{ color: catC1, backgroundColor: `${catC1}14` }}>
                          <MessageSquare className="size-3.5" />
                        </div>
                        <div className="min-w-0">
                          <div className="text-[11px] font-bold text-[#101828]">Atendimento humanizado</div>
                          <div className="text-[11px] text-[#667085] leading-snug mt-0.5">O lead sente que tem uma pessoa do outro lado, não um bot que responde no mesmo segundo.</div>
                        </div>
                      </div>
                      <div className="flex items-start gap-2.5 rounded-lg border border-[#eef1f5] bg-white p-2.5">
                        <div className="size-7 rounded-lg grid place-items-center shrink-0 text-[#7c3aed] bg-[#ede9fe]">
                          <Shield className="size-3.5" />
                        </div>
                        <div className="min-w-0">
                          <div className="text-[11px] font-bold text-[#101828]">Evita parecer suspeito</div>
                          <div className="text-[11px] text-[#667085] leading-snug mt-0.5">Respostas robóticas e instantâneas levantam suspeita do lead e do WhatsApp. O delay reduz esse risco.</div>
                        </div>
                      </div>
                    </div>
                  </div>
                </Card>

                {/* Tamanho das mensagens: em quantos caracteres a IA divide a resposta */}
                <Card className="p-6 lc-card">
                  <div className="flex items-center justify-between gap-3 flex-wrap">
                    <div>
                      <Label className="text-sm font-semibold text-[#101828]">Tamanho das mensagens</Label>
                      <p className="text-xs text-[#667085] mt-1">Em quantos caracteres a IA divide a resposta antes de enviar. Mensagens curtas parecem conversa; longas explicam mais de uma vez.</p>
                    </div>
                    <span className="text-xs font-semibold px-2.5 py-1 rounded-md" style={{ color: catC1, backgroundColor: `${catC1}14` }}>
                      {TAMANHOS_MSG.find((t) => t.valor === charsMsg)?.resumo ?? `até ${charsMsg} caracteres`}
                    </span>
                  </div>
                  <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-2">
                    {TAMANHOS_MSG.map((t) => {
                      const on = charsMsg === t.valor;
                      return (
                        <button key={t.valor} type="button" onClick={() => setCharsMsg(t.valor)}
                          style={on ? { borderColor: catC1, boxShadow: `0 0 0 3px ${catC1}22`, backgroundColor: `${catC1}0d` } : undefined}
                          className={`rounded-xl border px-3 py-2.5 text-left transition-all ${on ? "" : "border-[#E2E8F0] hover:border-[var(--cat)]"}`}>
                          <div className="text-[13px] font-semibold text-[#101828]">{t.rotulo}</div>
                          <div className="text-[11px] text-[#667085] mt-0.5">{t.resumo}</div>
                          <div className="mt-2 flex gap-0.5" aria-hidden>
                            {Array.from({ length: t.baloes }).map((_, i) => (
                              <span key={i} className="h-1.5 rounded-full" style={{ width: t.largura, backgroundColor: on ? catC1 : "#d0d5dd" }} />
                            ))}
                          </div>
                        </button>
                      );
                    })}
                  </div>
                  <p className="mt-3 text-[11px] text-[#98A2B3]">A divisão respeita frases e parágrafos (nunca corta uma palavra). Links e mídias vão sempre sozinhos.</p>
                </Card>

                {/* Pausa por intervenção humana */}
                <Card className="p-6 lc-card">
                  <div className="flex items-center justify-between gap-3 flex-wrap">
                    <div>
                      <Label className="text-sm font-semibold text-[#101828]">Pausa por intervenção humana</Label>
                      <p className="text-xs text-[#667085] mt-1">Quando um atendente humano responder, a IA fica pausada por este tempo antes de voltar a responder automaticamente.</p>
                    </div>
                    <span className="text-xs font-semibold px-2.5 py-1 rounded-md" style={{ color: catC1, backgroundColor: `${catC1}14` }}>
                      {humanPause === -1 ? "Nunca" : humanPause >= 60 ? `${humanPause / 60}h` : `${humanPause}min`}
                    </span>
                  </div>
                  <div className="mt-4 flex flex-wrap gap-2">
                    {[
                      { v: 15, l: "15min" },
                      { v: 30, l: "30min" },
                      { v: 60, l: "1h" },
                      { v: 120, l: "2h" },
                      { v: -1, l: "Nunca" },
                    ].map((opt) => (
                      <button
                        key={opt.v}
                        onClick={() => setHumanPause(opt.v)}
                        style={humanPause === opt.v ? { backgroundColor: catC1, borderColor: catC1, boxShadow: `0 4px 12px -4px ${catC1}80` } : undefined}
                        className={`px-3.5 py-2 rounded-full text-xs font-semibold border transition-all ${
                          humanPause === opt.v
                            ? "text-white"
                            : "border-[#E2E8F0] text-[#475467] hover:border-[var(--cat)]"
                        }`}
                      >
                        {opt.l}
                      </button>
                    ))}
                  </div>
                </Card>

                {/* Temperatura */}
                <Card className="p-6 lc-card">
                  <div className="flex items-center justify-between gap-3">
                    <Label className="text-sm font-semibold text-[#101828]">Temperatura (criatividade da resposta)</Label>
                    <span className="flex items-center gap-1.5">
                      {Math.abs(temperature[0] - TEMPERATURA_INDICADA) < 0.05
                        ? <span className="text-[11px] font-bold px-2 py-0.5 rounded-full bg-[#e3f7e8] text-[#067a2b]">✓ Indicada</span>
                        : <button type="button" onClick={() => setTemperature([TEMPERATURA_INDICADA])} className="text-[11px] font-semibold px-2 py-0.5 rounded-full border border-[#c6f0d2] text-[#067a2b] hover:bg-[#ecfdf3]">Usar a indicada (0.5)</button>}
                      <span className="text-xs font-semibold px-2.5 py-1 rounded-md" style={{ color: catC1, backgroundColor: `${catC1}14` }}>{temperature[0].toFixed(1)}</span>
                    </span>
                  </div>
                  <p className="text-xs text-[#667085] mt-1 leading-relaxed">
                    Controla o quanto o agente "improvisa" ao responder. Quanto <strong>mais baixo</strong>, mais ele segue o roteiro ao pé da letra
                    (respostas previsíveis e consistentes, sempre parecidas). Quanto <strong>mais alto</strong>, mais ele varia as palavras e soa
                    natural, porém aumenta a chance de fugir do script e inventar coisas. A indicada para atendimento jurídico é <strong>0.5</strong>.
                  </p>
                  <div className="mt-4">
                    <div style={{ ["--primary" as any]: hexToHsl(catC1) }}>
                      <Slider value={temperature} onValueChange={setTemperature} min={0} max={2} step={0.1} />
                    </div>
                    <div className="relative h-4 mt-1" aria-hidden>
                      {/* O Radix mantém a bolinha (20px) dentro da barra: o centro dela fica em 10px + (largura − 20px) × fração. */}
                      <span className="absolute top-0 flex items-center gap-1 text-[10px] font-bold text-[#067a2b] whitespace-nowrap"
                        style={{ left: `calc(10px + (100% - 20px) * ${TEMPERATURA_INDICADA / 2})`, transform: "translateX(-4px)" }}>
                        <span className="leading-none">▲</span>0.5 indicada
                      </span>
                    </div>
                    <div className="flex justify-between text-[11px] text-muted-foreground mt-1">
                      <span>Mais previsível (segue o roteiro)</span>
                      <span>Mais criativo (improvisa)</span>
                    </div>
                    <p className="text-xs text-muted-foreground mt-3">
                      {temperature[0] <= 0.3
                        ? "Respostas firmes e diretas. O agente segue o roteiro à risca, ideal para informações técnicas e jurídicas."
                        : temperature[0] <= 0.9
                        ? "Equilíbrio entre seguir o roteiro e soar humano. Recomendado para a maioria dos atendimentos."
                        : "O agente improvisa mais e varia o vocabulário. Bom para conversas leves, ruim para temas sensíveis."}
                    </p>
                  </div>
                </Card>

                {/* Modelo de IA — recolhido por padrão (avançado) */}
                <Card className="p-6 lc-card">
                  <details className="group">
                    <summary className="cursor-pointer flex items-center justify-between gap-3">
                      <div>
                        <Label className="text-sm font-semibold cursor-pointer">Modelo de IA (avançado)</Label>
                        <p className="text-xs text-muted-foreground mt-1">
                          Em uso pelo agente: <span className="font-semibold text-foreground">{llmModels.find((m) => m.id === selectedModel)?.name}</span>
                          {selectedModel === template.recommended_model && (
                            <span className="ml-1.5 text-[9px] font-bold px-1.5 py-0.5 rounded bg-success/15 text-success border border-success/30 uppercase align-middle">Padrão</span>
                          )}
                          . É o modelo que vai para o agente (enviado ao backend). Recomendamos manter o <strong>GPT-4.1 Mini</strong>.
                        </p>
                      </div>
                      <ChevronDown className="size-4 text-muted-foreground group-open:rotate-180 transition shrink-0" />
                    </summary>

                    <div className="mt-6 grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
                      {llmModels.map((m) => {
                        const selected = selectedModel === m.id;
                        const costPerConv =
                          ((3000 / 1000) * m.costPer1kIn + (1000 / 1000) * m.costPer1kOut) * 5.4;
                        return (
                          <button
                            key={m.id}
                            type="button"
                            onClick={() => setSelectedModel(m.id)}
                            style={selected ? { borderColor: catC1, backgroundColor: `${catC1}10`, boxShadow: `0 8px 24px -12px ${catC1}80` } : undefined}
                            className={`relative p-4 rounded-2xl border-2 text-left transition-all w-full ${
                              selected ? "" : "border-[#E6EAF0] hover:border-[var(--cat)]"
                            }`}
                          >
                            {m.recommended && (
                              <span className="absolute -top-2.5 left-4 text-[10px] font-bold px-2 py-0.5 rounded-md text-white tracking-wider" style={{ backgroundImage: `linear-gradient(135deg, ${catC1}, ${catC2})` }}>RECOMENDADO</span>
                            )}
                            <div className={`size-9 rounded-xl bg-gradient-to-br ${providerColors[m.provider]} grid place-items-center text-white shadow mb-3`}>
                              <Bot className="size-4" />
                            </div>
                            <div className="font-bold text-sm flex items-center gap-1.5">
                              {m.name}
                              {selected && <Check className="size-3.5" style={{ color: catC1 }} />}
                            </div>
                            <div className="text-[11px] text-muted-foreground capitalize">{m.provider} · {m.contextWindow}</div>
                            <div className="mt-2 text-[11px] tabular-nums">
                              <span className="text-muted-foreground">~</span>
                              <span className="font-semibold" style={{ color: catC1 }}>
                                {costPerConv.toLocaleString("pt-BR", { style: "currency", currency: "BRL", minimumFractionDigits: costPerConv < 1 ? 4 : 2 })}
                              </span>
                              <span className="text-muted-foreground"> /conv</span>
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  </details>
                </Card>
              </div>
            </motion.div>
          )}

          {step === 3 && (
            <motion.div key="s3" initial={{ opacity: 0, x: 24, filter: "blur(4px)" }} animate={{ opacity: 1, x: 0, filter: "blur(0px)" }} exit={{ opacity: 0, x: -24, filter: "blur(4px)", transition: STEP_EXIT }} transition={STEP_ENTER}>
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-start gap-3.5 min-w-0">
                  <div className="size-11 rounded-2xl grid place-items-center text-white shadow-sm shrink-0" style={{ backgroundImage: `linear-gradient(135deg, ${catC1}, ${catC2})` }}>
                    <Settings2 className="size-5" />
                  </div>
                  <div className="min-w-0">
                    <div className="text-[11px] font-bold uppercase tracking-wider" style={{ color: catC1 }}>Passo 3 · Conteúdo</div>
                    <h1 className="text-[1.8rem] font-bold tracking-tight text-[#101828] leading-tight">Configure o conteúdo</h1>
                    <p className="text-[#667085] mt-1 leading-relaxed">
                      Aqui você ajusta as <strong>regras gerais</strong>, o <strong>prompt de cada agente</strong>, o <strong>FAQ</strong> e as <strong>objeções</strong>.
                    </p>
                  </div>
                </div>
                {/* Dica rápida (estilo Linear/Notion) */}
                <Aviso tipo="dica" compacto titulo="Dica rápida" className="hidden xl:block max-w-[280px] shrink-0">
                  Digite <strong>@</strong> no prompt para inserir mídia ou transferir o lead a outro agente.
                </Aviso>
              </div>

              {bootstrapping || pipelineAgents.length === 0 ? (
                <div className="grid place-items-center py-20">
                  <Loader2 className="size-8 text-primary animate-spin" />
                </div>
              ) : (
                <div className="mt-6 grid lg:grid-cols-[248px_minmax(0,1fr)] gap-6 items-start" style={{ ["--cat" as any]: catC1 }}>
                  {/* NAV vertical — uma lista só, sempre clara onde você está */}
                  <nav className="lg:sticky lg:top-[5.5rem] rounded-2xl border border-[#E6EAF0] bg-white p-3 shadow-[0_1px_2px_rgba(16,24,40,.04)]">
                    {/* Cabeçalho — neutro (personalizar é opcional, o padrão já é bom) */}
                    {(() => {
                      const personalizados = pipelineAgents.filter((a) => isAgentCustomized(a)).length;
                      return (
                        <div className="px-1.5 pb-3 mb-1 border-b border-[#f0f2f6]">
                          <div className="text-[13px] font-bold text-[#101828]">Conteúdo do produto</div>
                          <div className="text-[11px] text-[#98A2B3] mt-0.5">
                            {personalizados > 0 ? (
                              <><span className="font-semibold" style={{ color: catC1 }}>{personalizados}</span> agente{personalizados > 1 ? "s" : ""} personalizado{personalizados > 1 ? "s" : ""}</>
                            ) : (
                              "Tudo no padrão do catálogo"
                            )}
                          </div>
                        </div>
                      );
                    })()}

                    {/* Atalho DESTACADO: Edição rápida de Prompt. Some o destaque quando tudo é preenchido. */}
                    {(() => {
                      const active = step3Tab === "campos";
                      const done = productFields.length === 0; // nada pendente → fica apagado
                      return (
                        <button
                          onClick={() => goToSection("campos")}
                          className="w-full text-left rounded-xl p-3 transition-all"
                          style={{
                            border: `1px solid ${done ? "#e9edf3" : active ? "#7c3aed" : "#e6ddfb"}`,
                            backgroundImage: done
                              ? "none"
                              : active
                              ? "linear-gradient(135deg, #f1ebfe, #faf8ff)"
                              : "linear-gradient(135deg, #faf8ff, #fdfcff)",
                            backgroundColor: done ? "#fafbfc" : undefined,
                            boxShadow: !done && active ? "0 4px 14px -6px rgba(124,58,237,.45)" : "none",
                            opacity: done && !active ? 0.85 : 1,
                          }}
                        >
                          <div className="flex items-center gap-2">
                            <div
                              className="size-7 rounded-lg grid place-items-center shrink-0 shadow-sm"
                              style={done
                                ? { backgroundColor: "#dcfce7", color: "#16a34a" }
                                : { backgroundImage: "linear-gradient(135deg, #a855f7, #7c3aed)", color: "#fff" }}
                            >
                              {done ? <Check className="size-4" strokeWidth={3} /> : <Braces className="size-4" />}
                            </div>
                            <span className={`text-sm font-bold flex-1 min-w-0 truncate ${done ? "text-[#64748b]" : "text-[#101828]"}`}>Edição rápida de Prompt</span>
                            {done ? (
                              <span className="text-[10px] font-bold rounded-full px-1.5 py-0.5 bg-[#dcfce7] text-[#16a34a] shrink-0 inline-flex items-center gap-0.5"><Check className="size-2.5" strokeWidth={3} />OK</span>
                            ) : (
                              <span className="text-[10px] font-bold rounded-full px-1.5 py-0.5 bg-[#ede9fe] text-[#7c3aed] shrink-0">{productFields.length}</span>
                            )}
                          </div>
                          <p className={`text-[10.5px] mt-1.5 leading-snug ${done ? "text-[#94a3b8]" : "text-[#7c5fc0]"}`}>
                            {done ? (
                              <>Tudo preenchido. Os valores já entraram em todos os agentes.</>
                            ) : (
                              <>⚡ Atalho: preenche os campos <span className="font-semibold">{"{{ }}"}</span> em <strong>todos os agentes</strong> de uma vez.</>
                            )}
                          </p>
                        </button>
                      );
                    })()}

                    {/* Atalho ciano: Edição rápida de ÁUDIOS (só na variante mídia) — irmão do de Prompt. */}
                    {isAudio && (() => {
                      const active = step3Tab === "audios";
                      const n = audioMarkers.length; // marcadores ainda pendentes (sem áudio escolhido)
                      return (
                        <button
                          onClick={() => goToSection("audios")}
                          className="w-full text-left rounded-xl p-3 transition-all mt-2"
                          style={{
                            border: `1px solid ${active ? "#0891b2" : "#cffafe"}`,
                            backgroundImage: active ? "linear-gradient(135deg, #ecfeff, #f0fdff)" : "linear-gradient(135deg, #f0fdff, #fafffe)",
                            boxShadow: active ? "0 4px 14px -6px rgba(8,145,178,.45)" : "none",
                          }}
                        >
                          <div className="flex items-center gap-2">
                            <div className="size-7 rounded-lg grid place-items-center shrink-0 shadow-sm" style={{ backgroundImage: "linear-gradient(135deg, #22d3ee, #0891b2)", color: "#fff" }}>
                              <Headphones className="size-4" />
                            </div>
                            <span className="text-sm font-bold flex-1 min-w-0 truncate text-[#101828]">Edição rápida de mídias</span>
                            {n > 0 && <span className="text-[10px] font-bold rounded-full px-1.5 py-0.5 bg-[#cffafe] text-[#0891b2] shrink-0">{n}</span>}
                          </div>
                          <p className="text-[10.5px] mt-1.5 leading-snug text-[#0e7490]">
                            🎧 Escolha a mídia de cada <span className="font-semibold">[[midia:…]]</span> dos seus textos.
                          </p>
                        </button>
                      );
                    })()}
                    {isAudio && roteiro && <CardRoteiroAtivacao roteiro={roteiro} aoGravar={gravarRoteiro} />}

                    <div className="my-2.5 border-t border-[#f0f2f6]" />

                    <div className="px-1.5 pt-3 pb-1.5 text-[10px] font-bold uppercase tracking-wider text-[#98A2B3]">Agentes do funil</div>

                    {/* lista de agentes com conector de funil */}
                    <div className="relative">
                      <div className="absolute left-[23px] top-5 bottom-5 w-px bg-[#E8ECF2]" aria-hidden />
                      {pipelineAgents.map((a, i) => {
                        const meta = ROLE_META[a.role] ?? { label: a.role, Icon: FileSignature } as any;
                        const active = step3Tab === "agente" && activeRoleIdx === i;
                        const custom = isAgentCustomized(a);
                        const status = active ? "Editando…" : custom ? "Personalizado" : "Padrão";
                        return (
                          <button
                            key={a.role}
                            onClick={() => goToSection("agente", i)}
                            style={active ? { backgroundColor: `${catC1}14` } : undefined}
                            className={`relative w-full flex items-center gap-2.5 rounded-xl px-1.5 py-1.5 text-left transition-colors ${active ? "" : "hover:bg-[#f6f8fb]"}`}
                          >
                            <div className="relative z-10 shrink-0">
                              <div
                                className="size-8 rounded-lg grid place-items-center shadow-sm ring-2 ring-white transition-colors"
                                style={custom
                                  ? { backgroundImage: `linear-gradient(135deg, ${catC1}, ${catC2})`, color: "#fff" }
                                  : { backgroundColor: "#eef1f6", color: "#aab2c0" }}
                              >
                                <meta.Icon className="size-4" />
                              </div>
                              {custom && (
                                <span className="absolute -bottom-1 -right-1 size-3.5 rounded-full bg-white grid place-items-center shadow-sm" title="Personalizado">
                                  <Check className="size-2.5" style={{ color: catC1 }} strokeWidth={3.5} />
                                </span>
                              )}
                            </div>
                            <div className="min-w-0 flex-1">
                              <div className="text-sm font-semibold truncate" style={{ color: active ? catC1 : custom ? "#101828" : "#475467" }}>{meta.label}</div>
                              <div className="text-[10px] truncate" style={{ color: active ? catC1 : "#98A2B3" }}>{status}</div>
                            </div>
                            {active && <span className="size-1.5 rounded-full shrink-0" style={{ backgroundColor: catC1 }} />}
                          </button>
                        );
                      })}
                    </div>

                    <div className="px-1.5 pt-3 pb-1.5 text-[10px] font-bold uppercase tracking-wider text-[#98A2B3]">Extras</div>
                    {([
                      { id: "faq", label: "FAQ", hint: "Perguntas frequentes", icon: <MessageSquare className="size-4" />, disabled: false },
                      { id: "objecoes", label: "Objeções", hint: "Como contorná-las", icon: <Shield className="size-4" />, disabled: false },
                      { id: "dados_escritorio", label: "Dados do Escritório", hint: "Informações da firma", icon: <Building2 className="size-4" />, disabled: false },
                      { id: "honorarios", label: "Honorários", hint: "Transcrição do áudio", icon: <Scale className="size-4" />, disabled: false },
                      { id: "conhecimento", label: "Conhecimento", hint: "Documentos do agente", icon: <Bot className="size-4" />, disabled: false },
                    ] as const).map((t) => (
                      <NavRow
                        key={t.id}
                        icon={t.icon}
                        label={t.label}
                        hint={t.hint}
                        active={step3Tab === t.id}
                        accent={catC1}
                        disabled={t.disabled}
                        onClick={() => goToSection(t.id)}
                      />
                    ))}

                    <div className="mt-3 rounded-lg bg-[#f6f8fb] px-3 py-2 text-[10px] leading-relaxed text-[#667085] flex items-center gap-1.5">
                      <Check className="size-3 shrink-0" style={{ color: catC1 }} /> Tudo é salvo automaticamente ao navegar.
                    </div>
                  </nav>

                  {/* PAINEL de conteúdo */}
                  <div className="min-w-0 space-y-6">
                  {step3Tab === "audios" && (
                    <AudioSlotsPanel
                      markers={audioMarkers}
                      onFill={fillAudioMarker}
                      onFillMany={fillAudioMarkers}
                      onRemove={excludeAudioMarker}
                      sugestoes={sugestoesRoteiro}
                      onGravarRoteiro={roteiro?.total ? gravarRoteiro : undefined}
                      opcionais={marcadoresDeObjecao}
                    />
                  )}
                  {step3Tab === "campos" && (
                    <Card className="p-6 lc-card" style={{ borderColor: "#ece9fb" }}>
                      <div className="flex items-center gap-2">
                        <div className="size-7 rounded-lg grid place-items-center shrink-0 bg-[#ede9fe] text-[#7c3aed]"><Braces className="size-4" /></div>
                        <span className="text-sm font-semibold text-[#101828]">Edição rápida de Prompt</span>
                        {productFields.length > 0 && <span className="text-[10px] font-bold rounded-full px-1.5 py-0.5 bg-[#ede9fe] text-[#7c3aed]">{productFields.length}</span>}
                        <span className="text-[10px] font-bold uppercase tracking-wider rounded-full px-2 py-0.5 bg-[#f1f5f9] text-[#64748b]">Global</span>
                      </div>
                      <p className="text-xs text-muted-foreground mt-1.5 mb-3">
                        Acha tudo que está em <code className="text-[#7c3aed] font-medium">{"{{ }}"}</code> nos <strong>5 agentes, no FAQ e nas objeções</strong>.
                        Preencha <strong>uma vez</strong> aqui e o valor entra em todos os lugares que usam o campo.
                        {productFields.length > 0 && <span className="text-[#94a3b8]"> Não tem algum (ex.: <code className="text-[#7c3aed]">{"{{Site}}"}</code>)? Use <strong>Excluir</strong> — não é obrigatório preencher todos.</span>}
                      </p>
                      {productFields.length === 0 ? (
                        appliedValues.length > 0 ? (
                          <motion.div
                            initial={{ opacity: 0, y: 8 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ duration: 0.35 }}
                            className="rounded-xl border border-[#bbf7d0] bg-[#f0fdf4] p-6 text-center"
                          >
                            <motion.div
                              initial={{ scale: 0, rotate: -20 }}
                              animate={{ scale: 1, rotate: 0 }}
                              transition={{ type: "spring", stiffness: 320, damping: 16, delay: 0.08 }}
                              className="size-12 rounded-full bg-[#22c55e] text-white grid place-items-center mx-auto shadow-[0_6px_16px_-4px_rgba(34,197,94,.55)]"
                            >
                              <Check className="size-6" strokeWidth={3} />
                            </motion.div>
                            <div className="text-base font-bold text-[#101828] mt-3">Tudo preenchido! 🎉</div>
                            <p className="text-xs text-[#667085] mt-1 max-w-sm mx-auto leading-relaxed">
                              Os valores entraram em <strong>todos os agentes</strong>, regras, FAQ e objeções. O que você preencheu aparece <span className="text-[#7c3aed] font-semibold">em roxo</span> dentro dos prompts.
                            </p>
                          </motion.div>
                        ) : (
                          <div className="rounded-xl border border-dashed border-[#e0d9f7] bg-[#faf8ff] p-5">
                            <div className="flex items-start gap-3">
                              <div className="size-9 rounded-xl grid place-items-center shrink-0 bg-[#ede9fe] text-[#7c3aed]">
                                <Braces className="size-[18px]" />
                              </div>
                              <div className="min-w-0">
                                <div className="text-sm font-semibold text-[#101828]">Ainda não há campos para preencher</div>
                                <p className="text-xs text-[#667085] mt-0.5 leading-relaxed">
                                  Campos são "atalhos" do prompt: você escreve uma vez e reaproveita em todos os agentes, sem editar um por um.
                                </p>
                              </div>
                            </div>

                            <div className="mt-4 space-y-2.5">
                              {[
                                <>No prompt de um agente, escreva o que muda de cliente para cliente entre <code className="text-[#7c3aed] font-medium">{"{{ }}"}</code>. Ex: <code className="text-[#7c3aed]">{"{{nome_do_escritorio}}"}</code>, <code className="text-[#7c3aed]">{"{{valor_da_consulta}}"}</code>.</>,
                                <>O campo <strong>aparece aqui sozinho</strong>, mostrando em quais lugares (agentes, FAQ, objeções) ele é usado.</>,
                                <>Você <strong>preenche uma vez</strong> e o valor entra em todos os lugares de uma vez.</>,
                              ].map((txt, i) => (
                                <div key={i} className="flex items-start gap-2.5">
                                  <span className="mt-0.5 size-5 shrink-0 rounded-full grid place-items-center text-[11px] font-bold bg-[#ede9fe] text-[#7c3aed]">{i + 1}</span>
                                  <span className="text-xs text-[#475467] leading-relaxed">{txt}</span>
                                </div>
                              ))}
                            </div>
                          </div>
                        )
                      ) : (
                        <div className="space-y-2.5">
                          {productFields.map(({ field: f, locs }) => {
                            const filled = !!(globalDraft[f] ?? "").trim();
                            return (
                            <div key={f} className="rounded-xl border border-[#eceaf6] bg-[#fcfbff] p-3">
                              <div className="flex items-center gap-2 flex-wrap mb-2">
                                <code className="rounded px-1.5 py-1 text-[12px] font-semibold text-[#7c3aed] bg-[#ede9fe]" title={`{{${f}}}`}>{`{{${f}}}`}</code>
                                <span className="text-[10px] font-bold text-[#98A2B3] uppercase tracking-wide">Opcional</span>
                                <span className="text-[10px] text-[#98A2B3]">· usado em</span>
                                {locs.map((l) => (
                                  <span key={l} className="text-[10px] font-semibold rounded-md px-1.5 py-0.5 bg-white border border-[#e5e8ee] text-[#64748b]">{l}</span>
                                ))}
                              </div>
                              <div className="flex items-center gap-2">
                                <Input
                                  value={globalDraft[f] ?? ""}
                                  onChange={(e) => setGlobalDraft((d) => ({ ...d, [f]: e.target.value }))}
                                  onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); applyGlobalField(f, globalDraft[f] ?? ""); } }}
                                  placeholder={`Valor para ${f}…`}
                                  className="h-9 text-sm bg-white focus-visible:ring-[#7c3aed]"
                                />
                                <Button
                                  size="sm"
                                  variant={filled ? "default" : "outline"}
                                  className={`h-9 shrink-0 font-semibold disabled:opacity-100 ${filled ? "text-white border-transparent" : "bg-white border-[#d6cdf2] text-[#7c3aed] hover:bg-[#ede9fe]"}`}
                                  style={filled ? { backgroundColor: "#7c3aed" } : undefined}
                                  disabled={!filled}
                                  onClick={() => applyGlobalField(f, globalDraft[f] ?? "")}
                                >
                                  <Check className="size-4 mr-1" />Aplicar
                                </Button>
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  className="h-9 shrink-0 text-[#98A2B3] hover:text-[#dc2626] hover:bg-[#fef2f2]"
                                  title="Remover este campo do prompt (para quem não tem esse dado)"
                                  onClick={() => excludeGlobalField(f)}
                                >
                                  <X className="size-4 mr-1" />Excluir
                                </Button>
                              </div>
                            </div>
                            );
                          })}
                        </div>
                      )}
                    </Card>
                  )}

                  {step3Tab === "agente" && currentAgent && (
                    <div className={MOSTRAR_TESTE_RASCUNHO ? "grid xl:grid-cols-[minmax(0,1fr)_minmax(340px,380px)] gap-5 items-start" : "grid gap-5 items-start"}>
                      <div className="space-y-4 min-w-0">
                        {/* Faixa de contexto/navegação — qual agente, posição e ir/voltar */}
                        <div className="flex items-center justify-between gap-3">
                          <div className="text-[11px] font-semibold text-[#667085]">
                            <span style={{ color: catC1 }}>Editando</span> · agente {activeRoleIdx + 1} de {pipelineAgents.length}
                          </div>
                          <div className="flex items-center gap-1.5 shrink-0">
                            <Button variant="outline" size="sm" onClick={() => goToSection("agente", Math.max(0, activeRoleIdx - 1))} disabled={activeRoleIdx === 0}>
                              <ArrowLeft className="size-4 mr-1" />Anterior
                            </Button>
                            <Button variant="outline" size="sm" onClick={() => goToSection("agente", Math.min(pipelineAgents.length - 1, activeRoleIdx + 1))} disabled={activeRoleIdx === pipelineAgents.length - 1}>
                              Próximo<ArrowRight className="size-4 ml-1" />
                            </Button>
                          </div>
                        </div>

                        <PipelineAgentEditor
                          key={`${currentAgent.role}-${editorVersion}`}
                          role={currentAgent.role}
                          agentId={currentAgent.id}
                          initialName={currentAgent.name}
                          initialWelcome={currentAgent.welcome}
                          initialBlocks={currentAgent.blocks}
                          initialPromptText={currentAgent.promptText}
                          saving={savingAgent}
                          saved={currentAgent.saved}
                          accent={catC1}
                          accentTo={catC2}
                          highlights={appliedValues}
                          onSave={saveCurrentAgent}
                          registerSaveHandler={(fn) => { saveHandlerRef.current = fn; }}
                          onFlush={captureAgentEdits}
                          registerFlushHandler={(fn) => { flushHandlerRef.current = fn; }}
                          registerSnapshotHandler={(fn) => { snapshotHandlerRef.current = fn; }}
                          onDirty={handleAgentDirty}
                        />
                      </div>

                      {/* Painel lateral: teste do RASCUNHO no motor real do servidor (app/gestao/rotas_rascunho.py). */}
                      {MOSTRAR_TESTE_RASCUNHO && <div className="xl:sticky xl:top-[5.5rem]">
                        <TestePrompt idProduto={groupId} obterRascunho={obterRascunhoTeste} etapas={etapasTeste}
                                     etapaSugerida={currentAgent.role} c1={catC1} />
                      </div>}
                    </div>
                  )}

                  {step3Tab === "faq" && (
                    <Card className="p-6 lc-card space-y-5">
                      <div className="flex items-center gap-3">
                        <div className="size-9 rounded-xl grid place-items-center text-white shrink-0" style={{ backgroundColor: catC1 }}><MessageSquare className="size-[18px]" /></div>
                        <div>
                          <Label className="text-sm font-semibold text-[#101828]">Perguntas frequentes</Label>
                          <p className="text-xs text-muted-foreground mt-0.5">Dúvidas comuns dos leads e como responder. Entram no conhecimento de todos os agentes deste produto.</p>
                        </div>
                      </div>

                      {faqItems.length === 0 ? (
                        <div className="rounded-xl border border-dashed border-[#e5e8ee] bg-[#fafbfc] p-6 text-center">
                          <MessageSquare className="size-5 mx-auto text-[#cbd5e1] mb-2" />
                          <p className="text-sm text-[#667085]">Nenhuma pergunta ainda.</p>
                          <p className="text-xs text-[#98A2B3] mt-0.5">Ex.: "Quanto tempo demora o processo?", "Quais documentos preciso?"</p>
                        </div>
                      ) : (
                        <div className="space-y-3">
                          {faqItems.map((item, idx) => (
                            <div key={idx} className="rounded-xl border border-[#eef1f5] bg-[#fafbfc] p-3">
                              <div className="flex items-center justify-between mb-2">
                                <span className="text-[10px] font-bold uppercase tracking-wider text-[#98A2B3]">Pergunta {idx + 1}</span>
                                <button onClick={() => setFaqItems((p) => p.filter((_, i) => i !== idx))} className="text-[#cbd5e1] hover:text-rose-500 transition-colors" title="Remover"><X className="size-4" /></button>
                              </div>
                              <Input
                                value={item.pergunta}
                                onChange={(e) => setFaqItems((prev) => prev.map((it, i) => i === idx ? { ...it, pergunta: e.target.value } : it))}
                                placeholder="Pergunta frequente (ex: Quanto tempo demora o processo?)"
                                className="font-semibold bg-white"
                              />
                              <RespostaComMidia
                                value={item.resposta}
                                onChange={(v) => setFaqItems((prev) => prev.map((it, i) => i === idx ? { ...it, resposta: v } : it))}
                                highlights={appliedValues}
                                placeholder="Como o agente deve responder…"
                                className="mt-2 min-h-[84px]"
                                showMidia={isAudio}
                              />
                            </div>
                          ))}
                        </div>
                      )}
                      <Button variant="outline" onClick={() => setFaqItems((p) => [...p, { pergunta: "", resposta: "" }])}>
                        <Plus className="size-4 mr-1.5" />Adicionar pergunta
                      </Button>
                    </Card>
                  )}

                  {step3Tab === "objecoes" && (
                    <Card className="p-6 lc-card space-y-5">
                      <div className="flex items-center gap-3">
                        <div className="size-9 rounded-xl grid place-items-center text-white shrink-0" style={{ backgroundColor: catC1 }}><Shield className="size-[18px]" /></div>
                        <div>
                          <Label className="text-sm font-semibold text-[#101828]">Objeções</Label>
                          <p className="text-xs text-muted-foreground mt-0.5">Resistências comuns do lead e como o agente deve contorná-las com segurança.</p>
                        </div>
                      </div>

                      {objectionItems.length === 0 ? (
                        <div className="rounded-xl border border-dashed border-[#e5e8ee] bg-[#fafbfc] p-6 text-center">
                          <Shield className="size-5 mx-auto text-[#cbd5e1] mb-2" />
                          <p className="text-sm text-[#667085]">Nenhuma objeção cadastrada.</p>
                          <p className="text-xs text-[#98A2B3] mt-0.5">Ex.: "Acho que é golpe", "Está caro", "Vou pensar".</p>
                        </div>
                      ) : (
                        <div className="space-y-3">
                          {objectionItems.map((item, idx) => (
                            <div key={idx} className="rounded-xl border border-[#eef1f5] bg-[#fafbfc] p-3">
                              <div className="flex items-center justify-between mb-2">
                                <span className="text-[10px] font-bold uppercase tracking-wider text-[#98A2B3]">Objeção {idx + 1}</span>
                                <button onClick={() => setObjectionItems((p) => p.filter((_, i) => i !== idx))} className="text-[#cbd5e1] hover:text-rose-500 transition-colors" title="Remover"><X className="size-4" /></button>
                              </div>
                              <Input
                                value={item.titulo}
                                onChange={(e) => setObjectionItems((prev) => prev.map((it, i) => i === idx ? { ...it, titulo: e.target.value } : it))}
                                placeholder="Título da objeção (ex: Acho que é golpe)"
                                className="font-semibold bg-white"
                              />
                              <RespostaComMidia
                                value={item.resposta}
                                onChange={(v) => setObjectionItems((prev) => prev.map((it, i) => i === idx ? { ...it, resposta: v } : it))}
                                highlights={appliedValues}
                                placeholder="Como o agente deve contornar essa objeção…"
                                className="mt-2 min-h-[100px]"
                                showMidia={isAudio}
                              />
                            </div>
                          ))}
                        </div>
                      )}
                      <Button variant="outline" onClick={() => setObjectionItems((p) => [...p, { titulo: "", resposta: "" }])}>
                        <Plus className="size-4 mr-1.5" />Adicionar objeção
                      </Button>
                    </Card>
                  )}

                  {step3Tab === "dados_escritorio" && (
                    <DadosEscritorioPanel
                      value={dadosEscritorio}
                      onChange={setDadosEscritorio}
                      accent={catC1}
                      handoffOptions={pipelineAgents.map((a) => a.name).filter(Boolean)}
                      highlights={appliedValues}
                    />
                  )}

                  {step3Tab === "honorarios" && (
                    <DadosEscritorioPanel
                      titulo="Honorários (transcrição do áudio)"
                      descricao="Como o escritório cobra, do jeito que está no áudio. A IA usa no Closer, no Contratos e na Assinatura quando o lead pergunta valor, porcentagem ou como paga. Os {{ }} entram na Edição rápida."
                      Icone={Scale}
                      value={honorariosTexto}
                      onChange={setHonorariosTexto}
                      accent={catC1}
                      handoffOptions={pipelineAgents.map((a) => a.name).filter(Boolean)}
                      highlights={appliedValues}
                    />
                  )}

                  {step3Tab === "conhecimento" && (
                    <ConhecimentoManager idAgente={isEdit ? (editData?.weaverAgentId ? String(editData.weaverAgentId) : null) : null} idProduto={template?.id ?? null} />
                  )}

                  </div>
                </div>
              )}
            </motion.div>
          )}

          {step === 4 && (
            <motion.div key="s4" initial={{ opacity: 0, x: 24, filter: "blur(4px)" }} animate={{ opacity: 1, x: 0, filter: "blur(0px)" }} exit={{ opacity: 0, x: -24, filter: "blur(4px)", transition: STEP_EXIT }} transition={STEP_ENTER}>
              <div className="flex items-start gap-3.5">
                <div className="size-11 rounded-2xl grid place-items-center text-white shadow-sm shrink-0" style={{ backgroundImage: `linear-gradient(135deg, ${catC1}, ${catC2})` }}>
                  <Globe className="size-5" />
                </div>
                <div className="min-w-0 max-w-2xl">
                  <div className="text-[11px] font-bold uppercase tracking-wider" style={{ color: catC1 }}>Passo 4 · Integrações</div>
                  <h1 className="text-[1.8rem] font-bold tracking-tight text-[#101828] leading-tight">Integrações</h1>
                  <p className="text-[#667085] mt-1 leading-relaxed">Conecte ferramentas externas que o agente vai usar no atendimento. Por enquanto, a integração disponível é o <strong>ZapSign</strong> (gerar contratos e coletar assinaturas).</p>
                </div>
              </div>

              <div className="mt-8 max-w-3xl space-y-2.5">
                {/* ZapSign */}
                <Card className="p-4 lc-card">
                  <div className="flex items-center gap-4">
                    <img src={zapsignLogo} alt="ZapSign" className="size-11 rounded-xl object-contain shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-bold text-[#101828]">ZapSign</span>
                        {integrations.zapsign?.enabled ? (
                          <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-success/15 text-success border border-success/30 inline-flex items-center gap-1"><Check className="size-2.5" strokeWidth={3} />Conectado</span>
                        ) : (
                          <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-[#f1f5f9] text-[#64748b]">Não conectado</span>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground mt-0.5 line-clamp-1">Contratos personalizados e assinaturas com validade jurídica, direto pelo agente.</p>
                    </div>
                    <Button
                      variant={integrations.zapsign?.enabled ? "outline" : "default"}
                      className={integrations.zapsign?.enabled ? "shrink-0" : "shrink-0 bg-gradient-primary text-white shadow-glow"}
                      onClick={() => setZapsignOpen(true)}
                    >
                      {integrations.zapsign?.enabled ? (<><Settings2 className="size-4 mr-1.5" />Configurar</>) : (<><Plus className="size-4 mr-1.5" />Conectar</>)}
                    </Button>
                  </div>
                </Card>

                {/* Em breve */}
                <div className="text-[10px] font-bold uppercase tracking-wider text-[#98A2B3] pt-3 pb-0.5">Em breve</div>
                {[
                  { logo: advboxLogo, name: "ADV Box", desc: "O software jurídico que reúne a gestão do escritório de advocacia." },
                  { logo: googleCalendarLogo, name: "Google Calendar", desc: "Consulta e agenda eventos de forma automatizada pelos agentes de IA." },
                  { logo: asaasLogo, name: "Asaas", desc: "Cobranças e pagamentos (boleto, Pix, cartão) gerados e acompanhados pelo agente." },
                  { logo: customToolLogo, name: "Custom Tool", desc: "Chamadas de API personalizadas: endpoints, headers, query params e body." },
                ].map((it) => (
                  <Card key={it.name} className="p-4 lc-card border-[#eef1f5] bg-[#fcfdfe]">
                    <div className="flex items-center gap-4">
                      <img src={it.logo} alt={it.name} className="size-11 rounded-xl object-contain shrink-0 opacity-90" />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-[#475467]">{it.name}</span>
                          <span className="text-[9px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-[#eef1f5] text-[#94a3b8]">Em breve</span>
                        </div>
                        <p className="text-xs text-[#98A2B3] mt-0.5 line-clamp-1">{it.desc}</p>
                      </div>
                      <div className="size-9 rounded-lg grid place-items-center text-[#cbd5e1] bg-[#f6f8fb] shrink-0" title="Em breve">
                        <Settings2 className="size-4" />
                      </div>
                    </div>
                  </Card>
                ))}

                <p className="text-[11px] text-[#98A2B3]">A integração com o <strong>ZapSign é obrigatória</strong> para o agente gerar e coletar a assinatura dos contratos — configure-a antes de ativar.</p>
              </div>
            </motion.div>
          )}

          {step === 5 && (
            <motion.div key="s5fu" initial={{ opacity: 0, x: 24, filter: "blur(4px)" }} animate={{ opacity: 1, x: 0, filter: "blur(0px)" }} exit={{ opacity: 0, x: -24, filter: "blur(4px)", transition: STEP_EXIT }} transition={STEP_ENTER}>
              <div className="flex items-start gap-3.5">
                <div className="size-11 rounded-2xl grid place-items-center text-white shadow-sm shrink-0" style={{ backgroundImage: `linear-gradient(135deg, ${catC1}, ${catC2})` }}>
                  <BellRing className="size-5" />
                </div>
                <div className="min-w-0 max-w-2xl">
                  <div className="text-[11px] font-bold uppercase tracking-wider" style={{ color: catC1 }}>Passo 5 · Follow-up</div>
                  <h1 className="text-[1.8rem] font-bold tracking-tight text-[#101828] leading-tight">Follow-up</h1>
                  <p className="text-[#667085] mt-1 leading-relaxed">{fuPrevia?.por_que ?? "Quando o lead para de responder, a IA manda um lembrete curto no tempo de cada tentativa e para sozinha quando ele responde ou a equipe assume."}</p>
                </div>
              </div>

              <div className="mt-8 max-w-3xl space-y-3">
                <Card className="p-4 lc-card">
                  {isEdit && !reativando ? (
                    <div className="flex flex-wrap items-center gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="font-bold text-[#101828]">Follow-up {followupEdicao?.ligado ? "ligado" : "desligado"}</div>
                        <p className="text-xs text-muted-foreground mt-0.5">Cadência: {(followupEdicao?.resumo ?? []).join(", ") || "—"}. Para mudar tempos, mensagens e horário, clique em Configurar follow-up (abre aqui mesmo, sem sair da ativação).</p>
                      </div>
                      {editData?.weaverAgentId && (
                        <Button type="button" variant="outline" size="sm" className="font-semibold" onClick={() => setFollowupPopup(true)}><Settings2 className="size-4 mr-1.5" />Configurar follow-up</Button>
                      )}
                    </div>
                  ) : (
                    <div className="flex items-start gap-4">
                      <div className="flex-1 min-w-0">
                        <Label htmlFor="followup-ativo" className="font-bold text-[#101828]">Ligar o follow-up</Label>
                        <p className="text-xs text-muted-foreground mt-0.5">Quando cada lembrete sai, contado a partir da última mensagem da IA. Até 4 tentativas.</p>
                        {fuPrevia ? (
                          <CadenciaEditavel
                            horas={fuHoras ?? fuPrevia.passos ?? []}
                            desligado={!followupLigado}
                            mudou={!!fuHoras}
                            aoMudar={setFuHoras}
                            aoVoltarPadrao={() => setFuHoras(null)}
                          />
                        ) : (
                          <span className="mt-2 block text-[11px] text-[#98A2B3]">carregando a cadência…</span>
                        )}
                      </div>
                      <Switch id="followup-ativo" checked={followupLigado} onCheckedChange={setFollowupLigado} />
                    </div>
                  )}
                </Card>
                {!(isEdit && !reativando) && !followupLigado && (
                  <Aviso tipo="atencao" titulo="Follow-up desligado">Leads que param de responder não vão receber lembrete. Dá para ligar depois na tela do produto, com o botão “Ligar com o padrão”.</Aviso>
                )}
                <p className="text-[11px] text-[#98A2B3]">O follow-up não manda quando a IA está desligada, quando alguém da equipe assumiu ou falou com o lead, para lead desqualificado ou com contrato assinado, fora do horário comercial (seg. a sáb., 8h às 20h) e, no número oficial, depois de 24 h sem modelo aprovado.</p>
              </div>
            </motion.div>
          )}

          {step === 6 && (
            <motion.div key="s5" initial={{ opacity: 0, x: 24, filter: "blur(4px)" }} animate={{ opacity: 1, x: 0, filter: "blur(0px)" }} exit={{ opacity: 0, x: -24, filter: "blur(4px)", transition: STEP_EXIT }} transition={STEP_ENTER}>
              <h1 className="text-[1.8rem] font-bold tracking-tight text-[#101828]">{reativando ? "Pronto para ativar de novo 🚀" : isEdit ? "Revise o que vai mudar" : podeAtivar ? "Pronto para ativar 🚀" : "Revise antes de ativar"}</h1>
              <p className="text-[#667085] mt-1.5">{isEdit ? "Confira as alterações antes de salvar — elas serão sincronizadas no agente." : podeAtivar ? "Tudo certo — confira o resumo e coloque seu agente em operação." : "Há itens obrigatórios pendentes. Resolva-os para liberar a ativação."}</p>

              {/* MODO EDIÇÃO: diff do que mudou (a "grande jogada") */}
              {isEdit && editChanges && (
                <Card className="mt-6 p-5 lc-card">
                  <div className="flex items-center justify-between mb-3">
                    <div className="text-xs uppercase tracking-widest text-[#98A2B3] font-semibold">O que vai ser atualizado</div>
                    {editChanges.total > 0 ? (
                      <span className="text-[11px] font-bold inline-flex items-center gap-1 px-2 py-0.5 rounded-full border" style={{ backgroundColor: `${catC1}1f`, color: catC1, borderColor: `${catC1}4d` }}>{editChanges.total} alteração{editChanges.total > 1 ? "ões" : ""}</span>
                    ) : (
                      <span className="text-[11px] font-bold inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-muted text-muted-foreground">Nenhuma alteração</span>
                    )}
                  </div>

                  {editChanges.total === 0 ? (
                    <div className="rounded-xl border border-dashed border-border bg-muted/30 p-6 text-center text-sm text-muted-foreground">
                      Você não alterou nada ainda. Volte e edite os prompts, FAQ, comportamento ou o número.
                    </div>
                  ) : (
                    <div className="space-y-4">
                      {/* Prompts alterados — com antes/depois */}
                      {editChanges.promptChanges.length > 0 && (
                        <div>
                          <div className="text-[11px] font-bold uppercase tracking-wider text-[#98A2B3] mb-2">Prompts alterados</div>
                          <div className="space-y-2.5">
                            {editChanges.promptChanges.map((pc) => {
                              const RoleIcon = ROLE_META[pc.role]?.Icon ?? FileSignature;
                              return (
                              <details key={pc.role} className="rounded-xl border border-border bg-muted/20 p-3">
                                <summary className="cursor-pointer text-sm font-semibold flex items-center gap-2">
                                  <span className="size-6 rounded-md grid place-items-center text-white shrink-0" style={{ backgroundImage: `linear-gradient(135deg, ${catC1}, ${catC2})` }}><RoleIcon className="size-3.5" /></span>
                                  {pc.label}
                                  <span className="ml-auto flex items-center gap-2 shrink-0">
                                    {pc.delta !== 0 && (
                                      <span className={`text-[10px] font-bold tabular-nums ${pc.delta > 0 ? "text-success" : "text-destructive"}`}>{pc.delta > 0 ? "+" : ""}{pc.delta} car.</span>
                                    )}
                                    <span className="text-[10px] font-bold text-amber-600">alterado</span>
                                  </span>
                                </summary>
                                <div className="mt-3 grid md:grid-cols-2 gap-2.5">
                                  <div className="rounded-lg border border-border bg-background p-2.5">
                                    <div className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-1">Antes</div>
                                    <pre className="text-[11px] leading-relaxed whitespace-pre-wrap break-words max-h-44 overflow-auto text-muted-foreground">{pc.before || "(vazio)"}</pre>
                                  </div>
                                  <div className="rounded-lg border p-2.5" style={{ borderColor: `${catC1}55`, backgroundColor: `${catC1}0a` }}>
                                    <div className="text-[10px] font-bold uppercase tracking-wider mb-1" style={{ color: catC1 }}>Depois</div>
                                    <pre className="text-[11px] leading-relaxed whitespace-pre-wrap break-words max-h-44 overflow-auto">{pc.after || "(vazio)"}</pre>
                                  </div>
                                </div>
                              </details>
                              );
                            })}
                          </div>
                        </div>
                      )}

                      {/* Demais campos alterados */}
                      {editChanges.changedItems.length > 0 && (
                        <div>
                          <div className="text-[11px] font-bold uppercase tracking-wider text-[#98A2B3] mb-2">Outras alterações</div>
                          <div className="divide-y divide-[#f1f4f8] rounded-xl border border-border">
                            {editChanges.changedItems.map((it) => (
                              <div key={it.key} className="flex items-start gap-3 px-3 py-2.5">
                                <span className="size-6 rounded-md grid place-items-center shrink-0 mt-0.5" style={{ backgroundColor: `${catC1}1f`, color: catC1 }}><Check className="size-3.5" strokeWidth={3} /></span>
                                <div className="flex-1 min-w-0">
                                  <div className="text-sm font-semibold text-[#101828]">{it.label}</div>
                                  <div className="mt-1 flex items-center gap-2 flex-wrap text-xs">
                                    <span className="inline-flex items-center rounded-md bg-muted px-1.5 py-0.5 text-muted-foreground line-through max-w-[46%] truncate" title={(it as any).before}>{(it as any).before}</span>
                                    <ArrowRight className="size-3 text-muted-foreground shrink-0" />
                                    <span className="inline-flex items-center rounded-md px-1.5 py-0.5 font-semibold max-w-[46%] truncate" style={{ backgroundColor: `${catC1}14`, color: catC1 }} title={(it as any).after}>{(it as any).after}</span>
                                  </div>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </Card>
              )}

              {/* Checklist de revisão — valida cada etapa (só no modo ativação) */}
              {!isEdit && (
              <Card className="mt-6 p-5 lc-card">
                <div className="flex items-center justify-between mb-1">
                  <div className="text-xs uppercase tracking-widest text-[#98A2B3] font-semibold">Checklist de ativação</div>
                  {podeAtivar ? (
                    <span className="text-[11px] font-bold inline-flex items-center gap-1 px-2 py-0.5 rounded-full border" style={{ backgroundColor: `${catC1}1f`, color: catC1, borderColor: `${catC1}4d` }}><Check className="size-3" strokeWidth={3} />Tudo pronto</span>
                  ) : (
                    <span className="text-[11px] font-bold inline-flex items-center gap-1 px-2 py-0.5 rounded-full border border-amber-300 bg-amber-50 text-amber-800"><AlertTriangle className="size-3 text-amber-600" />{pendencias.length} pendência{pendencias.length > 1 ? "s" : ""}</span>
                  )}
                </div>
                <div className="divide-y divide-[#f1f4f8]">
                  {revisao.map((it) => {
                    const pend = it.obrig && !it.ok;
                    const dash = it.opcional && it.vazio;
                    return (
                      <div key={it.key} className="flex items-center gap-3 py-2.5">
                        <span className="size-7 rounded-lg grid place-items-center shrink-0" style={pend ? { backgroundColor: "#fef3c7", color: "#d97706" } : dash ? { backgroundColor: "#f1f4f8", color: "#cbd5e1" } : { backgroundColor: `${catC1}1f`, color: catC1 }}>
                          {pend ? <AlertTriangle className="size-3.5" /> : dash ? <span className="text-base leading-none">–</span> : <Check className="size-3.5" strokeWidth={3} />}
                        </span>
                        <div className="flex-1 min-w-0">
                          <div className="text-sm font-semibold text-[#101828] flex items-center gap-1.5">
                            {it.label}
                            {it.opcional && <span className="text-[9px] font-bold uppercase tracking-wider text-[#94a3b8]">opcional</span>}
                          </div>
                          <div className={`text-xs mt-0.5 ${pend ? "text-amber-700 font-medium" : "text-[#667085]"}`}>{it.det}</div>
                        </div>
                        {pend && (
                          <Button size="sm" variant="outline" className="shrink-0 border-amber-300 text-amber-700 hover:bg-amber-50" onClick={it.ir}>Corrigir</Button>
                        )}
                      </div>
                    );
                  })}
                </div>
                {!podeAtivar && (
                  <Aviso tipo="atencao" compacto className="mt-3" titulo="Não dá para ativar ainda">
                    Resolva os itens marcados acima com <strong>Corrigir</strong>. FAQ e Objeções são opcionais e não bloqueiam.
                  </Aviso>
                )}
              </Card>
              )}

              <div className="mt-6 grid md:grid-cols-2 gap-4">
                <Card className="p-5 lc-card">
                  <div className="text-xs uppercase tracking-widest text-[#98A2B3] font-semibold">Identidade</div>
                  <div className="mt-3 space-y-2 text-sm">
                    <Row label="Nome">{name}</Row>
                    <Row label="Baseado em">{template.name} v{template.version}</Row>
                    <Row label="Categoria">{template.category}</Row>
                  </div>
                </Card>
                <Card className="p-5 lc-card">
                  <div className="text-xs uppercase tracking-widest text-[#98A2B3] font-semibold">Configuração</div>
                  <div className="mt-3 space-y-2 text-sm">
                    <Row label="Modelo">{llmModels.find((m) => m.id === selectedModel)?.name}</Row>
                    <Row label="Canais">{selectedChannels.length}</Row>
                  </div>
                </Card>

                <Card className="p-5 lc-card md:col-span-2">
                  <div className="flex items-center justify-between mb-3">
                    <div className="text-xs uppercase tracking-widest text-[#98A2B3] font-semibold">Pipeline · {pipelineAgents.length} agentes</div>
                    <span className="text-[10px] font-bold uppercase tracking-wider text-[#94a3b8]">Funil de atendimento</span>
                  </div>
                  <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
                    {pipelineAgents.map((a, i) => {
                      const meta = ROLE_META[a.role] ?? { label: a.role, Icon: FileSignature } as any;
                      const Icon = meta.Icon;
                      return (
                        <div key={a.role} className="relative flex items-center gap-3 p-3 rounded-xl border border-[#eef1f5] bg-[#fcfdfe]">
                          <div className="absolute top-2 right-2.5 text-[10px] font-bold text-[#cbd5e1]">{i + 1}</div>
                          <div className="size-9 rounded-xl grid place-items-center text-white shrink-0 shadow-sm" style={{ backgroundImage: `linear-gradient(135deg, ${catC1}, ${catC2})` }}>
                            <Icon className="size-[18px]" />
                          </div>
                          <div className="flex-1 min-w-0 pr-3">
                            <div className="text-[13px] font-semibold text-[#101828] truncate" title={a.name}>{a.name}</div>
                            <div className="text-[11px] text-[#98A2B3] truncate inline-flex items-center gap-1">
                              <Check className="size-2.5" strokeWidth={3} style={{ color: catC1 }} />
                              {a.saved ? "Personalizado" : "Configurado"}
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </Card>

                {(!isEdit || reativando) && (
                <Card className="p-5 lc-card md:col-span-2 flex items-center justify-between">
                  <div>
                    <Label className="text-sm font-semibold">Ativar imediatamente</Label>
                    <p className="text-xs text-muted-foreground">{reativando ? "Desligado, o produto fica pausado no número escolhido." : "Desligado, o produto fica como rascunho."}</p>
                  </div>
                  <Switch checked={activateNow} onCheckedChange={setActivateNow} />
                </Card>
                )}

              </div>
            </motion.div>
          )}
          </AnimatePresence>

        <Dialog open={perguntaObjecoes} onOpenChange={setPerguntaObjecoes}>
          <DialogContent className="max-w-lg">
            <DialogHeader className="text-left">
              <DialogTitle className="flex items-center gap-2"><Headphones className="size-5 text-[#0891b2]" />Áudio de objeções não encontrado</DialogTitle>
            </DialogHeader>
            <p className="text-sm text-muted-foreground">
              {objecoesSemAudio.length === 1 ? "Uma objeção ainda não tem" : `${objecoesSemAudio.length} objeções ainda não têm`} áudio gravado.
              Deseja substituir por objeções quebradas em texto?
            </p>
            <ul className="max-h-48 overflow-y-auto rounded-xl border border-border/60 bg-muted/20 p-3 space-y-1 text-[13px]">
              {objecoesSemAudio.map((o) => <li key={o.titulo} className="flex gap-2"><span className="text-[#0891b2]">•</span>{o.titulo}</li>)}
            </ul>
            <p className="text-[12.5px] text-muted-foreground">
              Esses áudios não são obrigatórios: o agente responde essas objeções com o texto curto do roteiro, sem ocupar o
              prompt. Mas, para um desempenho melhor da IA, vale gravar: a sua voz passa mais confiança na hora da dúvida.
              Quando gravar, é só confirmar na Edição rápida de mídias e o áudio volta a valer.
            </p>
            <div className="flex flex-wrap justify-end gap-2 pt-1">
              {roteiro?.total ? <Button variant="outline" onClick={() => { setPerguntaObjecoes(false); void gravarRoteiro(); }}>Gravar agora</Button> : null}
              <Button className="lc-continuar" onClick={() => { objecoesEmTextoOk.current = true; setPerguntaObjecoes(false); depoisDaPergunta.current(); }}>
                Sim, usar em texto
              </Button>
            </div>
          </DialogContent>
        </Dialog>
        <Dialog open={followupPopup} onOpenChange={(v) => { if (!v) void fecharFollowupPopup(); }}>
          <DialogContent className="max-w-5xl w-[calc(100vw-24px)] max-h-[90vh] flex flex-col gap-0 p-0 overflow-hidden">
            <DialogHeader className="p-5 pb-3 text-left">
              <DialogTitle className="flex items-center gap-2"><BellRing className="size-5 text-primary" />Follow-up do agente</DialogTitle>
            </DialogHeader>
            <div className="px-5 pb-5 overflow-y-auto">
              {followupPopup && editData?.weaverAgentId && (
                <AbaFollowup agente={{ id: editData.weaverAgentId, nome: "" } as Agente} />
              )}
            </div>
          </DialogContent>
        </Dialog>
        <ZapsignDialog
          open={zapsignOpen}
          onOpenChange={setZapsignOpen}
          value={integrations.zapsign ?? {}}
          saving={savingTab}
          produtoId={groupId ?? undefined}
          onSave={async (next) => {
            const merged = { ...integrations, zapsign: next };
            setIntegrations(merged);
            await persistGroupField({ integrations: merged }, "ZapSign");
          }}
        />

        <div className="mt-10 flex justify-between">
          <Button variant="outline" onClick={prev} disabled={step === 1}><ArrowLeft className="size-4 mr-1" />Voltar</Button>
          {step === 3 ? (
            <Button
              onClick={async () => {
                await sairDoConteudo();
              }}
              disabled={savingAgent || bootstrapping}
              className="lc-continuar"
            >
              {savingAgent || bootstrapping ? <><Loader2 className="size-4 mr-1.5 animate-spin" />{savingAgent ? "Salvando os agentes…" : "Preparando…"}</>
                : <>Continuar<ArrowRight className="size-4 ml-1" /></>}
            </Button>
          ) : step === 4 ? (
            <Button onClick={() => setStep(5)} className="lc-continuar">
              Continuar<ArrowRight className="size-4 ml-1" />
            </Button>
          ) : step === 5 ? (
            <Button onClick={() => setStep(6)} className="lc-continuar">
              Ir para o resumo<ArrowRight className="size-4 ml-1" />
            </Button>
          ) : step < 4 ? (
            <Button onClick={next} disabled={bootstrapping || (step === 1 && !name.trim())} className="lc-continuar">
              {bootstrapping ? <><Loader2 className="size-4 mr-1.5 animate-spin" />Preparando…</> : <>Continuar<ArrowRight className="size-4 ml-1" /></>}
            </Button>

          ) : (
            <Button onClick={pedirAtivar} disabled={submitting || (isEdit ? (editChanges?.total ?? 0) === 0 : !podeAtivar)} size="lg" className="lc-continuar" title={isEdit ? ((editChanges?.total ?? 0) === 0 ? "Nenhuma alteração para salvar" : "Salvar e sincronizar no agente") : (!podeAtivar ? "Resolva as pendências obrigatórias do checklist antes de continuar" : undefined)}>
              {submitting ? <Loader2 className="size-4 mr-1.5 animate-spin" /> : <Rocket className="size-4 mr-1.5" />}
              {submitting ? (isEdit && !reativando ? "Salvando..." : "Ativando...") : reativando ? (selectedWhatsapp ? "Ativar produto" : "Escolha o número") : isEdit ? `Confirmar e salvar${(editChanges?.total ?? 0) > 0 ? ` (${editChanges?.total})` : ""}` : !podeAtivar ? `${pendencias.length} pendência${pendencias.length > 1 ? "s" : ""}` : "Ativar produto"}
            </Button>
          )}
        </div>
        </div>
        {MOSTRAR_TESTE_RASCUNHO && template && step === 6 && groupId ? (
          <div className="lg:sticky lg:top-[5.5rem] self-start">
            <TestePrompt idProduto={groupId} obterRascunho={obterRascunhoTeste} etapas={etapasTeste} c1={catC1} />
          </div>
        ) : template && step !== 3 && <ActivationSummary template={template} name={name} step={step} />}
        </div>
        )}
      </div>

      {/* Revisar atualização do catálogo (só edição) */}
      {isEdit && template?.id && (
        <RevisarAtualizacao
          open={revisarOpen}
          onOpenChange={setRevisarOpen}
          templateId={template.id}
          versaoCatalogo={editData?.versaoCatalogo}
          objecoesAtuais={objectionItems}
          faqAtuais={faqItems}
          regrasAtuais={generalRules}
          dadosAtuais={dadosEscritorio}
          onAplicar={aplicarAtualizacao}
        />
      )}
    </div>
    </FrasesProdutoProvider>
  );
};

const Row = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <div className="flex justify-between gap-3"><span className="text-muted-foreground">{label}</span><span className="font-semibold text-right">{children}</span></div>
);

/** Item da navegação lateral do passo 3 (Conteúdo). */
const NavRow = ({
  icon, label, hint, active, accent, onClick, disabled,
}: {
  icon: React.ReactNode;
  label: string;
  hint?: string;
  active: boolean;
  accent: string;
  onClick: () => void;
  disabled?: boolean;
}) => (
  <button
    onClick={disabled ? undefined : onClick}
    disabled={disabled}
    title={disabled ? "Em breve" : undefined}
    style={active && !disabled ? { backgroundColor: `${accent}14` } : undefined}
    className={`w-full flex items-center gap-2.5 rounded-xl px-1.5 py-1.5 text-left transition-colors ${
      disabled ? "opacity-50 cursor-not-allowed" : active ? "" : "hover:bg-[#f6f8fb]"
    }`}
  >
    <span
      className="size-8 shrink-0 grid place-items-center rounded-lg transition-colors"
      style={active && !disabled ? { backgroundColor: `${accent}1f`, color: accent } : { backgroundColor: "#f3f5f9", color: "#667085" }}
    >
      {icon}
    </span>
    <span className="min-w-0 flex-1">
      <span className="block text-sm font-semibold truncate" style={active && !disabled ? { color: accent } : { color: "#101828" }}>{label}</span>
      {hint && <span className="block text-[10px] text-[#98A2B3] truncate">{hint}</span>}
    </span>
    {disabled
      ? <span className="text-[9px] font-bold uppercase tracking-wider rounded-full px-1.5 py-0.5 bg-[#f1f5f9] text-[#94a3b8] shrink-0">Em breve</span>
      : active && <span className="size-1.5 rounded-full shrink-0" style={{ backgroundColor: accent }} />}
  </button>
);

const DICAS_CONSTRUCAO = [
  "Depois de ativar, mande uma mensagem do seu celular para o número e veja a IA responder.",
  "No Laboratório do agente você testa o atendimento sem gastar mensagens reais.",
  "O follow-up já vem ligado: lembretes em 1 h, 24 h, 72 h e 7 dias.",
  "Quando a IA não souber seguir, ela passa o caso para a equipe com a ficha pronta.",
];
/** Uma dica por vez, trocando a cada 4,5 s, enquanto o agente é construído. */
function DicaRotativa() {
  const [i, setI] = useState(0);
  useEffect(() => { const t = setInterval(() => setI((n) => (n + 1) % DICAS_CONSTRUCAO.length), 4500); return () => clearInterval(t); }, []);
  return (
    <div className="mt-5 rounded-2xl bg-[#f6fef9] border border-[#d1fadf] px-4 py-3 text-left min-h-[64px]">
      <div className="text-[10.5px] font-bold uppercase tracking-wider text-[#067a2b]">Enquanto isso</div>
      <AnimatePresence mode="wait">
        <motion.p key={i} className="text-[13px] text-[#344054] mt-0.5" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={{ duration: 0.25 }}>
          {DICAS_CONSTRUCAO[i]}
        </motion.p>
      </AnimatePresence>
    </div>
  );
}

const fmtElapsed = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

/** Tela cheia de construção do agente — mostra o progresso real enquanto aguarda o
 *  servidor; se a ativação falhar/expirar, vira tela de ERRO (não volta pro wizard). */
const BuildingOverlay = ({ c1, c2, stage, productName, agentCount, error, onGoProducts, onClose, emoji, categoria }: {
  c1: string; c2: string; stage: number; productName: string; agentCount: number; emoji?: string | null; categoria?: string;
  error?: string | null; onGoProducts: () => void; onClose: () => void;
}) => {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (error) return;
    const iv = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(iv);
  }, [error]);

  const lastIdx = BUILD_STEPS.length - 1;
  const waiting = stage >= lastIdx; // segurando no passo de "aguardando servidor"
  const pct = error ? 100 : Math.round((Math.min(stage + 1, BUILD_STEPS.length) / BUILD_STEPS.length) * 100);

  return (
    <motion.div
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      className="fixed inset-0 z-[60] grid place-items-center p-6"
      style={{ backgroundImage: error ? "linear-gradient(135deg, #b42318, #7a271a)" : "radial-gradient(900px 520px at 18% 12%, rgba(0,188,51,.22), transparent 60%), radial-gradient(800px 520px at 85% 90%, rgba(59,224,98,.14), transparent 60%), linear-gradient(160deg, #0b1220, #101a2e 55%, #0b1220)" }}
    >
      <div className="absolute inset-0 opacity-[.12]" style={{ backgroundImage: "radial-gradient(rgba(255,255,255,.6) 1px, transparent 1px)", backgroundSize: "24px 24px" }} />
      {!error && [0, 1, 2].map((k) => (
        <motion.div key={k} className="absolute rounded-full pointer-events-none" aria-hidden
          style={{ width: 260 + k * 120, height: 260 + k * 120, border: "1px solid rgba(0,188,51,.16)" }}
          animate={{ scale: [0.9, 1.15], opacity: [0.5, 0] }} transition={{ duration: 3.2, repeat: Infinity, ease: "easeOut", delay: k * 1.05 }} />
      ))}
      <motion.div
        key={error ? "err" : "build"}
        initial={{ scale: 0.94, y: 12, opacity: 0 }} animate={{ scale: 1, y: 0, opacity: 1 }}
        transition={{ type: "spring", stiffness: 240, damping: 22 }}
        className="relative w-full max-w-lg rounded-[28px] bg-white/[.97] backdrop-blur-xl p-8 text-center"
        style={{ boxShadow: "0 40px 80px -24px rgba(0,0,0,.55), 0 0 0 1px rgba(255,255,255,.08)" }}
      >
        {error ? (
          <>
            <motion.div className="relative mx-auto size-20 mb-5 rounded-2xl grid place-items-center text-white"
              style={{ backgroundImage: "linear-gradient(135deg, #f04438, #b42318)" }}
              initial={{ rotate: -6, scale: 0.8 }} animate={{ rotate: [0, -5, 5, -3, 0], scale: 1 }} transition={{ duration: 0.6 }}>
              <AlertTriangle className="size-9" />
            </motion.div>
            <div className="text-[11px] font-bold uppercase tracking-wider text-[#b42318]">Não foi possível ativar</div>
            <h2 className="text-xl font-bold tracking-tight text-[#101828] mt-1 truncate">{productName}</h2>
            <p className="text-sm text-[#475467] mt-2 break-words">{error}</p>
            <Aviso tipo="info" compacto className="mt-4 text-left" titulo="Nada foi perdido">
              Suas edições foram <strong>salvas</strong>. O produto está em <strong>Meus Produtos</strong> marcado como <strong>“Erro”</strong> — você pode ajustar e tentar de novo.
            </Aviso>
            <div className="mt-5 flex gap-2">
              <button onClick={onClose} className="flex-1 h-10 rounded-xl border border-[#d0d5dd] text-sm font-semibold text-[#344054] hover:bg-[#f9fafb] transition-colors">Voltar e ajustar</button>
              <button onClick={onGoProducts} className="flex-1 h-10 rounded-xl text-sm font-semibold text-white inline-flex items-center justify-center gap-1.5 shadow-lg" style={{ backgroundImage: "linear-gradient(135deg, #f04438, #b42318)" }}>Ver em Meus Produtos <ArrowRight className="size-4" /></button>
            </div>
          </>
        ) : (
          <>
            {/* Núcleo: o ícone do PRODUTO (emoji e cores do cartão do produto) com anéis e um ponto orbitando */}
            <div className="relative mx-auto size-24 mb-5">
              <motion.div className="absolute inset-0 rounded-[28px] ring-1 ring-inset ring-white/20"
                style={{ backgroundImage: `radial-gradient(130% 90% at 25% 0%, rgba(255,255,255,0.42), rgba(255,255,255,0) 58%), linear-gradient(135deg, ${c1} 0%, ${c2} 100%)`,
                  boxShadow: `inset 0 1px 0 rgba(255,255,255,0.5), inset 0 -4px 10px ${c2}66, 0 18px 40px -14px ${c1}cc` }}
                animate={{ scale: [1, 1.05, 1] }} transition={{ duration: 2.4, repeat: Infinity, ease: "easeInOut" }} />
              <div className="absolute inset-0 grid place-items-center">
                {emoji
                  ? <span className="text-[44px] leading-none drop-shadow-[0_2px_2px_rgba(0,0,0,0.25)]" aria-hidden>{emoji}</span>
                  : (() => { const CatIcon = categoria ? getCategoryIcon(categoria) : null;
                      return CatIcon ? <CatIcon className="size-11 text-white drop-shadow-[0_2px_2px_rgba(0,0,0,0.25)]" strokeWidth={2} />
                        : <img src={iconeLawChat} alt="" className="size-14 drop-shadow" />; })()}
              </div>
              {[0, 1].map((k) => (
                <motion.div key={k} className="absolute -inset-2 rounded-[34px] border-2" style={{ borderColor: `${c1}59` }}
                  animate={{ scale: [1, 1.28], opacity: [0.6, 0] }} transition={{ duration: 1.9, repeat: Infinity, ease: "easeOut", delay: k * 0.95 }} />
              ))}
              <motion.div className="absolute -inset-3" animate={{ rotate: 360 }} transition={{ duration: 3.4, repeat: Infinity, ease: "linear" }}>
                <div className="absolute -top-0.5 left-1/2 -ml-1.5 size-3 rounded-full" style={{ background: c1, boxShadow: `0 0 12px ${c1}` }} />
              </motion.div>
            </div>

            <div className="text-[11px] font-bold uppercase tracking-[.14em]" style={{ color: c2 }}>Construindo seu agente</div>
            <h2 className="text-2xl font-bold tracking-tight text-[#101828] mt-1 truncate">{productName}</h2>
            <p className="text-[13px] text-[#667085] mt-1">
              {waiting ? "Quase lá: aguardando a confirmação do servidor" : "Preparando tudo"} · não feche esta janela
            </p>

            {/* Os agentes do funil aparecendo um a um */}
            <div className="mt-5 flex justify-center gap-2" aria-label={`${agentCount} agentes`}>
              {Array.from({ length: Math.max(1, agentCount) }).map((_, i) => {
                const pronto = i < Math.ceil(((stage + 1) / BUILD_STEPS.length) * Math.max(1, agentCount));
                return (
                  <motion.div key={i} className="size-9 rounded-xl grid place-items-center"
                    initial={{ scale: 0.4, opacity: 0, y: 6 }} animate={{ scale: 1, opacity: 1, y: 0 }} transition={{ delay: 0.15 + i * 0.12, type: "spring", stiffness: 320, damping: 18 }}
                    style={pronto ? { backgroundImage: "linear-gradient(135deg, #3BE062, #00A32C)", color: "#fff", boxShadow: "0 6px 14px -6px rgba(0,163,44,.7)" } : { backgroundColor: "#f2f4f7", color: "#98A2B3" }}>
                    {pronto ? <Check className="size-4" strokeWidth={3} /> : <Bot className="size-4" />}
                  </motion.div>
                );
              })}
            </div>

            {/* Progresso: porcentagem grande + barra com brilho */}
            <div className="mt-6 flex items-end justify-between">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-[#98A2B3]">{waiting ? "Pode levar alguns minutos" : "Progresso"}</span>
              <span className="text-2xl font-bold tabular-nums text-[#101828]">{pct}<span className="text-sm text-[#98A2B3]">%</span></span>
            </div>
            <div className="mt-1.5 h-2.5 rounded-full bg-[#eef1f5] overflow-hidden relative">
              <motion.div className="h-full rounded-full relative overflow-hidden" style={{ backgroundImage: "linear-gradient(90deg, #00A32C, #3BE062)" }}
                initial={{ width: "6%" }} animate={{ width: `${pct}%` }} transition={{ ease: "easeOut", duration: 0.7 }}>
                <motion.div className="absolute inset-0" style={{ backgroundImage: "linear-gradient(90deg, transparent, rgba(255,255,255,.6), transparent)" }}
                  animate={{ x: ["-100%", "220%"] }} transition={{ duration: 1.3, repeat: Infinity, ease: "linear" }} />
              </motion.div>
            </div>
            <div className="mt-1 text-right text-[11px] text-[#98A2B3] tabular-nums">{fmtElapsed(elapsed)}</div>

            {/* Etapas numa linha do tempo */}
            <div className="mt-3 text-left relative">
              <div className="absolute left-[15px] top-4 bottom-4 w-0.5 bg-[#eef1f5]" aria-hidden />
              <motion.div className="absolute left-[15px] top-4 w-0.5 bg-[#00BC33] origin-top" aria-hidden
                animate={{ height: `calc(${(Math.min(stage, lastIdx) / lastIdx) * 100}% - 32px * ${Math.min(stage, lastIdx) / lastIdx})` }} transition={{ duration: 0.6, ease: "easeOut" }} />
              {BUILD_STEPS.map((s, i) => {
                const isDone = i < stage;
                const isActive = i === stage;
                const label = (i === lastIdx && waiting) ? "Aguardando confirmação do servidor" : s.label;
                return (
                  <motion.div key={s.label} className="relative flex items-center gap-3 py-1.5"
                    initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.07 }}>
                    <div className="relative size-8 rounded-full grid place-items-center shrink-0 transition-colors"
                      style={isDone ? { backgroundColor: "#00BC33", color: "#fff" } : isActive ? { backgroundColor: "#fff", color: "#00A32C", boxShadow: "0 0 0 2px #00BC33, 0 0 0 6px rgba(0,188,51,.15)" } : { backgroundColor: "#f2f4f7", color: "#aab2c0" }}>
                      {isDone ? <Check className="size-4" strokeWidth={3} /> : isActive ? <Loader2 className="size-4 animate-spin" /> : <s.Icon className="size-4" />}
                    </div>
                    <span className={`text-[14px] ${isActive ? "font-semibold text-[#101828]" : isDone ? "text-[#344054]" : "text-[#98A2B3]"}`}>{label}</span>
                    {isDone && <span className="ml-auto text-[11px] font-semibold text-[#00A32C]">feito</span>}
                  </motion.div>
                );
              })}
            </div>

            {/* Dicas enquanto espera */}
            <DicaRotativa />
          </>
        )}
      </motion.div>
    </motion.div>
  );
};

export default ProductConfigurator;

/* ----------------------------------------------------------------- cadência do follow-up (ativação) */
const OPCOES_HORAS = [0.25, 0.5, 1, 2, 4, 8, 12, 24, 48, 72, 96, 120, 168, 240, 336, 504, 720];
function rotuloHoras(h: number): string {
  const min = Math.round(h * 60);
  if (min < 60) return `${min} min`;
  if (min % 60) return `${Math.floor(min / 60)} h ${min % 60} min`;
  const hh = min / 60;
  return hh <= 72 || hh % 24 ? `${hh} h` : `${hh / 24} dias`;
}

function CadenciaEditavel({ horas, desligado, mudou, aoMudar, aoVoltarPadrao }: {
  horas: number[]; desligado: boolean; mudou: boolean; aoMudar: (h: number[]) => void; aoVoltarPadrao: () => void;
}) {
  const trocar = (i: number, valor: number) => {
    const novo = [...horas]; novo[i] = valor;
    aoMudar(novo);
  };
  const tirar = (i: number) => aoMudar(horas.filter((_, j) => j !== i));
  const pôr = () => {
    const ultimo = horas[horas.length - 1] ?? 0;
    aoMudar([...horas, OPCOES_HORAS.find((o) => o > ultimo) ?? 720]);
  };
  const foraDeOrdem = horas.some((h, i) => i > 0 && h <= horas[i - 1]);
  return (
    <div className={`mt-2.5 space-y-2 ${desligado ? "opacity-50 pointer-events-none" : ""}`}>
      <div className="flex flex-wrap items-center gap-2" aria-label="Cadência do follow-up">
        {horas.map((h, i) => (
          <div key={i} className="inline-flex items-center gap-1 rounded-lg border border-[#e2e8f0] bg-[#f8fafc] pl-2 pr-1 py-1">
            <span className="text-[11px] font-bold text-[#475467]">{i + 1}ª</span>
            <select
              value={OPCOES_HORAS.includes(h) ? h : ""}
              onChange={(e) => trocar(i, Number(e.target.value))}
              className="h-7 rounded-md border border-[#e2e8f0] bg-white px-1.5 text-[12px] font-semibold text-[#101828]"
              aria-label={`Tempo da ${i + 1}ª tentativa`}
            >
              {!OPCOES_HORAS.includes(h) && <option value="">{rotuloHoras(h)}</option>}
              {OPCOES_HORAS.map((o) => <option key={o} value={o}>{rotuloHoras(o)}</option>)}
            </select>
            {horas.length > 1 && (
              <button type="button" onClick={() => tirar(i)} className="size-6 grid place-items-center rounded-md text-[#98A2B3] hover:text-red-600 hover:bg-red-50" aria-label={`Tirar a ${i + 1}ª tentativa`}>×</button>
            )}
          </div>
        ))}
        {horas.length < 4 && (
          <button type="button" onClick={pôr} className="h-8 px-2.5 rounded-lg border border-dashed border-[#cbd5e1] text-[12px] font-semibold text-[#475467] hover:border-primary hover:text-primary">+ tentativa</button>
        )}
        {mudou && (
          <button type="button" onClick={aoVoltarPadrao} className="text-[11px] font-semibold text-primary underline-offset-2 hover:underline">voltar ao padrão</button>
        )}
      </div>
      {foraDeOrdem && <p className="text-[11px] font-semibold text-red-600">Cada tentativa precisa vir depois da anterior.</p>}
    </div>
  );
}
