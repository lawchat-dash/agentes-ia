# ZapSign: o que a API permite e o que o LawChat pode passar a fazer

Para: dono do produto. Escrito a partir da documentação pública (docs.zapsign.com.br) e da leitura do nosso código.
Nenhuma chamada foi feita à API de verdade e nenhum token foi usado. Complementa `docs/FLUXO_CONTRATO.md`.

**Resposta curta:** sim, dá para fazer. Com o MESMO token que o escritório já salvou no painel (Bearer, guardado no
cofre) a ZapSign deixa ler e mexer em praticamente tudo da conta: modelos, documentos, signatários, plano e webhooks.
Hoje usamos 4 funções de mais de 20. As que mais valem, e são baratas:

1. **Cancelar a versão antiga** quando sai uma nova (hoje o link velho continua assinável).
2. **Trocar telefone, e-mail ou forma de autenticação** do signatário sem gerar contrato novo (sem gastar crédito).
3. **Entender por que o lead não assinou** (abriu? quantas vezes? travou na selfie?) e responder de acordo.
4. **Receber recusa, exclusão e falha de autenticação** pelo webhook, além do "assinou".
5. No painel: **cadastrar o webhook sozinho**, **ler todos os modelos** (hoje só os 20 primeiros), **mostrar plano e
   créditos**, **gerar um contrato de teste** e **baixar o PDF assinado com link renovado** (o link da ZapSign vence em 60 min).

Legenda usada no texto: **[DEPENDE]** = espera a correção do vínculo modelo↔produto que está em andamento em outro trabalho.

---

## 1. Funções da ZapSign

Base: produção `https://api.zapsign.com.br`, sandbox `https://sandbox.api.zapsign.com.br` (confirmado na documentação;
o comentário "a confirmar" em `app/canal/zapsign.py:16` pode sair). Cabeçalho `Authorization: Bearer <token>`.

| Função (endpoint) | O que faz | Já usamos? | Uso pelo agente | Uso pelo painel |
|---|---|---|---|---|
| Criar documento por modelo `POST /api/v1/models/create-doc/` | Gera o contrato a partir de um modelo DOCX trocando os `{{...}}`. 1 signatário. Devolve token, `sign_url`, links de arquivo (60 min). | **Sim** (`ZapSign.criar_de_modelo`, chamado por `_gerar_contrato`, `app/acoes.py:496`). Mandamos só modelo, external_id, nome, telefone, e-mail e variáveis. | Mandar também `metadata` (escritório, lead, versão), `folder_path` (`/LawChat/{produto}/`), `brand_name`, `allow_refuse_signature`. | Por modelo: pasta, marca, "permitir recusa", "lead recebe o PDF assinado pela ZapSign". Prévia do contrato com um cliente fictício. |
| Criar documento por arquivo `POST /api/v1/docs/` | Cria a partir de PDF, DOCX ou texto Markdown, com **vários signatários** (lead, testemunha, advogado), cada um com sua autenticação. Aceita prazo, observadores, ordem de assinatura. | Não | Procuração, declaração de hipossuficiência, termo LGPD; contrato com testemunha. | "Documentos complementares" por produto; prazo de assinatura; e-mail do responsável como observador. |
| Anexar documento `POST /api/v1/docs/{token}/upload-extra-doc/` | Junta um PDF ao principal para assinar tudo no mesmo link. Até 14 anexos; **1 crédito cada, não dá para remover**. | Não | Anexar procuração e declaração logo depois de gerar o contrato (1 link só). | Lista de anexos fixos por produto, com aviso do custo. |
| Detalhar documento `GET /api/v1/docs/{token}/` | Status do documento (`pending`, `signed`; `refused` se cancelado), `deleted`, e por signatário: status (`new`, `link-opened`, `signed`), `times_viewed`, `last_view_at`, `signed_at`, autenticação, reenvios. | **Sim** (`ZapSign.documento`), em `_verificar_assinatura` (`acoes.py:583`) e `_lembrar_assinatura` (`acoes.py:758`). Não lemos visualizações, `deleted`, recusa nem `external_id`. | "Já assinei" (já existe); responder "vi que você abriu mas não concluiu"; não lembrar contrato cancelado; conferir `external_id`. | Status ao vivo de cada versão; botão "baixar PDF" que pede link novo na hora. |
| Listar documentos `GET /api/v1/docs/?page=N` | Lista paginada com filtros por status, pasta, e-mail do signatário, datas. Tem cache (~1 min). **Não filtra por external_id.** | Não | Rede de segurança: achar um documento cujo token não foi gravado (timeout na criação). | Conciliar a pasta `/LawChat` com o nosso banco; relatório de pendentes e assinados. |
| Cancelar documento `POST /api/v1/refuse/` | Interrompe a assinatura: o documento vira recusado, ganha marca d'água e não pode mais ser assinado. Sem volta documentada. | Não | **Cancelar a versão anterior ao gerar a nova.** Cancelar quando o lead desiste (com confirmação humana). | Botão "Cancelar contrato" com motivo; interruptor "cancelar automaticamente a versão anterior". |
| Excluir documento `DELETE /api/v1/docs/{token}/` | Exclusão lógica e definitiva (some da tela, fica na API com `deleted=true`). Dispara `doc_deleted`. | Não | Não recomendado (prefira cancelar). | Ação administrativa com confirmação dupla. |
| Atualizar documento `PUT /api/v1/docs/{token}/` | Muda nome, prazo (`date_limit_to_sign`), pasta. | Não | Prorrogar prazo quando o lead pede tempo; mover para pasta "Assinados". | Editar prazo e pasta de um contrato pendente. |
| Reenviar notificações `POST /api/v1/docs/{token}/resend-notifications-bulk/` | A ZapSign reenvia por e-mail/WhatsApp dela a todos os pendentes. Tem intervalo mínimo. | Não | Plano B quando o lead diz que não recebeu pelo nosso número. | Botão "reenviar pela ZapSign". |
| Adicionar signatário `POST /api/v1/docs/{token}/add-signer/` | Inclui alguém num documento em andamento; devolve o link dele. | Não | Testemunha, advogado, representante (ex.: esposa assinando pelo marido). Também é o caminho para **trocar a pessoa** (adiciona o novo e remove o antigo). | "Signatários adicionais fixos" por modelo. |
| Atualizar signatário `POST /api/v1/signers/{signer_token}/` | Muda nome, telefone, e-mail, CPF e **autenticação** de quem ainda não assinou. Com `send_automatic_*` funciona como lembrete oficial (no máximo 1 a cada 30 min). | Não | **Trocar telefone/e-mail sem nova versão**; afrouxar selfie ou trocar SMS por WhatsApp (se o escritório permitir). | Editar contato e autenticação na linha do contrato; política de autenticação por modelo. |
| Detalhar signatário `GET /api/v1/signers/{signer_token}/` | Status, visualizações, IP, geolocalização, foto da selfie, reenvios. | Não (lemos o signatário de dentro do documento) | Diagnóstico fino quando trava. | Detalhe da assinatura (IP, geo, hora) para anexar ao processo. |
| Remover signatário `DELETE /api/v1/signer/{signer_token}/remove/` | Remove quem não assinou. Não remove o único signatário. | Não | Completa a troca de signatário. | Gerenciar signatários de um contrato pendente. |
| Trilha de auditoria `GET /api/v1/docs/signer-log/{token}` | Histórico (visualizou, leu, reconhecimento facial...) em JSON ou PDF. | Não | Dizer ao lead em que passo parou ("a validação facial falhou"). | Linha do tempo do contrato; baixar o relatório. |
| Listar modelos `GET /api/v1/templates/?page=N` | Modelos da conta, **20 por página**, com `active`, `template_type` (docx/pdf), pasta, data. | **Sim** (`ZapSign.modelos`), mas **só a 1ª página** e sem `active`/tipo. | Nenhum. | Ler todas as páginas; mostrar só ativos e DOCX; ocultos com motivo. |
| Detalhar modelo `GET /api/v1/templates/{token}/` | Variáveis com `label` (a pergunta), `help_text`, `required`, opções; e a configuração do 1º signatário (selfie, documento, código). | **Em parte** (`variaveis_do_modelo` usa só os nomes). | Usar `label` como pergunta ao lead e avisar antes: "vai pedir uma selfie e a foto do RG". | Mostrar obrigatório, opções e "este modelo exige selfie"; sugerir obrigatórios. |
| Atualizar modelo `PUT /api/v1/templates/{token}/` | Muda nome, idioma, 1º signatário, pasta, página pós-assinatura. Não troca o DOCX. | Não | Nenhum (agente não mexe em modelo). | Avançado: autenticação padrão e página de "obrigado". |
| Plano `GET /api/v1/info-plan` | Nome do plano, créditos, situação do pagamento, vencimento. | Não | Antes de gerar: sem crédito ou pagamento pendente → "equipe envia" sem gastar tentativa. | **Testar token mostrando plano e créditos**; alerta de créditos baixos. |
| Webhooks `POST /api/v1/user/company/webhook/` (+ `/header/`, `/delete/`) | Cadastra pela API a URL que recebe os eventos, com cabeçalhos próprios. Devolve um id. **Não há como listar.** | Não (hoje o escritório cola a URL à mão) | Indireto: o "assinou" chega na hora. | **Botão "Configurar aviso automaticamente"**; guardar o id. |
| Reprocessar `POST /api/v1/docs/{token}/reprocess-doc/` | Reenvia os webhooks de um documento e/ou refaz o PDF assinado. | Não | Nenhum. | "Testar aviso de assinatura" no tutorial. |
| Validar PDF `POST /api/v1/validate-pdf-signature/` | Diz se um PDF assinado é íntegro e quem assinou. | Não | Lead manda o PDF dizendo "já assinei": conferir. | Ferramenta "validar PDF". |
| OneClick, lote, consulta de antecedentes, JWT | Aceite com 1 clique; assinatura em massa (token pessoal); checagens; autenticação alternativa. | Não | OneClick para termo LGPD no início, se o escritório quiser. | Futuro: advogado assina em lote. |

---

## 2. O que o AGENTE pode passar a fazer (em ordem de prioridade)

Princípio que mantemos: **a IA conversa, o código age**. O agente só sinaliza (intenção ou ferramenta); a ação vai para
a fila (`agentesia_acoes`), o executor (`app/acoes.py`) chama a ZapSign e **relê o documento antes de decidir**.

| # | Situação | O que o código faz | Endpoint | Onde entra no código | Depende? |
|---|---|---|---|---|---|
| A1 | Sai a versão nova do contrato | Cancela a versão anterior na ZapSign com motivo "Substituído pela versão N", sem avisar o lead | `POST /refuse/` | Depois de `servico.gravar_gerado` em `_gerar_contrato` (`acoes.py:548`): enfileirar ação nova `cancelar_contrato` para cada versão substituída. `gravar_gerado` passa a devolver os tokens substituídos. | Não |
| A2 | Lead diz "já assinei" | **Já existe** (intenção `diz_que_assinou` → `verificar_assinatura`, `pipeline.py:554`). Melhorar a resposta quando não assinou: se nunca abriu → reenviar link; se abriu e não concluiu → "travou em alguma etapa? É a selfie?"; se cancelado → não mandar link velho. | `GET /docs/{token}/` | `_documento` (`zapsign.py:61`) passa a ler `times_viewed`, `last_view_at`, `deleted`, `external_id`; `situacao_da_assinatura` (`contrato/assinatura.py:31`) ganha `abriu_sem_assinar` e `cancelado`; textos novos em `contrato/dados.py`. | Não |
| A3 | Lead pede o link de novo | **Já existe** (`pediu_link` → `_reenviar_link`, `acoes.py:745`). Melhorar: reler o documento antes (não mandar link de contrato cancelado); se o lead diz que não chega pelo WhatsApp, pedir à ZapSign que envie pelo canal dela. | `GET /docs/{token}/`; plano B `POST /docs/{token}/resend-notifications-bulk/` | `_reenviar_link` | Não |
| A4 | Lead informa outro telefone ou e-mail para o contrato | Atualiza o signatário **sem gerar nova versão** e reenvia o link | `POST /signers/{signer_token}/` | Nova ação `atualizar_signatario`. Hoje telefone/e-mail novo cai em `dados_confirmados` → nova versão; a regra passa a ser: se só mudou contato, atualizar. Decisão em `pipeline._acoes_do_contrato` (`pipeline.py:525`) comparando o hash só dos campos do corpo do contrato. | Não |
| A5 | Lead não consegue fazer selfie / o código por SMS não chega | Se o escritório permitir (política por modelo), troca a autenticação (ex.: selfie → assinatura na tela; SMS → WhatsApp) e avisa o lead | `POST /signers/{signer_token}/` | Mesma ação `atualizar_signatario`, campo `auth_mode`. Gatilho: intenção nova `dificuldade_assinatura` ou webhook `signer_authentication_failed`. Sem permissão: nota para a equipe. | Política por modelo **[DEPENDE]** |
| A6 | Lead recusa pelo link | Para os lembretes, deixa nota com o motivo, pausa a IA e dispara automação `contrato_recusado` | Webhook `doc_refused` + releitura `GET /docs/{token}/` | `receber_webhook` (`servico.py:127`) põe `verificar_assinatura` também para recusa; `_verificar_assinatura` trata `refused/rejected`. Para o lead **poder** recusar: `allow_refuse_signature=true` no create-doc (hoje é `false` por padrão). | Não |
| A7 | Lead assinou | Baixar o PDF assinado para o nosso storage (hoje gravamos um link que **vence em 60 min**); opcional: mandar o PDF ao lead | `GET /docs/{token}/` (`signed_file`) | `marcar_assinado` (`servico.py:108`) grava o caminho no nosso storage em vez da URL; ação nova `guardar_pdf_assinado`. Envio ao lead: `enviar_mensagem` com `url_arquivo`, ou `send_automatic_whatsapp_signed_file=true` na criação. | Não |
| A8 | Webhook `doc_viewed` / lembrete chegando | Lembrete mais esperto: se o lead abriu há poucos minutos, adia; texto diferente para "abriu e não concluiu" | `GET /docs/{token}/` | `_lembrar_assinatura` (`acoes.py:758`) já relê o documento: só usar os campos novos. | Não |
| A9 | Antes de gerar | Conferir plano e créditos; sem crédito → "equipe envia" direto, sem tentativa | `GET /info-plan` | Início de `_gerar_contrato`, com cache de alguns minutos. | Não |
| A10 | Contrato com prazo (se o escritório quiser) | Define o prazo logo depois de criar; perto de vencer, o agente avisa; se o lead pedir, prorroga | `PUT /docs/{token}/` (`date_limit_to_sign`) | Depois de `gravar_gerado`; prorrogação = ação `prorrogar_contrato`. | Config por modelo **[DEPENDE]** |
| A11 | Representante / testemunha / advogado | Adicionar signatário (e remover o original quando é troca) e mandar o link novo | `POST /docs/{token}/add-signer/`, `DELETE /signer/{token}/remove/` | Ação `adicionar_signatario`; sempre com confirmação humana na primeira versão. | Não |
| A12 | Documentos complementares | Procuração e declaração anexadas ao mesmo link (1 crédito cada) ou criadas por Markdown | `upload-extra-doc/` ou `POST /docs/` | Depois de `gravar_gerado`, se o produto tiver anexos configurados. | **[DEPENDE]** |
| A13 | Avisar antes o que vai ser pedido | "Na assinatura vai pedir uma selfie e a foto do RG" | `GET /templates/{token}/` (`signers[]`) | Guardar no config do modelo ao salvar no painel; o texto do link usa um marcador novo `{exige}`. | **[DEPENDE]** |

### Como cada uma vira "@" no editor de prompt

Hoje o menu "@" tem uma ferramenta só, `@ZapSign` (`painel/src/data/handoffTargets.ts:37`, tool `zapsign`), que o back
reconhece em `TOOLS_DE_ACAO` (`app/cerebro/catalogo.py:28`) e significa "gerar contrato". A proposta é um submenu, mesmo
padrão de rótulo amigável no editor e "acionar tool `x`" no envio:

| Rótulo no "@" | Tool | Quem dispara de fato | Observação |
|---|---|---|---|
| `@ZapSign › Gerar contrato (modelo X)` | `zapsign:<id_modelo>` | Ferramenta + `dados_confirmados` | Um item por modelo ligado ao produto. `@ZapSign` sozinho continua valendo (alias legado = modelo padrão do produto). **[DEPENDE]** |
| `@ZapSign › Verificar assinatura` | `zapsign_verificar` | Intenção `diz_que_assinou` (já existe) | O "@" serve para o prompt dizer QUANDO conferir; o código já faz. |
| `@ZapSign › Reenviar link` | `zapsign_reenviar` | Intenção `pediu_link` (já existe) | Idem. |
| `@ZapSign › Atualizar contato do signatário` | `zapsign_contato` | Fatos `telefone_contrato` / `email` mudaram e o contrato já foi gerado | Sem gastar versão nem crédito. |
| `@ZapSign › Ajudar com a assinatura` | `zapsign_ajuda` | Intenção nova `dificuldade_assinatura` | Lê visualizações e autenticação; troca autenticação só se a política permitir. |
| `@ZapSign › Cancelar contrato` | `zapsign_cancelar` | Só com confirmação humana (nota + botão no painel) | O cancelamento automático da versão antiga (A1) não precisa de "@". |
| `@ZapSign › Enviar contrato assinado` | `zapsign_pdf` | Depois de `contrato_assinado` | Manda o PDF do nosso storage. |

Regras para não quebrar nada: (1) o editor continua gravando o rótulo e expandindo no envio; (2) `TOOLS_DE_ACAO` e
`FERRAMENTAS_DO_PAPEL` (`catalogo.py:39`) ganham os nomes novos, liberados só com a função de contrato ligada, como hoje;
(3) as ações de conferir e reenviar continuam sendo decididas pelo código (o "@" só documenta no prompt quando usar).

---

## 3. O que o PAINEL pode passar a fazer

### 3.1 Tutorial guiado "Conectar ZapSign" (substitui a tela `IntegracaoZapSign.tsx` e o diálogo `ZapsignDialog.tsx`)

Hoje há dois caminhos com regras diferentes, três textos diferentes para "onde pegar o token", três dicionários de
variáveis (`MAPEAMENTO_PADRAO`, `CAMPOS_SISTEMA`, `CAMPO_SERVIDOR`) e promessas que não acontecem (o diálogo diz que
configura o webhook, mas `registrarWebhook` em `useZapsign.ts` é vazio). Proposta: um fluxo só, 7 passos, cada um com
selo (a fazer / conferindo / ok / atenção / erro), progresso salvo em `config.tutorial`, e o selo do ambiente sempre no
topo ("TESTE – sem validade jurídica" em amarelo, ou "PRODUÇÃO"). O navegador nunca fala com a ZapSign: tudo pelo servidor.

**Passo 1 · Onde vamos usar**
> Quer testar antes de usar com clientes? Recomendamos começar no ambiente de Teste: é grátis e os contratos não têm validade jurídica.
> [Começar no Teste] [Já vou usar com clientes (Produção)]
>
> *Teste:* O Teste é uma conta separada da ZapSign. Crie a sua em sandbox.app.zapsign.com.br. Seus modelos precisam ser criados lá também.
> *Produção:* A Produção exige o plano de API da ZapSign.

**Passo 2 · Token da ZapSign**
> Abra a ZapSign em Configurações › Integrações › ZAPSIGN API e copie o token. [Abrir a página do token ↗]

O botão leva a `…/conta/configuracoes/integration?tab=api-zapsign` no ambiente escolhido (o de produção, a confirmar).
Conferência pelo servidor com `GET /info-plan` (e `GET /templates/?page=1`):
- 200 → "Conta conectada. Plano {nome}, {n} créditos, {m} modelos."
- 401 → "Esse token não foi aceito. Copie de novo, sem espaços."
- 403 → o servidor tenta o OUTRO ambiente; se der certo: "Esse token é do ambiente de {Teste/Produção}. [Usar {Teste/Produção}]". Se não: "Token sem permissão neste ambiente."
- 402 → "Sua conta ZapSign não tem o plano de API. Contrate o plano ou comece pelo ambiente de Teste. [Usar Teste]" (hoje diz "pagamento pendente", que confunde).
- 429/5xx → "A ZapSign está ocupada. Tentando de novo…"

Sempre visível abaixo do campo: "Salvo · termina em {final} · {Teste|Produção}".

**Passo 3 · Modelo do contrato** **[DEPENDE]**
> Escolha o modelo que a IA vai usar. Mostramos só modelos ativos em Word (DOCX).

Lê todas as páginas, ordena pela última alteração, com busca. "Ocultos (inativos ou PDF)" com o motivo. Avisos:
- sem variáveis: "Este modelo não tem campos {{ }}: o contrato sairia sem os dados do cliente. Na ZapSign, escreva os campos entre chaves duplas, como {{NOME}} e {{CPF}}."
- PDF: "Modelos em PDF não geram contrato pela API. Use um modelo em Word (DOCX)."
- selfie/documento: "Este modelo pede selfie ou foto do documento. Muitos clientes desistem nessa hora."
- 2 ou mais signatários: "O escritório também assina este contrato. O cliente recebe o link dele pelo WhatsApp."

**Passo 4 · Ligar os campos do modelo aos dados do cliente** (mapeamento automático por nome)
> Ligamos sozinhos os campos que reconhecemos. Confira os amarelos e decida os vermelhos.

Regra (no servidor, um dicionário só): normalizar `variable`, `label` e `help_text` (sem acento, sem `{{ }}`, `_` e `-`
viram espaço, minúsculas) e tentar, nesta ordem: (1) nome exato do `MAPEAMENTO_PADRAO` → verde "ligado automaticamente";
(2) sinônimos ("nome completo | nome cliente | contratante" → nome; "logradouro | rua" → endereço; "uf" → estado;
"data | data assinatura" → data de hoje) → verde; (3) palavra contida (`CPF_CONTRATANTE` contém "cpf") → amarelo
"sugestão, confira"; senão vermelho "sem ligação", com [campo do cliente ▾] [data de hoje] [texto fixo] [deixar em branco].
Resumo: "14 ligados · 1 para conferir · 1 sem ligação". Continuar só sem vermelho sem decisão.
[Veja como fica] mostra variável → valor com um cliente fictício (Maria da Silva, CPF 123.456.789-09, Rua das Flores, 100, Centro, Belo Horizonte/MG).

**Passo 5 · O que a IA precisa pedir ao cliente**
> A IA só gera o contrato depois de ter estes dados. Os desmarcados vão em branco se o cliente não informar.

Caixas pré-marcadas por: campos ligados + `required` do modelo + obrigatórios padrão. Grava `modelos[].obrigatorios`, que hoje nenhuma tela grava.

**Passo 6 · Aviso de assinatura (webhook)**
> Para saber na hora que o cliente assinou, a ZapSign precisa avisar o LawChat. [Configurar automaticamente]

Ver seção 4. Se a conta não permitir:
> Sua conta não permitiu criar o aviso automaticamente. Na ZapSign, vá em Configurações › Integrações › ZapSign API › Webhooks, cole o endereço abaixo e marque "Todos os eventos", sem filtro de modelo. [Copiar endereço]

Rodapé: "Sem o aviso, o sistema ainda confere a assinatura quando o cliente diz que assinou e nos lembretes, mas demora mais."

**Passo 7 · Contrato de teste**
> Vamos gerar um contrato com dados fictícios para você assinar e ver tudo funcionando. [Gerar contrato de teste]
> *Em Produção:* "Isso usa 1 documento do seu plano. Continuar?"

Lista que vai se marcando: Contrato criado [Abrir e assinar ↗] → Aguardando a sua assinatura… → Assinatura confirmada →
Aviso automático recebido (se não chegar em 60 s: "O aviso não chegou. Confira o passo 6.") → Campos preenchidos
(compara `answers` com a prévia; campo vazio ou `{{X}}` literal fica vermelho). O teste usa `external_id = teste-{id}` e
`metadata {teste: true}`; o webhook reconhece e não mexe em lead nenhum.

**Final · Ligar no agente**
> Tudo pronto. [Gerar contrato na ZapSign: ligado]

Confere se o agente tem as etapas "assinatura" e "contrato_assinado". No Teste: "Você está no ambiente de Teste. Os
contratos não têm validade jurídica. [Passar para Produção]" (volta ao passo 2 e obriga a escolher o modelo de novo,
porque os modelos do Teste não existem na Produção).

**Depois do teste (avançado, padrões já bons):** lembretes em botões [2 h] [24 h] [72 h] [+], de 0,5 a 240 h, até 5;
vídeo pós-assinatura conferido (abre, é vídeo, até 16 MB); as 11 mensagens editáveis com prévia e erro se faltar `{link}`.

### 3.2 Status dos contratos por lead
No card do lead, uma linha por versão: "Não abriu" / "Abriu 3 vezes, último acesso 14:02" / "Assinou em 12/11 10:31",
autenticação exigida, e botões: [Baixar PDF] (pede link novo na hora ou usa o nosso storage), [Reenviar pela ZapSign],
[Editar telefone/e-mail], [Cancelar contrato] (com motivo), [Linha do tempo] (trilha de auditoria).
Rotas novas: `GET /leads/{id}/contratos` (relê na ZapSign com cache curto) e `POST /contratos/{id}/{acao}`.

### 3.3 Saúde contínua
Ao abrir Integrações e 1 vez por dia: token válido, plano pago, créditos, modelo ainda existe/ativo/DOCX, variáveis ligadas
ainda existem, dias desde o último aviso recebido. Problema vira selo e nota: "O modelo 'X' mudou na ZapSign: {{CPF}} não
existe mais. [Revisar ligação]".

### 3.4 Correções pequenas que o painel precisa (back-end)
- `ZapSign.modelos()` ler todas as páginas e devolver `active`, `template_type`, `last_update_at`.
- `variaveis_do_modelo` devolver `label`, `help_text`, `required`, `options`.
- `_motivo` (`zapsign.py:72`): 402 → "sem plano de API"; 403 → "ambiente"; 404 na geração → "modelo" (problema do escritório, sem repetir; hoje vira repetição + "imprevisto" ao lead); 429 → repetir com espera, não "limite"; 406 não é "fora do ar".
- `PUT /integracoes/zapsign` manter o ambiente quando ele não vem (o diálogo hoje volta para produção sem avisar).
- Não trocar mapeamento vazio pelo padrão; recusar mensagem sem `{link}`.
- Desconectar de verdade: apagar token, segredo e webhook (hoje `clearToken` não faz nada).

---

## 4. Webhooks: quais eventos assinar e o que fazer

Como funciona: a ZapSign faz POST em JSON na nossa URL e espera **HTTP 200 rápido**; senão repete (quantidade e intervalo
não documentados) e pode duplicar. Não há assinatura HMAC: a segurança é um segredo nosso, que deve ir no **cabeçalho**
`x-agentesia-segredo` (a rota `app/main.py` já aceita) em vez de `?segredo=` na URL. Os eventos de documento trazem
`external_id` (= id do nosso contrato) e `metadata`. Pela API, o tipo aceita `""` (todos: criado, assinado, removido,
recusado), `doc_signed`, `doc_created`, `doc_deleted`, `doc_refused`, `email_bounce`. **`doc_viewed`, `doc_expired` e os
alertas de prazo parecem só cadastráveis pela tela da ZapSign** (confirmar no sandbox).

Cadastro automático (passo 6): o servidor chama `POST /api/v1/user/company/webhook/` com a URL do escritório **sem**
`?segredo=`, tipo `""` e `headers [{name: "x-agentesia-segredo", value: segredo}]`; outro cadastro para `email_bounce`.
Guarda os ids em `config.webhook_ids` (o `ZapsignDialog.tsx` já espera um `webhook_id`). Ao trocar token/ambiente ou
desconectar: `DELETE …/webhook/delete/` com o id e cria de novo. Como não dá para listar, o tutorial avisa: "se você já
colou o endereço à mão, apague o antigo na ZapSign". Alternativa que não mexe na conta inteira (útil se o escritório tem
webhooks de outro sistema): cadastrar por documento (`doc_token`) logo depois de criar o contrato.

| Evento | Assinar? | O que fazer |
|---|---|---|
| `doc_signed` | **Sim** (já tratamos) | Sai a CADA assinatura (traz `signer_who_signed`). Continuar: enfileirar `verificar_assinatura` e decidir pela releitura. Atenção: pode sair depois de um cancelamento; a releitura tem de tratar `refused/rejected` como cancelado, nunca como assinado nem "pendente". |
| `doc_refused` | **Sim** | Releitura confirma → contrato "recusado" (ou "cancelado", se fomos nós), cancela lembretes (`servico.cancelar_lembretes`), nota com `rejected_reason`, pausa a IA, automação `contrato_recusado`. Se o cancelamento foi o A1 (versão substituída), só registrar. |
| `doc_deleted` | **Sim** | Marcar o contrato como excluído, cancelar lembretes, nota à equipe. |
| `email_bounce` | Sim (cadastro próprio) | E-mail do lead não existe: o agente pede outro e-mail; o código atualiza o signatário (A4). |
| `signer_authentication_failed` | Se a tela permitir | Lead estourou as tentativas de selfie/validação: nota à equipe e mensagem do agente oferecendo ajuda; com a política do escritório, trocar a autenticação (A5). |
| `doc_viewed` / `doc_read_confirmation` | Opcional (pela tela) | Registrar "lead abriu"; o lembrete seguinte fica contextual ou é adiado (A8). |
| `doc_expiration_alert` / `doc_expired` | Só se usarmos prazo | Avisar o lead antes de vencer e oferecer prorrogação; vencido → nota e nova versão se o lead quiser. Como talvez não dê para cadastrar pela API, a consulta periódica de reserva cobre. |
| `doc_created`, `created_signer`, `signature_notification_sent`, `background_check_completed` | Não | Gravar como "ignorado" (como hoje), **sem guardar o corpo inteiro** (tem CPF, telefone, geolocalização). |

Ajustes no receptor (`servico.receber_webhook`, `servico.py:127`): aceitar `doc_refused` e `doc_deleted` (hoje só
`doc_signed` e um `signer_signed` que não existe na ZapSign); conferir `external_id` == id do contrato (divergiu: ignora e
registra); ignorar evento com `sandbox=true` quando o escritório está em produção (e vice-versa); JSON inválido devolve
400, não 500 (evita repetição à toa); guardar só os campos necessários dos eventos ignorados (LGPD).

---

## 5. Plano de implementação

Cada etapa é pequena e testável sozinha. Testes com `httpx.MockTransport` (nada de API real), no padrão de `tests/test_contrato.py`.

**Etapa 1 · Cliente ZapSign completo (base de tudo)** — não depende
- `app/canal/zapsign.py`: `_documento` lê `external_id`, `deleted`, `times_viewed`, `last_view_at`, `auth_mode`; métodos novos `cancelar`, `atualizar_signatario`, `reenviar_pela_zapsign`, `plano`, `criar_webhook`, `apagar_webhook`, `reprocessar`, `adicionar_signatario`, `remover_signatario`, `trilha`; `modelos()` paginado com `active/template_type`; `variaveis_do_modelo` com label/required/options; `_motivo` corrigido (402, 403, 404, 406, 429).
- Testes: `tests/test_zapsign_cliente.py` (paginação, cada endpoint com corpo esperado, mapa de erros).

**Etapa 2 · Cancelar a versão antiga + tratar recusa e exclusão** — não depende
- `app/contrato/servico.py`: `gravar_gerado` devolve os tokens substituídos; `receber_webhook` aceita `doc_refused`/`doc_deleted`, confere `external_id`, olha `sandbox`, não guarda o corpo dos ignorados.
- `app/acoes.py`: ação `cancelar_contrato` (+ descrição em `DESCRICOES`); `_verificar_assinatura` trata cancelado/recusado/excluído; `_reenviar_link` e `_lembrar_assinatura` não mandam link morto.
- `app/contrato/assinatura.py`: situações `cancelado` e `abriu_sem_assinar`.
- `app/main.py`: JSON inválido → 400.
- Testes: versão 2 gerada cancela a 1; `doc_signed` depois de cancelar não marca assinado; `doc_refused` pausa e para lembretes; `external_id` errado é ignorado.

**Etapa 3 · Agente mais esperto na assinatura** — não depende (A5 depende da política por modelo)
- Respostas para "já assinei" conforme abriu/não abriu (textos em `app/contrato/dados.py`); lembrete adiado se abriu há pouco.
- Ação `atualizar_signatario` (contato novo sem nova versão) e regra em `pipeline._acoes_do_contrato`.
- Baixar PDF assinado para o nosso storage (`marcar_assinado` grava caminho, não URL temporária); ação `guardar_pdf_assinado`.
- Checagem de plano/créditos antes de gerar.
- Testes: lead troca telefone → 1 chamada a `/signers/`, nenhuma versão nova; "já assinei" sem abrir → reenvia link; cenários de avaliação em `avaliacao/` para "abriu e não concluiu".

**Etapa 4 · Webhook automático e diagnóstico no painel** — não depende
- `app/gestao/rotas.py`: `GET /integracoes/zapsign/diagnostico`, `POST /integracoes/zapsign/webhook`, `POST /integracoes/zapsign/teste`; `PUT /integracoes/zapsign` testa com `info-plan`, tenta o outro ambiente no 403, mantém o ambiente.
- `painel/src/hooks/useZapsign.ts`: `registrarWebhook`/`removerWebhook` de verdade; mandar o ambiente.
- Testes: cadastro guarda o id; troca de token apaga o antigo; 402/403 caem no passo manual.

**Etapa 5 · Tutorial guiado** — **[DEPENDE]** nos passos 3, 4, 5 e 7 (modelo por produto)
- Novo componente único (por exemplo `painel/src/components/integrations/ConectarZapSign.tsx`) usado pela tela de Integrações e pelo configurador de produto; aposenta a lógica duplicada de `IntegracaoZapSign.tsx` e `ZapsignDialog.tsx`.
- Mapeamento automático e sinônimos num dicionário só, no servidor (`app/contrato/modelos.py`), exposto em `GET /integracoes/zapsign/modelos/{id}/sugestao`.
- Testes: `{{NOME COMPLETO}}`, `{{CPF_CONTRATANTE}}`, `{{Endereco}}` ligam certo; modelo sem variáveis bloqueia; mensagem sem `{link}` é recusada.

**Etapa 6 · "@" por função e por modelo** — **[DEPENDE]** (modelo por produto)
- `painel/src/data/handoffTargets.ts`: itens `ZapSign › …` e alias `ZapSign` → gerar contrato.
- `app/cerebro/catalogo.py`: `TOOLS_DE_ACAO`/`FERRAMENTAS_DO_PAPEL` com as tools novas; `app/cerebro/turno.py` reconhece `zapsign:<id_modelo>`.
- Testes: prompt antigo com `@ZapSign` continua gerando o contrato; tool nova só aparece com a função de contrato ligada.

**Etapa 7 · Painel de contratos por lead** — depende das etapas 1 e 3
- Rotas `GET /leads/{id}/contratos` e ações por contrato; tela no card do lead.

**Antes de depender de algo, confirmar no sandbox** (lacunas da documentação): se o GET do documento traz `sign_url`
(por isso o link continua vindo da criação, como hoje); se cancelar dispara `doc_refused` ou só `doc_signed`; o status
exato depois de cancelar (`refused` ou `rejected`); se `doc_viewed`/`doc_expired` são aceitos no cadastro pela API; se a
listagem de documentos devolve `external_id`; quantas vezes a ZapSign repete um webhook.

Limites a respeitar: 500 pedidos/min por IP ou token (acima: 429, esperar o minuto virar); lembrete individual no máximo
1 a cada 30 min; arquivos até 10 MB; até 14 anexos (1 crédito cada, sem remoção); links de arquivo valem 60 min; modelo
dinâmico só DOCX; não dá para remover o único signatário; datas em UTC.
