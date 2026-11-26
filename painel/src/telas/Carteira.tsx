import { useState } from "react";
import { X } from "lucide-react";
import { enviar, quando } from "../api";
import { Carregando, Modal, Vazio, useAcao } from "../componentes/ui";

/*
 * Peças da carteira usadas pela tela Créditos & Consumo (telas/Creditos.tsx) e pela Cobrança da IA (admin): tipos,
 * extrato, lista de recargas e o pedido de recarga. O cliente nunca vê US$, cotação ou markup.
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

export const reais = (v: number | null | undefined, casas = 2) =>
  (v ?? 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL", minimumFractionDigits: casas, maximumFractionDigits: casas });
const SITUACAO_RECARGA: Record<string, string> = { pendente: "warn", paga: "ok", cancelada: "", expirada: "", estornada: "bad" };

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

export function PedirRecarga({ aoFechar, aoPedir, valorInicial = 300 }: { aoFechar: () => void; aoPedir: () => void; valorInicial?: number }) {
  const { ocupado, executar } = useAcao();
  const [valor, setValor] = useState(String(valorInicial));
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
