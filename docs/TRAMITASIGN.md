# Contrato pela Tramitação Inteligente (TramitaSign): desenho

Situação: **desenho, nada implementado**. Hoje o motor só fala com a ZapSign (`app/canal/zapsign.py`,
`app/contrato/*`, `Executor._gerar_contrato` / `_verificar_assinatura` em `app/acoes.py`). Objetivo: cada escritório
(e, se preciso, cada agente) escolhe o provedor de assinatura: **ZapSign** ou **Tramitação Inteligente**.

---

## 1. O que a API oferece (e o que não achamos)

### 1.1 Documentação pública

**Não existe documentação pública encontrável** (pesquisa em 26/11/2026):

- `https://tramitacaointeligente.com.br` redireciona (301) para `https://planilha.tramitacaointeligente.com.br/`, uma
  página de login sem link para API, desenvolvedores ou integrações.
- `…/api-docs`, `…/api/v1/docs` e `…/info/api` devolvem 404.
- Buscas na web por "Tramitação Inteligente API", "TramitaSign" e "envelope.signed" não trazem nada do produto. Só
  aparecem páginas de conteúdo do site (ex.: `https://planilha.tramitacaointeligente.com.br/info/modelos-de-peticoes-previdenciarias`).

A documentação deve ficar dentro da conta logada (Configurações > API / Integrações). **Pedir ao dono** o link ou um
PDF/print da documentação (seção 9). Nenhuma chamada autenticada foi feita.

### 1.2 O que sabemos de fato: o fluxo n8n em produção

Fonte: `Fluxos N8N/07 - Contrato (Geral)/GERAL - Contrato (gerar e assinado).json`, nós `T1`–`T16` (gerar) e
`B1`/`B3t`/`B4` (assinado), que hoje rodam para o escritório "Frederico". É a referência até a documentação chegar.

Base: `https://planilha.tramitacaointeligente.com.br`. Autenticação por cabeçalho (`httpHeaderAuth` do n8n,
`Authorization: Bearer <chave>`). Timeout de 45 s por chamada.

| Passo | Método e caminho | Corpo / observação |
|---|---|---|
| Buscar cliente | `GET /api/v1/clientes?cpf_cnpj=<cpf formatado>` | resposta `{customers:[{id,…}]}`; vazio = não existe |
| Criar cliente | `POST /api/v1/clientes` + `Idempotency-Key` | `{customer:{customer_type:'cliente', name, cpf_cnpj, email, phone_mobile, phone_1, marital_status, profession, zipcode, street, street_number, neighborhood, city, state}}`. Resposta `{customer:{id}}` |
| Gerar documento | `POST /api/v1/documentos` + `Idempotency-Key`, **um por modelo, 300 ms entre eles** | `{document:{user_id, template_id, customer_id}}`. Resposta `{document:{id,title}, template_usage:{blank_variables:[…]}}` |
| Conferir dados em branco | (local) | se algum `blank_variables` (exceto os que citam "RG") existir: bloqueia com `DADOS_EM_BRANCO` |
| Criar envelope | `POST /api/v2/assinaturas` + `Idempotency-Key` | `{envelope:{user_id, name, signers:[{signer_type:'customer', customer_id}]}}`. Resposta `{envelope:{id}}` |
| Incluir documentos | `POST /api/v2/assinaturas/{id}/documentos` + `Idempotency-Key`, um a um com 300 ms | `{document:{block_id:<document.id>}}` |
| Renomear | `PATCH /api/v2/assinaturas/{id}` | `{envelope:{name}}` |
| Enviar | `POST /api/v2/assinaturas/{id}/envio` + `Idempotency-Key` | sem corpo |
| Ler envelope | `GET /api/v2/assinaturas/{id}` | `{envelope:{id,status,signers:[{signature_link, status, signed_at, full_name|name}]}}`. O link **não sai na hora**: o n8n espera 30 s, lê, e se não tiver link espera mais 30 s e lê de novo |
| Aviso de assinatura | webhook que **a Tramitação chama** | corpo `{event_type:'envelope.signed', payload:{envelope:{id}}}`; o n8n só age em `envelope.signed` |

Configuração usada por conta: chave (Bearer), `user_id` (ex.: `user_…`, o advogado dono dos documentos), lista de
`template_id` (ex.: `[301,302,303,304]`), nome do envelope (`"Documentos para assinatura - {nome}"`) e
`bloquear_se_faltar_dado` (true).

O n8n grava o `customer_id` como `external_id` do lead e o id do envelope como id do contrato.

### 1.3 Diferenças em relação à ZapSign que mudam o desenho

1. **Várias chamadas por contrato** (2 + N modelos + 1 + N + 2 + 1-2 leituras, cerca de 12 para 4 modelos) em vez de uma. Uma
   falha no meio deixa sobras (cliente criado, documentos soltos, envelope sem envio).
2. **Os dados do lead vão para o cadastro do cliente**, não para variáveis do modelo. Não há `mapeamento` variável→campo:
   o modelo da Tramitação puxa as variáveis do cliente. Quem preenche os campos é o cadastro.
3. **O cliente é reaproveitado pelo CPF.** Se já existe com dados velhos, o n8n **não atualiza**: o documento sai com o
   endereço antigo. Ver o risco R2.
4. **Link assíncrono**: a geração leva de 30 a 60 s e não pode rodar dentro do turno.
5. **Webhook sem segredo conhecido** e sem `external_id`: o aviso só traz o id do envelope.
6. **Um signatário** (o cliente). Não há "o escritório também assina": `so_o_escritorio_assinou` não se aplica.

---

## 2. Mapeamento campo a campo (`app/contrato/dados.py` CAMPOS → cliente TramitaSign)

Entrada: o dicionário `valido` que sai de `cdados.validar_dados()` (CPF já `000.000.000-00`, CEP `00000-000`, UF sigla,
telefone só dígitos 10/11 sem 55, profissão normalizada, estado civil normalizado).

| Nosso campo (fato do lead) | Campo `customer` | Transformação |
|---|---|---|
| `nome` (nome_completo) | `name` | igual |
| `cpf` | `cpf_cnpj` | igual, formatado (o n8n usa formatado, inclusive na busca `?cpf_cnpj=`). **Confirmar** se a busca aceita só dígitos |
| `email` | `email` | omitir se vazio |
| `telefone` (telefone_contrato ou o da conversa) | `phone_mobile` e `phone_1` | `"55" + dígitos`; omitir se vazio |
| `estado_civil` | `marital_status` | texto livre ("Casada", "União estável"). **Confirmar** se a API espera um enum (`casado`, `solteiro`…) |
| `profissao` | `profession` | igual ("Desempregado" / "Não informado" já resolvidos) |
| `rg` | `rg_numero` | igual (o n8n atual **não envia** o RG, por isso ignora `blank_variables` com "RG". Passaremos a enviar) |
| `cep` | `zipcode` | igual (`00000-000`) |
| `endereco` | `street` | igual |
| `numero` + `complemento` | `street_number` | `"{numero} - {complemento}"`; só o número se não houver complemento |
| `bairro` | `neighborhood` | igual |
| `cidade` | `city` | igual |
| `estado` (uf) | `state` | sigla |
| (fixo) | `customer_type` | `'cliente'` |
| `nomecompletomenor`, `cpfdomenor` | **sem campo conhecido** | não vai. Pergunta em aberto Q4 (campo extra? outro cliente? variável do documento?) |
| `@data_geracao` / `@fixo` | não se aplica | a data do documento é da Tramitação |

Regra: campo vazio **não é enviado** (igual ao n8n `T4`), para não apagar dado que o cadastro já tinha.

`obrigatorios` continua valendo (a validação é nossa). A trava `blank_variables` é a segunda rede: pega variável do
modelo que não tem dado no cliente.

---

## 3. Como chega o status da assinatura

### 3.1 Webhook (principal)

- A Tramitação faz `POST` com `event_type = "envelope.signed"` e `payload.envelope.id`. Outros eventos `envelope.*`
  provavelmente existem (recusa, cancelamento, vencimento), mas não estão confirmados.
- Rota nova: `POST /webhook/tramitasign/{id_escritorio}?segredo=<segredo>`. O segredo vai **na URL** porque não sabemos
  se a Tramitação deixa colocar cabeçalho próprio. Se a documentação trouxer assinatura HMAC (ex.: `X-Signature`), ela
  passa a ser a validação e o segredo na URL fica como reserva.
- Igual à ZapSign: **o aviso nunca decide**. Ele só registra (em `agentesia_eventos_recebidos`, com origem
  `tramitasign` e id externo `"{envelope_id}:{event_type}"`) e põe `verificar_assinatura` na fila. Quem decide é a
  releitura `GET /api/v2/assinaturas/{id}`.

### 3.2 Polling (rede de segurança)

A mesma rotina `servico.agendar_consultas` (de 30 em 30 min nas primeiras horas, depois mais espaçada) vale para os dois
provedores: ela só põe `verificar_assinatura` na fila e o provedor do contrato decide como ler. Na Tramitação isso é
ainda mais importante, porque não sabemos se o webhook chega sempre.

### 3.3 Leitura → nossas situações

`ler()` do provedor devolve a mesma `Leitura` de `app/contrato/assinatura.py` (situação + abertura):

| Envelope na Tramitação | Nossa `situacao` | Efeito |
|---|---|---|
| `status` em `signed/completed/finished/concluded/assinado/concluido`, ou todos os signers com `signed_at` | `assinado` | fluxo **"contrato assinado"** (marca uma vez, etapa `contrato_assinado`, cancela lembretes, mensagem pós-assinatura, nota, PDF, resumo, automações) |
| status de recusa/cancelamento (a confirmar: `refused`, `canceled`…) | `cancelado` | `_contrato_encerrado` (texto "cancelado", equipe) |
| status de vencido (a confirmar) | `expirado` | idem |
| envelope 404 | `excluido` | idem |
| qualquer outro (`sent`, `pending`…) | `pendente` | no **"já assinei"**: manda o texto `pendente` com o link de novo |
| signer com "visualizado/aberto" (se a API informar) | `pendente` + abertura `abriu_sem_assinar` | texto `travou` |

Sem dado de abertura, o "já assinei" sempre cai em `pendente` (link de novo). Não se aplicam
`so_o_escritorio_assinou` nem `nao_reconhecido` (há um signatário só, e ele é o cliente que criamos).

O fluxo **"já assinei"** não muda: a IA põe `verificar_assinatura` com `origem='verificacao'`, o executor relê pelo
provedor do contrato e responde.

---

## 4. Arquitetura proposta

### 4.1 Interface comum de provedor

```
app/contrato/provedores/
  __init__.py        # Provedor (Protocol), DocumentoGerado, LeituraEnvelope, ErroProvedor, provedor_do_contrato()
  zapsign.py         # adaptador fino sobre app/canal/zapsign.py (sem mudar o comportamento de hoje)
  tramitasign.py     # cliente HTTP + passos da seção 1.2
```

```python
class Provedor(Protocol):
    nome: str                                   # 'zapsign' | 'tramitasign'
    async def gerar(self, *, id_contrato: str, dados: dict[str, str], modelo: dict, config: dict,
                    chave_idem: str) -> DocumentoGerado: ...
        # DocumentoGerado: id_documento_externo, link (pode ser None = 'preparando'), id_assinante_externo,
        #                  id_cliente_externo, id_modelo, extras (ids dos documentos, para limpeza/auditoria)
    async def status(self, id_documento_externo: str) -> LeituraEnvelope: ...
        # status bruto + assinantes normalizados (nome, status, assinou_em, link, abriu) + arquivo_assinado
    async def ler_link(self, id_documento_externo: str) -> str | None: ...
        # para quem gera com link assíncrono (Tramitação) e para "mesmo_link"
    def validar_webhook(self, id_escritorio: str, pedido_headers, query, corpo) -> EventoAssinatura | None: ...
        # confere o segredo/assinatura e extrai (id_documento_externo, evento, id_externo_do_evento); None = ignorar
    async def cancelar(self, id_documento_externo: str, motivo: str) -> None: ...      # versão substituída
    async def atualizar_contato(self, ...) -> bool: ...                                  # False = não suportado
```

`ErroProvedor(motivo, detalhe, status)` com os mesmos motivos de hoje (`chave`, `pagamento`, `limite`, `modelo`,
`fora_do_ar`, mais `dados_em_branco` e `sem_link`). `ErroZapSign` passa a ser subclasse, para não quebrar o que já captura ele.
`NOTAS_CAUSA` ganha a versão por provedor ("a Tramitação recusou a chave…").

`assinatura.py` hoje recebe `DocumentoZapSign`. Ele passa a receber a `LeituraEnvelope` neutra. O adaptador ZapSign converte
`DocumentoZapSign` → `LeituraEnvelope`, e a lógica de reconhecer o lead pelo token/telefone fica igual.

### 4.2 Onde o executor muda (`app/acoes.py`)

- `_zapsign(id_escritorio)` vira `_provedor(id_escritorio, id_agente)`, que devolve `(Provedor | None, config)`.
- `_gerar_contrato`: reserva, validação e "só mudou o contato" continuam iguais. Troca `zapsign.criar_de_modelo` por
  `provedor.gerar`. Se `link is None` (Tramitação preparando):
  grava o contrato como `gerado` sem link (ou situação nova `preparando`, ver 4.4), **não** manda mensagem e põe
  `buscar_link_contrato` na fila para daqui a 30 s (até 3 tentativas). Quando o link chega, manda o texto `link`/`nova_versao`,
  move para `assinatura` e roda as automações de "contrato gerado". Assim o turno nunca espera 60 s.
- `_verificar_assinatura` / `_cancelar_contrato` / `_lembrar_assinatura` / `_ler_documento`: usam o provedor **gravado
  no contrato** (`agentesia_contratos.provedor`), não o atual da conta. Um contrato gerado na ZapSign continua sendo lido
  na ZapSign mesmo depois de a conta trocar para a Tramitação.
- `_guardar_pdf_assinado`: só se a Tramitação expuser o PDF assinado (pergunta Q6); senão a ação é pulada.

### 4.3 Onde fica a escolha do provedor

- **Integração da conta**: uma linha nova em `agentesia_integracoes` com `tipo = 'tramitasign'` (a chave fica no Vault, como a
  da ZapSign). `config`:
  ```json
  { "user_id": "user_…", "nome_envelope": "Documentos para assinatura - {nome}",
    "bloquear_se_faltar_dado": true, "ignorar_em_branco": ["rg"],
    "modelos": [ { "id_modelo": "pacote-bpc", "nome": "BPC/LOAS", "padrao": true,
                   "template_ids": [301,302,303,304], "id_agente": null, "id_ativado": null,
                   "obrigatorios": ["nome","cpf",…] } ],
    "mensagens": {…}, "midia_pos_assinatura": {…}, "resumo": {…} }
  ```
  Na Tramitação, o "modelo" é um **pacote** de `template_ids`. Reaproveita `app/contrato/modelos.py` (padrão, por produto,
  por agente), com `template_ids` no lugar de `mapeamento`.
- **Qual provedor vale**: campo `provedor_contrato` em `agentesia_escritorios.config` (padrão da conta: `'zapsign'`) e,
  opcional, `provedor_contrato` na config do agente/produto ativado, que sobrepõe o da conta. Ordem: agente → conta → o único
  integrado → `zapsign`. Fica uma função pura `escolher_provedor(config_conta, config_agente, integracoes)` com teste.
- Textos, mídia pós-assinatura e resumo: hoje moram na `config` da ZapSign. Proposta: ler da integração do **provedor
  escolhido**, e, se lá não houver, da outra, para não obrigar a reconfigurar tudo. Depois, mover para um lugar neutro (Q8).

### 4.4 Banco (migração nova, com `desfazer_`)

- `agentesia_integracoes.tipo`: incluir `'tramitasign'`.
- `agentesia_contratos.provedor`: check `in ('zapsign','tramitasign')`.
- `agentesia_contratos`: colunas `id_cliente_externo text` (customer_id) e `extras jsonb` (ids dos documentos gerados,
  status bruto). Opcional: situação `'preparando'` (gerado na Tramitação, sem link ainda). Também dá para usar `gerado` com
  `link null`, mas a situação explícita deixa o painel e o `reservar()` mais claros (o índice `um_gerado` precisa incluir `preparando`).
- `agentesia_leads`: guardar o `customer_id` em `agentesia_contratos.id_cliente_externo` basta. O "external_id do lead" do
  n8n era para achar o lead no aviso; aqui achamos pelo envelope (`provedor, id_documento_externo`, que já tem índice único).

### 4.5 Rota do webhook (`app/main.py`)

`POST /webhook/tramitasign/{id_escritorio}` → `provedor.validar_webhook` → `servico.receber_webhook(pool, id_escritorio,
evento, provedor='tramitasign')`. `receber_webhook` vira genérico: recebe o evento já normalizado, e a parte de ZapSign
(`EVENTOS_QUE_RELEEM`, `signer_who_signed`, `external_id`) fica no adaptador. Responde 200 na hora.

---

## 5. Erros e idempotência

- **Idempotency-Key** (a API aceita, o n8n já usa): chave estável **por versão do contrato**, não por execução:
  `"{id_contrato}:cliente"`, `"{id_contrato}:doc:{template_id}"`, `"{id_contrato}:envelope"`,
  `"{id_contrato}:incluir:{block_id}"`, `"{id_contrato}:envio"`. Repetir a ação da fila (queda, deploy no meio) não duplica
  nada. **Confirmar** por quanto tempo a Tramitação guarda a chave e se devolve a mesma resposta (Q3).
- **Retomada passo a passo**: cada id obtido (customer_id, document ids, envelope_id, enviado=true) é gravado em
  `agentesia_contratos.extras` assim que sai. Na nova tentativa, o `gerar()` pula o que já foi feito. Isso é mais seguro que
  depender só da Idempotency-Key.
- **Reserva**: `RESERVA_MINUTOS = 3` cobre as ~12 chamadas (com 45 s de timeout cada, no pior caso não cobre). Para a
  Tramitação: renovar a reserva a cada passo (batimento, como o turno já faz) ou subir para 10 min.
- **Classificação** (igual ao `T16`): 401/403 → `chave`; 402 → `pagamento`; 429/limit/quota → `limite` (tenta de novo com
  espera); 400/404/422 → `modelo` (definitivo, do escritório); `blank_variables` → `dados_em_branco`; 5xx/timeout →
  `fora_do_ar` (tenta de novo); envelope sem link após as tentativas → `sem_link` (nota para a equipe, o lead recebe `equipe_envia`).
- **`dados_em_branco`**: nota interna listando "documento: variável" e a mensagem `equipe_envia` ao lead. Se a variável
  em branco for de um campo nosso (ex.: profissão), pedir ao lead pelo `pedir_correcao`. Precisa de um mapa nome da variável →
  nosso campo, que só sai com a documentação (Q5).
- **Sobras**: documentos/envelope criados numa tentativa que falhou de vez são registrados em `extras` e listados na nota
  ("envelope X criado e não enviado"). Não apagamos nada na Tramitação sem a API de exclusão confirmada.
- **Versão nova (dados mudaram)**: cria envelope novo e **cancela o antigo** se a API permitir (Q7); senão a nota avisa que
  o link antigo continua válido. "Só mudou o contato" não vale para a Tramitação no começo (`atualizar_contato` → False →
  gera versão nova).
- **Limite de taxa**: 300 ms entre documentos e entre inclusões (como no n8n); uma geração por vez por escritório na Tramitação
  (trava leve no executor).
- **Log**: nunca gravar a chave nem o corpo do cliente (CPF, endereço) no log ou em `agentesia_eventos_recebidos`. Só ids e status.

---

## 6. O que muda no painel

- **Integrações**: novo cartão "Tramitação Inteligente" ao lado do ZapSign (`painel/src/telas/Integracoes.tsx`) e tela
  `IntegracaoTramitaSign.tsx` (molde: `IntegracaoZapSign.tsx` / `ZapsignDialog.tsx`):
  - chave de API (mascarada, últimos 4), `user_id` (com "Testar conexão": um `GET /api/v1/clientes?cpf_cnpj=00000000000`
    ou o endpoint de usuário, se existir, que mostra o nome do usuário);
  - **pacotes de modelos**: nome + lista de ids de modelo (`301, 302, 303, 304`), padrão, vínculo com produto/agente;
    se a API listar modelos (`GET /api/v1/modelos`?), vira lista de seleção;
  - nome do envelope (com `{nome}`), "bloquear se faltar dado" e a lista de variáveis que podem ficar em branco;
  - URL do webhook para colar na Tramitação (com o segredo), com botão copiar. Se a API permitir cadastrar o webhook,
    usar um botão "Cadastrar aviso", igual ao da ZapSign (`/integracoes/zapsign/aviso-assinatura`).
- **Escolha do provedor**: em Integrações (ou Minha Conta), um seletor "Assinatura dos contratos: ZapSign | Tramitação",
  que só habilita os integrados. Na tela de contrato do produto/agente (`ProductConfigurator.tsx`, `AgenteFuncoes.tsx`),
  "Usar o provedor da conta / ZapSign / Tramitação" e, conforme a escolha, o editor de modelo da ZapSign (variáveis) ou o
  de pacote da Tramitação.
- **Contratos do lead** (`rotas_contrato.py` `/leads/{id}/contratos`): mostrar o provedor, o envelope e a situação
  `preparando`.
- **Ativação** (`app/gestao/ativacao.py` linha "lembre de colar o webhook"): checklist por provedor.
- Rotas novas em `app/gestao/rotas.py`: `GET/PUT /integracoes/tramitasign`, `POST /integracoes/tramitasign/testar`,
  `PUT /escritorio/provedor-contrato`.

---

## 7. Riscos

- **R1. Sem documentação.** Tudo vem do n8n, e status, eventos, cancelamento e PDF são suposições. Mitigação: implementar
  só o caminho que o n8n prova e deixar o resto atrás de "a confirmar".
- **R2. Cliente reaproveitado com dados velhos.** Busca por CPF achou → o documento sai com o cadastro antigo. Proposta:
  quando achar, `PATCH /api/v1/clientes/{id}` com os campos novos (se a API tiver), ou comparar e avisar na nota. Pergunta Q2.
- **R3. Link assíncrono.** Se em 90 s não houver link, o lead fica sem contrato. É preciso a ação `buscar_link_contrato` e
  uma nota para a equipe.
- **R4. Webhook sem autenticação forte.** Segredo na URL vaza em log de proxy. Como a releitura decide, um aviso falso só
  gera uma leitura a mais (risco baixo).
- **R5. Vários documentos por envelope.** Assinado = envelope todo assinado. Se a Tramitação permitir assinatura parcial
  por documento, isso precisa de cuidado.
- **R6. Migração do Frederico.** Contratos antigos gerados pelo n8n (`contrato_documento`, `leads_dashboard.customer_id`)
  não estão em `agentesia_contratos`. Avisos desses envelopes caem em "documento desconhecido" (ignorados). Enquanto o n8n
  não for desligado para esse escritório, o webhook da Tramitação tem de continuar apontando para o n8n, ou os dois sistemas
  precisam receber o aviso.
- **R7. Créditos/plano.** Não sabemos se existe endpoint de plano (como o `plano()` da ZapSign) para avisar antes de falhar.

---

## 8. Estimativa de passos

| # | Passo | Tamanho |
|---|---|---|
| 0 | Conseguir a documentação e uma chave de teste com o dono (seção 9) | depende do dono |
| 1 | `provedores/__init__.py` (Protocol, tipos neutros, `ErroProvedor`) + adaptador `zapsign.py` sem mudar comportamento; `assinatura.py` sobre a `LeituraEnvelope` | médio, 1 dia, com os testes atuais passando sem mudança |
| 2 | Migração 013: `tipo`/`provedor` com `tramitasign`, `id_cliente_externo`, `extras`, situação `preparando` (+ `desfazer_013.sql`, `APLICAR_NO_SUPABASE.sql`) | pequeno |
| 3 | `provedores/tramitasign.py`: cliente HTTP, `montar_cliente()` puro (seção 2), `gerar()` com retomada por `extras` e Idempotency-Key, `status()`, `ler_link()`, `validar_webhook()`; testes com respostas gravadas (fake httpx) | médio-grande, 1 a 2 dias |
| 4 | Executor: `_provedor()` + `escolher_provedor()`, provedor pelo contrato na verificação/cancelamento/lembrete, ação `buscar_link_contrato`, causas novas | médio, 1 dia |
| 5 | Rota `/webhook/tramitasign/{id}` + `receber_webhook` genérico + polling para os dois | pequeno |
| 6 | Painel: cartão e tela da integração, seletor do provedor (conta e agente), pacote de modelos, contratos do lead com provedor | médio, 1 a 1,5 dia |
| 7 | Teste ponta a ponta numa conta de teste da Tramitação (gerar, link, assinar, webhook, "já assinei", versão nova) | 0,5 dia |
| 8 | Virar o escritório Frederico: decidir o webhook (R6), desligar o ramo T* do n8n | combinado com o dono |

Total: cerca de 5 a 6 dias de trabalho depois de ter a documentação e a chave de teste.

---

## 9. Perguntas em aberto para o dono

1. **Documentação**: onde está (link na conta, PDF)? Tem ambiente de teste (sandbox) ou uma conta de teste?
2. **Cliente que já existe**: atualizamos o cadastro com os dados novos do lead (há `PATCH /api/v1/clientes/{id}`?) ou
   mantemos o que está lá?
3. **Idempotency-Key**: por quanto tempo vale e o que a API devolve numa chave repetida?
4. **Menor de idade**: como o contrato com menor funciona na Tramitação (outro cliente, campo extra, outro modelo)?
5. **Nomes das variáveis** de `blank_variables` (para pedir ao lead o dado que faltou em vez de mandar para a equipe).
   E o RG: o n8n ignora, mas agora vamos enviar `rg_numero`. Pode tirar a exceção?
6. **PDF assinado**: a API devolve o arquivo assinado (URL ou download)?
7. **Cancelar envelope** (versão substituída) e **eventos do webhook** além de `envelope.signed` (recusa, vencimento,
   visualização). Existe "abriu e não assinou"?
8. **Escolha por conta ou por agente?** Um escritório pode ter um agente na ZapSign e outro na Tramitação? Os textos,
   a mídia e o resumo pós-assinatura são os mesmos nos dois provedores?
9. **Webhook**: a Tramitação deixa cadastrar URL por API e colocar cabeçalho próprio? Assina o corpo (HMAC)?
10. **`user_id`**: é sempre o mesmo advogado por escritório, ou muda por produto/agente?
11. **Estado civil**: a API aceita texto livre ou uma lista fixa?
12. **Frederico**: quando virar para o código, os contratos já gerados pelo n8n precisam ser importados para acompanhar a
    assinatura?
