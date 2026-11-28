// Uma parte do roteiro de gravação: texto para ler, exemplo, gravar (áudio ou vídeo) ou anexar, "ficou bom?" e o envio.
// Usado na tela Roteiros e no card de gravação da ativação do produto.
import { useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Mic, RotateCcw, Square, Trash2, Upload, Video as IconeVideo, Volume2 } from "lucide-react";
import { api, enviar } from "@/api";
import { arquivoParaBase64 } from "@/lib/base64";
import { useConfirmar } from "@/componentes/ui";
import { toast } from "sonner";
import type { ParteRoteiro, Qualidade } from "./tipos";
import "./vozesProntas.css";

const TIPOS_AUDIO = ["audio/ogg;codecs=opus", "audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
const TIPOS_VIDEO = ["video/mp4;codecs=avc1,mp4a", "video/mp4", "video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm"];
const MAX_AUDIO_S = 10 * 60;
const MAX_VIDEO_S = 3 * 60;
const LIMITE_ARQUIVO = 80 * 1024 * 1024;
const EXT_AUDIO = ["ogg", "oga", "opus", "mp3", "m4a", "aac", "wav", "webm"];
const EXT_VIDEO = ["mp4", "mov", "webm", "m4v"];

const fmtTempo = (s: number) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const quando = (iso: string) => new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });

const FRASE_QUALIDADE: Record<Qualidade, string> = {
  boa: "Ficou bom: dá para ouvir com clareza.",
  curta: "Ficou curto demais: grave pelo menos alguns segundos.",
  baixa: "O som ficou muito baixo. Aproxime o celular da boca e grave de novo.",
  silenciosa: "Quase não ouvimos sua voz. Confira o microfone e grave de novo.",
};

interface Medida { duracao_s: number; pico: number; silencio_pct: number; qualidade: Qualidade }

/** "Ficou bom?": duração, volume máximo e quanto do tempo ficou em silêncio, medidos no próprio aparelho. */
async function medirQualidade(blob: Blob, segundosGravados: number): Promise<Medida | null> {
  try {
    const ctx = new AudioContext();
    const audio = await ctx.decodeAudioData(await blob.arrayBuffer());
    ctx.close().catch(() => {});
    const dados = audio.getChannelData(0);
    const janela = Math.max(1, Math.floor(audio.sampleRate / 20));        // 50 ms
    let pico = 0, silenciosas = 0, janelas = 0;
    for (let i = 0; i < dados.length; i += janela) {
      let soma = 0;
      const fim = Math.min(dados.length, i + janela);
      for (let j = i; j < fim; j++) { const v = Math.abs(dados[j]); soma += v * v; if (v > pico) pico = v; }
      const rms = Math.sqrt(soma / (fim - i));
      if (rms < 0.01) silenciosas++;
      janelas++;
    }
    const duracao = audio.duration || segundosGravados;
    const silencio = janelas ? (silenciosas / janelas) * 100 : 100;
    const qualidade: Qualidade = duracao < 3 ? "curta" : silencio > 85 ? "silenciosa" : pico < 0.08 ? "baixa" : "boa";
    return { duracao_s: Math.round(duracao * 10) / 10, pico: Math.min(1, Math.round(pico * 1000) / 1000), silencio_pct: Math.round(silencio * 10) / 10, qualidade };
  } catch {
    return null;                                                          // formato que o navegador não decodifica: segue sem medida
  }
}

/** Texto do roteiro: "xxxxxxxx" vira marca amarela (trocar pelo dado real); "Observação:" vira caixa de atenção. */
function TextoParaLer({ texto }: { texto: string }) {
  if (!texto.trim()) return <p className="rg-texto rg-texto--vazio">Fale com as suas palavras sobre este tema.</p>;
  const blocos = texto.split(/\n{2,}/);
  return (
    <div className="rg-texto">
      {blocos.map((b, i) => {
        const obs = /^\s*observa[cç][aã]o\s*:/i.test(b);
        const partes = b.split(/(x{4,})/gi);
        const conteudo = partes.map((p, j) => /^x{4,}$/i.test(p)
          ? <mark key={j} title="Troque pelo dado real do seu escritório antes de gravar">{p}</mark> : <span key={j}>{p}</span>);
        return obs ? <div key={i} className="rg-obs"><AlertTriangle size={14} />{conteudo}</div> : <p key={i}>{conteudo}</p>;
      })}
      {/x{4,}/i.test(texto) && <span className="rg-dica-x">Troque o que está marcado em amarelo pelo dado real do seu escritório antes de gravar.</span>}
    </div>
  );
}

export function GravadorParte({ parte, aoMudar, aoOcupar, liberado = true }: {
  parte: ParteRoteiro; aoMudar: (p: ParteRoteiro) => void; liberado?: boolean;
  /** Avisado quando passa a ter (ou deixa de ter) gravação em andamento ou prévia ainda não enviada. */
  aoOcupar?: (ocupado: boolean) => void;
}) {
  const [confirmar, modalConfirmar] = useConfirmar();
  const [regravar, setRegravar] = useState(false);
  const [comoAudio, setComoAudio] = useState(false);
  const video = parte.tipo === "video" && !comoAudio;
  const suportado = typeof window !== "undefined" && typeof window.MediaRecorder !== "undefined" && !!navigator.mediaDevices?.getUserMedia;
  const [gravando, setGravando] = useState(false);
  const [segundos, setSegundos] = useState(0);
  const [niveis, setNiveis] = useState<number[]>(() => Array(14).fill(0));
  const [previa, setPrevia] = useState<{ blob: Blob; url: string; segundos: number; medida: Medida | null } | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [erroMic, setErroMic] = useState<string | null>(null);
  const [abrindo, setAbrindo] = useState(false);                          // esperando a permissão do microfone/câmera
  const iniciando = useRef(false);                                        // trava contra clique duplo em "Gravar"
  const montado = useRef(false);
  const avisarOcupado = useRef(aoOcupar);
  avisarOcupado.current = aoOcupar;
  const gravador = useRef<MediaRecorder | null>(null);
  const fluxo = useRef<MediaStream | null>(null);
  const contexto = useRef<AudioContext | null>(null);
  const relogio = useRef<number | null>(null);
  const quadro = useRef<number | null>(null);
  const tempo = useRef(0);
  const arquivo = useRef<HTMLInputElement>(null);
  const camera = useRef<HTMLVideoElement>(null);

  const limpar = () => {
    if (relogio.current) window.clearInterval(relogio.current);
    if (quadro.current) cancelAnimationFrame(quadro.current);
    relogio.current = quadro.current = null;
    fluxo.current?.getTracks().forEach((t) => t.stop());
    fluxo.current = null;
    contexto.current?.close().catch(() => {});
    contexto.current = null;
    setNiveis(Array(14).fill(0));
  };
  useEffect(() => {
    montado.current = true;
    return () => {
      montado.current = false;
      if (gravador.current?.state === "recording") gravador.current.stop();
      limpar();
      avisarOcupado.current?.(false);
    };
  }, []);
  useEffect(() => () => { if (previa) URL.revokeObjectURL(previa.url); }, [previa]);
  useEffect(() => { avisarOcupado.current?.(gravando || !!previa); }, [gravando, previa]);
  // Câmera ao vivo: liga o <video> ao fluxo quando a gravação começa (o elemento já está na tela, escondido).
  useEffect(() => {
    const el = camera.current;
    if (!el) return;
    if (gravando && video && fluxo.current) { el.srcObject = fluxo.current; el.play().catch(() => {}); }
    else el.srcObject = null;
  }, [gravando, video]);

  const parar = () => { if (gravador.current?.state === "recording") gravador.current.stop(); };

  const comecar = async () => {
    if (iniciando.current || gravador.current?.state === "recording") return;
    iniciando.current = true;
    setAbrindo(true);
    setErroMic(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia(video
        ? { audio: { echoCancellation: true, noiseSuppression: true }, video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } } }
        : { audio: { echoCancellation: true, noiseSuppression: true } });
      if (!montado.current) { stream.getTracks().forEach((t) => t.stop()); return; }   // fechou o cartão enquanto pedia permissão
      fluxo.current = stream;
      const tipos = video ? TIPOS_VIDEO : TIPOS_AUDIO;
      const mime = tipos.find((t) => MediaRecorder.isTypeSupported?.(t)) ?? "";
      const rec = new MediaRecorder(stream, mime ? (video ? { mimeType: mime, videoBitsPerSecond: 1_200_000, audioBitsPerSecond: 64000 }
        : { mimeType: mime, audioBitsPerSecond: 48000 }) : undefined);
      const pedacos: Blob[] = [];
      rec.ondataavailable = (e) => { if (e.data.size) pedacos.push(e.data); };
      rec.onstop = async () => {
        if (!montado.current) return;                                     // cartão fechado: a gravação é descartada
        const blob = new Blob(pedacos, { type: rec.mimeType || mime || (video ? "video/webm" : "audio/webm") });
        const segs = tempo.current;
        setGravando(false);
        limpar();
        const medida = await medirQualidade(blob, segs);
        if (!montado.current) return;
        setPrevia((p) => { if (p) URL.revokeObjectURL(p.url); return { blob, url: URL.createObjectURL(blob), segundos: segs, medida }; });
      };
      try {                                       // medidor de volume (barrinhas) enquanto grava
        const ctx = new AudioContext();
        const analisador = ctx.createAnalyser();
        analisador.fftSize = 512;
        ctx.createMediaStreamSource(stream).connect(analisador);
        contexto.current = ctx;
        const buf = new Uint8Array(analisador.fftSize);
        let ultimo = 0;
        const medir = (t: number) => {
          analisador.getByteTimeDomainData(buf);
          let pico = 0;
          for (const v of buf) pico = Math.max(pico, Math.abs(v - 128));
          if (t - ultimo > 90) { ultimo = t; setNiveis((n) => [...n.slice(1), Math.min(1, pico / 80)]); }
          quadro.current = requestAnimationFrame(medir);
        };
        quadro.current = requestAnimationFrame(medir);
      } catch { /* sem medidor: grava do mesmo jeito */ }
      gravador.current = rec;
      tempo.current = 0;
      setSegundos(0);
      setPrevia(null);
      rec.start(1000);
      setGravando(true);
      relogio.current = window.setInterval(() => {
        tempo.current += 1;
        setSegundos(tempo.current);
        if (tempo.current >= (video ? MAX_VIDEO_S : MAX_AUDIO_S)) parar();
      }, 1000);
    } catch (e) {
      limpar();
      if (!montado.current) return;
      const nome = (e as DOMException)?.name;
      setErroMic(nome === "NotAllowedError"
        ? `Não conseguimos acessar ${video ? "a câmera" : "o microfone"}. Libere a permissão no cadeado da barra de endereço ou envie um arquivo.`
        : nome === "NotFoundError" ? `Nenhum${video ? "a câmera" : " microfone"} encontrado neste aparelho.` : "Não deu para começar a gravar.");
    } finally {
      iniciando.current = false;
      if (montado.current) setAbrindo(false);
    }
  };

  const subir = async (blob: Blob, nome?: string, medida?: Medida | null) => {
    setEnviando(true);
    try {
      const r = await enviar<ParteRoteiro>(`/roteiro-gravacao/partes/${parte.id}`, {
        conteudo_base64: await arquivoParaBase64(blob), mime: blob.type, nome, como_audio: parte.tipo === "video" && comoAudio,
        ...(medida ? { duracao_s: medida.duracao_s, pico: medida.pico, silencio_pct: medida.silencio_pct, qualidade: medida.qualidade } : {}),
      });
      aoMudar(r);
      setPrevia(null);
      setRegravar(false);                                                 // volta a mostrar o envio novo, não o gravador
      toast.success(`${parte.titulo}: enviado`, { description: "Já está na Biblioteca, na pasta Roteiros gravados." });
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setEnviando(false);
    }
  };

  const escolherArquivo = async (f: File | undefined) => {
    if (arquivo.current) arquivo.current.value = "";
    if (!f) return;
    const ext = f.name.toLowerCase().split(".").pop() ?? "";
    const aceitas = video ? EXT_VIDEO : EXT_AUDIO;
    if (!aceitas.includes(ext)) { toast.error(video ? "Envie um vídeo .mp4, .mov ou .webm." : "Envie um áudio .ogg, .mp3, .m4a, .wav ou .webm."); return; }
    if (f.size > LIMITE_ARQUIVO) { toast.error(`Este arquivo tem ${(f.size / 1048576).toFixed(0)} MB e o limite é 80 MB. Grave um trecho mais curto.`); return; }
    if (parte.gravacao && !(await confirmar({ titulo: "Trocar o envio?", texto: "O arquivo atual é substituído por este.", confirmar: "Trocar" }))) return;
    const medida = video ? null : await medirQualidade(f, 0);
    subir(f, f.name, medida);
  };

  const excluir = async () => {
    const pronta = parte.gravacao?.origem === "pronta";
    if (!(await confirmar(pronta
      ? { titulo: "Tirar a voz pronta?", texto: "O modelo sai desta parte e da sua Biblioteca, e a parte volta para gravar.", confirmar: "Tirar", perigo: true }
      : { titulo: "Excluir este envio?", texto: "A gravação sai da Biblioteca e esta parte volta para gravar.", confirmar: "Excluir", perigo: true }))) return;
    try {
      const r = await api<{ ok: boolean; arquivo_ficou: boolean }>(`/roteiro-gravacao/partes/${parte.id}`, { metodo: "DELETE" });
      aoMudar({ ...parte, gravacao: null });
      toast.success(r.arquivo_ficou ? "Envio excluído. O arquivo continua na Biblioteca porque um prompt ainda usa." : "Envio excluído.");
    } catch (e) { toast.error((e as Error).message); }
  };

  const g = parte.gravacao;
  // Voz pronta da LawChat: gravar ou enviar por cima vira gravação própria (a própria sempre vale mais).
  const pronta = g?.origem === "pronta";
  const mostrarGravador = !g || regravar || gravando || !!previa;

  return (
    <div className="rg-parte-corpo">
      <TextoParaLer texto={parte.texto} />

      {parte.exemplo_url && !g && (
        <div className="rg-exemplo">
          <span><Volume2 size={13} />{parte.tipo === "video" ? "Veja o exemplo antes de gravar" : "Ouça o exemplo antes de gravar"}</span>
          {parte.tipo === "video" ? <video src={parte.exemplo_url} controls preload="metadata" playsInline /> : <audio src={parte.exemplo_url} controls preload="metadata" />}
        </div>
      )}

      {g && !regravar && !gravando && !previa && (
        <div className={`rg-enviado ${pronta ? "vp-pronta" : ""}`}>
          <div className="rg-enviado-topo">
            <div>
              <b>{parte.titulo}</b>
              <small><CheckCircle2 size={13} />{pronta ? `Voz pronta${g.voz_nome ? ` · ${g.voz_nome}` : ""} (modelo da LawChat)`
                : g.reaproveitada ? "Você já tem este material (gravado em outro produto)" : "Enviado com sucesso"}
                {g.duracao_s ? ` · ${fmtTempo(g.duracao_s)}` : ""} · {quando(g.atualizado_em || g.criado_em)}</small>
              {g.qualidade && g.qualidade !== "boa" && <small className="rg-alerta">Recebido, mas com problema de som: {FRASE_QUALIDADE[g.qualidade].toLowerCase()}</small>}
            </div>
            <div className="rg-enviado-acoes">
              <button type="button" title={pronta ? "Gravar com a minha voz" : "Gravar ou enviar novamente"} aria-label={pronta ? "Gravar com a minha voz" : "Gravar ou enviar novamente"} onClick={() => setRegravar(true)} disabled={!liberado}><RotateCcw size={15} /></button>
              <button type="button" className="perigo" title={pronta ? "Tirar a voz pronta desta parte" : "Excluir este envio"} aria-label={pronta ? "Tirar a voz pronta desta parte" : "Excluir este envio"} onClick={excluir}><Trash2 size={15} /></button>
            </div>
          </div>
          {g.tipo === "video" ? <video src={g.url} controls preload="metadata" playsInline /> : <audio src={g.url} controls preload="metadata" />}
          {pronta && <small className="rg-ajuda">Prefere a sua voz? Grave ou envie por cima: a sua gravação passa a valer no lugar deste modelo.</small>}
        </div>
      )}

      {mostrarGravador && liberado && (
        <>
          {parte.tipo === "video" && !gravando && !previa && (
            <button type="button" className="rg-trocar" disabled={abrindo} onClick={() => setComoAudio((v) => !v)}>
              {comoAudio ? <><IconeVideo size={14} />Voltar a enviar vídeo</> : <><Mic size={14} />Não quero inserir um vídeo, vou trocar por áudio</>}
            </button>
          )}

          {video && <video ref={camera} className="rg-camera" muted playsInline hidden={!gravando} />}

          {previa && !gravando ? (
            <div className={`rg-previa ${previa.medida && previa.medida.qualidade !== "boa" ? "ruim" : ""}`}>
              <b>Ficou bom? · {fmtTempo(previa.segundos)}</b>
              {video ? <video src={previa.url} controls playsInline /> : <audio src={previa.url} controls />}
              {previa.medida && <p className="rg-medida">{previa.medida.qualidade === "boa" ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}{FRASE_QUALIDADE[previa.medida.qualidade]}</p>}
              <div className="rg-botoes">
                <button type="button" className="rg-btn rg-btn--pri" disabled={enviando} onClick={() => subir(previa.blob, undefined, previa.medida)}>
                  <Upload size={15} />{enviando ? "Enviando…" : previa.medida && previa.medida.qualidade !== "boa" ? "Enviar assim mesmo" : "Enviar"}
                </button>
                <button type="button" className="rg-btn" disabled={enviando} onClick={() => setPrevia(null)}><RotateCcw size={15} />Gravar de novo</button>
              </div>
            </div>
          ) : gravando ? (
            <div className="rg-gravando">
              <div className="rg-botoes">
                <button type="button" className="rg-btn rg-btn--parar" onClick={parar}><Square size={14} />Parar</button>
                <span className="rg-relogio"><i />{fmtTempo(segundos)}</span>
              </div>
              <div className="rg-nivel" aria-hidden>
                <Mic size={13} />
                {niveis.map((n, i) => <span key={i} style={{ transform: `scaleY(${0.15 + n * 0.85})`, opacity: 0.35 + n * 0.65 }} />)}
                <small>{niveis[niveis.length - 1] > 0.08 ? "captando" : "sem som…"}</small>
              </div>
            </div>
          ) : (
            <div className="rg-botoes">
              {suportado && <button type="button" className="rg-btn rg-btn--escuro" disabled={enviando || abrindo} onClick={comecar}>
                {video ? <IconeVideo size={15} /> : <Mic size={15} />}{abrindo ? "Abrindo…" : video ? "Gravar vídeo" : "Gravar"}</button>}
              <button type="button" className="rg-btn" disabled={enviando || abrindo} onClick={() => arquivo.current?.click()}>
                <Upload size={15} />{enviando ? "Enviando…" : video ? "Enviar vídeo" : "Enviar arquivo"}</button>
              {regravar && <button type="button" className="rg-btn rg-btn--leve" onClick={() => setRegravar(false)}>Cancelar</button>}
            </div>
          )}
          {erroMic && <p className="rg-erro">{erroMic}</p>}
          {!gravando && !previa && <small className="rg-ajuda">{video
            ? "Vídeo de até 3 minutos. O sistema converte para o formato do WhatsApp (MP4, até 16 MB)."
            : "Grave num lugar silencioso. .ogg chega como mensagem de voz; .mp3, .m4a e .wav são convertidos."}</small>}
          <input ref={arquivo} type="file" hidden accept={video ? ".mp4,.mov,.webm,.m4v,video/*" : ".ogg,.oga,.opus,.mp3,.m4a,.aac,.wav,.webm,audio/*"}
            onChange={(e) => escolherArquivo(e.target.files?.[0])} />
        </>
      )}
      {modalConfirmar}
    </div>
  );
}
