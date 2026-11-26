// Upload de conhecimento: o SERVIDOR extrai o texto (PDF/DOCX/TXT) — o navegador só manda o
// arquivo em base64. Ficam aqui os utilitários de tela que, no agents-lawchat-main, moravam em
// lib/extrairTexto.ts (que também extraía no navegador com pdfjs/mammoth — não usado aqui).

/** Extensões/MIMEs aceitos no upload de conhecimento. */
export const CONHECIMENTO_ACCEPT = ".pdf,.docx,.txt,.md,.csv,.json";

/** Tamanho legível (B/KB/MB). */
export const formatarTamanho = (b: number): string =>
  b < 1024 ? `${b} B` : b < 1_048_576 ? `${Math.round(b / 1024)} KB` : `${(b / 1_048_576).toFixed(1)} MB`;
