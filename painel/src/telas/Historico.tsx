import { Fragment, useState } from "react";
import { ChevronRight } from "lucide-react";
import { quando } from "../api";
import { Cabecalho, Carregando, Vazio, linhaClicavel, useCarregar } from "../componentes/ui";
import { useSessao } from "../sessao";

interface Alteracao { id: string; tabela: string; acao: string; resumo: string; usuario: string | null; papel: string | null; escritorio: string | null; criado_em: string; antes: unknown; depois: unknown; }

export function TelaHistorico() {
  const { escritorio } = useSessao();
  const { dados, erro } = useCarregar<Alteracao[]>("/alteracoes", [escritorio]);
  const [aberta, setAberta] = useState<string | null>(null);
  return (
    <>
      <Cabecalho eyebrow="Configurar" titulo="Histórico" texto="Quem mudou o quê, com antes e depois. Vale para o escritório e para a equipe LawChat. Clique numa linha (ou Enter) para ver o antes e depois." />
      {!dados ? <Carregando erro={erro} /> : dados.length === 0 ? <div className="panel"><Vazio>Nenhuma alteração ainda.</Vazio></div> : (
        <div className="lst"><table>
          <thead><tr><th aria-hidden style={{ width: 28, paddingRight: 0 }} /><th>Quando</th><th>Quem</th><th>Ação</th><th>O quê</th></tr></thead>
          <tbody>{dados.map((h) => {
            const temDetalhe = h.antes != null || h.depois != null;
            const aberto = aberta === h.id && temDetalhe;
            const alternar = () => setAberta(aberto ? null : h.id);
            return (
              <Fragment key={h.id}>
                <tr {...(temDetalhe ? linhaClicavel(alternar, { expandida: aberto }) : {})}>
                  <td aria-hidden style={{ width: 28, paddingRight: 0, color: "var(--ink-3)" }}>
                    {temDetalhe && <ChevronRight size={15} className="transition-transform duration-200" style={{ transform: aberto ? "rotate(90deg)" : undefined, color: aberto ? "var(--acento)" : undefined }} />}
                  </td>
                  <td className="s num">{quando(h.criado_em)}</td>
                  <td>{h.usuario ?? "sistema"}{(h.papel === "admin_lawchat" || h.papel === "dono_lawchat") && <span className="chip ac" style={{ marginLeft: 6 }}>LawChat</span>}</td>
                  <td><span className="chip">{h.acao.replace(/_/g, " ")}</span></td>
                  <td>{h.resumo}</td>
                </tr>
                {aberto && (
                  <tr><td colSpan={5} style={{ background: "var(--surface-2)" }}>
                    <div className="grid2 animate-in fade-in slide-in-from-top-1 duration-200">
                      <div><span className="lbl">Antes</span><pre className="bloco">{JSON.stringify(h.antes, null, 2)}</pre></div>
                      <div><span className="lbl">Depois</span><pre className="bloco">{JSON.stringify(h.depois, null, 2)}</pre></div>
                    </div>
                  </td></tr>
                )}
              </Fragment>
            );
          })}</tbody>
        </table></div>
      )}
    </>
  );
}
