import { useEffect, useRef, useState } from "react";
import { Send, RotateCcw, Loader2, FlaskConical, UserPlus, ArrowRight, ChevronDown, AlertTriangle, Coins } from "lucide-react";
import { toast } from "sonner";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, enviar, ErroApi } from "@/api";

/**
 * TESTE DO RASCUNHO — o motor REAL do servidor (app/gestao/rotas_rascunho.py), não uma simulação no navegador.
 *
 * A cada mensagem manda o conteúdo que está na tela (o mesmo payload de ativar/sincronizar, ainda não salvo) e o
 * servidor roda o turno de verdade em memória: sem número, sem LawChat, sem gravar lead. Cada resposta mostra a
 * etapa, os fatos extraídos, as travas acionadas, a troca de agente e o custo estimado em R$.
 * O teste gasta créditos da carteira (com o modelo falso, em teste local, não gasta) e respeita o "pode gastar?".
 */

export interface EtapaDoTeste { role: string; name: string }

interface Resposta {
  id_conversa: string;
  situacao: string;
  motivo: string;
  mensagens: { tipo?: string; texto?: string; url?: string }[];
  etapa: string | null;
  etapa_nome: string | null;
  troca: { de: string; de_nome: string; para: string; para_nome: string } | null;
  fatos_novos: { chave: string; valor: unknown; trecho?: string }[];
  fatos: Record<string, unknown>;
  travas: { codigo: string; orientacao: string }[];
  estado: string;
  custo_brl: number;
  gastou: boolean;
}

interface Info { gasta_creditos: boolean; modelo_falso: boolean; pode_gastar: boolean; disponivel_brl: number | null; aviso: string | null }

type Item = { tipo: "lead"; texto: string } | { tipo: "ia"; r: Resposta } | { tipo: "erro"; texto: string };

const brl = (v: number) => v.toLocaleString("pt-BR", { style: "currency", currency: "BRL", minimumFractionDigits: 2, maximumFractionDigits: v > 0 && v < 0.01 ? 4 : 2 });
const ROTULO_TRAVA: Record<string, string> = {
  promessa: "promessa de resultado", garantia: "garantia de resultado", valor: "valor não autorizado",
  resposta_vazia: "resposta vazia", catalogo: "regra do produto",
};
const rotuloTrava = (c: string) => ROTULO_TRAVA[c] ?? c.replace(/_/g, " ");
const valorFato = (v: unknown) => (typeof v === "string" ? v : JSON.stringify(v));

export function TestePrompt({ idProduto, obterRascunho, etapas, etapaSugerida, c1 = "#2563eb", className }: {
  /** id do produto ativado (o rascunho do assistente ou o produto no ar). */
  idProduto: string | null;
  /** Monta o payload com o que está na tela agora (prompts, FAQ, objeções, regras) — mesmo do ativar/sincronizar. */
  obterRascunho: () => Promise<any>;
  /** Etapas do funil, na ordem (a primeira é onde o lead novo entra). */
  etapas: EtapaDoTeste[];
  /** Etapa que está sendo editada (sugere "começar aqui"). */
  etapaSugerida?: string;
  c1?: string;
  className?: string;
}) {
  const [info, setInfo] = useState<Info | null>(null);
  const [itens, setItens] = useState<Item[]>([]);
  const [texto, setTexto] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [idConversa, setIdConversa] = useState<string | null>(null);
  const [inicio, setInicio] = useState<string>("");          // "" = a principal (lead novo)
  const [aberto, setAberto] = useState<number | null>(null);
  const [semSaldo, setSemSaldo] = useState<string | null>(null);
  const fimRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!idProduto) return;
    let vivo = true;
    api<Info>(`/produtos-ativados/${idProduto}/laboratorio`).then((i) => { if (vivo) setInfo(i); }).catch(() => null);
    return () => { vivo = false; };
  }, [idProduto]);
  useEffect(() => { fimRef.current?.scrollIntoView({ block: "nearest" }); }, [itens, enviando]);

  const total = itens.reduce((s, it) => s + (it.tipo === "ia" ? it.r.custo_brl : 0), 0);
  const nomeEtapa = (role: string) => etapas.find((e) => e.role === role)?.name ?? role;

  const limpar = async (novoInicio: string) => {
    if (idConversa && idProduto) {
      enviar(`/produtos-ativados/${idProduto}/laboratorio/recomecar`, { id_conversa: idConversa }).catch(() => null);
    }
    setIdConversa(null);
    setItens([]);
    setAberto(null);
    setInicio(novoInicio);
  };

  const mandar = async () => {
    const t = texto.trim();
    if (!t || enviando || !idProduto) return;
    setTexto("");
    setItens((xs) => [...xs, { tipo: "lead", texto: t }]);
    setEnviando(true);
    try {
      const rascunho = await obterRascunho();
      const r = await enviar<Resposta>(`/produtos-ativados/${idProduto}/laboratorio`, {
        texto: t, id_conversa: idConversa, etapa_inicial: idConversa ? null : (inicio || null), rascunho,
      });
      setIdConversa(r.id_conversa);
      setItens((xs) => [...xs, { tipo: "ia", r }]);
      setSemSaldo(null);
    } catch (e: any) {
      if (e instanceof ErroApi && e.status === 402) setSemSaldo(e.message);
      setItens((xs) => [...xs, { tipo: "erro", texto: e?.message ?? "Não deu para testar agora." }]);
      if (!(e instanceof ErroApi)) toast.error("Não deu para testar agora", { description: e?.message });
    } finally {
      setEnviando(false);
    }
  };

  const bloqueado = !idProduto || !!semSaldo || (info ? !info.pode_gastar : false);

  return (
    <Card className={`lc-card flex flex-col overflow-hidden ${className ?? ""}`} style={{ maxHeight: "calc(100vh - 7rem)" }}>
      {/* Topo: o que está sendo testado e onde começa */}
      <div className="border-b border-[#eef1f5] p-4 space-y-2.5">
        <div className="flex items-center gap-2">
          <div className="size-8 rounded-lg grid place-items-center text-white shrink-0" style={{ backgroundColor: c1 }}><FlaskConical className="size-4" /></div>
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold text-[#101828] leading-tight">Testar o rascunho</h3>
            <p className="text-[11px] text-[#667085] leading-tight">O motor de verdade, sem número e sem enviar nada.</p>
          </div>
        </div>
        <span className="inline-flex items-center rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-amber-800">
          Testando o rascunho (não publicado)
        </span>
        {info && (info.gasta_creditos ? (
          <p className="flex items-start gap-1.5 text-[11px] text-[#667085]">
            <Coins className="size-3.5 mt-px shrink-0 text-amber-600" />
            <span>{info.aviso ?? "O teste gasta créditos."}{info.disponivel_brl != null && <> Disponível: <strong>{brl(info.disponivel_brl)}</strong>.</>}</span>
          </p>
        ) : (
          <p className="text-[11px] text-[#667085]">Modelo de teste local: não gasta créditos.</p>
        ))}
        <label className="flex items-center gap-2 text-[11px] text-[#667085]">
          Começar na etapa
          <select
            className="h-7 flex-1 rounded-md border border-[#e4e7ec] bg-white px-2 text-xs text-[#101828]"
            value={inicio}
            onChange={(e) => { void limpar(e.target.value); }}
            aria-label="Começar na etapa"
          >
            <option value="">{etapas[0] ? `${etapas[0].name} (lead novo)` : "Início do funil"}</option>
            {etapas.slice(1).map((e) => <option key={e.role} value={e.role}>{e.name}</option>)}
          </select>
        </label>
        {etapaSugerida && etapaSugerida !== (inicio || etapas[0]?.role) && etapas.some((e) => e.role === etapaSugerida) && itens.length === 0 && (
          <button type="button" className="text-[11px] font-semibold underline-offset-2 hover:underline" style={{ color: c1 }}
                  onClick={() => void limpar(etapaSugerida === etapas[0]?.role ? "" : etapaSugerida)}>
            Começar no {nomeEtapa(etapaSugerida)} (o que você está editando)
          </button>
        )}
      </div>

      {/* Conversa */}
      <div className="flex-1 min-h-[220px] overflow-y-auto bg-[#fafbfc] p-3 space-y-2.5" aria-live="polite">
        {itens.length === 0 && !enviando && (
          <div className="text-center text-xs text-[#98A2B3] py-8 px-4">
            Escreva como um lead escreveria (ex.: "oi, sofri um acidente de moto"). A resposta usa os prompts, a FAQ,
            as objeções e as regras que estão na tela agora, mesmo sem salvar.
          </div>
        )}
        {itens.map((it, i) => {
          if (it.tipo === "lead") return (
            <div key={i} className="flex justify-end"><div className="max-w-[85%] rounded-2xl rounded-br-md bg-[#dcf8c6] px-3 py-2 text-[13px] text-[#101828] whitespace-pre-wrap break-words">{it.texto}</div></div>
          );
          if (it.tipo === "erro") return (
            <div key={i} className="flex items-start gap-1.5 rounded-lg border border-red-200 bg-red-50 px-2.5 py-2 text-[11px] text-red-800"><AlertTriangle className="size-3.5 shrink-0 mt-px" />{it.texto}</div>
          );
          const r = it.r;
          const detalhes = aberto === i;
          return (
            <div key={i} className="space-y-1">
              {r.troca && (
                <div className="flex items-center justify-center gap-1.5 text-[10px] font-bold uppercase tracking-wide text-[#667085]">
                  <span>{r.troca.de_nome}</span><ArrowRight className="size-3" style={{ color: c1 }} /><span style={{ color: c1 }}>{r.troca.para_nome}</span>
                </div>
              )}
              {r.mensagens.length === 0 ? (
                <div className="text-[11px] italic text-[#98A2B3]">A IA não respondeu{r.motivo ? ` (${r.motivo.replace(/_/g, " ")})` : ""}.</div>
              ) : r.mensagens.map((m, j) => (
                <div key={j} className="flex"><div className="max-w-[85%] rounded-2xl rounded-bl-md bg-white border border-[#eef1f5] px-3 py-2 text-[13px] text-[#101828] whitespace-pre-wrap break-words">
                  {m.texto || (m.tipo ? `[${m.tipo}]` : "")}
                </div></div>
              ))}
              <button type="button" onClick={() => setAberto(detalhes ? null : i)} aria-expanded={detalhes}
                      className="flex w-full flex-wrap items-center gap-x-1.5 gap-y-0.5 text-left text-[10.5px] text-[#98A2B3] hover:text-[#667085]">
                <span>Etapa {r.etapa_nome ?? "—"}</span>
                <span>· {r.fatos_novos.length} fato{r.fatos_novos.length === 1 ? "" : "s"} novo{r.fatos_novos.length === 1 ? "" : "s"}</span>
                <span className={r.travas.length ? "text-amber-700" : ""}>· {r.travas.length} trava{r.travas.length === 1 ? "" : "s"}{r.travas.length ? ` (${r.travas.map((t) => rotuloTrava(t.codigo)).join(", ")})` : ""}</span>
                <span>· {brl(r.custo_brl)}</span>
                <span className="inline-flex items-center gap-0.5 font-semibold">· ver detalhes<ChevronDown className={`size-3 transition-transform ${detalhes ? "rotate-180" : ""}`} /></span>
              </button>
              {detalhes && (
                <div className="rounded-lg border border-[#eef1f5] bg-white p-2.5 text-[11px] text-[#475467] space-y-2">
                  <div><strong className="text-[#101828]">Etapa:</strong> {r.etapa_nome ?? "—"}{r.troca ? ` (passou de ${r.troca.de_nome} para ${r.troca.para_nome})` : " (sem troca de agente)"}{r.estado !== "ativo" ? ` · lead ${r.estado}` : ""}</div>
                  <div>
                    <strong className="text-[#101828]">Fatos novos:</strong>{" "}
                    {r.fatos_novos.length === 0 ? "nenhum" : (
                      <ul className="mt-1 space-y-0.5">{r.fatos_novos.map((f, k) => (
                        <li key={k}><code className="text-[10.5px]">{f.chave}</code> = {valorFato(f.valor) || "—"}{f.trecho ? <span className="text-[#98A2B3]"> · “{f.trecho}”</span> : null}</li>
                      ))}</ul>
                    )}
                  </div>
                  <div>
                    <strong className="text-[#101828]">Travas:</strong>{" "}
                    {r.travas.length === 0 ? "nenhuma" : (
                      <ul className="mt-1 space-y-0.5">{r.travas.map((t, k) => <li key={k}><span className="font-semibold text-amber-700">{rotuloTrava(t.codigo)}</span>: {t.orientacao}</li>)}</ul>
                    )}
                  </div>
                  <div><strong className="text-[#101828]">Fatos da conversa:</strong> {Object.keys(r.fatos).length}</div>
                  <div><strong className="text-[#101828]">Custo estimado:</strong> {brl(r.custo_brl)}{r.gastou ? "" : " (não gastou)"}</div>
                </div>
              )}
            </div>
          );
        })}
        {enviando && <div className="flex items-center gap-1.5 text-[11px] text-[#98A2B3]"><Loader2 className="size-3.5 animate-spin" />A IA está respondendo…</div>}
        <div ref={fimRef} />
      </div>

      {/* Enviar e recomeçar */}
      <div className="border-t border-[#eef1f5] p-3 space-y-2">
        {(semSaldo || (info && !info.pode_gastar)) && (
          <div className="flex items-start gap-1.5 rounded-lg border border-amber-300 bg-amber-50 px-2.5 py-2 text-[11px] text-amber-900">
            <AlertTriangle className="size-3.5 shrink-0 mt-px" />{semSaldo ?? "O saldo de IA acabou: recarregue a carteira para testar."}
          </div>
        )}
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); void mandar(); }}>
          <Input value={texto} onChange={(e) => setTexto(e.target.value)} placeholder="Mensagem do lead…" disabled={bloqueado} aria-label="Mensagem do lead de teste" />
          <Button type="submit" size="icon" disabled={bloqueado || enviando || !texto.trim()} aria-label="Enviar" style={{ backgroundColor: c1 }} className="text-white shrink-0">
            {enviando ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
          </Button>
        </form>
        <div className="flex items-center gap-1.5">
          <Button type="button" variant="outline" size="sm" className="h-7 text-[11px]" onClick={() => void limpar(inicio)} disabled={enviando || itens.length === 0}>
            <RotateCcw className="size-3 mr-1" />Recomeçar
          </Button>
          <Button type="button" variant="outline" size="sm" className="h-7 text-[11px]" onClick={() => void limpar("")} disabled={enviando}>
            <UserPlus className="size-3 mr-1" />Testar como lead novo
          </Button>
          {total > 0 && <span className="ml-auto text-[10.5px] text-[#98A2B3] tabular-nums">Total {brl(total)}</span>}
        </div>
      </div>
    </Card>
  );
}

export default TestePrompt;
