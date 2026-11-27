// Admin › Planos: catálogo comercial (mensal, anual pago 1x, limites e recursos) e os adicionais, sempre mensais.
// Fonte: /admin/planos e /admin/adicionais (app/cobranca/rotas.py, migração 017).
import { useState, type ReactNode } from "react";
import { Bot, Check, Crown, Info, MessageSquare, Pencil, Plus, Save, Sparkles, Star, Trash2, UserPlus, Workflow, X, Zap } from "lucide-react";
import { api, enviar } from "@/api";
import { Cabecalho, Carregando, Modal, Vazio, useAcao, useCarregar, useConfirmar } from "@/componentes/ui";
import "./adminPlanos.css";

export interface Plano {
  id: string; codigo: string; nome: string; descricao: string | null; preco_mensal_brl: number; bonus_mensal_brl: number;
  bonus_acumula: boolean; ativo: boolean; ordem: number; escritorios: number;
  preco_anual_brl?: number | null; sob_proposta?: boolean; usuarios?: number; canais_whatsapp?: number; canais_instagram?: number;
  cria_agentes?: boolean; ia_inclusa?: boolean; selo?: string | null; icone?: string | null;
}
interface Adicional { id: string; codigo: string; nome: string; descricao: string | null; preco_mensal_brl: number; icone: string | null; ativo: boolean; ordem: number }

/** Desconto do plano anual (pago 1x) quando o preço anual não foi digitado à mão. */
export const DESCONTO_ANUAL = 0.15;
const reais = (v: number) => v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
export const anualDe = (p: Pick<Plano, "preco_mensal_brl" | "preco_anual_brl">) =>
  p.preco_anual_brl ?? Math.round(p.preco_mensal_brl * 12 * (1 - DESCONTO_ANUAL) * 100) / 100;

const ICONES_PLANO: Record<string, { Icone: typeof Zap; cor: string }> = {
  raio: { Icone: Zap, cor: "#475467" }, brilho: { Icone: Sparkles, cor: "#00A32C" }, coroa: { Icone: Crown, cor: "#7C3AED" },
  estrela: { Icone: Star, cor: "#C2410C" },
};
const ICONES_ADICIONAL: Record<string, typeof Bot> = { robo: Bot, usuario: UserPlus, canal: MessageSquare, automacao: Workflow };
const SELOS = ["", "🥉", "🥈", "🥇", "💎", "⭐", "🚀"];

function Sim({ v }: { v?: boolean }) {
  return v ? <Check className="ap-sim" aria-label="sim" /> : <X className="ap-nao" aria-label="não" />;
}

export default function AdminPlanos() {
  const planos = useCarregar<Plano[]>("/admin/planos");
  const adicionais = useCarregar<Adicional[]>("/admin/adicionais");
  const [editar, setEditar] = useState<Partial<Plano> | null>(null);
  const [editarAd, setEditarAd] = useState<Partial<Adicional> | null>(null);
  const { executar } = useAcao();
  const [confirmar, modalConfirmar] = useConfirmar();

  const excluirPlano = async (p: Plano) => {
    if (p.escritorios > 0) {
      await confirmar({ titulo: `Não dá para excluir o ${p.nome}`, texto: `${p.escritorios} escritório(s) usam este plano. Desative em vez de excluir: ele some das novas contratações e quem já tem continua igual.`, confirmar: "Entendi", cancelar: "Fechar" });
      return;
    }
    if (!(await confirmar({ titulo: `Excluir o plano ${p.nome}?`, texto: "Ele some do catálogo. Nenhum escritório usa este plano hoje.", confirmar: "Excluir", perigo: true }))) return;
    await executar(() => api(`/admin/planos/${p.id}`, { metodo: "DELETE" }), "Plano excluído.");
    planos.recarregar();
  };
  const excluirAdicional = async (a: Adicional) => {
    if (!(await confirmar({ titulo: `Excluir "${a.nome}"?`, texto: "Ele some do catálogo de adicionais.", confirmar: "Excluir", perigo: true }))) return;
    await executar(() => api(`/admin/adicionais/${a.id}`, { metodo: "DELETE" }), "Adicional excluído.");
    adicionais.recarregar();
  };
  const semRecursos = planos.dados?.length ? planos.dados[0].usuarios === undefined : false;

  return (
    <div className="stack ap-planos">
      <Cabecalho titulo="Planos" texto="Catálogo comercial: valores mensal e anual, limites e recursos."
        acoes={<button className="btn pri" onClick={() => setEditar({ codigo: "", nome: "", preco_mensal_brl: 0, bonus_mensal_brl: 0, bonus_acumula: false, ativo: true,
          ordem: ((planos.dados?.length ?? 0) + 1) * 10, usuarios: 3, canais_whatsapp: 1, canais_instagram: 1, cria_agentes: false, ia_inclusa: false, sob_proposta: false, selo: "", icone: "raio" })}>
          <Plus />Novo plano</button>} />

      <div className="ap-aviso"><Info size={16} />
        <span>Anual com {Math.round(DESCONTO_ANUAL * 100)}% de desconto, pago 1x. Adicionais são sempre mensais. Alterações valem para novas contratações.</span></div>
      {semRecursos && <div className="ap-aviso ap-aviso--ruim"><Info size={16} /><span>O banco ainda não tem a migração 017: usuários, canais e recursos não aparecem até ela ser aplicada.</span></div>}

      {!planos.dados ? <Carregando erro={planos.erro} /> : planos.dados.length === 0 ? <div className="panel"><Vazio>Nenhum plano. Crie o primeiro.</Vazio></div> : (
        <div className="ap-tabela-caixa">
          <table className="ap-tabela">
            <thead><tr>
              <th>Plano</th><th>Mensal</th><th>Anual (1x)</th><th className="c">Usuários</th><th className="c">WA / IG</th>
              <th className="c">Cria agentes</th><th className="c">IA inclusa</th><th>Bônus de IA</th><th className="c">Escritórios</th><th>Status</th><th className="d">Ações</th>
            </tr></thead>
            <tbody>{planos.dados.map((p) => {
              const ic = ICONES_PLANO[p.icone ?? ""] ?? ICONES_PLANO.raio;
              return (
                <tr key={p.id} className={p.ativo ? "" : "ap-inativo"}>
                  <td><div className="ap-plano">
                    <span className="ap-plano-ico" style={{ background: ic.cor }}><ic.Icone size={17} /></span>
                    <div><b>{p.selo && <span className="ap-selo">{p.selo}</span>}{p.nome}</b><code>{p.codigo}</code></div>
                  </div></td>
                  <td className="ap-valor">{p.sob_proposta ? <span className="ap-proposta">Sob proposta</span> : reais(p.preco_mensal_brl)}</td>
                  <td className="ap-valor">{p.sob_proposta ? "—" : <>{reais(anualDe(p))}<small>{reais(anualDe(p) / 12)}/mês</small></>}</td>
                  <td className="c"><span className="ap-num">{p.usuarios ?? "—"}</span></td>
                  <td className="c ap-mono">{p.canais_whatsapp ?? "—"} / {p.canais_instagram ?? "—"}</td>
                  <td className="c"><Sim v={p.cria_agentes} /></td>
                  <td className="c"><Sim v={p.ia_inclusa} /></td>
                  <td className="ap-valor">{p.bonus_mensal_brl > 0 ? reais(p.bonus_mensal_brl) : "—"}</td>
                  <td className="c ap-mono">{p.escritorios}</td>
                  <td><span className={`ap-status ${p.ativo ? "on" : ""}`}>{p.ativo ? "Ativo" : "Inativo"}</span></td>
                  <td className="d"><div className="ap-acoes">
                    <button type="button" title="Editar" aria-label={`Editar ${p.nome}`} onClick={() => setEditar(p)}><Pencil size={16} /></button>
                    <button type="button" className="perigo" title="Excluir" aria-label={`Excluir ${p.nome}`} onClick={() => excluirPlano(p)}><Trash2 size={16} /></button>
                  </div></td>
                </tr>
              );
            })}</tbody>
          </table>
        </div>
      )}

      <div className="ap-sub">
        <h3><Sparkles size={16} />Adicionais <span>(sempre mensal)</span></h3>
        <button className="btn sm" onClick={() => setEditarAd({ codigo: "", nome: "", preco_mensal_brl: 0, ativo: true, icone: "", ordem: ((adicionais.dados?.length ?? 0) + 1) * 10 })}><Plus />Adicional</button>
      </div>
      {!adicionais.dados ? <Carregando erro={adicionais.erro} /> : adicionais.dados.length === 0 ? <div className="panel"><Vazio>Nenhum adicional.</Vazio></div> : (
        <div className="ap-tabela-caixa">
          <table className="ap-tabela">
            <thead><tr><th>Adicional</th><th>Código</th><th>Mensal</th><th>Status</th><th className="d">Ações</th></tr></thead>
            <tbody>{adicionais.dados.map((a) => {
              const Icone = ICONES_ADICIONAL[a.icone ?? ""];
              return (
                <tr key={a.id} className={a.ativo ? "" : "ap-inativo"}>
                  <td><span className="ap-ad">{Icone && <Icone size={16} />}{a.nome}</span></td>
                  <td><code className="ap-cod">{a.codigo}</code></td>
                  <td className="ap-valor">{reais(a.preco_mensal_brl)}</td>
                  <td><span className={`ap-status ${a.ativo ? "on" : ""}`}>{a.ativo ? "Ativo" : "Inativo"}</span></td>
                  <td className="d"><div className="ap-acoes">
                    <button type="button" title="Editar" aria-label={`Editar ${a.nome}`} onClick={() => setEditarAd(a)}><Pencil size={16} /></button>
                    <button type="button" className="perigo" title="Excluir" aria-label={`Excluir ${a.nome}`} onClick={() => excluirAdicional(a)}><Trash2 size={16} /></button>
                  </div></td>
                </tr>
              );
            })}</tbody>
          </table>
        </div>
      )}

      {editar && <EditarPlano plano={editar} aoFechar={(mudou) => { setEditar(null); if (mudou) planos.recarregar(); }} />}
      {editarAd && <EditarAdicional item={editarAd} aoFechar={(mudou) => { setEditarAd(null); if (mudou) adicionais.recarregar(); }} />}
      {modalConfirmar}
    </div>
  );
}

const numero = (t: string) => Number(t.replace(/\./g, "").replace(",", ".")) || 0;
const inteiro = (t: string) => Math.max(0, Math.floor(Number(t) || 0));

function Campo({ rotulo, children, ajuda }: { rotulo: string; children: ReactNode; ajuda?: ReactNode }) {
  return <label className="field"><span className="lbl">{rotulo}</span>{children}{ajuda && <span className="ajuda">{ajuda}</span>}</label>;
}
function Chave({ rotulo, v, aoMudar, ajuda }: { rotulo: string; v?: boolean; aoMudar: (v: boolean) => void; ajuda?: string }) {
  return (
    <button type="button" role="switch" aria-checked={Boolean(v)} className={`ap-chave ${v ? "on" : ""}`} onClick={() => aoMudar(!v)}>
      <span className="ap-chave-txt"><b>{rotulo}</b>{ajuda && <small>{ajuda}</small>}</span><i />
    </button>
  );
}

function EditarPlano({ plano, aoFechar }: { plano: Partial<Plano>; aoFechar: (mudou: boolean) => void }) {
  const { ocupado, executar } = useAcao();
  const [p, setP] = useState<Partial<Plano>>(plano);
  const [anualManual, setAnualManual] = useState(plano.preco_anual_brl != null);
  const novo = !plano.id;
  const mudar = (m: Partial<Plano>) => setP((v) => ({ ...v, ...m }));
  const anualAuto = anualDe({ preco_mensal_brl: Number(p.preco_mensal_brl ?? 0), preco_anual_brl: null });
  const salvar = () => executar(async () => {
    const corpo: Record<string, unknown> = {
      nome: p.nome, descricao: p.descricao || null, preco_mensal_brl: Number(p.preco_mensal_brl ?? 0), bonus_mensal_brl: Number(p.bonus_mensal_brl ?? 0),
      bonus_acumula: Boolean(p.bonus_acumula), ativo: Boolean(p.ativo), ordem: Number(p.ordem ?? 0), sob_proposta: Boolean(p.sob_proposta),
      usuarios: Number(p.usuarios ?? 0), canais_whatsapp: Number(p.canais_whatsapp ?? 0), canais_instagram: Number(p.canais_instagram ?? 0),
      cria_agentes: Boolean(p.cria_agentes), ia_inclusa: Boolean(p.ia_inclusa), selo: p.selo ?? "", icone: p.icone ?? "",
    };
    if (anualManual) corpo.preco_anual_brl = Number(p.preco_anual_brl ?? anualAuto);
    if (novo) await enviar("/admin/planos", { ...corpo, codigo: p.codigo, selo: p.selo || null, icone: p.icone || null });
    else await enviar(`/admin/planos/${plano.id}`, { ...corpo, limpar_preco_anual: !anualManual }, "PATCH");
    aoFechar(true);
  }, "Plano salvo.");
  return (
    <Modal titulo={novo ? "Novo plano" : `Plano ${plano.nome}`} largura={640} aoFechar={() => aoFechar(false)}
      texto="Mudanças valem para novas contratações. O bônus de IA muda a partir do próximo mês."
      rodape={<><span className="sp" /><button className="btn" onClick={() => aoFechar(false)}>Cancelar</button>
        <button className="btn pri" disabled={ocupado || !p.nome || (novo && !p.codigo)} onClick={salvar}><Save />Salvar</button></>}>
      <div className="form ap-form">
        <div className="ap-form-grade">
          <Campo rotulo="Nome"><input value={p.nome ?? ""} onChange={(e) => mudar({ nome: e.target.value })} placeholder="Ouro" /></Campo>
          <Campo rotulo="Código" ajuda={novo ? "Letras minúsculas, números, _ ou -. Não muda depois." : undefined}>
            <input value={p.codigo ?? ""} disabled={!novo} onChange={(e) => mudar({ codigo: e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, "") })} placeholder="master" /></Campo>
        </div>
        <div className="ap-form-linha">
          <span className="lbl">Selo</span>
          <div className="ap-escolhas">{SELOS.map((s) => (
            <button key={s || "nenhum"} type="button" className={(p.selo ?? "") === s ? "on" : ""} onClick={() => mudar({ selo: s })}>{s || "nenhum"}</button>))}</div>
        </div>
        <div className="ap-form-linha">
          <span className="lbl">Ícone</span>
          <div className="ap-escolhas">{Object.entries(ICONES_PLANO).map(([k, { Icone, cor }]) => (
            <button key={k} type="button" aria-label={k} className={p.icone === k ? "on" : ""} onClick={() => mudar({ icone: k })}>
              <span className="ap-plano-ico pequeno" style={{ background: cor }}><Icone size={14} /></span></button>))}</div>
        </div>

        <Chave rotulo="Sob proposta" ajuda="Sem preço público (ex.: Diamante). A tela mostra “Sob proposta”." v={p.sob_proposta} aoMudar={(v) => mudar({ sob_proposta: v })} />
        {!p.sob_proposta && <div className="ap-form-grade">
          <Campo rotulo="Mensal (R$)"><input inputMode="decimal" value={String(p.preco_mensal_brl ?? 0).replace(".", ",")} onChange={(e) => mudar({ preco_mensal_brl: numero(e.target.value) })} /></Campo>
          <Campo rotulo="Anual, pago 1x (R$)" ajuda={anualManual
            ? <button type="button" className="ap-link" onClick={() => { setAnualManual(false); mudar({ preco_anual_brl: null }); }}>Voltar para o automático ({reais(anualAuto)})</button>
            : <>Automático: 12 meses com {Math.round(DESCONTO_ANUAL * 100)}% de desconto. <button type="button" className="ap-link" onClick={() => { setAnualManual(true); mudar({ preco_anual_brl: anualAuto }); }}>Digitar outro valor</button></>}>
            <input inputMode="decimal" disabled={!anualManual} value={String(anualManual ? p.preco_anual_brl ?? anualAuto : anualAuto).replace(".", ",")}
              onChange={(e) => mudar({ preco_anual_brl: numero(e.target.value) })} /></Campo>
        </div>}

        <div className="ap-form-grade tres">
          <Campo rotulo="Usuários"><input type="number" min={0} value={p.usuarios ?? 0} onChange={(e) => mudar({ usuarios: inteiro(e.target.value) })} /></Campo>
          <Campo rotulo="Números de WhatsApp"><input type="number" min={0} value={p.canais_whatsapp ?? 0} onChange={(e) => mudar({ canais_whatsapp: inteiro(e.target.value) })} /></Campo>
          <Campo rotulo="Contas de Instagram"><input type="number" min={0} value={p.canais_instagram ?? 0} onChange={(e) => mudar({ canais_instagram: inteiro(e.target.value) })} /></Campo>
        </div>
        <div className="ap-form-grade">
          <Chave rotulo="Cria agentes" ajuda="Pode montar agentes próprios." v={p.cria_agentes} aoMudar={(v) => mudar({ cria_agentes: v })} />
          <Chave rotulo="IA inclusa" ajuda="Ativação dos agentes já vem no plano." v={p.ia_inclusa} aoMudar={(v) => mudar({ ia_inclusa: v })} />
        </div>
        <div className="ap-form-grade">
          <Campo rotulo="Bônus mensal de IA (R$)" ajuda="Crédito de consumo da IA renovado todo mês.">
            <input inputMode="decimal" value={String(p.bonus_mensal_brl ?? 0).replace(".", ",")} onChange={(e) => mudar({ bonus_mensal_brl: numero(e.target.value) })} /></Campo>
          <Chave rotulo="Bônus acumula" ajuda="O que sobra passa para o mês seguinte." v={p.bonus_acumula} aoMudar={(v) => mudar({ bonus_acumula: v })} />
        </div>
        <Campo rotulo="Descrição (opcional)"><input value={p.descricao ?? ""} onChange={(e) => mudar({ descricao: e.target.value })} /></Campo>
        <div className="ap-form-grade">
          <Campo rotulo="Ordem na lista"><input type="number" value={p.ordem ?? 0} onChange={(e) => mudar({ ordem: Number(e.target.value) || 0 })} /></Campo>
          <Chave rotulo="Ativo" ajuda="Pode ser contratado." v={p.ativo} aoMudar={(v) => mudar({ ativo: v })} />
        </div>
      </div>
    </Modal>
  );
}

function EditarAdicional({ item, aoFechar }: { item: Partial<Adicional>; aoFechar: (mudou: boolean) => void }) {
  const { ocupado, executar } = useAcao();
  const [a, setA] = useState<Partial<Adicional>>(item);
  const novo = !item.id;
  const salvar = () => executar(async () => {
    const corpo = { nome: a.nome, descricao: a.descricao || null, preco_mensal_brl: Number(a.preco_mensal_brl ?? 0), icone: a.icone || null,
      ativo: Boolean(a.ativo), ordem: Number(a.ordem ?? 0) };
    if (novo) await enviar("/admin/adicionais", { ...corpo, codigo: a.codigo });
    else await enviar(`/admin/adicionais/${item.id}`, corpo, "PATCH");
    aoFechar(true);
  }, "Adicional salvo.");
  return (
    <Modal titulo={novo ? "Novo adicional" : a.nome ?? "Adicional"} aoFechar={() => aoFechar(false)} texto="Adicionais são cobrados todo mês, junto do plano."
      rodape={<><span className="sp" /><button className="btn" onClick={() => aoFechar(false)}>Cancelar</button>
        <button className="btn pri" disabled={ocupado || !a.nome || (novo && !a.codigo)} onClick={salvar}><Save />Salvar</button></>}>
      <div className="form ap-form">
        <div className="ap-form-grade">
          <Campo rotulo="Nome"><input value={a.nome ?? ""} onChange={(e) => setA({ ...a, nome: e.target.value })} /></Campo>
          <Campo rotulo="Código"><input value={a.codigo ?? ""} disabled={!novo} onChange={(e) => setA({ ...a, codigo: e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, "") })} /></Campo>
        </div>
        <div className="ap-form-grade">
          <Campo rotulo="Mensal (R$)"><input inputMode="decimal" value={String(a.preco_mensal_brl ?? 0).replace(".", ",")} onChange={(e) => setA({ ...a, preco_mensal_brl: numero(e.target.value) })} /></Campo>
          <Chave rotulo="Ativo" ajuda="Pode ser contratado." v={a.ativo} aoMudar={(v) => setA({ ...a, ativo: v })} />
        </div>
        <div className="ap-form-linha">
          <span className="lbl">Ícone</span>
          <div className="ap-escolhas">
            <button type="button" className={!a.icone ? "on" : ""} onClick={() => setA({ ...a, icone: "" })}>nenhum</button>
            {Object.entries(ICONES_ADICIONAL).map(([k, Icone]) => (
              <button key={k} type="button" aria-label={k} className={a.icone === k ? "on" : ""} onClick={() => setA({ ...a, icone: k })}><Icone size={16} /></button>))}
          </div>
        </div>
      </div>
    </Modal>
  );
}
