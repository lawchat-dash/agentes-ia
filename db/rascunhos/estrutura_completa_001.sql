-- =============================================================================
-- 001_agentesia_base.sql
-- Estrutura do sistema de IA em código (LawChat). Sistema novo, do zero:
-- não migra nem lê nada do Weaver, do n8n ou das tabelas sistemaia_*.
-- Fica no projeto AGENT WEAVER só por hospedagem.
--
-- Regras desta migração:
--   * Só cria. Nenhuma tabela existente no projeto é alterada.
--   * Todas as tabelas novas começam com agentesia_.
--   * RLS ligado em todas as tabelas: só o backend (service_role) lê e grava até
--     existirem as políticas do painel de gestão.
--   * Para desfazer: desfazer_001_002.sql.
-- =============================================================================

begin;

-- -----------------------------------------------------------------------------
-- Função comum: mantém atualizado_em em dia
-- -----------------------------------------------------------------------------
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

-- =============================================================================
-- 1. ORGANIZAÇÃO (quem é o cliente e por onde ele fala)
-- =============================================================================

-- Escritório de advocacia atendido pela IA.
create table public.agentesia_escritorios (
  id                    uuid primary key default gen_random_uuid(),
  nome                  text not null,
  situacao              text not null default 'ativo'
                        check (situacao in ('ativo', 'pausado', 'encerrado')),
  ia_desligada          boolean not null default false,   -- interruptor de emergência do escritório
  id_conta_helena       uuid unique,                      -- companyId da Helena
  fuso                  text not null default 'America/Sao_Paulo',
  config                jsonb not null default '{}'::jsonb, -- horário comercial, números de teste...
  criado_em             timestamptz not null default now(),
  atualizado_em         timestamptz not null default now()
);

-- Chaves de integração. O valor fica no Supabase Vault; aqui só o id do segredo.
create table public.agentesia_credenciais (
  id                 uuid primary key default gen_random_uuid(),
  id_escritorio      uuid not null references public.agentesia_escritorios(id) on delete cascade,
  provedor           text not null
                     check (provedor in ('helena', 'zapsign', 'tramitacao', 'openai', 'anthropic', 'zapi', 'outro')),
  nome               text not null default 'principal',
  id_segredo_vault   uuid not null,                       -- vault.secrets.id
  ativa              boolean not null default true,
  ultimo_teste_em    timestamptz,
  ultimo_teste_ok    boolean,
  criado_em          timestamptz not null default now(),
  atualizado_em      timestamptz not null default now(),
  unique (id_escritorio, provedor, nome)
);

-- Número de WhatsApp (canal da Helena).
create table public.agentesia_canais (
  id                   uuid primary key default gen_random_uuid(),
  id_escritorio        uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_canal_helena      text unique,
  numero               text not null,
  numero_normalizado   text not null,                     -- só dígitos, com 55
  tipo                 text not null default 'nao_oficial'
                       check (tipo in ('oficial', 'nao_oficial')),
  nome                 text,
  ativo                boolean not null default true,
  criado_em            timestamptz not null default now(),
  atualizado_em        timestamptz not null default now(),
  unique (id_escritorio, numero_normalizado)
);

-- =============================================================================
-- 2. CONFIGURAÇÃO (produto, agente, etapas, prompts) — o que o painel edita
-- =============================================================================

-- Catálogo de produtos jurídicos (Auxílio-Acidente, BPC/LOAS...). Global.
create table public.agentesia_produtos (
  id                      uuid primary key default gen_random_uuid(),
  codigo                  text not null unique,           -- auxilio_acidente, bpc_loas...
  nome                    text not null,
  descricao               text,
  ativo                   boolean not null default true,
  criado_em               timestamptz not null default now(),
  atualizado_em           timestamptz not null default now()
);

-- Regras estruturadas do produto, versionadas: fatos, qualificação, etapas,
-- passos do closer, travas, mensagens fixas. Só uma versão publicada por vez.
create table public.agentesia_produto_versoes (
  id              uuid primary key default gen_random_uuid(),
  id_produto      uuid not null references public.agentesia_produtos(id) on delete cascade,
  versao          int  not null,
  situacao        text not null default 'rascunho'
                  check (situacao in ('rascunho', 'publicada', 'arquivada')),
  conteudo        jsonb not null,
  notas           text,
  criado_por      uuid,
  criado_em       timestamptz not null default now(),
  publicado_em    timestamptz,
  publicado_por   uuid,
  unique (id_produto, versao)
);
create unique index agentesia_produto_versoes_uma_publicada
  on public.agentesia_produto_versoes (id_produto) where situacao = 'publicada';

-- A IA de um escritório para um produto, num canal.
create table public.agentesia_agentes (
  id                     uuid primary key default gen_random_uuid(),
  id_escritorio          uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_canal               uuid not null references public.agentesia_canais(id),
  id_produto             uuid references public.agentesia_produtos(id), -- vazio = agente de triagem
  nome                   text not null,                   -- nome da persona
  situacao               text not null default 'pausado'
                         check (situacao in ('ativo', 'pausado', 'desligado')),
  motivo_situacao        text,
  modo                   text not null default 'teste'    -- teste: responde só aos números de teste
                         check (modo in ('teste', 'producao')),
  minutos_pausa_humano   int  not null default 15 check (minutos_pausa_humano between 0 and 10080),
  modelos                jsonb not null default '{}'::jsonb, -- modelo por papel (extrator, etapa...)
  criado_em              timestamptz not null default now(),
  atualizado_em          timestamptz not null default now()
);
create index agentesia_agentes_canal on public.agentesia_agentes (id_canal);

-- Agente que recebe o lead novo no canal (triagem ou produto padrão).
alter table public.agentesia_canais
  add column id_agente_entrada uuid references public.agentesia_agentes(id) on delete set null;

-- Ajustes do escritório sobre o produto (persona, honorários, horários, mídias),
-- versionados, presos a uma versão do produto.
create table public.agentesia_agente_versoes (
  id                  uuid primary key default gen_random_uuid(),
  id_agente           uuid not null references public.agentesia_agentes(id) on delete cascade,
  versao              int  not null,
  situacao            text not null default 'rascunho'
                      check (situacao in ('rascunho', 'publicada', 'arquivada')),
  id_produto_versao   uuid references public.agentesia_produto_versoes(id),
  ajustes             jsonb not null default '{}'::jsonb,
  notas               text,
  criado_por          uuid,
  criado_em           timestamptz not null default now(),
  publicado_em        timestamptz,
  publicado_por       uuid,
  unique (id_agente, versao)
);
create unique index agentesia_agente_versoes_uma_publicada
  on public.agentesia_agente_versoes (id_agente) where situacao = 'publicada';

-- Etapas do agente e o espelho delas no CRM da Helena.
create table public.agentesia_agente_etapas (
  id                    uuid primary key default gen_random_uuid(),
  id_agente             uuid not null references public.agentesia_agentes(id) on delete cascade,
  codigo                text not null,                    -- sdr, periodo_graca, closer, coleta_dados...
  nome                  text not null,
  ordem                 int  not null,
  tipo                  text not null default 'conversa'
                        check (tipo in ('conversa', 'terminal')),
  principal             boolean not null default false,   -- etapa onde o lead novo entra
  tem_followup          boolean not null default true,
  id_etapa_crm_helena   text,                             -- coluna do painel do CRM
  id_tag_helena         text,
  ativa                 boolean not null default true,
  criado_em             timestamptz not null default now(),
  atualizado_em         timestamptz not null default now(),
  unique (id_agente, codigo)
);
create unique index agentesia_agente_etapas_uma_principal
  on public.agentesia_agente_etapas (id_agente) where principal;

-- Instrução de cada etapa, versionada. Temperatura limitada a 1.
create table public.agentesia_prompts (
  id                 uuid primary key default gen_random_uuid(),
  id_agente_etapa    uuid not null references public.agentesia_agente_etapas(id) on delete cascade,
  versao             int  not null,
  situacao           text not null default 'rascunho'
                     check (situacao in ('rascunho', 'publicada', 'arquivada')),
  texto              text not null,
  modelo             text,
  temperatura        numeric(3,2) not null default 0.4 check (temperatura between 0 and 1),
  notas              text,
  criado_por         uuid,
  criado_em          timestamptz not null default now(),
  publicado_em       timestamptz,
  publicado_por      uuid,
  unique (id_agente_etapa, versao)
);
create unique index agentesia_prompts_uma_publicada
  on public.agentesia_prompts (id_agente_etapa) where situacao = 'publicada';

-- Mídias que a IA pode mandar (vídeo inicial, áudio explicativo...).
create table public.agentesia_midias (
  id              uuid primary key default gen_random_uuid(),
  id_escritorio   uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_agente       uuid references public.agentesia_agentes(id) on delete cascade,
  chave           text not null,                          -- video_inicial, audio_educacao...
  tipo            text not null check (tipo in ('video', 'audio', 'imagem', 'documento')),
  url             text not null,
  transcricao     text,                                   -- o que a mídia diz, para a IA não repetir
  regra           jsonb not null default '{}'::jsonb,     -- ex.: só em horário comercial
  ativa           boolean not null default true,
  criado_em       timestamptz not null default now(),
  atualizado_em   timestamptz not null default now(),
  unique (id_agente, chave)
);

-- Cadência de follow-up. Padrão decidido em 22/11: segunda a sábado, 8h às 20h.
create table public.agentesia_followup_cadencias (
  id                          uuid primary key default gen_random_uuid(),
  id_agente                   uuid not null references public.agentesia_agentes(id) on delete cascade,
  id_agente_etapa             uuid references public.agentesia_agente_etapas(id) on delete cascade, -- vazio = todas as etapas de conversa
  nome                        text not null,
  ativa                       boolean not null default true,
  dias_semana                 int[] not null default '{1,2,3,4,5,6}', -- 1 = segunda ... 7 = domingo
  hora_inicio                 int not null default 8  check (hora_inicio between 0 and 23),
  hora_fim                    int not null default 20 check (hora_fim between 1 and 24),
  intervalo_minimo_minutos    int not null default 30,    -- nunca dois follow-ups mais perto que isso
  expira_apos_minutos         int not null default 1440,  -- atraso máximo antes de desistir do envio
  criado_em                   timestamptz not null default now(),
  atualizado_em               timestamptz not null default now(),
  check (hora_inicio < hora_fim)
);

create table public.agentesia_followup_passos (
  id               uuid primary key default gen_random_uuid(),
  id_cadencia      uuid not null references public.agentesia_followup_cadencias(id) on delete cascade,
  ordem            int  not null,
  espera_minutos   int  not null check (espera_minutos > 0),
  tipo             text not null default 'gerada'
                   check (tipo in ('gerada', 'fixa', 'template')),
  instrucao        text,                                  -- para o tipo gerada
  texto_fixo       text,                                  -- para o tipo fixa
  nome_template    text,                                  -- canal oficial fora das 24 horas
  ativo            boolean not null default true,
  criado_em        timestamptz not null default now(),
  atualizado_em    timestamptz not null default now(),
  unique (id_cadencia, ordem)
);

-- Avisos à equipe: tipos, destinatários e se desligam a IA.
create table public.agentesia_notificacao_regras (
  id              uuid primary key default gen_random_uuid(),
  id_escritorio   uuid not null references public.agentesia_escritorios(id) on delete cascade,
  tipo            text not null,                          -- nao_sabe_ler, videochamada, cliente_antigo...
  ativa           boolean not null default true,
  canal           text not null default 'whatsapp' check (canal in ('whatsapp', 'nota', 'email')),
  destinatarios   jsonb not null default '[]'::jsonb,
  modelo_texto    text,
  desligar_ia     boolean not null default false,
  criado_em       timestamptz not null default now(),
  atualizado_em   timestamptz not null default now(),
  unique (id_escritorio, tipo)
);

-- =============================================================================
-- 3. ATENDIMENTO (o que acontece a cada mensagem)
-- =============================================================================

create table public.agentesia_contatos (
  id                     uuid primary key default gen_random_uuid(),
  id_escritorio          uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_contato_helena      text,
  nome                   text,
  telefone               text,
  telefone_normalizado   text,                            -- só dígitos, com 55, com o nono dígito
  criado_em              timestamptz not null default now(),
  atualizado_em          timestamptz not null default now(),
  unique (id_escritorio, id_contato_helena)
);
create index agentesia_contatos_telefone on public.agentesia_contatos (id_escritorio, telefone_normalizado);

-- O lead: um contato num canal.
create table public.agentesia_leads (
  id                        uuid primary key default gen_random_uuid(),
  id_escritorio             uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_contato                uuid not null references public.agentesia_contatos(id),
  id_canal                  uuid not null references public.agentesia_canais(id),
  id_agente                 uuid references public.agentesia_agentes(id),
  id_produto                uuid references public.agentesia_produtos(id),
  id_etapa                  uuid references public.agentesia_agente_etapas(id),
  estado                    text not null default 'ativo'
                            check (estado in ('ativo', 'pausado', 'desligado', 'encerrado')),
  motivo_estado             text,                         -- humano_assumiu, desqualificado, pediu_parar, engano...
  pausado_ate               timestamptz,                  -- volta automática da IA
  origem                    jsonb not null default '{}'::jsonb, -- utm, anúncio, triagem
  primeira_mensagem_em      timestamptz,
  ultima_mensagem_lead_em   timestamptz,
  ultima_resposta_ia_em     timestamptz,
  etapa_trocada_em          timestamptz,
  criado_em                 timestamptz not null default now(),
  atualizado_em             timestamptz not null default now(),
  unique (id_canal, id_contato)
);
create index agentesia_leads_escritorio_etapa on public.agentesia_leads (id_escritorio, id_etapa);
create index agentesia_leads_volta on public.agentesia_leads (pausado_ate) where estado = 'pausado';

-- Atendimento (sessão) da Helena.
create table public.agentesia_conversas (
  id                 uuid primary key default gen_random_uuid(),
  id_escritorio      uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_lead            uuid not null references public.agentesia_leads(id) on delete cascade,
  id_sessao_helena   text unique,
  aberta_em          timestamptz not null default now(),
  fechada_em         timestamptz,
  criado_em          timestamptz not null default now()
);
create index agentesia_conversas_lead on public.agentesia_conversas (id_lead, aberta_em desc);

-- Tudo o que chega de fora, cru: descarte de repetidos e reprodução.
create table public.agentesia_eventos_recebidos (
  id              uuid primary key default gen_random_uuid(),
  id_escritorio   uuid references public.agentesia_escritorios(id) on delete cascade,
  origem          text not null check (origem in ('helena', 'zapsign', 'tramitacao', 'painel', 'laboratorio')),
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
create index agentesia_eventos_recebidos_pendentes
  on public.agentesia_eventos_recebidos (recebido_em) where situacao = 'pendente';

-- Turno: um lote de mensagens do lead e o que o sistema fez com ele.
create table public.agentesia_turnos (
  id                   uuid primary key default gen_random_uuid(),
  id_escritorio        uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_lead              uuid not null references public.agentesia_leads(id) on delete cascade,
  id_conversa          uuid references public.agentesia_conversas(id),
  modo                 text not null check (modo in ('producao', 'teste', 'laboratorio')),
  etapa_antes          text,
  etapa_depois         text,
  id_agente_versao     uuid references public.agentesia_agente_versoes(id),
  id_produto_versao    uuid references public.agentesia_produto_versoes(id),
  contexto             jsonb,                             -- o que foi enviado ao modelo
  resposta             jsonb,                             -- o que o modelo devolveu e o que saiu
  situacao             text not null default 'processando'
                       check (situacao in ('processando', 'respondido', 'silencio', 'descartado', 'erro')),
  motivo               text,
  iniciado_em          timestamptz not null default now(),
  concluido_em         timestamptz,
  duracao_ms           int
);
create index agentesia_turnos_lead on public.agentesia_turnos (id_lead, iniciado_em desc);

-- Mensagens de todos os autores, na ordem do WhatsApp.
create table public.agentesia_mensagens (
  id               uuid primary key default gen_random_uuid(),
  id_escritorio    uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_lead          uuid not null references public.agentesia_leads(id) on delete cascade,
  id_conversa      uuid references public.agentesia_conversas(id),
  id_turno         uuid references public.agentesia_turnos(id),
  id_externo       text,                                  -- id da mensagem na Helena
  autor            text not null check (autor in ('lead', 'ia', 'humano', 'automacao', 'sistema')),
  tipo             text not null default 'texto'
                   check (tipo in ('texto', 'audio', 'imagem', 'video', 'documento', 'figurinha',
                                   'localizacao', 'contato', 'template', 'nota')),
  texto            text,
  texto_extraido   text,                                  -- transcrição ou descrição da mídia
  url_midia        text,
  mime             text,
  enviada_em       timestamptz not null,                  -- horário do WhatsApp (ordena o buffer)
  registrada_em    timestamptz not null default now(),
  situacao_envio   text not null default 'recebida'
                   check (situacao_envio in ('recebida', 'pendente', 'enviada', 'entregue', 'lida', 'falhou')),
  erro             text
);
create unique index agentesia_mensagens_id_externo
  on public.agentesia_mensagens (id_escritorio, id_externo) where id_externo is not null;
create index agentesia_mensagens_lead on public.agentesia_mensagens (id_lead, enviada_em);

-- Fatos do lead, cada um com o trecho que prova.
create table public.agentesia_lead_fatos (
  id               uuid primary key default gen_random_uuid(),
  id_escritorio    uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_lead          uuid not null references public.agentesia_leads(id) on delete cascade,
  chave            text not null,                         -- data_acidente, tinha_carteira...
  valor            jsonb not null,
  trecho           text,                                  -- frase literal do lead
  id_mensagem      uuid references public.agentesia_mensagens(id) on delete set null,
  fonte            text not null check (fonte in ('extrator', 'equipe', 'sistema', 'documento')),
  confianca        numeric(3,2) check (confianca between 0 and 1),
  id_turno         uuid references public.agentesia_turnos(id) on delete set null,
  criado_em        timestamptz not null default now(),
  substituido_em   timestamptz
);
create index agentesia_lead_fatos_vigentes
  on public.agentesia_lead_fatos (id_lead, chave) where substituido_em is null;

-- Decisões das funções em código (qualificação, período de graça...).
create table public.agentesia_lead_decisoes (
  id              uuid primary key default gen_random_uuid(),
  id_escritorio   uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_lead         uuid not null references public.agentesia_leads(id) on delete cascade,
  id_turno        uuid references public.agentesia_turnos(id) on delete set null,
  funcao          text not null,
  entrada         jsonb not null,
  resultado       jsonb not null,
  criado_em       timestamptz not null default now()
);
create index agentesia_lead_decisoes_lead on public.agentesia_lead_decisoes (id_lead, criado_em desc);

-- Histórico de troca de etapa.
create table public.agentesia_lead_etapas_historico (
  id              uuid primary key default gen_random_uuid(),
  id_escritorio   uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_lead         uuid not null references public.agentesia_leads(id) on delete cascade,
  etapa_de        text,
  etapa_para      text not null,
  motivo          text,
  autor           text not null check (autor in ('codigo', 'humano', 'sistema')),
  id_turno        uuid references public.agentesia_turnos(id) on delete set null,
  criado_em       timestamptz not null default now()
);
create index agentesia_lead_etapas_historico_lead on public.agentesia_lead_etapas_historico (id_lead, criado_em);

-- Ficha do começo da conversa (resumo), uma por lead.
create table public.agentesia_lead_resumos (
  id                     uuid primary key default gen_random_uuid(),
  id_escritorio          uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_lead                uuid not null unique references public.agentesia_leads(id) on delete cascade,
  conteudo               jsonb not null,
  ate_mensagem           uuid references public.agentesia_mensagens(id) on delete set null,
  mensagens_resumidas    int not null default 0,
  versao                 int not null default 1,
  atualizado_em          timestamptz not null default now()
);

-- =============================================================================
-- 4. INTEGRAÇÕES (CRM, contrato, fila de ações)
-- =============================================================================

-- Um lead, um card.
create table public.agentesia_crm_cards (
  id                     uuid primary key default gen_random_uuid(),
  id_escritorio          uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_lead                uuid not null unique references public.agentesia_leads(id) on delete cascade,
  id_card_helena         text unique,
  id_painel_helena       text,
  id_etapa_crm_helena    text,
  situacao               text not null default 'pendente' check (situacao in ('ok', 'pendente', 'erro')),
  erro                   text,
  sincronizado_em        timestamptz,
  criado_em              timestamptz not null default now(),
  atualizado_em          timestamptz not null default now()
);

-- Contrato com versão, reserva e assinatura.
create table public.agentesia_contratos (
  id                      uuid primary key default gen_random_uuid(),
  id_escritorio           uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_lead                 uuid not null references public.agentesia_leads(id) on delete cascade,
  versao                  int  not null,
  provedor                text not null check (provedor in ('zapsign', 'tramitacao')),
  id_documento_externo    text,
  link                    text,
  dados                   jsonb not null,                 -- dados usados para gerar
  dados_hash              text not null,                  -- mesmos dados = mesmo link
  situacao                text not null default 'reservado'
                          check (situacao in ('reservado', 'gerado', 'substituido', 'assinado', 'cancelado', 'erro')),
  reservado_ate           timestamptz,
  gerado_em               timestamptz,
  assinado_em             timestamptz,
  signatarios             jsonb,
  erro                    text,
  criado_em               timestamptz not null default now(),
  atualizado_em           timestamptz not null default now(),
  unique (id_lead, versao)
);
create unique index agentesia_contratos_um_vigente
  on public.agentesia_contratos (id_lead) where situacao in ('reservado', 'gerado');
create unique index agentesia_contratos_documento
  on public.agentesia_contratos (provedor, id_documento_externo) where id_documento_externo is not null;

-- Pedidos para sistemas de fora (Helena, ZapSign...), com novas tentativas.
create table public.agentesia_acoes (
  id              uuid primary key default gen_random_uuid(),
  id_escritorio   uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_lead         uuid references public.agentesia_leads(id) on delete cascade,
  id_turno        uuid references public.agentesia_turnos(id) on delete set null,
  tipo            text not null,                          -- mover_card, por_tag, nota, gerar_contrato...
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

-- =============================================================================
-- 5. FOLLOW-UP (fila)
-- =============================================================================

create table public.agentesia_followups (
  id              uuid primary key default gen_random_uuid(),
  id_escritorio   uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_lead         uuid not null references public.agentesia_leads(id) on delete cascade,
  id_cadencia     uuid not null references public.agentesia_followup_cadencias(id) on delete cascade,
  id_passo        uuid not null references public.agentesia_followup_passos(id) on delete cascade,
  agendado_para   timestamptz not null,
  situacao        text not null default 'pendente'
                  check (situacao in ('pendente', 'reservado', 'enviando', 'enviado', 'cancelado', 'expirado', 'falhou')),
  motivo          text,                                   -- lead respondeu, humano assumiu, etapa final...
  reservado_ate   timestamptz,
  tentativas      int not null default 0,
  enviado_em      timestamptz,
  id_mensagem     uuid references public.agentesia_mensagens(id) on delete set null,
  criado_em       timestamptz not null default now(),
  atualizado_em   timestamptz not null default now()
);
create unique index agentesia_followups_um_aberto
  on public.agentesia_followups (id_lead) where situacao in ('pendente', 'reservado', 'enviando');
create index agentesia_followups_vencidos
  on public.agentesia_followups (agendado_para) where situacao = 'pendente';

-- =============================================================================
-- 6. OBSERVABILIDADE, CUSTO E QUALIDADE
-- =============================================================================

-- Problemas e avisos, com quem é o responsável.
create table public.agentesia_eventos (
  id               uuid primary key default gen_random_uuid(),
  id_escritorio    uuid references public.agentesia_escritorios(id) on delete cascade,
  id_lead          uuid references public.agentesia_leads(id) on delete cascade,
  id_turno         uuid references public.agentesia_turnos(id) on delete set null,
  tipo             text not null,                         -- trava_honorarios, transferencia, erro_helena...
  gravidade        text not null default 'aviso' check (gravidade in ('info', 'aviso', 'erro', 'critico')),
  responsavel      text check (responsavel in ('cliente', 'cadastro', 'provedor', 'lead', 'lawchat')),
  codigo_padrao    text,                                  -- P01..P26 do catálogo de auditoria
  descricao        text,
  detalhe          jsonb,
  nota_enviada     boolean not null default false,
  aviso_enviado    boolean not null default false,
  resolvido_em     timestamptz,
  criado_em        timestamptz not null default now()
);
create index agentesia_eventos_escritorio on public.agentesia_eventos (id_escritorio, criado_em desc);
create index agentesia_eventos_abertos on public.agentesia_eventos (criado_em) where resolvido_em is null;

-- Cada chamada de IA, com custo medido na fonte.
create table public.agentesia_chamadas_ia (
  id               uuid primary key default gen_random_uuid(),
  id_escritorio    uuid references public.agentesia_escritorios(id) on delete cascade,
  id_lead          uuid references public.agentesia_leads(id) on delete set null,
  id_turno         uuid references public.agentesia_turnos(id) on delete set null,
  papel            text not null,                         -- triagem, extrator, etapa, auditor, transcricao, resumo...
  provedor         text not null,
  modelo           text not null,
  tokens_entrada   int not null default 0,
  tokens_saida     int not null default 0,
  tokens_cache     int not null default 0,
  custo_usd        numeric(12,6) not null default 0,
  duracao_ms       int,
  tentativa        int not null default 1,
  sucesso          boolean not null,
  erro             text,
  criado_em        timestamptz not null default now()
);
create index agentesia_chamadas_ia_escritorio on public.agentesia_chamadas_ia (id_escritorio, criado_em);

-- Nota de qualidade por conversa (auditor de IA ou pessoa).
create table public.agentesia_avaliacoes (
  id               uuid primary key default gen_random_uuid(),
  id_escritorio    uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_lead          uuid not null references public.agentesia_leads(id) on delete cascade,
  id_conversa      uuid references public.agentesia_conversas(id) on delete set null,
  avaliador        text not null check (avaliador in ('auditor_ia', 'humano')),
  nota             numeric(4,2) check (nota between 0 and 10),
  criterios        jsonb,
  codigos_padrao   text[] not null default '{}',
  comentario       text,
  criado_em        timestamptz not null default now()
);

-- Cenários de teste (conversas simuladas) e o resultado de cada rodada.
create table public.agentesia_cenarios (
  id              uuid primary key default gen_random_uuid(),
  id_produto      uuid references public.agentesia_produtos(id) on delete cascade,
  nome            text not null,
  codigo_padrao   text,
  descricao       text,
  persona         jsonb not null default '{}'::jsonb,
  conversa        jsonb not null default '[]'::jsonb,
  esperado        jsonb not null default '{}'::jsonb,
  ativo           boolean not null default true,
  criado_em       timestamptz not null default now(),
  atualizado_em   timestamptz not null default now()
);

create table public.agentesia_cenario_execucoes (
  id                   uuid primary key default gen_random_uuid(),
  id_cenario           uuid not null references public.agentesia_cenarios(id) on delete cascade,
  id_agente_versao     uuid references public.agentesia_agente_versoes(id) on delete set null,
  id_produto_versao    uuid references public.agentesia_produto_versoes(id) on delete set null,
  resultado            text not null check (resultado in ('passou', 'falhou', 'erro')),
  detalhes             jsonb,
  criado_em            timestamptz not null default now()
);

-- =============================================================================
-- 7. GESTÃO (painel)
-- =============================================================================

-- Quem entra no painel. id = usuário do Supabase Auth.
create table public.agentesia_usuarios (
  id              uuid primary key,                       -- auth.users.id
  id_escritorio   uuid references public.agentesia_escritorios(id) on delete cascade, -- vazio = equipe LawChat
  nome            text not null,
  papel           text not null check (papel in ('admin_lawchat', 'gestor', 'atendente', 'leitura')),
  ativo           boolean not null default true,
  criado_em       timestamptz not null default now(),
  atualizado_em   timestamptz not null default now()
);

-- Quem mudou o quê no painel.
create table public.agentesia_alteracoes (
  id              uuid primary key default gen_random_uuid(),
  id_usuario      uuid references public.agentesia_usuarios(id) on delete set null,
  id_escritorio   uuid references public.agentesia_escritorios(id) on delete cascade,
  tabela          text not null,
  id_registro     uuid,
  acao            text not null check (acao in ('criou', 'alterou', 'publicou', 'arquivou', 'apagou', 'ligou', 'desligou')),
  antes           jsonb,
  depois          jsonb,
  criado_em       timestamptz not null default now()
);
create index agentesia_alteracoes_registro on public.agentesia_alteracoes (tabela, id_registro);

-- =============================================================================
-- 8. GATILHOS DE atualizado_em
-- =============================================================================
do $$
declare t text;
begin
  for t in
    select c.table_name
    from information_schema.columns c
    where c.table_schema = 'public'
      and c.table_name like 'agentesia\_%'
      and c.column_name = 'atualizado_em'
      and c.table_name not in ('agentesia_lead_resumos')
  loop
    execute format(
      'create trigger %I before update on public.%I
         for each row execute function public.agentesia_tocar_atualizado_em()',
      t || '_atualizado_em', t);
  end loop;
end
$$;

-- =============================================================================
-- 9. VISÕES PARA O PAINEL
-- =============================================================================

-- Funil: leads por etapa e estado.
create view public.agentesia_v_funil with (security_invoker = true) as
select l.id_escritorio, l.id_agente, e.codigo as etapa, e.ordem, l.estado, count(*) as leads
from public.agentesia_leads l
left join public.agentesia_agente_etapas e on e.id = l.id_etapa
group by l.id_escritorio, l.id_agente, e.codigo, e.ordem, l.estado;

-- Fila de follow-up: quantos vencidos e o mais atrasado.
create view public.agentesia_v_followup_fila with (security_invoker = true) as
select f.id_escritorio,
       count(*) filter (where f.agendado_para <= now())          as vencidos,
       count(*)                                                  as pendentes,
       min(f.agendado_para) filter (where f.agendado_para <= now()) as mais_antigo
from public.agentesia_followups f
where f.situacao = 'pendente'
group by f.id_escritorio;

-- Custo de IA por dia e escritório.
create view public.agentesia_v_custo_dia with (security_invoker = true) as
select c.id_escritorio,
       (c.criado_em at time zone 'America/Sao_Paulo')::date as dia,
       c.papel, c.modelo,
       count(*) as chamadas,
       sum(c.tokens_entrada) as tokens_entrada,
       sum(c.tokens_saida) as tokens_saida,
       sum(c.custo_usd) as custo_usd
from public.agentesia_chamadas_ia c
group by 1, 2, 3, 4;

-- Saúde: problemas abertos nas últimas 24 horas, por responsável.
create view public.agentesia_v_saude with (security_invoker = true) as
select ev.id_escritorio, ev.responsavel, ev.tipo, ev.gravidade,
       count(*) as ocorrencias, max(ev.criado_em) as ultima
from public.agentesia_eventos ev
where ev.criado_em > now() - interval '24 hours' and ev.resolvido_em is null
group by 1, 2, 3, 4;

-- =============================================================================
-- 10. RLS: ligado em tudo. Sem política = só o backend (service_role) acessa.
-- =============================================================================
do $$
declare t text;
begin
  for t in
    select tablename from pg_tables
    where schemaname = 'public' and tablename like 'agentesia\_%'
  loop
    execute format('alter table public.%I enable row level security', t);
  end loop;
end
$$;

commit;
