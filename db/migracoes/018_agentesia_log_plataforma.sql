-- =============================================================================
-- 018_agentesia_log_plataforma.sql
-- Log da plataforma (Superadmin › Logs): o histórico do que acontece de ADMINISTRATIVO na plataforma, sem relação
-- com a conversa dos leads. Ex.: produto ativado/pausado/arquivado, IA ligada para todos, escritório liberado ou
-- bloqueado, recarga confirmada, follow-up ligado, catálogo publicado, usuário admin criado.
--
-- Quem grava: app/gestao/log_plataforma.py (registrar() e o decorador @registrado nas rotas). Quem lê:
-- app/gestao/rotas_log_plataforma.py (GET /api/admin/logs, /resumo, /exportar.csv), só a equipe LawChat.
--
--   agentesia_log_plataforma   uma linha por ação: quando, conta (pode ser nula: ação da plataforma toda),
--                              quem fez e o papel, a função (código + rótulo), uma referência curta, o payload e o
--                              resultado em JSON (já sem token, senha, chave, CPF e telefone), status ok/erro, o erro
--                              e quanto tempo levou.
--
-- Não muda nem apaga nada que já existe. Pode rodar mais de uma vez e com o servidor no ar. Depende da 001 e da 002.
-- Sem esta migração o servidor segue normal: o log só não é gravado (a ação principal nunca cai por causa dele).
-- Para desfazer: desfazer_018.sql.
-- =============================================================================

begin;

create table if not exists public.agentesia_log_plataforma (
  id              uuid primary key default gen_random_uuid(),
  criado_em       timestamptz not null default now(),
  id_escritorio   uuid references public.agentesia_escritorios(id) on delete set null,
  id_usuario      uuid references public.agentesia_usuarios(id) on delete set null,
  papel           text,
  funcao          text not null,
  rotulo          text not null,
  referencia      text,
  payload         jsonb,
  resultado       jsonb,
  status          text not null default 'ok' check (status in ('ok', 'erro')),
  erro            text,
  duracao_ms      integer check (duracao_ms is null or duracao_ms >= 0)
);
alter table public.agentesia_log_plataforma enable row level security;

create index if not exists agentesia_log_plataforma_data
  on public.agentesia_log_plataforma (criado_em desc);
create index if not exists agentesia_log_plataforma_escritorio
  on public.agentesia_log_plataforma (id_escritorio, criado_em desc);
create index if not exists agentesia_log_plataforma_funcao
  on public.agentesia_log_plataforma (funcao, criado_em desc);

commit;
