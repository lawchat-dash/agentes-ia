// Roteiros (escritório): os roteiros de gravação dos produtos de mídia. Escolhe o produto e grava parte por parte.
// /roteiros            lista de produtos com o progresso
// /roteiros/:produto   gravação (?voltar=<caminho> mostra "Voltar para a ativação", vindo do Passo 3 da ativação)
import { useRef, type CSSProperties } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ArrowLeft, ArrowRight, Check, Clapperboard, Headphones, Lock, Mic, Video } from "lucide-react";
import { Cabecalho, Carregando, Vazio, useCarregar } from "@/componentes/ui";
import { RoteiroGravacao } from "@/components/roteiro/RoteiroGravacao";
import type { ProdutoComRoteiro } from "@/components/roteiro/tipos";
import { emojiDoProduto, getCategoryIcon, resolveGradient } from "@/data/categories";
import "@/components/roteiro/roteiro.css";

/** Quadrado do ícone em degradê, o mesmo do cartão do produto na Biblioteca. */
const iconTileStyle = (c1: string, c2: string): CSSProperties => ({
  backgroundImage: `radial-gradient(130% 90% at 25% 0%, rgba(255,255,255,0.42), rgba(255,255,255,0) 58%), linear-gradient(135deg, ${c1} 0%, ${c2} 100%)`,
  boxShadow: `inset 0 1px 0 rgba(255,255,255,0.5), inset 0 -3px 8px ${c2}66, 0 10px 20px -10px ${c1}cc, 0 2px 5px -2px ${c2}66`,
});
const SELO = "h-6 inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider leading-none px-2 rounded-md border whitespace-nowrap shrink-0";
/** "Auxílio Acidente · v2 (novo)" -> "Auxílio Acidente" (o título do cartão é "Roteiro do Auxílio Acidente"). */
const nomeCurto = (nome: string) => nome.replace(/\s*·\s*v\d.*$/i, "").replace(/\s*\(novo\)\s*$/i, "").trim() || nome;

export function TelaRoteirosGravacao() {
  const navegar = useNavigate();
  const { dados, erro } = useCarregar<{ liberado: boolean; motivo: string | null; produtos: ProdutoComRoteiro[] }>("/roteiro-gravacao");
  return (
    <div className="stack">
      <Cabecalho eyebrow="Mídia" titulo="Roteiros de gravação"
        texto="Grave os áudios e vídeos que dão a sua voz ao agente. Cada gravação vai para a Biblioteca e entra no lugar certo do prompt quando você ativar o produto."
        acoes={<button type="button" className="btn" onClick={() => navegar("/roteiros/vozes")}><Headphones />Usar vozes prontas</button>} />
      {!dados ? <Carregando erro={erro} /> : (
        <>
          {!dados.liberado && <div className="rg-bloqueado"><Lock size={16} /><span>{dados.motivo}</span></div>}
          {dados.produtos.length === 0 ? (
            <div className="panel"><Vazio icone={<Clapperboard />}>Nenhum produto com roteiro de gravação ainda.</Vazio></div>
          ) : (
            <div className="grid gap-4 [grid-template-columns:repeat(auto-fill,minmax(280px,1fr))]">
              {dados.produtos.map((p) => {
                // O que conta para concluir são os obrigatórios (vídeos + áudios principais); objeções são opcionais.
                const obrig = p.obrigatorias ?? p.total;
                const feitas = p.obrigatorias_gravadas ?? p.gravadas;
                const pct = obrig ? Math.round((feitas / obrig) * 100) : 0;
                const tudo = p.gravadas === p.total;
                const pronto = p.concluido ?? tudo;
                const [c1, c2] = resolveGradient(p.capa_gradiente, p.categoria);
                const emoji = emojiDoProduto(p.icone);
                const CatIcon = getCategoryIcon(p.categoria ?? undefined);
                const selo: [string, string] = tudo ? ["Concluído", "bg-emerald-500/15 text-emerald-700 border-emerald-500/30"]
                  : pronto ? ["Pronto", "bg-emerald-500/15 text-emerald-700 border-emerald-500/30"]
                  : p.gravadas ? ["Em andamento", "bg-amber-500/15 text-amber-700 border-amber-500/30"]
                  : ["A gravar", "text-muted-foreground bg-muted/60 border-transparent"];
                return (
                  <button key={p.id} type="button" onClick={() => navegar(`/roteiros/${p.id}`)}
                    className="group text-left rounded-2xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-success/70 focus-visible:ring-offset-2">
                    <div className="relative rounded-2xl border border-border bg-card h-full flex flex-col p-4 overflow-hidden transition-all duration-200 hover:border-[var(--cat)] hover:shadow-[0_14px_34px_-16px_var(--catShadow)] hover:-translate-y-1"
                      style={{ ["--cat" as any]: c1, ["--catShadow" as any]: `${c1}59` }}>
                      <div className="absolute -right-10 -top-10 size-32 rounded-full blur-2xl opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none" style={{ background: `radial-gradient(circle, ${c1}38, ${c1}00 70%)` }} />
                      <div className="relative flex items-center justify-between gap-2 mb-3">
                        <div className="relative size-11 shrink-0 rounded-xl grid place-items-center overflow-hidden ring-1 ring-inset ring-white/15 transition-transform duration-300 group-hover:-translate-y-0.5 group-hover:scale-[1.07] group-hover:-rotate-3 motion-reduce:transform-none"
                          style={iconTileStyle(c1, c2)}>
                          {emoji
                            ? <span className="text-[21px] leading-none drop-shadow-[0_1px_1px_rgba(0,0,0,0.25)]" aria-hidden>{emoji}</span>
                            : <CatIcon className="size-[19px] text-white drop-shadow-[0_1px_1px_rgba(0,0,0,0.25)]" strokeWidth={2} />}
                        </div>
                        <div className="flex items-center gap-1.5 min-w-0">
                          {p.ativado && <span className={`${SELO} bg-sky-500/15 text-sky-700 border-sky-500/30`}>Ativado</span>}
                          <span className={`${SELO} ${selo[1]}`}>{tudo || pronto ? <Check className="size-2.5" /> : null}{selo[0]}</span>
                        </div>
                      </div>
                      <h3 className="relative font-semibold text-sm leading-snug line-clamp-1">Roteiro do {nomeCurto(p.nome)}</h3>
                      <p className="relative text-xs text-muted-foreground mt-1 line-clamp-1">{p.nome}</p>
                      <div className="relative flex items-center gap-3 mt-3 text-[10.5px] text-muted-foreground">
                        <span className="inline-flex items-center gap-1"><Video className="size-3" /> {p.videos} {p.videos === 1 ? "vídeo" : "vídeos"}</span>
                        <span className="inline-flex items-center gap-1"><Mic className="size-3" /> {p.audios} áudios</span>
                      </div>
                      <div className="relative mt-3">
                        <div className="flex items-center justify-between text-[11px] mb-1.5">
                          <span className="text-muted-foreground">Obrigatórios</span>
                          <span className="font-semibold tabular-nums whitespace-nowrap" style={{ color: pronto ? "#00852a" : undefined }}>{feitas}/{obrig}</span>
                        </div>
                        <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                          <div className="h-full rounded-full transition-[width] duration-500" style={{ width: `${pct}%`, backgroundImage: `linear-gradient(90deg, ${c1}, ${c2})` }} />
                        </div>
                        {!!p.objecoes && (
                          <div className="flex items-center justify-between text-[11px] mt-1.5 text-muted-foreground">
                            <span>Objeções (opcional)</span><span className="tabular-nums whitespace-nowrap">{p.objecoes_gravadas ?? 0}/{p.objecoes}</span>
                          </div>
                        )}
                      </div>
                      <div className="relative mt-auto pt-3 border-t border-border/60 flex items-center justify-between gap-2" style={{ marginTop: 14 }}>
                        <span className="text-[11px] font-semibold text-muted-foreground group-hover:text-[var(--cat)] transition-colors whitespace-nowrap">
                          {tudo ? "Ver o roteiro" : pronto ? "Gravar as objeções" : p.gravadas ? "Continuar gravando" : "Começar a gravar"}</span>
                        <div className="size-7 shrink-0 rounded-full bg-muted grid place-items-center text-muted-foreground group-hover:text-white transition-all group-hover:[background:var(--cat)]">
                          <ArrowRight className="size-3.5 group-hover:translate-x-0.5 transition-transform" />
                        </div>
                      </div>
                    </div>
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
