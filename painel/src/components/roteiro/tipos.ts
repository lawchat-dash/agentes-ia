// Roteiro de gravação por produto (servidor: app/gestao/rotas_roteiro_gravacao.py, migração 019).

export type TipoParte = "audio" | "video";
export type Secao = "videos" | "principais" | "objecoes";
export type Qualidade = "boa" | "curta" | "baixa" | "silenciosa";
export type OrigemGravacao = "propria" | "pronta";

export interface GravacaoParte {
  chave: string; id_parte: string | null; id_midia: string; nome: string; url: string; tipo: "audio" | "video";
  mime_type: string | null; tamanho_bytes: number | null; qualidade: Qualidade | null; duracao_s: number | null;
  criado_em: string; atualizado_em: string; reaproveitada: boolean;
  /** "pronta" = veio de uma voz pronta da LawChat (migração 020); sem a 020 o servidor manda "propria" ou nada. */
  origem?: OrigemGravacao; id_voz?: string | null; voz_nome?: string | null;
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

// Vozes prontas (servidor: app/gestao/rotas_vozes_prontas.py, migração 020): áudios do roteiro já gravados pela LawChat
// (voz de IA ou da equipe) que o escritório usa no lugar de gravar.

export interface AudioVozPronta { id_parte: string; titulo: string; secao: Secao; tipo: "audio" | "video"; url: string }

export interface VozPronta {
  id: string; nome: string; tom: string | null; genero: "feminina" | "masculina" | null; origem: "ia" | "equipe";
  descricao: string | null; partes_cobertas: number; total_partes: number; em_uso: boolean;
  amostra: { url: string; tipo: "audio" | "video"; titulo: string } | null;
  audios: AudioVozPronta[];
  /** Partes cujo áudio fala algo que o escritório precisa conferir (honorários com valor padrão). */
  avisos?: { id_parte: string; titulo: string; aviso: string }[];
}

/** GET /api/roteiro-gravacao/{id_produto}/vozes */
export interface VozesDoProduto { texto_aceite: string; vozes: VozPronta[] }

/** POST /api/roteiro-gravacao/{id_produto}/vozes/{id_voz}/usar */
export interface ResultadoUsarVoz { usadas: number; mantidas: number; puladas?: number; total: number }
