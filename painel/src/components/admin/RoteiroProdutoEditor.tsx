import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { AlertTriangle, ArrowDown, ArrowUp, Check, Clapperboard, Info, Loader2, Mic, Plus, Save, Shield, Trash2, Upload, Video, Wand2, X } from "lucide-react";
import { toast } from "sonner";
import { api, enviar } from "@/api";
import { Carregando, useCarregar, useConfirmar } from "@/componentes/ui";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import VozesProntasEditor from "@/components/admin/VozesProntasEditor";

/**
 * Admin › Produtos › Roteiros: o que o escritório grava (áudios e vídeos) para a IA falar com a voz dele.
 * Cada parte preenche um marcador do prompt ([[audio:Honorários]] → "Honorários"). Parte geral (chave) é gravada uma
 * vez e vale para todos os produtos com a mesma chave. Servidor: app/gestao/rotas_roteiro_gravacao.py (superadmin).
 *
 * Salvamento: tipo, seção e ativo salvam na hora; título, texto, marcador e chave salvam ao sair do campo. Os
 * salvamentos de um cartão vão em fila (um de cada vez) e cada um leva tudo o que ainda não foi salvo.
 */

type Tipo = "audio" | "video";
type Secao = "videos" | "principais" | "objecoes";

export interface ParteRoteiro {
  id: string; titulo: string; texto: string; tipo: Tipo; secao: Secao; marcador: string | null; chave_geral: string | null;
  exemplo_url: string | null; ordem: number; ativo: boolean; criado_em?: string; atualizado_em?: string;
}
interface Marcador { tipo: Tipo; nome: string; tem_parte: boolean }
interface Geral { chave_geral: string; titulo: string; tipo: Tipo; produtos: number }
interface Roteiro {
  produto: { id: string; nome: string; modo_midia: string | null; status: string | null; roteiro_orientacoes: string | null };
  partes: ParteRoteiro[]; gravacoes: number; marcadores: Marcador[]; gerais: Geral[];
}

const SECOES: { v: Secao; titulo: string; texto: string; Icone: typeof Mic }[] = [
  { v: "videos", titulo: "Vídeos", texto: "Vídeos que a IA manda (apresentação, como assinar…).", Icone: Clapperboard },
  { v: "principais", titulo: "Áudios principais", texto: "Os áudios do caminho normal da conversa.", Icone: Mic },
  { v: "objecoes", titulo: "Quebra de objeção", texto: "Áudios para quando o cliente fica em dúvida ou reclama.", Icone: Shield },
];
const ORDEM_SECAO: Record<Secao, number> = { videos: 0, principais: 1, objecoes: 2 };
const LIMITE_EXEMPLO_MB = 48;

/** Mesma comparação do servidor: sem acento, minúsculo, só letras e números. */
const normalizar = (t: string | null | undefined) =>
  (t ?? "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
/** Chave geral como o servidor grava ("Vídeo inicial" → "video_inicial"). */
const chaveNormalizada = (t: string) => normalizar(t).replace(/ /g, "_").slice(0, 60).replace(/_+$/, "");
const ehVideo = (url: string) => /\.(mp4|webm|mov|m4v)(\?|#|$)/i.test(url);

function ordenar(partes: ParteRoteiro[]): ParteRoteiro[] {
  return [...partes].sort((a, b) => ORDEM_SECAO[a.secao] - ORDEM_SECAO[b.secao] || a.ordem - b.ordem
    || (a.criado_em ?? "").localeCompare(b.criado_em ?? ""));
}

function lerBase64(arquivo: File): Promise<string> {
  return new Promise((resolver, rejeitar) => {
    const leitor = new FileReader();
    leitor.onload = () => resolver(String(leitor.result ?? ""));
    leitor.onerror = () => rejeitar(new Error("Não deu para ler o arquivo."));
    leitor.readAsDataURL(arquivo);
  });
}

// ------------------------------------------------------------------------------------------------- tela
export default function RoteiroProdutoEditor({ idProduto, modoMidia }: { idProduto: string | null | undefined; modoMidia?: string }) {
  const caminho = idProduto ? `/admin/biblioteca/produtos/${idProduto}/roteiro` : null;
  const { dados, erro, setDados, recarregar } = useCarregar<Roteiro>(caminho, [], { guardar: false });
  const [puxando, setPuxando] = useState(false);
  const [criando, setCriando] = useState(false);
  const [movendo, setMovendo] = useState(false);
  const [novaId, setNovaId] = useState<string | null>(null);
  const [confirmar, janelaConfirmar] = useConfirmar();
  // Partes excluídas: o cartão que some por exclusão não tenta salvar o que ficou pendente.
  const apagadas = useRef(new Set<string>());

  const partes = useMemo(() => ordenar(dados?.partes ?? []), [dados?.partes]);
  const comParte = useMemo(() => new Set(partes.filter((p) => p.marcador).map((p) => normalizar(p.marcador))), [partes]);
  const semParte = (dados?.marcadores ?? []).filter((m) => !comParte.has(normalizar(m.nome)));

  if (!idProduto) {
    return <Card className="p-5 text-sm text-muted-foreground">Salve o produto primeiro para montar o roteiro de gravação.</Card>;
  }
  if (!dados) return <Carregando erro={erro} />;

  const modo = modoMidia ?? dados.produto.modo_midia ?? "texto";
  const publicado = dados.produto.status === "publicado";
  const ativas = partes.filter((p) => p.ativo);
  const conta = (s: Secao) => ativas.filter((p) => p.secao === s).length;
  const inativas = partes.length - ativas.length;

  const trocarParte = (nova: ParteRoteiro) =>
    setDados((d) => (d ? { ...d, partes: d.partes.map((p) => (p.id === nova.id ? nova : p)) } : d));

  const puxar = async () => {
    setPuxando(true);
    try {
      const { criadas, ...resto } = await enviar<Roteiro & { criadas: number }>(`/admin/biblioteca/produtos/${idProduto}/roteiro/puxar`, {});
      setDados(resto);
      if (criadas > 0) toast.success(criadas === 1 ? "1 parte criada a partir do prompt." : `${criadas} partes criadas a partir do prompt.`,
        { description: "Agora escreva o texto que o escritório vai ler em cada uma." });
      else toast.success("Nada novo: todos os marcadores do prompt já têm parte.");
    } catch (e) {
      toast.error("Não deu para puxar do prompt", { description: (e as Error).message });
    } finally { setPuxando(false); }
  };

  const novaParte = async (secao: Secao) => {
    setCriando(true);
    try {
      const parte = await enviar<ParteRoteiro>(`/admin/biblioteca/produtos/${idProduto}/roteiro/partes`,
        { titulo: "Nova parte", secao, tipo: secao === "videos" ? "video" : "audio" });
      setDados((d) => (d ? { ...d, partes: [...d.partes, parte] } : d));
      setNovaId(parte.id);
    } catch (e) {
      toast.error("Não deu para criar a parte", { description: (e as Error).message });
    } finally { setCriando(false); }
  };

  const mover = async (parte: ParteRoteiro, direcao: -1 | 1) => {
    const daSecao = partes.filter((p) => p.secao === parte.secao);
    const i = daSecao.findIndex((p) => p.id === parte.id);
    const j = i + direcao;
    if (i < 0 || j < 0 || j >= daSecao.length) return;
    const trocada = [...daSecao];
    [trocada[i], trocada[j]] = [trocada[j], trocada[i]];
    const ids = SECOES.flatMap((s) => (s.v === parte.secao ? trocada : partes.filter((p) => p.secao === s.v)).map((p) => p.id));
    setMovendo(true);
    try {
      const r = await enviar<{ partes: ParteRoteiro[] }>(`/admin/biblioteca/produtos/${idProduto}/roteiro/ordem`, { ids });
      setDados((d) => (d ? { ...d, partes: r.partes } : d));
    } catch (e) {
      toast.error("Não deu para mudar a ordem", { description: (e as Error).message });
      recarregar();
    } finally { setMovendo(false); }
  };

  const apagar = async (parte: ParteRoteiro) => {
    const ok = await confirmar({
      titulo: `Excluir "${parte.titulo}"?`, perigo: true, confirmar: "Excluir",
      texto: "A parte some do roteiro deste produto. O que os escritórios já gravaram continua na biblioteca de mídia deles.",
    });
    if (!ok) return;
    try {
      await api(`/admin/roteiro/partes/${parte.id}`, { metodo: "DELETE" });
      apagadas.current.add(parte.id);
      setDados((d) => (d ? { ...d, partes: d.partes.filter((p) => p.id !== parte.id) } : d));
      toast.success("Parte excluída.");
    } catch (e) {
      toast.error("Não deu para excluir", { description: (e as Error).message });
    }
  };

  // Uma lista só (cabeçalhos de seção no meio): o cartão que muda de seção só muda de lugar e não perde o que está digitado.
  const linhas: ReactNode[] = [];
  for (const s of SECOES) {
    const daSecao = partes.filter((p) => p.secao === s.v);
    linhas.push(
      <div key={`secao-${s.v}`} className="flex items-end justify-between gap-3 pt-3 first:pt-0">
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="size-8 rounded-lg grid place-items-center shrink-0 bg-[#E6F5EB] text-[#00852A]"><s.Icone className="size-4" /></div>
          <div className="min-w-0">
            <h4 className="text-[14px] font-semibold text-[#0C1811]">{s.titulo} <span className="text-[#69786F] font-normal">({daSecao.length})</span></h4>
            <p className="text-[11.5px] text-[#69786F]">{s.texto}</p>
          </div>
        </div>
        <Button variant="outline" size="sm" disabled={criando} onClick={() => novaParte(s.v)} className="shrink-0">
          <Plus className="size-3.5 mr-1" /> Adicionar
        </Button>
      </div>,
    );
    if (daSecao.length === 0) {
      linhas.push(<div key={`vazio-${s.v}`} className="rounded-xl border border-dashed border-[#E2E9E4] p-5 text-center text-[13px] text-[#69786F]">
        Nenhuma parte nesta seção.</div>);
    }
    daSecao.forEach((p, i) => linhas.push(
      <ParteCartao key={p.id} parte={p} marcadores={dados.marcadores} gerais={dados.gerais} focar={novaId === p.id}
        primeiro={i === 0} ultimo={i === daSecao.length - 1} movendo={movendo}
        aoMudar={trocarParte} aoMover={(d) => mover(p, d)} aoApagar={() => apagar(p)}
        foiApagada={() => apagadas.current.has(p.id)} />,
    ));
  }

  return (
    <div className="space-y-4">
      {(modo !== "audio" || !publicado) && (
        <div role="status" className="flex items-start gap-3 rounded-xl border border-amber-300/80 bg-amber-50 p-3.5 text-amber-900">
          <AlertTriangle className="size-4 mt-0.5 shrink-0 text-amber-600" />
          <div className="text-[12.5px] leading-relaxed">
            <strong className="font-semibold">O escritório ainda não vê este roteiro.</strong>{" "}
            Ele só aparece em produtos com mídia e publicados.
            {modo !== "audio" && <> Este produto está <strong>só com texto</strong>: ligue “Produto com mídia” na aba Identidade e salve.</>}
            {!publicado && <> O produto ainda não está publicado.</>}
          </div>
        </div>
      )}

      {/* Resumo + puxar do prompt */}
      <Card className="p-5 space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-start gap-3 min-w-0">
            <div className="size-9 rounded-xl grid place-items-center shrink-0 text-white" style={{ backgroundImage: "linear-gradient(135deg, #3BE062, #00BC33)" }}>
              <Mic className="size-[18px]" />
            </div>
            <div className="min-w-0">
              <h3 className="text-base font-semibold text-[#0C1811]">Roteiro de gravação</h3>
              <p className="text-xs text-[#69786F] mt-0.5">O que o escritório grava com a própria voz. Cada parte preenche um marcador do prompt.</p>
            </div>
          </div>
          <div className="flex flex-col items-end gap-1">
            <Button onClick={puxar} disabled={puxando} className="text-white shadow-sm" style={{ backgroundImage: "linear-gradient(135deg, #3BE062, #00BC33)" }}>
              {puxando ? <Loader2 className="size-4 mr-1.5 animate-spin" /> : <Wand2 className="size-4 mr-1.5" />}
              Puxar do prompt
              {semParte.length > 0 && <span className="ml-1.5 rounded-full bg-white/25 px-1.5 text-[11px] font-semibold leading-5">{semParte.length}</span>}
            </Button>
            <span className="text-[11px] text-[#69786F]">
              {semParte.length === 0 ? "Todos os marcadores do prompt já têm parte." : semParte.length === 1 ? "1 marcador do prompt ainda sem parte." : `${semParte.length} marcadores do prompt ainda sem parte.`}
            </span>
          </div>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
          <Numero valor={conta("videos")} rotulo={conta("videos") === 1 ? "vídeo" : "vídeos"} />
          <Numero valor={conta("principais")} rotulo={conta("principais") === 1 ? "áudio principal" : "áudios principais"} />
          <Numero valor={conta("objecoes")} rotulo={conta("objecoes") === 1 ? "objeção" : "objeções"} />
          <Numero valor={dados.gravacoes} rotulo={dados.gravacoes === 1 ? "gravação recebida" : "gravações recebidas"} destaque />
        </div>
        {inativas > 0 && <p className="text-[11.5px] text-[#69786F]">{inativas === 1 ? "1 parte desligada não entra na conta." : `${inativas} partes desligadas não entram na conta.`}</p>}

        {semParte.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[11.5px] text-[#69786F] mr-1">Sem parte:</span>
            {semParte.map((m) => (
              <span key={m.nome} className="inline-flex items-center gap-1 rounded-full border border-[#E2E9E4] bg-white px-2 py-0.5 text-[11.5px] text-[#0C1811]">
                {m.tipo === "video" ? <Video className="size-3 text-[#69786F]" /> : <Mic className="size-3 text-[#69786F]" />}{m.nome}
              </span>
            ))}
          </div>
        )}
        <p className="text-[11px] text-[#69786F] flex items-start gap-1.5">
          <Info className="size-3.5 mt-px shrink-0" />
          Lê os marcadores [[audio:…]] e [[video:…]] do que está salvo. Mudou o prompt? Salve o produto antes de puxar.
        </p>
      </Card>

      <Orientacoes idProduto={idProduto} inicial={dados.produto.roteiro_orientacoes ?? ""}
        aoSalvar={(texto) => setDados((d) => (d ? { ...d, produto: { ...d.produto, roteiro_orientacoes: texto || null } } : d))} />

      {/* Partes */}
      <Card className="p-5 space-y-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h3 className="text-base font-semibold text-[#0C1811]">Partes do roteiro</h3>
            <p className="text-xs text-[#69786F] mt-0.5">Título, texto para ler e o marcador que cada gravação preenche. Salva sozinho ao sair do campo.</p>
          </div>
          <Button variant="outline" disabled={criando} onClick={() => novaParte("principais")} className="shrink-0">
            {criando ? <Loader2 className="size-4 mr-1.5 animate-spin" /> : <Plus className="size-4 mr-1.5" />} Nova parte
          </Button>
        </div>
        <div className="space-y-3">{linhas}</div>
      </Card>

      {/* Vozes prontas: recarrega quando as partes mudam (título, seção, tipo, ligada) */}
      <VozesProntasEditor idProduto={idProduto}
        versaoPartes={partes.map((p) => `${p.id}:${p.titulo}:${p.secao}:${p.tipo}:${p.ativo ? 1 : 0}`).join("|")} />
      {janelaConfirmar}
    </div>
  );
}

function Numero({ valor, rotulo, destaque }: { valor: number; rotulo: string; destaque?: boolean }) {
  return (
    <div className={`rounded-xl border px-3 py-2.5 ${destaque ? "border-[#00BC33]/40 bg-[#E6F5EB]" : "border-[#E2E9E4] bg-white"}`}>
      <div className={`text-xl font-semibold tabular-nums ${destaque ? "text-[#00852A]" : "text-[#0C1811]"}`}>{valor}</div>
      <div className="text-[11.5px] text-[#69786F]">{rotulo}</div>
    </div>
  );
}

// ------------------------------------------------------------------------------------------------- orientações
function Orientacoes({ idProduto, inicial, aoSalvar }: { idProduto: string; inicial: string; aoSalvar: (texto: string) => void }) {
  const [texto, setTexto] = useState(inicial);
  const [salvo, setSalvo] = useState(inicial);
  const [salvando, setSalvando] = useState(false);
  const [acabouDeSalvar, setAcabouDeSalvar] = useState(false);
  const mudou = texto.trim() !== salvo.trim();
  // Valor atual e salvo em ref: ao sair da tela (trocar de aba) o que não foi salvo é enviado.
  const textoRef = useRef(texto);
  const salvoRef = useRef(salvo);
  textoRef.current = texto;
  const aoSalvarRef = useRef(aoSalvar);
  aoSalvarRef.current = aoSalvar;

  useEffect(() => () => {
    const pendente = textoRef.current;
    if (pendente.trim() === salvoRef.current.trim()) return;
    salvoRef.current = pendente;
    enviar(`/admin/biblioteca/produtos/${idProduto}/roteiro/orientacoes`, { texto: pendente }, "PUT")
      .then(() => aoSalvarRef.current(pendente.trim()))
      .catch((e) => toast.error("Não deu para salvar as orientações", { description: (e as Error).message }));
  }, [idProduto]);

  const salvar = async () => {
    setSalvando(true);
    try {
      await enviar(`/admin/biblioteca/produtos/${idProduto}/roteiro/orientacoes`, { texto }, "PUT");
      salvoRef.current = texto;
      setSalvo(texto);
      aoSalvar(texto.trim());
      setAcabouDeSalvar(true);
    } catch (e) {
      toast.error("Não deu para salvar as orientações", { description: (e as Error).message });
    } finally { setSalvando(false); }
  };

  return (
    <Card className="p-5 space-y-3">
      <div>
        <h3 className="text-base font-semibold text-[#0C1811]">Orientações</h3>
        <p className="text-xs text-[#69786F] mt-0.5">Aparece para o escritório antes de começar a gravar (lugar calmo, celular perto da boca, falar devagar…).</p>
      </div>
      <Textarea value={texto} maxLength={8000} onChange={(e) => { setTexto(e.target.value); setAcabouDeSalvar(false); }}
        placeholder="Ex.: Grave num lugar sem barulho, com o celular a um palmo da boca. Leia com calma, do seu jeito; pode trocar uma palavra ou outra."
        className="min-h-[110px] text-[13.5px] leading-relaxed" />
      <div className="flex items-center justify-end gap-3">
        {mudou ? <span className="text-[11.5px] text-amber-700">Alterações não salvas</span>
          : acabouDeSalvar ? <span className="inline-flex items-center gap-1 text-[11.5px] font-medium text-[#00852A]"><Check className="size-3.5" />Salvo</span> : null}
        <Button size="sm" disabled={!mudou || salvando} onClick={salvar}>
          {salvando ? <Loader2 className="size-3.5 mr-1.5 animate-spin" /> : <Save className="size-3.5 mr-1.5" />} Salvar orientações
        </Button>
      </div>
    </Card>
  );
}

// ------------------------------------------------------------------------------------------------- cartão da parte
type Rascunho = { titulo: string; texto: string; tipo: Tipo; secao: Secao; marcador: string; geral: boolean; chave: string; ativo: boolean };
const rascunhoDe = (p: ParteRoteiro): Rascunho => ({
  titulo: p.titulo, texto: p.texto ?? "", tipo: p.tipo, secao: p.secao, marcador: p.marcador ?? "",
  geral: Boolean(p.chave_geral), chave: p.chave_geral ?? "", ativo: p.ativo,
});

/** O que o rascunho tem de diferente do que está salvo, no formato do PATCH. */
function diferencas(r: Rascunho, s: ParteRoteiro): Record<string, unknown> {
  const m: Record<string, unknown> = {};
  if (r.titulo.trim() && r.titulo.trim() !== s.titulo) m.titulo = r.titulo.trim();
  if (r.texto !== (s.texto ?? "")) m.texto = r.texto;
  if (r.tipo !== s.tipo) m.tipo = r.tipo;
  if (r.secao !== s.secao) m.secao = r.secao;
  if (r.ativo !== s.ativo) m.ativo = r.ativo;
  if (r.marcador.trim() !== (s.marcador ?? "")) m.marcador = r.marcador.trim();   // "" tira o marcador
  if (!r.geral && s.chave_geral) m.chave_geral = "";                                  // "" tira a chave
  if (r.geral && r.chave.trim() && chaveNormalizada(r.chave) !== (s.chave_geral ?? "")) m.chave_geral = r.chave.trim();
  return m;
}

type Estado = "parado" | "salvando" | "salvo" | "erro";

function ParteCartao({ parte, marcadores, gerais, focar, primeiro, ultimo, movendo, aoMudar, aoMover, aoApagar, foiApagada }: {
  parte: ParteRoteiro; marcadores: Marcador[]; gerais: Geral[]; focar: boolean; primeiro: boolean; ultimo: boolean; movendo: boolean;
  aoMudar: (p: ParteRoteiro) => void; aoMover: (direcao: -1 | 1) => void; aoApagar: () => void; foiApagada: () => boolean;
}) {
  const [r, setR] = useState<Rascunho>(() => rascunhoDe(parte));
  const rRef = useRef(r);
  const salvoRef = useRef(parte);                       // última versão que o servidor devolveu
  const fila = useRef<Promise<void>>(Promise.resolve());
  const [estado, setEstado] = useState<Estado>("parado");
  const [enviandoExemplo, setEnviandoExemplo] = useState(false);
  const arquivo = useRef<HTMLInputElement>(null);
  const tituloRef = useRef<HTMLInputElement>(null);
  const idLista = useId();
  const idListaGerais = useId();

  // Mudou por fora (ordem, exemplo, puxar): acompanha o que o servidor tem nos campos que não estão sendo editados.
  useEffect(() => {
    const antes = salvoRef.current;
    salvoRef.current = parte;
    const atual = rRef.current;
    const deAntes = rascunhoDe(antes), deAgora = rascunhoDe(parte);
    const novo = { ...atual };
    (Object.keys(deAgora) as (keyof Rascunho)[]).forEach((k) => {
      if (atual[k] === deAntes[k]) (novo as Record<string, unknown>)[k] = deAgora[k];
    });
    rRef.current = novo;
    setR(novo);
  }, [parte]);

  // Ao sair (trocar de aba do editor, fechar): o cartão some antes do onBlur salvar. Manda o que ficou pendente,
  // na mesma fila, sem mexer no estado do cartão (já desmontado). Parte excluída não salva.
  const aoMudarRef = useRef(aoMudar);
  aoMudarRef.current = aoMudar;
  const foiApagadaRef = useRef(foiApagada);
  foiApagadaRef.current = foiApagada;
  useEffect(() => () => {
    fila.current = fila.current.then(async () => {
      if (foiApagadaRef.current()) return;
      const enviado = rRef.current;
      const corpo = diferencas(enviado, salvoRef.current);
      if (Object.keys(corpo).length === 0) return;
      try {
        const nova = await enviar<ParteRoteiro>(`/admin/roteiro/partes/${parte.id}`, corpo, "PATCH");
        salvoRef.current = nova;
        aoMudarRef.current(nova);
      } catch (e) {
        toast.error(`Não deu para salvar "${enviado.titulo.trim() || salvoRef.current.titulo}"`, { description: (e as Error).message });
      }
    });
  }, [parte.id]);

  useEffect(() => {
    if (focar) { tituloRef.current?.focus(); tituloRef.current?.select(); tituloRef.current?.scrollIntoView({ block: "center", behavior: "smooth" }); }
  }, [focar]);

  const salvar = () => {
    fila.current = fila.current.then(async () => {
      const enviado = rRef.current;
      const corpo = diferencas(enviado, salvoRef.current);
      if (Object.keys(corpo).length === 0) return;
      setEstado("salvando");
      try {
        const nova = await enviar<ParteRoteiro>(`/admin/roteiro/partes/${parte.id}`, corpo, "PATCH");
        salvoRef.current = nova;
        // Campos que não mudaram enquanto salvava ficam com o valor do servidor (ex.: chave já normalizada).
        const agora = rRef.current, doServidor = rascunhoDe(nova);
        const ajustado = { ...agora };
        (Object.keys(doServidor) as (keyof Rascunho)[]).forEach((k) => {
          if (agora[k] === enviado[k] && !(k === "chave" && agora.geral && !doServidor.geral)) (ajustado as Record<string, unknown>)[k] = doServidor[k];
        });
        if (agora.geral && !nova.chave_geral) ajustado.geral = true;      // ligou "geral" e ainda não digitou a chave
        rRef.current = ajustado;
        setR(ajustado);
        aoMudar(nova);
        setEstado("salvo");
      } catch (e) {
        setEstado("erro");
        toast.error(`Não deu para salvar "${enviado.titulo.trim() || parte.titulo}"`, { description: (e as Error).message });
      }
    });
  };

  const mudar = (m: Partial<Rascunho>, salvarJa = false) => {
    const novo = { ...rRef.current, ...m };
    rRef.current = novo;
    setR(novo);
    if (estado === "salvo") setEstado("parado");
    if (salvarJa) salvar();
  };

  const pendente = Object.keys(diferencas(r, salvoRef.current)).length > 0;
  const achado = marcadores.find((m) => normalizar(m.nome) === normalizar(r.marcador));
  const geralUsada = gerais.find((g) => g.chave_geral === (parte.chave_geral ?? ""));

  const enviarExemplo = async (f: File | undefined) => {
    if (!f) return;
    if (f.size > LIMITE_EXEMPLO_MB * 1024 * 1024) { toast.error(`Arquivo grande demais (máximo ${LIMITE_EXEMPLO_MB} MB).`); return; }
    setEnviandoExemplo(true);
    try {
      const conteudo_base64 = await lerBase64(f);
      const nova = await enviar<ParteRoteiro>(`/admin/roteiro/partes/${parte.id}/exemplo`, { conteudo_base64, mime: f.type || null, nome: f.name });
      aoMudar(nova);
      toast.success("Exemplo enviado.");
    } catch (e) {
      toast.error("Não deu para enviar o exemplo", { description: (e as Error).message });
    } finally {
      setEnviandoExemplo(false);
      if (arquivo.current) arquivo.current.value = "";
    }
  };

  const tirarExemplo = async () => {
    setEnviandoExemplo(true);
    try {
      aoMudar(await api<ParteRoteiro>(`/admin/roteiro/partes/${parte.id}/exemplo`, { metodo: "DELETE" }));
    } catch (e) {
      toast.error("Não deu para tirar o exemplo", { description: (e as Error).message });
    } finally { setEnviandoExemplo(false); }
  };

  return (
    <div className={`rounded-xl border bg-white p-4 space-y-3.5 transition-opacity ${r.ativo ? "border-[#E2E9E4]" : "border-dashed border-[#E2E9E4] opacity-70"}`}>
      {/* topo: título + ações */}
      <div className="flex items-start gap-2">
        <div className="flex-1 min-w-0 space-y-1">
          <label className="text-[11.5px] font-medium text-[#69786F]" htmlFor={`${idLista}-titulo`}>Título</label>
          <Input id={`${idLista}-titulo`} ref={tituloRef} value={r.titulo} maxLength={160}
            onChange={(e) => mudar({ titulo: e.target.value })}
            onBlur={() => { if (!rRef.current.titulo.trim()) mudar({ titulo: salvoRef.current.titulo }); else salvar(); }}
            className="font-semibold text-[#0C1811]" placeholder="Ex.: Explicação dos honorários" />
        </div>
        <div className="flex items-center gap-1 pt-6 shrink-0">
          <Indicador estado={estado} pendente={pendente} aoTentar={salvar} />
          <IconeBotao rotulo="Subir" desligado={primeiro || movendo} aoClicar={() => aoMover(-1)}><ArrowUp className="size-4" /></IconeBotao>
          <IconeBotao rotulo="Descer" desligado={ultimo || movendo} aoClicar={() => aoMover(1)}><ArrowDown className="size-4" /></IconeBotao>
          <IconeBotao rotulo="Excluir parte" perigo aoClicar={aoApagar}><Trash2 className="size-4" /></IconeBotao>
        </div>
      </div>

      {/* tipo / seção / ativo */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2.5">
        <Pilulas rotulo="Tipo" valor={r.tipo} aoMudar={(v) => mudar({ tipo: v }, true)}
          opcoes={[{ v: "audio", l: "Áudio", Icone: Mic }, { v: "video", l: "Vídeo", Icone: Video }]} />
        <Pilulas rotulo="Seção" valor={r.secao} aoMudar={(v) => mudar({ secao: v }, true)}
          opcoes={[{ v: "videos", l: "Vídeos" }, { v: "principais", l: "Principais" }, { v: "objecoes", l: "Objeção" }]} />
        <label className="ml-auto inline-flex items-center gap-2 text-[12.5px] text-[#0C1811]">
          <Switch checked={r.ativo} onCheckedChange={(v) => mudar({ ativo: v }, true)} aria-label="Parte ligada" />
          {r.ativo ? "Ligada" : "Desligada"}
        </label>
      </div>

      {/* texto para ler */}
      <div className="space-y-1">
        <label className="text-[11.5px] font-medium text-[#69786F]" htmlFor={`${idLista}-texto`}>Texto para ler</label>
        <Textarea id={`${idLista}-texto`} value={r.texto} maxLength={20000} onChange={(e) => mudar({ texto: e.target.value })} onBlur={salvar}
          placeholder="O que o escritório vai falar na gravação, do jeito que deve soar."
          className="min-h-[150px] text-[13.5px] leading-relaxed" />
      </div>

      <div className="grid md:grid-cols-2 gap-3.5">
        {/* marcador */}
        <div className="space-y-1">
          <label className="text-[11.5px] font-medium text-[#69786F]" htmlFor={`${idLista}-marcador`}>Marcador do prompt</label>
          <Input id={`${idLista}-marcador`} list={`${idLista}-lista`} value={r.marcador} maxLength={160}
            onChange={(e) => mudar({ marcador: e.target.value })} onBlur={salvar} placeholder="Escolha ou digite (ex.: Honorários)" />
          <datalist id={`${idLista}-lista`}>
            {marcadores.map((m) => <option key={m.nome} value={m.nome}>{m.tipo === "video" ? "vídeo" : "áudio"}</option>)}
          </datalist>
          <p className="text-[11px] leading-snug">
            {!r.marcador.trim() ? <span className="text-[#69786F]">Sem marcador: a gravação não entra sozinha em nenhum ponto do prompt.</span>
              : achado ? <span className="text-[#00852A]">Está no prompt como [[{achado.tipo === "video" ? "video" : "audio"}:{achado.nome}]]
                {achado.tipo !== r.tipo && <span className="text-amber-700"> (no prompt é {achado.tipo === "video" ? "vídeo" : "áudio"})</span>}</span>
              : <span className="text-amber-700">Esse marcador não está no prompt salvo.</span>}
          </p>
        </div>

        {/* parte geral */}
        <div className="space-y-1.5">
          <label className="flex items-center justify-between gap-2 text-[11.5px] font-medium text-[#69786F]">
            Parte geral
            <Switch checked={r.geral} aria-label="Parte geral"
              onCheckedChange={(v) => mudar(v ? { geral: true } : { geral: false, chave: "" }, !v)} />
          </label>
          {r.geral ? (
            <>
              <Input list={idListaGerais} value={r.chave} maxLength={60} onChange={(e) => mudar({ chave: e.target.value })} onBlur={salvar}
                placeholder="Chave (ex.: video_inicial)" className="font-mono text-[13px]" aria-label="Chave da parte geral" />
              <datalist id={idListaGerais}>
                {gerais.map((g) => <option key={g.chave_geral} value={g.chave_geral}>{`${g.titulo} · ${g.produtos} ${g.produtos === 1 ? "parte" : "partes"}`}</option>)}
              </datalist>
              {gerais.length > 0 && !r.chave && (
                <div className="flex flex-wrap gap-1">
                  {gerais.slice(0, 8).map((g) => (
                    <button key={g.chave_geral} type="button" onClick={() => { mudar({ chave: g.chave_geral }); salvar(); }}
                      className="rounded-full border border-[#E2E9E4] bg-white px-2 py-0.5 font-mono text-[11px] text-[#0C1811] hover:border-[#00BC33]">
                      {g.chave_geral}
                    </button>
                  ))}
                </div>
              )}
            </>
          ) : null}
          <p className="text-[11px] leading-snug text-[#69786F]">
            Gravada uma vez, vale para todos os produtos com a mesma chave.
            {r.geral && geralUsada && geralUsada.produtos > 1 && <span className="text-[#00852A]"> Esta chave está em {geralUsada.produtos} partes.</span>}
            {r.geral && !r.chave.trim() && <span className="text-amber-700"> Digite a chave para salvar.</span>}
          </p>
        </div>
      </div>

      {/* exemplo de referência */}
      <div className="rounded-lg border border-[#E2E9E4] bg-[#F7FAF8] p-3 space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="min-w-0">
            <div className="text-[12.5px] font-semibold text-[#0C1811]">Exemplo de referência</div>
            <div className="text-[11px] text-[#69786F]">Como deve soar. O escritório pode ouvir antes de gravar.</div>
          </div>
          <div className="flex items-center gap-1.5">
            <input ref={arquivo} type="file" className="hidden" accept={r.tipo === "video" ? "video/*" : "audio/*"}
              onChange={(e) => enviarExemplo(e.target.files?.[0])} />
            <Button variant="outline" size="sm" disabled={enviandoExemplo} onClick={() => arquivo.current?.click()}>
              {enviandoExemplo ? <Loader2 className="size-3.5 mr-1.5 animate-spin" /> : <Upload className="size-3.5 mr-1.5" />}
              {parte.exemplo_url ? "Trocar" : r.tipo === "video" ? "Enviar vídeo" : "Enviar áudio"}
            </Button>
            {parte.exemplo_url && (
              <Button variant="ghost" size="sm" disabled={enviandoExemplo} onClick={tirarExemplo} className="text-[#69786F]">
                <X className="size-3.5 mr-1" /> Tirar
              </Button>
            )}
          </div>
        </div>
        {parte.exemplo_url && (ehVideo(parte.exemplo_url)
          ? <video controls preload="metadata" src={parte.exemplo_url} className="w-full max-w-md rounded-lg bg-black" />
          : <audio controls preload="metadata" src={parte.exemplo_url} className="w-full max-w-md" />)}
      </div>
    </div>
  );
}

function Indicador({ estado, pendente, aoTentar }: { estado: Estado; pendente: boolean; aoTentar: () => void }) {
  if (estado === "salvando") return <span className="inline-flex items-center gap-1 px-1.5 text-[11px] text-[#69786F]"><Loader2 className="size-3 animate-spin" />Salvando</span>;
  if (estado === "erro") return <button type="button" onClick={aoTentar} className="px-1.5 text-[11px] font-medium text-red-600 underline">Tentar de novo</button>;
  if (pendente) return <span className="px-1.5 text-[11px] text-amber-700">Não salvo</span>;
  if (estado === "salvo") return <span className="inline-flex items-center gap-1 px-1.5 text-[11px] font-medium text-[#00852A]"><Check className="size-3" />Salvo</span>;
  return null;
}

function IconeBotao({ rotulo, desligado, perigo, aoClicar, children }: { rotulo: string; desligado?: boolean; perigo?: boolean; aoClicar: () => void; children: ReactNode }) {
  return (
    <button type="button" title={rotulo} aria-label={rotulo} disabled={desligado} onClick={aoClicar}
      className={`grid size-8 place-items-center rounded-lg text-[#69786F] transition-colors disabled:opacity-35 disabled:cursor-not-allowed ${perigo ? "hover:bg-red-50 hover:text-red-600" : "hover:bg-[#E6F5EB] hover:text-[#00852A]"}`}>
      {children}
    </button>
  );
}

function Pilulas<T extends string>({ rotulo, valor, opcoes, aoMudar }: {
  rotulo: string; valor: T; opcoes: { v: T; l: string; Icone?: typeof Mic }[]; aoMudar: (v: T) => void;
}) {
  return (
    <div className="inline-flex items-center gap-2">
      <span className="text-[11.5px] font-medium text-[#69786F]">{rotulo}</span>
      <div role="radiogroup" aria-label={rotulo} className="inline-flex rounded-full border border-[#E2E9E4] bg-[#F7FAF8] p-0.5">
        {opcoes.map((o) => {
          const on = o.v === valor;
          return (
              <button key={o.v} type="button" role="radio" aria-checked={on} onClick={() => { if (!on) aoMudar(o.v); }}
                className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[12px] font-medium transition-colors ${on ? "bg-white text-[#00852A] shadow-sm ring-1 ring-[#00BC33]/40" : "text-[#69786F] hover:text-[#0C1811]"}`}>
                {o.Icone && <o.Icone className="size-3.5" />}{o.l}
              </button>
          );
        })}
      </div>
    </div>
  );
}
