import { api, geracaoAtual, guardarResposta, temResposta } from "./api";

/**
 * Pré-carga da tela de abertura: enquanto a logo se desenha, busca em paralelo os dados da tela que vai abrir (a da
 * URL) e da moldura (saldo, sino, contador de erros, lista de escritórios), e grava no MESMO lugar que as telas leem
 * (ultimaResposta, em api.ts). A tela que montar junta-se ao pedido em andamento (api.ts junta GETs iguais), então
 * não há segunda ida ao servidor. Depois, em segundo plano e devagar, aquece as outras telas principais que ainda
 * não têm cópia nenhuma.
 *
 * Os caminhos aqui têm de ser EXATAMENTE os que as telas pedem (mesmo texto, mesma ordem dos parâmetros).
 */
export interface ContextoPreCarga { escritorio: string | null; podeGerir: boolean; lawchat: boolean; admin: boolean }

type Lista = (string | false | null | undefined)[];

function caminhosInicio(c: ContextoPreCarga): Lista {
  if (!c.escritorio) return [];
  return ["/inicio/metricas?dias=30", "/inicio", c.podeGerir && "/carteira", c.podeGerir && "/inicio/primeiros-passos", "/funil?dias=30"];
}
function caminhosMeusProdutos(c: ContextoPreCarga): Lista {
  if (!c.escritorio || !c.podeGerir) return [];
  return ["/produtos-ativados?lixeira=0", "/produtos-ativados?lixeira=1", "/saude/numeros"];
}
function caminhosCreditos(c: ContextoPreCarga): Lista {
  if (!c.escritorio || !c.podeGerir) return [];
  return ["/carteira/painel?dias=30", "/carteira/conversas?dias=30&ordem=custo&limite=10", "/carteira/recargas"];
}

const TELAS: [RegExp, (c: ContextoPreCarga) => Lista][] = [
  [/^\/$/, caminhosInicio],
  [/^\/meus-produtos\/?$/, caminhosMeusProdutos],
  [/^\/consumo\/?$/, caminhosCreditos],
];

/** Topo e menu, presentes em quase toda tela (ver Estrutura, SaldoTopo, AvisoSaldo, CentralNotificacoes). */
function caminhosMoldura(c: ContextoPreCarga): Lista {
  return [
    c.escritorio && "/carteira/estado",
    c.escritorio && "/central-notificacoes?limite=30",
    c.escritorio && c.podeGerir && "/inicio/contadores",
    c.lawchat && "/admin/escritorios",
  ];
}

const limpar = (l: Lista): string[] => Array.from(new Set(l.filter((x): x is string => typeof x === "string")));

function buscar(caminho: string): Promise<void> {
  const geracao = geracaoAtual();
  return api(caminho).then((r) => guardarResposta(caminho, r, geracao), () => undefined);
}

let aquecimento = 0;
window.addEventListener("agentesia:sair", () => { aquecimento += 1; });   // saiu: para de aquecer as outras telas

/**
 * Começa a pré-carga. Devolve uma promessa que termina quando os dados da tela atual e da moldura que ainda NÃO
 * tinham cópia chegaram (o que já tinha cópia é conferido por trás e não segura a abertura). Nunca falha.
 */
export function preCarregar(pathname: string, c: ContextoPreCarga): Promise<void> {
  // Logo depois de entrar a URL ainda é /login, /entrar...: a tela que abre é o Início (ver as rotas em main.tsx).
  const rota = /^\/(login|entrar|superadmin|acesso)\/?$/.test(pathname) ? (c.admin ? "/admin/escritorios" : "/") : pathname;
  const daTela = TELAS.find(([re]) => re.test(rota))?.[1](c) ?? [];
  const prioridade = limpar([...daTela, ...caminhosMoldura(c)]);
  const todas: Promise<void>[] = [];
  const esperar: Promise<void>[] = [];
  for (const caminho of prioridade) {
    const tinha = temResposta(caminho);
    const p = buscar(caminho);                      // com cópia: é a conferência que a tela faria de qualquer jeito
    todas.push(p);
    if (!tinha) esperar.push(p);
  }
  const pronto = Promise.all(esperar).then(() => undefined);

  // Depois: as outras telas principais, uma por vez, só as que não têm cópia nenhuma.
  const minha = ++aquecimento;
  const resto = limpar(TELAS.flatMap(([, f]) => f(c))).filter((x) => !prioridade.includes(x));
  const proxima = (i: number) => {
    if (minha !== aquecimento || i >= resto.length) return;
    if (temResposta(resto[i])) { proxima(i + 1); return; }
    void buscar(resto[i]).finally(() => window.setTimeout(() => proxima(i + 1), 150));
  };
  void Promise.all(todas).finally(() => window.setTimeout(() => proxima(0), 800));
  return pronto;
}
