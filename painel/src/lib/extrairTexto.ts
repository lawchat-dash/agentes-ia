// Aqui o texto de PDF/DOCX é extraído NO SERVIDOR: o navegador só manda o arquivo em base64.
// (No agents-lawchat-main a extração era no navegador, com pdf.js/mammoth.)

/** Extensões/MIMEs aceitos no upload de conhecimento. */
export const CONHECIMENTO_ACCEPT = ".pdf,.docx,.txt,.md,.csv,.json";

/** Lê o arquivo como base64 (sem o prefixo "data:...;base64,"). */
export function arquivoParaBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const leitor = new FileReader();
    leitor.onload = () => {
      const r = String(leitor.result ?? "");
      resolve(r.includes(",") ? r.slice(r.indexOf(",") + 1) : r);
    };
    leitor.onerror = () => reject(leitor.error ?? new Error("Não consegui ler o arquivo."));
    leitor.readAsDataURL(file);
  });
}

/** Corpo para POST de documento (o servidor extrai o texto). */
export async function corpoDocumento(file: File): Promise<{ nome: string; tipo: "arquivo"; conteudo_base64: string; mime: string }> {
  return { nome: file.name, tipo: "arquivo", conteudo_base64: await arquivoParaBase64(file), mime: file.type || "application/octet-stream" };
}

/**
 * Extrai o texto de arquivos de texto puro (TXT/MD/CSV/JSON) no navegador.
 * PDF/DOCX não são lidos aqui: mande o arquivo com `corpoDocumento` e o servidor extrai.
 */
export async function extrairTextoArquivo(file: File): Promise<string> {
  const ext = file.name.toLowerCase().split(".").pop() ?? "";
  const mime = (file.type ?? "").toLowerCase();
  if (mime.startsWith("text/") || ["txt", "md", "markdown", "csv", "json"].includes(ext)) {
    return (await file.text()).trim();
  }
  throw new Error(`Formato ${ext || mime} é lido pelo servidor: envie o arquivo (base64), não o texto.`);
}

/** Tamanho legível (B/KB/MB). */
export const formatarTamanho = (b: number): string =>
  b < 1024 ? `${b} B` : b < 1_048_576 ? `${Math.round(b / 1024)} KB` : `${(b / 1_048_576).toFixed(1)} MB`;
