import { useEffect, useState } from "react";
import { History, Loader2, ChevronDown, RotateCcw, GitCompare } from "lucide-react";
import { toast } from "sonner";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Aviso } from "@/components/common/Aviso";
import { api, enviar } from "@/api";
import { recolherHandoffsDoBot } from "@/data/handoffTargets";

/**
 * VERSÕES dos prompts do produto (app/gestao/rotas_rascunho.py + migração 008).
 * Cada "Salvar" do editor (e a ativação) grava uma versão: data, autor, resumo e o conteúdo dos agentes.
 * "Ver diferenças" mostra antes e depois lado a lado; "Restaurar no rascunho" leva a versão para o editor —
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

const dataHora = (iso: string) => {
  try {
    return new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch { return iso; }
};

export function VersoesProduto({ idProduto, mudancasNaoSalvas = 0, onRestaurar, c1 = "#2563eb" }: {
  idProduto: string;
  /** Quantas mudanças o rascunho do editor tem e ainda não foram salvas (mostra a linha "Rascunho atual"). */
  mudancasNaoSalvas?: number;
  onRestaurar: (conteudo: ConteudoVersao, numero: number) => void;
  c1?: string;
}) {
  const [lista, setLista] = useState<Versao[] | null>(null);
  const [disponivel, setDisponivel] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [aberta, setAberta] = useState<number | null>(null);
  const [comparar, setComparar] = useState<Record<number, number | "">>({});
  const [detalhes, setDetalhes] = useState<Record<string, Detalhe>>({});
  const [carregando, setCarregando] = useState<string | null>(null);
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
    setCarregando(chave);
    try {
      const d = await api<Detalhe>(`/produtos-ativados/${idProduto}/versoes/${n}${com !== "" ? `?com=${com}` : ""}`);
      setDetalhes((x) => ({ ...x, [chave]: d }));
    } catch (e: any) {
      toast.error("Não deu para abrir as diferenças", { description: e?.message });
    } finally {
      setCarregando(null);
    }
  };

  const restaurar = async (n: number) => {
    setRestaurando(n);
    try {
      const r = await enviar<{ conteudo: ConteudoVersao; numero: number; aviso: string }>(`/produtos-ativados/${idProduto}/versoes/${n}/restaurar`, {});
      onRestaurar(r.conteudo, r.numero);
      toast.success(r.aviso);
    } catch (e: any) {
      toast.error("Não deu para restaurar", { description: e?.message });
    } finally {
      setRestaurando(null);
      setConfirmar(null);
    }
  };

  if (erro) return <Aviso tipo="erro" titulo="Versões indisponíveis">{erro}</Aviso>;
  if (!lista) return <div className="grid place-items-center py-16"><Loader2 className="size-6 animate-spin text-primary" /></div>;

  return (
    <div className="space-y-4">
      <div className="max-w-2xl space-y-1.5">
        <h1 className="text-[1.8rem] font-bold tracking-tight text-[#101828]">Versões dos prompts</h1>
        <p className="text-[#667085]">
          Cada vez que você salva, guardamos o que foi ao ar: prompts, frases de troca, FAQ, objeções e regras.
          Restaurar leva a versão para o rascunho do editor; ela só vai ao ar quando você conferir e salvar.
        </p>
      </div>

      {!disponivel && (
        <Aviso tipo="atencao" titulo="Versões ainda não ligadas neste banco">
          Falta aplicar a migração 008 (db/migracoes/008_agentesia_produto_versoes.sql) no Supabase. Enquanto isso, salvar funciona normalmente, mas sem guardar versões.
        </Aviso>
      )}

      <Card className="lc-card divide-y divide-[#f1f4f8] overflow-hidden">
        {mudancasNaoSalvas > 0 && (
          <div className="flex items-center gap-3 px-4 py-3 bg-amber-50/60">
            <span className="text-[11px] font-bold uppercase tracking-wide rounded-full px-2 py-0.5 border border-amber-300 bg-amber-50 text-amber-800 shrink-0">Rascunho atual</span>
            <span className="text-sm text-[#475467]">{mudancasNaoSalvas} mudança{mudancasNaoSalvas > 1 ? "s" : ""} não publicada{mudancasNaoSalvas > 1 ? "s" : ""}. Vá à Revisão para conferir e salvar.</span>
          </div>
        )}
        {lista.length === 0 && (
          <div className="p-8 text-center text-sm text-[#667085]">
            <History className="size-6 mx-auto mb-2 text-[#cbd5e1]" />
            Nenhuma versão guardada ainda. A primeira aparece no próximo "Salvar".
          </div>
        )}
        {lista.map((v, i) => {
          const aberto = aberta === v.numero;
          const com = comparar[v.numero] ?? "";
          const d = detalhes[chaveDetalhe(v.numero, com)];
          return (
            <div key={v.numero} className="px-4 py-3">
              <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-bold text-[#101828]">v{v.numero}</span>
                    {i === 0 && <span className="text-[10px] font-bold uppercase tracking-wide rounded-full px-2 py-0.5 text-white" style={{ backgroundColor: c1 }}>No ar</span>}
                    <span className="text-xs text-[#667085]">{v.origem === "ativou" ? "ativado" : "salvo"} em {dataHora(v.criado_em)} por <strong className="text-[#344054]">{v.autor}</strong></span>
                  </div>
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {v.resumo.map((r) => <span key={r} className="text-[11px] rounded-md bg-[#f2f4f7] px-1.5 py-0.5 text-[#475467]">{r}</span>)}
                  </div>
                  <div className="mt-1 text-[11px] text-[#98A2B3]">{v.agentes} agentes · {v.faq} FAQ · {v.objecoes} objeções</div>
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                  <Button variant="outline" size="sm" onClick={() => (aberto ? setAberta(null) : void abrir(v.numero))} aria-expanded={aberto}>
                    <GitCompare className="size-3.5 mr-1" />Ver diferenças<ChevronDown className={`size-3.5 ml-1 transition-transform ${aberto ? "rotate-180" : ""}`} />
                  </Button>
                  {confirmar === v.numero ? (
                    <>
                      <Button size="sm" onClick={() => void restaurar(v.numero)} disabled={restaurando !== null} className="text-white" style={{ backgroundColor: c1 }}>
                        {restaurando === v.numero ? <Loader2 className="size-3.5 mr-1 animate-spin" /> : null}Levar para o rascunho
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setConfirmar(null)}>Cancelar</Button>
                    </>
                  ) : (
                    <Button variant="outline" size="sm" onClick={() => setConfirmar(v.numero)}>
                      <RotateCcw className="size-3.5 mr-1" />Restaurar
                    </Button>
                  )}
                </div>
              </div>
              {confirmar === v.numero && (
                <p className="mt-2 text-[11px] text-[#667085]">
                  O que está no editor agora será trocado pela v{v.numero}{mudancasNaoSalvas > 0 ? " (as mudanças não salvas se perdem)" : ""}. O agente no ar não muda até você salvar.
                </p>
              )}
              {aberto && (
                <div className="mt-3 space-y-2.5">
                  <label className="flex items-center gap-2 text-xs text-[#667085]">
                    Comparar com
                    <select className="h-7 rounded-md border border-[#e4e7ec] bg-white px-2 text-xs text-[#101828]" value={com}
                            onChange={(e) => { const n = e.target.value === "" ? "" : Number(e.target.value); setComparar((x) => ({ ...x, [v.numero]: n })); void abrir(v.numero, n); }}>
                      <option value="">{v.numero > 1 ? `a anterior (v${v.numero - 1})` : "nada (primeira versão)"}</option>
                      {lista.filter((o) => o.numero !== v.numero && o.numero !== v.numero - 1).map((o) => <option key={o.numero} value={o.numero}>v{o.numero}</option>)}
                    </select>
                  </label>
                  {!d ? (
                    <div className="py-4 text-center"><Loader2 className="size-4 animate-spin inline text-primary" /></div>
                  ) : d.diferencas.length === 0 ? (
                    <div className="rounded-lg border border-dashed border-[#e5e8ee] p-4 text-center text-xs text-[#667085]">Sem diferença de conteúdo entre as duas versões.</div>
                  ) : d.diferencas.map((x) => (
                    <details key={x.chave} className="rounded-xl border border-border bg-muted/20 p-3" open={d.diferencas.length <= 3}>
                      <summary className="cursor-pointer text-sm font-semibold text-[#101828]">
                        {x.rotulo}{x.mudanca ? ` ${x.mudanca}` : ""}
                      </summary>
                      <div className="mt-2.5 grid md:grid-cols-2 gap-2.5">
                        <div className="rounded-lg border border-border bg-background p-2.5">
                          <div className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-1">
                            {d.comparada_com ? `Antes (v${d.comparada_com})` : "Antes"}
                          </div>
                          <pre className="text-[11px] leading-relaxed whitespace-pre-wrap break-words max-h-64 overflow-auto text-muted-foreground">{recolherHandoffsDoBot(x.antes) || "(vazio)"}</pre>
                        </div>
                        <div className="rounded-lg border p-2.5" style={{ borderColor: `${c1}55`, backgroundColor: `${c1}0a` }}>
                          <div className="text-[10px] font-bold uppercase tracking-wider mb-1" style={{ color: c1 }}>Nesta versão (v{d.numero})</div>
                          <pre className="text-[11px] leading-relaxed whitespace-pre-wrap break-words max-h-64 overflow-auto">{recolherHandoffsDoBot(x.depois) || "(vazio)"}</pre>
                        </div>
                      </div>
                    </details>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </Card>
    </div>
  );
}

export default VersoesProduto;
