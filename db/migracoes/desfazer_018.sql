-- Desfaz a 018 (log da plataforma): apaga a tabela agentesia_log_plataforma e os índices dela (o histórico do
-- Superadmin › Logs some junto). Nada mais muda: agentesia_alteracoes continua. Pode rodar de novo.
begin;
drop table if exists public.agentesia_log_plataforma;
commit;
