import { Fragment, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { CalendarClock, Eye, Plus, Power, RotateCcw, Save, Settings2, Trash2, Undo2 } from "lucide-react";
import { api, enviar, quando, type Agente } from "../api";
import { Alerta, Carregando, Interruptor, Painel, Vazio, useAcao, useAvisar, useCarregar } from "../componentes/ui";
import { useSessao } from "../sessao";
import { DashboardFollowup, HistoricoFollowup } from "./Followup";
import { Button } from "@/components/ui/button";
import { LIMITE_ETAPA_FOLLOWUP, LIMITE_PROMPT_FOLLOWUP, PromptFollowupEditor, type VariavelFollowup } from "@/components/followup/PromptFollowupEditor";

// Backend: GET/PUT /agentes/:id/followup (app/gestao/rotas.py), motor em app/followup/ (regras.validar é quem manda).
interface Passo { apos_horas: number; modo: "ia" | "texto" | "modelo"; instrucao: string; texto: string }
interface Limites { max_toques_sem_resposta: number; oferecer_parar: boolean; lead_parado_apos: number }
interface Config {
  ativo: boolean; horario: { inicio: number; fim: number; dias: number[] }; intervalo_minimo_min: number; etapas: string[];
  prompt: string; por_etapa: Record<string, string>; passos: Passo[]; modelo_oficial: { id_modelo?: string; nome?: string };
  desistir: { ativo: boolean; apos_horas: number; nota: string }; modelo: string | null;
  decidir?: boolean;   // o agente de follow-up decide antes (enviar, adiar se o lead pediu para esperar, não enviar)
  limites?: Limites;   // regras da OAB e da Meta (quem ligou com o padrão novo)
}
interface Linha { passo: number; situacao: string; motivo: string | null; motivo_texto?: string | null; nome: string | null; desistencia?: boolean }
interface Dados {
  config: Config; configurado?: boolean;
  padrao: { prompt: string; cadencia: number[]; instrucoes: Record<string, string>; por_etapa?: Record<string, string> };
  variaveis?: VariavelFollowup[];
  etapas: { codigo: string; nome: string; tipo: string; pode_followup?: boolean }[]; tipo_canal: string;
  proximos: (Linha & { agendado_para: string; final: string })[];
  recentes: (Linha & { enviado_em: string | null; atualizado_em: string; mensagens: unknown })[];
}
type Resposta = Config & { reprogramacao?: { reprogramados: number; cancelados: number } };

const DIAS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"];
const SEM_FOLLOWUP = new Set(["desqualificado", "contrato_assinado"]);
const MIN_H = 10 / 60;
const MAX_H = 24 * 90;

type Unidade = "minutos" | "horas" | "dias";
const FATOR: Record<Unidade, number> = { minutos: 1 / 60, horas: 1, dias: 24 };
function unidade(horas: number): [number, Unidade] {
  if (!Number.isFinite(horas) || horas <= 0) return [0, "horas"];
  const minutos = Math.round(horas * 60);
  if (minutos < 60 || minutos % 60) return [minutos, "minutos"];
  if (horas >= 24 && horas % 24 === 0) return [horas / 24, "dias"];
  return [Math.round(horas), "horas"];
}
/** "30 min", "1 hora", "3 dias". */
export function tempoLegivel(h: number): string {
  const [n, u] = unidade(h);
  if (u === "minutos") return `${n} min`;
  if (u === "horas") return `${n} ${n === 1 ? "hora" : "horas"}`;
  return `${n} ${n === 1 ? "dia" : "dias"}`;
}
const juntar = (itens: string[]) => (itens.length <= 1 ? itens.join("") : `${itens.slice(0, -1).join(", ")} e ${itens[itens.length - 1]}`);
function diasLegiveis(dias: number[]): string {
  const d = [...dias].sort();
  if (d.length === 7) return "todos os dias";
  if (d.join() === "0,1,2,3,4") return "segunda a sexta";
  if (d.join() === "0,1,2,3,4,5") return "segunda a sábado";
  return juntar(d.map((i) => DIAS[i]));
}

/** Conferência antes de salvar, com a mesma regra do servidor (regras.validar), para a mensagem sair clara na hora. */
function conferir(c: Config, tipoCanal: string): string | null {
  if (c.passos.length === 0) return "Coloque pelo menos uma tentativa na cadência.";
  if (c.passos.length > 12) return "No máximo 12 tentativas.";
  for (const [i, p] of c.passos.entries()) {
    if (!Number.isFinite(p.apos_horas) || p.apos_horas < MIN_H - 1e-9 || p.apos_horas > MAX_H)
      return `A tentativa ${i + 1} precisa de um tempo entre 10 minutos e 90 dias.`;
  }
  const tempos = c.passos.map((p) => Math.round(p.apos_horas * 60));
  const repetido = tempos.findIndex((t, i) => tempos.indexOf(t) !== i);
  if (repetido >= 0) return `As tentativas ${tempos.indexOf(tempos[repetido]) + 1} e ${repetido + 1} estão com o mesmo tempo. Cada uma precisa de um tempo diferente.`;
  if (!(c.horario.inicio < c.horario.fim)) return "Horário permitido: o início precisa ser antes do fim.";
  if (c.horario.dias.length === 0) return "Escolha pelo menos um dia da semana para enviar.";
  if (!Number.isFinite(c.intervalo_minimo_min) || c.intervalo_minimo_min < 5 || c.intervalo_minimo_min > 1440)
    return "Intervalo mínimo entre mensagens: de 5 a 1440 minutos.";
  if (c.desistir.ativo && !(c.desistir.apos_horas >= 1)) return "Desistir do lead: espere pelo menos 1 hora depois da última tentativa.";
  if (c.prompt.length > LIMITE_PROMPT_FOLLOWUP)
    return `O prompt do follow-up passou de ${LIMITE_PROMPT_FOLLOWUP.toLocaleString("pt-BR")} caracteres. Encurte para salvar.`;
  const longa = Object.entries(c.por_etapa).find(([, t]) => (t ?? "").length > LIMITE_ETAPA_FOLLOWUP);
  if (longa) return `A instrução de uma etapa passou de ${LIMITE_ETAPA_FOLLOWUP.toLocaleString("pt-BR")} caracteres. Encurte para salvar.`;
  if (c.ativo && tipoCanal === "oficial" && !c.modelo_oficial.id_modelo)
    return "Número da API oficial: escolha o modelo aprovado (em \"Desistir e número oficial\") antes de ligar.";
  return null;
}

/** O que vai para o servidor: tentativas em ordem, todas escritas pela IA (sem texto fixo). */
const paraSalvar = (c: Config): Config => ({
  ...c, passos: [...c.passos].sort((a, b) => a.apos_horas - b.apos_horas).map((p) => ({ ...p, modo: "ia", texto: "" })),
});

function avisoDoSalvar(r: Resposta): string {
  const partes = [r.ativo ? "Follow-up salvo e ligado." : "Follow-up salvo (desligado)."];
  const rp = r.reprogramacao;
  if (r.ativo && rp?.reprogramados) partes.push(`${rp.reprogramados} agendado(s) passaram para a cadência nova.`);
  if (rp?.cancelados) partes.push(`${rp.cancelados} agendado(s) cancelado(s).`);
  if (r.ativo && !rp?.reprogramados) partes.push("Vale para cada lead a partir da próxima resposta da IA.");
  return partes.join(" ");
}

/** Resumo em palavras: "4 tentativas: 1 hora, 24 horas, 3 dias e 7 dias depois da última resposta da IA". */
function resumoDaConfig(c: Config, etapas: Dados["etapas"]): string[] {
  const passos = [...c.passos].sort((a, b) => a.apos_horas - b.apos_horas);
  const possiveis = etapas.filter((e) => e.pode_followup ?? (e.tipo === "conversa" && !SEM_FOLLOWUP.has(e.codigo)));
  const escolhidas = c.etapas.length ? possiveis.filter((e) => c.etapas.includes(e.codigo)) : possiveis;
  const linhas = [
    `${passos.length} ${passos.length === 1 ? "tentativa" : "tentativas"}: ${juntar(passos.map((p) => tempoLegivel(p.apos_horas)))} depois da última resposta da IA, se o lead não responder.`,
    `Envia de ${c.horario.inicio}h às ${c.horario.fim}h (Brasília), ${diasLegiveis(c.horario.dias)}.`,
    c.etapas.length ? `Só nas etapas: ${juntar(escolhidas.map((e) => e.nome))}.` : `Em todas as etapas de conversa (${juntar(possiveis.map((e) => e.nome))}).`,
  ];
  if (c.limites?.max_toques_sem_resposta) linhas.push(`Quem nunca respondeu à IA recebe no máximo ${c.limites.max_toques_sem_resposta}.`);
  linhas.push(c.desistir.ativo ? `Sem resposta ${tempoLegivel(c.desistir.apos_horas)} depois da última: a IA encerra a conversa.` : "Depois da última tentativa, a conversa fica como está.");
  return linhas;
}

// =========================================================================== página Follow-up do agente
/** Follow-up do agente num lugar só: ligar/desligar, cadência, horário, etapas, mensagem, agendados e histórico. */
export function AbaFollowup({ agente }: { agente: Agente }) {
  const { dados, erro, recarregar } = useCarregar<Dados>(`/agentes/${agente.id}/followup`, [], { guardar: false }); // formulário
  const modelos = useCarregar<{ id: string; nome: string; texto: string }[]>(dados?.tipo_canal === "oficial" ? "/integracoes/helena/modelos-aprovados" : null, [dados?.tipo_canal]);
  const { ocupado, executar } = useAcao();
  const avisar = useAvisar();
  const { catalogo } = useSessao();
  const [c, setC] = useState<Config | null>(null);
  const [previas, setPrevias] = useState<Record<number, string[]>>({});
  const [dias, setDias] = useState(30);
  const [verHistorico, setVerHistorico] = useState(false);
  useEffect(() => { if (dados) setC(dados.config); }, [dados]);
  const mudou = useMemo(() => Boolean(dados && c && JSON.stringify(paraSalvar(c)) !== JSON.stringify(paraSalvar(dados.config))), [dados, c]);
  // Sair da página com alteração não salva: o navegador pergunta antes.
  useEffect(() => {
    if (!mudou) return;
    const segurar = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", segurar);
    return () => window.removeEventListener("beforeunload", segurar);
  }, [mudou]);

  if (!dados || !c) return (
    <div className="stack">
      <Carregando erro={erro ? `Não deu para abrir a configuração do follow-up: ${erro}` : null} />
      {erro && <Painel titulo="Histórico do follow-up"><HistoricoFollowup dias={30} agente={agente.id} compacto /></Painel>}
    </div>
  );

  const etapasPossiveis = dados.etapas.filter((e) => e.pode_followup ?? (e.tipo === "conversa" && !SEM_FOLLOWUP.has(e.codigo)));
  const codigosPossiveis = etapasPossiveis.map((e) => e.codigo);
  const etapasMarcadas = c.etapas.filter((e) => codigosPossiveis.includes(e));
  const mudarPasso = (i: number, p: Partial<Passo>) => setC({ ...c, passos: c.passos.map((x, j) => (j === i ? { ...x, ...p } : x)) });
  const totalPassos = c.passos.length;
  const limites: Limites = c.limites ?? { max_toques_sem_resposta: 0, oferecer_parar: false, lead_parado_apos: 3 };
  const mudarLimites = (l: Partial<Limites>) => setC({ ...c, limites: { ...limites, ...l } });

  const salvar = (config: Config) => executar(async () => {
    const problema = conferir(config, dados.tipo_canal);
    if (problema) throw new Error(problema);
    const r = await enviar<Resposta>(`/agentes/${agente.id}/followup`, paraSalvar(config), "PUT");
    recarregar();
    return r;
  }).then((r) => {
    if (r) { const { reprogramacao: _r, ...salva } = r; setC(salva); }   // eslint-disable-line @typescript-eslint/no-unused-vars
    return r;
  });
  const salvarComAviso = (config: Config) => salvar(config).then((r) => { if (r) avisar(avisoDoSalvar(r)); });
  // O interruptor do topo salva na hora (antes ele só mudava a tela e quem saía sem clicar em Salvar ficava desligado).
  const ligar = (v: boolean) => salvarComAviso({ ...(mudou ? c : dados.config), ativo: v });
  const previa = (i: number) => executar(async () => {
    const r = await enviar<{ mensagens: string[]; aviso?: string }>(`/agentes/${agente.id}/followup/previa`,
      { passo: i, config: paraSalvar(c) });
    setPrevias((v) => ({ ...v, [i]: r.aviso ? [...r.mensagens, r.aviso] : r.mensagens }));
  });
  const ligadoSalvo = dados.config.ativo;

  return (
    <div className="stack fu-pagina">
      {/* 1. Ligado? + resumo: o que o dono precisa ver primeiro. */}
      <Painel titulo={<h3 className="fu-titulo">Follow-up deste agente <span className={`chip ${ligadoSalvo ? "ok" : ""}`}><span className="d" />{ligadoSalvo ? "Ligado" : dados.configurado ? "Desligado" : "Não configurado"}</span></h3>}
        acoes={<label className="fu-ligar"><span>{ligadoSalvo ? "Ligado" : "Desligado"}</span>
          <Interruptor rotulo={ligadoSalvo ? "Desligar o follow-up" : "Ligar o follow-up"} ligado={ligadoSalvo} desligado={ocupado} aoMudar={ligar} /></label>}>
        <p className="sec" style={{ margin: "0 0 10px" }}>Quando o lead para de responder, o agente retoma a conversa no tempo de cada tentativa.
          Para sozinho quando o lead responde, quando alguém da equipe fala, quando a IA é desligada na conversa ou quando o lead pede para parar.</p>
        {!dados.configurado && <div style={{ marginBottom: 10 }}><Alerta tipo="info">Este agente ainda não tem follow-up. Abaixo já vem a cadência padrão
          ({juntar(dados.padrao.cadencia.map(tempoLegivel))}). Ajuste se quiser e ligue no botão ao lado.</Alerta></div>}
        <ul className="fu-resumo">{resumoDaConfig(c, dados.etapas).map((l) => <li key={l}>{l}</li>)}</ul>
        {ligadoSalvo && dados.tipo_canal === "oficial" && <p className="muted" style={{ fontSize: 12.5, margin: "8px 0 0" }}>Número oficial: depois de 24 h sem o lead escrever, sai o modelo aprovado.</p>}
      </Painel>

      {/* 2. Agendados agora. */}
      <Painel titulo={<h3 className="fu-titulo"><CalendarClock size={16} />Próximos follow-ups agendados <span className="muted" style={{ fontWeight: 400, fontSize: 13 }}>{dados.proximos.length}</span></h3>}>
        {dados.proximos.length === 0 ? <Vazio icone={<CalendarClock />}>{ligadoSalvo
          ? "Nenhum follow-up agendado agora. Ele é agendado depois de cada resposta da IA, para quem está numa etapa com follow-up."
          : "Nada agendado: o follow-up está desligado."}</Vazio> : (
          <div className="fu-lista">{dados.proximos.map((p, i) => (
            <div key={i} className="fu-item">
              <b>{p.nome || "Lead sem nome"}<span className="muted"> · final {p.final}</span></b>
              <span>{p.desistencia ? "Desistência (encerrar a conversa)" : `Tentativa ${p.passo + 1} de ${Math.max(totalPassos, p.passo + 1)}`}</span>
              <span className="fu-quando">{p.situacao === "reservado" ? "enviando agora" : quando(p.agendado_para)}</span>
              {p.motivo_texto && <small className="muted">{p.motivo_texto}</small>}
            </div>))}
          </div>)}
      </Painel>

      {/* 3. Cadência. */}
      <Painel titulo="Fluxo de cadência" acoes={<>
        <button className="btn sm" onClick={() => setC({ ...c, passos: dados.padrao.cadencia.map((h) => ({ apos_horas: h, modo: "ia", instrucao: "", texto: "" })) })}><RotateCcw />Cadência padrão</button>
        <button className="btn sm" disabled={c.passos.length >= 12} onClick={() => setC({ ...c, passos: [...c.passos, { apos_horas: Math.max(0, ...c.passos.map((p) => p.apos_horas)) + 24, modo: "ia", instrucao: "", texto: "" }] })}><Plus />Tentativa</button>
      </>}>
        <div className="linha-tempo">
          {c.passos.map((p, i) => {
            const [n, u] = unidade(p.apos_horas);
            return (
              <div key={i} className="passo-fu">
                <div className="passo-fu-marca"><b>{i + 1}</b></div>
                <div className="passo-fu-corpo">
                  <div className="fu-passo-linha">
                    <span className="lbl">Depois de</span>
                    <input className="inp" type="number" min={1} step={1} style={{ width: 78 }} aria-label={`Tempo da tentativa ${i + 1}`} value={n || ""}
                      onChange={(e) => mudarPasso(i, { apos_horas: Number(e.target.value) * FATOR[u] })} />
                    <select className="inp" style={{ width: 104 }} aria-label={`Unidade da tentativa ${i + 1}`} value={u}
                      onChange={(e) => mudarPasso(i, { apos_horas: n * FATOR[e.target.value as Unidade] })}>
                      <option value="minutos">minutos</option><option value="horas">horas</option><option value="dias">dias</option>
                    </select>
                    <span className="muted fu-passo-ajuda">sem resposta, desde a última mensagem da IA</span>
                    <button className="btn sm ghost" aria-label={`Tirar a tentativa ${i + 1}`} disabled={c.passos.length <= 1} onClick={() => setC({ ...c, passos: c.passos.filter((_, j) => j !== i) })}><Trash2 /></button>
                  </div>
                  {limites.oferecer_parar && totalPassos >= 2 && i === totalPassos - 2 && <small className="muted">Esta tentativa oferece parar: “Se preferir que eu não mande mais mensagens, é só me avisar.”</small>}
                </div>
              </div>
            );
          })}
          {c.desistir.ativo && <div className="passo-fu fim"><div className="passo-fu-marca">✕</div>
            <div className="passo-fu-corpo"><span className="sec">Depois de mais {tempoLegivel(c.desistir.apos_horas)} sem resposta: a IA encerra a conversa com este lead.</span></div></div>}
        </div>
        <div className="form fu-limites">
          <label className="field"><span className="lbl">Quem nunca respondeu à IA recebe no máximo</span>
            <select value={limites.max_toques_sem_resposta} onChange={(e) => mudarLimites({ max_toques_sem_resposta: Number(e.target.value) })}>
              <option value={0}>todas as tentativas</option>
              {Array.from({ length: Math.max(totalPassos, 1) }, (_, k) => k + 1).map((k) => <option key={k} value={k}>{k} {k === 1 ? "tentativa" : "tentativas"}</option>)}
            </select></label>
          <label className="field"><span className="lbl">Avisar a equipe (lead parado) depois de</span>
            <select value={limites.lead_parado_apos} onChange={(e) => mudarLimites({ lead_parado_apos: Number(e.target.value) })}>
              <option value={0}>não avisar</option>
              {Array.from({ length: Math.max(totalPassos, limites.lead_parado_apos, 1) }, (_, k) => k + 1).map((k) => <option key={k} value={k}>{k} {k === 1 ? "tentativa" : "tentativas"} sem resposta</option>)}
            </select>
            <span className="ajuda">24 h depois dessa tentativa sem resposta, vira tarefa da equipe.</span></label>
          <label className="check fu-check"><input type="checkbox" checked={limites.oferecer_parar} onChange={(e) => mudarLimites({ oferecer_parar: e.target.checked })} />
            Na penúltima tentativa, oferecer parar (recomendado pela OAB e pela Meta)</label>
        </div>
        <p className="muted" style={{ fontSize: 12, marginBottom: 0 }}>Cada tempo conta a partir da última mensagem da IA (não soma com o anterior). As tentativas são postas em ordem ao salvar.
          Se o lead responder, o fluxo para e recomeça depois da próxima resposta da IA.</p>
      </Painel>

      {/* 4. Quando e onde vale. */}
      <div className="two">
        <Painel titulo="Horário permitido">
          <div className="form">
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <span className="lbl">Das</span>
              <select className="inp" style={{ width: 90 }} aria-label="Início" value={c.horario.inicio} onChange={(e) => setC({ ...c, horario: { ...c.horario, inicio: Number(e.target.value) } })}>
                {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{h}h</option>)}</select>
              <span className="lbl">às</span>
              <select className="inp" style={{ width: 90 }} aria-label="Fim" value={c.horario.fim} onChange={(e) => setC({ ...c, horario: { ...c.horario, fim: Number(e.target.value) } })}>
                {Array.from({ length: 24 }, (_, h) => h + 1).map((h) => <option key={h} value={h}>{h}h</option>)}</select>
              <span className="muted" style={{ fontSize: 12 }}>horário de Brasília</span>
            </div>
            <div className="dias">{DIAS.map((d, i) => (
              <button key={d} type="button" className={c.horario.dias.includes(i) ? "on" : ""} aria-pressed={c.horario.dias.includes(i)}
                onClick={() => setC({ ...c, horario: { ...c.horario, dias: c.horario.dias.includes(i) ? c.horario.dias.filter((x) => x !== i) : [...c.horario.dias, i].sort() } })}>{d}</button>
            ))}</div>
            <span className="ajuda">Fora do horário, a tentativa espera a próxima abertura.</span>
            <label className="field"><span className="lbl">Intervalo mínimo entre mensagens ao mesmo lead (minutos)</span>
              <input type="number" min={5} max={1440} value={c.intervalo_minimo_min} onChange={(e) => setC({ ...c, intervalo_minimo_min: Number(e.target.value) })} /></label>
          </div>
        </Painel>
        <Painel titulo="Etapas do CRM em que vale">
          <div className="form">
            <div className="dias" style={{ flexWrap: "wrap" }}>{etapasPossiveis.map((e) => {
              const marcada = etapasMarcadas.length === 0 || etapasMarcadas.includes(e.codigo);
              return <button key={e.codigo} type="button" className={marcada ? "on" : ""} aria-pressed={marcada} onClick={() => {
                const base = etapasMarcadas.length === 0 ? codigosPossiveis : etapasMarcadas;
                const nova = marcada ? base.filter((x) => x !== e.codigo) : [...base, e.codigo];
                if (nova.length === 0) return;                    // nenhuma marcada seria "todas": deixa pelo menos uma
                setC({ ...c, etapas: nova.length === codigosPossiveis.length ? [] : nova });
              }}>{e.nome}</button>;
            })}</div>
            <span className="ajuda">{etapasMarcadas.length === 0 ? "Vale em todas as etapas de conversa." : `Vale em ${etapasMarcadas.length} de ${codigosPossiveis.length} etapas.`} Encerramento e contrato assinado nunca recebem follow-up.</span>
          </div>
        </Painel>
      </div>

      {/* 5. Mensagem. */}
      <Painel titulo="Mensagem do follow-up">
        <PromptFollowupEditor
          nomeAgente={agente.nome}
          prompt={c.prompt} promptSalvo={dados.config.prompt} promptPadrao={dados.padrao.prompt}
          porEtapa={c.por_etapa} porEtapaSalvo={dados.config.por_etapa} porEtapaPadrao={dados.padrao.por_etapa ?? {}}
          etapas={etapasPossiveis}
          variaveis={dados.variaveis ?? []}
          onPrompt={(t) => setC((v) => (v ? { ...v, prompt: t } : v))}
          onEtapa={(codigo, t) => setC((v) => (v ? { ...v, por_etapa: { ...v.por_etapa, [codigo]: t } } : v))}
          acoes={<Button size="sm" variant="outline" onClick={() => previa(0)} disabled={ocupado}
            title="Escreve um exemplo com uma conversa de teste (usa uma chamada de IA)"><Eye className="size-3.5 mr-1.5" />Ver como fica</Button>}
          rodape={<div className="form">
            <label className="field" style={{ maxWidth: 360 }}><span className="lbl">Modelo de IA do follow-up</span>
              <select value={c.modelo ?? ""} onChange={(e) => setC({ ...c, modelo: e.target.value || null })}>
                <option value="">Padrão do servidor (GPT-4.1 mini)</option>
                {(catalogo?.modelos ?? []).map((m) => <option key={m.id} value={m.id}>{m.nome}</option>)}
              </select></label>
            {previas[0] && <div className="previa-fu"><span className="muted" style={{ fontSize: 12 }}>Exemplo da 1ª retomada (conversa de teste):</span>
              {previas[0].map((t, j) => <div key={j} className="bolha ia">{t}</div>)}</div>}
            <p className="muted" style={{ fontSize: 12, margin: 0 }}>Quem escreve é o agente da etapa em que o lead está, com a voz dele. Valem sempre: sem link, sem prometer resultado ou valor.</p>
          </div>}
        />
      </Painel>

      {/* 6. Desistência, número oficial e decisão. */}
      <div className="two">
        <Painel titulo="Desistir e número oficial">
          <div className="form">
            <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <Interruptor rotulo="Desistir do lead" ligado={c.desistir.ativo} aoMudar={(v) => setC({ ...c, desistir: { ...c.desistir, ativo: v } })} />
              <span className="sec" style={{ fontSize: 13 }}>Depois da última tentativa sem resposta, a IA encerra a conversa e dispara a automação "O lead não respondeu a nenhum follow-up".</span>
            </div>
            {c.desistir.ativo && <>
              <label className="field"><span className="lbl">Esperar depois da última tentativa (horas)</span>
                <input type="number" min={1} value={c.desistir.apos_horas} onChange={(e) => setC({ ...c, desistir: { ...c.desistir, apos_horas: Number(e.target.value) } })} /></label>
              <label className="field"><span className="lbl">Nota para a equipe</span>
                <textarea rows={2} value={c.desistir.nota} onChange={(e) => setC({ ...c, desistir: { ...c.desistir, nota: e.target.value } })} /></label>
            </>}
            {dados.tipo_canal === "oficial" && (
              <label className="field"><span className="lbl">Modelo aprovado (número oficial, janela de 24 h fechada)</span>
                <select value={c.modelo_oficial.id_modelo ?? ""} onChange={(e) => {
                  const m = (modelos.dados ?? []).find((x) => x.id === e.target.value);
                  setC({ ...c, modelo_oficial: m ? { id_modelo: m.id, nome: m.nome } : {} });
                }}>
                  <option value="">Escolher…</option>
                  {(modelos.dados ?? []).map((m) => <option key={m.id} value={m.id}>{m.nome}</option>)}
                </select>
                <span className="ajuda">{modelos.erro ? `Não deu para buscar os modelos aprovados: ${modelos.erro}` : "Na API oficial, depois de 24 h sem o lead escrever, só modelo aprovado pela Meta abre a conversa."}</span></label>
            )}
          </div>
        </Painel>
        <Painel titulo="Antes de enviar">
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <Interruptor rotulo="O agente de follow-up decide antes de enviar" ligado={c.decidir !== false} aoMudar={(v) => setC({ ...c, decidir: v })} />
            <span className="sec" style={{ fontSize: 13 }}>O agente lê a conversa antes de cada tentativa: adia se o lead pediu para falar depois e não envia se não fizer sentido.</span>
          </div>
        </Painel>
      </div>

      {/* 7. Ver tudo: o que já saiu ou não saiu, e os números. */}
      <Painel titulo="Últimos enviados e cancelados">
        {dados.recentes.length === 0 ? <Vazio>Nenhum follow-up enviado ou cancelado ainda.</Vazio> : (
          <div className="fu-lista">{dados.recentes.map((r, i) => {
            const textos = Array.isArray(r.mensagens) ? (r.mensagens as unknown[]).filter((m): m is string => typeof m === "string") : [];
            return (
              <div key={i} className="fu-item">
                <b>{r.nome || "Lead sem nome"}</b>
                <span>{r.desistencia ? "Desistência" : `Tentativa ${r.passo + 1}`}</span>
                <span className={`chip ${r.situacao === "enviado" ? "ok" : r.situacao === "falhou" ? "bad" : ""}`}>{r.situacao === "enviado" ? "enviado" : r.situacao === "falhou" ? "falhou" : "não enviado"}</span>
                <span className="fu-quando">{quando(r.enviado_em ?? r.atualizado_em)}</span>
                {(r.situacao !== "enviado" || r.desistencia) && r.motivo_texto && <small className="muted fu-motivo">Motivo: {r.motivo_texto}</small>}
                {r.situacao === "enviado" && textos.length > 0 && <small className="fu-motivo">“{textos.join(" ")}”</small>}
              </div>);
          })}</div>)}
      </Painel>
      <Painel titulo={<h3 className="fu-titulo">Resultados deste agente <span className="seg" style={{ marginLeft: "auto" }}>{[7, 30, 90].map((d) => (
        <button key={d} type="button" className={dias === d ? "on" : ""} aria-pressed={dias === d} onClick={() => setDias(d)}>{d} dias</button>))}</span></h3>}>
        <DashboardFollowup dias={dias} agente={agente.id} compacto />
      </Painel>
      <Painel titulo="Histórico completo" acoes={<button className="btn sm" onClick={() => setVerHistorico((v) => !v)}>{verHistorico ? "Esconder" : "Mostrar"}</button>}>
        {verHistorico ? <HistoricoFollowup dias={dias} agente={agente.id} compacto />
          : <p className="muted" style={{ margin: 0, fontSize: 13 }}>Cada follow-up deste agente com filtro por situação e busca por lead. Visão de todos os agentes em <Link to="/ferramentas/followup">Ferramentas › Follow-up</Link>.</p>}
      </Painel>

      {/* Barra de salvar: aparece quando há alteração. */}
      {mudou && (
        <div className="fu-barra-salvar" role="region" aria-label="Alterações não salvas">
          <span>Alterações não salvas no follow-up.</span>
          <button className="btn sm" onClick={() => setC(dados.config)} disabled={ocupado}><Undo2 />Descartar</button>
          <button className="btn pri sm" onClick={() => salvarComAviso(c)} disabled={ocupado}><Save />Salvar follow-up</button>
        </div>
      )}
    </div>
  );
}

// =========================================================================== painel na Ativação do agente
/** Na página do agente (Ativação): ver se está ligado, ligar/desligar na hora e ir montar a cadência. */
export function PainelFollowupDoAgente({ agente }: { agente: Agente }) {
  const { dados, erro, recarregar } = useCarregar<Dados>(`/agentes/${agente.id}/followup`, [agente.id], { guardar: false });
  const { ocupado, executar } = useAcao();
  const avisar = useAvisar();
  const link = `/agentes/${agente.id}/followup`;
  const alternar = (ligar: boolean) => executar(async () => {
    const atual = dados ?? await api<Dados>(`/agentes/${agente.id}/followup`);
    const config = { ...atual.config, ativo: ligar };
    const problema = conferir(config, atual.tipo_canal);
    if (problema) throw new Error(`${problema} Abra "Montar cadência" para ajustar.`);
    const r = await enviar<Resposta>(`/agentes/${agente.id}/followup`, paraSalvar(config), "PUT");
    recarregar();
    return r;
  }).then((r) => { if (r) avisar(avisoDoSalvar(r)); });

  if (!dados) return <Painel titulo="Follow-up"><Carregando erro={erro ? `Não deu para abrir o follow-up: ${erro}` : null} /></Painel>;
  const ligado = dados.config.ativo;
  const passos = [...dados.config.passos].sort((a, b) => a.apos_horas - b.apos_horas);
  const enviados = dados.recentes.filter((r) => r.situacao === "enviado").length;
  const naoEnviados = dados.recentes.length - enviados;
  return (
    <Painel titulo={<h3 className="fu-titulo">Follow-up <span className={`chip ${ligado ? "ok" : ""}`}><span className="d" />{ligado ? "Ligado" : dados.configurado ? "Desligado" : "Não configurado"}</span></h3>}
      acoes={<label className="fu-ligar"><span>{ligado ? "Ligado" : "Desligado"}</span>
        <Interruptor rotulo={ligado ? "Desligar o follow-up" : "Ligar o follow-up"} ligado={ligado} desligado={ocupado} aoMudar={alternar} /></label>}>
      <div className="form">
        <div className="fu-cadencia" aria-label="Cadência">
          {passos.map((p, i) => <Fragment key={i}>{i > 0 && <i />}<span>{tempoLegivel(p.apos_horas)}</span></Fragment>)}
        </div>
        <ul className="fu-resumo">{resumoDaConfig(dados.config, dados.etapas).slice(1, 3).map((l) => <li key={l}>{l}</li>)}</ul>
        <div className="fu-numeros-mini">
          <span><b>{dados.proximos.length}</b> agendado{dados.proximos.length === 1 ? "" : "s"}</span>
          <span><b>{enviados}</b> enviado{enviados === 1 ? "" : "s"} recente{enviados === 1 ? "" : "s"}</span>
          <span><b>{naoEnviados}</b> não enviado{naoEnviados === 1 ? "" : "s"}</span>
        </div>
        {!ligado && <Alerta tipo="warn">Desligado: leads que param de responder não recebem lembrete.</Alerta>}
        <Link className="btn" to={link}><Settings2 />Montar cadência e ver agendados</Link>
        {!ligado && !dados.configurado && <span className="muted" style={{ fontSize: 12 }}><Power size={12} style={{ verticalAlign: -2 }} /> Ligar aqui usa a cadência padrão ({juntar(dados.padrao.cadencia.map(tempoLegivel))}).</span>}
      </div>
    </Painel>
  );
}
