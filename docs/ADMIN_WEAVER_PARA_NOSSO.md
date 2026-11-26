# Admin do Weaver → o que existe e o que recriar no nosso sistema

25/11/2026. Leitura só de arquivos: nenhuma API chamada, nada alterado fora deste documento. O objetivo não é migrar dados, e sim ter aqui o equivalente de cada função que o admin da LawChat usa no painel do Weaver.

**Fontes lidas**
- Weaver (`agents-lawchat-main`): `src/App.tsx` (rotas), `src/pages/admin/*` (10 telas), `src/components/admin/*` (AccountForm, BalanceManager, BibliotecaConhecimentoManager, ImpersonationBanner, AdminGuard, AdminLayout), `src/hooks/{useIsAdmin,useAdminFinanceiro,useAvisos,useContaLiberada}.ts`, `src/components/DemoToggle.tsx`, `src/pages/{Auth,Configuracoes}.tsx` (trechos de admin), `supabase/functions/*` (cabeçalhos das 17 edges; `admin-accounts`, `habilitar-funcoes`, `status-check` lidos com mais detalhe), `weaver/migrations/*` (lista de funções `sistemaia_*`, views `sistemaia_v_*` e crons; cabeçalhos de 0003, 0038, 0042, 0044, 0050, 0091, 0104, 0106, 0108, 0114).
- Contexto: `docs/WEAVER_TABELAS_E_ADMIN.md` (primeira criação e sincronizar conta; não repito o detalhe que está lá).
- Nosso lado: `app/gestao/{rotas,produtos,metricas,repositorio}.py`, `app/main.py` (rotas), `db/migracoes/001..005`, `painel/src/main.tsx` e telas `AdminEscritorios`, `Equipe`, `Modelos`, `Erros`, `Historico`, `Avisos`, `pages/admin/AdminProdutos`, `AdminProdutoEditor`, `components/admin/*`.

**Observação:** a pasta `supabase/migrations` não existe no Weaver; as migrações estão só em `weaver/migrations` (150 arquivos). Os fluxos n8n chamados pelo admin (`ativar_criarcrm_criaretiqueta_criarwebhook`, o antigo `sincronizar_canal_whatsapp`) não estão nas pastas locais.

---

## Resumo em números

| Área | Funções no Weaver | Igual | Parcial | Não existe | Não vale recriar |
|---|---|---|---|---|---|
| A. Acesso e navegação | 4 | 2 | 1 | 0 | 1 |
| B. Contas/clientes | 11 | 1 | 5 | 3 | 2 |
| C. Sincronização com a Helena | 5 | 2 | 1 | 0 | 2 |
| D. Criar/habilitar agente e funções | 5 | 3 | 2 | 0 | 0 |
| E. Planos | 5 | 0 | 0 | 3 | 2 |
| F. Saldo, créditos e financeiro | 7 | 0 | 2 | 3 | 2 |
| G. Catálogo/produtos/biblioteca (inclui prompts, conhecimento e follow-up padrão) | 13 | 13 | 0 | 0 | 0 |
| H. Usuários/equipe/permissões | 5 | 3 | 2 | 0 | 0 |
| I. Entrar como cliente | 2 | 1 | 1 | 0 | 0 |
| J. Logs/auditoria | 1 | 0 | 1 | 0 | 0 |
| K. Avisos (comunicados no app) | 3 | 0 | 0 | 3 | 0 |
| L. Status do sistema | 3 | 0 | 1 | 1 | 1 |
| **Total** | **64** | **25** | **16** | **13** | **10** |

Leitura rápida: o catálogo já foi portado inteiro; o que falta está na **operação dos escritórios** (ficha, situação, onboarding, sincronizar, usuários dos clientes, log com falhas) e na parte **comercial** (planos e saldo), que depende de decisão.

Notificações à equipe, contratos/ZapSign e follow-up do agente **não têm função de admin no Weaver**: são telas do cliente (o admin só chega nelas entrando como cliente). Estão na seção M só para mostrar o nosso equivalente.

O que o nosso sistema tem e o Weaver não tem no admin: responsável da LawChat por escritório, erros abertos e consumo do mês na lista de escritórios, limite mensal de consumo por escritório, "Erros de todos os escritórios", modelos de agente (`/admin/modelos`, inclusive "salvar agente como modelo"), importação do catálogo do Weaver, papéis dono/admin na equipe com regra de "pelo menos um dono".

---

## 1 e 2. Inventário por área, com o nosso equivalente

Legenda de n8n: **sim** = a função chama ou depende de um fluxo n8n; **indireto** = grava tabelas do "bot" que só o n8n lê; **não** = não passa pelo n8n.

### A. Acesso e navegação

| # | Função (o que faz para o admin) | Onde no Weaver · lê → grava | n8n | Nosso equivalente | Situação |
|---|---|---|---|---|---|
| A1 | Login da equipe por e-mail e senha em rota separada (`/acesso` ou `?admin=1`); o cliente entra pela Helena | `pages/Auth.tsx` · Supabase Auth | não | `POST /api/entrar` + tela `Entrar.tsx`; `/acesso` e `/login` redirecionam | Igual |
| A2 | Só `admin_plataforma` vê o menu "Admin" e as rotas `/admin/*` | `AdminGuard`, `useIsAdmin`, `Sidebar` · lê `sistemaia_usuarios.role` | não | Dependência `ADMIN`/`DONO` em `rotas.py` (papéis `dono_lawchat`, `admin_lawchat`), menu por papel no painel | Igual (melhor: checagem no servidor, não só na tela) |
| A3 | Cliente só usa o app se a conta está liberada (`situacao` ativo/implementando **e** "Criar Agente" ligado); expulsa na navegação seguinte | `hooks/useContaLiberada.ts` · lê `sistemaia_v_contas` | não | `/entrar/helena` recusa escritório com `situacao != 'ativo'`; o motor não responde com escritório suspenso | Parcial: quem já está logado continua no painel; o `contexto()` não confere a situação do escritório a cada pedido |
| A4 | "Modo exibição" com dados de demonstração, botão só para admin | `components/DemoToggle.tsx` | não | — | Não vale recriar (serve para demo comercial; se precisar, um escritório de demonstração com dados de teste resolve) |

### B. Contas/clientes (tela `AdminContas`)

| # | Função | Onde no Weaver · lê → grava | n8n | Nosso equivalente | Situação |
|---|---|---|---|---|---|
| B1 | Lista de contas: nome, razão social, CNPJ, situação, "Criar Agente", "Funções", status do webhook, última sincronização | `AdminContas.tsx` · lê `sistemaia_v_contas`, `sistemaia_contas.funcoes_habilitadas` | não | `GET /admin/escritorios` (`repositorio.escritorios`) + `AdminEscritorios.tsx`: nome, conta Helena, situação da integração Helena, agentes ativos/total, erros (7 dias), consumo do mês, situação, responsável | Parcial: falta "última sincronização" (vem com a 006) e o estado do onboarding por passo |
| B2 | Busca (nome, CNPJ, e-mail), filtro "Criar Agente" on/off, ocultar contas não sincronizadas | idem, filtro no navegador | não | Filtro "Todos / Comigo" | Parcial: sem busca e sem filtro por situação, Helena ou erros |
| B3 | Indicador geral "Status do Webhook" (quantas contas em erro/pendentes) | idem, calculado de `status_sincronizacao` | não | Coluna "Helena" por linha | Parcial: sem o resumo no topo |
| B4 | Ficha da conta: company id, datas, empresa, administrador, endereço, plano, funções, saldo | modal de detalhe · lê `sistemaia_contas`, `sistemaia_v_conta_plano`, `BalanceManager` | não | — (só a linha da tabela; detalhes só entrando no escritório) | Não existe |
| B5 | Nova conta manual (tipo PF/PJ, CNPJ, razão social, administrador, endereço com ViaCEP, recursos e limites de canais/usuários/painéis) | `AccountForm.tsx` · grava `sistemaia_contas`, chama `sistemaia_definir_plano_conta` | não | `POST /admin/escritorios` (nome, conta Helena, token gerado no servidor, gestor com senha provisória, domínio da Helena) | Parcial: cria o que o motor precisa. CNPJ/endereço/administrador não são guardados. Recursos e limites são da conta Helena: **não vale recriar** essa parte |
| B6 | Editar conta | `AccountForm` suporta edição, mas a tela só abre o formulário vazio ("Nova conta"); não há botão de editar | não | Nome editável em `PATCH /escritorio` (Configurações) | Igual na prática (o Weaver também não edita pela tela) |
| B7 | Mudar situação em lote (ativo, implementando, inativo, cancelado) | `submitBulk` · `update sistemaia_contas.situacao` | não (mas a situação bloqueia o cliente via A3) | `PATCH /escritorio` aceita `situacao` (`ativo`/`suspenso`/`encerrado`) só para a equipe LawChat | Parcial: **não há botão na tela** (só a API) e não há lote |
| B8 | Mudar plano em lote | `sistemaia_definir_plano_conta` por conta | indireto (grava `clientes.plano`) | — | Não existe (depende da decisão sobre planos, E) |
| B9 | Bônus de crédito em lote | `sistemaia_ajustar_saldo_conta(_origem='bonus_admin')` | indireto (saldo corta o agente) | — | Não vale recriar enquanto não houver saldo pré-pago (F) |
| B10 | Exportar CSV das contas (selecionadas ou filtradas) | gerado no navegador | não | — | Não existe |
| B11 | Contas "não sincronizadas" escondidas por padrão (workspace sem company id) | filtro de `status_sincronizacao` | não | Não se aplica: nosso escritório já nasce de uma conta da Helena escolhida na lista ao vivo | Não vale recriar |

### C. Sincronização com a Helena

| # | Função | Onde no Weaver · lê → grava | n8n | Nosso equivalente | Situação |
|---|---|---|---|---|---|
| C1 | "Sincronizar com LawChat": baixa todas as empresas da Helena e faz upsert do espelho | edge `admin-accounts` `sync` · Helena `GET core/v1/company` (token master) → `sistemaia_contas` | não (substituiu o fluxo `sincronizar_contas`) | `GET /admin/helena/empresas?busca=` ao vivo (`HelenaParceiro.empresas`), usado no "Novo escritório" | Não vale recriar o espelho; a lista ao vivo basta. Pendente: paginação (só 50 sem busca) |
| C2 | Sincronizar uma conta (botão por linha) | `admin-accounts` `sync_one` | não | — | Parcial: o "sincronizar conta" que interessa aqui é outro (canais, painéis, etiquetas, equipes da conta), em andamento na **migração 006** |
| C3 | Sincronizar números de WhatsApp da conta (livre/ocupado) | RPC `sistemaia_sincronizar_numeros_whatsapp` (HTTP de dentro do banco com o token do cliente) → `sistemaia_numeros_whatsapp` | não | `POST /integracoes/helena/canais` + passo `canal` da ativação → `agentesia_canais`; `GET /canais/disponiveis` (com a **004**, número de produto na lixeira volta a ficar livre) | Igual |
| C4 | Sincronizar modelos oficiais (templates Meta) | RPC `sistemaia_sincronizar_templates_whatsapp` → `sistemaia_templates_whatsapp` | não | `GET /integracoes/helena/modelos-aprovados` ao vivo | Igual |
| C5 | Edge antiga `sync-whatsapp-numbers` (chamava webhook n8n) | edge | sim | — | Não vale recriar (legado) |

### D. Criar/habilitar agente e "Habilitar Funções"

| # | Função | Onde no Weaver · lê → grava | n8n | Nosso equivalente | Situação |
|---|---|---|---|---|---|
| D1 | "Criar Agente" ligado: cria/atualiza o cliente no bot, gera token da Helena, aplica o plano escolhido (obrigatório na tela) | RPC `sistemaia_habilitar_cliente_no_bot` + `sistemaia_criar_token_helena` (HTTP no banco) + `sistemaia_definir_plano_conta` · grava `clientes`, `planos`, `sistemaia_contas` | indireto | `POST /admin/escritorios` com `gerar_token_helena` (token no Vault, `agentesia_integracoes` tipo `helena`) | Igual (melhor), sem plano |
| D2 | "Criar Agente" desligado: cliente inativo, nada apagado | mesma RPC com `status='desativado'` | indireto | `situacao` do escritório (`suspenso`/`encerrado`) e `ia_desligada` | Parcial: falta botão no admin (ver B7) |
| D3 | "Habilitar Funções" (uso único): cria painel do CRM com 6 colunas, etiquetas padrão e assinatura de webhook na Helena | edge `habilitar-funcoes` → webhook n8n `ativar_criarcrm_criaretiqueta_criarwebhook` · grava `painel`, `etapas`, `tags`, `clientes.id_webhook/id_departamento`, `sistemaia_contas.funcoes_habilitadas` | **sim** | Webhook: `POST /integracoes/helena/conectar` e passo `webhook` da ativação (idempotente). Painel: o gestor escolhe um existente (`PUT /integracoes/crm`). Etiquetas: criadas na hora por nome (`InsertIfNotExists`) | Parcial: falta criar etiquetas padrão e (se a API permitir) painel padrão num passo do **onboarding da 006** |
| D4 | Ativar produto (feito pelo cliente, ou pelo admin entrando como cliente) | tela Ativar → edge `ativar-produto` → RPC `sistemaia_ativar_produto_no_bot`; `agent-build-callback` (n8n avisa fim da construção) | indireto (o callback é sim) | `POST /produtos-ativados/rascunho`, `.../{id}/ativar`, `POST /agentes/{id}/ativacao` (checagem em 10 passos) | Igual (melhor: só liga sem erro) |
| D5 | Cópia dos documentos padrão do catálogo para o agente recém-ativado (travados) | RPC `sistemaia_conhecimento_copiar_catalogo` | não | `agentesia_documentos.origem/travado` na ativação (`produtos.py`) | Igual |

### E. Planos (tela `AdminPlans`)

| # | Função | Onde no Weaver · lê → grava | n8n | Nosso equivalente | Situação |
|---|---|---|---|---|---|
| E1 | Criar, editar e excluir planos (preços mensal/anual, canais e usuários incluídos, cria agentes, bônus em R$, recursos de áudio/mídia/documentos, enterprise) | `AdminPlans.tsx` · `sistemaia_planos` | não | — | Não existe |
| E2 | Ver adicionais (só leitura) | `sistemaia_planos_adicionais` | não | — | Não vale recriar (tabela comercial sem uso no motor) |
| E3 | Aplicar plano a uma conta (e o catálogo vira a tabela `planos` do bot) | `sistemaia_definir_plano_conta`, `sistemaia_sync_plano_catalogo` · `clientes.plano`, `planos` | indireto | — | Não existe |
| E4 | Bônus de crédito do plano (mensal e no aniversário) | crons `sistemaia-bonus-plano-mensal`/`-aniversario` · `sistemaia_creditar_bonus_plano*` | não | — | Não vale recriar sem saldo pré-pago |
| E5 | Plano mínimo do produto bloqueia a ativação | `sistemaia_biblioteca_produtos.plano_minimo` + checagem (0109) | não | Campo `plano_minimo` existe no nosso catálogo e é importado, **mas nada o confere** | Não existe (a checagem) |

### F. Saldo, créditos e financeiro

| # | Função | Onde no Weaver · lê → grava | n8n | Nosso equivalente | Situação |
|---|---|---|---|---|---|
| F1 | Ver saldo da conta, total recarregado/gasto, 15 últimas recargas, custo interno | `BalanceManager` · `sistemaia_saldos`, `sistemaia_recargas`, `sistemaia_v_billing_admin` | não | Coluna "Consumo do mês" (US$) em `AdminEscritorios`; `GET /consumo` do escritório (dia a dia e por função) | Parcial: há custo, não há saldo |
| F2 | Crédito (bônus) ou débito manual com motivo | `sistemaia_ajustar_saldo_conta` | indireto (corte por saldo) | — | Não existe (depende de decisão de produto) |
| F3 | Margem por conta (quanto o saldo desce por US$ de custo) | `sistemaia_definir_margem` | não | — | Não existe |
| F4 | Lista de recargas (Asaas) de todas as contas | `AdminRecharges` · `sistemaia_v_recargas_admin` | não | — | Não vale recriar enquanto a cobrança não for pelo nosso sistema |
| F5 | Controle financeiro: saldo na plataforma, recarregado, bônus, cobrado, custo real, lucro por conta | `AdminFinanceiro`, `useAdminFinanceiro` · `sistemaia_v_billing_admin`, `sistemaia_v_recargas_admin` | não | Só o gasto do mês por escritório | Parcial: falta a visão consolidada de custo (todos os escritórios, por mês, modelo e função) |
| F6 | Reprocessar pagamento Asaas (admin, **sem botão na tela**) | edge `asaas-reprocess` | não | — | Não vale recriar |
| F7 | Rotinas de cobrança: debitar consumo, cortar agente sem saldo (com tolerância negativa), cotação do dólar, conferir recargas pendentes | crons `sistemaia-processar-consumo`, `-atualizar-cotacao`; `sistemaia_trg_corte_saldo`, `sistemaia_definir_tolerancia`; edge `asaas-poll-pending` | indireto (o n8n lê o corte) | `app/consumo.py`: limite mensal em US$ com "pausar" ou "só avisar" e avisos em 80/100% (`PUT /admin/escritorios/{id}/limite`) | Não existe como saldo; o limite cobre o risco de gasto |

### G. Catálogo, prompts, conhecimento e follow-up padrão (`AdminProdutos`, `AdminProdutoEditor`)

Nosso painel já tem a mesma tela portada (`painel/src/pages/admin/AdminProdutos.tsx`, `AdminProdutoEditor.tsx`), falando com `app/gestao/produtos.py` em vez do Supabase.

| # | Função | Onde no Weaver · lê → grava | n8n | Nosso equivalente | Situação |
|---|---|---|---|---|---|
| G1 | Lista do catálogo com contagem por status, busca, categoria | `sistemaia_biblioteca_produtos` | não | `GET /biblioteca/produtos?todos=1` | Igual |
| G2 | Criar produto no padrão (5 agentes prontos) | RPC `sistemaia_criar_produto_padrao` | não | `POST /admin/biblioteca/produtos/padrao` | Igual |
| G3 | Mudar status (rascunho, em breve, publicado) | `update` direto | não | `PATCH /admin/biblioteca/produtos/{id}` | Igual |
| G4 | Duplicar | `insert` da cópia + agentes | não | `POST .../{id}/duplicar` | Igual |
| G5 | Excluir | `delete` | não | `DELETE .../{id}` | Igual |
| G6 | Identidade: nome, slug, ícone, capa, categoria, plano mínimo, versão, tags, produto com mídia | editor · `sistemaia_biblioteca_produtos` | não | `POST/PATCH /admin/biblioteca/produtos` | Igual (plano mínimo sem efeito, E5) |
| G7 | Agentes por papel: prompt, gatilho de transferência, mensagens de boas-vindas/despedida/fallback, modelo; baixar prompt `.md` | `sistemaia_biblioteca_agentes` | não | `PUT /admin/biblioteca/produtos/{id}/agentes`; botão de baixar portado | Igual |
| G8 | Frases de troca de departamento por produto | `sistemaia_salvar_frase_troca`, `sistemaia_excluir_frase_troca` · `sistemaia_frases_troca` | não | `PUT/DELETE /admin/biblioteca/frases-troca` | Igual |
| G9 | Conteúdo padrão: regras gerais, dados do escritório, FAQ, objeções | colunas do produto/agente | não | mesmos campos (`regras_markdown`, `dados_escritorio`, `faq`, `objecoes`) | Igual |
| G10 | Conhecimento padrão (arquivo ou texto) por produto | `BibliotecaConhecimentoManager` · Storage `knowledge` + `sistemaia_biblioteca_conhecimento`; ingestão pela edge `sistemaia_processar_conhecimento` | não | `POST/DELETE /admin/biblioteca/produtos/{id}/documentos` (texto extraído no servidor) | Igual |
| G11 | Follow-up padrão: cadência, etapas com follow-up, prompt por etapa do CRM | `sistemaia_biblioteca_followups` | não | `padrao_followup` (jsonb do produto) | Igual |
| G12 | Recuperar alterações não salvas (rascunho no navegador) | `useRascunhoLocal` | não | `hooks/useRascunhoLocal.ts`, usado no nosso editor | Igual |
| G13 | Resposta com mídia (áudio/vídeo da biblioteca de mídia) no editor | `useBibliotecaMidia` · `sistemaia_biblioteca_midia` (+ edge `transcribe-media`) | não | `RespostaComMidia` + rotas `/midia` | Igual na tela; a biblioteca de mídia aqui é por escritório. **Não vale recriar** a transcrição pela edge (já está no motor) |

### H. Usuários, equipe e permissões (`AdminUsersAdmin`)

| # | Função | Onde no Weaver · lê → grava | n8n | Nosso equivalente | Situação |
|---|---|---|---|---|---|
| H1 | Listar usuários com escopo "equipe da plataforma / logins de clientes / todos", filtro por papel, busca | `sistemaia_usuarios` | não | `GET /admin/equipe` + `Equipe.tsx` (só a equipe LawChat) | Parcial: não há lista de usuários dos escritórios no admin |
| H2 | Editar nome, telefone, papel, ativo | `update sistemaia_usuarios` | não | `PATCH /admin/equipe/{id}` (nome, papel, ativo; só dono; impede ficar sem dono) | Igual para a equipe; não existe para usuários de clientes |
| H3 | Ativar/desativar | idem | não | idem | Igual (equipe) |
| H4 | Promover alguém a admin por e-mail | `update ... set role` | não | `POST /admin/equipe` cria a pessoa com senha provisória | Igual (o papel é separado de escritório por regra no banco) |
| H5 | E-mail de redefinição de senha | `supabase.auth.resetPasswordForEmail` | não | `POST /admin/equipe/{id}/senha` (senha provisória mostrada uma vez) | Parcial: só equipe; para usuários de clientes não há ação no admin |

### I. Entrar como cliente

| # | Função | Onde no Weaver · lê → grava | n8n | Nosso equivalente | Situação |
|---|---|---|---|---|---|
| I1 | "Acessar como cliente": gera magic link do administrador da conta, troca a sessão do navegador inteiro, guarda o refresh do admin | edge `admin-accounts` `impersonate` · cria usuário no Auth se não existe; log em `sistemaia_logs_funcoes` | não | "Entrar" (poderes LawChat) e "Como cliente" (visão do gestor) em `AdminEscritorios`: cabeçalhos `X-Escritorio` e `X-Visao`, a sessão continua sendo do admin | Parcial: melhor que o Weaver (não troca sessão nem cria usuário), mas **a entrada não fica registrada** em `agentesia_alteracoes` |
| I2 | Faixa "Impersonificação" + "Voltar para admin" | `ImpersonationBanner` | não | `components/admin/ImpersonationBanner.tsx` (troca a visão) | Igual |

### J. Logs, erros e auditoria

| # | Função | Onde no Weaver · lê → grava | n8n | Nosso equivalente | Situação |
|---|---|---|---|---|---|
| J1 | Logs de funções: cada ação admin/bot com ok/erro, executor, conta, duração, payload, resultado, erro; filtros por período/status/função, busca, copiar, CSV | `AdminLogsFuncoes` · `sistemaia_v_logs_funcoes` (gravado por edges e `chamarRpcBot`) | não | `agentesia_alteracoes` (antes/depois, quem) na tela `Historico.tsx` **do escritório aberto**; a API já aceita `todos_escritorios` para admin | Parcial: só sucesso, sem tela global, sem filtros, sem CSV |
| (extra) | Erros do atendimento de todas as contas | não há no admin do Weaver (fica no n8n e em `atendimento_evento`) | — | `/admin/erros` (`Erros.tsx todos`, `GET /eventos?todos_escritorios=true`, resolver) | Só nosso (não contado). Falta filtro por escritório e tipo |

### K. Avisos (comunicados dentro do app) — `AdminAvisos`

| # | Função | Onde no Weaver · lê → grava | n8n | Nosso equivalente | Situação |
|---|---|---|---|---|---|
| K1 | Criar/editar/excluir aviso: faixa ou modal, cor, botão com link, janela de datas, perfis alvo, contas alvo ou todas | `sistemaia_avisos`; lista contas de `sistemaia_v_contas` | não | — (nossa tela "Avisos" é outra coisa: avisos por WhatsApp para a equipe do escritório) | Não existe |
| K2 | Ligar/desligar aviso | `update ativo` | não | — | Não existe |
| K3 | Contagem de vistos e cliques | RPC `sistemaia_aviso_incrementar` (cliente); dispensar fica no navegador | não | — | Não existe |

### L. Status do sistema — `AdminStatus`

| # | Função | Onde no Weaver · lê → grava | n8n | Nosso equivalente | Situação |
|---|---|---|---|---|---|
| L1 | Lista de serviços com status e latência, "checar agora" e checagem automática a cada 30 s (feita pelo navegador) | `sistemaia_servicos`, `sistemaia_configuracoes` | não | `GET /saude` (`app/main.py`) | Parcial: sem tela e sem checagem de dependências externas |
| L2 | Incidentes: abrir (severidade, serviço), monitorar, resolver | `sistemaia_incidentes` | não | — | Não vale recriar (página de status pública não é necessidade de operação hoje) |
| L3 | Checagem pelo servidor com proteção contra SSRF | edge `status-check` (`service_definitions`) | não | — | Não existe |

### M. Áreas sem função de admin no Weaver (para referência)

| Área | Weaver (tela do cliente) | Nosso |
|---|---|---|
| Notificações à equipe | `ConfiguracoesGlobais`, edge `emit-event` (assinaturas de webhook n8n + notificações), `sistemaia_sincronizar_notificacao_no_bot` → `avisos` (n8n "99 - Alerta Notificação") | `GET/PUT/DELETE /notificacoes/{tipo}`, `POST .../teste`, tela `Avisos.tsx`; disparo pelo motor (`automacoes.py`, `acoes.py`) |
| Contratos/ZapSign | `zapsign-proxy` (listar modelos), `zapsign-webhook` → `sistemaia_assinaturas`; geração no n8n | `/integracoes/zapsign/*`, `/webhook/zapsign/{id}`, `app/contrato/*` |
| Follow-up do agente | `FollowUp`, `FollowUpEditor`, `sistemaia_sincronizar_followup_no_bot` | `GET/PUT /agentes/{id}/followup`, prévia, `app/followup/servico.py` |
| Conhecimento do agente | `useConhecimento`, RPCs `sistemaia_conhecimento_*`, worker de ingestão | `/agentes/{id}/documentos`, lacunas |
| Teste do agente | edge `agent-chat` (efêmero) | `POST /agentes/{id}/laboratorio`, `/lab` |

---

## 3. O que recriar, por prioridade

Critério: valor para operar os clientes no dia a dia × esforço. "006" = migração em andamento (onboarding em passos + sincronizar conta da Helena). "004" = lixeira que solta o número (já existe).

| # | Item | Cobre | Valor | Esforço | Depende de |
|---|---|---|---|---|---|
| 1 | Onboarding em passos e "Sincronizar conta" no admin | D3, C2, B1 (última sync), D2 | Alto | Médio | **006** |
| 2 | Ficha do escritório no admin + suspender/encerrar/reativar | B4, B7, D2, A3 | Alto | Baixo | 004 (encerrar solta números), 006 (mostra os passos) |
| 3 | Log de ações do admin com falhas + tela global | J1, I1 (registrar "entrou") | Alto | Baixo | 006 (colunas em `agentesia_alteracoes`) |
| 4 | Usuários dos escritórios no admin | H1, H2, H5 | Médio-alto | Baixo | — |
| 5 | Custo da IA consolidado (todos os escritórios, por mês) | F1, F5 | Médio-alto | Médio | — (usa `agentesia_chamadas_ia`) |
| 6 | Lista de escritórios com busca, filtros, lote e CSV | B2, B3, B7 (lote), B10 | Médio | Baixo | itens 1 e 2 |
| 7 | Saúde do sistema para o admin | L1, L3 | Médio | Baixo-médio | — |
| 8 | Comunicados no painel (faixa/modal) | K1–K3 | Médio-baixo | Médio | — |
| depois | Planos e saldo pré-pago (planos, aplicar plano, bônus, margem, recargas, corte por saldo, plano mínimo do produto) | E1, E3, E5, F2, F3, F7 | Alto comercialmente | Alto | **Decisão do dono**: continuar com limite em US$ ou voltar ao saldo em R$ |

### 3.1 Onboarding em passos e "Sincronizar conta" (006)

- **Rotas**: `GET /admin/escritorios/{id}/onboarding` (passos e situação); `POST /admin/escritorios/{id}/onboarding` (roda os passos pendentes ou um passo: `{"passo": "etiquetas"}`); `POST /admin/escritorios/{id}/sincronizar` (atualiza o cache da conta).
- **Passos** (reusar o padrão `ativacao.Passo`): `token` (existe/valida) → `webhook` (`garantir_assinatura`) → `canais` (mesma lógica de `POST /integracoes/helena/canais`) → `etiquetas` (cria as padrão por nome, idempotente, `POST core/v1/tag`) → `crm` (escolher painel existente; criar painel padrão só se a API da Helena permitir, a confirmar) → `equipe` (equipe de transferência) → `gestor` (existe usuário gestor).
- **Tela**: na ficha do escritório (item 2), bloco "Primeiros passos" com um botão por passo e "Rodar tudo"; na lista, um selo "onboarding 5/7".
- **Tabela**: o que a 006 já prevê: `agentesia_escritorios.onboarding` (jsonb por passo, com situação, detalhe, quando e quem), `sincronizado_em`, `agentesia_helena_recursos` (canal, painel, coluna, etiqueta, equipe, usuário sem e-mail/telefone).
- Substitui três botões do Weaver ("Sincronizar", "Criar Agente", "Habilitar Funções") e corrige o problema de lá: reenviar é seguro porque cada passo é idempotente e o resultado fica gravado.

### 3.2 Ficha do escritório e situação

- **Rotas**: `GET /admin/escritorios/{id}` (dados, integrações e situação de cada uma, agentes e números, gestor(es), limite, responsável, onboarding); `PATCH /admin/escritorios/{id}` com `situacao` (`ativo`/`suspenso`/`encerrado`), `ia_desligada`, `nome`, `config.cadastro` opcional (CNPJ, contato do responsável no cliente; só se o dono quiser guardar).
- **Encerrar** usa a 004: os agentes do escritório vão para "sem número" (`id_canal = null`, `id_canal_anterior`, `canal_liberado_em`) e os números ficam livres; **suspender** só bloqueia (IA não responde, `/entrar/helena` recusa). Pedir confirmação com o nome digitado para encerrar.
- **Bloqueio de quem já está logado** (A3): `contexto()` passa a recusar usuários de escritório com `situacao != 'ativo'` (403 com mensagem clara), não só no login.
- **Tela**: painel lateral ou página `/admin/escritorios/:id` aberta ao clicar na linha de `AdminEscritorios.tsx`.
- **Tabela**: nenhuma nova (colunas existem desde a 002 e a 004).

### 3.3 Log de ações do admin com falhas

- **Tabela**: `agentesia_alteracoes.situacao` (`ok`/`erro`) e `erro`, como já proposto para a 006 (item G de `WEAVER_TABELAS_E_ADMIN.md`).
- **Código**: um ajudante `registrar_falha(...)` chamado nos `except` das rotas de admin (criar escritório, gerar token, onboarding, sincronizar, situação, limite, equipe) e um registro `acao='entrou'` quando a equipe abre um escritório (um por sessão e escritório, para não encher a tabela).
- **Rota**: `GET /admin/alteracoes?escritorio=&acao=&situacao=&desde=&ate=` (o `GET /alteracoes?todos_escritorios=true` já faz metade).
- **Tela**: `/admin/historico`, reusando `Historico.tsx` com filtros, coluna do escritório e "Exportar CSV".

### 3.4 Usuários dos escritórios no admin

- **Rotas**: `GET /admin/usuarios?escritorio=&papel=&busca=` (gestores e atendentes de todos os escritórios, com último acesso se houver); `PATCH /admin/usuarios/{id}` (ativo, papel `gestor`/`atendente`); `POST /admin/usuarios/{id}/senha` (senha provisória mostrada uma vez, como na equipe).
- **Tela**: aba "Usuários dos escritórios" em `Equipe.tsx` (ou `/admin/usuarios`). Também uma seção na ficha do escritório (3.2).
- **Tabela**: nenhuma (`agentesia_usuarios`). Registrar cada mudança em `agentesia_alteracoes`.

### 3.5 Custo da IA consolidado

- **Rota**: `GET /admin/consumo?mes=AAAA-MM` → por escritório: gasto US$, chamadas, tokens, limite e percentual; quebras por modelo e por função; comparação com o mês anterior. Opcional `?escritorio=` para o detalhe diário (reusa `repo.consumo_do_mes`).
- **Tela**: `/admin/consumo` com cartões (total do mês, escritórios acima de 80%, maior gasto) e tabela ordenável; exportar CSV.
- **Tabela**: nenhuma; consulta agregada em `agentesia_chamadas_ia` (conferir índice por `(id_escritorio, criado_em)`). Se a cobrança voltar a ser em R$, este é o ponto de partida para "cobrado × custo".

### 3.6 Lista de escritórios: busca, filtros, lote e CSV

- **Tela** (`AdminEscritorios.tsx`): busca por nome ou conta Helena; filtros por situação, integração Helena (`ok`/`erro`/`pendente`), "com erros abertos", "acima de 80% do limite", onboarding incompleto; resumo no topo ("3 escritórios com a Helena em erro").
- **Lote**: `POST /admin/escritorios/lote` `{ids, acao: "situacao"|"limite"|"responsavel", valor}` com resultado por escritório (ok/erro), cada um registrado no log (3.3).
- **CSV**: gerado no navegador a partir da lista (sem dados pessoais além do nome do escritório).

### 3.7 Saúde do sistema

- **Rota**: `GET /admin/saude` (no servidor, sem o navegador chamar terceiros): banco (latência), fila `agentesia_acoes` (pendentes e atrasadas), webhooks recebidos na última hora (total e escritórios ativos sem nenhum há mais de X horas), eventos críticos nas últimas 24 h, e um teste leve das dependências (Helena, OpenAI/Anthropic, ZapSign) com tempo limite e sem gastar tokens.
- **Tela**: `/admin/saude` com cartões verde/amarelo/vermelho e atualização manual. Sem incidentes (L2 não vale recriar).
- **Tabela**: nenhuma.

### 3.8 Comunicados no painel

- **Tabela** (migração futura, depois da 006): `agentesia_comunicados` (`id`, `titulo`, `mensagem`, `tipo` faixa/modal, `cor`, `cta_texto`, `cta_url`, `inicio`, `fim`, `papeis` text[], `escritorios` uuid[], `todos` bool, `ativo`, `vistos`, `cliques`, `criado_por`, `criado_em`). RLS ligado sem políticas, como as outras.
- **Rotas**: `GET/POST/PUT/DELETE /admin/comunicados`; `GET /comunicados` (ativos para o usuário logado, filtrando data, papel e escritório no servidor); `POST /comunicados/{id}/visto` e `/clique`.
- **Tela**: `/admin/comunicados` (lista + formulário) e a faixa/modal em `componentes/Estrutura.tsx`; "dispensar" fica no navegador como no Weaver.

### 3.9 Depois, com decisão do dono: planos e saldo

O Weaver cobra por saldo pré-pago em R$ (recarga Asaas, débito por cron, margem por conta, bônus por plano, corte do agente com tolerância negativa) e libera produtos por plano. Nós temos limite mensal em US$ por escritório. Se o dono quiser voltar ao modelo do Weaver, o desenho mínimo é: `agentesia_planos` (catálogo), `agentesia_escritorios.id_plano`, `agentesia_saldo_movimentos` (crédito, débito, bônus, ajuste, com origem e quem), conferência de `plano_minimo` na ativação e o corte reaproveitando a mesma decisão `_por_que_nao_atende` que já trata o limite de consumo. Sem essa decisão, nenhuma tabela.

---

## 4. Não vale recriar (resumo)

| Weaver | Por quê |
|---|---|
| Espelho `sistemaia_contas` e "Sincronizar com LawChat" de todas as empresas | A lista ao vivo da Helena basta; o escritório nasce de uma conta escolhida |
| Recursos e limites da conta Helena no formulário (chatbots, painéis, sequências, canais) | São da Helena, não do nosso motor |
| Funções `*_no_bot` e o webhook n8n de "Habilitar Funções" | Existiam para copiar o app para as tabelas do n8n; aqui o motor lê a configuração direto e o onboarding faz os passos no servidor |
| Token da Helena gerado por HTTP de dentro do Postgres | Já geramos no servidor Python e guardamos no Vault |
| Magic link para "acessar como cliente" | Nossa visão por cabeçalho é mais segura (a sessão continua sendo do admin) |
| Modo exibição (demo) | Uso comercial; um escritório de demonstração resolve |
| Página de status com incidentes; checagem feita pelo navegador | Substituída pela saúde do sistema no servidor (3.7) |
| Recargas Asaas, reprocessar pagamento, adicionais de plano | Só se a cobrança vier para o nosso sistema (3.9) |
| Edge antiga `sync-whatsapp-numbers` (n8n) e `agent-build-callback` | Legado do n8n |

---

## 5. Pontos de atenção encontrados nesta leitura

- **Weaver, `AdminContas`**: a situação e o plano em lote são `update` direto em `sistemaia_contas` pelo navegador (dependem só da RLS de admin) e não passam por `sistemaia_logs_funcoes`; só "Criar Agente" e "Habilitar Funções" ficam no log. No nosso, toda ação de admin deve passar por rota com registro (3.3).
- **Weaver, `AdminUsersAdmin`**: "Promover por e-mail" é um `update ... set role='admin_plataforma'` pelo navegador; a proteção é só a RLS. No nosso, só o dono muda papéis e o banco impede papel LawChat ligado a escritório.
- **Weaver, `AdminStatus`**: a checagem roda no navegador do admin e grava o resultado na tabela (qualquer admin com a tela aberta escreve status); a edge `status-check` faz certo (no servidor, com bloqueio de SSRF), mas a tela não a usa.
- **Nosso**: `PATCH /escritorio` aceita `situacao` para admin, mas não há tela; e o usuário de um escritório suspenso que já está logado continua usando o painel (3.2).
- **Nosso**: `plano_minimo` é importado do catálogo e não tem efeito; deixar claro na tela do editor ("sem efeito até existir plano") para não enganar quem edita.
