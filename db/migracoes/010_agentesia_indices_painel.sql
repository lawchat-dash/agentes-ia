-- =============================================================================
-- 010_agentesia_indices_painel.sql
-- Índices para as telas do painel (Início, Conversas, Rastro, Contas). Só índices: nenhuma tabela ou coluna muda.
--
-- Sem eles o Postgres lê a tabela inteira (seq scan) a cada abertura do Início e da lista de Conversas:
--   agentesia_leads      por escritório (lista de Conversas, resumo e métricas do Início) e por agente (funil, ranking)
--   agentesia_mensagens  por escritório e data (métricas do Início, "respostas da IA em 24 h")
--   agentesia_eventos    por lead (Conversa aberta, repetida a cada 8 s)
--   agentesia_turnos     com erro nas últimas 24 h (resumo do Início)
--   agentesia_eventos_recebidos  último webhook do escritório (resumo do Início)
--   agentesia_followups  por escritório (métricas do Início)
--   agentesia_contratos  por lead (assinados no funil, nas métricas e no Rastro)
--
-- Pode rodar mais de uma vez (if not exists) e com o servidor no ar. Depende da 001 e da 002.
-- Para desfazer: desfazer_010.sql.
-- =============================================================================

begin;

create index if not exists agentesia_leads_escritorio_recentes
  on public.agentesia_leads (id_escritorio, (coalesce(ultima_mensagem_lead_em, criado_em)) desc);
create index if not exists agentesia_leads_escritorio_criado
  on public.agentesia_leads (id_escritorio, criado_em);
create index if not exists agentesia_leads_agente_criado
  on public.agentesia_leads (id_agente, criado_em);

create index if not exists agentesia_mensagens_escritorio_enviada
  on public.agentesia_mensagens (id_escritorio, enviada_em);
create index if not exists agentesia_mensagens_escritorio_ia
  on public.agentesia_mensagens (id_escritorio, registrada_em) where autor = 'ia';

create index if not exists agentesia_eventos_lead
  on public.agentesia_eventos (id_lead, criado_em desc) where id_lead is not null;

create index if not exists agentesia_turnos_escritorio_erro
  on public.agentesia_turnos (id_escritorio, iniciado_em) where situacao = 'erro';

create index if not exists agentesia_eventos_recebidos_escritorio
  on public.agentesia_eventos_recebidos (id_escritorio, recebido_em desc);

create index if not exists agentesia_followups_escritorio
  on public.agentesia_followups (id_escritorio);

create index if not exists agentesia_contratos_lead
  on public.agentesia_contratos (id_lead);

commit;
