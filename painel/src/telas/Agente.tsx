import { useEffect, useMemo, useState, type KeyboardEvent as TeclaReact, type ReactNode } from "react";
import { Link, Navigate, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { AlertTriangle, ArrowLeft, BookOpen, CheckCircle2, CircleDashed, FileText, Lock, Pause, Play, Plus, RotateCcw, Save, Send, Trash2, Unlock, Upload, Wrench, XCircle } from "lucide-react";
import { api, enviar, formatarTelefone, quando, type Agente, type Canal, type Definicao, type PassoAtivacao, type Preparacao } from "../api";
import { Alerta, Cabecalho, Carregando, Painel, Situacao, Vazio, useAcao, useCarregar, useConfirmar } from "../componentes/ui";
import { useSessao } from "../sessao";
import { EditorDefinicao } from "./EditorDefinicao";
import { EscolherPapeis, ItensDaBase, PerguntasSemResposta, ResumoFixoOuBuscado, papeisDoAgente } from "./AgenteBase";
import { AbaFollowup, PainelFollowupDoAgente } from "./AgenteFollowup";
import { cartoesDo, estiloIconeSecao, secoesDo } from "./agenteSecoes";
import { HistoricoDoAgente } from "./AgenteHistorico";
import Stepper, { Step } from "@/components/reactbits/Stepper";
import { AbaFuncoes } from "./AgenteFuncoes";

export function TelaAgente() {
  const { id = "", secao } = useParams();
  const [busca] = useSearchParams();
  const navegar = useNavigate();
  const { escritorio, admin } = useSessao();
  const { dados: agente, erro, setDados, recarregar, fresco } = useCarregar<Agente>(`/agentes/${id}`, [escritorio]);
  const { ocupado, executar } = useAcao();

  if (!agente) return <Carregando erro={erro} />;
  const proprio = agente.tipo_produto === "proprio";
  const secoes = secoesDo(proprio, admin);
  const cartoes = cartoesDo(proprio, admin);
  const atual = secoes.find((s) => s.chave === secao);
  // Seção que esta pessoa não vê (ex.: Instruções fora do superadmin) ou que não existe: volta para a página do agente.
  if (secao && !atual) return <Navigate to="/meus-produtos" replace />;
  const aviso_criado = admin
    ? <><b>Agente criado.</b> Agora ajuste as instruções, ligue as funções, teste no Laboratório e ative.</>
    : <><b>Agente criado.</b> As funções e automações já vêm no padrão. Confira e ative.</>;
  const salvarComoModelo = admin ? <button className="btn" disabled={ocupado} onClick={() => executar(async () => {
    const modelo = await api<{ id: string }>(`/admin/modelos/do-agente/${agente.id}`, { metodo: "POST" });
    window.location.assign(`/admin/modelos/${modelo.id}`);
  }, "Modelo criado em rascunho.")}><BookOpen />Salvar como modelo</button> : undefined;

  if (!atual) {
    // A página "Visão geral" do agente saiu (pedido do dono): o agente é gerido pelos cartões de Meus agentes.
    // Agente recém-criado vai direto para a Ativação; o resto volta para a lista.
    return <Navigate to={busca.get("criado") ? `/agentes/${agente.id}/ativacao?criado=1` : "/meus-produtos"} replace />;
  }

  return (
    <>
      <Link className="btn ghost sm" to="/meus-produtos" style={{ marginBottom: 10 }}><ArrowLeft />Meus agentes</Link>
      <Cabecalho eyebrow={`${agente.nome} · ${atual.etiqueta}`} titulo={atual.rotulo}
        texto={<>{atual.descricao} <Situacao valor={agente.situacao} /> {agente.situacao === "ativo" && <Situacao valor={agente.modo} />}</>}
        acoes={atual.chave === "ativacao" ? salvarComoModelo : undefined} />
      {busca.get("criado") && <div style={{ marginBottom: 16 }}><Alerta tipo="ok">{aviso_criado}</Alerta></div>}
      {/* As abas copiam o agente para os formulários delas: esperam o dado do servidor (não a cópia guardada da última visita). */}
      {!fresco ? <Carregando erro={erro} /> : <div key={atual.chave} className="passo-corpo">
        {atual.chave === "ativacao" && <AbaGeral agente={agente} aoSalvar={setDados} />}
        {atual.chave === "instrucoes" && <AbaInstrucoes agente={agente} aoSalvar={recarregar} />}
        {atual.chave === "conhecimento" && <AbaConhecimento agente={agente} aoSalvar={setDados} />}
        {atual.chave === "etapas" && <AbaEtapas agente={agente} aoSalvar={setDados} />}
        {atual.chave === "funcoes" && <AbaFuncoes agente={agente} aoSalvar={setDados} />}
        {atual.chave === "followup" && <AbaFollowup agente={agente} />}
        {atual.chave === "laboratorio" && <AbaLaboratorio agente={agente} />}
        {atual.chave === "historico" && <AbaHistorico agente={agente} />}
      </div>}
    </>
  );
}

// =========================================================================== ativação (assistente em passos)
const ICONE_PASSO: Record<PassoAtivacao["situacao"], JSX.Element> = {
  ok: <CheckCircle2 size={16} color="var(--ok)" />, feito: <Wrench size={16} color="var(--acento)" />,
  aviso: <AlertTriangle size={16} color="var(--warn)" />, erro: <XCircle size={16} color="var(--bad)" />,
  pulado: <CircleDashed size={16} color="var(--ink-3)" />, pendente: <CircleDashed size={16} color="var(--ink-3)" />,
};

/**
 * Os passos do assistente de ativação. Cada um agrupa itens da conferência que o servidor já faz
 * (app/gestao/ativacao.py, `codigos`): o passo fica pronto quando nenhum item dele está com erro, a mesma regra
 * que barra a ativação. Follow-up é opcional (não barra nada); Ativar fica pronto quando o agente está ligado.
 */
interface PassoAssistente { chave: string; titulo: string; descricao: string; codigos: string[]; opcional?: boolean }
const PASSOS_ATIVACAO: PassoAssistente[] = [
  { chave: "numero", titulo: "Número de WhatsApp", descricao: "Conta da LawChat e o número que a IA usa", codigos: ["helena", "canal", "webhook", "alcance"] },
  { chave: "comportamento", titulo: "Comportamento", descricao: "Nome, modelo de IA, honorários e pausas", codigos: ["etapas", "modelo_ia"] },
  { chave: "teste", titulo: "Números de teste", descricao: "Quem recebe resposta no modo teste", codigos: ["teste"] },
  { chave: "integracoes", titulo: "CRM e contrato", descricao: "Etapas do CRM, equipe e ZapSign", codigos: ["crm", "equipe", "contrato"] },
  { chave: "followup", titulo: "Follow-up", descricao: "Opcional: lembrete para quem parou de responder", codigos: [], opcional: true },
  { chave: "ativar", titulo: "Ativar", descricao: "Conferir tudo e ligar o agente", codigos: [] },
];

/** Conferência e ativação (antes o painel "Ativação"): mesmas chamadas, mesmas confirmações. */
function useAtivacao(agente: Agente, aoSalvar: (a: Agente) => void) {
  const { ocupado, executar } = useAcao();
  const modoAlvo = agente.situacao === "ativo" && agente.modo === "teste" ? "producao" : "teste";
  const [prep, setPrep] = useState<Preparacao | null>(agente.ultima_preparacao ?? null);
  const [conferindo, setConferindo] = useState(false);
  const [conferiuUmaVez, setConferiuUmaVez] = useState(false);
  const [confirmar, janelaConfirmar] = useConfirmar();

  const conferir = async (aplicar: boolean) => {
    setConferindo(true);
    try {
      setPrep(aplicar
        ? await enviar<Preparacao>(`/agentes/${agente.id}/ativacao/preparar?modo=${modoAlvo}`, {})
        : await api<Preparacao>(`/agentes/${agente.id}/ativacao/checagem?modo=${modoAlvo}`));
    } finally { setConferindo(false); setConferiuUmaVez(true); }
  };
  useEffect(() => { conferir(false).catch(() => undefined); }, [agente.id, agente.situacao, agente.modo]); // eslint-disable-line react-hooks/exhaustive-deps

  const ativar = async (situacao: "ativo" | "pausado", modo?: "teste" | "producao") => {
    if (modo === "producao" && !(await confirmar({
      titulo: "Ativar para todos?", confirmar: "Ativar para todos",
      texto: <>A IA vai responder <b>qualquer pessoa</b> que escrever para {formatarTelefone(agente.numero_canal)}, não só os números de teste. Dá para voltar para teste quando quiser.</>,
    }))) return;
    if (situacao === "pausado" && !(await confirmar({
      titulo: "Pausar o agente?", confirmar: "Pausar agente", perigo: true,
      texto: <>A IA para de responder neste número. As mensagens continuam chegando na LawChat para a equipe atender.</>,
    }))) return;
    executar(async () => {
      try {
        const salvo = await enviar<Agente>(`/agentes/${agente.id}/ativacao`, { situacao, modo });
        if (salvo.preparacao) setPrep(salvo.preparacao);
        aoSalvar(salvo);
      } catch (erro) {
        await conferir(false).catch(() => undefined);
        throw erro;
      }
    }, situacao === "pausado" ? "Agente pausado." : modo === "producao" ? "Agente respondendo a todos." : "Agente ativo em teste.");
  };
  const preparar = () => executar(() => conferir(true), "Preparação feita.");
  return { prep, conferindo, conferiuUmaVez, conferir, ativar, preparar, modoAlvo, ocupado, janelaConfirmar };
}

/** Itens da conferência (todos, no passo Ativar, ou só os de um passo). */
function ItensConferencia({ passos, vazio }: { passos: PassoAtivacao[]; vazio: string }) {
  return (
    <div className="passos-ativacao" aria-live="polite">
      {passos.length === 0 ? <span className="muted" style={{ padding: 10 }}>{vazio}</span> : passos.map((p) => (
        <div key={p.codigo} className={`passo-at ${p.situacao}`}>
          {ICONE_PASSO[p.situacao]}
          <div><b>{p.titulo}</b><span>{p.detalhe}</span></div>
        </div>
      ))}
    </div>
  );
}

function AbaGeral({ agente, aoSalvar }: { agente: Agente; aoSalvar: (a: Agente) => void }) {
  const { catalogo } = useSessao();
  const [busca] = useSearchParams();
  const { ocupado: salvando, executar } = useAcao();
  const canais = useCarregar<{ canais: Canal[] }>("/integracoes");
  const at = useAtivacao(agente, aoSalvar);
  const doAgente = () => ({
    nome: agente.nome, modelo: agente.modelo, honorarios: agente.honorarios,
    minutos_pausa_humano: agente.minutos_pausa_humano, numeros_teste: agente.numeros_teste.map(formatarTelefone).join("\n"),
    id_canal: agente.id_canal, espera_s: agente.espera_s ?? 0, pausa_sem_volta: Boolean(agente.pausa_sem_volta),
  });
  const [form, setForm] = useState(doAgente);
  const [salvo, setSalvo] = useState(doAgente);
  const mudou = JSON.stringify(form) !== JSON.stringify(salvo);
  const salvar = async () => {
    const ok = await executar(async () => {
      aoSalvar(await enviar<Agente>(`/agentes/${agente.id}`, {
        ...form, numeros_teste: form.numeros_teste.split(/[\n,;]/).map((n) => n.trim()).filter(Boolean),
      }, "PATCH"));
      return true;
    }, "Agente salvo.");
    if (ok) { setSalvo(form); at.conferir(false).catch(() => undefined); }
    return Boolean(ok);
  };

  // Pronto = nenhum item do passo com erro na conferência. Agente já ligado: tudo pronto, salvo erro que apareça agora.
  const ativo = agente.situacao === "ativo";
  const [viuFollowup, setViuFollowup] = useState(false);
  const itensDo = (codigos: string[]) => (at.prep?.passos ?? []).filter((p) => codigos.includes(p.codigo));
  const comErro = (codigos: string[]) => itensDo(codigos).some((p) => p.situacao === "erro");
  const feitos = PASSOS_ATIVACAO.map((p) =>
    p.chave === "ativar" ? ativo
      : p.chave === "followup" ? ativo || Boolean(agente.followup_resumo?.ativo) || viuFollowup
        : (ativo || Boolean(at.prep)) && !comErro(p.codigos));
  const total = PASSOS_ATIVACAO.length;

  // Onde abrir: agente ligado abre no último passo (situação e botões); os outros, no primeiro passo pendente.
  const [passo, setPasso] = useState<number | null>(null);
  useEffect(() => {
    if (passo !== null || (!at.prep && !at.conferiuUmaVez)) return;
    if (ativo && !busca.get("criado")) { setPasso(total); return; }
    const pendente = PASSOS_ATIVACAO.findIndex((p, i) => !p.opcional && !feitos[i]);
    setPasso(pendente < 0 ? total : pendente + 1);
  }, [at.prep, at.conferiuUmaVez]); // eslint-disable-line react-hooks/exhaustive-deps

  const n = passo ?? 1;
  const atual = PASSOS_ATIVACAO[n - 1];
  const temForm = ["numero", "comportamento", "teste"].includes(atual.chave);
  const irPara = (alvo: number) => {
    if (atual.chave === "followup" && alvo > n) setViuFollowup(true);
    setPasso(alvo);
  };
  // Continuar salva antes o que mudou (se falhar, fica no passo com o aviso do erro).
  const continuar = async () => {
    if (temForm && mudou && !(await salvar())) return;
    irPara(Math.min(total, n + 1));
  };
  const erros = at.prep?.passos.filter((p) => p.situacao === "erro").length ?? 0;
  // O botão final chama a mesma ação de antes: pausado -> ativar em teste; em teste -> ativar para todos.
  const acaoFinal = agente.situacao === "pausado"
    ? { texto: "Preparar e ativar em teste", fazer: () => at.ativar("ativo", "teste") }
    : agente.modo === "teste" ? { texto: "Ativar para todos", fazer: () => at.ativar("ativo", "producao") } : null;
  const ocupado = salvando || at.ocupado;

  if (passo === null) {
    return <Painel titulo="Ativação"><Carregando /><p className="muted" style={{ textAlign: "center", margin: 0, fontSize: 12.5 }}>Conferindo o que já está pronto…</p></Painel>;
  }

  const cabeca = (p: PassoAssistente, extra?: ReactNode) => (
    <div className="ativ-passo-cab">
      <div>
        <span className="ativ-passo-num">Passo {PASSOS_ATIVACAO.indexOf(p) + 1} de {total}{p.opcional ? " · opcional" : ""}</span>
        <h3>{p.titulo}</h3>
        <p>{p.descricao}.</p>
      </div>
      {extra}
    </div>
  );
  const botaoSalvar = <button className="btn sm" onClick={salvar} disabled={ocupado || !mudou}><Save />{mudou ? "Salvar" : "Salvo"}</button>;
  const itens = (p: PassoAssistente) => <ItensConferencia passos={itensDo(p.codigos)} vazio={at.conferindo ? "Conferindo…" : "Ainda não conferido."} />;
  const [pNumero, pComportamento, pTeste, pIntegracoes, pFollowup, pAtivar] = PASSOS_ATIVACAO;

  return (
    <section className="panel ativ-assistente">
      <div className="panel-b">
        <div className="ativ-agora">
          <span className="lbl">Agora:</span><Situacao valor={agente.situacao} />{ativo && <Situacao valor={agente.modo} />}
          <span className="muted">{feitos.filter(Boolean).length} de {total} passos prontos</span>
        </div>
        <Stepper step={n} onStepChange={irPara} feitos={feitos} orientation="vertical" width="100%" radius={18}
          nextButtonText={temForm && mudou ? "Salvar e continuar" : "Continuar"}
          completeButtonText={acaoFinal?.texto ?? "Concluir"} mostrarProximo={atual.chave !== "ativar" || Boolean(acaoFinal)}
          backButtonProps={{ disabled: ocupado }}
          nextButtonProps={{
            disabled: ocupado,
            onClick: (e) => { e.preventDefault(); if (atual.chave === "ativar") acaoFinal?.fazer(); else continuar(); },
          }}>
          <Step title={pNumero.titulo} description="Conta da LawChat e o número">
            {cabeca(pNumero, botaoSalvar)}
            <div className="form">
              <label className="field"><span className="lbl">Número de WhatsApp</span>
                <select value={form.id_canal} onChange={(e) => setForm({ ...form, id_canal: e.target.value })}>
                  {(canais.dados?.canais ?? []).filter((c) => c.ativo && (!c.id_agente || c.id_agente === agente.id)).map((c) =>
                    <option key={c.id} value={c.id}>{formatarTelefone(c.numero_normalizado)}</option>)}
                </select>
                <span className="ajuda">O número precisa estar conectado na LawChat. Não achou? Veja em <Link to="/integracoes">Integrações</Link>.</span></label>
              {itens(pNumero)}
              <span className="muted" style={{ fontSize: 12.5 }}>O recebimento das mensagens (webhook) o sistema cria ou corrige sozinho ao ativar.</span>
            </div>
          </Step>
          <Step title={pComportamento.titulo} description="Nome, modelo e honorários">
            {cabeca(pComportamento, botaoSalvar)}
            <div className="form">
              <div className="form cols">
                <label className="field"><span className="lbl">Nome da persona</span><input value={form.nome} onChange={(e) => setForm({ ...form, nome: e.target.value })} /></label>
                <label className="field"><span className="lbl">Modelo de IA</span>
                  <select value={form.modelo} onChange={(e) => setForm({ ...form, modelo: e.target.value })}>
                    {(catalogo?.modelos ?? []).map((m) => <option key={m.id} value={m.id}>{m.nome}</option>)}
                  </select></label>
                <label className="field"><span className="lbl">Pausa quando a equipe fala (minutos)</span>
                  <input type="number" min={0} max={10080} value={form.minutos_pausa_humano} disabled={form.pausa_sem_volta} onChange={(e) => setForm({ ...form, minutos_pausa_humano: Number(e.target.value) })} />
                  <span className="ajuda"><label className="check"><input type="checkbox" checked={form.pausa_sem_volta} onChange={(e) => setForm({ ...form, pausa_sem_volta: e.target.checked })} />Só a equipe religa a IA</label></span></label>
                <label className="field"><span className="lbl">Tempo de resposta (segundos)</span>
                  <select value={form.espera_s} onChange={(e) => setForm({ ...form, espera_s: Number(e.target.value) })}>
                    <option value={0}>Automático (pelo tamanho da mensagem)</option>
                    {[5, 10, 15, 20, 30, 45].map((s) => <option key={s} value={s}>{s} s</option>)}
                  </select></label>
              </div>
              <label className="field"><span className="lbl">Honorários</span>
                <textarea rows={3} value={form.honorarios} onChange={(e) => setForm({ ...form, honorarios: e.target.value })} placeholder="Ex.: 30% do valor recebido, pagos só ao final e só se der certo." />
                <span className="ajuda">A IA só pode citar valores escritos aqui. Qualquer outro número é barrado pela trava.</span></label>
              {itens(pComportamento)}
            </div>
          </Step>
          <Step title={pTeste.titulo} description="Quem recebe resposta no teste">
            {cabeca(pTeste, botaoSalvar)}
            <div className="form">
              <label className="field"><span className="lbl">Números de teste</span>
                <textarea rows={4} value={form.numeros_teste} onChange={(e) => setForm({ ...form, numeros_teste: e.target.value })} placeholder={"Um por linha, com DDD.\n(11) 98888-7777"} />
                <span className="ajuda">Em modo teste, a IA responde só a estes números. Coloque o seu para conversar com o agente antes de liberar para todos.</span></label>
              {itens(pTeste)}
            </div>
          </Step>
          <Step title={pIntegracoes.titulo} description="CRM, equipe e ZapSign">
            {cabeca(pIntegracoes)}
            <div className="form">
              {itens(pIntegracoes)}
              <div className="ativ-links">
                <Link className="btn sm" to={`/agentes/${agente.id}/funcoes`}><Wrench />Funções e automações</Link>
                <Link className="btn sm" to="/integracoes"><Upload />Integrações (CRM e ZapSign)</Link>
              </div>
              <span className="muted" style={{ fontSize: 12.5 }}>As funções já vêm no padrão. Item com “função desligada” não impede a ativação.</span>
            </div>
          </Step>
          <Step title={pFollowup.titulo} description="Opcional">
            {cabeca(pFollowup)}
            {/* Follow-up dentro do agente: ver, ligar/desligar na hora e ir montar a cadência (telas/AgenteFollowup.tsx). */}
            <PainelFollowupDoAgente agente={agente} />
          </Step>
          <Step title={pAtivar.titulo} description="Conferir tudo e ligar">
            {cabeca(pAtivar, <button className="btn sm" onClick={at.preparar} disabled={ocupado || at.conferindo}
              title="Sincroniza o número e cria ou corrige o webhook na LawChat"><Wrench />Preparar agora</button>)}
            <div className="form">
              <ItensConferencia passos={at.prep?.passos ?? []} vazio={at.conferindo ? "Conferindo…" : "Ainda não conferido."} />
              {at.prep && <span className="muted" style={{ fontSize: 12 }}>{at.conferindo ? "Conferindo…" : `Conferido ${quando(at.prep.conferido_em)}${at.prep.por ? ` por ${at.prep.por}` : ""}${at.modoAlvo === "producao" ? ", pensando em produção" : ""}.`}</span>}
              {erros > 0 && <Alerta tipo="warn">{erros === 1 ? "Falta 1 item" : `Faltam ${erros} itens`} antes de ativar. Número e webhook o sistema arruma sozinho ao ativar.</Alerta>}
              {agente.situacao === "pausado" && <p className="muted" style={{ margin: 0, fontSize: 12.5 }}>
                <b>Preparar e ativar em teste</b> sincroniza o número, cria o webhook na LawChat, confere CRM e chave de IA, e liga. Só os números de teste recebem resposta.</p>}
              {ativo && agente.modo === "teste" && <p className="muted" style={{ margin: 0, fontSize: 12.5 }}>
                <b>Ativar para todos</b>: a IA passa a responder qualquer pessoa que escrever neste número.</p>}
              {ativo && agente.modo === "producao" && <Alerta tipo="ok">O agente está ligado e respondendo a todos.</Alerta>}
              {ativo && <div className="ativ-links">
                <button className="btn bad" onClick={() => at.ativar("pausado")} disabled={ocupado}><Pause />Pausar agente</button>
                {agente.modo === "producao" && <button className="btn" onClick={() => at.ativar("ativo", "teste")} disabled={ocupado}><Play />Voltar para teste</button>}
              </div>}
            </div>
          </Step>
        </Stepper>
      </div>
      {at.janelaConfirmar}
    </section>
  );
}

// =========================================================================== conhecimento
function AbaConhecimento({ agente, aoSalvar }: { agente: Agente; aoSalvar: (a: Agente) => void }) {
  const { ocupado, executar } = useAcao();
  const base = agente.conhecimento ?? { faq: [], objecoes: [], dados_escritorio: "" };
  const [faq, setFaq] = useState(base.faq);
  const [objecoes, setObjecoes] = useState(base.objecoes);
  const [dados, setDados] = useState(base.dados_escritorio);
  // Os limites da busca (teto_documentos...) vão junto: o PATCH troca o bloco de conhecimento inteiro.
  const salvar = () => executar(async () => aoSalvar(await enviar<Agente>(`/agentes/${agente.id}`,
    { conhecimento: { ...base, faq, objecoes, dados_escritorio: dados } }, "PATCH")), "Conhecimento salvo. Vale a partir da próxima mensagem.");
  const recarregarAgente = () => executar(async () => {
    const novo = await api<Agente>(`/agentes/${agente.id}`);
    setFaq(novo.conhecimento?.faq ?? []); aoSalvar(novo);
  });
  return (
    <div className="stack">
      <Painel titulo="Perguntas frequentes" acoes={<><button className="btn sm" onClick={() => setFaq([...faq, { pergunta: "", resposta: "" }])}><Plus />Pergunta</button>
        <button className="btn pri sm" onClick={salvar} disabled={ocupado}><Save />Salvar conhecimento</button></>}>
        <ResumoFixoOuBuscado agente={agente} faq={faq} objecoes={objecoes} />
        <ItensDaBase agente={agente} itens={faq} campo="pergunta" rotulos={["Pergunta", "Resposta"]} vazio="Ex.: Onde fica o escritório?"
          aoMudar={setFaq} />
      </Painel>
      <Painel titulo="Objeções" acoes={<button className="btn sm" onClick={() => setObjecoes([...objecoes, { objecao: "", resposta: "" }])}><Plus />Objeção</button>}>
        <ItensDaBase agente={agente} itens={objecoes} campo="objecao" rotulos={["Se o lead disser", "Responda assim"]} vazio="Ex.: “É golpe?”, “Vou pensar”."
          aoMudar={setObjecoes} />
      </Painel>
      <Painel titulo="Dados do escritório">
        <textarea className="inp" rows={6} aria-label="Dados do escritório" value={dados} onChange={(e) => setDados(e.target.value)} placeholder="Endereço, horário, advogados, OAB…" />
      </Painel>
      <PerguntasSemResposta agente={agente} aoVirarFaq={recarregarAgente} />
      <Documentos agente={agente} />
    </div>
  );
}

interface Documento { id: string; nome: string; formato: string; tamanho_bytes: number; caracteres: number; criado_em: string; previa?: string; papeis?: string[] }

function lerArquivo(arquivo: File): Promise<string> {
  return new Promise((ok, falha) => {
    const leitor = new FileReader();
    leitor.onload = () => ok(String(leitor.result));
    leitor.onerror = () => falha(new Error("Não foi possível ler o arquivo."));
    leitor.readAsDataURL(arquivo);
  });
}

function Documentos({ agente }: { agente: Agente }) {
  const { dados, recarregar } = useCarregar<Documento[]>(`/agentes/${agente.id}/documentos`, [agente.id]);
  const { ocupado, executar } = useAcao();
  const [arrastando, setArrastando] = useState(false);
  const [confirmar, janelaConfirmar] = useConfirmar();
  const mandar = (arquivos: FileList | null) => {
    if (!arquivos?.length) return;
    executar(async () => {
      for (const arquivo of Array.from(arquivos)) {
        if (arquivo.size > 8 * 1024 * 1024) throw new Error(`"${arquivo.name}" passa de 8 MB.`);
        await enviar(`/agentes/${agente.id}/documentos`, { nome: arquivo.name, conteudo_base64: await lerArquivo(arquivo), mime: arquivo.type || null });
      }
      recarregar();
    }, arquivos.length > 1 ? "Documentos lidos e guardados." : "Documento lido e guardado.");
  };
  const apagar = async (d: Documento) => {
    if (!(await confirmar({ titulo: "Tirar este documento?", confirmar: "Tirar documento", perigo: true,
      texto: <>A IA deixa de consultar <b>{d.nome}</b> a partir da próxima mensagem. Para voltar, é preciso enviar o arquivo de novo.</> }))) return;
    executar(async () => { await api(`/agentes/${agente.id}/documentos/${d.id}`, { metodo: "DELETE" }); recarregar(); }, "Documento tirado da base.");
  };
  const kb = (n: number) => n > 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`;
  const papeis = papeisDoAgente(agente);
  const trocarPapeis = (d: Documento, valor: string[]) => executar(async () => {
    await enviar(`/agentes/${agente.id}/documentos/${d.id}/papeis`, { papeis: valor }, "PUT"); recarregar();
  }, "Papéis do documento salvos.");
  // Mesmo limite do motor: os documentos do papel até 2.000 caracteres ficam fixos no prompt; acima, são buscados.
  const fixo = (d: Documento) => (dados ?? []).filter((x) => !x.papeis?.length || !d.papeis?.length || x.papeis.some((p) => d.papeis?.includes(p)))
    .reduce((s, x) => s + x.caracteres, 0) <= 2000;
  return (
    <Painel titulo="Documentos" acoes={<label className={`btn sm ${ocupado ? "disabled" : ""}`}><Upload />Enviar arquivo
      <input type="file" multiple hidden accept=".pdf,.docx,.xlsx,.txt,.md,.csv" disabled={ocupado} onChange={(e) => { mandar(e.target.files); e.target.value = ""; }} /></label>}>
      <div className={`soltar ${arrastando ? "on" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setArrastando(true); }} onDragLeave={() => setArrastando(false)}
        onDrop={(e) => { e.preventDefault(); setArrastando(false); mandar(e.dataTransfer.files); }}>
        <p className="sec" style={{ margin: 0 }}>Tabela de valores, perguntas do escritório, regras do benefício… A IA lê o texto e consulta só os trechos que combinam com a conversa. Arraste arquivos aqui (PDF, Word, Excel ou texto, até 8 MB). PDF escaneado não tem texto para ler.</p>
        {!dados ? <Carregando /> : dados.length === 0 ? <Vazio icone={<FileText />}>Nenhum documento ainda.</Vazio> : (
          <div className="rows">
            {dados.map((d) => (
              <div key={d.id}>
                <FileText className="i" />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <b>{d.nome}</b>
                  <div className="muted" style={{ fontSize: 12 }}>{d.formato.toUpperCase()} · {kb(d.tamanho_bytes)} · {d.caracteres.toLocaleString("pt-BR")} caracteres lidos · {quando(d.criado_em)}</div>
                  {d.previa && <div className="muted" style={{ fontSize: 12, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{d.previa}</div>}
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center", marginTop: 4 }}>
                    <span className={`chip ${fixo(d) ? "ok" : "info"}`}>{fixo(d) ? "Sempre no prompt" : "Buscado quando perguntarem"}</span>
                    {papeis.length > 1 && <EscolherPapeis papeis={papeis} valor={d.papeis} rotulo={`Papéis de ${d.nome}`} aoMudar={(v) => trocarPapeis(d, v)} />}
                  </div>
                </div>
                <button className="btn sm ghost" aria-label={`Tirar ${d.nome}`} disabled={ocupado} onClick={() => apagar(d)}><Trash2 /></button>
              </div>
            ))}
          </div>
        )}
      </div>
      {janelaConfirmar}
    </Painel>
  );
}

// =========================================================================== instruções
function AbaInstrucoes({ agente, aoSalvar }: { agente: Agente; aoSalvar: () => void }) {
  const { admin } = useSessao();
  const { ocupado, executar } = useAcao();
  const [confirmar, janelaConfirmar] = useConfirmar();
  const [codigo, setCodigo] = useState(agente.etapas[0]?.codigo ?? "");
  const etapa = agente.etapas.find((e) => e.codigo === codigo) ?? agente.etapas[0];
  const [texto, setTexto] = useState(etapa?.instrucao ?? etapa?.instrucao_padrao ?? "");
  useEffect(() => { setTexto(etapa?.instrucao ?? etapa?.instrucao_padrao ?? ""); }, [etapa?.codigo, etapa?.instrucao]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!etapa) return <Vazio>Este agente não tem etapas.</Vazio>;
  const bloqueada = etapa.instrucao_travada && !admin;
  const salvar = (corpo: { instrucao: string | null; travada?: boolean }, aviso: string) =>
    executar(async () => { await enviar(`/agentes/${agente.id}/etapas/${etapa.codigo}`, corpo, "PUT"); aoSalvar(); }, aviso);

  return (
    <div className="two">
      <Painel titulo={<h3>{etapa.nome} <span className="chip" style={{ marginLeft: 6 }}>{etapa.tipo === "terminal" ? "encerramento" : "conversa"}</span></h3>}
        acoes={<>
          {admin && <button className="btn sm" disabled={ocupado} onClick={() => salvar({ instrucao: texto, travada: !etapa.instrucao_travada }, etapa.instrucao_travada ? "Instrução destravada." : "Instrução travada: o cliente não edita mais.")}>
            {etapa.instrucao_travada ? <><Unlock />Destravar</> : <><Lock />Travar</>}</button>}
          <button className="btn sm" disabled={ocupado || bloqueada || !etapa.personalizada} onClick={async () => {
            if (await confirmar({ titulo: "Voltar à instrução padrão?", confirmar: "Voltar ao padrão", perigo: true,
              texto: <>A instrução personalizada da etapa <b>{etapa.nome}</b> é descartada e a IA passa a usar a padrão do modelo.</> }))
              salvar({ instrucao: null }, "Voltou à instrução padrão.");
          }}><RotateCcw />Voltar ao padrão</button>
          <button className="btn pri sm" disabled={ocupado || bloqueada} onClick={() => salvar({ instrucao: texto }, "Instrução salva.")}><Save />Salvar</button>
        </>}>
        {bloqueada && <div style={{ marginBottom: 10 }}><Alerta tipo="warn">Instrução travada pela equipe LawChat. Para mudar, fale com o suporte.</Alerta></div>}
        <textarea className="inp codigo" rows={20} value={texto} readOnly={bloqueada} onChange={(e) => setTexto(e.target.value)} aria-label="Instrução da etapa" />
        <p className="muted" style={{ fontSize: 12, marginBottom: 0 }}>
          {etapa.personalizada ? "Instrução personalizada." : "Instrução padrão do modelo."} As regras de tom (calma, uma pergunta por vez, sem promessas) valem para todas as etapas e não precisam ser repetidas aqui.
        </p>
      </Painel>
      <Painel titulo="Etapas" sem_corpo>
        <div className="rows">
          {agente.etapas.map((e) => (
            <button key={e.codigo} onClick={() => setCodigo(e.codigo)} aria-pressed={e.codigo === etapa.codigo}
              className={`btn ghost ${e.codigo === etapa.codigo ? "!bg-[var(--acento-suave)] shadow-[inset_3px_0_0_var(--acento)]" : ""}`}
              style={{ borderRadius: 0, justifyContent: "flex-start", fontWeight: e.codigo === etapa.codigo ? 700 : 500, color: e.codigo === etapa.codigo ? "#0B7A2A" : undefined }}>
              <span className="chip num">{e.ordem}</span>{e.nome}
              <span style={{ marginLeft: "auto", display: "flex", gap: 4 }}>
                {e.personalizada && <span className="chip ac">editada</span>}
                {e.instrucao_travada && <span className="chip warn"><Lock size={10} />travada</span>}
              </span>
            </button>
          ))}
        </div>
      </Painel>
      {janelaConfirmar}
    </div>
  );
}

// =========================================================================== etapas e regras (agente próprio)
function AbaEtapas({ agente, aoSalvar }: { agente: Agente; aoSalvar: (a: Agente) => void }) {
  const { ocupado, executar } = useAcao();
  const [definicao, setDefinicao] = useState<Definicao | null>(agente.definicao);
  const [problema, setProblema] = useState<string | null>(null);
  if (!definicao) return <Carregando />;
  const salvar = () => executar(async () => aoSalvar(await enviar<Agente>(`/agentes/${agente.id}/definicao`, { definicao }, "PUT")), "Etapas e regras salvas.");
  return (
    <>
      <div style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "center" }}>
        <p className="sec" style={{ margin: 0, flex: 1 }}>Vale na hora, inclusive com o agente rodando. Etapa com conversa parada não pode ser removida.</p>
        <button className="btn pri" onClick={salvar} disabled={ocupado || Boolean(problema)}><Save />Salvar etapas e regras</button>
      </div>
      <EditorDefinicao valor={definicao} aoMudar={setDefinicao} aoErro={setProblema} />
    </>
  );
}

// funções e automações: telas/AgenteFuncoes.tsx (abas, já com o padrão automático)

// =========================================================================== laboratório
interface Turno {
  situacao: string; motivo: string; etapa_antes: string; etapa_depois: string; estado_lead: string | null; motivo_estado: string | null;
  mensagens: { tipo: string; texto?: string; chave?: string }[];
  fatos_novos: { chave: string; valor: unknown; trecho: string }[];
  fatos_rejeitados: { chave: string; valor: unknown; trecho: string; motivo: string }[];
  decisoes: { funcao: string; resultado: string; motivo: string; faltam: string[] }[];
  faltam: string[]; reprovacoes: { codigo: string; orientacao: string }[][];
  chamadas: { papel: string; modelo: string; tokens_entrada: number; tokens_saida: number; custo_usd: number; duracao_ms: number; sucesso: boolean; erro: string | null }[];
  contexto: { etapa?: { sistema: string; conteudo: string } };
}

function AbaLaboratorio({ agente }: { agente: Agente }) {
  const [conversa, setConversa] = useState<string | null>(null);
  const [mensagens, setMensagens] = useState<{ autor: string; texto: string; turno?: Turno }[]>([]);
  const [texto, setTexto] = useState("");
  const [turno, setTurno] = useState<Turno | null>(null);
  const [fatos, setFatos] = useState<Record<string, unknown>>({});
  const [etapa, setEtapa] = useState(agente.etapas[0]?.codigo ?? "");
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const custo = useMemo(() => mensagens.reduce((s, m) => s + (m.turno?.chamadas.reduce((a, c) => a + c.custo_usd, 0) ?? 0), 0), [mensagens]);

  async function mandar() {
    const valor = texto.trim();
    if (!valor || ocupado) return;
    setTexto(""); setErro(null); setOcupado(true);
    setMensagens((m) => [...m, { autor: "lead", texto: valor }]);
    try {
      const r = await enviar<{ id_conversa: string; turno: Turno | null; etapa: string; fatos: Record<string, unknown> }>(
        `/agentes/${agente.id}/laboratorio`, { texto: valor, id_conversa: conversa });
      setConversa(r.id_conversa); setEtapa(r.etapa); setFatos(r.fatos); setTurno(r.turno);
      const t = r.turno;
      if (t) {
        const respostas = t.mensagens.map((m) => ({ autor: "ia", texto: m.tipo === "texto" ? m.texto ?? "" : `[mídia: ${m.chave}]`, turno: t }));
        const notas = t.situacao === "erro" ? [{ autor: "nota", texto: `A IA falhou (${t.motivo}).` }]
          : t.estado_lead ? [{ autor: "nota", texto: `Lead ${t.estado_lead}: ${t.motivo_estado}` }] : [];
        setMensagens((m) => [...m, ...respostas, ...notas]);
      }
    } catch (e) {
      setErro((e as Error).message);
    } finally {
      setOcupado(false);
    }
  }

  return (
    <div className="two">
      <Painel titulo="Converse como se fosse o lead" acoes={<>
        <span className="chip mono">US$ {custo.toFixed(4)}</span>
        <span className="chip ac">{agente.etapas.find((e) => e.codigo === etapa)?.nome ?? etapa}</span>
        <button className="btn sm" onClick={() => { setConversa(null); setMensagens([]); setTurno(null); setFatos({}); setEtapa(agente.etapas[0]?.codigo ?? ""); }}>Nova conversa</button>
      </>}>
        <p className="muted" style={{ marginTop: 0, fontSize: 12.5 }}>Usa a configuração salva deste agente. Nada é enviado ao WhatsApp e nada fica nas conversas.</p>
        <div className="chat" aria-live="polite">
          {mensagens.length === 0 && <div className="bolha nota">Escreva a primeira mensagem do lead.</div>}
          {mensagens.map((m, i) => (
            <div key={i} className={`bolha ${m.autor} ${m.turno ? "transition-shadow hover:shadow-[0_0_0_2px_var(--acento-suave)]" : ""}`}
              style={{ cursor: m.turno ? "pointer" : undefined, boxShadow: m.turno && m.turno === turno ? "0 0 0 2px color-mix(in srgb, var(--acento) 45%, transparent)" : undefined }}
              {...(m.turno ? {
                role: "button", tabIndex: 0, "aria-pressed": m.turno === turno, title: "Ver por dentro deste turno",
                onClick: () => m.turno && setTurno(m.turno),
                onKeyDown: (e: TeclaReact) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); if (m.turno) setTurno(m.turno); } },
              } : {})}>{m.texto}</div>
          ))}
          {ocupado && <div className="bolha nota">pensando…</div>}
        </div>
        {erro && <div style={{ marginTop: 10 }}><Alerta tipo="bad">{erro}</Alerta></div>}
        <form style={{ display: "flex", gap: 8, marginTop: 10 }} onSubmit={(e) => { e.preventDefault(); mandar(); }}>
          <textarea className="inp" rows={2} value={texto} onChange={(e) => setTexto(e.target.value)} aria-label="Mensagem do lead"
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); mandar(); } }} placeholder="Enter envia; Shift+Enter quebra a linha" />
          <button className="btn pri" disabled={ocupado}><Send />Enviar</button>
        </form>
      </Painel>

      <div className="stack">
        <Painel titulo="Fatos do lead" sem_corpo>
          {Object.keys(fatos).length === 0 ? <Vazio>Nenhum fato ainda.</Vazio> : (
            <div className="rows">{Object.entries(fatos).map(([k, v]) => <div key={k}><span className="mono" style={{ flex: 1 }}>{k}</span><b>{String(v)}</b></div>)}</div>
          )}
        </Painel>
        {turno && <DetalheTurno turno={turno} />}
      </div>
    </div>
  );
}

function DetalheTurno({ turno }: { turno: Turno }) {
  const [verContexto, setVerContexto] = useState(false);
  return (
    <Painel titulo="Por dentro deste turno">
      <div className="form" style={{ gap: 10 }}>
        <div><span className="lbl">Etapa: </span><span className="mono">{turno.etapa_antes}</span> → <b className="mono">{turno.etapa_depois}</b> <span className="muted">({turno.motivo})</span></div>
        {turno.fatos_novos.length > 0 && <div><span className="lbl">Fatos novos</span>
          {turno.fatos_novos.map((f) => <div key={f.chave} style={{ fontSize: 13 }}><span className="mono">{f.chave}</span> = <b>{String(f.valor)}</b> <span className="muted">“{f.trecho}”</span></div>)}</div>}
        {turno.fatos_rejeitados.length > 0 && <Alerta tipo="warn"><b>Descartados pelo código:</b> {turno.fatos_rejeitados.map((f) => `${f.chave} (${f.motivo})`).join(", ")}</Alerta>}
        {turno.decisoes.map((d, i) => <div key={i} style={{ fontSize: 13 }}><span className="chip">{d.funcao}</span> <b>{d.resultado}</b> {d.motivo && <span className="muted">· {d.motivo}</span>}</div>)}
        {turno.faltam.length > 0 && <div style={{ fontSize: 13 }}><span className="lbl">Próxima pergunta: </span><span className="mono">{turno.faltam[0]}</span></div>}
        {turno.reprovacoes.map((lista, i) => lista.length > 0
          ? <Alerta key={i} tipo="warn"><b>Tentativa {i + 1} barrada:</b> {lista.map((r) => r.orientacao).join(" ")}</Alerta>
          : <div key={i} className="chip ok" style={{ alignSelf: "flex-start" }}>tentativa {i + 1} aprovada nas travas</div>)}
        <div className="lst"><table>
          <thead><tr><th>Chamada</th><th>Modelo</th><th>Tokens</th><th>Tempo</th><th>Custo</th></tr></thead>
          <tbody>{turno.chamadas.map((c, i) => (
            <tr key={i}><td>{c.papel}</td><td className="mono">{c.modelo}</td><td className="num">{c.tokens_entrada}/{c.tokens_saida}</td>
              <td className="num">{(c.duracao_ms / 1000).toFixed(1)} s</td><td className="num">{c.sucesso ? `US$ ${c.custo_usd.toFixed(4)}` : <span style={{ color: "var(--bad)" }}>{c.erro}</span>}</td></tr>
          ))}</tbody>
        </table></div>
        {turno.contexto.etapa && <>
          <button className="btn sm" style={{ alignSelf: "flex-start" }} onClick={() => setVerContexto(!verContexto)}>{verContexto ? "Esconder" : "Ver"} o que a IA recebeu</button>
          {verContexto && <><pre className="bloco">{turno.contexto.etapa.sistema}</pre><pre className="bloco">{turno.contexto.etapa.conteudo}</pre></>}
        </>}
      </div>
    </Painel>
  );
}

// =========================================================================== histórico
function AbaHistorico({ agente }: { agente: Agente }) {
  return <HistoricoDoAgente agente={agente} />;
}
