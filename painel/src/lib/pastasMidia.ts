// Pastas da Biblioteca de mídia. A coluna `pasta` (migração 019) guarda o caminho com "/", ex.:
// "Roteiros gravados/Auxílio-Acidente". Sem pasta (null/"") = arquivo solto, na raiz.
// Usado pela tela Ferramentas › Biblioteca de mídia e pelo seletor do editor de prompt.

/** Caminho limpo: sem espaços nas pontas nem "/" repetida ou nas pontas. "" = raiz. */
export function normalizarPasta(pasta?: string | null): string {
  return String(pasta ?? "").split("/").map((p) => p.trim()).filter(Boolean).join("/");
}

/** Nome para mostrar de uma pasta: o último pedaço do caminho. Dentro de "Roteiros gravados" vira
 *  "Roteiro <produto>" (e "Gerais" vira "Roteiros gerais"). */
export function nomeDaPasta(caminho: string): string {
  const partes = normalizarPasta(caminho).split("/").filter(Boolean);
  const ultimo = partes[partes.length - 1] ?? "";
  const pai = partes[partes.length - 2];
  if (pai && pai.toLowerCase() === "roteiros gravados") return ultimo.toLowerCase() === "gerais" ? "Roteiros gerais" : `Roteiro ${ultimo}`;
  return ultimo;
}

/** Pedaços do caminho para a navegação (breadcrumb): cada um com o caminho até ali e o nome. */
export function trilhaDaPasta(caminho: string): { caminho: string; nome: string }[] {
  const partes = normalizarPasta(caminho).split("/").filter(Boolean);
  return partes.map((_, i) => {
    const ate = partes.slice(0, i + 1).join("/");
    return { caminho: ate, nome: nomeDaPasta(ate) };
  });
}

/** Caminho da pasta de cima ("" = raiz). */
export const pastaDeCima = (caminho: string) => normalizarPasta(caminho).split("/").slice(0, -1).join("/");

export interface PastaResumo {
  caminho: string;
  nome: string;
  /** Arquivos dentro dela, contando as subpastas. */
  quantidade: number;
  /** Data (ISO) da gravação mais recente lá dentro. */
  atualizado: string | null;
}

/** Ordem por nome que respeita o número na frente ("02 - Honorários" antes de "10 - ..."). */
export const porNome = (a: string, b: string) => a.localeCompare(b, "pt-BR", { numeric: true, sensitivity: "base" });

/** O que aparece dentro de `atual` ("" = raiz): as subpastas logo abaixo e os arquivos que estão nela.
 *  Na raiz os arquivos mantêm a ordem recebida; dentro de uma pasta vão por nome. */
export function conteudoDaPasta<T>(itens: T[], atual: string, pastaDe: (i: T) => string | null | undefined,
  nomeDe: (i: T) => string, dataDe: (i: T) => string | null | undefined): { pastas: PastaResumo[]; arquivos: T[] } {
  const base = normalizarPasta(atual);
  const prefixo = base ? `${base}/` : "";
  const pastas = new Map<string, PastaResumo>();
  const arquivos: T[] = [];
  for (const item of itens) {
    const p = normalizarPasta(pastaDe(item));
    if (p === base) { arquivos.push(item); continue; }
    if (base && !p.startsWith(prefixo)) continue;
    const resto = p.slice(prefixo.length);
    if (!resto) continue;
    const caminho = prefixo + resto.split("/")[0];
    const resumo = pastas.get(caminho) ?? { caminho, nome: nomeDaPasta(caminho), quantidade: 0, atualizado: null };
    resumo.quantidade += 1;
    const data = dataDe(item);
    if (data && (!resumo.atualizado || String(data) > resumo.atualizado)) resumo.atualizado = String(data);
    pastas.set(caminho, resumo);
  }
  if (base) arquivos.sort((a, b) => porNome(nomeDe(a), nomeDe(b)));
  return { pastas: [...pastas.values()].sort((a, b) => porNome(a.nome, b.nome)), arquivos };
}

/** "12 arquivos · atualizado em 27/11/2026" */
export function descreverPasta(p: PastaResumo): string {
  const qtd = `${p.quantidade} ${p.quantidade === 1 ? "arquivo" : "arquivos"}`;
  const d = p.atualizado ? new Date(p.atualizado) : null;
  return d && !Number.isNaN(d.getTime()) ? `${qtd} · atualizado em ${d.toLocaleDateString("pt-BR")}` : qtd;
}

/** Caminho legível da pasta de um arquivo, para mostrar ao lado dele (ex.: "Roteiros gravados › Roteiro Auxílio-Acidente"). */
export function rotuloDaPasta(pasta?: string | null): string {
  return trilhaDaPasta(normalizarPasta(pasta)).map((t) => t.nome).join(" › ");
}
