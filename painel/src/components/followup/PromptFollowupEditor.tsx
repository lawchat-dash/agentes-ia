import { useRef, useState, type ReactNode } from "react";
import { Braces, Check, Eraser, Layers, Repeat, RotateCcw } from "lucide-react";
import { RichPromptEditor, RichPromptEditorHandle } from "@/components/agent/RichPromptEditor";
import { ROLE_META, AgentRole } from "@/hooks/useProducts";

/** Limites do servidor (app/followup/regras.validar): acima disso o texto seria cortado ao salvar. */
export const LIMITE_PROMPT_FOLLOWUP = 4000;
export const LIMITE_ETAPA_FOLLOWUP = 1500;

const COR = "#00bc33";

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
  /** Conteúdo extra no fim do editor (ex.: modelo de IA e "decide antes de enviar"). */
  rodape?: ReactNode;
  /** Coluna da direita: como o lead recebe (celular com o exemplo). */
  previa?: ReactNode;
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
 * Editor do prompt do agente de follow-up (aba Mensagens): lista à esquerda (como retomar + uma instrução por etapa),
 * editor com barra de formatação, contador e menu @ de variáveis, e o celular "Como o lead recebe" à direita.
 * Grava em config.prompt e config.por_etapa. Visual nas classes fu2-* (estilo-automacao.css).
 */
export function PromptFollowupEditor({
  nomeAgente, prompt, promptSalvo, promptPadrao, porEtapa, porEtapaSalvo, porEtapaPadrao, etapas, variaveis,
  onPrompt, onEtapa, acoes, rodape, previa,
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

  const Selo = ({ tipo }: { tipo: "padrao" | "personalizado" | "vazio" | "naosalvo" }) => {
    const txt = { padrao: "Padrão", personalizado: "Personalizado", vazio: "Sem instrução", naosalvo: "Alterado · não salvo" }[tipo];
    return <span className={`fu2-selo ${tipo}`}>{txt}</span>;
  };

  const ItemNav = ({ ativo, icone, rotulo, status, custom, aoClicar, naoSalvo }: {
    ativo: boolean; icone: ReactNode; rotulo: string; status: string; custom: boolean; aoClicar: () => void; naoSalvo: boolean;
  }) => (
    <button type="button" onClick={aoClicar} className={ativo ? "on" : ""} aria-current={ativo ? "true" : undefined}>
      <span className="fu2-chip">{icone}</span>
      <div className="nome"><b>{rotulo}</b><small className={custom ? "pers" : ""}>{status}</small></div>
      {naoSalvo && <span className="ponto" title="Alterado, não salvo" />}
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
    <div className={`fu2-msg${previa ? " com-cel" : ""}`}>
      {/* Lista: como retomar (geral) + uma instrução por etapa */}
      <nav className="fu2-card fu2-lista-et" aria-label="Partes do prompt do follow-up">
        <div className="fu2-lista-cab"><b>Prompt do follow-up</b>
          <small>{naoSalvos > 0
            ? <><em className="laranja">{naoSalvos}</em> {naoSalvos > 1 ? "partes alteradas" : "parte alterada"}, falta salvar</>
            : personalizados > 0
              ? <><em>{personalizados}</em> {personalizados > 1 ? "partes personalizadas" : "parte personalizada"}</>
              : "Tudo no padrão"}</small></div>
        <div className="fu2-grupo">Geral</div>
        <ItemNav ativo={geral} icone={<Repeat size={16} />} rotulo="Como retomar" custom={promptPersonalizado}
          status={promptPersonalizado ? "Personalizado" : "Padrão LawChat"} naoSalvo={promptAlterado} aoClicar={() => setItem({ chave: "geral" })} />
        {etapas.length > 0 && <div className="fu2-grupo">Por etapa</div>}
        {etapas.map((e) => {
          const s = estadoEtapa(e.codigo);
          const Icone = ROLE_META[e.codigo as AgentRole]?.Icon ?? Layers;
          return <ItemNav key={e.codigo} ativo={!geral && etapaAtual?.codigo === e.codigo} icone={<Icone size={16} />}
            rotulo={e.nome} custom={!s.vazia && s.personalizada} naoSalvo={s.alterada}
            status={s.vazia ? "Sem instrução extra" : s.personalizada ? "Personalizado" : "Padrão do produto"}
            aoClicar={() => setItem({ chave: "etapa", codigo: e.codigo })} />;
        })}
        <div className="fu2-lista-pe"><Check size={12} />Nada vale até clicar em Salvar follow-up.</div>
      </nav>

      <div className="fu2-card fu2-editor">
        <div className="fu2-editor-topo">
          <span className="fu2-chip lg"><MetaIcone size={20} /></span>
          <div className="tt">
            <small>{geral ? "Vale em todas as etapas" : "Instrução da etapa · soma ao geral"}</small>
            <b>{geral ? (nomeAgente ? `Como ${nomeAgente} retoma a conversa` : "Como retomar a conversa") : etapaAtual!.nome}
              {geral ? <Selo tipo={promptPersonalizado ? "personalizado" : "padrao"} />
                : <Selo tipo={est!.vazia ? "vazio" : est!.personalizada ? "personalizado" : "padrao"} />}
              {(geral ? promptAlterado : est!.alterada) && <Selo tipo="naosalvo" />}</b>
          </div>
          <div className="acoes">
            {geral ? (
              <button type="button" className="fu2-btn-borda" disabled={!promptPersonalizado} onClick={() => onPrompt(promptPadrao)}
                title="Volta ao prompt padrão do sistema (só vale depois de salvar)"><RotateCcw size={14} />Restaurar padrão</button>
            ) : (
              <>
                {est!.padrao && (
                  <button type="button" className="fu2-btn-borda" disabled={!est!.personalizada} onClick={() => onEtapa(etapaAtual!.codigo, est!.padrao)}
                    title="Volta à instrução padrão do produto para esta etapa"><RotateCcw size={14} />Restaurar padrão</button>
                )}
                <button type="button" className="fu2-btn-borda" disabled={est!.vazia} onClick={() => onEtapa(etapaAtual!.codigo, "")}
                  title="Tira a instrução extra desta etapa"><Eraser size={14} />Limpar</button>
              </>
            )}
            {geral && acoes}
          </div>
        </div>

        <div className="fu2-editor-corpo">
          <p className="fu2-editor-ajuda">{geral
            ? <>O agente de follow-up lê a conversa, decide se retoma agora e diz por onde; quem escreve a mensagem é o agente da etapa{nomeAgente ? <>, com a voz de {nomeAgente}</> : null}.</>
            : <>Entra junto do prompt geral só quando o lead parou nesta etapa. Ex.: lembrar que os honorários só são pagos no final. Vazio = só o prompt geral.</>}</p>

          <RichPromptEditor
            key={geral ? "geral" : etapaAtual!.codigo}
            ref={editorRef}
            value={paraEditor(texto)}
            onChange={mudar}
            accent={COR}
            max={limite}
            semMidia
            variaveis={variaveis}
            minHeight={geral ? "min-h-[280px]" : "min-h-[160px]"}
          />
          {passou && <p className="fu2-erro solto">Passou do limite de {limite.toLocaleString("pt-BR")} caracteres: encurte o texto para conseguir salvar.</p>}

          <div className="fu2-legenda">
            <span>Digite <code>@</code> para inserir uma variável · <code>{"{{ }}"}</code> o sistema troca pelo valor na hora de enviar</span>
            <span>Sem link, mídia ou transferência: a retomada só conversa</span>
          </div>

          {/* Variáveis que o motor de follow-up preenche (app/followup/agente.valores) */}
          {variaveis.length > 0 && (
            <div className="fu2-vars">
              <b><Braces size={13} />Variáveis <em>{variaveis.length}</em></b>
              <p>Clique para inserir onde está o cursor. Linha com variável sem valor sai inteira do prompt na hora de enviar.</p>
              <div className="lst">
                {variaveis.map((v) => (
                  <button key={v.nome} type="button"
                    onMouseDown={(e) => { e.preventDefault(); editorRef.current?.insertText(`{{${v.nome}}}`); }}
                    title={v.valor ? `Agora vale: ${v.valor}` : "Ainda sem valor: preencha nos dados do agente"}>
                    <code>{`{{${v.nome}}}`}</code>
                    <em className={v.valor ? "" : "sem"}>{v.valor ?? "sem valor"}</em>
                  </button>
                ))}
              </div>
            </div>
          )}

          {rodape && <div className="fu2-editor-rodape">{rodape}</div>}
        </div>
      </div>
      {previa && <aside className="fu2-cel-col">{previa}</aside>}
    </div>
  );
}
