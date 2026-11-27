import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ArrowLeft, ArrowRight, Check, Eye, EyeOff, MinusCircle, PartyPopper, Rocket } from "lucide-react";
import SpringCheck from "@/components/reactbits/SpringCheck";
import BotaoBrilho from "@/components/reactbits/BotaoBrilho";
import { useCarregar } from "@/componentes/ui";
import { useSessao } from "@/sessao";
import { ModalCrmPasso } from "./CrmPasso";
import { ModalDadosEscritorio } from "./DadosEscritorio";
import "./PrimeirosPassos.css";

/** GET /api/inicio/primeiros-passos (app/gestao/primeiros_passos.py). */
export interface PassoInicial {
  codigo: string; titulo: string; situacao: "feito" | "pendente" | "nao_se_aplica"; detalhe: string;
  para: string | null; acao: string | null;
}
export interface PrimeirosPassosDados { passos: PassoInicial[]; feitos: number; total: number; completo: boolean; proximo: string | null }

/** O porquê e o que fazer de cada passo, em frases curtas (o "detalhe" do servidor entra como situação atual). */
const GUIA: Record<string, { porque: string; fazer: string }> = {
  conta: {
    porque: "É o que libera os agentes de IA na sua conta.",
    fazer: "Peça à equipe LawChat para liberar a função de agente. Quando liberarem, este passo se marca sozinho.",
  },
  whatsapp: {
    porque: "O agente conversa com os leads pelo seu número de WhatsApp.",
    fazer: "Abra Canais de atendimento e conecte o WhatsApp do escritório.",
  },
  crm: {
    porque: "É por estas etapas que a IA move cada lead sozinha, do primeiro contato ao contrato assinado.",
    fazer: "Crie o painel no CRM com as etapas sugeridas e depois marque qual coluna é cada etapa.",
  },
  roteiro: {
    porque: "Os áudios e vídeos com a sua voz deixam o atendimento mais humano e convertem mais.",
    fazer: "Escolha um produto e grave o roteiro (vídeos e áudios principais). As objeções podem ficar para depois.",
  },
  dados: {
    porque: "Nome, endereço, CNPJ e redes entram em todos os agentes: você preenche uma vez só.",
    fazer: "Preencha os dados da firma. Na ativação, o prompt já vem com eles.",
  },
  produto: {
    porque: "O agente é quem responde os leads por você, a qualquer hora.",
    fazer: "Escolha um produto na Biblioteca e siga a ativação até ligar o agente.",
  },
  followup: {
    porque: "O follow-up chama de novo quem parou de responder, na hora certa.",
    fazer: "Abra o follow-up do agente, ligue e confira as mensagens de retorno.",
  },
};

const CHAVE_OCULTO = "agentesia_tutorial_oculto";
function lerOculto(usuario: string): boolean {
  try { return localStorage.getItem(`${CHAVE_OCULTO}:${usuario}`) === "1"; } catch { return false; }
}
function gravarOculto(usuario: string, oculto: boolean): void {
  try {
    if (oculto) localStorage.setItem(`${CHAVE_OCULTO}:${usuario}`, "1");
    else localStorage.removeItem(`${CHAVE_OCULTO}:${usuario}`);
  } catch { /* sem armazenamento: só não lembra */ }
}

const pronto = (p: PassoInicial) => p.situacao !== "pendente";

/** "Primeiros passos" do Início como tutorial guiado: um passo por vez em destaque, a trilha dos passos ao lado.
 * Cada passo se marca sozinho (mesmos dados de antes); o cartão some quando tudo está pronto. */
export function PrimeirosPassos({ dados, aoMudar }: { dados: PrimeirosPassosDados; aoMudar?: () => void }) {
  const { eu, escritorio } = useSessao();
  const usuario = eu?.id ?? "anonimo";
  const navegar = useNavigate();
  const reduzir = useReducedMotion();
  const [oculto, setOculto] = useState(() => lerOculto(usuario));
  useEffect(() => { setOculto(lerOculto(usuario)); }, [usuario]);

  const passos = dados.passos;
  const primeiroPendente = dados.proximo ?? passos.find((p) => !pronto(p))?.codigo ?? passos[0]?.codigo ?? null;
  const [aberto, setAberto] = useState<string | null>(primeiroPendente);
  const [direcao, setDirecao] = useState(1);
  const [comemorando, setComemorando] = useState(false);
  const [recemFeito, setRecemFeito] = useState<string | null>(null);
  const [popup, setPopup] = useState<"crm" | "dados" | null>(null);

  // Passo que acabou de ficar pronto (dados novos): mostra o "feito" e passa para o próximo sozinho.
  const anteriores = useRef<Record<string, PassoInicial["situacao"]>>({});
  const completoAntes = useRef(dados.completo);
  useEffect(() => {
    const antes = anteriores.current;
    const virou = passos.find((p) => antes[p.codigo] === "pendente" && p.situacao === "feito");
    anteriores.current = Object.fromEntries(passos.map((p) => [p.codigo, p.situacao]));
    if (dados.completo && !completoAntes.current) setComemorando(true);
    completoAntes.current = dados.completo;
    if (!virou) { if (aberto == null || !passos.some((p) => p.codigo === aberto)) setAberto(primeiroPendente); return; }
    setAberto(virou.codigo);
    setRecemFeito(virou.codigo);
    const t = window.setTimeout(() => { setRecemFeito(null); setDirecao(1); setAberto(primeiroPendente); }, 1600);
    return () => window.clearTimeout(t);
  }, [dados]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!comemorando) return;
    const t = window.setTimeout(() => setComemorando(false), 5000);
    return () => window.clearTimeout(t);
  }, [comemorando]);

  // "Ativar": leva direto à ativação do agente desligado (o nome vem no detalhe do passo).
  const passoProduto = passos.find((p) => p.codigo === "produto");
  const precisaAgente = passoProduto?.situacao === "pendente" && passoProduto.para === "/meus-produtos";
  const agentes = useCarregar<{ id: string; nome: string; situacao?: string }[]>(precisaAgente && escritorio ? "/agentes" : null, [escritorio, precisaAgente]);
  const destinoDe = useMemo(() => (p: PassoInicial): string | null => {
    if (p.codigo === "produto" && precisaAgente) {
      const nome = p.detalhe.replace(/ criado, mas ainda desligado$/, "");
      const ag = (agentes.dados ?? []).find((a) => a.nome === nome) ?? (agentes.dados ?? []).find((a) => a.situacao !== "ativo");
      if (ag) return `/agentes/${ag.id}/ativacao`;
    }
    if (p.codigo === "crm" || p.codigo === "dados") return "#popup";
    return p.para;
  }, [agentes.dados, precisaAgente]);

  if (dados.completo && !comemorando) return null;

  const indice = Math.max(0, passos.findIndex((p) => p.codigo === aberto));
  const atual = passos[indice];
  const pct = Math.round((dados.feitos / Math.max(1, dados.total)) * 100);

  const esconder = () => { gravarOculto(usuario, true); setOculto(true); };
  const mostrar = () => { gravarOculto(usuario, false); setOculto(false); };
  const ir = (codigo: string) => {
    const novo = passos.findIndex((p) => p.codigo === codigo);
    setDirecao(novo >= indice ? 1 : -1);
    setAberto(codigo);
  };

  if (comemorando) {
    return (
      <motion.section initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} aria-label="Primeiros passos"
        className="lc-card pp-tutorial pp-fim relative overflow-hidden p-6 mb-3">
        <div className="pp-confete" aria-hidden>{Array.from({ length: 18 }, (_, i) => <i key={i} style={{ ["--i" as string]: i }} />)}</div>
        <div className="flex items-center gap-3">
          <div className="pp-fim-icone"><PartyPopper className="size-6" /></div>
          <div>
            <h3 className="m-0 text-[18px] font-bold text-[#101828]">Tudo pronto!</h3>
            <p className="m-0 text-[13.5px] text-[#475467]">Todos os passos estão feitos. A sua IA já está atendendo.</p>
          </div>
        </div>
      </motion.section>
    );
  }

  if (oculto) {
    return (
      <section aria-label="Primeiros passos" className="lc-card pp-tutorial pp-mini mb-3">
        <Rocket className="size-4 text-[#00a32c] shrink-0" aria-hidden />
        <span className="min-w-0 truncate"><b>Primeiros passos</b> · {dados.feitos} de {dados.total} prontos</span>
        <button type="button" className="pp-link" onClick={mostrar}><Eye className="size-3.5" /> Mostrar de novo</button>
      </section>
    );
  }

  const guia = GUIA[atual.codigo] ?? { porque: "", fazer: atual.detalhe };
  const destino = destinoDe(atual);
  const naoSeAplica = atual.situacao === "nao_se_aplica";
  const feito = atual.situacao === "feito";
  const proximoDepois = passos.slice(indice + 1).find((p) => !pronto(p)) ?? passos.find((p) => !pronto(p) && p.codigo !== atual.codigo);
  const fazerTexto = atual.codigo === "produto" && precisaAgente
    ? `O agente ${atual.detalhe.replace(/ criado, mas ainda desligado$/, "")} já existe, mas está desligado. Abra a ativação e siga os passos até ligar.`
    : atual.codigo === "followup" && !feito && atual.detalhe.startsWith("ligue um")
      ? "Primeiro, ative um agente. Depois, volte aqui para ligar o follow-up."
      : guia.fazer;
  const acao = atual.codigo === "produto" && precisaAgente && destino?.includes("/ativacao") ? "Abrir a ativação" : atual.acao;

  const abrirDestino = () => {
    if (atual.codigo === "crm" || atual.codigo === "dados") { setPopup(atual.codigo); return; }
    if (!destino) return;
    navegar(destino);
  };

  return (
    <motion.section initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}
      aria-label="Primeiros passos" className="lc-card pp-tutorial relative overflow-hidden mb-3">
      {/* Cabeçalho: título, progresso e esconder */}
      <header className="pp-cab">
        <div className="flex items-center gap-3 min-w-0">
          <div className="pp-cab-icone"><Rocket className="size-[18px]" /></div>
          <div className="min-w-0">
            <h3 className="m-0 text-[16px] font-bold tracking-tight text-[#101828]">Deixe a sua IA pronta em {dados.total} passos</h3>
            <p className="m-0 text-[13px] text-[#475467]">Um passo por vez. Cada um se marca sozinho quando fica pronto.</p>
          </div>
        </div>
        <div className="pp-progresso">
          <div className="pp-progresso-txt"><b>{dados.feitos} de {dados.total}</b> prontos</div>
          <div className="pp-barra" role="progressbar" aria-valuenow={dados.feitos} aria-valuemin={0} aria-valuemax={dados.total} aria-label="Passos prontos">
            <i style={{ width: `${Math.max(4, pct)}%` }} />
          </div>
          <button type="button" className="pp-link" onClick={esconder}><EyeOff className="size-3.5" /> Esconder tutorial</button>
        </div>
      </header>

      <div className="pp-corpo">
        {/* Passo em destaque */}
        <div className="pp-palco" aria-live="polite">
          <AnimatePresence mode="wait" initial={false} custom={direcao}>
            <motion.div key={atual.codigo} className="pp-destaque"
              custom={direcao}
              initial={reduzir ? { opacity: 0 } : { opacity: 0, x: 28 * direcao }}
              animate={{ opacity: 1, x: 0 }}
              exit={reduzir ? { opacity: 0 } : { opacity: 0, x: -28 * direcao }}
              transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}>
              <div className="pp-destaque-topo">
                <span className="pp-numero-grande" data-situacao={atual.situacao}>
                  {feito ? <SpringCheck checked somenteLeitura animarAoAparecer atraso={0.1} boxSize={22} boxRadius={999} bounce={0.4} ariaLabel="pronto" />
                    : naoSeAplica ? <MinusCircle className="size-5" aria-hidden /> : indice + 1}
                </span>
                <span className="pp-eyebrow">Passo {indice + 1} de {passos.length}</span>
                <span className={`pp-selo ${feito ? "ok" : naoSeAplica ? "na" : "falta"}`}>
                  {feito ? "Pronto" : naoSeAplica ? "Não se aplica" : atual.codigo === dados.proximo ? "Agora" : "Falta"}
                </span>
              </div>
              <h4 className="pp-titulo">{atual.titulo}</h4>
              {recemFeito === atual.codigo && (
                <motion.p className="pp-feito-agora" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}>
                  <Check className="size-4" /> Feito! Indo para o próximo passo…
                </motion.p>
              )}
              {feito || naoSeAplica ? (
                <p className="pp-texto">{naoSeAplica ? "Este passo não é preciso na sua conta: " : "Tudo certo: "}{atual.detalhe}.</p>
              ) : (
                <>
                  <p className="pp-texto"><span className="pp-rotulo">Por que</span>{guia.porque}</p>
                  <p className="pp-texto"><span className="pp-rotulo">O que fazer</span>{fazerTexto}</p>
                </>
              )}
              <div className="pp-acoes">
                {!feito && !naoSeAplica && destino && acao && (
                  <BotaoBrilho size="md" radius={12} onClick={abrirDestino}>{acao} <ArrowRight className="size-4" /></BotaoBrilho>
                )}
                {(feito || naoSeAplica) && proximoDepois && (
                  <button type="button" className="btn pri" onClick={() => ir(proximoDepois.codigo)}>Ir para o próximo passo <ArrowRight /></button>
                )}
                <span className="flex-1" />
                <button type="button" className="pp-nav" disabled={indice === 0} onClick={() => ir(passos[indice - 1].codigo)} aria-label="Passo anterior"><ArrowLeft className="size-4" /></button>
                <button type="button" className="pp-nav" disabled={indice >= passos.length - 1} onClick={() => ir(passos[indice + 1].codigo)} aria-label="Próximo passo"><ArrowRight className="size-4" /></button>
              </div>
            </motion.div>
          </AnimatePresence>
        </div>

        {/* Trilha dos passos */}
        <ol className="pp-trilha" aria-label="Todos os passos">
          {passos.map((p, i) => {
            const pFeito = p.situacao === "feito";
            const pNa = p.situacao === "nao_se_aplica";
            return (
              <li key={p.codigo} data-situacao={p.situacao} className={p.codigo === atual.codigo ? "on" : undefined}>
                <button type="button" onClick={() => ir(p.codigo)} aria-current={p.codigo === atual.codigo ? "step" : undefined}>
                  <span className="pp-marca">
                    {pFeito ? <SpringCheck checked somenteLeitura animarAoAparecer atraso={0.2 + i * 0.08} boxSize={18} boxRadius={999} bounce={0.35} ariaLabel="pronto" />
                      : pNa ? <MinusCircle className="size-[18px]" aria-label="não se aplica" /> : <b>{i + 1}</b>}
                  </span>
                  <span className="pp-trilha-txt">
                    <span className="pp-trilha-titulo">{p.titulo}</span>
                    <small>{pFeito ? "Pronto" : pNa ? "Não se aplica" : p.codigo === dados.proximo ? "Próximo passo" : "Falta"}</small>
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      </div>
      {popup === "crm" && <ModalCrmPasso aoFechar={() => setPopup(null)} aoSalvar={aoMudar} />}
      {popup === "dados" && <ModalDadosEscritorio aoFechar={() => setPopup(null)} aoSalvar={aoMudar} />}
    </motion.section>
  );
}
