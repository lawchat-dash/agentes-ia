// Ferramentas › Biblioteca de mídia (tela própria; antes era um pop-up). Os pop-ups de "Inserir mídia" dos editores
// de prompt continuam usando components/agent/MediaLibrary.tsx. Backend: /midia (GET lista + cota, POST envia,
// PATCH renomeia, DELETE apaga). Pastas: a coluna `pasta` ("Roteiros gravados/Auxílio-Acidente") vira cartões de pasta no
// topo, com navegação (trilha) ao entrar; arquivos sem pasta ficam na raiz como antes.
import { useMemo, useRef, useState, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, ChevronRight, Copy, Folder, FolderOpen, Image as ImageIcon, Mic, Music, Pencil, Search, Trash2, UploadCloud, Video } from "lucide-react";
import { api, enviar } from "../api";
import { Cabecalho, Carregando, Modal, Vazio, useAcao, useAvisar, useCarregar, useConfirmar } from "../componentes/ui";
import { useSessao } from "../sessao";
import { arquivoParaBase64 } from "@/lib/base64";
import { conteudoDaPasta, descreverPasta, nomeDaPasta, normalizarPasta, rotuloDaPasta, trilhaDaPasta } from "@/lib/pastasMidia";
import "../estilo-automacao.css";

interface ItemBruto { id: string; nome: string; tipo: string; url: string; mime_type: string | null; tamanho_bytes: number | null; created_at: string; pasta?: string | null }
interface Lista { itens: ItemBruto[]; usado_bytes: number; limite_bytes: number }
type Tipo = "audio" | "video" | "imagem";

const TIPO: Record<Tipo, { rotulo: string; cor: string; Icone: typeof Music; token: string }> = {
  audio: { rotulo: "Áudio", cor: "#7C3AED", Icone: Music, token: "audio" },
  video: { rotulo: "Vídeo", cor: "#2563EB", Icone: Video, token: "video" },
  imagem: { rotulo: "Imagem", cor: "#0E9F6E", Icone: ImageIcon, token: "image" },
};
const tipoDo = (t: string): Tipo => (t === "audio" || t === "video" ? t : "imagem");
const tamanho = (b: number) => (!b ? "0 KB" : b >= 1024 * 1024 ? `${(b / 1024 / 1024).toFixed(1).replace(".", ",")} MB` : `${Math.max(1, Math.round(b / 1024))} KB`);
const ACEITA = ".ogg,.oga,.opus,.mp3,.m4a,.mp4,.jpg,.jpeg,.png";

function tipoDoArquivo(nome: string): Tipo | null {
  const ext = nome.toLowerCase().split(".").pop() ?? "";
  if (["ogg", "oga", "opus", "mp3", "m4a"].includes(ext)) return "audio";
  if (ext === "mp4") return "video";
  if (["jpg", "jpeg", "png"].includes(ext)) return "imagem";
  return null;
}

export function TelaBibliotecaMidia() {
  const { escritorio } = useSessao();
  const { dados, erro, recarregar, setDados } = useCarregar<Lista>("/midia", [escritorio]);
  const roteiros = useCarregar<{ id_midia: string | null; titulo: string }[]>("/roteiros", [escritorio]);
  const avisar = useAvisar();
  const { ocupado, executar } = useAcao();
  const [confirmar, janelaConfirmar] = useConfirmar();
  const [filtro, setFiltro] = useState<"todos" | Tipo>("todos");
  const [texto, setTexto] = useState("");
  const [pasta, setPasta] = useState("");
  const [arrastando, setArrastando] = useState(false);
  const [enviando, setEnviando] = useState<string | null>(null);
  const [renomear, setRenomear] = useState<ItemBruto | null>(null);
  const [novoNome, setNovoNome] = useState("");
  const arquivo = useRef<HTMLInputElement>(null);

  const deRoteiro = useMemo(() => Object.fromEntries((roteiros.dados ?? []).filter((r) => r.id_midia).map((r) => [r.id_midia as string, r.titulo])), [roteiros.dados]);
  const itens = useMemo(() => (dados?.itens ?? []).slice().sort((a, b) => String(b.created_at).localeCompare(String(a.created_at))), [dados]);
  const termo = texto.trim().toLowerCase();
  const doTipo = itens.filter((i) => filtro === "todos" || tipoDo(i.tipo) === filtro);
  // Com busca, procura em todas as pastas (e o cartão mostra a pasta); sem busca, mostra o conteúdo da pasta aberta.
  const conteudo = conteudoDaPasta(doTipo, pasta, (i) => i.pasta, (i) => i.nome, (i) => i.created_at);
  const pastasVisiveis = termo ? [] : conteudo.pastas;
  const visiveis = termo
    ? doTipo.filter((i) => i.nome.toLowerCase().includes(termo) || (deRoteiro[i.id] ?? "").toLowerCase().includes(termo)
      || normalizarPasta(i.pasta).toLowerCase().includes(termo))
    : conteudo.arquivos;
  const trilha = trilhaDaPasta(pasta);
  const contagem = (t: "todos" | Tipo) => (t === "todos" ? itens.length : itens.filter((i) => tipoDo(i.tipo) === t).length);

  const usado = dados?.usado_bytes ?? 0;
  const limite = Math.max(1, dados?.limite_bytes ?? 1);
  const uso = Math.min(100, Math.round((100 * usado) / limite));

  const enviarArquivos = async (lista: FileList | null) => {
    if (!lista?.length) return;
    let livre = limite - usado;
    let enviados = 0;
    for (const f of Array.from(lista)) {
      const tipo = tipoDoArquivo(f.name);
      if (!tipo) { avisar(`Formato não aceito: ${f.name}. Use .ogg/.opus/.mp3/.m4a, .mp4, .jpg ou .png.`, "bad"); continue; }
      const maximo = tipo === "imagem" ? 5 : 16;
      if (f.size > maximo * 1024 * 1024) { avisar(`${f.name} passa de ${maximo} MB (limite do WhatsApp).`, "bad"); continue; }
      if (f.size > livre) { avisar(`${f.name} não cabe no espaço que sobrou (${tamanho(Math.max(0, livre))}).`, "bad"); continue; }
      setEnviando(f.name);
      try {
        await enviar("/midia", { nome: f.name, conteudo_base64: await arquivoParaBase64(f), mime: f.type || undefined });
        livre -= f.size;
        enviados += 1;
      } catch (e) {
        avisar(`Falha ao enviar ${f.name}: ${(e as Error).message}`, "bad");
      }
    }
    setEnviando(null);
    if (arquivo.current) arquivo.current.value = "";
    if (enviados) { avisar(enviados > 1 ? `${enviados} arquivos enviados.` : "Arquivo enviado."); recarregar(); }
  };

  const apagar = async (i: ItemBruto) => {
    const sim = await confirmar({
      titulo: "Apagar este arquivo?", perigo: true, confirmar: "Apagar",
      texto: <>O arquivo <b>{i.nome}</b> sai da biblioteca. Prompts que usam o link dele deixam de enviar a mídia.
        {deRoteiro[i.id] && <> O roteiro "{deRoteiro[i.id]}" volta para "a gravar".</>}</>,
    });
    if (!sim) return;
    executar(async () => {
      await api(`/midia/${i.id}`, { metodo: "DELETE" });
      setDados((d) => d && { ...d, itens: d.itens.filter((x) => x.id !== i.id), usado_bytes: Math.max(0, d.usado_bytes - (i.tamanho_bytes ?? 0)) });
    }, "Arquivo apagado.");
  };

  const salvarNome = () => renomear && executar(async () => {
    await enviar(`/midia/${renomear.id}`, { nome: novoNome.trim() }, "PATCH");
    setDados((d) => d && { ...d, itens: d.itens.map((x) => (x.id === renomear.id ? { ...x, nome: novoNome.trim() } : x)) });
    setRenomear(null);
  }, "Nome trocado.");

  const copiar = (i: ItemBruto) => {
    const token = `[${TIPO[tipoDo(i.tipo)].token}:${i.nome}](${i.url})`;
    navigator.clipboard?.writeText(token).then(() => avisar("Referência copiada. Cole no prompt do agente."), () => avisar("Não deu para copiar.", "bad"));
  };

  return (
    <>
      {janelaConfirmar}
      <Link className="btn ghost sm" to="/ferramentas" style={{ marginBottom: 10 }}><ArrowLeft />Ferramentas</Link>
      <Cabecalho eyebrow="Ferramentas" titulo="Biblioteca de mídia"
        texto="Áudios, vídeos e imagens do escritório, prontos para os agentes enviarem no WhatsApp. Copie a referência e cole no prompt, ou insira pelo editor do agente."
        acoes={dados && (
          <div className="mid-espaco" title={`${tamanho(Math.max(0, limite - usado))} livres`}>
            <div><span>Espaço usado</span><b className="num" style={{ color: uso >= 90 ? "var(--warn)" : undefined }}>{tamanho(usado)} de {tamanho(limite)}</b></div>
            <i><s style={{ width: `${Math.max(uso, usado ? 2 : 0)}%`, background: uso >= 90 ? "var(--warn)" : undefined }} /></i>
          </div>
        )} />

      <input ref={arquivo} type="file" multiple accept={ACEITA} hidden onChange={(e) => enviarArquivos(e.target.files)} />
      <div role="button" tabIndex={0} aria-label="Enviar arquivos: arraste aqui ou clique para escolher"
        className={`mid-envio ${arrastando ? "arrastando" : ""}`}
        onClick={() => !enviando && arquivo.current?.click()}
        onKeyDown={(e) => { if ((e.key === "Enter" || e.key === " ") && !enviando) { e.preventDefault(); arquivo.current?.click(); } }}
        onDragOver={(e) => { e.preventDefault(); setArrastando(true); }} onDragLeave={() => setArrastando(false)}
        onDrop={(e) => { e.preventDefault(); setArrastando(false); if (!enviando) enviarArquivos(e.dataTransfer.files); }}>
        <span className="au-icone" style={{ "--au-cor": "#7C3AED" } as CSSProperties}><UploadCloud className={enviando ? "girando" : ""} /></span>
        <div>
          <b>{enviando ? `Enviando ${enviando}…` : arrastando ? "Solte para enviar" : "Arraste arquivos aqui ou clique para escolher"}</b>
          <small>Áudio .ogg/.opus (chega como mensagem de voz), .mp3 ou .m4a e vídeo .mp4 até 16 MB · imagem .jpg/.png até 5 MB</small>
        </div>
        <button type="button" className="btn pri" disabled={Boolean(enviando)} onClick={(e) => { e.stopPropagation(); arquivo.current?.click(); }}><UploadCloud />Enviar arquivo</button>
      </div>

      <div className="au-barra">
        <label className="au-busca"><Search /><input className="inp" placeholder="Buscar pelo nome" aria-label="Buscar mídia" value={texto} onChange={(e) => setTexto(e.target.value)} /></label>
        <div className="seg" role="radiogroup" aria-label="Tipo">
          {([["todos", "Todos"], ["audio", "Áudios"], ["video", "Vídeos"], ["imagem", "Imagens"]] as const).map(([chave, rotulo]) => (
            <button key={chave} type="button" role="radio" aria-checked={filtro === chave} className={filtro === chave ? "on" : ""} onClick={() => setFiltro(chave)}>
              {rotulo} <span className="muted">{dados ? contagem(chave) : ""}</span>
            </button>
          ))}
        </div>
      </div>

      {pasta && !termo && (
        <nav className="mid-trilha" aria-label="Pastas">
          <button type="button" onClick={() => setPasta("")}><ArrowLeft />Biblioteca</button>
          {trilha.map((t, n) => (
            <span key={t.caminho} className="mid-trilha-passo">
              <ChevronRight aria-hidden />
              {n === trilha.length - 1 ? <b aria-current="page">{t.nome}</b> : <button type="button" onClick={() => setPasta(t.caminho)}>{t.nome}</button>}
            </span>
          ))}
        </nav>
      )}

      {dados && pastasVisiveis.length > 0 && (
        <div className="mid-pastas">
          {pastasVisiveis.map((p) => (
            <button key={p.caminho} type="button" className="au-cartao mid-pasta" style={{ "--au-cor": "#00852A" } as CSSProperties}
              onClick={() => setPasta(p.caminho)} aria-label={`Abrir a pasta ${p.nome}`}>
              <div className="au-cartao-corpo">
                <div className="au-cartao-cab">
                  <span className="au-icone"><Folder /></span>
                  <div><b title={p.nome}>{p.nome}</b><small>{descreverPasta(p)}</small></div>
                  <ChevronRight className="mid-pasta-seta" aria-hidden />
                </div>
              </div>
            </button>
          ))}
        </div>
      )}

      {!dados ? <Carregando erro={erro} /> : visiveis.length === 0 ? (
        pastasVisiveis.length > 0 ? null : (
          <div className="panel"><Vazio icone={<FolderOpen />}>{itens.length === 0 ? "Nenhum arquivo ainda. Envie o primeiro acima."
            : pasta && !termo ? (filtro === "todos" ? "Esta pasta está vazia." : "Nada com esse filtro nesta pasta.") : "Nada com esse filtro."}</Vazio></div>
        )
      ) : (
        <div className="au-grade">
          {visiveis.map((i) => {
            const t = TIPO[tipoDo(i.tipo)];
            return (
              <div key={i.id} className="au-cartao" style={{ "--au-cor": t.cor } as CSSProperties}>
                {tipoDo(i.tipo) === "imagem" ? <a className="mid-previa" href={i.url} target="_blank" rel="noreferrer"><img src={i.url} alt={i.nome} loading="lazy" /></a>
                  : tipoDo(i.tipo) === "video" ? <div className="mid-previa"><video src={i.url} controls preload="metadata" /></div>
                  : <div className="mid-previa audio"><audio src={i.url} controls preload="none" /></div>}
                <div className="au-cartao-corpo">
                  <div className="au-cartao-cab">
                    <span className="au-icone" style={{ width: 34, height: 34 }}><t.Icone /></span>
                    <div><b title={i.nome}>{i.nome}</b>
                      <small>{t.rotulo} · {tamanho(i.tamanho_bytes ?? 0)} · {new Date(i.created_at).toLocaleDateString("pt-BR")}</small></div>
                  </div>
                  {termo && normalizarPasta(i.pasta) && (
                    <button type="button" className="chip ac mid-chip-pasta" title={`Abrir a pasta ${rotuloDaPasta(i.pasta)}`}
                      onClick={() => { setPasta(normalizarPasta(i.pasta)); setTexto(""); }}><Folder size={11} />{nomeDaPasta(normalizarPasta(i.pasta))}</button>
                  )}
                  {deRoteiro[i.id] && <span className="chip info" title={`Gravado no roteiro "${deRoteiro[i.id]}"`}><Mic size={11} />Roteiro: {deRoteiro[i.id]}</span>}
                </div>
                <div className="au-cartao-rodape">
                  <button type="button" className="au-link" onClick={() => copiar(i)}><Copy />Copiar referência</button>
                  <span className="mid-acoes">
                    <button type="button" className="btn ghost sm" aria-label={`Renomear ${i.nome}`} title="Renomear" onClick={() => { setRenomear(i); setNovoNome(i.nome); }}><Pencil /></button>
                    <button type="button" className="btn ghost sm" aria-label={`Apagar ${i.nome}`} title="Apagar" disabled={ocupado} onClick={() => apagar(i)}><Trash2 /></button>
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {renomear && (
        <Modal titulo="Renomear arquivo" texto="Só o nome na biblioteca muda; o link continua o mesmo." aoFechar={() => setRenomear(null)}
          rodape={<><span className="sp" /><button className="btn" onClick={() => setRenomear(null)}>Cancelar</button>
            <button className="btn pri" disabled={ocupado || !novoNome.trim() || novoNome.trim() === renomear.nome} onClick={salvarNome}>Salvar</button></>}>
          <label className="field"><span className="lbl">Nome</span><input data-autofocus value={novoNome} onChange={(e) => setNovoNome(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") salvarNome(); }} /></label>
        </Modal>
      )}
    </>
  );
}
