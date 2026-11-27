// Roteiro de gravação de um produto: orientações, materiais principais (vídeos + áudios) e quebra de objeção, com
// progresso e cada parte num cartão que abre. Tela Roteiros e card da ativação do produto usam este mesmo componente.
import { useEffect, useMemo, useState, type MutableRefObject } from "react";
import { ArrowLeft, ArrowRight, Check, ChevronDown, Lock, Mic, Video } from "lucide-react";
import { useCarregar, useConfirmar } from "@/componentes/ui";
import { GravadorParte } from "./GravadorParte";
import type { ParteRoteiro, RoteiroDoProduto } from "./tipos";
import "./roteiro.css";

type Passo = "orientacoes" | "principais" | "objecoes";

function CartaoParte({ parte, numero, aberto, aoAbrir, aoMudar, aoOcupar, liberado }: {
  parte: ParteRoteiro; numero: number; aberto: boolean; aoAbrir: () => void; aoMudar: (p: ParteRoteiro) => void;
  aoOcupar: (ocupado: boolean) => void; liberado: boolean;
}) {
  const feito = !!parte.gravacao;
  const Icone = parte.tipo === "video" ? Video : Mic;
  return (
    <div className={`rg-cartao ${feito ? "feito" : ""} ${aberto ? "aberto" : ""}`}>
      <button type="button" className="rg-cartao-topo" onClick={aoAbrir} aria-expanded={aberto}>
        <span className={`rg-ico ${parte.tipo}`}><Icone size={16} /></span>
        <span className="rg-cartao-tit">
          <small>{parte.tipo === "video" ? "Vídeo" : "Áudio"} {String(numero).padStart(2, "0")}{parte.chave_geral ? " · geral" : ""}</small>
          <b>{parte.titulo}</b>
        </span>
        <span className={`rg-check ${feito ? "on" : ""}`} aria-label={feito ? "Enviado" : "Falta enviar"}>{feito && <Check size={14} strokeWidth={3} />}</span>
        <ChevronDown size={16} className="rg-seta" />
      </button>
      {aberto && <GravadorParte parte={parte} aoMudar={aoMudar} aoOcupar={aoOcupar} liberado={liberado} />}
    </div>
  );
}

export function RoteiroGravacao({ idProduto, aoGravou, compacto = false, aoVoltar, sair }: {
  idProduto: string;
  /** Avisado a cada envio/exclusão (a ativação usa para trocar o marcador do prompt pelo link). */
  aoGravou?: (parte: ParteRoteiro) => void;
  compacto?: boolean;
  aoVoltar?: () => void;
  /** Preenchido aqui: quem está fora (ex.: "Voltar para a ativação") chama antes de sair, e só sai se confirmar o descarte. */
  sair?: MutableRefObject<((ir: () => void) => void) | null>;
}) {
  const { dados, erro } = useCarregar<RoteiroDoProduto>(`/roteiro-gravacao/${idProduto}`, [idProduto], { guardar: false });
  const [confirmar, modalConfirmar] = useConfirmar();
  const [partes, setPartes] = useState<ParteRoteiro[]>([]);
  const [passo, setPasso] = useState<Passo>(compacto ? "principais" : "orientacoes");
  const [aberta, setAberta] = useState<string | null>(null);
  // Parte com gravação em andamento ou prévia ainda não enviada: fechar/trocar o cartão descartaria sem aviso.
  const [ocupada, setOcupada] = useState<string | null>(null);
  useEffect(() => { if (dados) setPartes(dados.partes); }, [dados]);

  /** Faz `ir` direto ou, se há gravação não enviada, só depois de confirmar o descarte. */
  const seguir = async (ir: () => void) => {
    if (ocupada && !(await confirmar({ titulo: "Descartar a gravação?", texto: "Descartar a gravação que ainda não foi enviada?", confirmar: "Descartar", perigo: true }))) return;
    setOcupada(null);
    ir();
  };
  useEffect(() => {
    if (!sair) return;
    sair.current = (ir) => { void seguir(ir); };
    return () => { sair.current = null; };
  });
  const irPasso = (novo: Passo) => { if (novo !== passo) void seguir(() => setPasso(novo)); };
  const voltar = aoVoltar && (() => { void seguir(aoVoltar); });

  const principais = useMemo(() => partes.filter((p) => p.secao !== "objecoes"), [partes]);
  const objecoes = useMemo(() => partes.filter((p) => p.secao === "objecoes"), [partes]);
  const lista = passo === "objecoes" ? objecoes : principais;
  // Abre a primeira parte que ainda falta ao trocar de passo.
  useEffect(() => {
    if (passo === "orientacoes") return;
    setAberta((lista.find((p) => !p.gravacao) ?? lista[0])?.id ?? null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [passo, partes.length]);

  if (!dados) return <div className="rg-carregando">{erro ? `Não deu para abrir o roteiro: ${erro}` : "Abrindo o roteiro…"}</div>;

  const gravadas = partes.filter((p) => p.gravacao).length;
  const total = partes.length;
  // Obrigatórios = vídeos + áudios principais: concluem o roteiro e liberam a ativação. Quebra de objeção é opcional e
  // fica "em aberto" para gravar depois (até lá o agente responde essas objeções em texto).
  const obrigatorias = principais.length;
  const obrigGravadas = principais.filter((p) => p.gravacao).length;
  const concluido = obrigatorias > 0 && obrigGravadas === obrigatorias;
  const objGravadas = objecoes.filter((p) => p.gravacao).length;
  const passos: { id: Passo; rotulo: string }[] = [
    ...(compacto ? [] : [{ id: "orientacoes" as Passo, rotulo: "Orientações" }]),
    { id: "principais", rotulo: "Materiais principais" },
    ...(objecoes.length ? [{ id: "objecoes" as Passo, rotulo: "Quebra de objeção (opcional)" }] : []),
  ];
  const indice = passos.findIndex((p) => p.id === passo);
  const mudar = (nova: ParteRoteiro) => {
    setPartes((v) => v.map((p) => (p.id === nova.id ? nova
      // parte geral: a mesma gravação vale para as outras partes com a mesma chave
      : nova.chave_geral && p.chave_geral === nova.chave_geral ? { ...p, gravacao: nova.gravacao && { ...nova.gravacao, reaproveitada: true } } : p)));
    aoGravou?.(nova);
    if (nova.gravacao) {
      const proxima = lista.find((p) => p.id !== nova.id && !p.gravacao);
      if (proxima) setAberta(proxima.id);
    }
  };
  const feitas = (l: ParteRoteiro[]) => l.filter((p) => p.gravacao).length;
  const contar = (l: ParteRoteiro[], tipo: "audio" | "video") => l.filter((p) => p.tipo === tipo).length;

  return (
    <div className={`rg ${compacto ? "rg--compacto" : ""}`}>
      {!compacto && (
        <div className="rg-topo">
          {voltar && <button type="button" className="rg-voltar" onClick={voltar}><ArrowLeft size={15} />Roteiros</button>}
          <h2>Seu roteiro de gravação</h2>
          <p>{dados.produto.nome}</p>
          <div className="rg-passos">
            {passos.map((p, i) => (
              <button key={p.id} type="button" className={i <= indice ? "on" : ""} onClick={() => irPasso(p.id)}>
                <i /><span>{i + 1}. {p.rotulo}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {!dados.liberado && (
        <div className="rg-bloqueado"><Lock size={16} /><span>{dados.motivo ?? "O seu plano não inclui o roteiro de gravação."}</span></div>
      )}

      <div className="rg-progresso">
        <div><span>Materiais obrigatórios</span><b className={concluido ? "ok" : ""}>{obrigGravadas} de {obrigatorias} enviados</b></div>
        <div className="rg-barra"><i style={{ width: `${obrigatorias ? (obrigGravadas / obrigatorias) * 100 : 0}%` }} /></div>
        {objecoes.length > 0 && <div className="rg-progresso-extra"><span>Quebra de objeção (opcional)</span><span>{objGravadas} de {objecoes.length}</span></div>}
      </div>
      {gravadas === total && total > 0
        ? <div className="rg-fim">🎉 Tudo enviado! As gravações já estão na Biblioteca, prontas para a ativação.</div>
        : concluido && <div className="rg-fim">✅ Materiais obrigatórios completos: você já pode ativar o agente. Os áudios de objeção não são
            obrigatórios, mas deixam a IA mais convincente: grave quando puder (até lá, ela responde essas objeções em texto).</div>}

      {compacto && passos.length > 1 && (
        <div className="rg-abas">
          {passos.map((p) => {
            const l = p.id === "objecoes" ? objecoes : principais;
            return <button key={p.id} type="button" className={passo === p.id ? "on" : ""} onClick={() => irPasso(p.id)}>{p.rotulo} <small>{feitas(l)}/{l.length}</small></button>;
          })}
        </div>
      )}

      {passo === "orientacoes" ? (
        <div className="rg-orient">
          <h3>Materiais personalizados para sua IA</h3>
          <p>Grave os áudios e vídeos:</p>
          <div className="rg-dicas"><span>🔇 Num lugar silencioso, sem ruído ao fundo.</span><span>🗣️ Falando de forma natural, como com um cliente.</span></div>
          <div className="rg-contas">
            <div><span className="rg-ico video"><Video size={16} /></span><b>{contar(partes, "video")}</b><small>vídeos</small></div>
            <div><span className="rg-ico audio"><Mic size={16} /></span><b>{contar(principais, "audio")}</b><small>áudios principais</small></div>
            {objecoes.length > 0 && <div><span className="rg-ico audio"><Mic size={16} /></span><b>{objecoes.length}</b><small>áudios de objeção</small></div>}
          </div>
          <ul className="rg-lista-dicas">
            <li>Abra cada item, ouça ou assista ao exemplo e grave ali mesmo, ou envie um arquivo pronto.</li>
            <li>Cada material enviado ganha um ✓ verde ao lado do título.</li>
            <li>Pode parar e voltar depois: o que já foi enviado fica salvo.</li>
            <li>Quando você ativar o produto, cada gravação já entra no lugar certo do prompt.</li>
          </ul>
          {dados.produto.roteiro_orientacoes && <div className="rg-orient-texto">{dados.produto.roteiro_orientacoes}</div>}
        </div>
      ) : (
        <div className="rg-secao">
          {!compacto && (
            <div className="rg-secao-topo">
              <h3>{passo === "objecoes" ? "Quebra de objeção" : "Materiais principais"}</h3>
              <span>{feitas(lista)} de {lista.length}</span>
            </div>
          )}
          {passo === "objecoes" && (
            <div className="rg-dica-opcional">
              <b>Estes áudios não são obrigatórios, mas fazem diferença.</b>
              <span>Quando o lead hesita ("está caro", "tenho medo de golpe", "preciso pensar"), ouvir a sua voz passa muito mais
                confiança do que um texto. Para a IA ter um desempenho melhor e fechar mais contratos, vale gravar.</span>
              <span>Dá para ativar o agente sem eles e gravar depois: enquanto não houver áudio, o agente responde a objeção em texto.</span>
            </div>
          )}
          <div className="rg-cartoes">
            {lista.map((p) => (
              <CartaoParte key={p.id} parte={p} numero={partes.indexOf(p) + 1} aberto={aberta === p.id} liberado={dados.liberado}
                aoAbrir={() => { void seguir(() => setAberta((a) => (a === p.id ? null : p.id))); }} aoMudar={mudar}
                aoOcupar={(o) => setOcupada((atual) => (o ? p.id : atual === p.id ? null : atual))} />
            ))}
          </div>
        </div>
      )}

      {!compacto && (
        <div className="rg-rodape">
          {indice > 0 ? <button type="button" className="rg-btn" onClick={() => irPasso(passos[indice - 1].id)}><ArrowLeft size={15} />Voltar</button> : <span />}
          <div className="rg-botoes">
            {/* Obrigatórios prontos: já dá para concluir; as objeções ficam em aberto para depois. */}
            {voltar && concluido && passo === "principais" && objecoes.length > 0 && objGravadas < objecoes.length &&
              <button type="button" className="rg-btn" onClick={voltar}><Check size={15} />Concluir (objeções depois)</button>}
            {indice < passos.length - 1
              ? <button type="button" className="rg-btn rg-btn--pri" onClick={() => irPasso(passos[indice + 1].id)}>
                  {passo === "orientacoes" ? "Começar a gravar" : passo === "principais" && concluido ? "Gravar as objeções" : "Próximo"}<ArrowRight size={15} /></button>
              : voltar && <button type="button" className="rg-btn rg-btn--pri" onClick={voltar}><Check size={15} />{concluido ? "Concluído" : "Salvar e sair"}</button>}
          </div>
        </div>
      )}
      {modalConfirmar}
    </div>
  );
}
