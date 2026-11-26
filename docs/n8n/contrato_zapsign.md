# Fluxos n8n "WEAVER - Contrato": especificação para a reescrita (ZapSign)

Fontes:
- `WEAVER - Contrato - NOVO.json`: **versão atual e principal** (tag `WEAVER`, `executionOrder: v1`).
  Duas rotinas: **A. Gerar contrato** (ferramenta da IA) e **B. Contrato assinado** (aviso da ZapSign
  e verificação), com um ramo **R. Resumo pós-assinatura**.
- `WEAVER - Contrato.json`: versão antiga. Usada só para achar o que a nova não tem (seção 10).

`pinData` foi ignorado. Nenhum segredo nem dado pessoal foi copiado: onde há um segredo aparece
`<SEGREDO: tipo>`; ids de modelo ou de conta aparecem como **configuração por escritório**.

Tudo o que os fluxos leem e gravam no banco está em tabelas do **Weaver** (`public.lead`,
`public.contrato_documento`...). O sistema novo **não usa nem altera** essas tabelas: a seção 11 diz
onde cada coisa passa a morar (`agentesia_*`).

---

## 1. Objetivo

Gerar, a partir dos dados pessoais que o lead informou, o contrato de honorários em um **modelo da
ZapSign**, entregar o link de assinatura ao lead pelo WhatsApp (via Helena) e acompanhar a assinatura
até o fim:

1. **Gerar** (A): validar e normalizar os dados, reservar o lead para que só uma chamada gere por vez,
   criar o documento na ZapSign, gravar documento e link, mover o lead para a etapa `assinatura`,
   mover o card do CRM, trocar as etiquetas, deixar nota no atendimento e devolver um texto pronto
   para a IA mandar ao lead (link, pedido de correção ou aviso de problema).
2. **Acompanhar** (B): ao receber o aviso da ZapSign (ou quando o lead diz que assinou), **consultar o
   documento na ZapSign** para saber quem assinou. Só quando o **lead** assinou: muda a etapa para
   `contratoassinado` (uma vez só), move o card, troca as etiquetas, encerra os follow-ups, manda a
   mensagem de confirmação (e, para um escritório, um vídeo), deixa nota e avisa o escritório.
   Assinatura só do advogado fica registrada, sem efeito no funil.
3. **Resumir** (R, opcional por escritório): depois da assinatura, uma IA lê a conversa e escreve um
   resumo do caso como nota no atendimento.

Regras de negócio que a reescrita deve manter:
- Chamada repetida com **os mesmos dados** não gera outro contrato: devolve o mesmo link.
- Dados diferentes geram **versão nova** (a anterior vira `substituido`), até **3 documentos por lead**.
- Contrato só é gerado com o lead nas etapas `contratos` ou `assinatura`.
- Nunca enviar link quebrado: só vale se a ZapSign devolveu o documento **e** um link `http(s)`.

## 2. Gatilhos

### 2.1 Geração (A)

| Item | Valor |
|---|---|
| Nó | `Faz Contrato` (`executeWorkflowTrigger` v1.1): subfluxo chamado como **ferramenta da IA** pelo fluxo principal do Weaver |
| Quem decide chamar | O agente de IA da etapa de contrato, quando acha que tem os dados (a IA aciona a ferramenta) |
| Entradas (objetos) | `etapa_agente`, `lead`, `contato`, `conexao`, `cliente`, `agente` |
| Entradas (escalares) | `id_card`, `id_step_assinatura`, `session_id`, `grupo_cliente`, `numero_ia`, `Numero_cliente` |
| Entradas (dados do contrato, preenchidos pela IA) | `nome`, `estado_civil`, `profissao`, `cpf`, `rg`, `endereco`, `numero`, `complemento`, `bairro`, `cidade`, `estado`, `cep`, `telefone`, `email`, `data`, `nomecompletomenor`, `nacionalidadedomenor`, `naturalidadedomenor`, `filiacaodomenor`, `cpfdomenor`, `naturalidadedamae`, `filiacaodamae` |
| Campos dos objetos usados | `lead.ulid`, `lead.numero_telefone`, `lead.id_contato`, `cliente.id_conta_helena`, `cliente.id_ulid`, `cliente.nome`, `cliente.api_lawchat` (token da Helena), `agente.id`, `contato.user_name` |
| Não usados no NOVO | `etapa_agente`, `conexao`, `id_card`, `id_step_assinatura`, `grupo_cliente`, `numero_ia`, `data` (a data é recalculada) |
| Saída para a IA | `{ "Mensagem": "<texto pronto para o lead>" }` (nó `RETORNO`) ou **erro** `Captura Chamada Errada (<situação>)` quando a ferramenta foi chamada fora de hora |

Filtro de teste: se `lead.ulid` está vazio ou é o id fixo de teste `00000000-0000-0000-0000-000000000001`,
o fluxo para (`PULA`) sem fazer nada.

`Dados da execução` grava como metadado da execução: `Numero_Lead`, `id_lead`, `id_conta_helena`,
`id_agente`, `cpf_lead` (para busca no n8n; no sistema novo não se grava CPF em log).

### 2.2 Assinatura (B)

Duas entradas, que o nó `B1 - Entrada` põe no mesmo formato:

| Entrada | Nó | Método e caminho | Autenticação | Corpo esperado |
|---|---|---|---|---|
| Aviso da ZapSign | `Contrato Assinado Weaver` (webhook v2) | `POST /webhook/contratoassinadogeral` (n8n), responde na hora | **Nenhuma** | Webhook da ZapSign. Campos usados: `external_id` (id do lead, uuid), `token` (token do documento), `event_type`, `signer_who_signed.name`. O corpo inteiro é repassado ao fluxo de notificação (B11) |
| Verificação (lead diz que assinou) | `Verificação (entrada interna)` (webhook v2) | `POST /webhook/contrato-verifica-assinatura`, `responseMode: lastNode` (responde com o `B13`) | Nenhuma | `{ "origem": "verificacao", "id_lead": "<uuid>", "doc_token": "<uuid>" }` |

> **Lacuna no export:** o nó `Verificação (entrada interna)` **não está ligado** a nada nas conexões
> (só o `Contrato Assinado Weaver → B1`). O `B1` e o `B12` já tratam `origem = 'verificacao'`, então a
> intenção é clara; no sistema novo a verificação é uma ação própria (seção 11.4).

Regra de passagem (`B1b`): segue só se `id_lead` é um **uuid** (leads do Weaver; os do sistema "Geral"
têm id numérico e são tratados em outro fluxo) e, quando vem da ZapSign, se `event_type` está vazio ou
contém `sign` (sem diferenciar maiúsculas). Caso contrário devolve
`{resultado: "ignorado", mensagem: "Vou pedir para a nossa equipe conferir a sua assinatura e já te retorno."}`.

## 3. Lógica passo a passo (versão NOVA)

### 3.1 A1. Montagem e validação das variáveis

`A1 - Valida os dados` (Code) normaliza cada campo bruto vindo da IA e devolve `{dados, erros, valido}`.

Normalização (`txt` = string sem espaços repetidos; `dig` = só dígitos):

| Campo | Normalização | Regra que gera erro | Texto para pedir de novo (`pedir`) |
|---|---|---|---|
| `nome` | `txt` | vazio, menos de 2 palavras, ou contém dígito | "seu nome completo" |
| `estado_civil` | `txt` | (nenhuma) | |
| `profissao` | `txt`, vazio vira `Não informado` | (nenhuma) | |
| `cpf` | formata `000.000.000-00` se válido | dígito verificador inválido, 11 dígitos repetidos, ou ≠ 11 dígitos | "o seu CPF" |
| `rg` | `txt` | (nenhuma) | |
| `endereco` | `txt` | vazio ou só números | "o nome da sua rua ou avenida" |
| `numero` | `txt` | vazio | "o número da sua residência" |
| `complemento` | `txt` | (nenhuma) | |
| `bairro` | `txt` | vazio | "o seu bairro" |
| `cidade` | `txt` | vazio ou contém dígito | "a sua cidade" |
| `estado` | `txt` maiúsculo | não é uma das 27 UFs | "o seu estado (a sigla, como MG ou SP)" |
| `cep` | formata `00000-000` | ≠ 8 dígitos | "o seu CEP" |
| `telefone` | só dígitos; tira `55` se tiver 12 ou 13 dígitos | não gera erro: se não ficar com 10 ou 11 dígitos, usa o número da conversa (`lead.numero_telefone`, mesma regra); se nem assim, vazio | |
| `email` | minúsculo, sem espaços | preenchido e fora do formato `x@y.zz` | "o seu e-mail" |
| `cpfdomenor` | `txt` | preenchido e inválido | "o CPF do(a) menor" |
| demais campos do menor e da mãe | `txt` | (nenhuma) | |

`A1b - Dados certos?`:
- **Válido** → `A1g`.
- **Inválido** → releitura da conversa (A1c–A1f):
  1. `A1c` lê as 200 últimas mensagens da memória do chat (Weaver, seção 6).
  2. `A1d` monta a conversa em ordem crescente de `id`, só mensagens com `content` texto, rotuladas
     `IA:` (`type = ai`) ou `Humano:` (`type = human`), separadas por linha em branco.
  3. `A1e` pede à OpenAI que extraia os dados cadastrais da conversa (prompt na seção 7.1).
  4. `A1f` troca **só os campos que estavam com erro** pelo valor que a IA achou (se não vazio) e
     valida tudo de novo. Guarda `trocados`, `erros_iniciais` e `releitura_falhou`.
- `A1g` fica com o resultado da segunda validação, se ela rodou; senão, com o da primeira.
- `A1h - Pode gerar?`: inválido → vai direto para a resposta `dado_invalido` (A9) com o pedido de
  correção. Válido → reserva.

### 3.2 A2. Reserva do lead e decisão (um comando SQL só)

`A2 - Reserva o lead` recebe `id_lead`, `dados` (JSON, sem `telefone_origem`), limite `3` e o id da
execução. Trava a linha do lead (`FOR UPDATE`) e decide, nesta ordem:

| Decisão | Quando |
|---|---|
| `ja_assinado` | etapa atual do lead (pelo **id**, em `agente_etapas`) é `contratoassinado`, ou o último documento está `assinado` |
| `etapa_errada` | etapa atual não é `contratos` nem `assinatura` |
| `gerando` | último documento está `gerando` com `reservado_ate > now()` (reserva de **3 minutos**) |
| `mesmo` | último documento está `gerado` e `dados_hash = md5(dados)` |
| `limite` | já existem ≥ 3 documentos em `gerado`, `substituido` ou `assinado` |
| `sem_chave` | não há chave ZapSign ativa com `template_id` para o escritório (ver 3.3) |
| `reservar` | nenhum dos casos acima |

Em `reservar`:
- se o último documento está `falhou` ou com reserva vencida, **reaproveita a mesma linha**
  (`estado = 'gerando'`, novos dados e hash, `reservado_ate = now() + 3 min`, limpa `erro`);
- senão **insere a versão nova** (`versao = última + 1`) em `gerando`. Se outra chamada inseriu no
  mesmo instante, o índice único impede (`ON CONFLICT DO NOTHING`) e a decisão vira `gerando`.

Devolve também: `id_doc`, `versao`, `link_atual`, `versao_atual`, `documentos_feitos`, `etapa`,
dados do lead (`id_cliente`, `id_agente`, `id_contato`, `numero_telefone`), `chave` (token ZapSign),
`template_id`, `api_lawchat` (token Helena) e nome do escritório.

`A2b - Decisão` organiza: erro de banco → `erro_banco`; sem linha → `lead_inexistente`;
`gerar = (decisao == 'reservado')`. `A2c`: só `reservado` segue para a ZapSign; o resto vai para A9.

### 3.3 Escolha do modelo de documento

Não há lógica no código do fluxo: o modelo vem do banco, na mesma consulta da reserva (`chave` em A2):

- `api_key` (ativa, do escritório) + `api_key_atributos` (`template_id`);
- vale a linha **do agente** (`aka.id_agente = lead.id_agente`); se não houver, a linha **geral** do
  escritório (`aka.id_agente IS NULL`); empate → `aka.id` mais recente.

Ou seja: **um modelo por agente, com um modelo padrão por escritório**. Não existe escolha por produto,
por presença de menor nem por dado da conversa. O id do modelo (`template_id`) é **configuração por
escritório** (não aparece no JSON).

### 3.4 A3–A5. Chamada à ZapSign

1. `A3 - Monta o pedido` monta o corpo como **objeto** (não como texto, para aspas e quebras de linha
   nos dados não quebrarem o JSON). Mapeamento completo na seção 5. `DATA` = agora em
   `America/Sao_Paulo`, formato `dd-LL-yyyy HH:mm`. Valores ausentes vão como `""`. `signer_email` só
   vai se houver e-mail.
2. `A4 - Gera na ZapSign`: `POST /api/v1/models/create-doc` (seção 4.1). Timeout 45 s, **sem nova
   tentativa** (para não criar dois documentos). Erro não derruba o fluxo (`continueRegularOutput`).
3. `A5 - Confere a resposta`: `ok` só se não houve erro, há `token` (documento) e o primeiro assinante
   tem `sign_url` (ou `signing_link`) começando com `http`. Guarda `doc_token`, `signer_token`
   (`signers[0].token`), `link`. Se falhou, classifica a **causa** pelo texto do erro:

   | Causa | Texto do erro contém | Quem resolve | `falha` |
   |---|---|---|---|
   | `pagamento` | `payment required` ou `402` | escritório (conta ZapSign) | `equipe` |
   | `limite` | `limit`, `quota`, `too many` ou `429` | escritório | `equipe` |
   | `chave` | `forbidden`, `unauthorized`, `401` ou `403` | escritório/suporte | `equipe` |
   | `modelo` | `not found`, `bad request`, `400`, `404`, `422` ou `template` | escritório/suporte | `equipe` |
   | `fora_do_ar` | qualquer outro (inclui timeout) | ninguém: tentar de novo | `imprevisto` |

4. `A5b - Gerou?`: sim → A6; não → `A6x - Marca a falha` (`estado = 'falhou'`, `erro`, libera a reserva)
   → A9.

### 3.5 A6. Gravação do contrato e mudança de etapa

`A6 - Grava o contrato`, um comando só, **assim que a ZapSign responde**:
1. documento → `estado = 'gerado'`, `provedor = 'zapsign'`, `doc_token`, `signer_token`, `link`,
   limpa reserva e erro;
2. o documento `gerado` anterior do mesmo lead → `substituido`;
3. lead → `id_contrato = doc_token`, `id_etapa_atual` = etapa `assinatura` ativa do agente (se existir;
   senão mantém a atual).

Devolve `gravado`, `versao`, `substituidos`, `id_etapa_assinatura`, `etapa_gravada`.

### 3.6 A7. Card do CRM (coluna "Aguardando assinatura")

1. `A7 - Cards do lead`: até 10 cards do lead com `id_card_helena`; para cada um, a etapa do **mesmo
   painel** com `tipo_etapa = 'AGUARDANDO_ASSINATURA'` (`valor_uuid` = stepId da Helena). Card sem
   etapa gravada usa a coluna desse tipo no **primeiro painel** do escritório. Sempre devolve ao menos
   uma linha.
2. `A7b`: só segue se há `id_card_helena` e `step_uuid`.
3. `A7c - Move o card`: `PUT crm/v3/panel/card/{id}` com `StepId` e `Position = 0` (topo da coluna),
   3 tentativas.
4. `A7d` compara cada card enviado com a resposta; `A7e` grava a etapa nova só nos cards que moveram.

### 3.7 A8. Etiquetas e nota

1. `A8 - Tags`: busca, pelo **nome**, o id Helena da etiqueta `✍️ Etapa de Assinatura` e a lista a
   remover: `✅ Contrato Assinado`, `📄 Contrato em Elaboração`, `🛒 Comercial`, `📞 SDR`,
   `❌ Desqualificado`.
2. Se há etiqueta e contato: `A8c` adiciona (`InsertIfNotExists`), depois `A8d` remove as outras
   (`DeleteIfExists`).
3. `A8e - Nota no chat` (sempre, mesmo sem etiqueta):
   `Contrato gerado (versão N). Acompanhar o lead até a assinatura.`

### 3.8 A9. Resposta para a IA, histórico, nota de problema e alerta

`A9 - Resposta` monta `situacao`, `Mensagem` (texto que a IA manda ao lead, seção 8.1), `link`, `nota`
(para a equipe do escritório), `responsavel`, `descricao` e `aviso` (para a equipe LawChat):

| Situação | Mensagem ao lead | Nota no chat | Alerta LawChat | Responsável |
|---|---|---|---|---|
| `dado_invalido` | pedido de correção | sim | não | `lead` |
| `gerado` | link (ou "Contrato atualizado...") | não (já houve A8e) | só se não gravou no banco ou card não moveu | |
| `zapsign_fora_do_ar` | "imprevisto, vou tentar novamente" | sim | sim | `zapsign` |
| `zapsign_pagamento/limite/chave/modelo` | "nossa equipe vai te enviar o link" | sim, com "gerar manualmente" | sim | `cliente` |
| `mesmo_link` | "Segue novamente o link..." | não | não | |
| `em_andamento` | "já está sendo preparado" | não | não | |
| `limite` | "nossa equipe vai falar com você" | sim | sim | `lead` |
| `ja_assinado` | "já está assinado" | não | não | |
| `sem_chave` | "nossa equipe vai te enviar o link" | sim | sim | `cadastro` |
| `erro_banco` | "imprevisto, vou tentar novamente" | não | sim | `lawchat` |
| `etapa_errada`, `lead_inexistente` | **nenhuma**: erro para a IA (`Captura Chamada Errada`) | não | só `lead_inexistente` | |

Depois:
1. `A9e - Registra no histórico`: insere em `contrato_evento` (Weaver) toda chamada (`fluxo = 'gerar'`)
   e devolve: quando foi o **primeiro aviso** do mesmo problema para o escritório desde o último
   contrato gerado com sucesso, quantas ocorrências houve, e se já houve nota igual para este lead nas
   **últimas 6 horas** (para não repetir).
2. `A9f - Monta a nota`: manda a nota se houver texto e não houve nota igual em 6 h (se o histórico
   falhou, manda assim mesmo). Se o responsável é o `cliente` e o problema é recorrente, acrescenta
   `Primeiro aviso deste problema: <data>. Ocorrências desde então: <n>.`
3. `A9h`: nota no chat (se há `session_id` e token).
4. `A9c - Alerta`: se há alerta, `POST` no fluxo `AlertaLawchat` (seção 4.4) com
   `{origem: 'contrato_gerar', texto, cliente, id_lead, telefone_lead, falhas: [alerta], execution_id}`.
   O `texto` começa com `⚠️ Contrato (Weaver)` e traz escritório, telefone do lead e situação.
5. `A9d`: se `erro_para_a_ia` (situações sem mensagem) → `stopAndError`; senão `RETORNO`.

### 3.9 Esperas e lembretes

- **Não há lembrete de assinatura neste fluxo.** Nenhum nó agenda "você ainda não assinou".
  Os lembretes do Weaver vinham do sistema de follow-up geral (`followups`, `followup_queue`), e este
  fluxo só os **encerra** quando o lead assina (B7).
- Esperas existentes:
  - reserva de 3 minutos (A2) contra geração dupla;
  - 3 segundos entre o vídeo e a mensagem de confirmação (B9d), para um escritório específico;
  - novas tentativas: banco 3× a cada 2 s; Helena 3× a cada 2 s; OpenAI 2× a cada 2–3 s; leitura da
    ZapSign 3× a cada 2 s; **criação na ZapSign: nenhuma**.
- Lembretes no sistema novo: proposta na seção 11.5.

### 3.10 B. Assinatura concluída

1. `B1`/`B1b`: entrada e filtro (seção 2.2).
2. `B2 - Lead e contrato`: acha o documento pelo `doc_token` recebido; sem token, pelo lead (último
   `gerado` ou `assinado`, maior versão). Para contratos antigos sem ficha, usa `lead.id_contrato`.
   Traz também: etapa atual, id da etapa `contratoassinado` do agente, escritório e token Helena,
   chave ZapSign (a mais recente ativa do escritório), `session_id` mais recente do lead, canal,
   **mensagem pós-assinatura** (do prompt ligado à etapa `contratoassinado`, ou o texto padrão da
   seção 8.2) e ids das etiquetas `✅ Contrato Assinado` e `✍️ Etapa de Assinatura`.
3. `B2b - Situação`: erro de banco → `erro_banco`; sem lead → `lead_inexistente`; sem `doc_token` ou
   sem chave → `sem_contrato`. Qualquer parada vai direto ao resultado (B12).
4. `B3 - Lê o documento na ZapSign`: `GET /api/v1/docs/{doc_token}/` (seção 4.2). **Não confia no
   aviso**: sempre relê o documento.
5. `B4 - Quem assinou`: identifica o assinante que é o lead, nesta ordem:
   1. pelo `signer_token` guardado na geração;
   2. pelos **8 últimos dígitos** do telefone (`signers[].phone_number` × telefone do lead);
   3. se o documento tem um assinante só, é ele.

   Calcula `lead_assinou` (`status` ou `status_code` = `signed`), `todos_assinaram` (documento com
   `status = signed`), `outro_assinou` (alguém além do lead), `arquivo_assinado` (`signed_file`, só com
   todos assinados), `link` do lead, e a lista `signatarios` (nome, status, data, se é o lead).
6. `B5 - Marca como assinado`, um comando só (dois avisos simultâneos: só o primeiro altera o lead):
   - lead → etapa `contratoassinado`, **só se** o lead assinou, a etapa existe e o lead ainda não está
     nela (`primeira_vez` = linhas alteradas);
   - documento → `assinado` + `lead_assinou_em` (se o lead assinou), `concluido_em` (se todos
     assinaram), `arquivo_assinado`, `signatarios`.
7. `B5b - Primeira vez?`: não → resultado (B12). Sim → efeitos:
   1. **Card** (B6–B6e): igual ao A7, com `tipo_etapa = 'CONTRATO_ASSINADO'` e só `StepId` (sem
      `Position`).
   2. **Follow-ups** (B7): apaga `followups` do lead e cancela `followup_queue` pendente com
      `payload.motivo = 'contrato assinado'`.
   3. **Etiquetas** (B8): se há contato e etiqueta, adiciona `✅ Contrato Assinado` e remove
      `✍️ Etapa de Assinatura`.
   4. **Mensagem ao lead** (B9): só quando veio da **ZapSign** e há `session_id` (na verificação, a
      mensagem volta para quem chamou). Para **um escritório específico** (id fixo no código:
      configuração por escritório), antes manda um **vídeo** (`fileUrl` público, configuração por
      escritório) e espera 3 s. Depois a mensagem pós-assinatura (seção 8.2).
   5. **Nota** (B10): `Contrato assinado pelo lead.` + ` Confirmado pela verificação de assinatura.`
      quando veio da verificação.
   6. **Resumo** (R1–R10, seção 3.11).
   7. **Notificação ao escritório** (B11): `POST` no fluxo `NotificaContratoAssinado` com o corpo
      original da ZapSign (ou, na verificação, o documento lido + `external_id`).
8. `B12 - Resultado`:

   | Resultado | Mensagem (para a verificação) | Nota no chat | Alerta LawChat |
   |---|---|---|---|
   | `erro` (banco) | "Vou pedir para a nossa equipe conferir..." | não | sim |
   | `lead_inexistente` | idem | não | sim |
   | `sem_contrato` | idem | sim (`cadastro`) | sim |
   | `zapsign_sem_leitura` | idem | sim; `cliente` se erro 401/402/403, senão `zapsign` | sim |
   | `nao_reconhecido` | idem | sim (`lawchat`) | sim |
   | `assinado` (primeira vez) | mensagem pós-assinatura | só se assinou versão **substituída** (`lead`) | se card não moveu, mensagem falhou ou versão substituída |
   | `ja_estava_assinado` | "Seu contrato já está assinado..." | não | se o agente não tem a etapa `contratoassinado` ou se a gravação falhou |
   | `so_o_advogado_assinou` | "Ainda não consta a sua assinatura... Segue o link novamente:" + link | sim | não |
   | `pendente` | idem | só na verificação | não |

9. `B12e`–`B12c`: histórico (`fluxo = 'assinado'` ou `'verificacao'`), nota com a mesma regra de
   6 horas e "primeiro aviso", alerta `AlertaLawchat` com `origem: 'contrato_assinado'` e texto
   começando por `⚠️ Contrato assinado (Weaver)`.
10. `B13 - Resposta`: `{resultado, mensagem, link}` (usado só pela entrada de verificação).

### 3.11 R. Resumo pós-assinatura (opcional)

1. `R1`: lê a configuração do escritório (`contrato_resumo_config`: `prompt`, `modelo`, `ativo`;
   linha do agente vale mais que a geral). Não roda se o lead **já tem resumo**.
2. `R3`/`R4`: 300 últimas mensagens da memória, rotuladas `Atendente:`/`Cliente:`; se passar de 60 000
   caracteres, fica com o **final**. Prompt do escritório, ou o padrão (seção 7.2); modelo padrão
   `gpt-4.1-mini`.
3. `R6`: OpenAI (seção 4.3). `R7`: texto até 6 000 caracteres; registra erro se não havia conversa ou a
   IA falhou/voltou vazia.
4. `R8`: grava em `contrato_resumo` (resumo, prompt usado, modelo, mensagens lidas, tokens, erro).
5. `R10`: nota `📄 RESUMO DO CONTRATO ASSINADO` + resumo.

### 3.12 Mudanças de card/etapa no CRM e notas: resumo

| Momento | Etapa do lead (Weaver) | Coluna do card | Etiquetas | Nota |
|---|---|---|---|---|
| Contrato gerado | `assinatura` | `AGUARDANDO_ASSINATURA`, topo | + `✍️ Etapa de Assinatura`; − Assinado, Em Elaboração, Comercial, SDR, Desqualificado | "Contrato gerado (versão N)..." |
| Problema na geração | não muda | não muda | não muda | nota do problema (máx. 1 por 6 h e situação) |
| Lead assinou (1ª vez) | `contratoassinado` | `CONTRATO_ASSINADO` | + `✅ Contrato Assinado`; − `✍️ Etapa de Assinatura` | "Contrato assinado pelo lead." + resumo (se ligado) |
| Só o advogado assinou | não muda | não muda | não muda | "O escritório assinou... lead pendente" |

## 4. Chamadas externas

Cabeçalhos: só os nomes. Valores de autenticação: `<SEGREDO: ...>`.

### 4.1 ZapSign: criar documento a partir de modelo (A4)

| Item | Valor |
|---|---|
| Método e URL | `POST https://api.zapsign.com.br/api/v1/models/create-doc` |
| Cabeçalhos | `Authorization: Bearer <SEGREDO: token da API ZapSign do escritório>`, `Content-Type: application/json` |
| Timeout / tentativas | 45 s / nenhuma |

Corpo:

```json
{
  "template_id": "<id do modelo: configuração por escritório>",
  "external_id": "<id do lead>",
  "signer_name": "<nome>",
  "signer_phone_country": "55",
  "signer_phone_number": "<DDD + número, 10 ou 11 dígitos>",
  "signer_email": "<e-mail, só se houver>",
  "data": [ { "de": "<texto da variável no modelo>", "para": "<valor>" } ]
}
```

Resposta, campos usados: `token` (documento), `signers[0].token` (assinante), `signers[0].sign_url`
(ou `signers[0].signing_link`). Em erro: `message`, `error.message`, `error.description`.

### 4.2 ZapSign: ler documento (B3)

| Item | Valor |
|---|---|
| Método e URL | `GET https://api.zapsign.com.br/api/v1/docs/{token_do_documento}/` |
| Cabeçalhos | `Authorization: Bearer <SEGREDO: token da API ZapSign do escritório>` |
| Timeout / tentativas | 30 s / 3 (2 s) |

Resposta, campos usados: `status` (`signed` = todos assinaram), `signed_file`,
`signers[]`: `token`, `name`, `status` ou `status_code` (`signed`), `phone_number`, `sign_url` ou
`signing_link`, `signed_at`.

### 4.3 OpenAI (A1e e R6)

| Item | Valor |
|---|---|
| Método e URL | `POST https://api.openai.com/v1/chat/completions` |
| Autenticação | credencial n8n `openAiApi` (`Authorization: Bearer <SEGREDO: chave OpenAI>`); `Content-Type: application/json` |
| A1e | `model: gpt-4.1-mini`, `temperature: 0`, `response_format: {type: json_object}`, mensagens `system` + `user`; timeout 45 s; 2 tentativas |
| R6 | `model`: da configuração ou `gpt-4.1-mini`; mensagens `system` (prompt) + `user` (`Conversa:\n\n...`); timeout 60 s; 2 tentativas |
| Resposta usada | `choices[0].message.content`; em R6 também `usage.prompt_tokens`, `usage.completion_tokens` |

### 4.4 Helena

Todas com `Authorization: <SEGREDO: token da Helena do escritório>` (no NOVO o valor vai **sem**
o prefixo `Bearer`; a versão antiga usava `Bearer` num dos nós; o `HelenaConta` do sistema novo aceita
os dois).

| Uso | Método e caminho (host `https://api.helena.run`) | Outros cabeçalhos | Corpo |
|---|---|---|---|
| Mover card (A7c) | `PUT /crm/v3/panel/card/{id_card}` | `accept: application/json`, `Content-Type: application/json` | `{"fields": ["StepId", "Position"], "stepId": "<stepId>", "position": 0}` |
| Mover card (B6c) | idem | idem | `{"fields": ["StepId"], "stepId": "<stepId>"}` |
| Pôr etiqueta (A8c, B8b) | `POST /core/v1/contact/{id_contato}/tags` | idem | `{"tagIds": ["<id>"], "operation": "InsertIfNotExists"}` |
| Tirar etiquetas (A8d, B8c) | idem | idem | `{"tagIds": ["<id>", ...], "operation": "DeleteIfExists"}` |
| Nota (A8e, A9h, B10, R10, B12h) | `POST /chat/v1/session/{session_id}/note` | `content-type: application/*+json`, `accept: application/json` | `{"text": "<nota>"}` |
| Vídeo (B9c) | `POST /chat/v1/session/{session_id}/message` | `Accept: application/json` | `{"channelId": "<canal>", "fileUrl": "<URL do vídeo: configuração por escritório>"}` |
| Mensagem (B9e) | idem | idem | `{"channelId": "<canal>", "to": "<telefone do lead>", "text": "<mensagem>"}` |

Respostas: só se conferiu se houve erro (cards: um item de resposta por card enviado).
Timeout 20 s (30 s nas mensagens); 3 tentativas a cada 2 s, exceto o vídeo (nenhuma).

### 4.5 Fluxos internos do n8n (LawChat)

| Uso | Método e URL | Corpo |
|---|---|---|
| Alerta para a equipe LawChat (A9c, B12c) | `POST https://webhook.lawchats.com.br/webhook/AlertaLawchat` | objeto `aviso` (3.8). Timeout 10 s, 2 tentativas |
| Notificação de contrato assinado ao escritório (B11) | `POST https://webhook.lawchats.com.br/webhook/NotificaContratoAssinado` | corpo original da ZapSign, ou documento lido + `external_id` |

## 5. Mapeamento das variáveis do documento

`de` é o **texto exato** da variável no modelo da ZapSign (sem `{{ }}`, como o fluxo envia). No NOVO o
mapeamento é **fixo no código**; os mesmos 22 nomes estão na versão antiga.

| # | Variável no modelo (`de`) | Campo do lead (`para`) | Formato aplicado |
|---|---|---|---|
| 1 | `NOME` | `nome` | texto, ≥ 2 palavras, sem dígito |
| 2 | `Estado Civil` | `estado_civil` | texto livre |
| 3 | `Profissão` | `profissao` | texto; vazio = `Não informado` |
| 4 | `CPF` | `cpf` | `000.000.000-00`, dígito verificador |
| 5 | `RG` | `rg` | como informado |
| 6 | `Endereço` | `endereco` | logradouro sem número |
| 7 | `Número` | `numero` | como informado (`S/N` aceito) |
| 8 | `Complemento` | `complemento` | opcional |
| 9 | `Bairro` | `bairro` | obrigatório |
| 10 | `Cidade` | `cidade` | sem dígito |
| 11 | `Estado` | `estado` | UF maiúscula |
| 12 | `CEP` | `cep` | `00000-000` |
| 13 | `Telefone` | `telefone` | 10–11 dígitos, sem `55`; se faltar, o número da conversa |
| 14 | `Email` | `email` | minúsculo, opcional |
| 15 | `DATA` | data e hora da geração | `dd-LL-yyyy HH:mm`, fuso `America/Sao_Paulo` |
| 16 | `Qual o nome completo do(a) menor?` | `nomecompletomenor` | opcional |
| 17 | `Qual o CPF do(a) menor?` | `cpfdomenor` | opcional; se preenchido, CPF válido |
| 18 | `Nacionalidade do(a) menor` | `nacionalidadedomenor` | opcional |
| 19 | `Naturalidade do(a) menor` | `naturalidadedomenor` | opcional |
| 20 | `filiação do(a) menor` | `filiacaodomenor` | opcional |
| 21 | `Naturalidade da mae` | `naturalidadedamae` | opcional |
| 22 | `filiação da mae` | `filiacaodamae` | opcional |

Campos do assinante (fora de `data`): `signer_name` = `nome`, `signer_phone_country` = `55`,
`signer_phone_number` = `telefone`, `signer_email` = `email` (se houver), `external_id` = id do lead.

Observações:
- Os campos do menor e da mãe **não têm regra que os exija**: vão vazios quando não se aplicam. O
  modelo do escritório decide se aparecem.
- `estado_civil` e `rg` também não são exigidos.
- A data de geração **ignora** a entrada `data` da ferramenta.

## 6. Consultas ao banco

**Todas as tabelas abaixo são do Weaver** (`public.*`, credencial "Organização"). O sistema novo não as usa.

| Nó | Tabelas | Operação | Para quê |
|---|---|---|---|
| A1c | `memoria` (Weaver) | SELECT 200 últimas por `session_id = id do lead` | Reler a conversa quando um dado veio errado |
| A2 | `lead` (FOR UPDATE), `agente_etapas`, `contrato_documento`, `api_key`, `api_key_atributos`, `clientes` (Weaver) | SELECT + UPDATE/INSERT em `contrato_documento` | Decisão e reserva atômicas; chave e modelo ZapSign; token Helena |
| A6 | `contrato_documento`, `agente_etapas`, `lead` (Weaver) | UPDATE | Gravar documento e link, substituir versão anterior, mover o lead para `assinatura`, gravar `id_contrato` |
| A6x | `contrato_documento` (Weaver) | UPDATE | Marcar falha e liberar a reserva |
| A7 / B6 | `card`, `etapas`, `painel`, `lead` (Weaver) | SELECT | Cards do lead e stepId da coluna `AGUARDANDO_ASSINATURA` / `CONTRATO_ASSINADO` |
| A7e / B6e | `card` (Weaver) | UPDATE | Gravar a etapa nova nos cards que moveram |
| A8 | `tags`, `lead` (Weaver) | SELECT | Ids Helena das etiquetas, por nome |
| A9e / B12e | `contrato_evento`, `lead`, `clientes` (Weaver) | INSERT + SELECT | Histórico de cada chamada, primeiro aviso, nota repetida em 6 h |
| B2 | `contrato_documento`, `lead`, `agente_etapas`, `prompts`, `clientes`, `api_key`, `conversas_agentes`, `conexoes`, `tags` (Weaver) | SELECT | Lead, documento, sessão, canal, mensagem pós-assinatura, etiquetas, chave |
| B5 | `lead`, `contrato_documento` (Weaver) | UPDATE | Passagem a `assinado`, idempotente |
| B7 | `followups`, `followup_queue` (Weaver) | DELETE / UPDATE | Encerrar follow-ups do lead assinado |
| R1 | `contrato_resumo_config`, `contrato_resumo` (Weaver) | SELECT | Resumo ligado? Lead já tem resumo? |
| R3 | `memoria` (Weaver) | SELECT 300 últimas | Conversa para o resumo |
| R8 | `contrato_resumo` (Weaver) | INSERT | Guardar resumo, prompt, modelo, tokens, erro |

Colunas de `contrato_documento` usadas (referência para o novo modelo): `id`, `id_lead`, `versao`,
`estado` (`gerando`, `gerado`, `substituido`, `assinado`, `falhou`), `provedor`, `doc_token`,
`signer_token`, `link`, `dados`, `dados_hash`, `reservado_ate`, `erro`, `execution_id`,
`lead_assinou_em`, `concluido_em`, `arquivo_assinado`, `signatarios`, `updated_at`.

## 7. Prompts de IA

### 7.1 Releitura dos dados (A1e)

Intenção: quando a ferramenta recebeu algum dado inválido, extrair da conversa os dados cadastrais do
cliente, só o que ele informou ou confirmou, para substituir **apenas** os campos com erro.
Saída: JSON com chaves fixas. Mensagem `system`:

```
Você é um extrator de dados cadastrais. Leia a conversa de WhatsApp entre uma atendente (IA) e um
cliente (Humano) e extraia os dados pessoais do cliente para um contrato.

REGRAS
- Considere só dados informados ou confirmados pelo Humano. Se a IA resumiu e o Humano confirmou, o resumo vale.
- Se o Humano corrigiu um dado, use sempre a versão mais recente.
- Nunca invente, deduza ou complete. Campo não informado = "".
- Ignore dados de terceiros.
- Endereço em uma linha só: separe nos campos certos.

FORMATO
- cpf: 000.000.000-00 (se não tiver 11 dígitos, devolva como foi digitado)
- cep: 00000-000
- estado: sigla da UF
- endereco: tipo e nome da rua, sem o número
- numero: só o número do imóvel ("S/N" se não tiver)

Responda SOMENTE com um JSON com estas chaves: {"nome":"","estado_civil":"","profissao":"","cpf":"",
"rg":"","endereco":"","numero":"","complemento":"","bairro":"","cidade":"","estado":"","cep":"",
"telefone":"","email":""}
```

Mensagem `user`: `Nome do contato no WhatsApp (só apoio): <nome>` + `Conversa:` + conversa rotulada.
Não extrai os campos do menor nem da mãe.

### 7.2 Resumo pós-assinatura (R4, padrão quando o escritório não escreveu um)

Intenção: resumo curto para a equipe, sem inventar, com avaliação de qualidade e potencial.

```
Você recebe a conversa de WhatsApp entre a atendente (IA) e um cliente que acabou de ASSINAR o
contrato com o escritório.
Escreva um resumo curto para a equipe do escritório, em português, sem inventar nada que não esteja
na conversa.

Responda neste formato:

📄 Resumo do caso:
[o que aconteceu, quando, e os pontos que importam para o caso, em até 4 linhas]

📊 Qualidade do contrato:
[Alta | Média | Baixa] — [justificativa curta]

💰 Potencial retorno:
[avaliação curta do potencial do caso para o escritório]

Se a conversa não trouxer alguma informação, escreva "não informado".
```

Mensagem `user`: `Conversa:\n\n` + conversa rotulada `Atendente:`/`Cliente:`.

## 8. Textos enviados ao lead

### 8.1 Geração (devolvidos à IA, que os envia)

| Situação | Texto |
|---|---|
| `gerado`, versão 1 | `Segue o link de contrato:\n<link>` |
| `gerado`, versão > 1 | `Contrato atualizado. Segue o novo link para assinatura:\n<link>` |
| `mesmo_link` | `Segue novamente o link do seu contrato:\n<link>` |
| `dado_invalido`, 1 campo | `Para finalizar seu contrato, preciso confirmar uma informação: <pedir>. Pode me enviar novamente, por favor?` |
| `dado_invalido`, vários | `Para finalizar seu contrato, preciso confirmar algumas informações: <a>, <b> e <c>. Pode me enviar novamente, por favor?` |
| `em_andamento` | `Seu contrato já está sendo preparado. Em instantes eu te envio o link para assinatura.` |
| `zapsign_fora_do_ar`, `erro_banco`, `erro_interno` | `Tive um imprevisto para gerar seu contrato agora. Vou tentar novamente em instantes, tudo bem?` |
| `zapsign_<causa do cliente>`, `sem_chave` | `Seu contrato será finalizado pela nossa equipe, que vai te enviar o link por aqui em breve.` |
| `limite` | `Seu contrato já foi atualizado algumas vezes. Para essa nova alteração, nossa equipe vai falar com você por aqui.` |
| `ja_assinado` | `Seu contrato já está assinado. Está tudo certo por aqui!` |

### 8.2 Assinatura

Mensagem pós-assinatura padrão (quando a etapa `contratoassinado` não tem `mensagem_troca` no prompt):

```
✅ Assinatura confirmada!

Acabamos de verificar e seu contrato foi assinado com sucesso. Está tudo certo por aqui! 🎉

A partir de agora, nossa equipe dá andamento ao seu caso e você será informado(a) sobre cada nova
etapa. Se surgir qualquer dúvida, é só nos chamar por aqui.

Obrigado pela confiança! 🤝
```

Outros (respostas da verificação):
- `Seu contrato já está assinado. Está tudo certo por aqui!`
- `Ainda não consta a sua assinatura por aqui. Segue o link novamente:\n<link>` (sem link: só a 1ª frase)
- `Vou pedir para a nossa equipe conferir a sua assinatura e já te retorno.`

### 8.3 Notas para a equipe do escritório (texto fixo)

- `Contrato gerado (versão N). Acompanhar o lead até a assinatura.`
- `A IA não gerou o contrato porque o lead informou dados que não conferem (<campos>). Ela pediu a correção ao lead.`
- `⚠️ A IA tentou gerar o contrato deste lead e NÃO conseguiu: <explicação>` + (causa do cliente)
  ` Enquanto isso, o contrato deste lead precisa ser gerado manualmente.` Explicações por causa:
  - `pagamento`: a ZapSign recusou o pedido por falta de pagamento ou de créditos na conta. Regularize a conta da ZapSign para a IA voltar a gerar contratos.
  - `limite`: a conta da ZapSign atingiu o limite de documentos. Aumente o limite ou o plano da ZapSign para a IA voltar a gerar contratos.
  - `chave`: a ZapSign recusou a chave de acesso cadastrada (chave inválida, vencida ou sem permissão). Confira a chave da ZapSign com o suporte.
  - `modelo`: a ZapSign não aceitou o pedido (modelo de contrato não encontrado ou alterado). Confira o modelo na ZapSign com o suporte.
  - `fora_do_ar`: a ZapSign não respondeu. A IA vai tentar de novo quando o lead responder.
- `sem_chave`: `⚠️ A IA tentou gerar...: não há chave da ZapSign ou modelo de contrato cadastrado para este escritório. Fale com o suporte.`
- `limite`: `O lead pediu mais uma alteração no contrato, mas já foram gerados N contratos para ele. A IA não gerou outro: a alteração precisa ser feita pela equipe.`
- `Contrato assinado pelo lead.` (+ ` Confirmado pela verificação de assinatura.`)
- `⚠️ Atenção: o lead assinou a versão N do contrato, que já tinha sido substituída por uma versão mais nova. Confira qual versão vale.`
- `sem_contrato`: `⚠️ [O lead disse que assinou o contrato. ]Não encontramos contrato gerado para ele no sistema. Confira na ZapSign se existe um contrato e se foi assinado.`
- `zapsign_sem_leitura`: `⚠️ [...]Não conseguimos conferir a assinatura na ZapSign: ` + `a ZapSign recusou o acesso da conta (pagamento pendente ou chave recusada). Regularize a ZapSign e confira o contrato por lá.` ou `a ZapSign não respondeu. Confira o contrato direto na ZapSign.`
- `nao_reconhecido`: `⚠️ Houve uma assinatura neste contrato, mas não foi possível identificar se quem assinou foi o lead. Confira na ZapSign.`
- Só o escritório assinou: `O escritório assinou o contrato. A assinatura do lead ainda está pendente.` (verificação: `O lead disse que assinou o contrato. Na ZapSign só consta a assinatura do escritório; a do lead ainda está pendente.`)
- Verificação, pendente: `O lead disse que assinou o contrato. Na ZapSign o contrato ainda está pendente de assinatura. A IA enviou o link de novo.`
- Problema recorrente do escritório: `\n\nPrimeiro aviso deste problema: dd/mm/aaaa hh:mm. Ocorrências desde então: N.`

## 9. Tratamento de erro

- **Nenhum nó derruba o fluxo** (`onError: continueRegularOutput` + `alwaysOutputData`): cada etapa
  confere `error` na saída da anterior e decide.
- **Única falha proposital**: `stopAndError` quando a ferramenta foi chamada com o lead fora das
  etapas `contratos`/`assinatura` ou com lead inexistente, para a IA receber erro e não falar nada.
- **Geração dupla**: reserva atômica (linha do lead travada, reserva de 3 min, índice único na versão);
  criação na ZapSign **sem** nova tentativa; dados iguais devolvem o mesmo link.
- **Falha da ZapSign**: classificada por causa (3.4); a linha fica `falhou` e a próxima chamada
  reaproveita a mesma versão. Só `fora_do_ar` "se resolve sozinho" (quando a IA chamar de novo); as
  demais pedem ação do escritório, com nota e alerta.
- **Gerou na ZapSign mas não gravou no banco**: alerta com o token do documento (para conserto manual).
- **Card/etiqueta/nota falharam**: 3 tentativas; contrato continua valendo; alerta se o card não moveu.
- **Assinatura**: sempre relê o documento; passagem para `assinado` é idempotente; assinatura de outro
  signatário não mexe no funil; assinante não identificado gera nota e alerta; versão substituída
  assinada gera nota.
- **Notas repetidas**: no máximo uma por lead e situação a cada 6 horas.
- **Histórico** (`contrato_evento`) falhou: a nota sai assim mesmo.
- Mensagens de erro técnico truncadas (300–400 caracteres) antes de gravar.

## 10. Diferenças relevantes em relação à versão antiga

| Tema | Antiga (`WEAVER - Contrato`) | Nova |
|---|---|---|
| Provedor | **ZapSign ou Tramitação Inteligente** (`Qual provedor?` por `api_key.nome` = `ZapSign`/`TramitaSign`) | **Só ZapSign** |
| Validação dos dados | Nenhuma: enviava o que a IA mandou | Normaliza, valida CPF, CEP, UF, e-mail; pede correção ao lead |
| Releitura da conversa | Só num caminho de **teste manual** (extrator com prompt mais detalhado: estado civil flexionado, nome com iniciais maiúsculas, telefone `(DD) 00000-0000`) | Na produção, só para os campos com erro |
| Corpo da ZapSign | Texto JSON com interpolação (aspas no dado quebravam o pedido); `signer_email` sempre, mesmo vazio | Objeto; e-mail só se houver |
| Data | `$now` no fuso do servidor | `America/Sao_Paulo` |
| Geração repetida | Bloqueava se a etapa já era `assinatura` ("O Contrato já foi realizado"); sem versão | Mesmo link para mesmos dados; versões até 3; reserva contra concorrência |
| Etapas aceitas | `contratos` ou `contrato` (pelo nome gravado no lead) | `contratos` ou `assinatura` (pelo **id** da etapa) |
| Registro do documento | Só `lead.id_contrato` | Ficha `contrato_documento` com versão, link, assinante, estado |
| Link inválido | Mandava `signers[0].sign_url` sem conferir | Confere token e link `http(s)` |
| Assinatura | Confiava no aviso: qualquer assinatura (inclusive a do **advogado**) movia o lead | Relê o documento e identifica o assinante que é o lead |
| Assinatura repetida | Checava etapa antes, sem atomicidade | Passagem atômica (`primeira_vez`) |
| Follow-up ao assinar | `BEGIN; DELETE ...` (apagava a fila) | Apaga `followups` e **cancela** a fila com motivo |
| Erros | Nós falhavam ou seguiam calados; sem alerta | Causa, responsável, nota ao escritório, alerta LawChat, histórico |
| Notificação "aguardando assinatura" | Nó `NotificaTrocaDeDepartamento` (desligado das conexões) | Não existe |
| Resumo | Agente fixo de auxílio-acidente ("UPDATE FUTURO", desligado; lia tabela de outro projeto) | Configurável por escritório, prompt e modelo editáveis |
| Vídeo pós-assinatura | Mesmo escritório fixo, espera padrão | Igual, espera de 3 s |
| Faxina do n8n | Nós que apagam execuções do próprio fluxo (soltos) | Não existe |
| Sobras soltas | Envio de contato via Z-API e via outro provedor, com token fixo no nó (`<SEGREDO: token Z-API>`, `<SEGREDO: token de outro provedor de WhatsApp>`), chamada a "99 - Verifica Contrato" (desligada) | Removidas |

O que a antiga tinha e a nova **não tem** (avaliar no sistema novo):
1. **Tramitação Inteligente** como segundo provedor: busca/cria cliente por CPF, gera um documento por
   modelo (lista de ids de modelo: configuração por escritório), cria envelope com o cliente como
   signatário, inclui os documentos, nomeia e envia o envelope, espera 30 s e lê o link. Bloqueava se
   algum modelo tivesse variável em branco (`template_usage.blank_variables`). Usava `Idempotency-Key`
   por execução em cada chamada (`<execution>-cliente`, `-doc-<modelo>`, `-envelope`, `-envio`).
   Gravava o id do cliente do provedor no lead. O DESENHO cita a Tramitação; a migração 002 só aceita
   `provedor = 'zapsign'`.
2. **Configuração rica do vínculo chave/modelo**: a consulta antiga lia de `api_key_atributos` também
   `template_nome`, `webhook_id`, `webhook_modelo`, `contrato_id`, `pos_assinatura_etapa`, `variaveis`
   e `mapeamento`. Ou seja, o Weaver já previa **mapeamento de variáveis e etapa pós-assinatura por
   escritório**, mas a nova versão usa mapeamento fixo no código. A tela nova deve recuperar isso.
3. **Webhook de notificação ao mudar para "aguardando assinatura"** (estava solto).
4. **Extrator completo** como alternativa de entrada (montava todos os dados a partir do lead e da
   conversa, sem a IA passar os campos): é o desenho que o sistema novo adota.

## 11. Como fica no sistema novo

### 11.1 Princípios

- **A IA não aciona a geração.** Os dados do contrato são fatos extraídos turno a turno (com o trecho
  que prova) e validados pelo código; quando estão completos e o lead **confirmou**, o turno enfileira
  a ação `gerar_contrato` (DESENHO 7.1 e 11.5: ações externas só depois da checagem de mensagem nova).
- Toda chamada à ZapSign e à Helena passa pelo **Executor** (`agentesia_acoes`), com as regras de
  tentativa que ele já tem.
- O webhook da ZapSign só **registra e enfileira**; quem decide é a releitura do documento.
- Mapeamento de variáveis, modelos, mensagens e efeitos no CRM são **configuração por escritório**
  (tela ZapSign + automações), não código.

Pré-requisitos no que já existe:
- `app/cerebro/auxilio_acidente.py`: `ETAPAS` ainda não tem `assinatura` nem `contrato_assinado`
  (o DESENHO 4.1 já prevê; `travas.ETAPAS_COM_DADOS` e `produto.etapas_com_dados_pessoais` já citam
  `assinatura`). `FATOS` não tem os campos do contrato. A instrução de `coleta_dados` em
  `app/cerebro/agente.py` diz "Não peça documentos por enquanto" e "a equipe vai dar sequência": precisa
  de uma versão para quando a função `contrato_zapsign` estiver ligada.
- Intenção `confirmou_dados` (DESENHO 7.1) ainda não existe em `INTENCOES`; `diz_que_assinou` já existe.
- `HelenaConta` não envia mensagem; o envio está em `ClienteHelena.enviar` (`app/canal/helena.py`).
  O Executor precisa dos dois.

### 11.2 Funções Python (assinaturas)

```python
# app/canal/zapsign.py  (mesmo padrão de helena_conta.py)
class ErroZapSign(Exception):
    """motivo: chave | pagamento | limite | modelo | dados | nao_encontrado | fora_do_ar"""
    def __init__(self, motivo: str, detalhe: str = "", status: int | None = None) -> None: ...

@dataclass(frozen=True)
class Assinante:
    token: str; nome: str; status: str; telefone: str | None
    link: str | None; assinou_em: datetime | None

@dataclass(frozen=True)
class DocumentoZapSign:
    token: str; status: str; arquivo_assinado: str | None; assinantes: list[Assinante]

class ZapSign:
    def __init__(self, token: str, url_base: str = "https://api.zapsign.com.br",
                 http: httpx.AsyncClient | None = None) -> None: ...
    async def criar_de_modelo(self, *, id_modelo: str, id_externo: str, nome: str,
                              telefone: str, email: str | None,
                              variaveis: list[tuple[str, str]], pais: str = "55") -> DocumentoZapSign:
        """POST /api/v1/models/create-doc. Erro HTTP vira ErroZapSign pelo status
        (401/403 chave, 402 pagamento, 429 limite, 400/404/422 modelo ou dados, 5xx/timeout fora_do_ar)."""
    async def documento(self, token_documento: str) -> DocumentoZapSign:
        """GET /api/v1/docs/{token}/"""
    async def modelos(self) -> list[dict[str, Any]]:
        """Lista de modelos da conta, para a tela e para testar o token (endpoint a confirmar na doc da ZapSign)."""
    async def variaveis_do_modelo(self, id_modelo: str) -> list[str]:
        """Variáveis do modelo, para montar o mapeamento (endpoint a confirmar)."""
```

```python
# app/contrato/dados.py  (funções puras, com teste)
CAMPOS_CONTRATO: tuple[str, ...]          # os 21 campos da seção 5 (sem DATA)
OBRIGATORIOS_PADRAO = ("nome", "cpf", "endereco", "numero", "bairro", "cidade", "estado", "cep")

@dataclass(frozen=True)
class CampoInvalido:
    campo: str; pedir: str                # "o seu CPF"...

def validar_dados(brutos: dict[str, Any], telefone_da_conversa: str | None,
                  obrigatorios: tuple[str, ...] = OBRIGATORIOS_PADRAO) -> tuple[dict[str, str], list[CampoInvalido]]: ...
def cpf_valido(valor: str) -> bool: ...
def hash_dados(dados: dict[str, str]) -> str:          # sha256 do JSON com chaves ordenadas
def montar_variaveis(dados: dict[str, str], mapeamento: list[dict[str, str]],
                     agora: datetime, fuso: str) -> list[tuple[str, str]]:
    """mapeamento: [{"variavel": "NOME", "campo": "nome"}, {"variavel": "DATA", "campo": "@data_geracao"},
    {"variavel": "Foro", "campo": "@fixo", "valor": "..."}]"""
def pedir_correcao(erros: list[CampoInvalido]) -> str: ...   # texto da seção 8.1

# app/contrato/assinatura.py  (puras)
def identificar_lead(doc: DocumentoZapSign, token_assinante: str | None,
                     telefone_lead: str | None) -> tuple[Assinante | None, str | None]:
    """token guardado > 8 últimos dígitos do telefone > assinante único. Devolve (assinante, como)."""
def situacao_da_assinatura(doc: DocumentoZapSign, lead: Assinante | None) -> str:
    """assinado | so_o_escritorio_assinou | pendente | nao_reconhecido"""
def causa_da_falha(erro: ErroZapSign) -> tuple[str, str, bool]:
    """(situacao, responsavel, repetir): fora_do_ar -> ('zapsign_fora_do_ar', 'provedor', True)..."""
```

```python
# app/contrato/servico.py  (banco + chamadas; usado pelo Executor)
@dataclass
class Reserva:
    decisao: str        # reservado | mesmo | gerando | limite | ja_assinado | etapa_errada | sem_integracao
    id_contrato: str | None; versao: int | None; link_atual: str | None; documentos_feitos: int

async def reservar_contrato(pool: asyncpg.Pool, *, id_escritorio: str, id_lead: str,
                            dados: dict[str, str], limite: int = 3,
                            reserva_minutos: int = 3) -> Reserva:
    """Port da A2 numa transação: SELECT ... FOR UPDATE no agentesia_leads, decide e insere/reaproveita
    a linha em agentesia_contratos (situacao 'reservado')."""

async def gerar_contrato(pool: asyncpg.Pool, zapsign: ZapSign, *, id_escritorio: str, id_lead: str,
                         config: dict[str, Any], fuso: str) -> ResultadoGeracao:
    """valida -> reserva -> escolhe modelo -> cria na ZapSign -> grava 'gerado' e substitui o anterior
    -> muda a etapa para 'assinatura'. Devolve situação, link, versão e o texto para o lead."""

async def processar_assinatura(pool: asyncpg.Pool, zapsign: ZapSign, *, id_escritorio: str,
                               id_contrato: str | None = None, token_documento: str | None = None,
                               origem: str = "zapsign") -> ResultadoAssinatura:
    """Relê o documento, identifica o lead e passa para 'assinado' com
    UPDATE agentesia_contratos ... WHERE situacao <> 'assinado' RETURNING (primeira_vez)."""
```

```python
# app/acoes.py: novos tipos no Executor
async def _gerar_contrato(self, contexto: dict[str, Any], dados: dict[str, Any]) -> dict[str, Any]: ...
async def _verificar_assinatura(self, contexto: dict[str, Any], dados: dict[str, Any]) -> dict[str, Any]: ...
async def _lembrar_assinatura(self, contexto: dict[str, Any], dados: dict[str, Any]) -> dict[str, Any]: ...
async def _enviar_mensagem(self, contexto: dict[str, Any], dados: dict[str, Any]) -> dict[str, Any]:
    """texto ou arquivo (vídeo pós-assinatura), via ClienteHelena.enviar; grava em agentesia_mensagens
    com autor 'automacao'."""
async def _resumir_contrato(self, contexto: dict[str, Any], dados: dict[str, Any]) -> dict[str, Any]: ...
# _contexto() passa a carregar também o token ZapSign do cofre (agentesia_integracoes tipo 'zapsign').
```

```python
# app/main.py: webhook
@app.post("/webhook/zapsign/{id_escritorio}")
async def webhook_zapsign(id_escritorio: str, pedido: Request) -> dict[str, Any]:
    """Confere o segredo (query ?segredo= ou cabeçalho, comparado com config.segredo_webhook do escritório),
    grava em agentesia_eventos_recebidos (origem 'zapsign', id_externo = '<token doc>:<event_type>:<token assinante>'),
    ignora evento que não é de assinatura ou documento desconhecido, enfileira verificar_assinatura
    (chave_unica 'zapsign:<token doc>:<token assinante>') e responde 200 na hora."""
```

```python
# app/contrato/lembretes.py
def agenda_de_lembretes(gerado_em: datetime, config: dict[str, Any], fuso: str) -> list[datetime]:
    """Horários dos lembretes (padrão sugerido: 2 h, 24 h, 72 h), só em horário comercial."""
async def agendar_lembretes_assinatura(pool: asyncpg.Pool, *, id_escritorio: str, id_lead: str,
                                       id_contrato: str, horarios: list[datetime]) -> None: ...
async def cancelar_lembretes_assinatura(pool: asyncpg.Pool, *, id_lead: str, motivo: str) -> int: ...
```

### 11.3 Tabelas e colunas `agentesia_` que faltam (migração 003)

`agentesia_contratos` (já existe na 002):

| Mudança | Para quê (nó de origem) |
|---|---|
| `id_assinante_externo text` | token do assinante (A5 `signer_token`, B4) |
| `id_modelo text` | modelo usado nesta versão (auditoria) |
| `lead_assinou_em timestamptz` | B5 (o `assinado_em` atual vira "documento concluído", ou renomear para `concluido_em`) |
| `concluido_em timestamptz` | todos assinaram |
| `arquivo_assinado text` | `signed_file` |
| `causa_erro text` | `pagamento`, `limite`, `chave`, `modelo`, `fora_do_ar` |
| `id_acao uuid references agentesia_acoes` | qual ação gerou (substitui `execution_id`) |
| `resumo text`, `resumo_erro text` | R8 (no lugar de `contrato_resumo`) |
| Índice `agentesia_contratos_um_vigente` | **Hoje impede a versão nova**: é único por lead com `situacao in ('reservado','gerado')`, e o fluxo precisa ter a versão anterior `gerado` (link ainda válido) enquanto a nova está `reservado`. Trocar por dois índices únicos: um `where situacao = 'reservado'` e outro `where situacao = 'gerado'`, e na gravação marcar a anterior `substituido` **antes** de pôr a nova em `gerado`, na mesma transação |

Outras:
- `agentesia_eventos_recebidos.origem`: incluir `'zapsign'` no `check`.
- `agentesia_integracoes` tipo `zapsign`: só `config` (seção 11.6); segredo no Vault como hoje.
- `agentesia_lead_fatos`: sem mudança de estrutura; novas chaves (`contrato.nome`, `contrato.cpf`...,
  ou sem prefixo, com `fonte` `extrator` ou `equipe`). A equipe pode corrigir um dado pelo painel.
- `agentesia_eventos`: substitui `contrato_evento`. Tipos sugeridos: `contrato_dado_invalido`,
  `contrato_zapsign_<causa>`, `contrato_sem_integracao`, `contrato_limite`, `contrato_nao_gravado`,
  `assinatura_nao_reconhecida`, `assinatura_versao_substituida`, `assinatura_sem_leitura`. A regra "uma
  nota por 6 h" e "primeiro aviso desde" vira consulta em `agentesia_eventos` (mesmo `tipo`, lead,
  `criado_em`).
- `agentesia_chamadas_ia`: registra a releitura e o resumo (papel `contrato_extrator`, `contrato_resumo`).
- Lembretes: usar a própria `agentesia_acoes` com `proxima_em` futura (tipo `lembrar_assinatura`) até
  existir a fila de follow-up (`agentesia_followups`, ainda em `db/rascunhos`).
- Provedor Tramitação: se for entrar, ampliar o `check (provedor in ('zapsign'))` e o `tipo` de
  integração; fora do escopo desta spec.

### 11.4 Ações do Executor e gatilhos

Fluxo de geração:

1. Turno em `coleta_dados`: o extrator grava os campos; o código valida (`validar_dados`). Faltando ou
   inválido → o agente da etapa pede (texto de `pedir`). Completo → o agente mostra o resumo dos dados
   e pede confirmação. Intenção `confirmou_dados` → enfileira
   `gerar_contrato` com `chave_unica = "<id_lead>:contrato:<hash_dados>"` (mesmos dados nunca enfileiram
   duas vezes) e `dados = {"dados": {...}, "hash": "..."}`.
2. `Executor._gerar_contrato`: `gerar_contrato(...)`. Resultado:
   - `gerado`/`mesmo`: enfileira `enviar_mensagem` com o link (seção 8.1), muda o lead para a etapa
     `assinatura` e dispara os gatilhos **`contrato_gerado`** e `etapa:assinatura`; agenda lembretes.
   - `zapsign_fora_do_ar` / erro de banco: levanta erro "repetível" → o Executor reagenda (1, 5, 30,
     120 min). Na **primeira** falha manda ao lead "Tive um imprevisto... vou tentar novamente"; na
     última vira evento e "nossa equipe vai te enviar o link".
   - causa do escritório (`chave`, `pagamento`, `limite`, `modelo`) ou `sem_integracao`: falha
     definitiva, evento com `responsavel = 'cliente'`/`'cadastro'`, nota no atendimento, mensagem
     "nossa equipe vai te enviar o link", gatilho **`contrato_falhou`**.
   - `limite`: evento `lead`, nota, mensagem da seção 8.1.
   - `ja_assinado`, `etapa_errada`: nada ao lead (etapa errada é evento `lawchat`, não deveria ocorrer).
3. A ZapSign é chamada **uma vez por tentativa**; se a ação morrer entre a criação e a gravação, a
   próxima tentativa encontra a reserva vencida e criaria outro documento. Mitigação: usar
   `external_id = id do contrato` (uuid da linha em `agentesia_contratos`, não o id do lead) e gravar o
   token do documento numa transação curta logo após a resposta.

Fluxo de assinatura:

1. `POST /webhook/zapsign/{id_escritorio}` → `verificar_assinatura` (`origem: 'zapsign'`).
2. Intenção `diz_que_assinou` no turno (etapa `assinatura`) → `verificar_assinatura`
   (`origem: 'verificacao'`, `chave_unica = "<id_lead>:<id_turno>:verificar"`). O texto ao lead sai da
   ação (seção 8.2), não da IA.
3. `Executor._verificar_assinatura`: `processar_assinatura(...)`. Se `primeira_vez`:
   lead → etapa `contrato_assinado` (estado `encerrado` ou IA desligada, conforme DESENHO), gatilhos
   **`contrato_assinado`** e `etapa:contrato_assinado`, `cancelar_lembretes_assinatura`, enfileira
   `enviar_mensagem` (vídeo opcional + 3 s + mensagem pós-assinatura), nota "Contrato assinado pelo
   lead.", `resumir_contrato` (se ligado). Só o escritório assinou → nota, nada mais. Não reconhecido /
   não leu → evento + nota (regra de 6 h).
4. Documento desconhecido (ex.: `external_id` de um lead do Weaver): `agentesia_eventos_recebidos.situacao
   = 'ignorado'`, sem efeito. Importante durante a migração, quando a mesma conta ZapSign pode ter
   documentos dos dois sistemas.

Gatilhos novos em `app/automacoes.py` (`GATILHOS_FIXOS`):

| Gatilho | Quando | Sugestão padrão (`sugestao_padrao`) |
|---|---|---|
| `contrato_gerado` | documento criado ou atualizado (versão nova) | coluna "Aguardando assinatura"; + `✍️ Etapa de Assinatura`; − `✅ Contrato Assinado`, `📄 Contrato em Elaboração`, `🛒 Comercial`, `📞 SDR`, `❌ Desqualificado`; nota "Contrato gerado (versão N). Acompanhar o lead até a assinatura." |
| `contrato_assinado` | o **lead** assinou, primeira vez | coluna "Contrato assinado"; + `✅ Contrato Assinado`; − `✍️ Etapa de Assinatura`; nota "Contrato assinado pelo lead." |
| `contrato_falhou` | falha definitiva na geração | nota do problema; transferir (opcional) |

`montar_acoes` hoje exige `id_turno` para a `chave_unica`; para gatilhos vindos do webhook usar
`chave = f"{id_lead}:{id_contrato}:{gatilho}"` (parâmetro `id_origem` no lugar de `id_turno`).
Para não mover o card duas vezes, ligar o CRM **ou** em `etapa:assinatura` **ou** em `contrato_gerado`
(a sugestão padrão usa os gatilhos de contrato e deixa os de etapa vazios).
`app/gestao/rotas.py`: `contrato_zapsign` passa a `"pronta": True` quando a integração estiver `ok`.

### 11.5 Lembretes de assinatura (novo; não existia no fluxo)

- Ao gerar: `agendar_lembretes_assinatura` cria ações `lembrar_assinatura` com `proxima_em` nos
  horários configurados (padrão sugerido: 2 h, 24 h, 72 h; só em horário comercial do escritório).
- Ao disparar: confere de novo (lead ainda em `assinatura`, contrato ainda `gerado` e é o vigente, IA
  ligada, lead não respondeu depois do agendamento), **relê o documento na ZapSign** (se já assinou,
  chama `processar_assinatura` e não lembra) e manda o texto configurado com o link.
- Ao assinar, ao gerar versão nova ou ao lead sair da etapa: `cancelar_lembretes_assinatura`
  (`update agentesia_acoes set situacao = 'cancelada' where tipo = 'lembrar_assinatura' and id_lead = $1
  and situacao = 'pendente'`).
- Canal oficial: lembrete depois de 24 h da última mensagem do lead exige modelo aprovado (DESENHO 11.6).

### 11.6 Tela Integrações > ZapSign

`agentesia_integracoes` (`tipo = 'zapsign'`), segredo no Vault, `config` sugerido:

```json
{
  "ambiente": "producao",
  "modelos": [
    {"id_modelo": "<configuração por escritório>", "nome": "Honorários auxílio-acidente",
     "id_agente": null, "padrao": true,
     "mapeamento": [{"variavel": "NOME", "campo": "nome"}, {"variavel": "DATA", "campo": "@data_geracao"}],
     "obrigatorios": ["nome", "cpf", "endereco", "numero", "bairro", "cidade", "estado", "cep"]}
  ],
  "limite_versoes": 3,
  "segredo_webhook_id_vault": "<SEGREDO: segredo do webhook>",
  "mensagens": {"link": "Segue o link de contrato:\n{link}", "nova_versao": "...", "pos_assinatura": "...",
                "lembrete": "..."},
  "midia_pos_assinatura": {"url": null, "espera_s": 3},
  "lembretes": {"ativo": true, "horas": [2, 24, 72]},
  "resumo": {"ativo": false, "prompt": "", "modelo": "gpt-4.1-mini"}
}
```

Partes da tela:
1. **Token**: campo mascarado (mostra os 4 últimos), botão "Testar" (lista modelos; grava `situacao`,
   `erro`, `testado_em`). Ambiente produção ou sandbox (host do sandbox a confirmar).
2. **Modelos**: lista vinda da ZapSign; escolher um modelo **padrão** do escritório e, opcionalmente,
   um por agente (mesma precedência do Weaver: agente > padrão).
3. **Mapeamento de variáveis**, por modelo: cada variável do modelo (lida da ZapSign ou digitada, texto
   exato) ligada a um campo do lead (os 21 da seção 5), à **data de geração** ou a um **texto fixo**;
   marcar quais campos são obrigatórios. Pré-preencher com o mapeamento da seção 5 quando os nomes
   coincidirem. Aviso para variável sem ligação (a Tramitação antiga bloqueava variável em branco).
4. **Depois da geração e da assinatura**: textos das mensagens (com `{link}`, `{versao}`), mídia
   pós-assinatura opcional, limite de versões, lembretes, resumo (prompt e modelo editáveis).
5. **Webhook**: URL para copiar (`https://<servidor>/webhook/zapsign/<id_escritorio>?segredo=...`),
   instrução de onde colar na ZapSign, botão "gerar novo segredo" e último aviso recebido.
6. **CRM e etiquetas**: não ficam aqui; ficam nas automações (`contrato_gerado`, `contrato_assinado`),
   com a sugestão padrão da seção 11.4.
7. Botão "Gerar contrato de teste" para um lead do modo teste (cria um documento real na conta).

### 11.7 O que descartar

- Tabelas do Weaver (`contrato_documento`, `contrato_evento`, `contrato_resumo*`, `card`, `etapas`,
  `tags`, `memoria`, `followups`...), ids de etiqueta por tabela (o sistema novo etiqueta por nome).
- Fluxos `AlertaLawchat` e `NotificaContratoAssinado`: viram `agentesia_eventos` (tela Erros) e
  gatilho `contrato_assinado` (nota/aviso; webhook do escritório quando existir a função "Chamar um
  webhook").
- Filtro de lead de teste por id fixo: o modo teste do agente já cobre.
- Escritório e vídeo fixos no código: viram `midia_pos_assinatura` na configuração.
- Webhook sem autenticação: o novo exige segredo e sempre relê o documento.

### 11.8 Testes sugeridos

- `validar_dados`: CPF com dígito errado, 11 dígitos iguais, CEP com 7 dígitos, UF inválida, nome com
  número, telefone com 55, telefone ausente (usa o da conversa), e-mail inválido, CPF do menor.
- `hash_dados`: mesma entrada em ordem diferente dá o mesmo hash.
- `reservar_contrato`: duas reservas simultâneas (só uma `reservado`), mesmos dados (`mesmo`), dados
  novos (versão 2, a 1 continua `gerado` até a 2 gravar), limite 3, reserva vencida reaproveitada.
- `identificar_lead`: por token, por telefone, assinante único, dois assinantes sem token e sem
  telefone (`nao_reconhecido`), só o escritório assinou.
- `processar_assinatura`: dois avisos ao mesmo tempo → efeitos uma vez só; versão substituída assinada.
- Webhook: segredo errado (401), evento que não é de assinatura (ignorado), documento de outro sistema.
- Executor: `fora_do_ar` reagenda e avisa o lead só uma vez; `chave` falha definitiva com evento
  `cliente`.
