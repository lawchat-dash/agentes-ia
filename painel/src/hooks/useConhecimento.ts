import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, enviar } from "@/api";

/** Um documento da base de conhecimento de um agente (GET /agentes/{id}/documentos). */
export interface ConhecimentoDoc {
  id: string;
  descricao: string | null;
  tipo: string;                 // texto | arquivo
  status: string;               // processando | concluido | erro
  arquivo_nome: string | null;
  arquivo_mime: string | null;
  arquivo_tamanho: number | null;
  tokens: number | null;
  origem: string;               // catalogo | cliente
  travado: boolean;             // catálogo do admin → sem remover
  erro_mensagem: string | null;
  created_at: string;
}

/** Corpo do POST: arquivo em base64 (o servidor extrai o texto) ou texto colado. */
export type NovoConhecimento =
  | { nome: string; conteudo_base64: string; mime: string }
  | { nome: string; tipo: "texto"; texto: string };

/** Linha da API (situacao: processando | pronto | erro) → shape da tela. */
const mapDoc = (d: any): ConhecimentoDoc => ({
  id: String(d.id),
  descricao: d.nome ?? null,
  tipo: d.tipo ?? "arquivo",
  status: d.situacao === "pronto" ? "concluido" : (d.situacao ?? "processando"),
  arquivo_nome: d.tipo === "texto" ? null : (d.nome ?? null),
  arquivo_mime: d.formato ?? null,
  arquivo_tamanho: d.tamanho_bytes ?? null,
  tokens: d.tokens ?? null,
  origem: d.origem ?? "cliente",
  travado: !!d.travado,
  erro_mensagem: d.erro ?? null,
  created_at: d.created_at,
});

/**
 * Base de conhecimento de UM agente: lista + adicionar + remover. O servidor extrai o texto e
 * indexa; fazemos polling a cada 3 s enquanto houver doc "processando".
 */
export function useConhecimento(idAgente: string | null | undefined) {
  const qc = useQueryClient();
  const key = ["conhecimento", idAgente];

  const query = useQuery({
    queryKey: key,
    enabled: !!idAgente,
    refetchInterval: (q) =>
      (q.state.data as ConhecimentoDoc[] | undefined)?.some((d) => d.status === "processando") ? 3000 : false,
    queryFn: async () => {
      const data = await api<any[]>(`/agentes/${idAgente}/documentos`);
      return ((data ?? []) as any[]).map(mapDoc);
    },
  });

  /** Pede ao servidor para processar de novo um documento (volta para "processando"). */
  const reprocessar = useMutation({
    mutationFn: async (id: string) => {
      await enviar(`/agentes/${idAgente}/documentos/${id}/reprocessar`, {});
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: key }),
  });

  const adicionar = useMutation({
    mutationFn: async (doc: NovoConhecimento) => {
      return await enviar(`/agentes/${idAgente}/documentos`, doc);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: key }),
  });

  const remover = useMutation({
    mutationFn: async (id: string) => {
      await api(`/agentes/${idAgente}/documentos/${id}`, { metodo: "DELETE" });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: key }),
  });

  return { ...query, adicionar, remover, reprocessar };
}
