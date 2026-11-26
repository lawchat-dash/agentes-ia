-- =============================================================================
-- 007_agentesia_cobranca.sql
-- Cobrança por consumo de IA em R$, no modelo do Weaver (ver docs/COBRANCA_TOKENS.md):
--   A) agentesia_cobranca_config: cotação US$→R$ e markup (multiplicador) globais, com histórico. A linha mais recente
--      com vigente_desde <= now() é a que vale. Começa com 5,50 e 1,00 (o nó de tokens do n8n);
--   B) agentesia_planos: preço mensal e bônus mensal em R$ (renovado todo mês; bonus_acumula decide se sobra passa);
--   C) agentesia_carteiras: uma por escritório. saldo_brl (recargas, bônus manual, ajustes) e bonus_brl (bônus do plano
--      do mês) só mudam por agentesia_carteira_lancar, que grava o movimento no livro na mesma transação. Modo
--      'pre_pago' pausa a IA com saldo + bônus <= 0; 'so_registrar' só registra (escritórios que já existiam);
--   D) agentesia_carteira_movimentos: o LIVRO. Cada linha: tipo, valor, parte no saldo e parte no bônus, saldo e bônus
--      depois, chave_unica (idempotência), quem e por quê. Não pode ser alterado. Soma do livro = carteira;
--   E) agentesia_chamadas_ia ganha tokens_cache, lead, agente, etapa, origem, cotação, markup, custo em R$ (real e
--      cobrado), situação da cobrança e o movimento que a debitou. Um gatilho calcula o R$ na hora do insert, então
--      todo ponto que grava chamada já sai com o valor certo. Chamadas antigas ficam 'isenta' (não são cobradas);
--   F) agentesia_debitar_consumo: débito em lote, atômico, com "for update skip locked" (dois servidores nunca debitam
--      a mesma chamada; cada chamada é debitada uma vez só);
--   G) agentesia_recargas (pedido de recarga, Pix/boleto, gateway manual ou asaas), agentesia_pagamento_eventos
--      (webhooks recebidos, idempotentes) e agentesia_assinaturas (plano com cobrança recorrente, previsto);
--      agentesia_confirmar_recarga credita uma vez só;
--   H) agentesia_renovar_bonus: bônus do plano do mês, idempotente por mês;
--   I) agentesia_v_carteira_conferencia: carteira × soma do livro (diferença tem de ser zero).
--
-- O código funciona sem esta migração (grava as chamadas como antes e não bloqueia por saldo): pode aplicar com o
-- servidor no ar. Pode rodar mais de uma vez. Só mexe em tabelas agentesia_*. Depende da 001 e da 002.
-- Para desfazer: desfazer_007.sql.
-- =============================================================================

begin;

-- A) Cotação e markup globais, com histórico ------------------------------------------------------------------------
create table if not exists public.agentesia_cobranca_config (
  id              uuid primary key default gen_random_uuid(),
  cotacao_usd_brl numeric(10,4) not null check (cotacao_usd_brl > 0 and cotacao_usd_brl < 100),
  markup          numeric(10,4) not null check (markup > 0 and markup <= 20),   -- 1,00 = cobra o custo; 2,00 = o dobro
  vigente_desde   timestamptz not null default now(),
  motivo          text,
  id_usuario      uuid references public.agentesia_usuarios(id) on delete set null,
  criado_em       timestamptz not null default now()
);
create index if not exists agentesia_cobranca_config_vigente on public.agentesia_cobranca_config (vigente_desde desc, criado_em desc);
insert into public.agentesia_cobranca_config (cotacao_usd_brl, markup, motivo)
select 5.50, 1.00, 'valor inicial (nó de cálculo de tokens do n8n)'
where not exists (select 1 from public.agentesia_cobranca_config);
alter table public.agentesia_cobranca_config enable row level security;

create or replace function public.agentesia_cobranca_vigente()
returns table (cotacao_usd_brl numeric, markup numeric, vigente_desde timestamptz)
language sql stable as $$
  select c.cotacao_usd_brl, c.markup, c.vigente_desde from public.agentesia_cobranca_config c
  where c.vigente_desde <= now() order by c.vigente_desde desc, c.criado_em desc limit 1
$$;

-- B) Planos -----------------------------------------------------------------------------------------------------------
create table if not exists public.agentesia_planos (
  id                 uuid primary key default gen_random_uuid(),
  codigo             text not null unique check (codigo ~ '^[a-z0-9_-]{2,40}$'),
  nome               text not null,
  descricao          text,
  preco_mensal_brl   numeric(12,2) not null default 0 check (preco_mensal_brl >= 0),
  bonus_mensal_brl   numeric(12,2) not null default 0 check (bonus_mensal_brl >= 0),
  bonus_acumula      boolean not null default false,          -- false: o que sobra do bônus expira na virada do mês
  ativo              boolean not null default true,
  ordem              int not null default 0,
  criado_em          timestamptz not null default now(),
  atualizado_em      timestamptz not null default now()
);
alter table public.agentesia_planos enable row level security;
drop trigger if exists agentesia_planos_atualizado_em on public.agentesia_planos;
create trigger agentesia_planos_atualizado_em before update on public.agentesia_planos
  for each row execute function public.agentesia_tocar_atualizado_em();

-- C) Carteiras --------------------------------------------------------------------------------------------------------
create table if not exists public.agentesia_carteiras (
  id_escritorio      uuid primary key references public.agentesia_escritorios(id) on delete cascade,
  id_plano           uuid references public.agentesia_planos(id) on delete set null,
  modo               text not null default 'so_registrar' check (modo in ('pre_pago', 'so_registrar')),
  saldo_brl          numeric(16,6) not null default 0,         -- recargas, bônus manual e ajustes (pode ficar negativo)
  bonus_brl          numeric(16,6) not null default 0 check (bonus_brl >= 0),
  bonus_mes          text,                                     -- 'AAAA-MM' do último bônus do plano creditado
  bonus_do_mes_brl   numeric(16,6) not null default 0,         -- quanto de bônus o mês começou (base do aviso de 80%)
  markup             numeric(10,4) check (markup is null or (markup > 0 and markup <= 20)),  -- só este escritório
  pausado_por_saldo  boolean not null default false,
  pausado_em         timestamptz,
  religado_em        timestamptz,
  avisos             jsonb not null default '{}'::jsonb,       -- avisos já mandados: {"bonus_80": "2026-11", ...}
  criado_em          timestamptz not null default now(),
  atualizado_em      timestamptz not null default now()
);
alter table public.agentesia_carteiras enable row level security;
drop trigger if exists agentesia_carteiras_atualizado_em on public.agentesia_carteiras;
create trigger agentesia_carteiras_atualizado_em before update on public.agentesia_carteiras
  for each row execute function public.agentesia_tocar_atualizado_em();

-- Escritórios que já existem entram em "só registrar": nada para de responder ao aplicar a migração.
insert into public.agentesia_carteiras (id_escritorio, modo)
select e.id, 'so_registrar' from public.agentesia_escritorios e on conflict (id_escritorio) do nothing;

-- D) Livro de movimentos ----------------------------------------------------------------------------------------------
create table if not exists public.agentesia_carteira_movimentos (
  id              uuid primary key default gen_random_uuid(),
  id_escritorio   uuid not null references public.agentesia_carteiras(id_escritorio) on delete cascade,
  tipo            text not null check (tipo in ('recarga', 'bonus_plano', 'bonus_manual', 'consumo', 'ajuste',
                                                'expira_bonus', 'estorno')),
  valor_brl       numeric(16,6) not null check (valor_brl <> 0),
  parte_saldo     numeric(16,6) not null default 0,
  parte_bonus     numeric(16,6) not null default 0,
  saldo_depois    numeric(16,6) not null,
  bonus_depois    numeric(16,6) not null,
  chave_unica     text unique,
  motivo          text,
  id_usuario      uuid references public.agentesia_usuarios(id) on delete set null,
  id_recarga      uuid,
  detalhe         jsonb not null default '{}'::jsonb,
  criado_em       timestamptz not null default now(),
  check (valor_brl = parte_saldo + parte_bonus)
);
create index if not exists agentesia_carteira_movimentos_escritorio
  on public.agentesia_carteira_movimentos (id_escritorio, criado_em desc);
alter table public.agentesia_carteira_movimentos enable row level security;

create or replace function public.agentesia_livro_imutavel() returns trigger language plpgsql as $$
begin
  raise exception 'o livro da carteira não pode ser alterado: lance um ajuste';
end $$;
drop trigger if exists agentesia_carteira_movimentos_imutavel on public.agentesia_carteira_movimentos;
create trigger agentesia_carteira_movimentos_imutavel before update on public.agentesia_carteira_movimentos
  for each row execute function public.agentesia_livro_imutavel();

-- Saldo e bônus só mudam pelo lançamento; a pausa por saldo acompanha (só no pré-pago).
create or replace function public.agentesia_carteira_conferir() returns trigger language plpgsql as $$
begin
  if (new.saldo_brl is distinct from old.saldo_brl or new.bonus_brl is distinct from old.bonus_brl)
     and coalesce(current_setting('agentesia.lancando', true), '') <> 'sim' then
    raise exception 'saldo e bônus só mudam por agentesia_carteira_lancar (o livro)';
  end if;
  if new.modo = 'pre_pago' and new.saldo_brl + new.bonus_brl <= 0 then
    if not new.pausado_por_saldo then
      new.pausado_por_saldo := true;
      new.pausado_em := now();
    end if;
  elsif new.pausado_por_saldo then
    new.pausado_por_saldo := false;
    new.religado_em := now();
  end if;
  return new;
end $$;
drop trigger if exists agentesia_carteiras_conferir on public.agentesia_carteiras;
create trigger agentesia_carteiras_conferir before update on public.agentesia_carteiras
  for each row execute function public.agentesia_carteira_conferir();

-- Um lançamento: trava a carteira, grava o movimento e atualiza saldo/bônus na mesma transação.
-- Devolve o movimento, ou null quando a chave_unica já tinha sido usada (nada muda: idempotente).
create or replace function public.agentesia_carteira_lancar(
  p_id_escritorio uuid, p_tipo text, p_valor numeric, p_chave text default null, p_motivo text default null,
  p_id_usuario uuid default null, p_detalhe jsonb default '{}'::jsonb, p_id_recarga uuid default null)
returns public.agentesia_carteira_movimentos language plpgsql as $$
declare
  c public.agentesia_carteiras;
  m public.agentesia_carteira_movimentos;
  pb numeric := 0;
  ps numeric := 0;
  v numeric := round(p_valor, 6);
begin
  if v is null or v = 0 then
    raise exception 'lançamento sem valor';
  end if;
  if p_tipo in ('recarga', 'bonus_plano', 'bonus_manual') and v < 0 then
    raise exception 'lançamento de % precisa ser positivo', p_tipo;
  end if;
  if p_tipo in ('consumo', 'expira_bonus', 'estorno') and v > 0 then
    raise exception 'lançamento de % precisa ser negativo', p_tipo;
  end if;
  if p_chave is not null and exists (select 1 from public.agentesia_carteira_movimentos where chave_unica = p_chave) then
    return null;
  end if;
  insert into public.agentesia_carteiras (id_escritorio) values (p_id_escritorio) on conflict (id_escritorio) do nothing;
  select * into c from public.agentesia_carteiras where id_escritorio = p_id_escritorio for update;
  if p_tipo = 'bonus_plano' then
    pb := v;
  elsif p_tipo = 'expira_bonus' then
    pb := greatest(v, -c.bonus_brl);
    if pb = 0 then
      return null;
    end if;
    v := pb;
  elsif p_tipo = 'consumo' then
    pb := -least(greatest(c.bonus_brl, 0), -v);          -- o bônus do mês é gasto primeiro
    ps := v - pb;
  else
    ps := v;
  end if;
  insert into public.agentesia_carteira_movimentos (id_escritorio, tipo, valor_brl, parte_saldo, parte_bonus,
                                                    saldo_depois, bonus_depois, chave_unica, motivo, id_usuario,
                                                    id_recarga, detalhe)
  values (p_id_escritorio, p_tipo, v, ps, pb, c.saldo_brl + ps, c.bonus_brl + pb, p_chave, p_motivo, p_id_usuario,
          p_id_recarga, coalesce(p_detalhe, '{}'::jsonb))
  on conflict (chave_unica) do nothing
  returning * into m;
  if m.id is null then
    return null;
  end if;
  perform set_config('agentesia.lancando', 'sim', true);
  update public.agentesia_carteiras set saldo_brl = saldo_brl + ps, bonus_brl = bonus_brl + pb
  where id_escritorio = p_id_escritorio;
  perform set_config('agentesia.lancando', '', true);
  return m;
end $$;

-- E) Chamadas de IA com custo em R$ -----------------------------------------------------------------------------------
alter table public.agentesia_chamadas_ia
  add column if not exists tokens_cache   int not null default 0,      -- parte de tokens_entrada lida do cache
  add column if not exists id_lead        uuid references public.agentesia_leads(id) on delete set null,
  add column if not exists id_agente      uuid references public.agentesia_agentes(id) on delete set null,
  add column if not exists codigo_etapa   text,
  add column if not exists origem         text not null default 'producao',
  add column if not exists sem_preco      boolean not null default false,
  add column if not exists cotacao        numeric(10,4),
  add column if not exists markup         numeric(10,4),
  add column if not exists custo_brl_real numeric(16,6) not null default 0,   -- custo em R$ (sem markup)
  add column if not exists custo_brl      numeric(16,6) not null default 0,   -- valor cobrado (com markup)
  add column if not exists cobranca       text not null default 'pendente',
  add column if not exists id_movimento   uuid references public.agentesia_carteira_movimentos(id) on delete set null;
do $$ begin
  alter table public.agentesia_chamadas_ia add constraint agentesia_chamadas_ia_cobranca
    check (cobranca in ('pendente', 'debitada', 'isenta'));
exception when duplicate_object then null; end $$;

-- Histórico de antes da cobrança: calcula o R$ (para relatório), mas não cobra.
update public.agentesia_chamadas_ia c
   set cotacao = v.cotacao_usd_brl, markup = v.markup,
       custo_brl_real = round(c.custo_usd * v.cotacao_usd_brl, 6),
       custo_brl = round(c.custo_usd * v.cotacao_usd_brl * v.markup, 6), cobranca = 'isenta'
  from public.agentesia_cobranca_vigente() v
 where c.cotacao is null;

create index if not exists agentesia_chamadas_ia_escritorio_data on public.agentesia_chamadas_ia (id_escritorio, criado_em);
create index if not exists agentesia_chamadas_ia_turno on public.agentesia_chamadas_ia (id_turno);
create index if not exists agentesia_chamadas_ia_lead on public.agentesia_chamadas_ia (id_lead);
create index if not exists agentesia_chamadas_ia_pendentes on public.agentesia_chamadas_ia (id_escritorio, criado_em)
  where cobranca = 'pendente';

create or replace function public.agentesia_precificar_chamada() returns trigger language plpgsql as $$
declare
  v_lead uuid;
  v_etapa text;
  v_agente uuid;
  v_cotacao numeric;
  v_markup numeric;
  v_markup_escritorio numeric;
begin
  if new.id_turno is not null and (new.id_lead is null or new.codigo_etapa is null) then
    select t.id_lead, coalesce(t.etapa_antes, t.etapa_depois) into v_lead, v_etapa
      from public.agentesia_turnos t where t.id = new.id_turno;
    new.id_lead := coalesce(new.id_lead, v_lead);
    new.codigo_etapa := coalesce(new.codigo_etapa, v_etapa);
  end if;
  if new.id_lead is not null and new.id_agente is null then
    select l.id_agente into v_agente from public.agentesia_leads l where l.id = new.id_lead;
    new.id_agente := v_agente;
  end if;
  if new.cotacao is null or new.markup is null then
    select v.cotacao_usd_brl, v.markup into v_cotacao, v_markup from public.agentesia_cobranca_vigente() v;
    select c.markup into v_markup_escritorio from public.agentesia_carteiras c where c.id_escritorio = new.id_escritorio;
    new.cotacao := coalesce(new.cotacao, v_cotacao, 5.50);
    new.markup := coalesce(new.markup, v_markup_escritorio, v_markup, 1.00);
  end if;
  new.custo_brl_real := round(coalesce(new.custo_usd, 0) * new.cotacao, 6);
  new.custo_brl := round(coalesce(new.custo_usd, 0) * new.cotacao * new.markup, 6);
  if new.custo_brl <= 0 or new.id_escritorio is null then
    new.cobranca := 'isenta';
  end if;
  return new;
end $$;
drop trigger if exists agentesia_chamadas_ia_precificar on public.agentesia_chamadas_ia;
create trigger agentesia_chamadas_ia_precificar before insert on public.agentesia_chamadas_ia
  for each row execute function public.agentesia_precificar_chamada();

-- F) Débito em lote ---------------------------------------------------------------------------------------------------
-- Para cada escritório com chamadas pendentes: trava as chamadas (skip locked), soma, lança UM débito no livro e marca
-- as chamadas com o movimento. Tudo na mesma transação: ou debita e marca, ou nada.
create or replace function public.agentesia_debitar_consumo(p_id_escritorio uuid default null, p_limite int default 5000)
returns table (escritorio uuid, movimento uuid, valor numeric, quantidade int)
language plpgsql as $$
declare
  v_escritorio uuid;
  v_ids uuid[];
  v_total numeric;
  v_usd numeric;
  v_real numeric;
  v_de timestamptz;
  v_ate timestamptz;
  v_mov public.agentesia_carteira_movimentos;
begin
  for v_escritorio in
    select distinct c.id_escritorio from public.agentesia_chamadas_ia c
     where c.cobranca = 'pendente' and c.id_escritorio is not null
       and (p_id_escritorio is null or c.id_escritorio = p_id_escritorio)
  loop
    select array_agg(s.id), sum(s.custo_brl), sum(s.custo_usd), sum(s.custo_brl_real), min(s.criado_em), max(s.criado_em)
      into v_ids, v_total, v_usd, v_real, v_de, v_ate
      from (select c.id, c.custo_brl, c.custo_usd, c.custo_brl_real, c.criado_em from public.agentesia_chamadas_ia c
             where c.id_escritorio = v_escritorio and c.cobranca = 'pendente'
             order by c.criado_em limit p_limite for update skip locked) s;
    if v_ids is null or coalesce(v_total, 0) <= 0 then
      continue;
    end if;
    v_mov := public.agentesia_carteira_lancar(
      v_escritorio, 'consumo', -v_total, 'consumo:' || gen_random_uuid()::text, 'Consumo da IA', null,
      jsonb_build_object('chamadas', array_length(v_ids, 1), 'custo_usd', round(v_usd, 6),
                         'custo_brl_real', round(v_real, 6), 'de', v_de, 'ate', v_ate), null);
    update public.agentesia_chamadas_ia set cobranca = 'debitada', id_movimento = v_mov.id where id = any(v_ids);
    escritorio := v_escritorio;
    movimento := v_mov.id;
    valor := v_total;
    quantidade := array_length(v_ids, 1);
    return next;
  end loop;
end $$;

-- G) Recargas, eventos de pagamento e assinaturas ---------------------------------------------------------------------
create table if not exists public.agentesia_recargas (
  id               uuid primary key default gen_random_uuid(),
  id_escritorio    uuid not null references public.agentesia_escritorios(id) on delete cascade,
  valor_brl        numeric(12,2) not null check (valor_brl > 0 and valor_brl <= 100000),
  situacao         text not null default 'pendente'
                   check (situacao in ('pendente', 'paga', 'cancelada', 'expirada', 'estornada')),
  gateway          text not null default 'manual' check (gateway in ('manual', 'asaas')),
  metodo           text check (metodo in ('pix', 'boleto', 'cartao', 'manual')),
  id_externo       text,                       -- id do pagamento no gateway (Asaas: pay_...)
  url_pagamento    text,                       -- fatura/boleto
  pix_copia_cola   text,
  pix_qr_base64    text,
  vencimento       timestamptz,
  pedido_por       uuid references public.agentesia_usuarios(id) on delete set null,
  confirmada_por   uuid references public.agentesia_usuarios(id) on delete set null,
  observacao       text,
  paga_em          timestamptz,
  encerrada_em     timestamptz,                -- cancelada, expirada ou estornada
  id_movimento     uuid references public.agentesia_carteira_movimentos(id) on delete set null,
  detalhe          jsonb not null default '{}'::jsonb,
  criado_em        timestamptz not null default now(),
  atualizado_em    timestamptz not null default now()
);
create unique index if not exists agentesia_recargas_externo on public.agentesia_recargas (gateway, id_externo)
  where id_externo is not null;
create index if not exists agentesia_recargas_escritorio on public.agentesia_recargas (id_escritorio, criado_em desc);
alter table public.agentesia_recargas enable row level security;
drop trigger if exists agentesia_recargas_atualizado_em on public.agentesia_recargas;
create trigger agentesia_recargas_atualizado_em before update on public.agentesia_recargas
  for each row execute function public.agentesia_tocar_atualizado_em();

-- Webhooks de pagamento recebidos: o mesmo evento repetido pelo gateway não é processado de novo.
create table if not exists public.agentesia_pagamento_eventos (
  id               uuid primary key default gen_random_uuid(),
  gateway          text not null,
  id_evento        text not null,
  tipo             text,
  id_externo       text,
  id_recarga       uuid references public.agentesia_recargas(id) on delete set null,
  payload          jsonb not null default '{}'::jsonb,
  resultado        text,
  erro             text,
  criado_em        timestamptz not null default now(),
  unique (gateway, id_evento)
);
alter table public.agentesia_pagamento_eventos enable row level security;

-- Plano com cobrança recorrente (previsto: hoje a mensalidade é cobrada fora do sistema).
create table if not exists public.agentesia_assinaturas (
  id                uuid primary key default gen_random_uuid(),
  id_escritorio     uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_plano          uuid not null references public.agentesia_planos(id),
  situacao          text not null default 'ativa' check (situacao in ('pendente', 'ativa', 'atrasada', 'suspensa', 'cancelada')),
  ciclo             text not null default 'mensal' check (ciclo in ('mensal', 'anual')),
  valor_brl         numeric(12,2) not null check (valor_brl >= 0),
  gateway           text not null default 'manual' check (gateway in ('manual', 'asaas')),
  id_externo        text,                  -- Asaas: sub_...
  proxima_cobranca  date,
  criado_em         timestamptz not null default now(),
  atualizado_em     timestamptz not null default now()
);
create index if not exists agentesia_assinaturas_escritorio on public.agentesia_assinaturas (id_escritorio);
alter table public.agentesia_assinaturas enable row level security;
drop trigger if exists agentesia_assinaturas_atualizado_em on public.agentesia_assinaturas;
create trigger agentesia_assinaturas_atualizado_em before update on public.agentesia_assinaturas
  for each row execute function public.agentesia_tocar_atualizado_em();

-- Confirma a recarga e credita UMA vez: repetir (webhook duplicado, admin clicando duas vezes) devolve o mesmo movimento.
create or replace function public.agentesia_confirmar_recarga(
  p_id_recarga uuid, p_id_usuario uuid default null, p_id_externo text default null, p_detalhe jsonb default '{}'::jsonb)
returns uuid language plpgsql as $$
declare
  r public.agentesia_recargas;
  m public.agentesia_carteira_movimentos;
  v_id uuid;
begin
  select * into r from public.agentesia_recargas where id = p_id_recarga for update;
  if not found then
    raise exception 'recarga não encontrada';
  end if;
  if r.situacao = 'paga' then
    return r.id_movimento;
  end if;
  if r.situacao in ('cancelada', 'estornada') then
    raise exception 'recarga % não pode ser confirmada', r.situacao;
  end if;
  m := public.agentesia_carteira_lancar(r.id_escritorio, 'recarga', r.valor_brl, 'recarga:' || r.id::text,
                                        'Recarga confirmada (' || r.gateway || ')', p_id_usuario,
                                        coalesce(p_detalhe, '{}'::jsonb), r.id);
  v_id := m.id;
  if v_id is null then
    select id into v_id from public.agentesia_carteira_movimentos where chave_unica = 'recarga:' || r.id::text;
  end if;
  update public.agentesia_recargas
     set situacao = 'paga', paga_em = now(), confirmada_por = p_id_usuario, id_movimento = v_id,
         id_externo = coalesce(id_externo, p_id_externo)
   where id = r.id;
  return v_id;
end $$;

-- Estorno (chargeback ou devolução): tira o valor da carteira uma vez só.
create or replace function public.agentesia_estornar_recarga(p_id_recarga uuid, p_id_usuario uuid default null,
                                                             p_motivo text default null)
returns uuid language plpgsql as $$
declare
  r public.agentesia_recargas;
  m public.agentesia_carteira_movimentos;
begin
  select * into r from public.agentesia_recargas where id = p_id_recarga for update;
  if not found then
    raise exception 'recarga não encontrada';
  end if;
  if r.situacao <> 'paga' then
    return null;
  end if;
  m := public.agentesia_carteira_lancar(r.id_escritorio, 'estorno', -r.valor_brl, 'estorno:' || r.id::text,
                                        coalesce(p_motivo, 'Recarga estornada'), p_id_usuario, '{}'::jsonb, r.id);
  update public.agentesia_recargas set situacao = 'estornada', encerrada_em = now() where id = r.id;
  return m.id;
end $$;

-- H) Bônus do plano do mês --------------------------------------------------------------------------------------------
-- Idempotente por mês (chave bonus_plano:<escritório>:<AAAA-MM>). Sem acumular: o bônus que sobrou expira antes.
create or replace function public.agentesia_renovar_bonus(p_id_escritorio uuid, p_mes text)
returns numeric language plpgsql as $$
declare
  c public.agentesia_carteiras;
  p public.agentesia_planos;
  m public.agentesia_carteira_movimentos;
  v_sobra numeric := 0;
begin
  select * into c from public.agentesia_carteiras where id_escritorio = p_id_escritorio for update;
  if not found or c.id_plano is null or c.bonus_mes is not distinct from p_mes then
    return null;
  end if;
  select * into p from public.agentesia_planos where id = c.id_plano;
  if not p.bonus_acumula and c.bonus_brl > 0 then
    perform public.agentesia_carteira_lancar(p_id_escritorio, 'expira_bonus', -c.bonus_brl,
                                             'expira_bonus:' || p_id_escritorio::text || ':' || p_mes,
                                             'Bônus do mês anterior expirou (não acumula)', null, '{}'::jsonb, null);
  elsif p.bonus_acumula then
    v_sobra := c.bonus_brl;
  end if;
  if p.bonus_mensal_brl > 0 then
    m := public.agentesia_carteira_lancar(p_id_escritorio, 'bonus_plano', p.bonus_mensal_brl,
                                          'bonus_plano:' || p_id_escritorio::text || ':' || p_mes,
                                          'Bônus do plano ' || p.nome || ' (' || p_mes || ')', null,
                                          jsonb_build_object('plano', p.codigo, 'mes', p_mes), null);
  end if;
  update public.agentesia_carteiras
     set bonus_mes = p_mes, bonus_do_mes_brl = p.bonus_mensal_brl + v_sobra,
         avisos = avisos - 'bonus_80' - 'bonus_100'
   where id_escritorio = p_id_escritorio;
  return case when m.id is null then 0 else p.bonus_mensal_brl end;
end $$;

-- I) Conferência: carteira × soma do livro ----------------------------------------------------------------------------
create or replace view public.agentesia_v_carteira_conferencia as
select c.id_escritorio, c.saldo_brl, c.bonus_brl,
       coalesce(sum(m.parte_saldo), 0) as soma_saldo, coalesce(sum(m.parte_bonus), 0) as soma_bonus,
       c.saldo_brl - coalesce(sum(m.parte_saldo), 0) + c.bonus_brl - coalesce(sum(m.parte_bonus), 0) as diferenca,
       count(m.id) as movimentos
  from public.agentesia_carteiras c
  left join public.agentesia_carteira_movimentos m on m.id_escritorio = c.id_escritorio
 group by c.id_escritorio, c.saldo_brl, c.bonus_brl;

-- Só o servidor (service role / dono do banco) mexe em dinheiro: nada pela API pública do Supabase.
revoke execute on function public.agentesia_carteira_lancar(uuid, text, numeric, text, text, uuid, jsonb, uuid) from public;
revoke execute on function public.agentesia_debitar_consumo(uuid, int) from public;
revoke execute on function public.agentesia_confirmar_recarga(uuid, uuid, text, jsonb) from public;
revoke execute on function public.agentesia_estornar_recarga(uuid, uuid, text) from public;
revoke execute on function public.agentesia_renovar_bonus(uuid, text) from public;
do $$
declare papel text;
begin
  foreach papel in array array['anon', 'authenticated'] loop
    if exists (select 1 from pg_roles where rolname = papel) then
      execute format('revoke all on public.agentesia_v_carteira_conferencia from %I', papel);
    end if;
  end loop;
end $$;

commit;
