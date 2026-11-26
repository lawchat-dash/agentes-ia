// Frases de troca de departamento (tabela sistemaia_frases_troca — só o super admin altera).
//
// COMO O FLUXO USA: o bot troca o departamento do lead comparando a resposta da IA com a
// prompts.mensagem_troca da etapa DESTINO. O agente anterior fala a frase exata (ela está no
// prompt dele) e o lead passa para a etapa dona da frase.
//
// MODELO (igual ao @Agente do handoff): no EDITOR o prompt guarda o token amigável
// "@Transferência: Closer" (chip laranja); no ENVIO AO BOT o token vira o texto exato da
// frase no prompt, e a mesma frase vai para a mensagem_troca da etapa destino. Na CARGA do
// bot o caminho é o reverso (texto exato → token). Módulo puro: o carregamento do banco
// fica em hooks/useFrasesTroca (alimenta este registro).

export interface FraseTroca {
  id: string;
  /** Produto do catálogo dono da frase — cada produto tem as SUAS frases (mig 0133). */
  id_produto_biblioteca?: string | null;
  /** Etapa que o lead ENTRA quando a frase é dita (dona da mensagem_troca). */
  etapa_destino: string;
  /** Nome do token: "@Transferência: <nome>" (imutável — identifica a frase nos prompts). */
  nome: string;
  /** Texto exato que a IA fala e que o bot compara. */
  frase: string;
  descricao: string | null;
  ordem: number;
}

export const PREFIXO_TRANSFERENCIA = "Transferência: ";
export const COR_TRANSFERENCIA = "#ea580c";

/** Departamentos que RECEBEM o lead (donos da mensagem_troca), na ordem do funil. O nome é o
 *  do token — espelha sistemaia_nome_frase_troca() no banco. */
export const ETAPAS_TROCA: { etapa: string; nome: string }[] = [
  { etapa: "sdr", nome: "SDR" },
  { etapa: "periododegraca", nome: "Período de Graça" },
  { etapa: "closer", nome: "Closer" },
  { etapa: "contratos", nome: "Coleta de Dados" },
  { etapa: "assinatura", nome: "Assinatura" },
  { etapa: "desqualificado", nome: "Desqualificado" },
];

/** Trecho selecionado no prompt → frase: tira espaços, aspas, ** e ">" das pontas (esses
 *  ficam no prompt, fora do chip). Devolve quantos caracteres cortou de cada lado. */
export const limparTrechoFrase = (bruto: string): { frase: string; corteInicio: number; corteFim: number } => {
  const ini = (bruto.match(/^[\s"'“”‘’*_>]*/)?.[0].length) ?? 0;
  const resto = bruto.slice(ini);
  const fim = (resto.match(/[\s"'“”‘’*_]*$/)?.[0].length) ?? 0;
  return { frase: resto.slice(0, resto.length - fim), corteInicio: ini, corteFim: fim };
};

/** Rótulo do token sem o "@" (é o que vai no menu @ e no chip). */
export const rotuloFrase = (nome: string) => `${PREFIXO_TRANSFERENCIA}${nome}`;

// Registro POR PRODUTO: cada produto do catálogo tem as suas frases (a mesma etapa pode ter
// textos diferentes em produtos diferentes). As funções abaixo usam, por padrão, as frases do
// PRODUTO ATUAL — definido pela tela aberta (FrasesProdutoProvider / setProdutoFrases).
const REGISTRO = new Map<string, FraseTroca[]>();
let PRODUTO_ATUAL: string | null = null;

/** Define o produto do catálogo cujas frases valem na tela aberta. */
export const setProdutoFrases = (idProduto: string | null | undefined) => {
  PRODUTO_ATUAL = idProduto ?? null;
};
export const getProdutoFrases = () => PRODUTO_ATUAL;

/** Frases do produto informado (ou do produto atual). Sem produto → nenhuma. */
export const getFrasesTroca = (idProduto: string | null = PRODUTO_ATUAL): FraseTroca[] =>
  (idProduto ? REGISTRO.get(idProduto) : undefined) ?? [];

export const setFrasesTroca = (idProduto: string, lista: FraseTroca[] | null | undefined) => {
  REGISTRO.set(idProduto, Array.isArray(lista) ? lista : []);
};

const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
// Não casa "Closer" dentro de "Closers" (nomes que são prefixo de outra palavra).
const FIM_PALAVRA = "(?![A-Za-zÀ-ÿ0-9])";
const tokenRe = (nome: string, flags = "g") =>
  new RegExp("@" + escapeRe(rotuloFrase(nome)) + FIM_PALAVRA, flags);

/** "@Transferência: Closer" → texto exato da frase. Usado SÓ no que vai para o bot. */
export const expandirFrasesParaBot = (texto: string, lista: FraseTroca[] = getFrasesTroca()): string => {
  if (!texto || !texto.includes("@" + PREFIXO_TRANSFERENCIA)) return texto;
  let out = texto;
  for (const f of [...lista].sort((a, b) => b.nome.length - a.nome.length)) {
    out = out.replace(tokenRe(f.nome), () => f.frase); // função: texto entra literal
  }
  return out;
};

/** Reverso (carga do bot/catálogo): texto exato da frase → "@Transferência: <nome>". */
export const recolherFrasesDoBot = (texto: string, lista: FraseTroca[] = getFrasesTroca()): string => {
  if (!texto) return texto;
  let out = texto;
  for (const f of [...lista].sort((a, b) => b.frase.length - a.frase.length)) {
    if (f.frase && out.includes(f.frase)) out = out.split(f.frase).join("@" + rotuloFrase(f.nome));
  }
  return out;
};

/** Frase cadastrada para a etapa (a mensagem_troca daquela etapa no bot). */
export const fraseDaEtapa = (etapa: string, lista: FraseTroca[] = getFrasesTroca()): FraseTroca | null =>
  lista.find((f) => f.etapa_destino === etapa) ?? null;

/** Frases referenciadas (por token) num texto — p/ mostrar "este agente transfere para…". */
export const frasesReferenciadas = (texto: string, lista: FraseTroca[] = getFrasesTroca()): FraseTroca[] =>
  !texto ? [] : lista.filter((f) => tokenRe(f.nome, "").test(texto));

/** Etapas que PASSAM o lead adiante: o prompt delas precisa ter ao menos 1 Frase para
 *  Transferência de saída. Assinatura e Desqualificado são fim de funil (não precisam). */
export const ETAPAS_COM_SAIDA = ["sdr", "periododegraca", "closer", "contratos"];

/** Para onde cada etapa passa o lead (a frase de saída é a de ENTRADA de um destes). */
export const DESTINOS_DA_ETAPA: Record<string, string[]> = {
  sdr: ["periododegraca", "closer"],
  periododegraca: ["closer"],
  closer: ["contratos"],
  contratos: ["assinatura"],
};

/** O prompt tem alguma frase de SAÍDA — token ou texto exato de uma frase de OUTRA etapa?
 *  (A frase de entrada da própria etapa não conta.) */
export const temFraseDeSaida = (prompt: string, etapa: string, lista: FraseTroca[] = getFrasesTroca()): boolean => {
  const txt = prompt ?? "";
  return lista.some((f) => f.etapa_destino !== etapa && (tokenRe(f.nome, "").test(txt) || (!!f.frase && txt.includes(f.frase))));
};

/** Agentes que passam o lead adiante e ficaram SEM frase de saída (ex.: alguém apagou o chip).
 *  Sem frases cadastradas não há o que exigir → []. `ignorarVazios`: prompt vazio = agente
 *  ainda não configurado (rascunho do catálogo), não entra na trava. */
export const agentesSemFraseDeSaida = <T extends { etapa: string; prompt: string }>(
  agentes: T[], lista: FraseTroca[] = getFrasesTroca(), opts: { ignorarVazios?: boolean } = {},
): T[] => {
  if (lista.length === 0) return [];
  return agentes.filter((a) =>
    ETAPAS_COM_SAIDA.includes(a.etapa)
    // só cobra se ESTE produto tem frase para um destino da etapa (frase excluída não trava ninguém)
    && lista.some((f) => (DESTINOS_DA_ETAPA[a.etapa] ?? []).includes(f.etapa_destino))
    && !(opts.ignorarVazios && !(a.prompt ?? "").trim())
    && !temFraseDeSaida(a.prompt, a.etapa, lista));
};

/** Frase excluída: o chip "@Transferência: X" vira o texto exato dela (igual ao que o bot recebia). */
export const trocarTokenPorTexto = (texto: string, f: Pick<FraseTroca, "nome" | "frase">): string =>
  texto ? texto.replace(tokenRe(f.nome), () => f.frase) : texto;

/** Sobrou token sem frase cadastrada? (frase excluída ou registro não carregou) */
export const temTokenTransferencia = (texto: string): boolean =>
  !!texto && texto.includes("@" + PREFIXO_TRANSFERENCIA);

/** Validação da frase no formulário do admin (espelha o CHECK da tabela). */
export const validarFrase = (frase: string): string | null => {
  const t = frase.trim();
  if (t.length < 8) return "A frase precisa ter pelo menos 8 caracteres.";
  if (t.length > 400) return "A frase pode ter no máximo 400 caracteres.";
  if (/\n/.test(t)) return "Use uma linha só — o bot compara a frase exatamente.";
  if (/[@{}[\]"\\]/.test(t)) return "Sem @, {{ }}, [[ ]], aspas ou barra: a frase é comparada literalmente.";
  return null;
};
