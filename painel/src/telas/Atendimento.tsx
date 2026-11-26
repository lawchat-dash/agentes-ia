import { useCallback, useContext, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, ExternalLink, Headset, RefreshCw } from "lucide-react";
import { enviar } from "../api";
import { Alerta, Carregando } from "../componentes/ui";
import { useSessao } from "../sessao";
import { NomeDoEscritorio } from "../componentes/nomeEscritorio";

/** Pede ao servidor o link de uso único do Login integrado da Helena (o token da conta nunca vem ao navegador). */
export async function linkDaHelena(idLead?: string): Promise<string> {
  const r = await enviar<{ url: string }>("/atendimento/entrar", idLead ? { id_lead: idLead } : {});
  return r.url;
}

/**
 * Abre a Helena já logada numa janela separada. A janela é aberta NO CLIQUE (antes da resposta do servidor),
 * senão o navegador a bloqueia como popup; depois recebe o endereço.
 */
export async function abrirHelenaEmJanela(idLead?: string): Promise<void> {
  const janela = window.open("about:blank", idLead ? `helena-${idLead}` : "helena-atendimento", "width=1280,height=860");
  try {
    const url = await linkDaHelena(idLead);
    if (janela) { janela.opener = null; janela.location.href = url; } else window.location.href = url;
  } catch (e) {
    janela?.close();
    throw e;
  }
}

/**
 * Atendimento: a tela da Helena ocupando toda a área do painel, já logada como o usuário (Login integrado).
 * Só uma barrinha discreta no canto (recarregar / abrir em janela separada). Se a Helena não deixar ser
 * mostrada aqui dentro, "Abrir em janela separada" sempre funciona.
 */
export function TelaAtendimento() {
  const { escritorio } = useSessao();
  const nomeEscritorio = useContext(NomeDoEscritorio);
  const navegar = useNavigate();
  // Volta para onde a pessoa estava no painel; aberto direto pelo link, vai para o Início.
  const voltar = () => { if (window.history.state?.idx > 0) navegar(-1); else navegar("/"); };
  const [url, setUrl] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(true);

  const carregar = useCallback(async () => {
    setCarregando(true); setErro(null); setUrl(null);
    try { setUrl(await linkDaHelena()); } catch (e) { setErro((e as Error).message); } finally { setCarregando(false); }
  }, []);

  useEffect(() => { void carregar(); }, [carregar, escritorio]);

  const abrirFora = () => { abrirHelenaEmJanela().catch((e) => setErro((e as Error).message)); };

  return (
    <div className="flex-1 min-h-0 flex flex-col bg-white h-full">
      <div className="flex items-center justify-between gap-3 px-3 h-11 shrink-0 border-b border-[#eef1f5] bg-[#fafbfc]">
        <div className="flex items-center gap-3 min-w-0">
          <button type="button" className="btn sm" onClick={voltar}><ArrowLeft size={15} /> Voltar ao painel</button>
          <span className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-[#101828] truncate">
            <Headset size={15} className="text-[#00bc33] shrink-0" /> Central de Atendimento
            {nomeEscritorio && <span className="font-normal text-[#667085] truncate">· {nomeEscritorio}</span>}
          </span>
        </div>
        <span className="flex gap-1 shrink-0">
          <button type="button" className="btn ghost sm" onClick={() => void carregar()} title="Recarregar o atendimento" disabled={carregando}><RefreshCw size={14} /></button>
          <button type="button" className="btn ghost sm" onClick={abrirFora} title="Use se a tela ficar em branco ou pedir login"><ExternalLink size={14} /> Janela separada</button>
        </span>
      </div>
      {url && (
        <iframe title="Atendimento na Helena" src={url} className="flex-1 w-full min-h-0 border-0"
          allow="clipboard-read; clipboard-write; microphone; camera" referrerPolicy="no-referrer" />
      )}
      {carregando && <div className="flex-1 grid place-items-center"><Carregando /></div>}
      {erro && (
        <div className="flex-1 grid place-items-center p-6">
          <div style={{ maxWidth: 520 }}>
            <Alerta tipo="bad" titulo="Não deu para abrir o atendimento">{erro}</Alerta>
            <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
              <button type="button" className="btn" onClick={() => void carregar()}><RefreshCw size={15} /> Tentar de novo</button>
              <button type="button" className="btn pri" onClick={abrirFora}><ExternalLink size={15} /> Abrir em janela separada</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
