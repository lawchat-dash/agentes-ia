import { Fragment, useEffect, useState, type ReactNode } from "react";
import { BellRing, CheckCheck, Eye, Plus, Save, Send, Trash2, X } from "lucide-react";
import { api, enviar } from "../api";
import { Alerta, Cabecalho, Carregando, Interruptor, Painel, Vazio, useAcao, useAvisar, useCarregar, useConfirmar } from "../componentes/ui";
import { useSessao } from "../sessao";

interface Destinatario { rotulo: string; numero: string }
interface Aviso { tipo_evento: string; nome: string; habilitada: boolean; modelo_mensagem: string; destinatarios: Destinatario[] }
interface Dados { eventos: Record<string, string>; avisos: Aviso[]; modelo_padrao: string; marcadores: string[] }

/** Avisos por WhatsApp para a equipe do escritório quando algo acontece no atendimento. */
export function TelaAvisos() {
  const { escritorio } = useSessao();
  const { dados, erro, recarregar } = useCarregar<Dados>("/notificacoes", [escritorio]);
  const [escolhido, setEscolhido] = useState<string | null>(null);
  if (!dados) return <Carregando erro={erro} />;
  const configurados = new Map(dados.avisos.map((a) => [a.tipo_evento, a]));
  const livres = Object.entries(dados.eventos).filter(([codigo]) => !configurados.has(codigo));
  const novoEscolhido = escolhido !== null && !configurados.has(escolhido);

  return (
    <>
      <Cabecalho eyebrow="Configurar" titulo="Avisos à equipe"
        texto="Quando algo acontecer no atendimento, a equipe recebe uma mensagem no WhatsApp. Ligue a função &quot;Avisar a equipe&quot; no agente para valer." />
      {/* Aqui a lista é curta e o editor é que precisa de espaço: proporção invertida em relação ao .two padrão. */}
      <div className="two min-[1001px]:!grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)]">
        <Painel titulo="Avisos" sem_corpo acoes={
          <select className="inp" aria-label="Novo aviso" value="" style={{ maxWidth: 200 }} onChange={(e) => e.target.value && setEscolhido(e.target.value)}>
            <option value="">+ Novo aviso…</option>
            {livres.map(([codigo, nome]) => <option key={codigo} value={codigo}>{nome}</option>)}
          </select>}>
          {dados.avisos.length === 0 && !novoEscolhido ? <Vazio icone={<BellRing />}>Nenhum aviso ainda. Escolha um evento em "Novo aviso".</Vazio> : (
            <div className="rows">
              {novoEscolhido && (
                <ItemAviso selecionado nome={dados.eventos[escolhido] ?? escolhido} detalhe="Novo · ainda não salvo" ligado aoEscolher={() => undefined} />
              )}
              {dados.avisos.map((a) => (
                <ItemAviso key={a.tipo_evento} selecionado={escolhido === a.tipo_evento} nome={a.nome} ligado={a.habilitada}
                  detalhe={<>{dados.eventos[a.tipo_evento] ?? a.tipo_evento} · {a.destinatarios.length} {a.destinatarios.length === 1 ? "número" : "números"}</>}
                  aoEscolher={() => setEscolhido(a.tipo_evento)} />
              ))}
            </div>
          )}
        </Painel>
        {escolhido ? (
          <EditorAviso key={escolhido} codigo={escolhido} nomeEvento={dados.eventos[escolhido] ?? escolhido}
            atual={configurados.get(escolhido)} modeloPadrao={dados.modelo_padrao} marcadores={dados.marcadores}
            aoMudar={() => recarregar()} aoApagar={() => { setEscolhido(null); recarregar(); }} aoFechar={() => setEscolhido(null)} />
        ) : <Painel titulo="Como funciona"><p className="sec" style={{ margin: 0 }}>
          Escolha um evento (lead qualificado, não sabe ler, contrato assinado…), escreva a mensagem e cadastre quem recebe.
          Os campos entre chaves, como {"{{nome}}"}, viram os dados do lead. Linha com campo vazio não aparece.
          O aviso sai do número do agente, sem abrir atendimento.</p></Painel>}
      </div>
    </>
  );
}

/** Item da lista: o selecionado ganha barra e fundo verdes (diferente do hover, que é só cinza). */
function ItemAviso({ nome, detalhe, ligado, selecionado, aoEscolher }: { nome: string; detalhe: ReactNode; ligado: boolean; selecionado: boolean; aoEscolher: () => void }) {
  return (
    <button type="button" aria-pressed={selecionado} onClick={aoEscolher}
      className={`linha-aviso relative w-full text-left transition-colors ${selecionado
        ? "bg-[var(--acento-suave)] shadow-[inset_3px_0_0_var(--acento)]"
        : "bg-transparent hover:bg-[var(--surface-2)]"}`}>
      <span aria-hidden className="grid size-8 shrink-0 place-items-center rounded-lg"
        style={ligado
          ? { backgroundImage: "linear-gradient(135deg, #2BD45A, var(--acento-forte))", color: "#fff" }
          : { background: "var(--surface-2)", color: "var(--ink-3)", border: "1px solid var(--line)" }}>
        <BellRing size={15} />
      </span>
      <span className="min-w-0 flex-1">
        <b className="block truncate" style={{ color: selecionado ? "#0B7A2A" : "var(--ink)" }}>{nome}</b>
        <span className="block truncate text-[12px]" style={{ color: "var(--ink-3)" }}>{detalhe}</span>
      </span>
      {!ligado && <span className="chip">desligado</span>}
    </button>
  );
}

/** Formatação do WhatsApp na prévia: *negrito*, _itálico_, ~riscado~ (sem HTML cru). */
function formatarWhatsApp(texto: string): ReactNode[] {
  return texto.split(/(\*[^*\n]+\*|_[^_\n]+_|~[^~\n]+~)/g).map((parte, i) => {
    if (parte.length > 2 && parte.startsWith("*") && parte.endsWith("*")) return <b key={i}>{parte.slice(1, -1)}</b>;
    if (parte.length > 2 && parte.startsWith("_") && parte.endsWith("_")) return <i key={i}>{parte.slice(1, -1)}</i>;
    if (parte.length > 2 && parte.startsWith("~") && parte.endsWith("~")) return <s key={i}>{parte.slice(1, -1)}</s>;
    return <Fragment key={i}>{parte}</Fragment>;
  });
}

/** A prévia como ela chega: balão verde de mensagem enviada, sobre o fundo da conversa do WhatsApp. */
function PreviaWhatsApp({ texto, envio, aoFechar }: { texto: string; envio: number | null; aoFechar: () => void }) {
  const hora = new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  return (
    <div className="overflow-hidden rounded-2xl border animate-in fade-in slide-in-from-bottom-2 duration-300" style={{ borderColor: "var(--line)" }} aria-live="polite">
      <div className="flex items-center gap-2 px-3.5 py-2 text-[12.5px] font-semibold text-white" style={{ background: "#075E54" }}>
        <span className="size-2 rounded-full" style={{ background: "#25D366" }} aria-hidden />
        Prévia no WhatsApp
        <button type="button" className="ml-auto grid size-6 place-items-center rounded-md text-white/80 hover:bg-white/10 hover:text-white" aria-label="Fechar prévia" onClick={aoFechar}><X size={14} /></button>
      </div>
      <div className="flex flex-col gap-2 px-3.5 py-4" style={{ background: "#EFEAE2", backgroundImage: "radial-gradient(rgba(0,0,0,.035) 1px, transparent 1px)", backgroundSize: "14px 14px" }}>
        <div className="relative ml-auto max-w-[88%] rounded-lg rounded-tr-none px-3 pb-1.5 pt-2 text-[13.5px] leading-[1.45] shadow-[0_1px_.5px_rgba(11,20,26,.13)]"
          style={{ background: "#D9FDD3", color: "#111B21" }}>
          <div className="whitespace-pre-wrap [overflow-wrap:anywhere]">{formatarWhatsApp(texto)}</div>
          <div className="mt-0.5 flex items-center justify-end gap-1 text-[11px]" style={{ color: "#667781" }}>
            {hora}<CheckCheck size={14} style={{ color: envio ? "#53BDEB" : "#8696A0" }} aria-hidden />
          </div>
        </div>
      </div>
      {envio !== null && (
        <div className="border-t px-3.5 py-2.5" style={{ borderColor: "var(--line)" }}>
          {envio > 0
            ? <Alerta tipo="ok">Teste na fila para {envio} {envio === 1 ? "número" : "números"}. Chega em alguns segundos.</Alerta>
            : <Alerta tipo="warn" titulo="Ninguém recebeu o teste">Nenhum número válido na lista. Confira os números (com DDD), salve e tente de novo.</Alerta>}
        </div>
      )}
    </div>
  );
}

function EditorAviso({ codigo, nomeEvento, atual, modeloPadrao, marcadores, aoMudar, aoApagar, aoFechar }: {
  codigo: string; nomeEvento: string; atual?: Aviso; modeloPadrao: string; marcadores: string[]; aoMudar: () => void; aoApagar: () => void; aoFechar: () => void;
}) {
  const { ocupado, executar } = useAcao();
  const avisar = useAvisar();
  const [confirmar, janelaConfirmar] = useConfirmar();
  const [form, setForm] = useState<Aviso>(atual ?? { tipo_evento: codigo, nome: nomeEvento, habilitada: true, modelo_mensagem: modeloPadrao, destinatarios: [{ rotulo: "", numero: "" }] });
  const [previa, setPrevia] = useState<string | null>(null);
  const [envio, setEnvio] = useState<number | null>(null);
  useEffect(() => { setPrevia(null); setEnvio(null); }, [codigo]);
  const caminho = `/notificacoes/${encodeURIComponent(codigo)}`;
  const mudarDest = (i: number, campo: keyof Destinatario, valor: string) =>
    mudar({ ...form, destinatarios: form.destinatarios.map((d, j) => (j === i ? { ...d, [campo]: valor } : d)) });
  // "Sujo" = mudou algo desde que abriu ou desde o último salvar (a prévia e o teste usam a versão salva).
  const [alterado, setAlterado] = useState(false);
  const mudar = (novo: Aviso) => { setForm(novo); setAlterado(true); };

  const verPrevia = () => executar(async () => {
    setPrevia((await api<{ texto: string }>(`${caminho}/teste`, { metodo: "POST" })).texto);
    setEnvio(null);
  });
  const enviarTeste = () => executar(async () => {
    const r = await api<{ texto: string; enfileirados: number }>(`${caminho}/teste?enviar=true`, { metodo: "POST" });
    setPrevia(r.texto);
    const n = Number(r.enfileirados ?? 0);
    setEnvio(n);
    if (n > 0) avisar(`Teste enviado para ${n} ${n === 1 ? "número" : "números"}.`);
    else avisar("Nenhum número válido recebeu o teste.", "bad");
  });
  const apagar = async () => {
    const sim = await confirmar({
      titulo: "Apagar este aviso?", perigo: true, confirmar: "Apagar aviso",
      texto: <>A equipe deixa de receber <b>{form.nome || nomeEvento}</b> no WhatsApp. A mensagem e a lista de números somem; dá para criar de novo depois.</>,
    });
    if (sim) executar(async () => { await api(caminho, { metodo: "DELETE" }); aoApagar(); }, "Aviso apagado.");
  };

  return (
    <Painel titulo={<h3>{nomeEvento}{!atual && <span className="chip ac" style={{ marginLeft: 8 }}>novo</span>}</h3>} acoes={<>
      <Interruptor rotulo="Aviso ligado" ligado={form.habilitada} aoMudar={(v) => mudar({ ...form, habilitada: v })} />
      {!atual && <button type="button" className="btn ghost sm" aria-label="Descartar novo aviso" onClick={aoFechar}><X /></button>}
    </>}>
      <div className="form">
        <label className="field"><span className="lbl">Nome do aviso</span>
          <input value={form.nome} onChange={(e) => mudar({ ...form, nome: e.target.value })} /></label>
        <label className="field"><span className="lbl">Mensagem</span>
          <textarea className="codigo" rows={8} value={form.modelo_mensagem} onChange={(e) => mudar({ ...form, modelo_mensagem: e.target.value })} />
          <span className="ajuda">Campos: {marcadores.map((m) => <code key={m} style={{ marginRight: 6 }}>{`{{${m}}}`}</code>)} · *negrito*, _itálico_</span></label>
        <div className="field">
          <span className="lbl">Quem recebe</span>
          {form.destinatarios.map((d, i) => (
            <div key={i} style={{ display: "flex", gap: 8 }}>
              <input className="inp" aria-label="Nome de quem recebe" placeholder="Nome (ex.: Dra. Ana)" value={d.rotulo} onChange={(e) => mudarDest(i, "rotulo", e.target.value)} />
              <input className="inp" aria-label="WhatsApp de quem recebe" inputMode="tel" placeholder="(11) 91234-5678" value={d.numero} onChange={(e) => mudarDest(i, "numero", e.target.value)} />
              <button type="button" className="btn ghost sm" aria-label="Tirar número" onClick={() => mudar({ ...form, destinatarios: form.destinatarios.filter((_, j) => j !== i) })}><X /></button>
            </div>
          ))}
          <button type="button" className="btn sm" style={{ alignSelf: "flex-start" }} onClick={() => mudar({ ...form, destinatarios: [...form.destinatarios, { rotulo: "", numero: "" }] })}><Plus />Mais um número</button>
          <span className="ajuda">O número do próprio agente não recebe. Número da API oficial não envia aviso (exige modelo aprovado).</span>
        </div>
        {previa !== null && <PreviaWhatsApp texto={previa} envio={envio} aoFechar={() => { setPrevia(null); setEnvio(null); }} />}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <button type="button" className="btn pri" disabled={ocupado} onClick={() => executar(async () => {
            await enviar(caminho, { ...form, destinatarios: form.destinatarios.filter((d) => d.numero.trim()) }, "PUT");
            setAlterado(false); aoMudar();
          }, "Aviso salvo.")}><Save />Salvar</button>
          <button type="button" className="btn" disabled={ocupado || !atual} title={atual ? "Mostra a mensagem com dados de exemplo" : "Salve antes"} onClick={verPrevia}><Eye />Ver como fica</button>
          <button type="button" className="btn" disabled={ocupado || !atual} title={atual ? "Manda a mensagem de exemplo para os números salvos" : "Salve antes"} onClick={enviarTeste}><Send />Enviar teste</button>
          {atual && <button type="button" className="btn bad" style={{ marginLeft: "auto" }} disabled={ocupado} onClick={apagar}><Trash2 />Apagar</button>}
        </div>
        {atual && alterado && <span style={{ marginTop: -6, fontSize: 12, color: "var(--warn)" }}>Há mudanças não salvas: a prévia e o teste usam a versão salva.</span>}
      </div>
      {janelaConfirmar}
    </Painel>
  );
}
