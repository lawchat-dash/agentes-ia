import { useState } from "react";
import { Wallet, PlusCircle, X } from "lucide-react";
import { enviar, quando } from "../api";
import { Alerta, Cabecalho, Carregando, Modal, Painel, Vazio, useAcao, useCarregar } from "../componentes/ui";
import { useSessao } from "../sessao";

/*
 * Consumo e saldo (cliente). Só o necessário: quanto tem, quanto do bônus do mês já foi, onde a IA gastou (em R$) e o
 * extrato. Sem US$, cotação ou markup. Tokens e número de chamadas só no "Detalhe".
 */

export interface Carteira {
  modo: "pre_pago" | "so_registrar"; saldo_brl: number; bonus_brl: number; bonus_do_mes_brl: number; bonus_usado_pct: number | null;
  disponivel_brl: number; pendente_brl: number; consumo_mes_brl: number; pausado_por_saldo: boolean; bloqueado: boolean;
  pausado_em: string | null; plano: string | null; plano_preco_brl: number | null; plano_bonus_brl: number | null; bonus_acumula: boolean | null; mes: string;
  recargas_pendentes?: Recarga[];
}
export interface Recarga { id: string; valor_brl: number; situacao: string; metodo: string | null; url_pagamento: string | null; pix_copia_cola: string | null;
  vencimento: string | null; paga_em?: string | null; criado_em: string; observacao?: string | null; pedido_por?: string | null; gateway?: string }
export interface Movimento { id: string; tipo: string; nome_tipo: string; valor_brl: number; parte_saldo: number; parte_bonus: number; saldo_depois: number;
  bonus_depois: number; motivo: string | null; detalhe: Record<string, any>; criado_em: string; usuario: string | null }
interface Consumo { dias: number; total_brl: number; por_dia: { dia: string; valor_brl: number }[]; por_agente: { agente: string; valor_brl: number }[];
  por_etapa: { etapa: string; valor_brl: number }[]; por_funcao: { papel: string; nome: string; valor_brl: number; chamadas?: number; tokens?: number }[] }

export const reais = (v: number | null | undefined, casas = 2) =>
  (v ?? 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL", minimumFractionDigits: casas, maximumFractionDigits: casas });
const SITUACAO_RECARGA: Record<string, string> = { pendente: "warn", paga: "ok", cancelada: "", expirada: "", estornada: "bad" };

export function TelaCarteira() {
  const { escritorio } = useSessao();
  const carteira = useCarregar<Carteira>("/carteira", [escritorio]);
  const [dias, setDias] = useState(30);
  const [detalhe, setDetalhe] = useState(false);
  const consumo = useCarregar<Consumo>(`/carteira/consumo?dias=${dias}${detalhe ? "&detalhe=1" : ""}`, [escritorio, dias, detalhe]);
  const extrato = useCarregar<Movimento[]>("/carteira/extrato?limite=100", [escritorio]);
  const recargas = useCarregar<Recarga[]>("/carteira/recargas", [escritorio]);
  const [pedir, setPedir] = useState(false);
  const recarregar = () => { carteira.recarregar(); extrato.recarregar(); recargas.recarregar(); };

  if (!carteira.dados) return <Carregando erro={carteira.erro} />;
  const c = carteira.dados;
  return (
    <>
      <Cabecalho eyebrow="Acompanhar" titulo="Consumo e saldo"
        texto="Cada resposta da IA consome do bônus do mês e, depois, do saldo. Quando o saldo acaba, a IA pausa e volta sozinha assim que o crédito entrar."
        acoes={<button className="btn pri" onClick={() => setPedir(true)}><PlusCircle />Pedir recarga</button>} />
      {c.bloqueado && <Alerta tipo="bad" titulo="A IA está pausada: o saldo acabou">As mensagens novas ficam com a equipe na LawChat. Peça uma recarga: assim que ela for confirmada, a IA volta a responder (sem responder de uma vez o que chegou durante a pausa).</Alerta>}
      {c.modo === "so_registrar" && <Alerta tipo="info">Este escritório ainda não está no pré-pago: o consumo é registrado, mas a IA não pausa por saldo.</Alerta>}
      <div className="grid2" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", marginBottom: 16 }}>
        <Indicador rotulo="Disponível agora" valor={reais(c.disponivel_brl)} destaque={c.bloqueado ? "bad" : undefined} nota="saldo + bônus − consumo em processamento" />
        <Indicador rotulo="Saldo" valor={reais(c.saldo_brl)} nota="recargas e créditos" />
        <Indicador rotulo={`Bônus do mês (${c.mes.slice(5)}/${c.mes.slice(0, 4)})`} valor={reais(c.bonus_brl)}
          nota={c.bonus_do_mes_brl > 0 ? `${c.bonus_usado_pct ?? 0}% usado de ${reais(c.bonus_do_mes_brl)}` : "sem bônus neste mês"} />
        <Indicador rotulo="Consumo do mês" valor={reais(c.consumo_mes_brl)} nota={c.plano ? `Plano ${c.plano}` : "sem plano"} />
      </div>
      {c.bonus_do_mes_brl > 0 && <BarraBonus pct={c.bonus_usado_pct ?? 0} />}

      {(recargas.dados ?? []).some((r) => r.situacao === "pendente") && (
        <Painel titulo="Recargas aguardando pagamento">
          <ListaRecargas recargas={(recargas.dados ?? []).filter((r) => r.situacao === "pendente")} aoMudar={recarregar} cancelavel />
        </Painel>
      )}

      <Painel titulo="Onde a IA gastou" acoes={<>
        <div className="seg" role="radiogroup" aria-label="Período">
          {[7, 30, 90].map((d) => <button key={d} role="radio" aria-checked={dias === d} className={dias === d ? "on" : ""} onClick={() => setDias(d)}>{d} dias</button>)}
        </div>
        <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13 }}><input type="checkbox" checked={detalhe} onChange={(e) => setDetalhe(e.target.checked)} />Detalhe</label>
      </>}>
        {!consumo.dados ? <Carregando erro={consumo.erro} /> : consumo.dados.total_brl === 0 ? <Vazio icone={<Wallet />}>Sem consumo no período.</Vazio> : (
          <div className="stack">
            <div><span className="lbl">Por dia · total {reais(consumo.dados.total_brl)}</span><BarrasPorDia dados={consumo.dados.por_dia} /></div>
            <div className="grid2">
              <Ranking titulo="Por agente" itens={consumo.dados.por_agente.map((a) => [a.agente, a.valor_brl])} />
              <Ranking titulo="Por etapa" itens={consumo.dados.por_etapa.map((e) => [e.etapa, e.valor_brl])} />
            </div>
            <div className="lst"><table>
              <thead><tr><th>Função</th><th className="num">Valor</th>{detalhe && <><th className="num">Chamadas</th><th className="num">Tokens</th></>}</tr></thead>
              <tbody>{consumo.dados.por_funcao.map((f) => (
                <tr key={f.papel}><td>{f.nome}</td><td className="num">{reais(f.valor_brl)}</td>
                  {detalhe && <><td className="num">{f.chamadas ?? 0}</td><td className="num">{(f.tokens ?? 0).toLocaleString("pt-BR")}</td></>}</tr>
              ))}</tbody>
            </table></div>
          </div>
        )}
      </Painel>

      <Painel titulo="Extrato">
        <Extrato movimentos={extrato.dados} erro={extrato.erro} />
      </Painel>

      <Painel titulo="Recargas">
        {!recargas.dados ? <Carregando erro={recargas.erro} /> : recargas.dados.length === 0 ? <Vazio>Nenhum pedido de recarga.</Vazio>
          : <ListaRecargas recargas={recargas.dados} aoMudar={recarregar} />}
      </Painel>
      {pedir && <PedirRecarga aoFechar={() => setPedir(false)} aoPedir={recarregar} />}
    </>
  );
}

function Indicador({ rotulo, valor, nota, destaque }: { rotulo: string; valor: string; nota?: string; destaque?: "bad" }) {
  return (
    <div className="panel" style={{ padding: 16 }}>
      <span className="lbl">{rotulo}</span>
      <div style={{ fontSize: 26, fontWeight: 600, color: destaque === "bad" ? "var(--bad, #c0392b)" : undefined }}>{valor}</div>
      {nota && <span className="ajuda">{nota}</span>}
    </div>
  );
}

function BarraBonus({ pct }: { pct: number }) {
  const cor = pct >= 100 ? "var(--bad, #c0392b)" : pct >= 80 ? "var(--warn, #d68910)" : "var(--acento, #1e8e3e)";
  return (
    <div style={{ marginBottom: 16 }} aria-label={`Bônus do mês ${pct}% usado`}>
      <div style={{ height: 8, borderRadius: 4, background: "var(--surface-2, #eee)", overflow: "hidden" }}>
        <div style={{ width: `${Math.min(100, Math.max(0, pct))}%`, height: "100%", background: cor }} />
      </div>
    </div>
  );
}

function BarrasPorDia({ dados }: { dados: { dia: string; valor_brl: number }[] }) {
  const maior = Math.max(...dados.map((d) => d.valor_brl), 0.0001);
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 120, marginTop: 8 }}>
      {dados.map((d) => (
        <div key={d.dia} title={`${d.dia.split("-").reverse().join("/")}: ${reais(d.valor_brl)}`}
          style={{ flex: 1, minWidth: 4, height: `${Math.max(2, (d.valor_brl / maior) * 100)}%`, background: "var(--acento, #1e8e3e)", borderRadius: "3px 3px 0 0", opacity: 0.85 }} />
      ))}
    </div>
  );
}

function Ranking({ titulo, itens }: { titulo: string; itens: [string, number][] }) {
  const total = itens.reduce((s, [, v]) => s + v, 0) || 1;
  return (
    <div>
      <span className="lbl">{titulo}</span>
      {itens.slice(0, 8).map(([nome, valor]) => (
        <div key={nome} style={{ display: "flex", justifyContent: "space-between", gap: 8, padding: "4px 0", borderBottom: "1px solid var(--line, #eee)" }}>
          <span>{nome}</span><span className="num">{reais(valor)} <span className="ajuda">({Math.round((valor / total) * 100)}%)</span></span>
        </div>
      ))}
    </div>
  );
}

export function Extrato({ movimentos, erro, admin }: { movimentos: Movimento[] | null; erro?: string | null; admin?: boolean }) {
  if (!movimentos) return <Carregando erro={erro} />;
  if (movimentos.length === 0) return <Vazio>Nenhum movimento ainda.</Vazio>;
  return (
    <div className="lst"><table>
      <thead><tr><th>Quando</th><th>Movimento</th><th className="num">Valor</th><th className="num">Saldo depois</th><th className="num">Bônus depois</th><th>Detalhe</th></tr></thead>
      <tbody>{movimentos.map((m) => (
        <tr key={m.id}>
          <td className="s num">{quando(m.criado_em)}</td>
          <td><span className={`chip ${m.valor_brl > 0 ? "ok" : ""}`}>{m.nome_tipo}</span></td>
          <td className="num" style={{ color: m.valor_brl < 0 ? "var(--bad, #c0392b)" : undefined }}>{reais(m.valor_brl, Math.abs(m.valor_brl) < 0.01 ? 4 : 2)}</td>
          <td className="num">{reais(m.saldo_depois)}</td>
          <td className="num">{reais(m.bonus_depois)}</td>
          <td className="s">{m.tipo === "consumo" ? `${m.detalhe?.chamadas ?? "?"} chamadas da IA${admin && m.detalhe?.custo_usd != null ? ` · custo US$ ${Number(m.detalhe.custo_usd).toFixed(4)}` : ""}` : m.motivo}
            {m.usuario && <span className="ajuda"> · {m.usuario}</span>}</td>
        </tr>
      ))}</tbody>
    </table></div>
  );
}

export function ListaRecargas({ recargas, aoMudar, cancelavel }: { recargas: Recarga[]; aoMudar: () => void; cancelavel?: boolean }) {
  const { ocupado, executar } = useAcao();
  return (
    <div className="lst"><table>
      <thead><tr><th>Pedido em</th><th className="num">Valor</th><th>Situação</th><th>Pagamento</th><th /></tr></thead>
      <tbody>{recargas.map((r) => (
        <tr key={r.id}>
          <td className="s num">{quando(r.criado_em)}</td>
          <td className="num">{reais(r.valor_brl)}</td>
          <td><span className={`chip ${SITUACAO_RECARGA[r.situacao] ?? ""}`}>{r.situacao}</span></td>
          <td className="s">{r.url_pagamento ? <a href={r.url_pagamento} target="_blank" rel="noreferrer">abrir cobrança</a>
            : r.pix_copia_cola ? <code style={{ fontSize: 11 }}>{r.pix_copia_cola.slice(0, 24)}…</code>
            : r.situacao === "pendente" ? "a equipe LawChat envia os dados de pagamento" : r.paga_em ? `paga em ${quando(r.paga_em)}` : "—"}</td>
          <td>{cancelavel && r.situacao === "pendente" && (
            <button className="btn" disabled={ocupado} onClick={() => executar(async () => { await enviar(`/carteira/recargas/${r.id}/cancelar`, {}); aoMudar(); }, "Pedido cancelado.")}><X />Cancelar</button>
          )}</td>
        </tr>
      ))}</tbody>
    </table></div>
  );
}

const VALORES_SUGERIDOS = [100, 300, 500, 1000];

export function PedirRecarga({ aoFechar, aoPedir }: { aoFechar: () => void; aoPedir: () => void }) {
  const { ocupado, executar } = useAcao();
  const [valor, setValor] = useState("300");
  const [obs, setObs] = useState("");
  const numero = Number(valor.replace(",", "."));
  return (
    <Modal titulo="Pedir recarga" texto="A equipe LawChat recebe o pedido e envia os dados de pagamento. O crédito entra no saldo assim que o pagamento for confirmado." aoFechar={aoFechar}
      rodape={<><span className="sp" /><button className="btn" onClick={aoFechar}>Fechar</button>
        <button className="btn pri" disabled={ocupado || !(numero > 0)} onClick={() => executar(async () => {
          await enviar("/carteira/recargas", { valor_brl: numero, observacao: obs.trim() || null }); aoPedir(); aoFechar();
        }, "Pedido enviado para a LawChat.")}>Pedir recarga</button></>}>
      <div className="form">
        <div className="seg" role="radiogroup" aria-label="Valores sugeridos">
          {VALORES_SUGERIDOS.map((v) => <button key={v} role="radio" aria-checked={Number(valor) === v} className={Number(valor) === v ? "on" : ""} onClick={() => setValor(String(v))}>{reais(v, 0)}</button>)}
        </div>
        <label className="field"><span className="lbl">Valor (R$)</span><input inputMode="decimal" value={valor} onChange={(e) => setValor(e.target.value)} /></label>
        <label className="field"><span className="lbl">Observação (opcional)</span><input value={obs} maxLength={500} onChange={(e) => setObs(e.target.value)} placeholder="Ex.: prefiro boleto" /></label>
      </div>
    </Modal>
  );
}
