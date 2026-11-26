import { useMemo, useState } from "react";
import { BellRing } from "lucide-react";
import { enviar } from "../api";
import { Alerta, Cabecalho, Carregando, Vazio, useAcao, useCarregar, useConfirmar } from "../componentes/ui";

interface Linha {
  id_ativado: string; nome: string; status: string; id_escritorio: string; escritorio: string; id_agente: string;
  situacao_agente: string; sem_numero: boolean; tipo_canal: string | null; produto_catalogo: string | null; modelo_oficial: boolean;
  followup: { ligado: boolean; configurado: boolean; passos: number; resumo: string[] };
}
interface Visao { produtos: Linha[]; totais: { produtos: number; ligados: number; desligados: number } }
interface Resultado { simulado: boolean; ligados?: { id_ativado: string; nome: string; escritorio: string }[]; ligaria?: { nome: string; escritorio: string }[]; avisos?: string[] }

const STATUS: Record<string, string> = { ativo: "ativo", pausado: "pausado", rascunho: "rascunho", erro: "erro" };

/** LawChat › Follow-up: todos os escritórios, follow-up ligado ou desligado por produto, e "Ligar com o padrão"
 *  (um a um ou em lote). Cada ligação fica no histórico (agentesia_alteracoes). Nada liga sozinho. */
export function TelaAdminFollowup() {
  const { dados, erro, recarregar } = useCarregar<Visao>("/admin/followup");
  const { ocupado, executar } = useAcao();
  const [confirmar, janela] = useConfirmar();
  const [filtro, setFiltro] = useState<"todos" | "desligados" | "ligados">("desligados");
  const [marcados, setMarcados] = useState<Set<string>>(new Set());
  const [avisos, setAvisos] = useState<string[]>([]);

  const linhas = useMemo(() => (dados?.produtos ?? []).filter((p) =>
    filtro === "todos" ? true : filtro === "ligados" ? p.followup.ligado : !p.followup.ligado), [dados, filtro]);
  const ativosDesligados = (dados?.produtos ?? []).filter((p) => p.status === "ativo" && !p.followup.ligado);

  const ligar = async (corpo: { ids?: string[]; todos_desligados?: boolean }, descricao: string) => {
    const previa = await executar(() => enviar<Resultado>("/admin/followup/ligar", { ...corpo, simular: true }));
    if (!previa?.ligaria?.length) return;
    const ok = await confirmar({
      titulo: `Ligar o follow-up com o padrão em ${previa.ligaria.length} produto${previa.ligaria.length > 1 ? "s" : ""}?`,
      texto: <>{descricao} Cada produto recebe a cadência e os prompts padrão do produto da biblioteca, e fica registrado no histórico.
        <ul style={{ margin: "8px 0 0", paddingLeft: 18 }}>{previa.ligaria.slice(0, 8).map((p, i) => <li key={i}>{p.escritorio} · {p.nome}</li>)}</ul>
        {previa.ligaria.length > 8 && <div className="muted">e mais {previa.ligaria.length - 8}…</div>}</>,
      confirmar: "Ligar com o padrão",
    });
    if (!ok) return;
    const r = await executar(() => enviar<Resultado>("/admin/followup/ligar", corpo), "Follow-up ligado com o padrão.");
    setAvisos(r?.avisos ?? []);
    setMarcados(new Set());
    recarregar();
  };

  if (!dados) return <Carregando erro={erro} />;
  const alternar = (id: string) => setMarcados((m) => { const n = new Set(m); if (n.has(id)) n.delete(id); else n.add(id); return n; });

  return (
    <>
      {janela}
      <Cabecalho eyebrow="LawChat" titulo="Follow-up dos escritórios"
        texto="O follow-up vem ligado na ativação; aqui aparecem os produtos que ficaram desligados (inclusive os ativados antes dessa regra)."
        acoes={<>
          <button className="btn" disabled={ocupado || marcados.size === 0} onClick={() => ligar({ ids: [...marcados] }, "Os produtos marcados.")}>Ligar os marcados ({marcados.size})</button>
          <button className="btn pri" disabled={ocupado || ativosDesligados.length === 0}
            onClick={() => ligar({ todos_desligados: true }, "Todos os produtos ATIVOS com follow-up desligado.")}><BellRing />Ligar todos os ativos desligados ({ativosDesligados.length})</button>
        </>} />
      <div style={{ display: "flex", gap: 8, alignItems: "center", margin: "0 0 12px", flexWrap: "wrap" }}>
        <span className="chip ok">{dados.totais.ligados} ligados</span>
        <span className="chip">{dados.totais.desligados} desligados</span>
        <span className="sp" style={{ flex: 1 }} />
        <select className="inp" aria-label="Filtrar" value={filtro} onChange={(e) => setFiltro(e.target.value as typeof filtro)} style={{ width: 180 }}>
          <option value="desligados">Só desligados</option><option value="ligados">Só ligados</option><option value="todos">Todos</option>
        </select>
      </div>
      {avisos.length > 0 && <><Alerta tipo="warn" titulo="Ligados, mas confira">{avisos.map((a, i) => <div key={i}>{a}</div>)}</Alerta><div style={{ height: 12 }} /></>}
      {linhas.length === 0 ? <div className="panel"><Vazio icone={<BellRing />}>Nada aqui com esse filtro.</Vazio></div> : (
        <div className="lst"><table>
          <thead><tr><th /><th>Escritório</th><th>Produto</th><th>Situação</th><th>Follow-up</th><th>Cadência</th><th /></tr></thead>
          <tbody>{linhas.map((p) => (
            <tr key={p.id_ativado}>
              <td>{!p.followup.ligado && <input type="checkbox" aria-label={`Marcar ${p.nome}`} checked={marcados.has(p.id_ativado)} onChange={() => alternar(p.id_ativado)} />}</td>
              <td className="t">{p.escritorio}</td>
              <td><div className="t">{p.nome}</div><div className="s">{p.produto_catalogo ?? "—"}{p.tipo_canal === "oficial" ? " · número oficial" : ""}{p.sem_numero ? " · sem número" : ""}</div></td>
              <td><span className="chip">{STATUS[p.status] ?? p.status}</span></td>
              <td><span className={`chip ${p.followup.ligado ? "ok" : ""}`}>{p.followup.ligado ? "ligado" : p.followup.configurado ? "desligado" : "nunca configurado"}</span>
                {p.followup.ligado && p.tipo_canal === "oficial" && !p.modelo_oficial && <div className="s">falta modelo aprovado (24 h)</div>}</td>
              <td className="s">{p.followup.resumo.join(", ")}</td>
              <td style={{ whiteSpace: "nowrap" }}>{!p.followup.ligado && (
                <button className="btn sm" disabled={ocupado} onClick={() => ligar({ ids: [p.id_ativado] }, `${p.escritorio} · ${p.nome}.`)}>Ligar com o padrão</button>
              )}</td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
    </>
  );
}
