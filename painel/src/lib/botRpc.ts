/**
 * Porte do agents-lawchat-main: lá isto chamava funções sistemaia_*_no_bot via RPC do Supabase e
 * gravava um log em sistemaia_logs_funcoes. Aqui não há RPC nem log remoto: as telas falam com a
 * API do painel (ver docs/API_PRODUTOS.md). Fica só o registro no console para depuração.
 */
export type BotRpcMap = {
  sistemaia_sincronizar_followup_no_bot: { ok: boolean };
  sistemaia_mudar_status_no_bot: { ok: boolean };
  sistemaia_mudar_status_followup_no_bot: { ok: boolean };
  sistemaia_inativar_produto_no_bot: { ok: boolean };
  sistemaia_sincronizar_produto_no_bot: { ok: boolean };
  sistemaia_habilitar_cliente_no_bot: { ok: boolean };
  sistemaia_sincronizar_numeros_whatsapp: Array<Record<string, unknown>>;
  sistemaia_sincronizar_notificacao_no_bot: { ok: boolean };
  sistemaia_trocar_canal_no_bot: { ok: boolean; numero_anterior: string | null; numero_novo: string; conexao_nova: number; conexao_vinculada: boolean };
};

/** Registra no console uma chamada (sucesso/erro) com a duração — substitui o log remoto. */
export function registrarChamada(funcao: string, inicio: number, erro?: unknown, referencia?: string | null) {
  const duracao = Date.now() - inicio;
  if (erro) console.warn(`[botRpc] ${funcao} falhou (${duracao} ms)`, referencia ?? "", erro);
  else console.info(`[botRpc] ${funcao} ok (${duracao} ms)`, referencia ?? "");
}

export async function chamarRpcBot<K extends keyof BotRpcMap>(
  nomeSql: K,
  params: Record<string, unknown>,
  meta?: { idConta?: string | null; referencia?: string | null },
): Promise<BotRpcMap[K]>;
export async function chamarRpcBot(
  nomeSql: string,
  params: Record<string, unknown>,
  meta?: { idConta?: string | null; referencia?: string | null },
): Promise<unknown>;
export async function chamarRpcBot(
  nomeSql: string,
  _params: Record<string, unknown>,
  meta: { idConta?: string | null; referencia?: string | null } = {},
): Promise<unknown> {
  const erro = new Error(`Função ${nomeSql} não existe neste sistema: use a rota equivalente da API do painel.`);
  registrarChamada(nomeSql.replace(/^sistemaia_/, "").replace(/_no_bot$/, ""), Date.now(), erro, meta.referencia);
  throw erro;
}
