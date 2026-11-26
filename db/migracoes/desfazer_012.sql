-- Desfaz a 012 (índices dos relatórios e o espelho do CRM). Apaga só o espelho dos cards e o ponto da varredura:
-- leads, cards ligados (agentesia_crm_cards), contratos e conversas ficam. Pode rodar de novo.
begin;
drop table if exists public.agentesia_crm_varredura;
drop table if exists public.agentesia_crm_espelho;
drop index if exists public.agentesia_leads_escritorio_origem;
drop index if exists public.agentesia_contratos_escritorio_assinado;
commit;
