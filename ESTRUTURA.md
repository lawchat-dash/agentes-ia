# Estrutura: banco real, tabelas novas, código e painel de teste

Versão 2, 13/11/2026. Substitui o rascunho anterior, que tinha as tabelas inferidas dos fluxos. Esta versão parte da **leitura somente da estrutura** do banco do projeto Supabase "AGENT WEAVER" (o banco "Organização" dos fluxos 99) e dos 13 fluxos da geração 99. Nenhum dado de lead, contato ou mensagem foi lido.

Complementa o [DESENHO.md](DESENHO.md).

> **Substituído em 22/11/2026.** O sistema em código é novo, do zero, e não usa nem altera as tabelas do Weaver. As tabelas `cerebro_*` e os `alter table` da seção 3, o reaproveitamento da seção 1.3 e o roteamento n8n/cérebro não valem mais. A estrutura em vigor está em [db/TABELAS.md](db/TABELAS.md) e em `db/migracoes/`. Este arquivo fica como registro da leitura do banco antigo.

## 1. O que o banco mostrou

### 1.1 Duas camadas

O banco tem 81 tabelas e 22 views, em duas camadas:

| Camada | Tabelas | Papel |
|---|---|---|
| **Plataforma (app)** | `sistemaia_*` | Catálogo de produtos, contas dos escritórios, produtos ativados, mídias, notificações, templates de WhatsApp oficial, contratos, cobrança e saldo |
| **Bot (execução)** | `clientes`, `conexoes`, `agentes`, `agente_etapas`, `prompts`, `lead`, `contatos`, `conversas_agentes`, `mensagens`, `memoria`, `card`, `tags`, `followups`... | O que os fluxos 99 leem e gravam a cada mensagem |

A ponte entre as duas são funções no banco (`sistemaia_ativar_produto_no_bot`, `sistemaia_sincronizar_produto_no_bot`, `sistemaia_atualizar_prompts_no_bot`), que **compilam** a configuração da plataforma em agentes, etapas e prompts do bot.

### 1.2 Hierarquia

```
sistemaia_biblioteca_produtos        produto-modelo (19: Auxílio Acidente · Mídia, BPC/LOAS Autismo, BPC Idoso...)
 ├── sistemaia_biblioteca_agentes    papéis do produto: sdr, periododegraca, closer, contratos, assinatura, desqualificado
 ├── sistemaia_frases_troca          frase que dispara cada troca de etapa
 ├── sistemaia_biblioteca_followups  modelos de lembrete
 └── sistemaia_biblioteca_conhecimento

sistemaia_contas (escritório)  ──  clientes (mesmo escritório no bot)
 └── sistemaia_produtos_ativados     produto do catálogo ativado e personalizado por escritório (24)
       │  regras, FAQ, objeções, dados do escritório, período de graça ligado
       │  ── compilado por função ──▶
       ├── produto (bot)
       └── agentes (12, um por produto ativado; ex.: "Júlia - Auxílio Acidente")
             ├── conexoes            número de WhatsApp
             ├── agente_etapas       sdr, periododegraca, closer, contratos, assinatura, desqualificado
             │     │                 + terminais: contratoassinado, iadesativada
             │     └── prompts       prompt, objeções, FAQ, dados do escritório, regras gerais, modelo, temperatura, frase de troca
             ├── followup_cadences   5 passos por agente  ── prompts_followup por passo e etapa
             └── sistemaia_conhecimento_vetores   base de conhecimento por agente

lead ── contato, conexão, agente, etapa atual (agente_etapas)
 ├── conversas_agentes ── mensagens
 ├── card ── tags (CRM na Helena)
 ├── followups ── followup_queue ── followup_events
 └── memoria (histórico no formato do n8n)
```

### 1.3 O que já existe e o sistema novo reaproveita

| Necessidade do desenho | Já existe | Decisão |
|---|---|---|
| Produto como configuração | `sistemaia_biblioteca_produtos` + `sistemaia_produtos_ativados` | **Fonte da configuração**; acrescentar só a parte estruturada (seção 3) |
| Custo por chamada | `consumo_tokens` (com gatilho e cobrança por `sistemaia_processar_consumo`) e `sistemaia_precos_modelos` | **Gravar direto em `consumo_tokens`**, para a cobrança continuar funcionando. Sai a tabela `chamadas_ia` do rascunho |
| Lembretes | `followup_cadences`, `followups`, `followup_queue`, `followup_events`, `prompts_followup`, função `advance_followup` | **Reaproveitar**. Sai a tabela `lembretes` do rascunho |
| Avisos à equipe | `sistemaia_notificacoes` + `sistemaia_notificacao_destinatarios` | Reaproveitar |
| Catálogo de mídias | `sistemaia_biblioteca_midia` (já tem transcrição) | Reaproveitar como catálogo da seção 7.1 do desenho |
| Base de conhecimento | `sistemaia_conhecimento_vetores` + `sistemaia_match_conhecimento` | Reaproveitar na busca prévia |
| Canal oficial ou não | `sistemaia_numeros_whatsapp.tipo` (`CLOUDAPI_WHATSAPP`) e `sistemaia_templates_whatsapp` | Reaproveitar na regra das 24 horas |
| Contrato | `sistemaia_produto_contratos`, `api_key_atributos` | Reaproveitar |
| Honorários | `sistemaia_contas.honorarios` | Fonte da trava de honorários |
| Etapa inicial e sincronização | Gatilhos `lead_set_etapa_inicial`, `lead_sync_etapa_atual`, `notifica_reativacao` | Continuam valendo; o sistema novo grava `id_etapa_atual` e os gatilhos fazem o resto |

Tabelas criadas pelos fluxos n8n refeitos em novembro (pasta `Fluxos N8N`). Valem só depois que o SQL de cada pasta rodar no AGENT WEAVER:

| Necessidade do desenho | Tabela do n8n refeito | Decisão |
|---|---|---|
| Problemas do atendimento | `atendimento_evento` (situação, responsável: cliente, cadastro, provedor, lead ou LawChat) | **Reaproveitar** acrescentando `id_turno` e `codigo_padrao`. Sai a tabela `cerebro_eventos` do rascunho |
| Resumo da conversa | `lead_memoria_resumo` (ficha por lead, refeita a cada 20 mensagens) | Reaproveitar como resumo que o agente da etapa recebe |
| Histórico de etapa | `lead_etapa_historico` + colunas `etapa_trocada_em` e `etapa_trocada_msg` em `lead` | Reaproveitar; o código grava uma linha a cada transição |
| Contrato | `contrato_documento` (versão, `dados_hash`, reserva, link), `contrato_evento`, `contrato_resumo_config`, `contrato_resumo` | **Reaproveitar** como está: o n8n e o código passam a usar a mesma ficha de contrato |

### 1.4 Achados que importam para a qualidade

| Achado | Por que importa |
|---|---|
| **Temperatura 2 no agente 1 e 1,5 no agente 2**, contra 0,4 a 0,7 nos demais | Temperatura 2 é o máximo da OpenAI e torna as respostas muito aleatórias. Forte candidato a causa de alucinação nesses dois agentes. Vale baixar já, no n8n |
| `tamanho_historico = 10` na configuração dos agentes, mas o fluxo 99 lê 100 mensagens da memória | A configuração não está sendo respeitada |
| Troca de etapa por frase (`sistemaia_frases_troca`) | É a fonte do problema de troca de etapa por texto; no sistema novo a troca vira decisão do código e essa tabela deixa de ser usada |
| Regras gerais com o mesmo texto (2.942 caracteres) em todos os produtos | Uma regra só, repetida; no sistema novo vira configuração compartilhada |
| Prompts do BPC Idoso entre 10 e 22 mil caracteres por papel | Candidatos prioritários para a desmontagem da seção 9.1 do desenho |
| Agente com nome de advogado real | Confirma o ponto de identidade das auditorias |
| Tabelas sem RLS (`memoria`, `followup_queue`, `consumo_tokens`, `tags`...) | Conferido: nenhuma delas é legível pelos papéis `anon` e `authenticated`. Sem exposição pela API pública |
| `cliente_integracoes.valor`, `api_key.chave`, `clientes.api_lawchat` guardam credenciais | Não li os valores. Vale confirmar se estão criptografados |

## 2. Princípios da migração do banco

1. **Mesmo banco, só acréscimos.** Nada é apagado nem renomeado enquanto o n8n estiver ativo.
2. **Tabelas novas com prefixo `cerebro_`**, para separar visualmente do que o n8n usa.
3. **Migrações numeradas** no repositório (`db/migracoes/001_...sql`), aplicadas em ordem.
4. **Banco de desenvolvimento separado.** Uma cópia só da estrutura (branch do Supabase ou projeto novo), com dados fictícios. Nenhum teste roda no banco de produção.
5. **Esquema atual versionado.** Um script gera `db/esquema_atual.sql` a partir do banco, para o repositório sempre ter a foto da estrutura.

## 3. Tabelas novas

```sql
-- 001_cerebro_base.sql (rascunho)

-- Parte estruturada da configuração do produto (complementa a biblioteca).
create table cerebro_config_produto (
  id                    uuid primary key default gen_random_uuid(),
  id_produto_biblioteca uuid not null references sistemaia_biblioteca_produtos(id),
  versao                int  not null,
  conteudo              jsonb not null,   -- fatos, regras de qualificação, etapas, passos do closer,
                                          -- instruções curtas por etapa, travas, mensagens fixas
  publicado_em          timestamptz,
  publicado_por         text,
  ativa                 boolean not null default false,
  unique (id_produto_biblioteca, versao)
);

-- Ajustes por escritório sobre a configuração do produto.
create table cerebro_config_ativado (
  id                    uuid primary key default gen_random_uuid(),
  id_produto_ativado    uuid not null references sistemaia_produtos_ativados(id),
  versao                int  not null,
  ajustes               jsonb not null,   -- persona, honorários, horários, números de teste, travas extras
  publicado_em          timestamptz,
  ativa                 boolean not null default false,
  unique (id_produto_ativado, versao)
);

-- Quem atende cada agente: o n8n ou o cérebro. É a chave da virada por número.
create table cerebro_roteamento (
  id_agente             bigint primary key references agentes(id),
  sistema               text not null default 'n8n',   -- n8n, cerebro, sombra
  alterado_em           timestamptz not null default now(),
  alterado_por          text
);

-- Eventos recebidos, crus. Deduplicação e reprodução.
create table cerebro_eventos_recebidos (
  id             uuid primary key default gen_random_uuid(),
  id_cliente     uuid references clientes(id_ulid),
  origem         text not null,          -- helena, zapsign, painel
  id_externo     text,
  tipo           text,
  payload        jsonb not null,
  recebido_em    timestamptz not null default now(),
  processado_em  timestamptz,
  situacao       text not null default 'pendente',
  unique (origem, id_externo)
);

-- Um turno = um lote de mensagens do lead.
create table cerebro_turnos (
  id              uuid primary key default gen_random_uuid(),
  id_cliente      uuid not null references clientes(id_ulid),
  id_lead         uuid not null references lead(ulid),
  id_conversa     bigint references conversas_agentes(id),
  mensagens_lote  bigint[] not null,
  etapa_antes     text,
  etapa_depois    text,
  contexto        jsonb,                  -- o que foi enviado ao modelo (para o painel de teste e auditoria)
  resposta        jsonb,
  versao_config   jsonb not null,         -- {produto: n, ativado: n}
  modo            text not null,          -- producao, sombra, laboratorio
  situacao        text not null,          -- ok, descartado_reprocesso, erro, silencio
  motivo          text,
  iniciado_em     timestamptz not null default now(),
  concluido_em    timestamptz
);

-- Fatos do lead, com prova.
create table cerebro_lead_fatos (
  id              uuid primary key default gen_random_uuid(),
  id_cliente      uuid not null references clientes(id_ulid),
  id_lead         uuid not null references lead(ulid) on delete cascade,
  produto         text not null,
  chave           text not null,
  valor           jsonb not null,
  trecho          text,
  id_mensagem     bigint references mensagens(id),
  fonte           text not null,          -- extrator, equipe, sistema
  id_turno        uuid references cerebro_turnos(id),
  criado_em       timestamptz not null default now(),
  substituido_em  timestamptz
);
create index on cerebro_lead_fatos (id_lead) where substituido_em is null;

-- Decisões das funções.
create table cerebro_lead_decisoes (
  id             uuid primary key default gen_random_uuid(),
  id_cliente     uuid not null references clientes(id_ulid),
  id_lead        uuid not null references lead(ulid) on delete cascade,
  id_turno       uuid references cerebro_turnos(id),
  funcao         text not null,
  entrada        jsonb not null,
  resultado      jsonb not null,
  criado_em      timestamptz not null default now()
);

-- Ações para as integrações, com novas tentativas.
create table cerebro_acoes (
  id           uuid primary key default gen_random_uuid(),
  id_cliente   uuid not null references clientes(id_ulid),
  id_lead      uuid references lead(ulid),
  id_turno     uuid references cerebro_turnos(id),
  tipo         text not null,
  dados        jsonb not null,
  situacao     text not null default 'pendente',
  tentativas   int not null default 0,
  proxima_em   timestamptz not null default now(),
  resultado    jsonb,
  criado_em    timestamptz not null default now()
);

-- Travas, avisos, transferências, erros: grava na tabela atendimento_evento,
-- criada pelo Fluxo Principal refeito (migracao_fluxo_principal.sql).
-- Esta migração só acrescenta o que o cérebro precisa.
alter table atendimento_evento
  add column if not exists id_turno      uuid references cerebro_turnos(id),
  add column if not exists codigo_padrao text;   -- P01..P26

-- Classificação de anúncios reaproveitada.
create table cerebro_cache_anuncios (
  id_anuncio   text primary key,
  resultado    jsonb not null,
  criado_em    timestamptz not null default now()
);

-- Colunas novas em tabelas existentes (só acréscimo).
alter table mensagens add column if not exists autor text;           -- lead, ia, humano, automacao, outra_integracao
alter table mensagens add column if not exists posicao timestamptz;  -- horário da mensagem no WhatsApp
alter table mensagens add column if not exists texto_extraido text;  -- transcrição ou descrição
alter table mensagens add column if not exists id_turno uuid;
alter table lead add column if not exists produto text;
alter table lead add column if not exists estado text;                -- ativo, encerrado, pausado...
alter table lead add column if not exists motivo_estado text;
```

As chamadas de IA vão para `consumo_tokens`, com `categoria` indicando o agente (extrator, etapa_sdr, auditor...) e o `id_turno` em `metadata`.

## 4. Como o código lê as tabelas

| Momento | Lê | Grava |
|---|---|---|
| Webhook chega | `cerebro_roteamento` (quem atende este agente), `conexoes`, `clientes` | `cerebro_eventos_recebidos` |
| Identificar o lead | `contatos`, `lead`, `conversas_agentes` | `contatos`, `lead`, `conversas_agentes`, `mensagens` |
| Montar a configuração | `sistemaia_produtos_ativados` → `sistemaia_biblioteca_produtos` → `cerebro_config_produto` + `cerebro_config_ativado`; `sistemaia_contas.honorarios`; `sistemaia_biblioteca_midia` | — |
| Montar o contexto | `cerebro_lead_fatos`, últimas `mensagens`, `sistemaia_conhecimento_vetores` | — |
| Depois de cada chamada de IA | — | `consumo_tokens` |
| Depois das funções | — | `cerebro_lead_fatos`, `cerebro_lead_decisoes`, `lead.id_etapa_atual` (os gatilhos sincronizam o nome da etapa) |
| Fim do turno | — | `cerebro_turnos`, `atendimento_evento`, `cerebro_acoes`, `mensagens` |
| Lembretes | `followup_cadences`, `prompts_followup` | `followups`, `followup_queue`, `followup_events` |

A configuração montada é validada por um esquema Python. Se faltar algo obrigatório, o agente não atende e um aviso é gerado: nunca roda com configuração pela metade.

## 5. Painel de teste ("Laboratório")

Uma tela interna para ver por dentro cada turno, antes de qualquer lead real.

### 5.1 O que mostra

```
┌───────────────────────────────┬──────────────────────────────────────────┐
│ Conversa                      │ Por dentro do turno                      │
│                               │                                          │
│  Escritório: [Júlia ▾]        │  1. Contexto enviado ao modelo           │
│  Produto: Auxílio Acidente    │     instrução da etapa · fatos · o que   │
│  Etapa atual: sdr             │     falta · trechos da base · histórico  │
│                               │                                          │
│  Lead: "sofri acidente de     │  2. Extrator                             │
│  moto em 2021, era fichado"   │     JSON devolvido + trechos conferidos  │
│                               │                                          │
│  IA: "Que situação difícil... │  3. Fatos no banco (antes → depois)      │
│  você ficou com alguma        │     vinculo_na_data: — → clt  ✓ trecho   │
│  limitação?"                  │                                          │
│                               │  4. Decisões                             │
│ [digitar como lead]           │     decidir_qualificacao → faltam_dados  │
│ [lead simulado: persona ▾]    │     [sequela]                            │
│                               │                                          │
│ [salvar como cenário · P08 ▾] │  5. Travas · 6. Ações (não executadas)   │
│                               │  7. Modelo, tokens, custo, tempo         │
└───────────────────────────────┴──────────────────────────────────────────┘
```

- **Ver o prompt de verdade**: o contexto exato enviado ao modelo, parte por parte, com a versão da configuração.
- **Ver se refletiu nas tabelas**: os fatos e decisões gravados, com o antes e o depois.
- **Ver o que seria feito**: ações listadas sem executar (troca de etapa, aviso, contrato).
- **Trocar a configuração e repetir**: editar a instrução de uma etapa num rascunho e rodar o mesmo turno de novo, lado a lado.
- **Lead simulado**: escolher uma persona dos cenários e deixar a conversa correr sozinha.
- **Salvar como cenário**: transformar a conversa em teste, com o código do catálogo de auditoria.
- **Reproduzir um turno real** (depois do modo sombra): abrir um turno gravado e ver o que o cérebro faria.

### 5.2 Como é construído

- O mesmo serviço Python que atende os leads expõe as rotas do laboratório (FastAPI).
- A tela é uma página web simples servida pelo próprio serviço, sem sistema separado para manter.
- O laboratório roda com `modo = laboratorio`: usa o banco de desenvolvimento, não envia nada pela Helena e marca os turnos para não entrarem em relatórios nem na cobrança.
- Acesso só para a equipe, com login.

## 6. Como eu começaria

| Passo | O que | Entrega |
|---|---|---|
| 0 | Segurança e base: revogar o token usado nesta leitura, repositório git, arquivo de variáveis de ambiente, banco de desenvolvimento com a estrutura copiada | Ambiente pronto, nada tocando a produção |
| 1 | Esquema: script que gera `db/esquema_atual.sql`; migração `001_cerebro_base.sql`; dados fictícios de um escritório, produto e agente | Banco de desenvolvimento com as tabelas novas |
| 2 | Configuração: leitura da hierarquia (produto ativado → biblioteca → config do cérebro), esquema de validação, configuração de Auxílio Acidente · Mídia desmontada a partir dos prompts atuais | Configuração validada de um produto |
| 3 | Núcleo: funções de decisão, validadores, formatador, travas, com os testes das auditorias | Regras testadas, sem IA |
| 4 | IA: camada de modelo gravando em `consumo_tokens`, extrator, agente da etapa, busca prévia | Turno completo rodando por código |
| 5 | Laboratório | Tela para conversar e ver tudo por dentro |
| 6 | Canal, integrações e modo sombra num agente | Comparação com o n8n em conversas reais |

Os passos 0 a 5 não tocam o banco de produção nem enviam mensagem a ninguém.

## 7. Pendências

| # | Pendência | Para quê |
|---|---|---|
| E1 | Revogar o token de acesso usado na leitura (ele foi colado na conversa) | Segurança |
| E2 | Criar o banco de desenvolvimento (branch do Supabase ou projeto novo) | Passos 1 a 5 |
| E3 | Documentação ou exemplos da API da Helena | Passo 6 |
| E4 | Confirmar como as credenciais em `api_key`, `cliente_integracoes` e `clientes.api_lawchat` estão guardadas | Segurança antes do passo 6 |
| E5 | Onde o serviço vai rodar | Passo 6 |
| E6 | Validação das regras de qualificação por advogado | Antes de atender leads reais |
