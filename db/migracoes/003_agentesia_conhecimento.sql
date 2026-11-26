-- =============================================================================
-- 003_agentesia_conhecimento.sql
-- Base de conhecimento por papel (docs/BASE_DE_CONHECIMENTO.md):
--   * escopo por papel/etapa nos documentos e nos trechos (vazio = todos os papéis);
--   * documentos "virtuais" de FAQ e objeções (um de cada por agente, gerados da config.conhecimento);
--   * trechos com escritório, título, fonte, hash (cache de embedding), modelo e dimensões;
--   * perguntas sem resposta na base (agentesia_conhecimento_lacunas), para o painel virar FAQ.
--
-- Só mexe em tabelas agentesia_*. Depende da 002. Para desfazer: desfazer_003.sql.
-- Sem pgvector: os vetores continuam como real[] (ver seção 2 do desenho).
-- =============================================================================

begin;

-- Documentos: escopo por papel e os tipos virtuais.
alter table public.agentesia_documentos
  add column if not exists papeis text[] not null default '{}';          -- vazio = todos os papéis
alter table public.agentesia_documentos drop constraint if exists agentesia_documentos_tipo_check;
alter table public.agentesia_documentos add constraint agentesia_documentos_tipo_check
  check (tipo in ('arquivo', 'texto', 'faq', 'objecoes'));
-- Um documento virtual de cada tipo por agente.
create unique index if not exists agentesia_documentos_virtual_unico
  on public.agentesia_documentos (id_agente, tipo) where tipo in ('faq', 'objecoes');

-- Trechos: escopo, fonte e cache de embedding.
alter table public.agentesia_documento_trechos
  add column if not exists id_escritorio uuid references public.agentesia_escritorios(id) on delete cascade,
  add column if not exists papeis        text[] not null default '{}',
  add column if not exists titulo        text,
  add column if not exists fonte         text not null default 'documento',
  add column if not exists hash          text,
  add column if not exists modelo        text not null default 'text-embedding-3-small',
  add column if not exists dimensoes     int  not null default 1536;
alter table public.agentesia_documento_trechos drop constraint if exists agentesia_documento_trechos_fonte_check;
alter table public.agentesia_documento_trechos add constraint agentesia_documento_trechos_fonte_check
  check (fonte in ('documento', 'faq', 'objecao'));
-- Trechos antigos: escritório do documento e dimensão do vetor guardado.
update public.agentesia_documento_trechos t
   set id_escritorio = d.id_escritorio
  from public.agentesia_documentos d
 where d.id = t.id_documento and t.id_escritorio is null;
update public.agentesia_documento_trechos
   set dimensoes = coalesce(array_length(vetor, 1), 0)
 where dimensoes <> coalesce(array_length(vetor, 1), 0);
create index if not exists agentesia_documento_trechos_hash
  on public.agentesia_documento_trechos (id_agente, hash);

-- Perguntas que a IA não achou na base nem no prompt (base.sem_resposta da saída do agente).
create table if not exists public.agentesia_conhecimento_lacunas (
  id                   uuid primary key default gen_random_uuid(),
  id_escritorio        uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_agente            uuid not null references public.agentesia_agentes(id) on delete cascade,
  papel                text,                                   -- etapa em que a pergunta apareceu
  pergunta             text not null,                          -- como a IA resumiu a pergunta do lead
  pergunta_normalizada text not null,                          -- minúsculas, sem acento e sem pontuação (agrupa repetidas)
  vezes                int  not null default 1 check (vezes >= 1),
  ultimo_lead          uuid references public.agentesia_leads(id) on delete set null,
  ultimo_turno         uuid references public.agentesia_turnos(id) on delete set null,
  situacao             text not null default 'aberta' check (situacao in ('aberta', 'respondida', 'ignorada')),
  resposta             text,                                   -- quando respondida, vira item da FAQ
  respondida_por       uuid references public.agentesia_usuarios(id) on delete set null,
  criado_em            timestamptz not null default now(),
  ultima_em            timestamptz not null default now(),
  atualizado_em        timestamptz not null default now()
);
-- A mesma dúvida aberta soma em "vezes" (upsert por este índice).
create unique index if not exists agentesia_conhecimento_lacunas_aberta
  on public.agentesia_conhecimento_lacunas (id_agente, pergunta_normalizada) where situacao = 'aberta';
create index if not exists agentesia_conhecimento_lacunas_escritorio
  on public.agentesia_conhecimento_lacunas (id_escritorio, situacao, ultima_em desc);

create trigger agentesia_conhecimento_lacunas_atualizado_em before update on public.agentesia_conhecimento_lacunas
  for each row execute function public.agentesia_tocar_atualizado_em();
alter table public.agentesia_conhecimento_lacunas enable row level security;

commit;
