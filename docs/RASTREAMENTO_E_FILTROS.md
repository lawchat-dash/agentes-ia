# Rastreamento das conversas e filtros

25/11/2026. Proposta, sem código alterado. Lido: `app/origem.py`, `app/canal/helena.py`, `app/canal/webhook.py`,
`app/canal/filtro.py`, `app/pipeline.py` (só leitura), `app/consumo.py`, `app/horario.py`, `app/acoes.py`,
`app/gestao/metricas.py`, `app/gestao/repositorio.py`, `app/gestao/rotas.py`, `db/migracoes/001..003`,
`docs/HELENA_API.md`, `docs/WEAVER_PARA_CODIGO.md` e as telas `Inicio`, `Conversas`, `Funil`, `Erros` do painel.

## Resumo em cinco linhas

1. **A base já existe.** Hoje gravamos de onde o lead veio (primeiro toque), cada mensagem com autor (lead, IA, humano), cada turno com a etapa antes e depois, o custo de cada chamada de IA, os contratos e os problemas.
2. **Falta a linha do tempo.** O lead guarda só a situação de *agora*. Quando ele muda de etapa, é pausado ou volta, o valor antigo é sobrescrito. Sem esse histórico não dá para medir "quanto tempo da entrada até assinar" nem "em que etapa perdemos".
3. **Falta ligar custo ao lead.** Parte do gasto de IA (leitura de áudio e imagem, classificação do anúncio, resumo) fica gravada sem o lead. Então "custo por contrato" sai errado para baixo.
4. **Os filtros do painel são poucos e cada tela tem os seus.** A proposta é um filtro único, igual em todas as telas, que vai no endereço da página (dá para mandar o link) e depois pode ser salvo.
5. **Na entrada, o motor já barra o principal**, mas gasta token antes de saber se vai atender: lê áudio e imagem de lead pausado, em modo teste ou de escritório sem saldo. É o conserto mais barato com mais retorno.

---

## Parte 1. Rastreamento

### 1.1 O que já registramos hoje

| O que | Onde fica | Situação |
|---|---|---|
| Origem do lead: link do anúncio, `ctwa_clid`, fonte, meio, campanha, conteúdo, título, termo, id do anúncio | `agentesia_leads.origem` (jsonb), lido do evento TRACK da Helena em `app/origem.py` | **Existe.** Só o primeiro toque: se o mesmo lead voltar por outro anúncio, o segundo não é guardado |
| Benefício que o anúncio oferece (BPC, auxílio-acidente...) e confiança | `agentesia_leads.origem.produto` / `.confianca`, feito pela fila (`acoes.py`, `_classificar_origem`) | **Existe** |
| Quando o lead chegou | `agentesia_leads.criado_em` | **Existe** |
| Primeira mensagem do lead | `agentesia_mensagens` (a mais antiga com `autor = 'lead'`) | **Dá para calcular**, mas não fica pronta no lead |
| Tempo da primeira resposta | Calculado na hora em `metricas.py` (média entre a primeira mensagem do lead e a primeira da IA) | **Parcial**: usa média (um lead que esperou a noite toda distorce tudo), ignora resposta humana e é lento com muitos leads |
| Etapa atual | `agentesia_leads.id_etapa` | **Existe** |
| Troca de etapa feita pela IA | `agentesia_turnos.etapa_antes` / `etapa_depois` | **Parcial**: só a troca feita num turno da IA. Mudança feita pela equipe ou pelo CRM não aparece |
| Situação da IA no lead (ativa, pausada, encerrada) e motivo | `agentesia_leads.estado` / `motivo_estado` (`humano_assumiu`, `desativada_pela_equipe`, `sinal:...`, `desqualificado:...`, `sem_resposta_followup`...) | **Existe só o valor atual.** O anterior é apagado na próxima mudança |
| Motivo de desqualificação | Dentro de `motivo_estado`, como texto `desqualificado:<motivo>` | **Parcial**: some se o lead for reativado; não há lista fechada de motivos |
| Sinais (não sabe ler, quer videochamada, cliente antigo...) | `agentesia_turnos.resposta` (jsonb) e `motivo_estado = 'sinal:...'` quando pausa | **Parcial**: só no produto Auxílio-Acidente; difícil de contar |
| Contrato gerado e assinado | `agentesia_contratos` (`gerado_em`, `lead_assinou_em`, `assinado_em`, `concluido_em`, versões) | **Existe e está bom** |
| Custo de tokens | `agentesia_chamadas_ia` (modelo, tokens, custo, `id_turno`) | **Parcial**: não tem a coluna do lead. Chamadas fora do turno (leitura de mídia em `pipeline.py`, classificação de anúncio e resumo em `acoes.py`) ficam com `id_turno` vazio e não se ligam a ninguém |
| Quem respondeu cada mensagem | `agentesia_mensagens.autor` (`ia`, `humano`, `automacao`) | **Existe**, mas não diz *qual* atendente |
| Follow-up enviado e respondido | `agentesia_followups` | **Existe** |
| Problemas | `agentesia_eventos` | **Existe** |
| Ações da equipe no painel | `agentesia_alteracoes` | **Existe** |
| Mensagens descartadas na porta (grupo, reação, vazia) | Lugar nenhum | **Não existe**: não sabemos quanto o filtro barra |

### 1.2 O que falta

| Falta | Por que importa |
|---|---|
| **Linha do tempo do lead** (cada troca de etapa e de situação, com data, motivo e quem fez) | Base de quase todos os indicadores: tempo em cada etapa, onde o lead parou, quantos voltaram depois da pausa |
| **Marcos prontos no lead** (primeira mensagem, primeira resposta, quem respondeu primeiro, qualificado em, contrato gerado em, assinado em, perdido em) | Filtro e métrica rápidos, sem varrer milhões de mensagens |
| **Motivo de perda padronizado** | Hoje é texto livre. Para ranking de motivos precisa de uma lista fechada (ver 1.5) |
| **Lead em cada chamada de IA** | Custo por lead, por campanha e por contrato |
| **Cada toque de origem**, não só o primeiro | Lead que volta por outro anúncio meses depois. O primeiro toque continua valendo para o funil |
| **Conjunto de anúncios e criativo** | O TRACK traz o id do anúncio e o título, mas não o nome do conjunto. Precisa de uma tabela de anúncios (ver 1.3) |
| **Gasto com anúncio** | Sem ele não existe "custo por lead" de verdade, só o custo de IA |
| **Qual atendente humano falou** | "Atendido por IA, humano ou os dois", e por qual pessoa |
| **Contagem do que a porta barrou** | Saber se o filtro está barrando demais ou de menos |

### 1.3 Proposta de banco: migração `004_agentesia_rastreamento.sql`

Tudo aditivo (só colunas e tabelas novas), com o `desfazer_004.sql` correspondente e teste em `db/testes/teste_migracoes.mjs`, como as anteriores.

**a) Linha do tempo: tabela nova `agentesia_lead_historico`**

| Coluna | Conteúdo |
|---|---|
| `id`, `id_escritorio`, `id_lead` | |
| `tipo` | `etapa`, `estado`, `origem`, `sinal`, `contrato`, `atendente` |
| `de`, `para` | Valor antigo e novo (ex.: `sdr` → `closer`; `ativo` → `pausado`) |
| `motivo` | `humano_assumiu`, `desqualificado:sem_qualidade_de_segurado`, `sinal:nao_sabe_ler`... |
| `autor` | `ia`, `equipe`, `helena` (etiqueta ou CRM), `sistema` (follow-up, rajada, limite) |
| `id_turno`, `id_usuario` | Quando houver |
| `criado_em` | |

Como preencher: um **gatilho no próprio banco** em `agentesia_leads`, que grava uma linha sempre que `id_etapa`, `estado` ou `motivo_estado` mudarem. Vantagem: pega todos os caminhos (turno da IA, botão do painel, etiqueta da Helena em `ia_controle.py`, desistência do follow-up, rajada) sem mexer em `pipeline.py`, que outra frente está editando. O `autor` sai de uma variável de sessão (`set local agentesia.autor = 'equipe'`) que cada caminho põe antes do update; sem ela, fica `sistema`. Sinais e contrato entram por insert direto nos pontos onde já são gravados.

Preencher o passado uma vez: a partir de `agentesia_turnos` (etapa antes e depois) e de `agentesia_contratos`.

**b) Marcos no lead: colunas novas em `agentesia_leads`**

| Coluna | Preenchida quando |
|---|---|
| `primeira_mensagem_em`, `primeira_mensagem` (até 300 caracteres) | Primeira mensagem do lead gravada |
| `primeira_resposta_em`, `primeira_resposta_por` (`ia`/`humano`) | Primeira mensagem de IA ou humano depois da do lead |
| `qualificado_em` | Lead entra no `closer` (ou etapa marcada como "qualificado" no produto) |
| `perdido_em`, `motivo_perda` (código da lista fechada) | Desqualificado, desistência do follow-up, pediu para parar, engano |
| `contrato_gerado_em`, `contrato_assinado_em` | Espelho de `agentesia_contratos`, para filtrar sem join |
| `atendido_por` | `so_ia`, `so_humano`, `ia_e_humano` (recalculado quando um humano fala) |
| `ultima_origem` (jsonb) | Último toque, se diferente do primeiro |

Os mesmos gatilhos de (a) mantêm essas colunas, então elas nunca divergem do histórico.

**c) Custo por lead: `agentesia_chamadas_ia.id_lead`**

Coluna nova, com índice `(id_escritorio, id_lead)`. Passado: copiar de `agentesia_turnos.id_lead` pelo `id_turno`. Daqui para frente, `gravar_chamadas` (`app/banco/postgres.py`) e `_gravar_chamadas` (`app/acoes.py`) passam o lead. Hoje a leitura de mídia grava com `id_turno=None` (`pipeline.py`, perto da linha 175) e as ações da fila também; com `id_lead` elas passam a contar.

**d) Toques de origem: tabela nova `agentesia_lead_toques`**

Uma linha por TRACK ou UTM recebido (`id_lead`, `origem` jsonb, `chave_anuncio`, `recebido_em`). `agentesia_leads.origem` segue como primeiro toque (o funil conta por ele) e `ultima_origem` mostra o mais recente.

**e) Anúncios: tabela nova `agentesia_anuncios`**

`id_escritorio`, `id_anuncio` (o `sourceId` do TRACK), `chave_anuncio` (já calculada em `origem.py`), `campanha`, `conjunto`, `criativo`, `titulo`, `url`, `produto`, `primeiro_lead_em`. Preenchida sozinha a cada TRACK novo. Para o **conjunto** há dois caminhos:

1. **Agora, sem integração:** combinar com quem sobe as campanhas uma regra de nomes (ex.: UTM `campaign={{campaign.name}}`, `medium={{adset.name}}`, `content={{ad.name}}` nos anúncios com link). Em anúncio de clique para WhatsApp, a Meta só manda o id do anúncio, o título e o link; o nome do conjunto não vem.
2. **Depois:** buscar campanha, conjunto e criativo pelo id do anúncio na API de Marketing da Meta. Exige conectar a conta de anúncios do escritório, que é decisão de produto.

**f) Gasto com anúncio: tabela nova `agentesia_gasto_anuncios`**

`id_escritorio`, `dia`, `campanha` (ou `id_anuncio`), `valor_brl`, `fonte` (`manual`, `planilha`, `meta`). Primeira versão: o escritório cola uma planilha (data, campanha, valor) no painel. Sem isso, a tela mostra só o custo de IA e deixa claro que não é o custo do anúncio.

**g) Atendente humano: colunas em `agentesia_mensagens`**

`id_atendente_helena` e `nome_atendente`, quando o webhook trouxer (hoje o código já tira o `*Nome:*` do começo do texto em `helena.py`, então o nome está disponível). Confirmar no primeiro webhook real se vem também o id do usuário.

**h) Uma visão para o painel: `agentesia_v_leads`**

Uma linha por lead com tudo que os filtros e as métricas usam: escritório, agente, canal, etapa atual, situação de atendimento (ver 2.1), campanha, conjunto, produto do anúncio, marcos, motivo de perda, contrato, sinais, custo de IA somado, última mensagem. Todas as telas leem dela; o filtro vira só um `where`.

**Índices novos**: `agentesia_leads (id_escritorio, criado_em desc)`; expressão `(id_escritorio, (origem->>'campanha'))`; `(id_escritorio, motivo_perda)`; `agentesia_lead_historico (id_lead, criado_em)` e `(id_escritorio, tipo, criado_em)`; `agentesia_turnos (id_escritorio, iniciado_em desc)` para a tela de Execuções.

### 1.4 Indicadores que saem disso

Regra para todos: **contar pela data de entrada do lead** (a "safra"). "Leads de março que assinaram", não "contratos assinados em março". Assim a taxa de uma campanha não muda de mês para mês só porque o contrato demorou. E usar **mediana** para tempos, não média.

| Indicador | Como se calcula | Precisa de | Tela |
|---|---|---|---|
| Funil por campanha | Leads da safra que chegaram a cada etapa, agrupados por `origem->>'campanha'` (ou conjunto, criativo, produto do anúncio) | Histórico (1.3a) e anúncios (1.3e) | Funil |
| Conversão por etapa | Chegaram na etapa N+1 ÷ chegaram na etapa N | Histórico | Funil (já existe parcial em `repositorio.funil`) |
| Conversão por origem | Assinados ÷ leads, por campanha, conjunto, produto, UF | Marcos (1.3b) | Funil |
| Custo de IA por lead, por qualificado, por contrato | Soma de `custo_usd` dos leads da safra ÷ leads, qualificados ou assinados | `id_lead` nas chamadas (1.3c) | Consumo e Funil |
| Custo por lead e por contrato com anúncio (CPL, CAC) | (gasto com anúncio + custo de IA) ÷ leads ou assinados, por campanha | Gasto (1.3f) | Funil |
| Tempo até assinar | Mediana de `contrato_assinado_em - criado_em`; também por etapa (tempo parado em cada uma) | Marcos e histórico | Funil |
| Tempo da primeira resposta | Mediana e 90% pior, separado IA e humano, e dentro ou fora do horário | Marcos | Início |
| Motivos de perda | Ranking de `motivo_perda`, por campanha e por etapa em que o lead parou | Lista fechada (1.5) | Funil |
| Sinais | Quantos leads com cada sinal, por campanha; quantos viraram contrato | Histórico (tipo `sinal`) | Funil |
| Quem atende | % de leads só IA, só humano, os dois; contratos assinados por cada grupo | `atendido_por` | Início |
| Retomada | Leads pausados por humano que voltaram para a IA, e quanto tempo ficaram pausados | Histórico | Conversas |
| Follow-up | Enviados, respondidos, assinados depois de um follow-up | Já existe | Início |
| Barrados na porta | Por motivo, por dia | Contagem (2.2) | Execuções |

### 1.5 Motivos de perda: lista fechada sugerida

`sem_qualidade_de_segurado`, `sem_carencia`, `fora_do_prazo`, `beneficio_ja_concedido`, `ja_tem_advogado`, `sem_documentos`, `recusou_honorarios`, `sem_interesse`, `nao_respondeu` (desistência do follow-up), `pediu_para_parar`, `engano`, `outro_beneficio`, `fora_da_area`, `outro`.

Os motivos que o código já produz (`desqualificado:<motivo>` do cérebro, `sem_resposta_followup`, intenções `pediu_para_parar`, `engano`, `recusou`) viram esses códigos por um dicionário único em Python (sugestão: `app/rastreio.py`), que também dá o nome bonito para o painel. Motivo novo que não estiver no dicionário cai em `outro` e gera um evento `info` para alguém acrescentar.

### 1.6 Cuidados

- **Privacidade:** a primeira mensagem fica cortada em 300 caracteres e some junto com o lead. O `ctwa_clid` é identificador de clique, não dado pessoal sensível, mas não deve aparecer em URL de painel.
- **Devolver a conversão para a Meta** (enviar "lead qualificado" e "contrato assinado" com o `ctwa_clid` pela API de Conversões) é o que faz a Meta otimizar a campanha para quem assina, não para quem só clica. É o passo seguinte natural, mas envia dados para fora e precisa de decisão e de aceite do escritório. Fica fora desta proposta.
- **Formato do TRACK:** a documentação da Helena não lista TRACK entre os eventos de webhook (`HELENA_API.md`), e o código o reconhece pelo `eventType` ou pelo `content.type`. Confirmar no primeiro anúncio real. Reserva: a sessão (`GET chat/v2/session/{id}`) e o contato (`GET core/v1/contact/phonenumber`) também trazem `utm`.

---

## Parte 2. Filtros

### 2.1 Filtros no painel

**Como está hoje**

| Tela | Filtros que existem | Problemas |
|---|---|---|
| Início | Nenhum: período fixo de 30 dias (`DIAS` em `Inicio.tsx`) | Não dá para olhar a semana ou um agente |
| Conversas | Busca por nome ou telefone e agente (no servidor); estado (ativa, pausada, encerrada) | O filtro de estado roda **só sobre as 100 conversas carregadas**: com mais de 100 conversas, "Pausadas" mostra só as pausadas entre as 100 mais recentes, e os contadores ficam errados |
| Funil | Período (7, 30, 90 dias) e agente | Não filtra por campanha nem produto; a tabela de origens é só por campanha |
| Erros | Abertos ou todos; responsável (no navegador); todos os escritórios (admin) | Sem período, sem tipo, sem gravidade |
| Consumo | Só o mês corrente, por dia e por função | Sem agente, sem campanha, sem lead |
| Execuções | **Não existe tela.** Os turnos aparecem só dentro de cada conversa (os 50 últimos) | A equipe LawChat não tem onde ver "todos os turnos com erro hoje" |

**Proposta: um filtro só, igual em todas as telas**

Uma barra de filtros comum (`painel/src/componentes/BarraDeFiltros.tsx`), com os mesmos nomes e o mesmo comportamento em todas as telas. O que está escolhido vai para o endereço da página (`/conversas?periodo=30d&campanha=BPC-SP&situacao=humano`): voltar no navegador funciona e dá para mandar o link para um colega.

No servidor, um módulo só (`app/gestao/filtros.py`) lê esses parâmetros, confere cada um e monta o `where` com parâmetros (nunca texto colado no SQL). Conversas, Funil, Execuções, Consumo e Início passam a usar o mesmo módulo sobre a visão `agentesia_v_leads`.

| Filtro | Valores | Telas |
|---|---|---|
| Escritório | O do seletor do topo; para admin LawChat, também "todos" | Todas (todos só em Execuções, Erros e Consumo) |
| Período | Hoje, 7, 30, 90 dias, mês atual, mês passado, intervalo livre; e **por qual data** (entrada do lead ou última mensagem) | Todas |
| Agente | Lista dos agentes | Todas |
| Etapa | Etapas do produto do agente, em ordem, com nome amigável | Conversas, Funil, Execuções |
| Origem | Anúncio, UTM, direto; campanha; conjunto; criativo; produto do anúncio | Conversas, Funil, Consumo |
| Situação de atendimento | IA atendendo; pausada por humano; pausada pela equipe ou etiqueta; pausada por sinal; pausada por trava ou rajada; aguardando horário; encerrada | Conversas, Funil |
| Motivo de perda | Lista fechada (1.5) | Conversas, Funil |
| Contrato | Sem contrato; gerado e não assinado; assinado; com erro | Conversas, Funil |
| Sinal | Os sinais do produto | Conversas, Funil |
| Erro | Teve erro ou trava no período; tipo; gravidade; responsável | Conversas, Execuções, Erros |
| Atendido por | Só IA, só humano, os dois | Conversas, Funil |
| UF | Pelo DDD (já existe `uf_do_telefone`) | Conversas, Funil |
| Busca | Nome ou telefone (já existe; telefone por dígitos) | Conversas, Execuções |

A "situação de atendimento" sai de `estado` + `motivo_estado` por um dicionário único (no mesmo `app/rastreio.py`), por exemplo: `humano_assumiu` → pausada por humano; `desativada_pela_equipe` e `pausado_pela_equipe` → pausada pela equipe; `sinal:*` → pausada por sinal; `rajada`, `trava_persistente`, `pedido_repetido` → pausada por trava; `encerrado` → encerrada. Assim a tela não precisa saber os códigos internos.

**Por tela**

- **Conversas:** todos os filtros acima no servidor (acaba o problema das 100), contadores por situação calculados no servidor, paginação ("carregar mais") em vez de limite fixo, e uma etiqueta na lista mostrando campanha e motivo de perda.
- **Funil:** os mesmos filtros; seletor "agrupar por" (campanha, conjunto, criativo, produto do anúncio, UF, atendido por); colunas de custo (IA, anúncio, total) por lead, qualificado e contrato; tempo mediano até assinar; ranking de motivos de perda.
- **Execuções (tela nova):** lista de turnos (`agentesia_turnos`) com situação (respondido, silêncio, descartado, erro), motivo, etapa antes e depois, duração, custo e tokens do turno, link para a conversa. Filtros: período, escritório (admin), agente, situação, motivo do silêncio, com erro, modo (produção, teste, laboratório). Uma aba "Barrados na porta" com a contagem por motivo (2.2).
- **Consumo:** período livre e quebra por agente, por campanha e por lead (top 20 leads mais caros), com o custo por contrato.
- **Início:** só período e agente, para não virar uma tela de análise.

**Filtros salvos**

1. **Primeira versão:** o link já é o filtro salvo. Um botão "Copiar link deste filtro" e os favoritos do navegador resolvem.
2. **Segunda versão:** tabela `agentesia_filtros_salvos` (`id_escritorio`, `id_usuario`, `tela`, `nome`, `parametros` jsonb, `compartilhado` com o escritório). A barra mostra "Meus filtros" e "Do escritório". Sugestões prontas: "Pausadas por humano há mais de 1 dia", "Contrato gerado e não assinado", "Desqualificados da semana", "Turnos com erro hoje".

### 2.2 Filtros na entrada: o que o motor barra antes de gastar token

**O caminho de hoje, na ordem**

1. `ler_webhook` (`helena.py`): ignora tipos `TRANSITION` e `NOTE`, eventos que não são mensagem, e separa avisos de entrega (status).
2. `antes_do_banco` (`filtro.py`), sem gravar nada: reação, mensagem apagada, editada, chamada, enquete, sistema; grupo, lista de transmissão e canal (pelo sufixo `@g.us`, `@broadcast`, `@newsletter` e por número com mais de 15 dígitos); texto vazio sem mídia.
3. `receber` (`pipeline.py`): conta de outro escritório, webhook repetido, conta não cadastrada, canal não cadastrado, contato sem número, eco da própria IA.
4. `decidir` (`filtro.py`), com a mensagem já gravada: conversa consigo mesmo, número bloqueado, mensagem atrasada (mais de 30 min), rajada (mais de 20 mensagens em 60 s pausa a IA por 1 hora).
5. Espera que junta as mensagens (`responder_apos`): várias mensagens viram um turno só.
6. Antes de chamar a IA (`_por_que_nao_atende` e `_conferir_consumo`): escritório inativo, IA desligada no escritório, canal sem agente, agente pausado, lead pausado ou encerrado, agente sem etapa, modo teste com número fora da lista, etapa sem instrução (`sem_prompt`), fora do horário (segura até abrir ou fica em silêncio), limite de consumo estourado.

**Pedido por pedido**

| Filtro pedido | Existe? | Onde | O que falta |
|---|---|---|---|
| Grupos | Sim | `antes_do_banco` | Nada |
| Status (entregue, lido) | Sim | `ler_webhook` | Nada |
| Próprio número | Sim | `decidir` (`conversa_consigo_mesmo`) | Nada |
| Mensagem vazia | Sim, para texto | `antes_do_banco` | Mensagem só de espaços ou só pontuação conta como vazia? Hoje só `strip()` |
| Figurinha repetida | **Não** | | Figurinha (e mensagem só com emoji) abre turno e chama a IA. Proposta: figurinha ou emoji sozinho é gravado, mas **não abre turno**; entra no contexto junto com a próxima mensagem de verdade. Se o lote inteiro for só isso, o turno fecha em silêncio com motivo `so_figurinha` |
| Mensagem repetida | **Não** | | Mesmo texto 3 vezes em 2 minutos: guarda uma, não abre turno novo |
| Spam | Parcial (rajada) | `decidir` | Mensagem só com link de fora; texto muito longo (proposta: cortar o texto do lead que vai para a IA em cerca de 2.000 caracteres por turno, protege o custo e dificulta texto malicioso); número de fora do Brasil (configurável: atender, só gravar, avisar a equipe) |
| Número bloqueado | Sim | `decidir`, regras em `escritorio.config.filtro` e `agente.config.filtro` | **Não há tela para isso**: hoje só editando o JSON. Proposta: botão "Não é lead / bloquear" na conversa e uma lista em Configurações (equipe, fornecedores, parceiros) |
| Fora do horário | Sim | `horario.py`, no turno | Nada no filtro. Ver o furo da mídia abaixo |
| Lead já cliente | **Não antes da IA** | Só o sinal `cliente_antigo`, que a IA detecta (e paga para detectar), e só no Auxílio-Acidente | Proposta: antes do turno, conferir se o contato já tem contrato assinado em qualquer lead do escritório, ou se tem a etiqueta "Cliente" na Helena. Configurável por escritório: `pausar_e_avisar` (padrão: nota no chat, aviso à equipe, IA fora) ou `atender_normal` |
| Escritório sem saldo | Sim, no turno | `_conferir_consumo` / `consumo.py` | As **ações da fila que chamam IA** (classificar anúncio, resumo da conversa, resumo do contrato em `acoes.py`) **não conferem o limite**. E a leitura de mídia também não (abaixo) |

**Os furos que mais custam**

1. **Leitura de áudio e imagem antes da porta.** Em `receber`, se o filtro deixa passar, a leitura da mídia (`_ler_midia`, transcrição ou visão) começa na hora, **antes** das conferências do passo 6. Resultado: pagamos a transcrição de lead pausado com humano, de lead encerrado, de número fora da lista no modo teste, de escritório com IA desligada, com o limite estourado ou no modo "só fora do horário". E esse custo fica sem lead (`id_turno=None`). Proposta: uma conferência barata única (`pode_gastar`) chamada antes de **qualquer** gasto: leitura de mídia, turno e ações de IA da fila. Se o escritório quiser a transcrição para a equipe mesmo com a IA parada, vira opção (`ler_midia_sem_ia`, desligada por padrão; a Helena muitas vezes já manda a transcrição pronta).
2. **Figurinha e "ok" abrindo turno.** Cada um custa um turno completo (extrator + resposta). Ver a tabela.
3. **Lead já cliente** passa pelo SDR inteiro antes de a IA perceber.
4. **O que a porta barra não é contado.** Proposta: tabela `agentesia_filtro_contagem` (`id_escritorio`, `dia`, `motivo`, `total`), só números, sem conteúdo (mensagem de grupo é de terceiros e não deve ser guardada). O escritório vem do endereço do webhook, que já identifica o escritório antes de abrir a mensagem. Alimenta a aba "Barrados na porta".
5. **Rajada só na memória.** Perde a contagem ao reiniciar e não funciona com dois servidores. Por enquanto serve; quando houver mais de um servidor, contar no banco pelas mensagens dos últimos 60 segundos do lead (o índice `agentesia_mensagens_lead` já cobre).

**Configuração proposta (por escritório, o agente pode sobrescrever)**

```json
"filtro": {
  "atraso_maximo_min": 30,
  "numeros_bloqueados": ["55..."],
  "rajada": {"mensagens": 20, "segundos": 60},
  "figurinha_abre_turno": false,
  "repetida": {"vezes": 3, "minutos": 2},
  "texto_maximo_por_turno": 2000,
  "numero_estrangeiro": "avisar",
  "cliente_existente": "pausar_e_avisar",
  "ler_midia_sem_ia": false
}
```

---

## Parte 3. O que implementar, em ordem

Arquivos marcados com (*) estão sendo editados por outra frente agora (`app/pipeline.py`, `app/canal/*`, `app/cerebro/*`): combinar antes ou fazer depois que ela terminar.

| # | O que | Arquivos e tabelas | Esforço | Por que nessa ordem |
|---|---|---|---|---|
| 1 | **Porta única antes de gastar**: conferir se a IA vai atender antes de ler mídia, e conferir o limite nas ações de IA da fila | `app/pipeline.py` (*) (`receber`, `_precisa_ler_midia`, `_por_que_nao_atende`), `app/acoes.py`, `app/consumo.py`; testes em `tests/` | Pequeno | Economia direta, sem migração |
| 2 | **Lead em cada chamada de IA** | Migração 004: `agentesia_chamadas_ia.id_lead` + cópia do passado; `app/banco/postgres.py` (`gravar_chamadas`), `app/acoes.py` (`_gravar_chamadas`), `app/pipeline.py` (*) | Pequeno | Sem isso nenhum custo por lead ou contrato fica certo |
| 3 | **Linha do tempo + marcos no lead** (gatilho no banco) | Migração 004: `agentesia_lead_historico`, colunas novas em `agentesia_leads`, gatilho, preenchimento do passado; `app/rastreio.py` (dicionários de motivo de perda e situação de atendimento) | Médio | Base dos indicadores; o gatilho não exige mexer no pipeline |
| 4 | **Filtros de Conversas no servidor** (situação, etapa, campanha, contrato, perda, período) e paginação | `app/gestao/filtros.py` (novo), `app/gestao/repositorio.py` (`conversas`), `app/gestao/rotas.py` (`/conversas`), `painel/src/telas/Conversas.tsx`, `ListaConversas.tsx`, `BarraDeFiltros.tsx` (novo) | Médio | Conserta o erro dos 100 e é a tela mais usada |
| 5 | **Visão `agentesia_v_leads` e índices** | Migração 004 | Pequeno | Deixa 4, 6 e 7 rápidos |
| 6 | **Funil com filtros, agrupamento por origem, motivos de perda e tempo até assinar** | `repositorio.funil`, `rotas.py` (`/funil`), `painel/src/telas/Funil.tsx` | Médio | Responde "qual campanha dá contrato" |
| 7 | **Tela de Execuções** (turnos com filtros) | `rotas.py` (`/execucoes`), `repositorio.py`, `painel/src/telas/Execucoes.tsx` (nova), rota em `main.tsx` | Médio | Ferramenta de suporte da equipe LawChat |
| 8 | **Filtros de entrada novos**: figurinha e emoji sem turno, repetida, texto máximo, estrangeiro, lead já cliente | `app/canal/filtro.py` (*), `app/pipeline.py` (*), `tests/` | Médio | Corta turnos inúteis |
| 9 | **Contagem do que a porta barra** + aba "Barrados na porta" | Migração: `agentesia_filtro_contagem`; `app/pipeline.py` (*); tela de Execuções | Pequeno | Dá visibilidade ao item 8 |
| 10 | **Bloqueio pelo painel** ("Não é lead") e lista em Configurações | `rotas.py`, `repositorio.py`, `ConversaAberta.tsx`, `Configuracoes.tsx` | Pequeno | Hoje só pelo JSON |
| 11 | **Anúncios, toques e conjunto/criativo** | Migração: `agentesia_anuncios`, `agentesia_lead_toques`; `app/origem.py`, `app/pipeline.py` (*) (`_gravar_origem`); regra de nomes de UTM combinada com o tráfego | Médio | Funil por conjunto e criativo |
| 12 | **Gasto com anúncio** (planilha colada no painel) e CPL/CAC no Funil | Migração: `agentesia_gasto_anuncios`; `rotas.py`; tela de Consumo ou Funil | Médio | Custo por contrato completo |
| 13 | **Atendente humano por mensagem** e "atendido por" | Migração: colunas em `agentesia_mensagens`; `app/canal/helena.py` (*) | Pequeno | Confirmar antes o que o webhook traz |
| 14 | **Filtros salvos** no banco | Migração: `agentesia_filtros_salvos`; `rotas.py`; `BarraDeFiltros.tsx` | Pequeno | O link já resolve no começo |
| 15 | **Mais tarde, com decisão de produto**: API de Marketing da Meta (nomes de campanha e conjunto, gasto automático) e devolver a conversão para a Meta pelo `ctwa_clid` | Integração nova | Grande | Precisa de conta de anúncios conectada e aceite do escritório |

**Tudo da migração 004 numa vez só** (itens 2, 3, 5 e as colunas de 13): um arquivo, um desfazer e um teste. As tabelas dos itens 9, 11, 12 e 14 podem entrar na mesma migração, vazias, ou numa 005 quando forem usadas, seguindo a regra do `db/TABELAS.md` ("as tabelas nascem junto com o módulo que as usa").
