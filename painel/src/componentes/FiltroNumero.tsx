import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Filter, Loader2, RotateCcw, X } from "lucide-react";
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
  const [texto, setTexto] = useState((atual?.numeros ?? []).map(formatarTelefone).join("\n"));
  const [salvando, setSalvando] = useState(false);
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
      const numeros = texto.split(/[\n,;]/).map((n) => n.trim()).filter(Boolean);
      const novo = await enviar<Filtro>(`/agentes/${idAgente}/filtro-numeros`, { ligado, numeros }, "PUT");
      aoSalvar(novo);
      toast.success(novo.ligado ? `Pronto: o agente responde só a ${novo.numeros.length} número(s).` : "Pronto: o agente voltou a responder todo mundo.");
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
        <label className="mt-3 block">
          <span className="text-[13px] font-semibold text-[#344054]">Números (um por linha, com DDD)</span>
          <textarea rows={4} value={texto} onChange={(e) => setTexto(e.target.value)} placeholder={"(31) 98888-7777"}
            className="mt-1 w-full rounded-xl border border-[#d0d5dd] px-3 py-2 text-[14px] outline-none focus:border-[#00bc33] focus:ring-2 focus:ring-[#00bc33]/20" />
        </label>
        {lawchat && (atual?.numeros.length ?? 0) > 0 && (
          <div className="mt-4 rounded-xl border border-dashed border-[#fecdca] bg-[#fffbfa] p-3">
            <div className="text-[11px] font-bold uppercase tracking-wider text-[#b42318]">Só equipe LawChat · zerar número de teste</div>
            <p className="mt-0.5 text-[12px] text-[#667085]">Apaga a memória da IA sobre o número (conversa, fatos, etapa) e ele recomeça do SDR.</p>
            <div className="mt-2 space-y-1.5">
              {atual!.numeros.map((n) => (
                <div key={n} className="flex items-center justify-between gap-2 rounded-lg bg-white px-3 py-2 border border-[#f2f4f7]">
                  <span className="text-[13px] font-medium text-[#344054] tabular-nums">{formatarTelefone(n)}</span>
                  <button type="button" onClick={() => void zerar(n)} disabled={zerando === n}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-[#fecdca] px-2.5 py-1 text-[12px] font-semibold text-[#b42318] hover:bg-[#fef3f2] disabled:opacity-60">
                    {zerando === n ? <Loader2 className="size-3.5 animate-spin" /> : <RotateCcw className="size-3.5" />}Zerar e voltar ao SDR
                  </button>
                </div>
              ))}
            </div>
          </div>
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
