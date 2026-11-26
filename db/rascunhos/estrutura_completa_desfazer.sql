-- =============================================================================
-- desfazer_001_002.sql
-- Remove TUDO o que as migrações 001 e 002 criaram (tabelas agentesia_*,
-- visões e funções). Apaga também os dados dessas tabelas.
-- Não toca em nenhuma outra tabela do projeto.
-- A extensão vector não é removida (outras tabelas do projeto podem usar).
-- =============================================================================

begin;

drop view if exists public.agentesia_v_saude;
drop view if exists public.agentesia_v_custo_dia;
drop view if exists public.agentesia_v_followup_fila;
drop view if exists public.agentesia_v_funil;

drop function if exists public.agentesia_buscar_conhecimento;

do $$
declare t text;
begin
  for t in
    select tablename from pg_tables
    where schemaname = 'public' and tablename like 'agentesia\_%'
  loop
    execute format('drop table if exists public.%I cascade', t);
  end loop;
end
$$;

drop function if exists public.agentesia_tocar_atualizado_em();

commit;
