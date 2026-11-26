import { useRef, useState, type ReactNode } from "react";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { ArrowLeft, ArrowRight, Braces, Check, Eraser, Layers, Repeat, RotateCcw } from "lucide-react";
import { RichPromptEditor, RichPromptEditorHandle } from "@/components/agent/RichPromptEditor";
import { ROLE_META, AgentRole } from "@/hooks/useProducts";

/** Limites do servidor (app/followup/regras.validar): acima disso o texto seria cortado ao salvar. */
export const LIMITE_PROMPT_FOLLOWUP = 4000;
export const LIMITE_ETAPA_FOLLOWUP = 1500;

const COR = "#00bc33";
const COR2 = "#16a34a";

export interface VariavelFollowup { nome: string; valor: string | null }

interface Props {
  nomeAgente: string;
  prompt: string;
  promptSalvo: string;
  promptPadrao: string;
  porEtapa: Record<string, string>;
  porEtapaSalvo: Record<string, string>;
  /** Instrução de cada etapa no padrão do produto da biblioteca (pode faltar). */
  porEtapaPadrao: Record<string, string>;
  etapas: { codigo: string; nome: string }[];
  variaveis: VariavelFollowup[];
  onPrompt: (texto: string) => void;
  onEtapa: (codigo: string, texto: string) => void;
  /** Botões extras no topo do prompt geral (ex.: "Ver como fica"). */
  acoes?: ReactNode;
  /** Conteúdo extra no fim do prompt geral (ex.: modelo de IA, prévia). */
  rodape?: ReactNode;
}

const limpo = (t: string | undefined | null) => String(t ?? "").replace(/ /g, " ").replace(/\s+/g, " ").trim();

/** Texto simples (uma instrução por linha) -> markdown que o editor mantém linha a linha: sem isso o markdown junta
 *  linhas seguidas num parágrafo só, e a linha com variável sem valor (que o motor tira) levaria o resto junto. */
function paraEditor(texto: string): string {
  const linhas = String(texto ?? "").split("\n");
  const marcador = /^\s*([-*+]\s|\d+[.)]\s|#|>)/;
  let saida = "";
  linhas.forEach((linha, i) => {
    saida += linha;
    if (i === linhas.length - 1) return;
    const proxima = linhas[i + 1];
    saida += linha.trim() && proxima.trim() && !marcador.test(proxima) && !marcador.test(linha) ? "\n\n" : "\n";
  });
  return saida;
}

type Item = { chave: "geral" } | { chave: "etapa"; codigo: string };

/**
 * Editor do prompt do agente de follow-up no mesmo modelo do editor dos agentes do produto (PipelineAgentEditor):
 * lista à esquerda (prompt geral + uma instrução por etapa, como os agentes do funil), editor grande com barra de
 * formatação e contador, variáveis clicáveis e "Restaurar padrão". Grava em config.prompt e config.por_etapa.
 */
export function PromptFollowupEditor({
  nomeAgente, prompt, promptSalvo, promptPadrao, porEtapa, porEtapaSalvo, porEtapaPadrao, etapas, variaveis,
  onPrompt, onEtapa, acoes, rodape,
}: Props) {
  const [item, setItem] = useState<Item>({ chave: "geral" });
  const editorRef = useRef<RichPromptEditorHandle>(null);

  const promptPersonalizado = limpo(prompt) !== limpo(promptPadrao);
  const promptAlterado = limpo(prompt) !== limpo(promptSalvo);
  const estadoEtapa = (codigo: string) => {
    const atual = porEtapa[codigo] ?? "";
    const padrao = porEtapaPadrao[codigo] ?? "";
    return {
      atual, padrao,
      vazia: !limpo(atual),
      personalizada: limpo(atual) !== limpo(padrao),
      alterada: limpo(atual) !== limpo(porEtapaSalvo[codigo]),
    };
  };
  const personalizados = (promptPersonalizado ? 1 : 0) + etapas.filter((e) => estadoEtapa(e.codigo).personalizada).length;
  const naoSalvos = (promptAlterado ? 1 : 0) + etapas.filter((e) => estadoEtapa(e.codigo).alterada).length;

  const indiceEtapa = item.chave === "etapa" ? etapas.findIndex((e) => e.codigo === item.codigo) : -1;
  const etapaAtual = indiceEtapa >= 0 ? etapas[indiceEtapa] : null;
  const ir = (i: number) => setItem(i < 0 ? { chave: "geral" } : { chave: "etapa", codigo: etapas[Math.min(i, etapas.length - 1)].codigo });
  const posicao = item.chave === "geral" ? 0 : indiceEtapa + 1;
  const total = etapas.length + 1;

  const Selo = ({ tipo }: { tipo: "padrao" | "personalizado" | "vazio" | "naosalvo" }) => {
    const estilo = {
      padrao: { bg: "#f1f5f9", fg: "#64748b", txt: "Padrão" },
      personalizado: { bg: `${COR}1a`, fg: COR2, txt: "Personalizado" },
      vazio: { bg: "#f8fafc", fg: "#98A2B3", txt: "Sem instrução" },
      naosalvo: { bg: "#fff7ed", fg: "#c2410c", txt: "Alterado · não salvo" },
    }[tipo];
    return <span className="text-[10px] font-bold uppercase tracking-wider rounded-full px-2 py-0.5" style={{ backgroundColor: estilo.bg, color: estilo.fg }}>{estilo.txt}</span>;
  };

  const ItemNav = ({ ativo, icone, rotulo, status, custom, aoClicar, naoSalvo }: {
    ativo: boolean; icone: ReactNode; rotulo: string; status: string; custom: boolean; aoClicar: () => void; naoSalvo: boolean;
  }) => (
    <button type="button" onClick={aoClicar} style={ativo ? { backgroundColor: `${COR}14` } : undefined}
      className={`relative w-full flex items-center gap-2.5 rounded-xl px-1.5 py-1.5 text-left transition-colors ${ativo ? "" : "hover:bg-[#f6f8fb]"}`}>
      <div className="relative z-10 shrink-0">
        <div className="size-8 rounded-lg grid place-items-center shadow-sm ring-2 ring-white transition-colors"
          style={custom ? { backgroundImage: `linear-gradient(135deg, ${COR}, ${COR2})`, color: "#fff" } : { backgroundColor: "#eef1f6", color: "#aab2c0" }}>
          {icone}
        </div>
        {custom && (
          <span className="absolute -bottom-1 -right-1 size-3.5 rounded-full bg-white grid place-items-center shadow-sm" title="Personalizado">
            <Check className="size-2.5" style={{ color: COR }} strokeWidth={3.5} />
          </span>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-sm font-semibold truncate" style={{ color: ativo ? COR2 : custom ? "#101828" : "#475467" }}>{rotulo}</div>
        <div className="text-[10px] truncate" style={{ color: ativo ? COR2 : "#98A2B3" }}>{ativo ? "Editando…" : status}</div>
      </div>
      {naoSalvo && <span className="size-1.5 rounded-full shrink-0 bg-[#f97316]" title="Alterado, não salvo" />}
      {!naoSalvo && ativo && <span className="size-1.5 rounded-full shrink-0" style={{ backgroundColor: COR }} />}
    </button>
  );

  // O que está no editor agora (geral ou a etapa escolhida).
  const geral = item.chave === "geral" || !etapaAtual;
  const est = etapaAtual ? estadoEtapa(etapaAtual.codigo) : null;
  const texto = geral ? prompt : est!.atual;
  const limite = geral ? LIMITE_PROMPT_FOLLOWUP : LIMITE_ETAPA_FOLLOWUP;
  const passou = texto.length > limite;
  const mudar = (t: string) => (geral ? onPrompt(t) : onEtapa(etapaAtual!.codigo, t));
  const MetaIcone = etapaAtual ? (ROLE_META[etapaAtual.codigo as AgentRole]?.Icon ?? Layers) : Repeat;

  return (
    <div className="grid lg:grid-cols-[248px_minmax(0,1fr)] gap-6 items-start">
      {/* Lista: prompt geral + uma instrução por etapa (como os agentes do funil no editor do produto) */}
      <nav className="lg:sticky lg:top-[5.5rem] rounded-2xl border border-[#E6EAF0] bg-white p-3 shadow-[0_1px_2px_rgba(16,24,40,.04)]">
        <div className="px-1.5 pb-3 mb-1 border-b border-[#f0f2f6]">
          <div className="text-[13px] font-bold text-[#101828]">Prompt do follow-up</div>
          <div className="text-[11px] text-[#98A2B3] mt-0.5">
            {naoSalvos > 0
              ? <><span className="font-semibold text-[#c2410c]">{naoSalvos}</span> {naoSalvos > 1 ? "partes alteradas" : "parte alterada"}, falta salvar</>
              : personalizados > 0
                ? <><span className="font-semibold" style={{ color: COR2 }}>{personalizados}</span> {personalizados > 1 ? "partes personalizadas" : "parte personalizada"}</>
                : "Tudo no padrão"}
          </div>
        </div>

        <div className="px-1.5 pt-3 pb-1.5 text-[10px] font-bold uppercase tracking-wider text-[#98A2B3]">Geral</div>
        <ItemNav ativo={item.chave === "geral"} icone={<Repeat className="size-4" />} rotulo="Como retomar" custom={promptPersonalizado}
          status={promptPersonalizado ? "Personalizado" : "Padrão"} naoSalvo={promptAlterado} aoClicar={() => setItem({ chave: "geral" })} />

        {etapas.length > 0 && <>
          <div className="px-1.5 pt-3 pb-1.5 text-[10px] font-bold uppercase tracking-wider text-[#98A2B3]">Instrução por etapa</div>
          <div className="relative">
            <div className="absolute left-[23px] top-5 bottom-5 w-px bg-[#E8ECF2]" aria-hidden />
            {etapas.map((e) => {
              const s = estadoEtapa(e.codigo);
              const Icone = ROLE_META[e.codigo as AgentRole]?.Icon ?? Layers;
              return <ItemNav key={e.codigo} ativo={item.chave === "etapa" && item.codigo === e.codigo} icone={<Icone className="size-4" />}
                rotulo={e.nome} custom={!s.vazia} naoSalvo={s.alterada}
                status={s.vazia ? "Sem instrução extra" : s.personalizada ? "Personalizado" : "Padrão do produto"}
                aoClicar={() => setItem({ chave: "etapa", codigo: e.codigo })} />;
            })}
          </div>
        </>}

        <div className="mt-3 rounded-lg bg-[#f6f8fb] px-3 py-2 text-[10px] leading-relaxed text-[#667085] flex items-center gap-1.5">
          <Check className="size-3 shrink-0" style={{ color: COR }} /> Nada vale até clicar em Salvar follow-up.
        </div>
      </nav>

      <div className="min-w-0 space-y-4">
        {/* Faixa de contexto/navegação — igual ao editor dos agentes */}
        <div className="flex items-center justify-between gap-3">
          <div className="text-[11px] font-semibold text-[#667085]">
            <span style={{ color: COR2 }}>Editando</span> · parte {posicao + 1} de {total}
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            <Button variant="outline" size="sm" onClick={() => ir(indiceEtapa - 1)} disabled={geral}>
              <ArrowLeft className="size-4 mr-1" />Anterior
            </Button>
            <Button variant="outline" size="sm" onClick={() => ir(indiceEtapa + 1)} disabled={posicao === total - 1}>
              Próximo<ArrowRight className="size-4 ml-1" />
            </Button>
          </div>
        </div>

        <Card className="lc-card p-0 overflow-hidden">
          {/* Identidade */}
          <div className="flex items-center gap-3 p-5">
            <div className="size-12 rounded-2xl grid place-items-center text-white shadow-sm shrink-0"
              style={{ backgroundImage: `linear-gradient(135deg, ${COR}, ${COR2})` }}>
              <MetaIcone className="size-6" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-[10px] uppercase tracking-wider font-bold" style={{ color: COR }}>
                {geral ? "Agente de follow-up" : "Follow-up da etapa"}
              </div>
              <div className="mt-0.5 flex items-center gap-2 flex-wrap">
                <div className="text-base font-bold text-[#101828] truncate">{geral ? `Retomadas de ${nomeAgente}` : etapaAtual!.nome}</div>
                {geral
                  ? <Selo tipo={promptPersonalizado ? "personalizado" : "padrao"} />
                  : <Selo tipo={est!.vazia ? "vazio" : est!.personalizada ? "personalizado" : "padrao"} />}
                {(geral ? promptAlterado : est!.alterada) && <Selo tipo="naosalvo" />}
              </div>
            </div>
          </div>

          {/* Prompt */}
          <div className="px-5 pb-5 pt-4 border-t border-[#eef1f5]">
            <div className="flex items-center justify-between mb-2.5 flex-wrap gap-2">
              <div className="min-w-0">
                <Label className="text-sm font-semibold text-[#101828]">
                  {geral ? "Prompt do agente de follow-up" : `Instrução extra · ${etapaAtual!.nome}`}
                </Label>
                <p className="text-xs text-muted-foreground mt-0.5 max-w-[640px]">
                  {geral
                    ? <>Vale em todas as etapas. O agente de follow-up lê a conversa, decide se retoma agora e diz por onde; quem escreve a mensagem é o agente da etapa, com a voz de {nomeAgente}. Use a barra para formatar.</>
                    : <>Entra junto do prompt geral só quando o lead parou nesta etapa. Ex.: lembrar que os honorários só são pagos no final. Vazio = só o prompt geral.</>}
                </p>
              </div>
              <div className="flex gap-2 flex-wrap">
                {geral ? (
                  <Button size="sm" variant="outline" disabled={!promptPersonalizado} onClick={() => onPrompt(promptPadrao)}
                    title="Volta ao prompt padrão do sistema (só vale depois de salvar)">
                    <RotateCcw className="size-3.5 mr-1.5" />Restaurar padrão
                  </Button>
                ) : (
                  <>
                    {est!.padrao && (
                      <Button size="sm" variant="outline" disabled={!est!.personalizada} onClick={() => onEtapa(etapaAtual!.codigo, est!.padrao)}
                        title="Volta à instrução padrão do produto para esta etapa">
                        <RotateCcw className="size-3.5 mr-1.5" />Restaurar padrão
                      </Button>
                    )}
                    <Button size="sm" variant="outline" disabled={est!.vazia} onClick={() => onEtapa(etapaAtual!.codigo, "")}
                      title="Tira a instrução extra desta etapa">
                      <Eraser className="size-3.5 mr-1.5" />Limpar
                    </Button>
                  </>
                )}
                {geral && acoes}
              </div>
            </div>

            <RichPromptEditor
              key={geral ? "geral" : etapaAtual!.codigo}
              ref={editorRef}
              value={paraEditor(texto)}
              onChange={mudar}
              accent={COR}
              max={limite}
              semMidia
              minHeight={geral ? "min-h-[280px]" : "min-h-[160px]"}
            />
            {passou && (
              <p className="mt-1.5 text-[11px] font-semibold text-[#dc2626]">
                Passou do limite de {limite.toLocaleString("pt-BR")} caracteres: encurte o texto para conseguir salvar.
              </p>
            )}

            {/* Legenda */}
            <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-[#98A2B3]">
              <span><code className="text-[#7c3aed]">{"{{ }}"}</code> variável (o sistema troca pelo valor na hora de enviar)</span>
              <span>Sem link, mídia ou transferência: a retomada só conversa</span>
            </div>

            {/* Variáveis que o motor de follow-up preenche (app/followup/agente.valores) */}
            {variaveis.length > 0 && (
              <div className="mt-3 rounded-xl border border-[#ece9fb] bg-[#faf8ff] p-3">
                <div className="flex items-center gap-1.5">
                  <Braces className="size-3.5 text-[#7c3aed]" />
                  <span className="text-[11px] font-bold uppercase tracking-wider text-[#7c3aed]">Variáveis disponíveis</span>
                  <span className="text-[10px] font-bold rounded-full px-1.5 py-0.5 bg-[#ede9fe] text-[#7c3aed]">{variaveis.length}</span>
                </div>
                <p className="text-[11px] text-[#98A2B3] mt-1 mb-2.5">
                  Clique para inserir onde está o cursor. Linha com variável sem valor sai inteira do prompt na hora de enviar.
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {variaveis.map((v) => (
                    <button key={v.nome} type="button"
                      onMouseDown={(e) => { e.preventDefault(); editorRef.current?.insertText(`{{${v.nome}}}`); }}
                      title={v.valor ? `Agora vale: ${v.valor}` : "Ainda sem valor: preencha nos dados do agente"}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-[#e6ddfb] bg-white px-2 py-1 text-left hover:bg-[#ede9fe] transition-colors">
                      <code className="text-[11px] font-semibold text-[#7c3aed]">{`{{${v.nome}}}`}</code>
                      <span className={`text-[10px] max-w-[160px] truncate ${v.valor ? "text-[#667085]" : "text-[#c2410c] font-semibold"}`}>
                        {v.valor ?? "sem valor"}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {geral && rodape && <div className="mt-4">{rodape}</div>}
          </div>
        </Card>
      </div>
    </div>
  );
}
