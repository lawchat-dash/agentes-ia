// Postgres local em memória, já com as tabelas agentesia_*, para testar o código
// sem tocar no Supabase. Uso: node servidor_local.mjs [porta]
// Conexão: postgresql://postgres:postgres@127.0.0.1:55432/postgres
import { PGlite } from '@electric-sql/pglite';
import { PGLiteSocketServer } from '@electric-sql/pglite-socket';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const aqui = path.dirname(fileURLToPath(import.meta.url));
const porta = Number(process.argv[2] ?? 55432);

const db = new PGlite();
await db.exec(fs.readFileSync(path.join(aqui, '../migracoes/001_agentesia_nucleo.sql'), 'utf8'));
await db.exec(fs.readFileSync(path.join(aqui, '../migracoes/002_agentesia_gestao.sql'), 'utf8'));
await db.exec(fs.readFileSync(path.join(aqui, '../migracoes/003_agentesia_conhecimento.sql'), 'utf8'));
await db.exec(fs.readFileSync(path.join(aqui, '../migracoes/004_agentesia_canal_liberado.sql'), 'utf8'));
await db.exec(fs.readFileSync(path.join(aqui, '../migracoes/005_agentesia_midia_pendente.sql'), 'utf8'));
await db.exec(fs.readFileSync(path.join(aqui, '../migracoes/006_agentesia_conta_helena.sql'), 'utf8'));
await db.exec(fs.readFileSync(path.join(aqui, '../migracoes/007_agentesia_cobranca.sql'), 'utf8'));
await db.exec(fs.readFileSync(path.join(aqui, '../migracoes/008_agentesia_produto_versoes.sql'), 'utf8'));
await db.exec(fs.readFileSync(path.join(aqui, '../migracoes/009_agentesia_roteiros.sql'), 'utf8'));
await db.exec(fs.readFileSync(path.join(aqui, '../migracoes/010_agentesia_indices_painel.sql'), 'utf8'));
await db.exec(fs.readFileSync(path.join(aqui, '../migracoes/011_agentesia_indices_execucoes.sql'), 'utf8'));
await db.exec(fs.readFileSync(path.join(aqui, '../migracoes/012_agentesia_relatorios.sql'), 'utf8'));
await db.exec(fs.readFileSync(path.join(aqui, '../migracoes/013_agentesia_relatorios_crm.sql'), 'utf8'));
await db.exec(fs.readFileSync(path.join(aqui, '../migracoes/014_agentesia_isolamento.sql'), 'utf8'));
await db.exec(fs.readFileSync(path.join(aqui, '../migracoes/015_agentesia_central_notificacoes.sql'), 'utf8'));
await db.exec(fs.readFileSync(path.join(aqui, '../migracoes/016_agentesia_agente_arquivado.sql'), 'utf8'));
await db.exec(fs.readFileSync(path.join(aqui, '../migracoes/017_agentesia_planos_recursos.sql'), 'utf8'));
await db.exec(fs.readFileSync(path.join(aqui, '../migracoes/018_agentesia_log_plataforma.sql'), 'utf8'));
await db.exec(fs.readFileSync(path.join(aqui, '../migracoes/019_agentesia_roteiro_gravacao.sql'), 'utf8'));
// Imitação mínima do Supabase Vault, só para o teste (no Supabase o valor fica cifrado).
await db.exec(`
  create schema if not exists vault;
  create table vault.decrypted_secrets (id uuid primary key default gen_random_uuid(), name text, decrypted_secret text);
  create function vault.create_secret(valor text, nome text default null) returns uuid language sql as
    $$ insert into vault.decrypted_secrets (name, decrypted_secret) values (nome, valor) returning id $$;
  create function vault.update_secret(id_segredo uuid, valor text) returns void language sql as
    $$ update vault.decrypted_secrets set decrypted_secret = valor where id = id_segredo $$;
`);

const servidor = new PGLiteSocketServer({ db, port: porta, host: '127.0.0.1', maxConnections: 10 });
await servidor.start();
console.log(`pronto na porta ${porta}`);

const parar = async () => { await servidor.stop(); await db.close(); process.exit(0); };
process.on('SIGINT', parar);
process.on('SIGTERM', parar);
