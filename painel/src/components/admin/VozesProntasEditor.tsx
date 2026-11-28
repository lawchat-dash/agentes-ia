import { useMemo, useRef, useState, type ReactNode } from "react";
import {
  AlertTriangle, Bot, Check, ChevronDown, Clapperboard, Copy, FileText, Files, Info, Loader2, Mic, Pencil, Plus, Power, Save, Shield, Trash2, Upload, Users, X,
} from "lucide-react";
import { toast } from "sonner";
import { api, enviar } from "@/api";
import { Carregando, Modal, useCarregar, useConfirmar } from "@/componentes/ui";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

/**
 * Admin › Produtos › Roteiros › Vozes prontas: áudios modelo da LawChat (ElevenLabs ou equipe) para o escritório que não
 * quer gravar. Cada voz tem um áudio por parte do roteiro; o escritório escolhe a voz e usa (vira gravação dele).
 * Servidor: app/gestao/rotas_vozes_prontas.py.
 */

type Tipo = "audio" | "video";
type Secao = "videos" | "principais" | "objecoes";
type Genero = "feminina" | "masculina";
type Origem = "ia" | "equipe";

interface Voz {
  id: string; nome: string; tom: string | null; genero: Genero | null; origem: Origem; descricao: string | null;
  ativo: boolean; ordem: number; audios?: number; escritorios?: number;
}
interface AudioVoz { url: string; tipo: Tipo; mime_type: string | null; tamanho_bytes: number | null; duracao_s: number | null }
interface ParteMatriz {
  id: string; titulo: string; secao: Secao; tipo: Tipo; marcador: string | null; ordem: number; ativo?: boolean;
  /** O que a voz pronta fala (texto levado ao ElevenLabs) e o aviso que o escritório vê antes de usar. */
  texto_pronto?: string | null; aviso_pronto?: string | null;
}
interface VozMatriz extends Omit<Voz, "audios"> { audios: Record<string, AudioVoz> }
interface Matriz { partes: ParteMatriz[]; vozes: VozMatriz[] }

const SECOES: { v: Secao; titulo: string; Icone: typeof Mic }[] = [
  { v: "videos", titulo: "Vídeos", Icone: Clapperboard },
  { v: "principais", titulo: "Áudios principais", Icone: Mic },
  { v: "objecoes", titulo: "Quebra de objeção", Icone: Shield },
];
const ORDEM_SECAO: Record<Secao, number> = { videos: 0, principais: 1, objecoes: 2 };
const LIMITE_MB = 48;
const ACEITA_AUDIO = ".ogg,.opus,.oga,.mp3,.m4a,.aac,.wav,.webm,audio/*";
const ACEITA_VIDEO = ".mp4,.mov,.m4v,video/*";

/** Sem acento, minúsculo, só letras e números (igual ao servidor). */
const normalizar = (t: string | null | undefined) =>
  (t ?? "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

/** Honorários: a voz pronta fala um valor padrão, então a parte precisa de um aviso para o escritório. */
const ehHonorarios = (p: ParteMatriz) => [p.titulo, p.marcador].map(normalizar).some((t) => t.startsWith("honorario"));
const ehRecepcao = (p: ParteMatriz) => [p.titulo, p.marcador].map(normalizar).some((t) => t.includes("recepcao"));
const ehArquivoVideo = (f: File) => f.type.startsWith("video/") || /\.(mp4|mov|m4v)$/i.test(f.name);

function lerBase64(arquivo: File): Promise<string> {
  return new Promise((resolver, rejeitar) => {
    const leitor = new FileReader();
    leitor.onload = () => resolver(String(leitor.result ?? ""));
    leitor.onerror = () => rejeitar(new Error("Não deu para ler o arquivo."));
    leitor.readAsDataURL(arquivo);
  });
}

function duracao(s: number | null | undefined): string | null {
  if (s == null || !Number.isFinite(Number(s))) return null;
  const t = Math.round(Number(s));
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;
}
function tamanho(b: number | null | undefined): string | null {
  if (!b) return null;
  return b >= 1024 * 1024 ? `${(b / 1024 / 1024).toFixed(1).replace(".", ",")} MB` : `${Math.max(1, Math.round(b / 1024))} KB`;
}

/** Casa o nome do arquivo com a parte: igual ao título/marcador; senão o título mais longo contido no nome. */
function casarArquivo(nome: string, partes: ParteMatriz[]): ParteMatriz | null {
  const base = normalizar(nome.replace(/\.[^.]+$/, "")).replace(/^\d+\s+/, "");
  if (!base) return null;
  const igual = partes.find((p) => normalizar(p.titulo) === base || (p.marcador && normalizar(p.marcador) === base));
  if (igual) return igual;
  let melhor: ParteMatriz | null = null, tam = 0;
  for (const p of partes) {
    for (const alvo of [normalizar(p.titulo), normalizar(p.marcador)]) {
      if (alvo.length < 4) continue;
      if ((` ${base} `.includes(` ${alvo} `) || ` ${alvo} `.includes(` ${base} `)) && alvo.length > tam) { melhor = p; tam = alvo.length; }
    }
  }
  return melhor;
}

// ------------------------------------------------------------------------------------------------- tela
export default function VozesProntasEditor({ idProduto, versaoPartes }: { idProduto: string; versaoPartes?: string }) {
  const lista = useCarregar<Voz[]>("/admin/vozes-prontas", [], { guardar: false });
  const matriz = useCarregar<Matriz>(`/admin/biblioteca/produtos/${idProduto}/vozes-prontas`, [versaoPartes], { guardar: false });
  const [escolhida, setEscolhida] = useState<string | null>(null);
  const [formulario, setFormulario] = useState<Voz | "nova" | null>(null);
  const [varios, setVarios] = useState<File[] | null>(null);
  const [mexendo, setMexendo] = useState<string | null>(null);
  const [confirmar, janelaConfirmar] = useConfirmar();
  const entradaVarios = useRef<HTMLInputElement>(null);

  const vozes = lista.dados ?? [];
  const usoPorVoz = useMemo(() => new Map(vozes.map((v) => [v.id, v.escritorios ?? 0])), [vozes]);
  const partes = useMemo(() => [...(matriz.dados?.partes ?? [])].filter((p) => p.ativo !== false)
    .sort((a, b) => ORDEM_SECAO[a.secao] - ORDEM_SECAO[b.secao] || a.ordem - b.ordem), [matriz.dados?.partes]);
  const vozesMatriz = matriz.dados?.vozes ?? [];
  const voz = vozesMatriz.find((v) => v.id === escolhida) ?? vozesMatriz[0] ?? null;

  const recarregarTudo = () => { lista.recarregar(); matriz.recarregar(); };

  const guardarAudio = (idVoz: string, idParte: string, audio: AudioVoz | null) =>
    matriz.setDados((d) => (d ? {
      ...d, vozes: d.vozes.map((v) => {
        if (v.id !== idVoz) return v;
        const audios = { ...v.audios };
        if (audio) audios[idParte] = audio; else delete audios[idParte];
        return { ...v, audios };
      }),
    } : d));

  /** Sobe um arquivo para a parte (substitui o anterior). Devolve true se deu certo. */
  const subir = async (idVoz: string, parte: ParteMatriz, f: File): Promise<boolean> => {
    if (f.size > LIMITE_MB * 1024 * 1024) throw new Error(`Arquivo grande demais (máximo ${LIMITE_MB} MB).`);
    const conteudo_base64 = await lerBase64(f);
    const r = await enviar<AudioVoz & { id_parte: string }>(`/admin/vozes-prontas/${idVoz}/partes/${parte.id}`,
      { conteudo_base64, mime: f.type || null, nome: f.name });
    guardarAudio(idVoz, parte.id, { url: r.url, tipo: r.tipo, mime_type: r.mime_type, tamanho_bytes: r.tamanho_bytes, duracao_s: r.duracao_s });
    return true;
  };

  /** Quem já usou a voz guarda o link do arquivo: o servidor mantém o arquivo antigo enquanto alguém aponta para ele. */
  const avisarUso = async (idVoz: string, acao: "trocar" | "tirar", titulo: string) => {
    const usam = usoPorVoz.get(idVoz) ?? 0;
    if (usam === 0) return true;
    return confirmar({
      titulo: acao === "trocar" ? `Trocar o áudio de "${titulo}"?` : `Tirar o áudio de "${titulo}"?`, perigo: true,
      confirmar: acao === "trocar" ? "Trocar" : "Tirar",
      texto: `${usam === 1 ? "1 escritório já usa" : `${usam} escritórios já usam`} esta voz. Eles continuam com o áudio antigo até usarem a voz de novo.`,
    });
  };

  const enviarUm = async (parte: ParteMatriz, f: File | undefined) => {
    if (!f || !voz) return;
    if (voz.audios[parte.id] && !(await avisarUso(voz.id, "trocar", parte.titulo))) return;
    setMexendo(parte.id);
    try {
      await subir(voz.id, parte, f);
      toast.success(`Áudio de "${parte.titulo}" enviado.`);
      lista.recarregar();
    } catch (e) {
      toast.error("Não deu para enviar", { description: (e as Error).message });
    } finally { setMexendo(null); }
  };

  const tirar = async (parte: ParteMatriz) => {
    if (!voz) return;
    if (!(await avisarUso(voz.id, "tirar", parte.titulo))) return;
    setMexendo(parte.id);
    try {
      await api(`/admin/vozes-prontas/${voz.id}/partes/${parte.id}`, { metodo: "DELETE" });
      guardarAudio(voz.id, parte.id, null);
      lista.recarregar();
    } catch (e) {
      toast.error("Não deu para tirar o áudio", { description: (e as Error).message });
    } finally { setMexendo(null); }
  };

  const alternarAtivo = async (v: Voz) => {
    try {
      await enviar(`/admin/vozes-prontas/${v.id}`, { ativo: !v.ativo }, "PATCH");
      toast.success(v.ativo ? "Voz desativada." : "Voz ativada.", {
        description: v.ativo ? "Os escritórios não veem mais esta voz. Quem já usa continua com os áudios." : "Os escritórios já podem escolher esta voz.",
      });
      recarregarTudo();
    } catch (e) {
      toast.error("Não deu para mudar a voz", { description: (e as Error).message });
    }
  };

  const apagar = async (v: Voz) => {
    const ok = await confirmar({
      titulo: `Apagar a voz "${v.nome}"?`, perigo: true, confirmar: "Apagar",
      texto: "A voz e todos os áudios dela (em todos os produtos) são apagados. Não dá para desfazer.",
    });
    if (!ok) return;
    try {
      await api(`/admin/vozes-prontas/${v.id}`, { metodo: "DELETE" });
      toast.success("Voz apagada.");
      if (escolhida === v.id) setEscolhida(null);
      recarregarTudo();
    } catch (e) {
      toast.error("Não deu para apagar", { description: (e as Error).message });
    }
  };

  const precisam = partes;
  const precisamCom = voz ? precisam.filter((p) => voz.audios[p.id]).length : 0;
  const semTexto = partes.filter((p) => !p.texto_pronto?.trim() && p.tipo === "audio").length;

  const guardarTexto = async (parte: ParteMatriz, texto_pronto: string, aviso_pronto: string) => {
    const r = await enviar<{ texto_pronto: string | null; aviso_pronto: string | null }>(
      `/admin/roteiro-partes/${parte.id}/texto-pronto`, { texto_pronto, aviso_pronto }, "PATCH");
    matriz.setDados((d) => (d ? { ...d, partes: d.partes.map((x) => (x.id === parte.id ? { ...x, ...r } : x)) } : d));
    toast.success(`Texto de "${parte.titulo}" salvo.`);
  };

  /** Todos os textos, numerados como na tela (e no nome do arquivo que volta do ElevenLabs). */
  const copiarTodos = async () => {
    const linhas = partes.map((p, i) => `${String(i + 1).padStart(2, "0")} - ${p.titulo}\n${p.texto_pronto?.trim() || "(sem texto)"}`);
    try {
      await navigator.clipboard.writeText(linhas.join("\n\n"));
      toast.success("Textos copiados", { description: "Cole no ElevenLabs. Salve cada áudio com o número e o título da parte." });
    } catch {
      toast.error("Não deu para copiar.");
    }
  };

  return (
    <Card className="p-5 space-y-4">
      {/* topo */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3 min-w-0">
          <div className="size-9 rounded-xl grid place-items-center shrink-0 text-white" style={{ backgroundImage: "linear-gradient(135deg, #3BE062, #00BC33)" }}>
            <Bot className="size-[18px]" />
          </div>
          <div className="min-w-0">
            <h3 className="text-base font-semibold text-[#0C1811]">Vozes prontas</h3>
            <p className="text-xs text-[#69786F] mt-0.5 max-w-2xl leading-relaxed">
              Áudios modelo da LawChat (ElevenLabs ou equipe) para quem não quer gravar. O escritório escolhe a voz e usa.
              Cada parte tem o <strong className="text-[#0C1811]">texto da voz</strong>: sem nome de escritório, advogado, atendente,
              cidade nem número (a apresentação vai por texto). Os <strong className="text-[#0C1811]">Honorários</strong> falam um valor
              padrão: escreva no aviso o que o áudio fala, porque o escritório confere antes de usar. Na parte{" "}
              <strong className="text-[#0C1811]">Vídeo de Recepção</strong>, suba um áudio de boas-vindas (voz pronta não tem vídeo).
            </p>
          </div>
        </div>
        <Button variant="outline" onClick={() => setFormulario("nova")} className="shrink-0">
          <Plus className="size-4 mr-1.5" /> Nova voz
        </Button>
      </div>

      {/* lista de vozes */}
      {!lista.dados ? <Carregando erro={lista.erro} /> : vozes.length === 0 ? (
        <div className="rounded-xl border border-dashed border-[#E2E9E4] p-5 text-center text-[13px] text-[#69786F]">
          Nenhuma voz ainda. Crie a primeira (ex.: “Clara”, tom acolhedor) e depois suba os áudios de cada parte.
        </div>
      ) : (
        <div className="grid gap-2.5 md:grid-cols-2">
          {[...vozes].sort((a, b) => a.ordem - b.ordem || a.nome.localeCompare(b.nome)).map((v) => (
            <div key={v.id} className={`rounded-xl border bg-white p-3.5 space-y-2 ${v.ativo ? "border-[#E2E9E4]" : "border-dashed border-[#E2E9E4] opacity-75"}`}>
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="text-[14px] font-semibold text-[#0C1811] truncate">{v.nome}</div>
                  {v.descricao && <p className="text-[11.5px] text-[#69786F] line-clamp-2">{v.descricao}</p>}
                </div>
                <div className="flex items-center gap-0.5 shrink-0">
                  <IconeBotao rotulo="Editar voz" aoClicar={() => setFormulario(v)}><Pencil className="size-4" /></IconeBotao>
                  <IconeBotao rotulo={v.ativo ? "Desativar voz" : "Ativar voz"} aoClicar={() => alternarAtivo(v)}><Power className="size-4" /></IconeBotao>
                  <IconeBotao rotulo="Apagar voz" perigo aoClicar={() => apagar(v)}><Trash2 className="size-4" /></IconeBotao>
                </div>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {v.tom && <Chip>{v.tom}</Chip>}
                {v.genero && <Chip>{v.genero === "feminina" ? "Feminina" : "Masculina"}</Chip>}
                <Chip>{v.origem === "equipe" ? "Equipe" : "IA"}</Chip>
                <Chip cor={v.ativo ? "verde" : "cinza"}>{v.ativo ? "Ativa" : "Inativa"}</Chip>
                <Chip><Mic className="size-3" />{v.audios ?? 0} {(v.audios ?? 0) === 1 ? "áudio" : "áudios"}</Chip>
                <Chip><Users className="size-3" />{v.escritorios ?? 0} {(v.escritorios ?? 0) === 1 ? "escritório" : "escritórios"}</Chip>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* matriz do produto */}
      <div className="border-t border-[#E2E9E4] pt-4 space-y-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h4 className="text-[14px] font-semibold text-[#0C1811]">Áudios deste produto</h4>
            <p className="text-[11.5px] text-[#69786F]">Escolha a voz e suba um áudio para cada parte do roteiro.</p>
          </div>
          {partes.length > 0 && (
            <Button variant="outline" size="sm" onClick={copiarTodos}>
              <Copy className="size-3.5 mr-1.5" /> Copiar todos os textos
            </Button>
          )}
          {voz && partes.length > 0 && (
            <>
              <input ref={entradaVarios} type="file" multiple className="hidden" accept={`${ACEITA_AUDIO},${ACEITA_VIDEO}`}
                onChange={(e) => { const fs = Array.from(e.target.files ?? []); if (fs.length) setVarios(fs); e.target.value = ""; }} />
              <Button variant="outline" size="sm" onClick={() => entradaVarios.current?.click()}>
                <Files className="size-3.5 mr-1.5" /> Enviar vários
              </Button>
            </>
          )}
        </div>

        {!matriz.dados ? <Carregando erro={matriz.erro} /> : vozesMatriz.length === 0 ? (
          <p className="rounded-xl border border-dashed border-[#E2E9E4] p-4 text-center text-[13px] text-[#69786F]">Crie uma voz para subir os áudios.</p>
        ) : partes.length === 0 ? (
          <p className="rounded-xl border border-dashed border-[#E2E9E4] p-4 text-center text-[13px] text-[#69786F]">Este produto ainda não tem partes ligadas no roteiro.</p>
        ) : voz && (
          <>
            <div role="tablist" aria-label="Voz" className="flex flex-wrap gap-1.5">
              {vozesMatriz.map((v) => {
                const on = v.id === voz.id;
                const n = partes.filter((p) => v.audios[p.id]).length;
                return (
                  <button key={v.id} type="button" role="tab" aria-selected={on} onClick={() => setEscolhida(v.id)}
                    className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[12.5px] font-medium transition-colors ${on ? "border-[#00BC33] bg-[#E6F5EB] text-[#00852A]" : "border-[#E2E9E4] bg-white text-[#69786F] hover:text-[#0C1811]"} ${v.ativo ? "" : "opacity-70"}`}>
                    {v.nome}
                    <span className={`rounded-full px-1.5 text-[11px] leading-5 tabular-nums ${on ? "bg-white text-[#00852A]" : "bg-[#F7FAF8]"}`}>{n}</span>
                    {!v.ativo && <span className="text-[10.5px]">(inativa)</span>}
                  </button>
                );
              })}
            </div>

            <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 rounded-xl border border-[#E2E9E4] bg-[#F7FAF8] px-3.5 py-2.5">
              <span className="text-[13px] font-semibold text-[#0C1811] tabular-nums">
                {precisamCom} de {precisam.length} {precisam.length === 1 ? "parte" : "partes"} com áudio
              </span>
              {semTexto > 0 && (
                <span className="text-[11.5px] text-amber-800">{semTexto === 1 ? "1 parte de áudio sem texto da voz" : `${semTexto} partes de áudio sem texto da voz`}</span>
              )}
              {precisamCom === precisam.length && precisam.length > 0 && (
                <span className="inline-flex items-center gap-1 text-[11.5px] font-medium text-[#00852A]"><Check className="size-3.5" />Voz completa neste produto</span>
              )}
            </div>

            <div className="space-y-4">
              {SECOES.map((s) => {
                const daSecao = partes.filter((p) => p.secao === s.v);
                if (daSecao.length === 0) return null;
                return (
                  <div key={s.v} className="space-y-2">
                    <div className="flex items-center gap-2">
                      <div className="size-7 rounded-lg grid place-items-center shrink-0 bg-[#E6F5EB] text-[#00852A]"><s.Icone className="size-3.5" /></div>
                      <h5 className="text-[13px] font-semibold text-[#0C1811]">{s.titulo}
                        <span className="text-[#69786F] font-normal"> ({daSecao.filter((p) => voz.audios[p.id]).length}/{daSecao.length})</span></h5>
                    </div>
                    {daSecao.map((p) => (
                      <LinhaParte key={`${voz.id}-${p.id}`} parte={p} audio={voz.audios[p.id] ?? null} ocupado={mexendo === p.id}
                        aoEnviar={(f) => enviarUm(p, f)} aoTirar={() => tirar(p)} aoSalvarTexto={(t, a) => guardarTexto(p, t, a)} />
                    ))}
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>

      {formulario && (
        <FormularioVoz voz={formulario === "nova" ? null : formulario} aoFechar={() => setFormulario(null)}
          aoSalvar={(v) => { setFormulario(null); if (formulario === "nova") setEscolhida(v.id); recarregarTudo(); }} />
      )}
      {varios && voz && (
        <EnviarVarios arquivos={varios} partes={partes} voz={voz} usam={usoPorVoz.get(voz.id) ?? 0}
          subir={(parte, f) => subir(voz.id, parte, f)}
          aoFechar={(enviou) => { setVarios(null); if (enviou) lista.recarregar(); }} />
      )}
      {janelaConfirmar}
    </Card>
  );
}

// ------------------------------------------------------------------------------------------------- linha da parte
function LinhaParte({ parte, audio, ocupado, aoEnviar, aoTirar, aoSalvarTexto }: {
  parte: ParteMatriz; audio: AudioVoz | null; ocupado: boolean; aoEnviar: (f: File | undefined) => void; aoTirar: () => void;
  aoSalvarTexto: (texto: string, aviso: string) => Promise<void>;
}) {
  const entrada = useRef<HTMLInputElement>(null);
  const texto = ehHonorarios(parte) && !parte.aviso_pronto?.trim();
  const video = parte.tipo === "video";
  const detalhes = audio ? [duracao(audio.duracao_s), tamanho(audio.tamanho_bytes)].filter(Boolean).join(" · ") : "";

  return (
    <div className={`rounded-xl border p-3 ${texto ? "border-amber-300/80 bg-amber-50/60" : "border-[#E2E9E4] bg-white"}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[13px] font-semibold text-[#0C1811]">{parte.titulo}</span>
            <Chip>{video ? <Clapperboard className="size-3" /> : <Mic className="size-3" />}{video ? "Vídeo" : "Áudio"}</Chip>
            {texto && <Chip cor="ambar"><AlertTriangle className="size-3" />Falta o aviso</Chip>}
            {audio ? <Chip cor="verde"><Check className="size-3" />{audio.tipo === "video" ? "Vídeo enviado" : "Áudio enviado"}</Chip>
              : !texto && <Chip cor="cinza">Sem áudio</Chip>}
          </div>
          {parte.marcador && <div className="font-mono text-[11px] text-[#69786F]">[[{video ? "video" : "audio"}:{parte.marcador}]]</div>}
          {texto && <p className="text-[11px] text-amber-800">Fala um honorário padrão: escreva no aviso os valores que o áudio fala.</p>}
          {parte.aviso_pronto?.trim() && <p className="text-[11px] text-[#69786F] flex items-start gap-1"><Info className="size-3 mt-px shrink-0" />Aviso: {parte.aviso_pronto}</p>}
          {video && !audio && ehRecepcao(parte) && (
            <p className="text-[11px] text-[#69786F] flex items-start gap-1"><Info className="size-3 mt-px shrink-0" />Suba um áudio de boas-vindas (voz pronta não tem vídeo).</p>
          )}
          {video && !audio && !ehRecepcao(parte) && (
            <p className="text-[11px] text-[#69786F] flex items-start gap-1"><Info className="size-3 mt-px shrink-0" />Pode ser um vídeo genérico da equipe ou um áudio.</p>
          )}
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <input ref={entrada} type="file" className="hidden" accept={video ? `${ACEITA_AUDIO},${ACEITA_VIDEO}` : ACEITA_AUDIO}
            onChange={(e) => { aoEnviar(e.target.files?.[0]); e.target.value = ""; }} />
          <Button variant="outline" size="sm" disabled={ocupado} onClick={() => entrada.current?.click()}>
            {ocupado ? <Loader2 className="size-3.5 mr-1.5 animate-spin" /> : <Upload className="size-3.5 mr-1.5" />}
            {audio ? "Trocar" : video ? "Enviar áudio ou vídeo" : "Enviar áudio"}
          </Button>
          {audio && (
            <Button variant="ghost" size="sm" disabled={ocupado} onClick={aoTirar} className="text-[#69786F]">
              <X className="size-3.5 mr-1" /> Remover
            </Button>
          )}
        </div>
      </div>
      {audio && (
        <div className="mt-2.5 flex flex-wrap items-center gap-2.5">
          {audio.tipo === "video"
            ? <video controls preload="metadata" src={audio.url} className="w-full max-w-sm rounded-lg bg-black" />
            : <audio controls preload="metadata" src={audio.url} className="w-full max-w-md" />}
          {detalhes && <span className="text-[11px] text-[#69786F] tabular-nums">{detalhes}</span>}
        </div>
      )}
      <TextoDaVoz parte={parte} aoSalvar={aoSalvarTexto} />
    </div>
  );
}

/** O texto que a voz pronta fala nesta parte (para o ElevenLabs) e o aviso que o escritório vê antes de usar. */
function TextoDaVoz({ parte, aoSalvar }: { parte: ParteMatriz; aoSalvar: (texto: string, aviso: string) => Promise<void> }) {
  const [aberto, setAberto] = useState(false);
  const [texto, setTexto] = useState(parte.texto_pronto ?? "");
  const [aviso, setAviso] = useState(parte.aviso_pronto ?? "");
  const [salvando, setSalvando] = useState(false);
  const mudou = texto !== (parte.texto_pronto ?? "") || aviso !== (parte.aviso_pronto ?? "");
  const copiar = async () => {
    try { await navigator.clipboard.writeText(texto); toast.success("Texto copiado."); } catch { toast.error("Não deu para copiar."); }
  };
  const salvar = async () => {
    setSalvando(true);
    try { await aoSalvar(texto, aviso); } catch (e) { toast.error("Não deu para salvar", { description: (e as Error).message }); }
    finally { setSalvando(false); }
  };
  return (
    <div className="mt-2.5 border-t border-[#E2E9E4]/80 pt-2">
      <button type="button" onClick={() => setAberto((v) => !v)} aria-expanded={aberto}
        className="inline-flex items-center gap-1.5 text-[11.5px] font-medium text-[#69786F] hover:text-[#0C1811]">
        <FileText className="size-3.5" />Texto da voz
        <span className="font-normal">{parte.texto_pronto?.trim() ? `(${parte.texto_pronto.trim().length} caracteres)` : "(vazio)"}</span>
        <ChevronDown className={`size-3.5 transition-transform ${aberto ? "rotate-180" : ""}`} />
      </button>
      {aberto && (
        <div className="mt-2 space-y-2">
          <Textarea value={texto} onChange={(e) => setTexto(e.target.value)} rows={5} maxLength={6000}
            placeholder="O que a voz fala nesta parte. Sem nome de escritório, advogado, atendente, cidade nem número." className="text-[12.5px]" />
          <Input value={aviso} onChange={(e) => setAviso(e.target.value)} maxLength={600}
            placeholder="Aviso para o escritório (ex.: Fala: 4 salários mínimos e 30% dos atrasados)" className="text-[12.5px]" />
          <div className="flex flex-wrap gap-1.5">
            <Button variant="outline" size="sm" disabled={!texto.trim()} onClick={copiar}><Copy className="size-3.5 mr-1.5" />Copiar</Button>
            <Button size="sm" disabled={!mudou || salvando} onClick={salvar}>
              {salvando ? <Loader2 className="size-3.5 mr-1.5 animate-spin" /> : <Save className="size-3.5 mr-1.5" />}Salvar
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------------------------------------- enviar vários
type Situacao = "esperando" | "enviando" | "ok" | "erro";
interface ItemEnvio { arquivo: File; parte: ParteMatriz | null; motivo: string | null; situacao: Situacao; erro?: string }

function montarItens(arquivos: File[], partes: ParteMatriz[]): ItemEnvio[] {
  const itens: ItemEnvio[] = arquivos.map((arquivo) => {
    const parte = casarArquivo(arquivo.name, partes);
    let motivo: string | null = null;
    if (!parte) motivo = "Nenhuma parte com esse nome";
    else if (ehArquivoVideo(arquivo) && parte.tipo !== "video") motivo = "Vídeo só vale em parte de vídeo";
    else if (arquivo.size > LIMITE_MB * 1024 * 1024) motivo = `Maior que ${LIMITE_MB} MB`;
    return { arquivo, parte, motivo, situacao: "esperando" };
  });
  // Dois arquivos para a mesma parte: vale o primeiro.
  const vistas = new Set<string>();
  for (const it of itens) {
    if (it.motivo || !it.parte) continue;
    if (vistas.has(it.parte.id)) it.motivo = "Outro arquivo já casou com esta parte";
    else vistas.add(it.parte.id);
  }
  return itens;
}

function EnviarVarios({ arquivos, partes, voz, usam, subir, aoFechar }: {
  arquivos: File[]; partes: ParteMatriz[]; voz: VozMatriz; usam: number;
  subir: (parte: ParteMatriz, f: File) => Promise<boolean>; aoFechar: (enviou: boolean) => void;
}) {
  const [itens, setItens] = useState<ItemEnvio[]>(() => montarItens(arquivos, partes));
  const [rodando, setRodando] = useState(false);
  const [terminou, setTerminou] = useState(false);
  const validos = itens.filter((i) => !i.motivo);
  const substitui = validos.filter((i) => i.parte && voz.audios[i.parte.id]).length;
  const enviados = itens.filter((i) => i.situacao === "ok").length;
  const falhas = itens.filter((i) => i.situacao === "erro").length;

  const mudar = (idx: number, m: Partial<ItemEnvio>) => setItens((lista) => lista.map((it, i) => (i === idx ? { ...it, ...m } : it)));

  const comecar = async () => {
    setRodando(true);
    for (let i = 0; i < itens.length; i++) {
      const it = itens[i];
      if (it.motivo || !it.parte || it.situacao === "ok") continue;
      mudar(i, { situacao: "enviando", erro: undefined });
      try {
        await subir(it.parte, it.arquivo);
        mudar(i, { situacao: "ok" });
      } catch (e) {
        mudar(i, { situacao: "erro", erro: (e as Error).message });
      }
    }
    setRodando(false);
    setTerminou(true);
  };

  return (
    <Modal titulo={`Enviar vários para "${voz.nome}"`} largura={620} aoFechar={() => { if (!rodando) aoFechar(enviados > 0); }}
      texto="O nome do arquivo é comparado com o título da parte (sem acento e sem número na frente). Ex.: “03 - Como funciona.mp3”."
      rodape={<>
        <Button variant="outline" disabled={rodando} onClick={() => aoFechar(enviados > 0)}>{terminou ? "Fechar" : "Cancelar"}</Button>
        {!terminou || falhas > 0 ? (
          <Button disabled={rodando || validos.length === 0} onClick={comecar} className="text-white" style={{ backgroundImage: "linear-gradient(135deg, #3BE062, #00BC33)" }}>
            {rodando ? <Loader2 className="size-4 mr-1.5 animate-spin" /> : <Upload className="size-4 mr-1.5" />}
            {terminou ? "Tentar os que falharam" : validos.length === 1 ? "Enviar 1 arquivo" : `Enviar ${validos.length} arquivos`}
          </Button>
        ) : null}
      </>}>
      <div className="space-y-3">
        <div className="flex flex-wrap gap-1.5 text-[11.5px]">
          <Chip cor="verde">{validos.length} {validos.length === 1 ? "casou" : "casaram"}</Chip>
          {itens.length - validos.length > 0 && <Chip cor="ambar">{itens.length - validos.length} sem parte</Chip>}
          {terminou && <Chip cor={falhas ? "ambar" : "verde"}>{enviados} {enviados === 1 ? "enviado" : "enviados"}{falhas ? ` · ${falhas} com erro` : ""}</Chip>}
        </div>
        {substitui > 0 && usam > 0 && !terminou && (
          <div className="flex items-start gap-2 rounded-lg border border-amber-300/80 bg-amber-50 p-2.5 text-[11.5px] text-amber-900">
            <AlertTriangle className="size-3.5 mt-px shrink-0 text-amber-600" />
            {substitui === 1 ? "1 áudio vai ser trocado" : `${substitui} áudios vão ser trocados`}.{" "}
            {usam === 1 ? "1 escritório já usa" : `${usam} escritórios já usam`} esta voz: eles continuam com o áudio antigo até usarem a voz de novo.
          </div>
        )}
        <ul className="max-h-[50vh] overflow-y-auto divide-y divide-[#E2E9E4] rounded-xl border border-[#E2E9E4]">
          {itens.map((it, i) => (
            <li key={`${it.arquivo.name}-${i}`} className="flex items-center gap-2.5 px-3 py-2">
              <div className="min-w-0 flex-1">
                <div className="truncate text-[12.5px] text-[#0C1811]">{it.arquivo.name}</div>
                <div className={`truncate text-[11px] ${it.motivo ? "text-amber-700" : "text-[#69786F]"}`}>
                  {it.motivo ?? <>→ {it.parte?.titulo}{it.parte && voz.audios[it.parte.id] && it.situacao !== "ok" ? " · troca o atual" : ""}</>}
                  {it.erro && <span className="text-red-600"> · {it.erro}</span>}
                </div>
              </div>
              <span className="shrink-0">
                {it.motivo ? <X className="size-4 text-amber-600" aria-label="Não casou" />
                  : it.situacao === "enviando" ? <Loader2 className="size-4 animate-spin text-[#69786F]" aria-label="Enviando" />
                  : it.situacao === "ok" ? <Check className="size-4 text-[#00852A]" aria-label="Enviado" />
                  : it.situacao === "erro" ? <AlertTriangle className="size-4 text-red-600" aria-label="Erro" />
                  : <span className="text-[11px] text-[#69786F]">na fila</span>}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </Modal>
  );
}

// ------------------------------------------------------------------------------------------------- criar / editar voz
function FormularioVoz({ voz, aoFechar, aoSalvar }: { voz: Voz | null; aoFechar: () => void; aoSalvar: (v: Voz) => void }) {
  const [nome, setNome] = useState(voz?.nome ?? "");
  const [tom, setTom] = useState(voz?.tom ?? "");
  const [genero, setGenero] = useState<Genero | "">(voz?.genero ?? "");
  const [origem, setOrigem] = useState<Origem>(voz?.origem ?? "ia");
  const [descricao, setDescricao] = useState(voz?.descricao ?? "");
  const [ordem, setOrdem] = useState(String(voz?.ordem ?? 0));
  const [salvando, setSalvando] = useState(false);

  const salvar = async () => {
    if (!nome.trim()) { toast.error("Dê um nome para a voz."); return; }
    setSalvando(true);
    const corpo = {
      nome: nome.trim(), tom: tom.trim() || null, genero: genero || null, origem,
      descricao: descricao.trim() || null, ordem: Number.parseInt(ordem, 10) || 0,
    };
    try {
      const v = voz
        ? await enviar<Voz>(`/admin/vozes-prontas/${voz.id}`, corpo, "PATCH")
        : await enviar<Voz>("/admin/vozes-prontas", corpo);
      toast.success(voz ? "Voz salva." : "Voz criada.", { description: voz ? undefined : "Agora suba os áudios de cada parte." });
      aoSalvar(v);
    } catch (e) {
      toast.error("Não deu para salvar a voz", { description: (e as Error).message });
      setSalvando(false);
    }
  };

  return (
    <Modal titulo={voz ? `Editar "${voz.nome}"` : "Nova voz"} largura={520} aoFechar={() => { if (!salvando) aoFechar(); }}
      rodape={<>
        <Button variant="outline" disabled={salvando} onClick={aoFechar}>Cancelar</Button>
        <Button disabled={salvando || !nome.trim()} onClick={salvar} className="text-white" style={{ backgroundImage: "linear-gradient(135deg, #3BE062, #00BC33)" }}>
          {salvando ? <Loader2 className="size-4 mr-1.5 animate-spin" /> : <Check className="size-4 mr-1.5" />} {voz ? "Salvar" : "Criar voz"}
        </Button>
      </>}>
      <div className="space-y-3.5">
        <Campo rotulo="Nome">
          <Input value={nome} maxLength={80} onChange={(e) => setNome(e.target.value)} placeholder="Ex.: Clara" autoFocus />
        </Campo>
        <Campo rotulo="Tom">
          <Input value={tom} maxLength={80} onChange={(e) => setTom(e.target.value)} placeholder="Ex.: acolhedora, firme, animada" />
        </Campo>
        <div className="flex flex-wrap gap-x-6 gap-y-3">
          <Campo rotulo="Gênero" grupo>
            <Pilulas<Genero | ""> valor={genero} aoMudar={setGenero} rotulo="Gênero"
              opcoes={[{ v: "feminina", l: "Feminina" }, { v: "masculina", l: "Masculina" }, { v: "", l: "Não informar" }]} />
          </Campo>
          <Campo rotulo="Origem" grupo>
            <Pilulas<Origem> valor={origem} aoMudar={setOrigem} rotulo="Origem"
              opcoes={[{ v: "ia", l: "IA (ElevenLabs)" }, { v: "equipe", l: "Equipe" }]} />
          </Campo>
        </div>
        <Campo rotulo="Descrição">
          <Textarea value={descricao} maxLength={400} onChange={(e) => setDescricao(e.target.value)}
            placeholder="Aparece para o escritório ao escolher. Ex.: Voz calma e próxima, boa para público mais velho."
            className="min-h-[80px] text-[13px]" />
        </Campo>
        <Campo rotulo="Ordem na lista">
          <Input type="number" value={ordem} onChange={(e) => setOrdem(e.target.value)} className="w-28" />
        </Campo>
      </div>
    </Modal>
  );
}

// ------------------------------------------------------------------------------------------------- peças
/** Rótulo + campo. Com botões dentro (pílulas) use grupo: um <label> repassaria o clique para o primeiro botão. */
function Campo({ rotulo, grupo, children }: { rotulo: string; grupo?: boolean; children: ReactNode }) {
  const Caixa = grupo ? "div" : "label";
  return (
    <Caixa className="block space-y-1">
      <span className="block text-[11.5px] font-medium text-[#69786F]">{rotulo}</span>
      {children}
    </Caixa>
  );
}

function Chip({ children, cor }: { children: ReactNode; cor?: "verde" | "ambar" | "cinza" }) {
  const estilo = cor === "verde" ? "border-[#00BC33]/40 bg-[#E6F5EB] text-[#00852A]"
    : cor === "ambar" ? "border-amber-300 bg-amber-50 text-amber-800"
    : cor === "cinza" ? "border-[#E2E9E4] bg-[#F7FAF8] text-[#69786F]"
    : "border-[#E2E9E4] bg-white text-[#0C1811]";
  return <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11.5px] ${estilo}`}>{children}</span>;
}

function IconeBotao({ rotulo, perigo, aoClicar, children }: { rotulo: string; perigo?: boolean; aoClicar: () => void; children: ReactNode }) {
  return (
    <button type="button" title={rotulo} aria-label={rotulo} onClick={aoClicar}
      className={`grid size-8 place-items-center rounded-lg text-[#69786F] transition-colors ${perigo ? "hover:bg-red-50 hover:text-red-600" : "hover:bg-[#E6F5EB] hover:text-[#00852A]"}`}>
      {children}
    </button>
  );
}

function Pilulas<T extends string>({ rotulo, valor, opcoes, aoMudar }: {
  rotulo: string; valor: T; opcoes: { v: T; l: string }[]; aoMudar: (v: T) => void;
}) {
  return (
    <div role="radiogroup" aria-label={rotulo} className="inline-flex flex-wrap rounded-full border border-[#E2E9E4] bg-[#F7FAF8] p-0.5">
      {opcoes.map((o) => {
        const on = o.v === valor;
        return (
          <button key={o.v || "vazio"} type="button" role="radio" aria-checked={on} onClick={() => aoMudar(o.v)}
            className={`rounded-full px-2.5 py-1 text-[12px] font-medium transition-colors ${on ? "bg-white text-[#00852A] shadow-sm ring-1 ring-[#00BC33]/40" : "text-[#69786F] hover:text-[#0C1811]"}`}>
            {o.l}
          </button>
        );
      })}
    </div>
  );
}
