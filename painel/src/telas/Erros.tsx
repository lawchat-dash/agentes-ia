import { useState } from "react";
import { Navigate } from "react-router-dom";
import { CheckCircle2 } from "lucide-react";
import { api, quando } from "../api";
import { Cabecalho, Carregando, Situacao, Vazio, useAcao, useCarregar } from "../componentes/ui";
import { useSessao } from "../sessao";

interface Evento {
  id: string; escritorio: string | null; id_lead: string | null; tipo: string; gravidade: string;
  responsavel: string | null; descricao: string; criado_em: string; resolvido_em: string | null;
}

const RESPONSAVEIS: Record<string, [string, string]> = {
  cliente: ["warn", "Do escritório: em geral um token ou cadastro a corrigir em Integrações."],
  cadastro: ["warn", "Cadastro incompleto: número, etapa ou atendimento faltando."],
  provedor: ["info", "LawChat ou provedor de IA fora do ar ou recusando: o sistema tenta de novo sozinho."],
  lead: ["", "Pedido do lead (humano, parar, sinal). Só acompanhar."],
  lawchat: ["bad", "Falha do sistema: a equipe LawChat é avisada."],
};

const ROTULOS: Record<string, string> = { cliente: "Cliente", cadastro: "Cadastro", provedor: "Provedor", lead: "Lead", lawchat: "LawChat" };

/** A tela de Erros é só da equipe LawChat (superadmin): o cliente não tem essa aba. */
export function TelaErros({ todos = false }: { todos?: boolean }) {
  const { lawchat } = useSessao();
  return lawchat ? <ListaDeErros todos={todos} /> : <Navigate to="/" replace />;
}

function ListaDeErros({ todos }: { todos: boolean }) {
  const { escritorio } = useSessao();
  const [abertos, setAbertos] = useState(true);
  const { dados, erro, recarregar } = useCarregar<Evento[]>(`/eventos?abertos=${abertos}&todos_escritorios=${todos}`, [escritorio, abertos, todos]);
  const { ocupado, executar } = useAcao();
  const [filtro, setFiltro] = useState("");
  const lista = (dados ?? []).filter((e) => !filtro || e.responsavel === filtro);

  return (
    <>
      <Cabecalho eyebrow="Acompanhar" titulo={todos ? "Erros de todos os escritórios" : "Erros"}
        texto="Tudo o que deu errado, com o responsável e o que fazer. Marque como resolvido quando tratar." />
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "flex-start", marginBottom: 14 }}>
        <div className="seg" role="radiogroup" aria-label="Situação dos erros">
          <button type="button" role="radio" aria-checked={abertos} className={abertos ? "on" : ""} onClick={() => setAbertos(true)}>Abertos</button>
          <button type="button" role="radio" aria-checked={!abertos} className={!abertos ? "on" : ""} onClick={() => setAbertos(false)}>Todos</button>
        </div>
        <div className="seg" role="radiogroup" aria-label="Filtrar por responsável">
          <button type="button" role="radio" aria-checked={!filtro} className={!filtro ? "on" : ""} onClick={() => setFiltro("")}>Qualquer responsável</button>
          {Object.keys(RESPONSAVEIS).map((r) => (
            <button key={r} type="button" role="radio" aria-checked={filtro === r} className={filtro === r ? "on" : ""} onClick={() => setFiltro(r)}>{ROTULOS[r] ?? r}</button>
          ))}
        </div>
      </div>
      {filtro && <p className="sec" style={{ marginTop: -4 }}>{RESPONSAVEIS[filtro][1]}</p>}
      {!dados ? <Carregando erro={erro} /> : lista.length === 0 ? <div className="panel"><Vazio icone={<CheckCircle2 />}>Nada por aqui.</Vazio></div> : (
        <div className="lst"><table>
          <thead><tr><th>Quando</th>{todos && <th>Escritório</th>}<th>Gravidade</th><th>Responsável</th><th>O que aconteceu</th><th /></tr></thead>
          <tbody>{lista.map((e) => (
            <tr key={e.id}>
              <td className="s num">{quando(e.criado_em)}</td>
              {todos && <td>{e.escritorio ?? "—"}</td>}
              <td><Situacao valor={e.gravidade} /></td>
              <td><span className={`chip ${RESPONSAVEIS[e.responsavel ?? ""]?.[0] ?? ""}`}>{e.responsavel ?? "—"}</span></td>
              <td>{e.descricao}<div className="s mono">{e.tipo}</div></td>
              <td>{!e.resolvido_em ? <button className="btn sm" disabled={ocupado} onClick={() => executar(async () => { await api(`/eventos/${e.id}/resolver`, { metodo: "POST" }); await recarregar(); }, "Marcado como resolvido.")}>Resolvido</button>
                : <span className="chip ok">resolvido</span>}</td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
    </>
  );
}
