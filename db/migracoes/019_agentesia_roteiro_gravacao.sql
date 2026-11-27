-- =============================================================================
-- 019_agentesia_roteiro_gravacao.sql
-- Roteiro de gravação por produto: o que o escritório grava (áudios e vídeos) para a IA falar com a voz dele.
--
-- A) agentesia_roteiro_partes: as partes do roteiro de cada produto do catálogo (Admin › Produtos › Roteiros):
--    título, texto para ler, áudio ou vídeo, seção, exemplo de referência, ordem e o MARCADOR do prompt que ela
--    preenche ([[audio:Honorários]] → marcador "Honorários"). chave_geral = parte geral (vídeo inicial, como assinar):
--    a mesma chave em vários produtos é gravada uma vez só e serve para todos.
-- B) agentesia_roteiro_gravacoes: o que o escritório gravou. Uma por escritório + chave (chave = 'geral:<chave_geral>'
--    ou 'parte:<id da parte>'); regravar substitui. O arquivo é um item da biblioteca de mídia.
-- C) agentesia_biblioteca_midia ganha "pasta" (ex.: "Roteiros gravados/Auxílio-Acidente").
-- D) agentesia_biblioteca_produtos ganha roteiro_orientacoes (texto antes de começar a gravar).
-- E) agentesia_planos ganha "midia" (o plano libera mídia e roteiros); ligado em pro_plus, master e enterprise.
--
-- Só acrescenta. Pode rodar mais de uma vez e com o servidor no ar. Depende da 002, 007 e 017.
-- Para desfazer: desfazer_019.sql.
-- =============================================================================

begin;

create table if not exists public.agentesia_roteiro_partes (
  id                     uuid primary key default gen_random_uuid(),
  id_produto_biblioteca  uuid not null references public.agentesia_biblioteca_produtos(id) on delete cascade,
  titulo                 text not null,
  texto                  text not null default '',
  tipo                   text not null default 'audio' check (tipo in ('audio', 'video')),
  secao                  text not null default 'principais' check (secao in ('videos', 'principais', 'objecoes')),
  marcador               text,                     -- nome dentro de [[audio:...]] / [[video:...]] no prompt
  chave_geral            text check (chave_geral is null or chave_geral ~ '^[a-z0-9_-]{2,60}$'),
  exemplo_url            text,
  ordem                  int not null default 0,
  ativo                  boolean not null default true,
  criado_em              timestamptz not null default now(),
  atualizado_em          timestamptz not null default now()
);
create index if not exists agentesia_roteiro_partes_produto
  on public.agentesia_roteiro_partes (id_produto_biblioteca, ordem);
alter table public.agentesia_roteiro_partes enable row level security;

create table if not exists public.agentesia_roteiro_gravacoes (
  id             uuid primary key default gen_random_uuid(),
  id_escritorio  uuid not null references public.agentesia_escritorios(id) on delete cascade,
  chave          text not null,                    -- 'geral:<chave_geral>' | 'parte:<id da parte>'
  id_parte       uuid references public.agentesia_roteiro_partes(id) on delete set null,
  id_midia       uuid not null references public.agentesia_biblioteca_midia(id) on delete cascade,
  duracao_s      numeric(8,2),
  pico           numeric(6,4),
  silencio_pct   numeric(5,2),
  qualidade      text check (qualidade is null or qualidade in ('boa', 'curta', 'baixa', 'silenciosa')),
  id_usuario     uuid references public.agentesia_usuarios(id) on delete set null,
  criado_em      timestamptz not null default now(),
  atualizado_em  timestamptz not null default now(),
  unique (id_escritorio, chave)
);
alter table public.agentesia_roteiro_gravacoes enable row level security;

alter table public.agentesia_biblioteca_midia add column if not exists pasta text;
create index if not exists agentesia_biblioteca_midia_pasta
  on public.agentesia_biblioteca_midia (id_escritorio, pasta) where pasta is not null;

-- Orientações do roteiro (o texto da tela antes de começar a gravar), por produto do catálogo.
alter table public.agentesia_biblioteca_produtos add column if not exists roteiro_orientacoes text;

alter table public.agentesia_planos add column if not exists midia boolean not null default false;
update public.agentesia_planos set midia = true where codigo in ('pro_plus', 'master', 'enterprise') and not midia;

commit;
