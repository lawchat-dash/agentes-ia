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
