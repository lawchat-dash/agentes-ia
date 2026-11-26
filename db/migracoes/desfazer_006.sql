-- =============================================================================
-- desfazer_006.sql
-- Tira o que a 006 criou: onboarding e sincronização da conta, cópia dos recursos da Helena, histórico de etapa,
-- chave de telefone sem o nono dígito, detalhes do canal e situação/erro das alterações.
-- Apaga os dados dessas tabelas e colunas (o código volta a funcionar como antes). Pode rodar de novo.
-- =============================================================================

begin;

drop trigger if exists agentesia_leads_troca_etapa on public.agentesia_leads;
drop function if exists public.agentesia_registrar_troca_etapa();
drop table if exists public.agentesia_lead_etapas cascade;
drop table if exists public.agentesia_helena_recursos cascade;

drop index if exists public.agentesia_contatos_telefone_chave;
alter table if exists public.agentesia_contatos drop column if exists telefone_chave;

alter table if exists public.agentesia_canais
  drop column if exists nome_exibicao,
  drop column if exists tipo_helena,
  drop column if exists sincronizado_em;

alter table if exists public.agentesia_alteracoes
  drop column if exists situacao,
  drop column if exists erro;

alter table if exists public.agentesia_escritorios
  drop column if exists onboarding,
  drop column if exists sincronizado_em,
  drop column if exists dados_helena;

commit;
