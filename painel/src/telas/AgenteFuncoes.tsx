import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Bell, FileSignature, KanbanSquare, RotateCcw, Save, Sparkles, StickyNote, Users, Wand2 } from "lucide-react";
import { api, enviar, type Agente, type Regra } from "../api";
import { Alerta, Carregando, Interruptor, Painel, useAcao, useCarregar, useConfirmar } from "../componentes/ui";
import { useSessao } from "../sessao";

/** O que o motor roda sozinho para este agente (GET /agentes/:id/automacoes/padrao). */
interface Padrao {
  regras: Record<string, Regra>; tipos: Record<string, string>;
  usa_padrao: boolean; crm_desligado: boolean; crm_pronto: boolean; tem_painel: boolean;
  etapas_por_tipo: Record<string, string>; colunas: Record<string, string>; funcoes_efetivas: Record<string, boolean>;
}
interface PainelCrm { id: string; titulo: string; etapas: { id: string; titulo: string }[] }

type Aba = "crm" | "notas" | "departamento" | "avisos" | "contrato";
const ABAS: { chave: Aba; rotulo: string; icone: ReactNode }[] = [
  { chave: "crm", rotulo: "CRM e etiquetas", icone: <KanbanSquare size={15} /> },
  { chave: "notas", rotulo: "Notas", icone: <StickyNote size={15} /> },
  { chave: "departamento", rotulo: "Departamento", icone: <Users size={15} /> },
  { chave: "avisos", rotulo: "Avisos", icone: <Bell size={15} /> },
  { chave: "contrato", rotulo: "Contrato", icone: <FileSignature size={15} /> },
];
const NOME_TIPO: Record<string, string> = {
  SDR: "SDR", COMERCIAL: "COMERCIAL", CONTRATO: "CONTRATO", AGUARDANDO_ASSINATURA: "AGUARDANDO_ASSINATURA",
  CONTRATO_ASSINADO: "CONTRATO_ASSINADO", DESQUALIFICADO: "DESQUALIFICADO",
};
const CONTRATO = ["contrato_gerado", "contrato_assinado", "contrato_falhou"];
const ATENDIMENTO = ["pediu_humano", "trava", "ia_falhou", "lead_quente", "pediu_para_parar", "followup_desistiu", "lead_parado"];

const lista = (texto: string) => texto.split(",").map((t) => t.trim()).filter(Boolean);
const limpar = (r: Record<string, Regra>) =>
  Object.fromEntries(Object.entries(r).filter(([, v]) => Object.values(v).some((x) => (Array.isArray(x) ? x.length : x !== undefined && x !== ""))));
const igual = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/** Funções e automações em abas, já preenchidas com o padrão do LawChat. A pessoa só muda se quiser. */
export function AbaFuncoes({ agente, aoSalvar }: { agente: Agente; aoSalvar: (a: Agente) => void }) {
  const { catalogo } = useSessao();
  const { ocupado, executar } = useAcao();
  const [confirmar, janelaConfirmar] = useConfirmar();
  const padrao = useCarregar<Padrao>(`/agentes/${agente.id}/automacoes/padrao`, [agente.id], { guardar: false });
  const equipes = useCarregar<{ id: string; nome: string }[]>("/integracoes/helena/equipes");
  const etiquetas = useCarregar<{ id: string; nome: string }[]>("/integracoes/helena/etiquetas");
  const [painel, setPainel] = useState<PainelCrm | null>(null);
  const [aba, setAba] = useState<Aba>("crm");
  const [funcoes, setFuncoes] = useState<Record<string, boolean>>(agente.funcoes);
  const [equipe, setEquipe] = useState(agente.id_equipe_transferencia ?? "");
  const [regras, setRegras] = useState<Record<string, Regra>>({});
  const [inicial, setInicial] = useState<{ regras: Record<string, Regra>; funcoes: Record<string, boolean> } | null>(null);

  const proprias = Object.keys(agente.automacoes ?? {}).length > 0;
  const p = padrao.dados;
  // Só os gatilhos que este agente tem (o padrão traz todos os papéis possíveis quando o produto não diz quais).
  const regrasPadrao = useMemo(() => Object.fromEntries(Object.entries(p?.regras ?? {}).filter(([g]) => g in agente.gatilhos)), [p, agente.gatilhos]);

  useEffect(() => {
    if (!p) return;
    const r = proprias ? agente.automacoes : regrasPadrao;
    const f = { ...agente.funcoes, ...p.funcoes_efetivas };
    setRegras(r); setFuncoes(f); setInicial({ regras: r, funcoes: f });
  }, [p]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (p?.tem_painel) api<{ painel: PainelCrm }>(`/agentes/${agente.id}/automacoes/sugestao`).then((r) => setPainel(r.painel)).catch(() => undefined);
  }, [p?.tem_painel, agente.id]);

  if (!p || !inicial) return <Carregando erro={padrao.erro} />;

  const regrasMudaram = !igual(limpar(regras), limpar(inicial.regras));
  const mudou = regrasMudaram || !igual(funcoes, inicial.funcoes) || equipe !== (agente.id_equipe_transferencia ?? "");
  const usandoPadrao = !proprias && !regrasMudaram;
  const mudarRegra = (g: string, parcial: Partial<Regra>) => setRegras({ ...regras, [g]: { ...(regras[g] ?? {}), ...parcial } });
  const nomeEtapa = (codigo: string) => agente.etapas.find((e) => e.codigo === codigo)?.nome ?? codigo;
  const rotulo = (g: string) => g === "lead_novo" ? "Lead novo chegou"
    : g.startsWith("etapa:") ? `Lead passou para ${nomeEtapa(g.slice(6))}` : (agente.gatilhos[g] ?? g);
  const colunas = painel?.etapas ?? Object.entries(p.colunas).map(([id, titulo]) => ({ id, titulo }));
  const nomeColuna = (id?: string, g?: string) => !id ? "—" : colunas.find((c) => c.id === id)?.titulo ?? (g && p.tipos[g] ? NOME_TIPO[p.tipos[g]] : "coluna escolhida");
  const etapasDoAgente = ["lead_novo", ...Object.keys(agente.gatilhos).filter((g) => g.startsWith("etapa:"))];
  const sinais = Object.keys(agente.gatilhos).filter((g) => g === "sinal" || g.startsWith("sinal:") || g.startsWith("intencao:"));

  const salvar = () => executar(async () => {
    // As funções do motor (o CRM vem ligado no padrão) vão junto: salvar sem mexer não desliga nada.
    let salvo = await enviar<Agente>(`/agentes/${agente.id}`, { funcoes, id_equipe_transferencia: equipe }, "PATCH");
    if (regrasMudaram || proprias) salvo = await enviar<Agente>(`/agentes/${agente.id}/automacoes`, { automacoes: limpar(regras) }, "PUT");
    aoSalvar(salvo); padrao.recarregar();
  }, regrasMudaram || proprias ? "Automações salvas como regras próprias deste agente. Valem a partir da próxima mensagem." : "Funções salvas. O agente segue no padrão automático.");

  const voltarAoPadrao = async () => {
    if (!(await confirmar({ titulo: "Voltar ao padrão automático?", confirmar: "Voltar ao padrão", perigo: true,
      texto: <>As regras próprias deste agente são apagadas e ele volta a usar a pré-configuração do LawChat (card na coluna do tipo, etiqueta e nota a cada troca de agente).</> }))) return;
    executar(async () => {
      const salvo = await enviar<Agente>(`/agentes/${agente.id}/automacoes`, { automacoes: {} }, "PUT");
      aoSalvar(salvo); padrao.recarregar();
    }, "Agente de volta ao padrão automático.");
  };
  const descartar = () => { setRegras(inicial.regras); setFuncoes(inicial.funcoes); setEquipe(agente.id_equipe_transferencia ?? ""); };
  const sugerirPeloPainel = () => executar(async () => {
    const r = await api<{ painel: PainelCrm; automacoes: Record<string, Regra> }>(`/agentes/${agente.id}/automacoes/sugestao`);
    setPainel(r.painel);
    setRegras(Object.fromEntries(Object.entries({ ...regras }).map(([g, v]) => [g, { ...v, ...(r.automacoes[g]?.coluna_crm ? { coluna_crm: r.automacoes[g].coluna_crm } : {}) }])));
  }, "Colunas escolhidas pelo nome. Confira e salve.");

  const funcao = (id: string) => catalogo?.funcoes.find((f) => f.id === id);
  const chave = (id: string, extra?: ReactNode) => {
    const f = funcao(id);
    if (!f) return null;
    return (
      <div className="func-linha">
        <Interruptor rotulo={f.nome} ligado={Boolean(funcoes[id])} desligado={!f.pronta} aoMudar={(v) => setFuncoes({ ...funcoes, [id]: v })} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <b>{f.nome}</b> <span className={`chip ${funcoes[id] ? "ok" : ""}`}>{funcoes[id] ? "ligada" : "desligada"}</span>
          <div className="sec" style={{ fontSize: 13 }}>{f.descricao}</div>
          {extra}
        </div>
      </div>
    );
  };

  return (
    <div className="stack">
      {/* Topo: em que modo o agente está, e o que fazer. */}
      <section className={`func-topo ${usandoPadrao ? "padrao" : "proprio"}`}>
        <span className="func-topo-icone">{usandoPadrao ? <Sparkles size={18} /> : <Wand2 size={18} />}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <b>{usandoPadrao ? "Padrão (automático)" : proprias && !regrasMudaram ? "Regras próprias deste agente" : "Você alterou o padrão"}</b>
          <p>{usandoPadrao
            ? "Este agente já vem configurado: a cada passo do lead o LawChat move o card no CRM, troca a etiqueta e deixa uma nota no atendimento. Está tudo preenchido abaixo; mude só o que quiser."
            : proprias && !regrasMudaram
              ? "Este agente usa as regras que alguém salvou para ele, no lugar do padrão. Dá para voltar ao padrão a qualquer hora."
              : "Ao salvar, estas regras passam a valer só para este agente, no lugar do padrão."}</p>
        </div>
        <div className="func-topo-acoes">
          {mudou && <button className="btn sm ghost" onClick={descartar} disabled={ocupado}>Descartar</button>}
          {proprias && <button className="btn sm" onClick={voltarAoPadrao} disabled={ocupado}><RotateCcw />Voltar ao padrão</button>}
          <button className="btn pri sm" onClick={salvar} disabled={ocupado || !mudou}><Save />Salvar</button>
        </div>
      </section>

      {p.crm_desligado && <Alerta tipo="warn">A função <b>Etapa do CRM e etiquetas</b> está desligada neste agente, então nada do CRM roda. Ligue na aba <b>CRM e etiquetas</b>.</Alerta>}
      {!p.crm_pronto && !p.crm_desligado && (
        <Alerta tipo="info">{p.tem_painel
          ? <>O painel do CRM escolhido não tem as colunas padrão do LawChat (SDR, COMERCIAL, CONTRATO…). Escolha as colunas abaixo (ou use <b>Escolher pelas colunas do painel</b>) e salve.</>
          : <>Para o card do lead aparecer no CRM, escolha o painel do CRM em <Link to="/integracoes">Integrações</Link>. Até lá, o padrão fica pronto aqui, esperando o painel.</>}</Alerta>
      )}

      <div className="tabs" role="tablist" style={{ marginBottom: 0 }}>
        {ABAS.map((a) => (
          <button key={a.chave} role="tab" aria-selected={aba === a.chave} className={aba === a.chave ? "on" : ""} onClick={() => setAba(a.chave)}>{a.icone}{a.rotulo}</button>
        ))}
      </div>
      <datalist id="etiquetas-conta">{(etiquetas.dados ?? []).map((t) => <option key={t.id} value={t.nome} />)}</datalist>

      {aba === "crm" && <>
        <Painel sem_corpo>{chave("crm")}</Painel>
        <Painel titulo="A cada passo do lead" sem_corpo acoes={!p.crm_pronto && p.tem_painel
          ? <button className="btn sm" onClick={sugerirPeloPainel} disabled={ocupado}><Sparkles />Escolher pelas colunas do painel</button> : undefined}>
          <p className="sec func-explica">Quando o lead chega ou passa de um agente para outro, o card vai para a coluna do tipo, a etiqueta do tipo entra e as outras saem.</p>
          <div className="func-tabela">
            <div className="func-cab"><span>Quando</span><span>Coluna do CRM</span><span>Põe a etiqueta</span><span>Tira as etiquetas</span></div>
            {etapasDoAgente.map((g) => {
              const r = regras[g] ?? {};
              return (
                <div key={g} className="func-linha-regra">
                  <span className="func-quando">{rotulo(g)}{regrasPadrao[g] && igual(r, regrasPadrao[g]) && <span className="chip ok">padrão</span>}</span>
                  <label className="field"><span className="lbl so-celular">Coluna do CRM</span>
                    <select value={r.coluna_crm ?? ""} disabled={!colunas.length} onChange={(e) => mudarRegra(g, { coluna_crm: e.target.value || undefined })}>
                      <option value="">{p.tipos[g] && !colunas.length ? `${NOME_TIPO[p.tipos[g]]} (quando houver painel)` : "Não mover"}</option>
                      {colunas.map((c) => <option key={c.id} value={c.id}>{c.titulo}</option>)}
                    </select></label>
                  <label className="field"><span className="lbl so-celular">Põe a etiqueta</span>
                    <input list="etiquetas-conta" value={(r.adicionar_etiquetas ?? []).join(", ")} placeholder="nenhuma" onChange={(e) => mudarRegra(g, { adicionar_etiquetas: lista(e.target.value) })} /></label>
                  <label className="field"><span className="lbl so-celular">Tira as etiquetas</span>
                    <input list="etiquetas-conta" value={(r.remover_etiquetas ?? []).join(", ")} placeholder="nenhuma" title={(r.remover_etiquetas ?? []).join(", ")} onChange={(e) => mudarRegra(g, { remover_etiquetas: lista(e.target.value) })} /></label>
                </div>
              );
            })}
          </div>
        </Painel>
      </>}

      {aba === "notas" && (
        <Painel titulo="Nota no atendimento" sem_corpo>
          <p className="sec func-explica">A nota aparece só para a equipe, dentro do atendimento. A nota da troca de agente ("🔄 Lead passou para o agente…") sai sempre; as outras saem com <b>Avisar a equipe</b> ligada (aba Avisos).</p>
          {[...etapasDoAgente, ...ATENDIMENTO.filter((g) => g in agente.gatilhos)].map((g) => {
            const r = regras[g] ?? {};
            return (
              <div key={g} className="func-linha-nota">
                <span className="func-quando">{rotulo(g)}{r.nota_sempre && <span className="chip ac">sempre</span>}</span>
                <input className="inp" value={r.nota ?? ""} placeholder="Sem nota" aria-label={`Nota: ${rotulo(g)}`} onChange={(e) => mudarRegra(g, { nota: e.target.value || undefined })} />
              </div>
            );
          })}
        </Painel>
      )}

      {aba === "departamento" && <>
        <Painel sem_corpo>{chave("transferir_humano", funcoes.transferir_humano && (
          <select className="inp" style={{ marginTop: 8, maxWidth: 340 }} aria-label="Departamento padrão" value={equipe} onChange={(e) => setEquipe(e.target.value)}>
            <option value="">Departamento padrão (quando a regra não escolhe)</option>
            {(equipes.dados ?? []).map((e) => <option key={e.id} value={e.id}>{e.nome}</option>)}
          </select>))}</Painel>
        <Painel titulo="Passar o atendimento para um departamento" sem_corpo>
          <p className="sec func-explica">Marque quando o atendimento deve ir para um departamento da equipe. Sem marcar nada, o lead continua com a IA.</p>
          {[...ATENDIMENTO.filter((g) => g in agente.gatilhos), ...sinais, ...etapasDoAgente.filter((g) => g !== "lead_novo")].map((g) => {
            const r = regras[g] ?? {};
            return (
              <div key={g} className="func-linha-nota">
                <label className="check func-quando"><input type="checkbox" checked={Boolean(r.transferir)}
                  onChange={(e) => mudarRegra(g, { transferir: e.target.checked || undefined, id_equipe: e.target.checked ? r.id_equipe : undefined })} />{rotulo(g)}</label>
                {r.transferir ? <select className="inp" aria-label={`Departamento: ${rotulo(g)}`} value={r.id_equipe ?? ""} onChange={(e) => mudarRegra(g, { id_equipe: e.target.value || undefined })}>
                  <option value="">Departamento padrão do agente</option>
                  {(equipes.dados ?? []).map((e) => <option key={e.id} value={e.id}>{e.nome}</option>)}
                </select> : <span className="muted" style={{ fontSize: 12.5 }}>continua com a IA</span>}
              </div>
            );
          })}
        </Painel>
      </>}

      {aba === "avisos" && <>
        <Painel sem_corpo>{chave("avisos")}</Painel>
        <Painel titulo="Quem recebe e quando">
          <p className="sec" style={{ marginTop: 0 }}>Os avisos por WhatsApp para a equipe (qualificou, não sabe ler, contrato assinado…) e quem recebe cada um ficam em <b>Avisos à equipe</b>, para todos os agentes do escritório.</p>
          <Link className="btn" to="/avisos">Abrir Avisos à equipe<ArrowRight /></Link>
        </Painel>
      </>}

      {aba === "contrato" && <>
        <Painel sem_corpo>{chave("contrato_zapsign")}{chave("buscar_cep")}</Painel>
        <Painel titulo="Quando o contrato andar" sem_corpo>
          <p className="sec func-explica">O card e as etiquetas da assinatura já andam com a troca de agente (aba CRM). Aqui, o que fazer a mais em cada momento do contrato.</p>
          {CONTRATO.filter((g) => g in agente.gatilhos).map((g) => {
            const r = regras[g] ?? {};
            return (
              <div key={g} className="func-linha-regra">
                <span className="func-quando">{rotulo(g)}</span>
                <label className="field"><span className="lbl">Coluna do CRM</span>
                  <select value={r.coluna_crm ?? ""} disabled={!colunas.length} onChange={(e) => mudarRegra(g, { coluna_crm: e.target.value || undefined })}>
                    <option value="">Não mover</option>
                    {colunas.map((c) => <option key={c.id} value={c.id}>{c.titulo}</option>)}
                  </select></label>
                <label className="field"><span className="lbl">Põe a etiqueta</span>
                  <input list="etiquetas-conta" value={(r.adicionar_etiquetas ?? []).join(", ")} placeholder="nenhuma" onChange={(e) => mudarRegra(g, { adicionar_etiquetas: lista(e.target.value) })} /></label>
                <label className="field"><span className="lbl">Nota</span>
                  <input value={r.nota ?? ""} placeholder="Sem nota" onChange={(e) => mudarRegra(g, { nota: e.target.value || undefined })} /></label>
              </div>
            );
          })}
        </Painel>
      </>}

      {/* Resumo do que roda, sempre à vista: o "como funciona" em uma linha por passo. */}
      {aba === "crm" && etapasDoAgente.some((g) => regras[g]) && (
        <Painel titulo="Resumo: o que acontece sozinho" sem_corpo>
          <div className="func-resumo">
            {etapasDoAgente.filter((g) => regras[g]).map((g) => (
              <div key={g}>
                <b>{rotulo(g)}</b><ArrowRight size={14} aria-hidden />
                <span className="chip">{nomeColuna(regras[g].coluna_crm, g)}</span>
                {(regras[g].adicionar_etiquetas ?? []).map((t) => <span key={t} className="chip ac">{t}</span>)}
                {regras[g].nota && <span className="muted">· nota “{regras[g].nota}”</span>}
              </div>
            ))}
          </div>
        </Painel>
      )}
      {janelaConfirmar}
    </div>
  );
}
