import { Link } from "react-router-dom";
import { Wallet } from "lucide-react";
import { useCarregar } from "./ui";

interface Estado { bloqueado: boolean; disponivel_brl?: number; bonus_usado_pct?: number | null; modo?: string }

const reais = (v: number) => `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

/** Saldo da IA na barra do topo (como no painel antigo): valor e uma barrinha; clique abre Créditos. */
export function SaldoTopo({ escritorio }: { escritorio: string }) {
  const { dados } = useCarregar<Estado>("/carteira/estado", [escritorio]);
  if (!dados || dados.disponivel_brl == null) return null;
  const valor = dados.disponivel_brl;
  // Barra: quanto do bônus do mês ainda resta; sem bônus, cheia enquanto houver saldo.
  const pct = dados.bloqueado || valor <= 0 ? 0 : dados.bonus_usado_pct != null ? Math.max(8, 100 - dados.bonus_usado_pct) : 100;
  const cor = dados.bloqueado || valor <= 0 ? "#ff9b85" : pct < 25 ? "#fbbf24" : "#3ddc6f";
  return (
    <Link to="/consumo" className="lc-saldo-topo" title="Créditos da IA: ver consumo e pedir recarga">
      <Wallet aria-hidden />
      <span className="lc-saldo-rot">Saldo</span>
      <b className="num" style={{ color: dados.bloqueado || valor <= 0 ? "#ff9b85" : undefined }}>{reais(valor)}</b>
      <span className="lc-saldo-barra" aria-hidden><i style={{ width: `${pct}%`, background: cor }} /></span>
    </Link>
  );
}
