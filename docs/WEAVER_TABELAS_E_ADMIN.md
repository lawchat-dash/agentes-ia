# Weaver: tabelas, uso no atendimento e funções de admin → o que recriar aqui

25/11/2026. Leitura só de arquivos (nenhuma API chamada, nada alterado fora deste documento).

**Fontes lidas**
- Weaver/app antigo: `agents-lawchat-main/weaver/migrations/0001..0139` (150 arquivos), `supabase/functions/admin-accounts`, `habilitar-funcoes`, `sync-whatsapp-numbers`, `ativar-produto`, `auth-by-company-id`, `src/pages/admin/AdminContas.tsx`, `CLAUDE.md`, `docs/N8N.md` (colunas das 40 tabelas do bot).
- n8n: `Fluxos N8N/00 - Banco de Dados/MAPA_DO_BANCO.md`, `ENTREGA - WEAVER/*` (fluxos e SQL), `08 - Fluxo Principal (Weaver)/LEIA-ME.md`, `02 - Troca de Departamento/MUDANCAS_TROCA_DEPARTAMENTO.md`.
- Nosso lado: `db/migracoes/001..004`, `db/TABELAS.md`, `app/banco/postgres.py`, `app/gestao/{rotas,ativacao,repositorio}.py`, `app/canal/helena_conta.py`, `app/memoria.py`, `docs/WEAVER_PARA_CODIGO.md`, `MAPA_DO_SISTEMA.md`.

**Limite desta leitura:** os fluxos n8n de admin que criam CRM, etiquetas, webhook e departamento (`ativar_criarcrm_criaretiqueta_criarwebhook`) e o que lista números (`sincronizar_canal_whatsapp`) **não estão nas pastas locais**. O que está escrito sobre eles vem do payload que as edge functions mandam, das colunas que eles preenchem (`clientes.id_webhook`, `clientes.id_departamento`, `painel`, `etapas`, `tags`) e do MAPA_DO_BANCO. Está marcado como *inferido*.

---

## 1. Mapa das tabelas do Weaver

O banco AGENT WEAVER tem duas camadas:
- **Bot** (tabelas sem prefixo, ~40): o que o n8n lê e grava no atendimento. Estrutura "intocável" para o app antigo; o app só escreve nelas por funções `sistemaia_*_no_bot` (SECURITY DEFINER).
- **Plataforma** (`sistemaia_*`, ~45): o app de gestão (contas, catálogo, saldo, logs). Liga-se ao bot por `clientes.id_ulid` / `id_conta_helena`.
- **Tabelas novas dos fluxos de 22-24/11** (`atendimento_evento`, `lead_memoria_resumo`, `lead_etapa_historico`, `contrato_*`): **escritas, mas o LEIA-ME de 24/11 diz que as duas primeiras ainda não foram rodadas no banco**.

Legenda de "quem": **FP** = WEAVER Fluxo Principal; **ME** = Mensagem Enviada; **LN** = subfluxo Lead novo; **AG** = subfluxo Agentes; **TD** = Troca de Departamento; **CT** = Contrato; **FU** = Follow Up Unificado; **TK** = Contar Token; **AN** = Anúncio TRACK; **App** = agents-lawchat (funções `sistemaia_*`/edge).

### 1.1 Clientes, contas, usuários e planos

| Tabela Weaver | Para que serve | Colunas-chave | Quem escreve / lê | Nossa equivalente |
|---|---|---|---|---|
| `clientes` | O escritório no bot | `id_ulid` (PK uuid, = company_id da Helena), `id_conta_helena` (único), `nome`, `status_cliente` (enum), `plano`→`planos`, **`api_lawchat` (token da Helena em texto)**, `id_webhook`, `id_departamento` | Escreve: App `sistemaia_habilitar_cliente_no_bot` (0015/0018/0020) e n8n "habilitar funções" (*inferido*: `id_webhook`, `id_departamento`). Lê: todos os fluxos (token para chamar a Helena) | `agentesia_escritorios` (`id_conta_helena`, `situacao`, `ia_desligada`, `config`) + token no Vault via `agentesia_integracoes` (tipo `helena`) |
| `sistemaia_contas` | Espelho das empresas da Helena (pré-cliente) e chave "Criar Agente" | `id_conta_helena` (único), `id_cliente`→`clientes`, dados cadastrais, `helena_snapshot`, `status_sincronizacao`, `agentes_habilitados`, `status_provisionamento`, `funcoes_habilitadas*` (colunas posteriores) | Escreve: edge `admin-accounts` (sync), `habilitar_cliente_no_bot`, `habilitar-funcoes`. Lê: telas admin, `sistemaia_v_*` | Não existe como espelho. Nós listamos ao vivo (`GET /admin/helena/empresas`) e criamos o escritório direto |
| `sistemaia_usuarios` | Login do app (Supabase Auth) | `auth_user_id`, `email`, `role` (`admin_plataforma`, `admin_cliente`...), `id_conta`, `id_cliente` | App (trigger de auto-cadastro, impersonate) | `agentesia_usuarios` (senha scrypt própria, `papel`, `id_usuario_helena`) |
| `usuarios`, `usuarios_grupos`, `grupos` | Usuários do painel antigo do Weaver e grupos de WhatsApp | `email`, `role`, `tokens`, `id_cliente` | Legado; `conversas_agentes.user_id` aponta para cá | Não existe (não precisa) |
| `planos` / `sistemaia_planos` / `sistemaia_planos_adicionais` | Plano comercial (bot mínimo; app rico) | `qnt_agentes`, `qnt_creditos_reais` / `slug`, preços, `cria_agentes`, `bonus_token_brl`, `id_plano_weaver` | App (`definir_plano_conta`, 0010, 0043, 0107) | Não existe (limite de consumo em `agentesia_escritorios.config`) |
| `sistemaia_config` | Dados do escritório e config do app | `office_info`, `app_config` | App | `agentesia_escritorios.config` |
| `sistemaia_logs_funcoes` | Log de cada função admin/no_bot (ok/erro, payload, duração) | `funcao`, `status`, `id_conta`, `payload`, `resultado`, `erro` | Edges e `chamarRpcBot` | `agentesia_alteracoes` (só sucesso, com antes/depois) + `agentesia_eventos` |
| `sistemaia_avisos`, `sistemaia_servicos`, `sistemaia_incidentes` | Banner de avisos do app e página de status | | App | Não existe (fora do motor) |

### 1.2 Canais e Helena

| Tabela Weaver | Para que serve | Colunas-chave | Quem | Nossa equivalente |
|---|---|---|---|---|
| `conexoes` | Número de WhatsApp | `numero_telefone`, `id_canal` (canal da Helena), `nome_instancia`, `api_key` | App `ativar_produto_no_bot` (cria por número), backfill 0066; FP/ME acham o canal pelo número | `agentesia_canais` (`id_canal_helena` único, `numero_normalizado`, `tipo` oficial/não oficial, `ativo`) |
| `sistemaia_numeros_whatsapp` | Cache dos canais da Helena, com "livre/ocupado" | `id_cliente`, `id_canal`, `numero_digitos`, `tipo`, `display_name`, `ativo_no_canal`, `disponivel`, `usado_por_agente` | `sistemaia_sincronizar_numeros_whatsapp` (0022, HTTP de dentro do banco com o token do cliente) | `agentesia_canais` + join com `agentesia_agentes` (em `repositorio.canais`). Falta `nome_exibicao` e `tipo_helena` |
| `dados_helena` | Ids da Helena do lead | `id_session_helena`, `id_linkconversa_helena`, `id_campanha_link_helena` | LN | `agentesia_leads.id_sessao_helena` e `origem` (jsonb). Link da conversa: não existe |
| `conversas_agentes` | Sessão de atendimento ligada ao lead | `session_id` (único), `id_lead`, `id_agente`, `pausado`, `pausa_ate`, `status_atendimento` | LN cria; FP/ME/FU leem; ME pausa | `agentesia_leads` (`id_sessao_helena`, `estado`, `pausado_ate`) |
| `templates_whatsapp` / `sistemaia_templates_whatsapp` | Modelos oficiais (Meta) por conexão | `id_template_meta`, `status`, `corpo`, `variaveis` | App 0117/0120 (sincroniza da Helena); FU lê | Não existe tabela: `GET /integracoes/helena/modelos-aprovados` consulta ao vivo |
| `departamento` | Agrupador interno de prompts (não é a equipe da Helena) | `nome`, `cor`, `ordem` | Legado (`prompts.id_departamento`) | Não existe (não precisa) |

### 1.3 CRM (painel, colunas, cards, etiquetas)

| Tabela Weaver | Para que serve | Colunas-chave | Quem | Nossa equivalente |
|---|---|---|---|---|
| `painel` | Painel do CRM da Helena por cliente | `id_cliente`, `id_painel` (Helena) | n8n "habilitar funções" (*inferido*). 2 clientes sem painel, 1 com dois | `agentesia_integracoes` tipo `crm`, `config.id_painel` (um por escritório) |
| `etapas` | Colunas do painel (6 por painel: SDR, COMERCIAL, CONTRATO, AGUARDANDO_ASSINATURA, DESQUALIFICADO, CONTRATO_ASSINADO) | `ulid_painel`, `tipo_etapa` (código), `valor_uuid` (id da coluna na Helena), `nome_etapa` | Idem. `fn_etapa_uuid` liga etapa do agente → coluna (pega "o primeiro painel que achar") | Não existe tabela: a coluna de cada gatilho fica em `agentesia_agentes.config.automacoes` |
| `tags` | Etiquetas da Helena por cliente (📞 SDR, 🛒 Comercial, 📄 Contrato em Elaboração, ✍️ Etapa de Assinatura, ❌ Desqualificado, ✅ Contrato Assinado, 🤖 IA Desativada) | `id_cliente`, `id_tag_helena`, `nome` | Idem; LN/TD/CT/AN usam | Não existe tabela: etiquetas por nome em `config.automacoes` (`InsertIfNotExists`) |
| `card`, `painel_card`, `card_tag` | Card do lead (N:N com painel e tag) | `id_card_helena` (único), `id_lead`, `id_etapa` | LN cria; TD/CT movem. **3.167 de 3.188 cards gravados em SDR** (nunca atualizado), 116 leads com vários cards | `agentesia_crm_cards` (um por lead, `id_card_helena` único, `id_etapa_helena`, `situacao`) |

### 1.4 Agente, etapas, prompts e catálogo

| Tabela Weaver | Para que serve | Colunas-chave | Quem | Nossa equivalente |
|---|---|---|---|---|
| `agentes` | A IA do cliente num número | `id_cliente`, `conexao_id`, `modelo_id`, `produto_id`, `numero_ia`, `status`, `ativo`, `minutos_pausa`, `tamanho_historico`, `tempo_espera_variavel`, `separar_mensagens`, `conhecimento` (jsonb, guarda `agent_group_id`) | App `ativar_produto_no_bot` (0064/0075), `mudar_status_no_bot`, `trocar_canal_no_bot` (0136); FP lê | `agentesia_agentes` (`id_canal` único, `produto`, `situacao`, `modo`, `minutos_pausa_humano`, `config`) |
| `agente_etapas` | Etapas do agente (sdr, periododegraca, closer, contratos, assinatura, desqualificado, contratoassinado, iadesativada) | `id_agente`, `etapa`, `id_prompt`, `eh_principal`, `ordem`, `config` (13 chaves: gatilhos, pausa, delay...) | App (ativação, 0021, 0101); FP/TD/CT leem | `agentesia_agente_etapas` (`codigo`, `ordem`, `tipo` conversa/terminal, `principal`, `instrucao`, `modelo`, `temperatura`, `instrucao_travada`) |
| `prompts` | Texto do prompt da etapa | `prompt`, `modelo`, `temperatura`, `faq`, `objecoes`, `dados_escritorio`, `regras`, `mensagem_troca` | App (ativação, `atualizar_prompts_no_bot` 0019) | `agentesia_agente_etapas.instrucao` + `agentesia_agentes.config.conhecimento` |
| `agente_roteiros` | Roteiros ordenados | `ordem`, `texto` | App (ativação) | Não existe (vai no texto da instrução) |
| `models`, `api_key`, `api_key_atributos` | Modelo LLM e **chaves (OpenAI, ZapSign) em texto**, atributos (modelo de contrato por agente) | `api_key.chave`, `provedor`; `api_key_atributos.chave_atributo/valor` | App (ativação; 0139: uma chave ZapSign por cliente, um atributo por agente). CT lê | `agentesia_integracoes` (tipos `openai`, `anthropic`, `zapsign`, segredo no Vault, `config.modelos` por produto) |
| `produto`, `sistemaia_biblioteca_produtos`, `sistemaia_biblioteca_agentes`, `sistemaia_biblioteca_conhecimento`, `sistemaia_biblioteca_followups`, `sistemaia_frases_troca` | Catálogo (bot mínimo + app rico) | slug, blocos_prompt, faq, objecoes, papel | App admin | `agentesia_biblioteca_produtos`, `agentesia_biblioteca_agentes`, `agentesia_frases_troca`, `agentesia_documentos` (id_produto_biblioteca), importados por `app/catalogo_importar.py` |
| `sistemaia_produtos_ativados` | Rascunho do assistente + produto ativado | `id_conta`, `numero_ia`, `status_provisionamento`, `id_agente_weaver`, `faq`, `objecoes`, `conhecimento` | App (tela Ativar → `ativar_produto_no_bot`) | `agentesia_produtos_ativados` (mesmo desenho) |
| `sistemaia_produto_contratos`, `sistemaia_integracoes` | Modelo ZapSign por produto/agente; integrações da conta | `modelo_token`, `mapeamento` | App | `agentesia_integracoes.config.modelos` (zapsign) |

### 1.5 Lead, mensagens, memória e histórico

| Tabela Weaver | Para que serve | Colunas-chave | Quem | Nossa equivalente |
|---|---|---|---|---|
| `contatos` | Contato do WhatsApp | `id_cliente`, `user_number`, `user_name`, `lead_antigo`, `uild` | LN (upsert) | `agentesia_contatos` (`id_contato_helena`, `telefone_normalizado`, único por escritório) |
| `lead` | O lead no funil | `ulid`, único por (contato, conexão); `id_agente`, `id_etapa_atual`→`agente_etapas`, `etapa_atual` (cópia em texto), `ia_ligada`, `reativar_em`, `contrato_realizado`, `etapa_trocada_em/msg` (TD) | LN cria; FP/TD/CT/ME/FU leem e gravam. Gatilhos `trg_lead_etapa_inicial`, `trg_a_lead_sync_etapa_atual`, `trg_audita_etapa_null`, `trg_reativacao_lead` | `agentesia_leads` (único por canal+contato; `id_etapa`, `estado` ativo/pausado/encerrado, `motivo_estado`, `pausado_ate`, `responder_apos`, `processando_ate`, `origem`) |
| `memoria` | Memória da IA no formato "Postgres Chat Memory" do n8n | `session_id` (= id do lead), `message` jsonb (`type` human/ai, `content`) | AG grava; FP/ME/TD/CT/FU leem; ME grava a fala do atendente como se fosse da IA | `agentesia_mensagens` (autor lead/ia/humano/automacao/sistema, `texto_extraido`, `situacao_envio`) |
| `mensagens` | Mensagens para o painel antigo | `id_conversa`, `direcao`, `from_ai`, `from_me`, `tipo_mensagem` | FP/ME | `agentesia_mensagens` |
| `lead_memoria_resumo` (nova, não rodada) | Ficha da conversa antiga | `id_lead` PK, `resumo`, `ate_id` (linha de `memoria`), `mensagens_resumidas`, `modelo`, tokens | FP (bloco 11) | `agentesia_lead_resumo` (002) — **já existe e o código usa** (`postgres.py` `comeco_da_conversa`, `trecho_para_resumir`; `app/memoria.py`) |
| `atendimento_evento` (nova, não rodada) | Problemas do atendimento com responsável | `situacao`, `responsavel`, `descricao`, `session_id`, `nota_enviada` | FP/ME | `agentesia_eventos` (+ `resolvido_em`) e `agentesia_turnos` |
| `lead_etapa_historico` | Cada troca de etapa e o resultado no CRM/tag; base da repescagem | `etapa_de`, `etapa_para`, `etapa_pedida`, `resultado`, `crm_atualizado`, `tag_atualizada`, `crm_tentativas` | TD e Repescagem | Parcial: `agentesia_turnos.etapa_antes/etapa_depois` (só trocas feitas pela IA) e `agentesia_acoes` (retentativa do card). **Sem histórico único de etapa** |
| `lead_etapa_audit`, `reativacao_fila` | Auditoria de etapa vazia; fila para religar IA | | Gatilhos | Não precisa: `pausado_ate` + índice `agentesia_leads_volta` |
| (Redis) buffer de mensagens | Junta mensagens antes de responder | | FP | `agentesia_leads.responder_apos` / `processando_ate` (no banco, sobrevive a reinício) |

### 1.6 Contrato

| Tabela Weaver | Para que serve | Colunas-chave | Quem | Nossa equivalente |
|---|---|---|---|---|
| `contrato_documento` | Versões do contrato por lead, uma "gerando" por vez | `versao`, `estado`, `dados_hash`, `doc_token`, `signer_token`, `link`, `lead_assinou_em` | CT | `agentesia_contratos` (mesmo desenho, com `reservado`/`gerado` únicos por lead) |
| `contrato_evento` | Histórico das tools de contrato | `situacao`, `responsavel` | CT | `agentesia_eventos` + `agentesia_acoes` |
| `contrato_resumo_config`, `contrato_resumo` | Resumo do caso depois da assinatura (config por cliente/agente) | `prompt`, `modelo`, `ativo` | CT, front | `agentesia_contratos.resumo` (config do prompt: no código / config do agente) |
| `sistemaia_assinaturas` | Webhook da ZapSign no app | `doc_token`, `signer_status` | Edge `zapsign-webhook` | `agentesia_eventos_recebidos` (origem `zapsign`) |

### 1.7 Follow-up

| Tabela Weaver | Para que serve | Colunas-chave | Quem | Nossa equivalente |
|---|---|---|---|---|
| `produto_cadencia_template` → `followup_cadences` → `prompts_followup` | Cadência do produto, instanciada por agente, um prompt por passo e por `etapa_crm` | `steps` jsonb, `etapa_crm`, `step` | App `sincronizar_followup_no_bot` (0008, 0094, 0126-0130) | `agentesia_agentes.config.followup` e `agentesia_biblioteca_produtos.padrao_followup` |
| `followups` | Estado por lead (passo atual, próximo, apto, adiado) | `current_step`, `next_run_at`, `paused_until`, `completed_at` | FU | `agentesia_followups` (um pendente por lead, `passo`, `base`, `agendado_para`) |
| `followup_queue` | Fila de envio com trava | `scheduled_for`, `status` (enum), `locked_until`; único (lead, passo) pendente | FU, TD cancela | `agentesia_followups` (`reservado_ate`) — a mesma linha é estado e fila |
| `followup_events` | Auditoria de envio e resposta | `status`, `responded_at`, `engagement_score` | FU | `agentesia_followups.mensagens/enviado_em` + `agentesia_mensagens` (autor `automacao`) |
| `sistemaia_followups_produtos`, `sistemaia_followup_templates` | Config do follow-up no app; modelo oficial por etapa | | App | `config.followup.modelo_oficial` |

### 1.8 Notificações

| Tabela Weaver | Para que serve | Quem | Nossa equivalente |
|---|---|---|---|
| `sistemaia_notificacoes`, `sistemaia_notificacao_destinatarios` | Aviso por evento (etapa, sinal, contrato) e números da equipe | App; copiado para `avisos` por `sistemaia_sincronizar_notificacao_no_bot` (0024, 0083) | `agentesia_notificacoes` (`tipo_evento`, `modelo_mensagem`, `destinatarios` jsonb) |
| `avisos` | Cópia no bot, lida pelo fluxo "99 - Alerta Notificação" | n8n | (a mesma) |

### 1.9 Base de conhecimento

| Tabela Weaver | Para que serve | Quem | Nossa equivalente |
|---|---|---|---|
| `grupo_conhecimentos` | Textos/arquivos do agente | App (ativação) | `agentesia_documentos` |
| `sistemaia_conhecimento_vetores` | pgvector + HNSW, RPC de busca, cron de ingestão (0087-0093) | App/cron, AG (topK) | `agentesia_documento_trechos` (vetor `real[]`, sem pgvector) + `agentesia_conhecimento_lacunas` |

### 1.10 Consumo, saldo e cobrança

| Tabela Weaver | Para que serve | Quem | Nossa equivalente |
|---|---|---|---|
| `consumo_tokens`, `consumo_tokens_consolidado` | Tokens e custo por execução | TK | `agentesia_chamadas_ia` (por chamada, com `custo_usd`) |
| `sistemaia_execucoes_cobradas`, `sistemaia_consumo_pulados` | Idempotência da cobrança por execução | TK, cron | Não precisa (custo gravado na própria chamada) |
| `sistemaia_saldos`, `sistemaia_uso`, `sistemaia_cortes_saldo`, `sistemaia_recargas`, `sistemaia_eventos_asaas`, `sistemaia_cotacao`, `sistemaia_precos_modelos`, `pagamento_tokens` | Saldo pré-pago em R$, débito por cron (`sistemaia_processar_consumo`), corte do agente sem saldo, recarga Asaas, cotação diária | App, crons (0046, 0052, 0058, 0061, 0097) | **Não existe.** Temos limite mensal em USD por escritório (`app/consumo.py`, `config`) |

---

## 2. O atendimento passo a passo

### 2.1 No Weaver (n8n)

| # | Passo | O que acontece | Tabelas |
|---|---|---|---|
| 1 | Mensagem chega | Webhook `wts-inbound` da Helena (MESSAGE_RECEIVED). Descarte de repetida (Redis). Acha o canal pelo número que recebeu e o cliente pela conta | lê `conexoes`, `clientes` (pega `api_lawchat`), `agentes` (`numero_ia`, `status`) |
| 2 | Lead | Lead novo → subfluxo LN: upsert do contato, cria o lead na etapa principal (gatilho `trg_lead_etapa_inicial`), liga a conversa, tag 📞 SDR, card na coluna SDR | grava `contatos`, `lead`, `conversas_agentes`, `dados_helena`, `card`; lê `painel`, `etapas`, `tags`, `agente_etapas` |
| 3 | A IA atende? | `ia_ligada`, agente pausado, **saldo** (`sistemaia_saldos`/`sistemaia_contas`), etapa com prompt, canal de outro cliente | lê `lead`, `agentes`, `agente_etapas`, `prompts`, `sistemaia_saldos`, `sistemaia_contas`; grava `atendimento_evento` (versão nova) |
| 4 | Espera e junta | Buffer no Redis; depois da espera, confere de novo se a IA ainda está ligada | Redis; lê `lead` |
| 5 | Memória e histórico | Até 40 mensagens da `memoria` (janela que não corta tool call) + ficha `lead_memoria_resumo` + fatos do banco (contrato, data do contato) | lê `memoria`, `lead_memoria_resumo`, `contrato_documento`, `lead` |
| 6 | Etapa → agente | `lead.id_etapa_atual` → `agente_etapas.etapa` escolhe um dos 5 agentes (SDR, Período de Graça, Closer, Contratos, Assinatura); prompt e modelo de `prompts` | lê `agente_etapas`, `prompts`, `models`, `api_key` |
| 7 | Resposta | Agente LangChain com ferramentas (troca de etapa, notificação, ZapSign, CEP, verificação de assinatura, base de conhecimento). Memória gravada pelo nó Postgres Chat Memory | grava `memoria`; lê `sistemaia_conhecimento_vetores` / `grupo_conhecimentos` |
| 8 | Envio | Divide e envia pela Helena com o token do cliente; grava para o painel | grava `mensagens`; avisos em `atendimento_evento` |
| 9 | Troca de etapa | Tool chama o fluxo TD: troca em um comando com o lead travado, só para frente, recusa terminal e troca dupla; move todos os cards e as tags; nota; cancela follow-up | grava `lead` (`id_etapa_atual`, gatilho grava `etapa_atual`), `lead_etapa_historico`, `followup_queue`; lê `etapas`, `card`, `tags`, `painel` |
| 10 | Contrato | Tool ZapSign chama CT: reserva versão, gera pelo modelo do agente, devolve link; webhook de assinado move para `contratoassinado`, tag, nota, resumo, desliga IA | `contrato_documento`, `contrato_evento`, `contrato_resumo(_config)`, `api_key`, `api_key_atributos`, `lead`, `card`, `tags` |
| 11 | Notificação | Tool "Sistema Notificação" chama "99 - Alerta Notificação" com o tipo do evento | lê `avisos` |
| 12 | Follow-up | Depois da resposta agenda o próximo passo; FU (cron) envia, usa modelo oficial se a janela fechou | `followups`, `followup_queue`, `followup_events`, `followup_cadences`, `prompts_followup`, `sistemaia_followup_templates`, `sistemaia_templates_whatsapp` |
| 13 | Tokens | Contar Token lê a execução e grava o consumo; cron debita o saldo e corta o agente sem saldo | `consumo_tokens`, `sistemaia_execucoes_cobradas` → `sistemaia_uso`, `sistemaia_saldos`, `sistemaia_cortes_saldo` |
| 14 | Atendente fala | Webhook `wts-outbound` (ME): acha o lead, pausa a IA (`ia_ligada=false`, `reativar_em`), grava a fala na `memoria` | `lead`, `conversas_agentes`, `memoria`, `mensagens` |

### 2.2 No nosso motor

| # | Passo | Onde | Tabelas |
|---|---|---|---|
| 1 | Webhook do escritório (URL com segredo próprio) | `app/canal/webhook.py`, `pipeline.py` | grava `agentesia_eventos_recebidos` (repetido é recusado); lê `agentesia_escritorios`, `agentesia_canais` |
| 2 | Contato e lead numa transação (`achar_ou_criar_lead`), etapa principal | `postgres.py` | `agentesia_contatos`, `agentesia_leads` |
| 3 | Mensagem gravada **sempre**, antes da decisão; mídia lida | `pipeline.py` | `agentesia_mensagens` |
| 4 | Espera no banco (`responder_apos`) e trava (`processando_ate`) | `pipeline.py` | `agentesia_leads` |
| 5 | Decisão (`_por_que_nao_atende`): IA desligada no escritório, canal sem agente, agente pausado, lead pausado/encerrado, sem etapa, modo teste, fora do horário, limite de consumo | `pipeline.py`, `consumo.py` | `agentesia_turnos` (situação `silencio` + motivo), `agentesia_eventos` |
| 6 | Contexto: 40 últimas + ficha + antigas não resumidas + fatos | `postgres.historico`, `comeco_da_conversa`, `fatos_do_sistema`; `app/memoria.py` | `agentesia_mensagens`, `agentesia_lead_resumo`, `agentesia_lead_fatos`, `agentesia_contratos` |
| 7 | Turno: papel pela etapa, saída estruturada, travas, base por vetor | `app/cerebro/*` | `agentesia_turnos`, `agentesia_chamadas_ia`, `agentesia_documento_trechos` |
| 8 | Envio por parte, com situação de cada uma | `pipeline.py`, `canal/helena.py` | `agentesia_mensagens` (`situacao_envio`, `erro`) |
| 9 | Troca de etapa (campo `transferir_para` ou frase) gravada no lead; card/etiqueta pela fila de ações | `turno.py`, `automacoes.py`, `acoes.py` | `agentesia_leads.id_etapa`, `agentesia_acoes`, `agentesia_crm_cards` |
| 10 | Contrato: ação `gerar_contrato` com hash e versões; webhook ZapSign | `acoes.py`, `contrato/*` | `agentesia_contratos`, `agentesia_acoes`, `agentesia_eventos_recebidos` |
| 11 | Aviso à equipe: gatilho `sinal:*`, `etapa:*`, `contrato_assinado` | `automacoes.py`, `acoes.py` | `agentesia_notificacoes`, `agentesia_acoes` |
| 12 | Follow-up: um pendente por lead; resposta do lead cancela | `followup/servico.py` | `agentesia_followups` |
| 13 | Custo por chamada; limite mensal | `consumo.py` | `agentesia_chamadas_ia` |
| 14 | Atendente fala: grava, pausa com `pausado_ate`, cancela follow-up | `pipeline.py` | `agentesia_mensagens`, `agentesia_leads`, `agentesia_followups` |
| 15 | Ficha de memória refeita pela fila (`resumir_conversa`) | `app/memoria.py` | `agentesia_lead_resumo`, `agentesia_acoes` |

### 2.3 Diferenças que importam

| Ponto | Weaver | Nosso | Ação |
|---|---|---|---|
| Fonte da etapa | `id_etapa_atual` + cópia em texto `etapa_atual` (502 leads divergentes) | Só `id_etapa` | Nada; não recriar a cópia |
| Memória | `memoria` jsonb do n8n; atendente gravado como IA | `agentesia_mensagens` com autor | Nosso é melhor |
| Card | `card` nunca atualizado, vários por lead | Um por lead, retentativa na fila | Card nasce só no gatilho `lead_novo` depois da 1ª resposta (ver WEAVER_PARA_CODIGO) |
| Histórico de etapa | `lead_etapa_historico` com resultado de CRM e tag | Só nos turnos da IA | **Recriar** (item 4.1 C) |
| Trava de troca dupla | `etapa_trocada_em/msg` | Trava de turno + uma decisão por turno | Nada |
| Saldo | Pré-pago, corte por cron | Limite USD mensal | Decisão de produto |
| Painel/colunas/etiquetas | Tabelas por cliente, criadas no onboarding | Ids dentro de `config.automacoes`, consultados ao vivo | Cache da conta (item 4.1 B) |
| Canal → cliente | Número + `clientes.api_lawchat` | URL com segredo por escritório + Vault | Nosso é melhor |

---

## 3. Funções de admin

### 3.1 "Primeira criação" de uma conta no Weaver

É uma sequência de quatro ações separadas na tela `AdminContas`, cada uma registrada em `sistemaia_logs_funcoes`:

**(a) Sincronizar com LawChat** — edge `admin-accounts`, `action: "sync"`
- Só `admin_plataforma` (confere `sistemaia_usuarios.role`).
- Lê da Helena: `GET core/v1/company?PageSize=100` com o **token master** (secret de função; também no Vault). Sem paginação: acima de 100 empresas, as demais não entram.
- Grava: upsert em `sistemaia_contas` por `id_conta_helena` (nome fantasia, razão social, CNPJ/CPF formatado, tipo PF/PJ, e-mail e telefone do administrador, endereço, `helena_snapshot`, `status_sincronizacao='sincronizado'`). Exceção fixa no código para a conta da própria LawChat (o e-mail do admin não é sobrescrito).
- Erros: `helena_token_missing` (500), `helena_unreachable` (502), por empresa "sem id" ou erro de upsert (conta em `failed`, até 20 erros na resposta).
- `sync_one`: mesma coisa para uma conta (baixa a lista inteira e filtra). `impersonate`: cria/acha usuário no Auth e gera magic link (acessar como cliente).

**(b) Criar Agente (liga/desliga)** — RPC `sistemaia_habilitar_cliente_no_bot(payload, _api_lawchat, _criar_token_helena)` (0015 → 0018 → 0020), depois `sistemaia_definir_plano_conta`
- Só admin (`auth.uid()` admin ou service role).
- Lê da Helena: `POST core/v1/company/{id}/tokens` com `{"name":"LawChat"}`, feito **de dentro do Postgres** pela extensão `http`, com o token master lido do Vault (`sistemaia_criar_token_helena`). Desde 0020 é "melhor esforço": se falhar, habilita sem token e devolve o erro.
- Grava: upsert em `planos` (por uuid, se veio plano), upsert em `clientes` (por `id_conta_helena`: `id_ulid = company_id`, nome, contato, CNPJ, `status_cliente='ativo'`, plano, **`api_lawchat` = token**), atualiza `sistemaia_contas` (`agentes_habilitados`, `habilitado_em`, `id_cliente`, `status_provisionamento='confirmado'`).
- Desligar: `clientes.status_cliente='inativo'` e `agentes_habilitados=false` (não apaga nada).
- Validações: `company_id` obrigatório; só admin.

**(c) Habilitar Funções (uso único)** — edge `habilitar-funcoes` → webhook n8n `ativar_criarcrm_criaretiqueta_criarwebhook`
- Guardas: só admin; exige `agentes_habilitados`; se `funcoes_habilitadas` já é true, não dispara de novo.
- Manda ao n8n (HMAC) a conta inteira, o plano, o `helena_snapshot` e a URL do webhook de entrada que deve ser registrada.
- O n8n (*inferido*, fluxo não está nas pastas): cria na Helena o **painel do CRM com as 6 colunas**, as **etiquetas padrão** das etapas e a **assinatura de webhook**; grava `painel`, `etapas` (`tipo_etapa` + `valor_uuid`), `tags` (`id_tag_helena`), `clientes.id_webhook` e `clientes.id_departamento`.
- Ao receber 2xx marca `funcoes_habilitadas(_em,_por)`. Erros: `criar_agente_inativo` (409), `n8n_unreachable`/`n8n_error` (502). Se o n8n criou metade e falhou, a marca não é gravada e o reenvio pode duplicar coisas na Helena (o fluxo n8n precisa ser idempotente; não dá para conferir aqui).
- Problemas de dados que vêm daqui: clientes sem painel e cliente com dois painéis (MAPA_DO_BANCO), cliente sem a etiqueta de desqualificado (TD, achado F).

**(d) Ativar produto** — tela Ativar → `sistemaia_ativar_produto_no_bot` (0064, refeita em 0075; canal em 0136/0137; ZapSign em 0139)
- Valida payload (`product`, `agents` não vazio, `workspace_id`, `product_uuid`, `whatsapp_number`, `model`), cliente existe, permissão (admin ou usuário da conta), plano (0109).
- Grava em uma transação: `conexoes` (por número, com `id_canal` vindo do cache de números), `models`, `produto`, `agentes`, `api_key` + `api_key_atributos`, `prompts` + `agente_etapas` (um por papel, com FAQ/objeções em texto), `agente_roteiros`, `grupo_conhecimentos`; idempotente por `agent_group_id`; confere por contagem no fim.

### 3.2 "Sincronizar conta" no Weaver (o que é puxado da Helena)

| Recurso da Helena | Weaver | Onde fica |
|---|---|---|
| Empresas (contas) | `admin-accounts` sync/sync_one | `sistemaia_contas` |
| Números/canais | `sistemaia_sincronizar_numeros_whatsapp(workspace_id)` (0022): `GET chat/v1/channel?ChannelType=All` com o **token do cliente**; marca `disponivel` casando os 11 últimos dígitos com `agentes.numero_ia`. Erro claro se o cliente não tem token ("habilite Criar Agente primeiro"). Edge antiga `sync-whatsapp-numbers` chamava um webhook n8n | `sistemaia_numeros_whatsapp` |
| Modelos oficiais (templates) | `sistemaia_sincronizar_templates_whatsapp` (0117, paginado em 0120, preserva ids em 0123) | `sistemaia_templates_whatsapp` |
| Painéis e colunas do CRM | Só na criação (c). Não há ressincronização | `painel`, `etapas` |
| Etiquetas | Só na criação (c) | `tags` |
| Departamentos (equipes) | Só o id de um departamento em `clientes.id_departamento` (c) | `clientes` |
| Usuários (atendentes) | Não sincroniza. Login por `auth-by-company-id` (company_id → magic link) | `sistemaia_usuarios` |

### 3.3 O nosso equivalente

| Função | Nosso | Situação |
|---|---|---|
| Listar empresas da Helena | `GET /admin/helena/empresas?busca=` (`HelenaParceiro.empresas`, `PageSize=50`, ao vivo, token de parceiro em variável de ambiente) | Existe. Sem espelho local (não precisa). Sem paginação: só as 50 primeiras sem busca |
| Criar o cliente ("Criar Agente") | `POST /admin/escritorios` (tela `AdminEscritorios.tsx`): cria `agentesia_escritorios`, gera o token na Helena (`POST core/v1/company/{id}/tokens`) **no servidor**, guarda no Vault (`agentesia_integracoes` tipo `helena`), cria o gestor com senha provisória, registra em `agentesia_alteracoes` | Existe e é melhor (token nunca em tabela). Falta: plano; o erro de token não fica registrado (só volta para a tela) |
| Desligar o cliente | `agentesia_escritorios.situacao` (`suspenso`, `encerrado`) e `ia_desligada` | Coluna existe; conferir se o admin tem botão (o PATCH `/escritorio` é do gestor) |
| Webhook na Helena | `POST /integracoes/helena/conectar` e passo `webhook` da ativação (`garantir_assinatura`: cria ou corrige a assinatura com MESSAGE_RECEIVED, MESSAGE_SENT, CONTACT_TAG_UPDATE) | Existe, idempotente |
| Números/canais | `POST /integracoes/helena/canais` (`useChannelsSync`) e passo `canal` da ativação: upsert em `agentesia_canais` por `id_canal_helena`, desativa os que sumiram | Existe. Falta guardar nome de exibição e tipo cru da Helena |
| Painéis e colunas | `GET /integracoes/helena/paineis` (ao vivo) + `PUT /integracoes/crm` (guarda `id_painel`); passo `crm` confere se as colunas usadas nas automações existem | Existe para **escolher**. **Não cria** painel nem colunas padrão |
| Etiquetas | `GET /integracoes/helena/etiquetas` (ao vivo); etiquetar usa `InsertIfNotExists` por nome | Lista; **não cria** as etiquetas padrão no onboarding |
| Equipes (departamentos) | `GET /integracoes/helena/equipes` (ao vivo); passo `equipe` confere a equipe de transferência | Existe |
| Usuários | Entrada pela Helena (`/entrar/helena`): confere o atendente na API com o token da conta e cria `agentesia_usuarios` no primeiro acesso | Existe e é mais seguro que o Weaver. Sem lista/sincronização em lote |
| Modelos oficiais | `GET /integracoes/helena/modelos-aprovados` (ao vivo) | Existe |
| Ativar produto | `app/gestao/produtos.py` (catálogo → agente + etapas + documentos) e `POST /agentes/{id}/ativacao` (checagem em 10 passos: helena, canal, webhook, alcance, etapas, modelo_ia, crm, equipe, contrato, teste) | Existe e é melhor (só liga sem erro) |
| Log das funções | `agentesia_alteracoes` | Só sucesso; falhas de admin não ficam gravadas |

**O que falta para o "primeira criação" ficar completo aqui:**
1. Um **assistente de onboarding** que rode, em ordem e com resultado por passo, o que o Weaver fazia em três botões: token → webhook → canais → etiquetas padrão → painel do CRM (escolher um existente ou criar o padrão) → equipe de transferência → gestor. Reusar o padrão `ativacao.Passo` e guardar o resultado no escritório.
2. **Criar etiquetas padrão** (`POST core/v1/tag`, já documentado em `docs/HELENA_API.md`), idempotente por nome.
3. **Painel padrão do CRM**: decidir se a LawChat cria o painel com as 6 colunas (conferir na documentação da Helena se a API cria painel e etapas; não confirmado nesta leitura) ou se o gestor escolhe um painel existente (hoje).
4. **Sincronizar conta em um clique** com cache local (canais, painéis/colunas, etiquetas, equipes, usuários), para validar automações e mostrar o que sumiu na Helena sem chamar a API a cada tela.
5. Registrar **falhas** das ações de admin (hoje só sucesso).

---

## 4. O que recriar aqui

### 4.1 Lista priorizada

| Prioridade | O quê | Por quê | Risco |
|---|---|---|---|
| A | **Onboarding em passos** (rota admin + coluna `agentesia_escritorios.onboarding` jsonb + `sincronizado_em`) | Hoje o admin cria o escritório e o gestor precisa achar sozinho token, webhook, CRM e etiquetas. O Weaver errou aqui (clientes sem painel, sem etiqueta) | Baixo: só acrescenta coluna e uma rota que reusa `ativacao.preparar` |
| B | **Cache da conta Helena** (`agentesia_helena_recursos`: canal, painel, coluna, etiqueta, equipe, usuário) | Validar `config.automacoes` contra o que existe (o Weaver teve o erro `periodograca` e etiqueta inexistente), autocomplete sem bater na Helena, detectar recurso apagado | Médio: é cópia; precisa marcar `removido_em` e nunca ser fonte para ação sem conferir na hora |
| C | **Histórico de etapa** (`agentesia_lead_etapas`, preenchido por gatilho em `agentesia_leads.id_etapa`) | Tempo por etapa no funil, auditoria de quem moveu (IA, frase, equipe, contrato, painel), base para repescagem de card. O Weaver teve 502 leads com etapa divergente e nenhuma prova | Baixo: gatilho só insere; nada lê para decidir |
| D | **Busca de telefone sem o nono dígito** (coluna gerada `telefone_chave` em `agentesia_contatos`) | Item de WEAVER_PARA_CODIGO: lead duplicado quando a Helena manda sem o 9 | Baixo; a busca deve preferir o número exato |
| E | **Nome e tipo do canal** (`agentesia_canais.nome_exibicao`, `tipo_helena`, `sincronizado_em`) | Tela de canais mostra o nome que o cliente reconhece; tipo cru ajuda a separar Instagram e provedores | Baixo |
| F | **Link da conversa** (`config.dominio_helena` no escritório, sem migração) | Avisos à equipe saem sem link (`link_conversa` nunca preenchido) | Baixo |
| G | **Falha de admin registrada** (`agentesia_alteracoes.situacao`, `erro`) | O Weaver tinha `sistemaia_logs_funcoes` com ok/erro; nós só gravamos sucesso | Baixo |
| H | Saldo pré-pago / corte por saldo | Só se o produto continuar cobrando por saldo; hoje há limite USD | Alto (cobrança). **Decisão do dono antes de qualquer tabela** |

### 4.1.1 Implementado (25/11/2026) — migração 006

As prioridades A, B, C, D, E e G viraram a **migração 006** (`db/migracoes/006_agentesia_conta_helena.sql` + `desfazer_006.sql`; o número 005 já era a mídia pendente). Idempotente, testada em `db/testes/teste_migracoes.mjs` e incluída em `db/testes/servidor_local.mjs`. **Não aplicada em produção** (o dono aplica). O código funciona sem ela (lê as colunas novas por `to_jsonb(...)` e trata `UndefinedColumn`).

| Item | O que ficou | Onde |
|---|---|---|
| A Onboarding | `agentesia_escritorios.onboarding` (passos, `concluido_em`), `sincronizado_em` e `dados_helena` (dados da empresa sem e-mail/telefone + ids: `id_assinatura`, `id_departamento`, `id_painel`, `etapas_por_tipo` com os 6 tipos SDR/COMERCIAL/CONTRATO/AGUARDANDO_ASSINATURA/CONTRATO_ASSINADO/DESQUALIFICADO, `etiquetas` nome→id). Passos, na ordem da primeira criação pedida pelo dono (um passo a passo só, retomável, cada passo reaproveita o que já existe): 1 token da conta (sem token e com o token de parceiro, cria "IA LawChat" por `POST core/v1/company/{id}/tokens`, cofre + só o final no banco), 2 webhook, 3 equipe "🤖 Comercial IA", 4 as 7 etiquetas, 5 painel (escolher existente e ligar as colunas aos 6 tipos) ou 5b painel padrão por código digitado, 6 números/canais, depois dados da empresa (CNPJ, razão social, endereço, plano, e-mail de contato da empresa) e cópia da conta, ZapSign (opcional) e primeiro produto (reusa `ativacao.preparar`) | `app/gestao/onboarding.py`; rotas `GET /api/admin/escritorios/{id}/onboarding`, `POST .../onboarding/conferir`, `POST .../onboarding/avancar` (`passos`, `id_painel`, `etapas_por_tipo`) em `app/gestao/rotas_conta.py` |
| Primeira criação | `POST /api/admin/escritorios` aceita `criar_etiquetas_padrao`, `criar_equipe_ia`, `id_painel`; com o token de parceiro guarda os dados da empresa (`GET core/v1/company`, filtrado pelo id) | `app/gestao/rotas.py` (`_primeira_criacao_na_helena`) |
| B Cache da conta | `agentesia_helena_recursos` (canal, painel, coluna, etiqueta, equipe, usuário; `id_externo`, `id_pai_externo`, `nome`, `posicao`, `dados`, `visto_em`, `sumiu_em`). Tipo que falhou na leitura não marca nada como sumido. Usuário só com id e nome | `app/gestao/sincronizar_conta.py`; `POST /api/admin/escritorios/{id}/sincronizar`, `GET .../helena-recursos`, e para o gestor `POST /api/integracoes/helena/sincronizar`, `GET /api/integracoes/helena/recursos` |
| C Histórico de etapa | `agentesia_lead_etapas` por gatilho em insert/update de `id_etapa`. Origem: `entrada` (lead novo), `equipe` (rota de conversa), `contrato` (`mover_lead_para_etapa`, padrão), `ia` (turno em andamento no lead, com `id_turno`); vazio quando não dá para saber | gatilho na 006; `app/contrato/servico.py` (`origem`) |
| D Nono dígito | `agentesia_contatos.telefone_chave` gerada (55+DDD+8 últimos, só Brasil) + índice. `achar_ou_criar_lead` prefere o número exato e só usa a chave quando há um contato só com ela | `app/banco/postgres.py` |
| E Canal | `agentesia_canais.nome_exibicao`, `tipo_helena`, `sincronizado_em` (preenchidos na sincronização e no passo canais) | `sincronizar_conta.gravar_detalhes_canais` |
| G Falha de admin | `agentesia_alteracoes.situacao` (ok/erro) e `erro`; `registrar_alteracao(..., situacao, erro)`; criação de escritório, onboarding e sincronização registram as falhas | `app/gestao/repositorio.py` |
| Painel | Coluna "Onboarding" e janela com os passos, Conferir, Avançar (com escolha do painel), "Sincronizar conta" e resumo dos dados/ids; opções de etiquetas e equipe na criação | `painel/src/telas/AdminEscritorios.tsx` |

Suposições sobre a API da Helena (conferir no primeiro uso real): `POST core/v1/tag` devolve `{id, name, color}` (cores do fluxo n8n; se recusar a cor, cria sem); `POST core/v1/department {"name","isDefault":true}` devolve `{id}`; `GET core/v1/agent` traz `userId`/`name` (disponibilidade em `availability` ou `status`); campo de plano da empresa (`plan` ou `config.plan`) não confirmado; `GET core/v1/company` sem paginação além de 100. **A API pública não cria painel**: o fluxo n8n usa a API interna `api.wts.chat/crm/v1/panel` com login de usuário por código no e-mail; isso não foi implementado e o passo `painel_padrao` fica pendente até decisão do dono.

Testes: `tests/test_conta_helena.py` (banco local + Helena falsa por `httpx.MockTransport`).

**Painel padrão do CRM com código digitado (decisão do dono, 25/11/2026).** `app/gestao/painel_crm.py` (chamadas), `app/gestao/painel_crm_padrao.py` (corpo do POST, cópia byte a byte do n8n) e `app/gestao/rotas_painel_crm.py` (rotas e travas). Mesma sequência do fluxo n8n de admin: `send-otp` → `authenticate` (código) → `GET core/v5/company?refPartnerId…` (confere o companyId) → `GET core/v1/agent?companyId…&pageSize=1000` (usuário com o e-mail de admin configurado) → `authenticate/impersonate` (`userId`, `tenantId`=companyId) → `POST crm/v1/panel` → grava id do painel e `steps[0..5].id` por tipo (integração `crm` + `dados_helena.ids`). Rotas (só admin LawChat): `GET/POST /api/admin/escritorios/{id}/painel-crm` (`?simular=true` só lê), `POST .../painel-crm/codigo`, `POST .../painel-crm/conferido`. Travas: desligado sem `AGENTESIA_PAINEL_CRM_LIGADO=1` (404; o router nem entra no app), login há menos de 15 min, cabeçalho anti-CSRF `X-LawChat-Acao: painel-crm` + Origin, 3 códigos por escritório/hora, estado atômico por escritório em `dados_helena.painel_crm` (em_andamento/incerto/criado/divergente), "já existe painel" bloqueia antes do código, simulação obrigatória (30 min) antes de criar, token do impersonate só no POST do painel, sem repetição e timeout de 15 s (timeout no painel = "incerto" até marcar "conferido"), retorno conferido (id + 6 etapas com os títulos) senão "divergente" + evento `painel_crm_divergente` na central, auditoria em `agentesia_alteracoes` (IP, passos, erro mascarado). Variáveis em `.env.example`. Testes: `tests/test_painel_crm.py`. Suposições: o `impersonate` vai como JSON (padrão do nó HTTP Request v4 do n8n com "body parameters"; conferir no fluxo); o token volta em `accessToken`; `Referer` = Origin + "/".

### 4.2 Migração proposta (texto original; implementada como 006, ver 4.1.1)

```sql
-- =============================================================================
-- 005_agentesia_conta_helena.sql (PROPOSTA)
-- Onboarding em passos, cache da conta Helena, histórico de etapa do lead,
-- chave de telefone sem o nono dígito e detalhes do canal.
-- Só tabelas agentesia_*. Depende da 001-004. Desfazer: desfazer_005.sql.
-- =============================================================================
begin;

-- A) Onboarding e última sincronização da conta
alter table public.agentesia_escritorios
  add column if not exists onboarding jsonb not null default '{}'::jsonb,
      -- {"passos": [{"codigo":"token","situacao":"feito","detalhe":"...","em":"..."}], "concluido_em": null}
  add column if not exists sincronizado_em timestamptz;

-- B) Cache do que existe na conta da Helena (nunca é fonte de ação sem conferir na hora)
create table if not exists public.agentesia_helena_recursos (
  id              uuid primary key default gen_random_uuid(),
  id_escritorio   uuid not null references public.agentesia_escritorios(id) on delete cascade,
  tipo            text not null check (tipo in ('canal', 'painel', 'coluna', 'etiqueta', 'equipe', 'usuario')),
  id_helena       text not null,
  id_pai_helena   text,                 -- coluna -> painel
  nome            text,
  posicao         int,                  -- ordem da coluna no painel
  dados           jsonb not null default '{}'::jsonb,  -- só o necessário (sem e-mail/telefone de usuário)
  removido_em     timestamptz,          -- sumiu na última sincronização
  sincronizado_em timestamptz not null default now(),
  criado_em       timestamptz not null default now(),
  atualizado_em   timestamptz not null default now(),
  unique (id_escritorio, tipo, id_helena)
);
create index if not exists agentesia_helena_recursos_tipo
  on public.agentesia_helena_recursos (id_escritorio, tipo) where removido_em is null;

-- C) Histórico de etapa do lead, preenchido pelo banco em qualquer caminho de troca
create table if not exists public.agentesia_lead_etapas (
  id              uuid primary key default gen_random_uuid(),
  id_escritorio   uuid not null references public.agentesia_escritorios(id) on delete cascade,
  id_lead         uuid not null references public.agentesia_leads(id) on delete cascade,
  etapa_de        text,                 -- código (agentesia_agente_etapas.codigo)
  etapa_para      text,
  origem          text,                 -- ia | frase | equipe | contrato | painel | sistema (vem de set_config)
  id_turno        uuid references public.agentesia_turnos(id) on delete set null,
  criado_em       timestamptz not null default now()
);
create index if not exists agentesia_lead_etapas_lead on public.agentesia_lead_etapas (id_lead, criado_em desc);
create index if not exists agentesia_lead_etapas_funil on public.agentesia_lead_etapas (id_escritorio, etapa_para, criado_em desc);

create or replace function public.agentesia_registrar_troca_etapa()
returns trigger language plpgsql as $$       -- SECURITY INVOKER de propósito
begin
  if new.id_etapa is distinct from old.id_etapa then
    insert into public.agentesia_lead_etapas (id_escritorio, id_lead, etapa_de, etapa_para, origem, id_turno)
    values (new.id_escritorio, new.id,
            (select codigo from public.agentesia_agente_etapas where id = old.id_etapa),
            (select codigo from public.agentesia_agente_etapas where id = new.id_etapa),
            nullif(current_setting('agentesia.origem_etapa', true), ''),
            nullif(current_setting('agentesia.id_turno', true), '')::uuid);
  end if;
  return new;
end $$;

drop trigger if exists agentesia_leads_troca_etapa on public.agentesia_leads;
create trigger agentesia_leads_troca_etapa
  after update of id_etapa on public.agentesia_leads
  for each row execute function public.agentesia_registrar_troca_etapa();

-- D) Chave de telefone para achar o contato sem o nono dígito: 55 + DDD + 8 últimos
alter table public.agentesia_contatos
  add column if not exists telefone_chave text
  generated always as (case when length(telefone_normalizado) >= 12
                            then left(telefone_normalizado, 4) || right(telefone_normalizado, 8) end) stored;
create index if not exists agentesia_contatos_telefone_chave
  on public.agentesia_contatos (id_escritorio, telefone_chave) where telefone_chave is not null;

-- E) Detalhes do canal vindos da Helena
alter table public.agentesia_canais
  add column if not exists nome_exibicao   text,
  add column if not exists tipo_helena     text,      -- CloudAPI_WhatsApp, ZAPI_WhatsApp, Instagram...
  add column if not exists sincronizado_em timestamptz;

-- G) Falha de ação de admin também fica registrada
alter table public.agentesia_alteracoes
  add column if not exists situacao text not null default 'ok' check (situacao in ('ok', 'erro')),
  add column if not exists erro     text;

-- atualizado_em e RLS (mesmo padrão da 001/002: RLS ligado, sem políticas, só o backend acessa)
create trigger agentesia_helena_recursos_atualizado_em before update on public.agentesia_helena_recursos
  for each row execute function public.agentesia_tocar_atualizado_em();
alter table public.agentesia_helena_recursos enable row level security;
alter table public.agentesia_lead_etapas enable row level security;

commit;
```

Notas da proposta:
- O gatilho C lê a origem por `set_config('agentesia.origem_etapa', 'ia', true)` dentro da transação que troca a etapa; sem isso, grava `origem` vazia (não quebra nada).
- A coluna gerada D é calculada na escrita: uma tabela grande ganha reescrita na migração (hoje é pequena). Testar no PGlite como as outras.
- `agentesia_helena_recursos` tipo `usuario` não deve guardar e-mail nem telefone: só id e nome.
- Precisa de `desfazer_005.sql` e teste em `db/testes`, como 001-004.

### 4.3 O que NÃO vale recriar

| Weaver | Por que não |
|---|---|
| `memoria` (jsonb do n8n) e `mensagens` duplicadas | `agentesia_mensagens` já tem autor, mídia lida e situação de envio; a ficha já existe em `agentesia_lead_resumo` |
| `lead.etapa_atual` (cópia em texto) + `trg_a_lead_sync_etapa_atual` | Fonte da divergência de 502 leads; nós só usamos o id |
| `conversas_agentes`, `dados_helena` | Cabem em `agentesia_leads` (`id_sessao_helena`, `origem`) |
| `card` + `painel_card` + `card_tag` (N:N) | Um card por lead em `agentesia_crm_cards` resolve os 116 leads com vários cards |
| `painel`/`etapas`/`tags` como tabelas de configuração | A configuração já está nas automações do agente; o que falta é validação, coberta pelo cache (4.1 B) |
| `prompts` separado de `agente_etapas`, `models`, `departamento`, `agente_roteiros` | A instrução mora na etapa; modelo em `config`; roteiro é texto |
| `api_key`, `api_key_atributos`, `clientes.api_lawchat`, `conexoes.api_key` | Segredos em texto. Nosso Vault + `agentesia_integracoes` é o certo |
| `followup_cadences` + `prompts_followup` + `followups` + `followup_queue` + `followup_events` | `agentesia_followups` (um pendente por lead) + `config.followup` fazem o mesmo sem as cadências duplicadas e sem enum quebrado |
| `reativacao_fila`, `lead_etapa_audit`, buffer no Redis | `pausado_ate`, `responder_apos`, `processando_ate` no lead |
| `sistemaia_contas` (espelho das empresas) e "habilitar cliente no bot" | Criamos o escritório direto da lista ao vivo; não há "bot" separado para sincronizar |
| Todas as funções `sistemaia_*_no_bot` (sincronizar produto, follow-up, status, notificação, ZapSign, trocar canal) | Existiam para copiar o app para as tabelas do n8n. Aqui o motor lê a configuração direto |
| Chamadas HTTP de dentro do banco (extensão `http` em funções SECURITY DEFINER) | Rede e segredo ficam no servidor Python, com retentativa e log |
| `consumo_tokens_consolidado`, `sistemaia_execucoes_cobradas`, `pagamento_tokens` | Custo já é gravado por chamada; idempotência por execução do n8n não se aplica |
| `templates_whatsapp` em cache | A consulta ao vivo basta enquanto o volume é baixo; se virar gargalo, entra no cache B como mais um tipo |

---

## 5. Pontos de atenção de segurança e dados

| # | Onde | O que | Gravidade |
|---|---|---|---|
| 1 | Weaver `clientes.api_lawchat`, `api_key.chave`, `conexoes.api_key`, `usuarios.tokens` | Tokens da Helena, chaves OpenAI e ZapSign **em texto puro** em tabelas. Qualquer função SECURITY DEFINER ou view mal filtrada expõe. Na importação, **nunca** copiar essas colunas para cá; o token da conta deve ser gerado de novo e ir para o Vault | Alta |
| 2 | 115 ocorrências de `security definer` nas migrações do Weaver | Padrão `if auth.uid() is not null and not admin then raise`: quando `auth.uid()` é nulo a checagem é pulada. A proteção depende de `revoke ... from public, anon` em cada função; uma função sem o revoke fica aberta para a chave anônima. Vale uma varredura no Weaver (fora do escopo deste documento) | Alta |
| 3 | `sistemaia_criar_token_helena` | Lê o token master do Vault e faz HTTP de dentro do banco; executável por `authenticated` (checa admin por dentro). Um erro na checagem dá a qualquer usuário logado a criação de token de qualquer empresa | Alta |
| 4 | Edge `habilitar-funcoes` | Manda o segredo do webhook **no cabeçalho** (`X-LawChat-Secret`) junto com a assinatura HMAC: quem vê a requisição tem o segredo, e o HMAC perde o sentido | Média |
| 5 | Edges admin (`admin-accounts`, `habilitar-funcoes`) | CORS `*` e id/e-mail da conta admin fixos no código-fonte | Baixa/média |
| 6 | `auth-by-company-id` (Weaver) e nosso `/entrar/helena` | Sem o segredo de handoff configurado, o Weaver gera login só com o company_id (o próprio código avisa: tomada de conta). O nosso também aceita sem assinatura quando `AGENTESIA_HELENA_HANDOFF_SEGREDO` não existe, mas exige um id de usuário que a API da Helena confirma na conta. **Configurar o segredo em produção** | Média |
| 7 | `impersonate` (Weaver) | Gera magic link de qualquer conta para o admin; fica só no log de funções | Média (auditoria) |
| 8 | RLS no Weaver | `sistemaia_*` têm políticas por conta; `atendimento_evento` e as tabelas novas têm RLS sem política (só service role). As tabelas do bot (`lead`, `memoria`, `clientes`...) não foram conferidas nesta leitura | A conferir |
| 9 | Nosso banco | RLS ligado sem políticas em todas as `agentesia_*`: só o backend com service role acessa. Manter assim; qualquer acesso direto do painel ao Supabase exigiria políticas por `id_escritorio` | Ok |
| 10 | Nosso `sincronizar_canais` | `on conflict (id_canal_helena) ... where id_escritorio = excluded.id_escritorio`: um canal já ligado a outro escritório é ignorado em silêncio. Melhor registrar evento `canal_de_outro_escritorio` | Baixa |
| 11 | Nosso `GET /admin/helena/empresas` | `PageSize=50` sem paginação: com mais contas, só aparecem com busca | Baixa |
| 12 | Dados pessoais | O cache proposto (4.1 B) não deve guardar e-mail/telefone de atendentes; `agentesia_contatos` e `agentesia_mensagens` já são dados pessoais: ligar backup e definir retenção antes de produção (o projeto está no plano FREE, sem backup, segundo `db/TABELAS.md`) | Média |
| 13 | Projeto compartilhado | As `agentesia_*` vivem no mesmo projeto Supabase do Weaver. Um `truncate ... cascade` ou função SECURITY DEFINER do Weaver mal escrita não alcança nossas tabelas (não há FK cruzada), mas as credenciais do projeto são as mesmas: quem tem a credencial de banco ou a service role usada pelo n8n também alcança as nossas tabelas. Considerar um usuário Postgres próprio, só com acesso às `agentesia_*` | Média |
