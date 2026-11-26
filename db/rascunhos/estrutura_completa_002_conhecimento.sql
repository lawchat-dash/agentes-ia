-- =============================================================================
-- 002_agentesia_conhecimento.sql
-- Base de conhecimento com busca por semelhança (pgvector).
-- Separada da 001 porque depende da extensão vector.
-- Embeddings de 1536 dimensões (text-embedding-3-small da OpenAI).
-- =============================================================================

begin;

-- No Supabase a extensão costuma estar no schema extensions; se o projeto já a
-- tiver em public, o comando abaixo não faz nada e os nomes sem schema continuam
-- funcionando, porque o search_path inclui os dois.
create extension if not exists vector with schema extensions;
set local search_path = public, extensions;

create table public.agentesia_conhecimento (
  id              uuid primary key default gen_random_uuid(),
  id_produto      uuid references public.agentesia_produtos(id) on delete cascade,    -- vale para o produto
  id_escritorio   uuid references public.agentesia_escritorios(id) on delete cascade, -- vale para o escritório
  id_agente       uuid references public.agentesia_agentes(id) on delete cascade,     -- vale só para o agente
  titulo          text not null,
  conteudo        text not null,
  fonte           text,                                   -- faq, objecao, regra, documento...
  embedding       vector(1536),
  ativo           boolean not null default true,
  criado_em       timestamptz not null default now(),
  atualizado_em   timestamptz not null default now()
);

create index agentesia_conhecimento_embedding
  on public.agentesia_conhecimento using hnsw (embedding vector_cosine_ops);

create trigger agentesia_conhecimento_atualizado_em
  before update on public.agentesia_conhecimento
  for each row execute function public.agentesia_tocar_atualizado_em();

alter table public.agentesia_conhecimento enable row level security;

-- Busca os trechos mais parecidos que valem para o agente:
-- os do próprio agente, os do escritório dele e os do produto dele.
create or replace function public.agentesia_buscar_conhecimento(
  p_id_agente  uuid,
  p_embedding  vector(1536),
  p_limite     int default 5
)
returns table (id uuid, titulo text, conteudo text, fonte text, semelhanca float)
language sql
stable
set search_path = public, extensions
as $$
  select k.id, k.titulo, k.conteudo, k.fonte,
         1 - (k.embedding <=> p_embedding) as semelhanca
  from public.agentesia_conhecimento k
  join public.agentesia_agentes a on a.id = p_id_agente
  where k.ativo
    and k.embedding is not null
    and (k.id_agente = a.id
         or (k.id_agente is null and k.id_escritorio = a.id_escritorio)
         or (k.id_agente is null and k.id_escritorio is null and k.id_produto = a.id_produto))
  order by k.embedding <=> p_embedding
  limit greatest(1, least(p_limite, 20));
$$;

commit;
