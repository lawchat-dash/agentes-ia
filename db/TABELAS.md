# Tabelas do sistema de IA (`agentesia_`)

22/11/2026. Sistema novo, do zero: não lê nem altera nenhuma tabela que já existe no projeto Supabase AGENT WEAVER, que serve só de hospedagem.

## Como vamos construir

As tabelas nascem junto com o módulo que as usa. Primeiro o núcleo, só o que a IA precisa para funcionar. Depois, uma migração por módulo:

| Ordem | Módulo | Migração | Situação |
|---|---|---|---|
| 1 | **Núcleo da IA**: recebe, junta mensagens, entende, decide, responde, registra. Testado pelo Laboratório, em modo `teste` | `001_agentesia_nucleo.sql` (12 tabelas) | Escrita e testada; falta aplicar |
| 2 | Painel de gestão, follow-up, CRM, contrato, documentos da base, ficha de memória | `002_agentesia_gestao.sql` | Escrita e testada |
| 3 | **Base de conhecimento por papel**: escopo por papel, FAQ/objeções como trechos, cache de embedding por hash, perguntas sem resposta | `003_agentesia_conhecimento.sql` | Escrita e testada (PGlite); falta aplicar |
| 4 | **Lixeira solta o número**: `agentesia_agentes.id_canal` aceita null (agente sem número = precisa ativar), `id_canal_anterior` e `canal_liberado_em` de histórico | `004_agentesia_canal_liberado.sql` (desfazer: `desfazer_004.sql`) | Escrita e testada (PGlite); falta aplicar |
| 5 | Avaliações e cenários de teste no banco | — | Rascunho |

O desenho completo dessas próximas tabelas está em `rascunhos/`. Ele não é aplicado; cada parte vira migração quando o módulo for construído.

## Como aplicar o núcleo

1. No **SQL Editor** do projeto, rode `migracoes/001_agentesia_nucleo.sql` inteiro.
2. Confira em **Table Editor**: 12 tabelas começando com `agentesia_`, todas com cadeado (RLS).

Para voltar atrás: `migracoes/desfazer_001.sql` apaga só o que começa com `agentesia_`.

**Cuidados**
- O projeto está no plano FREE, sem backup. A migração só cria tabelas novas. Mesmo assim, ligue o backup antes de o sistema gravar conversas de verdade.
- Os nomes ficam em minúsculas (`agentesia_`): com maiúsculas, o Postgres exigiria aspas no nome em toda consulta.
- RLS ligado e sem políticas: só o backend, com a chave `service_role`, lê e grava.

## O núcleo: 12 tabelas

### Configuração: quem atende, por onde, com que instruções
| Tabela | O que guarda |
|---|---|
| `agentesia_escritorios` | Escritório: conta da Helena, token no Vault, fuso, interruptor `ia_desligada`. Em `config`: horário comercial, números de teste, honorários |
| `agentesia_canais` | Número de WhatsApp da Helena, oficial ou não |
| `agentesia_agentes` | A IA do canal: persona, produto (as regras do produto ficam no código), `situacao` (ativo, pausado), `modo` (teste ou produção), minutos de pausa quando o humano entra. Em `config`: honorários, vídeo inicial, modelo |
| `agentesia_agente_etapas` | Etapas com a instrução (prompt), modelo e temperatura (no máximo 1); qual é a etapa de entrada |

### Atendimento: o lead e o que a IA fez
| Tabela | O que guarda |
|---|---|
| `agentesia_contatos` | Contato da Helena, telefone normalizado |
| `agentesia_leads` | Lead: agente, etapa, `estado` (ativo, pausado, encerrado) com motivo, `pausado_ate`, atendimento da Helena, origem |
| `agentesia_eventos_recebidos` | Todo webhook cru: descarta repetido e permite reprocessar |
| `agentesia_turnos` | Cada lote de mensagens processado: o que foi enviado à IA, o que ela devolveu, decisões, travas, etapa antes e depois |
| `agentesia_mensagens` | Mensagens de lead, IA, humano e automação, na ordem do WhatsApp, com transcrição |
| `agentesia_lead_fatos` | O que a IA entendeu do lead, cada fato com o trecho que prova |
| `agentesia_chamadas_ia` | Cada chamada de IA: modelo, tokens, tempo, erro |
| `agentesia_eventos` | Problemas e travas, com o responsável (cliente, cadastro, provedor, lead, LawChat) |

### Regras que o banco garante
- Um agente por canal e uma etapa de entrada por agente.
- Um lead por contato e canal.
- Webhook e mensagem repetidos são recusados.
- Temperatura no máximo 1.
- Agente nasce pausado e em modo `teste`.
- Apagar um escritório apaga tudo dele.

### O que ficou para depois, e por quê
| Ficou para | O que | Enquanto isso |
|---|---|---|
| Painel | Versões de configuração, usuários, registro de alterações | Configuração editada direto nas tabelas, com cuidado |
| Painel | Catálogo de produtos no banco | Regras do produto no código, versionadas no git |
| Módulo 3 | Credenciais por provedor | Token da Helena em `id_segredo_helena`; demais chaves em variáveis de ambiente |
| Módulo 5 | Ficha de resumo da conversa | Últimas mensagens + fatos já dão o contexto |

## Base de conhecimento (003)

Desenho: `docs/BASE_DE_CONHECIMENTO.md`. Só acrescenta colunas e uma tabela; não usa pgvector.

| Tabela | O que muda |
|---|---|
| `agentesia_documentos` | `papeis text[]` (vazio = todos os papéis); `tipo` aceita `faq` e `objecoes` (um documento virtual de cada por agente, gerado de `config.conhecimento`; índice único `(id_agente, tipo)`) |
| `agentesia_documento_trechos` | `id_escritorio`, `papeis`, `titulo` ("Documento > Seção" ou a pergunta), `fonte` (`documento`, `faq`, `objecao`), `hash` (sha256 de modelo + texto: o vetor de texto igual é reaproveitado), `modelo`, `dimensoes`; índice `(id_agente, hash)` |
| `agentesia_conhecimento_lacunas` | Nova. Pergunta que a IA não achou na base (`base.sem_resposta`): papel, pergunta, `vezes`, último lead/turno, `situacao` (aberta, respondida, ignorada), resposta. Índice único `(id_agente, pergunta_normalizada)` enquanto aberta: a mesma dúvida soma em `vezes`. RLS ligado |

Para voltar atrás: `migracoes/desfazer_003.sql` (apaga os documentos virtuais; FAQ e objeções continuam na config do agente).
O custo do embedding da consulta fica em `agentesia_chamadas_ia` com papel `conhecimento_consulta`; o da indexação, com papel `conhecimento`.

## Teste

Na pasta `testes/`, rode `npm install` e depois `npm run testar`. O teste aplica a migração num Postgres embutido e confere:
- as 12 tabelas e o RLS em todas;
- cada regra acima;
- o gatilho de `atualizado_em`;
- que apagar o escritório apaga os dados dele;
- que o desfazer remove tudo sem tocar numa tabela que já existia, e que a migração pode ser aplicada de novo.

Resultado atual: 19 certos, 0 falhas.
