-- =============================================================================
-- 013_agentesia_relatorios_crm.sql
-- Dashboard pelos cards do CRM (como o dashboard comercial original): o espelho dos cards ganha o que os filtros
-- precisam. Tudo vem da listagem de cards da plataforma (GET crm/v2/panel/card), gravado pela varredura de fundo
-- (app/gestao/reconciliar_crm.py, agora em TODOS os painéis da conta) e pelo aviso de card movido (webhook).
--
--   titulo_painel        nome do painel (panelTitle)                         -> filtro PAINEL CRM
--   fase_helena          fase da coluna na plataforma (stepPhase)
--   situacao_helena      status do card (status)
--   id_responsavel       usuário responsável (responsibleUserId)             -> filtro RESPONSÁVEL
--   responsavel_nome     nome do responsável (responsibleUser)
--   ids_etiquetas        etiquetas do card (tagIds)                          -> filtro TAGS
--   etiquetas            nomes das etiquetas (lista de etiquetas da conta, lida uma vez por varredura)
--   id_sessao_helena     atendimento ligado ao card (sessionId)
--   numero_canal         número de WhatsApp (canal) do lead ligado ao card   -> filtro NÚMERO
--
-- Não muda nem apaga nada que já existe (só acrescenta colunas e índices). Pode rodar mais de uma vez e com o
-- servidor no ar. Depende da 012. Para desfazer: desfazer_013.sql.
-- =============================================================================

begin;

alter table public.agentesia_crm_espelho
  add column if not exists titulo_painel     text,
  add column if not exists fase_helena       text,
  add column if not exists situacao_helena   text,
  add column if not exists id_responsavel    text,
  add column if not exists responsavel_nome  text,
  add column if not exists ids_etiquetas     text[] not null default '{}',
  add column if not exists etiquetas         text[] not null default '{}',
  add column if not exists id_sessao_helena  text,
  add column if not exists numero_canal      text;

create index if not exists agentesia_crm_espelho_escritorio_atualizado
  on public.agentesia_crm_espelho (id_escritorio, atualizado_em_helena);
create index if not exists agentesia_crm_espelho_escritorio_painel
  on public.agentesia_crm_espelho (id_escritorio, id_painel_helena);

-- A próxima varredura relê tudo (importação completa) para preencher as colunas novas nos cards antigos.
update public.agentesia_crm_varredura set importar_pedido_em = coalesce(importar_pedido_em, now());

commit;
