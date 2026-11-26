/** Lê um arquivo do navegador e devolve o conteúdo em base64 (sem o prefixo "data:...;base64,"). */
export const arquivoParaBase64 = (file: File | Blob): Promise<string> =>
  new Promise((resolve, reject) => {
    const leitor = new FileReader();
    leitor.onload = () => {
      const r = String(leitor.result ?? "");
      const i = r.indexOf(",");
      resolve(i >= 0 ? r.slice(i + 1) : r);
    };
    leitor.onerror = () => reject(leitor.error ?? new Error("Não foi possível ler o arquivo."));
    leitor.readAsDataURL(file);
  });
