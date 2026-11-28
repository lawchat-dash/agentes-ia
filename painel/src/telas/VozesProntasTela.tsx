// /roteiros/vozes: vozes prontas (áudios de IA ou da equipe LawChat) para quem não quer gravar.
// A pessoa ouve as vozes, escolhe uma e marca em quais produtos quer usar. Para cada produto, os áudios da voz entram na
// Biblioteca (pasta "Roteiros prontos/<voz>") como gravações do roteiro, e a ativação já sugere cada um.
// Servidor: GET /roteiro-gravacao (produtos) + GET /roteiro-gravacao/{produto}/vozes + POST .../vozes/{voz}/usar.
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, ArrowRight, Check, Headphones, Info, Lock, Mic, Sparkles, Users } from "lucide-react";
import { toast } from "sonner";
import { api, enviar } from "@/api";
import { Cabecalho, Carregando, Vazio } from "@/componentes/ui";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import type { ProdutoComRoteiro, ResultadoUsarVoz, VozPronta, VozesDoProduto } from "@/components/roteiro/tipos";
import { emojiDoProduto, resolveGradient } from "@/data/categories";
import "@/components/roteiro/roteiro.css";
import "@/components/roteiro/vozesProntas.css";

interface NoProduto { produto: ProdutoComRoteiro; voz: VozPronta }
interface VozGeral { voz: VozPronta; produtos: NoProduto[] }
interface Carga { liberado: boolean; motivo: string | null; produtos: ProdutoComRoteiro[]; textoAceite: string; vozes: VozGeral[] }

const nomeCurtoProduto = (nome: string) => nome.replace(/\s*·\s*v\d.*$/i, "").replace(/\s*\(novo\)\s*$/i, "").trim() || nome;
const nomeCurtoVoz = (nome: string) => (nome.split(/\s+[—–-]\s+/)[0] || nome).trim();
const iniciais = (nome: string) => {
  const p = nomeCurtoVoz(nome).split(/\s+/).filter(Boolean);
  return ((p[0]?.[0] ?? "") + (p[1]?.[0] ?? "")).toUpperCase() || "?";
};
const plural = (n: number, um: string, varios: string) => `${n} ${n === 1 ? um : varios}`;

async function carregar(): Promise<Carga> {
  const lista = await api<{ liberado: boolean; motivo: string | null; produtos: ProdutoComRoteiro[] }>("/roteiro-gravacao");
  const respostas = await Promise.all(lista.produtos.map((p) =>
    api<VozesDoProduto>(`/roteiro-gravacao/${p.id}/vozes`).then((r) => ({ p, r })).catch(() => null)));
  const porVoz = new Map<string, VozGeral>();
  let textoAceite = "";
  for (const item of respostas) {
    if (!item) continue;
    textoAceite ||= item.r.texto_aceite;
    for (const v of item.r.vozes) {
      const geral = porVoz.get(v.id) ?? { voz: v, produtos: [] };
      // A amostra que vale é a do "Como funciona" do primeiro produto que tiver.
      if (!geral.voz.amostra && v.amostra) geral.voz = v;
      geral.produtos.push({ produto: item.p, voz: v });
      porVoz.set(v.id, geral);
    }
  }
  return { ...lista, textoAceite, vozes: [...porVoz.values()] };
}

export function TelaVozesProntas() {
  const navegar = useNavigate();
  const [busca] = useSearchParams();
  const preProduto = busca.get("produto");
  const [carga, setCarga] = useState<Carga | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [escolhida, setEscolhida] = useState<VozGeral | null>(null);
  const galeria = useRef<HTMLDivElement>(null);

  const recarregar = () => carregar().then(setCarga).catch((e) => setErro((e as Error).message));
  useEffect(() => { recarregar(); }, []);

  // Um player de cada vez.
  useEffect(() => {
    const el = galeria.current;
    if (!el) return;
    const tocar = (e: Event) => el.querySelectorAll<HTMLMediaElement>("audio, video").forEach((m) => { if (m !== e.target && !m.paused) m.pause(); });
    el.addEventListener("play", tocar, true);
    return () => el.removeEventListener("play", tocar, true);
  }, [carga]);

  const abrir = (v: VozGeral) => {
    galeria.current?.querySelectorAll<HTMLMediaElement>("audio, video").forEach((m) => m.pause());
    setEscolhida(v);
  };

  return (
    <div className="stack">
      <div><button type="button" className="btn" onClick={() => navegar("/roteiros")}><ArrowLeft />Roteiros de gravação</button></div>
      <Cabecalho eyebrow="Mídia" titulo="Vozes prontas"
        texto="Áudios do roteiro já prontos, com voz de IA ou da equipe LawChat. Escolha a voz e o produto: os áudios entram na sua Biblioteca e a ativação já usa cada um. Você pode trocar qualquer áudio pela sua gravação quando quiser." />
      {!carga ? <Carregando erro={erro} /> : (
        <>
          {!carga.liberado && <div className="rg-bloqueado"><Lock size={16} /><span>{carga.motivo}</span></div>}
          {carga.vozes.length === 0 ? (
            <div className="panel vp-vazio">
              <Vazio icone={<Headphones />}>As vozes prontas ainda não estão disponíveis. Enquanto isso, você pode gravar o roteiro com a sua voz.</Vazio>
              <div className="vp-vazio-acao"><button type="button" className="btn pri" onClick={() => navegar("/roteiros")}><Mic />Gravar o roteiro</button></div>
            </div>
          ) : (
            <div className="vp"><div className="vp-galeria" ref={galeria}>
              {carga.vozes.map((g, i) => <CartaoVozGeral key={g.voz.id} geral={g} indice={i} liberado={carga.liberado} motivo={carga.motivo} aoUsar={() => abrir(g)} />)}
            </div></div>
          )}
        </>
      )}
      {carga && escolhida && (
        <DialogoUsar geral={escolhida} textoAceite={carga.textoAceite} preProduto={preProduto}
          aoFechar={() => setEscolhida(null)}
          aoAplicar={(aplicados) => {
            setEscolhida(null);
            recarregar();
            const falta = aplicados.find((p) => !p.ativado);
            if (aplicados.length === 1 && falta) {
              toast.message(`Quer ativar o ${nomeCurtoProduto(falta.nome)} agora?`, {
                action: { label: "Ativar", onClick: () => navegar(`/ativar/${falta.slug}`) },
              });
            }
          }} />
      )}
    </div>
  );
}

function CartaoVozGeral({ geral, indice, liberado, motivo, aoUsar }: {
  geral: VozGeral; indice: number; liberado: boolean; motivo: string | null; aoUsar: () => void;
}) {
  const { voz, produtos } = geral;
  const chips = [voz.tom, voz.genero === "feminina" ? "Feminina" : voz.genero === "masculina" ? "Masculina" : null,
    voz.origem === "equipe" ? "Voz da equipe" : "Voz de IA"].filter(Boolean) as string[];
  const emUso = produtos.filter((p) => p.voz.em_uso);
  return (
    <article className={`vp-voz ${emUso.length ? "em-uso" : ""}`}>
      <header className="vp-voz-topo">
        <span className={`vp-avatar tom-${indice % 4}`} aria-hidden>{iniciais(voz.nome)}</span>
        <div className="vp-voz-nome">
          <b>{voz.nome}</b>
          <div className="vp-chips">{chips.map((c) => <span key={c} className="vp-chip">{c}</span>)}</div>
        </div>
        {emUso.length > 0 && <span className="vp-em-uso"><Check size={12} strokeWidth={3} />Em uso</span>}
      </header>
      {voz.descricao && <p className="vp-voz-desc">{voz.descricao}</p>}
      {voz.amostra && (
        <div className="vp-amostra">
          <span><Headphones size={13} />Amostra: {voz.amostra.titulo}</span>
          {voz.amostra.tipo === "video"
            ? <video src={voz.amostra.url} controls preload="metadata" playsInline />
            : <audio src={voz.amostra.url} controls preload="none" />}
        </div>
      )}
      <div className="vp-cobertura">
        <span><b>{plural(produtos.length, "produto", "produtos")}</b> com esta voz</span>
        <small>{produtos.map((p) => nomeCurtoProduto(p.produto.nome)).join(" · ")}</small>
      </div>
      <p className="vp-aviso"><Info size={13} />Não fala o nome do seu escritório: a apresentação vai por texto.</p>
      <button type="button" className="rg-btn rg-btn--pri vp-usar" disabled={!liberado} title={liberado ? undefined : motivo ?? undefined} onClick={aoUsar}>
        <Sparkles size={15} />Usar esta voz
      </button>
    </article>
  );
}

function DialogoUsar({ geral, textoAceite, preProduto, aoFechar, aoAplicar }: {
  geral: VozGeral; textoAceite: string; preProduto: string | null; aoFechar: () => void; aoAplicar: (p: ProdutoComRoteiro[]) => void;
}) {
  const [marcados, setMarcados] = useState<string[]>(() => {
    if (preProduto && geral.produtos.some((p) => p.produto.id === preProduto)) return [preProduto];
    return geral.produtos.length === 1 ? [geral.produtos[0].produto.id] : [];
  });
  const [pular, setPular] = useState<string[]>([]);
  const [aceite, setAceite] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const escolhidos = useMemo(() => geral.produtos.filter((p) => marcados.includes(p.produto.id)), [geral, marcados]);
  const avisos = escolhidos.flatMap((p) => (p.voz.avisos ?? []).map((a) => ({ ...a, produto: p.produto })));
  const alternar = (lista: string[], id: string) => (lista.includes(id) ? lista.filter((x) => x !== id) : [...lista, id]);

  const confirmar = async () => {
    if (!aceite || escolhidos.length === 0) return;
    setEnviando(true);
    const feitos: ProdutoComRoteiro[] = [];
    let usadas = 0, mantidas = 0;
    try {
      for (const { produto, voz } of escolhidos) {
        const meus = (voz.avisos ?? []).map((a) => a.id_parte).filter((id) => pular.includes(id));
        const r = await enviar<ResultadoUsarVoz>(`/roteiro-gravacao/${produto.id}/vozes/${voz.id}/usar`,
          { aceite: true, substituir_minhas: false, pular_partes: meus });
        usadas += r.usadas; mantidas += r.mantidas;
        feitos.push(produto);
      }
      toast.success(`Voz ${nomeCurtoVoz(geral.voz.nome)} aplicada em ${plural(feitos.length, "produto", "produtos")}`, {
        description: `${plural(usadas, "áudio", "áudios")} na pasta Roteiros prontos da sua Biblioteca.`
          + (mantidas ? ` ${plural(mantidas, "gravação sua foi mantida", "gravações suas foram mantidas")}.` : ""),
      });
      aoAplicar(feitos);
    } catch (e) {
      toast.error(feitos.length ? `Aplicada em ${feitos.length} produto(s), mas parou: ${(e as Error).message}` : (e as Error).message);
      if (feitos.length) aoAplicar(feitos);
    } finally {
      setEnviando(false);
    }
  };

  return (
    <Dialog open onOpenChange={(aberto) => { if (!aberto && !enviando) aoFechar(); }}>
      <DialogContent className="vp-dialogo max-w-lg w-[calc(100vw-2rem)] p-0 gap-0 overflow-hidden rounded-2xl">
        <div className="vp-dialogo-corpo" style={{ maxHeight: "min(82vh, 760px)", overflowY: "auto" }}>
          <div className="vp-dialogo-topo">
            <span className="vp-avatar tom-0" aria-hidden>{iniciais(geral.voz.nome)}</span>
            <div>
              <DialogTitle className="vp-dialogo-tit">Usar a voz {nomeCurtoVoz(geral.voz.nome)}</DialogTitle>
              <DialogDescription className="vp-dialogo-sub">Em qual produto você quer usar esta voz?</DialogDescription>
            </div>
          </div>

          <div className="flex flex-col gap-2" role="group" aria-label="Produtos">
            {geral.produtos.map(({ produto, voz }) => {
              const on = marcados.includes(produto.id);
              const [c1, c2] = resolveGradient(produto.capa_gradiente, produto.categoria);
              const emoji = emojiDoProduto(produto.icone);
              return (
                <label key={produto.id} className={`vp-caixa ${on ? "on" : ""}`} style={{ alignItems: "center" }}>
                  <input type="checkbox" checked={on} onChange={() => setMarcados((l) => alternar(l, produto.id))} />
                  <span className="size-8 shrink-0 rounded-lg grid place-items-center text-[16px]" aria-hidden
                    style={{ backgroundImage: `linear-gradient(135deg, ${c1}, ${c2})` }}>{emoji ?? ""}</span>
                  <span className="min-w-0 flex-1">
                    Roteiro do {nomeCurtoProduto(produto.nome)}
                    <small>
                      {voz.partes_cobertas} de {voz.total_partes} partes com áudio
                      {produto.ativado ? " · produto ativado" : ""}{voz.em_uso ? " · já usa esta voz" : ""}
                    </small>
                  </span>
                </label>
              );
            })}
          </div>

          {avisos.map((a) => {
            const usar = !pular.includes(a.id_parte);
            return (
              <label key={a.id_parte} className={`vp-caixa vp-caixa--leve ${usar ? "on" : ""}`}>
                <input type="checkbox" checked={usar} onChange={() => setPular((l) => alternar(l, a.id_parte))} />
                <span>
                  Usar o áudio de {a.titulo} ({nomeCurtoProduto(a.produto.nome)})
                  <small>{a.aviso} {usar ? "Se os seus valores forem diferentes, desmarque: essa parte vai em texto (ou você grava a sua)."
                    : "Essa parte vai em texto, com os valores do seu prompt."}</small>
                </span>
              </label>
            );
          })}

          <div className="vp-aceite-texto"><Users size={15} /><p>{textoAceite}</p></div>
          <label className={`vp-caixa ${aceite ? "on" : ""}`}>
            <input type="checkbox" checked={aceite} onChange={(e) => setAceite(e.target.checked)} />
            <span>Li e concordo</span>
          </label>
          <p className="vp-aviso" style={{ margin: 0 }}><Info size={13} />As gravações que você já fez continuam valendo: a voz pronta só preenche o que falta.</p>

          <div className="vp-dialogo-botoes">
            <button type="button" className="rg-btn" disabled={enviando} onClick={aoFechar}>Cancelar</button>
            <button type="button" className="rg-btn rg-btn--pri" disabled={!aceite || escolhidos.length === 0 || enviando} onClick={confirmar}>
              <Sparkles size={15} />{enviando ? "Aplicando…" : escolhidos.length > 1 ? `Usar em ${escolhidos.length} produtos` : "Usar esta voz"}
              {!enviando && <ArrowRight size={15} />}
            </button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
