// Roteiros (escritório): os roteiros de gravação dos produtos de mídia. Escolhe o produto e grava parte por parte.
// /roteiros            lista de produtos com o progresso
// /roteiros/:produto   gravação (?voltar=<caminho> mostra "Voltar para a ativação", vindo do Passo 3 da ativação)
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
                const pct = p.total ? Math.round((p.gravadas / p.total) * 100) : 0;
                return (
                  <button key={p.id} type="button" className="rg-produto" onClick={() => navegar(`/roteiros/${p.id}`)}>
                    <div className="rg-produto-topo">
                      <h3>{p.nome}</h3>
                      <span className={`selo ${p.gravadas === p.total ? "ok" : ""}`}>
                        {p.gravadas === p.total ? "Concluído" : p.gravadas ? "Em andamento" : "Pendente"}</span>
                    </div>
                    <div className="rg-produto-num">
                      <span><Video size={13} /> <b>{p.videos}</b> vídeos</span>
                      <span><Mic size={13} /> <b>{p.audios}</b> áudios</span>
                      {p.ativado && <span>· já ativado</span>}
                    </div>
                    <div className="rg-barra"><i style={{ width: `${pct}%` }} /></div>
                    <div className="rg-produto-pe"><span>{p.gravadas} de {p.total} enviados</span>
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

export function TelaRoteiroGravacao() {
  const { produto } = useParams();
  const [busca] = useSearchParams();
  const navegar = useNavigate();
  const voltar = busca.get("voltar");
  const destino = voltar && voltar.startsWith("/") ? voltar : null;   // só caminho interno
  return (
    <div className="stack">
      {destino && (
        <div className="rg-voltar-ativacao">
          <button type="button" className="btn" onClick={() => navegar(destino)}><ArrowLeft />Voltar para a ativação do produto</button>
          <span className="muted" style={{ fontSize: 12.5 }}>O produto ficou salvo como rascunho: você continua de onde parou.</span>
        </div>
      )}
      <RoteiroGravacao idProduto={produto ?? ""} aoVoltar={() => navegar(destino ?? "/roteiros")} />
    </div>
  );
}
