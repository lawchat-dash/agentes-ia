-- =============================================================================
-- desfazer_009.sql
-- Tira o que a 009 criou: a tabela de roteiros de áudio (agentesia_roteiros).
-- APAGA os roteiros (os áudios já gravados continuam na biblioteca de mídia). Pode rodar de novo.
-- =============================================================================

begin;

drop table if exists public.agentesia_roteiros cascade;

commit;
