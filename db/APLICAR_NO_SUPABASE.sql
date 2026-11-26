-- =============================================================================
-- APLICAR_NO_SUPABASE.sql — tudo o que o banco de produção precisa, na ordem.
--
-- Como usar:
--   1. Supabase > projeto de produção > SQL Editor > New query.
--   2. Cole o arquivo INTEIRO e clique em Run (uma vez só).
--   3. No fim aparece a conferência do bucket de mídia (1 linha "agentesia-midia").
--
-- O que faz: cria as tabelas agentesia_* (núcleo, gestão, base de conhecimento, canal liberado, mídia pendente,
-- conta da Helena, cobrança) e o bucket "agentesia-midia" do Storage. Não lê nem altera tabelas que já existem
-- (Weaver, sistemaia_*, n8n). RLS ligado em tudo: só o servidor (service_role) lê e grava.
-- Cada bloco tem begin/commit próprio: se um falhar, os anteriores ficam e o erro mostra qual parou.
-- Para desfazer: db/migracoes/desfazer_007.sql ... desfazer_001.sql, nessa ordem (do 7 para o 1).
-- =============================================================================



-- #############################################################################
-- db/migracoes/001_agentesia_nucleo.sql
-- #############################################################################

-- =============================================================================
-- 001_agentesia_nucleo.sql
-- Núcleo do sistema de IA em código (LawChat): só o que a IA precisa para
-- receber a mensagem, entender, decidir, responder e registrar.
--
-- Sistema novo, do zero: não lê nem altera nenhuma tabela que já existe no
-- projeto. Follow-up, CRM, contrato, painel de gestão etc. entram em migrações
-- próprias, quando cada módulo for construído (rascunho em db/rascunhos/).
--
-- RLS ligado em tudo: só o backend (service_role) lê e grava.
-- Para desfazer: desfazer_001.sql.
-- =============================================================================

begin;

create or replace function public.agentesia_tocar_atualizado_em()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.atualizado_em := now();
  return new;
end
$$;

-- -----------------------------------------------------------------------------
-- CONFIGURAÇÃO: quem atende, por onde, com que instruções
-- -----------------------------------------------------------------------------

-- Escritório. config: horário comercial, números de teste, honorários...
create table public.agentesia_escritorios (
  id                  uuid primary key default gen_random_uuid(),
  nome                text not null,
  ia_desligada        boolean not null default false,     -- interruptor de emergência
  id_conta_helena     uuid unique,                        -- companyId da Helena
  id_segredo_helena   uuid,                               -- token da Helena no Supabase Vault
  fuso                text not null default 'America/Sao_Paulo',
  config              jsonb not null default '{}'::jsonb,
  criado_em           timestamptz not null default now(),
  atualizado_em       timestamptz not null default now()
);

-- Número de WhatsApp (canal da Helena).
create table public.agentesia_canais (
  id                   uuid primary key default gen_random_uuid(),
  id_escritorio        uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_canal_helena      text unique,
  numero_normalizado   text not null,                     -- só dígitos, com 55
  tipo                 text not null default 'nao_oficial' check (tipo in ('oficial', 'nao_oficial')),
  ativo                boolean not null default true,
  criado_em            timestamptz not null default now(),
  atualizado_em        timestamptz not null default now(),
  unique (id_escritorio, numero_normalizado)
);

-- A IA do escritório num canal. produto: código do produto (as regras ficam no código).
-- config: persona, honorários, mídias (vídeo inicial), modelo por papel.
create table public.agentesia_agentes (
  id                     uuid primary key default gen_random_uuid(),
  id_escritorio          uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_canal               uuid not null unique references public.agentesia_canais(id) on delete cascade,
  nome                   text not null,
  produto                text not null default 'auxilio_acidente',
  situacao               text not null default 'pausado' check (situacao in ('ativo', 'pausado')),
  modo                   text not null default 'teste'      -- teste: só responde aos números de teste
                         check (modo in ('teste', 'producao')),
  minutos_pausa_humano   int  not null default 15 check (minutos_pausa_humano between 0 and 10080),
  config                 jsonb not null default '{}'::jsonb,
  criado_em              timestamptz not null default now(),
  atualizado_em          timestamptz not null default now()
);

-- Etapas do agente com a instrução de cada uma.
create table public.agentesia_agente_etapas (
  id              uuid primary key default gen_random_uuid(),
  id_agente       uuid not null references public.agentesia_agentes(id) on delete cascade,
  codigo          text not null,                          -- sdr, periodo_graca, closer, coleta_dados...
  ordem           int  not null,
  tipo            text not null default 'conversa' check (tipo in ('conversa', 'terminal')),
  principal       boolean not null default false,         -- onde o lead novo entra
  instrucao       text,                                   -- prompt da etapa
  modelo          text,
  temperatura     numeric(3,2) not null default 0.4 check (temperatura between 0 and 1),
  criado_em       timestamptz not null default now(),
  atualizado_em   timestamptz not null default now(),
  unique (id_agente, codigo)
);
create unique index agentesia_agente_etapas_uma_principal
  on public.agentesia_agente_etapas (id_agente) where principal;

-- -----------------------------------------------------------------------------
-- ATENDIMENTO: o lead, a conversa e o que a IA fez
-- -----------------------------------------------------------------------------

create table public.agentesia_contatos (
  id                     uuid primary key default gen_random_uuid(),
  id_escritorio          uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_contato_helena      text,
  nome                   text,
  telefone_normalizado   text,                            -- com 55 e com o nono dígito
  criado_em              timestamptz not null default now(),
  atualizado_em          timestamptz not null default now(),
  unique (id_escritorio, id_contato_helena)
);
-- Um contato por telefone em cada escritório (contato com número oculto fica sem telefone).
create unique index agentesia_contatos_telefone
  on public.agentesia_contatos (id_escritorio, telefone_normalizado) where telefone_normalizado is not null;

-- Lead: um contato num canal.
create table public.agentesia_leads (
  id                        uuid primary key default gen_random_uuid(),
  id_escritorio             uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_contato                uuid not null references public.agentesia_contatos(id) on delete cascade,
  id_canal                  uuid not null references public.agentesia_canais(id) on delete cascade,
  id_agente                 uuid references public.agentesia_agentes(id) on delete set null,
  id_etapa                  uuid references public.agentesia_agente_etapas(id) on delete set null,
  estado                    text not null default 'ativo'
                            check (estado in ('ativo', 'pausado', 'encerrado')),
  motivo_estado             text,                         -- humano_assumiu, desqualificado, pediu_parar...
  pausado_ate               timestamptz,                  -- volta automática da IA
  id_sessao_helena          text,                         -- atendimento aberto na Helena
  origem                    jsonb not null default '{}'::jsonb, -- utm, anúncio
  ultima_mensagem_lead_em   timestamptz,
  ultima_resposta_ia_em     timestamptz,
  criado_em                 timestamptz not null default now(),
  atualizado_em             timestamptz not null default now(),
  unique (id_canal, id_contato)
);
create index agentesia_leads_volta on public.agentesia_leads (pausado_ate) where estado = 'pausado';

-- Webhooks crus: descarte de repetidos e reprocessamento.
create table public.agentesia_eventos_recebidos (
  id              uuid primary key default gen_random_uuid(),
  id_escritorio   uuid references public.agentesia_escritorios(id) on delete cascade,
  origem          text not null check (origem in ('helena', 'laboratorio')),
  id_externo      text,
  tipo            text,
  payload         jsonb not null,
  situacao        text not null default 'pendente'
                  check (situacao in ('pendente', 'processado', 'ignorado', 'erro')),
  motivo          text,
  recebido_em     timestamptz not null default now(),
  processado_em   timestamptz,
  unique (origem, id_externo)
);

-- Turno: um lote de mensagens do lead e tudo o que o sistema fez com ele.
-- contexto = o que foi enviado à IA; resposta = extrator, decisões, travas e o que saiu.
create table public.agentesia_turnos (
  id              uuid primary key default gen_random_uuid(),
  id_escritorio   uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_lead         uuid not null references public.agentesia_leads(id) on delete cascade,
  modo            text not null check (modo in ('producao', 'teste', 'laboratorio')),
  etapa_antes     text,
  etapa_depois    text,
  contexto        jsonb,
  resposta        jsonb,
  situacao        text not null default 'processando'
                  check (situacao in ('processando', 'respondido', 'silencio', 'descartado', 'erro')),
  motivo          text,
  iniciado_em     timestamptz not null default now(),
  concluido_em    timestamptz
);
create index agentesia_turnos_lead on public.agentesia_turnos (id_lead, iniciado_em desc);

-- Mensagens de todos os autores, na ordem do WhatsApp.
create table public.agentesia_mensagens (
  id               uuid primary key default gen_random_uuid(),
  id_escritorio    uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_lead          uuid not null references public.agentesia_leads(id) on delete cascade,
  id_turno         uuid references public.agentesia_turnos(id) on delete set null,
  id_externo       text,                                  -- id da mensagem na Helena
  autor            text not null check (autor in ('lead', 'ia', 'humano', 'automacao', 'sistema')),
  tipo             text not null default 'texto'
                   check (tipo in ('texto', 'audio', 'imagem', 'video', 'documento', 'figurinha',
                                   'localizacao', 'contato')),
  texto            text,
  texto_extraido   text,                                  -- transcrição ou descrição da mídia
  url_midia        text,
  enviada_em       timestamptz not null,                  -- horário do WhatsApp
  registrada_em    timestamptz not null default now(),
  situacao_envio   text not null default 'recebida'
                   check (situacao_envio in ('recebida', 'pendente', 'enviada', 'falhou')),
  erro             text
);
create unique index agentesia_mensagens_id_externo
  on public.agentesia_mensagens (id_escritorio, id_externo) where id_externo is not null;
create index agentesia_mensagens_lead on public.agentesia_mensagens (id_lead, enviada_em);

-- Fatos do lead, cada um com o trecho que prova. É a base contra alucinação.
create table public.agentesia_lead_fatos (
  id               uuid primary key default gen_random_uuid(),
  id_escritorio    uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_lead          uuid not null references public.agentesia_leads(id) on delete cascade,
  chave            text not null,                         -- data_acidente, tinha_carteira...
  valor            jsonb not null,
  trecho           text,                                  -- frase literal do lead
  id_mensagem      uuid references public.agentesia_mensagens(id) on delete set null,
  fonte            text not null check (fonte in ('extrator', 'equipe', 'sistema')),
  id_turno         uuid references public.agentesia_turnos(id) on delete set null,
  criado_em        timestamptz not null default now(),
  substituido_em   timestamptz
);
create index agentesia_lead_fatos_vigentes
  on public.agentesia_lead_fatos (id_lead, chave) where substituido_em is null;

-- Cada chamada de IA: modelo, tokens, tempo e erro.
create table public.agentesia_chamadas_ia (
  id               uuid primary key default gen_random_uuid(),
  id_escritorio    uuid references public.agentesia_escritorios(id) on delete cascade,
  id_turno         uuid references public.agentesia_turnos(id) on delete set null,
  papel            text not null,                         -- extrator, etapa, transcricao...
  modelo           text not null,
  tokens_entrada   int not null default 0,
  tokens_saida     int not null default 0,
  custo_usd        numeric(12,6) not null default 0,
  duracao_ms       int,
  sucesso          boolean not null,
  erro             text,
  criado_em        timestamptz not null default now()
);

-- Problemas e travas, com o responsável.
create table public.agentesia_eventos (
  id              uuid primary key default gen_random_uuid(),
  id_escritorio   uuid references public.agentesia_escritorios(id) on delete cascade,
  id_lead         uuid references public.agentesia_leads(id) on delete cascade,
  id_turno        uuid references public.agentesia_turnos(id) on delete set null,
  tipo            text not null,                          -- trava_honorarios, erro_helena...
  gravidade       text not null default 'aviso' check (gravidade in ('info', 'aviso', 'erro', 'critico')),
  responsavel     text check (responsavel in ('cliente', 'cadastro', 'provedor', 'lead', 'lawchat')),
  descricao       text,
  detalhe         jsonb,
  criado_em       timestamptz not null default now()
);
create index agentesia_eventos_escritorio on public.agentesia_eventos (id_escritorio, criado_em desc);

-- -----------------------------------------------------------------------------
-- atualizado_em automático e RLS em tudo
-- -----------------------------------------------------------------------------
do $$
declare t text;
begin
  for t in
    select c.table_name from information_schema.columns c
    where c.table_schema = 'public' and c.table_name like 'agentesia\_%'
      and c.column_name = 'atualizado_em'
  loop
    execute format('create trigger %I before update on public.%I
                    for each row execute function public.agentesia_tocar_atualizado_em()',
                   t || '_atualizado_em', t);
  end loop;

  for t in
    select tablename from pg_tables
    where schemaname = 'public' and tablename like 'agentesia\_%'
  loop
    execute format('alter table public.%I enable row level security', t);
  end loop;
end
$$;

commit;


-- #############################################################################
-- db/migracoes/002_agentesia_gestao.sql
-- #############################################################################

-- =============================================================================
-- 002_agentesia_gestao.sql
-- Tabelas do painel de gestão: login, integrações (Helena, CRM, ZapSign, chaves
-- de IA), histórico de alterações, card do CRM, contrato e fila de ações.
--
-- Só cria tabelas agentesia_* e acrescenta colunas em tabelas agentesia_* da 001.
-- Não toca em nenhuma tabela que já existia no projeto.
-- Depende da 001. Para desfazer: desfazer_002.sql.
-- =============================================================================

begin;

-- Colunas novas nas tabelas do núcleo (nossas).
alter table public.agentesia_agente_etapas
  add column if not exists instrucao_travada boolean not null default false;  -- só a LawChat edita
alter table public.agentesia_agentes
  add column if not exists numeros_teste text[] not null default '{}';        -- quem a IA responde em modo teste
alter table public.agentesia_escritorios
  add column if not exists situacao text not null default 'ativo'
    check (situacao in ('ativo', 'suspenso', 'encerrado'));

-- -----------------------------------------------------------------------------
-- Login do painel (independente do Auth do Supabase)
-- -----------------------------------------------------------------------------
create table public.agentesia_usuarios (
  id               uuid primary key default gen_random_uuid(),
  email            text not null unique check (email = lower(email)),
  nome             text not null,
  senha_hash       text not null,                         -- scrypt, com sal
  papel            text not null check (papel in ('dono_lawchat', 'admin_lawchat', 'gestor', 'atendente')),
  id_escritorio    uuid references public.agentesia_escritorios(id) on delete cascade,
  id_usuario_helena text,                                 -- quem entra pela Helena (sem senha)
  ativo            boolean not null default true,
  trocar_senha     boolean not null default true,          -- senha provisória
  ultimo_acesso_em timestamptz,
  criado_em        timestamptz not null default now(),
  atualizado_em    timestamptz not null default now(),
  -- dono e equipe LawChat não pertencem a escritório; gestor e atendente pertencem a um
  check ((papel in ('dono_lawchat', 'admin_lawchat')) = (id_escritorio is null))
);
create unique index agentesia_usuarios_helena
  on public.agentesia_usuarios (id_escritorio, id_usuario_helena) where id_usuario_helena is not null;

-- Quem da equipe LawChat cuida de cada escritório (opcional).
alter table public.agentesia_escritorios
  add column id_responsavel uuid references public.agentesia_usuarios(id) on delete set null;

-- -----------------------------------------------------------------------------
-- Biblioteca de modelos de agente: a equipe LawChat cria e publica; o cliente
-- escolhe um no assistente e ativa no número dele.
-- -----------------------------------------------------------------------------
create table public.agentesia_modelos_agente (
  id              uuid primary key default gen_random_uuid(),
  nome            text not null,
  descricao       text not null default '',
  produto         text not null default 'proprio' check (produto in ('auxilio_acidente', 'proprio')),
  config          jsonb not null default '{}'::jsonb,   -- definição, instruções por etapa, funções, automações, honorários, modelo de IA
  situacao        text not null default 'rascunho' check (situacao in ('rascunho', 'publicado', 'arquivado')),
  criado_por      uuid references public.agentesia_usuarios(id) on delete set null,
  criado_em       timestamptz not null default now(),
  atualizado_em   timestamptz not null default now()
);

alter table public.agentesia_agentes
  add column if not exists id_modelo uuid references public.agentesia_modelos_agente(id) on delete set null;

-- -----------------------------------------------------------------------------
-- Integrações por escritório. O segredo (token) fica no Supabase Vault.
-- -----------------------------------------------------------------------------
create table public.agentesia_integracoes (
  id               uuid primary key default gen_random_uuid(),
  id_escritorio    uuid not null references public.agentesia_escritorios(id) on delete cascade,
  tipo             text not null check (tipo in ('helena', 'crm', 'zapsign', 'openai', 'anthropic')),
  id_segredo_vault uuid,                                  -- vault.secrets.id
  final_segredo    text,                                  -- últimos 4 caracteres, para mostrar mascarado
  config           jsonb not null default '{}'::jsonb,
  situacao         text not null default 'pendente' check (situacao in ('pendente', 'ok', 'erro', 'desligada')),
  erro             text,
  testado_em       timestamptz,
  criado_em        timestamptz not null default now(),
  atualizado_em    timestamptz not null default now(),
  unique (id_escritorio, tipo)
);

-- -----------------------------------------------------------------------------
-- Histórico de alterações (quem mudou o quê, com antes e depois)
-- -----------------------------------------------------------------------------
create table public.agentesia_alteracoes (
  id              uuid primary key default gen_random_uuid(),
  id_usuario      uuid references public.agentesia_usuarios(id) on delete set null,
  id_escritorio   uuid references public.agentesia_escritorios(id) on delete cascade,
  tabela          text not null,
  id_registro     uuid,
  acao            text not null,                          -- criou, alterou, ativou, pausou, conectou...
  resumo          text,
  antes           jsonb,
  depois          jsonb,
  criado_em       timestamptz not null default now()
);
create index agentesia_alteracoes_escritorio on public.agentesia_alteracoes (id_escritorio, criado_em desc);
create index agentesia_alteracoes_registro on public.agentesia_alteracoes (tabela, id_registro, criado_em desc);

-- -----------------------------------------------------------------------------
-- CRM: um card por lead
-- -----------------------------------------------------------------------------
create table public.agentesia_crm_cards (
  id                  uuid primary key default gen_random_uuid(),
  id_escritorio       uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_lead             uuid not null unique references public.agentesia_leads(id) on delete cascade,
  id_card_helena      text unique,
  id_painel_helena    text,
  id_etapa_helena     text,
  situacao            text not null default 'pendente' check (situacao in ('ok', 'pendente', 'erro')),
  erro                text,
  sincronizado_em     timestamptz,
  criado_em           timestamptz not null default now(),
  atualizado_em       timestamptz not null default now()
);

-- -----------------------------------------------------------------------------
-- Contrato: versão, reserva e assinatura
-- -----------------------------------------------------------------------------
create table public.agentesia_contratos (
  id                    uuid primary key default gen_random_uuid(),
  id_escritorio         uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_lead               uuid not null references public.agentesia_leads(id) on delete cascade,
  versao                int  not null,
  provedor              text not null default 'zapsign' check (provedor in ('zapsign')),
  id_documento_externo  text,
  link                  text,
  dados                 jsonb not null,
  dados_hash            text not null,                    -- mesmos dados = mesmo link
  situacao              text not null default 'reservado'
                        check (situacao in ('reservado', 'gerado', 'substituido', 'assinado', 'cancelado', 'erro')),
  reservado_ate         timestamptz,
  gerado_em             timestamptz,
  assinado_em           timestamptz,
  signatarios           jsonb,
  erro                  text,
  causa_erro            text,                             -- chave, pagamento, limite, modelo, dados, fora_do_ar
  id_modelo             text,                             -- modelo de documento usado nesta versão
  id_assinante_externo  text,                             -- token do assinante (o lead) na ZapSign
  lead_assinou_em       timestamptz,
  concluido_em          timestamptz,                      -- todos assinaram
  arquivo_assinado      text,
  id_acao               uuid,                             -- ação da fila que gerou esta versão
  resumo                text,                             -- resumo do caso feito pela IA depois da assinatura
  criado_em             timestamptz not null default now(),
  atualizado_em         timestamptz not null default now(),
  unique (id_lead, versao)
);
-- Uma versão em geração e uma vigente por lead. A anterior fica 'gerado' (link válido) enquanto a
-- nova está 'reservado'; ao gravar a nova, a anterior vira 'substituido' na mesma transação.
create unique index agentesia_contratos_um_reservado
  on public.agentesia_contratos (id_lead) where situacao = 'reservado';
create unique index agentesia_contratos_um_gerado
  on public.agentesia_contratos (id_lead) where situacao = 'gerado';
create unique index agentesia_contratos_documento
  on public.agentesia_contratos (provedor, id_documento_externo) where id_documento_externo is not null;

-- -----------------------------------------------------------------------------
-- Fila de chamadas a sistemas de fora (Helena, ZapSign), com novas tentativas
-- -----------------------------------------------------------------------------
create table public.agentesia_acoes (
  id              uuid primary key default gen_random_uuid(),
  id_escritorio   uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_lead         uuid references public.agentesia_leads(id) on delete cascade,
  id_turno        uuid references public.agentesia_turnos(id) on delete set null,
  tipo            text not null,                          -- criar_card, mover_card, etiquetar, nota, gerar_contrato...
  chave_unica     text unique,                            -- impede pedir a mesma ação duas vezes
  dados           jsonb not null,
  situacao        text not null default 'pendente'
                  check (situacao in ('pendente', 'executando', 'feita', 'falhou', 'cancelada')),
  tentativas      int not null default 0,
  proxima_em      timestamptz not null default now(),
  travada_ate     timestamptz,
  resultado       jsonb,
  erro            text,
  criado_em       timestamptz not null default now(),
  atualizado_em   timestamptz not null default now()
);
create index agentesia_acoes_fila on public.agentesia_acoes (proxima_em) where situacao = 'pendente';

-- -----------------------------------------------------------------------------
-- Avisos à equipe (WhatsApp para números do escritório) quando algo acontece no atendimento.
-- tipo_evento = gatilho das automações (etapa:closer, sinal:nao_sabe_ler, contrato_assinado...).
-- -----------------------------------------------------------------------------
create table public.agentesia_notificacoes (
  id               uuid primary key default gen_random_uuid(),
  id_escritorio    uuid not null references public.agentesia_escritorios(id) on delete cascade,
  tipo_evento      text not null,
  nome             text not null,
  habilitada       boolean not null default true,
  modelo_mensagem  text not null,
  destinatarios    jsonb not null default '[]'::jsonb,     -- [{"rotulo": "Dra. Ana", "numero": "5511..."}]
  criado_em        timestamptz not null default now(),
  atualizado_em    timestamptz not null default now(),
  unique (id_escritorio, tipo_evento)
);

-- -----------------------------------------------------------------------------
-- Follow-up: um envio agendado por vez para cada lead (o próximo passo da cadência).
-- base = última resposta da IA; o lead responder cancela; o envio agenda o passo seguinte.
-- -----------------------------------------------------------------------------
create table public.agentesia_followups (
  id              uuid primary key default gen_random_uuid(),
  id_escritorio   uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_lead         uuid not null references public.agentesia_leads(id) on delete cascade,
  id_agente       uuid references public.agentesia_agentes(id) on delete cascade,
  passo           int  not null check (passo >= 0),          -- 0 = primeiro; passo = total de passos = desistência
  base            timestamptz not null,
  agendado_para   timestamptz not null,
  situacao        text not null default 'pendente'
                  check (situacao in ('pendente', 'reservado', 'enviado', 'cancelado', 'falhou')),
  motivo          text,                                      -- por que cancelou, adiou ou falhou
  mensagens       jsonb,                                     -- o que foi enviado
  tentativas      int  not null default 0,
  reservado_ate   timestamptz,
  enviado_em      timestamptz,
  criado_em       timestamptz not null default now(),
  atualizado_em   timestamptz not null default now()
);
create unique index agentesia_followups_um_por_lead
  on public.agentesia_followups (id_lead) where situacao in ('pendente', 'reservado');
create index agentesia_followups_fila on public.agentesia_followups (agendado_para) where situacao = 'pendente';

-- -----------------------------------------------------------------------------
-- Catálogo de produtos (mesmo desenho do agents-lawchat-main, com prefixo agentesia_).
-- Produto = equipe de agentes do funil (SDR, Closer, Contratos, Assinatura, Desqualificado e,
-- opcional, Período de Graça). O cliente ativa: vira um agente aqui, com uma etapa por papel.
-- -----------------------------------------------------------------------------
create table public.agentesia_biblioteca_produtos (
  id                     uuid primary key default gen_random_uuid(),
  slug                   text not null unique,
  nome                   text not null,
  categoria              text not null default 'Previdenciário',  -- nome da categoria (src/data/categories.ts)
  icone                  text,
  capa_gradiente         text,                               -- "#c1,#c2" (sobrescreve a cor da categoria)
  capa_imagem_url        text,
  descricao_curta        text not null default '',
  descricao_longa        text,
  etiquetas              jsonb not null default '[]'::jsonb,
  modelo_recomendado     text not null default 'gpt-4.1-mini',
  config_modelo          jsonb not null default '{}'::jsonb,
  mensagem_boas_vindas   text,
  mensagem_despedida     text,
  mensagem_fallback      text,
  mensagem_fora_horario  text,
  idioma                 text not null default 'pt-BR',
  blocos_prompt          jsonb not null default '[]'::jsonb,
  exemplos               jsonb not null default '[]'::jsonb,
  casos_de_uso           jsonb not null default '[]'::jsonb,
  plano_minimo           text,
  status                 text not null default 'rascunho' check (status in ('rascunho', 'em_breve', 'publicado')),
  versao                 text not null default '1.0.0',
  faq                    jsonb not null default '[]'::jsonb,   -- [{pergunta, resposta}]
  objecoes               jsonb not null default '[]'::jsonb,   -- [{titulo, resposta}]
  regras_markdown        text,
  dados_escritorio       text,
  modo_midia             text not null default 'texto' check (modo_midia in ('texto', 'audio')),
  id_produto_base        uuid references public.agentesia_biblioteca_produtos(id) on delete set null,
  oferece_periodo_graca  boolean not null default false,
  padrao_followup        jsonb not null default '{}'::jsonb,
  id_origem              text unique,                        -- id do produto no sistema antigo (importação do catálogo)
  criado_por             uuid references public.agentesia_usuarios(id) on delete set null,
  criado_em              timestamptz not null default now(),
  atualizado_em          timestamptz not null default now()
);

create table public.agentesia_biblioteca_agentes (
  id                     uuid primary key default gen_random_uuid(),
  id_produto_biblioteca  uuid not null references public.agentesia_biblioteca_produtos(id) on delete cascade,
  papel                  text not null check (papel in ('sdr', 'periododegraca', 'closer', 'contratos', 'assinatura', 'desqualificado')),
  nome_exibicao          text not null,
  descricao              text,
  icone                  text,
  ordem                  int  not null default 0,
  blocos_prompt          jsonb not null default '[]'::jsonb,   -- [{id:'freeform', content:<markdown>}, {id:'handoff_trigger', ...}]
  texto_prompt           text,
  mensagem_boas_vindas   text,
  mensagem_despedida     text,
  mensagem_fallback      text,
  modelo_recomendado     text not null default 'gpt-4.1-mini',
  config_modelo          jsonb not null default '{}'::jsonb,
  regras_handoff         jsonb not null default '[]'::jsonb,
  criado_em              timestamptz not null default now(),
  atualizado_em          timestamptz not null default now(),
  unique (id_produto_biblioteca, papel)
);

-- Frase que o agente fala para passar o lead adiante ("@Transferência: Closer" no prompt). Só a LawChat edita.
create table public.agentesia_frases_troca (
  id                     uuid primary key default gen_random_uuid(),
  id_produto_biblioteca  uuid references public.agentesia_biblioteca_produtos(id) on delete cascade,
  etapa_destino          text not null,
  nome                   text not null,
  frase                  text not null check (char_length(frase) between 8 and 400),
  descricao              text,
  ordem                  int  not null default 0,
  criado_em              timestamptz not null default now(),
  atualizado_em          timestamptz not null default now()
);
create unique index agentesia_frases_troca_destino
  on public.agentesia_frases_troca (coalesce(id_produto_biblioteca, '00000000-0000-0000-0000-000000000000'::uuid), etapa_destino);

-- Produto ativado pelo escritório (rascunho do assistente + o agente criado).
create table public.agentesia_produtos_ativados (
  id                       uuid primary key default gen_random_uuid(),
  id_escritorio            uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_produto_biblioteca    uuid references public.agentesia_biblioteca_produtos(id) on delete set null,
  id_agente                uuid references public.agentesia_agentes(id) on delete set null,
  nome                     text not null,
  descricao                text,
  status                   text not null default 'rascunho' check (status in ('rascunho', 'ativo', 'pausado', 'erro')),
  versao_template          text,
  canais                   jsonb not null default '["whatsapp"]'::jsonb,
  regras_markdown          text,
  faq                      jsonb not null default '[]'::jsonb,
  objecoes                 jsonb not null default '[]'::jsonb,
  conhecimento             jsonb not null default '[]'::jsonb,
  integracoes              jsonb not null default '{}'::jsonb,
  dados_escritorio         text,
  status_provisionamento   text not null default 'pendente' check (status_provisionamento in ('pendente', 'construindo', 'pronto', 'falhou')),
  erro_provisionamento     text,
  provisioning_started_at  timestamptz,
  numero_ia                text,
  periodo_graca_ativo      boolean not null default false,
  rascunho                 jsonb not null default '{}'::jsonb,  -- estado completo do assistente
  excluido_em              timestamptz,
  criado_em                timestamptz not null default now(),
  atualizado_em            timestamptz not null default now()
);
create index agentesia_produtos_ativados_escritorio on public.agentesia_produtos_ativados (id_escritorio, criado_em desc);
create unique index agentesia_produtos_ativados_um_rascunho
  on public.agentesia_produtos_ativados (id_escritorio, id_produto_biblioteca) where status = 'rascunho' and excluido_em is null;

-- Biblioteca de mídia do escritório (áudio, vídeo, imagem) para usar nos prompts.
create table public.agentesia_biblioteca_midia (
  id               uuid primary key default gen_random_uuid(),
  id_escritorio    uuid not null references public.agentesia_escritorios(id) on delete cascade,
  nome             text not null,
  tipo             text not null check (tipo in ('audio', 'video', 'imagem', 'documento')),
  url              text not null,
  caminho_storage  text,
  mime_type        text,
  tamanho_bytes    bigint not null default 0,
  tags             jsonb not null default '[]'::jsonb,
  favorito         boolean not null default false,
  transcricao      text,
  criado_em        timestamptz not null default now(),
  atualizado_em    timestamptz not null default now()
);
create index agentesia_biblioteca_midia_escritorio on public.agentesia_biblioteca_midia (id_escritorio, criado_em desc);

-- Temperatura de 0 a 2 (controle do assistente, como na OpenAI).
alter table public.agentesia_agente_etapas drop constraint if exists agentesia_agente_etapas_temperatura_check;
alter table public.agentesia_agente_etapas add constraint agentesia_agente_etapas_temperatura_check check (temperatura between 0 and 2);

alter table public.agentesia_agentes
  add column if not exists id_produto_ativado uuid references public.agentesia_produtos_ativados(id) on delete set null;

-- Base de conhecimento: o texto lido do arquivo (PDF, Word, planilha, texto) ou colado no painel.
-- Do agente (id_agente) ou padrão do produto do catálogo (id_produto_biblioteca), copiado travado ao ativar.
-- O arquivo original não é guardado. Cada documento vira trechos com vetor (agentesia_documento_trechos).
create table public.agentesia_documentos (
  id              uuid primary key default gen_random_uuid(),
  id_escritorio   uuid references public.agentesia_escritorios(id) on delete cascade,
  id_agente       uuid references public.agentesia_agentes(id) on delete cascade,
  id_produto_biblioteca uuid references public.agentesia_biblioteca_produtos(id) on delete cascade,
  id_origem       uuid,                                      -- documento padrão do produto de onde veio a cópia
  id_externo      text,                                      -- id no sistema antigo (só documentos que vieram da importação)
  tipo            text not null default 'arquivo' check (tipo in ('arquivo', 'texto')),
  nome            text not null,
  formato         text not null,                             -- pdf, docx, xlsx, texto
  tamanho_bytes   int  not null check (tamanho_bytes >= 0),
  texto           text not null,
  caracteres      int  not null,
  situacao        text not null default 'processando' check (situacao in ('processando', 'pronto', 'erro')),
  erro            text,
  tokens          int  not null default 0,
  origem          text not null default 'cliente' check (origem in ('cliente', 'produto')),
  travado         boolean not null default false,            -- padrão do produto: o cliente vê, mas não apaga
  ordem           int  not null default 0,
  ativo           boolean not null default true,
  criado_por      uuid references public.agentesia_usuarios(id) on delete set null,
  criado_em       timestamptz not null default now(),
  atualizado_em   timestamptz not null default now(),
  check (num_nonnulls(id_agente, id_produto_biblioteca) = 1),
  check (id_agente is null or id_escritorio is not null)
);
create index agentesia_documentos_agente on public.agentesia_documentos (id_agente) where ativo;
create index agentesia_documentos_produto on public.agentesia_documentos (id_produto_biblioteca) where ativo;
create index agentesia_documentos_fila on public.agentesia_documentos (criado_em) where situacao = 'processando';
create unique index agentesia_documentos_copia_unica on public.agentesia_documentos (id_agente, id_origem) where id_origem is not null;

-- Trechos de ~3.000 caracteres (300 de sobra) com o vetor (text-embedding-3-small, 1536 dimensões).
create table public.agentesia_documento_trechos (
  id              uuid primary key default gen_random_uuid(),
  id_documento    uuid not null references public.agentesia_documentos(id) on delete cascade,
  id_agente       uuid not null references public.agentesia_agentes(id) on delete cascade,
  ordem           int  not null,
  conteudo        text not null,
  vetor           real[] not null,
  criado_em       timestamptz not null default now()
);
create index agentesia_documento_trechos_agente on public.agentesia_documento_trechos (id_agente);
create index agentesia_documento_trechos_documento on public.agentesia_documento_trechos (id_documento);

-- Espera e trava do turno no banco: um reinício não perde a resposta agendada e dois servidores
-- nunca respondem o mesmo lead ao mesmo tempo.
alter table public.agentesia_leads
  add column if not exists responder_apos  timestamptz,      -- fim da espera que junta as mensagens
  add column if not exists processando_ate timestamptz;      -- reserva de quem está respondendo agora
create index if not exists agentesia_leads_esperando on public.agentesia_leads (responder_apos) where responder_apos is not null;

-- O webhook da ZapSign também entra na caixa de recebidos (idempotência por id_externo).
alter table public.agentesia_eventos_recebidos drop constraint if exists agentesia_eventos_recebidos_origem_check;
alter table public.agentesia_eventos_recebidos add constraint agentesia_eventos_recebidos_origem_check
  check (origem in ('helena', 'laboratorio', 'zapsign'));

-- Eventos: marcar como resolvido pelo painel.
alter table public.agentesia_eventos
  add column if not exists resolvido_em timestamptz,
  add column if not exists resolvido_por uuid references public.agentesia_usuarios(id) on delete set null;
create index if not exists agentesia_eventos_abertos
  on public.agentesia_eventos (id_escritorio, criado_em desc) where resolvido_em is null;

-- Ficha de memória da conversa (o antigo lead_memoria_resumo do Weaver): uma por lead.
-- A IA vê as 40 últimas mensagens inteiras; o que é mais antigo vira este resumo, refeito pela fila
-- (ação 'resumir_conversa') a cada 20 mensagens antigas novas. Some junto com o lead.
create table public.agentesia_lead_resumo (
  id_lead              uuid primary key references public.agentesia_leads(id) on delete cascade,
  id_escritorio        uuid not null references public.agentesia_escritorios(id) on delete cascade,
  resumo               text not null,                    -- a ficha que a IA lê no lugar das mensagens antigas
  ate_id_mensagem      uuid references public.agentesia_mensagens(id) on delete set null,  -- última mensagem coberta
  mensagens_resumidas  int  not null default 0,          -- quantas mensagens já entraram no resumo
  modelo               text,
  tokens               int,                              -- entrada + saída da última chamada
  criado_em            timestamptz not null default now(),
  atualizado_em        timestamptz not null default now()
);
create index agentesia_lead_resumo_escritorio on public.agentesia_lead_resumo (id_escritorio, atualizado_em desc);

-- -----------------------------------------------------------------------------
-- atualizado_em automático e RLS nas tabelas novas
-- -----------------------------------------------------------------------------
do $$
declare t text;
begin
  foreach t in array array['agentesia_usuarios', 'agentesia_integracoes', 'agentesia_crm_cards',
                           'agentesia_contratos', 'agentesia_acoes', 'agentesia_modelos_agente',
                           'agentesia_notificacoes', 'agentesia_followups', 'agentesia_documentos',
                           'agentesia_biblioteca_produtos', 'agentesia_biblioteca_agentes', 'agentesia_frases_troca',
                           'agentesia_produtos_ativados', 'agentesia_biblioteca_midia', 'agentesia_lead_resumo']
  loop
    execute format('create trigger %I before update on public.%I
                    for each row execute function public.agentesia_tocar_atualizado_em()',
                   t || '_atualizado_em', t);
  end loop;

  foreach t in array array['agentesia_usuarios', 'agentesia_integracoes', 'agentesia_alteracoes',
                           'agentesia_crm_cards', 'agentesia_contratos', 'agentesia_acoes', 'agentesia_modelos_agente',
                           'agentesia_notificacoes', 'agentesia_followups', 'agentesia_documentos',
                           'agentesia_documento_trechos', 'agentesia_biblioteca_produtos', 'agentesia_biblioteca_agentes',
                           'agentesia_frases_troca', 'agentesia_produtos_ativados', 'agentesia_biblioteca_midia',
                           'agentesia_lead_resumo']
  loop
    execute format('alter table public.%I enable row level security', t);
  end loop;
end
$$;

commit;


-- #############################################################################
-- db/migracoes/003_agentesia_conhecimento.sql
-- #############################################################################

-- =============================================================================
-- 003_agentesia_conhecimento.sql
-- Base de conhecimento por papel (docs/BASE_DE_CONHECIMENTO.md):
--   * escopo por papel/etapa nos documentos e nos trechos (vazio = todos os papéis);
--   * documentos "virtuais" de FAQ e objeções (um de cada por agente, gerados da config.conhecimento);
--   * trechos com escritório, título, fonte, hash (cache de embedding), modelo e dimensões;
--   * perguntas sem resposta na base (agentesia_conhecimento_lacunas), para o painel virar FAQ.
--
-- Só mexe em tabelas agentesia_*. Depende da 002. Para desfazer: desfazer_003.sql.
-- Sem pgvector: os vetores continuam como real[] (ver seção 2 do desenho).
-- =============================================================================

begin;

-- Documentos: escopo por papel e os tipos virtuais.
alter table public.agentesia_documentos
  add column if not exists papeis text[] not null default '{}';          -- vazio = todos os papéis
alter table public.agentesia_documentos drop constraint if exists agentesia_documentos_tipo_check;
alter table public.agentesia_documentos add constraint agentesia_documentos_tipo_check
  check (tipo in ('arquivo', 'texto', 'faq', 'objecoes'));
-- Um documento virtual de cada tipo por agente.
create unique index if not exists agentesia_documentos_virtual_unico
  on public.agentesia_documentos (id_agente, tipo) where tipo in ('faq', 'objecoes');

-- Trechos: escopo, fonte e cache de embedding.
alter table public.agentesia_documento_trechos
  add column if not exists id_escritorio uuid references public.agentesia_escritorios(id) on delete cascade,
  add column if not exists papeis        text[] not null default '{}',
  add column if not exists titulo        text,
  add column if not exists fonte         text not null default 'documento',
  add column if not exists hash          text,
  add column if not exists modelo        text not null default 'text-embedding-3-small',
  add column if not exists dimensoes     int  not null default 1536;
alter table public.agentesia_documento_trechos drop constraint if exists agentesia_documento_trechos_fonte_check;
alter table public.agentesia_documento_trechos add constraint agentesia_documento_trechos_fonte_check
  check (fonte in ('documento', 'faq', 'objecao'));
-- Trechos antigos: escritório do documento e dimensão do vetor guardado.
update public.agentesia_documento_trechos t
   set id_escritorio = d.id_escritorio
  from public.agentesia_documentos d
 where d.id = t.id_documento and t.id_escritorio is null;
update public.agentesia_documento_trechos
   set dimensoes = coalesce(array_length(vetor, 1), 0)
 where dimensoes <> coalesce(array_length(vetor, 1), 0);
create index if not exists agentesia_documento_trechos_hash
  on public.agentesia_documento_trechos (id_agente, hash);

-- Perguntas que a IA não achou na base nem no prompt (base.sem_resposta da saída do agente).
create table if not exists public.agentesia_conhecimento_lacunas (
  id                   uuid primary key default gen_random_uuid(),
  id_escritorio        uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_agente            uuid not null references public.agentesia_agentes(id) on delete cascade,
  papel                text,                                   -- etapa em que a pergunta apareceu
  pergunta             text not null,                          -- como a IA resumiu a pergunta do lead
  pergunta_normalizada text not null,                          -- minúsculas, sem acento e sem pontuação (agrupa repetidas)
  vezes                int  not null default 1 check (vezes >= 1),
  ultimo_lead          uuid references public.agentesia_leads(id) on delete set null,
  ultimo_turno         uuid references public.agentesia_turnos(id) on delete set null,
  situacao             text not null default 'aberta' check (situacao in ('aberta', 'respondida', 'ignorada')),
  resposta             text,                                   -- quando respondida, vira item da FAQ
  respondida_por       uuid references public.agentesia_usuarios(id) on delete set null,
  criado_em            timestamptz not null default now(),
  ultima_em            timestamptz not null default now(),
  atualizado_em        timestamptz not null default now()
);
-- A mesma dúvida aberta soma em "vezes" (upsert por este índice).
create unique index if not exists agentesia_conhecimento_lacunas_aberta
  on public.agentesia_conhecimento_lacunas (id_agente, pergunta_normalizada) where situacao = 'aberta';
create index if not exists agentesia_conhecimento_lacunas_escritorio
  on public.agentesia_conhecimento_lacunas (id_escritorio, situacao, ultima_em desc);

create trigger agentesia_conhecimento_lacunas_atualizado_em before update on public.agentesia_conhecimento_lacunas
  for each row execute function public.agentesia_tocar_atualizado_em();
alter table public.agentesia_conhecimento_lacunas enable row level security;

commit;


-- #############################################################################
-- db/migracoes/004_agentesia_canal_liberado.sql
-- #############################################################################

-- =============================================================================
-- 004_agentesia_canal_liberado.sql
-- Produto na lixeira SOLTA o número de WhatsApp (decisão do dono): outro produto pode usar o canal.
--   * agentesia_agentes.id_canal passa a aceitar null (agente sem número = "precisa ativar");
--     o unique continua (vários null são permitidos; dois agentes no mesmo número, não);
--   * id_canal_anterior: o número que o agente usava antes de ser solto (só histórico, não prende nada);
--   * canal_liberado_em: quando o número foi solto.
-- O motor acha o agente pelo canal (agente_do_canal): número solto = nenhum agente responde nele.
--
-- Só mexe em tabelas agentesia_*. Depende da 001/002. Para desfazer: desfazer_004.sql.
-- =============================================================================

begin;

alter table public.agentesia_agentes alter column id_canal drop not null;

alter table public.agentesia_agentes
  add column if not exists id_canal_anterior uuid references public.agentesia_canais(id) on delete set null,
  add column if not exists canal_liberado_em timestamptz;

commit;


-- #############################################################################
-- db/migracoes/005_agentesia_midia_pendente.sql
-- #############################################################################

-- =============================================================================
-- 005_agentesia_midia_pendente.sql
-- Marca no banco a leitura de mídia em andamento (áudio, imagem, documento do lead).
--   * agentesia_mensagens.midia_pendente_desde: preenchida quando a recepção manda ler a mídia e limpa quando o texto
--     lido é gravado (ou a leitura falha). Antes a leitura vivia só na memória do processo: com 2 servidores, ou depois
--     de um reinício, o turno respondia "não consegui abrir o arquivo" sem esperar nem refazer a leitura.
-- O código funciona sem esta coluna (só não enxerga a leitura de outro servidor): pode aplicar com o servidor no ar.
--
-- Só mexe em tabelas agentesia_*. Depende da 001. Para desfazer: desfazer_005.sql.
-- =============================================================================

begin;

alter table public.agentesia_mensagens
  add column if not exists midia_pendente_desde timestamptz;

commit;


-- #############################################################################
-- db/migracoes/006_agentesia_conta_helena.sql
-- #############################################################################

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


-- #############################################################################
-- db/migracoes/007_agentesia_cobranca.sql
-- #############################################################################

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


-- #############################################################################
-- db/exemplos/criar_bucket_midia.sql
-- #############################################################################

-- Bucket da biblioteca de mídia (áudio, vídeo e imagem que o roteiro manda ao lead).
-- NÃO é migração: o dono roda UMA vez no SQL Editor do Supabase (projeto AGENT WEAVER), antes de ligar
-- AGENTESIA_MIDIA_ARMAZENAMENTO=supabase. Pode rodar de novo sem estrago (tudo é idempotente).
--
-- Como fica:
--   leitura  pública, pela URL {SUPABASE_URL}/storage/v1/object/public/agentesia-midia/{caminho}
--            (a Helena baixa o arquivo por ela para mandar ao lead). Não há política de SELECT: ninguém LISTA o bucket
--            pela API; só baixa quem tem a URL do arquivo.
--   escrita  só a service role (AGENTESIA_SUPABASE_SERVICE_KEY, usada pelo servidor). A service role ignora o RLS;
--            anon e authenticated ficam barrados por políticas RESTRITIVAS (valem mesmo se outra política
--            permissiva antiga, por exemplo a do bucket "agent-media", liberar escrita geral em storage.objects).
--
-- Se mudar o nome do bucket (AGENTESIA_MIDIA_BUCKET), troque 'agentesia-midia' em todo o arquivo.

-- 1) O bucket: público para leitura, 16 MB por arquivo (limite do WhatsApp para áudio e vídeo; imagem até 5 MB é
--    conferida pelo servidor), só os formatos que a biblioteca aceita.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('agentesia-midia', 'agentesia-midia', true, 16777216,
        array['audio/ogg', 'audio/mpeg', 'audio/mp4', 'video/mp4', 'image/jpeg', 'image/png'])
on conflict (id) do update
  set public = excluded.public,
      file_size_limit = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;

-- 2) Escrita barrada para anon e authenticated neste bucket (inserir, trocar e apagar).
drop policy if exists "agentesia_midia_sem_insert_publico" on storage.objects;
create policy "agentesia_midia_sem_insert_publico" on storage.objects
  as restrictive for insert to anon, authenticated
  with check (bucket_id <> 'agentesia-midia');

drop policy if exists "agentesia_midia_sem_update_publico" on storage.objects;
create policy "agentesia_midia_sem_update_publico" on storage.objects
  as restrictive for update to anon, authenticated
  using (bucket_id <> 'agentesia-midia')
  with check (bucket_id <> 'agentesia-midia');

drop policy if exists "agentesia_midia_sem_delete_publico" on storage.objects;
create policy "agentesia_midia_sem_delete_publico" on storage.objects
  as restrictive for delete to anon, authenticated
  using (bucket_id <> 'agentesia-midia');

-- 3) Conferência (só leitura): o bucket e as políticas de storage.objects.
select id, public, file_size_limit, allowed_mime_types from storage.buckets where id = 'agentesia-midia';
select policyname, permissive, cmd, roles from pg_policies where schemaname = 'storage' and tablename = 'objects'
 order by policyname;

-- Para desfazer (apaga o bucket só se estiver vazio; esvazie pelo painel do Storage antes):
--   drop policy if exists "agentesia_midia_sem_insert_publico" on storage.objects;
--   drop policy if exists "agentesia_midia_sem_update_publico" on storage.objects;
--   drop policy if exists "agentesia_midia_sem_delete_publico" on storage.objects;
--   delete from storage.buckets where id = 'agentesia-midia';


-- =============================== 008_agentesia_produto_versoes.sql
-- =============================================================================
-- 008_agentesia_produto_versoes.sql
-- Versões dos prompts de um produto ativado (rascunho -> publicar -> voltar; docs/PESQUISA_PLATAFORMAS.md, item 3).
--
-- Cada vez que o produto é ativado ou salvo no editor (sincronizar), o servidor grava uma versão com:
--   número (1, 2, 3... por produto), quem salvou, quando, o resumo das mudanças e o CONTEÚDO dos agentes
--   (prompts, nomes, boas-vindas, frases de troca, FAQ, objeções, regras e dados do escritório).
-- "Restaurar" no painel só copia o conteúdo de uma versão para o rascunho do editor: nada vai ao ar sozinho.
--
-- O código funciona sem esta migração (só não grava nem lista versões): pode aplicar com o servidor no ar.
-- Pode rodar mais de uma vez. Só mexe em tabelas agentesia_*. Depende da 001 e da 002.
-- RLS ligado, sem políticas: só o servidor (service_role) lê e grava, como nas outras tabelas agentesia_*.
-- Para desfazer: desfazer_008.sql.
-- =============================================================================

begin;

create table if not exists public.agentesia_produto_versoes (
  id                  uuid primary key default gen_random_uuid(),
  id_escritorio       uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_produto_ativado  uuid not null references public.agentesia_produtos_ativados(id) on delete cascade,
  numero              int not null,                       -- 1, 2, 3... dentro do produto
  origem              text not null default 'sincronizou', -- ativou | sincronizou
  id_usuario          uuid references public.agentesia_usuarios(id) on delete set null,
  autor               text,                               -- nome de quem salvou (fica mesmo se o usuário sair)
  resumo              jsonb not null default '[]'::jsonb, -- ["Prompt do Closer", "FAQ (+2)", ...]
  conteudo            jsonb not null,                     -- {agentes: [...], faq, objecoes, regras_markdown, dados_escritorio}
  criado_em           timestamptz not null default now(),
  unique (id_produto_ativado, numero)
);
create index if not exists agentesia_produto_versoes_produto
  on public.agentesia_produto_versoes (id_produto_ativado, numero desc);
create index if not exists agentesia_produto_versoes_escritorio
  on public.agentesia_produto_versoes (id_escritorio, criado_em desc);
do $$ begin
  alter table public.agentesia_produto_versoes add constraint agentesia_produto_versoes_origem
    check (origem in ('ativou', 'sincronizou'));
exception when duplicate_object then null; end $$;
alter table public.agentesia_produto_versoes enable row level security;

commit;


-- =============================== 009_agentesia_roteiros.sql
-- =============================================================================
-- 009_agentesia_roteiros.sql
-- Roteiros de áudio do escritório (Ferramentas > Roteiros).
--
-- Um roteiro é o texto que alguém da equipe vai gravar em áudio: título, texto, para qual agente/etapa/produto
-- é (opcional) e a situação (a_gravar | gravado). Quando o áudio é gravado no navegador ou enviado, ele vira um
-- item da biblioteca de mídia (agentesia_biblioteca_midia) e o roteiro guarda o id dele (id_midia); daí pode ser
-- inserido no prompt como as outras mídias.
--
-- O código funciona sem esta migração (a tela de roteiros avisa que falta aplicar): pode aplicar com o servidor no ar.
-- Pode rodar mais de uma vez. Só mexe em tabelas agentesia_*. Depende da 001 e da 002.
-- RLS ligado, sem políticas: só o servidor (service_role) lê e grava, como nas outras tabelas agentesia_*.
-- Para desfazer: desfazer_009.sql.
-- =============================================================================

begin;

create table if not exists public.agentesia_roteiros (
  id                  uuid primary key default gen_random_uuid(),
  id_escritorio       uuid not null references public.agentesia_escritorios(id) on delete cascade,
  titulo              text not null,
  texto               text not null default '',
  id_agente           uuid references public.agentesia_agentes(id) on delete set null,
  etapa               text,                                -- código da etapa do agente (sdr, closer...), opcional
  id_produto_ativado  uuid references public.agentesia_produtos_ativados(id) on delete set null,
  status              text not null default 'a_gravar',    -- a_gravar | gravado
  id_midia            uuid references public.agentesia_biblioteca_midia(id) on delete set null,
  id_usuario          uuid references public.agentesia_usuarios(id) on delete set null,
  criado_em           timestamptz not null default now(),
  atualizado_em       timestamptz not null default now()
);
create index if not exists agentesia_roteiros_escritorio
  on public.agentesia_roteiros (id_escritorio, criado_em desc);
create index if not exists agentesia_roteiros_midia
  on public.agentesia_roteiros (id_midia) where id_midia is not null;
do $$ begin
  alter table public.agentesia_roteiros add constraint agentesia_roteiros_status
    check (status in ('a_gravar', 'gravado'));
exception when duplicate_object then null; end $$;
do $$ begin
  create trigger agentesia_roteiros_atualizado_em before update on public.agentesia_roteiros
    for each row execute function public.agentesia_tocar_atualizado_em();
exception when duplicate_object then null; end $$;
alter table public.agentesia_roteiros enable row level security;

commit;


-- =============================== 010_agentesia_indices_painel.sql
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


-- =============================== 011_agentesia_indices_execucoes.sql
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


-- =============================== 012_agentesia_relatorios.sql
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


-- =============================== 013_agentesia_relatorios_crm.sql
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
