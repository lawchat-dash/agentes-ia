/* Tipos da tela Créditos da IA (resposta de GET /carteira/painel). */
export interface Agente {
  id_agente: string | null; agente: string; valor_brl: number; tokens: number; chamadas: number; conversas: number; contratos: number;
  custo_por_lead_brl: number | null; custo_por_contrato_brl: number | null; conversao_pct: number | null; participacao_pct: number;
}
/** Mês do calendário (desde o dia 1º) e o mês anterior: independe do período escolhido na tela. */
export interface MesConsumo {
  creditos_brl: number; tokens: number; contratos: number; custo_por_contrato_brl: number | null;
  anterior: { creditos_brl: number; contratos: number; custo_por_contrato_brl: number | null };
  por_agente: { id_agente: string | null; agente: string; produto: string | null; valor_brl: number; participacao_pct: number }[];
}
export interface PainelConsumo {
  dias: number; granularidade: "hora" | "dia";
  carteira: { disponivel_brl: number; saldo_brl: number; bonus_brl: number; bonus_do_mes_brl: number; bonus_usado_pct: number | null;
    consumo_mes_brl: number; modo: string; bloqueado: boolean; pausado_por_saldo: boolean; plano: string | null; mes: string };
  custo_por_lead: { valor_brl: number | null; fonte: "periodo" | "historico_90d" | "referencia_modelo" | null; estimativa: boolean;
    leads_com_saldo: number | null };
  totais: { creditos_brl: number; chamadas: number; tokens: number; tokens_entrada: number; tokens_saida: number; tokens_cache: number;
    conversas: number; contratos: number; custo_por_conversa_brl: number | null; custo_por_contrato_brl: number | null; conversao_pct: number | null };
  serie: { quando: string; valor_brl: number; tokens: number; conversas: number }[];
  por_funcao: { papel: string; nome: string; valor_brl: number; chamadas: number; tokens: number }[];
  por_agente: Agente[];
  comparativo: { ultimos_7_brl: number; anteriores_7_brl: number; ultimos_30_brl: number };
  media_dia_brl: number | null;
  mes?: MesConsumo;
  creditos: { recargas_brl: number; recargas: number; bonus_brl: number; bonus: number; outros_brl: number;
    por_mes: { mes: string; recargas_brl: number; bonus_brl: number }[] };
}
