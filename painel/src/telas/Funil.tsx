import { useState } from "react";
import { Filter } from "lucide-react";
import { Carregando, Painel, Vazio, useCarregar } from "../componentes/ui";
import { useSessao } from "../sessao";

interface EtapaFunil { codigo: string; nome: string; leads: number; do_inicio: number | null; da_anterior: number | null }
interface Funil {
  agente: { id: string; nome: string } | null;
  agentes: { id: string; nome: string }[];
  dias: number;
  etapas: EtapaFunil[];
  totais: { leads?: number; desqualificados?: number; analise_manual?: number; pausados?: number; assinados?: number };
  origens: { origem: string; leads: number; assinados: number }[];
}

const PERIODOS = [7, 30, 90];

export function PainelFunil() {
  const { escritorio } = useSessao();
  const [dias, setDias] = useState(30);
  const [agente, setAgente] = useState<string>("");
  const caminho = `/funil?dias=${dias}${agente ? `&id_agente=${agente}` : ""}`;
  const { dados, erro } = useCarregar<Funil>(escritorio ? caminho : null, [escritorio, caminho]);

  const acoes = (
    <div className="funil-acoes">
      {dados && dados.agentes.length > 1 && (
        <select className="inp funil-agente" aria-label="Agente do funil" value={agente || dados.agente?.id || ""} onChange={(e) => setAgente(e.target.value)}>
          {dados.agentes.map((a) => <option key={a.id} value={a.id}>{a.nome}</option>)}
        </select>
      )}
      <div className="seg funil-periodo" role="radiogroup" aria-label="Período do funil">
        {PERIODOS.map((p) => <button key={p} type="button" role="radio" aria-checked={dias === p} className={dias === p ? "on" : ""} onClick={() => setDias(p)}>{p} dias</button>)}
      </div>
    </div>
  );

  if (!dados) return <Painel titulo="Funil" acoes={acoes}><Carregando erro={erro} /></Painel>;
  const t = dados.totais;
  const topo = Math.max(1, ...dados.etapas.map((e) => e.leads));
  const semLeads = !t.leads;
  return (
    <Painel titulo={<h3 style={{ display: "flex", gap: 8, alignItems: "center" }}><Filter className="i" />Funil{dados.agente ? <span className="muted" style={{ fontWeight: 400 }}>· {dados.agente.nome}</span> : null}</h3>} acoes={acoes}>
      {semLeads ? <Vazio>Nenhum lead novo nos últimos {dados.dias} dias.</Vazio> : (
        <div className="funil">
          <ol className="funil-etapas" aria-label="Leads por etapa alcançada">
            {dados.etapas.map((e, i) => (
              <li key={e.codigo} style={{ animationDelay: `${i * 60}ms` }}>
                <div className="funil-rotulo"><b>{e.nome}</b>{e.da_anterior !== null && <span className="muted">{e.da_anterior.toFixed(0)}% da anterior</span>}</div>
                <div className="funil-barra" role="img" aria-label={`${e.nome}: ${e.leads} leads`}>
                  <i style={{ width: `${Math.max(2, (e.leads / topo) * 100)}%` }} />
                </div>
                <div className="funil-numero"><b className="num">{e.leads}</b>{e.do_inicio !== null && i > 0 && <span className="muted">{e.do_inicio.toFixed(0)}%</span>}</div>
              </li>
            ))}
          </ol>
          <div className="funil-totais">
            <span><b className="num">{t.leads ?? 0}</b> leads novos</span>
            <span><b className="num" style={{ color: "var(--ok)" }}>{t.assinados ?? 0}</b> contratos assinados{t.leads ? ` (${(((t.assinados ?? 0) / t.leads) * 100).toFixed(1)}%)` : ""}</span>
            <span><b className="num">{t.desqualificados ?? 0}</b> desqualificados</span>
            {(t.analise_manual ?? 0) > 0 && <span><b className="num">{t.analise_manual}</b> em análise da equipe</span>}
            {(t.pausados ?? 0) > 0 && <span><b className="num">{t.pausados}</b> com a IA pausada</span>}
          </div>
          {dados.origens.length > 0 && (
            <div className="lst"><table>
              <thead><tr><th>Origem</th><th className="num">Leads</th><th className="num">Assinados</th><th className="num">Conversão</th></tr></thead>
              <tbody>{dados.origens.map((o) => (
                <tr key={o.origem}><td>{o.origem}</td><td className="num">{o.leads}</td><td className="num">{o.assinados}</td>
                  <td className="num">{o.leads ? `${((o.assinados / o.leads) * 100).toFixed(1)}%` : "—"}</td></tr>
              ))}</tbody>
            </table></div>
          )}
        </div>
      )}
    </Painel>
  );
}
