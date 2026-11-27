// Roteiro de gravação de um produto: orientações, materiais principais (vídeos + áudios) e quebra de objeção, com
// progresso e cada parte num cartão que abre. Tela Roteiros e card da ativação do produto usam este mesmo componente.
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, ArrowRight, Check, ChevronDown, Lock, Mic, Video } from "lucide-react";
import { useCarregar } from "@/componentes/ui";
import { GravadorParte } from "./GravadorParte";
import type { ParteRoteiro, RoteiroDoProduto } from "./tipos";
import "./roteiro.css";

type Passo = "orientacoes" | "principais" | "objecoes";

function CartaoParte({ parte, numero, aberto, aoAbrir, aoMudar, liberado }: {
  parte: ParteRoteiro; numero: number; aberto: boolean; aoAbrir: () => void; aoMudar: (p: ParteRoteiro) => void; liberado: boolean;
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
      {aberto && <GravadorParte parte={parte} aoMudar={aoMudar} liberado={liberado} />}
    </div>
  );
}

export function RoteiroGravacao({ idProduto, aoGravou, compacto = false, aoVoltar }: {
  idProduto: string;
  /** Avisado a cada envio/exclusão (a ativação usa para trocar o marcador do prompt pelo link). */
  aoGravou?: (parte: ParteRoteiro) => void;
  compacto?: boolean;
  aoVoltar?: () => void;
}) {
  const { dados, erro } = useCarregar<RoteiroDoProduto>(`/roteiro-gravacao/${idProduto}`, [idProduto], { guardar: false });
  const [partes, setPartes] = useState<ParteRoteiro[]>([]);
  const [passo, setPasso] = useState<Passo>(compacto ? "principais" : "orientacoes");
  const [aberta, setAberta] = useState<string | null>(null);
  useEffect(() => { if (dados) setPartes(dados.partes); }, [dados]);

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
  const passos: { id: Passo; rotulo: string }[] = [
    ...(compacto ? [] : [{ id: "orientacoes" as Passo, rotulo: "Orientações" }]),
    { id: "principais", rotulo: "Materiais principais" },
    ...(objecoes.length ? [{ id: "objecoes" as Passo, rotulo: "Quebra de objeção" }] : []),
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
          {aoVoltar && <button type="button" className="rg-voltar" onClick={aoVoltar}><ArrowLeft size={15} />Roteiros</button>}
          <h2>Seu roteiro de gravação</h2>
          <p>{dados.produto.nome}</p>
          <div className="rg-passos">
            {passos.map((p, i) => (
              <button key={p.id} type="button" className={i <= indice ? "on" : ""} onClick={() => setPasso(p.id)}>
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
        <div><span>Seu progresso</span><b className={gravadas === total ? "ok" : ""}>{gravadas} de {total} enviados</b></div>
        <div className="rg-barra"><i style={{ width: `${total ? (gravadas / total) * 100 : 0}%` }} /></div>
      </div>
      {gravadas === total && total > 0 && <div className="rg-fim">🎉 Tudo enviado! As gravações já estão na Biblioteca, prontas para a ativação.</div>}

      {compacto && passos.length > 1 && (
        <div className="rg-abas">
          {passos.map((p) => {
            const l = p.id === "objecoes" ? objecoes : principais;
            return <button key={p.id} type="button" className={passo === p.id ? "on" : ""} onClick={() => setPasso(p.id)}>{p.rotulo} <small>{feitas(l)}/{l.length}</small></button>;
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
          {passo === "objecoes" && <p className="rg-secao-txt">Áudios para quando o lead tiver uma dúvida, insegurança ou objeção durante o atendimento.</p>}
          <div className="rg-cartoes">
            {lista.map((p) => (
              <CartaoParte key={p.id} parte={p} numero={partes.indexOf(p) + 1} aberto={aberta === p.id} liberado={dados.liberado}
                aoAbrir={() => setAberta((a) => (a === p.id ? null : p.id))} aoMudar={mudar} />
            ))}
          </div>
        </div>
      )}

      {!compacto && (
        <div className="rg-rodape">
          {indice > 0 ? <button type="button" className="rg-btn" onClick={() => setPasso(passos[indice - 1].id)}><ArrowLeft size={15} />Voltar</button> : <span />}
          {indice < passos.length - 1
            ? <button type="button" className="rg-btn rg-btn--pri" onClick={() => setPasso(passos[indice + 1].id)}>
                {passo === "orientacoes" ? "Começar a gravar" : "Próximo"}<ArrowRight size={15} /></button>
            : aoVoltar && <button type="button" className="rg-btn rg-btn--pri" onClick={aoVoltar}><Check size={15} />{gravadas === total ? "Concluído" : "Salvar e sair"}</button>}
        </div>
      )}
    </div>
  );
}
