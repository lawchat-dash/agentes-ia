import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Check, Filter, Loader2, Pencil, Phone, Plus, RotateCcw, Trash2, X } from "lucide-react";
import { useSessao } from "../sessao";
import { toast } from "sonner";
import { api, enviar, formatarTelefone } from "../api";

interface Filtro { ligado: boolean; numeros: string[] }

/**
 * Filtro de número do agente: ligado, o agente responde SÓ aos números da lista (bom para testar sozinho com o
 * seu celular). Botão no cartão do agente; mostra "Só 1 número" quando está ligado.
 */
export function FiltroNumero({ idAgente }: { idAgente: string }) {
  const [filtro, setFiltro] = useState<Filtro | null>(null);
  const [aberto, setAberto] = useState(false);
  useEffect(() => {
    let vivo = true;
    api<Filtro>(`/agentes/${idAgente}/filtro-numeros`).then((f) => { if (vivo) setFiltro(f); }).catch(() => { /* sem filtro */ });
    return () => { vivo = false; };
  }, [idAgente]);
  const ligado = !!filtro?.ligado;
  return (
    <>
      <button type="button" onClick={() => setAberto(true)}
        className={`flex w-full items-center gap-2 rounded-xl border px-2.5 py-2 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00bc33] ${ligado ? "border-amber-300 bg-amber-50 hover:bg-amber-100" : "border-border/70 bg-muted/20 hover:bg-muted/40"}`}
        title={ligado ? `Responde só a: ${filtro!.numeros.map(formatarTelefone).join(", ")}` : "Fazer o agente responder só a alguns números (para testar)"}>
        <span className={`grid size-7 shrink-0 place-items-center rounded-lg ${ligado ? "bg-amber-100 text-amber-700" : "bg-white text-muted-foreground"}`}>
          <Filter className="size-3.5" aria-hidden />
        </span>
        <span className="min-w-0 flex-1 leading-tight">
          <span className={`block text-[12px] font-semibold ${ligado ? "text-amber-900" : "text-foreground"}`}>
            {ligado ? `Teste: responde só a ${filtro!.numeros.length} número${filtro!.numeros.length > 1 ? "s" : ""}` : "Filtrar número"}
          </span>
          <span className={`block truncate text-[11px] ${ligado ? "text-amber-800/80" : "text-muted-foreground"}`}>
            {ligado ? filtro!.numeros.map(formatarTelefone).join(", ") : "Responde a todos · toque para testar só com o seu"}
          </span>
        </span>
        <span className={`shrink-0 text-[11px] font-semibold ${ligado ? "text-amber-800" : "text-muted-foreground"}`}>Alterar</span>
      </button>
      {aberto && createPortal(<JanelaFiltro idAgente={idAgente} atual={filtro} aoFechar={() => setAberto(false)} aoSalvar={setFiltro} />, document.body)}
    </>
  );
}

function JanelaFiltro({ idAgente, atual, aoFechar, aoSalvar }: {
  idAgente: string; atual: Filtro | null; aoFechar: () => void; aoSalvar: (f: Filtro) => void;
}) {
  const [ligado, setLigado] = useState(atual?.ligado ?? true);
  // A lista na tela (como a pessoa digitou/formatado). Cada número é uma linha: editar, remover, zerar.
  const [numeros, setNumeros] = useState<string[]>((atual?.numeros ?? []).map(formatarTelefone));
  const [novo, setNovo] = useState("");
  const [editando, setEditando] = useState<number | null>(null);
  const [textoEdicao, setTextoEdicao] = useState("");
  const [salvando, setSalvando] = useState(false);
  const digitos = (n: string) => n.replace(/\D/g, "");
  const valido = (n: string) => { const d = digitos(n); return d.length >= 10 && d.length <= 13; };
  const repetido = (n: string, fora?: number) => numeros.some((x, i) => i !== fora && digitos(x).slice(-11) === digitos(n).slice(-11));
  const adicionar = () => {
    const n = novo.trim();
    if (!n) return;
    if (!valido(n)) { toast.error("Número inválido: use DDD + número, ex.: (31) 98888-7777."); return; }
    if (repetido(n)) { toast.error("Esse número já está na lista."); return; }
    if (numeros.length >= 20) { toast.error("No máximo 20 números."); return; }
    setNumeros([...numeros, formatarTelefone(digitos(n))]);
    setNovo("");
  };
  const confirmarEdicao = (i: number) => {
    const n = textoEdicao.trim();
    if (!valido(n)) { toast.error("Número inválido: use DDD + número, ex.: (31) 98888-7777."); return; }
    if (repetido(n, i)) { toast.error("Esse número já está na lista."); return; }
    setNumeros(numeros.map((x, j) => (j === i ? formatarTelefone(digitos(n)) : x)));
    setEditando(null);
  };
  // Zerar só vale para número que já estava salvo na lista do agente (o servidor confere).
  const salvoNoAgente = (n: string) => (atual?.numeros ?? []).some((s) => digitos(s).slice(-11) === digitos(n).slice(-11));
  const numeroSalvo = (n: string) => (atual?.numeros ?? []).find((s) => digitos(s).slice(-11) === digitos(n).slice(-11)) ?? n;
  const { lawchat } = useSessao();
  const [zerando, setZerando] = useState<string | null>(null);
  const zerar = async (numero: string) => {
    if (!window.confirm(`Zerar a memória de ${formatarTelefone(numero)}?

A conversa, os fatos e a etapa deste número somem do sistema; a próxima mensagem dele recomeça do SDR. Não dá para desfazer.`)) return;
    setZerando(numero);
    try {
      const r = await enviar<{ leads_apagados: number }>(`/agentes/${idAgente}/filtro-numeros/zerar`, { numero });
      toast.success(r.leads_apagados ? `Pronto: ${formatarTelefone(numero)} volta ao início (SDR) na próxima mensagem.` : "Esse número ainda não tinha conversa: nada para zerar.");
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setZerando(null);
    }
  };
  const salvar = async () => {
    setSalvando(true);
    try {
      // O que ficou digitado no campo de adicionar também entra (a pessoa esquece de apertar Adicionar).
      const lista = novo.trim() && valido(novo) && !repetido(novo) ? [...numeros, novo.trim()] : numeros;
      const salvo = await enviar<Filtro>(`/agentes/${idAgente}/filtro-numeros`, { ligado, numeros: lista }, "PUT");
      aoSalvar(salvo);
      toast.success(salvo.ligado ? `Pronto: o agente responde só a ${salvo.numeros.length} número(s).` : "Pronto: o agente voltou a responder todo mundo.");
      aoFechar();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSalvando(false);
    }
  };
  return (
    <div className="fixed inset-0 z-[70] grid place-items-center bg-[rgba(8,14,27,.42)] p-4 backdrop-blur-[2px]" onMouseDown={(e) => e.target === e.currentTarget && aoFechar()}>
      <div role="dialog" aria-label="Filtrar número" className="w-full max-w-md rounded-2xl bg-white p-5 shadow-2xl">
        <div className="flex items-start gap-3">
          <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-amber-50 text-amber-700"><Filter className="size-5" /></span>
          <div className="min-w-0 flex-1">
            <h2 className="text-[16px] font-bold text-[#101828]">Filtrar número</h2>
            <p className="mt-0.5 text-[13px] text-[#667085]">Para testar sozinho: com o filtro ligado, este agente responde só aos números abaixo. As outras mensagens continuam chegando, mas a IA não responde.</p>
          </div>
          <button type="button" onClick={aoFechar} className="grid size-8 place-items-center rounded-lg text-[#98A2B3] hover:bg-[#f2f4f7]" aria-label="Fechar"><X className="size-4" /></button>
        </div>
        <label className="mt-4 flex cursor-pointer items-center justify-between gap-3 rounded-xl border border-[#eef1f5] bg-[#f8fafc] px-3.5 py-3">
          <span>
            <span className="block text-[14px] font-semibold text-[#101828]">Responder só a estes números</span>
            <span className="block text-[12px] text-[#667085]">{ligado ? "Ligado: só a lista recebe resposta" : "Desligado: responde todo mundo"}</span>
          </span>
          <input type="checkbox" className="size-5 accent-[#00a32c]" checked={ligado} onChange={(e) => setLigado(e.target.checked)} />
        </label>
        {/* Adicionar número */}
        <div className="mt-4">
          <span className="text-[13px] font-semibold text-[#344054]">Números que a IA responde</span>
          <div className="mt-1.5 flex gap-2">
            <input value={novo} onChange={(e) => setNovo(e.target.value)} inputMode="tel" placeholder="(31) 98888-7777"
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); adicionar(); } }}
              className="h-10 min-w-0 flex-1 rounded-xl border border-[#d0d5dd] px-3 text-[14px] outline-none focus:border-[#00bc33] focus:ring-2 focus:ring-[#00bc33]/20" />
            <button type="button" onClick={adicionar}
              className="inline-flex h-10 shrink-0 items-center gap-1.5 rounded-xl border border-[#c6f0d2] bg-[#ecfdf3] px-3.5 text-[13px] font-semibold text-[#067a2b] hover:bg-[#d1fadf]">
              <Plus className="size-4" />Adicionar
            </button>
          </div>
        </div>

        {/* A lista: cada número numa linha, com editar, remover e (equipe LawChat) zerar */}
        <div className="mt-3 max-h-[300px] space-y-1.5 overflow-y-auto pr-0.5">
          {numeros.length === 0 && (
            <div className="rounded-xl border border-dashed border-[#e4e7ec] px-3 py-4 text-center text-[13px] text-[#98A2B3]">
              Nenhum número ainda. Adicione o seu para testar.
            </div>
          )}
          {numeros.map((n, i) => (
            <div key={`${n}-${i}`} className="rounded-xl border border-[#eef1f5] bg-[#f8fafc] px-3 py-2">
              {editando === i ? (
                <div className="flex items-center gap-2">
                  <input autoFocus value={textoEdicao} onChange={(e) => setTextoEdicao(e.target.value)} inputMode="tel"
                    onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); confirmarEdicao(i); } if (e.key === "Escape") setEditando(null); }}
                    className="h-9 min-w-0 flex-1 rounded-lg border border-[#00bc33] bg-white px-2.5 text-[14px] outline-none ring-2 ring-[#00bc33]/15" />
                  <button type="button" onClick={() => confirmarEdicao(i)} className="grid size-9 place-items-center rounded-lg bg-[#00a32c] text-white hover:bg-[#008a25]" aria-label="Confirmar"><Check className="size-4" /></button>
                  <button type="button" onClick={() => setEditando(null)} className="grid size-9 place-items-center rounded-lg text-[#667085] hover:bg-[#eef1f5]" aria-label="Cancelar edição"><X className="size-4" /></button>
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-white text-[#00a32c] shadow-[0_1px_2px_rgba(16,24,40,.06)]"><Phone className="size-4" /></span>
                  <span className="min-w-0 flex-1 truncate text-[14px] font-semibold tabular-nums text-[#101828]">{n}</span>
                  <button type="button" onClick={() => { setEditando(i); setTextoEdicao(n); }} title="Editar"
                    className="grid size-8 place-items-center rounded-lg text-[#667085] hover:bg-white hover:text-[#101828]" aria-label={`Editar ${n}`}><Pencil className="size-4" /></button>
                  <button type="button" onClick={() => setNumeros(numeros.filter((_, j) => j !== i))} title="Remover"
                    className="grid size-8 place-items-center rounded-lg text-[#667085] hover:bg-[#fef3f2] hover:text-[#b42318]" aria-label={`Remover ${n}`}><Trash2 className="size-4" /></button>
                </div>
              )}
              {lawchat && editando !== i && salvoNoAgente(n) && (
                <button type="button" onClick={() => void zerar(numeroSalvo(n))} disabled={zerando === numeroSalvo(n)}
                  className="mt-2 inline-flex items-center gap-1.5 rounded-lg border border-[#fecdca] bg-white px-2.5 py-1 text-[12px] font-semibold text-[#b42318] hover:bg-[#fef3f2] disabled:opacity-60"
                  title="Só equipe LawChat: apaga a conversa, os fatos e a etapa deste número; ele recomeça do SDR">
                  {zerando === numeroSalvo(n) ? <Loader2 className="size-3.5 animate-spin" /> : <RotateCcw className="size-3.5" />}Zerar e voltar ao SDR
                </button>
              )}
            </div>
          ))}
        </div>
        {lawchat && numeros.some((n) => salvoNoAgente(n)) && (
          <p className="mt-2 text-[11px] text-[#98A2B3]">"Zerar e voltar ao SDR" é só da equipe LawChat e vale para números já salvos.</p>
        )}
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" onClick={aoFechar} className="h-10 rounded-xl border border-[#d0d5dd] px-4 text-[14px] font-semibold text-[#344054] hover:bg-[#f9fafb]">Cancelar</button>
          <button type="button" onClick={() => void salvar()} disabled={salvando}
            className="inline-flex h-10 items-center gap-2 rounded-xl bg-[#00a32c] px-4 text-[14px] font-semibold text-white hover:bg-[#008a25] disabled:opacity-60">
            {salvando && <Loader2 className="size-4 animate-spin" />}Salvar
          </button>
        </div>
      </div>
    </div>
  );
}
