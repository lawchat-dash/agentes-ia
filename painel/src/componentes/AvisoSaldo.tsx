import { Link } from "react-router-dom";
import { useCarregar } from "./ui";

/** Faixa no topo de todas as telas quando a IA do escritório está pausada por falta de saldo (todos os papéis veem). */
export function AvisoSaldo({ escritorio, podeGerir }: { escritorio: string; podeGerir: boolean }) {
  const { dados } = useCarregar<{ bloqueado: boolean; pode_pedir_recarga?: boolean }>("/carteira/estado", [escritorio]);
  if (!dados?.bloqueado) return null;
  return (
    <div role="alert" style={{ background: "var(--bad-bg, #fdecea)", color: "var(--bad, #a61b1b)", padding: "10px 16px", fontSize: 14,
      display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", borderBottom: "1px solid var(--line, #f3c2bd)" }}>
      <b>A IA está pausada: o saldo acabou.</b>
      <span>As mensagens novas ficam com a equipe na LawChat. Ela volta sozinha quando entrar crédito.</span>
      {podeGerir && dados.pode_pedir_recarga && <Link to="/consumo" className="btn pri" style={{ marginLeft: "auto" }}>Pedir recarga</Link>}
    </div>
  );
}
