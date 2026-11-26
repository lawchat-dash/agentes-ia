// Aplica as migrações num Postgres embutido (PGlite) e confere as regras do banco.
// Uso: node teste_migracoes.mjs ../migracoes
import { PGlite } from '@electric-sql/pglite';
import fs from 'node:fs';
import path from 'node:path';

const pasta = process.argv[2] ?? '../migracoes';
const ler = (f) => fs.readFileSync(path.join(pasta, f), 'utf8');
const db = new PGlite();

let ok = 0, falhas = 0;
async function deve(nome, fn) {
  try { await fn(); ok++; console.log('OK   ', nome); }
  catch (e) { falhas++; console.log('FALHA', nome, '->', e.message); }
}
async function deveFalhar(nome, sql, params = []) {
  try { await db.query(sql, params); falhas++; console.log('FALHA', nome, '-> deveria ter sido recusado'); }
  catch (e) { ok++; console.log('OK   ', nome, '(recusado: ' + e.message.split('\n')[0] + ')'); }
}
const um = async (sql, p = []) => (await db.query(sql, p)).rows[0];

// Tabela que já existe no projeto, para provar que a migração não mexe nela.
await db.exec(`create table public.lead (ulid uuid primary key, nome text); insert into public.lead values (gen_random_uuid(), 'antigo');`);

await deve('aplica 001', () => db.exec(ler('001_agentesia_nucleo.sql')));

const n = await um(`select count(*)::int n from pg_tables where schemaname='public' and tablename like 'agentesia\\_%'`);
console.log('tabelas agentesia_:', n.n);
await deve('12 tabelas', async () => { if (n.n !== 12) throw new Error(n.n); });
const semRls = await db.query(`select tablename from pg_tables where schemaname='public' and tablename like 'agentesia\\_%' and not rowsecurity`);
await deve('RLS ligado em todas', async () => { if (semRls.rows.length) throw new Error(JSON.stringify(semRls.rows)); });

const esc = (await um(`insert into agentesia_escritorios (nome) values ('Escritório Teste') returning id`)).id;
const can = (await um(`insert into agentesia_canais (id_escritorio, numero_normalizado) values ($1,'5511999990000') returning id`, [esc])).id;
const ag = await um(`insert into agentesia_agentes (id_escritorio, id_canal, nome) values ($1,$2,'Júlia') returning id, modo, situacao, produto`, [esc, can]);
await deve('agente nasce pausado, em teste, Auxílio-Acidente', async () => {
  if (ag.modo !== 'teste' || ag.situacao !== 'pausado' || ag.produto !== 'auxilio_acidente') throw new Error(JSON.stringify(ag));
});
await deveFalhar('um agente por canal', `insert into agentesia_agentes (id_escritorio, id_canal, nome) values ($1,$2,'Outra')`, [esc, can]);

const et = (await um(`insert into agentesia_agente_etapas (id_agente, codigo, ordem, principal, instrucao) values ($1,'sdr',1,true,'Você é a Júlia') returning id`, [ag.id])).id;
await deveFalhar('só uma etapa principal', `insert into agentesia_agente_etapas (id_agente, codigo, ordem, principal) values ($1,'closer',2,true)`, [ag.id]);
await deveFalhar('temperatura acima de 1', `insert into agentesia_agente_etapas (id_agente, codigo, ordem, temperatura) values ($1,'x',3,1.5)`, [ag.id]);

const cont = (await um(`insert into agentesia_contatos (id_escritorio, id_contato_helena, nome, telefone_normalizado) values ($1,'c1','Maria','5511988887777') returning id`, [esc])).id;
const lead = (await um(`insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_agente, id_etapa) values ($1,$2,$3,$4,$5) returning id`, [esc, cont, can, ag.id, et])).id;
await deveFalhar('um lead por contato e canal', `insert into agentesia_leads (id_escritorio, id_contato, id_canal) values ($1,$2,$3)`, [esc, cont, can]);

await deve('webhook recebido', () => db.query(`insert into agentesia_eventos_recebidos (id_escritorio, origem, id_externo, payload) values ($1,'helena','w1','{}')`, [esc]));
await deveFalhar('webhook repetido', `insert into agentesia_eventos_recebidos (id_escritorio, origem, id_externo, payload) values ($1,'helena','w1','{}')`, [esc]);

const turno = (await um(`insert into agentesia_turnos (id_escritorio, id_lead, modo) values ($1,$2,'teste') returning id`, [esc, lead])).id;
const msg = (await um(`insert into agentesia_mensagens (id_escritorio, id_lead, id_turno, id_externo, autor, texto, enviada_em) values ($1,$2,$3,'m1','lead','sofri um acidente em março',now()) returning id`, [esc, lead, turno])).id;
await deveFalhar('mensagem repetida pelo id', `insert into agentesia_mensagens (id_escritorio, id_lead, id_externo, autor, texto, enviada_em) values ($1,$2,'m1','lead','oi',now())`, [esc, lead]);

await deve('fato com trecho', () => db.query(`insert into agentesia_lead_fatos (id_escritorio, id_lead, chave, valor, trecho, id_mensagem, fonte, id_turno) values ($1,$2,'mes_acidente','"março"','sofri um acidente em março',$3,'extrator',$4)`, [esc, lead, msg, turno]));
await deve('chamada de IA', () => db.query(`insert into agentesia_chamadas_ia (id_escritorio, id_turno, papel, modelo, tokens_entrada, tokens_saida, sucesso) values ($1,$2,'extrator','modelo-x',900,120,true)`, [esc, turno]));
await deve('evento com responsável', () => db.query(`insert into agentesia_eventos (id_escritorio, id_lead, tipo, responsavel) values ($1,$2,'erro_helena','provedor')`, [esc, lead]));
await deveFalhar('responsável inválido', `insert into agentesia_eventos (tipo, responsavel) values ('x','ninguem')`);

await deve('atualizado_em muda no update', async () => {
  const a = await um(`select atualizado_em from agentesia_leads where id=$1`, [lead]);
  await new Promise(r => setTimeout(r, 20));
  await db.query(`update agentesia_leads set estado='pausado' where id=$1`, [lead]);
  const b = await um(`select atualizado_em from agentesia_leads where id=$1`, [lead]);
  if (!(new Date(b.atualizado_em) > new Date(a.atualizado_em))) throw new Error('não mudou');
});

await deve('apagar o escritório apaga tudo dele', async () => {
  await db.query(`delete from agentesia_escritorios where id=$1`, [esc]);
  const r = await um(`select (select count(*) from agentesia_leads)::int l, (select count(*) from agentesia_mensagens)::int m, (select count(*) from agentesia_lead_fatos)::int f, (select count(*) from agentesia_contatos)::int c`);
  if (r.l || r.m || r.f || r.c) throw new Error(JSON.stringify(r));
});

// ---------------------------------------------------------------- 002: gestão
await deve('aplica 002', () => db.exec(ler('002_agentesia_gestao.sql')));
await deve('29 tabelas e RLS em todas', async () => {
  const t = await um(`select count(*)::int n, count(*) filter (where not rowsecurity)::int sem from pg_tables where schemaname='public' and tablename like 'agentesia\\_%'`);
  if (t.n !== 29 || t.sem !== 0) throw new Error(JSON.stringify(t));
});
const esc2 = (await um(`insert into agentesia_escritorios (nome) values ('Escritório Dois') returning id, situacao`));
await deve('escritório nasce ativo', async () => { if (esc2.situacao !== 'ativo') throw new Error(esc2.situacao); });
await deve('usuário gestor do escritório', () => db.query(`insert into agentesia_usuarios (email, nome, senha_hash, papel, id_escritorio) values ('gestor@x.com','Gestor','h','gestor',$1)`, [esc2.id]));
await deve('admin LawChat sem escritório', () => db.query(`insert into agentesia_usuarios (email, nome, senha_hash, papel) values ('admin@x.com','Admin','h','admin_lawchat')`));
await deveFalhar('gestor sem escritório', `insert into agentesia_usuarios (email, nome, senha_hash, papel) values ('g2@x.com','G','h','gestor')`);
await deveFalhar('admin com escritório', `insert into agentesia_usuarios (email, nome, senha_hash, papel, id_escritorio) values ('a2@x.com','A','h','admin_lawchat',$1)`, [esc2.id]);
await deve('dono LawChat sem escritório', () => db.query(`insert into agentesia_usuarios (email, nome, senha_hash, papel) values ('dono@x.com','Dono','h','dono_lawchat')`));
await deveFalhar('dono com escritório', `insert into agentesia_usuarios (email, nome, senha_hash, papel, id_escritorio) values ('d2@x.com','D','h','dono_lawchat',$1)`, [esc2.id]);
await deveFalhar('papel inventado', `insert into agentesia_usuarios (email, nome, senha_hash, papel) values ('op@x.com','O','h','operador')`);
await deve('aviso à equipe', () => db.query(`insert into agentesia_notificacoes (id_escritorio, tipo_evento, nome, modelo_mensagem) values ($1,'etapa:closer','Qualificado','{{nome}}')`, [esc2.id]));
await deveFalhar('aviso repetido no mesmo evento', `insert into agentesia_notificacoes (id_escritorio, tipo_evento, nome, modelo_mensagem) values ($1,'etapa:closer','De novo','x')`, [esc2.id]);
await deve('recebido da ZapSign', () => db.query(`insert into agentesia_eventos_recebidos (origem, id_externo, payload) values ('zapsign','doc:evt','{}')`));
await deve('responsável LawChat no escritório', () => db.query(`update agentesia_escritorios set id_responsavel = (select id from agentesia_usuarios where email='dono@x.com') where id = $1`, [esc2.id]));
await deveFalhar('e-mail com maiúscula', `insert into agentesia_usuarios (email, nome, senha_hash, papel) values ('Admin@X.com','A','h','admin_lawchat')`);
await deve('integração helena', () => db.query(`insert into agentesia_integracoes (id_escritorio, tipo) values ($1,'helena')`, [esc2.id]));
await deveFalhar('integração repetida', `insert into agentesia_integracoes (id_escritorio, tipo) values ($1,'helena')`, [esc2.id]);
await deve('colunas novas no núcleo', async () => {
  const c = await um(`select count(*)::int n from information_schema.columns where table_name in ('agentesia_agente_etapas','agentesia_agentes','agentesia_eventos') and column_name in ('instrucao_travada','numeros_teste','resolvido_em','resolvido_por')`);
  if (c.n !== 4) throw new Error(c.n);
});
await deve('ficha de memória: uma por lead e some com o lead', async () => {
  const can2 = (await um(`insert into agentesia_canais (id_escritorio, numero_normalizado) values ($1,'5511999990002') returning id`, [esc2.id])).id;
  const cont2 = (await um(`insert into agentesia_contatos (id_escritorio, telefone_normalizado) values ($1,'5511988880002') returning id`, [esc2.id])).id;
  const lead2 = (await um(`insert into agentesia_leads (id_escritorio, id_contato, id_canal) values ($1,$2,$3) returning id`, [esc2.id, cont2, can2])).id;
  await db.query(`insert into agentesia_lead_resumo (id_lead, id_escritorio, resumo, mensagens_resumidas) values ($1,$2,'- Quem é: Maria',20)`, [lead2, esc2.id]);
  let repetida = false;
  try { await db.query(`insert into agentesia_lead_resumo (id_lead, id_escritorio, resumo) values ($1,$2,'outra')`, [lead2, esc2.id]); repetida = true; } catch (e) {}
  if (repetida) throw new Error('aceitou duas fichas para o mesmo lead');
  await db.query(`delete from agentesia_leads where id=$1`, [lead2]);
  const r = await um(`select count(*)::int n from agentesia_lead_resumo where id_lead=$1`, [lead2]);
  if (r.n !== 0) throw new Error(r.n);
});
// 003: base de conhecimento por papel e perguntas sem resposta.
await deve('aplica 003', () => db.exec(ler('003_agentesia_conhecimento.sql')));
await deve('003: RLS na tabela de lacunas', async () => {
  const r = await um(`select rowsecurity from pg_tables where tablename='agentesia_conhecimento_lacunas'`);
  if (!r || !r.rowsecurity) throw new Error(JSON.stringify(r));
});
await deve('003: lacuna aberta repetida soma em vezes', async () => {
  const esc3 = (await um(`insert into agentesia_escritorios (nome) values ('Base Ltda') returning id`)).id;
  const can3 = (await um(`insert into agentesia_canais (id_escritorio, numero_normalizado) values ($1,'5511999990003') returning id`, [esc3])).id;
  const ag3 = (await um(`insert into agentesia_agentes (id_escritorio, id_canal, nome) values ($1,$2,'Base') returning id`, [esc3, can3])).id;
  const upsert = `insert into agentesia_conhecimento_lacunas (id_escritorio, id_agente, papel, pergunta, pergunta_normalizada)
                  values ($1,$2,'closer','Tem estacionamento?','tem estacionamento')
                  on conflict (id_agente, pergunta_normalizada) where situacao = 'aberta'
                  do update set vezes = agentesia_conhecimento_lacunas.vezes + 1 returning vezes`;
  await db.query(upsert, [esc3, ag3]);
  const r = await um(upsert, [esc3, ag3]);
  if (r.vezes !== 2) throw new Error(JSON.stringify(r));
  await db.query(`update agentesia_conhecimento_lacunas set situacao='respondida' where id_agente=$1`, [ag3]);
  const nova = await um(upsert, [esc3, ag3]);
  if (nova.vezes !== 1) throw new Error('respondida não deveria somar: ' + JSON.stringify(nova));
  // documento virtual: um de cada tipo por agente; trecho com fonte e papéis.
  const faq = (await um(`insert into agentesia_documentos (id_escritorio, id_agente, tipo, nome, formato, tamanho_bytes, texto, caracteres)
                         values ($1,$2,'faq','FAQ','texto',1,'x',1) returning id`, [esc3, ag3])).id;
  let dupla = false;
  try { await db.query(`insert into agentesia_documentos (id_escritorio, id_agente, tipo, nome, formato, tamanho_bytes, texto, caracteres)
                        values ($1,$2,'faq','FAQ 2','texto',1,'y',1)`, [esc3, ag3]); dupla = true; } catch (e) {}
  if (dupla) throw new Error('aceitou dois documentos virtuais de FAQ no mesmo agente');
  await db.query(`insert into agentesia_documento_trechos (id_documento, id_agente, id_escritorio, ordem, conteudo, vetor, papeis, fonte, hash)
                  values ($1,$2,$3,0,'Pergunta: x',array[0.1,0.2]::real[],'{closer}','faq','h1')`, [faq, ag3, esc3]);
  let fonteRuim = false;
  try { await db.query(`insert into agentesia_documento_trechos (id_documento, id_agente, ordem, conteudo, vetor, fonte)
                        values ($1,$2,1,'x',array[0.1]::real[],'outra')`, [faq, ag3]); fonteRuim = true; } catch (e) {}
  if (fonteRuim) throw new Error('aceitou fonte inválida');
});
await deve('desfazer 003 mantém a 002', async () => {
  await db.exec(ler('desfazer_003.sql'));
  const t = await um(`select count(*)::int n from pg_tables where tablename='agentesia_conhecimento_lacunas'`);
  const c = await um(`select count(*)::int n from information_schema.columns where table_name='agentesia_documento_trechos' and column_name in ('hash','papeis','fonte')`);
  if (t.n !== 0 || c.n !== 0) throw new Error(JSON.stringify({ t, c }));
});
await deve('aplica 003 de novo', () => db.exec(ler('003_agentesia_conhecimento.sql')));
// 004: o produto na lixeira solta o número (id_canal do agente aceita null; o número anterior fica de histórico).
await deve('aplica 004', () => db.exec(ler('004_agentesia_canal_liberado.sql')));
await deve('004: agente sem número; o número solto vai para outro agente; desfazer para com quem sobrou', async () => {
  const esc4 = (await um(`insert into agentesia_escritorios (nome) values ('Lixeira Ltda') returning id`)).id;
  const can4 = (await um(`insert into agentesia_canais (id_escritorio, numero_normalizado) values ($1,'5511999990004') returning id`, [esc4])).id;
  const a = (await um(`insert into agentesia_agentes (id_escritorio, id_canal, nome) values ($1,$2,'A') returning id`, [esc4, can4])).id;
  let dois = false;
  try { await db.query(`insert into agentesia_agentes (id_escritorio, id_canal, nome) values ($1,$2,'X')`, [esc4, can4]); dois = true; } catch (e) {}
  if (dois) throw new Error('aceitou dois agentes no mesmo número');
  await db.query(`update agentesia_agentes set id_canal_anterior = id_canal, id_canal = null, canal_liberado_em = now() where id=$1`, [a]);
  const b = (await um(`insert into agentesia_agentes (id_escritorio, id_canal, nome) values ($1,$2,'B') returning id`, [esc4, can4])).id;
  await db.query(`insert into agentesia_agentes (id_escritorio, nome) values ($1,'C sem número')`, [esc4]);
  let parou = false;
  try { await db.exec(ler('desfazer_004.sql')); } catch (e) { parou = /sem número/.test(String(e.message)); await db.exec('rollback'); }
  if (!parou) throw new Error('o desfazer deveria parar com agente sem número');
  const r = await um(`select is_nullable from information_schema.columns where table_name='agentesia_agentes' and column_name='id_canal'`);
  if (r.is_nullable !== 'YES') throw new Error('o desfazer parado não pode deixar meia mudança');
  // Tirando quem sobrou (o A não volta: o número dele é do B), o desfazer passa.
  await db.query(`delete from agentesia_agentes where id_escritorio=$1 and id <> $2`, [esc4, b]);
  await db.exec(ler('desfazer_004.sql'));
  const c = await um(`select count(*)::int n from information_schema.columns where table_name='agentesia_agentes' and column_name in ('id_canal_anterior','canal_liberado_em')`);
  if (c.n !== 0) throw new Error(JSON.stringify(c));
});
await deve('desfazer 004 roda duas vezes', () => db.exec(ler('desfazer_004.sql')));
await deve('aplica 004 de novo', () => db.exec(ler('004_agentesia_canal_liberado.sql')));
await deve('004 aplica duas vezes', () => db.exec(ler('004_agentesia_canal_liberado.sql')));
await deve('desfazer 004: dois agentes com o mesmo número anterior, volta só o último', async () => {
  const esc5 = (await um(`insert into agentesia_escritorios (nome) values ('Dupla Ltda') returning id`)).id;
  const can5 = (await um(`insert into agentesia_canais (id_escritorio, numero_normalizado) values ($1,'5511999990005') returning id`, [esc5])).id;
  const velho = (await um(`insert into agentesia_agentes (id_escritorio, nome, id_canal_anterior, canal_liberado_em)
                           values ($1,'Velho',$2, now() - interval '2 days') returning id`, [esc5, can5])).id;
  const novo = (await um(`insert into agentesia_agentes (id_escritorio, nome, id_canal_anterior, canal_liberado_em)
                          values ($1,'Novo',$2, now()) returning id`, [esc5, can5])).id;
  let parou = false;
  try { await db.exec(ler('desfazer_004.sql')); } catch (e) { parou = /Velho/.test(String(e.message)) && !/Novo/.test(String(e.message)); await db.exec('rollback'); }
  if (!parou) throw new Error('deveria devolver o número ao Novo e parar só pelo Velho');
  await db.query(`delete from agentesia_agentes where id=$1`, [velho]);
  await db.exec(ler('desfazer_004.sql'));
  const r = await um(`select id_canal from agentesia_agentes where id=$1`, [novo]);
  if (r.id_canal !== can5) throw new Error(JSON.stringify(r));
});
// 006: conta da Helena (onboarding, cache de recursos, histórico de etapa, chave do telefone, falha de admin).
await deve('aplica 006', () => db.exec(ler('006_agentesia_conta_helena.sql')));
await deve('006 aplica duas vezes', () => db.exec(ler('006_agentesia_conta_helena.sql')));
await deve('006: RLS nas tabelas novas', async () => {
  const r = await um(`select count(*) filter (where rowsecurity)::int n from pg_tables where tablename in ('agentesia_helena_recursos','agentesia_lead_etapas')`);
  if (r.n !== 2) throw new Error(JSON.stringify(r));
});
await deve('006: histórico de etapa, chave do telefone, recurso único e alteração com erro', async () => {
  const esc6 = (await um(`insert into agentesia_escritorios (nome) values ('Conta Ltda') returning id, onboarding, dados_helena`));
  if (JSON.stringify(esc6.onboarding) !== '{}' || JSON.stringify(esc6.dados_helena) !== '{}') throw new Error('onboarding e dados_helena deveriam nascer {}');
  const can6 = (await um(`insert into agentesia_canais (id_escritorio, numero_normalizado) values ($1,'5511999990006') returning id`, [esc6.id])).id;
  const ag6 = (await um(`insert into agentesia_agentes (id_escritorio, id_canal, nome) values ($1,$2,'Seis') returning id`, [esc6.id, can6])).id;
  const sdr = (await um(`insert into agentesia_agente_etapas (id_agente, codigo, ordem, principal) values ($1,'sdr',1,true) returning id`, [ag6])).id;
  const closer = (await um(`insert into agentesia_agente_etapas (id_agente, codigo, ordem) values ($1,'closer',2) returning id`, [ag6])).id;
  const c9 = await um(`insert into agentesia_contatos (id_escritorio, telefone_normalizado) values ($1,'5511988887777') returning id, telefone_chave`, [esc6.id]);
  if (c9.telefone_chave !== '551188887777') throw new Error('chave: ' + c9.telefone_chave);
  const c8 = await um(`insert into agentesia_contatos (id_escritorio, telefone_normalizado) values ($1,'551188887777') returning telefone_chave`, [esc6.id]);
  if (c8.telefone_chave !== '551188887777') throw new Error('chave sem o 9: ' + c8.telefone_chave);
  const fora = await um(`insert into agentesia_contatos (id_escritorio, telefone_normalizado) values ($1,'14155550123') returning telefone_chave`, [esc6.id]);
  if (fora.telefone_chave !== null) throw new Error('número de fora do Brasil não tem chave');
  const lead6 = (await um(`insert into agentesia_leads (id_escritorio, id_contato, id_canal, id_agente, id_etapa) values ($1,$2,$3,$4,$5) returning id`, [esc6.id, c9.id, can6, ag6, sdr])).id;
  await db.query(`update agentesia_leads set estado='pausado' where id=$1`, [lead6]);          // sem troca de etapa
  await db.exec('begin');
  await db.query(`select set_config('agentesia.origem_etapa', 'equipe', true)`);
  await db.query(`update agentesia_leads set id_etapa=$2 where id=$1`, [lead6, closer]);
  await db.exec('commit');
  const turno6 = (await um(`insert into agentesia_turnos (id_escritorio, id_lead, modo) values ($1,$2,'teste') returning id`, [esc6.id, lead6])).id;
  await db.query(`update agentesia_leads set id_etapa=$2 where id=$1`, [lead6, sdr]);       // turno em andamento: IA
  const h = (await db.query(`select etapa_de, etapa_para, origem, id_turno from agentesia_lead_etapas where id_lead=$1 order by criado_em, etapa_de nulls first`, [lead6])).rows;
  const visto = h.map((x) => `${x.etapa_de ?? '-'}>${x.etapa_para}:${x.origem}`).join(' ');
  if (visto !== '->sdr:entrada sdr>closer:equipe closer>sdr:ia' || h[2].id_turno !== turno6) throw new Error(visto);
  await db.query(`insert into agentesia_helena_recursos (id_escritorio, tipo, id_externo, nome) values ($1,'etiqueta','t1','SDR')`, [esc6.id]);
  let repetido = false;
  try { await db.query(`insert into agentesia_helena_recursos (id_escritorio, tipo, id_externo) values ($1,'etiqueta','t1')`, [esc6.id]); repetido = true; } catch (e) {}
  if (repetido) throw new Error('aceitou o mesmo recurso duas vezes');
  let tipoRuim = false;
  try { await db.query(`insert into agentesia_helena_recursos (id_escritorio, tipo, id_externo) values ($1,'contato','x')`, [esc6.id]); tipoRuim = true; } catch (e) {}
  if (tipoRuim) throw new Error('aceitou tipo inválido');
  const alt = await um(`insert into agentesia_alteracoes (id_escritorio, tabela, acao) values ($1,'agentesia_escritorios','sincronizou') returning situacao`, [esc6.id]);
  if (alt.situacao !== 'ok') throw new Error(alt.situacao);
  await db.query(`insert into agentesia_alteracoes (id_escritorio, tabela, acao, situacao, erro) values ($1,'x','sincronizou','erro','token_recusado')`, [esc6.id]);
});
// ---------------------------------------------------------------- 007: cobrança em R$ (carteira e livro)
await deve('aplica 007', () => db.exec(ler('007_agentesia_cobranca.sql')));
await deve('007 aplica duas vezes', () => db.exec(ler('007_agentesia_cobranca.sql')));
await deve('007: RLS nas tabelas novas', async () => {
  const t = await um(`select count(*) filter (where not rowsecurity)::int sem, count(*)::int n from pg_tables where tablename in
    ('agentesia_cobranca_config','agentesia_planos','agentesia_carteiras','agentesia_carteira_movimentos','agentesia_recargas','agentesia_pagamento_eventos','agentesia_assinaturas')`);
  if (t.n !== 7 || t.sem) throw new Error(JSON.stringify(t));
});
await deve('007: débito com cotação e markup, bônus primeiro, livro = carteira, recarga uma vez só', async () => {
  const e7 = (await um(`insert into agentesia_escritorios (nome) values ('Cobra Ltda') returning id`)).id;
  await db.query(`insert into agentesia_cobranca_config (cotacao_usd_brl, markup, motivo) values (5.00, 2.00, 'teste')`);
  const p = (await um(`insert into agentesia_planos (codigo, nome, preco_mensal_brl, bonus_mensal_brl) values ('basico7','Básico',297,10) returning id`)).id;
  await db.query(`insert into agentesia_carteiras (id_escritorio, id_plano, modo) values ($1,$2,'pre_pago')`, [e7, p]);
  await db.query(`select agentesia_renovar_bonus($1,'2026-11')`, [e7]);
  await db.query(`select agentesia_renovar_bonus($1,'2026-11')`, [e7]);          // repetido: nada muda
  const ch = await um(`insert into agentesia_chamadas_ia (id_escritorio, papel, modelo, custo_usd, sucesso) values ($1,'etapa','x',1.5,true) returning custo_brl, custo_brl_real, cobranca`, [e7]);
  if (Number(ch.custo_brl) !== 15 || Number(ch.custo_brl_real) !== 7.5 || ch.cobranca !== 'pendente') throw new Error(JSON.stringify(ch));
  const d = await db.query(`select * from agentesia_debitar_consumo($1)`, [e7]);
  const d2 = await db.query(`select * from agentesia_debitar_consumo($1)`, [e7]);
  if (d.rows.length !== 1 || Number(d.rows[0].valor) !== 15 || d2.rows.length !== 0) throw new Error(JSON.stringify([d.rows, d2.rows]));
  const c = await um(`select saldo_brl, bonus_brl, pausado_por_saldo from agentesia_carteiras where id_escritorio=$1`, [e7]);
  if (Number(c.saldo_brl) !== -5 || Number(c.bonus_brl) !== 0 || !c.pausado_por_saldo) throw new Error(JSON.stringify(c));
  const r = (await um(`insert into agentesia_recargas (id_escritorio, valor_brl) values ($1, 50) returning id`, [e7])).id;
  const m1 = (await um(`select agentesia_confirmar_recarga($1) as m`, [r])).m;
  const m2 = (await um(`select agentesia_confirmar_recarga($1) as m`, [r])).m;
  const c2 = await um(`select saldo_brl, pausado_por_saldo from agentesia_carteiras where id_escritorio=$1`, [e7]);
  if (m1 !== m2 || Number(c2.saldo_brl) !== 45 || c2.pausado_por_saldo) throw new Error(JSON.stringify({ m1, m2, c2 }));
  const conf = await um(`select diferenca from agentesia_v_carteira_conferencia where id_escritorio=$1`, [e7]);
  if (Number(conf.diferenca) !== 0) throw new Error('livro diferente da carteira: ' + conf.diferenca);
  let mexeu = false;
  try { await db.query(`update agentesia_carteiras set saldo_brl = 999 where id_escritorio=$1`, [e7]); mexeu = true; } catch (e) {}
  try { await db.query(`update agentesia_carteira_movimentos set valor_brl = 1 where id_escritorio=$1`, [e7]); mexeu = true; } catch (e) {}
  if (mexeu) throw new Error('saldo ou livro alterado por fora do lançamento');
  await db.query(`delete from agentesia_cobranca_config where motivo = 'teste'`);
});
await deve('desfazer 007 tira tudo e roda duas vezes', async () => {
  await db.exec(ler('desfazer_007.sql'));
  await db.exec(ler('desfazer_007.sql'));
  const t = await um(`select count(*)::int n from pg_tables where tablename in ('agentesia_carteiras','agentesia_carteira_movimentos','agentesia_planos','agentesia_recargas','agentesia_cobranca_config')`);
  const c = await um(`select count(*)::int n from information_schema.columns where table_name='agentesia_chamadas_ia' and column_name in ('custo_brl','cobranca','id_lead')`);
  if (t.n || c.n) throw new Error(JSON.stringify({ t, c }));
});
await deve('aplica 007 de novo depois de desfazer', () => db.exec(ler('007_agentesia_cobranca.sql')));
await deve('desfazer 007 antes da 006', () => db.exec(ler('desfazer_007.sql')));
await deve('desfazer 006 tira tudo e roda duas vezes', async () => {
  await db.exec(ler('desfazer_006.sql'));
  await db.exec(ler('desfazer_006.sql'));
  const t = await um(`select count(*)::int n from pg_tables where tablename in ('agentesia_helena_recursos','agentesia_lead_etapas')`);
  const c = await um(`select count(*)::int n from information_schema.columns where (table_name, column_name) in
                      (('agentesia_escritorios','onboarding'),('agentesia_escritorios','dados_helena'),('agentesia_contatos','telefone_chave'),('agentesia_canais','nome_exibicao'),('agentesia_alteracoes','situacao'))`);
  const f = await um(`select count(*)::int n from pg_proc where proname = 'agentesia_registrar_troca_etapa'`);
  if (t.n || c.n || f.n) throw new Error(JSON.stringify({ t, c, f }));
});
await deve('aplica 006 de novo depois de desfazer', () => db.exec(ler('006_agentesia_conta_helena.sql')));
await deve('desfazer 006 antes das outras', () => db.exec(ler('desfazer_006.sql')));
await deve('desfazer 003 de novo', () => db.exec(ler('desfazer_003.sql')));
await deve('desfazer 002 mantém o núcleo', async () => {
  await db.exec(ler('desfazer_002.sql'));
  const t = await um(`select count(*)::int n from pg_tables where schemaname='public' and tablename like 'agentesia\\_%'`);
  const c = await um(`select count(*)::int n from information_schema.columns where column_name in ('instrucao_travada','numeros_teste','resolvido_em')`);
  if (t.n !== 12 || c.n !== 0) throw new Error(JSON.stringify({ t, c }));
});
await deve('aplica 002 de novo', () => db.exec(ler('002_agentesia_gestao.sql')));

await deve('desfazer remove tudo e preserva a tabela antiga', async () => {
  await db.exec(ler('desfazer_002.sql'));
  await db.exec(ler('desfazer_001.sql'));
  const r = await um(`select count(*)::int n from pg_class c join pg_namespace s on s.oid=c.relnamespace where s.nspname='public' and c.relname like 'agentesia%'`);
  const f = await um(`select count(*)::int n from pg_proc where proname like 'agentesia%'`);
  const antiga = await um(`select count(*)::int n from public.lead`);
  if (r.n || f.n || antiga.n !== 1) throw new Error(JSON.stringify({ r, f, antiga }));
});
await deve('aplica de novo depois de desfazer', () => db.exec(ler('001_agentesia_nucleo.sql')));

console.log(`\n${ok} certos, ${falhas} falhas`);
await db.close();
process.exitCode = falhas ? 1 : 0;
