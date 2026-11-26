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
