import { useCallback, useContext, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, ExternalLink, Headset, RefreshCw } from "lucide-react";
import { enviar } from "../api";
import { Alerta, Carregando } from "../componentes/ui";
import { useSessao } from "../sessao";
import iconeLawChat from "../assets/lawchat-icone.svg";
import { NomeDoEscritorio, telaDoPainel } from "../componentes/nomeEscritorio";

/** Pede ao servidor o link de uso único do Login integrado da LawChat (o token da conta nunca vem ao navegador). */
export async function linkDaHelena(idLead?: string): Promise<string> {
  const r = await enviar<{ url: string }>("/atendimento/entrar", idLead ? { id_lead: idLead } : {});
  return r.url;
}

/**
 * Abre a LawChat já logada numa janela separada. A janela é aberta NO CLIQUE (antes da resposta do servidor),
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
 * Atendimento: a tela da LawChat ocupando toda a área do painel, já logada como o usuário (Login integrado).
 * Só uma barrinha discreta no canto (recarregar / abrir em janela separada). Se a LawChat não deixar ser
 * mostrada aqui dentro, "Abrir em janela separada" sempre funciona.
 */
export function TelaAtendimento() {
  const { escritorio } = useSessao();
  const nomeEscritorio = useContext(NomeDoEscritorio);
  const navegar = useNavigate();
  // Volta para onde a pessoa estava no painel; aberto direto pelo link, vai para o Início.
  // Vai direto para a última tela do painel (o histórico do navegador inclui os cliques dentro da Central).
  const voltar = () => navegar(telaDoPainel());
  const [url, setUrl] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(true);
  // A tela da LawChat ainda está entrando (login + primeira carga): mostra a tela de carregamento por cima.
  const [entrando, setEntrando] = useState(true);

  const carregar = useCallback(async () => {
    setCarregando(true); setEntrando(true); setErro(null); setUrl(null);
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
          <button type="button" className="btn ghost sm" onClick={() => void carregar()} title="Recarregar a LawChat" disabled={carregando}><RefreshCw size={14} /></button>
          <button type="button" className="btn ghost sm" onClick={abrirFora} title="Use se a tela ficar em branco ou pedir login"><ExternalLink size={14} /> Janela separada</button>
        </span>
      </div>
      {url && (
        // Ficam de fora, cortados: a barra de chat interno da equipe (64px na direita) e a faixa "Ative as notificações
        // na web" (32px no topo; dentro do painel o navegador não deixa ativar notificação, então ela nunca sairia).
        <div className="flex-1 min-h-0 overflow-hidden relative">
          {entrando && <TelaEntrando />}
          <iframe title="Atendimento na LawChat" src={url} className="border-0" style={{ width: "calc(100% + 64px)", height: "calc(100% + 32px)", marginTop: -32 }}
            // O "load" chega antes de a tela de dentro terminar de montar: segura mais um pouco para não piscar branco.
            onLoad={() => window.setTimeout(() => setEntrando(false), 1800)}
            allow="clipboard-read; clipboard-write; microphone; camera" referrerPolicy="no-referrer" />
        </div>
      )}
      {carregando && <div className="flex-1 relative"><TelaEntrando /></div>}
      {erro && (
        <div className="flex-1 grid place-items-center p-6">
          <div style={{ maxWidth: 520 }}>
            <Alerta tipo="bad" titulo="Não deu para abrir a LawChat">{erro}</Alerta>
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

/** Tela de carregamento da Central enquanto o login e a primeira carga acontecem (evita a tela branca). */
function TelaEntrando() {
  return (
    <div className="absolute inset-0 z-10 grid place-items-center bg-white">
      <div className="flex flex-col items-center gap-4 text-center px-6">
        <div className="relative size-14">
          <img src={iconeLawChat} alt="" className="size-14 rounded-2xl" />
          <span className="absolute -inset-1.5 rounded-[20px] border-2 border-[#00bc33]/25 border-t-[#00bc33] animate-spin" />
        </div>
        <div>
          <div className="text-[15px] font-semibold text-[#101828]">Abrindo a Central de Atendimento</div>
          <div className="text-[13px] text-[#667085] mt-1">Entrando na sua conta, só um instante…</div>
        </div>
      </div>
    </div>
  );
}
