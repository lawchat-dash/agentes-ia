import { Link, useNavigate } from "react-router-dom";
import { Bot, ChevronRight, Plus } from "lucide-react";
import { formatarTelefone, quando, type Agente } from "../api";
import { Cabecalho, Carregando, Situacao, Vazio, linhaClicavel, useCarregar } from "../componentes/ui";
import { useSessao } from "../sessao";

export function TelaAgentes() {
  const { escritorio, catalogo } = useSessao();
  const navegar = useNavigate();
  const { dados, erro } = useCarregar<Agente[]>("/agentes", [escritorio]);
  const nomeModelo = (id: string) => catalogo?.modelos.find((m) => m.id === id)?.nome ?? id;

  return (
    <>
      <Cabecalho eyebrow="Fazer" titulo="Agentes"
        texto="Cada agente atende um número de WhatsApp da Helena. Crie a partir de um modelo pronto ou do zero."
        acoes={<Link className="btn pri" to="/biblioteca"><Plus />Criar agente</Link>} />
      {!dados ? <Carregando erro={erro} /> : dados.length === 0 ? (
        <div className="panel"><Vazio icone={<Bot />}>Nenhum agente ainda. <Link to="/biblioteca">Criar o primeiro</Link></Vazio></div>
      ) : (
        <div className="lst">
          <table>
            <thead><tr><th>Agente</th><th>Número</th><th>Tipo</th><th>Modelo de IA</th><th>Situação</th><th>Criado</th><th aria-hidden /></tr></thead>
            <tbody>
              {dados.map((a) => (
                <tr key={a.id} {...linhaClicavel(() => navegar(`/agentes/${a.id}`), { papel: "link", rotulo: `Abrir o agente ${a.nome}`, classe: "group" })}>
                  <td className="t">{a.nome}</td>
                  <td className="mono">{formatarTelefone(a.numero_canal)}</td>
                  <td>{a.tipo_produto === "proprio" ? <span className="chip ac">Próprio</span> : <span className="chip">Auxílio-Acidente</span>}</td>
                  <td>{nomeModelo(a.modelo)}</td>
                  <td><Situacao valor={a.situacao} /> {a.situacao === "ativo" && <Situacao valor={a.modo} />}</td>
                  <td className="s">{quando(a.criado_em)}</td>
                  <td aria-hidden style={{ width: 36, paddingLeft: 0, color: "var(--ink-3)" }}>
                    <ChevronRight size={16} className="transition-transform duration-200 group-hover:translate-x-0.5 group-hover:text-[var(--acento)] group-focus-visible:translate-x-0.5 group-focus-visible:text-[var(--acento)]" /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
