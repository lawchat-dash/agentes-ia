-- =============================================================================
-- desfazer_007.sql
-- Tira o que a 007 criou: cobrança em R$ (cotação e markup, planos, carteiras, livro de movimentos, recargas, eventos
-- de pagamento, assinaturas) e as colunas novas de agentesia_chamadas_ia. As chamadas continuam (com o custo em US$).
-- APAGA o livro e os saldos: exporte antes se houver dinheiro de cliente lançado. Pode rodar de novo.
-- =============================================================================

begin;

drop trigger if exists agentesia_chamadas_ia_precificar on public.agentesia_chamadas_ia;
drop function if exists public.agentesia_precificar_chamada();
drop function if exists public.agentesia_debitar_consumo(uuid, int);
drop function if exists public.agentesia_renovar_bonus(uuid, text);
drop function if exists public.agentesia_confirmar_recarga(uuid, uuid, text, jsonb);
drop function if exists public.agentesia_estornar_recarga(uuid, uuid, text);
drop view if exists public.agentesia_v_carteira_conferencia;

drop index if exists public.agentesia_chamadas_ia_escritorio_data;
drop index if exists public.agentesia_chamadas_ia_turno;
drop index if exists public.agentesia_chamadas_ia_lead;
drop index if exists public.agentesia_chamadas_ia_pendentes;
alter table if exists public.agentesia_chamadas_ia
  drop constraint if exists agentesia_chamadas_ia_cobranca,
  drop column if exists tokens_cache,
  drop column if exists id_lead,
  drop column if exists id_agente,
  drop column if exists codigo_etapa,
  drop column if exists origem,
  drop column if exists sem_preco,
  drop column if exists cotacao,
  drop column if exists markup,
  drop column if exists custo_brl_real,
  drop column if exists custo_brl,
  drop column if exists cobranca,
  drop column if exists id_movimento;

drop table if exists public.agentesia_pagamento_eventos cascade;
drop table if exists public.agentesia_assinaturas cascade;
drop table if exists public.agentesia_recargas cascade;
drop table if exists public.agentesia_carteira_movimentos cascade;
drop function if exists public.agentesia_carteira_lancar(uuid, text, numeric, text, text, uuid, jsonb, uuid);
drop function if exists public.agentesia_livro_imutavel();
drop table if exists public.agentesia_carteiras cascade;
drop function if exists public.agentesia_carteira_conferir();
drop table if exists public.agentesia_planos cascade;
drop function if exists public.agentesia_cobranca_vigente();
drop table if exists public.agentesia_cobranca_config cascade;

commit;
