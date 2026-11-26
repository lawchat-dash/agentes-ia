// Ferramentas › Avisos no WhatsApp. A conta escolhe o número que envia e quem recebe (valem para todos os avisos) e liga
// os avisos que quer, cada um com o texto da mensagem. Só aparecem os avisos que o sistema dispara de verdade.
// Backend: app/gestao/rotas_avisos.py (/avisos, /avisos/conta, /avisos/ligados, /avisos/item/:chave).
import { Fragment, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle, ArrowLeft, BadgeCheck, Bell, BookX, BotOff, Check, ClipboardList, Contact, FileCheck, FileSignature, Flame,
  Handshake, Hourglass, Image, MapPinOff, MessagesSquare, Mic, Pencil, Phone, Plus, Printer, RotateCcw, Scale, Search, Send,
  Shuffle, Trash2, UserPlus, UserRound, UserX, Video, X,
} from "lucide-react";
import { api, enviar, formatarTelefone } from "../api";
import { Alerta, Carregando, Interruptor, Modal, Vazio, useAcao, useAvisar, useCarregar, useConfirmar } from "../componentes/ui";
import { useSessao } from "../sessao";
import "../estilo-automacao.css";

// --------------------------------------------------------------------------- tipos
interface Canal { id: string; numero: string; nome: string | null; tipo: string | null; tipo_helena: string | null; ativo: boolean; agente: string | null; oficial: boolean; pode_enviar: boolean }
interface Pessoa { rotulo: string; numero: string }
interface Item { chave: string; nome: string; descricao: string; icone: string; ligado: boolean; configurado: boolean; nome_interno: string; modelo: string; modelo_padrao: string }
interface Grupo { chave: string; titulo: string; itens: Item[] }
interface Dados {
  numero_envio: Canal | null; numero_escolhido: boolean; canais: Canal[]; destinatarios: Pessoa[]; grupos: Grupo[];
  antigos: { tipo_evento: string; nome: string; habilitada: boolean }[];
  marcadores: { chave: string; rotulo: string }[]; exemplo: Record<string, string>;
  agentes: { total: number; com_avisos: string[]; sem_avisos: string[] };
}

const ICONES: Record<string, typeof Bell> = {
  "user-plus": UserPlus, "badge-check": BadgeCheck, handshake: Handshake, "clipboard-list": ClipboardList, "file-signature": FileSignature,
  "file-check": FileCheck, "user-x": UserX, "user-round": UserRound, scale: Scale, "book-x": BookX, mic: Mic, video: Video,
  contact: Contact, shuffle: Shuffle, "messages-square": MessagesSquare, image: Image, "map-pin-off": MapPinOff, printer: Printer,
  flame: Flame, hourglass: Hourglass, "alert-triangle": AlertTriangle, "bot-off": BotOff,
};
const COR_GRUPO: Record<string, string> = { funil: "#00A32C", atencao: "#2563EB", problema: "#DC2626" };
const corDo = (grupo: string, item: Item) => (item.icone === "alert-triangle" ? "#D97706" : COR_GRUPO[grupo] ?? "#00A32C");
const iniciais = (nome: string) => nome.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]?.toUpperCase()).join("") || "?";
const pessoas = (n: number) => `${n} ${n === 1 ? "pessoa" : "pessoas"}`;

// --------------------------------------------------------------------------- prévia do WhatsApp
const MARCADOR = /\{\{\s*([a-z_]+)\s*\}\}/g;
/** Mesma regra do envio (app/notificacoes.renderizar_modelo): linha com dado vazio some. */
function renderizar(modelo: string, valores: Record<string, string>): string {
  const linhas = modelo.replace(/\r\n/g, "\n").split("\n").filter((l) => [...l.matchAll(MARCADOR)].every((m) => (valores[m[1]] ?? "").trim()));
  return linhas.map((l) => l.replace(MARCADOR, (_, c) => valores[c] ?? "")).join("\n").replace(/\n{3,}/g, "\n\n").trim();
}
function emLinha(texto: string): ReactNode[] {
  return texto.split(/(`[^`\n]+`|\*[^*\n]+\*|_[^_\n]+_|~[^~\n]+~)/g).map((p, i) => {
    if (p.length > 2 && p.startsWith("`") && p.endsWith("`")) return <code key={i}>{p.slice(1, -1)}</code>;
    if (p.length > 2 && p.startsWith("*") && p.endsWith("*")) return <b key={i}>{p.slice(1, -1)}</b>;
    if (p.length > 2 && p.startsWith("_") && p.endsWith("_")) return <i key={i}>{p.slice(1, -1)}</i>;
    if (p.length > 2 && p.startsWith("~") && p.endsWith("~")) return <s key={i}>{p.slice(1, -1)}</s>;
    return <Fragment key={i}>{p}</Fragment>;
  });
}
function BalaoWhatsApp({ texto }: { texto: string }) {
  const hora = new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  return (
    <div className="av-zap" aria-live="polite">
      <div className="av-zap-topo"><span style={{ width: 8, height: 8, borderRadius: 9, background: "#25D366" }} />Como chega no WhatsApp</div>
      <div className="av-zap-fundo">
        <div className="av-balao">
          {texto ? texto.split("\n").map((linha, i) => linha.startsWith("> ")
            ? <blockquote key={i}>{emLinha(linha.slice(2))}</blockquote>
            : <Fragment key={i}>{emLinha(linha)}{"\n"}</Fragment>) : <span className="muted">Mensagem vazia.</span>}
          <small>{hora} ✓✓</small>
        </div>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- tela
export function TelaAvisos() {
  const { escritorio } = useSessao();
  const { dados, erro, recarregar } = useCarregar<Dados>("/avisos", [escritorio]);
  const { ocupado, executar } = useAcao();
  const [confirmar, janelaConfirmar] = useConfirmar();
  const [janela, setJanela] = useState<null | "numero" | "pessoas" | "gerenciar">(null);
  const [editando, setEditando] = useState<{ item: Item; grupo: string } | null>(null);
  const [ajustar, setAjustar] = useState<boolean | null>(null);

  const itens = useMemo(() => (dados?.grupos ?? []).flatMap((g) => g.itens.map((i) => ({ ...i, grupo: g.chave }))), [dados]);
  if (!dados) return <><Topo /><Carregando erro={erro} /></>;

  const ligados = itens.filter((i) => i.ligado).length;
  const numeroOk = Boolean(dados.numero_envio?.pode_enviar);
  const passos = [numeroOk, dados.destinatarios.length > 0, ligados > 0];
  const feitos = passos.filter(Boolean).length;
  const aberta = ajustar ?? feitos < 3;
  const alternar = (item: Item, v: boolean) => executar(async () => {
    await enviar(`/avisos/item/${item.chave}`, { ligado: v }, "PUT");
    await recarregar();
  }, v ? `"${item.nome}" ligado.` : `"${item.nome}" desligado.`);
  const apagarAntigo = async (a: Dados["antigos"][number]) => {
    if (!(await confirmar({ titulo: "Apagar aviso antigo?", perigo: true, confirmar: "Apagar",
      texto: <><b>{a.nome}</b> está fora da lista de avisos ({a.tipo_evento}). Os avisos da lista já cobrem esse acontecimento.</> }))) return;
    executar(async () => { await api(`/notificacoes/${encodeURIComponent(a.tipo_evento)}`, { metodo: "DELETE" }); await recarregar(); }, "Aviso antigo apagado.");
  };

  return (
    <>
      {janelaConfirmar}
      <Topo />

      {dados.numero_envio?.oficial && (
        <div style={{ marginBottom: 14 }}><Alerta tipo="bad" titulo="O número de envio é oficial">
          Número oficial (API oficial do WhatsApp) só manda mensagens aprovadas pela Meta: os avisos não saem. Troque por um número não oficial.
        </Alerta></div>
      )}
      {dados.agentes.total > 0 && dados.agentes.com_avisos.length === 0 && ligados > 0 && (
        <div style={{ marginBottom: 14 }}><Alerta tipo="warn" titulo="Nenhum agente está avisando a equipe">
          Os avisos saem dos agentes com a função "Avisar a equipe" ligada. Ligue em <Link to="/meus-produtos">Meus agentes</Link> › Funções e automações.
        </Alerta></div>
      )}

      {!aberta ? (
        <div className="av-faixa">
          <span className="ok"><Check />Configuração concluída</span>
          <span className="pt">·</span><span className="mono">{formatarTelefone(dados.numero_envio?.numero)}</span>
          <span className="pt">·</span><span>{pessoas(dados.destinatarios.length)}</span>
          <span className="pt">·</span><span>{ligados} {ligados === 1 ? "aviso ativo" : "avisos ativos"}</span>
          <span className="sp" />
          <button type="button" className="btn sm" onClick={() => setAjustar(true)}>Ajustar</button>
        </div>
      ) : (
        <section className="av-config" aria-label="Configuração da conta">
          <div className="av-config-cab">
            <div><b>Configuração da conta</b><small>Em 3 passos: defina o número que envia, quem recebe e ligue os avisos.</small></div>
            <span className="sp" />
            <span className={`chip ${feitos === 3 ? "ok" : ""}`}>{feitos} de 3</span>
            {feitos === 3 && <button type="button" className="btn ghost sm" onClick={() => setAjustar(false)}>Recolher</button>}
          </div>
          <div className="av-passos">
            <div className="av-passo">
              <div className="av-passo-cab"><span className={`av-num ${passos[0] ? "feito" : ""}`}>{passos[0] ? <Check /> : 1}</span>
                <div><b>Número de envio</b><small>De qual WhatsApp os avisos saem.</small></div></div>
              {dados.numero_envio ? (
                <div><span className="av-numero">{formatarTelefone(dados.numero_envio.numero)}</span>{" "}
                  <span className={`chip ${dados.numero_envio.oficial ? "bad" : "ok"}`}>{dados.numero_envio.oficial ? "Oficial" : "Não oficial"}</span>
                  {!dados.numero_escolhido && <div className="muted" style={{ fontSize: 12 }}>Escolhido automaticamente (o primeiro número não oficial).</div>}
                </div>
              ) : <span className="sec" style={{ fontSize: 13 }}>Nenhum número da conta pode enviar avisos.</span>}
              <button type="button" className="btn sm" style={{ alignSelf: "flex-start" }} onClick={() => setJanela("numero")}><Phone />Trocar número</button>
            </div>
            <div className="av-passo">
              <div className="av-passo-cab"><span className={`av-num ${passos[1] ? "feito" : ""}`}>{passos[1] ? <Check /> : 2}</span>
                <div><b>Quem recebe</b><small>As pessoas que recebem os avisos.</small></div></div>
              {dados.destinatarios.length ? (
                <div className="av-pessoas">{dados.destinatarios.slice(0, 6).map((p) => (
                  <span key={p.numero} className="av-pessoa" title={formatarTelefone(p.numero)}><span className="av">{iniciais(p.rotulo)}</span>{p.rotulo}</span>
                ))}{dados.destinatarios.length > 6 && <span className="av-pessoa">+{dados.destinatarios.length - 6}</span>}</div>
              ) : <span className="sec" style={{ fontSize: 13 }}>Ninguém ainda.</span>}
              <button type="button" className="btn sm" style={{ alignSelf: "flex-start" }} onClick={() => setJanela("pessoas")}><Pencil />Editar</button>
            </div>
            <div className="av-passo">
              <div className="av-passo-cab"><span className={`av-num ${passos[2] ? "feito" : ""}`}>{passos[2] ? <Check /> : 3}</span>
                <div><b>Ligar os avisos</b><small>Quais acontecimentos te avisam.</small></div></div>
              <span className="sec" style={{ fontSize: 13 }}><b className="num">{ligados}</b> {ligados === 1 ? "aviso ativo" : "avisos ativos"}</span>
              <button type="button" className="btn sm" style={{ alignSelf: "flex-start" }} onClick={() => setJanela("gerenciar")}><Bell />Gerenciar avisos</button>
            </div>
          </div>
        </section>
      )}

      <div className="au-titulo-grupo" style={{ marginTop: 6 }}>
        <h3>Seus avisos</h3><span>{ligados} de {itens.length} ligados</span><span className="sp" style={{ flex: 1 }} />
        <button type="button" className="au-link" onClick={() => setJanela("gerenciar")}>Gerenciar</button>
      </div>
      {dados.grupos.map((g) => g.itens.length > 0 && (
        <section key={g.chave} aria-label={g.titulo}>
          <div className="au-titulo-grupo"><h3 style={{ fontSize: 11 }}>{g.titulo}</h3><span>{g.itens.filter((i) => i.ligado).length} de {g.itens.length}</span></div>
          <div className="au-grade tres">
            {g.itens.map((item) => {
              const Icone = ICONES[item.icone] ?? Bell;
              return (
                <div key={item.chave} className={`au-cartao av-cartao ${item.ligado ? "" : "desligado"}`} style={{ "--au-cor": corDo(g.chave, item) } as CSSProperties}>
                  <div className="au-cartao-corpo">
                    <div className="au-cartao-cab">
                      <span className="au-icone"><Icone /></span>
                      <div><b title={item.nome}>{item.nome}</b>
                        <span className={`chip ${item.ligado ? "ok" : ""}`} style={{ marginTop: 3 }}>{item.ligado ? "Ativo" : "Inativo"}</span></div>
                      <Interruptor rotulo={`${item.nome}: ${item.ligado ? "ligado" : "desligado"}`} ligado={item.ligado} desligado={ocupado} aoMudar={(v) => alternar(item, v)} />
                    </div>
                    <p>{item.descricao}</p>
                  </div>
                  <div className="au-cartao-rodape">
                    <button type="button" className="au-link" onClick={() => setEditando({ item, grupo: g.chave })}><Pencil />Editar mensagem</button>
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      ))}

      {dados.antigos.length > 0 && (
        <section aria-label="Avisos antigos" style={{ marginTop: 22 }}>
          <div className="au-titulo-grupo"><h3 style={{ fontSize: 11 }}>Antigos</h3><span>fora da lista atual (genéricos ou que não existem mais). Salvar em "Gerenciar" desliga; apague para não duplicar.</span></div>
          <div className="lst"><table><tbody>{dados.antigos.map((a) => (
            <tr key={a.tipo_evento}><td className="t">{a.nome}</td><td className="s mono">{a.tipo_evento}</td><td><span className={`chip ${a.habilitada ? "warn" : ""}`}>{a.habilitada ? "ligado" : "desligado"}</span></td>
              <td style={{ textAlign: "right" }}><button type="button" className="btn sm bad" disabled={ocupado} onClick={() => apagarAntigo(a)}><Trash2 />Apagar</button></td></tr>
          ))}</tbody></table></div>
        </section>
      )}

      {janela === "numero" && <JanelaNumero dados={dados} aoFechar={() => setJanela(null)} aoSalvar={recarregar} />}
      {janela === "pessoas" && <JanelaPessoas dados={dados} aoFechar={() => setJanela(null)} aoSalvar={recarregar} />}
      {janela === "gerenciar" && <JanelaGerenciar dados={dados} itens={itens} aoFechar={() => setJanela(null)} aoSalvar={recarregar} />}
      {editando && <JanelaMensagem dados={dados} item={editando.item} aoFechar={() => setEditando(null)} aoSalvar={recarregar} />}
    </>
  );
}

function Topo() {
  return (
    <>
      <Link className="btn ghost sm" to="/ferramentas" style={{ marginBottom: 10 }}><ArrowLeft />Ferramentas</Link>
      <div className="av-cab">
        <span className="au-icone" style={{ "--au-cor": "#2563EB" } as CSSProperties}><Bell /></span>
        <div><h1>Avisos no WhatsApp</h1><p>Receba um aviso no seu WhatsApp quando algo importante acontecer com um cliente.</p></div>
      </div>
    </>
  );
}

// --------------------------------------------------------------------------- 1. número de envio
function JanelaNumero({ dados, aoFechar, aoSalvar }: { dados: Dados; aoFechar: () => void; aoSalvar: () => Promise<void> | void }) {
  const { ocupado, executar } = useAcao();
  const escolher = (id: string) => executar(async () => {
    await enviar("/avisos/conta", { numero_envio: id }, "PUT");
    await aoSalvar();
    aoFechar();
  }, "Número de envio salvo.");
  return (
    <Modal titulo="Número de envio" texto="Os avisos saem deste WhatsApp da sua conta. Número oficial não serve: o WhatsApp só permite mensagens aprovadas."
      aoFechar={aoFechar} rodape={<><span className="sp" /><button className="btn" onClick={aoFechar}>Fechar</button></>}>
      {dados.canais.length === 0 ? <Vazio icone={<Phone />}>Nenhum número na conta. Conecte um WhatsApp em <Link to="/integracoes">Integrações</Link>.</Vazio> : (
        <div className="av-canais">
          {dados.canais.map((c) => {
            const atual = dados.numero_envio?.id === c.id;
            return (
              <button key={c.id} type="button" className={`av-canal ${atual ? "on" : ""}`} disabled={!c.pode_enviar || ocupado} onClick={() => !atual && escolher(c.id)}
                title={c.oficial ? "Número oficial: o WhatsApp só permite mensagens aprovadas; escolha um número não oficial." : undefined}>
                <span className="au-icone" style={{ width: 32, height: 32, "--au-cor": c.oficial ? "#94A3B8" : "#00A32C" } as CSSProperties}><Phone size={15} /></span>
                <span><b className="mono">{formatarTelefone(c.numero)}</b>
                  <small>{c.oficial ? "Número oficial: o WhatsApp só permite mensagens aprovadas; escolha um número não oficial."
                    : [c.nome, c.agente ? `agente ${c.agente}` : null, c.ativo ? null : "desconectado"].filter(Boolean).join(" · ") || "WhatsApp"}</small></span>
                <span className={`chip ${c.oficial ? "" : "ok"}`}>{c.oficial ? "Oficial" : "Não oficial"}</span>
                {atual && <Check size={16} style={{ color: "var(--acento)" }} />}
              </button>
            );
          })}
        </div>
      )}
    </Modal>
  );
}

// --------------------------------------------------------------------------- 2. quem recebe
function JanelaPessoas({ dados, aoFechar, aoSalvar }: { dados: Dados; aoFechar: () => void; aoSalvar: () => Promise<void> | void }) {
  const { ocupado, executar } = useAcao();
  const [lista, setLista] = useState<Pessoa[]>(dados.destinatarios);
  const [nome, setNome] = useState("");
  const [numero, setNumero] = useState("");
  const [editandoNumero, setEditandoNumero] = useState<string | null>(null);
  const [busca, setBusca] = useState("");
  const campoNome = useRef<HTMLInputElement>(null);
  const gravar = (nova: Pessoa[], aviso: string) => executar(async () => {
    await enviar("/avisos/conta", { destinatarios: nova }, "PUT");
    setLista(nova);
    await aoSalvar();
    return true;
  }, aviso);
  const adicionar = async () => {
    const digitos = numero.replace(/\D/g, "");
    if (digitos.length < 10) return;
    const limpo = digitos.length <= 11 ? `55${digitos}` : digitos;      // mesma regra do servidor (DDI 55 quando falta)
    const pessoa = { rotulo: nome.trim() || formatarTelefone(limpo), numero: limpo };
    const nova = editandoNumero ? lista.map((p) => (p.numero === editandoNumero ? pessoa : p)) : [...lista, pessoa];
    const ok = await gravar(nova, editandoNumero ? "Pessoa atualizada." : "Pessoa adicionada.");
    if (ok !== undefined) { setNome(""); setNumero(""); setEditandoNumero(null); campoNome.current?.focus(); }
  };
  const termo = busca.trim().toLowerCase();
  const visiveis = lista.filter((p) => !termo || p.rotulo.toLowerCase().includes(termo) || p.numero.includes(termo.replace(/\D/g, "") || "§"));
  return (
    <Modal titulo="Quem recebe os avisos" texto="As pessoas aqui recebem os avisos no WhatsApp. Vale para todos os avisos da conta." largura={620}
      aoFechar={aoFechar} rodape={<><span className="sp" /><button className="btn" onClick={aoFechar}>Fechar</button></>}>
      <div className="form">
        <div className="av-passo" style={{ background: "var(--surface-2)" }}>
          <b style={{ fontSize: 13.5 }}>{editandoNumero ? "Editar pessoa" : "Adicionar pessoa"}</b>
          <div className="form cols">
            <label className="field"><span className="lbl">Tipo</span><select disabled value="phone"><option value="phone">Um número de WhatsApp</option></select></label>
            <label className="field"><span className="lbl">Nome</span><input ref={campoNome} placeholder="Ex: João — Comercial" value={nome} onChange={(e) => setNome(e.target.value)} /></label>
          </div>
          <label className="field"><span className="lbl">WhatsApp com DDD (e DDI, se não for do Brasil)</span>
            <input inputMode="tel" placeholder="+55 11 99999-9999" value={numero} onChange={(e) => setNumero(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") adicionar(); }} /></label>
          {dados.numero_envio && <span className="ajuda">O número que envia ({formatarTelefone(dados.numero_envio.numero)}) não pode receber.</span>}
          <div style={{ display: "flex", gap: 8 }}>
            <button type="button" className="btn pri sm" disabled={ocupado || numero.replace(/\D/g, "").length < 10} onClick={adicionar}>{editandoNumero ? <><Check />Salvar</> : <><Plus />Adicionar</>}</button>
            {editandoNumero && <button type="button" className="btn sm" onClick={() => { setEditandoNumero(null); setNome(""); setNumero(""); }}>Cancelar</button>}
          </div>
        </div>
        <div className="au-barra" style={{ margin: 0 }}>
          <b style={{ fontSize: 13.5 }}>Recebem os avisos ({lista.length})</b><span className="sp" />
          {lista.length > 4 && <label className="au-busca" style={{ maxWidth: 220 }}><Search /><input className="inp" placeholder="Buscar" aria-label="Buscar pessoa" value={busca} onChange={(e) => setBusca(e.target.value)} /></label>}
        </div>
        {lista.length === 0 ? <Vazio icone={<UserRound />}>Ninguém ainda. Adicione a primeira pessoa acima.</Vazio> : (
          <div className="av-lista-pessoas">
            {visiveis.map((p) => (
              <div key={p.numero}>
                <span className="au-icone" style={{ width: 30, height: 30, "--au-cor": "#00A32C" } as CSSProperties}><Phone size={14} /></span>
                <span className="av-quem"><b>{p.rotulo}</b><small>WhatsApp · <span className="mono">{formatarTelefone(p.numero)}</span></small></span>
                <button type="button" className="btn ghost sm" aria-label={`Editar ${p.rotulo}`} onClick={() => { setEditandoNumero(p.numero); setNome(p.rotulo); setNumero(p.numero); campoNome.current?.focus(); }}><Pencil /></button>
                <button type="button" className="btn ghost sm" aria-label={`Tirar ${p.rotulo}`} disabled={ocupado} onClick={() => gravar(lista.filter((x) => x.numero !== p.numero), "Pessoa removida.")}><X /></button>
              </div>
            ))}
          </div>
        )}
      </div>
    </Modal>
  );
}

// --------------------------------------------------------------------------- 3. gerenciar avisos
function JanelaGerenciar({ dados, itens, aoFechar, aoSalvar }: { dados: Dados; itens: (Item & { grupo: string })[]; aoFechar: () => void; aoSalvar: () => Promise<void> | void }) {
  const { ocupado, executar } = useAcao();
  const [marcados, setMarcados] = useState<Set<string>>(() => new Set(itens.filter((i) => i.ligado).map((i) => i.chave)));
  const [busca, setBusca] = useState("");
  const termo = busca.trim().toLowerCase();
  const visiveis = itens.filter((i) => !termo || i.nome.toLowerCase().includes(termo) || i.descricao.toLowerCase().includes(termo));
  const todos = visiveis.length > 0 && visiveis.every((i) => marcados.has(i.chave));
  const marcar = (chave: string) => setMarcados((m) => { const n = new Set(m); if (n.has(chave)) n.delete(chave); else n.add(chave); return n; });
  const salvar = () => executar(async () => {
    await enviar("/avisos/ligados", { ligados: [...marcados] }, "PUT");
    await aoSalvar();
    aoFechar();
  }, "Avisos salvos.");
  return (
    <Modal titulo="Gerenciar avisos" largura={640}
      texto="Marque pra ligar, desmarque pra desligar. Reflete o que está ativo no painel e usa quem recebe + o número da conta."
      aoFechar={aoFechar} rodape={<>
        <span className="muted" style={{ fontSize: 12.5 }}>{marcados.size} ligado(s) · {dados.destinatarios.length} destinatário{dados.destinatarios.length === 1 ? "" : "s"}</span>
        <span className="sp" />
        <button className="btn" onClick={aoFechar}>Cancelar</button>
        <button className="btn pri" disabled={ocupado} onClick={salvar}>Salvar</button>
      </>}>
      <div className="form">
        <div className="au-barra" style={{ margin: 0 }}>
          <label className="au-busca" style={{ maxWidth: "none" }}><Search /><input className="inp" placeholder="Buscar aviso…" aria-label="Buscar aviso" value={busca} onChange={(e) => setBusca(e.target.value)} /></label>
          <button type="button" className="btn sm" onClick={() => setMarcados((m) => {
            const n = new Set(m); visiveis.forEach((i) => (todos ? n.delete(i.chave) : n.add(i.chave))); return n;
          })}>{todos ? "Desmarcar tudo" : "Marcar tudo"}</button>
        </div>
        <div className="av-opcoes">
          {visiveis.map((i) => {
            const Icone = ICONES[i.icone] ?? Bell;
            return (
              <label key={i.chave} className="av-opcao">
                <input type="checkbox" checked={marcados.has(i.chave)} onChange={() => marcar(i.chave)} />
                <span className="au-icone" style={{ "--au-cor": corDo(i.grupo, i) } as CSSProperties}><Icone /></span>
                <span style={{ flex: 1, minWidth: 0 }}>{i.nome} <small>• Mensagem pronta</small></span>
              </label>
            );
          })}
          {visiveis.length === 0 && <div className="av-opcao muted">Nenhum aviso com esse nome.</div>}
        </div>
      </div>
    </Modal>
  );
}

// --------------------------------------------------------------------------- editar mensagem
function JanelaMensagem({ dados, item, aoFechar, aoSalvar }: { dados: Dados; item: Item; aoFechar: () => void; aoSalvar: () => Promise<void> | void }) {
  const { ocupado, executar } = useAcao();
  const avisar = useAvisar();
  const [nome, setNome] = useState(item.nome_interno);
  const [texto, setTexto] = useState(item.modelo);
  const campo = useRef<HTMLTextAreaElement>(null);
  const inserir = (chave: string) => {
    const el = campo.current;
    const marca = `{{${chave}}}`;
    if (!el) { setTexto((t) => t + marca); return; }
    const ini = el.selectionStart ?? texto.length;
    const fim = el.selectionEnd ?? texto.length;
    setTexto(texto.slice(0, ini) + marca + texto.slice(fim));
    requestAnimationFrame(() => { el.focus(); el.setSelectionRange(ini + marca.length, ini + marca.length); });
  };
  const salvar = () => executar(async () => {
    await enviar(`/avisos/item/${item.chave}`, { modelo: texto, nome: nome.trim() || item.nome }, "PUT");
    await aoSalvar();
    aoFechar();
  }, "Mensagem salva.");
  const testar = () => executar(async () => {
    const r = await api<{ enfileirados: number }>(`/avisos/item/${item.chave}/teste`, { metodo: "POST" });
    avisar(`Teste na fila para ${r.enfileirados} ${r.enfileirados === 1 ? "pessoa" : "pessoas"}.`);
  });
  const alterado = texto !== item.modelo || nome !== item.nome_interno;
  return (
    <Modal titulo={`Editar mensagem — ${item.nome}`} largura={920} aoFechar={aoFechar} rodape={<>
      <button className="btn ghost sm" type="button" onClick={() => setTexto(item.modelo_padrao)} disabled={texto === item.modelo_padrao}><RotateCcw />Texto padrão</button>
      <button className="btn ghost sm" type="button" onClick={testar} disabled={ocupado || alterado || !item.configurado || dados.destinatarios.length === 0}
        title={alterado ? "Salve antes de testar" : !item.configurado ? "Salve ou ligue o aviso antes de testar" : "Manda com dados de exemplo para quem recebe"}><Send />Enviar teste</button>
      <span className="sp" />
      <button className="btn" onClick={aoFechar}>Cancelar</button>
      <button className="btn pri" disabled={ocupado || texto.trim().length < 3} onClick={salvar}>Salvar mensagem</button>
    </>}>
      <div className="form">
        <label className="field"><span className="lbl">Nome do aviso (uso interno)</span><input value={nome} onChange={(e) => setNome(e.target.value)} maxLength={120} /></label>
        <div className="field"><span className="lbl">Toque para inserir um dado do cliente</span>
          <div className="av-chips">{dados.marcadores.map((m) => <button key={m.chave} type="button" onClick={() => inserir(m.chave)}>+ {m.rotulo}</button>)}</div></div>
        <div className="av-editor">
          <label className="field"><span className="lbl">Texto do aviso</span>
            <textarea ref={campo} className="codigo" rows={14} value={texto} onChange={(e) => setTexto(e.target.value)} />
            <span className="ajuda">*negrito*, _itálico_, ~riscado~, `destaque`, "&gt; " no começo da linha vira citação. Linha com dado vazio não aparece.</span></label>
          <BalaoWhatsApp texto={renderizar(texto, dados.exemplo)} />
        </div>
      </div>
    </Modal>
  );
}
