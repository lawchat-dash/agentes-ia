import { useEffect, useState, type ReactNode } from "react";
import { History, Loader2, ChevronDown, RotateCcw, GitCompare, Radio, PencilLine, ArrowRight, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Aviso } from "@/components/common/Aviso";
import { api, enviar } from "@/api";
import { recolherHandoffsDoBot } from "@/data/handoffTargets";

/**
 * VERSÕES dos prompts do produto (app/gestao/rotas_rascunho.py + migração 008).
 * Cada "Salvar" do editor (e a ativação) grava uma versão: data, autor, resumo e o conteúdo dos agentes.
 * A tela separa 3 coisas: o que está NO AR (a versão mais nova), o RASCUNHO (mudanças do editor ainda não salvas)
 * e o HISTÓRICO (versões anteriores). "Usar esta versão como rascunho" leva a versão para o editor —
 * o agente no ar só muda quando a pessoa confere e salva.
 */

export interface ConteudoVersao {
  agentes: { papel: string; nome: string; boas_vindas: string; prompt: string; mensagem_troca: string }[];
  faq: { pergunta: string; resposta: string }[];
  objecoes: { titulo: string; resposta: string }[];
  regras_markdown: string;
  dados_escritorio: string;
}

interface Versao { numero: number; origem: string; autor: string; resumo: string[]; criado_em: string; agentes: number; faq: number; objecoes: number }
interface Diferenca { chave: string; rotulo: string; tipo: string; mudanca?: string; antes: string; depois: string }
interface Detalhe { numero: number; comparada_com: number | null; diferencas: Diferenca[] }

const ANO_ATUAL = new Date().getFullYear();
/** "26/11 às 03:31" (com o ano só quando não é o ano atual). */
const quando = (iso: string) => {
  try {
    const d = new Date(iso);
    const dia = d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit", ...(d.getFullYear() !== ANO_ATUAL ? { year: "numeric" } : {}) });
    const hora = d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
    return `${dia} às ${hora}`;
  } catch { return iso; }
};

const contar = (n: number, um: string, varios: string, nenhum: string) => (n === 0 ? nenhum : n === 1 ? `1 ${um}` : `${n} ${varios}`);
const contadores = (v: Versao) => [
  contar(v.agentes, "etapa de agente", "etapas de agente", "nenhuma etapa de agente"),
  contar(v.faq, "pergunta frequente", "perguntas frequentes", "nenhuma pergunta frequente"),
  contar(v.objecoes, "objeção", "objeções", "nenhuma objeção"),
].join(" · ");

/** O resumo gravado na 1ª versão é só um marcador ("Versão inicial (ativação)"), não uma mudança. */
const ehMarcadorInicial = (r: string) => /^(Versão inicial|Primeira versão)/i.test(r);

/** Sem o atalho do pai: troca para a aba Editar e abre a etapa Revisão do editor. */
const irParaRevisaoPelaTela = () => {
  const abaEditar = document.querySelector<HTMLButtonElement>('[role="tab"][aria-label="Editar"]');
  abaEditar?.click();
  window.setTimeout(() => {
    const revisao = Array.from(document.querySelectorAll<HTMLButtonElement>("button"))
      .find((b) => !b.disabled && b.textContent?.trim().replace(/^\d+/, "").trim() === "Revisão");
    revisao?.click();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, 60);
};

export function VersoesProduto({ idProduto, mudancasNaoSalvas = 0, onRestaurar, onIrParaRevisao, c1 = "#2563eb" }: {
  idProduto: string;
  /** Quantas mudanças o rascunho do editor tem e ainda não foram salvas (mostra o cartão "Rascunho"). */
  mudancasNaoSalvas?: number;
  onRestaurar: (conteudo: ConteudoVersao, numero: number) => void;
  /** Leva para a etapa Revisão do editor (conferir e salvar o rascunho). Sem ele, a tela troca de aba sozinha. */
  onIrParaRevisao?: () => void;
  c1?: string;
}) {
  const [lista, setLista] = useState<Versao[] | null>(null);
  const [disponivel, setDisponivel] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [aberta, setAberta] = useState<number | null>(null);
  const [comparar, setComparar] = useState<Record<number, number | "">>({});
  const [detalhes, setDetalhes] = useState<Record<string, Detalhe>>({});
  const [restaurando, setRestaurando] = useState<number | null>(null);
  const [confirmar, setConfirmar] = useState<number | null>(null);

  useEffect(() => {
    let vivo = true;
    api<{ disponivel: boolean; versoes: Versao[] }>(`/produtos-ativados/${idProduto}/versoes`)
      .then((r) => { if (vivo) { setLista(r.versoes); setDisponivel(r.disponivel); } })
      .catch((e) => { if (vivo) setErro(e?.message ?? "Não deu para carregar as versões."); });
    return () => { vivo = false; };
  }, [idProduto]);

  const chaveDetalhe = (n: number, com: number | "") => `${n}:${com}`;
  const abrir = async (n: number, com: number | "" = comparar[n] ?? "") => {
    setAberta(n);
    const chave = chaveDetalhe(n, com);
    if (detalhes[chave]) return;
    try {
      const d = await api<Detalhe>(`/produtos-ativados/${idProduto}/versoes/${n}${com !== "" ? `?com=${com}` : ""}`);
      setDetalhes((x) => ({ ...x, [chave]: d }));
    } catch (e: any) {
      toast.error("Não deu para abrir as diferenças", { description: e?.message });
    }
  };
  const escolherComparacao = (n: number, com: number | "") => { setComparar((x) => ({ ...x, [n]: com })); void abrir(n, com); };

  const restaurar = async (n: number) => {
    setRestaurando(n);
    try {
      const r = await enviar<{ conteudo: ConteudoVersao; numero: number; aviso: string }>(`/produtos-ativados/${idProduto}/versoes/${n}/restaurar`, {});
      onRestaurar(r.conteudo, r.numero);
      toast.success(r.aviso);
    } catch (e: any) {
      toast.error("Não deu para usar esta versão", { description: e?.message });
    } finally {
      setRestaurando(null);
      setConfirmar(null);
    }
  };

  const irParaRevisao = () => (onIrParaRevisao ? onIrParaRevisao() : irParaRevisaoPelaTela());

  if (erro) return <Aviso tipo="erro" titulo="Versões indisponíveis">{erro}</Aviso>;
  if (!lista) return <div className="grid place-items-center py-16"><Loader2 className="size-6 animate-spin text-primary" /></div>;

  const noAr = lista[0];
  const anteriores = lista.slice(1);
  const temRascunho = mudancasNaoSalvas > 0;

  return (
    <div className="space-y-5">
      <div className="max-w-2xl space-y-1.5">
        <h1 className="text-[1.8rem] font-bold tracking-tight text-[#101828]">Versões dos prompts</h1>
        <p className="text-[#667085]">
          Toda vez que você salva, guardamos uma cópia de tudo o que o agente usa: prompts, frases de troca,
          perguntas frequentes, objeções e regras. Assim dá para ver o que mudou e voltar atrás quando quiser.
        </p>
      </div>

      {!disponivel && (
        <Aviso tipo="atencao" titulo="Versões ainda não ligadas neste banco">
          Falta aplicar a migração 008 (db/migracoes/008_agentesia_produto_versoes.sql) no Supabase. Enquanto isso, salvar funciona normalmente, mas sem guardar versões.
        </Aviso>
      )}

      {/* Os 3 estados: no ar, rascunho e histórico */}
      <div className="grid gap-3 md:grid-cols-3">
        <Card className="lc-card p-4" style={{ borderColor: `${c1}55` }}>
          <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wide" style={{ color: c1 }}>
            <Radio className="size-4" />No ar agora
          </div>
          {noAr ? (
            <>
              <div className="mt-2 text-lg font-bold text-[#101828]">Versão {noAr.numero}</div>
              <div className="text-xs text-[#667085]">desde {quando(noAr.criado_em)} · por {noAr.autor}</div>
            </>
          ) : (
            <div className="mt-2 text-sm font-semibold text-[#101828]">Nenhuma versão guardada ainda</div>
          )}
          <p className="mt-2 text-xs text-[#475467]">É o que os leads recebem hoje nas conversas.</p>
        </Card>

        <Card className={`lc-card p-4 ${temRascunho ? "border-amber-300 bg-amber-50/50" : ""}`}>
          <div className={`flex items-center gap-2 text-xs font-bold uppercase tracking-wide ${temRascunho ? "text-amber-800" : "text-[#667085]"}`}>
            <PencilLine className="size-4" />Rascunho
          </div>
          {temRascunho ? (
            <>
              <div className="mt-2 text-lg font-bold text-[#101828]">
                {mudancasNaoSalvas} mudança{mudancasNaoSalvas > 1 ? "s" : ""} não salva{mudancasNaoSalvas > 1 ? "s" : ""}
              </div>
              <p className="mt-1 text-xs text-[#475467]">O que você editou e ainda não foi ao ar. Os leads só recebem depois que você salvar.</p>
              <Button size="sm" className="mt-3 text-white" style={{ backgroundColor: c1 }} onClick={irParaRevisao}>
                Conferir e salvar<ArrowRight className="size-3.5 ml-1" />
              </Button>
            </>
          ) : (
            <>
              <div className="mt-2 flex items-center gap-1.5 text-sm font-semibold text-[#101828]">
                <CheckCircle2 className="size-4 text-emerald-600" />Nada pendente
              </div>
              <p className="mt-1 text-xs text-[#475467]">O editor está igual ao que está no ar. Quando você mudar algo e não salvar, aparece aqui.</p>
            </>
          )}
        </Card>

        <Card className="lc-card p-4">
          <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wide text-[#667085]">
            <History className="size-4" />Histórico
          </div>
          <div className="mt-2 text-lg font-bold text-[#101828]">
            {lista.length === 0 ? "Vazio" : lista.length === 1 ? "1 versão guardada" : `${lista.length} versões guardadas`}
          </div>
          <p className="mt-1 text-xs text-[#475467]">
            Versões que já estiveram no ar. Você pode ver o que cada uma mudou e usar uma delas como ponto de partida do rascunho.
          </p>
        </Card>
      </div>

      {/* Linha do tempo */}
      <div>
        <h2 className="mb-2 text-sm font-bold text-[#101828]">Linha do tempo</h2>
        <Card className="lc-card overflow-hidden">
          {lista.length === 0 && (
            <div className="p-8 text-center text-sm text-[#667085]">
              <History className="size-6 mx-auto mb-2 text-[#cbd5e1]" />
              Nenhuma versão guardada ainda. A primeira aparece no próximo "Salvar".
            </div>
          )}
          <ol className="relative">
            {lista.map((v, i) => {
              const ehNoAr = i === 0;
              const ehPrimeira = i === lista.length - 1 && v.numero === 1;
              const substituidaEm = i > 0 ? lista[i - 1].criado_em : null;
              const aberto = aberta === v.numero;
              const com = comparar[v.numero] ?? "";
              const d = detalhes[chaveDetalhe(v.numero, com)];
              const mudancas = v.resumo.filter((r) => !ehMarcadorInicial(r));
              const titulo = ehPrimeira
                ? `Versão ${v.numero} · ${v.origem === "ativou" ? "primeira ativação" : "primeira versão guardada"}`
                : `Versão ${v.numero}`;
              const outras = lista.filter((o) => o.numero !== v.numero && o.numero !== v.numero - 1 && o.numero !== noAr.numero);
              return (
                <li key={v.numero} className="relative pl-10 pr-4 py-4 border-b border-[#f1f4f8] last:border-b-0">
                  {/* trilho e marcador da linha do tempo */}
                  {i < lista.length - 1 && <span className="absolute left-[19px] top-7 bottom-0 w-px bg-[#e4e7ec]" aria-hidden />}
                  {i > 0 && <span className="absolute left-[19px] top-0 h-5 w-px bg-[#e4e7ec]" aria-hidden />}
                  <span className="absolute left-[13px] top-5 size-3.5 rounded-full border-2 bg-white"
                        style={ehNoAr ? { borderColor: c1, backgroundColor: c1 } : { borderColor: "#cbd5e1" }} aria-hidden />

                  <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-bold text-[#101828]">{titulo}</span>
                        {ehNoAr && <span className="text-[10px] font-bold uppercase tracking-wide rounded-full px-2 py-0.5 text-white" style={{ backgroundColor: c1 }}>No ar</span>}
                      </div>
                      <div className="mt-0.5 text-xs text-[#667085]">
                        {ehNoAr
                          ? <>No ar desde {quando(v.criado_em)}</>
                          : <>Esteve no ar de {quando(v.criado_em)} até {quando(substituidaEm!)}</>}
                        {" · "}{v.origem === "ativou" ? "ativada" : "salva"} por <strong className="text-[#344054]">{v.autor}</strong>
                      </div>

                      <div className="mt-2 text-xs font-semibold text-[#344054]">O que mudou nesta versão:</div>
                      {ehPrimeira ? (
                        <div className="mt-1 text-xs text-[#667085]">É a primeira versão guardada: o ponto de partida, sem nada antes para comparar.</div>
                      ) : mudancas.length === 0 ? (
                        <div className="mt-1 text-xs text-[#667085]">Nenhuma mudança nos textos em relação à versão anterior.</div>
                      ) : (
                        <div className="mt-1 flex flex-wrap gap-1.5">
                          {mudancas.map((r) => <span key={r} className="text-[11px] rounded-md bg-[#f2f4f7] px-1.5 py-0.5 text-[#475467]">{r}</span>)}
                        </div>
                      )}
                      <div className="mt-2 text-[11px] text-[#98A2B3]">Nesta versão: {contadores(v)}</div>
                    </div>

                    <div className="flex flex-wrap items-center gap-1.5 shrink-0">
                      <Button variant="outline" size="sm" onClick={() => (aberto ? setAberta(null) : void abrir(v.numero))} aria-expanded={aberto}>
                        <GitCompare className="size-3.5 mr-1" />{aberto ? "Fechar comparação" : "Ver diferenças"}
                        <ChevronDown className={`size-3.5 ml-1 transition-transform ${aberto ? "rotate-180" : ""}`} />
                      </Button>
                      {ehNoAr ? (
                        <span className="text-[11px] text-[#98A2B3] px-1">Esta já é a versão no ar</span>
                      ) : (
                        <Button variant="outline" size="sm" onClick={() => setConfirmar(v.numero)} disabled={restaurando !== null}>
                          {restaurando === v.numero ? <Loader2 className="size-3.5 mr-1 animate-spin" /> : <RotateCcw className="size-3.5 mr-1" />}
                          Usar esta versão como rascunho
                        </Button>
                      )}
                    </div>
                  </div>

                  {aberto && (
                    <div className="mt-3 space-y-2.5 rounded-xl border border-[#e4e7ec] bg-[#fafbfc] p-3">
                      <div className="flex flex-wrap items-center gap-1.5 text-xs text-[#667085]">
                        <span className="mr-1 font-semibold text-[#344054]">Comparar a versão {v.numero} com:</span>
                        <Escolha ativo={com === ""} c1={c1} onClick={() => escolherComparacao(v.numero, "")}>
                          {v.numero > 1 ? `a versão anterior (${v.numero - 1})` : "nada (é a primeira)"}
                        </Escolha>
                        {!ehNoAr && noAr.numero !== v.numero - 1 && (
                          <Escolha ativo={com === noAr.numero} c1={c1} onClick={() => escolherComparacao(v.numero, noAr.numero)}>
                            o que está no ar (versão {noAr.numero})
                          </Escolha>
                        )}
                        {outras.length > 0 && (
                          <select aria-label="Comparar com outra versão"
                                  className="h-7 rounded-full border border-[#e4e7ec] bg-white px-2 text-xs text-[#101828]"
                                  value={typeof com === "number" && com !== noAr.numero ? com : ""}
                                  onChange={(e) => { if (e.target.value !== "") escolherComparacao(v.numero, Number(e.target.value)); }}>
                            <option value="">outra versão…</option>
                            {outras.map((o) => <option key={o.numero} value={o.numero}>versão {o.numero}</option>)}
                          </select>
                        )}
                      </div>
                      {!d ? (
                        <div className="py-4 text-center"><Loader2 className="size-4 animate-spin inline text-primary" /></div>
                      ) : d.diferencas.length === 0 ? (
                        <div className="rounded-lg border border-dashed border-[#e5e8ee] bg-white p-4 text-center text-xs text-[#667085]">
                          {d.comparada_com ? `Os textos da versão ${d.numero} e da versão ${d.comparada_com} são iguais.` : "Não há nada para comparar."}
                        </div>
                      ) : (
                        <>
                          <p className="text-[11px] text-[#667085]">
                            {d.diferencas.length} parte{d.diferencas.length > 1 ? "s" : ""} diferente{d.diferencas.length > 1 ? "s" : ""}.
                            À esquerda {d.comparada_com ? `a versão ${d.comparada_com}` : "o que havia antes"}, à direita a versão {d.numero}.
                          </p>
                          {d.diferencas.map((x) => (
                            <details key={x.chave} className="rounded-xl border border-border bg-white p-3" open={d.diferencas.length <= 3}>
                              <summary className="cursor-pointer text-sm font-semibold text-[#101828]">
                                {x.rotulo}{x.mudanca ? ` ${x.mudanca}` : ""}
                              </summary>
                              <div className="mt-2.5 grid md:grid-cols-2 gap-2.5">
                                <div className="rounded-lg border border-border bg-background p-2.5">
                                  <div className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-1">
                                    {d.comparada_com ? `Versão ${d.comparada_com}${d.comparada_com === noAr.numero ? " (no ar)" : ""}` : "Antes"}
                                  </div>
                                  <pre className="text-[11px] leading-relaxed whitespace-pre-wrap break-words max-h-64 overflow-auto text-muted-foreground">{recolherHandoffsDoBot(x.antes) || "(vazio)"}</pre>
                                </div>
                                <div className="rounded-lg border p-2.5" style={{ borderColor: `${c1}55`, backgroundColor: `${c1}0a` }}>
                                  <div className="text-[10px] font-bold uppercase tracking-wider mb-1" style={{ color: c1 }}>
                                    Versão {d.numero}{d.numero === noAr.numero ? " (no ar)" : ""}
                                  </div>
                                  <pre className="text-[11px] leading-relaxed whitespace-pre-wrap break-words max-h-64 overflow-auto">{recolherHandoffsDoBot(x.depois) || "(vazio)"}</pre>
                                </div>
                              </div>
                            </details>
                          ))}
                        </>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ol>
        </Card>
        {anteriores.length === 0 && lista.length === 1 && (
          <p className="mt-2 text-xs text-[#98A2B3]">Ainda só existe a versão no ar. As próximas aparecem aqui sempre que você salvar.</p>
        )}
      </div>

      <AlertDialog open={confirmar !== null} onOpenChange={(o) => { if (!o && restaurando === null) setConfirmar(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Usar a versão {confirmar} como rascunho?</AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="space-y-2 text-sm text-[#475467]">
                <p>Os textos da versão {confirmar} vão para o editor, no lugar do que está lá agora.</p>
                <p><strong className="text-[#101828]">Nada muda para os leads ainda.</strong> A versão {noAr?.numero} continua no ar até você conferir e salvar.</p>
                {temRascunho && (
                  <p className="text-amber-800">
                    Atenção: você tem {mudancasNaoSalvas} mudança{mudancasNaoSalvas > 1 ? "s" : ""} não salva{mudancasNaoSalvas > 1 ? "s" : ""} no rascunho. {mudancasNaoSalvas > 1 ? "Elas serão descartadas." : "Ela será descartada."}
                  </p>
                )}
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={restaurando !== null}>Cancelar</AlertDialogCancel>
            <AlertDialogAction disabled={restaurando !== null} className="text-white" style={{ backgroundColor: c1 }}
                               onClick={(e) => { e.preventDefault(); if (confirmar !== null) void restaurar(confirmar); }}>
              {restaurando !== null ? <Loader2 className="size-3.5 mr-1 animate-spin" /> : null}Usar como rascunho
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

function Escolha({ ativo, c1, onClick, children }: { ativo: boolean; c1: string; onClick: () => void; children: ReactNode }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={ativo}
            className={`h-7 rounded-full border px-2.5 text-xs font-medium transition-colors ${ativo ? "" : "border-[#e4e7ec] bg-white text-[#475467] hover:bg-[#f2f4f7]"}`}
            style={ativo ? { borderColor: c1, color: c1, backgroundColor: `${c1}12` } : undefined}>
      {children}
    </button>
  );
}

export default VersoesProduto;
