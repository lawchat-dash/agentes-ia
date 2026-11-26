import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, ArrowRight, FileText, RotateCcw, Save } from "lucide-react";
import { enviar, quando } from "../api";
import { Alerta, Cabecalho, Carregando, Interruptor, Painel, Vazio, useAcao, useCarregar } from "../componentes/ui";
import "../estilo-ferramentas.css";

// --------------------------------------------------------------------------- tipos
interface ConfigResumo { ligado: boolean; prompt: string; modelo: string; no_aviso: boolean; id_equipe_assinado: string | null }
interface Consumo {
  por_agente: boolean; chamadas: number; feitos: number; tokens_entrada: number; tokens_saida: number; tokens: number;
  media_tokens: number; custo_usd: number; custo_brl: number; chamadas_30d: number; tokens_30d: number; custo_brl_30d: number;
}
interface Visao {
  agente: { id: string; nome: string; produto: string | null; caso: string };
  config: ConfigResumo;
  vale: { origem: "agente" | "escritorio" | "padrao" };
  prompt_padrao: string;
  modelos: string[];
  consumo?: Consumo;
  ultimos?: { id: string; versao: number; nome: string; assinado_em: string | null; resumo: string | null }[];
}
interface ItemAgente { id: string; nome: string; caso: string; situacao: string; ligado: boolean; prompt_proprio: boolean }

const numero = (n: number) => n.toLocaleString("pt-BR");
const reais = (n: number) => n.toLocaleString("pt-BR", { style: "currency", currency: "BRL", minimumFractionDigits: 2, maximumFractionDigits: 4 });

// --------------------------------------------------------------------------- lista de agentes
export function TelaResumosContrato() {
  const navegar = useNavigate();
  const { dados, erro } = useCarregar<ItemAgente[]>("/resumo-contrato/agentes");
  return (
    <>
      <Cabecalho eyebrow="Ferramentas" titulo="Resumo de contrato"
        texto="Quando o contrato é assinado, a IA lê a conversa e escreve o resumo do caso para a equipe: vai na nota do atendimento, no card do CRM e no aviso de contrato assinado. Escolha o agente para ajustar."
        acoes={<Link to="/ferramentas" className="btn ghost"><ArrowLeft /> Ferramentas</Link>} />
      {!dados ? <Carregando erro={erro} /> : dados.length === 0 ? (
        <Painel><Vazio icone={<FileText />}>Nenhum agente ainda. Ative um produto na Biblioteca.</Vazio></Painel>
      ) : (
        <Painel sem_corpo>
          <div className="lst"><table><tbody>{dados.map((a) => (
            <tr key={a.id} className="click" onClick={() => navegar(`/ferramentas/resumo-contrato/${a.id}`)}>
              <td className="t">{a.nome}<div className="muted" style={{ fontSize: 12 }}>{a.caso}</div></td>
              <td>{a.ligado ? <span className="chip ok"><span className="d" /> Ligado</span> : <span className="chip">Desligado</span>}</td>
              <td className="s">{a.prompt_proprio ? "prompt próprio" : "prompt padrão"}</td>
              <td style={{ textAlign: "right" }}><ArrowRight size={15} /></td>
            </tr>
          ))}</tbody></table></div>
        </Painel>
      )}
    </>
  );
}

// --------------------------------------------------------------------------- um agente
export function TelaResumoContrato() {
  const { id = "" } = useParams();
  const { dados, erro, recarregar, fresco } = useCarregar<Visao>(`/agentes/${id}/contrato/resumo`, [id], { guardar: false });
  const equipes = useCarregar<{ id: string; nome: string }[]>("/integracoes/helena/equipes");
  const [form, setForm] = useState<ConfigResumo | null>(null);
  const { ocupado, executar } = useAcao();

  useEffect(() => {
    if (dados && fresco) setForm({ ...dados.config, prompt: dados.config.prompt || dados.prompt_padrao });
  }, [dados, fresco]);

  if (!dados || !form) return <Carregando erro={erro} />;
  const mudar = (parte: Partial<ConfigResumo>) => setForm({ ...form, ...parte });
  const ehPadrao = form.prompt.trim() === dados.prompt_padrao.trim();
  const salvar = async () => {
    const r = await executar(() => enviar<Visao>(`/agentes/${id}/contrato/resumo`, {
      ...form, prompt: ehPadrao ? "" : form.prompt, id_equipe_assinado: form.id_equipe_assinado || null,
    }, "PUT"), "Resumo de contrato salvo");
    if (r) recarregar();
  };
  const c = dados.consumo;

  return (
    <>
      <Cabecalho eyebrow="Ferramentas · Resumo de contrato" titulo={`Resumo de contrato do agente ${dados.agente.nome}`}
        texto={`Caso: ${dados.agente.caso}. Quando o lead assina, a IA lê a conversa com este prompt e escreve o resumo do caso. Se a IA falhar, o contrato assinado segue normal, só sem o resumo.`}
        acoes={<>
          <Link to="/ferramentas/resumo-contrato" className="btn ghost"><ArrowLeft /> Agentes</Link>
          <button type="button" className="btn pri" disabled={ocupado} onClick={salvar}><Save /> Salvar</button>
        </>} />

      <Painel titulo="Resumo do caso">
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
          <Interruptor ligado={form.ligado} aoMudar={(v) => mudar({ ligado: v })} rotulo="Fazer o resumo do contrato assinado" />
          <span><b>{form.ligado ? "Ligado" : "Desligado"}</b> <span className="muted">— fazer o resumo quando o contrato for assinado</span></span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
          <Interruptor ligado={form.no_aviso} aoMudar={(v) => mudar({ no_aviso: v })} rotulo="Levar o resumo no aviso à equipe" />
          <span>Levar o resumo no aviso <b>Contrato assinado</b> à equipe <span className="muted">(o aviso espera o resumo)</span></span>
        </div>
        <div style={{ display: "grid", gap: 12, gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", marginBottom: 14 }}>
          <label style={{ display: "grid", gap: 4 }}>
            <span className="muted" style={{ fontSize: 12.5 }}>Modelo de IA</span>
            <select className="inp" value={form.modelo} onChange={(e) => mudar({ modelo: e.target.value })} aria-label="Modelo de IA do resumo">
              {dados.modelos.map((m) => <option key={m} value={m}>{m}{m === "gpt-4.1-mini" ? " (padrão)" : ""}</option>)}
            </select>
          </label>
          <label style={{ display: "grid", gap: 4 }}>
            <span className="muted" style={{ fontSize: 12.5 }}>Transferir o atendimento para</span>
            <select className="inp" value={form.id_equipe_assinado ?? ""} onChange={(e) => mudar({ id_equipe_assinado: e.target.value || null })}
              aria-label="Departamento depois da assinatura" disabled={!equipes.dados}>
              <option value="">Não transferir</option>
              {(equipes.dados ?? []).map((q) => <option key={q.id} value={q.id}>{q.nome}</option>)}
            </select>
          </label>
        </div>
        <label style={{ display: "grid", gap: 4 }}>
          <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className="muted" style={{ fontSize: 12.5 }}>Prompt do resumo</span>
            {ehPadrao ? <span className="chip">padrão do produto</span> : <span className="chip warn">editado</span>}
            <span style={{ flex: 1 }} />
            {!ehPadrao && <button type="button" className="btn sm ghost" onClick={() => mudar({ prompt: dados.prompt_padrao })}><RotateCcw /> Voltar ao padrão</button>}
          </span>
          <textarea className="inp" rows={18} style={{ maxWidth: "none", fontFamily: "inherit", lineHeight: 1.5 }} value={form.prompt}
            onChange={(e) => mudar({ prompt: e.target.value })} aria-label="Prompt do resumo do contrato" />
        </label>
        {dados.vale.origem === "escritorio" && ehPadrao && (
          <div style={{ marginTop: 10 }}><Alerta tipo="info">O escritório tem um prompt próprio em Integrações › ZapSign, e ele vale enquanto este agente usar o padrão.</Alerta></div>
        )}
      </Painel>

      {c && (
        <Painel titulo="Consumo do resumo">
          <div style={{ display: "grid", gap: 12, gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
            <Numero rotulo="Resumos feitos" valor={numero(c.feitos)} />
            <Numero rotulo="Tokens (total)" valor={numero(c.tokens)} detalhe={`${numero(c.tokens_entrada)} de entrada · ${numero(c.tokens_saida)} de saída`} />
            <Numero rotulo="Média por resumo" valor={`${numero(c.media_tokens)} tokens`} />
            <Numero rotulo="Custo (total)" valor={reais(c.custo_brl)} />
            <Numero rotulo="Últimos 30 dias" valor={reais(c.custo_brl_30d)} detalhe={`${numero(c.chamadas_30d)} chamada(s) · ${numero(c.tokens_30d)} tokens`} />
          </div>
          <p className="muted" style={{ fontSize: 12.5, margin: "10px 0 0" }}>
            {c.por_agente ? "Deste agente." : "Do escritório inteiro (o consumo por agente aparece depois da atualização da cobrança)."} O custo entra em Créditos como as outras chamadas da IA.
          </p>
        </Painel>
      )}

      <Painel titulo="Últimos resumos">
        {!dados.ultimos?.length ? <Vazio>Nenhum contrato assinado neste agente ainda.</Vazio> : (
          <div style={{ display: "grid", gap: 12 }}>
            {dados.ultimos.map((u) => (
              <div key={u.id} style={{ border: "1px solid var(--line)", borderRadius: 10, padding: 12 }}>
                <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}>
                  <b>{u.nome || "Lead"}</b><span className="muted" style={{ fontSize: 12 }}>versão {u.versao} · assinado {quando(u.assinado_em)}</span>
                </div>
                <div style={{ whiteSpace: "pre-wrap", fontSize: 13, lineHeight: 1.5, color: "var(--ink-2)" }}>
                  {u.resumo || <span className="muted">Sem resumo (desligado ou a IA não conseguiu).</span>}
                </div>
              </div>
            ))}
          </div>
        )}
      </Painel>
    </>
  );
}

function Numero({ rotulo, valor, detalhe }: { rotulo: string; valor: string; detalhe?: string }) {
  return (
    <div style={{ border: "1px solid var(--line)", borderRadius: 10, padding: "10px 12px" }}>
      <div className="muted" style={{ fontSize: 12 }}>{rotulo}</div>
      <div style={{ fontSize: 18, fontWeight: 650, color: "var(--ink)" }}>{valor}</div>
      {detalhe && <div className="muted" style={{ fontSize: 11.5 }}>{detalhe}</div>}
    </div>
  );
}
