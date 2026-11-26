# Deploy no Easypanel: dois apps

O sistema sobe em **dois apps** no Easypanel, os dois a partir do **mesmo repositório**:

| App | O que faz | Dockerfile | Ponto de entrada | Domínio sugerido |
|---|---|---|---|---|
| **ia** | Recebe os webhooks da Helena e da ZapSign, roda o atendimento (pipeline), a fila de ações, os follow-ups, a central de avisos e a indexação da base de conhecimento. | `Dockerfile.ia` | `app.entrada_ia:app` | `ia.seudominio.com.br` |
| **painel** | Entrega o painel (as telas) e a API de gestão `/api/*`, e o login pela Helena (`/entrar/helena`). **Não** roda nenhuma tarefa de fundo. | `Dockerfile.painel` | `app.entrada_painel:app` | `painel.seudominio.com.br` |

Por que separar: se o painel cair ou for atualizado, o atendimento continua respondendo os clientes, e vice-versa.

No seu computador nada muda: `uvicorn app.main:app --port 8000` continua subindo tudo num processo só.

---

## 0. Antes de tudo: o banco (Supabase)

Aplique as migrações **na ordem**, no SQL Editor do Supabase (projeto AGENT WEAVER), **antes** do primeiro deploy:

1. `db/migracoes/001_agentesia_nucleo.sql`
2. `db/migracoes/002_agentesia_gestao.sql`
3. `db/migracoes/003_agentesia_conhecimento.sql`
4. `db/migracoes/004_agentesia_canal_liberado.sql`
5. `db/migracoes/005_agentesia_midia_pendente.sql`
6. `db/migracoes/006_agentesia_conta_helena.sql`

Os dois apps conferem as tabelas na hora de subir: se faltar alguma migração essencial, o app **não sobe** e o log mostra
`banco sem as migrações do atendimento (falta: ...)`.

Pegue a string de conexão em **Project Settings > Database > Connection string**, modo **Transaction pooler**. Ela vai
na variável `AGENTESIA_BANCO_URL` dos dois apps.

### 0.1 O bucket da mídia (Supabase Storage)

A mídia da biblioteca (áudio `.ogg`/`.mp3`/`.m4a`, vídeo `.mp4`, imagem `.jpg`/`.png`) fica num **bucket do Supabase
Storage**, no mesmo projeto do banco. A Helena baixa cada arquivo pela URL pública do bucket para mandar ao lead.

1. No SQL Editor do Supabase, rode **uma vez** `db/exemplos/criar_bucket_midia.sql`. Ele cria o bucket
   `agentesia-midia`:
   - **público para leitura**: qualquer um com a URL do arquivo baixa
     (`https://<projeto>.supabase.co/storage/v1/object/public/agentesia-midia/...`), mas ninguém lista o bucket;
   - **escrita só pela service role** (a chave que o servidor usa): políticas restritivas barram anon e authenticated
     de gravar, trocar ou apagar arquivos ali;
   - limite de 16 MB por arquivo e só os formatos aceitos pela biblioteca.
   - Também dá para criar pela tela (**Storage > New bucket**, nome `agentesia-midia`, **Public bucket** ligado), mas o
     SQL já põe o limite, os formatos e as políticas.
2. Pegue a chave **service_role** em **Project Settings > API** (ou **API Keys**). Ela é segredo: vai só na aba
   **Environment** do Easypanel, na variável `AGENTESIA_SUPABASE_SERVICE_KEY`, nunca no repositório.
3. Nos dois apps, ligue `AGENTESIA_MIDIA_ARMAZENAMENTO=supabase` (seção 5).

Com o bucket, **os dois apps não precisam mais dividir uma pasta**: o painel grava direto no bucket e a URL guardada é
a do Storage. O `/midia` local nem é montado nesse modo, e um deploy novo não perde nenhum arquivo.

## 1. O código precisa estar num repositório Git

O Easypanel constrói a imagem a partir do GitHub (ou de outro Git). Suba este projeto para um repositório **privado**.
O `.env` nunca vai junto (está no `.gitignore` e no `.dockerignore`).

## 2. Criar o projeto (e a pasta da mídia, só sem o bucket)

1. No Easypanel, clique em **Create Project** e dê um nome (por exemplo `lawchat`).
2. **Com o bucket do Supabase (seção 0.1, o recomendado), pule este item e os passos 3.5 e 4.5.** Só no modo local
   (`AGENTESIA_MIDIA_ARMAZENAMENTO=local`) a mídia é gravada no disco pelo **painel** e servida pelo endereço público
   da **ia**, e aí os dois apps precisam enxergar a **mesma pasta** do servidor, montada nos dois (passos 3.5 e 4.5).
   - Pelo terminal do servidor (SSH), crie a pasta e dê a posse ao usuário do container (uid 1000):
     ```
     mkdir -p /etc/easypanel/projects/lawchat/midia
     chown -R 1000:1000 /etc/easypanel/projects/lawchat/midia
     ```
   - Sem o `chown`, o envio de mídia pelo painel falha com erro de permissão.

## 3. App "ia"

1. Dentro do projeto: **+ Service > App**, nome `ia`.
2. **Source**: GitHub (ou Git), escolha o repositório e o branch (`main`).
3. **Build**: escolha **Dockerfile** e, no caminho do arquivo, escreva `Dockerfile.ia`.
4. **Environment**: cole as variáveis da seção 5.1 (uma por linha, `NOME=valor`).
5. **Mounts** (só no modo local da mídia; com o bucket, pule): **Add Bind Mount**, Host Path
   `/etc/easypanel/projects/lawchat/midia`, Mount Path `/dados/midia`.
6. **Domains**: adicione `ia.seudominio.com.br`, com HTTPS ligado e **porta 8000** (a porta de dentro do container).
7. **Deploy**.
8. Deixe **uma instância só** (réplicas = 1): os laços de fundo (fila, follow-up, avisos) rodam neste app.

## 4. App "painel"

1. **+ Service > App**, nome `painel`.
2. **Source**: o mesmo repositório e branch.
3. **Build**: **Dockerfile**, caminho `Dockerfile.painel`. Esse build compila o front (Node) e depois monta o servidor
   Python; demora mais que o da ia (alguns minutos na primeira vez).
4. **Environment**: as variáveis da seção 5.2.
5. **Mounts** (só no modo local da mídia; com o bucket, pule): **Add Bind Mount**, Host Path
   `/etc/easypanel/projects/lawchat/midia`, Mount Path `/dados/midia` (a mesma pasta do app ia).
6. **Domains**: `painel.seudominio.com.br`, HTTPS ligado, **porta 8000**.
7. **Deploy**.

As duas imagens aceitam a variável `PORT`: se você mudar a porta (por exemplo `PORT=3000`), mude também a porta do
domínio. Sem `PORT`, é 8000.

## 5. Variáveis de ambiente

Nunca coloque valores reais em arquivos do repositório; eles só vão na aba **Environment** de cada app. A lista completa,
comentada e sem valores, está no `.env.example`.

**Iguais nos dois apps** (copie o mesmo valor): `AGENTESIA_BANCO_URL`, `AGENTESIA_WEBHOOK_SEGREDO`,
`AGENTESIA_URL_PUBLICA`, `OPENAI_API_KEY` (e `ANTHROPIC_API_KEY`, se usar), `AGENTESIA_MODELO` e as da mídia:

| Variável | Valor | Para que serve |
|---|---|---|
| `AGENTESIA_MIDIA_ARMAZENAMENTO` | `supabase` | Mídia no bucket do Storage. `local` (o padrão) grava no disco e exige a pasta compartilhada. Escolhido na subida: trocou, faça deploy dos dois apps. |
| `AGENTESIA_SUPABASE_URL` | `https://<projeto>.supabase.co` | Endereço do projeto Supabase (Project Settings > API). |
| `AGENTESIA_SUPABASE_SERVICE_KEY` | a chave service_role | **Segredo.** Grava e apaga arquivos no bucket. Só no Environment. |
| `AGENTESIA_MIDIA_BUCKET` | `agentesia-midia` (padrão) | Nome do bucket criado na seção 0.1. |

Quem grava e apaga no bucket é só o **painel**: `AGENTESIA_SUPABASE_URL`, `AGENTESIA_SUPABASE_SERVICE_KEY` e
`AGENTESIA_MIDIA_BUCKET` são obrigatórias nele. No app **ia** basta `AGENTESIA_MIDIA_ARMAZENAMENTO=supabase` (para não
montar o `/midia` local); a chave service_role pode ficar fora dele. Sem a URL ou a chave, no modo supabase o envio de
mídia pelo painel responde com o aviso do que falta (o resto do sistema funciona).

### 5.1 App "ia"

| Variável | Obrigatória? | Para que serve |
|---|---|---|
| `AGENTESIA_BANCO_URL` | sim | Conexão com o Supabase (Transaction pooler). Sem ela o app não atende nada. |
| `AGENTESIA_WEBHOOK_SEGREDO` | sim | Segredo mestre dos webhooks. Dele saem os segredos de cada escritório. **Mesmo valor do painel.** Nunca vai em URL. |
| `AGENTESIA_URL_PUBLICA` | sim | Endereço público **deste app**, com https e sem barra no fim (`https://ia.seudominio.com.br`). Base das URLs de webhook e dos links de mídia. |
| `OPENAI_API_KEY` | sim | Chave da OpenAI: respostas da IA, leitura de imagem/áudio e vetores da base de conhecimento. |
| `ANTHROPIC_API_KEY` | só se algum agente usar `claude-...` | Chave da Anthropic. |
| `AGENTESIA_MODELO` | não (padrão `gpt-4.1`) | Modelo padrão dos agentes. |
| `AGENTESIA_MODELO_FOLLOWUP` | não (padrão `gpt-4.1-mini`) | Modelo dos follow-ups. |
| `AGENTESIA_MODELO_AUDITOR` | não | Modelo do auditor da resposta (vazio = padrão do código). |
| `AGENTESIA_HELENA_URL` | não (padrão `https://api.helena.run`) | API pública da Helena. |
| `AGENTESIA_HELENA_TOKEN_LAWCHAT` | recomendada | Token da conta Helena da LawChat, usado pela central de avisos. |
| `AGENTESIA_ALERTA_LAWCHAT_DE` | recomendada | Número que envia os avisos de erro grave. |
| `AGENTESIA_ALERTA_LAWCHAT_PARA` | recomendada | Números que recebem os avisos (separados por vírgula). Sem as três, a central fica desligada. |
| `AGENTESIA_BANCO_CONEXOES` | não (padrão 10) | Tamanho do pool de conexões com o banco. |
| `AGENTESIA_BANCO_TIMEOUT_S` / `AGENTESIA_BANCO_COMANDO_S` | não (10 / 15) | Prazo para abrir uma conexão nova e para uma consulta. |
| `AGENTESIA_BANCO_ESPERA_S` | não (5) | Espera máxima por uma conexão LIVRE do pool; passou, o turno fecha como erro de banco "BancoOcupado". |
| `AGENTESIA_BANCO_CONEXOES_MIN` / `AGENTESIA_BANCO_OCIOSA_S` | não (4 / 600) | Conexões sempre abertas e quanto tempo uma conexão parada fica aberta. |
| `AGENTESIA_TURNOS_SIMULTANEOS` | não (5) | Turnos da IA ao mesmo tempo por container (os outros esperam a vez). |
| `AGENTESIA_TURNO_CONSULTAS_PARALELAS` | não (3) | Idas ao banco em paralelo dentro de um turno. |
| `AGENTESIA_CACHE_CONFIG_S` | não (30; 0 desliga) | Cache em memória do escritório da conta, canal, agente e token da plataforma. Mudança feita no painel vale na IA em até esse tempo. |
| `AGENTESIA_SAUDE_BANCO_S` | não (180) | O `/saude` diz "banco ok" se houve consulta bem-sucedida nesse tempo (não vai ao banco). Diagnóstico com o banco: `/saude/banco`. |
| `AGENTESIA_VIGIA_INTERVALO_MIN` | não (10) | Intervalo das varreduras de follow-up ausente e dos avisos (0 desliga todas). |
| `AGENTESIA_FOLLOWUP_AUSENTE_H` / `_JANELA_H` / `_LIMITE` | não (2 / 24 / 10) | Lead cuja última fala é da IA há mais de 2 h (e menos de 24 h) sem follow-up agendado: agenda pelas regras do agente, até 10 por rodada. `_H=0` desliga. |
| `AGENTESIA_AVISO_FOLLOWUP_DESLIGADO_DIAS` | não (7; 0 desliga) | Aviso à equipe LawChat de agente em produção com follow-up desligado (1 por agente nesse período). |
| `AGENTESIA_SEM_WEBHOOK_H` / `AGENTESIA_SEM_WEBHOOK_HORARIO` | não (4 / `9-18`) | Aviso à equipe LawChat quando um escritório ativo fica 4 h sem mensagem dentro do horário comercial (seg-sex), 1 por dia. `_H=0` desliga. |
| `AGENTESIA_REPROCESSAR_JANELA_H` | não (48) | "Responder agora" (POST /api/conversas/{id}/reprocessar) olha as mensagens do lead sem resposta nesse período. |
| `AGENTESIA_IA_TIMEOUT_S` / `AGENTESIA_TETO_TURNO_S` | não (60 / 180) | Tempo máximo de cada chamada à IA e do turno inteiro. |
| `AGENTESIA_DESLIGAR_TETO_S` | não (30) | No desligamento (deploy novo), quanto esperar os turnos em andamento. |
| `AGENTESIA_ESPERA_MINIMA` / `_MAXIMA` / `_PADRAO` | não (15 / 90 / 40) | Espera antes de responder, em segundos. |
| `AGENTESIA_SEGUNDOS_POR_LETRA` / `AGENTESIA_MAX_REPROCESSOS` | não (0.5 / 2) | Ritmo de "digitação" e quantas vezes um turno com erro é refeito. |
| `AGENTESIA_SEGREDO_SESSAO` | não | Não é usado aqui; se faltar, só aparece um aviso no log na subida. |
| `AGENTESIA_MIDIA_ARMAZENAMENTO` | sim (`supabase`) | Mídia no bucket; sem ela vale `local` e o app monta o `/midia` do disco. |
| `AGENTESIA_PASTA_MIDIA` | não mexa | Só no modo local. Já vem `/dados/midia` na imagem (a pasta montada). |

**Não coloque no app ia**: `AGENTESIA_LAB_SENHA`, `AGENTESIA_MODO_LAB`, `AGENTESIA_HELENA_TOKEN`,
`AGENTESIA_ZAPSIGN_URL_TESTE`, `AGENTESIA_MODELO_FALSO` (são de teste local).

### 5.2 App "painel"

| Variável | Obrigatória? | Para que serve |
|---|---|---|
| `AGENTESIA_BANCO_URL` | sim | A mesma conexão do app ia. |
| `AGENTESIA_SEGREDO_SESSAO` | sim | Assina o cookie de login do painel (texto longo e aleatório). Sem ela, todo mundo é deslogado a cada deploy. |
| `AGENTESIA_WEBHOOK_SEGREDO` | sim | **Mesmo valor do app ia.** O painel usa para montar as URLs de webhook na ativação. |
| `AGENTESIA_URL_PUBLICA` | sim | **O endereço do app ia** (`https://ia.seudominio.com.br`), e não o do painel: é a base das URLs de webhook mostradas na ativação e dos links de mídia. |
| `OPENAI_API_KEY` | sim | A ativação confere se a chave existe, e o Laboratório/prévia de cada agente roda neste app. |
| `ANTHROPIC_API_KEY` | só se usar `claude-...` | Idem, para a Anthropic. |
| `AGENTESIA_MODELO` | não (padrão `gpt-4.1`) | Modelo padrão (Laboratório e prévia). |
| `AGENTESIA_HELENA_URL` | não | API pública da Helena. |
| `AGENTESIA_HELENA_TOKEN_PARCEIRO` | recomendada | Token de parceiro da Helena: lista contas, gera o token de cada conta e lê os dados da empresa no onboarding. |
| `AGENTESIA_HELENA_HANDOFF_SEGREDO` | recomendada | Exige que o link `/entrar/helena` venha assinado (válido por 5 min). |
| `AGENTESIA_HELENA_CONTA_LAWCHAT` | não | Id da conta Helena da LawChat: quem entra por ela vira equipe LawChat no painel. |
| `AGENTESIA_HELENA_TOKEN_LAWCHAT` | não | Token da conta Helena da LawChat (entrada da equipe LawChat pelo link da Helena). |
| `AGENTESIA_BANCO_CONEXOES` | não (padrão 10 no painel) | O Início abre vários pedidos ao mesmo tempo e as rotas leem em paralelo. |
| `AGENTESIA_PAINEL_CRM_LIGADO` e `AGENTESIA_HELENA_INTERNA_URL`, `AGENTESIA_HELENA_PARCEIRO_EMAIL`, `AGENTESIA_HELENA_PARCEIRO_ID`, `AGENTESIA_HELENA_DEVICE_ID`, `AGENTESIA_HELENA_PARCEIRO_ORIGEM`, `AGENTESIA_HELENA_ADMIN_EMAIL` | não (desligado) | Painel padrão do CRM pela API interna da Helena. Só preencha se for usar. |
| `AGENTESIA_LAB_SENHA` | não | Se preenchida, liga o Laboratório antigo (`/lab`) protegido por essa senha. Vazia = `/lab` não existe no painel. |
| `AGENTESIA_MIDIA_ARMAZENAMENTO` | sim (`supabase`) | Mídia no bucket do Storage (seção 0.1). |
| `AGENTESIA_SUPABASE_URL` | sim, com o bucket | `https://<projeto>.supabase.co`. |
| `AGENTESIA_SUPABASE_SERVICE_KEY` | sim, com o bucket | Chave service_role: grava e apaga no bucket. **Segredo.** |
| `AGENTESIA_MIDIA_BUCKET` | não (padrão `agentesia-midia`) | Nome do bucket. |
| `AGENTESIA_PASTA_MIDIA` | não mexa | Só no modo local. Já vem `/dados/midia` na imagem. |

## 6. Endereços dos webhooks

Os webhooks apontam sempre para o **app ia**. Você não precisa montar as URLs à mão: na **ativação** de cada escritório o
painel mostra as URLs prontas, já com o segredo daquele escritório. O formato é:

- **Helena (mensagens)**: `https://ia.seudominio.com.br/webhook/helena/{id do escritório}?segredo=...`
- **Botão "IA" da Helena** (desliga/religa a IA de uma conversa):
  `https://ia.seudominio.com.br/webhook/helena/{id do escritório}/ia?segredo=...`
- **ZapSign (assinatura do contrato)**: `https://ia.seudominio.com.br/webhook/zapsign/{id do escritório}?segredo=...`

O segredo de cada um é diferente (é derivado do `AGENTESIA_WEBHOOK_SEGREDO`): por isso esse valor precisa ser **igual**
nos dois apps. Se um dia trocar o `AGENTESIA_WEBHOOK_SEGREDO`, refaça a ativação de cada escritório para gerar as URLs
novas.

O painel dentro da Helena (iframe) abre por `https://painel.seudominio.com.br/entrar/helena?...`.

## 7. Conferir que subiu

1. No navegador, abra `https://ia.seudominio.com.br/saude`. O esperado é algo assim:
   `{"ok": true, "atendimento": true, "banco": true, "tarefas": {"executor": true, "followup": true, ...}, ...}`
   - `"atendimento": false` = faltou a `AGENTESIA_BANCO_URL`.
   - Resposta 503 = o banco não respondeu ou uma tarefa de fundo morreu (o Easypanel reinicia o container sozinho).
2. Abra `https://painel.seudominio.com.br/saude`: o esperado é
   `{"ok": true, "papel": "painel", "banco_configurado": true, "banco": true, ...}`.
3. Abra `https://painel.seudominio.com.br/` e faça login.
4. Na ativação de um escritório, o passo do webhook faz um teste na URL do app ia (`?teste=1`): se ele passar, a Helena
   alcança o app ia.

As duas imagens têm **HEALTHCHECK** no `/saude`: se ele falhar 3 vezes seguidas, o container é marcado como doente.

## 8. Ver os logs

- **Logs do app rodando**: abra o app (ia ou painel) no Easypanel > aba **Logs**. Erros do atendimento aparecem no app
  **ia**; erros de tela e de API, no **painel**.
- **Logs do build** (quando o deploy falha antes de subir): aba **Deployments** > clique no deploy > veja a saída.
- O segredo dos webhooks nunca aparece no log de acesso (vira `segredo=***`).
- Mensagens comuns na subida:
  - `banco sem as migrações do atendimento (falta: ...)`: rode as migrações que faltam (seção 0).
  - `sem AGENTESIA_SEGREDO_SESSAO`: preencha no painel.
  - `central de avisos da LawChat desligada`: faltam as três variáveis da central no app ia.

## 9. Voltar para a versão anterior (rollback)

O código e o banco voltam separadamente. Na maioria das vezes, só o código precisa voltar.

**Código** (um app por vez, comece pelo que deu problema):

1. No Git, descubra o commit da última versão boa (por exemplo, no histórico do GitHub).
2. Opção mais simples: faça um **revert** do commit com problema no `main` e clique em **Deploy** no app. O Easypanel
   constrói de novo a partir do código revertido.
3. Opção sem mexer no `main`: em **Source**, troque o branch por uma tag ou branch apontando para o commit bom (por exemplo
   `git tag versao-boa <commit>` e `git push origin versao-boa`) e clique em **Deploy**. Depois volte para `main`.
4. Confira o `/saude` (seção 7).

**Banco**: cada migração tem um `db/migracoes/desfazer_00X.sql`. **Só use se uma migração nova quebrou algo**, e na
ordem inversa (a última primeiro). Desfazer **apaga** as colunas/tabelas daquela migração e os dados dentro delas: faça
um backup no Supabase antes. Código antigo costuma funcionar com o banco mais novo, então o normal é voltar só o código.

**Os dois apps são independentes**: dá para voltar só o painel sem tocar no atendimento, e vice-versa. A única amarra
entre eles é o banco (mesmas migrações) e as variáveis iguais listadas na seção 5.

## 10. Teste local sem Easypanel (opcional)

Com Docker instalado, na raiz do projeto:

```
docker build -f Dockerfile.ia -t lawchat-ia .
docker build -f Dockerfile.painel -t lawchat-painel .
docker run --rm -p 8001:8000 --env-file .env lawchat-ia
docker run --rm -p 8002:8000 --env-file .env lawchat-painel
```

E abra `http://localhost:8001/saude` e `http://localhost:8002/saude`.

Sem Docker, os mesmos pontos de entrada sobem direto:

```
.venv/Scripts/python -m uvicorn app.entrada_ia:app --port 8001
.venv/Scripts/python -m uvicorn app.entrada_painel:app --port 8002
```

## O que ainda falta (pendências conhecidas)

- **Mídia antiga do disco**: arquivos enviados antes do bucket têm URL `{AGENTESIA_URL_PUBLICA}/midia/...`. No modo
  supabase o `/midia` local não é montado, então esses links deixam de abrir: suba de novo esses arquivos pela
  biblioteca e troque o link no roteiro (a linha antiga continua aparecendo e pode ser apagada normalmente).
- **Indexação na hora**: um documento novo na base de conhecimento, enviado pelo painel, é indexado pelo app ia em até
  30 segundos (antes era na hora, porque tudo rodava no mesmo processo).
