-- =============================================================================
-- 014_agentesia_isolamento.sql
-- Integridade entre escritórios (auditoria de isolamento): o banco passa a recusar que uma linha de um escritório
-- aponte para o lead, o contato ou o canal de OUTRO escritório. O código já filtra id_escritorio em todo lugar; isto
-- é a rede de segurança por baixo.
--
--   unique (id, id_escritorio)      em agentesia_leads, agentesia_canais e agentesia_contatos (alvo das FKs compostas)
--   FK (id_lead, id_escritorio)     em agentesia_mensagens, agentesia_turnos, agentesia_acoes e agentesia_followups
--   FK (id_contato, id_escritorio) e (id_canal, id_escritorio) em agentesia_leads
--
-- As FKs entram NOT VALID (não varrem a tabela) e valem na hora para tudo que for gravado depois. Em seguida cada uma
-- é validada SÓ SE não houver nenhuma linha divergente; se houver, fica NOT VALID e sai um aviso (NOTICE) com o nome
-- dela: corrija os dados e rode `alter table ... validate constraint ...`. As FKs antigas (só por id) continuam.
-- Pode rodar mais de uma vez. Depende da 001 e da 002. Para desfazer: desfazer_014.sql.
-- NÃO aplicar em produção sem rodar antes a conferência abaixo.
--
-- Conferência dos dados existentes (rode antes; cada linha com n > 0 é uma FK que vai ficar NOT VALID):
--
--   select 'mensagens' as tabela, count(*) as n from public.agentesia_mensagens m
--     join public.agentesia_leads l on l.id = m.id_lead where l.id_escritorio <> m.id_escritorio
--   union all select 'turnos', count(*) from public.agentesia_turnos t
--     join public.agentesia_leads l on l.id = t.id_lead where l.id_escritorio <> t.id_escritorio
--   union all select 'acoes', count(*) from public.agentesia_acoes a
--     join public.agentesia_leads l on l.id = a.id_lead where l.id_escritorio <> a.id_escritorio
--   union all select 'followups', count(*) from public.agentesia_followups f
--     join public.agentesia_leads l on l.id = f.id_lead where l.id_escritorio <> f.id_escritorio
--   union all select 'leads->contatos', count(*) from public.agentesia_leads l
--     join public.agentesia_contatos c on c.id = l.id_contato where c.id_escritorio <> l.id_escritorio
--   union all select 'leads->canais', count(*) from public.agentesia_leads l
--     join public.agentesia_canais c on c.id = l.id_canal where c.id_escritorio <> l.id_escritorio;
-- =============================================================================

begin;

do $$
declare
  alvo record;
begin
  for alvo in select * from (values
      ('agentesia_leads',    'agentesia_leads_id_escritorio_unico'),
      ('agentesia_canais',   'agentesia_canais_id_escritorio_unico'),
      ('agentesia_contatos', 'agentesia_contatos_id_escritorio_unico')) as v(tabela, nome)
  loop
    if not exists (select 1 from pg_constraint where conname = alvo.nome) then
      execute format('alter table public.%I add constraint %I unique (id, id_escritorio)', alvo.tabela, alvo.nome);
    end if;
  end loop;
end $$;

do $$
declare
  fk record;
begin
  for fk in select * from (values
      ('agentesia_mensagens', 'agentesia_mensagens_lead_do_escritorio', 'id_lead',    'agentesia_leads'),
      ('agentesia_turnos',    'agentesia_turnos_lead_do_escritorio',    'id_lead',    'agentesia_leads'),
      ('agentesia_acoes',     'agentesia_acoes_lead_do_escritorio',     'id_lead',    'agentesia_leads'),
      ('agentesia_followups', 'agentesia_followups_lead_do_escritorio', 'id_lead',    'agentesia_leads'),
      ('agentesia_leads',     'agentesia_leads_contato_do_escritorio',  'id_contato', 'agentesia_contatos'),
      ('agentesia_leads',     'agentesia_leads_canal_do_escritorio',    'id_canal',   'agentesia_canais')) as v(tabela, nome, coluna, pai)
  loop
    if not exists (select 1 from pg_constraint where conname = fk.nome) then
      execute format('alter table public.%I add constraint %I foreign key (%I, id_escritorio) '
                     'references public.%I (id, id_escritorio) on delete cascade not valid',
                     fk.tabela, fk.nome, fk.coluna, fk.pai);
    end if;
  end loop;
end $$;

commit;

-- Validação só quando é seguro (nenhuma linha divergente). Fora da transação acima: as FKs já valem para o que entrar.
do $$
declare
  fk record;
  divergentes bigint;
begin
  for fk in select * from (values
      ('agentesia_mensagens', 'agentesia_mensagens_lead_do_escritorio', 'id_lead',    'agentesia_leads'),
      ('agentesia_turnos',    'agentesia_turnos_lead_do_escritorio',    'id_lead',    'agentesia_leads'),
      ('agentesia_acoes',     'agentesia_acoes_lead_do_escritorio',     'id_lead',    'agentesia_leads'),
      ('agentesia_followups', 'agentesia_followups_lead_do_escritorio', 'id_lead',    'agentesia_leads'),
      ('agentesia_leads',     'agentesia_leads_contato_do_escritorio',  'id_contato', 'agentesia_contatos'),
      ('agentesia_leads',     'agentesia_leads_canal_do_escritorio',    'id_canal',   'agentesia_canais')) as v(tabela, nome, coluna, pai)
  loop
    if exists (select 1 from pg_constraint where conname = fk.nome and not convalidated) then
      execute format('select count(*) from public.%I f join public.%I p on p.id = f.%I '
                     'where p.id_escritorio <> f.id_escritorio', fk.tabela, fk.pai, fk.coluna) into divergentes;
      if divergentes = 0 then
        execute format('alter table public.%I validate constraint %I', fk.tabela, fk.nome);
      else
        raise notice '% ficou NOT VALID: % linha(s) de %.% apontam para outro escritório',
          fk.nome, divergentes, fk.tabela, fk.coluna;
      end if;
    end if;
  end loop;
end $$;
