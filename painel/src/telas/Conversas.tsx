import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { enviar } from "../api";
import { useAcao, useCarregar, useConfirmar } from "../componentes/ui";
import { useSessao } from "../sessao";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { ListaConversas, type FiltroEstado, type OpcaoAgente } from "@/components/conversas/ListaConversas";
import { ConversaAberta, NenhumaConversa } from "@/components/conversas/ConversaAberta";
import { BotoesIa, PainelLateral } from "@/components/conversas/PainelLateral";
import { ID_VALIDO, nomeDoLead, type AcaoIa, type DetalheConversa, type ResumoConversa } from "@/components/conversas/tipos";
import "@/components/conversas/conversas.css";

/*
 * Conversas: o registro do que o lead escreveu e do que a IA (ou a equipe) respondeu, com os fatos,
 * a etapa, a origem, os turnos e os eventos do lead, o estado da IA e os botões "Desativar IA" (30 min, 2 h, 24 h ou
 * até religar), "Reativar IA" e "Encerrar" (docs/LIGAR_DESLIGAR_IA.md).
 * API: GET /api/conversas?busca=&id_agente=, GET /api/conversas/{id_lead}, POST /api/conversas/{id_lead}/ia {acao, minutos?}
 * e GET /api/agentes (só os nomes, para o filtro por agente).
 * Atendente também usa esta tela (a API é aberta a todos os papéis do escritório).
 */

const LARGA = "(min-width: 1360px)";   // o painel lateral cabe ao lado da conversa (mesmo corte do conversas.css)
const ATUALIZAR_LISTA_MS = 20_000;
const ATUALIZAR_CONVERSA_MS = 8_000;

/** "por 2 horas", "até alguém religar" (texto das confirmações de "Desativar IA"). */
function prazoLegivel(minutos: number): string {
  if (!minutos) return "até alguém religar";
  return minutos % 60 === 0 ? `por ${minutos / 60} ${minutos === 60 ? "hora" : "horas"}` : `por ${minutos} minutos`;
}

const CONFIRMACOES: Record<AcaoIa, { titulo: string; texto: (nome: string, minutos: number) => string; confirmar: string; perigo?: boolean; feito: string }> = {
  desativar: {
    titulo: "Desativar a IA nesta conversa?",
    texto: (nome, minutos) => `A IA para de responder ${nome} ${prazoLegivel(minutos)}, os follow-ups pendentes são cancelados e a etiqueta "🤖 IA Desativada" vai para o contato na Helena, com uma nota no chat.`
      + (minutos ? " Depois do prazo ela volta sozinha, sem mandar mensagem; se o lead escrever no meio tempo, ela responde quando voltar." : ""),
    confirmar: "Desativar IA", feito: "IA desativada nesta conversa.",
  },
  reativar: {
    titulo: "Reativar a IA nesta conversa?",
    texto: (nome) => `A IA volta a responder as próximas mensagens de ${nome}, da etapa em que a conversa estava, sem repetir as boas-vindas. A etiqueta "🤖 IA Desativada" sai do contato. Combine com a equipe para ninguém responder ao mesmo tempo.`,
    confirmar: "Reativar IA", feito: "IA reativada nesta conversa.",
  },
  encerrar: {
    titulo: "Encerrar esta conversa?",
    texto: (nome) => `A IA deixa de responder ${nome} e a conversa sai das que estão em andamento. Se precisar, dá para devolver para a IA depois.`,
    confirmar: "Encerrar", perigo: true, feito: "Conversa encerrada.",
  },
};

/** Conversa encerrada: "Reativar" devolve a conversa para a IA (o lead volta a ser atendido). */
const DEVOLVER_ENCERRADA = {
  titulo: "Devolver a conversa para a IA?",
  texto: (nome: string, _minutos: number) => `A IA volta a responder as próximas mensagens de ${nome}. Combine com a equipe para ninguém responder ao mesmo tempo.`,
  confirmar: "Devolver para a IA", perigo: false, feito: "Conversa devolvida para a IA.",
};

/** O telefone é guardado só com dígitos: "(11) 98765-4321" busca "11987654321". Com letra, é nome e vai como está. */
function termoDaBusca(busca: string): string {
  const b = busca.trim();
  if (/\p{L}/u.test(b)) return b;
  return b.replace(/\D/g, "") || b;
}

function useTelaLarga(): boolean {
  const [larga, setLarga] = useState(() => typeof window !== "undefined" && window.matchMedia(LARGA).matches);
  useEffect(() => {
    const m = window.matchMedia(LARGA);
    const mudou = () => setLarga(m.matches);
    mudou();
    m.addEventListener("change", mudou);
    return () => m.removeEventListener("change", mudou);
  }, []);
  return larga;
}

/** Repete a função enquanto a aba do navegador estiver à vista. */
function useAtualizarSozinho(fn: () => void, ms: number, ligado: boolean) {
  useEffect(() => {
    if (!ligado) return;
    const t = window.setInterval(() => { if (document.visibilityState === "visible") fn(); }, ms);
    return () => window.clearInterval(t);
  }, [fn, ms, ligado]);
}

export function TelaConversas() {
  const { escritorio } = useSessao();
  const { id: idParam } = useParams();
  const navegar = useNavigate();
  const larga = useTelaLarga();
  const [confirmar, janelaConfirmar] = useConfirmar();
  const { ocupado, executar } = useAcao();

  // Filtros: a busca (nome ou telefone) e o agente vão para a API; o estado filtra aqui mesmo.
  const [busca, setBusca] = useState("");
  const [buscaAplicada, setBuscaAplicada] = useState("");
  const [estado, setEstado] = useState<FiltroEstado>("todos");
  const [agente, setAgente] = useState("");
  const [detalhesAbertos, setDetalhesAbertos] = useState(false);
  useEffect(() => {
    const t = window.setTimeout(() => setBuscaAplicada(termoDaBusca(busca)), 300);
    return () => window.clearTimeout(t);
  }, [busca]);

  const idAgente = ID_VALIDO.test(agente) ? agente : "";
  const lista = useCarregar<ResumoConversa[]>(
    escritorio ? `/conversas?busca=${encodeURIComponent(buscaAplicada)}${idAgente ? `&id_agente=${idAgente}` : ""}` : null, [escritorio]);
  const listaDeAgentes = useCarregar<{ id: string; nome: string }[]>(escritorio ? "/agentes" : null, [escritorio]);
  const id = idParam && ID_VALIDO.test(idParam) ? idParam : null;
  const conversa = useCarregar<DetalheConversa>(id ? `/conversas/${id}` : null, [escritorio]);
  // Ao trocar de conversa, a anterior não aparece enquanto a nova carrega.
  const detalhe = conversa.dados && conversa.dados.id === id ? conversa.dados : null;
  const naoEncontrada = Boolean(idParam) && (!id || (!detalhe && /não encontrada/i.test(conversa.erro ?? "")));

  const recarregarLista = lista.recarregar;
  const recarregarConversa = conversa.recarregar;
  useAtualizarSozinho(useCallback(() => { recarregarLista(); }, [recarregarLista]), ATUALIZAR_LISTA_MS, Boolean(escritorio));
  useAtualizarSozinho(useCallback(() => { recarregarConversa(); }, [recarregarConversa]), ATUALIZAR_CONVERSA_MS, Boolean(id && detalhe));
  useEffect(() => { setDetalhesAbertos(false); }, [id]);

  const todas = lista.dados ?? [];
  // Opções do filtro: os agentes do escritório e, se a lista deles não vier, os que aparecem nas conversas.
  const agentes = useMemo<OpcaoAgente[]>(() => {
    const nomes = new Map<string, string>();
    for (const a of listaDeAgentes.dados ?? []) nomes.set(a.id, a.nome);
    for (const c of todas) if (c.id_agente && !nomes.has(c.id_agente)) nomes.set(c.id_agente, c.agente || "Agente sem nome");
    return Array.from(nomes, ([id, nome]) => ({ id, nome })).sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR"));
  }, [listaDeAgentes.dados, todas]);
  // Enquanto a lista do agente novo não chega, a anterior não aparece misturada.
  const doAgente = useMemo(() => (idAgente ? todas.filter((c) => c.id_agente === idAgente) : todas), [todas, idAgente]);
  const contagens = useMemo(() => ({
    todos: doAgente.length,
    ativo: doAgente.filter((c) => c.estado === "ativo").length,
    pausado: doAgente.filter((c) => c.estado === "pausado").length,
    encerrado: doAgente.filter((c) => c.estado === "encerrado").length,
  }), [doAgente]);
  const itens = useMemo(() => (estado === "todos" ? doAgente : doAgente.filter((c) => c.estado === estado)), [doAgente, estado]);

  const agir = async (acao: AcaoIa, minutos = 0) => {
    if (!id || !detalhe) return;
    const c = acao === "reativar" && detalhe.estado === "encerrado" ? DEVOLVER_ENCERRADA : CONFIRMACOES[acao];
    const nome = nomeDoLead(detalhe);
    if (!(await confirmar({ titulo: c.titulo, texto: c.texto(nome, minutos), confirmar: c.confirmar, perigo: c.perigo }))) return;
    await executar(async () => {
      await enviar(`/conversas/${id}/ia`, acao === "desativar" ? { acao, minutos } : { acao });
      await Promise.all([conversa.recarregar(), lista.recarregar()]);
    }, c.feito);
  };

  const limpar = () => { setBusca(""); setBuscaAplicada(""); setEstado("todos"); setAgente(""); };
  const voltar = () => navegar("/conversas");

  return (
    <div className="cv-area" data-aberta={Boolean(idParam)}>
      <ListaConversas
        itens={itens} carregado={Boolean(lista.dados)} erro={lista.erro} atualizando={lista.carregando} totalRecebido={todas.length}
        contagens={contagens} busca={busca} aoBuscar={setBusca} estado={estado} aoFiltrarEstado={setEstado}
        agente={agente} agentes={agentes} aoFiltrarAgente={setAgente}
        selecionado={id} aoRecarregar={() => { lista.recarregar(); }} aoLimpar={limpar} />

      {!idParam ? (
        <div className="cv-conversa-vazia" style={{ gridColumn: larga ? "span 2" : undefined }}>
          <NenhumaConversa />
        </div>
      ) : (
        <>
          <ConversaAberta detalhe={detalhe} erro={conversa.erro} naoEncontrada={naoEncontrada} aoVoltar={voltar}
            aoRecarregar={() => { conversa.recarregar(); }}
            aoAbrirDetalhes={!larga && detalhe ? () => setDetalhesAbertos(true) : undefined}
            acoes={!larga && detalhe ? <BotoesIa conversa={detalhe} ocupado={ocupado} aoAgir={agir} compacto /> : undefined} />
          {larga && (
            <aside className="cv-lateral lc-card relative" aria-label="Detalhes do lead">
              {detalhe ? <PainelLateral detalhe={detalhe} ocupado={ocupado} aoAgir={agir} /> : naoEncontrada ? null : <EsqueletoLateral />}
            </aside>
          )}
        </>
      )}

      {!larga && detalhe && (
        <Sheet open={detalhesAbertos} onOpenChange={setDetalhesAbertos}>
          <SheetContent side="right" className="w-[min(380px,100vw)] sm:max-w-[380px] p-0 flex flex-col gap-0 bg-[#F8FAFC]">
            <SheetHeader className="px-4 pt-4 pb-2 text-left">
              <SheetTitle className="text-[15px]">{nomeDoLead(detalhe)}</SheetTitle>
              <SheetDescription className="text-[12px]">Fatos, memória, etapa, origem, turnos e eventos do lead.</SheetDescription>
            </SheetHeader>
            <div className="flex-1 min-h-0">
              {/* Sem os botões da IA: já ficam no cabeçalho da conversa, e a confirmação aberta daqui
                  ficaria por baixo do overlay da gaveta (sem receber clique nem foco). */}
              <PainelLateral detalhe={detalhe} ocupado={ocupado} aoAgir={agir} semBotoes />
            </div>
          </SheetContent>
        </Sheet>
      )}
      {janelaConfirmar}
    </div>
  );
}

function EsqueletoLateral() {
  return (
    <div className="p-3.5 flex flex-col gap-2.5" role="status" aria-label="Carregando os detalhes">
      <div className="carregando-brilho" style={{ height: 38, borderRadius: 11 }} />
      <div className="carregando-brilho" style={{ height: 38, borderRadius: 11 }} />
      <div className="carregando-brilho" style={{ height: 30, borderRadius: 10, marginTop: 6 }} />
      <div className="carregando-brilho" style={{ height: 180, borderRadius: 14 }} />
      <div className="carregando-brilho" style={{ height: 120, borderRadius: 14 }} />
    </div>
  );
}
