import { Link } from "react-router-dom";
import { Wallet, Info, AlertTriangle, Calendar, TrendingUp, PieChart, Check, ChevronRight, SlidersHorizontal } from "lucide-react";
import walletImg from "@/assets/wallet-finance.png";

export interface ConsumoMes {
  gasto_usd: number;
  limite_usd: number | null;
  ao_estourar: string;
  percentual: number | null;
  bloqueado: boolean;
  media_dia_usd: number;
  previsao_dias: number | null;
  mes: string;
}

interface Props {
  consumo: ConsumoMes;
  /** Equipe LawChat: mostra o botão para ajustar o limite do escritório. */
  ajustarLimite?: string | null;
  className?: string;
}

export const formatUSD = (v: number | null | undefined) =>
  `US$ ${(Number(v) || 0).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];

/** Consumo da IA no mês — mesmo desenho do "Saldo disponível" (carteira 3D + indicadores + barra), em dólar e com o limite mensal. */
export function ConsumoCenter({ consumo, ajustarLimite, className = "" }: Props) {
  const limite = consumo.limite_usd;
  const temLimite = limite != null && limite > 0;
  const pctReal = consumo.percentual ?? 0;
  const pct = temLimite ? Math.min(100, pctReal) : 0;
  const barColor = pct >= 90 ? "#ef4444" : pct >= 70 ? "#f59e0b" : "#00bc33";
  const planoTxt = consumo.bloqueado ? "IA pausada: limite do mês atingido"
    : pctReal >= 100 ? "Limite passado (só aviso, a IA segue)"
    : pct >= 90 ? "Perto do limite do mês" : pct >= 70 ? "Consumo elevado este mês" : "Dentro do limite do mês";
  const planoColor = pct >= 90 ? "#dc2626" : pct >= 70 ? "#b7791f" : "#16a34a";
  const nivel: "ok" | "low" | "critical" = !temLimite ? "ok" : pctReal >= 100 || consumo.bloqueado ? "critical" : pctReal >= 80 ? "low" : "ok";
  const [ano, mes] = consumo.mes.split("-").map(Number);
  const nomeMes = mes ? `${MESES[mes - 1]} de ${ano}` : "este mês";

  return (
    <div className={`lc-card relative overflow-hidden p-5 flex flex-col ${className}`}>

      {/* Header */}
      <div className="relative flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <div className="size-10 rounded-xl grid place-items-center shrink-0" style={{ background: "#e8f9ee", color: "#00bc33" }}>
            <Wallet className="size-5" />
          </div>
          <div className="min-w-0">
            <h2 className="text-[16px] font-bold tracking-tight text-[#101828]">Consumo da IA no mês</h2>
            <p className="text-[12px] text-[#667085] mt-0.5 inline-flex items-center gap-1" title="Soma do custo das chamadas ao modelo de IA, em dólar, desde o dia 1º (horário de Brasília).">
              Custo das respostas da IA em {nomeMes} <Info className="size-3 text-[#98A2B3]" />
            </p>
          </div>
        </div>
      </div>

      {/* Gasto + carteira */}
      <div className="relative mt-3 flex items-center justify-between gap-3">
        <div className="text-[30px] lg:text-[34px] font-extrabold tracking-[-0.04em] tabular-nums leading-none text-[#0b1324]">{formatUSD(consumo.gasto_usd)}</div>
        <img src={walletImg} alt="" width={150} height={130} className="lc-float hidden sm:block w-[120px] lg:w-[140px] shrink-0 select-none pointer-events-none mix-blend-multiply -my-2 -mr-1" loading="eager" />
      </div>
      {nivel !== "ok" && (
        <div className={`mt-2 self-start inline-flex items-center gap-1 px-2 py-0.5 rounded-md border whitespace-nowrap ${nivel === "critical" ? "bg-[#fef2f2] border-[#fecaca]" : "bg-[#fff8e6] border-[rgba(245,158,11,.3)]"}`}>
          <AlertTriangle className={`size-3 shrink-0 ${nivel === "critical" ? "text-[#ef4444]" : "text-[#d97706]"}`} />
          <span className={`text-[11px] font-medium ${nivel === "critical" ? "text-[#dc2626]" : "text-[#b7791f]"}`}>
            <b>{nivel === "critical" ? "Limite atingido" : "Perto do limite"}</b> · {pctReal.toFixed(0)}% de {formatUSD(limite)}
          </span>
        </div>
      )}

      {/* Indicadores */}
      <div className="relative mt-3 grid grid-cols-3 rounded-xl border border-[#eef1f5] bg-[#fafbfc] divide-x divide-[#eef1f5] overflow-hidden">
        <Indicador icon={Calendar} bg="#e8f9ee" color="#00bc33" value={consumo.previsao_dias != null ? `${consumo.previsao_dias} dias` : "—"} label="Até o limite" />
        <Indicador icon={TrendingUp} bg="#eaf1ff" color="#2563eb" value={formatUSD(consumo.media_dia_usd)} label="Média/dia" />
        <Indicador icon={PieChart} bg="#fff4df" color="#d97706" value={temLimite ? formatUSD(Math.max(0, (limite as number) - consumo.gasto_usd)) : "—"} label="Restante" />
      </div>

      {/* Barra de utilização */}
      <div className="relative mt-3">
        <div className="flex items-center justify-between text-[13px]">
          <span className="font-semibold text-[#344054]">Uso este mês</span>
          <span className="tabular-nums">
            <strong style={{ color: barColor }}>{formatUSD(consumo.gasto_usd)}</strong>
            {temLimite && <span className="text-[#98A2B3]"> / {formatUSD(limite)}</span>}
          </span>
        </div>
        {temLimite ? (
          <div className="mt-2 h-2.5 rounded-full bg-[#eef1f5] overflow-hidden">
            <div className="h-full rounded-full transition-all duration-700" style={{ width: `${Math.max(3, pct)}%`, background: `linear-gradient(90deg, ${barColor}, ${barColor}cc)` }} />
          </div>
        ) : (
          <div className="mt-2 text-[11px] text-[#98A2B3]">Sem limite mensal definido para este escritório.</div>
        )}
        <div className="mt-3 w-full inline-flex items-center justify-between gap-2 px-3.5 h-11 rounded-xl border border-[#eef1f5] bg-white">
          <span className="inline-flex items-center gap-2 text-[13px] font-medium" style={{ color: temLimite ? planoColor : "#667085" }}>
            <Check className="size-4" /> {temLimite ? planoTxt : "Acompanhe o consumo da IA"}
          </span>
          <span className="text-[11px] text-[#98A2B3] whitespace-nowrap">
            {temLimite ? (consumo.ao_estourar === "pausar" ? "pausa no limite" : "só avisa") : ""}
          </span>
        </div>
      </div>

      {/* Botão principal */}
      {ajustarLimite ? (
        <Link to={ajustarLimite} className="lc-pay-btn relative mt-3 w-full h-11 rounded-xl text-white font-bold text-[14px] inline-flex items-center justify-center gap-2">
          <SlidersHorizontal className="size-4" /> Ajustar limite do escritório <ChevronRight className="size-4" />
        </Link>
      ) : (
        <p className="mt-3 text-center text-[11px] text-[#98A2B3]">Para mudar o limite mensal, fale com a equipe LawChat.</p>
      )}
    </div>
  );
}

/** Carteira do escritório em R$ (o que o cliente vê). Mesmos campos de GET /api/carteira. */
export interface CarteiraResumo {
  modo: "pre_pago" | "so_registrar"; disponivel_brl: number; saldo_brl: number; bonus_brl: number;
  bonus_do_mes_brl: number; bonus_usado_pct: number | null; consumo_mes_brl: number; bloqueado: boolean; plano: string | null; mes: string;
}

export const formatBRL = (v: number | null | undefined) =>
  `R$ ${(Number(v) || 0).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

/** Saldo da IA no Início — em reais, sem US$, cotação ou markup. */
export function SaldoCenter({ carteira, admin, className = "" }: { carteira: CarteiraResumo; admin?: boolean; className?: string }) {
  const c = carteira;
  const temBonus = c.bonus_do_mes_brl > 0;
  const pct = temBonus ? Math.min(100, c.bonus_usado_pct ?? 0) : 0;
  const barColor = pct >= 90 ? "#ef4444" : pct >= 70 ? "#f59e0b" : "#00bc33";
  const [ano, mes] = c.mes.split("-").map(Number);
  const nomeMes = mes ? `${MESES[mes - 1]} de ${ano}` : "este mês";
  const situacao = c.bloqueado ? { txt: "IA pausada: o saldo acabou", cor: "#dc2626" }
    : c.modo === "so_registrar" ? { txt: "Consumo só registrado (sem pausa por saldo)", cor: "#667085" }
    : c.disponivel_brl <= 0 ? { txt: "Saldo zerado", cor: "#dc2626" }
    : { txt: "IA respondendo normalmente", cor: "#16a34a" };

  return (
    <div className={`lc-card relative overflow-hidden p-5 flex flex-col ${className}`}>
      <div className="relative flex items-start gap-3">
        <div className="size-10 rounded-xl grid place-items-center shrink-0" style={{ background: "#e8f9ee", color: "#00bc33" }}>
          <Wallet className="size-5" />
        </div>
        <div className="min-w-0">
          <h2 className="text-[16px] font-bold tracking-tight text-[#101828]">Saldo da IA</h2>
          <p className="text-[12px] text-[#667085] mt-0.5 inline-flex items-center gap-1" title="Saldo + bônus do mês − consumo ainda em processamento.">
            Disponível para as respostas da IA <Info className="size-3 text-[#98A2B3]" />
          </p>
        </div>
      </div>

      <div className="relative mt-3 flex items-center justify-between gap-3">
        <div className={`text-[30px] lg:text-[34px] font-extrabold tracking-[-0.04em] tabular-nums leading-none ${c.bloqueado ? "text-[#dc2626]" : "text-[#0b1324]"}`}>{formatBRL(c.disponivel_brl)}</div>
        <img src={walletImg} alt="" width={150} height={130} className="lc-float hidden sm:block w-[120px] lg:w-[140px] shrink-0 select-none pointer-events-none mix-blend-multiply -my-2 -mr-1" loading="eager" />
      </div>

      <div className="relative mt-3 grid grid-cols-3 rounded-xl border border-[#eef1f5] bg-[#fafbfc] divide-x divide-[#eef1f5] overflow-hidden">
        <Indicador icon={Calendar} bg="#e8f9ee" color="#00bc33" value={formatBRL(c.saldo_brl)} label="Saldo" />
        <Indicador icon={PieChart} bg="#fff4df" color="#d97706" value={formatBRL(c.bonus_brl)} label="Bônus do mês" />
        <Indicador icon={TrendingUp} bg="#eaf1ff" color="#2563eb" value={formatBRL(c.consumo_mes_brl)} label={`Gasto em ${nomeMes.split(" ")[0]}`} />
      </div>

      <div className="relative mt-3">
        {temBonus ? (
          <>
            <div className="flex items-center justify-between text-[13px]">
              <span className="font-semibold text-[#344054]">Bônus usado</span>
              <span className="tabular-nums"><strong style={{ color: barColor }}>{pct.toFixed(0)}%</strong><span className="text-[#98A2B3]"> de {formatBRL(c.bonus_do_mes_brl)}</span></span>
            </div>
            <div className="mt-2 h-2.5 rounded-full bg-[#eef1f5] overflow-hidden">
              <div className="h-full rounded-full transition-all duration-700" style={{ width: `${Math.max(3, pct)}%`, background: `linear-gradient(90deg, ${barColor}, ${barColor}cc)` }} />
            </div>
          </>
        ) : (
          <div className="text-[11px] text-[#98A2B3]">{c.plano ? `Plano ${c.plano} · sem bônus neste mês` : "Sem bônus neste mês."}</div>
        )}
        <div className="mt-3 w-full inline-flex items-center gap-2 px-3.5 h-11 rounded-xl border border-[#eef1f5] bg-white">
          {c.bloqueado ? <AlertTriangle className="size-4" style={{ color: situacao.cor }} /> : <Check className="size-4" style={{ color: situacao.cor }} />}
          <span className="text-[13px] font-medium" style={{ color: situacao.cor }}>{situacao.txt}</span>
        </div>
      </div>

      <Link to={admin ? "/admin/cobranca" : "/consumo"} className="lc-pay-btn relative mt-3 w-full h-11 rounded-xl text-white font-bold text-[14px] inline-flex items-center justify-center gap-2">
        {admin ? <><SlidersHorizontal className="size-4" /> Cobrança da IA</> : <>Ver consumo e pedir recarga</>} <ChevronRight className="size-4" />
      </Link>
    </div>
  );
}

const Indicador = ({ icon: Icon, bg, color, label, value }: { icon: any; bg: string; color: string; label: string; value: string }) => (
  // Ícone em cima e texto embaixo: na coluna do meio do Início (estreita) valor e rótulo cabem inteiros.
  <div className="flex flex-col items-start gap-1.5 p-2.5 min-w-0">
    <div className="size-7 rounded-lg grid place-items-center shrink-0" style={{ background: bg, color }}><Icon className="size-3.5" /></div>
    <div className="min-w-0 w-full leading-tight">
      <div className="text-[13px] font-bold tabular-nums text-[#101828] break-words" title={value}>{value}</div>
      <div className="text-[10.5px] text-[#667085] mt-0.5">{label}</div>
    </div>
  </div>
);
