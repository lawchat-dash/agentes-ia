import { useState } from "react";
import { Bot, Check, Copy } from "lucide-react";
import { Alerta, Painel } from "./ui";

/**
 * Cartão "Link do Controle da IA" (tela Integrações): o link FIXO que o escritório cadastra na plataforma de
 * atendimento (botão/link dentro da conversa). A plataforma abre o link preenchendo as variáveis da conversa e a página
 * /controle-ia/ponte abre como popup com o controle da IA daquele lead, sem login: o escritório é achado pela conta da
 * plataforma (id_da_conta) e o link só vale com o segredo do escritório (segredo=, vindo de GET /api/integracoes).
 * Backend: app/gestao/rotas_controle_ia.py (rotas /publico).
 */
const VARIAVEIS = "id_da_conta={{id_da_conta}}&id_do_atendimento={{id_do_atendimento}}&id_do_contato={{id_do_contato}}"
  + "&telefone_do_contato={{telefone_do_contato}}&id_do_usuario={{id_do_usuario}}";

/** URL para colar na plataforma (o domínio é o do próprio painel: em produção, https://painel.lawchat.com.br). */
export function urlDoLink(segredo: string): string {
  return `${window.location.origin}/controle-ia/ponte?segredo=${encodeURIComponent(segredo)}&${VARIAVEIS}`;
}

export function LinkControleIA({ segredo }: { segredo: string | null }) {
  const [copiado, setCopiado] = useState(false);
  const url = segredo ? urlDoLink(segredo) : "";
  const copiar = async () => {
    if (!url) return;
    try { await navigator.clipboard.writeText(url); setCopiado(true); window.setTimeout(() => setCopiado(false), 2500); } catch { /* sem área de transferência: dá para selecionar o texto */ }
  };
  return (
    <Painel titulo={<h3 style={{ display: "flex", gap: 8, alignItems: "center" }}><Bot className="i" />Link do Controle da IA</h3>}>
      <div className="form">
        <p className="sec" style={{ margin: 0 }}>
          Um link para a equipe ver e mudar a IA de cada conversa sem sair da plataforma de atendimento. Ao clicar dentro da conversa,
          abre uma janelinha com o status da IA daquele lead e os botões Desativar e Reativar. Cada mudança deixa uma nota no
          atendimento e fica no Histórico como "pelo link da conversa". O link é só deste escritório: não passe para fora da equipe.
        </p>
        {!segredo && <Alerta tipo="warn">O servidor ainda não tem o segredo geral configurado (AGENTESIA_WEBHOOK_SEGREDO). Fale com a equipe LawChat.</Alerta>}
        <div className="field">
          <span className="lbl">Link para cadastrar na plataforma</span>
          <div style={{ display: "flex", gap: 8 }}>
            <input className="inp mono" readOnly value={url} aria-label="Link do Controle da IA" style={{ fontSize: 11.5 }} onFocus={(e) => e.currentTarget.select()} />
            <button className="btn pri" disabled={!url} onClick={() => void copiar()} aria-label="Copiar link">{copiado ? <Check /> : <Copy />}{copiado ? "Copiado" : "Copiar"}</button>
          </div>
        </div>
        <div className="field">
          <span className="lbl">Como usar</span>
          <ol style={{ margin: 0, paddingLeft: 18, lineHeight: 1.6 }}>
            <li>Copie o link acima.</li>
            <li>Na plataforma de atendimento, crie um link/botão (app) dentro da conversa com este endereço, do jeito que está: as partes entre chaves duplas são preenchidas pela própria plataforma.</li>
            <li>Peça para abrir como janela/popup. Pronto: em qualquer conversa, um clique mostra se a IA está ligada e deixa desativar ou reativar.</li>
            <li>Já tinha cadastrado um link antigo (sem "segredo=")? Troque por este: o antigo parou de funcionar.</li>
          </ol>
        </div>
      </div>
    </Painel>
  );
}
