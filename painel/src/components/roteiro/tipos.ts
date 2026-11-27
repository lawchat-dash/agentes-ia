// Roteiro de gravação por produto (servidor: app/gestao/rotas_roteiro_gravacao.py, migração 019).

export type TipoParte = "audio" | "video";
export type Secao = "videos" | "principais" | "objecoes";
export type Qualidade = "boa" | "curta" | "baixa" | "silenciosa";

export interface GravacaoParte {
  chave: string; id_parte: string | null; id_midia: string; nome: string; url: string; tipo: "audio" | "video";
  mime_type: string | null; tamanho_bytes: number | null; qualidade: Qualidade | null; duracao_s: number | null;
  criado_em: string; atualizado_em: string; reaproveitada: boolean;
}

export interface ParteRoteiro {
  id: string; id_produto_biblioteca: string; titulo: string; texto: string; tipo: TipoParte; secao: Secao;
  marcador: string | null; chave_geral: string | null; exemplo_url: string | null; ordem: number; ativo: boolean;
  gravacao: GravacaoParte | null;
}

export interface ResumoRoteiro {
  total: number; gravadas: number; videos: number; audios: number; faltam_videos: number; faltam_audios: number;
  /** Vídeos + áudios principais: concluem o roteiro e liberam a ativação. */
  obrigatorias?: number; obrigatorias_gravadas?: number;
  /** Quebra de objeção: opcional, fica em aberto para gravar depois (o agente usa o texto enquanto isso). */
  objecoes?: number; objecoes_gravadas?: number; concluido?: boolean;
}

export interface RoteiroDoProduto extends ResumoRoteiro {
  produto: { id: string; slug: string; nome: string; categoria: string | null; icone: string | null; roteiro_orientacoes: string | null };
  liberado: boolean; motivo: string | null; partes: ParteRoteiro[];
}

export interface ProdutoComRoteiro extends ResumoRoteiro {
  id: string; slug: string; nome: string; categoria: string | null; icone: string | null; capa_gradiente?: string | null; ativado: boolean;
}

export const NOME_SECAO: Record<Secao, string> = { videos: "Vídeos", principais: "Áudios principais", objecoes: "Quebra de objeção" };

/** Mesma comparação do servidor (normalizar): sem acento, minúsculo, só letras e números. */
export const normalizarMarcador = (nome: string) =>
  nome.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
