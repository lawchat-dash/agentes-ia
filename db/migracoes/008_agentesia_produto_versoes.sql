-- =============================================================================
-- 008_agentesia_produto_versoes.sql
-- Versões dos prompts de um produto ativado (rascunho -> publicar -> voltar; docs/PESQUISA_PLATAFORMAS.md, item 3).
--
-- Cada vez que o produto é ativado ou salvo no editor (sincronizar), o servidor grava uma versão com:
--   número (1, 2, 3... por produto), quem salvou, quando, o resumo das mudanças e o CONTEÚDO dos agentes
--   (prompts, nomes, boas-vindas, frases de troca, FAQ, objeções, regras e dados do escritório).
-- "Restaurar" no painel só copia o conteúdo de uma versão para o rascunho do editor: nada vai ao ar sozinho.
--
-- O código funciona sem esta migração (só não grava nem lista versões): pode aplicar com o servidor no ar.
-- Pode rodar mais de uma vez. Só mexe em tabelas agentesia_*. Depende da 001 e da 002.
-- RLS ligado, sem políticas: só o servidor (service_role) lê e grava, como nas outras tabelas agentesia_*.
-- Para desfazer: desfazer_008.sql.
-- =============================================================================

begin;

create table if not exists public.agentesia_produto_versoes (
  id                  uuid primary key default gen_random_uuid(),
  id_escritorio       uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_produto_ativado  uuid not null references public.agentesia_produtos_ativados(id) on delete cascade,
  numero              int not null,                       -- 1, 2, 3... dentro do produto
  origem              text not null default 'sincronizou', -- ativou | sincronizou
  id_usuario          uuid references public.agentesia_usuarios(id) on delete set null,
  autor               text,                               -- nome de quem salvou (fica mesmo se o usuário sair)
  resumo              jsonb not null default '[]'::jsonb, -- ["Prompt do Closer", "FAQ (+2)", ...]
  conteudo            jsonb not null,                     -- {agentes: [...], faq, objecoes, regras_markdown, dados_escritorio}
  criado_em           timestamptz not null default now(),
  unique (id_produto_ativado, numero)
);
create index if not exists agentesia_produto_versoes_produto
  on public.agentesia_produto_versoes (id_produto_ativado, numero desc);
create index if not exists agentesia_produto_versoes_escritorio
  on public.agentesia_produto_versoes (id_escritorio, criado_em desc);
do $$ begin
  alter table public.agentesia_produto_versoes add constraint agentesia_produto_versoes_origem
    check (origem in ('ativou', 'sincronizou'));
exception when duplicate_object then null; end $$;
alter table public.agentesia_produto_versoes enable row level security;

commit;
