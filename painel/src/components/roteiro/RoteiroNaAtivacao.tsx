// O roteiro de gravação dentro da ativação/edição do produto (Passo 3 › Conteúdo):
// - useRoteiroDoProduto: as partes do roteiro e o que o escritório já gravou;
// - sugestoesDeMidia: para cada marcador [[audio:x]] ainda no prompt, a gravação do roteiro que o preenche;
// - CardRoteiroAtivacao: card da lateral "Roteiro de gravação · faltam X" com "Gravar o roteiro".
import { useEffect, useState } from "react";
import { Clapperboard, Mic, Video } from "lucide-react";
import { api } from "@/api";
import { normalizarMarcador, type GravacaoParte, type RoteiroDoProduto } from "./tipos";

export function useRoteiroDoProduto(idProduto: string | null | undefined, ligado: boolean) {
  const [dados, setDados] = useState<RoteiroDoProduto | null>(null);
  useEffect(() => {
    if (!ligado || !idProduto) { setDados(null); return; }
    let vivo = true;
    api<RoteiroDoProduto>(`/roteiro-gravacao/${idProduto}`)
      .then((r) => { if (vivo) setDados(r); })
      .catch(() => { if (vivo) setDados(null); });           // sem roteiro (ou sem a migração): o card não aparece
    return () => { vivo = false; };
  }, [idProduto, ligado]);
  return dados;
}

export interface SugestaoDeMidia { marcador: string; titulo: string; gravacao: GravacaoParte }

/** Marcadores do prompt ("audio:Honorários") → a gravação da parte do roteiro com o mesmo nome. */
export function sugestoesDeMidia(marcadores: string[], roteiro: RoteiroDoProduto | null): Record<string, SugestaoDeMidia> {
  const saida: Record<string, SugestaoDeMidia> = {};
  if (!roteiro) return saida;
  const porNome = new Map(roteiro.partes.filter((p) => p.marcador && p.gravacao).map((p) => [normalizarMarcador(p.marcador!), p]));
  for (const mk of marcadores) {
    const nome = mk.includes(":") ? mk.slice(mk.indexOf(":") + 1) : mk;
    const parte = porNome.get(normalizarMarcador(nome));
    if (parte?.gravacao) saida[mk] = { marcador: mk, titulo: parte.titulo, gravacao: parte.gravacao };
  }
  return saida;
}

export function CardRoteiroAtivacao({ roteiro, aoGravar }: { roteiro: RoteiroDoProduto; aoGravar: () => void }) {
  if (!roteiro.total) return null;
  const tudo = roteiro.gravadas >= roteiro.total;
  return (
    <div className="mt-2 rounded-xl p-3" style={{ border: "1px solid #d9f2df", backgroundImage: "linear-gradient(135deg, #f3fcf5, #fbfffc)" }}>
      <div className="flex items-center gap-2">
        <div className="size-7 rounded-lg grid place-items-center shrink-0 shadow-sm" style={{ backgroundImage: "linear-gradient(135deg, #34e06b, #00852a)", color: "#fff" }}>
          <Clapperboard className="size-4" />
        </div>
        <span className="text-sm font-bold flex-1 min-w-0 truncate text-[#101828]">Roteiro de gravação</span>
        <span className="text-[10px] font-bold rounded-full px-1.5 py-0.5 bg-[#e6f5eb] text-[#0b5e27] shrink-0">{roteiro.gravadas}/{roteiro.total}</span>
      </div>
      <div className="mt-2 h-1.5 rounded-full bg-[#e4eae6] overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${(roteiro.gravadas / roteiro.total) * 100}%`, background: "linear-gradient(90deg,#00bc33,#34e06b)" }} />
      </div>
      <p className="text-[10.5px] mt-1.5 leading-snug text-[#3d6b4b]">
        {tudo ? "Tudo gravado. As gravações aparecem na Edição rápida de mídias para confirmar."
          : <>Faltam {roteiro.faltam_audios > 0 && <><Mic className="inline size-3 -mt-0.5" /> {roteiro.faltam_audios} áudio{roteiro.faltam_audios > 1 ? "s" : ""}</>}
              {roteiro.faltam_audios > 0 && roteiro.faltam_videos > 0 && " e "}
              {roteiro.faltam_videos > 0 && <><Video className="inline size-3 -mt-0.5" /> {roteiro.faltam_videos} vídeo{roteiro.faltam_videos > 1 ? "s" : ""}</>}.</>}
      </p>
      <button type="button" onClick={aoGravar}
        className="mt-2 w-full h-8 rounded-lg text-[12.5px] font-semibold text-white transition-transform active:scale-[.98]"
        style={{ background: "linear-gradient(135deg,#12c94a,#00852a)", boxShadow: "0 6px 14px -8px rgba(0,163,44,.7)" }}>
        {tudo ? "Ver o roteiro" : roteiro.gravadas ? "Continuar gravando" : "Gravar o roteiro agora"}
      </button>
    </div>
  );
}
