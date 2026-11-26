import { useCallback, useEffect, useState } from "react";
import { api, enviar } from "@/api";
import { useAuth } from "@/contexts/AuthContext";

export interface ZapsignInput {
  variable: string;
  label: string;
  type: string;
  required: boolean;
}

export interface ZapsignModel {
  id: string;
  name: string;
  variables: string[];
  /** Variáveis detalhadas (tipo/obrigatório) — usado no mapeamento (aba 2). */
  inputs?: ZapsignInput[];
  /** Nomes dos documentos complementares anexados ao modelo. */
  extras?: string[];
}

/** Configuração da integração ZapSign guardada no rascunho do produto. */
export interface ZapsignConfig {
  enabled?: boolean;
  api_token?: string;
  /** Modelo padrão usado para gerar o contrato (token do template). */
  template_id?: string;
  /** Cache dos modelos sincronizados da conta ZapSign. */
  templates?: ZapsignModel[];
  /** ISO da última sincronização. */
  synced_at?: string;
  /** Pós-assinatura: etapa do CRM ao assinar (ex.: "concluido"). */
  pos_assinatura?: { etapa?: string };
}

/** Config da integração a NÍVEL DE ESCRITÓRIO (agentesia_integracoes.config, tipo zapsign). */
export interface ZapsignAccountConfig {
  api_token?: string;
  webhook_id?: number | null;
  webhook_modelo?: string;
  synced_at?: string;
  ambiente?: string;
  modelos?: { id_modelo: string; nome: string; padrao: boolean; id_agente?: string | null; id_ativado?: string | null; mapeamento: { variavel: string; campo: string; valor?: string }[]; obrigatorios?: string[] }[];
}

/** Vínculo Produto ↔ Modelo de Contrato (o item DESTE produto na lista de modelos da ZapSign do escritório). */
export interface ProdutoContrato {
  id?: string;
  modelo_token?: string | null;
  modelo_nome?: string | null;
  variaveis?: ZapsignInput[];
  mapeamento?: Record<string, { origem: string; valor?: string; campo?: string }>;
  webhook_id?: number | null;
  id_agente_weaver?: number | null;
}

/** Ligação variável → campo do lead que o servidor entende (contrato/dados.py → CAMPOS). */
interface Ligacao { variavel: string; campo: string; valor?: string }

/** Nome normalizado da variável → campo do servidor (nome, cpf, endereco, numero, …). */
const CAMPO_SERVIDOR: Record<string, string> = {
  nome: "nome", "nome completo": "nome", email: "email", "e mail": "email",
  telefone: "telefone", celular: "telefone", whatsapp: "telefone", cpf: "cpf", rg: "rg",
  endereco: "endereco", logradouro: "endereco", numero: "numero", complemento: "complemento",
  bairro: "bairro", cidade: "cidade", estado: "estado", uf: "estado", cep: "cep",
  profissao: "profissao", "estado civil": "estado_civil",
  data: "@data_geracao", "data assinatura": "@data_geracao",
};
const normalizar = (s: string) =>
  s.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[{}]/g, "").replace(/[_-]+/g, " ").trim().toLowerCase();

/** Campo do servidor para uma variável do modelo (padrão da LawChat primeiro, depois pelo nome). */
export const campoDoServidor = (variavel: string, padrao: Ligacao[] = []): string | null => {
  const nome = normalizar(variavel);
  const doPadrao = padrao.find((m) => normalizar(m.variavel) === nome)?.campo;
  return doPadrao || CAMPO_SERVIDOR[nome] || null;
};

/** Resposta de GET /integracoes/zapsign/modelos. */
interface LeituraModelos { modelos: { id: string; nome: string }[]; variaveis?: string[]; campos?: Record<string, string>; mapeamento_padrao?: Ligacao[] }

let PADRAO_CACHE: Ligacao[] = [];

/** Executa as promessas em lotes pequenos (não martelar a ZapSign com N pedidos de uma vez). */
async function emLotes<T, R>(itens: T[], tamanho: number, fn: (t: T) => Promise<R>): Promise<R[]> {
  const out: R[] = [];
  for (let i = 0; i < itens.length; i += tamanho) out.push(...(await Promise.all(itens.slice(i, i + tamanho).map(fn))));
  return out;
}

/**
 * Fala com a API do painel (o navegador nunca chama a ZapSign direto): o token fica no cofre do
 * servidor (PUT /integracoes/zapsign) e os modelos vêm de GET /integracoes/zapsign/modelos.
 */
export function useZapsign() {
  const [syncing, setSyncing] = useState(false);

  /** (Se veio token) grava/testa o token; depois devolve os modelos da conta ZapSign com as variáveis. */
  const sincronizarModelos = async (
    apiToken?: string,
  ): Promise<{ models?: ZapsignModel[]; error?: string }> => {
    const token = (apiToken ?? "").trim();
    setSyncing(true);
    try {
      if (token) {
        const integracao = await enviar<any>("/integracoes/zapsign", { token }, "PUT");
        if (integracao?.situacao === "erro") return { error: integracao?.erro ?? "A ZapSign recusou o token." };
      }
      const leitura = await api<LeituraModelos>("/integracoes/zapsign/modelos");
      PADRAO_CACHE = leitura?.mapeamento_padrao ?? PADRAO_CACHE;
      const base = leitura?.modelos ?? [];
      const models = await emLotes(base, 4, async (m): Promise<ZapsignModel> => {
        const det = await api<LeituraModelos>(`/integracoes/zapsign/modelos?id_modelo=${encodeURIComponent(m.id)}`).catch(() => null);
        const variables = det?.variaveis ?? [];
        return {
          id: m.id,
          name: m.nome ?? m.id,
          variables,
          inputs: variables.map((v) => ({ variable: `{{${v}}}`, label: v, type: "input", required: true })),
        };
      });
      return { models };
    } catch (e: any) {
      return { error: e?.message ?? "Falha ao conectar com a ZapSign." };
    } finally {
      setSyncing(false);
    }
  };

  /** Cadastra (uma vez) na conta ZapSign do escritório o aviso de assinatura apontando para o servidor. */
  const registrarWebhook = async (_apiToken: string, _templateId: string): Promise<{ webhook_id?: number; error?: string }> =>
    conectarAvisoAssinatura();

  /** Idem: não há webhook criado pelo navegador para remover. */
  const removerWebhook = async (_apiToken: string): Promise<{ error?: string }> => ({});

  return { syncing, sincronizarModelos, registrarWebhook, removerWebhook };
}

/** POST /integracoes/zapsign/aviso-assinatura: o servidor cadastra o webhook na conta ZapSign (reusa se já existe). */
export async function conectarAvisoAssinatura(): Promise<{ webhook_id?: number; error?: string }> {
  try {
    const r = await enviar<{ webhook_id?: number | string | null }>("/integracoes/zapsign/aviso-assinatura", {});
    return { webhook_id: (r?.webhook_id as number) ?? undefined };
  } catch (e: any) {
    return { error: e?.message ?? "Falha ao conectar o aviso de assinatura." };
  }
}

/**
 * Token da ZapSign a NÍVEL DE ESCRITÓRIO. Salvo uma vez (no cofre do servidor) e reaproveitado em
 * todos os produtos. O token não volta para o navegador: `token` fica vazio e `finalSegredo`
 * mostra o final do que está salvo.
 */
export function useZapsignAccount() {
  const { workspace } = useAuth();
  const [token, setToken] = useState("");
  const [config, setConfig] = useState<ZapsignAccountConfig>({});
  const [temToken, setTemToken] = useState(false);
  const [finalSegredo, setFinalSegredo] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [savingToken, setSavingToken] = useState(false);

  const reload = useCallback(async () => {
    if (!workspace) { setLoading(false); return; }
    setLoading(true);
    try {
      const r = await api<{ integracoes: Record<string, any> }>("/integracoes");
      const z = r?.integracoes?.zapsign ?? null;
      setConfig(((z?.config ?? {}) as ZapsignAccountConfig));
      setTemToken(!!(z?.tem_segredo || z?.final_segredo));
      setFinalSegredo(z?.final_segredo ?? null);
    } catch {
      setConfig({});
    } finally {
      setLoading(false);
    }
  }, [workspace]);

  useEffect(() => { void reload(); }, [reload]);

  const saveToken = useCallback(async (apiToken: string): Promise<{ error?: string }> => {
    if (!workspace) return { error: "Conta não carregada." };
    const novoToken = apiToken.trim();
    if (!novoToken) return {};
    setSavingToken(true);
    try {
      const integracao = await enviar<any>("/integracoes/zapsign", { token: novoToken, ambiente: config.ambiente ?? "producao" }, "PUT");
      if (integracao?.situacao === "erro") return { error: integracao?.erro ?? "A ZapSign recusou o token." };
      setToken("");
      setTemToken(true);
      setFinalSegredo(integracao?.final_segredo ?? null);
      setConfig((integracao?.config ?? config) as ZapsignAccountConfig);
      return {};
    } catch (e: any) {
      return { error: e?.message ?? "Falha ao salvar o token." };
    } finally {
      setSavingToken(false);
    }
  }, [workspace, config]);

  /** Desconectar: não há rota para apagar o token do cofre; o produto só deixa de usar a ZapSign. */
  const clearToken = useCallback(async () => {
    setToken("");
  }, []);

  return { token, config, temToken, finalSegredo, loading, savingToken, saveToken, clearToken, reload };
}

type ModeloSalvo = NonNullable<ZapsignAccountConfig["modelos"]>[number];

/** Resposta de GET/PUT /integracoes/zapsign/produtos/{id}: o modelo deste produto e o padrão do escritório. */
interface LeituraContratoProduto { modelo: ModeloSalvo | null; padrao?: ModeloSalvo | null }

const linhaDoModelo = (m: ModeloSalvo): ProdutoContrato => ({
  id: m.id_modelo,
  modelo_token: m.id_modelo,
  modelo_nome: m.nome,
  mapeamento: Object.fromEntries((m.mapeamento ?? []).map((l) => [`{{${l.variavel}}}`, { origem: "sistema", campo: l.campo }])),
});

/**
 * Vínculo Produto ↔ Modelo de Contrato. Cada produto tem o SEU item na lista de modelos da ZapSign do
 * escritório: GET/PUT /integracoes/zapsign/produtos/{produtoId} lê e grava só esse item (salvar o
 * contrato de um produto nunca apaga o de outro). `produtoId` = agentesia_produtos_ativados.id (o
 * rascunho também serve: na ativação o servidor liga o modelo ao agente). `padrao` = o modelo do
 * escritório que vale enquanto este produto não tem um próprio.
 */
export function useProdutoContrato(produtoId?: string) {
  const { workspace } = useAuth();
  const [row, setRow] = useState<ProdutoContrato | null>(null);
  const [padrao, setPadrao] = useState<ProdutoContrato | null>(null);
  const [loading, setLoading] = useState(true);
  const [salvando, setSalvando] = useState(false);

  const reload = useCallback(async () => {
    if (!produtoId) { setLoading(false); return; }
    setLoading(true);
    try {
      const r = await api<LeituraContratoProduto>(`/integracoes/zapsign/produtos/${encodeURIComponent(produtoId)}`);
      setRow(r?.modelo ? linhaDoModelo(r.modelo) : null);
      setPadrao(r?.padrao ? linhaDoModelo(r.padrao) : null);
    } catch {
      setRow(null);
      setPadrao(null);
    } finally {
      setLoading(false);
    }
  }, [produtoId]);

  useEffect(() => { void reload(); }, [reload]);

  const salvar = useCallback(async (patch: Partial<ProdutoContrato>): Promise<{ error?: string }> => {
    if (!workspace || !produtoId) return { error: "Produto não carregado." };
    if (!patch.modelo_token) return { error: "Escolha um modelo." };
    setSalvando(true);
    try {
      // Só vão as variáveis que o sistema sabe preencher (excluídas e "fora do padrão" ficam de fora).
      const mapeamento: Ligacao[] = Object.entries(patch.mapeamento ?? {})
        .filter(([, v]) => v?.origem === "sistema")
        .map(([variavel]) => {
          const nome = variavel.replace(/[{}]/g, "").trim();
          return { variavel: nome, campo: campoDoServidor(nome, PADRAO_CACHE) ?? "" };
        })
        .filter((l) => l.variavel && l.campo);
      // Só o item deste produto (o servidor não mexe no dos outros nem tira o padrão de ninguém).
      const r = await enviar<LeituraContratoProduto>(`/integracoes/zapsign/produtos/${encodeURIComponent(produtoId)}`, {
        id_modelo: patch.modelo_token, nome: patch.modelo_nome ?? patch.modelo_token, mapeamento,
      }, "PUT");
      setRow(r?.modelo ? { ...linhaDoModelo(r.modelo), ...patch, id: patch.modelo_token } : { ...(row ?? {}), ...patch, id: patch.modelo_token });
      return {};
    } catch (e: any) {
      return { error: e?.message ?? "Falha ao salvar o contrato." };
    } finally {
      setSalvando(false);
    }
  }, [workspace, produtoId, row]);

  return { row, padrao, loading, salvando, salvar, reload };
}
