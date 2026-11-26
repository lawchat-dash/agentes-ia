-- =============================================================================
-- 011_agentesia_indices_execucoes.sql
-- Índices da tela Superadmin > Execuções (cada turno da IA, mais novos primeiro, atualizando a cada 10 s).
-- Só índices: nenhuma tabela ou coluna muda.
--
-- Sem eles a lista lia agentesia_turnos inteira e ordenava a cada atualização:
--   agentesia_turnos  todos os escritórios, por iniciado_em desc (lista sem filtro de conta)
--   agentesia_turnos  de uma conta, por iniciado_em desc (filtro "conta")
-- (por lead já existe agentesia_turnos_lead; custo por turno usa agentesia_chamadas_ia_turno, da 007)
--
-- Pode rodar mais de uma vez (if not exists) e com o servidor no ar. Depende da 001.
-- Para desfazer: desfazer_011.sql.
-- =============================================================================

begin;

create index if not exists agentesia_turnos_recentes
  on public.agentesia_turnos (iniciado_em desc);
create index if not exists agentesia_turnos_escritorio_recentes
  on public.agentesia_turnos (id_escritorio, iniciado_em desc);

commit;
