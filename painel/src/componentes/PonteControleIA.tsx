import { useEffect, useMemo } from "react";
import { Bot } from "lucide-react";
import { MENSAGEM_CONVERSA, PainelDoLead, useLeadIA, type Alvo } from "./ControleIA";
import "./controleIA.css";

/**
 * Página-ponte do app "Controle da IA" cadastrado na plataforma de atendimento:
 *   /controle-ia/ponte?id_da_conta=...&id_do_atendimento=...&id_do_contato=...&telefone_do_contato=...
 *
 * A plataforma abre esta página num iframe ao lado da conversa (e a plataforma, por sua vez, está dentro do painel).
 * Ela avisa o painel (window.top, só na origem do próprio painel) qual conversa está aberta: a bolinha da Central troca
 * o lead na hora. Aberta sozinha (ou com a plataforma fora do painel), mostra o próprio mini controle.
 */
function lerAlvo(): Alvo {
  const q = new URLSearchParams(window.location.search);
  const v = (nome: string) => (q.get(nome) || "").trim().slice(0, 80) || undefined;
  return { sessao: v("id_do_atendimento"), contato: v("id_do_contato"), telefone: v("telefone_do_contato"), conta: v("id_da_conta") };
}

/** O topo é o próprio painel (mesma origem)? Ler a origem de outro domínio lança erro. */
function dentroDoPainel(): boolean {
  try { return window.top !== window.self && window.top?.location.origin === window.location.origin; } catch { return false; }
}

export default function PonteControleIA() {
  const alvo = useMemo(lerAlvo, []);
  const temAlvo = Boolean(alvo.sessao || alvo.contato || alvo.telefone);
  const noPainel = useMemo(dentroDoPainel, []);

  useEffect(() => {
    document.title = "Controle da IA · LawChat";
    if (!temAlvo || window.top === window.self) return;
    const avisar = () => {
      try { window.top?.postMessage({ tipo: MENSAGEM_CONVERSA, ...alvo }, window.location.origin); } catch { /* topo de outro domínio: a mensagem não sai */ }
    };
    avisar();
    // De novo em seguida: o painel pode estar terminando de montar a bolinha quando a conversa abre.
    const t1 = window.setTimeout(avisar, 1200);
    const t2 = window.setTimeout(avisar, 4000);
    return () => { window.clearTimeout(t1); window.clearTimeout(t2); };
  }, [alvo, temAlvo]);

  return (
    <div className="cia-ponte">
      <div className="cia-ponte-cartao">
        <header><Bot size={16} /> Controle da IA</header>
        {noPainel ? (
          <div className="cia-ponte-conectada"><i aria-hidden /> Conectado. Use a bolinha da IA na Central para ligar ou desligar.</div>
        ) : (
          <MiniControle alvo={temAlvo ? alvo : null} />
        )}
      </div>
    </div>
  );
}

function MiniControle({ alvo }: { alvo: Alvo | null }) {
  const ctl = useLeadIA(alvo, true);
  const semLogin = /entre de novo|usuário desativado/i.test(ctl.erro || "");
  return (
    <div className="cia-corpo">
      {semLogin ? (
        <>
          <p className="cia-dica">Entre no painel da LawChat neste navegador para controlar a IA desta conversa.</p>
          <a className="cia-btn sucesso" href="/" target="_blank" rel="noopener">Abrir o painel</a>
        </>
      ) : (
        <PainelDoLead ctl={ctl} alvo={alvo} />
      )}
    </div>
  );
}
