import { useState } from "react";
import { Copy, FileSignature, KeyRound, RefreshCw, Save } from "lucide-react";
import { api, enviar } from "../api";
import { Alerta, Painel, Situacao, useAcao } from "../componentes/ui";

interface Ligacao { variavel: string; campo: string; valor?: string }
interface ModeloContrato { id_modelo: string; nome: string; padrao: boolean; mapeamento: Ligacao[]; obrigatorios?: string[]; id_agente?: string | null; id_ativado?: string | null }
interface Integracao { situacao: string; final_segredo: string | null; config: Record<string, any>; erro: string | null }
interface Leitura { modelos: { id: string; nome: string }[]; variaveis?: string[]; campos: Record<string, string>; mapeamento_padrao: Ligacao[] }

const MENSAGENS: [string, string][] = [
  ["link", "Link do contrato (use {link})"], ["nova_versao", "Contrato atualizado (use {link})"],
  ["pos_assinatura", "Depois que o lead assina"], ["lembrete", "Lembrete de assinatura (use {link})"],
  ["equipe_envia", "Quando a ZapSign recusa (a equipe envia)"],
];

/** Contrato na ZapSign: token no cofre, modelo, ligação das variáveis com os dados do lead e o que acontece depois. */
export function IntegracaoZapSign({ integracao, urlWebhook, aoMudar }: { integracao?: Integracao; urlWebhook: string | null; aoMudar: () => void }) {
  const { ocupado, executar } = useAcao();
  const config = integracao?.config ?? {};
  const [token, setToken] = useState("");
  const [ambiente, setAmbiente] = useState<string>(config.ambiente ?? "producao");
  const [leitura, setLeitura] = useState<Leitura | null>(null);
  // Esta tela cuida do modelo GERAL (padrão do escritório). Os modelos de cada produto são salvos na
  // tela do produto e o servidor os mantém quando esta tela salva (PUT /integracoes/zapsign/config).
  const doProduto = (m: ModeloContrato) => !!(m.id_ativado || m.id_agente);
  const gerais: ModeloContrato[] = (config.modelos ?? []).filter((m: ModeloContrato) => !doProduto(m));
  const deProdutos = (config.modelos ?? []).length - gerais.length;
  const atual: ModeloContrato | undefined = gerais.find((m) => m.padrao) ?? gerais[0];
  // Sem modelo geral, o padrão que vale (para o agente sem modelo próprio) é o de um produto.
  const padraoDeProduto: ModeloContrato | undefined = gerais.length ? undefined : (config.modelos ?? []).find((m: ModeloContrato) => m.padrao && doProduto(m));
  const [modelo, setModelo] = useState<ModeloContrato | null>(atual ?? null);
  const [limite, setLimite] = useState<number>(config.limite_versoes ?? 3);
  const [lembretes, setLembretes] = useState<string>(((config.lembretes?.horas ?? [2, 24, 72]) as number[]).join(", "));
  const [lembretesAtivos, setLembretesAtivos] = useState<boolean>(config.lembretes?.ativo ?? true);
  const [video, setVideo] = useState<string>(config.midia_pos_assinatura?.url ?? "");
  const [mensagens, setMensagens] = useState<Record<string, string>>(config.mensagens ?? {});
  const conectada = integracao?.situacao === "ok";

  const ler = (id?: string) => executar(async () => {
    const r = await api<Leitura>(`/integracoes/zapsign/modelos${id ? `?id_modelo=${encodeURIComponent(id)}` : ""}`);
    setLeitura(r);
    if (id && r.variaveis) {
      // Liga sozinho as variáveis com o mesmo nome do modelo padrão da LawChat.
      const padrao = new Map(r.mapeamento_padrao.map((m) => [m.variavel.toLowerCase(), m.campo]));
      const antigas = new Map((modelo?.id_modelo === id ? modelo.mapeamento : []).map((m) => [m.variavel, m]));
      setModelo({ id_modelo: id, nome: r.modelos.find((m) => m.id === id)?.nome ?? id, padrao: true,
        mapeamento: r.variaveis.map((v) => antigas.get(v) ?? { variavel: v, campo: padrao.get(v.toLowerCase()) ?? "" }) });
    }
  });
  const mudarLigacao = (i: number, p: Partial<Ligacao>) => modelo && setModelo({ ...modelo, mapeamento: modelo.mapeamento.map((l, j) => (j === i ? { ...l, ...p } : l)) });
  const semLigacao = (modelo?.mapeamento ?? []).filter((l) => !l.campo).length;
  const campos = leitura?.campos ?? {};

  return (
    <Painel titulo={<h3 style={{ display: "flex", gap: 8, alignItems: "center" }}><FileSignature className="i" />ZapSign (contrato) <Situacao valor={integracao?.situacao ?? "pendente"} /></h3>}>
      <div className="form">
        <div className="grid2">
          <div className="field">
            <label htmlFor="token-zapsign">Token da API da ZapSign</label>
            <div style={{ display: "flex", gap: 8 }}>
              <input id="token-zapsign" type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)}
                placeholder={integracao?.final_segredo ? `Salvo, termina em ${integracao.final_segredo}` : "Cole o token"} />
              <select className="inp" aria-label="Ambiente da ZapSign" value={ambiente} onChange={(e) => setAmbiente(e.target.value)} style={{ maxWidth: 130 }}>
                <option value="producao">Produção</option><option value="sandbox">Teste (sandbox)</option>
              </select>
              <button className="btn pri" disabled={ocupado || token.trim().length < 8}
                onClick={() => executar(async () => { await enviar("/integracoes/zapsign", { token: token.trim(), ambiente }, "PUT"); setToken(""); aoMudar(); }, "Token salvo e testado.")}><KeyRound />Salvar</button>
            </div>
            <span className="ajuda">Na ZapSign: Configurações › Integração › Token da API. Fica no cofre; aqui só o final.</span>
            {integracao?.erro && <Alerta tipo="bad">{integracao.erro}</Alerta>}
          </div>
          <div className="field">
            <span className="lbl">Aviso de assinatura (webhook)</span>
            {urlWebhook ? <div style={{ display: "flex", gap: 8 }}>
              <input className="inp mono" readOnly value={urlWebhook} aria-label="Endereço do webhook da ZapSign" style={{ fontSize: 11.5 }} />
              <button className="btn" onClick={() => { navigator.clipboard?.writeText(urlWebhook); }} aria-label="Copiar endereço"><Copy /></button>
            </div> : <Alerta tipo="warn">O servidor ainda não tem endereço público.</Alerta>}
            <span className="ajuda">Cole na ZapSign em Configurações › Webhooks, evento "documento assinado". Mesmo sem ele, o sistema confere quando o lead diz que assinou e nos lembretes.</span>
          </div>
        </div>

        {conectada && <>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <span className="lbl">Modelo de contrato:</span>
            {leitura ? (
              <select className="inp" aria-label="Modelo de contrato" style={{ maxWidth: 320 }} value={modelo?.id_modelo ?? ""} onChange={(e) => e.target.value && ler(e.target.value)}>
                <option value="">Escolher…</option>
                {leitura.modelos.map((m) => <option key={m.id} value={m.id}>{m.nome}</option>)}
              </select>
            ) : <b>{modelo?.nome ?? "nenhum"}</b>}
            <button className="btn sm" disabled={ocupado} onClick={() => ler(modelo?.id_modelo)}><RefreshCw />Ler modelos da ZapSign</button>
          </div>
          <p className="muted" style={{ margin: 0, fontSize: 12.5 }}>
            Este é o modelo padrão do escritório: vale para o agente que não tem modelo próprio.
            {deProdutos > 0 && ` ${deProdutos} produto(s) têm modelo próprio, escolhido na tela do produto; salvar aqui não muda esses.`}
            {padraoDeProduto && ` Ainda não há modelo geral: hoje o padrão é "${padraoDeProduto.nome}", escolhido na tela de um produto. Salvar um modelo aqui o substitui como padrão.`}
          </p>

          {modelo && (
            <div>
              <span className="lbl">Ligação das variáveis do modelo com os dados do lead</span>
              {!leitura && <p className="muted" style={{ fontSize: 12.5 }}>Use "Ler modelos da ZapSign" para editar.</p>}
              <div className="lst" style={{ marginTop: 6 }}><table>
                <thead><tr><th>Variável no modelo</th><th>Preencher com</th></tr></thead>
                <tbody>{modelo.mapeamento.map((l, i) => (
                  <tr key={l.variavel + i}>
                    <td className="mono">{l.variavel}</td>
                    <td>{leitura ? <div style={{ display: "flex", gap: 6 }}>
                      <select className="inp" aria-label={`Campo para ${l.variavel}`} value={l.campo} onChange={(e) => mudarLigacao(i, { campo: e.target.value })}>
                        <option value="">(em branco)</option>
                        {Object.entries(campos).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                      </select>
                      {l.campo === "@fixo" && <input className="inp" aria-label="Texto fixo" value={l.valor ?? ""} onChange={(e) => mudarLigacao(i, { valor: e.target.value })} />}
                    </div> : (campos[l.campo] ?? l.campo ?? "(em branco)")}</td>
                  </tr>
                ))}</tbody>
              </table></div>
              {semLigacao > 0 && <Alerta tipo="warn">{semLigacao} variável(is) sem ligação vão em branco no contrato.</Alerta>}
            </div>
          )}

          <div className="form cols">
            <label className="field"><span className="lbl">Máximo de versões por lead</span>
              <input type="number" min={1} max={10} value={limite} onChange={(e) => setLimite(Number(e.target.value))} />
              <span className="ajuda">Depois disso, alteração no contrato fica com a equipe.</span></label>
            <label className="field"><span className="lbl">Lembretes de assinatura (horas depois do envio)</span>
              <input value={lembretes} onChange={(e) => setLembretes(e.target.value)} placeholder="2, 24, 72" disabled={!lembretesAtivos} />
              <span className="ajuda"><label className="check"><input type="checkbox" checked={lembretesAtivos} onChange={(e) => setLembretesAtivos(e.target.checked)} />Lembrar quem não assinou</label></span></label>
          </div>
          <label className="field"><span className="lbl">Vídeo depois da assinatura (opcional, link https)</span>
            <input value={video} onChange={(e) => setVideo(e.target.value)} placeholder="https://…/boas-vindas.mp4" /></label>
          <details>
            <summary className="lbl" style={{ cursor: "pointer" }}>Mensagens ao lead (vazio = texto padrão)</summary>
            <div className="form" style={{ marginTop: 8 }}>
              {MENSAGENS.map(([chave, rotulo]) => (
                <label key={chave} className="field"><span className="lbl">{rotulo}</span>
                  <textarea rows={chave === "pos_assinatura" ? 4 : 2} value={mensagens[chave] ?? ""} onChange={(e) => setMensagens({ ...mensagens, [chave]: e.target.value })} /></label>
              ))}
            </div>
          </details>
          <button className="btn pri" style={{ alignSelf: "flex-start" }} disabled={ocupado || !modelo}
            onClick={() => executar(async () => {
              await enviar("/integracoes/zapsign/config", {
                // O modelo desta tela é o padrão do escritório.
                modelos: modelo ? [{ ...modelo, padrao: true }] : [], limite_versoes: limite, mensagens,
                lembretes: { ativo: lembretesAtivos, horas: lembretes.split(/[,; ]+/).map(Number).filter((n) => n > 0) },
                midia_pos_assinatura: { url: video.trim() || null },
              }, "PUT");
              aoMudar();
            }, "Configuração do contrato salva.")}><Save />Salvar configuração do contrato</button>
          <p className="muted" style={{ margin: 0, fontSize: 12.5 }}>Depois, ligue "Gerar contrato na ZapSign" no agente. A IA pede os dados, confirma com o lead e o sistema gera, manda o link, lembra e confere a assinatura.</p>
        </>}
      </div>
    </Painel>
  );
}
