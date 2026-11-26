import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, BookOpen, Plus, Save } from "lucide-react";
import { api, enviar, quando, type Definicao, type Regra } from "../api";
import { Alerta, Cabecalho, Carregando, Interruptor, Painel, Situacao, Vazio, useAcao, useCarregar } from "../componentes/ui";
import { useSessao } from "../sessao";
import { EditorDefinicao } from "./EditorDefinicao";

interface Linha { id: string; nome: string; descricao: string; produto: string; situacao: string; agentes: number; atualizado_em: string; }
interface Modelo extends Linha {
  config: { definicao?: Definicao; instrucoes?: Record<string, string>; funcoes?: Record<string, boolean>; automacoes?: Record<string, Regra>; honorarios?: string | null; modelo_ia?: string };
  etapas: { codigo: string; nome: string; tipo: string; instrucao_padrao: string }[];
  gatilhos: Record<string, string>;
}

const SITUACAO_MODELO: Record<string, string> = { rascunho: "pendente", publicado: "ok", arquivado: "encerrado" };

export function TelaModelos() {
  const navegar = useNavigate();
  const { dados, erro } = useCarregar<Linha[]>("/admin/modelos");
  const { ocupado, executar } = useAcao();
  const criar = (produto: string) => executar(async () => {
    const inicial = produto === "proprio" ? await api<Definicao>("/modelo-inicial-proprio") : undefined;
    const novo = await enviar<Modelo>("/admin/modelos", { nome: produto === "proprio" ? "Novo modelo" : "Auxílio-Acidente (variação)", produto, definicao: inicial });
    navegar(`/admin/modelos/${novo.id}`);
  });
  return (
    <>
      <Cabecalho eyebrow="Equipe LawChat" titulo="Modelos de agente"
        texto="A biblioteca que os clientes veem ao criar um agente. Crie, teste num escritório e publique. O cliente ativa no número dele e liga as funções que quiser."
        acoes={<>
          <button className="btn" disabled={ocupado} onClick={() => criar("auxilio_acidente")}><Plus />Variação do Auxílio-Acidente</button>
          <button className="btn pri" disabled={ocupado} onClick={() => criar("proprio")}><Plus />Modelo do zero</button>
        </>} />
      <Alerta tipo="info">Também dá para transformar um agente que já funciona bem em modelo: abra o agente e use "Salvar como modelo".</Alerta>
      <div style={{ height: 14 }} />
      {!dados ? <Carregando erro={erro} /> : dados.length === 0 ? <div className="panel"><Vazio icone={<BookOpen />}>A biblioteca está vazia. Os clientes veem só o Auxílio-Acidente e o "começar do zero".</Vazio></div> : (
        <div className="lst"><table>
          <thead><tr><th>Modelo</th><th>Base</th><th>Situação</th><th>Agentes criados</th><th>Atualizado</th></tr></thead>
          <tbody>{dados.map((m) => (
            <tr key={m.id} className="click" onClick={() => navegar(`/admin/modelos/${m.id}`)}>
              <td><div className="t">{m.nome}</div><div className="s">{m.descricao}</div></td>
              <td>{m.produto === "proprio" ? <span className="chip ac">próprio</span> : <span className="chip">Auxílio-Acidente</span>}</td>
              <td><Situacao valor={SITUACAO_MODELO[m.situacao]} texto={m.situacao} /></td>
              <td className="num">{m.agentes}</td>
              <td className="s num">{quando(m.atualizado_em)}</td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
    </>
  );
}

export function TelaModelo() {
  const { id = "" } = useParams();
  const { catalogo } = useSessao();
  const { dados, erro, setDados } = useCarregar<Modelo>(`/admin/modelos/${id}`, [], { guardar: false }); // formulário
  const { ocupado, executar } = useAcao();
  const [form, setForm] = useState<{
    nome: string; descricao: string; situacao: string; honorarios: string; modelo_ia: string;
    definicao?: Definicao; instrucoes: Record<string, string>; funcoes: Record<string, boolean>; automacoes: Record<string, Regra>;
  } | null>(null);
  const [problema, setProblema] = useState<string | null>(null);
  const [etapa, setEtapa] = useState("");

  useEffect(() => {
    if (!dados) return;
    setForm({
      nome: dados.nome, descricao: dados.descricao, situacao: dados.situacao, honorarios: dados.config.honorarios ?? "",
      modelo_ia: dados.config.modelo_ia ?? "gpt-4.1", definicao: dados.config.definicao, instrucoes: dados.config.instrucoes ?? {},
      funcoes: dados.config.funcoes ?? {}, automacoes: dados.config.automacoes ?? {},
    });
    setEtapa((e) => e || dados.etapas[0]?.codigo || "");
  }, [dados]);
  if (!dados || !form) return <Carregando erro={erro} />;

  const salvar = (situacao?: string) => executar(async () => {
    const salvo = await enviar<Modelo>(`/admin/modelos/${id}`, { ...form, situacao: situacao ?? form.situacao, produto: dados.produto }, "PUT");
    setDados(salvo);
  }, situacao === "publicado" ? "Modelo publicado: os clientes já podem ativar." : "Modelo salvo.");
  const etapaAtual = dados.etapas.find((e) => e.codigo === etapa);
  const lista = (t: string) => t.split(",").map((x) => x.trim()).filter(Boolean);

  return (
    <>
      <Link className="btn ghost sm" to="/admin/modelos" style={{ marginBottom: 10 }}><ArrowLeft />Modelos</Link>
      <Cabecalho eyebrow={dados.produto === "proprio" ? "Modelo próprio" : "Variação do Auxílio-Acidente"} titulo={form.nome}
        texto={<><Situacao valor={SITUACAO_MODELO[dados.situacao]} texto={dados.situacao} /> · {dados.agentes} agentes criados a partir dele</>}
        acoes={<>
          <button className="btn" disabled={ocupado || Boolean(problema)} onClick={() => salvar()}><Save />Salvar</button>
          {dados.situacao !== "publicado"
            ? <button className="btn pri" disabled={ocupado || Boolean(problema)} onClick={() => salvar("publicado")}>Publicar</button>
            : <button className="btn" disabled={ocupado} onClick={() => salvar("rascunho")}>Tirar da biblioteca</button>}
        </>} />

      <div className="stack">
        <Painel titulo="Como aparece para o cliente">
          <div className="form cols">
            <label className="field"><span className="lbl">Nome</span><input value={form.nome} onChange={(e) => setForm({ ...form, nome: e.target.value })} /></label>
            <label className="field"><span className="lbl">Modelo de IA sugerido</span>
              <select value={form.modelo_ia} onChange={(e) => setForm({ ...form, modelo_ia: e.target.value })}>
                {(catalogo?.modelos ?? []).map((m) => <option key={m.id} value={m.id}>{m.nome}</option>)}
              </select></label>
          </div>
          <label className="field" style={{ marginTop: 12 }}><span className="lbl">Descrição</span>
            <textarea rows={2} value={form.descricao} onChange={(e) => setForm({ ...form, descricao: e.target.value })} placeholder="Para que serve, em uma ou duas frases." /></label>
          <label className="field" style={{ marginTop: 12 }}><span className="lbl">Honorários sugeridos</span>
            <input value={form.honorarios} onChange={(e) => setForm({ ...form, honorarios: e.target.value })} placeholder="O cliente pode trocar depois" /></label>
        </Painel>

        {dados.produto === "proprio" && form.definicao && (
          <EditorDefinicao valor={form.definicao} aoMudar={(d) => setForm({ ...form, definicao: d })} aoErro={setProblema} />
        )}

        <Painel titulo="Instruções por etapa">
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
            {dados.etapas.map((e) => <button key={e.codigo} className={`btn sm ${etapa === e.codigo ? "pri" : ""}`} onClick={() => setEtapa(e.codigo)}>{e.nome}{form.instrucoes[e.codigo] ? " ●" : ""}</button>)}
          </div>
          {etapaAtual && <textarea className="inp codigo" rows={12} aria-label="Instrução da etapa"
            value={form.instrucoes[etapaAtual.codigo] ?? etapaAtual.instrucao_padrao}
            onChange={(e) => setForm({ ...form, instrucoes: { ...form.instrucoes, [etapaAtual.codigo]: e.target.value === etapaAtual.instrucao_padrao ? "" : e.target.value } })} />}
          <p className="muted" style={{ fontSize: 12, marginBottom: 0 }}>Vazio ou igual ao padrão = usa a instrução padrão. Etapas com ● foram personalizadas.</p>
        </Painel>

        <Painel titulo="Funções ligadas de início" sem_corpo>
          <div className="rows">{(catalogo?.funcoes ?? []).map((f) => (
            <div key={f.id}><Interruptor rotulo={f.nome} ligado={Boolean(form.funcoes[f.id])} desligado={!f.pronta}
              aoMudar={(v) => setForm({ ...form, funcoes: { ...form.funcoes, [f.id]: v } })} />
              <div><b>{f.nome}</b> {!f.pronta && <span className="chip">em breve</span>}<div className="sec" style={{ fontSize: 13 }}>{f.descricao}</div></div></div>
          ))}</div>
        </Painel>

        <Painel titulo="Automações de partida (sem coluna do CRM)" sem_corpo>
          <p className="sec" style={{ margin: "0 16px 8px" }}>Etiquetas, notas e transferência vão junto com o modelo. As colunas do CRM o cliente escolhe no painel dele.</p>
          {Object.entries(dados.gatilhos).map(([g, desc]) => {
            const r = form.automacoes[g] ?? {};
            const mudar = (p: Partial<Regra>) => setForm({ ...form, automacoes: { ...form.automacoes, [g]: { ...r, ...p } } });
            return (
              <div key={g} className="regra">
                <span className={`chip ${Object.keys(r).length ? "ac" : ""}`}>{Object.keys(r).length ? "ativa" : "—"}</span>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 13 }}>Quando: {desc}</div>
                  <div className="form cols" style={{ marginTop: 6 }}>
                    <input className="inp" aria-label="Pôr etiquetas" placeholder="Pôr etiquetas (vírgula)" value={(r.adicionar_etiquetas ?? []).join(", ")} onChange={(e) => mudar({ adicionar_etiquetas: lista(e.target.value) })} />
                    <input className="inp" aria-label="Tirar etiquetas" placeholder="Tirar etiquetas (vírgula)" value={(r.remover_etiquetas ?? []).join(", ")} onChange={(e) => mudar({ remover_etiquetas: lista(e.target.value) })} />
                    <input className="inp" aria-label="Nota" placeholder="Nota no atendimento" value={r.nota ?? ""} onChange={(e) => mudar({ nota: e.target.value || undefined })} />
                  </div>
                  <label className="check" style={{ fontSize: 13, marginTop: 6 }}><input type="checkbox" checked={Boolean(r.transferir)} onChange={(e) => mudar({ transferir: e.target.checked || undefined })} />Transferir para a equipe</label>
                </div>
                <span />
              </div>
            );
          })}
        </Painel>
        {problema && <Alerta tipo="warn">{problema}</Alerta>}
      </div>
    </>
  );
}
