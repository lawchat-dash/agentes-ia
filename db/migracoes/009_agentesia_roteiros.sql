-- =============================================================================
-- 009_agentesia_roteiros.sql
-- Roteiros de áudio do escritório (Ferramentas > Roteiros).
--
-- Um roteiro é o texto que alguém da equipe vai gravar em áudio: título, texto, para qual agente/etapa/produto
-- é (opcional) e a situação (a_gravar | gravado). Quando o áudio é gravado no navegador ou enviado, ele vira um
-- item da biblioteca de mídia (agentesia_biblioteca_midia) e o roteiro guarda o id dele (id_midia); daí pode ser
-- inserido no prompt como as outras mídias.
--
-- O código funciona sem esta migração (a tela de roteiros avisa que falta aplicar): pode aplicar com o servidor no ar.
-- Pode rodar mais de uma vez. Só mexe em tabelas agentesia_*. Depende da 001 e da 002.
-- RLS ligado, sem políticas: só o servidor (service_role) lê e grava, como nas outras tabelas agentesia_*.
-- Para desfazer: desfazer_009.sql.
-- =============================================================================

begin;

create table if not exists public.agentesia_roteiros (
  id                  uuid primary key default gen_random_uuid(),
  id_escritorio       uuid not null references public.agentesia_escritorios(id) on delete cascade,
  titulo              text not null,
  texto               text not null default '',
  id_agente           uuid references public.agentesia_agentes(id) on delete set null,
  etapa               text,                                -- código da etapa do agente (sdr, closer...), opcional
  id_produto_ativado  uuid references public.agentesia_produtos_ativados(id) on delete set null,
  status              text not null default 'a_gravar',    -- a_gravar | gravado
  id_midia            uuid references public.agentesia_biblioteca_midia(id) on delete set null,
  id_usuario          uuid references public.agentesia_usuarios(id) on delete set null,
  criado_em           timestamptz not null default now(),
  atualizado_em       timestamptz not null default now()
);
create index if not exists agentesia_roteiros_escritorio
  on public.agentesia_roteiros (id_escritorio, criado_em desc);
create index if not exists agentesia_roteiros_midia
  on public.agentesia_roteiros (id_midia) where id_midia is not null;
do $$ begin
  alter table public.agentesia_roteiros add constraint agentesia_roteiros_status
    check (status in ('a_gravar', 'gravado'));
exception when duplicate_object then null; end $$;
do $$ begin
  create trigger agentesia_roteiros_atualizado_em before update on public.agentesia_roteiros
    for each row execute function public.agentesia_tocar_atualizado_em();
exception when duplicate_object then null; end $$;
alter table public.agentesia_roteiros enable row level security;

commit;
