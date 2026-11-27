-- =============================================================================
-- 016_agentesia_agente_arquivado.sql
-- Agente arquivado: sai da lista principal de "Meus agentes" (fica em "Arquivados") e para de atender.
--
-- Só amplia a checagem de agentesia_agentes.situacao: passa a aceitar 'arquivado' além de 'ativo' e 'pausado'.
-- O motor só responde com situacao = 'ativo' (app/pipeline.py, follow-up e vigia), então arquivado = não atende.
-- O número continua com o agente (diferente da lixeira, que solta o número). Restaurar volta para 'pausado'.
--
-- Não muda nem apaga dado nenhum. Pode rodar mais de uma vez e com o servidor no ar. Depende da 001.
-- Para desfazer: desfazer_016.sql.
-- =============================================================================

begin;

alter table public.agentesia_agentes drop constraint if exists agentesia_agentes_situacao_check;
alter table public.agentesia_agentes
  add constraint agentesia_agentes_situacao_check check (situacao in ('ativo', 'pausado', 'arquivado'));

commit;
