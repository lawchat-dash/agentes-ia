import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { AlertTriangle, CheckCircle2, CircleDashed, Loader2, PhoneOff, Radio, ShieldCheck, Stethoscope, XCircle } from "lucide-react";
import { api, formatarTelefone } from "../api";
import { Modal, useCarregar } from "./ui";

/*
 * Saúde do número de WhatsApp (GET /api/saude/numeros e POST /api/saude/numeros/{id}/testar, app/gestao/saude_numero.py):
 * o selo "recebendo mensagens · última há X min" / "sem mensagens há X dias" / "sem número", o tipo do número
 * (API oficial, com a janela de 24 h, ou não oficial) e o "Testar conexão" passo a passo, que só lê.
 */

export type TipoSelo = "recebendo" | "parado" | "sem_mensagens" | "sem_numero";
export interface Selo { tipo: TipoSelo; minutos: number | null }
export interface SaudeAgente {
  id: string; nome: string; situacao: string; id_canal: string | null; numero_normalizado: string | null; tipo: string | null;
  ultima_recebida: string | null; selo: Selo; aviso_tipo: string | null;
}
export interface SaudeCanal {
  id: string; id_canal_helena: string; numero_normalizado: string; tipo: string; ativo: boolean; id_agente: string | null;
  nome_agente: string | null; ultima_recebida: string | null; selo: Selo; aviso_tipo: string | null;
}
export interface Saude { canais: SaudeCanal[]; agentes: SaudeAgente[]; limite_horas: number; agora: string }
interface PassoTeste { codigo: string; titulo: string; situacao: string; detalhe: string }
interface ResultadoTeste { ok: boolean; avisos?: number; passos: PassoTeste[]; tipo: string; aviso_tipo: string | null; conferido_em: string }

export function useSaudeNumeros(escritorio: string | null) {
  const r = useCarregar<Saude>(escritorio ? "/saude/numeros" : null, [escritorio]);
  // Atualiza sozinha (a cada 45 s e ao voltar para a aba): antes ficava "ainda sem mensagens" até recarregar a página.
  const { recarregar } = r;
  useEffect(() => {
    if (!escritorio) return;
    const t = window.setInterval(() => { if (document.visibilityState === "visible") void recarregar(); }, 45_000);
    const aoVoltar = () => { if (document.visibilityState === "visible") void recarregar(); };
    document.addEventListener("visibilitychange", aoVoltar);
    window.addEventListener("focus", aoVoltar);
    return () => { window.clearInterval(t); document.removeEventListener("visibilitychange", aoVoltar); window.removeEventListener("focus", aoVoltar); };
  }, [escritorio, recarregar]);
  return r;
}

/** "há 3 min", "há 2 h", "há 4 dias". */
export function haTempo(minutos: number | null): string {
  if (minutos == null) return "";
  if (minutos < 1) return "agora";
  if (minutos < 60) return `há ${minutos} min`;
  if (minutos < 48 * 60) return `há ${Math.floor(minutos / 60)} h`;
  return `há ${Math.floor(minutos / (24 * 60))} dias`;
}

export function textoDoSelo(selo: Selo): string {
  if (selo.tipo === "sem_numero") return "sem número";
  if (selo.tipo === "sem_mensagens") return "ainda sem mensagens";
  if (selo.tipo === "parado") return `sem mensagens ${haTempo(selo.minutos)}`;
  return `recebendo mensagens · última ${haTempo(selo.minutos)}`;
}

const COR: Record<TipoSelo, string> = {
  recebendo: "bg-[#00BC33]/10 text-[#0a6b25] border-[#00BC33]/30",
  parado: "bg-amber-50 text-amber-800 border-amber-300",
  sem_mensagens: "bg-slate-100 text-slate-600 border-slate-200",
  sem_numero: "bg-amber-50 text-amber-800 border-amber-300",
};

/** Selo da saúde do número. */
export function SeloSaude({ selo, className = "" }: { selo: Selo; className?: string }) {
  const Icone = selo.tipo === "sem_numero" ? PhoneOff : selo.tipo === "recebendo" ? Radio : selo.tipo === "parado" ? AlertTriangle : CircleDashed;
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[10.5px] font-semibold leading-tight ${COR[selo.tipo]} ${className}`}
      title={selo.tipo === "parado" ? "Nenhuma mensagem de lead chegou neste número há mais de 24 h. Use Testar conexão." : undefined}>
      <Icone className={`size-3 shrink-0 ${selo.tipo === "recebendo" ? "animate-pulse" : ""}`} aria-hidden />{textoDoSelo(selo)}
    </span>
  );
}

/** Tipo do número: API oficial (com o lembrete da janela de 24 h) ou não oficial. */
export function TipoNumero({ tipo, aviso, className = "" }: { tipo: string | null; aviso?: string | null; className?: string }) {
  if (!tipo) return null;
  const oficial = tipo === "oficial";
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[10.5px] font-semibold leading-tight ${oficial ? "bg-sky-50 text-sky-800 border-sky-200" : "bg-slate-50 text-slate-600 border-slate-200"} ${className}`}
      title={aviso ?? (oficial ? undefined : "Número não oficial (sem a janela de 24 h da Meta)")}>
      {oficial && <ShieldCheck className="size-3 shrink-0" aria-hidden />}{oficial ? "API oficial · janela de 24 h" : "não oficial"}
    </span>
  );
}

const ICONE_PASSO: Record<string, JSX.Element> = {
  ok: <CheckCircle2 className="size-4 text-[#00a32c]" aria-label="certo" />,
  feito: <CheckCircle2 className="size-4 text-[#00a32c]" aria-label="certo" />,
  aviso: <AlertTriangle className="size-4 text-amber-600" aria-label="atenção" />,
  erro: <XCircle className="size-4 text-red-600" aria-label="erro" />,
  pulado: <CircleDashed className="size-4 text-slate-400" aria-label="pulado" />,
  pendente: <CircleDashed className="size-4 text-slate-400" aria-label="pendente" />,
};

/** Botão "Testar conexão": confere conta, número, webhook e endereço pela LawChat (só lendo) e mostra o passo a passo. */
export function TestarConexao({ idCanal, numero, compacto = false, className = "" }: { idCanal: string; numero?: string; compacto?: boolean; className?: string }) {
  const [aberto, setAberto] = useState(false);
  const [ocupado, setOcupado] = useState(false);
  const [resultado, setResultado] = useState<ResultadoTeste | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const testar = async () => {
    setAberto(true); setOcupado(true); setErro(null); setResultado(null);
    try { setResultado(await api<ResultadoTeste>(`/saude/numeros/${idCanal}/testar`, { metodo: "POST" })); }
    catch (e) { setErro((e as Error).message); }
    finally { setOcupado(false); }
  };
  return (
    <>
      <button type="button" onClick={(e) => { e.preventDefault(); e.stopPropagation(); testar(); }} disabled={ocupado}
        className={compacto
          ? `inline-flex items-center gap-1 rounded-md border border-border bg-card px-2 py-1 text-[11px] font-semibold text-foreground/80 hover:border-[#00BC33]/50 hover:text-foreground transition-colors disabled:opacity-60 ${className}`
          : `btn sm ${className}`}>
        {ocupado ? <Loader2 className="size-3.5 animate-spin" /> : <Stethoscope className="size-3.5" />}Testar conexão
      </button>
      {aberto && createPortal(
        <Modal titulo="Testar conexão" texto={<>Conferência do número {numero ? <b>{/^\d+$/.test(numero) ? formatarTelefone(numero) : numero}</b> : null} pela LawChat. Só lê: nada muda na conta.</>}
          aoFechar={() => setAberto(false)}
          rodape={<><span className="sp" /><button className="btn" onClick={testar} disabled={ocupado}>Testar de novo</button>
            <button className="btn pri" onClick={() => setAberto(false)}>Fechar</button></>}>
          {ocupado && <p className="muted" style={{ margin: 0 }}><Loader2 className="inline size-4 animate-spin mr-1.5" />Conferindo…</p>}
          {erro && <p style={{ margin: 0, color: "#b42318" }}>{erro}</p>}
          {resultado && (
            <div className="flex flex-col gap-2.5">
              <ol className="m-0 p-0 list-none flex flex-col gap-2">
                {resultado.passos.map((p) => (
                  <li key={p.codigo} className="flex items-start gap-2.5">
                    <span className="mt-0.5 shrink-0">{ICONE_PASSO[p.situacao] ?? ICONE_PASSO.pendente}</span>
                    <span className="min-w-0">
                      <b className="text-[13px]">{p.titulo}</b>
                      <span className="block text-[12.5px] text-[#667085] break-words">{p.detalhe}</span>
                    </span>
                  </li>
                ))}
              </ol>
              <p className={`m-0 text-[13px] font-semibold ${!resultado.ok ? "text-red-700" : resultado.avisos ? "text-amber-800" : "text-[#0a6b25]"}`}>
                {!resultado.ok ? "Há um problema: resolva o passo com ✗ e teste de novo. Se precisar, fale com a equipe LawChat."
                  : resultado.avisos ? "Conectado, mas veja os passos com atenção (⚠)." : "Conexão certa."}
              </p>
              {resultado.aviso_tipo && <p className="m-0 text-[12px] text-sky-800">{resultado.aviso_tipo}</p>}
            </div>
          )}
        </Modal>, document.body)}
    </>
  );
}
