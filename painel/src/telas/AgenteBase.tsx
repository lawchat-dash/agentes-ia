// Base de conhecimento por papel (docs/BASE_DE_CONHECIMENTO.md): papéis por item e por documento, selo
// "sempre no prompt" / "buscado quando perguntarem" e a lista de perguntas que a IA não achou na base.
import { useState } from "react";
import { CheckCircle2, HelpCircle, X, XCircle } from "lucide-react";
import { api, enviar, quando, type Agente, type ItemBase } from "../api";
import { Carregando, Painel, Vazio, useAcao, useCarregar } from "../componentes/ui";

// Mesmos limites do motor (app/conhecimento.py): FAQ + objeções do papel até 3.000 caracteres ficam fixas no prompt.
const FIXO_FAQ_OBJECOES = 3000;

export function papeisDoAgente(agente: Agente): { codigo: string; nome: string }[] {
  return agente.etapas.filter((e) => e.codigo !== "contrato_assinado").map((e) => ({ codigo: e.codigo, nome: e.nome || e.codigo }));
}

/** Chips para escolher os papéis de um item. Nenhum marcado = todos os papéis. */
export function EscolherPapeis({ papeis, valor, aoMudar, rotulo }: {
  papeis: { codigo: string; nome: string }[]; valor: string[] | undefined; aoMudar: (v: string[]) => void; rotulo: string;
}) {
  const marcados = valor ?? [];
  const trocar = (codigo: string) => aoMudar(marcados.includes(codigo) ? marcados.filter((c) => c !== codigo) : [...marcados, codigo]);
  return (
    <div className="dias" role="group" aria-label={rotulo} style={{ display: "flex", flexWrap: "wrap", gap: 4, alignItems: "center" }}>
      <span className="muted" style={{ fontSize: 12 }}>{marcados.length ? "Só em:" : "Todos os papéis ·"}</span>
      {papeis.map((p) => (
        <button key={p.codigo} type="button" className={`chip ${marcados.includes(p.codigo) ? "ac" : ""}`} aria-pressed={marcados.includes(p.codigo)}
          onClick={() => trocar(p.codigo)}>{p.nome}</button>
      ))}
    </div>
  );
}

function tamanho(item: ItemBase, campo: "pergunta" | "objecao"): number {
  const titulo = item[campo] ?? "";
  return titulo.length + item.resposta.length + 30;
}

/** Por papel: a FAQ e as objeções cabem fixas no prompt, ou vão para a busca? */
export function ResumoFixoOuBuscado({ agente, faq, objecoes }: { agente: Agente; faq: ItemBase[]; objecoes: ItemBase[] }) {
  const papeis = papeisDoAgente(agente);
  if (!papeis.length || (!faq.length && !objecoes.length)) return null;
  const serve = (i: ItemBase, papel: string) => !i.papeis?.length || i.papeis.includes(papel);
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }} aria-label="Como a FAQ e as objeções entram em cada papel">
      {papeis.map((p) => {
        const total = faq.filter((f) => serve(f, p.codigo)).reduce((s, f) => s + tamanho(f, "pergunta"), 0)
          + objecoes.filter((o) => serve(o, p.codigo)).reduce((s, o) => s + tamanho(o, "objecao"), 0);
        if (!total) return null;
        const fixo = total <= FIXO_FAQ_OBJECOES;
        return <span key={p.codigo} className={`chip ${fixo ? "ok" : "info"}`} title={`${total.toLocaleString("pt-BR")} caracteres neste papel`}>
          {p.nome}: {fixo ? "sempre no prompt" : "buscado quando perguntarem"}</span>;
      })}
    </div>
  );
}

/** Lista de pergunta/resposta (FAQ) ou objeção/resposta, com os papéis de cada item. */
export function ItensDaBase({ agente, itens, campo, rotulos, vazio, aoMudar }: {
  agente: Agente; itens: ItemBase[]; campo: "pergunta" | "objecao"; rotulos: [string, string]; vazio: string;
  aoMudar: (l: ItemBase[]) => void;
}) {
  const papeis = papeisDoAgente(agente);
  if (!itens.length) return <Vazio>{vazio}</Vazio>;
  const mudar = (i: number, novo: Partial<ItemBase>) => aoMudar(itens.map((x, j) => (j === i ? { ...x, ...novo } : x)));
  return (
    <div className="form">{itens.map((item, i) => (
      <div key={i} style={{ display: "grid", gap: 6, paddingBottom: 8, borderBottom: "1px solid var(--line)" }}>
        <div className="par">
          <input className="inp" aria-label={rotulos[0]} placeholder={rotulos[0]} value={item[campo] ?? ""}
            onChange={(e) => mudar(i, { [campo]: e.target.value } as Partial<ItemBase>)} />
          <textarea className="inp" rows={2} aria-label={rotulos[1]} placeholder={rotulos[1]} value={item.resposta}
            onChange={(e) => mudar(i, { resposta: e.target.value })} />
          <button className="btn ghost sm" aria-label="Tirar" onClick={() => aoMudar(itens.filter((_, j) => j !== i))}><X /></button>
        </div>
        {papeis.length > 1 && <EscolherPapeis papeis={papeis} valor={item.papeis} rotulo={`Papéis de ${rotulos[0].toLowerCase()} ${i + 1}`}
          aoMudar={(v) => mudar(i, { papeis: v })} />}
      </div>
    ))}</div>
  );
}

interface Lacuna { id: string; papel: string | null; pergunta: string; vezes: number; ultima_em: string }

/** Perguntas que a IA não achou na base nem no prompt: responder vira FAQ; ignorar tira da lista. */
export function PerguntasSemResposta({ agente, aoVirarFaq }: { agente: Agente; aoVirarFaq: () => void }) {
  const { dados, erro, recarregar } = useCarregar<Lacuna[]>(`/agentes/${agente.id}/lacunas`, [agente.id]);
  const { ocupado, executar } = useAcao();
  const [respostas, setRespostas] = useState<Record<string, string>>({});
  const nomes = Object.fromEntries(papeisDoAgente(agente).map((p) => [p.codigo, p.nome]));
  const responder = (l: Lacuna) => executar(async () => {
    await enviar(`/agentes/${agente.id}/lacunas/${l.id}/responder`, { resposta: respostas[l.id] ?? "", papeis: l.papel ? [l.papel] : [] });
    recarregar(); aoVirarFaq();
  }, "Virou pergunta frequente. Vale a partir da próxima mensagem.");
  const ignorar = (l: Lacuna) => executar(async () => {
    await api(`/agentes/${agente.id}/lacunas/${l.id}/ignorar`, { metodo: "POST" }); recarregar();
  }, "Pergunta tirada da lista.");
  return (
    <Painel titulo="Perguntas sem resposta">
      <p className="sec" style={{ marginTop: 0 }}>O que os leads perguntaram e a IA não achou no roteiro, nos dados nem na base. Responda para virar uma pergunta frequente.</p>
      {erro ? <Carregando erro={erro} /> : !dados ? <Carregando /> : dados.length === 0 ? <Vazio icone={<HelpCircle />}>Nenhuma pergunta pendente.</Vazio> : (
        <div className="rows">
          {dados.map((l) => (
            <div key={l.id} style={{ alignItems: "flex-start" }}>
              <HelpCircle className="i" />
              <div style={{ flex: 1, minWidth: 0, display: "grid", gap: 6 }}>
                <div><b>{l.pergunta}</b>
                  <div className="muted" style={{ fontSize: 12 }}>{l.vezes}× · {l.papel ? (nomes[l.papel] ?? l.papel) : "—"} · última {quando(l.ultima_em)}</div></div>
                <textarea className="inp" rows={2} aria-label={`Resposta para: ${l.pergunta}`} placeholder="Resposta do escritório"
                  value={respostas[l.id] ?? ""} onChange={(e) => setRespostas({ ...respostas, [l.id]: e.target.value })} />
              </div>
              <div style={{ display: "grid", gap: 4 }}>
                <button className="btn pri sm" disabled={ocupado || (respostas[l.id] ?? "").trim().length < 2} onClick={() => responder(l)}><CheckCircle2 />Virar FAQ</button>
                <button className="btn sm ghost" disabled={ocupado} onClick={() => ignorar(l)}><XCircle />Ignorar</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </Painel>
  );
}
