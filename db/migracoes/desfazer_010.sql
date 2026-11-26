-- Desfaz a 010 (só índices; nenhum dado se perde). Pode rodar de novo.
begin;
drop index if exists public.agentesia_leads_escritorio_recentes;
drop index if exists public.agentesia_leads_escritorio_criado;
drop index if exists public.agentesia_leads_agente_criado;
drop index if exists public.agentesia_mensagens_escritorio_enviada;
drop index if exists public.agentesia_mensagens_escritorio_ia;
drop index if exists public.agentesia_eventos_lead;
drop index if exists public.agentesia_turnos_escritorio_erro;
drop index if exists public.agentesia_eventos_recebidos_escritorio;
drop index if exists public.agentesia_followups_escritorio;
drop index if exists public.agentesia_contratos_lead;
commit;
