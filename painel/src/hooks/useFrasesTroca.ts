import { createContext, createElement, useContext, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, enviar } from "@/api";
import { ETAPAS_TROCA, FraseTroca, getFrasesTroca, setFrasesTroca, setProdutoFrases } from "@/data/frasesTroca";

/** Chave base (invalida as frases de todos os produtos). */
export const frasesTrocaKeyBase = ["frases-troca"] as const;
export const frasesTrocaKey = (idProduto?: string | null) => ["frases-troca", idProduto ?? null] as const;

// ---------------------------------------------------------------------------
// PRODUTO da tela aberta. As frases são POR PRODUTO do catálogo: a página (editor do admin,
// ativação, edição do cliente) informa o produto e os componentes de dentro (editor de prompt,
// cards, "Marcar frase", cadastro) usam só as frases dele.
// ---------------------------------------------------------------------------
const FrasesProdutoContext = createContext<string | null>(null);

export const FrasesProdutoProvider = ({ idProduto, children }: { idProduto: string | null | undefined; children: ReactNode }) => {
  // Também fixa o produto atual do registro (usado pelas funções puras de expandir/recolher).
  setProdutoFrases(idProduto ?? null);
  return createElement(FrasesProdutoContext.Provider, { value: idProduto ?? null }, children);
};

/** Produto do catálogo cujas frases valem aqui (null = fora de um produto). */
export const useIdProdutoFrases = () => useContext(FrasesProdutoContext);

const carregando = new Map<string, Promise<FraseTroca[]>>();

/**
 * Carrega as frases do PRODUTO e alimenta o registro (funções puras de expandir/recolher).
 * Os fluxos que falam com o bot aguardam isto antes de montar o payload — sem o registro,
 * o token "@Transferência" iria cru para o bot.
 */
export async function carregarFrasesTroca(idProduto: string | null | undefined, forcar = false): Promise<FraseTroca[]> {
  if (!idProduto) return [];
  if (!forcar && carregando.has(idProduto)) return carregando.get(idProduto)!;
  const p = (async () => {
    const data = await api<any[]>(`/biblioteca/frases-troca?id_produto=${encodeURIComponent(idProduto)}`);
    // A API devolve as globais + as do produto: valem só as do produto (como no sistema de referência).
    const lista = ((data ?? []) as FraseTroca[])
      .filter((f) => f.id_produto_biblioteca === idProduto)
      .sort((a, b) => (a.ordem ?? 0) - (b.ordem ?? 0) || String(a.nome).localeCompare(String(b.nome)));
    setFrasesTroca(idProduto, lista);
    return getFrasesTroca(idProduto);
  })();
  carregando.set(idProduto, p);
  p.catch(() => { if (carregando.get(idProduto) === p) carregando.delete(idProduto); });
  return p;
}

/** Frases do produto (padrão: o produto do contexto da tela). */
export const useFrasesTroca = (idProduto?: string | null) => {
  const doContexto = useIdProdutoFrases();
  const id = idProduto === undefined ? doContexto : idProduto;
  return useQuery({
    queryKey: frasesTrocaKey(id),
    queryFn: () => carregarFrasesTroca(id, true),
    enabled: !!id,
    staleTime: 60_000,
  });
};

/** Nome do token da etapa (igual a sistemaia_nome_frase_troca() do sistema de referência). */
const nomeDaEtapa = (etapa: string) => ETAPAS_TROCA.find((e) => e.etapa === etapa)?.nome ?? etapa;

/**
 * Cria (id null) ou edita a frase DE UM PRODUTO. Editar o texto propaga só para os prompts
 * dos clientes que ativaram ESTE produto (e a mensagem_troca da etapa) — nunca outros produtos.
 */
export const useSalvarFraseTroca = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: { id: string | null; id_produto_biblioteca: string; etapa_destino: string; frase: string; descricao?: string | null }) => {
      return (await enviar("/admin/biblioteca/frases-troca", {
        ...(input.id ? { id: input.id } : {}),
        id_produto_biblioteca: input.id_produto_biblioteca,
        etapa_destino: input.etapa_destino,
        nome: nomeDaEtapa(input.etapa_destino),
        frase: input.frase.trim(),
        descricao: input.descricao ?? null,
      }, "PUT")) as any;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: frasesTrocaKeyBase }),
  });
};

/**
 * Exclui a frase DE UM PRODUTO. Nunca altera prompts de clientes nem outros produtos:
 * no catálogo deste produto o chip vira o texto da frase; os clientes seguem como estão.
 */
export const useExcluirFraseTroca = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: { id: string; id_produto_biblioteca: string; etapa_destino: string }) => {
      return (await api(`/admin/biblioteca/frases-troca/${input.id}`, { metodo: "DELETE" })) as any;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: frasesTrocaKeyBase }),
  });
};
