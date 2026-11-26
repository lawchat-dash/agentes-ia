-- Desfaz a 015 (central de notificações do sino): some só a data da última leitura e os dois índices.
-- As notificações em si vêm de tabelas que continuam. Pode rodar de novo.
begin;
drop index if exists public.agentesia_alteracoes_desligou_ia;
drop index if exists public.agentesia_contratos_escritorio_gerado;
drop table if exists public.agentesia_notificacoes_leitura;
commit;
