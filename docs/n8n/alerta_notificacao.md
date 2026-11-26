# Especificação: fluxo n8n "WEAVER - Alerta Notificação"

Fonte: export `WEAVER - Alerta Notificação.json` (53 nós, ativo, tag "99 - Novo"). Lido em 22/11/2026 com script, sem `pinData` e sem segredos. Serve de guia para a reescrita em Python. Onde o fluxo tem defeito, a seção 9 descreve o defeito e a seção 10 diz o que fazer no lugar. Não é para reproduzir o defeito.

Convenção: `<SEGREDO: tipo>` marca um valor sensível que **não** foi copiado. A seção 7.4 diz onde cada um deve ficar.

---

## 1. Objetivo

O fluxo avisa a equipe do escritório por WhatsApp quando algo no atendimento precisa de uma pessoa. São três entradas independentes:

| Entrada | Quando dispara | O que faz |
|---|---|---|
| **A. Subfluxo chamado pelo agente** (Execute Workflow Trigger) | A IA principal decide que o lead precisa de humano (não sabe ler, quer áudio, videochamada, etc.) | Um **auditor** (LLM) confere no histórico se o aviso faz sentido. Se fizer: desliga a IA do lead, grava nota na Helena, envia o aviso aos números configurados e devolve à IA principal a mensagem que ela deve mandar ao lead. Se não fizer: devolve à IA principal o motivo e pede que continue normalmente. |
| **B. Webhook de troca de etapa** (`POST /NotificaTrocaDeDepartamento`) | O fluxo "Troca de Departamento" muda a etapa do lead | Traduz a etapa em tipo de evento, busca a notificação configurada, monta o texto e envia aos destinatários. Não tem auditor nem efeito no lead. |
| **C. Webhook da ZapSign** (`POST /NotificaContratoAssinado`) | A ZapSign avisa que um documento foi assinado | Confere que quem assinou foi o lead, busca o lead e envia o aviso "contrato assinado" aos destinatários. |

Nas três entradas, o texto do aviso e a lista de destinatários vêm da configuração que o escritório fez no app da plataforma (`sistemaia_notificacoes`).

---

## 2. Gatilhos e formato da entrada

### 2.A Execute Workflow Trigger ("When Executed by Another Workflow")

Entradas declaradas, todas texto:

| Campo | Conteúdo | Uso |
|---|---|---|
| `Número do Lead` | telefone do lead | casar com `lead.numero_telefone` / `origin_number` |
| `Nome do Lead` | nome | `{{nome}}` no aviso |
| `Link do Chat` | URL do atendimento na Helena | extrair `session_id` |
| `Tipo de Notificação` | código do aviso (ver 7.1) | escolher o auditor e a notificação |
| `Company ID` | `companyId` da Helena (uuid) | achar o escritório (`clientes.id_conta_helena`) |
| `Numero IA` | número do canal da IA | casar a conexão |
| `Mensagem` | última mensagem do lead | entra no fim do histórico enviado ao auditor |

**Saída para quem chamou:** o subfluxo devolve o item do último nó executado, um objeto `{ "Resposta": "<texto>" }` (ver seção 8). Quem chama é a ferramenta "Sistema Notificação" da IA principal (DESENHO.md, seção 7.1), que lê esse texto como resultado da ferramenta.

Extração do `session_id` (nó `extraindo_dados`), em ordem:
1. formato antigo: `[?&]id=([^&#]+)` (com `decodeURIComponent`);
2. formato novo: `/sessions?/([^/?#]+)` (sem diferenciar maiúsculas).
Se nenhum casar, `session_id = null`.

### 2.B Webhook `POST /NotificaTrocaDeDepartamento`

Não tem autenticação. O n8n responde 200 assim que recebe (modo padrão `onReceived`). Campos lidos de `body`, com alternativas na ordem:

| Parâmetro interno | Caminho(s) no `body` |
|---|---|
| etapa atual | `ProxAgente_Etapa` → `etapa_agente.etapa` |
| `id_conta` | `agente.conhecimento.id_conta` (calculado, mas **não usado** na busca; ver 9) |
| `api_lawchat` | `cliente.api_lawchat` (**é o token da Helena e chega no corpo**; ver 9) |
| conta para a busca | `cliente.id_ulid` |
| `id_canal` | `conexao.id_canal` |
| `numero_ia` | `numero_ia` → `Numero_ia` → `conexao.numero_telefone` |
| `numero_lead` | `Numero_cliente` → `Numero_lead` → `lead.numero_telefone` |
| `nome` | `nome` → `contato.user_name` |
| `produto` | `agente.conhecimento.category` |
| `data_evento` | `data` |
| `valor` | `lead.valor_do_contrato` → `valor` |
| `link_assinatura` | `link_assinatura` |

### 2.C Webhook `POST /NotificaContratoAssinado` (ZapSign)

Não tem autenticação nem conferência de assinatura do webhook. Campos lidos de `body`:

| Campo | Uso |
|---|---|
| `event_type` | só segue se for `doc_signed` |
| `signer_who_signed.email` | comparado ao do criador para ignorar a assinatura do escritório |
| `created_by.email` | e-mail do escritório que criou o documento |
| `signer_who_signed.name` | `{{nome}}` |
| `signer_who_signed.phone_country` + `phone_number` | telefone de reserva do lead |
| `signer_who_signed.signed_at` | `{{data_hora}}`, formatado em `dd/mm/aaaa hh:mm`, fuso America/Sao_Paulo |
| `external_id` | `lead.ulid` (uuid do lead no Weaver, gravado quando o contrato foi gerado) |

---

## 3. Lógica passo a passo

### 3.A Subfluxo do agente (auditor)

1. **Tira invalidos** (Filter, `OR`): `tipo != "qualificado"` OU `tipo == "periododegraca"` OU `tipo == "desqualificado"`. Na prática, **só barra `qualificado`**; as outras duas condições sobram.
2. **extraindo_dados**: calcula `session_id` (2.A).
3. **Clientes Selecionados?** (IF): se `Company ID` está na lista fixa (7.2, um único escritório):
   - sim → **analisehumana** (IF `tipo == "analisehumana"`): sim → passo 4; não → **fim, sem saída** (ramo falso sem ligação).
   - não → passo 4.
   - Efeito: para o escritório da lista só `analisehumana` passa, e `analisehumana` morre no Switch do passo 9. **Esse escritório não recebe nenhum aviso por essa entrada.**
4. **BUSCA ENTIDADES WEAVER** (Postgres, `alwaysOutputData`): uma linha com `notificacao`, `conexao`, `cliente`, `lead`, `agente`, `etapa` em JSON (ver 5.1).
5. **Filter1**: descarta item vazio. Se não sobrar nada, o fluxo termina sem saída.
6. **Reune os Itens - W** (Aggregate) + **Root Items - W** (Code): junta tudo em `data[]` e pega o primeiro objeto não vazio. Se não houver, termina sem saída.
7. **Baixar Memoria** (Postgres): até 15 linhas de `memoria` com `session_id = lead.ulid`. Sem `ORDER BY` (ver 9). Sem `alwaysOutputData`: **se não houver memória, o fluxo termina sem resposta**.
8. **Ordena Memoria Novo** (Code): ordena por `id` numérico. Acrescenta `Mensagem` (entrada) como última mensagem `{type:"human", content}` se não for vazia e se a última do histórico não for igual a ela. Depois **Summarize2** concatena o campo `message` de todas as linhas com `\n` em `concatenated_message`.
9. **Switch - Tipo de Notificação**: compara `Tipo de Notificação` (igualdade exata, diferencia maiúsculas) com 10 códigos (7.1). Cada saída vai para o seu auditor (seção 6). A saída "Não identificado" (`analisehumana`, `desqualificado`, `periododegraca` e qualquer outro) **não tem ligação, e o fluxo termina sem resposta**.
10. **Auditor** (agente LangChain, modelo da seção 6): entrada `"Conversa completa\n" + concatenated_message`; sai `output` em texto.
11. **Organiza a resposta** (Code): tira cercas ```json, recorta do primeiro `{` ao último `}`, faz `JSON.parse`. Produz `{tipo, validade, valido: validade=="valido", motivo, Mensagem (ou mensagem), parseOk, erroParse}`. Se o parse falhar, `valido=false`.
12. **A notificação veio errada?** (IF `valido == false`):
   - **Sim (inválida)** → **Contar Token SUBFLUXO** (chama o fluxo "99 - CONTAR TOKEN" sem esperar) → **Resposta caso errado** (Set) → fim. Saída: texto 8.1.
   - **Não (válida)** → passo 13.
13. **Desativa Weaver** (Supabase update): `lead.ia_ligada = false` onde `lead.ulid = <lead.ulid>`.
14. **I.A FOI DESATIVADA NOTA1** (HTTP): nota no atendimento da Helena (4.1): `A sua IA foi desativada com a notificação: <tipo>`. Se `tipo` estiver vazio, a expressão lança erro e o fluxo para.
15. **Tipo desqualificado? -- Filtro** (IF `tipo == "desqualificado"`): sim → NoOp (descarta). Não → passo 16. **O ramo "sim" nunca acontece**, porque `desqualificado` já saiu pelo fallback no passo 9.
16. **Verifica notificação ligada** (Code), sobre a linha do passo 4:
   1. notificação não encontrada (objeto vazio ou sem `id`/`tipo_evento`/`nome`) → item `{enviar:false, motivo:"notificacao_nao_encontrada"}`;
   2. desligada por algum campo `ativo|ativa|habilitado|habilitada|enabled|active|is_active` falso, ou `status` em `inativo|inativa|desabilitado|desabilitada|disabled|inactive|off` → `notificacao_desabilitada`;
   3. sem `modelo_mensagem` → `notificacao_sem_modelo`;
   4. monta os valores (7.3, coluna "A") e renderiza o modelo (regra 7.3);
   5. filtra destinatários (regra 7.3); se nenhum → `sem_destinatarios`;
   6. **um item por destinatário**: `{enviar:true, motivo:"ok", numero, label, mensagem, id_notificacao, tipo_evento, nome_evento}`.
17. **ENVIAR TEXTO ESCOLHENDO CANAL** (HTTP 4.2), **uma chamada por item**. Não há IF antes: os itens `enviar:false` também vão para o envio, com `to` indefinido (ver 9).
18. **Contar Token SUBFLUXO1** (sem esperar) → **Resposta caso a notificação tenha sido chamada** (Set) → fim. Saída: texto 8.1, um item por destinatário.

Repare na ordem: a IA do lead é desligada e a nota é gravada **antes** de conferir se o escritório configurou a notificação.

### 3.B Webhook de troca de etapa

1. **TRADUZ ETAPA + MONTA PARAMS** (Code): normaliza a etapa (sem acento, minúsculas, sem espaços) e traduz pelo mapa 7.1.B. Se a etapa não estiver no mapa, devolve zero itens e o fluxo termina (`console.log etapa_nao_mapeada`).
2. **BUSCA NOTIFICACAO** (Postgres, `alwaysOutputData`): 5.3, com `id_conta = body.cliente.id_ulid`.
3. **MONTA MENSAGEM** (Code): se não houver notificação ou `modelo_mensagem` → `{enviar:false, motivo:"notificacao_nao_encontrada_ou_desabilitada"}`. Senão renderiza (valores 7.3, coluna "B") e filtra os destinatários. Gera um item por destinatário, ou `sem_destinatarios`.
4. **IF ENVIAR** (`enviar == true`): sim → **ENVIAR TEXTO ESCOLHENDO CANAL1** (HTTP 4.3), uma chamada por destinatário. Não → fim.

### 3.C Webhook ZapSign

1. **EXTRAI DADOS ZAPSIGN** (Code):
   - `event_type != "doc_signed"` → `{enviar_evento:false, motivo:"evento_zapsign_ignorado: <tipo>"}`;
   - e-mail de quem assinou igual ao de `created_by` (sem diferenciar maiúsculas) → `{enviar_evento:false, motivo:"assinatura_do_escritorio_nao_do_lead"}`;
   - senão `{enviar_evento:true, id_lead: external_id, nome, numero_lead: phone_country+phone_number, data_evento}`.
2. **BUSCA CLIENTE POR LEAD ZAPSIGN** (Postgres, `alwaysOutputData`): 5.4. Roda **também** quando `enviar_evento=false`, com `id_lead` vazio, e então `''::uuid` dá erro (ver 9).
3. **MONTA PARAMS ZAPSIGN** (Code): evento ignorado → `enviar:false`; sem `id_conta` → `lead_nao_encontrado_no_banco`; senão `{tipo_evento:"contrato_assinado", etapa:"Contrato Assinado", id_conta, api_lawchat, id_canal, numero_ia, numero_lead (do banco, senão da ZapSign), nome (ZapSign), produto, data_evento, valor: lead.valor_do_contrato, link_assinatura:null}`.
4. **IF ENVIAR E ID CONTA**: `enviar !== false` E `id_conta` com formato de uuid → passo 5. Senão → NoOp "Lead não encontrado - encerra".
5. **BUSCA NOTIFICACAO1** (Postgres, `alwaysOutputData`): 5.3 com `id_conta` do passo 3. Os parâmetros voltam como colunas `_p_*`, porque o nó seguinte não lê o nó anterior.
6. **MONTA MENSAGEM1**: igual a 3.B passo 3, valores 7.3 coluna "C".
7. **IF ENVIAR1** → **ENVIAR TEXTO ESCOLHENDO CANAL2** (HTTP 4.3) → **Chegou Fim** (Stop and Error: `"Fim do aviso contrato weaver Alguem já chegou ?"`). **Toda execução bem-sucedida termina marcada como erro.** O nó parece ter ficado de uma depuração.

Não há esperas (`Wait`) nem laços explícitos. Os "laços" são o n8n rodando um nó uma vez por item, como no envio a cada destinatário.

---

## 4. Chamadas externas

Nas três entradas o host é a Helena, `https://api.helena.run`. O token da Helena vem do banco (`clientes.api_lawchat`) ou do corpo do webhook. Nenhum desses nós tem nova tentativa, timeout próprio ou tratamento de erro.

### 4.1 Nota no atendimento (entrada A, passo 14)
- `POST https://api.helena.run/chat/v1/session/{session_id}/note`
- Cabeçalhos: `Authorization` (= `<SEGREDO: token Helena do escritório>` **sem** o prefixo `Bearer`), `content-type: application/*+json`, `accept: application/json`.
- Corpo: `{ "text": "A sua IA foi desativada com a notificação: <tipo>" }`.
- Resposta: não é usada.
- O cliente novo já tem isso: `HelenaConta.nota(id_sessao, texto)`, que manda com `Bearer`.

### 4.2 Envio do aviso sem atendimento (entrada A, passo 17)
- `POST https://api.helena.run/chat/v1/message/send`
- Cabeçalhos: `Accept: application/json`, `Content-Type: application/json`, `Authorization: Bearer <SEGREDO: token Helena do escritório>`.
- Corpo:
  ```json
  { "from": "<conexao.numero_telefone>", "to": "<numero destinatário, 55+DDD+número>",
    "body": { "text": "<mensagem>", "refId": "<id da notificação>" },
    "options": { "enableBot": false, "hiddenSession": true } }
  ```
- Resposta: não é usada.
- O endpoint está em `docs/HELENA_API.md` ("Enviar sem atendimento"). O cliente novo ainda não tem esse envio.

### 4.3 Envio do aviso, outra rota (entradas B e C)
- `POST https://api.helena.run/chat/v1/send/text`
- Cabeçalhos: `Accept: application/json`, `Authorization: Bearer <SEGREDO: token Helena do escritório>`.
- Corpo (JSON):
  ```json
  { "from": "<numero_ia>", "to": "<numero destinatário>", "text": "<mensagem>",
    "senderId": "<id da notificação>", "options": { "enableBot": false, "hiddenSession": true } }
  ```
- Resposta: não é usada.
- Essa rota **não está** em `docs/HELENA_API.md`. A reescrita deve usar só a 4.2 e confirmar na documentação da Helena o que `hiddenSession` faz.

### 4.4 Subfluxo "99 - CONTAR TOKEN" (id n8n `f1OVqsz8objNYFsO`)
- Execute Workflow com `waitForSubWorkflow: false`. Envia `ExecutionId`, `executionMode`, `executionResumeUrl`, `$executionResumeFormUrl` e `Execution` (o objeto `$execution` inteiro), para o subfluxo somar os tokens desta execução.
- Resposta: não é usada.

### 4.5 OpenAI
- Pelo nó `lmChatOpenAi` (credencial `<SEGREDO: chave da API OpenAI>`), sem ferramentas. Ver seção 6.

---

## 5. Consultas ao banco

Todas usam o banco "Organização" (projeto Supabase AGENT WEAVER). Credenciais: `postgres` "Organização" (A) e "Organização - Transaction Pooler" (B, C), mais `supabaseApi` "Organização" para o update. **Todas as tabelas abaixo são do Weaver.** A coluna "Camada" diz se a tabela é da plataforma (`sistemaia_*`) ou do bot. Pela regra do projeto, **o sistema novo não lê nem grava nenhuma delas.**

Todas as consultas montam o SQL colando texto (`'{{ ... }}'::uuid`), sem parâmetros. Ver 9.

| Tabela | Camada | Colunas usadas | Para quê |
|---|---|---|---|
| `clientes` | bot (Weaver) | `id_ulid`, `id_conta_helena`, `api_lawchat` (token Helena) | Achar o escritório pelo companyId; token para a Helena |
| `lead` | bot (Weaver) | `ulid`, `id_cliente`, `numero_telefone`, `origin_number`, `id_agente`, `id_etapa_atual`, `id_conexao`, `valor_do_contrato`, `nome`, `numero_formatado`, `etapa_atual`, **`ia_ligada` (gravada)** | Achar o lead pelo telefone; dados do aviso; desligar a IA |
| `agentes` | bot (Weaver) | `id`, `conhecimento->>'category'` (produto), `conhecimento->>'id_conta'`, `numero_ia` | Produto no aviso; conta da plataforma (C) |
| `agente_etapas` | bot (Weaver) | `id`, `etapa` | Nome da etapa no aviso |
| `conexoes` | bot (Weaver) | `id`, `numero_telefone`, `id_canal` | Número que envia (`from`) e exclusão do próprio canal da lista de destinatários |
| `memoria` | bot (Weaver), formato do chat memory do n8n | `id`, `session_id` (= `lead.ulid`), `message` (`{type, content, ...}`) | Histórico para o auditor |
| `sistemaia_notificacoes` | plataforma (Weaver) | `id`, `id_conta`, `tipo_evento`, `nome`, `habilitada`, `modelo_mensagem`, `destinatarios` (jsonb `[{id, type:"phone", value, label}]`), `updated_at` | Configuração do aviso: texto e destinatários |
| `sistemaia_contas` | plataforma (Weaver) | `id`, `id_conta_helena` | Ligar o companyId à conta da plataforma (A) |

### 5.1 BUSCA ENTIDADES WEAVER (A)
Parâmetros: `company_id` (Company ID), `numero_ia`, `numero_lead`, `session_id`, `tipo_evento` (= Tipo de Notificação).
- `clientes c` com `c.id_conta_helena = company_id`;
- `lead l` com `l.id_cliente = c.id_ulid` e o telefone casando por igualdade em `numero_telefone`, igualdade em `origin_number` ou só dígitos de `numero_telefone`;
- `LEFT JOIN agentes`, `agente_etapas` (etapa atual);
- LATERAL `sistemaia_notificacoes` + `sistemaia_contas` com `sc.id_conta_helena = company_id`, `tipo_evento` igual e `habilitada`, a mais recente por `updated_at`;
- LATERAL `conexoes`: `co.id = l.id_conexao` ou só dígitos do número igual a `numero_ia`, dando preferência à do lead.
Devolve uma linha por lead que casar, com cada entidade em `to_jsonb`. Se houver mais de um lead com o mesmo telefone no escritório, vêm várias linhas, e o fluxo usa a primeira (sem ordem definida).

### 5.2 Baixar Memoria (A)
`SELECT * FROM memoria WHERE session_id = <lead.ulid> LIMIT 15`, sem ordem (ver 9).

### 5.3 BUSCA NOTIFICACAO / BUSCA NOTIFICACAO1 (B, C)
```sql
SELECT sn.* FROM sistemaia_notificacoes sn
WHERE sn.id_conta = $conta::uuid AND sn.tipo_evento = $tipo AND sn.habilitada
ORDER BY sn.updated_at DESC LIMIT 1;
```
Em B, `$conta` = `body.cliente.id_ulid` (id do `clientes` do bot). Em C, `$conta` = `agentes.conhecimento->>'id_conta'`. Os dois são ids diferentes e só funcionam se coincidirem (ver 9).

### 5.4 BUSCA CLIENTE POR LEAD ZAPSIGN (C)
`lead l JOIN clientes c ON c.id_ulid = l.id_cliente LEFT JOIN agentes a LEFT JOIN conexoes cx WHERE l.ulid = <external_id> LIMIT 1`. Devolve `numero_lead`, `valor_contrato`, `api_lawchat`, `id_conta`, `produto`, `id_canal`, `numero_ia`.

### 5.5 Desativa Weaver (A)
Supabase `update lead set ia_ligada = false where ulid = <lead.ulid>`.

---

## 6. Prompts de IA

- **Modelo:** `gpt-6-luna` (OpenAI, nó `lmChatOpenAi` v1.3, sem opções: temperatura e limite padrão). Um único modelo para os 10 auditores.
- **Mensagem do usuário:** `Conversa completa\n{{concatenated_message}}`. O histórico chega como concatenação do campo `message` da memória do n8n, sem papel legível nem horário (ver 9).
- **Saída esperada:** só um JSON, sem cerca de código:
  ```json
  { "tipo": "<código>", "validade": "valido|invalido",
    "motivo": "<1 a 2 frases explicando a decisão>", "Mensagem": "<mensagem ao lead>" }
  ```
- **Intenção:** um "auditor de qualidade" confere se o aviso que outra IA disparou faz sentido (na dúvida, inválido) e escreve a resposta ao lead nos dois casos. Se válido, a resposta diz que a equipe vai atender. Se inválido, a resposta segue a conversa sem falar em equipe.

### 6.1 Esqueleto comum (texto nosso, igual nos 10)

```
# PAPEL
Você é um auditor de qualidade do atendimento via WhatsApp de um escritório de advocacia previdenciária.
Outra IA disparou a notificação "<TÍTULO>", que <EFEITO>.
Sua função é: (1) verificar se essa notificação faz sentido e (2) escrever a mensagem que será enviada ao lead.

# PASSO 1 – VALIDAR
Leia todo o histórico, dando mais peso às mensagens mais recentes do lead.
<PREPARO opcional>
VALIDO quando ...: <lista>
INVALIDO quando ...: <lista>
Na dúvida, considere INVALIDO.

# PASSO 2 – ESCREVER A MENSAGEM PARA O LEAD
Sempre escreva uma mensagem que responda diretamente à ÚLTIMA mensagem do lead.
Se VALIDO: <orientação> [Referência de tom: "..."]
Se INVALIDO: <orientação>
- Não diga que a equipe vai assumir o atendimento.

# REGRAS DA MENSAGEM
- Português do Brasil, tom humano e acolhedor de WhatsApp.   (objeções e endereço: "tom humano, calmo e respeitoso")
- No máximo 2 frases.
- Não prometa prazos, valores ou resultados.                 (objeções: "prazos, valores, descontos ou resultados")
- Não diga que é uma IA e não use termos internos ("notificação", "grupo", "sistema", "válido").   (contrato manual: + "manual")

# FORMATO DE SAÍDA
Responda SOMENTE com este JSON, sem texto antes ou depois e sem ```json:
{ "tipo": "<código>", "validade": "<valido ou invalido>", "motivo": "<...>", "Mensagem": "<mensagem ao lead>" }
```

### 6.2 Partes de cada tipo

| Código | Título / efeito | VÁLIDO quando | INVÁLIDO quando | Se válido (tom) | Se inválido |
|---|---|---|---|---|---|
| `dificuldadenaassinatura` | "DIFICULDADE NA ASSINATURA": chama a equipe para ajudar a assinar | não consegue assinar; link não abre, deu erro ou expirou; não sabe como assinar ou pede ajuda; travou em selfie, foto do documento, código ou token | só não assinou ainda; vai assinar depois; já assinou; nem recebeu o link | "Entendi! Vou pedir para a nossa equipe te dar suporte na assinatura agora mesmo, tudo bem?" | conduzir ao próximo passo da assinatura; se já assinou, agradecer e dizer que a equipe vai conferir |
| `fotodocontrato` | "FOTO DO CONTRATO IDENTIFICADA": equipe confere a documentação | enviou foto, print ou arquivo do contrato (ou de uma página); disse claramente que acabou de enviar | não houve imagem nem arquivo; o que mandou não é o contrato (selfie, figurinha, comprovante sem relação); só falou do contrato | "Recebi a foto do contrato! Vou pedir para a nossa equipe verificar por aqui e já te retorno, combinado?" | se mandou outra coisa, agradecer e explicar o que falta; senão seguir a conversa |
| `naosabeler` | "CLIENTE QUE NÃO SABE LER": equipe atende por áudio | diz que não sabe ler ou é analfabeto; tem muita dificuldade para ler; não enxerga bem; precisa de alguém para ler | só não leu ou vai ler depois; texto grande ou sem tempo; só mandou áudios | "Sem problema! Vou verificar aqui para te enviar um áudio explicando tudo direitinho, tá bom?" (frases MUITO curtas, palavras simples) | seguir a conversa; se o texto era grande, oferecer resumo |
| `clienteantigo` | "CLIENTE ANTIGO": encaminha ao setor operacional | já é cliente do escritório; já tem processo ou contrato; já assinou antes; pergunta do andamento de processo existente | só conhece o escritório ou viu anúncio; é cliente de OUTRO escritório; pedido direto no INSS; nenhum sinal de vínculo | "Perfeito! Nosso setor operacional vai entrar em contato com você para te ajudar, tudo certo?" (compreensão sem excesso de desculpas; não informar andamento) | seguir a conversa |
| `outrobeneficio` | "LEAD REQUER CONVERSA DE OUTRO BENEFÍCIO": chama especialista. Preparo: identificar o benefício da conversa | pede benefício DIFERENTE (ex.: conversa de BPC/LOAS e pergunta de aposentadoria, auxílio-doença, pensão, salário-maternidade); diz que quer outro | mesmo benefício com outro nome ("LOAS" e "BPC"); dúvida genérica; só comentou que recebe ou recebeu outro | "Entendi! Vou solicitar para a nossa equipe responsável por esse benefício para entender melhor o seu caso, combinado?" (pode citar o benefício; não dizer se tem direito) | retomar o benefício que estava em conversa |
| `videochamada` | "LEAD SOLICITOU VÍDEO CHAMADA": agendar com prioridade | pede chamada de vídeo; quer "ver" alguém ou falar "olhando no rosto"; aceitou claramente uma oferecida | pediu só áudio; foi sugerida e não aceitou ou não respondeu; nenhuma menção | "Claro, conseguimos fazer a vídeo chamada sim! Qual o melhor dia e horário para você? Assim já deixo agendado com a nossa equipe." Se já deu dia e hora: repetir e dizer que a equipe confirma, sem garantir | seguir a conversa; não oferecer videochamada |
| `leadquerreceberaudio` | "O LEAD QUER RECEBER ÁUDIO": equipe explica por áudio | pede áudio ("manda um áudio", "explica por áudio"); prefere áudio; não acompanha bem por texto | só ENVIOU áudios; o motivo real é não saber ler (dizer no motivo que o tipo certo seria `naosabeler`); nenhum pedido | "Certo! Vou verificar por aqui para te enviar um áudio explicando melhor o seu caso, tudo bem?" (se citou um ponto, dizer que o áudio cobre esse ponto) | responder, inclusive ao conteúdo do áudio transcrito |
| `muitasobjecoes` | "LEAD COM MUITAS OBJEÇÕES": humano contorna a resistência. Preparo: listar objeções (golpe, desconfiança, honorários, "vou pensar", família, "já tentei", documentos) | 2 ou mais objeções diferentes e segue resistente; OU repetiu a mesma depois de respondido | dúvida pontual já esclarecida; perguntas normais de interesse; já aceitou seguir | "Entendo suas dúvidas! Vou pedir para um especialista da nossa equipe falar com você e esclarecer tudo direitinho, pode ser?" (sem discutir nem pressionar; medo de golpe: segurança sem exagero) | responder à dúvida e seguir |
| `enderecosemfalar` | "OBJEÇÃO DE ENDEREÇO SEM FALAR": lead não quer dar endereço | recusou; desviou e não informou; questionou o motivo sem fornecer | já informou (mesmo incompleto); ainda não foi pedido; só pediu tempo para buscar | respeitar sem pressionar, dizer que os dados servem só para o processo e que alguém da equipe vai explicar (sem frase de referência) | seguir; se pediu tempo, dizer que pode mandar quando puder |
| `contratomanual` | "NECESSÁRIO REALIZAR CONTRATO MANUALMENTE": contrato fora do fluxo automático | pediu contrato físico ou impresso; assina representante legal, curador, procurador ou responsável por menor; não consegue assinatura digital de jeito nenhum (sem celular compatível, sem e-mail, sem documento com foto); dados fora do padrão (falta CPF, nome divergente) | o fluxo automático ainda é possível; dificuldade pontual no link (isso seria `dificuldadenaassinatura`) | dizer que a equipe vai preparar o contrato do jeito certo para o caso e entrar em contato | seguir com o fluxo normal de assinatura |

O campo `motivo` pede, conforme o tipo, "citando o que o lead disse", "disse ou enviou", "o benefício da conversa e o que o lead pediu", "as objeções que o lead apresentou" ou "o impedimento encontrado".

---

## 7. Constantes fixas

### 7.1 Códigos
**A. `Tipo de Notificação` (entrada A).** Com auditor: `dificuldadenaassinatura`, `fotodocontrato`, `naosabeler`, `clienteantigo`, `outrobeneficio`, `videochamada`, `leadquerreceberaudio`, `muitasobjecoes`, `enderecosemfalar`, `contratomanual`. Barrado: `qualificado`. Sem destino (fallback): `analisehumana`, `desqualificado`, `periododegraca`. Esse mesmo código é o `tipo_evento` procurado em `sistemaia_notificacoes`.

**B. Etapa → evento (entrada B)**, depois de normalizar:

| Etapa (normalizada) | `tipo_evento` | Nome usado em `{{etapa}}` |
|---|---|---|
| `closer` | `lead_qualificado` | Qualificado |
| `coletadedados` | `lead_iniciou_coleta` | Coleta de Dados |
| `contratos` | `aguardando_assinatura` | Aguardando Assinatura |
| `contratoassinado` | `contrato_assinado` | Contrato Assinado |

**C. ZapSign:** `tipo_evento = contrato_assinado`, `etapa = "Contrato Assinado"`, só para `event_type = doc_signed`.

### 7.2 Ids
- Lista "Clientes Selecionados?": `['7232ea53-01f7-4e08-b5cc-20642c4de0e1']` (companyId Helena de um escritório; a nota do nó traz o nome).
- Subfluxo de tokens: `f1OVqsz8objNYFsO` ("99 - CONTAR TOKEN").
- Caminhos de webhook: `NotificaTrocaDeDepartamento`, `NotificaContratoAssinado`.
- Modelo: `gpt-6-luna`.

### 7.3 Modelo de mensagem do aviso
O texto vem de `sistemaia_notificacoes.modelo_mensagem`, escrito pelo escritório. Marcadores: `{{nome}} {{telefone}} {{produto}} {{etapa}} {{data_hora}} {{valor}} {{link_assinatura}} {{origem}} {{resumo}} {{primeira_mensagem}} {{forma_pagamento}} {{parcelas}}`.

**Regra de render (igual nos três caminhos):** o texto é tratado linha a linha. Linha sem marcador fica como está. Linha com marcador vazio (`null`, `undefined` ou só espaços) **some inteira**. Nas outras, cada `{{ chave }}` (aceita espaços) vira o valor. Depois, 3 ou mais `\n` seguidos viram 2, e o texto é aparado.

**Valores por caminho:**

| Marcador | A (agente) | B (troca de etapa) | C (ZapSign) |
|---|---|---|---|
| `nome` | `Nome do Lead` → `lead.nome` | `body.nome` → `contato.user_name` | `signer_who_signed.name` |
| `telefone` | `lead.numero_formatado` → formatado de `lead.numero_telefone` | formatado de `numero_lead` | formatado de `numero_lead` |
| `produto` | `agente.conhecimento.category` | `agente.conhecimento.category` | idem, do banco |
| `etapa` | `agente_etapas.etapa` → `lead.etapa_atual` | nome do mapa 7.1.B | "Contrato Assinado" |
| `data_hora` | agora | `body.data` → agora | `signed_at` → agora |
| `valor` | `lead.valor_do_contrato` | `lead.valor_do_contrato` → `valor` | `lead.valor_do_contrato` |
| `link_assinatura` | vazio | `body.link_assinatura` | vazio |
| `origem` | formatado de `lead.origin_number` | vazio | vazio |
| `resumo`, `primeira_mensagem`, `forma_pagamento`, `parcelas` | vazio | vazio | vazio |

"agora" = `dd/mm/aaaa, hh:mm` em `pt-BR`, fuso `America/Sao_Paulo`.

**Funções de número:**
- `normalizaNumero(v)`: só dígitos; vazio → `null`; até 11 dígitos → prefixa `55`; mais que isso fica como está.
- `formataTelefone(v)`: só dígitos, tira o `55` do início; 11 dígitos → `(DD) NNNNN-NNNN`; 10 → `(DD) NNNN-NNNN`; senão devolve o valor original.

**Destinatários:** de `notificacao.destinatarios`, ficam os itens com `type == "phone"` e `value` preenchido que **não** sejam o próprio canal. É canal quando o item não tem `id`, quando o `label` começa com `Canal:` (sem diferenciar maiúsculas) ou quando o número normalizado é igual ao do canal (`conexao.numero_telefone`, senão `agente.numero_ia` em A; `numero_ia` em B e C). Números repetidos saem. O que se guarda é `{label, numero normalizado}`.

### 7.4 Segredos (não copiados)
| Onde aparecia | O quê | Onde deve morar |
|---|---|---|
| `Authorization` dos três nós HTTP | `<SEGREDO: token Helena do escritório>`, lido de `clientes.api_lawchat` ou de `body.cliente.api_lawchat` | Supabase Vault, referência em `agentesia_integracoes (tipo='helena').id_segredo_vault`, lido pelo `Executor._contexto` (já é assim) |
| Credencial `openAiApi` "Weaver" | `<SEGREDO: chave da API OpenAI>` | Variável de ambiente do servidor (`OPENAI_API_KEY`, já usada por `app/modelo.py`) ou integração `openai` do escritório no Vault |
| Credenciais `postgres` e `supabaseApi` "Organização" | `<SEGREDO: conexão Postgres / chave Supabase do Weaver>` | Não se aplica: o sistema novo não acessa o Weaver. A conexão própria fica no env (`DATABASE_URL`) |
| Webhook ZapSign (não existe hoje) | `<SEGREDO: segredo do webhook ZapSign>` | Vault, `agentesia_integracoes (tipo='zapsign')` |

---

## 8. Saídas e efeitos colaterais

### 8.1 Textos devolvidos à IA principal (entrada A)
- Inválida: `O atendimento não foi desativado pelo motivo a seguir:\n{{motivo}}\n\nContinue o atendimento normalmente ignorando essa resposta`
- Válida e enviada: `Enviar para o lead a mensagem:\n{{Mensagem}}`, um item por destinatário com o mesmo texto.
- Sem resposta definida (a IA principal fica sem retorno claro): tipo no fallback, escritório da lista, lead não encontrado, memória vazia.

### 8.2 Efeitos
| Efeito | Entrada | Condição |
|---|---|---|
| `lead.ia_ligada = false` (Weaver) | A | auditor disse válido |
| Nota na sessão da Helena "A sua IA foi desativada com a notificação: X" | A | auditor disse válido |
| WhatsApp aos destinatários pela Helena (sessão oculta, bot desligado) | A, B, C | notificação habilitada, com modelo e com destinatário |
| Execução do "99 - CONTAR TOKEN" | A | sempre que o auditor roda (uma vez por item no ramo válido) |
| Execução marcada como erro ("Chegou Fim") | C | sempre que o aviso é enviado |

A mensagem ao lead **não é enviada por este fluxo**: ela volta como texto e a IA principal decide se manda.

---

## 9. Tratamento de erro e defeitos encontrados

Nenhum nó tem `retryOnFail`, `onError` ou fluxo de erro. Qualquer falha de HTTP ou SQL para a execução, e nos webhooks o remetente já recebeu 200. Pontos a não repetir:

1. **Envio sem IF em A:** itens `enviar:false` (notificação ausente, desligada, sem modelo ou sem destinatário) vão para o HTTP com `to` indefinido. A Helena devolve erro, a execução para e a IA principal recebe erro. Isso acontece depois que a IA já foi desligada e a nota gravada.
2. **Ordem dos efeitos em A:** desliga a IA e grava a nota antes de saber se dá para avisar alguém. O lead fica sem IA e sem humano avisado.
3. **Fallback sem ligação:** `analisehumana`, `desqualificado` e `periododegraca` passam pelo filtro e pela busca, mas morrem no Switch. O IF "Tipo desqualificado?" e o IF "analisehumana" não têm efeito.
4. **Escritório fixo no código:** "Clientes Selecionados?" deixa o escritório da lista sem nenhum aviso por A.
5. **Memória sem ordem:** `LIMIT 15` sem `ORDER BY` pega 15 linhas quaisquer, não as últimas. Com memória vazia, o fluxo para sem resposta.
6. **Histórico ilegível:** `Summarize` concatena o objeto `message` (`{type, content, ...}`). O auditor não recebe "lead:" e "IA:" de forma clara, nem horários.
7. **JSON por texto:** o modelo devolve texto livre e o parse é manual. Se falhar, a notificação vira "inválida" sem registro do motivo.
8. **SQL por concatenação:** os parâmetros são colados dentro de aspas. Um nome com apóstrofo quebra a consulta, e o caminho abre espaço para injeção (os webhooks não têm autenticação).
9. **Token no corpo do webhook B** (`cliente.api_lawchat`) e webhooks sem autenticação. Qualquer um que conheça a URL dispara WhatsApp em nome do escritório.
10. **Conta inconsistente:** B usa `cliente.id_ulid` como `sistemaia_notificacoes.id_conta`, C usa `agentes.conhecimento.id_conta`, A passa por `sistemaia_contas.id_conta_helena`. Três chaves para a mesma coisa.
11. **ZapSign:** evento ignorado ainda executa a consulta com `''::uuid` e dá erro. "Chegou Fim" marca toda execução como erro. Não há idempotência: a ZapSign reenviando o mesmo evento gera aviso duplicado.
12. **Dois endpoints de envio** (`message/send` com `body.text`/`refId` e `send/text` com `text`/`senderId`). Só o primeiro está documentado.
13. **Nota com `Authorization` sem `Bearer`**, ao contrário dos outros nós.
14. **Leads com o mesmo telefone:** a busca de A pode trazer vários, e o fluxo usa o primeiro sem ordem.
15. **Contagem de tokens** depende de um subfluxo que lê `$execution` e não fica ligada ao lead.

---

## 10. Como fica no sistema novo

O fluxo vira três peças: (1) o **auditor** dentro do turno, que confirma o sinal do extrator antes de pausar; (2) a ação **`notificar`** no Executor, que envia o aviso configurado a cada destinatário, com novas tentativas; (3) uma **rota da ZapSign** que grava o evento e enfileira o aviso. Nada lê nem grava tabela do Weaver. A configuração dos avisos passa a ter tabela própria `agentesia_`.

### 10.1 Códigos novos (mapa do legado)

| Código antigo | Sinal no extrator (`produto.sinais`) | `tipo_evento` do aviso |
|---|---|---|
| `naosabeler` | `nao_sabe_ler` (já existe) | `nao_sabe_ler` |
| `leadquerreceberaudio` | `quer_audio` (já existe) | `quer_audio` |
| `videochamada` | `quer_videochamada` (já existe) | `quer_videochamada` |
| `clienteantigo` | `cliente_antigo` (já existe) | `cliente_antigo` |
| `outrobeneficio` | `outro_beneficio` (já existe) | `outro_beneficio` |
| `dificuldadenaassinatura` | `dificuldade_assinatura` (novo) | `dificuldade_assinatura` |
| `fotodocontrato` | `foto_contrato` (novo; também pode vir da mídia recebida na etapa de contrato) | `foto_contrato` |
| `muitasobjecoes` | `muitas_objecoes` (novo) | `muitas_objecoes` |
| `enderecosemfalar` | `endereco_sem_falar` (novo) | `endereco_sem_falar` |
| `contratomanual` | `contrato_manual` (novo) | `contrato_manual` |
| troca de etapa `closer` / `coleta_dados` / `contratos` / `contrato_assinado` | gatilho `etapa:<codigo>` (já existe em `automacoes.gatilhos_do_turno`) | `lead_qualificado` / `lead_iniciou_coleta` / `aguardando_assinatura` / `contrato_assinado` |
| `analisehumana` | resultado `analise_manual` do `decidir_etapa` (já gera evento em `turno.py`) | `analise_manual` (hoje não avisa ninguém; passa a avisar se o escritório configurar) |
| `desqualificado`, `periododegraca` | etapa decidida pelo código | `etapa:desqualificado`, `etapa:periodo_graca`, se o escritório quiser aviso |

### 10.2 Módulo novo `app/notificacoes.py` (funções puras e leitura da configuração)

```python
EVENTO_POR_ETAPA: dict[str, str]        # {"closer": "lead_qualificado", "coleta_dados": "lead_iniciou_coleta", ...}
EVENTO_POR_SINAL: dict[str, str]        # identidade hoje; separado para permitir renomear
MARCADORES: tuple[str, ...]             # nome, telefone, produto, etapa, data_hora, valor, link_assinatura, origem, resumo, ...

@dataclass
class Destinatario:
    rotulo: str
    numero: str                         # só dígitos, com 55

def normalizar_numero(valor: str | None) -> str | None: ...
def formatar_telefone(valor: str | None) -> str: ...
def renderizar_modelo(modelo: str, valores: Mapping[str, Any]) -> str: ...
    # regra 7.3: linha com marcador vazio some; \n{3,} -> \n\n; strip
def filtrar_destinatarios(itens: list[dict[str, Any]], numero_canal: str | None) -> list[Destinatario]: ...
    # tira o próprio canal e repetidos; só type == "phone"
def valores_do_aviso(*, lead: Mapping[str, Any], contato: Mapping[str, Any], agente: Mapping[str, Any],
                     etapa: str | None, contrato: Mapping[str, Any] | None,
                     resumo: str | None, agora: datetime, fuso: str) -> dict[str, Any]: ...
async def carregar_notificacao(pool: asyncpg.Pool, id_escritorio: str, tipo_evento: str) -> dict[str, Any] | None: ...
async def acoes_de_aviso(pool: asyncpg.Pool, *, id_escritorio: str, id_lead: str, id_turno: str | None,
                         tipo_evento: str, valores: Mapping[str, Any], numero_canal: str,
                         chave_base: str) -> tuple[list[dict[str, Any]], str | None]: ...
    # devolve (ações 'notificar' uma por destinatário, motivo quando não há envio:
    #  'notificacao_nao_configurada' | 'notificacao_desligada' | 'sem_modelo' | 'sem_destinatarios')
```

`acoes_de_aviso` **não envia nada**: só monta as linhas para `agentesia_acoes`. Quando não há envio, quem chama grava o motivo em `agentesia_eventos` (gravidade `aviso`, responsável `cadastro`). Assim, "escritório não configurou o aviso" aparece no painel em vez de virar erro de HTTP.

### 10.3 Auditor: módulo novo `app/cerebro/auditor.py` (função do agente)

```python
PROMPTS: dict[str, str]                 # um por sinal, montado do esqueleto 6.1 + partes 6.2
ESQUEMA = {                             # saída estruturada; acaba o parse manual
    "type": "object", "additionalProperties": False,
    "properties": {"valido": {"type": "boolean"}, "motivo": {"type": "string"},
                   "mensagem": {"type": "string"}},
    "required": ["valido", "motivo", "mensagem"]}

@dataclass
class Auditoria:
    sinal: str
    valido: bool
    motivo: str
    mensagem: str
    chamadas: list[Chamada]

def sistema_do_auditor(sinal: str, *, escritorio: str, produto: Any) -> str: ...
def conteudo_do_auditor(historico: list[dict[str, Any]], novas: list[str]) -> str: ...
    # "lead: ..." / "ia: ..." com horário, as N últimas em ordem (corrige 9.5 e 9.6)
async def auditar_sinal(modelo: Modelo, *, sinal: str, historico: list[dict[str, Any]], novas: list[str],
                        nome_modelo: str, escritorio: str, produto: Any, esforco: str = "low") -> Auditoria: ...
    # usa Modelo.gerar(papel="auditor", ...); a chamada vai para agentesia_chamadas_ia
```

**Entrada no turno** (`app/cerebro/turno.py`, bloco `if extracao.sinais:`):
1. Para cada sinal, chamar `auditar_sinal`. Ficam só os válidos.
2. Nenhum válido: registrar evento `sinal_recusado` (gravidade `info`, com `motivo`) e **seguir o turno normal** (equivale ao "Continue o atendimento normalmente").
3. Algum válido: `estado_lead="pausado"`, `motivo_estado="sinal:<códigos>"`. A mensagem ao lead passa a ser a `mensagem` do auditor no lugar de `_fixa(entrada, "sinal")`. A fixa fica como reserva se o auditor falhar. O evento continua `sinal_<código>`.
4. Se o auditor falhar (`ErroModelo`): tratar o sinal como **válido**, usar a mensagem fixa e registrar `auditor_falhou`. Errar para o lado de chamar humano é mais seguro que ignorar.
5. Modelo do auditor: `config.modelo_auditor` do agente, com padrão em `app/config.py`. O legado usa `gpt-6-luna`.

O auditor só entra quando `produto.sinais` tem o código. Os 5 sinais novos precisam ser acrescentados a `auxilio_acidente.SINAIS` e à descrição do extrator.

### 10.4 Automações e Executor

**`app/automacoes.py`**
- `gatilhos_do_turno`: além de `"sinal"`, emitir `f"sinal:{codigo}"` para cada sinal válido. `etapa:<codigo>` já existe.
- `montar_acoes(...)`: quando `funcoes["avisos"]` está ligado e o gatilho tem `tipo_evento` (por `EVENTO_POR_ETAPA`/`EVENTO_POR_SINAL` ou pelo campo novo `notificar` da regra), acrescentar um pedido `{"tipo": "preparar_aviso", "chave_unica": f"{chave}:aviso", "dados": {"tipo_evento": ..., "valores": {...}}}`. Acrescentar `"notificar"` em `CAMPOS` para o escritório escolher o evento por gatilho.
- A nota "A sua IA foi desativada com a notificação: X" vira a `nota` da regra `sinal:<codigo>` em `sugestao_padrao`, com esse texto como padrão.

**`app/acoes.py`** (novos tipos no Executor)
```python
async def _preparar_aviso(self, contexto: dict[str, Any], dados: dict[str, Any]) -> dict[str, Any]: ...
    # lê agentesia_notificacoes, renderiza, filtra destinatários e insere uma ação 'notificar'
    # por destinatário (chave_unica = f"{id_acao}:{numero}"); motivo sem envio -> agentesia_eventos
async def _notificar(self, contexto: dict[str, Any], dados: dict[str, Any]) -> dict[str, Any]: ...
    # dados = {"de": numero_canal, "para": numero, "texto": ..., "id_notificacao": ...}
    # chama HelenaConta.enviar_sem_atendimento; devolve {"id_mensagem": ...}
```
Acrescentar `"preparar_aviso": "preparar o aviso à equipe"` e `"notificar": "enviar o aviso à equipe"` em `DESCRICOES`. Ganha de graça: novas tentativas (1, 5, 30, 120 min), evento na última falha e `chave_unica` contra envio duplicado. Separar em duas etapas faz a tentativa repetir só o número que falhou.

**`app/canal/helena_conta.py`** (método novo)
```python
async def enviar_sem_atendimento(self, *, de: str, para: str, texto: str,
                                 ref_id: str | None = None) -> str | None: ...
    # POST chat/v1/message/send
    # {"from": de, "to": para, "body": {"text": texto, "refId": ref_id},
    #  "options": {"enableBot": False, "hiddenSession": True}}
```
Em canal oficial (`agentesia_canais.tipo = 'oficial'`), conversa nova com número da equipe só abre com modelo aprovado (HELENA_API.md). Até haver suporte a modelo, `_notificar` deve falhar de forma definitiva com `ErroDeCadastro("canal oficial exige modelo aprovado")`.

**Desligar a IA:** não existe mais `ia_ligada` no lead. Quem faz isso é `estado='pausado'` + `motivo_estado` em `agentesia_leads`, que o pipeline já grava com o resultado do turno. Não há update à parte.

### 10.5 ZapSign: rota e módulo novos

- `app/main.py`: `@app.post("/webhook/zapsign/{id_escritorio}")`, com conferência do segredo do escritório (cabeçalho ou token na URL, guardado no Vault por `agentesia_integracoes tipo='zapsign'`).
- Módulo novo `app/contratos_eventos.py`:
  ```python
  async def receber_zapsign(pool: asyncpg.Pool, id_escritorio: str, corpo: dict[str, Any]) -> str: ...
      # 1. grava em agentesia_eventos_recebidos (origem 'zapsign', id_externo = token do doc + evento) -> idempotente
      # 2. ignora event_type != 'doc_signed' e assinatura do próprio escritório (e-mail = created_by.email)
      # 3. acha agentesia_contratos por (provedor='zapsign', id_documento_externo); reserva: external_id = agentesia_leads.id
      # 4. marca o contrato 'assinado' (assinado_em = signed_at) e enfileira 'preparar_aviso' com tipo_evento 'contrato_assinado'
      # devolve a situação: 'processado' | 'ignorado:<motivo>'
  ```
- A troca de etapa para `contrato_assinado` e o desligamento da IA são a ação `contrato_assinado` do DESENHO (7.3) e ficam fora desta spec. Aqui entra só o aviso.

### 10.6 Tabelas e colunas `agentesia_` que faltam

```sql
-- Configuração dos avisos por escritório (substitui sistemaia_notificacoes, sem ler o Weaver)
create table public.agentesia_notificacoes (
  id               uuid primary key default gen_random_uuid(),
  id_escritorio    uuid not null references public.agentesia_escritorios(id) on delete cascade,
  tipo_evento      text not null,          -- nao_sabe_ler, lead_qualificado, contrato_assinado...
  nome             text not null,
  habilitada       boolean not null default true,
  modelo_mensagem  text not null,
  destinatarios    jsonb not null default '[]'::jsonb,   -- [{"rotulo": "...", "numero": "55..."}]; sem o item "Canal:"
  criado_em        timestamptz not null default now(),
  atualizado_em    timestamptz not null default now(),
  unique (id_escritorio, tipo_evento)
);
-- + gatilho agentesia_tocar_atualizado_em e RLS, como nas outras
```
- `agentesia_eventos_recebidos.origem`: incluir `'zapsign'` no `check`.
- `agentesia_integracoes.tipo`: `'zapsign'` já existe. O segredo do webhook vai em `config`, com referência ao Vault.
- `agentesia_agentes.config`: chaves `modelo_auditor` e `automacoes.<gatilho>.notificar` (jsonb, sem migração).
- Para `{{valor}}`: não há coluna. Ler de `agentesia_contratos.dados->>'valor'` (ou do fato `valor_contrato` em `agentesia_lead_fatos`). Decidir e documentar.
- `{{origem}}`: `agentesia_leads.origem` (jsonb). `{{link_assinatura}}`: `agentesia_contratos.link`. `{{resumo}}`: quando houver resumo do lead.
- Painel (`app/gestao/rotas.py`): CRUD de `agentesia_notificacoes`, com histórico em `agentesia_alteracoes`. A descrição de `funcoes.avisos` passa a citar os 10 tipos e as etapas.

Nenhuma tabela de log nova: o envio fica em `agentesia_acoes` (resultado e erro), a decisão do auditor em `agentesia_turnos.contexto` e `agentesia_eventos`, e o custo em `agentesia_chamadas_ia` (papel `auditor`).

### 10.7 O que se descarta (coisa do n8n ou defeito)

| Do fluxo | Por quê |
|---|---|
| Execute Workflow Trigger e os textos "Enviar para o lead a mensagem" / "Continue o atendimento normalmente" | A IA não chama ferramenta: o extrator marca o sinal e o código decide. A mensagem vai direto para `saida.mensagens` |
| `Tira invalidos`, `Clientes Selecionados?` (id fixo), `analisehumana`, `Tipo desqualificado?` | Filtros que não filtram, ramos mortos e escritório fixo no código. A escolha vira `funcoes.avisos` por agente e `habilitada` por aviso |
| `extraindo_dados` (session_id pelo link) | `agentesia_leads.id_sessao_helena` já existe |
| `BUSCA ENTIDADES WEAVER`, `Filter1`, `Reune os Itens`, `Root Items` | Busca por telefone e malabarismo de itens. O turno já tem lead, canal, agente e etapa pelo id |
| `Baixar Memoria`, `Ordena Memoria Novo`, `Summarize2` | O histórico vem de `agentesia_mensagens`, em ordem e com autor |
| `Organiza a resposta` | Saída estruturada com esquema (`Modelo.gerar`) |
| 10 nós de agente + Switch | Um `auditar_sinal` com um dicionário de prompts |
| `Contar Token SUBFLUXO` (x2) | `agentesia_chamadas_ia` grava cada chamada |
| `Desativa Weaver` (`lead.ia_ligada`) | `agentesia_leads.estado = 'pausado'` |
| `TRADUZ ETAPA` com normalização de texto | As etapas já são códigos nossos (`EVENTO_POR_ETAPA`) |
| `Verifica notificação ligada` (adivinhar campo de "ativo") | Coluna `habilitada` própria |
| Webhook `NotificaTrocaDeDepartamento` com token no corpo | A troca de etapa acontece dentro do sistema e vira gatilho `etapa:<codigo>`, sem HTTP |
| Endpoint `chat/v1/send/text`, nota sem `Bearer` | Um envio só (`enviar_sem_atendimento`) e o cliente `HelenaConta`, que já põe `Bearer` |
| `Chegou Fim` (Stop and Error) | Depuração esquecida |
| SQL montado por concatenação | asyncpg com parâmetros `$1` |

### 10.8 Testes sugeridos (`tests/`)
- `renderizar_modelo`: linha com marcador vazio some; espaços dentro de `{{ x }}`; colapso de `\n`.
- `filtrar_destinatarios`: tira o canal (sem id, `Canal:`, mesmo número), repetidos e não `phone`; normaliza 10, 11 e 13 dígitos.
- `auditar_sinal` com `ModeloFalso`: válido pausa e usa a mensagem do auditor; inválido segue o turno; erro do modelo pausa com a mensagem fixa.
- `_preparar_aviso`: sem configuração, desligada, sem modelo e sem destinatário geram evento e nenhum envio; dois destinatários geram duas ações `notificar` com chaves diferentes.
- `receber_zapsign`: evento repetido não duplica; `doc_signed` do e-mail do escritório é ignorado; contrato desconhecido vira evento `cadastro`.
