import { Link } from "react-router-dom";
import { useCarregar } from "./ui";
import "./saldoTopo.css";

/** Pílula de saldo no topo (só quem gere a conta vê valores): ● Saldo R$ 482,10  [Recarregar].
 *  Usa a mesma rota leve do aviso de saldo (/carteira/estado, guardada 15 s no servidor). */
export function SaldoTopo({ escritorio }: { escritorio: string }) {
  const { dados } = useCarregar<{ bloqueado: boolean; disponivel_brl?: number | string | null }>("/carteira/estado", [escritorio]);
  if (dados?.disponivel_brl == null) return null;
  const valor = Number(dados.disponivel_brl) || 0;
  const tom = dados.bloqueado || valor <= 0 ? "zerado" : valor < 50 ? "baixo" : "ok";
  const texto = valor.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
  return (
    <span className={`lc-saldo-topo lc-saldo-${tom}`} title={tom === "zerado" ? "Sem saldo: a IA está pausada" : "Saldo disponível para a IA"}>
      <i className="lc-saldo-ponto" aria-hidden />
      <span className="lc-saldo-rotulo">Saldo</span>
      <b className="lc-saldo-valor">{texto}</b>
      <Link to="/consumo" className="lc-saldo-botao">Recarregar</Link>
    </span>
  );
}
