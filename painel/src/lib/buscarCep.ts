// Tool "Buscar CEP" — porta a cadeia de fallback do n8n (VIACEP → OpenCEP → BRASILAPI)
// para o front (CORS confirmado nas 3). Usado pelo Teste de Prompt p/ EXECUTAR a tool de
// verdade quando o agente aciona `buscarcep`, devolvendo o endereço pro agente continuar.

export interface EnderecoCep {
  cep: string;
  logradouro: string;
  bairro: string;
  cidade: string;
  uf: string;
}

/** Extrai o 1º CEP (8 dígitos, com/sem traço/espaço) de um texto. */
export function extrairCep(texto: string): string | null {
  const m = (texto || "").match(/(\d{5})[-\s]?(\d{3})/);
  return m ? m[1] + m[2] : null;
}

/** Endereço legível: "Logradouro, Bairro, Cidade-UF". */
export const formatarEndereco = (e: EnderecoCep): string =>
  [e.logradouro, e.bairro, e.cidade && e.uf ? `${e.cidade}-${e.uf}` : (e.cidade || e.uf)]
    .filter(Boolean)
    .join(", ");

/**
 * Busca o endereço pelo CEP com a MESMA cadeia de fallback do n8n: VIACEP → OpenCEP →
 * BRASILAPI. Normaliza os shapes (viacep/opencep usam PT; brasilapi usa EN). Retorna null
 * se o CEP for inválido ou nenhuma API achar.
 */
export async function buscarCep(cepRaw: string): Promise<EnderecoCep | null> {
  const cep = (cepRaw || "").replace(/\D/g, "");
  if (cep.length !== 8) return null;

  // 1) VIACEP (PT) — retorna { erro: true } p/ CEP inexistente
  try {
    const r = await fetch(`https://viacep.com.br/ws/${cep}/json`);
    if (r.ok) {
      const d = await r.json();
      if (!d?.erro && (d.logradouro || d.localidade))
        return { cep, logradouro: d.logradouro ?? "", bairro: d.bairro ?? "", cidade: d.localidade ?? "", uf: d.uf ?? "" };
    }
  } catch { /* tenta o próximo */ }

  // 2) OpenCEP (PT)
  try {
    const r = await fetch(`https://opencep.com/v1/${cep}`);
    if (r.ok) {
      const d = await r.json();
      if (d?.logradouro || d?.localidade)
        return { cep, logradouro: d.logradouro ?? "", bairro: d.bairro ?? "", cidade: d.localidade ?? "", uf: d.uf ?? "" };
    }
  } catch { /* tenta o próximo */ }

  // 3) BRASILAPI (EN)
  try {
    const r = await fetch(`https://brasilapi.com.br/api/cep/v1/${cep}`);
    if (r.ok) {
      const d = await r.json();
      if (d?.street || d?.city)
        return { cep, logradouro: d.street ?? "", bairro: d.neighborhood ?? "", cidade: d.city ?? "", uf: d.state ?? "" };
    }
  } catch { /* sem mais fallback */ }

  return null;
}
