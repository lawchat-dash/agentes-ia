import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, enviar } from "@/api";

/** Doc padrão do catálogo de um produto (o servidor guarda o arquivo e extrai o texto). */
export interface BibliotecaConhecimentoDoc {
  id: string;
  nome: string;
  tipo: string;               // 'arquivo' | 'texto'
  formato: string | null;     // pdf, docx, txt…
  tamanho_bytes: number | null;
  caracteres: number | null;
  created_at: string;
}

/** Corpo do POST: arquivo em base64 (o servidor extrai o texto) ou texto colado. */
export type NovoDocumentoBiblioteca =
  | { nome: string; tipo: "arquivo"; conteudo_base64: string; mime: string }
  | { nome: string; tipo: "texto"; texto: string };

/** Catálogo de conhecimento (docs padrão) de um produto — a equipe LawChat gerencia. */
export function useBibliotecaConhecimento(idProduto: string | null | undefined) {
  const qc = useQueryClient();
  const key = ["biblioteca-conhecimento", idProduto];

  const query = useQuery({
    queryKey: key,
    enabled: !!idProduto,
    queryFn: async () => {
      const data = await api<BibliotecaConhecimentoDoc[]>(`/biblioteca/produtos/${idProduto}/documentos`);
      return (data ?? []) as BibliotecaConhecimentoDoc[];
    },
  });

  const adicionar = useMutation({
    mutationFn: async (doc: NovoDocumentoBiblioteca) => {
      await enviar(`/admin/biblioteca/produtos/${idProduto}/documentos`, doc);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: key }),
  });

  const remover = useMutation({
    mutationFn: async (id: string) => {
      await api(`/admin/biblioteca/produtos/${idProduto}/documentos/${id}`, { metodo: "DELETE" });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: key }),
  });

  return { ...query, adicionar, remover };
}
