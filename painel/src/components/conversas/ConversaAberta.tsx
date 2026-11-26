import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowDown, ArrowLeft, Headset, MessageSquareDashed, MessagesSquare, PanelRightOpen, RefreshCw, SearchX, X } from "lucide-react";
import { toast } from "sonner";
import { abrirHelenaEmJanela } from "../../telas/Atendimento";
import { formatarTelefone } from "../../api";
import { BolhaMensagem } from "./BolhaMensagem";
import { corDoAvatar, estadoDaIa, iniciais, nomeDoLead, nomeEtapa, porDia, type DetalheConversa } from "./tipos";

interface Props {
  detalhe: DetalheConversa | null;
  erro: string | null;
  naoEncontrada: boolean;
  aoVoltar: () => void;
  aoRecarregar: () => void;
  /** Botão "Detalhes" (quando o painel lateral não cabe ao lado). */
  aoAbrirDetalhes?: () => void;
  /** Botões da IA no cabeçalho (quando o painel lateral não cabe ao lado). */
  acoes?: ReactNode;
}

/** Coluna do meio: cabeçalho do lead e a conversa em balões, do mais antigo ao mais novo. */
export function ConversaAberta({ detalhe, erro, naoEncontrada, aoVoltar, aoRecarregar, aoAbrirDetalhes, acoes }: Props) {
  if (naoEncontrada) {
    return (
      <Moldura>
        <Estado icone={<SearchX className="size-5" />} titulo="Conversa não encontrada" texto="Ela pode ser de outro escritório ou o link está incompleto.">
          <Link to="/conversas" className="cv-botao sm mt-3 mx-auto w-fit"><ArrowLeft /> Voltar para a lista</Link>
        </Estado>
      </Moldura>
    );
  }
  if (!detalhe) {
    return (
      <Moldura>
        <CabecalhoVoltar aoVoltar={aoVoltar} />
        {erro ? (
          <Estado icone={<X className="size-5" />} tom="erro" titulo="Não deu para abrir a conversa" texto={erro}>
            <button type="button" className="cv-botao sm mt-3 mx-auto" onClick={aoRecarregar}><RefreshCw /> Tentar de novo</button>
          </Estado>
        ) : <EsqueletoConversa />}
      </Moldura>
    );
  }
  return <Conversa detalhe={detalhe} aoVoltar={aoVoltar} aoAbrirDetalhes={aoAbrirDetalhes} acoes={acoes} />;
}

/** Nenhuma conversa escolhida (só aparece no computador, ao lado da lista). */
export function NenhumaConversa() {
  return (
    <Moldura>
      <Estado icone={<MessagesSquare className="size-6" />} tom="verde" titulo="Escolha uma conversa"
        texto="Veja o que o lead escreveu, o que a IA respondeu e, se precisar, pause ou devolva o atendimento." />
    </Moldura>
  );
}

function Conversa({ detalhe: d, aoVoltar, aoAbrirDetalhes, acoes }: { detalhe: DetalheConversa; aoVoltar: () => void; aoAbrirDetalhes?: () => void; acoes?: ReactNode }) {
  const nome = nomeDoLead(d);
  const estado = estadoDaIa(d);
  const grupos = useMemo(() => porDia(d.mensagens), [d.mensagens]);
  const rolagem = useRef<HTMLDivElement>(null);
  const noFim = useRef(true);
  const [mostrarDescer, setMostrarDescer] = useState(false);
  const quantas = d.mensagens.length;

  // Ao abrir outra conversa, começa no fim (a mensagem mais nova).
  useLayoutEffect(() => {
    const el = rolagem.current;
    if (el) el.scrollTop = el.scrollHeight;
    noFim.current = true;
    setMostrarDescer(false);
  }, [d.id]);
  // Mensagem nova: acompanha só se a pessoa já estava no fim (não puxa quem está lendo lá em cima).
  useEffect(() => {
    const el = rolagem.current;
    if (el && noFim.current) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [quantas]);

  const aoRolar = () => {
    const el = rolagem.current;
    if (!el) return;
    const perto = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    noFim.current = perto;
    setMostrarDescer(!perto);
  };
  const descer = () => rolagem.current?.scrollTo({ top: rolagem.current.scrollHeight, behavior: "smooth" });

  return (
    <Moldura>
      <header className="cv-cab">
        <button type="button" className="cv-icone-btn cv-voltar" onClick={aoVoltar} aria-label="Voltar para a lista"><ArrowLeft /></button>
        <span className="cv-av" style={{ background: corDoAvatar(d.id), width: 40, height: 40 }} aria-hidden>
          {iniciais(nome)}<i className="cv-av-ponto" style={{ background: estado.cor }} />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-[14.5px] font-bold tracking-tight text-[#101828]">{nome}</h2>
          <p className="truncate text-[12px] text-[#667085]">
            <span className="font-semibold" style={{ color: estado.cor }}>{estado.rotulo}</span>
            {[d.nome ? formatarTelefone(d.telefone) : null, d.agente, d.etapa ? nomeEtapa(d.etapa) : null].filter(Boolean).map((t) => ` · ${t}`).join("")}
          </p>
        </div>
        {acoes && <div className="cv-acoes-cab">{acoes}</div>}
        <button type="button" className="cv-icone-btn" aria-label="Abrir esta conversa na Helena" title="Abrir na Helena (já logado)"
          onClick={() => { abrirHelenaEmJanela(d.id).catch((e) => toast.error((e as Error).message)); }}><Headset /></button>
        {aoAbrirDetalhes && (
          <button type="button" className="cv-icone-btn" onClick={aoAbrirDetalhes} aria-label="Ver detalhes do lead" title="Fatos, origem, turnos e eventos"><PanelRightOpen /></button>
        )}
      </header>
      {(d.ia_desligada_escritorio || (d.situacao_agente && d.situacao_agente !== "ativo")) && (
        <p role="status" className="m-0 px-4 py-2 text-[12px] text-[#7A4B00] bg-[#FFF4DF] border-b border-[#F5E1B8]">
          {d.ia_desligada_escritorio
            ? "A IA está desligada no escritório inteiro: nenhum lead recebe resposta nem follow-up. Quem religa é o gestor, em Configurações."
            : `O agente ${d.agente ?? "deste número"} está pausado: nenhum lead deste número recebe resposta nem follow-up. Quem religa é o gestor, no produto.`}
        </p>
      )}

      <div className="relative flex-1 min-h-0 flex flex-col">
        <div ref={rolagem} className="cv-chat" onScroll={aoRolar} role="log" aria-label={`Mensagens com ${nome}`} aria-live="polite">
          {grupos.length === 0 ? (
            <Estado icone={<MessageSquareDashed className="size-5" />} titulo="Sem mensagens registradas" texto="O lead existe, mas nenhuma mensagem foi gravada ainda." />
          ) : grupos.map((g) => (
            <div key={g.dia}>
              <div className="cv-dia"><span>{g.dia}</span></div>
              {g.mensagens.map((m, i) => (
                <BolhaMensagem key={m.id} mensagem={m} novoAutor={i === 0 || g.mensagens[i - 1].autor !== m.autor} />
              ))}
            </div>
          ))}
        </div>
        {/* No centro, para não ficar embaixo do botão redondo de atalhos (canto direito). */}
        <div className="absolute left-1/2 bottom-4 -translate-x-1/2">
          <AnimatePresence>
            {mostrarDescer && (
              <motion.button type="button" onClick={descer} aria-label="Ir para a mensagem mais nova"
                initial={{ opacity: 0, scale: 0.8 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.8 }}
                className="size-10 rounded-full grid place-items-center bg-white text-[#475467] shadow-[0_6px_18px_rgba(15,23,42,.18)] hover:text-[#00bc33]">
                <ArrowDown className="size-4" />
              </motion.button>
            )}
          </AnimatePresence>
        </div>
      </div>
    </Moldura>
  );
}

function Moldura({ children }: { children: ReactNode }) {
  return <section className="cv-conversa lc-card relative" aria-label="Conversa">{children}</section>;
}

/** Só no celular: volta para a lista (no computador a lista está ao lado). */
function CabecalhoVoltar({ aoVoltar }: { aoVoltar: () => void }) {
  return (
    <header className="cv-cab cv-so-celular">
      <button type="button" className="cv-icone-btn" onClick={aoVoltar} aria-label="Voltar para a lista"><ArrowLeft /></button>
      <span className="text-[13px] font-semibold text-[#344054]">Conversas</span>
    </header>
  );
}

function Estado({ icone, titulo, texto, tom = "neutro", children }: { icone: ReactNode; titulo: string; texto?: ReactNode; tom?: "neutro" | "verde" | "erro"; children?: ReactNode }) {
  const cores = { neutro: ["#F1F5F9", "#667085"], verde: ["#e8f9ee", "#00bc33"], erro: ["#FDE8E8", "#DC2626"] }[tom];
  return (
    <div className="cv-vazio">
      <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
        <div className="mx-auto size-12 rounded-2xl grid place-items-center" style={{ background: cores[0], color: cores[1] }}>{icone}</div>
        <p className="mt-3 text-[14px] font-semibold text-[#344054]">{titulo}</p>
        {texto && <p className="mt-1 text-[12.5px] text-[#667085] max-w-[22rem] mx-auto">{texto}</p>}
        {children}
      </motion.div>
    </div>
  );
}

function EsqueletoConversa() {
  const larguras = [46, 62, 38, 70, 52, 34, 58];
  return (
    <div className="cv-chat" role="status" aria-label="Carregando a conversa">
      {larguras.map((l, i) => (
        <div key={i} className={`cv-linha ${i % 2 ? "dir" : "esq"} novo-autor`}>
          <div className="carregando-brilho" style={{ height: 34 + (i % 3) * 10, width: `${l}%`, borderRadius: 12 }} />
        </div>
      ))}
    </div>
  );
}
