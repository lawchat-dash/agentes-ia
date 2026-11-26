
# Plano de implementação: consumo, execuções, funções do cliente e dois apps

O plano tem 4 frentes. O pedido do usuário pede prioridade para a **frente C** (o que o cliente vê quando o token acaba, e pausar, ativar, editar prompt e criar agente gravando nas tabelas certas). Por isso a ordem recomendada é: **C0 → C1-C4 → A1-A3 → C5 → B → A4-A6 → D**. A frente D pode correr em paralelo a qualquer momento, mas o item D1 (fábrica de app) deve vir antes de mexer muito em `app/main.py`.

**Convenções**
- Cada item vira um PR pequeno. Um item só termina com `pytest` verde, sem chamada paga: tudo usa `AGENTESIA_MODELO_FALSO` ou o RepositorioMemoria.
- **[CONFLITO]** marca os itens que tocam `app/pipeline.py`, `app/canal/*` ou `app/cerebro/*`, que outro trabalho está editando agora. Esses itens só começam depois desse trabalho ser integrado, ou com rebase combinado. Sempre que der, a lógica nova fica num módulo separado (`app/consumo.py`, `app/execucoes.py`, `app/banco/postgres.py`) e o pipeline recebe só uma chamada de 1 a 3 linhas.
- Migrações novas: `db/migracoes/003_consumo_e_cliente.sql` (A e C), `004_execucoes.sql` (B), cada uma com seu `desfazer_00X.sql`. Todas aditivas (`add column if not exists`, `create index if not exists`), sem quebrar a 001 e a 002.

---

## Decisões de produto antes de codar (C0, bloqueia C5, A5 e parte de C1)

1. **Regra comercial do "token acabou"**: continua o teto mensal em US$ (`agentesia_escritorios.config.limite_consumo`) ou passa a valer saldo pré-pago (`sistemaia_saldos.pausado_por_saldo`, citado em MAPA_DO_SISTEMA.md:70 como "Novo")? O plano supõe que **o teto mensal continua sendo a fonte**, com o saldo como fonte opcional (C5).
2. **O que o cliente pode fazer com a IA parada**: só pedir aumento, que vira evento para a LawChat (recomendado para começar), ou liberar um "adicional do mês" até um teto definido pelo admin.
3. **Moeda mostrada ao cliente**: só US$ por enquanto, ou R$ com markup (A5)?
4. **Chave OpenAI própria do escritório**: vale ou sai da tela? Hoje é salva e mostrada como "ok", mas nunca usada (modelo.py:353-360, ativacao.py:189-191).
5. **Uma tela por tipo de agente**: agentes `produto='catalogo'` são editados só em Meus Produtos e ProdutoEditor, e a tela antiga `/agentes` fica só para `produto` diferente de `catalogo` (recomendado).

Saída esperada: uma seção "Decisões" no PLANO.md. Não há código nesta etapa.

---

## Frente C: funções do cliente (prioridade do usuário)

### C1. Uma função comum de "pode gastar?" e o bloqueio em todos os pontos que custam
- **Problema**: hoje só `_um_turno` confere o limite (pipeline.py:395). Follow-up, mídia, memória, resumos, origem, indexação e prévia continuam gastando com a IA "pausada".
- **Arquivos**:
  - `app/consumo.py`: novo `async def bloqueado(pool, id_escritorio) -> MotivoBloqueio | None`, que reaproveita o `ControleDeConsumo` com cache de 60 s, e `somar(id_escritorio, custo)` público.
  - `app/followup/servico.py`: em `_por_que_nao`, adiar com motivo `limite_de_consumo`, sem cancelar.
  - `app/acoes.py`: resumo de contrato e origem (623/649/676) adiam a ação ou a marcam como `falhou` com motivo.
  - `app/memoria.py:171`.
  - `app/conhecimento_indice.py:48`: não indexa e deixa o documento pendente.
  - `app/gestao/rotas.py:1539`: prévia de follow-up devolve 409 "limite atingido".
  - **[CONFLITO]** `app/pipeline.py`: `_ler_midia` (133-175) chama `consumo.bloqueado` antes de transcrever ou descrever (só baixa), e `_conferir_consumo` (656-675) passa a delegar para `consumo.bloqueado`.
- **Tabelas**: lê `agentesia_escritorios.config.limite_consumo` e soma `agentesia_chamadas_ia.custo_usd`. Grava `agentesia_followups` (adiado) e `agentesia_acoes`.
- **Testes**:
  - `tests/test_consumo.py`: `bloqueado` com limite estourado em `pausar` e em `so_avisar`, e sem limite;
  - `tests/test_followup.py`: follow-up adiado com limite estourado;
  - `tests/test_trava_cem_por_cento.py`: mídia não transcreve com limite estourado.
- **Depende de**: nada para a parte sem conflito. A parte do pipeline espera o outro trabalho.

### C2. Front do "token acabou" visível para todos os papéis
- **Arquivos**:
  - `app/gestao/metricas.py`: novo `GET /api/consumo/estado`, perfil TODOS, que devolve `{bloqueado, motivo, percentual, volta_em, pode_pedir_aumento}` **sem valores em US$** para quem não está em `PAPEIS_QUE_VEEM_CONSUMO`.
  - `painel/src/componentes/Estrutura.tsx`: banner global vermelho "A IA está parada: o limite do mês acabou. Volta em 01/MM ou quando o limite subir", com botão **Pedir aumento** (só gestor) e link "Ver conversas sem resposta".
  - `painel/src/telas/Conversas.tsx` e `components/conversas/PainelLateral.tsx`: chip "IA parada por limite" no cabeçalho da conversa.
  - `painel/src/components/dashboard/ConsumoCenter.tsx`: troca "fale com a equipe" (linha 114) pelo botão.
- **Tabelas**: só leitura de `agentesia_escritorios` e `agentesia_chamadas_ia`.
- **Testes**:
  - `tests/test_metricas.py`: atendente recebe `bloqueado` sem custo; gestor recebe com custo.
  - Painel: `npm run build` (tsc).
- **Depende de**: C1, para que o `bloqueado` venha da mesma função.

### C3. "Pedir aumento" e "religar" do cliente, gravando nas tabelas certas
- **Arquivos**:
  - `app/gestao/rotas.py`: `POST /api/consumo/pedir-aumento` (GESTAO) grava `agentesia_eventos` tipo `pedido_aumento_limite`, gravidade `aviso`, responsável `lawchat`, com `detalhe {percentual, gasto, limite, pedido_por}`, e `agentesia_alteracoes`. Dedup de 1 pedido a cada 6 h.
  - `app/central_avisos.py:61`: incluir no filtro `pedido_aumento_limite`, `limite_de_consumo` (de qualquer responsável) e `ia_sem_credito`, para que a LawChat seja alertada no WhatsApp.
  - `app/acoes.py:397-400` (aviso_consumo): sem aviso `consumo_limite` cadastrado, mandar para o responsável do escritório como padrão.
  - `app/gestao/rotas.py` (`PUT /admin/escritorios/{id}/limite`, 556-576): depois de subir o limite, **invalidar o cache** do ControleDeConsumo e marcar como resolvidos os eventos `limite_de_consumo` abertos.
  - Opcional, conforme a decisão C0.2: `POST /api/consumo/adicional`, para o gestor liberar um adicional até `config.limite_consumo.teto_adicional_usd` definido pelo admin.
- **Tabelas**: `agentesia_eventos`, `agentesia_alteracoes`, `agentesia_escritorios.config.limite_consumo` (campo novo `adicional_mes_usd` e `teto_adicional_usd`, só em jsonb, sem migração).
- **Lista "leads sem resposta por limite"**: `GET /api/consumo/leads-parados`, com `agentesia_turnos` em `situacao='silencio' and motivo='limite_de_consumo'` desde o bloqueio, agrupados por `id_lead`. O botão "Responder agora" fica disponível depois que a IA volta (usa B6).
- **Testes**:
  - `tests/test_gestao.py`: pedir aumento grava evento e alteração, com dedup;
  - `tests/test_central_avisos.py`: `limite_de_consumo` de responsável cliente gera `alertar_lawchat`;
  - `tests/test_consumo.py`: subir o limite libera na hora (cache invalidado).
- **Depende de**: C1 e C2.

### C4. Pausar e ativar agente com o mesmo resultado nas duas telas
- **Problemas**:
  - `POST /produtos-ativados/{id}/status` liga o agente sem `_preparar` e aceita produto sem `id_agente`.
  - `/agentes/{id}/ativacao` não atualiza `agentesia_produtos_ativados.status`.
  - `_montar_agente` grava `situacao='ativo'` antes da preparação.
- **Arquivos**:
  - `app/gestao/ativacao.py` (ou um módulo novo `app/gestao/agente_estado.py`): função única `async def mudar_situacao(conn, ctx, id_agente, nova, motivo)`, que:
    1. ao ligar, roda `preparar` e só liga se `resultado.pronto`; se não estiver pronto, devolve 409 com as pendências;
    2. grava `agentesia_agentes.situacao` e `modo`;
    3. se houver `id_produto_ativado`, grava `agentesia_produtos_ativados.status` e `status_provisionamento`;
    4. grava `agentesia_alteracoes` com antes e depois.
  - `app/gestao/rotas.py:1335-1374` e `app/gestao/produtos.py:722-731` passam a chamar essa função. Em `mudar_status`, responder 409 quando não houver `id_agente`.
  - `app/gestao/produtos.py` `_montar_agente` (598-686): insert com `situacao='pausado'` e ligar só se `verificacao.pronto`; se não estiver pronto, `status_provisionamento='falhou'` com a lista de pendências.
  - `painel/src/components/agent/ProductConfigurator.tsx:1101-1110`: ler `verificacao.pronto` e mostrar os passos com erro, em vez do "pronto!" fixo.
  - `painel/src/pages/MeusProdutos.tsx`: botão Ativar mostra as pendências do 409.
  - Banner "Agente pausado" no `Estrutura.tsx` quando todos os agentes do escritório estiverem pausados, ou `ia_desligada`.
- **Tabelas**: `agentesia_agentes.situacao` e `.modo`, `agentesia_produtos_ativados.status` e `.status_provisionamento`, `agentesia_alteracoes`.
- **Testes**: `tests/test_gestao.py` e `tests/test_produto_livre.py`.
  - Pausar pelo catálogo reflete em `/agentes`, e o contrário também.
  - Ativar com a preparação falhando não liga e devolve 409.
  - Status `ativo` em rascunho sem agente devolve 409.
  - Toda mudança gera alteração.
- **Depende de**: C0.5.

### C5. Pausar e devolver um LEAD pelo painel com o mesmo efeito da Helena
- **Arquivos**:
  - `app/gestao/rotas.py:1852-1864` (`acao_na_conversa`) passa a usar `app/ia_controle.mudar_ia`, ou uma função comum extraída dele, com:
    - motivo `desativada_pela_equipe`;
    - nota DES e etiqueta em `agentesia_acoes`;
    - cancelamento de `agentesia_followups`.
  - Ao devolver, remover a etiqueta e, se houver mensagem do lead sem resposta, gravar `responder_apos=now()`, que o laço `retomar_esperas` já pega.
  - `app/ia_controle.py:46`: incluir `pausado_pela_equipe` em `religaveis` (compatibilidade com dados antigos).
- **Tabelas**: `agentesia_leads.estado`, `.motivo_estado` e `.responder_apos`, `agentesia_acoes`, `agentesia_followups`, `agentesia_alteracoes`.
- **Testes** (`tests/test_ia_controle.py` e `tests/test_conversas_tela.py`):
  - pausar pelo painel enfileira nota e etiqueta e cancela follow-up;
  - devolver remove a etiqueta e agenda resposta;
  - uma etiqueta posterior não repausa.
- **Depende de**: nada. Não mexe no pipeline: usa `responder_apos`, que já existe.

### C6. Editar prompt: trava, histórico e "voltar versão"
- **Arquivos**:
  - `app/gestao/produtos.py` (sincronizar, 646-669):
    - no upsert de `agentesia_agente_etapas`, manter `instrucao` quando `instrucao_travada=true` e o papel não for admin;
    - gravar **antes e depois por etapa** em `agentesia_alteracoes`;
    - mesclar `config.funcoes` e `config.modelos` (`{**antigo, **novo}`) em vez de substituir (hoje apaga crm, avisos e transferir_humano);
    - só rodar `_preparar` se mudou canal ou integração.
  - `app/gestao/rotas.py:1264-1287` (tela antiga): para `produto='catalogo'`, nunca gravar `instrucao=null` por igualdade ao padrão (evita etapa `sem_prompt`).
  - `painel/src/pages/ProdutoEditor.tsx`: aba "Histórico do prompt" (lista `agentesia_alteracoes` da entidade e etapa) e botão "Voltar a esta versão", que faz um novo sincronizar só daquela etapa.
  - `painel/src/telas/Agentes.tsx` e `Agente.tsx`: agente `catalogo` redireciona para `/meus-produtos/{id_produto_ativado}` (decisão C0.5).
- **Tabelas**: `agentesia_agente_etapas.instrucao` e `.instrucao_travada`, `agentesia_agentes.config.funcoes` e `.modelos`, `agentesia_alteracoes`. Não é preciso tabela nova de versões: o antes e depois em alterações basta. Se o volume crescer, criar `agentesia_agente_etapas_versoes` depois.
- **Testes** (`tests/test_produto_livre.py` e `tests/test_catalogo.py`):
  - o sincronizar não sobrescreve etapa travada;
  - o sincronizar preserva `funcoes.crm`;
  - a alteração tem antes e depois;
  - a tela antiga não anula instrução de agente do catálogo.
- **Depende de**: C0.5.

### C7. Criar agente pela biblioteca preenchendo tudo que o motor usa
- **Arquivos**: `app/gestao/produtos.py` (`_config_do_agente` 574-596 e `_montar_agente`):
  - `funcoes` padrão `{crm, avisos, transferir_humano, contrato_zapsign, buscar_cep}` vindas do catálogo, ou de um padrão;
  - copiar `agentesia_biblioteca_produtos.padrao_followup` para `config.followup` **só se ainda não existir**;
  - copiar as automações padrão (como faz `POST /agentes` com modelo, rotas.py:1172-1176);
  - gravar `config.catalogo.nome`;
  - usar `modelo_recomendado` quando o painel não mandar modelo;
  - completar boas-vindas, mensagem_troca e destinos a partir de `agentesia_biblioteca_agentes.regras_handoff`, quando faltarem no payload.
- No painel, `ProductConfigurator.tsx` mostra no resumo final "Follow-up: ligado | CRM: ligado | Avisos: ligado".
- **Tabelas**: `agentesia_agentes.config.funcoes`, `.followup`, `.automacoes` e `.catalogo`; lê `agentesia_biblioteca_produtos` e `agentesia_biblioteca_agentes`.
- **Fica fora** (decidir depois, porque toca o cérebro **[CONFLITO]**): `modo_midia`, `mensagem_fallback`, `mensagem_despedida` e temperatura por etapa (`app/cerebro/*`, `app/pipeline.py:775`).
- **Testes**: `tests/test_catalogo.py` e `tests/test_produto_livre.py`.
  - O agente ativado tem `config.followup.ativo`, `funcoes.crm` e `catalogo.nome`.
  - Reativar não sobrescreve um follow-up já editado.
- **Depende de**: C4 (mesma função `_montar_agente`) e C6 (mescla de `funcoes`).

### C8. Arestas de exclusão
- `app/gestao/produtos.py`:
  - `excluir_produto` (734-748) com leads ativos deixa o produto na lixeira em vez de apagar, para não deixar agente órfão segurando `id_canal`;
  - `DELETE /midia/{id}` (848-857) bloqueia quando a URL aparece em `agentesia_agente_etapas.instrucao`, e lista os agentes.
- **Testes**: `tests/test_produto_livre.py`.
- **Depende de**: C4.

### C9 (opcional, conforme C0.1). Saldo pré-pago como fonte do bloqueio
- `app/consumo.py`: `bloqueado` também lê `sistemaia_saldos.pausado_por_saldo`, ou uma nova `agentesia_saldos`.
- Banner com "recarregar".
- **Depende de**: C0.1 e C1.

---

## Frente A: custo de tokens por mensagem e por etapa no painel

### A1. Migração 003: colunas de atribuição e índices em `agentesia_chamadas_ia`
- **Arquivo**: `db/migracoes/003_consumo_e_cliente.sql` e `desfazer_003.sql`.
- **Colunas**:
  - `tokens_cache int default 0` e `tokens_cache_escrita int default 0`;
  - `id_lead uuid`, `id_agente uuid` e `codigo_etapa text`;
  - `id_mensagem uuid null` e `ordem smallint`;
  - `origem text default 'producao'` (producao, teste, laboratorio ou previa).
- **Índices**: `(id_escritorio, criado_em)`, `(id_turno)` e `(id_lead)`.
- **Views**: `agentesia_v_custo_dia` (escritório, dia, papel, modelo) e `agentesia_v_custo_turno` (id_turno, soma de tokens e custo, número de chamadas).
- **Testes**: aplicar a migração num banco de teste (o `tests/test_postgres.py` já tem fixture?). Se não houver, conferir a sintaxe com `psql --dry` manual.
- **Depende de**: nada.

### A2. Gravação única de chamadas
- **Arquivos**:
  - `app/banco/postgres.py:467-475`: `gravar_chamadas(chamadas, *, id_escritorio, id_turno=None, id_lead=None, id_agente=None, codigo_etapa=None, origem='producao')`, gravando entrada, cache e saída **separados** (hoje soma entrada + cache, na linha 474).
  - Usar essa função em `app/acoes.py:700-705`, `app/followup/servico.py:293-298` e `app/conhecimento_indice.py:46-50`. Esses pontos hoje perdem o cache e não têm `id_lead`.
  - Somar no `ControleDeConsumo` em todos esses pontos (fecha a lacuna junto com C1).
  - **[CONFLITO]** `app/pipeline.py:175` e `:415`: passar `id_lead`, `id_agente`, `codigo_etapa` e `id_turno` (também nas chamadas de mídia).
- **Testes**: `tests/test_postgres.py` (colunas preenchidas) e `tests/test_followup.py` (chamada de follow-up gravada com `id_lead` e cache).
- **Depende de**: A1.

### A3. Medir o que hoje sai como zero
- **Arquivos**:
  - `app/modelo.py`:
    - ler `cache_creation_input_tokens` (Anthropic, 193-197) e cobrar 1,25x o preço da entrada;
    - cadastrar `gpt-4o-mini-transcribe` e o modelo de embedding em `PRECOS_USD_POR_MILHAO`;
    - para modelo sem preço, fazer `calcular_custo` devolver um marcador `sem_preco` e quem grava criar o evento `modelo_sem_preco`.
  - `app/midia/openai_visao.py:45-58`: transcrição preenche tokens e custo (pelo usage, ou pela duração vezes o preço por minuto).
  - **[CONFLITO]** `app/pipeline.py:736`: gravar o embedding da consulta com papel `busca_conhecimento` e `id_turno`.
- **Testes**: `tests/test_modelo.py`, com respostas falsas contendo usage de cache de escrita e modelo sem preço, e `tests/test_midia.py`.
- **Depende de**: A2.

### A4. API de consumo detalhado
- **Arquivos**:
  - `app/gestao/rotas.py:579-594` e `app/gestao/repositorio.py:177-188`: `GET /api/consumo?de=&ate=&agente=&agrupar=dia|papel|etapa|agente|lead|modelo&origem=`.
  - `GET /api/admin/consumo`, com os mesmos filtros e mais `escritorio`.
  - `app/gestao/metricas.py`: aceitar `de` e `ate` além de `dias`, e **omitir `custo_usd`** para quem não está em `PAPEIS_QUE_VEEM_CONSUMO` (lacuna de privacidade, linhas 53, 80-101).
  - `app/gestao/repositorio.py:498-500`: `/conversas/{id}` passa a trazer o custo por turno (join com `agentesia_v_custo_turno`).
- **Testes**: `tests/test_metricas.py` (agrupamentos, período e ocultação para atendente) e `tests/test_conversas_tela.py` (custo por turno).
- **Depende de**: A1 e A2. Dados antigos sem `id_lead` caem no join via `id_turno`.

### A5. Telas
- **Arquivos**:
  - nova `painel/src/telas/Consumo.tsx`: filtro de período, gráfico por dia, tabela por papel, etapa, agente e modelo, custo médio por mensagem da IA e por lead, e os 10 leads mais caros;
  - rota e menu em `painel/src/main.tsx`;
  - `Inicio.tsx`: trocar `DIAS=30` fixo por um seletor e esconder o custo do atendente;
  - `ConsumoCenter.tsx`: link para Consumo;
  - `components/conversas/PainelLateral.tsx`: custo e tokens por turno na aba Turnos;
  - `AdminEscritorios.tsx`: link para o consumo do escritório.
- **R$ e markup** (se C0.3 decidir): `config.cobranca {markup, cotacao_fixa}` no escritório; conversão na consulta; cliente vê R$ cobrado e admin vê US$ real.
- **Testes**: `npm run build`; conferência manual no navegador com dados de seed.
- **Depende de**: A4.

### A6. Laboratório e prévia com registro
- **Arquivos**: `app/gestao/laboratorio.py` (11, 57-59) e `app/gestao/rotas.py:1539`. As chamadas vão para `agentesia_chamadas_ia` com `origem='laboratorio'` ou `'previa'`, entram no limite e podem ser filtradas na tela Consumo.
- **Testes**: `tests/test_gestao.py`.
- **Depende de**: A2 e C1.

---

## Frente B: Execuções e alertas de erro (visibilidade como no n8n)

### B1. Migração 004 e fechamento seguro do turno
- `db/migracoes/004_execucoes.sql`:
  - `agentesia_turnos`: `id_agente`, `hash_prompt`, `duracao_ms` e `erro jsonb`;
  - `agentesia_eventos_recebidos`: `id_lead` e `id_turno`;
  - índices `agentesia_turnos(id_escritorio, iniciado_em desc)` e `(situacao)`, `agentesia_eventos(id_turno)` e `agentesia_acoes(id_turno)`.
- **[CONFLITO]** `app/pipeline.py` (`_um_turno`, 318-324, 389, 828-834): `try/except` depois de `abrir_turno`, fechando com `situacao='erro'`, `motivo='excecao:<Classe>'` e `erro={classe, msg, stack <= 4 KB}`. O evento `erro_no_turno` ganha `id_turno`.
- `app/banco/postgres.py`: `fechar_turno` aceita `erro`, `id_agente`, `hash_prompt` e `duracao_ms`. Novo `varrer_turnos_presos()` fecha como `erro` os turnos `processando` há mais de 10 min.
- `app/main.py`: laço do varredor a cada 5 min.
- `app/central_avisos.py:57`: trocar o join interno por left join, para não perder evento sem escritório.
- **Testes**: `tests/test_pipeline.py` (exceção fecha o turno como erro com `id_turno` no evento) e `tests/test_postgres.py` (varredor).
- **Depende de**: nada. Pode ser feito junto com A1.

### B2. API de execuções
- `app/gestao/repositorio.py` e `app/gestao/rotas.py` (ou um novo `app/gestao/execucoes.py`, para não inchar `rotas.py`):
  - `GET /api/execucoes`: lista leve, sem `contexto`. Filtros: agente, lead ou telefone, situação, só erro ou reprovação, período e modo. Paginação por cursor `(iniciado_em, id)`. Custo vindo de `agentesia_v_custo_turno`.
  - `GET /api/execucoes/{id}` (GESTAO): turno com `contexto`, mais as mensagens de entrada e de saída, as chamadas de IA, as ações e os eventos daquele `id_turno`. Mascarar CPF e telefone no que é exibido.
  - `/api/admin/execucoes` com filtro de escritório.
- **Testes**: um `tests/test_execucoes.py` novo (filtros, paginação, permissão do atendente, que não vê o prompt).
- **Depende de**: B1. O custo vem de A1, mas a tela funciona sem.

### B3. Tela Execuções
- `painel/src/telas/Execucoes.tsx` (novo) e rotas `/execucoes` e `/admin/execucoes` em `main.tsx`.
- **Lista**: quando, lead (com link), agente, etapa antes → depois, chip de situação, `motivoLegivel` (de `components/conversas/tipos.ts`), duração, número de chamadas, custo e ícones (trava, ferramenta, envio falhou).
- **Detalhe em gaveta**, com linha do tempo: Entrada → Conferência → Extrator → Etapa (prompt recolhível, tentativas e reprovações) → Auditor → Catálogo e ferramenta → Chamadas de IA → Envio à Helena → Ações → Eventos.
- Link "Ver execução" no `PainelLateral.tsx` (aba Turnos).
- **Testes**: `npm run build` e conferência manual.
- **Depende de**: B2.

### B4. Tela Erros com filtros no servidor e agrupamento
- `app/gestao/repositorio.py:440-447` e `rotas.py:1820`:
  - filtros de tipo, gravidade, responsável, lead, agente e período;
  - `agrupar=1`, com contagem e primeira e última ocorrência por tipo + lead;
  - `POST /eventos/resolver-lote`.
- `painel/src/telas/Erros.tsx`: links "Ver execução" (`id_turno`) e "Ver conversa" (`id_lead`), e agrupamento. Eventos repetidos como `limite_de_consumo` e `agente_pausado` viram uma linha só.
- **Testes**: `tests/test_gestao.py`.
- **Depende de**: nada; melhora com B3.

### B5. Alertas
- Painel:
  - contador de erros abertos no menu (`Estrutura.tsx`, reaproveitando `resumo.erros_abertos`);
  - faixa crítica (compartilha o componente de banner com C2).
- `app/notificacoes.py:17` e `painel/src/telas/Avisos.tsx`: gatilhos de erro selecionáveis pelo escritório (`ia_nao_respondeu`, `envio_falhou`, `limite_de_consumo` e `acao_falhou_*`) com dedup por janela.
- `app/central_avisos.py` e `app/main.py:126`: persistir o cursor (usar `max(criado_em)` dos `alertar_lawchat` já enfileirados) em vez de guardá-lo em memória.
- E-mail via SMTP ou Resend: opcional e posterior.
- **Testes**: `tests/test_central_avisos.py` e `tests/test_avisos_link_e_painel.py`.
- **Depende de**: C3 (filtro da central) e B4.

### B6. Reprocessar e "testar de novo"
- `POST /api/execucoes/{id}/reprocessar` (GESTAO): só se a última mensagem for do lead e o lead estiver ativo. Marca as mensagens como pendentes e chama `atendimento.processar(id_lead)`. Grava `agentesia_alteracoes` e `contexto.reprocessado_de`.
- Variante `modo='laboratorio'` ("testar com o prompt atual sem enviar"), ligando com C6.
- Botão na Execução e na lista "leads parados por limite" (C3).
- **[CONFLITO]** `app/pipeline.py` (`processar` e o modo laboratório, 332-345).
- **Testes**: `tests/test_pipeline.py` e `tests/test_execucoes.py`.
- **Depende de**: B2 e C3.

### B7. Retenção
- Laço diário em `app/main.py` (no app IA, depois de D1):
  - anula o `contexto` vencido: 30 dias em produção, 7 dias para silêncio e descartado, 90 dias para erro;
  - anula o payload de `agentesia_eventos_recebidos` com mais de 7 dias.
- **[CONFLITO]** `app/pipeline.py:69-80`: gravar `situacao` e `motivo` do webhook ignorado com payload mínimo.
- Tabela de prompts por hash (`agentesia_prompts_montados`) fica para depois.
- **Testes**: `tests/test_postgres.py`.
- **Depende de**: B1 e D1.

---

## Frente D: dois apps no Easypanel

### D1. Fábrica de app
- `app/servidor.py` (novo), com `criar_app(papel: 'ia'|'painel'|'tudo')`, reaproveitando o `_ciclo` de `app/main.py:68-165`.
- `app/main.py` vira `app = criar_app('tudo')`, para o desenvolvimento local e os testes continuarem iguais.
- `app/main_ia.py`: pool, Atendimento, Executor, Disparador, retomar_esperas, central_de_avisos, indexar_conhecimento e varredor (B1); rotas `/webhook/*`, `/saude` e `/midia` (se a mídia ficar aqui).
- `app/main_painel.py`: pool, RepositorioGestao, Assinador e Laboratorios; routers `/api/*` e `/entrar/helena`, `/midia`, `/saude` e o catch-all do `painel/dist`. **Sem laços de fundo**.
- **Testes**: um `tests/test_servidor.py` novo, que confere quais rotas e tarefas cada papel monta, sem banco.
- **Depende de**: nada. Mexe só em `main.py`, não no pipeline.

### D2. Desacoplar o que hoje depende de estar no mesmo processo
- `app.state.indexar_agora` (rotas.py:519/534, produtos.py:693-696): o painel só marca o documento como pendente no banco, e o laço do app IA (que já roda a cada 30 s) pega. Se quiser rapidez, usar `NOTIFY/LISTEN` do Postgres.
- `app.state.laboratorios`: continua no painel (laboratório e prévia rodam no processo do painel e gravam com `origem` diferente, item A6). Isso exige `OPENAI_API_KEY` também no painel; documentar.
- `/lab` antigo: **não montar no app IA**. No painel, remover, ou exigir `AGENTESIA_LAB_SENHA` e falhar ao subir em produção sem ela.
- **Testes**: `tests/test_conhecimento.py` (indexação por pendência).
- **Depende de**: D1.

### D3. URLs e mídia
- Separar `AGENTESIA_URL_PUBLICA` (base do webhook, `app/canal/webhook.py:26` **[CONFLITO]**, e `ativacao.py:69-76/138`) de `AGENTESIA_URL_MIDIA` (`produtos.py:783`), com fallback para a primeira, para não quebrar o que existe.
- Mídia (`AGENTESIA_PASTA_MIDIA`, `produtos.py:778`): a mídia é escrita pelo painel e lida pelo cérebro e pela Helena. Opções:
  - (a) volume compartilhado no Easypanel montado nos dois apps;
  - (b) servir `/midia` só pelo painel, e a IA usa a URL pública;
  - (c) Supabase Storage (recomendado a médio prazo).
- A ativação (`ativacao.py`) faz POST de teste na URL da IA: funciona entre apps porque usa a URL pública.
- **Depende de**: D1. A parte de `app/canal/webhook.py` espera o outro trabalho.

### D4. Artefatos de deploy
- `Dockerfile.ia`: python:3.12-slim, `requirements.txt` (separar `pytest` em `requirements-dev.txt`), `uvicorn app.main_ia:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=*`.
- `Dockerfile.painel`: multi-stage, com node:20 (`cd painel && npm ci && npm run build`) e depois python:3.12-slim com `app/` e `painel/dist`, rodando `uvicorn app.main_painel:app ...`.
- `.dockerignore`: excluir `chats_reais*`, `.env`, `painel/node_modules`, `avaliacao/` e `tests/dados`.
- Atualizar `LEIA-ME.md` e `docs/ESTADO.md`: dois serviços App no Easypanel, mesmo repositório, build path por Dockerfile, domínios `ia.` e `painel.`, e a lista de variáveis por app. Pool de conexões menor no painel.
- **Testes**: `docker build` local dos dois arquivos, `/saude` respondendo e o painel abrindo pelo iframe da Helena (cookie SameSite=None, já tratado em rotas.py:232-237).
- **Depende de**: D1, D2 e D3.

---

## Mapa de dependências e de conflitos

| Item | Depende de | Toca arquivos em edição? |
|---|---|---|
| C1 | C0 | **Sim** (pipeline: `_ler_midia` e `_conferir_consumo`); o resto não |
| C2, C3 | C1 | Não |
| C4 | C0.5 | Não |
| C5 | nada | Não |
| C6 | C0.5 | Não |
| C7 | C4, C6 | Não (os extras de cérebro ficam fora e são **[CONFLITO]**) |
| C8 | C4 | Não |
| A1 | nada | Não |
| A2 | A1 | **Sim** (pipeline:175/415); acoes, followup e índice não |
| A3 | A2 | **Sim** (pipeline:736); modelo e openai_visao não |
| A4, A5 | A1, A2 | Não |
| A6 | A2, C1 | Não |
| B1 | nada | **Sim** (pipeline: try/except do turno) |
| B2, B3, B4 | B1 | Não |
| B5 | C3, B4 | Não |
| B6 | B2, C3 | **Sim** (pipeline: processar e laboratório) |
| B7 | B1, D1 | **Sim** (pipeline: webhook ignorado) |
| D1, D2, D4 | — | Não |
| D3 | D1 | **Sim** (`app/canal/webhook.py`) |

**O que dá para começar já, sem esperar o outro trabalho**:
- C5, C4, C6, C2 (com `consumo.bloqueado` já criado);
- a parte de C1 fora do pipeline;
- A1, a parte de A2 fora do pipeline, A4;
- B2 a B4 (sobre os dados que já existem), D1, D2.

**Esperam a integração** com quem edita `app/pipeline.py`, `app/canal/*` e `app/cerebro/*`:
- os ganchos de pipeline de C1, A2, A3, B1, B6 e B7;
- a base de webhook de D3;
- os extras de cérebro de C7.
