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
