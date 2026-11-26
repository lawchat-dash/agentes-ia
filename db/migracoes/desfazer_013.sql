-- Desfaz a 013 (colunas novas do espelho dos cards do CRM). O espelho e os cards continuam; só some o que a 013
-- acrescentou. Pode rodar de novo.
begin;
drop index if exists public.agentesia_crm_espelho_escritorio_atualizado;
drop index if exists public.agentesia_crm_espelho_escritorio_painel;
alter table public.agentesia_crm_espelho
  drop column if exists titulo_painel, drop column if exists fase_helena, drop column if exists situacao_helena,
  drop column if exists id_responsavel, drop column if exists responsavel_nome, drop column if exists ids_etiquetas,
  drop column if exists etiquetas, drop column if exists id_sessao_helena, drop column if exists numero_canal;
commit;
