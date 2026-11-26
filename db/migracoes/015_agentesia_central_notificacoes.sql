-- =============================================================================
-- 015_agentesia_central_notificacoes.sql
-- Central de notificações do sino do painel (app/gestao/rotas_central_notificacoes.py).
--
-- As notificações NÃO são gravadas numa tabela nova: saem das fontes que já existem (troca de etapa para o Closer,
-- eventos de pausa da IA, IA desligada pela equipe, contrato gerado e assinado). Aqui só fica o "lido":
--
--   agentesia_notificacoes_leitura   uma linha por usuário e escritório com a data da última leitura (lido_ate).
--                                    Tudo o que aconteceu depois dela é "não lido".
--
-- E dois índices para a consulta do sino (a cada ~45 s) não varrer as tabelas:
--   agentesia_contratos (id_escritorio, gerado_em)           contratos enviados
--   agentesia_alteracoes (id_escritorio, criado_em) parcial  IA desligada pela equipe
--
-- Não muda nem apaga nada que já existe. Pode rodar mais de uma vez e com o servidor no ar. Depende da 001 e da 002.
-- Para desfazer: desfazer_015.sql.
-- =============================================================================

begin;

create table if not exists public.agentesia_notificacoes_leitura (
  id_usuario      uuid not null references public.agentesia_usuarios(id) on delete cascade,
  id_escritorio   uuid not null references public.agentesia_escritorios(id) on delete cascade,
  lido_ate        timestamptz not null default now(),
  atualizado_em   timestamptz not null default now(),
  primary key (id_usuario, id_escritorio)
);
alter table public.agentesia_notificacoes_leitura enable row level security;

drop trigger if exists agentesia_notificacoes_leitura_atualizado_em on public.agentesia_notificacoes_leitura;
create trigger agentesia_notificacoes_leitura_atualizado_em before update on public.agentesia_notificacoes_leitura
  for each row execute function public.agentesia_tocar_atualizado_em();

create index if not exists agentesia_contratos_escritorio_gerado
  on public.agentesia_contratos (id_escritorio, gerado_em desc) where gerado_em is not null;
create index if not exists agentesia_alteracoes_desligou_ia
  on public.agentesia_alteracoes (id_escritorio, criado_em desc) where acao = 'desligou_ia';

commit;
