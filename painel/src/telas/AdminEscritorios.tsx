import fotoLawChat from "@/assets/lawchat-perfil.jpg";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, Bot, Building2, CheckCircle2, Clock, ExternalLink, RefreshCw, Search } from "lucide-react";
import { enviar } from "../api";
import { Alerta, Carregando, Modal, Situacao, Vazio, useAcao, useCarregar } from "../componentes/ui";
import { useSessao } from "../sessao";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

/** GET /api/admin/escritorios/primeiros-passos: os 7 primeiros passos de cada conta (app/gestao/primeiros_passos.py). */
interface Progresso { feitos: number; total: number; completo: boolean; faltam: string[] }

interface ContaEmpresa { nome?: string | null; razao_social?: string | null; documento?: string | null; documento_formatado?: string | null;
  tipo_pessoa?: string | null; administrador?: string | null; email_contato?: string | null; telefone?: string | null; ativa?: boolean; foto?: string | null;
  endereco?: { city?: string; state?: string } }
interface Linha { id: string; nome: string; situacao: string; ia_desligada: boolean; id_conta_helena: string | null; criado_em: string; agentes: number; agentes_ativos: number; erros_abertos: number; helena: string | null; id_responsavel: string | null; responsavel: string | null;
  gasto_mes_usd: number; limite_consumo: Limite | null; onboarding?: Onboarding | null; sincronizado_em?: string | null;
  conta_helena?: ContaEmpresa | null; sync_helena?: { situacao?: string; erro?: string | null } | null;
  conta_lawchat?: boolean; agente_habilitado?: boolean; webhook?: "synced" | "pending" | "error" }
interface PassoOnboarding { codigo: string; titulo: string; situacao: string; detalhe: string; em?: string }
interface Onboarding { passos?: PassoOnboarding[]; concluido_em?: string | null; atualizado_em?: string }
/** Painel da conta como o conferir devolve: `padrao` = tem as 6 etapas fixas; `sugestao` = etapas ligadas por tipo. */
interface PainelDaConta { id: string; titulo: string; colunas: number; padrao?: boolean; etapas?: { id: string; titulo: string }[];
  sugestao?: Record<string, string> }
interface ResultadoOnboarding extends Onboarding { completo?: boolean; paineis?: PainelDaConta[]; painel_sugerido?: string;
  painel_crm?: { criar_ligado: boolean; falta_configurar: string[] };
  sincronizado_em?: string | null; obrigatorios?: string[]; dados_helena?: DadosHelena; etapas_por_tipo?: Record<string, string> }
interface DadosHelena { conta?: { razao_social?: string | null; documento?: string | null; documento_formatado?: string | null; tipo_documento?: string | null;
  endereco?: { city?: string; state?: string }; recursos?: { includedAgents?: number; includedSessions?: number } };
  ids?: { id_painel?: string; etapas_por_tipo?: Record<string, string>; id_departamento?: string; id_assinatura?: string; etiquetas?: Record<string, string> } }
interface Sincronizacao { sincronizado_em: string | null; tipos: Record<string, { total: number; novos: number; sumiram: number }>; erros: Record<string, string> }
interface ResultadoSync { total: number; criadas: number; atualizadas: number; com_erro: number; erros: { nome?: string | null; id_conta_helena?: string | null; erro: string }[] }
interface ResultadoHabilitar { habilitado: boolean; passos: PassoOnboarding[] }
// O que trava o onboarding DA CONTA (o servidor devolve a mesma lista em `obrigatorios`; esta é a reserva).
const OBRIGATORIOS = ["token", "webhook", "etiquetas", "painel"];
// Só informação: o primeiro produto é da ativação do agente e não prende o Avançar nem o Habilitado.
const INFORMATIVOS = ["produto"];
// Números e ZapSign são da ativação do agente (lá o sistema sincroniza com a LawChat). O painel do CRM fica AQUI:
// a ativação não cria nem escolhe painel, só usa o escolhido (app/gestao/ativacao.py, passo "crm").
const FORA_DA_INTEGRACAO = ["canais", "zapsign"];
const NOME_ETAPA: Record<string, string> = { SDR: "SDR", COMERCIAL: "Comercial", CONTRATO: "Contrato em Elaboração",
  AGUARDANDO_ASSINATURA: "Aguardando Assinatura", CONTRATO_ASSINADO: "Contrato Assinado", DESQUALIFICADO: "Desqualificado" };
const PASSO_OK = (p?: { situacao: string }) => p?.situacao === "ok" || p?.situacao === "feito";
/** Painel sugerido: o "🤖 CRM COMERCIAL IA" (ou outro com "Comercial IA" no nome), quando existe na conta. */
function painelSugerido(paineis: { id: string; titulo: string; padrao?: boolean }[]): string {
  const padrao = paineis.filter((x) => x.padrao);
  if (padrao.length === 1) return padrao[0].id;                 // o único com as 6 etapas fixas
  if (padrao.length > 1) return "";                             // mais de um: o admin escolhe
  const chave = (t: string) => String(t ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  return (paineis.find((x) => chave(x.titulo).includes("crm comercial ia")) ?? paineis.find((x) => chave(x.titulo).includes("comercial ia")))?.id ?? "";
}
const TIPOS_ETAPA = ["SDR", "COMERCIAL", "CONTRATO", "AGUARDANDO_ASSINATURA", "CONTRATO_ASSINADO", "DESQUALIFICADO"];
const NOME_TIPO: Record<string, string> = { canal: "números", painel: "painéis", coluna: "colunas", etiqueta: "etiquetas", equipe: "equipes", usuario: "usuários" };
const SITUACAO_PASSO: Record<string, [string, string]> = {
  ok: ["ok", "ok"], feito: ["ok", "feito agora"], aviso: ["aviso", "atenção"], erro: ["erro", "com erro"],
  pendente: ["pendente", "pendente"], pulado: ["desligada", "não se aplica"],
};
const quando = (iso?: string | null) => (iso ? new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "nunca");
interface Limite { mensal_usd: number | null; ao_estourar: "pausar" | "so_avisar"; avisar_em: number[]; }

/** O dono vende a LawChat com a marca LawChat: textos do servidor mostrados nesta tela trocam o nome. */
function marca(texto?: unknown): string {
  // Texto do servidor pode vir em outro formato (lista, objeto): vira texto em vez de derrubar a tela.
  const t = typeof texto === "string" ? texto : texto == null ? "" : typeof texto === "object" ? JSON.stringify(texto) : String(texto);
  return t.replace(/A LawChat/g, "O LawChat").replace(/a LawChat/g, "o LawChat").replace(/da LawChat/g, "do LawChat")
    .replace(/na LawChat/g, "no LawChat").replace(/LawChat/g, "LawChat");
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
  const { dados, erro, recarregar: recarregarContas } = useCarregar<Linha[]>("/admin/escritorios");
  const progresso = useCarregar<Record<string, Progresso>>("/admin/escritorios/primeiros-passos");
  const recarregar = () => { recarregarContas(); progresso.recarregar(); };
  const linhas = dados ?? [];
  const { ocupado: sincronizando, executar } = useAcao();
  const acaoLinha = useAcao();
  const [linhaOcupada, setLinhaOcupada] = useState<string | null>(null);
  const [sync, setSync] = useState<ResultadoSync | null>(null);
  const [busca, setBusca] = useState("");
  const [filtro, setFiltro] = useState<FiltroAgente>("todos");
  const [habilitar, setHabilitar] = useState<Linha | null>(null);
  const [passos, setPassos] = useState<Linha | null>(null);

  const entrar = (id: string, para = "/") => { trocarEscritorio(id); trocarVisao("lawchat"); navegar(para); };
  // "Primeiro produto" pendente: entra na conta (o mesmo Acessar da linha) e abre a Biblioteca para ativar o agente.
  const ativarPrimeiro = (id: string) => entrar(id, "/biblioteca");

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
            <th>Nome fantasia / Razão social</th><th>CNPJ</th><th>Situação</th><th>Função de agente</th><th>Webhook</th><th>Progresso</th><th>Última sync</th>
            <th style={{ textAlign: "right" }}>Ações</th>
          </tr></thead>
          <tbody>
            {filtradas.length === 0 && <tr><td colSpan={8} className="muted" style={{ textAlign: "center", padding: 28 }}>Nenhuma conta encontrada.</td></tr>}
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
                  <td><CelulaProgresso p={progresso.dados?.[l.id]} carregando={!progresso.dados && !progresso.erro} /></td>
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
        aoVerPassos={() => { setPassos(habilitar); setHabilitar(null); }} aoAtivarProduto={() => ativarPrimeiro(habilitar.id)} />}
      {passos && <PassosDaConta linha={passos} aoFechar={() => { setPassos(null); recarregar(); }} aoAtivarProduto={() => ativarPrimeiro(passos.id)} />}
    </>
  );
}

/** "4/7" com a barrinha; a dica lista os passos que faltam (os mesmos do cartão "Primeiros passos" do cliente). */
function CelulaProgresso({ p, carregando }: { p?: Progresso; carregando: boolean }) {
  if (!p) return <span className="muted">{carregando ? "…" : "—"}</span>;
  const pct = Math.round((p.feitos / Math.max(1, p.total)) * 100);
  const cor = p.completo ? "var(--ok)" : pct >= 50 ? "var(--warn)" : "var(--bad)";
  const marca = (
    <span tabIndex={0} aria-label={`${p.feitos} de ${p.total} primeiros passos`}
      style={{ display: "inline-flex", alignItems: "center", gap: 6, whiteSpace: "nowrap", cursor: p.completo ? "default" : "help" }}>
      <span aria-hidden style={{ width: 44, height: 5, borderRadius: 3, background: "var(--surface-2, #eef1f5)", overflow: "hidden", display: "inline-block" }}>
        <span style={{ display: "block", height: "100%", width: `${Math.max(6, pct)}%`, background: cor }} />
      </span>
      <b className="num" style={{ fontSize: 12.5 }}>{p.feitos}/{p.total}</b>
    </span>
  );
  if (p.completo) return marca;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{marca}</TooltipTrigger>
      <TooltipContent side="top" className="max-w-[320px]">
        <b>Faltam:</b>
        <ul style={{ margin: "4px 0 0", paddingLeft: 16 }}>{p.faltam.map((f) => <li key={f}>{f}</li>)}</ul>
      </TooltipContent>
    </Tooltip>
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
function HabilitarAgente({ linha, aoFechar, aoMudar, aoVerPassos, aoAtivarProduto }: { linha: Linha; aoFechar: () => void; aoMudar: () => void;
  aoVerPassos: () => void; aoAtivarProduto: () => void }) {
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
          {resultado.habilitado && !PASSO_OK(resultado.passos.find((p) => p.codigo === "painel")) && (
            <Alerta tipo="warn">Falta escolher o painel do CRM.{" "}
              <button className="btn sm" onClick={aoVerPassos}>Abrir os passos e escolher o painel</button></Alerta>
          )}
          {resultado.habilitado && !PASSO_OK(resultado.passos.find((p) => p.codigo === "produto")) && (
            <button className="btn sm pri" style={{ alignSelf: "flex-start" }} onClick={aoAtivarProduto}><ExternalLink />Acessar e ativar o primeiro agente</button>
          )}
          <p className="muted" style={{ margin: 0, fontSize: 12 }}>O número entra quando você ativar o primeiro agente (Acessar › Biblioteca).</p>
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
      {ids && <span>Etapas do painel ligadas: {ligados.length}/{TIPOS_ETAPA.length}{ligados.length < TIPOS_ETAPA.length && ids.id_painel ? ` · sem coluna: ${TIPOS_ETAPA.filter((t) => !ligados.includes(t)).join(", ")}` : ""}{!ids.id_painel ? " · nenhum painel escolhido" : ""}</span>}
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

/** Uma linha dizendo o que falta no servidor para ligar "Criar painel padrão" (só nomes de variáveis, nunca valores). */
function faltaParaCriar(config?: { criar_ligado: boolean; falta_configurar: string[] } | null): string[] {
  if (!config) return [];
  return [...(config.criar_ligado ? [] : ["AGENTESIA_PAINEL_CRM_LIGADO=1"]), ...config.falta_configurar];
}

function CriarPainelPadrao({ idEscritorio, aoMudar, config }: { idEscritorio: string; aoMudar: () => void;
  config?: { criar_ligado: boolean; falta_configurar: string[] } | null }) {
  const base = `/admin/escritorios/${idEscritorio}/painel-crm`;
  const [estado, setEstado] = useState<EstadoPainel | null>(null);
  const [desligado, setDesligado] = useState(config ? !config.criar_ligado : false);
  const [codigo, setCodigo] = useState("");
  const [resposta, setResposta] = useState<RespostaPainel | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const carregar = async () => {
    try { setEstado(await acaoPainelCrm<EstadoPainel>(base, undefined, "GET")); }
    catch (e) { if ((e as { status?: number }).status === 404) setDesligado(true); else setAviso((e as Error).message); }
  };
  useEffect(() => { if (!desligado) void carregar(); }, [idEscritorio, desligado]);  // eslint-disable-line react-hooks/exhaustive-deps
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
  const falta = desligado ? (faltaParaCriar(config).length ? faltaParaCriar(config) : ["AGENTESIA_PAINEL_CRM_LIGADO=1"]) : faltaParaCriar(config);
  if (falta.length) return <p className="muted" style={{ margin: 0, fontSize: 12 }}>Criar painel padrão está desligado no servidor (falta {falta.join(", ")}): escolha acima um painel que já existe.</p>;
  if (!estado) return null;
  const simulacaoValida = Boolean(estado.simulacao && Date.now() - new Date(estado.simulacao.quando).getTime() < 30 * 60 * 1000);
  const passos = resposta?.passos ?? estado.passos ?? [];
  const podeCriar = !estado.ja_tem_painel && !BLOQUEIOS_PAINEL.includes(estado.estado);
  return (
    <div className="panel" style={{ padding: 12, display: "grid", gap: 8 }}>
      <div className="t">Ou criar painel padrão (🤖 CRM COMERCIAL IA, com as 6 etapas fixas)</div>
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
          <p className="muted" style={{ margin: 0, fontSize: 12 }}>1) Enviar código (chega no e-mail do parceiro) · 2) Simular (só leitura: confere conta, empresa e usuário admin) · 3) Enviar novo código · 4) Criar painel padrão.</p>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <button className="btn sm" disabled={ocupado} onClick={pedirCodigo}>Enviar código</button>
            <input className="inp mono" style={{ width: 120 }} inputMode="numeric" autoComplete="one-time-code" placeholder="Código"
              value={codigo} onChange={(e) => setCodigo(e.target.value)} aria-label="Código recebido por e-mail" />
            <button className="btn sm" disabled={ocupado || codigo.trim().length < 4} onClick={simular}>Simular</button>
            <button className="btn sm pri" disabled={ocupado || codigo.trim().length < 4 || !simulacaoValida} onClick={criar}
              title={simulacaoValida ? "" : "Faça a simulação antes (vale 30 minutos)"}>Criar painel padrão</button>
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

/** Escolha do painel do CRM: o painel e, quando ele não tem as etapas fixas, qual coluna é cada tipo. */
function EscolherPainel({ paineis, painel, setPainel, etapas, setEtapas }: { paineis: PainelDaConta[]; painel: string;
  setPainel: (id: string) => void; etapas: Record<string, string>; setEtapas: (e: Record<string, string>) => void }) {
  const escolhido = paineis.find((x) => x.id === painel);
  const candidatos = paineis.filter((x) => x.padrao).length;
  return (
    <div className="field" style={{ display: "grid", gap: 6 }}>
      <label className="field"><span className="lbl">Painel do CRM (aplica ao avançar)</span>
        <select className="inp" value={painel} onChange={(e) => {
          const id = e.target.value;
          setPainel(id);
          setEtapas({ ...(paineis.find((x) => x.id === id)?.sugestao ?? {}) });
        }}>
          <option value="">Escolher…</option>
          {paineis.map((x) => <option key={x.id} value={x.id}>{x.titulo} · {x.colunas} colunas{x.padrao ? " · etapas padrão" : ""}</option>)}
        </select>
        <span className="ajuda">{candidatos === 1 ? "O painel com as etapas padrão já vem escolhido. " : candidatos > 1 ? `${candidatos} painéis têm as etapas padrão: escolha qual a IA usa. ` : ""}
          A ativação do agente usa este painel para mover os cards.</span>
      </label>
      {escolhido && !escolhido.padrao && (escolhido.etapas?.length ?? 0) > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 6 }}>
          {TIPOS_ETAPA.map((tipo) => (
            <label key={tipo} className="field"><span className="lbl" style={{ fontSize: 12 }}>{NOME_ETAPA[tipo] ?? tipo}</span>
              <select className="inp" value={etapas[tipo] ?? ""} onChange={(e) => {
                const novo = { ...etapas };
                if (e.target.value) novo[tipo] = e.target.value; else delete novo[tipo];
                setEtapas(novo);
              }}>
                <option value="">Sem coluna</option>
                {(escolhido.etapas ?? []).map((c) => <option key={c.id} value={c.id}>{c.titulo || "(sem nome)"}</option>)}
              </select>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

function PassosDaConta({ linha, aoFechar, aoAtivarProduto }: { linha: Linha; aoFechar: () => void; aoAtivarProduto: () => void }) {
  const base = `/admin/escritorios/${linha.id}`;
  const { dados, erro, recarregar } = useCarregar<ResultadoOnboarding>(`${base}/onboarding`);
  const { ocupado, executar } = useAcao();
  const [ultimo, setUltimo] = useState<ResultadoOnboarding | null>(null);
  const [sinc, setSinc] = useState<Sincronizacao | null>(null);
  const [painel, setPainel] = useState("");
  const [etapas, setEtapas] = useState<Record<string, string>>({});
  const [criarEquipe, setCriarEquipe] = useState(false);
  const [falha, setFalha] = useState<string | null>(null);
  const atual = ultimo ?? dados;
  const paineis = Array.isArray(ultimo?.paineis) ? ultimo!.paineis : [];
  const obrigatorios = Array.isArray(atual?.obrigatorios) && atual!.obrigatorios.length ? atual!.obrigatorios : OBRIGATORIOS;
  // Erro do servidor fica DENTRO do modal (legível), além do aviso no canto.
  const rodar = (fn: () => Promise<void>, sucesso: string) => executar(async () => {
    setFalha(null);
    try { await fn(); } catch (e) { setFalha((e as Error).message || "Falha inesperada."); throw e; }
  }, sucesso);
  const conferirEmSilencio = () => enviar<ResultadoOnboarding>(`${base}/onboarding/conferir`, {}).then(setUltimo)
    .catch((e) => setFalha((e as Error).message || "Não deu para conferir."));
  const conferir = () => rodar(async () => { setUltimo(await enviar<ResultadoOnboarding>(`${base}/onboarding/conferir`, {})); recarregar(); }, "Passos conferidos.");
  // Ao abrir, confere sozinho (só lê a conta): é o que traz a lista de painéis para escolher.
  useEffect(() => {
    let vivo = true;
    enviar<ResultadoOnboarding>(`${base}/onboarding/conferir`, {}).then((r) => { if (vivo) setUltimo(r); })
      .catch((e) => { if (vivo) setFalha((e as Error).message || "Não deu para conferir."); });
    return () => { vivo = false; };
  }, [base]);
  // Pré-seleciona: o painel já gravado; senão o único com as etapas padrão (ou "CRM Comercial IA" pelo nome).
  useEffect(() => {
    if (painel || !paineis.length) return;
    const gravado = ultimo?.dados_helena?.ids?.id_painel;
    const id = (gravado && paineis.some((x) => x.id === gravado) ? gravado : "") || ultimo?.painel_sugerido || painelSugerido(paineis);
    if (!id) return;
    setPainel(id);
    setEtapas({ ...(paineis.find((x) => x.id === id)?.sugestao ?? {}), ...(id === gravado ? ultimo?.dados_helena?.ids?.etapas_por_tipo ?? {} : {}) });
  }, [paineis, painel, ultimo]);
  const avancar = () => rodar(async () => {
    const corpo: Record<string, unknown> = { criar_equipe_ia: criarEquipe };
    if (painel) {
      corpo.id_painel = painel;
      const escolhido = paineis.find((x) => x.id === painel);
      if (escolhido && !escolhido.padrao && Object.keys(etapas).length) corpo.etapas_por_tipo = etapas;
    }
    setUltimo(await enviar<ResultadoOnboarding>(`${base}/onboarding/avancar`, corpo)); recarregar();
  }, "Passos aplicados.");
  const sincronizar = () => rodar(async () => { setSinc(await enviar<Sincronizacao>(`${base}/sincronizar`, {})); recarregar(); }, "Conta sincronizada.");
  const passos = Array.isArray(atual?.passos) ? atual!.passos : [];
  const passoPainel = passos.find((p) => p.codigo === "painel");
  const passoEquipe = passos.find((p) => p.codigo === "equipe");
  return (
    <Modal titulo={`Onboarding · ${linha.nome}`} largura={720} aoFechar={aoFechar}
      texto="Conferir só lê a conta na LawChat. Avançar conecta o webhook, cria as etiquetas padrão que faltam, grava o painel do CRM e copia a conta. Escolha aqui o painel do CRM. O número entra na ativação do agente."
      rodape={<>
        <button className="btn" disabled={ocupado} onClick={sincronizar}>Sincronizar conta</button>
        <span className="sp" />
        <button className="btn" disabled={ocupado} onClick={conferir}>Conferir</button>
        <button className="btn pri" disabled={ocupado} onClick={avancar}>{ocupado ? <RefreshCw className="animate-spin" /> : null}Avançar</button></>}>
      {!atual ? <Carregando erro={erro} /> : (
        <div className="form">
          {falha && <Alerta tipo="bad">{marca(falha)}</Alerta>}
          {atual.concluido_em && <Alerta tipo="ok">Onboarding da conta concluído em {quando(atual.concluido_em)}.</Alerta>}
          <div className="lst"><table><tbody>{passos.filter((p) => !FORA_DA_INTEGRACAO.includes(p.codigo)).map((p) => {
            const [valor, texto] = SITUACAO_PASSO[p.situacao] ?? ["", String(p.situacao ?? "")];
            return (
              <tr key={p.codigo}>
                <td className="t">{marca(p.titulo)}
                  {INFORMATIVOS.includes(p.codigo) ? <span className="muted"> · informativo (ativação do agente)</span>
                    : !obrigatorios.includes(p.codigo) && <span className="muted"> · opcional</span>}</td>
                <td><Situacao valor={valor} texto={texto} /></td>
                <td className="s">{marca(p.detalhe)}
                  {p.codigo === "produto" && !PASSO_OK(p) && (
                    <div style={{ marginTop: 6 }}><button className="btn sm pri" onClick={aoAtivarProduto}><ExternalLink />Acessar e ativar o primeiro agente</button></div>
                  )}
                </td>
              </tr>
            );
          })}</tbody></table></div>
          {paineis.length > 0 && <EscolherPainel paineis={paineis} painel={painel} setPainel={setPainel} etapas={etapas} setEtapas={setEtapas} />}
          {!ultimo && !falha && <p className="muted" style={{ margin: 0, fontSize: 12 }}>Lendo os painéis da conta…</p>}
          {ultimo && !PASSO_OK(passoPainel) && passoPainel?.situacao !== "aviso" && (
            <CriarPainelPadrao idEscritorio={linha.id} config={ultimo.painel_crm} aoMudar={() => { recarregar(); void conferirEmSilencio(); }} />
          )}
          {!PASSO_OK(passoEquipe) && (
            <label className="check" style={{ fontSize: 13 }}>
              <input type="checkbox" checked={criarEquipe} onChange={(e) => setCriarEquipe(e.target.checked)} />
              Criar também a equipe "🤖 Comercial IA" ao avançar, como equipe PADRÃO da conta
            </label>
          )}
          <DadosDaConta dados={ultimo?.dados_helena ?? dados?.dados_helena} />
          <p className="muted" style={{ margin: 0, fontSize: 12 }}>Cópia da conta do LawChat: {quando(sinc?.sincronizado_em ?? dados?.sincronizado_em ?? linha.sincronizado_em)}</p>
          {sinc && (
            <Alerta tipo={Object.keys(sinc.erros ?? {}).length ? "warn" : "ok"}>
              {Object.entries(sinc.tipos ?? {}).map(([t, v]) => `${v.total} ${NOME_TIPO[t] ?? t}${v.novos ? ` (+${v.novos})` : ""}${v.sumiram ? ` (${v.sumiram} sumiram)` : ""}`).join(" · ")}
              {Object.keys(sinc.erros ?? {}).length > 0 && <> · não deu para ler: {Object.entries(sinc.erros).map(([t, m]) => `${NOME_TIPO[t] ?? t} (${marca(m)})`).join(", ")}</>}
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

