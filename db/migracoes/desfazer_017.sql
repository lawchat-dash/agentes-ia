-- Desfaz a 017: tira a tabela de adicionais e as colunas novas dos planos (os planos carregados ficam).
begin;
drop table if exists public.agentesia_adicionais;
alter table public.agentesia_planos
  drop column if exists preco_anual_brl, drop column if exists sob_proposta, drop column if exists usuarios,
  drop column if exists canais_whatsapp, drop column if exists canais_instagram, drop column if exists cria_agentes,
  drop column if exists ia_inclusa, drop column if exists selo, drop column if exists icone;
commit;
