-- =============================================================================
-- desfazer_008.sql
-- Tira o que a 008 criou: a tabela de versões dos prompts dos produtos (agentesia_produto_versoes).
-- APAGA o histórico de versões (os produtos e os agentes no ar continuam iguais). Pode rodar de novo.
-- =============================================================================

begin;

drop table if exists public.agentesia_produto_versoes cascade;

commit;
