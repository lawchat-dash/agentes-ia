-- =============================================================================
-- cadastrar_escritorio.sql
-- Exemplo: cadastra UM escritório, o número de WhatsApp dele, a IA e as etapas.
-- Troque os valores marcados com <...> antes de rodar no SQL Editor.
-- A IA nasce em modo "teste": só responde aos números de teste.
-- =============================================================================

begin;

-- 1. Token da Helena no cofre do Supabase (Vault). O valor não fica em tabela nossa.
--    Guarde o id que este comando devolve e use no passo 2.
-- select vault.create_secret('<TOKEN_DA_HELENA>', 'helena_<nome_do_escritorio>');

with escritorio as (
  insert into agentesia_escritorios (nome, id_conta_helena, id_segredo_helena, config)
  values (
    '<Nome do Escritório>',
    '<companyId da Helena>'::uuid,
    '<id do segredo criado no passo 1>'::uuid,
    jsonb_build_object(
      'numeros_teste', jsonb_build_array('<5511999998888>'),   -- quem a IA responde em modo teste
      'espera_teste_s', 3
    )
  )
  returning id
),
canal as (
  insert into agentesia_canais (id_escritorio, id_canal_helena, numero_normalizado, tipo)
  select id, '<channelId da Helena>', '<5511999990000>', 'nao_oficial' from escritorio
  returning id, id_escritorio
),
agente as (
  insert into agentesia_agentes (id_escritorio, id_canal, nome, produto, situacao, modo, minutos_pausa_humano, config)
  select id_escritorio, id, 'Júlia', 'auxilio_acidente', 'ativo', 'teste', 15,
         jsonb_build_object(
           'honorarios', '<30% do valor recebido, pagos só ao final e só se der certo.>',
           'modelos', jsonb_build_object('extrator', 'gpt-4.1', 'etapa', 'gpt-4.1')
         )
  from canal
  returning id
)
-- Etapas. instrucao vazia = usa a instrução padrão do código (app/cerebro/agente.py).
insert into agentesia_agente_etapas (id_agente, codigo, ordem, tipo, principal)
select agente.id, e.codigo, e.ordem, e.tipo, e.principal
from agente,
     (values ('sdr', 1, 'conversa', true),
             ('periodo_graca', 2, 'conversa', false),
             ('closer', 3, 'conversa', false),
             ('coleta_dados', 4, 'conversa', false),
             ('analise_manual', 5, 'terminal', false),
             ('desqualificado', 6, 'terminal', false)) as e(codigo, ordem, tipo, principal);

commit;

-- Para passar a IA a responder todo mundo, depois dos testes:
-- update agentesia_agentes set modo = 'producao' where nome = 'Júlia';
-- Interruptor de emergência do escritório:
-- update agentesia_escritorios set ia_desligada = true where nome = '<Nome do Escritório>';
