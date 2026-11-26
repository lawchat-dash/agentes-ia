-- =============================================================================
-- 001_agentesia_nucleo.sql
-- Núcleo do sistema de IA em código (LawChat): só o que a IA precisa para
-- receber a mensagem, entender, decidir, responder e registrar.
--
-- Sistema novo, do zero: não lê nem altera nenhuma tabela que já existe no
-- projeto. Follow-up, CRM, contrato, painel de gestão etc. entram em migrações
-- próprias, quando cada módulo for construído (rascunho em db/rascunhos/).
--
-- RLS ligado em tudo: só o backend (service_role) lê e grava.
-- Para desfazer: desfazer_001.sql.
-- =============================================================================

begin;

create or replace function public.agentesia_tocar_atualizado_em()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.atualizado_em := now();
  return new;
end
$$;

-- -----------------------------------------------------------------------------
-- CONFIGURAÇÃO: quem atende, por onde, com que instruções
-- -----------------------------------------------------------------------------

-- Escritório. config: horário comercial, números de teste, honorários...
create table public.agentesia_escritorios (
  id                  uuid primary key default gen_random_uuid(),
  nome                text not null,
  ia_desligada        boolean not null default false,     -- interruptor de emergência
  id_conta_helena     uuid unique,                        -- companyId da Helena
  id_segredo_helena   uuid,                               -- token da Helena no Supabase Vault
  fuso                text not null default 'America/Sao_Paulo',
  config              jsonb not null default '{}'::jsonb,
  criado_em           timestamptz not null default now(),
  atualizado_em       timestamptz not null default now()
);

-- Número de WhatsApp (canal da Helena).
create table public.agentesia_canais (
  id                   uuid primary key default gen_random_uuid(),
  id_escritorio        uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_canal_helena      text unique,
  numero_normalizado   text not null,                     -- só dígitos, com 55
  tipo                 text not null default 'nao_oficial' check (tipo in ('oficial', 'nao_oficial')),
  ativo                boolean not null default true,
  criado_em            timestamptz not null default now(),
  atualizado_em        timestamptz not null default now(),
  unique (id_escritorio, numero_normalizado)
);

-- A IA do escritório num canal. produto: código do produto (as regras ficam no código).
-- config: persona, honorários, mídias (vídeo inicial), modelo por papel.
create table public.agentesia_agentes (
  id                     uuid primary key default gen_random_uuid(),
  id_escritorio          uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_canal               uuid not null unique references public.agentesia_canais(id) on delete cascade,
  nome                   text not null,
  produto                text not null default 'auxilio_acidente',
  situacao               text not null default 'pausado' check (situacao in ('ativo', 'pausado')),
  modo                   text not null default 'teste'      -- teste: só responde aos números de teste
                         check (modo in ('teste', 'producao')),
  minutos_pausa_humano   int  not null default 15 check (minutos_pausa_humano between 0 and 10080),
  config                 jsonb not null default '{}'::jsonb,
  criado_em              timestamptz not null default now(),
  atualizado_em          timestamptz not null default now()
);

-- Etapas do agente com a instrução de cada uma.
create table public.agentesia_agente_etapas (
  id              uuid primary key default gen_random_uuid(),
  id_agente       uuid not null references public.agentesia_agentes(id) on delete cascade,
  codigo          text not null,                          -- sdr, periodo_graca, closer, coleta_dados...
  ordem           int  not null,
  tipo            text not null default 'conversa' check (tipo in ('conversa', 'terminal')),
  principal       boolean not null default false,         -- onde o lead novo entra
  instrucao       text,                                   -- prompt da etapa
  modelo          text,
  temperatura     numeric(3,2) not null default 0.4 check (temperatura between 0 and 1),
  criado_em       timestamptz not null default now(),
  atualizado_em   timestamptz not null default now(),
  unique (id_agente, codigo)
);
create unique index agentesia_agente_etapas_uma_principal
  on public.agentesia_agente_etapas (id_agente) where principal;

-- -----------------------------------------------------------------------------
-- ATENDIMENTO: o lead, a conversa e o que a IA fez
-- -----------------------------------------------------------------------------

create table public.agentesia_contatos (
  id                     uuid primary key default gen_random_uuid(),
  id_escritorio          uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_contato_helena      text,
  nome                   text,
  telefone_normalizado   text,                            -- com 55 e com o nono dígito
  criado_em              timestamptz not null default now(),
  atualizado_em          timestamptz not null default now(),
  unique (id_escritorio, id_contato_helena)
);
-- Um contato por telefone em cada escritório (contato com número oculto fica sem telefone).
create unique index agentesia_contatos_telefone
  on public.agentesia_contatos (id_escritorio, telefone_normalizado) where telefone_normalizado is not null;

-- Lead: um contato num canal.
create table public.agentesia_leads (
  id                        uuid primary key default gen_random_uuid(),
  id_escritorio             uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_contato                uuid not null references public.agentesia_contatos(id) on delete cascade,
  id_canal                  uuid not null references public.agentesia_canais(id) on delete cascade,
  id_agente                 uuid references public.agentesia_agentes(id) on delete set null,
  id_etapa                  uuid references public.agentesia_agente_etapas(id) on delete set null,
  estado                    text not null default 'ativo'
                            check (estado in ('ativo', 'pausado', 'encerrado')),
  motivo_estado             text,                         -- humano_assumiu, desqualificado, pediu_parar...
  pausado_ate               timestamptz,                  -- volta automática da IA
  id_sessao_helena          text,                         -- atendimento aberto na Helena
  origem                    jsonb not null default '{}'::jsonb, -- utm, anúncio
  ultima_mensagem_lead_em   timestamptz,
  ultima_resposta_ia_em     timestamptz,
  criado_em                 timestamptz not null default now(),
  atualizado_em             timestamptz not null default now(),
  unique (id_canal, id_contato)
);
create index agentesia_leads_volta on public.agentesia_leads (pausado_ate) where estado = 'pausado';

-- Webhooks crus: descarte de repetidos e reprocessamento.
create table public.agentesia_eventos_recebidos (
  id              uuid primary key default gen_random_uuid(),
  id_escritorio   uuid references public.agentesia_escritorios(id) on delete cascade,
  origem          text not null check (origem in ('helena', 'laboratorio')),
  id_externo      text,
  tipo            text,
  payload         jsonb not null,
  situacao        text not null default 'pendente'
                  check (situacao in ('pendente', 'processado', 'ignorado', 'erro')),
  motivo          text,
  recebido_em     timestamptz not null default now(),
  processado_em   timestamptz,
  unique (origem, id_externo)
);

-- Turno: um lote de mensagens do lead e tudo o que o sistema fez com ele.
-- contexto = o que foi enviado à IA; resposta = extrator, decisões, travas e o que saiu.
create table public.agentesia_turnos (
  id              uuid primary key default gen_random_uuid(),
  id_escritorio   uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_lead         uuid not null references public.agentesia_leads(id) on delete cascade,
  modo            text not null check (modo in ('producao', 'teste', 'laboratorio')),
  etapa_antes     text,
  etapa_depois    text,
  contexto        jsonb,
  resposta        jsonb,
  situacao        text not null default 'processando'
                  check (situacao in ('processando', 'respondido', 'silencio', 'descartado', 'erro')),
  motivo          text,
  iniciado_em     timestamptz not null default now(),
  concluido_em    timestamptz
);
create index agentesia_turnos_lead on public.agentesia_turnos (id_lead, iniciado_em desc);

-- Mensagens de todos os autores, na ordem do WhatsApp.
create table public.agentesia_mensagens (
  id               uuid primary key default gen_random_uuid(),
  id_escritorio    uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_lead          uuid not null references public.agentesia_leads(id) on delete cascade,
  id_turno         uuid references public.agentesia_turnos(id) on delete set null,
  id_externo       text,                                  -- id da mensagem na Helena
  autor            text not null check (autor in ('lead', 'ia', 'humano', 'automacao', 'sistema')),
  tipo             text not null default 'texto'
                   check (tipo in ('texto', 'audio', 'imagem', 'video', 'documento', 'figurinha',
                                   'localizacao', 'contato')),
  texto            text,
  texto_extraido   text,                                  -- transcrição ou descrição da mídia
  url_midia        text,
  enviada_em       timestamptz not null,                  -- horário do WhatsApp
  registrada_em    timestamptz not null default now(),
  situacao_envio   text not null default 'recebida'
                   check (situacao_envio in ('recebida', 'pendente', 'enviada', 'falhou')),
  erro             text
);
create unique index agentesia_mensagens_id_externo
  on public.agentesia_mensagens (id_escritorio, id_externo) where id_externo is not null;
create index agentesia_mensagens_lead on public.agentesia_mensagens (id_lead, enviada_em);

-- Fatos do lead, cada um com o trecho que prova. É a base contra alucinação.
create table public.agentesia_lead_fatos (
  id               uuid primary key default gen_random_uuid(),
  id_escritorio    uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_lead          uuid not null references public.agentesia_leads(id) on delete cascade,
  chave            text not null,                         -- data_acidente, tinha_carteira...
  valor            jsonb not null,
  trecho           text,                                  -- frase literal do lead
  id_mensagem      uuid references public.agentesia_mensagens(id) on delete set null,
  fonte            text not null check (fonte in ('extrator', 'equipe', 'sistema')),
  id_turno         uuid references public.agentesia_turnos(id) on delete set null,
  criado_em        timestamptz not null default now(),
  substituido_em   timestamptz
);
create index agentesia_lead_fatos_vigentes
  on public.agentesia_lead_fatos (id_lead, chave) where substituido_em is null;

-- Cada chamada de IA: modelo, tokens, tempo e erro.
create table public.agentesia_chamadas_ia (
  id               uuid primary key default gen_random_uuid(),
  id_escritorio    uuid references public.agentesia_escritorios(id) on delete cascade,
  id_turno         uuid references public.agentesia_turnos(id) on delete set null,
  papel            text not null,                         -- extrator, etapa, transcricao...
  modelo           text not null,
  tokens_entrada   int not null default 0,
  tokens_saida     int not null default 0,
  custo_usd        numeric(12,6) not null default 0,
  duracao_ms       int,
  sucesso          boolean not null,
  erro             text,
  criado_em        timestamptz not null default now()
);

-- Problemas e travas, com o responsável.
create table public.agentesia_eventos (
  id              uuid primary key default gen_random_uuid(),
  id_escritorio   uuid references public.agentesia_escritorios(id) on delete cascade,
  id_lead         uuid references public.agentesia_leads(id) on delete cascade,
  id_turno        uuid references public.agentesia_turnos(id) on delete set null,
  tipo            text not null,                          -- trava_honorarios, erro_helena...
  gravidade       text not null default 'aviso' check (gravidade in ('info', 'aviso', 'erro', 'critico')),
  responsavel     text check (responsavel in ('cliente', 'cadastro', 'provedor', 'lead', 'lawchat')),
  descricao       text,
  detalhe         jsonb,
  criado_em       timestamptz not null default now()
);
create index agentesia_eventos_escritorio on public.agentesia_eventos (id_escritorio, criado_em desc);

-- -----------------------------------------------------------------------------
-- atualizado_em automático e RLS em tudo
-- -----------------------------------------------------------------------------
do $$
declare t text;
begin
  for t in
    select c.table_name from information_schema.columns c
    where c.table_schema = 'public' and c.table_name like 'agentesia\_%'
      and c.column_name = 'atualizado_em'
  loop
    execute format('create trigger %I before update on public.%I
                    for each row execute function public.agentesia_tocar_atualizado_em()',
                   t || '_atualizado_em', t);
  end loop;

  for t in
    select tablename from pg_tables
    where schemaname = 'public' and tablename like 'agentesia\_%'
  loop
    execute format('alter table public.%I enable row level security', t);
  end loop;
end
$$;

commit;
