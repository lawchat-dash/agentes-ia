# Spec: contagem de tokens e custo de IA (fluxo n8n "WEAVER - CONTAR TOKEN")

Lido em 22/11/2026 a partir do arquivo exportado do n8n (38 nós, fuso `America/Sao_Paulo`). Foram lidos só a estrutura, os parâmetros e as conexões. `pinData` foi ignorado. Nenhum dado de lead foi copiado.

Credenciais do fluxo (todas fora deste documento): API do n8n `<SEGREDO: credencial n8nApi>`, Postgres do Weaver `<SEGREDO: credencial postgres>`, Redis `<SEGREDO: credencial redis>`.

Legenda: **[WEAVER]** = tabela ou função do banco AGENT WEAVER no Supabase. **[N8N]** = infraestrutura do próprio n8n (API de execuções, data table, Redis). O sistema novo não usa nem altera nenhuma das duas.

---

## 1. Objetivo

Registrar quantos tokens cada execução do fluxo principal de atendimento (geração 99) gastou, por modelo, e ligar esse consumo ao escritório (`id_cliente`), ao agente (`id_agente`) e ao lead (número de WhatsApp).

O fluxo não chama a IA nem mede nada na hora da chamada. Ele espera a execução do atendimento terminar, busca essa execução pela API do n8n, varre o `runData` de todos os nós e soma o `tokenUsage` que o n8n guardou. O resultado vai para `consumo_tokens` **[WEAVER]**. O preço e o débito no saldo são feitos depois, por gatilho no banco, não neste fluxo (ver seção 4).

O fluxo também tem três blocos de manutenção que não têm relação com custo: apagar execuções do próprio fluxo, apagar execuções com erro e listar execuções demoradas.

---

## 2. Gatilhos

| Gatilho | Nó | Ligado a | Situação |
|---|---|---|---|
| Subfluxo | `When Executed by Another Workflow` | Caminho principal (seção 3.1) | **Em uso.** O fluxo de atendimento chama este fluxo no fim de cada execução |
| Agenda | `Cron :17` (cron `17 * * * *`, de hora em hora, no minuto 17) | Fila de reprocessamento (seção 3.2) | Em uso |
| Webhook | `Webhook` (POST `contar-tokens`) | **Nada.** O nó não tem saída ligada | Morto. Responde 200 e não faz nada |
| Manual | `Executar manualmente` | `Buscar execuções` → `Filtrar > 5 min` (seção 3.3) | Relatório operacional, rodado à mão |
| Manual, sem gatilho | `Get many executions` → `Delete an execution` e `Get many executions1` → `FILTRA ERROS` → `Delete an execution1` | Nenhum gatilho ligado; roda clicando no nó | Limpeza (seção 3.4) |

Entradas do subfluxo: `ExecutionId` (ID da execução do atendimento a contar), `executionMode` (`test` ou outro), `executionResumeUrl`, `$executionResumeFormUrl` e `Execution` (objeto). Só `ExecutionId` e `executionMode` são usados.

Configuração do fluxo: `saveDataSuccessExecution = none` (execuções bem-sucedidas deste fluxo não ficam salvas), `callerPolicy = workflowsFromSameOwner`.

---

## 3. Lógica passo a passo

### 3.1 Caminho principal (subfluxo, por execução do atendimento)

1. `ESPERA 2 SEGUNDOS INICIAS`: espera 2 s, para dar tempo de a execução que chamou terminar.
2. `EXECUCAO_TESTE?`: se `executionMode == "test"`, vai para `NÃO COBRA` (noOp) e para. Execução de teste no editor do n8n não é contada.
3. `Get an execution` **[N8N]**: busca a execução `ExecutionId` pela API do n8n, com o `runData` completo.
4. `EXECUCAO TERMINOU?`: confere `finished == true`.
   - **Sim** → `Code in JavaScript1` (cálculo, 3.5) → `INSERE NOVA MENSAGEM (s) ->1` (gravação, seção 5). Fim.
   - **Não** → `ESPERA 2 SEGUNDOS` → `INCREMENTA TENTOU 3 VEZES NA EXECUCAO` **[N8N/Redis]**.
5. Redis: `INCR` na chave = ID da execução, com expiração ligada (o TTL não está definido no nó, então vale o padrão do nó Redis do n8n). A chave conta as tentativas.
6. `TENTAMOS 3 VEZES?`: se o contador passou de 3 (ou seja, na 4ª tentativa):
   - **Sim** → `Insert row` na data table `Contar Token` **[N8N]**: coluna `Dados` = JSON das entradas do subfluxo, `Feito = false`. A execução fica na fila para o cron.
   - **Não** → volta para `EXECUCAO TERMINOU?`.

> **Defeito na espera.** O ramo "não" de `TENTAMOS 3 VEZES?` volta para o `IF` sem chamar `Get an execution` de novo. O `IF` passa a testar a saída do Redis, que não tem `finished`, e sempre dá "não". Na prática: ou a execução já tinha terminado na primeira consulta (cerca de 2 s depois da chamada), ou ela vai para a fila depois de 4 esperas, sem nova consulta. A espera `ESPERA 2 SEGUNDOS` não tem tempo configurado e usa o padrão do nó Wait, apesar do nome. Se o fluxo de atendimento chama este subfluxo esperando a resposta, a execução dele nunca está terminada na primeira consulta, e tudo cai na fila.

### 3.2 Fila de reprocessamento (cron de hora em hora)

1. `Pega as linhas` **[N8N]**: até 100 linhas da data table `Contar Token` com `Feito = false`.
2. `Filter`: de novo `Feito == false` (redundante).
3. `Map`: lê `Dados` (JSON em texto), tira espaços sobrando dos textos e devolve `{id da linha, ...entradas}`.
4. `Loop Over Items` (lotes de 1):
   1. `Get an execution2` **[N8N]**: busca a execução (`ExecutionId` sem espaços). Se der erro, segue com a saída de erro (`continueRegularOutput`).
   2. `EXECUCAO TERMINOU?1`: se `finished` for verdadeiro, vai para `Code in JavaScript` (cálculo idêntico ao 3.5) → `INSERE NOVA MENSAGEM (s) ->` (gravação) → `Foi feito o que ta na fila` (marca `Feito = true` na linha) → próximo item. Se não terminou, volta para o loop sem marcar.
5. Ao fim, `Finalizado` (noOp).

Defeitos:
- **Linha eterna.** Se a execução foi apagada ou expirou no n8n, a consulta falha, `finished` fica vazio e a linha nunca é marcada. Ela volta a cada hora. Com 100 linhas nesse estado, a leitura com limite 100 pode deixar de pegar as novas.
- **Loop interrompido.** Se a execução não teve nenhum token (o código devolve zero itens), o Postgres não roda, a linha não é marcada e o loop não recebe item de volta. É provável que os itens seguintes do lote não sejam processados nessa hora.

### 3.3 Relatório de execuções demoradas (manual)

`Buscar execuções` **[N8N]** lista todas as execuções do fluxo principal (ID fixo no nó). `Filtrar > 5 min` calcula a duração de cada uma (até agora, se ainda estiver rodando), formata no horário de Brasília e devolve as que passaram do limite, da maior para a menor. O limite no código é **3 minutos**, apesar do nome "5 min". Não grava nada.

Há ainda `Get an execution1`, solto, com um ID de execução fixo: sobra de depuração.

### 3.4 Limpeza (manual)

- `Get many executions` → `Delete an execution`: apaga **todas** as execuções deste fluxo.
- `Get many executions1` → `FILTRA ERROS` (`status == "error"`) → `Delete an execution1`: apaga as execuções com erro deste fluxo.

Existe só porque o n8n acumula execuções. Não tem equivalente no sistema novo.

### 3.5 Cálculo de tokens (`Code in JavaScript` e `Code in JavaScript1`, idênticos)

Entrada: o objeto da execução devolvido pela API do n8n.

1. Para cada nó e cada rodada em `data.resultData.runData`:
   - **Agente / LangChain:** se existir `data.ai_languageModel[0][0].json.tokenUsage` (ou, na falta dele, `tokenUsageEstimate`), soma `promptTokens` em entrada e `completionTokens` em saída. O modelo vem de `inputOverride.ai_languageModel[0][0].json.options.model`; sem ele, `desconhecido`.
   - **HTTP direto na OpenAI** (imagem, visão): se a saída principal tem `usage` e `model`, soma `usage.prompt_tokens` e `usage.completion_tokens` no modelo `model`.
2. Acumula por modelo: `{modelo: {in, out}}`.
3. Acha o nó gatilho da execução (o de menor `executionIndex`) e pega o `body` da primeira saída dele.
4. Número do agente: `customData.ConexaoNumeroTelefone`, senão `body.numero_ia`, senão `body.numero_agente`.
   Número do lead: `customData.ContatoUserNumber`, senão `body.numero_lead`, senão `body.destinatario`.
5. Saída: um item por modelo com `in + out > 0`:
   `{execution_id, numero_agente, numero_lead, modelo, tokens_in, tokens_out}`.

Limitações do cálculo:
- `tokenUsageEstimate` é estimativa do n8n, não o número da API.
- Tokens lidos do cache não são separados: entram como entrada cheia.
- Transcrição de áudio (cobrada por minuto) e embeddings da busca na base não aparecem em `ai_languageModel` e ficam de fora.
- Modelo `desconhecido` não casa com nenhum preço.
- O vínculo com escritório e agente depende do número do WhatsApp do agente, não de um ID.

---

## 4. Tabela de preços

**O fluxo não tem tabela de preços e não calcula valor.** Ele grava só tokens.

Pelo levantamento do banco antigo (`ESTRUTURA.md`, seção 1.3), o preço é aplicado depois, no banco:
- `sistemaia_precos_modelos` **[WEAVER]**: preço por modelo;
- gatilho em `consumo_tokens` e função `sistemaia_processar_consumo` **[WEAVER]**: markup, cotação do dólar e débito no saldo do escritório.

As definições dessas peças não foram lidas para esta spec. Não há preço, markup nem cotação no JSON do fluxo.

Para comparação, o sistema novo já tem a tabela em código (`app/modelo.py`, `PRECOS_USD_POR_MILHAO`, dólar por milhão de tokens: entrada / saída / entrada em cache):

| Modelo | Entrada | Saída | Cache |
|---|---|---|---|
| claude-fable-5-2 | 8,00 | 40,00 | 0,20 |
| claude-opus-5-5 | 4,00 | 20,00 | 0,20 |
| claude-sonnet-5-5 | 2,00 | 10,00 | 0,10 |
| claude-haiku-5-5 | 0,10 | 0,50 | 0,01 |
| gpt-4.1 | 2,00 | 8,00 | 0,50 |
| gpt-4.1-mini | 0,40 | 1,60 | 0,10 |

Modelo fora da tabela conta custo zero. Nome com data da OpenAI (`gpt-4.1-2025-04-14`) usa o preço do modelo-base. Os valores da OpenAI estão marcados no código como "de referência; conferir".

---

## 5. Onde grava e formato

### 5.1 Gravação de consumo (nós `INSERE NOVA MENSAGEM (s) ->` e `INSERE NOVA MENSAGEM (s) ->1`, mesma consulta)

Uma consulta por item (execução × modelo), em duas partes:

1. `insert into sistemaia_execucoes_cobradas (execution_id, modelo, numero_agente) ... on conflict (execution_id, modelo) do nothing returning execution_id` **[WEAVER]**. Serve de trava contra contar duas vezes a mesma execução e modelo.
2. Se a linha acima foi nova, `insert into consumo_tokens` **[WEAVER]** com o agente achado em `agentes` **[WEAVER]** por `numero_ia = numero_agente`:

| Coluna de `consumo_tokens` | Valor |
|---|---|
| `id_cliente` | `agentes.id_cliente` (o escritório) |
| `id_agente` | `agentes.id` |
| `categoria` | `'mensagem'` (fixo) |
| `modelo_nome` | modelo |
| `tokens_input` | soma de entrada |
| `tokens_output` | soma de saída |
| `total_tokens` | entrada + saída |
| `numero_origem` | número do lead |
| `started_at` | `now()` (hora da contagem, não da execução) |
| `metadata` | `{"n8n_execution_id": ..., "modelo": ...}` |

Problemas da gravação:
- **Consumo perdido sem aviso.** A primeira parte (CTE com `insert`) roda sempre. Se o agente não for achado pelo número (número vazio, formato diferente, agente apagado), a execução fica marcada como cobrada e nada entra em `consumo_tokens`. Ela nunca mais é tentada.
- **SQL montado por texto.** Os valores entram na consulta por interpolação (`'{{ $json.modelo }}'`), sem parâmetros. Aspas no conteúdo quebram a consulta, e número vazio vira texto vazio ou `null` em texto.
- `started_at` é a hora da contagem. Uma execução que passou pela fila fica registrada até uma hora depois.

### 5.2 Outros lugares

| Onde | O quê | Camada |
|---|---|---|
| `sistemaia_execucoes_nao_cobradas` (via `consumo_tokens`) | Nó `EXECUCAO COM PROBLEMA NÃO CONTABILIZADA - CUSTOS`, mesma consulta com outra tabela de trava. **Desativado e sem ligação** | **[WEAVER]** |
| Data table `Contar Token` (`Dados` texto JSON, `Feito` booleano) | Fila de execuções não terminadas | **[N8N]** |
| Redis, chave = ID da execução | Contador de tentativas com expiração | **[N8N]** |

---

## 6. Relatórios e limites

- **No fluxo:** nenhum relatório de custo e nenhum limite. O único relatório é o de execuções demoradas (3.3), que é operacional.
- **No Weaver (fora do fluxo, pelo levantamento em `MAPA_DO_SISTEMA.md` seção 4):** saldo do escritório com corte (`sistemaia_saldos.pausado_por_saldo`) e limites `limite_diario_brl` e `limite_mensal_brl` **[WEAVER]**, todos em reais e alimentados pelo gatilho de `consumo_tokens`. Não foram lidos para esta spec.
- **No desenho do sistema novo:** `DESENHO.md` 8.1 pede trava de "limite diário de custo do escritório" com resposta fixa e aviso; 14.4 pede visões por turno, lead, etapa, escritório e mês, custo por contrato e conferência mensal com o fornecedor (aviso acima de 5% de diferença).

---

## 7. Tratamento de erro

| Situação | O que o fluxo faz |
|---|---|
| Execução de teste no editor | Não conta (`NÃO COBRA`) |
| Execução ainda rodando | Espera e tenta; na 4ª vez vai para a fila (com o defeito de 3.1) |
| Execução sumiu ou API do n8n falhou (cron) | Segue em frente e deixa a linha na fila para sempre (3.2) |
| Execução sem tokens | Nada é gravado; no cron, a linha não é marcada e o loop pode parar (3.2) |
| Agente não achado pelo número | Marca como cobrada e perde o consumo (5.1) |
| Mesma execução contada duas vezes | Bloqueado por `unique (execution_id, modelo)` em `sistemaia_execucoes_cobradas` |
| Erro no Postgres | Sem tratamento: a execução do subfluxo falha. No cron, a linha fica na fila |
| Aviso à equipe | Nenhum. O nó `EXECUÇÃO NÃO COBRADA` (stopAndError, "A execução de ID ... não foi cobrada") existe mas não está ligado |

---

## 8. Como fica no sistema novo

### 8.1 O que já existe

| Peça | Onde | O que faz |
|---|---|---|
| Medição na origem | `app/modelo.py`, `Chamada` e `gerar(...)` | Cada chamada à Anthropic ou à OpenAI devolve `usage`. O código grava modelo real, tokens de entrada, saída e cache lido, duração, sucesso e erro. Substitui todo o "esperar a execução terminar e varrer o runData" |
| Cálculo de custo | `app/modelo.py`, `calcular_custo` e `PRECOS_USD_POR_MILHAO` | Custo em dólar na hora da chamada |
| Chamadas que falharam | `app/modelo.py` (anexa `chamadas` ao `ErroModelo`) e `app/cerebro/turno.py` | Tentativas que deram erro também são gravadas |
| Gravação | `app/banco/postgres.py`, `gravar_chamadas`, chamado em `app/pipeline.py` depois de `cerebro.processar` | Uma linha por chamada em `agentesia_chamadas_ia` |
| Tabela | `db/migracoes/001_agentesia_nucleo.sql`, `agentesia_chamadas_ia` | `id_escritorio`, `id_turno`, `papel` (extrator, etapa...), `modelo`, `tokens_entrada`, `tokens_saida`, `custo_usd numeric(12,6)`, `duracao_ms`, `sucesso`, `erro`, `criado_em` |
| Painel | `app/gestao/rotas.py` `GET /inicio` → `RepositorioGestao.resumo` (`app/gestao/repositorio.py`) | `custo_24h_usd` = soma de `custo_usd` do escritório nas últimas 24 h |

Escritório e lead são ligados por ID (`id_escritorio`, `id_turno` → `agentesia_turnos.id_lead`), não por número de WhatsApp. A trava contra contagem dupla deixa de ser necessária: cada chamada grava uma única vez.

### 8.2 O que falta

1. **Dados que se perdem na gravação.**
   - `gravar_chamadas` grava `tokens_entrada + tokens_cache` numa coluna só. O custo fica certo, mas não dá para auditar quanto veio do cache.
   - Na Anthropic, `cache_creation_input_tokens` (escrita no cache, mais cara que a entrada normal) não é lido nem cobrado. O custo fica subestimado sempre que o prompt é gravado no cache.
   - `agentesia_chamadas_ia` não tem `id_lead`, `id_agente` nem `modo`. Relatório por lead e por agente precisa de junção com `agentesia_turnos`, `agentesia_leads` e `agentesia_agentes`, e o agente pode mudar de canal depois.
2. **Teste misturado com produção.** O sistema antigo não contava execução de teste. Hoje `/inicio` soma tudo, inclusive turnos com `modo = 'teste'`. O laboratório (`app/gestao/laboratorio.py`) usa `RepositorioMemoria` e **não grava** as chamadas em lugar nenhum, embora gaste a API de verdade.
3. **Preço com vigência.** O preço está em constante no código. Trocar o valor muda o custo das próximas chamadas, mas não há registro de qual preço valia em cada dia, e modelo fora da tabela vira custo zero sem aviso.
4. **Consolidação diária por escritório.** Não existe. `/inicio` soma a tabela crua a cada abertura do painel.
5. **Relatório.** Não existe rota de custos por período, agente, lead, modelo ou papel.
6. **Limite e cota.** Não existe trava de gasto. `_por_que_nao_atende` (`app/pipeline.py`) confere IA desligada, canal, agente pausado e estado do lead, mas não custo.
7. **Aviso de estouro.** Não existe. Pode usar `agentesia_eventos`, que já tem `tipo`, `gravidade` e `responsavel`.
8. **Moeda.** O sistema novo grava em dólar. O Weaver cobrava em reais, com markup e cotação. Falta decidir se a cota é em dólar (custo real) ou em reais (preço ao escritório) e de onde vem a cotação.
9. **Outros custos de IA** (transcrição por minuto, embeddings), previstos em `DESENHO.md` 14.4, ainda não passam pela camada de modelo.

### 8.3 Tabelas propostas (migração `003_agentesia_custos.sql`)

```sql
-- 1) Completar a tabela de chamadas.
alter table public.agentesia_chamadas_ia
  add column id_lead              uuid references public.agentesia_leads(id)   on delete set null,
  add column id_agente            uuid references public.agentesia_agentes(id) on delete set null,
  add column modo                 text check (modo in ('producao', 'teste', 'laboratorio')),
  add column fornecedor           text,                 -- anthropic, openai
  add column tokens_cache         int not null default 0,   -- lidos do cache (tokens_entrada passa a ser só o preço cheio)
  add column tokens_cache_escrita int not null default 0;   -- gravados no cache (Anthropic)
create index agentesia_chamadas_ia_escritorio_data on public.agentesia_chamadas_ia (id_escritorio, criado_em);

-- 2) Preço por modelo com vigência (substitui a constante em app/modelo.py; a constante vira só a carga inicial).
create table public.agentesia_precos_modelos (
  modelo              text not null,
  vigente_desde       date not null,
  entrada_usd_mtok    numeric(10,4) not null,
  saida_usd_mtok      numeric(10,4) not null,
  cache_leitura_usd_mtok numeric(10,4) not null default 0,
  cache_escrita_usd_mtok numeric(10,4) not null default 0,
  primary key (modelo, vigente_desde)
);

-- 3) Consolidação diária (dia no fuso do escritório).
create table public.agentesia_consumo_diario (
  dia                 date not null,
  id_escritorio       uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_agente           uuid references public.agentesia_agentes(id) on delete set null,
  modelo              text not null,
  modo                text not null,
  chamadas            int not null default 0,
  chamadas_com_erro   int not null default 0,
  leads_distintos     int not null default 0,
  tokens_entrada      bigint not null default 0,
  tokens_cache        bigint not null default 0,
  tokens_cache_escrita bigint not null default 0,
  tokens_saida        bigint not null default 0,
  custo_usd           numeric(14,6) not null default 0,
  atualizado_em       timestamptz not null default now(),
  unique nulls not distinct (dia, id_escritorio, id_agente, modelo, modo)
);

-- 4) Cota por escritório.
create table public.agentesia_cotas_custo (
  id_escritorio       uuid primary key references public.agentesia_escritorios(id) on delete cascade,
  limite_diario_usd   numeric(12,2),            -- null = sem limite
  limite_mensal_usd   numeric(12,2),
  percentual_aviso    int not null default 80 check (percentual_aviso between 1 and 100),
  ao_estourar         text not null default 'avisar' check (ao_estourar in ('avisar', 'pausar_ia')),
  atualizado_por      uuid references public.agentesia_usuarios(id) on delete set null,
  atualizado_em       timestamptz not null default now()
);
```

Avisos usam `agentesia_eventos`, sem tabela nova: `tipo = 'cota_perto'` (gravidade `aviso`) e `'cota_estourada'` (gravidade `erro`), `responsavel = 'cliente'`, `detalhe = {"periodo": "dia"|"mes", "referencia": "2026-11-22", "gasto_usd": ..., "limite_usd": ...}`. Um evento por escritório, tipo, período e referência.

### 8.4 Funções Python propostas

Módulo novo `app/custos.py` (leitura e regras) e ajustes pequenos nos existentes.

```python
# app/modelo.py: passar a ler a escrita no cache da Anthropic
#   chamada.tokens_cache_escrita = getattr(uso, "cache_creation_input_tokens", 0) or 0
def calcular_custo(modelo: str, entrada: int, saida: int, cache: int,
                   cache_escrita: int = 0, *, preco: "Preco | None" = None) -> float: ...

# app/custos.py
@dataclass(frozen=True)
class Preco:
    modelo: str
    vigente_desde: date
    entrada: float; saida: float; cache_leitura: float; cache_escrita: float   # USD por milhão

@dataclass
class SituacaoCota:
    id_escritorio: str
    gasto_dia_usd: float
    gasto_mes_usd: float
    limite_dia_usd: float | None
    limite_mes_usd: float | None
    percentual_aviso: int
    ao_estourar: Literal["avisar", "pausar_ia"]

    @property
    def estourou(self) -> bool: ...
    @property
    def perto(self) -> bool: ...

async def carregar_precos(pool: asyncpg.Pool) -> dict[str, list[Preco]]:
    """Lê agentesia_precos_modelos; cache em memória, recarregado a cada N minutos."""

def preco_vigente(precos: dict[str, list[Preco]], modelo: str, quando: date) -> Preco | None:
    """Casa também o nome com data da OpenAI com o modelo-base. None → custo zero + evento 'modelo_sem_preco'."""

async def gasto_no_periodo(pool: asyncpg.Pool, id_escritorio: str, inicio: datetime, fim: datetime,
                           *, modos: tuple[str, ...] = ("producao",)) -> float:
    """Soma custo_usd de agentesia_chamadas_ia; dias fechados podem vir de agentesia_consumo_diario."""

async def situacao_da_cota(pool: asyncpg.Pool, id_escritorio: str,
                           agora: datetime | None = None) -> SituacaoCota:
    """Gasto do dia e do mês no fuso do escritório contra agentesia_cotas_custo."""

async def avisar_se_preciso(repo: "Repositorio", situacao: SituacaoCota) -> None:
    """Grava 'cota_perto' ou 'cota_estourada' em agentesia_eventos uma vez por período."""

async def consolidar_dia(pool: asyncpg.Pool, dia: date, id_escritorio: str | None = None) -> int:
    """Recalcula agentesia_consumo_diario do dia (delete + insert ... select, ou upsert). Idempotente.
    Devolve o número de linhas gravadas."""

async def relatorio_custos(pool: asyncpg.Pool, id_escritorio: str, inicio: date, fim: date,
                           agrupar_por: Literal["dia", "agente", "lead", "modelo", "papel"] = "dia",
                           modos: tuple[str, ...] = ("producao",)) -> list[dict[str, Any]]: ...

async def rodar_consolidacao(pool: asyncpg.Pool, fuso: str = "America/Sao_Paulo") -> None:
    """Tarefa de fundo: todo dia às 00:15 consolida ontem e anteontem (cobre chamadas que fecharam tarde)."""
```

Ajustes nos módulos que já existem:

| Onde | Mudança |
|---|---|
| `app/banco/postgres.py` `gravar_chamadas` | Nova assinatura `gravar_chamadas(*, id_escritorio, id_turno, id_lead, id_agente, modo, chamadas)`. Grava `tokens_entrada`, `tokens_cache` e `tokens_cache_escrita` separados, mais `fornecedor` e `modo`. Mesma mudança em `app/banco/tipos.py` e `app/banco/memoria.py` |
| `app/pipeline.py` `_um_turno` | Passa `lead.id`, `agente.id` e `modo` para `gravar_chamadas`. Antes de montar a entrada, chama `situacao_da_cota`. Se `estourou` e `ao_estourar == 'pausar_ia'`, fecha o turno como `silencio` com motivo `cota_estourada` (o mesmo caminho de `_por_que_nao_atende`). Depois de gravar as chamadas, chama `avisar_se_preciso` |
| `app/gestao/laboratorio.py` | Decidir: gravar as chamadas do laboratório com `modo = 'laboratorio'` em `agentesia_chamadas_ia` (gasto real da LawChat), fora dos relatórios do escritório |
| `app/gestao/repositorio.py` `resumo` | `custo_24h_usd` só com `modo = 'producao'`; acrescentar `custo_mes_usd` e a situação da cota |
| `app/gestao/rotas.py` | `GET /custos?inicio=&fim=&agrupar_por=` (gestor do escritório; admin pode ver todos) e `PUT /escritorios/{id}/cota` (só admin) |
| `app/main.py` `_ciclo` | Inicia `rodar_consolidacao` como tarefa de fundo, como já é feito com o executor de ações |

### 8.5 O que descartar

Tudo isto existia só porque o n8n não entrega o consumo na hora e guarda execuções:

- Subfluxo chamado no fim de cada execução, esperas de 2 s, contador de tentativas no Redis, `IF` de "execução terminou".
- Consulta à API do n8n (`Get an execution`, `Get many executions`) e a varredura do `runData` (`tokenUsage`, `tokenUsageEstimate`, `inputOverride`, `executionIndex`, `customData`).
- Data table `Contar Token` e o cron `:17` que a reprocessa.
- Identificar agente e lead pelo número de WhatsApp.
- Trava de contagem dupla (`sistemaia_execucoes_cobradas`, `sistemaia_execucoes_nao_cobradas`) e a separação por `executionMode == 'test'` (vira a coluna `modo`).
- Limpeza de execuções (apagar todas, apagar as com erro) e o relatório de execuções acima de 3 min. Se quiser medir lentidão, use `agentesia_turnos.iniciado_em` e `concluido_em` e `agentesia_chamadas_ia.duracao_ms`.
- Webhook `contar-tokens`, `Get an execution1` com ID fixo, `EXECUÇÃO NÃO COBRADA` e o nó desativado de "não contabilizada": nenhum está em uso.
- Gravação em `consumo_tokens`, `agentes` e o gatilho de cobrança **[WEAVER]**: o sistema novo não usa as tabelas do Weaver. Se a cobrança em reais com saldo continuar, ela precisa ser refeita sobre `agentesia_consumo_diario`; isso fica fora desta spec.
