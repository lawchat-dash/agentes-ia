-- =============================================================================
-- desfazer_004.sql
-- Volta o id_canal do agente a obrigatório e tira as colunas de histórico da 004.
--
-- Agente sem número (produto na lixeira ou esperando ativação) não cabe no "not null":
--   1. quem tem o número anterior ainda livre volta para ele (pausado, como estava); se dois agentes tiverem o
--      mesmo número anterior (os dois foram para a lixeira), volta só o que soltou por último;
--   2. se ainda sobrar agente sem número (o número anterior foi para outro produto ou sumiu), o script PARA
--      e lista quem é: decida antes (reativar com outro número ou excluir o produto). Nada é apagado aqui.
-- Pode rodar de novo: sem as colunas da 004, o passo 1 é pulado.
-- =============================================================================

begin;

do $$
declare
  sobra text;
begin
  if exists (select 1 from information_schema.columns
              where table_schema = 'public' and table_name = 'agentesia_agentes' and column_name = 'id_canal_anterior') then
    execute $q$
      update public.agentesia_agentes a
         set id_canal = a.id_canal_anterior, situacao = 'pausado'
        from (select distinct on (id_canal_anterior) id from public.agentesia_agentes
               where id_canal is null and id_canal_anterior is not null
               order by id_canal_anterior, canal_liberado_em desc nulls last, criado_em desc) escolhido
       where a.id = escolhido.id
         and not exists (select 1 from public.agentesia_agentes o where o.id_canal = a.id_canal_anterior)
    $q$;
  end if;
  select string_agg(a.nome || ' (' || a.id || ')', ', ') into sobra
    from public.agentesia_agentes a where a.id_canal is null;
  if sobra is not null then
    raise exception 'Agentes sem número de WhatsApp: %. Reative com um número ou exclua o produto antes de desfazer a 004.', sobra;
  end if;
end $$;

alter table public.agentesia_agentes alter column id_canal set not null;
alter table if exists public.agentesia_agentes
  drop column if exists id_canal_anterior,
  drop column if exists canal_liberado_em;

commit;
