-- =============================================================================
-- 020_agentesia_vozes_prontas.sql
-- Vozes prontas do roteiro de gravação: a LawChat grava (voz de IA ou da equipe), uma vez, os áudios de cada parte do
-- roteiro em algumas vozes. O escritório que não quer gravar escolhe uma voz, marca o aceite e usa: os áudios entram
-- na biblioteca dele como se tivesse gravado (pasta "Roteiros prontos/<voz>"), com o arquivo compartilhado da LawChat.
--
-- A) agentesia_vozes_prontas: as vozes (nome, tom, gênero, origem ia|equipe, ativo, ordem).
-- B) agentesia_voz_pronta_audios: o áudio (ou vídeo) de cada voz em cada parte do roteiro. Uma por voz + parte.
--    Áudio numa parte de vídeo é permitido (boas-vindas por áudio no lugar do vídeo inicial).
-- C) agentesia_voz_pronta_aceites: o aceite do escritório ("são modelos usados por outros escritórios").
-- D) agentesia_roteiro_gravacoes ganha origem (propria|pronta) e id_voz.
-- E) agentesia_roteiro_partes ganha texto_pronto (o que a voz pronta fala: sem nome de escritório, advogado, atendente,
--    cidade nem número; é o texto que a LawChat leva ao ElevenLabs) e aviso_pronto (o que o escritório precisa saber
--    antes de usar, ex.: "Fala: 4 salários mínimos e 30% dos atrasados" nos honorários).
--
-- Só acrescenta. Pode rodar mais de uma vez e com o servidor no ar. Depende da 019.
-- RLS ligado, sem políticas: só o servidor (service_role) lê e grava, como nas outras tabelas agentesia_*.
-- Para desfazer: desfazer_020.sql.
-- =============================================================================

begin;

create table if not exists public.agentesia_vozes_prontas (
  id             uuid primary key default gen_random_uuid(),
  nome           text not null,
  tom            text,
  genero         text check (genero is null or genero in ('feminina', 'masculina')),
  origem         text not null default 'ia' check (origem in ('ia', 'equipe')),
  descricao      text,
  ativo          boolean not null default true,
  ordem          int not null default 0,
  criado_em      timestamptz not null default now(),
  atualizado_em  timestamptz not null default now()
);
alter table public.agentesia_vozes_prontas enable row level security;

create table if not exists public.agentesia_voz_pronta_audios (
  id             uuid primary key default gen_random_uuid(),
  id_voz         uuid not null references public.agentesia_vozes_prontas(id) on delete cascade,
  id_parte       uuid not null references public.agentesia_roteiro_partes(id) on delete cascade,
  tipo           text not null check (tipo in ('audio', 'video')),
  url            text not null,
  caminho_storage text,
  mime_type      text,
  tamanho_bytes  bigint,
  duracao_s      numeric(8,2),
  criado_em      timestamptz not null default now(),
  unique (id_voz, id_parte)
);
create index if not exists agentesia_voz_pronta_audios_parte on public.agentesia_voz_pronta_audios (id_parte);
alter table public.agentesia_voz_pronta_audios enable row level security;

create table if not exists public.agentesia_voz_pronta_aceites (
  id                     uuid primary key default gen_random_uuid(),
  id_escritorio          uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_voz                 uuid references public.agentesia_vozes_prontas(id) on delete set null,
  id_produto_biblioteca  uuid,
  id_usuario             uuid references public.agentesia_usuarios(id) on delete set null,
  texto                  text not null,
  aceito_em              timestamptz not null default now()
);
create index if not exists agentesia_voz_pronta_aceites_escritorio on public.agentesia_voz_pronta_aceites (id_escritorio);
alter table public.agentesia_voz_pronta_aceites enable row level security;

alter table public.agentesia_roteiro_gravacoes
  add column if not exists origem text not null default 'propria' check (origem in ('propria', 'pronta'));
alter table public.agentesia_roteiro_gravacoes
  add column if not exists id_voz uuid references public.agentesia_vozes_prontas(id) on delete set null;
create index if not exists agentesia_roteiro_gravacoes_voz
  on public.agentesia_roteiro_gravacoes (id_voz) where id_voz is not null;

alter table public.agentesia_roteiro_partes add column if not exists texto_pronto text;
alter table public.agentesia_roteiro_partes add column if not exists aviso_pronto text;

commit;
