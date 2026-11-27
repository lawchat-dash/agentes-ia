-- Desfaz a 019: tira as tabelas do roteiro de gravação e as colunas novas (os arquivos continuam na biblioteca).
begin;
drop table if exists public.agentesia_roteiro_gravacoes;
drop table if exists public.agentesia_roteiro_partes;
drop index if exists public.agentesia_biblioteca_midia_pasta;
alter table public.agentesia_biblioteca_midia drop column if exists pasta;
alter table public.agentesia_planos drop column if exists midia;
alter table public.agentesia_biblioteca_produtos drop column if exists roteiro_orientacoes;
commit;
