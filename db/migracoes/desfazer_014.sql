-- Desfaz a 014 (FKs compostas de isolamento e os unique (id, id_escritorio)). As FKs antigas, só por id, continuam.
-- Pode rodar de novo.
begin;
alter table public.agentesia_mensagens drop constraint if exists agentesia_mensagens_lead_do_escritorio;
alter table public.agentesia_turnos    drop constraint if exists agentesia_turnos_lead_do_escritorio;
alter table public.agentesia_acoes     drop constraint if exists agentesia_acoes_lead_do_escritorio;
alter table public.agentesia_followups drop constraint if exists agentesia_followups_lead_do_escritorio;
alter table public.agentesia_leads     drop constraint if exists agentesia_leads_contato_do_escritorio;
alter table public.agentesia_leads     drop constraint if exists agentesia_leads_canal_do_escritorio;
alter table public.agentesia_leads     drop constraint if exists agentesia_leads_id_escritorio_unico;
alter table public.agentesia_canais    drop constraint if exists agentesia_canais_id_escritorio_unico;
alter table public.agentesia_contatos  drop constraint if exists agentesia_contatos_id_escritorio_unico;
commit;
