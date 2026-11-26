import { useEffect, useState } from "react";
import { Eye, Plus, RotateCcw, Save, Trash2 } from "lucide-react";
import { enviar, quando, type Agente } from "../api";
import { Alerta, Carregando, Interruptor, Painel, Vazio, useAcao, useCarregar } from "../componentes/ui";
import { useSessao } from "../sessao";

interface Passo { apos_horas: number; modo: "ia" | "texto" | "modelo"; instrucao: string; texto: string }
interface Config {
  ativo: boolean; horario: { inicio: number; fim: number; dias: number[] }; intervalo_minimo_min: number; etapas: string[];
  prompt: string; por_etapa: Record<string, string>; passos: Passo[]; modelo_oficial: { id_modelo?: string; nome?: string };
  desistir: { ativo: boolean; apos_horas: number; nota: string }; modelo: string | null;
}
interface Dados {
  config: Config; padrao: { prompt: string; cadencia: number[]; instrucoes: Record<string, string> };
  etapas: { codigo: string; nome: string; tipo: string }[]; tipo_canal: string;
  proximos: { passo: number; agendado_para: string; situacao: string; motivo: string | null; nome: string | null; final: string }[];
  recentes: { passo: number; enviado_em: string | null; atualizado_em: string; situacao: string; motivo: string | null; mensagens: unknown; nome: string | null }[];
}

const DIAS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"];
const MOTIVOS: Record<string, string> = {
  lead_respondeu: "lead respondeu", equipe_falou: "equipe falou", nova_resposta_da_ia: "IA respondeu de novo", modo_teste: "fora dos números de teste",
  etapa_sem_followup: "etapa sem follow-up", agente_pausado: "agente pausado", followup_desligado: "follow-up desligado", desistencia: "desistência",
  janela_fechada_sem_modelo: "janela de 24 h fechada sem modelo", fora_do_horario: "aguardando horário", intervalo_minimo: "intervalo mínimo",
};

function unidade(horas: number): [number, "horas" | "dias"] {
  return horas >= 24 && horas % 24 === 0 ? [horas / 24, "dias"] : [horas, "horas"];
}
const rotuloTempo = (h: number) => { const [n, u] = unidade(h); return `${n} ${n === 1 ? u.slice(0, -1) : u}`; };

/** Follow-up do agente: cadência, mensagem de cada passo, prompt, horário, etapas, modelo aprovado e desistência. */
export function AbaFollowup({ agente }: { agente: Agente }) {
  const { dados, erro, recarregar } = useCarregar<Dados>(`/agentes/${agente.id}/followup`);
  const modelos = useCarregar<{ id: string; nome: string; texto: string }[]>(dados?.tipo_canal === "oficial" ? "/integracoes/helena/modelos-aprovados" : null, [dados?.tipo_canal]);
  const { ocupado, executar } = useAcao();
  const { catalogo } = useSessao();
  const [c, setC] = useState<Config | null>(null);
  const [previas, setPrevias] = useState<Record<number, string[]>>({});
  useEffect(() => { if (dados) setC(dados.config); }, [dados]);
  if (!dados || !c) return <Carregando erro={erro} />;

  const conversa = new Set(dados.etapas.filter((e) => e.tipo === "conversa").map((e) => e.codigo));
  const mudarPasso = (i: number, p: Partial<Passo>) => setC({ ...c, passos: c.passos.map((x, j) => (j === i ? { ...x, ...p } : x)) });
  // Toda tentativa é escrita pelo agente de follow-up (sem mensagem fixa).
  const salvar = () => executar(async () => {
    setC(await enviar<Config>(`/agentes/${agente.id}/followup`, { ...c, passos: c.passos.map((p) => ({ ...p, modo: "ia", texto: "" })) }, "PUT"));
    recarregar();
  },
    c.ativo ? "Follow-up salvo e ligado. Vale a partir da próxima resposta da IA." : "Follow-up salvo (desligado).");
  const previa = (i: number) => executar(async () => {
    const r = await enviar<{ mensagens: string[]; aviso?: string }>(`/agentes/${agente.id}/followup/previa`,
      { passo: i, config: { ...c, passos: c.passos.map((p) => ({ ...p, modo: "ia" })) } });
    setPrevias({ ...previas, [i]: r.mensagens });
    if (r.aviso) setPrevias((v) => ({ ...v, [i]: [...r.mensagens, r.aviso as string] }));
  });

  return (
    <div className="stack">
      <Painel titulo={<h3 style={{ display: "flex", gap: 10, alignItems: "center" }}>Follow-up <span className={`chip ${c.ativo ? "ok" : ""}`}>{c.ativo ? "ligado" : "desligado"}</span></h3>}
        acoes={<><Interruptor rotulo="Follow-up ligado" ligado={c.ativo} aoMudar={(v) => setC({ ...c, ativo: v })} />
          <button className="btn pri sm" onClick={salvar} disabled={ocupado}><Save />Salvar follow-up</button></>}>
        <p className="sec" style={{ margin: 0 }}>Quando o lead para de responder, a IA retoma a conversa no tempo de cada passo (contado a partir da última resposta dela).
          Para sozinho se o lead responder, se alguém da equipe falar, se a etapa mudar ou se a IA for desligada.</p>
      </Painel>

      <Painel titulo="Agente de follow-up" acoes={<>
        <button className="btn sm" onClick={() => setC({ ...c, prompt: dados.padrao.prompt })}><RotateCcw />Prompt padrão</button>
        <button className="btn sm" onClick={() => previa(0)} disabled={ocupado}><Eye />Ver como fica</button>
      </>}>
        <div className="form">
          <p className="sec" style={{ margin: 0 }}>Quem escreve cada retomada é um agente de IA: ele lê a conversa e segue este prompt. Não há mensagem fixa.
            Ele fala como {agente.nome}, do escritório, e cada tentativa fica um pouco mais curta e leve.</p>
          <label className="field" style={{ maxWidth: 360 }}><span className="lbl">Modelo de IA do follow-up</span>
            <select value={c.modelo ?? ""} onChange={(e) => setC({ ...c, modelo: e.target.value || null })}>
              <option value="">Padrão do servidor (GPT-4.1 mini)</option>
              {(catalogo?.modelos ?? []).map((m) => <option key={m.id} value={m.id}>{m.nome}</option>)}
            </select></label>
          <label className="field"><span className="lbl">Prompt do agente de follow-up</span>
            <textarea className="codigo" rows={9} aria-label="Prompt do agente de follow-up" value={c.prompt} onChange={(e) => setC({ ...c, prompt: e.target.value })} /></label>
          <details>
            <summary className="lbl" style={{ cursor: "pointer" }}>Instrução extra por etapa</summary>
            <div className="form" style={{ marginTop: 8 }}>{dados.etapas.filter((e) => conversa.has(e.codigo)).map((e) => (
              <label key={e.codigo} className="field"><span className="lbl">{e.nome}</span>
                <textarea rows={2} value={c.por_etapa[e.codigo] ?? ""} placeholder="Ex.: lembre que os honorários só são pagos no final."
                  onChange={(ev) => setC({ ...c, por_etapa: { ...c.por_etapa, [e.codigo]: ev.target.value } })} /></label>
            ))}</div>
          </details>
          {previas[0] && <div className="previa-fu"><span className="muted" style={{ fontSize: 12 }}>Exemplo da 1ª retomada (conversa de teste):</span>
            {previas[0].map((t, j) => <div key={j} className="bolha ia">{t}</div>)}</div>}
          <p className="muted" style={{ fontSize: 12, margin: 0 }}>Valem sempre: sem link, sem prometer resultado ou valor. Se a IA escrever algo assim, sai uma mensagem simples de reserva.</p>
        </div>
      </Painel>

      <Painel titulo="Fluxo de cadência" acoes={<>
        <button className="btn sm" onClick={() => setC({ ...c, passos: dados.padrao.cadencia.map((h) => ({ apos_horas: h, modo: "ia", instrucao: "", texto: "" })) })}><RotateCcw />Cadência padrão</button>
        <button className="btn sm" disabled={c.passos.length >= 12} onClick={() => setC({ ...c, passos: [...c.passos, { apos_horas: (c.passos[c.passos.length - 1]?.apos_horas ?? 0) + 24, modo: "ia", instrucao: "", texto: "" }] })}><Plus />Tentativa</button>
      </>}>
        <div className="linha-tempo">
          {c.passos.map((p, i) => {
            const [n, u] = unidade(p.apos_horas);
            return (
              <div key={i} className="passo-fu">
                <div className="passo-fu-marca"><b>{i + 1}</b></div>
                <div className="passo-fu-corpo">
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                    <span className="lbl">Depois de</span>
                    <input className="inp" type="number" min={1} style={{ width: 80 }} aria-label={`Tempo do passo ${i + 1}`} value={n}
                      onChange={(e) => mudarPasso(i, { apos_horas: Number(e.target.value) * (u === "dias" ? 24 : 1) })} />
                    <select className="inp" style={{ width: 100 }} aria-label="Unidade" value={u} onChange={(e) => mudarPasso(i, { apos_horas: n * (e.target.value === "dias" ? 24 : 1) })}>
                      <option value="horas">horas</option><option value="dias">dias</option>
                    </select>
                    <span className="muted" style={{ fontSize: 12.5 }}>sem resposta, desde a última mensagem da IA</span>
                    <span style={{ flex: 1 }} />
                    <button className="btn sm ghost" aria-label="Tirar passo" disabled={c.passos.length <= 1} onClick={() => setC({ ...c, passos: c.passos.filter((_, j) => j !== i) })}><Trash2 /></button>
                  </div>
                </div>
              </div>
            );
          })}
          {c.desistir.ativo && <div className="passo-fu fim"><div className="passo-fu-marca">✕</div>
            <div className="passo-fu-corpo"><span className="sec">Depois de mais {rotuloTempo(c.desistir.apos_horas)} sem resposta: a IA encerra a conversa com este lead.</span></div></div>}
        </div>
        <p className="muted" style={{ fontSize: 12, marginBottom: 0 }}>Cada tentativa é escrita pelo agente de follow-up. Se o lead responder, o fluxo para e recomeça depois da próxima resposta da IA.</p>
      </Painel>

      <div className="two">
        <Painel titulo="Quando pode enviar">
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
              <button key={d} className={c.horario.dias.includes(i) ? "on" : ""} aria-pressed={c.horario.dias.includes(i)}
                onClick={() => setC({ ...c, horario: { ...c.horario, dias: c.horario.dias.includes(i) ? c.horario.dias.filter((x) => x !== i) : [...c.horario.dias, i].sort() } })}>{d}</button>
            ))}</div>
            <label className="field"><span className="lbl">Intervalo mínimo entre mensagens ao mesmo lead (minutos)</span>
              <input type="number" min={5} max={1440} value={c.intervalo_minimo_min} onChange={(e) => setC({ ...c, intervalo_minimo_min: Number(e.target.value) })} /></label>
            <div className="field"><span className="lbl">Em quais etapas</span>
              <div className="dias" style={{ flexWrap: "wrap" }}>{dados.etapas.filter((e) => conversa.has(e.codigo)).map((e) => {
                const marcada = c.etapas.length === 0 || c.etapas.includes(e.codigo);
                return <button key={e.codigo} className={marcada ? "on" : ""} aria-pressed={marcada} onClick={() => {
                  const base = c.etapas.length === 0 ? [...conversa] : c.etapas;
                  const nova = marcada ? base.filter((x) => x !== e.codigo) : [...base, e.codigo];
                  setC({ ...c, etapas: nova.length === conversa.size ? [] : nova });
                }}>{e.nome}</button>;
              })}</div>
              <span className="ajuda">Etapas de encerramento nunca recebem follow-up.</span></div>
          </div>
        </Painel>
        <Painel titulo="Desistir do lead">
          <div className="form">
            <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <Interruptor rotulo="Desistir do lead" ligado={c.desistir.ativo} aoMudar={(v) => setC({ ...c, desistir: { ...c.desistir, ativo: v } })} />
              <span className="sec" style={{ fontSize: 13 }}>Depois do último passo sem resposta, a IA encerra a conversa e dispara a automação "O lead não respondeu a nenhum follow-up".</span>
            </div>
            {c.desistir.ativo && <>
              <label className="field"><span className="lbl">Esperar depois do último passo (horas)</span>
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
                <span className="ajuda">Na API oficial, depois de 24 h sem o lead escrever, só modelo aprovado pela Meta abre a conversa.</span></label>
            )}
          </div>
        </Painel>
      </div>

      <div className="two">
        <Painel titulo="Próximos envios" sem_corpo>
          {dados.proximos.length === 0 ? <Vazio>Nenhum follow-up agendado.</Vazio> : (
            <div className="lst"><table><thead><tr><th>Lead</th><th>Passo</th><th>Quando</th></tr></thead><tbody>
              {dados.proximos.map((p, i) => <tr key={i}><td>{p.nome ?? "sem nome"} <span className="muted mono">…{p.final}</span></td>
                <td className="num">{p.passo < c.passos.length ? p.passo + 1 : "desistência"}</td><td className="s num">{quando(p.agendado_para)}</td></tr>)}
            </tbody></table></div>)}
        </Painel>
        <Painel titulo="Últimos" sem_corpo>
          {dados.recentes.length === 0 ? <Vazio>Nada ainda.</Vazio> : (
            <div className="lst"><table><thead><tr><th>Lead</th><th>Passo</th><th>Resultado</th></tr></thead><tbody>
              {dados.recentes.map((r, i) => <tr key={i}><td>{r.nome ?? "sem nome"}</td><td className="num">{r.passo + 1}</td>
                <td><span className={`chip ${r.situacao === "enviado" ? "ok" : r.situacao === "falhou" ? "bad" : ""}`}>{r.situacao}</span> <span className="s">{MOTIVOS[r.motivo ?? ""] ?? r.motivo ?? ""}</span></td></tr>)}
            </tbody></table></div>)}
        </Painel>
      </div>
      {!c.ativo && <Alerta tipo="info">O follow-up está desligado. Ligue no alto e salve.</Alerta>}
    </div>
  );
}
