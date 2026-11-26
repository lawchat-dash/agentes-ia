-- =============================================================================
-- 012_agentesia_relatorios.sql
-- Relatórios do painel (Dashboard e Rastreamento de campanhas) e o espelho leve do CRM.
--
-- A) Índices das consultas agregadas dos relatórios (tudo por escritório e período):
--   agentesia_leads      leads com origem (anúncio/UTM) de um escritório, por data de entrada
--   agentesia_contratos  contratos assinados de um escritório, por data da assinatura
--   (leads por escritório/data, turnos, mensagens e chamadas da IA por escritório/data já têm índice: 007, 010, 011)
--
-- B) agentesia_crm_espelho: cada card do painel do CRM da conta, como estava na última varredura (inclusive os
--    cards antigos, de antes da integração, e os que não têm lead nosso). Quem grava é a varredura de fundo
--    (app/gestao/reconciliar_crm.py); a tela só lê. Nenhum dado do card sai daqui para a IA.
--
-- C) agentesia_crm_varredura: uma linha por escritório com o ponto da última varredura incremental, se a importação
--    única dos cards antigos já rodou e o último erro.
--
-- Não muda nenhuma tabela ou coluna que já existe. Pode rodar mais de uma vez (if not exists) e com o servidor no ar.
-- Depende da 001, 002 e 006. Para desfazer: desfazer_012.sql.
-- =============================================================================

begin;

-- A) índices
create index if not exists agentesia_leads_escritorio_origem
  on public.agentesia_leads (id_escritorio, criado_em) where origem <> '{}'::jsonb;
create index if not exists agentesia_contratos_escritorio_assinado
  on public.agentesia_contratos (id_escritorio, assinado_em) where situacao = 'assinado';

-- B) espelho dos cards do CRM
create table if not exists public.agentesia_crm_espelho (
  id                    uuid primary key default gen_random_uuid(),
  id_escritorio         uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_card_helena        text not null,
  id_painel_helena      text,
  id_etapa_helena       text,
  etapa_titulo          text,                 -- nome da coluna no CRM
  fase                  text,                 -- sdr | closer | analise | contratos | assinatura | assinado |
                                              -- desqualificado | nao_assinou | outra (pelo nome da coluna)
  id_contato_helena     text,
  id_lead               uuid references public.agentesia_leads(id) on delete set null,
  titulo                text,
  valor                 numeric(14,2),
  arquivado             boolean not null default false,
  criado_em_helena      timestamptz,
  atualizado_em_helena  timestamptz,
  visto_em              timestamptz not null default now(),
  unique (id_escritorio, id_card_helena)
);
create index if not exists agentesia_crm_espelho_escritorio_criado
  on public.agentesia_crm_espelho (id_escritorio, criado_em_helena);
create index if not exists agentesia_crm_espelho_lead
  on public.agentesia_crm_espelho (id_lead) where id_lead is not null;
alter table public.agentesia_crm_espelho enable row level security;

-- C) ponto da varredura por escritório
create table if not exists public.agentesia_crm_varredura (
  id_escritorio         uuid primary key references public.agentesia_escritorios(id) on delete cascade,
  cursor_atualizado     timestamptz,          -- maior updatedAt de card já visto (a próxima varredura para antes dele)
  importado_em          timestamptz,          -- importação única dos cards antigos concluída
  importar_pedido_em    timestamptz,          -- alguém pediu (de novo) a importação completa pelo painel
  ultima_em             timestamptz,
  cards_vistos          int not null default 0,
  cards_mudados         int not null default 0,
  erro                  text,
  atualizado_em         timestamptz not null default now()
);
alter table public.agentesia_crm_varredura enable row level security;

commit;
