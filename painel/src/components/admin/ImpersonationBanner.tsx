import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Eye } from "lucide-react";
import { useSessao } from "@/sessao";

/**
 * Faixa de impersonificação. Aqui a equipe LawChat "entra como cliente" trocando a visão para
 * a do gestor (X-Visao): a sessão continua a mesma, e voltar é só trocar a visão de novo para
 * LawChat.
 *
 * Visual: uma barra fina e arredondada logo abaixo do topo flutuante (mesmas margens dele),
 * com gradiente âmbar bem sutil, ícone, texto direto e um botão discreto para voltar.
 */
export function ImpersonationBanner({ nomeEscritorio }: { nomeEscritorio: string }) {
  const { lawchat, escritorio, visao, trocarVisao } = useSessao();
  const [returning, setReturning] = useState(false);
  const navigate = useNavigate();

  const handleReturn = () => {
    setReturning(true);
    trocarVisao("lawchat");
    setReturning(false);
    navigate("/admin/escritorios", { replace: true });
  };

  if (!lawchat || !escritorio || visao === "lawchat") return null;

  return (
    <div
      role="status"
      aria-live="polite"
      className="relative mx-4 mt-2 flex items-center gap-3 overflow-hidden rounded-xl border border-amber-300/70 bg-gradient-to-r from-amber-50 via-amber-50/80 to-orange-50/60 py-1.5 pl-2 pr-1.5 text-[13px] text-amber-950 shadow-[0_1px_2px_rgba(16,24,40,.04),0_6px_18px_-12px_rgba(180,83,9,.35)] duration-300 animate-in fade-in slide-in-from-top-1 max-[820px]:mx-2 dark:border-amber-500/30 dark:from-amber-500/15 dark:via-amber-500/10 dark:to-orange-500/10 dark:text-amber-100"
    >
      {/* filete à esquerda: marca que é um estado temporário, sem gritar */}
      <span aria-hidden className="absolute inset-y-0 left-0 w-[3px] bg-gradient-to-b from-amber-400 to-orange-400" />

      <span
        aria-hidden
        className="relative ml-1 grid size-6 shrink-0 place-items-center rounded-full bg-amber-500/15 text-amber-600 ring-1 ring-amber-500/25 dark:text-amber-300"
      >
        <Eye className="size-3.5" />
        <span className="absolute -right-0.5 -top-0.5 size-2 rounded-full bg-amber-500 ring-2 ring-amber-50 motion-safe:animate-pulse dark:ring-transparent" />
      </span>

      <p className="m-0 min-w-0 flex-1 truncate leading-tight">
        Você está vendo como <strong className="font-semibold">{nomeEscritorio}</strong>
        <span className="text-amber-800/70 max-sm:hidden dark:text-amber-200/70"> · o acesso de admin fica pausado até você voltar</span>
      </p>

      <button
        type="button"
        onClick={handleReturn}
        disabled={returning}
        className="lc-brilho lc-brilho--borda [--brilho-cor:178_107_0] inline-flex h-7 shrink-0 items-center gap-1.5 rounded-lg border border-amber-400/50 bg-white/70 px-2.5 text-[12.5px] font-medium text-amber-900 shadow-sm transition-[background-color,border-color,box-shadow,transform] duration-150 hover:border-amber-500/70 hover:bg-white hover:shadow focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500/40 active:scale-[.97] disabled:opacity-60 dark:bg-amber-500/10 dark:text-amber-100 dark:hover:bg-amber-500/20"
      >
        <ArrowLeft className="size-3.5" />
        <span className="max-sm:hidden">{returning ? "Voltando..." : "Voltar para admin"}</span>
        <span className="sm:hidden">{returning ? "..." : "Voltar"}</span>
      </button>
    </div>
  );
}
