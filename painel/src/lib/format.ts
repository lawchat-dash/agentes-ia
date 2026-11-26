export const formatBRL = (v: number | null | undefined) =>
  (v ?? 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

export const formatBRLCompact = (v: number | null | undefined) => {
  const n = v ?? 0;
  if (Math.abs(n) >= 1000) return `R$ ${(n / 1000).toFixed(1).replace(".", ",")}k`;
  return formatBRL(n);
};
