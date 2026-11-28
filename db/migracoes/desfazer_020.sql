-- Desfaz a 020: tira as vozes prontas e as colunas novas das gravações. Os itens que já entraram na biblioteca dos
-- escritórios continuam lá (com o link do arquivo da LawChat); os arquivos das vozes no armazenamento não são apagados.
begin;
alter table public.agentesia_roteiro_partes drop column if exists aviso_pronto;
alter table public.agentesia_roteiro_partes drop column if exists texto_pronto;
drop index if exists public.agentesia_roteiro_gravacoes_voz;
alter table public.agentesia_roteiro_gravacoes drop column if exists id_voz;
alter table public.agentesia_roteiro_gravacoes drop column if exists origem;
drop table if exists public.agentesia_voz_pronta_aceites;
drop table if exists public.agentesia_voz_pronta_audios;
drop table if exists public.agentesia_vozes_prontas;
commit;
