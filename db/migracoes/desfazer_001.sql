-- =============================================================================
-- desfazer_001.sql
-- Remove o que a 001 criou: as tabelas agentesia_* (com os dados delas) e a
-- função agentesia_tocar_atualizado_em. Não toca em nenhuma outra tabela.
-- =============================================================================

begin;

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
