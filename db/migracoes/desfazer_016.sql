-- Desfaz a 016 (agente arquivado): os agentes arquivados voltam a pausados (não atendem, como antes)
-- e a checagem volta a aceitar só 'ativo' e 'pausado'. Pode rodar de novo.
begin;
update public.agentesia_agentes set situacao = 'pausado' where situacao = 'arquivado';
alter table public.agentesia_agentes drop constraint if exists agentesia_agentes_situacao_check;
alter table public.agentesia_agentes
  add constraint agentesia_agentes_situacao_check check (situacao in ('ativo', 'pausado'));
commit;
