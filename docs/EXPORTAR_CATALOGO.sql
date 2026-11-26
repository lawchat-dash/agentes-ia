-- =============================================================================
-- Exporta o CATÁLOGO do agents-lawchat-main (Supabase AGENT WEAVER) num JSON só.
-- Só leitura: não altera nada. Não lê leads, contatos, mensagens nem dados de clientes.
--
-- Como usar:
--   1. Supabase > projeto AGENT WEAVER > SQL Editor > New query.
--   2. Cole tudo isto e clique em Run.
--   3. No resultado (uma linha, coluna "catalogo"): botão de exportar/baixar o resultado em CSV,
--      ou copie a célula e salve num arquivo .json.
--   4. No painel LawChat IA: LawChat > Produtos (catálogo) > Importar catálogo > envie o arquivo.
--      Ou no servidor: .venv/Scripts/python -m app.catalogo_importar arquivo.json --simular
-- =============================================================================
select json_build_object(
  'formato', 'agentesia-catalogo-v1',
  'sistemaia_biblioteca_produtos',
    coalesce((select json_agg(p order by p.nome) from public.sistemaia_biblioteca_produtos p), '[]'::json),
  'sistemaia_biblioteca_agentes',
    coalesce((select json_agg(a order by a.id_produto_biblioteca, a.ordem) from public.sistemaia_biblioteca_agentes a), '[]'::json),
  'sistemaia_frases_troca',
    coalesce((select json_agg(f order by f.id_produto_biblioteca nulls first, f.ordem) from public.sistemaia_frases_troca f), '[]'::json),
  'sistemaia_biblioteca_followups',
    coalesce((select json_agg(u order by u.id_produto_biblioteca, u.ordem) from public.sistemaia_biblioteca_followups u), '[]'::json),
  'sistemaia_biblioteca_conhecimento',
    coalesce((select json_agg(c order by c.id_produto_biblioteca, c.ordem) from public.sistemaia_biblioteca_conhecimento c), '[]'::json)
) as catalogo;
