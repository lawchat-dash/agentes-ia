-- Desfaz a 011 (só índices; nenhum dado se perde). Pode rodar de novo.
begin;
drop index if exists public.agentesia_turnos_recentes;
drop index if exists public.agentesia_turnos_escritorio_recentes;
commit;
