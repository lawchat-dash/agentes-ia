/**
 * Cópia das respostas das telas guardada no navegador (localStorage), para que abrir de novo o painel ou recarregar a
 * página (F5) mostre os dados na hora, enquanto a tela confere com o servidor por trás.
 *
 * Segurança:
 * - Cada cópia leva o usuário dono dela e a versão do painel. Ao entrar, só voltam as cópias do MESMO usuário e da
 *   MESMA versão; as outras são apagadas. A chave de cada cópia já tem o escritório e a visão (ver chaveDoPedido em
 *   api.ts): um escritório nunca vê o dado de outro, nem a equipe LawChat "como cliente" vê o dado da visão LawChat.
 * - Sair da conta (ou a sessão cair) apaga tudo.
 * - Validade máxima de 24 h; resposta grande (> 300 KB) não é guardada; acima do teto total, sai a mais antiga.
 * - Nada que pareça segredo: caminhos de senha/token/entrada e respostas com campos como "token" ou "senha" ficam de fora.
 */

const PREFIXO = "agentesia_cache:";
const VALIDADE_MS = 24 * 60 * 60 * 1000;
const MAX_ENTRADA = 300_000;            // caracteres do JSON de uma resposta
const MAX_TOTAL = 2_500_000;            // soma de todas as cópias (o localStorage tem ~5 MB por site)
const MAX_ENTRADAS = 120;

const CAMINHO_PROIBIDO = /senha|segredo|token|entrar|sessao|^\/eu(\?|$)|^\/sair/i;
const CAMPO_SENSIVEL = /"(token|token_[a-z_]+|access_token|refresh_token|senha|senha_[a-z_]+|password|segredo|secret|client_secret|api_key|apikey|chave_api|chave_secreta|authorization|cookie)"\s*:/i;

interface Entrada { u: string; v: string; t: number; d: unknown }

/** Versão do painel: o nome (com hash) do arquivo principal. Mudou a versão, as cópias antigas não servem mais. */
function versaoDoPainel(): string {
  try {
    const scripts = Array.from(document.querySelectorAll<HTMLScriptElement>('script[type="module"][src]'));
    const principal = scripts.find((s) => s.src.includes("/assets/")) ?? scripts[scripts.length - 1];
    return principal ? principal.src.split("/").pop() ?? "dev" : "dev";
  } catch {
    return "dev";
  }
}
const VERSAO = versaoDoPainel();

let usuario: string | null = null;
const fila = new Map<string, unknown>();
let temporizador: number | null = null;

function armazenamento(): Storage | null {
  try { return window.localStorage; } catch { return null; }
}

function chavesGuardadas(ls: Storage): string[] {
  const chaves: string[] = [];
  for (let i = 0; i < ls.length; i++) {
    const k = ls.key(i);
    if (k && k.startsWith(PREFIXO)) chaves.push(k);
  }
  return chaves;
}

/**
 * Liga a cópia para este usuário e devolve as cópias dele que ainda valem (da mais antiga para a mais nova).
 * Apaga as de outro usuário, de outra versão do painel e as vencidas.
 */
export function ativar(idUsuario: string): [string, unknown][] {
  if (usuario !== idUsuario) descartarFila();
  usuario = idUsuario;
  const ls = armazenamento();
  if (!ls) return [];
  const agora = Date.now();
  const validas: [string, unknown, number][] = [];
  for (const k of chavesGuardadas(ls)) {
    try {
      const e = JSON.parse(ls.getItem(k) ?? "null") as Entrada | null;
      if (!e || e.u !== idUsuario || e.v !== VERSAO || !(agora - e.t < VALIDADE_MS) || e.t > agora + 60_000) { ls.removeItem(k); continue; }
      validas.push([k.slice(PREFIXO.length), e.d, e.t]);
    } catch {
      try { ls.removeItem(k); } catch { /* nada */ }
    }
  }
  return validas.sort((a, b) => a[2] - b[2]).map(([k, d]) => [k, d]);
}

/** Desliga e apaga tudo (saiu da conta / sessão caiu). */
export function desativar(): void {
  usuario = null;
  apagarTudo();
}

/** Apaga as cópias guardadas (alguma coisa foi salva: tudo fica velho). O usuário continua ligado. */
export function apagarTudo(): void {
  descartarFila();
  const ls = armazenamento();
  if (!ls) return;
  try { for (const k of chavesGuardadas(ls)) ls.removeItem(k); } catch { /* nada */ }
}

/** Guarda (um instante depois, fora da renderização) a resposta de um GET. `caminho` só serve para a lista de exclusão. */
export function gravar(chave: string, caminho: string, dados: unknown): void {
  if (!usuario || CAMINHO_PROIBIDO.test(caminho)) return;
  fila.set(chave, dados);
  if (temporizador == null) temporizador = window.setTimeout(descarregar, 400);
}

function descartarFila(): void {
  fila.clear();
  if (temporizador != null) { window.clearTimeout(temporizador); temporizador = null; }
}

function descarregar(): void {
  temporizador = null;
  const ls = armazenamento();
  if (!ls || !usuario) { fila.clear(); return; }
  const agora = Date.now();
  for (const [chave, dados] of fila) {
    const k = PREFIXO + chave;
    let texto: string;
    try { texto = JSON.stringify({ u: usuario, v: VERSAO, t: agora, d: dados } satisfies Entrada); } catch { continue; }
    if (texto.length > MAX_ENTRADA || CAMPO_SENSIVEL.test(texto)) { try { ls.removeItem(k); } catch { /* nada */ } continue; }
    try {
      ls.setItem(k, texto);
    } catch {
      podar(ls, texto.length);                 // cheio: tira as mais antigas e tenta mais uma vez
      try { ls.setItem(k, texto); } catch { /* fica só na memória */ }
    }
  }
  fila.clear();
  podar(ls, 0);
}

/** Mantém o teto de quantidade e de tamanho, tirando as mais antigas. */
function podar(ls: Storage, folga: number): void {
  try {
    const itens = chavesGuardadas(ls).map((k) => {
      const texto = ls.getItem(k) ?? "";
      // "t" vem logo no começo do JSON ({u, v, t, d}): lê só ele, sem abrir a resposta inteira.
      const t = Number(/"t":(\d+)/.exec(texto.slice(0, 300))?.[1] ?? 0);
      return { k, t, tamanho: texto.length };
    }).sort((a, b) => a.t - b.t);
    let total = itens.reduce((s, i) => s + i.tamanho, 0) + folga;
    let quantidade = itens.length;
    for (const i of itens) {
      if (total <= MAX_TOTAL && quantidade <= MAX_ENTRADAS) break;
      ls.removeItem(i.k);
      total -= i.tamanho;
      quantidade -= 1;
    }
  } catch { /* nada */ }
}
