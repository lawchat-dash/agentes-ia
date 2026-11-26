# Ações com "@" no prompt (menu do arroba, referências, grupo de agentes)

Desenho, 25/11/2026. **Nada aqui está implementado.** Serve para o dono do produto decidir o que entra e em que
ordem, e para quem for programar saber onde mexer.

Base do estudo:
- referência de um concorrente (LíderHub): estrutura das telas do menu "@", da aba Referências, do grupo de agentes,
  da configuração do agente e do sandbox. Estudamos **como funciona**, sem copiar textos;
- o nosso motor (`app/cerebro/catalogo.py`, `app/cerebro/turno.py`, `app/pipeline.py`, `app/automacoes.py`,
  `app/acoes.py`, `app/gestao/laboratorio.py`), o painel (`painel/src/components/agent/RichPromptEditor.tsx`,
  `painel/src/telas/Agente.tsx`) e a documentação da Helena (`docs/HELENA_API.md`);
- o desenho da recepção: [AGENTE_TRIAGEM.md](AGENTE_TRIAGEM.md).

Documentos ligados: [DESENHO.md](../DESENHO.md), [AGENTE_TRIAGEM.md](AGENTE_TRIAGEM.md),
[HELENA_API.md](HELENA_API.md), [BASE_DE_CONHECIMENTO.md](BASE_DE_CONHECIMENTO.md).

---

## 0. O menu do "@" que vamos ter

Quem escreve o prompt digita **"@"** e abre um menu **por categorias, cada uma com a contagem de itens**. Teclado:
setas sobem e descem, **Enter** escolhe, **Esc** fecha, **seta para a esquerda** volta à lista de categorias, e digitar
filtra ("@etiq", "@análise"). O nosso editor (`RichPromptEditor.tsx`) já faz o teclado e a volta às categorias. Falta
ter as categorias certas.

| Categoria (contagem) | De onde vêm os itens | Tipo | O que acontece quando o agente usa |
|---|---|---|---|
| **Agentes** | Membros do grupo (seção 4) | Troca de agente | A conversa passa para aquele agente (`transferir_para`) |
| **Status** | Colunas (etapas) do painel de CRM da Helena escolhido no agente | Ação | Move o card para a coluna |
| **Departamentos** | Equipes da Helena | Ação | Transfere o atendimento para a equipe |
| **Responsáveis** | Atendentes (usuários) da Helena | Ação | Põe a pessoa como responsável pela conversa |
| **Notificações internas** | Avisos cadastrados no LawChat (texto + quem recebe) | Ação | Avisa a equipe, **sem** tirar a conversa da IA |
| **Etiquetas** | Etiquetas da Helena | Ação | Põe a etiqueta no contato (e "@Tirar etiqueta" para remover) |
| **Origem** | Campanhas e anúncios já vistos nos leads do escritório + categorias do classificador de anúncio | Condição | Vira o nome da origem no texto; o motor diz ao modelo de onde o lead veio |
| **Dados gerais** | Configurações > Informações do escritório | Variável | Vira o valor (nome, CNPJ, OAB, endereço, Instagram, Facebook, site, responsável legal, telefone). Campo vazio aparece com **⚠ "Preencha em Configurações"** |
| **Dados do lead** | Fatos do lead | Variável | Primeiro nome, cidade, benefício... (o que o extrator já gravou) |
| **Ferramentas** | Fixas do LawChat | Capacidade ou ação | Base de conhecimento, Calculadora, Data e hora, Salvar nome, Gerar resumo, Ativar áudio, Desativar áudio, Desativar IA |
| **Mensagens** | Mensagens rápidas do LawChat (texto + mídia da Biblioteca) e respostas rápidas da Helena | Ação | Envia o modelo pronto |
| **ZapSign** | Modelos de contrato da conta ZapSign do escritório | Ação | Gera o contrato daquele modelo com os dados confirmados |
| **Google Calendar** | Tipos de reunião configurados (agenda + duração + presencial/online) | Ação | Oferece horários livres e marca a reunião |
| **AdvBox** | Ações liberadas: criar cliente, criar processo/oportunidade | Ação | Cadastra o cliente (e o caso) no software jurídico |

Três integrações são novas: **Google Calendar**, **ZapSign por modelo** (hoje o modelo é fixo por agente) e **AdvBox**.
Elas aparecem no menu mesmo sem conexão, com contagem **0** e o atalho "Conectar", como na referência.

**Uma diferença de nome importante.** No nosso editor de hoje, a categoria chamada "Departamento" lista os **agentes
do funil**. Na Helena (e na referência), departamento é a **equipe humana**. A categoria atual passa a se chamar
**Agentes**, e "Departamentos" passa a ser a equipe da Helena.

---

## 1. O que é, e como fica salvo no prompt

### 1.1 Ideia

O prompt deixa de ser só texto e passa a ter **peças ligadas a coisas reais** do escritório. Quem escreve vê um
"chip" colorido com o nome; o banco guarda o **id**. Exemplos de frases no prompt:

- "Assim que ele contar o acidente, marque @Acidente e mude o status para @Análise."
- "Se já tem advogado, explique com educação, marque @Desqualificado e use @Desativar IA."
- "Se pedirem o CNPJ, informe @CNPJ e o endereço @Endereço do escritório."
- "Se o lead veio de @facebook, não pergunte de onde ele conheceu o escritório."
- "Quando ele aceitar a proposta, passe para @Contratos."

### 1.2 Formato gravado (token estável)

```
@[tipo:id|Rótulo]
```

| Exemplo gravado | O que é |
|---|---|
| `@[status:7f3c…e1|Análise]` | Coluna "Análise" do painel de CRM (id da etapa na Helena) |
| `@[departamento:12ab…|Jurídico]` | Equipe da Helena |
| `@[responsavel:9d0e…|Dra. Ana]` | Atendente (userId da Helena) |
| `@[etiqueta:44c2…|Falta Laudo]` | Etiqueta da Helena (por **id**, não por nome) |
| `@[tirar_etiqueta:44c2…|Falta Laudo]` | Remover a etiqueta |
| `@[notificar:aviso-urgente|Avisar equipe: perícia marcada]` | Aviso interno do LawChat |
| `@[mensagem:lc-boasvindas|bemvindo]` | Mensagem rápida do LawChat (ou `helena-qr:<id>` da Helena) |
| `@[zapsign:5f8a…|Contrato auxílio-acidente]` | Modelo de contrato na ZapSign |
| `@[agenda:reuniao-30-online|Reunião online 30 min]` | Tipo de reunião do Google Calendar |
| `@[advbox:criar_cliente|Criar cliente no AdvBox]` | Ação no AdvBox |
| `@[agente:closer|Closer]` | Outro agente do grupo |
| `@[origem:ad09-pais|ad09-PAIS]` | Origem/campanha |
| `@[var:escritorio.cnpj|CNPJ]` | Dado do escritório |
| `@[var:lead.primeiro_nome|nome]` | Dado do lead |
| `@[ferramenta:desativar_ia|Desativar IA]` | Ferramenta |

**Por que assim:**
- **O nome pode mudar e nada quebra.** Se alguém renomeia "Análise" para "Em análise" na Helena, o id é o mesmo: o
  editor e o modelo passam a ver o nome novo na próxima sincronização.
- **O rótulo vai junto** para o prompt continuar legível se for copiado, exportado ou aberto num editor simples, e para
  a aba Referências mostrar "era *Falta Laudo*" quando o item for apagado.
- **O que vem antes dos dois-pontos** diz qual lista consultar. Um texto qualquer como "@fulano" num e-mail não vira
  token: só vira o que tem o formato completo.
- O formato é texto simples: cabe no campo `instrucao` de hoje (`agentesia_agente_etapas`, até 12 mil caracteres),
  sem mudar a coluna.

**Compatibilidade.** Prompts antigos continuam funcionando. O motor segue entendendo `@Agente X`, `@ZapSign`,
`@Buscar CEP` e "acionar tool `x`" (`ferramentas_do_prompt` em `catalogo.py`), e `{{NOME ESCRITORIO}}`. Ao abrir um
prompt antigo, o editor oferece "converter referências", que troca o texto solto pelo token com id. Nada é
convertido sem alguém salvar.

### 1.3 O que cada tipo vira (resumo)

| Classe | Tipos | Quando é resolvido | Pode falhar? |
|---|---|---|---|
| **Variável** | `var:escritorio.*`, `var:lead.*`, `ferramenta:data_hora` | Antes de mandar ao modelo, vira o valor | Não (vazio é barrado antes, na publicação) |
| **Condição** | `origem:*` | Antes de mandar ao modelo: vira o nome, e o motor informa a origem do lead | Não |
| **Capacidade** | `ferramenta:base_conhecimento`, `ferramenta:calculadora`, `ferramenta:salvar_nome` | Liga um recurso do motor naquele agente | Não |
| **Ação** | status, departamento, responsável, etiqueta, tirar_etiqueta, notificar, mensagem, zapsign, agenda, advbox, ativar/desativar áudio, desativar IA, gerar resumo | Depois da resposta do modelo, se ele pedir | Sim, sem derrubar a resposta (seção 2.5) |
| **Troca de agente** | `agente:*` | Depois da resposta, pelo `transferir_para` que já existe | Não (é no nosso banco) |

---

## 2. Como roda no motor

### 2.1 Antes de chamar o modelo: montar o prompt

1. **Ler os tokens** do prompt do agente atual (parser novo, função pura).
2. **Variáveis viram texto.** `@[var:escritorio.cnpj|CNPJ]` vira "12.345.678/0001-90". `@[var:lead.primeiro_nome|nome]`
   vira o primeiro nome gravado; se ainda não houver nome, vira "você" e o FORMATO já manda não inventar nome.
   `ferramenta:data_hora` vira a data de hoje (que já vai em todo turno, `linha_de_hoje`).
   Isso substitui as cópias de CNPJ, OAB, endereço e redes que hoje estão escritas à mão nos 6 prompts da Sousa e Costa.
3. **Condição de origem.** O token vira o nome ("ad09-PAIS") e o conteúdo do turno ganha uma linha do sistema:
   `ORIGEM DESTE LEAD (sistema): campanha ad09-PAIS, anúncio "…", rede facebook`. Quem compara é o modelo, como em
   qualquer regra do prompt. A origem vem de `lead.origem` e do classificador (`app/origem.py`). Se o lead não tem origem:
   `ORIGEM DESTE LEAD (sistema): não informada`.
4. **Ações e agentes viram "@Rótulo atual"** no texto, e o sistema ganha um bloco no fim:

```
AÇÕES QUE VOCÊ PODE PEDIR NESTE AGENTE (use o campo "acoes"; só estas):
- {"tipo":"status","id":"analise"}            -> mudar o status para "Análise"
- {"tipo":"etiqueta","id":"falta_laudo"}      -> marcar a etiqueta "Falta Laudo"
- {"tipo":"desativar_ia","id":"desativar_ia"} -> tirar a IA desta conversa (depois da sua última mensagem)
- {"tipo":"ativar_audio","id":"ativar_audio"} -> suas mensagens deste turno em diante saem em voz
Peça a ação no MESMO turno em que o prompt manda fazê-la. Não diga ao lead que está mudando status ou etiqueta.
```

5. **Capacidades** ligam recursos que o motor já tem:
   - *Base de conhecimento*: os trechos já entram em todo turno (`app/conhecimento.py`). O token acrescenta a regra
     comum: "se não estiver na base nem no roteiro, diga que essa informação não foi repassada, registre para a equipe
     e volte à pergunta pendente". O "registre" já existe: `agentesia_conhecimento_lacunas` (migração 003).
   - *Calculadora*: liga a flag `calculadora` do papel. **O modelo não faz conta.** O código calcula e entrega como
     fatos do sistema (hoje: período de graça). Ampliar com contas de datas (meses desde a cessação, dias com o pedido
     parado no INSS). Conta de honorários **não** entra (seção 5.4).
   - *Salvar nome*: o extrator já grava `nome`. O token só garante que o agente tem o extrator ligado.

### 2.2 O que o modelo devolve

O esquema de saída do catálogo (`esquema()` em `catalogo.py`) ganha **um campo**, montado a partir das ações citadas
no prompt do agente atual:

```json
{
  "mensagens": [{"texto": "..."}],
  "transferir_para": "",
  "ferramenta": "",
  "notificacao": "",
  "acoes": [
    {"tipo": "status",   "id": "analise",     "opcao": ""},
    {"tipo": "etiqueta", "id": "falta_laudo", "opcao": ""}
  ]
}
```

- `tipo` é um enum com **só os tipos citados** no prompt daquele agente. `id` é um enum com **só os ids citados**.
- O `id` que o modelo vê **não é o id da Helena** (um UUID). É uma chave curta e legível gerada a partir do rótulo
  (`analise`, `falta_laudo`), única dentro do agente. O motor traduz para o id real. Motivos: o modelo erra ao copiar
  UUID, e uma chave legível deixa o raio-x do Laboratório fácil de ler.
- `opcao` só é usado pelo Google Calendar (escolher um dos horários oferecidos, seção 2.6). Nos outros tipos vem "".
  O enum de `opcao` é montado a cada turno com os horários que o código ofereceu.
- Agente **sem nenhuma ação citada** não ganha o campo `acoes`: o esquema fica igual ao de hoje e nada muda para
  os escritórios atuais.
- O campo `ferramenta` (zapsign, buscar_cep) e o `notificacao` (analise_humana) continuam. Com o tempo, `zapsign` vira
  `{"tipo":"zapsign","id":"<modelo>"}` e `analise_humana` vira um `notificar` + `desativar_ia`. Os dois caminhos
  convivem enquanto houver prompt antigo.

### 2.3 Conferência no motor (lista fechada)

Uma função pura, ao lado de `_guardas_do_catalogo` em `turno.py`, confere cada ação pedida:

| Regra | Se falhar |
|---|---|
| O par `tipo`/`id` está nas referências **do prompt do agente atual** | Recusa a ação (o enum já impede, mas o motor confere de novo) |
| A referência existe e está ativa (não foi apagada na Helena) | Recusa e gera aviso para a equipe |
| No máximo 1 ação por tipo e 5 por turno (etiquetas: até 3) | Fica com as primeiras, recusa o resto |
| Status não anda **para trás** no funil | Ignora, a mesma regra de `_mover_card` hoje |
| `desativar_ia` não vem junto de `transferir_para` | Fica com `desativar_ia` e descarta a troca |
| `zapsign` só com os dados obrigatórios confirmados | Recusa (passa por `validar_dados`, como hoje) |
| `agenda` com `opcao` dentro dos horários oferecidos neste turno | Recusa e oferece horários de novo |
| `advbox` só depois de `contrato_assinado` (padrão; o escritório pode mudar) | Recusa |
| `ativar_audio` só com voz configurada | Recusa e a mensagem sai em texto |
| Ações vêm só da **tentativa escolhida** (o turno pode ter 2) | As da tentativa reprovada são descartadas |

Uma ação recusada **nunca** reprova a resposta inteira: a mensagem ao lead sai normalmente, e a recusa fica no
registro.

### 2.4 Execução, em ordem

Quem executa é o pipeline, **depois** da segunda conferência que já existe (se chegou mensagem nova no meio do turno,
o turno inteiro é descartado e nenhuma ação acontece). Ordem fixa:

1. `ativar_audio` / `desativar_audio`: muda o modo **antes** de enviar, para valer já nas mensagens deste turno
   (é o uso da referência: "ative o áudio e diga…").
2. Envio das mensagens do modelo (texto ou voz).
3. `mensagem` (mensagem rápida), logo depois do texto.
4. `etiqueta` / `tirar_etiqueta`.
5. `status` (mover card).
6. `notificar` e `gerar_resumo` (nota na Helena).
7. Integrações: `zapsign`, `agenda`, `advbox`.
8. `departamento` / `responsavel`.
9. `transferir_para` (troca de agente) **ou** `desativar_ia`, por último.

Os passos 1, 9 e a gravação do registro são **no nosso banco** e acontecem na hora. Os que chamam Helena, ZapSign,
Google ou AdvBox vão para a fila `agentesia_acoes`, que já tem novas tentativas (1, 5, 30 e 120 min) e reserva com
`for update skip locked`.

**Idempotência:**
- `chave_unica = {lead}:{turno}:acao:{tipo}:{id_real}`. Repetir o turno, um webhook duplicado ou uma nova tentativa da
  fila não fazem a ação duas vezes.
- Antes de enfileirar, o motor compara com o estado conhecido (coluna do card em `agentesia_crm_cards`, etiquetas já
  postas, estado do lead). Se já está assim, registra `ja_estava` e não chama a Helena.
- Operações que podem repetir sem efeito novo: etiqueta com `InsertIfNotExists`/`DeleteIfExists` **por id** (hoje é
  por nome), mover card para uma coluna, transferir para uma equipe.
- AdvBox: procura o cliente pelo CPF antes de criar. Calendar: um evento por lead e tipo de reunião (se já existe,
  remarca em vez de criar outro). ZapSign: a chave com o hash dos dados que já existe.

### 2.5 Registro e falhas

- Cada ação pedida gera um evento em `agentesia_eventos` ligado ao turno: `acao_pedida` (informação),
  `acao_recusada` (aviso, com o motivo) e, pelo executor que já existe, `acao_falhou_<tipo>` (falha definitiva).
- `turnos.contexto["acoes"]` guarda o pedido bruto do modelo, o resultado da conferência e as chaves enfileiradas. O
  raio-x do Laboratório mostra isso.
- **Falha não derruba a resposta.** A mensagem ao lead já foi enviada no passo 2. Se a Helena recusar a etiqueta,
  o lead não percebe; a fila tenta de novo, e na falha definitiva a equipe recebe um aviso (Central de Avisos).
- Ações sensíveis (desativar IA, trocar responsável, departamento) deixam também uma **nota** na conversa da Helena,
  no mesmo padrão de `app/ia_controle.py`: "IA desativada pelo agente Closer: lead já tem advogado".

### 2.6 Casos especiais

**Trocar de agente.** É o `transferir_para` que já existe, com enum por agente e as travas de hoje
(`frase_de_outro_destino`, `perguntar_antes_de_transferir`, `mensagem_troca`). O que muda: a lista de destinos deixa de
vir de `DESTINOS` fixo em `app/gestao/produtos.py` e passa a vir dos **`@[agente:…]` citados no prompt**. A frase de
troca continua valendo como gatilho alternativo. Para o lead, a troca é invisível (mesmo nome de atendente).

**Modo áudio.** `ativar_audio` liga uma marca por conversa (fato de controle `_modo_audio`, no padrão dos `MARCA_*` do
turno). Enquanto ligada, as mensagens da IA saem em **voz sintetizada** (TTS) com a voz do agente. Desliga com
`desativar_audio`, quando o lead pede texto, ou quando a equipe assume. Sempre saem em **texto**, mesmo com áudio
ligado: links, CPF, a lista de confirmação dos dados, o link do contrato e valores. O sinal `nao_sabe_ler` do extrator
pode ligar o modo sozinho, se o escritório quiser (interruptor no agente). Detalhes técnicos na seção 4.3.

**Desativar IA.** `desativar_ia` faz o mesmo que a etiqueta "IA Desativada" faz hoje em `ia_controle.py`: lead
`pausado`, `motivo_estado = desativada_pelo_agente:<agente>:<motivo>`, follow-up cancelado, nota na Helena e
registro. O **motivo** vem da regra do prompt (o motor guarda o trecho do prompt mais próximo do token e o rótulo do
status pedido junto, por exemplo "Desqualificado"). Quem religa é a equipe, pelo caminho de hoje, ou o tempo de
reativação (seção 4.2). Isso corrige uma falha atual: o papel Desqualificado continua respondendo depois do fecho.

**Google Calendar (agendar).** Duas fases, para o modelo nunca inventar horário:
1. O prompt diz "ofereça @Reunião online 30 min". Quando o agente pede `{"tipo":"agenda","id":"reuniao_online_30"}`
   sem `opcao`, o código consulta a agenda (horários livres) e, **no turno seguinte**, entrega:
   `HORÁRIOS LIVRES (sistema): ter 26/11 10:00 | ter 26/11 15:30 | qua 27/11 09:00`. O enum de `opcao` passa a ter
   esses 3 valores.
2. Quando o lead escolhe, o agente devolve `{"tipo":"agenda","id":"reuniao_online_30","opcao":"ter 26/11 15:30"}`.
   O código marca o evento (com link do Meet, se for online), manda a confirmação em texto e põe nota na Helena.
Integração por escritório com login do Google (OAuth), escolhendo a agenda e o horário de atendimento (o
`app/horario.py` já tem horário e dias do escritório).

**ZapSign.** O menu lista os modelos da conta (a função `modelos()` de `app/canal/zapsign.py` já busca
`api/v1/templates/`). A ação gera o contrato **daquele** modelo, com o fluxo de hoje (validação, hash, limite de
versões, lembretes, verificação da assinatura). Isso resolve escritórios com mais de um contrato (um por benefício).

**AdvBox.** Ações fechadas, sem parâmetro livre: `criar_cliente` (nome, CPF, telefone, endereço, a partir dos fatos
confirmados) e `criar_processo` (cliente + tipo de ação/benefício + responsável padrão). Por padrão só depois do
contrato assinado. Conexão por token do escritório. **A API do AdvBox ainda não foi estudada**: confirmar os campos
obrigatórios e se existe busca por CPF antes de prometer a funcionalidade.

**Mensagens rápidas.** Duas fontes no mesmo menu:
- **do LawChat** (recomendado): nome + texto e/ou mídia da Biblioteca (`/midia`). Funciona em qualquer canal e
  envia a mídia com segurança, só da nossa biblioteca;
- **da Helena** (respostas rápidas, `Type=QUICKREPLY`): por enquanto **só o texto**, porque não está documentado se
  dá para enviar pelo id nem como pegar o arquivo (pendente de teste real, `HELENA_API.md`).

**Responsável.** Não existe hoje no código. A Helena tem `PUT chat/v1/session/{id}/assignee`. Falta testar se o id
certo é `agent.userId` ou `agent.id`. Responsável aqui é **sempre uma pessoa**; trocar para outro agente de IA é a
categoria Agentes (na referência, as duas coisas se misturam em "Responsáveis").

---

## 3. Aba Referências (por agente e por grupo)

Uma aba nova na tela do agente (e uma no grupo, somando todos os membros). Inspirada na tela de referências da
concorrente, com o nosso jeito:

```
ETIQUETAS (4)
  ✓ Acidente          Referenciado por 2 agentes        [🏷 Acidente]
  ✓ Falta Laudo       Referenciado por 1 agente         [🏷 Falta Laudo]
STATUS (3)
  ✓ Análise           Referenciado por 4 agentes        [〰 Análise]
  ⚠ Análise Humana    Referenciado por 3 agentes        [ Apagada na Helena — escolher outra ▾ ]
DADOS GERAIS (2)
  ✓ CNPJ              12.345.678/0001-90
  ⚠ OAB               vazio — Preencha em Configurações
```

Para cada item:
- **rótulo** que o prompt usa e a **entidade real** ligada (com o nome atual dela);
- **"Referenciado por N agentes"**, que abre a lista de agentes e o trecho de cada prompt;
- **situação**:
  - ✓ verde: existe e está ativa;
  - ⚠ amarelo: renomeada (o nome atual é diferente do rótulo salvo), só informativo;
  - ✕ vermelho: **apagada** na Helena/ZapSign/Google/AdvBox, **integração desconectada**, ou **variável vazia**.
- botão **"Trocar"**: escolhe outra entidade e atualiza o token em **todos** os prompts que o usam, de uma vez.

**Bloqueio ao salvar.**
- Salvar um **rascunho** com referência quebrada: permitido, com aviso.
- **Publicar** (ativar ou mandar para produção) com referência vermelha: **bloqueado**, com a lista do que corrigir.
  É o mesmo padrão que a ativação já usa hoje (`app/gestao/ativacao.py`: "o painel não existe mais", "colunas que não
  existem mais", "a equipe escolhida não existe mais").
- Se algo é apagado na Helena **depois** de publicado: o motor recusa só aquela ação (seção 2.3), a conversa segue, e
  a equipe recebe um aviso "o agente X cita a etiqueta *Falta Laudo*, que foi apagada".

**De onde vêm as listas.** A Helena **não avisa** por webhook quando etiqueta, equipe, usuário ou painel é criado ou
apagado (só modelos têm `TEMPLATE_NEW/UPDATE`). Por isso a sincronização é por consulta:
- ao abrir o editor ou a aba Referências (com botão "Atualizar");
- a cada 15 minutos para escritórios ativos (5 a 7 chamadas por escritório, longe do limite da Helena);
- pelos webhooks de modelo, quando chegarem.
O que não voltou na listagem fica marcado como apagado ("marca e varre", o mesmo esquema de
`repositorio.sincronizar_canais`).

**Um aviso sobre as automações.** Hoje card, etiqueta e departamento também são movidos pelas **automações por
evento** (`app/automacoes.py`). Se o prompt e uma automação mandam o card para colunas diferentes no mesmo momento, a
aba Referências mostra "conflito com a automação *etapa:closer*". A regra de não andar para trás evita estrago, mas o
escritório precisa saber.

---

## 4. Grupo de agentes, ativação, voz, modelo e sandbox

### 4.1 Grupo de agentes

Na referência: um **grupo** tem um **agente inicial** e **membros**; dá para criar um agente novo no grupo ou
vincular um existente.

**No nosso sistema isso já existe com outro nome:**

| Referência | Nosso |
|---|---|
| Grupo | `agentesia_agentes` (o "agente" ligado a um número, ou o produto ativado) |
| Agente (membro) | `agentesia_agente_etapas` (cada papel: SDR, Período de Graça, Closer...) |
| Agente inicial | A etapa `principal` |
| "@Selecione #03" | `transferir_para` |

Então **não precisamos de tabela nova para o grupo**. Precisamos **soltar** o que hoje está fixo:
- aceitar membros fora dos 6 papéis (hoje `produtos.py` recusa qualquer papel fora de `PAPEIS`);
- escolher o agente inicial (hoje é sempre o primeiro da ordem);
- tirar os destinos do `DESTINOS` fixo e derivar dos `@[agente:…]` citados nos prompts;
- telas: "Adicionar agente: criar novo neste grupo" e "Duplicar a partir de outro".

Vários grupos no **mesmo número** (por exemplo auxílio-acidente e BPC) é o desenho da recepção
([AGENTE_TRIAGEM.md](AGENTE_TRIAGEM.md), seção 9): `id_canal` deixa de ser único e o canal ganha
`id_agente_entrada`. O grupo de entrada pode ser a própria triagem.

### 4.2 Ativação

| Campo | O que faz | Onde |
|---|---|---|
| **Agente primário no número** | Recebe todo lead novo daquele número | `agentesia_canais.id_agente_entrada` (desenho da triagem) |
| **Palavra-chave de ativação** | Se a 1ª mensagem do lead tem a palavra (ex.: "BPC", "#acidente"), vai direto para este grupo, sem triagem | Lista no `config` do grupo. Vira uma **camada antes da origem** na triagem: sem IA, custo zero |
| **Tempo de reativação** | Depois de a IA ser desativada (pelo agente ou pela equipe), quanto tempo **sem mensagem humana** até a IA poder voltar se o lead escrever de novo | `config.reativar_apos_min`. **Padrão: nunca** (só a equipe religa). O print da concorrente mostra um relógio com "15", mas não deixa claro se é isso ou tempo de agrupar mensagens; o nosso tempo de agrupar já existe (tempo de resposta na aba Ativação) |

Cuidado com a reativação automática: se a equipe desativou porque o lead tem advogado, a IA voltar sozinha é ruim.
Por isso: só vale para desativações com motivo marcado como "reativável" e nunca para Desqualificado, pedido de
parar ou engano.

### 4.3 Voz do agente

- Campo **Voz** no agente (ou no grupo, herdado pelos membros): provedor + voz + velocidade, com botão "Ouvir
  exemplo".
- Provedor sugerido para começar: o TTS da **OpenAI** (já temos a conta e a chave; vozes em português razoáveis).
  Alternativa de qualidade maior: ElevenLabs (outra conta e outro custo).
- Caminho do áudio: texto → TTS → **OGG/Opus mono** (o formato que o WhatsApp mostra como mensagem de voz) →
  upload (`core/v2/file` da Helena ou a nossa `/midia`) → envio por `POST chat/v1/send/audio`.
- **Pendente de teste real**: se chega como mensagem de voz (com a bolinha azul) no canal oficial e no não oficial.
  A documentação da Helena não tem flag de voz.
- Custo: TTS cobra por caractere ou minuto. É bem mais caro que o texto do turno, mas só nas conversas com áudio
  ligado. Mostrar no consumo como linha separada ("voz").

### 4.4 Modelo por agente

Já existe: modelo por etapa (`Etapa.modelo`) e por papel (`config.modelos`). A tela de Ativação mostra o modelo do
agente; falta mostrar **por membro** no grupo, com o custo estimado por conversa ao lado (o cálculo está em
`app/avaliacao/custo.py`).

### 4.5 Sandbox de teste (o nosso Laboratório)

**"Sem consumir créditos" não quer dizer "de graça".** Cada mensagem no teste chama o modelo de verdade. O que a
concorrente faz é **não descontar dos créditos do cliente**: o custo fica com a plataforma. O nosso Laboratório
(`app/gestao/laboratorio.py`) também chama o modelo de verdade: cerca de **US$ 0,003 a 0,01 por mensagem** com
`gpt-4.1-mini` (agente + extrator + auditor), e umas 5 vezes isso com `gpt-4.1` (tabela em `app/modelo.py`).

Proposta:
- **Motor de verdade, Helena falsa.** O Laboratório já roda o `Atendimento` real em memória com `helena=None`. Passa a
  usar uma Helena falsa (como a `HelenaFalsa` de `app/avaliacao/efeitos.py`) que **registra** cada ação sem executar.
  O raio-x do turno mostra: "teria movido o card para *Análise*", "teria posto a etiqueta *Acidente*", "teria
  desativado a IA (motivo: …)", "teria gerado o contrato do modelo X". ZapSign, Calendar e AdvBox também ficam falsos.
- **Mostrar o custo** de cada mensagem e o total da conversa (já mostra em US$; mostrar também em R$).
- **Não descontar do escritório**: o custo do Laboratório vai para um balde separado ("laboratório") em
  `agentesia_chamadas_ia`, com **teto diário por escritório** (sugestão: US$ 1/dia; ao passar, o teste pede para
  esperar o dia seguinte ou para o admin liberar). Assim a promessa "testar sem gastar créditos" é verdadeira e o
  risco é limitado.
- **Botão Resetar**: hoje existe "Nova conversa". Passa a se chamar **Resetar** e limpa conversa, fatos, modo áudio e
  marcas. Deixa a opção "Resetar mantendo os dados do lead", para testar só o fim do funil.
- **Voz no teste**: desligada por padrão (mostra "[áudio: texto]"); um interruptor liga para ouvir de verdade (custa).
- Depois: anexar imagem/PDF e gravar áudio no teste (hoje é só texto), como a concorrente faz. E apagar ou religar o
  `TestePrompt.tsx` do assistente, que chama uma rota que não existe (`/api/teste-prompt`).

---

## 5. Estrutura multiagente: a referência e a nossa

### 5.1 Comparação

| | Referência (auxílio-acidente) | Nosso (catálogo, Sousa e Costa) |
|---|---|---|
| Agentes | 7 curtos: Triagem, Segurado, Sequelas, Nexo doença/trabalho, Proposta e Objeções, Dados e Contrato, Assinatura e Documentos | 6 papéis: SDR, Período de Graça, Closer, Contratos, Assinatura, Desqualificado |
| Quem decide ações | O prompt (status, etiqueta, responsável a cada passo) | O código (automações por evento) + o modelo só escolhe destino e ferramenta |
| Contas | "@Calculadora" (o modelo usa) | O código calcula e entrega como fato |
| Regras gerais | Copiadas em todos os 7 | Copiadas em vários prompts (e dados do escritório em 6) |
| Desqualificação | Marca status e desliga a IA | Papel próprio, com fecho cuidadoso (mas não desliga a IA) |
| Doença ocupacional | Ramo próprio (Nexo) | Não existe; doença é desqualificada |

### 5.2 Quando vale dividir em mais agentes

Vale dividir quando:
- o trecho tem **um objetivo só** e um **fim claro** (ex.: "descobrir se é segurado");
- o trecho precisa de **regras ou ferramentas diferentes** (o de contrato precisa de ZapSign; os outros não devem ter);
- o prompt passou de ~6 a 8 mil caracteres e o modelo começa a **pular etapas** ou misturar regras;
- existe um **ramo** que só parte dos leads percorre (doença ocupacional).

Não vale dividir quando:
- os pedaços precisam do mesmo contexto o tempo todo (vai e volta entre agentes);
- a divisão só serve para "marcar status ao entrar": isso o código faz pela automação `etapa:X`;
- cada troca é um ponto a mais de erro (frase de troca, destino errado). Na referência, o próprio template chama o
  agente #07 pelo nome errado ("#06 - Assinatura e Reunião").

**Recomendação:** manter os nossos 6 papéis como base e **acrescentar dois**, que são os ramos que a referência tem e
nós não: **Nexo (doença ocupacional)** e **Documentos (pós-assinatura)**. Não quebrar o SDR em Triagem + Segurado +
Sequelas: o nosso SDR já faz isso com a calculadora do código, que é mais confiável.

### 5.3 O que trazer da referência para os nossos prompts

1. **Ramo de doença ocupacional (Nexo).** Hoje o SDR desqualifica doença e, ao mesmo tempo, conta hérnia por esforço
   repetitivo como acidente. O agente Nexo coleta profissão, doença, se recebeu auxílio-doença e se tem laudo, e
   marca `@Doença` e `@Falta Laudo`. **A IA não decide se há nexo**: quando a ligação for possível, vai para análise
   humana. A base de conhecimento serve para fazer as perguntas certas, não para julgar.
2. **Checagem de pedido anterior no INSS.** Corrige uma contradição nossa: o SDR desqualifica quem teve pedido
   negado, mas a objeção 9 do mesmo prompt manda seguir. Caminhos: nunca pediu → segue; pediu sem advogado e foi
   negado → segue; pediu com advogado → regra de advogado que já temos; perícia marcada → segue e `@notificar` a
   equipe (urgente); pedido parado → o **código** calcula os dias, e o prazo vem da configuração confirmada pelo
   advogado, não fixo no prompt.
3. **Documentos e contato de recado depois da assinatura** (agente Documentos): contato de recado (nome, parentesco,
   telefone, dizendo para que serve, porque é dado de outra pessoa); checklist de documentos com marcação de cada um
   recebido (a visão em `app/midia/openai_visao.py` ajuda a reconhecer); no fim `@Jurídico` e resumo na nota.
   **Nunca pedir a senha do gov.br/INSS pelo chat**: credencial e LGPD. Isso fica com uma pessoa, por canal seguro.
4. **Modo áudio** controlado pelo código (seção 2.6), em vez do áudio fixo de hoje.
5. **"Essa informação não me foi repassada"** quando o assunto não está na base, sem inventar.
6. **Dados do escritório por variável** (`@CNPJ`, `@OAB`...), em vez de copiados em 6 prompts.
7. **Análise humana para aposentado** que pode ter parcelas atrasadas de auxílio-acidente, em vez de desqualificar
   direto.
8. **Desqualificado desliga a IA** depois do fecho (`@Desativar IA`), com o nosso fecho cuidadoso mantido.

### 5.4 O que **não** trazer (ética e OAB)

O Código de Ética da OAB e o Provimento 205/2021 proíbem captação com promessa, mercantilização e depreciar colegas.
Não trazer:
- o discurso de **"prioridade na fila"** para apressar a assinatura;
- frases que **falam mal de outros advogados** ("advogado barato costuma errar") ou afirmações genéricas sobre o
  INSS ("o INSS está negando pedidos sem advogado");
- a **conta de honorários feita pelo bot** (a fórmula com o valor do benefício): honorário é combinado pelo
  escritório, e o bot só repete o texto aprovado;
- o **e-mail falso** no contrato (`sem@email.com`): se não tem e-mail, o campo fica vazio ou o contrato sai por
  WhatsApp;
- a **"indignação"** como tom e a **sequela julgada pela IA** ("é irreversível, então tem direito");
- pedir a senha do gov.br pelo chat.

Revisar também os **nossos** textos de objeção 1, 3, 4, 6 e 7, que têm o mesmo tipo de pressão. E três problemas que
apareceram nos nossos arquivos: `closer.md` está duplicado, os dados do escritório estão copiados em 6 prompts, e o
Desqualificado só manda o link de avaliação do Google para quem deu nota 5 (isso fere a política do Google de não
filtrar avaliações).

### 5.5 Onde a triagem entra

A recepção ([AGENTE_TRIAGEM.md](AGENTE_TRIAGEM.md)) é o **agente de entrada do número**, antes dos grupos de produto.
Na linguagem desta proposta:
- ela é um **grupo de um agente só**, primário no número, cujo prompt cita os grupos de produto como `@[agente:…]`
  (os destinos). A passagem é a troca de agente com o pacote de passagem da seção 6 daquele documento;
- a **palavra-chave de ativação** (seção 4.2) e a **origem** (camada 1 da triagem) decidem antes da conversa, sem IA;
- a triagem **não** deve ter ações de status, etiqueta ou desativar IA no prompt: o que ela faz na Helena é pelas
  automações `triagem:*` daquele documento. Isso mantém a recepção simples e barata;
- o `@Origem` desta proposta usa a mesma origem classificada que a triagem usa.

---

## 6. Plano de implementação (etapas pequenas)

Cada etapa é um PR que pode ir para produção sozinho e não muda nada para quem não usa o recurso novo. Entre
parênteses: arquivos principais, migração e testes.

**Atenção às dependências.** Outros trabalhos estão mexendo agora em `app/pipeline.py`, `app/canal/*` e
`app/cerebro/*`. As etapas marcadas com **[espera]** só começam depois que esse trabalho de produção for integrado,
para não haver conflito. Os arquivos **novos** dessas pastas podem ser escritos antes, sem ligar no fluxo.
Numeração de migração: a 003 já é `003_agentesia_conhecimento.sql`; o `AGENTE_TRIAGEM.md` cita uma "003 da triagem",
que vai virar **004**. Esta proposta usa a **005** (ou a próxima livre).

### Fase A: base, sem mudar o comportamento

| # | O quê | Arquivos | Testes |
|---|---|---|---|
| A1 | **Parser de tokens** (função pura): ler `@[tipo:id\|Rótulo]`, listar referências, trocar variáveis, montar o bloco "AÇÕES QUE VOCÊ PODE PEDIR", converter o formato antigo (`@Agente X`, `{{NOME ESCRITORIO}}`) | `app/cerebro/referencias.py` (novo) | `tests/test_referencias.py`: formato, rótulo com `\|` ou `]`, token malformado vira texto, compatibilidade |
| A2 | **Informações gerais do escritório** (nome, CNPJ, OAB, endereço, Instagram, Facebook, site, responsável legal, telefone) | `agentesia_escritorios.config.informacoes` (jsonb, **sem migração**); `app/gestao/rotas.py` (GET/PUT); `painel/src/telas/Configuracoes.tsx` | `tests/test_gestao.py`: validação de CNPJ e OAB, limite de tamanho |
| A3 | **Tabelas de entidades e referências** | `db/migracoes/005_agentesia_referencias.sql` + `desfazer_005.sql`: `agentesia_entidades` (id, id_escritorio, origem `helena/zapsign/google/advbox/lawchat`, tipo `etapa/etiqueta/departamento/atendente/resposta_rapida/modelo_zapsign/agenda/origem/aviso/mensagem`, id_externo, nome, extra jsonb, ativo, visto_em, apagado_em; único por escritório+origem+tipo+id_externo) e `agentesia_referencias` (id_escritorio, id_agente, id_etapa, tipo, chave, rotulo_salvo, id_entidade, situacao `ok/renomeada/apagada/vazia/desconectada`; refeita a cada salvamento do prompt) | `tests/test_postgres.py` e repositório em memória |
| A4 | **Sincronização com a Helena** (etiquetas por id, equipes, atendentes `core/v1/agent`, painéis com paginação e etapas, respostas rápidas `Type=QUICKREPLY`), marca e varre | `app/gestao/entidades.py` (novo, usa `HelenaConta`); métodos novos `atendentes()` e `respostas_rapidas()` em `helena_conta.py` **[espera: app/canal]** | `tests/test_entidades.py` com Helena falsa: item que some vira apagado, renomeado atualiza nome |
| A5 | **API do menu e das referências** | `app/gestao/rotas.py`: `GET /referencias/catalogo` (categorias com contagem, para o "@"), `GET /agentes/{id}/referencias`, `GET /grupos/{id}/referencias`, `POST /referencias/trocar` (troca em todos os prompts), `POST /entidades/sincronizar` | `tests/test_gestao.py` |

### Fase B: editor e aba Referências (painel)

| # | O quê | Arquivos |
|---|---|---|
| B1 | **Editor com o menu completo**: categorias da seção 0 com contagem; chip com nome atual; chip vermelho quando quebrado; aviso ⚠ em dado geral vazio; renomear a categoria "Departamento" para "Agentes" | `painel/src/components/agent/RichPromptEditor.tsx`, `painel/src/data/handoffTargets.ts`, novo `painel/src/data/referencias.ts` |
| B2 | **Usar o mesmo editor na tela do agente** (hoje é um textarea em `Agente.tsx`, aba Instruções) | `painel/src/telas/Agente.tsx` |
| B3 | **Aba Referências** por agente e por grupo, com "Trocar" e "Atualizar" | `painel/src/telas/agenteSecoes.tsx`, novo `painel/src/telas/Referencias.tsx` |
| B4 | **Bloqueio ao publicar** com referência vermelha ou variável vazia | `app/gestao/ativacao.py` (novos passos, no padrão dos passos 7 e 8) |

Até aqui o motor **só troca variáveis** (etapa C1). Nenhuma ação é executada ainda.

### Fase C: o motor executa as ações **[espera: app/cerebro e app/pipeline]**

| # | O quê | Arquivos | Testes |
|---|---|---|---|
| C1 | **Variáveis e origem no prompt** (troca antes do modelo; linha `ORIGEM DESTE LEAD`) | `catalogo.montar_sistema`, `pipeline` (passar `informacoes` e `lead.origem`) | `tests/test_catalogo.py` |
| C2 | **Campo `acoes` no esquema** (enum por agente, só quando há ação citada) e **conferência** (seção 2.3), com `acoes_pedidas` e `acoes_recusadas` na `Saida` | `catalogo.esquema`, `turno._turno_catalogo`, nova função ao lado de `_guardas_do_catalogo` | `tests/test_turno.py`: fora da lista, repetida, para trás, desativar + transferir, tentativa reprovada |
| C3 | **Execução em ordem com idempotência** (seção 2.4): etiqueta por id, status, notificar, mensagem rápida do LawChat, departamento | `pipeline` (ao lado de `_automacoes`), `app/acoes.py` (tipos novos), `helena_conta.etiquetar` por id **[espera: app/canal]** | `tests/test_pipeline.py`, `tests/test_automacoes.py`: chave única, `ja_estava`, falha não derruba a resposta, turno descartado não deixa efeito |
| C4 | **Desativar IA pelo agente** | `pipeline`, `app/ia_controle.py` (função comum) | `tests/test_ia_controle.py` |
| C5 | **Destinos pelos `@[agente:…]`** em vez de `DESTINOS` fixo | `catalogo.ferramentas_do_prompt`, `app/gestao/produtos.py` | `tests/test_catalogo.py`, cenários da avaliação |
| C6 | **Registro**: eventos `acao_pedida`/`acao_recusada`, `turnos.contexto["acoes"]`, raio-x do Laboratório | `turno`, `painel/src/telas/Agente.tsx` (raio-x) | |
| C7 | **Laboratório com Helena falsa, custo em R$, balde separado com teto diário, botão Resetar** | `app/gestao/laboratorio.py`, `app/consumo.py`, `Agente.tsx` | `tests/test_gestao.py` |

### Fase D: responsável, grupo e ativação

| # | O quê | Depende de |
|---|---|---|
| D1 | **Responsável** (`assignee`) | Teste real: `userId` ou `agent.id` (HELENA_API.md) **[espera: app/canal]** |
| D2 | **Grupo livre**: membros fora dos 6 papéis, escolher o inicial, criar/duplicar membro | `app/gestao/produtos.py`, `ProdutoEditor.tsx`, `EditorDefinicao.tsx` |
| D3 | **Agente primário por número e palavra-chave** | Migração 004 da triagem (`id_agente_entrada`, `id_canal` não único) |
| D4 | **Tempo de reativação** (padrão desligado) | C4 |

### Fase E: voz e integrações novas

| # | O quê | Depende de |
|---|---|---|
| E1 | **Voz do agente + modo áudio** (TTS, OGG/Opus, envio, marca `_modo_audio`, sempre texto para link/CPF/lista) | Teste real de mensagem de voz nos dois tipos de canal; `app/canal` **[espera]** |
| E2 | **ZapSign por modelo** no "@" | C3 (já temos `modelos()` em `zapsign.py`) |
| E3 | **Google Calendar** (OAuth por escritório, agenda, horários livres, marcar, remarcar) | C3; módulo novo `app/integracoes/google_agenda.py`; tela em Integrações |
| E4 | **AdvBox** (criar cliente, criar processo) | Estudo da API do AdvBox; C3 |
| E5 | **Mensagens rápidas da Helena com mídia** | Teste real de envio de `QUICKREPLY` pelo id |

### Fase F: prompts

| # | O quê |
|---|---|
| F1 | Converter os prompts da Sousa e Costa para tokens (dados do escritório por variável) e tirar as cópias |
| F2 | Agentes novos **Nexo** e **Documentos**, checagem de pedido anterior, regra "informação não repassada", Desqualificado com `@Desativar IA` |
| F3 | Revisão ética das objeções (seção 5.4), corrigir `closer.md` duplicado e o link de avaliação só para nota 5 |
| F4 | Cenários de avaliação para cada ação nova (a Helena falsa da avaliação registra a ação; checagem "pediu a ação X no turno Y") |

**Ordem sugerida para o primeiro valor visível:** A1 → A2 → C1 (dados do escritório por variável já resolvem as
cópias nos 6 prompts) → A3/A4/A5 → B1/B3/B4 → C2/C3/C4 → C7. Voz e integrações novas depois que a base estiver de pé.

### Pendências de teste real (antes de prometer ao cliente)

1. Áudio chega como mensagem de voz no canal oficial e no não oficial?
2. Resposta rápida da Helena pode ser enviada pelo id? Como pegar o arquivo?
3. `assignee` usa `userId` ou `agent.id`?
4. Dá para transferir para equipe **e** pessoa na mesma chamada?
5. Etiqueta por `tagIds` funciona igual ao `tagNames` de hoje?
6. API do AdvBox: campos obrigatórios e busca por CPF.
