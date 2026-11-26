-- =============================================================================
-- desfazer_002.sql
-- Remove o que a 002 criou. Mantém a 001 (núcleo) como estava.
-- =============================================================================

begin;

drop table if exists public.agentesia_lead_resumo cascade;
drop table if exists public.agentesia_acoes cascade;
drop table if exists public.agentesia_notificacoes cascade;
drop table if exists public.agentesia_followups cascade;
drop table if exists public.agentesia_documento_trechos cascade;
alter table if exists public.agentesia_agentes drop column if exists id_produto_ativado;
alter table if exists public.agentesia_agente_etapas drop constraint if exists agentesia_agente_etapas_temperatura_check;
update public.agentesia_agente_etapas set temperatura = least(temperatura, 1);
alter table if exists public.agentesia_agente_etapas add constraint agentesia_agente_etapas_temperatura_check check (temperatura between 0 and 1);
drop table if exists public.agentesia_biblioteca_midia cascade;
drop table if exists public.agentesia_produtos_ativados cascade;
drop table if exists public.agentesia_frases_troca cascade;
drop table if exists public.agentesia_biblioteca_agentes cascade;
drop table if exists public.agentesia_biblioteca_produtos cascade;
drop table if exists public.agentesia_documentos cascade;
drop index if exists public.agentesia_leads_esperando;
alter table if exists public.agentesia_leads drop column if exists responder_apos, drop column if exists processando_ate;
alter table if exists public.agentesia_eventos_recebidos drop constraint if exists agentesia_eventos_recebidos_origem_check;
delete from public.agentesia_eventos_recebidos where origem = 'zapsign';
alter table if exists public.agentesia_eventos_recebidos add constraint agentesia_eventos_recebidos_origem_check
  check (origem in ('helena', 'laboratorio'));
drop table if exists public.agentesia_contratos cascade;
drop table if exists public.agentesia_crm_cards cascade;
drop table if exists public.agentesia_alteracoes cascade;
drop table if exists public.agentesia_integracoes cascade;

drop index if exists public.agentesia_eventos_abertos;
alter table if exists public.agentesia_eventos
  drop column if exists resolvido_por,
  drop column if exists resolvido_em;

alter table if exists public.agentesia_agentes drop column if exists id_modelo;
drop table if exists public.agentesia_modelos_agente cascade;
alter table if exists public.agentesia_escritorios drop column if exists id_responsavel;
drop table if exists public.agentesia_usuarios cascade;

alter table if exists public.agentesia_escritorios drop column if exists situacao;
alter table if exists public.agentesia_agentes drop column if exists numeros_teste;
alter table if exists public.agentesia_agente_etapas drop column if exists instrucao_travada;

commit;
