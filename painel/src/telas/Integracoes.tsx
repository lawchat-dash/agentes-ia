import { useState } from "react";
import BotaoBrilho from "@/components/reactbits/BotaoBrilho";
import { CheckCircle2, Copy, KeyRound, Link2, PlugZap, RefreshCw, Save } from "lucide-react";
import { api, enviar, formatarTelefone, quando, type Canal } from "../api";
import { Alerta, Cabecalho, Carregando, Painel, Situacao, Vazio, useAcao, useCarregar } from "../componentes/ui";
import { useSessao } from "../sessao";
import { IntegracaoZapSign } from "./IntegracaoZapSign";
import { SeloSaude, TestarConexao, TipoNumero, useSaudeNumeros, type SaudeCanal } from "../componentes/SaudeNumero";

interface Integracao { situacao: string; final_segredo: string | null; config: Record<string, any>; erro: string | null; testado_em: string | null; tem_segredo: boolean; }
interface Dados { integracoes: Record<string, Integracao>; canais: Canal[]; url_webhook_configurada: boolean; url_webhook_zapsign: string | null; url_botao_ia: string | null; segredo_controle_ia?: string | null; }
interface PainelCrm { id: string; titulo: string; tipo: string; etapas: { id: string; titulo: string }[] }

export function TelaIntegracoes() {
  const { escritorio } = useSessao();
  const { dados, erro, recarregar } = useCarregar<Dados>("/integracoes", [escritorio]);
  const saude = useSaudeNumeros(escritorio);
  if (!dados) return <Carregando erro={erro} />;
  const helena = dados.integracoes.helena;
  return (
    <>
      <Cabecalho eyebrow="Configurar" titulo="Integrações" texto="Conexão com o WhatsApp e o CRM da LawChat, e a ZapSign para os contratos. O consumo da IA sai dos Créditos do escritório." />
      <div className="stack">
        <IntegracaoHelena integracao={helena} canais={dados.canais} saude={saude.dados?.canais ?? []} webhookPossivel={dados.url_webhook_configurada}
          aoMudar={() => { recarregar(); saude.recarregar(); }} />
        {helena?.situacao === "ok" && <IntegracaoCrm integracao={dados.integracoes.crm} aoMudar={recarregar} />}
        <IntegracaoZapSign integracao={dados.integracoes.zapsign} urlWebhook={dados.url_webhook_zapsign} aoMudar={recarregar} />
      </div>
    </>
  );
}

function IntegracaoHelena({ integracao, canais, saude, webhookPossivel, aoMudar }: { integracao?: Integracao; canais: Canal[]; saude: SaudeCanal[]; webhookPossivel: boolean; aoMudar: () => void }) {
  const saudeDo = new Map(saude.map((c) => [c.id, c]));
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
              <BotaoBrilho size="md" radius={10} disabled={ocupado || token.trim().length < 10}
                onClick={() => executar(async () => { await enviar("/integracoes/helena", { token: token.trim() }, "PUT"); setToken(""); aoMudar(); }, "Token salvo e testado.")}><KeyRound />Salvar</BotaoBrilho>
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
              <thead><tr><th>Número</th><th>Tipo</th><th>Mensagens</th><th>Agente</th><th>Situação</th><th aria-label="Testar conexão" /></tr></thead>
              <tbody>{canais.map((c) => {
                const s = saudeDo.get(c.id);
                return (
                  <tr key={c.id}>
                    <td className="mono">{formatarTelefone(c.numero_normalizado)}<div className="s mono" style={{ fontSize: 10.5 }}>{c.id_canal_helena}</div></td>
                    <td><TipoNumero tipo={c.tipo} aviso={s?.aviso_tipo} /></td>
                    <td>{s ? <SeloSaude selo={s.selo} /> : <span className="muted">—</span>}</td>
                    <td>{c.nome_agente ?? <span className="muted">livre</span>}</td>
                    <td><Situacao valor={c.ativo ? "ativo" : "encerrado"} texto={c.ativo ? "ativo" : "desligado na LawChat"} /></td>
                    <td style={{ textAlign: "right" }}>{conectada && <TestarConexao idCanal={c.id} numero={formatarTelefone(c.numero_normalizado)} />}</td>
                  </tr>
                );
              })}</tbody>
            </table></div>
          )}
          {saude.find((c) => c.aviso_tipo) && <span className="ajuda" style={{ display: "block", marginTop: 6 }}>{saude.find((c) => c.aviso_tipo)!.aviso_tipo}</span>}
        </div>
        {integracao?.testado_em && <span className="muted" style={{ fontSize: 12 }}>Última conferência: {quando(integracao.testado_em)}</span>}
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
        {paineis && <BotaoBrilho size="md" radius={10} style={{ alignSelf: "flex-start" }} disabled={ocupado || !escolhido}
          onClick={() => executar(async () => { await enviar("/integracoes/crm", { id_painel: escolhido, titulo_painel: painel?.titulo }, "PUT"); setPaineis(null); aoMudar(); }, "Painel do CRM salvo.")}><Save />Usar este painel</BotaoBrilho>}
      </div>
    </Painel>
  );
}
