import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft, CheckCircle2, Copy, FileAudio, Mic, Plus, RotateCcw, Save, Search, Square, Trash2, Unlink, Upload,
} from "lucide-react";
import { api, enviar, quando } from "../api";
import { Alerta, Cabecalho, Carregando, Modal, Painel, Vazio, useAcao, useAvisar, useCarregar, useConfirmar } from "../componentes/ui";
import { arquivoParaBase64 } from "@/lib/base64";
import "../estilo-ferramentas.css";

// --------------------------------------------------------------------------- tipos
export interface Roteiro {
  id: string; titulo: string; texto: string; status: "a_gravar" | "gravado";
  id_agente: string | null; agente_nome: string | null; etapa: string | null; etapa_nome: string | null;
  id_produto_ativado: string | null; produto_nome: string | null; id_midia: string | null;
  midia: { id: string; nome: string; url: string; mime_type: string | null; tamanho_bytes: number | null; criado_em: string } | null;
  criado_em: string; atualizado_em: string;
}
interface Opcoes {
  agentes: { id: string; nome: string; etapas: { codigo: string; nome: string }[] }[];
  produtos: { id: string; nome: string }[];
}

const NOME_STATUS = { a_gravar: "A gravar", gravado: "Gravado" } as const;
const tokenDaMidia = (r: Roteiro) => (r.midia ? `[audio:${r.midia.nome}](${r.midia.url})` : "");
const fmtBytes = (b: number) => (b >= 1024 * 1024 ? `${(b / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`);
const fmtTempo = (s: number) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

function ChipStatus({ status }: { status: Roteiro["status"] }) {
  return status === "gravado"
    ? <span className="chip ok"><span className="d" /> Gravado</span>
    : <span className="chip warn"><span className="d" /> A gravar</span>;
}

function Destino({ r }: { r: Roteiro }) {
  const partes = [r.produto_nome, r.agente_nome, r.etapa_nome].filter(Boolean);
  return partes.length ? <span className="chip">{partes.join(" · ")}</span> : null;
}

// --------------------------------------------------------------------------- lista
export function TelaRoteiros() {
  const navegar = useNavigate();
  const { dados, erro, recarregar } = useCarregar<Roteiro[]>("/roteiros");
  const [busca, setBusca] = useState("");
  const [filtro, setFiltro] = useState<"todos" | Roteiro["status"]>("todos");
  const [novo, setNovo] = useState(false);

  const lista = (dados ?? []).filter((r) => (filtro === "todos" || r.status === filtro)
    && (!busca.trim() || `${r.titulo} ${r.texto}`.toLowerCase().includes(busca.trim().toLowerCase())));
  const contar = (s: Roteiro["status"]) => (dados ?? []).filter((r) => r.status === s).length;

  return (
    <>
      <Cabecalho eyebrow="Ferramentas" titulo="Roteiros de áudio"
        texto="Escreva o texto que alguém da equipe vai gravar. Grave pelo navegador ou envie o áudio: ele entra na Biblioteca de Mídia, pronto para inserir no prompt."
        acoes={<>
          <Link to="/ferramentas" className="btn ghost"><ArrowLeft /> Ferramentas</Link>
          <button type="button" className="btn pri" onClick={() => setNovo(true)}><Plus /> Novo roteiro</button>
        </>} />

      {!dados ? <Carregando erro={erro} /> : (
        <>
          {dados.length > 0 && (
            <div className="rot-barra">
              <div style={{ position: "relative", flex: "1 1 240px", maxWidth: 360 }}>
                <Search size={15} style={{ position: "absolute", left: 11, top: "50%", transform: "translateY(-50%)", color: "var(--ink-3)" }} />
                <input className="inp" style={{ paddingLeft: 32, maxWidth: "none" }} placeholder="Buscar no título ou no texto" value={busca}
                  onChange={(e) => setBusca(e.target.value)} aria-label="Buscar roteiro" />
              </div>
              <div className="rot-filtros" role="tablist" aria-label="Filtrar por situação">
                <button type="button" role="tab" aria-selected={filtro === "todos"} className={filtro === "todos" ? "on" : ""} onClick={() => setFiltro("todos")}>Todos {dados.length}</button>
                <button type="button" role="tab" aria-selected={filtro === "a_gravar"} className={filtro === "a_gravar" ? "on" : ""} onClick={() => setFiltro("a_gravar")}>A gravar {contar("a_gravar")}</button>
                <button type="button" role="tab" aria-selected={filtro === "gravado"} className={filtro === "gravado" ? "on" : ""} onClick={() => setFiltro("gravado")}>Gravados {contar("gravado")}</button>
              </div>
            </div>
          )}
          {dados.length === 0 ? (
            <Painel>
              <Vazio icone={<Mic />}>
                <b style={{ color: "var(--ink)" }}>Nenhum roteiro ainda</b>
                <div style={{ marginTop: 4 }}>Crie o primeiro: escreva o texto, grave pelo navegador e use o áudio no prompt.</div>
                <button type="button" className="btn pri" style={{ marginTop: 12 }} onClick={() => setNovo(true)}><Plus /> Novo roteiro</button>
              </Vazio>
            </Painel>
          ) : lista.length === 0 ? (
            <Painel><Vazio>Nenhum roteiro com esse filtro.</Vazio></Painel>
          ) : (
            <div className="rot-grade">
              {lista.map((r) => (
                <div key={r.id} className="rot-card">
                  <div className="rot-meta"><ChipStatus status={r.status} /><Destino r={r} /></div>
                  <Link to={`/ferramentas/roteiros/${r.id}`} style={{ color: "var(--ink)", textDecoration: "none" }}><b>{r.titulo}</b></Link>
                  <p className="rot-trecho">{r.texto || <span className="muted">Sem texto ainda.</span>}</p>
                  {r.midia && <audio src={r.midia.url} controls preload="none" />}
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span className="muted" style={{ fontSize: 12 }}>Atualizado {quando(r.atualizado_em)}</span>
                    <span style={{ flex: 1 }} />
                    <Link to={`/ferramentas/roteiros/${r.id}`} className="btn sm">{r.status === "gravado" ? "Abrir" : <><Mic /> Gravar</>}</Link>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
      {novo && <NovoRoteiro aoFechar={() => setNovo(false)} aoCriar={(r) => { recarregar(); navegar(`/ferramentas/roteiros/${r.id}`); }} />}
    </>
  );
}

function NovoRoteiro({ aoFechar, aoCriar }: { aoFechar: () => void; aoCriar: (r: Roteiro) => void }) {
  const [titulo, setTitulo] = useState("");
  const [texto, setTexto] = useState("");
  const { ocupado, executar } = useAcao();
  const criar = async () => {
    const r = await executar(() => enviar<Roteiro>("/roteiros", { titulo: titulo.trim(), texto }), "Roteiro criado");
    if (r) { aoFechar(); aoCriar(r); }
  };
  return (
    <Modal titulo="Novo roteiro" texto="Dê um nome e escreva (ou cole) o texto. Dá para ajustar depois." aoFechar={aoFechar} largura={560}
      rodape={<><span className="sp" /><button className="btn ghost" onClick={aoFechar}>Cancelar</button>
        <button className="btn pri" disabled={ocupado || !titulo.trim()} onClick={criar}>Criar e abrir</button></>}>
      <div className="form">
        <div className="field"><label htmlFor="rot-titulo">Título</label>
          <input id="rot-titulo" value={titulo} maxLength={200} onChange={(e) => setTitulo(e.target.value)} placeholder="Ex.: Explicação dos honorários"
            onKeyDown={(e) => { if (e.key === "Enter" && titulo.trim()) criar(); }} />
        </div>
        <div className="field"><label htmlFor="rot-texto">Texto para gravar</label>
          <textarea id="rot-texto" rows={7} value={texto} onChange={(e) => setTexto(e.target.value)} placeholder="Olá! Aqui é do escritório..." />
        </div>
      </div>
    </Modal>
  );
}

// --------------------------------------------------------------------------- um roteiro
export function TelaRoteiro() {
  const { id = "" } = useParams();
  const navegar = useNavigate();
  const avisar = useAvisar();
  const { dados, erro, setDados } = useCarregar<Roteiro>(`/roteiros/${id}`, [id]);
  const { dados: opcoes } = useCarregar<Opcoes>("/roteiros/opcoes");
  const [form, setForm] = useState<{ titulo: string; texto: string; id_agente: string; etapa: string; id_produto_ativado: string } | null>(null);
  const { ocupado, executar } = useAcao();
  const [confirmar, janela] = useConfirmar();

  useEffect(() => {
    if (dados && !form) setForm({ titulo: dados.titulo, texto: dados.texto, id_agente: dados.id_agente ?? "", etapa: dados.etapa ?? "", id_produto_ativado: dados.id_produto_ativado ?? "" });
  }, [dados, form]);

  if (!dados || !form) return <><Cabecalho eyebrow="Roteiros" titulo="Roteiro" /><Carregando erro={erro} /></>;

  const mudou = form.titulo !== dados.titulo || form.texto !== dados.texto || form.id_agente !== (dados.id_agente ?? "")
    || form.etapa !== (dados.etapa ?? "") || form.id_produto_ativado !== (dados.id_produto_ativado ?? "");
  const agente = opcoes?.agentes.find((a) => a.id === form.id_agente);
  const palavras = form.texto.trim() ? form.texto.trim().split(/\s+/).length : 0;

  const salvar = async () => {
    const r = await executar(() => enviar<Roteiro>(`/roteiros/${id}`, form, "PATCH"), "Roteiro salvo");
    if (r) setDados(r);
  };
  const apagar = async () => {
    if (!(await confirmar({ titulo: "Apagar este roteiro?", texto: "O áudio gravado continua na Biblioteca de Mídia.", confirmar: "Apagar", perigo: true }))) return;
    const ok = await executar(() => api(`/roteiros/${id}`, { metodo: "DELETE" }), "Roteiro apagado");
    if (ok) navegar("/ferramentas/roteiros");
  };
  const mudarStatus = async (status: Roteiro["status"]) => {
    const r = await executar(() => enviar<Roteiro>(`/roteiros/${id}`, { status }, "PATCH"));
    if (r) setDados(r);
  };

  return (
    <>
      <Cabecalho eyebrow="Roteiros" titulo={dados.titulo}
        texto={<span style={{ display: "inline-flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}><ChipStatus status={dados.status} /><Destino r={dados} /></span>}
        acoes={<>
          <Link to="/ferramentas/roteiros" className="btn ghost"><ArrowLeft /> Roteiros</Link>
          <button type="button" className="btn bad" onClick={apagar} disabled={ocupado}><Trash2 /> Apagar</button>
          <button type="button" className="btn pri" onClick={salvar} disabled={ocupado || !mudou || !form.titulo.trim()}><Save /> Salvar</button>
        </>} />

      <div className="rot-editor">
        <div className="stack">
          <Painel titulo="Texto">
            <div className="form">
              <div className="field"><label htmlFor="rt-titulo">Título</label>
                <input id="rt-titulo" value={form.titulo} maxLength={200} onChange={(e) => setForm({ ...form, titulo: e.target.value })} />
              </div>
              <div className="field rot-texto"><label htmlFor="rt-texto">Texto para gravar</label>
                <textarea id="rt-texto" value={form.texto} onChange={(e) => setForm({ ...form, texto: e.target.value })}
                  placeholder="Escreva como a pessoa vai falar: frases curtas, tom de conversa." />
                <span className="rot-dica">{palavras} palavras · cerca de {fmtTempo(Math.round((palavras / 150) * 60))} de fala</span>
              </div>
            </div>
          </Painel>
          <Painel titulo="Para quem é (opcional)">
            <div className="form cols">
              <div className="field"><label htmlFor="rt-produto">Produto</label>
                <select id="rt-produto" value={form.id_produto_ativado} onChange={(e) => setForm({ ...form, id_produto_ativado: e.target.value })}>
                  <option value="">Nenhum</option>
                  {opcoes?.produtos.map((p) => <option key={p.id} value={p.id}>{p.nome}</option>)}
                </select>
              </div>
              <div className="field"><label htmlFor="rt-agente">Agente</label>
                <select id="rt-agente" value={form.id_agente} onChange={(e) => setForm({ ...form, id_agente: e.target.value, etapa: "" })}>
                  <option value="">Nenhum</option>
                  {opcoes?.agentes.map((a) => <option key={a.id} value={a.id}>{a.nome}</option>)}
                </select>
              </div>
              <div className="field"><label htmlFor="rt-etapa">Etapa</label>
                <select id="rt-etapa" value={form.etapa} disabled={!agente} onChange={(e) => setForm({ ...form, etapa: e.target.value })}>
                  <option value="">{agente ? "Qualquer etapa" : "Escolha o agente"}</option>
                  {agente?.etapas.map((e) => <option key={e.codigo} value={e.codigo}>{e.nome}</option>)}
                  {form.etapa && agente && !agente.etapas.some((e) => e.codigo === form.etapa) && <option value={form.etapa}>{dados.etapa_nome ?? form.etapa}</option>}
                </select>
              </div>
            </div>
          </Painel>
        </div>

        <Painel titulo="Áudio" acoes={dados.midia
          ? <select className="inp" style={{ width: "auto", padding: "4px 8px", fontSize: 12.5 }} value={dados.status} aria-label="Situação do roteiro"
              onChange={(e) => mudarStatus(e.target.value as Roteiro["status"])}>
              <option value="gravado">{NOME_STATUS.gravado}</option><option value="a_gravar">{NOME_STATUS.a_gravar}</option>
            </select>
          : undefined}>
          <AudioDoRoteiro roteiro={dados} aoMudar={(r) => { setDados(r); }} avisar={avisar} confirmar={confirmar} />
        </Painel>
      </div>
      {janela}
    </>
  );
}

// --------------------------------------------------------------------------- gravação
const TIPOS_GRAVACAO = ["audio/ogg;codecs=opus", "audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
const MAX_SEGUNDOS = 10 * 60;

function AudioDoRoteiro({ roteiro, aoMudar, avisar, confirmar }: {
  roteiro: Roteiro; aoMudar: (r: Roteiro) => void; avisar: (t: string, tipo?: "ok" | "bad") => void;
  confirmar: ReturnType<typeof useConfirmar>[0];
}) {
  const suportado = typeof window !== "undefined" && typeof window.MediaRecorder !== "undefined" && !!navigator.mediaDevices?.getUserMedia;
  const [gravando, setGravando] = useState(false);
  const [segundos, setSegundos] = useState(0);
  const [nivel, setNivel] = useState(0);
  const [previa, setPrevia] = useState<{ blob: Blob; url: string; segundos: number } | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [erroMic, setErroMic] = useState<string | null>(null);
  const gravador = useRef<MediaRecorder | null>(null);
  const fluxo = useRef<MediaStream | null>(null);
  const contexto = useRef<AudioContext | null>(null);
  const relogio = useRef<number | null>(null);
  const quadro = useRef<number | null>(null);
  const arquivo = useRef<HTMLInputElement>(null);

  const limpar = () => {
    if (relogio.current) window.clearInterval(relogio.current);
    if (quadro.current) cancelAnimationFrame(quadro.current);
    relogio.current = quadro.current = null;
    fluxo.current?.getTracks().forEach((t) => t.stop());
    fluxo.current = null;
    contexto.current?.close().catch(() => {});
    contexto.current = null;
    setNivel(0);
  };
  useEffect(() => () => { if (gravador.current?.state === "recording") gravador.current.stop(); limpar(); }, []);
  useEffect(() => () => { if (previa) URL.revokeObjectURL(previa.url); }, [previa]);

  const comecar = async () => {
    setErroMic(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      fluxo.current = stream;
      const mime = TIPOS_GRAVACAO.find((t) => MediaRecorder.isTypeSupported?.(t)) ?? "";
      const rec = new MediaRecorder(stream, mime ? { mimeType: mime, audioBitsPerSecond: 48000 } : undefined);
      const partes: Blob[] = [];
      rec.ondataavailable = (e) => { if (e.data.size) partes.push(e.data); };
      rec.onstop = () => {
        const tipo = rec.mimeType || mime || "audio/webm";
        const blob = new Blob(partes, { type: tipo });
        setPrevia((p) => { if (p) URL.revokeObjectURL(p.url); return { blob, url: URL.createObjectURL(blob), segundos: tempo.current }; });
        setGravando(false);
        limpar();
      };
      // Nível do microfone (só para a pessoa ver que está captando).
      try {
        const ctx = new AudioContext();
        const analisador = ctx.createAnalyser();
        analisador.fftSize = 512;
        ctx.createMediaStreamSource(stream).connect(analisador);
        contexto.current = ctx;
        const buf = new Uint8Array(analisador.fftSize);
        const medir = () => {
          analisador.getByteTimeDomainData(buf);
          let pico = 0;
          for (const v of buf) pico = Math.max(pico, Math.abs(v - 128));
          setNivel(Math.min(1, pico / 90));
          quadro.current = requestAnimationFrame(medir);
        };
        medir();
      } catch { /* sem medidor: grava do mesmo jeito */ }
      gravador.current = rec;
      tempo.current = 0;
      setSegundos(0);
      rec.start(1000);
      setGravando(true);
      relogio.current = window.setInterval(() => {
        tempo.current += 1;
        setSegundos(tempo.current);
        if (tempo.current >= MAX_SEGUNDOS) parar();
      }, 1000);
    } catch (e) {
      limpar();
      const nome = (e as DOMException)?.name;
      setErroMic(nome === "NotAllowedError" ? "O navegador não deixou usar o microfone. Libere o acesso no cadeado da barra de endereço e tente de novo."
        : nome === "NotFoundError" ? "Nenhum microfone encontrado neste computador." : "Não deu para começar a gravar.");
    }
  };
  const tempo = useRef(0);
  const parar = () => { if (gravador.current?.state === "recording") gravador.current.stop(); };

  const subir = async (blob: Blob, nome?: string) => {
    setEnviando(true);
    try {
      const r = await enviar<Roteiro>(`/roteiros/${roteiro.id}/audio`, { conteudo_base64: await arquivoParaBase64(blob), mime: blob.type, nome });
      aoMudar(r);
      setPrevia(null);
      avisar("Áudio salvo na Biblioteca de Mídia");
    } catch (e) {
      avisar((e as Error).message, "bad");
    } finally {
      setEnviando(false);
    }
  };
  const escolherArquivo = async (f: File | undefined) => {
    if (arquivo.current) arquivo.current.value = "";
    if (!f) return;
    const ext = f.name.toLowerCase().split(".").pop() ?? "";
    if (!["ogg", "oga", "opus", "mp3", "m4a", "webm"].includes(ext)) { avisar("Use áudio .ogg/.opus (chega como mensagem de voz), .mp3 ou .m4a.", "bad"); return; }
    if (f.size > 16 * 1024 * 1024) { avisar("Áudio grande demais: o limite é 16 MB.", "bad"); return; }
    if (roteiro.midia && !(await confirmar({ titulo: "Trocar o áudio?", texto: "O áudio atual sai da biblioteca (se nenhum prompt usar).", confirmar: "Trocar" }))) return;
    subir(f, f.name);
  };
  const usarGravacao = async () => {
    if (!previa) return;
    if (roteiro.midia && !(await confirmar({ titulo: "Trocar o áudio?", texto: "O áudio atual sai da biblioteca (se nenhum prompt usar).", confirmar: "Trocar" }))) return;
    subir(previa.blob);
  };
  const soltar = async () => {
    if (!(await confirmar({ titulo: "Tirar o áudio deste roteiro?", texto: "O arquivo continua na Biblioteca de Mídia; o roteiro volta para \"a gravar\".", confirmar: "Tirar" }))) return;
    try { aoMudar(await api<Roteiro>(`/roteiros/${roteiro.id}/audio`, { metodo: "DELETE" })); } catch (e) { avisar((e as Error).message, "bad"); }
  };

  return (
    <div className="rot-gravador">
      {roteiro.midia && !previa && !gravando && (
        <div className="rot-previa">
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <CheckCircle2 size={16} style={{ color: "var(--ok)" }} />
            <b style={{ fontSize: 13, flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{roteiro.midia.nome}</b>
            <span className="muted mono" style={{ fontSize: 11 }}>{fmtBytes(roteiro.midia.tamanho_bytes ?? 0)}</span>
          </div>
          <audio src={roteiro.midia.url} controls preload="metadata" />
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            <button type="button" className="btn sm" onClick={() => { navigator.clipboard.writeText(tokenDaMidia(roteiro)); avisar("Referência copiada: cole no prompt"); }}><Copy /> Copiar para o prompt</button>
            <button type="button" className="btn sm ghost" onClick={soltar}><Unlink /> Tirar do roteiro</button>
          </div>
          <span className="rot-dica">Já está na Biblioteca de Mídia: no editor do agente, use Inserir mídia para colocar no prompt.</span>
        </div>
      )}

      {!suportado ? (
        <Alerta tipo="warn">Este navegador não grava áudio. Use o Chrome, o Edge ou o Firefox, ou envie o arquivo abaixo.</Alerta>
      ) : previa && !gravando ? (
        <div className="rot-previa">
          <b style={{ fontSize: 13 }}>Nova gravação · {fmtTempo(previa.segundos)}</b>
          <audio src={previa.url} controls />
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            <button type="button" className="btn pri sm" disabled={enviando} onClick={usarGravacao}><CheckCircle2 /> {enviando ? "Salvando…" : "Usar esta gravação"}</button>
            <button type="button" className="btn sm" disabled={enviando} onClick={() => setPrevia(null)}><RotateCcw /> Descartar</button>
          </div>
        </div>
      ) : (
        <>
          <button type="button" className={`rot-mic ${gravando ? "gravando" : ""}`} onClick={gravando ? parar : comecar} disabled={enviando}
            aria-label={gravando ? "Parar gravação" : "Começar a gravar"}>
            {gravando ? <Square /> : <Mic />}
          </button>
          {gravando
            ? <div className="rot-tempo" aria-live="polite">{fmtTempo(segundos)}</div>
            : <div style={{ textAlign: "center", fontWeight: 600, fontSize: 14 }}>{roteiro.midia ? "Gravar de novo" : "Toque no microfone para gravar"}<div className="rot-dica" style={{ fontWeight: 400, marginTop: 2 }}>O navegador vai pedir para usar o microfone.</div></div>}
          {gravando && <div className="rot-nivel" aria-hidden><i style={{ width: `${Math.round(nivel * 100)}%` }} /></div>}
          {gravando && <span className="rot-dica" style={{ textAlign: "center" }}>Leia o texto ao lado com calma. Toque no quadrado para parar (máx. 10 min).</span>}
        </>
      )}
      {erroMic && <Alerta tipo="bad">{erroMic}</Alerta>}

      <div className="rot-ou">ou</div>
      <input ref={arquivo} type="file" accept=".ogg,.oga,.opus,.mp3,.m4a,.webm,audio/*" hidden onChange={(e) => escolherArquivo(e.target.files?.[0])} />
      <button type="button" className="btn" style={{ justifyContent: "center" }} disabled={enviando || gravando} onClick={() => arquivo.current?.click()}>
        {enviando ? <FileAudio /> : <Upload />} {enviando ? "Enviando…" : "Enviar arquivo de áudio"}
      </button>
      <span className="rot-dica" style={{ textAlign: "center" }}>.ogg/.opus chega como mensagem de voz; .mp3 e .m4a chegam como arquivo de áudio. Até 16 MB.</span>
    </div>
  );
}
