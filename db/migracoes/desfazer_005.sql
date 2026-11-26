-- =============================================================================
-- desfazer_005.sql
-- Tira a marca de leitura de mídia pendente (o código volta a só esperar a leitura do próprio processo).
-- Pode rodar de novo.
-- =============================================================================

begin;

alter table if exists public.agentesia_mensagens drop column if exists midia_pendente_desde;

commit;
