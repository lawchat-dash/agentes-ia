// Roteiros (escritório): os roteiros de gravação dos produtos de mídia. Escolhe o produto e grava parte por parte.
// /roteiros            lista de produtos com o progresso
// /roteiros/:produto   gravação (?voltar=<caminho> mostra "Voltar para a ativação", vindo do Passo 3 da ativação)
import { useRef } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ArrowLeft, ArrowRight, Clapperboard, Lock, Mic, Video } from "lucide-react";
import { Cabecalho, Carregando, Vazio, useCarregar } from "@/componentes/ui";
import { RoteiroGravacao } from "@/components/roteiro/RoteiroGravacao";
import type { ProdutoComRoteiro } from "@/components/roteiro/tipos";
import "@/components/roteiro/roteiro.css";

export function TelaRoteirosGravacao() {
  const navegar = useNavigate();
  const { dados, erro } = useCarregar<{ liberado: boolean; motivo: string | null; produtos: ProdutoComRoteiro[] }>("/roteiro-gravacao");
  return (
    <div className="stack">
      <Cabecalho eyebrow="Mídia" titulo="Roteiros de gravação"
        texto="Grave os áudios e vídeos que dão a sua voz ao agente. Cada gravação vai para a Biblioteca e entra no lugar certo do prompt quando você ativar o produto."
        acoes={<Link to="/ferramentas/roteiros" className="btn ghost">Roteiros avulsos</Link>} />
      {!dados ? <Carregando erro={erro} /> : (
        <>
          {!dados.liberado && <div className="rg-bloqueado"><Lock size={16} /><span>{dados.motivo}</span></div>}
          {dados.produtos.length === 0 ? (
            <div className="panel"><Vazio icone={<Clapperboard />}>Nenhum produto com roteiro de gravação ainda.</Vazio></div>
          ) : (
            <div className="rg-produtos">
              {dados.produtos.map((p) => {
                // O que conta para concluir são os obrigatórios (vídeos + áudios principais); objeções são opcionais.
                const obrig = p.obrigatorias ?? p.total;
                const feitas = p.obrigatorias_gravadas ?? p.gravadas;
                const pct = obrig ? Math.round((feitas / obrig) * 100) : 0;
                const tudo = p.gravadas === p.total;
                const pronto = p.concluido ?? tudo;
                return (
                  <button key={p.id} type="button" className="rg-produto" onClick={() => navegar(`/roteiros/${p.id}`)}>
                    <div className="rg-produto-topo">
                      <h3>{p.nome}</h3>
                      <span className={`selo ${pronto ? "ok" : ""}`}>
                        {tudo ? "Concluído" : pronto ? "Pronto · objeções em aberto" : p.gravadas ? "Em andamento" : "Pendente"}</span>
                    </div>
                    <div className="rg-produto-num">
                      <span><Video size={13} /> <b>{p.videos}</b> vídeos</span>
                      <span><Mic size={13} /> <b>{p.audios}</b> áudios</span>
                      {p.ativado && <span>· já ativado</span>}
                    </div>
                    <div className="rg-barra"><i style={{ width: `${pct}%` }} /></div>
                    <div className="rg-produto-pe"><span>{feitas} de {obrig} obrigatórios{p.objecoes ? ` · objeções ${p.objecoes_gravadas ?? 0}/${p.objecoes}` : ""}</span>
                      <span>{p.gravadas ? "Continuar" : "Começar"} <ArrowRight size={14} style={{ verticalAlign: -2 }} /></span></div>
                  </button>
                );
              })}
            </div>
          )}
        </>
      )}
    </div>
  );
}

/** ?voltar= só vale para caminho interno da ativação (/ativar/… ou /meus-produtos/…): "//host" e "/\host" ficam de fora. */
function destinoInterno(voltar: string | null): string | null {
  if (!voltar || !/^\/(?![/\\])/.test(voltar)) return null;
  try {
    const u = new URL(voltar, window.location.origin);
    if (u.origin !== window.location.origin) return null;
    if (!/^\/(ativar|meus-produtos)\//.test(u.pathname)) return null;
    return u.pathname + u.search + u.hash;
  } catch {
    return null;
  }
}

export function TelaRoteiroGravacao() {
  const { produto } = useParams();
  const [busca] = useSearchParams();
  const navegar = useNavigate();
  const destino = destinoInterno(busca.get("voltar"));
  // A saída passa pelo roteiro, que pergunta antes de descartar uma gravação ainda não enviada.
  const sair = useRef<((ir: () => void) => void) | null>(null);
  const irPara = (caminho: string) => { const ir = () => navegar(caminho); if (sair.current) sair.current(ir); else ir(); };
  return (
    <div className="stack">
      {destino && (
        <div className="rg-voltar-ativacao">
          <button type="button" className="btn" onClick={() => irPara(destino)}><ArrowLeft />Voltar para a ativação do produto</button>
          <span className="muted" style={{ fontSize: 12.5 }}>O produto ficou salvo como rascunho: você continua de onde parou.</span>
        </div>
      )}
      <RoteiroGravacao idProduto={produto ?? ""} aoVoltar={() => navegar(destino ?? "/roteiros")} sair={sair} />
    </div>
  );
}
