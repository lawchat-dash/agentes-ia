import fotoLawChat from "@/assets/lawchat-perfil.jpg";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, Bot, Building2, CheckCircle2, Clock, ExternalLink, RefreshCw, Search } from "lucide-react";
import { enviar } from "../api";
import { Alerta, Carregando, Modal, Situacao, Vazio, useAcao, useCarregar } from "../componentes/ui";
import { useSessao } from "../sessao";

interface ContaEmpresa { nome?: string | null; razao_social?: string | null; documento?: string | null; documento_formatado?: string | null;
  tipo_pessoa?: string | null; administrador?: string | null; email_contato?: string | null; telefone?: string | null; ativa?: boolean; foto?: string | null;
  endereco?: { city?: string; state?: string } }
interface Linha { id: string; nome: string; situacao: string; ia_desligada: boolean; id_conta_helena: string | null; criado_em: string; agentes: number; agentes_ativos: number; erros_abertos: number; helena: string | null; id_responsavel: string | null; responsavel: string | null;
  gasto_mes_usd: number; limite_consumo: Limite | null; onboarding?: Onboarding | null; sincronizado_em?: string | null;
  conta_helena?: ContaEmpresa | null; sync_helena?: { situacao?: string; erro?: string | null } | null;
  conta_lawchat?: boolean; agente_habilitado?: boolean; webhook?: "synced" | "pending" | "error" }
interface PassoOnboarding { codigo: string; titulo: string; situacao: string; detalhe: string; em?: string }
interface Onboarding { passos?: PassoOnboarding[]; concluido_em?: string | null; atualizado_em?: string }
interface ResultadoOnboarding extends Onboarding { completo?: boolean; paineis?: { id: string; titulo: string; colunas: number }[];
  sincronizado_em?: string | null; obrigatorios?: string[]; dados_helena?: DadosHelena; etapas_por_tipo?: Record<string, string> }
interface DadosHelena { conta?: { razao_social?: string | null; documento?: string | null; documento_formatado?: string | null; tipo_documento?: string | null;
  endereco?: { city?: string; state?: string }; recursos?: { includedAgents?: number; includedSessions?: number } };
  ids?: { id_painel?: string; etapas_por_tipo?: Record<string, string>; id_departamento?: string; id_assinatura?: string; etiquetas?: Record<string, string> } }
interface Sincronizacao { sincronizado_em: string | null; tipos: Record<string, { total: number; novos: number; sumiram: number }>; erros: Record<string, string> }
interface ResultadoSync { total: number; criadas: number; atualizadas: number; com_erro: number; erros: { nome?: string | null; id_conta_helena?: string | null; erro: string }[] }
interface ResultadoHabilitar { habilitado: boolean; passos: PassoOnboarding[] }
const OBRIGATORIOS = ["token", "webhook", "etiquetas", "produto"];
// Números, ZapSign e o painel do CRM são da ativação do agente (lá o sistema sincroniza com a LawChat), não da integração da conta.
const FORA_DA_INTEGRACAO = ["canais", "zapsign", "painel", "painel_padrao"];
const TIPOS_ETAPA = ["SDR", "COMERCIAL", "CONTRATO", "AGUARDANDO_ASSINATURA", "CONTRATO_ASSINADO", "DESQUALIFICADO"];
const NOME_TIPO: Record<string, string> = { canal: "números", painel: "painéis", coluna: "colunas", etiqueta: "etiquetas", equipe: "equipes", usuario: "usuários" };
const SITUACAO_PASSO: Record<string, [string, string]> = {
  ok: ["ok", "ok"], feito: ["ok", "feito agora"], aviso: ["aviso", "atenção"], erro: ["erro", "com erro"],
  pendente: ["pendente", "pendente"], pulado: ["desligada", "não se aplica"],
};
const quando = (iso?: string | null) => (iso ? new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "nunca");
interface Limite { mensal_usd: number | null; ao_estourar: "pausar" | "so_avisar"; avisar_em: number[]; }

/** O dono vende a Helena com a marca LawChat: textos do servidor mostrados nesta tela trocam o nome. */
function marca(texto?: string | null): string {
  return (texto ?? "").replace(/A Helena/g, "O LawChat").replace(/a Helena/g, "o LawChat").replace(/da Helena/g, "do LawChat")
    .replace(/na Helena/g, "no LawChat").replace(/Helena/g, "LawChat");
}

/** "há quanto tempo", como a coluna Última sync do painel antigo. */
function haQuanto(iso?: string | null): string {
  if (!iso) return "nunca";
  const minutos = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutos < 1) return "agora";
  if (minutos < 60) return `${minutos}m`;
  const horas = Math.floor(minutos / 60);
  if (horas < 24) return `${horas}h`;
  return new Date(iso).toLocaleDateString("pt-BR");
}

const SITUACAO_CONTA: Record<string, [string, string]> = { ativo: ["ok", "ativo"], suspenso: ["warn", "suspenso"], encerrado: ["", "encerrado"] };
const WEBHOOK: Record<string, [string, string]> = { synced: ["ok", "synced"], pending: ["warn", "pending"], error: ["bad", "error"] };
type FiltroAgente = "todos" | "habilitado" | "desativado";

export function TelaAdminEscritorios() {
  const { trocarEscritorio, trocarVisao } = useSessao();
  const navegar = useNavigate();
  const { dados, erro, recarregar } = useCarregar<Linha[]>("/admin/escritorios");
  const linhas = dados ?? [];
  const { ocupado: sincronizando, executar } = useAcao();
  const acaoLinha = useAcao();
  const [linhaOcupada, setLinhaOcupada] = useState<string | null>(null);
  const [sync, setSync] = useState<ResultadoSync | null>(null);
  const [busca, setBusca] = useState("");
  const [filtro, setFiltro] = useState<FiltroAgente>("todos");
  const [habilitar, setHabilitar] = useState<Linha | null>(null);
  const [passos, setPassos] = useState<Linha | null>(null);

  const entrar = (id: string) => { trocarEscritorio(id); trocarVisao("lawchat"); navegar("/"); };

  const filtradas = useMemo(() => {
    const b = busca.trim().toLowerCase();
    return linhas.filter((l) => {
      if (filtro === "habilitado" && !l.agente_habilitado) return false;
      if (filtro === "desativado" && l.agente_habilitado) return false;
      if (!b) return true;
      const c = l.conta_helena ?? {};
      return [l.nome, c.razao_social, c.documento, c.documento_formatado, c.email_contato]
        .some((v) => v && String(v).toLowerCase().includes(b));
    });
  }, [linhas, busca, filtro]);

  const status = useMemo(() => {
    const erros = linhas.filter((l) => l.webhook === "error").length;
    const pendentes = linhas.filter((l) => l.webhook === "pending").length;
    if (erros) return { cor: "var(--bad)", Icone: AlertTriangle, texto: `Erro de comunicação (${erros})` };
    if (pendentes) return { cor: "var(--warn)", Icone: Clock, texto: `Pendentes (${pendentes})` };
    return { cor: "var(--ok)", Icone: CheckCircle2, texto: linhas.length ? "Sincronizado" : "Nenhuma conta ainda" };
  }, [linhas]);

  const sincronizarTudo = () => executar(async () => {
    const r = await enviar<ResultadoSync>("/admin/escritorios/sincronizar-lawchat", {});
    setSync(r); setBusca(""); setFiltro("todos"); recarregar();
  }, "Sincronização com o LawChat concluída.");

  const sincronizarUma = (l: Linha) => {
    setLinhaOcupada(l.id);
    void acaoLinha.executar(async () => {
      await enviar(`/admin/escritorios/${l.id}/sincronizar-lawchat`, {});
      recarregar();
    }, `${l.nome} atualizada.`).finally(() => setLinhaOcupada(null));
  };

  const total = linhas.length;
  return (
    <>
      <div className="panel" style={{ padding: "14px 16px", display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 22 }}>
        <status.Icone size={20} style={{ color: status.cor, flex: "none" }} aria-hidden />
        <div>
          <div style={{ fontSize: 14, fontWeight: 600 }}>Status do Webhook</div>
          <div style={{ fontSize: 12, color: status.cor }}>{status.texto}</div>
        </div>
        <span className="sp" style={{ flex: 1 }} />
        <button className="btn" disabled={sincronizando} onClick={sincronizarTudo}>
          <RefreshCw className={sincronizando ? "animate-spin" : ""} />{sincronizando ? "Sincronizando…" : "Sincronizar com LawChat"}
        </button>
      </div>

      {sync && (
        <div style={{ marginBottom: 16 }}>
          <Alerta tipo={sync.com_erro ? "warn" : "ok"} titulo="Sincronização concluída">
            {sync.total} recebidas do LawChat · {sync.criadas} criadas · {sync.atualizadas} atualizadas · {sync.com_erro} com erro
            {sync.erros.length > 0 && (
              <ul style={{ margin: "6px 0 0", paddingLeft: 18, fontSize: 12 }}>
                {sync.erros.map((e, i) => <li key={i}>{e.nome ?? e.id_conta_helena ?? "sem id"}: {e.erro}</li>)}
              </ul>
            )}
          </Alerta>
        </div>
      )}

      <div className="ph" style={{ alignItems: "center" }}>
        <div>
          <h1 style={{ fontStyle: "normal", fontWeight: 700 }}>Contas</h1>
          <p>{filtradas.length === total ? `${total} ${total === 1 ? "conta" : "contas"} no total` : `${filtradas.length} de ${total} contas`}</p>
        </div>
        <div className="act" style={{ alignItems: "center" }}>
          <select className="inp" style={{ width: "auto" }} value={filtro} onChange={(e) => setFiltro(e.target.value as FiltroAgente)} aria-label="Filtrar por Função de agente">
            <option value="todos">Função de agente: todos</option>
            <option value="habilitado">Função de agente: habilitado</option>
            <option value="desativado">Função de agente: desativado</option>
          </select>
          <div style={{ position: "relative" }}>
            <Search size={15} aria-hidden style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "var(--ink-3)" }} />
            <input className="inp" style={{ paddingLeft: 32, width: 280 }} value={busca} onChange={(e) => setBusca(e.target.value)}
              placeholder="Buscar por nome, CNPJ, e-mail…" aria-label="Buscar contas" />
          </div>
          <button className="btn" onClick={recarregar}><RefreshCw />Atualizar</button>
        </div>
      </div>

      {!dados ? <Carregando erro={erro} /> : total === 0 ? (
        <div className="panel"><Vazio icone={<Building2 />}>Nenhuma conta ainda. Clique em <b>Sincronizar com LawChat</b> para puxar as contas.</Vazio></div>
      ) : (
        <div className="lst"><table>
          <thead><tr>
            <th>Nome fantasia / Razão social</th><th>CNPJ</th><th>Situação</th><th>Função de agente</th><th>Webhook</th><th>Última sync</th>
            <th style={{ textAlign: "right" }}>Ações</th>
          </tr></thead>
          <tbody>
            {filtradas.length === 0 && <tr><td colSpan={7} className="muted" style={{ textAlign: "center", padding: 28 }}>Nenhuma conta encontrada.</td></tr>}
            {filtradas.map((l) => {
              const c = l.conta_helena ?? {};
              const [classeSit, textoSit] = SITUACAO_CONTA[l.situacao] ?? ["", l.situacao];
              const [classeWh, textoWh] = WEBHOOK[l.webhook ?? "pending"];
              return (
                <tr key={l.id}>
                  <td style={{ paddingTop: 10, paddingBottom: 10 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <FotoConta nome={l.nome} foto={l.conta_lawchat && !c.foto ? fotoLawChat : c.foto} />
                      <div style={{ minWidth: 0 }}>
                        <div className="t" style={{ whiteSpace: "nowrap" }}>{l.nome}{l.conta_lawchat && <span className="chip ac" style={{ marginLeft: 6 }}>Conta admin LawChat</span>}</div>
                        <div className="s" style={{ whiteSpace: "nowrap" }}>{c.razao_social ?? (l.id_conta_helena ? "—" : "sem conta no LawChat")}</div>
                      </div>
                    </div>
                  </td>
                  <td className="mono" style={{ fontSize: 13, whiteSpace: "nowrap" }}>{c.documento_formatado ?? c.documento ?? "—"}{c.tipo_pessoa && <span className="s" style={{ marginLeft: 6 }}>{c.tipo_pessoa}</span>}</td>
                  <td><span className={`chip ${classeSit}`}><span className="d" />{textoSit}</span></td>
                  <td>
                    {l.agente_habilitado ? (
                        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                          <span className="chip ok"><span className="d" />Habilitado</span>
                          <ResumoOnboarding linha={l} aoAbrir={() => setPassos(l)} />
                        </div>
                      ) : (
                        <button className="btn sm" onClick={() => setHabilitar(l)} disabled={!l.id_conta_helena}
                          title={l.id_conta_helena ? "Habilitar a função de agente (integração inicial)" : "Sincronize com o LawChat antes"}>
                          Desativado
                        </button>
                      )}
                  </td>
                  <td><span className={`chip ${classeWh}`} title={l.sync_helena?.erro ?? undefined}><span className="d" />{textoWh}</span></td>
                  <td className="s" style={{ whiteSpace: "nowrap" }} title={quando(l.sincronizado_em)}>{haQuanto(l.sincronizado_em)}</td>
                  <td style={{ whiteSpace: "nowrap", textAlign: "right" }}>
                    <button className="btn sm ghost" onClick={() => sincronizarUma(l)} disabled={!l.id_conta_helena || linhaOcupada === l.id}
                      title="Sincronizar esta conta com o LawChat" aria-label={`Sincronizar ${l.nome} com o LawChat`}>
                      <RefreshCw className={linhaOcupada === l.id ? "animate-spin" : ""} />
                    </button>
                    <button className="btn sm" onClick={() => entrar(l.id)}><ExternalLink />Acessar</button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table></div>
      )}
      {habilitar && <HabilitarAgente linha={habilitar} aoFechar={() => setHabilitar(null)} aoMudar={recarregar}
        aoVerPassos={() => { setPassos(habilitar); setHabilitar(null); }} />}
      {passos && <PassosDaConta linha={passos} aoFechar={() => { setPassos(null); recarregar(); }} />}
    </>
  );
}

/** Foto da empresa (pictureUrl, só https) num círculo; sem foto ou se ela não carregar, a inicial no verde-claro. */
function FotoConta({ nome, foto }: { nome: string; foto?: string | null }) {
  const [falhou, setFalhou] = useState(false);
  const base = { width: 34, height: 34, borderRadius: "50%", flex: "none" } as const;
  if (foto && (foto.startsWith("https://") || foto.startsWith("/")) && !falhou) {
    return <img src={foto} alt="" aria-hidden referrerPolicy="no-referrer" loading="lazy" onError={() => setFalhou(true)}
      style={{ ...base, objectFit: "cover", background: "var(--surface-2)" }} />;
  }
  return <span aria-hidden style={{ ...base, display: "grid", placeItems: "center", background: "var(--acento-suave)",
    color: "var(--acento-forte)", fontWeight: 700 }}>{(nome || "?").charAt(0).toUpperCase()}</span>;
}

/** Confirmação e resultado do "Função de agente: Habilitar" (integração inicial da conta). */
function HabilitarAgente({ linha, aoFechar, aoMudar, aoVerPassos }: { linha: Linha; aoFechar: () => void; aoMudar: () => void; aoVerPassos: () => void }) {
  const { ocupado, executar } = useAcao();
  const [criarEquipe, setCriarEquipe] = useState(false);
  const [resultado, setResultado] = useState<ResultadoHabilitar | null>(null);
  useEffect(() => { setResultado(null); }, [linha.id]);
  const habilitar = () => executar(async () => {
    setResultado(await enviar<ResultadoHabilitar>(`/admin/escritorios/${linha.id}/habilitar-agente`, { criar_equipe_ia: criarEquipe }));
    aoMudar();
  });
  return (
    <Modal titulo={resultado ? `Função de agente · ${linha.nome}` : "Habilitar a função de agente?"} largura={560} aoFechar={aoFechar}
      texto={resultado ? undefined : <>Libera <b>{linha.nome}</b> para usar o agente de IA. Isto age na conta do cliente no LawChat:
        gera o token "IA LawChat", salva e testa, lê os números, cria as etiquetas padrão que faltam e conecta o webhook.</>}
      rodape={resultado ? <>
        <button className="btn" onClick={aoVerPassos}>Ver passos da integração</button>
        <span className="sp" /><button className="btn pri" onClick={aoFechar}>Fechar</button></> : <>
        <span className="sp" /><button className="btn ghost" onClick={aoFechar} disabled={ocupado}>Cancelar</button>
        <button className="btn pri" onClick={habilitar} disabled={ocupado} data-autofocus="">
          {ocupado ? <RefreshCw className="animate-spin" /> : <Bot />}{ocupado ? "Habilitando…" : "Habilitar"}</button></>}>
      {resultado ? (
        <div className="form">
          <Alerta tipo={resultado.habilitado ? "ok" : "bad"}>
            {resultado.habilitado ? "Função de agente habilitada." : "Não deu para habilitar: o token da conta não ficou de pé. Veja os passos abaixo."}
          </Alerta>
          <div className="lst"><table><tbody>{resultado.passos.filter((p) => !FORA_DA_INTEGRACAO.includes(p.codigo)).map((p) => {
            const [valor, texto] = SITUACAO_PASSO[p.situacao] ?? ["", p.situacao];
            return <tr key={p.codigo}><td className="t">{marca(p.titulo)}</td><td><Situacao valor={valor} texto={texto} /></td><td className="s">{marca(p.detalhe)}</td></tr>;
          })}</tbody></table></div>
          <p className="muted" style={{ margin: 0, fontSize: 12 }}>O painel do CRM e o número entram quando você ativar o primeiro agente (Acessar › Biblioteca).</p>
        </div>
      ) : (
        <label className="check" style={{ fontSize: 13 }}>
          <input type="checkbox" checked={criarEquipe} onChange={(e) => setCriarEquipe(e.target.checked)} />
          Criar também a equipe "🤖 Comercial IA" no LawChat, como equipe PADRÃO da conta
        </label>
      )}
    </Modal>
  );
}

function DadosDaConta({ dados }: { dados?: DadosHelena }) {
  if (!dados || (!dados.conta && !dados.ids)) return null;
  const { conta, ids } = dados;
  const ligados = TIPOS_ETAPA.filter((t) => ids?.etapas_por_tipo?.[t]);
  return (
    <div className="muted" style={{ fontSize: 12, display: "grid", gap: 2 }}>
      {conta && <span>{conta.razao_social ?? "—"} · {conta.tipo_documento ?? "documento"} {conta.documento_formatado ?? conta.documento ?? "—"}
        {conta.endereco?.city ? ` · ${conta.endereco.city}/${conta.endereco.state ?? ""}` : ""}
        {conta.recursos?.includedAgents != null ? ` · ${conta.recursos.includedAgents} usuários no plano` : ""}</span>}
      {ids && <span>Etiquetas padrão: {Object.keys(ids.etiquetas ?? {}).length}/7 · equipe da IA: {ids.id_departamento ? "sim" : "não"} · webhook: {ids.id_assinatura ? "sim" : "não"}</span>}
    </div>
  );
}

interface PassoPainel { passo: string; situacao: string; detalhe: string }
interface EstadoPainel { estado: string; passos: PassoPainel[]; erro?: string | null; ja_tem_painel: boolean; falta_configurar: string[];
  simulacao?: { quando: string; empresa: { id: string; nome: string }; usuario: { id: string; nome: string; email: string } } | null }
interface RespostaPainel { ok: boolean; simulacao?: boolean; estado?: string; parou_em?: string; erro?: string; passos?: PassoPainel[];
  painel?: { titulo: string; etapas: string[] }; divergencias?: string[]; enviado?: boolean; para?: string }
const BLOQUEIOS_PAINEL = ["incerto", "em_andamento", "criado", "divergente"];

/** Ações do painel padrão do CRM: levam o cabeçalho anti-CSRF (X-LawChat-Acao) que o servidor exige. */
async function acaoPainelCrm<T>(caminho: string, corpo?: unknown, metodo = "POST"): Promise<T> {
  const resposta = await fetch(`/api${caminho}`, {
    method: metodo, credentials: "same-origin",
    headers: { Accept: "application/json", "Content-Type": "application/json", "X-LawChat-Acao": "painel-crm" },
    body: corpo === undefined ? undefined : JSON.stringify(corpo),
  });
  const dados = await resposta.json().catch(() => null);
  if (!resposta.ok) {
    const erro = new Error(typeof dados?.detail === "string" ? dados.detail : `Erro ${resposta.status}`) as Error & { status?: number };
    erro.status = resposta.status;
    throw erro;
  }
  return dados as T;
}

function CriarPainelPadrao({ idEscritorio, aoMudar }: { idEscritorio: string; aoMudar: () => void }) {
  const base = `/admin/escritorios/${idEscritorio}/painel-crm`;
  const [estado, setEstado] = useState<EstadoPainel | null>(null);
  const [desligado, setDesligado] = useState(false);
  const [codigo, setCodigo] = useState("");
  const [resposta, setResposta] = useState<RespostaPainel | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const carregar = async () => {
    try { setEstado(await acaoPainelCrm<EstadoPainel>(base, undefined, "GET")); }
    catch (e) { if ((e as { status?: number }).status === 404) setDesligado(true); else setAviso((e as Error).message); }
  };
  useEffect(() => { void carregar(); }, [idEscritorio]);  // eslint-disable-line react-hooks/exhaustive-deps
  const rodar = async (fn: () => Promise<void>) => {
    if (ocupado) return;                                       // uma tentativa por clique, sem repetir sozinho
    setOcupado(true); setAviso(null);
    try { await fn(); } catch (e) { setAviso((e as Error).message); } finally { setOcupado(false); void carregar(); aoMudar(); }
  };
  const pedirCodigo = () => rodar(async () => {
    const r = await acaoPainelCrm<RespostaPainel>(`${base}/codigo`, {});
    setAviso(`Código enviado para ${r.para}. Digite abaixo.`); setCodigo("");
  });
  const simular = () => rodar(async () => {
    setResposta(await acaoPainelCrm<RespostaPainel>(`${base}?simular=true`, { codigo: codigo.trim() })); setCodigo("");
  });
  const criar = () => rodar(async () => {
    const sim = estado?.simulacao;
    if (!window.confirm(`Criar o painel "🤖 CRM COMERCIAL IA" na conta ${sim?.empresa.id ?? ""} (empresa ${sim?.empresa.nome ?? ""}), com o usuário admin ${sim?.usuario.nome ?? ""} (${sim?.usuario.email ?? ""})? Esta ação age dentro da conta do cliente.`)) return;
    setResposta(await acaoPainelCrm<RespostaPainel>(base, { codigo: codigo.trim() })); setCodigo("");
  });
  const conferido = () => rodar(async () => {
    if (!window.confirm("Você conferiu no LawChat se o painel foi criado? Se foi, escolha-o no passo do painel em vez de criar outro.")) return;
    await acaoPainelCrm(`${base}/conferido`, {});
  });
  if (desligado) return <p className="muted" style={{ margin: 0, fontSize: 12 }}>Criar o painel padrão está desligado no servidor (AGENTESIA_PAINEL_CRM_LIGADO). Escolha um painel que já existe.</p>;
  if (!estado) return null;
  const simulacaoValida = Boolean(estado.simulacao && Date.now() - new Date(estado.simulacao.quando).getTime() < 30 * 60 * 1000);
  const passos = resposta?.passos ?? estado.passos ?? [];
  const podeCriar = !estado.ja_tem_painel && !BLOQUEIOS_PAINEL.includes(estado.estado);
  return (
    <div className="panel" style={{ padding: 12, display: "grid", gap: 8 }}>
      <div className="t">Ou criar o painel padrão (🤖 CRM COMERCIAL IA) pela API interna do LawChat</div>
      {estado.falta_configurar.length > 0 && <Alerta tipo="warn">Falta configurar no servidor: {estado.falta_configurar.join(", ")}</Alerta>}
      {estado.ja_tem_painel && <Alerta tipo="info">Este escritório já tem painel gravado: não é possível criar outro.</Alerta>}
      {(estado.estado === "incerto" || estado.estado === "em_andamento") && (
        <Alerta tipo="bad">Resultado {estado.estado === "incerto" ? "incerto" : "em andamento"}: {estado.erro ?? "confira no LawChat"}{" "}
          <button className="btn sm" disabled={ocupado} onClick={conferido}>Marcar como conferido</button></Alerta>
      )}
      {estado.estado === "divergente" && <Alerta tipo="warn">Painel criado com divergência: {estado.erro}. Confira no LawChat.</Alerta>}
      {estado.estado === "criado" && <Alerta tipo="ok">Painel padrão criado e gravado.</Alerta>}
      {podeCriar && (
        <>
          <p className="muted" style={{ margin: 0, fontSize: 12 }}>1) Enviar código · 2) Simular (só leitura: confere conta, empresa e usuário admin) · 3) Enviar novo código · 4) Criar de verdade.</p>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <button className="btn sm" disabled={ocupado} onClick={pedirCodigo}>Enviar código</button>
            <input className="inp mono" style={{ width: 120 }} inputMode="numeric" autoComplete="one-time-code" placeholder="Código"
              value={codigo} onChange={(e) => setCodigo(e.target.value)} aria-label="Código recebido por e-mail" />
            <button className="btn sm" disabled={ocupado || codigo.trim().length < 4} onClick={simular}>Simular</button>
            <button className="btn sm pri" disabled={ocupado || codigo.trim().length < 4 || !simulacaoValida} onClick={criar}
              title={simulacaoValida ? "" : "Faça a simulação antes (vale 30 minutos)"}>Criar de verdade</button>
          </div>
          {estado.simulacao && simulacaoValida && (
            <p style={{ margin: 0, fontSize: 12 }}>Simulação: conta {estado.simulacao.empresa.id} · empresa {estado.simulacao.empresa.nome} · usuário admin {estado.simulacao.usuario.nome} ({estado.simulacao.usuario.email})</p>
          )}
        </>
      )}
      {aviso && <Alerta tipo="warn">{aviso}</Alerta>}
      {resposta && !resposta.ok && resposta.erro && <Alerta tipo="bad">{resposta.erro}</Alerta>}
      {resposta?.simulacao && resposta.painel && <p className="muted" style={{ margin: 0, fontSize: 12 }}>Seria criado: {resposta.painel.titulo} com {resposta.painel.etapas.join(" · ")}</p>}
      {passos.length > 0 && (
        <ol style={{ margin: 0, paddingLeft: 18, fontSize: 12 }}>
          {passos.map((p, i) => <li key={i}><Situacao valor={p.situacao === "ok" ? "ok" : p.situacao === "incerto" ? "aviso" : "erro"} texto={p.passo} /> {marca(p.detalhe)}</li>)}
        </ol>
      )}
    </div>
  );
}

function ResumoOnboarding({ linha, aoAbrir }: { linha: Linha; aoAbrir: () => void }) {
  const passos = (linha.onboarding?.passos ?? []).filter((p) => OBRIGATORIOS.includes(p.codigo));
  const prontos = passos.filter((p) => p.situacao === "ok" || p.situacao === "feito").length;
  const temErro = passos.some((p) => p.situacao === "erro");
  return (
    <button className="btn sm ghost" onClick={aoAbrir} title="Passos da primeira criação e cópia da conta do LawChat">
      {linha.onboarding?.concluido_em ? <Situacao valor="ok" texto="concluído" />
        : passos.length ? <Situacao valor={temErro ? "erro" : "pendente"} texto={`${prontos}/${OBRIGATORIOS.length} passos`} />
        : <Situacao valor="pendente" texto="não conferido" />}
    </button>
  );
}

function PassosDaConta({ linha, aoFechar }: { linha: Linha; aoFechar: () => void }) {
  const base = `/admin/escritorios/${linha.id}`;
  const { dados, erro, recarregar } = useCarregar<ResultadoOnboarding>(`${base}/onboarding`);
  const { ocupado, executar } = useAcao();
  const [ultimo, setUltimo] = useState<ResultadoOnboarding | null>(null);
  const [sinc, setSinc] = useState<Sincronizacao | null>(null);
  const [painel, setPainel] = useState("");
  const atual = ultimo ?? dados;
  const paineis = ultimo?.paineis ?? [];
  const conferir = () => executar(async () => { setUltimo(await enviar<ResultadoOnboarding>(`${base}/onboarding/conferir`, {})); recarregar(); }, "Passos conferidos.");
  const avancar = () => executar(async () => {
    setUltimo(await enviar<ResultadoOnboarding>(`${base}/onboarding/avancar`, painel ? { id_painel: painel } : {})); recarregar();
  }, "Passos aplicados.");
  const sincronizar = () => executar(async () => { setSinc(await enviar<Sincronizacao>(`${base}/sincronizar`, {})); recarregar(); }, "Conta sincronizada.");
  const passoPainel = atual?.passos?.find((p) => p.codigo === "painel");
  return (
    <Modal titulo={`Onboarding · ${linha.nome}`} largura={720} aoFechar={aoFechar}
      texto="Conferir só lê a conta na LawChat. Avançar conecta o webhook, cria as etiquetas padrão e a equipe da IA que faltam e copia a conta. O painel do CRM e o número entram na ativação do agente."
      rodape={<>
        <button className="btn" disabled={ocupado} onClick={sincronizar}>Sincronizar conta</button>
        <span className="sp" />
        <button className="btn" disabled={ocupado} onClick={conferir}>Conferir</button>
        <button className="btn pri" disabled={ocupado} onClick={avancar}>Avançar</button></>}>
      {!atual ? <Carregando erro={erro} /> : (
        <div className="form">
          {atual.concluido_em && <Alerta tipo="ok">Onboarding concluído em {quando(atual.concluido_em)}.</Alerta>}
          <div className="lst"><table><tbody>{(atual.passos ?? []).filter((p) => !FORA_DA_INTEGRACAO.includes(p.codigo)).map((p) => {
            const [valor, texto] = SITUACAO_PASSO[p.situacao] ?? ["", p.situacao];
            return (
              <tr key={p.codigo}>
                <td className="t">{marca(p.titulo)}{!OBRIGATORIOS.includes(p.codigo) && <span className="muted"> · opcional</span>}</td>
                <td><Situacao valor={valor} texto={texto} /></td>
                <td className="s">{marca(p.detalhe)}</td>
              </tr>
            );
          })}</tbody></table></div>
          <DadosDaConta dados={ultimo?.dados_helena ?? dados?.dados_helena} />
          <p className="muted" style={{ margin: 0, fontSize: 12 }}>Cópia da conta do LawChat: {quando(sinc?.sincronizado_em ?? dados?.sincronizado_em ?? linha.sincronizado_em)}</p>
          {sinc && (
            <Alerta tipo={Object.keys(sinc.erros).length ? "warn" : "ok"}>
              {Object.entries(sinc.tipos).map(([t, v]) => `${v.total} ${NOME_TIPO[t] ?? t}${v.novos ? ` (+${v.novos})` : ""}${v.sumiram ? ` (${v.sumiram} sumiram)` : ""}`).join(" · ")}
              {Object.keys(sinc.erros).length > 0 && <> · não deu para ler: {Object.entries(sinc.erros).map(([t, m]) => `${NOME_TIPO[t] ?? t} (${m})`).join(", ")}</>}
            </Alerta>
          )}
        </div>
      )}
    </Modal>
  );
}

function Consumo({ linha, aoEditar }: { linha: Linha; aoEditar: () => void }) {
  const teto = linha.limite_consumo?.mensal_usd ?? null;
  const pct = teto ? Math.min(100, (linha.gasto_mes_usd / teto) * 100) : 0;
  const cor = pct >= 100 ? "var(--bad)" : pct >= 80 ? "var(--warn)" : "var(--ok)";
  return (
    <button className="consumo" onClick={aoEditar} title="Definir o limite mensal de consumo da IA">
      <span className="num">US$ {linha.gasto_mes_usd.toFixed(2)}{teto ? <span className="muted"> / {teto.toFixed(0)}</span> : <span className="muted"> · sem limite</span>}</span>
      {teto ? <span className="barra"><i style={{ width: `${pct}%`, background: cor }} /></span> : null}
    </button>
  );
}

function EditarLimite({ linha, aoFechar, aoSalvar }: { linha: Linha; aoFechar: () => void; aoSalvar: () => void }) {
  const { ocupado, executar } = useAcao();
  const atual = linha.limite_consumo;
  const [valor, setValor] = useState(atual?.mensal_usd ? String(atual.mensal_usd) : "");
  const [aoEstourar, setAoEstourar] = useState<"pausar" | "so_avisar">(atual?.ao_estourar ?? "pausar");
  const [faixas, setFaixas] = useState((atual?.avisar_em ?? [80, 100]).join(", "));
  const salvar = () => executar(async () => {
    const avisar_em = faixas.split(/[,; ]+/).map((f) => parseInt(f, 10)).filter((f) => f > 0);
    await enviar(`/admin/escritorios/${linha.id}/limite`, { mensal_usd: valor.trim() ? Number(valor.replace(",", ".")) : null, ao_estourar: aoEstourar, avisar_em }, "PUT");
    aoSalvar();
  }, "Limite salvo.");
  return (
    <Modal titulo={`Limite de consumo · ${linha.nome}`} aoFechar={aoFechar}
      texto={`Gasto deste mês até agora: US$ ${linha.gasto_mes_usd.toFixed(2)}. O mês vira no dia 1 (horário de Brasília).`}
      rodape={<><button className="btn ghost" onClick={aoFechar}>Cancelar</button><button className="btn pri" disabled={ocupado} onClick={salvar}>Salvar</button></>}>
      <div className="form">
        <label className="field"><span className="lbl">Limite mensal (US$)</span>
          <input className="inp" inputMode="decimal" value={valor} onChange={(e) => setValor(e.target.value)} placeholder="Vazio = sem limite" />
        </label>
        <div className="field"><span className="lbl">Ao chegar em 100%</span>
          <div className="seg" role="radiogroup" aria-label="Ao estourar o limite">
            <button role="radio" aria-checked={aoEstourar === "pausar"} className={aoEstourar === "pausar" ? "on" : ""} onClick={() => setAoEstourar("pausar")}>Pausar a IA</button>
            <button role="radio" aria-checked={aoEstourar === "so_avisar"} className={aoEstourar === "so_avisar" ? "on" : ""} onClick={() => setAoEstourar("so_avisar")}>Só avisar</button>
          </div>
          <span className="ajuda">Com a IA pausada, as mensagens continuam chegando no LawChat para a equipe atender.</span>
        </div>
        <label className="field"><span className="lbl">Avisar em (%)</span>
          <input className="inp" value={faixas} onChange={(e) => setFaixas(e.target.value)} />
          <span className="ajuda">Um aviso por faixa no mês: fica em Erros e avisos e vai por WhatsApp para quem estiver no aviso "Consumo da IA perto do limite".</span>
        </label>
      </div>
    </Modal>
  );
}

