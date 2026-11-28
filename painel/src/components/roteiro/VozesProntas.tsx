// Vozes prontas: áudios do roteiro já gravados pela LawChat (voz de IA ou da equipe). O escritório que não quer gravar
// ouve as vozes, aceita que são modelos usados por outros escritórios e aplica uma: os áudios entram na Biblioteca dele
// (pasta "Roteiros prontos/<voz>") como se tivesse gravado. Servidor: app/gestao/rotas_vozes_prontas.py.
import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Headphones, Info, Mic, Sparkles, Users } from "lucide-react";
import { toast } from "sonner";
import { enviar } from "@/api";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { NOME_SECAO, type ResultadoUsarVoz, type VozPronta, type VozesDoProduto } from "./tipos";
import "./vozesProntas.css";

export type ModoRoteiro = "gravar" | "pronta";

/** Os dois caminhos do roteiro: gravar com a própria voz ou usar uma voz pronta. */
export function EscolhaModo({ modo, aoEscolher }: { modo: ModoRoteiro; aoEscolher: (m: ModoRoteiro) => void }) {
  const opcoes: { id: ModoRoteiro; Icone: typeof Mic; titulo: string; texto: string }[] = [
    { id: "gravar", Icone: Mic, titulo: "Gravar com a minha voz", texto: "Você lê o roteiro e grava. A IA fala com a sua voz." },
    { id: "pronta", Icone: Headphones, titulo: "Usar uma voz pronta", texto: "Áudios prontos da LawChat. Escolha o tom e ative na hora." },
  ];
  return (
    <div className="vp-escolha" role="radiogroup" aria-label="Como fazer os áudios do roteiro">
      {opcoes.map(({ id, Icone, titulo, texto }) => (
        <button key={id} type="button" role="radio" aria-checked={modo === id} className={`vp-escolha-op ${modo === id ? "on" : ""}`}
          onClick={() => aoEscolher(id)}>
          <span className="vp-escolha-ico"><Icone size={18} /></span>
          <span className="vp-escolha-txt"><b>{titulo}</b><small>{texto}</small></span>
          <span className="vp-escolha-marca" aria-hidden>{modo === id && <Check size={13} strokeWidth={3} />}</span>
        </button>
      ))}
    </div>
  );
}

const iniciais = (nome: string) => {
  const base = nome.split(/\s+[—–-]\s+/)[0] || nome;
  const palavras = base.trim().split(/\s+/).filter(Boolean);
  return ((palavras[0]?.[0] ?? "") + (palavras[1]?.[0] ?? "")).toUpperCase() || "?";
};
const nomeCurto = (nome: string) => (nome.split(/\s+[—–-]\s+/)[0] || nome).trim();
const plural = (n: number, um: string, varios: string) => `${n} ${n === 1 ? um : varios}`;

function Midia({ url, tipo }: { url: string; tipo: "audio" | "video" }) {
  return tipo === "video"
    ? <video src={url} controls preload="metadata" playsInline />
    : <audio src={url} controls preload="none" />;
}

function CartaoVoz({ voz, indice, liberado, motivo, aoUsar }: {
  voz: VozPronta; indice: number; liberado: boolean; motivo: string | null; aoUsar: () => void;
}) {
  const [todos, setTodos] = useState(false);
  const chips = [
    voz.tom,
    voz.genero === "feminina" ? "Feminina" : voz.genero === "masculina" ? "Masculina" : null,
    voz.origem === "equipe" ? "Voz da equipe" : "Voz de IA",
  ].filter(Boolean) as string[];
  const faltam = voz.total_partes - voz.partes_cobertas;
  return (
    <article className={`vp-voz ${voz.em_uso ? "em-uso" : ""}`}>
      <header className="vp-voz-topo">
        <span className={`vp-avatar tom-${indice % 4}`} aria-hidden>{iniciais(voz.nome)}</span>
        <div className="vp-voz-nome">
          <b>{voz.nome}</b>
          <div className="vp-chips">
            {chips.map((c) => <span key={c} className="vp-chip">{c}</span>)}
          </div>
        </div>
        {voz.em_uso && <span className="vp-em-uso"><Check size={12} strokeWidth={3} />Em uso</span>}
      </header>

      {voz.descricao && <p className="vp-voz-desc">{voz.descricao}</p>}

      {voz.amostra && (
        <div className="vp-amostra">
          <span><Headphones size={13} />Amostra: {voz.amostra.titulo}</span>
          <Midia url={voz.amostra.url} tipo={voz.amostra.tipo} />
        </div>
      )}

      <div className="vp-cobertura">
        <span><b>{voz.partes_cobertas} de {voz.total_partes}</b> partes do roteiro</span>
        {faltam > 0 && <small>{plural(faltam, "parte fica", "partes ficam")} para você gravar</small>}
      </div>
      <p className="vp-aviso"><Info size={13} />Não fala o nome do seu escritório: a apresentação vai por texto.</p>
      {(voz.avisos ?? []).map((a) => (
        <p key={a.id_parte} className="vp-aviso vp-aviso--valor"><Info size={13} /><span><b>{a.titulo}:</b> {a.aviso}</span></p>
      ))}

      {voz.audios.length > 0 && (
        <div className={`vp-todos ${todos ? "aberto" : ""}`}>
          <button type="button" className="vp-todos-btn" aria-expanded={todos} onClick={() => setTodos((v) => !v)}>
            Ouvir todos ({voz.audios.length})<ChevronDown size={15} />
          </button>
          {todos && (
            <ol className="vp-lista">
              {voz.audios.map((a) => (
                <li key={a.id_parte}>
                  <div><b>{a.titulo}</b><small>{NOME_SECAO[a.secao] ?? ""}</small></div>
                  <Midia url={a.url} tipo={a.tipo} />
                </li>
              ))}
            </ol>
          )}
        </div>
      )}

      <button type="button" className="rg-btn rg-btn--pri vp-usar" disabled={!liberado} title={liberado ? undefined : motivo ?? undefined} onClick={aoUsar}>
        <Sparkles size={15} />{voz.em_uso ? "Usar esta voz de novo" : "Usar esta voz"}
      </button>
    </article>
  );
}

export function VozesProntas({ idProduto, dados, minhasGravacoes, liberado = true, motivo = null, aoUsar }: {
  idProduto: string; dados: VozesDoProduto;
  /** Partes do roteiro com gravação própria do escritório: só com elas aparece "Trocar também as minhas gravações". */
  minhasGravacoes: number;
  liberado?: boolean; motivo?: string | null;
  /** Depois de aplicar a voz: o pai recarrega o roteiro. */
  aoUsar: (r: ResultadoUsarVoz, voz: VozPronta) => void;
}) {
  const [escolhida, setEscolhida] = useState<VozPronta | null>(null);
  const [aceite, setAceite] = useState(false);
  const [substituir, setSubstituir] = useState(false);
  const [pular, setPular] = useState<string[]>([]);
  const [enviando, setEnviando] = useState(false);
  const galeria = useRef<HTMLDivElement>(null);

  // Um player de cada vez: dar play numa amostra pausa as outras.
  useEffect(() => {
    const el = galeria.current;
    if (!el) return;
    const tocar = (e: Event) => {
      el.querySelectorAll<HTMLMediaElement>("audio, video").forEach((m) => { if (m !== e.target && !m.paused) m.pause(); });
    };
    el.addEventListener("play", tocar, true);
    return () => el.removeEventListener("play", tocar, true);
  }, []);

  const abrir = (voz: VozPronta) => {
    galeria.current?.querySelectorAll<HTMLMediaElement>("audio, video").forEach((m) => m.pause());
    setAceite(false);
    setSubstituir(false);
    setPular([]);
    setEscolhida(voz);
  };

  const confirmar = async () => {
    if (!escolhida || !aceite) return;
    setEnviando(true);
    try {
      const r = await enviar<ResultadoUsarVoz>(`/roteiro-gravacao/${idProduto}/vozes/${escolhida.id}/usar`,
        { aceite: true, substituir_minhas: substituir, pular_partes: pular });
      const nome = nomeCurto(escolhida.nome);
      const mantidas = r.mantidas > 0 ? `${plural(r.mantidas, "gravação sua foi mantida", "gravações suas foram mantidas")}.` : undefined;
      if (r.usadas > 0) toast.success(`Voz ${nome} aplicada: ${plural(r.usadas, "áudio", "áudios")} na pasta Roteiros prontos da sua Biblioteca`, { description: mantidas });
      else toast.success(`Nenhum áudio trocado: ${mantidas ?? "não havia parte para preencher."}`);
      setEscolhida(null);
      aoUsar(r, escolhida);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setEnviando(false);
    }
  };

  return (
    <div className="vp">
      <div className="vp-intro">
        <h3>Escolha uma voz</h3>
        <p>Ouça as amostras e escolha o tom que combina com o seu escritório. Os áudios entram na sua Biblioteca e você
          pode trocar qualquer um pela sua própria gravação depois.</p>
      </div>

      <div className="vp-galeria" ref={galeria}>
        {dados.vozes.map((v, i) => (
          <CartaoVoz key={v.id} voz={v} indice={i} liberado={liberado} motivo={motivo} aoUsar={() => abrir(v)} />
        ))}
      </div>

      <Dialog open={!!escolhida} onOpenChange={(aberto) => { if (!aberto && !enviando) setEscolhida(null); }}>
        <DialogContent className="vp-dialogo max-w-md w-[calc(100vw-2rem)] p-0 gap-0 overflow-hidden rounded-2xl">
          {escolhida && (
            <div className="vp-dialogo-corpo">
              <div className="vp-dialogo-topo">
                <span className="vp-avatar tom-0" aria-hidden>{iniciais(escolhida.nome)}</span>
                <div>
                  <DialogTitle className="vp-dialogo-tit">Usar a voz {nomeCurto(escolhida.nome)}</DialogTitle>
                  <DialogDescription className="vp-dialogo-sub">
                    {plural(escolhida.partes_cobertas, "áudio entra", "áudios entram")} na pasta Roteiros prontos da sua Biblioteca.
                  </DialogDescription>
                </div>
              </div>

              <div className="vp-aceite-texto"><Users size={15} /><p>{dados.texto_aceite}</p></div>

              <label className={`vp-caixa ${aceite ? "on" : ""}`}>
                <input type="checkbox" checked={aceite} onChange={(e) => setAceite(e.target.checked)} />
                <span>Li e concordo</span>
              </label>

              {(escolhida.avisos ?? []).map((a) => {
                const usar = !pular.includes(a.id_parte);
                return (
                  <label key={a.id_parte} className={`vp-caixa vp-caixa--leve ${usar ? "on" : ""}`}>
                    <input type="checkbox" checked={usar}
                      onChange={(e) => setPular((l) => (e.target.checked ? l.filter((x) => x !== a.id_parte) : [...l, a.id_parte]))} />
                    <span>
                      Usar também o áudio de {a.titulo}
                      <small>{a.aviso} {usar ? "Se os seus valores forem diferentes, desmarque: essa parte vai em texto (ou você grava a sua)."
                        : "Essa parte vai em texto, com os valores do seu prompt. Você pode gravar a sua depois."}</small>
                    </span>
                  </label>
                );
              })}

              {minhasGravacoes > 0 && (
                <label className={`vp-caixa vp-caixa--leve ${substituir ? "on" : ""}`}>
                  <input type="checkbox" checked={substituir} onChange={(e) => setSubstituir(e.target.checked)} />
                  <span>
                    Trocar também as minhas gravações por esta voz
                    <small>{substituir
                      ? `${plural(minhasGravacoes, "gravação sua sai", "gravações suas saem")} do roteiro e dá lugar à voz pronta.`
                      : `Sem marcar, ${plural(minhasGravacoes, "a gravação que você já fez continua", "as gravações que você já fez continuam")} valendo.`}</small>
                  </span>
                </label>
              )}

              <div className="vp-dialogo-botoes">
                <button type="button" className="rg-btn" disabled={enviando} onClick={() => setEscolhida(null)}>Cancelar</button>
                <button type="button" className="rg-btn rg-btn--pri" disabled={!aceite || enviando} onClick={confirmar}>
                  <Sparkles size={15} />{enviando ? "Aplicando…" : "Usar esta voz"}
                </button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
