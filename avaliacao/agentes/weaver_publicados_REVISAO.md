# Revisão dos 3 produtos publicados vindos do Weaver (26/11/2026)

Arquivo revisado: `avaliacao/agentes/weaver_publicados_revisado.json`. Ele tem o mesmo formato do exportado
(`agentesia-catalogo-v1`), com os mesmos ids, slugs e status, e reimporta com
`python -m app.catalogo_importar avaliacao/agentes/weaver_publicados_revisado.json`. Rode antes com `--simular`.

O que mudou no arquivo:
- o texto dos 16 prompts, em `texto_prompt` e no bloco `freeform` de `blocos_prompt`, que agora são iguais;
- 5 frases de troca reescritas e 3 frases novas para o Desqualificado;
- os 12 follow-ups (o prompt de cada etapa) e a cadência dos 3 produtos.

Nada mais foi tocado. FAQ, objeções, regras gerais, dados do escritório, boas-vindas, conhecimento e config continuam
como vieram do Weaver. Vários desses campos têm problemas: veja a seção 5.

---

## 0. Resumo: dá para pôr no ar?

| Produto | Prompts | No ar? |
|---|---|---|
| **Auxílio Acidente · Mídia** | Prontos, no padrão do `sousa_costa_enxuto` | **Sim, depois dos 4 ajustes de cadastro** da lista abaixo (itens 1 a 4). São campos fora do prompt, e os dois primeiros quebram a conversa se ficarem como estão. |
| **BPC/LOAS Autismo, TDAH e TOD · Mídia** | Prontos | **Não.** O motor ainda trava a passagem (item 5). |
| **BPC/LOAS Geral - Idoso** | Prontos | **Não**, pelo mesmo motivo. Também falta preencher os dados do escritório (item 4). |

**Bloqueios e riscos, do maior para o menor:**

1. **Boas-vindas de modelo nos 6 agentes do Auxílio Acidente** (campo `mensagem_boas_vindas` de cada agente, fora do
   prompt). O painel copia esse texto para a etapa na ativação (`ProductConfigurator.tsx`, linha 658), e o motor manda a
   IA abrir a etapa com ele (`turno.py`, linhas 380 a 388). Alguns exemplos que iriam ao lead:
   - Assinatura: "Te enviei o contrato ... por e-mail/WhatsApp";
   - Desqualificado: "posso te enviar materiais gratuitos sobre Auxílio Acidente. Topa?";
   - Closer: "Posso te explicar como funciona nossa atuação e os honorários?".

   Esses textos atropelam o roteiro e a frase de troca. **O que fazer:** deixar `mensagem_boas_vindas` vazio nos 6
   agentes. Nos dois BPC ele já está vazio.
2. **Regras gerais do produto contrárias ao motor e ao roteiro** (`regras_markdown` do Auxílio Acidente e do Autismo).
   Elas entram em todo prompt como "# REGRAS GERAIS DO ESCRITÓRIO". O texto manda, por exemplo:
   - "Nunca informe quanto cobramos de honorários — só na reunião" (o Closer precisa apresentar os honorários);
   - "Nunca diga que é IA" (o motor manda responder com honestidade);
   - "Nunca cite equipe";
   - "Você ouve áudios e lê fotos";
   - "Nunca use verbos de incerteza".

   **O que fazer:** apagar o campo ou trocar pelo texto curto da seção 5.1.
3. **Mídias que ainda não têm arquivo**: 12 marcadores `[[audio:...]]` e `[[video:...]]` (seção 4). O motor tira o
   marcador sem arquivo e a IA responde por texto. Nada quebra, mas o roteiro perde o vídeo de abertura e os áudios dos
   honorários. Escolha os arquivos na **Edição rápida de mídias** de cada produto. As mídias da assinatura vão no
   **Envio do contrato** do agente.
4. **Dados do escritório**: o BPC Idoso não tem o bloco `dados_escritorio`, e as objeções de confiança ("+ dados do
   escritório") ficam sem resposta. Nos outros dois, o bloco usa variáveis que precisam de valor (seção 3).
5. **BPC: o portão de fatos do motor foi feito para acidente** (`app/cerebro/catalogo.py`, `PORTAO_DE_FATOS`). Os slugs
   `bpc_loas_*` não estão na tabela e caem em `previdenciario`. Isso tem três efeitos:
   - **para ir ao Comercial, o motor exige o fato `sequela`.** Sem ele, segura a passagem e manda a pergunta
     "Depois do acidente, você ficou com alguma sequela ou limitação?" à mãe de uma criança autista. Conferido:
     `faltam_para_entrar(bpc, "closer", {aposentado: nao, advogado: nao})` devolve `['sequela']`;
   - **para desqualificar, falta o motivo.** Renda acima do limite, criança sem condição de saúde e benefício para o
     cuidador não estão em `MOTIVOS_DE_DESQUALIFICAR`. A desqualificação é barrada e, no segundo turno segurado, a
     conversa vai para a equipe (`analise_manual:faltam_fatos`);
   - o fato `aposentado` fala de quem conversa (a mãe), e não da criança.

   **O que fazer (frente do motor):** criar a tabela `bpc` no portão. Como sugestão: Comercial com
   `tem_advogado_no_caso` mais um fato do tipo `ja_recebe_beneficio`, e motivos para renda, sem condição e
   cuidador. **Para não esperar:** o escritório pode gravar
   `config.catalogo.portao_de_fatos = {"closer": ["tem_advogado_no_caso"]}`, o que tira a pergunta da sequela. Com
   isso a desqualificação por renda continua indo para a equipe.
6. **BPC: conta de renda.** O SDR do BPC tem a calculadora ligada (`FERRAMENTAS_DO_PAPEL["sdr"]`), e a regra fixa diz
   "Nunca calcule". A conta da calculadora só cobre o período de graça. Os prompts novos evitam a divisão: usam uma
   tabela de limite por número de pessoas e mandam os casos difíceis (gastos com o tratamento, aposentadoria de outro
   morador acima de 1 salário mínimo, pensão alimentícia) para @Análise da equipe. A soma das rendas ainda fica com a
   IA. **Frente do motor:** pôr a renda por pessoa na calculadora, ou desligar o bloco de datas no SDR do BPC.
7. **Auxílio Acidente: MEI que nunca teve carteira assinada.** O roteiro desqualifica esse caso, como no Sousa e Costa.
   O motivo `ja_foi_clt = nao` não está em `MOTIVOS_DE_DESQUALIFICAR`, então o motor barra a troca e o lead vai para a
   equipe. **Frente do motor:** incluir esse motivo, se o dono confirmar a regra.
8. **Valores fixos que vencem**: salário mínimo de R$ 1.621 e limites de R$ 810,50 e R$ 1.000 por pessoa na tabela do
   BPC. Precisam ser atualizados a cada ano.

**Checagens grátis que rodei** (nenhuma chamou IA):
- **Plano do importador** (`catalogo_importar.ler_arquivos` + `planejar`): 3 produtos, 6 + 5 + 5 agentes, 5, 4 e 4
  frases válidas, 4 follow-ups cada, nenhum aviso novo. O único aviso, "produto-base ... não está no arquivo", já
  vinha do original.
- **Prompts e frases, com as funções do motor**:
  - `ferramentas_do_prompt`: os destinos de cada agente saem certos (tabela da seção 6);
  - `arrobas_sem_destino`: 0 chips soltos. No original havia 1: "@Agente Contrato" no Closer do Idoso;
  - nenhum "acionar tool", "@Transferência", "@ZapSign" ou "@Buscar CEP" sobrou;
  - variáveis: só `NOME AGENTE`, `NOME ESCRITORIO` e `LINK AVALIACAO GOOGLE`;
  - `trecho_de_promessa`, sobre todas as falas entre aspas e as linhas ✅/✔️: 0 achados;
  - nenhum "100%" (havia 2);
  - `_frase_valida` e `catalogo.conferir` nas 13 frases: todas válidas e limpas;
  - nenhum prompt passa de 9.500 caracteres. O limite é 12.000; no original, 3 do Idoso passavam (21.447, 19.229 e
    18.748).
- **Modo falso**: `python -m app.avaliacao rodar --falso --agente <snapshot do Auxílio Acidente revisado>`, com prompts,
  frases e destinos novos, passou **8 de 8 cenários**: viável até a assinatura, desqualificado, os 3 de período de
  graça, objeção, áudio e fora do roteiro. O relatório ficou em `avaliacao/resultados/2026-11-26_0044_agente-referencia/`,
  que o git ignora. Esse modo prova a ligação com o motor (destinos, frases, portão, contrato), não a qualidade do
  texto: as falas da IA são roteirizadas. Os cenários são de acidente, por isso não serviram para os BPC. Para eles,
  conferi o portão chamando a função direto (item 5).

---

## 1. Auxílio Acidente · Mídia (6 agentes)

### SDR
**Fora do padrão:** o prompt tinha:
- "CONDUTA E TOM" inteiro e "uma pergunta por vez";
- "PROIBIDO valores", "nunca inventar link";
- "REGRA DE FORMATAÇÃO \n\n", "Formato final (exemplo literal)" e "Nota interna";
- "Toda desqualificação exige confirmação", "acione @Agente Closer (não aguardar resposta)";
- áudio e pergunta do Closer mandados pelo SDR;
- "@Transferência: Closer/Período de Graça" no texto.

Duas regras se contradiziam: "MEI → Período de Graça" (pergunta 9) e "Atua como MEI → DESQUALIFICADO" (regras). As
perguntas 10 e 10.1 eram confusas ("desempregado? SIM → PG; NÃO → PG"). **Não havia pergunta de aposentadoria**, e a de
advogado só existia no caminho da carteira assinada. Os dois são fatos que o portão exige para o Comercial.

**O que mudou:** o roteiro segue o do `sousa_costa_enxuto`:
- travas e não-travas;
- respostas que já contam;
- perguntas na ordem;
- decisão e dúvidas.

Trechos, antes → depois:
- "Em qual ano aconteceu o acidente?" + "Em qual mês de (ano)…" → "Em que mês e ano aconteceu o acidente? Pode ser
  aproximado."
- "Atua como MEI → DESQUALIFICADO" → "Ser ou ter sido MEI … o que decide é a carteira assinada"; MEI que já teve
  carteira vai para o Período de Graça.
- (não havia) → pergunta 10: "Hoje você recebe alguma aposentadoria do INSS?". A pergunta 11, do advogado, vale para
  todos os caminhos, antes de qualquer passagem.
- "Se o cliente não sabe [do advogado] → fale que é importante…" → pede para verificar; se continuar sem saber →
  @Análise da equipe.
- "@Agente Closer" / "@Agente Desqualificado" / "@Agente Período de Graça" → @Comercial / @Desqualificado /
  @Período de Graça.
- "'[[audio:Video Inicial]]'" (entre aspas, com "Mensagem 1/2") → marcador sozinho na linha, antes da apresentação.
- DECISÃO com condição clara: "só com a data, a sequela, a aposentadoria e o advogado respondidos".

**Decisão do dono:** a fala "Já tentei e negaram" do Sousa ("Normalmente negam porque o pedido foi montado errado")
afirma uma causa sem fonte. Troquei por "Isso acontece bastante. Quem avalia o seu caso agora é o nosso advogado…".

### Período de Graça
**Fora do padrão:**
- tinha 7 mil caracteres de cálculo (ALGORITMO, FÓRMULAS, EXEMPLOS, BLOQUEIO DE INDUÇÃO) que são da calculadora do
  motor;
- usava "Tool `qualificado`", "acionar a tool `desqualificado`" e "@Transferência: Período de Graça" como "pergunta 1";
- mandava "Nunca aceitar apenas o ano / refazer até obter mês e ano", o que contraria a regra fixa de datas
  aproximadas;
- o PG enviava o áudio do Closer.

**O que mudou:** passa a ser o PG enxuto do Sousa e Costa. Três perguntas: última carteira assinada, seguro-desemprego
e, se faltar, a data do acidente. O RESULTADO usa @Comercial, @Desqualificado e @Análise da equipe. As contas ficam
com o motor.

### Closer
**Fora do padrão:**
- "diga que pelo que ele contou o caso é bom e **há boas chances**" (o motor barra "boas chances");
- "✅ Atendimento simples e **100%** online", "Processo seguro e **estratégico**";
- "@Agente Coleta de Dados" + "@Transferência: Coleta de Dados" + "Quando o lead enviar o nome completo:", que estava
  cortado no fim;
- marcadores com barra invertida (`\[\[audio: …\]\]`);
- nenhuma regra para "não sei" no aceite (o portão de Contratos exige `aceite_honorarios = sim`).

**O que mudou:**
- "há boas chances" → "Não diga que o caso é bom nem fale em chances."
- "100% online" → "Atendimento simples, todo online."; "estratégico" → "acompanhado de perto"; "Cálculo exato" →
  "Cálculo feito por especialista".
- ETAPA 5: "SIM → @Coleta de Dados". "'Não sei', 'vou ver' ou 'talvez' não é aceite: responda à dúvida e repita a
  pergunta da etapa."
- A objeção do escritório (campo do produto) termina com a pergunta da etapa, e não com a pergunta aberta das objeções
  do produto.
- Informação nova que trava (aposentado, advogado) → @Desqualificado.

**Decisão do dono:** "✅ Você só paga se o benefício for aprovado" e "Pode ter retroativo de até 5 anos" ficaram, como no
Sousa e Costa. Confirme que batem com o contrato.

### Contratos
**Fora do padrão:**
- o OBJETIVO ainda era o do link ("Envie o link `[[LINK_ASSINATURA_CONTRATO]]`… você já assinou?");
- a seção "INTELIGÊNCIA NA COLETA" é a regra fixa do motor;
- "@Buscar CEP", "@ZapSign Documento apenas 1 vez";
- "@Transferência: Assinatura", "**Em alguns segundos você vai receber o link**";
- a ETAPA 4 inteira (`LINK_DOCUMENTOS`, áudio, vídeo, texto em caixa alta, formato literal).

**O que mudou:** passa a ser o Contratos enxuto, com a ordem do Weaver: nome, CPF, estado civil, RG, CEP,
número/complemento, e-mail. Termina em "Perfeito! Estamos gerando o seu contrato." O motor é quem busca o CEP, gera o
contrato e muda a etapa.

**Decisão do dono:** configurar o **Envio do contrato** do agente com os dois marcadores que saíram do prompt
(`[[audio:Como Fazer a Assinatura]]` e `[[audio:Vídeo Como Fazer a Assinatura]]`, que é um vídeo) e com o texto "SUA
DOCUMENTAÇÃO JÁ ESTÁ PRONTA…", se ainda quiser esse texto.

### Assinatura
**Fora do padrão:**
- "**Nataly** conduz o lead" (nome fixo);
- FAQ "Preciso imprimir todas as folhas? → **Sim, é necessário imprimir todas as páginas, assinar e depois enviar a
  foto**", que contradiz a assinatura digital;
- "Envie o link quando o lead pedir" (quem manda o link é o sistema).

**O que mudou:**
- "Sim, é necessário imprimir…" → "Não precisa imprimir nada: a assinatura é feita pelo celular, no próprio link que
  você recebeu."
- Fluxo e FAQ do Assinatura enxuto: código que não chegou em 3 tentativas, depois @Análise da equipe; dado errado →
  @Análise da equipe.
- Informação nova que trava → @Análise da equipe, porque o contrato já existe.
- Saiu "a empresa nem precisa ficar sabendo". Ficou só "não exige afastamento nem impede de continuar trabalhando".

### Desqualificado
**Fora do padrão:**
- `{{Google Meu Negócio}}` (funciona pelo apelido, mas o padrão é `{{LINK AVALIACAO GOOGLE}}`);
- "@Agente SDR";
- `\\n` literal no resumo;
- "**Somos especialistas** em Direito Previdenciário".

**O que mudou:**
- Resumo com a linha [Motivo…] e a lista de motivos reais (do Sousa e Costa).
- "Algo mudou → @SDR".
- Avaliação uma vez só e serviços depois da nota.
- "Somos especialistas" → "Atuamos em Direito Previdenciário".

**Decisão do dono (OAB):** usar "especialista" na publicidade pede título de especialização (Provimento 205/2021). Se
o escritório tem o título, pode voltar.

---

## 2. BPC/LOAS Autismo, TDAH e TOD · Mídia (5 agentes)

### SDR
**Fora do padrão:**
- "acionar tools", "tool `BUSCA CONHECIMENTOS`", "Calculadora";
- bloco único de conduta (regra fixa), "REGRA DE FORMATAÇÃO", formato literal;
- "Toda desqualificação exige confirmação";
- a seção APÓS DESQUALIFICAR mandava o SDR explicar o motivo. A regra fixa diz que quem explica é o Desqualificado;
- as faixas de renda se contradiziam: "Faixa 3 — acima de R$ 810,50 → NÃO desqualifique" e "Acima de R$ 1000 →
  @Agente Desqualificado";
- pedia a conta por pessoa ("Somatória − dedução / pessoas"), que bate na regra fixa de não calcular;
- "Atendimento ocorre exclusivamente por mensagens, mas nunca diga isso ao lead".

**O que mudou:**
- Roteiro em 9 perguntas: nome, idade, condição, impacto, laudo, benefício que já recebe, grupo familiar (com o áudio),
  renda por pessoa da casa + CadÚnico, advogado.
- Seção **RENDA** com tabela: até a 1ª coluna segue; entre as colunas pergunta dos gastos (tem → @Análise da equipe;
  não tem → @Desqualificado); acima da 2ª coluna → @Desqualificado. A 1ª coluna é N × R$ 810,50 (meio salário mínimo)
  e a 2ª é N × R$ 1.000, o mesmo corte do original.
- "Recalcule a renda por pessoa com a Calculadora" → gastos e casos difíceis vão para @Análise da equipe.
- "Faixa 1 → @Agente Closer" → "DECISÃO (só com a condição ou a idade, o benefício que já recebe, a renda e o advogado
  respondidos) → @Comercial".
- As mensagens de desqualificação (padrão, "já recebe", cuidador) foram para o Desqualificado.

**Decisões do dono:**
- (a) **Gastos com o tratamento**: antes a IA recalculava e qualificava sozinha. Agora vão para a equipe. É mais
  seguro, mas dá mais trabalho humano.
- (b) Os limites e o salário mínimo são de 2026.
- (c) O corte de R$ 1.000 por pessoa é regra do escritório, não da lei.

### Closer
**Fora do padrão:**
- "**Já analisei o caso por aqui**";
- "✔️ **R$ 1.621** todo mês";
- "várias despesas podem ser excluídas — **aumentando as chances de aprovação**";
- "você não vai chegar lá sem saber **o que falar, como agir**";
- "honorários de maneira clara e **irresistível**";
- "Esse contrato é justamente o que **garante a sua segurança**";
- "@Transferência: Coleta de Dados" + "@Agente Coleta de Dados".

**O que mudou:**
- "R$ 1.621 todo mês" → "Um salário mínimo todo mês". O número sai porque vence todo ano.
- "aumentando as chances de aprovação" → "Na análise da renda, alguns gastos com o tratamento podem ser considerados."
- "o que falar, como agir" → "a gente orienta vocês antes da perícia médica e da avaliação social, explicando o que
  levar e como cada etapa funciona."
- "garante a sua segurança" → "O contrato deixa tudo formalizado."
- ETAPA 1 com o áudio logo na primeira resposta. A frase de troca já faz a pergunta "Posso te explicar…?".
- "SIM → @Coleta de Dados".
- "não sei, vou ver ou talvez não é aceite", travas → @Desqualificado e renda nova → @Análise da equipe.

**Decisão do dono (OAB):** a orientação para a perícia deve ser sobre o que levar e como funciona, e não sobre o que
dizer ao perito.

### Contratos
**Fora do padrão:** igual ao Auxílio Acidente:
- link no objetivo;
- "@Buscar o Cep", que nem é o nome do chip;
- "@ZapSign", "Em alguns segundos…", ETAPA 4 com `LINK_DOCUMENTOS`.

A ordem do original começava pela criança, o que é coerente. A frase de troca, porém, pedia "o nome completo **do
criança**". Para o motor, o nome que vai no contrato é o de quem assina; a criança entra nos campos `nome_menor` e
`cpf_menor`.

**O que mudou:**
- Coleta em dois blocos (criança; responsável), com "Esse CPF é o seu ou o dele(a)?" na dúvida.
- CPF da criança que não existe → orienta e segue.
- Adulto ou idoso por si → só os dados dele. Curador → @Análise da equipe.
- Confirmação com os dois blocos e a conferência da grafia do nome da criança.

**Decisão do dono:** o modelo da ZapSign precisa ter as variáveis do menor ("Qual o nome completo do(a) menor?" e
"Qual o CPF do(a) menor?", que fazem parte do mapeamento padrão).

### Assinatura
**Fora do padrão:**
- o mesmo FAQ errado: "**Sim, é necessário imprimir todas as páginas**";
- "Envie o link quando pedir";
- um tópico vazio ("- ").

**O que mudou:**
- FAQ corrigido.
- Fluxo do Assinatura enxuto, adaptado à mãe ou responsável.
- Código e dado errado → @Análise da equipe.
- Laudo e CadÚnico: "a equipe orienta depois da assinatura".

### Desqualificado
**Fora do padrão:**
- "Chame a tool encerramento" (não existe no motor);
- `{{Google Meu Negócio}}`;
- "Somos especialistas";
- `\\n` literal;
- faltava a reabertura do caso: "Algo mudou → @SDR".

**O que mudou:**
- Resumo com a linha [Motivo…]: sem condição, já recebe, cuidador, renda.
- Variante "Que bom que o benefício já está ativo!".
- "Algo mudou, foi cortado ou outra pessoa → @SDR".
- Insistência: 1 resposta e depois a avaliação.
- "Atuamos em Direito Previdenciário".

---

## 3. BPC/LOAS Geral - Idoso (5 agentes)

**Problema geral do original:**
- variáveis fora do padrão: `{{ Nome Atendente }}`, `{{ @instagram }}`,
  `{{ Endereço completo, cidade/UF, CEP }}`, `{{ Link de avaliação do Google }}`, `{{ Video Inicial }}`;
- e variáveis de rascunho nunca preenchidas: `{{ X }}% dos atrasados`, `{{ N }} parcelas`, `{{ Y }}x`,
  `{{ Cole aqui a transcrição do áudio de honorários }}`.

Para o motor, uma linha com variável sem valor **sai inteira**. **"Olá! Me chamo {{ Nome Atendente }}…" sumiria da
abertura**, porque `NOME ATENDENTE` não é um nome conhecido (os conhecidos são `NOME AGENTE` e o apelido
`NOME DO AGENTE`). Três prompts passavam do limite de 12 mil caracteres. Cada agente também tinha seções de ferramentas
do Weaver que o motor não tem ou faz sozinho:
- "Sistema Notificação" com 8 valores;
- REUNIAO, `dados_lead` com JSON, `criardocumento`, `codigozapsing`, `voltarsdr`, `encerramento`;
- "BUSCA CONHECIMENTOS".

### SDR
**O que mudou:**
- `{{ Nome Atendente }}` / `{{ Nome do Escritório }}` → `{{NOME AGENTE}}` / `{{NOME ESCRITORIO}}`.
- `{{ Video Inicial }}` → `[[video:Video Inicial]]`.
- "FICHA DO CASO" e "COMO CONVERSAR" (regra fixa) → perguntas na ordem.
- Mesma seção RENDA e mesma DECISÃO do Autismo.
- A seção "MEMÓRIA DO LEAD — Tool dados_lead" saiu: quem extrai os dados é o motor.
- Saiu o exemplo "Com 65 anos **você já pode ter direito** ao BPC", porque a IA não diz se há direito.
- Os 4 exemplos de conversa saíram (eram 2 mil caracteres). As regras deles ficaram nas perguntas.

### Closer
**Fora do padrão:**
- honorários com `{{ X }}`/`{{ N }}`/`{{ Y }}`;
- "Se o INSS negar, a gente **recorre até a última instância**";
- "**O risco é todo nosso**";
- "Cada mês sem pedir **é um mês que não volta**" em 3 objeções;
- "O maior risco é continuar sem receber um direito seu";
- "Mas desistir agora significa continuar sem uma renda que **é um direito seu**";
- "Nunca use verbos de incerteza";
- tool REUNIAO com texto fixo sobre ligação;
- "@Agente Contrato", um chip que não existe e deixava o Closer sem destino por esse caminho.

**O que mudou:**
- Honorários só pelo áudio `[[audio:honorarios_bpc]]` e pelo bloco HONORÁRIOS do escritório (campo da ativação).
- "recorre até a última instância" → "✅ Acompanhamos cada etapa do pedido."
- "O risco é todo nosso" e "um direito seu" saíram.
- "um mês que não volta" → "Só para você saber: o BPC é pago a partir da data do pedido" (o fato, sem pressão).
- REUNIAO e notificações saíram: o motor percebe sozinho pedido de vídeo, de áudio e de humano.
- "@Agente Contrato" → "@Coleta de Dados".
- Travas → @Desqualificado ou @Análise da equipe.

**Decisões do dono (OAB/contrato):**
- (a) Se o escritório quiser prometer recurso, isso precisa estar no contrato.
- (b) "Você só paga se o benefício for aprovado" tem que bater com o contrato.

### Contratos
**Fora do padrão:**
- **campos que o motor não tem**: data de nascimento, vínculo e representante com estado civil e profissão próprios;
- "BLOQUEIOS ABSOLUTOS" exigia a data de nascimento para gerar o contrato;
- a seção "O que a ferramenta retorna… 'link_contrato'" mandava a IA escrever o link;
- 10 frases de espera ("Já já te mando o link…");
- "@ZapSign" e "@Transferência: Assinatura Envio na mesma execução…".

**O que mudou:**
- O titular é o beneficiário (idoso ou adulto). Criança: quem assina é o responsável e a criança vai nos campos do
  menor. Curador → @Análise da equipe.
- Os dados ficaram nos campos do motor: nome, CPF, RG, estado civil, profissão, CEP, número/complemento, e-mail,
  telefone.
- Travas e "idade não bate com o perfil" → @Análise da equipe.

**Decisão do dono:** **a data de nascimento saiu.** Se o modelo de contrato da ZapSign precisar dela, o motor precisa
de um campo novo (frente do contrato).

### Assinatura
**Fora do padrão:**
- tool `codigozapsing`;
- `{{ Cole aqui o resumo dos honorários… }}`;
- "O risco é todo do escritório";
- "**Quer assinar agora pra garantir?**";
- "Só se preferir assinar no papel: aí é preciso imprimir…";
- `{{ Link ou [[video: como_assinar]] }}`.

**O que mudou:**
- Código não chegou: as 3 tentativas do enxuto, depois @Análise da equipe.
- Honorários "pelos honorários do escritório, sem inventar números".
- "pra garantir" saiu.
- Papel: "Não precisa imprimir nada".
- `[[video:como_assinar]]` sozinho na linha.
- Quem assina: o idoso, mesmo quando o filho ajuda; se não consegue assinar → @Análise da equipe.

### Desqualificado
**O que mudou:**
- "voltarsdr" → @SDR.
- "tool encerramento" saiu.
- `{{ Link de avaliação do Google }}` → `{{LINK AVALIACAO GOOGLE}}`.
- O resumo ganhou a frase [Motivo…].
- Mantidas as variantes "já recebe" e cuidador, a mensagem do advogado, a insistência e o "fora do assunto".

**Decisão do dono:** o original separava "o SDR já explicou o motivo, não repita". Agora quem explica é sempre o
Desqualificado, depois da frase de entrada nova.

---

## 4. Mídias (marcadores sem arquivo, para a Edição rápida de mídias)

Todos estão sozinhos na linha, com a grafia normalizada (`[[audio:Nome]]`, sem espaço e sem barra invertida). Os nomes
são os do Weaver, para a edição rápida achar.

| Produto | Agente | Marcador | Observação |
|---|---|---|---|
| Auxílio Acidente | SDR | `[[audio:Video Inicial]]` | É um vídeo com prefixo de áudio (já era assim); funciona igual |
| Auxílio Acidente | Closer | `[[audio:Como Funciona o Auxílio-Acidente]]` | Saiu do SDR e do PG (era mandado duas vezes) |
| Auxílio Acidente | Closer | `[[audio:Honorários]]` | |
| Autismo | SDR | `[[video:Video Inicial]]` | |
| Autismo | SDR | `[[audio:Explicando Grupo Familiar]]` | |
| Autismo | Closer | `[[audio:Explicando o Beneficio]]` | O SDR também mandava `[[audio:explicando_beneficio]]`, outro nome; saiu do SDR |
| Autismo | Closer | `[[audio:audio_honorarios]]` | |
| Idoso | SDR | `[[video:Video Inicial]]` | Antes era a variável `{{ Video Inicial }}` |
| Idoso | SDR | `[[audio:Explicando Grupo Familiar]]` | |
| Idoso | Closer | `[[audio:explicando_beneficio]]` | Saiu do SDR |
| Idoso | Closer | `[[audio:honorarios_bpc]]` | |
| Idoso | Assinatura | `[[video:como_assinar]]` | Só quando o lead pede o passo a passo |

Saíram dos prompts e vão para o **Envio do contrato** do agente:
- Auxílio Acidente e Autismo: `[[audio:Como Fazer a Assinatura]]` e `[[audio:Vídeo Como Fazer a Assinatura]]`;
- Idoso: `[[midia:assinatura_audio]]` e `[[midia:VIDEO_ASSINATURA]]`.

Também saiu `[[LINK_ASSINATURA_CONTRATO]]`, que não era mídia.

Nas **objeções do produto Autismo**, fora do prompt, há 9 marcadores (`[[audio: objecao_medo]]` e outros) com "Envie
exatamente link:\\" e barras soltas. A "OBJ 5 - Já tentei e negaram" é só o marcador: sem o arquivo, fica vazia.

---

## 5. Campos fora do prompt que precisam de decisão (não mexi)

### 5.1 Regras gerais (`regras_markdown`), Auxílio Acidente e Autismo
O texto atual contradiz o motor e o roteiro (item 2 do resumo). Sugestão para colar no lugar, ou deixar vazio:

```
- Atendimento por WhatsApp; a equipe do escritório acompanha a conversa.
- Linguagem simples, humana, acolhedora e segura, sem juridiquês.
- Pergunta sobre onde fica o escritório: responda com o endereço dos dados do escritório.
- Nunca dê orientação jurídica sobre o caso: quem avalia é o advogado.
```

### 5.2 Objeções do produto (`objecoes`)
- **Auxílio Acidente**: a "OBJ 2 — Distância" oferece "**organizar uma videochamada**" (o motor proíbe oferecer
  ligação ou reunião). Todas terminam com pergunta aberta ("O que exatamente deixou você com mais receio?"); o Closer
  revisado manda trocar pela pergunta da etapa. A "OBJ 9" tem "somente em caso de resultado favorável" (confira com o
  contrato).
- **Autismo**: a mesma "videochamada" na OBJ 2. A OBJ 9 diz "fatores que impactam diretamente no resultado". Duas
  objeções se chamam "OBJ 4". Os marcadores trazem `\\` soltos.
- **Idoso**: não tem objeções no produto. As do Closer ficaram no prompt.

### 5.3 Dados do escritório (`dados_escritorio`)
- Auxílio Acidente e Autismo usam `{{SITE ESCRITÓRIO}}`, `{{CNPJ}}`, `{{Endereço}}`, `{{E-mail}}`, `{{Telefone}}`,
  `{{Google Meu Negócio}}`, `{{Canal no YouTube}}` e `{{Site oficial do escritório}}`. O primeiro rótulo é
  "Escritório: {{SITE ESCRITÓRIO}}", talvez um erro (deveria ser `{{NOME ESCRITORIO}}`).
- O Autismo ainda traz uma "Regra de endereço" que contradiz a regra geral ("priorize o endereço físico").
- **Idoso**: vazio. Sugestão: o mesmo bloco dos outros dois, mais `{{Instagram}}`.

### 5.4 Variáveis que o produto usa (para preencher com os dados da empresa da Helena)
- **Nos prompts revisados** (os 3 produtos): `{{NOME AGENTE}}`, `{{NOME ESCRITORIO}}` e `{{LINK AVALIACAO GOOGLE}}`
  (só no Desqualificado). Os honorários entram pelo campo Honorários da ativação, sem variável no texto.
- **Nos dados do escritório** (Auxílio Acidente e Autismo): `SITE ESCRITORIO`, `CNPJ`, `ENDERECO`, `E-MAIL`,
  `TELEFONE`, `GOOGLE MEU NEGOCIO` (que é o mesmo que `LINK AVALIACAO GOOGLE`), `CANAL NO YOUTUBE` e
  `SITE OFICIAL DO ESCRITORIO`. Os nomes aparecem como o motor os lê: sem acento e em maiúsculas.
- **Na boas-vindas do produto Auxílio Acidente**: `{{escritorio}}` não é variável conhecida, e a linha sairia
  inteira. Use `{{NOME ESCRITORIO}}`.
- Variável sem valor tira a linha inteira e grava o evento "Campo {{X}} sem valor".

### 5.5 Campos de modelo nos agentes do Auxílio Acidente
- `mensagem_boas_vindas` dos 6 agentes: item 1 do resumo. **Limpar.**
- `faq` e `regras_gerais` (`config_modelo.faq_items` e `rules_markdown`) são texto de modelo de tela. Exemplos:
  - "Atendemos 100% online";
  - "Após a triagem o especialista te dá uma estimativa realista";
  - "Sempre envie o contrato em PDF";
  - "Aguarde 10 minutos antes de cobrar assinatura";
  - "indique Defensoria, OAB, outro escritório parceiro";
  - "Se o cliente enviar áudio, agradeça e responda por texto".

  Não achei uso deles pelo motor em produção, mas o editor do admin os mostra. Sugiro limpar.
- `regras_handoff` (palavras-chave como "não tenho" → desqualificado; "vou pensar" → follow_up): o motor não usa, mas o
  **Teste de prompt do painel** usa (`ProductConfigurator.tsx`, linhas 1208 a 1244). O teste pode mostrar trocas que
  em produção não acontecem. Sugiro limpar nos 3 produtos.

---

## 6. Frases de troca (mensagem de entrada de cada agente)

| Produto | Destino | Antes | Depois |
|---|---|---|---|
| Auxílio Acidente | Período de Graça | "Agora vou confirmar algumas informações importantes sobre seu vínculo com o INSS, tudo bem?" | igual |
| Auxílio Acidente | Comercial (closer) | "Maravilha! Nós podemos te ajudar no seu caso." | + " Posso te explicar como funciona o Auxílio-Acidente?" (a pergunta que o SDR mandava separada; o Closer abre com o áudio) |
| Auxílio Acidente | Coleta de Dados | "Excelente! Por gentileza, me informe seu nome completo…" | igual |
| Auxílio Acidente | Assinatura | "Perfeito! Estamos gerando o seu contrato." | igual (quem muda a etapa é o sistema, depois do contrato) |
| Auxílio Acidente | **Desqualificado** | (não havia) | **nova:** "Analisei com atenção o que você me contou e, neste momento, não vamos conseguir seguir com esse pedido de Auxílio-Acidente. Sei que não é a resposta que você esperava." |
| Autismo | Comercial | "Maravilha! Nesse caso, conseguimos ajudar sim! 😊 **Vou passar o caso do seu filho(a) para o nosso time** dar sequência e **agilizar o benefício**, tá bom?" | "Maravilha! Pelo que você me contou, o escritório pode cuidar desse caso. 😊 Posso te explicar como funciona o BPC/LOAS?" (a regra fixa proíbe dizer que vai passar para outro setor; "agilizar" era promessa de prazo) |
| Autismo | Coleta de Dados | "…me informe por gentileza o nome completo **do criança**." | "Perfeito! Vou te pedir alguns dados para a formalização. Para começar, me informe por gentileza o seu nome completo." (quem assina é a mãe; a criança vem depois, nos campos do menor) |
| Autismo | Assinatura | "Perfeito! Estamos gerando o seu contrato." | igual |
| Autismo | **Desqualificado** | (não havia) | **nova:** "…não vamos conseguir seguir com esse pedido do BPC. Sei que não é a resposta que você esperava." |
| Idoso | Comercial | "Maravilha!! Nós podemos ajudar no seu caso." | "Maravilha! Pelo que você me contou, o escritório pode cuidar desse caso. Posso te explicar como funciona o BPC/LOAS?" |
| Idoso | Coleta de Dados | "…Me informe por gentileza o nome completo do beneficiário" | "…Me informe, por gentileza, o nome completo de quem vai assinar o contrato." (para a criança, quem assina é o responsável) |
| Idoso | Assinatura | "Perfeito! Estamos gerando o seu contrato." | igual |
| Idoso | **Desqualificado** | (não havia) | **nova**, igual à do Autismo |

**Por que a frase do Desqualificado:** a regra fixa `REGRA_DESQUALIFICAR` manda quem passa o lead **não** explicar o
motivo ("a mensagem de entrada do destino já diz o necessário"). Sem frase, o lead ficava sem nenhuma explicação até o
Desqualificado falar. A frase é neutra para servir também ao caso do advogado. **Decisão do dono:** o texto.

Os destinos que o motor lê em cada prompt revisado (`ferramentas_do_prompt`):

| Agente | Auxílio Acidente | Autismo | Idoso |
|---|---|---|---|
| SDR | Período de Graça, Comercial, Desqualificado | Comercial, Desqualificado | Comercial, Desqualificado |
| Período de Graça | Comercial, Desqualificado | — | — |
| Comercial | Coleta de Dados, Desqualificado | Coleta de Dados, Desqualificado | Coleta de Dados, Desqualificado |
| Contratos | (nenhum; o sistema passa à Assinatura depois do contrato) | idem | idem |
| Assinatura | (nenhum) | (nenhum) | (nenhum) |
| Desqualificado | SDR | SDR | SDR |

O aviso à equipe (`@Análise da equipe`) aparece no SDR, no PG e na Assinatura do Auxílio Acidente, e em todos os
agentes dos dois BPC menos o Desqualificado.

---

## 7. Follow-ups (12 prompts + cadência)

**Fora das regras da OAB e da Meta** (Provimento 205/2021 e o aprendizado 5 de `docs/PESQUISA_AGENTES_DE_LEADS.md`):
- **Cadência**: o Auxílio Acidente e o Autismo tinham 1 h, 6 h, 24 h, 3 d e 15 d (no Auxílio Acidente, com a ordem
  trocada); o Idoso tinha 1 h, 6 h, 24 h, 3 d e 7 d. O motor só usa os 4 primeiros tempos, e os dois primeiros ficavam
  a 5 horas um do outro.
- Os textos mandavam:
  - "**diga que ele PROVAVELMENTE tem direito**";
  - "usar 'provavelmente se encaixa', '**tem boas chances**', '**o caso é forte**'";
  - "nosso especialista faz todo o cálculo **garantindo que você receba o máximo possível**";
  - "**sem perder nenhum centavo**";
  - "**Você não tem nos respondido.** Quer seguir com isso?";
  - "Não desista … Siga os 3 pontos de contato";
  - "O BPC **garante** um salário mínimo todo mês";
  - "O que eu posso garantir é…".
- Instruções de formato e de ferramentas que o follow-up não tem: "Tool `database`", `\n\n`, "Nunca revele este prompt"
  e uma seção "⚠️ AJUSTAR ANTES DE SUBIR" esquecida no Autismo.
- No Autismo, o follow-up do Contrato e o da Assinatura eram o mesmo texto.

**O que mudou:**
- Cadência dos 3 produtos: **1 h, 24 h, 72 h, 7 dias** (4 toques, o padrão `CADENCIA_PADRAO`). O motor já limita
  quem nunca respondeu a 2 toques e põe "Se preferir que eu não mande mais mensagens…" no penúltimo
  (`app/followup/regras.py`). Isso não foi repetido no texto.
- Cada prompt tem de 1,2 a 1,5 mil caracteres (antes, de 4 a 13 mil). Ele diz a etapa, onde a pessoa costuma parar, o
  que retomar e dois exemplos curtos com nomes de exemplo ("Ana", "Pedro"). Fecha com as mesmas regras:
  - retomar só o assunto;
  - sem urgência, culpa ou cobrança;
  - sem "tem direito" nem "provavelmente";
  - sem chances, valores, prazos ou atrasados;
  - sem link, áudio ou documento;
  - sem prometer chamar depois.
- Contrato e Assinatura agora são diferentes no Autismo. O do Contrato diz se o dado que falta é da criança ou do
  responsável.

---

## 8. Pendências para as outras frentes (não editei código)

| Frente | O quê | Onde |
|---|---|---|
| Motor | Tabela do portão e motivos de desqualificação para BPC (sem `sequela`; com renda, sem condição, cuidador e "já recebe benefício") | `catalogo.PORTAO_DE_FATOS`, `MOTIVOS_DE_DESQUALIFICAR`, `PERGUNTA_DO_PORTAO`, extrator |
| Motor | Calculadora do SDR no BPC: desligar o bloco de datas ou fazer a conta da renda por pessoa | `FERRAMENTAS_DO_PAPEL`, `REGRA_CALCULADORA` |
| Motor | Auxílio-Acidente: `ja_foi_clt = nao` (MEI que nunca teve carteira) como motivo, se o dono confirmar | `MOTIVOS_DE_DESQUALIFICAR` |
| Contrato | Data de nascimento do titular (BPC Idoso), se o modelo da ZapSign pedir | `app/contrato/dados.py` (`CAMPOS`) |
| Painel | O Teste de prompt usa `regras_handoff` do catálogo (palavras-chave do Weaver) | `ProductConfigurator.tsx` |
| Cadastro | Limpar boas-vindas e FAQ/regras de modelo dos agentes do Auxílio Acidente; revisar regras gerais, objeções e dados do escritório (seção 5) | admin › Produtos |
