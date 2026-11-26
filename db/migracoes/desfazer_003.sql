-- =============================================================================
-- desfazer_003.sql
-- Remove o que a 003 criou. Mantém a 001 e a 002 como estavam.
-- Os documentos virtuais (faq/objecoes) são apagados: FAQ e objeções continuam na config do agente.
-- =============================================================================

begin;

drop table if exists public.agentesia_conhecimento_lacunas cascade;

drop index if exists public.agentesia_documento_trechos_hash;
alter table if exists public.agentesia_documento_trechos drop constraint if exists agentesia_documento_trechos_fonte_check;
alter table if exists public.agentesia_documento_trechos
  drop column if exists id_escritorio,
  drop column if exists papeis,
  drop column if exists titulo,
  drop column if exists fonte,
  drop column if exists hash,
  drop column if exists modelo,
  drop column if exists dimensoes;

delete from public.agentesia_documentos where tipo in ('faq', 'objecoes');
drop index if exists public.agentesia_documentos_virtual_unico;
alter table if exists public.agentesia_documentos drop constraint if exists agentesia_documentos_tipo_check;
alter table if exists public.agentesia_documentos add constraint agentesia_documentos_tipo_check
  check (tipo in ('arquivo', 'texto'));
alter table if exists public.agentesia_documentos drop column if exists papeis;

commit;
