import { useState } from "react";
import { CheckCircle2, Copy, KeyRound, Link2, PlugZap, RefreshCw, Save } from "lucide-react";
import { api, enviar, formatarTelefone, quando, type Canal } from "../api";
import { Alerta, Cabecalho, Carregando, Painel, Situacao, Vazio, useAcao, useCarregar } from "../componentes/ui";
import { useSessao } from "../sessao";
import { IntegracaoZapSign } from "./IntegracaoZapSign";

interface Integracao { situacao: string; final_segredo: string | null; config: Record<string, any>; erro: string | null; testado_em: string | null; tem_segredo: boolean; }
interface Dados { integracoes: Record<string, Integracao>; canais: Canal[]; url_webhook_configurada: boolean; url_webhook_zapsign: string | null; url_botao_ia: string | null; }
interface PainelCrm { id: string; titulo: string; tipo: string; etapas: { id: string; titulo: string }[] }

export function TelaIntegracoes() {
  const { escritorio } = useSessao();
  const { dados, erro, recarregar } = useCarregar<Dados>("/integracoes", [escritorio]);
  if (!dados) return <Carregando erro={erro} />;
  const helena = dados.integracoes.helena;
  return (
    <>
      <Cabecalho eyebrow="Configurar" titulo="Integrações" texto="Conexão com o WhatsApp e o CRM da LawChat, e a ZapSign para os contratos. O consumo da IA sai dos Créditos do escritório." />
      <div className="stack">
        <IntegracaoHelena integracao={helena} canais={dados.canais} webhookPossivel={dados.url_webhook_configurada} aoMudar={recarregar} />
        {helena?.situacao === "ok" && <IntegracaoCrm integracao={dados.integracoes.crm} aoMudar={recarregar} />}
        {helena?.situacao === "ok" && <DesligarIa url={dados.url_botao_ia} />}
        <IntegracaoZapSign integracao={dados.integracoes.zapsign} urlWebhook={dados.url_webhook_zapsign} aoMudar={recarregar} />
      </div>
    </>
  );
}

function IntegracaoHelena({ integracao, canais, webhookPossivel, aoMudar }: { integracao?: Integracao; canais: Canal[]; webhookPossivel: boolean; aoMudar: () => void }) {
  const { ocupado, executar } = useAcao();
  const [token, setToken] = useState("");
  const conectada = integracao?.situacao === "ok";
  const webhook = Boolean(integracao?.config?.webhook_conectado);

  return (
    <Painel titulo={<h3 style={{ display: "flex", gap: 8, alignItems: "center" }}><PlugZap className="i" />LawChat <Situacao valor={integracao?.situacao ?? "pendente"} /></h3>}>
      <div className="form">
        <div className="grid2">
          <div className="field">
            <label htmlFor="token-helena">Token da conta na LawChat</label>
            <div style={{ display: "flex", gap: 8 }}>
              <input id="token-helena" type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)}
                placeholder={integracao?.final_segredo ? `Salvo, termina em ${integracao.final_segredo}` : "Cole o token aqui"} />
              <button className="btn pri" disabled={ocupado || token.trim().length < 10}
                onClick={() => executar(async () => { await enviar("/integracoes/helena", { token: token.trim() }, "PUT"); setToken(""); aoMudar(); }, "Token salvo e testado.")}><KeyRound />Salvar</button>
            </div>
            <span className="ajuda">Na LawChat: Ajustes › Integrações › Integração via API. O token fica no cofre do servidor; aqui só aparece o final.</span>
            {integracao?.erro && <Alerta tipo="bad">{integracao.erro}</Alerta>}
          </div>
          <div className="field">
            <span className="lbl">Recebimento de mensagens (webhook)</span>
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              {webhook ? <span className="chip ok"><CheckCircle2 size={12} />conectado</span> : <span className="chip warn">não conectado</span>}
              <button className="btn" disabled={ocupado || !conectada || !webhookPossivel}
                onClick={() => executar(async () => { const r = await api<{ assinatura: { acao: string } }>("/integracoes/helena/conectar", { metodo: "POST" }); aoMudar(); return r; },
                  "Webhook da LawChat conferido.")}><Link2 />{webhook ? "Conferir webhook" : "Conectar webhook"}</button>
            </div>
            <span className="ajuda">O sistema cria a assinatura na LawChat sozinho, com eventos de mensagem recebida e enviada.</span>
            {!webhookPossivel && <Alerta tipo="warn">O servidor ainda não tem endereço público configurado. A equipe LawChat precisa definir AGENTESIA_URL_PUBLICA.</Alerta>}
          </div>
        </div>

        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
            <span className="lbl">Números encontrados na LawChat</span>
            <button className="btn sm" style={{ marginLeft: "auto" }} disabled={ocupado || !conectada}
              onClick={() => executar(async () => { await api("/integracoes/helena/canais", { metodo: "POST" }); aoMudar(); }, "Números atualizados.")}><RefreshCw />Atualizar da LawChat</button>
          </div>
          {canais.length === 0 ? <Vazio>Nenhum número ainda. Salve o token para buscar.</Vazio> : (
            <div className="lst"><table>
              <thead><tr><th>Número</th><th>Tipo</th><th>Canal na LawChat</th><th>Agente</th><th>Situação</th></tr></thead>
              <tbody>{canais.map((c) => (
                <tr key={c.id}>
                  <td className="mono">{formatarTelefone(c.numero_normalizado)}</td>
                  <td><span className={`chip ${c.tipo === "oficial" ? "info" : ""}`}>{c.tipo === "oficial" ? "API oficial" : "não oficial"}</span></td>
                  <td className="s mono">{c.id_canal_helena}</td>
                  <td>{c.nome_agente ?? <span className="muted">livre</span>}</td>
                  <td><Situacao valor={c.ativo ? "ativo" : "encerrado"} texto={c.ativo ? "ativo" : "desligado na LawChat"} /></td>
                </tr>
              ))}</tbody>
            </table></div>
          )}
        </div>
        {integracao?.testado_em && <span className="muted" style={{ fontSize: 12 }}>Última conferência: {quando(integracao.testado_em)}</span>}
      </div>
    </Painel>
  );
}

function DesligarIa({ url }: { url: string | null }) {
  const exemplo = '{ "acao": "desligar", "sessionId": "{{session.id}}" }';
  return (
    <Painel titulo="Desligar a IA pela LawChat">
      <div className="form">
        <p className="sec" style={{ margin: 0 }}>A equipe pode tirar a IA de uma conversa sem sair da LawChat. Cada vez fica uma nota no atendimento com um código (DES-…) e o follow-up da conversa é cancelado.</p>
        <div className="grid2">
          <div className="field">
            <span className="lbl">1. Pela etiqueta</span>
            <span>Coloque a etiqueta <b>🤖 IA Desativada</b> no contato para desligar. Tire a etiqueta para religar.</span>
            <span className="ajuda">Funciona depois de conectar o webhook acima (o evento de etiqueta já vai junto).</span>
          </div>
          <div className="field">
            <span className="lbl">2. Por botão ou automação</span>
            {url ? <div style={{ display: "flex", gap: 8 }}>
              <input className="inp mono" readOnly value={url} aria-label="Endereço do botão da IA" style={{ fontSize: 11.5 }} />
              <button className="btn" onClick={() => { navigator.clipboard?.writeText(url); }} aria-label="Copiar endereço"><Copy /></button>
            </div> : <Alerta tipo="warn">O servidor ainda não tem endereço público.</Alerta>}
            <span className="ajuda">Requisição POST com o corpo <code className="mono">{exemplo}</code>. Use "ligar" para religar. Também aceita "phone" no lugar de "sessionId".</span>
          </div>
        </div>
      </div>
    </Painel>
  );
}

function IntegracaoCrm({ integracao, aoMudar }: { integracao?: Integracao; aoMudar: () => void }) {
  const { ocupado, executar } = useAcao();
  const [paineis, setPaineis] = useState<PainelCrm[] | null>(null);
  const [escolhido, setEscolhido] = useState<string>(integracao?.config?.id_painel ?? "");
  const carregar = () => executar(async () => { const r = await api<{ paineis: PainelCrm[] }>("/integracoes/helena/paineis"); setPaineis(r.paineis); });
  const painel = paineis?.find((p) => p.id === escolhido);

  return (
    <Painel titulo="CRM da LawChat" acoes={<button className="btn sm" onClick={carregar} disabled={ocupado}><RefreshCw />Ler painéis</button>}>
      <div className="form">
        <p className="sec" style={{ margin: 0 }}>Escolha o painel onde os leads da IA aparecem. Quais colunas usar em cada etapa você define em cada agente, na aba "Funções e automações".</p>
        {integracao?.config?.titulo_painel && !paineis && <div><span className="lbl">Painel em uso: </span>{integracao.config.titulo_painel}</div>}
        {paineis && (
          <label className="field"><span className="lbl">Painel</span>
            <select value={escolhido} onChange={(e) => setEscolhido(e.target.value)}>
              <option value="">Escolher…</option>
              {paineis.map((p) => <option key={p.id} value={p.id}>{p.titulo}</option>)}
            </select>
            {painel && <span className="ajuda">Colunas: {painel.etapas.map((e) => e.titulo).join(" → ")}</span>}
          </label>
        )}
        {paineis && <button className="btn pri" style={{ alignSelf: "flex-start" }} disabled={ocupado || !escolhido}
          onClick={() => executar(async () => { await enviar("/integracoes/crm", { id_painel: escolhido, titulo_painel: painel?.titulo }, "PUT"); setPaineis(null); aoMudar(); }, "Painel do CRM salvo.")}><Save />Usar este painel</button>}
      </div>
    </Painel>
  );
}
