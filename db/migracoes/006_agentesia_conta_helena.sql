-- =============================================================================
-- 006_agentesia_conta_helena.sql
-- Conta da Helena e primeira criação do escritório (ver docs/WEAVER_TABELAS_E_ADMIN.md, seção 4):
--   A) agentesia_escritorios.onboarding (passos e situação), sincronizado_em (última "Sincronizar conta") e
--      dados_helena (dados da empresa na Helena e ids do que o onboarding criou ou escolheu: webhook, equipe da IA,
--      painel e etapas por tipo, etiquetas padrão);
--   B) agentesia_helena_recursos: cópia do que existe na conta da Helena (canal, painel, coluna, etiqueta, equipe,
--      usuário), com visto_em e sumiu_em. É só cópia: nunca é fonte de ação sem conferir na Helena na hora.
--      Usuário guarda só id e nome (nada de e-mail ou telefone de pessoas);
--   C) agentesia_lead_etapas: histórico de etapa do lead, preenchido por gatilho em qualquer caminho que mude
--      agentesia_leads.id_etapa. Origem: set_config('agentesia.origem_etapa', 'equipe', true) na transação; sem ela,
--      um turno da IA em andamento no lead vira origem 'ia'; senão fica vazia;
--   D) agentesia_contatos.telefone_chave (coluna gerada: 55 + DDD + 8 últimos dígitos) para achar o contato quando a
--      Helena manda o número sem o nono dígito;
--   E) agentesia_canais.nome_exibicao, tipo_helena, sincronizado_em (preenchidos pela sincronização);
--   G) agentesia_alteracoes.situacao (ok | erro) e erro: falha de ação de admin também fica registrada.
--
-- O código funciona sem esta migração (só não grava o onboarding, o cache, o histórico e a chave): pode aplicar com o
-- servidor no ar. Pode rodar mais de uma vez. Só mexe em tabelas agentesia_*. Depende da 001 e da 002.
-- Para desfazer: desfazer_006.sql.
-- =============================================================================

begin;

-- A) Onboarding e última sincronização da conta
alter table public.agentesia_escritorios
  add column if not exists onboarding jsonb not null default '{}'::jsonb,
      -- {"passos": [{"codigo":"token","titulo":"...","situacao":"ok","detalhe":"...","em":"..."}],
      --  "concluido_em": null, "atualizado_em": "..."}
  add column if not exists sincronizado_em timestamptz,
  -- Conta da Helena (sem token, sem e-mail/telefone de pessoas):
  -- {"conta": {"nome","razao_social","email_contato" (da empresa),"documento","tipo_documento","endereco":{...},"criada_em","plano",
  --            "recursos":{"includedAgents","includedSessions"}},
  --  "ids": {"token_final" (só os 4 últimos),"id_assinatura","id_departamento","id_painel","etapas_por_tipo":{"SDR":"<stepId>","COMERCIAL":...,
  --          "CONTRATO","AGUARDANDO_ASSINATURA","CONTRATO_ASSINADO","DESQUALIFICADO"},"etiquetas":{"📞 SDR":"<tagId>",...}}}
  add column if not exists dados_helena jsonb not null default '{}'::jsonb;

-- B) Cópia do que existe na conta da Helena
create table if not exists public.agentesia_helena_recursos (
  id               uuid primary key default gen_random_uuid(),
  id_escritorio    uuid not null references public.agentesia_escritorios(id) on delete cascade,
  tipo             text not null check (tipo in ('canal', 'painel', 'coluna', 'etiqueta', 'equipe', 'usuario')),
  id_externo       text not null,                       -- id na Helena
  id_pai_externo   text,                                -- coluna -> painel
  nome             text,
  posicao          int,                                 -- ordem da coluna no painel
  dados            jsonb not null default '{}'::jsonb,  -- só o necessário; nunca e-mail/telefone de pessoas
  visto_em         timestamptz not null default now(), -- última sincronização em que existia
  sumiu_em         timestamptz,                         -- não veio na última sincronização
  criado_em        timestamptz not null default now(),
  atualizado_em    timestamptz not null default now(),
  unique (id_escritorio, tipo, id_externo)
);
create index if not exists agentesia_helena_recursos_tipo
  on public.agentesia_helena_recursos (id_escritorio, tipo) where sumiu_em is null;

drop trigger if exists agentesia_helena_recursos_atualizado_em on public.agentesia_helena_recursos;
create trigger agentesia_helena_recursos_atualizado_em before update on public.agentesia_helena_recursos
  for each row execute function public.agentesia_tocar_atualizado_em();
alter table public.agentesia_helena_recursos enable row level security;

-- C) Histórico de etapa do lead
create table if not exists public.agentesia_lead_etapas (
  id              uuid primary key default gen_random_uuid(),
  id_escritorio   uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_lead         uuid not null references public.agentesia_leads(id) on delete cascade,
  etapa_de        text,                 -- código (agentesia_agente_etapas.codigo); vazio = lead entrou
  etapa_para      text,
  origem          text,                 -- entrada | ia | equipe | contrato | sistema... (vazio = não deu para saber)
  id_turno        uuid references public.agentesia_turnos(id) on delete set null,
  criado_em       timestamptz not null default now()
);
create index if not exists agentesia_lead_etapas_lead on public.agentesia_lead_etapas (id_lead, criado_em desc);
create index if not exists agentesia_lead_etapas_funil on public.agentesia_lead_etapas (id_escritorio, etapa_para, criado_em desc);
alter table public.agentesia_lead_etapas enable row level security;

create or replace function public.agentesia_registrar_troca_etapa()
returns trigger
language plpgsql
set search_path = ''
as $$                                     -- SECURITY INVOKER de propósito: só insere no histórico
declare
  v_origem text := nullif(current_setting('agentesia.origem_etapa', true), '');
  v_turno  uuid;
begin
  if tg_op = 'UPDATE' and new.id_etapa is not distinct from old.id_etapa then
    return new;
  end if;
  if tg_op = 'INSERT' and new.id_etapa is null then
    return new;
  end if;
  begin
    v_turno := nullif(current_setting('agentesia.id_turno', true), '')::uuid;
  exception when others then
    v_turno := null;
  end;
  if v_turno is not null and not exists (select 1 from public.agentesia_turnos t where t.id = v_turno) then
    v_turno := null;                      -- id inválido nunca impede a troca de etapa
  end if;
  if v_origem is null and tg_op = 'INSERT' then
    v_origem := 'entrada';
  end if;
  if v_turno is null and (v_origem is null or v_origem = 'ia') then
    -- Sem origem declarada: um turno da IA em andamento neste lead é quem trocou.
    select t.id into v_turno from public.agentesia_turnos t
     where t.id_lead = new.id and t.situacao = 'processando' and t.concluido_em is null
       and t.iniciado_em > now() - interval '10 minutes'
     order by t.iniciado_em desc limit 1;
  end if;
  if v_origem is null and v_turno is not null then
    v_origem := 'ia';
  end if;
  insert into public.agentesia_lead_etapas (id_escritorio, id_lead, etapa_de, etapa_para, origem, id_turno)
  values (new.id_escritorio, new.id,
          case when tg_op = 'UPDATE' then (select e.codigo from public.agentesia_agente_etapas e where e.id = old.id_etapa) end,
          (select e.codigo from public.agentesia_agente_etapas e where e.id = new.id_etapa),
          v_origem, v_turno);
  return new;
end
$$;

drop trigger if exists agentesia_leads_troca_etapa on public.agentesia_leads;
create trigger agentesia_leads_troca_etapa
  after insert or update of id_etapa on public.agentesia_leads
  for each row execute function public.agentesia_registrar_troca_etapa();

-- D) Chave de telefone sem o nono dígito (só números do Brasil: 55 + DDD + 8 ou 9 dígitos)
alter table public.agentesia_contatos
  add column if not exists telefone_chave text
  generated always as (
    case when telefone_normalizado ~ '^55[0-9]{10,11}$'
         then left(telefone_normalizado, 4) || right(telefone_normalizado, 8) end
  ) stored;
create index if not exists agentesia_contatos_telefone_chave
  on public.agentesia_contatos (id_escritorio, telefone_chave) where telefone_chave is not null;

-- E) Detalhes do canal vindos da Helena
alter table public.agentesia_canais
  add column if not exists nome_exibicao   text,
  add column if not exists tipo_helena     text,      -- CloudAPI_WhatsApp, ZAPI_WhatsApp, Instagram...
  add column if not exists sincronizado_em timestamptz;

-- G) Falha de ação de admin também fica registrada
alter table public.agentesia_alteracoes
  add column if not exists situacao text not null default 'ok' check (situacao in ('ok', 'erro')),
  add column if not exists erro     text;

commit;
