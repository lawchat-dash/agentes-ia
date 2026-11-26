-- =============================================================================
-- 004_agentesia_canal_liberado.sql
-- Produto na lixeira SOLTA o número de WhatsApp (decisão do dono): outro produto pode usar o canal.
--   * agentesia_agentes.id_canal passa a aceitar null (agente sem número = "precisa ativar");
--     o unique continua (vários null são permitidos; dois agentes no mesmo número, não);
--   * id_canal_anterior: o número que o agente usava antes de ser solto (só histórico, não prende nada);
--   * canal_liberado_em: quando o número foi solto.
-- O motor acha o agente pelo canal (agente_do_canal): número solto = nenhum agente responde nele.
--
-- Só mexe em tabelas agentesia_*. Depende da 001/002. Para desfazer: desfazer_004.sql.
-- =============================================================================

begin;

alter table public.agentesia_agentes alter column id_canal drop not null;

alter table public.agentesia_agentes
  add column if not exists id_canal_anterior uuid references public.agentesia_canais(id) on delete set null,
  add column if not exists canal_liberado_em timestamptz;

commit;
