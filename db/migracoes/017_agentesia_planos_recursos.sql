-- =============================================================================
-- 017_agentesia_planos_recursos.sql
-- Catálogo comercial de planos (tela Admin › Planos): o que cada plano inclui e os adicionais vendidos à parte.
--
-- A) agentesia_planos ganha: preço anual (pago 1x; vazio = 12 meses com o desconto anual), "sob proposta",
--    usuários, números de WhatsApp e Instagram, se cria agentes, se a IA vem inclusa, selo (emoji) e ícone.
--    O bônus mensal de IA (bonus_mensal_brl) já existia e é o "bônus token" da tela.
-- B) agentesia_adicionais: itens sempre mensais (ativação da IA, usuário, canal, chatbot de automação).
-- C) Carga inicial dos 5 planos e 4 adicionais do catálogo atual, só se o código ainda não existe
--    (não sobrescreve nada que a equipe já tenha mudado).
--
-- Só acrescenta. Pode rodar mais de uma vez e com o servidor no ar. Depende da 007. Para desfazer: desfazer_017.sql.
-- =============================================================================

begin;

alter table public.agentesia_planos
  add column if not exists preco_anual_brl   numeric(12,2) check (preco_anual_brl is null or preco_anual_brl >= 0),
  add column if not exists sob_proposta      boolean not null default false,
  add column if not exists usuarios          int not null default 1 check (usuarios between 0 and 9999),
  add column if not exists canais_whatsapp   int not null default 1 check (canais_whatsapp between 0 and 9999),
  add column if not exists canais_instagram  int not null default 0 check (canais_instagram between 0 and 9999),
  add column if not exists cria_agentes      boolean not null default false,
  add column if not exists ia_inclusa        boolean not null default false,
  add column if not exists selo              text,
  add column if not exists icone             text;

create table if not exists public.agentesia_adicionais (
  id                 uuid primary key default gen_random_uuid(),
  codigo             text not null unique check (codigo ~ '^[a-z0-9_-]{2,40}$'),
  nome               text not null,
  descricao          text,
  preco_mensal_brl   numeric(12,2) not null default 0 check (preco_mensal_brl >= 0),
  icone              text,
  ativo              boolean not null default true,
  ordem              int not null default 0,
  criado_em          timestamptz not null default now(),
  atualizado_em      timestamptz not null default now()
);
alter table public.agentesia_adicionais enable row level security;

insert into public.agentesia_planos (codigo, nome, preco_mensal_brl, bonus_mensal_brl, usuarios, canais_whatsapp, canais_instagram,
                                     cria_agentes, ia_inclusa, sob_proposta, selo, icone, ordem)
values ('start',      'Bronze',     697.90,    0, 3,  1,  1, false, false, false, '🥉', 'raio',    10),
       ('pro',        'Prata',     1297.90,   50, 3,  1,  1, true,  false, false, '🥈', 'brilho',  20),
       ('pro_plus',   'Prata Plus',1297.90,   50, 3,  1,  1, true,  false, false, '🥈', 'raio',    30),
       ('master',     'Ouro',      1795.80,  100, 5,  2,  1, true,  true,  false, '🥇', 'coroa',   40),
       ('enterprise', 'Diamante',     0,       0, 99, 99, 99, true,  true,  true,  '💎', 'estrela', 50)
on conflict (codigo) do nothing;

insert into public.agentesia_adicionais (codigo, nome, preco_mensal_brl, icone, ordem)
values ('ativacao_ia', 'Ativação dos Agentes Inteligentes', 497.90, 'robo',     10),
       ('usuario',     'Usuário adicional',                  49.90, 'usuario',  20),
       ('canal',       'Canal adicional (WhatsApp)',        249.90, 'canal',    30),
       ('automacao',   'Chatbot de Automação',              297.90, 'automacao',40)
on conflict (codigo) do nothing;

commit;
